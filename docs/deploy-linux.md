# Установка на Linux через Nix

Nix собирает и фиксирует Python, Git, Go и зависимости из `flake.lock` и
`ui/package-lock.json`, `ui/go.sum` и хеша Go vendor. На Linux с systemd комплект запускает четыре сервиса:
`wikisvc`, `wikiagent`, `wiki-ui`, `llm-wiki-model` (llama-server). Вход в `nix develop` на сервере не нужен.
Службы работают от отдельных системных пользователей, API слушают loopback.

```text
/opt/llm-wiki/current       установленный Nix bundle (постоянный GC root)
/opt/llm-wiki/previous      предыдущий bundle для отката
/etc/llm-wiki/             service.env, agent.env, wikiagent.yaml, llama.env, ui.env, backup.env
/var/lib/llm-wiki/
  wiki/                    отдельный репозиторий контента, включая .git
  state/                   state.db, worktrees, library, extract
  agent/                   agent.db, сессии и задачи
  index/                   производный индекс
/var/backups/llm-wiki/     закрытые резервные копии (root, 0700)
/srv/llm-wiki/models/      GGUF (не входит в Git и Nix store)
```

## 1. Nix и сборка

Нужны Linux с systemd, Bash, `sudo`, Git, curl, xz, GNU tar/gzip/find,
util-linux (`runuser`, `flock`, `getent`) и средства создания пользователей
(`useradd`, `groupadd`, `usermod`). Имена пакетов зависят от дистрибутива.
Подходят Arch, Debian, Ubuntu и другие системы с этими утилитами. Само приложение
и его Python/Go/Node-зависимости собирает Nix; NixOS не требуется.
Ниже — установка systemd-комплекта. Без systemd используйте готовые бинарники
`nix build .#wikisvc .#ui` под своим supervisor: он должен передавать то же
окружение и запускать службы от нужных пользователей. Автоматический установщик
требует systemd и в таком режиме не запускается.

Установку Nix выбирайте по [официальному руководству](https://nix.dev/install-nix).
Для обычной серверной системы используется multi-user daemon. На машине с
SELinux проверьте поддержку политики выбранным способом установки Nix;
установщик проекта не меняет SELinux и firewall.

```sh
# Сначала установите перечисленные системные утилиты пакетным менеджером своей ОС.
# Если Nix ещё не установлен:
curl --proto '=https' --tlsv1.2 -sSfL https://nixos.org/nix/install -o /tmp/install-nix.sh
# Просмотрите скрипт, затем запустите от обычного пользователя с sudo:
sh /tmp/install-nix.sh --daemon
# Откройте новую оболочку после установки.
nix --version

git clone git@github.com:BadRabbit00/llm-wiki.git backend
cd backend
nix --extra-experimental-features 'nix-command flakes' build .#deployment --out-link result-deployment
sudo ./result-deployment/bin/llm-wiki-install
```

При отсутствии SSH-ключа с доступом к GitHub используйте разрешённый вам способ
клонирования. `flake.lock` уже в репозитории; `nix flake update` при установке не нужен.
Сборка выполняет pytest, Ruff, mypy, ShellCheck, TypeScript и Go-тесты. Первая сборка может занять время.
Установщик создаёт пользователей, каталоги, конфигурацию и units; существующие
конфиги и контент сохраняются. Службы запускаются ниже, после настройки.

## 2. Новая вики или перенос

**Новая установка:**

```sh
sudo /usr/local/sbin/llm-wiki-admin wikisvc init /var/lib/llm-wiki/wiki
sudo /usr/local/sbin/llm-wiki-admin wikisvc reindex --full
sudo /usr/local/sbin/llm-wiki-admin wikisvc lint
```

**Перенос существующей вики:** не запускайте `init`. Используйте раздел переноса
ниже, включая `repair-worktrees`, затем продолжайте настройку токенов и модели.

Конфигурация сервисов — `/etc/llm-wiki/service.env`. Стандартные пути подходят
systemd-ограничениям записи; при изменении путей вне `/var/lib/llm-wiki` также
обновите `ReadWritePaths`/`RequiresMountsFor` через `systemctl edit`.
ENV-файлы используют простые `KEY=value` или `KEY="value with spaces"`, без
`export`, подстановки `$VAR`, обратных кавычек и команд. Их читают systemd и CLI helper.

## 3. Токены и Authentik

```sh
sudo /usr/local/sbin/llm-wiki-admin wikisvc token create \
  --name wikiagent --person wikiagent --kind agent --role writer --clearance restricted
sudoedit /etc/llm-wiki/agent.env
# Впишите выданный токен после WIKIAGENT_TOKEN=.

sudo /usr/local/sbin/llm-wiki-admin wikisvc token create \
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
в ui.env: PEM bundle системных корней и внутреннего CA, доступный llm-ui и диагностике
(например root:root, 0644; сертификаты публичные). Расположение системного bundle
зависит от дистрибутива; Go использует системные доверенные корни. Проверка TLS всегда включена.
Только локальный стенд с loopback IdP допускает `WIKI_UI_OIDC_INSECURE_HTTP=1`.

UI получает discovery/JWKS лениво, обновляет ключи каждые 5 минут и при промахе.
Соединение ограничено 5 секундами, запрос — 10; HTTP redirects к IdP не выполняются.
При недоступном IdP новый вход даёт 503; существующие сессии живут свой TTL
(`SESSION_TTL_HOURS=12`). Смена имени обновляет запись в справочнике людей,
а `person`, саморевью и сохранённые подтверждения остаются привязаны к sub.

## 4. Gemma 4 31B и llama-server

Нужны GGUF и версия llama.cpp, которая поддерживает именно этот файл и structured
JSON. Бинарник llama-server, его GPU-библиотеки и драйвер устанавливаются отдельно
под оборудование сервера. Nix bundle вики не включает CUDA или модель.
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
sudo /usr/local/sbin/llm-wiki-admin check --dependencies-only --wait 600 --model
sudo systemctl enable --now wikiagent wiki-ui
curl --fail http://127.0.0.1:8789/healthz
sudo /usr/local/sbin/llm-wiki-admin check --model
```

`wikiagent` перед стартом ждёт wiki API и зарегистрированную модель до 10 минут,
затем повторяет попытку через systemd. Проверка `--model` делает короткий запрос
к каждой уникальной настроенной модели; не создаёт предложений или задач.
Она проверяет совместимость протокола, а не качество решений Gemma 31B.
Эта модель ещё не проходила нашу оценку на данном сервере.

Проверка сценариев из checkout:

```sh
sudo /usr/local/sbin/llm-wiki-admin wikiagent eval \
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
sudo /usr/local/sbin/llm-wiki-admin check
```

`401`/`403`: проверьте токен, role/kind и clearance. Ошибка alias: сравните
`/v1/models` с YAML. GPU OOM: смотрите журнал модели и уменьшайте нагрузку на память.
При SELinux AVC используйте `sudo ausearch -m AVC -ts recent`, чтобы найти конкретное
отклонённое действие, если на сервере используется SELinux. На целевом сервере
нужно проверить запуск и права устройств; прохождение локальных тестов не проверяет GPU хоста.

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
sudo /usr/local/sbin/llm-wiki-admin wikisvc token create \
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
sudo /usr/local/sbin/llm-wiki-admin wikisvc token revoke breakglass
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

Каталог принадлежит root с правами `0700`, архивы — root с правами `0600`;
после создания применяется `restorecon`, если он доступен. Архив сначала пишется
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

Не используйте `llm-wiki-admin`: он читает рабочий `service.env` и переходит в рабочий
каталог. Здесь вызывается CLI напрямую. `Settings` читает только окружение
(`env_file=None`), поэтому для каждой команды явно заданы все три пути.
Отдельный `INDEX_DIR` находится вне `WIKI_ROOT` и не равен `STATE_DIR`.
Ни одна команда проверки не указывает на рабочий `/var/lib/llm-wiki`.

```sh
sudo sh -eu <<'RESTORE'
test ! -e /tmp/restore-test
test ! -L /tmp/restore-test
install -d -m 0700 /tmp/restore-test
trap 'rm -rf -- /tmp/restore-test' EXIT
tar --no-same-owner -C /tmp/restore-test -xzf '/var/backups/llm-wiki/data-<дата-UTC>-<суффикс>.tar.gz'
install -d -m 0700 /tmp/restore-test/index

env WIKI_ROOT=/tmp/restore-test/var/lib/llm-wiki/wiki \
  STATE_DIR=/tmp/restore-test/var/lib/llm-wiki/state \
  INDEX_DIR=/tmp/restore-test/index \
  /opt/llm-wiki/current/bin/wikisvc repair-worktrees
env WIKI_ROOT=/tmp/restore-test/var/lib/llm-wiki/wiki \
  STATE_DIR=/tmp/restore-test/var/lib/llm-wiki/state \
  INDEX_DIR=/tmp/restore-test/index \
  /opt/llm-wiki/current/bin/wikisvc reindex --full
env WIKI_ROOT=/tmp/restore-test/var/lib/llm-wiki/wiki \
  STATE_DIR=/tmp/restore-test/var/lib/llm-wiki/state \
  INDEX_DIR=/tmp/restore-test/index \
  /opt/llm-wiki/current/bin/wikisvc lint
RESTORE
```

После успешной проверки включите регулярный запуск:

```sh
sudo systemctl enable --now llm-wiki-backup.timer
systemctl list-timers llm-wiki-backup.timer
```

## Включение самолечения и аудита документации

В комплекте `heal.enabled: false`. Порядок включения:

1. Выполните первую операцию вручную; человек должен проверить и принять хотя бы
   одно предложение.
2. Добейтесь успешного `sudo /usr/local/sbin/llm-wiki-admin check --model`.
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

`docs_audit` появится в задаче 07. Текущая конфигурация ещё не поддерживает этот
раздел и отклоняет неизвестные поля: пока не добавляйте его в YAML. После появления
функции она должна оставаться выключенной по умолчанию (`docs_audit.enabled: false`)
и включаться отдельно:

1. Выполните ручной аудит и дождитесь человеческого ревью и принятия предложения.
2. Повторите проверку `check --model`, часового пояса и обязательную проверку копии.
3. Выберите окно аудита без пересечения с резервным копированием.
4. Включите `docs_audit.enabled` только в версии с поддержкой задачи 07 и
   перезапустите `wikiagent`.
5. Через сутки проверьте статистику находок; пороги корректирует человек
   по результатам ревью, по тому же правилу, что и для `heal`.

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
`backend/.dev/state/` → `/var/lib/llm-wiki/state`,
каталог состояния агента → `/var/lib/llm-wiki/agent`.
Копируйте содержимое каталогов вместе со скрытыми файлами (`cp -a SOURCE/. DEST/`).
Восстанавливайте в пустые каталоги, не смешивая с другой установкой.
Конфиги проверьте отдельно: старые абсолютные пути и имя 12B-модели здесь не подходят.
`agent.env` нужен с исходным токеном, соответствующим скопированной state.db.
Если его нет, выпустите новый агентский токен.

```sh
# На новой машине после копирования, до старта служб:
sudo chown -R llm-wiki:llm-wiki /var/lib/llm-wiki
if command -v restorecon >/dev/null; then
  sudo restorecon -RF /var/lib/llm-wiki /etc/llm-wiki
fi
sudo /usr/local/sbin/llm-wiki-admin wikisvc repair-worktrees
sudo /usr/local/sbin/llm-wiki-admin wikisvc schema upgrade
sudo /usr/local/sbin/llm-wiki-admin wikisvc reindex --full
sudo /usr/local/sbin/llm-wiki-admin wikisvc lint
```

`repair-worktrees` исправляет абсолютные связи Git после смены путей и отказывается
продолжать при недостающем worktree. Открытые предложения сохраняются; обычный
`git clone` контента не переносит state.db, worktrees, книги, сессии и токены.
Не запускайте одновременно старую и новую копии агента, если это один рабочий набор.
GGUF копируется отдельно. Архив содержит внутренние материалы и agent.env,
храните его с теми же правами, что и рабочие данные.

## Обновление и откат

Сначала соберите новую версию, пока старая работает. Затем остановите таймер,
дождитесь завершения текущего задания копирования, если оно выполняется,
и остановите сервисы. Сделайте согласованную резервную копию и установите готовый bundle:

```sh
git pull --ff-only
nix --extra-experimental-features 'nix-command flakes' build .#deployment --out-link result-deployment
sudo systemctl stop llm-wiki-backup.timer
# Если копирование уже идёт, дождитесь его завершения перед остановкой служб.
sudo systemctl stop wiki-ui wikiagent wikisvc llm-wiki-model
# Копия для обновления: службы остаются остановленными до конца обслуживания.
# Не запускайте здесь backup.service: его ExecStopPost вернёт службы в работу.
sudo install -d -m 0700 /var/backups/llm-wiki
if command -v restorecon >/dev/null; then
  sudo restorecon /var/backups/llm-wiki
fi
sudo sh -eu -c 'umask 077; tar -C / -czf "/var/backups/llm-wiki/pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" \
  var/lib/llm-wiki/wiki var/lib/llm-wiki/state var/lib/llm-wiki/agent etc/llm-wiki'
# Проверьте эту копию по инструкции восстановления выше.
sudo ./result-deployment/bin/llm-wiki-install
sudo /usr/local/sbin/llm-wiki-admin wikisvc schema upgrade
sudo /usr/local/sbin/llm-wiki-admin wikisvc reindex --full
sudo /usr/local/sbin/llm-wiki-admin wikisvc lint
sudo systemctl start llm-wiki-model wikisvc wikiagent wiki-ui
sudo /usr/local/sbin/llm-wiki-admin check --model
# Если таймер был включён до обслуживания:
sudo systemctl start llm-wiki-backup.timer
```

Установщик сохраняет `/etc/llm-wiki`; новые примеры сравнивайте с
`result-deployment/share/llm-wiki/linux/`. Units переустанавливаются; местные
изменения делайте в systemd drop-ins. Текущий и предыдущий bundle закреплены
GC roots, удаление checkout или `result-deployment` не ломает службы.

Для отката также остановите таймер, дождитесь завершения копирования,
остановите службы и выполните
`sudo /opt/llm-wiki/previous/bin/llm-wiki-install`: установщик вернёт прежний bundle
и units. Если версия изменила формат данных/схему, до запуска также восстановите
совместимую резервную копию данных и конфигурации. Смена бинарника сама по себе
не откатывает миграции БД.
