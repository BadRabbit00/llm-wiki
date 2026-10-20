# wikisvc-core: контракты

> HTTP, событий и CLI у ядра нет: эндпоинты — у SVC-wikisvc, MCP-инструменты — у SVC-wikisvc-mcp,
> команды — у SVC-wikisvc-cli. Ядро владеет форматами файлов контента вики (git-репозиторий
> BKT-wikisvc-core.wiki-repo), файлом ролей и (v3 planned) DTO ответов слоя знаний. Все YAML читаются только safe-загрузчиком без алиасов
> (CLS-wikisvc-core.parse), кодировка UTF-8, переводы строк LF.

## Форматы файлов

### FMT-wikisvc-core.page — Страница вики: YAML-frontmatter + Markdown
status: implemented | owner: LIB-wikisvc-core

- kind: Markdown с YAML-frontmatter между строками `---`; путь `wiki/<path_template типа>` (FMT-wikisvc-core.page-type)
- producer / consumer: пишет только CLS-wikisvc-core.Proposals (через предложение) и CLS-wikisvc-core.review; читают CLS-wikisvc-core.Indexer, CLS-wikisvc-core.validate_page
- changed: 2026-10-20 v3 (planned): необязательные общие поля `domain` и `scopes`; элемент `relations` — строка или DTO-wikisvc-core.RelationRef; страницы слоя знаний лежат в `wiki/kb/` (FMT-wikisvc-core.fact, FMT-wikisvc-core.topic, FMT-wikisvc-core.tech, FMT-wikisvc-core.question); старые страницы без `domain` валидны как раньше

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `id` | string | да | `[a-z0-9]+(-[a-z0-9]+)*`, ≤ 80, префикс типа | ID страницы, уникален в вики |
| `type` | string | да | ключ из `schema/page-types/` | тип страницы |
| `title` | string | да | 3..120 | заголовок |
| `summary` | string | да | 20..`summary_max` типа (200, у правила 160), одна строка | тезис для поиска и блока политик |
| `status` | enum(draft\|verified\|outdated) | да | любая запись в предложении сбрасывает в `draft` | проверена ли человеком |
| `sensitivity` | enum(public\|internal\|restricted) | нет | по умолчанию `internal` | SEC-clearance, нужный для чтения |
| `tags` | string[] | нет | из `schema/tags.yaml` | теги |
| `aliases` | string[] | нет | у правила желательно ≥ 2 | синонимы для поиска |
| `sources` | string[] | нет | ID `src-…` | источники; дают ребро `cites` |
| `relations` | map<string,string[]> | нет | связь из FMT-wikisvc-core.relations, разрешена типом | типизированные связи (v3 planned: тип — map<string,(string \| DTO-wikisvc-core.RelationRef)[]>; строка = `{id}` с весом связи по умолчанию) |
| `domain` | string? | для типов с `{domain}` в `path_template` | путь из FMT-wikisvc-core.domains, иначе ERR-domain_unknown | домен страницы, даёт область `domain:<domain>` (v3 draft, INV-one-domain-per-page) |
| `scopes` | string[] | нет | значения по FMT-wikisvc-core.scopes | области страницы сверх `domain:<domain>`; у правила `applies_to` — алиас (v3 draft; общее поле — решение Q-kb-scopes-format) |
| `created`, `updated` | string | да | ISO 8601 | ставит сервис |
| `verified_by`, `verified_at` | string? | нет | ставит только человек | кто и когда подтвердил |
| поля типа | — | по типу | `extra_fields` типа; неизвестное поле — ошибка | например `parent` у `app-doc`, `owner` |

- body: разделы H2 из `required_sections` типа; ссылки `[[id]]` или `[[id|текст]]`; цитаты `[@src-id]` или `[@src-id стр. 12-14 "цитата"]` (`гл.` вместо `стр.`, цитата ≤ 30 слов и ≥ 2 слов); код в блоках и спанах ссылок не даёт; > 12000 символов — предупреждение `W_LONG_PAGE`
- запрещено: секреты (CLS-wikisvc-core.secret_kinds, плейсхолдеры `${VAR}` и `<secret>` допустимы); править `wiki/index.md` и `wiki/log.md` — их пишет CLS-wikisvc-core.generate
- example:

```markdown
---
id: term-proposal
type: term
title: Предложение
summary: Набор правок вики, который принимает человек-ревьюер.
status: planned
created: '2026-10-01'
updated: '2026-10-01'
---

## Определение
```

### FMT-wikisvc-core.rule — Страница правила компании
status: implemented | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page с `type: rule`, путь `wiki/rules/<slug>.md`, ID `rule-<slug>`; разделы `Правило`, `Обоснование`, `Примеры`; `summary` ≤ 160
- producer / consumer: пишут агенты и люди через предложения; `lifecycle`, `level`, `priority`, `owner`, `deprecated_reason` агент изменить не может (INV-agent-rule-inert), меняет человек при принятии (`promote`/`deprecate`); читает CLS-wikisvc-core.Policies
- changed: 2026-10-20 v3 (planned): связь `grounded_in` → `fact`/`topic` (у `rule`, `adr`, `pattern`, `playbook`; FMT-wikisvc-core.relations); `refines` разрешён и между фактами; `applies_to` читается как алиас общего поля `scopes`

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `category` | enum(code-style\|architecture\|logging\|errors\|security\|testing\|stack\|git\|build-ci\|docs\|process) | да | | группа в блоке политик |
| `level` | enum(must\|should\|idea) | да | `must` требует `owner` и `sources` | сила правила |
| `lifecycle` | enum(candidate\|active\|deprecated) | да | `active` только с `verified_by`; `candidate` — `status: draft` и level idea/should | STATE-rule-lifecycle |
| `applies_to` | string[] | да | ≥ 1; значения из FMT-wikisvc-core.scopes или `*` | области применения |
| `priority` | int32 | нет | 1..5, по умолчанию 3 | порядок в блоке |
| `origin` | enum(management\|team\|book\|article\|chat\|code) | да | `book`/`article` требуют `sources` и цитату | откуда правило |
| `owner` | string? | нет | ≤ 128 | ответственный |
| `enforced_by` | string[] | нет | `tool:<имя>`, `ci:<имя>` или `none` | чем проверяется автоматически |
| `deprecated_reason` | string? | при `deprecated` | ≤ 200 | почему снято |

### FMT-wikisvc-core.page-type — Описание типа страницы `schema/page-types/<type>.yaml`
status: implemented | owner: LIB-wikisvc-core

- kind: YAML-словарь, один файл на тип; модель `PageType` (CLS-wikisvc-core.Registry)
- schema: `type`, `prefix`, `path_template` (подстановки `{slug}`, `{parent_slug}`), `title_ru`, `required_sections` (string[]), `extra_fields` (map имя → `type`: str\|int\|list, `required`, `enum`, `pattern`, `item_enum`, `item_pattern`, `min_items`, `max_items`, `max_length`, `min`, `max`, `default`), `allowed_relations`, `template` (заготовка тела), `summary_max` (200), `sources_required` (true)
- типы в шаблоне: `adr` (adr, `decisions/`), `app` (app, `apps/{slug}/index.md`), `app-doc` (appdoc), `entity` (ent), `lesson` (les), `pattern` (pat), `playbook` (pb), `process` (proc), `role` (role), `rule` (rule), `source` (src, обязательны `kind`, `raw_path`, `raw_sha256`, `ingested_at`), `system` (sys), `term` (term)
- producer / consumer: администратор правит в git; CLS-wikisvc-core.load_registry читает при старте и `reindex`; изменение `schema/` всегда ведёт к полной перестройке индекса
- changed: 2026-10-20 v3 (planned): подстановка `{domain}` в `path_template` (домен проверяется по FMT-wikisvc-core.domains до вычисления пути; `{domain}` в шаблоне делает поле `domain` обязательным — решение Q-kb-domains-format); `extra_fields.type` += `dict` (map<string,string>, значения — по `item_enum`) и `date` (ISO 8601 `YYYY-MM-DD`); `default` применяется в CLS-wikisvc-core.validate_page; новые типы `fact` (f), `topic` (top), `tech` (tech), `question` (q) — FMT-wikisvc-core.fact … FMT-wikisvc-core.question; `source` — FMT-wikisvc-core.source; `rule`, `adr`, `pattern`, `playbook` += `grounded_in` в `allowed_relations`

### FMT-wikisvc-core.relations — Справочник связей `schema/relations.yaml`
status: implemented | owner: LIB-wikisvc-core

- kind: YAML-словарь `имя связи → {inverse, symmetric, from, to, same_type}`; модель `Relation`
- schema: `inverse` — имя обратной связи (в frontmatter не пишется, ошибка `E_REL_UNKNOWN`), `symmetric` (bool), `from`/`to` — допустимые типы источника и цели (пусто = любые), `same_type` — цель того же типа
- связи шаблона: automates, integrates_with, reads, writes, stored_in, owned_by, participates_in, part_of, depends_on, governed_by, implements, supersedes, caused_by, related (≤ 3 на страницу), refines, conflicts_with
- producer / consumer: администратор; CLS-wikisvc-core.upgrade_schema дописывает связи из шаблона; читает CLS-wikisvc-core.validate_set
- changed: 2026-10-20 v3 (planned): у связи поле `weight` (float64, базовый вес; нет в файле — 1.0, как `DEFAULT 1.0` в TBL-wikisvc-core.index.edges); у ребра вес переопределяет DTO-wikisvc-core.RelationRef `w`; вес влияет только на ранжирование в CLS-wikisvc-core.ppr, не на валидацию; новые связи — таблица ниже (ТЗ §4); `refines` расширяется на `fact`; существующие `part_of` (любой тип, `same_type`) и `conflicts_with` не меняются

Связи слоя знаний (v3 planned). «Сим.» — симметричная; вес — стартовое значение, тюнится на FMT-wikisvc-core.kb-eval:

| rel | обратная | откуда → куда | вес | смысл |
|---|---|---|---|---|
| `about` | `has_fact` | fact, question → topic, tech | 1.0 | принадлежность хабу; порядок — раздел `Facts` хаба |
| `applies_with` | сим. | fact, topic ↔ fact, topic | 0.8 | «применяя это, учитывай и то» |
| `supports` | `supported_by` | fact → fact | 0.7 | факт-свидетельство |
| `contradicts` | сим. | fact ↔ fact | 0.9 | противоречие; оба факта `confidence: contested` до разрешения |
| `refines` | `refined_by` | fact, rule → fact, rule | 0.7 | частный случай (было rule → rule) |
| `precedes` | `follows` | fact → fact | 0.6 | порядок шагов и изучения |
| `builds_on` | `prerequisite_of` | topic → topic | 0.5 | что знать раньше |
| `instance_of` | `has_instance` | tech → topic | 0.8 | технология — экземпляр понятия |
| `alternative_to` | сим. | tech ↔ tech | 0.6 | конкуренты |
| `replaces` | `replaced_by` | tech, fact → tech, fact | 0.7 | «вместо X теперь Y»; `replaced_by` у факта ⇒ STATE-fact `outdated` (решение Q-kb-derived-status) |
| `grounded_in` | `grounds` | rule, adr, pattern, playbook → fact, topic | 0.9 | предписание опирается на знание |
| `answered_by` | `answers` | question → fact | 1.0 | закрытие вопроса (STATE-question) |
| `part_of` | `has_part` | любой → тот же тип (как сейчас) | 0.5 | дерево тем |
| `related` | сим. | любые (как сейчас) | 0.2 | слабая, ≤ 3 на страницу |
| `covers` | `covered_by` | source → topic | 0.3 | оглавление источника на хабах; в белый список PPR не входит (решение Q-kb-core-defaults) |
| `conflicts_with` | сим. | rule ↔ rule (как сейчас) | — | не меняется |

Производные рёбра (в файлах не хранятся): `links_to` (`[[…]]`), `cites` (`[@…]`) — как сейчас, вес 1.0; `same_hub` 0.4, `co_cited` 0.3, `similar` = косинус − 0.5 — в TBL-wikisvc-core.index.soft_edges. Вес связи без значения в файле (automates и др.) — 1.0; в обход PPR они не входят (белый список — CLS-wikisvc-core.Ask).

### FMT-wikisvc-core.scopes — Области применения правил `schema/scopes.yaml`
status: implemented | owner: LIB-wikisvc-core

- kind: YAML-список строк `<ось>:<значение>`; файла может не быть (тогда областей нет)
- example: `- lang:python`, `- framework:fastapi`, `- app:service`
- producer / consumer: администратор; проверяют CLS-wikisvc-core.validate_rule (`E_SCOPE_UNKNOWN`), CLS-wikisvc-core.Policies, CLS-wikisvc-core.ProjectTemplate
- changed: 2026-10-20 v3 (planned): YAML-словарь `axes` (ТЗ §6) + список `values`; старый файл-список читается как `values` с осями из префиксов (решение Q-kb-scopes-format)

```yaml
axes:
  domain: {hierarchical: true}   # значения — FMT-wikisvc-core.domains; domain:db покрывает domain:db/kv
  lang:   {}                     # значения — из values
  tech:   {from: tech-pages}     # tech:<slug> страниц FMT-wikisvc-core.tech
  layer:  {enum: [kernel, runtime, app, infra]}
  scale:  {enum: [single-node, cluster, 1m-rps]}
  stage:  {enum: [design, implement, review, operate]}
  framework: {}                  # оси старого файла сохраняются
  app: {}
values: [lang:python, lang:rust, framework:fastapi, app:service]
```

- совпадение: область страницы подходит области запроса, если равна ей или (для `hierarchical`) лежит под ней; `*` — всё (направление иерархии — решение Q-kb-scopes-format); `tech:` проверяется по индексу (CLS-wikisvc-core.validate_set), остальное — по файлу

### FMT-wikisvc-core.profiles — Профиль проекта `schema/profiles/<id>.yaml`
status: implemented | owner: LIB-wikisvc-core

- kind: YAML-словарь, модель `Profile`: `id`, `title`, `scopes` (string[]), `budget_tokens` (int32 ≥ 1, по умолчанию 2000)
- example: `id: python-fastapi`, `scopes: ["lang:python", "framework:fastapi", "app:service"]`, `budget_tokens: 2000`
- producer / consumer: администратор; CLS-wikisvc-core.Policies берёт области и бюджет профиля; неизвестный профиль → ERR-profile_unknown (404)
- changed: 2026-10-20 v3 (planned): `reference_model` (string?, семейство модели по умолчанию, если клиент не передал `model` в brief — решение Q-kb-novelty-reference-model); `brief` {`include_novelty`: enum(common\|differs\|unique)[], по умолчанию `[differs, unique]`, неизвестное = `differs`; `max_facts`: int32 ≥ 1, по умолчанию 40}; читает CLS-wikisvc-core.Brief (ТЗ §6)

### FMT-wikisvc-core.project-template — Шаблон проекта `schema/project-templates/<id>.yaml`
status: implemented | owner: LIB-wikisvc-core

- kind: YAML, строгая схема без лишних полей, только данные (никаких хуков); в стартовом шаблоне вики файлов нет
- schema: `id` (= имя файла, `[a-z0-9][a-z0-9-]{0,63}`), `title`, `profile` (из FMT-wikisvc-core.profiles), `scopes` (из FMT-wikisvc-core.scopes), `components[]` {`name` `[a-z0-9][a-z0-9-]{0,31}`, `kind` svc\|lib, `lang` `LANG-…`}, `files[]` {`path`, `content`} (≤ 200 файлов, файл ≤ 256 KiB, сумма ≤ 2 MiB), `policy_blocks[]` {`file`, `profile`}
- пути: относительные, без `..`, `.`, `.git`, `\`, `:`, NUL; `.wiki-project.yaml` запрещён (им управляет `wk`); дубли и файл-над-каталогом запрещены
- producer / consumer: администратор; невалидный шаблон уходит в карантин (`invalid_project_templates`, ERR-template_invalid), сервис продолжает работу; потребитель — внешний клиент `wk` (ACT-coding-agent)

### FMT-wikisvc-core.policy-block — Блок политик в файле проекта
status: implemented | owner: LIB-wikisvc-core

- kind: фрагмент Markdown внутри файла проекта (`AGENTS.md`): `<!-- wikisvc:begin version=<8 hex> -->` … `<!-- wikisvc:end -->`
- content: текст по шаблону `schema/policy-template.md` вики (если нет — из MOD-wikisvc-core.template) с подстановками `{profile}`, `{version}`, `{used_tokens}`, `{rules}`; правила — строки `- [MUST|SHOULD] <summary> (проверяется: …) → <ID правила>`, группы «Обязательные» и «Желательные»
- version: первые 8 hex SHA-256 от пар (ID, `version`) включённых правил и параметров компиляции — одинаковый вход даёт одинаковый блок
- producer / consumer: CLS-wikisvc-core.Policies компилирует, CLS-wikisvc-core.export_block пишет; меняется только текст между маркерами (INV-policy-block-only), блок дописывается в конец, если его нет; два блока или маркер без пары → ERR-policy_block

### FMT-wikisvc-core.roles-file — Сопоставление групп SSO с ролями (`roles.yaml`)
status: implemented | owner: LIB-wikisvc-core

- kind: YAML-словарь, модель `RoleMap`, лишние поля запрещены; путь `ROLES_FILE` (по умолчанию `/etc/llm-wiki/roles.yaml`), вне `WIKI_ROOT` — файл оператора, не контента
- schema: `default` — {`role`, `clearance`}, обязан быть `reader`/`public` (запрет по умолчанию); `groups` — map имя группы → {`role`: reader…admin (ROLE-reader…ROLE-admin), `clearance`: SEC-clearance}
- resolve: из совпавших групп берётся наибольшая роль и наибольший допуск по отдельности; нет совпадений — `default`
- example: `groups: {wiki-reviewers: {role: reviewer, clearance: internal}}`
- producer / consumer: ACT-operator; читает CLS-wikisvc-core.Sessions при старте (если включён выпуск сессий) и проверка `auth_check` SVC-wikiagent; ошибка формата — сервис не стартует

## Слой знаний v3 (planned)

Типы страниц `wiki/kb/{domain}/{topics|facts|tech|questions}/<id>.md` (ТЗ §2–3). Имя файла = ID, поэтому в
`path_template` префикс пишется явно (как в примере ТЗ §2). Общие поля — FMT-wikisvc-core.page; `domain` обязателен.
Связи — FMT-wikisvc-core.relations. Тело и `summary` — на английском, русские термины — в `aliases` (ADR-0023).

### FMT-wikisvc-core.fact — Атомарный факт `type: fact`
status: planned | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page, префикс `f`, `path_template: kb/{domain}/facts/f-{slug}.md`; разделы: `Claim` обязателен, `Why`, `Example`, `Caveats` — по необходимости; ENT-fact, STATE-fact
- producer / consumer: пишут люди и SVC-wikiagent через предложения (FLOW-fact-ingest); читают CLS-wikisvc-core.Indexer, CLS-wikisvc-core.Knowledge, CLS-wikisvc-core.Brief, CLS-wikisvc-core.Ask

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `claim` | string | да | 20..200 символов, одна строка, одно минимальное утверждение (INV-claim-minimal); иначе ERR-claim_missing | единица дедупликации и поиска, уровень L0 |
| `summary` | string | да | общее поле, ≤ 200 | деконтекстуализированный `claim`, уровень L1 и ревью |
| `kind` | enum(definition\|mechanism\|constraint\|tradeoff\|number\|convention\|api\|pitfall\|comparison\|step\|snippet) | да | `snippet` — код в разделе `Example` | вид факта |
| `confidence` | enum(sourced\|inferred\|contested\|open) | нет | по умолчанию `inferred`; `open` ставится явно = «нужна проверка», его подхватывает JOB-wikiagent.heal (решение Q-kb-core-defaults); эффективный `contested` при `contradicts` вычисляет индекс (решение Q-kb-derived-status) | степень проверки |
| `novelty` | map<string, enum(common\|differs\|unique)> | нет | `dict`, по умолчанию `{}`; только ручное переопределение человеком — измеренная новизна хранится производно в TBL-wikisvc-core.state.novelty (пишет JOB-wikiagent.novelty-scan через CLS-wikisvc-core.Verdicts); итог = файл, иначе таблица, иначе `differs` (решение Q-kb-novelty-write-path) | новизна для модели |
| `valid_for` | string? | при `kind` ∈ {number, api, pitfall} | иначе ERR-valid_for_missing; `[A-Za-z0-9_.:<>=!, -]{1,64}`, одна строка; разбор строгой грамматикой `условие (, условие)*`, где условие — `имя оп версия` (оп ∈ `>= <= == != > <`) или `метка` | условие применимости: `rust>=1.75`, `kernel:io_uring` |
| `valid_from`, `valid_to` | date? | нет | `valid_to` непустой ⇒ STATE-fact `outdated` (решение Q-kb-derived-status) | время действительности в мире (bi-temporal, ADR-0021) |
| `value`, `unit`, `conditions` | string? | нет | для `kind: number`; тип `value` — строка (решение Q-kb-core-defaults) | число и условия замера |
| `measured_at` | date? | нет | для `kind: number` | когда измерено |

- allowed_relations: about, applies_with, supports, contradicts, refines, precedes, replaces, related
- sensitivity: у факта из ingest — чувствительность источника, по умолчанию `restricted`; понижение или `public` — причина `sensitivity_downgrade`, класс не `auto` (решение Q-kb-ingest-sensitivity); `confidence: sourced` сохраняется только на пути ingest, любая другая запись сбрасывает его в `inferred` (CLS-wikisvc-core.Proposals)
- lint: тело > 1500 символов — `W_FACT_LONG`; без `about` — `W_FACT_NO_HUB` (таблица кодов — `code.md`, CLS-wikisvc-core.Lint)

### FMT-wikisvc-core.topic — Хаб темы `type: topic`
status: planned | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page, префикс `top`, `path_template: kb/{domain}/topics/top-{slug}.md`; ENT-topic
- разделы: `Digest` (обязателен, ≤ 800 символов, abstractive-выжимка; вектор уровня `digest`), `Facts` (обязателен: нумерованный список `[[f-…]]`, порядок = канонический порядок выдачи, INV-canonical-order), `Open questions` (необязателен, `[[q-…]]`)
- поля: `priority` int32 1..5, по умолчанию 3 (вес хаба в CLS-wikisvc-core.Brief; решение Q-kb-core-defaults)
- allowed_relations: part_of, builds_on, applies_with, related
- инварианты: множество `Facts` = множество `has_fact` (`W_HUB_FACTS_MISMATCH`); 0 фактов — `W_HUB_EMPTY`, > 60 — `W_HUB_TOO_LARGE`; факт `outdated` в `Facts` — `W_HUB_CITES_OUTDATED`; `Digest` > 800 символов — `W_DIGEST_LONG` (решение Q-kb-lint-semantics)

### FMT-wikisvc-core.tech — Технология `type: tech`
status: planned | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page, префикс `tech`, `path_template: kb/{domain}/tech/tech-{slug}.md`; обязательных разделов нет (ТЗ не задаёт; решение Q-kb-core-defaults); ENT-tech

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `category` | enum(database\|runtime\|library\|protocol\|tool\|service\|chip\|board\|model) | да | | вид технологии |
| `adoption` | enum(STATE-tech) | да | evaluating, adopted, avoid, legacy, unknown | наше отношение; в ТЗ §3.3 это `status`, но имя занято статусом ревью (решение Q-kb-tech-question-status) |
| `verdict` | string | да | одна строка | наше суждение, не описание из README |
| `current_version` | string? | нет | | для `W_STALE_VERSION` |
| `homepage` | string? | нет | только `http://` или `https://`, без userinfo (`user@`), ≤ 2048 символов | сайт технологии |

- allowed_relations: instance_of, alternative_to, replaces, related; факты о технологии — FMT-wikisvc-core.fact с `about: [tech-…]`; область `tech:<slug>` появляется автоматически (FMT-wikisvc-core.scopes)

### FMT-wikisvc-core.question — Открытый вопрос `type: question`
status: planned | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page, префикс `q`, `path_template: kb/{domain}/questions/q-{slug}.md`; обязательных разделов нет (решение Q-kb-core-defaults); ENT-question
- поля: `priority` int32 1..5, по умолчанию 3 (решение Q-kb-core-defaults; в примере ТЗ — 2)
- состояние STATE-question: `open`, пока `answered_by` пуст, иначе `answered`; вычисляет индекс, в поле `status` не пишется (решение Q-kb-tech-question-status)
- allowed_relations: about, answered_by, related; без движения 90 d — `W_QUESTION_STALE`

### FMT-wikisvc-core.source — Источник `type: source`
status: planned | owner: LIB-wikisvc-core

- kind: FMT-wikisvc-core.page, префикс `src`, путь `sources/{slug}.md`; разделы `Кратко`, `Ключевые факты`, `Что изменилось в вики`; поля как сейчас: `kind`, `author`, `year`, `edition`, `url`, `raw_path`, `raw_sha256`, `ingested_at`; ENT-library-item
- v3: `kind` += `paper`, `datasheet`, `spec`, `course`, `video`, `rfc`; `covers` (string[], ID `top-…`) — оглавление источника, спроецированное на хабы; каждый ID должен существовать (ERR-link_unresolved в CLS-wikisvc-core.validate_set); каждый элемент даёт ребро `covers` → обратное `covered_by` (source → topic, kind `frontmatter`, вес 0.3, в белый список PPR не входит; решение Q-kb-core-defaults); `url` — только `http://` или `https://`, без userinfo, ≤ 2048 символов

### FMT-wikisvc-core.domains — Дерево доменов `schema/domains.yaml`
status: planned | owner: LIB-wikisvc-core

- kind: YAML-словарь `путь домена → описание` (решение Q-kb-domains-format); путь — `[a-z0-9-]+(/[a-z0-9-]+)*`
- example: `systems: "distributed and high-load systems"`, `lang/rust: "Rust language, idioms, ecosystem"`, `db: "storage engines, kv, oltp, olap"`
- стартовое дерево (MOD-wikisvc-core.template): systems, net, db, concurrency, os, lang, lang/rust, lang/python, lang/cpp, lang/c, lang/nix, infra, security, ml, hardware, business, math (ТЗ §2)
- правила: `domain` страницы — ровно путь из файла; родитель каждого пути — отдельной строкой файла (решение Q-kb-domains-format); расширяет только администратор (CLI-wikisvc-cli.domains.add), предложение агента с правкой файла — ERR-proposal_path, как любые правки вне `wiki/`
- fail-closed: ключ не по шаблону пути, не строка-описание или неразбираемый файл — CLS-wikisvc-core.load_registry отказывает в загрузке схемы (сервис не стартует, reindex не идёт), а не пропускает строку
- producer / consumer: администратор; читают CLS-wikisvc-core.load_registry, CLS-wikisvc-core.page_path, CLS-wikisvc-core.initialize; изменение — полная перестройка индекса, как всё в `schema/`

### FMT-wikisvc-core.kb-eval — Eval-набор слоя знаний `tests/fixtures/kb-eval.yaml`
status: planned | owner: LIB-wikisvc-core

- kind: YAML-список вопросов; 50–100 на этапе 1, растёт с каждой книгой (ТЗ §10, ADR-0025)
- элемент: `q` (string), `lang` enum(en\|ru), `hops` enum(single\|multi), `gold` (string[] ID фактов, ≥ 1)
- пары для дедупликации: 100–200 штук в `tests/fixtures/kb-pairs.yaml` — `{a, b, label: enum(duplicate\|refines\|contradicts\|independent)}` (отдельный файл — решение Q-kb-core-defaults)
- метрики: Recall@8 по `seeds[]`, Recall@20 по `seeds ∪ expanded` DTO-wikisvc-core.AskResult; срезы single/multi и ru/en; доля `expansion_used` и прирост recall от него (OBS-eval-metrics)
- consumer: CLS-wikisvc-core.evaluate — для CLI-wikisvc-cli.eval и `pytest -m eval` в PIPE-ci; порог — не ниже зафиксированной базовой линии (NFR-eval-recall-baseline)

### FMT-wikisvc-core.knowledge-block — Блок знаний в файле проекта
status: planned | owner: LIB-wikisvc-core

- kind: фрагмент Markdown: `<!-- wikisvc:knowledge begin version=<8 hex> -->` … `<!-- wikisvc:knowledge end -->` (конечный маркер и `version` — по образцу FMT-wikisvc-core.policy-block, решение Q-kb-core-defaults)
- content: DTO-wikisvc-core.BriefResult в виде текста ТЗ §7.1 — заголовок `## Knowledge brief: <profile> (v <version>, ~N tokens)`, группы `### <hub> (N facts, M shown)`, строки `- <id>: <claim>`, хвост `Details: get_fact(id). Related facts: expand(ids).`
- producer / consumer: CLS-wikisvc-core.Brief компилирует, CLS-wikisvc-core.export_block пишет только между своими маркерами (INV-policy-block-only); по умолчанию brief запрашивается в начале сессии, блок — по выбору (FLOW-knowledge-brief)

### FMT-wikisvc-core.workflow — Сценарии агента `schema/workflows/*.md`
status: planned | owner: LIB-wikisvc-core

- kind: Markdown без frontmatter; имя файла = имя сценария; CLS-wikisvc-core.Schema отдаёт `AGENTS.md` вики и все сценарии одним текстом
- v3: новые `knowledge-query.md` (brief в начале, `ask` перед решением, `list_questions`, ссылка по ID), `fact-authoring.md` (claim/summary, `kind`, `valid_for`, привязка к хабу, `propose_fact` с `confidence: inferred` вместо выдумки); `book-ingest.md` переписывается под FLOW-fact-ingest; `AGENTS.md` вики получает обязанности ТЗ §7.4 (INV-cite-by-id, INV-rules-pushed-knowledge-pulled)
- producer / consumer: MOD-wikisvc-core.template; в существующие вики попадают через CLS-wikisvc-core.upgrade_schema

## DTO слоя знаний (v3 planned)

Структуры ответов ядра; HTTP (DTO-wikisvc.*) и MCP рендерят их сами. Порядок элементов — канонический (INV-canonical-order).

### DTO-wikisvc-core.RelationRef — Ребро с весом в frontmatter
status: planned | owner: LIB-wikisvc-core

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `id` | string | да | ID существующей страницы | цель |
| `w` | float64? | нет | 0 < w ≤ 1 (решение Q-kb-core-defaults); нет — вес связи | заменяет базовый вес связи; у рёбер `origin` extracted/inferred — не выше базового (решение Q-kb-edge-weight-override) |
| `note` | string? | нет | одна строка, без секретов | когда применять связь |
| `origin` | enum(manual\|extracted\|inferred)? | нет | по умолчанию `manual` | провенанс: руками, из ingest, от heal |

### DTO-wikisvc-core.FactView — Страница на уровне L0/L1/L2
status: planned | owner: LIB-wikisvc-core

| поле | тип | обяз. | смысл |
|---|---|---|---|
| `id`, `type` | string | да | |
| `level` | enum(0\|1\|2) | да | L0 `claim` (у topic/tech/question — `summary`); L1 `summary` + `Caveats` + первый пример ≤ 600 символов, у topic — `Digest`; L2 — страница целиком |
| `text` | string | да | текст уровня; в L1/L2 и `Digest` ссылки `[[id]]`, `[@src]` и связи на невидимые по допуску страницы вырезаны (SEC-graph-clearance-mask) |
| `status` | enum(draft\|verified\|outdated) | да | эффективный статус из индекса (STATE-fact) |
| `version` | string | да | `content_hash` страницы — `base_version` для правки |
| `claim`, `summary` | string? | для `fact` | поля FMT-wikisvc-core.fact (у прочих типов — только `summary`) |
| `kind`, `confidence` | string? | для `fact` | `kind`, `confidence` FMT-wikisvc-core.fact |
| `novelty` | map<string, enum(common\|differs\|unique)> | нет | итоговая новизна по семействам моделей: переопределение из файла поверх TBL-wikisvc-core.state.novelty |
| `valid_for` | string? | нет | условие применимости |
| `valid_from`, `valid_to` | date? | нет | время действительности |
| `replaced_by` | string[] | нет | ID фактов и технологий, заместивших этот (обратное `replaces`) |
| `adoption` | enum(STATE-tech)? | для `tech` | состояние технологии — это имя поля во всех ответах |
| `origin` | enum(book\|manual\|chat) | да | происхождение страницы — `kind` принявшего предложения; для подвала доставки |
| `contested_with` | string[] | нет | пары `contradicts`: выдаются рядом с пометкой `⚠ contested` |
| `hub` | string? | нет | хаб, под которым факт показан |
| `edges` | DTO-wikisvc-core.EdgeView[] | только L2 | рёбра с весами для CLS-wikisvc-core.Knowledge `get_fact` |
| `tokens` | int32 | да | оценка CLS-wikisvc-core.estimate_tokens |

### DTO-wikisvc-core.EdgeView — Ребро в ответах
status: planned | owner: LIB-wikisvc-core

- единственная форма ребра во всех ответах ядра, HTTP и MCP (FactView `edges`, DTO-wikisvc-core.ExpandResult, CLS-wikisvc-core.GraphStore `neighbors`/`export`)

| поле | тип | обяз. | смысл |
|---|---|---|---|
| `src`, `dst` | string | да | концы ребра; ребро на невидимую страницу не выдаётся (INV-404-not-403) |
| `rel` | string | да | связь FMT-wikisvc-core.relations или производная (`links_to`, `cites`, `same_hub`, `co_cited`, `similar`) |
| `w` | float64 | да | итоговый вес ребра (TBL-wikisvc-core.index.edges `weight` или TBL-wikisvc-core.index.soft_edges `weight`) |
| `note` | string? | нет | заметка DTO-wikisvc-core.RelationRef |
| `origin` | enum(manual\|extracted\|inferred) | да | провенанс ребра |
| `kind` | enum(frontmatter\|wikilink\|citation\|inverse\|soft) | да | откуда ребро (CLS-wikisvc-core.Edge; `soft` — мягкое) |

### DTO-wikisvc-core.AskResult — Ответ `ask`
status: planned | owner: LIB-wikisvc-core

| поле | тип | смысл |
|---|---|---|
| `seeds` | DTO-wikisvc-core.FactView[] | семена (L1, при нехватке бюджета — L0) |
| `expanded` | DTO-wikisvc-core.FactView[] | найденное расширением по графу, L0 |
| `omitted_ids` | string[] | не влезло в бюджет — срезано по уровню, а не молча |
| `hubs` | {id, title, facts_total}[] | хабы семян одной строкой |
| `version` | string | хеш `meta.generation` индекса + модель эмбеддингов |
| `expansion_used` | bool | применялось ли расширение PPR |
| `degraded` | bool | векторы недоступны: ответ собран из BM25 и явных рёбер (решение Q-kb-embeddings-degraded) |
| `used_tokens`, `budget_tokens` | int32 | расход бюджета |

### DTO-wikisvc-core.BriefResult — Ответ `get_brief`
status: planned | owner: LIB-wikisvc-core

| поле | тип | смысл |
|---|---|---|
| `profile` | string | ID профиля FMT-wikisvc-core.profiles |
| `version` | string | 8 hex SHA-256 от пар (ID, `version`) включённых фактов и параметров — одинаковый вход даёт одинаковый brief |
| `groups` | {hub, title, facts_total, facts: DTO-wikisvc-core.FactView[]}[] | факты L0 по хабам в каноническом порядке |
| `omitted_ids` | string[] | кандидаты сверх бюджета или `max_facts` |
| `used_tokens`, `budget_tokens` | int32 | бюджет ≤ CFG-wikisvc.BRIEF_BUDGET_MAX |

Остальные ответы CLS-wikisvc-core.Knowledge:

| id | owner | поля | status |
|---|---|---|---|
| DTO-wikisvc-core.TopicResult | LIB-wikisvc-core | `topic` (DTO-wikisvc-core.FactView), `facts` (FactView[] уровня `level`), `open_questions` (string[] ID видимых вопросов раздела `Open questions`), `next_cursor?`, `omitted_ids[]`, `version` | planned |
| DTO-wikisvc-core.ExpandResult | LIB-wikisvc-core | `items` (FactView[] L0 соседей), `edges` (DTO-wikisvc-core.EdgeView[] между запрошенными ID и `items`), `omitted_ids[]`, `version` | planned |
| DTO-wikisvc-core.TechResult | LIB-wikisvc-core | `tech` (FactView L1 с `adoption`; `verdict`, `current_version?`), `facts` (FactView[] L0), `alternatives` (FactView[] L0) | planned |
| DTO-wikisvc-core.WhyResult | LIB-wikisvc-core | `paths` ({`nodes`: string[] ID от страницы через `grounded_in`/`supported_by` к фактам и источникам, `score`: float64}[] — лучший путь последним, ТЗ §7.3), `facts` (FactView[] L0 фактов путей), `sources` (string[] `src-…`) | planned |

### DTO-wikisvc-core.ProposalReasons — Класс ревью предложения и причины по фактам
status: planned | owner: LIB-wikisvc-core

- считает CLS-wikisvc-core.review_class при `submit` и `validate`; отдаётся в карточке предложения (DTO-wikisvc.* у SVC-wikisvc)

| поле | тип | смысл |
|---|---|---|
| `class` | enum(STATE-fact-review-class) | класс предложения: сильнейший из классов фактов (pair > queue > auto) |
| `needs_double_confirm` | bool | класс `pair`, правка `must`-правила, понижение `sensitivity` или > 5 страниц не-фактов — UI требует второго подтверждения (решение Q-kb-ui-double-confirm-facts) |
| `facts` | {id, class, reasons: string[]}[] | причины, по которым факт не `auto`: `contradicts`, `inferred`, `open`, `refines`, `possible_duplicate`, `convention`, `snippet`, `novelty_unique`, `url_or_shell`, `existing_page_edit`, `edge_edit`, `replaces`, `valid_to`, `sensitivity_downgrade`, `status_change`, `not_book_agent`, `citation_unverified`, `embeddings_unavailable` (список открыт, новые значения — тем же стилем) |
| `depends_on` | string[] | `pid` базовых предложений; принятие раньше них — ERR-proposal_dependency (решение Q-kb-proposal-dependencies) |
