# llm-wiki — документация

> Это источник правды о проекте. Код пишется по этим файлам.
> Если код и документ расходятся — прав документ, код считается багом.
> Не больше 150 строк. Подробности — в файлах по ссылкам.

## Как читать (агенту)

1. Этот файл — целиком.
2. `system/overview.md` и `system/domain.md` — всегда.
3. Компонент задачи: `components/<имя>/component.md`, дальше по ссылкам из него.
4. Незнакомый ID → `_meta/registry.md` (где определён, где в коде, кто использует).
5. Правила: ID — `_meta/ids.md`, формат — `_meta/format.md`, процесс — `_meta/workflow.md`.
6. Код открывай только для того, что прямо нужно задаче; место в коде — `grep -rn "doc: <ID>"`.

## Что это за система

Свод правил компании для агентов, которые пишут код. Правила хранятся Markdown-страницами в
отдельном git-репозитории (RES-wiki-repo) с ID, версией, обоснованием и историей; детерминированное
ядро SVC-wikisvc отдаёт их через HTTP и MCP, компилирует блок политик под профиль проекта
(FLOW-policy-compile) и принимает предложения правок. Любое изменение — предложение; принимает его
только человек (INV-human-decides). SVC-wikiagent добавляет модель: чат, планировщик правил из фраз,
разбор книг, самолечение и сверку проектной документации. SVC-wiki-ui — веб-пространство со входом
через EXT-authentik. В систему не входят: клиентский CLI `wk`, шаблон `docs-template`, навыки и хуки
агентов (отдельные репозитории); OCR, графовая БД; несколько узлов (ADR-0004).

**v3 «слой знаний» (утверждено 2026-10-20, факты `planned`, ТЗ — `../ref/knowledge-layer-spec.md`):** к слою правил
добавляется описательный слой `kb/` — атомарные факты ENT-fact (пара claim/summary, INV-claim-minimal), хабы
ENT-topic, технологии ENT-tech и открытые вопросы ENT-question по дереву доменов ENT-domain. Правила по-прежнему
идут в инструкцию всегда, знания — по запросу (INV-rules-pushed-knowledge-pulled): FLOW-knowledge-brief в начале
задачи и FLOW-ask по ходу (BM25 + эмбеддинги MDL-bge-m3 через EXT-embeddings-server, условное расширение PPR по
снимку графа в памяти, ADR-0018…ADR-0020). Книга разбирается на факты по хабам (FLOW-fact-ingest), дубликаты
решает NLI/LLM-судья (FLOW-dedup-judge), ревью маршрутизируется по классам auto/queue/pair
(FLOW-fact-review-routing, ADR-0024), устаревшее не удаляется (INV-invalidate-not-delete).

## Компоненты

| компонент | вид | язык | путь | одной строкой |
|---|---|---|---|---|
| SVC-wikisvc | http-сервис | LANG-python | `src/wikisvc/main.py`, `src/wikisvc/api/` | HTTP API `/api/v1` на FastAPI, порт 8787: страницы, поиск, предложения, политики, сессии; v3 planned: `/knowledge/*` (API-wikisvc.knowledge.*) |
| LIB-wikisvc-core | библиотека | LANG-python | `src/wikisvc/{domain,storage,index,services,template}/` | домен, git-хранилище с worktrees, SQLite state и FTS5-индекс, вся бизнес-логика; без LLM; v3 planned: эмбеддинги, снимок графа, `ask`, brief (CLS-wikisvc-core.Ask, CLS-wikisvc-core.Brief) |
| SVC-wikisvc-mcp | http-сервис (MCP) | LANG-python | `src/wikisvc/mcp_server.py`, `mcp_http.py`, `tool_contracts.py` | 21 MCP-инструмент для агентов: stdio (`wikisvc mcp`) и Streamable HTTP `/mcp`; v3 planned: +10 инструментов знаний, профиль `knowledge` |
| SVC-wikisvc-cli | cli | LANG-python | `src/wikisvc/cli.py` | `wikisvc`: init, serve, token, policies, reindex, lint, schema, миграции; v3 planned: domains, embeddings selftest, eval |
| SVC-wikiagent | http-сервис + воркер | LANG-python | `src/wikiagent/` | всё, что требует модели: чат и план правок, ingest-book, heal, docs_audit; порт 8788; v3 planned: ingest фактов, судья дубликатов, novelty-scan |
| SVC-wiki-ui | фронтенд + Go-сервер | LANG-typescript, LANG-go | `ui/` | React SPA и Go-бинарник с OIDC, cookie-сессией и прокси к API; порт 8789 |
| SVC-updater | воркер | LANG-go | `updater/` | демон обновления релизов на хосте: проверка тегов GHCR, подпись, откат; API для UI |

## Хранилища и инфраструктура

| ресурс | что | кто владеет |
|---|---|---|
| RES-wiki-repo | git-репозиторий контента вики (`WIKI_ROOT`), запись через worktrees | LIB-wikisvc-core |
| RES-state-db | SQLite `state.db`: токены, предложения, находки, аудит | LIB-wikisvc-core |
| RES-index-db | SQLite FTS5 `wiki.db`: производный индекс, пересобирается | LIB-wikisvc-core |
| RES-agent-db | SQLite `agent.db`: задачи, сессии чата, кэш пар | SVC-wikiagent |
| RES-llama-server | локальный `llama-server` с MDL-wiki-gemma-31b, порт 18089 | ACT-operator |
| RES-embeddings-server | v3 planned: второй `llama-server --embeddings` с MDL-bge-m3 на loopback (порт — Q-kb-embeddings-port) | ACT-operator |
| RES-host | один Linux-хост: podman + systemd, 4 юнита из `deploy/` | ACT-operator |
| RES-container-image | образ `ghcr.io/badrabbit00/llm-wiki` (wikisvc + wikiagent + ui) | PIPE-release |

Очередей сообщений нет: фоновые задачи — пулы потоков внутри процессов. Redis и Postgres нет
(RISK-sqlite-not-postgres). Объектного хранилища нет: книги лежат на диске (BKT-wikisvc-core.library).

## Ключевые сценарии

- FLOW-proposal-review — агент или человек создаёт предложение, человек принимает; автор не ревьюер.
- FLOW-chat-plan — фраза в чате → план правок и diff → предложение.
- FLOW-ingest-book — книга из библиотеки читается по главам, кандидаты в правила ждут человека.
- FLOW-heal — ночной поиск противоречий внутри вики, находки во входящие.
- FLOW-docs-audit — сверка `docs/` проекта с действующими политиками.
- FLOW-policy-compile — сборка блока политик под профиль, экспорт в `AGENTS.md` проекта.
- FLOW-oidc-login — вход человека через Authentik, сессия в HttpOnly-cookie.
- FLOW-release-update — тег → образ в GHCR → SVC-updater ставит и при неудаче откатывает.
- FLOW-backup-restore — бэкап на остановленных службах, проверка восстановления.
- v3 planned: FLOW-knowledge-brief, FLOW-ask, FLOW-fact-ingest, FLOW-dedup-judge, FLOW-fact-review-routing, FLOW-novelty-scan.

## Стек коротко

- Python 3.12, FastAPI, pydantic 2, SQLite через `sqlite3`, git через subprocess, `httpx`, `mcp`; тесты pytest, порог покрытия 98 %.
  v3 planned: `numpy`, `scipy` в ядре, `onnxruntime`, `tokenizers` в агенте — только после согласия (Q-kb-numpy-scipy-consent, Q-kb-onnxruntime-consent).
- Go 1.25 без зависимостей (updater) и с go-oidc/oauth2 (ui-сервер).
- TypeScript, React 19, Vite, TanStack Query, react-router; e2e — Playwright.
- Nix flakes для всего: devShell, пакеты, образ `dockerTools`, хост-часть, VM-тесты. Подробно — `stack/`.

## Где что лежит

| что ищешь | файл |
|---|---|
| сущности, статусы, бизнес-правила | `system/domain.md` |
| сквозные сценарии | `system/flows.md` |
| роли, права, PII, секреты | `system/security.md` |
| коды ошибок | `system/errors.md` |
| требования к скорости и лимитам | `system/nfr.md` |
| эндпоинты, события, DTO компонента | `components/<c>/contracts.md` |
| таблицы, кэш, файлы компонента | `components/<c>/data.md` |
| модули и ключевые классы | `components/<c>/code.md` |
| фоновые задачи и настройки | `components/<c>/runtime.md` |
| промпты к LLM | `components/wikiagent/ai.md` |
| языки, версии, инструменты | `stack/languages.md` |
| все библиотеки всех языков | `stack/dependencies.md` |
| нейросети | `stack/models.md` |
| окружения, серверы, БД-инстансы | `infra/resources.md` |
| CI/CD | `infra/delivery.md` |
| логи, метрики, алерты | `infra/observability.md` |
| почему выбрали X | `decisions/` (ADR-0001 … ADR-0027; ADR-0002 заменён ADR-0018) |
| открытые вопросы / риски | `open-questions.md` / `risks.md` |
| старая документация до шаблона | `../ref/` (вторичный источник, не источник правды) |

## Состояние

- Реализовано: всё со статусом `implemented`, маркеры `doc:` стоят в коде.
- В работе (`planned`, с 2026-10-20): v3 «слой знаний». Новые факты — `planned`; совместимое изменение существующего
  факта помечено строкой `changed: 2026-10-20 v3 (planned): …` в карточке или суффиксом `(v3 planned: …)` в строке таблицы,
  статус такого факта остаётся `implemented`, пока код не изменён; реализация идёт по этапам, ветки `feat/kb-phase<N>`. Этапы по ТЗ §13: 1 — схема и форматы
  (FMT-wikisvc-core.fact, FMT-wikisvc-core.domains, FMT-wikisvc-core.kb-eval, ADR-0017, ADR-0021, ADR-0023, ADR-0025);
  2 — доставка (TBL-wikisvc-core.index.embeddings, CLS-wikisvc-core.Ask, API-wikisvc.knowledge.ask, API-wikisvc-mcp.ask,
  ADR-0018…ADR-0020); 3 — ingest фактов (JOB-wikiagent.ingest-book, JOB-wikiagent.novelty-scan, ADR-0022, ADR-0024,
  ADR-0026, ADR-0027); 4 — UI (MOD-wiki-ui.knowledge-views).
- Вопросы v3 закрыты владельцем 2026-10-20 (раздел «Слой знаний v3» в `open-questions.md`, все `resolved`, ответы
  внесены в карточки). Ключевые решения: auto-блок фактов принимает человек одним действием (INV-human-decides без
  изменений, INV-auto-class-scope); эмбеддинги в ядре только через loopback (исключение к ADR-0003 и границе №4
  `AGENTS.md` вносит человек); numpy, scipy, onnxruntime, tokenizers согласованы; судья в двух ролях (claim↔claim,
  claim↔источник) с LLM-ступенью на развёрнутой Gemma (в проде 12B, MDL-gemma-12b); novelty и вердикты — производные
  данные в `state.db`; все MCP-инструменты переходят на markdown (`MCP-CONTRACT-CHANGES-v3.md` в корне — для `wk`).
- Блокирует v3: правка границ №1/№4 в файле правил агентов (вносит человек). Расхождения v3 с
  политиками — раздел «Слой знаний v3» в `risks.md` (статусы выставлены по решениям).
