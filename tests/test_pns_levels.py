import copy
import dataclasses
import itertools
import math
import pickle
import re
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from asserts import assert_levels_equal
from optional_pypulseq import pp
from pns_hardware import EXAMPLE_HW, hardware_for_peak
from synthetic import (
    GAMMA_1H,
    SYSTEM,
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    safe_example_hw,
    spin_echo_sequence,
    waveform_sequence,
)

from pulseq_analysis._equality import FrozenDict
from pulseq_analysis._validate import real
from pulseq_analysis.analyses import grad_spectrum, load
from pulseq_analysis.analyses.asc import hardware_from_asc
from pulseq_analysis.analyses.pns_levels import (
    _CHUNK_SAMPLES,
    BIN_S,
    MAX_BINS,
    NO_GRADIENTS,
    PEAK_TOLERANCE,
    PnsInterval,
    PnsLevels,
    _cast_outward,
    _check_hardware,
    _chunk_total,
    _compute_levels,
    _IntervalFinder,
    _validated_thresholds,
    bin_samples_for,
    pns_levels,
)
from pulseq_analysis.analyses.registry import PNS_SAFE_LEVELS
from pulseq_analysis.analyses.safe import SafeHardware, _safe_gwf_to_pns_chunk
from pulseq_analysis.synth import seq_index
from pulseq_analysis.synth.seq_index import sequence_index

_HW_FIELDS = ("tau1", "tau2", "tau3", "a1", "a2", "a3", "stim_limit", "g_scale")
_LIMIT = GAMMA_1H  # Hz/T: the stimulation limit for 1H, a fraction of 1 times GAMMA_1H


def _hw_dict(hw_ns) -> dict:
    return {
        axis: {field: getattr(getattr(hw_ns, axis), field) for field in _HW_FIELDS}
        for axis in "xyz"
    }


def _compute(snap, *, hardware, thresholds_hz_per_t=(), bin_s=BIN_S) -> PnsLevels:
    """`_compute_levels`, the calculation of `pns_levels` with no keep, with the arguments
    checked as `pns_levels` checks them. Each call runs the model and gives a new result, so
    a test that changes `_CHUNK_SAMPLES` or compares two calculations of one sequence uses it:
    a second call of `pns_levels` with the same arguments gives the kept object."""
    _check_hardware(hardware)
    return _compute_levels(
        snap,
        hardware,
        _validated_thresholds(thresholds_hz_per_t),
        real("bin_s", bin_s, positive=True),
    )


def _add_a_delay(seq: pp.Sequence, steps: float) -> None:
    """Add a block of `steps` gradient-raster steps of delay to `seq`, which is not a whole
    number of steps when `steps` is 1.5. pypulseq's writer divides a block duration by
    `BlockDurationRaster` and refuses a result that is not a whole number, so the sequence
    gets a block duration raster of 1 us first (a block of 15 us is then 15 raster steps)."""
    seq.block_duration_raster = 1e-6
    seq.set_definition("BlockDurationRaster", 1e-6)
    seq.add_block(pp.make_delay(steps * SYSTEM.grad_raster_time))


def _off_raster_sequence() -> pp.Sequence:
    """A trapezoid on x (so there is a gradient to predict PNS from), followed by a
    delay block whose duration (1.5 gradient-raster steps) pypulseq's `add_block`
    accepts but which is not a whole number of raster steps."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=1000, system=SYSTEM))
    _add_a_delay(seq, 1.5)
    return seq


def _other_gamma_waveform_sequence() -> pp.Sequence:
    """`waveform_sequence` with a copy of `SYSTEM` whose gamma is 0.9 times the gamma of 1H.
    The written file has no gamma (it is that of `waveform_sequence(SYSTEM)`), so the levels
    are those of the Hz/m samples."""
    other = copy.copy(SYSTEM)
    other.gamma = 0.9 * SYSTEM.gamma
    return waveform_sequence(other)


_SEQUENCES = {
    "spin_echo": spin_echo_sequence,
    "gre": gre_sequence,
    "arbitrary_gradient": arbitrary_gradient_sequence,
    "border": border_sequence,
    "waveform_other_gamma": _other_gamma_waveform_sequence,
}


def _oracle_model(snap, levels: PnsLevels) -> tuple[np.ndarray, np.ndarray]:
    """The SAFE model of the oracle samples of `snap`, the reference of `pns_levels`: the
    package's `_safe_gwf_to_pns_chunk` in one chunk, with the example hardware, on the stacked
    `(N, 3)` samples of the oracle of `sequence_of(snap)` (`oracle.block_samples` at the
    gradient raster when `levels.on_raster`, else `oracle.sample` at the file times
    `(k + 0.5) * dt` for `k < levels.num_samples`). Returns `(axis_values, total)`: the
    percent times 0.01 (`(N, 3)`) and the `sqrt(sum of squares)` of each row, as
    `pns_levels` computes them. The oracle reads the gradients of the snapshot
    as it plays them, so the rounding of the written file is not in a difference. The oracles
    import pypulseq, so they are imported here: the module also runs without it."""
    from oracles import waveform as oracle
    from oracles.blocks import sequence_of

    seq = sequence_of(snap)
    dt = seq.grad_raster_time
    if levels.on_raster:
        columns = [oracle.block_samples(seq, axis, dt) for axis in "xyz"]
    else:
        t = (np.arange(levels.num_samples) + 0.5) * dt
        columns = [oracle.sample(seq, axis, t) for axis in "xyz"]
    gwf = np.stack(columns, axis=1)
    percent, _ = _safe_gwf_to_pns_chunk(gwf, dt, safe_example_hw(), None)
    axis_values = 0.01 * percent
    return axis_values, np.sqrt((axis_values**2).sum(axis=1))


def _assert_summary_is_the_model(
    levels: PnsLevels, axis_values: np.ndarray, total: np.ndarray
) -> None:
    """The peak and the axis peaks of `levels` equal those of the model (`_oracle_model`)
    to a relative 1e-9 (the axis peaks also to an absolute 1e-12 of the peak), and the peak
    time is the centre of the first sample whose total is at least the peak times
    `1 - PEAK_TOLERANCE`."""
    peak = total.max()
    assert levels.num_samples == total.size
    assert levels.peak_hz_per_t == pytest.approx(peak, rel=1e-9)
    for i, axis in enumerate("xyz"):
        assert levels.axis_peaks_hz_per_t[axis] == pytest.approx(
            axis_values[:, i].max(), rel=1e-9, abs=1e-12 * peak
        )
    assert levels.peak_time_s == pytest.approx(
        (np.flatnonzero(total >= peak * (1 - PEAK_TOLERANCE))[0] + 0.5) * levels.dt_s,
        abs=1e-12,
    )


@pytest.mark.pypulseq
@pytest.mark.parametrize("build", _SEQUENCES.values(), ids=_SEQUENCES.keys())
def test_summary_is_the_safe_model_of_the_oracle_samples(build):
    """The peak, the peak time and the axis peaks of `pns_levels` (example hardware) equal
    the SAFE model of the oracle samples (`_oracle_model`: the package's
    `_safe_gwf_to_pns_chunk` on the samples of the model of MATLAB Pulseq) to a relative
    1e-9. Both are in Hz/T: the model runs on the Hz/m samples, so no gamma is divided."""
    seq = build()
    snap = load(seq)
    levels = pns_levels(snap, hardware=EXAMPLE_HW)
    axis_values, total = _oracle_model(snap, levels)

    assert levels.reason is None
    assert levels.hardware == EXAMPLE_HW.name
    assert levels.dt_s == seq.grad_raster_time
    assert levels.on_raster is True
    _assert_summary_is_the_model(levels, axis_values, total)


@pytest.mark.pypulseq
@pytest.mark.parametrize("build", _SEQUENCES.values(), ids=_SEQUENCES.keys())
def test_stored_bins_are_the_extremes_of_the_model_totals(build):
    """Each stored bin's minimum and maximum equal the minimum and the maximum of the totals
    of the SAFE model of the oracle samples (`_oracle_model`) over the same samples, for every
    bin, to a relative 1e-6 (the stored bins are float32, cast outward) and an absolute 1e-12
    of the peak (the rounding residue of a sample that is 0). A bin is 7 samples, so that each
    sequence has more than one."""
    snap = load(build())
    levels = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=7 * SYSTEM.grad_raster_time)
    _, total = _oracle_model(snap, levels)
    starts = range(0, levels.num_samples, levels.bin_samples)
    ref_min = np.array([total[s : s + levels.bin_samples].min() for s in starts])
    ref_max = np.array([total[s : s + levels.bin_samples].max() for s in starts])

    assert len(levels.level_min_hz_per_t) == len(ref_min) > 1
    atol = 1e-12 * total.max()
    np.testing.assert_allclose(levels.level_min_hz_per_t, ref_min, rtol=1e-6, atol=atol)
    np.testing.assert_allclose(levels.level_max_hz_per_t, ref_max, rtol=1e-6, atol=atol)


# The sequences with an end that is not 0 next to a gap that `spec` reads: the hand sequences of
# `gap_sequences` that it reads, three of them also with every amplitude negated (the gap rules
# do not depend on the sign), and the 8 random sequences of `random_gap_sequence(rng,
# for_spec=True)` (random signs, zero, short and long gaps, and blocks of zero duration). The
# names that end in `_off_raster` have a last block of 1.5 raster times (`_add_a_delay`), which
# is not on the raster, so that `pns_levels` samples the whole sequence with
# `GradientSampler.sample`.
_GAP_ON_RASTER = [
    "long_gap",
    "non_zero_ends",
    "short_gap_from_0",
    "negated_zero_gap",
    "negated_long_gap",
    "negated_non_zero_ends",
    *(f"random_gaps_for_spec_{seed}" for seed in range(8)),
]
_GAP_NAMES = _GAP_ON_RASTER + [
    f"{name}_off_raster"
    for name in [
        "long_gap",
        "short_gap_from_0",
        "negated_long_gap",
        *(f"random_gaps_for_spec_{seed}" for seed in range(8)),
    ]
]


def _gap_sequence(name: str) -> pp.Sequence:
    """The sequence `name` of `_GAP_NAMES`: `gap_sequences.<name>_sequence()` or
    `random_gap_sequence(np.random.default_rng(seed), for_spec=True)`, negated
    (`gap_sequences.negated`) for a name that starts with `negated_`, and with a last block of 1.5
    raster times (`_add_a_delay`) for a name that ends in `_off_raster`. `gap_sequences` and
    `random_gaps` import pypulseq, so they are imported here: the module also runs without it."""
    import gap_sequences
    from random_gaps import random_gap_sequence

    base = name.removesuffix("_off_raster").removeprefix("negated_")
    if base.startswith("random_gaps_for_spec_"):
        seed = int(base.removeprefix("random_gaps_for_spec_"))
        seq = random_gap_sequence(np.random.default_rng(seed), for_spec=True)
    else:
        seq = getattr(gap_sequences, f"{base}_sequence")()
    if name.startswith("negated_"):
        seq = gap_sequences.negated(seq)
    if name.endswith("_off_raster"):
        _add_a_delay(seq, 1.5)
    return seq


def check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
    snap, on_raster: bool
) -> None:
    """`pns_levels` of `snap` (example hardware, `bin_s` of one gradient raster time) is the SAFE
    model of the oracle samples (`_oracle_model`): `on_raster` is that of the levels, the summary
    is the model's (`_assert_summary_is_the_model`), and each bin of one sample holds the total of
    its sample, to a relative 1e-6 (the float32 cast) and an absolute 1e-12 of the peak."""
    from oracles.blocks import sequence_of

    levels = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=sequence_of(snap).grad_raster_time)
    axis_values, total = _oracle_model(snap, levels)

    assert levels.on_raster is on_raster
    _assert_summary_is_the_model(levels, axis_values, total)
    # The total of a sample at 0 can be a rounding residue of about 1e-16 of the peak, where a
    # sample at the last point of a ramp is not exactly 0 in one of the two paths.
    atol = 1e-12 * total.max()
    np.testing.assert_allclose(levels.level_max_hz_per_t, total, rtol=1e-6, atol=atol)
    np.testing.assert_allclose(levels.level_min_hz_per_t, total, rtol=1e-6, atol=atol)


@pytest.mark.pypulseq
@pytest.mark.parametrize("name", _GAP_NAMES)
def test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
    name,
):
    """For a sequence that `spec` reads with a long gap, a short gap from 0, or a step at a
    junction, and an end that is not 0 next to it (and the first value and the last value of an
    axis that are not 0), `pns_levels` is the SAFE model of the oracle samples
    (`check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`),
    on the raster and, for the names that end in `_off_raster`, off it (`_GAP_NAMES`).
    `calculate_pns` of pypulseq is not the reference: it draws a line across each gap
    (pypulseq-issues 12). The test of the same name of the `cpp-siemens` plugin has the sequences
    that `spec` rejects."""
    check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
        load(_gap_sequence(name)), on_raster=not name.endswith("_off_raster")
    )


def test_cast_outward_bounds_every_input_value():
    """`_cast_outward` (the float32 rounding of item 4 of `pns_levels`'s docstring)
    never lands on the wrong side of its float64 input: the downward cast (used for a
    bin's minimum) is at most the input, and the upward cast (used for a maximum) is
    at least the input, for values that generally fall strictly between two
    representable float32 numbers."""
    rng = np.random.default_rng(0)
    values = rng.uniform(-1000.0, 1000.0, size=2000)
    down = _cast_outward(values, down=True)
    up = _cast_outward(values, down=False)
    assert down.dtype == np.float32
    assert up.dtype == np.float32
    assert np.all(down.astype(np.float64) <= values)
    assert np.all(up.astype(np.float64) >= values)


def test_cast_outward_keeps_zero_at_zero():
    """`_cast_outward` of float64 values that the float32 cast holds exactly (zeros) gives
    the same zeros, for the downward and for the upward cast: a bin of zeros has no level
    below or above 0."""
    values = np.zeros(4)
    for down in (True, False):
        cast = _cast_outward(values, down=down)
        assert cast.dtype == np.float32
        assert np.array_equal(cast, np.zeros(4, dtype=np.float32)), down


def test_interval_finder_tie_across_a_chunk_boundary_keeps_the_earlier_peak_sample():
    """One run over a chunk boundary, with the same largest total on each side (1.0 at
    sample 1, the end of the first chunk, and at sample 2, the start of the second), is one
    interval of samples 1 and 2 whose peak is the first of the two samples: the peak time is
    `(1 + 0.5) * dt`, not `(2 + 0.5) * dt`."""
    finder = _IntervalFinder(1.0, 0.5)
    finder.add_chunk(0, np.array([0.0, 1.0]))
    finder.add_chunk(2, np.array([1.0, 0.0]))
    (interval,) = finder.finish()
    assert (interval.start_s, interval.end_s) == (1.0, 3.0)
    assert interval.num_samples == 2
    assert interval.peak_time_s == 1.5


def test_interval_finder_gap_at_the_start_of_a_chunk_does_not_join_the_open_run():
    """A run that ends at the end of a chunk, and a run in the next chunk that starts after
    one sample below the threshold (not at the first sample), are two intervals."""
    finder = _IntervalFinder(1.0, 0.5)
    finder.add_chunk(0, np.array([0.0, 1.0]))
    finder.add_chunk(2, np.array([0.0, 1.0]))
    intervals = finder.finish()
    assert [(i.start_s, i.end_s, i.num_samples) for i in intervals] == [
        (1.0, 2.0, 1),
        (3.0, 4.0, 1),
    ]


def test_an_interval_of_one_sample_spans_one_sample_interval_from_its_first_sample_edge():
    """A run of one sample, sample 2 of `[0, 0, 1, 0]`, has `start_s == 2 * dt` and
    `end_s - start_s == dt`, and the peak time is the time of the sample, `2.5 * dt`."""
    dt = 0.25  # a power of 2, so the products and the difference are exact
    finder = _IntervalFinder(dt, 0.5)
    finder.add_chunk(0, np.array([0.0, 0.0, 1.0, 0.0]))
    (interval,) = finder.finish()
    assert interval.num_samples == 1
    assert interval.start_s == 2 * dt
    assert interval.end_s - interval.start_s == dt
    assert interval.peak_time_s == 2.5 * dt


_NUMPY_DIR = str(Path(np.__file__).parent)


def _numpy_calls(call) -> int:
    """The number of NumPy calls that `call()` makes, at any depth: each call of a Python
    function of the NumPy package, and each call of a C method of an array, a ufunc or the
    `numpy` module (`sys.setprofile`)."""
    count = 0

    def profile(frame, event, arg):
        nonlocal count
        python = event == "call" and frame.f_code.co_filename.startswith(_NUMPY_DIR)
        method = event == "c_call" and isinstance(
            getattr(arg, "__self__", None), (np.ndarray, np.ufunc, type(np))
        )
        count += python or method

    sys.setprofile(profile)
    try:
        call()
    finally:
        sys.setprofile(None)
    return count


def test_interval_finder_makes_as_many_numpy_calls_for_many_runs_as_for_one():
    """The NumPy calls of `add_chunk` do not grow with the number of runs in the chunk: a
    chunk with 40 runs makes as many as a chunk with 1 run (each run is one sample at 1.0,
    between samples at 0.0, so no run touches an end of the chunk)."""

    def calls(runs: int) -> int:
        total = np.zeros(4 * runs + 1)
        total[2::4] = 1.0
        finder = _IntervalFinder(1.0, 0.5)
        count = _numpy_calls(lambda: finder.add_chunk(0, total))
        assert len(finder.finish()) == runs
        return count

    assert calls(40) == calls(1)


def _reference_runs(total: np.ndarray, threshold: float, dt: float) -> tuple[PnsInterval, ...]:
    """The runs of `total >= threshold` in the whole of `total`, with `itertools.groupby`,
    each with the first sample of its largest total."""
    runs = []
    position = 0
    for above, group in itertools.groupby(total >= threshold):
        length = len(list(group))
        if above:
            run = total[position : position + length]
            peak_sample = position + int(np.flatnonzero(run == run.max())[0])
            runs.append(
                PnsInterval(
                    start_s=position * dt,
                    end_s=(position + length) * dt,
                    peak_hz_per_t=float(run.max()),
                    peak_time_s=(peak_sample + 0.5) * dt,
                    num_samples=length,
                )
            )
        position += length
    return tuple(runs)


def test_interval_finder_gives_the_runs_of_a_reference_over_random_chunks():
    """For 500 random totals, cut into random chunks (of 1 sample or more, so runs cross one
    or more chunk boundaries), the intervals of `_IntervalFinder` equal the runs of the whole
    totals that `_reference_runs` finds. The totals are 0, 0.5, 1 or 1.5, with a threshold of
    1, so there are runs of one sample and ties of the largest total within a run, and some
    totals are NaN (in no run)."""
    dt = 1e-5
    rng = np.random.default_rng(0)
    for case in range(500):
        num_samples = int(rng.integers(1, 80))
        total = rng.integers(0, 4, num_samples) * 0.5
        total[rng.random(num_samples) < 0.05] = np.nan
        num_cuts = int(rng.integers(0, num_samples))
        cuts = np.sort(rng.choice(np.arange(1, num_samples), num_cuts, replace=False))
        finder = _IntervalFinder(dt, 1.0)
        for start, chunk in zip(
            np.concatenate(([0], cuts)).tolist(), np.split(total, cuts), strict=True
        ):
            finder.add_chunk(start, chunk)
        assert finder.finish() == _reference_runs(total, 1.0, dt), case


@pytest.mark.pypulseq
def test_bin_samples_for_matches_the_formula():
    """`bin_samples_for` follows `max(wanted, ceil(num_samples / MAX_BINS), 1)`, where
    `wanted` is the whole number of samples of `bin_s` (the new test below checks the snap).
    With the default `BIN_S` (5 ms): 500 samples at the 10 us raster for any file of up to
    1,000,000,000 samples (`500 * MAX_BINS`), and a coarser bin for a larger file, computed
    from `num_samples` alone. With another `bin_s`: the bin rounded down to whole samples,
    one sample for a `bin_s` shorter than `dt`, and the coarser bin of a large file. A
    `pns_levels` call on a real sequence also follows the same formula, and gives that many
    bins."""
    dt = 1e-5
    assert bin_samples_for(0, dt) == 500
    assert bin_samples_for(1_000_000_000, dt) == 500
    assert bin_samples_for(1_000_000_001, dt) == 501
    assert bin_samples_for(2_000_000_000, dt) == 1000
    assert bin_samples_for(0, 2e-5) == 250
    assert bin_samples_for(0, dt, BIN_S) == bin_samples_for(0, dt)
    assert BIN_S == 0.005
    assert bin_samples_for(0, dt, 10.0 / 1624) == 615  # the bin of 0.1.0rc5, by `bin_s`

    assert bin_samples_for(0, dt, 1e-3) == 100
    assert bin_samples_for(0, dt, 1.055e-3) == 105
    assert bin_samples_for(0, dt, 1.059e-3) == 105  # rounded down to whole samples
    assert bin_samples_for(0, dt, 1e-6) == 1  # shorter than dt: one sample
    assert bin_samples_for(0, dt, dt) == 1
    assert bin_samples_for(0, 0.25, 1) == 4  # an int is a number of seconds
    assert bin_samples_for(100 * MAX_BINS, dt, 1e-3) == 100
    assert bin_samples_for(100 * MAX_BINS + 1, dt, 1e-3) == 101
    assert bin_samples_for(2 * MAX_BINS, dt, 1e-6) == 2

    levels = pns_levels(load(gre_sequence(num_trs=6)), hardware=EXAMPLE_HW)
    assert levels.bin_samples == bin_samples_for(levels.num_samples, levels.dt_s)
    assert len(levels.level_min_hz_per_t) == -(
        -levels.num_samples // levels.bin_samples
    )  # ceil division
    assert len(levels.level_max_hz_per_t) == len(levels.level_min_hz_per_t)


def test_bin_samples_for_gives_the_whole_samples_of_a_bin_s_on_the_raster():
    """A `bin_s` within `ON_RASTER_TOLERANCE` of a whole number of samples gives that
    number, not one less because the division is not exact: for each `k` from 1 to 2000,
    `bin_s = k * 1e-5` and `bin_s = round(k * 1e-5, 10)` give `k` samples at the 10 us
    raster. A `bin_s` between two samples is rounded down (`615.5 * 1e-5` gives 615), and
    the default is 500 samples."""
    dt = 1e-5
    for k in range(1, 2001):
        assert bin_samples_for(0, dt, k * 1e-5) == k, k
        assert bin_samples_for(0, dt, round(k * 1e-5, 10)) == k, k
    assert bin_samples_for(0, dt, 0.01) == 1000  # `0.01 / 1e-5` is a hair under 1000
    assert bin_samples_for(0, dt, 615.5 * 1e-5) == 615
    assert bin_samples_for(0, dt) == 500


@pytest.mark.pypulseq
def test_bin_s_sets_the_bin_of_the_level_and_holds_every_total(monkeypatch):
    """`bin_s=1e-3` at the 10 us raster gives `bin_samples == 100` (`bin_samples * dt_s` is
    the bin) and `ceil(num_samples / 100)` bins, and each total of a bin (the totals of the
    model, recorded from `_chunk_total`) is in `[level_min_hz_per_t, level_max_hz_per_t]` of
    that bin, with the minimum and the maximum of the bin as its ends. `bin_s` is the
    `bin_s` of each call. Every other field (the summary and the intervals) equals that of
    the default `bin_s`. The levels of a `bin_s` shorter than `dt` have one sample in each
    bin, and so one bin for each sample."""
    snap = load(gre_sequence(num_trs=6))
    hardware = hardware_for_peak(snap, 1.5)
    default = _compute(snap, hardware=hardware, thresholds_hz_per_t=(_LIMIT,))
    totals = []

    def record(gwf, dt, hw_ns, state):
        result = _chunk_total(gwf, dt, hw_ns, state)
        totals.append(result[0])
        return result

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 10**9)
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._chunk_total", record)
    levels = _compute(snap, hardware=hardware, thresholds_hz_per_t=(_LIMIT,), bin_s=1e-3)
    monkeypatch.undo()

    assert levels is not default  # two calculations
    assert levels.dt_s == 1e-5
    assert levels.bin_s == 1e-3
    assert default.bin_s == BIN_S
    assert levels.bin_samples == 100
    assert levels.bin_samples * levels.dt_s == pytest.approx(1e-3)
    assert len(levels.level_min_hz_per_t) == math.ceil(levels.num_samples / 100)
    assert levels.bin_samples != default.bin_samples
    total = totals[0]  # one chunk; the rerun for the peak time records the same total
    assert total.shape[0] == levels.num_samples
    starts = np.arange(0, levels.num_samples, 100)  # the last bin can be shorter
    bin_min, bin_max = np.minimum.reduceat(total, starts), np.maximum.reduceat(total, starts)
    assert np.all(levels.level_min_hz_per_t <= bin_min)
    assert np.all(levels.level_max_hz_per_t >= bin_max)
    assert np.array_equal(levels.level_min_hz_per_t, _cast_outward(bin_min, down=True))
    assert np.array_equal(levels.level_max_hz_per_t, _cast_outward(bin_max, down=False))
    ignore = ("bin_s", "bin_samples", "level_min_hz_per_t", "level_max_hz_per_t")
    assert_levels_equal(levels, default, ignore=ignore)

    fine = _compute(snap, hardware=hardware, bin_s=1e-9)
    assert fine.bin_s == 1e-9
    assert fine.bin_samples == 1
    assert len(fine.level_min_hz_per_t) == fine.num_samples
    assert np.array_equal(fine.level_min_hz_per_t[:100].min(), levels.level_min_hz_per_t[0])


@pytest.mark.pypulseq
def test_max_bins_still_limits_the_bins_for_a_short_bin_s(monkeypatch):
    """With `MAX_BINS` set small, a `bin_s` that would give more bins gets a longer bin:
    `bin_samples == ceil(num_samples / MAX_BINS)` and no more than `MAX_BINS` bins, the
    level still holds every total (its range of the whole file is that of the finest
    level), and a `bin_s` that gives fewer bins keeps its own bin."""
    snap = load(gre_sequence(num_trs=6))
    fine = _compute(snap, hardware=EXAMPLE_HW, bin_s=1e-9)  # one sample in each bin
    assert fine.bin_samples == 1
    num_samples = fine.num_samples

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels.MAX_BINS", 50)
    limited = _compute(snap, hardware=EXAMPLE_HW, bin_s=1e-9)
    assert limited is not fine  # two calculations of one sequence and one bin_s
    assert limited.bin_samples == math.ceil(num_samples / 50)
    assert len(limited.level_min_hz_per_t) <= 50
    assert limited.level_min_hz_per_t.min() == fine.level_min_hz_per_t.min()
    assert limited.level_max_hz_per_t.max() == fine.level_max_hz_per_t.max()
    assert_levels_equal(
        limited, fine, ignore=("bin_samples", "level_min_hz_per_t", "level_max_hz_per_t")
    )

    long_bin = _compute(snap, hardware=EXAMPLE_HW, bin_s=num_samples * 1e-5)  # one bin
    assert long_bin.bin_samples == num_samples
    assert len(long_bin.level_min_hz_per_t) == 1


@pytest.mark.pypulseq
def test_result_does_not_depend_on_chunk_samples(monkeypatch):
    """The stored level and the summary do not depend on the chunk size: the fork's
    chunk function is exact for any chunk size, so a difference would be an error of
    this library's own binning, not of the fork. The test sets `_CHUNK_SAMPLES` of
    `pulseq_analysis.analyses.pns_levels`, and `pns_levels` rounds the chunk up to a whole number
    of bins: 1 gives a chunk of 1 bin, `bin_samples + 1` gives 2, and
    `7 * bin_samples - 1` gives 7."""
    snap = load(gre_sequence(num_trs=20))
    reference = _compute(snap, hardware=EXAMPLE_HW)
    bin_samples = reference.bin_samples
    assert reference.num_samples > bin_samples * 7  # so the smallest case has > 1 chunk

    sizes = [1, bin_samples + 1, 7 * bin_samples - 1]
    sizes.append(bin_samples * (reference.num_samples // bin_samples + 10))  # > the whole file

    for chunk_samples in sizes:
        monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", chunk_samples)
        got = _compute(snap, hardware=EXAMPLE_HW)
        assert got is not reference  # a new calculation, not the first result again
        assert np.array_equal(got.level_min_hz_per_t, reference.level_min_hz_per_t)
        assert np.array_equal(got.level_max_hz_per_t, reference.level_max_hz_per_t)
        assert got.peak_hz_per_t == reference.peak_hz_per_t
        assert got.peak_time_s == reference.peak_time_s
        assert got.axis_peaks_hz_per_t == reference.axis_peaks_hz_per_t
        assert got.num_samples == reference.num_samples
        assert got.bin_samples == reference.bin_samples


@pytest.mark.pypulseq
def test_a_block_longer_than_a_chunk_does_not_depend_on_chunk_samples(monkeypatch):
    """A block of 10,000 samples that holds events on x and z (with a delay before the first
    one) and is cut by many chunk ends gives the same result with chunks of 1 bin, of 2 bins
    and one chunk bigger than the file: every field, and the intervals of a threshold below
    the peak. Each chunk reads only its part of the block."""
    dt = SYSTEM.grad_raster_time
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_trapezoid(channel="x", area=1000.0, delay=2000 * dt, system=SYSTEM),
        pp.make_trapezoid(channel="z", area=500.0, system=SYSTEM),
        pp.make_delay(10_000 * dt),
    )
    seq.add_block(pp.make_trapezoid(channel="y", area=1000.0, system=SYSTEM))
    snap = load(seq)
    thresholds = (0.05 * _LIMIT,)

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 10**9)
    reference = _compute(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
    assert reference.bin_samples * 4 < 10_000  # the block is cut by more than 4 chunk ends
    assert len(reference.above[thresholds[0]]) >= 1

    for chunk_samples in (1, reference.bin_samples + 1):
        monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", chunk_samples)
        got = _compute(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
        assert got is not reference  # a new calculation, not the first result again
        assert_levels_equal(got, reference, ignore=())


@pytest.mark.pypulseq
def test_one_long_delay_block_gives_the_result_of_the_same_time_in_short_blocks():
    """A trapezoid and then one delay block of 1 s (100,000 samples, three real chunks) gives
    exactly the result of the trapezoid and then ten delay blocks of 0.1 s: the samples of
    the delay are 0 in both, so the totals, the stored level and the summary are equal."""
    trapezoid = pp.make_trapezoid(channel="x", area=1000.0, system=SYSTEM)
    long_block = pp.Sequence(SYSTEM)
    long_block.add_block(trapezoid)
    long_block.add_block(pp.make_delay(1.0))
    short_blocks = pp.Sequence(SYSTEM)
    short_blocks.add_block(trapezoid)
    for _ in range(10):
        short_blocks.add_block(pp.make_delay(0.1))

    levels = pns_levels(load(long_block), thresholds_hz_per_t=(0.1 * _LIMIT,), hardware=EXAMPLE_HW)
    assert levels.num_samples > 3 * _CHUNK_SAMPLES
    expected = pns_levels(
        load(short_blocks), thresholds_hz_per_t=(0.1 * _LIMIT,), hardware=EXAMPLE_HW
    )
    assert len(expected.above[0.1 * _LIMIT]) >= 1
    assert_levels_equal(levels, expected, ignore=())


@pytest.mark.pypulseq
def test_no_gradients():
    """A sequence with no gradient event gives `reason=NO_GRADIENTS`, no stored
    bins, a peak of 0 and `peak_time_s` of None, but still the chosen hardware and the
    `bin_s` of the call."""
    levels = pns_levels(load(empty_sequence()), hardware=EXAMPLE_HW)
    assert levels.reason == NO_GRADIENTS
    assert levels.hardware == EXAMPLE_HW.name
    assert levels.level_min_hz_per_t.shape == (0,)
    assert levels.level_max_hz_per_t.shape == (0,)
    assert levels.peak_hz_per_t == 0.0
    assert levels.peak_time_s is None
    assert levels.axis_peaks_hz_per_t == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert levels.hw == _hw_dict(safe_example_hw())
    assert levels.above == {}
    assert levels.bin_s == BIN_S
    assert pns_levels(load(empty_sequence()), hardware=EXAMPLE_HW, bin_s=1e-3).bin_s == 1e-3


@pytest.mark.pypulseq
def test_no_gradients_gives_an_empty_tuple_for_each_threshold():
    """A sequence with no gradient event and two thresholds gives `above` with the two keys,
    in the order of `thresholds_hz_per_t`, each with `()`."""
    levels = pns_levels(
        load(empty_sequence()), thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT), hardware=EXAMPLE_HW
    )
    assert levels.reason == NO_GRADIENTS
    assert list(levels.above) == [_LIMIT, 0.5 * _LIMIT]
    assert levels.above == {_LIMIT: (), 0.5 * _LIMIT: ()}


@pytest.mark.pypulseq
def test_off_raster_block_falls_back_to_sampling():
    """A file with a block that is not on the gradient raster (`pp.make_delay(1.5 * dt)`,
    which pypulseq's `add_block` accepts) is reported as `on_raster=False`, and its summary
    equals the SAFE model of the oracle samples at the file times `(k + 0.5) * dt`
    (`_oracle_model`) to a relative 1e-9."""
    snap = load(_off_raster_sequence())
    levels = pns_levels(snap, hardware=EXAMPLE_HW)
    axis_values, total = _oracle_model(snap, levels)

    assert levels.on_raster is False
    _assert_summary_is_the_model(levels, axis_values, total)


@pytest.mark.pypulseq
def test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples(monkeypatch):
    """An off-raster sequence (the samples come from `GradientSampler.sample` at the file
    times, chunk by chunk) of more than three chunks gives the result of one chunk, every
    field and every interval, `==`, and `num_samples` is 6002: 3 TRs of 2000 samples and a
    block of 1.5 samples, rounded up. A chunk that read the samples of the first chunk
    again, or a `num_samples` that rounds down, gives another result."""
    seq = gre_sequence(num_trs=3)
    _add_a_delay(seq, 1.5)  # off the raster
    snap = load(seq)
    hardware = hardware_for_peak(snap, 1.5)
    thresholds = (_LIMIT,)

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 10**9)
    reference = _compute(snap, hardware=hardware, thresholds_hz_per_t=thresholds)
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 1)  # a chunk of 1 bin
    got = _compute(snap, hardware=hardware, thresholds_hz_per_t=thresholds)

    assert got is not reference  # a new calculation, not the first result again
    assert reference.on_raster is False
    assert math.ceil(reference.num_samples / reference.bin_samples) > 3  # chunks of 1 bin
    assert reference.above[_LIMIT]
    assert got == reference
    assert reference.num_samples == 6002


# A bin of 615 samples at the 10 us raster. The intervals of `gre_sequence(num_trs=20)` are
# in samples 114 to 417 of each 2000, so none has a multiple of 500 (the chunk ends for the
# default bin) inside it, and `_chunk_across_an_interval` finds a size only with this bin.
_ACROSS_BIN_S = 10.0 / 1624


def _sample_range(interval: PnsInterval, dt: float) -> tuple[int, int]:
    """The first and the last sample of `interval`, from its edges `first * dt` and
    `(last + 1) * dt`."""
    return round(interval.start_s / dt), round(interval.end_s / dt) - 1


@pytest.mark.pypulseq
def test_a_sequence_below_the_limit_has_no_interval_and_one_above_it_has_some():
    """`above[_LIMIT]` is empty if and only if `peak_hz_per_t < _LIMIT`; the largest interval
    peak is `peak_hz_per_t`; the intervals are in time order, do not touch, and have the times
    and the count that their fields give."""
    snap = load(gre_sequence(num_trs=20))
    below = pns_levels(snap, thresholds_hz_per_t=(_LIMIT,), hardware=EXAMPLE_HW)
    assert below.peak_hz_per_t < _LIMIT
    assert below.above[_LIMIT] == ()

    levels = pns_levels(snap, hardware=hardware_for_peak(snap, 1.5), thresholds_hz_per_t=(_LIMIT,))
    dt = levels.dt_s
    assert levels.peak_hz_per_t >= _LIMIT
    assert len(levels.above[_LIMIT]) > 1
    assert max(i.peak_hz_per_t for i in levels.above[_LIMIT]) == levels.peak_hz_per_t
    for i in levels.above[_LIMIT]:
        first, last = _sample_range(i, dt)
        assert i.peak_hz_per_t >= _LIMIT
        assert i.start_s <= i.peak_time_s <= i.end_s
        assert i.num_samples == last - first + 1
    for a, b in itertools.pairwise(levels.above[_LIMIT]):
        assert a.end_s + dt / 2 < b.start_s  # at least one sample below the limit between them


@pytest.mark.pypulseq
def test_a_threshold_equal_to_the_peak_gives_an_interval():
    """A threshold that is exactly `peak_hz_per_t` gives one interval or more, and the
    peak of the largest one is the threshold: a total at the threshold is in an interval
    (`total >= threshold`)."""
    snap = load(gre_sequence())
    peak = pns_levels(snap, hardware=EXAMPLE_HW).peak_hz_per_t
    levels = pns_levels(snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=(peak,))
    assert list(levels.above) == [peak]
    assert len(levels.above[peak]) >= 1
    assert max(i.peak_hz_per_t for i in levels.above[peak]) == peak


@pytest.mark.pypulseq
def test_an_off_raster_sequence_that_ends_at_a_whole_number_of_samples_has_that_number():
    """An off-raster sequence (a trapezoid on x and four delays of 1.5 gradient-raster steps,
    which are 6 steps together) whose `end_s / dt` is above a whole number by float
    rounding only has that whole number of samples: `end_s / dt` is more than the whole
    number, and `(end_s - 1e-10) / dt` is not. The area of the trapezoid and the number of
    delays are such that the sum of the block durations of the written file has that rounding."""
    dt = SYSTEM.grad_raster_time
    seq = pp.Sequence(SYSTEM)
    trapezoid = pp.make_trapezoid(channel="x", area=500, system=SYSTEM)
    seq.add_block(trapezoid)
    for _ in range(4):
        _add_a_delay(seq, 1.5)
    snap = load(seq)
    end_s = sequence_index(snap).end_s
    whole = round(pp.calc_duration(trapezoid) / dt) + 6
    assert round(end_s / dt) == whole
    assert end_s / dt > whole
    assert (end_s - 1e-10) / dt <= whole  # a `num_samples` with no `- 1e-10` is `whole + 1`

    levels = pns_levels(snap, hardware=EXAMPLE_HW)
    assert levels.on_raster is False
    assert levels.num_samples == whole


@pytest.mark.pypulseq
def test_the_intervals_do_not_depend_on_chunk_samples(monkeypatch):
    """With chunks of 1 bin, with a chunk size that has an interval across the end of a
    chunk, and with the normal `_CHUNK_SAMPLES`, `pns_levels` gives the same result, every
    field exactly, including the intervals."""
    snap = load(gre_sequence(num_trs=20))
    hardware = hardware_for_peak(snap, 3.0)
    thresholds = (_LIMIT,)
    reference = _compute(
        snap, hardware=hardware, thresholds_hz_per_t=thresholds, bin_s=_ACROSS_BIN_S
    )
    dt, bin_samples = reference.dt_s, reference.bin_samples
    ranges = [_sample_range(i, dt) for i in reference.above[_LIMIT]]
    assert len(ranges) > 1

    across = _chunk_across_an_interval(reference.above[_LIMIT], reference)
    whole = bin_samples * (reference.num_samples // bin_samples + 10)
    assert not any(last // whole > first // whole for first, last in ranges)

    for chunk_samples in (1, across, whole):
        monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", chunk_samples)
        got = _compute(snap, hardware=hardware, thresholds_hz_per_t=thresholds, bin_s=_ACROSS_BIN_S)
        assert got is not reference  # a new calculation, not the first result again
        assert_levels_equal(got, reference, ignore=())
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", across)
    got = _compute(snap, hardware=hardware, thresholds_hz_per_t=thresholds, bin_s=_ACROSS_BIN_S)
    assert got is not reference
    assert got.above[_LIMIT] == reference.above[_LIMIT]


@pytest.mark.pypulseq
def test_an_interval_across_three_chunks_does_not_depend_on_chunk_samples(monkeypatch):
    """A threshold far below the peak gives an interval that covers three chunks or more of
    1 bin (the open run goes over more than one chunk end, with a chunk that is all above the
    threshold), and `above` of the chunks of 1 bin equals `above` of one chunk: the same
    intervals, each with the same start, end, peak, peak time and number of samples."""
    snap = load(gre_sequence(num_trs=3))
    thresholds = (1e-5 * _LIMIT,)

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 10**9)
    reference = _compute(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 1)  # a chunk of 1 bin
    got = _compute(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)

    assert got is not reference  # a new calculation, not the first result again
    chunk = reference.bin_samples
    intervals = reference.above[thresholds[0]]
    assert intervals
    spans = [
        last // chunk - first // chunk
        for first, last in (_sample_range(i, reference.dt_s) for i in intervals)
    ]
    assert max(spans) >= 2  # an interval has samples in three chunks or more
    assert got.above == reference.above


@pytest.mark.pypulseq
@pytest.mark.parametrize(
    ("build", "on_raster"),
    [(lambda: gre_sequence(num_trs=20), True), (_off_raster_sequence, False)],
    ids=["on raster", "off raster"],
)
def test_the_intervals_match_the_runs_of_the_totals(monkeypatch, build, on_raster):
    """The start, the end, the peak, the peak time and the number of samples of each
    interval equal the runs of `total >= _LIMIT` that plain NumPy and `itertools.groupby` find
    in the totals of the whole sequence, with the model run on it in one chunk."""
    snap = load(build())
    hardware = hardware_for_peak(snap, 1.5)
    totals = []

    def record(gwf, dt, hw_ns, state):
        result = _chunk_total(gwf, dt, hw_ns, state)
        totals.append(result[0])
        return result

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 10**9)
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._chunk_total", record)
    levels = _compute(snap, hardware=hardware, thresholds_hz_per_t=(_LIMIT,))
    assert levels.on_raster is on_raster
    total, dt = totals[0], levels.dt_s  # the rerun for the peak time records the same total
    assert total.shape[0] == levels.num_samples

    expected = []
    position = 0
    for above, group in itertools.groupby(total >= _LIMIT):
        length = len(list(group))
        if above:
            run = total[position : position + length]
            peak_sample = position + int(np.flatnonzero(run == run.max())[0])
            expected.append(
                PnsInterval(
                    start_s=position * dt,
                    end_s=(position + length) * dt,
                    peak_hz_per_t=float(run.max()),
                    peak_time_s=(peak_sample + 0.5) * dt,
                    num_samples=length,
                )
            )
        position += length
    assert len(expected) >= 1
    assert levels.above[_LIMIT] == tuple(expected)


@pytest.mark.pypulseq
def test_two_separate_intervals_are_in_time_order():
    """Two equal trapezoids on x with a 50 ms gap give two intervals, the first before the
    gap and the second after it, with hardware for which one trapezoid alone gives one
    interval."""
    gap = 50e-3
    trapezoid = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    duration = trapezoid.rise_time + trapezoid.flat_time + trapezoid.fall_time
    one = pp.Sequence(SYSTEM)
    one.add_block(trapezoid)
    two = pp.Sequence(SYSTEM)
    two.add_block(trapezoid)
    two.add_block(pp.make_delay(gap))
    two.add_block(trapezoid)
    one, two = load(one), load(two)
    hardware = hardware_for_peak(one, 1.02)  # only the larger hump of a trapezoid is above
    # the limit
    thresholds = (_LIMIT,)
    assert (
        len(pns_levels(one, hardware=hardware, thresholds_hz_per_t=thresholds).above[_LIMIT]) == 1
    )

    first, second = pns_levels(two, hardware=hardware, thresholds_hz_per_t=thresholds).above[_LIMIT]
    assert first.end_s < duration + gap / 2 < second.start_s
    assert second.start_s >= duration + gap  # the second trapezoid starts there
    assert first.peak_hz_per_t >= _LIMIT
    assert second.peak_hz_per_t >= _LIMIT


def _chunk_across_an_interval(intervals: tuple[PnsInterval, ...], levels: PnsLevels) -> int:
    """The first size of 1 to 19 bins, in samples, for which an interval of `intervals` has
    a sample in a chunk and the next sample in the next chunk."""
    ranges = [_sample_range(i, levels.dt_s) for i in intervals]
    for n in range(1, 20):
        chunk = n * levels.bin_samples
        if any(last // chunk > first // chunk for first, last in ranges):
            return chunk
    raise AssertionError("no chunk size of 1 to 19 bins has an interval across a chunk end")


@pytest.mark.pypulseq
def test_two_thresholds_in_one_call_give_the_runs_of_two_calls(monkeypatch):
    """`thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)` gives, for each threshold, the intervals of
    the call with that one threshold, and the other fields of the result do not change. The
    keys are in the order of `thresholds_hz_per_t` (and an `int` is the key of the same
    `float`). It holds with chunks of 1 bin and with a chunk size that has an interval of
    each threshold across a chunk end."""
    snap = load(gre_sequence(num_trs=20))
    hardware = hardware_for_peak(snap, 3.0)
    high_t, low_t = _LIMIT, 0.5 * _LIMIT
    thresholds = (high_t, low_t)
    single = {
        t: _compute(snap, hardware=hardware, thresholds_hz_per_t=(t,), bin_s=_ACROSS_BIN_S)
        for t in thresholds
    }
    high, low = single[high_t].above[high_t], single[low_t].above[low_t]
    assert len(high) > 1
    assert sum(i.num_samples for i in low) > sum(i.num_samples for i in high)
    assert low != high

    sizes = [None, 1]  # None: the _CHUNK_SAMPLES of the module
    sizes += [_chunk_across_an_interval(single[t].above[t], single[t]) for t in thresholds]
    boths = []
    for chunk_samples in sizes:
        if chunk_samples is not None:
            monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", chunk_samples)
        both = _compute(
            snap, hardware=hardware, thresholds_hz_per_t=thresholds, bin_s=_ACROSS_BIN_S
        )
        boths.append(both)
        assert list(both.above) == [high_t, low_t]
        for t in thresholds:
            assert both.above[t] == single[t].above[t]
        assert_levels_equal(both, single[high_t], ignore=("above",))
    assert len({id(both) for both in boths}) == len(sizes)  # each size ran the model again

    monkeypatch.undo()
    swapped = pns_levels(
        snap, hardware=hardware, thresholds_hz_per_t=(low_t, high_t), bin_s=_ACROSS_BIN_S
    )
    assert list(swapped.above) == [low_t, high_t]
    assert swapped.above[low_t] == low
    assert swapped.above[high_t] == high

    whole = round(_LIMIT)  # an int that is equal to the float `_LIMIT`
    assert float(whole) == _LIMIT
    keys = list(
        pns_levels(
            snap, hardware=hardware, thresholds_hz_per_t=(whole, low_t), bin_s=_ACROSS_BIN_S
        ).above
    )
    assert keys == [high_t, low_t]
    assert all(type(key) is float for key in keys)


@pytest.mark.pypulseq
@pytest.mark.parametrize(
    ("thresholds", "error"),
    [
        pytest.param([1.0], TypeError, id="list"),
        pytest.param(1.0, TypeError, id="float"),
        pytest.param(None, TypeError, id="none"),
        pytest.param((True,), TypeError, id="bool"),
        pytest.param((1.0, False), TypeError, id="bool second"),
        pytest.param(("1.0",), TypeError, id="string"),
        pytest.param((None,), TypeError, id="none element"),
        pytest.param((1j,), TypeError, id="complex"),
        pytest.param((math.nan,), ValueError, id="nan"),
        pytest.param((math.inf,), ValueError, id="inf"),
        pytest.param((10**400,), ValueError, id="int too large for a float"),
        pytest.param((0.0,), ValueError, id="zero"),
        pytest.param((-1.0,), ValueError, id="negative"),
        pytest.param((1.0, -math.inf), ValueError, id="minus inf"),
        pytest.param((1.0, 1.0), ValueError, id="equal floats"),
        pytest.param((1, 1.0), ValueError, id="equal int and float"),
        pytest.param((1.0, 0.5, 1.0), ValueError, id="equal, not next to each other"),
        pytest.param((np.float32(1.0), 1.0), ValueError, id="equal numpy float and float"),
    ],
)
def test_pns_levels_refuses_bad_thresholds_before_the_snapshot_type(thresholds, error):
    """`pns_levels` raises `TypeError` for `thresholds_hz_per_t` that is not a tuple or has
    an element that is a `bool` or not a real number, and `ValueError` for an element that
    is not finite, not above 0 or too large for a float, or for two elements that are equal
    as floats. It does so before the type of the first argument is checked: the first
    argument is a `pp.Sequence`, which is not a snapshot and would raise the `TypeError` that
    names `load`, and the error is still the one of the thresholds."""
    with pytest.raises(error, match="threshold"):
        pns_levels(spin_echo_sequence(), thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)


@pytest.mark.pypulseq
def test_pns_levels_takes_numpy_and_fraction_thresholds():
    """A threshold that is a NumPy real scalar or a `Fraction` (any `numbers.Real`, not a
    `bool`) is valid. The key of `above` is `float(t)`, and the result is that of the
    thresholds as floats. The calculation with the floats is a new one (`_compute`): a second
    `pns_levels` call with the same keys would give the kept object, and the test would
    compare that object with itself."""
    snap = load(spin_echo_sequence())
    thresholds = (np.float32(0.3 * _LIMIT), np.int64(12_345_678), Fraction(1, 3) * _LIMIT)
    keys = tuple(float(t) for t in thresholds)
    levels = pns_levels(snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=thresholds)
    assert list(levels.above) == list(keys)
    assert all(type(key) is float for key in levels.above)
    from_floats = _compute(snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=keys)
    assert from_floats is not levels
    assert_levels_equal(levels, from_floats, ignore=())


@pytest.mark.pypulseq
@pytest.mark.parametrize(
    ("bin_s", "error"),
    [
        pytest.param(True, TypeError, id="bool"),
        pytest.param(False, TypeError, id="false"),
        pytest.param("0.006", TypeError, id="string"),
        pytest.param(None, TypeError, id="none"),
        pytest.param((0.006,), TypeError, id="tuple"),
        pytest.param(1j, TypeError, id="complex"),
        pytest.param(math.nan, ValueError, id="nan"),
        pytest.param(math.inf, ValueError, id="inf"),
        pytest.param(-math.inf, ValueError, id="minus inf"),
        pytest.param(10**400, ValueError, id="int too large for a float"),
        pytest.param(0, ValueError, id="zero int"),
        pytest.param(0.0, ValueError, id="zero"),
        pytest.param(-1, ValueError, id="negative int"),
        pytest.param(-1e-3, ValueError, id="negative"),
    ],
)
def test_pns_levels_refuses_a_bad_bin_s_before_the_snapshot_type(bin_s, error):
    """`pns_levels` raises `TypeError` for a `bin_s` that is a `bool` or not a real number
    (a string, `None`, a tuple, a complex number) and `ValueError` for one that is not
    finite or not above 0 (NaN, infinity, an `int` too large for a float, 0, a negative
    value). It does so before the type of the first argument is checked: the first argument
    is a `pp.Sequence`, which is not a snapshot and would raise the `TypeError` that names
    `load`, and the error is still the one of `bin_s`."""
    with pytest.raises(error, match="bin_s"):
        pns_levels(spin_echo_sequence(), hardware=EXAMPLE_HW, bin_s=bin_s)


@pytest.mark.pypulseq
def test_pns_levels_takes_a_safe_hardware_and_gives_its_name_as_the_label():
    """`pns_levels(snap, hardware=h)` with a `SafeHardware` `h` gives `h.name` as
    `PnsLevels.hardware` and the fields of `h` as `PnsLevels.hw`, and `to_series` puts the
    name into the `meta` of `pns_total` as `hardware`. A `SafeHardware` with the same fields
    and another name gives that name, and the same levels otherwise."""
    snap = load(gre_sequence(num_trs=4))
    hardware = SafeHardware.from_namespace(safe_example_hw(), "LABEL")
    levels = pns_levels(snap, hardware=hardware)
    assert levels.hardware == "LABEL"
    assert levels.hw == _hw_dict(hardware)
    (total,) = PNS_SAFE_LEVELS.to_series(levels)
    assert total.meta["hardware"] == "LABEL"
    other = pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "OTHER"))
    assert other.hardware == "OTHER"
    assert_levels_equal(other, levels, ignore=("hardware",))


@pytest.mark.parametrize(
    "struct",
    [
        pytest.param(safe_example_hw, id="namespace"),
        pytest.param(lambda: SafeHardware.from_namespace(safe_example_hw()), id="safe-hardware"),
    ],
)
def test_pns_levels_refuses_a_pair_of_a_struct_and_a_label_with_the_name_of_from_namespace(struct):
    """`pns_levels` with the pair `(struct, label)` of the earlier interface, of a namespace in
    the form of pypulseq's `asc_to_hw` or of a `SafeHardware`, raises `TypeError` whose message
    names `SafeHardware.from_namespace`, which makes the `SafeHardware` of a struct and a label.
    This is so before the type of the first argument is checked: the first argument is a path,
    which is not a snapshot and would raise the `TypeError` that names `load`."""
    with pytest.raises(TypeError, match=re.escape("SafeHardware.from_namespace(")):
        pns_levels("sequence.seq", hardware=(struct(), "LABEL"))


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(spin_echo_sequence, id="sequence", marks=pytest.mark.pypulseq),
        pytest.param(lambda: "sequence.seq", id="path"),
    ],
)
def test_pns_levels_raises_type_error_that_names_load_for_a_non_snapshot(source):
    """`pns_levels` with good other arguments raises `TypeError` that names `load` for a
    `pp.Sequence` and for a path: the first argument is a `Snapshot`."""
    with pytest.raises(TypeError, match="load"):
        pns_levels(source(), hardware=EXAMPLE_HW)


@pytest.mark.pypulseq
def test_pns_levels_takes_an_int_or_a_numpy_bin_s():
    """A `bin_s` that is an `int` or a NumPy float (any real number, not a `bool`) is
    accepted and gives the levels of the equal `float` (the calculation of `bin_s=1.0`, with
    no keep), with `bin_s` the `float` 1.0."""
    snap = load(spin_echo_sequence())
    expected = _compute(snap, hardware=EXAMPLE_HW, bin_s=1.0)
    assert len(expected.level_min_hz_per_t) == 1  # a bin of 1 s holds the whole sequence
    for bin_s in (1, np.float64(1.0)):
        levels = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=bin_s)
        assert_levels_equal(levels, expected, ignore=())
        assert type(levels.bin_s) is float  # `==` does not tell 1 or numpy.float64 from 1.0


@pytest.mark.pypulseq
@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_asc_hardware_file_is_used_for_the_levels(write_gradient_asc, split):
    """`pns_levels` with `hardware_from_asc(path)` has the hardware name and the 8 kept
    fields of each axis of the gradient .asc file, and its stored level and summary then
    equal the call with the example hardware (`EXAMPLE_HW`) exactly: this .asc file
    encodes the example hardware's own numbers. This is so for the plain layout and for the
    layout of a scanner file (a main file that includes the PNS parameters)."""
    snap = load(spin_echo_sequence())
    path = write_gradient_asc(split=split)
    levels = pns_levels(snap, hardware=hardware_from_asc(path))
    assert levels.hardware == "MP_GPA_TEST"
    assert levels.hw == _hw_dict(safe_example_hw())

    default = pns_levels(snap, hardware=EXAMPLE_HW)
    assert np.array_equal(levels.level_min_hz_per_t, default.level_min_hz_per_t)
    assert np.array_equal(levels.level_max_hz_per_t, default.level_max_hz_per_t)
    assert levels.peak_hz_per_t == default.peak_hz_per_t
    assert levels.peak_time_s == default.peak_time_s


@pytest.mark.pypulseq
@pytest.mark.parametrize(
    "make_seq", [spin_echo_sequence, empty_sequence], ids=["spin_echo", "no_gradients"]
)
def test_the_arrays_of_the_levels_are_read_only(make_seq):
    """`level_min_hz_per_t` and `level_max_hz_per_t` are read-only, also for a sequence
    without gradients. A conversion to a new array works."""
    levels = pns_levels(load(make_seq()), hardware=EXAMPLE_HW)
    for a in (levels.level_min_hz_per_t, levels.level_max_hz_per_t):
        assert not a.flags.writeable
        with pytest.raises(ValueError):
            a *= 100
    # A conversion to a new array works, and the level stays as it was.
    before = levels.level_max_hz_per_t.copy()
    converted = levels.level_max_hz_per_t * 100
    assert converted.flags.writeable
    np.testing.assert_array_equal(levels.level_max_hz_per_t, before)


@pytest.mark.pypulseq
def test_levels_compare_by_value():
    """`==` compares the fields of two results by value, also with more than one bin (where
    the `__eq__` of `dataclasses` raises), a `PnsLevels` is not hashable, and a copy from `pickle`
    or `copy.deepcopy` is equal to the original, with `FrozenDict`s for its dicts (a
    `MappingProxyType` could not be pickled)."""
    thresholds = (_LIMIT, 0.5 * _LIMIT)
    levels = pns_levels(
        load(gre_sequence(num_trs=4)), thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW
    )
    assert levels.level_min_hz_per_t.size > 1
    other = pns_levels(
        load(gre_sequence(num_trs=4)), thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW
    )
    assert other is not levels
    assert other == levels
    for copied in (pickle.loads(pickle.dumps(levels)), copy.deepcopy(levels)):
        assert copied is not levels
        assert copied == levels
        assert all(isinstance(d, FrozenDict) for d in _every_dict(copied))

    changed = levels.level_max_hz_per_t.copy()
    changed[1] = np.nextafter(changed[1], np.float32(np.inf))
    assert dataclasses.replace(levels, level_max_hz_per_t=changed) != levels
    reordered = pns_levels(
        load(gre_sequence(num_trs=4)), thresholds_hz_per_t=thresholds[::-1], hardware=EXAMPLE_HW
    )
    assert reordered.above == levels.above  # a dict ignores the order of its keys
    assert reordered != levels  # the order of `above` counts
    assert levels != "levels"
    with pytest.raises(TypeError):
        hash(levels)


@pytest.mark.pypulseq
def test_another_safe_hardware_of_the_example_struct_gives_the_levels_of_the_example_hardware():
    """`hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL")` gives the levels of
    the call with `EXAMPLE_HW` (another `SafeHardware` object of the same fields, another
    name), exactly, except the hardware name, which is the label, for a sequence on the raster
    and for one off it."""
    for build in (spin_echo_sequence, _off_raster_sequence):
        snap = load(build())
        default = pns_levels(snap, hardware=EXAMPLE_HW)
        levels = pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL"))
        assert levels.hardware == "LABEL"
        assert_levels_equal(levels, default, ignore=("hardware",))


@pytest.mark.pypulseq
def test_the_levels_of_a_negated_waveform_are_equal():
    """The same sequence with each amplitude times -1 gives exactly equal levels, every field
    and every interval, with two thresholds that both have intervals: the model of `-g` is
    equal to the model of `g`, bit for bit."""
    positive = load(waveform_sequence(SYSTEM))
    negative = load(waveform_sequence(SYSTEM, sign=-1.0))
    hardware = hardware_for_peak(positive, 1.5)
    thresholds = (_LIMIT, 0.5 * _LIMIT)

    a = pns_levels(positive, hardware=hardware, thresholds_hz_per_t=thresholds)
    b = pns_levels(negative, hardware=hardware, thresholds_hz_per_t=thresholds)

    assert a.reason is None
    assert all(a.above[t] for t in thresholds)
    assert_levels_equal(a, b, ignore=())


@pytest.mark.pypulseq
def test_the_default_has_no_thresholds():
    """`pns_levels(snap, hardware=...)` without thresholds has `above == {}`, also for a
    sequence with a peak above the limit, and `thresholds_hz_per_t=()` gives the same result,
    every field."""
    snap = load(gre_sequence(num_trs=4))
    hardware = hardware_for_peak(snap, 1.5)

    for kwargs in ({"hardware": EXAMPLE_HW}, {"hardware": hardware}):
        default = pns_levels(snap, **kwargs)
        assert default.above == {}
        explicit = _compute(snap, thresholds_hz_per_t=(), **kwargs)
        assert explicit is not default  # a new calculation, not the kept result
        assert_levels_equal(default, explicit, ignore=())


def _every_dict(levels: PnsLevels) -> list[dict]:
    """The dicts of a `PnsLevels`: `hw`, each inner dict of `hw`, `axis_peaks_hz_per_t` and
    `above`."""
    return [levels.hw, *levels.hw.values(), levels.axis_peaks_hz_per_t, levels.above]


@pytest.mark.pypulseq
@pytest.mark.parametrize(
    "make_seq", [spin_echo_sequence, empty_sequence], ids=["spin_echo", "no_gradients"]
)
def test_the_dicts_of_the_levels_are_read_only_frozen_dicts(make_seq):
    """`hw` (the outer dict and each inner dict), `axis_peaks_hz_per_t` and `above` are
    `FrozenDict`s (and so `dict`s), also for a sequence without gradients: a change of an
    item, a new key, a deletion and `update` raise `TypeError`, and the dict stays as it
    was."""
    levels = pns_levels(load(make_seq()), hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,))
    dicts = _every_dict(levels)
    assert len(dicts) == 6  # hw, three inner dicts, the axis peaks, above
    for d in dicts:
        assert isinstance(d, FrozenDict)
        assert isinstance(d, dict)
        key = next(iter(d))
        before = dict(d)
        with pytest.raises(TypeError):
            d[key] = 0.0
        with pytest.raises(TypeError):
            d["new"] = 0.0
        with pytest.raises(TypeError):
            del d[key]
        with pytest.raises(TypeError):
            d.update({key: 0.0})
        assert d == before


@pytest.mark.pypulseq
def test_the_reason_without_gradients_is_the_object_of_seq_index():
    """`pns_levels.NO_GRADIENTS` and `grad_spectrum.NO_GRADIENTS` are `seq_index.NO_GRADIENTS`
    (one object), and the `reason` of a result is it."""
    assert NO_GRADIENTS is seq_index.NO_GRADIENTS
    assert grad_spectrum.NO_GRADIENTS is seq_index.NO_GRADIENTS
    levels = pns_levels(load(empty_sequence()), hardware=EXAMPLE_HW)
    assert levels.reason is seq_index.NO_GRADIENTS


@pytest.mark.pypulseq
def test_gradients_that_all_have_the_amplitude_zero_have_no_peak_time_and_one_run(monkeypatch):
    """A sequence whose only gradient is a trapezoid of the amplitude 0 (long enough for
    several chunks) has `reason` None, a peak of 0 and of each axis, `peak_time_s` None and
    an empty tuple for a threshold. The model runs once for each chunk and no second time
    for the peak time."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", amplitude=0, flat_time=20e-3, system=SYSTEM))
    snap = load(seq)
    calls = []

    def record(gwf, dt, hw_ns, state):
        calls.append(gwf.shape[0])
        return _chunk_total(gwf, dt, hw_ns, state)

    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._CHUNK_SAMPLES", 1)  # a chunk of 1 bin
    monkeypatch.setattr("pulseq_analysis.analyses.pns_levels._chunk_total", record)
    levels = _compute(snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,))
    monkeypatch.undo()

    assert levels.reason is None
    assert levels.peak_hz_per_t == 0.0
    assert levels.peak_time_s is None
    assert levels.axis_peaks_hz_per_t == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert levels.above == {_LIMIT: ()}
    num_chunks = math.ceil(levels.num_samples / levels.bin_samples)
    assert num_chunks > 3
    assert len(calls) == num_chunks
