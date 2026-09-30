from wikisvc.config import Settings
from wikisvc.domain.models import LintIssue
from wikisvc.index.context import Context
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph
from wikisvc.index.indexer import Indexer
from wikisvc.index.search import Search
from wikisvc.services.auth import Auth
from wikisvc.services.lint import Lint
from wikisvc.services.pages import Pages
from wikisvc.services.proposals import Proposals
from wikisvc.services.raw import Raw
from wikisvc.services.schema import Schema
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.schema import load_registry
from wikisvc.storage.state_db import StateDB


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = load_registry(settings.wiki_root)
        self.state = StateDB(settings.state_dir)
        self.index = IndexDB(settings.index_dir)
        self.auth = Auth(self.state, settings.rate_limit_per_min)
        self.indexer = Indexer(settings.wiki_root, self.index, self.registry)
        self.pages = Pages(settings.wiki_root, self.index)
        self.search = Search(self.index, settings.boosts())
        self.graph = Graph(self.index)
        self.context = Context(self.index, self.pages, settings.relation_priority.split(","))
        self.proposals = Proposals(self)
        self.raw = Raw(self)
        self.lint = Lint(self)
        self.schema = Schema(self)

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
        return self.indexer.reindex(paths)
