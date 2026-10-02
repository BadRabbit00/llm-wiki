from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.state_db import StateDB


def proposal(client: TestClient, title: str = "New knowledge") -> str:
    response = client.post("/api/v1/proposals", json={"title": title})
    assert response.status_code == 200, response.text
    return str(response.json()["pid"])


def payload(
    page_id: str = "term-new", text: str = "Новые факты для определения."
) -> dict[str, Any]:
    return {
        "frontmatter": {
            "id": page_id,
            "type": "term",
            "title": "Новый термин",
            "summary": "Определение нового понятия для базы знаний компании.",
            "created": "1900-01-01",
            "verified_by": "forged",
            "status": "verified",
        },
        "body_md": "## Определение\n\n" + text,
    }


def reviewer(client: TestClient, config: Settings, name: str = "reviewer") -> None:
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        name, "reviewer", "restricted", kind="human"
    )


def test_proposal_lifecycle(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    response = client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload())
    assert response.status_code == 200, response.text
    page = response.json()
    assert (
        page["status"] == "draft"
        and page["verified_by"] is None
        and page["created"] != "1900-01-01"
    )
    assert client.get("/api/v1/pages/term-new").status_code == 404
    assert client.get(f"/api/v1/proposals/{pid}/validate").json()["errors"] == []
    diff = client.get(f"/api/v1/proposals/{pid}/diff").json()
    assert diff["pages"][0]["change"] == "added"
    assert client.post(f"/api/v1/proposals/{pid}/submit").json()["status"] == "submitted"
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 403
    reviewer(client, config)
    accepted = client.post(f"/api/v1/proposals/{pid}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert client.get("/api/v1/pages/term-new").status_code == 200
    assert "term-new" in (config.wiki_root / "wiki/index.md").read_text()
    assert pid in (config.wiki_root / "wiki/log.md").read_text()
    assert not (config.state_dir / "worktrees" / pid).exists()
    GitRepo(config.wiki_root).ensure_main()
    assert client.get(f"/api/v1/proposals/{pid}/diff").json()["pages"]
    verified = client.post("/api/v1/pages/term-new/verify").json()
    assert verified["status"] == "verified" and verified["verified_by"] == "reviewer"
    assert (
        client.post(
            "/api/v1/pages/term-new/mark-outdated", json={"reason": "Изменилась система"}
        ).json()["status"]
        == "outdated"
    )


def test_patch_atomic_and_versions(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    page = client.get("/api/v1/pages/term-orphan").json()
    endpoint = f"/api/v1/proposals/{pid}/pages/term-orphan"
    assert (
        client.patch(
            endpoint, json={"ops": [{"op": "set_field", "field": "title", "value": "Changed"}]}
        ).status_code
        == 409
    )
    branch = GitRepo(config.state_dir / "worktrees" / pid)
    before = branch.head()
    bad = client.patch(
        endpoint,
        json={
            "base_version": page["version"],
            "ops": [
                {"op": "set_field", "field": "title", "value": "Changed"},
                {"op": "replace_text", "old": "missing", "new": "bad", "expect_count": 1},
            ],
        },
    )
    assert bad.status_code == 422
    assert branch.head() == before
    assert not client.get(f"/api/v1/proposals/{pid}/diff").json()["pages"]
    good = client.patch(
        endpoint,
        json={
            "base_version": page["version"],
            "ops": [
                {
                    "op": "replace_section",
                    "heading": "Определение",
                    "text": "Обновлённое определение.",
                },
                {
                    "op": "add_section",
                    "heading": "Заметки",
                    "text": "Новая заметка",
                    "after": "Определение",
                },
                {"op": "append_to_section", "heading": "Заметки", "text": "Добавление"},
                {"op": "replace_text", "old": "Новая заметка", "new": "Исправленная заметка"},
            ],
        },
    )
    assert good.status_code == 200, good.text
    assert "Исправленная заметка" in good.json()["body_md"]
    assert client.delete(f"/api/v1/proposals/{pid}/pages/sys-example-1").status_code == 422
    assert client.delete(endpoint).status_code == 200


def test_self_review_and_conflict(client: TestClient, config: Settings) -> None:
    reviewer(client, config, "author-reviewer")
    own = proposal(client)
    assert (
        client.put(f"/api/v1/proposals/{own}/pages/term-own", json=payload("term-own")).status_code
        == 200
    )
    assert client.post(f"/api/v1/proposals/{own}/submit").status_code == 200
    response = client.post(f"/api/v1/proposals/{own}/accept")
    assert response.status_code == 403 and response.json()["error"]["code"] == "E_SELF_REVIEW"
    first, second = proposal(client, "First proposal"), proposal(client, "Second proposal")
    for pid, text in [
        (first, "Первый вариант определения."),
        (second, "Второй вариант определения."),
    ]:
        assert (
            client.put(
                f"/api/v1/proposals/{pid}/pages/term-conflict", json=payload("term-conflict", text)
            ).status_code
            == 200
        )
        assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    reviewer(client, config, "other-reviewer")
    assert client.post(f"/api/v1/proposals/{first}/accept").status_code == 200
    before = GitRepo(config.wiki_root).head()
    response = client.post(f"/api/v1/proposals/{second}/accept")
    assert response.status_code == 409, response.text
    assert client.get(f"/api/v1/proposals/{second}").json()["status"] == "submitted"
    assert GitRepo(config.wiki_root).head() == before
    GitRepo(config.wiki_root).ensure_main()


def test_overlay_workflow_and_visibility(client: TestClient, config: Settings) -> None:
    pid = proposal(client)
    data = payload("term-linked", "Новые факты [[term-next]].")
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-linked", json=data).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 422
    assert (
        client.put(
            f"/api/v1/proposals/{pid}/pages/term-next", json=payload("term-next")
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    auth = client.headers["Authorization"]
    reviewer(client, config)
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/request-changes", json={"comment": "Уточнить источник"}
        ).json()["status"]
        == "changes_requested"
    )
    client.headers["Authorization"] = auth
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "restricted", "writer", "restricted"
    )
    private = proposal(client, "Restricted change")
    private_data = payload("term-private")
    private_data["frontmatter"]["sensitivity"] = "restricted"
    assert (
        client.put(f"/api/v1/proposals/{private}/pages/term-private", json=private_data).status_code
        == 200
    )
    client.headers["Authorization"] = auth
    for path in [
        f"/proposals/{private}",
        f"/proposals/{private}/diff",
        f"/proposals/{private}/validate",
    ]:
        assert client.get("/api/v1" + path).status_code == 404
    assert private not in str(client.get("/api/v1/proposals").json())
    assert client.post(f"/api/v1/proposals/{pid}/abandon").json()["status"] == "abandoned"
    assert not Path(config.state_dir / "worktrees" / pid).exists()
