# doc: MOD-wikiagent.cli
from pathlib import Path

import typer

from wikiagent.config import load_config

app = typer.Typer(no_args_is_help=True)


# doc: CLI-wikiagent.check
@app.command("check")
def check_deployment(
    dependencies_only: bool = False,
    model: bool = False,
    wait: float = typer.Option(0, min=0, max=3600),
) -> None:
    """Check service/token/model readiness; --model also tests structured generation."""
    import time

    import httpx

    from wikiagent.check import check

    config = load_config()
    deadline = time.monotonic() + wait
    previous = ""
    while True:
        try:
            for message in check(config, dependencies_only=dependencies_only, model=model):
                typer.echo(message)
            return
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            # Never print HTTP bodies, authorization headers or model responses.
            message = (
                f"HTTP {exc.response.status_code}: {exc.request.url.path}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            if type(exc) is ValueError:
                message = str(exc)
            if message != previous:
                typer.echo(f"Not ready: {message}", err=True)
                previous = message
            if time.monotonic() >= deadline:
                raise typer.Exit(1) from None
            time.sleep(min(2, max(0, deadline - time.monotonic())))


@app.command()
# doc: CLI-wikiagent.jobs
def jobs() -> None:
    """Jobs the agent resumes after a restart, as JSON: identity and status, no payload."""
    import json

    from wikiagent.jobs.runner import RESUMABLE
    from wikiagent.state import AgentState

    state = AgentState(load_config().state_dir)
    rows = state.rows(
        "SELECT id,kind,status,updated_at FROM jobs "
        f"WHERE status IN ({','.join('?' * len(RESUMABLE))}) ORDER BY created_at,id",
        RESUMABLE,
    )
    typer.echo(json.dumps(rows))


@app.command()
# doc: CLI-wikiagent.serve
def serve(config: Path | None = None) -> None:
    import uvicorn

    from wikiagent.api import create_app

    settings = load_config(config)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)


# doc: CLI-wikiagent.eval
@app.command("eval")
def evaluate(
    role: str = "planner",
    model: str | None = None,
    scenarios: Path = Path("tests/scenarios"),
    out: Path | None = None,
) -> None:
    import json

    from wikiagent.planner.eval import evaluate_scenarios

    typer.echo(
        json.dumps(
            evaluate_scenarios(load_config(), scenarios, role, model, out=out),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
