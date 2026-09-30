import io
import os
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
    pdf = io.BytesIO()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    pdf_path = upload(client, "sample.pdf", pdf.getvalue())
    response = client.get("/api/v1/raw/" + pdf_path + "/text")
    assert response.status_code == 200, response.text
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
    assert response.json()["error"]["code"] == (
        "E_TEXT_LIMIT" if parser == "timeout" else "E_TEXT_INVALID"
    )
    assert client.get("/api/v1/health").status_code == 200
