import subprocess
from pathlib import Path

from wikisvc.domain.errors import WikiError
from wikisvc.storage.safefs import SafeFS


def initialize(root: Path) -> None:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise WikiError("E_INIT_NONEMPTY", "Каталог для init должен быть пустым.", status=409)
    root.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).resolve().parents[1] / "template"
    source, target = SafeFS(template), SafeFS(root)
    for path in source.files("**/*"):
        target.write(path, source.path(path).read_bytes())
    target.path("CLAUDE.md").symlink_to("AGENTS.md")
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "add", "--all"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=wikisvc",
            "-c",
            "user.email=token@wikisvc.local",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Initialize company wiki",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
