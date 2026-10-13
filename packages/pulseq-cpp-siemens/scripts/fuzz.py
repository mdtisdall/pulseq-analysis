"""Fuzz the checks of undefined behaviour against the sanitized C++ oracle (tests/seqfuzz.py).

Run it in the Nix devShell, which has `pulseq-cpp-oracle-sanitized`, from the repository root,
with the package installed in packages/pulseq-cpp-siemens/.venv:

    nix develop --command packages/pulseq-cpp-siemens/.venv/bin/python \\
        packages/pulseq-cpp-siemens/scripts/fuzz.py --seed 1 --count 200000

It writes each failing file and its result to --keep, prints a summary, and exits with 1 when a
file fails. A failure is reproduced with --seed S --start INDEX --count 1.
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import seqfuzz


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--jobs", type=int, default=None, help="default: the number of CPUs")
    parser.add_argument("--keep", type=Path, default=Path("fuzz-failures"))
    parser.add_argument("--chunk", type=int, default=5000, help="files between two summaries")
    args = parser.parse_args()
    oracle = shutil.which("pulseq-cpp-oracle-sanitized")
    if oracle is None:
        sys.exit("pulseq-cpp-oracle-sanitized is not on the PATH: run in the Nix devShell")
    began = time.monotonic()
    results = []
    for start in range(args.start, args.start + args.count, args.chunk):
        count = min(args.chunk, args.start + args.count - start)
        report = seqfuzz.run(args.seed, start, count, oracle, jobs=args.jobs, keep=args.keep)
        results += report.results
        total = seqfuzz.Report(results)
        print(
            f"{start + count - args.start} files in {time.monotonic() - began:.0f} s, "
            f"{len(total.failures)} failures",
            flush=True,
        )
    total = seqfuzz.Report(results)
    print(total.summary())
    print("codes confirmed by the oracle:", dict(sorted(total.confirmed_codes().items())))
    for failure in total.failures:
        print(
            f"FAIL seed {args.seed} index {failure.index} {failure.mutations} "
            f"[{failure.known or 'not known'}]: {failure.failure}"
        )
    sys.exit(1 if total.failures else 0)


if __name__ == "__main__":
    main()
