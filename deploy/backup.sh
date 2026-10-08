#!/usr/bin/env bash
set -euo pipefail
export PATH=@tools@:/usr/sbin:/usr/bin:/sbin:/bin
if [[ $(id -u) != 0 ]]; then
    echo 'Run through llm-wiki-backup.service as root, with wiki services stopped.' >&2
    exit 1
fi
if [[ $# -ne 0 ]]; then
    echo 'Usage: llm-wiki-backup (invoked by llm-wiki-backup.service)' >&2
    exit 2
fi
if [[ ${BACKUP_DIR:-} != /* || ! ${BACKUP_KEEP_DAYS:-} =~ ^[1-9][0-9]{0,4}$ ]]; then
    echo 'Set an absolute BACKUP_DIR and BACKUP_KEEP_DAYS between 1 and 99999 in backup.env.' >&2
    exit 2
fi
backup_dir=$(realpath -m -- "$BACKUP_DIR")
case "$backup_dir" in
    /|/var/lib/llm-wiki|/var/lib/llm-wiki/*|/etc/llm-wiki|/etc/llm-wiki/*)
        echo 'BACKUP_DIR must be a separate directory outside the archived data and configuration.' >&2
        exit 2
        ;;
esac

install -d -m 0700 -o root -g root -- "$backup_dir"
if command -v restorecon >/dev/null; then
    restorecon "$backup_dir"
fi
umask 077
temporary=$(mktemp "$backup_dir/.data-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.tar.gz.partial")
trap 'rm -f -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
tar -C / -czf "$temporary" \
    var/lib/llm-wiki/wiki var/lib/llm-wiki/state var/lib/llm-wiki/agent etc/llm-wiki
chmod 0600 "$temporary"
archive_name=${temporary##*/}
archive_name=${archive_name#.}
archive_name=${archive_name%.partial}
mv -- "$temporary" "$backup_dir/$archive_name"
if command -v restorecon >/dev/null; then
    restorecon "$backup_dir/$archive_name"
fi
# Only complete archives in this directory participate in retention.
find "$backup_dir" -maxdepth 1 -type f -name 'data-*.tar.gz' \
    ! -newermt "$BACKUP_KEEP_DAYS days ago" -delete
echo "Backup saved: $backup_dir/$archive_name"
