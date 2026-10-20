# Ошибки

## Формат ошибки

Все HTTP-ответы с ошибкой у `SVC-wikisvc` и `SVC-wikiagent` строит `CLS-wikisvc-core.WikiError`
(`src/wikisvc/domain/errors.py`); статус по умолчанию — 422.

```json
{ "error": { "code": "E_NOT_FOUND", "message": "Объект не найден.", "hint": "…", "details": [] } }
```

- `code` — код `E_*`; ID в документации — префикс `ERR-` и код без `E_` в нижнем регистре (`E_SELF_REVIEW` → `ERR-self_review`).
- `details` — список: ошибки валидации (`{field, message}`) или проблемы линтера (`{code, severity, page, message, hint}`).
- Ошибки проверки страниц (`require_valid` в `src/wikisvc/domain/validate.py`) поднимаются кодом первой ошибки, остальные — в `details`.
- `SVC-wikiagent` пробрасывает код и статус ответа `SVC-wikisvc` без изменений; в потоке чата (SSE) ошибка приходит событием `error` с тем же телом.
- `SVC-wiki-ui` (`ui/main.go`) отвечает своими ошибками в виде `{"error": {"code", "message"}}`, `SVC-updater` (`updater/api.go`) — `{"error": {"code", "message", "hint": "", "details": null}}`.
- Предупреждения линтера (`W_*`) — не ошибки: они идут в `warnings`/`details` и запрос не прерывают. Предупреждения слоя знаний v3 (`W_FACT_LONG`, `W_HUB_*`, `W_POSSIBLE_DUPLICATE`… — ТЗ §9) перечислены в `CLS-wikisvc-core.Lint`.
- Расхождение с `rule-arch-domain-errors` (там формат `{"detail", "code"}`) — RISK-core-error-format.

## Каталог

Колонка «повтор»: «да» — тот же запрос может пройти позже без изменений; «нет» — нужно менять запрос или данные.

| id | http | когда возникает | повтор | что делать клиенту | status |
|---|---|---|---|---|---|
| ERR-adr_exhausted | 409 | свободных четырёхзначных номеров ADR нет | нет | обратиться к администратору вики | implemented |
| ERR-agent_repair | 422 | исправление плана агента создаёт новые страницы или удаляет чужие | нет | агент повторяет исправление в рамках плана | implemented |
| ERR-agent_revise_target | 409 | предложение нельзя менять через агента | нет | править предложение вручную | implemented |
| ERR-agent_step_limit | 422 | чат превысил `CFG-wikiagent.limits.max_tool_steps` | нет | упростить вопрос | implemented |
| ERR-agent_token | 403 | токен `SVC-wikiagent` не writer или не `kind=agent` | нет | оператор выпускает правильный токен | implemented |
| ERR-agent_tool_arguments | 422 | модель передала неверные аргументы инструмента | нет | ответ модели отбрасывается | implemented |
| ERR-agent_tool_forbidden | 403, 422 | агент вызвал маршрут вне allowlist или правит страницу вне находки | нет | — (защита от промпт-инъекций) | implemented |
| ERR-agent_validation | 422 | предложение агента или лекаря не прошло валидацию после исправлений | нет | разобрать предложение вручную | implemented |
| ERR-audit_stale | 409 | политики изменились во время сверки документации | да, через resume | возобновить задачу | implemented |
| ERR-bad_request | 400 | `SVC-updater`: тело не JSON или лишние поля | нет | исправить запрос | implemented |
| ERR-body_too_large | 413 | тело больше лимита (`NFR-body-limit`) или сумма файлов сверки больше лимита | нет | уменьшить тело | implemented |
| ERR-budget_too_small | 422 | `budget_tokens` меньше, чем нужно на заголовок ответа и одну строку L0 (`API-wikisvc.knowledge.*`, `API-wikisvc-mcp.*`); при бюджете выше минимума ответ режется в `omitted_ids`, а не ошибкой | нет | увеличить бюджет | planned |
| ERR-claim_missing | 422 | у `fact` нет `claim` или он вне 20–200 символов (`E_CLAIM_MISSING`, `INV-claim-minimal`) | нет | исправить claim | planned |
| ERR-commit_invalid | 400 | хеш коммита не 7–40 hex | нет | передать хеш | implemented |
| ERR-cursor_invalid | 400 | неверный `cursor` пагинации | нет | начать без cursor | implemented |
| ERR-docs_audit_disabled | 403 | сверка документации выключена (`CFG-wikiagent.docs_audit.enabled`) | нет | включает оператор | implemented |
| ERR-domain_unknown | 422 | `domain` страницы не из `schema/domains.yaml` (`E_DOMAIN_UNKNOWN`, `INV-one-domain-per-page`) | нет | взять домен из `API-wikisvc.knowledge.domains`; новый добавляет администратор (`CLI-wikisvc-cli.domains.add`) | planned |
| ERR-embeddings_unavailable | 502 | `EXT-embeddings-server` недоступен, ответил ошибкой или не прошёл self-test (`OBS-wikisvc.embeddings-selftest`: две фиксированные пары, расхождение косинуса > 0.02, Q-kb-embeddings-selftest); там, где векторы обязательны: `CLI-wikisvc-cli.reindex --embeddings`, `CLI-wikisvc-cli.embeddings.selftest`, kNN в `FLOW-dedup-judge`. `ask` в этом случае не падает, а работает урезанно (Q-kb-embeddings-degraded) | да | повторить позже; оператор проверяет сервер эмбеддингов, модель и pooling | planned |
| ERR-extract_failed | 422 | извлечение книги завершилось `failed` без кода | да, через resume | возобновить задачу | implemented |
| ERR-extractor_unavailable | 400 | в окружении нет `pypdf` / `python-docx` | нет | оператор ставит зависимости | implemented |
| ERR-extract_pending | 409 | текст источника ещё извлекается | да, через секунды | повторить позже | implemented |
| ERR-extract_timeout | 422 | извлечение превысило `CFG-wikisvc.EXTRACT_JOB_TIMEOUT` или ожидание агента | да, `retry=true` | повторить извлечение | implemented |
| ERR-field_protected | 422 | PATCH меняет защищённое поле правила (`lifecycle`, `level`, `priority`, `owner`, `status`, `deprecated_reason`) | нет | решение ревьюера (`INV-human-decides`) | implemented |
| ERR-forbidden | 403 | недостаточно роли; выпускающий токен вне `POST /sessions`; чужие заметки или предложение; MCP для выпускающего токена; людям без `internal`; допуск ниже агента | нет | нужен другой токен | implemented |
| ERR-frontmatter_invalid | 422 | frontmatter не YAML-словарь, алиасы YAML, неверные поля | нет | исправить страницу | implemented |
| ERR-fts5_missing | 500 | SQLite собран без FTS5 | нет | оператор меняет сборку Python | implemented |
| ERR-git_dirty | 409 | в контент-репозитории правки вне сервиса, не та ветка | да, после очистки | оператор чистит `BKT-wikisvc-core.wiki-repo` | implemented |
| ERR-git_merging | 409 | в контент-репозитории незавершённое слияние | да, после очистки | оператор завершает слияние | implemented |
| ERR-http | любой | Starlette `HTTPException` (404 маршрута, 405 метода) | нет | проверить путь и метод | implemented |
| ERR-human_required | 403 | решение, откат, сверка документации или обновление — не человеческим токеном | нет | войти человеком (`SEC-principal-kind#human`) | implemented |
| ERR-id_duplicate | 422 | ID или путь страницы уже заняты | нет | выбрать другой ID | implemented |
| ERR-id_invalid | 422 | ID не по шаблону типа или не совпадает с URL | нет | исправить ID | implemented |
| ERR-init_nonempty | 409 | `wikisvc init` в непустой каталог | нет | выбрать пустой каталог | implemented |
| ERR-internal | 500 | необработанное исключение; в лог — только имя класса | да | сообщить оператору | implemented |
| ERR-job_busy | 409 | задача уже выполняется; самолечение уже идёт | да, позже | дождаться окончания | implemented |
| ERR-job_kind | 422 | в `TBL-wikiagent.agent.jobs` неизвестный `kind` | нет | — | implemented |
| ERR-job_state | 409 | возобновление задачи не в `failed`/`cancelled`/`paused`/`needs_outline` | нет | — | implemented |
| ERR-link_unresolved | 422 | связь на несуществующую страницу; удаление страницы с входящими ссылками | нет | исправить связи | implemented |
| ERR-locator_out_of_range | 422 | страницы или глава вне источника; оглавление не покрывает страницы | нет | исправить локатор | implemented |
| ERR-lock_timeout | 409 | запись ждала `CFG-wikisvc.LOCK_TIMEOUT` | да | повторить позже | implemented |
| ERR-merge_conflict | 409 | конфликт слияния при принятии; main не изменён | нет | пересоздать предложение на свежем main | implemented |
| ERR-method | 405 | `SVC-wiki-ui`: метод вне GET/HEAD/POST/PUT/PATCH/DELETE | нет | — | implemented |
| ERR-model_context | 400 | сообщения больше контекста модели | нет | агент делит пакет | implemented |
| ERR-model_output | 422 | модель не дала проверяемый ответ после повторов | нет | ответ отбрасывается | implemented |
| ERR-model_unavailable | 502 | `EXT-llm-server` недоступен или вернул неверный HTTP | да | повторить позже, задача на паузе | implemented |
| ERR-must_needs_owner | 422 | правилу `level=must` не задан `owner` | нет | указать владельца | implemented |
| ERR-no_text_layer | 422 | в документе нет текстового слоя (OCR нет) | нет | загрузить текстовую версию | implemented |
| ERR-not_found | 404 | объекта нет или он вне допуска (`INV-404-not-403`); выпуск сессий выключен | нет | — | implemented |
| ERR-patch_count | 422 | число совпадений `replace_text` не равно `expect_count` | нет | перечитать страницу | implemented |
| ERR-patch_field | 422 | PATCH меняет служебное поле (`id`, `type`, даты, `verified_*`) | нет | — | implemented |
| ERR-patch_invalid | 422 | неизвестная операция или не 1–100 операций | нет | исправить PATCH | implemented |
| ERR-patch_section | 422 | раздел отсутствует, неоднозначен или текст ломает уровни | нет | исправить PATCH | implemented |
| ERR-path_mismatch | 422 | путь страницы не по шаблону типа (v3 planned: шаблон с `{domain}`, `kb/<domain>/<каталог>/<id>.md`) | нет | — | implemented |
| ERR-path_unsafe | 400, 422 | путь выходит из репозитория или источник вне `raw/`, `library/` | нет | — | implemented |
| ERR-policy_block | 422 | в файле повреждён или повторён блок `wikisvc:begin…end` | нет | починить блок руками | implemented |
| ERR-profile_invalid | 422 | проблема линтера: профиль ссылается на неизвестное | нет | исправить профиль | implemented |
| ERR-profile_unknown | 404 | профиль не найден | нет | взять ID из списка профилей | implemented |
| ERR-proposal_dependency | 409 | принятие предложения раньше предложений из его `depends_on` (базовое ещё не `accepted`) — `STATE-proposal`, Q-kb-proposal-dependencies | да, после принятия базового | сначала принять базовое предложение (`source`, хабы) | planned |
| ERR-proposal_empty | 422 | отправка или принятие предложения без изменений | нет | — | implemented |
| ERR-proposal_path | 422 | предложение меняет файлы вне `wiki/` | нет | — | implemented |
| ERR-proposal_state | 400, 409 | переход вне `STATE-proposal` или неизвестное решение | нет | перечитать статус | implemented |
| ERR-quote_not_found | 422 | цитата модели или находки не найдена в тексте (v3 planned: в `FLOW-fact-ingest` кандидат не отбрасывается, а получает `confidence: inferred`) | нет | ответ отбрасывается | implemented |
| ERR-quote_too_long | 422 | цитата длиннее 30 слов | нет | сократить | implemented |
| ERR-quote_too_short | 422 | цитата короче двух слов источника | нет | удлинить | implemented |
| ERR-rate_limit | 429 | токен превысил `CFG-wikisvc.RATE_LIMIT_PER_MIN` | да, в следующую минуту | подождать | implemented |
| ERR-raw_category | 400 | неизвестная категория источника | нет | — | implemented |
| ERR-raw_exists | 409 | путь источника уже есть (источники неизменяемы) | нет | — | implemented |
| ERR-raw_extension | 422 | расширение не в `CFG-wikisvc.ALLOWED_RAW_EXT` | нет | — | implemented |
| ERR-raw_signature | 422 | содержимое не соответствует расширению (`SEC-upload`) | нет | — | implemented |
| ERR-rel_type_mismatch | 422 | тип связи не разрешён для типов страниц (v3 planned: + связи ТЗ §4 — `about`, `applies_with`, `refines`, `grounded_in`…) | нет | исправить связь | implemented |
| ERR-rel_unknown | 422 | неизвестный тип связи | нет | исправить связь | implemented |
| ERR-request_invalid | 400, 422 | запрос не по схеме, неверные параметры, `Content-Length`, вложенность | нет | исправить запрос по `details` | implemented |
| ERR-required_field | 422 | нет обязательного поля типа | нет | заполнить поле | implemented |
| ERR-restore_incomplete | 422 | после переноса данных нет `.git` или worktree | нет | скопировать `STATE_DIR` целиком (`FLOW-backup-restore`) | implemented |
| ERR-revert_conflict | 409 | откат пересекается с поздними коммитами | нет | новое предложение | implemented |
| ERR-rule_active_not_verified | 422 | `lifecycle=active` без `verified_by` | нет | только решение ревьюера | implemented |
| ERR-rule_fields | 422 | поля правила противоречат жизненному циклу (`STATE-rule-lifecycle`) | нет | исправить поля | implemented |
| ERR-rule_not_in_proposal | 422 | повышение или снятие правила, которого нет в предложении | нет | — | implemented |
| ERR-schema_newer | 500 | база записана более новой версией | нет | вернуть новую версию или копию данных | implemented |
| ERR-scope_unknown | 400, 422 | область не из словаря `ENT-scope` (v3 planned: с учётом осей и иерархии `domain:`) | нет | взять область из списка | implemented |
| ERR-secret_detected | 400, 422 | в тексте найден возможный секрет (`SEC-secret-detector`) | нет | убрать секрет | implemented |
| ERR-section_missing | 422 | нет обязательного раздела типа страницы | нет | добавить раздел | implemented |
| ERR-self_review | 403 | автор или редактор принимает своё предложение (`INV-no-self-review`) | нет | нужен другой ревьюер | implemented |
| ERR-sensitivity_ref | 422 | страница ссылается (связь, `[[…]]`, `Facts` хаба) на страницу с `sensitivity` выше своей (`E_SENSITIVITY_REF`, `SEC-graph-clearance-mask`) | нет | повысить `sensitivity` ссылающейся страницы или убрать ссылку | planned |
| ERR-service_unavailable | 502, 503 | `SVC-wiki-ui` не достучался до соседа; `SVC-updater` не проверил права | да | повторить позже | implemented |
| ERR-source_hash | 422 | `raw_sha256` не совпадает с источником или хеш неверен | нет | — | implemented |
| ERR-summary_too_long | 422 | тезис правила длиннее 160 символов | нет | сократить | implemented |
| ERR-tag_unknown | 422 | тег не из словаря | нет | — | implemented |
| ERR-template_invalid | 422 | шаблон проекта не прошёл карантинную проверку | нет | администратор исправляет шаблон | implemented |
| ERR-template_unknown | 404 | шаблона проекта нет | нет | — | implemented |
| ERR-text_invalid | 422 | парсер отклонил документ или упал | нет | — | implemented |
| ERR-text_limit | 422 | превышены память, время, число страниц или объём текста извлечения | нет | разбить документ | implemented |
| ERR-text_too_large | 413 | текст целиком больше лимита | нет | читать по `pages`/`chapter` | implemented |
| ERR-text_unavailable | 400 | формат не поддерживает извлечение | нет | — | implemented |
| ERR-token_exists | 409 | имя токена занято | нет | другое имя | implemented |
| ERR-token_name | 422 | имя токена не по шаблону | нет | — | implemented |
| ERR-token_person | 422 | `person` не по шаблону | нет | — | implemented |
| ERR-type_unknown | 422 | неизвестный тип страницы или смена типа | нет | — | implemented |
| ERR-ui_build | 503 | в бинарник `SVC-wiki-ui` не встроена сборка SPA | нет | оператор пересобирает | implemented |
| ERR-unauthorized | 401 | нет или недействителен Bearer-токен, истёк срок | нет | войти заново (`FLOW-oidc-login`) | implemented |
| ERR-update_busy | 409 | проверка или обновление уже идёт | да, позже | дождаться | implemented |
| ERR-update_channel | 400 | канал не `release` и не `beta` | нет | — | implemented |
| ERR-update_stale | 409 | предложенное обновление сменилось | нет | проверить обновления снова | implemented |
| ERR-update_state | 500 | `SVC-updater` не сохранил состояние | да | оператор смотрит журнал | implemented |
| ERR-upload_too_large | 413 | файл больше `CFG-wikisvc.MAX_UPLOAD_MB` / `CFG-wikisvc.MAX_LIBRARY_UPLOAD_MB` | нет | — | implemented |
| ERR-valid_for_missing | 422 | факт `kind` ∈ {number, api, pitfall} без `valid_for` (`E_VALID_FOR_MISSING`) | нет | указать условие применимости | planned |
| ERR-validation | 422 | при принятии предложения найдены ошибки | нет | автор исправляет | implemented |
| ERR-version_conflict | 409 | `base_version` страницы устарел | нет | перечитать страницу | implemented |
| ERR-wiki_service | 502 | `SVC-wikisvc` вернул ответ без тела ошибки | да | повторить позже | implemented |
