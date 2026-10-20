# Языки, рантаймы, инструменты

## Языки

| id | язык и версия | где закреплена версия | компоненты | почему | status |
|---|---|---|---|---|---|
| LANG-python | Python 3.12 (в devShell 3.12.14) | `flake.nix` (`pkgs.python312`), `pyproject.toml` (`requires-python = ">=3.12"`, ruff `target-version = "py312"`) | SVC-wikisvc, LIB-wikisvc-core, SVC-wikisvc-mcp, SVC-wikisvc-cli, SVC-wikiagent | Весь серверный код (API, ядро, MCP, CLI, агент) — один Python-пакет (wheel) с двумя CLI; продолжает стек проекта (`rule-stack-continue-existing`, `rule-stack-python-or-go`). 3.12 закреплён явно, потому что дефолтный Python в nixpkgs новее (комментарий в `.github/workflows/ci.yml`) | implemented |
| LANG-go | Go 1.25 (директива `go 1.25.0`; в devShell go 1.26.7) | `ui/go.mod`, `updater/go.mod` | SVC-wiki-ui, SVC-updater | Go-сервер UI держит OIDC-вход и проксирует API (`ref/decisions.md`, «Анонимные агенты и человеческий вход через OIDC»); updater — демон одним статическим бинарником без сторонних зависимостей (`CGO_ENABLED=0`, `updater/package.nix`) | implemented |
| LANG-typescript | TypeScript 7.0.2 | `ui/package.json` (`devDependencies.typescript`), `ui/package-lock.json` | SVC-wiki-ui | React-интерфейс (React 19 + Vite); собирается в статические файлы, которые встраивает Go-сервер (`ui/package.nix`) | implemented |
| LANG-nix | Nix (flakes; Nix 2.34.9 в devShell) | `flake.nix`, `flake.lock` | все компоненты (сборка и выкладка) | Окружение и сборка декларативные (`rule-nix-flake-devshell`). Файлы: `flake.nix`, `ui/package.nix`, `updater/package.nix`, `deploy/package.nix`, `deploy/image.nix`, `deploy/vm-test.nix`, `deploy/vm-update-test.nix` | implemented |
| LANG-shell | Bash (`#!/usr/bin/env bash`, `set -euo pipefail`) | не закреплена: интерпретатор хоста; `deploy/*.sh` в `deploy/package.nix` проходят `shellcheck` | SVC-updater, хост-часть выкладки | Установка, запуск контейнеров, бэкап и админ-команды на хосте: `deploy/install.sh`, `deploy/run.sh`, `deploy/admin.sh`, `deploy/backup.sh`, `deploy/model.sh`; проверки релиза: `scripts/check-release-tag.sh`, `scripts/smoke-image.sh` | implemented |

Скрипты `scripts/*.py` (бенчмарки, `check_local_model.py`) — тот же LANG-python.

## Инструменты сборки и разработки

| id | инструмент | для чего | версия / где закреплена | status |
|---|---|---|---|---|
| TOOL-nix | Nix flakes | окружение (`devShells.default`), сборка пакетов `default`/`ui`/`updater`/`deployment`/`image`, `checks` с VM-тестами | вход `nixpkgs` = `github:NixOS/nixpkgs/nixos-unstable`, rev `7a0f122f5090cf4c2ade2a13a0e229d4e19ba71f` (`lastModified` 1790578696), `flake.lock`; `rule-nix-flake-lock-pinned` | implemented |
| TOOL-hatchling | hatchling | сборочный бэкенд wheel `wikisvc` (пакеты `src/wikisvc`, `src/wikiagent`) | `pyproject.toml` `[build-system]` без ограничения версии; версия из nixpkgs по `flake.lock` | implemented |
| TOOL-ruff | ruff 0.16.8 | линтер и форматтер Python (line-length 100); запускается в `preCheck` сборки и в `just lint` | `pyproject.toml` `[tool.ruff]`; версия из nixpkgs (`pkgs.ruff`) | implemented |
| TOOL-mypy | mypy 2.1.0 | типы Python, `strict = true` (`mypy src`) | `pyproject.toml` `[tool.mypy]`; версия из nixpkgs | implemented |
| TOOL-pytest | pytest 9.1.1, pytest-cov 7.1.0, hypothesis 6.156.1 | тесты Python (`tests/`), покрытие с ветвями и подпроцессами, порог `fail_under = 98` | `pyproject.toml` `[tool.pytest.ini_options]`, `[tool.coverage.*]`; версии из nixpkgs; в сборке `pytestFlags = --cov` (v3 planned: маркеры `eval` и `perf` регистрируются в `[tool.pytest.ini_options]`; `pytest -m eval` — гейт в джобе `quality` PIPE-ci, `pytest -m perf` — отдельный джоб без гейта (решение Q-kb-perf-ci-runner), сборка пакета исключает оба — ADR-0025; бенчмарк `scripts/benchmark_graph.py` расширяется до `scripts/benchmark_retrieval.py`, ТЗ §11.11) | implemented |
| TOOL-just | just 1.58.0 | короткие команды `dev`, `test`, `lint`, `init-dev`, `reindex` | `justfile`; пакет в devShell (v3 planned: + рецепт `just perf` — локальная проверка порогов NFR-ppr-latency и NFR-index-speedup, решение Q-kb-perf-ci-runner) | implemented |
| TOOL-npm | npm (Node.js v24.20.0 в devShell) | зависимости UI по `package-lock.json`, скрипты `build`, `typecheck`, `format:check`, `test` | `ui/package-lock.json`; Nix-сборка — `buildNpmPackage` с `npmDepsHash` (`ui/package.nix`); CI — `npm ci` (`rule-nix-node-modules-npm-ci`) | implemented |
| TOOL-vite | Vite 7.3.7 | dev-сервер и сборка SPA | `ui/package.json` (точная версия), `ui/vite.config.ts` | implemented |
| TOOL-tsc | tsc (пакет `typescript` 7.0.2) | проверка типов и сборка (`tsc -b`, `npm run typecheck`) | `ui/tsconfig.json`, `ui/package.json` | implemented |
| TOOL-playwright | Playwright 1.63.0 (`@playwright/test`) | браузерные сценарии UI (`ui/tests/*.spec.ts`), порт 18789; браузер из `CHROME_BIN`, если задан | `ui/playwright.config.ts`, `ui/package.json` | implemented |
| TOOL-prettier | Prettier 3.9.9 | форматирование UI; `format:check` — часть Nix-сборки UI (`preBuild`) и CI | `ui/package.json` | implemented |
| TOOL-go | Go toolchain 1.26.7 (`go vet`, `gofmt`, `go build`) | сборка `wiki-ui` и `llm-wiki-updater` через `buildGoModule`; в CI `go vet` и `gofmt -l` | `go` из nixpkgs; минимум — в `ui/go.mod`, `updater/go.mod` | implemented |
| TOOL-podman | podman | запуск релизного образа на хосте (`deploy/run.sh`, юниты systemd); инструмент хоста, проектом не ставится | не закреплена: версия хоста (`ref/deploy-linux.md`, раздел 1) | implemented |
| TOOL-github-actions | GitHub Actions | `ci.yml` (lint, полный набор, образ), `release.yml` (образ, attestation), `wk.yml` (проверка документации); действия закреплены по SHA коммита | `.github/workflows/*.yml` | implemented |

## Как поднять всё окружение

```
nix develop        # Python 3.12 со всеми зависимостями, git, sqlite, ruff, just, go, nodejs, wk
```

devShell (`flake.nix`, `devShells.default`) кладёт в PATH обёртки `wikisvc` и `wikiagent`
(`python -m wikisvc.cli`, `python -m wikiagent.cli`). `shellHook` только выставляет переменные и
создаёт локальные папки (`rule-nix-shellhook-no-install`); заданные снаружи значения не затираются:

| Переменная | Значение по умолчанию | Конфигурация |
|---|---|---|
| `PYTHONPATH` | `$PWD/src` в начале | — |
| `WIKI_ROOT` | `../wiki` рядом с репозиторием | CFG-wikisvc.WIKI_ROOT |
| `STATE_DIR` | `$PWD/.dev/state` (папка создаётся) | CFG-wikisvc.STATE_DIR |
| `INDEX_DIR` | `$PWD/.dev/index` (папка создаётся) | CFG-wikisvc.INDEX_DIR |
| `WIKIAGENT_STATE_DIR` | `$PWD/.dev/agent` (папка не создаётся) | CFG-wikiagent.WIKIAGENT_STATE_DIR |

Каждая команда проекта идёт через `nix develop -c <команда>` (`rule-nix-run-via-develop`). Проверки:
`nix develop -c just lint`, `nix develop -c pytest --cov --cov-report=term-missing`, `nix flake check`.
UI: `nix develop -c npm --prefix ui ci`, затем `npm --prefix ui run typecheck|format:check|test`.

## Правила

- Версии закреплены: Nix — `flake.lock`, npm — точные версии в `package.json` + `package-lock.json`, Go — `go.sum` (`rule-stack-versions-pinned`). Обновление входов flake — отдельная задача (`rule-nix-flake-lock-pinned`).
- Один инструмент на роль (`rule-stack-one-tool-per-job`): ruff — Python, Prettier — TypeScript, `gofmt` — Go, `shellcheck` — shell. Python-зависимости приходят из nixpkgs, `.venv` нет (`rule-nix-python-no-venv`).
- Расхождения со стеком по умолчанию (`rule-stack-python-defaults`, `rule-stack-react-defaults`, `rule-stack-postgres-default`) — в `docs/risks.md`.
