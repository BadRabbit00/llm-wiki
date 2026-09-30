import subprocess
from pathlib import Path

import pytest
from conftest import make_page

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Principal
from wikisvc.domain.registry import Registry
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph
from wikisvc.index.indexer import Indexer, chunks
from wikisvc.index.normalize import match_query, normalize
from wikisvc.services.initialize import initialize
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import StateDB


def test_normalizer_and_query() -> None:
    assert normalize("Выгрузки счетов") == normalize("выгрузка счёта")
    assert normalize("running exports") == normalize("run export")
    assert match_query('"выгрузки счетов" банк*') == '"выгрузк счет" AND "банк"*'
    assert match_query('" OR * : ; --') == '"or"'
    assert match_query("   ") == ""


def test_incremental_graph_and_visibility(tmp_path: Path, registry: Registry) -> None:
    root = tmp_path / "wiki"
    initialize(root)
    fs = SafeFS(root)
    term = make_page(registry, "term-invoice", relations={"depends_on": ["term-bank"]})
    bank = make_page(
        registry, "term-bank", sensitivity="restricted", relations={"related": ["term-public"]}
    )
    public = make_page(registry, "term-public")
    for page in (term, bank, public):
        fs.write(page.path, render(page.frontmatter.model_dump(), page.body_md))
    repo = GitRepo(root)
    repo.commit("Add pages", "writer")
    index = IndexDB(tmp_path / "index")
    indexer = Indexer(root, index, registry)
    assert not any(i.severity == "error" for i in indexer.reindex())
    with index.connect() as db:
        assert (
            db.execute(
                "SELECT rel FROM edges WHERE src='term-bank' AND dst='term-invoice'"
            ).fetchone()[0]
            == "required_by"
        )
        assert (
            db.execute(
                "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                (match_query("выгрузки счетов"),),
            ).fetchone()[0]
            == 3
        )
    actor = Principal(name="reader", role="reader", clearance="internal")
    graph = Graph(index)
    assert len(graph.neighbors(term.id, actor, depth=5)["nodes"]) == 1
    assert graph.path(term.id, public.id, actor)["nodes"] == []
    assert len(graph.export(actor)["nodes"]) == 2
    with pytest.raises(WikiError) as error:
        graph.neighbors(bank.id, actor)
    assert error.value.status == 404
    actor.clearance = "restricted"
    assert graph.path(term.id, public.id, actor)["nodes"] == [term.id, bank.id, public.id]
    assert len(graph.neighbors(term.id, actor, direction="out", rels=["depends_on"])["nodes"]) == 2
    term.body_md += "\n\n### Extra\nUpdated invoice processing."
    fs.write(term.path, render(term.frontmatter.model_dump(), term.body_md))
    fs.remove(public.path)
    fs.write("wiki/broken.md", "not frontmatter")
    repo.commit("Update", "writer")
    indexer.reindex([term.path, public.path, "wiki/broken.md"])

    def snapshot() -> tuple[list[tuple[object, ...]], ...]:
        with index.connect() as db:
            return tuple(
                [tuple(row) for row in db.execute(sql)]
                for sql in (
                    "SELECT * FROM pages ORDER BY id",
                    "SELECT * FROM edges ORDER BY src,dst,rel,kind",
                    "SELECT page_id,ord,heading,text FROM chunks ORDER BY page_id,ord",
                    "SELECT title,heading,text FROM chunks_fts ORDER BY title,heading,text",
                    "SELECT * FROM issues ORDER BY path,data",
                )
            )

    incremental = snapshot()
    indexer.reindex()
    assert snapshot() == incremental


def test_chunks() -> None:
    result = chunks("## Heading\n\n" + "a" * 700 + "\n\n" + "b" * 700 + "\n\n" + "c" * 700)
    assert len(result) == 2 and "b" * 700 in result[0][1] and "b" * 700 in result[1][1]
    assert all(len(text) <= 1500 for _, text in chunks("## Long\n" + "a" * 5000))
    assert chunks("") == [("", "")]


def test_state_git_and_lock(tmp_path: Path) -> None:
    root, state = tmp_path / "wiki", tmp_path / "state"
    initialize(root)
    repo = GitRepo(root)
    repo.ensure_main()
    base = repo.head()
    work = state / "worktrees/test"
    with write_lock(state):
        repo.add_worktree(work, "proposal/test")
        with pytest.raises(WikiError, match="ожидания"), write_lock(state, timeout=0.01):
            pass
    SafeFS(work).write("wiki/test.md", "hello")
    GitRepo(work).commit("Work", "alice")
    assert repo.changed(base, "proposal/test") == ["wiki/test.md"]
    repo.remove_worktree(work, "proposal/test")
    assert not work.exists()
    assert repo.history("wiki/index.md")[0]["author"] == "wikisvc"
    assert "Индекс" in repo.show(base, "wiki/index.md")
    with pytest.raises(WikiError):
        repo.show("--all", "wiki/index.md")
    with pytest.raises(WikiError):
        repo.show(base, "../secret")
    with pytest.raises(WikiError):
        repo.show(base, "wiki/missing.md")
    SafeFS(root).write("inbox/file", "raw")
    repo.ensure_main()
    SafeFS(root).write("wiki/uncommitted.md", "local content")
    with pytest.raises(WikiError):
        repo.ensure_main()
    database = StateDB(state)
    database.audit("alice", "test", "id")
    assert database.rows("SELECT token_name FROM audit")[0]["token_name"] == "alice"
    assert database.path.stat().st_mode & 0o777 == 0o600
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, check=False
        ).returncode
        == 0
    )


def test_existing_state_schema_migrates_without_data_loss(tmp_path: Path) -> None:
    from wikisvc.services.auth import Auth

    state = StateDB(tmp_path / "state")
    token = Auth(state).create("existing", "writer", "internal")
    with state.connect() as db:
        db.execute("ALTER TABLE proposals DROP COLUMN last_editor")
        db.execute("ALTER TABLE raw_notes DROP COLUMN original_name")
        db.execute(
            "INSERT INTO raw_notes VALUES ('test-hash','saved note','existing','raw/docs/test.txt')"
        )
    migrated = StateDB(tmp_path / "state")
    assert Auth(migrated).authenticate(token).name == "existing"
    assert migrated.rows("SELECT note,original_name FROM raw_notes") == [
        {"note": "saved note", "original_name": None}
    ]
