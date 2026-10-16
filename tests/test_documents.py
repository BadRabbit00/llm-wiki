import io
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_proposals import reviewer

from wikisvc.config import Settings
from wikisvc.services.raw import safe_name


def upload(client: TestClient, name: str, data: bytes) -> str:
    response = client.post("/api/v1/raw", files={"file": (name, data)}, data={"category": "docs"})
    assert response.status_code == 200, response.text
    return str(response.json()["path"])


def test_original_filename_and_transliteration(client: TestClient, config: Settings) -> None:
    reviewer(client, config)
    name = "Регламент согласования счетов.txt"
    path = upload(client, name, "Факты компании".encode())
    assert path.endswith("reglament_soglasovaniya_schetov.txt")
    entry = next(item for item in client.get("/api/v1/raw").json()["items"] if item["path"] == path)
    assert entry["original_name"] == name
    assert safe_name("../../Привет.docx") == "privet.docx"


def test_real_pdf_and_docx_in_worker(client: TestClient, config: Settings) -> None:
    pypdf = pytest.importorskip("pypdf")
    docx = pytest.importorskip("docx")
    reviewer(client, config)
    generic = pytest.importorskip("pypdf.generic")
    pdf = io.BytesIO()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=100)
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
        }
    )
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {generic.NameObject("/Font"): generic.DictionaryObject({generic.NameObject("/F1"): font})}
    )
    content = generic.ContentStream(None, None)
    content.set_data(b"BT /F1 12 Tf 10 50 Td (Company handbook) Tj ET")
    page.replace_contents(content)
    writer.write(pdf)
    pdf_path = upload(client, "sample.pdf", pdf.getvalue())
    response = client.get("/api/v1/raw/" + pdf_path + "/text")
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Company handbook"
    document = docx.Document()
    document.add_paragraph("Документ компании")
    output = io.BytesIO()
    document.save(output)
    docx_path = upload(client, "sample.docx", output.getvalue())
    response = client.get("/api/v1/raw/" + docx_path + "/text")
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Документ компании"


@pytest.mark.parametrize("parser", ["timeout", "memory", "output", "invalid"])
def test_parser_limits_are_enforced_in_subprocess(
    client: TestClient,
    config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parser: str,
) -> None:
    reviewer(client, config)
    path = upload(client, "untrusted.pdf", b"%PDF-1.7\n" + parser.encode())
    scripts = {
        "timeout": "import time\ntime.sleep(30)\n",
        "memory": "data = bytearray(1024 * 1024 * 1024)\n",
        "output": "class Page:\n def extract_text(self): return 'a' * 10000\nclass PdfReader:\n def __init__(self, path): self.pages = [Page()]\n",
        "invalid": "raise ValueError('invalid document')\n",
    }
    module = tmp_path / "parser"
    module.mkdir()
    (module / "pypdf.py").write_text(scripts[parser])
    monkeypatch.setenv("PYTHONPATH", str(module) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    config.extract_timeout_seconds = 1
    config.extract_memory_mb = 128
    config.extract_max_chars = 1000
    response = client.get("/api/v1/raw/" + path + "/text")
    assert response.status_code == 422, response.text
    # MemoryError under RLIMIT_AS is a resource limit, not a malformed document: it used to be
    # reported as E_TEXT_INVALID and now must be E_TEXT_LIMIT (issue #15).
    assert response.json()["error"]["code"] == (
        "E_TEXT_LIMIT" if parser in ("timeout", "memory") else "E_TEXT_INVALID"
    )
    assert client.get("/api/v1/health").status_code == 200


def fake_pypdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str) -> None:
    module = tmp_path / "parser"
    module.mkdir()
    (module / "pypdf.py").write_text(source)
    monkeypatch.setenv("PYTHONPATH", str(module) + os.pathsep + os.environ.get("PYTHONPATH", ""))


def host_locale_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nix glibc maps the whole archive named by LOCALE_ARCHIVE* (~230 MB on a Nix-on-Arch host);
    # with RLIMIT_AS = 128 MB the worker then dies of MemoryError before the parser runs.
    archive = next(
        (
            value
            for key in ("LOCALE_ARCHIVE_2_27", "LOCALE_ARCHIVE")
            if (value := os.environ.get(key)) and Path(value).is_file()
        ),
        None,
    )
    if archive is None:
        pytest.skip("No real locale-archive in LOCALE_ARCHIVE_2_27 / LOCALE_ARCHIVE")
    monkeypatch.setenv("LOCALE_ARCHIVE_2_27", archive)
    monkeypatch.setenv("LOCALE_ARCHIVE", archive)


def extraction_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, parser: str
) -> dict[str, str]:
    response = client.post(
        "/api/v1/raw",
        files={"file": (name, b"%PDF-1.7\n" + name.encode())},
        data={"category": "library"},
    )
    assert response.status_code == 200, response.text
    path = response.json()["path"]
    fake_pypdf(monkeypatch, tmp_path, parser)
    assert client.post("/api/v1/raw/" + path + "/extract").status_code == 202
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.app.state.runtime.extractions.status(path)
        if status["status"] in ("done", "failed"):
            return {"status": status["status"], "error": status["error"]}
        time.sleep(0.02)
    raise AssertionError("Extraction did not finish")


def test_host_locale_archive_does_not_eat_worker_memory_limit(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host_locale_archive(monkeypatch)
    reviewer(client, config)
    path = upload(client, "slow.pdf", b"%PDF-1.7\ntimeout")
    fake_pypdf(monkeypatch, tmp_path, "import time\ntime.sleep(30)\n")
    config.extract_timeout_seconds = 1
    config.extract_memory_mb = 128
    response = client.get("/api/v1/raw/" + path + "/text")
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    # The message tells the timeout apart from an E_TEXT_LIMIT caused by memory exhaustion.
    assert (error["code"], error["message"]) == (
        "E_TEXT_LIMIT",
        "Превышено время извлечения текста.",
    )


def test_host_locale_archive_does_not_eat_extraction_job_memory_limit(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host_locale_archive(monkeypatch)
    reviewer(client, config)
    config.extract_timeout_seconds = 1
    config.extract_memory_mb = 128
    # A worker killed by the locale-archive mapping would report E_TEXT_LIMIT, not the timeout.
    assert extraction_job(
        client, monkeypatch, tmp_path, "slow.pdf", "import time\ntime.sleep(30)\n"
    ) == {"status": "failed", "error": "E_EXTRACT_TIMEOUT"}


def test_worker_runs_without_locale_archive_and_with_c_locale(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALE_ARCHIVE_2_27", "inherited-locale-archive")
    monkeypatch.setenv("LOCALE_ARCHIVE", "inherited-locale-archive")
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    monkeypatch.setenv("WIKISVC_TEST_MARKER", "inherited")
    reviewer(client, config)
    path = upload(client, "environ.pdf", b"%PDF-1.7\nenviron")
    fake_pypdf(
        monkeypatch,
        tmp_path,
        "import os\n"
        "KEYS = ('LOCALE_ARCHIVE', 'LC_ALL', 'WIKISVC_TEST_MARKER')\n"
        "class Page:\n"
        " def extract_text(self):\n"
        "  pairs = sorted(os.environ.items())\n"
        "  return '\\n'.join(k + '=' + v for k, v in pairs if k.startswith(KEYS))\n"
        "class PdfReader:\n"
        " def __init__(self, path): self.pages = [Page()]\n",
    )
    response = client.get("/api/v1/raw/" + path + "/text")
    assert response.status_code == 200, response.text
    environ = response.json()["text"].splitlines()
    assert not [line for line in environ if line.startswith("LOCALE_ARCHIVE")]
    assert "LC_ALL=C.UTF-8" in environ
    assert "WIKISVC_TEST_MARKER=inherited" in environ


def test_workers_find_wikisvc_without_pythonpath(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Nix-wrapped wikisvc of the release image puts its packages on sys.path from inside
    # the script, so its environment has no PYTHONPATH. The tests' own PYTHONPATH hid that the
    # worker, a bare `python -m`, then could not import wikisvc: every extraction failed.
    docx = pytest.importorskip("docx")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    reviewer(client, config)
    path = upload(client, "02-tech-stack.md", b"# Stack\n\nPython and Nix.\n")
    assert client.post("/api/v1/raw/" + path + "/extract").status_code == 202
    deadline = time.monotonic() + 30
    while (status := client.app.state.runtime.extractions.status(path))["status"] not in (
        "done",
        "failed",
    ):
        assert time.monotonic() < deadline, "Extraction did not finish"
        time.sleep(0.02)
    assert (status["status"], status["error"]) == ("done", None)
    document = docx.Document()
    document.add_paragraph("Стек компании")
    output = io.BytesIO()
    document.save(output)
    response = client.get(
        "/api/v1/raw/" + upload(client, "stack.docx", output.getvalue()) + "/text"
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Стек компании"


def test_worker_memory_exhaustion_fails_extraction_job_as_limit(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reviewer(client, config)
    config.extract_memory_mb = 128
    assert extraction_job(
        client, monkeypatch, tmp_path, "memory.pdf", "data = bytearray(1024 * 1024 * 1024)\n"
    ) == {"status": "failed", "error": "E_TEXT_LIMIT"}
