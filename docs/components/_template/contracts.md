# <Имя компонента>: контракты

> Всё, через что компонент общается с внешним миром: API, события, CLI, DTO, форматы файлов.
> Контракт описывает **что** и **с какими гарантиями**, а не как реализовано.

## Синхронные вызовы

### API-<компонент>.<действие> — <Что делает>
status: <…> | owner: SVC-<…> | kind: <http | grpc | graphql | ws | webhook>

- endpoint: `<POST /v1/orders>` (или `<package.Service/Method>` для gRPC)
- auth: <публичный / ROLE-<…> с PERM-<…> / подпись вебхука SEC-<…>>
- request: DTO-<…>
- response: <201> → DTO-<…>
- errors: ERR-<…> (<409>), ERR-<…> (<422>)
- idempotency: <нет / заголовок `Idempotency-Key`, окно 24h / естественная по <поле>>
- side effects: <пишет TBL-<…>, публикует EVT-<…>, вызывает EXT-<…>>
- implements: FLOW-<…> (шаг <N>), INV-<…>
- limits: <10 rps на пользователя, тело ≤ 1 MB, таймаут 5s> (NFR-<…>)
- consumers: <кто вызывает: SVC-<…>, фронтенд, EXT-<…>>
- notes: <почему так, неочевидное поведение>

## Асинхронные сообщения

### EVT-<сущность>.<что случилось> — <Описание>
status: <…> | owner: SVC-<…> | kind: <event | command>

- channel: RES-<брокер>, <subject / topic / queue> `<orders.created.v1>`
- payload: DTO-<…>
- when: <в какой момент публикуется; до или после коммита в БД>
- delivery: <at-least-once / at-most-once>; dedup key: `<поле>`
- ordering: <гарантирован по <ключу> / не гарантирован>
- consumers: SVC-<…> (что делает с событием), SVC-<…>
- retention / dlq: <сколько хранится, куда уходят необработанные>

## Команды CLI

### CLI-<компонент>.<команда> — <Что делает>
status: <…> | owner: SVC-<…>

- usage: `<tool orders import --file <path> [--dry-run]>`
- args: <таблица или список аргументов с типами и значениями по умолчанию>
- input / output: FMT-<…>
- exit codes: `0` — ок, `1` — <…>, `2` — <…>
- side effects: <…>

## Структуры данных

### DTO-<имя> — <Что описывает>
status: <…> | owner: SVC-<…>

| поле | тип | обяз. | ограничения | смысл |
|---|---|---|---|---|
| `<id>` | uuid | да | — | <…> |
| `<items>` | DTO-<…>[] | да | 1..50 | <…> |
| `<status>` | enum(STATE-<…>) | да | — | <…> |
| `<comment>` | string? | нет | ≤ 500 символов | <…> |

- serialization: <JSON, camelCase / snake_case; protobuf `<файл.proto>`>

## Форматы файлов

### FMT-<имя> — <Что за файл>
status: <…> | owner: SVC-<…>

- kind: <CSV / JSON / YAML / XLSX / бинарный>
- encoding: <UTF-8, разделитель `;`, первая строка — заголовок>
- schema: <таблица полей как у DTO или ссылка на DTO-<…>>
- example: <3–5 строк реального примера>
- producer / consumer: <кто пишет, кто читает>
