"""Knowledge-layer template: stage 1 schema files, kb tree on init and schema upgrade."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml
from wikisvc.services.initialize import initialize
from wikisvc.services.migrations import upgraded_scopes
from wikisvc.services.schema import KB_KINDS, with_scope, yaml_text
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.schema import load_domains

TEMPLATE = SafeFS(Path(__file__).parents[1] / "src/wikisvc/template")
FOLDERS = {"fact": "facts", "topic": "topics", "tech": "tech", "question": "questions"}
PREFIXES = {"fact": "f", "topic": "top", "tech": "tech", "question": "q"}
INSTRUCTIONS = "AGENTS" + ".md"


def yaml_file(path: str) -> dict[str, Any]:
    data = load_yaml(TEMPLATE.read(path))
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("kind", FOLDERS)
def test_new_page_types_use_domain_paths(kind: str) -> None:
    definition = yaml_file(f"schema/page-types/{kind}.yaml")
    prefix = PREFIXES[kind]
    assert definition["prefix"] == prefix
    assert definition["path_template"] == f"kb/{{domain}}/{FOLDERS[kind]}/{prefix}-{{slug}}.md"


def test_fact_fields_follow_the_card() -> None:
    fact = yaml_file("schema/page-types/fact.yaml")
    fields = fact["extra_fields"]
    assert fields["confidence"]["default"] == "inferred"
    assert fields["novelty"]["type"] == "dict"
    assert fields["valid_to"]["type"] == "date"
    assert "snippet" in fields["kind"]["enum"]
    assert fact["required_sections"] == ["Claim"]
    tech = yaml_file("schema/page-types/tech.yaml")["extra_fields"]
    assert "adoption" in tech and "status" not in tech
    topic = yaml_file("schema/page-types/topic.yaml")
    assert topic["required_sections"] == ["Digest", "Facts"]
    assert topic["extra_fields"]["priority"]["default"] == 3


def test_hub_types_do_not_require_sources() -> None:
    for kind in ("topic", "tech", "question"):
        assert yaml_file(f"schema/page-types/{kind}.yaml")["sources_required"] is False
    assert yaml_file("schema/page-types/fact.yaml").get("sources_required", True) is True


@pytest.mark.parametrize("raw", ["axes:\nvalues:\n", "values:\n", "axes: {}\nvalues: ~\n"])
def test_scopes_with_null_sections(raw: str, tmp_path: Path) -> None:
    assert yaml_text({"values": ["lang:zig"]}) in (with_scope(raw, "lang:zig") or "")
    fs = SafeFS(tmp_path)
    fs.write("schema/scopes.yaml", raw)
    upgraded = load_yaml(upgraded_scopes(fs, TEMPLATE) or "")
    assert upgraded["values"] == [] and upgraded["axes"]["domain"] == {"hierarchical": True}


def test_old_types_keep_domainless_paths_and_gain_grounded_in() -> None:
    for kind in ("rule", "adr", "pattern", "playbook"):
        definition = yaml_file(f"schema/page-types/{kind}.yaml")
        assert "{domain}" not in definition["path_template"]
        assert "grounded_in" in definition["allowed_relations"]
    source = yaml_file("schema/page-types/source.yaml")["extra_fields"]
    assert {"paper", "rfc", "video"} <= set(source["kind"]["enum"])
    assert source["covers"]["type"] == "list"


def test_relations_have_weights_and_inverses() -> None:
    relations = yaml_file("schema/relations.yaml")
    assert relations["covers"]["inverse"] == "covered_by"
    assert relations["covers"]["weight"] == 0.3
    assert relations["related"]["weight"] == 0.2
    assert relations["grounded_in"]["inverse"] == "grounds"
    assert set(relations["grounded_in"]["from"]) == {"rule", "adr", "pattern", "playbook"}
    assert relations["contradicts"]["symmetric"] is True
    assert "fact" in relations["refines"]["from"]
    assert "weight" not in relations["conflicts_with"]


def test_scopes_domains_and_profile() -> None:
    scopes = yaml_file("schema/scopes.yaml")
    assert scopes["axes"]["domain"] == {"hierarchical": True}
    assert "lang:python" in scopes["values"]
    domains = load_domains(TEMPLATE)
    assert {"systems", "lang", "lang/rust", "lang/nix", "math"} <= set(domains)
    assert len(domains) == 17
    profile = yaml_file("schema/profiles/python-fastapi.yaml")
    assert profile["brief"] == {"include_novelty": ["differs", "unique"], "max_facts": 40}


@pytest.mark.parametrize("text", ["- a\n", "Bad_Key: x\n", "a: 1\n"])
def test_load_domains_rejects_bad_files(text: str, tmp_path: Path) -> None:
    fs = SafeFS(tmp_path)
    fs.write("schema/domains.yaml", text)
    with pytest.raises(WikiError) as error:
        load_domains(fs)
    assert error.value.code == "E_SCHEMA_INVALID"


def test_workflows_and_instructions_mention_knowledge() -> None:
    for name in ("knowledge-query", "fact-authoring", "book-ingest"):
        assert TEMPLATE.read(f"schema/workflows/{name}.md").startswith("# ")
    assert "get_brief" in TEMPLATE.read(INSTRUCTIONS)
    assert "propose_fact" in TEMPLATE.read("schema/workflows/fact-authoring.md")


def test_initialize_creates_kb_tree(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    initialize(root)
    for domain in load_domains(TEMPLATE):
        for kind in KB_KINDS:
            assert (root / "wiki/kb" / domain / kind / ".gitkeep").is_file()
    assert "wiki/kb/lang/rust/facts/.gitkeep" in GitRepo(root).run("ls-files", "wiki/kb/lang/rust")


def test_schema_upgrade_adds_v3_without_losing_old(
    config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "WIKI_ROOT": config.wiki_root,
        "STATE_DIR": config.state_dir,
        "INDEX_DIR": config.index_dir,
    }.items():
        monkeypatch.setenv(name, str(value))
    fs, repo = SafeFS(config.wiki_root), GitRepo(config.wiki_root)
    fs.write("schema/scopes.yaml", "- lang:python\n- team:own\n")
    relations = load_yaml(fs.read("schema/relations.yaml"))
    for definition in relations.values():
        definition.pop("weight", None)
    relations["refines"]["from"] = ["rule"]
    relations["refines"]["to"] = ["rule"]
    relations["related"]["weight"] = 0.9
    for name in ("about", "covers", "grounded_in"):
        relations.pop(name)
    fs.write("schema/relations.yaml", yaml_text(relations))
    rule = fs.read("schema/page-types/rule.yaml").replace(", grounded_in", "")
    fs.write("schema/page-types/rule.yaml", rule)
    removed = [
        "schema/domains.yaml",
        "schema/page-types/fact.yaml",
        "schema/workflows/fact-authoring.md",
        *(f"wiki/kb/lang/rust/{kind}/.gitkeep" for kind in KB_KINDS),
    ]
    for path in removed:
        fs.remove(path)
    repo.commit(
        "Old schema",
        "fixtures",
        [*removed, "schema/scopes.yaml", "schema/relations.yaml", "schema/page-types/rule.yaml"],
    )

    result = CliRunner().invoke(app, ["schema", "upgrade"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert "schema/domains.yaml" in report["updated"]
    assert "wiki/kb/lang/rust/facts/.gitkeep" in report["updated"]
    scopes = load_yaml(fs.read("schema/scopes.yaml"))
    assert scopes["values"] == ["lang:python", "team:own"]
    assert scopes["axes"]["team"] == {} and scopes["axes"]["domain"] == {"hierarchical": True}
    new = load_yaml(fs.read("schema/relations.yaml"))
    assert new["related"]["weight"] == 0.9
    assert new["part_of"]["weight"] == 0.5
    assert new["refines"]["from"] == ["rule", "fact"]
    assert new["covers"]["weight"] == 0.3 and "grounded_in" in new
    assert "grounded_in" in load_yaml(fs.read("schema/page-types/rule.yaml"))["allowed_relations"]
    assert fs.path("schema/page-types/fact.yaml").exists()

    again = json.loads(CliRunner().invoke(app, ["schema", "upgrade"]).stdout)
    assert again["updated"] == [] and again["commit"] == report["commit"]
