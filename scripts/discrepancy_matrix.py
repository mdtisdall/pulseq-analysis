"""The acceptance matrix that the entries of `docs/discrepancies.md` cite: each `.seq` file of
`tests/seqfiles` (the fixtures and `oracle/`) through the two interpreters of the package and the
C++ reader, as a Markdown table on stdout. The document does not keep the table (its appendix);
this script may suit a separate report on the discrepancies better than this package.

- `spec`: `seqfile.read_seqfile(FILE)` with its default interpreter. "accept", or the rule IDs of
  the violations, or "not supported" for a version outside 1.4.0 to 1.5.x.
- `cpp-siemens`: `seqfile.read_seqfile(FILE, "cpp-siemens")`, the interpreter of the plugin
  `pulseq-cpp-siemens`. The same cells as `spec`.
- C++ reader: `pulseq-cpp-oracle FILE`, the reader `ExternalSequence` of pulseq/pulseq
  (`tests/cpp_oracle`). "accept" (exit 0), "reject" (exit 1), "crash" and the exit status (70 is
  a signal), or "no end in 10 s".

Run it in the devShell, where the oracle is on the PATH:

    nix develop --command uv run python scripts/discrepancy_matrix.py

`--cpp` gives the path of the oracle if it is not on the PATH. A reader that cannot run (the
oracle is missing, or the plugin `pulseq-cpp-siemens` is not installed) gives "not run" in its
column. The time of the run goes to stderr.
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pulseq_analysis.seqfile import NotSupported, SeqFileError, interpreter_names, read_seqfile

ROOT = Path(__file__).resolve().parent.parent
SEQFILES = ROOT / "tests" / "seqfiles"
TIMEOUT = 10  # s for one file in the C++ oracle


def interpreter_verdict(path: Path, interpreter: str) -> str:
    """The verdict of `read_seqfile` through `interpreter`, or "not run" when no installed
    interpreter has the name."""
    if interpreter not in interpreter_names():
        return "not run"
    try:
        read_seqfile(path, interpreter)
    except NotSupported:
        return "not supported"
    except SeqFileError as error:
        return " ".join(f"`{r}`" for r in sorted({v.rule for v in error.violations}))
    return "accept"


def cpp_verdict(oracle: str | None, path: Path) -> str:
    if oracle is None:
        return "not run"
    try:
        result = subprocess.run(
            [oracle, str(path)], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return f"no end in {TIMEOUT} s"
    return {0: "accept", 1: "reject"}.get(result.returncode, f"crash ({result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cpp", default=shutil.which("pulseq-cpp-oracle"))
    args = parser.parse_args()

    start = time.perf_counter()
    paths = sorted(SEQFILES.rglob("*.seq"), key=lambda p: p.relative_to(SEQFILES).as_posix())
    print("| File | spec | cpp-siemens | C++ reader |")
    print("|---|---|---|---|")
    for path in paths:
        name = path.relative_to(SEQFILES).as_posix()
        cells = (
            interpreter_verdict(path, "spec"),
            interpreter_verdict(path, "cpp-siemens"),
            cpp_verdict(args.cpp, path),
        )
        print(f"| `{name}` | " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    print(f"{len(paths)} files in {time.perf_counter() - start:.0f} s.", file=sys.stderr)


if __name__ == "__main__":
    main()
