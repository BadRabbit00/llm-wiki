# Host side of a deployment: units, configuration templates and the scripts that
# install, run, back up and maintain the services. The services themselves come from
# the release image (deploy/image.nix), so this closure builds in seconds and holds
# no application code.
{ pkgs, version }:
pkgs.runCommand "llm-wiki-deployment-${version}" {
  nativeBuildInputs = [ pkgs.shellcheck ];
} ''
  mkdir -p "$out/bin" "$out/share/llm-wiki"
  cp -r ${./linux} "$out/share/llm-wiki/linux"
  cp -r ${./systemd} "$out/share/llm-wiki/systemd"
  render() {
    substitute "$1" "$out/bin/$2" \
      --replace-fail '#!/usr/bin/env bash' '#!${pkgs.bash}/bin/bash' \
      --replace-warn '@tools@' '${pkgs.lib.makeBinPath [ pkgs.coreutils pkgs.gnused ]}' \
      --replace-warn '@nix@' '${pkgs.nix}' \
      --replace-warn '@bundle@' "$out"
    chmod +x "$out/bin/$2"
    shellcheck "$out/bin/$2"
  }
  render ${./install.sh} llm-wiki-install
  render ${./admin.sh} llm-wiki-admin
  render ${./run.sh} llm-wiki-run
  render ${./model.sh} llm-wiki-model
  render ${./backup.sh} llm-wiki-backup
''
