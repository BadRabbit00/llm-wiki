import subprocess
from pathlib import Path

import httpx
import pytest

from wikiagent.auth_check import check_authentication
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB


@pytest.mark.parametrize("failure", [None, "missing", "revoked", "expired", "privileged", "roles"])
def test_local_issuer_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    state = StateDB(tmp_path / "state")
    auth = Auth(state)
    if failure != "missing":
        auth.create(
            "wiki-ui",
            "admin" if failure == "privileged" else "reader",
            "public",
            expires_at="2000-01-01T00:00:00+00:00" if failure == "expired" else None,
        )
    if failure == "revoked":
        auth.revoke("wiki-ui")
    roles = tmp_path / "roles.yaml"
    roles.write_text("groups: {wiki-readers: {role: reader, clearance: internal}}")
    monkeypatch.setenv("SESSION_ISSUER_TOKEN_NAME", "wiki-ui")
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ROLES_FILE", str(roles if failure != "roles" else tmp_path / "missing"))
    monkeypatch.setenv("WIKI_UI_OIDC_ISSUER", "https://idp.example/application/o/wiki/")
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "yes\n")
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert (
            request.url == "https://idp.example/application/o/wiki/.well-known/openid-configuration"
        )
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"issuer": "https://idp.example/application/o/wiki/"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        if failure:
            with pytest.raises(ValueError):
                check_authentication(http)
        else:
            messages = check_authentication(http)
            assert messages == [
                "session issuer: valid (local DB); roles: wiki-readers",
                "OIDC discovery: ready",
                "NTP: synchronized",
            ]
            monkeypatch.setattr(
                subprocess,
                "run",
                lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "no\n"),
            )
            with httpx.Client(
                transport=httpx.MockTransport(lambda request: httpx.Response(503))
            ) as down:
                degraded = check_authentication(down)
            assert degraded[1].startswith("WARN OIDC") and degraded[2].startswith("WARN NTP")


def test_auth_diagnostics_disabled_with_legacy_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SESSION_ISSUER_TOKEN_NAME", raising=False)
    assert check_authentication() == []
