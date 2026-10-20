# ADR-0014 — Деплой: контейнеры podman под systemd и хост-часть из Nix
status: accepted | date: 2026-10-13

## Контекст

Сервер — обычный Linux-дистрибутив с systemd (Arch), не NixOS. Службы приходят образом (ADR-0011),
модель работает на хосте с GPU. Ограничения прежних systemd-юнитов нужно сохранить.

## Решение

`wikisvc`, `wikiagent`, `wiki-ui` — контейнеры образа в rootful podman из дистрибутива, каждый своим
systemd-юнитом в стиле Quadlet (`Type=notify`, `--sdnotify conmon`, `--cgroups split`, `Delegate=yes`).
Все флаги podman — в одном `llm-wiki-run` (`deploy/run.sh`): свой uid, read-only корень, `--cap-drop ALL`,
`no-new-privileges`, запись только в свои каталоги, `--network host`, `--init`, `--pull never`.
Nix ставит только хост-часть `.#deployment`: юниты, шаблоны конфигурации, скрипты, без приложения.
Образ задаётся в `/etc/llm-wiki/image.env` только по дайджесту.

## Почему

- одно место флагов для юнитов, `llm-wiki-admin` и updater — ограничения не расходятся (rule-deploy-runtime-hardening);
- дайджест не сдвигается (rule-deploy-by-digest); `--pull never` — после перезагрузки службы поднимаются без сети;
- `--init` (catatonit): иначе CLI как PID 1 игнорирует SIGTERM, а осиротевшие процессы git копятся зомби;
- хост-часть собирается за секунды.

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| NixOS-модуль | сервер не NixOS |
| процессы на хосте без контейнеров | сервер собирал бы приложение (ADR-0011) |

## Последствия

- проверка на настоящих systemd и podman — `deploy/vm-test.nix`;
- ENV-файлы podman читает без снятия кавычек, они остаются простыми `KEY=value`;
- затрагивает: RES-host, RES-container-image, TOOL-podman, SVC-wikisvc, SVC-wikiagent, SVC-wiki-ui.
