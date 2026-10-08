import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, get_ident
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, InitializeResult, ListToolsResult, TextContent
from pydantic import ValidationError
from starlette.types import Message, Scope
from typer.testing import CliRunner

from wikisvc.cli import app as cli_app
from wikisvc.config import Settings
from wikisvc.domain.models import Principal
from wikisvc.index.indexer import Indexer
from wikisvc.main import create_app
from wikisvc.mcp_server import _token, checked
from wikisvc.services.auth import Auth
from wikisvc.services.runtime import Runtime
from wikisvc.storage.state_db import StateDB
from wikisvc.tool_contracts import TOOL_PROFILES

FULL_TOOLS = {
    "get_instructions",
    "get_policies",
    "get_rule",
    "rules_related",
    "graph_impact",
    "search",
    "get_page",
    "get_context",
    "neighbors",
    "list_pending_sources",
    "read_source_text",
    "get_outline",
    "read_source_pages",
    "get_page_template",
    "create_proposal",
    "put_page",
    "patch_page",
    "validate_proposal",
    "submit_proposal",
    "lint",
}


@pytest.fixture
def mcp_client(config: Settings) -> Iterator[TestClient]:
    config.mcp_http_enabled = True
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
            "mcp-writer", "writer", "internal"
        )
        yield client


def rpc(
    client: TestClient,
    method: str,
    params: dict[str, object] | None = None,
    *,
    path: str = "/mcp",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    response = client.post(
        path,
        headers={"Accept": "application/json, text/event-stream", **(headers or {})},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
    ]
    assert len(events) == 1 and events[0]["id"] == 1, events
    result: dict[str, object] = events[0]["result"]
    return result


def call(
    client: TestClient,
    name: str,
    arguments: dict[str, object] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> CallToolResult:
    return CallToolResult.model_validate(
        rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, headers=headers)
    )


def error_code(result: CallToolResult) -> str:
    assert result.isError
    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    error = json.loads(text[text.index("{") :])["error"]["code"]
    assert isinstance(error, str)
    return error


@pytest.mark.parametrize("authorization", [None, "", "Basic invalid", "Bearer ", "Bearer invalid"])
def test_http_requires_bearer_token(
    mcp_client: TestClient, authorization: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIKI_TOKEN", mcp_client.headers.pop("Authorization")[7:])
    headers = {"Authorization": authorization} if authorization is not None else {}
    response = mcp_client.post("/mcp", headers=headers, content=b"invalid json")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "E_UNAUTHORIZED"


def test_http_rejects_revoked_token(mcp_client: TestClient, config: Settings) -> None:
    assert call(mcp_client, "get_instructions").isError is False
    Auth(StateDB(config.state_dir)).revoke("mcp-writer")
    response = mcp_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "E_UNAUTHORIZED"


@pytest.mark.parametrize("profile", TOOL_PROFILES)
def test_http_profile_and_lifespan(config: Settings, profile: str) -> None:
    config.mcp_http_enabled = True
    config.mcp_profile = profile
    token = Auth(StateDB(config.state_dir)).create("profile-reader", "reader", "internal")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = "bEaReR " + token
        initialized = InitializeResult.model_validate(
            rpc(
                client,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            )
        )
        assert initialized.serverInfo.name == "wikisvc"
        listed = ListToolsResult.model_validate(rpc(client, "tools/list"))
        names = [tool.name for tool in listed.tools]
        expected = set(TOOL_PROFILES[profile]) or FULL_TOOLS
        assert set(names) == expected and len(names) == len(expected)
        assert "get_instructions" in names
        assert call(client, "get_instructions").isError is False
        if profile == "coding":
            assert call(client, "lint").isError


@pytest.mark.parametrize("use_profile", [True, False])
def test_http_policies_match_rest(mcp_client: TestClient, use_profile: bool) -> None:
    arguments: dict[str, object] = {"budget_tokens": 800, "explain": True}
    params: dict[str, str | int | bool] = {"budget_tokens": 800, "explain": True}
    if use_profile:
        arguments["profile"] = params["profile"] = "python-fastapi"
    else:
        arguments["scopes"] = ["lang:python", "framework:fastapi"]
        params["scopes"] = "lang:python,framework:fastapi"
    response = mcp_client.get(
        "/api/v1/policies/compile",
        params=params,
    )
    assert response.status_code == 200
    result = call(mcp_client, "get_policies", arguments)
    assert not result.isError
    assert result.structuredContent == response.json()


def test_http_reader_cannot_create_proposal(mcp_client: TestClient, config: Settings) -> None:
    token = Auth(StateDB(config.state_dir)).create("reader", "reader", "internal")
    result = call(
        mcp_client,
        "create_proposal",
        {"title": "Denied"},
        headers={"Authorization": "Bearer " + token},
    )
    assert error_code(result) == "E_FORBIDDEN"


def test_http_request_principals_are_isolated(
    mcp_client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = Auth(StateDB(config.state_dir))
    first = mcp_client.headers["Authorization"]
    second = "Bearer " + auth.create("other-writer", "writer", "internal")
    monkeypatch.setenv("WIKI_TOKEN", auth.create("environment", "writer", "restricted"))
    for authorization, author in [
        (first, "mcp-writer"),
        (second, "other-writer"),
        (first, "mcp-writer"),
    ]:
        result = call(
            mcp_client,
            "create_proposal",
            {"title": "Request identity"},
            headers={"Authorization": authorization},
        )
        assert not result.isError
        assert result.structuredContent is not None
        assert result.structuredContent["author"] == author


def test_http_clearance_isolation(mcp_client: TestClient, config: Settings) -> None:
    restricted = Auth(StateDB(config.state_dir)).create("restricted", "reader", "restricted")
    visible = call(
        mcp_client,
        "get_page",
        {"id": "sys-restricted"},
        headers={"Authorization": "Bearer " + restricted},
    )
    assert not visible.isError and "TOPSECRET_RESTRICTED" in visible.model_dump_json()
    assert mcp_client.get("/api/v1/pages/sys-restricted").status_code == 404
    assert error_code(call(mcp_client, "get_page", {"id": "sys-restricted"})) == "E_NOT_FOUND"
    assert error_code(call(mcp_client, "get_context", {"id": "sys-restricted"})) == "E_NOT_FOUND"
    result = call(mcp_client, "search", {"q": "TOPSECRET_RESTRICTED", "expand": True})
    assert not result.isError
    assert result.structuredContent is not None and result.structuredContent["results"] == []


def test_http_disabled_by_default(config: Settings) -> None:
    assert not config.mcp_http_enabled
    with TestClient(create_app(config)) as client:
        assert client.post("/mcp").status_code == 404
        assert client.get("/api/v1/health").status_code == 200


def test_http_custom_path(config: Settings) -> None:
    config.mcp_http_enabled = True
    config.mcp_http_path = "/integrations/wiki"
    token = Auth(StateDB(config.state_dir)).create("custom", "reader", "internal")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = "Bearer " + token
        for path in ("/integrations/wiki", "/integrations/wiki/"):
            result = ListToolsResult.model_validate(rpc(client, "tools/list", path=path))
            assert {tool.name for tool in result.tools} == set(TOOL_PROFILES["coding"])
        assert client.post("/mcp").status_code == 404
        assert client.post("/integrations/wikipedia").status_code == 404


def test_http_reuses_runtime_and_restarts_lifespan(config: Settings) -> None:
    config.mcp_http_enabled = True
    token = Auth(StateDB(config.state_dir)).create("shared", "reader", "internal")
    app = create_app(config)
    with (
        patch("wikisvc.main.Runtime", wraps=Runtime) as runtime_factory,
        patch.object(Indexer, "reindex", autospec=True, side_effect=Indexer.reindex) as reindex,
    ):
        for starts in (1, 2):
            with TestClient(app, base_url="http://127.0.0.1:8787") as client:
                client.headers["Authorization"] = "Bearer " + token
                assert client.get("/api/v1/health").status_code == 200
                for _ in range(2):
                    assert not call(client, "get_instructions").isError
                assert runtime_factory.call_count == starts
                assert reindex.call_count == starts


def test_http_unknown_profile_fails_at_startup(config: Settings) -> None:
    config.mcp_http_enabled = True
    config.mcp_profile = "missing"
    with pytest.raises(ValueError, match="Unknown MCP profile"), TestClient(create_app(config)):
        pytest.fail("Unknown profile started successfully")


@pytest.mark.parametrize(
    "authorized,length,status,code",
    [
        (False, 2_000_000, 401, "E_UNAUTHORIZED"),
        (True, 2_000_000, 413, "E_BODY_TOO_LARGE"),
        (True, -1, 400, "E_REQUEST_INVALID"),
    ],
)
def test_http_auth_precedes_body_read(
    mcp_client: TestClient, authorized: bool, length: int, status: int, code: str
) -> None:
    output: list[Message] = []

    async def receive() -> Message:
        pytest.fail("Request body read before rejection")

    async def send(message: Message) -> None:
        output.append(message)

    headers = [(b"content-length", str(length).encode())]
    if authorized:
        headers.append((b"authorization", mcp_client.headers["Authorization"].encode()))
    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}

    async def request() -> None:
        assert _token.get() is None
        await mcp_client.app(scope, receive, send)
        assert _token.get() is None

    assert mcp_client.portal is not None
    mcp_client.portal.call(request)
    assert output[0]["status"] == status
    assert json.loads(output[1]["body"])["error"]["code"] == code


def test_http_chunked_body_limit(mcp_client: TestClient) -> None:
    messages = iter([{"type": "http.request", "body": b"x" * 600_000, "more_body": True}] * 2)
    output: list[Message] = []

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        output.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", mcp_client.headers["Authorization"].encode())],
    }
    assert mcp_client.portal is not None
    mcp_client.portal.call(mcp_client.app, scope, receive, send)
    assert output[0]["status"] == 413
    assert json.loads(output[1]["body"])["error"]["code"] == "E_BODY_TOO_LARGE"


def test_http_concurrent_principals(
    mcp_client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = Auth(StateDB(config.state_dir))
    second = auth.create("other-reader", "reader", "restricted")
    runtime: Runtime = mcp_client.app.state.runtime
    authenticate = runtime.auth.authenticate
    barrier = Barrier(2, timeout=10)

    def synchronized_authenticate(token: str) -> Principal:
        principal = authenticate(token)
        barrier.wait()
        return principal

    monkeypatch.setattr(runtime.auth, "authenticate", synchronized_authenticate)

    def read(authorization: str) -> CallToolResult:
        return call(
            mcp_client,
            "get_page",
            {"id": "sys-restricted"},
            headers={"Authorization": authorization},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        internal, restricted = list(
            pool.map(read, [mcp_client.headers["Authorization"], "Bearer " + second])
        )
    assert error_code(internal) == "E_NOT_FOUND"
    assert not restricted.isError
    assert "TOPSECRET_RESTRICTED" in restricted.model_dump_json()


def test_mcp_environment_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HTTP_ENABLED", "true")
    monkeypatch.setenv("MCP_HTTP_PATH", "/remote/mcp")
    monkeypatch.setenv("MCP_PROFILE", "full")
    config = Settings(
        wiki_root=tmp_path / "wiki", state_dir=tmp_path / "state", index_dir=tmp_path / "index"
    )
    assert config.mcp_http_enabled
    assert config.mcp_http_path == "/remote/mcp"
    assert config.mcp_profile == "full"
    monkeypatch.setenv("MCP_HTTP_PATH", "relative")
    with pytest.raises(ValidationError):
        Settings(
            wiki_root=tmp_path / "wiki", state_dir=tmp_path / "state", index_dir=tmp_path / "index"
        )


def test_tools_run_outside_event_loop() -> None:
    event_loop_thread = get_ident()

    @checked
    def thread_id() -> int:
        return get_ident()

    assert asyncio.run(thread_id()) != event_loop_thread


@pytest.mark.parametrize("arguments,expected", [([], "full"), (["--profile", "coding"], "coding")])
def test_stdio_profile_option(
    config: Settings, monkeypatch: pytest.MonkeyPatch, arguments: list[str], expected: str
) -> None:
    for name in ("wiki_root", "state_dir", "index_dir"):
        monkeypatch.setenv(name.upper(), str(getattr(config, name)))
    profiles: list[str] = []

    class Server:
        def run(self, transport: str) -> None:
            assert transport == "stdio"

    def server(runtime: Runtime, profile: str = "full") -> Server:
        profiles.append(profile)
        return Server()

    monkeypatch.setattr("wikisvc.mcp_server.create_server", server)
    result = CliRunner().invoke(cli_app, ["mcp", *arguments])
    assert result.exit_code == 0, result.output
    assert profiles == [expected]
