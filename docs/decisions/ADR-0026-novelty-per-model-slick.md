# ADR-0026 — `novelty` per-model: усечённый SliCK фоновой задачей
status: accepted | date: 2026-10-20

## Контекст

`get_brief` должен класть в контекст то, чего модель не знает сама (FLOW-knowledge-brief). Frontier-модель
знает почти всю Rust Book, локальная 8B — нет (ТЗ §3.1). В ревизии 1 `novelty` ставил агент-экстрактор (ТЗ §14).

## Решение

- `novelty` — бакет `common | differs | unique` на пару (факт, семейство модели); ключ — семейство (`claude-sonnet`,
  `gemini-pro`, `gemma`), не точная версия; новая версия — повод пересчитать, не обязанность.
- Хранится производно в TBL-wikisvc-core.state.novelty (`page_id`, `model_family`, `bucket`, `measured_at`,
  `content_hash`); агент пишет через API-wikisvc.knowledge.novelty; предложений нет, `verified` не трогается;
  поле `novelty` во frontmatter — только ручное переопределение (решение Q-kb-novelty-write-path).
- Per-model для потребителя: `get_brief` принимает `model` от клиента, профиль хранит только значение по умолчанию.
  Нет бакета — `differs` (факт доставляется).
- Процедура, а не самооценка: усечённый SliCK — `claim` → cloze-вопрос (PRM-wikiagent.novelty_cloze), 2 парафразы ×
  5 сэмплов при T = 0.5 (PRM-wikiagent.novelty_answer), NLI-судья сравнивает ответ с `claim`
  (PRM-wikiagent.novelty_judge, MDL-nli-judge) — ≈ 11 вызовов на факт; доля попаданий ≥ 0.8 — `common`,
  0.2–0.8 — `differs`, < 0.2 — `unique` (решение Q-kb-novelty-defaults).
- Лениво: только для фактов из кандидатов brief какого-то профиля и только когда клиент с этой моделью впервые
  запросил brief; остальное — локальной моделью в фоне. Задача JOB-wikiagent.novelty-scan выключена по умолчанию,
  ≤ 2000 вызовов в сутки (CFG-wikiagent.novelty.max_calls_per_day), окна и простой общие с `heal`; ingest `novelty`
  не ставит. `unique` идёт в очередь ревью (ADR-0024).
- Внешняя модель — только через официальный SDK за интерфейсом провайдера (`rule-stack-llm-providers`), `https`,
  ключ из `token_env`; наружу — только факты `sensitivity: public` (фильтр в коде); для `internal` и `restricted` —
  только локальные модели (решение Q-kb-novelty-reference-model). На практике внешний провайдер сейчас не подключается.

## Почему

- closed-book самооценка расходится с правдой на 7–35 % (FActScore, arXiv:2305.14251; ТЗ §3.1);
- SliCK (arXiv:2405.05904) — процедура для «знает ли модель факт»; полный — ~170 вызовов на факт,
  усечённый — 10–30 (ТЗ §8.5);
- ценны только детали, которые модель не выведет сама: +4 % success у рукописных инструкций, −3 % у
  сгенерированных LLM (ETH, arXiv:2602.11988; ТЗ §1, §7.1) — `common` в brief не идёт;
- фоновой задачей — чтобы не тормозить ingest и пересчитывать под новую референсную модель.

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| самооценка агентом (ревизия 1) | расхождение 7–35 % (ТЗ §14) |
| полный SliCK | ~170 вызовов на факт — неподъёмно на 10 000 фактов |
| одно глобальное значение `novelty` | знание зависит от модели (ТЗ §3.1) |
| считать в ingest | удлиняет ingest; референсная модель профиля может смениться |
| писать `novelty` во frontmatter через предложения | тысячи предложений на ревью и правки `verified`-фактов ради производного значения (Q-kb-novelty-write-path) |
| считать сразу для всех фактов и моделей | ≈ 11 вызовов × тысячи фактов × семейства моделей — лениво дешевле |

## Последствия

- потеря надёжности от усечения (2 парафразы вместо полного SliCK) в литературе не измерена — проверяется на eval
  (ADR-0025); RISK-kb-novelty-truncated, RISK-kb-untuned-constants;
- нагрузка на RES-llama-server: ≈ 11 вызовов на факт, но только для кандидатов brief; доля фактов с `novelty`
  ≥ 95 % (NFR-ingest-quality) считается по этим кандидатам;
- `novelty` — производные данные в RES-state-db, а не в git: пересчитываются, в историю страниц не попадают;
- облачный потребитель без бакета получает факт как `differs` — brief для него длиннее, чем мог бы быть;
- затрагивает: JOB-wikiagent.novelty-scan, JOB-wikiagent.scheduler, API-wikiagent.jobs.novelty-scan,
  API-wikisvc.knowledge.novelty, TBL-wikisvc-core.state.novelty, DTO-wikiagent.NoveltyResult,
  PRM-wikiagent.novelty_cloze, PRM-wikiagent.novelty_answer, PRM-wikiagent.novelty_judge, CFG-wikiagent.novelty.samples,
  CFG-wikiagent.novelty.temperature, CFG-wikiagent.novelty.paraphrases, CFG-wikiagent.novelty.common_threshold,
  CFG-wikiagent.novelty.unique_threshold, CFG-wikiagent.novelty.max_calls_per_day, FLOW-novelty-scan,
  FLOW-knowledge-brief, TERM-novelty, TERM-reference-model, ENT-profile, RES-state-db, MDL-nli-judge, MDL-gemma-12b.
