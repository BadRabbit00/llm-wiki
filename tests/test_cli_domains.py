"""`wikisvc domains add`: admin-only growth of the domain tree."""

import pytest
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.models import Principal
from wikisvc.services.runtime import Runtime
from wikisvc.services.schema import KB_KINDS
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.schema import load_domains
from wikisvc.storage.state_db import StateDB


@pytest.fixture
def env(config: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("WIKI_ROOT", str(config.wiki_root))
    monkeypatch.setenv("STATE_DIR", str(config.state_dir))
    monkeypatch.setenv("INDEX_DIR", str(config.index_dir))
    return config


def test_add_domain_is_one_commit_and_idempotent(env: Settings) -> None:
    repo, fs = GitRepo(env.wiki_root), SafeFS(env.wiki_root)
    result = CliRunner().invoke(app, ["domains", "add", "lang/zig", "--description", "Zig"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "lang/zig\n"
    assert load_domains(fs)["lang/zig"] == "Zig"
    for kind in KB_KINDS:
        assert (env.wiki_root / "wiki/kb/lang/zig" / kind / ".gitkeep").is_file()
    assert repo.run("log", "-1", "--format=%s|%an").strip() == "Add domain lang/zig|cli"
    head = repo.head()
    again = CliRunner().invoke(app, ["domains", "add", "lang/zig"])
    assert again.exit_code == 0 and repo.head() == head
    audit = StateDB(env.state_dir).rows("SELECT target FROM audit WHERE action='domain.add'")
    assert [row["target"] for row in audit] == ["lang/zig"]


@pytest.mark.parametrize("path", ["Lang", "nope/child", "a//b", "lang/"])
def test_add_domain_rejects_bad_paths(env: Settings, path: str) -> None:
    head = GitRepo(env.wiki_root).head()
    result = CliRunner().invoke(app, ["domains", "add", path])
    assert result.exit_code == 1 and "E_DOMAIN_UNKNOWN" in result.output
    assert GitRepo(env.wiki_root).head() == head


def test_add_domain_requires_admin(env: Settings) -> None:
    writer = Principal(name="w", role="writer", clearance="internal")
    with pytest.raises(WikiError) as error:
        Runtime(env).schema.add_domain("lang/zig", "Zig", writer)
    assert error.value.status == 403


def test_add_domain_restores_missing_directories(env: Settings) -> None:
    repo = GitRepo(env.wiki_root)
    keep = env.wiki_root / "wiki/kb/ml/facts/.gitkeep"
    repo.run("rm", "-q", "wiki/kb/ml/facts/.gitkeep")
    repo.run("commit", "-q", "-m", "drop")
    assert not keep.exists()
    assert CliRunner().invoke(app, ["domains", "add", "ml"]).exit_code == 0
    assert keep.is_file()


def test_scopes_add_keeps_axes_format(env: Settings) -> None:
    fs = SafeFS(env.wiki_root)
    assert "axes" in fs.read("schema/scopes.yaml")
    first = CliRunner().invoke(app, ["scopes", "add", "lang:zig"])
    assert first.exit_code == 0, first.output
    data = load_yaml(fs.read("schema/scopes.yaml"))
    assert isinstance(data, dict) and "lang:zig" in data["values"]
    assert data["axes"]["domain"] == {"hierarchical": True}
    head = GitRepo(env.wiki_root).head()
    assert CliRunner().invoke(app, ["scopes", "add", "lang:zig"]).exit_code == 0
    assert GitRepo(env.wiki_root).head() == head
    assert load_yaml(fs.read("schema/scopes.yaml"))["values"].count("lang:zig") == 1


def test_scopes_add_keeps_flat_list_format(env: Settings) -> None:
    fs, repo = SafeFS(env.wiki_root), GitRepo(env.wiki_root)
    fs.write("schema/scopes.yaml", "- lang:python\n")
    repo.commit("Flat scopes", "fixtures", ["schema/scopes.yaml"])
    assert CliRunner().invoke(app, ["scopes", "add", "lang:zig"]).exit_code == 0
    assert load_yaml(fs.read("schema/scopes.yaml")) == ["lang:python", "lang:zig"]
