# wikisvc-mcp

> Карточка компонента. Агент читает этот файл первым, когда задача касается MCP-доступа к вики.

### SVC-wikisvc-mcp — MCP-адаптер вики
status: implemented | kind: http-service | lang: LANG-python

- purpose: даёт кодинг-агентам инструменты вики по протоколу MCP — локально через stdio и по сети через Streamable HTTP внутри процесса SVC-wikisvc.
- not responsible for: бизнес-логику, хранение и индекс (всё в LIB-wikisvc-core); выпуск токенов (CLI-wikisvc-cli.token.create); принятие предложений — человек делает это в UI/HTTP (INV-human-decides).
- path: `src/wikisvc/mcp_server.py`, `src/wikisvc/mcp_http.py`, `src/wikisvc/tool_contracts.py`
- manifest: `pyproject.toml`, lock: `flake.lock` (Python-пакеты берутся из nixpkgs)
- build: TOOL-nix; собирается вместе с пакетом `wikisvc`
- run locally: `nix develop -c wikisvc mcp --profile coding` (stdio, без порта); HTTP — `MCP_HTTP_ENABLED=1 nix develop -c wikisvc serve`, путь `/mcp` на порту SVC-wikisvc
- test: `nix develop -c pytest tests/test_mcp.py tests/test_mcp_http.py`
- entrypoints:
  - `wikisvc mcp` (CLI-wikisvc-cli.mcp) → `create_server(...).run(transport="stdio")` в `src/wikisvc/mcp_server.py`;
  - mount в FastAPI-приложение (`src/wikisvc/main.py`) при CFG-wikisvc.MCP_HTTP_ENABLED: путь CFG-wikisvc.MCP_HTTP_PATH, профиль CFG-wikisvc.MCP_PROFILE, перед ним middleware `MCPHTTPAuth` из `src/wikisvc/mcp_http.py`.
- framework: DEP-py-mcp (`FastMCP`, stateless Streamable HTTP, ответы SSE)
- deps: DEP-py-mcp, DEP-py-pydantic; Starlette — транзитивно через DEP-py-fastapi
- changed: 2026-10-20 v3 (planned): слой знаний — 10 инструментов (API-wikisvc-mcp.get_brief, API-wikisvc-mcp.ask и др.),
  профиль `knowledge`, `budget_tokens` и потолок ответа у всех читающих, компактный markdown у всех 31 инструмента
  — ломающее изменение принято владельцем (ТЗ §7, §11.10; Q-kb-mcp-response-format; перечень для клиентов —
  `MCP-CONTRACT-CHANGES-v3.md`); новых зависимостей нет

## Что компонент даёт другим

- API: API-wikisvc-mcp.* — 21 инструмент; профиль `coding` — 14 из них, `full` — все (детали — `contracts.md`);
  v3 (planned): 31 инструмент, `coding` — 19, `knowledge` — 14
- contracts: CLS-wikisvc-mcp.CONTRACTS, CLS-wikisvc-mcp.ALLOWLISTS, CLS-wikisvc-mcp.definitions — единые описания инструментов для MCP и для модели SVC-wikiagent

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| LIB-wikisvc-core | все инструменты зовут сервисы ядра (`Runtime`) напрямую, в том же процессе, не через HTTP | компонент не стартует |
| TBL-wikisvc-core.state.tokens | проверка Bearer-токена на каждый вызов инструмента (через `Auth.authenticate`) | инструмент отвечает ERR-unauthorized |
| CFG-wikisvc.ANONYMOUS_ACCESS | анонимный доступ без токена (SEC-anonymous) | — |
| CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME | токену, выпускающему сессии UI, MCP запрещён | — |
| CLS-wikisvc-core.Brief, CLS-wikisvc-core.Ask, CLS-wikisvc-core.Knowledge (v3 planned) | инструменты слоя знаний | компонент не стартует |
| EXT-embeddings-server через CLS-wikisvc-core.Embeddings (v3 planned) | векторные семена `ask` | `ask` отвечает по BM25 с пометкой (Q-kb-embeddings-degraded) |
| CFG-wikisvc.TOOL_RESPONSE_CAP (v3 planned) | потолок любого ответа | — |

## Данные

- owns: ничего (детали — `data.md`)
- reads foreign data: только через сервисы LIB-wikisvc-core

## Устройство

- modules: MOD-wikisvc-mcp.server, MOD-wikisvc-mcp.http, MOD-wikisvc-mcp.contracts, v3 (planned) MOD-wikisvc-mcp.render
  (детали — `code.md`)
- jobs: нет; config: CFG-wikisvc-mcp.WIKI_TOKEN, ссылки на CFG-wikisvc.MCP_HTTP_ENABLED, CFG-wikisvc.MCP_HTTP_PATH, CFG-wikisvc.MCP_PROFILE (детали — `runtime.md`)

## Безопасность

- Каждый вызов инструмента заново аутентифицирует принципала и проверяет роль: чтение — ROLE-reader,
  изменения предложений — ROLE-writer; допуск SEC-clearance ограничивает видимые страницы и сырьё.
- HTTP: аутентификация в `MCPHTTPAuth` выполняется до лимита тела запроса (INV-auth-before-body).
- Инструменты не принимают и не отклоняют предложения: только `submit_proposal` на ревью человеку (INV-human-decides).
- Текст источников помечается `trust: untrusted_external` (INV-untrusted-external).
- Ошибки сервисов отдаются как MCP `ToolError` с JSON `{"error": {code, message, hint, details}}`.
- v3 (planned): обход графа в `ask`, `expand`, `why` режется допуском до построения матрицы (SEC-graph-clearance-mask);
  статистика выдачи хранит id и идентичность вызывающего без текста запросов (SEC-delivery-stats); `propose_fact`/`propose_link` пишут только в
  предложение, не дают агенту поставить `confidence: sourced` и поднять вес связи выше базового
  (INV-human-decides, Q-kb-mcp-propose-provenance). Выдача знаний (SEC-untrusted-external): метки происхождения
  (`[draft]`, `origin: book`, `trust: untrusted_external`) — до текста факта, вставляемые поля экранированы
  (CLS-wikisvc-mcp.render_compact), описания для модели называют факты справочными данными, не инструкциями;
  все инструменты отдают только страницы из main, а каждая принята человеком (Q-kb-auto-accept-human-decides).

## Развёртывание

- runs on: RES-host, ENV-prod — внутри процесса SVC-wikisvc (HTTP) или отдельным процессом у клиента (stdio)
- scaling: один экземпляр (INV-single-node); HTTP-сервер stateless, сессий MCP не хранит
- health: OBS-wikisvc.health (отдельного health у MCP нет)
