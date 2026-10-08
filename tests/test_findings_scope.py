from fastapi.testclient import TestClient
from test_proposals import reviewer

from wikisvc.config import Settings
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB


def finding_payload() -> dict[str, object]:
    return {
        "kind": "docs-audit",
        "pages": ["rule-stack-example-1"],
        "summary": "Нарушение правила проекта",
        "evidence": [{"page": "rule-stack-example-1", "quote": "Описание счетов"}],
    }


def test_legacy_fingerprint_and_migration(client: TestClient, config: Settings) -> None:
    data = {**finding_payload(), "kind": "duplicate"}
    response = client.post("/api/v1/findings", json=data)
    assert response.status_code == 200, response.text
    finding = response.json()
    # Captured from the pre-scope implementation using this fixed corpus.
    assert finding["fingerprint"] == (
        "f0aa1a9a60b7a4e23133f7b380d8d59399c507a14efdf1672e7a9d0092965e6d"
    )
    assert finding["scope"] == ""
    assert client.post("/api/v1/findings", json={**data, "scope": ""}).json() == finding
    reviewer(client, config)
    dismissed = client.post(
        f"/api/v1/findings/{finding['id']}/dismiss", json={"reason": "Согласованное исключение"}
    )
    assert dismissed.status_code == 200, dismissed.text

    # Recreate a database written before scope existed, keeping the legacy row.
    state = client.app.state.runtime.state
    with state.connect() as db:
        db.execute("ALTER TABLE findings DROP COLUMN scope")
    legacy = state.rows("SELECT * FROM findings")[0]
    assert "scope" not in legacy
    for _ in range(2):
        migrated = StateDB(config.state_dir)
        assert migrated.rows("SELECT * FROM findings") == [{**legacy, "scope": ""}]
    for values in (data, {**data, "scope": ""}):
        repeated = client.post("/api/v1/findings", json=values)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == dismissed.json()
    assert len(state.rows("SELECT * FROM findings")) == 1


def test_projects_deduplicate_independently_and_share_kind_stats(
    client: TestClient, config: Settings
) -> None:
    orders_data = {
        **finding_payload(),
        "scope": "orders-platform",
        "summary": "Нарушение в заказах",
        "explanation": "orders-platform docs/stack/orders.md:2",
    }
    billing_data = {
        **finding_payload(),
        "scope": "billing",
        "summary": "Нарушение в оплате",
        "explanation": "billing docs/stack/billing.md:8",
        "evidence": [{"page": "rule-stack-example-1", "quote": "счетов"}],
    }
    orders_response = client.post("/api/v1/findings", json=orders_data)
    billing_response = client.post("/api/v1/findings", json=billing_data)
    assert orders_response.status_code == 200, orders_response.text
    assert billing_response.status_code == 200, billing_response.text
    orders, billing = orders_response.json(), billing_response.json()
    assert orders["id"] != billing["id"] and orders["fingerprint"] != billing["fingerprint"]
    for row, data in ((orders, orders_data), (billing, billing_data)):
        for field in ("kind", "scope", "summary", "explanation", "evidence"):
            assert row[field] == data[field]
        assert row["status"] == "open"
        assert client.post("/api/v1/findings", json=data).json() == row

    reviewer(client, config)
    dismissed = client.post(
        f"/api/v1/findings/{orders['id']}/dismiss", json={"reason": "Исключение для заказов"}
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    assert client.post("/api/v1/findings", json=orders_data).json() == dismissed.json()
    assert client.post("/api/v1/findings", json=billing_data).json() == billing
    assert client.get("/api/v1/findings", params={"scope": "billing"}).json()["items"] == [billing]
    assert client.get(
        "/api/v1/findings", params={"scope": "orders-platform", "status": "dismissed"}
    ).json()["items"] == [dismissed.json()]
    assert client.get("/api/v1/findings/stats").json()["kinds"] == {
        "docs-audit": {
            "open": 1,
            "dismissed": 1,
            "resolved": 0,
            "recommendation": "Поднять порог уверенности",
        }
    }
    assert len(client.app.state.runtime.state.rows("SELECT * FROM findings")) == 2

    legacy = client.post("/api/v1/findings", json=finding_payload()).json()
    assert legacy["scope"] == "" and legacy["id"] not in (orders["id"], billing["id"])
    assert client.get("/api/v1/findings", params={"scope": ""}).json()["items"] == [legacy]
    assert len(client.get("/api/v1/findings").json()["items"]) == 3
    for params in (
        {"scope": "unknown"},
        {"scope": "billing", "status": "dismissed"},
        {"scope": "billing", "kind": "duplicate"},
        {"scope": "billing", "severity": "critical"},
    ):
        assert client.get("/api/v1/findings", params=params).json()["items"] == []
    assert client.get(
        "/api/v1/findings",
        params={"scope": "billing", "status": "open", "kind": "docs-audit", "severity": "warning"},
    ).json()["items"] == [billing]


def test_scope_validation(client: TestClient) -> None:
    for invalid in ("Orders", "two words", "app.billing", "a" * 65, "-orders", "app_x", None):
        response = client.post("/api/v1/findings", json={**finding_payload(), "scope": invalid})
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "E_REQUEST_INVALID"
        assert response.json()["error"]["details"][0]["field"] == "body.scope"
    combined = client.post(
        "/api/v1/findings", json={**finding_payload(), "scope": "Orders", "kind": "docs:audit"}
    )
    assert combined.status_code == 400, combined.text
    assert combined.json()["error"]["code"] == "E_REQUEST_INVALID"
    assert {detail["field"] for detail in combined.json()["error"]["details"]} == {
        "body.scope",
        "body.kind",
    }
    assert (
        client.post(
            "/api/v1/findings", json={**finding_payload(), "scope": "orders", "project": "orders"}
        ).status_code
        == 400
    )
    assert not client.app.state.runtime.state.rows("SELECT * FROM findings")
    for valid in ("", "0", "orders-platform", "a" * 64):
        response = client.post("/api/v1/findings", json={**finding_payload(), "scope": valid})
        assert response.status_code == 200, response.text
        assert response.json()["scope"] == valid


def test_scope_rule_version_and_pagination(client: TestClient, config: Settings) -> None:
    data = {**finding_payload(), "scope": "orders"}
    response = client.post("/api/v1/findings", json=data)
    assert response.status_code == 200, response.text
    old = response.json()
    reviewer(client, config)
    assert (
        client.post(
            f"/api/v1/findings/{old['id']}/dismiss", json={"reason": "Исключение старой версии"}
        ).status_code
        == 200
    )
    path = next(
        page.path
        for page in client.app.state.runtime.indexer.pages()
        if page.id == "rule-stack-example-1"
    )
    fs = SafeFS(config.wiki_root)
    fs.write(path, fs.read(path) + "\nУточнение правила.\n")
    GitRepo(config.wiki_root).commit("Change scoped policy", "fixtures")
    client.app.state.runtime.reindex()
    response = client.post("/api/v1/findings", json=data)
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["id"] != old["id"] and current["fingerprint"] != old["fingerprint"]
    assert current["scope"] == "orders" and current["status"] == "open"
    assert client.post("/api/v1/findings", json={**data, "scope": "billing"}).status_code == 200
    first = client.get("/api/v1/findings", params={"scope": "orders", "limit": 1}).json()
    assert first["items"][0]["id"] == old["id"] and first["next_cursor"]
    second = client.get(
        "/api/v1/findings", params={"scope": "orders", "limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert second == {"items": [current], "next_cursor": None}
