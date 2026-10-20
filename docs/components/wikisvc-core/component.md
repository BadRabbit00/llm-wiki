# wikisvc-core

> Карточка компонента. Агент читает этот файл первым, когда задача касается ядра `wikisvc`.

### LIB-wikisvc-core — Ядро вики: домен, git-хранилище, индекс и сценарии
status: implemented | kind: lib | lang: LANG-python

- purpose: детерминированная бизнес-логика вики компании — страницы и правила в git, предложения с ревью человеком, индекс и поиск, компилятор блока политик; одна реализация для HTTP API, MCP, CLI и `wikiagent`.
- not responsible for: не вызывает LLM (INV-core-deterministic) и не делает исходящих сетевых запросов; не знает про HTTP (запросы, ответы, cookies, заголовки — в SVC-wikisvc); не читает переменные окружения сам — получает `Settings` из `src/wikisvc/config.py`; не планирует фоновые джобы агента (SVC-wikiagent).
- path: `src/wikisvc/domain/`, `src/wikisvc/storage/`, `src/wikisvc/index/`, `src/wikisvc/services/`, `src/wikisvc/template/`
- manifest: `pyproject.toml` (пакет `wikisvc` вместе с `wikiagent`), lock: нет lock-файла — версии зависимостей пинует `flake.lock`
- build: TOOL-nix, TOOL-hatchling; собирается в составе пакета `wikisvc`
- test: `nix develop -c pytest -q`; линтер `nix develop -c ruff check src/wikisvc`; типы TOOL-mypy (`strict = true`)
- entrypoints: нет своего процесса; `python -m wikisvc.services.extract_worker` — одноразовый процесс разбора документа (JOB-wikisvc-core.extract-worker)
- framework: DEP-py-pydantic
- deps: DEP-py-ruamel.yaml, DEP-py-pystemmer, DEP-py-pypdf, DEP-py-python-docx; из системы — DEP-nix-git (бинарник `git`), DEP-nix-sqlite (SQLite с FTS5 через `sqlite3` стандартной библиотеки)
- changed: 2026-10-20 v3 (planned): слой знаний (ТЗ `ref/knowledge-layer-spec.md`) — типы fact/topic/tech/question и домены, связи с весами, векторы и мягкие рёбра в индексе, снимок графа с PPR, `ask`, brief, чтение знаний, маршрутизация ревью фактов, lint §9, оптимизации §11.1–11.7; deps += DEP-py-numpy, DEP-py-scipy (согласие получено — решение Q-kb-numpy-scipy-consent), DEP-py-httpx (уже в пакете, в ядре — впервые); ядро впервые делает исходящий вызов — только к EXT-embeddings-server и reranker на loopback; принято исключение к ADR-0003 и правилу проекта «ядро без сети», формулировку правила правит человек (решение Q-kb-core-outbound-embeddings); детерминизм — при фиксированных модели и индексе (INV-core-deterministic)

## Что компонент даёт другим

- classes: CLS-wikisvc-core.Runtime (точка сборки), CLS-wikisvc-core.WikiError, CLS-wikisvc-core.Principal, CLS-wikisvc-core.Page, CLS-wikisvc-core.Proposal, CLS-wikisvc-core.LintIssue, CLS-wikisvc-core.parse_page, CLS-wikisvc-core.validate_set, CLS-wikisvc-core.secret_kinds, CLS-wikisvc-core.Sessions, CLS-wikisvc-core.export_block (полный список — `code.md`)
- formats: FMT-wikisvc-core.page, FMT-wikisvc-core.rule, FMT-wikisvc-core.page-type, FMT-wikisvc-core.relations, FMT-wikisvc-core.scopes, FMT-wikisvc-core.profiles, FMT-wikisvc-core.project-template, FMT-wikisvc-core.policy-block, FMT-wikisvc-core.roles-file
- v3 (planned): CLS-wikisvc-core.Knowledge, CLS-wikisvc-core.Brief, CLS-wikisvc-core.Ask, CLS-wikisvc-core.review_class; FMT-wikisvc-core.fact, FMT-wikisvc-core.topic, FMT-wikisvc-core.tech, FMT-wikisvc-core.question, FMT-wikisvc-core.source, FMT-wikisvc-core.domains, FMT-wikisvc-core.kb-eval, FMT-wikisvc-core.knowledge-block, FMT-wikisvc-core.workflow; DTO-wikisvc-core.* ответов знаний (`contracts.md`)
- data: TBL-wikisvc-core.state.*, TBL-wikisvc-core.index.* — чужие компоненты ходят в них только через классы ядра; исключение — SVC-wikiagent читает TBL-wikisvc-core.state.tokens только на чтение в проверке `auth_check`

| кто использует | что берёт |
|---|---|
| SVC-wikisvc | CLS-wikisvc-core.Runtime и все сервисы, CLS-wikisvc-core.WikiError для ответа об ошибке |
| SVC-wikisvc-mcp | те же сервисы через CLS-wikisvc-core.Runtime |
| SVC-wikisvc-cli | CLS-wikisvc-core.Runtime, CLS-wikisvc-core.initialize, CLS-wikisvc-core.Auth, CLS-wikisvc-core.export_block, CLS-wikisvc-core.upgrade_schema, CLS-wikisvc-core.repair_worktrees |
| SVC-wikiagent | доменные функции и модели (`domain/errors.py`, `markdown.py`, `models.py`, `patch.py`, `secrets.py`, `validate.py`), `storage/state_db.now`, `storage/db_version`, `services/sessions.load_roles` |

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| RES-wiki-repo | git-репозиторий контента (`WIKI_ROOT`) | старт падает; запись — ERR-git_dirty / ERR-git_merging при грязном или сливающемся `main` |
| RES-state-db | `state.db` в `STATE_DIR` | старт падает; база новее кода — ERR-schema_newer |
| RES-index-db | `wiki.db` в `INDEX_DIR` | старт падает; SQLite без FTS5 — ERR-fts5_missing; индекс новее кода можно выбросить и собрать заново |
| `git` в `PATH` | коммиты, worktree, слияния | любая запись падает с ошибкой subprocess |
| EXT-embeddings-server (v3 planned) | векторы страниц и запроса (CLS-wikisvc-core.Embeddings, MDL-bge-m3) | не роняет старт: ERR-embeddings_unavailable в лог и health, `ask` — только BM25, без `similar` и dense-prior; JOB-wikisvc-core.embed-index повторит при следующем reindex |

## Данные

- owns: TBL-wikisvc-core.state.*, TBL-wikisvc-core.index.*, BKT-wikisvc-core.wiki-repo, BKT-wikisvc-core.worktrees, BKT-wikisvc-core.library, BKT-wikisvc-core.extract (детали — `data.md`)
- store: RES-wiki-repo, RES-state-db, RES-index-db
- migrations: отдельного инструмента нет — `CREATE TABLE IF NOT EXISTS` и `ALTER TABLE ADD COLUMN` при каждом открытии базы в CLS-wikisvc-core.StateDB и CLS-wikisvc-core.IndexDB; версия схемы — `PRAGMA user_version` (CLS-wikisvc-core.refuse_newer); контент вики — CLS-wikisvc-core.upgrade_schema по команде администратора
- reads foreign data: нет

## Устройство

- modules: MOD-wikisvc-core.domain, MOD-wikisvc-core.storage, MOD-wikisvc-core.index, MOD-wikisvc-core.services, MOD-wikisvc-core.template (детали — `code.md`)
- jobs: JOB-wikisvc-core.extract-worker; v3 (planned): JOB-wikisvc-core.embed-index, JOB-wikisvc-core.delivery-flush (детали — `runtime.md`)
- config: своих настроек не читает; значения приходят из `Settings` SVC-wikisvc (`components/wikisvc/runtime.md`)

## Инварианты, которые держит ядро

| инвариант | где |
|---|---|
| INV-human-decides | CLS-wikisvc-core.require_human в CLS-wikisvc-core.Proposals.decide, CLS-wikisvc-core.Proposals.revert, CLS-wikisvc-core.review, CLS-wikisvc-core.Findings |
| INV-no-self-review | CLS-wikisvc-core.Proposals.decide |
| INV-agent-rule-inert | CLS-wikisvc-core.Proposals._put, CLS-wikisvc-core.Policies |
| INV-single-node | CLS-wikisvc-core.write_lock |
| INV-untrusted-external | CLS-wikisvc-core.Raw, JOB-wikisvc-core.extract-worker |
| INV-404-not-403 | CLS-wikisvc-core.Pages, CLS-wikisvc-core.GraphStore, CLS-wikisvc-core.Raw |
| INV-policy-block-only | CLS-wikisvc-core.export_block |
| INV-secrets-never-stored | CLS-wikisvc-core.secret_kinds в CLS-wikisvc-core.validate_page и при создании предложений, комментариев, находок |
| INV-anonymous-ceiling | CLS-wikisvc-core.Auth |
| INV-human-decides (без изменений) | CLS-wikisvc-core.review_class (INV-auto-class-scope) только сортирует и группирует: auto-блок предложения принимает человек одним действием через CLS-wikisvc-core.Proposals.decide (решение Q-kb-auto-accept-human-decides) |
| INV-claim-minimal, INV-one-domain-per-page (v3 planned) | CLS-wikisvc-core.validate_page (FMT-wikisvc-core.fact, FMT-wikisvc-core.domains) |
| INV-invalidate-not-delete (v3 planned) | CLS-wikisvc-core.Indexer: эффективный `outdated` по `valid_to`/`replaced_by`, файл не удаляется |
| INV-canonical-order (v3 planned) | CLS-wikisvc-core.Assemble, CLS-wikisvc-core.Brief |
| INV-rules-pushed-knowledge-pulled (v3 planned) | CLS-wikisvc-core.Brief отдельно от CLS-wikisvc-core.Policies; FMT-wikisvc-core.knowledge-block отдельно от блока политик |

## Развёртывание

- runs on: RES-host в процессах SVC-wikisvc, SVC-wikisvc-mcp, SVC-wikisvc-cli, SVC-wikiagent
- scaling: один хост — блокировка записи `fcntl.flock` в `STATE_DIR` (INV-single-node); несколько реплик на разных узлах не поддерживаются

## Политики

- rule-arch-strict-typing — mypy `strict` в `pyproject.toml`
- rule-arch-domain-errors — единое исключение CLS-wikisvc-core.WikiError
- rule-arch-dependency-direction, rule-arch-layers — `domain` → `storage` → `index` → `services`
- rule-arch-stateless-replicas, rule-arch-workers-parallel-safe — отступление: одноузловость
- rule-stack-postgres-default, rule-arch-orm-not-raw-sql, rule-arch-migrations-only — отступление: SQLite, сырой SQL, DDL при старте
- rule-stack-files-in-s3 — отступление: сырьё в git и `STATE_DIR/library`
- rule-secrets-never-in-artifacts — детектор CLS-wikisvc-core.secret_kinds не пускает секреты в git
- rule-arch-structured-logging — логи разбора документов без текста документа
- v3 (planned): rule-stack-new-tech-consent, rule-ai-no-stack-change — numpy и scipy — согласие получено (решение Q-kb-numpy-scipy-consent); rule-stack-one-tool-per-job — HTTP-клиент тот же DEP-py-httpx; rule-arch-outgoing-call-resilience — таймаут, повторы и урезанный режим CLS-wikisvc-core.Embeddings; rule-stack-postgres-default — векторы в SQLite (RISK-kb-vectors-in-sqlite, Q-kb-vector-store); rule-arch-orm-not-raw-sql, rule-arch-migrations-only — новые таблицы тем же способом (RISK-kb-raw-sql-new-tables); rule-stack-python-async — синхронный вызов эмбеддингов на пути запроса (RISK-kb-sync-outgoing-http); rule-arch-transactions-in-service — сеть вне транзакции индекса (JOB-wikisvc-core.embed-index); rule-arch-stateless-replicas — кэши в памяти процесса (RISK-kb-process-memory-state); rule-stack-background-tasks — потоки в процессе вместо Celery (ADR-0004); rule-arch-no-overengineering — интерфейс только у внешней границы (CLS-wikisvc-core.Embeddings)
