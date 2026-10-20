# ADR-0021 — Bi-temporal факты: инвалидация вместо удаления
status: accepted | date: 2026-10-20

## Контекст

Факты стареют: выходят версии, меняются числа, технология заменяется другой. Git даёт transaction-time
(когда изменили запись) бесплатно, а event-time (когда утверждение стало или перестало быть верным в
мире) — нет. Retrieval будет поднимать устаревшее, если его не пометить.

## Решение

- У `fact` — `valid_from` / `valid_to` (event-time) и связь `replaces` / `replaced_by`.
- Непустой `valid_to` или `replaced_by` ⇒ индекс вычисляет эффективный статус `outdated` (STATE-fact), файл не меняется (решение Q-kb-derived-status); страница не удаляется
  (INV-invalidate-not-delete).
- `valid_for` (условие применимости: версия, режим) обязателен для `kind ∈ {number, api, pitfall}` — `ERR-valid_for_missing`.
- В обходе `outdated` получает `f_status` 0.3 (ТЗ §4); хаб перечисляет только актуальные факты —
  `W_HUB_CITES_OUTDATED`; новые ссылки на заменённое — `W_REPLACED_LINKED`; `valid_for` ниже
  `current_version` связанного `tech` — `W_STALE_VERSION`.

## Почему

- knowledge-update — худшая категория всех memory-систем: ≤ 28 % на multi-hop (MemoryAgentBench,
  arXiv:2507.05257; ТЗ §0);
- схема Zep (arXiv:2501.13956): event-time рядом с transaction-time; инвалидация, не удаление — Zep, Mem0g (ТЗ §4);
- сравнение фактов из разных периодов — главный источник ложных противоречий; лечится квалификатором
  `valid_for` (CLAIRE, arXiv:2509.23233; ТЗ §3.1);
- `W_HUB_CITES_OUTDATED` — встроенный компенсатор того, что retrieval поднимет устаревшее (ТЗ §3.2).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| удалять устаревшие факты | ломаются ссылки и цепочка `why`; теряется история «что было верно и когда» |
| только история git | нет event-time; retrieval не может отфильтровать устаревшее |
| `valid_for` необязателен (ревизия 1) | ложные «противоречия» между фактами разных версий (CLAIRE; ТЗ §14) |

## Последствия

- корпус только растёт; выдача обязана учитывать статус — фильтр в `get_brief` и вес в PPR;
- автор факта типов `number/api/pitfall` обязан указать условие применимости — больше работы на ingest;
- затрагивает: STATE-fact, INV-invalidate-not-delete, TERM-bi-temporal, TERM-valid-for, FMT-wikisvc-core.fact,
  FMT-wikisvc-core.relations, ERR-valid_for_missing, CLS-wikisvc-core.Lint, CLS-wikisvc-core.validate_page,
  FLOW-knowledge-brief, FLOW-ask, ADR-0020.
