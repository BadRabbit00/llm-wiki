# ADR-0025 — Eval-набор обязателен с этапа 1 и является гейтом CI
status: accepted | date: 2026-10-20

## Контекст

В v3 почти каждая константа — гипотеза: α и dense-prior PPR (ADR-0020), веса рёбер (ТЗ §4), λ слияния,
порог kNN-кандидатов (ADR-0022), модель эмбеддингов (ADR-0018), усечённый SliCK (ADR-0026). Без замера
их нельзя ни выбрать, ни защитить от регресса. CI сейчас гоняет линтер, тесты и сборку (PIPE-ci), но не
меряет качество поиска.

## Решение

- Файл `tests/fixtures/kb-eval.yaml` (FMT-wikisvc-core.kb-eval): 50–100 вопросов с gold id, срезы
  `lang` (ru/en) и `hops` (single/multi); пары для дедупа — `tests/fixtures/kb-pairs.yaml` (100–200 размеченных);
  заводится на этапе 1 по корпусу из 50 рукописных фактов и растёт с каждой книгой (ТЗ §10, §13).
- Метрики: Recall@8 по `seeds[]`, Recall@20 по `seeds ∪ expanded`, отдельно по срезам; доля `expansion_used`
  и доля, где оно подняло recall; для A/B моделей эмбеддингов — доля размеченных дубликатов в kNN top-10 (OBS-eval-metrics).
- Гейт: `pytest -m eval` в джобе `quality` PIPE-ci; метрики строго не ниже базовой линии (NFR-eval-recall-baseline).
- Базовая линия — `tests/fixtures/kb-eval-baseline.json` (метрики по срезам, модель эмбеддингов и ревизия, хеш
  набора); поднимает её человек в PR; понижать нельзя (`rule-test-no-weakening`); решение Q-kb-eval-baseline.
  Для живой вики — `schema/eval/baseline.json` в RES-wiki-repo, замер — CLI-wikisvc-cli.eval.
- В CI нет GPU и серверов моделей: векторы фикстуры и вопросов — `tests/fixtures/kb-eval-vectors.<model>.npz` по
  `content_hash`, в git, генерирует `scripts/record_eval_vectors.py` в ENV-dev настоящей моделью; расхождение хеша
  набора и файла — тест падает с подсказкой (решение Q-kb-eval-ci-embeddings). Подменяется только внешняя граница
  (`rule-test-mock-only-boundaries`), прогон детерминирован. A/B моделей — каждый кандидат со своим файлом векторов.
- `pytest -m perf` (NFR-ppr-latency, NFR-index-speedup, OBS-ppr-latency) — не гейт: отдельный джоб с
  `continue-on-error`, результат — артефакт; пороги проверяются локально `just perf` (решение Q-kb-perf-ci-runner).

## Почему

- без набора α, веса рёбер, пороги и выбор модели эмбеддингов остаются гипотезами навсегда (ТЗ §0, §10);
- структура по GraphRAG-Bench — single/multi hop (ТЗ §10); Recall по id детерминирован и не требует LLM-оценщика;
- приёмка этапов 2 и 4 сформулирована через базовую линию (ТЗ §13);
- записанные векторы делают гейт воспроизводимым: одинаковый вход — одинаковые метрики, без допусков на шум.

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| завести eval позже (этап 2+) | константы этапов 1–2 замерзают без замера (ТЗ §10) |
| ручной прогон без гейта | регресс поиска не ловится до выкладки |
| LLM-оценка качества ответов | недетерминированно и требует модели в CI; Recall по id достаточно для retrieval |
| живой сервер эмбеддингов в CI | нет GPU; CPU-инференс на каждом PR медленный и вносит шум версий сервера |

## Последствия

- смена модели эмбеддингов или текста фикстур требует перегенерации файла векторов в ENV-dev;
- перф-регресс в CI не блокирует PR — его ловит человек по артефакту и `just perf`; RISK-kb-perf-flaky закрыт этим решением;
- сборка пакета (`pytestCheckHook`) исключает `eval` и `perf` (PIPE-ci, TOOL-pytest);
- затрагивает: FMT-wikisvc-core.kb-eval, NFR-eval-recall-baseline, NFR-ppr-latency, NFR-index-speedup, OBS-eval-metrics,
  OBS-ppr-latency, PIPE-ci, TOOL-pytest, TOOL-just, TERM-eval-set, ENV-dev, CLI-wikisvc-cli.eval, ADR-0018, ADR-0020,
  ADR-0022, ADR-0026.
