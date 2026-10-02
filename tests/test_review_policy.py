from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_proposals import payload, proposal, reviewer
from test_rules_domain import rule

from wikisvc.config import Settings
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo


def candidate(client: TestClient) -> str:
    pid = proposal(client, "New policy rule")
    page = rule(client.app.state.runtime.registry, sources=["src-example-1"])
    response = client.put(
        f"/api/v1/proposals/{pid}/pages/{page.id}",
        json={"frontmatter": page.frontmatter.model_dump(mode="json"), "body_md": page.body_md},
    )
    assert response.status_code == 200, response.text
    return pid


def compile_version(client: TestClient) -> str:
    return str(
        client.get("/api/v1/policies/compile", params={"profile": "python-fastapi"}).json()[
            "version"
        ]
    )


def test_accept_promote_and_revert(client: TestClient, config: Settings) -> None:
    initial = compile_version(client)
    pid = candidate(client)
    assert (
        client.put(
            f"/api/v1/proposals/{pid}/notes", json={"summary": "Новое правило", "items": []}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/proposals/{pid}").json()["notes"]["summary"] == "Новое правило"
    reviewer(client, config)
    assert client.get(f"/api/v1/proposals/{pid}/impact").status_code == 200
    result = client.post(
        f"/api/v1/proposals/{pid}/accept",
        json={
            "promote": [
                {"id": "rule-logging", "level": "must", "owner": "person-owner", "priority": 1}
            ]
        },
    )
    assert result.status_code == 200, result.text
    assert compile_version(client) != initial
    page = client.get("/api/v1/rules/rule-logging").json()
    assert (
        page["lifecycle"] == "active"
        and page["status"] == "verified"
        and page["verified_by"] == "reviewer"
    )
    result = client.post(f"/api/v1/proposals/{pid}/revert")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "reverted" and compile_version(client) == initial
    GitRepo(config.wiki_root).ensure_main()


@pytest.mark.parametrize("failure", ["commit", "validation", "target", "owner"])
def test_accept_transaction_rollback(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    pid = candidate(client)
    reviewer(client, config)
    rt = client.app.state.runtime
    actor = rt.auth.authenticate(client.headers["Authorization"].split()[1])
    repo = GitRepo(config.wiki_root)
    head = repo.head()
    values: dict[str, Any] = {"id": "rule-logging", "level": "must", "owner": "person-owner"}
    if failure == "target":
        values["id"] = "rule-stack-example-1"
    if failure == "owner":
        values.pop("owner")
    if failure == "validation":
        values["applies_to"] = ["unknown:scope"]
    with monkeypatch.context() as patch:
        if failure == "commit":

            def fail(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("forced failure after merge")

            patch.setattr(GitRepo, "commit", fail)
            with pytest.raises(RuntimeError):
                rt.proposals.decide(pid, actor, "accepted", promote=[values])
        else:
            response = client.post(f"/api/v1/proposals/{pid}/accept", json={"promote": [values]})
            assert response.status_code == 422, response.text
    assert repo.head() == head
    repo.ensure_main()
    assert not repo.git_path("MERGE_HEAD").exists()
    assert client.get(f"/api/v1/proposals/{pid}").json()["status"] == "draft"
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/accept",
            json={"promote": [{"id": "rule-logging", "level": "should"}]},
        ).status_code
        == 200
    )


def test_active_edits_and_revert_overlap(client: TestClient, config: Settings) -> None:
    writer = client.headers["Authorization"]
    pid = candidate(client)
    reviewer(client, config)
    human = client.headers["Authorization"]
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/accept", json={"promote": [{"id": "rule-logging"}]}
        ).status_code
        == 200
    )
    version = compile_version(client)
    client.headers["Authorization"] = writer
    edit = proposal(client)
    page = client.get("/api/v1/pages/rule-logging").json()
    response = client.patch(
        f"/api/v1/proposals/{edit}/pages/rule-logging",
        json={
            "base_version": page["version"],
            "ops": [
                {
                    "op": "set_field",
                    "field": "summary",
                    "value": "Всегда записывай структурированный контекст операции.",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = human
    assert client.post(f"/api/v1/proposals/{edit}/accept").status_code == 200
    updated = client.get("/api/v1/pages/rule-logging").json()
    assert updated["status"] == "verified" and updated["verified_at"] != page["verified_at"]
    denied = client.post(f"/api/v1/proposals/{pid}/revert")
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "E_REVERT_CONFLICT"
    assert client.post(f"/api/v1/proposals/{edit}/revert").status_code == 200
    assert compile_version(client) == version


def test_revert_failure_and_unrelated_changes(
    client: TestClient, config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = client.headers["Authorization"]
    pid = candidate(client)
    reviewer(client, config)
    human = client.headers["Authorization"]
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/accept", json={"promote": [{"id": "rule-logging"}]}
        ).status_code
        == 200
    )
    client.headers["Authorization"] = writer
    unrelated = proposal(client)
    assert (
        client.put(f"/api/v1/proposals/{unrelated}/pages/term-new", json=payload()).status_code
        == 200
    )
    client.headers["Authorization"] = human
    assert client.post(f"/api/v1/proposals/{unrelated}/accept").status_code == 200
    rt = client.app.state.runtime
    actor = rt.auth.authenticate(human.split()[1])
    head = GitRepo(config.wiki_root).head()
    with monkeypatch.context() as patch:

        def fail(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("forced revert failure")

        patch.setattr(GitRepo, "commit", fail)
        with pytest.raises(RuntimeError):
            rt.proposals.revert(pid, actor)
    assert GitRepo(config.wiki_root).head() == head
    GitRepo(config.wiki_root).ensure_main()
    assert client.get(f"/api/v1/proposals/{pid}").json()["status"] == "accepted"
    reverted = client.post(f"/api/v1/proposals/{pid}/revert")
    assert reverted.status_code == 200, reverted.text
    assert client.get("/api/v1/pages/term-new").status_code == 200


def test_human_identity_expiry_draft_and_agent_denial(client: TestClient, config: Settings) -> None:
    auth = Auth(client.app.state.runtime.state)
    human_author = auth.create("human-author", "writer", "restricted", person="alice", kind="human")
    same_person = auth.create(
        "human-reviewer", "reviewer", "restricted", person="alice", kind="human"
    )
    client.headers["Authorization"] = "Bearer " + human_author
    pid = candidate(client)
    client.headers["Authorization"] = "Bearer " + same_person
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 409
    client.headers["Authorization"] = "Bearer " + human_author
    client.post(f"/api/v1/proposals/{pid}/submit")
    client.headers["Authorization"] = "Bearer " + same_person
    assert client.post(f"/api/v1/proposals/{pid}/accept").json()["error"]["code"] == "E_SELF_REVIEW"
    client.headers["Authorization"] = "Bearer " + auth.create(
        "agent-reviewer", "reviewer", "restricted"
    )
    assert (
        client.post(f"/api/v1/proposals/{pid}/accept").json()["error"]["code"] == "E_HUMAN_REQUIRED"
    )
    assert client.post("/api/v1/rules/rule-stack-example-1/promote", json={}).status_code == 403
    assert client.post(f"/api/v1/proposals/{pid}/revert").status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create(
        "expired", "reader", "internal", expires_at="2020-01-01T00:00:00+00:00"
    )
    assert client.get("/api/v1/whoami").status_code == 401
    client.headers["Authorization"] = "Bearer " + same_person
    assert client.get("/api/v1/whoami").json()["person"] == "alice"


def test_editor_identity(client: TestClient, config: Settings) -> None:
    pid = candidate(client)
    auth = Auth(client.app.state.runtime.state)
    client.headers["Authorization"] = "Bearer " + auth.create(
        "bob-editor", "reviewer", "restricted", person="bob", kind="human"
    )
    assert (
        client.patch(
            f"/api/v1/proposals/{pid}/pages/rule-logging",
            json={"ops": [{"op": "set_field", "field": "title", "value": "Edited policy"}]},
        ).status_code
        == 200
    )
    client.headers["Authorization"] = "Bearer " + auth.create(
        "bob-other", "reviewer", "restricted", person="bob", kind="human"
    )
    assert client.post(f"/api/v1/proposals/{pid}/accept").json()["error"]["code"] == "E_SELF_REVIEW"


def test_findings_usage_and_inbox(client: TestClient, config: Settings) -> None:
    data = {
        "kind": "duplicate",
        "pages": ["rule-stack-example-1"],
        "summary": "Дублирующее правило",
        "evidence": [{"page": "rule-stack-example-1", "quote": "Описание счетов"}],
    }
    result = client.post("/api/v1/findings", json=data)
    assert result.status_code == 200, result.text
    finding = result.json()
    assert client.post("/api/v1/findings", json=data).json()["id"] == finding["id"]
    bad = {
        **data,
        "evidence": [
            {"page": "rule-stack-example-1", "quote": "invented sentence never in document"}
        ],
    }
    assert client.post("/api/v1/findings", json=bad).json()["error"]["code"] == "E_QUOTE_NOT_FOUND"
    for _ in range(3):
        assert (
            client.post(
                "/api/v1/rules/violations",
                json={
                    "items": [
                        {
                            "rule_id": "rule-stack-example-1",
                            "note": "Пример не соответствует правилу",
                        }
                    ]
                },
            ).status_code
            == 200
        )
    reviewer(client, config)
    assert client.get("/api/v1/rules/stats").json()["often_violated"] == ["rule-stack-example-1"]
    assert client.get("/api/v1/inbox").json()["open_findings"] == 1
    assert (
        client.post(f"/api/v1/findings/{finding['id']}/dismiss", json={"reason": ""}).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/v1/findings/{finding['id']}/dismiss", json={"reason": "Разные области"}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/findings", json=data).json()["status"] == "dismissed"
    assert client.get("/api/v1/findings/stats").json()["kinds"]["duplicate"]["recommendation"]
    assert client.post(f"/api/v1/findings/{finding['id']}/reopen").json()["status"] == "open"
    denied = client.post(
        "/api/v1/findings", json={**data, "pages": ["sys-restricted"], "evidence": []}
    )
    assert denied.status_code == 200
    client.headers["Authorization"] = "Bearer " + Auth(client.app.state.runtime.state).create(
        "reader-low", "reader", "internal"
    )
    assert len(client.get("/api/v1/findings").json()["items"]) == 1


def test_cors_default_off_and_explicit(config: Settings) -> None:
    for origins, expected in [("", False), ("http://localhost:3000", True)]:
        config.cors_origins = origins
        with TestClient(create_app(config)) as c:
            response = c.options(
                "/api/v1/whoami",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
            assert ("access-control-allow-origin" in response.headers) == expected
            assert response.headers.get("access-control-allow-credentials") is None


def test_direct_review_and_finding_resolution(client: TestClient, config: Settings) -> None:
    pid = candidate(client)
    writer = client.headers["Authorization"]
    reviewer(client, config)
    human = client.headers["Authorization"]
    assert client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200
    assert (
        client.post("/api/v1/rules/rule-logging/promote", json={"level": "must"}).json()["error"][
            "code"
        ]
        == "E_MUST_NEEDS_OWNER"
    )
    assert (
        client.post("/api/v1/rules/rule-logging/promote", json={"level": "should"}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/rules/rule-logging/deprecate", json={"reason": "Заменено решением команды"}
        ).status_code
        == 200
    )
    assert "rule-logging" not in {r["id"] for r in client.get("/api/v1/rules").json()["items"]}
    client.headers["Authorization"] = writer
    fix = proposal(client)
    assert client.put(f"/api/v1/proposals/{fix}/pages/term-new", json=payload()).status_code == 200
    finding = client.post(
        "/api/v1/findings",
        json={
            "kind": "quality",
            "pages": ["rule-logging"],
            "summary": "Неясное правило",
            "proposal_pid": fix,
        },
    ).json()
    client.headers["Authorization"] = human
    assert client.post(f"/api/v1/proposals/{fix}/reject", json={"reason": ""}).status_code == 400
    assert client.post(f"/api/v1/proposals/{fix}/accept").status_code == 200
    assert client.get("/api/v1/findings").json()["items"][0]["status"] == "resolved"
    assert client.post(f"/api/v1/proposals/{fix}/revert").status_code == 200
    assert client.get("/api/v1/findings").json()["items"][0]["id"] == finding["id"]
    assert client.get("/api/v1/findings").json()["items"][0]["status"] == "open"


@pytest.mark.parametrize("after_commit", [False, True])
def test_revert_process_death_recovery(
    client: TestClient, config: Settings, after_commit: bool
) -> None:
    import os
    import subprocess
    import sys

    from wikisvc.services.runtime import Runtime

    pid = candidate(client)
    reviewer(client, config)
    assert (
        client.post(
            f"/api/v1/proposals/{pid}/accept", json={"promote": [{"id": "rule-logging"}]}
        ).status_code
        == 200
    )
    script = """
import os
from wikisvc.config import Settings
from wikisvc.services.runtime import Runtime
from wikisvc.domain.models import Principal
from wikisvc.storage.gitrepo import GitRepo
rt=Runtime(Settings())
commit=GitRepo.commit
def die(self,*args,**kwargs):
    if os.environ['AFTER_COMMIT']=='1':
        commit(self,*args,**kwargs)
    os._exit(9)
GitRepo.commit=die
rt.proposals.revert(os.environ['PID'],Principal(name='human',role='reviewer',clearance='restricted',kind='human'))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "WIKI_ROOT": str(config.wiki_root),
            "STATE_DIR": str(config.state_dir),
            "INDEX_DIR": str(config.index_dir),
            "PID": pid,
            "AFTER_COMMIT": str(int(after_commit)),
        },
        check=False,
    )
    assert result.returncode == 9
    rt = Runtime(config)
    rt.reindex()
    assert rt.state.rows("SELECT status FROM proposals WHERE pid=?", (pid,))[0]["status"] == (
        "reverted" if after_commit else "accepted"
    )
    GitRepo(config.wiki_root).ensure_main()
