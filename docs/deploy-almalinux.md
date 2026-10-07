# AlmaLinux + Nix + локальная Gemma 4 31B

Nix собирает и фиксирует Python, Git, Go и зависимости из `flake.lock` и
`ui/package-lock.json`. Обычный systemd AlmaLinux запускает четыре сервиса:
`wikisvc`, `wikiagent`, `wiki-ui`, `llm-wiki-model` (llama-server). Вход в `nix develop` на сервере не нужен.
Службы работают от отдельных системных пользователей, API слушают loopback.

```text
/opt/llm-wiki/current       установленный Nix bundle (постоянный GC root)
/opt/llm-wiki/previous      предыдущий bundle для отката
/etc/llm-wiki/             service.env, agent.env, wikiagent.yaml, llama.env, ui.env
/var/lib/llm-wiki/
  wiki/                    отдельный репозиторий контента, включая .git
  state/                   state.db, worktrees, library, extract
  agent/                   agent.db, сессии и задачи
  index/                   производный индекс
/srv/llm-wiki/models/      GGUF (не входит в Git и Nix store)
```

## 1. Nix и сборка

Нужны AlmaLinux с systemd, `sudo`, Git, curl и многопользовательский Nix.
На AlmaLinux обычно включён SELinux: выбирайте установщик, который его
поддерживает, например [Determinate Nix Installer](https://github.com/DeterminateSystems/nix-installer).
Обычный upstream `--daemon` перечисляет Linux **без SELinux** в поддерживаемых
конфигурациях ([руководство Nix](https://nix.dev/manual/nix/stable/installation/installing-binary.html)).
Наш установщик SELinux и firewall не перенастраивает.

```sh
sudo dnf install git curl tar
# Если Nix ещё не установлен, изучите параметры выбранного установщика.
curl --proto '=https' --tlsv1.2 -sSfL https://install.determinate.systems/nix -o /tmp/install-nix.sh
sh /tmp/install-nix.sh install
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

## 3. Токены

```sh
sudo /usr/local/sbin/llm-wiki-admin wikisvc token create \
  --name wikiagent --person wikiagent --kind agent --role writer --clearance restricted
sudoedit /etc/llm-wiki/agent.env
# Впишите выданный токен после WIKIAGENT_TOKEN=.

sudo /usr/local/sbin/llm-wiki-admin wikisvc token create \
  --name admin --person your-name --kind human --role admin --clearance restricted
```

Токены выводятся один раз. Человеческий токен сохраните у себя для входа в UI и HTTP API;
в конфигурацию агента он не попадает. У коллег — отдельные human-токены со своим
`person`, обычно role=reviewer. После переноса state.db прежние токены сохраняются;
проверьте `llm-wiki-admin wikisvc token list`, повторно выдавать тот же name нельзя.
Потерянный агентский токен отзовите и выпустите с новым name, сохранив person=wikiagent.

## 4. Gemma 4 31B и llama-server

Нужны GGUF и версия llama.cpp, которая поддерживает именно этот файл и structured
JSON. Бинарник llama-server, его GPU-библиотеки и драйвер устанавливаются отдельно
под оборудование AlmaLinux. Nix bundle вики не включает CUDA или модель.
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
прежний отчёт Gemma 12B не является оценкой 31B. После проверки первой операции
и ревью предложения можно включить `heal.enabled: true` и перезапустить wikiagent.
Окна самолечения используют местное время сервера: проверьте `timedatectl`.

## 5. Доступ и диагностика

Для доступа со своего компьютера достаточно SSH-туннеля:

```sh
ssh -N -L 8789:127.0.0.1:8789 user@alma-host
```

Откройте **http://127.0.0.1:8789** и введите человеческий токен. Все обращения
к wiki и агенту идут через один Go-прокси. UI хранит токен только в сессии вкладки;
собственного доступа к файлам вики и токену агента у службы `llm-ui` нет.
Статика и шрифты встроены в бинарник; Node.js и внешние CDN для запуска не нужны.

Адрес задаётся в `/etc/llm-wiki/ui.env`: `WIKI_UI_BIND=127.0.0.1:8789`.
Там же `WIKI_UI_WIKISVC_URL` и `WIKI_UI_AGENT_URL` — HTTP(S) origins внутренних
API без путей. По умолчанию это loopback:8787 и loopback:8788. Модель остаётся
локальной; UI не хранит её параметры и использует настройки wikiagent.

Для общего сетевого доступа поставьте TLS reverse proxy перед `127.0.0.1:8789`.
Проксируйте `/` целиком, передавайте Authorization, выключите buffering для SSE
и задайте таймаут не ниже таймаута модели. Если загружаете книги, увеличьте лимит
тела у внешнего прокси до настроенного размера книги. UI запускается, даже пока
wikiagent ждёт модель; чтение вики и ручное ревью продолжают работать.

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
отклонённое действие; SELinux целиком выключать не требуется. На целевой AlmaLinux
нужно проверить запуск и права устройств: локальная проверка bundle проводится на NixOS.

## Перенос и резервная копия

GitHub содержит **код**, а данные переносятся отдельно. До копирования остановите
wiki-ui, wikiagent, wikisvc и прочие пишущие клиенты CLI/MCP. Для dev-запуска завершите процессы
в терминалах. Сохраняйте весь wiki, включая `.git`, весь STATE_DIR, весь
WIKIAGENT_STATE_DIR, конфиги и agent.env. Индекс можно пересоздать.

Для уже развёрнутой установки:

```sh
sudo systemctl stop wiki-ui wikiagent wikisvc
sudo install -d -m 0700 /var/backups/llm-wiki
sudo sh -c 'umask 077; tar -C / -czf /var/backups/llm-wiki/data.tar.gz \
  var/lib/llm-wiki/wiki var/lib/llm-wiki/state var/lib/llm-wiki/agent etc/llm-wiki'
sudo systemctl start wikisvc wikiagent wiki-ui
```

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
sudo restorecon -RF /var/lib/llm-wiki /etc/llm-wiki
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

Сначала соберите новую версию, пока старая работает. Затем остановите сервисы,
сделайте согласованную резервную копию и установите готовый bundle:

```sh
git pull --ff-only
nix --extra-experimental-features 'nix-command flakes' build .#deployment --out-link result-deployment
sudo systemctl stop wiki-ui wikiagent wikisvc llm-wiki-model
# Сделайте бэкап по разделу выше, оставив службы остановленными.
sudo ./result-deployment/bin/llm-wiki-install
sudo /usr/local/sbin/llm-wiki-admin wikisvc schema upgrade
sudo /usr/local/sbin/llm-wiki-admin wikisvc reindex --full
sudo /usr/local/sbin/llm-wiki-admin wikisvc lint
sudo systemctl start llm-wiki-model wikisvc wikiagent wiki-ui
sudo /usr/local/sbin/llm-wiki-admin check --model
```

Установщик сохраняет `/etc/llm-wiki`; новые примеры сравнивайте с
`result-deployment/share/llm-wiki/almalinux/`. Units переустанавливаются; местные
изменения делайте в systemd drop-ins. Текущий и предыдущий bundle закреплены
GC roots, удаление checkout или `result-deployment` не ломает службы.

Для отката остановите службы и выполните
`sudo /opt/llm-wiki/previous/bin/llm-wiki-install`: установщик вернёт прежний bundle
и units. Если версия изменила формат данных/схему, до запуска также восстановите
совместимую резервную копию данных и конфигурации. Смена бинарника сама по себе
не откатывает миграции БД.
