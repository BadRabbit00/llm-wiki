# updater

### SVC-updater — Демон обновления релизов
status: implemented | kind: worker | lang: LANG-go

- purpose: на хосте проверяет, вышел ли подписанный релиз образа, и по подтверждению администратора-человека ставит его: останавливает службы, архивирует данные, переключает закреплённый digest, мигрирует, проверяет здоровье и при сбое после переключения возвращает данные из архива.
- not responsible for: сборка и публикация образов (`PIPE-release`); установка хост-части (`deploy/install.sh`); запуск самих контейнеров (это `llm-wiki-run`); выдача и проверка токенов (решает wikisvc, updater только спрашивает); отдельный «откат по кнопке» (отката нет, откат — только автоматический внутри неудачного обновления); ночной бэкап (`llm-wiki-backup`).
- path: `updater/`
- manifest: `updater/go.mod` (module `github.com/BadRabbit00/llm-wiki/updater`, go 1.25.0), `go.sum` нет: сторонних зависимостей нет, только стандартная библиотека (`vendorHash = null` в `updater/package.nix`)
- build: TOOL-nix; `nix build .#updater` (`updater/package.nix`, только Linux, `CGO_ENABLED=0`; бинарь переименован в `llm-wiki-updater`, в `PATH` обёртки добавлены skopeo и cosign)
- run: на хосте — systemd-юнит `llm-wiki-updater.service` + сокет `llm-wiki-updater.socket` из `deploy/systemd/`, команда `/opt/llm-wiki/current/bin/llm-wiki-updater serve [флаги]`. Без сокета, выданного systemd (`LISTEN_PID`/`LISTEN_FDS=1`), демон не стартует. Локально отдельно не запускается; вся последовательность проверена VM-тестом `deploy/vm-update-test.nix` (`checks.<system>.updater-vm`)
- test: `cd updater && nix develop -c go test ./...` (тесты: `api_test.go`, `host_test.go`, `updater_test.go`, `version_test.go`); CI: `go vet` и `gofmt` (`PIPE-ci`)
- entrypoints: `updater/main.go` — подкоманда `serve`, единственная
- deps: стандартная библиотека Go; внешние программы на хосте: skopeo, cosign (из пакета), podman, systemctl, GNU tar (из дистрибутива), `llm-wiki-run`

## Что компонент даёт другим

- API: API-updater.* (HTTP поверх unix-сокета `/run/llm-wiki-updater/api.sock`; потребитель — `SVC-wiki-ui`, который проксирует `/updater-api/` администраторам)
- cli: CLI-updater.serve

## Что использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| EXT-ghcr | список тегов (`skopeo list-tags`), digest и метки тега, `podman pull` по digest | проверка пишет `check_error` и убирает предложение; обновление ничего не меняет и завершается `failed` на шаге `pull` |
| Sigstore (проверка cosign, `verify-attestation`) | доказать, что digest собран релизным workflow именно для этого тега | предложение не выдаётся (`check_error`); при обновлении шаг `verify` даёт `failed` до остановки служб |
| API-wikisvc.whoami | узнать, кто держит bearer-токен; права решает wikisvc | любой вызов API получает 503 `ERR-service_unavailable` |
| API-wikisvc.health | поле `version`: после старта должна совпасть с версией тега | шаг `health` не проходит за `health-timeout` → откат |
| OBS-wiki-ui.health | `GET /healthz` wiki-ui после старта | шаг `health` не проходит → откат |
| RES-host | `systemctl` (службы `wikisvc`, `wikiagent`, `wiki-ui`, таймер и задача бэкапа), `podman pull`, `tar`, `llm-wiki-run once maintenance …` | команда с ошибкой — шаг `failed`; после переключения — откат |

EXT-github-releases код не использует: релизы определяются тегами реестра, а не GitHub Releases.

## Данные

- owns: BKT-updater.state-dir, BKT-updater.pre-update-archives (детали — `data.md`)
- store: RES-host (файловая система)
- migrations: свои — нет; во время обновления запускает миграции wikisvc (`wikisvc schema upgrade`, `reindex --full`, `lint`) через `llm-wiki-run`
- reads foreign data: файл закрепления образа `FMT-updater.image-env` (`/etc/llm-wiki/image.env`, его же перезаписывает); данные служб `var/lib/llm-wiki/{wiki,state,agent}` и `etc/llm-wiki` только архивирует и восстанавливает целиком, внутрь не заглядывает

## Устройство

- modules: MOD-updater.main, MOD-updater.api, MOD-updater.config, MOD-updater.host, MOD-updater.updater, MOD-updater.version (детали — `code.md`)
- jobs: JOB-updater.check, JOB-updater.apply (детали — `runtime.md`)
- config: флаги `CFG-updater.*` и сокет systemd `CFG-updater.LISTEN_PID`, `CFG-updater.LISTEN_FDS` (детали — `runtime.md`)
- scenario: FLOW-release-update

## Развёртывание

- runs on: RES-host, ENV-prod
- unit: `llm-wiki-updater.service` (root, `Type=exec`, `StateDirectory=llm-wiki-updater` режим 0700, `UMask=0077`, `Restart=on-failure`, `TimeoutStopSec=60min`, `ProtectHome=yes`, `PrivateTmp=yes`); сокет `llm-wiki-updater.socket` — владелец root, группа `llm-ui`, режим 0660. Root нужен, чтобы останавливать службы, тянуть образы и восстанавливать данные
- scaling: ровно один экземпляр на хост; одновременность внутри процесса исключена флагами `checking`/`applying` (повторный вызов получает 409)
- health: собственного эндпоинта здоровья нет; доступность видна по `GET /v1/status` (API-updater.status) через wiki-ui

## Политики

- rule-deploy-by-digest — образ закрепляется как `репозиторий@sha256:…`, плавающие теги не применяются
- rule-deploy-release-semver — предлагаются только теги `vX.Y.Z` и `vX.Y.Z-beta.N`, остальные игнорируются
- rule-deploy-release-rollback — порядок: остановка, архив (бэкап), смена версии, отдельный шаг миграций, проверка здоровья, откат из архива
- rule-deploy-verify-artifact — подпись проверяется до выдачи предложения и повторно перед остановкой служб; поведение проверено VM-тестом
- rule-deploy-graceful-shutdown — по SIGTERM/SIGINT закрывает API и дожидается идущего обновления
- rule-arch-outgoing-call-resilience — таймаут у каждого внешнего вызова (HTTP-клиент 10s, проверка реестра 2m, ожидание готовности служб по флагам)
- rule-deploy-runtime-hardening — не выполняется для юнита (root, корень не read-only), RISK-updater-root-unit
