from typing import Any

import pytest
from conftest import make_page
from fastapi.testclient import TestClient
from test_proposals import proposal

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import citations, edges, render
from wikisvc.domain.registry import ExtraField, Registry
from wikisvc.domain.validate import parse_page, valid_extra, validate_page, validate_set


def rule(registry: Registry, **changes: Any) -> Any:
    values = {
        "category": "logging",
        "level": "should",
        "lifecycle": "candidate",
        "applies_to": ["lang:python"],
        "origin": "team",
        "priority": 3,
    }
    values.update(changes)
    return make_page(registry, "rule-logging", "rule", **values)


@pytest.mark.parametrize(
    "field,value,valid",
    [
        (ExtraField(type="str", enum=["a"], max_length=1), "a", True),
        (ExtraField(type="str", max_length=2), "aaa", False),
        (ExtraField(type="int", min=1, max=5), 3, True),
        (ExtraField(type="int", min=1, max=5), 0, False),
        (ExtraField(type="int", min=1, max=5), 6, False),
        (ExtraField(type="int"), True, False),
        (ExtraField(type="list", min_items=1, max_items=2, item_enum=["a", "b"]), ["a"], True),
        (ExtraField(type="list", min_items=1), [], False),
        (ExtraField(type="list", max_items=1), ["a", "b"], False),
        (ExtraField(type="list", item_pattern="tool:.+"), ["tool:ruff"], True),
        (ExtraField(type="list", item_pattern="tool:.+"), ["bad"], False),
        (ExtraField(type="list"), [1], False),
    ],
)
def test_typed_extra_fields(field: ExtraField, value: Any, valid: bool) -> None:
    assert valid_extra(value, field) == valid


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"category": None}, "E_RULE_FIELDS"),
        ({"applies_to": ["lang:unknown"]}, "E_SCOPE_UNKNOWN"),
        ({"level": "must", "lifecycle": "active", "verified_by": "human"}, "E_MUST_NEEDS_OWNER"),
        ({"lifecycle": "active"}, "E_RULE_ACTIVE_NOT_VERIFIED"),
        ({"lifecycle": "deprecated"}, "E_RULE_FIELDS"),
        ({"status": "verified"}, "E_RULE_FIELDS"),
        ({"priority": 6}, "E_FRONTMATTER_INVALID"),
        ({"applies_to": []}, "E_FRONTMATTER_INVALID"),
        ({"origin": "book", "sources": ["src-book"]}, "W_NO_CITATION"),
        ({"aliases": []}, "W_FEW_ALIASES"),
        (
            {
                "level": "must",
                "lifecycle": "active",
                "verified_by": "human",
                "owner": "alice",
                "sources": ["src-decision"],
            },
            "W_MUST_WITHOUT_ENFORCER",
        ),
    ],
)
def test_rule_codes(registry: Registry, changes: dict[str, Any], code: str) -> None:
    assert code in {i.code for i in validate_page(rule(registry, **changes), registry)}


def test_rule_positive_and_length(registry: Registry) -> None:
    page = rule(registry, aliases=["логи", "logging"])
    assert not validate_page(page, registry)
    metadata = page.frontmatter.model_dump()
    metadata["summary"] = "x" * 161
    with pytest.raises(WikiError) as error:
        parse_page(render(metadata, page.body_md))
    assert error.value.code == "E_SUMMARY_TOO_LONG"
    for origin in ("team", "chat", "code"):
        assert "W_NO_SOURCES" not in {
            i.code for i in validate_page(rule(registry, origin=origin), registry)
        }


def test_rule_cross_checks_and_citations(registry: Registry) -> None:
    first = rule(
        registry,
        lifecycle="active",
        verified_by="human",
        relations={"conflicts_with": ["rule-other"]},
    )
    other = rule(registry, lifecycle="active", verified_by="human")
    other.frontmatter.id = "rule-other"
    other.path = "wiki/rules/other.md"
    assert "W_RULE_CONFLICT" in {i.code for i in validate_set([first, other], registry)}
    other.frontmatter.__pydantic_extra__["applies_to"] = ["lang:dotnet"]
    assert "W_RULE_CONFLICT" not in {i.code for i in validate_set([first, other], registry)}
    other.frontmatter.__pydantic_extra__.update(
        lifecycle="deprecated", deprecated_reason="Replaced"
    )
    first.frontmatter.relations = {"refines": [other.id]}
    assert "W_DEPENDS_ON_DEPRECATED" in {i.code for i in validate_set([first, other], registry)}
    first.body_md += '\n[@src-book стр. 12-14 "Проверенная короткая цитата"]'
    assert citations(first.body_md)[0].end == 14
    assert "src-book" in {edge.dst for edge in edges(first)}
    first.body_md += '\n[@src-book гл. 2 "' + "слово " * 31 + '"]'
    assert "E_QUOTE_TOO_LONG" in {i.code for i in validate_page(first, registry)}


def test_proposals_cannot_activate_rules(client: TestClient) -> None:
    rt = client.app.state.runtime
    page = rule(rt.registry)
    metadata = page.frontmatter.model_dump()
    metadata.update(
        lifecycle="active", level="must", owner="forged", priority=5, verified_by="forged"
    )
    pid = proposal(client)
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/{page.id}",
        json={"frontmatter": metadata, "body_md": page.body_md},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (saved["lifecycle"], saved["level"], saved["priority"], saved["verified_by"]) == (
        "candidate",
        "should",
        3,
        None,
    )
    assert "owner" not in saved
    for field in ("lifecycle", "level", "priority", "owner", "verified_by", "verified_at"):
        response = client.patch(
            f"/api/v1/proposals/{pid}/pages/{page.id}",
            json={"ops": [{"op": "set_field", "field": field, "value": "forged"}]},
        )
        assert response.json()["error"]["code"] == "E_FIELD_PROTECTED"


def test_legacy_migration_is_preview_or_proposal(client: TestClient) -> None:
    from wikisvc.domain.models import Principal
    from wikisvc.services.migrations import migrate_rules
    from wikisvc.storage.gitrepo import GitRepo
    from wikisvc.storage.safefs import SafeFS

    rt = client.app.state.runtime
    metadata = {
        "id": "conv-legacy",
        "type": "convention",
        "title": "Старое правило",
        "summary": "Сохраняй содержательное описание решения в коде.",
        "status": "verified",
        "created": "2026-01-01",
        "updated": "2026-01-01",
    }
    SafeFS(rt.settings.wiki_root).write(
        "wiki/engineering/conventions/legacy.md",
        render(metadata, "## Правило\n\nПиши подробные сообщения об ошибках.\n"),
    )
    repo = GitRepo(rt.settings.wiki_root)
    repo.commit("Legacy fixture", "fixture")
    rt.reindex()
    head = repo.head()
    actor = Principal(name="migrator", role="writer", clearance="restricted")
    preview = migrate_rules(rt, actor)
    assert preview["mapping"] == {"conv-legacy": "rule-conv-legacy"}
    assert repo.head() == head
    result = migrate_rules(rt, actor, False)
    assert result["validation"]["errors"] == []
    assert repo.head() == head
    page = rt.proposals.get(result["proposal"], actor)["pages"]
    candidate = next(p for p in page if p["type"] == "rule")
    assert (candidate["lifecycle"], candidate["level"], candidate["origin"]) == (
        "candidate",
        "idea",
        "team",
    )
