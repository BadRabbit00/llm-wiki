from fastapi.testclient import TestClient

from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.state_db import StateDB


def test_pages_schema_auth(client: TestClient, config: Settings) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    response = client.get("/api/v1/pages", params={"limit": 10}).json()
    assert len(response["items"]) == 10 and response["next_cursor"]
    second = client.get(
        "/api/v1/pages", params={"limit": 10, "cursor": response["next_cursor"]}
    ).json()
    assert second["items"][0]["id"] != response["items"][0]["id"]
    assert len(client.get("/api/v1/pages").json()["items"]) >= 30
    assert len(client.get("/api/v1/schema").json()["page_types"]) == 13
    assert "## Назначение" in client.get("/api/v1/schema/page-types/system").json()["template"]
    assert "недоверенные" in client.get("/api/v1/schema/instructions").json()["instructions"]
    assert client.post("/api/v1/schema/next-adr-number").json()["number"] == "0003"
    head = GitRepo(config.wiki_root).head()
    plain = client.get("/api/v1/pages/app-example-1").json()
    assert not {"neighbors", "backlinks", "history"} & set(plain)
    page = client.get(
        "/api/v1/pages/app-example-1", params={"include": "neighbors,backlinks,history"}
    ).json()
    assert page["body_md"] == plain["body_md"]
    # Backlinks are the incoming edges only: the fixture's `automates: proc-example-1`
    # arrives back as proc-example-1 -automated_by-> app-example-1, while the outgoing
    # citation of src-example-1 must not appear here.
    assert page["backlinks"] == [
        {"id": "ent-example-1", "rel": "read_by", "kind": "inverse"},
        {"id": "proc-example-1", "rel": "automated_by", "kind": "inverse"},
        {"id": "rule-stack-example-1", "rel": "governs", "kind": "inverse"},
        {"id": "sys-example-1", "rel": "integrates_with", "kind": "inverse"},
        {"id": "sys-example-1", "rel": "required_by", "kind": "inverse"},
    ]
    assert page["neighbors"] == client.get("/api/v1/graph/neighbors/app-example-1").json()
    assert {
        "src": "app-example-1",
        "dst": "src-example-1",
        "rel": "cites",
        "kind": "citation",
    } in page["neighbors"]["edges"]
    assert [(h["commit"], h["author"], h["message"]) for h in page["history"]] == [
        (head, "fixtures", "Add fixture corpus")
    ]
    assert client.get("/api/v1/pages/app-example-1", params={"format": "markdown"}).text.startswith(
        "---"
    )
    history = client.get("/api/v1/pages/app-example-1/history").json()
    assert history == {"items": page["history"], "next_cursor": None}
    at_head = client.get(f"/api/v1/pages/app-example-1/at/{head}")
    assert at_head.status_code == 200
    assert (at_head.json()["id"], at_head.json()["body_md"]) == ("app-example-1", plain["body_md"])
    for path in [
        "/pages/sys-restricted",
        "/pages/sys-restricted/history",
        f"/pages/sys-restricted/at/{head}",
        "/graph/neighbors/sys-restricted",
        "/context/sys-restricted",
    ]:
        assert client.get("/api/v1" + path).status_code == 404
    assert "sys-restricted" not in client.get("/api/v1/index").text
    auth = Auth(StateDB(config.state_dir))
    token = auth.create("reader", "reader", "public")
    client.headers["Authorization"] = "Bearer " + token
    assert client.post("/api/v1/schema/next-adr-number").status_code == 403
    assert not client.get("/api/v1/pages").json()["items"]
    auth.revoke("reader")
    assert client.get("/api/v1/pages").status_code == 401
    client.headers.pop("Authorization")
    assert client.get("/api/v1/pages").status_code == 401


def test_search_graph_context(client: TestClient) -> None:
    ru = client.get("/api/v1/search", params={"q": "выгрузки счетов", "k": 50}).json()["results"]
    assert ru and any(page["type"] == "system" for page in ru)
    en = client.get("/api/v1/search", params={"q": '"invoice exports"', "type": "system"}).json()[
        "results"
    ]
    assert en and all(page["type"] == "system" for page in en)
    assert (
        client.get("/api/v1/search", params={"q": "TOPSECRET_RESTRICTED"}).json()["results"] == []
    )
    expanded = client.get(
        "/api/v1/search", params={"q": "Биллинг", "expand": True, "k": 50}
    ).json()["results"]
    assert any(page["via"] == "graph" for page in expanded)
    for query in ["' OR 1=1;--", '" OR * : ; --', "x NEAR(a,b)", "", "*", "title:secret", 'a"b']:
        assert client.get("/api/v1/search", params={"q": query}).status_code == 200
    assert len(client.get("/api/v1/graph/export").json()["nodes"]) >= 30
    assert client.get(
        "/api/v1/graph/path", params={"from": "app-example-1", "to": "sys-example-1"}
    ).json()["nodes"] == ["app-example-1", "sys-example-1"]
    root = client.get("/api/v1/pages/app-example-1").json()
    context = client.get(
        "/api/v1/context/app-example-1", params={"budget_chars": len(root["body_md"]) + 550}
    ).json()
    assert context["pages"][0]["body_md"] == root["body_md"]
    assert context["truncated_ids"]
    assert context["delivered_chars"] <= len(root["body_md"]) + 550
    assert context["available_chars"] > context["delivered_chars"]
    assert "TOPSECRET_RESTRICTED" not in str(context)
    for page in context["pages"][1:]:
        original = client.get("/api/v1/pages/" + page["id"]).json()["body_md"]
        assert original.startswith(page["body_md"])
        if page["truncated"]:
            assert original[len(page["body_md"]) :].startswith("##")


def test_request_errors(client: TestClient) -> None:
    for path, code in [
        ("/search", "E_REQUEST_INVALID"),
        ("/search?q=a&k=90", "E_REQUEST_INVALID"),
        ("/search?q=a&mode=vector", "E_REQUEST_INVALID"),
        ("/context/app-example-1?depth=9", "E_REQUEST_INVALID"),
        ("/pages?cursor=bad", "E_CURSOR_INVALID"),
        ("/graph/neighbors/app-example-1?depth=20", "E_REQUEST_INVALID"),
        ("/pages/app-example-1?include=bad", "E_REQUEST_INVALID"),
    ]:
        response = client.get("/api/v1" + path)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == code, path
