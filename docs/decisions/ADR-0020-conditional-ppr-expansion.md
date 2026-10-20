# ADR-0020 — Условное расширение по графу: PPR α = 0.5 с остановом по допуску
status: accepted | date: 2026-10-20

## Контекст

`ask` (FLOW-ask) находит семена гибридным поиском и может добрать связанные факты по графу: факт про
doc-комментарии лексически не связан с запросом про именование функций, но связан ребром
`applies_with` (ТЗ §7.2). Ревизия 1 ТЗ расширяла всегда, PPR с α = 0.15 и 20 итерациями (ТЗ §14).

## Решение

- Расширение **условное**, без LLM: пропускаем PPR и отдаём семена L1 с их хабами, если top-1 отрывается
  от top-2 по score в ≥ 1.5 раза и все семена из ≤ 2 хабов; расширяем, если семена размазаны по ≥ 3 хабам
  или top-1 слаб; семян меньше 3 — fallback на чистый гибридный поиск (ТЗ §7.2). Отрыв ×1.5 и «слабый top-1»
  (< 0.5) считаются по нормированным сырым score max(BM25/BM25max, cos); RRF — только для слияния
  (решение Q-kb-expansion-score).
- Personalized PageRank, α = 0.5, останов по допуску ‖Δπ‖₁ < 1e-6, предел — 100 итераций
  (решение Q-kb-core-defaults).
- Reset-вектор: семена с весом `score · s(v)` (specificity из TBL-wikisvc-core.index.node_stats — по явным рёбрам
  in+out, включая обратные, без soft_edges) плюс все узлы с весом 0.05 · cos(q, v) — dense-prior; без
  эмбеддингов dense-prior не используется.
- Белый список рёбер: `applies_with`, `about`/`has_fact`, `same_hub`, `refines`, `supports`, `contradicts`,
  `precedes`, `grounded_in`, `similar`; `covers` в него не входит. Вес ребра `base · override · f_origin · f_status ·
  f_usage` (ТЗ §4): `w` ребра заменяет базовый вес; `f_origin` — manual 1.0 / extracted 0.8 / inferred 0.6;
  `f_status` — verified 1.2 / draft 1.0 / outdated 0.3, отдельного штрафа за `draft`-узел нет; `f_usage` = 1.0
  (решение Q-kb-core-defaults, Q-kb-edge-weight-override).
- `expanded[]` — не больше 20 минус число семян; бюджет токенов приоритетнее.
- Константы — стартовые значения, тюнятся на eval (ADR-0025), а не фиксируются архитектурно.

## Почему

- три независимых сравнения 2025: граф даёт +10…+23 на multi-hop и 0 или минус на single-hop
  (GraphRAG-Bench, arXiv:2506.05690; RAG vs GraphRAG, arXiv:2502.11371; VLDB, arXiv:2503.04338; ТЗ §0);
- средняя длина прогулки (1−α)/α — один шаг при 0.5 и 5.7 при 0.15: в вики с хабами на 60 фактов масса
  за шесть шагов растекается по половине домена (ТЗ §7.2);
- остаток после k итераций ≤ (1−α)^k: при 0.5 и 20 итерациях 1e-6, при 0.15 — 0.039 (ТЗ §7.2, §14);
- dense-prior 0.05 и specificity — из HippoRAG 2 и HippoRAG (arXiv:2502.14802, arXiv:2405.14831): кривая
  по коэффициенту плоская, оптимум 0.05; без specificity −4.2 R@2 на HotpotQA (ТЗ §5, §7.2);
- у HippoRAG 2 18 % провалов были «фильтр не оставил ничего» — отсюда fallback (ТЗ §7.2);
- per-type весов и whitelist не абляционировала ни одна работа — веса честно гипотезы (ТЗ §4).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| расширять всегда (ревизия 1) | на single-hop граф даёт 0 или минус (ТЗ §0) |
| α = 0.15, 20 итераций (ревизия 1) | остаток 4 %, масса растекается по домену (ТЗ §14) |
| решать о расширении моделью | ядро без LLM (ADR-0003); недетерминированно |
| без графа, только гибридный поиск | теряются multi-hop связи (`applies_with`) — смысл слоя знаний |

## Последствия

- `ask` отдаёт `expansion_used`; eval проверяет, что расширение включается только на multi-hop (ТЗ §13), — OBS-eval-metrics;
- константы — настройки, а не код; их значения — RISK-kb-untuned-constants до первых замеров;
- затрагивает: FLOW-ask, CLS-wikisvc-core.Ask, CLS-wikisvc-core.ppr, CLS-wikisvc-core.Assemble, DTO-wikisvc-core.AskResult,
  TBL-wikisvc-core.index.node_stats, TBL-wikisvc-core.index.soft_edges, CFG-wikisvc.PPR_ALPHA, CFG-wikisvc.PPR_TOL,
  CFG-wikisvc.PPR_DENSE_PRIOR, CFG-wikisvc.ASK_SEEDS, CFG-wikisvc.ASK_EXPANSION_RATIO, CFG-wikisvc.ASK_EXPANSION_MIN_HUBS,
  CFG-wikisvc.SIMILAR_THRESHOLD, NFR-ppr-latency, TERM-ppr, TERM-seed, TERM-expansion, TERM-specificity, ADR-0019.
