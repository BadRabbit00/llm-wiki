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
            # The UI is built independently; frontend edits do not rebuild Python. Nor do
            # Nix expressions (image, host bundle, VM test) or CI workflows, which no
            # Python test reads; flake.nix stays because a test checks its version.
            src = e.pkgs.lib.cleanSourceWith {
              src = ./.;
              filter = path: _type:
                let name = builtins.baseNameOf path; in
                name != "ui" && name != ".github"
                && (name == "flake.nix" || !e.pkgs.lib.hasSuffix ".nix" name);
            };
            build-system = [ e.py.pkgs.hatchling ];
            dependencies = e.runtime;
            makeWrapperArgs = [ "--prefix PATH : ${e.pkgs.lib.makeBinPath [ e.pkgs.git ]}" ];
            nativeCheckInputs = e.dev ++ [ e.pkgs.git e.pkgs.ruff e.py.pkgs.pytestCheckHook ];
            pythonImportsCheck = [ "wikisvc" "wikiagent" "pypdf" "docx" ];
            pytestFlags = [ "--cov" "--cov-report=term-missing" ];
            # Coverage's patch = ["subprocess"] starts children through its a1_coverage.pth, and
            # Python runs .pth files only in site directories. Here dependencies arrive on
            # PYTHONPATH, so the parser worker went unmeasured. For the tests alone, a
            # sitecustomize on PYTHONPATH does what that .pth does; it shadows the nixpkgs one,
            # which acts only on NIX_PYTHON* variables the build does not set.
            preCheck = ''
              ruff check .
              ruff format --check .
              mypy src
              mkdir -p "$TMPDIR/coverage-startup"
              cat > "$TMPDIR/coverage-startup/sitecustomize.py" <<'EOF'
              import coverage

              coverage.process_startup()
              EOF
              pythonPathBeforeCheck="$PYTHONPATH"
              export PYTHONPATH="$TMPDIR/coverage-startup:$PYTHONPATH"
            '';
            postCheck = ''
              export PYTHONPATH="$pythonPathBeforeCheck"
            '';
          };
          # OIDC stays in Go; its pinned modules and vendor hash live with the UI derivation.
          ui = import ./ui/package.nix { pkgs = e.pkgs; };
          wikisvc = self.packages.${system}.default;
          wikiagent = self.packages.${system}.default;
        } // e.pkgs.lib.optionalAttrs e.pkgs.stdenv.hostPlatform.isLinux {
          updater = import ./updater/package.nix {
            pkgs = e.pkgs;
            inherit (self.packages.${system}.default) version;
          };
          deployment = import ./deploy/package.nix {
            pkgs = e.pkgs;
            inherit (self.packages.${system}.default) version;
            inherit (self.packages.${system}) updater;
          };
          image = import ./deploy/image.nix {
            pkgs = e.pkgs;
            app = self.packages.${system}.default;
            ui = self.packages.${system}.ui;
            revision = self.shortRev or self.dirtyShortRev or "unknown";
          };
        });
      apps = eachSystem (system: {
        ui = {
          type = "app";
          program = "${self.packages.${system}.ui}/bin/wiki-ui";
          meta.description = "Wiki web workspace with embedded assets and API proxy";
        };
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
        ui = self.packages.${system}.ui;
        default = self.packages.${system}.default;
      } // nixpkgs.lib.optionalAttrs nixpkgs.legacyPackages.${system}.stdenv.hostPlatform.isLinux {
        deployment = self.packages.${system}.deployment;
        # A NixOS VM with podman installs the bundle and runs the image through the units.
        deployment-vm = import ./deploy/vm-test.nix {
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (self.packages.${system}) deployment image;
        };
        # The updater installs a release and rolls back one that does not run its tag.
        updater-vm = import ./deploy/vm-update-test.nix {
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (self.packages.${system}) deployment;
          image = revision: import ./deploy/image.nix {
            pkgs = nixpkgs.legacyPackages.${system};
            app = self.packages.${system}.default;
            ui = self.packages.${system}.ui;
            inherit revision;
          };
        };
      });
      devShells = eachSystem (system:
        let e = env system; in {
          default = e.pkgs.mkShell {
            packages = [
              (e.py.withPackages (_: e.runtime ++ e.dev))
              (e.pkgs.writeShellScriptBin "wikisvc" ''exec python -m wikisvc.cli "$@"'')
              (e.pkgs.writeShellScriptBin "wikiagent" ''exec python -m wikiagent.cli "$@"'')
              e.pkgs.git e.pkgs.sqlite e.pkgs.ruff e.pkgs.just e.pkgs.go e.pkgs.nodejs
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
