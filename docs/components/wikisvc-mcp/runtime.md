# wikisvc-mcp: фоновые задачи и настройки

## Фоновые задачи

Своих фоновых задач нет. При старте stdio-сервера CLI-wikisvc-cli.mcp под блокировкой записи один раз
переиндексирует контент и просрочивает старые предложения; HTTP-вариант живёт в жизненном цикле SVC-wikisvc.

## Настройки

Настройки HTTP-транспорта читает `Settings` компонента SVC-wikisvc (`src/wikisvc/config.py`):
CFG-wikisvc.MCP_HTTP_ENABLED (включает mount и middleware), CFG-wikisvc.MCP_HTTP_PATH (путь mount),
CFG-wikisvc.MCP_PROFILE (профиль инструментов HTTP), а также CFG-wikisvc.ANONYMOUS_ACCESS,
CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME, CFG-wikisvc.CONTEXT_BUDGET_DEFAULT, CFG-wikisvc.LOG_LEVEL, CFG-wikisvc.BIND_HOST.
Профиль stdio задаётся флагом `--profile` команды CLI-wikisvc-cli.mcp (по умолчанию `full`).

changed: 2026-10-20 v3 (planned): своих настроек не добавляется. Инструменты дополнительно читают
CFG-wikisvc.TOOL_RESPONSE_CAP (потолок ответа), CFG-wikisvc.ASK_BUDGET_DEFAULT (бюджет `ask`),
CFG-wikisvc.BRIEF_BUDGET_MAX (предел `get_brief`); оценка токенов — через CLS-wikisvc-core.estimate_tokens по
CFG-wikisvc.CHARS_PER_TOKEN_LATIN и CFG-wikisvc.CHARS_PER_TOKEN_CYRILLIC. CFG-wikisvc.MCP_PROFILE и `--profile`
принимают ещё `knowledge`.

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-wikisvc-mcp.WIKI_TOKEN | SVC-wikisvc-mcp | env | string | нет | да для stdio без CFG-wikisvc.ANONYMOUS_ACCESS; для HTTP не читается | да | Bearer-токен ENT-token, от имени которого stdio-сервер и CLI-wikisvc-cli.migrate-rules вызывают сервисы; читается на каждом вызове инструмента | implemented |

Значение токена в документацию не пишется: выдаёт CLI-wikisvc-cli.token.create, хранит клиент в своём окружении (SEC-secrets).
Без токена сервер стартует, а каждый вызов инструмента отвечает ERR-unauthorized.
