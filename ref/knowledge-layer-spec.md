# ТЗ v3: слой знаний (knowledge layer) для `llm-wiki`

> Ревизия 2. Расширяет [SPEC.md](../SPEC.md) и [ТЗ v2](policy-layer-spec.md):
> из «свода правил для агентов, которые пишут код» делаем базу знаний обо всём,
> с которой работает любая модель через один MCP. Слой правил (`rule`, компилятор
> политик, `wk`) остаётся и опирается на новый слой.
>
> Ревизия 2 вносит правки по итогам обзора литературы и существующих систем
> (отчёт «Базы знаний для LLM агентов», 2026-10-20) и разбора кода на коммите
> `d420a5f`. Что изменилось относительно ревизии 1 — в разделе 13.

## 0. Решения, принятые до написания

| Вопрос | Решение | Почему |
|---|---|---|
| Единица знания | гибрид: страница-хаб (`topic`) + атомарные факты (`fact`) | proposition-level retrieval даёт +9–12 Recall@5 и +5–8 EM при бюджете 100 слов против passage-level (Dense X, arXiv:2312.06648); хаб собирает «актуальное состояние темы», чего атомарным заметкам не хватает |
| Язык | тело и `summary` на английском; русские термины в `aliases` и `schema/synonyms.yaml` | у Claude русский стоит ~3× токенов, у Qwen +52 %, у GPT/Gemini +18–23 %; источники английские |
| Домены на старте | systems, net, db, concurrency, lang/*, os, infra, security, ml, hardware, business, math | раздел 2 |
| Глубина ingest | всё подряд; `novelty` влияет только на доставку, не на хранение | полнота важнее экономии на хранении; экономим на выдаче |
| Эмбеддинги | включаем; дефолт BGE-M3, A/B с Qwen3-Embedding на собственном eval-наборе | ru→en MKQA: BGE-M3 76.2 vs mE5-large 76.8 (ничья), но у BGE-M3 8k контекст и sparse-голова; mE5 — 512 токенов |
| Графовая БД | не вводим; `GraphStore` поверх SQLite + граф в памяти (`scipy.sparse`) | Kùzu архивирован 2025-10-10; FalkorDB — SSPL, SurrealDB/Memgraph — BSL; 500 000 рёбер в CSR ≈ 6 МБ, PPR — миллисекунды |
| Расширение по графу | **условное**, не всегда | три независимых сравнения 2025: граф даёт +10…+23 на multi-hop и 0 или минус на single-hop (GraphRAG-Bench, arXiv:2506.05690; RAG vs GraphRAG, 2502.11371; VLDB, 2503.04338) |
| Время действительности фактов | bi-temporal: `valid_from/valid_to` + `replaced_by`, инвалидация вместо удаления | knowledge-update — худшая категория всех memory-систем (≤ 28 % multi-hop, MemoryAgentBench 2507.05257); схема Zep (2501.13956) |
| Дедупликация | косинус только отбирает кандидатов; решает NLI/LLM-судья | валидированного косинус-порога «тот же факт» не существует ни в одной работе; все системы (KGGen, Mem0, Graphiti, iText2KG) используют LLM как судью |
| Eval-набор | обязателен с этапа 1 | без него α, веса рёбер, пороги и выбор модели эмбеддингов остаются гипотезами |
| Личный слой (события, люди, хронология) | вне рамок этого ТЗ | отдельный документ |

Инварианты SPEC §6 сохраняются целиком: источник правды — Markdown в Git, ядро
детерминировано, решения принимает человек, внешние данные недоверенные.
Уточнение инварианта «решает человек» для ingest — в разделе 8.6.

---

## 1. Три слоя контента

```
wiki/
├── kb/          СЛОЙ ЗНАНИЙ   описательный: как устроен мир (новое)
├── rules/       СЛОЙ ПРАВИЛ   предписывающий: как делаем мы (v2, без изменений)
└── decisions/, playbooks/, lessons/, apps/, systems/, domain/ …
                 СЛОЙ ПРАКТИКИ  что решили, что делали, чему научились (v1)
```

Связь слоёв явная: `rule`, `adr`, `pattern`, `playbook` ссылаются на факты, из
которых следуют (`grounded_in`). Агент, открывший правило «используй io_uring для
сетевого ввода-вывода», одним переходом видит, почему и при каких условиях это так.

Разница слоёв важна для доставки: слой правил идёт в инструкцию **всегда**
(компилятор политик), слой знаний — **по запросу и по графу**. Знание не
навязывается, правило — да. Единственное измеренное исследование файлов-инструкций
для агентов (ETH, arXiv:2602.11988) показывает, что ценны только детали, которые
модель не может вывести сама (+4 % success у рукописных, −3 % у сгенерированных
LLM) — это же правило для содержимого brief в разделе 7.

---

## 2. Структура каталогов `kb/`

Путь страницы вычисляет сервис по шаблону `kb/{domain}/{kind}/{slug}.md`, где
`{domain}` — новое обязательное поле знаниевых типов, `{kind}` — каталог типа.
Разрешённые домены — дерево в `schema/domains.yaml`; администратор расширяет его,
агент через предложения — нет.

```
kb/
├── systems/        распределённые и высоконагруженные системы: архитектуры 1M+ rps,
│                   партиционирование, консенсус, backpressure
├── net/            сетевой стек: TCP/QUIC/HTTP3, kernel bypass (DPDK, XDP, AF_XDP),
│                   балансировка, zero-copy
├── db/             хранилища: storage engines (LSM, B-tree), kv, oltp, olap,
│                   кеши и их замены, репликация
├── concurrency/    модели памяти, lock-free, async-рантаймы, планировщики
├── os/             ядро Linux, io_uring, NUMA, hugepages, планирование, cgroups
├── lang/
│   ├── rust/       язык, идиомы, стиль, типичные ошибки, экосистема
│   ├── python/
│   ├── cpp/
│   ├── c/
│   └── nix/        язык Nix как язык, не NixOS как система
├── infra/          NixOS, деплой, контейнеры, наблюдаемость, сети офиса
├── security/       appsec, netsec, pentest, криптография, изоляция агентов
├── ml/             архитектуры, обучение, инференс, агенты, оценка
├── hardware/       электроника: МК, FPGA, схемотехника, PCB, даташиты
├── business/       процессы, CRM, моделирование предметной области, продукт
└── math/           алгоритмы, структуры данных, вероятность,
                    теория очередей и модели производительности
```

Внутри каждого домена четыре каталога по типу:

```
kb/db/
├── topics/     хабы              top-db-lsm-tree.md
├── facts/      атомарные факты   f-db-lsm-write-amplification.md
├── tech/       технологии        tech-scylladb.md
└── questions/  открытые вопросы  q-db-which-kv-for-1m-rps.md
```

Почему не глубже. Папки — физическая навигация для человека и Git, она должна быть
грубой и стабильной. Тонкая навигация («кеши → замены Redis → in-process») — это
хабы `topic` и рёбра `part_of`: их можно перестраивать без переноса файлов, ID не
ломаются. Практики Karpathy-вики называют главной болью «границы тем ad hoc» и
«index.md фрейзится на 200–500 документах»; атомарный факт задаёт границу
утверждением, а хаб — явным упорядоченным списком, не папкой.

Домен у страницы один (физический путь). Если факт относится к двум доменам
(«io_uring в Rust» — `os` и `lang/rust`), он лежит в одном, а второй указывается
в `scopes` (раздел 6).

---

## 3. Типы страниц слоя знаний

Четыре новых типа. Существующие тринадцать не меняются, кроме трёх точек: у `source`
расширяется `kind`, у `rule`/`adr`/`pattern`/`playbook` добавляется связь `grounded_in`,
у всех появляется необязательное поле `domain`.

### 3.1. `fact` — атомарное утверждение

Единица доставки. Ровно одно проверяемое утверждение.

```markdown
---
id: f-rust-fn-naming-snake-case
type: fact
domain: lang/rust
title: Function names are snake_case
claim: Functions and methods are named in snake_case; the compiler warns on CamelCase via non_snake_case.
summary: In Rust, functions and methods are named in snake_case; rustc's non_snake_case lint warns on CamelCase names.
kind: convention            # см. ниже
confidence: sourced         # sourced | inferred | contested | open
novelty:                    # per-model, см. ниже
  claude-sonnet-4.5: common
valid_for: "rust>=1.0"      # условие применимости (версия, режим)
valid_from: 2015-05-15      # с какого момента верно в мире (необязательно)
valid_to: null              # null = действует
scopes: [lang:rust]
tags: [naming, style]
aliases: [именование функций, snake_case]
sources: [src-rust-book-2021]
relations:
  about: [top-rust-naming]
  applies_with:
    - {id: f-rust-doc-comment-triple-slash, w: 0.8, note: "when writing a public fn"}
status: draft
sensitivity: public
---

## Claim
Functions and methods use `snake_case`. [@src-rust-book-2021 ch. 3]

## Why
Consistency with the standard library and the `non_snake_case` lint.

## Example
```rust
fn parse_header(buf: &[u8]) -> Header { … }
```

## Caveats
FFI bindings may keep foreign names with `#[allow(non_snake_case)]`.
```

Поля:

| поле | правило |
|---|---|
| `claim` | **обязательно**, 20–200 символов, одно предложение, **минимальное**: один смысл, без «in Rust, …» и прочих контекстных обёрток. Это единица дедупликации и retrieval (уровень L0) |
| `summary` | **деконтекстуализированный** `claim`: добавлен только тот признак, который снимает неоднозначность для читателя вне контекста («molecular fact», arXiv:2406.20079). Это то, что читает человек в ревью и что идёт в L1. Хранить пару (`claim`, `summary`) — рекомендация DnDScore (arXiv:2412.13175): от деконтекстуализации FActScore меняется на 13 пунктов, 19 % вердиктов переворачиваются |
| `kind` | `definition` \| `mechanism` \| `constraint` \| `tradeoff` \| `number` \| `convention` \| `api` \| `pitfall` \| `comparison` \| `step` \| `snippet` |
| `kind: snippet` | факт, суть которого — фрагмент кода: `claim` описывает, что показывает листинг, сам код — в `Example`. Нужен, потому что в книгах по языкам половина содержимого — листинги, и ни один опубликованный экстрактор не умеет работать с кодом как с фактом |
| `confidence` | `sourced` — есть проверенная цитата; `inferred` — выведено агентом/человеком без цитаты; `contested` — есть ребро `contradicts`; `open` — не проверено |
| `novelty` | словарь `модель → common \| differs \| unique`. **Per-model**, потому что frontier-модель знает почти всю Rust Book, локальная 8B — нет. Ставится не самооценкой модели (closed-book самооценка расходится с правдой на 7–35 %, FActScore 2305.14251), а процедурой из 8.5. Отсутствие ключа для модели = неизвестно = трактуется как `differs` при доставке |
| `valid_for` | условие применимости: `rust>=1.75`, `linux>=6.1`, `unsafe`, `kernel:io_uring`. **Обязательно для `kind ∈ {number, api, pitfall}`**: именно отсутствие квалификатора даёт ложные «противоречия» (CLAIRE 2509.23233: сравнение фактов из разных периодов — главный источник false positives) |
| `valid_from` / `valid_to` | event-time по Zep: когда факт стал/перестал быть верным в мире. Git даёт transaction-time (коммит) бесплатно, event-time — нет. `valid_to` непустой ⇒ сервис ставит `status: outdated` |
| для `kind: number` | дополнительно `value`, `unit`, `conditions` (железо, нагрузка, версия), `measured_at` |

Разделы: `Claim` обязателен, `Why`, `Example`, `Caveats` — по необходимости.
Тело больше 1 500 символов — `W_FACT_LONG`: это не факт, а тема, её надо резать.

### 3.2. `topic` — хаб

Собирает факты в осмысленном порядке, даёт сжатую выжимку и место в дереве тем.

```markdown
---
id: top-rust-naming
type: topic
domain: lang/rust
title: Naming conventions in Rust
summary: How items are named in Rust: cases per item kind, abbreviations, lints that enforce them.
scopes: [lang:rust]
aliases: [именование в Rust, naming]
relations:
  part_of: [top-rust-style]
  builds_on: []
  applies_with: [top-rust-docs]
status: draft
---

## Digest
<= 800 символов. Выжимка темы — abstractive-уровень между списком claims и полными
фактами. Её отдаёт `get_topic(level=1)` и она же индексируется вектором `digest`.

## Facts
Упорядоченный список. Порядок = порядок чтения/применения = канонический порядок выдачи.
1. [[f-rust-fn-naming-snake-case]]
2. [[f-rust-type-naming-camel-case]]
3. [[f-rust-const-naming-screaming]]

## Open questions
- [[q-rust-naming-ffi-wrappers]]
```

Ребро `about` (факт → хаб) объявляется у факта; обратное `has_fact` строит индекс.
Порядок фактов — из раздела `Facts` хаба (индексатор читает позицию `[[…]]`), lint
проверяет, что множества `Facts` и `has_fact` совпадают (`W_HUB_FACTS_MISMATCH`).
Хаб больше 60 фактов — `W_HUB_TOO_LARGE`, делить через `part_of`; без фактов —
`W_HUB_EMPTY`. **Хаб перечисляет только актуальные факты**: факт со `status: outdated`
в `Facts` — `W_HUB_CITES_OUTDATED`. Это встроенный компенсатор того, что retrieval
будет поднимать устаревшее.

### 3.3. `tech` — технология, инструмент, компонент

```yaml
id: tech-scylladb
type: tech
domain: db
title: ScyllaDB
summary: Cassandra-compatible wide-column store in C++ with shard-per-core architecture.
category: database        # database | runtime | library | protocol | tool | service | chip | board | model
status: evaluating        # evaluating | adopted | avoid | legacy | unknown
verdict: "Use for write-heavy 1M+ ops/s with simple access patterns; avoid for ad-hoc queries."
current_version: "6.2"
homepage: https://…
scopes: [domain:db, scale:1m-rps]
relations:
  instance_of: [top-db-wide-column]
  alternative_to: [tech-cassandra]
  replaces: [tech-redis]
```

`verdict` — твоё суждение, не описание из README. Факты о технологии — отдельные
`fact` с `about: [tech-…]`. Для железа: `category: chip|board`, даташит — `source`
с `kind: datasheet`, параметры — факты `kind: number`. `current_version` участвует
в lint `W_STALE_VERSION`.

### 3.4. `question` — открытый вопрос

```yaml
id: q-db-which-kv-for-1m-rps
type: question
domain: db
title: Which embedded KV sustains 1M+ ops/s on a single NVMe?
summary: Open: candidates are …; need a benchmark under our access pattern.
priority: 2
relations:
  about: [top-db-kv-stores]
  answered_by: []           # непустой список → status: answered
```

Явное «не знаем», чтобы агент не выдумывал (abstention в Agent Zero Memory,
«can't answer» в book2graph), а `heal` знал, что ресерчить.

### 3.5. Изменения в существующих типах

- `source.kind` += `paper`, `datasheet`, `spec`, `course`, `video`, `rfc`; поле
  `covers: [topic-id…]` — оглавление источника, спроецированное на хабы.
- `rule`, `adr`, `pattern`, `playbook` получают связь `grounded_in` → `fact`/`topic`.
- Все типы получают необязательное поле `domain`; старые `path_template` без
  `{domain}` продолжают работать.
- `term` остаётся для бизнес-терминов заказчика; технические определения —
  `fact` с `kind: definition`.

---

## 4. Связи

`schema/relations.yaml` расширяется. У связи — базовый `weight`; у конкретного
ребра он переопределяется в шапке объектом `{id, w, note, origin}`. `origin`
(`manual | extracted | inferred`) — провенанс ребра, как в Pulse8 Cortex; рёбра
`extracted` приходят из ingest, `inferred` — от `heal`. Вес участвует только в
ранжировании при обходе, не в валидации.

| rel | обратная | откуда → куда | вес | смысл |
|---|---|---|---|---|
| `about` | `has_fact` | fact, question → topic, tech | 1.0 | принадлежность хабу. Аналог «contains»-рёбер HippoRAG 2 — самый сильный по измеренному эффекту тип ребра (+6.1 R@5 без них падает) |
| `applies_with` | симметрична | fact, topic ↔ fact, topic | 0.8 | «применяя это, учитывай и то» — именование функций ↔ doc-комментарии |
| `supports` | `supported_by` | fact → fact | 0.7 | факт-свидетельство |
| `contradicts` | симметрична | fact ↔ fact | 0.9 | противоречие; оба факта получают `confidence: contested` до разрешения |
| `refines` | `refined_by` | fact, rule → fact, rule | 0.7 | частный случай, уточнение |
| `precedes` | `follows` | fact → fact | 0.6 | порядок шагов/изучения |
| `builds_on` | `prerequisite_of` | topic → topic | 0.5 | что нужно знать раньше |
| `instance_of` | `has_instance` | tech → topic | 0.8 | ScyllaDB — экземпляр «wide-column store» |
| `alternative_to` | симметрична | tech ↔ tech | 0.6 | конкуренты |
| `replaces` | `replaced_by` | tech, fact → tech, fact | 0.7 | «вместо X теперь Y». **Непустой `replaced_by` у факта ⇒ сервис ставит `status: outdated`** (инвалидация, не удаление — Zep, Mem0g) |
| `grounded_in` | `grounds` | rule, adr, pattern, playbook → fact, topic | 0.9 | предписание опирается на знание |
| `answered_by` | `answers` | question → fact | 1.0 | закрытие вопроса |
| `part_of` | `has_part` | topic → topic | 0.5 | дерево тем |
| `conflicts_with` | — | как в v2, только rule | — | не трогаем |
| `related` | — | как сейчас, слабое | 0.2 | ≤ 3 на страницу |

Производные рёбра, которые индексатор строит сам и в файлах не хранит:

- `links_to` из `[[…]]`, `cites` из `[@…]` — как сейчас;
- `same_hub`: два факта в одном хабе (вес 0.4);
- `co_cited`: два факта цитируют один источник в соседних главах (вес 0.3);
- `similar`: косинус `claim`-векторов ≥ 0.80 (вес = косинус − 0.5, т. е. 0.3–0.5).
  Порог 0.80 совпадает с τ synonymy-рёбер HippoRAG; их там в 7–20× больше явных,
  а удаление стоит лишь 0.7–1.4 R@2 — то есть это полезный, но не критичный слой.

Итоговый вес ребра в обходе:

$$
w = \text{base}(rel)\cdot \text{override}\cdot f_\text{status}(dst)\cdot f_\text{usage}(edge)
$$

`f_status`: verified 1.2 / draft 1.0 / outdated 0.3. `f_usage` пока 1.0; как его
считать из логов доставки — отдельное решение (в `delivery_stats` пишем выданные id
и какие из них агент потом открыл через `get_fact`).

**Честная оценка весов.** Ни одна работа не содержит абляции per-type весов или
whitelist'а связей в retrieval-графах; HippoRAG называет «relation-guided traversal»
future work. Таблица выше — разумные стартовые значения с ожидаемым эффектом в
единицы пунктов. Они тюнятся на eval-наборе (раздел 10), а не фиксируются
архитектурно. Что измеренно важнее весов: IDF-вес семян и fallback на чистый
гибридный поиск (раздел 7.2).

---

## 5. Индекс

`wiki.db` (производный, пересобирается):

```sql
ALTER TABLE edges ADD COLUMN weight REAL NOT NULL DEFAULT 1.0;
ALTER TABLE edges ADD COLUMN note TEXT;
ALTER TABLE edges ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual';
CREATE INDEX IF NOT EXISTS pages_type ON pages(type);
CREATE INDEX IF NOT EXISTS pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS chunks_page ON chunks(page_id);

CREATE TABLE embeddings (
  page_id TEXT NOT NULL, level TEXT NOT NULL,   -- claim | digest | chunk
  chunk_id INTEGER, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL,
  content_hash TEXT NOT NULL,                   -- для инкрементального пересчёта
  PRIMARY KEY (page_id, level, chunk_id)
);
CREATE TABLE soft_edges (                         -- similar, co_cited, same_hub
  src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL, weight REAL NOT NULL,
  PRIMARY KEY (src, dst, rel)
);
CREATE TABLE node_stats (                         -- IDF-подобная специфичность узла
  page_id TEXT PRIMARY KEY, degree INTEGER NOT NULL, specificity REAL NOT NULL
);
```

Эмбеддинги:

- одна многоязычная модель: **BGE-M3** по умолчанию (`--pooling cls`), кандидаты
  для A/B — `multilingual-e5-large` (`mean`, лимит 512 токенов) и
  `Qwen3-Embedding-0.6B/4B` (`last`; MTEB-Multilingual 64.33/69.45 против 59.56 у
  BGE-M3, но ru→en числа не опубликованы). Выбор — по Recall@8 на eval-наборе;
- провайдер `OpenAICompatibleEmbeddings` (`/v1/embeddings`, `llama-server --embeddings`
  или TEI). **Обязателен self-test при старте**: закодировать эталонную пару и
  сравнить косинус с сохранённым — неправильный pooling в llama.cpp «fails silently»
  (косинус ~0.8 вместо ~1.0);
- три уровня векторов: `claim` (title + claim, один на факт), `digest` (один на
  хаб/tech), `chunk` (разделы). **Все три уровня — в одном пуле поиска семян**:
  RAPTOR (arXiv:2401.18059) показывает 73.7 % при поиске по всем слоям против ~58 %
  по одному; хаб может оказаться лучшим семенем для широкого вопроса, chunk — для
  вопроса про конкретный пример;
- `model` в таблице — не формальность: пересечение top-k между разными моделями
  всего 0.43–0.54 (arXiv:2509.18869), смена модели = полный `reindex --embeddings`;
- пересчёт инкрементальный по `content_hash`.

Граф в памяти: `GraphStore` держит снимок `edges ∪ soft_edges` в `scipy.sparse.csr_matrix`
(узлы → индексы), привязанный к `meta.generation`; после `accept`/`reindex`
снимок перестраивается лениво при первом запросе. На 500 000 рёбер CSR —
≈ 500k × 12 байт + 50k × 4 ≈ 6 МБ, одна итерация PPR — один sparse matvec.
Допуск применяется до построения матрицы запроса: узлы выше clearance токена
в неё не попадают (та же гарантия, что у `visible_edges` сейчас).

`node_stats.specificity` — аналог node specificity HippoRAG (без него −4.2 R@2 на
HotpotQA): $s(v) = \log\frac{N}{1 + \deg(v)}$, нормированная в [0, 1]; хабы с
60 фактами получают низкую специфичность и не перетягивают массу PPR.

---

## 6. Scopes и профили

```yaml
axes:
  domain: {hierarchical: true}     # domain:db, domain:db/kv (родитель подразумевается)
  lang:   {}                       # lang:rust
  tech:   {from: tech-pages}       # tech:tokio — автоматически из страниц tech
  layer:  {enum: [kernel, runtime, app, infra]}
  scale:  {enum: [single-node, cluster, 1m-rps]}
  stage:  {enum: [design, implement, review, operate]}
```

Профиль — набор scopes + бюджет + политика доставки:

```yaml
id: rust-hpc-service
title: High-load Rust service
scopes: ["lang:rust", "domain:systems", "domain:net", "domain:concurrency", "scale:1m-rps"]
budget_tokens: 2500
reference_model: claude-sonnet-4.5     # чей novelty читать по умолчанию
brief:
  include_novelty: [differs, unique]   # common в brief не идёт
  max_facts: 40
```

Домен страницы автоматически даёт ей scope `domain:<domain>`; остальные перечисляются
в `scopes`. Отбор по scope — пересечение с профилем либо `*`, иерархия учитывается.
`rule.applies_to` остаётся как алиас `scopes` для обратной совместимости.

---

## 7. Доставка: как расходовать меньше токенов

Принцип тот же, что у блока политик: **в контекст идёт тезис с id, подробности —
по id**. Агент ссылается на факт (`f-…`), а не пересказывает.

Три уровня представления любой страницы:

| уровень | что | ≈ токенов |
|---|---|---|
| L0 | `id · claim` (для topic/tech — `id · summary`) | 30–50 |
| L1 | `id · summary` + `Caveats` + первый пример, ≤ 600 символов; для topic — `Digest` | 120–180 |
| L2 | страница целиком | 300–1500 |

L0 — extractive-уровень (дословный claim), он лучше любой выжимки для multi-hop
(RECOMP, arXiv:2310.04408: extractive бьёт abstractive на HotpotQA при 11 % токенов);
`Digest` — abstractive-уровень для обзорных вопросов. Claim — полное предложение с
именованным субъектом, не `key: value`: перевод структур в предложения даёт +15–20 %
к нахождению нужного документа (arXiv:2511.13900).

### 7.1. `get_brief(profile, budget)` — в начале задачи

Детерминированная компиляция, аналог `get_policies`:

1. кандидаты — все `fact` с пересекающимися scopes, `status ∉ {outdated}`;
2. фильтр по `novelty[reference_model]` из профиля (по умолчанию `differs`, `unique`
   и неизвестное; `common` — только если бюджет остался). Это не экономия, а
   качество: сгенерированные LLM context-файлы *снижают* success агентов на 3 %;
3. ранжирование: `priority` хаба × централность факта (PPR от всех хабов профиля,
   кешируется по `generation`) × `f_status`;
4. выдача L0 до бюджета, сгруппированная по хабам, в **каноническом порядке**
   (позиция в `Facts` хаба, затем id). Один и тот же top-5 в другом порядке меняет
   ответ модели в 50.8–84.4 % случаев (Stable-RAG, arXiv:2601.02993); канонический
   порядок — самый дешёвый рычаг воспроизводимости.

```
## Knowledge brief: rust-hpc-service (v 9c1e2a, ~2 300 tokens)

### top-net-io-uring  (12 facts, 4 shown)
- f-os-iouring-sqpoll-tradeoff: SQPOLL removes syscalls per submit but burns a core; …
- f-os-iouring-registered-buffers: registered buffers skip per-op pinning; …
…
Details: get_fact(id). Related facts: expand(ids).
```

Вёрстка brief не важна (факторное исследование 1 650 сессий, arXiv:2605.10039:
размер, позиция, split — без значимого эффекта); важно содержимое. Кешируется по
хешу содержимого; `wk policy sync` умеет вписывать его блоком
`<!-- wikisvc:knowledge begin -->`, но по умолчанию brief запрашивается в начале сессии.

### 7.2. `ask(query, budget, scopes?)` — по ходу задачи

Единый инструмент вместо `search` + `get_context`:

1. **Семена.** BM25 (FTS5 по claim/title/aliases/chunks) + косинус по векторам всех
   трёх уровней; слияние RRF (k = 60). RRF — безопасный дефолт без тюнинга; когда
   появится eval-набор, один вес λ выпуклой комбинации нормированных score обгоняет
   RRF (Bruch et al., arXiv:2210.11934). Топ-8 семян. BM25 здесь — страховка для
   точных имён (`io_uring`, `SQPOLL`, ключи конфигов) и основной путь для длинных
   тел L2: на полных документах BM25 обгоняет BGE-M3 на 13 пунктов (RusBEIR).
2. **Нужно ли расширение** (условие, без LLM). Пропускаем PPR и отдаём семена L1 +
   их хабы, если top-1 отрывается от top-2 по score в ≥ 1.5 раза **и** все семена
   из ≤ 2 хабов. Расширяем, если семена размазаны по ≥ 3 хабам или top-1 слаб.
   Fallback на чистый гибридный поиск, если семян меньше 3 (у HippoRAG 2 18 %
   провалов были «фильтр не оставил ничего»).
3. **Расширение по графу.** Personalized PageRank:

   $$\pi = \alpha\, r + (1-\alpha)\, P^{\top}\pi,\qquad \alpha = 0.5$$

   Reset-вектор $r$: семена с весом $\text{score} \cdot s(v)$ (specificity из
   `node_stats`) **плюс все узлы** с весом $0.05 \cdot \cos(q, v)$ — постоянный
   dense-prior HippoRAG 2 (кривая по коэффициенту плоская, оптимум 0.05).
   Почему α = 0.5, а не 0.15: средняя длина прогулки $(1-\alpha)/\alpha$ — один
   шаг при 0.5 и 5.7 при 0.15; в вики с хабами на 60 фактов и `part_of` между
   хабами масса за шесть шагов растечётся по половине домена. Сходимость:
   остаток после $k$ итераций $\le (1-\alpha)^k$; при 0.5 и 20 итерациях это
   $10^{-6}$, при 0.15 — 0.039. **Останов по допуску** $\|\Delta\pi\|_1 < 10^{-6}$,
   а не по фиксированному числу итераций. Белый список рёбер: `applies_with`,
   `about`/`has_fact`, `same_hub`, `refines`, `supports`, `contradicts`, `precedes`,
   `grounded_in`, `similar`. Берём топ-N по $\pi$, исключая семена.
   Именно так факт про doc-комментарии всплывает на запрос про именование функций:
   лексически они не связаны, но между ними `applies_with` с весом 0.8.
4. **Reranker** (необязательно, флаг): cross-encoder `bge-reranker-v2-m3` или
   `Qwen3-Reranker-0.6B` на шаге «какие id из `expanded[]` раскрыть до L1»
   (+4.7 nDCG@10 на русском поверх BGE-M3).
5. **Сборка в бюджет.** Семена — L1; расширение — L0; хабы семян — одной строкой;
   `contradicts`-пары выдаются парой с пометкой `⚠ contested`. Канонический
   порядок внутри хаба. Не влезает — режем по уровню, не молча: `omitted_ids[]`.
6. **Ответ**: `seeds[]`, `expanded[]`, `omitted_ids[]`, `hubs[]`, `version`
   (хеш генерации индекса + модель эмбеддингов), `expansion_used: bool`.

В описании инструмента `ask` для модели: *«quote the claim ids and text you rely on,
then answer»* — «сначала процитируй свидетельства» даёт до +4 % на RULER
(arXiv:2510.05381) бесплатно.

Бюджет: по умолчанию 1 500 токенов, brief ≤ 2 500. Claude Code принимает 25 000
токенов на результат инструмента и предупреждает с 10 000 — `get_topic(level=2)` для
хаба на 60 фактов обязан принимать `budget_tokens` и пагинацию.

### 7.3. Остальные инструменты

| инструмент | что |
|---|---|
| `get_fact(id)` | L2 + рёбра с весами, заметками и `origin` |
| `get_topic(id, level=0\|1\|2, budget_tokens, cursor)` | хаб: список claims / digest / всё, с пагинацией |
| `expand(ids, rels?, depth=1, budget)` | соседи по графу для уже полученных id |
| `get_tech(id)` | tech + verdict + факты L0 + альтернативы |
| `why(id)` | цепочка `grounded_in` → факты → источники: «откуда это известно». Вариант реализации — пути PathRAG (α = 0.7 на хоп, top-15 путей, лучший последним) |
| `list_questions(scopes)` | открытые вопросы по области |
| `propose_fact(...)`, `propose_link(...)` | запись через предложения |

Все инструменты принимают `budget_tokens`; ответы — компактный markdown-текст в
JSON-обёртке MCP, не вложенный JSON с отступами.

### 7.4. Что агент обязан делать (AGENTS.md вики)

1. В начале задачи — `get_brief(profile)`.
2. Перед проектным решением — `ask(...)` по ключевым понятиям; `list_questions` по области.
3. Ссылаться на факты по id; не пересказывать claim своими словами.
4. Нет нужного факта — не выдумывать: `propose_fact` с `confidence: inferred` или `question`.

---

## 8. Ingest книги «всё подряд»

### 8.1. Сколько выйдет на самом деле

Измеренные соотношения: ~2.3 proposition на предложение, средняя длина 11 слов
(Dense X); ~8.9 атомарных фактов на блок (CLAIRE); выход варьируется 2× только от
few-shot примеров (arXiv:2403.11903). Глава в 5 000 слов — 250–300 предложений,
**500–700 сырых фактов**; «The Rust Programming Language» — **8 000–12 000 до
дедупликации**, не 800–1 500. Ни одна работа не измеряла выход на технической
книге, так что реальное число может быть вдвое ниже из-за листингов, но порядок —
тысячи. Стоимость извлечения не фактор (KGGen: роман в 1M символов за $0.84 и
551 с на Gemini Flash); фактор — ревью, см. 8.6.

### 8.2. Окна

Не глава целиком, а **раздел главы, 1 000–2 000 токенов**, с перекрытием в один
абзац. GraphRAG работает чанками 300–1 200 токенов; iText2KG показывает, что
глобальный контекст (список уже известных хабов и терминов) стоит ~10 пунктов
precision, но даёт переиспользование сущностей, а без него граф раздувается на
30 %. Поэтому в каждое окно кладётся:

- текст раздела;
- **глобальный список хабов и tech** домена (id + title, ≤ 300 строк);
- `state` — скользящая выжимка главы (≤ 1 500 токенов);
- **5–8 эталонных фактов из вики как few-shot** — in-context примеры влияют на
  гранулярность сильнее, чем текст инструкции (DecompScore 42.3 против 20.0 при
  одинаковых инструкциях).

### 8.3. Извлечение

Планировщик возвращает список кандидатов:
`{claim, summary, kind, evidence: {page|chapter, quote ≤ 30 слов}, suggested_topic,
suggested_scopes, valid_for?}`. Правила для модели: `claim` минимален, `summary` —
деконтекстуализирован «молекулярно»; код — только в `kind: snippet`; нормативные
фразы книги («you should…») — `kind: convention`, описательные — `mechanism`/`constraint`.
Цитаты проверяет сервис по кешу текста (как сейчас); кандидат без цитаты —
`confidence: inferred`. Ожидаемый брак хороших экстракторов: 0.7–1.3 % неверных
и 3–5 % не самодостаточных единиц — первое снимает проверка цитаты, второе ловит
только человек.

Как дешёвый первый проход или эталон для промпта — Propositionizer
`chentong00/propositionizer-wiki-flan-t5-large` (F1 0.822 против GPT-4).

### 8.4. Привязка к хабам и дедупликация

1. **Хаб.** `suggested_topic` → `ask` по вики; есть подходящий `topic` → `about` на
   него; нет → в этом же предложении создаётся хаб `draft`. Хабы — по понятиям, не
   по главам: глава «Ownership» даёт `top-rust-ownership`, а не `top-rust-book-ch4`.
   Оглавление книги живёт в `source.covers`. Скелет хабов из оглавления можно
   построить детерминированно одним вызовом (book2graph).
2. **Кандидаты в дубликаты.** kNN по `claim`-векторам, косинус ≥ 0.80 → до 10
   кандидатов. Это recall-стадия; порог не переносится между моделями эмбеддингов
   и **калибруется на размеченных парах** (раздел 10).
3. **Судья.** Для каждой пары (новый, кандидат) — двунаправленный NLI (локальный
   cross-encoder) или LLM-судья:
   - A ⊨ B и B ⊨ A ⇒ **дубликат**: не создаём, `patch_page: add_source` + цитата
     к существующему;
   - одностороннее entailment ⇒ **`refines`** (конкретный уточняет общий), оба
     остаются;
   - contradiction ⇒ **`contradicts`**, оба получают `confidence: contested`,
     пара идёт в обязательное ревью;
   - иначе — независимые факты.
   Один проход даёт дубликаты, `refines` и `contradicts` вместо трёх эвристик.
   Ожидания по противоречиям: сильная модель с CoT — precision 0.95 при recall
   0.57 (arXiv:2504.00180), 8B-модели находят ~1 %; `W_CONTRADICTION_UNRESOLVED` —
   advisory-флаг, не истина.
4. **Связи.** Планировщик предлагает `applies_with`/`precedes` между новыми и
   найденными фактами с `note`, `origin: extracted`; валидатор проверяет типы и id.

### 8.5. `novelty`

Не самооценка модели. Усечённый SliCK (arXiv:2405.05904; полный — ~170 вызовов на
факт): `claim` → cloze-вопрос, 2–3 парафразы × 5 сэмплов при T = 0.5 у
референсной модели, NLI-судья сравнивает ответ с `claim`, бакет по доле попаданий:
≥ 0.8 — `common`, 0.2–0.8 — `differs`, < 0.2 — `unique`. 10–30 вызовов на факт;
потеря надёжности от усечения в литературе не измерена — это проверяется на
eval-наборе. Считается фоновой задачей `wikiagent` (`novelty_scan`), не в ingest;
`unique`-факты попадают в более строгое ревью: они одновременно самые ценные и
самые вероятно неверно извлечённые.

### 8.6. Предложения и ревью при тысячах фактов

Предложение — на хаб (а не на главу), ≤ 60 фактов. Ревью — список L0 (`summary`
для человека), L1 для конфликтов. Трёхуровневая маршрутизация (по MemGuard/Mem0):

| класс | условие | что происходит |
|---|---|---|
| авто | `confidence: sourced`, цитата проверена, кандидатов в дубликаты нет, `kind ∉ {convention}` | принимается в `draft` без ревью, но предложение остаётся в истории и может быть откачено целиком (`revert`) |
| очередь | `inferred`, есть `refines`, `W_POSSIBLE_DUPLICATE`, `kind: convention`, `novelty: unique` | обычное ревью списком |
| пара | `contradicts` | обязательное ревью пары, одно действие: оставить оба / `replaces` / снять |

Инвариант «решения принимает человек» сохраняется для всего, что **меняет смысл**:
повышение в `verified`, конфликты, нормативные утверждения, `replaces`. Для
переноса проверенной цитаты из книги в `draft`-факт человек не нужен — иначе
10 000 фактов ревью не переживёт (в литературе времени ревью нет ни у кого;
единственный ориентир — «один источник трогает 10–15 страниц» у Karpathy).
Выборочная проверка split/merge — ~50 фактов на главу: аннотаторы FActScore
разделяли 18 % и сливали 34 % LLM-фактов.

`heal` расширяется на `fact`: дубликаты и противоречия между книгами через ту же
пару «kNN → NLI», с кешем по хешам пары, как сейчас.

---

## 9. Lint (дополнения)

| код | проверка |
|---|---|
| `E_CLAIM_MISSING` | у `fact` нет `claim` или он вне 20–200 символов |
| `E_DOMAIN_UNKNOWN` | домена нет в `schema/domains.yaml` |
| `E_VALID_FOR_MISSING` | `kind ∈ {number, api, pitfall}` без `valid_for` |
| `W_FACT_LONG` | тело факта > 1 500 символов |
| `W_FACT_NO_HUB` | нет `about` |
| `W_HUB_EMPTY`, `W_HUB_TOO_LARGE` | 0 или > 60 фактов |
| `W_HUB_FACTS_MISMATCH` | `Facts` хаба ≠ множество `has_fact` |
| `W_HUB_CITES_OUTDATED` | хаб перечисляет факт со `status: outdated` |
| `W_POSSIBLE_DUPLICATE` | kNN-кандидат без вердикта судьи |
| `W_CONTRADICTION_UNRESOLVED` | пара `contradicts` старше 30 дней (advisory) |
| `W_STALE_VERSION` | `valid_for` ниже `current_version` связанного `tech` |
| `W_REPLACED_LINKED` | новые ссылки на `tech`/`fact` с `replaced_by` |
| `W_HIGH_DEGREE_DRAFT` | `draft`-факт со степенью ≥ 20: разделяемое ребро — единая точка отказа (GraphRAG under Fire, 2501.14050: одно ошибочное общее отношение протекает в 98 % ответов) |
| `W_QUESTION_STALE` | `question` без движения 90 дней |
| `W_NOVELTY_UNSET` | у `sourced`-факта нет `novelty` для `reference_model` профиля |

---

## 10. Eval-набор (новое)

Без него каждая константа — гипотеза навсегда. Файл `tests/fixtures/kb-eval.yaml`,
50–100 вопросов, заводится на этапе 1 по корпусу из 50 рукописных фактов и растёт
с каждой книгой. Структура по GraphRAG-Bench:

```yaml
- q: "how should I name a public function and document it?"
  lang: en
  hops: multi            # single | multi
  gold: [f-rust-fn-naming-snake-case, f-rust-doc-comment-triple-slash]
- q: "как назвать функцию в Rust"
  lang: ru
  hops: single
  gold: [f-rust-fn-naming-snake-case]
```

Метрики: Recall@8 по id для `seeds[]`, Recall@20 для `seeds ∪ expanded`,
отдельно single/multi и ru/en; доля запросов, где `expansion_used` и где оно
подняло recall. Этот же набор (плюс 100–200 размеченных пар «дубликат / refines /
contradicts / разные») используется для: выбора модели эмбеддингов, α и
dense-prior, λ слияния, порога kNN-кандидатов, весов рёбер, усечённого SliCK.
Запускается в CI как `pytest -m eval`, порог — не ниже предыдущего зафиксированного.

---

## 11. Оптимизация существующего кода

Разбор кода на `d420a5f` — в `docs/code-analysis-d420a5f.md`. Здесь — что менять,
зачем и какой выигрыш ожидается. Порядок — по отношению «выигрыш / усилия».

### 11.1. Нормализация (`index/normalize.py`)

Сейчас: `normalize()` создаёт два `Stemmer` на каждый вызов; `expand_synonyms()`
на каждый вызов заново нормализует все значения всех групп; при индексации это
3 вызова на чанк, при поиске — на каждое слово.

- Стеммеры — модульные синглтоны (`functools.cache`). PyStemmer не потокобезопасен
  для одного объекта — держать по экземпляру на поток (`threading.local`).
- Синонимы: при загрузке registry один раз строить `dict[normalized_word → frozenset[group]]`;
  `expand_synonyms` становится O(слов), а не O(слов × групп × значений).
- Добавить `normalize_many(list[str])` для батчевой индексации.

Ожидание: индексация ускоряется в разы (стемминг сейчас доминирует), поиск —
заметно на длинных запросах. Поведение не меняется — проверяется golden-тестами
`test_normalizer_and_query`.

### 11.2. Индексация (`index/indexer.py`, `db.py`)

- `executemany` для `pages`, `chunks`, `chunks_fts`, `edges`; одна транзакция уже есть.
- Инкрементальный reindex грузит и парсит **все** страницы из БД дважды
  (`self.pages()` в начале и при вычислении `old_ids`). Заменить: `old_ids` —
  `SELECT id FROM pages WHERE path IN (…)` до удаления; `all_pages` для
  `validate_set` — собирать из БД **без** полного парсинга frontmatter: кросс-страничные
  проверки нуждаются только в `id`, `type`, `path`, `relations`, `extra.lifecycle/applies_to`
  — хранить их в отдельной лёгкой таблице `page_meta` или читать из колонок.
- `ValidationCache` считает ключ через `fm.model_dump_json()` для каждой страницы на
  каждом проходе — ключ должен быть `content_hash` (он уже есть и покрывает
  frontmatter + body).
- Рёбра: не делать `SELECT * FROM pages WHERE id=?` + `row_page` на каждую страницу
  — `edges(page)` уже вычислен в `validate_set`, брать из кеша.
- `issues`: не перезаписывать целиком при инкременте — `DELETE WHERE path IN (…)`.
- FTS: колонка `title` (title + summary + aliases) дублируется в каждом чанке.
  Вариант без изменения ранжирования — внешний контент: `chunks_fts(..., content='chunks_norm')`
  с отдельной таблицей нормализованного текста, чтобы не хранить его дважды; либо
  отдельный FTS-ряд уровня страницы и `bm25()` по двум таблицам с RRF. Для L0-уровня
  `claim` в любом случае нужен **свой FTS-ряд на страницу** (`facts_fts(claim, title, aliases)`),
  иначе 60 чанков хаба съедят все слоты `LIMIT`.
- Индексы `pages(type)`, `pages(status)`, `chunks(page_id)`; `PRAGMA synchronous=NORMAL`,
  `cache_size=-65536`, `mmap_size` для read-соединений.
- Соединения: пул из одного write-соединения и N read-соединений вместо
  `connect()` на каждый вызов; `IndexDB.connect()` сейчас ещё и выполняет
  `PRAGMA journal_mode=WAL` каждый раз.

### 11.3. Поиск (`index/search.py`)

- `LIMIT 50` считает чанки: страница с 10 совпадающими чанками занимает 10 слотов.
  Заменить дедуп в Python на оконную функцию в SQL:
  ```sql
  SELECT * FROM (
    SELECT …, bm25(chunks_fts,6.0,3.0,1.0) AS rank,
           row_number() OVER (PARTITION BY c.page_id ORDER BY bm25(chunks_fts,6.0,3.0,1.0)) AS rn
    FROM chunks_fts JOIN chunks c ON … JOIN pages p ON …
    WHERE chunks_fts MATCH ? AND …
  ) WHERE rn = 1 ORDER BY rank, id LIMIT ?
  ```
- Не тянуть `p.*` (body, metadata) — только нужные колонки; тело грузится по id для
  L2 отдельно.
- Один connection на весь вызов, а не на каждый оператор AND/OR.
- `expand=True` сейчас: `neighbors()` для топ-3 (≈ 4 запроса каждый) + по
  соединению и `SELECT` на каждого соседа, вес 0.25 фиксированный. Заменяется
  целиком на PPR из раздела 7.2 поверх снимка графа в памяти; страницы соседей —
  одним `SELECT … WHERE id IN (…)`.
- `rules_related` (`services/rules.py`): до 50 × (`page` + `neighbors` + `impact(depth=2)`)
  + ещё `search(k=50)` по каждому `impact_terms`. Переписать через `ask` с
  `scopes=rule`: семена → PPR с whitelist `refines/conflicts_with/supersedes/depends_on/governed_by/implements`
  → одна выборка страниц. Ожидание: с сотен запросов до ~5.
- `Rules.list_rules` с `q`: `SELECT * … WHERE type='rule'` без индекса и парсинг всех
  строк — после индекса `pages(type)` и выборки только нужных колонок исчезает.

### 11.4. Граф (`index/graph.py`)

- Снимок в памяти (раздел 5): `networkx` не нужен; `scipy.sparse.csr_matrix` +
  `numpy`-массивы `id ↔ idx`, `type`, `status`, `sensitivity`. Строится из
  `SELECT src,dst,rel,weight FROM edges UNION soft_edges` за один проход,
  инвалидируется по `meta.generation`. `neighbors/path/impact/subgraph` переводятся
  на этот снимок: BFS по `indptr/indices` без SQL; допуск — булева маска по
  `sensitivity`, применяется к столбцам до обхода (эквивалент текущего
  `visible_edges`, проверяется golden-тестом `graph-golden.json`).
- `path`: ранний выход при достижении цели; двунаправленный BFS.
- `_edges`: сейчас выбирает по `src IN` и фильтрует `dst ∈ ids` в Python — в
  снимке это пересечение множеств; в SQL-варианте — `AND dst IN (…)`.
- `export`: не `SELECT *` с телами — только `id,type,title,summary,status`.
- PPR: `scipy.sparse.linalg`-free power iteration:
  ```python
  pi = r.copy()
  for _ in range(max_iter):
      new = alpha * r + (1 - alpha) * (PT @ pi)
      if np.abs(new - pi).sum() < tol: break
      pi = new
  ```
  где `PT` — столбцово-нормированная транспонированная матрица весов с
  `f_status` уже умноженным; `r` — reset-вектор из 7.2. На 50k узлов / 500k
  рёбер — единицы миллисекунд на итерацию.
- `benchmark_graph.py`: добавить inverse-рёбра (индексатор удваивает их), сценарии
  `path`, `impact`, `restricted`, PPR с проверкой допуска сходимости; порог
  PPR ≤ 50 мс на 50k/500k.

### 11.5. Контекст и сборка (`index/context.py` → `index/assemble.py`)

- N+1: `pages.page(id)` на каждый узел → один `SELECT … WHERE id IN (…)`.
- Ключ сортировки сканирует все рёбра на каждый узел (O(N·E)) → один проход по
  рёбрам с накоплением лучшего приоритета в `dict[node → prio]`.
- `delivery_stats`: запись на пути чтения в отдельном соединении на каждый вызов.
  Перевести в очередь в памяти с периодическим `executemany` (раз в N секунд или
  N записей) и писать выданные `ids` (нужно для `f_usage`). `Lint.stats` читать
  агрегатами в SQL, а не всю таблицу в Python.
- Бюджет — в токенах, оценка `len/4` для английского (реальные ~4 символа на
  токен у всех современных токенизаторов; текущие 2.5 завышают расход на 60 %),
  `len/3` для текста с кириллицей (консервативно под Claude, где русский ~3×).
  Константа `chars_per_token` становится парой `{latin: 4.0, cyrillic: 3.0}` и
  выбирается по доле кириллицы в строке.
- Корень сейчас никогда не обрезается; в новой сборке корень режется до L1,
  если не влезает, и это попадает в `truncated_ids`.
- Обрезка по разделам останавливается на первом невлезшем; для L2 продолжать
  пробовать следующие (короткий `Caveats` может влезть после длинного `Example`).

### 11.6. Политики (`services/policies.py`) — тот же код станет `services/brief.py`

- Жадное наполнение рендерит весь markdown заново на каждого кандидата (O(n²)),
  и каждый рендер до 10 итераций фикс-пойнта по `{used_tokens}`. Заменить:
  посчитать стоимость каждой строки один раз, накапливать сумму, рендерить
  один раз в конце; `{used_tokens}` подставлять после рендера с запасом на
  ширину числа (1 итерация).
- Промах кеша грузит и парсит **все** страницы → `SELECT … WHERE type='rule'`
  (индекс `pages(type)`) с нужными колонками.
- Шаблон читается с диска на каждый вызов → кеш по `mtime`.
- `count_usage` пишет в state DB на каждый вызов, включая попадания в кеш →
  в ту же очередь, что `delivery_stats`.
- Кеш: ключ включает полный текст шаблона — заменить на его хеш.

### 11.7. Домен (`domain/`)

- `ids.page_path`: добавить плейсхолдер `{domain}`; валидировать `domain` по
  `schema/domains.yaml` до вычисления пути.
- `Frontmatter.relations`: `dict[str, list[str | RelationRef]]`, где
  `RelationRef = {id, w?, note?, origin?}`; `edges(page)` отдаёт `Edge(weight, note, origin)`.
- `ExtraField.default` объявлен, но не применяется — применить в `valid_extra`
  (нужно для `novelty`, `origin`, `priority`).
- `ExtraField.type` += `dict` (для `novelty`) и `date` (для `valid_from/to`).
- `validate_page` считает `edges(page)` до двух раз и `without_code` дважды внутри
  `edges()` — считать один раз, передавать дальше.

### 11.8. Ingest (`wikiagent/jobs/ingest_book.py`, `services/extractions.py`)

- `GET /rules/related` на каждое окно **даже когда результат окна уже в чекпоинте**
  → чекпоинтить вместе с результатом; после 11.3 сам вызов дешевеет на порядок.
- Классификация: `GET /pages/{id}` на каждый `known`-id на каждого кандидата →
  кеш страниц на главу (они не меняются внутри job).
- `candidate_id()`: `client.all("/rules", lifecycle=all)` на каждого нового
  кандидата → загрузить множество id один раз на запуск, пополнять локально.
- Проверка цитаты: повторный `GET /raw/…/text` на каждого кандидата → excerpt окна
  уже в памяти, проверять по нему; за границы окна ходить только при промахе.
- `services/extractions.py::text` перечитывает весь `pages.jsonl` на каждый вызов
  → кеш по `sha` в памяти процесса; нарезка `text[offset:offset+max_chars]` —
  по границам абзацев/предложений с перекрытием (раздел 8.2).
- `context()` обрезает состояние с пересчётом `json.dumps` на каждом шаге (O(n²))
  → считать длину полей один раз, резать арифметически.
- Окно 8 000 токенов × 2.5 = 20 000 символов → разделы 1 000–2 000 токенов (8.2);
  `ChapterResult.candidates ≤ 10` на окно поднять до 40 — при разделе в 1 500
  токенов это и есть ожидаемый выход.

### 11.9. Heal (`wikiagent/heal/`)

- `neighbors` для изменённых страниц запрашивается дважды → один раз.
- Линейный скан всех страниц по категории/scopes на каждую выбранную — O(N²) →
  индекс `dict[(category, scope) → set[id]]`, строится один раз на запуск.
- Два `SELECT COUNT(*) FROM model_calls` на каждую пару → один счётчик на запуск,
  инкремент в памяти.
- Для фактов партнёры выбираются не поиском по `summary`, а kNN по `claim`-векторам
  (та же recall-стадия, что в 8.4), затем NLI-судья до LLM: дешёвый cross-encoder
  отсеивает «независимые» пары, LLM видит только entail/contradict-кандидатов.

### 11.10. MCP (`mcp_server.py`, `tool_contracts.py`)

- Глобальный потолок размера ответа (по умолчанию 8 000 токенов, предупреждение
  Claude Code с 10 000) и `budget_tokens` у всех читающих инструментов;
  `get_page`/`neighbors` сейчас не ограничены.
- Профиль `knowledge` (раздел 7.3); ответы — компактный markdown в одном текстовом
  поле, а не вложенный JSON.
- Имена инструментов без подчёркиваний в имени сервера (Gemini CLI: `mcp_{server}_{tool}`
  ≤ 63 символов, коллизии перезаписываются).

### 11.11. Зависимости и окружение

- `numpy`, `scipy` — в `pyproject.toml` и `flake.nix` (есть в nixpkgs). Для NLI-судьи
  и reranker'а — `onnxruntime` + `tokenizers` либо тот же `llama-server`
  (reranker поддерживается). Избегать `torch` в runtime-зависимостях ядра: судья
  и reranker живут в `wikiagent`.
- `benchmark_graph.py` расширяется до `benchmark_retrieval.py` с eval-набором из
  раздела 10 и перф-порогами; добавляется `pytest -m eval` и `-m perf`.

---

## 12. Что менять в коде (карта для агентов, по этапам)

| # | компонент | изменение | этап |
|---|---|---|---|
| 1 | `template/schema/page-types/` | `topic`, `fact`, `tech`, `question`; `source` += kinds, `covers`; `rule/adr/pattern/playbook` += `grounded_in` | 1 |
| 2 | `domain/ids.py`, `registry.py`, `models.py`, `validate.py` | `{domain}`; `schema/domains.yaml`; `RelationRef`; `ExtraField` default/dict/date; `edges` один раз | 1 |
| 3 | `template/schema/relations.yaml`, `scopes.yaml` | раздел 4 + `weight`; оси и иерархия | 1 |
| 4 | `index/normalize.py` | 11.1 | 1 |
| 5 | `tests/fixtures/kb-eval.yaml`, `pytest -m eval` | раздел 10 | 1 |
| 6 | `index/db.py`, `indexer.py` | схема раздела 5, 11.2, `facts_fts`, порядок фактов из хаба, `soft_edges`, `node_stats` | 2 |
| 7 | `index/embeddings.py` | `OpenAICompatibleEmbeddings` + self-test; три уровня | 2 |
| 8 | `index/graph.py` | снимок CSR, PPR с допуском, 11.4 | 2 |
| 9 | `index/search.py`, `index/assemble.py` | 11.3, 11.5; `ask` с условным расширением | 2 |
| 10 | `services/brief.py` (из `policies.py`) | 7.1, 11.6 | 2 |
| 11 | `mcp_server.py`, `tool_contracts.py` | профиль `knowledge`, 11.10 | 2 |
| 12 | `wikiagent` `ingest-book` | разделы 8.2–8.4, 8.6, 11.8 | 3 |
| 13 | `wikiagent` `novelty_scan`, `heal` для фактов | 8.5, 11.9 | 3 |
| 14 | `domain/validate.py`, `services/lint.py` | раздел 9 | 3 |
| 15 | `template/AGENTS.md`, `workflows/` | `knowledge-query.md`, `fact-authoring.md`, `book-ingest.md` | 3 |
| 16 | `ui/` | граф с весами, список фактов хаба, ревью списком claims, маршрутизация 8.6 | 4 |

---

## 13. Этапы

**Этап 1. Схема, ручные факты, eval.** Пункты 1–5. Приёмка: `wikisvc init` создаёт
`kb/` по дереву доменов; 50 фактов, 8 хабов, 3 tech, 2 question, написанные руками
по теме, которую ты знаешь хорошо (io_uring или `tokio`); eval-набор на 50 вопросов
с gold id (ru и en, single и multi); 100 размеченных пар для дедупа; lint зелёный;
старые правила и политики работают без изменений; индексация фикстурной вики
после 11.1 быстрее не менее чем в 3 раза (замер в `-m perf`).

**Этап 2. Доставка.** Пункты 6–11. Приёмка: на корпусе этапа 1 запрос «как называть
функции» через `ask` возвращает факт про doc-комментарии в `expanded[]`; русский
запрос находит английский факт; Recall@8 семян и Recall@20 с расширением
зафиксированы как базовая линия, `expansion_used` включается только на multi-hop
вопросах из набора; `get_brief` влезает в бюджет и включает только
`differs`/`unique`; `omitted_ids` непустой при малом бюджете; выдача одинакова
между двумя запусками (канонический порядок); PPR на синтетике 50 000 узлов /
500 000 рёбер ≤ 50 мс с допуском $10^{-6}$; golden-тесты графа и поиска проходят
на снимке в памяти; `rules_related` на фикстурах даёт тот же результат за ≤ 10 SQL-запросов.

**Этап 3. Ingest книги.** Пункты 12–15. Приёмка: «The Rust Programming Language»
проходит целиком по разделам; доля дубликатов между главами после судьи < 5 %;
у ≥ 90 % фактов есть проверенная цитата; доля фактов, ушедших в «авто», ≥ 70 %;
очередь ревью — только `inferred`/`refines`/`contradicts`/`convention`/`unique`;
`novelty_scan` для референсной модели проставлен на ≥ 95 % фактов; выборочная
проверка split/merge на 50 фактах главы — ≤ 25 % расхождений с человеком.

**Этап 4. Качество.** Пункт 16, `heal` для фактов, UI. Первый замер полезности:
20 задач по Rust/HPC с brief и без, сравнение ответов на «делает как я»; метрики
eval-набора после первой книги не ниже базовой линии этапа 2.

**Потом, отдельным ТЗ:** веса из использования (`f_usage`), личный слой (события,
люди, хронология), подключение внешних клиентов через туннель (Claude.ai требует
публичный HTTPS для connectors).

---

## 14. Что изменилось в ревизии 2

| было (ревизия 1) | стало | основание |
|---|---|---|
| PPR α = 0.15, 20 итераций | α = 0.5, останов по допуску $10^{-6}$, dense-prior 0.05 на все узлы, IDF-специфичность семян | HippoRAG/HippoRAG 2 (2405.14831, 2502.14802); при 0.15 за 20 итераций остаток 4 % |
| расширение по графу всегда | условное + fallback на гибридный поиск | GraphRAG-Bench, RAG vs GraphRAG, VLDB-фреймворк |
| дедуп по косинусу 0.80 / 0.92 | косинус ≥ 0.80 только как recall; решает двунаправленный NLI/LLM-судья; один проход даёт dup/refines/contradicts | ни одного валидированного порога в литературе; KGGen, Mem0, Graphiti, iText2KG |
| `novelty` ставит агент | per-model, усечённый SliCK фоновой задачей | FActScore: самооценка ±7–35 %; SliCK |
| `claim` ≈ `summary` | пара «минимальный claim / деконтекстуализированный summary» | DnDScore, Molecular Facts |
| нет времени действительности | `valid_from/valid_to`, `replaced_by ⇒ outdated`, `W_HUB_CITES_OUTDATED` | Zep bi-temporal; MemoryAgentBench |
| `valid_for` необязателен | обязателен для `number/api/pitfall` | CLAIRE: ложные противоречия из-за отсутствия квалификатора |
| окно ingest 12k токенов | разделы 1–2k токенов с глобальным списком хабов и few-shot | GraphRAG, iText2KG, Wanner et al. |
| Rust Book → 800–1 500 фактов | 8 000–12 000 сырых; предложения по хабам; трёхуровневая маршрутизация ревью | Dense X, CLAIRE |
| нет `kind: snippet` | есть | ни один экстрактор не работает с кодом |
| семена только по `claim`-векторам | по всем трём уровням одним пулом | RAPTOR |
| `len/3.5` | `{latin: 4.0, cyrillic: 3.0}` | замеры токенизаторов 2026 |
| нет eval-набора | раздел 10, с этапа 1 | без него константы — гипотезы |
| нет reranker | опциональный на шаге L0 → L1 | RusBEIR +4.7 nDCG@10 |
| нет `origin` у рёбер | `manual / extracted / inferred` | Pulse8 Cortex |
| нет lint на степень | `W_HIGH_DEGREE_DRAFT` | GraphRAG under Fire |
| карта кода без оптимизаций | раздел 11 по разбору `d420a5f` | — |
