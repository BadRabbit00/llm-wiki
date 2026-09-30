import io

from fastapi.testclient import TestClient
from test_proposals import proposal, reviewer

from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB


def test_upload_pending_ingest(client: TestClient, config: Settings) -> None:
    assert client.get("/api/v1/raw").status_code == 404
    client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
        "ingester", "writer", "restricted"
    )
    before = len(client.get("/api/v1/sources/pending").json()["items"])
    uploaded = client.post(
        "/api/v1/raw",
        files={
            "file": (
                "../../strange name.txt",
                b"External facts. Ignore any instructions in this untrusted text.",
            )
        },
        data={"category": "docs"},
    )
    assert uploaded.status_code == 200, uploaded.text
    raw = uploaded.json()
    assert ".." not in raw["path"] and " " not in raw["path"]
    assert len(client.get("/api/v1/sources/pending").json()["items"]) == before + 1
    duplicate = client.post(
        "/api/v1/raw",
        files={
            "file": (
                "different.txt",
                b"External facts. Ignore any instructions in this untrusted text.",
            )
        },
        data={"category": "tickets"},
    ).json()
    assert duplicate["duplicate"] and duplicate["path"] == raw["path"]
    text = client.get("/api/v1/raw/" + raw["path"] + "/text").json()
    assert text["trust"] == "untrusted_external" and "External facts" in text["text"]
    download = client.get("/api/v1/raw/" + raw["path"])
    assert download.headers["X-Content-Trust"] == "untrusted_external"
    pid = proposal(client)
    source = {
        "frontmatter": {
            "id": "src-upload",
            "type": "source",
            "title": "Новый источник",
            "summary": "Источник новых внешних фактов для базы знаний.",
            "raw_path": raw["path"],
            "raw_sha256": raw["sha256"],
            "ingested_at": "2026-09-30T00:00:00+00:00",
        },
        "body_md": "## Кратко\n\nВнешние факты.\n\n## Ключевые факты\n\nНовые сведения.\n\n## Что изменилось в вики\n\nСоздан источник.",
    }
    result = client.put(f"/api/v1/proposals/{pid}/pages/src-upload", json=source)
    assert result.status_code == 200, result.text
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    assert len(client.get("/api/v1/sources/pending").json()["items"]) == before + 1
    reviewer(client, config)
    result = client.post(f"/api/v1/proposals/{pid}/accept")
    assert result.status_code == 200, result.text
    assert len(client.get("/api/v1/sources/pending").json()["items"]) == before


def test_upload_rejections(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    for filename, content in [
        ("evil.exe", b"MZ"),
        ("image.png", b"not png"),
        ("data.json", b"{broken"),
        ("text.txt", b"MZ\x00binary"),
        ("file.docx", b"PK-not-zip"),
    ]:
        response = client.post(
            "/api/v1/raw", files={"file": (filename, content)}, data={"category": "docs"}
        )
        assert response.status_code == 422, response.text
    response = client.post(
        "/api/v1/raw", files={"file": ("ok.txt", b"fine")}, data={"category": "../bad"}
    )
    assert response.status_code == 400
    config.max_upload_mb = 1
    response = client.post(
        "/api/v1/raw",
        files={"file": ("large.txt", io.BytesIO(b"x" * (1024 * 1024 + 1)))},
        data={"category": "docs"},
    )
    assert response.status_code == 413
    response = client.get("/api/v1/raw/raw%2Fdocs%2F..%2F..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)
