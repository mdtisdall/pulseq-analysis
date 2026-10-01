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
    in
    {
      devShells = forAllSystems (pkgs: {
        default = mkDevShell pkgs [
          pkgs.python312
          pkgs.uv
          pkgs.gh
          pkgs.git
          pkgs.jq
          pkgs.shellcheck
        ];
        # A smaller shell for CI: only the tools that scripts/check needs.
        ci = mkDevShell pkgs [
          pkgs.python312
          pkgs.uv
          pkgs.shellcheck
        ];
      });
    };
}
