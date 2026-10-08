# 08 — Операционное: то, что провалится молча

Три вещи, которые не дают ошибки при настройке и обнаруживаются только последствиями.

---

## 1. Лимит запросов выключен по умолчанию

`rate_limit_per_min` имеет значение `0` (`src/wikisvc/config.py:34`), то есть ограничения нет.
Лимит считается по имени токена (`src/wikisvc/services/auth.py:108-121`). Несколько агентов
в цикле насыщают сервис без всякого сопротивления.

**Важное следствие из задачи 09:** у анонимного принципала одно имя на всех, поэтому встроенный
лимит для клиентов без credential либо не действует, либо действует как один общий счётчик.
Основной лимит для анонимного трафика ставится **на обратном прокси, по IP**.
Встроенный остаётся защитой для служебных и сессионных токенов.

### Что сделать

- `deploy/almalinux/service.env`: `RATE_LIMIT_PER_MIN=120` вместо пустого значения;
- `docs/deploy-almalinux.md`, раздел «Доступ и диагностика»: абзац — лимит считается на токен,
  запросы `health` не считаются, превышение даёт `429 E_RATE_LIMIT`;
- там же: при `ANONYMOUS_ACCESS=1` настроить ограничение по IP на обратном прокси перед `wiki-ui`,
  потому что все анонимные клиенты делят одно имя;
- `README.md`: в строке про `RATE_LIMIT_PER_MIN` указать, что значение по умолчанию отключает лимит.

Код не меняется: механизм есть и работает.

---

## 2. Резервная копия

GitHub хранит код. `state.db`, git-worktrees, библиотеку, сессии и `agent.env` не хранит никто.
Снимать копию на работающих службах нельзя: SQLite и worktrees дадут рваный архив,
который выглядит целым до дня восстановления.

### Что сделать

Добавить в комплект развёртывания systemd-таймер. Файлы — в `deploy/systemd/`,
установка — в `deploy/install.sh` рядом с остальными юнитами.

`llm-wiki-backup.service` (`Type=oneshot`):

1. `ExecStartPre`: `systemctl stop wiki-ui wikiagent wikisvc`;
2. `ExecStart`: `install -d -m 0700 /var/backups/llm-wiki`, затем
   `umask 077`, `tar -C / -czf /var/backups/llm-wiki/data-<дата>.tar.gz
   var/lib/llm-wiki/wiki var/lib/llm-wiki/state var/lib/llm-wiki/agent etc/llm-wiki`;
3. `ExecStart`: удалить архивы старше `BACKUP_KEEP_DAYS`;
4. **`ExecStopPost`: `systemctl --no-block start wikisvc wikiagent wiki-ui`.**
   `ExecStopPost` выполняется и при неудачном `ExecStart`, и при неудачном `ExecStartPre` —
   поэтому упавший архив не оставит систему выключенной. `--no-block`, чтобы oneshot-юнит
   не ждал запуска служб и не рисковал взаимной блокировкой;
5. `index/` не включать.

`llm-wiki-backup.timer`: ежедневно, в окне простоя, `Persistent=true`.

Требования:

- каталог `0700`, архивы `0600`, владелец `root`;
- `restorecon` после создания каталога;
- параметры (`путь`, `BACKUP_KEEP_DAYS`) — в `/etc/llm-wiki/backup.env`, устанавливается как остальные
  env-файлы, существующий не перезаписывается;
- окно бэкапа не пересекается с окнами `heal` из `wikiagent.yaml` — проверить и написать это в документации;
- установщик `install.sh` не запускает таймер сам: `enable --now` делает человек, как с остальными службами.

Проверка восстановления — обязательный пункт в документации, не опция.

**`llm-wiki-admin` для проверки не использовать.** Он читает `/etc/llm-wiki/service.env`
и делает `cd /var/lib/llm-wiki` (`deploy/admin.sh`), то есть работал бы по **рабочим** путям
и тронул бы живую вику. Проверка идёт прямым вызовом CLI с переопределёнными путями,
все три указывают внутрь распакованной копии:

```sh
sudo install -d -m 0700 /tmp/restore-test
sudo tar -C /tmp/restore-test -xzf /var/backups/llm-wiki/data-<дата>.tar.gz
sudo install -d -m 0700 /tmp/restore-test/index      # index/ в архив не входит

sudo env \
  WIKI_ROOT=/tmp/restore-test/var/lib/llm-wiki/wiki \
  STATE_DIR=/tmp/restore-test/var/lib/llm-wiki/state \
  INDEX_DIR=/tmp/restore-test/index \
  /opt/llm-wiki/current/bin/wikisvc repair-worktrees

sudo env WIKI_ROOT=... STATE_DIR=... INDEX_DIR=... \
  /opt/llm-wiki/current/bin/wikisvc reindex --full
sudo env WIKI_ROOT=... STATE_DIR=... INDEX_DIR=... \
  /opt/llm-wiki/current/bin/wikisvc lint

sudo rm -rf /tmp/restore-test        # архив содержит etc/llm-wiki вместе с agent.env
```

Требования к разделу документации:

- `Settings` читает только окружение (`env_file=None`), поэтому три переменные задаются явно;
  рабочие пути в проверку не попадают ни при каком стечении обстоятельств;
- `INDEX_DIR` обязан быть вне `WIKI_ROOT` и не равен `STATE_DIR` — иначе валидатор не пустит;
- каталог проверки `0700` и удаляется после: в нём лежит `agent.env` и внутренние материалы;
- в тексте прямым предложением: ни одна команда проверки не указывает на `/var/lib/llm-wiki`.

Непроверенная копия копией не считается.

---

## 3. Самолечение включается после первого ручного цикла

`heal.enabled: false` в `deploy/almalinux/wikiagent.yaml` — так и оставить.
То же для `docs_audit.enabled: false` из задачи 07.

### Что сделать

В `docs/deploy-almalinux.md` — явный порядок включения, пунктами:

1. первая операция выполнена руками, одно предложение прошло ревью и принято;
2. `llm-wiki-admin check --model` проходит;
3. `timedatectl` — часовой пояс сервера совпадает с ожидаемым: окна `heal` используют местное время;
4. окна `heal` не пересекаются с окном бэкапа;
5. только после этого `heal.enabled: true` и `systemctl restart wikiagent`;
6. через сутки — посмотреть `/findings/stats`. Если по виду находок отклонено (`dismissed`)
   больше половины от решённых, статистика возвращает `recommendation: "Поднять порог уверенности"`
   (`src/wikisvc/services/findings.py:177-181`): много ложных срабатываний, значит
   `confidence_threshold` **занижен** и его надо **повысить**.
   Порог правит человек в `wikiagent.yaml`, система его не меняет сама.

---

## Готово, когда

- `RATE_LIMIT_PER_MIN` в `service.env` непустой, поведение описано в документации;
- `nix build .#deployment` содержит `llm-wiki-backup.service` и `.timer`, `install.sh` их раскладывает;
- `shellcheck` проходит (он уже в сборке), `tests/test_deployment.py` дополнен проверкой наличия
  новых юнитов и env-файла в комплекте;
- в `docs/deploy-almalinux.md` есть раздел «Резервное копирование» с таймером, ротацией и проверкой восстановления;
- в том же файле — пронумерованный порядок включения `heal` и `docs_audit`.

## Не делать

- не включать `heal` и `docs_audit` в комплекте по умолчанию;
- не писать бэкап без остановки служб и не делать «горячую» копию SQLite обходными путями;
- не складывать архивы в `/var/lib/llm-wiki` — они попадут в следующий архив;
- не включать таймер из установщика.
