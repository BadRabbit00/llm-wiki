# wikiagent

> Карточка компонента. Агент читает этот файл первым, когда задача касается компонента.

### SVC-wikiagent — Агент вики с моделью
status: implemented | kind: http-service + worker | lang: LANG-python

- purpose: всё, что в llm-wiki требует языковой модели: чат с планировщиком правил из фраз
  (FLOW-chat-plan), правка существующих страниц, разбор книги (FLOW-ingest-book), самолечение
  (FLOW-heal) и сверка документации проекта (FLOW-docs-audit); результат — черновик предложения
  или находка в SVC-wikisvc, никогда не публикация.
- not responsible for:
  - не принимает решений: accept, promote, deprecate, revert, reject, verify делает человек
    (INV-human-decides); `CLS-wikiagent.WikiClient` режет эти пути до отправки;
  - не принимает анонимных вызовов: каждый эндпоинт требует bearer-токен, который проверяет
    SVC-wikisvc (`API-wikisvc.*`, `/whoami`);
  - не пишет в git и БД SVC-wikisvc: все изменения — через HTTP `API-wikisvc.*` рабочим токеном
    агента; исключение — только чтение `state.db` (RES-state-db) командой CLI-wikiagent.check;
  - не хранит секретов: токены берёт из окружения по имени переменной (INV-secrets-never-stored).
- changed: 2026-10-20 v3 (planned): слой знаний (ТЗ `ref/knowledge-layer-spec.md` §8, §11.8–11.9):
  ingest книги фактами по окнам и хабам (FLOW-fact-ingest, JOB-wikiagent.ingest-book), судья в двух ролях
  MOD-wikiagent.judge (claim ↔ claim — FLOW-dedup-judge; claim ↔ источник — grounding), маршрутизация ревью
  auto/queue/pair (FLOW-fact-review-routing, STATE-fact-review-class), фоновый JOB-wikiagent.novelty-scan
  (FLOW-novelty-scan), heal для фактов. Предложения агент не принимает: `auto`-блок принимает человек одним
  действием (решение Q-kb-auto-accept-human-decides). Эмбеддингов, графа и reranker'а агент не держит — kNN и `ask`
  у ядра (`API-wikisvc.knowledge.similar` с `include_pending`, `API-wikisvc.knowledge.ask`; решения Q-kb-knn-endpoint,
  Q-kb-reranker-placement); вердикты пар и novelty агент пишет в ядро (`API-wikisvc.knowledge.verdicts`,
  `API-wikisvc.knowledge.novelty`), своё в `agent.db` — только кэш.
- path: `src/wikiagent/`
- manifest: `pyproject.toml` (общий с SVC-wikisvc, скрипт `wikiagent = "wikiagent.cli:app"`), lock: `flake.lock`
- build: TOOL-nix, TOOL-hatchling; `nix build .#wikiagent` (тот же пакет, что `.#default`; образ — `.#image`)
- run locally: `nix develop -c wikiagent serve` (порт 8788, `CFG-wikiagent.bind_port`; конфиг FMT-wikiagent.config)
- test: `nix develop -c pytest -q`
- entrypoints: `src/wikiagent/cli.py` — Typer-приложение `wikiagent` (serve, check, jobs, eval)
- framework: DEP-py-fastapi (сервер DEP-py-uvicorn)
- deps: DEP-py-httpx, DEP-py-pydantic, DEP-py-typer, DEP-py-uvicorn; v3: DEP-py-onnxruntime, DEP-py-tokenizers (полный список — `stack/dependencies.md`)
- models: MDL-wiki-gemma-31b (роли `planner`, `reviewer`, `chat` в FMT-wikiagent.config);
  v3 (planned): NLI MDL-nli-judge, MDL-nli-judge-light, MDL-grounding-judge (ONNX); LLM-ступень судьи — та же модель роли
  `reviewer` (MDL-gemma-12b в проде, отдельного процесса нет), она же — эскалация grounding (MDL-grounding-escalation —
  опция на будущее; решения Q-kb-nli-judge-model, Q-kb-judge-runtime),
  референсные модели novelty по семействам (CFG-wikiagent.models.reference, решение Q-kb-novelty-reference-model)

## Что компонент даёт другим

- API: API-wikiagent.* (HTTP без префикса версии, детали — `contracts.md`)
- cli: CLI-wikiagent.serve, CLI-wikiagent.check, CLI-wikiagent.jobs, CLI-wikiagent.eval
- consumers: SVC-wiki-ui (прокси от имени человека); SVC-updater вызывает CLI-wikiagent.jobs

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| `API-wikisvc.*` | `/whoami` для каждого запроса, чтение страниц и правил, черновики `API-wikisvc.proposals.*`, `/raw`, `/findings` | ответ с ошибкой ядра пробрасывается с его кодом; тело без `error` → ERR-wiki_service (502); сетевой сбой не перехватывается — 500 (RISK в отчёте); таймаут 60s, повторов нет |
| EXT-llm-server | `POST {base_url}/chat/completions` (OpenAI-совместимый), JSON по схеме | ERR-model_unavailable (502); `structured` повторяет до `CFG-wikiagent.limits.retries` раз; таймаут `CFG-wikiagent.models.*` |
| LIB-wikisvc-core | прямой импорт кода ядра (ниже) | — (один пакет, одна сборка) |
| `API-wikisvc.knowledge.ask`, `API-wikisvc.knowledge.similar`, `API-wikisvc.knowledge.topics`, `API-wikisvc.knowledge.domains`, `API-wikisvc.knowledge.verdicts`, `API-wikisvc.knowledge.novelty` (draft) | v3: привязка к хабу, хабы домена, кандидаты в дубликаты, запись вердиктов и novelty | ERR-embeddings_unavailable от ядра → окно не обрабатывается, задача `failed`, resume продолжит с окна |
| судья MOD-wikiagent.judge: ONNX в процессе (DEP-py-onnxruntime, DEP-py-tokenizers), LLM-ступень — EXT-llm-server (draft) | v3: вердикт пары фактов (FLOW-dedup-judge) | ingest: задача не падает, кандидат с kNN-соседями → `queue` + `W_POSSIBLE_DUPLICATE`; heal: пары фактов пропускаются (`judge_unavailable` в отчёте); novelty: `paused` |

Импорт из LIB-wikisvc-core (без обхода HTTP к данным, кроме CLI-wikiagent.check):

| символ | откуда | где используется |
|---|---|---|
| `WikiError`, `not_found` | `wikisvc.domain.errors` | ошибки всего агента (CLS-wikisvc-core.WikiError) |
| `Principal` | `wikisvc.domain.models` | API-wikiagent.docs-audit.* (CLS-wikisvc-core.Principal) |
| `ALLOWLISTS`, `CONTRACTS`, `REQUIRED`, `definitions` | `wikisvc.tool_contracts` | инструменты модели, `CLS-wikiagent.execute` |
| `now` | `wikisvc.storage.state_db` | метки времени в TBL-wikiagent.agent.* |
| `AGENT_SCHEMA`, `refuse_newer`, `stamp` | `wikisvc.storage.db_version` | версия схемы agent.db |
| `paginate` | `wikisvc.services.pages` | API-wikiagent.chat.sessions.list |
| `sections`, `apply_patch`, `section_span`, `load_yaml` | `wikisvc.domain.markdown`, `wikisvc.domain.patch` | `CLS-wikiagent.Reviser`, конфиг, eval |
| `secret_kinds`, `overlaps`, `normalize_quote`, `quote_too_short` | `wikisvc.domain.secrets`, `.validate`, `.markdown` | MOD-wikiagent.jobs, MOD-wikiagent.heal |
| `load_roles` | `wikisvc.services.sessions` | `CLS-wikiagent.check_authentication` |

## Данные

- owns: TBL-wikiagent.agent.* (детали — `data.md`)
- store: RES-agent-db (`agent.db` в `CFG-wikiagent.WIKIAGENT_STATE_DIR`, каталог 0700, файл 0600)
- migrations: нет отдельного инструмента; `CREATE TABLE IF NOT EXISTS` при старте `CLS-wikiagent.AgentState`, версия — `PRAGMA user_version`, более новая схема → ERR-schema_newer
- reads foreign data: только через `API-wikisvc.*`; исключение — CLI-wikiagent.check читает таблицу `tokens` в RES-state-db только на чтение

## Устройство

- modules: MOD-wikiagent.api, MOD-wikiagent.cli, MOD-wikiagent.client, MOD-wikiagent.models,
  MOD-wikiagent.state, MOD-wikiagent.tools, MOD-wikiagent.chat, MOD-wikiagent.planner,
  MOD-wikiagent.jobs, MOD-wikiagent.heal, MOD-wikiagent.config, MOD-wikiagent.prompts;
  v3 (planned): MOD-wikiagent.ingest, MOD-wikiagent.judge (детали — `code.md`)
- jobs: JOB-wikiagent.ingest-book, JOB-wikiagent.heal, JOB-wikiagent.docs-audit, JOB-wikiagent.scheduler;
  v3 (planned): JOB-wikiagent.novelty-scan (детали — `runtime.md`)
- config: CFG-wikiagent.* (детали — `runtime.md`)
- prompts: PRM-wikiagent.* (детали — `ai.md`)
- invariants: INV-agent-clearance-ceiling, INV-human-decides, INV-untrusted-external, INV-404-not-403, INV-single-node;
  v3: INV-claim-minimal, INV-invalidate-not-delete, INV-one-domain-per-page

## Развёртывание

- runs on: RES-host, ENV-prod; в образе RES-container-image рядом с SVC-wikisvc
- scaling: один экземпляр (INV-single-node): блокировки сессий, очередь джоб и шлюз модели живут в памяти процесса
- health: отдельного эндпоинта нет; готовность проверяет CLI-wikiagent.check (вызывает API-wikiagent.jobs.list)

## Политики

- rule-arch-outgoing-call-resilience, rule-arch-structured-logging, rule-arch-single-scheduler,
  rule-arch-stateless-replicas, rule-stack-python-async, rule-stack-postgres-default,
  rule-secrets-agent-never-prints, rule-secrets-required-at-start, rule-test-mock-only-boundaries;
  v3: rule-stack-new-tech-consent (судья), rule-stack-llm-providers, rule-test-llm-fake,
  rule-arch-idempotent-consumers, rule-arch-no-overengineering, rule-stack-one-tool-per-job
