import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.project_templates import ProjectTemplate
from wikisvc.main import create_app
from wikisvc.storage.lock import write_lock
from wikisvc.storage.schema import load_registry


def template_data(config: Settings) -> dict[str, object]:
    registry = load_registry(config.wiki_root)
    profile = next(iter(registry.profiles))
    return {
        "id": "go-service",
        "title": "Go service",
        "profile": profile,
        "scopes": registry.profiles[profile].scopes,
        "files": [{"path": "main.go", "content": "package main"}],
        "components": [{"name": "api", "kind": "svc", "lang": "LANG-go"}],
        "policy_blocks": [{"file": "AGENTS.md", "profile": profile}],
    }


def write_template(config: Settings, data: dict[str, object], name: str = "go-service") -> Path:
    path = config.wiki_root / "schema/project-templates" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_template_api(config: Settings, client: TestClient) -> None:
    data = template_data(config)
    write_template(config, data)
    with TestClient(create_app(config)) as api:
        api.headers.update(client.headers)
        result = api.get("/api/v1/schema/project-templates/go-service")
        assert result.status_code == 200
        assert result.json() == data
        assert api.get("/api/v1/schema").json()["project_templates"]["go-service"] == data
        missing = api.get("/api/v1/schema/project-templates/absent")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "E_TEMPLATE_UNKNOWN"


@pytest.mark.parametrize(
    "path",
    [
        "../evil",
        "/evil",
        ".git/config",
        "x/.GIT/hooks/a",
        "a//b",
        "a/./b",
        "C:/x",
        "a\\b",
        "",
        "a\x00b",
        "a\nb",
        ".wiki-project.yaml",
    ],
)
def test_template_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        ProjectTemplate.model_validate(
            {"id": "go", "title": "Go", "profile": "go", "files": [{"path": path, "content": "x"}]}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"post_init": "echo pwn"},
        {"exec": "echo pwn"},
        {"script": "echo pwn"},
        {"command": "echo pwn"},
        {"files": [{"path": "a", "content": "x", "symlink": "../evil"}]},
        {"files": [{"path": str(i), "content": "x"} for i in range(300)]},
        {"files": [{"path": "a", "content": "x" * (1024 * 1024)}]},
        {"files": [{"path": "a", "content": "я" * (128 * 1024 + 1)}]},
        {"files": [{"path": str(i), "content": "x" * (256 * 1024)} for i in range(9)]},
        {"files": [{"path": "a", "content": "x"}, {"path": "a", "content": "x"}]},
        {"files": [{"path": "a", "content": "x"}, {"path": "a/b", "content": "x"}]},
        {"components": [{"name": "api", "kind": "svc"}] * 2},
        {"components": [{"name": "api", "kind": "svc", "lang": "go"}]},
        {"policy_blocks": [{"file": "AGENTS.md", "profile": "go"}] * 2},
        {"policy_blocks": [{"file": "../evil", "profile": "go"}]},
    ],
)
def test_template_rejects_unsafe_content(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjectTemplate.model_validate({"id": "go", "title": "Go", "profile": "go", **change})


@pytest.mark.parametrize(
    ("invalid", "reason"),
    [
        ("id", "ID шаблона не совпадает с именем файла."),
        ("profile", "Неизвестный профиль шаблона проекта."),
        ("scopes", "Неизвестный scope шаблона проекта."),
        ("policy", "Неизвестный профиль блока политик шаблона."),
        ("schema", "Невалидная структура шаблона проекта."),
    ],
)
def test_registry_quarantines_invalid_template(config: Settings, invalid: str, reason: str) -> None:
    data = template_data(config)
    healthy = {**data, "id": "healthy"}
    write_template(config, healthy, "healthy")
    if invalid == "id":
        data["id"] = "another"
    elif invalid == "profile":
        data["profile"] = "missing"
    elif invalid == "scopes":
        data["scopes"] = ["nonexistent:scope"]
    elif invalid == "policy":
        data["policy_blocks"] = [{"file": "AGENTS.md", "profile": "missing"}]
    else:
        data["post_init"] = "echo pwn"
    write_template(config, data)
    registry = load_registry(config.wiki_root)
    assert registry.invalid_project_templates == {"go-service": reason}
    assert set(registry.project_templates) == {"healthy"}
    assert registry.project_templates["healthy"].model_dump() == healthy


@pytest.mark.parametrize("invalid", ["yaml", "encoding", "schema", "scope", "profile", "policy"])
def test_quarantine_preserves_service(
    config: Settings, client: TestClient, caplog: pytest.LogCaptureFixture, invalid: str
) -> None:
    data = template_data(config)
    healthy = {**data, "id": "healthy"}
    write_template(config, healthy, "healthy")
    scopes_path = config.wiki_root / "schema/scopes.yaml"
    original_scopes = scopes_path.read_text()
    profile_path = config.wiki_root / "schema/profiles/disposable.yaml"
    if invalid == "scope":
        scopes = load_registry(config.wiki_root).scopes
        scopes_path.write_text(json.dumps([*scopes, "test:disposable"]))
        data["scopes"] = ["test:disposable"]
    elif invalid in {"profile", "policy"}:
        profile_path.write_text(
            json.dumps({"id": "disposable", "title": "Disposable", "scopes": []})
        )
        if invalid == "profile":
            data["profile"] = "disposable"
        else:
            data["policy_blocks"] = [{"file": "AGENTS.md", "profile": "disposable"}]
    path = write_template(config, data)
    assert "go-service" in load_registry(config.wiki_root).project_templates
    secret = "sensitive-template-content-never-echo"
    if invalid == "yaml":
        path.write_text(f"title: [{secret}")
    elif invalid == "encoding":
        path.write_bytes(secret.encode() + b"\xff")
    elif invalid == "schema":
        write_template(config, {**data, "post_init": secret})
    elif invalid == "scope":
        scopes_path.write_text(original_scopes)
    else:
        profile_path.unlink()

    caplog.clear()
    with (
        caplog.at_level(logging.WARNING, logger="wikisvc.storage.schema"),
        TestClient(create_app(config)) as api,
    ):
        api.headers.update(client.headers)
        assert api.get("/api/v1/schema/project-templates/healthy").status_code == 200
        broken = api.get("/api/v1/schema/project-templates/go-service")
        assert broken.status_code == 422
        assert broken.json()["error"]["code"] == "E_TEMPLATE_INVALID"
        assert broken.json()["error"]["details"] == []
        missing = api.get("/api/v1/schema/project-templates/absent")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "E_TEMPLATE_UNKNOWN"
        schema = api.get("/api/v1/schema")
        reason = broken.json()["error"]["message"]
        assert schema.json()["invalid_project_templates"] == {"go-service": reason}
        assert set(schema.json()["project_templates"]) == {"healthy"}
        lint = api.get("/api/v1/lint")
        issues = [i for i in lint.json()["issues"] if i["code"] == "E_TEMPLATE_INVALID"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert issues[0]["page"] == "schema/project-templates/go-service.yaml"
        assert issues[0]["message"] == reason
        assert secret not in broken.text + schema.text + lint.text + caplog.text
        policies = api.get("/api/v1/policies/compile", params={"profile": healthy["profile"]})
        assert policies.status_code == 200
        assert "markdown" in policies.json()
        warnings = [r for r in caplog.records if r.name == "wikisvc.storage.schema"]
        assert len(warnings) == 1
        assert all(r.levelno == logging.WARNING and r.exc_info is None for r in warnings)
        assert all("go-service" in r.message and reason in r.message for r in warnings)
        assert all(len(r.message.splitlines()) == 1 for r in warnings)

        # Rebuilding the registry after repair must release the template from quarantine.
        write_template(config, {**healthy, "id": "go-service"})
        with write_lock(config.state_dir, config.lock_timeout):
            api.app.state.runtime.reindex()
        assert api.get("/api/v1/schema/project-templates/go-service").status_code == 200
        assert api.get("/api/v1/schema").json()["invalid_project_templates"] == {}
        assert not any(
            i["code"] == "E_TEMPLATE_INVALID" for i in api.get("/api/v1/lint").json()["issues"]
        )


def test_lint_cli_reports_each_quarantined_template(
    config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = template_data(config)
    write_template(config, {**data, "post_init": "sensitive-content"})
    write_template(config, data, "other").write_text("title: [sensitive-content")
    monkeypatch.setenv("WIKI_ROOT", str(config.wiki_root))
    monkeypatch.setenv("STATE_DIR", str(config.state_dir))
    monkeypatch.setenv("INDEX_DIR", str(config.index_dir))
    result = CliRunner().invoke(app, ["lint"])
    assert result.exit_code == 1
    issues = [i for i in json.loads(result.stdout) if i["code"] == "E_TEMPLATE_INVALID"]
    assert len(issues) == 2
    assert {i["page"] for i in issues} == {
        "schema/project-templates/go-service.yaml",
        "schema/project-templates/other.yaml",
    }
    assert all(i["severity"] == "error" for i in issues)
    assert "sensitive-content" not in result.output


@pytest.mark.parametrize(
    "path",
    [
        "schema/profiles/*.yaml",
        "schema/page-types/*.yaml",
        "schema/relations.yaml",
        "schema/scopes.yaml",
    ],
)
def test_invalid_core_schema_still_prevents_startup(config: Settings, path: str) -> None:
    next(config.wiki_root.glob(path)).write_text("broken: [")
    with pytest.raises(WikiError, match="Некорректный YAML"), TestClient(create_app(config)):
        pytest.fail("Service started with invalid core schema")


def test_empty_templates_compatible(config: Settings) -> None:
    registry = load_registry(config.wiki_root)
    assert registry.project_templates == {}
    assert registry.invalid_project_templates == {}
