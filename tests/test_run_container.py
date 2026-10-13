"""llm-wiki-run builds every podman invocation; check its flags without root or podman."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux deployment")

DIGEST = "ghcr.io/badrabbit00/llm-wiki@sha256:" + "ab" * 32
COMMON = [
    "--init", "--pull", "never", "--log-driver", "journald", "--network", "host",
    "--read-only", "--tmpfs", "/tmp:mode=1777", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--env", "PYTHONUNBUFFERED=1",
]  # fmt: skip
ETC = ["--volume", "/etc/llm-wiki:/etc/llm-wiki:ro"]


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, str]:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("sed", "tail"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    shim = tools / "host-tool"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "name, args = Path(sys.argv[0]).name, sys.argv[1:]\n"
        "if name == 'id':\n"
        "    ids = {'llm-wiki': ('990', '991'), 'llm-ui': ('992', '993')}\n"
        "    if args == ['-u']:\n"
        "        print(os.environ.get('TEST_UID', '0'))\n"
        "    else:\n"
        "        print(ids[args[1]][0 if args[0] == '-u' else 1])\n"
        "elif name == 'podman':\n"
        "    Path(os.environ['TEST_ROOT'], 'podman.json').write_text(json.dumps(args))\n"
        "else:\n"
        "    raise AssertionError(name)\n"
    )
    shim.chmod(0o755)
    for name in ("id", "podman"):
        (tools / name).symlink_to(shim)
    (tmp_path / "image.env").write_text(f"# pinned\nLLM_WIKI_IMAGE={DIGEST}\n")
    template = (Path(__file__).parents[1] / "deploy/run.sh").read_text()
    script = template.replace("@tools@", str(tools)).replace(
        "/etc/llm-wiki/image.env", str(tmp_path / "image.env")
    )
    (tmp_path / "run.sh").write_text(script)
    return {
        **os.environ,
        "TEST_ROOT": str(tmp_path),
        "LLM_WIKI_CIDFILE": "/run/wikisvc.service.ctr-id",
    }


def run(environment: dict[str, str], *args: str) -> tuple[int, list[str] | None, str]:
    shell = shutil.which("bash")
    assert shell is not None
    root = Path(environment["TEST_ROOT"])
    result = subprocess.run(
        [shell, str(root / "run.sh"), *args],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    recorded = root / "podman.json"
    podman = json.loads(recorded.read_text()) if recorded.exists() else None
    return result.returncode, podman, result.stderr


def test_daemon_services_keep_their_unit_confinement(environment: dict[str, str]) -> None:
    detach = ["run", "--detach", "--replace", "--rm"]
    cid = ["--cidfile", "/run/wikisvc.service.ctr-id", "--cgroups", "split"]
    notify = ["--sdnotify", "conmon"]
    assert run(environment, "daemon", "wikisvc")[1] == [
        *detach, "--name", "wikisvc", *cid, *notify, *COMMON,
        "--env-file", "/etc/llm-wiki/service.env",
        "--volume", "/var/lib/llm-wiki:/var/lib/llm-wiki", *ETC,
        "--user", "990:991", DIGEST, "wikisvc", "serve",
    ]  # fmt: skip
    assert run(environment, "daemon", "wikiagent")[1] == [
        *detach, "--name", "wikiagent", *cid, *notify, *COMMON,
        "--env-file", "/etc/llm-wiki/service.env", "--env-file", "/etc/llm-wiki/agent.env",
        "--volume", "/var/lib/llm-wiki:/var/lib/llm-wiki:ro",
        "--volume", "/var/lib/llm-wiki/agent:/var/lib/llm-wiki/agent", *ETC,
        "--user", "990:991", DIGEST, "wikiagent", "serve",
    ]  # fmt: skip
    assert run(environment, "daemon", "wiki-ui")[1] == [
        *detach, "--name", "wiki-ui", *cid, *notify, *COMMON,
        "--env-file", "/etc/llm-wiki/ui.env", *ETC,
        "--user", "992:993", DIGEST, "wiki-ui",
    ]  # fmt: skip


def test_maintenance_runs_the_given_command_once(environment: dict[str, str]) -> None:
    status, podman, _ = run(environment, "once", "maintenance", "wikisvc", "schema", "upgrade")
    assert status == 0
    assert podman == [
        "run", "--rm", *COMMON,
        "--env-file", "/etc/llm-wiki/service.env", "--env-file", "/etc/llm-wiki/agent.env",
        "--env-file", "/etc/llm-wiki/ui.env",
        "--volume", "/var/lib/llm-wiki:/var/lib/llm-wiki", *ETC,
        "--user", "990:991", DIGEST, "wikisvc", "schema", "upgrade",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("image", "args", "uid", "status", "message"),
    [
        ("ghcr.io/badrabbit00/llm-wiki:v1.0.0", ("daemon", "wikisvc"), "0", 1, "pinned by digest"),
        ("", ("daemon", "wikisvc"), "0", 1, "pinned by digest"),
        (DIGEST, ("daemon", "maintenance"), "0", 2, "Usage"),
        (DIGEST, ("daemon", "wikisvc", "extra"), "0", 2, "Usage"),
        (DIGEST, ("once", "wikisvc"), "0", 2, "Usage"),
        (DIGEST, ("daemon", "wikisvc"), "1000", 1, "Run as root"),
    ],
)
def test_refuses_without_side_effects(
    environment: dict[str, str],
    image: str,
    args: tuple[str, ...],
    uid: str,
    status: int,
    message: str,
) -> None:
    Path(environment["TEST_ROOT"], "image.env").write_text(f"LLM_WIKI_IMAGE={image}\n")
    environment["TEST_UID"] = uid
    code, podman, stderr = run(environment, *args)
    assert (code, podman) == (status, None)
    assert message in stderr


def test_daemon_needs_the_unit_cid_file(environment: dict[str, str]) -> None:
    del environment["LLM_WIKI_CIDFILE"]
    code, podman, stderr = run(environment, "daemon", "wikisvc")
    assert (code, podman) == (1, None)
    assert "LLM_WIKI_CIDFILE" in stderr
