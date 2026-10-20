# wikisvc-mcp: данные

SVC-wikisvc-mcp своих таблиц, файлов и кэшей не имеет: все данные читает и пишет через сервисы
LIB-wikisvc-core, описание — в `components/wikisvc-core/data.md`.

changed: 2026-10-20 v3 (planned): своих данных по-прежнему нет. Выданные и открытые инструментами знаний id вместе с идентичностью вызывающего (имя токена, `person`) ядро
пишет в TBL-wikisvc-core.index.delivery_stats через CLS-wikisvc-core.DeliveryQueue (SEC-delivery-stats); кэш брифа
живёт в ядре (CLS-wikisvc-core.Brief).
