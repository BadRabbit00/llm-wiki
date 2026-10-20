# Домен: сущности, статусы, правила

> Понятия бизнеса, а не таблицы. Таблица хранит сущность, а сущность может жить в нескольких таблицах и сервисах.
> Слой знаний v3 (ТЗ `ref/knowledge-layer-spec.md`) — факты `draft`; строки `changed: … v3 (planned)` — ещё не в коде.

## Сущности

### ENT-page — Страница вики
status: implemented

- meaning: единица знания — Markdown с YAML-frontmatter (`FMT-wikisvc-core.page`) одного из типов `FMT-wikisvc-core.page-type` (app, app-doc, adr, entity, lesson, pattern, playbook, process, role, rule, source, system, term).
- identity: `id` с префиксом типа (`rule-…`, `src-…`); путь выводится из типа и ID.
- lifecycle: поле `status` — `draft` → `verified` (ревьюер) / `outdated`; новые и изменённые предложением страницы снова `draft`.
- stored in: `BKT-wikisvc-core.wiki-repo` (ветка `main`, источник правды); производные — `TBL-wikisvc-core.index.pages`, `.chunks`, `.chunks_fts`, `.edges`.
- owned by: `LIB-wikisvc-core`; меняется только через `ENT-proposal` или решение ревьюера (`API-wikisvc.pages.verify`, `API-wikisvc.pages.mark-outdated`).
- invariants: `INV-human-decides`, `INV-secrets-never-stored`, `INV-404-not-403`.
- relations: N—N ENT-page (связи `FMT-wikisvc-core.relations`, вики-ссылки, цитаты); N—N ENT-library-item (цитаты `[@src-…]`).
- changed: 2026-10-20 v3 (planned): + типы `fact`, `topic`, `tech`, `question` (`ENT-fact`, `ENT-topic`, `ENT-tech`, `ENT-question`); необязательное поле `domain` (`ENT-domain`, `INV-one-domain-per-page`); у связи — объект `{id, w, note, origin}` (`DTO-wikisvc-core.RelationRef`); производные — `TBL-wikisvc-core.index.embeddings`, `.soft_edges`, `.node_stats`, `.page_meta`; `rule`, `adr`, `pattern`, `playbook` получают связь `grounded_in` → fact/topic (ТЗ §3.5, §4).

### ENT-rule — Правило разработки
status: implemented

- meaning: страница типа `rule` (`FMT-wikisvc-core.rule`) с тезисом (`summary` ≤ 160 символов), категорией, уровнем `must`/`should`/`idea`, областями `applies_to` и жизненным циклом `STATE-rule-lifecycle`; `id` — `rule-<название>`.
- stored in: как `ENT-page`; статистика — `TBL-wikisvc-core.state.rule_usage`. Owned by: `LIB-wikisvc-core`; поля жизненного цикла меняет только человек-ревьюер.
- invariants: `INV-agent-rule-inert`, `INV-human-decides`.
- relations: N—N ENT-scope; N—N ENT-profile (через области); 1—N ENT-violation.
- changed: 2026-10-20 v3 (planned): связь `grounded_in` → `ENT-fact`/`ENT-topic` (`API-wikisvc.knowledge.why`); `applies_to` — алиас `scopes`.

### ENT-proposal — Предложение правок
status: implemented

- meaning: набор правок страниц на отдельной git-ветке и worktree; единственный путь изменить контент. `pid` — 32 hex; ветка и worktree называются по `pid`; статусы — `STATE-proposal`.
- stored in: `TBL-wikisvc-core.state.proposals` (статус и автор), правки — ветка в `BKT-wikisvc-core.wiki-repo` и `BKT-wikisvc-core.worktrees`; рядом `TBL-wikisvc-core.state.proposal_editors`, `.proposal_snapshots`, `.proposal_validation`, `.proposal_clearance`, `.proposal_notes`. Owned by: `LIB-wikisvc-core` (`src/wikisvc/services/proposals.py`).
- invariants: `INV-human-decides`, `INV-no-self-review`, `INV-agent-rule-inert`, `INV-404-not-403`.
- relations: 1—N ENT-page (правки); 1—N ENT-finding; `kind`: `manual`, `chat`, `book`, `heal`. Допуск предложения = допуск автора при создании (`proposal_clearance`).
- changed: 2026-10-20 v3 (planned): ingest книги создаёт предложения по (хаб, класс), ≤ 60 фактов (`CFG-wikiagent.ingest.proposal_max_facts`), а не на главу (`FLOW-fact-review-routing`); новые поля — `depends_on: [pid]` (Q-kb-proposal-dependencies), `review_class` на уровне предложения и `reasons` у каждого факта (`DTO-wikisvc-core.ProposalReasons`, Q-kb-ui-review-class-field), `needs_double_confirm` — считает ядро: класс `pair`, правки `must`-правил, понижение `sensitivity`, > 5 страниц не-фактов (Q-kb-ui-double-confirm-facts).

### ENT-finding — Находка
status: implemented

- meaning: обнаруженная проблема в страницах (противоречие пары, дубликат, расхождение проекта с политикой) с цитатами-доказательствами; `id` — uuid hex, дубликаты отсекает `fingerprint` = хеш (`kind`, ID и версии страниц, `scope`); статусы — `STATE-finding`.
- stored in: `TBL-wikisvc-core.state.findings`. Owned by: `LIB-wikisvc-core`; создают писатели (в основном `JOB-wikiagent.heal`, `JOB-wikiagent.docs-audit`), решает человек.
- invariants: `INV-human-decides`, `INV-secrets-never-stored`.
- relations: N—N ENT-page; N—1 ENT-proposal (своё предложение-исправление).

### ENT-violation — Сообщение о нарушении правила
status: implemented

- meaning: отметка агента или человека, что код проекта нарушил правило; питает статистику «часто нарушаемых». Строки без ключа (`rule_id`, `ref`, `author`, `created_at`).
- stored in: `TBL-wikisvc-core.state.violations`; счётчик — `TBL-wikisvc-core.state.rule_usage#violations`.
- owned by: `LIB-wikisvc-core` (`API-wikisvc.rules.violations`, роль writer); invariants: `INV-secrets-never-stored`.

### ENT-token — Токен доступа
status: implemented

- meaning: Bearer-учётка принципала: имя, роль, допуск, вид (`SEC-principal-kind`), `person`, срок. Уникальное `name`; в базе — SHA-256 токена, сам токен показывается один раз. Выпущен → отозван (`revoked_at`) или истёк (`expires_at`).
- stored in: `TBL-wikisvc-core.state.tokens`. Owned by: `SVC-wikisvc-cli` (`CLI-wikisvc-cli.token.create`, `.revoke`) и выпуск сессий (`ENT-session`).
- invariants: `INV-secrets-never-stored`, `INV-anonymous-ceiling`.

### ENT-session — Сессия человека
status: implemented

- meaning: короткоживущий токен `kind=human`, выпущенный после входа через `EXT-authentik`; в браузере — cookie `SEC-session-cookie`. Имя `sso-<префикс sub>-<наносекунды>`; `person` = OIDC `sub`.
- lifecycle: выпущена (`API-wikisvc.sessions.create`) → отозвана выходом (`API-wikisvc.sessions.revoke`) или удалена при старте после `expires_at` (`CFG-wikisvc.SESSION_TTL_HOURS`).
- stored in: `TBL-wikisvc-core.state.tokens`; owned by: `SVC-wikisvc` (выпуск — только токеном `CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME`). Relations: N—1 ENT-person.

### ENT-person — Человек
status: implemented

- meaning: стабильная идентичность человека для авторства, решений и запрета самопроверки; `person` — OIDC `sub` или значение `--person` при выпуске токена.
- stored in: `TBL-wikisvc-core.state.people`; ссылки — `tokens.person`, `proposals.author_identity`, `proposals.decided_by`, `verified_by` страниц. Owned by: `SVC-wikisvc` (обновляется при каждом входе); invariants: `INV-no-self-review`; класс данных — `SEC-pii`.

### ENT-library-item — Источник (книга, документ)
status: implemented

- meaning: неизменяемый загруженный файл: книга в библиотеке или документ, тикет, транскрипт, спецификация; данные извне (`SEC-untrusted-external`). Identity: путь `raw/<категория>/<год>/<sha8>-<имя>` или `library/<год>/<sha8>-<имя>`; дубликаты по SHA-256 не сохраняются.
- stored in: `raw/` — в `BKT-wikisvc-core.wiki-repo`; `library/` — `BKT-wikisvc-core.library` в `STATE_DIR` (вне git); метаданные — `TBL-wikisvc-core.index.raw_files`, заметки — `TBL-wikisvc-core.state.raw_notes`.
- owned by: `LIB-wikisvc-core` (`API-wikisvc.raw.upload`, писатель с допуском `restricted`); invariants: `INV-untrusted-external`.
- relations: 1—1 ENT-extraction; 1—N ENT-page (страница `source` и цитаты).
- changed: 2026-10-20 v3 (planned): у страницы `source` (`FMT-wikisvc-core.source`) `kind` += `paper`, `datasheet`, `spec`, `course`, `video`, `rfc`; поле `covers: [topic-id…]` — оглавление источника, спроецированное на хабы `ENT-topic` (ТЗ §3.5, §8.4).

### ENT-extraction — Извлечение текста
status: implemented

- meaning: постраничный текст и оглавление источника, полученные изолированным парсером; ключ — путь источника, кэш — по SHA-256 содержимого; статусы — `STATE-extraction`.
- stored in: `TBL-wikisvc-core.state.extractions`, `TBL-wikisvc-core.state.outline_overrides`, кэш `BKT-wikisvc-core.extract`.
- owned by: `LIB-wikisvc-core`, исполнитель — `JOB-wikisvc-core.extract-worker`; invariants: `INV-untrusted-external`.
- changed: 2026-10-20 v3 (planned): текст режется по границам абзацев с перекрытием для окон ingest (`CLS-wikisvc-core.Extractions`, ТЗ §8.2, §11.8).

### ENT-job — Задача агента
status: implemented

- meaning: долгая работа `SVC-wikiagent`: `ingest_book`, `heal`, `docs_audit`. `id` — uuid hex; владелец — `person` или имя токена вызвавшего; допуск — его допуск; статусы — `STATE-job`.
- stored in: `TBL-wikiagent.agent.jobs`, контрольные точки — `TBL-wikiagent.agent.job_state`, кэш вердиктов пар — `TBL-wikiagent.agent.pair_checks`, учёт вызовов — `TBL-wikiagent.agent.model_calls`.
- owned by: `SVC-wikiagent`; invariants: `INV-agent-clearance-ceiling`, `INV-human-decides` (задача только создаёт предложения и находки); relations: 1—N ENT-proposal, 1—N ENT-finding.
- changed: 2026-10-20 v3 (planned): `kind` += `novelty_scan` (`JOB-wikiagent.novelty-scan`, `FLOW-novelty-scan`); `ingest_book` идёт окнами по разделам (`FLOW-fact-ingest`), окна — `TBL-wikiagent.agent.ingest_windows`; `TBL-wikiagent.agent.fact_verdicts` — кэш, источник правды вердиктов — `TBL-wikisvc-core.state.pair_verdicts` (Q-kb-judge-verdict-visibility); лимиты 500 окон и 20 000 вызовов на задачу → `paused` (Q-kb-ingest-defaults).

### ENT-chat-session — Сессия чата с агентом
status: implemented

- meaning: диалог человека с агентом, привязанный к странице, правилу, предложению или ни к чему, с профилем и текущим планом правок; `id`, владелец и допуск — вызвавшего.
- stored in: `TBL-wikiagent.agent.chat_sessions`, `TBL-wikiagent.agent.chat_messages`; итог плана — `ENT-proposal` с `kind=chat` и транскрипт в `raw/transcripts`. Owned by: `SVC-wikiagent`; invariants: `INV-agent-clearance-ceiling`, `INV-untrusted-external`.

### ENT-profile — Профиль политик
status: implemented

- meaning: именованный набор областей и бюджет токенов для сборки блока политик под тип проекта (`fastapi-fullstack`, `go-service`…); `id` — файл профиля.
- stored in: `schema/profiles/*.yaml` в `BKT-wikisvc-core.wiki-repo` (`FMT-wikisvc-core.profiles`); owned by: администратор вики; читают `API-wikisvc.policies.*`; relations: N—N ENT-scope.
- changed: 2026-10-20 v3 (planned): + `reference_model` — только умолчание, модель передаёт клиент `get_brief` (Q-kb-novelty-reference-model), и `brief: {include_novelty, max_facts}` для `FLOW-knowledge-brief` (ТЗ §6); бюджет brief — `NFR-brief-budget`.

### ENT-scope — Область применения
status: implemented

- meaning: метка стека или вида приложения (`lang:python`, `app:auth`), к которой относится правило; `*` — все области; строка `<группа>:<значение>`.
- stored in: `schema/scopes.yaml` в `BKT-wikisvc-core.wiki-repo` (`FMT-wikisvc-core.scopes`); добавляет `CLI-wikisvc-cli.scopes.add`.
- changed: 2026-10-20 v3 (planned): группы становятся осями (`TERM-scope-axis`): `domain` (иерархическая: `domain:db/kv` подразумевает `domain:db`), `lang`, `tech` (из страниц `tech`), `layer`, `scale`, `stage` (enum, ТЗ §6); страница получает `domain:<domain>` автоматически; отбор — пересечение с профилем либо `*` с учётом иерархии.

### ENT-audit-entry — Запись аудита
status: implemented

- meaning: журнал действий: кто (имя токена), что, над чем, успех, деталь; отказанные изменяющие запросы авторизованных принципалов тоже пишутся, неаутентифицированные — нет.
- stored in: `TBL-wikisvc-core.state.audit`; читает admin с `restricted` (`API-wikisvc.admin.audit`); owned by: `LIB-wikisvc-core`.

### ENT-fact — Атомарный факт
status: implemented

- meaning: страница типа `fact` (`FMT-wikisvc-core.fact`) — ровно одно проверяемое утверждение, единица доставки и дедупликации (ADR-0017): пара `claim` (L0) / `summary` (L1) — `INV-claim-minimal`; `kind` (definition, mechanism, constraint, tradeoff, number, convention, api, pitfall, comparison, step, snippet); `confidence` (`inferred` по умолчанию, `sourced`, `contested` — вычисляет индекс, `open` — явно «нужна проверка», Q-kb-core-defaults); `novelty` по семействам моделей (`TERM-novelty`) — производное в `TBL-wikisvc-core.state.novelty`, во frontmatter — только ручное переопределение (Q-kb-novelty-write-path); `valid_for`, `valid_from`/`valid_to` (`TERM-bi-temporal`); для `number` — `value`, `unit`, `conditions`, `measured_at`.
- identity: `id` вида `f-<…>`; путь `kb/<domain>/facts/<id>.md` (`INV-one-domain-per-page`).
- lifecycle: `STATE-fact`; маршрут ревью — `STATE-fact-review-class`.
- stored in: как `ENT-page`; производные — `TBL-wikisvc-core.index.facts_fts`, `TBL-wikisvc-core.index.embeddings` (уровень `claim`), `.soft_edges`, `.node_stats`; вердикты пар — `TBL-wikisvc-core.state.pair_verdicts`.
- owned by: `LIB-wikisvc-core`; создаётся предложением (`API-wikisvc-mcp.propose_fact`, `FLOW-fact-ingest`).
- invariants: `INV-claim-minimal`, `INV-invalidate-not-delete`, `INV-cite-by-id`, `INV-one-domain-per-page`, `INV-human-decides`.
- relations: N—N ENT-topic/ENT-tech (`about`); N—N ENT-fact (`applies_with`, `supports`, `contradicts`, `refines`, `precedes`, `replaces`); ENT-question → ENT-fact (`answered_by`); ENT-rule → ENT-fact (`grounded_in`); N—N ENT-library-item (`sources`, цитаты).

### ENT-topic — Хаб темы
status: implemented

- meaning: страница типа `topic` (`FMT-wikisvc-core.topic`): `summary`, раздел `Digest` ≤ 800 символов (`TERM-digest`), упорядоченный список `Facts` — канонический порядок (`INV-canonical-order`), `Open questions`. Хабы — по понятиям, не по главам книги (ТЗ §8.4).
- identity: `id` вида `top-<…>`; путь `kb/<domain>/topics/<id>.md`.
- lifecycle: как `ENT-page`; в `Facts` — только актуальные факты (`INV-invalidate-not-delete`), не больше 60 (`NFR-kb-limits`).
- stored in: как `ENT-page`; вектор `digest` — `TBL-wikisvc-core.index.embeddings`; обратное ребро `has_fact` строит индекс.
- relations: 1—N ENT-fact (`has_fact`); N—N ENT-topic (`part_of`, `builds_on`, `applies_with`); ENT-tech → ENT-topic (`instance_of`).

### ENT-tech — Технология
status: implemented

- meaning: страница типа `tech` (`FMT-wikisvc-core.tech`) — технология, инструмент, компонент, чип: `category` (database, runtime, library, protocol, tool, service, chip, board, model), статус принятия `STATE-tech` (поле `adoption`), `verdict` (суждение команды, не описание из README), `current_version` (`W_STALE_VERSION`), `homepage`. Факты о технологии — отдельные `ENT-fact` с `about: [tech-…]`; даташит — `source` с `kind: datasheet`.
- identity: `id` вида `tech-<…>`; путь `kb/<domain>/tech/<id>.md`; автоматически даёт область `tech:<…>` (`ENT-scope`).
- relations: N—N ENT-topic (`instance_of`); N—N ENT-tech (`alternative_to`, `replaces`).

### ENT-question — Открытый вопрос
status: implemented

- meaning: страница типа `question` (`FMT-wikisvc-core.question`) — явное «не знаем», чтобы агент не выдумывал, а `FLOW-heal` знал, что ресерчить: `summary`, `priority`, `answered_by`; статусы — `STATE-question`.
- identity: `id` вида `q-<…>`; путь `kb/<domain>/questions/<id>.md`; список — `API-wikisvc.knowledge.questions`.
- relations: N—N ENT-topic/ENT-tech (`about`); N—N ENT-fact (`answered_by`).

### ENT-domain — Домен знаний
status: implemented

- meaning: узел дерева доменов `schema/domains.yaml` (`FMT-wikisvc-core.domains`, `TERM-domain`); стартовые: systems, net, db, concurrency, lang/{rust, python, cpp, c, nix}, os, infra, security, ml, hardware, business, math (ТЗ §0, §2). Задаёт физический путь страницы и область `domain:<domain>`.
- identity: путь в дереве (`db`, `lang/rust`).
- stored in: `schema/domains.yaml` в `BKT-wikisvc-core.wiki-repo`; каталоги `kb/<domain>/{topics,facts,tech,questions}/` создаёт `CLI-wikisvc-cli.init`.
- owned by: администратор вики (`CLI-wikisvc-cli.domains.add`); агент через предложения дерево не расширяет (предложения меняют только `wiki/`, `ERR-proposal_path`).
- invariants: `INV-one-domain-per-page`; список — `API-wikisvc.knowledge.domains`.

## Машины состояний

### STATE-proposal — Статусы предложения
status: implemented

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `draft` | `API-wikisvc.proposals.create` | роль writer | создаёт ветку и worktree, `proposal_clearance` = допуск автора |
| `draft`, `changes_requested` | `draft` | правка страницы (`API-wikisvc.proposals.*`) | автор или reviewer/admin; не `submitted` | автор правки → `proposal_editors` |
| `draft`, `changes_requested` | `submitted` | `API-wikisvc.proposals.submit` | есть изменения, валидация без ошибок | снимок страниц |
| `submitted` | `accepted` | `API-wikisvc.proposals.accept` | `INV-human-decides`, `INV-no-self-review`, валидация без новых ошибок | merge `--no-ff` в main, активные правила → `verified`, переиндексация, находки → `resolved`, worktree удалён |
| `draft` (автор `kind=agent`) | `accepted` | `API-wikisvc.proposals.accept` | как выше | как выше |
| `submitted` | `changes_requested` | `API-wikisvc.proposals.request-changes` | `INV-human-decides` | комментарий ревьюера |
| не терминальный | `rejected` | `API-wikisvc.proposals.reject` | `INV-human-decides`; с находками — нужна причина | находки → `dismissed`, worktree удалён |
| не терминальный | `abandoned` | `API-wikisvc.proposals.abandon` | автор или reviewer | worktree удалён |
| `draft`, `submitted`, `changes_requested` | `abandoned` | старт `SVC-wikisvc` | не менялось дольше `CFG-wikisvc.PROPOSAL_TTL_DAYS` | worktree удалён |
| `accepted` | `reverted` | `API-wikisvc.proposals.revert` | человек-reviewer; поздние коммиты не трогают те же страницы | revert-коммит, находки `resolved` → `open` |

- terminal: `accepted` (кроме отката), `rejected`, `abandoned`, `reverted`.
- forbidden: любое решение из терминального статуса (`ERR-proposal_state`); `accept` и `request-changes` не из `submitted` (кроме `accept` черновика агента); правка и повторная отправка из `submitted`.
- recovery: при старте `Proposals.recover()` доводит до `accepted` или `reverted` предложения, чей merge/revert-коммит уже в main.
- статус `conflict` есть в модели и разрешён для правки и TTL, но в коде никогда не выставляется — Q-proposal-conflict-status.
- changed: 2026-10-20 v3 (planned): предложение с `depends_on` не принимается раньше базового — `ERR-proposal_dependency`; validate видит страницы зависимостей; дописывание `## Facts` разными предложениями сливается по строкам (Q-kb-proposal-dependencies); `accept` принимает `{exclude, resolutions}` (Q-kb-ui-review-decisions); блок `auto` принимает человек одним действием, обычным `accept` (Q-kb-auto-accept-human-decides).

### STATE-rule-lifecycle — Жизненный цикл правила
status: implemented

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `candidate` | новое правило в предложении (`Proposals._put`) | всегда: `lifecycle`, `level`, `priority`, `owner` от автора отбрасываются | `level=should`, `priority=3`, `status=draft` |
| `candidate`, `deprecated` | `active` | `API-wikisvc.rules.promote` или `promote` при `API-wikisvc.proposals.accept` | `INV-human-decides`; `level` — `must` или `should` | `status=verified`, `verified_by` = человек |
| `candidate`, `active` | `deprecated` | `API-wikisvc.rules.deprecate` или `deprecate` при принятии | `INV-human-decides`; причина 1–200 символов | `deprecated_reason` |

- проверки (`validate_rule` в `src/wikisvc/domain/validate.py`): `active` без `verified_by` → `ERR-rule_active_not_verified`; `candidate` только `status=draft` и `level` `idea`/`should`; `must` требует `owner` (`ERR-must_needs_owner`) и `sources`; `deprecated` требует причину.
- В блок политик попадают только `active` + `verified_by` с уровнем `must`/`should` (`INV-agent-rule-inert`).

### STATE-finding — Статусы находки
status: implemented

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `open` | `API-wikisvc.findings.create` | writer; цитаты найдены в страницах; нет секретов | повтор с тем же `fingerprint` возвращает существующую |
| `open` | `resolved` | принятие связанного предложения | — | `reason` = комментарий ревьюера |
| `open` | `dismissed` | `API-wikisvc.findings.dismiss` или отклонение связанного предложения | `INV-human-decides`; причина до 2000 символов | — |
| `dismissed` | `open` | `API-wikisvc.findings.reopen` | `INV-human-decides` | `reason` очищается |
| `resolved` | `open` | `API-wikisvc.proposals.revert` | — | — |

### STATE-extraction — Статусы извлечения
status: implemented

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `pending` | `API-wikisvc.raw.extract` | writer; формат pdf, epub, docx, md, txt | задача в пул из 2 потоков |
| `pending` | `running` | `JOB-wikisvc-core.extract-worker` | — | пачки по 15 страниц в отдельном процессе |
| `running` | `done` | конец извлечения | есть текст | `pages.jsonl`, `outline.json` в кэше |
| `running` | `failed` | любая ошибка | — | `error` = код (`ERR-text_limit`, `ERR-extract_timeout`…) |
| `failed` | `pending` | `API-wikisvc.raw.extract` с `retry=true` | — | ошибка очищается |

- `done`/`failed` с тем же SHA-256 без `retry` не перезапускаются; `pending`/`running` перезапускаются при старте `SVC-wikisvc`.

### STATE-job — Статусы задачи агента
status: implemented

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `pending` | `API-wikiagent.jobs.*`, `JOB-wikiagent.scheduler` | `INV-agent-clearance-ceiling`; один `heal` за раз | — |
| `pending` | `running` | пул `JobRunner` (2 потока) | — | — |
| `running` | `waiting_chat` → `running` | `JOB-wikiagent.heal` | идёт чат человека | ждёт, чат приоритетнее |
| `running` | `paused` | остановка процесса, контрольная точка, исчерпан бюджет вызовов | — | прогресс в `job_state` |
| `running` | `needs_outline` | `JOB-wikiagent.ingest-book` | у книги только запасное оглавление | ждёт `PUT` оглавления |
| `running` | `awaiting_review` | ingest-book, docs-audit | предложение/находки созданы | — |
| `running` | `done` | heal; ingest-book, если предложение уже принято | — | — |
| `running` | `failed` | исключение | — | `error` = код ошибки |
| любой | `cancelled` | `API-wikiagent.jobs.cancel` | владелец | задача останавливается на контрольной точке |
| `failed`, `cancelled`, `paused`, `needs_outline` | `pending` | `API-wikiagent.jobs.resume` | не активна | продолжает с контрольной точки |

- `pending`, `running`, `paused`, `waiting_chat` перезапускаются при старте `SVC-wikiagent` (`RESUMABLE` в `src/wikiagent/jobs/runner.py`); их же сравнивает `JOB-updater.apply` до и после обновления.
- changed: 2026-10-20 v3 (planned): `novelty_scan` проходит те же статусы, что `heal` (лимит вызовов → `paused`, чат → `waiting_chat`); в `ingest_book` отказ эмбеддингов или модели → `failed`, продолжение — `API-wikiagent.jobs.resume` с последней стадии окна.

### STATE-fact — Статусы факта
status: planned

| из | в | что вызывает | условие | побочные эффекты |
|---|---|---|---|---|
| — | `draft` | принятие предложения с новым фактом (`FLOW-proposal-review`, `FLOW-fact-review-routing`) | валидация без ошибок | индекс, векторы `claim` |
| `draft` | `verified` | `API-wikisvc.pages.verify` | `INV-human-decides` | `f_status` 1.0 → 1.2 в обходе |
| `draft`, `verified` | `outdated` | индекс: у факта непустой `replaced_by` или `valid_to` | автоматически (`INV-invalidate-not-delete`); эффективный статус вычисляет индекс, файл не меняется (Q-kb-derived-status) | `f_status` 0.3; из brief исключён; хаб с ним — `W_HUB_CITES_OUTDATED` |
| `draft`, `verified` | `outdated` | `API-wikisvc.pages.mark-outdated` | `INV-human-decides` | как выше |

- `confidence` — отдельно от статуса: по умолчанию `inferred`; `sourced` требует проверенной цитаты и grounding-проверки (`FLOW-fact-ingest`); `contested` индекс вычисляет, пока есть ребро `contradicts`; `open` ставится явно и подхватывается `FLOW-heal` (Q-kb-core-defaults). Forbidden: удаление факта вместо инвалидации (`INV-invalidate-not-delete`).

### STATE-question — Статусы вопроса
status: planned

- поля в файле нет: индекс вычисляет `answered` при непустом `answered_by`, иначе `open` (ТЗ §3.4, Q-kb-tech-question-status, Q-kb-derived-status); `answered` → `open` — правка предложением опустошила `answered_by`. Без движения 90 дней — `W_QUESTION_STALE`.

### STATE-tech — Статус принятия технологии
status: implemented

- поле `adoption` (не `status` страницы, Q-kb-tech-question-status): `evaluating` | `adopted` | `avoid` | `legacy` | `unknown` (ТЗ §3.3); переходы не ограничены; меняется предложением, смена — изменение смысла и идёт в ревью человеку (`INV-human-decides`).

### STATE-fact-review-class — Класс маршрутизации ревью факта
status: planned

| класс | условие (ТЗ §8.6) | что происходит |
|---|---|---|
| `auto` | `confidence: sourced`, цитата проверена, нет кандидатов в дубликаты, `kind` ≠ `convention`, нет признаков классов ниже; допустимый объём правки — `INV-auto-class-scope` | блок `auto` предложения хаба принимает человек одним действием без построчного ревью; факты входят в `main` как `draft` (Q-kb-auto-accept-human-decides, ADR-0024) |
| `queue` | `inferred`, есть `refines`, `W_POSSIBLE_DUPLICATE`, `kind: convention`, `novelty: unique` | обычное ревью списком L0 |
| `pair` | есть `contradicts` | обязательное ревью пары одним действием: оставить оба / `replaces` / снять |

- приоритет: `pair` > `queue` > `auto`. Класс — только сортировка и группировка: его пересчитывает ядро по diff предложения (`INV-auto-class-scope`), вердиктам судьи (`TBL-wikisvc-core.state.pair_verdicts`) и `TBL-wikisvc-core.state.novelty`; класс от агента — подсказка; `review_class` — у предложения, `reasons` — у каждого факта (`DTO-wikisvc-core.ProposalReasons`). Сценарий — `FLOW-fact-review-routing`.

## Бизнес-правила

### INV-human-decides — Решает только человек
status: implemented

- statement: принять, отклонить, вернуть на доработку и откатить предложение, подтвердить или устареть страницу, повысить или снять правило, отклонить или открыть находку, запустить сверку документации и обновление может только принципал `kind=human` с ролью reviewer и выше (обновление — admin). Why: агент не должен сам себе утверждать правила.
- enforced at: `require_human` в `src/wikisvc/services/auth.py` (`CLS-wikisvc-core.require_human`), вызовы в `services/proposals.py`, `services/review.py`, `services/findings.py`; allowlist `CLS-wikiagent.WikiClient` запрещает агенту `accept`, `reject`, `revert`, `promote`, `deprecate`, `verify`; `audit_actor` в `src/wikiagent/api.py`; `admin` в `updater/api.go`.
- on violation: `ERR-human_required`, `ERR-agent_tool_forbidden`.
- changed: 2026-10-20 v3 (planned): statement и граница №1 `AGENTS.md` не меняются (Q-kb-auto-accept-human-decides, вариант 1): класс `auto` (`STATE-fact-review-class`) — только сортировка; блок `auto` предложения хаба принимает человек одним действием без построчного ревью, системного пути в `main` нет. Вердикты судьи и `novelty` (`API-wikisvc.knowledge.verdicts`, `API-wikisvc.knowledge.novelty`) — производные данные state, а не правки контента.

### INV-no-self-review — Автор не принимает своё
status: implemented

- statement: предложение не может принять ни его автор, ни любой его редактор; сравнение — по идентичности (`person`, иначе имя токена), а не по отображаемому имени. Why: правка проходит вторые глаза.
- enforced at: `Proposals.decide` в `src/wikisvc/services/proposals.py` (`TBL-wikisvc-core.state.proposal_editors#identity`); отказ пишется в аудит. On violation: `ERR-self_review`.

### INV-agent-rule-inert — Новое правило инертно
status: implemented

- statement: правило, созданное или изменённое через предложение, не меняет свой `lifecycle`/`level`/`priority`/`owner`/`verified_*` от автора; новое — всегда `candidate`, а в блок политик попадает только `active` с `verified_by`. Why: правило действует только после решения человека.
- enforced at: `Proposals._put` в `src/wikisvc/services/proposals.py`; `apply_patch` в `src/wikisvc/domain/patch.py`; `validate_rule` в `src/wikisvc/domain/validate.py`; отбор в `src/wikisvc/services/policies.py`. On violation: `ERR-field_protected`, `ERR-rule_active_not_verified`, `ERR-rule_fields`.

### INV-core-deterministic — Ядро без модели
status: implemented

- statement: `LIB-wikisvc-core`, `SVC-wikisvc`, `SVC-wikisvc-mcp` и `SVC-wikisvc-cli` не вызывают языковую модель и не зависят от `SVC-wikiagent`; ответ модели проверяется ядром как любой другой ввод. Why: валидация, права и решения воспроизводимы; модель — необязательная надстройка.
- enforced at: в `src/wikisvc/` нет клиента модели и импорта `wikiagent`; `SVC-wikiagent` ходит только по HTTP через `CLS-wikiagent.WikiClient`. On violation: —
- changed: 2026-10-20 v3 (planned): ядро получает векторы и ранжирование reranker из `EXT-embeddings-server` (`CLS-wikisvc-core.Embeddings`) — модели-кодировщики, не LLM, только на loopback. Это принятое исключение к ADR-0003 и границе №4 `AGENTS.md`; формулировку границы правит человек (Q-kb-core-outbound-embeddings). Детерминизм сохраняется при фиксированных модели, pooling, размерности (self-test, `OBS-wikisvc.embeddings-selftest`) и поколении индекса: тот же запрос → тот же ответ (`INV-canonical-order`). Судья, NLI и novelty — только в `SVC-wikiagent`.

### INV-single-node — Один узел
status: implemented

- statement: все экземпляры `SVC-wikisvc`, CLI и обслуживания работают на одном хосте с общими `STATE_DIR` и `WIKI_ROOT`; записи сериализуются файловой блокировкой. Why: хранилище — git-репозиторий и SQLite-файлы.
- enforced at: `write_lock` (`fcntl.flock` на `STATE_DIR/write.lock`) в `src/wikisvc/storage/lock.py`; пулы задач в памяти процесса (`services/extractions.py`, `src/wikiagent/jobs/runner.py`). On violation: `ERR-lock_timeout`.

### INV-untrusted-external — Внешний текст — данные
status: implemented

- statement: содержимое источников, извлечённый текст и файлы сверки помечаются `trust: untrusted_external` и передаются модели как данные; инструкции из них не исполняются. Why: защита от промпт-инъекций через документы.
- enforced at: `src/wikisvc/services/raw.py`, `src/wikisvc/services/extractions.py`, заголовок `X-Content-Trust` в `API-wikisvc.raw.download`; `<UNTRUSTED_DATA>` в `src/wikiagent/chat/loop.py`; `PRM-wikiagent.docs_audit`; allowlist `CLS-wikiagent.WikiClient`. On violation: `ERR-agent_tool_forbidden`.

### INV-anonymous-ceiling — Потолок анонима
status: implemented

- statement: анонимный принципал (`SEC-anonymous`) — всегда `kind=agent`, роль не выше writer, допуск не выше internal. Why: аноним не решает и не видит `restricted`.
- enforced at: типы `anonymous_role`/`anonymous_clearance` в `CLS-wikisvc.Settings` (`src/wikisvc/config.py`); `Auth.anonymous` в `src/wikisvc/services/auth.py`. On violation: сервис не стартует (ошибка валидации настроек).

### INV-agent-clearance-ceiling — Не выше допуска агента
status: implemented

- statement: вызвать `SVC-wikiagent` может только writer и выше с допуском не ниже допуска рабочего токена агента; задачи и чаты видны владельцу в пределах его допуска. Why: иначе пользователь получил бы через агента чужие данные.
- enforced at: `authorize` в `src/wikiagent/api.py`; `JobRunner.get` в `src/wikiagent/jobs/runner.py`. On violation: `ERR-forbidden`, `ERR-not_found`.

### INV-404-not-403 — Скрытое не существует
status: implemented

- statement: объект вне допуска принципала (страница, предложение со страницами выше допуска, источник без `restricted`, чужая задача) отвечает 404, как несуществующий. Why: не раскрывать факт существования (`rule-auth-no-enumeration`).
- enforced at: `can_read` + `not_found()` в `src/wikisvc/services/*.py`, `Raw.require_clearance`, `JobRunner.get`. On violation: `ERR-not_found`. Исключение: `API-wikisvc.people.list` отвечает 403 без допуска internal.
- changed: 2026-10-20 v3 (planned): скрытые узлы не попадают ни в `seeds`, `expanded`, `omitted_ids`, `hubs`, ни в счётчики фактов хаба (`SEC-graph-clearance-mask`).

### INV-auth-before-body — Аутентификация до тела
status: implemented

- statement: запрос к `/api/v1/` и `/mcp` проходит аутентификацию до чтения тела; тело читается с лимитом размера. Why: неаутентифицированный клиент не нагружает сервис большими телами.
- enforced at: `CLS-wikisvc.BodyLimit` в `src/wikisvc/main.py`, `CLS-wikisvc-mcp.MCPHTTPAuth` в `src/wikisvc/mcp_http.py`; в `SVC-wiki-ui` — проверка Bearer до проксирования (`ui/main.go`). On violation: `ERR-unauthorized`, `ERR-body_too_large`.

### INV-policy-block-only — Только свой блок
status: implemented

- statement: экспорт политик в файл проекта меняет только текст между `<!-- wikisvc:begin … -->` и `<!-- wikisvc:end -->`; нет блока — дописывает в конец; блок повреждён или их больше одного — отказ. Why: остальной `AGENTS.md` принадлежит проекту.
- enforced at: `export_block` в `src/wikisvc/services/policies.py` (`FMT-wikisvc-core.policy-block`). On violation: `ERR-policy_block`.
- changed: 2026-10-20 v3 (planned): то же для блока `<!-- wikisvc:knowledge begin -->` (`FMT-wikisvc-core.knowledge-block`); блоки правил и знаний независимы.

### INV-secrets-never-stored — Секреты не хранятся
status: implemented

- statement: токены хранятся только хешем SHA-256; страницы, описания и комментарии предложений, заметки, находки, причины, нарушения и ответы сверки с возможным секретом отклоняются. Why: вика читается людьми и агентами и уходит в модель.
- enforced at: `Auth.create` (`src/wikisvc/services/auth.py`); `secret_kinds` (`SEC-secret-detector`) в `domain/validate.py`, `services/proposals.py`, `services/findings.py`, `services/rules.py`, `services/review.py`, `src/wikiagent/jobs/docs_audit.py`. On violation: `ERR-secret_detected`. Загружаемые источники (`ENT-library-item`) детектором не проверяются.

### INV-invalidate-not-delete — Инвалидация вместо удаления
status: planned

- statement: устаревший факт не удаляется, а получает эффективный статус `outdated` (вычисляет индекс, Q-kb-derived-status) — через `replaces` у нового факта (у старого появляется `replaced_by`) или `valid_to`; хаб перечисляет только актуальные факты; ссылки на заменённое — `W_REPLACED_LINKED`. Why: knowledge-update — худшая категория memory-систем; история нужна для `why` и отката (ADR-0021, ТЗ §3.1, §4).
- enforced at: план — `CLS-wikisvc-core.validate_set`, `CLS-wikisvc-core.Indexer`, `CLS-wikisvc-core.Lint` (`W_HUB_CITES_OUTDATED`, `W_REPLACED_LINKED`); `replaces` меняет смысл → только решением человека. On violation: предупреждения линтера.

### INV-claim-minimal — Минимальный claim
status: implemented

- statement: `claim` факта — одно утверждение, одно предложение 20–200 символов без контекстных обёрток («in Rust, …»); `summary` — тот же claim, деконтекстуализированный ровно настолько, чтобы читаться вне контекста; хранятся парой. Тело факта > 1 500 символов — это тема (`W_FACT_LONG`). Why: claim — единица дедупликации и L0-выдачи (ТЗ §3.1).
- enforced at: план — `CLS-wikisvc-core.validate_page` (длина, наличие), `PRM-wikiagent.fact_extract` (минимальность), человек в ревью. On violation: `ERR-claim_missing`.

### INV-cite-by-id — Ссылка на факт по id
status: planned

- statement: каждая единица выдачи знаний несёт `id`; подробности — только по `id` (`API-wikisvc-mcp.get_fact`); агент цитирует `id` и текст claim, а не пересказывает. Why: тезис в контексте, подробности по запросу — меньше токенов и проверяемость (ТЗ §7, §7.4).
- enforced at: план — `CLS-wikisvc-core.Assemble`, `CLS-wikisvc-mcp.render_compact`, описание `API-wikisvc-mcp.ask`, `FMT-wikisvc-core.workflow` (`knowledge-query.md`). On violation: — (поведение модели кодом не проверяется).

### INV-canonical-order — Канонический порядок выдачи
status: planned

- statement: внутри хаба факты выдаются по позиции в `Facts` хаба, затем по `id`; равные score и факты без позиции — по `id`. При одинаковых запросе, допуске, поколении индекса и модели эмбеддингов выдача одинакова побайтно. Why: тот же top-5 в другом порядке меняет ответ модели в 50.8–84.4 % случаев (ТЗ §7.1).
- enforced at: план — `CLS-wikisvc-core.Assemble`, `CLS-wikisvc-core.Brief`; приёмка — два прогона дают одно и то же (ТЗ §13, этап 2). On violation: —

### INV-rules-pushed-knowledge-pulled — Правила навязываются, знания запрашиваются
status: planned

- statement: правила идут в инструкцию агента всегда (`FLOW-policy-compile`); знания — по запросу (`FLOW-knowledge-brief` в начале задачи, `FLOW-ask` по ходу) и по графу. Блок знаний в файле проекта — только по явному экспорту; правила не смешиваются с фактами в одном блоке. Why: ценны только детали, которые модель не выведет сама (ТЗ §1).
- enforced at: план — `CLS-wikisvc-core.Policies`, `CLS-wikisvc-core.Brief`, `FMT-wikisvc-core.knowledge-block`. On violation: —

### INV-one-domain-per-page — Один домен на страницу
status: planned

- statement: у страницы ровно один `domain` из `schema/domains.yaml` — он задаёт физический путь `kb/<domain>/<каталог типа>/<id>.md`; второй домен — только в `scopes` (`domain:<…>`). Для `fact`, `topic`, `tech`, `question` поле обязательно, для остальных типов — необязательно (старые `path_template` без `{domain}` работают). Why: папки — грубая стабильная навигация, тонкая — хабы и `part_of` (ТЗ §2).
- enforced at: план — `CLS-wikisvc-core.page_path`, `CLS-wikisvc-core.validate_page`. On violation: `ERR-domain_unknown`, `ERR-required_field`, `ERR-path_mismatch`.

### INV-auto-class-scope — Границы класса auto
status: planned

- statement: класс `auto` (`STATE-fact-review-class`) считается ядром по diff предложения и допустим только для новых страниц `fact` из ingest, запущенного человеком (`kind=human`); единственное разрешённое изменение существующих страниц — дописывание раздела `## Facts` хабов; других правок существующих страниц и рёбер (кроме `about` новых фактов) нет, без `replaces`, `valid_to`, смены `sensitivity` или `status`, без `kind: snippet` и фактов с URL или командами. Всё остальное — `queue`. Why: авто-приём не должен менять смысл принятого (ТЗ §8.6); блок `auto` принимает человек одним действием (Q-kb-auto-accept-human-decides).
- enforced at: план — `CLS-wikisvc-core.validate_set` при валидации предложения (решение координатора 2026-10-20). On violation: класс понижается до `queue`.
