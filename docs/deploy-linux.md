# Установка на Linux: podman и образ релиза

`wikisvc`, `wikiagent` и `wiki-ui` запускаются из одного образа релиза
`ghcr.io/badrabbit00/llm-wiki` в rootful podman, каждый своим systemd-юнитом.
Четвёртая служба — `llm-wiki-model` (llama-server) — работает на хосте. Образ
собирает CI (раздел «Образ контейнера»), на сервере ничего не собирается.
Через Nix ставится только хост-часть: юниты, шаблоны конфигурации и скрипты.
Службы работают от отдельных системных пользователей, API слушают loopback.

```text
/opt/llm-wiki/current       хост-часть: скрипты и юниты (постоянный GC root)
/opt/llm-wiki/previous      предыдущая хост-часть для отката
/etc/llm-wiki/             service.env, agent.env, wikiagent.yaml, llama.env, ui.env, backup.env
/etc/llm-wiki/image.env    образ релиза, закреплённый по дайджесту
/var/lib/llm-wiki/
  wiki/                    отдельный репозиторий контента, включая .git
  state/                   state.db, worktrees, library, extract
  agent/                   agent.db, сессии и задачи
  index/                   производный индекс
/var/backups/llm-wiki/     закрытые резервные копии (root, 0700)
/srv/llm-wiki/models/      GGUF (не входит в Git и Nix store)
```

## 1. podman, Nix и хост-часть

Нужны Linux с systemd, Bash, `sudo`, podman, curl, xz, GNU tar/gzip/find,
`getent` и средства создания пользователей (`useradd`, `groupadd`, `usermod`).
Юниты вызывают `/usr/bin/podman` и `/usr/bin/systemctl` — обычные пути дистрибутива.
На Arch: `pacman -S podman`. Nix нужен только для хост-части; NixOS не требуется.
Установку Nix выбирайте по [официальному руководству](https://nix.dev/install-nix),
для сервера — multi-user daemon. Установщик проекта не меняет firewall.

Хост-часть собирается за секунды и не содержит приложения. Клон репозитория и
SSH-доступ к GitHub не нужны: Nix забирает версию по HTTPS.

```sh
sudo pacman -S podman
nix --extra-experimental-features 'nix-command flakes' \
  build 'github:BadRabbit00/llm-wiki/vX.Y.Z#deployment' --out-link result-deployment
sudo ./result-deployment/bin/llm-wiki-install
```

Установщик создаёт пользователей, каталоги, конфигурацию и юниты; существующие
конфиги и контент сохраняются. Затем закрепите образ релиза той же версии.
Проверьте происхождение (подпись `release.yml` из этого репозитория) и запишите
дайджест — юниты запускают только образ, закреплённый по дайджесту:

```sh
image=ghcr.io/badrabbit00/llm-wiki
sudo podman pull "$image:vX.Y.Z"
digest=$(sudo podman image inspect --format '{{.Digest}}' "$image:vX.Y.Z")
nix shell nixpkgs#cosign -c cosign verify-attestation --type https://slsa.dev/provenance/v1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/vX.Y.Z' \
  "$image@$digest" > /dev/null
echo "LLM_WIKI_IMAGE=$image@$digest" | sudo tee /etc/llm-wiki/image.env
```

Службы не скачивают образ при старте (`--pull never`): после перезагрузки они
поднимаются без сети. Службы запускаются ниже, после настройки.

## 2. Новая вики или перенос

**Новая установка:**

```sh
sudo llm-wiki-admin wikisvc init /var/lib/llm-wiki/wiki
sudo llm-wiki-admin wikisvc reindex --full
sudo llm-wiki-admin wikisvc lint
```

`llm-wiki-admin` установщик кладёт симлинком в `/usr/local/sbin`, а этот каталог
входит в `secure_path` у sudo на Arch, Debian и Ubuntu — короткого имени
достаточно. Где `secure_path` собран без `/usr/local/sbin`, зовите полным
путём: `sudo /usr/local/sbin/llm-wiki-admin …`.

**Перенос существующей вики:** не запускайте `init`. Используйте раздел переноса
ниже, включая `repair-worktrees`, затем продолжайте настройку токенов и модели.

`llm-wiki-admin` выполняет команду в одноразовом контейнере образа релиза от
`llm-wiki`, со всеми каталогами данных и настройками.

Конфигурация сервисов — `/etc/llm-wiki/service.env`. Контейнеры видят только
`/var/lib/llm-wiki` и `/etc/llm-wiki` по тем же путям, поэтому данные держите там.
ENV-файлы — простые строки `KEY=value`: podman передаёт значение как есть, без
снятия кавычек, без `export`, подстановки `$VAR` и команд.

## 3. Токены и Authentik

```sh
sudo llm-wiki-admin wikisvc token create \
  --name wikiagent --person wikiagent --kind agent --role writer --clearance restricted
sudoedit /etc/llm-wiki/agent.env
# Впишите выданный токен после WIKIAGENT_TOKEN=.

sudo llm-wiki-admin wikisvc token create \
  --name wiki-ui --kind agent --role reader --clearance public
sudoedit /etc/llm-wiki/ui-session.token
# Впишите только выданный wiki-ui токен, без KEY= и кавычек.
```

Токены выводятся один раз. `wiki-ui` может только выпускать сессии, даже `/whoami`
и MCP для него закрыты. Права reader/public ограничивают ущерб при ошибке охраны путей.
После переноса state.db прежние токены сохраняются;
проверьте `llm-wiki-admin wikisvc token list`, повторно выдавать тот же name нельзя.
Потерянный агентский токен отзовите и выпустите с новым name, сохранив person=wikiagent.

Сначала подготовьте удалённый Authentik и служебный токен, затем устанавливайте
или обновляйте `wiki-ui`. Установщик сохраняет конфигурацию: при обновлении
добавьте новые параметры из `deploy/linux/service.env` и `ui.env` вручную.
Без issuer, client id и непустых файлов секретов новый UI откажется стартовать.
Настроенный, но недоступный IdP запуску не мешает.

В Authentik создайте Application `wiki` с confidential OAuth2/OIDC Provider:
authorization code, PKCE S256, RSA signing key (RS256), issuer mode per-provider.
Выберите стабильный непрозрачный subject, например user UUID: не `user_username`.
Не меняйте subject mode после запуска: переименование логина не должно менять человека.
Укажите точные redirect URI браузера: `https://wiki.example.org/auth/callback`
для TLS-прокси или `http://127.0.0.1:8789/auth/callback` для SSH-туннеля.
Параметры провайдера описаны в [документации Authentik](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/).

Добавьте scopes `openid`, `profile`, `email`, `groups` и включите
**Include claims in id_token**. Для scope `groups` создайте mapping:

```python
return {"groups": [group.name for group in request.user.groups.all()]}
```

Mapping нужно выбрать в провайдере; без него пользователи получают reader/public.
См. [scope mappings](https://docs.goauthentik.io/add-secure-apps/providers/property-mappings/)
и [штатные mappings Authentik](https://github.com/goauthentik/authentik/blob/main/blueprints/system/providers-oauth2.yaml).
Сопоставление групп задаёт `/etc/llm-wiki/roles.yaml` (root:llm-wiki, 0640, вне wiki).
Поставляются wiki-readers → reader/internal, wiki-writers → writer/internal,
wiki-reviewers → reviewer/restricted, wiki-admins → admin/restricted.
При нескольких группах берутся максимальные роль и допуск; неизвестные группы
ничего не добавляют. Изменение карты требует перезапуска wikisvc и нового входа;
уже выданные сессии сохраняют права до отзыва или окончания TTL.

```sh
sudoedit /etc/llm-wiki/ui.env
# WIKI_UI_OIDC_ISSUER=https://auth.example.org/application/o/wiki/
# WIKI_UI_OIDC_CLIENT_ID=<client id провайдера>
# WIKI_UI_OIDC_REDIRECT_URL=https://wiki.example.org/auth/callback
# WIKI_UI_COOKIE_SECURE=1
sudoedit /etc/llm-wiki/ui-oidc.secret
# Только client secret. ui-oidc.secret и ui-session.token: root:llm-ui, 0640.
sudoedit /etc/llm-wiki/roles.yaml
timedatectl
```

На сервере вики и IdP нужен NTP (`chronyd` или `systemd-timesyncd`):
`System clock synchronized: yes`. Это нужно и для окон heal, и для проверки
OIDC exp/iat/nbf; допуск будущего iat/nbf — не более 60 секунд, истёкший exp отвергается.
Issuer обязан быть HTTPS. Для частного CA укажите `SSL_CERT_FILE=/etc/llm-wiki/idp-ca.pem`
в ui.env: PEM bundle публичных корней и внутреннего CA, доступный llm-ui и диагностике
(например root:root, 0644; сертификаты публичные). Файл должен лежать в
`/etc/llm-wiki`: контейнер видит только этот каталог хоста. Без `SSL_CERT_FILE`
образ доверяет публичным корням из своего CA bundle. Проверка TLS всегда включена.
Только локальный стенд с loopback IdP допускает `WIKI_UI_OIDC_INSECURE_HTTP=1`.

UI получает discovery/JWKS лениво, обновляет ключи каждые 5 минут и при промахе.
Соединение ограничено 5 секундами, запрос — 10; HTTP redirects к IdP не выполняются.
При недоступном IdP новый вход даёт 503; существующие сессии живут свой TTL
(`SESSION_TTL_HOURS=12`). Смена имени обновляет запись в справочнике людей,
а `person`, саморевью и сохранённые подтверждения остаются привязаны к sub.

## 4. Gemma 4 31B и llama-server

Нужны GGUF и версия llama.cpp, которая поддерживает именно этот файл и structured
JSON. Бинарник llama-server, его GPU-библиотеки и драйвер устанавливаются отдельно
под оборудование сервера. Ни образ, ни хост-часть не включают CUDA или модель.
Если llama-server тоже установлен через Nix, держите его в постоянном Nix profile
или другом GC root; для GPU должны быть доступны библиотеки драйвера **хоста**.
Сначала проверьте запуск этого бинарника на целевом компьютере.

```sh
# Пример размещения файла; замените путь и имя на свой GGUF.
sudo cp /path/to/gemma-4-31b.gguf /srv/llm-wiki/models/
sudo chown llm-model:llm-model /srv/llm-wiki/models/gemma-4-31b.gguf
sudo chmod 0640 /srv/llm-wiki/models/gemma-4-31b.gguf
sudoedit /etc/llm-wiki/llama.env
sudoedit /etc/llm-wiki/wikiagent.yaml
```

В `llama.env` задайте `LLAMA_SERVER_BIN` абсолютным путём к работающему бинарнику
и `LLAMA_ARG_MODEL` путём к GGUF. Для split GGUF скопируйте все части и укажите первую.
Бинарник/модель должны быть доступны `llm-model`; `/home` и `/root` скрыты от службы.
Установщик добавляет llm-model в существующие группы video/render.

| Параметр llama.env | Параметр wikiagent.yaml | Начальное значение |
|---|---|---|
| LLAMA_ARG_ALIAS | models.*.model | wiki-gemma-31b |
| LLAMA_ARG_HOST / PORT | models.*.base_url | 127.0.0.1:18089 /v1 |
| LLAMA_ARG_CTX_SIZE | models.*.context | 16384 |
| LLAMA_ARG_N_PARALLEL | — | 1 |
| LLAMA_ARG_N_GPU_LAYERS | — | auto |

Контекст и alias должны совпадать. 16K — стартовая настройка, её пригодность зависит
от квантования, RAM/VRAM и GPU. `auto` подбирает выгрузку слоёв; при необходимости
задайте число вручную. При нехватке памяти уменьшайте контекст **в обоих** файлах
и `limits.chapter_chunk_tokens` (для 16K здесь 4000). Не включайте несколько слотов
без пересчёта контекста на слот. В примере reasoning выключен, KV cache q8_0,
Flash Attention включён; доступные параметры проверяйте через `llama-server --help`.
Описание переменных и API — [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

```sh
sudo systemctl enable --now llm-wiki-model wikisvc
sudo journalctl -u llm-wiki-model -n 80 --no-pager
curl --fail http://127.0.0.1:18089/health
curl --fail http://127.0.0.1:8787/api/v1/health

# Дождаться загрузки модели, проверить токен, alias и генерацию JSON:
sudo llm-wiki-admin check --dependencies-only --wait 600 --model
sudo systemctl enable --now wikiagent wiki-ui
curl --fail http://127.0.0.1:8789/healthz
sudo llm-wiki-admin check --model
```

`wikiagent` перед стартом ждёт wiki API и зарегистрированную модель до 10 минут,
затем повторяет попытку через systemd. Проверка `--model` делает короткий запрос
к каждой уникальной настроенной модели; не создаёт предложений или задач.
Она проверяет совместимость протокола, а не качество решений Gemma 31B.
Эта модель ещё не проходила нашу оценку на данном сервере.

Проверка сценариев из checkout:

```sh
sudo llm-wiki-admin wikiagent eval \
  --scenarios "$PWD/tests/scenarios" --out /var/lib/llm-wiki/agent/eval-31b.json
```

Каталог scenarios должен быть доступен llm-wiki (если checkout в закрытом home,
скопируйте `tests/scenarios/` в `/var/lib/llm-wiki/agent/scenarios/` и задайте этот путь).
В комплекте 12 сценариев, порог полного допуска — ≥30 и ≥90% правильных результатов;
прежний отчёт Gemma 12B не является оценкой 31B. Самолечение включается отдельно,
после ручного цикла и настройки резервного копирования, по порядку ниже.

## 5. Доступ и диагностика

Для доступа со своего компьютера достаточно SSH-туннеля:

```sh
ssh -N -L 8789:127.0.0.1:8789 user@wiki-host
```

Откройте **http://127.0.0.1:8789**: вход перенаправит в Authentik. Для туннеля
задайте этот браузерный origin в redirect URI, сохранив `WIKI_UI_COOKIE_SECURE=1`
(loopback в поддерживаемом браузере — доверенный контекст).
Все обращения к wiki и агенту идут через Go-прокси. Сессионный токен находится
только в HttpOnly/Secure/SameSite=Lax cookie; JavaScript его не видит.
У службы `llm-ui` нет доступа к файлам вики и рабочему токену агента.
Статика и шрифты встроены в бинарник; Node.js и внешние CDN для запуска не нужны.

Адрес задаётся в `/etc/llm-wiki/ui.env`: `WIKI_UI_BIND=127.0.0.1:8789`.
Там же `WIKI_UI_WIKISVC_URL` и `WIKI_UI_AGENT_URL` — HTTP(S) origins внутренних
API без путей. По умолчанию это loopback:8787 и loopback:8788. Модель остаётся
локальной; UI не хранит её параметры и использует настройки wikiagent.

Для общего сетевого доступа поставьте TLS reverse proxy перед `127.0.0.1:8789`.
Проксируйте `/` целиком, сохраняйте Cookie и Origin, выключите buffering для SSE
и задайте таймаут не ниже таймаута модели. Если загружаете книги, увеличьте лимит
тела у внешнего прокси до настроенного размера книги. UI запускается, даже пока
wikiagent ждёт модель; чтение вики и ручное ревью продолжают работать.

В `/etc/llm-wiki/service.env` комплект задаёт `RATE_LIMIT_PER_MIN=120`.
Лимит считается отдельно на имя токена; запросы `/api/v1/health` не считаются.
Превышение возвращает HTTP `429` с кодом `E_RATE_LIMIT`. Значение по умолчанию
в приложении — `0`, оно отключает ограничение. При обновлении установщик сохраняет
существующий `service.env`: добавьте параметр вручную и перезапустите `wikisvc`.
Комплект включает `ANONYMOUS_ACCESS=1`: API/MCP без Authorization получают
writer/internal с kind=agent. **API с анонимным writer нельзя публиковать в интернет.**
Ограничьте сеть и настройте лимит **по IP на прокси перед API/MCP**;
анонимные клиенты делят одну identity и общий пул предложений. Решения, restricted
и wikiagent им недоступны. Встроенный лимит защищает служебные и сессионные токены;
у разных сессий одного человека независимые счётчики.

В интернет исходящий доступ нужен только wiki-ui → хост Authentik (кроме локальных
API wikisvc/wikiagent). Ядру wikisvc интернет не нужен; wikiagent обращается к локальной
модели. OIDC discovery не добавляется в ExecStartPre и не блокирует запуск служб.

Swagger остаётся на http://127.0.0.1:8787/docs и http://127.0.0.1:8788/docs;
для доступа к нему с другого компьютера добавьте соответствующие SSH forwards.

```sh
sudo systemctl status wikisvc wikiagent wiki-ui llm-wiki-model
sudo journalctl -u wikisvc -u wikiagent -u wiki-ui -u llm-wiki-model -f
sudo llm-wiki-admin check
```

`401`/`403`: проверьте токен, role/kind и clearance. Ошибка alias: сравните
`/v1/models` с YAML. GPU OOM: смотрите журнал модели и уменьшайте нагрузку на память.
На целевом сервере нужно проверить запуск и права устройств; прохождение локальных
тестов не проверяет GPU хоста.

### Диагностика входа

Диагностика проверяет роли и служебный токен UI по локальной БД: отсутствие,
отзыв, истечение срока или лишние полномочия — fail. Печатает сопоставленные группы;
недоступность discovery и несинхронизированное время — warn. `--dependencies-only`
по-прежнему проверяет только локальные зависимости агента.
Ошибка входа: сначала сравните redirect URI **побайтно** с настройкой провайдера,
затем issuer, client id, secret, NTP и CA. Нет прав после входа — проверьте scope
mapping групп и Include claims in id_token; роль/допуск видны в настройках UI.
После logout локальная сессия отзывается даже при отказе IdP; возможная ошибка
страницы end-session не возвращает ей доступ.

### Аварийный доступ

До аварии выпустите ограниченный по сроку human-токен; `--person` должен точно
совпадать с вашим sub из Authentik (виден как `person` в `/api/v1/whoami`),
иначе вы получите вторую identity и обойдёте запрет саморевью:

```sh
sudo llm-wiki-admin wikisvc token create \
  --name breakglass --person '<ваш sub>' --kind human --role admin \
  --clearance restricted --expires-at '<ISO-8601 дата с часовым поясом>'
```

Храните токен вне сервера, как пароль от сейфа. Проверяйте раз в квартал запросом
`GET /api/v1/whoami`. В аварии обращайтесь напрямую к API через локальный доступ
или SSH-туннель; в UI входа по токену нет. В оболочке с безопасно установленным
`BREAKGLASS_TOKEN` и выбранным `PID`:

```sh
curl --fail -H "Authorization: Bearer $BREAKGLASS_TOKEN" \
  "http://127.0.0.1:8787/api/v1/proposals/$PID"
# Просмотрите diff/impact и notes.accept_body из ответа (план решения).
# Сохраните проверенный accept_body как accept.json; не принимайте вслепую.
curl --fail -X POST -H "Authorization: Bearer $BREAKGLASS_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @accept.json \
  "http://127.0.0.1:8787/api/v1/proposals/$PID/accept"
sudo llm-wiki-admin wikisvc token revoke breakglass
```

После использования выпустите новый токен с другим name и тем же person;
срок обновляйте до истечения. Штатные проверки человеческого решения и саморевью
в аварийном API действуют полностью.

## Резервное копирование

Установщик копирует `llm-wiki-backup.service`, `llm-wiki-backup.timer` и
`/etc/llm-wiki/backup.env`, сохраняя существующий env-файл. Таймер включает человек.
По умолчанию он запускается ежедневно в **23:00 по местному времени сервера**,
архивы хранятся в `BACKUP_DIR=/var/backups/llm-wiki`, срок — `BACKUP_KEEP_DAYS=14`.
Путь должен быть абсолютным, вне `/var/lib/llm-wiki` и `/etc/llm-wiki`, срок — целым
числом дней от 1 до 99999. Для отдельного диска добавьте его точку монтирования
в `RequiresMountsFor` через `systemctl edit llm-wiki-backup.service`.

Задание останавливает `wiki-ui`, `wikiagent`, `wikisvc` и архивирует целиком
`wiki/` (включая `.git`), `state/` (SQLite, worktrees, библиотеку), `agent/`
(сессии и задачи) и `/etc/llm-wiki` (включая `agent.env`). Индекс не входит в архив.
На время копирования завершите также отдельные пишущие CLI/MCP-процессы;
не запускайте службы вручную до завершения задания. Модель останавливать не нужно.

Каталог принадлежит root с правами `0700`, архивы — root с правами `0600`.
Архив сначала пишется
во временный файл и получает имя `data-<дата-UTC>-<суффикс>.tar.gz` только после
успешного завершения `tar`. Затем удаляются завершённые архивы `data-*.tar.gz`
старше `BACKUP_KEEP_DAYS` в этом каталоге. При ошибке архивирования прежние копии
не удаляются. Используются GNU tar, gzip и find, установленные на хосте.

`ExecStopPost` ставит запуск служб в очередь через `systemctl --no-block start`,
в том числе после ошибки остановки или архивирования. Поэтому после задания
проверьте и его результат, и готовность служб: постановка в очередь ещё не означает,
что они уже запустились.

Зарезервируйте окно **23:00–01:00** для остановки, копирования и запуска служб.
Оно не пересекается с поставляемым окном `heal` **01:00–06:00**. `TimeoutStartSec=45min`
ограничивает отдельно остановку и архивирование; оставшееся время — запас на запуск.
При изменении расписания или таймаутов пересчитайте запас и окна `heal`.
`Persistent=true` догоняет пропущенный запуск после включения таймера, поэтому
после простоя копирование может начаться сразу, вне обычного окна. Планируйте
такое включение в период обслуживания; службы всё равно будут остановлены.

```sh
sudoedit /etc/llm-wiki/backup.env
timedatectl
# При необходимости изменить расписание через drop-in:
# sudo systemctl edit llm-wiki-backup.timer
# [Timer]
# OnCalendar=
# OnCalendar=*-*-* 23:00:00
sudo systemctl daemon-reload
sudo systemctl start llm-wiki-backup.service
sudo journalctl -u llm-wiki-backup.service -n 80 --no-pager
sudo systemctl status wikisvc wikiagent wiki-ui
```

### Обязательная проверка восстановления

**Непроверенная копия копией не считается.** После первой копии и регулярно после
обновлений проверяйте восстановление доверенного архива. Замените имя архива ниже
на существующее. Каталог `/tmp/restore-test` должен отсутствовать: пример прекращает
работу, если он уже есть, создаёт его с правами `0700` и удаляет после проверки,
включая случай ошибки. Внутри находятся секреты из `agent.env` и внутренние материалы.
`--no-same-owner` оставляет владельцем распакованных файлов root, от которого идёт проверка.

Не используйте `llm-wiki-admin`: он монтирует рабочие `/var/lib/llm-wiki` и
`/etc/llm-wiki`. Здесь CLI запускается в контейнере установленного образа без сети,
от `llm-wiki`, и видит только каталог проверки. `Settings` читает только окружение
(`env_file=None`), поэтому все три пути заданы явно. Отдельный `INDEX_DIR`
находится вне `WIKI_ROOT` и не равен `STATE_DIR`.

```sh
sudo sh -eu <<'RESTORE'
test ! -e /tmp/restore-test
test ! -L /tmp/restore-test
install -d -m 0700 /tmp/restore-test
trap 'rm -rf -- /tmp/restore-test' EXIT
tar --no-same-owner -C /tmp/restore-test -xzf '/var/backups/llm-wiki/data-<дата-UTC>-<суффикс>.tar.gz'
install -d -m 0700 /tmp/restore-test/index
chown -R llm-wiki:llm-wiki /tmp/restore-test
image=$(sed -n 's/^LLM_WIKI_IMAGE=//p' /etc/llm-wiki/image.env)
for command in repair-worktrees 'reindex --full' lint; do
  podman run --rm --pull never --network none --read-only --tmpfs /tmp \
    --user "$(id -u llm-wiki):$(id -g llm-wiki)" --volume /tmp/restore-test:/restore \
    --env WIKI_ROOT=/restore/var/lib/llm-wiki/wiki \
    --env STATE_DIR=/restore/var/lib/llm-wiki/state --env INDEX_DIR=/restore/index \
    "$image" wikisvc $command
done
RESTORE
```

Архив содержит и `image.env` своего времени: при настоящем восстановлении вместе с
данными вернётся и образ, с которым они были записаны.

После успешной проверки включите регулярный запуск:

```sh
sudo systemctl enable --now llm-wiki-backup.timer
systemctl list-timers llm-wiki-backup.timer
```

## Включение самолечения и аудита документации

В комплекте `heal.enabled: false`. Порядок включения:

1. Выполните первую операцию вручную; человек должен проверить и принять хотя бы
   одно предложение.
2. Добейтесь успешного `sudo llm-wiki-admin check --model`.
3. Проверьте `timedatectl`: окна `heal` используют местное время сервера,
   часовой пояс должен совпадать с ожидаемым.
4. Настройте и проверьте резервное копирование по разделу выше. Убедитесь, что
   окна `heal` не пересекаются с окном бэкапа, включая остановку и запуск служб.
5. Только теперь задайте `heal.enabled: true` в `/etc/llm-wiki/wikiagent.yaml`
   и выполните `sudo systemctl restart wikiagent`.
6. Через сутки проверьте `GET /api/v1/findings/stats` с человеческим токеном.
   Если для вида находок `dismissed / (resolved + dismissed) > 0.5`, API возвращает
   `recommendation: "Поднять порог уверенности"`. Много ложных срабатываний означает,
   что `confidence_threshold` **занижен**. Человек повышает его в `wikiagent.yaml`
   и перезапускает `wikiagent`; система порог сама не меняет.

`docs_audit` реализован и поддерживается конфигурацией; в комплекте он выключен
(`docs_audit.enabled: false`) и включается тем же порядком, что `heal`:

1. Выполните ручной аудит из UI и дождитесь человеческого ревью: хотя бы одна
   находка разобрана, хотя бы одно связанное предложение принято.
2. Повторите проверку `check --model`, часового пояса и обязательную проверку копии.
3. Убедитесь, что запуски аудита не пересекаются с окном резервного копирования.
4. Задайте `docs_audit.enabled: true` и перезапустите `wikiagent`.
5. Через сутки проверьте статистику находок; порог `confidence_threshold`
   корректирует человек по результатам ревью, по тому же правилу, что и для `heal`.

Аудит запускается **только из UI**, человеческой сессией: клиентского пути
к `wikiagent` без неё нет, и команды `wk audit` не существует. Это сознательное
ограничение — иначе обошлось бы сравнение допусков. Загружаемые файлы: до 200
штук `.md`, по 256 КиБ, суммарно до `MAX_UPLOAD_MB` и `docs_audit.max_total_bytes`.

## Перенос данных

GitHub содержит **код**, а данные переносятся отдельно. До копирования остановите
wiki-ui, wikiagent, wikisvc и прочие пишущие клиенты CLI/MCP. Для dev-запуска завершите процессы
в терминалах. Сохраняйте весь wiki, включая `.git`, весь STATE_DIR, весь
WIKIAGENT_STATE_DIR, конфиги и agent.env. Индекс можно пересоздать.

Для уже развёрнутой установки используйте проверенный архив из раздела
«Резервное копирование». Перед окончательным переносом остановите таймер,
дождитесь завершения текущего копирования, остановите службы и снимите последнюю
копию командой `tar` из раздела «Обновление и откат». До завершения переноса
не возобновляйте запись на старой машине. Задание `llm-wiki-backup.service`
для этого не подходит: оно возвращает службы в работу после копирования.

Для переноса текущей структуры `work/wiki` + `work/backend/.dev/` архив удобно
создать из `work/` после остановки процессов; `agent/` включайте, если он существует:

```sh
umask 077
tar -czf wiki-data.tar.gz wiki backend/.dev/state
# Если использовался wikiagent, также перенесите его фактический state_dir целиком.
# Обычно это backend/.dev/agent; пользовательская настройка могла указывать другой путь.
```

На новой машине распакуйте доверенную копию во временный закрытый каталог.
При стандартной серверной копии пути уже имеют вид `var/lib/llm-wiki/...`;
для dev-копии разложите `wiki/` → `/var/lib/llm-wiki/wiki`,
`.dev/state/` репозитория кода → `/var/lib/llm-wiki/state`,
каталог состояния агента → `/var/lib/llm-wiki/agent`.
Копируйте содержимое каталогов вместе со скрытыми файлами (`cp -a SOURCE/. DEST/`).
Восстанавливайте в пустые каталоги, не смешивая с другой установкой.
Конфиги проверьте отдельно: старые абсолютные пути и имя 12B-модели здесь не подходят.
`agent.env` нужен с исходным токеном, соответствующим скопированной state.db.
Если его нет, выпустите новый агентский токен.

На новой машине сначала установите хост-часть и закрепите образ (раздел 1).
Если вы восстановили `/etc/llm-wiki` из архива, в нём уже есть `image.env` старой
машины: выполните для этого дайджеста `podman pull`.

```sh
# На новой машине после копирования, до старта служб:
sudo chown -R llm-wiki:llm-wiki /var/lib/llm-wiki
sudo llm-wiki-admin wikisvc repair-worktrees
sudo llm-wiki-admin wikisvc schema upgrade
sudo llm-wiki-admin wikisvc reindex --full
sudo llm-wiki-admin wikisvc lint
```

`repair-worktrees` исправляет абсолютные связи Git после смены путей и отказывается
продолжать при недостающем worktree. Открытые предложения сохраняются; обычный
`git clone` контента не переносит state.db, worktrees, книги, сессии и токены.
Не запускайте одновременно старую и новую копии агента, если это один рабочий набор.
GGUF копируется отдельно. Архив содержит внутренние материалы и agent.env,
храните его с теми же правами, что и рабочие данные.

## Обновление из интерфейса

`llm-wiki-updater` — демон хост-части. Он раз в 6 часов проверяет реестр, а
администратор подтверждает обновление кнопкой в интерфейсе: **Настройки →
Обновления**. Там же выбирается канал: релизы (`vX.Y.Z`) или бета (`vX.Y.Z-beta.N`;
бета-канал сам переходит на вышедший релиз). Пока есть обновление, администратор
видит метку в шапке. Остальным пользователям раздел и метка не показываются.

```sh
sudo systemctl enable --now llm-wiki-updater.socket llm-wiki-updater.service
sudo journalctl -u llm-wiki-updater -f
```

Демон работает от root: он останавливает и запускает службы, скачивает образы и
восстанавливает данные. Поэтому доступ к нему узкий. Его единственный интерфейс —
сокет `/run/llm-wiki-updater/api.sock` с правами `root:llm-ui 0660`; в него ходит
только `wiki-ui`, проксируя `/updater-api/`. Каждый запрос демон проверяет у
`wikisvc` (`/api/v1/whoami`): пускает только человека с ролью `admin`. Подтвердить
можно только то обновление, которое демон сам нашёл и проверил, — назвать ему
произвольный образ нельзя.

Обновление предлагается, только если `cosign` подтвердил: образ собран
`release.yml` этого репозитория **для этого тега**. Серверу нужен исходящий HTTPS
до `ghcr.io` и до Sigstore TUF (`tuf-repo-cdn.sigstore.dev`): `cosign` держит там
корень доверия, кэш — в `/var/lib/llm-wiki-updater`. Токен GitHub не нужен.

Что происходит после подтверждения:

1. Образ скачивается по дайджесту, подпись проверяется ещё раз.
2. `wikiagent jobs` фиксирует задачи, которые агент продолжит после рестарта.
3. Таймер копий останавливается; идущее копирование дожидается конца.
4. Службы останавливаются мягко: агент дописывает открытые ответы чата и ставит
   задачи на паузу на ближайшем чекпоинте (до 11 минут).
5. Данные и `/etc/llm-wiki` архивируются в
   `/var/backups/llm-wiki/pre-update-<время>-<тег>.tar.gz` (root, `0600`).
6. `image.env` переключается на новый дайджест (прежний — в `image.env.previous`),
   новый образ выполняет `schema upgrade`, `reindex --full` и `lint`.
7. Службы запускаются; `wikisvc` должен сообщить версию из тега, а всё, что
   работало до обновления, — снова работать.
8. Задачи сверяются со списком из шага 2, таймер копий возвращается, из архивов
   перед обновлениями остаются три последних.

Если шаги 6–7 не прошли, демон откатывается сам: текущие данные откладываются в
`*.failed-<время>`, архив распаковывается на место (вместе с прежним `image.env`),
индекс перестраивается прежним образом, службы запускаются и проверяются. Если
сбой случился до шага 6, данные не менялись — службы просто запускаются снова.
Итог, шаги, задачи и путь к архиву видны в разделе обновлений; состояние — в
`/var/lib/llm-wiki-updater/state.json`.

Отложенные `*.failed-*` удаляет человек, разобравшись в причине. Если демон
остановился посреди обновления (перезагрузка, сбой), он не гадает, на каком шаге
система: обновление помечается «прервано», и дальше действует администратор —
по журналу демона и, если нужно, по архиву из раздела ниже.

## Обновление и откат

Обычно обновляет `llm-wiki-updater` (раздел выше); вручную — когда он выключен
или для разбора сбоя. Версия — это образ релиза; хост-часть меняется редко и
обновляется отдельно.
Сначала скачайте и проверьте новый образ, пока старый работает:

```sh
image=ghcr.io/badrabbit00/llm-wiki
sudo podman pull "$image:vX.Y.Z"
digest=$(sudo podman image inspect --format '{{.Digest}}' "$image:vX.Y.Z")
nix shell nixpkgs#cosign -c cosign verify-attestation --type https://slsa.dev/provenance/v1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/vX.Y.Z' \
  "$image@$digest" > /dev/null
```

Затем остановите таймер, дождитесь завершения текущего копирования, если оно идёт,
и остановите службы. `wikiagent` при остановке дописывает открытые ответы чата и
ставит задачи на паузу на ближайшем чекпоинте (до 11 минут); после запуска они
продолжаются. Модель останавливать не нужно: она не входит в образ.

```sh
sudo systemctl stop llm-wiki-backup.timer
sudo systemctl stop wiki-ui wikiagent wikisvc
# Копия для обновления: службы остаются остановленными до конца обслуживания.
# Не запускайте здесь backup.service: его ExecStopPost вернёт службы в работу.
sudo install -d -m 0700 /var/backups/llm-wiki
sudo sh -eu -c 'umask 077; tar -C / -czf "/var/backups/llm-wiki/pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" \
  var/lib/llm-wiki/wiki var/lib/llm-wiki/state var/lib/llm-wiki/agent etc/llm-wiki'
# Проверьте эту копию по инструкции восстановления выше.
sudo cp /etc/llm-wiki/image.env /etc/llm-wiki/image.env.previous
echo "LLM_WIKI_IMAGE=$image@$digest" | sudo tee /etc/llm-wiki/image.env
sudo llm-wiki-admin wikisvc schema upgrade
sudo llm-wiki-admin wikisvc reindex --full
sudo llm-wiki-admin wikisvc lint
sudo systemctl start wikisvc wikiagent wiki-ui
curl --fail http://127.0.0.1:8787/api/v1/health    # version — новая
sudo llm-wiki-admin check --model
# Если таймер был включён до обслуживания:
sudo systemctl start llm-wiki-backup.timer
```

Откат: остановите службы, верните `image.env.previous` на место `image.env` и
запустите службы. Предыдущий образ остаётся в хранилище podman, пока его не удалят
(`podman image prune`), — не чистите его, пока новая версия не проверена. Если
релиз изменил схему, до запуска восстановите pre-upgrade копию: смена образа
сама по себе не откатывает миграции БД.

Хост-часть (юниты, `llm-wiki-run`, `llm-wiki-admin`) обновляется так же, как
ставилась: соберите `#deployment` нужной версии, остановите службы и
`llm-wiki-updater`, выполните
`llm-wiki-install`. Установщик сохраняет `/etc/llm-wiki`; новые примеры сравнивайте
с `result-deployment/share/llm-wiki/linux/`. Юниты переустанавливаются; местные
изменения делайте в systemd drop-ins. Текущая и предыдущая хост-часть закреплены
GC roots; откат — `sudo /opt/llm-wiki/previous/bin/llm-wiki-install`.

## Образ контейнера

Каждый мердж в `main` и каждый тег версии публикуют образ
`ghcr.io/badrabbit00/llm-wiki` (`.github/workflows/release.yml`). Теги образа:
`vX.Y.Z` — релиз, `vX.Y.Z-beta.N` — бета той же версии, `main` — последний мердж,
`sha-<7 символов коммита>` — конкретная сборка. Обновления предлагаются только из
тегов версий; `main` и `sha-` нужны для проверок. Пакет публичный, токен для
`podman pull` не нужен. Каждая публикация подписана attestation происхождения:
`cosign verify-attestation` из примеров выше доказывает, что дайджест собран
`release.yml` этого репозитория из указанного тега.

Образ один на три службы. В нём только closures служб, git и CA-сертификаты,
shell нет. `llama-server` в образ не входит и остаётся на хосте. Коммит, из которого
собран образ, записан в метке `org.opencontainers.image.revision`.

Все контейнеры запускает `llm-wiki-run`: юниты (`daemon`), `llm-wiki-admin`
(`once maintenance`) и проверки. Флаги повторяют прежний hardening systemd-юнитов:
`--network host` (службы и модель слушают loopback хоста), `--read-only --tmpfs /tmp`,
`--cap-drop ALL`, `--security-opt no-new-privileges`, `--pull never`, журнал в
journald под именем юнита и `--user` с uid и gid пользователя службы.

| Профиль | Команда | Пользователь | `--env-file` | Тома |
|---|---|---|---|---|
| wikisvc | `wikisvc serve` | `llm-wiki` | `service.env` | `/var/lib/llm-wiki`, `/etc/llm-wiki:ro` |
| wikiagent | `wikiagent serve` | `llm-wiki` | `service.env`, `agent.env` | `/var/lib/llm-wiki:ro`, `/var/lib/llm-wiki/agent`, `/etc/llm-wiki:ro` |
| wiki-ui | `wiki-ui` | `llm-ui` | `ui.env` | `/etc/llm-wiki:ro` |
| maintenance | любая (`llm-wiki-admin`) | `llm-wiki` | `service.env`, `agent.env`, `ui.env` | `/var/lib/llm-wiki`, `/etc/llm-wiki:ro` |

Состояние контейнеров — `sudo podman ps`; журналы — `journalctl -u <служба>`.
