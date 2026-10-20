# ADR-0018 — Эмбеддинги: BGE-M3 через OpenAI-совместимый локальный сервер
status: accepted | date: 2026-10-20

Заменяет ADR-0002 (в части «без эмбеддингов») после принятия; BM25 и граф из ADR-0002 остаются.

## Контекст

ADR-0002 отказался от векторов: корпус был мал, а модель в ядре нарушала бы ADR-0003. В v3 факты
и тела — на английском, запросы часто на русском (ADR-0023); приёмка этапа 2 требует, чтобы русский
запрос находил английский факт (ТЗ §13). Дедупликации и самолечению нужен kNN по `claim` (ADR-0022).
ADR-0003 и граница 4 в `AGENTS.md` запрещают ядру вызывать модели и делать исходящие сетевые запросы.

## Решение

- Одна многоязычная модель эмбеддингов в проде — MDL-bge-m3 (GGUF F16, `--pooling cls`) с первого дня,
  CFG-wikisvc.EMBEDDINGS_ENABLED = true по умолчанию; без адреса сервера сервис не стартует.
- A/B сразу на этапе 2: MDL-multilingual-e5-large (префиксы `query:`/`passage:`, `mean`) и MDL-qwen3-embedding
  (только 0.6B, `last`); 4B/8B не берём. Критерий — Recall@8 на ru→en и доля размеченных дубликатов в kNN top-10
  при пороге 0.80 (ADR-0025). От модели зависят порог kNN, порог `similar` и базовая линия: смена после этапа 2 —
  перекалибровка и полный `reindex --embeddings` (решение Q-kb-mdl-ab-candidates).
- Провайдер — `OpenAICompatibleEmbeddings` (CLS-wikisvc-core.Embeddings, `POST /v1/embeddings`), сервер —
  отдельный процесс `llama-server --embeddings` на `127.0.0.1:18090` без ключа (RES-embeddings-server,
  EXT-embeddings-server). Reranker MDL-bge-reranker-v2-m3 — шаг `ask` в ядре, включён с этапа 2, свой процесс
  (RES-reranker-server).
- Векторы: в TBL-wikisvc-core.index.embeddings — float16 BLOB, `model` + ревизия; в памяти — float32, нормированы
  один раз при загрузке снимка, косинус = dot; хранилище — SQLite (решение Q-kb-vector-store). Пересчёт — по
  `content_hash`; уровень `chunk` при разрастании можно держать только в FTS.
- Self-test до любого прогона: две фиксированные пары, расхождение косинуса > 0.02 — провал (OBS-wikisvc.embeddings-selftest).
- Три уровня векторов (`claim`, `digest`, `chunk`) — в одном пуле семян; слияние с BM25 — RRF k = 60 (ТЗ §7.2).
- Сервер недоступен или self-test не прошёл — `ask` деградирует до BM25 и явных рёбер без dense-prior,
  `degraded: true` (ERR-embeddings_unavailable, `rule-arch-outgoing-call-resilience`).

Отношение к ADR-0003. Модель эмбеддингов — не LLM: энкодер ничего не генерирует, и при фиксированных
файле весов, сборке сервера и pooling ожидается одинаковый вектор на одинаковый текст. Ядро остаётся
детерминированным при фиксированной модели и индексе — так это решение уточняет INV-core-deterministic.
Исходящий HTTP-вызов из ядра — исключение к ADR-0003 и границе 4 `AGENTS.md`, ограниченное loopback
(решение Q-kb-core-outbound-embeddings); формулировку границы правит человек.

## Почему

- ru→en MKQA: BGE-M3 76.2 против 76.8 у mE5-large — ничья, но у BGE-M3 8k контекста и sparse-голова, у
  mE5 — 512 токенов (ТЗ §0); Qwen3-Embedding выше на MTEB-Multilingual (64.33/69.45 против 59.56), но
  ru→en чисел нет — поэтому A/B на своём eval, выбор по Recall@8 (ТЗ §5);
- поиск по всем уровням одним пулом: 73.7 % против ~58 % по одному (RAPTOR, arXiv:2401.18059);
- BM25 остаётся: на полных документах обгоняет BGE-M3 на 13 пунктов (RusBEIR) и страхует точные
  имена; RRF — безопасный дефолт, выпуклая комбинация с λ — после eval (arXiv:2210.11934; ТЗ §7.2);
- пересечение top-k между моделями 0.43–0.54 (arXiv:2509.18869) — модель обязана быть в индексе (ТЗ §5);
- неверный pooling в llama.cpp «fails silently» (косинус ~0.8 вместо ~1.0) — нужен self-test (ТЗ §5);
- llama-server уже в стеке (RES-llama-server): второй экземпляр не добавляет технологию (`rule-stack-one-tool-per-job`).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| оставить ADR-0002 без векторов | русский запрос не находит английский факт; нет kNN для дедупа (ADR-0022) |
| TEI (text-embeddings-inference) | второй сервер инференса в той же роли рядом с llama-server; новая технология (`rule-stack-new-tech-consent`) |
| инференс в процессе ядра (onnxruntime) | рантайм модели внутри ядра; ТЗ §11.11 держит тяжёлый инференс вне ядра |
| внешний SaaS эмбеддингов | в провайдер уходит текст `restricted` страниц — запрещено SEC-embeddings-boundary |
| pgvector | PostgreSQL в проекте нет (ADR-0001); индекс производный — RISK-kb-vectors-in-sqlite |
| две модели в проде | `rule-stack-one-tool-per-job`; несовместимые векторы в одном индексе |

## Последствия

- ядро получает исходящий вызов на loopback с таймаутом и деградацией; клиент — DEP-py-httpx;
- индекс растёт на векторы float16; пересоздание индекса с нуля требует сервера эмбеддингов (RES-index-db);
- GPU хоста делят развёрнутую Gemma (сейчас 12B, MDL-gemma-12b), MDL-bge-m3 и reranker: энкодер на GPU при ≥ 2 GB свободных, иначе CPU
  (решение Q-kb-vram-budget); RISK-kb-vram-contention;
- бит-в-бит воспроизводимость векторов между сборками llama-server и железом не проверена — RISK-kb-embeddings-determinism;
- ревизия и sha256 модели фиксируются при установке (решение Q-kb-mdl-bge-m3);
- затрагивает: INV-core-deterministic, SEC-embeddings-boundary, EXT-embeddings-server, CLS-wikisvc-core.Embeddings,
  TBL-wikisvc-core.index.embeddings, CFG-wikisvc.EMBEDDINGS_URL, CFG-wikisvc.EMBEDDINGS_MODEL,
  CFG-wikisvc.EMBEDDINGS_POOLING, CFG-wikisvc.EMBEDDINGS_DIM, CFG-wikisvc.EMBEDDINGS_ENABLED, CFG-wikisvc.ASK_RERANK_ENABLED,
  CLI-wikisvc-cli.reindex, CLI-wikisvc-cli.embeddings.selftest, ERR-embeddings_unavailable, RES-embeddings-server,
  RES-reranker-server, RES-index-db, MDL-bge-m3, MDL-multilingual-e5-large, MDL-qwen3-embedding, MDL-bge-reranker-v2-m3,
  OBS-wikisvc.embeddings-selftest, ADR-0002, ADR-0003.
