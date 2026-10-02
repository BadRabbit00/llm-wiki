from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import citations
from wikisvc.domain.models import LintIssue, Page, Principal
from wikisvc.domain.validate import issue
from wikisvc.services.auth import require_role
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


def normalize_quote(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    replacements: dict[str, str | int | None] = {
        "«": '"',
        "»": '"',
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "-",
        "–": "-",
        "‑": "-",
    }
    text = text.translate(str.maketrans(replacements))
    return " ".join(text.split())


def clean_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repeats: Counter[str] = Counter()
    for page in pages:
        lines = page["text"].splitlines()
        if len(lines) < 4:
            continue
        repeats.update(
            {
                line.strip()
                for line in [*lines[:2], *lines[-2:]]
                if line.strip() and not re.match(r"(?i)(chapter|глава)\b", line.strip())
            }
        )
    headers = {
        line
        for line, count in repeats.items()
        if count >= max(2, math.ceil(len(pages) * 0.3)) and len(line) < 160
    }
    result = []
    for page in pages:
        lines = []
        code = False
        for line in page["text"].replace("\u00ad", "").splitlines():
            if line.strip().startswith("```"):
                code = not code
                lines.append(line)
                continue
            if not code and (line.strip() in headers or re.fullmatch(r"\s*\d+\s*", line)):
                continue
            lines.append(line)
        text = "\n".join(lines)
        text = re.sub(r"(?<=\w)-\n\s*(?=\w)", "", text)
        paragraphs = []
        code = False
        current: list[str] = []
        for line in text.splitlines():
            if line.strip().startswith("```"):
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                code = not code
                paragraphs.append(line)
            elif code or line.startswith(("    ", "\t")):
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append(line)
            elif not line.strip():
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append("")
            else:
                current.append(line.strip())
        if current:
            paragraphs.append(" ".join(current))
        result.append({**page, "text": "\n".join(paragraphs).strip()})
    return result


class Extractions:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wiki-extract")
        self.lock = threading.Lock()
        self.active: set[str] = set()

    def record(self, actor: Principal, path: str) -> dict[str, Any]:
        file = self.rt.raw.file(actor, path)
        path = path if path.startswith(("raw/", "library/")) else "raw/" + path
        with self.rt.index.connect() as db:
            row = db.execute("SELECT * FROM raw_files WHERE path=?", (path,)).fetchone()
        assert row is not None
        if file.suffix.lower() not in (".pdf", ".epub", ".docx", ".md", ".txt"):
            raise WikiError(
                "E_TEXT_UNAVAILABLE", "Формат не поддерживает постраничное извлечение.", status=400
            )
        return dict(row)

    def status(self, path: str) -> dict[str, Any] | None:
        rows = self.rt.state.rows("SELECT * FROM extractions WHERE path=?", (path,))
        return rows[0] if rows else None

    def start(self, actor: Principal, path: str) -> dict[str, Any]:
        require_role(actor, "writer")
        record = self.record(actor, path)
        path = record["path"]
        with self.lock:
            previous = self.status(path)
            if (
                previous
                and previous["status"] in ("done", "failed")
                and previous["sha256"] == record["sha256"]
            ):
                return previous
            with self.rt.state.connect() as db:
                db.execute(
                    "INSERT INTO extractions(path,sha256,status) VALUES (?,?,'pending') ON CONFLICT(path) DO UPDATE SET status=CASE WHEN status='running' THEN status ELSE 'pending' END,error=NULL",
                    (path, record["sha256"]),
                )
            self.schedule(path)
        return self.status(path) or {}

    def schedule(self, path: str) -> None:
        if path not in self.active:
            self.active.add(path)
            self.pool.submit(self.run, path)

    def recover(self) -> None:
        with self.lock:
            for row in self.rt.state.rows(
                "SELECT path FROM extractions WHERE status IN ('pending','running')"
            ):
                self.schedule(row["path"])

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)

    def directory(self, sha: str) -> Path:
        if not re.fullmatch("[a-f0-9]{64}", sha):
            raise WikiError("E_SOURCE_HASH", "Некорректный хеш источника.")
        return self.rt.settings.state_dir / "extract" / sha

    def run(self, path: str) -> None:
        actor = Principal(name="extractor", role="writer", clearance="restricted")
        try:
            record = self.record(actor, path)
            file = self.rt.raw.file(actor, path)
            cache = SafeFS(self.directory(record["sha256"]))
            with self.rt.state.connect() as db:
                db.execute(
                    "UPDATE extractions SET status='running',started_at=?,error=NULL WHERE path=?",
                    (now(), path),
                )
            deadline = time.monotonic() + self.rt.settings.extract_job_timeout
            pages: list[dict[str, Any]] = []
            bookmarks = []
            total = 1
            start = 1
            while start <= total:
                batch_file = f"batch-{start:06}.json"
                if cache.path(batch_file).exists():
                    part = json.loads(cache.read(batch_file))
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WikiError("E_EXTRACT_TIMEOUT", "Превышено время задачи извлечения.")
                    with tempfile.TemporaryDirectory(prefix="wiki-extract-") as temporary:
                        completed = subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "wikisvc.services.extract_worker",
                                str(file),
                                str(self.rt.settings.extract_memory_mb),
                                str(self.rt.settings.extract_max_chars),
                                str(self.rt.settings.extract_timeout_seconds),
                                "--pages",
                                str(start),
                                "15",
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL,
                            cwd=temporary,
                            timeout=min(remaining, self.rt.settings.extract_timeout_seconds),
                            check=False,
                        )
                    if completed.returncode != 0:
                        raise WikiError(
                            "E_TEXT_INVALID", "Парсер отклонил документ или превысил лимиты."
                        )
                    part = json.loads(completed.stdout)
                    cache.write(batch_file, json.dumps(part, ensure_ascii=False))
                total = part["total"]
                if total > 50000:
                    raise WikiError("E_TEXT_LIMIT", "Слишком много страниц.")
                pages.extend(part["pages"])
                bookmarks = part["outline"]
                if sum(len(p["text"]) for p in pages) > self.rt.settings.extract_job_max_chars:
                    raise WikiError("E_TEXT_LIMIT", "Превышен объём извлечённого текста.")
                if not part["pages"]:
                    break
                start = part["pages"][-1]["n"] + 1
                with self.rt.state.connect() as db:
                    db.execute("UPDATE extractions SET pages=? WHERE path=?", (len(pages), path))
            pages = clean_pages(pages)
            chars = sum(len(p["text"]) for p in pages)
            if not chars:
                raise WikiError(
                    "E_NO_TEXT_LAYER", "В документе нет извлекаемого текста; OCR не поддерживается."
                )
            outline = self.build_outline(pages, bookmarks)
            cache.write(
                "pages.jsonl", "\n".join(json.dumps(p, ensure_ascii=False) for p in pages) + "\n"
            )
            cache.write("outline.json", json.dumps(outline, ensure_ascii=False))
            with self.rt.state.connect() as db:
                db.execute(
                    "UPDATE extractions SET status='done',pages=?,chars=?,finished_at=? WHERE path=?",
                    (len(pages), chars, now(), path),
                )
        except Exception as exc:  # noqa: BLE001 -- persist any background job failure
            code = (
                exc.code
                if isinstance(exc, WikiError)
                else "E_EXTRACT_TIMEOUT"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "E_TEXT_INVALID"
            )
            with self.rt.state.connect() as db:
                db.execute(
                    "UPDATE extractions SET status='failed',error=?,finished_at=? WHERE path=?",
                    (code, now(), path),
                )
        finally:
            with self.lock:
                self.active.discard(path)

    def build_outline(
        self, pages: list[dict[str, Any]], bookmarks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        origin = "bookmarks"
        starts = {
            p["page_from"]: p["title"] for p in bookmarks if 1 <= p["page_from"] <= len(pages)
        }
        if not starts:
            origin = "headings"
            for page in pages:
                match = re.search(
                    r"(?im)^\s*(?:#+\s*)?((?:глава|chapter)\s+\d+[^\n]{0,150})", page["text"]
                )
                if match:
                    starts[page["n"]] = match[1]
        if not starts:
            origin = "fallback"
            starts = {
                n: f"Страницы {n}–{min(n + self.rt.settings.outline_fallback_pages - 1, len(pages))}"
                for n in range(1, len(pages) + 1, self.rt.settings.outline_fallback_pages)
            }
        keys = sorted(starts)
        return {
            "origin": origin,
            "chapters": [
                {
                    "n": i + 1,
                    "title": starts[start],
                    "page_from": start,
                    "page_to": keys[i + 1] - 1 if i + 1 < len(keys) else len(pages),
                }
                for i, start in enumerate(keys)
            ],
        }

    def ready(self, actor: Principal, path: str) -> tuple[dict[str, Any], SafeFS]:
        record = self.record(actor, path)
        status = self.status(record["path"])
        if not status or status["status"] != "done":
            raise WikiError(
                "E_EXTRACT_PENDING",
                "Извлечение ещё не готово.",
                details=[status or {"status": "pending"}],
                status=409,
            )
        return record, SafeFS(self.directory(record["sha256"]))

    def outline(self, actor: Principal, path: str) -> dict[str, Any]:
        record, cache = self.ready(actor, path)
        override = self.rt.state.rows(
            "SELECT outline FROM outline_overrides WHERE sha256=?", (record["sha256"],)
        )
        result: dict[str, Any] = (
            json.loads(override[0]["outline"])
            if override
            else json.loads(cache.read("outline.json"))
        )
        return {
            **result,
            "path": record["path"],
            "sha256": record["sha256"],
            "trust": "untrusted_external",
        }

    def put_outline(
        self, actor: Principal, path: str, chapters: list[dict[str, Any]]
    ) -> dict[str, Any]:
        require_role(actor, "writer")
        record, _ = self.ready(actor, path)
        status = self.status(record["path"])
        assert status is not None
        end = 0
        for n, chapter in enumerate(chapters, 1):
            if (
                chapter["n"] != n
                or not end < chapter["page_from"] <= chapter["page_to"] <= status["pages"]
            ):
                raise WikiError(
                    "E_LOCATOR_OUT_OF_RANGE",
                    "Оглавление должно последовательно покрывать существующие страницы без пересечений.",
                )
            end = chapter["page_to"]
        with self.rt.state.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO outline_overrides VALUES (?,?,?,?)",
                (
                    record["sha256"],
                    json.dumps({"origin": "manual", "chapters": chapters}, ensure_ascii=False),
                    actor.name,
                    now(),
                ),
            )
        return self.outline(actor, path)

    def text(
        self,
        actor: Principal,
        path: str,
        pages: str | None = None,
        chapter: int | None = None,
        max_chars: int = 30000,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not 1 <= max_chars <= 60000 or offset < 0 or (pages and chapter is not None):
            raise WikiError(
                "E_REQUEST_INVALID", "Выберите pages или chapter; max_chars: 1–60000.", status=400
            )
        record, cache = self.ready(actor, path)
        rows = [json.loads(line) for line in cache.read("pages.jsonl").splitlines()]
        start, end = 1, len(rows)
        if chapter is not None:
            matched = [c for c in self.outline(actor, path)["chapters"] if c["n"] == chapter]
            if not matched:
                raise WikiError("E_LOCATOR_OUT_OF_RANGE", "Глава отсутствует.")
            start, end = matched[0]["page_from"], matched[0]["page_to"]
        elif pages:
            if not re.fullmatch(r"\d+(?:-\d+)?", pages):
                raise WikiError("E_REQUEST_INVALID", "pages: N или N-M.", status=400)
            numbers = pages.split("-")
            start = int(numbers[0])
            end = int(numbers[-1])
        if not 1 <= start <= end <= len(rows):
            raise WikiError("E_LOCATOR_OUT_OF_RANGE", "Диапазон страниц отсутствует.")
        text = "\n\n".join(row["text"] for row in rows[start - 1 : end])
        if not pages and chapter is None and len(text) > max_chars:
            raise WikiError(
                "E_TEXT_TOO_LARGE", "Используйте pages или chapter и max_chars.", status=413
            )
        remaining = text[offset:]
        truncated = len(remaining) > max_chars
        return {
            "path": record["path"],
            "sha256": record["sha256"],
            "text": remaining[:max_chars],
            "pages": f"{start}-{end}",
            "next_pages": f"{start}-{end}" if truncated else None,
            "next_offset": offset + max_chars if truncated else None,
            "trust": "untrusted_external",
        }

    def citation_issues(self, pages: list[Page], ids: set[str] | None = None) -> list[LintIssue]:
        by_id = {p.id: p for p in pages}
        actor = Principal(name="citation-validator", role="reader", clearance="restricted")
        result = []
        for page in pages:
            if ids is not None and page.id not in ids:
                continue
            for citation in citations(page.body_md):
                if citation.start is None or citation.quote is None:
                    continue
                source = by_id.get(citation.source)
                if source is None:
                    continue
                path = (source.frontmatter.model_extra or {}).get("raw_path", "")
                status = self.status(path)
                if not status or status["status"] != "done":
                    result.append(
                        issue("W_QUOTE_UNVERIFIED", page.id, "Для источника нет кэша извлечения.")
                    )
                    continue
                start, end = citation.start, citation.end or citation.start
                if citation.unit == "гл.":
                    chapters = self.outline(actor, path)["chapters"]
                    selected = [c for c in chapters if start <= c["n"] <= end]
                    if len(selected) != end - start + 1:
                        result.append(
                            issue("E_LOCATOR_OUT_OF_RANGE", page.id, "Указанная глава отсутствует.")
                        )
                        continue
                    start, end = selected[0]["page_from"], selected[-1]["page_to"]
                if not 1 <= start <= end <= status["pages"]:
                    result.append(
                        issue("E_LOCATOR_OUT_OF_RANGE", page.id, "Страница цитаты отсутствует.")
                    )
                    continue
                cache = SafeFS(self.directory(status["sha256"]))
                rows = [json.loads(line) for line in cache.read("pages.jsonl").splitlines()]
                text = "\n".join(
                    p["text"]
                    for p in rows[
                        max(0, start - (2 if citation.unit == "стр." else 1)) : min(
                            len(rows), end + (1 if citation.unit == "стр." else 0)
                        )
                    ]
                )
                if normalize_quote(citation.quote) not in normalize_quote(text):
                    result.append(
                        issue(
                            "E_QUOTE_NOT_FOUND",
                            page.id,
                            "Цитата не найдена на указанных страницах.",
                        )
                    )
        return result
