"""Time of the measurements other than PNS, on a large synthetic sequence.

`docs/implementation.md` ("Measured times") gives the results. `scripts/time_pns_levels.py`
times `pns_levels`.

The script builds `build_repeating` (or, with `--case worst`, `build_worst`) of
`tests/scale_sequences.py` with about `--blocks` blocks: a GRE-like TR of 5 blocks. In
`build_repeating` the gradient events repeat (the phase-encode table has 256 entries), and
in `build_worst` each TR has a new phase-encode event. Then it calls the public functions
in this order, on the same sequence object, and times each call:

1. `sequence_index(seq)`: the block table.
2. `gradient_peaks(seq)`: the first call of a gradient measurement. It reads the points of
   the unique gradient events and makes the values of each block, and keeps them.
3. `block_gradient_values(seq)`: with the kept values of each block.
4. `gradient_peaks(seq, window=...)`: the median of `WINDOWS` windows at random places, of
   one block, of one TR and of 1000 TRs.
5. `gradient_sampler(seq).sample("gx", t)`: `SAMPLE_TIMES` sorted times over the sequence.
6. `gradient_spectrum(seq)`: the default arguments.

A row is thus the time of its call after the calls above it. Each repeat builds a new
sequence, so it keeps nothing from the repeat before it. The result of each row is the
minimum over the repeats. Run it in the devShell:

    nix develop --command uv run python scripts/time_measurements.py [--blocks N] \
[--case repeating|worst] [--repeat R] [--json OUT]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from time_pns_levels import machine

WINDOWS = 100
SAMPLE_TIMES = 1_000_000
SEED = 0


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def median_window_time(seq, index, n_blocks, rng):
    """The median time of `WINDOWS` calls of `gradient_peaks` with a window of `n_blocks`
    whole blocks, at random places, after one call that is not timed."""
    from pulseq_analysis.grad_peaks import gradient_peaks

    n = int(index.num_blocks)
    firsts = rng.integers(0, n - n_blocks + 1, size=WINDOWS + 1)
    times = []
    for first in firsts:
        lo = float(index.start_s[first])
        last = first + n_blocks - 1
        hi = float(index.start_s[last] + index.duration_s[last])
        seconds, _ = timed(lambda lo=lo, hi=hi: gradient_peaks(seq, window=(lo, hi)))
        times.append(seconds)
    return float(np.median(times[1:]))


def run_once(build, n_trs, rng):
    from scale_sequences import TR_BLOCKS

    from pulseq_analysis.grad_peaks import block_gradient_values, gradient_peaks
    from pulseq_analysis.grad_spectrum import gradient_spectrum
    from pulseq_analysis.sampling import gradient_sampler
    from pulseq_analysis.seq_index import sequence_index

    seq = build(n_trs)
    rows = {}
    rows["sequence_index"], index = timed(lambda: sequence_index(seq))
    rows["gradient_peaks, first call"], _ = timed(lambda: gradient_peaks(seq))
    rows["block_gradient_values"], _ = timed(lambda: block_gradient_values(seq))
    for label, n_blocks in (
        ("gradient_peaks, window of 1 block", 1),
        ("gradient_peaks, window of 1 TR", TR_BLOCKS),
        ("gradient_peaks, window of 1000 TRs", min(1000 * TR_BLOCKS, int(index.num_blocks))),
    ):
        rows[label] = median_window_time(seq, index, n_blocks, rng)
    t = np.linspace(0.0, float(index.end_s), SAMPLE_TIMES)
    rows[f"sample, {SAMPLE_TIMES} times"], _ = timed(lambda: gradient_sampler(seq).sample("gx", t))
    rows["gradient_spectrum"], spectrum = timed(lambda: gradient_spectrum(seq))
    return rows, index, spectrum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--blocks", type=int, default=100_000, help="blocks of the sequence")
    parser.add_argument("--case", choices=("repeating", "worst"), default="repeating")
    parser.add_argument("--repeat", type=int, default=3, help="number of timed runs")
    parser.add_argument("--json", type=Path, metavar="OUT", help="write the results as JSON")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    from scale_sequences import TR_BLOCKS, build_repeating, build_worst

    if args.blocks < 1000 * TR_BLOCKS:
        parser.error(f"--blocks must be at least {1000 * TR_BLOCKS}, 1000 TRs")
    build = build_repeating if args.case == "repeating" else build_worst
    n_trs = args.blocks // TR_BLOCKS
    rng = np.random.default_rng(SEED)
    runs = []
    for i in range(args.repeat):
        print(f"run {i + 1} of {args.repeat}", file=sys.stderr)
        rows, index, spectrum = run_once(build, n_trs, rng)
        runs.append(rows)

    info = machine()
    best = {label: min(r[label] for r in runs) for label in runs[0]}
    print()
    print(
        f"case: {args.case}; blocks: {index.num_blocks}; "
        f"unique gradient events: {index.grad_first.size}; duration (s): {index.end_s:.2f}"
    )
    print("; ".join(f"{k}: {v}" for k, v in info.items()))
    for label, seconds in best.items():
        print(f"{label:40s} {seconds * 1e3:12.2f} ms")
    if args.json:
        report = {
            "case": args.case,
            "blocks": int(index.num_blocks),
            "unique_gradient_events": int(index.grad_first.size),
            "duration_s": float(index.end_s),
            "spectrum_frequencies": int(spectrum.frequency_hz.size),
            "machine": info,
            "repeat": args.repeat,
            "seconds": runs,
            "minimum_seconds": best,
        }
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
