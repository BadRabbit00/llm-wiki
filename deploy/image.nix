# One image for wikisvc, wikiagent and wiki-ui: a release is a single digest, so the
# three services can never run different versions against the same data.
# Distroless: the service closures, git for `llm-wiki-admin git`, CA certificates for
# OIDC and HTTPS models, and passwd/group entries. No shell, no package manager.
{ pkgs, app, ui, revision }:
pkgs.dockerTools.buildLayeredImage {
  name = "ghcr.io/badrabbit00/llm-wiki";
  tag = revision;
  contents = [ app ui pkgs.git pkgs.cacert pkgs.dockerTools.fakeNss ];
  extraCommands = "mkdir -m 1777 tmp";
  config = {
    # The server overrides this with the uid that owns /var/lib/llm-wiki.
    User = "65534:65534";
    WorkingDir = "/var/lib/llm-wiki";
    Env = [
      "PYTHONUNBUFFERED=1"
      "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    ];
    Labels = {
      "org.opencontainers.image.source" = "https://github.com/BadRabbit00/llm-wiki";
      "org.opencontainers.image.revision" = revision;
      "org.opencontainers.image.version" = app.version;
    };
  };
}
