"""Refusals of proposals, review, findings and rules, driven through the real HTTP and MCP API."""

import shutil
import sqlite3
import subprocess
import uuid
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from test_mcp_http import call, error_code
from test_proposals import payload, proposal

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Principal
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.review import rule_decision
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB

SECRET = "AKIA" + "A1" * 8


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


def human(config: Settings) -> str:
    return bearer(config, "reviewer", "restricted", "human")


def worktrees(config: Settings) -> list[str]:
    root = config.state_dir / "worktrees"
    return sorted(path.name for path in root.iterdir()) if root.exists() else []


def status(client: TestClient, pid: str) -> str:
    return str(client.get(f"/api/v1/proposals/{pid}").json()["status"])


def put(client: TestClient, pid: str, data: dict[str, Any]) -> httpx.Response:
    return client.put(f"/api/v1/proposals/{pid}/pages/{data['frontmatter']['id']}", json=data)


def accept(client: TestClient, config: Settings, *pages: dict[str, Any]) -> str:
    """Create, submit and accept a proposal as a distinct human, keeping the caller's token."""
    author = client.headers["Authorization"]
    pid = proposal(client, "Accepted change")
    for data in pages:
        response = put(client, pid, data)
        assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = human(config)
    response = client.post(f"/api/v1/proposals/{pid}/accept")
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = author
    return pid


def rule_payload(
    page_id: str, summary: str, relations: dict[str, list[str]] | None = None, **extra: Any
) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {
        "id": page_id,
        "type": "rule",
        "title": "Правило " + page_id,
        "summary": summary,
        "category": "logging",
        "applies_to": ["lang:python"],
        "origin": "team",
        "relations": relations or {},
    }
    frontmatter.update(extra)
    body = (
        "## Правило\n\nЖурналируй ошибки с контекстом.\n\n"
        "## Обоснование\n\nБез контекста расследование затягивается.\n\n"
        "## Примеры\n\nlogger.exception с идентификатором запроса.\n"
    )
    return {"frontmatter": frontmatter, "body_md": body}


def operator_commit(config: Settings, files: dict[str, str], message: str) -> None:
    """Content committed to main outside wikisvc, as an editor or operator would do."""
    fs = SafeFS(config.wiki_root)
    for path, text in files.items():
        fs.write(path, text)
    GitRepo(config.wiki_root).commit(message, "operator", list(files))


# --- proposals: identifiers, visibility and creation -------------------------------------


@pytest.mark.parametrize("pid", ["not-a-proposal", "A" * 32, "0" * 31, "0" * 33])
def test_proposal_id_must_be_lowercase_hex(client: TestClient, pid: str) -> None:
    assert error(client.get(f"/api/v1/proposals/{pid}")) == (404, "E_NOT_FOUND")


def test_restricted_page_added_by_reviewer_hides_proposal_from_internal_author(
    client: TestClient, config: Settings
) -> None:
    author = client.headers["Authorization"]
    pid = proposal(client)
    client.headers["Authorization"] = bearer(config, "reviewer", "restricted")
    data = payload("term-secret", "Закрытые сведения.")
    data["frontmatter"]["sensitivity"] = "restricted"
    assert put(client, pid, data).status_code == 200
    assert [p["id"] for p in client.get(f"/api/v1/proposals/{pid}").json()["pages"]] == [
        "term-secret"
    ]
    client.headers["Authorization"] = author
    for suffix in ("", "/diff", "/validate", "/impact"):
        assert error(client.get(f"/api/v1/proposals/{pid}{suffix}")) == (404, "E_NOT_FOUND")
    assert client.get("/api/v1/proposals").json()["items"] == []


@pytest.mark.parametrize("path", ["schema/tags.yaml", "wiki/index.md", "wiki/notes.txt"])
def test_submit_rejects_branch_commit_outside_wiki_pages(
    client: TestClient, config: Settings, path: str
) -> None:
    pid = proposal(client)
    assert put(client, pid, payload()).status_code == 200
    work = config.state_dir / "worktrees" / pid
    SafeFS(work).write(path, "smuggled\n")
    GitRepo(work).commit("Edit next to the service", "operator", [path])
    assert error(client.post(f"/api/v1/proposals/{pid}/submit")) == (422, "E_PROPOSAL_PATH")
    assert status(client, pid) == "draft"


@pytest.mark.parametrize(
    "body",
    [
        {"title": "ab"},
        {"title": "x" * 201},
        {"title": "Две\nстроки"},
        {"title": "Нормальный заголовок", "description": "d" * 12001},
    ],
)
def test_create_rejects_invalid_title_or_description(
    client: TestClient, config: Settings, body: dict[str, str]
) -> None:
    assert error(client.post("/api/v1/proposals", json=body)) == (400, "E_REQUEST_INVALID")
    assert client.app.state.runtime.state.rows("SELECT pid FROM proposals") == []
    assert worktrees(config) == []


def test_mcp_create_rejects_unknown_kind(config: Settings) -> None:
    config.mcp_http_enabled = True
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.headers["Authorization"] = bearer(config)
        result = call(client, "create_proposal", {"title": "Неизвестный вид", "kind": "merge"})
        assert error_code(result) == "E_REQUEST_INVALID"
        assert client.app.state.runtime.state.rows("SELECT pid FROM proposals") == []
    assert worktrees(config) == []


def test_create_removes_worktree_when_state_db_rejects_the_row(
    client: TestClient, config: Settings
) -> None:
    database = config.state_dir / "state.db"
    database.chmod(0o444)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            client.post("/api/v1/proposals", json={"title": "Не сохранится"})
    finally:
        database.chmod(0o600)
    assert worktrees(config) == []
    assert GitRepo(config.wiki_root).run("branch", "--list", "proposal/*") == ""
    assert client.app.state.runtime.state.rows("SELECT pid FROM proposals") == []


# --- proposals: notes ----------------------------------------------------------------------


def test_notes_are_author_only_bounded_and_secret_free(
    client: TestClient, config: Settings
) -> None:
    author = client.headers["Authorization"]
    pid = proposal(client)
    endpoint = f"/api/v1/proposals/{pid}/notes"
    client.headers["Authorization"] = human(config)
    assert error(client.put(endpoint, json={"summary": "Чужие заметки"})) == (403, "E_FORBIDDEN")
    client.headers["Authorization"] = author
    assert error(client.put(endpoint, json={"summary": "x" * 100001})) == (
        400,
        "E_REQUEST_INVALID",
    )
    assert error(client.put(endpoint, json={"summary": "ключ " + SECRET})) == (
        422,
        "E_SECRET_DETECTED",
    )
    assert client.get(f"/api/v1/proposals/{pid}").json()["notes"] is None
    assert client.put(endpoint, json={"summary": "Свои заметки"}).status_code == 200
    assert client.get(f"/api/v1/proposals/{pid}").json()["notes"] == {"summary": "Свои заметки"}


# --- proposals: page writes ------------------------------------------------------------------


def test_put_requires_matching_id(client: TestClient) -> None:
    pid = proposal(client)
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload("term-other"))
    assert error(response) == (422, "E_ID_INVALID")
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


def test_put_hides_restricted_page_and_refuses_raising_sensitivity(
    client: TestClient, config: Settings
) -> None:
    pid = proposal(client)
    head = GitRepo(config.state_dir / "worktrees" / pid).head()
    hidden = payload("sys-restricted")
    assert error(put(client, pid, hidden)) == (404, "E_NOT_FOUND")
    raised = payload("term-raised")
    raised["frontmatter"]["sensitivity"] = "restricted"
    assert error(put(client, pid, raised)) == (404, "E_NOT_FOUND")
    assert GitRepo(config.state_dir / "worktrees" / pid).head() == head


def test_put_hides_restricted_page_published_after_branching(
    client: TestClient, config: Settings
) -> None:
    author = client.headers["Authorization"]
    pid = proposal(client, "Older branch")
    client.headers["Authorization"] = bearer(config, "writer", "restricted")
    classified = payload("term-classified")
    classified["frontmatter"]["sensitivity"] = "restricted"
    accept(client, config, classified)
    client.headers["Authorization"] = author
    # Absent from the older branch, the page is known only from main: no version conflict leak.
    assert error(put(client, pid, payload("term-classified"))) == (404, "E_NOT_FOUND")
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


def test_put_refuses_changing_the_type_of_an_existing_page(client: TestClient) -> None:
    pid = proposal(client)
    data = payload("term-orphan")
    data["frontmatter"]["type"] = "system"
    data["base_version"] = client.get("/api/v1/pages/term-orphan").json()["version"]
    assert error(put(client, pid, data)) == (422, "E_TYPE_UNKNOWN")
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


def test_put_refuses_path_held_by_another_page(client: TestClient, config: Settings) -> None:
    occupant = render(
        {
            "id": "term-occupant",
            "type": "term",
            "title": "Чужой файл",
            "summary": "Страница, записанная редактором по чужому пути.",
            "status": "draft",
            "sensitivity": "internal",
            "created": "2026-01-01",
            "updated": "2026-01-01",
        },
        "## Определение\n\nТекст.\n",
    )
    operator_commit(config, {"wiki/domain/glossary/occupied.md": occupant}, "Misplaced page")
    pid = proposal(client)
    assert error(put(client, pid, payload("term-occupied"))) == (422, "E_ID_DUPLICATE")
    work = SafeFS(config.state_dir / "worktrees" / pid)
    assert "term-occupant" in work.read("wiki/domain/glossary/occupied.md")


def test_put_checks_raw_path_even_when_schema_allows_any_path(
    client: TestClient, config: Settings
) -> None:
    fs = SafeFS(config.wiki_root)
    schema = fs.read("schema/page-types/source.yaml")
    relaxed = schema.replace("    pattern: '(?:raw|library)/[^\\\\]+'\n", "")
    assert relaxed != schema
    operator_commit(config, {"schema/page-types/source.yaml": relaxed}, "Relax raw_path")
    pid = proposal(client)
    data = {
        "frontmatter": {
            "id": "src-escape",
            "type": "source",
            "title": "Источник вне сырья",
            "summary": "Источник, который ссылается на файл вне каталога сырья.",
            "kind": "doc",
            "raw_path": "etc/passwd",
            "raw_sha256": "0" * 64,
            "ingested_at": "2026-01-01",
        },
        "body_md": "## Кратко\n\nТекст.\n\n## Ключевые факты\n\nТекст.\n\n"
        "## Что изменилось в вики\n\nТекст.\n",
    }
    assert error(put(client, pid, data)) == (422, "E_PATH_UNSAFE")
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


def test_put_moves_app_doc_when_parent_changes(client: TestClient, config: Settings) -> None:
    current = client.get("/api/v1/pages/appdoc-example-1-notes").json()
    pid = proposal(client)
    frontmatter = {
        key: current[key] for key in ("id", "type", "title", "summary", "sources", "sensitivity")
    }
    frontmatter["parent"] = "app-example"
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/appdoc-example-1-notes",
        json={
            "frontmatter": frontmatter,
            "body_md": current["body_md"],
            "base_version": current["version"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["parent"] == "app-example"
    work = config.state_dir / "worktrees" / pid
    assert not (work / "wiki/apps/example-1/example-1-notes.md").exists()
    assert (work / "wiki/apps/example/example-1-notes.md").is_file()
    assert GitRepo(work).run("status", "--porcelain") == ""


def test_patch_and_delete_of_missing_pages(client: TestClient) -> None:
    pid = proposal(client)
    ops = {"ops": [{"op": "set_field", "field": "title", "value": "Новое"}]}
    assert error(client.patch(f"/api/v1/proposals/{pid}/pages/term-missing", json=ops)) == (
        404,
        "E_NOT_FOUND",
    )
    assert error(client.delete(f"/api/v1/proposals/{pid}/pages/term-missing")) == (
        404,
        "E_NOT_FOUND",
    )
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


def test_patch_resolves_slug_shared_by_several_types(client: TestClient) -> None:
    pid = proposal(client)
    version = client.get("/api/v1/pages/term-example-1").json()["version"]
    response = client.patch(
        f"/api/v1/proposals/{pid}/pages/term-example-1",
        json={
            "base_version": version,
            "ops": [{"op": "set_field", "field": "title", "value": "Термин с общим слагом"}],
        },
    )
    assert response.status_code == 200, response.text
    assert (response.json()["id"], response.json()["title"]) == (
        "term-example-1",
        "Термин с общим слагом",
    )
    work = SafeFS(client.app.state.runtime.proposals.worktree(pid))
    assert "Термин с общим слагом" in work.read("wiki/domain/glossary/example-1.md")


def test_delete_checks_base_version(client: TestClient) -> None:
    pid = proposal(client)
    endpoint = f"/api/v1/proposals/{pid}/pages/term-orphan"
    stale = client.delete(endpoint, params={"base_version": "0" * 64})
    assert error(stale) == (409, "E_VERSION_CONFLICT")
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []
    version = client.get("/api/v1/pages/term-orphan").json()["version"]
    deleted = client.delete(endpoint, params={"base_version": version})
    assert deleted.json() == {"id": "term-orphan", "change": "deleted"}


def test_delete_of_page_accepted_after_branching_is_not_found(
    client: TestClient, config: Settings
) -> None:
    pid = proposal(client, "Older branch")
    accept(client, config, payload())
    assert client.get("/api/v1/pages/term-new").status_code == 200
    assert error(client.delete(f"/api/v1/proposals/{pid}/pages/term-new")) == (
        404,
        "E_NOT_FOUND",
    )
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


# --- proposals: decisions and revert -----------------------------------------------------------


def test_decide_refuses_long_comment_and_unknown_decision(
    client: TestClient, config: Settings
) -> None:
    pid = proposal(client)
    assert put(client, pid, payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = human(config)
    response = client.post(f"/api/v1/proposals/{pid}/reject", json={"reason": "x" * 12001})
    assert error(response) == (422, "E_REQUEST_INVALID")
    # No HTTP route forwards an arbitrary decision; the service still refuses one.
    actor = Principal(name="human", role="reviewer", clearance="restricted", kind="human")
    with pytest.raises(WikiError) as refused:
        client.app.state.runtime.proposals.decide(pid, actor, "merged")
    assert (refused.value.code, refused.value.status) == ("E_PROPOSAL_STATE", 400)
    assert status(client, pid) == "submitted"


def test_accept_of_agent_draft_runs_validation(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    linked = payload("term-linked", "Ссылка на [[term-ghost]].")
    assert put(client, pid, linked).status_code == 200
    head = GitRepo(config.wiki_root).head()
    client.headers["Authorization"] = human(config)
    response = client.post(f"/api/v1/proposals/{pid}/accept")
    assert error(response) == (422, "E_VALIDATION")
    assert {d["code"] for d in response.json()["error"]["details"]} == {"E_LINK_UNRESOLVED"}
    assert GitRepo(config.wiki_root).head() == head
    assert status(client, pid) == "draft"


def test_revert_requires_accepted_proposal(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    assert put(client, pid, payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = human(config)
    assert error(client.post(f"/api/v1/proposals/{pid}/revert")) == (409, "E_PROPOSAL_STATE")
    assert status(client, pid) == "submitted"


# --- proposals: reconciliation on restart --------------------------------------------------


def restarted(config: Settings, client: TestClient) -> TestClient:
    service = TestClient(create_app(config))
    service.headers.update(client.headers)
    return service


def test_restart_keeps_open_proposals_without_commits_or_awaiting_changes(
    client: TestClient, config: Settings
) -> None:
    empty = proposal(client, "Empty draft")
    changes = proposal(client, "Needs changes")
    assert put(client, changes, payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{changes}/submit").status_code == 200
    author = client.headers["Authorization"]
    client.headers["Authorization"] = human(config)
    assert client.post(
        f"/api/v1/proposals/{changes}/request-changes", json={"comment": "Уточнить"}
    ).json()["status"] == ("changes_requested")
    client.headers["Authorization"] = author
    with restarted(config, client) as service:
        first = service.get(f"/api/v1/proposals/{empty}").json()
        second = service.get(f"/api/v1/proposals/{changes}").json()
    assert (first["status"], first["last_editor"]) == ("draft", None)
    assert (second["status"], [p["id"] for p in second["pages"]]) == (
        "changes_requested",
        ["term-new"],
    )
    assert worktrees(config) == sorted([empty, changes])


def test_restart_skips_open_proposal_whose_worktree_was_lost(
    client: TestClient, config: Settings
) -> None:
    pid = proposal(client)
    assert put(client, pid, payload()).status_code == 200
    shutil.rmtree(config.state_dir / "worktrees" / pid)
    with restarted(config, client) as service:
        found = service.get(f"/api/v1/proposals/{pid}").json()
        assert (found["status"], [p["id"] for p in found["pages"]]) == ("draft", ["term-new"])
        abandoned = service.post(f"/api/v1/proposals/{pid}/abandon")
    assert abandoned.json()["status"] == "abandoned"
    assert GitRepo(config.wiki_root).run("branch", "--list", "proposal/" + pid) == ""


def test_restart_removes_worktree_left_by_failed_reject(
    client: TestClient, config: Settings
) -> None:
    pid = proposal(client)
    assert put(client, pid, payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = human(config)
    work = config.state_dir / "worktrees" / pid
    work.chmod(0o555)  # the directory cannot be emptied, e.g. files owned by another user
    try:
        with pytest.raises(subprocess.CalledProcessError):
            client.post(f"/api/v1/proposals/{pid}/reject", json={"reason": "Не нужно"})
    finally:
        work.chmod(0o755)
    assert status(client, pid) == "rejected"
    assert work.exists()
    with restarted(config, client) as service:
        assert service.get(f"/api/v1/proposals/{pid}").json()["status"] == "rejected"
    assert not work.exists()
    assert GitRepo(config.wiki_root).run("branch", "--list", "proposal/" + pid) == ""
    assert GitRepo(config.wiki_root).run("worktree", "list", "--porcelain").count("worktree ") == 1


# --- review: verify, mark-outdated, promote, deprecate ---------------------------------------


@pytest.mark.parametrize("reason", ["   ", "x" * 1001, "ключ " + SECRET])
def test_mark_outdated_requires_short_secret_free_reason(
    client: TestClient, config: Settings, reason: str
) -> None:
    head = GitRepo(config.wiki_root).head()
    client.headers["Authorization"] = human(config)
    response = client.post("/api/v1/pages/term-orphan/mark-outdated", json={"reason": reason})
    assert error(response) == (400, "E_REQUEST_INVALID")
    assert client.get("/api/v1/pages/term-orphan").json()["status"] == "draft"
    assert GitRepo(config.wiki_root).head() == head


def test_verify_rule_runs_full_page_validation(client: TestClient, config: Settings) -> None:
    fs = SafeFS(config.wiki_root)
    incomplete = fs.read("wiki/rules/conv-example-1.md").split("## Обоснование")[0]
    operator_commit(config, {"wiki/rules/conv-example-1.md": incomplete}, "Edit rule by hand")
    head = GitRepo(config.wiki_root).head()
    client.headers["Authorization"] = human(config)
    response = client.post("/api/v1/pages/rule-conv-example-1/verify")
    assert error(response) == (422, "E_SECTION_MISSING")
    assert GitRepo(config.wiki_root).head() == head
    assert fs.read("wiki/rules/conv-example-1.md") == incomplete
    verified = client.post("/api/v1/pages/rule-conv-example-2/verify")
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"


def test_promote_and_deprecate_refusals(client: TestClient, config: Settings) -> None:
    head = GitRepo(config.wiki_root).head()
    client.headers["Authorization"] = human(config)
    assert error(client.post("/api/v1/rules/term-orphan/promote", json={})) == (
        422,
        "E_RULE_FIELDS",
    )
    unknown = client.post("/api/v1/rules/rule-conv-example-1/promote", json={"status": "x"})
    assert error(unknown) == (400, "E_REQUEST_INVALID")
    assert error(
        client.post("/api/v1/rules/rule-conv-example-1/promote", json={"level": "idea"})
    ) == (400, "E_REQUEST_INVALID")
    assert error(
        client.post("/api/v1/rules/rule-conv-example-1/deprecate", json={"reason": "   "})
    ) == (400, "E_REQUEST_INVALID")
    assert GitRepo(config.wiki_root).head() == head
    assert client.get("/api/v1/rules/rule-conv-example-1").json()["lifecycle"] == "active"


@pytest.mark.parametrize(
    "values,code",
    [({"status": "verified"}, "E_REQUEST_INVALID"), ({"level": "idea"}, "E_RULE_FIELDS")],
)
def test_rule_decision_rechecks_fields_behind_the_api_model(
    client: TestClient, values: dict[str, str], code: str
) -> None:
    # The HTTP models reject these earlier; the shared transformation must not trust callers.
    rt = client.app.state.runtime
    actor = Principal(name="human", role="reviewer", clearance="restricted", kind="human")
    page = rt.pages.page("rule-conv-example-1", actor)
    with pytest.raises(WikiError) as refused:
        rule_decision(page, actor, "promote", values)
    assert refused.value.code == code


# --- rules -----------------------------------------------------------------------------------


def test_rule_endpoint_is_only_for_rules(client: TestClient) -> None:
    assert error(client.get("/api/v1/rules/term-orphan")) == (404, "E_NOT_FOUND")


def test_related_rules_beyond_token_budget_are_listed_as_omitted(config: Settings) -> None:
    config.chars_per_token = 1
    with TestClient(create_app(config)) as client:
        client.headers["Authorization"] = bearer(config)
        thesis = "Журналируй каждую ошибку вместе с идентификатором запроса и пользователя, " * 2
        related = [f"rule-related-{index}" for index in range(1, 5)]
        accept(
            client,
            config,
            *(rule_payload(page_id, thesis.strip()[:150]) for page_id in related),
            rule_payload("rule-root", "Корневое правило журналирования.", {"refines": related}),
        )
        result = client.get("/api/v1/rules/rule-root").json()
    assert [item["id"] for item in result["related"]] == related[:3]
    assert result["related_omitted_ids"] == related[3:]
    assert result["related_tokens"] <= 600


def test_related_rules_validation_and_scope_filter(client: TestClient, config: Settings) -> None:
    for params in ({"limit": 0}, {"limit": 51}):
        assert error(client.get("/api/v1/rules/related", params={"q": "ошибки", **params})) == (
            400,
            "E_REQUEST_INVALID",
        )
    assert error(
        client.get("/api/v1/rules/related", params={"q": "ошибки", "scopes": "lang:cobol"})
    ) == (400, "E_SCOPE_UNKNOWN")
    accept(client, config, rule_payload("rule-python-only", "Журналируй ошибки в Python."))
    python = client.get("/api/v1/rules/related", params={"q": "Python", "scopes": "lang:python"})
    assert "rule-python-only" in [r["id"] for r in python.json()["rules"]]
    dotnet = client.get("/api/v1/rules/related", params={"q": "Python", "scopes": "lang:dotnet"})
    assert "rule-python-only" not in [r["id"] for r in dotnet.json()["rules"]]


def test_proposal_impact_with_deletion_and_unpublished_targets(client: TestClient) -> None:
    pid = proposal(client)
    assert client.delete(f"/api/v1/proposals/{pid}/pages/term-orphan").status_code == 200
    target = rule_payload("rule-target", "Правило, существующее только в предложении.")
    source = rule_payload(
        "rule-source",
        "Правило со ссылками на новое и существующее правило.",
        {"depends_on": ["rule-target"], "related": ["rule-conv-example-1"]},
    )
    for data in (target, source):
        assert put(client, pid, data).status_code == 200
    response = client.get(f"/api/v1/proposals/{pid}/impact")
    assert response.status_code == 200, response.text
    assert response.json()["pages"] == []
    assert response.json()["profiles"] == ["python-fastapi"]


def test_rule_list_and_stats_parameters(client: TestClient, config: Settings) -> None:
    assert error(client.get("/api/v1/rules", params={"sort": "title"})) == (
        400,
        "E_REQUEST_INVALID",
    )
    client.headers["Authorization"] = human(config)
    for days in (0, 3651):
        assert error(client.get("/api/v1/rules/stats", params={"days": days})) == (
            400,
            "E_REQUEST_INVALID",
        )


def test_violations_need_rule_and_no_secret(client: TestClient) -> None:
    state = client.app.state.runtime.state
    for item, expected in (
        ({"rule_id": "term-orphan", "note": "Не правило"}, (404, "E_NOT_FOUND")),
        ({"rule_id": "rule-conv-example-1", "note": SECRET}, (422, "E_SECRET_DETECTED")),
        (
            {"rule_id": "rule-conv-example-1", "note": "ok", "ref": "https://u:pass@h/"},
            (422, "E_SECRET_DETECTED"),
        ),
    ):
        batch = {"items": [{"rule_id": "rule-conv-example-2", "note": "Нарушение"}, item]}
        assert error(client.post("/api/v1/rules/violations", json=batch)) == expected
    assert state.rows("SELECT * FROM violations") == []
    assert state.rows("SELECT * FROM rule_usage WHERE violations>0") == []


# --- findings ----------------------------------------------------------------------------------


def finding(**changes: Any) -> dict[str, Any]:
    return {
        "kind": "docs-audit",
        "pages": ["term-orphan"],
        "summary": "Страница без связей",
        "evidence": [{"page": "term-orphan", "quote": "Отдельное знание"}],
        **changes,
    }


def test_finding_size_secret_and_foreign_proposal(client: TestClient, config: Settings) -> None:
    state = client.app.state.runtime.state
    assert error(client.post("/api/v1/findings", json=finding(run_id="r" * 100001))) == (
        400,
        "E_REQUEST_INVALID",
    )
    assert error(client.post("/api/v1/findings", json=finding(explanation=SECRET))) == (
        422,
        "E_SECRET_DETECTED",
    )
    author = client.headers["Authorization"]
    client.headers["Authorization"] = bearer(config)
    foreign = proposal(client, "Чужое предложение")
    client.headers["Authorization"] = author
    assert error(client.post("/api/v1/findings", json=finding(proposal_pid=foreign))) == (
        403,
        "E_FORBIDDEN",
    )
    assert state.rows("SELECT id FROM findings") == []


def test_finding_dismissal_reason_and_missing_finding(client: TestClient, config: Settings) -> None:
    created = client.post("/api/v1/findings", json=finding())
    assert created.status_code == 200, created.text
    finding_id = created.json()["id"]
    client.headers["Authorization"] = human(config)
    response = client.post(
        f"/api/v1/findings/{finding_id}/dismiss", json={"reason": "токен " + SECRET}
    )
    assert error(response) == (422, "E_SECRET_DETECTED")
    assert client.get("/api/v1/findings").json()["items"][0]["status"] == "open"
    missing = client.post(f"/api/v1/findings/{'0' * 32}/dismiss", json={"reason": "Нет такой"})
    assert error(missing) == (404, "E_NOT_FOUND")
