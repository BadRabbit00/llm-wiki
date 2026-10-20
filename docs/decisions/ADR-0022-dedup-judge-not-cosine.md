# ADR-0022 — Дедупликация: косинус только отбирает кандидатов, решает NLI/LLM-судья
status: accepted | date: 2026-10-20

## Контекст

Ingest книги даёт 8 000–12 000 сырых фактов (ТЗ §8.1), между главами и книгами много повторов,
уточнений и противоречий. Ревизия 1 ТЗ резала дубликаты порогами косинуса 0.80 / 0.92 (ТЗ §14).
Самолечение (`heal`) ищет те же пары между книгами (ТЗ §8.6, §11.9).

## Решение

- Recall-стадия: kNN по `claim`-векторам (ADR-0018), косинус ≥ 0.80 → до 10 кандидатов
  (CFG-wikiagent.ingest.dup_cosine, CFG-wikiagent.ingest.dup_k); видны и черновые факты открытых предложений
  книг (`include_pending`, решение Q-kb-knn-endpoint). Порог калибруется на размеченных парах
  `tests/fixtures/kb-pairs.yaml` (ADR-0025) и не переносится между моделями эмбеддингов.
- Судья — две роли (решение Q-kb-nli-judge-model, Q-kb-judge-runtime):
  - claim ↔ claim — двунаправленный NLI MDL-nli-judge (`MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`),
    A/B — MDL-nli-modernbert, массовый фон — MDL-nli-judge-light. A ⊨ B и B ⊨ A — дубликат (не создаём,
    `add_source` к существующему); одностороннее entailment — `refines`; contradiction — `contradicts`, оба
    `confidence: contested`, пара — в обязательное ревью (ADR-0024); иначе — независимые;
  - claim ↔ источник (grounding) — MDL-grounding-judge (FactCG-DeBERTa-L), эскалация MDL-grounding-escalation:
    новый шаг ingest между проверкой подстроки цитаты и дедупом (CLS-wikiagent.GroundingJudge, PRM-wikiagent.fact_ground).
- Каскад: NLI по всем kNN-кандидатам → LLM-судья — развёрнутая Gemma на RES-llama-server (сейчас 12B, MDL-gemma-12b;
  PRM-wikiagent.fact_judge), тот же процесс, отдельного нет (решение Q-kb-judge-llm-server)
  только на contradiction и на парах с уверенностью < 0.7; уверенный duplicate LLM не подтверждается. Пороги
  стартовые entail 0.7 / contradiction 0.7 (CFG-wikiagent.judge.entail_threshold,
  CFG-wikiagent.judge.contradiction_threshold), калибруются на размеченных парах.
- Вердикты, включая independent, агент пишет в ядро (API-wikisvc.knowledge.verdicts →
  TBL-wikisvc-core.state.pair_verdicts); lint `W_POSSIBLE_DUPLICATE` и класс ревью читают их; вердикт устаревает
  при смене `content_hash` любой стороны.
- `heal` для фактов — та же цепочка kNN → NLI → LLM (ТЗ §11.9).
- Исполнение NLI и grounding — DEP-py-onnxruntime в `wikiagent`, не в ядре (ТЗ §11.11; ADR-0003).

## Почему

- валидированного косинус-порога «тот же факт» нет ни в одной работе; KGGen, Mem0, Graphiti, iText2KG
  используют LLM как судью (ТЗ §0, §14);
- один проход судьи даёт дубликаты, `refines` и `contradicts` вместо трёх эвристик (ТЗ §8.4);
- 0.80 совпадает с τ synonymy-рёбер HippoRAG — как recall-порог, не как решение (ТЗ §4);
- ожидания по противоречиям: сильная модель с CoT — precision 0.95 при recall 0.57, 8B-модели ~1 %
  (arXiv:2504.00180) — поэтому `W_CONTRADICTION_UNRESOLVED` advisory (ТЗ §8.4).

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| пороги косинуса 0.80 / 0.92 (ревизия 1) | нет валидированного порога; порог зависит от модели эмбеддингов (ТЗ §14) |
| только LLM-судья на всех парах | дорого: ограничено NFR-agent-model-budget; cross-encoder отсеивает независимые дешевле (ТЗ §11.9) |
| совпадение по хешу текста | ловит только буквальные копии, не перефразы |

## Последствия

- в `wikiagent` появляются DEP-py-onnxruntime и DEP-py-tokenizers (согласие получено, Q-kb-onnxruntime-consent) и
  несколько ONNX-моделей на хосте (`/srv/llm-wiki/models/`, решение Q-kb-models-dir);
- LLM второй ступени делит RES-llama-server (один слот) с planner, reviewer, chat, ingest и novelty — очередь к
  модели длиннее; 12B-класс находит малую долю противоречий (ТЗ §8.4) — RISK-kb-contradiction-recall;
- эскалация grounding (MDL-grounding-escalation) на этапе 3 — PRM-wikiagent.fact_ground на развёрнутой Gemma в
  RES-llama-server, отдельного процесса нет (Q-kb-grounding-escalation); `Bespoke-MiniCheck-7B` (CC-BY-NC) или
  `Granite Guardian 3.3` (Apache-2.0) — опция на будущее при отдельном процессе и VRAM (Q-stack-license-policy);
- 8B-класс находит ~1 % противоречий (ТЗ §8.4) — `W_CONTRADICTION_UNRESOLVED` остаётся advisory;
- нужен размеченный набор 100–200 пар «дубликат / refines / contradicts / разные» (ТЗ §10, FMT-wikisvc-core.kb-eval);
- затрагивает: FLOW-dedup-judge, FLOW-fact-ingest, FLOW-heal, MOD-wikiagent.judge, CLS-wikiagent.GroundingJudge,
  PRM-wikiagent.fact_judge, PRM-wikiagent.fact_ground, PRM-wikiagent.heal_pair, DTO-wikiagent.JudgeVerdict,
  JOB-wikiagent.ingest-book, JOB-wikiagent.heal, CFG-wikiagent.ingest.dup_cosine, CFG-wikiagent.ingest.dup_k,
  CFG-wikiagent.models.judge_llm, CFG-wikiagent.models.grounding, CFG-wikiagent.judge.entail_threshold,
  CFG-wikiagent.judge.contradiction_threshold, API-wikisvc.knowledge.verdicts, TBL-wikisvc-core.state.pair_verdicts,
  MDL-nli-judge, MDL-nli-judge-light, MDL-nli-modernbert, MDL-grounding-judge, MDL-grounding-escalation, MDL-gemma-12b, RES-llama-server,
  MDL-bge-m3, TERM-judge, ADR-0018.
