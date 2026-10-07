"""Command line entry point."""

from pathlib import Path
from typing import Annotated, cast

import typer

from wikisvc.config import Settings
from wikisvc.domain.models import Role, Sensitivity

app = typer.Typer(no_args_is_help=True)
tokens = typer.Typer(no_args_is_help=True)
app.add_typer(tokens, name="token")
schema_commands = typer.Typer(no_args_is_help=True)
app.add_typer(schema_commands, name="schema")
policy_commands = typer.Typer(no_args_is_help=True)
app.add_typer(policy_commands, name="policies")
scope_commands = typer.Typer(no_args_is_help=True)
app.add_typer(scope_commands, name="scopes")


def cli_policies(profile: str) -> dict[str, object]:
    from wikisvc.domain.models import Principal
    from wikisvc.services.runtime import Runtime
    from wikisvc.storage.lock import write_lock

    rt = Runtime(settings())
    with write_lock(rt.settings.state_dir, rt.settings.lock_timeout):
        rt.sync_index()
    return rt.policies.compile(
        Principal(name="cli", role="admin", clearance="restricted", kind="human"),
        profile=profile,
        count_usage=False,
    )


@policy_commands.command("export")
def policies_export(
    profile: Annotated[str, typer.Option()], out: Annotated[Path, typer.Option()]
) -> None:
    from wikisvc.services.policies import export_block

    result = cli_policies(profile)
    export_block(out, result)
    typer.echo(f"Exported version {result['version']} to {out}")


@policy_commands.command("check")
def policies_check(
    profile: Annotated[str, typer.Option()], file: Annotated[Path, typer.Option()]
) -> None:
    from wikisvc.services.policies import BLOCK

    matches = BLOCK.findall(file.read_text()) if file.exists() else []
    if matches != [cli_policies(profile)["version"]]:
        typer.echo("Policy block is missing or outdated")
        raise typer.Exit(1)
    typer.echo("Policy block is current")


@scope_commands.command("add")
def scopes_add(value: str) -> None:
    import re

    from wikisvc.domain.errors import WikiError
    from wikisvc.services.migrations import yaml_text
    from wikisvc.services.runtime import Runtime
    from wikisvc.storage.gitrepo import GitRepo
    from wikisvc.storage.lock import write_lock
    from wikisvc.storage.safefs import SafeFS

    if not re.fullmatch(r"[a-z][a-z0-9-]*:[a-z0-9][a-z0-9.-]*", value):
        raise WikiError("E_SCOPE_UNKNOWN", "Область должна иметь вид lang:python.")
    rt = Runtime(settings())
    with write_lock(rt.settings.state_dir, rt.settings.lock_timeout):
        repo = GitRepo(rt.settings.wiki_root)
        repo.ensure_main()
        if value not in rt.registry.scopes:
            with repo.transaction(["schema/scopes.yaml"]):
                SafeFS(repo.root).write(
                    "schema/scopes.yaml", yaml_text([*rt.registry.scopes, value])
                )
                repo.commit(f"Add scope {value}", "cli", ["schema/scopes.yaml"])
            rt.reindex()
            rt.state.audit("cli", "scope.add", value)
    typer.echo(value)


@schema_commands.command("upgrade")
def schema_upgrade(refresh_instructions: bool = False) -> None:
    """Install policy schema additions; content changes require migrate-rules proposals."""
    import json

    from wikisvc.domain.models import Principal
    from wikisvc.services.migrations import upgrade_schema
    from wikisvc.services.runtime import Runtime

    typer.echo(
        json.dumps(
            upgrade_schema(
                Runtime(settings()),
                Principal(name="cli", role="admin", clearance="restricted"),
                refresh_instructions,
            ),
            ensure_ascii=False,
        )
    )


@app.command("migrate-rules")
def migrate_rule_pages(dry_run: bool = False) -> None:
    """Preview legacy conversion or create a draft proposal with WIKI_TOKEN."""
    import json
    import os

    from wikisvc.domain.models import Principal
    from wikisvc.services.migrations import migrate_rules
    from wikisvc.services.runtime import Runtime

    rt = Runtime(settings())
    actor = (
        Principal(name="cli-preview", role="writer", clearance="restricted")
        if dry_run
        else rt.auth.authenticate(os.environ.get("WIKI_TOKEN", ""))
    )
    typer.echo(json.dumps(migrate_rules(rt, actor, dry_run), ensure_ascii=False, indent=2))


def settings() -> Settings:
    import logging

    config = Settings()  # type: ignore[call-arg]
    logging.basicConfig(level=config.log_level)
    return config


@app.command()
def version() -> None:
    """Print the service version."""
    from wikisvc import __version__

    typer.echo(__version__)


@app.command()
def init(path: Path) -> None:
    """Create a separate content repository."""
    from wikisvc.services.initialize import initialize

    initialize(path)
    typer.echo(f"Initialized wiki: {path.resolve()}")


@app.command()
def serve(reload: bool = False) -> None:
    """Serve the API with one worker."""
    import uvicorn

    config = settings()
    uvicorn.run(
        "wikisvc.main:create_app",
        factory=True,
        host=config.bind_host,
        port=config.bind_port,
        reload=reload,
        workers=1,
        log_level=config.log_level.lower(),
    )


@app.command()
def repair_worktrees() -> None:
    """Repair moved wiki/state worktrees with both services stopped, before reindex."""
    from wikisvc.services.relocate import repair_worktrees as repair

    typer.echo(f"Repaired {repair(settings())} worktrees.")


@app.command()
def reindex(full: bool = False) -> None:
    """Rebuild the derived index from content."""
    from wikisvc.services.runtime import Runtime
    from wikisvc.storage.lock import write_lock

    config = settings()
    runtime = Runtime(config)
    with write_lock(config.state_dir, config.lock_timeout):
        issues = runtime.reindex(full)
    typer.echo(f"Index rebuilt; {len(issues)} issues.")


@tokens.command("create")
def token_create(
    name: str = typer.Option(...),
    role: str = "writer",
    clearance: str = "internal",
    person: str | None = None,
    kind: str = "agent",
    expires_at: str | None = None,
) -> None:
    """Issue a token; the plaintext is shown only once."""
    from wikisvc.services.auth import Auth
    from wikisvc.storage.state_db import StateDB

    if role not in ("reader", "writer", "reviewer", "admin") or clearance not in (
        "public",
        "internal",
        "restricted",
    ):
        raise typer.BadParameter("Invalid role or clearance")
    if kind not in ("agent", "human"):
        raise typer.BadParameter("kind: agent or human")
    from typing import Literal

    typer.echo(
        Auth(StateDB(settings().state_dir)).create(
            name,
            cast(Role, role),
            cast(Sensitivity, clearance),
            person,
            cast(Literal["agent", "human"], kind),
            expires_at,
        )
    )


@tokens.command("revoke")
def token_revoke(name: str) -> None:
    """Revoke a named token."""
    from wikisvc.services.auth import Auth
    from wikisvc.storage.state_db import StateDB

    Auth(StateDB(settings().state_dir)).revoke(name)
    typer.echo("Revoked")


@tokens.command("list")
def token_list() -> None:
    """List names, access and revocation dates without credentials or hashes."""
    import json

    from wikisvc.storage.state_db import StateDB

    rows = StateDB(settings().state_dir).rows(
        "SELECT name,role,clearance,person,kind,expires_at,created_at,revoked_at FROM tokens ORDER BY name"
    )
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@app.command()
def lint() -> None:
    """Print all lint findings; exit with 1 if errors exist."""
    import json

    from wikisvc.domain.models import Principal
    from wikisvc.services.runtime import Runtime
    from wikisvc.storage.lock import write_lock

    config = settings()
    runtime = Runtime(config)
    with write_lock(config.state_dir, config.lock_timeout):
        runtime.indexer.reindex()
    issues = runtime.lint.run(Principal(name="cli", role="admin", clearance="restricted"))
    typer.echo(json.dumps([issue.model_dump() for issue in issues], ensure_ascii=False, indent=2))
    if any(issue.severity == "error" for issue in issues):
        raise typer.Exit(1)


@app.command()
def mcp() -> None:
    """Run MCP over stdio, authenticated with WIKI_TOKEN."""
    from wikisvc.mcp_server import create_server
    from wikisvc.services.runtime import Runtime
    from wikisvc.storage.lock import write_lock

    config = settings()
    runtime = Runtime(config)
    with write_lock(config.state_dir, config.lock_timeout):
        runtime.indexer.reindex()
        runtime.proposals.expire()
    create_server(runtime).run(transport="stdio")


if __name__ == "__main__":
    app()
