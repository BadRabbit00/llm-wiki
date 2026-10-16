#!/usr/bin/env bash
# Install the scopes, profiles and project templates next to this script into the live
# wiki, commit them and restart wikisvc, which reads the schema only at start.
# The copy and commit hold wikisvc's own write lock, so they cannot interleave with a
# proposal commit. lint takes that lock itself and therefore runs after it is released.
# Files are added or replaced, never removed: deleting a profile or template is manual.
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
wiki_root=$(sed -n 's/^WIKI_ROOT=//p' /etc/llm-wiki/service.env | tail -n 1)
wiki=${wiki_root:-/var/lib/llm-wiki/wiki}
state_dir=$(sed -n 's/^STATE_DIR=//p' /etc/llm-wiki/service.env | tail -n 1)
lock=${state_dir:-/var/lib/llm-wiki/state}/write.lock
port=$(sed -n 's/^BIND_PORT=//p' /etc/llm-wiki/service.env | tail -n 1)
git_author=(-c user.name=cli -c user.email=token@wikisvc.local)
message=${1:?usage: apply.sh COMMIT_MESSAGE}

if [[ $(id -u) != 0 ]]; then
    echo 'Run with sudo: the wiki belongs to llm-wiki and llm-wiki-admin needs root.' >&2
    exit 1
fi
if [[ -n $(llm-wiki-admin git status --porcelain) ]]; then
    echo 'The wiki working tree is dirty; resolve it before applying the schema.' >&2
    exit 1
fi

exec 9>>"$lock"
flock -w 60 9
install -d -o llm-wiki -g llm-wiki -m 0755 "$wiki/schema/profiles" "$wiki/schema/project-templates"
install -o llm-wiki -g llm-wiki -m 0600 "$src/scopes.yaml" "$wiki/schema/scopes.yaml"
install -o llm-wiki -g llm-wiki -m 0600 "$src"/profiles/*.yaml "$wiki/schema/profiles/"
install -o llm-wiki -g llm-wiki -m 0600 "$src"/project-templates/*.yaml "$wiki/schema/project-templates/"
llm-wiki-admin git add schema/scopes.yaml schema/profiles schema/project-templates
if [[ -z $(llm-wiki-admin git diff --cached --name-only) ]]; then
    echo 'The live schema already matches; nothing to do.'
    exit 0
fi
llm-wiki-admin git "${git_author[@]}" commit -q -m "$message"
llm-wiki-admin git log -1 --stat --format='%h %an | %s'
flock -u 9

if ! llm-wiki-admin wikisvc lint >/dev/null; then
    echo 'lint found errors; wikisvc was not restarted. Inspect them with' >&2
    echo '  sudo llm-wiki-admin wikisvc lint' >&2
    echo 'and undo the commit with: sudo llm-wiki-admin git -c user.name=cli -c user.email=token@wikisvc.local revert --no-edit HEAD' >&2
    exit 1
fi
systemctl restart wikisvc
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${port:-8787}/api/v1/health"; then
        echo
        exit 0
    fi
    sleep 2
done
echo 'wikisvc did not become healthy; see journalctl -u wikisvc' >&2
exit 1
