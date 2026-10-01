"""Time of `pns_levels` on a large synthetic sequence (plan decision D3).

Builds `build_repeating` of `tests/scale_sequences.py` with about 10^6 blocks, and times
`pns_levels.pns_levels(seq)` with pypulseq's example hardware, `--repeat` times in this
process. The result is the minimum time. With `--thresholds T [T ...]` the call is
`pns_levels(seq, thresholds=(T, ...))`, and without it the default of `pns_levels` is
used. Run it in the devShell:

    nix develop --command uv run python scripts/time_pns_levels.py [--blocks N] \
[--repeat R] [--thresholds T [T ...]] [--json OUT]

The build of the sequence is timed and printed, but it is not part of the result.
`sequence_index` keeps its result for the sequence object, so the first run also builds
the block table and the later runs do not. The minimum is thus the time of the PNS model,
the sampling and the bins, without the block table.
"""

import argparse
import json
import platform
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))


def git_commit() -> str:
    """The commit of the repository, with "-dirty" when the work tree has changes."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
        ).stdout.strip()

    commit = git("rev-parse", "HEAD") or "unknown"
    return commit + ("-dirty" if git("status", "--porcelain", "--untracked-files=no") else "")


def machine() -> dict:
    cpu = platform.processor()
    if sys.platform == "darwin":
        brand = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        cpu = brand or cpu
    return {
        "platform": platform.platform(),
        "cpu": cpu,
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "pypulseq": version("pypulseq"),
        "pulseq_analysis": version("pulseq-analysis"),
        "commit": git_commit(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--blocks", type=int, default=1_000_000, help="blocks of the sequence")
    parser.add_argument("--repeat", type=int, default=3, help="number of timed runs")
    parser.add_argument(
        "--thresholds",
        type=float,
        nargs="+",
        metavar="T",
        help="the thresholds of pns_levels (default: the default of pns_levels)",
    )
    parser.add_argument("--json", type=Path, metavar="OUT", help="write the results as JSON")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    from scale_sequences import TR_BLOCKS, build_repeating

    from pulseq_analysis.pns_levels import pns_levels

    n_trs = args.blocks // TR_BLOCKS
    blocks = n_trs * TR_BLOCKS
    print(f"building {blocks} blocks", file=sys.stderr)
    start = time.perf_counter()
    seq = build_repeating(n_trs)
    build_s = time.perf_counter() - start
    print(f"build {build_s:.1f} s (not part of the result)")

    seconds = []
    for i in range(args.repeat):
        print(f"run {i + 1} of {args.repeat}", file=sys.stderr)
        start = time.perf_counter()
        if args.thresholds is None:
            levels = pns_levels(seq)
        else:
            levels = pns_levels(seq, thresholds=tuple(args.thresholds))
        seconds.append(time.perf_counter() - start)

    info = machine()
    print()
    print(f"blocks: {blocks}; " + "; ".join(f"{k}: {v}" for k, v in info.items()))
    print(f"samples: {levels.num_samples}; peak: {levels.peak:.6f}")
    thresholds_used = "default" if args.thresholds is None else ", ".join(map(str, levels.above))
    print(f"thresholds: {thresholds_used}")
    for threshold, intervals in levels.above.items():
        print(f"intervals at or above {threshold}: {len(intervals)}")
    print("pns_levels (s): " + ", ".join(f"{s:.2f}" for s in seconds))
    print(f"minimum (s): {min(seconds):.2f}")
    if args.json:
        report = {
            "blocks": blocks,
            "build_seconds": build_s,
            "machine": info,
            "num_samples": levels.num_samples,
            "peak": levels.peak,
            "thresholds": args.thresholds,
            "intervals": {str(t): len(intervals) for t, intervals in levels.above.items()},
            "seconds": seconds,
            "minimum_seconds": min(seconds),
        }
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
