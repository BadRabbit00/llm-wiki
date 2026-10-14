"""Parsers and page extraction on real files: the worker subprocess, the job and raw reads."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from test_documents import upload
from test_library_extract import finished, library
from test_proposals import reviewer

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal
from wikisvc.main import create_app
from wikisvc.services import extractions as extraction_module
from wikisvc.services.extract_worker import worker_env
from wikisvc.services.extractions import clean_pages
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB

CONTAINER = b'<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>'
READER = Principal(name="mcp-reader", role="reader", clearance="restricted")


def fixtures() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "book_fixture", Path(__file__).parents[1] / "scripts/create_book_fixtures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def opf(*hrefs: str, doctype: str = "", metadata: str = "") -> bytes:
    manifest = "".join(
        f'<item id="c{n}" href="{href}" media-type="application/xhtml+xml"/>'
        for n, href in enumerate(hrefs, 1)
    )
    spine = "".join(f'<itemref idref="c{n}"/>' for n in range(1, len(hrefs) + 1))
    return (
        f"{doctype}<package><metadata>{metadata}</metadata><manifest>{manifest}</manifest>"
        f"<spine>{spine}</spine></package>"
    ).encode()


def chapter(title: str, body: str = "Original chapter text.") -> bytes:
    return f"<html><body><h1>{title}</h1><p>{body}</p></body></html>".encode()


def epub(
    entries: dict[str, bytes],
    container: bytes = CONTAINER,
    stored: dict[str, bytes] | None = None,
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        for name, data in entries.items():
            archive.writestr(name, data)
        for name, data in (stored or {}).items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED)
    return stream.getvalue()


def book() -> dict[str, bytes]:
    return {"OEBPS/book.opf": opf("one.html"), "OEBPS/one.html": chapter("Chapter 1")}


def job(client: TestClient, name: str, data: bytes) -> dict[str, Any]:
    path = library(client, name, data)["path"]
    response = client.post("/api/v1/raw/" + path + "/extract")
    assert response.status_code == 202, response.text
    status = finished(client, path)
    return {"path": path, "status": status["status"], "error": status["error"]}


def error(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def fake_parser(monkeypatch: pytest.MonkeyPatch, directory: Path, name: str, source: str) -> None:
    # The parser library is the external boundary of the worker: a stand-in on PYTHONPATH
    # behaves like the real one would on a hostile or huge document.
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (name + ".py")).write_text(textwrap.dedent(source))
    monkeypatch.setenv("PYTHONPATH", str(directory) + os.pathsep + os.environ.get("PYTHONPATH", ""))


def worker(
    tmp_path: Path, file: Path, *pages: str, maximum: int = 2_000_000
) -> subprocess.CompletedProcess[bytes]:
    cwd = tmp_path / "worker-cwd"
    cwd.mkdir(exist_ok=True)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "wikisvc.services.extract_worker",
            str(file),
            "512",
            str(maximum),
            "15",
            *(("--pages", *pages) if pages else ()),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        env=worker_env(),
        timeout=120,
        check=False,
    )


LAUGHS = (
    '<!DOCTYPE package [<!ENTITY a "lol">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
)


# Each hostile book is otherwise a valid EPUB that the parser would read: expat itself does
# not fetch external DTDs, declares unused external entities silently and expands a small
# amplification, so only the DOCTYPE/ENTITY filter and the archive limits turn them away.
@pytest.mark.parametrize(
    "case",
    [
        "plain",
        "external-dtd",
        "entity-in-container",
        "external-entity",
        "billion-laughs",
        "colon-href",
        "expansion-ratio",
        "entry-at-limit",
        "entry-over-limit",
    ],
)
def test_epub_parser_rejects_entities_and_archive_bombs(
    client: TestClient, config: Settings, case: str
) -> None:
    reviewer(client, config)
    container, entries, stored = CONTAINER, book(), None
    if case == "external-dtd":
        container = b'<!DOCTYPE container SYSTEM "http://127.0.0.1:9/evil.dtd">' + CONTAINER
    elif case == "entity-in-container":
        container = (
            b'<!DOCTYPE container [<!ENTITY opf "OEBPS/book.opf">]>'
            b'<container><rootfiles><rootfile full-path="&opf;"/></rootfiles></container>'
        )
    elif case == "external-entity":
        entries["OEBPS/book.opf"] = opf(
            "one.html", doctype='<!DOCTYPE package [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        )
    elif case == "billion-laughs":
        entries["OEBPS/book.opf"] = opf("one.html", doctype=LAUGHS, metadata="<t>&d;</t>")
    elif case == "colon-href":
        entries["OEBPS/book.opf"] = opf("http://evil.example/one.html")
        entries["OEBPS/http:/evil.example/one.html"] = chapter("Chapter 1")
    elif case == "expansion-ratio":
        entries["OEBPS/zeros.bin"] = b"\0" * 1_000_000
    elif case == "entry-at-limit":
        stored = {"OEBPS/blob.bin": b"\0" * 20_000_000}
    elif case == "entry-over-limit":
        stored = {"OEBPS/blob.bin": b"\0" * 20_000_001}
    result = job(client, case + ".epub", epub(entries, container, stored))
    if case in ("plain", "entry-at-limit"):
        assert (result["status"], result["error"]) == ("done", None)
        text = client.get("/api/v1/raw/" + result["path"] + "/text", params={"pages": "1"})
        assert text.status_code == 200, text.text
        assert text.json()["text"] == "Chapter 1\n\n\n\nOriginal chapter text."
    else:
        assert (result["status"], result["error"]) == ("failed", "E_TEXT_INVALID")


def test_worker_rejects_escaping_epub_paths_and_entry_count(
    client: TestClient, config: Settings, tmp_path: Path
) -> None:
    # Upload already refuses `..`, absolute names and more than 20000 entries, so the worker's
    # own checks are reached only by a file that did not come through it: run the worker.
    reviewer(client, config)
    escapes = {
        "inside": ("one.html", "OEBPS/one.html"),
        "parent": ("../../escape.html", "../escape.html"),
        "absolute": ("/abs.html", "/abs.html"),
    }
    for name, (href, member) in escapes.items():
        file = tmp_path / (name + ".epub")
        file.write_bytes(epub({"OEBPS/book.opf": opf(href), member: chapter("Chapter 1")}))
        completed = worker(tmp_path, file, "1", "15")
        if name == "inside":
            assert completed.returncode == 0
            assert json.loads(completed.stdout)["pages"] == [
                {"n": 1, "text": "Chapter 1\n\n\n\nOriginal chapter text.", "title": "Chapter 1"}
            ]
        else:
            assert (completed.returncode, completed.stdout) == (3, b"")
            response = client.post(
                "/api/v1/raw",
                files={"file": (name + ".epub", file.read_bytes())},
                data={"category": "library"},
            )
            assert error(response) == (422, "E_RAW_SIGNATURE")
    many = tmp_path / "many.epub"
    # mimetype, container.xml, the OPF and one chapter, filled up to exactly 20000 entries.
    entries = book() | {f"OEBPS/empty/{n}.txt": b"" for n in range(20000 - 4)}
    many.write_bytes(epub(entries))
    assert worker(tmp_path, many, "1", "15").returncode == 0
    entries["OEBPS/empty/over.txt"] = b""
    many.write_bytes(epub(entries))
    over = worker(tmp_path, many, "1", "15")
    assert (over.returncode, over.stdout) == (3, b"")
    response = client.post(
        "/api/v1/raw",
        files={"file": ("many.epub", many.read_bytes())},
        data={"category": "library"},
    )
    assert error(response) == (422, "E_RAW_SIGNATURE")


def test_worker_page_batch_size_formfeed_and_missing_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = tmp_path / "notes.md"
    text.write_text("a" * 3000)
    big = worker(tmp_path, text, "1", "15", maximum=1000)
    assert (big.returncode, big.stdout) == (3, b"")
    small = worker(tmp_path, text, "1", "15", maximum=10_000)
    assert small.returncode == 0
    assert json.loads(small.stdout) == {
        "total": 1,
        "pages": [{"n": 1, "text": "a" * 3000}],
        "outline": [],
    }
    # Upload refuses control characters in text, but a form feed is a page break wherever the
    # text comes from; it beats the 4000-character fallback split.
    feed = tmp_path / "feed.txt"
    feed.write_text("first\fsecond\fthird")
    result = worker(tmp_path, feed, "2", "15")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "total": 3,
        "pages": [{"n": 2, "text": "second"}, {"n": 3, "text": "third"}],
        "outline": [],
    }
    pdf = tmp_path / "missing.pdf"
    pdf.write_bytes(b"%PDF-1.7\nmissing")
    fake_parser(monkeypatch, tmp_path / "parser", "pypdf", "raise ImportError('no pypdf')\n")
    whole = worker(tmp_path, pdf)
    paged = worker(tmp_path, pdf, "1", "15")
    assert (whole.returncode, whole.stdout, paged.returncode, paged.stdout) == (2, b"", 2, b"")


def test_pdf_nested_bookmarks_and_detached_bookmark(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    source = PdfReader(io.BytesIO(fixtures().pdf(4)))
    writer = PdfWriter()
    for page in source.pages:
        writer.add_page(page)
    part = writer.add_outline_item("Part I", 0)
    writer.add_outline_item("Section 1.1", 1, parent=part)
    writer.add_outline_item("Part II", 2)
    writer.add_outline_item("Detached note", None)  # no destination page
    output = io.BytesIO()
    writer.write(output)
    result = job(client, "nested.pdf", output.getvalue())
    assert (result["status"], result["error"]) == ("done", None)
    outline = client.get("/api/v1/raw/" + result["path"] + "/outline").json()
    assert (outline["origin"], outline["chapters"]) == (
        "bookmarks",
        [
            {"n": 1, "title": "Part I", "page_from": 1, "page_to": 1},
            {"n": 2, "title": "Section 1.1", "page_from": 2, "page_to": 2},
            {"n": 3, "title": "Part II", "page_from": 3, "page_to": 4},
        ],
    )


def test_epub_chapter_html_drops_script_and_style_and_fences_pre(
    client: TestClient, config: Settings
) -> None:
    reviewer(client, config)
    html = (
        b"<html><head><style>p { color: red }</style><script>alert(1)</script></head><body>"
        b"<h1>Chapter 1</h1><p>Before<br/>after</p><pre>  indented()\n  more()</pre>"
        b"<script>evil()</script><p>Tail</p></body></html>"
    )
    result = job(
        client, "html.epub", epub({"OEBPS/book.opf": opf("one.html"), "OEBPS/one.html": html})
    )
    assert (result["status"], result["error"]) == ("done", None)
    response = client.get("/api/v1/raw/" + result["path"] + "/text", params={"chapter": 1})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == (
        "Chapter 1\n\n\n\nBefore\n\nafter\n\n\n```\n  indented()\n  more()\n```\n\n\nTail"
    )


MD_FIRST = "# Chapter 1 Basics\n\nFirst line\ncontinued line\n\n"
MD_FILLER = "word " * 790 + "xxx"  # completes the first 4000-character page


def markdown_book() -> str:
    assert len(MD_FIRST + MD_FILLER) == 4000
    return MD_FIRST + MD_FILLER + "# Chapter 2 Advanced\n\nSecond page\nwrapped here\n"


def test_library_md_txt_docx_extract_by_pages(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    md = job(client, "book.md", markdown_book().encode())
    assert (md["status"], md["error"]) == ("done", None)
    outline = client.get("/api/v1/raw/" + md["path"] + "/outline").json()
    assert (outline["origin"], outline["chapters"]) == (
        "headings",
        [
            {"n": 1, "title": "Chapter 1 Basics", "page_from": 1, "page_to": 1},
            {"n": 2, "title": "Chapter 2 Advanced", "page_from": 2, "page_to": 2},
        ],
    )
    first = client.get("/api/v1/raw/" + md["path"] + "/text", params={"pages": "1"}).json()
    # Wrapped lines of one paragraph are joined; the blank line between paragraphs stays.
    assert first["text"] == "# Chapter 1 Basics\n\nFirst line continued line\n\n" + MD_FILLER
    second = client.get("/api/v1/raw/" + md["path"] + "/text", params={"chapter": 2}).json()
    assert second["text"] == "# Chapter 2 Advanced\n\nSecond page wrapped here"

    txt = job(client, "plain.txt", ("plain words " * 500).encode())
    assert (txt["status"], txt["error"]) == ("done", None)
    outline = client.get("/api/v1/raw/" + txt["path"] + "/outline").json()
    assert (outline["origin"], outline["chapters"]) == (
        "fallback",
        [{"n": 1, "title": "Страницы 1–2", "page_from": 1, "page_to": 2}],
    )

    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Chapter 1 Intro")
    document.add_paragraph("Body of the document.")
    output = io.BytesIO()
    document.save(output)
    word = job(client, "word.docx", output.getvalue())
    assert (word["status"], word["error"]) == ("done", None)
    text = client.get("/api/v1/raw/" + word["path"] + "/text", params={"pages": "1"}).json()
    assert text["text"] == "Chapter 1 Intro\n\nBody of the document."
    outline = client.get("/api/v1/raw/" + word["path"] + "/outline").json()
    assert outline["chapters"] == [
        {"n": 1, "title": "Chapter 1 Intro", "page_from": 1, "page_to": 1}
    ]


def test_clean_pages_joins_paragraphs_around_code_and_indent() -> None:
    # Pages under four lines are too short to tell a running header from content: their
    # repeated lines stay.
    pages = [
        {"n": 1, "text": "short\nline"},
        {"n": 2, "text": "short\nline"},
        {
            "n": 3,
            "text": "Intro line\ncontinues exam-\nple\n```\ncode()\n```\nAfter fence\n"
            "    indented()\nTail",
        },
    ]
    assert clean_pages(pages) == [
        {"n": 1, "text": "short line"},
        {"n": 2, "text": "short line"},
        {
            "n": 3,
            "text": "Intro line continues example\n```\ncode()\n```\nAfter fence\n"
            "    indented()\nTail",
        },
    ]


def test_job_limits_empty_book_and_unsupported_format(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reviewer(client, config)
    config.extract_job_max_chars = 1000
    long = job(client, "long.md", ("long text " * 300).encode())
    assert (long["status"], long["error"]) == ("failed", "E_TEXT_LIMIT")
    config.extract_job_max_chars = 50_000_000
    # A book without spine items yields an empty batch: no pages, so no text layer.
    empty = job(client, "empty.epub", epub({"OEBPS/book.opf": opf()}))
    assert (empty["status"], empty["error"]) == ("failed", "E_NO_TEXT_LAYER")
    data = library(client, "data.json", b'{"a": 1}')["path"]
    response = client.post("/api/v1/raw/" + data + "/extract")
    assert error(response) == (400, "E_TEXT_UNAVAILABLE")
    assert client.app.state.runtime.extractions.status(data) is None
    fake_parser(
        monkeypatch,
        tmp_path / "parser",
        "pypdf",
        """
        class Page:
            def extract_text(self):
                return ""

        class Pages:
            def __init__(self, count):
                self.count = count

            def __len__(self):
                return self.count

            def __getitem__(self, n):
                return Page()

        class PdfReader:
            def __init__(self, path):
                with open(path, "rb") as stream:
                    self.pages = Pages(int(stream.read().split()[-1]))
                self.outline = []
        """,
    )
    over = job(client, "over.pdf", b"%PDF-1.7\n50001")
    assert (over["status"], over["error"]) == ("failed", "E_TEXT_LIMIT")
    # 50000 pages is still allowed; walking them in empty batches runs into the job deadline.
    config.extract_job_timeout = 3
    limit = job(client, "limit.pdf", b"%PDF-1.7\n50000")
    assert (limit["status"], limit["error"]) == ("failed", "E_EXTRACT_TIMEOUT")


CRASH = """
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from wikisvc.config import Settings
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB

wiki, state, index, path = sys.argv[1:5]
config = Settings(wiki_root=Path(wiki), state_dir=Path(state), index_dir=Path(index))
client = TestClient(create_app(config)).__enter__()
client.headers["Authorization"] = "Bearer " + Auth(StateDB(config.state_dir)).create(
    "crash", "writer", "restricted"
)
assert client.post("/api/v1/raw/" + path + "/extract").status_code == 202
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    if client.app.state.runtime.extractions.status(path)["pages"] == 15:
        os._exit(0)  # the service dies between batches, with no shutdown at all
    time.sleep(0.02)
os._exit(1)
"""

PAGED = """
import time

class Page:
    def __init__(self, n):
        self.n = n

    def extract_text(self):
        if {slow} and self.n > 15:
            time.sleep(10)
        return "{version} page " + str(self.n)

class PdfReader:
    def __init__(self, path):
        self.pages = [Page(n) for n in range(1, 21)]
        self.outline = []
"""


def test_restart_resumes_unfinished_job_from_cached_batch(
    config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config.extract_job_timeout = 60  # bounds the wait below if the job is never resumed
    with TestClient(create_app(config)) as client:
        reviewer(client, config)
        uploaded = library(client, "resume.pdf", b"%PDF-1.7\nresume")
    path, sha = uploaded["path"], uploaded["sha256"]
    fake_parser(monkeypatch, tmp_path / "v1", "pypdf", PAGED.format(slow=True, version="v1"))
    script = tmp_path / "crash.py"
    script.write_text(CRASH)
    crashed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(config.wiki_root),
            str(config.state_dir),
            str(config.index_dir),
            path,
        ],
        stdin=subprocess.DEVNULL,
        timeout=180,
        check=False,
    )
    assert crashed.returncode == 0
    rows = StateDB(config.state_dir).rows(
        "SELECT status,pages FROM extractions WHERE path=?", (path,)
    )
    assert rows == [{"status": "running", "pages": 15}]
    assert SafeFS(config.state_dir).files(f"extract/{sha}/*") == [
        f"extract/{sha}/batch-000001.json"
    ]
    # A newer parser would read the first pages differently: the restart must not reparse them.
    fake_parser(monkeypatch, tmp_path / "v2", "pypdf", PAGED.format(slow=False, version="v2"))
    with TestClient(create_app(config)) as client:
        reviewer(client, config, "reviewer-after-restart")
        status = finished(client, path)
        assert (status["status"], status["pages"], status["error"]) == ("done", 20, None)
        pages = [
            client.get("/api/v1/raw/" + path + "/text", params={"pages": str(n)}).json()["text"]
            for n in (1, 15, 16, 20)
        ]
        assert pages == ["v1 page 1", "v1 page 15", "v2 page 16", "v2 page 20"]


def test_page_read_parameters(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    md = job(client, "book.md", markdown_book().encode())
    assert md["status"] == "done"
    url = "/api/v1/raw/" + md["path"] + "/text"
    both = client.get(url, params={"pages": "1", "chapter": 1})
    assert error(both) == (400, "E_REQUEST_INVALID")
    assert both.json()["error"]["message"] == "Выберите pages или chapter; max_chars: 1–60000."
    assert error(client.get(url, params={"chapter": 3})) == (422, "E_LOCATOR_OUT_OF_RANGE")
    for pages in ("one", "1-", "1-2-3"):
        response = client.get(url, params={"pages": pages})
        assert error(response) == (400, "E_REQUEST_INVALID"), pages
        assert response.json()["error"]["message"] == "pages: N или N-M."
    for pages in ("0", "3", "2-1", "1-3"):
        response = client.get(url, params={"pages": pages})
        assert error(response) == (422, "E_LOCATOR_OUT_OF_RANGE"), pages
        assert response.json()["error"]["message"] == "Диапазон страниц отсутствует."
    whole = client.get(url, params={"max_chars": 4000})
    assert error(whole) == (413, "E_TEXT_TOO_LARGE")
    assert client.get(url, params={"max_chars": 60000}).json()["pages"] == "1-2"
    # MCP read_source_pages hands its arguments to the service as they are.
    extractions = client.app.state.runtime.extractions
    for arguments in ({"max_chars": 0}, {"max_chars": 60001}, {"offset": -1}):
        with pytest.raises(WikiError) as raised:
            extractions.text(READER, md["path"], **arguments)
        assert (raised.value.code, raised.value.status) == ("E_REQUEST_INVALID", 400)
    overlapping = [
        {"n": 1, "title": "One", "page_from": 1, "page_to": 2},
        {"n": 2, "title": "Two", "page_from": 2, "page_to": 2},
    ]
    response = client.put("/api/v1/raw/" + md["path"] + "/outline", json={"chapters": overlapping})
    assert error(response) == (422, "E_LOCATOR_OUT_OF_RANGE")
    assert client.get("/api/v1/raw/" + md["path"] + "/outline").json()["origin"] == "headings"
    for sha in ("../../etc", "A" * 64, "a" * 63):
        with pytest.raises(WikiError) as raised:
            extractions.directory(sha)
        assert raised.value.code == "E_SOURCE_HASH"
    assert extractions.directory("a" * 64) == config.state_dir / "extract" / ("a" * 64)


def raw_error(client: TestClient, name: str, data: bytes, **form: str) -> tuple[int, str]:
    response = client.post(
        "/api/v1/raw", files={"file": (name, data)}, data={"category": "docs", **form}
    )
    return error(response)


def test_raw_upload_names_signatures_and_collisions(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    response = client.post(
        "/api/v1/raw", files={"file": ("report..v2.txt", b"report")}, data={"category": "docs"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["path"].rsplit("/", 1)[-1] == response.json()["sha256"][:8] + (
        "-report-v2.txt"
    )
    assert upload(client, "deep.json", ("[" * 128 + "]" * 128).encode()).endswith("-deep.json")
    assert raw_error(client, "deeper.json", ("[" * 129 + "]" * 129).encode()) == (
        422,
        "E_RAW_SIGNATURE",
    )
    assert upload(client, "conf.yaml", b"key: value\n").endswith("-conf.yaml")
    for name, data in [
        ("broken.yaml", b"key: [\n"),
        ("alias.yml", b"a: &x 1\nb: *x\n"),
        ("photo.jpg", b"GIF89a not a jpeg"),
    ]:
        assert raw_error(client, name, data) == (422, "E_RAW_SIGNATURE"), name
    assert upload(client, "photo.jpg", b"\xff\xd8\xff\xe0 jpeg").endswith("-photo.jpg")
    assert raw_error(client, "anim.gif", b"GIF89a") == (422, "E_RAW_EXTENSION")
    # An allowed extension without a known signature is still refused.
    config.allowed_raw_ext += ",gif"
    assert raw_error(client, "anim.gif", b"GIF89a") == (422, "E_RAW_SIGNATURE")
    assert raw_error(client, "noted.txt", b"noted", note="n" * 4001) == (
        400,
        "E_REQUEST_INVALID",
    )
    assert upload(client, "noted.txt", b"noted").endswith("-noted.txt")
    # A raw file committed to the wiki repository directly sits where the upload would go.
    data = b"new raw source"
    taken = f"raw/docs/{datetime.now(UTC).year}/{hashlib.sha256(data).hexdigest()[:8]}-taken.txt"
    SafeFS(config.wiki_root).write(taken, b"committed by hand")
    GitRepo(config.wiki_root).commit("Add raw file by hand", "fixtures", [taken])
    assert raw_error(client, "taken.txt", data) == (409, "E_RAW_EXISTS")
    assert (config.wiki_root / taken).read_bytes() == b"committed by hand"


def test_raw_text_reading_edges(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reviewer(client, config)
    missing = client.get("/api/v1/raw/raw/docs/missing.txt/text")
    assert error(missing) == (404, "E_NOT_FOUND")
    path = upload(client, "short.txt", b"y" * 200)
    for params in ({"max_chars": 0}, {"max_chars": 60001}, {"offset": -1}):
        response = client.get("/api/v1/raw/" + path + "/text", params=params)
        assert error(response) == (400, "E_REQUEST_INVALID"), params
        assert response.json()["error"]["message"] == "max_chars: 1–60000, offset >= 0."
    over = client.get("/api/v1/raw/" + path + "/text", params={"max_chars": 199})
    assert error(over) == (413, "E_TEXT_TOO_LARGE")
    exact = client.get("/api/v1/raw/" + path + "/text", params={"max_chars": 200})
    assert exact.status_code == 200 and exact.json()["text"] == "y" * 200
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    small = upload(client, "small.png", png + b"\0" * 16)
    assert error(client.get("/api/v1/raw/" + small + "/text")) == (400, "E_TEXT_UNAVAILABLE")
    # Over a megabyte the read is refused before the format is even looked at.
    large = upload(client, "large.png", png + b"\0" * 1_000_000)
    assert error(client.get("/api/v1/raw/" + large + "/text")) == (413, "E_TEXT_TOO_LARGE")
    legacy = "raw/docs/legacy.txt"
    SafeFS(config.wiki_root).write(legacy, "café".encode("latin-1"))
    GitRepo(config.wiki_root).commit("Add legacy raw file", "fixtures", [legacy])
    client.app.state.runtime.reindex()
    assert error(client.get("/api/v1/raw/" + legacy + "/text")) == (422, "E_TEXT_INVALID")
    pdf = upload(client, "pending.pdf", b"%PDF-1.7\npending")
    response = client.get("/api/v1/raw/" + pdf + "/text", params={"pages": "1"})
    assert error(response) == (409, "E_EXTRACT_PENDING")
    fake_parser(monkeypatch, tmp_path / "parser", "pypdf", "raise ImportError('no pypdf')\n")
    assert error(client.get("/api/v1/raw/" + pdf + "/text")) == (400, "E_EXTRACTOR_UNAVAILABLE")


def test_job_reports_missing_parser_and_logs_worker_failure(
    client: TestClient,
    config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reviewer(client, config)
    fake_parser(monkeypatch, tmp_path / "parser", "pypdf", "raise ImportError('no pypdf')\n")
    with caplog.at_level("WARNING", logger="wikisvc"):
        result = job(client, "noparser.pdf", b"%PDF-1.7\nmissing")
    assert (result["status"], result["error"]) == ("failed", "E_EXTRACTOR_UNAVAILABLE")
    worker_logs = [r.getMessage() for r in caplog.records if "worker failed" in r.getMessage()]
    assert len(worker_logs) == 1
    assert result["path"] in worker_logs[0]
    assert "rc=2" in worker_logs[0]
    assert "ImportError" in worker_logs[0]
    # The sync text path logs the same way and keeps its own error mapping.
    caplog.clear()
    pdf = upload(client, "sync.pdf", b"%PDF-1.7\nsync")
    with caplog.at_level("WARNING", logger="wikisvc"):
        response = client.get("/api/v1/raw/" + pdf + "/text")
    assert error(response) == (400, "E_EXTRACTOR_UNAVAILABLE")
    assert any("rc=2" in r.getMessage() for r in caplog.records)


def test_job_logs_unexpected_exception_with_traceback(
    client: TestClient,
    config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reviewer(client, config)

    def explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(client.app.state.runtime.extractions, "build_outline", explode)
    with caplog.at_level("WARNING", logger="wikisvc"):
        result = job(client, "boom.md", b"# Title\n\nSome text.\n")
    assert (result["status"], result["error"]) == ("failed", "E_TEXT_INVALID")
    crashes = [r for r in caplog.records if "crashed" in r.getMessage()]
    assert len(crashes) == 1
    assert result["path"] in crashes[0].getMessage()
    assert "RuntimeError" in crashes[0].getMessage()
    assert crashes[0].exc_info is not None
    assert crashes[0].exc_info[0] is RuntimeError


def test_failed_extraction_is_rerun_only_on_explicit_retry(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer(client, config)
    extractions = client.app.state.runtime.extractions
    writer = Principal(name="retrier", role="writer", clearance="restricted")

    def explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise RuntimeError("environment is broken")

    monkeypatch.setattr(extractions, "build_outline", explode)
    failed = job(client, "retry.md", b"# Title\n\nSome text.\n")
    path = failed["path"]
    assert (failed["status"], failed["error"]) == ("failed", "E_TEXT_INVALID")
    monkeypatch.delattr(extractions, "build_outline")  # the cause is gone
    # Without retry the failed record is returned as it was and nothing is scheduled.
    stale = extractions.start(writer, path)
    assert (stale["status"], stale["error"]) == ("failed", "E_TEXT_INVALID")
    assert extractions.status(path)["status"] == "failed"
    # With retry the record is reset and the extraction runs again, now successfully.
    restarted = extractions.start(writer, path, retry=True)
    assert (restarted["status"], restarted["error"]) == ("pending", None)
    done = finished(client, path)
    assert (done["status"], done["error"]) == ("done", None)
    # A done record is returned as is, even with retry.
    again = extractions.start(writer, path, retry=True)
    assert (again["status"], again["pages"]) == ("done", done["pages"])


def test_extract_endpoint_honours_the_retry_parameter(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer(client, config)
    extractions = client.app.state.runtime.extractions

    def explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise RuntimeError("environment is broken")

    monkeypatch.setattr(extractions, "build_outline", explode)
    path = job(client, "param.md", b"# Title\n\nSome text.\n")["path"]
    monkeypatch.delattr(extractions, "build_outline")
    plain = client.post("/api/v1/raw/" + path + "/extract")
    assert (plain.status_code, plain.json()["status"]) == (202, "failed")
    retried = client.post("/api/v1/raw/" + path + "/extract", params={"retry": "true"})
    assert (retried.status_code, retried.json()["status"]) == (202, "pending")
    assert finished(client, path)["status"] == "done"


def test_retry_during_failure_persistence_is_not_lost(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A retry that lands while the failure is being written must still run: the row turning
    # `failed` and the path leaving `active` happen under one lock.
    reviewer(client, config)
    extractions = client.app.state.runtime.extractions
    writer = Principal(name="racer", role="writer", clearance="restricted")
    persisting = threading.Event()
    release = threading.Event()
    armed = threading.Event()
    real_now = extraction_module.now

    def explode(*args: object, **kwargs: object) -> dict[str, Any]:
        armed.set()
        raise RuntimeError("environment is broken")

    def slow_now() -> str:
        if armed.is_set() and not persisting.is_set():
            persisting.set()
            assert release.wait(30)
        return real_now()

    monkeypatch.setattr(extractions, "build_outline", explode)
    monkeypatch.setattr(extraction_module, "now", slow_now)
    path = library(client, "race.md", b"# Title\n\nSome text.\n")["path"]
    assert client.post("/api/v1/raw/" + path + "/extract").status_code == 202
    assert persisting.wait(30)
    monkeypatch.delattr(extractions, "build_outline")  # the cause is gone
    retry = threading.Thread(target=lambda: extractions.start(writer, path, retry=True))
    retry.start()
    time.sleep(0.2)  # let the retry reach the lock the failing worker holds
    release.set()
    retry.join(30)
    assert not retry.is_alive()
    assert finished(client, path)["status"] == "done"
