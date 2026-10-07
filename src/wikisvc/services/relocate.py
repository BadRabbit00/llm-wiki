"""Repair Git's absolute worktree links after an offline data transfer."""

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock


def repair_worktrees(config: Settings) -> int:
    # Deliberately avoid Runtime: its recovery needs the worktrees to be usable first.
    with write_lock(config.state_dir, config.lock_timeout):
        repo = GitRepo(config.wiki_root)
        git_dir = config.wiki_root / ".git"
        if not git_dir.is_dir():
            raise WikiError("E_RESTORE_INCOMPLETE", "WIKI_ROOT должен содержать основной .git.")
        paths = []
        for entry in sorted((git_dir / "worktrees").glob("*")):
            # wikisvc uses proposal IDs as both worktree names and directory names.
            path = config.state_dir / "worktrees" / entry.name
            if not path.is_dir() or not (path / ".git").is_file():
                raise WikiError(
                    "E_RESTORE_INCOMPLETE",
                    f"Не перенесён worktree {entry.name}; скопируйте STATE_DIR целиком.",
                )
            paths.append(path)
        repo.run("worktree", "repair", *(str(path) for path in paths))
        for path in paths:
            work = GitRepo(path)
            if (path / work.run("rev-parse", "--git-common-dir")).resolve() != git_dir.resolve():
                raise WikiError("E_RESTORE_INCOMPLETE", "Worktree связан с другим репозиторием.")
        return len(paths)
