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
            packages = packages ++ pulseq-cpp-siemens-build pkgs;
            # uv builds the venv on the Nix python and never downloads one.
            UV_PYTHON = "${pkgs.python312}/bin/python3";
            UV_PYTHON_DOWNLOADS = "never";
            # packages/pulseq-cpp-siemens compiles the C++ reader from this checkout of
            # pulseq/pulseq (its CMakeLists.txt checks the SHA-256 of each file), not from the
            # network.
            PULSEQ_SOURCE_DIR = "${pulseq-source pkgs}";
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

      # The tools that build packages/pulseq-cpp-siemens in every devShell: scripts/check builds
      # and tests it. scikit-build-core and nanobind come from PyPI, at the exact versions of
      # its pyproject.toml.
      pulseq-cpp-siemens-build = pkgs: [
        pkgs.cmake
        pkgs.ninja
        pkgs.stdenv.cc
      ];

      # The source of pulseq/pulseq (MIT) at one commit, for both oracles: the C++ reader in
      # src/ and MATLAB Pulseq in matlab/. Neither is copied into this repository.
      pulseq-source =
        pkgs:
        pkgs.fetchFromGitHub {
          owner = "pulseq";
          repo = "pulseq";
          rev = "c7469123c2f381f065986e6cc3a7d09730ed16ef";
          hash = "sha256-Q9XjlghUUVDb9ZLs6UQoh6Q/n+KhrrVlyhcIsVzuuig=";
        };

      # The SAFE PNS model of Szczepankiewicz and Witzel, filip-szczepankiewicz/safe_pns_prediction
      # (BSD-3-Clause), at one commit, for the SAFE oracle: the package that calcPNS of MATLAB
      # Pulseq calls, and of which pypulseq's translation is the source of the port in
      # src/pulseq_analysis/analyses/safe.py. It is not copied into this repository.
      safe-source =
        pkgs:
        pkgs.fetchFromGitHub {
          owner = "filip-szczepankiewicz";
          repo = "safe_pns_prediction";
          rev = "152ab67c086170c40c1988ebba9002e018a0652c";
          hash = "sha256-ROHkx9zMabFr47K/NqY6t0jTx/EKqk4GMxMLVyjmfRg=";
        };

      # The reader of the Pulseq interpreter on the scanner, ExternalSequence of pulseq/pulseq
      # (MIT), with the small driver in tests/cpp_oracle, compiled with `flags` by the compiler of
      # `stdenv`. `extra` adds attributes to the derivation.
      #
      # Each build has the char and the arithmetic of the reader's x86_64 build on the scanner,
      # whatever the system:
      # - -fsigned-char: ExternalSequence::getline compares a char with EOF. With an unsigned
      #   char (gcc and clang on Linux aarch64) the comparison is never true, and the reader
      #   does not end on any file.
      # - -ffp-contract=off: the x86_64 build has no FMA instructions, so it never fuses a
      #   multiply and an add. On arm64 the compiler fuses them by default, and gradientsAt
      #   then rounds some values differently in the last bit.
      cpp-oracle =
        pkgs:
        {
          name,
          flags,
          stdenv ? pkgs.stdenv,
          extra ? { },
        }:
        stdenv.mkDerivation (
          {
            pname = name;
            version = "c7469123";
            src = pulseq-source pkgs;
            driver = ./tests/cpp_oracle/driver.cpp;
            dontConfigure = true;
            buildPhase = ''
              runHook preBuild
              $CXX -std=c++11 -fsigned-char -ffp-contract=off ${flags} -I src -o ${name} \
                $driver src/ExternalSequence.cpp src/md5.cpp
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -D ${name} $out/bin/${name}
              runHook postInstall
            '';
            meta.mainProgram = name;
          }
          // extra
        );

      # tests/test_cpp_oracle.py compares this build with the parser of this package.
      pulseq-cpp-oracle =
        pkgs:
        cpp-oracle pkgs {
          name = "pulseq-cpp-oracle";
          flags = "-O2";
        };

      # The same reader and driver with AddressSanitizer, UndefinedBehaviorSanitizer and the
      # assertions of the C++ standard library (libstdc++ on Linux, libc++ on macOS). The exit
      # status 3 says that one of them fired: the reader has undefined behaviour on the file,
      # whatever an ordinary build does with it (docs/plans/parser-redesign.md, section 5.3).
      # tests/test_cpp_oracle_sanitized.py runs it.
      pulseq-cpp-oracle-sanitized =
        pkgs:
        cpp-oracle pkgs {
          name = "pulseq-cpp-oracle-sanitized";
          # Clang on each system, so that macOS and Linux have the same sanitizers. Not the
          # default LLVM 21: its AddressSanitizer hangs at the start of each process on macOS 26
          # (a recursion of malloc in the start of the runtime). LLVM 22 starts.
          stdenv = pkgs.llvmPackages_22.stdenv;
          flags = pkgs.lib.concatStringsSep " " [
            "-O1"
            "-fno-omit-frame-pointer"
            "-fsanitize=address,undefined"
            "-fno-sanitize-recover=all"
            "-D_GLIBCXX_ASSERTIONS"
            # libstdc++ marks the capacity of a vector past its size for AddressSanitizer only
            # with this macro (libc++ always does): a write there, as decodeArbGradInBlock makes
            # into the buffer that it reuses, is then a report of container-overflow on Linux too.
            "-D_GLIBCXX_SANITIZE_VECTOR"
            "-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG"
            "-DPULSEQ_CPP_ORACLE_SANITIZED"
          ];
          extra = {
            # _FORTIFY_SOURCE of the Nix wrapper does not work with AddressSanitizer.
            hardeningDisable = [ "fortify" ];
          };
        };

      # MATLAB Pulseq of the same commit, run under GNU Octave by tests/matlab_oracle/dump.m.
      # `pulseq-matlab-oracle OUT_DIR FILE.seq...` writes OUT_DIR/<stem>.json for each file, in
      # one Octave process. Only the default devShell has it: the closure of Octave is about
      # 2.5 GiB.
      pulseq-matlab-oracle =
        pkgs:
        pkgs.writeShellApplication {
          name = "pulseq-matlab-oracle";
          runtimeInputs = [
            pkgs.coreutils
            pkgs.octave
          ];
          text = ''
            if [ "$#" -lt 2 ]; then
              echo "usage: pulseq-matlab-oracle OUT_DIR FILE.seq..." >&2
              exit 2
            fi
            out_dir=$1
            shift
            for f in "$@"; do
              case $f in
                *.seq) ;;
                *)
                  echo "pulseq-matlab-oracle: '$f' does not end in .seq" >&2
                  exit 2
                  ;;
              esac
            done
            same=$(for f in "$@"; do basename "$f" .seq; done | sort | uniq -d)
            if [ -n "$same" ]; then
              echo "pulseq-matlab-oracle: more than one file has the name '$same'" >&2
              exit 2
            fi
            mkdir -p "$out_dir"
            PULSEQ_ORACLE_OUT=$out_dir PULSEQ_ORACLE_FILES=$(printf '%s\n' "$@") \
              exec octave-cli --no-gui --norc --eval '
                addpath("${pulseq-source pkgs}/matlab");
                addpath("${
                  pkgs.lib.fileset.toSource {
                    root = ./tests/matlab_oracle;
                    fileset = ./tests/matlab_oracle/dump.m;
                  }
                }");
                warning("off", "all");
                dump(strsplit(getenv("PULSEQ_ORACLE_FILES"), "\n"), getenv("PULSEQ_ORACLE_OUT"));
              '
          '';
        };

      # The original SAFE package of `safe-source`, with MATLAB Pulseq for its calcPNS, run under
      # GNU Octave by tests/safe_oracle/dump_safe.m, in one Octave process:
      # - `pulseq-safe-oracle filter REQUEST.json OUT_DIR`: safe_gwf_to_pns and safe_hw_check of
      #   the cases of REQUEST.json;
      # - `pulseq-safe-oracle calcpns FILE.asc OUT_DIR FILE.seq...`: calcPNS of each file with
      #   the hardware of FILE.asc.
      # tests/safe_oracle/README.md gives the files. Only the default devShell has it, as
      # pulseq-matlab-oracle.
      pulseq-safe-oracle =
        pkgs:
        pkgs.writeShellApplication {
          name = "pulseq-safe-oracle";
          runtimeInputs = [
            pkgs.coreutils
            pkgs.octave
          ];
          text = ''
            usage() {
              echo "usage: pulseq-safe-oracle filter REQUEST.json OUT_DIR" >&2
              echo "       pulseq-safe-oracle calcpns FILE.asc OUT_DIR FILE.seq..." >&2
              exit 2
            }
            mode=''${1:-}
            case $mode in
              filter) [ "$#" -eq 3 ] || usage ;;
              calcpns)
                [ "$#" -ge 4 ] || usage
                for f in "''${@:4}"; do
                  case $f in
                    *.seq) ;;
                    *)
                      echo "pulseq-safe-oracle: '$f' does not end in .seq" >&2
                      exit 2
                      ;;
                  esac
                done
                same=$(for f in "''${@:4}"; do basename "$f" .seq; done | sort | uniq -d)
                if [ -n "$same" ]; then
                  echo "pulseq-safe-oracle: more than one file has the name '$same'" >&2
                  exit 2
                fi
                ;;
              *) usage ;;
            esac
            shift
            # OUT_DIR is the second argument of both modes.
            out_dir=$2
            mkdir -p "$out_dir"
            SAFE_ORACLE_MODE=$mode SAFE_ORACLE_ARGS=$(printf '%s\n' "$@") \
              exec octave-cli --no-gui --norc --eval '
                addpath("${pulseq-source pkgs}/matlab");
                addpath("${safe-source pkgs}");
                addpath("${
                  pkgs.lib.fileset.toSource {
                    root = ./tests/safe_oracle;
                    fileset = ./tests/safe_oracle/dump_safe.m;
                  }
                }");
                warning("off", "all");
                dump_safe(getenv("SAFE_ORACLE_MODE"), strsplit(getenv("SAFE_ORACLE_ARGS"), "\n"));
              '
          '';
        };
    in
    {
      packages = forAllSystems (pkgs: {
        pulseq-cpp-oracle = pulseq-cpp-oracle pkgs;
        pulseq-cpp-oracle-sanitized = pulseq-cpp-oracle-sanitized pkgs;
        pulseq-matlab-oracle = pulseq-matlab-oracle pkgs;
        pulseq-safe-oracle = pulseq-safe-oracle pkgs;
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
          (pulseq-cpp-oracle-sanitized pkgs)
          (pulseq-matlab-oracle pkgs)
          (pulseq-safe-oracle pkgs)
        ];
        # A smaller shell for CI: only the tools that scripts/check needs.
        ci = mkDevShell pkgs [
          pkgs.python312
          pkgs.uv
          pkgs.shellcheck
          (pulseq-cpp-oracle pkgs)
          (pulseq-cpp-oracle-sanitized pkgs)
        ];
      });
    };
}
