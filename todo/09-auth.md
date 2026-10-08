# 09 — Аутентификация: аноним для агентов, Authentik для людей

## Модель

```
Агенты, MCP, API с ноутов  →  без credential. Один анонимный принципал с жёстким потолком.
                              Граница доступа — сеть, а не токен.

Люди в UI                  →  Authentik → короткоживущая сессия wikisvc.
                              kind=human, person=<sub>. Решения и аудит достоверны.

wikiagent ↔ wikisvc        →  один служебный токен в /etc/llm-wiki/agent.env, не покидает сервер.
wiki-ui   →  wikisvc       →  один служебный токен, право ровно на выпуск сессий.
```

Персональных токенов, которые надо кому-то выдавать и у кого-то отзывать, не остаётся.

## Что это обеспечивает и чего стоит

Сохраняется полностью: решение принимает человек; граница `restricted`; достоверность «кто принял».

Теряется осознанно: отзыв по одному агенту (рубильник один — сеть); лимит запросов на агента
(переносится на прокси по IP); атрибуция «чей агент предложил» — предложение в этой системе
не имеет полномочий, поэтому потеря допустима.

---

# Часть A. Анонимный принципал в `wikisvc`

## Конфигурация

`src/wikisvc/config.py`:

| поле | env | по умолчанию |
|---|---|---|
| `anonymous_access` | `ANONYMOUS_ACCESS` | `False` |
| `anonymous_name` | `ANONYMOUS_NAME` | `anonymous` |
| `anonymous_role` | `ANONYMOUS_ROLE` | `writer` |
| `anonymous_clearance` | `ANONYMOUS_CLEARANCE` | `internal` |
| `session_issuer_token_name` | `SESSION_ISSUER_TOKEN_NAME` | `""` |
| `session_ttl_hours` | `SESSION_TTL_HOURS` | `12` |

Валидатор в `Settings` (падение при старте, не в рантайме):

- `anonymous_role` ∈ {`reader`, `writer`}. `reviewer` и `admin` запрещены;
- `anonymous_clearance` ∈ {`public`, `internal`}. `restricted` запрещён;
- `anonymous_name` соответствует `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}` — значение уходит в git-автора
  (`storage/gitrepo.py:22`), непроверенная строка туда попасть не должна.

Потолок задаётся кодом. Конфигурация может его только понизить.

## Принципал

`src/wikisvc/services/auth.py`, метод `Auth.anonymous() -> Principal`:

```
Principal(name=<anonymous_name>, person=None, kind="agent",
          role=<anonymous_role>, clearance=<anonymous_clearance>)
```

`kind="agent"` — жёстко, не из конфигурации. Это единственное место, где держится
«решение принимает человек» (`require_human`, `auth.py:26`). Анонимный принципал
не получает `accept`, `promote`, `deprecate`, `revert`, `dismiss` ни при каких настройках.

`person=None` → `identity == name == "anonymous"`.

## Точки подключения

### `main.py:BodyLimit.__call__`

Текущее поведение для `/api/v1/` (кроме `/health`): нет `Bearer` → 401.

Новое:

- заголовок `Authorization` **отсутствует** и `anonymous_access` включён → `actor = runtime.auth.anonymous()`;
- заголовок **присутствует** → аутентификация как сейчас, строго. Неверный, отозванный или
  истёкший токен → **401**. Молчаливого понижения до анонима нет;
- `anonymous_access` выключен → поведение не меняется ни на байт.

### `api/deps.py:Authorize.__call__`

Сейчас `credentials is None` → 401 до чтения `request.state.actor`. Переставить порядок:

```
actor = getattr(request.state, "actor", None)
if actor is None:
    if credentials is None: raise WikiError("E_UNAUTHORIZED", …, status=401)
    actor = services.auth.authenticate(credentials.credentials)
request.state.actor = actor
require_role(actor, self.role)
```

Поведение при работающем middleware не меняется; 401 сохраняется для прямого использования без него.

### Обёртка MCP (задача 01)

Та же логика: нет заголовка и `anonymous_access` включён → анонимный принципал; заголовок есть → строго.

## Следствия, принимаемые сознательно

- все анонимные вызовы делят одну identity, значит анонимный клиент может редактировать заметки
  и отменять (`abandon`) черновики, созданные другим анонимным клиентом (`proposals.py:65,208,625`).
  Это прямое следствие общей identity, менять логику владения **не нужно**;
- `E_SELF_REVIEW` для анонимных предложений не срабатывает: `anonymous` ≠ identity человека.
  Это желаемое поведение — человек принимает черновик агента;
- `RATE_LIMIT_PER_MIN` для анонима не работает (лимит считается по имени токена). Лимит переносится
  на обратный прокси по IP — записать требованием в `docs/deploy-almalinux.md`.

## `wikiagent` остаётся за человеческой сессией

`src/wikiagent/api.py:86-91` требует, чтобы допуск вызывающего был не ниже допуска рабочего токена
агента (`restricted`). Анонимный принципал имеет `internal`, значит получает 403 — и это правильно:
через агента нельзя получить доступ к тому, чего не видишь сам.

Отсюда прямое следствие для задачи 07B: **`wk audit` в первой версии не реализуется.**
Сверка документации запускается из UI, где есть человеческая сессия. Правку внести в
`todo/07-policy-sync-and-audit.md` при выполнении этой задачи. Клиентский путь к `wikiagent`
без сессии не открывать: это обойдёт проверку допуска.

## Тесты части A

`tests/test_anonymous.py`:

1. `ANONYMOUS_ACCESS=0`: запрос без заголовка → 401 (регресс не допускается);
2. включено, без заголовка: `GET /whoami` → `name=anonymous`, `kind=agent`, `role=writer`, `clearance=internal`;
3. включено, неверный токен → 401; отозванный → 401; истёкший → 401;
4. анонимный `POST /proposals/{pid}/accept` → 403 **`E_FORBIDDEN`**.
   Именно этот код, а не `E_HUMAN_REQUIRED`: ручка объявлена с `actor: Reviewer`
   (`api/routers/proposals.py:124`), поэтому `require_role` в зависимости срабатывает **раньше**
   `require_human` в сервисе. Порядок проверок **не менять** — он корректен,
   `E_HUMAN_REQUIRED` остаётся кодом для агентского токена с ролью reviewer;
5. анонимный `POST /rules/{id}/promote`, `/deprecate`, `/proposals/{pid}/revert`,
   `/findings/{id}/dismiss` → 403;
6. анонимный `GET` страницы с `sensitivity: restricted` → 404; её нет в `search`, `context`, графе;
7. анонимный `POST /raw` и `GET /raw/...` → 404 (`E_NOT_FOUND`): существующая
   `Raw.require_clearance` скрывает сырьё; код сохраняется по требованию совместимости API;
8. `ANONYMOUS_ROLE=admin` или `ANONYMOUS_CLEARANCE=restricted` → приложение не стартует;
9. анонимный полный цикл: `create_proposal` → `put_page` → `validate` → `submit` проходит;
   созданное правило имеет `lifecycle: candidate`, `level: should`, `priority: 3`;
10. человек с `kind=human` принимает анонимное предложение — `E_SELF_REVIEW` не срабатывает;
11. git-автор принятого коммита — имя **человека**, не `anonymous`.

---

# Часть B. Выпуск сессий в `wikisvc`

## Эндпоинт

`POST /api/v1/sessions`, новый роутер `src/wikisvc/api/routers/sessions.py`.

Вызывающий: токен, имя которого **точно равно** `session_issuer_token_name`, с `kind=agent`.
Любой другой токен → 403. Пустое `session_issuer_token_name` → эндпоинт отдаёт 404 (функция выключена).

Авторизация идёт **по имени токена, а не по роли**, поэтому выпускающему токену привилегии не нужны:
он выдаётся как `role=reader`, `clearance=public`. Это защита в глубину — если охрана путей
когда-нибудь регрессирует, этот токен сможет прочитать только публичные страницы.

## Область действия выпускающего токена

Токен с именем `session_issuer_token_name` имеет право **только** на `POST /api/v1/sessions`.
Любой другой путь и метод → 403 `E_FORBIDDEN`.

Проверка ставится там, где принципал уже установлен, и не обходится ни одним входом:

- в middleware `main.py` — сразу после аутентификации, покрывает все `/api/v1/*`;
- в обёртке MCP (задача 01) — этот токен отвергается полностью, MCP ему недоступен;
- `api/deps.py:Authorize` читает `request.state.actor`, выставленный middleware, поэтому
  отдельная проверка там не нужна.

Следствие для диагностики: `GET /whoami` этому токену тоже запрещён, значит
`llm-wiki-check` проверяет его наличие **по локальной БД** (как `wikisvc token list`),
а не запросом по HTTP. Это `fail` при отсутствии или отзыве.

Тело:

```json
{"subject": "<oidc sub>", "username": "<preferred_username>", "groups": ["wiki-reviewers"]}
```

Поведение:

1. `subject` обязателен, 1–128 символов, соответствует `[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}` — это `person`;
2. `username` санитизируется до `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`; не проходит — `user-<subject[:8]>`.
   Результат — **`display_name`** (см. ниже), он попадает в git-автора, поэтому санитайзинг обязателен;
3. `role` и `clearance` берутся из карты групп (ниже). Ни одна группа не сопоставлена → `reader` + `public`;
4. `kind="human"` — жёстко. Эндпоинт не умеет выпускать `kind=agent`;
5. **имя строки токена**: `sso-<subject[:8]>-<unix>` — `tokens.name` имеет UNIQUE (`auth.py:81`);
6. `expires_at` = сейчас + `session_ttl_hours`;
7. ответ: `{"token": "<plaintext>", "expires_at": "...", "actor": {...}}`. Токен отдаётся один раз;
8. аудит: `token.session.create` с `subject`, **без** токена и без групп.

## Имя строки токена против имени человека

`tokens.name` сейчас несёт две роли: уникальный ключ строки и `Principal.name`, который уходит
в git-автора (`storage/gitrepo.py:22` через `proposals.py:693`). Для сессий это конфликт: ключ обязан
быть уникальным на сессию, а автор коммита — стабильным и читаемым.

Вариант «одно имя `sso-<username>-<суффикс>`» отвергнут: имя автора менялось бы каждую сессию
и навсегда осело бы в истории вики, а история здесь — продуктовая поверхность
(`/pages/{id}/history`, `/pages/{id}/at/{commit}`, `revert`). `git log --author` стал бы бесполезен.

### Разрешённые изменения — только эти три

Этот пункт отменяет запрет на правку `Auth` из `todo/AGENTS.md` **в объёме ровно трёх правок**:

1. `src/wikisvc/storage/state_db.py:65-69` — в существующий словарь `migrations["tokens"]`
   добавить `"display_name": "TEXT"`. Механизм `ALTER TABLE ... ADD COLUMN` уже есть
   (`state_db.py:80-84`), существующие данные сохраняются, у старых строк значение `NULL`;
2. `Auth.create(...)` — необязательный параметр `display_name: str | None = None`, пишется в новую
   колонку. Существующие вызовы (CLI, тесты) не меняются;
3. `Auth.authenticate(...)` — перед `Principal.model_validate(rows[0])` подставить
   `name = display_name or name`. Две строки.

Ничего другого в `Auth` не меняется: проверка хеша, `hmac.compare_digest`, срок, отзыв,
учёт лимита по `tokens.name` — как есть. Лимит продолжает считаться по имени строки,
то есть **на сессию**, и это желаемое поведение.

Итог модели для сессии: `tokens.name = sso-<sub8>-<unix>` (ключ, лимит),
`display_name = <username>` (`Principal.name`, git-автор), `person = <sub>`
(`Principal.identity`, `E_SELF_REVIEW`, `decided_by`, `verified_by`).

Читаемость identity обеспечивается отдельно от её хранения: таблица
`people(person TEXT PRIMARY KEY, display_name TEXT NOT NULL, updated_at TEXT NOT NULL)`
создаётся в существующем блоке схемы. Каждый выпуск сессии делает upsert по person
с текущими display_name и now(), одна строка на человека. `GET /api/v1/people`
возвращает список с обычными limit/cursor, требует reader и допуск internal.
UI разрешает verified_by и identity автора предложения в display_name; если записи
нет, показывает сохранённое имя автора либо саму identity. verified_by не менять:
его стабильное значение участвует в валидации и компиляции политик. Subject mode
user_username не использовать: переименование и повторное использование логина
не должны менять или объединять людей.

Отдельно разрешена одна правка `services/proposals.py`: при записи `decided_by`
использовать `actor.identity` вместо `actor.name`, не меняя машину состояний и проверки.
Исторические строки сохраняют прежнее имя; новые содержат identity. Для токенов без
`person` эти значения совпадают. Старые человеческие записи не переписываются:
это различие архивного представления, поле не участвует в проверке полномочий.

`DELETE /api/v1/sessions/current` — отзывает токен, которым сделан запрос (`Auth.revoke` по его имени).
Доступно любому `kind=human` для своей сессии. Нужен для logout.

## Карта групп

Файл `/etc/llm-wiki/roles.yaml`, путь — из `ROLES_FILE`. Root-owned, `0640`, группа `llm-wiki`.

```yaml
default: { role: reader, clearance: public }
groups:
  wiki-readers:   { role: reader,   clearance: internal }
  wiki-writers:   { role: writer,   clearance: internal }
  wiki-reviewers: { role: reviewer, clearance: restricted }
  wiki-admins:    { role: admin,    clearance: restricted }
```

- несколько совпавших групп → берётся **максимальная** роль и максимальный допуск;
- неизвестная группа игнорируется;
- файл отсутствует или не разбирается → приложение не стартует;
- **карта прав не хранится в репозитории вики.** Writer может предложить правку чего угодно
  в `schema/`, включая собственную роль. Это требование безопасности, не вкусовое.

## Очистка

`Auth.expire_sessions()` удаляет строки с истёкшим `expires_at` и именем по шаблону `sso-%`.
Вызов — рядом с `runtime.proposals.expire()` в `main.py:lifespan`.

## Тесты части B

1. выпуск неразрешённым токеном → 403; при пустой настройке → 404;
2. `kind=human` в выпущенном принципале; попытка задать `kind=agent` телом игнорируется;
3. `username` с пробелами/юникодом → `display_name` санитизирован, `person` равен `subject`;
4. два выпуска для одного `subject` → разные `tokens.name`, **одинаковый** `display_name`
   и одинаковый `person`; оба токена валидны;
4a. git-автор коммита принятия одинаков для двух разных сессий одного человека;
4b. токен без `display_name` (выпущенный CLI до миграции) даёт `Principal.name = tokens.name` —
    прежнее поведение сохранено;
4c. выпускающий токен на `GET /whoami`, `GET /search`, любой `POST` кроме `/sessions`,
    и на MCP → 403 `E_FORBIDDEN`; на `POST /sessions` → успех;
5. карта групп: несколько групп → максимальные роль и допуск; неизвестная → `default`;
6. истёкший сессионный токен → 401; `expire_sessions()` удаляет его строку;
7. `DELETE /sessions/current` → токен перестаёт работать;
8. два человека с разными `sub`: один создал предложение в UI, второй принял — проходит;
   тот же `sub` в новой сессии пытается принять своё — `E_SELF_REVIEW` 403 (identity стабильна);
9. аудит не содержит plaintext-токена.

---

# Часть C. OIDC в `wiki-ui`

`wikisvc` остаётся герметичным: исходящих запросов и JWT-библиотек в нём нет и не появляется.
Вся работа с Authentik — в Go-сервисе.

## Поток

1. нет cookie сессии → redirect на Authentik, authorization code + **PKCE (S256)**, параметры `state` и `nonce`;
2. callback: сверить `state`, обменять код на токены, проверить ID-token — подпись по JWKS,
   `iss`, `aud`, `exp`, `iat`, `nonce`. Допуск по часам ≤ 60 с;
3. из claims взять `sub`, `preferred_username`, `groups`;
4. `POST /api/v1/sessions` в wikisvc со служебным токеном;
5. полученный токен — в cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, срок = `expires_at`;
6. прокси подставляет `Authorization: Bearer` из cookie в `/api/v1/*` и `/agent-api/*`;
7. `/logout`: `DELETE /api/v1/sessions/current`, удалить cookie, redirect на end-session Authentik.

## Требования

- `state` и `nonce` — криптослучайные, одноразовые, живут не дольше 10 минут;
- client secret читается **из файла** (`/etc/llm-wiki/ui-oidc.secret`, `0640`, `root:llm-ui`), не из env;
- JWKS кэшируется в памяти с периодическим обновлением; недоступность Authentik не ломает уже
  открытые сессии;
- токен сессии не попадает в JS, в логи, в URL и в шаблоны;
- при 401 от wikisvc прокси удаляет cookie и отправляет на логин;
- `/healthz` остаётся без авторизации.

## Фронтенд

- `ui/src/pages/Login.tsx` — экран ввода токена удаляется, вместо него redirect на `/auth/login`;
- `ui/src/auth.tsx` — `credentials`/`sessionStorage` убрать; `actor` получается из `GET /api/v1/whoami`,
  который теперь авторизуется cookie через прокси; `logout()` вызывает `/auth/logout`;
- `canWrite`/`canReview` не меняются: они читают `role` и `kind` из `/whoami`.

## Тесты части C

Go, `httptest` + поддельный OIDC-эндпоинт:

1. нет cookie → 302 на Authentik с `code_challenge`, `state`, `nonce`;
2. callback с чужим `state` → 400, cookie не выставляется;
3. callback с `nonce`, не совпадающим с ID-token → 400;
4. успешный callback → cookie с флагами `HttpOnly`, `Secure`, `SameSite=Lax`;
5. проксированный запрос несёт `Authorization` из cookie; ответ 401 от wikisvc → cookie удалён;
6. `/logout` вызывает `DELETE /sessions/current`;
7. значение токена не встречается ни в одном логе и ни в одном теле ответа.

---

# Часть C2. Authentik на удалённом сервере

Authentik живёт **не на этом хосте**. Схема не меняется, но появляются четыре темы:
доступность, время, доверие к транспорту и путь входа, когда IdP недоступен.

## Деградация, а не отказ

Удалённый IdP — внешняя зависимость. Требования:

- **`wiki-ui` стартует, даже если Authentik недоступен.** OIDC discovery и JWKS получаются
  лениво, с повтором, а не на старте. Недоступность IdP ломает только вход; уже выданные
  сессии, чтение вики и ручное ревью продолжают работать. Это тот же принцип, что у
  `wiki-ui` относительно `wikiagent`, который ждёт модель;
- `ExecStartPre` для `wiki-ui.service` **не добавлять**: проверка внешнего сервиса не должна
  мешать запуску;
- на `/auth/login` при недоступном IdP — 503 с одной понятной строкой, не 500 и не таймаут
  на минуту;
- именно поэтому сессия выпускается **токеном wikisvc** со своим TTL, а не проверяется у IdP
  на каждый запрос: падение Authentik не выбрасывает работающих людей.

## Явные таймауты

Все исходящие вызовы к IdP (discovery, token, JWKS, end-session) — с жёсткими таймаутами:
соединение 5 с, запрос целиком 10 с, `follow_redirects` выключен. Без этого повисший IdP
держит обработчик логина и копит горутины.

## Время

Проверка `exp`/`iat`/`nonce` идёт между двумя машинами. Расхождение часов — рабочий отказ:
вход «вдруг перестаёт работать».

- допуск по скью ≤ 60 с, больше не ставить;
- на сервере вики обязателен работающий NTP (`chronyd` или `systemd-timesyncd`);
- в `docs/deploy-almalinux.md` — пункт «проверь `timedatectl`: `System clock synchronized: yes`».
  Он уже упоминается для окон `heal`; здесь добавить вторую причину.

## Транспорт и доверие

- только `https` у `WIKI_UI_OIDC_ISSUER`. `http` — ошибка конфигурации при старте, кроме явного
  `WIKI_UI_OIDC_INSECURE_HTTP=1`, допустимого лишь для локального стенда;
- проверка сертификата **всегда включена**. `InsecureSkipVerify` в коде отсутствует;
- внутренний CA: путь к корневому сертификату задаётся `SSL_CERT_FILE` в `ui.env`
  (Go читает системный пул, на AlmaLinux это `/etc/pki/tls/certs/ca-bundle.crt`;
  для частного CA нужен явный путь). Файл положить в `/etc/llm-wiki/`, права как у конфигов;
- `ProtectSystem=strict` и `PrivateTmp=true` оставляют `/etc` читаемым, поэтому
  `resolv.conf` и CA-бандл доступны. Менять юнит не нужно;
- если позже будете ограничивать egress — `wiki-ui` нужен исход **только** к хосту Authentik.
  `wikisvc` и `wikiagent` исходящий доступ в интернет не нужен вовсе; записать это в документацию
  как намеренное свойство.

## Адрес возврата

Браузер должен достучаться и до Authentik, и до `wiki-ui`, поэтому `redirect_uri` — это адрес,
видимый **браузеру**, а не внутренний loopback:

| сценарий | `WIKI_UI_OIDC_REDIRECT_URL` | cookie `Secure` |
|---|---|---|
| команда, TLS-прокси перед `wiki-ui` | `https://wiki.<домен>/auth/callback` | `1` |
| один человек через SSH-туннель | `http://127.0.0.1:8789/auth/callback` | `1` — браузеры считают `127.0.0.1` защищённым контекстом |

Оба варианта регистрируются в Authentik как разрешённые redirect URI. Несовпадение даёт ошибку
на стороне IdP — в документации указать это первым пунктом диагностики входа.

## Группы приходят только при настроенном mapping

В Authentik claim `groups` попадает в ID-token лишь при добавленном scope mapping для групп.
Без него claim отсутствует, карта групп не совпадает ни с чем, и по правилу default-deny
**все становятся `reader`/`public`** — вход работает, а прав нет.

Поэтому:

- после входа UI показывает роль и допуск текущего пользователя (данные уже есть в `/whoami`);
- `llm-wiki-check` печатает, какие группы сопоставлены в `roles.yaml`;
- в документации — отдельный пункт: «нет прав после входа → проверь scope mapping групп
  в провайдере Authentik».

## Аварийный вход

Удалённый IdP недоступен, а решение принять надо. Без запасного пути система встаёт:
принимать предложения, повышать правила и администрировать вику может только `kind=human`.

- один **аварийный** человеческий токен выпускается заранее, офлайн, через CLI:
  `wikisvc token create --name breakglass --person <ваш sub> --kind human --role admin
  --clearance restricted --expires-at <дата>`;
- `--person` обязательно равен вашему `sub` из Authentik, иначе вы станете для системы
  вторым человеком и обойдёте `E_SELF_REVIEW` на собственных предложениях;
- хранится вне сервера, как пароль от сейфа; срок ограничен; после использования отзывается
  и выпускается новый;
- применяется напрямую к API (`Authorization: Bearer`), минуя UI;
- в `docs/deploy-almalinux.md` — раздел «Аварийный доступ» с этим порядком и с требованием
  проверять токен раз в квартал.

## Тесты части C2

1. discovery недоступен на старте → `wiki-ui` поднялся, `/healthz` отвечает, чтение вики работает;
2. `/auth/login` при недоступном IdP → 503 с текстом, время ответа меньше таймаута;
3. уже выданная сессия продолжает работать при недоступном IdP;
4. ID-token с `exp` в прошлом и с перекосом больше 60 с → вход отвергнут;
5. ID-token без claim `groups` → принципал `reader`/`public`, вход при этом успешен;
6. `WIKI_UI_OIDC_ISSUER` со схемой `http` без флага → отказ при старте;
7. end-session недоступен → локальный logout всё равно удаляет cookie и отзывает сессию.

# Часть D. Развёртывание

`deploy/almalinux/service.env`:

```
ANONYMOUS_ACCESS=1
ANONYMOUS_ROLE=writer
ANONYMOUS_CLEARANCE=internal
SESSION_ISSUER_TOKEN_NAME=wiki-ui
SESSION_TTL_HOURS=12
ROLES_FILE=/etc/llm-wiki/roles.yaml
RATE_LIMIT_PER_MIN=120
```

`deploy/almalinux/ui.env` — добавить: `WIKI_UI_OIDC_ISSUER`, `WIKI_UI_OIDC_CLIENT_ID`,
`WIKI_UI_OIDC_SECRET_FILE`, `WIKI_UI_OIDC_REDIRECT_URL`, `WIKI_UI_SESSION_TOKEN_FILE`,
`WIKI_UI_COOKIE_SECURE=1`, `SSL_CERT_FILE` (закомментирован, нужен только для частного CA).

Новые файлы в комплекте: `deploy/almalinux/roles.yaml`, пустой `ui-oidc.secret`.
`deploy/install.sh` раскладывает их как остальные конфиги (`0640`, существующие не перезаписывает),
секреты — с группой `llm-ui`.

`deploy/systemd/wiki-ui.service`: `wiki-ui` нужен исходящий доступ к удалённому Authentik.
`ExecStartPre` с проверкой IdP **не добавлять** (см. часть C2).
`wikisvc.service` и `wikiagent.service` — без изменений, исходящий доступ им не нужен.

`llm-wiki-check` (`src/wikiagent/check.py`) дополнить:

- `roles.yaml` разбирается, печатать сопоставленные группы;
- служебный токен `wiki-ui` существует и не отозван — это `fail`;
- OIDC discovery (`<issuer>/.well-known/openid-configuration`) доступен — это **`warn`**, не `fail`:
  удалённый IdP не влияет на работоспособность вики и не должен валить проверку;
- `timedatectl` сообщает `System clock synchronized: yes` — `warn` при расхождении.

`docs/deploy-almalinux.md`:

- раздел «Токены» переписать: персональных токенов нет. Выпускаются два служебных —
  `wikiagent` (`writer`/`agent`/`restricted`) и `wiki-ui` (**`reader`/`agent`/`public`**,
  имя совпадает с `SESSION_ISSUER_TOKEN_NAME`). Второму привилегии не нужны: эндпоинт
  авторизует его по имени, а все пути кроме `POST /sessions` ему запрещены;
- новый раздел «Authentik» (IdP на **удалённом** сервере): provider, application,
  разрешённые redirect URI для обоих сценариев из части C2, **scope mapping для групп**,
  соответствие групп и `roles.yaml`, требование работающего NTP, частный CA через `SSL_CERT_FILE`;
- раздел «Диагностика входа», по порядку: несовпадение redirect URI; отсутствие scope mapping
  групп (вход есть, прав нет — все `reader`/`public`); расхождение часов; недоступность IdP
  (вход 503, работающие сессии и чтение не затронуты);
- новый раздел «Аварийный доступ»: порядок выпуска breakglass-токена, обязательное совпадение
  `--person` с вашим `sub`, хранение вне сервера, отзыв после использования, проверка раз в квартал;
- **явное предупреждение**: при `ANONYMOUS_ACCESS=1` порт `8787` становится доступом уровня
  writer/internal. Держать на loopback за SSH-туннелем, mTLS или в закрытом сегменте.
  Наружу выставлять только `wiki-ui` за TLS;
- лимит запросов для анонима — на обратном прокси по IP.

`docs/decisions.md` — записать: анонимный доступ допустим, пока в вике нет материалов `restricted`;
их появление требует пересмотра. Это дверь в одну сторону.

---

## Готово, когда

- `nix develop -c just lint`, `pytest --cov`, `nix flake check`, `go test ./...` — зелёные;
- при `ANONYMOUS_ACCESS=0` и пустом `SESSION_ISSUER_TOKEN_NAME` поведение **HTTP API и MCP**
  прежнее, включая коды ошибок; существующие тесты не правятся;
- **UI переводится на OIDC без режима совместимости**: форма ввода токена удаляется, второго
  пути входа не остаётся. Иначе SSO превращается в декорацию — включённый «на всякий случай»
  вход по токену никто потом не выключит;
- `wiki-ui` **отказывается стартовать**, если OIDC не настроен (нет issuer, client id или файла
  секрета) — с одной внятной строкой в журнале. Это не противоречит части C2:
  «не настроен» → отказ при старте, «настроен, но недоступен» → старт и деградация только входа;
- аварийный путь на время недоступности IdP — **API, а не UI**: в документации показать
  `GET /proposals/{pid}` (взять `accept_body` из плана) и `POST /proposals/{pid}/accept`
  с breakglass-токеном;
- порядок развёртывания в документации: сначала настроить Authentik и выпустить служебный токен,
  потом переустанавливать `wiki-ui`;
- анонимный клиент читает `internal`, создаёт предложения и получает 403 на любое решение;
- `wiki-ui` поднимается и отдаёт вику при **недоступном** Authentik; выданные сессии живут;
- `llm-wiki-check` сообщает недоступность IdP как `warn`, а отсутствие служебного токена как `fail`;
- `docs/deploy-almalinux.md` и `docs/decisions.md` обновлены, включая разделы
  «Диагностика входа» и «Аварийный доступ».

## Не делать

- не добавлять JWT-библиотеки и исходящие запросы в `wikisvc`;
- не вводить доверие к заголовкам вида `X-authentik-*`;
- не менять `Auth` шире трёх правок, перечисленных в разделе «Разрешённые изменения»:
  колонка `display_name` в миграциях, необязательный параметр в `Auth.create`,
  подстановка `name = display_name or name` в `Auth.authenticate`.
  `Principal`, `require_human`, `require_role` и порядок проверок роли и `kind` — не трогать;
- не позволять анонимному принципалу `reviewer`, `admin` или `restricted`;
- не открывать `wikiagent` анонимным вызовам;
- не хранить карту прав и секреты в репозитории вики;
- не отключать проверку TLS-сертификата Authentik ни флагом, ни `InsecureSkipVerify`,
  ни «временно для отладки»;
- не делать запуск `wiki-ui` зависимым от доступности удалённого IdP;
- не проверять сессию у IdP на каждый запрос: сессия живёт TTL токена wikisvc;
- не расширять допуск по скью больше 60 с, чтобы «починить» вход — чинить часы.
