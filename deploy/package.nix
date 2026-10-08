{ pkgs, app, ui }:
pkgs.runCommand "llm-wiki-deployment-${app.version}" {
  nativeBuildInputs = [ pkgs.shellcheck ];
} ''
  mkdir -p "$out/bin" "$out/share/llm-wiki"
  cp -r ${./linux} "$out/share/llm-wiki/linux"
  cp -r ${./systemd} "$out/share/llm-wiki/systemd"
  for command in wikisvc wikiagent; do
    ln -s ${app}/bin/$command "$out/bin/$command"
  done
  ln -s ${ui}/bin/wiki-ui "$out/bin/wiki-ui"
  render() {
    substitute "$1" "$out/bin/$2" \
      --replace-fail '#!/usr/bin/env bash' '#!${pkgs.bash}/bin/bash' \
      --replace-warn '@tools@' '${pkgs.lib.makeBinPath [ pkgs.coreutils ]}' \
      --replace-warn '@app@' '${app}' \
      --replace-warn '@git@' '${pkgs.git}' \
      --replace-warn '@nix@' '${pkgs.nix}' \
      --replace-warn '@bundle@' "$out"
    chmod +x "$out/bin/$2"
    shellcheck "$out/bin/$2"
  }
  render ${./install.sh} llm-wiki-install
  render ${./admin.sh} llm-wiki-admin
  render ${./model.sh} llm-wiki-model
  render ${./backup.sh} llm-wiki-backup
  cat > "$out/bin/llm-wiki-check" <<EOF
  #!${pkgs.bash}/bin/bash
  exec ${app}/bin/wikiagent check "\$@"
  EOF
  chmod +x "$out/bin/llm-wiki-check"
''
