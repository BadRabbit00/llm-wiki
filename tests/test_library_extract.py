import time
from pathlib import Path
from typing import Any

import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.domain.markdown import normalize_quote, render
from wikisvc.services.extractions import clean_pages
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS

CITATION_WARNINGS = {"W_QUOTE_UNVERIFIED", "W_CITATION_UNPARSED", "W_NO_CITATION"}


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


def handbook_source(client: TestClient, pid: str, uploaded: dict[str, Any]) -> None:
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/src-handbook",
        json={
            "frontmatter": {
                "id": "src-handbook",
                "type": "source",
                "title": "Test handbook",
                "summary": "Оригинальная фикстурная книга о правилах разработки.",
                "kind": "book",
                "raw_path": uploaded["path"],
                "raw_sha256": uploaded["sha256"],
                "ingested_at": "2026-10-02",
            },
            "body_md": "## Кратко\n\nOriginal test book.\n\n## Ключевые факты\n\nAsync.\n\n## Что изменилось в вики\n\nCandidates.",
        },
    )
    assert response.status_code == 200, response.text


def test_short_and_unparsed_quotes(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    data = (Path(__file__).parent / "fixtures/books/handbook.pdf").read_bytes()
    uploaded = library(client, "handbook.pdf", data)
    pid = proposal(client)
    handbook_source(client, pid, uploaded)
    page = rule(client.app.state.runtime.registry, origin="book", sources=["src-handbook"])

    def put_body(citation: str) -> Any:
        return client.put(
            f"/api/v1/proposals/{pid}/pages/{page.id}",
            json={
                "frontmatter": page.frontmatter.model_dump(mode="json"),
                "body_md": page.body_md + "\n\n" + citation,
            },
        )

    def put_quote(value: str) -> Any:
        return put_body(f'[@src-handbook стр. 3 "{value}"]')

    def rejected(response: Any) -> str:
        assert response.status_code == 422, response.text
        return str(response.json()["error"]["code"])

    def own(kind: str) -> set[str]:
        result = client.get(f"/api/v1/proposals/{pid}/validate").json()[kind]
        codes = {i["code"] for i in result if i["page"] == page.id}
        # The fixture rule has unrelated warnings (aliases); compare only the citation ones.
        return codes if kind == "errors" else codes & CITATION_WARNINGS

    # The extraction is not ready yet: an empty quote used to pass with a mere warning.
    assert rejected(put_quote(" ")) == "E_QUOTE_TOO_SHORT"
    assert put_quote("два слова").status_code == 200
    assert own("warnings") == {"W_QUOTE_UNVERIFIED"}
    extract(client, uploaded["path"])
    # A blank quote normalizes to "", which is a substring of every page.
    assert rejected(put_quote(" ")) == "E_QUOTE_TOO_SHORT"
    assert rejected(put_quote("a")) == "E_QUOTE_TOO_SHORT"
    assert rejected(put_quote("слово")) == "E_QUOTE_TOO_SHORT"
    # One real word from the page is still too short to tie the rule to the passage.
    assert rejected(put_quote("asynchronous")) == "E_QUOTE_TOO_SHORT"
    # Words are counted after the same normalization the source check uses: a soft hyphen
    # does not split a word, so this is one word, though it is found in the source.
    assert rejected(put_quote("asyn\u00adchronous")) == "E_QUOTE_TOO_SHORT"
    # Two words pass the length check and then go through the source check.
    assert rejected(put_quote("два слова")) == "E_QUOTE_NOT_FOUND"
    assert put_quote("asynchronous HTTP").status_code == 200
    assert own("errors") == set() and own("warnings") == set()
    # An inner quote hides the reference from the parser, so nothing checks the quote.
    assert put_quote('Use "asynchronous" HTTP clients').status_code == 200
    assert own("errors") == set()
    assert own("warnings") == {"W_CITATION_UNPARSED", "W_NO_CITATION"}
    assert client.get(f"/api/v1/proposals/{pid}/validate").json()["errors"] == []
    # The same text inside code is an example, not a reference.
    assert (
        put_body(
            '[@src-handbook стр. 3 "asynchronous HTTP"]\n\n```\n'
            '[@src-handbook стр. 3 "Use "asynchronous" HTTP clients"]\n```'
        ).status_code
        == 200
    )
    assert own("warnings") == set()


def test_short_quote_on_existing_page(client: TestClient, config: Settings) -> None:
    writer = client.headers["Authorization"]
    reviewer(client, config)
    human = client.headers["Authorization"]
    data = (Path(__file__).parent / "fixtures/books/handbook.pdf").read_bytes()
    uploaded = library(client, "handbook.pdf", data)
    extract(client, uploaded["path"])
    runtime = client.app.state.runtime
    source = make_page(
        runtime.registry,
        "src-handbook",
        "source",
        title="Test handbook",
        raw_path=uploaded["path"],
        raw_sha256=uploaded["sha256"],
        ingested_at="2026-10-02",
    )
    page = rule(runtime.registry, origin="book", sources=["src-handbook"])
    body = page.body_md + '\n\n[@src-handbook стр. 3 " "]'
    fs = SafeFS(config.wiki_root)
    # make_page takes the page type as `kind`, so the source kind is set afterwards.
    fs.write(
        source.path,
        render({**source.frontmatter.model_dump(mode="json"), "kind": "book"}, source.body_md),
    )
    fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), body))
    # Written before the check existed, as on a live wiki.
    GitRepo(config.wiki_root).commit("Add page with a blank quote", "fixtures")
    runtime.reindex()
    issues = client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]
    assert {"E_QUOTE_TOO_SHORT", "W_NO_CITATION"} <= {
        i["code"] for i in issues if i["page"] == page.id
    }

    # A proposal that does not touch the page is not blocked by it.
    client.headers["Authorization"] = writer
    unrelated = proposal(client, "Unrelated")
    assert (
        client.put(f"/api/v1/proposals/{unrelated}/pages/term-new", json=payload()).status_code
        == 200
    )
    assert client.get(f"/api/v1/proposals/{unrelated}/validate").json()["errors"] == []
    assert client.post(f"/api/v1/proposals/{unrelated}/submit").json()["status"] == "submitted"
    client.headers["Authorization"] = human
    accepted = client.post(f"/api/v1/proposals/{unrelated}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    # Editing the page through the API keeps the blank quote out.
    client.headers["Authorization"] = writer
    pid = proposal(client, "Edit legacy rule")
    metadata = page.frontmatter.model_dump(mode="json")
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/{page.id}",
        json={
            "frontmatter": metadata,
            "body_md": body + "\n\nУточнение.",
            "base_version": client.get(f"/api/v1/pages/{page.id}").json()["version"],
        },
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "E_QUOTE_TOO_SHORT"
    # A proposal edited before the check existed: the page changes, the blank quote stays.
    worktree = runtime.proposals.worktree(pid)
    SafeFS(worktree).write(page.path, render(metadata, body + "\n\nУточнение."))
    GitRepo(worktree).commit("Edit legacy rule", "test", [page.path])
    submitted = client.post(f"/api/v1/proposals/{pid}/submit")
    assert submitted.status_code == 422
    assert submitted.json()["error"]["code"] == "E_QUOTE_TOO_SHORT"
    validation = client.get(f"/api/v1/proposals/{pid}/validate").json()
    assert {(i["code"], i["page"]) for i in validation["errors"]} == {
        ("E_QUOTE_TOO_SHORT", page.id)
    }
    assert ("W_NO_CITATION", page.id) in {(i["code"], i["page"]) for i in validation["warnings"]}
    assert client.get(f"/api/v1/proposals/{pid}").json()["status"] == "draft"
