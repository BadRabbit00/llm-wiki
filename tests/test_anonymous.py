import asyncio
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.types import Message, Scope
from test_mcp_http import call, error_code
from test_proposals import payload, proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.domain.markdown import parse
from wikisvc.main import create_app
from wikisvc.mcp_server import create_server
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.state_db import StateDB


@pytest.fixture
def anonymous(config: Settings) -> Iterator[TestClient]:
    config.anonymous_access = True
    config.mcp_http_enabled = True
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        yield client


def test_anonymous_identity_and_strict_credentials(anonymous: TestClient, config: Settings) -> None:
    assert anonymous.get("/api/v1/whoami").json() == {
        "name": "anonymous",
        "person": None,
        "kind": "agent",
        "role": "writer",
        "clearance": "internal",
    }
    auth = Auth(StateDB(config.state_dir))
    revoked = auth.create("revoked", "reader", "public")
    auth.revoke("revoked")
    expired = auth.create("expired", "reader", "public", expires_at="2000-01-01T00:00:00+00:00")
    for header in (
        "",
        "Basic token",
        "Bearer",
        "Bearer wrong",
        "Bearer " + revoked,
        "Bearer " + expired,
    ):
        for path in ("/api/v1/whoami", "/mcp"):
            result = anonymous.get(path, headers={"Authorization": header})
            assert result.status_code == 401
            assert result.json()["error"]["code"] == "E_UNAUTHORIZED"
    assert not call(anonymous, "get_instructions").isError
    assert error_code(call(anonymous, "get_page", {"id": "sys-restricted"})) == "E_NOT_FOUND"


def test_anonymous_hidden_data_and_decisions(anonymous: TestClient) -> None:
    for path in ("/pages/sys-restricted", "/context/sys-restricted"):
        assert anonymous.get("/api/v1" + path).status_code == 404
    for path in ("/search?q=TOPSECRET_RESTRICTED&expand=true", "/graph/export"):
        result = anonymous.get("/api/v1" + path)
        assert result.status_code == 200
        if path.startswith("/search"):
            assert result.json()["results"] == []
        assert "sys-restricted" not in result.text
    for path in (
        "/proposals/missing/accept",
        "/proposals/missing/revert",
        "/rules/missing/promote",
        "/rules/missing/deprecate",
        "/findings/missing/dismiss",
    ):
        response = anonymous.post("/api/v1" + path, json={})
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "E_FORBIDDEN"
    assert anonymous.get("/api/v1/raw/raw/docs/example.txt/text").status_code == 404
    assert (
        anonymous.post(
            "/api/v1/raw", data={"category": "docs"}, files={"file": ("test.txt", b"test")}
        ).status_code
        == 404
    )


def test_anonymous_proposal_review_and_candidate_defaults(
    anonymous: TestClient, config: Settings
) -> None:
    pid = proposal(anonymous, "New policy rule")
    # The anonymous agent tries to ship a binding rule; the service must make it inert.
    forged = rule(
        anonymous.app.state.runtime.registry,
        sources=["src-example-1"],
        lifecycle="active",
        level="must",
        priority=1,
        owner="role-example-1",
    )
    sent = forged.frontmatter.model_dump(mode="json")
    assert (sent["lifecycle"], sent["level"], sent["priority"], sent["owner"]) == (
        "active",
        "must",
        1,
        "role-example-1",
    )
    stored = anonymous.put(
        f"/api/v1/proposals/{pid}/pages/{forged.id}",
        json={"frontmatter": sent, "body_md": forged.body_md},
    )
    assert stored.status_code == 200, stored.text
    changed = anonymous.get(f"/api/v1/proposals/{pid}/diff").json()["pages"][0]
    assert changed["id"] == "rule-logging"
    assert anonymous.get(f"/api/v1/proposals/{pid}/validate").json()["errors"] == []
    assert anonymous.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    reviewer(anonymous, config, "human-reviewer")
    response = anonymous.post(f"/api/v1/proposals/{pid}/accept")
    assert response.status_code == 200, response.text
    accepted = anonymous.get("/api/v1/rules/rule-logging").json()
    assert (
        accepted["lifecycle"],
        accepted["level"],
        accepted["priority"],
        accepted.get("owner"),
    ) == ("candidate", "should", 3, None)
    on_main, _ = parse(GitRepo(config.wiki_root).run("show", "main:wiki/rules/logging.md"))
    assert (on_main["lifecycle"], on_main["level"], on_main["priority"]) == (
        "candidate",
        "should",
        3,
    )
    assert on_main.get("owner") is None
    assert GitRepo(config.wiki_root).run("log", "-1", "--format=%an") == "human-reviewer"


@pytest.mark.parametrize(
    "setting,value",
    [
        ("anonymous_role", "admin"),
        ("anonymous_role", "reviewer"),
        ("anonymous_clearance", "restricted"),
        ("anonymous_name", "bad\nname"),
    ],
)
def test_anonymous_settings_ceiling(config: Settings, setting: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({**config.model_dump(), setting: value})


def test_anonymous_can_be_reduced_to_public_reader(config: Settings) -> None:
    config.anonymous_access = True
    config.anonymous_role = "reader"
    config.anonymous_clearance = "public"
    with TestClient(create_app(config)) as client:
        assert client.get("/api/v1/whoami").json()["clearance"] == "public"
        hidden = client.get("/api/v1/pages/app-example-1")
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "E_NOT_FOUND"
        denied = client.post("/api/v1/proposals", json={"title": "Forbidden"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "E_FORBIDDEN"
    assert StateDB(config.state_dir).rows("SELECT pid FROM proposals") == []


def test_bad_credential_rejected_before_body(anonymous: TestClient) -> None:
    async def receive() -> Message:
        pytest.fail("Body read before authentication")

    output: list[Message] = []

    async def send(message: Message) -> None:
        output.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/proposals",
        "headers": [(b"authorization", b"Bearer wrong"), (b"content-length", b"2000000")],
    }
    assert anonymous.portal is not None
    anonymous.portal.call(anonymous.app, scope, receive, send)
    assert output[0]["status"] == 401
    assert json.loads(output[1]["body"])["error"]["code"] == "E_UNAUTHORIZED"


def test_stdio_anonymous_does_not_fallback_from_bad_token(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WIKI_TOKEN", raising=False)
    server = create_server(anonymous.app.state.runtime)
    result = asyncio.run(server.call_tool("get_instructions", {}))
    assert result
    monkeypatch.setenv("WIKI_TOKEN", "bad")
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="E_UNAUTHORIZED"):
        asyncio.run(server.call_tool("get_instructions", {}))


def test_anonymous_disabled_still_requires_credentials(config: Settings) -> None:
    with TestClient(create_app(config)) as client:
        for response in (
            client.get("/api/v1/whoami"),
            client.post("/api/v1/proposals", json={"title": "No token"}),
        ):
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "E_UNAUTHORIZED"
    assert StateDB(config.state_dir).rows("SELECT pid FROM proposals") == []


def test_anonymous_shares_proposal_ownership(anonymous: TestClient) -> None:
    pid = proposal(anonymous)
    assert (
        anonymous.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
    )
    assert anonymous.post(f"/api/v1/proposals/{pid}/abandon").status_code == 200
