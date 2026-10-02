import json
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wikisvc.domain.errors import WikiError


class GitRepo:
    managed = ("wiki", "raw", "schema")

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
        if self.git_path("MERGE_HEAD").exists():
            raise WikiError(
                "E_GIT_MERGING",
                "Обнаружено незавершённое слияние.",
                "Перезапустите сервис для восстановления или выполните git merge --abort.",
                status=409,
            )
        if (
            self.run("branch", "--show-current") != "main"
            or self.run("status", "--porcelain", "--", *self.managed)
            or self.run("diff", "--cached", "--name-only")
        ):
            raise WikiError(
                "E_GIT_DIRTY",
                "Нужна ветка main без правок wiki/, raw/, schema/ и подготовленных коммитов.",
                "Сохраните правки контента, уберите файлы из staging и переключитесь на main.",
                status=409,
            )

    def commit(self, message: str, author: str, paths: list[str] | None = None) -> str:
        selected = paths or list(self.managed)
        cached = set(self.run("ls-files", "--cached", "--", *selected).splitlines())
        add_paths = [p for p in selected if (self.root / p).exists() or p in cached]
        if add_paths:
            self.run("add", "--all", "--", *add_paths)
        if self.run("diff", "--cached", "--name-only"):
            options = (
                []
                if self.git_path("MERGE_HEAD").exists()
                else ["--only", "--", *(paths or self.managed)]
            )
            self.run("commit", "-m", message, *options, author=author)
        return self.head()

    def git_path(self, name: str) -> Path:
        return self.root / self.run("rev-parse", "--git-path", name)

    def recover(self) -> None:
        """Recover only paths owned by an interrupted service write, under write.lock."""
        journal = self.git_path("wikisvc-transaction.json")
        data = json.loads(journal.read_text()) if journal.exists() else None
        # Restore journal-owned paths before abort: promoted rules may differ from
        # the merge index, which would otherwise make `merge --abort` refuse.
        if data and self.head() == data["head"]:
            for path in data["paths"]:
                if self.run("ls-tree", "--name-only", data["head"], "--", path):
                    self.run(
                        "restore", "--source", data["head"], "--staged", "--worktree", "--", path
                    )
                else:
                    self.run("rm", "--cached", "--force", "--ignore-unmatch", "--", path)
                    from wikisvc.storage.safefs import SafeFS

                    SafeFS(self.root).path(path).unlink(missing_ok=True)
        if self.git_path("MERGE_HEAD").exists():
            self.run("merge", "--abort")
        if self.git_path("REVERT_HEAD").exists() or self.git_path("sequencer").exists():
            self.run("revert", "--abort")
        journal.unlink(missing_ok=True)

    @contextmanager
    def transaction(self, paths: list[str]) -> Iterator[None]:
        """Journal before touching files; roll back failed writes without resetting other paths."""
        from wikisvc.storage.safefs import SafeFS

        journal = self.git_path("wikisvc-transaction.json")
        if journal.exists():
            self.recover()
        SafeFS(journal.parent).write(
            journal.name, json.dumps({"head": self.head(), "paths": sorted(set(paths))})
        )
        try:
            yield
        except BaseException:
            self.recover()
            raise
        else:
            journal.unlink(missing_ok=True)

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
