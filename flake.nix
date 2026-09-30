{
  description = "wikisvc: git-backed wiki API and MCP";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      env = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          py = pkgs.python312.override {
            packageOverrides = final: prev:
              let
                snapshot = prev.inline-snapshot.overridePythonAttrs (old: {
                  disabledTestPaths = (old.disabledTestPaths or [ ]) ++ [ "tests/test_docs.py" ];
                });
              in {
                fastapi = prev.fastapi.override { inline-snapshot = snapshot; };
                mcp = prev.mcp.override { inline-snapshot = snapshot; };
                rich-toolkit = prev.rich-toolkit.override { inline-snapshot = snapshot; };
              };
          };
          runtime = with py.pkgs; [
            fastapi uvicorn pydantic pydantic-settings ruamel-yaml pystemmer
            python-multipart typer httpx mcp
          ];
          dev = with py.pkgs; [ pytest pytest-cov hypothesis mypy ];
        in { inherit pkgs py runtime dev; };
    in {
      packages = eachSystem (system:
        let e = env system; in {
          default = e.py.pkgs.buildPythonApplication {
            pname = "wikisvc";
            version = "0.1.0";
            pyproject = true;
            src = ./.;
            build-system = [ e.py.pkgs.hatchling ];
            dependencies = e.runtime;
            makeWrapperArgs = [ "--prefix PATH : ${e.pkgs.lib.makeBinPath [ e.pkgs.git ]}" ];
            nativeCheckInputs = e.dev ++ [ e.pkgs.git e.pkgs.ruff e.py.pkgs.pytestCheckHook ];
            pythonImportsCheck = [ "wikisvc" ];
            pytestFlags = [ "--cov=wikisvc.domain" "--cov=wikisvc.index" "--cov-report=term-missing" ];
            preCheck = ''
              ruff check .
              ruff format --check .
              mypy src
            '';
          };
        });
      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/wikisvc";
          meta.description = "Git-backed wiki API and MCP service";
        };
      });
      checks = eachSystem (system: { default = self.packages.${system}.default; });
      devShells = eachSystem (system:
        let e = env system; in {
          default = e.pkgs.mkShell {
            packages = [
              (e.py.withPackages (_: e.runtime ++ e.dev))
              (e.pkgs.writeShellScriptBin "wikisvc" ''exec python -m wikisvc.cli "$@"'')
              e.pkgs.git e.pkgs.sqlite e.pkgs.ruff e.pkgs.just
            ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
              export WIKI_ROOT="''${WIKI_ROOT:-$(realpath -m "$PWD/../wiki")}"
              export STATE_DIR="''${STATE_DIR:-$PWD/.dev/state}"
              export INDEX_DIR="''${INDEX_DIR:-$PWD/.dev/index}"
              mkdir -p "$STATE_DIR" "$INDEX_DIR"
            '';
          };
        });
    };
}
