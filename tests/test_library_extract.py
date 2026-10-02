import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_proposals import proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.services.extractions import clean_pages, normalize_quote
from wikisvc.storage.gitrepo import GitRepo


def library(client: TestClient, name: str, data: bytes) -> dict[str, Any]:
    response = client.post(
        "/api/v1/raw", files={"file": (name, data)}, data={"category": "library"}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def extract(client: TestClient, path: str) -> dict[str, Any]:
    response = client.post("/api/v1/raw/" + path + "/extract")
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = client.app.state.runtime.extractions.status(path)
        if status["status"] in ("done", "failed"):
            assert status["status"] == "done", status
            return dict(status)
        time.sleep(0.02)
    raise AssertionError("Extraction did not finish")


@pytest.mark.parametrize("extension", ["pdf", "epub"])
def test_library_extract_outline_text_citations(
    client: TestClient, config: Settings, extension: str
) -> None:
    reviewer(client, config)
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    data = (Path(__file__).parent / "fixtures/books" / ("handbook." + extension)).read_bytes()
    uploaded = library(client, "handbook." + extension, data)
    path = uploaded["path"]
    assert uploaded["storage"] == "local" and not (config.wiki_root / path).exists()
    assert (config.state_dir / path).is_file()
    assert library(client, "other." + extension, data)["duplicate"]
    assert repo.head() == head
    repo.ensure_main()
    assert client.get("/api/v1/raw/" + path + "/text", params={"chapter": 2}).status_code == 409
    result = extract(client, path)
    assert client.post("/api/v1/raw/" + path + "/extract").json()["sha256"] == result["sha256"]
    outline = client.get("/api/v1/raw/" + path + "/outline").json()
    assert len(outline["chapters"]) == 3
    text = client.get("/api/v1/raw/" + path + "/text", params={"chapter": 2}).json()
    quote = "Use asynchronous HTTP clients in async handlers."
    assert (
        quote in text["text"]
        and "structured logs" not in text["text"]
        and "type hints" not in text["text"]
    )
    fragment = client.get(
        "/api/v1/raw/" + path + "/text", params={"chapter": 2, "max_chars": 20}
    ).json()
    rest = client.get(
        "/api/v1/raw/" + path + "/text",
        params={"pages": fragment["next_pages"], "offset": fragment["next_offset"]},
    ).json()
    assert fragment["text"] + rest["text"] == text["text"]
    outline["chapters"][1]["title"] = "Edited chapter title"
    assert (
        client.put(
            "/api/v1/raw/" + path + "/outline", json={"chapters": outline["chapters"]}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/raw/" + path + "/outline").json()["chapters"][1]["title"]
        == "Edited chapter title"
    )
    pid = proposal(client)
    source = {
        "id": "src-handbook",
        "type": "source",
        "title": "Test handbook",
        "summary": "Оригинальная фикстурная книга о правилах разработки.",
        "kind": "book",
        "raw_path": path,
        "raw_sha256": uploaded["sha256"],
        "ingested_at": "2026-10-02",
    }
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/src-handbook",
        json={
            "frontmatter": source,
            "body_md": "## Кратко\n\nOriginal test book.\n\n## Ключевые факты\n\nAsync.\n\n## Что изменилось в вики\n\nCandidates.",
        },
    )
    assert response.status_code == 200, response.text
    page = rule(client.app.state.runtime.registry, origin="book", sources=["src-handbook"])
    unit, location = ("стр.", 3) if extension == "pdf" else ("гл.", 2)

    def put_quote(value: str, number: int = location) -> Any:
        return client.put(
            f"/api/v1/proposals/{pid}/pages/{page.id}",
            json={
                "frontmatter": page.frontmatter.model_dump(mode="json"),
                "body_md": page.body_md + f'\n\n[@src-handbook {unit} {number} "{value}"]',
            },
        )

    assert put_quote(quote).status_code == 200
    assert (
        put_quote("A completely invented quotation from the book.").json()["error"]["code"]
        == "E_QUOTE_NOT_FOUND"
    )
    assert put_quote("word " * 31).json()["error"]["code"] == "E_QUOTE_TOO_LONG"
    assert put_quote(quote, 999).json()["error"]["code"] == "E_LOCATOR_OUT_OF_RANGE"


def test_450_pages_and_scan(client: TestClient, config: Settings) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "book_fixture", Path(__file__).parents[1] / "scripts/create_book_fixtures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reviewer(client, config)
    path = library(client, "large.pdf", module.pdf(450))["path"]
    started = time.monotonic()
    response = client.post("/api/v1/raw/" + path + "/extract")
    assert response.status_code == 202 and time.monotonic() - started < 2
    result = extract(client, path)
    assert result["pages"] == 450
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    scan = library(client, "scan.pdf", output.getvalue())["path"]
    client.post("/api/v1/raw/" + scan + "/extract")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.app.state.runtime.extractions.status(scan)
        if status["status"] == "failed":
            assert status["error"] == "E_NO_TEXT_LAYER"
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Scan should fail")


def test_text_cleanup_and_quote_normalization() -> None:
    assert normalize_quote("«Про-\nверка»\u00ad — Text") == '"проверка" - text'
    pages = [
        {
            "n": n,
            "text": f"Common Header\nChapter {n}\nUnique paragraph {n}\ncontinued line\n\n```\n  code()\n```\n{n}",
        }
        for n in range(1, 5)
    ]
    cleaned = clean_pages(pages)
    assert "Common Header" not in cleaned[0]["text"]
    assert "Unique paragraph 1 continued line" in cleaned[0]["text"]
    assert "  code()" in cleaned[0]["text"]
