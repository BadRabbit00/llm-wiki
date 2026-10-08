import json
import shutil
from configparser import ConfigParser
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer

from wikiagent.check import check
from wikiagent.config import load_config
from wikiagent.heal.scheduler import in_window
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.relocate import repair_worktrees
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.state_db import StateDB


def test_backup_deployment_assets_and_service_lifecycle() -> None:
    deploy = Path(__file__).parents[1] / "deploy"
    for asset in (
        "systemd/llm-wiki-backup.service",
        "systemd/llm-wiki-backup.timer",
        "linux/backup.env",
        "backup.sh",
    ):
        assert (deploy / asset).is_file()
    service = ConfigParser(interpolation=None)
    service.read(deploy / "systemd/llm-wiki-backup.service")
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["User"] == service["Service"]["Group"] == "root"
    assert service["Service"]["UMask"] == "0077"
    assert service["Service"]["EnvironmentFile"] == "/etc/llm-wiki/backup.env"
    assert service["Service"]["ExecStartPre"].split() == [
        "/usr/bin/systemctl",
        "stop",
        "wiki-ui",
        "wikiagent",
        "wikisvc",
    ]
    assert service["Service"]["ExecStart"] == "/opt/llm-wiki/current/bin/llm-wiki-backup"
    # ExecStopPost also runs when stopping the writers or creating the archive fails.
    assert service["Service"]["ExecStopPost"].split() == [
        "/usr/bin/systemctl",
        "--no-block",
        "start",
        "wikisvc",
        "wikiagent",
        "wiki-ui",
    ]
    timer = ConfigParser(interpolation=None)
    timer.read(deploy / "systemd/llm-wiki-backup.timer")
    assert timer["Timer"].getboolean("Persistent")
    assert timer["Timer"]["Unit"] == "llm-wiki-backup.service"
    assert timer["Timer"]["OnCalendar"] == "*-*-* 23:00:00"
    config = load_config(deploy / "linux/wikiagent.yaml")
    assert not config.heal.enabled
    for hour in (23, 0):
        assert not in_window(datetime(2026, 1, 1, hour, tzinfo=UTC), config.heal.windows)
    assert "RATE_LIMIT_PER_MIN=120" in (deploy / "linux/service.env").read_text().splitlines()
    assert "BACKUP_KEEP_DAYS=14" in (deploy / "linux/backup.env").read_text().splitlines()


def test_development_example_loads() -> None:
    config = load_config(Path(__file__).parents[1] / "wikiagent.example.yaml")
    assert config.models["planner"].model == "wiki-gemma-12b"


def test_offline_copy_repairs_worktrees_and_preserves_review(
    config: Settings, tmp_path: Path
) -> None:
    with TestClient(create_app(config)) as client:
        token = Auth(StateDB(config.state_dir)).create("agent", "writer", "internal")
        client.headers["Authorization"] = "Bearer " + token
        pid = proposal(client)
        assert (
            client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
        )
        assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    old_git_file = (config.state_dir / "worktrees" / pid / ".git").read_text()
    moved = Settings(
        wiki_root=tmp_path / "new-host/wiki",
        state_dir=tmp_path / "new-host/state",
        index_dir=tmp_path / "new-host/index",
    )
    shutil.copytree(config.wiki_root, moved.wiki_root, symlinks=True)
    shutil.copytree(config.state_dir, moved.state_dir, symlinks=True)
    assert repair_worktrees(moved) == 1
    assert repair_worktrees(moved) == 1  # Safe to repeat.
    assert (config.state_dir / "worktrees" / pid / ".git").read_text() == old_git_file
    assert GitRepo(config.wiki_root).run("worktree", "list").find(str(moved.state_dir)) == -1
    with TestClient(create_app(moved)) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get(f"/api/v1/proposals/{pid}").json()["status"] == "submitted"
        reviewer(client, moved)
        accepted = client.post(f"/api/v1/proposals/{pid}/accept")
        assert accepted.status_code == 200, accepted.text
        assert client.get("/api/v1/pages/term-new").status_code == 200


def test_repair_rejects_incomplete_state_copy(config: Settings) -> None:
    repo = GitRepo(config.wiki_root)
    path = config.state_dir / "worktrees" / "abcdef"
    repo.add_worktree(path, "proposal/abcdef")
    shutil.rmtree(path)
    with pytest.raises(WikiError, match="Не перенесён"):
        repair_worktrees(config)


@pytest.mark.parametrize("failure", [None, "token", "alias", "generation"])
def test_deployment_readiness_and_structured_smoke(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    config = load_config(Path(__file__).parents[1] / "deploy/linux/wikiagent.yaml")
    monkeypatch.setenv("WIKIAGENT_TOKEN", "private-test-token")
    generated = []

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/whoami":
            assert request.headers["Authorization"] == "Bearer private-test-token"
            return httpx.Response(
                200, json={"role": "reviewer" if failure == "token" else "writer", "kind": "agent"}
            )
        if path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": "wrong" if failure == "alias" else "wiki-gemma-31b"}]}
            )
        if path == "/v1/chat/completions":
            body = json.loads(request.content)
            assert body["response_format"]["type"] == "json_schema"
            assert "Authorization" not in request.headers
            generated.append(body)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"ok":false}'
                                if failure == "generation"
                                else '{"ok":true}'
                            }
                        }
                    ]
                },
            )
        assert path == "/jobs"
        return httpx.Response(200, json={"items": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        if failure:
            with pytest.raises(ValueError):
                check(config, model=True, http=http)
        else:
            assert len(check(config, model=True, http=http)) == 3
            assert len(generated) == 1  # Shared model checked once, without any wiki writes.
            assert len(check(config, dependencies_only=True, http=http)) == 2
            assert len(generated) == 1
