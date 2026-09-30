from typer.testing import CliRunner

from wikisvc.cli import app


def test_help() -> None:
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0
