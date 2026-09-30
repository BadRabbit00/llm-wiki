from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from wikisvc.config import Settings
from wikisvc.domain.ids import page_path
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Page
from wikisvc.domain.registry import Registry
from wikisvc.domain.validate import parse_page
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.initialize import initialize
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.schema import load_registry
from wikisvc.storage.state_db import StateDB


@pytest.fixture
def registry() -> Registry:
    return load_registry(Path(__file__).parents[1] / "src/wikisvc/template")


@pytest.fixture
def config(tmp_path: Path) -> Settings:
    config = Settings(
        wiki_root=tmp_path / "wiki", state_dir=tmp_path / "state", index_dir=tmp_path / "index"
    )
    initialize(config.wiki_root)
    source = SafeFS(Path(__file__).parent / "fixtures/wiki")
    target = SafeFS(config.wiki_root)
    for path in source.files("**/*"):
        target.write(path, source.read(path))
    GitRepo(config.wiki_root).commit("Add fixture corpus", "fixtures")
    return config


@pytest.fixture
def client(config: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(config)) as client:
        auth = Auth(StateDB(config.state_dir))
        client.headers["Authorization"] = "Bearer " + auth.create("test", "writer", "internal")
        yield client


def make_page(
    registry: Registry, page_id: str = "term-invoice", kind: str = "term", **changes: Any
) -> Page:
    definition = registry.page_type(kind)
    metadata: dict[str, Any] = {
        "id": page_id,
        "type": kind,
        "title": "Счета и проводки",
        "summary": "Описание счетов и правил выгрузки данных компании.",
        "status": "draft",
        "sensitivity": "internal",
        "created": "2026-01-01",
        "updated": "2026-01-01",
    }
    metadata.update(changes)
    body = "\n\n".join(
        f"## {heading}\n\nВыгрузка счёта. Invoice processing and exports."
        for heading in definition.required_sections
    )
    return parse_page(
        render(metadata, body), page_path(registry, kind, page_id, changes.get("parent"))
    )
