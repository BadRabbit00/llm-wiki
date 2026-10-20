"""Refusal and recovery paths of wikisvc outside proposals, through HTTP, MCP and the CLI."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import TextContent
from pydantic import ValidationError
from test_mcp_http import call, error_code
from test_proposals import payload, proposal
from typer.testing import CliRunner

from wikisvc.cli import app as cli_app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml, parse, render
from wikisvc.main import create_app
from wikisvc.mcp_server import create_server
from wikisvc.services.auth import Auth
from wikisvc.services.runtime import Runtime
from wikisvc.services.schema import yaml_text
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB

ROLES = """default: {role: reader, clearance: public}
groups:
  writers: {role: writer, clearance: internal}
"""


def error(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, str(response.json()["error"]["code"])


def bearer(
    config: Settings,
    role: Literal["reader", "writer", "reviewer", "admin"] = "writer",
    clearance: Literal["public", "internal", "restricted"] = "internal",
    kind: Literal["agent", "human"] = "agent",
) -> str:
    name = f"{role}-{uuid.uuid4().hex[:8]}"
    return "Bearer " + Auth(StateDB(config.state_dir)).create(name, role, clearance, kind=kind)


def operator_commit(config: Settings, files: dict[str, str], message: str) -> None:
    """Content committed to main outside wikisvc, as an editor or operator would do."""
    fs = SafeFS(config.wiki_root)
    for path, text in files.items():
        fs.write(path, text)
    GitRepo(config.wiki_root).commit(message, "operator", list(files))


def operator_remove(config: Settings, path: str) -> None:
    repo = GitRepo(config.wiki_root)
    repo.run("rm", "--quiet", "--", path)
    repo.run("commit", "--quiet", "-m", "Remove " + path, author="operator")


def environment(config: Settings, **extra: str) -> dict[str, str]:
    return {
        "WIKI_ROOT": str(config.wiki_root),
        "STATE_DIR": str(config.state_dir),
        "INDEX_DIR": str(config.index_dir),
        **extra,
    }


def wiki_error(result: Any) -> tuple[str, int]:
    assert isinstance(result.exception, WikiError), result.output
    return result.exception.code, result.exception.status


def page_text(page_id: str, kind: str, summary: str, body: str, **extra: Any) -> str:
    metadata = {
        "id": page_id,
        "type": kind,
        "title": "Страница " + page_id,
        "summary": summary,
        "status": "draft",
        "sensitivity": "internal",
        "created": "2026-01-01",
        "updated": "2026-01-01",
        **extra,
    }
    return render(metadata, body)


# --- MCP over HTTP: the full tool set -----------------------------------------------------


@pytest.fixture
def mcp_full(config: Settings) -> Iterator[TestClient]:
    config.mcp_http_enabled = True
    config.mcp_profile = "full"
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = bearer(config, "writer", "restricted")
        yield client


def structured(client: TestClient, name: str, arguments: dict[str, object]) -> Any:
    result = call(client, name, arguments)
    assert not result.isError, result
    return result.structuredContent


def test_mcp_read_tools_match_rest(mcp_full: TestClient) -> None:
    rest = mcp_full.get
    assert structured(mcp_full, "graph_impact", {"id": "proc-example-1"}) == (
        rest("/api/v1/graph/impact/proc-example-1").json()
    )
    neighbors = structured(mcp_full, "neighbors", {"id": "app-example-1", "direction": "out"})
    assert (
        neighbors
        == rest("/api/v1/graph/neighbors/app-example-1", params={"direction": "out"}).json()
    )
    assert neighbors["nodes"][0]["id"] == "app-example-1"
    pending = structured(mcp_full, "list_pending_sources", {})
    assert pending == rest("/api/v1/sources/pending").json()
    text = structured(mcp_full, "read_source_text", {"path": "raw/docs/example.txt"})
    assert text == rest("/api/v1/raw/docs/example.txt/text").json()
    assert text["trust"] == "untrusted_external"
    template = structured(mcp_full, "get_page_template", {"type": "term"})
    assert template == rest("/api/v1/schema/page-types/term").json()
    assert template["prefix"] == "term"
    assert (
        structured(mcp_full, "lint", {"limit": 5})
        == rest("/api/v1/lint", params={"limit": 5}).json()
    )
    assert error_code(call(mcp_full, "neighbors", {"id": "app-example-1", "direction": "up"})) == (
        "E_REQUEST_INVALID"
    )


def test_mcp_write_tools_validate_and_submit(mcp_full: TestClient) -> None:
    pid = structured(mcp_full, "create_proposal", {"title": "MCP полный профиль"})["pid"]
    data = payload("term-mcp-full")
    page = structured(
        mcp_full,
        "put_page",
        {"pid": pid, "id": "term-mcp-full", **data},
    )
    assert (page["id"], page["status"]) == ("term-mcp-full", "draft")
    assert structured(mcp_full, "validate_proposal", {"pid": pid})["errors"] == []
    submitted = structured(mcp_full, "submit_proposal", {"pid": pid})
    assert (submitted["status"], [p["id"] for p in submitted["pages"]]) == (
        "submitted",
        ["term-mcp-full"],
    )
    assert error_code(call(mcp_full, "submit_proposal", {"pid": pid})) == "E_PROPOSAL_STATE"


# --- MCP: the session issuer never reaches tools ------------------------------------------------


def issuer_config(config: Settings, tmp_path: Path) -> tuple[str, str]:
    config.session_issuer_token_name = "wiki-ui"
    config.roles_file = tmp_path / "roles.yaml"
    config.roles_file.write_text(ROLES)
    auth = Auth(StateDB(config.state_dir))
    return auth.create("wiki-ui", "reader", "public"), auth.create(
        "mcp-agent", "writer", "internal"
    )


def test_stdio_credential_of_session_issuer_is_refused(
    config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, agent = issuer_config(config, tmp_path)
    runtime = Runtime(config)
    runtime.indexer.reindex()
    server = create_server(runtime, profile="full")
    monkeypatch.setenv("WIKI_TOKEN", issuer)
    for tool, arguments in (
        ("get_instructions", {}),
        ("get_page", {"id": "term-orphan"}),
        ("create_proposal", {"title": "От выпускающего"}),
    ):
        with pytest.raises(ToolError) as refused:
            asyncio.run(server.call_tool(tool, arguments))
        message = str(refused.value)
        assert json.loads(message[message.index("{") :])["error"]["code"] == "E_FORBIDDEN"
    assert StateDB(config.state_dir).rows("SELECT pid FROM proposals") == []
    monkeypatch.setenv("WIKI_TOKEN", agent)
    allowed = asyncio.run(server.call_tool("get_page", {"id": "term-orphan"}))
    assert isinstance(allowed, tuple) and allowed[1]["id"] == "term-orphan"


def test_stdio_process_refuses_session_issuer(config: Settings, tmp_path: Path) -> None:
    issuer, _ = issuer_config(config, tmp_path)

    async def run() -> tuple[bool, str]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "wikisvc.cli", "mcp"],
            env={
                **os.environ,
                **environment(
                    config,
                    WIKI_TOKEN=issuer,
                    SESSION_ISSUER_TOKEN_NAME="wiki-ui",
                    ROLES_FILE=str(config.roles_file),
                ),
            },
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            await session.initialize()
            result = await session.call_tool("get_page", {"id": "term-orphan"})
            content = result.content[0]
            assert isinstance(content, TextContent)
            return result.isError, content.text

    is_error, text = asyncio.run(run())
    assert is_error
    assert json.loads(text[text.index("{") :])["error"]["code"] == "E_FORBIDDEN"
    assert "Отдельное знание" not in text


# --- sessions, admin, inbox -----------------------------------------------------------------------


def test_session_revocation_needs_issuance_and_a_human(
    client: TestClient, config: Settings, tmp_path: Path
) -> None:
    assert error(client.delete("/api/v1/sessions/current")) == (404, "E_NOT_FOUND")
    agent = client.headers["Authorization"]
    issuer_config(config, tmp_path)
    with TestClient(create_app(config)) as service:
        service.headers["Authorization"] = agent
        assert error(service.delete("/api/v1/sessions/current")) == (403, "E_FORBIDDEN")
        assert service.get("/api/v1/whoami").status_code == 200


def test_role_map_must_keep_unmapped_users_reader(config: Settings, tmp_path: Path) -> None:
    config.session_issuer_token_name = "wiki-ui"
    config.roles_file = tmp_path / "roles.yaml"
    config.roles_file.write_text("default: {role: writer, clearance: internal}\ngroups: {}\n")
    with pytest.raises(ValueError, match="ROLES_FILE"), TestClient(create_app(config)):
        pytest.fail("A role map granting writer to everyone started")


def test_audit_needs_restricted_clearance(client: TestClient, config: Settings) -> None:
    client.headers["Authorization"] = bearer(config, "admin", "internal")
    assert error(client.get("/api/v1/admin/audit")) == (404, "E_NOT_FOUND")
    client.headers["Authorization"] = bearer(config, "admin", "restricted")
    assert client.get("/api/v1/admin/audit").json()["items"] != []


def test_inbox_counts_only_visible_work(client: TestClient, config: Settings) -> None:
    client.headers["Authorization"] = bearer(config, "writer", "restricted")
    pid = proposal(client)
    data = payload("term-private")
    data["frontmatter"]["sensitivity"] = "restricted"
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-private", json=data).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = bearer(config, "reviewer", "internal", "human")
    internal = client.get("/api/v1/inbox").json()
    assert (internal["proposals"], internal["pending_sources"]) == (0, None)
    client.headers["Authorization"] = bearer(config, "reviewer", "restricted", "human")
    restricted = client.get("/api/v1/inbox").json()
    assert (restricted["proposals"], restricted["pending_sources"]) == (1, 0)


def test_inbox_counts_pending_sources_across_pages(config: Settings) -> None:
    files = {f"raw/docs/bulk-{index:03}.txt": f"Сырьё номер {index}\n" for index in range(101)}
    operator_commit(config, files, "Bulk raw drop")
    with TestClient(create_app(config)) as client:
        client.headers["Authorization"] = bearer(config, "reviewer", "restricted", "human")
        assert client.get("/api/v1/inbox").json()["pending_sources"] == 101


def test_cors_wildcard_is_a_configuration_error(config: Settings) -> None:
    config.cors_origins = "https://wiki.example, *"
    with pytest.raises(ValueError, match="explicit origins"):
        create_app(config)
    config.cors_origins = "https://wiki.example"
    with TestClient(create_app(config)) as client:
        response = client.options(
            "/api/v1/health",
            headers={"Origin": "https://wiki.example", "Access-Control-Request-Method": "GET"},
        )
    assert response.headers["access-control-allow-origin"] == "https://wiki.example"


# --- tokens through the CLI ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "options,expected",
    [
        (["--name", "bad name"], ("E_TOKEN_NAME", 422)),
        (["--name", "valid", "--person", "@alice"], ("E_TOKEN_PERSON", 422)),
        (["--name", "valid", "--expires-at", "2030-01-01T00:00:00"], ("E_REQUEST_INVALID", 422)),
        (["--name", "valid", "--expires-at", "tomorrow"], ("E_REQUEST_INVALID", 422)),
        (["--name", "taken"], ("E_TOKEN_EXISTS", 409)),
    ],
)
def test_token_create_refusals(
    config: Settings, options: list[str], expected: tuple[str, int]
) -> None:
    Auth(StateDB(config.state_dir)).create("taken", "reader", "public")
    result = CliRunner().invoke(cli_app, ["token", "create", *options], env=environment(config))
    assert wiki_error(result) == expected
    names = [row["name"] for row in StateDB(config.state_dir).rows("SELECT name FROM tokens")]
    assert names == ["taken"]


def test_token_expiry_is_stored_in_utc(config: Settings) -> None:
    result = CliRunner().invoke(
        cli_app,
        ["token", "create", "--name", "dated", "--expires-at", "2030-01-01T03:00:00+03:00"],
        env=environment(config),
    )
    assert result.exit_code == 0, result.output
    rows = StateDB(config.state_dir).rows("SELECT expires_at FROM tokens WHERE name='dated'")
    assert rows == [{"expires_at": "2030-01-01T00:00:00+00:00"}]


# --- pages, graph, search --------------------------------------------------------------------------


def test_page_listing_and_reading_parameters(client: TestClient) -> None:
    assert error(client.get("/api/v1/pages", params={"cursor": "LTE="})) == (
        400,
        "E_CURSOR_INVALID",
    )
    assert error(client.get("/api/v1/pages/term-orphan", params={"format": "xml"})) == (
        400,
        "E_REQUEST_INVALID",
    )
    backlinks = client.get("/api/v1/pages/proc-example-1", params={"include": "backlinks"}).json()
    assert "neighbors" not in backlinks
    assert {"id": "app-example-1", "rel": "automates", "kind": "frontmatter"} in backlinks[
        "backlinks"
    ]
    neighbors = client.get("/api/v1/pages/proc-example-1", params={"include": "neighbors"}).json()
    assert "backlinks" not in neighbors
    assert "app-example-1" in [node["id"] for node in neighbors["neighbors"]["nodes"]]


def test_graph_direction_and_search_lifecycle_are_checked(client: TestClient) -> None:
    response = client.get("/api/v1/graph/neighbors/app-example-1", params={"direction": "up"})
    assert error(response) == (400, "E_REQUEST_INVALID")
    response = client.get("/api/v1/search", params={"q": "счёт", "lifecycle": "retired"})
    assert error(response) == (400, "E_REQUEST_INVALID")


def test_search_expansion_honours_filters(client: TestClient) -> None:
    query = {"q": "Процесс", "expand": True}
    expanded = client.get("/api/v1/search", params=query).json()["results"]
    assert {hit["type"] for hit in expanded if hit["via"] == "graph"} == {
        "app",
        "role",
        "source",
        "system",
    }
    filtered = client.get("/api/v1/search", params={**query, "type": "process"}).json()
    assert [(hit["id"], hit["via"]) for hit in filtered["results"]] == [("proc-example-1", "match")]


# --- validation driven by an operator-edited schema -----------------------------------------------


def test_schema_summary_limit_and_tags(client: TestClient, config: Settings) -> None:
    fs = SafeFS(config.wiki_root)
    term = load_yaml(fs.read("schema/page-types/term.yaml"))
    term["summary_max"] = 40
    operator_commit(config, {"schema/page-types/term.yaml": yaml_text(term)}, "Shorter terms")
    pid = proposal(client)
    long = payload("term-long")
    long["frontmatter"]["summary"] = "Определение длиннее сорока символов для этого типа."
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-long", json=long)
    assert error(response) == (422, "E_SUMMARY_TOO_LONG")
    tagged = payload("term-tagged")
    tagged["frontmatter"].update(summary="Короткое определение термина.", tags=["finance"])
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-tagged", json=tagged)
    assert response.status_code == 200, response.text
    assert response.json()["tags"] == ["finance"]
    tagged["frontmatter"]["tags"] = ["finance", "astrology"]
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-tagged", json=tagged)
    assert error(response) == (422, "E_TAG_UNKNOWN")


def test_schema_path_template_cannot_escape_wiki(client: TestClient, config: Settings) -> None:
    fs = SafeFS(config.wiki_root)
    term = load_yaml(fs.read("schema/page-types/term.yaml"))
    term["path_template"] = "../../outside/{slug}.md"
    operator_commit(config, {"schema/page-types/term.yaml": yaml_text(term)}, "Bad template")
    pid = proposal(client)
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-escape", json=payload("term-escape"))
    assert error(response) == (422, "E_PATH_MISMATCH")
    work = config.state_dir / "worktrees" / pid
    assert not (work.parent / "outside").exists() and not (work / "outside").exists()
    assert not (config.wiki_root.parent / "outside").exists()


def test_rule_from_a_book_needs_sources(client: TestClient) -> None:
    pid = proposal(client)
    body = "## Правило\n\nТекст.\n\n## Обоснование\n\nТекст.\n\n## Примеры\n\nТекст.\n"
    rule = {
        "frontmatter": {
            "id": "rule-from-book",
            "type": "rule",
            "title": "Правило из книги",
            "summary": "Тезис, взятый из книги без указания источника.",
            "category": "logging",
            "applies_to": ["*"],
            "origin": "book",
        },
        "body_md": body,
    }
    response = client.put(f"/api/v1/proposals/{pid}/pages/rule-from-book", json=rule)
    assert error(response) == (422, "E_RULE_FIELDS")
    assert "Правило из книги или статьи требует sources." in [
        detail["message"] for detail in response.json()["error"]["details"]
    ]


# --- indexing of raw files and broken pages ----------------------------------------------------


def raw_paths(client: TestClient) -> list[str]:
    return [
        item["path"] for item in client.get("/api/v1/raw", params={"limit": 100}).json()["items"]
    ]


def test_full_reindex_forgets_raw_file_removed_while_stopped(
    client: TestClient, config: Settings
) -> None:
    client.headers["Authorization"] = bearer(config, "reader", "restricted")
    assert raw_paths(client) == ["raw/docs/example.txt"]
    operator_remove(config, "raw/docs/example.txt")
    with TestClient(create_app(config)) as service:
        service.headers.update(client.headers)
        assert raw_paths(service) == []


def test_incremental_reindex_forgets_removed_raw_file(client: TestClient, config: Settings) -> None:
    client.headers["Authorization"] = bearer(config, "admin", "restricted")
    operator_commit(config, {"raw/docs/second.txt": "Второй файл\n"}, "Second raw")
    assert client.post("/api/v1/admin/reindex", json={"full": False}).status_code == 200
    assert raw_paths(client) == ["raw/docs/example.txt", "raw/docs/second.txt"]
    operator_remove(config, "raw/docs/example.txt")
    assert client.post("/api/v1/admin/reindex", json={"full": False}).status_code == 200
    assert raw_paths(client) == ["raw/docs/second.txt"]


def test_unreadable_raw_file_is_skipped(config: Settings) -> None:
    operator_commit(config, {"raw/docs/locked.txt": "Недоступное сырьё\n"}, "Locked raw")
    locked = config.wiki_root / "raw/docs/locked.txt"
    locked.chmod(0o000)
    try:
        with TestClient(create_app(config)) as client:
            client.headers["Authorization"] = bearer(config, "reader", "restricted")
            assert raw_paths(client) == ["raw/docs/example.txt"]
    finally:
        locked.chmod(0o644)


def test_unparseable_page_with_good_summary_is_reported_once(
    client: TestClient, config: Settings
) -> None:
    text = page_text(
        "term-broken-sensitivity",
        "term",
        "Тезис достаточной длины для страницы.",
        "## Определение\n\nТекст.\n",
        sensitivity="secret",
    )
    operator_commit(config, {"wiki/domain/glossary/broken-sensitivity.md": text}, "Bad page")
    client.headers["Authorization"] = bearer(config, "admin", "restricted")
    assert client.post("/api/v1/admin/reindex", json={"full": True}).status_code == 200
    issues = client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]
    path = "wiki/domain/glossary/broken-sensitivity.md"
    assert [i["code"] for i in issues if i["page"] == path] == ["E_FRONTMATTER_INVALID"]


# --- interrupted git operations ------------------------------------------------------------------

INTERRUPTED_REVERT = """
import os, sys
from pathlib import Path
from wikisvc.storage.gitrepo import GitRepo
repo = GitRepo(Path(sys.argv[1]))
with repo.transaction(sys.argv[3:]):
    repo.run("revert", "-m", "1", "--no-commit", sys.argv[2])
    os._exit(9)
"""

INTERRUPTED_WRITE = """
import os, sys
from pathlib import Path
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
repo = GitRepo(Path(sys.argv[1]))
with repo.transaction([sys.argv[2]]):
    SafeFS(repo.root).write(sys.argv[2], "interrupted")
    repo.run("add", "--", sys.argv[2])
    os._exit(9)
"""


def run_script(tmp_path: Path, source: str, *arguments: str) -> int:
    script = tmp_path / f"script-{uuid.uuid4().hex[:8]}.py"
    script.write_text(source)
    return subprocess.run(
        [sys.executable, str(script), *arguments], check=False, env=os.environ.copy()
    ).returncode


def test_startup_aborts_revert_interrupted_by_process_death(
    client: TestClient, config: Settings, tmp_path: Path
) -> None:
    pid = proposal(client)
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = bearer(config, "reviewer", "restricted", "human")
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200
    accepted = client.app.state.runtime.state.rows(
        "SELECT accepted_commit FROM proposals WHERE pid=?", (pid,)
    )
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    paths = ["wiki/domain/glossary/new.md", "wiki/index.md", "wiki/log.md"]
    code = run_script(
        tmp_path, INTERRUPTED_REVERT, str(config.wiki_root), accepted[0]["accepted_commit"], *paths
    )
    assert code == 9
    assert repo.git_path("REVERT_HEAD").exists()
    Runtime(config)
    assert not repo.git_path("REVERT_HEAD").exists()
    assert not repo.git_path("wikisvc-transaction.json").exists()
    assert repo.head() == head
    assert repo.run("status", "--porcelain", "--", "wiki") == ""
    repo.ensure_main()
    assert client.get("/api/v1/pages/term-new").status_code == 200


def test_write_recovers_journal_left_in_proposal_worktree(
    client: TestClient, config: Settings, tmp_path: Path
) -> None:
    pid = proposal(client)
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
    work = GitRepo(config.state_dir / "worktrees" / pid)
    interrupted = "wiki/domain/glossary/interrupted.md"
    assert run_script(tmp_path, INTERRUPTED_WRITE, str(work.root), interrupted) == 9
    assert work.git_path("wikisvc-transaction.json").exists()
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-second", json=payload("term-second"))
    assert response.status_code == 200, response.text
    assert not (work.root / interrupted).exists()
    assert not work.git_path("wikisvc-transaction.json").exists()
    assert work.run("status", "--porcelain") == ""
    pages = client.get(f"/api/v1/proposals/{pid}").json()["pages"]
    assert sorted(p["id"] for p in pages) == ["term-new", "term-second"]


# --- administrative commands ---------------------------------------------------------------------


def test_schema_upgrade_restores_relations_and_drops_legacy_types(config: Settings) -> None:
    fs = SafeFS(config.wiki_root)
    relations = load_yaml(fs.read("schema/relations.yaml"))
    del relations["conflicts_with"]
    legacy = "type: convention\nprefix: conv\npath_template: conventions/{slug}.md\ntitle_ru: Соглашение\n"
    operator_commit(
        config,
        {
            "schema/relations.yaml": yaml_text(relations),
            "schema/page-types/convention.yaml": legacy,
        },
        "Schema from an older release",
    )
    result = CliRunner().invoke(cli_app, ["schema", "upgrade"], env=environment(config))
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["removed"] == ["schema/page-types/convention.yaml"]
    assert "schema/relations.yaml" in report["updated"]
    assert not fs.path("schema/page-types/convention.yaml").exists()
    assert "conflicts_with" in load_yaml(fs.read("schema/relations.yaml"))
    assert GitRepo(config.wiki_root).head() == report["commit"]


def legacy_page(page_id: str, rule: str, **extra: Any) -> str:
    return page_text(
        page_id,
        "convention",
        "Сохраняй содержательное описание решения в коде.",
        "## Правило\n\n" + rule + "\n",
        **extra,
    )


def test_migrate_rules_converts_legacy_pages_and_references(config: Settings) -> None:
    operator_commit(
        config,
        {
            "wiki/engineering/conventions/short.md": legacy_page(
                "conv-short", "Коротко.", enforcement="manual", owner="role-example-1"
            ),
            "wiki/domain/glossary/uses-legacy.md": page_text(
                "term-uses-legacy",
                "term",
                "Термин, ссылающийся на старое правило.",
                "## Определение\n\nСм. [[conv-short]].\n",
            ),
        },
        "Legacy rules",
    )
    token = Auth(StateDB(config.state_dir)).create("migrator", "writer", "restricted")
    result = CliRunner().invoke(
        cli_app, ["migrate-rules"], env=environment(config, WIKI_TOKEN=token)
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["mapping"] == {"conv-short": "rule-conv-short"}
    assert {
        "before": "wiki/domain/glossary/uses-legacy.md",
        "path": "wiki/domain/glossary/uses-legacy.md",
    } in report["pages"]
    work = SafeFS(config.state_dir / "worktrees" / report["proposal"])
    metadata, _ = parse(work.read("wiki/rules/conv-short.md"))
    assert metadata["summary"] == "Сохраняй содержательное описание решения в коде."
    assert "enforcement" not in metadata
    assert metadata["owner"] == "role-example-1"
    assert "[[rule-conv-short]]" in work.read("wiki/domain/glossary/uses-legacy.md")
    assert not work.path("wiki/engineering/conventions/short.md").exists()


def test_migrate_rules_needs_access_to_every_page(config: Settings) -> None:
    operator_commit(
        config,
        {
            "wiki/engineering/conventions/private.md": legacy_page(
                "conv-private",
                "Закрытое правило о журналировании ошибок.",
                sensitivity="restricted",
            )
        },
        "Restricted legacy rule",
    )
    token = Auth(StateDB(config.state_dir)).create("migrator", "writer", "internal")
    result = CliRunner().invoke(
        cli_app, ["migrate-rules"], env=environment(config, WIKI_TOKEN=token)
    )
    assert wiki_error(result) == ("E_FORBIDDEN", 403)
    assert StateDB(config.state_dir).rows("SELECT pid FROM proposals") == []


def test_repair_worktrees_needs_the_main_git_directory(config: Settings, tmp_path: Path) -> None:
    plain = tmp_path / "plain-copy"
    plain.mkdir()
    result = CliRunner().invoke(
        cli_app,
        ["repair-worktrees"],
        env={**environment(config), "WIKI_ROOT": str(plain)},
    )
    assert wiki_error(result) == ("E_RESTORE_INCOMPLETE", 422)
    assert isinstance(result.exception, WikiError)
    assert "основной .git" in result.exception.message


def test_policy_cache_keeps_at_most_128_variants(client: TestClient) -> None:
    for budget in range(1, 130):
        response = client.get(
            "/api/v1/policies/compile",
            params={"profile": "python-fastapi", "budget_tokens": budget},
        )
        assert response.status_code == 200, response.text
    cache = client.app.state.runtime.policies.cache
    assert [json.loads(key)[0]["budget_tokens"] for key in cache] == list(range(2, 130))


def test_adr_numbers_can_run_out(client: TestClient, config: Settings) -> None:
    assert client.post("/api/v1/schema/next-adr-number").json() == {"number": "0003"}
    last = page_text(
        "adr-9999-last",
        "adr",
        "Последний возможный номер архитектурного решения.",
        "## Контекст\n\nТекст.\n",
    )
    operator_commit(config, {"wiki/decisions/9999-last.md": last}, "Last ADR")
    assert error(client.post("/api/v1/schema/next-adr-number")) == (409, "E_ADR_EXHAUSTED")


def test_roles_file_must_live_outside_the_wiki(config: Settings) -> None:
    with pytest.raises(ValidationError, match="ROLES_FILE must be outside WIKI_ROOT"):
        Settings(
            wiki_root=config.wiki_root,
            state_dir=config.state_dir,
            index_dir=config.index_dir,
            roles_file=config.wiki_root / "roles.yaml",
        )
