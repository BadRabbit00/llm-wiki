import json
from pathlib import Path

from conftest import make_page
from fastapi.testclient import TestClient

from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Principal
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def test_graph_golden(client: TestClient) -> None:
    rt = client.app.state.runtime
    actor = Principal(name="test", role="reader", clearance="internal")
    actual = {
        "neighbors": rt.graph.neighbors("app-example-1", actor, depth=3),
        "out": rt.graph.neighbors(
            "app-example-1", actor, depth=2, rels=["governed_by"], direction="out"
        ),
        "path": rt.graph.path("app-example-1", "sys-example-1", actor),
        "export": rt.graph.export(actor),
    }
    golden = json.loads((Path(__file__).parent / "fixtures/graph-golden.json").read_text())
    for key in actual:
        for field in ("nodes", "edges"):
            assert sorted(actual[key][field], key=str) == sorted(golden[key][field], key=str), (
                key,
                field,
            )


def test_retrieval_lifecycle_and_impact(client: TestClient, config: Settings) -> None:
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    defaults = {
        "category": "logging",
        "level": "should",
        "lifecycle": "active",
        "applies_to": ["lang:python"],
        "origin": "team",
        "status": "verified",
        "verified_by": "human",
        "verified_at": "2026-10-02",
        "aliases": ["журнал приложения", "application log"],
    }
    for page_id, summary, changes in [
        ("rule-logging", "Пиши структурированные логи в Python для каждой операции.", {}),
        (
            "rule-http-requests-sync",
            "Используй requests для синхронных HTTP запросов Python.",
            {"category": "stack"},
        ),
        (
            "rule-neighbor",
            "Задавай таймауты при выполнении сетевых запросов.",
            {"relations": {"refines": ["rule-http-requests-sync"]}},
        ),
        (
            "rule-deprecated",
            "Пиши логи Python старым способом для приложения.",
            {"lifecycle": "deprecated", "deprecated_reason": "Replaced"},
        ),
    ]:
        page = make_page(rt.registry, page_id, "rule", summary=summary, **(defaults | changes))
        fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md))
    pattern = make_page(
        rt.registry,
        "pat-fastapi-sync-endpoint",
        "pattern",
        relations={"governed_by": ["rule-http-requests-sync"]},
    )
    fs.write(pattern.path, render(pattern.frontmatter.model_dump(mode="json"), pattern.body_md))
    GitRepo(config.wiki_root).commit("Retrieval fixture", "fixtures")
    rt.reindex()
    for query in ["как писать логи в python", "что логировать", "logging python"]:
        hits = client.get("/api/v1/search", params={"q": query}).json()["results"]
        assert "rule-logging" in {h["id"] for h in hits}
        assert "rule-deprecated" not in {h["id"] for h in hits}
    result = client.get("/api/v1/rules/related", params={"q": "только async код"}).json()
    hit = next(h for h in result["rules"] if h["id"] == "rule-http-requests-sync")
    assert "rule-neighbor" in {h["id"] for h in hit["related"]}
    assert "pat-fastapi-sync-endpoint" in {h["id"] for h in result["pages"]}
    rule = client.get("/api/v1/rules/rule-http-requests-sync").json()
    assert rule["related"] and rule["related_tokens"] <= 600
    all_pages = client.get(
        "/api/v1/pages", params={"type": "rule", "lifecycle": "candidate,active,deprecated"}
    ).json()["items"]
    assert "rule-deprecated" in {p["id"] for p in all_pages}
    graph = client.get("/api/v1/graph/export", params={"include_scopes": True}).json()
    assert any(n["id"] == "scope:lang:python" for n in graph["nodes"])
    assert client.get("/api/v1/graph/impact/sys-restricted").status_code == 404
