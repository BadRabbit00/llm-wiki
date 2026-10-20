# Внешние зависимости всех компонентов

> Одна таблица на все языки. Только **прямые** зависимости, не транзитивные.
> Версия — ограничение из манифеста; для Python `*` значит «без ограничения», фактическая версия
> приходит из nixpkgs по `flake.lock` (rev `7a0f122f5090cf4c2ade2a13a0e229d4e19ba71f`) и указана
> как «окружение: X» — снято `importlib.metadata` в `nix develop`. npm — точные версии из
> `ui/package.json` (совпадают с `ui/package-lock.json`). Go — из `go.mod`.
> `updater/go.mod` сторонних зависимостей не имеет (только стандартная библиотека, `vendorHash = null`).

| id | пакет | версия | компоненты | зачем | почему не другое | status |
|---|---|---|---|---|---|---|
| DEP-py-fastapi | `fastapi` | `*`; окружение: 0.141.1 | SVC-wikisvc, SVC-wikiagent | HTTP API `/api/v1` и API агента | — | implemented |
| DEP-py-uvicorn | `uvicorn` | `*`; окружение: 0.51.0 | SVC-wikisvc-cli, SVC-wikiagent | ASGI-сервер для `serve` (импорт внутри команд `cli.py`) | — | implemented |
| DEP-py-pydantic | `pydantic` | `>=2`; окружение: 2.13.4 | LIB-wikisvc-core, SVC-wikisvc, SVC-wikiagent | модели и валидация DTO, конфигов, ответов модели | — | implemented |
| DEP-py-pydantic-settings | `pydantic-settings` | `*`; окружение: 2.12.0 | SVC-wikisvc | настройки из окружения (`wikisvc/config.py`) | — | implemented |
| DEP-py-ruamel.yaml | `ruamel.yaml` | `*`; окружение: 0.19.1 | LIB-wikisvc-core | разбор frontmatter и YAML-схемы вики (`domain/markdown.py`) | — | implemented |
| DEP-py-pystemmer | `pystemmer` | `*`; окружение: 3.1.0 | LIB-wikisvc-core | русская и английская стемминг-нормализация для поиска (`index/normalize.py`) | — | implemented |
| DEP-py-python-multipart | `python-multipart` | `*`; окружение: 0.0.32 | SVC-wikisvc | приём загрузки файлов `UploadFile` в `api/routers/raw.py` (требование FastAPI) | — | implemented |
| DEP-py-typer | `typer` | `*`; окружение: 0.25.1 | SVC-wikisvc-cli, SVC-wikiagent | CLI `wikisvc` и `wikiagent` | — | implemented |
| DEP-py-httpx | `httpx` | `*`; окружение: 0.28.1 | SVC-wikiagent | клиент к API вики и к OpenAI-совместимому серверу модели (EXT-llm-server) с таймаутами (v3 planned: + LIB-wikisvc-core — клиент CLS-wikisvc-core.Embeddings к EXT-embeddings-server, тот же пакет по `rule-stack-one-tool-per-job`; исходящий вызов из ядра — Q-kb-core-outbound-embeddings) | — | implemented |
| DEP-py-pypdf | `pypdf` | `*`; окружение: 6.18.1 | LIB-wikisvc-core | извлечение текста из PDF (`services/extract_worker.py`) | — | implemented |
| DEP-py-python-docx | `python-docx` | `*`; окружение: 1.2.0 | LIB-wikisvc-core | извлечение текста из DOCX (`services/extract_worker.py`) | — | implemented |
| DEP-py-mcp | `mcp` | `>=1.29,<2`; окружение: 1.29.0 | SVC-wikisvc-mcp | MCP-сервер `FastMCP` (`mcp_server.py`) | — | implemented |
| DEP-py-numpy | `numpy` | нет в окружении, версия — после добавления (в nixpkgs по `flake.lock`: 2.5.2, BSD-3-Clause — `nix eval`); согласие получено (Q-kb-numpy-scipy-consent) | LIB-wikisvc-core | массивы `id ↔ idx`, `type`, `status`, `sensitivity` снимка графа, reset-вектор и итерации PPR, косинус по векторам (ТЗ §5, §11.4; ADR-0019, ADR-0020) | выбор ТЗ §11.4; `networkx` не нужен (там же); порог скорости — NFR-ppr-latency | planned |
| DEP-py-scipy | `scipy` | нет в окружении, версия — после добавления (в nixpkgs по `flake.lock`: 1.18.1, BSD-3-Clause — `nix eval`); согласие получено (Q-kb-numpy-scipy-consent) | LIB-wikisvc-core | только `scipy.sparse.csr_matrix` для CLS-wikisvc-core.GraphSnapshot; PPR — степенной итерацией без `scipy.sparse.linalg` (ТЗ §11.4) | графовая БД отвергнута (ADR-0019); свой CSR на `numpy` не нужен — согласие на `scipy` получено | planned |
| DEP-py-onnxruntime | `onnxruntime` | нет в окружении, версия — после добавления (в nixpkgs по `flake.lock`: 1.27.1, MIT — `nix eval`); согласие получено (Q-kb-onnxruntime-consent, Q-kb-judge-runtime) | SVC-wikiagent (не ядро: ТЗ §11.11) | ONNX-модели судей в MOD-wikiagent.judge: MDL-nli-judge, MDL-nli-judge-light, MDL-nli-modernbert (A/B), MDL-grounding-judge | LLM-судья на всех парах дороже (NFR-agent-model-budget) — LLM только второй ступенью каскада (развёрнутая Gemma на RES-llama-server, ADR-0022); reranker — не здесь, а `llama-server --reranking` (RES-reranker-server); `torch` в runtime не берём (ТЗ §11.11) | planned |
| DEP-py-tokenizers | `tokenizers` | нет в окружении, версия — после добавления (в nixpkgs по `flake.lock`: 0.23.2, Apache-2.0 — `nix eval`); согласие получено (Q-kb-onnxruntime-consent) | SVC-wikiagent | токенизация входа cross-encoder для DEP-py-onnxruntime; без него ONNX-модель не получает токены | нужен только вместе с DEP-py-onnxruntime | planned |
| DEP-py-pytest | `pytest` | `*` (extra `dev`); окружение: 9.1.1 | все Python-компоненты | тесты | — | implemented |
| DEP-py-pytest-cov | `pytest-cov` | `*` (extra `dev`); окружение: 7.1.0 | все Python-компоненты | покрытие, порог 98% | — | implemented |
| DEP-py-hypothesis | `hypothesis` | `*` (extra `dev`); окружение: 6.156.1 | все Python-компоненты | property-тесты | — | implemented |
| DEP-py-mypy | `mypy` | `*` (extra `dev`); окружение: 2.1.0 | все Python-компоненты | `mypy --strict src` | — | implemented |
| DEP-py-ruff | `ruff` | `*` (extra `dev`); окружение: 0.16.8 (из `pkgs.ruff`) | все Python-компоненты | линтер и форматтер | — | implemented |
| DEP-npm-react | `react` | `19.3.0` | SVC-wiki-ui | интерфейс | — | implemented |
| DEP-npm-react-dom | `react-dom` | `19.3.0` | SVC-wiki-ui | отрисовка в DOM | — | implemented |
| DEP-npm-react-router-dom | `react-router-dom` | `7.18.4` | SVC-wiki-ui | маршрутизация SPA | — | implemented |
| DEP-npm-tanstack-react-query | `@tanstack/react-query` | `5.104.1` | SVC-wiki-ui | кэш и запросы к API (`ui/src/api.ts`) | — | implemented |
| DEP-npm-react-markdown | `react-markdown` | `10.1.0` | SVC-wiki-ui | отрисовка Markdown страниц (`components/common.tsx`) | — | implemented |
| DEP-npm-remark-gfm | `remark-gfm` | `4.0.1` | SVC-wiki-ui | таблицы и GFM-синтаксис в Markdown | — | implemented |
| DEP-npm-d3-force | `d3-force` | `3.0.0` | SVC-wiki-ui | раскладка графа связей (`pages/Graph.tsx`) | — | implemented |
| DEP-npm-lucide-react | `lucide-react` | `1.52.0` | SVC-wiki-ui | иконки | — | implemented |
| DEP-npm-fontsource-manrope | `@fontsource/manrope` | `5.3.0` | SVC-wiki-ui | шрифт Manrope (кириллица и латиница) со своего домена, без внешнего CDN (`rule-design-typeface`) | — | implemented |
| DEP-npm-fontsource-ibm-plex-mono | `@fontsource/ibm-plex-mono` | `5.3.0` | SVC-wiki-ui | моноширинный шрифт | — | implemented |
| DEP-npm-vite | `vite` | `7.3.7` (dev) | SVC-wiki-ui | сборка и dev-сервер | — | implemented |
| DEP-npm-vitejs-plugin-react | `@vitejs/plugin-react` | `5.2.0` (dev) | SVC-wiki-ui | плагин React для Vite | — | implemented |
| DEP-npm-typescript | `typescript` | `7.0.2` (dev) | SVC-wiki-ui | проверка типов | — | implemented |
| DEP-npm-playwright-test | `@playwright/test` | `1.63.0` (dev) | SVC-wiki-ui | браузерные сценарии вместо Vitest (`ui/tests/*.spec.ts`) | — | implemented |
| DEP-npm-prettier | `prettier` | `3.9.9` (dev) | SVC-wiki-ui | форматирование | — | implemented |
| DEP-npm-types-d3-force | `@types/d3-force` | `3.0.10` (dev) | SVC-wiki-ui | типы `d3-force` | — | implemented |
| DEP-npm-types-node | `@types/node` | `26.6.4` (dev) | SVC-wiki-ui | типы Node для конфигов Vite/Playwright | — | implemented |
| DEP-npm-types-react | `@types/react` | `19.3.0` (dev) | SVC-wiki-ui | типы React | — | implemented |
| DEP-npm-types-react-dom | `@types/react-dom` | `19.3.0` (dev) | SVC-wiki-ui | типы React DOM | — | implemented |
| DEP-go-go-oidc | `github.com/coreos/go-oidc/v3` | `v3.21.0` | SVC-wiki-ui | проверка ID-токена и JWKS при входе OIDC (`ui/oidc.go`) | `ref/decisions.md` («Анонимные агенты и человеческий вход через OIDC»): `nix search nixpkgs go-oidc` перед добавлением; проверка JWT делегирована библиотеке | implemented |
| DEP-go-go-jose | `github.com/go-jose/go-jose/v4` | `v4.1.4` | SVC-wiki-ui | JOSE-криптография для проверки подписи | та же запись в `ref/decisions.md`: криптография делегируется go-jose | implemented |
| DEP-go-oauth2 | `golang.org/x/oauth2` | `v0.36.0` | SVC-wiki-ui | PKCE и обмен кода авторизации | та же запись в `ref/decisions.md` | implemented |
| DEP-nix-nixpkgs | `nixpkgs` (flake input) | `nixos-unstable`; rev `7a0f122f5090cf4c2ade2a13a0e229d4e19ba71f`, `lastModified` 1790578696 (`flake.lock`) | все компоненты | источник Python, Go, Node и системных пакетов; обновляется отдельной задачей | — | implemented |
| DEP-nix-wk | `wk` (flake input `github:BadRabbit00/wk`) | rev `7c9250cd1c25be70cdbf0b6c2926b535918fd54d` | окружение разработки | только инструмент devShell и хуков агента (`wk hook …`, `wk docs check`); в продукт не входит | — | implemented |
| DEP-nix-git | `git` | из nixpkgs; окружение: 2.55.0 | LIB-wikisvc-core, окружение | хранилище страниц и worktree предложений; в Nix-пакете `wikisvc` добавлен в PATH обёртки (`makeWrapperArgs`) | git как хранилище — основа продукта (`SPEC.md`) | implemented |
| DEP-nix-sqlite | `sqlite` | из nixpkgs; окружение: 3.53.3 | окружение | клиент `sqlite3` для отладки баз `state.db`, `wiki.db`, `agent.db` | — | implemented |
| DEP-nix-nodejs | `nodejs` | из nixpkgs; окружение: v24.20.0 | SVC-wiki-ui (сборка) | рантайм npm, Vite, Playwright | — | implemented |
| DEP-nix-go | `go` | из nixpkgs; окружение: 1.26.7 | SVC-wiki-ui, SVC-updater (сборка) | компилятор Go | — | implemented |
| DEP-nix-just | `just` | из nixpkgs; окружение: 1.58.0 | окружение | запуск `justfile` | — | implemented |
| DEP-nix-ruff | `ruff` | из nixpkgs; окружение: 0.16.8 | окружение, сборка `wikisvc` | линтер в devShell и в `preCheck`; тот же пакет, что DEP-py-ruff | — | implemented |

## Правила

- Новая зависимость появляется здесь со статусом `draft` **до** того, как её добавят в манифест (`rule-stack-new-tech-consent`); по правилам проекта новая зависимость ищется в nixpkgs и обосновывается в PR.
- Две библиотеки для одной задачи в одном компоненте — только с объяснением в «почему не другое» (`rule-stack-one-tool-per-job`). Сейчас дублей нет: один HTTP-клиент на Python (`httpx`), один менеджер серверного состояния в UI (TanStack Query).
- Python-зависимости собираются из nixpkgs (`withPackages` в devShell, `dependencies` в пакете); `pip install` и `.venv` не используются. `fastapi`, `mcp` и `rich-toolkit` собраны с переопределением `inline-snapshot` (отключён тест `tests/test_docs.py`, `flake.nix`).
- Лицензии: политика лицензий зависимостей в репозитории не задана — см. Q-stack-license-policy; файла `LICENSE` в корне нет.
- v3 (planned): на четыре новые Python-зависимости выше согласие пользователя получено (`rule-stack-new-tech-consent`; Q-kb-numpy-scipy-consent, Q-kb-onnxruntime-consent); строки остаются `draft` до перевода человеком в `planned`. Python 3.12-пакеты не лежат в cache.nixos.org (комментарий в `.github/workflows/ci.yml`), `scipy` и `onnxruntime` собираются из исходников — RISK-kb-heavy-python-builds (`rule-nix-heavy-build-limits`). Модели эмбеддингов, reranker и LLM-судья — не Python-зависимости: их обслуживают процессы `llama-server` (RES-embeddings-server, RES-reranker-server; ADR-0018), список — `stack/models.md`.
