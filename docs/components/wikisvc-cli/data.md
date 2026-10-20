# wikisvc-cli: данные

SVC-wikisvc-cli своих данных не имеет: таблицы, репозиторий и индекс принадлежат LIB-wikisvc-core,
описание — в `components/wikisvc-core/data.md`.

changed: 2026-10-20 v3 (planned): своих данных по-прежнему нет. `eval --out` пишет отчёт FMT-wikisvc-cli.eval-report
по пути оператора; `domains add` меняет `schema/domains.yaml` и `kb/` через сервис ядра в BKT-wikisvc-core.wiki-repo.
