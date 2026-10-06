import threading
from collections.abc import Iterator
from contextlib import contextmanager


class PriorityGate:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.busy = False
        self.foreground_waiters = 0

    @contextmanager
    def enter(self, background: bool) -> Iterator[None]:
        with self.condition:
            if not background:
                self.foreground_waiters += 1
            try:
                while self.busy or (background and self.foreground_waiters):
                    self.condition.wait()
                self.busy = True
            finally:
                if not background:
                    self.foreground_waiters -= 1
        try:
            yield
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()
