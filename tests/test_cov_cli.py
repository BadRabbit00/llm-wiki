"""Command line paths end to end.

wikisvc commands run through CliRunner on a real Git wiki in tmp and are judged by what
they leave behind: a token that does or does not open the real API, a commit, an index.
wikiagent commands meet wikisvc and the model as real HTTP services on loopback; their
CLI builds its own httpx client, so a transport cannot be handed in. The SSO diagnostics
read a real state.db and run whatever ``timedatectl`` PATH resolves to.
"""

import json
import os
import shutil
import socket
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import pytest
import uvicorn
from agent_helpers import agent_config, wiki_client
from fake_llm import FakeLLM
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from wikiagent.api import create_app as create_agent_app
from wikiagent.auth_check import check_authentication
from wikiagent.check import check
from wikiagent.cli import app as agent_cli
from wikiagent.config import AgentConfig, load_config
from wikisvc import __version__
from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Role
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.storage.db_version import INDEX_SCHEMA
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB

TEMPLATE = SafeFS(Path(__file__).parents[1] / "src/wikisvc/template")


@pytest.fixture
def env(config: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The variables a deployment gives every wikisvc command."""
    for name in ("wiki_root", "state_dir", "index_dir"):
        monkeypatch.setenv(name.upper(), str(getattr(config, name)))
    monkeypatch.delenv("WIKI_TOKEN", raising=False)
    monkeypatch.delenv("LOCK_TIMEOUT", raising=False)
    return config


def invoke(*arguments: str) -> Any:
    return CliRunner().invoke(app, list(arguments))


def whoami(config: Settings, token: str) -> httpx.Response:
    with TestClient(create_app(config)) as client:
        return client.get("/api/v1/whoami", headers={"Authorization": "Bearer " + token})


def token_rows(config: Settings) -> list[dict[str, Any]]:
    return StateDB(config.state_dir).rows("SELECT name,role,clearance,kind,person FROM tokens")


# --- wikisvc token ---------------------------------------------------------------------


def test_token_create_issues_a_working_token_and_revoke_closes_it(env: Settings) -> None:
    created = invoke(
        "token",
        "create",
        "--name",
        "alice-cli",
        "--role",
        "reviewer",
        "--clearance",
        "restricted",
        "--kind",
        "human",
        "--person",
        "alice",
    )
    assert created.exit_code == 0, created.output
    token = created.stdout.strip()
    assert created.stdout == token + "\n" and len(token) >= 32

    response = whoami(env, token)
    assert response.status_code == 200
    assert {k: response.json()[k] for k in ("name", "role", "clearance", "kind", "person")} == {
        "name": "alice-cli",
        "role": "reviewer",
        "clearance": "restricted",
        "kind": "human",
        "person": "alice",
    }

    revoked = invoke("token", "revoke", "alice-cli")
    assert (revoked.exit_code, revoked.stdout) == (0, "Revoked\n")
    refused = whoami(env, token)
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "E_UNAUTHORIZED"


def test_token_create_defaults_to_a_writer_agent(env: Settings) -> None:
    created = invoke("token", "create", "--name", "bot")
    assert created.exit_code == 0, created.output
    assert token_rows(env) == [
        {"name": "bot", "role": "writer", "clearance": "internal", "kind": "agent", "person": None}
    ]
    assert whoami(env, created.stdout.strip()).json()["role"] == "writer"


@pytest.mark.parametrize(
    "option,value,message",
    [
        ("--role", "owner", "Invalid role or clearance"),
        ("--role", "Admin", "Invalid role or clearance"),
        ("--clearance", "secret", "Invalid role or clearance"),
        ("--clearance", "", "Invalid role or clearance"),
        ("--kind", "robot", "kind: agent or human"),
        ("--kind", "Human", "kind: agent or human"),
    ],
)
def test_token_create_rejects_unknown_access_and_stores_nothing(
    env: Settings, option: str, value: str, message: str
) -> None:
    result = invoke("token", "create", "--name", "bad", option, value)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Invalid value: " + message in result.stderr
    assert token_rows(env) == []


def test_token_create_reports_service_validation_without_storing(env: Settings) -> None:
    for arguments, code in [
        (["--name", "-bad"], "E_TOKEN_NAME"),
        (["--name", "ok", "--person", "al ice"], "E_TOKEN_PERSON"),
        (["--name", "ok", "--expires-at", "2030-01-01T00:00:00"], "E_REQUEST_INVALID"),
    ]:
        result = invoke("token", "create", *arguments)
        assert result.exit_code == 1
        assert isinstance(result.exception, WikiError)
        assert result.exception.code == code
    assert token_rows(env) == []


def test_token_with_past_expiry_never_opens_the_api(env: Settings) -> None:
    created = invoke(
        "token", "create", "--name", "old", "--expires-at", "2000-01-01T00:00:00+00:00"
    )
    assert created.exit_code == 0, created.output
    response = whoami(env, created.stdout.strip())
    assert (response.status_code, response.json()["error"]["code"]) == (401, "E_UNAUTHORIZED")


def test_token_revoke_touches_only_the_named_token(env: Settings) -> None:
    kept = invoke("token", "create", "--name", "kept").stdout.strip()
    gone = invoke("token", "create", "--name", "gone").stdout.strip()
    assert invoke("token", "revoke", "gone").exit_code == 0
    assert whoami(env, kept).status_code == 200
    assert whoami(env, gone).status_code == 401
    audit = StateDB(env.state_dir).rows(
        "SELECT action,target,ok FROM audit WHERE action=?", ("token.revoke",)
    )
    assert audit == [{"action": "token.revoke", "target": "gone", "ok": 1}]


def test_token_revoke_refuses_a_name_with_no_active_token(env: Settings) -> None:
    kept = invoke("token", "create", "--name", "kept").stdout.strip()
    assert invoke("token", "revoke", "kept").exit_code == 0
    for name in ("kept", "mistyped"):  # Already revoked, never issued.
        result = invoke("token", "revoke", name)
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == "E_NOT_FOUND: Токен не найден или уже отозван.\n"
    assert whoami(env, kept).status_code == 401
    audit = StateDB(env.state_dir).rows(
        "SELECT target,ok FROM audit WHERE action=? ORDER BY rowid", ("token.revoke",)
    )
    assert audit == [
        {"target": "kept", "ok": 1},
        {"target": "kept", "ok": 0},
        {"target": "mistyped", "ok": 0},
    ]


# --- wikisvc init / version / scopes ---------------------------------------------------


def test_version_prints_the_package_version() -> None:
    result = invoke("version")
    assert (result.exit_code, result.stdout) == (0, __version__ + "\n")
    assert __version__ == "0.2.0"


def test_init_creates_a_committed_wiki_and_refuses_a_non_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "company-wiki"
    result = invoke("init", str(target))
    assert (result.exit_code, result.stdout) == (0, f"Initialized wiki: {target.resolve()}\n")
    assert os.readlink(target / "CLAUDE.md") == "AGENTS.md"
    assert (target / "AGENTS.md").read_text() == TEMPLATE.read("AGENTS.md")
    repo = GitRepo(target)
    assert repo.run("log", "--format=%s").splitlines() == ["Initialize company wiki"]
    assert repo.run("status", "--porcelain") == ""

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("mine")
    refused = invoke("init", str(occupied))
    assert refused.exit_code == 1
    assert isinstance(refused.exception, WikiError)
    assert (refused.exception.code, refused.exception.status) == ("E_INIT_NONEMPTY", 409)
    assert [p.name for p in occupied.iterdir()] == ["notes.txt"]
    assert (occupied / "notes.txt").read_text() == "mine"


@pytest.mark.parametrize(
    "value", ["Lang:python", "lang", "lang:", ":python", "lang:py thon", "1x:y"]
)
def test_scope_add_rejects_malformed_scope_without_commit(env: Settings, value: str) -> None:
    repo = GitRepo(env.wiki_root)
    head, scopes = repo.head(), SafeFS(env.wiki_root).read("schema/scopes.yaml")
    result = invoke("scopes", "add", value)
    assert result.exit_code == 1
    assert isinstance(result.exception, WikiError)
    assert result.exception.code == "E_SCOPE_UNKNOWN"
    assert repo.head() == head
    assert SafeFS(env.wiki_root).read("schema/scopes.yaml") == scopes


def test_scope_add_commits_once_and_serves_the_scope(env: Settings) -> None:
    repo = GitRepo(env.wiki_root)
    assert invoke("scopes", "add", "db:postgres-16.2").stdout == "db:postgres-16.2\n"
    head = repo.head()
    assert repo.run("log", "-1", "--format=%s").strip() == "Add scope db:postgres-16.2"
    again = invoke("scopes", "add", "db:postgres-16.2")
    assert (again.exit_code, again.stdout, repo.head()) == (0, "db:postgres-16.2\n", head)
    with TestClient(create_app(env)) as client:
        client.headers["Authorization"] = "Bearer " + Auth(StateDB(env.state_dir)).create(
            "reader", "reader", "internal"
        )
        assert "db:postgres-16.2" in client.get("/api/v1/scopes").json()


# --- wikisvc schema upgrade / migrate-rules -------------------------------------------


def legacy_schema(config: Settings) -> GitRepo:
    """A wiki from before rules: a convention page type, a lost workflow, own AGENTS.md."""
    fs, repo = SafeFS(config.wiki_root), GitRepo(config.wiki_root)
    fs.write(
        "schema/page-types/convention.yaml",
        TEMPLATE.read("schema/page-types/term.yaml")
        .replace("type: term", "type: convention")
        .replace("prefix: term", "prefix: legacyconv")
        .replace("domain/glossary/", "legacy/conventions/"),
    )
    fs.remove("schema/workflows/heal.md")
    fs.write("AGENTS.md", "# Our own instructions\n")
    # AGENTS.md is outside GitRepo.managed, so it has to be named to be committed.
    repo.commit(
        "Legacy schema",
        "fixtures",
        ["schema/page-types/convention.yaml", "schema/workflows/heal.md", "AGENTS.md"],
    )
    assert repo.run("status", "--porcelain") == ""
    return repo


def test_schema_upgrade_installs_missing_and_removes_legacy_once(env: Settings) -> None:
    repo = legacy_schema(env)
    fs = SafeFS(env.wiki_root)
    first = invoke("schema", "upgrade")
    assert first.exit_code == 0, first.output
    report = json.loads(first.stdout)
    assert report["commit"] == repo.head()
    assert "schema/workflows/heal.md" in report["updated"]
    assert "AGENTS.md" not in report["updated"]
    assert report["removed"] == ["schema/page-types/convention.yaml"]
    assert fs.read("schema/workflows/heal.md") == TEMPLATE.read("schema/workflows/heal.md")
    assert not fs.path("schema/page-types/convention.yaml").exists()
    assert fs.read("AGENTS.md") == "# Our own instructions\n"
    assert repo.run("log", "-1", "--format=%s|%an").strip() == "Upgrade policy schema|cli"

    second = json.loads(invoke("schema", "upgrade").stdout)
    assert second == {"commit": report["commit"], "updated": [], "removed": []}

    refreshed = json.loads(invoke("schema", "upgrade", "--refresh-instructions").stdout)
    assert refreshed["updated"] == ["AGENTS.md"] and refreshed["removed"] == []
    assert refreshed["commit"] == repo.head()
    assert refreshed["commit"] != report["commit"]
    assert fs.read("AGENTS.md") == TEMPLATE.read("AGENTS.md")
    assert repo.run("show", "HEAD:AGENTS.md") + "\n" == TEMPLATE.read("AGENTS.md")
    audit = StateDB(env.state_dir).rows("SELECT target FROM audit WHERE action='schema.upgrade'")
    assert [row["target"] for row in audit] == [report["commit"], refreshed["commit"]]


def legacy_rule(config: Settings) -> GitRepo:
    metadata = {
        "id": "conv-legacy",
        "type": "convention",
        "title": "Старое правило",
        "summary": "Сохраняй содержательное описание решения в коде.",
        "status": "verified",
        "created": "2026-01-01",
        "updated": "2026-01-01",
    }
    SafeFS(config.wiki_root).write(
        "wiki/engineering/conventions/legacy.md",
        render(metadata, "## Правило\n\nПиши подробные сообщения об ошибках.\n"),
    )
    repo = GitRepo(config.wiki_root)
    repo.commit("Legacy rule", "fixtures")
    return repo


def proposals(config: Settings) -> list[dict[str, Any]]:
    return StateDB(config.state_dir).rows("SELECT pid,author,status FROM proposals")


def test_migrate_rules_dry_run_previews_without_writing(env: Settings) -> None:
    repo = legacy_rule(env)
    head = repo.head()
    result = invoke("migrate-rules", "--dry-run")
    assert result.exit_code == 0, result.output
    preview = json.loads(result.stdout)
    assert preview["dry_run"] is True
    assert preview["mapping"] == {"conv-legacy": "rule-conv-legacy"}
    assert {
        "before": "wiki/engineering/conventions/legacy.md",
        "path": "wiki/rules/conv-legacy.md",
    } in preview["pages"]
    assert "proposal" not in preview
    assert repo.head() == head and proposals(env) == []


def test_migrate_rules_needs_a_writer_token(env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = legacy_rule(env)
    head = repo.head()
    missing = invoke("migrate-rules")
    assert isinstance(missing.exception, WikiError)
    assert (missing.exit_code, missing.exception.code) == (1, "E_UNAUTHORIZED")
    reader = Auth(StateDB(env.state_dir)).create("reader", "reader", "restricted")
    monkeypatch.setenv("WIKI_TOKEN", reader)
    refused = invoke("migrate-rules")
    assert isinstance(refused.exception, WikiError)
    assert (refused.exit_code, refused.exception.code) == (1, "E_FORBIDDEN")
    assert repo.head() == head and proposals(env) == []


def test_migrate_rules_opens_a_proposal_for_the_token_owner(
    env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = legacy_rule(env)
    head = repo.head()
    token = invoke(
        "token", "create", "--name", "migrator", "--clearance", "restricted"
    ).stdout.strip()
    monkeypatch.setenv("WIKI_TOKEN", token)
    result = invoke("migrate-rules")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["dry_run"] is False and report["validation"]["errors"] == []
    assert proposals(env) == [{"pid": report["proposal"], "author": "migrator", "status": "draft"}]
    assert repo.head() == head  # Nothing reaches main without review.
    with TestClient(create_app(env)) as client:
        client.headers["Authorization"] = "Bearer " + token
        pages = client.get(f"/api/v1/proposals/{report['proposal']}").json()["pages"]
    rule = next(p for p in pages if p["id"] == "rule-conv-legacy")
    assert (rule["type"], rule["lifecycle"], rule["level"], rule["priority"]) == (
        "rule",
        "candidate",
        "idea",
        3,
    )


# --- wikisvc reindex / repair-worktrees -----------------------------------------------


def index_ids(config: Settings) -> set[str]:
    with sqlite3.connect(config.index_dir / "wiki.db") as db:
        return {row[0] for row in db.execute("SELECT id FROM pages")}


def commit_outside_service(config: Settings) -> None:
    """A page committed straight to Git, as an administrator restoring content would."""
    metadata = {
        "id": "term-restored",
        "type": "term",
        "title": "Восстановленный термин",
        "summary": "Термин, добавленный в Git в обход сервиса при восстановлении.",
        "status": "draft",
        "sensitivity": "internal",
        "created": "2026-01-01",
        "updated": "2026-01-01",
    }
    SafeFS(config.wiki_root).write(
        "wiki/domain/glossary/restored.md",
        render(metadata, "## Определение\n\nТермин из резервной копии.\n"),
    )
    GitRepo(config.wiki_root).commit("Restore a term", "admin")


def test_reindex_picks_up_commits_made_outside_the_service(env: Settings) -> None:
    assert invoke("reindex").exit_code == 0
    assert "term-restored" not in index_ids(env)
    commit_outside_service(env)
    result = invoke("reindex")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Index rebuilt; ") and result.stdout.endswith(" issues.\n")
    assert "term-restored" in index_ids(env)
    with sqlite3.connect(env.index_dir / "wiki.db") as db:
        indexed = db.execute("SELECT value FROM meta WHERE key='index_commit'").fetchone()[0]
    assert indexed == GitRepo(env.wiki_root).head()


def test_only_a_full_reindex_repairs_a_damaged_index(env: Settings) -> None:
    assert invoke("reindex").exit_code == 0
    with sqlite3.connect(env.index_dir / "wiki.db") as db:
        db.execute("DELETE FROM pages WHERE id='term-example-1'")
    # Nothing changed in Git since index_commit, so an incremental pass has nothing to do.
    assert invoke("reindex").exit_code == 0
    assert "term-example-1" not in index_ids(env)
    rebuilt = invoke("reindex", "--full")
    assert rebuilt.exit_code == 0, rebuilt.output
    assert "term-example-1" in index_ids(env)


def test_reindex_waits_for_the_write_lock(env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    assert invoke("reindex").exit_code == 0
    commit_outside_service(env)
    monkeypatch.setenv("LOCK_TIMEOUT", "0.2")
    with write_lock(env.state_dir):
        result = invoke("reindex")
    assert isinstance(result.exception, WikiError)
    assert (result.exit_code, result.exception.code) == (1, "E_LOCK_TIMEOUT")
    assert "term-restored" not in index_ids(env)


def test_full_reindex_replaces_an_index_from_a_newer_version(env: Settings) -> None:
    assert invoke("reindex").exit_code == 0
    with sqlite3.connect(env.index_dir / "wiki.db") as db:
        db.execute(f"PRAGMA user_version = {INDEX_SCHEMA + 1}")
    refused = invoke("reindex")
    assert isinstance(refused.exception, WikiError)
    assert (refused.exit_code, refused.exception.code) == (1, "E_SCHEMA_NEWER")
    rebuilt = invoke("reindex", "--full")
    assert rebuilt.exit_code == 0, rebuilt.output
    with sqlite3.connect(env.index_dir / "wiki.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == INDEX_SCHEMA
    assert {"sys-example-1", "term-example-1"} <= index_ids(env)


def test_repair_worktrees_relinks_a_moved_copy(
    env: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with TestClient(create_app(env)) as client:
        client.headers["Authorization"] = "Bearer " + Auth(StateDB(env.state_dir)).create(
            "author", "writer", "internal"
        )
        created = client.post("/api/v1/proposals", json={"title": "Moved draft"})
        assert created.status_code == 200, created.text
    moved = tmp_path / "new-host"
    shutil.copytree(env.wiki_root, moved / "wiki", symlinks=True)
    shutil.copytree(env.state_dir, moved / "state", symlinks=True)
    for name in ("wiki", "state", "index"):
        monkeypatch.setenv(
            {"wiki": "WIKI_ROOT", "state": "STATE_DIR", "index": "INDEX_DIR"}[name],
            str(moved / name),
        )
    result = invoke("repair-worktrees")
    assert (result.exit_code, result.stdout) == (0, "Repaired 1 worktrees.\n")
    listed = GitRepo(moved / "wiki").run("worktree", "list")
    assert str((moved / "state").resolve()) in listed
    assert str(env.state_dir) not in listed


def test_repair_worktrees_refuses_a_partial_state_copy(
    env: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    GitRepo(env.wiki_root).add_worktree(env.state_dir / "worktrees" / "abcdef", "proposal/abcdef")
    shutil.rmtree(env.state_dir / "worktrees" / "abcdef")
    result = invoke("repair-worktrees")
    assert isinstance(result.exception, WikiError)
    assert (result.exit_code, result.exception.code) == (1, "E_RESTORE_INCOMPLETE")
    assert result.stdout == ""


# --- real services on loopback for the wikiagent CLI ----------------------------------


@contextmanager
def serve_wikisvc(config: Settings) -> Iterator[str]:
    """The real wikisvc over a real socket: the agent CLI builds its own httpx client."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(config), log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "wikisvc did not start"
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(30)
        listener.close()


@contextmanager
def serve_model(
    models: Callable[[], tuple[int, dict[str, Any]]], llm: FakeLLM | None = None
) -> Iterator[str]:
    """llama-server's two endpoints over real HTTP: GET /v1/models, POST chat completions."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.path == "/v1/models", self.path
            status, body = models()
            self.reply(status, json.dumps(body).encode())

        def do_POST(self) -> None:
            assert self.path == "/v1/chat/completions" and llm is not None, self.path
            content = self.rfile.read(int(self.headers["Content-Length"]))
            response = llm.handle(httpx.Request("POST", self.path, content=content))
            self.reply(response.status_code, response.content)

        def reply(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Keep pytest output to what the CLI prints."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)


def aliases(*names: str) -> tuple[int, dict[str, Any]]:
    return 200, {"object": "list", "data": [{"id": name} for name in names]}


def write_agent_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wikisvc: str, models: str, **extra: Any
) -> AgentConfig:
    settings = agent_config(tmp_path / "agent").model_dump(mode="json")
    settings["wikisvc"]["base_url"] = wikisvc
    for model in settings["models"].values():
        model["base_url"] = models
    settings.update(extra)
    path = tmp_path / "wikiagent.yaml"
    path.write_text(json.dumps(settings))
    monkeypatch.setenv("WIKIAGENT_CONFIG", str(path))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SESSION_ISSUER_TOKEN_NAME", raising=False)
    return load_config()


def closed_port() -> tuple[socket.socket, str]:
    """A bound loopback port nobody listens on: connections are refused at once."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    return holder, f"http://127.0.0.1:{holder.getsockname()[1]}"


def agent_invoke(*arguments: str) -> Any:
    return CliRunner().invoke(agent_cli, list(arguments))


# --- wikiagent check --------------------------------------------------------------------


def test_check_without_token_fails_once_and_names_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder, address = closed_port()
    with holder:
        write_agent_config(tmp_path, monkeypatch, address, address + "/v1")
        monkeypatch.delenv("WIKIAGENT_TOKEN", raising=False)
        result = agent_invoke("check", "--dependencies-only")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Not ready: Set WIKIAGENT_TOKEN to a writer kind=agent token\n"


def test_check_wait_retries_until_the_deadline_and_reports_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder, address = closed_port()
    with holder:
        write_agent_config(tmp_path, monkeypatch, address, address + "/v1")
        monkeypatch.setenv("WIKIAGENT_TOKEN", "not-checked-yet")
        started = time.monotonic()
        result = agent_invoke("check", "--dependencies-only", "--wait", "0.6")
        elapsed = time.monotonic() - started
    assert result.exit_code == 1
    assert result.stdout == ""
    # Two refused attempts (at 0 and at the deadline), one line: the same reason is not repeated.
    assert result.stderr == "Not ready: ConnectError\n"
    assert 0.6 <= elapsed < 1.8


def test_check_wait_rejects_a_wait_outside_its_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder, address = closed_port()
    with holder:
        write_agent_config(tmp_path, monkeypatch, address, address + "/v1")
        for wait in ("-1", "3601"):
            result = agent_invoke("check", "--wait", wait)
            assert result.exit_code == 2
            assert "Invalid value for '--wait'" in result.stderr


def test_check_wait_survives_a_loading_model_and_reports_each_reason_once(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = Auth(StateDB(config.state_dir)).create("wikiagent", "writer", "internal")
    monkeypatch.setenv("WIKIAGENT_TOKEN", token)
    # llama-server answers 503 while it loads weights, then lists its aliases; the first
    # list here still lacks the configured one, as after a model swap.
    answers = [
        (503, {"error": {"message": "Loading model"}}),
        (503, {"error": {"message": "Loading model"}}),
        aliases("other-model"),
    ]
    served: list[int] = []

    def models() -> tuple[int, dict[str, Any]]:
        served.append(1)
        if answers:
            return answers.pop(0)
        return aliases("fake-planner", "fake-reviewer", "fake-chat")

    with serve_wikisvc(config) as wikisvc, serve_model(models) as model_url:
        write_agent_config(tmp_path, monkeypatch, wikisvc, model_url)
        result = agent_invoke("check", "--dependencies-only", "--wait", "30")
    assert result.exit_code == 0, result.output
    assert result.stderr == (
        "Not ready: HTTP 503: /v1/models\n"
        "Not ready: planner: configured model alias is absent from /models\n"
    )
    assert result.stdout == (
        "wikisvc: ready; agent token: valid\n"
        "planner model: ready\n"
        "reviewer model: ready\n"
        "chat model: ready\n"
    )
    assert token not in result.output
    assert len(served) == 6  # Three failed rounds, then each distinct model once.


def test_check_reports_a_token_wikisvc_refuses_by_status_and_path(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIKIAGENT_TOKEN", "revoked-or-mistyped")
    with serve_wikisvc(config) as wikisvc, serve_model(lambda: aliases()) as model_url:
        write_agent_config(tmp_path, monkeypatch, wikisvc, model_url)
        result = agent_invoke("check", "--dependencies-only")
    assert result.exit_code == 1
    assert result.stderr == "Not ready: HTTP 401: /api/v1/whoami\n"
    assert "revoked-or-mistyped" not in result.output


# --- wikiagent eval ---------------------------------------------------------------------


def write_scenario(directory: Path, name: str, message: str, actions: list[str]) -> None:
    directory.mkdir(exist_ok=True)
    (directory / f"{name}.yaml").write_text(
        json.dumps(
            {
                "input": message,
                "initial_pages": [],
                "scopes": ["*"],
                "expected": {"actions": actions, "questions": []},
            },
            ensure_ascii=False,
        )
    )


def test_eval_scores_scenarios_against_the_model_over_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenarios = tmp_path / "scenarios"
    write_scenario(scenarios, "01-cancel", "Отмени план", ["cancel"])
    write_scenario(scenarios, "02-misrouted", "Что такое счёт?", ["cancel"])

    def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
        assert task == "route"
        intent = "cancel" if data["message"] == "Отмени план" else "question"
        return {"intent": intent, "clarification": None}

    llm = FakeLLM(respond, check_schema=True)
    with serve_model(lambda: aliases(), llm) as model_url:
        write_agent_config(tmp_path, monkeypatch, "http://127.0.0.1:9", model_url)
        out = tmp_path / "reports/eval.json"
        result = agent_invoke(
            "eval",
            "--role",
            "chat",
            "--model",
            "candidate-q4",
            "--scenarios",
            str(scenarios),
            "--out",
            str(out),
        )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert json.loads(out.read_text()) == report
    assert not out.with_suffix(".json.tmp").exists()
    assert report["models"] == {
        "planner": "fake-planner",
        "reviewer": "fake-reviewer",
        "chat": "candidate-q4",
    }
    assert (report["scenarios"], report["completed"], report["accuracy"]) == (2, 2, 0.5)
    assert [
        (r["scenario"], r["pass"], r["actions"], r["model_calls"]) for r in report["results"]
    ] == [
        ("01-cancel", True, ["cancel"], 1),
        ("02-misrouted", False, [], 1),
    ]
    assert report["production_ready"] is False and report["forbidden_attempts"] == 0
    assert [request["model"] for request in llm.requests] == ["candidate-q4", "candidate-q4"]


def test_eval_refuses_an_unknown_role_before_calling_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenarios = tmp_path / "scenarios"
    write_scenario(scenarios, "01-cancel", "Отмени план", ["cancel"])
    llm = FakeLLM(lambda task, data: {"intent": "cancel", "clarification": None})
    with serve_model(lambda: aliases(), llm) as model_url:
        write_agent_config(tmp_path, monkeypatch, "http://127.0.0.1:9", model_url)
        result = agent_invoke("eval", "--role", "coder", "--scenarios", str(scenarios))
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "Unknown model role"
    assert llm.requests == []


# --- wikiagent check(): addresses and refusals at the service boundary ------------------


@contextmanager
def deployment(
    config: Settings, tmp_path: Path, bind_host: str, health: dict[str, Any] | None = None
) -> Iterator[tuple[AgentConfig, httpx.Client, list[str]]]:
    """wikisvc and wikiagent as real apps behind one transport; the model lists its aliases.

    ``health`` replaces wikisvc's health answer, as a service still starting would send.
    """
    settings = agent_config(tmp_path / "agent").model_copy(
        update={"bind_host": bind_host, "bind_port": 28788}
    )
    seen: list[str] = []
    with TestClient(create_app(config)) as service:
        wiki = wiki_client(service, settings)
        with TestClient(create_agent_app(settings, wiki)) as agent:

            def route(request: httpx.Request) -> httpx.Response:
                seen.append(str(request.url))
                if request.url.host == "models":
                    status, body = aliases("fake-planner", "fake-reviewer", "fake-chat")
                    return httpx.Response(status, json=body)
                if request.url.path == "/api/v1/health" and health is not None:
                    return httpx.Response(200, json=health)
                target = service if request.url.path.startswith("/api/") else agent
                response = target.request(
                    request.method, request.url.path, headers=dict(request.headers)
                )
                return httpx.Response(response.status_code, content=response.content)

            with httpx.Client(transport=httpx.MockTransport(route)) as http:
                yield settings, http, seen


@pytest.mark.parametrize(
    "bind_host,address",
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "[::1]"),
        ("2001:db8::5", "[2001:db8::5]"),
        ("10.20.30.40", "10.20.30.40"),
        ("localhost", "localhost"),
    ],
)
def test_check_reaches_the_agent_where_it_listens(
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bind_host: str,
    address: str,
) -> None:
    monkeypatch.setenv(
        "WIKIAGENT_TOKEN", Auth(StateDB(config.state_dir)).create("agent", "writer", "internal")
    )
    monkeypatch.delenv("SESSION_ISSUER_TOKEN_NAME", raising=False)
    with deployment(config, tmp_path, bind_host) as (settings, http, seen):
        messages = check(settings, http=http)
    assert messages == [
        "wikisvc: ready; agent token: valid",
        "planner model: ready",
        "reviewer model: ready",
        "chat model: ready",
        "wikiagent: ready; authenticated API: passed",
    ]
    assert seen[-1] == f"http://{address}:28788/jobs"


def test_check_stops_before_the_token_when_wikisvc_is_not_ready(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "WIKIAGENT_TOKEN", Auth(StateDB(config.state_dir)).create("agent", "writer", "internal")
    )
    starting = {"status": "starting"}
    with (
        deployment(config, tmp_path, "127.0.0.1", starting) as (settings, http, seen),
        pytest.raises(ValueError, match="^wikisvc is not ready$"),
    ):
        check(settings, http=http)
    assert seen == ["http://127.0.0.1:8787/api/v1/health"]


def test_check_without_token_sends_nothing(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WIKIAGENT_TOKEN", raising=False)
    with (
        deployment(config, tmp_path, "127.0.0.1") as (settings, http, seen),
        pytest.raises(ValueError, match="^Set WIKIAGENT_TOKEN to a writer kind=agent token$"),
    ):
        check(settings, http=http)
    assert seen == []


@pytest.mark.parametrize("role,kind", [("writer", "human"), ("reviewer", "agent")])
def test_check_refuses_a_token_that_is_not_a_writer_agent(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, kind: str
) -> None:
    token = Auth(StateDB(config.state_dir)).create(
        "someone", cast(Role, role), "internal", kind=cast(Literal["agent", "human"], kind)
    )
    monkeypatch.setenv("WIKIAGENT_TOKEN", token)
    with (
        deployment(config, tmp_path, "127.0.0.1") as (settings, http, seen),
        pytest.raises(ValueError, match="^wikiagent requires a writer kind=agent token$"),
    ):
        check(settings, http=http)
    assert [url.rsplit("/", 1)[1] for url in seen] == ["health", "whoami"]


# --- SSO diagnostics: real state.db, real timedatectl lookup --------------------------


def sso_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issuer: str) -> Path:
    state = tmp_path / "state"
    Auth(StateDB(state)).create("wiki-ui", "reader", "public")
    roles = tmp_path / "roles.yaml"
    roles.write_text("groups: {wiki-readers: {role: reader, clearance: internal}}")
    monkeypatch.setenv("SESSION_ISSUER_TOKEN_NAME", "wiki-ui")
    monkeypatch.setenv("STATE_DIR", str(state))
    monkeypatch.setenv("ROLES_FILE", str(roles))
    monkeypatch.setenv("WIKI_UI_OIDC_ISSUER", issuer)
    return state / "state.db"


def timedatectl(tmp_path: Path, script: str) -> Path:
    """A stand-in for systemd's timedatectl, the only thing PATH will offer."""
    directory = tmp_path / "bin"
    directory.mkdir()
    shim = directory / "timedatectl"
    shim.write_text("#!/bin/sh\n" + script)
    shim.chmod(stat.S_IRWXU)
    return directory


def recording_client(seen: list[str]) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"issuer": "never asked"})

    return httpx.Client(transport=httpx.MockTransport(respond))


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files regardless of mode 000")
def test_unreadable_state_db_is_reported_without_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = sso_environment(tmp_path, monkeypatch, "https://idp.example/")
    database.chmod(0)
    try:
        with pytest.raises(ValueError) as raised:
            check_authentication()
    finally:
        database.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert str(raised.value) == "Cannot inspect the session issuer in local state.db"
    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)


@pytest.mark.parametrize(
    "issuer",
    ["", "http://idp.example/application/o/wiki/", "https://", "https://admin@idp.example/"],
)
def test_oidc_discovery_is_never_attempted_without_an_https_issuer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issuer: str
) -> None:
    sso_environment(tmp_path, monkeypatch, issuer)
    monkeypatch.setenv("PATH", str(timedatectl(tmp_path, "echo yes\n")))
    seen: list[str] = []
    with recording_client(seen) as http:
        messages = check_authentication(http)
    assert messages == [
        "session issuer: valid (local DB); roles: wiki-readers",
        "WARN OIDC discovery: configure an HTTPS issuer in ui.env",
        "NTP: synchronized",
    ]
    assert seen == []


@pytest.mark.parametrize(
    "script,expected",
    [
        (
            '[ "$*" = "show --property=NTPSynchronized --value" ] || exit 64\necho yes\n',
            "NTP: synchronized",
        ),
        ("echo no\n", "WARN NTP: verify clock synchronization"),
        ("echo yes\nexit 1\n", "WARN NTP: verify clock synchronization"),
        (None, "WARN NTP: verify clock synchronization"),
    ],
)
def test_ntp_state_comes_from_timedatectl_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str | None, expected: str
) -> None:
    sso_environment(tmp_path, monkeypatch, "http://plain.example/")
    if script is None:  # A minimal container without systemd: nothing on PATH.
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
    else:
        monkeypatch.setenv("PATH", str(timedatectl(tmp_path, script)))
    assert check_authentication()[-1] == expected


def test_a_hanging_timedatectl_is_abandoned_after_five_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep = shutil.which("sleep")
    assert sleep is not None
    sso_environment(tmp_path, monkeypatch, "http://plain.example/")
    # exec: the timeout kills the sleeper itself, so no orphan keeps the pipes open.
    monkeypatch.setenv("PATH", str(timedatectl(tmp_path, f"exec {sleep} 60\n")))
    started = time.monotonic()
    messages = check_authentication()
    assert messages[-1] == "WARN NTP: verify clock synchronization"
    assert 5 <= time.monotonic() - started < 15


# --- wikiagent configuration ------------------------------------------------------------


def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Path:
    settings: dict[str, Any] = {
        "models": {
            role: {"base_url": "http://models/v1", "model": "fake-" + role}
            for role in ("planner", "reviewer", "chat")
        }
    }
    settings.update(changes)
    path = tmp_path / "wikiagent.yaml"
    path.write_text(json.dumps(settings))
    monkeypatch.setenv("WIKIAGENT_CONFIG", str(path))
    for name in ("MAX_UPLOAD_MB", "SECRET_ENTROPY_THRESHOLD", "WIKIAGENT_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)
    return path


def config_errors(path: Path | None = None) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as raised:
        load_config(path)
    return [(tuple(e["loc"]), e["msg"]) for e in raised.value.errors()]


def test_config_loads_from_the_environment_path_with_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file(tmp_path, monkeypatch, heal={"windows": ["23:30-01:15", "12:00-12:30"]})
    monkeypatch.setenv("MAX_UPLOAD_MB", "64")
    monkeypatch.setenv("WIKIAGENT_STATE_DIR", str(tmp_path / "agent-state"))
    config = load_config()
    assert config.heal.windows == ["23:30-01:15", "12:00-12:30"]
    assert (config.max_upload_mb, config.state_dir) == (64, tmp_path / "agent-state")
    assert (config.bind_host, config.bind_port, config.wikisvc.token_env) == (
        "127.0.0.1",
        8788,
        "WIKIAGENT_TOKEN",
    )


@pytest.mark.parametrize(
    "window", ["1:00-06:00", "24:00-01:00", "01:60-02:00", "01:00", "01:00-06:00 "]
)
def test_config_rejects_heal_windows_not_in_hh_mm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: str
) -> None:
    config_file(tmp_path, monkeypatch, heal={"windows": ["01:00-02:00", window]})
    assert config_errors() == [
        (("heal", "windows"), "Value error, windows use HH:MM-HH:MM in server local time")
    ]


@pytest.mark.parametrize(
    "roles", [("planner", "reviewer"), ("planner", "reviewer", "chat", "coder"), ()]
)
def test_config_requires_exactly_the_three_model_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, roles: tuple[str, ...]
) -> None:
    config_file(
        tmp_path,
        monkeypatch,
        models={role: {"base_url": "http://models/v1", "model": role} for role in roles},
    )
    assert config_errors() == [((), "Value error, models must define planner, reviewer and chat")]


def test_config_rejects_unknown_keys_and_out_of_range_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config_file(tmp_path, monkeypatch, heal_enabled=False)
    assert config_errors(path) == [(("heal_enabled",), "Extra inputs are not permitted")]
    config_file(tmp_path, monkeypatch, docs_audit={"enabled": True, "max_files": 10, "paths": []})
    assert config_errors() == [(("docs_audit", "paths"), "Extra inputs are not permitted")]
    config_file(tmp_path, monkeypatch, bind_port=0)
    assert [loc for loc, _ in config_errors()] == [("bind_port",)]
    config_file(tmp_path, monkeypatch)
    for name, value, location in [
        ("MAX_UPLOAD_MB", "0", "max_upload_mb"),
        ("MAX_UPLOAD_MB", "2048", "max_upload_mb"),
        ("SECRET_ENTROPY_THRESHOLD", "0", "secret_entropy_threshold"),
    ]:
        monkeypatch.setenv(name, value)
        assert [loc for loc, _ in config_errors()] == [(location,)]
        monkeypatch.delenv(name)


def test_config_file_missing_is_an_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIKIAGENT_CONFIG", str(tmp_path / "absent.yaml"))
    with pytest.raises(FileNotFoundError):
        load_config()
