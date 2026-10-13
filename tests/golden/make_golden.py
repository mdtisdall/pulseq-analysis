"""Write `safe_fork.npz`: the outputs of the functions that only the pypulseq fork has, for the
inputs of the tests of `test_safe.py` that compare with them. Run it with the fork pinned
(README.md gives the commit), from the root of the repository:

    uv run python tests/golden/make_golden.py
"""

import sys
from pathlib import Path

import numpy as np
from pypulseq.utils import safe_pns_prediction as module

TESTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TESTS))

import synthetic
import test_safe

from pulseq_analysis.analyses import load
from pulseq_analysis.analyses import pns_levels as pns_levels_module
from pulseq_analysis.analyses.pns_levels import _compute_levels


def chunk_values() -> dict[str, np.ndarray]:
    """The `pns` array and the state (`g_last`, `zi`) of the fork's `_safe_gwf_to_pns_chunk`
    for each chunk of `test_the_chunk_function_equals_the_forks_for_every_chunk_and_state`."""
    values = {}
    for scaled_id, ns_of in test_safe.CHUNK_NAMESPACES.items():
        for dt_id, dt in test_safe.CHUNK_DTS.items():
            state = None
            for i, (start, stop) in enumerate(test_safe.CHUNKS):
                pns, state = module._safe_gwf_to_pns_chunk(
                    test_safe.chunk_waveform()[start:stop], dt, ns_of(), state
                )
                key = f"chunk/{scaled_id}/{dt_id}/{i}"
                values[f"{key}/pns"] = pns
                values[f"{key}/g_last"] = state.g_last
                values[f"{key}/zi"] = state.zi
    return values


def hw_check_values() -> dict[str, np.ndarray]:
    """Whether the fork's `safe_hw_check` accepts each namespace of
    `test_the_hardware_check_accepts_and_refuses_what_the_forks_safe_hw_check_does`."""
    values = {}
    for case_id, ns_of in test_safe.HW_CHECK_CASES.items():
        try:
            module.safe_hw_check(ns_of())
        except (ValueError, AttributeError):
            accepts = False
        else:
            accepts = True
        values[f"hw_check/{case_id}"] = np.array(accepts)
    return values


def levels_values() -> dict[str, np.ndarray]:
    """The fields of `_compute_levels` with the fork's `_safe_gwf_to_pns_chunk` in place of
    the package's, for each case of
    `test_pns_levels_equals_the_levels_with_the_forks_chunk_function`."""
    values = {}
    pns_levels_module._CHUNK_SAMPLES = 1000
    pns_levels_module._safe_gwf_to_pns_chunk = module._safe_gwf_to_pns_chunk
    for seq_id, builder in test_safe.SEQUENCES.items():
        snap = load(getattr(synthetic, builder)())
        for bin_id, bin_s in test_safe.BINS.items():
            levels = _compute_levels(snap, synthetic.EXAMPLE_HW, test_safe.THRESHOLDS, bin_s)
            values.update(
                {
                    f"levels/{seq_id}/{bin_id}/{k}": np.asarray(v)
                    for k, v in test_safe.levels_arrays(levels).items()
                }
            )
    return values


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "safe_fork.npz"
    np.savez_compressed(out, **chunk_values(), **hw_check_values(), **levels_values())
    print(f"wrote {out}")
