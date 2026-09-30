import hashlib
import json
import mimetypes
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import edges, parse, sections
from wikisvc.domain.models import Edge, Frontmatter, LintIssue, Page
from wikisvc.domain.registry import Registry
from wikisvc.domain.validate import ValidationCache, issue, parse_page, validate_set
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


def read_pages(root: Path, paths: list[str] | None = None) -> tuple[list[Page], list[LintIssue]]:
    fs = SafeFS(root)
    pages, issues = [], []
    for path in fs.files("wiki/**/*.md") if paths is None else sorted(set(paths)):
        if (
            not path.startswith("wiki/")
            or not path.endswith(".md")
            or path in ("wiki/index.md", "wiki/log.md")
        ):
            continue
        try:
            if not fs.path(path).is_file():
                continue
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
        self.validation = ValidationCache()

    def pages(self) -> list[Page]:
        with self.db.connect() as db:
            return [row_page(row) for row in db.execute("SELECT * FROM pages ORDER BY path")]

    def failures(self) -> list[LintIssue]:
        with self.db.connect() as db:
            return [
                LintIssue.model_validate_json(row[0])
                for row in db.execute("SELECT data FROM issues WHERE page LIKE 'wiki/%'")
            ]

    def reindex(self, paths: list[str] | None = None) -> list[LintIssue]:
        fs = SafeFS(self.root)
        with self.db.connect() as db:
            if db.execute(
                "SELECT 1 FROM issues WHERE json_extract(data,'$.code')='E_ID_DUPLICATE' LIMIT 1"
            ).fetchone():
                paths = None  # a duplicate omitted from the unique index may become canonical
        selected = set(paths) if paths is not None else None
        changed, failures = read_pages(self.root, paths)
        all_pages = changed
        if selected is not None:
            all_pages = [p for p in self.pages() if p.path not in selected] + changed
            failures += [i for i in self.failures() if i.page not in selected]
        if len({page.id for page in all_pages}) != len(all_pages):
            selected = None  # keep duplicate resolution identical to a full rebuild
            all_pages, failures = read_pages(self.root)
        issues = failures + validate_set(all_pages, self.registry, self.validation)
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
            if selected is None:
                db.execute("DELETE FROM edges")
                edge_pages = all_pages
            else:
                old_ids = {p.id for p in self.pages() if p.path in selected}
                changed_ids = old_ids | {p.id for p in changed}
                for page_id in changed_ids:
                    db.execute(
                        "DELETE FROM edges WHERE (src=? AND kind!='inverse') OR (dst=? AND kind='inverse')",
                        (page_id, page_id),
                    )
                edge_pages = changed
            for page in edge_pages:
                row = db.execute("SELECT * FROM pages WHERE id=?", (page.id,)).fetchone()
                if row is None:
                    continue
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
            raw_paths = (
                set(fs.files("raw/**/*"))
                if paths is None
                else {p for p in paths if p.startswith("raw/")}
            )
            if paths is None:
                for row in db.execute("SELECT path FROM raw_files").fetchall():
                    if row[0] not in raw_paths:
                        db.execute("DELETE FROM raw_files WHERE path=?", (row[0],))
            for path in raw_paths:
                if Path(path).name == ".gitkeep":
                    continue
                try:
                    raw = fs.path(path)
                    if not raw.is_file():
                        db.execute("DELETE FROM raw_files WHERE path=?", (path,))
                        continue
                    stat = raw.stat()
                    modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
                    cached = db.execute(
                        "SELECT size,added_at FROM raw_files WHERE path=?", (path,)
                    ).fetchone()
                    if cached and (cached[0], cached[1]) == (stat.st_size, modified):
                        continue
                    data = raw.read_bytes()
                    db.execute(
                        "INSERT OR REPLACE INTO raw_files VALUES (?,?,?,?,?)",
                        (
                            path,
                            hashlib.sha256(data).hexdigest(),
                            len(data),
                            mimetypes.guess_type(path)[0] or "application/octet-stream",
                            modified,
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
