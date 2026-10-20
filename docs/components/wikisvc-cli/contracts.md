# wikisvc-cli: контракты

> Команды `wikisvc`. Запуск в разработке — `nix develop -c wikisvc <команда>`.

## Общее для всех команд

- env: CFG-wikisvc.WIKI_ROOT, CFG-wikisvc.STATE_DIR, CFG-wikisvc.INDEX_DIR — нужны всем командам, кроме `version` и `init`.
- exit codes (общие): `0` — успех; `1` — ошибка ядра (`WikiError`, трассировка в stderr) или явный отказ команды;
  `2` — ошибка разбора аргументов Typer и `typer.BadParameter`.
- booleans: флаги вида `--x/--no-x`, по умолчанию выключены.
- consumers: ACT-operator.
- changed: 2026-10-20 v3 (planned): подгруппы `domains` и `embeddings`, команда `eval` (всего 18). Командам с векторами
  нужны CFG-wikisvc.EMBEDDINGS_URL, CFG-wikisvc.EMBEDDINGS_MODEL, CFG-wikisvc.EMBEDDINGS_POOLING,
  CFG-wikisvc.EMBEDDINGS_DIM, CFG-wikisvc.EMBEDDINGS_ENABLED, CFG-wikisvc.EMBEDDINGS_TIMEOUT_SECONDS,
  CFG-wikisvc.EMBEDDINGS_RETRIES. CFG-wikisvc.EMBEDDINGS_ENABLED по умолчанию включён: без
  CFG-wikisvc.EMBEDDINGS_URL `Settings` не проходит проверку и команда не стартует (код `1`, имя переменной в
  stderr). Ключа нет (локальный сервер на loopback, SEC-embeddings-boundary; решение Q-kb-embeddings-api-key).
  Сервер задан, но недоступен или self-test не прошёл: `reindex` без `--embeddings`, `lint`, `mcp` работают по тексту
  с предупреждением в stderr и прежним кодом выхода; `reindex --embeddings`, `embeddings selftest`, `eval` завершаются
  с `1` (ERR-embeddings_unavailable). Решение Q-kb-embeddings-degraded; rule-arch-outgoing-call-resilience.
- policies: rule-secrets-not-in-argv, rule-arch-layers (логика новых команд — в ядре), rule-arch-outgoing-call-resilience

## Запуск

### CLI-wikisvc-cli.version — Версия сервиса
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc version`; output: строка версии пакета (`wikisvc.__version__`)

### CLI-wikisvc-cli.serve — Запуск HTTP API
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc serve [--reload]`
- does: запускает uvicorn с фабрикой `wikisvc.main:create_app` (SVC-wikisvc), один воркер, хост CFG-wikisvc.BIND_HOST,
  порт CFG-wikisvc.BIND_PORT, уровень логов CFG-wikisvc.LOG_LEVEL; `--reload` — перезапуск при изменении кода (разработка)
- notes: при CFG-wikisvc.MCP_HTTP_ENABLED в том же процессе поднимается HTTP-транспорт SVC-wikisvc-mcp

### CLI-wikisvc-cli.mcp — MCP-сервер по stdio
status: implemented | owner: SVC-wikisvc-cli

- usage: `WIKI_TOKEN=… wikisvc mcp [--profile full|coding]` (по умолчанию `full`)
- does: под блокировкой записи переиндексирует контент и просрочивает предложения, затем обслуживает
  API-wikisvc-mcp.* по stdio до закрытия входа
- auth: CFG-wikisvc-mcp.WIKI_TOKEN на каждом вызове инструмента; без него — анонимно при CFG-wikisvc.ANONYMOUS_ACCESS
- exit codes: неизвестный профиль — `1` (`ValueError`)
- changed: 2026-10-20 v3 (planned): `--profile` enum(coding|full|knowledge), по умолчанию `full` (CLS-wikisvc-mcp.TOOL_PROFILES); переиндексация
  при старте включает инкрементальные эмбеддинги; провайдер недоступен — сервер всё равно стартует (Q-kb-embeddings-degraded)

## Репозиторий и схема

### CLI-wikisvc-cli.init — Новый репозиторий контента
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc init PATH`; args: `PATH` path (обяз.) — пустой или несуществующий каталог
- side effects: копирует шаблон FMT-wikisvc-core.project-template (страницы FMT-wikisvc-core.page, схемы
  FMT-wikisvc-core.page-type, FMT-wikisvc-core.relations, FMT-wikisvc-core.scopes, FMT-wikisvc-core.profiles),
  делает `CLAUDE.md` ссылкой на `AGENTS.md`, `git init -b main` и первый коммит от `wikisvc`
- errors: ERR-init_nonempty (каталог не пуст) → `1`
- calls: `initialize` (MOD-wikisvc-core.services); env не нужен
- changed: 2026-10-20 v3 (planned): шаблон несёт FMT-wikisvc-core.domains, типы `topic`, `fact`, `tech`, `question` и
  FMT-wikisvc-core.workflow слоя знаний (MOD-wikisvc-core.template); `init` создаёт в первом коммите дерево
  `kb/<домен>/{topics,facts,tech,questions}/` для каждого домена `schema/domains.yaml` (ТЗ §2; приёмка этапа 1, ТЗ §13);
  пустые каталоги держит `.gitkeep` (решение, Q-kb-cli-kb-tree). calls: CLS-wikisvc-core.initialize

### CLI-wikisvc-cli.schema.upgrade — Дополнить схему из шаблона
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc schema upgrade [--refresh-instructions]`
- does: от принципала `cli` (ROLE-admin) добавляет недостающие файлы `schema/**` из шаблона, дополняет
  `schema/relations.yaml` и поля `schema/page-types/source.yaml`, удаляет устаревшие типы правил;
  `--refresh-instructions` перезаписывает `AGENTS.md` и `schema/workflows/*.md` из шаблона
- output: JSON `{"commit", "updated", "removed"}`; нечего менять — пустые списки и текущий коммит
- side effects: коммит в main BKT-wikisvc-core.wiki-repo, переиндексация, запись аудита `schema.upgrade`
- notes: содержимое страниц не меняет — для этого CLI-wikisvc-cli.migrate-rules
- changed: 2026-10-20 v3 (planned): в существующую вики добавляет `schema/domains.yaml`, типы слоя знаний, связи ТЗ §4
  и оси ТЗ §6 (дополнением) и дерево `kb/` по доменам; `--refresh-instructions` приносит `knowledge-query.md`,
  `fact-authoring.md`, `book-ingest.md`. Логика — CLS-wikisvc-core.upgrade_schema. Без этого шага v3 на действующей
  вики не включается (решение, Q-kb-cli-kb-tree)

### CLI-wikisvc-cli.migrate-rules — Перевод старых правил в кандидаты
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc migrate-rules [--dry-run]`
- auth: без `--dry-run` — CFG-wikisvc-mcp.WIKI_TOKEN с ROLE-writer (иначе ERR-unauthorized / ERR-forbidden → `1`);
  с `--dry-run` — встроенный принципал `cli-preview` (ROLE-writer)
- output: JSON с планом изменений (`dry_run`, изменения); без `--dry-run` и при наличии изменений — ещё `proposal`
  и `validation`
- side effects: без `--dry-run` открывает предложение ENT-proposal «Migrate legacy rules to candidates» со страницами
  FMT-wikisvc-core.rule в статусе кандидата (STATE-rule-lifecycle); main не меняется до решения человека (INV-human-decides)

### CLI-wikisvc-cli.scopes.add — Добавить область применения
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc scopes add VALUE`; args: `VALUE` string вида `lang:python` (`[a-z][a-z0-9-]*:[a-z0-9][a-z0-9.-]*`)
- side effects: если области нет — коммит `schema/scopes.yaml` (FMT-wikisvc-core.scopes) в main от `cli`,
  переиндексация, аудит `scope.add`; повтор — без изменений (идемпотентна)
- output: значение области; errors: ERR-scope_unknown (неверный формат) → `1`

### CLI-wikisvc-cli.domains.add — Добавить домен в дерево `kb/`
status: planned | owner: SVC-wikisvc-cli

- usage: `wikisvc domains add PATH`; args: `PATH` string — путь домена вида `lang/zig` (ENT-domain), формат —
  FMT-wikisvc-core.domains; родитель должен существовать
- does: от принципала `cli` (ROLE-admin) под блокировкой записи одним коммитом в main BKT-wikisvc-core.wiki-repo
  добавляет домен в `schema/domains.yaml` и каталоги `kb/<PATH>/{topics,facts,tech,questions}/` (Q-kb-cli-kb-tree),
  переиндексирует, пишет аудит `domain.add`; повтор — без изменений (идемпотентна, как CLI-wikisvc-cli.scopes.add)
- output: путь домена; errors: ERR-domain_unknown (нет родителя или неверный формат) → `1`
- notes: только расширение (ТЗ §2): удаления и переименования нет — путь страниц `kb/{domain}/…` зависит от домена;
  агент через предложения домены не расширяет (ТЗ §2). Область `domain:<PATH>` возникает из дерева сама (ТЗ §6),
  CLI-wikisvc-cli.scopes.add не нужен. Проверка и запись — сервис ядра, CLI только разбирает аргумент и печатает
  (MOD-wikisvc-cli.app, rule-arch-layers)

## Индекс и проверки

### CLI-wikisvc-cli.reindex — Пересобрать индекс
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc reindex [--full]`
- does: под блокировкой записи пересобирает производный индекс RES-index-db из контента; `--full` — полная пересборка,
  заодно заменяет индекс, записанный более новой версией (откат обновления)
- output: `Index rebuilt; N issues.`
- changed: 2026-10-20 v3 (planned): `wikisvc reindex [--full] [--embeddings]`. `--embeddings` — полный пересчёт векторов
  трёх уровней (`claim`, `digest`, `chunk`; TBL-wikisvc-core.index.embeddings) моделью CFG-wikisvc.EMBEDDINGS_MODEL,
  нужен после смены модели или pooling (ТЗ §5). Без флага при CFG-wikisvc.EMBEDDINGS_ENABLED векторы пересчитываются
  только для изменившегося `content_hash` (JOB-wikisvc-core.embed-index). Сначала self-test (как
  CLI-wikisvc-cli.embeddings.selftest); провал — старые векторы не трогаются. Векторы считаются вне блокировки записи,
  под ней пишутся строки с неизменившимся `content_hash`; `--full` сохраняет совпавшие векторы (решение,
  Q-kb-cli-reindex-embeddings). Вывод: `Index rebuilt; N issues; embeddings: M computed, K reused.` Схема индекса
  1 → 2 (ADR-0016): первый запуск новой версии пересобирает индекс целиком

### CLI-wikisvc-cli.lint — Проверка контента
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc lint`
- does: переиндексирует под блокировкой и запускает `Lint.run` от `cli` (ROLE-admin, SEC-clearance#restricted)
- output: JSON-массив всех находок; exit codes: `1` — есть находка с `severity: error`
- changed: 2026-10-20 v3 (planned): новые коды ТЗ §9 — ошибки ERR-claim_missing, ERR-domain_unknown,
  ERR-valid_for_missing (код выхода `1`) и предупреждения `W_*` (список — CLS-wikisvc-core.Lint); формат вывода и
  коды выхода прежние. `W_POSSIBLE_DUPLICATE` требует векторов: без провайдера проверка пропускается с
  предупреждением в stderr (Q-kb-embeddings-degraded)

### CLI-wikisvc-cli.embeddings.selftest — Проверить провайдер эмбеддингов
status: planned | owner: SVC-wikisvc-cli

- usage: `wikisvc embeddings selftest`
- does: через CLS-wikisvc-core.Embeddings кодирует две фиксированные пары текстов из кода и сравнивает косинусы с
  эталоном модели CFG-wikisvc.EMBEDDINGS_MODEL в `meta.embeddings_selftest` индекса; расхождение > 0.02 — провал
  (ТЗ §5: неверный pooling даёт ~0.8 вместо ~1.0 без ошибки; решение Q-kb-embeddings-selftest). Эталона ещё нет —
  его записывает первый успешный запуск модели в ядре, команда только сообщает `expected: null`. Блокировку не берёт,
  индекс не меняет; таймаут и повторы — у CLS-wikisvc-core.Embeddings (rule-arch-outgoing-call-resilience)
- output: JSON `{"model", "pooling", "dim", "cosines", "expected", "ok"}`; при явно выключенном
  CFG-wikisvc.EMBEDDINGS_ENABLED — `Embeddings disabled`, код `0`
- exit codes: `1` — EXT-embeddings-server недоступен, размерность не равна CFG-wikisvc.EMBEDDINGS_DIM или косинус
  расходится с эталоном больше чем на 0.02 (ERR-embeddings_unavailable)
- notes: та же проверка, что в API-wikisvc.health (OBS-wikisvc.embeddings-selftest; провал там — `embeddings: failed`
  при `status: ok`); URL и ответ сервера в вывод не попадают, только поля выше

### CLI-wikisvc-cli.eval — Замер качества `ask` на eval-наборе
status: planned | owner: SVC-wikisvc-cli

- usage: `wikisvc eval --set PATH [--baseline PATH] [--out PATH]`

| аргумент | тип | обяз. | по умолчанию | что |
|---|---|---|---|---|
| `--set` | path | да | — | набор вопросов FMT-wikisvc-core.kb-eval: фикстуры — `tests/fixtures/kb-eval.yaml`, живая вики — `schema/eval/` её репозитория |
| `--baseline` | path? | нет | — | прежний отчёт FMT-wikisvc-cli.eval-report: фикстуры — `tests/fixtures/kb-eval-baseline.json`, живая вики — `schema/eval/` |
| `--out` | path? | нет | — | куда записать отчёт FMT-wikisvc-cli.eval-report |

- does: синхронизирует индекс под блокировкой записи, затем на каждый вопрос вызывает CLS-wikisvc-core.Ask от `cli`
  (ROLE-admin, SEC-clearance#restricted) с бюджетом CFG-wikisvc.ASK_BUDGET_DEFAULT и считает метрики ТЗ §10:
  Recall@8 по `seeds`, Recall@20 по `seeds ∪ expanded`, срезы single/multi и ru/en, долю `expansion_used` и долю
  запросов, где расширение принесло gold id вне `seeds`. Статистику выдачи не пишет (SEC-delivery-stats); пары
  для дедупликации из набора не использует (судья — SVC-wikiagent)
- output: таблица метрик в stdout; с `--out` — ещё JSON-отчёт
- exit codes: `1` — любая метрика `recall_at_8`/`recall_at_20` строго ниже `--baseline` (ТЗ §10: «не ниже
  предыдущего зафиксированного»; ADR-0025, NFR-eval-recall-baseline), набор не по формату (ERR-request_invalid) или
  провайдер эмбеддингов недоступен (ERR-embeddings_unavailable)
- notes: команда нужна для живой вики — A/B моделей и сравнения после книги (решение Q-kb-cli-eval). Расчёт метрик —
  CLS-wikisvc-core.evaluate, общий с `pytest -m eval` (PIPE-ci), CLI только печатает (MOD-wikisvc-cli.app). В CI
  векторы берутся из записанных `tests/fixtures/kb-eval-vectors.<model>.npz`, а не с сервера (RISK-kb-eval-gate-flaky);
  команда на живой вики ходит в EXT-embeddings-server. Базовую линию поднимает человек в PR. gold id, которых нет
  или не видно, — промах и список `unknown_gold`; OBS-eval-metrics

### FMT-wikisvc-cli.eval-report — Отчёт и базовая линия eval
status: planned | owner: SVC-wikisvc-cli

- file: JSON UTF-8; пишет CLI-wikisvc-cli.eval (`--out`), читают он же (`--baseline`) и `pytest -m eval`; базовая
  линия фикстур — `tests/fixtures/kb-eval-baseline.json` в репозитории кода, живой вики — `schema/eval/` в
  репозитории вики (решение Q-kb-cli-eval; OBS-eval-metrics, ТЗ §10)

| поле | тип | что |
|---|---|---|
| `set_sha256` | string | хеш файла набора |
| `version` | string | `version` из ответа `ask`: генерация индекса и модель эмбеддингов |
| `questions` | int32 | число вопросов |
| `recall_at_8` | map<string,float64> | Recall@8 по `seeds`; ключи `all`, `single`, `multi`, `ru`, `en` |
| `recall_at_20` | map<string,float64> | Recall@20 по `seeds ∪ expanded`; те же ключи |
| `expansion_used` | float64 | доля запросов с `expansion_used` |
| `expansion_helped` | float64 | доля запросов, где `expanded` принёс gold id вне `seeds` |
| `unknown_gold` | string[] | gold id, которых нет в индексе или не видно |

- compare: сравниваются все ключи `recall_at_8` и `recall_at_20`, которые есть в базовой линии; разные `version` и
  `set_sha256` допустимы — это и есть сравнение моделей или выросшего набора

### CLI-wikisvc-cli.repair-worktrees — Починить worktree после переноса
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc repair-worktrees` — при остановленных SVC-wikisvc и SVC-wikiagent, до `reindex`
- does: под блокировкой записи выполняет `git worktree repair` для каждого worktree предложения в
  `STATE_DIR/worktrees` (BKT-wikisvc-core.worktrees) и проверяет, что он связан с `WIKI_ROOT/.git`
- output: `Repaired N worktrees.`; errors: ERR-restore_incomplete (нет `.git`, не перенесён worktree,
  чужой репозиторий) → `1`; implements: FLOW-backup-restore

## Токены

Токены — ENT-token в TBL-wikisvc-core.state.tokens. Значение не принимается и не хранится: генерируется сервисом,
в базе только хеш (SEC-secrets, INV-secrets-never-stored).

### CLI-wikisvc-cli.token.create — Выпустить токен
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc token create --name NAME [--role writer] [--clearance internal] [--person ID] [--kind agent] [--expires-at ISO]`

| аргумент | тип | обяз. | по умолчанию | ограничения |
|---|---|---|---|---|
| `--name` | string | да | — | `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`, уникально |
| `--role` | enum(reader\|writer\|reviewer\|admin) | нет | `writer` | ROLE-* |
| `--clearance` | enum(public\|internal\|restricted) | нет | `internal` | SEC-clearance |
| `--person` | string? | нет | — | стабильный ID человека до 128 символов (ENT-person) |
| `--kind` | enum(agent\|human) | нет | `agent` | SEC-principal-kind |
| `--expires-at` | timestamp? | нет | — | ISO 8601 с часовым поясом, хранится в UTC |

- output: токен в открытом виде — единственный раз
- side effects: строка в TBL-wikisvc-core.state.tokens (хеш), аудит `token.create`
- exit codes: `2` — неверные роль, допуск или вид; `1` — ERR-token_name, ERR-token_person, ERR-request_invalid
  (`expires_at`), ERR-token_exists (409)

### CLI-wikisvc-cli.token.list — Список токенов
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc token list`
- output: JSON-массив `name`, `role`, `clearance`, `person`, `kind`, `expires_at`, `created_at`, `revoked_at`,
  отсортированный по имени; ни токенов, ни хешей не выводит

### CLI-wikisvc-cli.token.revoke — Отозвать токен
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc token revoke NAME`
- side effects: `Auth.revoke` — отметка `revoked_at` и аудит (неудачная попытка тоже пишется с `ok=0`)
- output: `Revoked`; exit codes: `1` — активного токена с таким именем нет (`E_NOT_FOUND: …` в stderr, ERR-not_found)

## Политики

### CLI-wikisvc-cli.policies.export — Записать блок политик в файл
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc policies export --profile NAME --out PATH` (оба обязательны)
- does: компилирует свод профиля (FLOW-policy-compile) и вставляет или заменяет блок FMT-wikisvc-core.policy-block
  в файле `PATH` (обычно `AGENTS.md`), остальной текст файла не трогает (INV-policy-block-only)
- output: `Exported version V to PATH`; errors: ERR-profile_unknown, ERR-policy_block (блок повреждён или
  их несколько) → `1`
- changed: 2026-10-20 v3 (planned): `[--knowledge] [--clearance public|internal|restricted]`. С `--knowledge` команда
  ещё вставляет или заменяет блок FMT-wikisvc-core.knowledge-block (`<!-- wikisvc:knowledge begin -->`) с брифом
  профиля (CLS-wikisvc-core.Brief, FLOW-knowledge-brief, бюджет ≤ CFG-wikisvc.BRIEF_BUDGET_MAX); без флага блок
  знаний не создаётся и не трогается — бриф по умолчанию запрашивают в начале сессии (ТЗ §7.1,
  INV-rules-pushed-knowledge-pulled). Бриф компилируется с допуском `--clearance` (по умолчанию `internal`,
  `restricted` — только явно), чтобы закрытые факты не попали в файл проекта (решение,
  Q-kb-cli-knowledge-export). Вывод += `knowledge version V2`; ошибки блока знаний — ERR-policy_block → `1`,
  неверный `--clearance` → `2`

### CLI-wikisvc-cli.policies.check — Проверить актуальность блока
status: implemented | owner: SVC-wikisvc-cli

- usage: `wikisvc policies check --profile NAME --file PATH` (оба обязательны)
- output: `Policy block is current`; exit codes: `1` — файла нет, блока нет, блоков несколько или версия
  не совпадает с текущей компиляцией (`Policy block is missing or outdated`)
- changed: 2026-10-20 v3 (planned): `--knowledge` (и `--clearance`, как у CLI-wikisvc-cli.policies.export) ещё сверяет
  версию блока FMT-wikisvc-core.knowledge-block с текущей компиляцией брифа; расхождение или нет блока — `1`
