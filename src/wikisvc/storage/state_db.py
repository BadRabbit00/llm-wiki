import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class StateDB:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / "state.db"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL, clearance TEXT NOT NULL,
                created_at TEXT NOT NULL, revoked_at TEXT);
            CREATE TABLE IF NOT EXISTS proposals (
                pid TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                author TEXT NOT NULL, status TEXT NOT NULL, base_commit TEXT NOT NULL,
                branch TEXT NOT NULL, review_comment TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, decided_by TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                ts TEXT NOT NULL, token_name TEXT NOT NULL, action TEXT NOT NULL,
                target TEXT, ok INTEGER NOT NULL, detail TEXT);
            CREATE TABLE IF NOT EXISTS proposal_validation (
                pid TEXT PRIMARY KEY, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS proposal_snapshots (
                pid TEXT NOT NULL, path TEXT NOT NULL, before_text TEXT, after_text TEXT,
                PRIMARY KEY(pid,path));
            CREATE TABLE IF NOT EXISTS proposal_clearance (
                pid TEXT PRIMARY KEY, clearance TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS proposal_editors (
                pid TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(pid,name));
            CREATE TABLE IF NOT EXISTS raw_notes (
                sha256 TEXT PRIMARY KEY, note TEXT NOT NULL, author TEXT NOT NULL, path TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rate_limits (
                name TEXT NOT NULL, minute INTEGER NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY(name,minute));
            """)
            if "last_editor" not in {row[1] for row in db.execute("PRAGMA table_info(proposals)")}:
                db.execute("ALTER TABLE proposals ADD COLUMN last_editor TEXT")
            if "original_name" not in {
                row[1] for row in db.execute("PRAGMA table_info(raw_notes)")
            }:
                db.execute("ALTER TABLE raw_notes ADD COLUMN original_name TEXT")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def audit(
        self,
        name: str,
        action: str,
        target: str | None = None,
        ok: bool = True,
        detail: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit VALUES (?,?,?,?,?,?)",
                (now(), name, action, target, int(ok), detail),
            )

    def rows(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, parameters)]
