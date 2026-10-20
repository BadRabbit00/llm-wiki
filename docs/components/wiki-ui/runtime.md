# wiki-ui: фоновые задачи и настройки

## Фоновые задачи

### JOB-wiki-ui.oidc-refresh — Обновление ключей IdP и чистка незавершённых входов
status: implemented | owner: SVC-wiki-ui

- trigger: тикер каждые 5m в горутине процесса, с момента старта до остановки.
- does: удаляет просроченные записи KV-wiki-ui.oidc-flows; если discovery уже загружен — заново
  читает JWKS EXT-authentik в KV-wiki-ui.oidc-provider.
- touches: KV-wiki-ui.oidc-flows, KV-wiki-ui.oidc-provider, вызывает EXT-authentik (`jwks_uri`).
- idempotent: да.
- concurrency: один экземпляр на процесс.
- timeout / retries: 10s на запрос; ошибка игнорируется до следующего тика, прежние ключи остаются —
  уже выданные сессии от IdP не зависят.

## Настройки

Все переменные читаются один раз при старте. Ошибка в OIDC-настройках — процесс не стартует
(`rule-secrets-required-at-start`). Значения секретов — только в файлах вне git и образа
(`/etc/llm-wiki/…` на RES-host, SEC-secrets); образец — `deploy/linux/ui.env`.

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-wiki-ui.WIKI_UI_BIND | SVC-wiki-ui | env | string | `127.0.0.1:8789` | нет | нет | адрес и порт HTTP-сервера | implemented |
| CFG-wiki-ui.WIKI_UI_WIKISVC_URL | SVC-wiki-ui | env | string | `http://127.0.0.1:8787` | нет | нет | origin SVC-wikisvc для прокси и выпуска сессий; только `http(s)://host[:port]` без пути, query и учётных данных | implemented |
| CFG-wiki-ui.WIKI_UI_AGENT_URL | SVC-wiki-ui | env | string | `http://127.0.0.1:8788` | нет | нет | origin SVC-wikiagent для `/agent-api/*`; те же ограничения | implemented |
| CFG-wiki-ui.WIKI_UI_UPDATER_SOCKET | SVC-wiki-ui | env | string | `/run/llm-wiki-updater/api.sock` | нет | нет | Unix-сокет SVC-updater для `/updater-api/*` | implemented |
| CFG-wiki-ui.WIKI_UI_OIDC_ISSUER | SVC-wiki-ui | env | string | нет | да | нет | issuer EXT-authentik; только `https`, `http` — лишь на loopback при CFG-wiki-ui.WIKI_UI_OIDC_INSECURE_HTTP; все endpoints discovery обязаны быть на его origin | implemented |
| CFG-wiki-ui.WIKI_UI_OIDC_CLIENT_ID | SVC-wiki-ui | env | string | нет | да | нет | `client_id` OIDC и ожидаемый `aud` ID-токена | implemented |
| CFG-wiki-ui.WIKI_UI_OIDC_SECRET_FILE | SVC-wiki-ui | file | string | нет | да | да | путь к файлу с client secret (≤ 8 KB, не пустой) | implemented |
| CFG-wiki-ui.WIKI_UI_OIDC_REDIRECT_URL | SVC-wiki-ui | env | string | нет | да | нет | браузерный адрес `…/auth/callback` (`https`, `http` — только loopback); его origin — эталон проверки `Origin` | implemented |
| CFG-wiki-ui.WIKI_UI_SESSION_TOKEN_FILE | SVC-wiki-ui | file | string | нет | да | да | путь к файлу служебного токена SVC-wikisvc, которым callback вызывает API-wikisvc.sessions.create | implemented |
| CFG-wiki-ui.WIKI_UI_COOKIE_SECURE | SVC-wiki-ui | env | bool (`1`/иное) | `1` | нет | нет | флаг `Secure` у cookies; `0` допустим только вместе с CFG-wiki-ui.WIKI_UI_OIDC_INSECURE_HTTP и loopback redirect | implemented |
| CFG-wiki-ui.WIKI_UI_OIDC_INSECURE_HTTP | SVC-wiki-ui | env | bool (`1`/иное) | выключено | нет | нет | разрешает `http`-issuer на loopback для локального тестового IdP | implemented |

- Частный CA IdP задаётся стандартной переменной Go `SSL_CERT_FILE` (читает библиотека TLS, не код
  компонента); в образе она указывает на системный набор корневых сертификатов.
- Переменных сборки Vite (`import.meta.env.*`, `VITE_*`) SPA не использует.
