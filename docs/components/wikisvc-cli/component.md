# wikisvc-cli

> Карточка компонента. Агент читает этот файл первым, когда задача касается командной строки `wikisvc`.

### SVC-wikisvc-cli — CLI администратора вики
status: implemented | kind: cli | lang: LANG-python

- purpose: даёт оператору хоста команды обслуживания вики: создать репозиторий, запустить API и MCP, выпустить и отозвать токены, переиндексировать, проверить и мигрировать контент, выгрузить блок политик.
- not responsible for: работу через сеть — команды вызывают сервисы LIB-wikisvc-core в своём процессе, с прямым доступом к каталогам данных; ревью предложений (это UI и HTTP API SVC-wikisvc).
- path: `src/wikisvc/cli.py`
- manifest: `pyproject.toml` (скрипт `wikisvc = "wikisvc.cli:app"`), lock: `flake.lock`
- build: TOOL-nix; собирается вместе с пакетом `wikisvc`
- run locally: `nix develop -c wikisvc --help`
- test: `nix develop -c pytest tests/test_cli.py tests/test_cov_cli.py`
- entrypoints: `src/wikisvc/cli.py` — объект `app` (`typer.Typer`) с подгруппами `token`, `policies`, `schema`, `scopes`
- framework: DEP-py-typer
- deps: DEP-py-typer, DEP-py-uvicorn (команда `serve`)
- changed: 2026-10-20 v3 (planned): подгруппы `domains`, `embeddings`; новые CLI-wikisvc-cli.domains.add,
  CLI-wikisvc-cli.embeddings.selftest, CLI-wikisvc-cli.eval; изменены `init`, `schema upgrade`, `reindex`
  (`--embeddings`), `lint`, `mcp`, `policies export/check` (`--knowledge`); новых зависимостей нет

## Что компонент даёт другим

- cli: CLI-wikisvc-cli.* — 15 команд (детали — `contracts.md`); v3 (planned): 18 команд и отчёт FMT-wikisvc-cli.eval-report

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| LIB-wikisvc-core | все команды, кроме `version`, вызывают сервисы ядра (`Runtime`, `Auth`, `StateDB`, миграции) | команда падает с ошибкой |
| SVC-wikisvc | `serve` запускает его фабрику `wikisvc.main:create_app` | — |
| SVC-wikisvc-mcp | `mcp` запускает stdio-сервер | — |
| CFG-wikisvc.WIKI_ROOT, CFG-wikisvc.STATE_DIR, CFG-wikisvc.INDEX_DIR | каталоги данных; нужны всем командам, кроме `version` и `init` | ошибка валидации `Settings` при старте |
| CFG-wikisvc-mcp.WIKI_TOKEN | токен для `migrate-rules` без `--dry-run` и для `mcp` | ERR-unauthorized |
| EXT-embeddings-server через CLS-wikisvc-core.Embeddings (v3 planned) | векторы в `reindex`, `lint`, `mcp`; `embeddings selftest`, `eval` | `reindex --embeddings`, `selftest`, `eval` → `1`; остальные — по тексту с предупреждением (Q-kb-embeddings-degraded) |

## Данные

- owns: ничего (детали — `data.md`); пишет через сервисы ядра в TBL-wikisvc-core.state.tokens,
  BKT-wikisvc-core.wiki-repo, BKT-wikisvc-core.worktrees и индекс RES-index-db
- исключение: `token list` и `token revoke` читают TBL-wikisvc-core.state.tokens SQL-запросом прямо из CLI

## Устройство

- modules: MOD-wikisvc-cli.app (детали — `code.md`)
- jobs: нет; config: свои настройки не определяет (детали — `runtime.md`)

## Безопасность

- Оператор с доступом к каталогам данных считается администратором: `lint`, `policies *`, `schema upgrade`
  работают от встроенного принципала `cli` (ROLE-admin, SEC-clearance#restricted) без токена.
- Токен выводится в открытом виде один раз при создании; в TBL-wikisvc-core.state.tokens хранится только хеш SHA-256
  (ENT-token, SEC-secrets). Секреты аргументами не принимаются: токен для `migrate-rules` и `mcp` берётся
  из окружения (rule-secrets-not-in-argv).
- Изменения контента (`scopes add`, `schema upgrade`) идут коммитом в main под блокировкой записи и пишут аудит.
- v3 (planned): `domains add` — так же, коммит в main и аудит `domain.add`. Ключа к серверу эмбеддингов нет: сервер
  локальный на loopback (SEC-embeddings-boundary; решение Q-kb-embeddings-api-key).
  `policies export --knowledge` по умолчанию собирает бриф
  с допуском `internal`, а не `restricted` (Q-kb-cli-knowledge-export); `eval` работает с допуском `restricted`, но
  печатает только id и метрики.

## Развёртывание

- runs on: RES-host (внутри контейнера RES-container-image или из devShell), ENV-dev, ENV-prod
- scaling: команды, меняющие данные, берут файловую блокировку записи в `STATE_DIR` (INV-single-node)
