import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope
from test_proposals import payload, proposal

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.sessions import SessionResponse
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.state_db import StateDB

ROLES = """default: {role: reader, clearance: public}
groups:
  writers: {role: writer, clearance: internal}
  readers: {role: reader, clearance: restricted}
  reviewers: {role: reviewer, clearance: restricted}
"""


@pytest.fixture
def sessions(config: Settings) -> Iterator[TestClient]:
    config.anonymous_access = True
    config.mcp_http_enabled = True
    config.session_issuer_token_name = "wiki-ui"
    config.roles_file = config.state_dir.parent / "roles.yaml"
    config.roles_file.write_text(ROLES)
    issuer = Auth(StateDB(config.state_dir)).create("wiki-ui", "reader", "public")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = "Bearer " + issuer
        yield client


def issue(
    client: TestClient,
    subject: str = "alice",
    username: str = "Alice",
    groups: list[str] | None = None,
) -> SessionResponse:
    result = client.post(
        "/api/v1/sessions",
        json={
            "subject": subject,
            "username": username,
            "groups": groups or [],
            "kind": "agent",
        },
    )
    assert result.status_code == 200, result.text
    return SessionResponse.model_validate(result.json())


def test_issuer_is_confined_before_body(sessions: TestClient) -> None:
    for method, path in (
        ("GET", "/whoami"),
        ("GET", "/health"),
        ("GET", "/search"),
        ("POST", "/proposals"),
        ("DELETE", "/sessions/current"),
        ("GET", "/sessions"),
    ):
        response = sessions.request(method, "/api/v1" + path)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "E_FORBIDDEN"
    assert sessions.post("/mcp").status_code == 403
    output: list[Message] = []

    async def receive() -> Message:
        pytest.fail("Issuer's forbidden request body read")

    async def send(message: Message) -> None:
        output.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/proposals",
        "headers": [(b"authorization", sessions.headers["Authorization"].encode())],
    }
    assert sessions.portal is not None
    sessions.portal.call(sessions.app, scope, receive, send)
    assert output[0]["status"] == 403
    assert issue(sessions).actor.kind == "human"


def test_display_identity_sanitizing_revocation_and_audit(sessions: TestClient) -> None:
    issuer = sessions.headers["Authorization"]
    first = issue(sessions, username="Alice Smith / человек", groups=["reviewers"])
    second = issue(sessions, username="Alice Smith / человек", groups=["reviewers"])
    state = sessions.app.state.runtime.state
    rows = state.rows("SELECT name,display_name,person FROM tokens WHERE name LIKE 'sso-%'")
    assert len(rows) == 2 and rows[0]["name"] != rows[1]["name"]
    assert rows[0]["display_name"] == rows[1]["display_name"] == first.actor.name
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", first.actor.name)
    assert first.actor.identity == second.actor.identity == "alice"
    assert first.actor.kind == "human"
    sessions.headers["Authorization"] = "Bearer " + first.token
    assert sessions.get("/api/v1/whoami").json()["name"] == first.actor.name
    assert sessions.delete("/api/v1/sessions/current").status_code == 204
    assert sessions.get("/api/v1/whoami").status_code == 401
    sessions.headers["Authorization"] = "Bearer " + second.token
    assert sessions.get("/api/v1/whoami").status_code == 200
    sessions.headers["Authorization"] = issuer
    assert issue(sessions, subject="a@domain", username="юникод").actor.name == "user-a-domain"
    audit = json.dumps(state.rows("SELECT * FROM audit"))
    assert first.token not in audit and second.token not in audit and "reviewers" not in audit
    assert "token.session.create" in audit


def test_group_mapping_and_display_name_cannot_impersonate_issuer(sessions: TestClient) -> None:
    issuer = sessions.headers["Authorization"]
    for groups, role, clearance in (
        (["writers", "readers"], "writer", "restricted"),
        (["unknown"], "reader", "public"),
        ([], "reader", "public"),
    ):
        result = issue(sessions, username="wiki-ui", groups=groups)
        assert (result.actor.role, result.actor.clearance) == (role, clearance)
        sessions.headers["Authorization"] = "Bearer " + result.token
        assert sessions.get("/api/v1/whoami").status_code == 200
        assert sessions.post("/api/v1/sessions", json={"subject": "evil"}).status_code == 403
        sessions.headers["Authorization"] = issuer


def test_identity_and_git_author_stay_stable_across_sessions(
    sessions: TestClient, config: Settings
) -> None:
    alice = issue(sessions, groups=["reviewers"])
    alice_again = issue(sessions, groups=["reviewers"])
    bob = issue(sessions, "bob", "Bob", ["reviewers"])
    for number, reviewer in enumerate((alice, alice_again)):
        sessions.headers["Authorization"] = "Bearer " + bob.token
        pid = proposal(sessions)
        page_id = f"term-session-{number}"
        assert (
            sessions.put(
                f"/api/v1/proposals/{pid}/pages/{page_id}", json=payload(page_id)
            ).status_code
            == 200
        )
        assert sessions.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
        sessions.headers["Authorization"] = "Bearer " + reviewer.token
        result = sessions.post(f"/api/v1/proposals/{pid}/accept")
        assert result.status_code == 200, result.text
        assert result.json()["decided_by"] == "alice"
        assert GitRepo(config.wiki_root).run("log", "-1", "--format=%an") == "Alice"
    own = proposal(sessions)
    assert (
        sessions.put(
            f"/api/v1/proposals/{own}/pages/term-own", json=payload("term-own")
        ).status_code
        == 200
    )
    assert sessions.post(f"/api/v1/proposals/{own}/submit").status_code == 200
    sessions.headers["Authorization"] = "Bearer " + alice.token
    response = sessions.post(f"/api/v1/proposals/{own}/accept")
    assert response.status_code == 403 and response.json()["error"]["code"] == "E_SELF_REVIEW"


def test_expiry_cleanup_and_rate_limits_use_session_keys(sessions: TestClient) -> None:
    first, second = issue(sessions), issue(sessions)
    auth = sessions.app.state.runtime.auth
    auth.rate_limit = 1
    assert auth.authenticate(first.token).name == auth.authenticate(second.token).name
    with pytest.raises(WikiError, match="Превышен"):
        auth.authenticate(first.token)
    state = auth.state
    assert len(state.rows("SELECT * FROM rate_limits WHERE name LIKE 'sso-%'")) == 2
    with state.connect() as db:
        db.execute(
            "UPDATE tokens SET expires_at=? WHERE token_hash=?",
            ("2000-01-01T00:00:00+00:00", hashlib.sha256(first.token.encode()).hexdigest()),
        )
    sessions.headers["Authorization"] = "Bearer " + first.token
    assert sessions.get("/api/v1/whoami").status_code == 401
    auth.expire_sessions()
    assert len(state.rows("SELECT * FROM tokens WHERE name LIKE 'sso-%'")) == 1
    assert state.rows("SELECT * FROM tokens WHERE name='wiki-ui'")


def test_legacy_tokens_and_disabled_sessions(config: Settings) -> None:
    state = StateDB(config.state_dir)
    auth = Auth(state)
    token = auth.create("legacy", "reviewer", "restricted", kind="human")
    assert auth.authenticate(token).name == "legacy"
    assert state.rows("SELECT display_name FROM tokens")[0]["display_name"] is None
    with TestClient(create_app(config)) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.post("/api/v1/sessions", json={"subject": "alice"}).status_code == 404


def test_people_directory_is_internal_paginated_and_tracks_renames(sessions: TestClient) -> None:
    original = issue(sessions, "opaque-alice", "Alice", ["readers"])
    renamed = issue(sessions, "opaque-alice", "Alice.New", ["readers"])
    issue(sessions, "opaque-bob", "Bob", ["writers"])
    public = issue(sessions, "opaque-public", "Public")
    sessions.headers["Authorization"] = "Bearer " + original.token
    first = sessions.get("/api/v1/people", params={"limit": 1})
    assert first.status_code == 200
    assert first.json()["items"][0]["person"] == "opaque-alice"
    assert first.json()["items"][0]["display_name"] == "Alice.New"
    assert first.json()["items"][0]["updated_at"]
    second = sessions.get(
        "/api/v1/people", params={"limit": 1, "cursor": first.json()["next_cursor"]}
    )
    assert second.json()["items"][0]["person"] == "opaque-bob"
    assert len(sessions.get("/api/v1/people").json()["items"]) == 3
    auth = sessions.app.state.runtime.auth
    assert auth.authenticate(original.token).identity == auth.authenticate(renamed.token).identity
    assert auth.authenticate(original.token).name == "Alice"
    sessions.headers["Authorization"] = "Bearer " + public.token
    assert sessions.get("/api/v1/people").status_code == 403
    del sessions.headers["Authorization"]
    assert sessions.get("/api/v1/people").status_code == 200


@pytest.mark.parametrize("content", [None, "broken: [", "groups: {evil: {role: superuser}}"])
def test_bad_role_file_fails_at_startup(
    config: Settings, tmp_path: Path, content: str | None
) -> None:
    config.session_issuer_token_name = "wiki-ui"
    config.roles_file = tmp_path / "roles.yaml"
    if content is not None:
        config.roles_file.write_text(content)
    with pytest.raises(ValueError, match="ROLES_FILE"), TestClient(create_app(config)):
        pytest.fail("Invalid roles configuration started")


def test_token_migration_keeps_legacy_identity_and_credential(tmp_path: Path) -> None:
    token = "previously-issued-secret"
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.execute(
            "CREATE TABLE tokens(token_hash TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, "
            "role TEXT NOT NULL, clearance TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT)"
        )
        db.execute(
            "INSERT INTO tokens VALUES (?,?,?,?,?,NULL)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                "legacy",
                "reader",
                "public",
                "2020-01-01",
            ),
        )
    state = StateDB(tmp_path)
    assert state.rows("SELECT display_name FROM tokens") == [{"display_name": None}]
    assert Auth(state).authenticate(token).identity == "legacy"
