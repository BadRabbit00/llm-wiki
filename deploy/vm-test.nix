# The deployment as a server sees it: llm-wiki-install from the host bundle, the
# release image loaded into rootful podman, and the services started by their own
# systemd units. The model and wikiagent are not started: the agent needs a model
# and its container flags are covered by tests/test_run_container.py.
{ pkgs, deployment, image }:
pkgs.testers.runNixOSTest {
  name = "llm-wiki-podman-deployment";
  nodes.server = {
    virtualisation.podman.enable = true;
    virtualisation.memorySize = 2048;
    virtualisation.diskSize = 8192;
    environment.systemPackages = [ deployment pkgs.curl ];
    system.extraDependencies = [ image ];
    # The scripts and units expect a conventional distribution such as Arch: host tools
    # in /usr/bin and /usr/sbin. NixOS keeps them elsewhere, so the VM links them there.
    systemd.tmpfiles.rules = [ "d /usr/sbin 0755 root root -" ]
      ++ map (tool: "L+ /usr/bin/${tool} - - - - /run/current-system/sw/bin/${tool}")
        [ "podman" "systemctl" "tar" "gzip" "find" "getent" ]
      ++ map (tool: "L+ /usr/sbin/${tool} - - - - /run/current-system/sw/bin/${tool}")
        [ "groupadd" "useradd" "usermod" ];
  };
  testScript = ''
    import json
    from datetime import timedelta

    repository = "ghcr.io/badrabbit00/llm-wiki"


    def no_containers_left():
        # podman run --rm returns before conmon has finished removing the container.
        try:
            server.wait_until_succeeds(
                "test -z \"$(podman ps --all --quiet)\"", timeout=timedelta(seconds=30)
            )
        except Exception:
            print(server.succeed("podman ps --all --format '{{.Names}} {{.Status}} {{.Command}}'"))
            raise


    server.wait_for_unit("multi-user.target")
    # On NixOS /etc/systemd/system links into the read-only store; on Arch, where
    # llm-wiki-install puts the units, it is an ordinary directory.
    server.succeed(
        "mkdir /etc/systemd/system.local"
        " && cp -a /etc/systemd/system/. /etc/systemd/system.local/"
        " && rm /etc/systemd/system && mv /etc/systemd/system.local /etc/systemd/system"
    )
    server.succeed("llm-wiki-install")

    with subtest("the services refuse an image that is not pinned by digest"):
        server.succeed(f"echo 'LLM_WIKI_IMAGE={repository}:${image.imageTag}' > /etc/llm-wiki/image.env")
        server.fail("systemctl start wikisvc")
        server.succeed("journalctl -u wikisvc | grep -q 'pinned by digest'")
        # Restart=on-failure keeps retrying until the image is fixed; cancel that here.
        server.succeed("systemctl stop wikisvc")

    server.succeed("podman load --input ${image}")
    digest = server.succeed(
        f"podman image inspect --format '{{{{.Digest}}}}' {repository}:${image.imageTag}"
    ).strip()
    server.succeed(f"echo 'LLM_WIKI_IMAGE={repository}@{digest}' > /etc/llm-wiki/image.env")

    with subtest("maintenance commands run as llm-wiki in a one-off container"):
        server.succeed("llm-wiki-admin wikisvc init /var/lib/llm-wiki/wiki")
        no_containers_left()
        server.succeed("llm-wiki-admin wikisvc reindex --full")
        no_containers_left()
        # A reader that stops early (grep -q, head) must not strand the container.
        server.succeed("llm-wiki-admin git log --oneline | grep -q .")
        server.succeed("test \"$(stat -c %U /var/lib/llm-wiki/wiki/.git)\" = llm-wiki")
        no_containers_left()

    with subtest("wikisvc runs under its unit with the unit's confinement"):
        server.succeed("systemctl start wikisvc")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
        container = json.loads(server.succeed("podman inspect wikisvc"))[0]
        uid = server.succeed("id -u llm-wiki").strip()
        assert container["Config"]["User"].startswith(uid + ":"), container["Config"]["User"]
        assert container["HostConfig"]["ReadonlyRootfs"], "root filesystem is writable"
        assert container["HostConfig"]["CapDrop"], "capabilities were not dropped"

    with subtest("wiki-ui runs as llm-ui and reaches wikisvc"):
        server.succeed(
            "printf '%s\\n' WIKI_UI_BIND=127.0.0.1:8789 WIKI_UI_WIKISVC_URL=http://127.0.0.1:8787"
            " WIKI_UI_AGENT_URL=http://127.0.0.1:8788 WIKI_UI_OIDC_ISSUER=http://127.0.0.1:18790"
            " WIKI_UI_OIDC_CLIENT_ID=vm-test WIKI_UI_OIDC_SECRET_FILE=/etc/llm-wiki/ui-oidc.secret"
            " WIKI_UI_SESSION_TOKEN_FILE=/etc/llm-wiki/ui-session.token"
            " WIKI_UI_OIDC_REDIRECT_URL=http://127.0.0.1:8789/auth/callback"
            " WIKI_UI_OIDC_INSECURE_HTTP=1 WIKI_UI_COOKIE_SECURE=0 > /etc/llm-wiki/ui.env"
        )
        server.succeed("echo vm-secret > /etc/llm-wiki/ui-oidc.secret")
        server.succeed("echo vm-token > /etc/llm-wiki/ui-session.token")
        server.succeed("systemctl start wiki-ui")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8789/healthz")
        uid = server.succeed("id -u llm-ui").strip()
        user = json.loads(server.succeed("podman inspect wiki-ui"))[0]["Config"]["User"]
        assert user.startswith(uid + ":"), user

    with subtest("restart replaces the container and stop removes it"):
        server.succeed("systemctl restart wikisvc")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
        # wiki-ui wants wikiagent, which waits in its check container for the model.
        assert server.succeed("systemctl is-active wikiagent || true").strip() == "activating"
        server.succeed("systemctl stop wiki-ui wikiagent wikisvc")
        no_containers_left()

    with subtest("the backup job stops the services, archives and starts them again"):
        server.succeed("systemctl start wikisvc")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
        server.succeed("systemctl start llm-wiki-backup")
        server.succeed("ls /var/backups/llm-wiki/data-*.tar.gz")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
  '';
}
