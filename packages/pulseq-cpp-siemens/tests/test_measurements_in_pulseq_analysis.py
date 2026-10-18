"""The measurements of pulseq-analysis for the sequences that `spec` rejects, loaded through
`cpp-siemens`: `gradient_peaks`, `block_gradient_values`, `gradient_spectrum`, `pns_levels` and
`GradientSampler` against the oracle (the model of MATLAB Pulseq) and against values by hand, for
a gradient that ends above 0 before its block ends, a gradient that starts above 0 after a delay,
a delay off the gradient raster, and a gradient raster of 4 us with a block duration raster of
10 us. The random sequences are those of `random_gap_sequence(rng)`, made with such gradients:
`spec` rejects most of them, and reads a few seeds. The root tests of these measurements run
without the plugin, so they have the sequences that `spec` reads (with the random sequences of
`random_gap_sequence(rng, for_spec=True)`), and a test here with the name of a root test calls the
same check or helper of the root module (`check_*`).

The module is not collected without pulseq-analysis (`conftest.py`); the MATLAB oracle and the
helpers are those of the tests of pulseq-analysis (the root of this repository).
"""

import math
import warnings
from pathlib import Path

import numpy as np
import pypulseq as pp
import pytest
from gap_sequences import (
    DELAYED_RAMP_CASES,
    DT,
    ULP_EDGE_CASES,
    A,
    U,
    delayed_ramp_sequence,
    delayed_sequence,
    early_end_sequence,
    gap_of_1_5_raster_times_sequence,
    negated,
    short_arbitrary_sequence,
    short_gap_sequence,
    short_gap_to_0_sequence,
)
from oracles import grad_spectrum as spectrum_oracle
from oracles import waveform as oracle
from oracles.blocks import sequence_of
from pns_hardware import EXAMPLE_HW
from pulseq_cpp_siemens.interpreter import CppSiemens
from random_gaps import random_gap_sequence
from synthetic import (
    GAMMA_1H,
    RASTER_4US,
    RASTER_4US_JUNCTION,
    RASTER_4US_JUNCTION_TIME,
    SYSTEM,
    raster_4us_sequence,
)
from test_grad_peaks import (
    _MAX_STEP,
    _RASTER,
    _WRITER_REL,
    _assert_axis,
    _assert_block_values_agree_with_gradient_peaks,
    _assert_matches_oracle_on_windows,
    _end_step_sequence,
    _oracle_windows,
    check_a_window_gives_the_same_result_with_and_without_the_kept_data,
    check_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has,
    check_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end,
)
from test_grad_spectrum import _assert_matches_oracle as _assert_spectrum_matches_oracle
from test_played import QUARTER_Z, check_a_nan_of_one_block_is_credited_to_its_first_nan
from test_pns_levels import (
    _add_a_delay,
    check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples,
)
from test_sampling import (
    _A,
    _ANY_RANGE_CASES,
    _FROM_PARTS_NAMES,
    _MODEL_SEQUENCES,
    _REJECTED_BY_SPEC,
    _TIME_RANGE_NAMES,
    _WHOLE_CASES,
    _assert_samples_match,
    _model_sequence,
    _model_times,
    _name_of,
    _sample_ranges,
    check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot,
    check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid,
    check_block_samples_equal_the_oracle_for_the_whole_sequence,
    check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range,
)
from test_sampling import _AXES as _SAMPLER_AXES
from test_sampling import _assert_matches_oracle as _assert_sampler_matches_oracle
from test_series import (
    _PNS_CASES,
    check_the_series_of_gradient_spectrum_is_valid,
    check_the_series_of_pns_safe_levels_are_valid,
)

from pulseq_analysis.analyses import grad_spectrum, load
from pulseq_analysis.analyses.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.analyses.pns_levels import pns_levels
from pulseq_analysis.synth import ScannerSettingWarning, Session
from pulseq_analysis.synth.sampling import gradient_sampler, raster_block_lengths
from pulseq_analysis.synth.seq_index import sequence_index
from pulseq_analysis.synth.seq_utils import TIME_TOLERANCE
from pulseq_analysis.synth.snapshot import Snapshot

# ---- gradient_peaks and block_gradient_values (`test_grad_peaks.py`) ----


def test_junction_step_uses_the_gradient_raster_of_the_file_not_of_seq_system(tmp_path):
    """A sequence built with a 4 µs gradient raster, written to a file: the junction step is
    divided by 4 µs, the raster of the file, whether `load` reads the file or the sequence
    object. `spec` rejects a gradient raster of 4 µs with a block duration raster of 10 µs (it
    is neither a multiple nor a divisor of it); `cpp-siemens` reads it."""
    built = raster_4us_sequence()
    path = tmp_path / "raster_4us.seq"
    built.write(str(path))
    _block_a_id, block_b_id = built.block_events

    for source in (path, built):
        snap = load(source, "cpp-siemens")
        result = gradient_peaks(snap)

        # The file stores the amplitudes with fewer digits: 2e-5 relative in the value.
        assert snap.data.rasters.gradient == pytest.approx(RASTER_4US)
        assert result.axes["y"].max_slew_hz_per_m_per_s == pytest.approx(
            RASTER_4US_JUNCTION * GAMMA_1H, rel=1e-4
        )
        assert result.axes["y"].slew_block == block_b_id
        assert result.axes["y"].slew_time_s == pytest.approx(RASTER_4US_JUNCTION_TIME)


@pytest.mark.parametrize("early", [0.5 * TIME_TOLERANCE, 0.9 * TIME_TOLERANCE, DT])
def test_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end(early):
    """The last point of the extended trapezoid is `early` before the end of the sequence. The
    step to 0 is counted only when `early` is more than `TIME_TOLERANCE`, in the whole file, in
    the window that ends at the end of the sequence and in the window that ends
    `0.5 * TIME_TOLERANCE` before it
    (`check_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end`).
    `spec` rejects a gradient that ends at `A` before its block ends (`gradient.nonzero-end-align`)
    and, for an `early` that is not a multiple of the raster, a last point off the gradient
    raster; `cpp-siemens` plays it. The test of the same name of the root tests has the `early`
    of 0, which `spec` reads."""
    seq = _end_step_sequence(100e-6, early)
    check_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end(
        seq, load(seq, "cpp-siemens"), early
    )


def test_a_first_value_that_is_not_zero_after_a_delay_has_a_ramp_from_zero_in_its_block():
    """An x extended trapezoid with a delay (100 us) and a first value that is not 0
    (`add_block` accepts it), after a block that ends at 0 at 0.3 ms: the gap is 100 us, a long
    gap, so the gradient is 0 until half a raster time before the first point and then rises to
    the first value (the ramp from 0). There is no step. The ramp is the largest slew (twice the
    first value divided by the raster, more than any slope of the sequence), it starts at the
    block start plus the delay minus half a raster time, and it is credited to the block of the
    event. The junction of that block is 0. `spec` rejects a first value that is not 0 after a
    delay (`gradient.nonzero-start-delay`); `cpp-siemens` plays it."""
    seq = _delayed_junction_sequence()
    _block_a_id, block_b_id = seq.block_events
    snap = load(seq, "cpp-siemens")
    block_start = float(sequence_index(snap).start_s[1])
    assert block_start > 0.0

    result = gradient_peaks(snap)

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(2 * 0.9 * _MAX_STEP / _RASTER)
    assert result.axes["x"].slew_block == block_b_id
    assert result.axes["x"].slew_time_s == pytest.approx(
        block_start + _DELAY - _RASTER / 2, abs=1e-12
    )
    assert block_gradient_values(snap).junction_hz_per_m_per_s["x"][1] == 0.0


def test_window_that_cuts_the_ramp_from_zero_of_a_delayed_event_has_the_part_inside_it():
    """For the sequence of the test above, the ramp from 0 is from 395 us to 400 us. A window
    that starts in the middle of it has the second half: the slew is the same, and its time is the
    window start (the start of the cut). A window that ends at 395 us, the start of the ramp, does
    not have the ramp: its slew is the slope of the ramps of the first block. `spec` rejects the
    first value that is not 0 after a delay (`gradient.nonzero-start-delay`); `cpp-siemens`
    plays it."""
    seq = _delayed_junction_sequence()
    block_a_id, block_b_id = seq.block_events
    snap = load(seq, "cpp-siemens")
    index = sequence_index(snap)
    ramp_start = float(index.start_s[1]) + _DELAY - _RASTER / 2
    segment_slope = 0.3 * SYSTEM.max_grad / 100e-6  # the ramps of block 1
    assert segment_slope < 2 * 0.9 * _MAX_STEP / _RASTER

    cut = gradient_peaks(snap, range_s=(ramp_start + _RASTER / 4, index.end_s))
    assert cut.reason is None
    assert cut.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(2 * 0.9 * _MAX_STEP / _RASTER)
    assert cut.axes["x"].slew_block == block_b_id
    assert cut.axes["x"].slew_time_s == pytest.approx(ramp_start + _RASTER / 4, abs=1e-12)

    before_the_ramp = gradient_peaks(snap, range_s=(0.0, ramp_start))
    assert before_the_ramp.reason is None
    assert before_the_ramp.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(
        segment_slope, rel=_WRITER_REL
    )
    assert before_the_ramp.axes["x"].slew_block == block_a_id


def test_matches_oracle_on_synthetic_sequences():
    """`gradient_peaks` matches the oracle on the whole file, and on 12 windows that cut the
    gradients of `raster_4us_sequence` of `tests/synthetic.py` (`_oracle_windows`), the first half
    of the sequence among them. It has a gradient that is not 0 at a block junction. `spec`
    rejects it (a gradient raster of 4 µs with a block duration raster of 10 µs); `cpp-siemens`
    reads it. The test of the same name of the root tests has the synthetic sequences that `spec`
    reads."""
    snap = load(raster_4us_sequence(), "cpp-siemens")
    windows = _oracle_windows(snap, np.random.default_rng(20261007), 12)
    windows.append((0.0, sequence_index(snap).end_s / 2))
    _assert_matches_oracle_on_windows(snap, windows)


@pytest.mark.parametrize(
    "build",
    [delayed_sequence, early_end_sequence, short_gap_sequence],
    ids=["delayed", "early_end", "short_gap"],
)
def test_matches_oracle_on_the_sequences_of_the_oracle_tests(build):
    """`gradient_peaks` matches the oracle on the whole file and on 40 windows that cut the
    gradients, for each sequence of `gap_sequences.py` that `spec` rejects: the two sequences of
    pypulseq-issues 12 (a delay before a first value that is not 0,
    `gradient.nonzero-start-delay`, and an end that is not 0 before the end of its block,
    `gradient.nonzero-end-align`) and a short gap (an end that is not 0 before the end of its
    block); `cpp-siemens` plays them. The test of the same name of the root tests has the
    others."""
    seq = build()
    snap = load(seq, "cpp-siemens")
    windows = _oracle_windows(snap, np.random.default_rng(20261007), 40)
    _assert_matches_oracle_on_windows(snap, windows)


@pytest.mark.parametrize("seed", range(40))
def test_matches_oracle_on_random_sequences_with_ends_that_are_not_zero_next_to_gaps(seed):
    """40 random sequences (`random_gap_sequence`) with events that start and end at values
    that are not 0, with delays and delay blocks before and after them, so that the gaps between
    the events are zero (a step or none), short (a line) and long (a ramp to 0 and a ramp from 0),
    with a first value and a last value of the axis that are not 0: `gradient_peaks` matches the
    oracle, on the whole file and on 8 windows (`_oracle_windows`) that start and end at the
    ramp points, the points and the edges of the blocks. `spec` rejects such events
    (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`), in 37 of the 40 sequences;
    `cpp-siemens` plays them. The test of the same name of the root tests has the sequences of
    `random_gap_sequence(rng, for_spec=True)`, which `spec` reads."""
    rng = np.random.default_rng(seed)
    seq = random_gap_sequence(rng)
    snap = load(seq, "cpp-siemens")
    _assert_matches_oracle_on_windows(snap, _oracle_windows(snap, rng, 8))


_DELAY = 100e-6  # the delay of the extended trapezoid of `_delayed_junction_sequence`


def _delayed_junction_sequence() -> pp.Sequence:
    """An x trapezoid that ends at 0, then an x extended trapezoid with a delay and a first
    value that is not 0 (`add_block` accepts it): the step from 0 to the first value is at
    the end of the delay. The step is 90% of the largest step, larger than every slope here
    (block 1 has ramps of 100 us)."""
    step = 0.9 * _MAX_STEP
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_trapezoid(
            channel="x",
            amplitude=0.3 * SYSTEM.max_grad,
            rise_time=100e-6,
            flat_time=100e-6,
            system=SYSTEM,
        )
    )
    delayed = pp.make_extended_trapezoid(
        channel="x", times=[0.0, 100e-6, 200e-6], amplitudes=[step, step, 0.0], system=SYSTEM
    )
    delayed.delay = _DELAY
    seq.add_block(delayed)
    return seq


_AGREEMENT_SEQUENCES = [
    raster_4us_sequence,
    _delayed_junction_sequence,
    lambda: delayed_sequence(),
    lambda: early_end_sequence(),
    lambda: short_gap_sequence(),
    *(lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)) for seed in range(8)),
]


_AGREEMENT_IDS = [
    "raster_4us",
    "delayed_junction",
    "oracle_delayed",
    "oracle_early_end",
    "oracle_short_gap",
    *(f"random_gap_{seed}" for seed in range(8)),
]


@pytest.mark.parametrize("make_seq", _AGREEMENT_SEQUENCES, ids=_AGREEMENT_IDS)
def test_block_gradient_values_agree_with_gradient_peaks_for_the_whole_file(make_seq):
    """The maxima of `block_gradient_values` over the blocks are the whole-file values of
    `gradient_peaks`, with the same block and time
    (`_assert_block_values_agree_with_gradient_peaks`). `spec` rejects the sequences
    (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`, and a gradient raster of 4 µs
    with a block duration raster of 10 µs, `definitions.raster-commensurate`); `cpp-siemens`
    plays them. The test of the same name of the root tests has the sequences that `spec`
    reads."""
    _assert_block_values_agree_with_gradient_peaks(load(make_seq(), "cpp-siemens"))


def test_block_gradient_values_use_the_gradient_raster_of_the_file_not_of_seq_system(tmp_path):
    """A sequence built with a 4 µs gradient raster, written to a file: the junction step of each
    block that `block_gradient_values` gives is divided by 4 µs, the raster of the file, so it is
    `RASTER_4US_JUNCTION` (60 T/m/s) in block 2 and 0 in block 1, whether `load` reads the file or
    the sequence object. `spec` rejects a gradient raster of 4 µs with a block duration raster of
    10 µs (it is neither a multiple nor a divisor of it); `cpp-siemens` reads it."""
    built = raster_4us_sequence()
    path = tmp_path / "raster_4us.seq"
    built.write(str(path))

    for source in (path, built):
        snap = load(source, "cpp-siemens")
        junction = block_gradient_values(snap).junction_hz_per_m_per_s

        assert junction["y"][0] == 0.0
        # The file stores the amplitudes with fewer digits: 2e-5 relative in the value.
        assert junction["y"][1] == pytest.approx(RASTER_4US_JUNCTION * GAMMA_1H, rel=1e-4)
        assert not junction["x"].any()
        assert not junction["z"].any()


@pytest.mark.parametrize(
    "make_seq",
    [_delayed_junction_sequence, lambda: random_gap_sequence(np.random.default_rng(5))],
    ids=["delayed_junction", "random_gap_5"],
)
def test_a_window_gives_the_same_result_with_and_without_the_kept_data(make_seq):
    """`check_a_window_gives_the_same_result_with_and_without_the_kept_data` through
    `cpp-siemens`, for sequences that `spec` rejects (`gradient.nonzero-start-delay`,
    `gradient.nonzero-end-align`). The test of the same name of the root tests has the sequences
    that `spec` reads."""
    check_a_window_gives_the_same_result_with_and_without_the_kept_data(make_seq(), "cpp-siemens")


@pytest.mark.parametrize(
    ("build", "vector_time_2"),
    [(delayed_sequence, 200e-6), (early_end_sequence, 300e-6)],
    ids=["delayed", "early_end"],
)
def test_the_values_of_each_sequence_of_pypulseq_issue_12_are_those_of_matlab_pulseq(
    build, vector_time_2
):
    """The two sequences of pypulseq-issues 12 (a first value A after a delay, and an end at A
    before the end of its block), each with a gap of 100 us, have the polyline of MATLAB Pulseq: at
    0, 100, 200, 205, 295, 300 and 400 us the values 0, A, A, 0, 0, A and 0, with A half of
    `max_slew * grad_raster_time`. The whole file has the peak A at 100 us in block 1, and the
    slew `max_slew` (a ramp of A in half a raster time) at 200 us in block 1, or at 295 us in block
    2 (the two ramps have one slope, up to the rounding of the times). The RMS is A times
    sqrt(170 / 400): the integral of the square is (100/3 + 100 + 5/3 + 5/3 + 100/3) us times
    A^2, over 400 us. The vector peak is A, at 100 us in block 1. The values of each block: the peak
    A in both blocks, the slew `max_slew` in both (the ramp to 0 is in block 1, the ramp from 0 in
    block 2), the junction 0 in both (a long gap has ramps and no junction), and the vector peak A
    in both blocks. Block 2 has it from the first time that has a value of A on the side of block
    2: at 200 us for the first sequence (block 2 starts at 200 us, where the ramp to 0 starts) and
    at 300 us for the second (block 1 lasts to 300 us, and the value after 300 us is in block 2).
    `spec` rejects both sequences (`gradient.nonzero-start-delay`,
    `gradient.nonzero-end-align`); `cpp-siemens` plays them."""
    seq = build()
    block_1, block_2 = seq.block_events

    snap = load(seq, "cpp-siemens")
    result = gradient_peaks(snap)

    axis = result.axes["x"]
    assert axis.peak_hz_per_m == pytest.approx(A, rel=1e-9)
    assert axis.peak_time_s == pytest.approx(100e-6, rel=0, abs=1e-12)
    assert axis.peak_block == block_1
    assert axis.max_slew_hz_per_m_per_s == pytest.approx(SYSTEM.max_slew, rel=1e-9)
    assert (axis.slew_time_s, axis.slew_block) in [
        (pytest.approx(200e-6, rel=0, abs=1e-12), block_1),
        (pytest.approx(295e-6, rel=0, abs=1e-12), block_2),
    ]
    assert axis.rms_hz_per_m == pytest.approx(A * math.sqrt(170 / 400), rel=1e-9)
    assert result.vector_peak_hz_per_m == pytest.approx(A, rel=1e-9)
    assert result.vector_peak_time_s == pytest.approx(100e-6, rel=0, abs=1e-12)
    assert result.vector_peak_block == block_1
    for other in ("y", "z"):
        assert result.axes[other].peak_block is None
        assert result.axes[other].slew_block is None

    values = block_gradient_values(snap)
    np.testing.assert_allclose(values.peak_hz_per_m["x"], [A, A], rtol=1e-9)
    np.testing.assert_allclose(values.peak_time_s["x"], [100e-6, 300e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(values.slew_hz_per_m_per_s["x"], [SYSTEM.max_slew] * 2, rtol=1e-9)
    np.testing.assert_allclose(values.slew_time_s["x"], [200e-6, 295e-6], rtol=0, atol=1e-12)
    np.testing.assert_array_equal(values.junction_hz_per_m_per_s["x"], [0.0, 0.0])
    np.testing.assert_allclose(values.vector_peak_hz_per_m, [A, A], rtol=1e-9)
    np.testing.assert_allclose(
        values.vector_peak_time_s, [100e-6, vector_time_2], rtol=0, atol=1e-12
    )


def test_a_short_gap_gives_a_line_credited_to_the_later_block():
    """The first gradient goes from 0 to 3 U in 100 us, and its block lasts 110 us. The second
    block starts at 2 U and goes to 0 in 100 us: the gap is one raster time, so the gradient is the
    line from 3 U at 100 us to 2 U at 110 us, with the slope U / 10 us = U / DT. It is the slew of
    the whole file, from 100 us, in block 2 (more than the 3e8 of the rise and the 2e8 of the
    fall). The peak is 3 U at 100 us in block 1, and the RMS is U times sqrt(149/63): the integral
    of the square is (300 + 19/3 x 10 + 400/3) U^2 us, over 210 us. The junction of block 2 is the
    slope of the line, and the slew of the blocks is that of the rise (3 U / 100 us) and of the
    fall (2 U / 100 us).

    A window from 105 to 150 us has the second half of the line, then 40 us of block 2. The
    peak is 2.5 U, the value of the line at 105 us, credited to block 2 (the block of the line)
    at 105 us, and the slew is that of the line, from 105 us in block 2. The vector peak has the
    same value and time, in block 1: the block that has 105 us. `spec` rejects a gradient that
    ends at 3 U before its block ends (`gradient.nonzero-end-align`); `cpp-siemens` plays it."""
    seq = short_gap_sequence()
    block_1, block_2 = seq.block_events

    snap = load(seq, "cpp-siemens")
    _assert_axis(
        gradient_peaks(snap).axes["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=block_1,
        slew=U / DT,
        slew_time=100e-6,
        slew_block=block_2,
        rms=U * math.sqrt(149 / 63),
    )
    values = block_gradient_values(snap)
    np.testing.assert_allclose(values.junction_hz_per_m_per_s["x"], [0.0, U / DT], rtol=1e-9)
    np.testing.assert_allclose(
        values.slew_hz_per_m_per_s["x"], [3 * U / 100e-6, 2 * U / 100e-6], rtol=1e-9
    )
    np.testing.assert_allclose(values.peak_hz_per_m["x"], [3 * U, 2 * U], rtol=1e-9)
    np.testing.assert_allclose(values.peak_time_s["x"], [100e-6, 110e-6], rtol=0, atol=1e-12)

    window = gradient_peaks(snap, range_s=(105e-6, 150e-6))
    rms = U * math.sqrt(
        (5 * (2.5**2 + 2.5 * 2 + 2**2) / 3 + 40 * (2**2 + 2 * 1.2 + 1.2**2) / 3) / 45
    )
    _assert_axis(
        window.axes["x"],
        peak=2.5 * U,
        peak_time=105e-6,
        peak_block=block_2,
        slew=U / DT,
        slew_time=105e-6,
        slew_block=block_2,
        rms=rms,
    )
    assert window.vector_peak_hz_per_m == pytest.approx(2.5 * U, rel=1e-9)
    assert window.vector_peak_time_s == pytest.approx(105e-6, rel=0, abs=1e-12)
    assert window.vector_peak_block == block_1


def test_a_window_edge_next_to_a_block_edge_credits_the_vector_peak_by_time():
    """`raster_4us_sequence`: block 1 is the y gradient that rises to the top in 400 us and stays
    there to 800 us, and block 2 starts at a step down from the top (to 15.76 mT/m) at 800 us.
    A window that starts 1 ps before 800 us has the top at its start (the flat top that it cuts).
    The block of the peak of the axis is block 1, the block of the flat segment. The vector peak is
    credited to the block that has the time of the window start, seen from the side where the
    value is (after the start), within `TIME_TOLERANCE`: block 2 starts 1 ps after the window
    start, so block 2 has the top. A window that starts 1 ps after 800 us has the value after the
    step at its start, 15.76 mT/m, in block 2, for the peak of the axis and for the vector peak.
    `spec` rejects a gradient raster of 4 µs with a block duration raster of 10 µs; `cpp-siemens`
    reads it."""
    seq = raster_4us_sequence()
    block_1, block_2 = seq.block_events
    snap = load(seq, "cpp-siemens")
    index = sequence_index(snap)
    end_s, edge = float(index.end_s), float(index.start_s[1])
    top, step_to = 16e-3 * GAMMA_1H, 15.76e-3 * GAMMA_1H

    before_the_step = gradient_peaks(snap, range_s=(edge - 1e-12, end_s))
    assert before_the_step.axes["y"].peak_hz_per_m == pytest.approx(top, rel=_WRITER_REL)
    assert before_the_step.axes["y"].peak_block == block_1
    assert before_the_step.vector_peak_hz_per_m == pytest.approx(top, rel=_WRITER_REL)
    assert before_the_step.vector_peak_time_s == pytest.approx(edge - 1e-12, rel=0, abs=1e-15)
    assert before_the_step.vector_peak_block == block_2

    after_the_step = gradient_peaks(snap, range_s=(edge + 1e-12, end_s))
    assert after_the_step.axes["y"].peak_hz_per_m == pytest.approx(step_to, rel=_WRITER_REL)
    assert after_the_step.axes["y"].peak_block == block_2
    assert after_the_step.vector_peak_hz_per_m == pytest.approx(step_to, rel=_WRITER_REL)
    assert after_the_step.vector_peak_time_s == pytest.approx(edge + 1e-12, rel=0, abs=1e-15)
    assert after_the_step.vector_peak_block == block_2


def test_the_gap_rule_uses_the_gradient_raster_of_the_file_not_of_seq_system(tmp_path):
    """A sequence built with a 4 us gradient raster: block 1 has a gradient from 0 to V in 400 us
    and its block lasts 410 us, and block 2 has a gradient from W to 0 in 400 us. The gap is 10
    us, which is more than one raster time of 4 us, so it is a long gap: the ramp to 0 is
    V / 2 us in block 1, the ramp from 0 is W / 2 us in block 2, and the junction of block 2 is 0.
    (With the 10 us of `seq.system`, the gap would be a short gap: a line, and a junction in block
    2.) The sequence object and the file that it is written to give the same values, and match
    the oracle. `spec` rejects the raster of 4 us with a block duration raster of 10 us
    (`definitions.raster-commensurate`), and a gradient that ends at V before its block ends
    (`gradient.nonzero-end-align`); `cpp-siemens` plays it."""
    system = pp.Opts(
        max_grad=100,
        grad_unit="mT/m",
        max_slew=200,
        slew_unit="T/m/s",
        grad_raster_time=RASTER_4US,
    )
    v, w = 0.4e-3 * GAMMA_1H, 0.3e-3 * GAMMA_1H
    built = pp.Sequence(system)
    built.add_block(
        pp.make_extended_trapezoid(
            channel="x", times=[0.0, 400e-6], amplitudes=[0.0, v], system=system
        ),
        pp.make_delay(410e-6),
    )
    built.add_block(
        pp.make_extended_trapezoid(
            channel="x", times=[0.0, 400e-6], amplitudes=[w, 0.0], system=system
        )
    )
    path = tmp_path / "gap_4us.seq"
    built.write(str(path))

    for source in (path, built):
        snap = load(source, "cpp-siemens")
        assert snap.data.rasters.gradient == pytest.approx(RASTER_4US)
        values = block_gradient_values(snap)
        # The file stores the amplitudes with fewer digits: 2e-5 relative in the value.
        np.testing.assert_array_equal(values.junction_hz_per_m_per_s["x"], [0.0, 0.0])
        assert values.slew_hz_per_m_per_s["x"][0] == pytest.approx(v / 2e-6, rel=1e-4)
        assert values.slew_time_s["x"][0] == pytest.approx(400e-6, rel=0, abs=1e-12)
        assert values.slew_hz_per_m_per_s["x"][1] == pytest.approx(w / 2e-6, rel=1e-4)
        assert values.slew_time_s["x"][1] == pytest.approx(410e-6 - 2e-6, rel=0, abs=1e-12)
        _assert_matches_oracle_on_windows(snap, [(300e-6, 405e-6), (401e-6, 700e-6)])


_BLOCK_VALUE_SEQUENCES = [
    raster_4us_sequence,
    lambda: delayed_sequence(),
    lambda: early_end_sequence(),
    lambda: short_gap_sequence(),
    *(lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)) for seed in range(14)),
]


_BLOCK_VALUE_IDS = [
    "raster_4us",
    "oracle_delayed",
    "oracle_early_end",
    "oracle_short_gap",
    *(f"random_gap_{seed}" for seed in range(14)),
]


@pytest.mark.parametrize("make_seq", _BLOCK_VALUE_SEQUENCES, ids=_BLOCK_VALUE_IDS)
def test_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has(make_seq):
    """`check_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has` for
    sequences that `spec` rejects (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`,
    and a gradient raster of 4 µs with a block duration raster of 10 µs,
    `definitions.raster-commensurate`); `cpp-siemens` plays them. 1 of the 14 sequences of
    `random_gap_sequence` (seed 8) is one that `spec` reads. The test of the same name of the
    root tests has the sequences that `spec` reads."""
    check_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has(
        load(make_seq(), "cpp-siemens")
    )


# ---- gradient_spectrum (`test_grad_spectrum.py`) ----


_SPECTRUM_GAP_SEQUENCES = {
    "short_gap": short_gap_sequence,
    "issue_12_delayed": delayed_sequence,
    "issue_12_early_end": early_end_sequence,
    "gap_of_1_5_raster_times": gap_of_1_5_raster_times_sequence,
    "short_gap_to_0": short_gap_to_0_sequence,
}
# The sequences of `gap_sequences` with every amplitude negated (the gap rules do not depend on
# the sign).
_SPECTRUM_GAP_SEQUENCES |= {
    f"negated_{name}": (lambda build=_SPECTRUM_GAP_SEQUENCES[name]: negated(build()))
    for name in ("short_gap", "issue_12_delayed", "issue_12_early_end")
}
# The random sequences of `random_gaps` (random signs, zero, short and long gaps).
_SPECTRUM_GAP_SEQUENCES |= {
    f"random_gaps_{seed}": (lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)))
    for seed in range(8)
}


@pytest.mark.parametrize(
    "build", _SPECTRUM_GAP_SEQUENCES.values(), ids=_SPECTRUM_GAP_SEQUENCES.keys()
)
def test_a_gap_with_ends_that_are_not_0_gives_the_spectrum_of_the_oracle_waveform(build):
    """The spectrum of a sequence with a short gap, a long gap, or a step at a junction, and
    ends that are not 0 next to it, equals the spectrum that the oracle calculates from
    `oracle.sample` (the model of MATLAB Pulseq), for the sequences that `spec` rejects.
    pypulseq's `calculate_gradient_spectrum` draws a line across a long gap
    (pypulseq-issues 12) and gives another spectrum, so it is not the reference here. The
    sequences are the hand sequences of `gap_sequences` that `spec` rejects (a short gap and the
    two sequences of pypulseq-issues 12), each also with every amplitude negated, a gap of 1.5
    raster times between two values that are not 0, a short gap from a value that is not 0 to 0,
    and the 8 random sequences of `random_gaps` (seeds 0 to 7). The oracle reads the gradients as
    the snapshot plays them (`sequence_of`). The test of the same name of the root tests has the
    sequences that `spec` reads."""
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`), a delay off the gradient raster (`raster.gradient-delay`) and
    # a gradient that starts above 0 after a delay (`gradient.nonzero-start-delay`);
    # `cpp-siemens` plays them.
    snap = load(build(), "cpp-siemens")
    _assert_spectrum_matches_oracle(
        grad_spectrum.gradient_spectrum(snap),
        spectrum_oracle.gradient_spectrum(sequence_of(snap)),
        sequence_of(snap),
    )


# ---- pns_levels (`test_pns_levels.py`) ----


def _two_axis_short_gap_sequence() -> pp.Sequence:
    """Two blocks of 110 us (11 samples) on x and y. Each block has an event that ends at a
    value that is not 0 at 100 us, 10 us (one raster time) before the end of the block, and
    the event of the next block starts at a value that is not 0. The gap on each axis is
    short. The first value of x is 3 U at the start of the sequence, and the last value of x
    is 5 U at the end of the last event (a step to 0 there). U = 1e4 Hz/m."""
    unit = 1e4

    def event(channel, amplitudes):
        return pp.make_extended_trapezoid(
            channel, times=[0.0, 100e-6], amplitudes=np.array(amplitudes) * unit, system=SYSTEM
        )

    seq = pp.Sequence(SYSTEM)
    seq.add_block(event("x", [3, 4]), event("y", [0, 2]), pp.make_delay(110e-6))
    seq.add_block(event("x", [2, 5]), event("y", [1, 0]), pp.make_delay(110e-6))
    return seq


def _off_raster(build):
    """`build` with a last block of 1.5 raster times, which is not on the raster, so that
    `pns_levels` samples the whole sequence with `GradientSampler.sample`."""

    def build_off_raster() -> pp.Sequence:
        seq = build()
        _add_a_delay(seq, 1.5)
        return seq

    return build_off_raster


_PNS_GAP_SEQUENCES = {
    "short_gap_two_axes": _two_axis_short_gap_sequence,
    "issue_12_delayed": lambda: delayed_sequence(),
    "issue_12_early_end": lambda: early_end_sequence(),
    "gap_of_1_5_raster_times": lambda: gap_of_1_5_raster_times_sequence(),
    "short_gap_to_0": lambda: short_gap_to_0_sequence(),
}
# The sequences of `gap_sequences` with every amplitude negated (the gap rules do not depend on
# the sign).
_PNS_GAP_SEQUENCES |= {
    f"negated_{name}": (lambda build=build: negated(build()))
    for name, build in {
        "short_gap": short_gap_sequence,
        "issue_12_delayed": delayed_sequence,
        "issue_12_early_end": early_end_sequence,
    }.items()
}
# The sequences of the edges of `block_samples`: the last point of an event at a sample time
# (`DELAYED_RAMP_CASES` and `ULP_EDGE_CASES`) and a step inside one event (`short_arbitrary_sequence`).
_PNS_GAP_SEQUENCES |= {
    "delayed_ramp_" + "_".join(map(str, case)): (lambda case=case: delayed_ramp_sequence(*case))
    for case in DELAYED_RAMP_CASES + ULP_EDGE_CASES
}
_PNS_GAP_SEQUENCES["short_arbitrary"] = lambda: short_arbitrary_sequence()
# The random sequences of `random_gaps` (random signs, zero, short and long gaps).
_PNS_GAP_SEQUENCES |= {
    f"random_gaps_{seed}": (lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)))
    for seed in range(8)
}
# The same gaps off the raster: the new sequences above, each with a last block that is not on the
# raster.
_PNS_GAP_SEQUENCES |= {
    f"{name}_off_raster": _off_raster(_PNS_GAP_SEQUENCES[name])
    for name in ["gap_of_1_5_raster_times", "short_gap_to_0", "negated_short_gap"]
    + [f"random_gaps_{seed}" for seed in range(8)]
}


@pytest.mark.parametrize("name", _PNS_GAP_SEQUENCES)
def test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
    name,
):
    """For a sequence that `spec` rejects with a short gap or a long gap and ends that are not 0
    next to it (and the first value and the last value of an axis that are not 0), `pns_levels`
    is the SAFE model of the oracle samples
    (`check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`),
    on the raster and, for the names that end in `_off_raster`, off it. The sequences are the two
    sequences of pypulseq-issues 12 of `gap_sequences`, each also with every amplitude negated,
    `short_gap_sequence` negated, a short gap on two axes, a gap of 1.5 raster times between two
    values that are not 0, a short gap from a value that is not 0 to 0, and the 8 random sequences
    of `random_gaps` (seeds 0 to 7). Three of them (`gap_of_1_5_raster_times`, `short_gap_to_0`
    and `negated_short_gap`) and the random ones are also run with a last block that is not on the
    raster. The 14 ramps of `DELAYED_RAMP_CASES` and `ULP_EDGE_CASES` (a delay of half a raster
    time behind filler blocks, review 1.3) and the arbitrary gradient of 3 samples of
    `short_arbitrary_sequence` (review 1.4) have the last sample of an event at a sample time. The
    test of the same name of the root tests has the sequences that `spec` reads."""
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`), a delay off the gradient raster (`raster.gradient-delay`) and
    # a gradient that starts above 0 after a delay (`gradient.nonzero-start-delay`);
    # `cpp-siemens` plays them.
    check_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
        load(_PNS_GAP_SEQUENCES[name](), "cpp-siemens"), on_raster=not name.endswith("_off_raster")
    )


# ---- GradientSampler (`test_sampling.py`) ----


def _rejected_by_spec(cases: list) -> list:
    """The cases of `cases` whose sequence `spec` rejects (`_REJECTED_BY_SPEC`)."""
    return [case for case in cases if _name_of(case) in _REJECTED_BY_SPEC]


def _load_model(name: str) -> Snapshot:
    """The snapshot of the sequence `name` of `_MODEL_SEQUENCES`, read by `cpp-siemens`."""
    return load(_model_sequence(name), "cpp-siemens")


@pytest.mark.parametrize("name", _rejected_by_spec(list(_MODEL_SEQUENCES)))
def test_sample_equals_the_oracle_for_the_whole_sequence(name):
    """`sample` equals the oracle (the model of MATLAB Pulseq) on a grid across each
    sequence of the model that `spec` rejects, with times at the points, the steps and the
    ramps."""
    snap = _load_model(name)
    _assert_sampler_matches_oracle(snap, _model_times(snap))


@pytest.mark.parametrize("name", _rejected_by_spec(_TIME_RANGE_NAMES))
def test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(name):
    """Each time range of a grid of times, for the sequences of the model that `spec` rejects
    (`check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`)."""
    check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(_load_model(name))


@pytest.mark.parametrize(("name", "divisor"), _rejected_by_spec(_WHOLE_CASES))
def test_block_samples_equals_the_oracle_for_the_whole_sequence(name, divisor):
    """`block_samples` of the whole sequence equals `oracle.block_samples` for each axis, at the
    gradient raster and at finer rasters, for the sequences of the model that `spec` rejects
    (`check_block_samples_equal_the_oracle_for_the_whole_sequence`)."""
    check_block_samples_equal_the_oracle_for_the_whole_sequence(_load_model(name), divisor)


@pytest.mark.parametrize(("name", "divisor"), _rejected_by_spec(_ANY_RANGE_CASES))
def test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range(
    name, divisor
):
    """Each range of blocks, and each range of samples, of `block_samples` equals the same
    samples of the oracle, and the same slice of the whole range exactly, for the sequences of
    the model that `spec` rejects
    (`check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range`)."""
    check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range(
        _load_model(name), divisor
    )


@pytest.mark.parametrize("name", _rejected_by_spec(_FROM_PARTS_NAMES))
def test_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot(name):
    """`GradientSampler._from_parts` gives, bit for bit, the values of `gradient_sampler(snap)`,
    for the sequences that `spec` rejects
    (`check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`)."""
    check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot(_load_model(name))


def test_a_ramp_to_0_and_a_ramp_from_0_cross_a_long_gap_by_hand():
    """`_off_raster_events_sequence` at times in the two ramps (half a raster time long, at 3.3
    to 3.8 and 8.2 to 8.7 raster times), with hand values, and 0 between the ramps and after
    the last point."""
    snap = _load_model("off_raster_events")
    t = _RASTER * np.array([3.3, 3.5, 3.8, 5.0, 8.2, 8.5, 8.7, 11.7, 12.0])
    expected = _A * np.array([1.0, 0.6, 0.0, 0.0, 0.0, 0.3, 0.5, 0.0, 0.0])
    got = gradient_sampler(snap).sample("x", t)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-9 * _A)


def test_hand_made_ramp_and_no_event_block():
    """A hand-made sequence, not one of the `synthetic.py` builders: block 0 has a
    gradient on x that ramps from 0 to a nonzero value and stops there (unlike an
    ordinary trapezoid, whose amplitude is 0 at both ends of the event, this event's
    own last point is not zero), inside a block made longer than the ramp by a second
    gradient on z that fills the rest of the block; block 1 is a delay, with no
    gradient event on any axis. The expected values are computed by hand from the
    linear-interpolation rule of the docstring, not read from `sample` or `pns_lanes.js`.
    """
    dt = SYSTEM.grad_raster_time
    n_ramp = 4
    n_block = 7
    amp = 1000.0  # Hz/m
    rise = n_ramp * dt
    gx = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, amp]),
        times=np.array([0.0, rise]),
        system=SYSTEM,
    )
    # A trapezoid on z occupying the whole block, so the block is longer than gx's own
    # event: the samples after gx's last point (at `rise`) must be 0, even though that
    # last point's own value (amp) is not 0.
    gz = pp.make_trapezoid(channel="z", duration=n_block * dt, area=1.0, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx, gz)
    seq.add_block(pp.make_delay(n_block * dt))
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`); `cpp-siemens` plays it.
    sampler = gradient_sampler(load(seq, "cpp-siemens"))

    j = np.arange(n_block, dtype=np.float64)
    t = (j + 0.5) * dt
    expected_gx_block0 = np.where(t < rise, amp * t / rise, 0.0)
    expected_gx = np.concatenate([expected_gx_block0, np.zeros(n_block)])
    got_gx = sampler.block_samples("x", 0, 2, dt)
    # A division (the linear-interpolation formula) makes exact equality unlikely: the
    # implementation and this test compute the ramp fraction with a different order of
    # floating-point operations.
    np.testing.assert_allclose(got_gx, expected_gx, rtol=1e-12, atol=1e-12 * amp)

    # gy has no event anywhere in the file: 0 for every sample of both blocks.
    got_gy = sampler.block_samples("y", 0, 2, dt)
    np.testing.assert_array_equal(got_gy, np.zeros(2 * n_block, dtype=np.float64))

    # Block 1 (the delay) has no event on any axis: 0 for gx and gz too.
    np.testing.assert_array_equal(got_gx[n_block:], np.zeros(n_block, dtype=np.float64))
    got_gz = sampler.block_samples("z", 0, 2, dt)
    np.testing.assert_array_equal(got_gz[n_block:], np.zeros(n_block, dtype=np.float64))


def _blocks_with_long_events_sequence() -> pp.Sequence:
    """Five blocks. Block 0: a trapezoid on x and a longer one on z. Block 1: a delay, with no
    event on any axis. Block 2: an arbitrary gradient on x that starts 20 raster steps after
    the block start, and a delay event that holds the block for 120 steps, so the gradient's
    last point is 60 steps before the block end. Block 3: a triangle on y (two points at one
    time). Block 4: the block 2 again (the same event in a block of the same length)."""
    dt = SYSTEM.grad_raster_time
    n_arb = 40
    t = (np.arange(n_arb) + 0.5) * dt
    waveform = 0.1 * SYSTEM.max_grad * np.sin(np.pi * t / (n_arb * dt))
    arbitrary = pp.make_arbitrary_grad(channel="x", waveform=waveform, delay=20 * dt, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_trapezoid(channel="x", area=1000.0, system=SYSTEM),
        pp.make_trapezoid(channel="z", area=3000.0, system=SYSTEM),
    )
    seq.add_block(pp.make_delay(300 * dt))
    seq.add_block(arbitrary, pp.make_delay(120 * dt))
    seq.add_block(pp.make_trapezoid(channel="y", area=10.0, system=SYSTEM))
    seq.add_block(arbitrary, pp.make_delay(120 * dt))
    return seq


def test_skip_and_count_equal_the_same_slice_of_the_whole_range():
    """`block_samples(axis, first, stop, dt, skip=s, count=c)` equals `block_samples(axis, first,
    stop, dt)[s : s + c]` exactly, for each axis, for block ranges of the whole file and of
    its inner blocks, and for sample ranges that start and end inside a block, at the edge
    of a block, inside a block with no event, and after the last point of the event of a
    block (the samples that are 0 and that the sampler does not keep). `count=None` gives all
    the samples after `skip`. The sampler that made the whole range first (with samples kept)
    and a new one give the same part."""
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`) and one that starts above 0 after a delay
    # (`gradient.nonzero-start-delay`); `cpp-siemens` plays them.
    snap = load(_blocks_with_long_events_sequence(), "cpp-siemens")
    dt = SYSTEM.grad_raster_time
    index = sequence_index(snap)
    n_all, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    assert n_all[2] == n_all[4] == 120  # the event of block 2 stops 60 samples before its end
    sampler = gradient_sampler(snap)
    checked = 0
    for first, stop in [(0, 5), (1, 5), (2, 5), (1, 4), (2, 3), (3, 5), (0, 2), (4, 5)]:
        n = n_all[first:stop]
        for axis in _SAMPLER_AXES:
            whole = sampler.block_samples(axis, first, stop, dt)
            for skip, count in _sample_ranges(n):
                expected = whole[skip : skip + count]
                got = sampler.block_samples(axis, first, stop, dt, skip=skip, count=count)
                assert got.dtype == np.float64
                assert np.array_equal(got, expected), (axis, first, stop, skip, count)
                fresh = gradient_sampler(snap)
                got = fresh.block_samples(axis, first, stop, dt, skip=skip, count=count)
                assert np.array_equal(got, expected), (axis, first, stop, skip, count)
                checked += 1
            for skip in (0, 1, whole.size // 2, whole.size):
                got = sampler.block_samples(axis, first, stop, dt, skip=skip)
                assert np.array_equal(got, whole[skip:]), (axis, first, stop, skip)
    assert checked > 300
    # The range has samples that are not 0 after the first sample of block 2 and 0 at its end.
    part = sampler.block_samples("x", 2, 3, dt, skip=60, count=60)
    assert not np.any(part)
    assert np.any(sampler.block_samples("x", 2, 3, dt, skip=20, count=40))


def test_the_sample_at_the_time_of_the_last_point_has_the_value_of_that_point():
    """With `dt` of two raster steps, the first sample of a block is at the raster time
    `dt / 2`, which is exactly the time of the last point of a ramp that ends there with a
    value that is not 0. That sample is the value of the last point, and the next sample (after
    the last point, in the same block) is 0, also when the range cuts the block to one
    sample."""
    raster = SYSTEM.grad_raster_time
    amp = 1000.0  # Hz/m
    ramp = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, amp]),
        times=np.array([0.0, raster]),
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(ramp, pp.make_delay(4 * raster))
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`); `cpp-siemens` plays it.
    sampler = gradient_sampler(load(seq, "cpp-siemens"))
    dt = 2 * raster
    assert 0.5 * dt == raster
    np.testing.assert_array_equal(sampler.block_samples("x", 0, 1, dt), [amp, 0.0])
    np.testing.assert_array_equal(sampler.block_samples("x", 0, 1, dt, skip=0, count=1), [amp])
    np.testing.assert_array_equal(sampler.block_samples("x", 0, 1, dt, skip=1, count=1), [0.0])


def test_the_sample_at_a_last_point_that_is_many_steps_in_has_the_value_of_that_point():
    """With `dt` of two raster steps, a ramp from 0 to 1000 Hz/m over 27 raster steps ends
    exactly at the time of sample 13, `(13 + 0.5) * dt`, which the test asserts with the same
    float product that the sampler uses. The sample is the value of the last point, the
    sample after it is 0, and no sample before it is above it."""
    raster = SYSTEM.grad_raster_time
    amp = 1000.0  # Hz/m
    n_ramp = 27
    dt = 2 * raster
    last = (n_ramp - 1) // 2
    assert (last + 0.5) * dt == n_ramp * raster
    ramp = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, amp]),
        times=np.array([0.0, n_ramp * raster]),
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(ramp, pp.make_delay((n_ramp + 3) * raster))
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`); `cpp-siemens` plays it.
    sampler = gradient_sampler(load(seq, "cpp-siemens"))
    got = sampler.block_samples("x", 0, 1, dt)
    assert got.shape == (last + 2,)
    assert got[last] == amp
    assert got[last + 1] == 0.0
    assert np.all(got[:last] < amp)


def test_the_samples_in_a_short_gap_are_the_line_by_hand():
    """`short_gap_sequence`: the first gradient ends at 3 U at 100 us, its block ends at 110
    us, and the second block starts at 2 U. The gap is one raster time, so the sample at 105
    us (the last of block 0) is on the line from 3 U to 2 U: 2.5 U. It is 0 in the own event
    of block 0, after its last point. The other samples are those of the own events. The
    first sample of block 1 (5 us) is on the ramp down of block 1."""
    snap = _load_model("short_gap")
    sampler = gradient_sampler(snap)
    got = sampler.block_samples("x", 0, 2, _RASTER)
    assert got.shape == (21,)
    unit = 1e4
    # Block 0: the ramp 0 to 3 U over 100 us at 5, 15, ..., 95 us, then the line at 105 us.
    np.testing.assert_allclose(
        got[:11],
        unit * np.array([0.15, 0.45, 0.75, 1.05, 1.35, 1.65, 1.95, 2.25, 2.55, 2.85, 2.5]),
        rtol=1e-9,
    )
    # Block 1: 2 U down to 0 over 100 us at 5, ..., 95 us, then nothing.
    np.testing.assert_allclose(
        got[11:20], unit * np.array([1.9, 1.7, 1.5, 1.3, 1.1, 0.9, 0.7, 0.5, 0.3]), rtol=1e-9
    )


def test_the_samples_in_a_ramp_of_a_long_gap_that_are_not_at_its_ends_are_the_ramp_by_hand():
    """`_off_raster_events_sequence` at the gradient raster, where the ramp to 0 (3.3 to 3.8
    raster times) has the sample at 3.5, and the ramp from 0 (8.2 to 8.7) the sample at 8.5,
    a sample of the first block and the first sample of the second block. The hand values are
    in `test_a_ramp_to_0_and_a_ramp_from_0_cross_a_long_gap_by_hand`. The other samples are
    those of the own events."""
    snap = _load_model("off_raster_events")
    sampler = gradient_sampler(snap)
    got = sampler.block_samples("x", 0, 2, _RASTER)
    expected = _A * np.array(
        [
            0.2 / 3,
            1.2 / 3,
            2.2 / 3,
            0.6,
            0,
            0,
            0,
            0,
            0.3,
            0.5 * (1 - 0.8 / 3),
            0.5 * (1 - 1.8 / 3),
            0.5 * (1 - 2.8 / 3),
            0,
            0,
            0,
            0,
        ]
    )
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-9 * _A)


_EDGE_SEQUENCES = {
    "delayed_ramp_" + "_".join(map(str, case)): (lambda case=case: delayed_ramp_sequence(*case))
    for case in DELAYED_RAMP_CASES + ULP_EDGE_CASES
} | {"short_arbitrary": lambda: short_arbitrary_sequence()}


@pytest.mark.parametrize("name", _EDGE_SEQUENCES)
def test_block_samples_at_the_last_point_of_an_event_and_at_a_step_equals_the_oracle(name):
    """`block_samples` of the whole sequence equals `oracle.block_samples` at the gradient
    raster. The `delayed_ramp_sequence` cases of `DELAYED_RAMP_CASES` and `ULP_EDGE_CASES` have a
    ramp after a delay of half a raster time (and whole raster times) behind filler blocks: the
    sample at the last point has the value of that point, also where the sum `delay + offset`
    is one ulp before the sample time (review 1.3). The oracle has the same tolerance after the
    last point, which the `ULP_EDGE_CASES` need. `short_arbitrary_sequence` has a step inside
    one event at a sample time: the sample has the value before the step (review 1.4, the rule
    of `sample`)."""
    # `spec` rejects these sequences (a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`) or starts above 0 after a delay
    # (`gradient.nonzero-start-delay`), a delay or an end off the gradient raster); `cpp-siemens`
    # plays them.
    snap = load(_EDGE_SEQUENCES[name](), "cpp-siemens")
    index = sequence_index(snap)
    assert raster_block_lengths(index, _RASTER)[1]
    sampler = gradient_sampler(snap)
    for axis in "xyz":
        got = sampler.block_samples(axis, 0, index.num_blocks, _RASTER)
        _assert_samples_match(got, oracle.block_samples(sequence_of(snap), axis, _RASTER))


# ---- The series (`test_series.py`) ----


@pytest.mark.parametrize(("thresholds", "bin_s"), _PNS_CASES)
def test_the_series_of_pns_safe_levels_are_valid(thresholds, bin_s):
    """The series of `pns.safe.levels` for `raster_4us_sequence`, with and without thresholds and
    with bins that divide the level and bins that do not, are valid
    (`check_the_series_of_pns_safe_levels_are_valid`). `spec` rejects a gradient raster of 4 us
    with a block duration raster of 10 us (`definitions.raster-commensurate`)."""
    snap = load(raster_4us_sequence(), "cpp-siemens")
    check_the_series_of_pns_safe_levels_are_valid(snap, thresholds, bin_s)


def test_the_series_of_gradient_spectrum_is_valid():
    """The series of `gradient.spectrum` for `raster_4us_sequence` is valid
    (`check_the_series_of_gradient_spectrum_is_valid`)."""
    snap = load(raster_4us_sequence(), "cpp-siemens")
    check_the_series_of_gradient_spectrum_is_valid(snap, has_gradient=True)


# ---- A NaN of the file (`bad_syntax_number.seq`) ----

# `tests/seqfiles/bad_syntax_number.seq`: the trapezoid 1 has the amplitude `nan`. `spec` rejects
# it (`syntax.number`); the reader reads it. The trapezoid is gx of block 2 (play index 1), which
# starts at 300 us, with gy (the arbitrary gradient 2). Block 5 (play index 4) has the rotation
# object 1 of the file, 45 degrees about z.
_BAD_NUMBER = Path(__file__).resolve().parents[3] / "tests" / "seqfiles" / "bad_syntax_number.seq"
_NAN_TRAP_ROW = "1 nan 100 200 100 100\n"
_BLOCK_2_ROW = "2  50  0  1  2  0  1  0\n"
# The settings of the NaN cases: the interpreter, the session, and whether block 2 has the
# rotation object too (`_bad_number_files`).
_NAN_SETTINGS = {
    "unrotated": ("cpp-siemens", None, False),
    "apply": (CppSiemens(rotation="apply"), None, False),
    "apply-rotated-block": (CppSiemens(rotation="apply"), None, True),
    "fov": ("cpp-siemens", Session(fov_rotation=QUARTER_Z), False),
}


def _bad_number_files(directory: Path, rotated: bool) -> tuple[Path, Path]:
    """`bad_syntax_number.seq` and the same file with the amplitude 0 for the trapezoid 1 (no
    NaN), written in `directory`. With `rotated`, block 2 has the extension list 3 of the file,
    the rotation object 1 (45 degrees about z), so that `CppSiemens(rotation="apply")` reads it
    through `gradients_at`."""
    text = _BAD_NUMBER.read_text()
    assert text.count(_NAN_TRAP_ROW) == 1 and text.count(_BLOCK_2_ROW) == 1
    if rotated:
        text = text.replace(_BLOCK_2_ROW, "2  50  0  1  2  0  1  3\n")
    nan, clean = directory / "nan.seq", directory / "clean.seq"
    nan.write_text(text)
    clean.write_text(text.replace(_NAN_TRAP_ROW, "1 0 100 200 100 100\n"))
    return nan, clean


def _load_nan_case(directory: Path, setting: str) -> tuple[Snapshot, Snapshot]:
    """The snapshots of the two files of `_bad_number_files` with the setting `setting` of
    `_NAN_SETTINGS`, without the warning of the rotation of block 5, which `"cpp-siemens"` leaves
    unapplied."""
    interpreter, session, rotated = _NAN_SETTINGS[setting]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        return tuple(
            load(path, interpreter, session=session)
            for path in _bad_number_files(directory, rotated)
        )


@pytest.mark.parametrize(
    ("setting", "axes", "peak_time_s", "vector_time_s"),
    [
        pytest.param("unrotated", "x", 500e-6, 405e-6, id="unrotated"),
        pytest.param("apply", "x", 500e-6, 405e-6, id="apply"),
        pytest.param("apply-rotated-block", "xyz", 405e-6, 405e-6, id="apply-rotated-block"),
        pytest.param("fov", "xyz", 405e-6, 405e-6, id="fov"),
    ],
)
def test_a_nan_of_the_file_is_credited_to_its_block_at_its_first_nan(
    tmp_path, setting, axes, peak_time_s, vector_time_s
):
    """In `bad_syntax_number.seq` through `cpp-siemens`, the NaN of the trapezoid in block 2
    (play index 1) follows the rule of a NaN in the peaks
    (`check_a_nan_of_one_block_is_credited_to_its_first_nan`), and every other value is the
    value of the same file with the amplitude 0. With no rotation, and with
    `CppSiemens(rotation="apply")` (block 2 has no rotation), the event is decoded and the NaN is
    on x. When block 2 is read through `gradients_at` (it has the rotation object and the
    rotation is applied, or the session's field of view rotates it), the rotation of the reader
    gives NaN on every axis of the block, and the measurements take what the decoding gives."""
    snap, clean = _load_nan_case(tmp_path, setting)
    # The trapezoid starts at 400 us (the block start and its delay of 100 us), and the segment of
    # its rise is the first NaN segment. Decoded, its first NaN point is the end of the rise, at
    # 500 us; read through `gradients_at`, the block has a point at each time of the points of gx
    # and gy, and gy has one at 405 us. The vector is NaN first at 405 us: in the decoded block the
    # polyline of gx is NaN there, between 0 at 400 us and the NaN at 500 us.
    check_a_nan_of_one_block_is_credited_to_its_first_nan(
        snap, clean, 1, axes, peak_time_s, slew_time_s=400e-6, vector_time_s=vector_time_s
    )


@pytest.mark.parametrize("setting", list(_NAN_SETTINGS))
def test_the_pns_peak_of_a_nan_of_the_file_is_nan_at_the_first_nan_sample(tmp_path, setting):
    """In `bad_syntax_number.seq` through `cpp-siemens`, with each setting of the NaN cases, the
    summary of `pns_levels` (with pypulseq's example hardware) gives the NaN peak of the total
    (a NaN propagates), at the time of the first sample whose total is NaN. Sample 40 (at 405 us) is the first
    sample in the NaN trapezoid, and the filters of the SAFE model carry the NaN to every later
    sample."""
    snap, _ = _load_nan_case(tmp_path, setting)
    levels = pns_levels(snap, hardware=EXAMPLE_HW)
    assert math.isnan(levels.peak_hz_per_t)
    assert levels.peak_time_s == pytest.approx((40 + 0.5) * levels.dt_s, rel=0, abs=TIME_TOLERANCE)
