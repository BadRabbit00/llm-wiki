# llm-wiki-updater on a real systemd and podman: a local registry offers releases,
# an administrator confirms one through the updater's socket, and the update stops,
# archives, switches, migrates and verifies; a release that does not run what its
# tag says is rolled back from the archive. Only the signature check is replaced:
# Sigstore is out of reach in a VM, so a stand-in cosign checks it is asked about
# the right tag and image; the real check is covered by the updater's Go tests.
{ pkgs, deployment, image, version }:
let
  # Same application, different labels: three digests whose wikisvc reports `version`.
  # The tags follow the code's version, so a release bump does not break this test.
  images = { a = image "vm-a"; b = image "vm-b"; c = image "vm-c"; };
  release = "v${version}";
  # The next patch release: a tag the images do not run, which the updater must roll back.
  parts = pkgs.lib.splitVersion version;
  next = pkgs.lib.concatStringsSep "." [
    (builtins.elemAt parts 0)
    (builtins.elemAt parts 1)
    (toString (pkgs.lib.toInt (builtins.elemAt parts 2) + 1))
  ];
  cosign = pkgs.writeShellScript "cosign-stand-in" ''
    echo "$*" >> /var/lib/llm-wiki-updater/cosign.log
    case "$*" in
      *"--certificate-identity https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/v"*"127.0.0.1:5000/llm-wiki@sha256:"*) exit 0 ;;
    esac
    exit 1
  '';
in
pkgs.testers.runNixOSTest {
  name = "llm-wiki-updater";
  nodes.server = {
    virtualisation.podman.enable = true;
    virtualisation.memorySize = 3072;
    virtualisation.diskSize = 12288;
    # The local registry speaks plain HTTP. Written in the v2 format current skopeo
    # requires; the NixOS registries options still produce v1.
    environment.etc."containers/registries.conf".text = pkgs.lib.mkForce ''
      [[registry]]
      location = "127.0.0.1:5000"
      insecure = true
    '';
    services.dockerRegistry = { enable = true; listenAddress = "127.0.0.1"; port = 5000; };
    environment.systemPackages = [ deployment pkgs.curl pkgs.skopeo pkgs.jq ];
    system.extraDependencies = builtins.attrValues images;
    systemd.tmpfiles.rules = [ "d /usr/sbin 0755 root root -" ]
      ++ map (tool: "L+ /usr/bin/${tool} - - - - /run/current-system/sw/bin/${tool}")
        [ "podman" "systemctl" "tar" "gzip" "find" "getent" ]
      ++ map (tool: "L+ /usr/sbin/${tool} - - - - /run/current-system/sw/bin/${tool}")
        [ "groupadd" "useradd" "usermod" ];
  };
  testScript = ''
    import json
    from datetime import timedelta

    registry = "127.0.0.1:5000/llm-wiki"
    socket = "/run/llm-wiki-updater/api.sock"


    def push(archive, tag):
        server.succeed(
            f"skopeo copy --insecure-policy --dest-tls-verify=false docker-archive:{archive} docker://{registry}:{tag}"
        )


    def api(method, path, token="", body=None):
        header = f"-H 'Authorization: Bearer {token}'" if token else ""
        data = f"-H 'Content-Type: application/json' -d '{json.dumps(body)}'" if body is not None else ""
        return json.loads(server.succeed(
            f"curl -s -X {method} {header} {data} --unix-socket {socket} http://updater{path}"
        ))


    def finished(token):
        status = api("GET", "/v1/status", token)
        return status["operation"] and status["operation"]["state"] != "running"


    def pinned():
        return server.succeed("cat /etc/llm-wiki/image.env").strip().rsplit("@", 1)[1]


    def digest_of(tag):
        return server.succeed(f"skopeo inspect --tls-verify=false --format '{{{{.Digest}}}}' docker://{registry}:{tag}").strip()


    server.wait_for_unit("multi-user.target")
    server.wait_for_unit("docker-registry.service")
    server.succeed(
        "mkdir /etc/systemd/system.local"
        " && cp -a /etc/systemd/system/. /etc/systemd/system.local/"
        " && rm /etc/systemd/system && mv /etc/systemd/system.local /etc/systemd/system"
    )
    server.succeed("llm-wiki-install")

    push("${images.a}", "${release}-beta.1")
    push("${images.b}", "${release}")
    server.succeed(f"podman pull {registry}:${release}-beta.1")
    server.succeed(f"echo 'LLM_WIKI_IMAGE={registry}@{digest_of('${release}-beta.1')}' > /etc/llm-wiki/image.env")

    server.succeed("llm-wiki-admin wikisvc init /var/lib/llm-wiki/wiki")
    server.succeed("llm-wiki-admin wikisvc reindex --full")
    admin = server.succeed(
        "llm-wiki-admin wikisvc token create --name admin --person admin --kind human --role admin --clearance restricted"
    ).strip()
    agent = server.succeed("llm-wiki-admin wikisvc token create --name robot --kind agent --role admin").strip()
    tokens_before = server.succeed("llm-wiki-admin wikisvc token list")
    server.succeed(
        "printf '%s\\n' WIKI_UI_BIND=127.0.0.1:8789 WIKI_UI_WIKISVC_URL=http://127.0.0.1:8787"
        " WIKI_UI_AGENT_URL=http://127.0.0.1:8788 WIKI_UI_OIDC_ISSUER=http://127.0.0.1:18790"
        " WIKI_UI_OIDC_CLIENT_ID=vm-test WIKI_UI_OIDC_SECRET_FILE=/etc/llm-wiki/ui-oidc.secret"
        " WIKI_UI_SESSION_TOKEN_FILE=/etc/llm-wiki/ui-session.token"
        " WIKI_UI_OIDC_REDIRECT_URL=http://127.0.0.1:8789/auth/callback"
        " WIKI_UI_OIDC_INSECURE_HTTP=1 WIKI_UI_COOKIE_SECURE=0 > /etc/llm-wiki/ui.env"
    )
    server.succeed("echo vm-secret > /etc/llm-wiki/ui-oidc.secret && echo vm-token > /etc/llm-wiki/ui-session.token")
    server.succeed("systemctl start wikisvc wiki-ui")
    server.wait_until_succeeds("curl -fsS http://127.0.0.1:8789/healthz")
    # The updater asks wikisvc who is calling: it has to be up before the API checks.
    server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")

    server.succeed("mkdir -p /etc/systemd/system/llm-wiki-updater.service.d")
    server.succeed(
        "printf '%s\\n' '[Service]' 'ExecStart=' "
        f"'ExecStart=/opt/llm-wiki/current/bin/llm-wiki-updater serve -repository {registry}"
        " -cosign ${cosign} -stop-timeout 3m -health-timeout 3m -agent-timeout 1m'"
        " > /etc/systemd/system/llm-wiki-updater.service.d/vm.conf"
    )
    server.succeed("systemctl daemon-reload && systemctl start llm-wiki-updater.socket llm-wiki-updater.service")

    with subtest("the socket is open to root and llm-ui only, and the API to human administrators"):
        server.succeed(f"test \"$(stat -c '%U %G %a' {socket})\" = 'root llm-ui 660'")
        server.fail(f"runuser -u llm-wiki -- curl -sf --unix-socket {socket} http://updater/v1/status")
        anonymous = api("GET", "/v1/status")
        assert anonymous["error"]["code"] == "E_UNAUTHORIZED", anonymous
        robot = api("GET", "/v1/status", agent)
        assert robot["error"]["code"] == "E_HUMAN_REQUIRED", robot
        administrator = api("GET", "/v1/status", admin)
        assert administrator["channel"] == "release", administrator

    with subtest("a confirmed release is installed and verified"):
        status = api("POST", "/v1/check", admin)
        assert status["available"]["tag"] == "${release}", status
        assert status["available"]["digest"] == digest_of("${release}"), status
        api("POST", "/v1/apply", admin, {"digest": status["available"]["digest"]})
        server.wait_until_succeeds(
            f"curl -s -H 'Authorization: Bearer {admin}' --unix-socket {socket} http://updater/v1/status"
            " | jq -e '.operation != null and .operation.state != \"running\"'",
            timeout=timedelta(minutes=10),
        )
        operation = api("GET", "/v1/status", admin)["operation"]
        assert operation["state"] == "succeeded", operation
        assert [s["name"] for s in operation["steps"]] == [
            "pull", "verify", "jobs-before", "stop", "archive", "switch", "migrate", "start", "health", "jobs-after", "prune",
        ], operation["steps"]
        assert pinned() == digest_of("${release}")
        server.succeed(f"test \"$(stat -c %a {operation['archive']})\" = 600")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8789/healthz")
        assert server.succeed("llm-wiki-admin wikisvc token list") == tokens_before
        assert api("GET", "/v1/status", admin)["current"]["tag"] == "${release}"

    with subtest("a release that does not run what its tag says is rolled back from the archive"):
        push("${images.c}", "v${next}")
        status = api("POST", "/v1/check", admin)
        assert status["available"]["tag"] == "v${next}", status
        api("POST", "/v1/apply", admin, {"digest": status["available"]["digest"]})
        server.wait_until_succeeds(
            f"curl -s -H 'Authorization: Bearer {admin}' --unix-socket {socket} http://updater/v1/status"
            " | jq -e '.operation != null and .operation.state != \"running\"'",
            timeout=timedelta(minutes=10),
        )
        operation = api("GET", "/v1/status", admin)["operation"]
        assert operation["state"] == "rolled_back", operation
        assert "${next}" in operation["error"], operation["error"]
        assert pinned() == digest_of("${release}")
        server.succeed("ls -d /var/lib/llm-wiki/wiki.failed-* /etc/llm-wiki.failed-*")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8787/api/v1/health")
        server.wait_until_succeeds("curl -fsS http://127.0.0.1:8789/healthz")
        assert server.succeed("llm-wiki-admin wikisvc token list") == tokens_before

    with subtest("each signature check named the exact tag and image"):
        asked = server.succeed("cat /var/lib/llm-wiki-updater/cosign.log")
        for tag in ("${release}", "v${next}"):
            assert f"release.yml@refs/tags/{tag}" in asked, asked
  '';
}
