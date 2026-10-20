# wiki-ui: контракты

> HTTP-поверхность Go-сервера `wiki-ui`. Своих DTO нет: тела прокси — контракты API-wikisvc.*,
> API-wikiagent.*, API-updater.*; типы SPA в `ui/src/types.ts` — зеркала DTO-wikisvc.*.
> v3 (planned): экраны слоя знаний ходят к API-wikisvc.knowledge.* через API-wiki-ui.proxy.wikisvc
> (`/api/v1/*`); новых путей, лимитов тела и заголовков не нужно — контракты ниже не меняются.

## Общее для всех ответов

- Заголовки: `Cache-Control: no-store` (кроме статики, см. API-wiki-ui.static); `Referrer-Policy:
  no-referrer` на `/auth/*`, `same-origin` на остальных путях; там же `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY` и CSP `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'`.
- Cookies (SEC-session-cookie): `wiki_session` — токен сессии SVC-wikisvc, `Path=/`, срок = `expires_at`
  сессии; `wiki_oidc_flow` — `state` незавершённого входа, `Path=/auth`, 10m. Обе `HttpOnly`,
  `SameSite=Lax`, `Secure` по CFG-wiki-ui.WIKI_UI_COOKIE_SECURE (`rule-auth-browser-cookies`).
- Ошибки JSON (прокси и раздача) — `{"error": {"code", "message"}}`; ошибки страниц входа — `text/plain`
  с русским текстом.

## Синхронные вызовы

### API-wiki-ui.auth.login — Начать вход через OIDC
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `GET /auth/login`; тот же обработчик вызывается для любого `GET` без cookie `wiki_session`.
- auth: публичный.
- response: `302` на authorization endpoint IdP (code flow, PKCE S256, `state` и `nonce` по 32 случайных
  байта, scopes `openid profile email groups`) + cookie `wiki_oidc_flow`.
- errors: `405` не GET; `503` нет discovery IdP («нет связи с Authentik»); `503` больше 10 000 незавершённых входов.
- side effects: свежий discovery EXT-authentik (все endpoints обязаны быть на origin issuer), запись в KV-wiki-ui.oidc-flows.
- implements: FLOW-oidc-login (шаг 1), `rule-auth-external-idp`.

### API-wiki-ui.auth.callback — Завершить вход и выпустить сессию вики
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `GET /auth/callback?state=&code=`
- auth: публичный; `state` из query сравнивается за постоянное время с cookie `wiki_oidc_flow` и
  одноразово снимается из KV-wiki-ui.oidc-flows.
- response: `302` на `/` + cookie `wiki_session`; cookie `wiki_oidc_flow` удаляется.
- errors: `400` — неверный/истёкший `state`, `error` от IdP, нет `code`, обмен кода не удался, нет
  `id_token`, подпись/`iss`/`aud`/`exp`/`iat` (не более 60s в будущем)/`nonce`/`nbf` неверны, пустой `sub`;
  `503` — нет discovery или SVC-wikisvc не выпустил сессию (не 200, пустой токен, истёкший `expires_at`).
- side effects: обмен кода у EXT-authentik; `POST /api/v1/sessions` (API-wikisvc.sessions.create) с
  `Authorization: Bearer <служебный токен из CFG-wiki-ui.WIKI_UI_SESSION_TOKEN_FILE>` и телом
  `{subject, username, groups}` (`groups` — всегда массив); роль по группам назначает SVC-wikisvc.
- implements: FLOW-oidc-login (шаги 2–4), `rule-auth-external-idp`.
- notes: подписи проверяются ключами JWKS с `use` sig/пусто и `alg` RS256/пусто; неизвестный ключ —
  одно обновление JWKS на запрос (ротация ключей IdP без рестарта).

### API-wiki-ui.auth.logout — Выход с отзывом сессии
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `POST /auth/logout` (синоним `POST /logout`); SPA отправляет обычную HTML-форму.
- auth: cookie `wiki_session` (может отсутствовать); `Origin` обязан совпадать с origin
  CFG-wiki-ui.WIKI_UI_OIDC_REDIRECT_URL.
- response: `303` на `end_session_endpoint` IdP с `client_id` и `post_logout_redirect_uri=<origin>/`;
  если discovery ещё не загружен или endpoint не объявлен — `200 text/plain` «Вы вышли из вики».
- errors: `405` не POST; `403` чужой `Origin`; `503` — cookie удалён, но SVC-wikisvc не подтвердил отзыв
  (сеть или ответ не 204/401).
- side effects: cookie `wiki_session` удаляется всегда; `DELETE /api/v1/sessions/current`
  (API-wikisvc.sessions.revoke) с токеном из cookie; IdP при выходе не запрашивается
  (`rule-auth-logout-revocation`).

### API-wiki-ui.health — Проверка живости
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `GET /healthz` — без cookie и без обращения к upstream.
- response: `200` `{"status":"ok","service":"wiki-ui"}`.
- consumers: OBS-wiki-ui.health, проверка здоровья после обновления (SVC-updater).

### API-wiki-ui.proxy.wikisvc — Прокси к HTTP API вики
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `/api/v1/*` → CFG-wiki-ui.WIKI_UI_WIKISVC_URL тем же путём.
- auth: cookie `wiki_session`; Go заменяет входящий `Authorization` на `Bearer <cookie>`. Без cookie:
  `GET` — как API-wiki-ui.auth.login, остальные — `303` на `/auth/login`. `/api/v1/sessions` через UI
  закрыт (`403`): ответ с токеном получает только callback.
- request / response: контракты API-wikisvc.*.
- errors: `403` — изменяющий метод с `Origin` не равным origin UI (защита от CSRF вместо токена, см.
  `rule-auth-csrf`); `405` ERR-method — метод вне GET/HEAD/POST/PUT/PATCH/DELETE; `413` ERR-body_too_large —
  тело больше 1 MB (для `POST /api/v1/raw` — 1 GiB + 64 KiB, точный лимит у SVC-wikisvc);
  `502` ERR-service_unavailable — upstream недоступен; `401` от upstream → `302` на `/auth/login` с
  удалением `wiki_session`.
- side effects: из запроса удаляются `Cookie`, `Origin`, `Referer`; из ответа — `Set-Cookie`;
  добавляются `Cache-Control: no-store` и `X-Accel-Buffering: no`; SSE отдаётся без буферизации;
  ожидание заголовков ответа — до 5m.
- implements: SEC-session-cookie, `rule-auth-browser-cookies`.

### API-wiki-ui.proxy.wikiagent — Прокси к API агента
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `/agent-api/*` → CFG-wiki-ui.WIKI_UI_AGENT_URL, префикс `/agent-api` отрезается.
- auth, errors, side effects: как API-wiki-ui.proxy.wikisvc (лимит тела 1 MB, SSE чата без буферизации).
- request / response: контракты API-wikiagent.* (сессии чата, сообщения, джобы, `docs-audit`).

### API-wiki-ui.proxy.updater — Прокси к демону обновлений
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `/updater-api/*` → Unix-сокет CFG-wiki-ui.WIKI_UI_UPDATER_SOCKET, префикс отрезается.
- auth: как API-wiki-ui.proxy.wikisvc; роль ROLE-admin проверяет сам SVC-updater через `/whoami` вики.
- request / response: контракты API-updater.* (`/v1/status`, `/v1/channel`, `/v1/check`, `/v1/apply`).
- limits: ожидание заголовков ответа — до 3m (проверка подписей образа).
- notes: демон работает от root и слушает только сокет, открыть который может лишь пользователь wiki-ui.

### API-wiki-ui.static — Раздача SPA
status: implemented | owner: SVC-wiki-ui | kind: http

- endpoint: `GET|HEAD /*` вне путей выше; файлы из встроенного `dist/`.
- auth: `/assets/*` — без cookie; остальное — cookie `wiki_session`, иначе API-wiki-ui.auth.login.
- response: существующий файл; `/assets/*` с `Cache-Control: public, max-age=31536000, immutable`;
  путь без расширения — `index.html` с `no-cache` (маршрутизацию делает SPA); путь с расширением,
  скрытый файл или `api/`, `agent-api/`, `updater-api/` без маршрута — `404`.
- errors: `405` не GET/HEAD; `503` ERR-ui_build — бинарник собран без `dist/index.html`.
