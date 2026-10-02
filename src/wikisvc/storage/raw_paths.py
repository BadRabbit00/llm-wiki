from pathlib import Path

from wikisvc.domain.errors import WikiError
from wikisvc.storage.safefs import SafeFS


def raw_path(root: Path, state_dir: Path, path: str) -> Path:
    if path.startswith("raw/"):
        return SafeFS(root).path(path)
    if path.startswith("library/"):
        return SafeFS(state_dir).path(path)
    raise WikiError("E_PATH_UNSAFE", "Источник должен находиться в raw/ или library/.", status=400)
