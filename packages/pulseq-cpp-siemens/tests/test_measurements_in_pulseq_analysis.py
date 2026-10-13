"""The measurements of pulseq-analysis for the sequences that `spec` rejects, loaded through
`cpp-siemens`: `gradient_peaks`, `block_gradient_values`, `gradient_spectrum`, `pns_levels` and
`GradientSampler` against the oracle (the model of MATLAB Pulseq) and against values by hand, for
a gradient that ends above 0 before its block ends, a gradient that starts above 0 after a delay,
a delay off the gradient raster, and a gradient raster of 4 us with a block duration raster of
10 us. The root tests of these measurements run without the plugin, so they keep the sequences
that `spec` reads and call the same checks (`check_*`); the other tests of the sequences that
`spec` rejects are here.

The module is not collected without pulseq-analysis (`conftest.py`); the MATLAB oracle and the
helpers are those of the tests of pulseq-analysis (the root of this repository).
"""

import math

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
    long_gap_sequence,
    negated,
    non_zero_ends_sequence,
    short_arbitrary_sequence,
    short_gap_from_0_sequence,
    short_gap_sequence,
    short_gap_to_0_sequence,
    vector_sequence,
    zero_gap_sequence,
)
from oracles import grad_spectrum as spectrum_oracle
from oracles import waveform as oracle
from oracles.blocks import sequence_of
from random_gaps import random_gap_sequence
from scale_sequences import build_repeating, build_worst
from synthetic import (
    EXAMPLE_HW,
    GAMMA_1H,
    RASTER_4US,
    RASTER_4US_JUNCTION,
    RASTER_4US_JUNCTION_TIME,
    SYSTEM,
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    raster_4us_sequence,
    spin_echo_sequence,
)
from test_grad_peaks import (
    _MAX_STEP,
    _RASTER,
    _WRITER_REL,
    _assert_axis,
    _assert_matches_oracle_on_windows,
    _end_step_sequence,
    _first_block_starts_non_zero_sequence,
    _gradient_ends_non_zero_before_delay_sequence,
    _junction_and_segment_sequence,
    _junction_sequence,
    _oracle_windows,
    _random_gradient_sequence,
)
from test_grad_spectrum import _assert_matches_oracle as _assert_spectrum_matches_oracle
from test_pns_levels import _add_a_delay
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
from pulseq_analysis.analyses.pns_levels import PEAK_TOLERANCE, pns_levels
from pulseq_analysis.analyses.safe import _safe_gwf_to_pns_chunk
from pulseq_analysis.synth.sampling import gradient_sampler, raster_block_lengths
from pulseq_analysis.synth.seq_index import sequence_index
from pulseq_analysis.synth.seq_utils import _AXES, TIME_TOLERANCE, gradient_offsets
from pulseq_analysis.synth.snapshot import Snapshot, _kept_results

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


@pytest.mark.parametrize("early", [0.0, 0.5 * TIME_TOLERANCE, 0.9 * TIME_TOLERANCE, DT])
def test_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end(early):
    """The last point of the extended trapezoid is `early` before the end of the sequence. The
    step to 0 is counted only when `early` is more than `TIME_TOLERANCE`: then it is the largest
    slew, `A / DT`, in block 2, at the last point (`early` is one raster time then). Else the
    largest slew is the 1e9 Hz/m/s of the trapezoid. The whole file, the window that ends at the
    end of the sequence, the window that ends `0.5 * TIME_TOLERANCE` before it (the step of an
    `early` of 0.9 * `TIME_TOLERANCE` is before the end of that window, and is not counted) and the
    values of each block agree with the oracle. `spec` rejects a gradient that ends at `A` before
    its block ends (`gradient.nonzero-end-align`) and, for an `early` that is not a multiple of
    the raster, a last point off the gradient raster; `cpp-siemens` plays it."""
    seq = _end_step_sequence(100e-6, early)
    snap = load(seq, "cpp-siemens")
    index = sequence_index(snap)
    block_a_id, block_b_id = seq.block_events
    counted = early > TIME_TOLERANCE

    expected = oracle.peaks(seq)["x"]
    assert expected["max_slew"] == pytest.approx(A / DT if counted else 1e9, rel=1e-6)
    assert expected["slew_block"] == (block_b_id if counted else block_a_id)
    for result in (
        gradient_peaks(snap).axes["x"],
        gradient_peaks(snap, window=(0.0, index.end_s)).axes["x"],
    ):
        assert result.max_slew_hz_per_m_per_s == pytest.approx(expected["max_slew"], rel=1e-6)
        assert result.slew_block == expected["slew_block"]
        assert result.slew_time_s == pytest.approx(expected["slew_time"], abs=1e-12)
    window = (0.0, index.end_s - 0.5 * TIME_TOLERANCE)
    expected_window = oracle.peaks(seq, window)["x"]
    result = gradient_peaks(snap, window=window).axes["x"]
    assert expected_window["max_slew"] == pytest.approx(expected["max_slew"], rel=1e-6)
    assert expected_window["slew_block"] == expected["slew_block"]
    assert result.max_slew_hz_per_m_per_s == pytest.approx(expected["max_slew"], rel=1e-6)
    assert result.slew_block == expected["slew_block"]
    slew = block_gradient_values(snap).slew_hz_per_m_per_s["x"]
    assert slew[1] == pytest.approx(A / DT if counted else A / 100e-6, rel=1e-6)
    if counted:
        assert expected["slew_time"] == pytest.approx(index.end_s - early, abs=1e-12)


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

    cut = gradient_peaks(snap, window=(ramp_start + _RASTER / 4, index.end_s))
    assert cut.reason is None
    assert cut.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(2 * 0.9 * _MAX_STEP / _RASTER)
    assert cut.axes["x"].slew_block == block_b_id
    assert cut.axes["x"].slew_time_s == pytest.approx(ramp_start + _RASTER / 4, abs=1e-12)

    before_the_ramp = gradient_peaks(snap, window=(0.0, ramp_start))
    assert before_the_ramp.reason is None
    assert before_the_ramp.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(
        segment_slope, rel=_WRITER_REL
    )
    assert before_the_ramp.axes["x"].slew_block == block_a_id


@pytest.mark.parametrize(
    "make_seq",
    [
        spin_echo_sequence,
        gre_sequence,
        empty_sequence,
        arbitrary_gradient_sequence,
        border_sequence,
        raster_4us_sequence,
    ],
    ids=["spin_echo", "gre", "empty", "arbitrary_gradient", "border", "raster_4us"],
)
def test_matches_oracle_on_synthetic_sequences(make_seq):
    """`gradient_peaks` matches the oracle on the whole file, and on 12 windows that cut the
    gradients of `tests/synthetic.py`'s sequences (`_oracle_windows`), the first half of the
    sequence among them. `border_sequence` and `raster_4us_sequence` have a gradient that is not 0
    at a block junction. `spec` rejects `raster_4us_sequence` (a gradient raster of 4 µs with a
    block duration raster of 10 µs); `cpp-siemens` reads it, and the others too."""
    seq = make_seq()
    snap = load(seq, "cpp-siemens")
    windows = _oracle_windows(snap, np.random.default_rng(20261007), 12)
    windows.append((0.0, sequence_index(snap).end_s / 2))
    _assert_matches_oracle_on_windows(snap, windows)


@pytest.mark.parametrize(
    "build",
    [
        delayed_sequence,
        early_end_sequence,
        zero_gap_sequence,
        short_gap_sequence,
        long_gap_sequence,
        non_zero_ends_sequence,
        vector_sequence,
    ],
    ids=["delayed", "early_end", "zero_gap", "short_gap", "long_gap", "non_zero_ends", "vector"],
)
def test_matches_oracle_on_the_sequences_of_the_oracle_tests(build):
    """`gradient_peaks` matches the oracle on the whole file and on 40 windows that cut the
    gradients, for each sequence of `gap_sequences.py`: the two sequences of
    pypulseq-issues 12 (a delay before a first value that is not 0, and an end that is not 0
    before the end of its block), a zero gap with a step, a short gap, a long gap, a first and a
    last value that are not 0, and one block with two axes. `spec` rejects most of these (a first
    value that is not 0 after a delay, `gradient.nonzero-start-delay`, or an end that is not 0
    before the end of its block, `gradient.nonzero-end-align`); `cpp-siemens` plays all of
    them."""
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
    (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`); `cpp-siemens` plays them."""
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


def _junction_time(seq: pp.Sequence, values, axis: str, play: int) -> float:
    """The time of the junction (the step, or the line) into the event of the block `play` on
    `axis`, read with `get_block`: the time of the first point of the event, `(block start +
    delay)`, for a step and for the first event of the axis, and the time of the last point of the
    event before it, for a line across a short gap. The arithmetic is that of the package."""
    first_event = getattr(seq.get_block(int(values.block_id[play])), f"g{axis}")
    first_time = values.start_s[play] + first_event.delay
    for earlier in range(play - 1, -1, -1):
        g = getattr(seq.get_block(int(values.block_id[earlier])), f"g{axis}", None)
        if g is not None:
            delay, offsets, _ = gradient_offsets(g)
            last_time = (values.start_s[earlier] + delay) + offsets[-1]
            return last_time if first_time - last_time > TIME_TOLERANCE else first_time
    return first_time


def _assert_block_values_agree_with_gradient_peaks(snap: Snapshot) -> None:
    """The maximum of each value of `block_gradient_values` is the value of the whole file
    in `gradient_peaks`, and the first block with that value, with its time, is the block and
    the time of `gradient_peaks` (for the vector peak, the block with the earliest time of the
    blocks with that value). The time of a junction is read here with `get_block`
    (`_junction_time`). The arithmetic is the same, so every comparison is exact."""
    values = block_gradient_values(snap)
    whole = gradient_peaks(snap)
    assert values.block_id.size > 0
    for axis in ("x", "y", "z"):
        result = whole.axes[axis]

        peak = values.peak_hz_per_m[axis]
        top = float(peak.max())
        assert top == result.peak_hz_per_m
        if top > 0.0:
            play = int(np.argmax(peak == top))
            assert int(values.block_id[play]) == result.peak_block
            assert values.peak_time_s[axis][play] == result.peak_time_s
        else:
            assert result.peak_block is None

        segment = values.slew_hz_per_m_per_s[axis]
        junction = values.junction_hz_per_m_per_s[axis]
        combined = np.maximum(segment, junction)
        top = float(combined.max())
        assert top == result.max_slew_hz_per_m_per_s
        if top > 0.0:
            play = int(np.argmax(combined == top))
            assert int(values.block_id[play]) == result.slew_block
            # The junction is before every other item of its block.
            if junction[play] == top:
                time = _junction_time(sequence_of(snap), values, axis, play)
            else:
                time = values.slew_time_s[axis][play]
            assert time == result.slew_time_s
        else:
            assert result.slew_block is None

    vector = values.vector_peak_hz_per_m
    top = float(vector.max())
    assert top == whole.vector_peak_hz_per_m
    if top > 0.0:
        tied = np.flatnonzero(vector == top)
        play = int(tied[np.argmin(values.vector_peak_time_s[tied])])
        assert int(values.block_id[play]) == whole.vector_peak_block
        assert values.vector_peak_time_s[play] == whole.vector_peak_time_s
    else:
        assert whole.vector_peak_block is None


_AGREEMENT_SEQUENCES = [
    spin_echo_sequence,
    gre_sequence,
    empty_sequence,
    arbitrary_gradient_sequence,
    border_sequence,
    raster_4us_sequence,
    lambda: build_repeating(50),
    lambda: build_worst(50),
    _junction_sequence,
    _junction_and_segment_sequence,
    _gradient_ends_non_zero_before_delay_sequence,
    _first_block_starts_non_zero_sequence,
    _delayed_junction_sequence,
    lambda: delayed_sequence(),
    lambda: early_end_sequence(),
    lambda: zero_gap_sequence(),
    lambda: short_gap_sequence(),
    lambda: long_gap_sequence(),
    lambda: non_zero_ends_sequence(),
    lambda: vector_sequence(),
    *(
        lambda seed=seed: _random_gradient_sequence(np.random.default_rng(seed))
        for seed in range(4)
    ),
    *(lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)) for seed in range(8)),
]


_AGREEMENT_IDS = [
    "spin_echo",
    "gre",
    "empty",
    "arbitrary_gradient",
    "border",
    "raster_4us",
    "build_repeating_50",
    "build_worst_50",
    "junction",
    "junction_and_segment",
    "ends_non_zero_before_delay",
    "first_block_starts_non_zero",
    "delayed_junction",
    "oracle_delayed",
    "oracle_early_end",
    "oracle_zero_gap",
    "oracle_short_gap",
    "oracle_long_gap",
    "oracle_non_zero_ends",
    "oracle_vector",
    *(f"random_{seed}" for seed in range(4)),
    *(f"random_gap_{seed}" for seed in range(8)),
]


@pytest.mark.parametrize("make_seq", _AGREEMENT_SEQUENCES, ids=_AGREEMENT_IDS)
def test_block_gradient_values_agree_with_gradient_peaks_for_the_whole_file(make_seq):
    """The maxima of `block_gradient_values` over the blocks are the whole-file values of
    `gradient_peaks`, with the same block and time. `spec` rejects some of the sequences
    (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`, and a gradient raster of 4 µs
    with a block duration raster of 10 µs, `definitions.raster-commensurate`); `cpp-siemens`
    plays all of them."""
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


def _zero_duration_blocks_sequence() -> pp.Sequence:
    """Trapezoids on x and y with blocks of zero duration (labels) before, between and after
    them, so a window edge can fall on the time of a block of zero duration."""
    seq = pp.Sequence(SYSTEM)
    label = pp.make_label(label="LIN", type="SET", value=1)
    seq.add_block(label)
    seq.add_block(pp.make_trapezoid(channel="x", area=1000, system=SYSTEM))
    seq.add_block(label)
    seq.add_block(label)
    seq.add_block(pp.make_trapezoid(channel="y", area=500, system=SYSTEM))
    seq.add_block(label)
    seq.add_block(pp.make_trapezoid(channel="x", area=700, system=SYSTEM))
    seq.add_block(label)
    return seq


def _random_windows(snap: Snapshot, rng: np.random.Generator, count: int) -> list:
    """`count` windows of `snap`: half have each end on a start or an end of a block (so a window
    edge and a block edge are equal, also for a block of zero duration), half have random ends."""
    index = sequence_index(snap)
    edges = np.unique(
        np.concatenate(([0.0, index.end_s], index.start_s, index.start_s + index.duration_s))
    )
    windows = []
    for i in range(count):
        pool = edges if i % 2 == 0 else rng.uniform(0.0, index.end_s, size=edges.size)
        start, end = np.sort(rng.choice(pool, size=2))
        if start < end:
            windows.append((float(start), float(end)))
    return windows


@pytest.mark.parametrize(
    "make_seq",
    [
        lambda: build_repeating(30),
        _zero_duration_blocks_sequence,
        _junction_sequence,
        _delayed_junction_sequence,
        lambda: _random_gradient_sequence(np.random.default_rng(3)),
        lambda: random_gap_sequence(np.random.default_rng(5)),
    ],
    ids=[
        "build_repeating_30",
        "zero_duration_blocks",
        "junction",
        "delayed_junction",
        "random_3",
        "random_gap_5",
    ],
)
def test_a_window_gives_the_same_result_with_and_without_the_kept_data(make_seq):
    """For 30 random windows, `gradient_peaks` of a snapshot that has its kept data (from the
    windows before: it is never emptied, and it is one object for all the windows) gives a
    result equal (`==`) to the result of a second snapshot of the same build whose kept data of
    `gradient_peaks` is empty and is built by this call (a new snapshot for each window)."""
    seq = make_seq()
    snap = load(seq, "cpp-siemens")
    windows = _random_windows(snap, np.random.default_rng(20261006), 30)
    kept = _kept_results(snap)
    kept_data = None
    for window in windows:
        with_kept = gradient_peaks(snap, window=window)
        if kept_data is None:
            kept_data = kept["block_data"]
        assert kept["block_data"] is kept_data
        assert with_kept == gradient_peaks(load(seq, "cpp-siemens"), window=window), window


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

    window = gradient_peaks(snap, window=(105e-6, 150e-6))
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

    before_the_step = gradient_peaks(snap, window=(edge - 1e-12, end_s))
    assert before_the_step.axes["y"].peak_hz_per_m == pytest.approx(top, rel=_WRITER_REL)
    assert before_the_step.axes["y"].peak_block == block_1
    assert before_the_step.vector_peak_hz_per_m == pytest.approx(top, rel=_WRITER_REL)
    assert before_the_step.vector_peak_time_s == pytest.approx(edge - 1e-12, rel=0, abs=1e-15)
    assert before_the_step.vector_peak_block == block_2

    after_the_step = gradient_peaks(snap, window=(edge + 1e-12, end_s))
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


def _block_values_of_the_polyline(seq: pp.Sequence, axis: str) -> dict:
    """The values of each block on `axis`, from the polyline of the oracle only: the peak and its
    time, the junction (the items of a segment from a point of one block to a point of another,
    and the steps before the last point), and the slew (the other segments, and the step after the
    last point when it is more than `TIME_TOLERANCE` before the end of the sequence), each with
    the items of the block that have the largest value. The credit of an item is the play index of
    the polyline."""
    poly = oracle.axis_polyline(seq, axis)
    n = len(poly.block_id)
    end = float(poly.block_end[-1])
    peak, peak_time = np.zeros(n), np.array(poly.block_start)
    for time, value, play in zip(poly.t, poly.g, poly.point_play, strict=True):
        if abs(value) > peak[play]:
            peak[play], peak_time[play] = abs(value), time
    items = []  # (position in the polyline, is a junction, play index, value, time)
    for s in range(poly.t.size - 1):
        t0, t1 = poly.t[s], poly.t[s + 1]
        if t1 - t0 >= TIME_TOLERANCE and not poly.segment_is_step[s]:
            junction = poly.point_play[s] != poly.point_play[s + 1]
            slope = abs(poly.g[s + 1] - poly.g[s]) / (t1 - t0)
            items.append((s, junction, poly.point_play[s + 1], slope, t0))
    for point, time, size, play in zip(
        poly.step_point, poly.step_time, poly.step_size, poly.step_play, strict=True
    ):
        last = point == poly.t.size - 1
        if not last or time < end - TIME_TOLERANCE:
            items.append((point - 0.5, not last, play, abs(size) / seq.grad_raster_time, time))
    junction = np.zeros(n)
    slew = np.zeros(n)
    for _, is_junction, play, value, _ in items:
        column = junction if is_junction else slew
        column[play] = max(column[play], value)
    slew_times = [
        [time for _, is_junction, play, value, time in items if not is_junction and play == p
         and value >= slew[p] * (1 - 1e-9)]
        for p in range(n)
    ]  # fmt: skip
    return {
        "peak": peak,
        "peak_time": peak_time,
        "junction": junction,
        "slew": slew,
        "slew_times": slew_times,
    }


_BLOCK_VALUE_SEQUENCES = [
    spin_echo_sequence,
    gre_sequence,
    border_sequence,
    raster_4us_sequence,
    lambda: delayed_sequence(),
    lambda: early_end_sequence(),
    lambda: zero_gap_sequence(),
    lambda: short_gap_sequence(),
    lambda: long_gap_sequence(),
    lambda: non_zero_ends_sequence(),
    lambda: vector_sequence(),
    *(lambda seed=seed: random_gap_sequence(np.random.default_rng(seed)) for seed in range(14)),
]


_BLOCK_VALUE_IDS = [
    "spin_echo",
    "gre",
    "border",
    "raster_4us",
    "oracle_delayed",
    "oracle_early_end",
    "oracle_zero_gap",
    "oracle_short_gap",
    "oracle_long_gap",
    "oracle_non_zero_ends",
    "oracle_vector",
    *(f"random_gap_{seed}" for seed in range(14)),
]


@pytest.mark.parametrize("make_seq", _BLOCK_VALUE_SEQUENCES, ids=_BLOCK_VALUE_IDS)
def test_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has(make_seq):
    """For each axis and each block, the peak, the junction and the slew of `block_gradient_values`
    are the values of the items that the credit of the model gives to the block, found in the
    polyline of the oracle (`_block_values_of_the_polyline`): the peak and its time (the first point
    that has it), the junction (a line across a short gap, a step across a zero gap, and the step
    before the first point, and not a ramp), and the slew (the segments of the event and the
    ramps of the event, and the step after the last point when it is before the end of the
    sequence). The time of the slew of a block is the time of one of its items with the largest
    slope (two items can have one slope up to the rounding of the times). The polyline is that
    of the gradients that the snapshot plays (`sequence_of`): the file holds the amplitudes
    rounded by the writer. `spec` rejects some of the sequences (`gradient.nonzero-start-delay`,
    `gradient.nonzero-end-align`, and a gradient raster of 4 µs with a block duration raster of
    10 µs, `definitions.raster-commensurate`); `cpp-siemens` plays all of them."""
    snap = load(make_seq(), "cpp-siemens")
    seq = sequence_of(snap)
    values = block_gradient_values(snap)

    for axis in _AXES:
        expected = _block_values_of_the_polyline(seq, axis)
        np.testing.assert_allclose(values.peak_hz_per_m[axis], expected["peak"], rtol=1e-12)
        positive = expected["peak"] > 0.0
        np.testing.assert_allclose(
            values.peak_time_s[axis][positive], expected["peak_time"][positive], rtol=0, atol=1e-12
        )
        np.testing.assert_allclose(
            values.junction_hz_per_m_per_s[axis], expected["junction"], rtol=1e-9
        )
        np.testing.assert_allclose(values.slew_hz_per_m_per_s[axis], expected["slew"], rtol=1e-9)
        for play in np.flatnonzero(expected["slew"] > 0.0):
            assert any(
                abs(values.slew_time_s[axis][play] - time) <= 1e-12
                for time in expected["slew_times"][play]
            ), f"{axis} block {play}: slew time {values.slew_time_s[axis][play]!r}"


# ---- gradient_spectrum (`test_grad_spectrum.py`) ----


_SPECTRUM_GAP_SEQUENCES = {
    "zero_gap": zero_gap_sequence,
    "short_gap": short_gap_sequence,
    "long_gap": long_gap_sequence,
    "non_zero_ends": non_zero_ends_sequence,
    "issue_12_delayed": delayed_sequence,
    "issue_12_early_end": early_end_sequence,
    "gap_of_1_5_raster_times": gap_of_1_5_raster_times_sequence,
    "short_gap_from_0": short_gap_from_0_sequence,
    "short_gap_to_0": short_gap_to_0_sequence,
}
# The sequences of `gap_sequences` with every amplitude negated (the gap rules do not depend on
# the sign).
_SPECTRUM_GAP_SEQUENCES |= {
    f"negated_{name}": (lambda build=_SPECTRUM_GAP_SEQUENCES[name]: negated(build()))
    for name in (
        "zero_gap",
        "short_gap",
        "long_gap",
        "non_zero_ends",
        "issue_12_delayed",
        "issue_12_early_end",
    )
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
    ends that are not 0 next to it (and a first and a last value that are not 0), equals the
    spectrum that the oracle calculates from `oracle.sample` (the model of MATLAB Pulseq).
    pypulseq's `calculate_gradient_spectrum` draws a line across a long gap
    (pypulseq-issues 12) and gives another spectrum, so it is not the reference here. The
    sequences are the hand sequences of `gap_sequences`, each also with every amplitude negated,
    a gap of 1.5 raster times between two values that are not 0, a short gap from 0 to a value
    that is not 0 and from one to 0, and the 8 random sequences of `random_gaps` (seeds 0 to 7).
    The oracle reads the gradients as the snapshot plays them (`sequence_of`)."""
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


def _long_gap_then_an_off_raster_block_sequence() -> pp.Sequence:
    """`long_gap_sequence` and a last block of 1.5 raster times, which is not on the raster,
    so that `pns_levels` samples the whole sequence with `GradientSampler.sample`."""
    seq = long_gap_sequence()
    _add_a_delay(seq, 1.5)
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
    "long_gap": lambda: long_gap_sequence(),
    "issue_12_delayed": lambda: delayed_sequence(),
    "issue_12_early_end": lambda: early_end_sequence(),
    "non_zero_ends": lambda: non_zero_ends_sequence(),
    "long_gap_off_raster": _long_gap_then_an_off_raster_block_sequence,
    "gap_of_1_5_raster_times": lambda: gap_of_1_5_raster_times_sequence(),
    "short_gap_from_0": lambda: short_gap_from_0_sequence(),
    "short_gap_to_0": lambda: short_gap_to_0_sequence(),
}
# The sequences of `gap_sequences` with every amplitude negated (the gap rules do not depend on
# the sign).
_PNS_GAP_SEQUENCES |= {
    f"negated_{name}": (lambda build=build: negated(build()))
    for name, build in {
        "zero_gap": zero_gap_sequence,
        "short_gap": short_gap_sequence,
        "long_gap": long_gap_sequence,
        "non_zero_ends": non_zero_ends_sequence,
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
    for name in [
        "gap_of_1_5_raster_times",
        "short_gap_from_0",
        "short_gap_to_0",
        "negated_long_gap",
        "negated_short_gap",
    ]
    + [f"random_gaps_{seed}" for seed in range(8)]
}


@pytest.mark.parametrize("name", _PNS_GAP_SEQUENCES)
def test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples(
    name,
):
    """For a sequence with a short gap or a long gap and ends that are not 0 next to it (and
    the first value and the last value of an axis that are not 0), `pns_levels` equals the SAFE
    model of the package, `_safe_gwf_to_pns_chunk` of `pulseq_analysis.analyses.safe`, in one
    chunk on the stacked `(N, 3)` samples of the oracle (`oracle.block_samples` at the gradient
    raster, `oracle.sample` at the file times `(k + 0.5) * dt` for the sequence that has a
    block that is not on the raster), with the
    percent times 0.01 and the total `sqrt(sum of squares)`, as `pns_levels` does. The peak
    and the axis peaks are equal to a relative 1e-9, and each bin of one sample (`bin_s=dt`)
    holds the total of its sample. `calculate_pns` of pypulseq is not the reference: it draws
    a line across each gap (pypulseq-issues 12). The sequences are the hand sequences of
    `gap_sequences`, each also with every amplitude negated, a gap of 1.5 raster times between
    two values that are not 0, a short gap from 0 to a value that is not 0 and from one to 0,
    and the 8 random sequences of `random_gaps` (seeds 0 to 7). The new ones and the random ones
    are also run with a last block that is not on the raster. The 14 ramps of
    `DELAYED_RAMP_CASES` and `ULP_EDGE_CASES` (a delay of half a raster time behind filler
    blocks, review 1.3) and the arbitrary gradient of 3 samples of `short_arbitrary_sequence` (review 1.4) have the
    last sample of an event at a sample time. The oracle reads the gradients of the snapshot
    as it plays them (`sequence_of`), so the written file's rounding is not in the difference;
    the bins also have an absolute tolerance of 1e-12 of the peak for the rounding residue of a
    sample that is 0."""
    # `spec` rejects a gradient that ends above 0 before its block ends
    # (`gradient.nonzero-end-align`), a delay off the gradient raster (`raster.gradient-delay`) and
    # a gradient that starts above 0 after a delay (`gradient.nonzero-start-delay`);
    # `cpp-siemens` plays them. The oracle reads the gradients as the snapshot plays them
    # (`sequence_of`).
    snap = load(_PNS_GAP_SEQUENCES[name](), "cpp-siemens")
    seq = sequence_of(snap)
    dt = seq.grad_raster_time
    levels = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=dt)
    if levels.on_raster:
        columns = [oracle.block_samples(seq, axis, dt) for axis in "xyz"]
    else:
        t = (np.arange(levels.num_samples) + 0.5) * dt
        columns = [oracle.sample(seq, axis, t) for axis in "xyz"]
    gwf = np.stack(columns, axis=1)
    percent, _ = _safe_gwf_to_pns_chunk(gwf, dt, EXAMPLE_HW[0], None)
    axis_values = 0.01 * percent
    total = np.sqrt((axis_values**2).sum(axis=1))

    assert levels.num_samples == total.size
    assert levels.on_raster is not name.endswith("_off_raster")
    assert levels.peak_hz_per_t == pytest.approx(total.max(), rel=1e-9)
    for i, axis in enumerate("xyz"):
        peak = axis_values[:, i].max()
        assert levels.axis_peaks_hz_per_t[axis] == pytest.approx(
            peak, rel=1e-9, abs=1e-12 * total.max()
        )
    assert levels.peak_time_s == pytest.approx(
        (np.flatnonzero(total >= total.max() * (1 - PEAK_TOLERANCE))[0] + 0.5) * dt, abs=1e-12
    )
    # The total of a sample at 0 can be a rounding residue of about 1e-16 of the peak, where a
    # sample at the last point of a ramp is not exactly 0 in one of the two paths.
    atol = 1e-12 * total.max()
    np.testing.assert_allclose(levels.level_max_hz_per_t, total, rtol=1e-6, atol=atol)
    np.testing.assert_allclose(levels.level_min_hz_per_t, total, rtol=1e-6, atol=atol)


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
    """`GradientSampler._from_parts` gives, bit for bit, the values of `GradientSampler(snap)`,
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
    got = gradient_sampler(snap).sample("gx", t)
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
    got_gx = sampler.block_samples("gx", 0, 2, dt)
    # A division (the linear-interpolation formula) makes exact equality unlikely: the
    # implementation and this test compute the ramp fraction with a different order of
    # floating-point operations.
    np.testing.assert_allclose(got_gx, expected_gx, rtol=1e-12, atol=1e-12 * amp)

    # gy has no event anywhere in the file: 0 for every sample of both blocks.
    got_gy = sampler.block_samples("gy", 0, 2, dt)
    np.testing.assert_array_equal(got_gy, np.zeros(2 * n_block, dtype=np.float64))

    # Block 1 (the delay) has no event on any axis: 0 for gx and gz too.
    np.testing.assert_array_equal(got_gx[n_block:], np.zeros(n_block, dtype=np.float64))
    got_gz = sampler.block_samples("gz", 0, 2, dt)
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
    part = sampler.block_samples("gx", 2, 3, dt, skip=60, count=60)
    assert not np.any(part)
    assert np.any(sampler.block_samples("gx", 2, 3, dt, skip=20, count=40))


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
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt), [amp, 0.0])
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt, skip=0, count=1), [amp])
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt, skip=1, count=1), [0.0])


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
    got = sampler.block_samples("gx", 0, 1, dt)
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
    got = sampler.block_samples("gx", 0, 2, _RASTER)
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
    got = sampler.block_samples("gx", 0, 2, _RASTER)
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
        got = sampler.block_samples(f"g{axis}", 0, index.num_blocks, _RASTER)
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
