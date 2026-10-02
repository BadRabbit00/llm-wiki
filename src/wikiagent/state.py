import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from wikisvc.storage.state_db import now


class AgentState:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / "agent.db"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,owner TEXT NOT NULL,clearance TEXT NOT NULL,payload TEXT NOT NULL,progress TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS job_state(job_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(job_id,key));
            CREATE TABLE IF NOT EXISTS pair_checks(a_id TEXT NOT NULL,a_hash TEXT NOT NULL,b_id TEXT NOT NULL,b_hash TEXT NOT NULL,verdict TEXT NOT NULL,confidence REAL NOT NULL,checked_at TEXT NOT NULL,PRIMARY KEY(a_id,a_hash,b_id,b_hash));
            CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY,owner TEXT NOT NULL,clearance TEXT NOT NULL,bind TEXT NOT NULL,profile TEXT,plan TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,plan TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS model_calls(day TEXT NOT NULL,role TEXT NOT NULL,task TEXT NOT NULL,ts TEXT NOT NULL);
            """)
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

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def checkpoint(self, job_id: str, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO job_state VALUES (?,?,?)",
                (job_id, key, json.dumps(value, ensure_ascii=False)),
            )

    def restore(self, job_id: str, key: str, default: Any = None) -> Any:
        rows = self.rows("SELECT value FROM job_state WHERE job_id=? AND key=?", (job_id, key))
        return json.loads(rows[0]["value"]) if rows else default

    def job(self, kind: str, actor: dict[str, Any], payload: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    kind,
                    "pending",
                    actor.get("person") or actor["name"],
                    actor["clearance"],
                    json.dumps(payload),
                    "{}",
                    None,
                    now(),
                    now(),
                ),
            )
        return job_id

    def status(
        self,
        job_id: str,
        status: str,
        progress: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status=?,progress=COALESCE(?,progress),error=?,updated_at=? WHERE id=?",
                (
                    status,
                    json.dumps(progress) if progress is not None else None,
                    error,
                    now(),
                    job_id,
                ),
            )
