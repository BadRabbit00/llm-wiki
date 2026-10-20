# wikisvc-cli: фоновые задачи и настройки

## Фоновые задачи

Фоновых задач нет: каждая команда выполняется и завершается. Долгоживущие процессы запускают
CLI-wikisvc-cli.serve (SVC-wikisvc) и CLI-wikisvc-cli.mcp (SVC-wikisvc-mcp).

## Настройки

Своих настроек CLI не определяет. Команды читают `Settings` компонента SVC-wikisvc (`src/wikisvc/config.py`):
CFG-wikisvc.WIKI_ROOT, CFG-wikisvc.STATE_DIR, CFG-wikisvc.INDEX_DIR, CFG-wikisvc.LOG_LEVEL, CFG-wikisvc.LOCK_TIMEOUT,
CFG-wikisvc.BIND_HOST и CFG-wikisvc.BIND_PORT (для `serve`), а также CFG-wikisvc-mcp.WIKI_TOKEN
(для `migrate-rules` и `mcp`).

changed: 2026-10-20 v3 (planned): своих настроек по-прежнему нет. `reindex`, `lint`, `mcp`, `embeddings selftest` и
`eval` читают CFG-wikisvc.EMBEDDINGS_ENABLED, CFG-wikisvc.EMBEDDINGS_URL, CFG-wikisvc.EMBEDDINGS_MODEL,
CFG-wikisvc.EMBEDDINGS_POOLING, CFG-wikisvc.EMBEDDINGS_DIM, CFG-wikisvc.EMBEDDINGS_TIMEOUT_SECONDS и
CFG-wikisvc.EMBEDDINGS_RETRIES (секрета нет, Q-kb-embeddings-api-key);
`eval` — CFG-wikisvc.ASK_BUDGET_DEFAULT; `policies export --knowledge` — CFG-wikisvc.BRIEF_BUDGET_MAX.
