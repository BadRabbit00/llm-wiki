#!/usr/bin/env bash
# A version tag publishes a release only if it names a commit already on main (which
# passed the full CI as a pull request) and the version the code itself reports.
# vX.Y.Z is the release channel; vX.Y.Z-beta.N is a beta of the same version.
# Usage: scripts/check-release-tag.sh TAG   (origin/main must be fetched)
set -euo pipefail
tag=${1:?usage: check-release-tag.sh TAG}
pattern='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-beta\.(0|[1-9][0-9]*))?$'
if [[ ! $tag =~ $pattern ]]; then
    echo "Tag $tag is neither vX.Y.Z (release) nor vX.Y.Z-beta.N (beta)." >&2
    exit 1
fi
base=${tag#v}
base=${base%%-*}
code=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
if [[ $base != "$code" ]]; then
    echo "Tag $tag is for version $base, but pyproject.toml declares $code." >&2
    exit 1
fi
if ! git merge-base --is-ancestor "$tag^{commit}" origin/main; then
    echo "Tag $tag points to a commit that is not on main." >&2
    exit 1
fi
echo "Release tag $tag: version $base, commit on main."
