# Сборка и выкатка

Ветки: работа идёт в `develop`, релиз-кандидат — pull request в `main`, релиз — тег версии на коммите `main`.
Все пайплайны — TOOL-github-actions на `ubuntu-latest`; Nix ставит `cachix/install-nix-action`, сторонние actions
закреплены по SHA (кроме `actions/checkout@v4` в PIPE-wk-check).

## Сборочные цели flake

| цель | выражение | что даёт | где собирается |
|---|---|---|---|
| `packages.default` (= `.#wikisvc`, `.#wikiagent`) | `flake.nix`, `buildPythonApplication` на Python 3.12 | один пакет с CLI `wikisvc` и `wikiagent`; при сборке `ruff check`, `ruff format --check`, `mypy src`, pytest с покрытием | PIPE-ci (`full`), PIPE-release (как часть образа) |
| `.#ui` | `ui/package.nix` | Go-бинарник `wiki-ui` с встроенной SPA (React + Vite) | то же |
| `.#updater` (Linux) | `updater/package.nix` | Go-бинарник `llm-wiki-updater` | PIPE-ci (`full`, через `.#deployment`) |
| `.#deployment` (Linux) | `deploy/package.nix` | хост-часть: `llm-wiki-install`, `llm-wiki-run`, `llm-wiki-admin`, `llm-wiki-model`, `llm-wiki-backup`, ссылка на `llm-wiki-updater`; юниты `deploy/systemd/`, шаблоны `deploy/linux/`; все скрипты проходят `shellcheck` при сборке. Приложения внутри нет | PIPE-ci (`full`); на сервере — оператором |
| `.#image` (Linux) | `deploy/image.nix`, `dockerTools.buildLayeredImage` | RES-container-image: distroless, без shell (rule-deploy-dockertools-distroless) | PIPE-ci (`full`), PIPE-release |
| `checks.default`, `checks.ui`, `checks.deployment` | те же пакеты | сборка с тестами | `nix flake check` |
| `checks.deployment-vm` | `deploy/vm-test.nix` | NixOS-VM с podman: установка, отказ без дайджеста, ограничения контейнеров, остановка, задание бэкапа | `nix flake check` в PIPE-ci (`full`) |
| `checks.updater-vm` | `deploy/vm-update-test.nix` | NixOS-VM с локальным реестром: обновление, откат по несовпавшей версии, права сокета, «только человек-admin» | то же |

Образ в `nix flake check` не входит: метка ревизии меняет его на каждом коммите, проверка — запуск
`scripts/smoke-image.sh`. Входы закреплены `flake.lock` (rule-nix-flake-lock-pinned); devShell — тот же Python и
инструменты (`TOOL-ruff`, `TOOL-just`, `TOOL-go`, `TOOL-npm`, `wk`).

### PIPE-ci — Проверки кода и релиз-кандидата
status: implemented

- changed: 2026-10-20 v3 (planned): гейт качества слоя знаний (ADR-0025, ТЗ §10, §11.11):
  1. Новый джоб `quality` (после `lint`; PR в `develop` и `main`, вручную; триггеры — решение Q-kb-infra-defaults): `nix develop -c pytest -m eval` —
     Recall@8 по `seeds[]` и Recall@20 по `seeds ∪ expanded` на FMT-wikisvc-core.kb-eval, отдельно single/multi
     и ru/en, доля `expansion_used`; падает, если любая метрика ниже базовой линии (NFR-eval-recall-baseline).
  2. Базовая линия — `tests/fixtures/kb-eval-baseline.json` (решение Q-kb-eval-baseline): метрики по срезам, модель
     эмбеддингов и её ревизия, хеш FMT-wikisvc-core.kb-eval; сравнение строгое (≥). Поднимает её человек в PR вместе
     с изменением, которое подняло метрики; понижать нельзя (`rule-test-no-weakening`). Отчёт — OBS-eval-metrics.
  3. GPU и серверов моделей в CI нет: векторы фикстур и вопросов — `tests/fixtures/kb-eval-vectors.<model>.npz` по
     `content_hash`, в git; генерирует их в ENV-dev настоящей моделью `scripts/record_eval_vectors.py` (решение
     Q-kb-eval-ci-embeddings). Расхождение хеша набора и файла векторов — тест падает с подсказкой перегенерировать.
     Подменяется только внешняя граница (`rule-test-mock-only-boundaries`); прогон детерминирован (`rule-test-deterministic-independent`).
  4. `nix develop -c pytest -m perf` — отдельный джоб `perf` с `continue-on-error: true`, результат — артефакт; гейтом не
     является (решение Q-kb-perf-ci-runner). Пороги PPR ≤ 50 ms на 50 000 узлах / 500 000 рёбер с допуском 1e-6
     (NFR-ppr-latency) и индексация быстрее не менее чем в 3 раза (NFR-index-speedup) проверяются локально `just perf`
     (TOOL-just) и на self-hosted раннере, когда он появится; `scripts/benchmark_retrieval.py` — тот же замер вручную.
     RISK-kb-perf-flaky закрыт этим решением.
  5. Сборка пакета (`pytestCheckHook` в `flake.nix`) исключает `-m "eval or perf"`: песочница Nix не должна зависеть
     от времени и записанных векторов; порог покрытия NFR-test-coverage считается без них. Маркеры — TOOL-pytest.
  6. Кэш: новые Python 3.12-пакеты собираются из исходников — RISK-kb-heavy-python-builds (`rule-nix-heavy-build-limits`, ADR-0012).
- trigger: push в `develop`; pull request в `develop` и `main`; вручную (`workflow_dispatch`). Повторный запуск
  на ту же ветку/PR отменяет предыдущий (`concurrency`).
- where: GitHub Actions `.github/workflows/ci.yml`, права `contents: read`, checkout без сохранения токена.
- steps:
  1. `lint` (всегда): `nix flake check --no-build` → `nix develop -c just lint` (ruff, mypy) → `npm ci` UI →
     Prettier → `tsc` → `go vet` и `gofmt` для `ui/` и `updater/` → `shellcheck deploy/*.sh`.
  2. `full` (только PR в `main`, после `lint`): `nix flake check -L` (все пакеты с тестами и обе VM-проверки) →
     `nix build .#image` → `scripts/smoke-image.sh` (rule-deploy-verify-artifact).
  3. `e2e` (только PR в `main`, после `lint`): Playwright против настоящих wikisvc, wikiagent и wiki-ui
     со скриптовой моделью и локальным IdP; Chrome раннера.
- кэш: `nix-community/cache-nix-action`, ключ — хеш `flake.lock`, `flake.nix`, `ui/package.nix`, `deploy/*.nix`,
  отдельно на джоб, с откатом на любой `nix-Linux-…` (ADR-0012).
- artifacts: при падении `e2e` — трассы Playwright (`playwright-traces`, 7d). Образ не публикуется.
- rollback: не применимо.
- secrets: нет (`GITHUB_TOKEN` только на чтение).

### PIPE-release — Публикация образа и релиза
status: implemented

- trigger: push в `main` (мердж PR), тег `v*`, вручную. Параллельные запуски одного ref не отменяются.
- where: GitHub Actions `.github/workflows/release.yml`, джоб `publish`; единственный с правами
  `packages: write`, `id-token: write`, `attestations: write`.
- steps:
  1. Для тега: `scripts/check-release-tag.sh` — формат `vX.Y.Z` или `vX.Y.Z-beta.N`, база совпадает с `version`
     в `pyproject.toml`, коммит есть в `origin/main` (ADR-0013, rule-deploy-release-semver).
  2. `nix build .#image` → `scripts/smoke-image.sh` (запуск как на сервере: не root, read-only корень, без capabilities).
  3. `skopeo copy` в `ghcr.io/badrabbit00/llm-wiki` (EXT-ghcr): всегда `sha-<7>`, плюс имя тега для тега версии
     или `main` для ветки `main`. Логин через stdin.
  4. `actions/attest`: attestation происхождения на дайджест, загружается в реестр.
- artifacts: RES-container-image; дайджест — в сводке запуска. Хост-часть (`.#deployment`) не публикуется:
  оператор собирает её на сервере из checkout нужной версии.
- каналы: SVC-updater предлагает только теги версий; по semver `X.Y.Z-beta.N` < `X.Y.Z`, поэтому бета-канал сам
  переходит на вышедший релиз. `main` и `sha-…` — для проверок, как обновления не предлагаются.
- rollback: FLOW-release-update — SVC-updater перед переключением архивирует данные, после неуспешной проверки
  OBS-wikisvc.health (версия = тег) возвращает прежний дайджест и данные из архива (проверено `checks.updater-vm`).
  Вручную — вернуть `image.env.previous` и, если схема менялась, восстановить копию до обновления
  (`ref/deploy-linux.md`, «Обновление и откат»). Хост-часть — `/opt/llm-wiki/previous/bin/llm-wiki-install`.
- secrets: только автоматический `GITHUB_TOKEN` (имя пользователя — `github.actor`); своих repository secrets нет.

### PIPE-wk-check — Гейт документации
status: implemented

- trigger: любой push и любой pull request.
- where: GitHub Actions `.github/workflows/wk.yml` (меняет только человек), права `contents: read`.
- steps: скачать релиз `wk` `v0.1.0` из `BadRabbit00/wk` через `gh release download` → проверить `sha256sum` и
  `gh attestation verify` → `wk check --strict`. Код выхода 3 (документация чиста, вики недоступна из CI) — успех,
  ошибки документации — провал.
- artifacts: нет.
- rollback: не применимо.
- secrets: `WIKI_TOKEN` (repository secret, токен вики для сверки политик), `GITHUB_TOKEN` (как `GH_TOKEN` для `gh`).

## Выкатка на ENV-prod

Автоматической выкатки из CI нет: сервер ничего не собирает из кода приложения и сам тянет образ (rule-deploy-build-once).

| шаг | как | кто |
|---|---|---|
| хост-часть | `nix build .#deployment` → `sudo result/bin/llm-wiki-install` (службы и updater остановлены; `/etc/llm-wiki` сохраняется) | оператор (ACT-operator) |
| версия служб | SVC-updater: проверка реестра каждые 6h → `cosign verify-attestation` (подпись `release.yml` этого тега) → подтверждение admin в UI → pull, остановка, архив, смена `image.env`, миграции, старт, health, очистка | человек с ROLE-admin |
| версия вручную | `podman pull` → `cosign verify-attestation` → копия данных → новый дайджест в `image.env` → `schema upgrade`, `reindex --full`, `lint` → старт → `curl /api/v1/health` | оператор |
