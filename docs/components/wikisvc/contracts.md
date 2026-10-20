# wikisvc: контракты

> HTTP API `/api/v1` компонента SVC-wikisvc. Список эндпоинтов сверен с `app.openapi()` (67 операций;
> ещё 13 `draft` слоя знаний v3). Логика ответов — в LIB-wikisvc-core; здесь — адрес, доступ, тела и ошибки.

## Общее для всех эндпоинтов

- base: `http://127.0.0.1:8787/api/v1` (CFG-wikisvc.BIND_HOST, CFG-wikisvc.BIND_PORT); JSON UTF-8, поля snake_case.
- auth: `Authorization: Bearer <token>` (SEC-authn), проверка до чтения тела (CLS-wikisvc.BodyLimit,
  INV-auth-before-body). Без заголовка при CFG-wikisvc.ANONYMOUS_ACCESS — анонимный принципал
  (INV-anonymous-ceiling). Колонка auth ниже — минимальная роль: ROLE-reader, ROLE-writer, ROLE-reviewer, ROLE-admin.
- видимость: страницы, правила, предложения и сырьё выше допуска принципала (SEC-clearance)
  отдаются как ERR-not_found (`404`), а не `403` (INV-404-not-403).
- решения ревью: где указано `human` — нужен токен человека SEC-principal-kind#human, иначе
  ERR-human_required (`403`); агент и аноним решений не принимают (INV-human-decides).
- ошибки: конверт `{"error": {"code", "message", "hint", "details": [{"field", "message"}]}}`
  (CLS-wikisvc-core.WikiError); `code` — `E_*`, каталог ERR-* в `system/errors.md`.
- общие ошибки любого эндпоинта, кроме health (в таблицах не повторяются): ERR-unauthorized (`401`),
  ERR-forbidden (`403`, роль ниже нужной), ERR-rate_limit (`429`), ERR-request_invalid (`400`;
  в том числе ошибки валидации тела и параметров — OpenAPI называет их `422`, сервис отдаёт `400`),
  ERR-body_too_large (`413`), ERR-http (неизвестный путь или метод), ERR-internal (`500`).
  Изменяющие эндпоинты под блокировкой записи ещё отдают ERR-lock_timeout (`409`, ждёт CFG-wikisvc.LOCK_TIMEOUT).
- страница списка: ответ `{items: json[], next_cursor: string?}`; `limit` 1..100 (по умолчанию 50),
  `cursor` — непрозрачная строка из прошлого ответа; плохой cursor → ERR-cursor_invalid (`400`).
- limits: тело ≤ 1 MB (кроме `POST /raw`), лимит запросов на токен CFG-wikisvc.RATE_LIMIT_PER_MIN.
- idempotency: заголовков идемпотентности нет; повтор изменяющего вызова — новая операция.
- ответы без DTO: большинство ответов — `json`-объект ядра без схемы в OpenAPI; в таблицах указаны ключевые поля.
- consumers: `U` — SVC-wiki-ui, `A` — SVC-wikiagent, `C` — ACT-coding-agent (в том числе `wk`, MCP-клиенты по HTTP).

## Синхронные вызовы: карточки

### API-wikisvc.health — живость и версия индекса
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `GET /api/v1/health`
- auth: без токена; при заданном CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME присланный `Authorization` проверяется
- response: `200` → `{status: "ok", version: string, index_commit: string}`
- side effects: читает `meta.index_commit` из RES-index-db
- consumers: OBS-wikisvc.health (`deploy/vm-test.nix`, `deploy/wiki-schema/apply.sh`), U
- changed: 2026-10-20 v3 (planned): в ответе ещё `embeddings: {enabled: bool, model: string?, selftest:
  enum(ok|failed|disabled), checked_at: timestamp?}` и `degraded: bool` (= не `ok` при включённых эмбеддингах) — результат self-test при старте (OBS-wikisvc.embeddings-selftest),
  сервер эмбеддингов на каждый запрос не вызывается; `status` остаётся `ok` и при `failed` (rule-arch-health-readiness:
  соседи не проверяются, SVC-updater не откатывает релиз из-за RES-embeddings-server; решение Q-kb-embeddings-degraded)

### API-wikisvc.sessions.create — выпуск SSO-сессии человека
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `POST /api/v1/sessions`
- auth: только токен с именем CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME и `kind=agent` (SEC-principal-kind#agent)
- request: DTO-wikisvc.SessionRequest → response: `200` → DTO-wikisvc.SessionResponse
- errors: ERR-not_found (`404`, выпуск выключен), ERR-forbidden (`403`, другой токен)
- side effects: создаёт токен `sso-…` (`kind=human`, срок CFG-wikisvc.SESSION_TTL_HOURS, роль и допуск
  по группам из CFG-wikisvc.ROLES_FILE, без совпадения — reader/public), пишет справочник людей и аудит
- implements: FLOW-oidc-login (выпуск токена после OIDC)
- consumers: U (Go-сервер после OIDC-входа)

### API-wikisvc.sessions.revoke — выход: отзыв своей сессии
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `DELETE /api/v1/sessions/current` → `204`
- auth: ROLE-reader, только SEC-principal-kind#human
- errors: ERR-not_found (`404`, выпуск выключен), ERR-forbidden (`403`, не человек)
- side effects: ставит `revoked_at` токену запроса
- consumers: U

### API-wikisvc.raw.upload — загрузка сырья
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `POST /api/v1/raw`, `multipart/form-data`: `file` (обяз.), `category` (обяз.:
  `docs|library|transcripts|tickets|api-specs|code-samples|assets`), `note` (≤ 4000 символов)
- auth: ROLE-writer
- response: `200` → запись сырья: `path`, `sha256`, `original_name`, `duplicate`, `trust: "untrusted_external"`
- errors: ERR-raw_category (`400`), ERR-raw_extension, ERR-raw_signature, ERR-upload_too_large (`413`), ERR-raw_exists (`409`)
- side effects: обычное сырьё — коммит в RES-wiki-repo (`raw/<category>/<год>/…`); `library` — файл в
  BKT-wikisvc-core.library; переиндексация пути, аудит; тот же `sha256` — возврат существующей записи
- limits: файл ≤ CFG-wikisvc.MAX_UPLOAD_MB, для `library` ≤ CFG-wikisvc.MAX_LIBRARY_UPLOAD_MB;
  расширения — CFG-wikisvc.ALLOWED_RAW_EXT; содержимое — недоверенное (INV-untrusted-external)
- consumers: U, A

### API-wikisvc.proposals.put-page — записать страницу в предложение
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `PUT /api/v1/proposals/{pid}/pages/{page_id}`
- auth: ROLE-writer; автор предложения или ревьюер; предложение в `draft|changes_requested|conflict` (STATE-proposal)
- request: DTO-wikisvc.PutPage либо строка — Markdown с frontmatter (FMT-wikisvc-core.page);
  ожидаемая версия — `base_version` в теле или заголовок `If-Match`
- response: `200` → `json` (страница в предложении и статус проверки)
- errors: ERR-not_found, ERR-proposal_state (`409`), ERR-id_invalid, ERR-id_duplicate, ERR-type_unknown,
  ERR-version_conflict (`409`), ERR-secret_detected, ERR-path_unsafe, ERR-source_hash, ERR-frontmatter_invalid
  и другие ошибки проверки страницы ядром
- side effects: коммит в ветку предложения (BKT-wikisvc-core.worktrees), статус в RES-state-db
- implements: FLOW-proposal-review (правка)
- consumers: U, A, C

### API-wikisvc.proposals.accept — принять предложение
status: implemented | owner: SVC-wikisvc | kind: http

- endpoint: `POST /api/v1/proposals/{pid}/accept`
- auth: ROLE-reviewer, `human`; не автор предложения (INV-no-self-review)
- request: DTO-wikisvc.Accept (тело можно не передавать)
- response: `200` → `json` (предложение со статусом `accepted`)
- errors: ERR-not_found, ERR-human_required, ERR-self_review (`403`), ERR-proposal_state (`409`),
  ERR-proposal_empty, ERR-validation, ERR-merge_conflict (`409`), ERR-rule_not_in_proposal, ERR-rule_fields
- side effects: слияние в `main` RES-wiki-repo, переиндексация, повышение и вывод правил из
  `promote`/`deprecate` (STATE-rule-lifecycle), аудит
- implements: FLOW-proposal-review (решение), INV-human-decides, INV-agent-rule-inert
- consumers: U
- changed: 2026-10-20 v3 (planned): в DTO-wikisvc.Accept поля `exclude` и `resolutions` — ревьюер снимает факты и решает
  пары `contradicts` (ТЗ §8.6) в самом решении, не становясь редактором (INV-no-self-review; решение Q-kb-ui-review-decisions);
  «снять» для пары уже принятых фактов = API-wikisvc.pages.mark-outdated одного; предложение с непринятым `depends_on` →
  ERR-proposal_dependency (`409`)

## Синхронные вызовы: чтение (`GET`, auth ROLE-reader, если не указано иное)

| id | endpoint | параметры | response | errors | consumers | owner | status |
|---|---|---|---|---|---|---|---|
| API-wikisvc.whoami | `GET /whoami` | — | DTO-wikisvc.Principal | — | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.pages.list | `GET /pages` | `type`, `status`, `tag`, `q_title`, `lifecycle` (через запятую), `limit`, `cursor` | страница списка | — | U, C | SVC-wikisvc | implemented |
| API-wikisvc.pages.get | `GET /pages/{page_id}` | `include` (`backlinks`, `neighbors`, `history`), `format` (`json`/`markdown`) | `json` страницы или `text/plain` Markdown; чтение правила агентом пишет статистику | ERR-not_found | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.pages.history | `GET /pages/{page_id}/history` | `limit`, `cursor` | страница списка коммитов | ERR-not_found | U | SVC-wikisvc | implemented |
| API-wikisvc.pages.at | `GET /pages/{page_id}/at/{commit}` | — | страница на коммите | ERR-not_found, ERR-commit_invalid | U | SVC-wikisvc | implemented |
| API-wikisvc.index | `GET /index` | — | `text/plain` оглавление видимых страниц | — | C | SVC-wikisvc | implemented |
| API-wikisvc.search | `GET /search` | `q` (обяз.), `type`, `tag`, `status`, `sensitivity`, `k`=10, `mode`=`bm25`, `expand`, `lifecycle` | `{query, results[]}` (v3 planned: одна строка на страницу, `expand` — PPR по снимку графа; заменяется API-wikisvc.knowledge.ask: `deprecated` после переезда `wk`, SVC-wikiagent и SVC-wiki-ui, удаление — в следующей мажорной версии (решение Q-kb-search-context-deprecation)) | — | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.context | `GET /context/{page_id}` | `depth`=1, `rels`, `budget_chars` (по умолчанию CFG-wikisvc.CONTEXT_BUDGET_DEFAULT) | `{pages, delivered_chars, available_chars, truncated_ids, omitted_ids}`; пишет статистику выдачи (v3 planned: сборка CLS-wikisvc-core.Assemble, корень режется до L1 и попадает в `truncated_ids`; заменяется API-wikisvc.knowledge.ask на тех же условиях, что API-wikisvc.search) | ERR-not_found | C | SVC-wikisvc | implemented |
| API-wikisvc.graph.impact | `GET /graph/impact/{page_id}` | `depth`=2, `rels` | узлы и рёбра | ERR-not_found | C | SVC-wikisvc | implemented |
| API-wikisvc.graph.neighbors | `GET /graph/neighbors/{page_id}` | `depth`=1, `rels`, `direction`=`both` | узлы и рёбра (v3 planned: рёбра как DTO-wikisvc-core.EdgeView; параметр `soft`=`false` — включать `soft_edges`; Q-kb-ui-graph-edge-fields) | ERR-not_found | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.graph.path | `GET /graph/path` | `from`, `to` (обяз.), `max_depth`=5 | путь между страницами | ERR-not_found | C | SVC-wikisvc | implemented |
| API-wikisvc.graph.export | `GET /graph/export` | `type`, `status`, `include_scopes` | весь видимый граф (v3 planned: рёбра как DTO-wikisvc-core.EdgeView; параметры `soft`=`false` (включать `soft_edges`), `domain` (ENT-domain с поддоменами), `limit` узлов 1..2000; при обрезке — `truncated: true`; Q-kb-ui-graph-edge-fields, RISK-kb-ui-graph-export-size) | — | U | SVC-wikisvc | implemented |
| API-wikisvc.rules.list | `GET /rules` | `category`, `level`, `lifecycle`, `applies_to`, `origin`, `source`, `q`, `sort`=`id`, `limit`, `cursor` | страница списка | — | U, A | SVC-wikisvc | implemented |
| API-wikisvc.rules.get | `GET /rules/{page_id}` | — | правило (FMT-wikisvc-core.rule) | ERR-not_found | U, C | SVC-wikisvc | implemented |
| API-wikisvc.rules.related | `GET /rules/related` | `q` (обяз.), `scopes`, `limit`=10, `impact_terms` | похожие правила (v3 planned: через CLS-wikisvc-core.Ask со `scopes=rule`, ответ прежний, NFR-rules-related-queries) | ERR-scope_unknown | A, C | SVC-wikisvc | implemented |
| API-wikisvc.rules.stats | `GET /rules/stats` (ROLE-reviewer) | `days`=30 | статистика применения правил | — | U | SVC-wikisvc | implemented |
| API-wikisvc.policies.compile | `GET /policies/compile` | `profile`, `scopes`, `budget_tokens`, `enforced`=`keep_must`, `explain` | `{profile, scopes, budget_tokens, used_tokens, version, over_budget, markdown, included[]}` (FMT-wikisvc-core.policy-block) (v3 planned: параметр `knowledge`=`false`; при `true` ещё `knowledge_markdown` — FMT-wikisvc-core.knowledge-block из brief того же профиля; `used_tokens` по CFG-wikisvc.CHARS_PER_TOKEN_LATIN и CFG-wikisvc.CHARS_PER_TOKEN_CYRILLIC) | ERR-profile_unknown, ERR-scope_unknown, ERR-rule_fields | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.profiles.list | `GET /profiles` | — | профили (FMT-wikisvc-core.profiles) | — | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.scopes.list | `GET /scopes` | — | `string[]` | — | A, C | SVC-wikisvc | implemented |
| API-wikisvc.schema.get | `GET /schema` | — | реестр схемы: типы, связи, области, профили | — | U, C | SVC-wikisvc | implemented |
| API-wikisvc.schema.page-type | `GET /schema/page-types/{type_name}` | — | тип страницы (FMT-wikisvc-core.page-type) | ERR-type_unknown | C | SVC-wikisvc | implemented |
| API-wikisvc.schema.instructions | `GET /schema/instructions` | — | `{instructions: string}` | — | C | SVC-wikisvc | implemented |
| API-wikisvc.schema.project-template | `GET /schema/project-templates/{template_id}` | — | FMT-wikisvc-core.project-template | ERR-template_unknown (`404`), ERR-template_invalid | C | SVC-wikisvc | implemented |
| API-wikisvc.lint | `GET /lint` | `limit`, `cursor` | `{issues[], next_cursor}` | — | U, A | SVC-wikisvc | implemented |
| API-wikisvc.stats | `GET /stats` | — | сводка по вики | — | U | SVC-wikisvc | implemented |
| API-wikisvc.findings.list | `GET /findings` | `status`, `kind`, `severity`, `scope`, `limit`, `cursor` | страница списка (ENT-finding) | — | U | SVC-wikisvc | implemented |
| API-wikisvc.findings.stats | `GET /findings/stats` | — | `{kinds}` | — | U | SVC-wikisvc | implemented |
| API-wikisvc.inbox | `GET /inbox` (ROLE-reviewer) | — | `{proposals, pending_sources, candidates_by_source, open_findings, jobs, lint}`; `pending_sources` только при допуске restricted; `jobs` из RES-agent-db | — | U | SVC-wikisvc | implemented |
| API-wikisvc.people.list | `GET /people` (допуск ≥ internal) | `limit`, `cursor` | DTO-wikisvc.People | ERR-forbidden | U | SVC-wikisvc | implemented |
| API-wikisvc.raw.list | `GET /raw` | `limit`, `cursor` | страница списка + `trust` | ERR-not_found | U, A | SVC-wikisvc | implemented |
| API-wikisvc.sources.pending | `GET /sources/pending` | `limit`, `cursor` | необработанное сырьё, как `raw.list` | ERR-not_found | U | SVC-wikisvc | implemented |
| API-wikisvc.raw.download | `GET /raw/{path}` | — | файл `application/octet-stream`, `X-Content-Trust: untrusted_external`, `nosniff` | ERR-not_found, ERR-path_unsafe | U | SVC-wikisvc | implemented |
| API-wikisvc.raw.text | `GET /raw/{path}/text` | `pages`, `chapter`, `max_chars`=30000, `offset`=0 | извлечённый текст | ERR-not_found, ERR-extract_pending (`409`), ERR-text_unavailable, ERR-text_too_large, ERR-locator_out_of_range, ERR-extractor_unavailable | U, A | SVC-wikisvc | implemented |
| API-wikisvc.raw.outline.get | `GET /raw/{path}/outline` | — | оглавление книги | ERR-not_found, ERR-extract_pending | U, A | SVC-wikisvc | implemented |
| API-wikisvc.admin.audit | `GET /admin/audit` (ROLE-admin, допуск restricted) | `since`, `token`, `action`, `limit`, `cursor` | страница записей аудита | ERR-not_found (без restricted) | U | SVC-wikisvc | implemented |

## Синхронные вызовы: слой знаний v3 (`/knowledge/…`, FLOW-knowledge-brief, FLOW-ask)

- auth: ROLE-reader (`similar`, `verdicts`, `novelty` — ROLE-writer). Узлы выше допуска (SEC-clearance) не попадают ни в выдачу, ни в `omitted_ids`, ни в рёбра;
  скрытый или несуществующий id в пути — ERR-not_found (INV-404-not-403, SEC-graph-clearance-mask).
- бюджет: `budget_tokens` int32 ≥ 1, больше CFG-wikisvc.TOOL_RESPONSE_CAP — урезается до него (NFR-tool-response-cap;
  решение Q-kb-wikisvc-defaults); оценка — CLS-wikisvc-core.estimate_tokens (NFR-token-estimate);
  не влезает даже одна строка L0 — ERR-budget_too_small. Ответ — поля DTO-wikisvc.KnowledgeMeta.
- выдача: уровни L0/L1/L2 — DTO-wikisvc-core.FactView, канонический порядок (INV-canonical-order); не влезшее —
  в `omitted_ids`, не молча. Выданные id пишет CLS-wikisvc-core.DeliveryQueue (SEC-delivery-stats).
- запись фактов и связей (`propose_fact`, `propose_link`) — только API-wikisvc.proposals.create, API-wikisvc.proposals.put-page,
  API-wikisvc.proposals.patch-page (ROLE-writer); эндпоинты `/knowledge/…` страниц не меняют.
- RES-embeddings-server недоступен или self-test не прошёл — урезанный режим: семена только BM25, без dense-prior,
  `degraded: true` в ответе, в `version` модель `none` (rule-arch-outgoing-call-resilience; решение Q-kb-embeddings-degraded).
- запись агента без предложений — только производные данные: API-wikisvc.knowledge.verdicts, API-wikisvc.knowledge.novelty.
- лимиты (SEC-rate-limit): CFG-wikisvc.RATE_LIMIT_PER_MIN считается по стоимости — `ask` = 1 + эмбеддинг запроса,
  `similar` = число текстов, `expand` = `ids` × `depth`, прочие = 1; анонимы делят один общий лимит; одновременные
  вызовы эмбеддингов ограничивает семафор CLS-wikisvc-core.Embeddings.

### API-wikisvc.knowledge.ask — вопрос к слою знаний
status: planned | owner: SVC-wikisvc | kind: http

- endpoint: `GET /api/v1/knowledge/ask`: `query` (обяз., 1..1000 символов), `budget_tokens` (по умолчанию CFG-wikisvc.ASK_BUDGET_DEFAULT),
  `scopes` (через запятую, ENT-scope, иерархия осей), `type`, `tag`, `status` (фильтры, как у API-wikisvc.search),
  `rerank` (bool, по умолчанию CFG-wikisvc.ASK_RERANK_ENABLED)
- response: `200` → DTO-wikisvc-core.AskResult (с полем `degraded: bool`); настройки шагов — CFG-wikisvc.ASK_SEEDS, CFG-wikisvc.ASK_EXPANSION_RATIO,
  CFG-wikisvc.ASK_EXPANSION_MIN_HUBS, CFG-wikisvc.PPR_ALPHA, CFG-wikisvc.PPR_TOL, CFG-wikisvc.PPR_DENSE_PRIOR
- errors: ERR-scope_unknown, ERR-budget_too_small; reranker (в ядре, решение Q-kb-reranker-placement) выключен или недоступен — шаг пропускается без ошибки
- implements: FLOW-ask, NFR-ask-budget; заменит API-wikisvc.search и API-wikisvc.context; consumers: A, C

| id | endpoint | параметры | response | errors | consumers | owner | status |
|---|---|---|---|---|---|---|---|
| API-wikisvc.knowledge.brief | `GET /knowledge/brief` | `profile` (обяз.), `model?` (перекрывает `reference_model` профиля), `budget_tokens` (по умолчанию из профиля, не больше CFG-wikisvc.BRIEF_BUDGET_MAX) | DTO-wikisvc-core.BriefResult (NFR-brief-budget, INV-rules-pushed-knowledge-pulled) | ERR-profile_unknown, ERR-budget_too_small | A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.fact | `GET /knowledge/facts/{fact_id}` | `budget_tokens` | `{fact: DTO-wikisvc-core.FactView (L2), edges: DTO-wikisvc-core.EdgeView[]}`; при малом `budget_tokens` L2 режется как контекст страницы: заголовок и `claim`/`summary` всегда, затем разделы по порядку, пока влезают; невлезшие — в `truncated_sections` (решение координатора 2026-10-20) | ERR-not_found (нет `fact` с таким id), ERR-budget_too_small (бюджет меньше L0) | U, A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.topic | `GET /knowledge/topics/{topic_id}` | `level` 0\|1\|2 (по умолчанию 0, решение Q-kb-wikisvc-defaults), `budget_tokens`, `cursor` | DTO-wikisvc-core.TopicResult | ERR-not_found, ERR-cursor_invalid, ERR-budget_too_small | U, A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.expand | `GET /knowledge/expand` | `ids` (обяз., через запятую, 1..20), `rels` (по умолчанию белый список FLOW-ask), `depth` 1..3 (=1), `budget_tokens`; обход не дальше 500 посещённых узлов (решение Q-kb-wikisvc-defaults) | DTO-wikisvc-core.ExpandResult; скрытые и неизвестные id молча пропускаются | ERR-not_found (ни одного видимого id), ERR-rel_unknown, ERR-budget_too_small | A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.tech | `GET /knowledge/tech/{tech_id}` | `budget_tokens` | DTO-wikisvc-core.TechResult (состояние — поле `adoption`, STATE-tech) | ERR-not_found, ERR-budget_too_small | U, A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.why | `GET /knowledge/why/{page_id}` | `budget_tokens` | DTO-wikisvc-core.WhyResult | ERR-not_found, ERR-budget_too_small | U, A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.questions | `GET /knowledge/questions` | `scopes`, `status`=`open` (STATE-question), `limit`, `cursor`, `budget_tokens` | страница списка: `question` в L0 и `priority` | ERR-scope_unknown, ERR-cursor_invalid | U, A, C | SVC-wikisvc | planned |
| API-wikisvc.knowledge.similar | `POST /knowledge/similar` (только чтение; тело — длинные claims не влезают в URL) | тело: `claims: string[]` (1..40, каждый 20..200 символов) или `ids: string[]` (1..40), `k` 1..10, `threshold` (по умолчанию CFG-wikisvc.SIMILAR_THRESHOLD), `domain?`, `include_pending` (bool, по умолчанию `false`: ещё черновые факты открытых предложений `kind=book`, отдельный пул векторов; решение Q-kb-knn-endpoint); kNN по `claim`-векторам (CLS-wikisvc-core.Embeddings, CLS-wikisvc-core.Knowledge) | `{results: {query: string, items: {id, cosine: float64, claim}[]}[]}` (L0, только видимое); роль ROLE-writer — до 40 текстов в эмбеддинги за запрос | ERR-embeddings_unavailable, ERR-request_invalid | A | SVC-wikisvc | planned |
| API-wikisvc.knowledge.topics | `GET /knowledge/topics` | `domain` (обяз., с поддоменами), `type` (`topic`\|`tech`\|`all`=`all`), `limit` 1..300 (ТЗ §8.2) | `{items: {id, title}[]}` по id (глобальный список хабов для ingest) | ERR-domain_unknown | A, U | SVC-wikisvc | planned |
| API-wikisvc.knowledge.verdicts | `POST /knowledge/verdicts` (ROLE-writer и принципал `kind=agent`, (решение координатора 2026-10-20)) | тело: `{a: string, b: string, verdict: enum(duplicate\|refines\|contradicts\|independent), model: string, confidence: float64 0..1}` (1 пара; пару упорядочивает ядро) | `{a, b, verdict, recorded_at}`; пишет TBL-wikisvc-core.state.pair_verdicts через CLS-wikisvc-core.Verdicts с текущими `content_hash` сторон — смена хеша любой стороны делает вердикт устаревшим; читают lint (`W_POSSIBLE_DUPLICATE`) и review_class (FLOW-dedup-judge, решение Q-kb-nli-judge-model) | ERR-not_found (сторона не видна), ERR-request_invalid | A | SVC-wikisvc | planned |
| API-wikisvc.knowledge.novelty | `POST /knowledge/novelty` (ROLE-writer и принципал `kind=agent`, (решение координатора 2026-10-20)); ещё `GET /knowledge/novelty?model_family=…&limit=…` (ROLE-writer, страница списка с `cursor`) — очередь фактов-кандидатов brief профилей без novelty для этого семейства; ядро пополняет её при `get_brief` с незнакомым семейством (таблица TBL-wikisvc-core.state.novelty_queue; запись удаляется при `POST`), агент читает для ленивого novelty-scan (FLOW-novelty-scan) | тело: `{page_id: string, model_family: string, bucket: enum(common\|differs\|unique), content_hash: string}` | `{page_id, model_family, bucket, measured_at}`; пишет TBL-wikisvc-core.state.novelty через CLS-wikisvc-core.Verdicts, без предложения, `verified` не трогает (FLOW-novelty-scan) | ERR-not_found, ERR-version_conflict (`content_hash` не текущий), ERR-request_invalid | A | SVC-wikisvc | planned |
| API-wikisvc.knowledge.domains | `GET /knowledge/domains` | — | дерево доменов FMT-wikisvc-core.domains (ENT-domain) | — | U, A, C | SVC-wikisvc | planned |

## Синхронные вызовы: предложения (STATE-proposal, FLOW-proposal-review)

| id | endpoint | auth | request | response | errors | consumers | owner | status |
|---|---|---|---|---|---|---|---|---|
| API-wikisvc.proposals.create | `POST /proposals` | ROLE-writer | DTO-wikisvc.CreateProposal | предложение (`pid`, `status: draft`) | ERR-secret_detected | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.list | `GET /proposals` | ROLE-reader | `status`, `author`, `kind`, `limit`, `cursor` | страница списка (v3 planned: у элемента `review_class: enum(STATE-fact-review-class)?` предложения, `needs_double_confirm: bool`, `depends_on: string[]`; Q-kb-ui-review-class-field) | — | U, A | SVC-wikisvc | implemented |
| API-wikisvc.proposals.get | `GET /proposals/{pid}` | ROLE-reader | — | предложение, изменения, заметки (v3 planned: ещё `review_class`, `needs_double_confirm` (считает ядро), `depends_on`, у каждого факта `reasons` — DTO-wikisvc-core.ProposalReasons; auto-блок принимает человек одним решением, системного приёма нет (решение Q-kb-auto-accept-human-decides); факты предложения в L0/L1 DTO-wikisvc-core.FactView строит сервер, в том числе не попавшие в индекс, с подвалом происхождения в фиксированной позиции до текста: `origin`, для `kind=book` — `trust: untrusted_external` (INV-untrusted-external); Q-kb-ui-proposal-fact-view) | ERR-not_found | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.patch-page | `PATCH /proposals/{pid}/pages/{page_id}` | ROLE-writer, автор или ревьюер | DTO-wikisvc.PatchPage | как `put-page` | как `put-page`, ERR-patch_invalid | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.delete-page | `DELETE /proposals/{pid}/pages/{page_id}` | ROLE-writer, автор или ревьюер | `base_version` в query | `json` | ERR-not_found, ERR-proposal_state, ERR-link_unresolved | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.validate | `GET /proposals/{pid}/validate` | ROLE-writer | — | результат проверки страниц (v3 planned: видит страницы предложений из `depends_on`) | ERR-not_found | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.diff | `GET /proposals/{pid}/diff` | ROLE-reader | — | разница с `main` (v3 planned: изменённые факты — ещё DTO-wikisvc-core.FactView L0/L1 от сервера с подвалом происхождения, как в `get`; Q-kb-ui-proposal-fact-view) | ERR-not_found | U | SVC-wikisvc | implemented |
| API-wikisvc.proposals.impact | `GET /proposals/{pid}/impact` | ROLE-reader | — | затронутые правила и проекты | ERR-not_found | U, A | SVC-wikisvc | implemented |
| API-wikisvc.proposals.notes | `PUT /proposals/{pid}/notes` | ROLE-writer | `json`-объект заметок | `json` | ERR-not_found, ERR-forbidden, ERR-secret_detected | A | SVC-wikisvc | implemented |
| API-wikisvc.proposals.submit | `POST /proposals/{pid}/submit` | ROLE-writer | — | предложение `submitted` | ERR-not_found, ERR-proposal_state, ERR-proposal_empty | U, A, C | SVC-wikisvc | implemented |
| API-wikisvc.proposals.reject | `POST /proposals/{pid}/reject` | ROLE-reviewer, `human` | DTO-wikisvc.Comment (`reason`) | предложение `rejected` | ERR-not_found, ERR-human_required, ERR-proposal_state, ERR-secret_detected | U | SVC-wikisvc | implemented |
| API-wikisvc.proposals.request-changes | `POST /proposals/{pid}/request-changes` | ROLE-reviewer, `human` | DTO-wikisvc.Comment (`comment`) | предложение `changes_requested` | как `reject` | U | SVC-wikisvc | implemented |
| API-wikisvc.proposals.abandon | `POST /proposals/{pid}/abandon` | ROLE-writer; не автор — ROLE-reviewer | — | предложение `abandoned` | ERR-not_found, ERR-proposal_state | U, A | SVC-wikisvc | implemented |
| API-wikisvc.proposals.revert | `POST /proposals/{pid}/revert` | ROLE-reviewer, `human` | — | предложение `reverted` | ERR-not_found, ERR-human_required, ERR-proposal_state, ERR-revert_conflict (`409`) | U | SVC-wikisvc | implemented |

Все изменяющие вызовы предложений коммитят в ветку предложения или в `main` RES-wiki-repo и пишут аудит.

## Синхронные вызовы: ревью, находки, сырьё, администрирование

| id | endpoint | auth | request | response | errors | consumers | owner | status |
|---|---|---|---|---|---|---|---|---|
| API-wikisvc.pages.verify | `POST /pages/{page_id}/verify` | ROLE-reviewer, `human` | — | страница `status: verified` | ERR-not_found, ERR-human_required | U | SVC-wikisvc | implemented |
| API-wikisvc.pages.mark-outdated | `POST /pages/{page_id}/mark-outdated` | ROLE-reviewer, `human` | DTO-wikisvc.OutdatedRequest | страница `status: outdated` | ERR-not_found, ERR-human_required | U | SVC-wikisvc | implemented |
| API-wikisvc.rules.promote | `POST /rules/{page_id}/promote` | ROLE-reviewer, `human` | DTO-wikisvc.Promote | правило `active` (STATE-rule-lifecycle) | ERR-not_found, ERR-human_required, ERR-rule_fields | U | SVC-wikisvc | implemented |
| API-wikisvc.rules.deprecate | `POST /rules/{page_id}/deprecate` | ROLE-reviewer, `human` | DTO-wikisvc.Deprecate | правило `deprecated` | ERR-not_found, ERR-human_required, ERR-rule_fields | U | SVC-wikisvc | implemented |
| API-wikisvc.rules.violations | `POST /rules/violations` | ROLE-writer | DTO-wikisvc.Violations | `map<string,int64>` счётчики | ERR-not_found, ERR-secret_detected | A, C | SVC-wikisvc | implemented |
| API-wikisvc.findings.create | `POST /findings` | ROLE-writer | DTO-wikisvc.Finding | находка (ENT-finding) | ERR-forbidden (чужое предложение), ERR-quote_not_found, ERR-secret_detected | A | SVC-wikisvc | implemented |
| API-wikisvc.findings.dismiss | `POST /findings/{finding_id}/dismiss` | ROLE-reviewer, `human` | DTO-wikisvc.Reason | находка `dismissed` (STATE-finding) | ERR-not_found, ERR-human_required, ERR-secret_detected | U | SVC-wikisvc | implemented |
| API-wikisvc.findings.reopen | `POST /findings/{finding_id}/reopen` | ROLE-reviewer, `human` | — | находка `open` | ERR-not_found, ERR-human_required | U | SVC-wikisvc | implemented |
| API-wikisvc.raw.extract | `POST /raw/{path}/extract` → `202` | ROLE-writer | `retry` в query | состояние извлечения (STATE-extraction) | ERR-not_found, ERR-text_unavailable | U, A | SVC-wikisvc | implemented |
| API-wikisvc.raw.outline.put | `PUT /raw/{path}/outline` | ROLE-writer | DTO-wikisvc.Outline | оглавление | ERR-not_found, ERR-extract_pending, ERR-locator_out_of_range | U, A | SVC-wikisvc | implemented |
| API-wikisvc.schema.next-adr-number | `POST /schema/next-adr-number` | ROLE-writer | — | `{number: "NNNN"}` | ERR-adr_exhausted (`409`) | C | SVC-wikisvc | implemented |
| API-wikisvc.admin.reindex | `POST /admin/reindex` | ROLE-admin | DTO-wikisvc.ReindexRequest | `{status: "ok"}` | — (v3 planned: ERR-embeddings_unavailable при `embeddings=true`) | C | SVC-wikisvc | implemented |

`raw.extract` ставит фоновое извлечение JOB-wikisvc-core.extract-worker (BKT-wikisvc-core.extract),
таймаут CFG-wikisvc.EXTRACT_JOB_TIMEOUT; `admin.reindex` пересобирает RES-index-db и пишет аудит.

## Структуры данных

Сериализация всех DTO — JSON, snake_case; лишние поля игнорируются, если не сказано «extra запрещены».

### DTO-wikisvc.Principal — кто вызывает
status: implemented | owner: SVC-wikisvc

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `name` | string | да | — | имя токена или отображаемое имя сессии |
| `role` | enum(reader\|writer\|reviewer\|admin) | да | — | ROLE-* |
| `clearance` | enum(public\|internal\|restricted) | да | — | SEC-clearance |
| `person` | string? | нет | — | стабильный id человека (`sub` OIDC) |
| `kind` | enum(agent\|human) | да | по умолчанию `agent` | SEC-principal-kind |

### DTO-wikisvc.SessionRequest — запрос сессии
status: implemented | owner: SVC-wikisvc

- fields: `subject: string` (обяз., `^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$`, `sub` из OIDC), `username: string?`
  (≤ 1024, отображаемое имя, очищается), `groups: string[]?` (≤ 1000, группы IdP для сопоставления ролей)

### DTO-wikisvc.SessionResponse — выпущенная сессия
status: implemented | owner: SVC-wikisvc

- fields (все обяз.): `token: string` (Bearer-токен сессии; секрет SEC-secrets, показывается один раз),
  `expires_at: timestamp` (конец сессии), `actor: DTO-wikisvc.Principal` (`kind=human`)

### DTO-wikisvc.CreateProposal — новое предложение
status: implemented | owner: SVC-wikisvc

- fields: `title: string` (обяз., 3..200 символов, одна строка), `description: string?` (≤ 12000),
  `kind: enum(manual|chat|book|heal)?` (источник предложения, по умолчанию `manual`)
- changed: 2026-10-20 v3 (planned): `depends_on: string[]?` — pid предложений, без принятия которых это не принимается
  (ERR-proposal_dependency); проверка видит страницы зависимостей (API-wikisvc.proposals.validate).

### DTO-wikisvc.PutPage — страница целиком
status: implemented | owner: SVC-wikisvc

- fields: `frontmatter: json` (обяз., FMT-wikisvc-core.page), `body_md: string` (обяз., тело Markdown),
  `base_version: string?` (ожидаемая версия; иначе ERR-version_conflict)

### DTO-wikisvc.PatchPage — точечные правки страницы
status: implemented | owner: SVC-wikisvc

- fields: `ops: json[]` (обяз., 1..100 операций правки разделов и полей frontmatter), `base_version: string?` (ожидаемая версия)

### DTO-wikisvc.Comment — причина решения ревьюера
status: implemented | owner: SVC-wikisvc

- fields: `comment: string?` (для `request-changes`), `reason: string?` (для `reject`); без секретов

### DTO-wikisvc.Accept — что сделать с правилами при принятии
status: implemented | owner: SVC-wikisvc

- fields: `promote: DTO-wikisvc.Promote[]?` (≤ 100, у элемента ещё `id: string`; правила предложения, которые
  сделать `active`), `deprecate: DTO-wikisvc.Deprecate[]?` (≤ 100, у элемента ещё `id: string`; правила, которые вывести)
- changed: 2026-10-20 v3 (planned): `exclude: string[]?` — id фактов, снятых ревьюером до слияния; `resolutions:
  {pair: [string, string], action: enum(keep_both|replaces|drop), replaces: {old: string, new: string}?}[]?` — одно
  действие на пару `contradicts` (ТЗ §8.6), `replaces` обязателен при `action=replaces` (Q-kb-ui-review-decisions)
- проверки (draft): `exclude` — только id страниц-фактов этого предложения; `pair` — только пара `contradicts` из
  предложения; `replaces.old`, `replaces.new` ∈ `pair`; `drop` снимает только новый факт, существующий становится
  `outdated`; после применения — повторная валидация; аудит с идентичностью ревьюера. Иначе ERR-request_invalid.

### DTO-wikisvc.Promote — параметры повышения правила
status: implemented | owner: SVC-wikisvc

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `level` | enum(must\|should) | нет | по умолчанию `should` | уровень |
| `priority` | int32? | нет | 1..5 | приоритет |
| `applies_to` | string[]? | нет | — | области |
| `owner` | string? | нет | — | владелец правила |
| `enforced_by` | string[]? | нет | — | чем проверяется |

- extra запрещены.

### DTO-wikisvc.Deprecate — вывод правила
status: implemented | owner: SVC-wikisvc

- fields: `reason: string` (обяз., 1..200, причина)

### DTO-wikisvc.Violations — отчёт о нарушениях правил
status: implemented | owner: SVC-wikisvc

- fields: `items: {rule_id: string, note: string ≤ 2000, ref: string ≤ 2000}[]` (обяз., 1..100, нарушения ENT-violation)

### DTO-wikisvc.Finding — находка проверки вики
status: implemented | owner: SVC-wikisvc

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `kind` | string | да | 1..80, `[a-zA-Z0-9_-]` | вид находки |
| `severity` | enum(info\|warning\|error\|critical) | нет | по умолчанию `warning` | важность |
| `pages` | string[] | да | 1..20 | затронутые страницы |
| `summary` | string | да | 3..500 | кратко |
| `explanation` | string | нет | ≤ 12000 | подробно |
| `evidence` | `{page: string, quote: string 1..4000}`[] | нет | ≤ 20; цитата должна найтись | доказательства |
| `proposal_pid` | string? | нет | только своё предложение | связанное предложение |
| `run_id` | string? | нет | — | запуск агента |
| `scope` | string | нет | `^([a-z0-9][a-z0-9-]{0,63})?$` | область |

- extra запрещены.

### DTO-wikisvc.Reason — причина отклонения находки
status: implemented | owner: SVC-wikisvc

- fields: `reason: string?` (причина, без секретов)

### DTO-wikisvc.OutdatedRequest — причина устаревания страницы
status: implemented | owner: SVC-wikisvc

- fields: `reason: string` (обяз., 1..1000, без секретов, почему страница устарела)

### DTO-wikisvc.Outline — оглавление книги
status: implemented | owner: SVC-wikisvc

- fields: `chapters: {n: int32 ≥ 1, title: string 1..200, page_from: int32 ≥ 1, page_to: int32 ≥ 1}[]` (обяз., 1..5000, главы и диапазоны страниц)

### DTO-wikisvc.ReindexRequest — переиндексация
status: implemented | owner: SVC-wikisvc

- fields: `full: bool?` (по умолчанию `true`: полная или только изменённое)
- changed: 2026-10-20 v3 (planned): поле `embeddings: bool?` (по умолчанию `false`) — пересчитать все векторы и
  повторить self-test (смена модели, ADR-0018); без него векторы пересчитываются по `content_hash`.

### DTO-wikisvc.KnowledgeMeta — общие поля ответов слоя знаний
status: planned | owner: SVC-wikisvc

- fields: `version: string` (генерация индекса + модель эмбеддингов), `budget_tokens: int32` (применённый),
  `used_tokens: int32`, `omitted_ids: string[]` (только видимые id)
- верхний уровень каждого ответа API-wikisvc.knowledge.*, рядом с полями core-DTO ответа (например,
  DTO-wikisvc-core.AskResult, DTO-wikisvc-core.TopicResult); одноимённые поля не дублируются.

### DTO-wikisvc.People — справочник людей
status: implemented | owner: SVC-wikisvc

- fields (все обяз.): `items: {person: string, display_name: string, updated_at: string}[]` (≤ `limit`, люди,
  входившие через SSO, SEC-pii), `next_cursor: string?` (курсор следующей страницы)
