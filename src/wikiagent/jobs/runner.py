import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from wikiagent.chat.loop import Chat
from wikiagent.client import WikiClient
from wikiagent.jobs.ingest_book import IngestBook
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError, not_found


class JobStopped(Exception):
    pass


class JobRunner:
    def __init__(
        self, state: AgentState, client: WikiClient, models: ModelClient, chat: Chat
    ) -> None:
        self.state, self.client, self.models, self.chat = state, client, models, chat
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wikiagent-job")
        self.lock = threading.Lock()
        self.active: set[str] = set()
        self.stopping = threading.Event()

    def boundary(self, job_id: str) -> None:
        row = self.state.rows("SELECT status FROM jobs WHERE id=?", (job_id,))[0]
        if self.stopping.is_set() or row["status"] in ("cancelled", "paused"):
            if row["status"] != "cancelled":
                self.state.status(job_id, "paused")
            raise JobStopped

    def start(self, job_id: str) -> None:
        with self.lock:
            if job_id not in self.active:
                self.active.add(job_id)
                self.state.status(job_id, "pending")
                self.pool.submit(self.run, job_id)

    def run(self, job_id: str) -> None:
        try:
            self.boundary(job_id)
            row = self.state.rows("SELECT * FROM jobs WHERE id=?", (job_id,))[0]
            self.state.status(job_id, "running")
            if row["kind"] == "ingest_book":
                IngestBook(self.client, self.models, self.state, self.boundary).run(
                    job_id, json.loads(row["payload"])
                )
            else:
                raise WikiError("E_JOB_KIND", "Неизвестный тип задачи.")
        except JobStopped:
            pass
        except Exception as exc:  # noqa: BLE001 -- job boundary persists failures for resumption
            self.state.status(
                job_id,
                "failed",
                error=exc.code if isinstance(exc, WikiError) else type(exc).__name__,
            )
        finally:
            with self.lock:
                self.active.discard(job_id)

    def recover(self) -> None:
        for row in self.state.rows(
            "SELECT id FROM jobs WHERE status IN ('running','pending','paused')"
        ):
            self.start(row["id"])

    def close(self) -> None:
        self.stopping.set()
        self.pool.shutdown(wait=True, cancel_futures=True)

    def get(self, job_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        rows = self.state.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        if (
            not rows
            or rows[0]["owner"] != (actor.get("person") or actor["name"])
            or ["public", "internal", "restricted"].index(actor["clearance"])
            < ["public", "internal", "restricted"].index(rows[0]["clearance"])
        ):
            raise not_found()
        result = rows[0]
        result["payload"] = json.loads(result["payload"])
        result["progress"] = json.loads(result["progress"])
        return result
