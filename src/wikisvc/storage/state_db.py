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
            CREATE TABLE IF NOT EXISTS rule_usage (
                rule_id TEXT NOT NULL, day TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                opened INTEGER NOT NULL DEFAULT 0, violations INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(rule_id,day));
            CREATE TABLE IF NOT EXISTS proposal_notes (pid TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, severity TEXT NOT NULL,
                status TEXT NOT NULL, pages TEXT NOT NULL, summary TEXT NOT NULL,
                explanation TEXT NOT NULL, evidence TEXT NOT NULL, proposal_pid TEXT,
                run_id TEXT, fingerprint TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                reason TEXT, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS extractions (
                path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,status TEXT NOT NULL,pages INTEGER NOT NULL DEFAULT 0,
                chars INTEGER NOT NULL DEFAULT 0,error TEXT,started_at TEXT,finished_at TEXT);
            CREATE TABLE IF NOT EXISTS outline_overrides(sha256 TEXT PRIMARY KEY,outline TEXT NOT NULL,author TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS violations (
                rule_id TEXT NOT NULL, note TEXT NOT NULL, ref TEXT NOT NULL,
                author TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            migrations = {
                "tokens": {
                    "person": "TEXT",
                    "kind": "TEXT NOT NULL DEFAULT 'agent'",
                    "expires_at": "TEXT",
                },
                "proposals": {
                    "kind": "TEXT NOT NULL DEFAULT 'manual'",
                    "author_identity": "TEXT",
                    "author_kind": "TEXT NOT NULL DEFAULT 'agent'",
                    "accepted_commit": "TEXT",
                    "reverted_commit": "TEXT",
                },
                "proposal_editors": {"identity": "TEXT"},
            }
            for table, fields in migrations.items():
                existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for field, definition in fields.items():
                    if field not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {field} {definition}")
            db.execute(
                "UPDATE proposals SET author_identity=COALESCE((SELECT person FROM tokens WHERE name=author),author) WHERE author_identity IS NULL"
            )
            db.execute(
                "UPDATE proposal_editors SET identity=COALESCE((SELECT person FROM tokens WHERE tokens.name=proposal_editors.name),name) WHERE identity IS NULL"
            )
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

    def usage(self, ids: list[str], field: str) -> None:
        if field not in {"delivered", "opened", "violations"}:
            raise ValueError("Invalid usage field")
        with self.connect() as db:
            db.executemany(
                f"INSERT INTO rule_usage(rule_id,day,{field}) VALUES (?,?,1) ON CONFLICT(rule_id,day) DO UPDATE SET {field}={field}+1",
                [(page_id, now()[:10]) for page_id in ids],
            )
