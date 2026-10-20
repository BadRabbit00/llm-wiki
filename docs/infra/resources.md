# Инфраструктура: ресурсы и окружения

Источники: `deploy/`, `flake.nix`, `README.md`; замысел — `ref/deploy-linux.md` (сверено с `deploy/`).

## Окружения

| id | назначение | где | отличия от prod | status |
|---|---|---|---|---|
| ENV-dev | локальная разработка и тесты | ноутбук разработчика: `nix develop` (shellHook из `flake.nix`), процессы `wikisvc serve`, `wikiagent serve`, `nix run .#ui` без контейнеров | `CFG-wikisvc.WIKI_ROOT` = `../wiki` (соседний каталог), `CFG-wikisvc.STATE_DIR` = `.dev/state`, `CFG-wikisvc.INDEX_DIR` = `.dev/index`, `CFG-wikiagent.WIKIAGENT_STATE_DIR` = `.dev/agent`; без systemd, podman и бэкапа; модель — вручную запущенный `llama-server` с Gemma 12B (`README.md`, раздел «Чат и модели»); UI требует OIDC и в dev, для локального IdP на loopback допустимы `WIKI_UI_OIDC_INSECURE_HTTP=1` и `WIKI_UI_COOKIE_SECURE=0` (`ui/README.md`); браузерные тесты поднимают свой IdP и скриптовую модель (v3 planned: + RES-embeddings-server и RES-reranker-server вручную; там же `scripts/record_eval_vectors.py` пишет `tests/fixtures/kb-eval-vectors.<model>.npz` — решение Q-kb-eval-ci-embeddings) | implemented |
| ENV-prod | боевое: одна вики в доверенной сети | один Linux-хост RES-host (Arch Linux + Nix, не NixOS): службы — контейнеры RES-container-image в rootful podman под systemd, модель — на хосте | — | implemented |

Других окружений (stage, preview) нет. CI-раннеры GitHub Actions — среда пайплайнов (`infra/delivery.md`),
а не окружение выкладки; NixOS-VM из `deploy/vm-test.nix` и `deploy/vm-update-test.nix` изображают ENV-prod в проверках.

## Ресурсы

### RES-host — Linux-хост с podman и systemd
status: implemented

- changed: 2026-10-20 v3 (planned): + юниты `llm-wiki-embeddings.service` (RES-embeddings-server, `127.0.0.1:18090`) и
  `llm-wiki-reranker.service` (RES-reranker-server, `127.0.0.1:18091`) от `llm-model` (решения Q-kb-embeddings-port,
  Q-kb-reranker-placement); четвёртого процесса нет — LLM-судья работает в RES-llama-server. GPU делят развёрнутую
  Gemma (сейчас 12B, MDL-gemma-12b), MDL-bge-m3 и reranker: энкодер на GPU, если после Gemma свободно ≥ 2 GB, иначе CPU (`--n-gpu-layers 0`); `deploy/install.sh` замеряет
  свободную VRAM через `nvidia-smi` (решение Q-kb-vram-budget; RISK-kb-vram-contention остаётся). Файлы моделей —
  `/srv/llm-wiki/models/`, владелец `llm-model`, группа `llm-wiki`, 0750 (решение Q-kb-models-dir); ONNX-файлы судей
  контейнер wikiagent читает только на чтение через группу `llm-wiki` (решение Q-kb-infra-defaults). Память процесса wikisvc растёт на снимок графа (≈ 6 MB на 500 000 рёбер, ТЗ §5, ADR-0019)
  и векторы float32 для косинуса (CLS-wikisvc-core.Embeddings)
- kind: один физический или виртуальный Linux-узел с systemd, rootful podman из дистрибутива (`/usr/bin/podman`), Nix (только для хост-части), GPU для модели. Один узел — следствие INV-single-node (ADR-0004).
- where: ENV-prod. Конкретный адрес хоста в документацию не пишем.
- used by: SVC-wikisvc, SVC-wikiagent, SVC-wiki-ui, SVC-updater, RES-llama-server.
- systemd-юниты (`deploy/systemd/`, ставит `deploy/install.sh`):

| юнит | что запускает | пользователь |
|---|---|---|
| `wikisvc.service` | контейнер `wikisvc serve` через `llm-wiki-run daemon wikisvc` | `llm-wiki` |
| `wikiagent.service` | контейнер `wikiagent serve`; до старта `wikiagent check --wait 600 --dependencies-only` | `llm-wiki` |
| `wiki-ui.service` | контейнер `wiki-ui` | `llm-ui` |
| `llm-wiki-model.service` | `llm-wiki-model` → `llama-server` на хосте (RES-llama-server) | `llm-model` |
| `llm-wiki-updater.service` + `.socket` | `llm-wiki-updater serve`, сокет `/run/llm-wiki-updater/api.sock` (`root:llm-ui 0660`) | root |
| `llm-wiki-backup.service` + `.timer` | `llm-wiki-backup`, ежедневно 23:00 по местному времени сервера | root |

- каталоги: `/opt/llm-wiki/current` и `/opt/llm-wiki/previous` (хост-часть, постоянные GC roots в
  `/nix/var/nix/gcroots/llm-wiki`), `/etc/llm-wiki/` (конфигурация), `/var/lib/llm-wiki/{wiki,state,index,agent}`
  (данные, `llm-wiki`, 0700), `/var/backups/llm-wiki/` (копии, root, 0700), `/srv/llm-wiki/models/` (GGUF),
  `/var/lib/llm-wiki-updater/` (состояние updater).
- access: службы слушают только loopback (`--network host`, адреса `127.0.0.1`): wikisvc 8787, wikiagent 8788,
  wiki-ui 8789, модель 18089. Доступ снаружи — SSH-туннель или TLS-прокси (не входит в репозиторий).
  Админ-доступ — `sudo` на хосте; обслуживание — `llm-wiki-admin` (одноразовый контейнер профиля `maintenance`).
- секреты (только пути; права `root:<группа службы> 0640`, значения вносит человек — rule-secrets-prod-values-by-human):
  `/etc/llm-wiki/agent.env` (`CFG-wikiagent.WIKIAGENT_TOKEN`), `/etc/llm-wiki/ui-oidc.secret`,
  `/etc/llm-wiki/ui-session.token`. Несекретные: `service.env`, `wikiagent.yaml`, `llama.env`, `ui.env`,
  `backup.env`, `roles.yaml`, `image.env` (дайджест образа, 0644). В репозитории — только шаблоны в `deploy/linux/`
  с пустыми значениями секретов (rule-secrets-never-in-artifacts).
- hardening контейнеров (`deploy/run.sh`, одно место для юнитов, `llm-wiki-admin` и updater): свой uid, `--read-only`,
  `--tmpfs /tmp`, `--cap-drop ALL`, `no-new-privileges`, `--pull never`, `--init`; wikiagent видит `/var/lib/llm-wiki`
  только на чтение, кроме `agent/` (rule-deploy-runtime-hardening).
- backup: не бэкапится как целое; данные — см. RES-wiki-repo, RES-state-db, RES-agent-db.
- managed by: хост-часть — Nix (`deploy/package.nix`, цель `.#deployment`) и `deploy/install.sh` (пользователи,
  каталоги, юниты, шаблоны конфигурации, GC roots); ОС, podman, Nix, драйвер GPU, TLS-прокси и включение
  юнитов/таймера — руками по `ref/deploy-linux.md` (RISK в отчёте infra-агента).

### RES-container-image — Образ релиза `ghcr.io/badrabbit00/llm-wiki`
status: implemented

- changed: 2026-10-20 v3 (planned): closure Python-пакета += DEP-py-numpy, DEP-py-scipy, DEP-py-onnxruntime,
  DEP-py-tokenizers (согласие получено: Q-kb-numpy-scipy-consent, Q-kb-onnxruntime-consent); файлы моделей и `llama-server`
  в образ не входят (ADR-0011); ONNX-файлы судей (MDL-nli-judge, MDL-grounding-judge) wikiagent читает из
  `/srv/llm-wiki/models/` томом только на чтение; каталог `llm-model:llm-wiki` 0750, доступ контейнера — через группу
  `llm-wiki` (решение Q-kb-infra-defaults, Q-kb-models-dir)
- kind: OCI-образ в реестре EXT-ghcr, один на три службы (ADR-0011): closures `wikisvc`/`wikiagent` (один Python-пакет),
  `wiki-ui`, `git`, `cacert`, `fakeNss`; без shell и пакетного менеджера. Пользователь по умолчанию `65534:65534`,
  рабочий каталог `/var/lib/llm-wiki`, метки OCI `source`, `revision`, `version`.
- сборка: `deploy/image.nix` (`dockerTools.buildLayeredImage`, rule-deploy-dockertools-distroless), цель `.#image`.
- теги: `vX.Y.Z` (релиз), `vX.Y.Z-beta.N` (бета), `main` (последний мердж), `sha-<7>` (сборка). Публикует PIPE-release,
  на каждый дайджест — attestation происхождения (SLSA provenance).
- where: ENV-prod тянет образ только по дайджесту: `LLM_WIKI_IMAGE=…@sha256:…` в `/etc/llm-wiki/image.env`;
  `deploy/run.sh` отказывается стартовать без дайджеста (rule-deploy-by-digest). ENV-dev образ не использует.
- used by: SVC-wikisvc, SVC-wikiagent, SVC-wiki-ui (контейнеры), SVC-updater (pull, проверка `cosign verify-attestation`, переключение).
- access: пакет публичный, `podman pull` без токена; запись — только у PIPE-release через `GITHUB_TOKEN`.
- backup: не нужен — воспроизводится из тега; предыдущий образ остаётся в хранилище podman для отката.
- managed by: PIPE-release (публикация), SVC-updater или оператор (`image.env`).

### RES-wiki-repo — Git-репозиторий контента
status: implemented

- kind: каталог с git-репозиторием (ветка `main`, worktrees предложений), источник правды вики (ADR-0001);
  формат и содержимое — BKT-wikisvc-core.wiki-repo, BKT-wikisvc-core.worktrees.
- where: ENV-dev — `../wiki` рядом с checkout; ENV-prod — `/var/lib/llm-wiki/wiki` (по умолчанию в `service.env`).
- used by: SVC-wikisvc (запись под `write.lock`), SVC-wikisvc-cli, SVC-wikiagent (только чтение в ENV-prod: том `:ro`).
- access: CFG-wikisvc.WIKI_ROOT; создаётся `wikisvc init`; ручной `git` — `llm-wiki-admin git …`.
- backup: ENV-prod — целиком с `.git` в ежедневном архиве `llm-wiki-backup` (службы остановлены), хранение
  `BACKUP_KEEP_DAYS` (по умолчанию 14d); перед обновлением — архив SVC-updater (последние 3). Восстановление
  проверяется вручную по `ref/deploy-linux.md` («Обязательная проверка восстановления»). ENV-dev — не бэкапится.
- managed by: SVC-wikisvc; каталог создаёт `deploy/install.sh`.

### RES-state-db — База состояния `state.db`
status: implemented

- kind: SQLite-файл `$STATE_DIR/state.db` (WAL) вместо PostgreSQL (ADR-0001): токены (хеши), предложения, сессии,
  аудит, находки, счётчики; таблицы — `TBL-wikisvc-core.state.*`. Рядом в `STATE_DIR` — worktrees,
  BKT-wikisvc-core.library и BKT-wikisvc-core.extract: это данные для бэкапа, а не расходный кэш.
- версия схемы: `PRAGMA user_version` (`src/wikisvc/storage/db_version.py`, `STATE_SCHEMA`); база новее кода — отказ ERR-schema_newer (ADR-0016).
- where: ENV-dev — `.dev/state/`; ENV-prod — `/var/lib/llm-wiki/state/`.
- used by: SVC-wikisvc, SVC-wikisvc-cli, SVC-wikisvc-mcp; SVC-wikiagent читает её только для проверки
  выпускающего токена (`src/wikiagent/auth_check.py`).
- access: CFG-wikisvc.STATE_DIR; один писатель (INV-single-node).
- backup: каталог `state/` целиком в архиве `llm-wiki-backup` и в архиве перед обновлением; только на остановленных
  службах (`ExecStartPre` останавливает `wiki-ui`, `wikiagent`, `wikisvc`).
- managed by: SVC-wikisvc (создание и миграции при старте); каталог — `deploy/install.sh`.

### RES-index-db — Поисковый индекс `wiki.db`
status: implemented

- changed: 2026-10-20 v3 (planned): новые таблицы TBL-wikisvc-core.index.embeddings, TBL-wikisvc-core.index.soft_edges,
  TBL-wikisvc-core.index.node_stats, TBL-wikisvc-core.index.page_meta, TBL-wikisvc-core.index.facts_fts; у
  TBL-wikisvc-core.index.edges — `weight`, `note`, `origin`; `INDEX_SCHEMA` 1 → 2 (ADR-0016: `reindex --full`).
  Размер растёт на векторы float16: число векторов (факты, хабы, разделы) × 1024 (CFG-wikisvc.EMBEDDINGS_DIM) × 2 байта
  (решение Q-kb-vector-store); уровень `chunk` при разрастании можно не векторизовать. Векторы пересчитываются
  инкрементально по `content_hash`; `reindex --full` сохраняет векторы с тем же хешем и моделью; смена модели — полный
  `reindex --embeddings` (ADR-0018). Пересоздание индекса с нуля требует RES-embeddings-server и длится дольше на
  пересчёт всех векторов. Векторы в SQLite, а не pgvector — RISK-kb-vectors-in-sqlite
- kind: SQLite-файл `$INDEX_DIR/wiki.db` с FTS5; производный от RES-wiki-repo (`TBL-wikisvc-core.index.*`).
- версия схемы: `INDEX_SCHEMA` в `src/wikisvc/storage/db_version.py`; индекс новее кода `wikisvc reindex --full` выбрасывает и собирает заново.
- where: ENV-dev — `.dev/index/`; ENV-prod — `/var/lib/llm-wiki/index/`.
- used by: SVC-wikisvc, SVC-wikisvc-mcp, SVC-wikisvc-cli.
- access: CFG-wikisvc.INDEX_DIR (вне `WIKI_ROOT` и не равен `STATE_DIR`).
- backup: не бэкапится; восстановление — `wikisvc reindex --full`. При восстановлении из копии теряется
  TBL-wikisvc-core.index.delivery_stats (полный reindex её сохраняет, пересоздание индекса — нет).
- managed by: SVC-wikisvc (переиндексация при старте и после записи).

### RES-agent-db — База агента `agent.db`
status: implemented

- kind: SQLite-файл `$WIKIAGENT_STATE_DIR/agent.db`: задачи, чекпоинты, чат-сессии, учёт вызовов модели
  (`TBL-wikiagent.agent.*`); версия схемы — `AGENT_SCHEMA` в `src/wikisvc/storage/db_version.py`.
- where: ENV-dev — `.dev/agent/`; ENV-prod — `/var/lib/llm-wiki/agent/` (единственный каталог, куда пишет wikiagent).
- used by: SVC-wikiagent (запись); SVC-wikisvc читает только на чтение (`mode=ro`) сводку задач для очереди ревью.
- access: CFG-wikiagent.WIKIAGENT_STATE_DIR.
- backup: каталог `agent/` в архиве `llm-wiki-backup` и в архиве перед обновлением.
- managed by: SVC-wikiagent; каталог — `deploy/install.sh`.

### RES-llama-server — Локальный сервер модели
status: implemented

- changed: 2026-10-20 v3 (planned): больше вызовов — извлечение фактов окнами (ADR-0027), novelty ≈ 11 вызовов на факт,
  ≤ 2000 в сутки (ADR-0026, CFG-wikiagent.novelty.max_calls_per_day); тот же бинарник запускает
  RES-embeddings-server и RES-reranker-server отдельными процессами; эмбеддинги и reranker в этот процесс не
  добавляются — один процесс = одна модель (решение Q-kb-vram-budget, Q-kb-reranker-placement); этот же процесс — LLM-судья
  каскада дедупа (PRM-wikiagent.fact_judge, ADR-0022), отдельного процесса нет (решение Q-kb-judge-llm-server);
  фактически отдаёт развёрнутую Gemma 4 12B (MDL-gemma-12b) под алиасом `wiki-gemma-31b`, 31B не развёрнута,
  возможная замена — 27B (со слов владельца); в процесс идут тексты фактов и книг — те же требования, что у
  RES-embeddings-server: логи без тел запросов и промптов, служебные эндпоинты (`/slots`, `/props`, `/metrics`)
  отключены или недоступны соседям — флаги по установленной версии, **проверить** (RISK-kb-embeddings-server-logs)
- kind: процесс `llama-server` (llama.cpp) на хосте, OpenAI-совместимый API — реализация EXT-llm-server;
  отдаёт модель MDL-wiki-gemma-31b под alias `wiki-gemma-31b`. В образ не входит (ADR-0011).
- where: ENV-prod — `llm-wiki-model.service` на RES-host, `127.0.0.1:18089`, контекст 16384, 1 слот
  (`deploy/linux/llama.env`); GGUF в `/srv/llm-wiki/models/`; GPU — пользователь `llm-model` в группах `video`/`render`,
  драйвер и GPU-библиотеки хоста, `LLAMA_ARG_N_GPU_LAYERS=auto`. ENV-dev — `llama-server`, запущенный вручную.
- used by: SVC-wikiagent (роли `planner`, `reviewer`, `chat` — CFG-wikiagent.models.planner и соседние поля `wikiagent.yaml`).
- access: без токена, только loopback; `/etc/llm-wiki/llama.env` (`LLAMA_SERVER_BIN`, `LLAMA_ARG_MODEL`, `LLAMA_ARG_*`).
  Проверка — `llm-wiki-admin check --model`.
- backup: не нужен; GGUF не входит ни в git, ни в Nix store, ни в архив.
- managed by: юнит и обёртка `deploy/model.sh` — Nix (`.#deployment`); бинарник llama.cpp, GPU-драйвер и GGUF — руками
  (RISK в отчёте infra-агента).

### RES-embeddings-server — Локальный сервер эмбеддингов
status: planned

- kind: второй процесс `llama-server` на хосте — тот же бинарник, что у RES-llama-server (`LLAMA_SERVER_BIN`), с
  `--embeddings --pooling cls` и моделью MDL-bge-m3 (GGUF F16); OpenAI-совместимый `POST /v1/embeddings` — реализация
  EXT-embeddings-server (ADR-0018). Один процесс — одна модель; TEI не используется (`rule-stack-one-tool-per-job`).
- where (решение Q-kb-embeddings-port): ENV-prod — юнит `llm-wiki-embeddings.service` от `llm-model`, конфигурация
  `/etc/llm-wiki/embeddings.env` по образцу `llama.env`, GGUF в `/srv/llm-wiki/models/` (решение Q-kb-models-dir), `127.0.0.1:18090`.
  ENV-dev — запуск вручную, как `llama-server` с Gemma 12B; без него сервис не стартует, пока
  CFG-wikisvc.EMBEDDINGS_ENABLED = true (по умолчанию; решение Q-kb-core-outbound-embeddings).
- hardware (решение Q-kb-vram-budget): GPU, если после развёрнутой Gemma (сейчас 12B) свободно ≥ 2 GB, иначе CPU
  `--n-gpu-layers 0` (медленнее, допустимо для индексации); замер — `nvidia-smi` в `deploy/install.sh`; RISK-kb-vram-contention.
- used by: SVC-wikisvc и SVC-wikisvc-cli через CLS-wikisvc-core.Embeddings (индексация трёх уровней, вектор запроса
  `ask`, `reindex --embeddings`, `embeddings selftest`). SVC-wikiagent напрямую не ходит: kNN по `claim`-векторам —
  через API SVC-wikisvc (решение Q-kb-knn-endpoint).
- data: тексты `claim`, `digest` и разделов всех страниц, включая `restricted`, и тексты запросов —
  SEC-embeddings-boundary; поэтому только локальный процесс на loopback, внешние провайдеры запрещены.
- access: без токена (решение Q-kb-embeddings-api-key), только `127.0.0.1`; адрес и модель — CFG-wikisvc.EMBEDDINGS_URL,
  CFG-wikisvc.EMBEDDINGS_MODEL, CFG-wikisvc.EMBEDDINGS_POOLING, CFG-wikisvc.EMBEDDINGS_DIM.
- security (draft, `rule-deploy-runtime-hardening`):
  - слушает только `127.0.0.1` (`LLAMA_ARG_HOST`), не `0.0.0.0`;
  - пользователь `llm-model` без доступа к данным вики (`/var/lib/llm-wiki/{wiki,state,index,agent}` — `llm-wiki`, 0700);
    тексты приходят только в запросах; модели — вне каталога данных, в `/srv/llm-wiki/models/` (`llm-model:llm-wiki`, 0750;
    решение Q-kb-models-dir);
  - юнит с тем же hardening, что `llm-wiki-model.service`: `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`,
    `PrivateTmp`, `UMask=0077`, запись только в свой каталог кэша;
  - логи без тел запросов и векторов: тексты `restricted` не должны попадать в journald (SEC-embeddings-boundary) —
    уровень логирования и флаги llama-server выбрать по установленной версии, **проверить**;
  - служебные эндпоинты llama-server (`/slots`, `/props`, `/metrics`) отключены или недоступны другим процессам
    хоста — конкретные флаги по установленной версии, **проверить**; RISK-kb-embeddings-server-logs.
- failure: недоступен или self-test не прошёл (расхождение > 0.02, решение Q-kb-embeddings-selftest) —
  ERR-embeddings_unavailable, `ask` работает по BM25 и явным рёбрам с `degraded: true`, health — `embeddings: failed`
  при `status: ok` (`rule-arch-outgoing-call-resilience`); OBS-wikisvc.embeddings-selftest.
- backup: не нужен; GGUF не входит ни в git, ни в Nix store, ни в архив. Смена файла модели — полный
  `reindex --embeddings` (ADR-0018).
- managed by: юнит и обёртка — Nix (`.#deployment`, по образцу `deploy/model.sh` и `llm-wiki-model.service`),
  `deploy/install.sh`, `checks.deployment-vm`; все варианты выкладки меняются вместе (`rule-deploy-keep-variants-in-sync`).
  Бинарник и GGUF — руками (RISK-host-manual-setup). Процесс на хосте, а не в контейнере — RISK-kb-embeddings-host-not-container
  (`rule-stack-llm-providers`).

### RES-reranker-server — Локальный сервер reranker
status: planned

- kind: третий процесс `llama-server` с `--reranking` и моделью MDL-bge-reranker-v2-m3; шаг 4 `ask` в ядре включён с
  этапа 2 (CFG-wikisvc.ASK_RERANK_ENABLED = true, CFG-wikisvc.RERANKER_URL, CFG-wikisvc.RERANKER_MODEL; решение
  Q-kb-reranker-placement).
- where: ENV-prod — юнит `llm-wiki-reranker.service` от `llm-model`, `127.0.0.1:18091`, GGUF в `/srv/llm-wiki/models/`;
  конфигурация — по образцу `embeddings.env` (`/etc/llm-wiki/reranker.env`, решение Q-kb-infra-defaults). ENV-dev — вручную или флаг выключен.
- hardware, security, access, backup, managed by: как у RES-embeddings-server — та же политика GPU/CPU (решение
  Q-kb-vram-budget), loopback без токена, hardening юнита, логи без тел запросов, служебные эндпоинты закрыты
  (**проверить**, RISK-kb-embeddings-server-logs), каталог моделей — `/srv/llm-wiki/models/` (решение Q-kb-models-dir).
- used by: SVC-wikisvc (CLS-wikisvc-core.Ask).
- data: `claim`/`summary` кандидатов `expanded[]` и текст запроса — SEC-embeddings-boundary.
- failure: недоступен — `ask` без шага reranker (порядок по PPR), не ошибка запроса (`rule-arch-outgoing-call-resilience`; решение Q-kb-infra-defaults).
