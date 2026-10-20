# updater: фоновые задачи и настройки

## Фоновые задачи

### JOB-updater.check — Периодическая проверка релизов
status: implemented | owner: SVC-updater

- trigger: первая проверка через 1m после старта, дальше раз в `check-every` (CFG-updater.check-every, по умолчанию 6h; отсчёт от конца предыдущей проверки); вручную — API-updater.check и API-updater.channel
- does: спрашивает реестр о тегах, выбирает новейший тег канала (CLS-updater.Latest), сверяет digest с `image.env`, проверяет подпись и записывает предложение в `state.json` (CLS-updater.discover). Ничего не устанавливает: установку запускает только человек
- touches: вызывает EXT-ghcr (`skopeo list-tags`, `skopeo inspect`), cosign; пишет BKT-updater.state-dir
- idempotent: да; та же картина, пока реестр не изменился. Ошибка проверки сбрасывает прежнее предложение (тег мог указывать на непроверяемый образ)
- concurrency: не параллельно с другой проверкой или обновлением; занято — плановая проверка молча пропускается (`ErrBusy`)
- timeout / retries: 2m на проверку; повторов нет, следующая попытка через `check-every`; сбой — предупреждение в логе и `check_error` в состоянии
- on failure: алерта нет; причина видна администратору в API-updater.status

### JOB-updater.apply — Установка подтверждённого релиза
status: implemented | owner: SVC-updater

- trigger: API-updater.apply с digest текущего предложения; выполняется отдельной горутиной, клиент получает 202
- does: переводит хост на новый образ по шагам и при сбое после переключения возвращает данные из архива (FLOW-release-update, rule-deploy-release-rollback):

| шаг | что делает | сбой |
|---|---|---|
| `pull` | `podman pull репозиторий@digest` | `failed`, ничего не менялось |
| `verify` | повторная проверка подписи digest для тега | `failed`, ничего не менялось |
| `jobs-before` | `wikiagent jobs`: что агент возобновит | не влияет (старый образ может не знать команду) |
| `stop` | остановить таймер бэкапа, дождаться конца задачи бэкапа, остановить `wiki-ui`, `wikiagent`, `wikisvc` (агент заканчивает ответы и ставит задачи на паузу, это до 11m) | `resume`, затем `failed` |
| `archive` | `tar` данных в BKT-updater.pre-update-archives | `resume`, затем `failed` |
| `switch` | записать новый digest в `image.env`, прежний — в `image.env.previous` | откат |
| `migrate` | `wikisvc schema upgrade`, `wikisvc reindex --full`, `wikisvc lint` через `llm-wiki-run once maintenance` | откат |
| `start` | `systemctl start --no-block` для `wikisvc`, `wikiagent`, `wiki-ui` | откат |
| `health` | wikisvc отвечает и сообщает версию тега; wiki-ui отвечает на `/healthz`; wikiagent активен (последние два — только если до обновления работали) | откат |
| `jobs-after`, `timer`, `prune` | список задач после, возврат таймера бэкапа, чистка старых архивов (оставить 3) | не влияет: операция всё равно `succeeded` |

- touches: RES-host (`systemctl`, `podman`, `tar`, `llm-wiki-run`), EXT-ghcr, API-wikisvc.health, OBS-wiki-ui.health; пишет `image.env`, BKT-updater.pre-update-archives, BKT-updater.state-dir
- idempotent: нет. Защита: за раз идёт одно обновление, digest должен совпадать с предложением. Демон остановился посреди обновления — при следующем старте операция получает `interrupted` с путём архива; продолжить или откатить автоматически он не пытается, службы и данные проверяет человек
- concurrency: один на хост (флаг `applying` в памяти; единственный экземпляр демона обеспечивает юнит)
- rollback: `rollback` останавливает службы, возвращает архив (с ним `image.env` и прежний образ), полностью перестраивает индекс прежним образом, запускает службы и проверяет здоровье с прежней версией; итог `rolled_back` (причина в `error`) или `failed` с обеими ошибками. Данные неудавшегося обновления остаются рядом под именем `….failed-<id>`. Неудача на `pull`, `verify`, `stop`, `archive` откат не запускает: данные ещё не менялись, `resume` лишь возвращает остановленное
- timeout / retries: ожидание конца бэкапа и остановка служб — до `stop-timeout` (15m каждое); `wikisvc` и `wiki-ui` — до `health-timeout` (3m) каждый, `wikiagent` — до `agent-timeout` (12m, он ждёт модель до 10m); опрос каждые 2s; повторов шагов нет
- shutdown: SIGTERM/SIGINT закрывает API (10s) и ждёт конца обновления (rule-deploy-graceful-shutdown); юнит даёт на это `TimeoutStopSec=60min`, потому что остановка посреди обновления оставила бы службы остановленными
- on failure: алерта нет; итог и журнал шагов — в API-updater.status, в логе записи `update started`, `update step failed`, `update finished`

Ожидаемое поведение проверяет VM-тест `deploy/vm-update-test.nix`: подтверждённый релиз ставится, а релиз, чей образ сообщает не ту версию, откатывается из архива. Подпись в тесте заменена заглушкой, настоящую проверку покрывают тесты Go.

## Настройки

Настройки — флаги `serve`; переменных окружения демон не читает, кроме служебных переменных сокета systemd. Значений секретов нет. Единицы времени — формат Go (`6h`, `15m`).

| id | owner | вид | тип | по умолчанию | обязательна | секрет | на что влияет | status |
|---|---|---|---|---|---|---|---|---|
| CFG-updater.repository | SVC-updater | flag | string | `ghcr.io/badrabbit00/llm-wiki` | нет | нет | репозиторий образов; должен совпадать с репозиторием в `image.env` | implemented |
| CFG-updater.identity | SVC-updater | flag | string | `https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/` | нет | нет | префикс идентичности подписанта; тег дополняет его до идентичности, ожидаемой от cosign | implemented |
| CFG-updater.issuer | SVC-updater | flag | string | `https://token.actions.githubusercontent.com` | нет | нет | OIDC-эмитент подписанта | implemented |
| CFG-updater.state-dir | SVC-updater | flag | string | `/var/lib/llm-wiki-updater` | нет | нет | где лежит `state.json` (BKT-updater.state-dir) | implemented |
| CFG-updater.image-file | SVC-updater | flag | string | `/etc/llm-wiki/image.env` | нет | нет | файл закрепления образа (FMT-updater.image-env) | implemented |
| CFG-updater.backup-dir | SVC-updater | flag | string | `/var/backups/llm-wiki` | нет | нет | куда класть архивы перед обновлением | implemented |
| CFG-updater.wiki-url | SVC-updater | flag | string | `http://127.0.0.1:8787` | нет | нет | адрес wikisvc: whoami и версия в health | implemented |
| CFG-updater.ui-url | SVC-updater | flag | string | `http://127.0.0.1:8789` | нет | нет | адрес wiki-ui для `/healthz` | implemented |
| CFG-updater.check-every | SVC-updater | flag | duration | `6h` | нет | нет | интервал плановой проверки (значение ≤ 0 не отвергается, Q-updater-check-every-validation) | implemented |
| CFG-updater.skopeo | SVC-updater | flag | string | `skopeo` | нет | нет | программа для реестра; ищется в `PATH` обёртки пакета | implemented |
| CFG-updater.cosign | SVC-updater | flag | string | `cosign` | нет | нет | программа проверки подписи; в VM-тесте подменена заглушкой | implemented |
| CFG-updater.podman | SVC-updater | flag | string | `/usr/bin/podman` | нет | нет | podman дистрибутива | implemented |
| CFG-updater.systemctl | SVC-updater | flag | string | `/usr/bin/systemctl` | нет | нет | управление службами и таймером | implemented |
| CFG-updater.tar | SVC-updater | flag | string | `/usr/bin/tar` | нет | нет | GNU tar для архива и восстановления | implemented |
| CFG-updater.run | SVC-updater | flag | string | `/opt/llm-wiki/current/bin/llm-wiki-run` | нет | нет | запуск контейнеров для `wikiagent jobs` и миграций | implemented |
| CFG-updater.stop-timeout | SVC-updater | flag | duration | `15m` | нет | нет | предел ожидания конца бэкапа и остановки служб | implemented |
| CFG-updater.health-timeout | SVC-updater | flag | duration | `3m` | нет | нет | предел ожидания wikisvc и wiki-ui после старта | implemented |
| CFG-updater.agent-timeout | SVC-updater | flag | duration | `12m` | нет | нет | предел ожидания wikiagent (он ждёт модель до 10m) | implemented |
| CFG-updater.LISTEN_PID | SVC-updater | env | string | нет | да | нет | задаёт systemd; должен равняться PID демона, иначе отказ запуска | implemented |
| CFG-updater.LISTEN_FDS | SVC-updater | env | string | нет | да | нет | задаёт systemd; должен быть `1` (сокет — fd 3) | implemented |

Переменные сокета демон после чтения удаляет из окружения, чтобы запускаемые им команды не сочли себя активированными сокетом. В установленном юните `PATH` задан дистрибутивным (нужен `gzip` для `tar -z`), `HOME=/var/lib/llm-wiki-updater` (там cosign держит корень доверия Sigstore). В VM-тесте флаги переопределяются drop-in `vm.conf`.
