# ADR-0009 — Go для сервера интерфейса и демона обновлений
status: accepted | date: 2026-10-07

## Контекст

Интерфейсу нужен сервер: раздача SPA, OIDC (ADR-0006) и прокси к wikisvc и wikiagent с одного origin.
Позже (2026-10-13) понадобился демон обновлений на хосте, вне образа (ADR-0015). Основной код — LANG-python.

## Решение

SVC-wiki-ui — бинарник на LANG-go: `net/http`, встроенные файлы SPA, прокси `/api/v1/`, `/agent-api/`,
`/updater-api/`, OIDC через DEP-go-go-oidc и DEP-go-oauth2. SVC-updater — бинарник на LANG-go только
на стандартной библиотеке.

## Почему

- один статический бинарник с ассетами: один origin, CORS не нужен;
- OIDC остаётся вне Python-ядра, а зависимости фиксируются `go.mod`, `go.sum` и `vendorHash` в Nix;
- updater работает от root вне образа: без сторонних модулей меньше поверхность атаки.

## Что рассматривали и отвергли

В источниках (`ref/decisions.md`, коммит `1270d9e`) альтернативы не записаны.

## Последствия

- в проекте два языка бэкенда; CI проверяет `go vet` и `gofmt` для `ui/` и `updater/` (PIPE-ci);
- затрагивает: SVC-wiki-ui, SVC-updater, LANG-go, DEP-go-go-oidc, DEP-go-oauth2, DEP-go-go-jose.
