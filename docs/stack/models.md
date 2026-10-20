# Нейросети и ML-модели

В проекте одна языковая модель, обслуживаемая локально; ядро `wikisvc` модели не вызывает
(`AGENTS.md`, граница 4). Модель использует только `SVC-wikiagent` для трёх ролей: `planner`,
`reviewer`, `chat` (поле `models.<роль>` в `wikiagent.yaml`, FMT-wikiagent.config). Все роли
по умолчанию указывают на один и тот же endpoint и одну и ту же модель.

v3 (draft, слой знаний) добавляет энкодеры — эмбеддинги, reranker, NLI- и grounding-судьи (раздел «v3»
ниже); LLM-судьёй каскада работает уже развёрнутая Gemma на RES-llama-server (сейчас 12B, MDL-gemma-12b).
Энкодеры не генерируют текст, и при
фиксированном файле весов, сборке сервера и параметрах от них ожидается воспроизводимый результат
(ADR-0018; где это не гарантировано — RISK-kb-embeddings-determinism). Novelty для внешней модели-потребителя
считается только по `public`-фактам через официальный SDK; на практике внешний провайдер сейчас не
подключается (решение Q-kb-novelty-reference-model, ADR-0026). В проде — одна модель эмбеддингов и один
reranker; кандидаты A/B живут только в прогонах eval (`rule-stack-one-tool-per-job`, ADR-0025).

### MDL-wiki-gemma-31b — генерация текста для planner, reviewer и chat
status: implemented

- changed: 2026-10-20 v3 (planned): по словам владельца 31B в проде не развёрнута («мы её не знаем»);
  алиас `wiki-gemma-31b` в конфигурации указывает на развёрнутую Gemma 4 12B (MDL-gemma-12b). Кандидат на
  замену позже — Gemma 27B. Сведения ниже о 31B описывают шаблон `deploy/linux/`, а не работающий хост; ID не меняется
- task: генерация текста со структурированным JSON-ответом: планировщик правил, ревью, чат,
  извлечение утверждений из книг, самолечение, сверка документации (JOB-wikiagent.ingest-book,
  JOB-wikiagent.heal, JOB-wikiagent.docs-audit)
- source: Gemma 4 31B (GGUF), файл `gemma-4-31b.gguf`; алиас в llama-server — `wiki-gemma-31b`
  (`deploy/linux/llama.env`, `LLAMA_ARG_ALIAS`). Откуда скачан файл и какой репозиторий — в проекте
  не записано, см. Q-mdl-31b-source
- version pin: нет (веса кладёт оператор на хост; хеш и ревизия не зафиксированы), см. Q-mdl-31b-source
- license: в документах проекта не указана; лицензия Gemma — см. Q-mdl-31b-license
- size / format: GGUF, путь по умолчанию `/srv/llm-wiki/models/gemma-4-31b.gguf` (владелец
  `llm-model`, права 0640); квантование и размер файла не записаны (`ref/deploy-linux.md`, раздел 4,
  говорит лишь «замените путь и имя на свой GGUF»), для split GGUF указывается первая часть;
  см. Q-mdl-31b-quant
- runtime: RES-llama-server (`deploy/model.sh` запускает `$LLAMA_SERVER_BIN` — абсолютный путь к
  `llama-server`, и читает `$LLAMA_ARG_MODEL` — абсолютный путь к GGUF; оба задаются в
  `/etc/llm-wiki/llama.env`). Параметры из `deploy/linux/llama.env`: `127.0.0.1:18089`,
  контекст 16384, один слот (`N_PARALLEL=1`), `N_GPU_LAYERS=auto`, Flash Attention `on`, KV cache
  `q8_0`, `JINJA=1`, `REASONING=off`. Бинарник `llama-server`, его GPU-библиотеки и драйвер ставятся
  отдельно под оборудование; ни образ, ни хост-часть не включают CUDA или модель
  (`ref/deploy-linux.md`, раздел 4). hardware: объём VRAM для 31B в проекте не записан (Q-mdl-31b-quant)
- weights stored: на хосте вне репозитория и образа, `/srv/llm-wiki/models/` (путь из `llama.env`);
  в Nix store и в git не попадают
- config (`deploy/linux/wikiagent.yaml`): `model: wiki-gemma-31b`, `base_url: http://127.0.0.1:18089/v1`,
  `context: 16384`, `temperature: 0`, `structured: json_schema`, `timeout_seconds: 600` — одинаково
  для planner, reviewer и chat. Контекст и алиас обязаны совпадать в `llama.env` и `wikiagent.yaml`;
  `limits.chapter_chunk_tokens` = 4000 рассчитан на 16K (`ref/deploy-linux.md`, раздел 4)
- used by: SVC-wikiagent — промпты PRM-wikiagent.system, PRM-wikiagent.route, PRM-wikiagent.classify,
  PRM-wikiagent.extract_claims, PRM-wikiagent.locate_revision, PRM-wikiagent.revise_page,
  PRM-wikiagent.repair_validation, PRM-wikiagent.book_chapter, PRM-wikiagent.book_review,
  PRM-wikiagent.heal_pair, PRM-wikiagent.heal_review, PRM-wikiagent.docs_audit
- quality: оценка этой модели не проводилась. По `ref/deploy-linux.md`, раздел 4: «Эта модель ещё
  не проходила нашу оценку на данном сервере», проверка `llm-wiki-admin check --model` проверяет
  совместимость протокола, а не качество; прежний отчёт Gemma 12B не является оценкой 31B. Порог
  полного допуска — не менее 30 сценариев и не менее 90% правильных результатов (там же); в
  комплекте `tests/scenarios/*.yaml` 12 сценариев (`01-new` … `12-cancel`: новое правило, дубликат,
  уточнение, область, конфликты should/must, pattern, неоднозначность, пачка, не-правило, ответ,
  отмена). Команда оценки: `llm-wiki-admin wikiagent eval --scenarios …/tests/scenarios --out …`
  (там же). Живой прогон чата, самолечения и книги: `scripts/check_local_model.py`
- fallback: модель недоступна или вернула не HTTP-ответ — `WikiError` с кодом `E_MODEL_UNAVAILABLE`,
  HTTP 502 (`src/wikiagent/models.py`), ERR-model_unavailable; переполнение контекста — отдельный
  `E_MODEL_CONTEXT` (HTTP 400) до запроса, он не кэшируется как вердикт (`ref/decisions.md`,
  «Проверка на локальной Gemma и сборка v2»). Перед стартом `wikiagent` ждёт wiki API и модель до
  10 минут и повторяет через systemd (`ref/deploy-linux.md`, раздел 4). Без модели ядро `wikisvc`,
  чтение и ручной ревью работают, не работают чат, планировщик, книги, самолечение

### MDL-gemma-12b — оценочная модель на разработке
status: implemented

- changed: 2026-10-20 v3 (planned): по словам владельца это фактическая runtime-модель RES-llama-server — роли
  `planner`, `reviewer`, `chat` под алиасом `wiki-gemma-31b`, плюс LLM-судья каскада дедупа (PRM-wikiagent.fact_judge,
  CFG-wikiagent.models.judge_llm; ADR-0022) в том же процессе, отдельного процесса нет. Новые задачи v3: извлечение
  фактов окнами 1–2k токенов (PRM-wikiagent.fact_extract, PRM-wikiagent.hub_skeleton, PRM-wikiagent.fact_links;
  ADR-0027), novelty для семейства `gemma` (PRM-wikiagent.novelty_cloze, PRM-wikiagent.novelty_answer; ADR-0026):
  ≈ 11 вызовов на факт, ≤ 2000 в сутки (CFG-wikiagent.novelty.max_calls_per_day). Делит GPU с RES-embeddings-server
  и RES-reranker-server (решение Q-kb-vram-budget, RISK-kb-vram-contention). Возможная замена — Gemma 27B
Только оценка и пример конфигурации, в боевом деплое (`deploy/linux/`) не используется: ни
`wikiagent.yaml`, ни `llama.env` в `deploy/linux/` её не называют. Её имя `wiki-gemma-12b` стоит в
`wikiagent.example.yaml` (три роли, `timeout_seconds: 300`) и проверяется в `tests/test_deployment.py`.

- task: та же, что у MDL-wiki-gemma-31b (planner, reviewer, chat)
- source: локальный файл `gemma-4-12b-it-uncensored-Q4_K_M.gguf` из `~/.eva/models/gemma-4-12b-it-uncensored-GGUF/`
  (`ref/model-evaluation.md`); репозиторий-источник и ревизия не записаны, см. Q-mdl-12b-source
- version pin: нет; сборка llama-server — `b10809-5266f24` (там же)
- license: не указана в документах проекта (Q-mdl-31b-license относится и к этой модели)
- size / format: 12B, GGUF, квантование Q4_K_M
- runtime: RES-llama-server (`llama-server b10809-5266f24`), hardware: RTX 5060 Laptop 8 ГиБ,
  слоёв на GPU 35, KV `q8_0`, контекст 16384, temperature 0, JSON schema, reasoning off, одна сессия
- weights stored: у разработчика локально, вне репозитория
- used by: SVC-wikiagent при разработке (`wikiagent.example.yaml`); результаты — `ref/evals/gemma-12b-*.json`
- quality (все цифры из `ref/model-evaluation.md`, прогон 2026-10-06, 12 сценариев `tests/scenarios/`,
  метрика — совпадение ожидаемых действий и вопросов):

  | Промпт | Совпадение | Запретные вызовы | Лишние вопросы в среднем | Файл |
  |---|---:|---:|---:|---|
  | v2.1, схема только в `response_format` | 1/12 (8,33%) | 0 | 1,08 | `ref/evals/gemma-12b-v2.1.json` |
  | v2.2, схема в контексте и явные defaults | 10/12 (83,33%) | 0 | 0,083 | `ref/evals/gemma-12b-v2.2.json` |
  | v2.3, совместимость вложенной схемы | 10/12 (83,33%) | 0 | 0,083 | `ref/evals/gemma-12b-v2.3.json` |

  Порог рабочей модели (не менее 90% на не менее 30 сценариях) не достигнут: `production_ready=false`
  в отчётах. Не прошли в v2.3: новое правило со словом «только» повышено до must (лишний вопрос о
  владельце) и связи с pattern (структурный ответ не прошёл проверку за три попытки). Живая проверка
  через настоящий API (`scripts/check_local_model.py`): в v2.2 чат и самолечение прошли, все главы
  книги отклонены до генерации из-за лимита сложности грамматики llama-server
  (`ref/evals/gemma-12b-live-v2.2.json`); в v2.3 прошли чат, самолечение и книга
  (`ref/evals/gemma-12b-live-v2.3.json`, четыре проверки `"pass": true`). Эти же 12 сценариев на
  scripted-модели проверяют конвейер на 100%, это не оценка LLM. Версии промптов после v2.3
  (v2.4–v2.6) на Gemma не прогонялись (`ref/decisions.md`)
- fallback: как у MDL-wiki-gemma-31b — ERR-model_unavailable

## v3 (planned): эмбеддинги, reranker, судьи

Общее для карточек ниже (решения Q-kb-mdl-bge-m3, Q-kb-mdl-ab-candidates, Q-kb-mdl-reranker,
Q-kb-nli-judge-model, Q-kb-judge-runtime): источник — официальный репозиторий модели на Hugging Face;
ревизия и sha256 файла фиксируются при установке (для эмбеддингов `model` + ревизия пишутся в
TBL-wikisvc-core.index.embeddings). Лицензия указана, где её назвал владелец; остальные — при установке,
по Q-stack-license-policy. Файлы весов — на хосте в `/srv/llm-wiki/models/` (владелец `llm-model`, 0750; решение Q-kb-models-dir),
не в git, образе и Nix store. Все модели исполняются локально: GGUF — процессами `llama-server` на loopback,
ONNX — DEP-py-onnxruntime в SVC-wikiagent. Внешних провайдеров для этих ролей нет; если появятся — только
`https` и наружу только тексты `public` — так же, как для novelty (решение Q-kb-novelty-reference-model,
SEC-embeddings-boundary). Выбор между кандидатами — по eval (FMT-wikisvc-core.kb-eval, OBS-eval-metrics).

### MDL-bge-m3 — эмбеддинги
status: planned

- task: векторы трёх уровней — `claim`, `digest`, `chunk` — в одном пуле семян `ask` (FLOW-ask) и kNN по
  `claim`-векторам для дедупа и самолечения (FLOW-dedup-judge, JOB-wikiagent.heal); ADR-0018. При разрастании
  уровень `chunk` допустимо держать только в FTS, без векторов (решение Q-kb-vector-store)
- source: официальный репозиторий BGE-M3; файл GGUF F16, ≈ 1.1 GB (решение Q-kb-vram-budget)
- params: pooling `cls` (CFG-wikisvc.EMBEDDINGS_POOLING), контекст 8k токенов (ТЗ §0); размерность 1024
  (CFG-wikisvc.EMBEDDINGS_DIM); в индексе — float16, в памяти — float32, нормированы один раз, косинус = dot
- runtime: RES-embeddings-server с первого дня, CFG-wikisvc.EMBEDDINGS_ENABLED = true; GPU, если после развёрнутой Gemma
  свободно ≥ 2 GB, иначе CPU (`--n-gpu-layers 0`)
- version pin: смена модели или файла — полный `reindex --embeddings` (CLI-wikisvc-cli.reindex): пересечение
  top-k между моделями 0.43–0.54 (arXiv:2509.18869, ТЗ §5)
- quality: ru→en MKQA 76.2 против 76.8 у MDL-multilingual-e5-large (ТЗ §0); подтверждается A/B на этапе 2
- self-test: до любого прогона — две фиксированные пары текстов, расхождение косинуса > 0.02 с сохранённым
  `meta.embeddings_selftest` = провал (решение Q-kb-embeddings-selftest); OBS-wikisvc.embeddings-selftest
- fallback: ERR-embeddings_unavailable; `ask` — BM25 и явные рёбра без dense-prior, `degraded: true`
  (`rule-arch-outgoing-call-resilience`)

### MDL-multilingual-e5-large — кандидат A/B эмбеддингов
status: planned

- task: A/B с MDL-bge-m3 сразу на этапе 2 (решение Q-kb-mdl-ab-candidates); в прод не ставится, пока не выиграл
- params: префиксы `query:` / `passage:`, pooling `mean`, лимит 512 токенов (ТЗ §5)
- quality: ru→en MKQA 76.8 (ТЗ §0); критерий A/B — Recall@8 на ru→en и доля размеченных дубликатов в kNN
  top-10 при пороге 0.80 (ADR-0018)
- runtime: RES-embeddings-server на время прогона в ENV-dev, свой файл записанных векторов (ADR-0025)

### MDL-qwen3-embedding — кандидат A/B эмбеддингов (только 0.6B)
status: planned

- task, критерий: как у MDL-multilingual-e5-large; варианты 4B и 8B не берём — GPU делится с развёрнутой Gemma (сейчас 12B)
  (решение Q-kb-mdl-ab-candidates)
- params: Qwen3-Embedding-0.6B, pooling `last` (ТЗ §5)
- quality: MTEB-Multilingual 64.33 против 59.56 у BGE-M3; ru→en числа не опубликованы (ТЗ §5)

### MDL-bge-reranker-v2-m3 — reranker для `ask`
status: planned

- task: шаг 4 `ask` — какие id из `expanded[]` раскрыть до L1 (ТЗ §7.2); в ядре, включён с этапа 2
  (CFG-wikisvc.ASK_RERANK_ENABLED = true, CFG-wikisvc.RERANKER_URL, CFG-wikisvc.RERANKER_MODEL; решение
  Q-kb-reranker-placement)
- quality: +4.7 nDCG@10 на русском поверх BGE-M3 (RusBEIR, ТЗ §7.2)
- runtime: RES-reranker-server (`llama-server --reranking`, отдельный процесс: один процесс — одна модель)

### MDL-qwen3-reranker-0.6b — reranker, не выбран
status: planned

- task: в прод не идёт — выбран MDL-bge-reranker-v2-m3 (решение Q-kb-mdl-reranker); остаётся только как
  возможный кандидат A/B (ТЗ §7.2)

### MDL-nli-judge — судья claim ↔ claim
status: planned

- task: двунаправленное entailment/contradiction для пар (новый факт, kNN-кандидат): дубликат, `refines`,
  `contradicts`, независимые (FLOW-dedup-judge, ADR-0022); сравнение ответа с `claim` в novelty
  (PRM-wikiagent.novelty_judge, ADR-0026)
- source: `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`, лицензия MIT (решение Q-kb-nli-judge-model)
- runtime: ONNX через DEP-py-onnxruntime и DEP-py-tokenizers в SVC-wikiagent, MOD-wikiagent.judge (решение
  Q-kb-judge-runtime); в ядро не входит (ТЗ §11.11). ONNX-файл — экспорт или готовый — фиксируется при установке
- thresholds: стартовые entail 0.7 / contradiction 0.7 (CFG-wikiagent.judge.entail_threshold,
  CFG-wikiagent.judge.contradiction_threshold), калибровка на размеченных парах `tests/fixtures/kb-pairs.yaml`
- cascade: contradiction и пары с уверенностью < 0.7 → LLM-судья — развёрнутая Gemma на RES-llama-server
  (сейчас MDL-gemma-12b, PRM-wikiagent.fact_judge); уверенный duplicate LLM не подтверждается
- quality: сильная модель с CoT — precision 0.95 при recall 0.57 на противоречиях, 8B-модели ~1 %
  (arXiv:2504.00180, ТЗ §8.4)

### MDL-nli-judge-light — массовый фоновый NLI
status: planned

- task: та же роль claim ↔ claim для массовых фоновых проходов (JOB-wikiagent.heal, пересчёт пар), где
  MDL-nli-judge дорог
- source: `cross-encoder/nli-deberta-v3-base` (ONNX); лицензия — при установке
- runtime: как у MDL-nli-judge

### MDL-nli-modernbert — кандидат A/B для судьи claim ↔ claim
status: planned

- task: A/B с MDL-nli-judge на размеченных парах; в прод — один из двух (`rule-stack-one-tool-per-job`)
- source: `tasksource/ModernBERT-large-nli`, лицензия Apache-2.0, контекст 8k (решение Q-kb-nli-judge-model)
- runtime: как у MDL-nli-judge

### MDL-grounding-judge — судья claim ↔ источник
status: planned

- task: проверить, что факт следует из цитаты или абзаца источника, а не только совпадает подстрокой;
  новый шаг ingest между проверкой подстроки цитаты и дедупом (CLS-wikiagent.GroundingJudge,
  PRM-wikiagent.fact_ground, CFG-wikiagent.models.grounding; FLOW-dedup-judge)
- source: FactCG-DeBERTa-L (≈ 0.4B); точный репозиторий, лицензия, ревизия, sha256 — при установке
- runtime: ONNX через DEP-py-onnxruntime в SVC-wikiagent

### MDL-grounding-escalation — эскалация grounding
status: planned

- task: спорные случаи MDL-grounding-judge
- этап 3: эскалацию выполняет PRM-wikiagent.fact_ground на развёрнутой Gemma (сейчас 12B, MDL-gemma-12b) в
  RES-llama-server; отдельного процесса нет (решение координатора, Q-kb-grounding-escalation)
- на будущее, когда появятся отдельный процесс и VRAM: `Bespoke-MiniCheck-7B` (лицензия CC-BY-NC —
  некоммерческая, допустимость решает владелец по Q-stack-license-policy) или `Granite Guardian 3.3` (Apache-2.0)

### MDL-propositionizer-flan-t5 — разовый офлайн-эталон извлечения
status: planned

- task: разовый прогон на одной главе; 5–8 выходов — few-shot-эталон для PRM-wikiagent.fact_extract (ТЗ §8.3)
- source: `chentong00/propositionizer-wiki-flan-t5-large` (ТЗ §8.3); quality — F1 0.822 против GPT-4 (там же)
- runtime: в runtime проекта не входит (решение Q-kb-mdl-propositionizer); прогон — вручную в ENV-dev
