from pathlib import Path

import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import proposal, reviewer

from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.index.normalize import normalize
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def test_edits_parse_only_changed_files(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    for i in range(150):
        page = make_page(rt.registry, f"term-scale-{i}")
        fs.write(page.path, render(page.frontmatter.model_dump(), page.body_md))
    GitRepo(config.wiki_root).commit("Add scale corpus", "fixture")
    rt.reindex()
    pid = proposal(client)
    page = client.get("/api/v1/pages/term-orphan").json()
    read = SafeFS.read
    seen: list[str] = []

    def track(self: SafeFS, path: str) -> str:
        if path.startswith("wiki/"):
            seen.append(path)
            assert "/scale-" not in path, "Unchanged Markdown was parsed during editing"
        return read(self, path)

    monkeypatch.setattr(SafeFS, "read", track)
    assert (
        client.patch(
            f"/api/v1/proposals/{pid}/pages/term-orphan",
            json={
                "base_version": page["version"],
                "ops": [{"op": "set_field", "field": "title", "value": "Изменённое понятие"}],
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/proposals/{pid}/submit").status_code == 200
    reviewer(client, config)
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200
    assert seen


def test_reindex_does_not_reread_unchanged_raw(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = client.app.state.runtime
    original = Path.read_bytes
    reads: list[str] = []

    def read(self: Path) -> bytes:
        if self.is_relative_to(config.wiki_root / "raw"):
            reads.append(self.name)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    rt.indexer.reindex([])
    rt.indexer.reindex()
    assert reads == []
    SafeFS(config.wiki_root).write("raw/docs/new.txt", "new source")
    rt.indexer.reindex(["raw/docs/new.txt"])
    assert reads == ["new.txt"]


def test_search_identifiers_and_no_corpus_score(client: TestClient, config: Settings) -> None:
    assert normalize("1С 1СERP") == normalize("1C 1CERP")
    assert normalize("Счёт счета") == normalize("счет счетов")
    rt = client.app.state.runtime
    page = make_page(rt.registry, "term-onec", title="Система 1С")
    fs = SafeFS(config.wiki_root)
    fs.write(page.path, render(page.frontmatter.model_dump(), page.body_md))
    GitRepo(config.wiki_root).commit("Add 1C", "fixture")
    rt.reindex()
    first = client.get("/api/v1/search", params={"q": "1C", "expand": True}).json()
    assert first["results"][0]["id"] == "term-onec"
    for i in range(6):
        hidden = make_page(
            rt.registry, f"term-secret-{i}", title="Система 1С", sensitivity="restricted"
        )
        fs.write(hidden.path, render(hidden.frontmatter.model_dump(), hidden.body_md))
    GitRepo(config.wiki_root).commit("Hidden corpus", "fixture")
    rt.reindex()
    assert client.get("/api/v1/search", params={"q": "1C", "expand": True}).json() == first
    assert all("score" not in result for result in first["results"])


def test_incremental_index_recovers_omitted_duplicate(client: TestClient, config: Settings) -> None:
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    original = "wiki/domain/glossary/orphan.md"
    duplicate = "wiki/domain/glossary/aaa-duplicate.md"
    fs.write(duplicate, fs.read(original))
    assert "E_ID_DUPLICATE" in {i.code for i in rt.indexer.reindex()}
    fs.remove(duplicate)
    issues = rt.indexer.reindex([duplicate])
    assert "E_ID_DUPLICATE" not in {i.code for i in issues}
    assert client.get("/api/v1/pages/term-orphan").status_code == 200
    with rt.index.connect() as db:
        assert db.execute("SELECT path FROM pages WHERE id='term-orphan'").fetchone()[0] == original


@pytest.mark.parametrize("operation", ["raw", "verify"])
def test_writes_sync_external_commits(client: TestClient, config: Settings, operation: str) -> None:
    rt = client.app.state.runtime
    page = make_page(rt.registry, "term-external", title="Внешнее изменение")
    SafeFS(config.wiki_root).write(page.path, render(page.frontmatter.model_dump(), page.body_md))
    GitRepo(config.wiki_root).commit("External maintenance", "admin")
    reviewer(client, config)
    if operation == "raw":
        response = client.post(
            "/api/v1/raw",
            files={"file": ("upload.txt", b"external facts")},
            data={"category": "docs"},
        )
    else:
        response = client.post("/api/v1/pages/term-orphan/verify")
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/pages/term-external").json()["title"] == "Внешнее изменение"
