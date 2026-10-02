import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.services.policies import export_block
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def seed_policies(client: TestClient, config: Settings) -> None:
    documents = json.loads((Path(__file__).parent / "fixtures/policies40.json").read_text())
    fs = SafeFS(config.wiki_root)
    for document in documents:
        metadata = document["frontmatter"]
        fs.write("wiki/rules/" + metadata["id"][5:] + ".md", render(metadata, document["body_md"]))
    GitRepo(config.wiki_root).commit("Policy fixture", "fixture")
    client.app.state.runtime.reindex()


def test_compile_budget_scopes_version_usage(client: TestClient, config: Settings) -> None:
    seed_policies(client, config)
    params: dict[str, Any] = {"profile": "python-fastapi", "explain": True}
    result = client.get("/api/v1/policies/compile", params=params).json()
    assert result["used_tokens"] <= result["budget_tokens"] and not result["over_budget"]
    assert ".NET" not in result["markdown"]
    assert {"rule-policy-00", "rule-policy-01", "rule-policy-02"} <= {
        p["id"] for p in result["included"]
    }
    assert {"scope", "lifecycle", "level", "enforced"} <= {p["reason"] for p in result["omitted"]}
    again = client.get("/api/v1/policies/compile", params=params).json()
    assert result == again
    golden = Path(__file__).parent / "fixtures/policies-python-fastapi.md"
    assert result["markdown"] == golden.read_text()
    db = client.app.state.runtime.state
    assert (
        db.rows("SELECT delivered FROM rule_usage WHERE rule_id='rule-policy-00'")[0]["delivered"]
        == 2
    )
    client.get("/api/v1/pages/rule-policy-00")
    assert db.rows("SELECT opened FROM rule_usage WHERE rule_id='rule-policy-00'")[0]["opened"] == 1
    small = client.get("/api/v1/policies/compile", params={**params, "budget_tokens": 50}).json()
    assert small["over_budget"] and all(p["level"] == "must" for p in small["included"])
    fs = SafeFS(config.wiki_root)
    path = "wiki/rules/policy-00.md"
    fs.write(path, fs.read(path).replace("Соблюдай", "Соблюдайте"))
    # Even an admin rebuild without a new Git commit invalidates the cache.
    client.app.state.runtime.indexer.reindex([path])
    assert (
        client.get("/api/v1/policies/compile", params=params).json()["version"] != result["version"]
    )


def test_compile_access_enforcement_and_export(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_policies(client, config)
    assert client.get("/api/v1/profiles").json()[0]["id"] == "python-fastapi"
    assert "lang:python" in client.get("/api/v1/scopes").json()
    assert (
        client.get("/api/v1/policies/compile", params={"scopes": "lang:missing"}).status_code == 400
    )
    assert client.get("/api/v1/policies/compile", params={"profile": "missing"}).status_code == 404
    result = client.get(
        "/api/v1/policies/compile", params={"profile": "python-fastapi", "enforced": "all"}
    ).json()
    assert "rule-policy-06" in {p["id"] for p in result["included"]}
    assert "rule-policy-09" not in str(result)
    path = tmp_path / "project/AGENTS.md"
    path.parent.mkdir()
    path.write_text("Before\n")
    export_block(path, result)
    path.write_text(path.read_text() + "\nAfter\n")
    export_block(path, result)
    assert path.read_text().startswith("Before\n") and path.read_text().endswith("\nAfter\n")
    for name in ("wiki_root", "state_dir", "index_dir"):
        monkeypatch.setenv(name.upper(), str(getattr(config, name)))
    runner = CliRunner()
    assert (
        runner.invoke(
            app, ["policies", "export", "--profile", "python-fastapi", "--out", str(path)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["policies", "check", "--profile", "python-fastapi", "--file", str(path)]
        ).exit_code
        == 0
    )
    path.write_text("Missing block")
    assert (
        runner.invoke(
            app, ["policies", "check", "--profile", "python-fastapi", "--file", str(path)]
        ).exit_code
        == 1
    )
    assert runner.invoke(app, ["scopes", "add", "lang:rust"]).exit_code == 0
    assert "lang:rust" in SafeFS(config.wiki_root).read("schema/scopes.yaml")
