# updater: контракты

> HTTP API демона по unix-сокету, командная строка, структуры JSON и файлы.
> Общие свойства API: сокет `/run/llm-wiki-updater/api.sock` (владелец root, группа `llm-ui`, режим 0660), протокол HTTP/1.1, JSON, ответы с `Cache-Control: no-store`. В wiki-ui маршруты видны как `/updater-api/v1/…`.

## Синхронные вызовы

Авторизация у всех четырёх маршрутов одна (CLS-updater.admin): заголовок `Authorization: Bearer <токен>`, токен проверяет wikisvc через API-wikisvc.whoami; допускается только `kind=human` и `role=admin` (INV-human-decides, ROLE-admin). Сначала доступ к сокету, потом токен: человек без доступа к сокету до проверки токена не доходит.

Общие ошибки авторизации (тело — DTO-updater.Error):

| код | HTTP | когда |
|---|---|---|
| ERR-unauthorized | 401 | нет bearer-токена; wikisvc ответил 401 или 403 на токен |
| ERR-service_unavailable | 503 | wikisvc недоступен или ответил иначе (права проверить нельзя — доступ закрыт) |
| ERR-human_required | 403 | токен агента, не человека |
| ERR-forbidden | 403 | человек, но не администратор |

### API-updater.status — Состояние обновлений
status: implemented | owner: SVC-updater | kind: http

- endpoint: `GET /v1/status`
- auth: человек-администратор (см. выше)
- request: без тела
- response: 200 → DTO-updater.State (поле `current.digest` берётся из `image.env`, остальное — из `state.json`)
- errors: общие ошибки авторизации
- idempotency: естественная (только чтение)
- side effects: нет
- consumers: SVC-wiki-ui (страница обновлений), операторская диагностика
- notes: клиент опрашивает его во время обновления: операция живёт в поле `operation` со списком шагов

### API-updater.check — Проверить обновления сейчас
status: implemented | owner: SVC-updater | kind: http

- endpoint: `POST /v1/check`
- auth: человек-администратор
- request: тело не читается
- response: 200 → DTO-updater.State после проверки; сбой самой проверки (реестр, подпись) не ошибка HTTP, а поле `check_error` в состоянии
- errors: ERR-update_busy (409) — идёт проверка или обновление; общие ошибки авторизации
- idempotency: естественная: повтор даёт ту же картину, пока реестр не изменился
- side effects: вызывает EXT-ghcr (список тегов, метаданные тега) и проверку cosign; пишет `state.json` (`checked_at`, `available`, `check_error`, имя запущенного тега)
- limits: проверка живёт до 2m и не отменяется, если клиент ушёл; таймаут записи сервера 3m
- consumers: SVC-wiki-ui (кнопка «Проверить»)

### API-updater.channel — Выбрать канал обновлений
status: implemented | owner: SVC-updater | kind: http

- endpoint: `PUT /v1/channel`
- auth: человек-администратор
- request: DTO-updater.ChannelRequest
- response: 200 → DTO-updater.State после новой проверки на выбранном канале
- errors: ERR-bad_request (400) — тело не JSON, больше 4096 байт или с неизвестными полями; ERR-update_channel (400) — не `release` и не `beta`; ERR-update_busy (409) — идёт обновление, либо проверка; ERR-update_state (500) — не удалось сохранить; общие ошибки авторизации
- idempotency: естественная
- side effects: меняет `channel` в `state.json`; при смене канала сбрасывает `available`; затем делает то же, что API-updater.check
- notes: переключение канала никогда не предлагает понижение версии (CLS-updater.discover)

### API-updater.apply — Подтвердить и начать обновление
status: implemented | owner: SVC-updater | kind: http

- endpoint: `POST /v1/apply`
- auth: человек-администратор
- request: DTO-updater.ApplyRequest
- response: 202 → DTO-updater.State с новой операцией в состоянии `running`; обновление идёт в фоне (JOB-updater.apply)
- errors: ERR-bad_request (400); ERR-update_busy (409); ERR-update_stale (409) — digest не совпал с текущим предложением, надо проверить заново; ERR-update_state (500) — не удалось записать состояние; общие ошибки авторизации
- idempotency: нет; защита — одно обновление за раз и привязка к предложенному digest: после начала `available` остаётся прежним до конца, а повторный вызов получит `update_busy`, затем (после успеха) `update_stale`
- side effects: запускает JOB-updater.apply (останавливает службы wikisvc, wikiagent, wiki-ui, пишет архив, переписывает `image.env`), пишет `state.json`; в лог — кто начал (`identity` или `name` принципала)
- implements: FLOW-release-update (шаг подтверждения)
- consumers: SVC-wiki-ui (кнопка «Установить»)
- notes: клиент не называет образ, он лишь подтверждает предложенный digest

## Команды CLI

### CLI-updater.serve — Запустить демон
status: implemented | owner: SVC-updater

- usage: `llm-wiki-updater serve [флаги]` (флаги — `CFG-updater.*` в `runtime.md`)
- args: единственная подкоманда `serve`; любая другая или отсутствие — сообщение `Usage: llm-wiki-updater serve [flags]` в stderr
- input / output: принимает сокет от systemd (fd 3), пишет текстовый лог `slog` в stderr (journald)
- exit codes: `0` — остановлен по SIGTERM/SIGINT после завершения идущего обновления; `1` — ошибка запуска или работы (нет сокета systemd, повреждённый `state.json`, не удалось сохранить состояние); `2` — неверные подкоманда или флаги
- side effects: при старте перезаписывает `state.json` и переводит операцию `running` в `interrupted`

## Структуры данных

Сериализация всех структур — JSON, snake_case, время RFC 3339 UTC.

### DTO-updater.State — Состояние обновлений
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `channel` | enum(release\|beta) | да | по умолчанию `release` | канал, за которым следит демон |
| `current` | DTO-updater.Image | да | `digest` из `image.env`; пустой, если файла нет | что работает сейчас |
| `available` | DTO-updater.Image? | нет | null, если предлагать нечего | предложенное обновление |
| `checked_at` | timestamp? | нет | — | время последней проверки |
| `check_error` | string? | нет | — | причина неудачной проверки |
| `operation` | DTO-updater.Operation? | нет | последняя операция, одна | идущее или последнее обновление |

### DTO-updater.Image — Образ релиза
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `tag` | string | да | `vX.Y.Z` или `vX.Y.Z-beta.N`; у запущенного образа может быть пуст, пока тег не узнали | тег релиза |
| `digest` | string | да | `sha256:` и 64 hex | идентификатор образа |
| `revision` | string | да | может быть пуст | метка `org.opencontainers.image.revision` |

### DTO-updater.Operation — Одно обновление
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `id` | string | да | UTC `ГГГГММДДTччммссZ` | идентификатор; входит в имя архива |
| `from`, `to` | DTO-updater.Image | да | — | с чего и на что |
| `started_by` | string | да | `identity` или `name` администратора | кто подтвердил |
| `state` | enum(running\|succeeded\|rolled_back\|failed\|interrupted) | да | — | итог (`failed` — обновление не удалось, а откат не потребовался или тоже упал; `interrupted` — демон остановился посреди обновления) |
| `steps` | DTO-updater.Step[] | да | порядок выполнения | журнал шагов |
| `jobs_before`, `jobs_after` | DTO-updater.Job[] | да | может быть null | возобновляемые задачи wikiagent до и после |
| `archive` | string? | нет | путь | архив, из которого откатывали; нужен при `interrupted` |
| `error` | string? | нет | — | причина неудачи |
| `started_at` | timestamp | да | — | начало |
| `finished_at` | timestamp? | нет | — | конец |

### DTO-updater.Step — Шаг обновления
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `name` | enum(pull\|verify\|jobs-before\|stop\|archive\|switch\|migrate\|start\|health\|resume\|rollback\|jobs-after\|timer\|prune) | да | — | шаг; повтор того же имени заменяет запись |
| `status` | enum(running\|done\|failed) | да | — | исход |
| `at` | timestamp | да | — | время записи |
| `detail` | string? | нет | — | подробность или текст ошибки |

### DTO-updater.Job — Возобновляемая задача агента
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `id` | string | да | — | идентификатор задачи |
| `kind` | string | да | — | вид (ENT-job) |
| `status` | string | да | — | состояние |
| `updated_at` | string | да | как отдаёт `wikiagent jobs` | время обновления |

Источник — вывод `llm-wiki-run once maintenance wikiagent jobs` (JSON-массив). Старый образ может эту команду не знать — тогда шаг `jobs-before` пишет «not available» и не мешает обновлению.

### DTO-updater.ChannelRequest — Тело выбора канала
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `channel` | enum(release\|beta) | да | неизвестные поля запрещены, тело ≤ 4096 байт | новый канал |

### DTO-updater.ApplyRequest — Тело подтверждения
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `digest` | string | да | должен равняться `available.digest` | подтверждаемое обновление |

### DTO-updater.Principal — Что updater берёт из whoami
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `kind` | string | да | нужен `human` (SEC-principal-kind#human) | вид принципала |
| `role` | string | да | нужен `admin` | роль |
| `name` | string | нет | — | имя, идёт в журнал, если нет `identity` |
| `identity` | string | нет | — | внешняя идентичность человека |

### DTO-updater.Error — Конверт ошибки
status: implemented | owner: SVC-updater

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `error.code` | string | да | `E_UNAUTHORIZED`, `E_SERVICE_UNAVAILABLE`, `E_HUMAN_REQUIRED`, `E_FORBIDDEN`, `E_BAD_REQUEST`, `E_UPDATE_BUSY`, `E_UPDATE_STALE`, `E_UPDATE_CHANNEL`, `E_UPDATE_STATE` | код |
| `error.message` | string | да | русский текст | для человека |
| `error.hint` | string | да | всегда пустая строка | как у wikisvc |
| `error.details` | json | да | всегда null | как у wikisvc |

Тот же конверт, что у wikisvc, чтобы интерфейс читал обе службы одинаково. Неизвестный маршрут или метод отвечает стандартным текстом `net/http` (404, 405), не конвертом.

## Форматы файлов

### FMT-updater.state — Файл состояния
status: implemented | owner: SVC-updater

- kind: JSON
- encoding: UTF-8, отступ 2 пробела, один объект
- schema: DTO-updater.State (поле `current.digest` в файле не авторитетно, живой digest берётся из `image.env`)
- producer / consumer: пишет и читает только демон; путь `<state-dir>/state.json` (BKT-updater.state-dir); запись атомарна (временный файл, `fsync`, `rename`), режим 0600

### FMT-updater.image-env — Закрепление образа служб
status: implemented | owner: SVC-updater

- kind: env-файл из одной строки
- encoding: UTF-8, `LLM_WIKI_IMAGE=<репозиторий>@sha256:<64 hex>` и перевод строки
- schema: репозиторий должен совпадать с флагом `repository` (CFG-updater.repository), иначе строка не считается закреплением; при нескольких подходящих строках берётся последняя
- example: `LLM_WIKI_IMAGE=ghcr.io/badrabbit00/llm-wiki@sha256:…` (rule-deploy-by-digest)
- producer / consumer: файл `/etc/llm-wiki/image.env` ставит `deploy/install.sh`; updater на шаге `switch` перезаписывает его целиком (режим 0644) и перед этим сохраняет прежний как `image.env.previous`; читают updater и `llm-wiki-run` (разбирает, а не source'ит)
