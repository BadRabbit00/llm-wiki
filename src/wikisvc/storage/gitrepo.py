import re
import subprocess
from pathlib import Path

from wikisvc.domain.errors import WikiError


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, *args: str, author: str = "wikisvc") -> str:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"user.name={author}",
                "-c",
                "user.email=token@wikisvc.local",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD")

    def ensure_main(self) -> None:
        if self.run("branch", "--show-current") != "main" or self.run("status", "--porcelain"):
            raise WikiError(
                "E_GIT_DIRTY",
                "Репозиторий должен быть на чистой ветке main.",
                "Сохраните локальные изменения и переключитесь на main.",
                status=409,
            )

    def commit(self, message: str, author: str) -> str:
        self.run("add", "--all")
        if self.run("diff", "--cached", "--name-only"):
            self.run("commit", "-m", message, author=author)
        return self.head()

    def add_worktree(self, path: Path, branch: str, base: str = "main") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.run("worktree", "add", "-b", branch, str(path), base)

    def remove_worktree(self, path: Path, branch: str) -> None:
        if path.exists():
            self.run("worktree", "remove", "--force", str(path))
        if self.run("branch", "--list", branch):
            self.run("branch", "-D", branch)

    def changed(self, base: str, target: str = "HEAD") -> list[str]:
        return self.run("diff", "--name-only", base, target, "--").splitlines()

    def show(self, commit: str, path: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            raise WikiError("E_COMMIT_INVALID", "Нужен хеш коммита (7–40 символов).", status=400)
        if not path.startswith("wiki/") or ".." in Path(path).parts:
            raise WikiError("E_PATH_UNSAFE", "Недопустимый путь.", status=400)
        try:
            return self.run("show", f"{commit}:{path}") + "\n"
        except subprocess.CalledProcessError as exc:
            raise WikiError("E_NOT_FOUND", "Версия страницы не найдена.", status=404) from exc

    def history(self, path: str) -> list[dict[str, str]]:
        lines = self.run("log", "--format=%H%x09%an%x09%aI%x09%s", "--", path).splitlines()
        return [
            dict(zip(("commit", "author", "date", "message"), line.split("\t", 3), strict=True))
            for line in lines
        ]
