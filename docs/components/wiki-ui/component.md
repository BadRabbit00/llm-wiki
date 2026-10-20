# wiki-ui

> Карточка компонента. Агент читает этот файл первым, когда задача касается веб-интерфейса.

### SVC-wiki-ui — Веб-интерфейс вики (Go-сервер с OIDC и прокси + React SPA)
status: implemented | kind: frontend | lang: LANG-typescript

- purpose: рабочее место человека (ACT-human): чтение и поиск вики, редактор предложений, ревью,
  чат с агентом, источники, задачи, граф, политики и обновление релиза — за входом через EXT-authentik.
- lang: SPA — LANG-typescript; сервер (вход, прокси, раздача статики) — LANG-go.
- not responsible for: бизнес-правил нет — права, саморевью, переходы статусов проверяют
  SVC-wikisvc и SVC-wikiagent (`rule-arch-frontend-no-business-rules`), кнопки только отражают роль;
  токен сессии JavaScript не видит — он живёт в HttpOnly-cookie, Go подставляет его в `Authorization`;
  не открывает рабочую папку вики, SQLite и конфигурацию модели; не сопоставляет группы IdP с ролями
  (это делает SVC-wikisvc при выпуске сессии).
- path: `ui/` (Go: `ui/*.go`, SPA: `ui/src/`)
- manifest: `ui/package.json` + `ui/go.mod`, lock: `ui/package-lock.json` + `ui/go.sum`
- build: TOOL-nix; `nix build .#ui` — `ui/package.nix`: `buildNpmPackage` собирает `dist/`
  (с `npm run format:check` перед сборкой, хеш `npmDepsHash`), затем `buildGoModule` (`vendorHash`,
  `CGO_ENABLED=0`) встраивает `dist/` в бинарник через `go:embed`; бинарник — `wiki-ui`.
  Обновили lock — обновите соответствующий хеш.
- run locally: `nix run .#ui` (порт 8789, адрес CFG-wiki-ui.WIKI_UI_BIND); без OIDC-настроек
  и файлов секретов не стартует.
- dev: `cd ui && npm run dev` — Vite на `127.0.0.1:5173`, `/api`, `/agent-api`, `/auth` проксируются
  в Go на 8789 (`ui/vite.config.ts`); redirect URI `http://127.0.0.1:5173/auth/callback` прописывается в IdP.
- test: в `nix develop` из `ui/`: `CGO_ENABLED=0 go test ./...` (локальный OIDC-провайдер: code/PKCE/state/
  nonce, подписи, ротация JWKS, отказ IdP, logout, маршрутизация, заголовки, SSE) и `npm test`
  (TOOL-playwright; поднимает настоящие wikisvc/wikiagent на 18787/18788 и Go-прокси на 18789,
  `pretest` собирает UI); `npm run typecheck`, `npm run format:check`.
- entrypoints: `ui/main.go` — HTTP-сервер; `ui/src/main.tsx` — корень SPA.
- framework: DEP-npm-react, DEP-npm-react-dom, DEP-npm-react-router-dom, DEP-npm-tanstack-react-query;
  Go: DEP-go-go-oidc, DEP-go-oauth2, DEP-go-go-jose
- deps: DEP-npm-react-markdown, DEP-npm-remark-gfm, DEP-npm-d3-force, DEP-npm-lucide-react,
  DEP-npm-fontsource-manrope, DEP-npm-fontsource-ibm-plex-mono (полный список — `stack/dependencies.md`)
- changed: 2026-10-20 v3 (planned): экраны слоя знаний (ТЗ v3 §12 п. 16, этап 4) — страницы ENT-fact,
  ENT-topic, ENT-tech, ENT-question; граф с весами и провенансом рёбер; ревью предложения списком claims
  с маршрутизацией по STATE-fact-review-class; открытые вопросы домена. Новых npm-зависимостей,
  путей прокси и настроек нет (детали — раздел «Слой знаний» ниже).

## Что компонент даёт другим

- API: API-wiki-ui.* — `/auth/login`, `/auth/callback`, `/auth/logout`, `/healthz`, прокси
  `/api/v1/*`, `/agent-api/*`, `/updater-api/*` и раздача SPA (детали — `contracts.md`).
- cli: нет — бинарник флагов не принимает, всё через окружение (`runtime.md`).

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| API-wikisvc.sessions.create | выпуск человеческой сессии в callback служебным токеном CFG-wiki-ui.WIKI_UI_SESSION_TOKEN_FILE | вход не завершается: 503 «Не удалось создать сеанс вики» |
| API-wikisvc.sessions.revoke | отзыв текущей сессии при выходе | cookie удалён, ответ 503 «отзыв не подтверждён» |
| API-wikisvc.* | всё остальное (страницы, предложения, поиск, граф, политики, источники) через прокси `/api/v1/*` | 502 ERR-service_unavailable, SPA показывает ошибку |
| API-wikisvc.knowledge.fact, API-wikisvc.knowledge.topic, API-wikisvc.knowledge.tech, API-wikisvc.knowledge.questions, API-wikisvc.knowledge.domains | (v3 planned) виды фактов, хабов, tech и вопросов через прокси `/api/v1/*` | ошибка в блоке вида, остальные экраны работают |
| API-wikiagent.* | чат (SSE), джобы, сверка документации через `/agent-api/*` | 502, разделы чата и задач показывают недоступность агента |
| API-updater.* | статус, канал, проверка и установка релиза (только ROLE-admin) через `/updater-api/*` по Unix-сокету | 502, блок обновлений показывает ошибку |
| EXT-authentik | OIDC discovery, JWKS, обмен кода, end-session | новые входы — 503; уже выданные сессии работают (проверяет только wikisvc), выход — без перехода в IdP, если discovery не загружен |

## Данные

- owns: KV-wiki-ui.oidc-flows, KV-wiki-ui.oidc-provider — в памяти процесса (детали — `data.md`).
- store: нет постоянного хранилища; сессии — токены SVC-wikisvc (ENT-session) в cookie браузера.
- reads foreign data: только через API-wikisvc.*, API-wikiagent.*, API-updater.*.

## Устройство

- modules: MOD-wiki-ui.server, MOD-wiki-ui.oidc, MOD-wiki-ui.app, MOD-wiki-ui.api, MOD-wiki-ui.pages,
  MOD-wiki-ui.components; v3 (planned): MOD-wiki-ui.knowledge-api, MOD-wiki-ui.knowledge-views (детали — `code.md`)
- jobs: JOB-wiki-ui.oidc-refresh (детали — `runtime.md`)
- config: CFG-wiki-ui.* (детали — `runtime.md`)

## Развёртывание

- runs on: RES-host, ENV-prod; образ RES-container-image (один образ с wikisvc и wikiagent).
- unit: `deploy/systemd/wiki-ui.service` запускает контейнер через `llm-wiki-run daemon wiki-ui`;
  окружение — `deploy/linux/ui.env`.
- scaling: одна реплика — незавершённые входы (KV-wiki-ui.oidc-flows) живут в памяти процесса.
- health: OBS-wiki-ui.health (`GET /healthz`)

## Слой знаний (v3, draft)

- Данные: только через API-wikisvc.knowledge.*, API-wikisvc.graph.*, API-wikisvc.proposals.* по
  API-wiki-ui.proxy.wikisvc; форма — DTO-wikisvc-core.FactView, DTO-wikisvc-core.EdgeView.
- Цепочка: вид MOD-wiki-ui.knowledge-views → хук CLS-wiki-ui.useKnowledge → MOD-wiki-ui.knowledge-api →
  CLS-wiki-ui.request (`rule-arch-frontend-api-layer`); старые экраны не переделываются (RISK-wiki-ui-fetch-in-page).
- UI ничего не вычисляет: порядок фактов хаба (INV-canonical-order), класс ревью и `reasons`, `confidence`,
  `status: outdated` (STATE-fact), `needs_double_confirm` и итоговый вес обхода приходят с сервера
  (`rule-arch-frontend-no-business-rules`).
- Решения принимает человек (INV-human-decides, INV-no-self-review): блок `auto` — одним действием
  (Q-kb-auto-accept-human-decides, вариант 1), снятые факты и решения по парам — в том же вызове accept
  (Q-kb-ui-review-decisions). Решения по графу, классу, L0/L1 и двойному подтверждению — Q-kb-ui-graph-edge-fields,
  Q-kb-ui-review-class-field, Q-kb-ui-proposal-fact-view, Q-kb-ui-double-confirm-facts.
- Без эмбеддингов — выделенное предупреждение CLS-wiki-ui.SearchDegradedBanner (Q-kb-embeddings-degraded).
- Риски объёма: RISK-kb-ui-graph-export-size, RISK-kb-ui-review-list-all.

## Политики

- `rule-auth-browser-cookies`, `rule-auth-external-idp`, `rule-auth-csrf`, `rule-auth-logout-revocation`,
  `rule-arch-frontend-api-layer`, `rule-arch-frontend-no-business-rules`, `rule-auth-frontend-refresh`,
  `rule-secrets-required-at-start`, `rule-test-tools-frontend`, `rule-stack-react-defaults`.
- v3 (planned): `rule-stack-new-tech-consent`, `rule-arch-file-naming`, `rule-arch-strict-typing`,
  `rule-design-contrast`, `rule-design-responsive`, `rule-design-reduced-motion`, `rule-design-tokens-system`.
