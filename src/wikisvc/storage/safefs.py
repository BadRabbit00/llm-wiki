import os
import tempfile
from pathlib import Path

from wikisvc.domain.errors import WikiError


class SafeFS:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, relative: str) -> Path:
        part = Path(relative)
        if part.is_absolute() or ".." in part.parts or "\\" in relative or "\0" in relative:
            raise WikiError("E_PATH_UNSAFE", "Недопустимый путь.", status=400)
        candidate = (self.root / part).resolve()
        if not candidate.is_relative_to(self.root):
            raise WikiError("E_PATH_UNSAFE", "Путь выходит за пределы репозитория.", status=400)
        return candidate

    def read(self, relative: str) -> str:
        return self.path(relative).read_text(encoding="utf-8")

    def write(self, relative: str, content: str | bytes) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        fd, name = tempfile.mkstemp(prefix=".wikisvc-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path(relative))
        finally:
            Path(name).unlink(missing_ok=True)

    def remove(self, relative: str) -> None:
        self.path(relative).unlink()

    def files(self, pattern: str) -> list[str]:
        return sorted(
            str(path.relative_to(self.root)) for path in self.root.glob(pattern) if path.is_file()
        )
