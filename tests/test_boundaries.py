from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml, parse, render, sections
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
    "ops,code",
    [
        ([], "E_PATCH_INVALID"),
        ([{"op": "unknown"}], "E_PATCH_INVALID"),
        ([{"op": "set_field", "field": "id", "value": "new"}], "E_PATCH_FIELD"),
        ([{"op": "replace_section", "heading": "missing", "text": "x"}], "E_PATCH_SECTION"),
        (
            [{"op": "add_section", "heading": "Existing", "text": "x", "level": 9}],
            "E_PATCH_SECTION",
        ),
        ([{"op": "replace_text", "old": "", "new": "x"}], "E_PATCH_COUNT"),
        ([{"op": "replace_text"}], "E_PATCH_INVALID"),
        ([{"op": "append_to_section", "heading": "Existing", "text": None}], "E_PATCH_INVALID"),
    ],
)
def test_patch_failures(ops: list[dict[str, object]], code: str) -> None:
    with pytest.raises(WikiError) as error:
        apply_patch({}, "## Existing\n\nText\n", ops)
    assert error.value.code == code


PREAMBLE_BODY = "Преамбула страницы.\n\n## Existing\n\nText\n\n### Sub\n\nSub text\n"
HEADING_IN_TEXT = "Текст раздела не должен содержать заголовки его уровня или выше."


@pytest.mark.parametrize(
    "operation,message",
    [
        ({"op": "replace_section", "heading": "", "text": "x"}, "Раздел '' отсутствует"),
        ({"op": "append_to_section", "heading": "", "text": "x"}, "Раздел '' отсутствует"),
        ({"op": "replace_section", "heading": "  ", "text": "x"}, "Раздел '  ' отсутствует"),
        (
            {"op": "replace_section", "heading": "Existing", "text": "Новое\n\n## Existing\n\nx"},
            HEADING_IN_TEXT,
        ),
        (
            {"op": "append_to_section", "heading": "Existing", "text": "# Заголовок"},
            HEADING_IN_TEXT,
        ),
        ({"op": "replace_section", "heading": "Sub", "text": "### Ещё"}, HEADING_IN_TEXT),
        ({"op": "add_section", "heading": "New", "text": "x\n## Другой"}, HEADING_IN_TEXT),
        ({"op": "add_section", "heading": "New", "level": 3, "text": "  ## X"}, HEADING_IN_TEXT),
    ],
)
def test_patch_section_heading_boundaries(operation: dict[str, object], message: str) -> None:
    with pytest.raises(WikiError) as error:
        apply_patch({}, PREAMBLE_BODY, [operation])
    assert error.value.code == "E_PATCH_SECTION"
    assert error.value.message.startswith(message)


def test_patch_section_allows_lower_headings_and_code() -> None:
    _, body = apply_patch(
        {},
        PREAMBLE_BODY,
        [
            {
                "op": "replace_section",
                "heading": "Existing",
                "text": "Новое\n\n### Подраздел\n\n```md\n## В коде\n```",
            },
            {"op": "add_section", "heading": "New", "level": 3, "text": "#### Глубже"},
        ],
    )
    assert body == (
        "Преамбула страницы.\n\n## Existing\n\nНовое\n\n### Подраздел\n\n```md\n## В коде\n```"
        "\n\n### New\n\n#### Глубже\n\n"
    )
    assert [s.heading for s in sections(body)] == ["", "Existing", "Подраздел", "New"]


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


def proposal_body(client: TestClient, pid: str, page_id: str) -> str:
    pages = client.get(f"/api/v1/proposals/{pid}").json()["pages"]
    return str(next(page["body_md"] for page in pages if page["id"] == page_id))


def test_patch_api_section_edges(client: TestClient) -> None:
    pid = proposal(client)
    endpoint = f"/api/v1/proposals/{pid}/pages/term-preamble"
    content = payload("term-preamble")
    content["body_md"] = "Преамбула страницы.\n\n## Определение\n\nСтарый текст."
    assert client.put(endpoint, json=content).status_code == 200
    original = proposal_body(client, pid, "term-preamble")
    for ops in (
        [{"op": "replace_section", "heading": "", "text": "Всё тело"}],
        [{"op": "append_to_section", "heading": " ", "text": "Всё тело"}],
        [{"op": "replace_section", "heading": "Определение", "text": "x\n\n## Определение\n\ny"}],
        [{"op": "add_section", "heading": "Заметки", "text": "# Заголовок"}],
    ):
        response = client.patch(endpoint, json={"ops": ops})
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "E_PATCH_SECTION"
        assert proposal_body(client, pid, "term-preamble") == original
    allowed = client.patch(
        endpoint,
        json={
            "ops": [
                {
                    "op": "replace_section",
                    "heading": "Определение",
                    "text": "Новый текст.\n\n### Подраздел\n\nДетали.",
                }
            ]
        },
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["body_md"] == (
        "Преамбула страницы.\n\n## Определение\n\nНовый текст.\n\n### Подраздел\n\nДетали.\n"
    )
    again = client.patch(
        endpoint,
        json={"ops": [{"op": "replace_section", "heading": "Определение", "text": "Итог."}]},
    )
    assert again.status_code == 200, again.text
    assert proposal_body(client, pid, "term-preamble") == (
        "Преамбула страницы.\n\n## Определение\n\nИтог.\n"
    )


@pytest.mark.parametrize("page_id", ["term", "unknown-page"])
@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_page_id_requires_type_prefix(client: TestClient, method: str, page_id: str) -> None:
    pid = proposal(client)
    endpoint = f"/api/v1/proposals/{pid}/pages/{page_id}"
    if method == "put":
        response = client.put(endpoint, json=payload(page_id))
    elif method == "patch":
        response = client.patch(
            endpoint, json={"ops": [{"op": "set_field", "field": "title", "value": "Новое"}]}
        )
    else:
        response = client.delete(endpoint)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "E_ID_INVALID"
    assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []


@pytest.mark.parametrize("limit,status", [(0, 400), (1, 200), (100, 200), (101, 400)])
def test_paginate_limit_bounds(client: TestClient, limit: int, status: int) -> None:
    created = [proposal(client, "First page"), proposal(client, "Second page")]
    response = client.get("/api/v1/proposals", params={"limit": limit})
    assert response.status_code == status, response.text
    if status == 400:
        assert response.json()["error"]["code"] == "E_REQUEST_INVALID"
        return
    result = response.json()
    assert [item["pid"] for item in result["items"]] == created[:limit]
    assert (result["next_cursor"] is not None) is (limit < len(created))


def test_rule_thesis_and_quote_length_bounds(client: TestClient) -> None:

    pid = proposal(client)
    page = rule(client.app.state.runtime.registry, sources=["src-example-1"])

    def put_rule(summary: str, quote_words: int) -> Any:
        metadata = page.frontmatter.model_dump(mode="json")
        metadata["summary"] = summary
        quote = " ".join(["слово"] * quote_words)
        body = page.body_md + f'\n\n[@src-example-1 стр. 1 "{quote}"]'
        return client.put(
            f"/api/v1/proposals/{pid}/pages/{page.id}",
            json={"frontmatter": metadata, "body_md": body},
        )

    exact = "Т" * 160
    assert put_rule(exact, 30).status_code == 200
    assert proposal_body(client, pid, page.id).count("слово") == 30
    long_thesis = put_rule(exact + "Т", 30)
    assert long_thesis.status_code == 422
    assert long_thesis.json()["error"]["code"] == "E_SUMMARY_TOO_LONG"
    long_quote = put_rule(exact, 31)
    assert long_quote.status_code == 422
    assert long_quote.json()["error"]["code"] == "E_QUOTE_TOO_LONG"
    assert proposal_body(client, pid, page.id).count("слово") == 30
