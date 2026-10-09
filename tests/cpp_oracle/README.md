# The C++ oracle

`driver.cpp` is a small program that reads one `.seq` file with `ExternalSequence::load`, the
reader of the Pulseq interpreter on the scanner, and then decodes each block with `decodeBlock`.
Nix builds it as `pulseq-cpp-oracle` (`flake.nix`), and `tests/test_cpp_oracle.py` runs it. The
program exits 0 when the file loads and each block decodes, 1 when it does not (the messages of
the reader are on stderr), and 70 when the reader crashes.

`ExternalSequence.h`, `ExternalSequence.cpp`, `md5.h` and `md5.cpp` are not in this folder. The
derivation takes the folder `src/` of [pulseq/pulseq](https://github.com/pulseq/pulseq) at commit
`c7469123c2f381f065986e6cc3a7d09730ed16ef`. That project is under the MIT license; its notice is
in `LICENSE.pulseq` in this folder, which is a copy of the `LICENSE` file of that commit.
