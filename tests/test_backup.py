"""Run the packaged backup script on temporary data without root or real services."""

import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux deployment")


@pytest.fixture
def backup_environment(tmp_path: Path) -> dict[str, str]:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("realpath", "mktemp", "date", "chmod", "mv", "rm", "find", "gzip"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    # Redirect just the archive inputs and privileged ownership operation. The real
    # tar, permissions, atomic publication, failure cleanup and retention still run.
    shim = tools / "host-tool"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "if name == 'id':\n"
        "    assert args == ['-u']\n"
        "    print(os.environ.get('TEST_UID', '0'))\n"
        "elif name == 'install':\n"
        "    assert args[:8] == ['-d', '-m', '0700', '-o', 'root', '-g', 'root', '--']\n"
        "    assert Path(args[-1]).is_relative_to(os.environ['TEST_ROOT'])\n"
        f"    sys.exit(subprocess.call([{shutil.which('install')!r}, *args[:3], *args[7:]]))\n"
        "elif name == 'restorecon':\n"
        "    assert len(args) == 1\n"
        "    assert Path(args[0]).is_relative_to(os.environ['TEST_ROOT'])\n"
        "elif name == 'tar':\n"
        "    assert args[:3] == ['-C', '/', '-czf']\n"
        "    assert args[4:] == ['var/lib/llm-wiki/wiki', 'var/lib/llm-wiki/state',\n"
        "                         'var/lib/llm-wiki/agent', 'etc/llm-wiki']\n"
        "    if os.environ.get('TEST_TAR_FAIL'):\n"
        "        Path(args[3]).write_text('incomplete archive')\n"
        "        sys.exit(2)\n"
        "    args[1] = os.environ['TEST_ROOT'] + '/source'\n"
        f"    sys.exit(subprocess.call([{shutil.which('tar')!r}, *args]))\n"
        "else:\n"
        "    raise AssertionError(name)\n"
    )
    shim.chmod(0o755)
    for name in ("id", "install", "restorecon", "tar"):
        (tools / name).symlink_to(shim)
    source = tmp_path / "source"
    for relative in (
        "var/lib/llm-wiki/wiki/.git/config",
        "var/lib/llm-wiki/wiki/docs/page.md",
        "var/lib/llm-wiki/state/state.db",
        "var/lib/llm-wiki/state/worktrees/proposal/.git",
        "var/lib/llm-wiki/state/library/book.txt",
        "var/lib/llm-wiki/agent/agent.db",
        "var/lib/llm-wiki/index/index.db",
        "etc/llm-wiki/agent.env",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture data")
    script = tmp_path / "backup.sh"
    template = (Path(__file__).parents[1] / "deploy/backup.sh").read_text()
    script.write_text(template.replace("@tools@", str(tools)))
    return {
        **os.environ,
        "TEST_ROOT": str(tmp_path),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "BACKUP_KEEP_DAYS": "14",
    }


def run_backup(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("bash")
    assert shell is not None
    return subprocess.run(
        [shell, str(Path(environment["TEST_ROOT"]) / "backup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("failure", [False, True])
def test_backup_archive_permissions_retention_and_failure(
    backup_environment: dict[str, str], failure: bool
) -> None:
    directory = Path(backup_environment["BACKUP_DIR"])
    directory.mkdir(mode=0o755)
    for name, age in (("data-old.tar.gz", 15), ("data-recent.tar.gz", 1), ("other.tar.gz", 15)):
        path = directory / name
        path.touch()
        timestamp = time.time() - age * 86400
        os.utime(path, (timestamp, timestamp))
    nested = directory / "nested" / "data-old.tar.gz"
    nested.parent.mkdir()
    nested.touch()
    timestamp = time.time() - 15 * 86400
    os.utime(nested, (timestamp, timestamp))
    if failure:
        backup_environment["TEST_TAR_FAIL"] = "1"
    result = run_backup(backup_environment)
    assert result.returncode == (2 if failure else 0), result.stderr
    assert directory.stat().st_mode & 0o777 == 0o700
    assert not list(directory.glob("*.partial"))
    assert (directory / "data-old.tar.gz").exists() == failure
    assert (directory / "data-recent.tar.gz").exists()
    assert (directory / "other.tar.gz").exists()
    assert nested.exists()
    archives = [path for path in directory.glob("data-*.tar.gz") if "T" in path.name]
    assert len(archives) == (0 if failure else 1)
    if archives:
        assert archives[0].stat().st_mode & 0o777 == 0o600
        with tarfile.open(archives[0]) as archive:
            names = set(archive.getnames())
        source = Path(backup_environment["TEST_ROOT"]) / "source"
        expected = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()}
        expected.remove("var/lib/llm-wiki/index/index.db")
        assert expected <= names
        assert not any(name.startswith("var/lib/llm-wiki/index") for name in names)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("BACKUP_DIR", "relative"),
        ("BACKUP_DIR", "/"),
        ("BACKUP_DIR", "/var/lib/llm-wiki/backups"),
        ("BACKUP_DIR", "/etc/llm-wiki/backups"),
        ("BACKUP_KEEP_DAYS", "0"),
        ("BACKUP_KEEP_DAYS", "-1"),
        ("BACKUP_KEEP_DAYS", "bad"),
        ("TEST_UID", "1000"),
    ],
)
def test_backup_rejects_invalid_configuration_before_writing(
    backup_environment: dict[str, str], key: str, value: str
) -> None:
    backup_environment[key] = value
    assert run_backup(backup_environment).returncode != 0
    assert not (Path(backup_environment["TEST_ROOT"]) / "backups").exists()


def test_backup_rejects_directory_symlink_into_archived_data(
    backup_environment: dict[str, str],
) -> None:
    directory = Path(backup_environment["BACKUP_DIR"])
    directory.symlink_to("/var/lib/llm-wiki/state")
    assert run_backup(backup_environment).returncode == 2
