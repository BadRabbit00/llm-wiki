from datetime import date
from pathlib import Path

import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml, parse, render
from wikisvc.domain.patch import apply_patch
from wikisvc.domain.registry import Registry
from wikisvc.domain.validate import parse_page, validate_page
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB


def test_patch_all_operations_and_nested_sections() -> None:
    metadata = {"tags": ["old"], "sources": [], "relations": {"depends_on": ["sys-old"]}}
    body = "## Parent\n\nOld text\n\n### Child\n\nChild text\n\n## Next\n\nOther text\n"
    result, changed = apply_patch(
        metadata,
        body,
        [
            {"op": "add_tag", "tag": "new"},
            {"op": "add_tag", "tag": "new"},
            {"op": "remove_tag", "tag": "old"},
            {"op": "remove_tag", "tag": "absent"},
            {"op": "add_source", "source": "src-test"},
            {"op": "add_relation", "rel": "depends_on", "target": "sys-new"},
            {"op": "remove_relation", "rel": "depends_on", "target": "sys-old"},
            {"op": "remove_relation", "rel": "related", "target": "sys-none"},
            {"op": "set_field", "field": "title", "value": "New title"},
            {"op": "replace_section", "heading": "Parent", "text": "New body"},
        ],
    )
    assert metadata["tags"] == ["old"]
    assert result["tags"] == ["new"] and result["sources"] == ["src-test"]
    assert result["relations"] == {"depends_on": ["sys-new"]}
    assert "Child" not in changed and "## Next" in changed


@pytest.mark.parametrize(
    "ops",
    [
        [],
        [{"op": "unknown"}],
        [{"op": "set_field", "field": "id", "value": "new"}],
        [{"op": "replace_section", "heading": "missing", "text": "x"}],
        [{"op": "add_section", "heading": "Existing", "text": "x", "level": 9}],
        [{"op": "replace_text", "old": "", "new": "x"}],
        [{"op": "replace_text"}],
        [{"op": "append_to_section", "heading": "Existing", "text": None}],
    ],
)
def test_patch_failures(ops: list[dict[str, object]]) -> None:
    with pytest.raises(WikiError):
        apply_patch({}, "## Existing\n\nText\n", ops)


def test_yaml_aliases_and_timestamps(registry: Registry) -> None:
    with pytest.raises(WikiError):
        load_yaml("a: &a [*a]")
    page = make_page(registry)
    data = page.frontmatter.model_dump()
    data["created"] = date(2026, 1, 1)
    assert parse_page(render(data, page.body_md)).frontmatter.created == "2026-01-01"
    data["summary"] = "First line of this sufficiently long summary\nSecond line"
    with pytest.raises(WikiError):
        parse_page(render(data, page.body_md))
    page.frontmatter.sources = ["term-not-source"]
    page.body_md += " [[invalid/path]]"
    assert {"E_ID_INVALID", "E_REL_TYPE_MISMATCH"} <= {
        problem.code for problem in validate_page(page, registry)
    }


def test_markdown_and_hidden_history(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    content = payload("term-markdown")
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/term-markdown",
        content=render(content["frontmatter"], content["body_md"]),
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 200, response.text
    page = client.get("/api/v1/pages/term-orphan").json()
    response = client.patch(
        f"/api/v1/proposals/{pid}/pages/term-orphan",
        json={
            "base_version": page["version"],
            "ops": [
                {"op": "append_to_section", "heading": "Определение", "text": "Not yet accepted."}
            ],
        },
    )
    assert response.status_code == 200
    private_commit = GitRepo(config.state_dir / "worktrees" / pid).head()
    assert client.get(f"/api/v1/pages/term-orphan/at/{private_commit}").status_code == 404
    forbidden = payload("term-known-private", "Ссылка [[sys-restricted]].")
    assert (
        client.put(f"/api/v1/proposals/{pid}/pages/term-known-private", json=forbidden).status_code
        == 404
    )
    reviewer(client, config)
    private_pid = proposal(client, "Publish declassified page")
    current = client.get("/api/v1/pages/sys-restricted").json()
    assert (
        client.patch(
            f"/api/v1/proposals/{private_pid}/pages/sys-restricted",
            json={
                "base_version": current["version"],
                "ops": [{"op": "set_field", "field": "sensitivity", "value": "internal"}],
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/proposals/{private_pid}/submit").status_code == 200
    reviewer(client, config, "second-reviewer")
    assert client.post(f"/api/v1/proposals/{private_pid}/accept").status_code == 200
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "internal", "reader", "internal"
    )
    for entry in client.get("/api/v1/pages/sys-restricted/history").json()["items"]:
        assert client.get(f"/api/v1/pages/sys-restricted/at/{entry['commit']}").status_code == 200
        original = GitRepo(config.wiki_root).show(entry["commit"], "wiki/systems/restricted.md")
        assert parse(original)[0]["sensitivity"] == "internal"
    assert client.get(f"/api/v1/proposals/{private_pid}/diff").status_code == 404


def test_reject_ttl_and_foreign_proposal(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
    auth = client.headers["Authorization"]
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "other", "writer", "internal"
    )
    assert (
        client.put(
            f"/api/v1/proposals/{pid}/pages/term-other", json=payload("term-other")
        ).status_code
        == 403
    )
    client.headers["Authorization"] = auth
    client.post(f"/api/v1/proposals/{pid}/submit")
    reviewer(client, config)
    assert (
        client.post(f"/api/v1/proposals/{pid}/reject", json={"reason": "Не подтверждено"}).json()[
            "status"
        ]
        == "rejected"
    )
    assert client.get(f"/api/v1/proposals/{pid}/diff").json()["pages"]
    stale = proposal(client)
    with StateDB(config.state_dir).connect() as db:
        db.execute("UPDATE proposals SET updated_at='2000-01-01' WHERE pid=?", (stale,))
    proposal(client, "Triggers expiry")
    assert client.get(f"/api/v1/proposals/{stale}").json()["status"] == "abandoned"
    assert not (config.state_dir / "worktrees" / stale).exists()


def test_incremental_admin_reindex_and_schema(client: TestClient, config: Settings) -> None:
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "admin", "admin", "restricted"
    )
    fs = SafeFS(config.wiki_root)
    fm, body = parse(fs.read("wiki/domain/glossary/orphan.md"))
    fm["summary"] = "Обновлённое описание независимого понятия компании."
    fs.write("wiki/domain/glossary/orphan.md", render(fm, body))
    GitRepo(config.wiki_root).commit("Change fixture", "fixtures")
    assert client.post("/api/v1/admin/reindex", json={"full": False}).status_code == 200
    assert client.get("/api/v1/pages/term-orphan").json()["summary"] == fm["summary"]
    fs.write("schema/tags.yaml", "[finance]\n")
    GitRepo(config.wiki_root).commit("Update schema", "fixtures")
    assert client.post("/api/v1/admin/reindex", json={"full": False}).status_code == 200
    assert client.get("/api/v1/schema").json()["tags"] == ["finance"]


def test_rate_limit_and_request_body(config: Settings) -> None:
    config.rate_limit_per_min = 1
    config.max_upload_mb = 1
    auth = Auth(StateDB(config.state_dir))
    token = auth.create("limited", "writer", "restricted")
    with TestClient(create_app(config)) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/api/v1/pages").status_code == 200
        assert client.get("/api/v1/pages").status_code == 429
        client.headers["Authorization"] = "Bearer " + auth.create(
            "size-check", "writer", "restricted"
        )
        assert (
            client.post("/api/v1/proposals", content=b"x" * (1024 * 1024 + 65537)).status_code
            == 413
        )
        assert client.get("/api/v1/health").status_code == 200


def test_index_symlink_and_duplicate_id(
    client: TestClient, config: Settings, tmp_path: Path
) -> None:
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "admin", "admin", "restricted"
    )
    fs = SafeFS(config.wiki_root)
    fs.write("wiki/domain/glossary/duplicate.md", fs.read("wiki/domain/glossary/orphan.md"))
    outside = tmp_path / "outside.md"
    outside.write_text("PRIVATE_OUTSIDE_CONTENT")
    (config.wiki_root / "wiki/outside.md").symlink_to(outside)
    assert client.post("/api/v1/admin/reindex", json={"full": True}).status_code == 200
    issues = client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]
    assert {"E_ID_DUPLICATE", "E_PATH_UNSAFE"} <= {i["code"] for i in issues}
    assert "PRIVATE_OUTSIDE_CONTENT" not in str(issues)
