import hashlib
import json
import mimetypes
import re
import sqlite3
from pathlib import Path

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import edges, parse, sections
from wikisvc.domain.models import Edge, Frontmatter, LintIssue, Page
from wikisvc.domain.registry import Registry
from wikisvc.domain.validate import issue, parse_page, validate_set
from wikisvc.index.db import IndexDB
from wikisvc.index.normalize import normalize
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def row_page(row: sqlite3.Row) -> Page:
    return Page(
        frontmatter=Frontmatter.model_validate_json(row["metadata"]),
        body_md=row["body"],
        path=row["path"],
        version=row["content_hash"],
    )


def read_pages(root: Path) -> tuple[list[Page], list[LintIssue]]:
    fs = SafeFS(root)
    pages, issues = [], []
    for path in fs.files("wiki/**/*.md"):
        if path in ("wiki/index.md", "wiki/log.md"):
            continue
        try:
            pages.append(parse_page(fs.read(path), path))
        except (WikiError, OSError, UnicodeError) as exc:
            issues.append(
                issue(
                    exc.code if isinstance(exc, WikiError) else "E_FRONTMATTER_INVALID",
                    path,
                    str(exc),
                )
            )
            try:
                metadata, _ = parse(fs.read(path))
                summary = metadata.get("summary")
                if isinstance(summary, str) and len(summary) < 20:
                    issues.append(
                        issue("W_SUMMARY_WEAK", path, "Нужен summary длиной 20–200 символов.")
                    )
            except (WikiError, OSError, UnicodeError):
                pass
    return pages, issues


def chunks(body: str, limit: int = 1500) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for section in sections(body):
        if not section.text.strip():
            continue
        paragraphs = re.split(r"\n\s*\n", section.text.strip())
        current: list[str] = []
        for paragraph in paragraphs:
            # An indivisible long paragraph is split to guarantee a bounded chunk.
            for part in [paragraph[i : i + limit] for i in range(0, len(paragraph), limit)]:
                if current and len("\n\n".join([*current, part])) > limit:
                    result.append((section.heading, "\n\n".join(current)))
                    overlap = current[-1]
                    current = [overlap] if len(overlap) + len(part) + 2 <= limit else []
                current.append(part)
        if current:
            result.append((section.heading, "\n\n".join(current)))
    return result or [("", "")]


class Indexer:
    def __init__(self, root: Path, db: IndexDB, registry: Registry) -> None:
        self.root, self.db, self.registry = root, db, registry

    def reindex(self, paths: list[str] | None = None) -> list[LintIssue]:
        fs = SafeFS(self.root)
        all_pages, failures = read_pages(self.root)
        issues = failures + validate_set(all_pages, self.registry)
        selected = set(paths) if paths is not None else None
        if len({page.id for page in all_pages}) != len(all_pages):
            selected = None  # keep duplicate resolution identical to a full rebuild
        with self.db.connect() as db:
            if selected is None:
                for table in ("chunks_fts", "embeddings", "chunks", "pages"):
                    db.execute(f"DELETE FROM {table}")
            else:
                for path in selected:
                    db.execute(
                        "DELETE FROM chunks_fts WHERE rowid IN (SELECT chunk_id FROM chunks JOIN pages ON pages.id=chunks.page_id WHERE pages.path=?)",
                        (path,),
                    )
                    db.execute(
                        "DELETE FROM embeddings WHERE chunk_id IN (SELECT chunk_id FROM chunks JOIN pages ON pages.id=chunks.page_id WHERE pages.path=?)",
                        (path,),
                    )
                    db.execute("DELETE FROM pages WHERE path=?", (path,))
            for page in all_pages:
                if selected is not None and page.path not in selected:
                    continue
                fm = page.frontmatter
                try:
                    db.execute(
                        "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            page.id,
                            fm.type,
                            fm.title,
                            fm.summary,
                            fm.status,
                            fm.sensitivity,
                            page.path,
                            json.dumps(fm.tags),
                            json.dumps(fm.aliases),
                            json.dumps(fm.model_extra or {}, default=str),
                            page.body_md,
                            page.version,
                            fm.created,
                            fm.updated,
                            fm.verified_at,
                            fm.verified_by,
                            fm.model_dump_json(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    continue  # duplicate IDs remain visible in issues
                for ordinal, (heading, text) in enumerate(chunks(page.body_md)):
                    cursor = db.execute(
                        "INSERT INTO chunks(page_id,ord,heading,text) VALUES (?,?,?,?)",
                        (page.id, ordinal, heading, text),
                    )
                    db.execute(
                        "INSERT INTO chunks_fts(rowid,title,heading,text) VALUES (?,?,?,?)",
                        (
                            cursor.lastrowid,
                            normalize(" ".join([fm.title, *fm.aliases])),
                            normalize(heading),
                            normalize(text),
                        ),
                    )
            db.execute("DELETE FROM edges")
            for row in db.execute("SELECT * FROM pages").fetchall():
                for edge in edges(row_page(row)):
                    self._edge(db, edge)
                    relation = self.registry.relations.get(edge.rel)
                    if relation:
                        self._edge(
                            db,
                            Edge(src=edge.dst, dst=edge.src, rel=relation.inverse, kind="inverse"),
                        )
            db.execute("DELETE FROM issues")
            for problem in issues:
                db.execute(
                    "INSERT INTO issues VALUES (?,?,?)",
                    (problem.page or "", problem.page, problem.model_dump_json()),
                )
            db.execute("DELETE FROM raw_files")
            for path in fs.files("raw/**/*"):
                if Path(path).name == ".gitkeep":
                    continue
                try:
                    raw = fs.path(path)
                    data = raw.read_bytes()
                    from datetime import UTC, datetime

                    db.execute(
                        "INSERT INTO raw_files VALUES (?,?,?,?,?)",
                        (
                            path,
                            hashlib.sha256(data).hexdigest(),
                            len(data),
                            mimetypes.guess_type(path)[0] or "application/octet-stream",
                            datetime.fromtimestamp(raw.stat().st_mtime, UTC).isoformat(),
                        ),
                    )
                except (WikiError, OSError):
                    continue
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES ('index_commit',?)",
                (GitRepo(self.root).head(),),
            )
        return issues

    @staticmethod
    def _edge(db: sqlite3.Connection, edge: Edge) -> None:
        db.execute(
            "INSERT OR IGNORE INTO edges VALUES (?,?,?,?)",
            (edge.src, edge.dst, edge.rel, edge.kind),
        )
