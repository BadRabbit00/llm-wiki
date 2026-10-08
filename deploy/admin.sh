#!/usr/bin/env bash
set -euo pipefail
export PATH=@tools@:/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID -eq 0 ]]; then
    if [[ ${1:-} == check || ${1:-} == wikiagent && ${2:-} == check ]]; then
        # Only root can read the llm-ui configuration. Export paths, never file contents.
        set -a
        # shellcheck disable=SC1091
        source /etc/llm-wiki/ui.env
        set +a
    fi
    exec runuser -u llm-wiki -- @bundle@/bin/llm-wiki-admin "$@"
fi
if [[ $(id -un) != llm-wiki ]]; then
    echo 'Run with sudo; data must be owned by llm-wiki.' >&2
    exit 1
fi
set -a
# These files are root-owned and use the shared shell/EnvironmentFile subset.
# shellcheck disable=SC1091
source /etc/llm-wiki/service.env
set +a
cd /var/lib/llm-wiki
case "${1:-}" in
    wikisvc) shift; exec @app@/bin/wikisvc "$@" ;;
    git) shift; exec @git@/bin/git -C "$WIKI_ROOT" "$@" ;;
    wikiagent|check)
        command=$1
        shift
        set -a
        # shellcheck disable=SC1091
        source /etc/llm-wiki/agent.env
        set +a
        if [[ $command == check ]]; then
            exec @bundle@/bin/llm-wiki-check "$@"
        fi
        exec @app@/bin/wikiagent "$@"
        ;;
    *) echo 'Usage: llm-wiki-admin {wikisvc|wikiagent|git|check} [arguments...]' >&2; exit 2 ;;
esac
