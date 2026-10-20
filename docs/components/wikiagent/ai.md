# wikiagent: LLM и промпты

> Промпт — это контракт: у него есть вход, выход, модель и способ проверки.
> Меняешь промпт — меняешь карточку и `PROMPT_VERSION` в `src/wikiagent/models.py`.

## Общий контракт вызова модели

Все промпты лежат в `src/wikiagent/prompts/` (MOD-wikiagent.prompts) и вызываются через
`ModelClient.structured(role, task, schema, data, validate)` в `src/wikiagent/models.py`
(кроме ответа на вопрос в чате, см. PRM-wikiagent.system).

- **Сборка сообщений.** system = текст PRM-wikiagent.system + файл `prompts/<task>.md` + JSON-схема
  pydantic-модели ответа (с defaults) + `Task: <task>`. user = входные данные `data` как JSON внутри
  `<UNTRUSTED_DATA> … </UNTRUSTED_DATA>`. Шаблонных переменных в `.md` нет: «inputs» ниже — ключи `data`.
- **Модель.** Роль (`planner` / `reviewer` / `chat`) выбирает настройки CFG-wikiagent.models.planner,
  CFG-wikiagent.models.reviewer, CFG-wikiagent.models.chat. Запрос — POST `<base_url>/chat/completions`
  к EXT-llm-server (OpenAI-совместимый), `temperature` из роли, `max_tokens = min(4096, context/4)`.
  В `deploy/linux/wikiagent.yaml` все три роли — MDL-wiki-gemma-31b, `temperature: 0`, `context: 16384`,
  `structured: json_schema`, `timeout_seconds: 600`.
- **Структурный вывод.** `structured: json_schema` → `response_format.json_schema` со строгой схемой
  (`strict_schema` убирает границы длины и чисел, иначе llama.cpp не строит грамматику; границы
  проверяет pydantic после ответа). `json_object` → схема только в тексте system.
- **validation.** Ответ разбирается `schema.model_validate_json`, затем вызывается `validate`
  задачи. До CFG-wikiagent.limits.retries попыток (по умолчанию 3); после ошибки проверки в диалог
  добавляется сообщение «Ошибка проверки ответа: … Верни исправленный JSON» (до 3000 символов ошибки).
  Ответ с `tool_calls` в структурном режиме считается ошибкой и учитывается в `forbidden_attempts`.
- **failure.** Нет ответа HTTP / неверный ответ сервера → ERR-model_unavailable (502), повтор тех же
  сообщений. Все попытки без валидного ответа → ERR-model_output (422). Вход больше контекста
  (`len(json)/2.5 > context − max_output`) → ERR-model_context (400) без запроса к модели.
- **Учёт.** Каждый запрос пишет строку в TBL-wikiagent.agent.model_calls (день, роль, задача) — по ней
  считаются дневные бюджеты JOB-wikiagent.heal и JOB-wikiagent.docs-audit.
- **Очередь.** Все запросы к модели идут по одному через `PriorityGate` (`src/wikiagent/jobs/priority.py`);
  задачи `heal_*` и `docs_audit` фоновые и ждут, пока есть ожидающие запросы чата и книги.
- **Недоверенные данные.** Вход модели всегда обёрнут в `<UNTRUSTED_DATA>` (SEC-untrusted-external),
  файл проекта в сверке — ключом `untrusted_external`. Ответ модели отдельной меткой не помечается:
  он недоверенный по построению и проходит pydantic-схему, `validate` задачи (цитаты сверяются
  с исходным текстом) и проверки wikisvc при записи в предложение. Все изменения — только
  предложения и находки, решает человек (INV-human-decides). См. Q в отчёте документирования.
- **Инструменты.** В структурных задачах инструментов нет. Только ответ на вопрос в чате получает
  инструменты чтения (`definitions("question")` = `READ_TOOLS` из `src/wikisvc/tool_contracts.py`:
  `search`, `get_outline`, `read_source_pages`, `get_page`, `get_rule`, `get_context`, `get_policies`,
  `list_rules`, `rules_related`, `graph_impact`, `validate_proposal`); вызов вне allowlist →
  ERR-agent_tool_forbidden. HTTP к wikisvc дополнительно ограничен allowlist путей в `WikiClient.request`.
- **data sent.** Тексты страниц вики (до уровня допуска рабочего токена агента, SEC-clearance), главы книг,
  файлы документации проектов, реплики и вложения чата. Возможны персональные данные (имена
  владельцев правил, `person`, текст реплик) — SEC-pii. В боевом конфиге сервер модели локальный
  (`127.0.0.1`), но `base_url` настраиваемый: при внешнем адресе всё это уходит наружу.
- **eval (общий).** `wikiagent eval` (`src/wikiagent/planner/eval.py`) гоняет 12 сценариев
  `tests/scenarios/*.yaml` через `route` → `extract_claims` → `classify` и меряет совпадение действий
  и вопросов, ложные конфликты, лишние вопросы, запретные вызовы; `production_ready` требует
  ≥ 30 сценариев и точность ≥ 0.9. Последний записанный результат (`ref/model-evaluation.md`,
  `ref/evals/gemma-12b-v2.3.json`): MDL-gemma-12b, промпт v2.3 — 10/12 (83,33 %), 0 запретных вызовов,
  0,083 лишних вопроса, `production_ready=false`. `scripts/check_local_model.py` — живой прогон чата,
  самолечения и книги во временной вики (`ref/evals/gemma-12b-live-v2.3.json`: все три прошли).
  Для текущих MDL-wiki-gemma-31b и промпта v2.6 результатов нет. В unit-тестах модель — сценарная
  заглушка с ошибочными ответами (`tests/test_agent_failures.py`), rule-test-llm-fake.

- **v3 (planned).** NLI-судьи (MDL-nli-judge, MDL-nli-judge-light, MDL-grounding-judge) — не чат-модели: ONNX в процессе через
  DEP-py-onnxruntime + DEP-py-tokenizers, промптов нет (решение Q-kb-judge-runtime). Промпты v3 идут ролям `judge_llm`
  (CFG-wikiagent.models.judge_llm — по умолчанию модель `reviewer`, MDL-gemma-12b на RES-llama-server), `grounding.escalation`
  (CFG-wikiagent.models.grounding, по умолчанию `models.reviewer`) и `reference` (CFG-wikiagent.models.reference, только
  PRM-wikiagent.novelty_answer). Референсная модель получает только cloze-вопрос: без контекста вики, инструментов и
  текстов страниц; её ответ — недоверенные данные для судьи (INV-untrusted-external). Внешняя референсная модель —
  официальный SDK за интерфейсом провайдера (rule-stack-llm-providers; сейчас не подключается, решение
  Q-kb-novelty-reference-model), наружу — только факты `sensitivity: public` (фильтр в коде); RISK-stack-llm-no-sdk.
  Few-shot-эталон для PRM-wikiagent.fact_extract — разовый прогон MDL-propositionizer-flan-t5 на одной главе, в runtime
  не нужен. Судья и пороги проверяются на размеченных парах eval-набора FMT-wikisvc-core.kb-eval (ТЗ §10,
  NFR-ingest-quality); в unit-тестах судьи и модели — фейки с ошибочными ответами (rule-test-llm-fake).

Политики: rule-stack-llm-providers, rule-test-llm-fake.

## Промпты

### PRM-wikiagent.system — Общая системная инструкция
status: implemented | owner: SVC-wikiagent

- model: любая роль; добавляется первым блоком ко всем задачам ниже и к ответу на вопрос в чате
  (`chat`, задача `question` в `src/wikiagent/chat/loop.py`)
- file: `src/wikiagent/prompts/system.md` (версия `policy-layer-v2.6`, совпадает с `PROMPT_VERSION`)
- inputs: нет; в задаче `question` user = `{message, context (привязанная страница/правило/предложение с diff), profile}`
- output: в структурных задачах — по схеме задачи; в `question` — свободный текст ответа человеку
- validation: в `question` нет — текст отдаётся человеку как есть
- tools: в `question` — `READ_TOOLS`, не больше CFG-wikiagent.limits.max_tool_steps вызовов, иначе ERR-agent_step_limit
- failure: ERR-model_unavailable; в `question` повторов нет
- data sent: см. общий контракт

### PRM-wikiagent.route — Намерение реплики в чате
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.chat
- file: `src/wikiagent/prompts/route.md`
- inputs: `message` (реплика + текст вложений), `plan` (план сессии), `bind` (привязка) — `Chat.message`
- output: JSON по DTO-wikiagent.Intent (`intake|question|edit|revise|cancel|revert|other`, `clarification`)
- validation: общая; `clarification` проходит фильтр `clarify()` (≤ 300 символов, преобладает кириллица)
- eval: все 12 сценариев `tests/scenarios/*.yaml`
- failure: общий; ERR-model_output возвращается в поток SSE как ошибка
- data sent: реплика и вложения человека — SEC-pii, SEC-untrusted-external

### PRM-wikiagent.extract_claims — Утверждения о правилах из реплики
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner (в eval — роль из `--role`)
- file: `src/wikiagent/prompts/extract_claims.md`
- inputs: `message`, `previous_plan`, `context` (привязка), `scopes` (словарь `GET /scopes`), `profile_scopes` — `src/wikiagent/planner/pipeline.py`
- output: JSON по DTO-wikiagent.Claims
- validation: общая; `remove_ids` допустимы только из кандидатов прошлого плана, иначе ERR-agent_repair
- eval: `tests/scenarios/*.yaml` (действия и вопросы плана)
- failure: общий
- data sent: реплика, план сессии, привязанная страница

### PRM-wikiagent.classify — Связь утверждения с существующими страницами
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/classify.md`
- inputs: чат — `claim`, `pages` (похожие страницы), `message`, `previous_plan` (`planner/pipeline.py`);
  книга — `claim {text, id}`, `pages` (из `rules/related`) (`jobs/ingest_book.py`)
- output: JSON по DTO-wikiagent.Classification
- validation: общая + `verify` (`src/wikiagent/planner/classify.py`): target из `pages`, цитата дословно из страницы
- eval: `tests/scenarios/*.yaml`
- failure: общий; без похожих страниц модель не вызывается (`new`)
- data sent: тексты страниц вики

### PRM-wikiagent.repair_validation — Исправление ошибок валидации предложения
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/repair_validation.md`
- inputs: `errors` (`GET /proposals/{pid}/validate`), `pages` (страницы предложения) — `Builder.validate` в `src/wikiagent/planner/builder.py`
- output: JSON по DTO-wikiagent.Repairs
- validation: общая; новые страницы запрещены (ERR-agent_repair); цикл валидации до CFG-wikiagent.limits.retries, затем ERR-agent_validation
- eval: только сценарная заглушка `tests/test_agent_failures.py`
- failure: общий
- data sent: страницы предложения

### PRM-wikiagent.locate_revision — Какие разделы страниц править
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/locate_revision.md`
- inputs: `message`, `pages` (оглавление: id, type, title, summary, headings) — `src/wikiagent/planner/revise.py`
- output: JSON по DTO-wikiagent.Located
- validation: общая; страница и заголовки вне оглавления → отказ (`refuse("scope")`)
- eval: только заглушка `tests/test_agent_revise.py`
- failure: общий; пустой `targets` → уточняющий вопрос человеку
- data sent: реплика, заголовки и summary страниц

### PRM-wikiagent.revise_page — Правка выбранных разделов
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/revise_page.md`
- inputs: `message`, `sections` (page, heading, text), при повторе `previous` и `error` — `src/wikiagent/planner/revise.py`
- output: JSON по DTO-wikiagent.Revisions
- validation: общая + `Reviser.prepare` и проверка wikisvc при записи; повтор до CFG-wikiagent.limits.retries с ошибкой сервиса
- eval: только заглушка `tests/test_agent_revise.py`
- failure: общий; пустой `pages` → уточняющий вопрос
- data sent: тексты разделов страниц, реплика

### PRM-wikiagent.book_chapter — Кандидаты правил из главы книги
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/book_chapter.md`
- inputs: `chapter`, `text` (кусок ≤ `chapter_chunk_tokens × 2.5` символов, ≤ 60000), `pages`, `state`
  (конспект ≤ CFG-wikiagent.limits.state_tokens), `scopes_hint`, `scopes`, `related`, `unit` — JOB-wikiagent.ingest-book
- output: JSON по DTO-wikiagent.ChapterResult
- validation: общая + `valid`: область из словаря, связи только на `related`, локатор в пределах книги,
  цитата ≥ 2 слов и дословно на указанных страницах (ERR-quote_not_found)
- eval: заглушка `tests/test_agent_book.py`; живой прогон `scripts/check_local_model.py`
- failure: ERR-model_unavailable валит задачу (глава повторится при resume); иная ошибка — глава пропускается с кодом в отчёте
- data sent: текст книги — SEC-untrusted-external
- changed: 2026-10-20 v3 (planned): только режим `rules` (DTO-wikiagent.BookJob#mode); в режиме `facts` заменён
  PRM-wikiagent.fact_extract

### PRM-wikiagent.book_review — Второй проход по кандидатам книги
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.reviewer
- file: `src/wikiagent/prompts/book_review.md`
- inputs: `candidates` (пачка до 40), `state`, `outline` — JOB-wikiagent.ingest-book
- output: JSON по DTO-wikiagent.BookReview
- validation: общая; слияния и ключевые идеи вне кандидатов игнорируются, связь вне книги → ERR-link_unresolved
- eval: заглушка `tests/test_agent_book.py`
- failure: общий; ошибка валит задачу
- data sent: кандидаты, конспект и оглавление книги

### PRM-wikiagent.heal_pair — Вердикт по паре правил
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/heal_pair.md`
- inputs: `pages` (две страницы `GET /pages/{id}`) — JOB-wikiagent.heal
- output: JSON по DTO-wikiagent.Verdict
- validation: общая + `validate_verdict` (`src/wikiagent/heal/verdicts.py`): цитаты из страниц пары, правки только этих страниц
- eval: заглушка `tests/test_agent_heal.py`; живой прогон `scripts/check_local_model.py`
- failure: ERR-model_output → кэшируется вердикт `none`; ERR-model_unavailable → пара повторится в следующем запуске
- data sent: тексты двух правил
- changed: 2026-10-20 v3 (planned): принимает и пару `fact` (две страницы с `claim`, `summary`, `kind`, `valid_for`,
  источниками) — только после CLS-wikiagent.Judge с вердиктом не `independent` (ТЗ §11.9); NLI-оценки в вход не
  передаются; ответ — DTO-wikiagent.Verdict с изменениями v3

### PRM-wikiagent.heal_review — Второе мнение по конфликту с must
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.reviewer
- file: `src/wikiagent/prompts/heal_review.md` (текст сейчас совпадает с `heal_pair.md`)
- inputs: `pages`, `first_verdict` — только если первый вердикт `conflicts`, есть `must` и уверенность ≥ CFG-wikiagent.heal.confidence_threshold
- output: JSON по DTO-wikiagent.Verdict
- validation: как PRM-wikiagent.heal_pair; не подтвердил конфликт → итоговый вердикт `none`
- eval: заглушка `tests/test_agent_heal.py`
- failure: как PRM-wikiagent.heal_pair
- data sent: тексты двух правил и первый вердикт

### PRM-wikiagent.docs_audit — Сверка политики с файлом документации проекта
status: implemented | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- file: `src/wikiagent/prompts/docs_audit.md`
- inputs: `policy` (страница правила), `level`, `project`, `untrusted_external` (путь и текст `.md` файла) — JOB-wikiagent.docs-audit
- output: JSON по DTO-wikiagent.AuditVerdict
- validation: общая + `validate_verdict` (`src/wikiagent/jobs/docs_audit.py`): нет секретов (SEC-secret-detector,
  CFG-wikiagent.secret_entropy_threshold), точные цитаты проекта (≤ 30 слов с указанной строки) и политики, действие;
  попыток не больше остатка бюджета вызовов
- eval: заглушка `tests/test_docs_audit.py`; живого прогона нет
- failure: ERR-model_output → вердикт `none`, в отчёт только код; ERR-model_context → пара пропускается
- data sent: файлы документации проекта (проверены детектором секретов до постановки задачи) — SEC-untrusted-external

## Промпты v3 (planned)

Тексты промптов не написаны; ниже — контракт. Все — через `ModelClient.structured`, кроме PRM-wikiagent.novelty_answer.

### PRM-wikiagent.hub_skeleton — Скелет хабов из оглавления
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner; один вызов на книгу (ТЗ §8.4, book2graph)
- inputs: `outline` (главы и разделы), `hubs` (хабы и tech домена: id + title, ≤ CFG-wikiagent.ingest.hub_list_max), `domain`
- output: JSON `{hubs: [{id?: string — существующий хаб из `hubs`, title 3..120, chapters: int32[], part_of?: string}]}`;
  хабы — по понятиям, не по главам; ID нового хаба `top-<последний сегмент домена>-<slug>` назначает агент
- validation: общая; `id` и `part_of` — только из `hubs` или новых хабов ответа; главы — из `outline`
- eval: фейк (rule-test-llm-fake); живой прогон — приёмка этапа 3 ТЗ §13
- failure: общий; ошибка валит задачу до первого окна (resume повторит вызов)
- data sent: оглавление книги — SEC-untrusted-external; заголовки хабов вики

### PRM-wikiagent.fact_extract — Кандидаты фактов из окна книги
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- inputs: `text` (окно CLS-wikiagent.Windows), `hubs` (≤ CFG-wikiagent.ingest.hub_list_max строк), `state` (≤ 1500 токенов),
  `examples` (CFG-wikiagent.ingest.fewshot_facts фактов вики: `claim`, `summary`, `kind`, `valid_for`), `scopes`, `domain`,
  `chapter`, `unit` — CLS-wikiagent.FactIngest (ТЗ §8.2)
- output: JSON по DTO-wikiagent.ChapterResult.v2
- validation: общая + поля DTO-wikiagent.FactCandidate (`claim` 20..200, `valid_for` для `number`/`api`/`pitfall`, код только в
  `snippet`, scopes из словаря, `suggested_topic.id` из `hubs`, локатор в пределах книги). Ненайденная цитата — не ошибка
  ответа: кандидат получает `confidence: inferred` (ТЗ §8.3)
- eval: фейк; качество — NFR-ingest-quality на книге (ТЗ §13 этап 3); эталон — MDL-propositionizer-flan-t5
- failure: ERR-model_unavailable валит задачу (окно повторится при resume); иная ошибка — окно пропускается с кодом в отчёте
- data sent: текст книги — SEC-untrusted-external; few-shot факты и заголовки хабов вики

### PRM-wikiagent.fact_judge — LLM-судья пары фактов
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.judge_llm (по умолчанию = `models.reviewer`, MDL-gemma-12b); каскад CLS-wikiagent.Judge — только на `contradicts` и парах ниже
  порогов CFG-wikiagent.judge.* (решение Q-kb-judge-llm-confirm); уверенный `duplicate` сюда не идёт
- inputs: `a`, `b` — `{claim, summary, kind, valid_for}` — CLS-wikiagent.Judge; факты с разным `valid_for` — разные периоды,
  а не противоречие (ТЗ §3.1)
- output: JSON `{verdict, direction?, explanation}` — подмножество DTO-wikiagent.JudgeVerdict (`source: llm`)
- validation: общая; `direction` только при `refines`
- eval: размеченные пары FMT-wikisvc-core.kb-eval (100–200, ТЗ §10); фейк
- failure: ERR-model_output → вердикт NLI остаётся итоговым, LLM-вердикт не кэшируется; ERR-model_unavailable → пара без вердикта (`queue`)
- data sent: тексты двух фактов, локальная модель (loopback)

### PRM-wikiagent.fact_ground — Следует ли факт из источника (эскалация grounding)
status: planned | owner: SVC-wikiagent

- model: `escalation` в CFG-wikiagent.models.grounding, по умолчанию `models.reviewer` (MDL-gemma-12b; MDL-grounding-escalation —
  опционально, на будущее); вызывается CLS-wikiagent.GroundingJudge,
  при оценке MDL-grounding-judge от CFG-wikiagent.judge.grounding_escalate_below до CFG-wikiagent.judge.grounding_threshold (решение Q-kb-grounding-escalation)
- inputs: `claim`, `summary`, `quote`, `paragraph` (абзац excerpt окна с цитатой, внутри `<UNTRUSTED_DATA>`)
- output: JSON `{grounded: bool, explanation ≤ 2000}`
- validation: общая
- eval: размеченные пары «факт — абзац» eval-набора (ТЗ §10); фейк
- failure: ERR-model_output или ERR-model_unavailable → не подтверждено: `confidence: inferred`, класс `queue`; задача не падает
- data sent: абзац книги — SEC-untrusted-external, локальная модель

### PRM-wikiagent.fact_links — Связи новых фактов окна
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner
- inputs: `new` (факты окна после судьи, L0: id, claim), `found` (факты из kNN и `ask`, L0) — CLS-wikiagent.FactIngest (ТЗ §8.4 п. 4)
- output: JSON `{links: [{src, dst, rel: enum(applies_with|precedes), note: string}]}`; агент пишет их с `origin: extracted`
- validation: общая; `src`/`dst` — из входа, хотя бы один — новый факт, не петля, `note` непустая
- eval: фейк; multi-hop вопросы eval-набора (NFR-eval-recall-baseline) после книги
- failure: ERR-model_output → связи окна не пишутся, код в отчёте; ERR-model_unavailable валит задачу
- data sent: `claim` фактов

### PRM-wikiagent.novelty_cloze — Cloze-вопрос и формулировки по факту
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.planner (фон `PriorityGate`)
- inputs: `claim`, `kind`, `valid_for` — CLS-wikiagent.NoveltyScan (ТЗ §8.5)
- output: JSON `{answer: string — скрытая часть claim, formulations: string[] ровно CFG-wikiagent.novelty.paraphrases, первая — cloze}`
- validation: общая; `answer` (нормализованный) не входит ни в одну формулировку
- eval: фейк; надёжность усечённого SliCK — на eval-наборе (ТЗ §8.5, RISK-kb-novelty-truncated)
- failure: ERR-model_output → факт пропускается, код в отчёте
- data sent: `claim` факта (только своей модели, EXT-llm-server)

### PRM-wikiagent.novelty_answer — Ответ референсной модели без контекста
status: planned | owner: SVC-wikiagent

- model: CFG-wikiagent.models.reference (ключ — `model` задачи), `temperature` = CFG-wikiagent.novelty.temperature,
  CFG-wikiagent.novelty.samples ответов на формулировку
- inputs: одна формулировка; без PRM-wikiagent.system, вики, инструментов и `<UNTRUSTED_DATA>` (closed-book)
- output: свободный текст ответа; структурного вывода нет (внешняя модель может его не поддерживать)
- validation: нет; ответ — недоверенные данные, идёт только в судью
- eval: фейк с пустым ответом, отказом и таймаутом (rule-test-llm-fake)
- failure: ERR-model_unavailable → задача `failed` (resume); пустой ответ — промах
- data sent: формулировка вопроса из `claim`; внешней модели (официальный SDK, `https`) — только факты `sensitivity: public` (решение Q-kb-novelty-reference-model)

### PRM-wikiagent.novelty_judge — Совпадает ли ответ с claim
status: planned | owner: SVC-wikiagent

- model: резерв — CFG-wikiagent.models.judge_llm, только если NLI CFG-wikiagent.models.judge не задан; по умолчанию не
  вызывается: ответы сравнивает NLI CLS-wikiagent.Judge (решение Q-kb-novelty-defaults)
- inputs: `claim`, `answer` (внутри `<UNTRUSTED_DATA>`)
- output: JSON `{hit: bool}` — ответ влечёт `claim`
- validation: общая
- eval: размеченные пары eval-набора; фейк
- failure: ERR-model_output → промах, код в отчёте
- data sent: `claim` и ответ референсной модели
