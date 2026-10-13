import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
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


def write_profile(config: Settings, profile_id: str, scopes: list[str], budget: int) -> None:
    data = {"id": profile_id, "title": profile_id, "scopes": scopes, "budget_tokens": budget}
    SafeFS(config.wiki_root).write(f"schema/profiles/{profile_id}.yaml", json.dumps(data))


@pytest.mark.parametrize(
    "broken,status,code,reason",
    [
        ("scope", 400, "E_SCOPE_UNKNOWN", "Нужны известные области проекта"),
        ("budget", 400, "E_REQUEST_INVALID", "Некорректный бюджет или enforced"),
        (
            "category",
            422,
            "E_RULE_FIELDS",
            "Правило rule-no-category без обязательного поля category",
        ),
    ],
)
def test_broken_profile_is_reported_without_failing_lint(
    client: TestClient, config: Settings, broken: str, status: int, code: str, reason: str
) -> None:
    seed_policies(client, config)
    if broken == "scope":
        write_profile(config, "broken", ["lang:missing"], 2000)
    elif broken == "budget":
        write_profile(config, "broken", ["lang:python"], 100001)
    else:
        write_profile(config, "broken", ["app:cli"], 2000)
        documents = json.loads((Path(__file__).parent / "fixtures/policies40.json").read_text())
        metadata = {**documents[0]["frontmatter"], "id": "rule-no-category"}
        metadata["applies_to"] = ["app:cli"]
        del metadata["category"]
        SafeFS(config.wiki_root).write(
            "wiki/rules/no-category.md", render(metadata, documents[0]["body_md"])
        )
    GitRepo(config.wiki_root).commit("Broken profile", "fixture")
    client.app.state.runtime.reindex()

    response = client.get("/api/v1/lint", params={"limit": 100})
    assert response.status_code == 200, response.text
    # Only the broken profile is reported; python-fastapi still compiles inside lint.
    assert [i for i in response.json()["issues"] if i["code"] == "E_PROFILE_INVALID"] == [
        {
            "code": "E_PROFILE_INVALID",
            "severity": "error",
            "page": None,
            "message": f"Профиль broken не компилируется: {reason}.",
            "hint": "Исправьте scopes, budget_tokens профиля или поля его правил.",
        }
    ]
    stats = client.get("/api/v1/stats")
    assert stats.status_code == 200 and stats.json()["pages"] > 0
    healthy = client.get("/api/v1/policies/compile", params={"profile": "python-fastapi"})
    assert healthy.status_code == 200 and healthy.json()["included"]
    direct = client.get("/api/v1/policies/compile", params={"profile": "broken"})
    assert direct.status_code == status
    assert direct.json()["error"]["code"] == code


def test_profile_over_budget_boundary(client: TestClient, config: Settings) -> None:
    seed_policies(client, config)
    write_profile(config, "python-fastapi", ["lang:python", "framework:fastapi", "app:service"], 1)
    GitRepo(config.wiki_root).commit("Smallest budget", "fixture")
    client.app.state.runtime.reindex()
    params = {"profile": "python-fastapi"}
    musts = client.get("/api/v1/policies/compile", params=params).json()["used_tokens"]
    warning = {
        "code": "W_PROFILE_OVER_BUDGET",
        "severity": "warning",
        "page": None,
        "message": "Обязательные правила профиля python-fastapi превышают бюджет.",
        "hint": "Исправьте страницу по /schema.",
    }
    for budget, over in [(musts, False), (musts - 1, True)]:
        write_profile(
            config, "python-fastapi", ["lang:python", "framework:fastapi", "app:service"], budget
        )
        GitRepo(config.wiki_root).commit(f"Budget {budget}", "fixture")
        client.app.state.runtime.reindex()
        compiled = client.get("/api/v1/policies/compile", params=params).json()
        assert compiled["budget_tokens"] == budget
        assert compiled["used_tokens"] == (budget + 1 if over else budget)
        assert compiled["over_budget"] is over
        issues = client.get("/api/v1/lint", params={"limit": 100}).json()["issues"]
        assert (warning in issues) is over


@pytest.mark.parametrize(
    "corrupted",
    [
        "Before\n<!-- wikisvc:begin version=0123abcd -->\nold rules without end\n",
        (
            "<!-- wikisvc:begin version=0123abcd -->\na\n<!-- wikisvc:end -->\n"
            "<!-- wikisvc:begin version=4567abcd -->\nb\n<!-- wikisvc:end -->\n"
        ),
    ],
)
def test_export_refuses_corrupted_block(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupted: str,
) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text(corrupted)
    for name in ("wiki_root", "state_dir", "index_dir"):
        monkeypatch.setenv(name.upper(), str(getattr(config, name)))
    result = CliRunner().invoke(
        app, ["policies", "export", "--profile", "python-fastapi", "--out", str(path)]
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, WikiError)
    assert result.exception.code == "E_POLICY_BLOCK"
    assert path.read_text() == corrupted
