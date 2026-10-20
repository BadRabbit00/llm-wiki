# ADR-0011 — Один образ релиза для трёх служб в GHCR
status: accepted | date: 2026-10-12

## Контекст

Раньше сервер собирал службы сам. wikisvc, wikiagent и wiki-ui работают с общими данными и не должны
расходиться по версиям.

## Решение

Релиз — один OCI-образ `ghcr.io/badrabbit00/llm-wiki` (RES-container-image) из `deploy/image.nix`
(`dockerTools.buildLayeredImage`): closures служб, git, CA-сертификаты, passwd/group, без shell и пакетного
менеджера. Публикует только PIPE-release в EXT-ghcr, на каждый дайджест — attestation происхождения.
Сервер запускает образ только по дайджесту. `llama-server` в образ не входит.

## Почему

- один дайджест — три службы одной версии на общих данных;
- сервер не собирает (rule-deploy-build-once), а тянет проверенный артефакт;
- distroless-образ (rule-deploy-dockertools-distroless); права записи в реестр — только у одного workflow;
- GPU, модель и их обновления остаются на хосте.

## Что рассматривали и отвергли

| вариант | почему нет |
|---|---|
| сборка на сервере из checkout | долго, и на сервере работает непроверенная сборка |
| по образу на службу | службы могут разойтись по версиям |
| образ в `nix flake check` | метка ревизии меняет его на каждом коммите; проверка — запуск `scripts/smoke-image.sh` |

## Последствия

- проверка подлинности — attestation (`cosign verify-attestation`, ADR-0015);
- `skopeo` берётся из закреплённого nixpkgs только в CI;
- затрагивает: RES-container-image, PIPE-release, PIPE-ci, EXT-ghcr, SVC-wikisvc, SVC-wikiagent, SVC-wiki-ui.
