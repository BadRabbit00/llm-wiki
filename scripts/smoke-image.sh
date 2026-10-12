#!/usr/bin/env bash
# Start the built image the way the server runs it: non-root, read-only root
# filesystem, data only in a mounted volume, host loopback networking. Proves that
# the distroless image carries everything the services need at runtime.
# Usage: scripts/smoke-image.sh IMAGE_ARCHIVE   (CONTAINER_ENGINE=podman to use podman)
set -euo pipefail
archive=${1:?usage: smoke-image.sh IMAGE_ARCHIVE}
engine=${CONTAINER_ENGINE:-docker}
api_port=18887
ui_port=18889
prefix=llm-wiki-smoke-$$

image=$("$engine" load --quiet --input "$archive" | sed -n 's/^Loaded image: //p')
if [[ -z $image ]]; then
    echo "Could not load $archive" >&2
    exit 1
fi
data=$(mktemp -d)
cleanup() {
    status=$?
    for name in "$prefix-wikisvc" "$prefix-ui"; do
        if [[ $status -ne 0 ]] && "$engine" container inspect "$name" >/dev/null 2>&1; then
            echo "--- logs of $name" >&2
            "$engine" logs "$name" >&2
        fi
        "$engine" rm --force "$name" >/dev/null 2>&1 || true
    done
    rm -rf -- "$data"
    exit "$status"
}
trap cleanup EXIT

wait_for() {
    for _ in $(seq 60); do
        if curl --silent --fail --output /dev/null "$1"; then
            return 0
        fi
        sleep 1
    done
    echo "No answer from $1" >&2
    return 1
}

common=(
    --read-only --tmpfs /tmp --network host --user "$(id -u):$(id -g)"
    --cap-drop ALL --security-opt no-new-privileges
    --volume "$data:/var/lib/llm-wiki"
)
wiki=(
    --env WIKI_ROOT=/var/lib/llm-wiki/wiki --env STATE_DIR=/var/lib/llm-wiki/state
    --env INDEX_DIR=/var/lib/llm-wiki/index --env BIND_HOST=127.0.0.1 --env "BIND_PORT=$api_port"
)
"$engine" run --rm "${common[@]}" "$image" git --version
"$engine" run --rm "${common[@]}" "$image" wikiagent --help >/dev/null
"$engine" run --rm "${common[@]}" "${wiki[@]}" "$image" wikisvc init /var/lib/llm-wiki/wiki
"$engine" run --rm "${common[@]}" "${wiki[@]}" "$image" wikisvc reindex --full
"$engine" run --detach --name "$prefix-wikisvc" "${common[@]}" "${wiki[@]}" "$image" wikisvc serve >/dev/null
wait_for "http://127.0.0.1:$api_port/api/v1/health"

mkdir "$data/etc"
printf 'smoke-secret' >"$data/etc/ui-oidc.secret"
printf 'smoke-token' >"$data/etc/ui-session.token"
"$engine" run --detach --name "$prefix-ui" "${common[@]}" \
    --volume "$data/etc:/etc/llm-wiki:ro" \
    --env WIKI_UI_BIND=127.0.0.1:$ui_port \
    --env WIKI_UI_WIKISVC_URL=http://127.0.0.1:$api_port \
    --env WIKI_UI_AGENT_URL=http://127.0.0.1:18888 \
    --env WIKI_UI_OIDC_ISSUER=http://127.0.0.1:18890 \
    --env WIKI_UI_OIDC_CLIENT_ID=smoke \
    --env WIKI_UI_OIDC_SECRET_FILE=/etc/llm-wiki/ui-oidc.secret \
    --env WIKI_UI_SESSION_TOKEN_FILE=/etc/llm-wiki/ui-session.token \
    --env WIKI_UI_OIDC_REDIRECT_URL=http://127.0.0.1:$ui_port/auth/callback \
    --env WIKI_UI_OIDC_INSECURE_HTTP=1 --env WIKI_UI_COOKIE_SECURE=0 \
    "$image" wiki-ui >/dev/null
wait_for "http://127.0.0.1:$ui_port/healthz"
echo "Image $image: wikisvc, wikiagent, wiki-ui and git start."
