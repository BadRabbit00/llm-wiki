#!/usr/bin/env bash
set -euo pipefail
export PATH=@tools@:/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID -ne 0 || ! -d /run/systemd/system ]]; then
    echo 'Run with sudo on the target Linux host with systemd.' >&2
    exit 1
fi
if [[ $# -ne 0 ]]; then
    echo 'Usage: llm-wiki-install (installs this built version; preserves configuration and data)' >&2
    exit 2
fi
for unit in wikisvc wikiagent wiki-ui llm-wiki-backup; do
    state=$(systemctl is-active "$unit.service" 2>/dev/null || true)
    if [[ $state == active || $state == activating || $state == deactivating || $state == reloading ]]; then
        echo "Stop wiki-ui, wikiagent, wikisvc and the backup job before installing ($unit: $state)." >&2
        exit 1
    fi
done
for account in llm-wiki llm-model llm-ui; do
    getent group "$account" >/dev/null || groupadd --system "$account"
    if ! id "$account" >/dev/null 2>&1; then
        useradd --system --gid "$account" --home-dir /nonexistent --no-create-home \
            --shell /sbin/nologin "$account"
    fi
done
for group in video render; do
    if getent group "$group" >/dev/null; then
        usermod --append --groups "$group" llm-model
    fi
done
install -d -m 0755 /opt/llm-wiki /etc/llm-wiki /srv/llm-wiki
install -d -m 0750 -o llm-model -g llm-model /srv/llm-wiki/models
install -d -m 0700 -o llm-model -g llm-model /var/cache/llm-wiki-model
install -d -m 0700 -o llm-wiki -g llm-wiki /var/lib/llm-wiki
for directory in state index agent; do
    install -d -m 0700 -o llm-wiki -g llm-wiki "/var/lib/llm-wiki/$directory"
done
for file in service.env agent.env wikiagent.yaml llama.env ui.env backup.env roles.yaml ui-oidc.secret ui-session.token; do
    if [[ ! -e /etc/llm-wiki/$file ]]; then
        config_group=llm-wiki
        [[ $file != llama.env ]] || config_group=llm-model
        case $file in ui.env|ui-oidc.secret|ui-session.token) config_group=llm-ui ;; esac
        [[ $file != backup.env ]] || config_group=root
        install -m 0640 -o root -g "$config_group" \
            "@bundle@/share/llm-wiki/almalinux/$file" "/etc/llm-wiki/$file"
    fi
done
# Permanent GC roots: the current and previous bundles survive deletion of result/checkout.
install -d -m 0755 /nix/var/nix/gcroots/llm-wiki
if [[ -L /opt/llm-wiki/current ]]; then
    previous=$(readlink -f /opt/llm-wiki/current)
    if [[ $previous != @bundle@ ]]; then
        @nix@/bin/nix-store --realise "$previous" \
            --add-root /nix/var/nix/gcroots/llm-wiki/previous >/dev/null
        ln -sfn "$previous" /opt/llm-wiki/previous
    fi
fi
@nix@/bin/nix-store --realise @bundle@ \
    --add-root /nix/var/nix/gcroots/llm-wiki/current >/dev/null
ln -sfn @bundle@ /opt/llm-wiki/current
for unit in wikisvc wikiagent llm-wiki-model wiki-ui llm-wiki-backup; do
    install -m 0644 "@bundle@/share/llm-wiki/systemd/$unit.service" "/etc/systemd/system/$unit.service"
done
install -m 0644 "@bundle@/share/llm-wiki/systemd/llm-wiki-backup.timer" \
    /etc/systemd/system/llm-wiki-backup.timer
ln -sfn /opt/llm-wiki/current/bin/llm-wiki-admin /usr/local/sbin/llm-wiki-admin
if command -v restorecon >/dev/null; then
    restorecon -RF /etc/llm-wiki /var/lib/llm-wiki /var/cache/llm-wiki-model \
        /srv/llm-wiki /opt/llm-wiki /usr/local/sbin/llm-wiki-admin
    restorecon /etc/systemd/system/{wikisvc,wikiagent,llm-wiki-model,wiki-ui,llm-wiki-backup}.service \
        /etc/systemd/system/llm-wiki-backup.timer
fi
systemctl daemon-reload
echo 'Installed. Configuration preserved. Follow docs/deploy-almalinux.md to initialize/restore and start.'
