"""Schema versions of the SQLite databases, kept in PRAGMA user_version.

Each database records the schema version of the newest code that migrated it, and
code refuses a database newer than itself. Without this, an older image started by
hand on a migrated database runs on a schema it does not know, and nothing says so.
A version changes together with its schema: tests/test_db_version.py
fingerprints every schema and fails until the version is raised.
"""

import sqlite3

from wikisvc.domain.errors import WikiError

STATE_SCHEMA = 1
INDEX_SCHEMA = 1
AGENT_SCHEMA = 1


def version(db: sqlite3.Connection) -> int:
    return int(db.execute("PRAGMA user_version").fetchone()[0])


# doc: CLS-wikisvc-core.refuse_newer
def refuse_newer(db: sqlite3.Connection, name: str, known: int, hint: str) -> None:
    found = version(db)
    if found > known:
        raise WikiError(
            "E_SCHEMA_NEWER",
            f"База {name} записана более новой версией: схема {found}, эта версия знает {known}.",
            hint,
            status=500,
        )


def stamp(db: sqlite3.Connection, known: int) -> None:
    """Record the schema after migrating; never lowers it."""
    if version(db) < known:
        # PRAGMA takes no parameters; int() keeps the statement a constant.
        db.execute(f"PRAGMA user_version = {int(known)}")
