# wiki-ui: данные

> Постоянных данных у компонента нет: БД, файлов и KV-сервера он не использует. Сессия — токен
> SVC-wikisvc (ENT-session), её состояние и срок хранит и проверяет SVC-wikisvc. Ниже — только
> состояние в памяти процесса и в браузере; рестарт процесса теряет его без вреда, кроме незавершённых входов.

## Кэш и KV

### KV-wiki-ui.oidc-flows — Незавершённые входы через OIDC
status: implemented | owner: SVC-wiki-ui | store: память процесса `wiki-ui`

- key: `state` (32 случайных байта, base64url), type: map в памяти под мьютексом.
- value: `nonce`, PKCE `verifier`, `expires`.
- ttl: 10m от API-wiki-ui.auth.login.
- invalidation: снимается одноразово в API-wiki-ui.auth.callback; просроченные чистятся при каждом
  входе и раз в 5m (JOB-wiki-ui.oidc-refresh). Не больше 10 000 записей — дальше вход отвечает 503.
- source of truth: сама; потеря (рестарт) — пользователь начинает вход заново.

### KV-wiki-ui.oidc-provider — Метаданные и ключи IdP
status: implemented | owner: SVC-wiki-ui | store: память процесса `wiki-ui`

- key: один экземпляр на процесс.
- value: OAuth2-конфигурация из discovery EXT-authentik (`authorization`, `token`, `jwks_uri`,
  `end_session_endpoint`) и набор публичных ключей подписи RS256 из JWKS.
- ttl: discovery обновляется на каждом API-wiki-ui.auth.login; JWKS — раз в 5m
  (JOB-wiki-ui.oidc-refresh) и сразу при подписи неизвестным ключом.
- invalidation: при недоступности IdP остаются последние валидные ключи.
- source of truth: EXT-authentik; кэш можно потерять без последствий (до первого входа выход
  не перенаправляет в IdP).

## Состояние в браузере

| что | где | смысл |
|---|---|---|
| cookie `wiki_session` | браузер, HttpOnly | токен сессии SVC-wikisvc; JS его не читает (контракт — `contracts.md`) |
| cookie `wiki_oidc_flow` | браузер, HttpOnly, `Path=/auth` | привязка `state` входа к браузеру, 10m |
| кэш TanStack Query | память вкладки | ответы API, `staleTime` 20s, без повторов, обновление при фокусе окна; очищается при выходе |
| `localStorage["wiki.theme"]` | браузер | выбранная тема `light`/`dark`; токенов и данных вики в хранилище браузера нет |
| ключи `["wiki", "kb", …]` кэша TanStack Query | память вкладки | (v3 planned) ответы API-wikisvc.knowledge.* и графа с весами (CLS-wiki-ui.useKnowledge); те же `staleTime`, повторы и очистка при выходе |
| параметры адреса `?level=`, `?domain=`, `?soft=&origin=&min_w=` | URL вкладки | (v3 planned) уровень вида хаба, домен вопросов, фильтры графа; не секреты и не данные вики — ссылкой можно поделиться |
| решения ревьюера по фактам предложения | память компонента CLS-wiki-ui.ClaimReview | (v3 planned) до отправки вместе с принятием; перезагрузка вкладки их теряет — сервер ничего не получил |
