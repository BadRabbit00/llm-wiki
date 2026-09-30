from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.models import Principal
from wikisvc.services.auth import require_role
from wikisvc.services.pages import paginate
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


def safe_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    while ".." in name:
        name = name.replace("..", "-")
    name = name.lstrip(".-")
    suffix = Path(name).suffix.lower()
    return (Path(name).stem[:100] or "upload") + suffix


def validate_signature(data: bytes, extension: str, max_size: int) -> None:
    valid = False
    if extension in {"txt", "md", "csv", "json", "yaml", "yml"}:
        try:
            text = data.decode("utf-8-sig")
            valid = not any(ord(c) < 32 and c not in "\t\r\n" for c in text)
            if extension == "json":
                json.loads(text)
            elif extension in {"yaml", "yml"}:
                load_yaml(text)
        except (UnicodeError, ValueError, WikiError):
            valid = False
    elif extension == "pdf":
        valid = data.startswith(b"%PDF-")
    elif extension == "png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR"
    elif extension in {"jpg", "jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
    elif extension in {"docx", "xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                expected = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
                valid = {"[Content_Types].xml", expected} <= set(archive.namelist())
                if sum(item.file_size for item in archive.infolist()) > max_size * 10:
                    valid = False
        except (zipfile.BadZipFile, OSError):
            valid = False
    if not valid:
        raise WikiError("E_RAW_SIGNATURE", "Содержимое не соответствует расширению файла.")


class Raw:
    def __init__(self, runtime: Runtime) -> None:
        self.rt, self.config = runtime, runtime.settings

    @staticmethod
    def require_clearance(actor: Principal) -> None:
        if actor.clearance != "restricted":
            raise not_found()

    def upload(
        self, actor: Principal, filename: str, file: BinaryIO, category: str, note: str = ""
    ) -> dict[str, Any]:
        require_role(actor, "writer")
        self.require_clearance(actor)
        if category not in {
            "docs",
            "transcripts",
            "tickets",
            "api-specs",
            "code-samples",
            "assets",
        }:
            raise WikiError("E_RAW_CATEGORY", "Неизвестная категория сырья.", status=400)
        name = safe_name(filename)
        extension = Path(name).suffix.lower().lstrip(".")
        if extension not in self.config.allowed_raw_ext.split(","):
            raise WikiError("E_RAW_EXTENSION", "Расширение файла не разрешено.")
        maximum = self.config.max_upload_mb * 1024 * 1024
        data = file.read(maximum + 1)
        if len(data) > maximum:
            raise WikiError("E_UPLOAD_TOO_LARGE", "Файл превышает MAX_UPLOAD_MB.", status=413)
        if len(note) > 4000:
            raise WikiError("E_REQUEST_INVALID", "note: до 4000 символов.", status=400)
        validate_signature(data, extension, maximum)
        digest = hashlib.sha256(data).hexdigest()
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            with self.rt.index.connect() as db:
                duplicate = db.execute(
                    "SELECT * FROM raw_files WHERE sha256=? ORDER BY path LIMIT 1", (digest,)
                ).fetchone()
            if duplicate:
                self.rt.state.audit(actor.name, "raw.duplicate", duplicate["path"])
                return {**dict(duplicate), "duplicate": True, "trust": "untrusted_external"}
            repo = GitRepo(self.config.wiki_root)
            repo.ensure_main()
            path = f"raw/{category}/{datetime.now(UTC).year}/{digest[:8]}-{name}"
            fs = SafeFS(self.config.wiki_root)
            if fs.path(path).exists():
                raise WikiError(
                    "E_RAW_EXISTS", "Такой путь уже существует; сырьё неизменяемо.", status=409
                )
            fs.write(path, data)
            repo.commit(f"Add raw source {path}", actor.name)
            self.rt.indexer.reindex([path])
            self.rt.state.audit(actor.name, "raw.upload", path)
            with self.rt.state.connect() as db:
                db.execute(
                    "INSERT INTO raw_notes VALUES (?,?,?,?)", (digest, note, actor.name, path)
                )
            with self.rt.index.connect() as db:
                row = db.execute("SELECT * FROM raw_files WHERE path=?", (path,)).fetchone()
        return {**dict(row), "duplicate": False, "trust": "untrusted_external"}

    def records(self, actor: Principal, pending: bool = False) -> list[dict[str, Any]]:
        self.require_clearance(actor)
        with self.rt.index.connect() as db:
            rows = db.execute("""SELECT r.*, EXISTS (
                SELECT 1 FROM pages p WHERE p.type='source' AND json_extract(p.extra,'$.raw_sha256')=r.sha256
                ) AS processed FROM raw_files r ORDER BY path""").fetchall()
        return [
            {**dict(row), "processed": bool(row["processed"]), "trust": "untrusted_external"}
            for row in rows
            if not pending or not row["processed"]
        ]

    def list_files(
        self, actor: Principal, pending: bool = False, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        return {
            **paginate(self.records(actor, pending), limit, cursor),
            "trust": "untrusted_external",
        }

    def file(self, actor: Principal, path: str) -> Path:
        self.require_clearance(actor)
        path = path if path.startswith("raw/") else "raw/" + path
        result = SafeFS(self.config.wiki_root).path(path)
        with self.rt.index.connect() as db:
            row = db.execute("SELECT path FROM raw_files WHERE path=?", (path,)).fetchone()
        if not row or not result.is_file():
            raise not_found()
        return result

    def text(self, actor: Principal, path: str) -> dict[str, Any]:
        file = self.file(actor, path)
        extension = file.suffix.lower()
        try:
            if extension in {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}:
                text = file.read_text(encoding="utf-8-sig")
            elif extension == ".pdf":
                from pypdf import PdfReader

                text = "\n\n".join(page.extract_text() or "" for page in PdfReader(str(file)).pages)
            elif extension == ".docx":
                from docx import Document

                text = "\n".join(paragraph.text for paragraph in Document(str(file)).paragraphs)
            else:
                raise WikiError(
                    "E_TEXT_UNAVAILABLE",
                    "Извлечение текста для этого формата не поддерживается.",
                    status=400,
                )
        except ImportError as exc:
            raise WikiError(
                "E_EXTRACTOR_UNAVAILABLE",
                "Установите необязательные pypdf / python-docx.",
                status=400,
            ) from exc
        except (UnicodeError, ValueError, OSError, zipfile.BadZipFile) as exc:
            raise WikiError("E_TEXT_INVALID", "Не удалось прочитать текст источника.") from exc
        return {
            "path": str(file.relative_to(self.config.wiki_root)),
            "text": text,
            "trust": "untrusted_external",
        }
