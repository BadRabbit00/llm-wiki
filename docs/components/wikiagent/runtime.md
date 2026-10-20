# wikiagent: фоновые задачи и настройки

## Фоновые задачи

Все задачи живут внутри процесса `wikiagent serve` (CLI-wikiagent.serve): пул потоков и поток
планировщика стартуют в `lifespan` FastAPI (`src/wikiagent/api.py`). Строка задачи — в
TBL-wikiagent.agent.jobs (статусы — STATE-job: `pending`, `running`, `waiting_chat`, `paused`,
`cancelled`, `failed`, `done`, `awaiting_review`, `needs_outline`), контрольные точки — в
TBL-wikiagent.agent.job_state. Расчёт на один экземпляр сервиса (INV-single-node).

Политики: rule-arch-single-scheduler, rule-stack-background-tasks, rule-arch-workers-parallel-safe,
rule-arch-idempotent-consumers (отступления — см. RISK в отчёте документирования).

### JOB-wikiagent.runner — Очередь и исполнитель задач агента
status: implemented | owner: SVC-wikiagent

- trigger: `JobRunner.start` из API-wikiagent.jobs.ingest-book, API-wikiagent.jobs.heal,
  API-wikiagent.jobs.docs-audit, API-wikiagent.jobs.resume и JOB-wikiagent.scheduler;
  `JobRunner.recover` при старте процесса перезапускает задачи в статусах `running`, `pending`,
  `paused`, `waiting_chat` (их же перед обновлением читает SVC-updater через CLI-wikiagent.jobs)
- does: по `kind` строки запускает JOB-wikiagent.ingest-book, JOB-wikiagent.heal или
  JOB-wikiagent.docs-audit; `boundary(job_id)` между шагами останавливает задачу при отмене
  (API-wikiagent.jobs.cancel) или остановке процесса (статус `paused`)
- touches: читает и пишет TBL-wikiagent.agent.jobs
- concurrency: `ThreadPoolExecutor(max_workers=2)`; один `job_id` не исполняется дважды (множество
  `active` под `RLock`); `docs_audit` идут по одной (`audit_lock`); `heal` — только одна активная,
  вторая → ERR-job_busy (409). Запросы к модели всех задач и чата сериализует `PriorityGate`
  (`src/wikiagent/jobs/priority.py`): чат и книга идут раньше `heal_*` и `docs_audit`
- timeout / retries: общего тайм-аута нет; автоматических повторов нет, кроме `recover` при рестарте
- on failure: исключение → статус `failed`, в `jobs.error` только код ошибки (WikiError) или имя
  класса исключения; возобновление — API-wikiagent.jobs.resume (статусы `failed`, `cancelled`,
  `paused`, `needs_outline`). Логов и алертов исполнитель не пишет
- changed: 2026-10-20 v3 (planned): `kind=novelty_scan` → JOB-wikiagent.novelty-scan; одна активная `novelty_scan`,
  вторая → ERR-job_busy (409); resume — как у `heal`

### JOB-wikiagent.ingest-book — Кандидаты правил из книги
status: implemented | owner: SVC-wikiagent

- trigger: API-wikiagent.jobs.ingest-book (`kind=ingest_book`), FLOW-ingest-book
- does: запускает извлечение книги в wikisvc и ждёт `done`; плохое оглавление → `needs_outline`.
  Открывает предложение `kind: book` и страницу `source`, по главам и кускам вызывает
  PRM-wikiagent.book_chapter, проверяет кандидатов PRM-wikiagent.classify, пишет инертные правила
  в предложение; второй проход PRM-wikiagent.book_review (пачки по 40) — слияния, связи, ключевые
  идеи; валидирует (PRM-wikiagent.repair_validation) и отправляет на ревью → `awaiting_review`
- touches: TBL-wikiagent.agent.jobs, TBL-wikiagent.agent.job_state, TBL-wikiagent.agent.model_calls;
  API-wikisvc.* (`/raw/{path}/extract|outline|text`, `/scopes`, `/rules`, `/rules/related`,
  `/pages/{id}`, `/proposals…` create/pages/validate/submit); EXT-llm-server
- idempotent: да. Контрольные точки в `job_state`: `proposal`, `source_written`, ответ модели на
  каждый кусок `chapter:<n>:<pages>:<offset>`, `classification:<hash>`, `candidate_ids`, `candidates`,
  `errors`, `context`, `chapter_done`, `review:<start>`, `report`. Потерянное предложение находится
  по метке `Job <id>` в описании; ID кандидата `rule-<category>-<slug>` с суффиксом при коллизии;
  отклонённые (`deprecated`) идеи и дубли пропускаются. Предложение уже `submitted`/`accepted` →
  задача сразу завершается
- concurrency: несколько книг могут идти параллельно в пределах пула JOB-wikiagent.runner
- timeout / retries: ожидание извлечения ≤ `models.planner.timeout_seconds + 600s`, иначе
  ERR-extract_timeout; модель — CFG-wikiagent.limits.retries на вызов, тайм-аут запроса
  `timeout_seconds` роли
- on failure: ERR-model_unavailable и ошибки второго прохода → `failed`, resume продолжит с
  последней контрольной точки; невалидный ответ по главе — глава пропускается, код в `progress.errors`
- changed: 2026-10-20 v3 (planned), оба режима (ТЗ §11.8): ответ `/rules/related` чекпоинтится вместе с результатом окна;
  кэш страниц вики на главу; множество занятых ID — один раз на запуск, пополняется локально; цитата сверяется с
  excerpt окна в памяти, к ядру — только при промахе; `context()` режет `state` арифметически, без O(n²) `json.dumps`
- changed: 2026-10-20 v3 (planned): режим `facts` — по умолчанию (DTO-wikiagent.BookJob#mode, решение Q-kb-ingest-rules-mode):
  книга → факты по хабам, FLOW-fact-ingest, CLS-wikiagent.FactIngest. Запускает только SEC-principal-kind#human
  (ERR-human_required), одна активная задача `mode=facts` (вторая — ERR-job_busy); лимиты на задачу
  CFG-wikiagent.ingest.max_windows_per_job и CFG-wikiagent.ingest.max_model_calls_per_job (исчерпан → `paused`,
  `budget_exhausted`). Владелец задачи — в описании каждого предложения `kind=book`; класс `auto` — только у задач
  человека (INV-auto-class-scope). `sensitivity` фактов и новых хабов наследует источник (DTO-wikiagent.BookJob#sensitivity,
  по умолчанию `restricted`); понижение или `public` — класс `queue` (решение Q-kb-ingest-sensitivity, RISK-kb-agent-uploaded-book):
  1. **Один раз на запуск** (чекпоинт `skeleton`): извлечение и оглавление — как в `rules`; хабы и tech домена —
     `API-wikisvc.knowledge.topics` (≤ CFG-wikiagent.ingest.hub_list_max); few-shot — CFG-wikiagent.ingest.fewshot_facts
     фактов того же домена, `verified` раньше `draft`, порядок INV-canonical-order (решение Q-kb-ingest-defaults).
     PRM-wikiagent.hub_skeleton: оглавление → хабы по понятиям, не по главам. Страница `source` с `covers`
     (FMT-wikisvc-core.source) и новые хабы скелета — первое предложение; остальные несут `depends_on: [pid]` на него
     (решение Q-kb-proposal-dependencies, ERR-proposal_dependency).
  2. **Окна** (CLS-wikiagent.Windows): раздел главы CFG-wikiagent.ingest.window_tokens с перекрытием
     CFG-wikiagent.ingest.overlap_paragraphs; токены → символы по NFR-token-estimate.
  3. **Извлечение** (`extracted`): PRM-wikiagent.fact_extract → DTO-wikiagent.ChapterResult.v2, ≤
     CFG-wikiagent.ingest.max_candidates_per_window кандидатов. Вход: текст окна, список хабов, `state` ≤
     CFG-wikiagent.limits.state_tokens, few-shot, словарь scopes. Цитата — подстрока excerpt окна (при промахе — по
     локатору через API-wikisvc.raw.text); не нашлась → `confidence: inferred`.
  4. **Grounding** (`grounded`): CLS-wikiagent.GroundingJudge — следует ли `claim` из цитаты и её абзаца (не только
     подстрока); провал → `confidence: inferred` и класс `queue`.
  5. **Хаб** (`bound`): CLS-wikiagent.HubBinder — `about` на найденный хаб или новый хаб `draft` в первом предложении.
  6. **Судья** (`judged`): CLS-wikiagent.Dedup, FLOW-dedup-judge: `API-wikisvc.knowledge.similar` (`include_pending=true` —
     видны черновики всех открытых предложений `kind=book`, решение Q-kb-knn-endpoint) ≥ CFG-wikiagent.ingest.dup_cosine,
     ≤ CFG-wikiagent.ingest.dup_k → каскад CLS-wikiagent.Judge; каждый вердикт, включая `independent`, — в
     `API-wikisvc.knowledge.verdicts` (решение Q-kb-judge-verdict-visibility). Судья недоступен → задача не падает:
     кандидат с kNN-соседями без вердикта — `queue` с `W_POSSIBLE_DUPLICATE` (ТЗ §9, rule-arch-outgoing-call-resilience).
     `duplicate` — факт не создаётся, существующему — `add_source` + цитата (PATCH, `queue`); `refines` — оба остаются,
     ребро `refines` от частного к общему; `contradicts` — ребро `contradicts`, обоим `confidence: contested`, класс `pair`.
  7. **Связи** (`linked`): PRM-wikiagent.fact_links — `applies_with`/`precedes` между новыми фактами окна и найденными
     (kNN, `ask`) с `note` и `origin: extracted` (DTO-wikisvc-core.RelationRef); id — только из этого набора.
  8. **Запись** (`written`): CLS-wikiagent.route_fact → STATE-fact-review-class; CLS-wikiagent.FactProposals кладёт
     факт (ID `f-<последний сегмент домена>-<slug claim>`, суффикс при коллизии) в предложение (хаб, класс) ≤
     CFG-wikiagent.ingest.proposal_max_facts фактов и дописывает строку `[[f-…]]` в `## Facts` хаба (FMT-wikisvc-core.topic;
     разные предложения сливаются по строкам). Правки существующих страниц → `queue`, кроме этой строки (INV-auto-class-scope).
  9. **Итог**: все предложения → `submit`; `auto`-блок принимает человек одним действием без построчного ревью
     (FLOW-fact-review-routing, решение Q-kb-auto-accept-human-decides); отчёт — метрики NFR-ingest-quality и выборка
     ~50 фактов главы на split/merge (ТЗ §8.6); статус `awaiting_review`.
  - touches v3: TBL-wikiagent.agent.ingest_windows, TBL-wikiagent.agent.fact_verdicts (кэш), `API-wikisvc.knowledge.ask`,
    `API-wikisvc.knowledge.similar`, `API-wikisvc.knowledge.verdicts`, API-wikisvc.raw.text, API-wikisvc.proposals.*;
    `/rules/related` и PRM-wikiagent.classify в режиме `facts` не вызываются
  - idempotent v3: стадия окна в TBL-wikiagent.agent.ingest_windows — resume не повторяет пройденные стадии
    (rule-arch-idempotent-consumers); ID факта — по sha256 нормализованного `claim` в `job_state.fact_ids`;
    предложения — по метке; повтор окна видит свои черновики через `include_pending` и не создаёт дубль
  - on failure v3: ERR-embeddings_unavailable, ERR-model_unavailable → `failed`, resume с окна и стадии; недоступный
    судья — не отказ (шаг 6); лимиты задачи → `paused` (защита от подготовленной книги и захвата модели:
    RISK-kb-agent-uploaded-book, RISK-kb-ingest-starves-background)

### JOB-wikiagent.heal — Самолечение: поиск несостыковок правил
status: implemented | owner: SVC-wikiagent

- trigger: API-wikiagent.jobs.heal (`scope: changed|full`) или JOB-wikiagent.scheduler; FLOW-heal
- does: берёт правила `candidate,active,deprecated`, выбирает пары (изменённые с прошлого прохода
  + соседи по графу + поиск `k_candidates` + та же категория; ≤ 20 пар на страницу, сначала `must`),
  по каждой паре — PRM-wikiagent.heal_pair, для конфликта с `must` — PRM-wikiagent.heal_review.
  Находки с уверенностью ≥ `heal.confidence_threshold` пишет в wikisvc; при `suggested_fix` —
  предложение `kind: heal` и отправка на ревью. Затем детерминированные проверки без модели
  (`/lint`, `W_CANDIDATE_STALE`, `W_RULE_UNUSED`, `W_RULE_VIOLATED`, покрытие категории `errors`)
- touches: TBL-wikiagent.agent.pair_checks, TBL-wikiagent.agent.job_state, TBL-wikiagent.agent.jobs,
  TBL-wikiagent.agent.model_calls; API-wikisvc.* (`/rules`, `/pages/{id}`, `/graph/neighbors/{id}`,
  `/search`, `/lint`, `/profiles`, `/findings`, `/proposals…`); EXT-llm-server
- idempotent: да. Кэш пары по хешам версий обеих страниц в `pair_checks`; страница изменилась во время
  проверки → пара не кэшируется (`retry_needed`). Глобальные отметки в `job_state` с `job_id='heal'`:
  `hashes`, `last_run`, `last_full` — пишутся только после полного прохода. Находки
  дедуплицирует wikisvc по `fingerprint`; предложение ищется по метке `Finding <fingerprint>`
- concurrency: одна активная задача `heal` (ERR-job_busy); на каждом шаге ждёт, пока в чате нет активных
  сообщений (статус `waiting_chat`)
- timeout / retries: бюджеты CFG-wikiagent.heal.max_model_calls_per_run,
  CFG-wikiagent.heal.max_model_calls_per_day (сутки по UTC, считаются по `model_calls` задач `heal_*`),
  CFG-wikiagent.heal.max_findings_per_run; перед парой резервируется `retries` (×2 при `must`) вызовов
- on failure: бюджет исчерпан или пара осталась непроверенной → `paused` с отчётом
  (`budget_exhausted`, `retry_needed`); ERR-model_output → кэшируется вердикт `none`; прочие
  ошибки → `failed` через JOB-wikiagent.runner
- changed: 2026-10-20 v3 (planned): heal для `fact` (ТЗ §8.6, §11.9), FLOW-heal, FLOW-dedup-judge:
  - пары фактов (`status` не `outdated`, INV-invalidate-not-delete): партнёры — `API-wikisvc.knowledge.similar`
    (CFG-wikiagent.ingest.dup_cosine, CFG-wikiagent.ingest.dup_k), не поиск по `summary`; массовый NLI — лёгкая модель
    MDL-nli-judge-light (CLS-wikiagent.Judge), `independent` отсеивается; PRM-wikiagent.heal_pair видит только
    `duplicate`/`refines`/`contradicts`; вердикты, включая `independent`, — в `API-wikisvc.knowledge.verdicts`;
  - исход — находка и предложение `kind: heal` на ревью человеку (`queue`: правки существующих страниц): дубль между
    книгами — выжившему `add_source` и `replaces: [второй]`, `replaced_by` во frontmatter не пишется (E_REL_UNKNOWN),
    второй становится `outdated` производно; противоречие — рёбра `contradicts` с `origin: inferred` и `confidence:
    contested` обоим (класс `pair`); уточнение — `refines` с `origin: inferred`. Удалений нет;
  - оптимизации §11.9: соседи изменённой страницы — один запрос; индекс `(category, scope) → ids` строится раз
    за запуск; дневной счётчик `model_calls` читается раз за запуск и дальше растёт в памяти;
  - бюджеты CFG-wikiagent.heal.* считают только вызовы LLM; NLI в процессе их не расходует, число его пар ограничено
    ≤ 20 пар на страницу; судья недоступен → пара пропускается до следующего запуска (`judge_unavailable` в отчёте)

### JOB-wikiagent.docs-audit — Сверка документации проекта с политиками
status: implemented | owner: SVC-wikiagent

- trigger: API-wikiagent.jobs.docs-audit, только сессия человека (ERR-human_required) и при
  CFG-wikiagent.docs_audit.enabled (иначе ERR-docs_audit_disabled); FLOW-docs-audit
- does: компилирует политики профиля (`/policies/compile`), сопоставляет правила с присланными `.md`
  файлами по частям пути (`SECTIONS`; ≤ 8 файлов на правило, сначала `must`); по каждой паре вызывает PRM-wikiagent.docs_audit,
  находки с уверенностью ≥ `docs_audit.confidence_threshold` пишет в wikisvc (`kind: docs-audit`).
  Предложений и raw не создаёт → `awaiting_review`
- touches: TBL-wikiagent.agent.jobs (payload с текстами файлов), TBL-wikiagent.agent.job_state,
  TBL-wikiagent.agent.pair_checks, TBL-wikiagent.agent.model_calls; API-wikisvc.* (`/policies/compile`,
  `/pages/{id}`, `/findings`); EXT-llm-server
- idempotent: да. Кэш пары в `pair_checks` по (`docs_audit:<rule>`, версия компиляции,
  `<project>/<path>`, sha256 текста); вердикт сохраняется в `job_state.pending` до POST находки,
  повтор POST дедуплицирует wikisvc по `fingerprint`
- concurrency: по одной (`audit_lock` в JOB-wikiagent.runner)
- timeout / retries: бюджеты CFG-wikiagent.docs_audit.max_model_calls_per_run,
  CFG-wikiagent.docs_audit.max_model_calls_per_day, CFG-wikiagent.docs_audit.max_findings_per_run;
  попыток на пару — не больше `limits.retries` и остатка бюджета
- on failure: бюджет исчерпан → `paused`; политики изменились во время сверки → ERR-audit_stale
  (`failed`, resume); ERR-model_output → вердикт `none`, сохраняется только код

### JOB-wikiagent.scheduler — Запуск самолечения в простое
status: implemented | owner: SVC-wikiagent

- trigger: поток `wikiagent-idle`, проверка каждые 30s (`Scheduler.tick`)
- does: запускает JOB-wikiagent.heal от имени рабочего токена агента (`scheduled: true`,
  видна ролям `reviewer`/`admin`), если: CFG-wikiagent.heal.enabled; текущее время в одном из
  CFG-wikiagent.heal.windows (**локальное время сервера**; пустой список = всегда); нет активных
  сообщений чата и задач `pending|running|waiting_chat`; с последней активности (чат, задачи, старт
  процесса) прошло ≥ CFG-wikiagent.heal.idle_minutes. Область `full`, если с `last_full` прошло
  ≥ CFG-wikiagent.heal.full_sweep_days, иначе `changed` — и только если есть изменённые правила
- touches: читает TBL-wikiagent.agent.jobs, TBL-wikiagent.agent.chat_sessions,
  TBL-wikiagent.agent.job_state; API-wikisvc.* (`/rules`, `/whoami`)
- idempotent: да — не запускает вторую задачу при активной
- concurrency: один поток на процесс; несколько процессов не координируются
- on failure: исключение тика пишется в лог предупреждением без деталей, следующий тик через 30s
- дневные лимиты вызовов модели проверяет JOB-wikiagent.heal, не планировщик
- changed: 2026-10-20 v3 (planned): если на тике heal не запущен (выключен или нечего проверять), при тех же условиях
  окна и простоя (`heal.windows`, `heal.idle_minutes` — общие, решение Q-kb-novelty-defaults) запускает
  JOB-wikiagent.novelty-scan (`scheduled: true`), когда CFG-wikiagent.novelty.enabled, есть работа (ниже) и не исчерпан
  CFG-wikiagent.novelty.max_calls_per_day. По-прежнему не больше одной фоновой задачи одновременно

### JOB-wikiagent.novelty-scan — Novelty фактов для референсной модели
status: planned | owner: SVC-wikiagent

- trigger: API-wikiagent.jobs.novelty-scan или JOB-wikiagent.scheduler; FLOW-novelty-scan (ТЗ §8.5, ADR-0026)
- scope (лениво, решение Q-kb-novelty-defaults и Q-kb-novelty-reference-model): (1) факты из кандидатов brief профиля
  для семейства модели, которое клиент впервые запросил в `get_brief` (очередь ведёт ядро, агент читает её
  `GET /api/v1/knowledge/novelty?model_family=…` — часть `API-wikisvc.knowledge.novelty`); (2) остальные факты — только локальной моделью в фоне. Ключ — семейство модели
  (`claude-sonnet`, `gemma-31b`), ключ CFG-wikiagent.models.reference; пропускаются факты с результатом для
  `(fact, family, content_hash)`
- does: на факт — PRM-wikiagent.novelty_cloze → cloze-вопрос и CFG-wikiagent.novelty.paraphrases формулировок; на каждую —
  CFG-wikiagent.novelty.samples ответов PRM-wikiagent.novelty_answer при CFG-wikiagent.novelty.temperature, без
  контекста вики и инструментов (closed-book); каждый ответ сравнивает с `claim` NLI CLS-wikiagent.Judge (попадание —
  ответ влечёт `claim`). Доля ≥ CFG-wikiagent.novelty.common_threshold → `common`, < CFG-wikiagent.novelty.unique_threshold
  → `unique`, иначе `differs`. Результат — `API-wikisvc.knowledge.novelty` (производные данные ядра, без предложений,
  `verified` не меняется; решение Q-kb-novelty-write-path); TBL-wikiagent.agent.novelty_results — локальный кэш.
  Самооценку модели не спрашивает
- cost: 1 + 2 × 5 = 11 вызовов LLM на факт при умолчаниях (ТЗ §8.5: 10–30); сравнение — NLI, вызовов LLM не тратит
- touches: TBL-wikiagent.agent.novelty_results, TBL-wikiagent.agent.jobs, TBL-wikiagent.agent.model_calls;
  `API-wikisvc.knowledge.novelty`, API-wikisvc.pages.*; EXT-llm-server или внешний провайдер (роль `reference`), MOD-wikiagent.judge
- idempotent: да — ключ `(fact, family, content_hash)`; результат пишется после всех сэмплов, повторная запись в ядро
  того же ключа идемпотентна; прерванный факт считается заново
- concurrency: одна активная `novelty_scan` (ERR-job_busy); вызовы модели — фон `PriorityGate`; ждёт чат (`waiting_chat`)
- timeout / retries: перед фактом резервирует все его вызовы; не влезает в CFG-wikiagent.novelty.max_calls_per_day →
  `paused` (`budget_exhausted`)
- security: ответы референсной модели — недоверенные данные (INV-untrusted-external), идут только в судью. Внешняя
  модель — официальный SDK за интерфейсом провайдера (rule-stack-llm-providers), только `https`, `token_env`; наружу
  уходят только факты `sensitivity: public` — фильтр в коде; `internal`/`restricted` — только локальные модели
- on failure: ERR-model_unavailable → `failed`, resume; ERR-model_output на cloze → факт пропускается, код в отчёте

## Настройки

Источник — YAML FMT-wikiagent.config по пути CFG-wikiagent.WIKIAGENT_CONFIG; разбирается
`load_config` в `src/wikiagent/config.py` (pydantic). Неизвестные ключи верхнего уровня и
`docs_audit` — ошибка старта; во вложенных `wikisvc`, `models.<role>`, `limits`, `heal` лишние ключи
молча игнорируются. Значение из YAML важнее переменной окружения. Политики: rule-arch-config-module,
rule-deploy-config-from-env, rule-secrets-env-default, rule-secrets-required-at-start.

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-wikiagent.WIKIAGENT_CONFIG | SVC-wikiagent | env | string | `wikiagent.yaml` (от рабочего каталога) | нет | нет | путь к YAML-конфигу; `serve --config` важнее | implemented |
| CFG-wikiagent.WIKIAGENT_STATE_DIR | SVC-wikiagent | env | string | `.wikiagent` | нет | нет | значение по умолчанию для `state_dir` | implemented |
| CFG-wikiagent.WIKIAGENT_TOKEN | SVC-wikiagent | secret | string | нет | да | да | writer-токен `kind=agent` к wikisvc (SEC-secrets); имя задаёт `wikisvc.token_env`; без него уходит пустой Bearer | implemented |
| CFG-wikiagent.MAX_UPLOAD_MB | SVC-wikiagent | env | int32 | `25` | нет | нет | значение по умолчанию для `max_upload_mb` | implemented |
| CFG-wikiagent.SECRET_ENTROPY_THRESHOLD | SVC-wikiagent | env | float64 | `4.5` | нет | нет | значение по умолчанию для `secret_entropy_threshold` | implemented |
| CFG-wikiagent.wikisvc.base_url | SVC-wikiagent | file | string | `http://127.0.0.1:8787` | нет | нет | адрес SVC-wikisvc (клиент добавляет `/api/v1`) | implemented |
| CFG-wikiagent.wikisvc.token_env | SVC-wikiagent | file | string | `WIKIAGENT_TOKEN` | нет | нет | имя env с токеном к wikisvc | implemented |
| CFG-wikiagent.models.planner | SVC-wikiagent | file | ModelConfig | нет | да | нет | модель извлечения, классификации, правки, книги, лекаря, сверки | implemented |
| CFG-wikiagent.models.reviewer | SVC-wikiagent | file | ModelConfig | нет | да | нет | второй проход книги, второе мнение лекаря | implemented |
| CFG-wikiagent.models.chat | SVC-wikiagent | file | ModelConfig | нет | да | нет | маршрут реплики и ответ на вопрос в чате | implemented |
| CFG-wikiagent.limits.max_tool_steps | SVC-wikiagent | file | int32 (1–100) | `25` | нет | нет | лимит вызовов инструментов при ответе на вопрос | implemented |
| CFG-wikiagent.limits.chapter_chunk_tokens | SVC-wikiagent | file | int32 (100–16000) | `8000` | нет | нет | размер куска главы: `×2.5` символов, ≤ 60000 (v3 planned: только режим `rules`; в `facts` — CFG-wikiagent.ingest.window_tokens) | implemented |
| CFG-wikiagent.limits.retries | SVC-wikiagent | file | int32 (1–3) | `3` | нет | нет | попытки структурного ответа, циклы валидации и правки | implemented |
| CFG-wikiagent.limits.state_tokens | SVC-wikiagent | file | int32 (100–1500) | `1500` | нет | нет | размер конспекта книги между главами (`×2.5` символов) (v3 planned: в `facts` — `state` окна ≤ 1500 токенов, ТЗ §8.2, символы по NFR-token-estimate) | implemented |
| CFG-wikiagent.heal.enabled | SVC-wikiagent | file | bool | `true` | нет | нет | автозапуск лекаря планировщиком (ручной запуск не блокирует) | implemented |
| CFG-wikiagent.heal.idle_minutes | SVC-wikiagent | file | int32 (≥ 0) | `15` | нет | нет | минуты простоя перед автозапуском | implemented |
| CFG-wikiagent.heal.windows | SVC-wikiagent | file | string[] `HH:MM-HH:MM` | `["01:00-06:00"]` | нет | нет | окна автозапуска, локальное время сервера, через полночь допустимо | implemented |
| CFG-wikiagent.heal.max_findings_per_run | SVC-wikiagent | file | int32 (1–100) | `20` | нет | нет | лимит новых находок за запуск | implemented |
| CFG-wikiagent.heal.max_model_calls_per_run | SVC-wikiagent | file | int32 (≥ 1) | `100` | нет | нет | лимит вызовов модели за запуск | implemented |
| CFG-wikiagent.heal.max_model_calls_per_day | SVC-wikiagent | file | int32 (≥ 1) | `2000` | нет | нет | лимит вызовов `heal_*` за сутки UTC | implemented |
| CFG-wikiagent.heal.confidence_threshold | SVC-wikiagent | file | float64 (0–1) | `0.7` | нет | нет | порог уверенности находки и второго мнения | implemented |
| CFG-wikiagent.heal.full_sweep_days | SVC-wikiagent | file | int32 (≥ 1) | `7` | нет | нет | период полного прохода | implemented |
| CFG-wikiagent.heal.k_candidates | SVC-wikiagent | file | int32 (1–20) | `8` | нет | нет | число кандидатов из поиска на страницу (v3 planned: только правила; для фактов — kNN CFG-wikiagent.ingest.dup_k) | implemented |
| CFG-wikiagent.heal.candidate_stale_days | SVC-wikiagent | file | int32 (≥ 1) | `30` | нет | нет | возраст кандидата для `W_CANDIDATE_STALE` | implemented |
| CFG-wikiagent.docs_audit.enabled | SVC-wikiagent | file | bool | `false` | нет | нет | доступность сверки документации | implemented |
| CFG-wikiagent.docs_audit.max_findings_per_run | SVC-wikiagent | file | int32 (1–100) | `20` | нет | нет | лимит новых находок за запуск | implemented |
| CFG-wikiagent.docs_audit.max_model_calls_per_run | SVC-wikiagent | file | int32 (≥ 1) | `100` | нет | нет | лимит вызовов модели за запуск | implemented |
| CFG-wikiagent.docs_audit.max_model_calls_per_day | SVC-wikiagent | file | int32 (≥ 1) | `1000` | нет | нет | лимит вызовов `docs_audit` за сутки UTC | implemented |
| CFG-wikiagent.docs_audit.confidence_threshold | SVC-wikiagent | file | float64 (0–1) | `0.7` | нет | нет | порог уверенности находки | implemented |
| CFG-wikiagent.docs_audit.max_files | SVC-wikiagent | file | int32 (1–200) | `200` | нет | нет | лимит файлов в запросе | implemented |
| CFG-wikiagent.docs_audit.max_total_bytes | SVC-wikiagent | file | int64 (1–26214400) | `26214400` (25 MiB) | нет | нет | лимит суммарного размера файлов (вместе с `max_upload_mb`) | implemented |
| CFG-wikiagent.max_upload_mb | SVC-wikiagent | file | int32 (1–1024) | из `MAX_UPLOAD_MB` | нет | нет | верхняя граница размера запроса сверки | implemented |
| CFG-wikiagent.secret_entropy_threshold | SVC-wikiagent | file | float64 (> 0) | из `SECRET_ENTROPY_THRESHOLD` | нет | нет | порог энтропии детектора секретов (SEC-secret-detector) в сверке | implemented |
| CFG-wikiagent.state_dir | SVC-wikiagent | file | string | из `WIKIAGENT_STATE_DIR` | нет | нет | каталог `agent.db` (RES-agent-db), права 0700, файл 0600 | implemented |
| CFG-wikiagent.bind_host | SVC-wikiagent | file | string | `127.0.0.1` | нет | нет | адрес HTTP API агента | implemented |
| CFG-wikiagent.bind_port | SVC-wikiagent | file | int32 (1–65535) | `8788` | нет | нет | порт HTTP API агента | implemented |
| CFG-wikiagent.ingest.window_tokens | SVC-wikiagent | file | int32 (1000–2000) | `1500` (решение Q-kb-ingest-defaults) | нет | нет | размер окна ingest фактов, раздел главы (ТЗ §8.2) | planned |
| CFG-wikiagent.ingest.overlap_paragraphs | SVC-wikiagent | file | int32 (≥ 0) | `1` | нет | нет | перекрытие соседних окон в абзацах (ТЗ §8.2) | planned |
| CFG-wikiagent.ingest.max_candidates_per_window | SVC-wikiagent | file | int32 (1–40) | `40` | нет | нет | потолок кандидатов DTO-wikiagent.ChapterResult.v2 на окно (ТЗ §11.8) | planned |
| CFG-wikiagent.ingest.fewshot_facts | SVC-wikiagent | file | int32 (5–8) | `8` (решение Q-kb-ingest-defaults) | нет | нет | эталонных фактов вики в окне (ТЗ §8.2) | planned |
| CFG-wikiagent.ingest.hub_list_max | SVC-wikiagent | file | int32 (1–300) | `300` | нет | нет | строк списка хабов и tech домена в окне (ТЗ §8.2) | planned |
| CFG-wikiagent.ingest.dup_cosine | SVC-wikiagent | file | float64 (0–1) | `0.80` | нет | нет | порог kNN-кандидатов в дубликаты (recall, не решение; калибруется на парах ТЗ §10, при смене модели эмбеддингов — заново) | planned |
| CFG-wikiagent.ingest.dup_k | SVC-wikiagent | file | int32 (1–10) | `10` | нет | нет | кандидатов kNN на факт (ТЗ §8.4) | planned |
| CFG-wikiagent.ingest.proposal_max_facts | SVC-wikiagent | file | int32 (1–60) | `60` | нет | нет | фактов в одном предложении (ТЗ §8.6) | planned |
| CFG-wikiagent.ingest.max_windows_per_job | SVC-wikiagent | file | int32 (≥ 1) | `500` (решение Q-kb-ingest-defaults) | нет | нет | лимит окон на задачу `facts`; исчерпан → `paused` | planned |
| CFG-wikiagent.ingest.max_model_calls_per_job | SVC-wikiagent | file | int32 (≥ 1) | `20000` (решение Q-kb-ingest-defaults) | нет | нет | лимит вызовов LLM на задачу `facts` (по `model_calls`); исчерпан → `paused` | planned |
| CFG-wikiagent.models.judge | SVC-wikiagent | file | JudgeConfig? | нет | для `facts` и heal фактов | нет | NLI claim ↔ claim в процессе через DEP-py-onnxruntime + DEP-py-tokenizers (решение Q-kb-judge-runtime): `model` — каталог ONNX MDL-nli-judge, `light_model` — MDL-nli-judge-light для массового фона heal, `ab_model?` — MDL-nli-modernbert; не задан → `mode=facts` отклоняется ERR-request_invalid, heal пропускает пары фактов | planned |
| CFG-wikiagent.models.judge_llm | SVC-wikiagent | file | ModelConfig? | `models.reviewer` | нет | нет | LLM-ступень каскада для PRM-wikiagent.fact_judge; не задан — берётся `models.reviewer` (MDL-gemma-12b на RES-llama-server, отдельной модели и процесса нет); модель недоступна → неуверенные пары без вердикта (`queue`) | planned |
| CFG-wikiagent.models.grounding | SVC-wikiagent | file | GroundingConfig? | нет | для `facts` | нет | claim ↔ источник: `model` — ONNX MDL-grounding-judge в процессе; `escalation?` — ModelConfig для PRM-wikiagent.fact_ground, по умолчанию `models.reviewer` (MDL-gemma-12b на RES-llama-server, отдельной модели и процесса нет); MDL-grounding-escalation — опция на будущее; не задан → `mode=facts` отклоняется ERR-request_invalid | planned |
| CFG-wikiagent.models.reference | SVC-wikiagent | file | map<string, ReferenceConfig>? | нет | для novelty | нет | ключ — семейство модели (`claude-sonnet`, `gemma-31b`; решение Q-kb-novelty-reference-model). Локальная — ModelConfig; внешняя — `provider` + официальный SDK за интерфейсом провайдера (rule-stack-llm-providers), только `https`; `token_env` — секрет (SEC-secrets): задан, но пуст → отказ старта с именем переменной (rule-secrets-required-at-start); наружу — только факты `sensitivity: public` | planned |
| CFG-wikiagent.judge.entail_threshold | SVC-wikiagent | file | float64 (0–1) | `0.7` (решение Q-kb-judge-thresholds) | нет | нет | entailment, с которой сторона «влечёт» другую; ниже — неуверенная пара; калибруется на размеченных парах | planned |
| CFG-wikiagent.judge.contradiction_threshold | SVC-wikiagent | file | float64 (0–1) | `0.7` (решение Q-kb-judge-thresholds) | нет | нет | вероятность contradiction для кандидата `contradicts` | planned |
| CFG-wikiagent.judge.grounding_threshold | SVC-wikiagent | file | float64 (0–1) | `0.7` (решение Q-kb-grounding-escalation) | нет | нет | оценка MDL-grounding-judge, с которой `claim` считается следующим из источника | planned |
| CFG-wikiagent.judge.grounding_escalate_below | SVC-wikiagent | file | float64 (0–1) | `0.4` (решение Q-kb-grounding-escalation) | нет | нет | ниже — сразу `confidence: inferred` и `queue`; от неё до `grounding_threshold` — эскалация PRM-wikiagent.fact_ground | planned |
| CFG-wikiagent.judge.llm_confirm | SVC-wikiagent | file | bool | `true` (решение Q-kb-judge-llm-confirm) | нет | нет | каскад: LLM только на `contradicts` и неуверенных парах; уверенный `duplicate` (≥ порога в обе стороны) — без LLM | planned |
| CFG-wikiagent.novelty.enabled | SVC-wikiagent | file | bool | `false` (решение Q-kb-novelty-defaults) | нет | нет | автозапуск novelty планировщиком (ручной запуск не блокирует) | planned |
| CFG-wikiagent.novelty.samples | SVC-wikiagent | file | int32 (≥ 1) | `5` | нет | нет | ответов на формулировку (ТЗ §8.5) | planned |
| CFG-wikiagent.novelty.temperature | SVC-wikiagent | file | float64 (0–2) | `0.5` | нет | нет | температура референсной модели при сэмплах (ТЗ §8.5) | planned |
| CFG-wikiagent.novelty.paraphrases | SVC-wikiagent | file | int32 (2–3) | `2` (решение Q-kb-novelty-defaults) | нет | нет | формулировок cloze-вопроса, включая исходную (ТЗ §8.5) | planned |
| CFG-wikiagent.novelty.common_threshold | SVC-wikiagent | file | float64 (0–1) | `0.8` | нет | нет | доля попаданий для `common` | planned |
| CFG-wikiagent.novelty.unique_threshold | SVC-wikiagent | file | float64 (0–1) | `0.2` | нет | нет | доля ниже — `unique`; между порогами — `differs` | planned |
| CFG-wikiagent.novelty.max_calls_per_day | SVC-wikiagent | file | int32 (≥ 1) | `2000` (решение Q-kb-novelty-defaults) | нет | нет | лимит вызовов `novelty_*` за сутки UTC | planned |

`ModelConfig` (поля каждой из трёх ролей; набор ролей ровно `planner`, `reviewer`, `chat`, иначе
ошибка старта): `base_url` (string, обязательно; к нему добавляется `/chat/completions`), `model`
(string, обязательно), `context` (int32 ≥ 4096, `32768`), `temperature` (float64 0–2, `0.2`),
`structured` (`enum(json_schema|json_object)`, `json_schema`), `token_env` (string?, нет — имя env с
Bearer-токеном сервера модели; значение — секрет, SEC-secrets; в `deploy/linux/wikiagent.yaml` не задан),
`timeout_seconds` (float64 > 0, `120`).
- changed: 2026-10-20 v3 (planned): `planner`, `reviewer`, `chat` по-прежнему обязательны; `judge`, `judge_llm`, `grounding`, `reference` — необязательные
  ключи `models` (старые файлы остаются валидными); новые разделы `ingest`, `novelty`, `judge` — лишние ключи в них
  ошибка старта, как у `docs_audit` (решение Q-kb-ingest-defaults). Для `mode=facts` и heal фактов в образе нужны файлы ONNX
  MDL-nli-judge и MDL-grounding-judge (размещение — RES-host, агент E).

Отличия боевого файла `deploy/linux/wikiagent.yaml` от значений по умолчанию: все роли —
MDL-wiki-gemma-31b, `context: 16384`, `temperature: 0`, `timeout_seconds: 600`;
`limits.chapter_chunk_tokens: 4000`; `heal.enabled: false`. Токен лежит в `deploy/linux/agent.env`
(в git — пустая заглушка), пути — в `deploy/linux/service.env`.
