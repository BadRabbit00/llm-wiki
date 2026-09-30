dev:
    python -m wikisvc.cli serve --reload

test:
    pytest -q

lint:
    ruff check .
    ruff format --check .
    mypy src

init-dev:
    python -m wikisvc.cli init ../wiki

reindex:
    python -m wikisvc.cli reindex --full
