# Глоссарий

> Слова предметной области. Если термин в коде называется иначе — пиши оба варианта.

| id | термин | значение | в коде | не путать с |
|---|---|---|---|---|
| TERM-wiki | вика, контент-репозиторий | git-репозиторий с Markdown-страницами, схемой и источниками; ветка `main` — принятое знание | `WIKI_ROOT`, `GitRepo` | TERM-index |
| TERM-page | страница | Markdown-файл с YAML-frontmatter одного типа; единица знания (`ENT-page`) (v3 planned: + типы fact, topic, tech, question и поле `domain`) | `Page`, `Frontmatter` | TERM-chunk |
| TERM-page-type | тип страницы | описание полей, разделов, префикса ID и связей страниц одного вида | `schema/page-types/*.yaml`, `PageType` | — |
| TERM-rule | правило | страница типа `rule`: что делать в разработке, с уровнем и областями (`ENT-rule`) | `type: rule` | TERM-invariant |
| TERM-summary | тезис | однострочное описание страницы; у правила ≤ 160 символов, попадает в блок политик (v3 planned: у факта — деконтекстуализированный claim, уровень L1) | `summary` | — |
| TERM-level | уровень правила | `must` — обязательно, `should` — по умолчанию да, `idea` — только кандидат | `level` | TERM-lifecycle |
| TERM-lifecycle | жизненный цикл правила | `candidate` → `active` → `deprecated` (`STATE-rule-lifecycle`) | `lifecycle` | TERM-page-status |
| TERM-page-status | статус страницы | `draft`, `verified` (подтверждена человеком), `outdated` | `status` | TERM-lifecycle |
| TERM-candidate | кандидат | правило в `lifecycle: candidate`; видно в вике, но в политики не попадает | `candidate` | — |
| TERM-inert-rule | инертное правило | правило, которое не действует, пока человек его не повысил (`INV-agent-rule-inert`) | — | TERM-candidate |
| TERM-policy | политика, правило компании | активное подтверждённое правило, которое выдаётся проектам; в документации проекта — `rule-…` | `policies` | TERM-invariant |
| TERM-policy-block | блок политик | сгенерированный текст правил между маркерами `<!-- wikisvc:begin version=… -->` и `<!-- wikisvc:end -->` в `AGENTS.md` проекта | `export_block`, `BLOCK` | — |
| TERM-profile | профиль | набор областей и бюджет токенов для типа проекта (`ENT-profile`) (v3 planned: + `reference_model`, `brief`) | `schema/profiles/*.yaml` | TERM-scope |
| TERM-scope | область, scope | метка стека или вида приложения `<группа>:<значение>` (`ENT-scope`); `*` — все (v3 planned: группы — оси, `TERM-scope-axis`) | `applies_to`, `scopes.yaml` | TERM-profile |
| TERM-proposal | предложение | набор правок страниц на отдельной ветке, который принимает человек (`ENT-proposal`) | `Proposal`, `pid` | — |
| TERM-worktree | рабочее дерево предложения | отдельный git worktree ветки предложения в `STATE_DIR/worktrees/<pid>` | `worktree()` | TERM-wiki |
| TERM-overlay | наложение | вид вики «main + правки предложения» для проверки ссылок и валидации | `_overlay` | — |
| TERM-review | ревью, решение | принятие, отклонение, возврат на доработку, откат — только человеком | `decide`, `review` | — |
| TERM-finding | находка | проблема в страницах с цитатами-доказательствами (`ENT-finding`) | `findings` | TERM-lint-issue |
| TERM-lint-issue | проблема линтера | детерминированная ошибка (`E_*`) или предупреждение (`W_*`) проверки страниц | `LintIssue` | TERM-finding |
| TERM-heal | самолечение, лекарь | фоновая задача агента: ищет противоречия и дубли между страницами и предлагает исправления (`FLOW-heal`) | `heal`, `Healer` | TERM-docs-audit |
| TERM-docs-audit | сверка документации | задача агента: сверяет файлы документации проекта с блоком политик (`FLOW-docs-audit`) | `docs_audit` | TERM-heal |
| TERM-violation | нарушение | сообщение, что код проекта нарушил правило (`ENT-violation`) | `violations` | TERM-finding |
| TERM-source | источник, сырьё | неизменяемый загруженный файл в `raw/` или `library/` (`ENT-library-item`) и его страница типа `source` | `raw`, `src-…` | — |
| TERM-library | библиотека, книга | источники категории `library` — книги; лежат в `STATE_DIR`, а не в git | `library/` | TERM-source |
| TERM-extraction | извлечение | постраничный текст и оглавление источника, полученные изолированным парсером (`ENT-extraction`) | `extractions`, `extract_worker` | — |
| TERM-outline | оглавление | главы книги со страницами; из закладок PDF, иначе запасное — блоками страниц; можно поправить вручную | `outline`, `outline_overrides` | — |
| TERM-citation | цитата | ссылка `[@src-… стр. N "текст"]` на страницу источника; текст сверяется с извлечением | `citations` | — |
| TERM-clearance | допуск, чувствительность | уровень доступа принципала и уровень страницы: `public` < `internal` < `restricted` (`SEC-clearance`) | `clearance`, `sensitivity` | TERM-role |
| TERM-role | роль | reader < writer < reviewer < admin | `Role` | TERM-clearance |
| TERM-principal | принципал | тот, от чьего имени запрос: имя, роль, допуск, вид, идентичность | `Principal` | TERM-person |
| TERM-principal-kind | вид принципала | `human` или `agent` (`SEC-principal-kind`) | `kind` | — |
| TERM-person | человек, идентичность | стабильный идентификатор человека (OIDC `sub` или `--person`) | `person`, `identity` | TERM-principal |
| TERM-session | сессия | короткоживущий токен человека после входа через IdP (`ENT-session`) | `sso-…`, `wiki_session` | — |
| TERM-issuer-token | выпускающий токен | служебный токен `SVC-wiki-ui`, которым он выпускает сессии; другого не умеет | `SESSION_ISSUER_TOKEN_NAME` | TERM-session |
| TERM-untrusted-external | недоверенные внешние данные | метка `trust: untrusted_external`: текст — данные, а не инструкции (`INV-untrusted-external`) | `untrusted_external` | — |
| TERM-index | индекс | производная SQLite-база страниц, связей и полнотекстового поиска; пересобирается из git | `wiki.db`, `IndexDB`, `INDEX_DIR` | TERM-wiki |
| TERM-chunk | чанк | фрагмент тела страницы по заголовкам для полнотекстового поиска BM25 (v3 planned: + вектор уровня `chunk`) | `chunks`, `chunks_fts` | TERM-page |
| TERM-graph | граф связей | рёбра между страницами: связи frontmatter, вики-ссылки, цитаты и обратные связи (v3 planned: вес, заметка, `origin`; мягкие рёбра; снимок в памяти) | `edges`, `GraphStore` | — |
| TERM-impact | влияние | страницы, зависящие от данной через граф; показывается ревьюеру | `impact` | — |
| TERM-context | контекст | связанный набор страниц в пределах бюджета символов для агента (v3 planned: заменяется ответом `ask`, `TERM-expansion`) | `context` | — |
| TERM-plan | план правок | результат разбора сообщения чата: что создать, изменить или отметить; оформляется предложением | `plan` | TERM-proposal |
| TERM-job | задача агента | долгая работа `SVC-wikiagent` с контрольными точками (`ENT-job`) | `jobs`, `JobRunner` | — |
| TERM-checkpoint | контрольная точка | сохранённый прогресс задачи, с которого её можно продолжить | `job_state`, `boundary` | — |
| TERM-channel | канал обновлений | `release` или `beta`: какие теги образа предлагает `SVC-updater` | `Channel` | — |
| TERM-invariant | инвариант | правило домена этого проекта (`INV-…` в `domain.md`) | — | TERM-policy |
| TERM-project-template | шаблон проекта | данные для старта проекта: файлы, компоненты, профиль, области; без исполняемых хуков | `ProjectTemplate` | TERM-profile |
| TERM-fact | факт | (v3 planned) атомарное проверяемое утверждение — страница `fact`, единица доставки (`ENT-fact`) | `type: fact`, `f-…` | TERM-rule, TERM-finding |
| TERM-claim | claim, тезис факта | (v3 planned) одно минимальное предложение 20–200 символов; уровень L0, единица дедупликации (`INV-claim-minimal`) | `claim` | TERM-summary |
| TERM-topic | хаб, тема | (v3 planned) страница `topic`: выжимка и упорядоченный список фактов темы (`ENT-topic`) | `type: topic`, `top-…` | TERM-domain |
| TERM-tech | технология | (v3 planned) страница `tech`: инструмент или компонент с вердиктом команды (`ENT-tech`) | `type: tech`, `tech-…` | — |
| TERM-question | открытый вопрос | (v3 planned) страница `question`: явное «не знаем» (`ENT-question`) | `type: question`, `q-…` | TERM-finding |
| TERM-domain | домен | (v3 planned) узел дерева `schema/domains.yaml`, задаёт путь `kb/<domain>/…` (`ENT-domain`) | `domain` | TERM-scope, TERM-topic |
| TERM-novelty | новизна | (v3 planned) знает ли факт модель без вики: `common`, `differs`, `unique` для каждого семейства моделей; ставится процедурой, не самооценкой, и хранится производно в state, а не в файле (`FLOW-novelty-scan`) | `novelty` | `confidence` |
| TERM-brief | brief знаний | (v3 planned) детерминированная подборка фактов L0 под профиль в начале задачи (`FLOW-knowledge-brief`) | `get_brief`, `services/brief.py` | TERM-policy-block |
| TERM-delivery-level | уровень выдачи | (v3 planned) L0 — `id · claim`; L1 — `id · summary` + оговорки + пример ≤ 600 символов, для хаба — `Digest`; L2 — страница целиком | `level` | — |
| TERM-digest | выжимка хаба | (v3 planned) раздел `Digest` хаба ≤ 800 символов; L1 хаба и вектор уровня `digest` | `## Digest` | TERM-summary |
| TERM-seed | семя | (v3 planned) страница из гибридного поиска (BM25 + векторы, RRF), с которой начинается ответ `ask` | `seeds` | — |
| TERM-expansion | расширение по графу | (v3 planned) добавление соседей семян через PPR; включается по условию (`expansion_used`) | `expanded`, `expansion_used` | TERM-context |
| TERM-ppr | Personalized PageRank | (v3 planned) случайное блуждание с возвратом к семенам, α = 0.5, останов по допуску 1e-6 | `ppr` | TERM-impact |
| TERM-soft-edge | мягкое ребро | (v3 planned) ребро, которое индекс строит сам: `same_hub`, `co_cited`, `similar`; в файлах не хранится | `soft_edges` | TERM-graph |
| TERM-specificity | специфичность узла | (v3 planned) log(N / (1 + степень)), нормированная в [0, 1]; не даёт крупным хабам перетянуть PPR | `node_stats.specificity` | — |
| TERM-judge | судья | (v3 planned) две роли: claim ↔ claim — NLI-модель с эскалацией на LLM (дубликат, уточнение, противоречие, независимы, `FLOW-dedup-judge`); claim ↔ источник — grounding-проверка, следует ли факт из цитаты (`FLOW-fact-ingest`) | `judge`, `JudgeVerdict` | TERM-heal |
| TERM-eval-set | eval-набор | (v3 planned) вопросы с gold id и размеченные пары фактов; гейт CI по Recall (`NFR-eval-recall-baseline`) | `tests/fixtures/kb-eval.yaml`, `pytest -m eval` | — |
| TERM-bi-temporal | двухвременность | (v3 planned) время в мире (`valid_from`/`valid_to`) плюс время записи (коммит git) | `valid_from`, `valid_to` | TERM-valid-for |
| TERM-grounded-in | обоснование | (v3 planned) связь `rule`/`adr`/`pattern`/`playbook` → факт или хаб, на котором держится предписание | `grounded_in` | TERM-citation |
| TERM-scope-axis | ось области | (v3 planned) группа областей с правилами: `domain` (иерархия), `lang`, `tech`, `layer`, `scale`, `stage` | `axes` в `scopes.yaml` | TERM-scope |
| TERM-reference-model | референсная модель | (v3 planned) модель профиля по умолчанию, чей `novelty` читает brief; клиент передаёт свою модель в `get_brief` | `reference_model` | — |
| TERM-valid-for | условие применимости | (v3 planned) версия или режим, при котором факт верен (`rust>=1.75`); обязательно для `number`, `api`, `pitfall` | `valid_for` | TERM-bi-temporal |
