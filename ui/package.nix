{ pkgs }:
let
  frontend = pkgs.buildNpmPackage {
    pname = "wiki-ui-assets";
    version = "0.3.0";
    src = ./.;
    npmDepsHash = "sha256-5rw11pN6pFUzLh2ruVT/niFbGEpc1LoiB5ajQNHd9G4=";
    preBuild = "npm run format:check";
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -r dist $out/
      runHook postInstall
    '';
  };
in pkgs.buildGoModule {
  pname = "wiki-ui";
  version = "0.3.0";
  src = ./.;
  vendorHash = null;
  env.CGO_ENABLED = "0";
  preBuild = ''
    cp -r ${frontend}/dist/. dist/
  '';
  postInstall = ''
    mv $out/bin/ui $out/bin/wiki-ui
  '';
  meta.mainProgram = "wiki-ui";
}
