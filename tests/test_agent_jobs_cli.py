"""wikiagent jobs: what llm-wiki-updater sees of the agent before and after an update."""

import json
from pathlib import Path

import pytest
from agent_helpers import agent_config
from typer.testing import CliRunner

from wikiagent.cli import app
from wikiagent.jobs.runner import RESUMABLE
from wikiagent.state import AgentState


def test_lists_jobs_recovery_resumes_without_their_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = agent_config(tmp_path / "agent")
    config = tmp_path / "wikiagent.yaml"
    config.write_text(json.dumps(settings.model_dump(mode="json")))
    monkeypatch.setenv("WIKIAGENT_CONFIG", str(config))
    state = AgentState(settings.state_dir)
    actor = {"name": "alice", "clearance": "internal"}
    created = {}
    for status in (*RESUMABLE, "awaiting_review", "cancelled", "failed"):
        job_id = state.job("ingest_book", actor, {"title": "confidential book"})
        state.status(job_id, status)
        created[status] = job_id

    result = CliRunner().invoke(app, ["jobs"])

    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert [row["id"] for row in listed] == [created[status] for status in RESUMABLE]
    assert [row["status"] for row in listed] == list(RESUMABLE)
    assert all(set(row) == {"id", "kind", "status", "updated_at"} for row in listed)
    assert "confidential" not in result.output
