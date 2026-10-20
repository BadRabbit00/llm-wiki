"""Knowledge layer v3: domains, weighted edges, field types and local/set lint codes."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import check_domain, page_path
from wikisvc.domain.markdown import edges, render
from wikisvc.domain.models import Frontmatter, Page, RelationRef
from wikisvc.domain.registry import ExtraField, PageType, Registry, Relation, ScopeAxis
from wikisvc.domain.validate import (
    ValidationCache,
    http_url_ok,
    overlaps,
    parse_page,
    valid_extra,
    valid_for_ok,
    validate_page,
    validate_set,
)
from wikisvc.storage.schema import load_registry

DOMAINS = {"db": "storage", "db/kv": "key-value", "lang": "languages", "lang/rust": "rust"}
CLAIM = "Write-ahead log makes commits durable."


def fields(**definitions: dict[str, Any]) -> dict[str, ExtraField]:
    return {name: ExtraField.model_validate(value) for name, value in definitions.items()}


def build_registry() -> Registry:
    types = [
        PageType(
            type="fact",
            prefix="f",
            path_template="kb/{domain}/facts/f-{slug}.md",
            title_ru="Факт",
            required_sections=["Claim"],
            sources_required=False,
            extra_fields=fields(
                claim={"required": True},
                kind={"required": True, "enum": ["definition", "number", "api", "pitfall"]},
                confidence={"enum": ["sourced", "inferred"], "default": "inferred"},
                novelty={"type": "dict", "item_enum": ["common", "differs"], "default": {}},
                valid_for={},
                valid_from={"type": "date"},
            ),
            allowed_relations=["about", "supports", "refines", "related", "replaces"],
        ),
        PageType(
            type="topic",
            prefix="top",
            path_template="kb/{domain}/topics/top-{slug}.md",
            title_ru="Хаб",
            required_sections=["Digest", "Facts"],
            sources_required=False,
            extra_fields=fields(priority={"type": "int", "min": 1, "max": 5}),
            allowed_relations=["part_of", "related"],
        ),
        PageType(
            type="tech",
            prefix="tech",
            path_template="kb/{domain}/tech/tech-{slug}.md",
            title_ru="Технология",
            sources_required=False,
            extra_fields=fields(
                category={"required": True},
                adoption={"required": True},
                verdict={"required": True},
                homepage={},
            ),
            allowed_relations=["related"],
        ),
        PageType(
            type="term",
            prefix="term",
            path_template="glossary/{slug}.md",
            title_ru="Термин",
            sources_required=False,
            allowed_relations=["related", "grounded_in"],
        ),
        PageType(
            type="source",
            prefix="src",
            path_template="sources/{slug}.md",
            title_ru="Источник",
            sources_required=False,
            extra_fields=fields(url={}, covers={"type": "list", "item_pattern": "top-.+"}),
            allowed_relations=["related"],
        ),
        PageType(
            type="rule",
            prefix="rule",
            path_template="rules/{slug}.md",
            title_ru="Правило",
            sources_required=False,
            extra_fields=fields(
                applies_to={"type": "list"},
                lifecycle={},
                level={},
            ),
            allowed_relations=["conflicts_with", "grounded_in", "related"],
        ),
    ]
    registry = Registry.from_documents(
        [t.model_dump() for t in types],
        {
            "about": {"inverse": "has_fact", "from": ["fact"], "to": ["topic", "tech"]},
            "supports": {
                "inverse": "supported_by",
                "from": ["fact"],
                "to": ["fact"],
                "weight": 0.7,
            },
            "refines": {"inverse": "refined_by", "from": ["fact"], "to": ["fact"], "weight": 0.7},
            "replaces": {"inverse": "replaced_by", "weight": 0.7},
            "grounded_in": {"inverse": "grounds", "from": ["rule", "term"], "to": ["fact"]},
            "part_of": {"inverse": "has_part", "same_type": True, "weight": 0.5},
            "related": {"inverse": "related", "symmetric": True, "weight": 0.2},
            "conflicts_with": {"inverse": "conflicts_with", "symmetric": True},
        },
        [],
    )
    registry.domains = DOMAINS
    registry.scopes = ["lang:python"]
    registry.scope_axes = {
        "domain": ScopeAxis(hierarchical=True),
        "lang": ScopeAxis(),
        "tech": ScopeAxis.model_validate({"from": "tech-pages"}),
        "layer": ScopeAxis(enum=["kernel", "app"]),
    }
    return registry


@pytest.fixture
def reg() -> Registry:
    return build_registry()


def make(
    reg: Registry,
    page_id: str,
    type_name: str,
    body: str = "",
    path: bool = True,
    **changes: Any,
) -> Page:
    metadata: dict[str, Any] = {
        "id": page_id,
        "type": type_name,
        "title": "Заголовок страницы",
        "summary": "A sufficiently long summary of the page.",
        "status": "draft",
        "created": "2026-01-01",
        "updated": "2026-01-01",
    }
    metadata.update(changes)
    definition = reg.page_type(type_name)
    sections = "\n\n".join(f"## {h}\n\nText of the section." for h in definition.required_sections)
    location = ""
    if path:
        location = page_path(
            reg, type_name, page_id, metadata.get("parent"), metadata.get("domain")
        )
    return parse_page(render(metadata, body or sections), location)


def fact(reg: Registry, page_id: str = "f-wal", **changes: Any) -> Page:
    data: dict[str, Any] = {
        "domain": "db",
        "claim": CLAIM,
        "kind": "definition",
        "relations": {"about": ["top-wal"]},
    }
    data.update(changes)
    return make(reg, page_id, "fact", **data)


def codes(issues: list[Any]) -> set[str]:
    return {issue.code for issue in issues}


def test_valid_fact_has_no_issues(reg: Registry) -> None:
    assert validate_page(fact(reg), reg) == []


# -- load_registry ---------------------------------------------------------------------------


def write_schema(root: Path, **files: str) -> Path:
    (root / "schema/page-types").mkdir(parents=True)
    (root / "schema/profiles").mkdir()
    (root / "schema/tags.yaml").write_text("[]\n")
    (root / "schema/relations.yaml").write_text(
        "related: {inverse: related, symmetric: true}\n"
        "about: {inverse: has_fact, weight: 0.9, from: [fact], to: [topic]}\n"
    )
    for name, text in files.items():
        (root / "schema" / name).write_text(text)
    return root


def test_load_registry_v3(tmp_path: Path) -> None:
    root = write_schema(
        tmp_path,
        **{
            "domains.yaml": 'db: "storage"\ndb/kv: "kv stores"\n',
            "scopes.yaml": (
                "axes:\n  domain: {hierarchical: true}\n  lang: {}\n"
                '  layer: {enum: [app]}\nvalues: ["lang:python"]\n'
            ),
        },
    )
    registry = load_registry(root)
    assert registry.domains == {"db": "storage", "db/kv": "kv stores"}
    assert registry.scopes == ["lang:python"]
    assert registry.scope_axes["domain"].hierarchical
    assert registry.scope_axes["layer"].enum == ["app"]
    assert registry.relations["about"].weight == 0.9
    assert registry.relations["related"].weight == 1.0


def test_load_registry_old_scopes_list_and_no_domains(tmp_path: Path) -> None:
    root = write_schema(tmp_path, **{"scopes.yaml": "- lang:python\n- app:service\n"})
    registry = load_registry(root)
    assert registry.scopes == ["lang:python", "app:service"]
    assert set(registry.scope_axes) == {"lang", "app"}
    assert registry.domains == {}


def test_load_registry_without_scopes_file(tmp_path: Path) -> None:
    registry = load_registry(write_schema(tmp_path))
    assert registry.scopes == [] and registry.scope_axes == {}
    empty = load_registry(
        write_schema(tmp_path / "other", **{"domains.yaml": "", "scopes.yaml": ""})
    )
    assert empty.domains == {} and empty.scopes == []


@pytest.mark.parametrize(
    "text",
    [
        "- db\n",  # not a mapping
        "Bad_Key: description\n",  # key is not a domain path
        "db: 5\n",  # description is not a string
        'db: ""\n',  # blank description
        'db/kv: "child without a parent line"\n',  # parent must be a separate line
        "db: [unclosed\n",  # not parseable
        "db: &anchor text\nlang: *anchor\n",  # YAML aliases
    ],
)
def test_domains_fail_closed(tmp_path: Path, text: str) -> None:
    root = write_schema(tmp_path, **{"domains.yaml": text})
    with pytest.raises(WikiError) as error:
        load_registry(root)
    assert error.value.code == "E_SCHEMA_INVALID"
    assert "schema/domains.yaml" in error.value.message


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("relations.yaml", "related: {inverse: related, weight: 5}\n"),
        ("relations.yaml", "- list\n"),
        ("relations.yaml", "related: [broken\n"),
        ("page-types/bad.yaml", "type: x\n"),
        ("page-types/bad.yaml", "type: [unclosed\n"),
        ("tags.yaml", "key: value\n"),
    ],
)
def test_other_schema_files_fail_closed(tmp_path: Path, name: str, text: str) -> None:
    root = write_schema(tmp_path)
    (root / "schema" / name).write_text(text)
    with pytest.raises(WikiError) as error:
        load_registry(root)
    assert error.value.code == "E_SCHEMA_INVALID"
    assert f"schema/{name}" in error.value.message


@pytest.mark.parametrize(
    "text",
    [
        "just text\n",
        "values: [1]\n",
        "axes: [a]\n",
        "axes: {lang: 5}\n",
        "axes: {lang: {enum: 5}}\n",
        "axes: {lang: {wat: 1}}\n",
    ],
)
def test_scopes_fail_closed(tmp_path: Path, text: str) -> None:
    root = write_schema(tmp_path, **{"scopes.yaml": text})
    if text == "axes: {lang: {wat: 1}}\n":
        assert load_registry(root).scope_axes["lang"].enum == []
        return
    with pytest.raises(WikiError) as error:
        load_registry(root)
    assert error.value.code == "E_SCHEMA_INVALID"


def test_relation_weight_range() -> None:
    assert Relation.model_validate({"inverse": "x"}).weight == 1.0
    for bad in (0, 1.5, -0.1):
        with pytest.raises(ValidationError):
            Relation.model_validate({"inverse": "x", "weight": bad})


# -- scopes ----------------------------------------------------------------------------------


def test_scope_matching_is_hierarchical_downwards(reg: Registry) -> None:
    assert reg.scope_matches("domain:db/kv", "domain:db")
    assert reg.scope_matches("domain:db", "domain:db")
    assert not reg.scope_matches("domain:db", "domain:db/kv")
    assert not reg.scope_matches("domain:dbx", "domain:db")
    assert not reg.scope_matches("lang:python/x", "lang:python")
    assert not reg.scope_matches("domain:db/kv", "lang:db")
    assert reg.scope_matches("lang:python", "*") and reg.scope_matches("*", "lang:rust")


def test_scope_known(reg: Registry) -> None:
    assert all(
        reg.scope_known(s)
        for s in ("*", "lang:python", "domain:db/kv", "layer:app", "tech:anything")
    )
    assert not any(
        reg.scope_known(s)
        for s in ("lang:go", "domain:nope", "layer:x", "nope:x", "tech", "layer:", "domain:")
    )


def test_overlaps_with_hierarchy(reg: Registry) -> None:
    assert overlaps(["domain:db"], ["domain:db/kv"], reg)
    assert overlaps(["domain:db/kv"], ["domain:db"], reg)
    assert not overlaps(["domain:db"], ["domain:lang"], reg)
    assert not overlaps(["domain:db"], ["domain:db/kv"])
    assert overlaps(["*"], ["lang:python"])


def test_page_scopes_validated(reg: Registry) -> None:
    ok = fact(reg, scopes=["domain:db/kv", "lang:python"])
    assert "E_SCOPE_UNKNOWN" not in codes(validate_page(ok, reg))
    bad = fact(reg, scopes=["domain:nope"])
    assert "E_SCOPE_UNKNOWN" in codes(validate_page(bad, reg))


# -- page_path / domain ------------------------------------------------------------------------


def test_page_path_with_domain(reg: Registry) -> None:
    assert page_path(reg, "fact", "f-wal", domain="db/kv") == "wiki/kb/db/kv/facts/f-wal.md"
    assert page_path(reg, "term", "term-x") == "wiki/glossary/x.md"
    assert page_path(reg, "term", "term-x", domain="not-checked") == "wiki/glossary/x.md"


@pytest.mark.parametrize(
    "domain", ["nope", "../db", "db/../db", "db\\kv", "db\0", "DB", "", "/db", "db/", "db//kv"]
)
def test_page_path_rejects_bad_domain(reg: Registry, domain: str) -> None:
    with pytest.raises(WikiError) as error:
        page_path(reg, "fact", "f-wal", domain=domain)
    assert error.value.code == "E_DOMAIN_UNKNOWN" and error.value.status == 422


def test_page_path_requires_domain(reg: Registry) -> None:
    with pytest.raises(WikiError) as error:
        page_path(reg, "fact", "f-wal")
    assert error.value.code == "E_REQUIRED_FIELD"
    with pytest.raises(WikiError):
        check_domain(reg, None)


def test_page_path_unsafe_template(reg: Registry) -> None:
    reg.page_types["term"].path_template = "a/../{slug}.md"
    with pytest.raises(WikiError) as error:
        page_path(reg, "term", "term-x")
    assert error.value.code == "E_PATH_MISMATCH"
    reg.page_types["term"].path_template = "a/{slug}\0.md"
    with pytest.raises(WikiError):
        page_path(reg, "term", "term-x")


def test_validate_domain_codes(reg: Registry) -> None:
    unknown = fact(reg, domain="db")
    unknown.frontmatter.domain = "nope"
    assert codes(validate_page(unknown, reg)) == {"E_DOMAIN_UNKNOWN"}
    missing = fact(reg)
    missing.frontmatter.domain = None
    assert codes(validate_page(missing, reg)) == {"E_REQUIRED_FIELD"}
    wrong_path = fact(reg)
    wrong_path.path = "wiki/kb/lang/facts/f-wal.md"
    assert codes(validate_page(wrong_path, reg)) == {"E_PATH_MISMATCH"}
    # An old-style type may carry a domain, which must still be a known one.
    term = make(reg, "term-x", "term")
    term.frontmatter.domain = "nope"
    assert codes(validate_page(term, reg)) == {"E_DOMAIN_UNKNOWN"}
    term.frontmatter.domain = "lang/rust"
    assert validate_page(term, reg) == []


# -- RelationRef / Edge ------------------------------------------------------------------------


def test_relation_ref_bounds_and_serialization() -> None:
    assert RelationRef(id="f-a").origin == "manual"
    assert RelationRef(id="f-a", w=1).w == 1
    for bad in (0, -1, 1.01):
        with pytest.raises(ValidationError):
            RelationRef(id="f-a", w=bad)
    with pytest.raises(ValidationError):
        RelationRef(id="f-a", note="two\nlines")
    with pytest.raises(ValidationError):
        RelationRef(id="f-a", origin="guess")  # type: ignore[arg-type]
    assert RelationRef(id="f-a", w=0.5).model_dump() == {"id": "f-a", "w": 0.5, "origin": "manual"}


def test_frontmatter_roundtrip_keeps_old_pages_unchanged(reg: Registry) -> None:
    term = make(reg, "term-x", "term")
    dumped = term.frontmatter.model_dump(mode="json")
    assert "domain" not in dumped and "scopes" not in dumped
    assert render(dumped, term.body_md) == render({k: v for k, v in dumped.items()}, term.body_md)
    with_domain = fact(reg, scopes=["lang:python"]).frontmatter.model_dump(mode="json")
    assert with_domain["domain"] == "db" and with_domain["scopes"] == ["lang:python"]


def test_mixed_relations_and_edges(reg: Registry) -> None:
    page = fact(
        reg,
        relations={
            "about": ["top-wal"],
            "supports": [{"id": "f-other", "w": 0.4, "note": "when sync", "origin": "extracted"}],
        },
    )
    assert isinstance(page.frontmatter, Frontmatter)
    found = {(e.rel, e.dst, e.weight, e.note, e.origin) for e in edges(page)}
    assert ("about", "top-wal", None, None, "manual") in found
    assert ("supports", "f-other", 0.4, "when sync", "extracted") in found


def test_covers_edges(reg: Registry) -> None:
    source = make(reg, "src-book", "source", covers=["top-wal", "top-lsm"])
    found = {(e.rel, e.dst, e.kind) for e in edges(source)}
    assert {("covers", "top-wal", "frontmatter"), ("covers", "top-lsm", "frontmatter")} <= found
    source.frontmatter.__pydantic_extra__ = {"covers": "top-wal"}
    assert not [e for e in edges(source) if e.rel == "covers"]


def test_bad_weight_is_a_frontmatter_error(reg: Registry) -> None:
    with pytest.raises(WikiError) as error:
        fact(reg, relations={"about": [{"id": "top-wal", "w": 3}]})
    assert error.value.code == "E_FRONTMATTER_INVALID"


def test_agent_edge_not_above_base_weight(reg: Registry) -> None:
    over = fact(reg, relations={"supports": [{"id": "f-b", "w": 0.9, "origin": "inferred"}]})
    assert "E_FRONTMATTER_INVALID" in codes(validate_page(over, reg))
    fine = fact(reg, relations={"supports": [{"id": "f-b", "w": 0.7, "origin": "extracted"}]})
    assert "E_FRONTMATTER_INVALID" not in codes(validate_page(fine, reg))
    manual = fact(reg, relations={"supports": [{"id": "f-b", "w": 1.0}]})
    assert "E_FRONTMATTER_INVALID" not in codes(validate_page(manual, reg))
    unknown = fact(reg, relations={"nope": [{"id": "f-b", "w": 1.0, "origin": "inferred"}]})
    assert codes(validate_page(unknown, reg)) == {"E_REL_UNKNOWN", "W_FACT_NO_HUB"}


# -- fact checks ---------------------------------------------------------------------------------


@pytest.mark.parametrize("claim", ["too short", "x" * 201, "two\nlines of a long enough claim", 5])
def test_claim_bounds(reg: Registry, claim: Any) -> None:
    result = codes(validate_page(fact(reg, claim=claim), reg))
    assert result == {"E_CLAIM_MISSING"}


def test_claim_missing_reported_once(reg: Registry) -> None:
    page = fact(reg)
    del page.frontmatter.__pydantic_extra__["claim"]  # type: ignore[index]
    issues = validate_page(page, reg)
    assert [i.code for i in issues] == ["E_CLAIM_MISSING"]
    assert issues[0].severity == "error"


def test_claim_boundaries(reg: Registry) -> None:
    assert validate_page(fact(reg, claim="a" * 20), reg) == []
    assert validate_page(fact(reg, claim="a" * 200), reg) == []


@pytest.mark.parametrize("kind", ["number", "api", "pitfall"])
def test_valid_for_required_for_some_kinds(reg: Registry, kind: str) -> None:
    assert codes(validate_page(fact(reg, kind=kind), reg)) == {"E_VALID_FOR_MISSING"}
    assert validate_page(fact(reg, kind=kind, valid_for="rust>=1.75"), reg) == []
    assert validate_page(fact(reg, kind="definition"), reg) == []


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("rust>=1.75", True),
        ("kernel:io_uring", True),
        ("rust >= 1.75, linux", True),
        ("a==1,b!=2,c<3,d>4,e<=5", True),
        ("", False),
        ("x" * 65, False),
        ("rust>=", False),
        (">=1.75", False),
        ("a,,b", False),
        ("rust;1", False),
        ("a >=< b", False),
        (5, False),
    ],
)
def test_valid_for_grammar(value: Any, ok: bool) -> None:
    assert valid_for_ok(value) is ok


def test_valid_for_invalid_value_is_error(reg: Registry) -> None:
    assert codes(validate_page(fact(reg, valid_for="rust;rm -rf"), reg)) == {
        "E_FRONTMATTER_INVALID"
    }


def test_fact_warnings(reg: Registry) -> None:
    long_body = "## Claim\n\n" + "word " * 400
    page = fact(reg, body=long_body)
    assert codes(validate_page(page, reg)) == {"W_FACT_LONG"}
    no_hub = fact(reg, relations={})
    issues = validate_page(no_hub, reg)
    assert codes(issues) == {"W_FACT_NO_HUB"} and issues[0].severity == "warning"
    hub_only_via_rel = fact(reg, relations={"supports": ["f-b"]})
    assert codes(validate_page(hub_only_via_rel, reg)) == {"W_FACT_NO_HUB"}


def test_defaults_and_dict_date_types(reg: Registry) -> None:
    page = fact(reg, novelty={"gpt": "common"}, valid_from=date(2026, 1, 2))
    assert validate_page(page, reg) == []
    assert "E_FRONTMATTER_INVALID" in codes(validate_page(fact(reg, novelty={"gpt": "wat"}), reg))
    assert "E_FRONTMATTER_INVALID" in codes(validate_page(fact(reg, novelty=["x"]), reg))
    assert "E_FRONTMATTER_INVALID" in codes(validate_page(fact(reg, valid_from="2026-13-40"), reg))
    assert "E_FRONTMATTER_INVALID" in codes(validate_page(fact(reg, confidence="wat"), reg))
    # A required field with a default is satisfied by the default.
    reg.page_types["fact"].extra_fields["confidence"].required = True
    assert validate_page(fact(reg), reg) == []


def test_valid_extra_types() -> None:
    date_field = ExtraField(type="date")
    assert valid_extra(date(2026, 1, 1), date_field)
    assert valid_extra("2026-01-31", date_field)
    assert not valid_extra("2026-02-30", date_field)
    assert not valid_extra("2026-1-1", date_field)
    assert not valid_extra(5, date_field)
    assert not valid_extra(datetime(2026, 1, 1, 10, tzinfo=UTC), date_field)
    dict_field = ExtraField(type="dict", item_enum=["a", "b"], item_pattern="[a-z]", min_items=1)
    assert valid_extra({"k": "a"}, dict_field)
    assert not valid_extra({}, dict_field)
    assert not valid_extra({"k": "c"}, dict_field)
    assert not valid_extra({"k": "A"}, ExtraField(type="dict", item_pattern="[a-z]"))
    assert not valid_extra({1: "a"}, dict_field)
    assert not valid_extra({"k": 1}, dict_field)
    assert not valid_extra({"a": "a", "b": "b"}, ExtraField(type="dict", max_items=1))
    assert not valid_extra("x", dict_field)
    # None takes the default; no default - not valid.
    assert valid_extra(None, ExtraField(type="dict", default={}))
    assert not valid_extra(None, ExtraField(type="dict"))
    assert not valid_extra(None, ExtraField(type="str", default=5))


# -- topic / tech / source ------------------------------------------------------------------------


def topic(reg: Registry, digest_size: int = 10, **changes: Any) -> Page:
    body = f"## Digest\n\n{'d' * digest_size}\n\n## Facts\n\n1. [[f-wal]]\n"
    return make(reg, "top-wal", "topic", body=body, **{"domain": "db", **changes})


def test_digest_length(reg: Registry) -> None:
    assert validate_page(topic(reg), reg) == []
    assert validate_page(topic(reg, 800), reg) == []
    assert codes(validate_page(topic(reg, 801), reg)) == {"W_DIGEST_LONG"}
    # Text after the Digest heading, not the following sections, is measured.
    big_facts = "## Digest\n\nshort\n\n## Facts\n\n" + "x" * 2000
    page = make(reg, "top-wal", "topic", body=big_facts, domain="db")
    assert validate_page(page, reg) == []


def tech(reg: Registry, **changes: Any) -> Page:
    data: dict[str, Any] = {
        "domain": "db",
        "category": "database",
        "adoption": "adopted",
        "verdict": "Our default storage engine.",
    }
    data.update(changes)
    return make(reg, "tech-rocksdb", "tech", **data)


@pytest.mark.parametrize("adoption", ["evaluating", "adopted", "avoid", "legacy", "unknown"])
def test_tech_adoption_enum(reg: Registry, adoption: str) -> None:
    assert validate_page(tech(reg, adoption=adoption), reg) == []


def test_tech_adoption_invalid(reg: Registry) -> None:
    assert codes(validate_page(tech(reg, adoption="trial"), reg)) == {"E_FRONTMATTER_INVALID"}


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://rocksdb.org", True),
        ("http://example.com/a?b=c#d", True),
        ("ftp://example.com", False),
        ("javascript:alert(1)", False),
        ("https://user@example.com", False),
        ("https://user:pw@example.com", False),
        ("https://", False),
        ("https://exa mple.com", False),
        ("https://example.com/\n", False),
        ("https://example.com/" + "a" * 2048, False),
        ("https://[::1", False),
        ("", False),
        (5, False),
    ],
)
def test_http_url(url: Any, ok: bool) -> None:
    assert http_url_ok(url) is ok


def test_homepage_and_source_url(reg: Registry) -> None:
    assert validate_page(tech(reg, homepage="https://rocksdb.org"), reg) == []
    assert codes(validate_page(tech(reg, homepage="ftp://x.org"), reg)) == {"E_FRONTMATTER_INVALID"}
    assert validate_page(make(reg, "src-a", "source", url="https://a.org"), reg) == []
    assert codes(validate_page(make(reg, "src-a", "source", url="file:///etc"), reg)) == {
        "E_FRONTMATTER_INVALID"
    }


def test_validate_page_computes_edges_once(reg: Registry, monkeypatch: pytest.MonkeyPatch) -> None:
    import wikisvc.domain.validate as module

    calls = 0
    original = module.edges

    def counting(page: Page) -> Any:
        nonlocal calls
        calls += 1
        return original(page)

    monkeypatch.setattr(module, "edges", counting)
    validate_page(fact(reg), reg)
    assert calls == 1
    ValidationCache().local(fact(reg), reg)
    assert calls == 2


# -- validate_set ---------------------------------------------------------------------------------


def test_sensitivity_ref(reg: Registry) -> None:
    hub = topic(reg, sensitivity="restricted")
    low = fact(reg, sensitivity="internal")
    result = validate_set([hub, low], reg)
    assert [(i.code, i.page) for i in result if i.severity == "error"] == [
        ("E_SENSITIVITY_REF", "f-wal")
    ]
    assert "top-wal" not in " ".join(i.message for i in result)
    # Equal or higher sensitivity of the referring page is fine.
    high = fact(reg, sensitivity="restricted")
    assert not [i for i in validate_set([hub, high], reg) if i.severity == "error"]
    public_hub = topic(reg, sensitivity="public")
    public_fact = fact(reg, sensitivity="public")
    assert not [i for i in validate_set([public_hub, public_fact], reg) if i.severity == "error"]
    # A public hub that lists an internal fact leaks its existence: also an error.
    assert "E_SENSITIVITY_REF" in codes(validate_set([public_hub, low], reg))


def test_sensitivity_ref_via_wikilink_and_citation(reg: Registry) -> None:
    secret = fact(reg, "f-secret", sensitivity="restricted", relations={"about": ["top-wal"]})
    link = fact(
        reg,
        "f-open",
        sensitivity="internal",
        body="## Claim\n\nSee [[f-secret]].\n",
        relations={"about": ["top-wal"]},
    )
    hub = topic(reg, sensitivity="restricted")
    assert "E_SENSITIVITY_REF" in codes(validate_set([hub, secret, link], reg))


def test_old_pages_are_not_sensitivity_checked(reg: Registry) -> None:
    low = make(reg, "term-a", "term", relations={"related": ["term-b"]})
    high = make(reg, "term-b", "term", sensitivity="restricted")
    assert "E_SENSITIVITY_REF" not in codes(validate_set([low, high], reg))


def test_hub_size_warnings(reg: Registry) -> None:
    hub = topic(reg)
    empty = validate_set([hub], reg)
    assert [i.code for i in empty if i.code.startswith("W_HUB")] == ["W_HUB_EMPTY"]
    facts = [fact(reg, f"f-n{i}") for i in range(60)]
    assert not [i for i in validate_set([hub, *facts], reg) if i.code.startswith("W_HUB")]
    many = [*facts, fact(reg, "f-n60")]
    assert "W_HUB_TOO_LARGE" in codes(validate_set([hub, *many], reg))
    # `about` of a non-fact (a question) does not count as a hub fact.
    other = fact(reg, "f-elsewhere", relations={"about": ["tech-rocksdb"]})
    assert "W_HUB_EMPTY" in codes(validate_set([hub, other, tech(reg)], reg))


def test_new_relation_type_pairs(reg: Registry) -> None:
    hub = topic(reg)
    wrong = fact(reg, relations={"about": ["f-b"]})
    other = fact(reg, "f-b")
    assert "E_REL_TYPE_MISMATCH" in codes(validate_set([hub, wrong, other], reg))
    unresolved = fact(reg, relations={"about": ["top-missing"]})
    assert "E_LINK_UNRESOLVED" in codes(validate_set([unresolved], reg))


def test_covers_resolved_and_typed(reg: Registry) -> None:
    reg.relations["covers"] = Relation.model_validate(
        {"inverse": "covered_by", "from": ["source"], "to": ["topic"], "weight": 0.3}
    )
    source = make(reg, "src-book", "source", covers=["top-wal"])
    assert "E_LINK_UNRESOLVED" in codes(validate_set([source], reg))
    ok = validate_set([source, topic(reg), fact(reg)], reg)
    assert not [i for i in ok if i.severity == "error"]
    wrong = make(reg, "src-book", "source", covers=["f-wal"])
    assert "E_REL_TYPE_MISMATCH" in codes(validate_set([wrong, fact(reg)], reg))


def test_tech_scope_resolved_against_pages(reg: Registry) -> None:
    page = fact(reg, scopes=["tech:rocksdb"])
    assert "E_SCOPE_UNKNOWN" in codes(validate_set([page], reg))
    assert "E_SCOPE_UNKNOWN" not in codes(validate_set([page, tech(reg)], reg))
    not_tech = tech(reg)
    not_tech.frontmatter.type = "term"
    assert "E_SCOPE_UNKNOWN" in codes(validate_set([page, not_tech], reg))


def test_set_with_cache_matches_without(reg: Registry) -> None:
    pages = [topic(reg), fact(reg), fact(reg, "f-b", relations={"about": ["top-wal"]})]
    cache = ValidationCache()
    assert validate_set(pages, reg, cache) == validate_set(pages, reg)
    assert validate_set(pages, reg, cache) == validate_set(pages, reg)


# -- rules: applies_to stays an alias of scopes ---------------------------------------------------


def rule(reg: Registry, page_id: str, **changes: Any) -> Page:
    data: dict[str, Any] = {
        "lifecycle": "active",
        "level": "should",
        "verified_by": "alice",
        "aliases": ["правило", "rule"],
    }
    data.update(changes)
    return make(reg, page_id, "rule", **data)


def test_rule_applies_to_alias(reg: Registry) -> None:
    assert "E_SCOPE_UNKNOWN" not in codes(
        validate_page(rule(reg, "rule-a", applies_to=["domain:db/kv", "lang:python"]), reg)
    )
    assert "E_SCOPE_UNKNOWN" in codes(validate_page(rule(reg, "rule-a", applies_to=["x:y"]), reg))
    # The common field works for a rule that has no applies_to.
    assert "E_SCOPE_UNKNOWN" in codes(validate_page(rule(reg, "rule-a", scopes=["x:y"]), reg))
    assert "E_SCOPE_UNKNOWN" not in codes(
        validate_page(rule(reg, "rule-a", scopes=["domain:db"]), reg)
    )


def test_rule_conflict_uses_hierarchy(reg: Registry) -> None:
    left = rule(reg, "rule-a", applies_to=["domain:db"], relations={"conflicts_with": ["rule-b"]})
    right = rule(reg, "rule-b", applies_to=["domain:db/kv"])
    assert "W_RULE_CONFLICT" in codes(validate_set([left, right], reg))
    far = rule(reg, "rule-b", applies_to=["domain:lang"])
    assert "W_RULE_CONFLICT" not in codes(validate_set([left, far], reg))


def test_rule_tech_scope_checked_in_set(reg: Registry) -> None:
    page = rule(reg, "rule-a", applies_to=["tech:rocksdb"])
    assert "E_SCOPE_UNKNOWN" in codes(validate_set([page], reg))
    assert "E_SCOPE_UNKNOWN" not in codes(validate_set([page, tech(reg)], reg))


def test_rule_grounded_in_fact_pair_and_sensitivity(reg: Registry) -> None:
    grounded = rule(reg, "rule-a", relations={"grounded_in": ["f-wal"]})
    restricted = fact(reg, sensitivity="restricted")
    result = codes(validate_set([grounded, restricted, topic(reg, sensitivity="restricted")], reg))
    assert "E_SENSITIVITY_REF" in result


def test_relation_ref_is_closed() -> None:
    with pytest.raises(ValidationError):
        RelationRef.model_validate({"id": "top-a", "weight": 0.5})
    with pytest.raises(WikiError) as error:
        make(
            build_registry(),
            "f-x",
            "fact",
            domain="db",
            relations={"about": [{"id": "a", "weight": 1}]},
        )
    assert error.value.code == "E_FRONTMATTER_INVALID"


def test_claim_rejects_carriage_return(reg: Registry) -> None:
    assert codes(validate_page(fact(reg, claim="a" * 25 + "\r" + "b" * 5), reg)) == {
        "E_CLAIM_MISSING"
    }


def test_exactly_one_error_per_dedicated_field(reg: Registry) -> None:
    def invalid(page: Page) -> list[str]:
        return [i.code for i in validate_page(page, reg) if i.code == "E_FRONTMATTER_INVALID"]

    # YAML-style constraints on the same fields must not double the report.
    reg.page_types["tech"].extra_fields["adoption"].enum = ["adopted"]
    reg.page_types["tech"].extra_fields["homepage"].pattern = "https://.*"
    reg.page_types["source"].extra_fields["url"].pattern = "https://.*"
    assert invalid(tech(reg, adoption="trial")) == ["E_FRONTMATTER_INVALID"]
    assert invalid(tech(reg, homepage="http://x.org")) == []
    assert invalid(tech(reg, homepage="ftp://x.org")) == ["E_FRONTMATTER_INVALID"]
    assert invalid(make(reg, "src-a", "source", url="ftp://a.org")) == ["E_FRONTMATTER_INVALID"]
    # Required stays generic.
    page = tech(reg)
    del page.frontmatter.__pydantic_extra__["adoption"]  # type: ignore[index]
    assert codes(validate_page(page, reg)) == {"E_REQUIRED_FIELD"}


def test_question_answered_by_facts(reg: Registry) -> None:
    reg.page_types["question"] = PageType(
        type="question",
        prefix="q",
        path_template="kb/{domain}/questions/q-{slug}.md",
        title_ru="Вопрос",
        sources_required=False,
        allowed_relations=["answered_by"],
    )
    reg.relations["answered_by"] = Relation.model_validate({"inverse": "answers"})
    good = make(reg, "q-a", "question", domain="db", relations={"answered_by": ["f-wal"]})
    assert validate_page(good, reg) == []
    bad = make(reg, "q-a", "question", domain="db", relations={"answered_by": ["top-wal"]})
    assert codes(validate_page(bad, reg)) == {"E_REL_TYPE_MISMATCH"}
