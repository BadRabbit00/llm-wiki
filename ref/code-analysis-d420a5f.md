# llm-wiki @ d420a5f: как сейчас устроены retrieval, граф, контекст, индекс, ingest

Фактическая карта кода (без оценок), на которую опирается раздел 11 ТЗ v3.
Все пути — относительно корня репозитория.

## 0. Зависимости
- `wikisvc` 0.3.2, Python ≥ 3.12. Runtime: fastapi, uvicorn, pydantic≥2, pydantic-settings, ruamel.yaml, pystemmer, python-multipart, typer, httpx, pypdf, python-docx, mcp 1.29–2.
- **numpy и scipy отсутствуют** и в `pyproject.toml`, и в `flake.nix`. `db.py` делает `DROP TABLE IF EXISTS embeddings`.
- Порог покрытия тестами `fail_under = 98`.

## 1. Граф — `src/wikisvc/index/graph.py`
- `GraphStore` Protocol: `neighbors`, `path`, `impact`, `subgraph`, `export`; единственная реализация `SqliteGraphStore`.
- `batches(ids)` — пачки по 400 id (лимит bound-параметров SQLite).
- `_check` — `SELECT count(*) FROM pages WHERE id IN (...) AND sensitivity IN (...)`; расхождение → `not_found()` (скрытое = несуществующее).
- `_wave` — один слой BFS на SQL: `SELECT … FROM edges e JOIN pages p ON p.id=e.{target} WHERE e.{source} IN (batch) AND p.sensitivity IN (levels) [AND e.rel IN …] [AND (e.kind!='inverse' OR e.rel='conflicts_with')] ORDER BY src,dst,rel,kind`. Допуск фильтруется по целевому узлу через JOIN. Уже посещённые узлы не исключаются в SQL.
- `_walk` — BFS по уровням в Python (не рекурсивный CTE): `distances` как visited, `parents` — первое увиденное ребро. Запросов ≈ Σ⌈|frontier|/400⌉ + check.
- `_nodes` — `SELECT id,type,title,summary,status … IN (batch)`, сортировка `(distance, id)` в Python.
- `_edges` — `SELECT * FROM edges WHERE src IN (batch)`, затем **фильтр dst ∈ ids в Python**; `canonical` не применяется → `impact()` возвращает и inverse-рёбра.
- `path` — полный `_walk` до `max_depth`, **без раннего выхода** при нахождении цели.
- `export` — `SELECT * FROM pages …` (**вместе с body и metadata**), затем `_edges` по всем узлам.
- Кеширования нет. Каждый вызов — новое соединение через `IndexDB.connect()` (+ `PRAGMA journal_mode=WAL`, `foreign_keys=ON`).
- Индексы: PK `edges(src,dst,rel,kind)`, `edges_dst(dst)`, `edges_dst_rel(dst,rel)`, `edges_src_rel(src,rel)`.

## 2. Поиск — `src/wikisvc/index/search.py`
- `mode` только `bm25`; k ≤ 50; query ≤ 1000 символов.
- Цикл операторов `("AND","OR")`: OR пропускается, если `len(hits) ≥ k/2`. **Новое соединение на каждый оператор.**
- SQL: `SELECT p.*, c.heading, c.text, bm25(chunks_fts,6.0,3.0,1.0) AS rank FROM chunks_fts JOIN chunks c … JOIN pages p … WHERE chunks_fts MATCH ? AND p.sensitivity IN (…) AND (фильтры type/status/sensitivity/tag через json_each) AND (p.type!='rule' OR json_extract(p.extra,'$.lifecycle') IN (…)) ORDER BY rank, p.id LIMIT 50`.
  - **`LIMIT 50` считает строки-чанки, не страницы**; дедуп по странице — потом в Python.
  - `p.*` тянет полный `body` и `metadata` в каждую строку.
- `score = -rank × boost[status]`; `tier` 0 (AND) / 1 (OR) / 2 (graph); сортировка `(tier, -score, id)` — любой AND-хит выше любого OR-хита.
- `expand=True`: для **топ-3** хитов `graph.neighbors(depth=1)` (≈ 4 запроса каждый), затем для каждого соседа **новое соединение + `SELECT * FROM pages WHERE id=?`** (N+1), фильтры повторно в Python; `score = root × 0.25`.
- `rules_related` (`services/rules.py::Rules.related`): `search(type=rule, k=50)` → на каждый хит `pages.page()` + `graph.neighbors(RULE_RELS)` + `graph.impact(IMPACT_RELS, depth=2)`; затем ещё `search(k=50)` по запросу и по каждому `impact_terms`. До 50 × (page + neighbors + impact) + ≥ 1 поиск.
- `Rules.list_rules` с `q`: `SELECT * FROM pages WHERE type='rule' ORDER BY id` (индекса на `type` нет), парсинг всех строк, фильтр в Python.

## 3. Контекст — `src/wikisvc/index/context.py`
- `get(page_id, actor, depth=1, rels, budget_chars=12000)`: `pages.page(root)` → `graph.neighbors(depth)` → ключ сортировки `(distance, лучший приоритет связи среди edges с dst==node, ранг статуса, id)` — **скан всех рёбер на каждый узел, O(N·E)**.
- Загрузка кандидатов: **`pages.page(id)` на каждый узел** (соединение + SELECT + парсинг JSON) — N+1.
- Корень никогда не обрезается. Остальные — целыми разделами H2/H3 до первого, который не влез; дальше не пробует. Бюджет — символы тела, без frontmatter.
- Каждый вызов **пишет в `delivery_stats`** (запись на пути чтения, отдельное соединение); `query_hash` всегда NULL. Читает таблицу только `Lint.stats` (всю, суммирует в Python).

## 4. Индекс — `src/wikisvc/index/indexer.py`, `db.py`
### 4.1 Схема `wiki.db` (`INDEX_SCHEMA = 1`)
| таблица | поля |
|---|---|
| `pages` | id PK, type, title, summary, status, sensitivity, path UNIQUE, tags JSON, aliases JSON, extra JSON, body, content_hash, created, updated, verified_at, verified_by, metadata JSON (весь frontmatter) |
| `edges` | src, dst, rel, kind; PK(src,dst,rel,kind); индексы `edges_dst`, `edges_dst_rel`, `edges_src_rel` |
| `chunks` | chunk_id PK, page_id → pages ON DELETE CASCADE, ord, heading, text — **индекса на `page_id` нет** |
| `chunks_fts` | FTS5(title, heading, text, tokenize='unicode61 remove_diacritics 2'), **contentful** (хранит уже стеммированный и расширенный синонимами текст), rowid = chunk_id |
| `raw_files`, `delivery_stats`, `issues` (без индекса), `meta` (`index_commit`, `generation`) |
- Нет индексов на `pages(type)`, `pages(sensitivity)`, `pages(status)`, `chunks(page_id)`.
- Соединение: `timeout=30`, Row, WAL, FK on; нет `synchronous`, `cache_size`, `mmap`; нет пула.

### 4.2 Чанки (`chunks(body, limit=1500)`)
- Разрез по H2/H3 (код маскируется `without_code`), внутри — абзацы по `\n\s*\n`; абзац > 1500 режется жёстко; упаковка жадная; перекрытие — последний абзац, если влезает.

### 4.3 Строка FTS на чанк
- `title` = `expand_synonyms(normalize(title + summary + aliases))` — **дублируется в каждом чанке страницы**; `heading`, `text` — аналогично. Теги в FTS не индексируются.

### 4.4 `Indexer.reindex(paths)` — одна транзакция
1. `read_pages` — glob `wiki/**/*.md`, `parse_page`.
2. Инкрементально: `all_pages` = **все страницы из БД** (`self.pages()` — `SELECT * ORDER BY path` + `Frontmatter.model_validate_json` для каждой) минус выбранные + изменённые.
3. `validate_set(all_pages)` — **на каждом reindex по всем страницам**; `ValidationCache` переиспользует только локальные проверки; ключ кеша = `(fm.model_dump_json(), body, path)` — сериализация frontmatter всех страниц на каждом проходе.
4. Удаления: инкрементально — `DELETE FROM chunks_fts WHERE rowid IN (SELECT …)`, `DELETE FROM pages WHERE path=?`.
5. Вставки: по одной строке `INSERT` в `pages`, `chunks`, `chunks_fts` — **без `executemany`**.
6. Рёбра: инкрементально `old_ids` через **второе соединение** и повторный `self.pages()` (снимок до транзакции); на каждую страницу — повторный `SELECT * FROM pages WHERE id=?` + `row_page` + `edges(page)` + `INSERT OR IGNORE`; inverse только для связей из `relations.yaml` (`links_to`/`cites` без обратных).
7. `DELETE FROM issues` + полная перезапись.
8. Raw-файлы: пропуск по `(size, mtime)`, иначе чтение + SHA-256.
9. `meta.index_commit`, `meta.generation += 1`.
- Триггер (`services/runtime.py`): `git diff --name-only <index_commit>` + untracked; любое изменение в `schema/` → полный reindex; registry перезагружается на каждом reindex.

### 4.5 Источники рёбер — `domain/markdown.py::edges`
frontmatter `relations` → kind `frontmatter`; `sources` → `cites`/`citation`; `[[…]]` → `links_to`/`wikilink`; `[@src …]` → `cites`. `without_code` вызывается дважды на `edges()`.

### 4.6 `content_hash` — sha256 всего файла (frontmatter + body).

## 5. Нормализация — `src/wikisvc/index/normalize.py`
- `normalize(text)`: **создаёт `Stemmer("russian")` и `Stemmer("english")` на каждый вызов**; lower, ё→е, `\w+`, подмена кириллических двойников в токенах с латиницей/цифрами, стемминг по алфавиту. Стоп-слова не удаляются из документов.
- `stopwords()` — `lru_cache`, 52 слова ru+en, применяется **только к запросу** (не к фразам).
- `expand_synonyms(text, synonyms)`: **на каждый вызов заново нормализует все значения всех групп**; применяется при индексации (3 раза на чанк) и на каждом слове запроса; многословные синонимы не матчатся.
- `match_query`: фразы в кавычках без синонимов и стоп-слов; слово → `("w" OR "syn"…)`; префикс `*` только на последнем слове; `AND`/`OR`.

## 6. Политики — `src/wikisvc/services/policies.py`
- `tokens(text)` = Σ по строкам `ceil(len/chars_per_token)`, **`chars_per_token = 2.5`** (и в агенте: `models.py`, `ingest_book.py`).
- `compile`: шаблон `policy-template.md` **читается с диска на каждый вызов**; кеш dict ≤ 128 (FIFO), ключ включает полный текст шаблона; инвалидация по `meta.generation` (1 запрос на вызов); при промахе `indexer.pages()` **загружает и парсит все страницы**, затем фильтр `type == "rule"`; `count_usage` — запись в state DB **на каждом вызове, включая попадания в кеш**.
- `_compile`: сортировка `(level!=must, -priority, category_order, id)`; жадное наполнение: для каждого кандидата **`_render(trial)` всего markdown заново** — O(n²), и каждый render до 10 итераций фикс-пойнта по `{used_tokens}`.

## 7. Домен — `registry.py`, `ids.py`, `markdown.py`, `validate.py`, `models.py`
- `ExtraField`: `type ∈ {str,int,list}`, `required`, `enum`, `pattern`, `max_length`, `min/max`, `min_items/max_items/item_enum/item_pattern`; **`default` объявлен, но `valid_extra` его не применяет**.
- `Relation`: `inverse`, `symmetric`, `from`, `to`, `same_type`. Веса нет.
- `Frontmatter.relations: dict[str, list[str]]` — **только строки-id, объекты отвергаются** (`E_FRONTMATTER_INVALID`).
- `page_path`: **только два плейсхолдера `{slug}` и `{parent_slug}`**; `{domain}` нет.
- `sections()` — только H2/H3; `required_sections` — точное совпадение H2.
- `validate_page`: `E_REL_TYPE_MISMATCH` если rel ∉ `allowed_relations` типа; `edges(page)` считается до 2 раз; секреты — через повторный рендер YAML.
- `validate_set`: `E_ID_DUPLICATE`, `E_LINK_UNRESOLVED`, пары rule→rule (`W_DEPENDS_ON_DEPRECATED`, `W_RULE_CONFLICT`), проверка `from/to/same_type` из `relations.yaml`.

## 8. Агент — `src/wikiagent/`
### 8.1 `jobs/ingest_book.py`
- Окно: `max_chars = min(60000, chapter_chunk_tokens × 2.5)`, по умолчанию 8000 токенов → **20 000 символов**; сервер (`services/extractions.py::text`) режет `text[offset:offset+max_chars]` — **жёстко, без перекрытия и границ предложений**, и на каждый вызов перечитывает весь `pages.jsonl`.
- На каждое окно: **`GET /rules/related?q=(title+text)[:1000]&limit=8` — всегда, даже если результат окна уже в чекпоинте**, без кеша (на сервере это search k=50 + до 8×(page+neighbors+impact) + ещё search).
- `models.structured("planner","book_chapter",ChapterResult)`; `valid`: scopes ⊆ словарь, `relations.rule_id ∈ known`, **на каждого кандидата повторный `GET /raw/…/text` за excerpt'ом**, цитата ≥ 2 слов и является подстрокой нормализованного excerpt.
- На каждого кандидата: `candidate_id()` — поиск в `GET /proposals/{pid}`, иначе slug + суффикс против **`client.all("/rules", lifecycle=all)` (все правила заново на каждого нового кандидата)**; классификация: **`GET /pages/{id}` на каждый id из `known` (до 8), на каждого кандидата, без кеша**; `models.structured("planner","classify")`.
- Состояние между окнами: `context()` ≤ `state_tokens×2.5` = 3750 символов, обрезка с пересчётом `json.dumps` на каждом шаге (O(n²)).
- Ревью-проход пачками по 40: `book_review` → merge (`GET /proposals/{pid}` на каждый merge, PATCH на страницу), links, key_ideas ≤ 15.
- Схемы: `Candidate` (thesis 20–160, quote ≤ 30 слов, relations ≤ 10), `ChapterResult` (candidates ≤ 10 на окно), `BookReview`.
- `ModelClient.structured`: system = SYSTEM + prompt + полный JSON-schema; user = `<UNTRUSTED_DATA>…`; `response_format json_schema` (strict: без min/max/default); retries ≤ 3 с repair-сообщением; `max_output = min(4096, context//4)`; предпроверка длины по 2.5 симв/токен.
- Чекпоинты: `job_state(job_id,key,value)`, новое соединение на каждый `checkpoint/restore`.

### 8.2 Heal — `heal/pairs.py`, `heal/run.py`
- `pairs`: для изменённых — `GET /graph/neighbors` (depth 1); для **каждой** выбранной — тот же neighbors **ещё раз**, `GET /search?q=<summary>&type=rule&k=8`, и **линейный скан всех страниц** по категории/scopes — O(N²) на полном проходе. ≤ 20 партнёров на страницу.
- `Healer.run`: кеш пар `pair_checks(a_id,a_hash,b_id,b_hash)`; **два `SELECT COUNT(*) FROM model_calls` на каждую пару**; `GET /pages/{a}`, `{b}`; `heal_pair` → при конфликте с must и confidence ≥ 0.7 — `heal_review`; при находке обе страницы фетчатся ещё раз.

## 9. MCP — `mcp_server.py`, `tool_contracts.py`
- FastMCP, `stateless_http=True`, `json_response=False` (SSE), профили `coding` (14) / `full` (все 21).
- Инструменты возвращают dict → JSON. Markdown только в поле `markdown` у `get_policies`.
- Лимиты: `budget_chars ≤ 60000`, `max_chars ≤ 60000`, `k ≤ 50`, snippets 500 симв., `get_rule` related ≤ 600 токенов. **Глобального потолка размера ответа нет**: `get_page`, `neighbors` не ограничены.

## 10. `scripts/benchmark_graph.py`
2000 синтетических `rule` + 10 000 случайных `depends_on` (без inverse), `neighbors(depth=3)` × 5, медиана ≤ 100 мс. Поиск, FTS, контекст, path, impact, export, `rels`, `restricted` не покрыты.

## 11. Тесты
`test_index_storage.py`, `test_incremental_regressions.py`, `test_related_graph.py` (golden `graph-golden.json`), `test_read_api.py`, `test_cov_wikisvc.py`, `test_policies.py`, `test_lint.py`, `test_mcp*.py`, агент: `test_agent_book.py`, `test_cov_book.py`, `test_agent_heal.py`. Hypothesis только в `test_domain.py`. Перф-тестов в pytest нет.

## 12. Горячие точки (факты)
1. `normalize()` — 2 Stemmer на вызов; `expand_synonyms()` — повторная нормализация всех синонимов на вызов; 3 вызова на чанк при индексации.
2. Индексация построчно, без `executemany`; `title` FTS дублируется в каждом чанке.
3. Инкрементальный reindex: все страницы из БД грузятся и парсятся дважды; `validate_set` по всем; `issues` перезаписывается целиком.
4. Поиск: `LIMIT 50` по чанкам; `p.*` с телами; expansion N+1 с соединением на соседа.
5. Контекст: N+1; ключ сортировки O(N·E); запись `delivery_stats` на каждом чтении.
6. Граф: соединение на вызов; `_check`; BFS пачками по 400; `path` без раннего выхода; фильтр dst в Python; `export` с телами; кеша нет.
7. Политики: промах кеша = все страницы; жадное наполнение O(n²) × 10 итераций; шаблон с диска; usage на каждый вызов.
8. `rules_related`: до 50 × (page + neighbors + impact) + поиск k=50; ingest зовёт его на каждом окне даже из кеша; `known` фетчится на каждого кандидата.
9. Heal: neighbors дважды; O(N²) скан; 2 COUNT на пару.
