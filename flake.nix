{
  description = "pulseq-analysis: development shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      # Attributes shared by every devShell for this project.
      mkDevShell =
        pkgs: packages:
        pkgs.mkShellNoCC (
          {
            inherit packages;
            # uv builds the venv on the Nix python and never downloads one.
            UV_PYTHON = "${pkgs.python312}/bin/python3";
            UV_PYTHON_DOWNLOADS = "never";
          }
          // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
            # PyPI manylinux wheels (numpy) load libstdc++ and zlib, which the
            # Nix python does not have on its library path.
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ];
          }
        );

      # The reader of the Pulseq interpreter on the scanner, ExternalSequence of pulseq/pulseq
      # (MIT), with the small driver in tests/cpp_oracle. tests/test_cpp_oracle.py compares it
      # with the parser of this package.
      pulseq-cpp-oracle =
        pkgs:
        pkgs.stdenv.mkDerivation {
          pname = "pulseq-cpp-oracle";
          version = "c7469123";
          src = pkgs.fetchFromGitHub {
            owner = "pulseq";
            repo = "pulseq";
            rev = "c7469123c2f381f065986e6cc3a7d09730ed16ef";
            hash = "sha256-Q9XjlghUUVDb9ZLs6UQoh6Q/n+KhrrVlyhcIsVzuuig=";
          };
          driver = ./tests/cpp_oracle/driver.cpp;
          dontConfigure = true;
          buildPhase = ''
            runHook preBuild
            $CXX -std=c++11 -O2 -I src -o pulseq-cpp-oracle \
              $driver src/ExternalSequence.cpp src/md5.cpp
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            install -D pulseq-cpp-oracle $out/bin/pulseq-cpp-oracle
            runHook postInstall
          '';
          meta.mainProgram = "pulseq-cpp-oracle";
        };
    in
    {
      packages = forAllSystems (pkgs: {
        pulseq-cpp-oracle = pulseq-cpp-oracle pkgs;
      });
      devShells = forAllSystems (pkgs: {
        default = mkDevShell pkgs [
          pkgs.python312
          pkgs.uv
          pkgs.gh
          pkgs.git
          pkgs.jq
          pkgs.shellcheck
          (pulseq-cpp-oracle pkgs)
        ];
        # A smaller shell for CI: only the tools that scripts/check needs.
        ci = mkDevShell pkgs [
          pkgs.python312
          pkgs.uv
          pkgs.shellcheck
          (pulseq-cpp-oracle pkgs)
        ];
      });
    };
}
