"""Schema versions: a database records its schema, and older code refuses a newer one."""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.index.db import IndexDB
from wikisvc.services.runtime import Runtime
from wikisvc.storage.db_version import AGENT_SCHEMA, INDEX_SCHEMA, STATE_SCHEMA
from wikisvc.storage.state_db import StateDB

DATABASES: dict[str, tuple[Callable[[Path], object], str, int]] = {
    "state": (StateDB, "state.db", STATE_SCHEMA),
    "index": (IndexDB, "wiki.db", INDEX_SCHEMA),
    "agent": (AgentState, "agent.db", AGENT_SCHEMA),
}

# A schema change must raise its version. When this test fails, raise the version in
# wikisvc/storage/db_version.py, give older code a migration, and record the new
# fingerprint here.
FINGERPRINTS = {
    "state": (1, "da3d7e6b67b28395d41554c9bbf74cfedba4789ef4b6a7d5383d9d63bdba10eb"),
    "index": (1, "47c417cf84ec17aa69323334627bdecb7b7a6f65cefd5f678f7d03d0e1de353f"),
    "agent": (1, "362204e941381283cd90299e28b3bb0deb68633b8f72f3677becb8d8edd06069"),
}


def user_version(path: Path) -> int:
    with sqlite3.connect(path) as db:
        return int(db.execute("PRAGMA user_version").fetchone()[0])


def set_user_version(path: Path, value: int) -> None:
    db = sqlite3.connect(path)
    try:
        db.execute(f"PRAGMA user_version = {value}")
        db.execute("CREATE TABLE written_by_newer_code (x)")
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("name", DATABASES)
def test_a_fresh_database_records_its_schema(tmp_path: Path, name: str) -> None:
    factory, filename, known = DATABASES[name]
    factory(tmp_path)
    assert user_version(tmp_path / filename) == known


@pytest.mark.parametrize("name", DATABASES)
def test_a_database_from_before_versions_is_migrated_and_stamped(tmp_path: Path, name: str) -> None:
    factory, filename, known = DATABASES[name]
    factory(tmp_path)
    with sqlite3.connect(tmp_path / filename) as db:
        db.execute("PRAGMA user_version = 0")
    factory(tmp_path)
    assert user_version(tmp_path / filename) == known


@pytest.mark.parametrize("name", DATABASES)
def test_older_code_refuses_a_newer_database_and_leaves_it_alone(tmp_path: Path, name: str) -> None:
    factory, filename, known = DATABASES[name]
    factory(tmp_path)
    set_user_version(tmp_path / filename, known + 1)
    with pytest.raises(WikiError) as refused:
        factory(tmp_path)
    assert refused.value.code == "E_SCHEMA_NEWER"
    assert f"схема {known + 1}" in refused.value.message
    assert user_version(tmp_path / filename) == known + 1
    with sqlite3.connect(tmp_path / filename) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='written_by_newer_code'"
        ).fetchone()


def test_a_full_reindex_replaces_an_index_a_newer_version_wrote(config: Settings) -> None:
    original = Runtime(config)
    issues = original.reindex(True)
    with original.index.connect() as db:
        pages = [row[0] for row in db.execute("SELECT id FROM pages ORDER BY id")]
    assert len(pages) >= 30
    set_user_version(config.index_dir / "wiki.db", INDEX_SCHEMA + 1)
    with pytest.raises(WikiError) as refused:
        Runtime(config)
    assert refused.value.code == "E_SCHEMA_NEWER" and "reindex --full" in refused.value.hint
    runtime = Runtime(config, discard_newer_index=True)
    # The rebuilt index reports the same corpus as before the newer version touched it.
    assert runtime.reindex(True) == issues
    assert user_version(config.index_dir / "wiki.db") == INDEX_SCHEMA
    with runtime.index.connect() as db:
        assert [row[0] for row in db.execute("SELECT id FROM pages ORDER BY id")] == pages
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='written_by_newer_code'"
        ).fetchone()


@pytest.mark.parametrize("name", DATABASES)
def test_the_schema_matches_its_version(tmp_path: Path, name: str) -> None:
    factory, filename, known = DATABASES[name]
    factory(tmp_path)
    with sqlite3.connect(tmp_path / filename) as db:
        rows = db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    fingerprint = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    assert (known, fingerprint) == FINGERPRINTS[name], (
        f"The {name} schema changed: raise its version and record {fingerprint}"
    )
