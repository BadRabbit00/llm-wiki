import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.domain.models import Page
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


CITATION_CODES = {"E_LOCATOR_OUT_OF_RANGE", "E_QUOTE_NOT_FOUND", "W_QUOTE_UNVERIFIED"}


def citation_codes(issues: list[dict[str, Any]], page_id: str) -> list[str]:
    return [i["code"] for i in issues if i["page"] == page_id and i["code"] in CITATION_CODES]


def lint_issues(client: TestClient) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    params: dict[str, Any] = {"limit": 100}
    while True:
        response = client.get("/api/v1/lint", params=params)
        assert response.status_code == 200, response.text
        issues.extend(response.json()["issues"])
        if not response.json()["next_cursor"]:
            return issues
        params["cursor"] = response.json()["next_cursor"]


# The quote sits in chapter 2 of the EPUB and on pages 3-4 of the PDF: 3 chapters, 6 pages.
@pytest.mark.parametrize(
    "extension,unit,location,expected",
    [
        ("epub", "гл.", "2", None),
        ("epub", "гл.", "2-2", None),
        ("epub", "гл.", "2-3", None),
        ("epub", "гл.", "3-2", "E_LOCATOR_OUT_OF_RANGE"),
        ("epub", "гл.", "0", "E_LOCATOR_OUT_OF_RANGE"),
        ("epub", "гл.", "4", "E_LOCATOR_OUT_OF_RANGE"),
        ("pdf", "стр.", "3", None),
        ("pdf", "стр.", "3-3", None),
        ("pdf", "стр.", "3-4", None),
        ("pdf", "стр.", "4-3", "E_LOCATOR_OUT_OF_RANGE"),
        ("pdf", "стр.", "0", "E_LOCATOR_OUT_OF_RANGE"),
        ("pdf", "стр.", "7", "E_LOCATOR_OUT_OF_RANGE"),
    ],
)
def test_citation_locator_range_after_extraction(
    client: TestClient,
    config: Settings,
    extension: str,
    unit: str,
    location: str,
    expected: str | None,
) -> None:
    # Issue #10: an accepted page cites the book before its extraction is ready; once the
    # extraction lands, /lint and validation of open proposals check the locator for real.
    writer = client.headers["Authorization"]
    reviewer(client, config)
    human = client.headers["Authorization"]
    data = (Path(__file__).parent / "fixtures/books" / ("handbook." + extension)).read_bytes()
    uploaded = library(client, "handbook." + extension, data)
    registry = client.app.state.runtime.registry
    citation = (
        f'\n\n[@src-handbook {unit} {location} "Use asynchronous HTTP clients in async handlers."]'
    )
    source = {
        "id": "src-handbook",
        "type": "source",
        "title": "Test handbook",
        "summary": "Оригинальная фикстурная книга о правилах разработки.",
        "kind": "book",
        "raw_path": uploaded["path"],
        "raw_sha256": uploaded["sha256"],
        "ingested_at": "2026-10-02",
    }
    accepted_page = rule(registry, origin="book", sources=["src-handbook"])
    draft_page = make_page(
        registry,
        "rule-book-draft",
        "rule",
        title="Черновое правило из книги",
        category="logging",
        level="should",
        lifecycle="candidate",
        applies_to=["lang:python"],
        origin="book",
        priority=3,
        sources=["src-handbook"],
    )

    def put(pid: str, page: Page) -> httpx.Response:
        return client.put(
            f"/api/v1/proposals/{pid}/pages/{page.id}",
            json={
                "frontmatter": page.frontmatter.model_dump(mode="json"),
                "body_md": page.body_md + citation,
            },
        )

    client.headers["Authorization"] = writer
    first = proposal(client, "Book rule")
    response = client.put(
        f"/api/v1/proposals/{first}/pages/src-handbook",
        json={
            "frontmatter": source,
            "body_md": "## Кратко\n\nOriginal test book.\n\n## Ключевые факты\n\nAsync.\n\n## Что изменилось в вики\n\nCandidates.",
        },
    )
    assert response.status_code == 200, response.text
    response = put(first, accepted_page)
    assert response.status_code == 200, response.text
    before = client.get(f"/api/v1/proposals/{first}/validate").json()
    assert before["errors"] == []
    assert citation_codes(before["warnings"], accepted_page.id) == ["W_QUOTE_UNVERIFIED"]
    assert client.post(f"/api/v1/proposals/{first}/submit").status_code == 200
    client.headers["Authorization"] = human
    response = client.post(f"/api/v1/proposals/{first}/accept")
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = writer
    draft = proposal(client, "Book rule draft")
    response = put(draft, draft_page)
    assert response.status_code == 200, response.text
    unrelated = proposal(client, "Unrelated knowledge")
    response = client.put(f"/api/v1/proposals/{unrelated}/pages/term-new", json=payload())
    assert response.status_code == 200, response.text
    assert citation_codes(lint_issues(client), accepted_page.id) == ["W_QUOTE_UNVERIFIED"]

    client.headers["Authorization"] = human  # the uploader starts the extraction
    extract(client, uploaded["path"])
    client.headers["Authorization"] = writer
    wanted = [expected] if expected else []
    assert citation_codes(lint_issues(client), accepted_page.id) == wanted
    response = client.get(f"/api/v1/proposals/{draft}/validate")
    assert response.status_code == 200, response.text
    assert citation_codes(response.json()["errors"], draft_page.id) == wanted
    response = client.get(f"/api/v1/proposals/{unrelated}/validate")
    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    response = put(unrelated, draft_page)
    if expected:
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == expected
    else:
        assert response.status_code == 200, response.text
