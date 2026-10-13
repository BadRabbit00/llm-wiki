import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wikisvc.domain.errors import WikiError
from wikisvc.storage.db_version import INDEX_SCHEMA, refuse_newer, stamp, version


class IndexDB:
    def __init__(self, directory: Path, discard_newer: bool = False) -> None:
        """discard_newer drops an index a newer version wrote; it is derived, so a
        full reindex rebuilds it. Otherwise such an index is refused like any database."""
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "wiki.db"
        with self.connect() as db:
            if not any("ENABLE_FTS5" in row[0] for row in db.execute("PRAGMA compile_options")):
                raise WikiError(
                    "E_FTS5_MISSING",
                    "SQLite собран без FTS5. Установите Python с поддержкой SQLite FTS5.",
                    status=500,
                )
            newer = version(db) > INDEX_SCHEMA
        if newer and discard_newer:
            for name in ("wiki.db", "wiki.db-wal", "wiki.db-shm"):
                (directory / name).unlink(missing_ok=True)
        with self.connect() as db:
            refuse_newer(
                db,
                "индекса",
                INDEX_SCHEMA,
                "Индекс производный: `wikisvc reindex --full` соберёт его заново этой версией.",
            )
            db.executescript("""
            CREATE TABLE IF NOT EXISTS pages (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
                status TEXT NOT NULL, sensitivity TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
                tags TEXT NOT NULL, aliases TEXT NOT NULL, extra TEXT NOT NULL,
                body TEXT NOT NULL, content_hash TEXT NOT NULL, created TEXT, updated TEXT,
                verified_at TEXT, verified_by TEXT, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS edges (
                src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY (src,dst,rel,kind));
            CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
            CREATE INDEX IF NOT EXISTS edges_dst_rel ON edges(dst,rel);
            CREATE INDEX IF NOT EXISTS edges_src_rel ON edges(src,rel);
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                ord INTEGER NOT NULL, heading TEXT NOT NULL, text TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                title, heading, text, tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS raw_files (
                path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                mime TEXT NOT NULL, added_at TEXT NOT NULL);
            DROP TABLE IF EXISTS embeddings;
            CREATE TABLE IF NOT EXISTS delivery_stats (
                ts TEXT NOT NULL, endpoint TEXT NOT NULL, query_hash TEXT,
                chars_available INTEGER NOT NULL, chars_delivered INTEGER NOT NULL,
                pages_truncated INTEGER NOT NULL, clearance TEXT NOT NULL DEFAULT 'restricted');
            CREATE TABLE IF NOT EXISTS issues (path TEXT NOT NULL, page TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            if "storage" not in {r[1] for r in db.execute("PRAGMA table_info(raw_files)")}:
                db.execute("ALTER TABLE raw_files ADD COLUMN storage TEXT NOT NULL DEFAULT 'git'")
            stamp(db, INDEX_SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()
