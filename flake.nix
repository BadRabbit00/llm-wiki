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
            python-multipart typer httpx pypdf python-docx mcp
          ];
          dev = with py.pkgs; [ pytest pytest-cov hypothesis mypy ];
        in { inherit pkgs py runtime dev; };
    in {
      packages = eachSystem (system:
        let e = env system; in {
          default = e.py.pkgs.buildPythonApplication {
            pname = "wikisvc";
            version = "0.2.0";
            pyproject = true;
            src = ./.;
            build-system = [ e.py.pkgs.hatchling ];
            dependencies = e.runtime;
            makeWrapperArgs = [ "--prefix PATH : ${e.pkgs.lib.makeBinPath [ e.pkgs.git ]}" ];
            nativeCheckInputs = e.dev ++ [ e.pkgs.git e.pkgs.ruff e.py.pkgs.pytestCheckHook ];
            pythonImportsCheck = [ "wikisvc" "wikiagent" "pypdf" "docx" ];
            pytestFlags = [ "--cov" "--cov-report=term-missing" ];
            preCheck = ''
              ruff check .
              ruff format --check .
              mypy src
            '';
          };
          wikisvc = self.packages.${system}.default;
          wikiagent = self.packages.${system}.default;
        } // e.pkgs.lib.optionalAttrs e.pkgs.stdenv.hostPlatform.isLinux {
          deployment = import ./deploy/package.nix {
            pkgs = e.pkgs;
            app = self.packages.${system}.default;
          };
        });
      apps = eachSystem (system: {
        wikiagent = {
          type = "app";
          program = "${self.packages.${system}.wikiagent}/bin/wikiagent";
          meta.description = "Wiki policy planner, chat, book jobs and healer";
        };
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/wikisvc";
          meta.description = "Git-backed wiki API and MCP service";
        };
      });
      checks = eachSystem (system: {
        default = self.packages.${system}.default;
      } // nixpkgs.lib.optionalAttrs nixpkgs.legacyPackages.${system}.stdenv.hostPlatform.isLinux {
        deployment = self.packages.${system}.deployment;
      });
      devShells = eachSystem (system:
        let e = env system; in {
          default = e.pkgs.mkShell {
            packages = [
              (e.py.withPackages (_: e.runtime ++ e.dev))
              (e.pkgs.writeShellScriptBin "wikisvc" ''exec python -m wikisvc.cli "$@"'')
              (e.pkgs.writeShellScriptBin "wikiagent" ''exec python -m wikiagent.cli "$@"'')
              e.pkgs.git e.pkgs.sqlite e.pkgs.ruff e.pkgs.just
            ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
              export WIKI_ROOT="''${WIKI_ROOT:-$(realpath -m "$PWD/../wiki")}"
              export STATE_DIR="''${STATE_DIR:-$PWD/.dev/state}"
              export INDEX_DIR="''${INDEX_DIR:-$PWD/.dev/index}"
              export WIKIAGENT_STATE_DIR="''${WIKIAGENT_STATE_DIR:-$PWD/.dev/agent}"
              mkdir -p "$STATE_DIR" "$INDEX_DIR"
            '';
          };
        });
    };
}
