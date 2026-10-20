# ADR-0027 — Ingest окнами 1–2k токенов с глобальным списком хабов и few-shot
status: accepted | date: 2026-10-20

## Контекст

Сейчас JOB-wikiagent.ingest-book режет главу окнами около 8 000 токенов (× 2.5 = 20 000 символов) и
берёт ≤ 10 кандидатов на окно (ТЗ §11.8); ревизия 1 ТЗ предлагала окна 12k токенов (ТЗ §14). Для фактов
это даёт пропуски, а без общего контекста модель плодит новые хабы вместо существующих.

## Решение

- Окно — раздел главы 1 000–2 000 токенов с перекрытием в один абзац (CFG-wikiagent.ingest.window_tokens,
  CFG-wikiagent.ingest.overlap_paragraphs); нарезка по границам абзацев (CLS-wikisvc-core.Extractions).
- В каждое окно: текст раздела; глобальный список хабов и `tech` домена (id + title, ≤ 300 строк,
  CFG-wikiagent.ingest.hub_list_max); `state` — скользящая выжимка главы ≤ 1 500 токенов; 5–8 эталонных фактов
  вики как few-shot (CFG-wikiagent.ingest.fewshot_facts).
- До 40 кандидатов на окно (CFG-wikiagent.ingest.max_candidates_per_window, DTO-wikiagent.ChapterResult);
  кандидат — DTO-wikiagent.FactCandidate. Скелет хабов из оглавления — одним вызовом (PRM-wikiagent.hub_skeleton).
- Результат окна чекпоинтится вместе с вызовом поиска хабов, страницы кешируются на главу (ТЗ §11.8).
- MDL-propositionizer-flan-t5 — только разовый офлайн-прогон на одной главе: 5–8 выходов — few-shot-эталон
  (решение Q-kb-mdl-propositionizer); в runtime не входит.
- Между проверкой подстроки цитаты и дедупом — шаг grounding: факт следует из цитаты или абзаца (MDL-grounding-judge,
  PRM-wikiagent.fact_ground, ADR-0022).
- Режим ingest по умолчанию — `facts` (`rules` — явным параметром); пределы задачи — 500 окон и 20 000 вызовов
  модели, исчерпание — `paused` (решение Q-kb-ingest-defaults, Q-kb-ingest-rules-mode).

## Почему

- GraphRAG работает чанками 300–1 200 токенов (ТЗ §8.2);
- iText2KG: глобальный контекст стоит ~10 пунктов precision, но даёт переиспользование сущностей; без него граф
  раздувается на 30 % (ТЗ §8.2);
- in-context примеры влияют на гранулярность сильнее инструкции: DecompScore 42.3 против 20.0 при одинаковых
  инструкциях; выход меняется в 2× только от few-shot (arXiv:2403.11903; ТЗ §8.1–8.2);
- раздел в 1 500 токенов — это и есть ~40 ожидаемых кандидатов (~2.3 proposition на предложение, Dense X; ТЗ §8.1, §11.8).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| глава или окно 8–12k токенов (сейчас и ревизия 1) | пропуски фактов; лимит 10 кандидатов на окно (ТЗ §11.8, §14) |
| окна без глобального списка хабов | граф раздувается на 30 % (iText2KG) |
| хабы по главам | хабы — по понятиям: `top-rust-ownership`, а не `top-rust-book-ch4`; оглавление — в `source.covers` (ТЗ §8.4) |

## Последствия

- вызовов модели на книгу больше в несколько раз (окна меньше); контекст 16 384 у развёрнутой Gemma (сейчас 12B, MDL-gemma-12b) должен
  вместить окно, список хабов, `state`, few-shot и ответ на 40 кандидатов — проверяется замером, не расчётом;
- приёмка этапа 3 — NFR-ingest-quality;
- затрагивает: JOB-wikiagent.ingest-book, FLOW-fact-ingest, FLOW-ingest-book, PRM-wikiagent.fact_extract,
  PRM-wikiagent.book_chapter, PRM-wikiagent.hub_skeleton, PRM-wikiagent.fact_links, DTO-wikiagent.ChapterResult,
  DTO-wikiagent.FactCandidate, CFG-wikiagent.limits.chapter_chunk_tokens, CFG-wikiagent.ingest.window_tokens,
  CFG-wikiagent.ingest.overlap_paragraphs, CFG-wikiagent.ingest.hub_list_max, CFG-wikiagent.ingest.fewshot_facts,
  CFG-wikiagent.ingest.max_candidates_per_window, CLS-wikisvc-core.Extractions, FMT-wikisvc-core.source,
  MDL-gemma-12b, MDL-propositionizer-flan-t5, RES-llama-server, ADR-0022, ADR-0024.
