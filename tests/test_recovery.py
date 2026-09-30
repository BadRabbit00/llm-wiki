import io
import os
import subprocess
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal
from wikisvc.main import create_app
from wikisvc.services.runtime import Runtime
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def submitted(client: TestClient, config: Settings) -> str:
    pid = proposal(client)
    assert client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=payload()).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    reviewer(client, config)
    return pid


def test_inbox_obsidian_and_unrelated_changes_survive_accept(
    client: TestClient, config: Settings
) -> None:
    fs, repo = SafeFS(config.wiki_root), GitRepo(config.wiki_root)
    fs.write("inbox/upload.txt", "Inbox contents")
    fs.write(".obsidian/workspace.json", "{}")
    fs.write("notes.txt", "untracked scratchpad")
    fs.write("AGENTS.md", fs.read("AGENTS.md") + "\nLocal note\n")
    pid = submitted(client, config)
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200
    repo.ensure_main()
    assert repo.run("status", "--porcelain") == "M AGENTS.md\n?? notes.txt"
    assert "Local note" not in repo.run("show", "HEAD:AGENTS.md")
    assert fs.read("inbox/upload.txt") == "Inbox contents"
    assert not repo.run("ls-files", "--", "inbox/upload.txt", ".obsidian", "notes.txt")


@pytest.mark.parametrize("failure", ["merge_started", "generate", "commit"])
def test_accept_failure_rolls_back_and_can_retry(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    pid = submitted(client, config)
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    fs = SafeFS(config.wiki_root)
    original_log = fs.read("wiki/log.md")
    with monkeypatch.context() as patch:
        if failure == "merge_started":
            run = GitRepo.run

            def fail_after_merge(self: GitRepo, *args: str, **kwargs: Any) -> str:
                result = run(self, *args, **kwargs)
                if args[:3] == ("merge", "--no-ff", "--no-commit"):
                    raise RuntimeError("Interrupted after merge")
                return result

            patch.setattr(GitRepo, "run", fail_after_merge)
        else:

            def fail(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("Injected write failure")

            if failure == "generate":
                patch.setattr("wikisvc.services.proposals.generate", fail)
            else:
                patch.setattr(GitRepo, "commit", fail)
        with pytest.raises(RuntimeError):
            client.post(f"/api/v1/proposals/{pid}/accept")
    assert repo.head() == head
    assert not repo.git_path("MERGE_HEAD").exists()
    assert not repo.git_path("wikisvc-transaction.json").exists()
    assert fs.read("wiki/log.md") == original_log
    assert not fs.path("wiki/domain/glossary/new.md").exists()
    repo.ensure_main()
    assert client.get(f"/api/v1/proposals/{pid}").json()["status"] == "submitted"
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200


@pytest.mark.parametrize("operation", ["raw", "verify", "put", "delete"])
def test_failed_commit_restores_files(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    rt = client.app.state.runtime
    actor = Principal(name="reviewer", role="reviewer", clearance="restricted")
    pid = proposal(client)
    repo = GitRepo(
        config.state_dir / "worktrees" / pid if operation in {"put", "delete"} else config.wiki_root
    )
    before = repo.head()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Commit failed")

    with monkeypatch.context() as patch:
        patch.setattr(GitRepo, "commit", fail)
        with pytest.raises(RuntimeError):
            if operation == "raw":
                rt.raw.upload(actor, "new.txt", io.BytesIO(b"new source"), "docs")
            elif operation == "verify":
                from wikisvc.services.review import review

                review(rt, actor, "term-orphan", True)
            elif operation == "put":
                data = payload()
                rt.proposals.put(pid, "term-new", actor, data["frontmatter"], data["body_md"])
            else:
                rt.proposals.delete(pid, "term-orphan", actor)
    assert repo.head() == before
    assert repo.run("status", "--porcelain") == ""


def test_startup_aborts_interrupted_merge(client: TestClient, config: Settings) -> None:
    pid = submitted(client, config)
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    repo.run("merge", "--no-ff", "--no-commit", "proposal/" + pid)
    with pytest.raises(WikiError) as error:
        repo.ensure_main()
    assert error.value.code == "E_GIT_MERGING"
    with TestClient(create_app(config)) as restarted:
        assert restarted.get("/api/v1/health").json()["index_commit"] == head
    repo.ensure_main()
    assert not repo.git_path("MERGE_HEAD").exists()


@pytest.mark.parametrize("path", ["raw/docs/interrupted.txt", "wiki/domain/glossary/orphan.md"])
def test_journal_survives_process_death(config: Settings, path: str) -> None:
    repo = GitRepo(config.wiki_root)
    before = repo.head()
    script = """
import os, sys
from pathlib import Path
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
repo = GitRepo(Path(sys.argv[1]))
with repo.transaction([sys.argv[2]]):
    SafeFS(repo.root).write(sys.argv[2], 'interrupted')
    repo.run('add', '--', sys.argv[2])
    os._exit(9)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(config.wiki_root), path],
        check=False,
        env=os.environ.copy(),
    )
    assert result.returncode == 9
    assert repo.git_path("wikisvc-transaction.json").exists()
    Runtime(config)
    assert repo.head() == before
    repo.ensure_main()
    assert not repo.git_path("wikisvc-transaction.json").exists()


def test_startup_reconciles_committed_accept(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = submitted(client, config)
    rt = client.app.state.runtime
    with monkeypatch.context() as patch:

        def fail(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("State unavailable after durable commit")

        patch.setattr(rt.proposals, "_status", fail)
        with pytest.raises(RuntimeError):
            client.post(f"/api/v1/proposals/{pid}/accept")
    with TestClient(create_app(config)) as restarted:
        restarted.headers.update(client.headers)
        assert restarted.get(f"/api/v1/proposals/{pid}").json()["status"] == "accepted"
        assert restarted.get("/api/v1/pages/term-new").status_code == 200
    assert not (config.state_dir / "worktrees" / pid).exists()
