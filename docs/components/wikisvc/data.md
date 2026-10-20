# wikisvc: данные

SVC-wikisvc не владеет ни таблицами, ни файлами: всё хранилище (RES-state-db, RES-index-db,
RES-wiki-repo и файлы на диске) принадлежит LIB-wikisvc-core — см. `components/wikisvc-core/data.md`
(`TBL-wikisvc-core.*`, `BKT-wikisvc-core.*`).

- Роутеры читают и пишут данные только через службы `Runtime` ядра; исключения с прямым SQL из
  роутера — `API-wikisvc.admin.audit` (таблица аудита), `API-wikisvc.people.list` (справочник людей),
  `API-wikisvc.inbox` (предложения в RES-state-db и только чтение `jobs` в RES-agent-db SVC-wikiagent).
- `API-wikisvc.health` читает `meta.index_commit` из RES-index-db.
- v3 (planned): API-wikisvc.knowledge.* читают TBL-wikisvc-core.index.* (в том числе TBL-wikisvc-core.index.embeddings,
  TBL-wikisvc-core.index.soft_edges, TBL-wikisvc-core.index.node_stats) только через службы ядра; выданные id пишутся
  в TBL-wikisvc-core.index.delivery_stats через CLS-wikisvc-core.DeliveryQueue с идентичностью вызывающего (имя токена или `person`), без текста запросов (SEC-delivery-stats).
  API-wikisvc.knowledge.verdicts и API-wikisvc.knowledge.novelty пишут TBL-wikisvc-core.state.pair_verdicts и
  TBL-wikisvc-core.state.novelty через CLS-wikisvc-core.Verdicts. Своих таблиц у SVC-wikisvc по-прежнему нет; `health.embeddings` — состояние self-test в памяти процесса.
