# ADR-0019 — Граф в памяти: CSR-снимок (`scipy.sparse`) поверх SQLite без графовой БД
status: accepted | date: 2026-10-20

## Контекст

`ask` расширяет семена по графу итерациями Personalized PageRank (ADR-0020), а `neighbors`, `path`,
`impact`, `subgraph` сейчас ходят в SQLite запросами на каждый узел (ТЗ §11.3–11.4). Целевой масштаб —
50 000 узлов и 500 000 рёбер с PPR ≤ 50 ms (NFR-ppr-latency). Граф — производный индекс от git (ADR-0001,
ADR-0002), допуск токена обязан скрывать узлы выше clearance так же, как сейчас `visible_edges`.

## Решение

Графовую БД не вводим. `GraphStore` остаётся поверх SQLite (`edges ∪ soft_edges`), а для обхода держит
снимок в памяти процесса — `scipy.sparse.csr_matrix` и `numpy`-массивы `id ↔ idx`, `type`, `status`,
`sensitivity` (CLS-wikisvc-core.GraphSnapshot). Снимок строится одним проходом
`SELECT src,dst,rel,weight FROM edges UNION soft_edges`, привязан к `meta.generation` и после `accept`/`reindex`
перестраивается лениво при первом запросе. Допуск — булева маска по `sensitivity`, применяется до обхода
(SEC-graph-clearance-mask). `neighbors/path/impact/subgraph` переходят на снимок (BFS по `indptr/indices`,
≤ 500 узлов на BFS — решение Q-kb-wikisvc-defaults). Рядом со снимком — векторы float32, нормированные один раз
при загрузке (косинус = dot, ADR-0018). Мягкие рёбра (`similar`, `co_cited`, `same_hub`) в снимок входят без
предела на узел (решение Q-kb-soft-edges-cap; RISK-kb-soft-edges-blowup принят). Вес ребра в снимке — по
провенансу и статусу узла (ADR-0020).

## Почему

- Kùzu архивирован 2025-10-10; FalkorDB — SSPL; SurrealDB и Memgraph — BSL (ТЗ §0);
- 500 000 рёбер в CSR ≈ 500k × 12 байт + 50k × 4 ≈ 6 MB; одна итерация PPR — один sparse matvec, миллисекунды (ТЗ §5);
- снимок производный и не становится вторым источником правды — как граф в ADR-0002;
- golden-тест `graph-golden.json` проверяет, что маска допуска эквивалентна текущему `visible_edges` (ТЗ §11.4);
- `networkx` не нужен (ТЗ §11.4).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| встраиваемая или внешняя графовая БД (Kùzu, FalkorDB, SurrealDB, Memgraph) | архивирована или несвободная лицензия (ТЗ §0); второй источник правды и синхронизация с git (ADR-0002) |
| обход SQL-запросами, как сейчас | запрос на узел и N+1 (ТЗ §11.3–11.4); итерации PPR по всему графу через SQL не укладываются в NFR-ppr-latency |
| `networkx` | ТЗ §11.4: не нужен при CSR-снимке |
| свой CSR на чистом `numpy` без `scipy` | пришлось бы писать и тестировать свой sparse matvec; согласие на DEP-py-scipy получено (Q-kb-numpy-scipy-consent) |

## Последствия

- две новые зависимости ядра — DEP-py-numpy, DEP-py-scipy; согласие получено (`rule-stack-new-tech-consent`, Q-kb-numpy-scipy-consent);
- мягкие рёбра без предела могут раздуть снимок и PPR на плотных доменах — RISK-kb-soft-edges-blowup (принят), замер — OBS-ppr-latency;
- состояние в памяти процесса: при N репликах у каждой свой снимок — допустимо только при одном узле
  (ADR-0004); `rule-arch-stateless-replicas` — RISK-kb-process-memory-state;
- снимок обязан инвалидироваться по `meta.generation` — устаревший снимок выдаёт неверных соседей;
- затрагивает: CLS-wikisvc-core.GraphSnapshot, CLS-wikisvc-core.GraphStore, CLS-wikisvc-core.ppr,
  TBL-wikisvc-core.index.edges, TBL-wikisvc-core.index.soft_edges, SEC-graph-clearance-mask, NFR-ppr-latency,
  OBS-ppr-latency, RES-host, LIB-wikisvc-core.
