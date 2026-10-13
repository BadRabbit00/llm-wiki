"""Negative tests for the system boundaries in AGENTS.md (issue #12).

Every test uses real principals created through Auth, real HTTP or MCP calls and checks the
resulting state: proposal status, finding status, git branches and agent jobs.
"""

import ast
import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from agent_helpers import agent_config, tokens, wiki_client
from conftest import make_page
from fake_llm import FakeLLM
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent
from starlette.types import Message, Scope
from test_agent_heal import seed_heal
from test_library_extract import extract, library
from test_mcp_http import call
from test_proposals import payload, proposal
from test_review_policy import candidate
from test_rules_domain import rule

import wikisvc
from wikiagent.api import create_app as create_agent_app
from wikiagent.chat.loop import Chat
from wikiagent.client import WikiClient
from wikiagent.config import AgentConfig
from wikiagent.heal.run import Healer
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikiagent.tools import execute
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import parse
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB

API = "/api/v1"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


def auth(client: TestClient) -> Auth:
    return Auth(client.app.state.runtime.state)


@pytest.fixture
def service(config: Settings) -> Iterator[TestClient]:
    """wikisvc with every MCP tool over HTTP; in-process ASGI, no socket is opened."""
    config.mcp_http_enabled = True
    config.mcp_profile = "full"
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        yield client


def tool_result(result: CallToolResult) -> dict[str, Any]:
    assert not result.isError, result
    if result.structuredContent is not None:
        return dict(result.structuredContent)
    assert isinstance(result.content[0], TextContent)
    return dict(json.loads(result.content[0].text))


def tool_error(result: CallToolResult) -> str:
    assert result.isError
    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    return str(json.loads(text[text.index("{") :])["error"]["code"])


# В1. Every decision requires a human token, whatever role an agent token has.

FINDING = {
    "kind": "duplicate",
    "pages": ["rule-stack-example-1"],
    "summary": "Дублирующее правило",
    "evidence": [{"page": "rule-stack-example-1", "quote": "Описание счетов"}],
}

Decision = tuple[str, dict[str, str] | None, Callable[[], object]]


def decision(client: TestClient, config: Settings, endpoint: str) -> Decision:
    """Bring a real object into the state the decision applies to; return path, body, state."""
    state = StateDB(config.state_dir)
    repo = GitRepo(config.wiki_root)
    if endpoint in ("accept", "reject", "request-changes", "revert"):
        pid = candidate(client)
        assert client.post(f"{API}/proposals/{pid}/submit").status_code == 200
        if endpoint == "revert":
            acceptor = auth(client).create("acceptor", "reviewer", "restricted", kind="human")
            response = client.post(f"{API}/proposals/{pid}/accept", headers=bearer(acceptor))
            assert response.status_code == 200, response.text
        body = {
            "reject": {"reason": "Не подтверждено источником."},
            "request-changes": {"comment": "Уточнить источник."},
        }.get(endpoint)

        def proposal_state() -> object:
            row = state.rows("SELECT status,decided_by FROM proposals WHERE pid=?", (pid,))
            return repo.head(), row

        return f"/proposals/{pid}/{endpoint}", body, proposal_state
    if endpoint in ("dismiss", "reopen"):
        finding = client.post(f"{API}/findings", json=FINDING)
        assert finding.status_code == 200, finding.text
        finding_id = finding.json()["id"]
        if endpoint == "reopen":
            closer = auth(client).create("closer", "reviewer", "restricted", kind="human")
            response = client.post(
                f"{API}/findings/{finding_id}/dismiss",
                json={"reason": "Разные области."},
                headers=bearer(closer),
            )
            assert response.status_code == 200, response.text

        def finding_state() -> object:
            return state.rows("SELECT status,reason FROM findings WHERE id=?", (finding_id,))

        body = {"reason": "Разные области."} if endpoint == "dismiss" else None
        return f"/findings/{finding_id}/{endpoint}", body, finding_state
    page_id = "term-orphan" if endpoint in ("verify", "mark-outdated") else "rule-stack-example-1"
    prefix = "/pages/" if endpoint in ("verify", "mark-outdated") else "/rules/"
    body = {
        "mark-outdated": {"reason": "Изменилась система."},
        "promote": {"level": "should"},
        "deprecate": {"reason": "Заменено решением команды."},
    }.get(endpoint)

    def page_state() -> object:
        page = client.get(f"{API}/pages/{page_id}").json()
        return repo.head(), page["version"], page["status"], page.get("lifecycle")

    return prefix + page_id + "/" + endpoint, body, page_state


DECISIONS = [
    "reject",
    "request-changes",
    "dismiss",
    "reopen",
    "verify",
    "mark-outdated",
    "deprecate",
    "promote",
    "accept",
    "revert",
]


@pytest.mark.parametrize("role", ["reviewer", "admin"])
@pytest.mark.parametrize("endpoint", DECISIONS)
def test_agent_token_cannot_decide(
    client: TestClient, config: Settings, endpoint: str, role: Literal["reviewer", "admin"]
) -> None:
    path, body, state = decision(client, config, endpoint)
    agent = auth(client).create("agent-" + role, role, "restricted", kind="agent")
    before = state()
    denied = client.post(API + path, json=body, headers=bearer(agent))
    assert denied.status_code == 403, denied.text
    assert code(denied) == "E_HUMAN_REQUIRED"
    assert state() == before
    # Positive control: the same call by a human reviewer is a real, working route.
    human = auth(client).create("human-decider", "reviewer", "restricted", kind="human")
    allowed = client.post(API + path, json=body, headers=bearer(human))
    assert allowed.status_code == 200, allowed.text
    assert state() != before


# В2. restricted rules never reach an internal principal, cached or not.

SECRET_RULE = "rule-audit-vault"
SECRET_SUMMARY = "Записывай журнал аудита платежей только в закрытое хранилище."


def test_restricted_rule_hidden_from_internal(service: TestClient, config: Settings) -> None:
    rt = service.app.state.runtime
    keys = auth(service)
    secret_writer = keys.create("secret-writer", "writer", "restricted")
    secret_reviewer = keys.create(
        "secret-reviewer", "reviewer", "restricted", person="secret-reviewer", kind="human"
    )
    internal_writer = keys.create("internal-writer", "writer", "internal")
    internal = keys.create("internal-reviewer", "reviewer", "internal")
    page = make_page(
        rt.registry,
        SECRET_RULE,
        "rule",
        title="Журнал аудита платежей",
        summary=SECRET_SUMMARY,
        sensitivity="restricted",
        category="logging",
        level="should",
        lifecycle="candidate",
        applies_to=["lang:python"],
        origin="team",
        priority=3,
        sources=["src-example-1"],
        aliases=["журнал аудита", "audit log"],
    )
    pid = service.post(
        f"{API}/proposals", json={"title": "Restricted rule"}, headers=bearer(secret_writer)
    ).json()["pid"]
    response = service.put(
        f"{API}/proposals/{pid}/pages/{SECRET_RULE}",
        json={"frontmatter": page.frontmatter.model_dump(mode="json"), "body_md": page.body_md},
        headers=bearer(secret_writer),
    )
    assert response.status_code == 200, response.text
    submitted = service.post(f"{API}/proposals/{pid}/submit", headers=bearer(secret_writer))
    assert submitted.status_code == 200, submitted.text
    accepted = service.post(
        f"{API}/proposals/{pid}/accept",
        json={"promote": [{"id": SECRET_RULE}]},
        headers=bearer(secret_reviewer),
    )
    assert accepted.status_code == 200, accepted.text
    # An internal proposal touching the same scope, for proposal impact.
    open_pid = service.post(
        f"{API}/proposals", json={"title": "Internal rule"}, headers=bearer(internal_writer)
    ).json()["pid"]
    logging_rule = rule(rt.registry, sources=["src-example-1"])
    assert (
        service.put(
            f"{API}/proposals/{open_pid}/pages/{logging_rule.id}",
            json={
                "frontmatter": logging_rule.frontmatter.model_dump(mode="json"),
                "body_md": logging_rule.body_md,
            },
            headers=bearer(internal_writer),
        ).status_code
        == 200
    )

    surfaces: list[tuple[str, dict[str, str], Callable[[dict[str, Any]], set[str]]]] = [
        (
            "/policies/compile",
            {"profile": "python-fastapi"},
            lambda r: {i["id"] for i in r["included"]},
        ),
        ("/rules", {}, lambda r: {i["id"] for i in r["items"]}),
        (
            "/rules/related",
            {"q": "журнал аудита платежей"},
            lambda r: {i["id"] for i in r["rules"]},
        ),
        ("/rules/stats", {}, lambda r: {i["id"] for i in r["items"]}),
        (f"/proposals/{open_pid}/impact", {}, lambda r: {i["id"] for i in r["rules"]}),
    ]
    # The restricted principal runs first and warms the policies cache.
    for path, params, ids in surfaces:
        response = service.get(API + path, params=params, headers=bearer(secret_reviewer))
        assert response.status_code == 200, (path, response.text)
        assert SECRET_RULE in ids(response.json()), path
    for path, params, ids in surfaces:
        response = service.get(API + path, params=params, headers=bearer(internal))
        assert response.status_code == 200, (path, response.text)
        assert SECRET_RULE not in ids(response.json()), path
        assert SECRET_RULE not in response.text and SECRET_SUMMARY not in response.text, path
    # MCP shares the same cache: the internal call follows the restricted HTTP compile.
    policies = tool_result(
        call(service, "get_policies", {"profile": "python-fastapi"}, headers=bearer(internal))
    )
    assert SECRET_RULE not in json.dumps(policies, ensure_ascii=False)
    assert (
        tool_error(call(service, "get_rule", {"id": SECRET_RULE}, headers=bearer(internal)))
        == "E_NOT_FOUND"
    )
    related = tool_result(
        call(service, "rules_related", {"q": "журнал аудита платежей"}, headers=bearer(internal))
    )
    assert SECRET_RULE not in json.dumps(related, ensure_ascii=False)
    control = tool_result(
        call(
            service, "get_policies", {"profile": "python-fastapi"}, headers=bearer(secret_reviewer)
        )
    )
    assert SECRET_RULE in {i["id"] for i in control["included"]}


# В3. Jobs of other people are invisible in wikiagent.


def wait_job(state: AgentState, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        row = state.rows("SELECT * FROM jobs WHERE id=?", (job_id,))[0]
        if row["status"] not in ("pending", "running", "waiting_chat"):
            return row
        time.sleep(0.02)
    raise AssertionError("Job did not stop: " + job_id)


def test_foreign_jobs_are_invisible(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = auth(client)
    agent = keys.create("heal-agent", "writer", "internal", person="heal-agent")
    alice = keys.create("alice-desk", "writer", "restricted", person="alice", kind="human")
    # The same person with a lower clearance: the owner check passes, clearance does not.
    alice_low = keys.create("alice-laptop", "writer", "internal", person="alice", kind="human")
    bob = keys.create("bob-desk", "writer", "restricted", person="bob", kind="human")
    carol = keys.create("carol-desk", "reviewer", "restricted", person="carol", kind="human")
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    wiki = wiki_client(client, settings)
    fake = FakeLLM(
        lambda task, data: {"relation": "none", "confidence": 0.99, "explanation": "Нет проблемы."}
    )
    models = ModelClient(settings, AgentState(settings.state_dir), fake.http)
    app = create_agent_app(settings, wiki, models)
    with TestClient(app) as api:
        state: AgentState = app.state.agent_state
        started = api.post("/jobs/heal", json={"scope": "full"}, headers=bearer(alice))
        assert started.status_code == 202, started.text
        own = started.json()["id"]
        wait_job(state, own)
        # A scheduled heal, started by the idle scheduler inside its window.
        moment = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=2, minute=0)
        scheduled = app.state.scheduler.tick(moment)
        assert scheduled
        wait_job(state, scheduled)

        def visible_ids(token: str) -> set[str]:
            response = api.get("/jobs", headers=bearer(token))
            assert response.status_code == 200, response.text
            return {job["id"] for job in response.json()["items"]}

        for token, job_id in [
            (bob, own),
            (alice_low, own),
            (carol, own),
            (bob, scheduled),
            (alice, scheduled),
        ]:
            before = state.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
            for method, path in [
                ("GET", f"/jobs/{job_id}"),
                ("POST", f"/jobs/{job_id}/cancel"),
                ("POST", f"/jobs/{job_id}/resume"),
            ]:
                response = api.request(method, path, headers=bearer(token))
                assert response.status_code == 404, (path, response.text)
                assert code(response) == "E_NOT_FOUND"
            assert job_id not in visible_ids(token)
            assert state.rows("SELECT * FROM jobs WHERE id=?", (job_id,)) == before
        # Positive controls: the owner sees its job, a reviewer sees the scheduled one.
        for token, job_id in [(alice, own), (carol, scheduled)]:
            assert api.get(f"/jobs/{job_id}", headers=bearer(token)).status_code == 200
            assert job_id in visible_ids(token)


# В4. authorize() in wikiagent.


def agent_app(
    client: TestClient, settings: AgentConfig
) -> tuple[TestClient, AgentState, Callable[[], int]]:
    wiki = wiki_client(client, settings)
    fake = FakeLLM(lambda task, data: {"intent": "intake"})
    state = AgentState(settings.state_dir)
    app = create_agent_app(settings, wiki, ModelClient(settings, state, fake.http))

    def rows() -> int:
        return sum(
            len(state.rows(f"SELECT id FROM {table}")) for table in ("jobs", "chat_sessions")
        )

    return TestClient(app), state, rows


def test_agent_api_rejects_unauthenticated_and_readers(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, human = tokens(client)
    reader = auth(client).create("reader-desk", "reader", "restricted", person="dave", kind="human")
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    api, _, rows = agent_app(client, agent_config(tmp_path / "agent"))
    with api:
        routes = [route for route in api.app.routes if isinstance(route, APIRoute)]
        assert len(routes) >= 12
        # Only FastAPI's generated documentation is outside APIRoute; it carries no data.
        assert {r.path for r in api.app.routes if not isinstance(r, APIRoute)} == {
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }
        for route in routes:
            path = re.sub(r"\{[^}]+\}", "0" * 32, route.path)
            for method in route.methods:
                response = api.request(method, path, json={})
                assert response.status_code == 401, (method, path, response.text)
                response = api.request(method, path, json={}, headers={"Authorization": "Bearer"})
                assert response.status_code == 401, (method, path, response.text)
        for method, path, body in [
            ("GET", "/jobs", None),
            ("POST", "/jobs/heal", {"scope": "changed"}),
            ("POST", "/chat/sessions", {}),
            ("GET", "/chat/sessions", None),
        ]:
            response = api.request(method, path, json=body, headers=bearer(reader))
            assert response.status_code == 403, (path, response.text)
            assert code(response) == "E_FORBIDDEN"
        assert rows() == 0
        assert api.get("/jobs", headers=bearer(human)).status_code == 200


@pytest.mark.parametrize(
    "role,kind",
    [("writer", "human"), ("reviewer", "agent"), ("admin", "agent"), ("reviewer", "human")],
)
def test_agent_service_token_must_be_agent_writer(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: Literal["writer", "reviewer", "admin"],
    kind: Literal["agent", "human"],
) -> None:
    agent, human = tokens(client)
    misconfigured = auth(client).create(
        "service-" + role + "-" + kind,
        role,
        "restricted",
        person="service-" + kind,
        kind=kind,
    )
    monkeypatch.setenv("WIKIAGENT_TOKEN", misconfigured)
    api, _, rows = agent_app(client, agent_config(tmp_path / "agent"))
    with api:
        for method, path, body in [
            ("GET", "/jobs", None),
            ("POST", "/jobs/heal", {"scope": "changed"}),
            ("POST", "/chat/sessions", {}),
        ]:
            response = api.request(method, path, json=body, headers=bearer(human))
            assert response.status_code == 403, (path, response.text)
            assert code(response) == "E_AGENT_TOKEN"
        assert rows() == 0
        # Positive control: the same caller passes once the service token is a writer agent.
        monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
        assert api.get("/jobs", headers=bearer(human)).status_code == 200


# В5. Healer fixes stay inside the checked pair.

PAIR = ("rule-heal-02", "rule-heal-03")


@pytest.mark.parametrize(
    "fix,valid",
    [
        (
            {
                "page": "rule-heal-04",
                "op": "set_field",
                "field": "summary",
                "value": "Правка лекаря вне проверяемой пары.",
            },
            False,
        ),
        (
            {
                "page": "rule-heal-02",
                "op": "add_relation",
                "rel": "related",
                "target": "rule-heal-04",
            },
            False,
        ),
        ({"page": "rule-heal-02", "op": "set_field", "field": "summary"}, False),
        (
            {"page": "rule-heal-02", "op": "add_relation", "rel": "supersedes", "target": PAIR[1]},
            True,
        ),
    ],
    ids=["third-page", "third-target", "set-field-no-value", "control-valid"],
)
def test_healer_fix_limited_to_pair(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fix: dict[str, str],
    valid: bool,
) -> None:
    seed_heal(client, config, 6)
    agent, human = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)

    def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
        pages = {p["id"]: p for p in data["pages"]}
        if tuple(sorted(pages)) != PAIR:
            return {"relation": "none", "confidence": 0.99, "explanation": "Нет проблемы."}
        return {
            "relation": "duplicate",
            "confidence": 0.98,
            "explanation": "Правила дублируют друг друга.",
            "evidence": [{"page": key, "quote": pages[key]["summary"]} for key in PAIR],
            "suggested_fix": [fix],
        }

    fake = FakeLLM(respond)
    models = ModelClient(settings, state, fake.http)
    healer = Healer(wiki, models, state, Chat(wiki, models, state), lambda _: None)
    head = GitRepo(config.wiki_root).head()
    outside = client.get(f"{API}/pages/rule-heal-04", headers=bearer(human)).json()["version"]
    job = state.job("heal", wiki.check_writer(), {"scope": "full"})
    healer.run(job, {"scope": "full"})
    report = state.restore(job, "report")
    assert any(tuple(sorted(p["id"] for p in d["pages"])) == PAIR for _, d in fake.calls)
    heal = client.get(f"{API}/proposals", params={"kind": "heal"}, headers=bearer(human)).json()
    duplicates = [
        f
        for f in client.get(f"{API}/findings", headers=bearer(human)).json()["items"]
        if f["kind"] == "duplicate"
    ]
    if valid:
        assert not report["discarded"], report
        assert len(heal["items"]) == 1 and len(duplicates) == 1
    else:
        assert {"pair": list(PAIR), "code": "E_MODEL_OUTPUT"} in report["discarded"]
        assert heal["items"] == [] and duplicates == []
    assert GitRepo(config.wiki_root).head() == head
    assert (
        client.get(f"{API}/pages/rule-heal-04", headers=bearer(human)).json()["version"] == outside
    )
    assert wiki.forbidden_attempts == 0


# В6. wikisvc makes no outgoing network calls and does not call the agent.

# The guard matches module paths, so `from asyncio import open_connection` is caught but an
# attribute call on a plain `import asyncio` is not; asyncio itself stays allowed.
FORBIDDEN_IMPORTS = (
    "httpx",
    "requests",
    "socket",
    "urllib.request",
    "aiohttp",
    "wikiagent",
    "http.client",
    "urllib3",
    "ftplib",
    "smtplib",
    "ssl",
    "asyncio.open_connection",
    "asyncio.open_unix_connection",
)


def forbidden_imports(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module, *(node.module + "." + alias.name for alias in node.names)]
        elif (
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names = [node.args[0].value]
        found.extend(
            name
            for name in names
            if any(name == banned or name.startswith(banned + ".") for banned in FORBIDDEN_IMPORTS)
        )
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import urllib.request as r",
        "from urllib import request",
        "from socket import create_connection",
        "from wikiagent.client import WikiClient",
        "__import__('requests')",
        "import importlib\nimportlib.import_module('aiohttp')",
        "import http.client",
        "from http import client",
        "from http.client import HTTPSConnection",
        "import urllib3",
        "from ftplib import FTP",
        "import smtplib",
        "import ssl",
        "from asyncio import open_connection",
        "from asyncio import open_unix_connection",
    ],
)
def test_import_guard_detects_network_imports(source: str) -> None:
    assert forbidden_imports(source)


@pytest.mark.parametrize(
    "source", ["import asyncio", "from http import HTTPStatus", "from asyncio import gather"]
)
def test_import_guard_allows_local_modules(source: str) -> None:
    assert forbidden_imports(source) == []


def test_wikisvc_has_no_network_or_agent_imports() -> None:
    root = Path(wikisvc.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert len(files) > 40
    found = {
        str(path.relative_to(root)): names
        for path in files
        if (names := forbidden_imports(path.read_text(encoding="utf-8")))
    }
    assert found == {}


# В7. A PUT of an existing rule keeps every protected field.

PROTECTED = ("lifecycle", "level", "priority", "owner", "deprecated_reason", "verified_by")


def test_put_existing_rule_restores_protected_fields(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    current = client.get(f"{API}/pages/rule-stack-example-1").json()
    metadata, body = parse(SafeFS(config.wiki_root).read("wiki/rules/stack-example-1.md"))
    summary = "Описание счетов, интеграций и правил работы компании с уточнением."
    forged = {
        **metadata,
        "summary": summary,
        "lifecycle": "deprecated",
        "deprecated_reason": "Снято агентом.",
        "level": "must",
        "owner": "team-forged",
        "priority": 1,
        "verified_by": "forged-agent",
        "verified_at": "2030-01-01",
        "status": "verified",
    }
    response = client.put(
        f"{API}/proposals/{pid}/pages/rule-stack-example-1",
        json={"frontmatter": forged, "body_md": body, "base_version": current["version"]},
    )
    assert response.status_code == 200, response.text
    stored = parse(
        SafeFS(config.state_dir / "worktrees" / pid).read("wiki/rules/stack-example-1.md")
    )[0]
    assert {key: stored.get(key) for key in (*PROTECTED, "verified_at", "status")} == {
        "lifecycle": "active",
        "level": "should",
        "priority": 3,
        "owner": None,
        "deprecated_reason": None,
        "verified_by": "fixture",
        "verified_at": "2026-01-01",
        "status": "draft",
    }
    assert stored["summary"] == summary
    assert client.post(f"{API}/proposals/{pid}/submit").status_code == 200
    human = auth(client).create("rule-reviewer", "reviewer", "restricted", kind="human")
    accepted = client.post(f"{API}/proposals/{pid}/accept", headers=bearer(human))
    assert accepted.status_code == 200, accepted.text
    result = client.get(f"{API}/rules/rule-stack-example-1").json()
    assert (result["summary"], result["lifecycle"], result["level"], result["priority"]) == (
        summary,
        "active",
        "should",
        3,
    )
    assert result.get("owner") is None and result.get("deprecated_reason") is None


@pytest.mark.parametrize(
    "field,value", [("status", "verified"), ("deprecated_reason", "Снято агентом.")]
)
def test_patch_rule_status_and_deprecated_reason_protected(
    client: TestClient, config: Settings, field: str, value: str
) -> None:
    pid = proposal(client)
    current = client.get(f"{API}/pages/rule-stack-example-1").json()
    branch = GitRepo(config.state_dir / "worktrees" / pid)
    head = branch.head()
    response = client.patch(
        f"{API}/proposals/{pid}/pages/rule-stack-example-1",
        json={
            "base_version": current["version"],
            "ops": [{"op": "set_field", "field": field, "value": value}],
        },
    )
    assert response.status_code == 422, response.text
    assert code(response) == "E_FIELD_PROTECTED"
    assert branch.head() == head
    assert client.get(f"{API}/proposals/{pid}/diff").json()["pages"] == []


# В8. Proposal ownership is compared by actor.name, which is a display name for SSO.


def edit(client: TestClient, pid: str, operation: str, token: str) -> httpx.Response:
    if operation == "put":
        return client.put(
            f"{API}/proposals/{pid}/pages/term-taken",
            json=payload("term-taken", "Чужая правка."),
            headers=bearer(token),
        )
    if operation == "notes":
        return client.put(
            f"{API}/proposals/{pid}/notes",
            json={"summary": "Чужие заметки", "items": []},
            headers=bearer(token),
        )
    return client.post(f"{API}/proposals/{pid}/abandon", headers=bearer(token))


def ownership_case(
    client: TestClient, config: Settings, other_display: str, operation: str
) -> tuple[httpx.Response, Callable[[], object]]:
    keys = auth(client)
    author = keys.create(
        "alex-sso", "writer", "internal", person="alex@corp", kind="human", display_name="Alex Kim"
    )
    other = keys.create(
        "alexa-sso",
        "writer",
        "internal",
        person="alexa@corp",
        kind="human",
        display_name=other_display,
    )
    pid = client.post(
        f"{API}/proposals", json={"title": "Own proposal"}, headers=bearer(author)
    ).json()["pid"]
    assert (
        client.put(
            f"{API}/proposals/{pid}/pages/term-new", json=payload(), headers=bearer(author)
        ).status_code
        == 200
    )
    db = StateDB(config.state_dir)

    def state() -> object:
        return (
            GitRepo(config.state_dir / "worktrees" / pid).head(),
            db.rows("SELECT status,last_editor FROM proposals WHERE pid=?", (pid,)),
            db.rows("SELECT * FROM proposal_notes WHERE pid=?", (pid,)),
        )

    before = state()
    return edit(client, pid, operation, other), lambda: before == state()


@pytest.mark.parametrize("operation", ["put", "notes", "abandon"])
def test_other_person_cannot_edit_proposal(
    client: TestClient, config: Settings, operation: str
) -> None:
    response, unchanged = ownership_case(client, config, "Alexa Lee", operation)
    assert response.status_code == 403, response.text
    assert code(response) == "E_FORBIDDEN"
    assert unchanged()


@pytest.mark.xfail(
    strict=True,
    reason="В8: proposals.py:65/210/627 сравнивают proposal.author с actor.name (display_name "
    "у SSO), а не с identity; тёзка правит, пишет заметки и закрывает чужое предложение. "
    "Фикс в защищённом proposals.py — отдельная задача.",
)
@pytest.mark.parametrize("operation", ["put", "notes", "abandon"])
def test_namesake_cannot_edit_proposal(
    client: TestClient, config: Settings, operation: str
) -> None:
    response, unchanged = ownership_case(client, config, "Alex Kim", operation)
    assert response.status_code == 403, response.text
    assert code(response) == "E_FORBIDDEN"
    assert unchanged()


# В9. Smaller boundaries.


def test_book_outline_and_pages_are_untrusted(service: TestClient, config: Settings) -> None:
    human = auth(service).create("librarian", "reviewer", "restricted", kind="human")
    service.headers["Authorization"] = "Bearer " + human
    data = (Path(__file__).parent / "fixtures/books/handbook.pdf").read_bytes()
    path = library(service, "handbook.pdf", data)["path"]
    extract(service, path)
    outline = service.get(f"{API}/raw/{path}/outline").json()
    whole = service.get(f"{API}/raw/{path}/text", params={"chapter": 2}).json()
    part = service.get(f"{API}/raw/{path}/text", params={"chapter": 2, "max_chars": 20}).json()
    rest = service.get(
        f"{API}/raw/{path}/text",
        params={"pages": part["next_pages"], "offset": part["next_offset"]},
    ).json()
    assert len(outline["chapters"]) == 3 and whole["text"] == part["text"] + rest["text"]
    mcp = [
        tool_result(call(service, "get_outline", {"path": path})),
        tool_result(call(service, "read_source_pages", {"path": path, "chapter": 2})),
    ]
    for result in [outline, whole, part, rest, *mcp]:
        assert result["trust"] == "untrusted_external"


def recording_client(client: TestClient, settings: AgentConfig) -> tuple[WikiClient, list[str]]:
    sent: list[str] = []

    def forward(request: httpx.Request) -> httpx.Response:
        sent.append(request.method + " " + request.url.raw_path.decode())
        response = client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.content
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"Content-Type": "application/json"},
        )

    http = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(forward))
    return WikiClient(settings.wikisvc, http=http), sent


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_page", {"id": ".."}),
        ("get_page", {"id": "app-example-1/history"}),
        ("get_page", {"id": "app%2dexample-1"}),
        ("get_page", {"id": "app-example-1?include=history"}),
        ("get_page", {"id": 1}),
        ("read_source_pages", {"path": "raw/docs/../../library/x"}),
        ("read_source_pages", {"path": "raw/docs/example%2etxt"}),
        ("get_outline", {"path": "library/../raw/docs/example.txt"}),
    ],
)
def test_agent_tool_rejects_route_arguments(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    arguments: dict[str, Any],
) -> None:
    agent, _ = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    wiki, sent = recording_client(client, agent_config(tmp_path / "agent"))
    with pytest.raises(WikiError) as error:
        execute(wiki, "chat", name, arguments)
    assert error.value.code == "E_AGENT_TOOL_ARGUMENTS"
    assert sent == []
    # Positive control: well-formed arguments of the same tools reach the service.
    assert execute(wiki, "chat", "get_page", {"id": "app-example-1"})["id"] == "app-example-1"
    text = execute(wiki, "chat", "read_source_pages", {"path": "raw/docs/example.txt"})
    assert text["trust"] == "untrusted_external"
    assert sent == ["GET /api/v1/pages/app-example-1", "GET /api/v1/raw/raw/docs/example.txt/text"]


@pytest.mark.parametrize(
    "path",
    [
        "/raw/../people",
        "/raw/../stats",
        "/raw/docs/../../inbox",
        "/raw/./../people",
        "/pages/../admin/audit",
        "/raw/%2e%2e/people",
    ],
)
def test_wiki_client_rejects_dot_segments(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    agent, _ = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    wiki, sent = recording_client(client, agent_config(tmp_path / "agent"))
    with pytest.raises(WikiError) as error:
        wiki.request("GET", path)
    assert error.value.code == "E_AGENT_TOOL_FORBIDDEN"
    assert sent == [] and wiki.forbidden_attempts == 1
    # Positive control: a raw path without dot segments still passes the allowlist.
    assert wiki.request("GET", "/raw/raw/docs/example.txt/text")["trust"] == "untrusted_external"
    assert sent == ["GET /api/v1/raw/raw/docs/example.txt/text"]


LIMIT = 1024 * 1024


def sized_proposal(size: int) -> bytes:
    data = json.dumps({"title": "Предложение на границе лимита"}).encode()
    return data + b" " * (size - len(data))


@pytest.mark.parametrize("streamed", [False, True])
def test_body_limit_boundary(client: TestClient, config: Settings, streamed: bool) -> None:
    db = StateDB(config.state_dir)
    before = len(db.rows("SELECT pid FROM proposals"))

    def post(size: int) -> httpx.Response:
        body = sized_proposal(size)
        content: bytes | Iterator[bytes] = (
            iter([body[: size // 2], body[size // 2 :]]) if streamed else body
        )
        return client.post(
            f"{API}/proposals", content=content, headers={"Content-Type": "application/json"}
        )

    exact = post(LIMIT)
    assert exact.status_code == 200, exact.text
    over = post(LIMIT + 1)
    assert over.status_code == 413, over.text
    assert code(over) == "E_BODY_TOO_LARGE"
    assert len(db.rows("SELECT pid FROM proposals")) == before + 1


@pytest.mark.parametrize("lengths", [[b"10", b"10"], [b"10", b"11"], [b"0", b"2000000"]])
def test_repeated_content_length_rejected_before_body(
    client: TestClient, config: Settings, lengths: list[bytes]
) -> None:
    db = StateDB(config.state_dir)
    before = len(db.rows("SELECT pid FROM proposals"))
    output: list[Message] = []

    async def receive() -> Message:
        pytest.fail("Body read despite repeated Content-Length")

    async def send(message: Message) -> None:
        output.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": f"{API}/proposals",
        "headers": [
            (b"authorization", client.headers["Authorization"].encode()),
            (b"content-type", b"application/json"),
            *((b"content-length", value) for value in lengths),
        ],
    }
    assert client.portal is not None
    client.portal.call(client.app, scope, receive, send)
    assert output[0]["status"] == 400
    assert json.loads(output[1]["body"])["error"]["code"] == "E_REQUEST_INVALID"
    assert len(db.rows("SELECT pid FROM proposals")) == before


# Б11. A proposal outside draft/changes_requested/conflict is closed for edits.


@pytest.mark.parametrize("status", ["submitted", "accepted", "rejected", "abandoned"])
def test_closed_proposal_cannot_be_edited(
    client: TestClient, config: Settings, status: str
) -> None:
    pid = candidate(client)
    assert client.post(f"{API}/proposals/{pid}/submit").status_code == 200
    human = auth(client).create("closing-reviewer", "reviewer", "restricted", kind="human")
    if status == "accepted":
        response = client.post(f"{API}/proposals/{pid}/accept", headers=bearer(human))
    elif status == "rejected":
        response = client.post(
            f"{API}/proposals/{pid}/reject", json={"reason": "Не нужно."}, headers=bearer(human)
        )
    elif status == "abandoned":
        response = client.post(f"{API}/proposals/{pid}/abandon")
    if status != "submitted":
        assert response.status_code == 200, response.text
    assert client.get(f"{API}/proposals/{pid}").json()["status"] == status
    repo = GitRepo(config.wiki_root)
    db = StateDB(config.state_dir)
    work = config.state_dir / "worktrees" / pid

    def state() -> object:
        return (
            repo.head(),
            repo.run("for-each-ref", "--format=%(objectname)", f"refs/heads/proposal/{pid}"),
            GitRepo(work).head() if work.exists() else None,
            db.rows("SELECT status,updated_at,last_editor FROM proposals WHERE pid=?", (pid,)),
            db.rows("SELECT * FROM proposal_snapshots WHERE pid=? ORDER BY path", (pid,)),
        )

    before = state()
    endpoint = f"{API}/proposals/{pid}/pages/"
    for response in [
        client.put(endpoint + "term-new", json=payload()),
        client.patch(
            endpoint + "rule-logging",
            json={"ops": [{"op": "set_field", "field": "title", "value": "Изменённое правило"}]},
        ),
        client.delete(endpoint + "rule-logging"),
    ]:
        assert response.status_code == 409, response.text
        assert code(response) == "E_PROPOSAL_STATE"
        assert state() == before
