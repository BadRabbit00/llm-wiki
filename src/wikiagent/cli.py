from pathlib import Path

import typer

from wikiagent.config import load_config

app = typer.Typer(no_args_is_help=True)


@app.command()
def serve(config: Path | None = None) -> None:
    import uvicorn

    from wikiagent.api import create_app

    settings = load_config(config)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)


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
