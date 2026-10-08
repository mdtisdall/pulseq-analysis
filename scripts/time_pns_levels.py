"""Time of `pns_levels` on a large synthetic sequence (plan decision D3).

Builds `build_repeating` of `tests/scale_sequences.py` with about 10^6 blocks, and times
`pns_levels._compute_levels` (the calculation of `pns_levels`, with no keep: a second call of
`pns_levels` would give the kept result, so each repeat would not run the model) with
pypulseq's example hardware, which is not a real scanner (`pns_levels` has no default
hardware, so the script gives
`(safe_example_hw(), "pypulseq example hardware (not a real scanner)")`), `--repeat`
times in this process. The script checks the hardware, the thresholds and the bin
(`BIN_S`) as `pns_levels` does, and gives `_compute_levels` the checked values. The result
is the minimum time. With `--thresholds-hz-per-t T [T ...]` (in Hz/T) the call also has
those thresholds, and without it the default of `pns_levels` is used (no threshold). The
peak is in Hz/T. Run it in the devShell:

    nix develop --command uv run python scripts/time_pns_levels.py [--blocks N] \
[--repeat R] [--thresholds-hz-per-t T [T ...]] [--json OUT]

`--blocks` must be at least `TR_BLOCKS` (one TR), and the thresholds are checked with
the validation of `pns_levels` before the sequence is built. The build of the sequence is
timed and printed, but it is not part of the result. So are the times of `load(seq)` and of
`load(path)` for the file that `seq.write` makes (`load_times`): each is printed and given in
the JSON, one time.
`sequence_index` keeps its result on the snapshot, so the first run also builds the block
table and the later runs do not. The minimum is thus the time of the PNS model, the sampling
and the bins, without the block table.
"""

import argparse
import json
import platform
import subprocess
import sys
import tempfile
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


def load_times(seq) -> tuple[float, float, object]:
    """The time of `load(seq)`, the time of `load(path)` for the file that `seq.write` makes
    (the write is not timed), and the `Snapshot` of `load(seq)`."""
    from pulseq_analysis.snapshot import load

    start = time.perf_counter()
    snap = load(seq)
    load_seq_s = time.perf_counter() - start
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sequence.seq"
        seq.write(str(path))
        start = time.perf_counter()
        load(path)
        load_path_s = time.perf_counter() - start
    return load_seq_s, load_path_s, snap


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
        "--thresholds-hz-per-t",
        type=float,
        nargs="+",
        metavar="T",
        help="the thresholds of pns_levels, in Hz/T (default: the default of pns_levels, none)",
    )
    parser.add_argument("--json", type=Path, metavar="OUT", help="write the results as JSON")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    from pypulseq.utils.safe_pns_prediction import safe_example_hw
    from scale_sequences import TR_BLOCKS, build_repeating

    from pulseq_analysis.pns_levels import (
        BIN_S,
        _check_hardware,
        _compute_levels,
        _validated_thresholds,
    )

    if args.blocks < TR_BLOCKS:
        parser.error(f"--blocks must be at least {TR_BLOCKS}, one TR")
    keys: tuple[float, ...] = ()
    if args.thresholds_hz_per_t is not None:
        try:
            keys = _validated_thresholds(tuple(args.thresholds_hz_per_t))
        except ValueError as error:
            parser.error(f"--thresholds-hz-per-t: {error}")

    n_trs = args.blocks // TR_BLOCKS
    blocks = n_trs * TR_BLOCKS
    print(f"building {blocks} blocks", file=sys.stderr)
    start = time.perf_counter()
    seq = build_repeating(n_trs)
    build_s = time.perf_counter() - start
    print(f"build {build_s:.1f} s (not part of the result)")
    load_seq_s, load_path_s, snap = load_times(seq)
    print(f"load(seq) {load_seq_s:.2f} s, load(path) {load_path_s:.2f} s (not part of the result)")

    hardware = (safe_example_hw(), "pypulseq example hardware (not a real scanner)")
    _check_hardware(hardware)
    seconds = []
    for i in range(args.repeat):
        print(f"run {i + 1} of {args.repeat}", file=sys.stderr)
        start = time.perf_counter()
        levels = _compute_levels(snap, hardware, keys, BIN_S)
        seconds.append(time.perf_counter() - start)

    info = machine()
    print()
    print(f"blocks: {blocks}; " + "; ".join(f"{k}: {v}" for k, v in info.items()))
    print(f"samples: {levels.num_samples}; peak_hz_per_t: {levels.peak_hz_per_t:.6f}")
    thresholds_used = (
        "default" if args.thresholds_hz_per_t is None else ", ".join(map(str, levels.above))
    )
    print(f"thresholds_hz_per_t: {thresholds_used}")
    for threshold, intervals in levels.above.items():
        print(f"intervals at or above {threshold} Hz/T: {len(intervals)}")
    print("pns_levels (s): " + ", ".join(f"{s:.2f}" for s in seconds))
    print(f"minimum (s): {min(seconds):.2f}")
    if args.json:
        report = {
            "blocks": blocks,
            "build_seconds": build_s,
            "load_seq_seconds": load_seq_s,
            "load_path_seconds": load_path_s,
            "machine": info,
            "num_samples": levels.num_samples,
            "peak_hz_per_t": levels.peak_hz_per_t,
            "thresholds_hz_per_t": args.thresholds_hz_per_t,
            "intervals": {str(t): len(intervals) for t, intervals in levels.above.items()},
            "seconds": seconds,
            "minimum_seconds": min(seconds),
        }
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
