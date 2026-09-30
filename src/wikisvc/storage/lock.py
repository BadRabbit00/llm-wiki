import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wikisvc.domain.errors import WikiError


@contextmanager
def write_lock(state_dir: Path, timeout: float = 30.0) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "write.lock").open("a") as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise WikiError(
                        "E_LOCK_TIMEOUT",
                        "Истекло время ожидания записи.",
                        "Повторите запрос позже.",
                        status=409,
                    )
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
