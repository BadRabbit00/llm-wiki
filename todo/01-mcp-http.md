# 01 — MCP по HTTP

## Цель

MCP доступен удалённо по HTTP с авторизацией из заголовка запроса. stdio остаётся рабочим.
Поверхность инструментов делится на профили: агент для кода получает подмножество, а не все 23.

## Почему не как сейчас

`src/wikisvc/cli.py:270-281` на каждую stdio-сессию берёт эксклюзивный `write_lock` и делает полный
`reindex` + `proposals.expire()`. Три клиента = драка за лок и `E_LOCK_TIMEOUT`.
`src/wikisvc/mcp_server.py:37` читает токен из `os.environ["WIKI_TOKEN"]` — на процесс, не на запрос.

## Факты окружения

- `mcp == 1.29.0`. У `FastMCP` есть `streamable_http_app()`, `run_streamable_http_async()`.
- Настройки `FastMCP`: `stateless_http`, `json_response`, `streamable_http_path`, `mount_path`.
- `src/wikisvc/tool_contracts.py` — единый источник контрактов. Профили инструментов определяются **там**.

## Изменения

### 1. Принципал из контекста запроса, а не из окружения

`src/wikisvc/mcp_server.py`:

- добавить модульный `ContextVar[str | None]` для сырого токена (`_token`);
- `actor(role)` берёт токен так: сначала `ContextVar`, при `None` — `os.environ.get("WIKI_TOKEN", "")` (stdio);
- поведение при пустом/неверном токене не меняется: `WikiError("E_UNAUTHORIZED", …, status=401)` из `Auth.authenticate`.

### 2. ASGI-обёртка авторизации

Новый модуль `src/wikisvc/mcp_http.py`:

- чистая ASGI-middleware поверх приложения MCP;
- читает `Authorization: Bearer <token>`; отсутствует или не `bearer` — отдаёт 401 телом `WikiError("E_UNAUTHORIZED").response()`;
- аутентифицирует через `runtime.auth.authenticate` в `run_in_threadpool`, кладёт **сырой токен** в `ContextVar`,
  сбрасывает его в `finally`;
- аутентификация до чтения тела — тот же порядок, что в `main.py:BodyLimit`;
- **размер тела не проверять.** `BodyLimit` применяет лимит 1 МиБ ко всем путям (авторизацию —
  только для `/api/v1/`), значит `/mcp` уже накрыт. Не дублировать.

Реализацией авторизации не дублировать `Auth`: только вызов.

### 2a. Порядок регистрации

`BodyLimit` **не менять**. Обёртку регистрировать в `create_app` **после**
`app.add_middleware(BodyLimit, config=config)`: в Starlette последний добавленный middleware —
внешний, поэтому авторизация выполнится до чтения тела.

Обёртка обрабатывает только `settings.mcp_http_path`; все прочие пути передаёт дальше без изменений.

### 3. Монтирование в основное приложение

`src/wikisvc/main.py`:

- MCP живёт в процессе `wikisvc serve`, использует **тот же** `Runtime`. Отдельного reindex нет;
- `FastMCP(..., stateless_http=True, json_response=False)`;
- путь: `/mcp` (значение из настройки, см. ниже);
- **обязательно**: приложение MCP имеет собственный lifespan (менеджер сессий). `app.mount()` его не запускает.
  В существующем `lifespan` (`main.py:122`) обернуть `yield` в
  `async with mcp_app.router.lifespan_context(mcp_app):`. Без этого инструменты падают в рантайме —
  закрыть тестом, а не ручной проверкой;
- `/mcp` **не** добавляется в исключения `BodyLimit`: путь не начинается с `/api/v1/`, значит в него не попадает;
  авторизацию делает middleware из п. 2.

### 4. Профили поверхности

`src/wikisvc/tool_contracts.py` — добавить объявление профилей:

```
TOOL_PROFILES: dict[str, tuple[str, ...]] = {
    "coding": ("get_instructions", "get_policies", "get_rule", "rules_related", "graph_impact",
               "search", "get_page", "get_context",
               "create_proposal", "put_page", "patch_page", "validate_proposal", "submit_proposal"),
    "full": (),   # пустой кортеж = все зарегистрированные инструменты
}
```

- `create_server(runtime, profile="full")` регистрирует только инструменты профиля;
- неизвестный профиль — `ValueError` при старте, не в рантайме;
- `get_instructions` присутствует во всех профилях: без него агент не знает правил;
- в профиль `coding` **не входят** `list_pending_sources`, `read_source_text`, `get_outline`,
  `read_source_pages`, `get_page_template`, `neighbors`, `lint`;
- тест: для каждого профиля список имён инструментов совпадает с объявленным точно.

### 5. Конфигурация

`src/wikisvc/config.py`, новые поля:

| поле | env | по умолчанию | смысл |
|---|---|---|---|
| `mcp_http_enabled` | `MCP_HTTP_ENABLED` | `False` | монтировать ли `/mcp` |
| `mcp_http_path` | `MCP_HTTP_PATH` | `/mcp` | путь монтирования, должен начинаться с `/` |
| `mcp_profile` | `MCP_PROFILE` | `coding` | профиль поверхности для HTTP |

Выключено по умолчанию. При `mcp_http_enabled=False` поведение `wikisvc serve` не меняется ни на байт.

`deploy/almalinux/service.env` — добавить три строки закомментированными, со значениями по умолчанию.

### 6. CLI

- `wikisvc mcp` (stdio) остаётся как есть, включая reindex и `write_lock`;
- добавить `--profile` (по умолчанию `full`) — одно значение, передаётся в `create_server`.

## Тесты

Новый файл `tests/test_mcp_http.py`, через `TestClient` поднятого `create_app`:

1. запрос без `Authorization` → 401, тело содержит `E_UNAUTHORIZED`.
   Проверка верна при выключенном анонимном доступе — это значение по умолчанию.
   Задача 09 добавляет анонимный принципал и **свой** тест на тот же путь; этот тест
   тогда фиксируется явным `ANONYMOUS_ACCESS=0` в настройках фикстуры, а не удаляется;
2. запрос с отозванным токеном → 401;
3. запрос с валидным токеном: `tools/list` возвращает ровно состав профиля;
4. вызов `get_policies` возвращает те же данные, что HTTP `/api/v1/policies/compile` с теми же параметрами;
5. `reader`-токен на `create_proposal` → ошибка `E_FORBIDDEN` в теле `ToolError`;
6. два последовательных запроса разными токенами видят разных принципалов (ContextVar не протекает);
7. изоляция допуска: `internal`-токен не видит `restricted`-страницу через MCP (как в `tests/test_boundaries.py`);
8. при `MCP_HTTP_ENABLED=False` путь `/mcp` отдаёт 404.

Существующий `tests/test_mcp.py` (stdio) должен проходить без изменений.

## Готово, когда

- `nix develop -c just lint`, `pytest --cov`, `nix flake check` — зелёные;
- `tests/test_mcp.py` не изменён;
- при `MCP_HTTP_ENABLED=False` диффа в поведении нет;
- `README.md`: в разделе про MCP — абзац про HTTP-транспорт, профили и три переменные.

## Не делать

- не выносить MCP в отдельный процесс и отдельный systemd-юнит;
- не писать шлюз на Go: контракты живут в одном месте;
- не добавлять SSE-транспорт (`sse_app`) — он устаревший;
- не трогать `Auth`, `BodyLimit`, `deps.Authorize`;
- не вводить собственный формат ошибок: только `WikiError.response()`.
