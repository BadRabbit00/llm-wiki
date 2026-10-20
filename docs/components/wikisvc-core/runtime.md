# wikisvc-core: фоновые задачи и настройки

## Фоновые задачи

### JOB-wikisvc-core.extract-worker — Извлечение текста из документа в изолированном процессе
status: implemented | owner: LIB-wikisvc-core

- trigger: очередь в памяти — `Extractions.start` (вызов API SVC-wikisvc на загруженном сырье) и `Extractions.recover` при старте SVC-wikisvc (строки `pending`/`running` ставятся в очередь заново); исполнитель — `ThreadPoolExecutor` на 2 потока внутри процесса SVC-wikisvc
- does: поток CLS-wikisvc-core.Extractions пачками по 15 страниц запускает `python -m wikisvc.services.extract_worker <файл> <MB> <символы> <секунды> --pages <старт> 15`; рабочий процесс до импорта парсеров ставит лимиты и вызывает CLS-wikisvc-core.document_pages; результат — BKT-wikisvc-core.extract и строка TBL-wikisvc-core.state.extractions
- limits рабочего процесса: `RLIMIT_AS` = CFG-wikisvc.EXTRACT_MEMORY_MB, `RLIMIT_CPU` = CFG-wikisvc.EXTRACT_TIMEOUT_SECONDS, `RLIMIT_FSIZE` 1 MiB, `RLIMIT_NOFILE` 64; ответ ≤ CFG-wikisvc.EXTRACT_MAX_CHARS; `stdin` закрыт, рабочий каталог — временный, окружение без `LOCALE_ARCHIVE*`, `LC_ALL=C.UTF-8`, `PYTHONPATH` = `sys.path` родителя
- limits задачи: вся задача ≤ CFG-wikisvc.EXTRACT_JOB_TIMEOUT, текст ≤ CFG-wikisvc.EXTRACT_JOB_MAX_CHARS, ≤ 50000 страниц
- touches: читает BKT-wikisvc-core.wiki-repo (`raw/`) или BKT-wikisvc-core.library, TBL-wikisvc-core.index.raw_files; пишет TBL-wikisvc-core.state.extractions, BKT-wikisvc-core.extract
- idempotent: да — готовые пачки берутся из кэша по SHA-256 файла; `done`/`failed` с тем же хешем не перезапускаются без `retry`
- concurrency: один путь — одна задача (множество `active` под `threading.Lock`); не больше 2 одновременно на процесс; кроме этого процесса никто задачи не исполняет
- exit codes рабочего процесса: `0` — ок; `2` — нет парсера (ERR-extractor_unavailable); `3` — документ отклонён или превышен лимит символов (ERR-text_invalid); `4` — исчерпана память (ERR-text_limit); таймаут → ERR-extract_timeout; без текстового слоя → ERR-no_text_layer (OCR нет)
- on failure: статус `failed` с кодом ошибки в `error`; в лог (OBS-logs) — путь, код возврата и только имя класса исключения, без текста документа
- implements: INV-untrusted-external, FLOW-ingest-book (шаг извлечения)

### JOB-wikisvc-core.embed-index — Инкрементальный пересчёт векторов
status: planned | owner: LIB-wikisvc-core

- why separate: сетевой вызов EXT-embeddings-server не должен идти внутри транзакции индекса и под CLS-wikisvc-core.write_lock (rule-arch-transactions-in-service); до пересчёта новые страницы находятся только BM25-веткой
- trigger: после каждой успешной перестройки индекса (`Runtime.reindex`, `sync_index`) и при старте — очередь в памяти, один поток внутри процесса SVC-wikisvc; CLI-wikisvc-cli.reindex `--embeddings` выполняет то же синхронно (полный пересчёт) — кодирование вне CLS-wikisvc-core.write_lock, под блокировкой пишутся только строки с неизменившимся `content_hash` (решение Q-kb-cli-reindex-embeddings)
- does: для страниц, у которых `content_hash` текста уровня (`claim`, `digest`, `chunk`) отличается от TBL-wikisvc-core.index.embeddings или `model` ≠ CFG-wikisvc.EMBEDDINGS_MODEL, кодирует текст пачками через CLS-wikisvc-core.Embeddings (размер пачки кодирования — константа кода, RISK-kb-untuned-constants; запись — `executemany` по 1000 строк, решение Q-kb-core-defaults), пишет векторы; затем пересчитывает `similar` в TBL-wikisvc-core.index.soft_edges для изменённых `claim`-векторов против всех (O(изменённые × N)) и увеличивает версию векторов в TBL-wikisvc-core.index.meta
- touches: читает TBL-wikisvc-core.index.pages, TBL-wikisvc-core.index.chunks; пишет TBL-wikisvc-core.index.embeddings, TBL-wikisvc-core.index.soft_edges, TBL-wikisvc-core.index.meta
- idempotent: да — повтор пересчитывает только несовпавшие `content_hash`; запись пачки — одна короткая транзакция
- concurrency: один исполнитель — процесс SVC-wikisvc (rule-arch-single-scheduler); SVC-wikisvc-mcp в режиме stdio и CLI (кроме CLI-wikisvc-cli.reindex с `--embeddings`) векторы только читают, переиндексация при старте stdio-MCP идёт без эмбеддингов; векторы пишут только этот JOB и `reindex --embeddings` (решение координатора 2026-10-20); новая перестройка индекса во время прогона ставит повтор в очередь, а не второй поток
- on failure: провайдер недоступен или self-test не прошёл → ERR-embeddings_unavailable в лог (OBS-logs: модель, код, число страниц, без текста), задача повторяется при следующем reindex; поиск работает в урезанном режиме без векторов (rule-arch-outgoing-call-resilience)
- disabled: CFG-wikisvc.EMBEDDINGS_ENABLED = false — задача не запускается, CLS-wikisvc-core.Ask работает без dense-ветки, `similar` и dense-prior

### JOB-wikisvc-core.delivery-flush — Сброс очереди статистики выдачи
status: planned | owner: LIB-wikisvc-core

- trigger: таймер раз в CFG-wikisvc.DELIVERY_FLUSH_SECONDS или при накоплении CFG-wikisvc.DELIVERY_FLUSH_BATCH записей; при закрытии CLS-wikisvc-core.Runtime (SIGTERM, rule-deploy-graceful-shutdown) — финальный сброс
- does: забирает накопленное CLS-wikisvc-core.DeliveryQueue и пишет одним `executemany`: строки TBL-wikisvc-core.index.delivery_stats (с выданными `ids`) и инкременты TBL-wikisvc-core.state.rule_usage (`delivered`, `opened`) вместо записи на каждом чтении (ТЗ §11.5–11.6)
- touches: пишет TBL-wikisvc-core.index.delivery_stats, TBL-wikisvc-core.state.rule_usage
- idempotent: нет — запись статистики; пачка удаляется из очереди только после коммита, сбой коммита оставляет её до следующего сброса
- concurrency: в каждом процессе с CLS-wikisvc-core.Runtime свой поток и своя очередь, каждый пишет только свой буфер — это не периодическая задача над общими данными (оценка агента относительно rule-arch-single-scheduler); SQLite сериализует запись
- on failure: падение процесса теряет не больше одного интервала статистики (данные вторичны; RISK-kb-delivery-stats-derived); ошибка записи — в лог без ID запросов
- deviation: поток внутри процесса, а не воркер Celery (rule-stack-background-tasks, SHOULD): проект без брокера, ADR-0004

## Настройки

Своих настроек ядро не читает: все переменные окружения разбирает `src/wikisvc/config.py`
(`Settings`), карточки — в `components/wikisvc/runtime.md` (CFG-wikisvc.*). Ядро получает готовый
объект `Settings` через CLS-wikisvc-core.Runtime.

v3 (planned) — настройки слоя знаний, которые читает ядро через `Settings` (определения — у SVC-wikisvc):

| что | настройки |
|---|---|
| эмбеддинги (CLS-wikisvc-core.Embeddings) | CFG-wikisvc.EMBEDDINGS_ENABLED, CFG-wikisvc.EMBEDDINGS_URL, CFG-wikisvc.EMBEDDINGS_MODEL, CFG-wikisvc.EMBEDDINGS_POOLING, CFG-wikisvc.EMBEDDINGS_DIM, CFG-wikisvc.EMBEDDINGS_TIMEOUT_SECONDS, CFG-wikisvc.EMBEDDINGS_RETRIES; ключа доступа нет — сервер на loopback (решение Q-kb-embeddings-api-key) |
| reranker (CLS-wikisvc-core.Ask, шаг 4) | CFG-wikisvc.ASK_RERANK_ENABLED, CFG-wikisvc.RERANKER_URL, CFG-wikisvc.RERANKER_MODEL — reranker в ядре, отдельный llama-server `--reranking` на loopback (RES-reranker-server), включён по умолчанию (решение Q-kb-reranker-placement) |
| ask и PPR | CFG-wikisvc.ASK_SEEDS, CFG-wikisvc.ASK_EXPANSION_RATIO, CFG-wikisvc.ASK_EXPANSION_MIN_HUBS, CFG-wikisvc.PPR_ALPHA, CFG-wikisvc.PPR_TOL, CFG-wikisvc.PPR_DENSE_PRIOR, CFG-wikisvc.SIMILAR_THRESHOLD |
| бюджеты | CFG-wikisvc.ASK_BUDGET_DEFAULT, CFG-wikisvc.BRIEF_BUDGET_MAX, CFG-wikisvc.TOOL_RESPONSE_CAP, CFG-wikisvc.CHARS_PER_TOKEN_LATIN, CFG-wikisvc.CHARS_PER_TOKEN_CYRILLIC |
| индекс и статистика | CFG-wikisvc.INDEX_READ_CONNECTIONS, CFG-wikisvc.DELIVERY_FLUSH_SECONDS, CFG-wikisvc.DELIVERY_FLUSH_BATCH |
