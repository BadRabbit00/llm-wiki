import io
import zipfile
from typing import Any

from fastapi.testclient import TestClient
from test_proposals import proposal, reviewer

from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
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
            "kind": "doc",
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
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    stored = client.get("/api/v1/raw").json()["items"]
    for filename, content, code in [
        ("evil.exe", b"MZ", "E_RAW_EXTENSION"),
        ("image.png", b"not png", "E_RAW_SIGNATURE"),
        ("data.json", b"{broken", "E_RAW_SIGNATURE"),
        ("text.txt", b"MZ\x00binary", "E_RAW_SIGNATURE"),
        ("file.docx", b"PK-not-zip", "E_RAW_SIGNATURE"),
    ]:
        response = client.post(
            "/api/v1/raw", files={"file": (filename, content)}, data={"category": "docs"}
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code, filename
    response = client.post(
        "/api/v1/raw", files={"file": ("ok.txt", b"fine")}, data={"category": "../bad"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "E_RAW_CATEGORY"
    # The allowlist is the operator's narrowing, separate from the signature check:
    # a well-formed Markdown file is refused once `md` is no longer allowed.
    config.allowed_raw_ext = "txt,pdf"
    response = client.post(
        "/api/v1/raw",
        files={"file": ("notes.md", b"# Valid markdown\n")},
        data={"category": "docs"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "E_RAW_EXTENSION"
    config.max_upload_mb = 1
    response = client.post(
        "/api/v1/raw",
        files={"file": ("large.txt", io.BytesIO(b"x" * (1024 * 1024 + 1)))},
        data={"category": "docs"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "E_UPLOAD_TOO_LARGE"
    assert repo.head() == head
    assert client.get("/api/v1/raw").json()["items"] == stored
    response = client.get("/api/v1/raw/raw%2Fdocs%2F..%2F..%2F..%2Fetc%2Fpasswd")
    # SafeFS rejects `..` before the raw_files lookup that would answer 404.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "E_PATH_UNSAFE"


def epub(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip")
        archive.writestr("META-INF/container.xml", b"<container/>")
        for name, data in entries.items():
            archive.writestr(name, data)
    return stream.getvalue()


def test_epub_archive_limits(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    config.max_library_upload_mb = 1
    limit = 10 * 1024 * 1024
    header = len(b"application/epub+zip") + len(b"<container/>")

    def upload(name: str, data: bytes) -> Any:
        return client.post(
            "/api/v1/raw", files={"file": (name, data)}, data={"category": "library"}
        )

    for name, entries in [
        ("bomb.epub", {"OEBPS/zeros.txt": b"\0" * (limit - header + 1)}),
        ("parent.epub", {"../outside.xhtml": b"<html/>"}),
        ("absolute.epub", {"/etc/outside.xhtml": b"<html/>"}),
    ]:
        data = epub(entries)
        assert len(data) < 1024 * 1024
        response = upload(name, data)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "E_RAW_SIGNATURE"
    exact = upload("exact.epub", epub({"OEBPS/zeros.txt": b"\0" * (limit - header)}))
    assert exact.status_code == 200, exact.text
    assert exact.json()["path"].startswith("library/")


def test_source_hash_and_raw_path(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    first, second = (
        client.post(
            "/api/v1/raw", files={"file": (name, content)}, data={"category": "docs"}
        ).json()
        for name, content in [("first.txt", b"First source text"), ("second.txt", b"Second")]
    )
    pid = proposal(client)

    def put_source(raw_path: str, sha: str) -> Any:
        return client.put(
            f"/api/v1/proposals/{pid}/pages/src-checked",
            json={
                "frontmatter": {
                    "id": "src-checked",
                    "type": "source",
                    "kind": "doc",
                    "title": "Проверяемый источник",
                    "summary": "Источник для проверки хэша и пути файла сырья.",
                    "raw_path": raw_path,
                    "raw_sha256": sha,
                    "ingested_at": "2026-09-30T00:00:00+00:00",
                },
                "body_md": "## Кратко\n\nФакты.\n\n## Ключевые факты\n\nФакты.\n\n"
                "## Что изменилось в вики\n\nИсточник.",
            },
        )

    for raw_path, sha, status, code in [
        (first["path"], second["sha256"], 422, "E_SOURCE_HASH"),
        ("raw/../../etc/passwd", first["sha256"], 400, "E_PATH_UNSAFE"),
        ("raw/..", first["sha256"], 400, "E_PATH_UNSAFE"),
        ("/etc/passwd", first["sha256"], 422, "E_FRONTMATTER_INVALID"),
        (str(config.wiki_root / first["path"]), first["sha256"], 422, "E_FRONTMATTER_INVALID"),
    ]:
        response = put_source(raw_path, sha)
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == code
        assert client.get(f"/api/v1/proposals/{pid}").json()["pages"] == []
    accepted = put_source(first["path"], first["sha256"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["raw_sha256"] == first["sha256"]
