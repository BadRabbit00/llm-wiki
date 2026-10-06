import logging
import threading
from datetime import UTC, datetime, timedelta

from wikiagent.jobs.runner import JobRunner


def in_window(moment: datetime, windows: list[str]) -> bool:
    minute = moment.hour * 60 + moment.minute
    for window in windows:
        start, end = (int(value[:2]) * 60 + int(value[3:]) for value in window.split("-"))
        if (start <= minute < end) if start < end else (minute >= start or minute < end):
            return True
    return not windows


class Scheduler:
    def __init__(self, runner: JobRunner) -> None:
        self.runner = runner
        self.started = datetime.now(UTC)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="wikiagent-idle", daemon=True)

    def tick(self, moment: datetime | None = None) -> str | None:
        moment = moment or datetime.now().astimezone()
        runner, config = self.runner, self.runner.models.config.heal
        if not config.enabled or not in_window(moment, config.windows):
            return None
        with runner.chat.condition:
            if runner.chat.active:
                return None
        if runner.state.rows(
            "SELECT id FROM jobs WHERE status IN ('pending','running','waiting_chat')"
        ):
            return None
        activity = [self.started]
        for query in (
            "SELECT MAX(updated_at) ts FROM chat_sessions",
            "SELECT MAX(updated_at) ts FROM jobs",
        ):
            value = runner.state.rows(query)[0]["ts"]
            if value:
                activity.append(datetime.fromisoformat(value))
        if moment - max(activity) < timedelta(minutes=config.idle_minutes):
            return None
        last_full = runner.state.restore("heal", "last_full")
        full = not last_full or moment - datetime.fromisoformat(last_full) >= timedelta(
            days=config.full_sweep_days
        )
        if not full:
            previous = runner.state.restore("heal", "hashes", {})
            if not any(
                previous.get(p["id"]) != p["version"]
                for p in runner.client.all("/rules", lifecycle="candidate,active,deprecated")
            ):
                return None
        return runner.heal(
            runner.client.check_writer(), "full" if full else "changed", scheduled=True
        )

    def loop(self) -> None:
        while not self.stopping.wait(30):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 -- keep scheduler alive; never log tokens or model data
                logging.getLogger(__name__).warning("Scheduled heal could not start; will retry.")

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stopping.set()
        self.thread.join()
