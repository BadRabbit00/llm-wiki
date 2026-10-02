from wikisvc.config import Settings
from wikisvc.domain.models import LintIssue
from wikisvc.index.context import Context
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import GraphStore, SqliteGraphStore
from wikisvc.index.indexer import Indexer
from wikisvc.index.search import Search
from wikisvc.services.auth import Auth
from wikisvc.services.lint import Lint
from wikisvc.services.pages import Pages
from wikisvc.services.policies import Policies
from wikisvc.services.proposals import Proposals
from wikisvc.services.raw import Raw
from wikisvc.services.rules import Rules
from wikisvc.services.schema import Schema
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.schema import load_registry
from wikisvc.storage.state_db import StateDB


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        with write_lock(settings.state_dir, settings.lock_timeout):
            GitRepo(settings.wiki_root).recover()
        self.registry = load_registry(settings.wiki_root)
        self.state = StateDB(settings.state_dir)
        self.index = IndexDB(settings.index_dir)
        self.auth = Auth(self.state, settings.rate_limit_per_min)
        self.indexer = Indexer(settings.wiki_root, self.index, self.registry)
        self.indexer.validation.entropy_threshold = settings.secret_entropy_threshold
        self.graph: GraphStore = SqliteGraphStore(self.index)
        self.pages = Pages(settings.wiki_root, self.index, self.state, self.graph)
        self.policies = Policies(self)
        self.search = Search(self.index, settings.boosts(), self.graph)
        self.search.synonyms = self.registry.synonyms
        self.context = Context(
            self.index, self.pages, settings.relation_priority.split(","), self.graph
        )
        self.proposals = Proposals(self)
        self.rules = Rules(self)
        self.raw = Raw(self)
        self.lint = Lint(self)
        self.schema = Schema(self)
        with write_lock(settings.state_dir, settings.lock_timeout):
            self.proposals.recover()

    def reindex(self, full: bool = True) -> list[LintIssue]:
        """Refresh schema and rebuild all or changed documents while the caller holds the lock."""
        paths: list[str] | None = None
        if not full:
            with self.index.connect() as db:
                previous = db.execute("SELECT value FROM meta WHERE key='index_commit'").fetchone()
            if previous:
                repo = GitRepo(self.settings.wiki_root)
                paths = repo.run("diff", "--name-only", previous[0], "--").splitlines()
                paths.extend(repo.run("ls-files", "--others", "--exclude-standard").splitlines())
                if any(path.startswith("schema/") for path in paths):
                    paths = None
        self.registry = load_registry(self.settings.wiki_root)
        self.indexer.registry = self.registry
        self.search.synonyms = self.registry.synonyms
        return self.indexer.reindex(paths)

    def sync_index(self) -> None:
        """Refresh externally committed changes before a write advances index_commit."""
        with self.index.connect() as db:
            previous = db.execute("SELECT value FROM meta WHERE key='index_commit'").fetchone()
        if previous is None or previous[0] != GitRepo(self.settings.wiki_root).head():
            self.reindex(full=False)
