# llm-wiki: правила компании для агентов

`wikisvc` хранит Markdown в отдельном Git-репозитории, компилирует инструкции
по профилям и предоставляет HTTP API и MCP. Он детерминированный и не вызывает
LLM. `wikiagent` — отдельный клиент: разбирает сообщения, готовит предложения,
извлекает кандидатов из книг и ищет несостыковки. Решения принимает человек.
Веб-пространство `ui/` объединяет базу знаний, потоковый чат, редактор и ревью,
библиотеку, граф, инструкции и задачи. React + TypeScript, отдельный Go-бинарник
со встроенными ресурсами. Python 3.12+, FastAPI, SQLite FTS5 и Git worktrees в API.

```text
work/
├── backend/               # этот репозиторий; имя каталога произвольное
│   ├── ui/                # Go-сервер, React, браузерные тесты и сборка
│   └── .dev/
│       ├── state/         # state.db, worktrees, library/, extract/ — нужен бэкап
│       ├── agent/         # agent.db, сессии, задачи, кэш пар — нужен бэкап
│       └── index/         # производный индекс, можно пересобрать
└── wiki/                  # отдельный Git-репозиторий контента
    ├── AGENTS.md
    ├── CLAUDE.md -> AGENTS.md
    ├── inbox/             # не индексируется
    ├── raw/               # небольшие исходники
    ├── wiki/              # страницы знаний
    └── schema/            # типы, связи, scopes, profiles, шаблон инструкции
```

## Запуск

Для постоянного развёртывания на **AlmaLinux с Nix и локальной Gemma 4 31B**:
[пошаговая установка](docs/deploy-almalinux.md). Комплект `nix build .#deployment`
содержит установщик, четыре systemd-службы, конфигурацию, проверку готовности и
команду восстановления worktrees после переноса. Ниже — запуск для разработки.

```sh
git clone git@github.com:BadRabbit00/llm-wiki.git backend
cd backend
nix develop
# Только для нового каталога контента:
wikisvc init "$WIKI_ROOT"

wikisvc token create --name wikiagent --person wikiagent --kind agent --role writer --clearance restricted
wikisvc token create --name alice --person alice --kind human --role reviewer --clearance restricted
wikisvc serve
```

Токены показываются один раз; храните их как секреты. В state.db только хеши.
У разных токенов одного человека должен быть одинаковый `person`: автор и все
редакторы предложения не могут принять его другим токеном. Решения ревьюера
требуют `kind=human`. Выдача, список и отзыв токенов — только CLI:
`wikisvc token list`, `wikisvc token revoke NAME`; есть `--expires-at`.

Dev shell задаёт `WIKI_ROOT=../wiki`, `.dev/state`, `.dev/index` и `.dev/agent`.
Переопределяйте пути до входа в оболочку; state и index должны находиться вне wiki.
Зависимости PDF/DOCX входят в обязательную установку. Без Nix можно установить
проект через `pip install -e '.[dev]'` в Python venv; отдельно нужен Git.

API wikisvc: `http://127.0.0.1:8787/api/v1`, документация `/docs`, схема
`/openapi.json`. Сервис работает одним процессом. Адрес меняют `BIND_HOST` и
`BIND_PORT`. При публикации используйте TLS-прокси. `CORS_ORIGINS` по умолчанию
пуст; встроенный UI использует один origin через Go-прокси и не требует CORS.

## Веб-интерфейс

После запуска `wikisvc` и `wikiagent`, в третьем терминале из корня репозитория:

```sh
nix run .#ui
# Откройте http://127.0.0.1:8789 и введите свой human-токен.
```

Чат работает с моделью из конфигурации `wikiagent`. База знаний, ручное редактирование,
ревью, источники, граф и экспорт инструкций доступны независимо от готовности модели.
Правки сохраняются предложениями; автору нужен другой человек для принятия.
Токен хранится в памяти и `sessionStorage` текущей вкладки; выход очищает кэш.
Поддерживаются светлая и тёмная темы, мобильная навигация и поиск по `Ctrl/Cmd+K`.

Разработка, тесты, переменные окружения: [ui/README.md](ui/README.md).
Папка вики остаётся отдельной от кода, UI читает и изменяет данные через API.

## Правила и инструкция

Тип `rule` объединяет правила стека, кода, безопасности и тестирования. Поля:
`summary` (один тезис 20–160 символов), `category`, `level` (`must`, `should`,
`idea`), `lifecycle` (`candidate`, `active`, `deprecated`), `applies_to`, `origin`.
Разделы: «Правило», «Обоснование», «Примеры», необязательные «Исключения».
`aliases` помогают поиску, `enforced_by` указывает линтер/CI. `must` требует
владельца и источник решения; активное правило подтверждается человеком.

Начинайте задачу с `get_policies(profile)`. В инструкцию входят только активные
must/should для пересекающихся scopes или `*`. Все must сохраняются даже сверх
бюджета (`over_budget=true`). По умолчанию машинно проверяемые should опускаются,
а must помечаются проверяющим инструментом; параметр `enforced=all|none|keep_must`
меняет это поведение. Подробности, исключения и связи открывайте через `get_rule`.

```sh
curl -H "Authorization: Bearer $WIKI_TOKEN" \
  'http://127.0.0.1:8787/api/v1/policies/compile?profile=python-fastapi&explain=true'
wikisvc policies export --profile python-fastapi --out ../myapp/AGENTS.md
wikisvc policies check --profile python-fastapi --file ../myapp/AGENTS.md
wikisvc scopes add app:billing
```

Экспорт заменяет только блок `<!-- wikisvc:begin version=… -->` …
`<!-- wikisvc:end -->`. Версия зависит от содержимого правил и параметров,
статистика использования её не меняет. Шаблон: `schema/policy-template.md`;
профили и словарь: `schema/profiles/`, `schema/scopes.yaml`. Scopes и схемой
управляет администратор; агент не меняет их через предложения.

Поиск: русские/английские словоформы, стоп-слова, `schema/synonyms.yaml`, BM25,
AND с OR fallback, граф. `1С` и `1C` нормализуются одинаково. Raw score не выдаётся.
По умолчанию deprecated скрыты; `lifecycle=candidate,active,deprecated` включает
всё. `rules/related`, `graph/impact/{id}`, `proposals/{pid}/impact` показывают связи
и затронутые страницы/профили. Счётчики delivered/opened/violations доступны
в списке rules и статистике ревьюера.

## Чат и модели

Во второй оболочке `nix develop`:

```sh
cp wikiagent.example.yaml wikiagent.yaml
# Задайте WIKIAGENT_TOKEN значением отдельного writer kind=agent токена.
export WIKIAGENT_CONFIG="$PWD/wikiagent.yaml"
wikiagent serve
```

Роли planner/reviewer/chat настраиваются независимо через совместимый
`/v1/chat/completions` endpoint. Конфигурация содержит имя модели, размер контекста,
температуру, `structured: json_schema|json_object`, таймаут и необязательный
`token_env`. Модель/версия промпта сохраняются в описании предложения.

Локальный пример для предоставленного GGUF (путь и число GPU-слоёв зависят от
машины; для воспроизводимой проверки использовался этот запуск):

```sh
llama-server \
  -m "$HOME/.eva/models/gemma-4-12b-it-uncensored-GGUF/gemma-4-12b-it-uncensored-Q4_K_M.gguf" \
  --alias wiki-gemma-12b --host 127.0.0.1 --port 18089 \
  -c 16384 -ngl 35 -np 1 -fa on --cache-type-k q8_0 --cache-type-v q8_0 \
  --jinja --reasoning off
```

Wikiagent слушает `127.0.0.1:8788`. Все запросы авторизуются пользовательским
Bearer-токеном через `/whoami`. Допуск пользователя должен быть не ниже допуска
рабочего токена агента. Пользовательский токен не сохраняется в agent.db.

1. `POST /chat/sessions` с `{"profile":"python-fastapi"}`; можно добавить
   `bind: {type: page|rule|proposal|none, id: ...}`.
2. `POST /chat/sessions/{id}/messages` с `{"text":"Мы используем FastAPI и только async код"}`.
   SSE-события: status, message (text/plan/plans), error. Вложения — виртуальные
   пути ранее загруженного сырья в `attachments`.
3. План содержит тезисы, diff, влияние, допущения и блокирующие вопросы.
   Ответ в той же сессии обновляет черновик.
4. Человек проверяет план и вызывает wikisvc `POST /proposals/{pid}/accept`
   с `accept_body` плана. Сам wikiagent этот запрос выполнить не может.

Новый rule через предложение всегда инертный candidate/should, priority=3.
Сигнал обязательности сохраняется в плане: для включения нужны владелец и
источник. Изменения защищённых lifecycle/level/priority/owner/verified_* через
PATCH отвергаются; PUT сохраняет прежние значения. При затронутом must план
показывает `needs_double_confirm`. UI в эту версию не входит.

## Предложения и решения человека

Обычный цикл: create → put/patch → validate → submit → diff/impact → accept/reject.
`base_version` — версия страницы из main. Заметки редактирует только автор.
`kind` различает manual/chat/book/heal. Пустое предложение не отправляется.
Понижение sensitivity отмечается предупреждением в validate и diff.

Reviewer kind=human может принять агентский draft одним запросом:

```json
{"promote":[{"id":"rule-async-only","level":"should","priority":3,
 "applies_to":["lang:python"],"enforced_by":[]}],
 "deprecate":[{"id":"rule-http-requests-sync","reason":"Заменено rule-async-only"}]}
```

Здесь разрешены только rule из предложения. Слияние, подтверждение изменённых
активных правил и эти решения входят в один коммит; при ошибке операция
откатывается целиком, статус предложения сохраняется. Восстановление после
сбоя учитывает уже созданный Git-коммит. Для кандидата в main есть отдельные
`POST /rules/{id}/promote` и `/deprecate` — тоже действия человека.

`POST /proposals/{pid}/revert` откатывает принятое предложение вместе с решениями.
Если последующие коммиты меняли те же страницы, возвращает `409 E_REVERT_CONFLICT`.
Закрытые предложения сохраняют diff в state.db. Отмена draft — `/abandon`,
отклонение ревьюером — `/reject` с причиной. Неактивные предложения имеют TTL.

## Книги и источники

`POST /raw` принимает multipart file/category/note. `library` сохраняет книгу
в `$STATE_DIR/library/<год>/<sha8>-<имя>` без коммита; предел по умолчанию 200 МиБ.
Категории docs/transcripts/tickets/api-specs/code-samples/assets сохраняются
в raw Git-репозитория, предел 25 МиБ. Файлы неизменяемы, проверяются по сигнатуре,
дедуплицируются по SHA-256; русские имена транслитерируются, оригинал сохраняется.
Raw и library требуют clearance=restricted. Ответы помечены untrusted_external.

- `POST /raw/{path}/extract` возвращает 202 с состоянием фоновой задачи; повторный
  POST идемпотентен. Pending/running восстанавливаются при старте, failed хранит
  код ошибки. Общий таймаут — `EXTRACT_JOB_TIMEOUT=600`.
- PDF с текстовым слоем, EPUB, DOCX, MD/TXT разбираются ограниченным подпроцессом
  порциями; скан даёт `E_NO_TEXT_LAYER`, OCR отсутствует. Кэш по хешу — extract/.
- `GET /raw/{path}/outline` возвращает главы, `PUT` сохраняет ручное оглавление.
- `GET /raw/{path}/text?chapter=2&max_chars=20000` либо `pages=10-15` ограничивает
  ответ. Продолжение: `pages=next_pages&offset=next_offset`; полный слишком большой
  текст даёт `E_TEXT_TOO_LARGE`. Не готовый кэш — 409.
- Цитаты `[@src-id стр. 12 "до 30 слов"]` или `гл. 2` проверяются по кэшу;
  ошибки: `E_QUOTE_NOT_FOUND`, `E_QUOTE_TOO_LONG`, `E_LOCATOR_OUT_OF_RANGE`.
  Без извлечённого текста — `W_QUOTE_UNVERIFIED`.

В wikiagent вызовите `POST /jobs/ingest-book` с `raw_path`, необязательными title,
author, year, scopes_hint. Чтение идёт по главам с ограниченным контекстом.
`needs_outline` требует ручного PUT оглавления и resume; после подготовки
кандидатов задача становится `awaiting_review`. Полный текст книги не попадает
в Markdown, остаются библиография, выжимка и короткие цитаты. Кандидаты после
принятия не включаются в инструкцию, пока человек их не повысит.

Задачи: `GET /jobs`, `/jobs/{id}`, `POST /jobs/{id}/cancel`, `/resume`.
Контрольные точки сохраняют ответы модели и ID до записи страниц: после
остановки задача продолжается без дублей. `/inbox` wikisvc читает статистику
задач, если `WIKIAGENT_STATE_DIR` указывает на тот же каталог agent.db.

## Самолечение

`POST /jobs/heal` с `{"scope":"changed"}` или `{"scope":"full"}` запускает проверку
вручную. Автоматически она запускается при простое внутри окна по местному времени
сервера; полный проход раз в неделю. Параметры — в `wikiagent.example.yaml`.
Чат получает модель первым, heal ждёт между парами (`waiting_chat`).

Пары ограничены поиском/графом/категорией и кэшируются по хешам; неизменная вики
не вызывает модель повторно. Есть бюджет на проход/сутки и число новых находок.
Выдуманные цитаты отвергаются, конфликт с must проверяет также reviewer-модель.
Лекарь пишет findings и отправляет предложения kind=heal; существующие правила
меняет только в предложениях, protected-поля и принятие недоступны.

`GET /findings`, `/findings/stats`, `/inbox` — очередь для человека. Dismiss
требует причины и сохраняется до изменения текста. Accept связанного предложения
закрывает находку, reject отклоняет, revert открывает снова. Статистика рекомендует
повысить порог, если отклонено больше половины находок вида; сама порог не меняет.

## MCP и права

```sh
# WIKI_TOKEN — ранее выданный токен. Передайте также пути WIKI_ROOT/STATE_DIR/INDEX_DIR.
wikisvc mcp
nix build .#wikiagent   # оба CLI входят в один пакет
nix run .#wikiagent -- --help
```

20 инструментов включают get_policies, get_rule, rules_related, graph_impact,
get_outline, read_source_pages и прежние инструменты поиска/страниц/предложений.
Определения MCP и инструментов модели общие. Операций принятия, повышения,
снятия и отката у агента нет. Транспорт дополнительно проверяет разрешённые пути.

HTTP-транспорт MCP (Streamable HTTP) включается через `MCP_HTTP_ENABLED=True`
в процессе `wikisvc serve` и использует общий Runtime без повторной индексации.
`MCP_HTTP_PATH` задаёт путь (по умолчанию `/mcp`, должен начинаться с `/`),
`MCP_PROFILE` — профиль инструментов (по умолчанию `coding`: 13 инструментов
для правил, поиска, чтения и предложений; `full`: все 20). Каждый запрос требует
`Authorization: Bearer <token>`; `WIKI_TOKEN` используется только для stdio.
HTTP выключен по умолчанию (`MCP_HTTP_ENABLED=False`). Для stdio профиль
выбирается через `wikisvc mcp --profile coding`, по умолчанию используется `full`.
В обоих профилях сначала вызывайте `get_instructions`.

Роли reader → writer → reviewer → admin, допуск public → internal → restricted.
Недоступная страница даёт 404 и скрывается из поиска, контекста, графа, истории,
индекса и предложений. `GET /admin/audit` требует admin/restricted. Авторизация
предшествует чтению тела; JSON/Markdown ограничены 1 МиБ. Неавторизованные запросы
не заполняют SQLite-аудит. `RATE_LIMIT_PER_MIN` включает ограничение на токен.
`LOG_LEVEL` управляет логами. Парсеры имеют лимиты времени/памяти; это не полноценная
системная песочница. Внешние источники и ответы модели всегда проверяются.

## Обновление существующей вики и бэкап

Сначала сохраните согласованный бэкап контента, STATE_DIR и WIKIAGENT_STATE_DIR
при остановленной записи. Библиотека и сессии не восстановятся только из Git.
INDEX_DIR можно пересобрать командой `wikisvc reindex --full`. Миграции state.db
применяются при старте с сохранением существующих данных. Старые токены получают
`kind=agent`: для решений ревьюера перевыпустите человеческий токен с
`--kind human --person ...`. Для прежних предложений без person идентичность
автора — старое имя токена; сохраните её при перевыпуске.

```sh
wikisvc schema upgrade                  # добавляет схему policy layer
wikisvc migrate-rules --dry-run         # отчёт без изменения страниц
# Если есть legacy-страницы: задайте WIKI_TOKEN writer, затем
wikisvc migrate-rules                   # готовит предложение, человек его принимает
# Чтобы также заменить стандартные инструкции/сценарии шаблоном v2:
wikisvc schema upgrade --refresh-instructions
wikisvc reindex --full
wikisvc lint
```

Без `--refresh-instructions` существующие AGENTS/workflows не заменяются.
Перед заменой перенесите свои дополнения. Старые convention/stack/security/testing
превращаются в кандидаты rule; ссылки переписываются внутри предложения.
`schema/tags.yaml` и scopes ведёт администратор. У новых вики есть стартовые теги;
пустой tags допустим. В старой `.gitignore` должны быть `.obsidian/`, `inbox/*`,
`!inbox/.gitkeep`. Чистота проверяется в wiki/raw/schema и staging; посторонние
неотслеживаемые файлы за их пределами не мешают записи.

## Проверки

```sh
just lint
pytest --cov --cov-report=term-missing
nix flake check
python scripts/benchmark_graph.py
wikiagent eval --role planner --model wiki-gemma-12b --out .dev/eval.json
```

Тесты используют настоящие временные Git-репозитории, TestClient, Hypothesis,
MCP stdio и scripted HTTP-модель. Включены 40 правил компилятора, 40 правил с
проблемами для самолечения, PDF/EPUB и 450-страничный PDF, восстановление после
аварий и изоляция допусков. Порог покрытия ядра — 85%; строгий mypy и Ruff.

`eval` проверяет входные фразы и ожидаемые действия/вопросы, сохраняет прогресс
после каждого случая. Ошибка модели считается провалом сценария. Прохождение
заглушки проверяет конвейер, а не качество LLM. Для production_ready нужны минимум
30 сценариев, точность ≥90%, ноль запретных вызовов и ≤1 лишнего вопроса в среднем.
В репозитории 12 основных сценариев; реальный отчёт и параметры проверки —
в [docs/model-evaluation.md](docs/model-evaluation.md).

Вне объёма v2: UI, OCR, OIDC, эмбеддинги, графовая БД и модуль NixOS для wikiagent.
Сервис использует только BM25; старый заготовочный векторный провайдер удалён.
[Решения](docs/decisions.md), [прогресс](docs/progress.md),
[спецификация v2](docs/policy-layer-spec.md).
