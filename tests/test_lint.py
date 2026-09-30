from fastapi.testclient import TestClient
from test_proposals import reviewer

from wikisvc.config import Settings
from wikisvc.domain.markdown import parse, render
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB


def test_lint_stats_and_audit(client: TestClient, config: Settings) -> None:
    response = client.get("/api/v1/lint", params={"limit": 100}).json()
    codes = {i["code"] for i in response["issues"]}
    assert {"W_STALE_DEPENDENCY", "W_ORPHAN", "W_NO_SOURCES", "E_LINK_UNRESOLVED"} <= codes
    assert any(i["code"] == "W_ORPHAN" and i["page"] == "term-orphan" for i in response["issues"])
    assert "sys-restricted" not in str(response)
    client.get("/api/v1/context/app-example-1", params={"budget_chars": 100})
    stats = client.get("/api/v1/stats").json()
    assert stats["pages"] >= 30 and stats["delivery"]["requests"] == 1
    assert stats["delivery"]["pages_truncated"] > 0
    assert stats["pending_sources"] is None
    reviewer(client, config)
    uploaded = client.post(
        "/api/v1/raw",
        files={"file": ("pending.txt", b"New source to be ingested")},
        data={"category": "docs"},
    )
    assert uploaded.status_code == 200
    issues = client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]
    assert any(i["code"] == "W_PENDING_SOURCE" for i in issues)
    assert client.get("/api/v1/stats").json()["pending_sources"] == 1
    assert client.get("/api/v1/admin/audit").status_code == 403
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "admin", "admin", "restricted"
    )
    assert client.post("/api/v1/admin/reindex", json={"full": True}).status_code == 200
    audit = client.get("/api/v1/admin/audit", params={"action": "raw.upload"}).json()["items"]
    assert len(audit) == 1 and audit[0]["target"] == uploaded.json()["path"]


def test_all_warnings(client: TestClient, config: Settings) -> None:
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "admin", "admin", "restricted"
    )
    fs = SafeFS(config.wiki_root)
    path = "wiki/domain/glossary/orphan.md"
    metadata, body = parse(fs.read(path))
    metadata["title"] = metadata["summary"]
    metadata["relations"] = {
        "related": ["sys-example-1", "sys-example-2", "app-example-1", "app-example-2"]
    }
    fs.write(path, render(metadata, body + "\n" + "Длинный текст. " * 1000))
    dep_path = "wiki/systems/example-1.md"
    dep, dep_body = parse(fs.read(dep_path))
    dep["status"] = "outdated"
    fs.write(dep_path, render(dep, dep_body))
    bad, bad_body = parse(fs.read("wiki/domain/glossary/example-2.md"))
    bad["summary"] = "short"
    fs.write("wiki/domain/glossary/example-2.md", render(bad, bad_body))
    GitRepo(config.wiki_root).commit("Update lint fixtures", "fixtures")
    client.post("/api/v1/admin/reindex", json={"full": True})
    codes = {i["code"] for i in client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]}
    assert {"W_SUMMARY_WEAK", "W_TOO_MANY_RELATED", "W_LONG_PAGE", "W_SUPERSEDED_LINKED"} <= codes
