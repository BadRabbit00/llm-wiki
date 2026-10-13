"""Version tags publish releases: the guard script and the version it compares against."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import wikiagent
import wikisvc

ROOT = Path(__file__).parents[1]


def test_every_version_declaration_agrees() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    flake = re.search(
        r'pname = "wikisvc";\s*version = "([^"]+)";', (ROOT / "flake.nix").read_text()
    )
    assert flake is not None
    assert wikisvc.__version__ == wikiagent.__version__ == flake[1] == declared


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git = shutil.which("git")
    assert git is not None

    def run(*args: str) -> None:
        subprocess.run(
            [git, "-c", "user.name=test", "-c", "user.email=test@example.org", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "wikisvc"\nversion = "1.2.0"\n')
    run("init", "--quiet", "--initial-branch=main")
    run("add", "pyproject.toml")
    run("commit", "--quiet", "--message", "release line 1.2.0")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    for tag in ("v1.2.0", "v1.2.0-beta.3", "v1.3.0"):
        run("tag", tag)
    run("switch", "--quiet", "--create", "unreviewed")
    run("commit", "--quiet", "--allow-empty", "--message", "never merged")
    run("tag", "v1.2.0-beta.4")
    return tmp_path


@pytest.mark.parametrize(
    ("tag", "published", "reason"),
    [
        ("v1.2.0", True, "commit on main"),
        ("v1.2.0-beta.3", True, "commit on main"),
        ("v1.3.0", False, "pyproject.toml declares 1.2.0"),
        ("v1.2.0-beta.4", False, "not on main"),
        ("v1.2", False, "neither"),
        ("v01.2.0", False, "neither"),
        ("v1.2.0-rc.1", False, "neither"),
    ],
)
def test_release_tag_guard(repository: Path, tag: str, published: bool, reason: str) -> None:
    shell = shutil.which("bash")
    assert shell is not None
    result = subprocess.run(
        [shell, str(ROOT / "scripts/check-release-tag.sh"), tag],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is published, result.stderr
    assert reason in result.stdout + result.stderr
