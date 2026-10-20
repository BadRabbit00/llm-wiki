# wikiagent: контракты

> Всё, через что компонент общается с внешним миром: HTTP API, CLI, DTO.
> Контракт описывает **что** и **с какими гарантиями**, а не как реализовано.

## Общее для всех HTTP-эндпоинтов

- Базовый адрес: `http://<bind_host>:8788` (`CFG-wikiagent.bind_port`), без префикса версии. SVC-wiki-ui
  проксирует его как `/agent-api/*`.
- auth: заголовок `Authorization: Bearer <токен вики>` обязателен; анонимного доступа нет. `CLS-wikiagent.authorize`
  спрашивает `/whoami` у SVC-wikisvc с токеном вызывающего и затем проверяет рабочий токен агента:
  - роль вызывающего — ROLE-writer, ROLE-reviewer или ROLE-admin, иначе ERR-forbidden (403);
  - рабочий токен агента — ROLE-writer и SEC-principal-kind#agent, иначе ERR-agent_token (403);
  - допуск вызывающего (SEC-clearance) не ниже допуска рабочего токена агента, иначе ERR-forbidden (403)
    — INV-agent-clearance-ceiling: агент читает корпус своим токеном и не должен показать больше, чем видно человеку;
  - ошибка `/whoami` (неверный или отозванный токен) возвращается с кодом и статусом SVC-wikisvc.
- Без заголовка `Authorization` отказывает `HTTPBearer` FastAPI ответом `{"detail": …}`, не форматом ERR.
- Ошибки: тело `{"error": {"code", "message", "hint", "details"}}` (как у SVC-wikisvc). Ошибка схемы тела —
  422 FastAPI `{"detail": [...]}`.
- Чужие сессии и джобы, а также объекты выше допуска вызывающего — ERR-not_found (404), не 403 (INV-404-not-403).
- Отдельного health-эндпоинта нет. FastAPI по умолчанию отдаёт `/docs` и `/openapi.json` без аутентификации.
- consumers: SVC-wiki-ui (страницы чата, задач, сверки документации).

## Синхронные вызовы

### API-wikiagent.chat.sessions.create — Открыть сессию чата
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /chat/sessions`
- request: DTO-wikiagent.NewSession
- response: 200 → DTO-wikiagent.Session (без сообщений)
- errors: ERR-profile_unknown (404) — профиля нет в `/profiles`; привязка к недоступной или
  несуществующей странице, правилу, предложению — ошибка ядра (ERR-not_found)
- side effects: пишет TBL-wikiagent.agent.chat_sessions (`owner` = person или name, `clearance` вызывающего)
- implements: FLOW-chat-plan (шаг 1)

### API-wikiagent.chat.sessions.list — Сессии вызывающего
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `GET /chat/sessions?limit=50&cursor=`
- response: 200 → `{items: DTO-wikiagent.Session[] (без messages и plan, с title — первые 120 символов первого сообщения), next_cursor: string?}`
- errors: ERR-request_invalid (`limit` вне 1..100), ERR-cursor_invalid
- notes: только свои сессии и не выше своего допуска; порядок `updated_at desc`

### API-wikiagent.chat.sessions.get — Сессия с историей
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `GET /chat/sessions/{session_id}`
- response: 200 → DTO-wikiagent.Session
- errors: ERR-not_found

### API-wikiagent.chat.messages.create — Сообщение в чат
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /chat/sessions/{session_id}/messages`, ответ `text/event-stream`
- request: DTO-wikiagent.Message
- response: 200, поток SSE: `event: status` `{"status":"planning"}`, затем ровно одно из
  `event: message` → DTO-wikiagent.ChatReply или `event: error` → тело ошибки ERR
- errors: до начала потока — ERR-not_found; в потоке — ERR-model_unavailable, ERR-model_output,
  ERR-model_context, ERR-agent_step_limit, ERR-agent_validation, ERR-agent_repair, ERR-agent_revise_target,
  ERR-quote_not_found, ERR-agent_tool_forbidden, ошибки ядра. Исключение не-`WikiError` (сеть) обрывает поток.
- side effects: пишет TBL-wikiagent.agent.chat_messages (вопрос и ответ) и `plan` сессии; TBL-wikiagent.agent.model_calls;
  вызывает EXT-llm-server; создаёт и меняет черновики через `API-wikisvc.proposals.*`, загружает транскрипт
  в `/raw`, отменяет свой черновик (`abandon`). Отправку на ревью, принятие и откат не делает: для отката
  возвращает `human_action` (INV-human-decides).
- implements: FLOW-chat-plan
- limits: одно сообщение на сессию одновременно (блокировка в памяти); вложения — до 10 путей `/raw`, их текст
  передаётся модели как недоверенные данные (INV-untrusted-external)

### API-wikiagent.jobs.ingest-book — Разобрать книгу
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/ingest-book`
- request: DTO-wikiagent.BookJob
- response: 202 → строка TBL-wikiagent.agent.jobs (`payload`, `progress` — объекты)
- errors: ERR-scope_unknown (422) — `scopes_hint` вне `/scopes` и не `*`; ошибки ядра запуска извлечения
- side effects: `POST /raw/<raw_path>/extract` в SVC-wikisvc, пишет TBL-wikiagent.agent.jobs, ставит JOB-wikiagent.ingest-book
- implements: FLOW-ingest-book
- changed: 2026-10-20 v3 (planned): поля `mode`, `domain`, `sensitivity` (DTO-wikiagent.BookJob); `mode=facts` — FLOW-fact-ingest,
  только SEC-principal-kind#human (ERR-human_required), одна активная задача `facts` (ERR-job_busy, 409);
  без `domain` или с доменом вне API-wikisvc.knowledge.domains → ERR-domain_unknown (422); без CFG-wikiagent.models.judge или
  CFG-wikiagent.models.grounding → ERR-request_invalid (422); результат — предложения по хабам и классам с `depends_on`
  (FLOW-fact-review-routing), а не одно `kind=book`; по умолчанию теперь `facts`, UI передаёт `mode` явно

### API-wikiagent.jobs.heal — Запустить самолечение
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/heal`
- request: DTO-wikiagent.HealJob
- response: 202 → строка TBL-wikiagent.agent.jobs
- errors: ERR-job_busy (409) — heal уже `pending`, `running` или `waiting_chat`
- side effects: ставит JOB-wikiagent.heal
- implements: FLOW-heal

### API-wikiagent.jobs.novelty-scan — Посчитать novelty фактов
status: planned | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/novelty-scan`
- request: JSON `{model?: string — семейство модели, ключ CFG-wikiagent.models.reference (нет — все), domain?: string — из
  API-wikisvc.knowledge.domains (нет — все)}`, лишние поля запрещены
- response: 202 → строка TBL-wikiagent.agent.jobs (`kind=novelty_scan`)
- errors: ERR-job_busy (409) — `novelty_scan` уже `pending`, `running` или `waiting_chat`; ERR-domain_unknown (422);
  ERR-request_invalid (422) — модели нет в CFG-wikiagent.models.reference или референсные модели не заданы
- side effects: ставит JOB-wikiagent.novelty-scan; результат — `API-wikisvc.knowledge.novelty`, без предложений
- implements: FLOW-novelty-scan

### API-wikiagent.docs-audit.config — Лимиты сверки документации
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `GET /docs-audit/config`
- auth: как у всех, плюс только SEC-principal-kind#human, иначе ERR-human_required (403)
- response: 200 → `{enabled: bool, max_files: int32, max_file_bytes: int32 (262144), max_total_bytes: int32}`;
  `max_total_bytes` = min(`CFG-wikiagent.docs_audit.max_total_bytes`, `MAX_UPLOAD_MB` МиБ)

### API-wikiagent.jobs.docs-audit — Сверить документацию проекта с правилами
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/docs-audit`
- auth: только человек (ERR-human_required)
- request: JSON `{project: string /^[a-z0-9][a-z0-9-]{0,63}$/, profile: string (тот же шаблон), scopes: string[] ≤ 200,
  files: [{path: относительный `.md` без `..`, ≤ 1024, text: string ≤ 256 KiB}] 1..200}`; лишние поля запрещены
  (модель `AuditRequest` в `src/wikiagent/jobs/docs_audit.py`)
- response: 202 → строка TBL-wikiagent.agent.jobs
- errors: ERR-docs_audit_disabled (403), ERR-request_invalid (400, детали валидации не возвращаются — могут
  содержать секреты), ERR-body_too_large (413), ERR-secret_detected (400) — проверка до записи в БД
- side effects: ставит JOB-wikiagent.docs-audit; результат — только находки в SVC-wikisvc, не предложения
- implements: FLOW-docs-audit

### API-wikiagent.jobs.list — Задачи вызывающего
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `GET /jobs`
- response: 200 → `{items: строка TBL-wikiagent.agent.jobs[]}` по `created_at`
- notes: свои задачи; ROLE-reviewer и ROLE-admin видят ещё задачи планировщика (`payload.scheduled`);
  задачи выше допуска скрыты. Задачи `docs_audit` для не-человека → ERR-human_required на весь ответ.
  Используется CLI-wikiagent.check как проверка готовности.

### API-wikiagent.jobs.get — Состояние задачи
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `GET /jobs/{job_id}`
- response: 200 → строка TBL-wikiagent.agent.jobs
- errors: ERR-not_found, ERR-human_required (docs_audit не человеку)

### API-wikiagent.jobs.cancel — Отменить задачу
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/{job_id}/cancel`
- response: 200 → строка TBL-wikiagent.agent.jobs со статусом `cancelled`
- errors: ERR-not_found
- notes: статус меняется сразу в БД; исполнитель останавливается на ближайшей границе шага. Повторный вызов идемпотентен.

### API-wikiagent.jobs.resume — Возобновить задачу
status: implemented | owner: SVC-wikiagent | kind: http

- endpoint: `POST /jobs/{job_id}/resume`
- response: 200 → строка TBL-wikiagent.agent.jobs
- errors: ERR-not_found, ERR-job_state (409) — статус не `failed`, `cancelled`, `paused`, `needs_outline`;
  ERR-job_busy (409) — задача уже исполняется или идёт другой heal
- notes: продолжает с чекпойнтов TBL-wikiagent.agent.job_state
- changed: 2026-10-20 v3 (planned): ERR-job_busy и для второй `novelty_scan`; режим `facts` — со стадии окна

## Команды CLI

Все команды читают FMT-wikiagent.config (`--config` или `WIKIAGENT_CONFIG`, по умолчанию `wikiagent.yaml`).

### CLI-wikiagent.serve — Запустить HTTP-сервис
status: implemented | owner: SVC-wikiagent

- usage: `wikiagent serve [--config PATH]`
- side effects: uvicorn на `bind_host:bind_port` (по умолчанию `127.0.0.1:8788`), восстановление задач `RESUMABLE`, запуск JOB-wikiagent.scheduler

### CLI-wikiagent.check — Проверить готовность развёртывания
status: implemented | owner: SVC-wikiagent

- usage: `wikiagent check [--dependencies-only] [--model] [--wait SECONDS (0..3600)]`
- output: строки готовности: ядро и токен агента, модели (`/models`, с `--model` — пробная генерация по
  JSON-схеме), API-wikiagent.jobs.list, затем `CLS-wikiagent.check_authentication`; `--dependencies-only` —
  без проверки самого агента и SSO
- exit codes: `0` — готово; `1` — не готово к концу `--wait` (повтор раз в 2s, в stderr `Not ready: <причина>`)
- notes: не печатает тела HTTP, заголовки авторизации и ответы модели; ничего не создаёт

### CLI-wikiagent.jobs — Задачи, которые агент продолжит после рестарта
status: implemented | owner: SVC-wikiagent

- usage: `wikiagent jobs`
- output: JSON-массив `[{id, kind, status, updated_at}]` со статусами `running`, `pending`, `paused`, `waiting_chat`; без payload
- consumers: SVC-updater до и после обновления

### CLI-wikiagent.eval — Оценить модель на сценариях
status: implemented | owner: SVC-wikiagent

- usage: `wikiagent eval [--role planner] [--model ALIAS] [--scenarios tests/scenarios] [--out FILE]`
- output: JSON-отчёт `CLS-wikiagent.evaluate_scenarios` в stdout и в `--out`
- side effects: вызывает EXT-llm-server, пишет TBL-wikiagent.agent.model_calls

## Структуры данных

### DTO-wikiagent.NewSession — Запрос новой сессии
status: implemented | owner: SVC-wikiagent

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `bind.type` | enum(page\|rule\|proposal\|none) | нет | `none` | к чему привязан чат |
| `bind.id` | string | нет | `^[a-z0-9-]*$`, `""` | ID страницы, правила или предложения |
| `profile` | string? | нет | есть в `/profiles` | профиль правил для областей |

### DTO-wikiagent.Message — Сообщение человека
status: implemented | owner: SVC-wikiagent

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `text` | string | да | 1..100000 | текст |
| `attachments` | string[] | нет | ≤ 10 | пути в `/raw`, текст добавляется как недоверенные данные |

### DTO-wikiagent.BookJob — Запрос разбора книги
status: implemented | owner: SVC-wikiagent

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `raw_path` | string | да | `^(library\|raw)/[a-zA-Z0-9_./-]+$` | файл книги в SVC-wikisvc |
| `title` | string? | нет | 3..120 | название |
| `author` | string? | нет | ≤ 200 | автор |
| `year` | string? | нет | ≤ 10 | год |
| `scopes_hint` | string[] | нет | ≤ 20, из `/scopes` или `*` | подсказка областей |
| `mode` | enum(facts\|rules) | нет | `facts` (решение Q-kb-ingest-rules-mode) | факты слоя знаний или кандидаты правил (v3 planned) |
| `domain` | string? | для `facts` | из API-wikisvc.knowledge.domains | домен фактов и новых хабов, INV-one-domain-per-page (v3 planned) |
| `sensitivity` | enum(public\|internal\|restricted) | нет | `restricted` | фактов и хабов, наследует источник; понижение или `public` → класс `queue` (v3 draft, решение Q-kb-ingest-sensitivity) |

### DTO-wikiagent.HealJob — Запрос самолечения
status: implemented | owner: SVC-wikiagent

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `scope` | enum(changed\|full) | нет | `changed` | только изменённые страницы или весь корпус |

### DTO-wikiagent.Session — Сессия чата
status: implemented | owner: SVC-wikiagent

Колонки TBL-wikiagent.agent.chat_sessions, где `bind` и `plan` (DTO-wikiagent.Plan?) — объекты, плюс
`messages: [{role: enum(user|assistant), text, plan: DTO-wikiagent.Plan?, created_at: timestamp}]`.

### DTO-wikiagent.ChatReply — Ответ чата для интерфейса
status: implemented | owner: SVC-wikiagent

| поле | тип | обяз. | смысл |
|---|---|---|---|
| `text` | string | да | текст человеку; уточнение модели — только короткий русский вопрос ≤ 300 символов, иначе шаблон |
| `plan` | DTO-wikiagent.Plan? | нет | первый (или единственный) план |
| `plans` | DTO-wikiagent.Plan[]? | нет | все планы, если пунктов больше 10 |
| `human_action` | `{method: "POST", path: "/api/v1/proposals/<pid>/revert"}`? | нет | действие, которое подтверждает только человек |

### DTO-wikiagent.Plan — План изменений, записанный в notes черновика
status: implemented | owner: SVC-wikiagent

| поле | тип | смысл |
|---|---|---|
| `items` | `{n, action: enum(create_rule\|patch_rule\|supersede_rule\|noop_duplicate\|flag_page\|revise_page), target, thesis?, level?, owner?, scopes?, reason, confidence?, claim?, relations?, deprecate?, headings?}`[] ≤ 10 | пункты |
| `questions` | `{id, text, options: string[]}`[] ≤ 3 | вопросы человеку (область, конфликт) |
| `assumptions` | string[] | допущения агента |
| `proposal` | string? | `pid` черновика в SVC-wikisvc; `null` — правок нет |
| `owner` | string? | кто может продолжать черновик через агента |
| `source` | string? | ID source-страницы чата |
| `validation`, `impact`, `preview_diff` | json | ответы `API-wikisvc.proposals.*` (validate, impact, diff) |
| `summary` | string | одна строка итога |
| `accept_body` | `{promote: [{id, level, priority: 3, applies_to, owner?}], deprecate: [{id, reason}]}` | готовое тело для принятия человеком |
| `needs_double_confirm` | bool | must-правило, затронуто must или больше 5 целей |
| `cancelled` | bool? | черновик отменён |

### DTO-wikiagent.Intent — Ответ модели: намерение сообщения
status: implemented | owner: SVC-wikiagent

`{intent: enum(intake|question|edit|revise|revert|cancel|other), clarification: string?}`, лишние поля запрещены.

### DTO-wikiagent.Claims — Ответ модели: утверждения из фразы
status: implemented | owner: SVC-wikiagent

- `claims`: ≤ 100 × `{text 1..4000, kind: enum(rule|not_rule), id: ^rule-[a-z0-9]+(-[a-z0-9]+)*$, title 3..120,
  thesis 20..160, category: enum(code-style|architecture|logging|errors|security|testing|stack|git|build-ci|docs|process),
  scopes_guess: string[], level_guess: enum(must|should), owner: string?, aliases: string[] 2..10, rationale 1..4000,
  good_example ≤ 4000, bad_example ≤ 4000, impact_terms ≤ 10, ambiguous_scope: bool}`
- `remove_ids`: string[] ≤ 10 — кандидаты прошлого плана к удалению

### DTO-wikiagent.Classification — Ответ модели: связи утверждения с правилами
status: implemented | owner: SVC-wikiagent

`relations`: 1..20 × `{relation: enum(new|duplicate_of|refines|extends_scope|conflicts_with|supersedes|affects),
target: string?, confidence: float64 0..1, quote ≤ 4000, reason 1..4000}`; проверка — `CLS-wikiagent.verify`.

### DTO-wikiagent.Repairs — Ответ модели: исправления черновика после validate
status: implemented | owner: SVC-wikiagent

`pages`: ≤ 10 × `{id, title?, summary? 20..160, body_md?, aliases?: string[], applies_to?: string[]}`; только существующие страницы черновика.

### DTO-wikiagent.Located — Ответ модели: какие разделы править
status: implemented | owner: SVC-wikiagent

`targets`: ≤ 5 × `{page, headings: string[] 1..5}`.

### DTO-wikiagent.Revisions — Ответ модели: правки разделов
status: implemented | owner: SVC-wikiagent

`pages`: ≤ 5 × `{page, summary 10..160, edits: 1..10 × {op: enum(replace_section|add_section|replace_text),
heading?, after?, old?, expect_count ≥ 1, text 1..4000 без заголовков markdown}}`; `replace_text` требует `old`, остальные — `heading`.

### DTO-wikiagent.ChapterResult — Ответ модели: кандидаты правил из куска главы
status: implemented | owner: SVC-wikiagent

Модель `ChapterResult` в `src/wikiagent/jobs/ingest_book.py`: `candidates` ≤ 10 × `{title 3..120, thesis 20..160,
category (как в DTO-wikiagent.Claims), applies_to_suggestion: string[] ≥ 1, level_suggestion: enum(idea|should),
rationale 1..4000, locator: {unit: enum(стр.|гл.), start ≥ 1, end?}, quote 1..1000 и ≤ 30 слов, aliases 2..10,
good_example ≤ 2000, bad_example ≤ 2000, relations ≤ 10 × {rule_id, type: enum(refines|conflicts_with|supersedes|depends_on)}}`;
`state_summary` ≤ 3750; `open_references` ≤ 20.

- changed: 2026-10-20 v3 (planned): остаётся для режима `rules`; в режиме `facts` заменён DTO-wikiagent.ChapterResult.v2

### DTO-wikiagent.ChapterResult.v2 — Ответ модели: кандидаты фактов из окна
status: planned | owner: SVC-wikiagent

`candidates` ≤ CFG-wikiagent.ingest.max_candidates_per_window (40) × DTO-wikiagent.FactCandidate; `state_summary` ≤
1500 токенов (символы по NFR-token-estimate); `open_references` ≤ 20. Ответ PRM-wikiagent.fact_extract.

### DTO-wikiagent.FactCandidate — Кандидат в факт (ТЗ §8.3)
status: planned | owner: SVC-wikiagent

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `claim` | string | да | 20..200 символов, одно минимальное утверждение без контекстных обёрток (INV-claim-minimal) | L0, единица дедупликации |
| `summary` | string | да | `claim`, деконтекстуализированный «молекулярно»; границы — FMT-wikisvc-core.fact | L1, читает ревьюер |
| `kind` | enum(definition\|mechanism\|constraint\|tradeoff\|number\|convention\|api\|pitfall\|comparison\|step\|snippet) | да | «you should…» книги → `convention` | тип факта |
| `evidence` | `{locator: {unit: enum(стр.\|гл.), start ≥ 1, end?}, quote: string}` | да | `quote` 2..30 слов, дословно | подстрока — CLS-wikiagent.Windows, следование — CLS-wikiagent.GroundingJudge; провал → `confidence: inferred` |
| `suggested_topic` | `{id?: string, title: string 3..120}` | да | `id` — только из списка хабов окна | понятие-хаб для CLS-wikiagent.HubBinder |
| `suggested_scopes` | string[] | нет | из `/scopes` | scopes факта сверх домена |
| `valid_for` | string? | для `number`, `api`, `pitfall` | иначе повтор с ERR-valid_for_missing | условие применимости |
| `example` | string? | для `snippet` | код — только у `snippet`; с книгой не сверяется → класс `queue` | листинг в разделе `Example` |
| `number` | `{value, unit, conditions, measured_at?}`? | для `number` | по FMT-wikisvc-core.fact | измеренное значение |

### DTO-wikiagent.JudgeVerdict — Вердикт судьи по паре фактов
status: planned | owner: SVC-wikiagent

| поле | тип | смысл |
|---|---|---|
| `verdict` | enum(duplicate\|refines\|contradicts\|independent) | A ⊨ B и B ⊨ A → `duplicate`; в одну сторону → `refines`; противоречие → `contradicts`; иначе `independent` (ТЗ §8.4) |
| `direction` | enum(a_refines_b\|b_refines_a)? | только для `refines`: частный уточняет общий |
| `scores` | `{entail_ab, entail_ba, contradiction}`? float64 0..1 | вероятности NLI; у LLM-судьи нет |
| `source` | enum(nli\|llm) | кто вынес итоговый вердикт |
| `model`, `confidence` | string, float64 | модель судьи и уверенность — поля `API-wikisvc.knowledge.verdicts`; ключ кэша |
| `explanation` | string? ≤ 2000 | только у LLM (PRM-wikiagent.fact_judge) |

### DTO-wikiagent.NoveltyResult — Novelty факта для референсной модели
status: planned | owner: SVC-wikiagent

| поле | тип | смысл |
|---|---|---|
| `fact_id`, `claim_hash` | string | факт и sha256 нормализованного `claim` |
| `model` | string | семейство модели, ключ CFG-wikiagent.models.reference; пишется в `API-wikisvc.knowledge.novelty` |
| `question`, `paraphrases` | string, string[] 2..3 | cloze-вопрос и формулировки (PRM-wikiagent.novelty_cloze) |
| `samples`, `hits`, `share` | int32, int32, float64 0..1 | ответов, попаданий, доля |
| `bucket` | enum(common\|differs\|unique) | по CFG-wikiagent.novelty.common_threshold и CFG-wikiagent.novelty.unique_threshold |
| `judge`, `prompt_version` | enum(nli\|llm), string | как сравнивали ответы; версия промптов |

### DTO-wikiagent.BookReview — Ответ модели: обзор кандидатов книги
status: implemented | owner: SVC-wikiagent

Модель `BookReview` в `src/wikiagent/jobs/ingest_book.py`: `merge` ≤ 20 × `{keep, drop}`, `links` ≤ 30 ×
`{src, target, rel: enum(refines|conflicts_with|supersedes|depends_on)}`, `key_ideas` ≤ 15 × `{id, text ≤ 160}`.

### DTO-wikiagent.Verdict — Ответ модели: вердикт лекаря по паре страниц
status: implemented | owner: SVC-wikiagent

Модель `Verdict` в `src/wikiagent/heal/verdicts.py`: `relation: enum(none|duplicate|refines|conflicts|scope_mismatch)`,
`confidence` 0..1, `explanation` ≤ 4000, `evidence` ≤ 10 × `{page, quote 1..4000}`, `suggested_fix` ≤ 10 ×
`{page, op: enum(set_field|add_relation|remove_relation|append_to_section), field?: enum(summary|applies_to|aliases|category),
value?, rel?, target?, heading?, text?}`; хранится в TBL-wikiagent.agent.pair_checks#verdict.

- changed: 2026-10-20 v3 (planned): для фактов `conflicts` = `contradicts`; `field` += `confidence`, `valid_for`; `rel` += `contradicts`, `replaces` (`origin: inferred`; `replaced_by` не пишется)

### DTO-wikiagent.AuditVerdict — Ответ модели: вердикт сверки файла с правилом
status: implemented | owner: SVC-wikiagent

Модель `AuditVerdict` в `src/wikiagent/jobs/docs_audit.py`: `relation: enum(none|violation|wording)`, `confidence` 0..1,
`summary` 3..500, `line ≥ 1`, `project_quote` ≤ 4000, `policy_quote` ≤ 4000, `action` ≤ 2000.

## Форматы файлов

### FMT-wikiagent.config — Конфиг агента `wikiagent.yaml`
status: implemented | owner: SVC-wikiagent

- kind: YAML, UTF-8; путь — `wikiagent serve --config`, иначе `CFG-wikiagent.WIKIAGENT_CONFIG`
- schema: модель `AgentConfig` в `src/wikiagent/config.py`, лишние ключи верхнего уровня и `docs_audit` запрещены;
  поля — `CFG-wikiagent.*` (`runtime.md`). Обязательно только `models` ровно с ролями `planner`, `reviewer`, `chat`.
- secrets: значения токенов в файле не хранятся, только имена переменных окружения (`wikisvc.token_env`, `models.*.token_env`)
- example: боевой файл `deploy/linux/wikiagent.yaml`
- producer / consumer: оператор (ACT-operator) пишет, CLI-wikiagent.* читают при старте
- changed: 2026-10-20 v3 (planned): разделы `ingest`, `novelty`, `judge`; необязательные `models.judge`, `models.reference`
