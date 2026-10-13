#!/usr/bin/env bash
# Maintenance commands run in a one-off container of the installed release image, as
# llm-wiki, with every data directory and setting (see llm-wiki-run's maintenance).
set -euo pipefail
export PATH=@tools@:/usr/sbin:/usr/bin:/sbin:/bin
if [[ $(id -u) != 0 ]]; then
    echo 'Run with sudo: the services run under rootful podman with their own uids.' >&2
    exit 1
fi
run=@bundle@/bin/llm-wiki-run
case "${1:-}" in
    wikisvc | wikiagent)
        exec "$run" once maintenance "$@"
        ;;
    check)
        shift
        exec "$run" once maintenance wikiagent check "$@"
        ;;
    git)
        shift
        wiki_root=$(sed -n 's/^WIKI_ROOT=//p' /etc/llm-wiki/service.env | tail -n 1)
        exec "$run" once maintenance git -C "${wiki_root:-/var/lib/llm-wiki/wiki}" "$@"
        ;;
    *)
        echo 'Usage: llm-wiki-admin {wikisvc|wikiagent|git|check} [arguments...]' >&2
        exit 2
        ;;
esac
