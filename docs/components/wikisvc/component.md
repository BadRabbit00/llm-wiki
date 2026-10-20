# wikisvc

> Карточка компонента. Агент читает этот файл первым, когда задача касается HTTP API вики.

### SVC-wikisvc — HTTP API вики `/api/v1`
status: implemented | kind: http-service | lang: LANG-python

- purpose: отдаёт HTTP API `/api/v1` над ядром LIB-wikisvc-core — чтение страниц, правил и графа,
  поиск, сборку блока политик, предложения и их ревью, сырьё, находки, аудит и выпуск сессий.
- not responsible for: не вызывает LLM и не делает исходящих сетевых запросов (это SVC-wikiagent);
  не ходит в OIDC (вход человека — SVC-wiki-ui, сюда приходит готовый `POST /sessions`);
  MCP-инструменты — SVC-wikisvc-mcp (здесь только монтируется `/mcp`), команды — SVC-wikisvc-cli;
  бизнес-логика, хранилище и индекс — LIB-wikisvc-core, роутеры её только вызывают.
- path: `src/wikisvc/main.py`, `src/wikisvc/api/`, `src/wikisvc/config.py`
- manifest: `pyproject.toml`, lock: `flake.lock` (Python-зависимости приходят из nixpkgs)
- build: TOOL-nix; `nix build .#default` (пакет `wikisvc`, тот же для SVC-wikiagent)
- run locally: `nix develop -c wikisvc serve` (порт 8787, `127.0.0.1`, один воркер uvicorn)
- test: `nix develop -c pytest -q`
- entrypoints: `src/wikisvc/main.py` — фабрика `create_app(settings)`; uvicorn запускает её
  с `factory=True` из CLI-wikisvc-cli.serve
- framework: DEP-py-fastapi
- deps: DEP-py-uvicorn, DEP-py-pydantic, DEP-py-pydantic-settings, DEP-py-python-multipart
  (полный список — `stack/dependencies.md`)
- changed: 2026-10-20 v3 (planned): ещё отдаёт слой знаний (API-wikisvc.knowledge.*); через LIB-wikisvc-core
  делает исходящие запросы к локальным RES-embeddings-server и RES-reranker-server (loopback) — это не LLM, граница
  SEC-embeddings-boundary (решение Q-kb-core-outbound-embeddings); LLM по-прежнему не вызывает.

## Что компонент даёт другим

- API: API-wikisvc.* (67 эндпоинтов, детали — `contracts.md`)
- knowledge API (draft): API-wikisvc.knowledge.* — brief, ask, fact, topic, topics, expand, similar, tech, why, questions, domains,
  verdicts, novelty (13 эндпоинтов, ROLE-reader; `similar`, `verdicts`, `novelty` — ROLE-writer; ответы в бюджете
  токенов до CFG-wikisvc.TOOL_RESPONSE_CAP); заменит
  API-wikisvc.search и API-wikisvc.context: `deprecated` после переезда клиентов, удаление — в следующей мажорной версии
  (решение Q-kb-search-context-deprecation)
- DTO: DTO-wikisvc.*
- MCP по HTTP: при CFG-wikisvc.MCP_HTTP_ENABLED монтирует приложение SVC-wikisvc-mcp на
  CFG-wikisvc.MCP_HTTP_PATH в том же процессе и порту.

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| LIB-wikisvc-core | вся логика: `Runtime` со службами, аутентификация, хранилище, индекс | без него приложение не собирается |
| RES-wiki-repo | контент вики (git, CFG-wikisvc.WIKI_ROOT) | старт падает |
| RES-state-db | токены, предложения, аудит, лимиты, люди | старт падает |
| RES-index-db | поиск, граф, `index_commit` для health | старт падает, индекс пересобирается при старте |
| RES-agent-db | только чтение числа незавершённых джоб для `API-wikisvc.inbox` | `jobs.available=false` |
| RES-embeddings-server (draft) | через LIB-wikisvc-core: векторы запроса и индекса (CFG-wikisvc.EMBEDDINGS_URL) | урезанный режим: только BM25 и явные рёбра, `degraded: true` в ask и health, `status` остаётся `ok` (решение Q-kb-embeddings-degraded) |
| RES-reranker-server (draft) | через LIB-wikisvc-core: reranker шага L0 → L1 в ask (CFG-wikisvc.RERANKER_URL) | шаг пропускается без ошибки |

## Данные

- owns: ничего; таблицы и файлы — у LIB-wikisvc-core (`TBL-wikisvc-core.*`, `BKT-wikisvc-core.*`,
  детали — `components/wikisvc-core/data.md`)
- store: RES-state-db, RES-index-db, RES-wiki-repo — через LIB-wikisvc-core
- migrations: схему SQLite создаёт LIB-wikisvc-core при открытии базы; отдельного шага нет
- reads foreign data: `agent.db` компонента SVC-wikiagent читается напрямую, только чтение
  (`mode=ro`), в `API-wikisvc.inbox` — RISK-wikisvc-router-sql

## Устройство

- modules: MOD-wikisvc.main, MOD-wikisvc.api (детали — `code.md`)
- jobs: своих нет; при старте синхронно: переиндексация, истечение предложений по
  CFG-wikisvc.PROPOSAL_TTL_DAYS, удаление истёкших SSO-сессий, восстановление извлечений
  (JOB-wikisvc-core.extract-worker) — детали в `runtime.md`
- config: CFG-wikisvc.* (детали — `runtime.md`)

## Развёртывание

- runs on: RES-host, ENV-dev, ENV-prod
- unit: образ RES-container-image (тот же образ, что у SVC-wiki-ui и SVC-wikiagent),
  env-файл `deploy/linux/service.env`
- scaling: один процесс и один воркер (INV-single-node): SQLite, файловая блокировка записи,
  счётчик подавления логов в памяти `BodyLimit`
- health: OBS-wikisvc.health (`GET /api/v1/health`, без токена)

## Безопасность

- аутентификация: Bearer-токен из RES-state-db (SEC-authn) до чтения тела (INV-auth-before-body);
  анонимный доступ — CFG-wikisvc.ANONYMOUS_ACCESS (INV-anonymous-ceiling, SEC-anonymous)
- скрытое по допуску отдаётся как `404` (INV-404-not-403); роли — ROLE-reader … ROLE-admin
- v3 (planned): допуск режет факты, хабы и рёбра до обхода графа и не светит скрытое в `omitted_ids`
  (SEC-graph-clearance-mask); текст restricted-страниц уходит только в локальный сервер эмбеддингов (SEC-embeddings-boundary):
  URL — только loopback-литерал, без прокси из окружения и редиректов
- v3 (planned): лимит запросов по стоимости (SEC-rate-limit): `ask` = 1 + эмбеддинг, `similar` (ROLE-writer) = число
  текстов, `expand` = `ids` × `depth`; общий лимит для анонимов; семафор вызовов эмбеддингов в CLS-wikisvc-core.Embeddings
- решения ревью — только человек (SEC-principal-kind#human, INV-human-decides)
- CORS: только явные origin из CFG-wikisvc.CORS_ORIGINS, без credentials; `*` запрещён при старте

## Политики

- rule-arch-config-module, rule-deploy-config-from-env — все настройки в `Settings` из env
- rule-arch-domain-errors — `WikiError` ядра переводится в HTTP одним обработчиком
- rule-arch-permissions-placement — роль проверяет зависимость `Authorize`, объект — ядро
- rule-auth-existing-scheme — своя схема: непрозрачные Bearer-токены в SQLite, не JWT
- rule-auth-no-bypass-mode, rule-arch-structured-logging, rule-stack-python-async,
  rule-arch-orm-not-raw-sql — есть расхождения, см. риски в отчёте
- v3 (planned): rule-arch-outgoing-call-resilience — таймаут и повторы к RES-embeddings-server, урезанный режим;
  rule-arch-health-readiness — health не проверяет сервер эмбеддингов вживую; rule-arch-strict-typing,
  rule-secrets-env-example-reference, rule-secrets-required-at-start — новые CFG без секретов, ключа к серверам нет (решение Q-kb-embeddings-api-key)
