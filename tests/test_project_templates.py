import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.project_templates import ProjectTemplate
from wikisvc.main import create_app
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


@pytest.mark.parametrize("invalid", ["id", "profile", "scopes", "policy", "schema"])
def test_registry_rejects_invalid_template(config: Settings, invalid: str) -> None:
    data = template_data(config)
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
    with pytest.raises(WikiError) as error:
        load_registry(config.wiki_root)
    assert error.value.code == "E_TEMPLATE_INVALID"


def test_empty_templates_compatible(config: Settings) -> None:
    assert load_registry(config.wiki_root).project_templates == {}
