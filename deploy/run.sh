#!/usr/bin/env bash
# Starts a wiki service from the release image with the confinement its systemd unit
# gave it before containers: its own uid, a read-only root, no capabilities, and
# write access only where it writes. Units, llm-wiki-admin and llm-wiki-updater all
# start containers through here, so these flags exist in one place.
#
# llm-wiki-run daemon SERVICE          from SERVICE's unit (needs LLM_WIKI_CIDFILE)
# llm-wiki-run once PROFILE COMMAND... one-off container: maintenance and migrations
#
# SERVICE is wikisvc, wikiagent or wiki-ui; PROFILE is one of them or maintenance.
set -euo pipefail
export PATH=@tools@:/usr/sbin:/usr/bin:/sbin:/bin

usage() {
    echo 'Usage: llm-wiki-run daemon {wikisvc|wikiagent|wiki-ui}' >&2
    echo '       llm-wiki-run once {wikisvc|wikiagent|wiki-ui|maintenance} COMMAND...' >&2
    exit 2
}

mode=${1:-}
profile=${2:-}
[[ $mode == daemon || $mode == once ]] || usage
if [[ $(id -u) != 0 ]]; then
    echo 'Run as root: the services run under rootful podman with their own uids.' >&2
    exit 1
fi

# Parsed, not sourced: llm-wiki-updater rewrites this file.
image=$(sed -n 's/^LLM_WIKI_IMAGE=//p' /etc/llm-wiki/image.env | tail -n 1)
if [[ ! $image =~ ^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$ ]]; then
    echo 'Set LLM_WIKI_IMAGE in /etc/llm-wiki/image.env to an image pinned by digest (…@sha256:…).' >&2
    exit 1
fi

# --init: the kernel drops signals PID 1 has no handler for, so a CLI as PID 1 would
# ignore SIGTERM and hold a stop until the unit's timeout; it also reaps git's
# orphaned children, which would otherwise pile up as zombies in long-lived services.
flags=(
    --init --pull never --log-driver journald --network host
    --read-only --tmpfs /tmp:mode=1777 --cap-drop ALL --security-opt no-new-privileges
    --env PYTHONUNBUFFERED=1
)
case $profile in
    wikisvc)
        user=llm-wiki
        command=(wikisvc serve)
        flags+=(
            --env-file /etc/llm-wiki/service.env
            --volume /var/lib/llm-wiki:/var/lib/llm-wiki
            --volume /etc/llm-wiki:/etc/llm-wiki:ro
        )
        ;;
    wikiagent)
        user=llm-wiki
        command=(wikiagent serve)
        flags+=(
            --env-file /etc/llm-wiki/service.env --env-file /etc/llm-wiki/agent.env
            --volume /var/lib/llm-wiki:/var/lib/llm-wiki:ro
            --volume /var/lib/llm-wiki/agent:/var/lib/llm-wiki/agent
            --volume /etc/llm-wiki:/etc/llm-wiki:ro
        )
        ;;
    wiki-ui)
        user=llm-ui
        command=(wiki-ui)
        flags+=(--env-file /etc/llm-wiki/ui.env --volume /etc/llm-wiki:/etc/llm-wiki:ro)
        ;;
    maintenance)
        # What llm-wiki-admin had as llm-wiki: every data directory and every setting.
        [[ $mode == once ]] || usage
        user=llm-wiki
        command=()
        flags+=(
            --env-file /etc/llm-wiki/service.env --env-file /etc/llm-wiki/agent.env
            --env-file /etc/llm-wiki/ui.env
            --volume /var/lib/llm-wiki:/var/lib/llm-wiki
            --volume /etc/llm-wiki:/etc/llm-wiki:ro
        )
        ;;
    *) usage ;;
esac
flags+=(--user "$(id -u "$user"):$(id -g "$user")")

if [[ $mode == daemon ]]; then
    [[ $# -eq 2 ]] || usage
    : "${LLM_WIKI_CIDFILE:?Set by the systemd unit: Environment=LLM_WIKI_CIDFILE=%t/%n.ctr-id}"
    exec podman run --detach --replace --rm --name "$profile" --cidfile "$LLM_WIKI_CIDFILE" \
        --cgroups split --sdnotify conmon "${flags[@]}" "$image" "${command[@]}"
fi
shift 2
[[ $# -gt 0 ]] || usage
terminal=()
if [[ -t 0 ]]; then
    terminal+=(--interactive)
fi
if [[ -t 1 ]]; then
    terminal+=(--tty)
fi
exec podman run --rm "${terminal[@]}" "${flags[@]}" "$image" "$@"
