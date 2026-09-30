import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send
from test_proposals import payload, proposal, reviewer

from wikisvc.config import Settings
from wikisvc.domain.secrets import secret_kinds
from wikisvc.main import BodyLimit
from wikisvc.storage.state_db import StateDB


@pytest.mark.parametrize(
    "secret",
    [
        "<AKIAIOSFODNN7EXAMPLE>",
        "<ghp_" + "a1" * 20 + ">",
        "${AKIAIOSFODNN7EXAMPLE}",
        "password: <sensitive12345>",
        "postgres://app:pass@host/db",
        "Authorization: Bearer opaque-example-token",
        '"token": "<sensitive12345>"',
    ],
)
def test_secrets_in_wrappers_and_context(secret: str) -> None:
    assert secret_kinds(secret)


@pytest.mark.parametrize("size", [32, 40, 64])
def test_hashes_are_safe_except_in_credential_context(size: int) -> None:
    digest = hashlib.sha256(b"hash regression test").hexdigest()[:size]
    assert not secret_kinds("Commit/checksum: " + digest)
    assert secret_kinds("password=" + digest)
    assert secret_kinds("Bearer " + digest)


def test_secrets_and_hashes_through_api(client: TestClient, config: Settings) -> None:
    digest = hashlib.sha256(b"ingested document").hexdigest()
    response = client.post(
        "/api/v1/proposals", json={"title": "Ingest source", "description": digest}
    )
    assert response.status_code == 200
    pid = response.json()["pid"]
    assert (
        client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload(text=digest)).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/proposals",
            json={"title": "Unsafe source", "description": "<AKIAIOSFODNN7EXAMPLE>"},
        ).json()["error"]["code"]
        == "E_SECRET_DETECTED"
    )
    assert (
        client.put(
            f"/api/v1/proposals/{pid}/pages/term-new", json=payload(text="<AKIAIOSFODNN7EXAMPLE>")
        ).json()["error"]["code"]
        == "E_SECRET_DETECTED"
    )
    client.post(f"/api/v1/proposals/{pid}/submit")
    reviewer(client, config)
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/request-changes",
            json={"comment": "Bearer opaque-example-token"},
        ).json()["error"]["code"]
        == "E_SECRET_DETECTED"
    )
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/request-changes", json={"comment": digest}
        ).status_code
        == 200
    )


def test_downgrade_warning_and_all_editors_cannot_accept(
    client: TestClient, config: Settings
) -> None:
    author_token = client.headers["Authorization"]
    pid = proposal(client)
    page = client.get("/api/v1/pages/term-orphan").json()
    endpoint = f"/api/v1/proposals/{pid}/pages/term-orphan"
    reviewer(client, config)
    editor_token = client.headers["Authorization"]
    response = client.patch(
        endpoint,
        json={
            "base_version": page["version"],
            "ops": [{"op": "set_field", "field": "sensitivity", "value": "public"}],
        },
    )
    assert response.status_code == 200, response.text
    warnings = client.get(f"/api/v1/proposals/{pid}/validate").json()["warnings"]
    assert "W_SENSITIVITY_DOWNGRADE" in {w["code"] for w in warnings}
    assert (
        client.get(f"/api/v1/proposals/{pid}/diff").json()["pages"][0]["warnings"][0]["code"]
        == "W_SENSITIVITY_DOWNGRADE"
    )
    assert client.get(f"/api/v1/proposals/{pid}").json()["last_editor"] == "reviewer"
    client.headers["Authorization"] = author_token
    assert (
        client.patch(
            endpoint,
            json={
                "base_version": page["version"],
                "ops": [{"op": "set_field", "field": "title", "value": "Изменённый термин"}],
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = editor_token
    denied = client.post(f"/api/v1/proposals/{pid}/accept")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "E_SELF_REVIEW"
    reviewer(client, config, "independent")
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200


def test_anonymous_requests_do_not_grow_audit(client: TestClient, config: Settings) -> None:
    db = StateDB(config.state_dir)
    before = len(db.rows("SELECT * FROM audit"))
    client.headers.pop("Authorization")
    for _ in range(300):
        assert client.post("/api/v1/proposals", content=b"x" * 2048).status_code == 401
    assert len(db.rows("SELECT * FROM audit")) == before


@pytest.mark.parametrize(
    "authorized,length,status", [(False, 30_000_000, 401), (True, 2_000_000, 413), (True, -1, 400)]
)
def test_auth_and_content_length_checked_without_reading(
    client: TestClient, config: Settings, authorized: bool, length: int, status: int
) -> None:
    rt = client.app.state.runtime
    output: list[Message] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Request reached parser")

    async def receive() -> Message:
        pytest.fail("Request body read before rejection")

    async def send(message: Message) -> None:
        output.append(message)

    headers = [(b"content-length", str(length).encode())]
    if authorized:
        headers.append((b"authorization", client.headers["Authorization"].encode()))
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/proposals",
        "headers": headers,
        "app": SimpleNamespace(state=SimpleNamespace(runtime=rt)),
    }
    asyncio.run(BodyLimit(downstream, config)(scope, receive, send))
    assert output[0]["status"] == status


def test_chunked_request_limit(client: TestClient, config: Settings) -> None:
    messages = iter([{"type": "http.request", "body": b"x" * 600_000, "more_body": True}] * 2)
    statuses: list[int] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Oversized stream reached parser")

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope: Scope = {
        "type": "http",
        "method": "PUT",
        "path": "/api/v1/proposals/test/pages/test",
        "headers": [(b"authorization", client.headers["Authorization"].encode())],
        "app": client.app,
    }
    asyncio.run(BodyLimit(downstream, config)(scope, receive, send))
    assert statuses == [413]


def test_json_size_limit_allows_large_raw_upload(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    assert client.post("/api/v1/proposals", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert (
        client.post(
            "/api/v1/raw",
            files={"file": ("larger.txt", b"x" * (1024 * 1024 + 1))},
            data={"category": "docs"},
        ).status_code
        == 200
    )


def test_deep_json_returns_client_error(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    nested = b"[" * 2000 + b"0" + b"]" * 2000
    assert (
        client.post(
            "/api/v1/raw", files={"file": ("deep.json", nested)}, data={"category": "docs"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/proposals", content=nested, headers={"content-type": "application/json"}
        ).status_code
        == 400
    )


def test_empty_proposal_cannot_submit_or_accept(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    assert (
        client.post(f"/api/v1/proposals/{pid}/submit").json()["error"]["code"] == "E_PROPOSAL_EMPTY"
    )
    with StateDB(config.state_dir).connect() as db:
        db.execute("UPDATE proposals SET status='submitted' WHERE pid=?", (pid,))
    reviewer(client, config)
    assert (
        client.post(f"/api/v1/proposals/{pid}/accept").json()["error"]["code"] == "E_PROPOSAL_EMPTY"
    )
