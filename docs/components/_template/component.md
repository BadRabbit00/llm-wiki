# <Имя компонента>

> Карточка компонента. Скопируй папку `_template` в `components/<имя>/` и заполни.
> Агент читает этот файл первым, когда задача касается компонента. Не больше 120 строк.

### SVC-<имя> — <Человеческое название>
status: <draft | planned | implemented> | kind: <http-service | worker | frontend | bot | cli | lib> | lang: LANG-<…>

- purpose: <одно предложение: зачем этот компонент существует>
- not responsible for: <что он НЕ делает, даже если кажется, что должен>
- path: `<путь в репозитории>`
- manifest: `<pyproject.toml / package.json / go.mod / Cargo.toml>`, lock: `<uv.lock / pnpm-lock.yaml / go.sum / Cargo.lock>`
- build: TOOL-<…>; `<команда сборки>`
- run locally: `<команда>` (порт <N>)
- test: `<команда>`
- entrypoints: `<путь к main>` — <что запускает>
- framework: DEP-<…>
- deps: DEP-<…>, DEP-<…> (полный список в `stack/dependencies.md`, фильтр по used_by)
- models: MDL-<…>

## Что компонент даёт другим

- API: API-<имя>.*
- events published: EVT-<…>
- cli: CLI-<…>

## Что компонент использует

| что | зачем | что будет, если недоступно |
|---|---|---|
| API-<чужой> | <…> | <ретраи / деградация / падаем> |
| EVT-<чужое> | <…> | <…> |
| EXT-<…> | <…> | <…> |

## Данные

- owns: TBL-<…>, KV-<…>, BKT-<…> (детали — `data.md`)
- store: RES-<…>
- migrations: <инструмент (DEP-<…>), путь `<…>`, кто и когда запускает>
- reads foreign data: <нет / только через API-<…>> — **напрямую в чужие таблицы не ходим**

## Устройство

- modules: MOD-<имя>.<…>, MOD-<имя>.<…> (детали — `code.md`)
- jobs: JOB-<…> (детали — `runtime.md`)
- config: CFG-<…> (детали — `runtime.md`)

## Развёртывание

- runs on: RES-<…>, ENV-<…>
- unit: <docker-образ / nix-модуль / systemd-юнит>, ресурсы: <CPU, RAM, GPU>
- scaling: <сколько реплик, можно ли больше одной — важно для JOB>
- health: OBS-<…>

## Решения

- ADR-<NNNN> — <почему этот язык / фреймворк / подход>
