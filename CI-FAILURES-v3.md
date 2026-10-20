# Падения CI и полных прогонов при реализации v3

> Журнал по просьбе владельца: при полном прогоне тестов / CI после закрытия этапа падения записываются сюда и
> исправляются после завершения этапа, а не по ходу. Строка удаляется, когда исправление влито.

| дата | этап / ветка | что упало | где (job, тест) | причина | исправлено (коммит) |
|---|---|---|---|---|---|
| 2026-10-20 | docs v3 / PR #35 `feat/wiki-schema` | `just lint` → `ruff format --check` | CI «Lint and static checks», `ref/knowledge-layer-spec.md:787` | ruff форматирует Python-блоки внутри markdown; в ТЗ однострочный `if …: break` | `extend-exclude = ["ref"]` в `pyproject.toml` (ветка `feat/kb-phase1`) |
| 2026-10-20 | docs v3 / PR #35 `feat/wiki-schema` | `wk check --strict` → exit 1 | CI job «check» (`.github/workflows/wk.yml`) | документация чистая (0 ошибок), но `WIKI_TOKEN` в GitHub Secrets пуст → «вика вернула HTTP 401», а `wk` на 401 выходит с кодом 1, не 3 | не исправлено: секрет и workflow меняет человек (`rule-secrets-github-on-request`); либо завести `WIKI_TOKEN`, либо в `wk` считать 401 недоступностью (exit 3) |
