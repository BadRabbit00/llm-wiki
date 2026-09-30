from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
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
    transliteration = dict(
        zip(
            "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
            [
                "a",
                "b",
                "v",
                "g",
                "d",
                "e",
                "yo",
                "zh",
                "z",
                "i",
                "y",
                "k",
                "l",
                "m",
                "n",
                "o",
                "p",
                "r",
                "s",
                "t",
                "u",
                "f",
                "kh",
                "ts",
                "ch",
                "sh",
                "shch",
                "",
                "y",
                "",
                "e",
                "yu",
                "ya",
            ],
            strict=True,
        )
    )
    name = "".join(transliteration.get(char.lower(), char) for char in name)
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
                stack: list[Iterator[Any]] = [iter([json.loads(text)])]
                while stack:
                    try:
                        value = next(stack[-1])
                    except StopIteration:
                        stack.pop()
                        continue
                    if isinstance(value, (dict, list)):
                        if len(stack) > 128:
                            raise ValueError("JSON nesting exceeds 128 levels")
                        stack.append(iter(value.values() if isinstance(value, dict) else value))
            elif extension in {"yaml", "yml"}:
                load_yaml(text)
        except (UnicodeError, ValueError, WikiError, RecursionError):
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
            repo = GitRepo(self.config.wiki_root)
            repo.ensure_main()
            self.rt.sync_index()
            with self.rt.index.connect() as db:
                duplicate = db.execute(
                    "SELECT * FROM raw_files WHERE sha256=? ORDER BY path LIMIT 1", (digest,)
                ).fetchone()
            if duplicate:
                self.rt.state.audit(actor.name, "raw.duplicate", duplicate["path"])
                return {**dict(duplicate), "duplicate": True, "trust": "untrusted_external"}
            path = f"raw/{category}/{datetime.now(UTC).year}/{digest[:8]}-{name}"
            fs = SafeFS(self.config.wiki_root)
            if fs.path(path).exists():
                raise WikiError(
                    "E_RAW_EXISTS", "Такой путь уже существует; сырьё неизменяемо.", status=409
                )
            with repo.transaction([path]):
                fs.write(path, data)
                repo.commit(f"Add raw source {path}", actor.name, [path])
            self.rt.indexer.reindex([path])
            self.rt.state.audit(actor.name, "raw.upload", path)
            with self.rt.state.connect() as db:
                db.execute(
                    "INSERT INTO raw_notes VALUES (?,?,?,?,?)",
                    (
                        digest,
                        note,
                        actor.name,
                        path,
                        filename.replace("\\", "/").rsplit("/", 1)[-1][:255],
                    ),
                )
            with self.rt.index.connect() as db:
                row = db.execute("SELECT * FROM raw_files WHERE path=?", (path,)).fetchone()
        return {
            **dict(row),
            "original_name": filename.replace("\\", "/").rsplit("/", 1)[-1][:255],
            "duplicate": False,
            "trust": "untrusted_external",
        }

    def records(self, actor: Principal, pending: bool = False) -> list[dict[str, Any]]:
        self.require_clearance(actor)
        with self.rt.index.connect() as db:
            rows = db.execute("""SELECT r.*, EXISTS (
                SELECT 1 FROM pages p WHERE p.type='source' AND json_extract(p.extra,'$.raw_sha256')=r.sha256
                ) AS processed FROM raw_files r ORDER BY path""").fetchall()
        names = {
            row["path"]: row["original_name"]
            for row in self.rt.state.rows("SELECT path,original_name FROM raw_notes")
        }
        return [
            {
                **dict(row),
                "original_name": names.get(row["path"]),
                "processed": bool(row["processed"]),
                "trust": "untrusted_external",
            }
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
            elif extension in {".pdf", ".docx"}:
                text = self._extract(file)
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

    def _extract(self, file: Path) -> str:
        try:
            with tempfile.TemporaryDirectory(prefix="wikisvc-extract-") as directory:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "wikisvc.services.extract_worker",
                        str(file),
                        str(self.config.extract_memory_mb),
                        str(self.config.extract_max_chars),
                        str(self.config.extract_timeout_seconds),
                    ],
                    cwd=directory,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=self.config.extract_timeout_seconds,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise WikiError("E_TEXT_LIMIT", "Превышено время извлечения текста.") from exc
        if result.returncode == 2:
            raise WikiError(
                "E_EXTRACTOR_UNAVAILABLE",
                "Установите необязательные pypdf / python-docx.",
                status=400,
            )
        if result.returncode != 0:
            raise WikiError(
                "E_TEXT_INVALID", "Не удалось извлечь текст в пределах ограничений ресурсов."
            )
        return result.stdout.decode("utf-8")
