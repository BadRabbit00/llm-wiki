# Наблюдаемость

Метрик (Prometheus, OpenTelemetry), дашбордов и алертов нет. Есть логи в journald, healthcheck-эндпоинты
двух служб и внутренняя статистика в базах.

## Логи

- format: текст, не JSON; `request_id` нет (RISK в отчёте infra-агента: rule-arch-structured-logging, rule-stack-observability).

| компонент | чем пишет | формат |
|---|---|---|
| SVC-wikisvc | `logging` (логгер `wikisvc`), uvicorn access/error log | строки по умолчанию `logging.basicConfig` и uvicorn; уровень — CFG-wikisvc.LOG_LEVEL (`DEBUG`…`CRITICAL`, по умолчанию `INFO`) |
| SVC-wikiagent | `logging` модулей, uvicorn | строки uvicorn по умолчанию; уровень не настраивается |
| SVC-wiki-ui | `log.Printf` / `log.Fatal` (Go stdlib) | строка с датой |
| SVC-updater | `log/slog` `TextHandler` в stderr | `key=value` (logfmt-подобный) |
| RES-llama-server | сам `llama-server` | его собственный формат |

- where: stdout/stderr. ENV-prod: контейнеры — `--log-driver journald` (`deploy/run.sh`), юниты хоста
  (`llm-wiki-model`, `llm-wiki-updater`, `llm-wiki-backup`) — journald через systemd. Смотреть: `journalctl -u <юнит>`.
  Хранение и ротация — настройки journald хоста, в репозитории не заданы. ENV-dev: терминал.
- must not log: SEC-pii, SEC-secrets. Токены в БД только хешами; `BodyLimit` в `src/wikisvc/main.py` пишет только код
  ошибки и не чаще раза в минуту. Автоматической проверки логов на секреты нет (`src/wikiagent/check.py` проверяет
  токен и модели, а не логи); SEC-secret-detector применяется к контенту и заданиям аудита, не к логам.
- В образе `PYTHONUNBUFFERED=1`, чтобы строки уходили в journald сразу.

## Метрики, алерты, healthcheck

| id | вид | имя / путь | компонент | порог | что делать | status |
|---|---|---|---|---|---|---|
| OBS-wikisvc.health | health | `GET /api/v1/health` (API-wikisvc.health) | SVC-wikisvc | HTTP 200 и `version` = версия релиза | нет ответа — `journalctl -u wikisvc`; не та версия — откат по FLOW-release-update (v3 planned: + поле `embeddings` — OBS-wikisvc.embeddings-selftest) | implemented |
| OBS-wiki-ui.health | health | `GET /healthz` | SVC-wiki-ui | HTTP 200 | `journalctl -u wiki-ui` | implemented |
| OBS-logs | dashboard | `journalctl -u wikisvc -u wikiagent -u wiki-ui -u llm-wiki-model -u llm-wiki-updater -u llm-wiki-backup` | все службы ENV-prod | — | разбор сбоев; `ref/deploy-linux.md`, раздел 5 «Доступ и диагностика» (v3 planned: + `-u llm-wiki-embeddings`, RES-embeddings-server) | implemented |
| OBS-wikisvc.embeddings-selftest | health | поле `embeddings` в ответе `GET /api/v1/health` (состав поля — API-wikisvc.health); вручную — CLI-wikisvc-cli.embeddings.selftest | SVC-wikisvc | до любого прогона: две фиксированные пары текстов в коде, косинусы сравниваются с `meta.embeddings_selftest`, записанным при первом успешном запуске модели; расхождение > 0.02 — провал (решение Q-kb-embeddings-selftest) | провал или недоступность — `embeddings: failed` при `status: ok`, `ask` идёт с `degraded: true` (ERR-embeddings_unavailable); проверить юнит RES-embeddings-server, файл модели и pooling (CFG-wikisvc.EMBEDDINGS_POOLING); на откат FLOW-release-update поле не влияет — health остаётся `ok` (решение Q-kb-embeddings-selftest) | planned |
| OBS-eval-metrics | отчёт CI | вывод `pytest -m eval` в джобе `quality` PIPE-ci: Recall@8 (`seeds[]`), Recall@20 (`seeds ∪ expanded`) по срезам single/multi и ru/en, доля запросов с `expansion_used` и доля, где оно подняло recall (ТЗ §10); для A/B моделей эмбеддингов — ещё доля размеченных дубликатов в kNN top-10 при 0.80 | LIB-wikisvc-core | строго не ниже базовой линии `tests/fixtures/kb-eval-baseline.json` (NFR-eval-recall-baseline; решение Q-kb-eval-baseline); для живой вики — `schema/eval/baseline.json` в RES-wiki-repo через CLI-wikisvc-cli.eval | регресс — найти изменение, которое его дало; рост — человек поднимает базовую линию в том же PR; A/B моделей (ADR-0018) сравнивается этим же отчётом | planned |
| OBS-ppr-latency | перф-тест | `pytest -m perf` в отдельном джобе `perf` PIPE-ci (`continue-on-error`, артефакт), локально `just perf` и `scripts/benchmark_retrieval.py`: медиана PPR на синтетике 50 000 узлов / 500 000 рёбер с проверкой сходимости | LIB-wikisvc-core | ≤ 50 ms при допуске 1e-6 (NFR-ppr-latency); в CI не гейт (решение Q-kb-perf-ci-runner) | превышение — разбор CLS-wikisvc-core.ppr и CLS-wikisvc-core.GraphSnapshot, подтверждение локальным `just perf`. В рантайме метрики нет (Prometheus в проекте нет) | planned |

### Что проверяет health wikisvc (OBS-wikisvc.health)

- Ответ `{"status": "ok", "version": <версия кода>, "index_commit": <коммит индекса>}` (`src/wikisvc/main.py`).
  Читает `meta.index_commit` из RES-index-db, то есть проверяет доступность индекса; RES-state-db и git не трогает.
  Отдельного `/ready` нет (rule-arch-health-readiness).
- Без токена, если не задан `SESSION_ISSUER_TOKEN_NAME` с заголовком Authorization; в лимит запросов не входит.
- Кто дёргает: SVC-updater после обновления (шаг `health`: версия = тег, таймаут 3 min), `scripts/smoke-image.sh`
  (PIPE-ci, PIPE-release), VM-тесты `deploy/vm-test.nix` и `deploy/vm-update-test.nix`, оператор — `curl` по
  `ref/deploy-linux.md`.

### Что проверяет health wiki-ui (OBS-wiki-ui.health)

- Статический ответ `{"status":"ok","service":"wiki-ui"}` (`ui/main.go`): процесс жив и слушает порт;
  OIDC-провайдер и wikisvc не проверяет.
- Кто дёргает: SVC-updater (если UI работал до обновления), `scripts/smoke-image.sh`, VM-тесты.

### Готовность в systemd

- Юниты `wikisvc`, `wikiagent`, `wiki-ui` — `Type=notify` с `--sdnotify conmon`: systemd считает службу готовой,
  когда контейнер запущен, а не когда healthcheck ответил. HEALTHCHECK в образе и `--health-cmd` в podman нет
  (RISK в отчёте infra-агента: rule-deploy-healthcheck-readiness).
- `wikiagent.service` до старта ждёт до 600s wikisvc и модель: `ExecStartPre` = `wikiagent check --wait 600 --dependencies-only`.
- HTTP-эндпоинта здоровья у SVC-wikiagent и SVC-updater нет: здоровье агента updater определяет по состоянию юнита
  (`active`), API updater (`/v1/status`) доступен только администратору через сокет.
- Проверка модели — `llm-wiki-admin check --model` (короткий запрос к каждой модели) и `curl http://127.0.0.1:18089/health`
  к RES-llama-server.

## Внутренняя статистика

Не метрики мониторинга, а данные продукта в SQLite, видимые через API:

| таблица | что считает |
|---|---|
| TBL-wikisvc-core.index.delivery_stats | выдачу страниц в контексте агентам; живёт в индексе (RES-index-db): `reindex --full` её сохраняет, но восстановление из копии и пересоздание индекса — нет (v3 planned: + выданные id, идентичность вызывающего (имя токена или person) и какие id агент открыл через `get_fact` — основа будущего `f_usage`; запись — очередью CLS-wikisvc-core.DeliveryQueue, без текста запросов — SEC-delivery-stats) |
| TBL-wikisvc-core.state.rule_usage | выдачи, открытия и нарушения каждого правила по дням |
| TBL-wikiagent.agent.model_calls | вызовы модели агентом; основа суточных бюджетов `heal` и `docs_audit` |
