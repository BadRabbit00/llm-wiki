# ADR-0006 — Вход людей через Authentik OIDC, cookie-сессии и анонимный режим для агентов
status: accepted | date: 2026-10-09

## Контекст

Людям нужен вход в веб-интерфейс через корпоративный IdP, агентам — простой доступ к API и MCP
в доверенной сети. Ядро не должно делать сетевых запросов (ADR-0003).

## Решение

OIDC (authorization code + PKCE) с EXT-authentik делает только Go-сервер SVC-wiki-ui: проверяет подпись,
issuer, audience, время и nonce, затем выпускающим токеном вызывает `POST /api/v1/sessions` и кладёт
ограниченный по времени токен wikisvc в HttpOnly cookie (SEC-session-cookie). wikisvc OIDC не знает.
`ANONYMOUS_ACCESS=1` (CFG-wikisvc.ANONYMOUS_ACCESS) пускает запросы без токена как `kind=agent` с потолком
writer/internal (SEC-anonymous, INV-anonymous-ceiling); в поставке для Linux он включён.

## Почему

- проверку JWT делает библиотека (DEP-go-go-oidc, go-jose), самописной криптографии нет;
- уже выданные сессии работают при недоступном IdP; аварийный доступ — human-токен через API;
- анонимный режим приемлем для доверенной сети без материалов restricted (`ref/decisions.md`).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| OIDC внутри wikisvc | ядро получило бы сетевые запросы и криптографию |
| токен в JavaScript | доступен XSS; cookie HttpOnly — нет |

## Последствия

- при появлении материалов restricted анонимный режим пересматривается;
- для анонимного API нужны сетевые ограничения и лимит по IP на прокси (вне репозитория);
- затрагивает: SVC-wiki-ui, SVC-wikisvc, EXT-authentik, DEP-go-go-oidc, DEP-go-oauth2.
