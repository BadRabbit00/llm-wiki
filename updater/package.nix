# llm-wiki-updater for the host bundle. skopeo and cosign come from the pinned
# nixpkgs on its PATH; podman, systemctl and tar are the distribution's.
{ pkgs, version }:
pkgs.buildGoModule {
  pname = "llm-wiki-updater";
  inherit version;
  src = ./.;
  vendorHash = null; # standard library only
  env.CGO_ENABLED = "0";
  nativeBuildInputs = [ pkgs.makeWrapper ];
  postInstall = ''
    mv "$out/bin/updater" "$out/bin/llm-wiki-updater"
    wrapProgram "$out/bin/llm-wiki-updater" \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.skopeo pkgs.cosign ]}
  '';
  meta.mainProgram = "llm-wiki-updater";
}
