# wikisvc: фоновые задачи и настройки

## Фоновые задачи

Своих фоновых и периодических задач у SVC-wikisvc нет. При старте (lifespan CLS-wikisvc.create_app)
синхронно, под блокировкой записи: переиндексация, перевод в `abandoned` предложений старше
CFG-wikisvc.PROPOSAL_TTL_DAYS, удаление истёкших SSO-сессий; затем восстановление незаконченных
извлечений. Истечение предложений повторяется при каждом `API-wikisvc.proposals.create` — это не
JOB, расписания нет. Извлечение текста книг запускает `API-wikisvc.raw.extract` в процессе сервиса —
это JOB-wikisvc-core.extract-worker ядра.

- changed: 2026-10-20 v3 (planned): при старте ещё self-test эмбеддингов (если CFG-wikisvc.EMBEDDINGS_ENABLED;
  провал — урезанный режим, а не отказ старта; решение Q-kb-embeddings-degraded) и запуск JOB-wikisvc-core.delivery-flush
  в процессе (период CFG-wikisvc.DELIVERY_FLUSH_SECONDS); при остановке очередь выдачи сбрасывается до закрытия баз
  (RISK-kb-process-memory-state). Пересчёт векторов — в переиндексации (JOB-wikisvc-core.embed-index).

## Настройки

Все настройки читает класс `Settings` (`src/wikisvc/config.py`, DEP-py-pydantic-settings) из
переменных окружения с именем поля в верхнем регистре; `.env` сам не загружается. Тот же `Settings`
используют SVC-wikisvc-cli и SVC-wikisvc-mcp. Ошибка значения — отказ старта с именем поля.
Проверки при старте: `STATE_DIR` и `INDEX_DIR` — разные и вне `WIKI_ROOT`; `ROLES_FILE` вне
`WIKI_ROOT`; формат `STATUS_BOOST`; `CORS_ORIGINS` без `*`. Секретов среди настроек нет (SEC-secrets):
токены живут в RES-state-db, а `WIKI_TOKEN` читают только CLI и MCP.

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-wikisvc.WIKI_ROOT | SVC-wikisvc | env | string (путь) | нет | да | нет | git-репозиторий контента RES-wiki-repo | implemented |
| CFG-wikisvc.STATE_DIR | SVC-wikisvc | env | string (путь) | нет | да | нет | RES-state-db, блокировка записи, worktree, библиотека | implemented |
| CFG-wikisvc.INDEX_DIR | SVC-wikisvc | env | string (путь) | нет | да | нет | RES-index-db | implemented |
| CFG-wikisvc.BIND_HOST | SVC-wikisvc | env | string | `127.0.0.1` | нет | нет | адрес uvicorn и MCP по HTTP | implemented |
| CFG-wikisvc.BIND_PORT | SVC-wikisvc | env | int32 1..65535 | `8787` | нет | нет | порт uvicorn | implemented |
| CFG-wikisvc.LOG_LEVEL | SVC-wikisvc | env | enum(DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL) | `INFO` | нет | нет | уровень логгера `wikisvc` и uvicorn | implemented |
| CFG-wikisvc.CORS_ORIGINS | SVC-wikisvc | env | string (origin через запятую) | пусто — CORS выключен | нет | нет | CORS без credentials; `*` — отказ старта | implemented |
| CFG-wikisvc.ANONYMOUS_ACCESS | SVC-wikisvc | env | bool | `false` | нет | нет | запрос без `Authorization` получает анонимного принципала (SEC-anonymous) | implemented |
| CFG-wikisvc.ANONYMOUS_NAME | SVC-wikisvc | env | string `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` | `anonymous` | нет | нет | имя анонима в аудите | implemented |
| CFG-wikisvc.ANONYMOUS_ROLE | SVC-wikisvc | env | enum(reader\|writer) | `writer` | нет | нет | роль анонима (INV-anonymous-ceiling) | implemented |
| CFG-wikisvc.ANONYMOUS_CLEARANCE | SVC-wikisvc | env | enum(public\|internal) | `internal` | нет | нет | допуск анонима (INV-anonymous-ceiling) | implemented |
| CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME | SVC-wikisvc | env | string | пусто — выпуск сессий выключен | нет | нет | имя токена, которому разрешён только `API-wikisvc.sessions.create` | implemented |
| CFG-wikisvc.SESSION_TTL_HOURS | SVC-wikisvc | env | int32 ≥ 1 | `12` | нет | нет | срок SSO-сессии | implemented |
| CFG-wikisvc.ROLES_FILE | SVC-wikisvc | env | string (путь) | `/etc/llm-wiki/roles.yaml` | при выпуске сессий | нет | сопоставление групп IdP ролям, FMT-wikisvc-core.roles-file | implemented |
| CFG-wikisvc.MCP_HTTP_ENABLED | SVC-wikisvc | env | bool | `false` | нет | нет | монтирует SVC-wikisvc-mcp в этот процесс | implemented |
| CFG-wikisvc.MCP_HTTP_PATH | SVC-wikisvc | env | string, начинается с `/` | `/mcp` | нет | нет | путь MCP по HTTP | implemented |
| CFG-wikisvc.MCP_PROFILE | SVC-wikisvc | env | string | `coding` | нет | нет | набор MCP-инструментов (v3 planned: enum(coding\|full\|knowledge), профиль `knowledge` — CLS-wikisvc-mcp.TOOL_PROFILES) | implemented |
| CFG-wikisvc.WIKIAGENT_STATE_DIR | SVC-wikisvc | env | string? (путь) | нет | нет | нет | откуда `API-wikisvc.inbox` читает `agent.db` | implemented |
| CFG-wikisvc.RATE_LIMIT_PER_MIN | SVC-wikisvc | env | int32 ≥ 0 | `0` — без лимита | нет | нет | запросов в минуту на токен, сверх — ERR-rate_limit | implemented |
| CFG-wikisvc.LOCK_TIMEOUT | SVC-wikisvc | env | float64 > 0 (секунды) | `30` | нет | нет | ожидание блокировки записи, затем ERR-lock_timeout | implemented |
| CFG-wikisvc.PROPOSAL_TTL_DAYS | SVC-wikisvc | env | int32 ≥ 1 | `14` | нет | нет | через сколько дней без изменений предложение `abandoned` | implemented |
| CFG-wikisvc.MAX_UPLOAD_MB | SVC-wikisvc | env | int32 1..1024 | `25` | нет | нет | размер сырья, кроме `library` | implemented |
| CFG-wikisvc.MAX_LIBRARY_UPLOAD_MB | SVC-wikisvc | env | int32 1..1024 | `200` | нет | нет | размер книги `library` | implemented |
| CFG-wikisvc.ALLOWED_RAW_EXT | SVC-wikisvc | env | string (через запятую) | `pdf,epub,docx,xlsx,md,txt,csv,json,yaml,yml,png,jpg,jpeg` | нет | нет | разрешённые расширения сырья | implemented |
| CFG-wikisvc.EXTRACT_TIMEOUT_SECONDS | SVC-wikisvc | env | int32 1..300 | `15` | нет | нет | таймаут одного процесса извлечения текста | implemented |
| CFG-wikisvc.EXTRACT_MEMORY_MB | SVC-wikisvc | env | int32 128..4096 | `512` | нет | нет | лимит памяти процесса извлечения | implemented |
| CFG-wikisvc.EXTRACT_MAX_CHARS | SVC-wikisvc | env | int32 1000..10000000 | `2000000` | нет | нет | максимум символов текста из одного файла | implemented |
| CFG-wikisvc.EXTRACT_JOB_TIMEOUT | SVC-wikisvc | env | int32 1..7200 (секунды) | `600` | нет | нет | общий срок фонового извлечения книги | implemented |
| CFG-wikisvc.EXTRACT_JOB_MAX_CHARS | SVC-wikisvc | env | int32 1000..200000000 | `50000000` | нет | нет | максимум символов текста книги | implemented |
| CFG-wikisvc.OUTLINE_FALLBACK_PAGES | SVC-wikisvc | env | int32 1..100 | `15` | нет | нет | страниц в главе запасного оглавления | implemented |
| CFG-wikisvc.CONTEXT_BUDGET_DEFAULT | SVC-wikisvc | env | int32 1..60000 | `12000` | нет | нет | `budget_chars` по умолчанию в `API-wikisvc.context` | implemented |
| CFG-wikisvc.CHARS_PER_TOKEN | SVC-wikisvc | env | float64 1..10 | `2.5` | нет | нет | оценка токенов в `API-wikisvc.policies.compile` (v3 planned: заменяется CFG-wikisvc.CHARS_PER_TOKEN_LATIN и CFG-wikisvc.CHARS_PER_TOKEN_CYRILLIC, при реализации — `deprecated`) | implemented |
| CFG-wikisvc.POLICY_CATEGORY_ORDER | SVC-wikisvc | env | string (через запятую) | `code-style,architecture,logging,errors,security,testing,stack,git,build-ci,docs,process` | нет | нет | порядок категорий в блоке политик | implemented |
| CFG-wikisvc.STATUS_BOOST | SVC-wikisvc | env | string `verified=…,draft=…,outdated=…` | `verified=1.2,draft=1.0,outdated=0.5` | нет | нет | веса статуса в поиске, каждый 0..100 | implemented |
| CFG-wikisvc.RELATION_PRIORITY | SVC-wikisvc | env | string (через запятую) | `governed_by,depends_on,uses,reads,writes,automates` | нет | нет | порядок связей при сборке контекста | implemented |
| CFG-wikisvc.SECRET_ENTROPY_THRESHOLD | SVC-wikisvc | env | float64 > 0 | `4.5` | нет | нет | порог энтропии детектора секретов (SEC-secret-detector) | implemented |

### Настройки слоя знаний v3 (planned)

Читаются тем же CLS-wikisvc.Settings (rule-arch-config-module, rule-deploy-config-from-env); каждая — в
`deploy/linux/.env.example` и `deploy/linux/service.env` в том же изменении, что и код (rule-secrets-env-example-reference).
Проверки при старте с отказом и именем поля: при `EMBEDDINGS_ENABLED` заданы `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL`,
`EMBEDDINGS_DIM`; при `ASK_RERANK_ENABLED` — `RERANKER_URL`, `RERANKER_MODEL`; `ASK_BUDGET_DEFAULT` и `BRIEF_BUDGET_MAX`
не больше `TOOL_RESPONSE_CAP`; хост `EMBEDDINGS_URL` и `RERANKER_URL` — только литерал loopback (`127.0.0.0/8`, `::1`),
без DNS-имён и userinfo; клиент не берёт прокси из окружения (`trust_env=False`) и не следует редиректам
(SEC-embeddings-boundary, CLS-wikisvc-core.Embeddings). Секретов нет: серверы эмбеддингов и reranker локальные, без ключа (SEC-embeddings-boundary, решение Q-kb-embeddings-api-key).
Значения с пометкой «решение» — не из ТЗ, приняты владельцем (Q-kb-wikisvc-defaults).

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-wikisvc.EMBEDDINGS_ENABLED | SVC-wikisvc | env | bool | `true` (решение Q-kb-core-outbound-embeddings) | нет | нет | векторы семян, `similar`-рёбра и dense-prior; `false` — только BM25 и явные рёбра (ADR-0018) | planned |
| CFG-wikisvc.EMBEDDINGS_URL | SVC-wikisvc | env | string (URL OpenAI-совместимого `/v1/embeddings`) | `http://127.0.0.1:18090` (RES-embeddings-server) | при `EMBEDDINGS_ENABLED`: пустое значение — отказ старта | нет | RES-embeddings-server; только loopback-литерал, внешние провайдеры запрещены (SEC-embeddings-boundary) | planned |
| CFG-wikisvc.EMBEDDINGS_MODEL | SVC-wikisvc | env | string | нет | при `EMBEDDINGS_ENABLED` | нет | имя модели в запросе и в TBL-wikisvc-core.index.embeddings (по ТЗ — MDL-bge-m3); смена — полный пересчёт векторов | planned |
| CFG-wikisvc.EMBEDDINGS_POOLING | SVC-wikisvc | env | enum(cls\|mean\|last) | `cls` (ТЗ §5) | нет | нет | ожидаемый pooling сервера; неверный pooling ловит self-test (CLS-wikisvc-core.Embeddings) | planned |
| CFG-wikisvc.EMBEDDINGS_DIM | SVC-wikisvc | env | int32 ≥ 1 | нет | при `EMBEDDINGS_ENABLED` | нет | размерность векторов; self-test сверяет длину ответа | planned |
| CFG-wikisvc.EMBEDDINGS_TIMEOUT_SECONDS | SVC-wikisvc | env | float64 > 0 | `5` (решение Q-kb-wikisvc-defaults, rule-arch-outgoing-call-resilience) | нет | нет | таймаут одного вызова `EMBEDDINGS_URL` и `RERANKER_URL` | planned |
| CFG-wikisvc.EMBEDDINGS_RETRIES | SVC-wikisvc | env | int32 0..3 | `1` (решение Q-kb-wikisvc-defaults) | нет | нет | повторы при таймауте и `5xx`, затем урезанный режим | planned |
| CFG-wikisvc.RERANKER_URL | SVC-wikisvc | env | string (URL) | `http://127.0.0.1:18091` (RES-reranker-server) | при `ASK_RERANK_ENABLED`: пустое значение — отказ старта | нет | cross-encoder шага L0 → L1 в API-wikisvc.knowledge.ask; только loopback-литерал; reranker в ядре (решение Q-kb-reranker-placement) | planned |
| CFG-wikisvc.RERANKER_MODEL | SVC-wikisvc | env | string? | нет | при `ASK_RERANK_ENABLED` | нет | имя модели reranker (MDL-bge-reranker-v2-m3 или MDL-qwen3-reranker-0.6b) | planned |
| CFG-wikisvc.ASK_RERANK_ENABLED | SVC-wikisvc | env | bool | `true` (решение Q-kb-reranker-placement, с этапа 2) | нет | нет | reranker в ask; умолчание параметра `rerank` | planned |
| CFG-wikisvc.ASK_SEEDS | SVC-wikisvc | env | int32 ≥ 1 | `8` (ТЗ §7.2) | нет | нет | число семян ask после RRF | planned |
| CFG-wikisvc.ASK_EXPANSION_RATIO | SVC-wikisvc | env | float64 ≥ 1 | `1.5` (ТЗ §7.2) | нет | нет | отрыв top-1 от top-2, при котором PPR пропускается | planned |
| CFG-wikisvc.ASK_EXPANSION_MIN_HUBS | SVC-wikisvc | env | int32 ≥ 2 | `3` (ТЗ §7.2) | нет | нет | семена из стольких хабов и больше — расширение по графу | planned |
| CFG-wikisvc.ASK_BUDGET_DEFAULT | SVC-wikisvc | env | int32 ≥ 1 | `1500` (NFR-ask-budget) | нет | нет | `budget_tokens` ask по умолчанию | planned |
| CFG-wikisvc.BRIEF_BUDGET_MAX | SVC-wikisvc | env | int32 ≥ 1 | `2500` (NFR-brief-budget) | нет | нет | потолок `budget_tokens` brief | planned |
| CFG-wikisvc.TOOL_RESPONSE_CAP | SVC-wikisvc | env | int32 1..25000 | `8000` (NFR-tool-response-cap) | нет | нет | потолок ответа API-wikisvc.knowledge.* и читающих инструментов SVC-wikisvc-mcp | planned |
| CFG-wikisvc.PPR_ALPHA | SVC-wikisvc | env | float64, 0 < α < 1 | `0.5` (ADR-0020) | нет | нет | вероятность возврата PPR | planned |
| CFG-wikisvc.PPR_TOL | SVC-wikisvc | env | float64 > 0 | `1e-6` (ТЗ §7.2) | нет | нет | останов PPR по ‖Δπ‖₁ | planned |
| CFG-wikisvc.PPR_DENSE_PRIOR | SVC-wikisvc | env | float64 ≥ 0 | `0.05` (ТЗ §7.2) | нет | нет | вес cos(q, v) всех узлов в reset-векторе; без эмбеддингов не применяется | planned |
| CFG-wikisvc.SIMILAR_THRESHOLD | SVC-wikisvc | env | float64 0..1 | `0.80` (ТЗ §4) | нет | нет | порог косинуса `claim`-векторов для `similar` в TBL-wikisvc-core.index.soft_edges | planned |
| CFG-wikisvc.CHARS_PER_TOKEN_LATIN | SVC-wikisvc | env | float64 1..10 | `4.0` (NFR-token-estimate) | нет | нет | символов на токен для текста без кириллицы (CLS-wikisvc-core.estimate_tokens) | planned |
| CFG-wikisvc.CHARS_PER_TOKEN_CYRILLIC | SVC-wikisvc | env | float64 1..10 | `3.0` (NFR-token-estimate) | нет | нет | символов на токен для текста с кириллицей | planned |
| CFG-wikisvc.DELIVERY_FLUSH_SECONDS | SVC-wikisvc | env | float64 > 0 | `5` (решение Q-kb-wikisvc-defaults) | нет | нет | период сброса CLS-wikisvc-core.DeliveryQueue (JOB-wikisvc-core.delivery-flush) | planned |
| CFG-wikisvc.DELIVERY_FLUSH_BATCH | SVC-wikisvc | env | int32 ≥ 1 | `500` (решение Q-kb-wikisvc-defaults) | нет | нет | сброс очереди раньше срока при стольких записях (ТЗ §11.5) | planned |
| CFG-wikisvc.INDEX_READ_CONNECTIONS | SVC-wikisvc | env | int32 ≥ 1 | `4` (решение Q-kb-wikisvc-defaults) | нет | нет | read-соединений CLS-wikisvc-core.ConnectionPool к RES-index-db (плюс одно на запись) | planned |

Значения для прода — `deploy/linux/service.env` (ENV-prod), для разработки — `shellHook` devShell
задаёт `WIKI_ROOT`, `STATE_DIR`, `INDEX_DIR`, `WIKIAGENT_STATE_DIR` (ENV-dev).
