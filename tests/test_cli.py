import hashlib
import json

import pytest
from typer.testing import CliRunner

from wikisvc.cli import app
from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB


def test_help() -> None:
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0


def test_token_list_does_not_expose_credentials(
    config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIKI_ROOT", str(config.wiki_root))
    monkeypatch.setenv("STATE_DIR", str(config.state_dir))
    monkeypatch.setenv("INDEX_DIR", str(config.index_dir))
    auth = Auth(StateDB(config.state_dir))
    token = auth.create("listed", "reader", "internal")
    auth.revoke("listed")
    result = CliRunner().invoke(app, ["token", "list"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows[0]["name"] == "listed" and rows[0]["revoked_at"]
    assert "token_hash" not in rows[0]
    assert token not in result.stdout
    assert hashlib.sha256(token.encode()).hexdigest() not in result.stdout
