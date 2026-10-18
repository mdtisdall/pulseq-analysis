import pytest

pytestmark = pytest.mark.pypulseq
pytest.importorskip("pypulseq")

import dataclasses
import math

import numpy as np
import pypulseq as pp
from asserts import assert_block_values_equal
from gap_sequences import (
    DT,
    A,
    U,
    extended,
    long_gap_sequence,
    non_zero_ends_sequence,
    sequence,
    vector_sequence,
    zero_gap_sequence,
)
from oracles import waveform as oracle
from oracles.blocks import sequence_of
from scale_sequences import build_repeating
from synthetic import (
    SYSTEM,
    gre_sequence,
    spin_echo_sequence,
    waveform_sequence,
)

from pulseq_analysis._equality import FrozenDict
from pulseq_analysis.analyses import grad_peaks, load
from pulseq_analysis.analyses.grad_peaks import (
    AxisResult,
    GradientPeaks,
    block_gradient_values,
    gradient_peaks,
)
from pulseq_analysis.synth._played import played_gradients
from pulseq_analysis.synth.seq_index import (
    NO_GRADIENTS,
    NO_GRADIENTS_IN_WINDOW,
    sequence_index,
)
from pulseq_analysis.synth.seq_utils import _AXES, TIME_TOLERANCE
from pulseq_analysis.synth.snapshot import Snapshot

# The writer rounds an amplitude and the values of a shape to 6 significant digits, so a value
# read from a written file is within about 1.2e-6 of the value in memory. The tests that compare
# a read value with the builder's value allow this.
_WRITER_REL = 1e-5
# For a step, the difference of two written values: its error is larger in proportion to it.
_WRITER_STEP_REL = 1e-4


def test_trapezoid_peak_slew_and_rms_match_hand_computed_values():
    """A single x trapezoid: the peak amplitude, the peak slew and the RMS amplitude
    equal values computed by hand from the trapezoid's own rise time, flat time and
    amplitude."""
    amplitude = 0.5 * SYSTEM.max_grad  # Hz/m
    gx = pp.make_trapezoid(
        channel="x", amplitude=amplitude, rise_time=200e-6, flat_time=1e-3, system=SYSTEM
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)
    (block_id,) = seq.block_events

    snap = load(seq)
    result = gradient_peaks(snap)

    peak_hz_per_m = amplitude
    slew_hz_per_m_per_s = amplitude / gx.rise_time
    # RMS^2 * duration is the integral of amplitude^2 dt: the rising ramp contributes
    # amplitude^2 * rise_time / 3 (the integral of (amplitude * t / rise_time)^2 from 0
    # to rise_time), the falling ramp contributes the same by symmetry, and the flat
    # top contributes amplitude^2 * flat_time.
    duration = sum(seq.block_durations.values())
    energy = 2 * (gx.rise_time * amplitude**2 / 3) + gx.flat_time * amplitude**2
    rms_hz_per_m = math.sqrt(energy / duration)

    axis = result.axes["x"]
    assert result.reason is None
    assert axis.peak_hz_per_m == pytest.approx(peak_hz_per_m)
    assert axis.peak_block == block_id
    assert axis.max_slew_hz_per_m_per_s == pytest.approx(slew_hz_per_m_per_s)
    assert axis.slew_block == block_id
    assert axis.rms_hz_per_m == pytest.approx(rms_hz_per_m)


def _assert_limits_equal(a: GradientPeaks, b: GradientPeaks) -> None:
    """Every field of two `GradientPeaks` is exactly equal."""
    assert a.reason == b.reason
    assert a.range_s == b.range_s
    assert list(a.axes) == list(b.axes)
    for axis in a.axes:
        assert a.axes[axis] == b.axes[axis]
    assert a.vector_peak_hz_per_m == b.vector_peak_hz_per_m
    assert a.vector_peak_time_s == b.vector_peak_time_s
    assert a.vector_peak_block == b.vector_peak_block


def test_the_values_of_a_negated_waveform_are_equal():
    """The same sequence with each amplitude times -1 gives exactly equal values of
    `gradient_peaks` (with and without a window) and `block_gradient_values`: a value is
    a magnitude, so it does not depend on the sign of a gradient, or of a gamma."""
    positive = load(waveform_sequence(SYSTEM))
    negative = load(waveform_sequence(SYSTEM, sign=-1.0))
    window = (0.0, sequence_index(positive).end_s / 2)

    assert gradient_peaks(positive).reason is None
    _assert_limits_equal(gradient_peaks(positive), gradient_peaks(negative))
    _assert_limits_equal(
        gradient_peaks(positive, window=window), gradient_peaks(negative, window=window)
    )
    assert_block_values_equal(block_gradient_values(positive), block_gradient_values(negative))


def test_no_gradients_sets_reason():
    """A sequence with no gradient at all: `reason` is set, and every numeric
    field is its zero value (0.0, or None for a block field)."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(2e-3))

    snap = load(seq)
    result = gradient_peaks(snap)

    assert result.reason == NO_GRADIENTS
    assert result.vector_peak_hz_per_m == 0.0
    assert result.vector_peak_time_s == 0.0
    for axis in ("x", "y", "z"):
        a = result.axes[axis]
        assert a.peak_hz_per_m == 0.0
        assert a.peak_block is None
        assert a.max_slew_hz_per_m_per_s == 0.0
        assert a.slew_block is None
        assert a.rms_hz_per_m == 0.0


def test_largest_over_several_blocks_and_axes_credits_the_first_block_with_that_value():
    """With several blocks on several axes, the peak amplitude and the peak slew of
    each axis are the largest over every block that has an event on that axis, and the
    credited block is the first block, in play order, whose event reaches that value
    (a later block with the very same event does not move the credit)."""
    gx_small = pp.make_trapezoid(
        channel="x",
        amplitude=0.2 * SYSTEM.max_grad,
        rise_time=100e-6,
        flat_time=200e-6,
        system=SYSTEM,
    )
    gx_big = pp.make_trapezoid(
        channel="x",
        amplitude=0.8 * SYSTEM.max_grad,
        rise_time=250e-6,
        flat_time=200e-6,
        system=SYSTEM,
    )
    gy = pp.make_trapezoid(
        channel="y",
        amplitude=0.5 * SYSTEM.max_grad,
        rise_time=200e-6,
        flat_time=100e-6,
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx_small)
    seq.add_block(gy)
    seq.add_block(gx_big)
    seq.add_block(gx_big)  # the same event again: the credit must stay on the first block
    block_ids = list(seq.block_events)

    snap = load(seq)
    result = gradient_peaks(snap)

    assert result.axes["x"].peak_hz_per_m == pytest.approx(0.8 * SYSTEM.max_grad)
    assert result.axes["x"].peak_block == block_ids[2]
    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(
        0.8 * SYSTEM.max_grad / gx_big.rise_time
    )
    assert result.axes["x"].slew_block == block_ids[2]
    assert result.axes["y"].peak_hz_per_m == pytest.approx(0.5 * SYSTEM.max_grad)
    assert result.axes["y"].peak_block == block_ids[1]


def test_window_that_cuts_a_ramp_gives_the_slew_of_the_part_inside_the_window():
    """A window that includes only part of an extended trapezoid, over a segment with a
    smaller slope than another segment outside the window: the slew over the window is
    the slope of the part inside the window, not the largest slope of the whole event, and its
    time is the window start, where the window cuts that segment."""
    mg = SYSTEM.max_grad
    times = [0.0, 200e-6, 400e-6, 900e-6, 1100e-6]
    amplitudes = [0.0, 0.1 * mg, 0.15 * mg, 0.15 * mg, 0.0]
    gx = pp.make_extended_trapezoid(channel="x", times=times, amplitudes=amplitudes, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)
    window = (100e-6, 300e-6)  # inside the first two segments; the steepest segment
    # (900 to 1100 us, 750 * mg) is outside the window.

    snap = load(seq)
    result = gradient_peaks(snap, window=window)

    expected_slew_hz_per_m_per_s = 500 * mg  # the slope of the 0-200 us segment

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(
        expected_slew_hz_per_m_per_s, rel=_WRITER_REL
    )
    assert result.axes["x"].slew_time_s == pytest.approx(100e-6)


def test_slew_time_is_the_start_of_the_steepest_segment():
    """An extended trapezoid whose steepest segment is its last one (900 to 1100 us): the
    slew time is the start of that segment, 900 us."""
    mg = SYSTEM.max_grad
    times = [0.0, 200e-6, 400e-6, 900e-6, 1100e-6]
    amplitudes = [0.0, 0.1 * mg, 0.15 * mg, 0.15 * mg, 0.0]
    gx = pp.make_extended_trapezoid(channel="x", times=times, amplitudes=amplitudes, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)

    snap = load(seq)
    result = gradient_peaks(snap)

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(750 * mg, rel=_WRITER_REL)
    assert result.axes["x"].slew_time_s == pytest.approx(900e-6)


def test_junction_step_equal_to_a_segment_slope_of_its_block_takes_the_credit():
    """Block 1 ends at A. Block 2 starts at 0 and its steepest segment (0 to A in one
    raster) has the slope of the junction step A to 0. The two slews are equal and the
    junction is at the block start, before the segment: the slew time is the start of
    block 2 and not a time in block 2, and the slew block is block 2."""
    raster = SYSTEM.grad_raster_time
    a = 0.5 * SYSTEM.max_slew * raster
    one = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, a, a]),
        times=np.array([0.0, 2, 3]) * raster,
        system=SYSTEM,
    )
    two = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, 0.0, a, a, 0.0]),
        times=np.array([0.0, 1, 2, 6, 8]) * raster,
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(one)
    seq.add_block(two)
    block_ids = list(seq.block_events)

    snap = load(seq)
    x = gradient_peaks(snap).axes["x"]

    assert x.max_slew_hz_per_m_per_s == pytest.approx(a / raster)
    assert x.slew_time_s == pytest.approx(3 * raster)
    assert x.slew_block == block_ids[1]


def test_segment_of_an_earlier_block_with_the_slew_of_a_junction_step_takes_the_credit():
    """Block 1 has a segment from 0 to A in one raster, and block 2 starts at A after block 1
    ends at 0: the junction step 0 to A divided by the raster has the slope of that segment, and
    no other value is as large. The two slews are equal, and the earlier block takes the credit,
    so the slew block is block 1 and the slew time is the start of its first segment, 0, not the
    junction time, the start of block 2.

    Block 1 has the amplitudes [0, A, A, 0] at the times [0, 1, 3, 5] rasters, and block 2 has
    [A, A, 0] at [0, 2, 4] rasters, with A = 0.5 * max_slew * raster. The slopes are A / raster
    (block 1, rise), 0 (flat), A / (2 raster) (block 1, fall), 0 (block 2, flat) and A / (2
    raster) (block 2, fall). The junction steps are 0 (block 1) and A / raster (block 2)."""
    raster = SYSTEM.grad_raster_time
    a = 0.5 * SYSTEM.max_slew * raster
    one = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, a, a, 0.0]),
        times=np.array([0.0, 1, 3, 5]) * raster,
        system=SYSTEM,
    )
    two = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([a, a, 0.0]),
        times=np.array([0.0, 2, 4]) * raster,
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(one)
    seq.add_block(two)
    block_ids = list(seq.block_events)
    snap = load(seq)
    values = block_gradient_values(snap)
    assert values.junction_hz_per_m_per_s["x"][1] == values.slew_hz_per_m_per_s["x"][0]

    x = gradient_peaks(snap).axes["x"]

    assert x.max_slew_hz_per_m_per_s == pytest.approx(a / raster)
    assert x.slew_block == block_ids[0]
    assert x.slew_time_s == 0.0


def test_vector_peak_of_g_compares_different_triples_across_blocks():
    """Two blocks with different triples of active gradients: the vector peak of `|G|`
    is the largest magnitude found across the two different triples, not just the
    largest single-axis peak, and its block and time are those of block B (the end of its
    rise, after the 0.8 ms of block A)."""
    amp_a = 0.9 * SYSTEM.max_grad
    gx_a = pp.make_trapezoid(
        channel="x", amplitude=amp_a, rise_time=300e-6, flat_time=200e-6, system=SYSTEM
    )
    amp_b = 0.7 * SYSTEM.max_grad
    gx_b = pp.make_trapezoid(
        channel="x", amplitude=amp_b, rise_time=200e-6, flat_time=200e-6, system=SYSTEM
    )
    gy_b = pp.make_trapezoid(
        channel="y", amplitude=amp_b, rise_time=200e-6, flat_time=200e-6, system=SYSTEM
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx_a)
    seq.add_block(gx_b, gy_b)

    snap = load(seq)
    result = gradient_peaks(snap)

    expected_vector_peak_hz_per_m = math.sqrt(2) * amp_b
    assert expected_vector_peak_hz_per_m > amp_a  # block B's triple wins
    assert result.vector_peak_hz_per_m == pytest.approx(expected_vector_peak_hz_per_m)
    _block_a_id, block_b_id = seq.block_events
    assert result.vector_peak_block == block_b_id
    assert result.vector_peak_time_s == pytest.approx(1.0e-3)


# ---- Junction steps ----
#
# `add_block` checks the step at every block junction against
# `max_slew * grad_raster_time`. The gradient limits card (pulseq-reports) reports that
# step, divided by `grad_raster_time`, as part of the axis's slew, whenever it is the largest
# value found (segment or junction). These sequences are built so that the step is larger than
# every segment's own slope, so the tests show the step is really included. A step across a zero
# gap is a junction of the block after it. A first value after a delay and a last value before
# the end of the block have a long gap (the gap tests below): the ramps, and not a junction.

_RASTER = SYSTEM.grad_raster_time
_MAX_STEP = SYSTEM.max_slew * _RASTER  # the largest step add_block accepts


def test_gradient_ending_non_zero_at_the_last_point_of_the_axis_has_a_step_in_its_own_block():
    """A gradient that ends at a non-zero value (within the tolerance `add_block` accepts) and
    is the last event of the axis, with a block with no gradient after it: the step to 0 is at the
    last point of the event (0.2 ms). It is the largest slew (the value divided by the raster,
    10 times the slope of the rise), and it is credited to the block of the event, not to the
    block after it."""
    last_value = 0.9 * _MAX_STEP
    seq = _gradient_ends_non_zero_before_delay_sequence()
    block_a_id, _block_b_id = seq.block_events

    snap = load(seq)
    result = gradient_peaks(snap)

    expected_slew_hz_per_m_per_s = last_value / _RASTER
    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)
    assert result.axes["x"].slew_block == block_a_id
    assert result.axes["x"].slew_time_s == pytest.approx(200e-6, abs=1e-12)


def _end_step_sequence(flat_time: float, early: float = 0.0) -> pp.Sequence:
    """An x trapezoid with a slope of 1e9 Hz/m/s that ends at 0 after 100 µs + `flat_time` +
    100 µs, then a block of 0.6 ms with an x extended trapezoid that ends at `A` (the step to 0
    is `A / DT`, 3.19e9 Hz/m/s, above the slope of the trapezoid). The last point of the extended
    trapezoid is `early` before the end of its block, which is the end of the sequence.
    pypulseq accepts an `early` of 0, of up to 1e-9 s (the time is on the raster within that
    tolerance), or of a multiple of the gradient raster."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_trapezoid(
            channel="x", amplitude=1e5, rise_time=100e-6, flat_time=flat_time, system=SYSTEM
        )
    )
    seq.add_block(extended([0.0, 100e-6, 600e-6 - early], [0.0, A, A]), pp.make_delay(600e-6))
    return seq


@pytest.mark.parametrize("k", range(20))
def test_a_gradient_that_ends_at_the_end_of_the_sequence_has_no_step(k):
    """A gradient that ends at `A` at the end of the sequence: the step to 0 after its last
    point is in no range, so the largest slew is the 1e9 Hz/m/s of the trapezoid, in block 1.
    The 20 values of `k` give 20 end times, for which `(start + delay) + shape_dur` and `end_s`
    can differ by one ulp."""
    seq = _end_step_sequence((5 + k) * DT)
    block_a_id, _block_b_id = seq.block_events

    snap = load(seq)
    result = gradient_peaks(snap).axes["x"]
    assert result.max_slew_hz_per_m_per_s == pytest.approx(1e9, rel=1e-6)
    assert result.slew_block == block_a_id
    slew = block_gradient_values(snap).slew_hz_per_m_per_s["x"]
    assert slew[0] == pytest.approx(1e9, rel=1e-6)
    assert slew[1] == pytest.approx(A / 100e-6, rel=1e-6)
    assert oracle.peaks(seq)["x"]["max_slew"] == pytest.approx(1e9, rel=1e-6)
    assert oracle.peaks(seq)["x"]["slew_block"] == block_a_id


def test_window_inside_a_block_with_no_gradient_ignores_the_step_to_zero_before_it():
    """A window entirely inside a block with no gradient, after a gradient event that ends at a
    non-zero value (within the tolerance `add_block` accepts) in the block before: the step to 0
    is at the end of the event, before the window start, so it is not used, and the window has
    no gradient event and 0 slew. A window that starts exactly at the time of the step has it (a
    step counts for `lo <= time < hi`), credited to the block of the event. A window that ends at
    that time does not have it: its slew is the slope of the rise of the event."""
    step = 0.9 * _MAX_STEP
    seq = _gradient_ends_non_zero_before_delay_sequence()
    block_a_id, _block_b_id = seq.block_events

    snap = load(seq)
    inside_result = gradient_peaks(snap, window=(0.5e-3, 1.0e-3))
    assert inside_result.reason == NO_GRADIENTS_IN_WINDOW
    assert inside_result.axes["x"].max_slew_hz_per_m_per_s == 0.0
    assert inside_result.axes["x"].slew_block is None

    at_the_step = gradient_peaks(snap, window=(0.2e-3, 1.0e-3))
    assert at_the_step.reason is None
    assert at_the_step.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(step / _RASTER)
    assert at_the_step.axes["x"].slew_block == block_a_id

    before_the_step = gradient_peaks(snap, window=(0.0, 0.2e-3))
    assert before_the_step.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(step / 100e-6)
    assert before_the_step.axes["x"].slew_block == block_a_id


def _tie_trapezoid(channel: str):
    """A trapezoid of 0.8 ms: rise 0 to 0.2 ms, flat to 0.6 ms, fall to 0.8 ms."""
    return pp.make_trapezoid(
        channel=channel,
        amplitude=0.5 * SYSTEM.max_grad,
        rise_time=200e-6,
        flat_time=400e-6,
        system=SYSTEM,
    )


def test_window_that_cuts_a_block_credits_it_on_a_tie_with_a_later_block():
    """A window that starts in the flat top of block 1, then block 2 with the same trapezoid
    fully inside the window: the two blocks reach the same peak and the same slew (the fall
    ramp of block 1 is fully inside the window), so both are credited to block 1, the first in
    play order, and the peak time is the window start, the first time block 1 reaches the
    peak."""
    g = _tie_trapezoid("x")
    seq = pp.Sequence(SYSTEM)
    seq.add_block(g)
    seq.add_block(g)
    seq.add_block(pp.make_delay(1e-3))
    block_1_id = next(iter(seq.block_events))

    snap = load(seq)
    result = gradient_peaks(snap, window=(0.4e-3, 2.0e-3))

    axis = result.axes["x"]
    assert axis.peak_block == block_1_id
    assert axis.peak_time_s == pytest.approx(0.4e-3)
    assert axis.slew_block == block_1_id
    assert result.vector_peak_time_s == pytest.approx(0.4e-3)


def test_vector_peak_time_on_a_tie_is_the_first_time_in_play_order():
    """The same trapezoid on x in block 1 and on y in block 2: |G| reaches the same peak in
    both blocks, from two different triples of events, and the vector peak time is the first
    time that block 1 reaches it (the end of its rise, 0.2 ms), not a time in block 2, and the
    vector peak block is block 1."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(_tie_trapezoid("x"))
    seq.add_block(_tie_trapezoid("y"))

    snap = load(seq)
    result = gradient_peaks(snap)

    assert result.vector_peak_time_s == pytest.approx(200e-6)
    assert result.vector_peak_block == next(iter(seq.block_events))


# Block 1 (20 us) has x at 3e5 Hz/m from 0 to 20 us + 0.5 ps: its time shape ends 5e-8 gradient
# rasters after the end of the block, which `spec` accepts (1 ps, `spec.TOLERANCE_NS`). Block 2
# (20 us) has y from 4e5 Hz/m at 20 us, flat for 10 us, then down to 0.
_TIE_IN_A_LATER_BLOCK = """\
[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

[BLOCKS]
1 2 0 1 0 0 0 0
2 2 0 0 2 0 0 0

[GRADIENTS]
1 300000 300000 300000 1 2 0
2 400000 400000 0 3 4 0

[SHAPES]

shape_id 1
num_samples 2
1
1

shape_id 2
num_samples 2
0
2.00000005

shape_id 3
num_samples 3
1
1
0

shape_id 4
num_samples 3
0
1
2
"""


def test_vector_peak_tie_goes_to_the_earliest_time_when_a_later_block_has_it(tmp_path):
    """|G| is 5e5 Hz/m (3e5 on x, 4e5 on y) just after 20 us, where y starts, and just before
    20 us + 0.5 ps, where x ends. Within `TIME_TOLERANCE`, the value after 20 us is credited to
    block 2 and the value before 20 us + 0.5 ps to block 1, so block 1, the first block in play
    order with the largest value, has the later time. The vector peak goes to the earliest time:
    20 us, in block 2, for the whole file and for a window that cuts block 1."""
    path = tmp_path / "tie.seq"
    path.write_text(_TIE_IN_A_LATER_BLOCK)
    snap = load(path)

    blocks = block_gradient_values(snap)
    assert blocks.block_id.tolist() == [1, 2]
    assert blocks.vector_peak_hz_per_m.tolist() == [5e5, 5e5]
    assert blocks.vector_peak_time_s[0] == pytest.approx(20e-6 + 0.5e-12, rel=0, abs=1e-14)
    assert blocks.vector_peak_time_s[1] == pytest.approx(20e-6, rel=0, abs=1e-14)

    for result in (gradient_peaks(snap), gradient_peaks(snap, window=(10e-6, 40e-6))):
        assert result.vector_peak_hz_per_m == 5e5
        assert result.vector_peak_time_s == pytest.approx(20e-6, rel=0, abs=1e-14)
        assert result.vector_peak_block == 2


def test_axis_whose_only_event_is_zero_credits_no_block():
    """A y event scaled to amplitude 0 (as a phase encode loop makes for the centre line of
    k-space), with an x trapezoid in the same block: the y axis has a peak and a slew of 0, and
    no block is credited for either."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(_tie_trapezoid("x"), pp.scale_grad(_tie_trapezoid("y"), 0.0))

    snap = load(seq)
    result = gradient_peaks(snap)

    axis = result.axes["y"]
    assert axis.peak_hz_per_m == 0.0
    assert axis.max_slew_hz_per_m_per_s == 0.0
    assert axis.peak_block is None
    assert axis.slew_block is None


# ---- Comparisons with the oracle ----
#
# `tests/oracles/waveform.py` is the oracle of the model of the module docstring of `grad_peaks`
# (the model of MATLAB Pulseq). It builds the polyline of each axis one time, with the ramps of
# the long gaps, and it reads every value from it with no per-block code. Its own code calls no
# code of this package, but its input here is not independent of it: `sequence_of(snap)`
# (`tests/oracles/blocks.py`) gives it the events that `_played.played_gradients(snap)` gives
# this package too (the event of each block and axis, and the points of each event), with the
# block durations and the gradient raster of the snapshot's data. The oracle adds up the block
# starts, joins the events by the gap rule, and finds each value, its time and its block itself.
# So these comparisons test the measurements of the played events, not the decoding, which has
# its own tests (`test_played.py`, `test_decoding.py`, and the C++ and MATLAB oracle tests).
# `oracle.peaks(seq, window)` gives the values of the package: the peak, the
# slew, the RMS and the vector peak, each with its time and its block. The test here compares all
# of them, for the whole file and for windows, on random sequences. The comparisons on the
# synthetic sequences and on the sequences of the oracle's own tests are in the tests of the
# `cpp-siemens` plugin (`packages/pulseq-cpp-siemens/tests/test_measurements_in_pulseq_analysis.py`),
# which load them through `cpp-siemens` and use the helpers of this file.
#
# The package sums and maxes per unique event; the oracle sums and maxes on the polyline, after
# adding the start of each block to the event's corner times before it differences them for a
# slope. When a sequence plays one event in several blocks at different start times (for
# example `tests/synthetic.gre_sequence`'s readout, once each TR), the oracle gets a very
# slightly different slope for the same event at each occurrence: each corner time `start +
# offset` is rounded to about machine eps times the start time, and a slope divides the
# difference of two such times by the segment's duration. The tolerance is therefore derived
# from each sequence (the user, 2026-09-28): `1e-12 + 4 * eps * duration / shortest segment`
# (`_rounding_tol`), relative to the value or to the limit of the same kind. The rounding can
# also make the oracle credit a slew of a repeated event to a later block, or to another
# segment of equal slope in the same block (the rise and the fall of a symmetric trapezoid).
# For the slew, the comparisons accept another item of the oracle's polyline with the same
# slope (`_assert_slew_item`). The block of the peak of each axis and the block of the vector
# peak must be the oracle's. The tests with hand-computed values use events that are not
# repeated and check the block and the time exactly.


def _rounding_tol(snap: Snapshot) -> float:
    """`1e-12 + 4 * eps * duration / shortest segment`: the rounding of the oracle's
    absolute corner times (`block start + offset`, about eps times the duration), divided
    by the shortest time between two corner points of any gradient event of `snap`."""
    seq = sequence_of(snap)
    duration = float(sum(seq.block_durations.values()))
    shortest = math.inf
    for _, offsets, _ in played_gradients(snap).points.values():
        steps = np.diff(np.asarray(offsets, dtype=float))
        steps = steps[steps > 0]
        if steps.size:
            shortest = min(shortest, float(steps.min()))
    if not math.isfinite(shortest):
        return 1e-12
    # The ramps (half a raster time) are the shortest segments of a gap.
    shortest = min(shortest, seq.grad_raster_time / 2)
    return 1e-12 + 4 * np.finfo(float).eps * duration / shortest


def _assert_close(actual: float, expected: float, scale: float, tol: float, label: str) -> None:
    bound = max(abs(expected) * tol, scale * tol)
    assert abs(actual - expected) <= bound, (
        f"{label}: {actual!r} != {expected!r} (tolerance {bound!r})"
    )


def _assert_slew_item(
    seq: pp.Sequence,
    axis: str,
    window: tuple[float, float] | None,
    ours: AxisResult,
    theirs: dict,
    bound: float,
) -> None:
    """The time and the block of the slew of this package are the oracle's, or they are those of
    another item of the polyline of `axis` with a slope within `bound` of the largest slope: a
    segment of `TIME_TOLERANCE` or more in the window (its time is the start of its cut, its block
    the block of its end point), or a step with `lo <= time < hi` and
    `time < end - TIME_TOLERANCE`. Two items of equal slope (the rise and the fall of a symmetric
    trapezoid, or the same event in two blocks) have slopes that differ by the rounding of the
    times, so the oracle can pick the other one."""
    if (
        ours.slew_time_s == pytest.approx(theirs["slew_time"], rel=0, abs=1e-12)
        and ours.slew_block == theirs["slew_block"]
    ):
        return
    poly = oracle.axis_polyline(seq, axis)
    end = float(poly.block_end[-1])
    lo, hi = window if window is not None else (0.0, end)
    step_hi = min(hi, end - TIME_TOLERANCE)
    items = []
    for s in range(poly.t.size - 1):
        t0, t1 = poly.t[s], poly.t[s + 1]
        a, b = max(t0, lo), min(t1, hi)
        if b - a >= TIME_TOLERANCE and not poly.segment_is_step[s]:
            slope = abs(poly.g[s + 1] - poly.g[s]) / (t1 - t0)
            items.append((slope, a, poly.block_id[poly.point_play[s + 1]]))
    for time, size, play in zip(poly.step_time, poly.step_size, poly.step_play, strict=True):
        if lo <= time < step_hi:
            items.append((abs(size) / seq.grad_raster_time, time, poly.block_id[play]))
    assert any(
        abs(slope - theirs["max_slew"]) <= bound
        and abs(time - ours.slew_time_s) <= 1e-12
        and block == ours.slew_block
        for slope, time, block in items
    ), f"{axis} slew: ({ours.slew_time_s!r}, {ours.slew_block!r}) is not an item of the polyline"


def _assert_matches_oracle(
    ours: GradientPeaks,
    theirs: dict,
    tol: float,
    seq: pp.Sequence,
    window: tuple[float, float] | None = None,
) -> None:
    """The values of this package match `theirs`, the values of `oracle.peaks(seq, window)`.
    The time of the peak of each axis and the time of the vector peak are equal to 1e-12 s, the
    block of the peak of each axis and the block of the vector peak are the oracle's, and the
    time and the block of the slew are the oracle's or another item with the same slope
    (`_assert_slew_item`). `seq` is the sequence of both results."""
    # The scale of the tolerance: the limits of `SYSTEM`, which the sequences of the tests have
    # (`raster_4us_sequence` has others, of the same order). `sequence_of` has no `system.max_grad`.
    grad_scale, slew_scale = SYSTEM.max_grad, SYSTEM.max_slew
    for axis in _AXES:
        a, b = ours.axes[axis], theirs[axis]
        _assert_close(a.peak_hz_per_m, b["peak"], grad_scale, tol, f"{axis} peak")
        _assert_close(a.max_slew_hz_per_m_per_s, b["max_slew"], slew_scale, tol, f"{axis} slew")
        _assert_close(a.rms_hz_per_m, b["rms"], grad_scale, tol, f"{axis} rms")
        assert a.peak_time_s == pytest.approx(b["peak_time"], rel=0, abs=1e-12), f"{axis} peak time"
        assert a.peak_block == b["peak_block"], f"{axis} peak_block"
        _assert_slew_item(seq, axis, window, a, b, slew_scale * tol)
    _assert_close(ours.vector_peak_hz_per_m, theirs["vector_peak"], grad_scale, tol, "vector peak")
    assert ours.vector_peak_time_s == pytest.approx(theirs["vector_peak_time"], rel=0, abs=1e-12)
    assert ours.vector_peak_block == theirs["vector_peak_block"]


def _oracle_windows(snap: Snapshot, rng: np.random.Generator, count: int) -> list:
    """`count` windows of `snap` with their ends where the rules of the model cut a gradient:
    on a start or an end of a block, on a point of a polyline of the oracle, half a raster time
    before or after one (a ramp point), on a multiple of 2.5 us, at random, and within 1.5 ns of
    a start or an end of a block (the tolerance of the block of a time). A window shorter
    than `TIME_TOLERANCE` is not made: its values are of a part of a segment that is shorter than
    the tolerance of a time."""
    index = sequence_index(snap)
    total = index.end_s
    times = [index.start_s, index.start_s + index.duration_s]
    for axis in _AXES:
        t = oracle.axis_polyline(sequence_of(snap), axis).t
        times += [
            t,
            t - sequence_of(snap).grad_raster_time / 2,
            t + sequence_of(snap).grad_raster_time / 2,
        ]
    edges = np.concatenate([index.start_s, index.start_s + index.duration_s])
    pools = [
        np.clip(np.concatenate(times), 0.0, total),
        np.round(rng.uniform(0.0, total, 60) / 2.5e-6) * 2.5e-6,
        rng.uniform(0.0, total, 60),
        np.clip(
            edges + rng.choice([-1.5e-9, -3e-10, -1e-12, 1e-12, 3e-10, 1.5e-9], edges.size),
            0,
            total,
        ),
    ]
    windows = []
    for i in range(count):
        start, end = np.sort(np.clip(rng.choice(pools[i % 4], size=2), 0.0, total))
        if end - start >= TIME_TOLERANCE:
            windows.append((float(start), float(end)))
    return windows


def _assert_matches_oracle_on_windows(snap: Snapshot, windows: list) -> None:
    """`gradient_peaks` matches the oracle on the whole file and on each of `windows`."""
    tol = _rounding_tol(snap)
    seq = sequence_of(snap)
    for window in [None, *windows]:
        _assert_matches_oracle(
            gradient_peaks(snap, window=window), oracle.peaks(seq, window), tol, seq, window
        )


def _zero_ended_trapezoid(rng: np.random.Generator, channel: str):
    amplitude = rng.uniform(0.05, 0.8) * SYSTEM.max_grad * rng.choice([-1.0, 1.0])
    min_rise = abs(amplitude) / (0.7 * SYSTEM.max_slew)
    rise_time = math.ceil(max(min_rise, 50e-6) / _RASTER) * _RASTER
    flat_time = round(rng.uniform(0.0, 500e-6) / _RASTER) * _RASTER
    return pp.make_trapezoid(
        channel=channel,
        amplitude=amplitude,
        rise_time=rise_time,
        flat_time=flat_time,
        system=SYSTEM,
    )


def _zero_ended_extended_trapezoid(rng: np.random.Generator, channel: str):
    peak = rng.uniform(0.05, 0.6) * SYSTEM.max_grad * rng.choice([-1.0, 1.0])
    min_ramp = abs(peak) / (0.7 * SYSTEM.max_slew)
    ramp = math.ceil(max(min_ramp, 50e-6) / _RASTER) * _RASTER
    flat = round(rng.uniform(_RASTER, 300e-6) / _RASTER) * _RASTER
    times = [0.0, ramp, ramp + flat, 2 * ramp + flat]
    amplitudes = [0.0, peak, peak, 0.0]
    return pp.make_extended_trapezoid(
        channel=channel, times=times, amplitudes=amplitudes, system=SYSTEM
    )


_ARB_N = 50
_ARB_SHAPE = np.sin(np.pi * np.arange(1, _ARB_N + 1) / (_ARB_N + 1))


def _zero_ended_arbitrary(rng: np.random.Generator, channel: str):
    amplitude = rng.uniform(0.05, 0.3) * SYSTEM.max_grad * rng.choice([-1.0, 1.0])
    # first and last default to a linear extrapolation of the waveform's own edge
    # samples (pypulseq's make_arbitrary_grad), not to 0: pass them explicitly so this
    # event, like the other two builders, starts and ends at 0.
    return pp.make_arbitrary_grad(
        channel=channel, waveform=_ARB_SHAPE * amplitude, first=0.0, last=0.0, system=SYSTEM
    )


_RANDOM_EVENT_BUILDERS = [
    _zero_ended_trapezoid,
    _zero_ended_extended_trapezoid,
    _zero_ended_arbitrary,
]


def _random_gradient_sequence(rng: np.random.Generator) -> pp.Sequence:
    """A sequence of 2 to 6 blocks, each with 0 to 3 random gradient axes, each a
    trapezoid, an extended trapezoid or an arbitrary gradient (`make_*` functions, so
    pypulseq's own checks apply) that starts and ends at 0, so every block junction
    step is 0 and no gap has a ramp."""
    seq = pp.Sequence(SYSTEM)
    n_blocks = int(rng.integers(2, 7))
    for _ in range(n_blocks):
        n_axes = int(rng.integers(0, 4))
        axes = rng.choice(["x", "y", "z"], size=n_axes, replace=False) if n_axes else []
        events = []
        for axis in axes:
            builder = _RANDOM_EVENT_BUILDERS[int(rng.integers(0, len(_RANDOM_EVENT_BUILDERS)))]
            events.append(builder(rng, str(axis)))
        if events:
            seq.add_block(*events)
        else:
            delay = round(rng.uniform(1e-4, 1e-3) / _RASTER) * _RASTER
            seq.add_block(pp.make_delay(delay))
    return seq


@pytest.mark.parametrize("seed", range(50))
def test_matches_oracle_on_random_gradient_sequences(seed):
    """50 random sequences of trapezoids, extended trapezoids and arbitrary gradients
    on random axes, each event starting and ending at 0 (so no gap has a step, a line or a ramp,
    and the values come from the events alone): `gradient_peaks` matches the oracle, on the
    whole file and on 6 windows (`_oracle_windows`), within `_rounding_tol` (see the comment
    above)."""
    rng = np.random.default_rng(seed)
    seq = _random_gradient_sequence(rng)
    snap = load(seq)
    windows = _oracle_windows(snap, rng, 6)
    _assert_matches_oracle_on_windows(snap, windows)


# ---- Values of each block (`block_gradient_values`) ----


def _junction_sequence() -> pp.Sequence:
    """Two x extended trapezoids with a step at their junction that is larger than every
    segment's own slope: block 1 ends at `x`, block 2 starts at `x - step`."""
    step = 0.9 * _MAX_STEP
    x = 0.3 * SYSTEM.max_grad
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x", times=[0.0, 100e-6, 200e-6], amplitudes=[0.0, x, x], system=SYSTEM
        )
    )
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            times=[0.0, 100e-6, 200e-6],
            amplitudes=[x - step, x - step, 0.0],
            system=SYSTEM,
        )
    )
    return seq


def _junction_and_segment_sequence() -> pp.Sequence:
    """The junction of `_junction_sequence`, and a first segment of block 2 that changes by the
    same step in one gradient raster: the junction step and that segment have the same slew."""
    step = 0.9 * _MAX_STEP
    x = 0.3 * SYSTEM.max_grad
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x", times=[0.0, 100e-6, 200e-6], amplitudes=[0.0, x, x], system=SYSTEM
        )
    )
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            times=[0.0, _RASTER, 200e-6],
            amplitudes=[x - step, x, x],
            system=SYSTEM,
        )
    )
    return seq


def _gradient_ends_non_zero_before_delay_sequence() -> pp.Sequence:
    last_value = 0.9 * _MAX_STEP
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            times=[0.0, 100e-6, 200e-6],
            amplitudes=[0.0, last_value, last_value],
            system=SYSTEM,
        )
    )
    seq.add_block(pp.make_delay(1e-3))
    return seq


def _first_block_starts_non_zero_sequence() -> pp.Sequence:
    start_value = 0.9 * _MAX_STEP
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            times=[0.0, 100e-6, 200e-6],
            amplitudes=[start_value, start_value, 0.0],
            system=SYSTEM,
        )
    )
    return seq


def test_block_without_an_event_on_an_axis_has_zero_values_and_its_start_as_time():
    """Block 1 has x and y gradients, block 2 only z, block 3 none: an axis without an event
    in a block has a peak, a slew and a junction step of 0 there, and the block start as the
    time. A block without gradients has vector peak 0 at its start. The values of the axes with
    an event are hand-computed from the trapezoids."""
    mg = SYSTEM.max_grad
    gy = pp.make_trapezoid(
        channel="y", amplitude=0.25 * mg, rise_time=100e-6, flat_time=200e-6, system=SYSTEM
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(_tie_trapezoid("x"), gy)  # x: 0.5 * mg, rise 0.2 ms
    seq.add_block(_tie_trapezoid("z"))
    seq.add_block(pp.make_delay(1e-3))

    snap = load(seq)
    values = block_gradient_values(snap)

    start_s = sequence_index(snap).start_s
    assert values.peak_hz_per_m["x"][0] == pytest.approx(0.5 * mg)
    assert values.peak_time_s["x"][0] == pytest.approx(200e-6)
    assert values.slew_hz_per_m_per_s["x"][0] == pytest.approx(0.5 * mg / 200e-6)
    assert values.peak_hz_per_m["y"][0] == pytest.approx(0.25 * mg)
    assert values.peak_hz_per_m["z"][1] == pytest.approx(0.5 * mg)
    assert values.peak_time_s["z"][1] == pytest.approx(start_s[1] + 200e-6)
    for axis, plays in (("x", [1, 2]), ("y", [1, 2]), ("z", [0, 2])):
        for play in plays:
            assert values.peak_hz_per_m[axis][play] == 0.0
            assert values.slew_hz_per_m_per_s[axis][play] == 0.0
            assert values.junction_hz_per_m_per_s[axis][play] == 0.0
            assert values.peak_time_s[axis][play] == start_s[play]
            assert values.slew_time_s[axis][play] == start_s[play]
    # Block 1: |G| is largest at 0.2 ms, where x has finished its rise and y is on its flat top.
    assert values.vector_peak_hz_per_m[0] == pytest.approx(math.hypot(0.5, 0.25) * mg)
    assert values.vector_peak_time_s[0] == pytest.approx(200e-6)
    assert values.vector_peak_hz_per_m[1] == pytest.approx(0.5 * mg)
    assert values.vector_peak_hz_per_m[2] == 0.0
    assert values.vector_peak_time_s[2] == start_s[2]


def test_a_zero_event_after_a_long_gap_has_the_start_of_its_block_as_slew_time():
    """Block 1 on x goes from 0 to U in 100 us, block 2 is a delay of 200 us, and block 3 has a
    trapezoid scaled to amplitude 0 (as a phase encode loop makes for the centre of k-space): a
    long gap with a ramp to 0 after block 1 and no ramp before block 3. The zero event has no
    slope and no ramp, so its slew is 0 and its slew time is the start of its block, 300 us, not
    the start of a ramp from 0 (295 us). Block 1 has the ramp to 0 as its slew, 2 U / DT at its
    last point, 100 us, and block 2 has no event, so 0 at its start, 100 us."""
    zero = pp.scale_grad(
        pp.make_trapezoid(
            channel="x",
            amplitude=U,
            rise_time=100e-6,
            flat_time=100e-6,
            fall_time=100e-6,
            system=SYSTEM,
        ),
        0.0,
    )
    seq = sequence(
        [extended([0, 100e-6], [0, U])],
        [pp.make_delay(200e-6)],
        [zero],
    )

    snap = load(seq)
    values = block_gradient_values(snap)

    np.testing.assert_allclose(values.start_s, [0.0, 100e-6, 300e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(values.peak_hz_per_m["x"], [U, 0.0, 0.0], rtol=1e-9)
    np.testing.assert_allclose(values.slew_hz_per_m_per_s["x"], [2 * U / DT, 0.0, 0.0], rtol=1e-9)
    np.testing.assert_allclose(
        values.slew_time_s["x"], [100e-6, 100e-6, 300e-6], rtol=0, atol=1e-12
    )


def test_junction_step_is_at_the_start_of_the_block_after_the_junction():
    """Block 1 ends at `x`, block 2 starts at `x - step` and ends at 0, and block 3 has no
    gradient: the step is in block 2 and is 0 in block 1 (0 before it) and in block 3 (it
    follows a block that ends at 0). A gradient that ends at a non-zero value before a block
    without a gradient has no junction in that block: the junction of a block with no event on the
    axis is 0. The step to 0 is in the slew of the block of the gradient."""
    step = 0.9 * _MAX_STEP
    seq = _junction_sequence()
    seq.add_block(pp.make_delay(1e-3))

    snap = load(seq)
    values = block_gradient_values(snap)

    np.testing.assert_array_equal(values.junction_hz_per_m_per_s["x"][[0, 2]], [0.0, 0.0])
    assert values.junction_hz_per_m_per_s["x"][1] == pytest.approx(
        step / _RASTER, rel=_WRITER_STEP_REL
    )

    last_value = 0.9 * _MAX_STEP
    after_delay = block_gradient_values(load(_gradient_ends_non_zero_before_delay_sequence()))
    np.testing.assert_array_equal(after_delay.junction_hz_per_m_per_s["x"], [0.0, 0.0])
    assert after_delay.slew_hz_per_m_per_s["x"][0] == pytest.approx(last_value / _RASTER)
    assert after_delay.slew_time_s["x"][0] == pytest.approx(200e-6, abs=1e-12)
    assert after_delay.slew_hz_per_m_per_s["x"][1] == 0.0


def test_block_gradient_values_are_in_play_order_with_one_entry_for_each_block():
    seq = gre_sequence(num_trs=3)
    snap = load(seq)
    index = sequence_index(snap)

    values = block_gradient_values(snap)

    assert index.num_blocks > 3
    np.testing.assert_array_equal(values.block_id, index.block_id)
    np.testing.assert_array_equal(values.start_s, index.start_s)
    arrays = [values.vector_peak_hz_per_m, values.vector_peak_time_s]
    for field in (
        values.peak_hz_per_m,
        values.peak_time_s,
        values.slew_hz_per_m_per_s,
        values.slew_time_s,
        values.junction_hz_per_m_per_s,
    ):
        assert list(field) == ["x", "y", "z"]
        arrays.extend(field.values())
    assert len(arrays) == 17
    for array in arrays:
        assert array.shape == (index.num_blocks,)
        assert array.dtype == np.float64
    assert np.all(np.diff(values.start_s) > 0.0)


def test_block_gradient_values_of_two_equal_sequences_are_equal_and_not_hashable():
    first = block_gradient_values(load(gre_sequence()))
    second = block_gradient_values(load(gre_sequence()))
    assert first is not second
    assert first == second
    assert first != block_gradient_values(load(gre_sequence(num_trs=5)))
    assert first != block_gradient_values(load(spin_echo_sequence()))
    with pytest.raises(TypeError):
        hash(first)


def test_gradient_peaks_of_two_equal_computations_are_equal_and_not_hashable():
    seq = spin_echo_sequence()
    window = (0.0, 1e-3)
    snap = load(seq)
    first, second = gradient_peaks(snap, window=window), gradient_peaks(snap, window=window)
    assert first is not second
    assert first == second
    assert gradient_peaks(load(spin_echo_sequence())) == gradient_peaks(load(spin_echo_sequence()))
    other = dataclasses.replace(first, vector_peak_hz_per_m=first.vector_peak_hz_per_m + 1.0)
    assert other != first
    assert first != gradient_peaks(snap, window=(0.0, 2e-3))
    with pytest.raises(TypeError):
        hash(first)


def test_axis_result_stays_hashable():
    result = gradient_peaks(load(spin_echo_sequence())).axes["x"]
    assert hash(result) == hash(dataclasses.replace(result))


_BLOCK_VALUE_DICTS = (
    "peak_hz_per_m",
    "peak_time_s",
    "slew_hz_per_m_per_s",
    "slew_time_s",
    "junction_hz_per_m_per_s",
)


def test_the_arrays_of_block_gradient_values_are_read_only_and_not_views_of_the_index():
    seq = gre_sequence()
    snap = load(seq)
    values = block_gradient_values(snap)
    index = sequence_index(snap)
    arrays = [values.block_id, values.start_s, values.vector_peak_hz_per_m]
    arrays.append(values.vector_peak_time_s)
    for name in _BLOCK_VALUE_DICTS:
        arrays.extend(getattr(values, name).values())
    assert len(arrays) == 4 + 5 * 3
    for array in arrays:
        assert not array.flags.writeable
        with pytest.raises(ValueError, match="read-only"):
            array[0] = array[0]
        assert not np.shares_memory(array, index.block_id)
        assert not np.shares_memory(array, index.start_s)
        copied = np.array(array)
        assert copied.flags.writeable
        copied[0] = copied[0]
    # Each array is its own: no two share memory.
    for i, a in enumerate(arrays):
        for b in arrays[i + 1 :]:
            assert not np.shares_memory(a, b)


def test_the_dicts_of_block_gradient_values_are_frozen_dicts_that_refuse_a_change():
    values = block_gradient_values(load(gre_sequence()))
    for name in _BLOCK_VALUE_DICTS:
        field = getattr(values, name)
        assert isinstance(field, FrozenDict)
        assert list(field) == ["x", "y", "z"]
        with pytest.raises(TypeError):
            field["x"] = field["x"]
        with pytest.raises(TypeError):
            del field["x"]
        with pytest.raises(TypeError):
            field.update(w=field["x"])
        assert list(field) == ["x", "y", "z"]


@pytest.mark.parametrize("window", [None, (0.0, 1e-3)], ids=["whole", "window"])
def test_the_axes_of_gradient_peaks_are_a_frozen_dict_that_refuses_a_change(window):
    result = gradient_peaks(load(spin_echo_sequence()), window=window)
    assert isinstance(result.axes, FrozenDict)
    assert list(result.axes) == ["x", "y", "z"]
    with pytest.raises(TypeError):
        result.axes["x"] = result.axes["y"]
    with pytest.raises(TypeError):
        result.axes.clear()


def test_the_reason_of_a_window_with_no_gradient_is_no_gradients_in_the_window():
    """The spin echo has gradients, but none in a window of its first RF block."""
    seq = spin_echo_sequence()
    snap = load(seq)
    index = sequence_index(snap)
    assert index.gx[0] == 0 and index.gy[0] == 0 and index.gz[0] == 0
    result = gradient_peaks(snap, window=(0.0, index.duration_s[0] / 2))
    assert result.reason == NO_GRADIENTS_IN_WINDOW
    assert gradient_peaks(snap).reason is None


def _fail_if_read(monkeypatch, *names: str) -> None:
    """Make each of the functions `names` of `grad_peaks` fail the test when it is called: the
    sequence or its events must not be read before a bad `window` is refused."""

    def fail(*args, **kwargs):
        raise AssertionError("the sequence was read before the window was refused")

    for name in names:
        monkeypatch.setattr(grad_peaks, name, fail)


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (total / 2, total / 2), id="start_equals_end"),
        pytest.param(lambda total: (total / 2, total / 4), id="start_after_end"),
    ],
)
def test_gradient_peaks_refuses_a_window_with_no_start_before_its_end(window_of, monkeypatch):
    """A `window` with a start equal to its end or after its end raises `ValueError`, before
    `gradient_peaks` reads the sequence index or the events."""
    seq = spin_echo_sequence()
    snap = load(seq)
    window = window_of(sequence_index(snap).end_s)
    _fail_if_read(monkeypatch, "sequence_index", "_event_values")
    with pytest.raises(ValueError, match="must have a start before its end"):
        gradient_peaks(snap, window=window)


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (math.nan, total / 2), id="start_nan"),
        pytest.param(lambda total: (0.0, math.nan), id="end_nan"),
        pytest.param(lambda total: (0.0, math.inf), id="end_inf"),
        pytest.param(lambda total: (-math.inf, total / 2), id="start_minus_inf"),
    ],
)
def test_gradient_peaks_refuses_a_window_with_an_end_that_is_not_finite(window_of, monkeypatch):
    """A `window` with a start or an end that is NaN or an infinity raises `ValueError`
    ("finite"), before the rules of the order and of the range, and before `gradient_peaks`
    reads the sequence index or the events."""
    seq = spin_echo_sequence()
    snap = load(seq)
    window = window_of(sequence_index(snap).end_s)
    _fail_if_read(monkeypatch, "sequence_index", "_event_values")
    with pytest.raises(ValueError, match="finite"):
        gradient_peaks(snap, window=window)


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (True, total / 2), id="start_bool"),
        pytest.param(lambda total: (0.0, True), id="end_bool"),
        pytest.param(lambda total: ("0.0", total / 2), id="start_str"),
        pytest.param(lambda total: (0.0, "1e-3"), id="end_str"),
        pytest.param(lambda total: (None, total / 2), id="start_none"),
        pytest.param(lambda total: (0.0, None), id="end_none"),
    ],
)
def test_gradient_peaks_refuses_a_window_end_that_is_not_a_real_number(window_of, monkeypatch):
    """A `window` with a start or an end that is a `bool`, a string or `None` raises
    `TypeError`, before `gradient_peaks` reads the sequence index or the events."""
    seq = spin_echo_sequence()
    snap = load(seq)
    window = window_of(sequence_index(snap).end_s)
    _fail_if_read(monkeypatch, "sequence_index", "_event_values")
    with pytest.raises(TypeError, match="window (start|end)"):
        gradient_peaks(snap, window=window)


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (0.0, total / 2, total), id="three_items"),
        pytest.param(lambda total: (0.0,), id="one_item"),
        pytest.param(lambda total: (), id="no_items"),
        pytest.param(lambda total: total / 2, id="a_number"),
        pytest.param(lambda total: "ab", id="a_string"),
        pytest.param(lambda total: {0.0, total / 2}, id="a_set"),
    ],
)
def test_gradient_peaks_refuses_a_window_that_is_not_a_pair(window_of, monkeypatch):
    """A `window` that is not a tuple or a list of two items raises `TypeError`, before
    `gradient_peaks` reads the sequence index or the events."""
    seq = spin_echo_sequence()
    snap = load(seq)
    window = window_of(sequence_index(snap).end_s)
    _fail_if_read(monkeypatch, "sequence_index", "_event_values")
    with pytest.raises(TypeError, match="must be a pair"):
        gradient_peaks(snap, window=window)


def test_gradient_peaks_takes_a_window_as_a_list_or_with_numpy_scalars():
    """A `window` that is a list, or has an `int` or numpy scalars, gives the result of the
    same window as a tuple of floats."""
    seq = spin_echo_sequence()
    snap = load(seq)
    total = sequence_index(snap).end_s
    expected = gradient_peaks(snap, window=(0.0, total / 2))
    assert gradient_peaks(snap, window=[0.0, total / 2]) == expected
    assert gradient_peaks(snap, window=(0, np.float64(total / 2))) == expected
    assert gradient_peaks(snap, window=(np.int64(0), np.float64(total / 2))) == expected


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (-2 * TIME_TOLERANCE, total / 2), id="start_below_zero"),
        pytest.param(lambda total: (0.0, total + 2 * TIME_TOLERANCE), id="end_after_the_end"),
    ],
)
def test_gradient_peaks_refuses_a_window_outside_the_sequence(window_of, monkeypatch):
    """A `window` that starts more than `TIME_TOLERANCE` before 0 or ends more than
    `TIME_TOLERANCE` after the end of the sequence raises `ValueError`, before
    `gradient_peaks` reads the events (it needs the sequence index for the length)."""
    seq = spin_echo_sequence()
    snap = load(seq)
    window = window_of(sequence_index(snap).end_s)
    _fail_if_read(monkeypatch, "_event_values")
    with pytest.raises(ValueError, match="is not within the sequence"):
        gradient_peaks(snap, window=window)


def test_gradient_peaks_accepts_a_window_within_the_tolerance_of_the_sequence():
    """A `window` that starts `TIME_TOLERANCE / 2` before 0 and ends `TIME_TOLERANCE / 2`
    after the end of the sequence is accepted, and `range_s` is clipped to the sequence."""
    seq = spin_echo_sequence()
    snap = load(seq)
    total = sequence_index(snap).end_s
    result = gradient_peaks(snap, window=(-TIME_TOLERANCE / 2, total + TIME_TOLERANCE / 2))
    assert result.range_s == (0.0, total)


@pytest.mark.parametrize("at_end", [True, False], ids=["past_the_end", "before_zero"])
def test_a_window_outside_the_sequence_within_the_tolerance_gives_an_empty_range(at_end):
    """A window that lies past the end of the sequence, or before 0, by less than
    `TIME_TOLERANCE` is accepted, and its range is clipped to a range of length 0 at that end,
    never with its start after its end. It has no gradient event and the zero values."""
    seq = spin_echo_sequence()
    snap = load(seq)
    total = sequence_index(snap).end_s
    window = (total + 5e-10, total + 9e-10) if at_end else (-9e-10, -5e-10)
    edge = total if at_end else 0.0

    result = gradient_peaks(snap, window=window)

    assert result.range_s == (edge, edge)
    assert result.reason == NO_GRADIENTS_IN_WINDOW
    assert result.vector_peak_hz_per_m == 0.0
    assert result.vector_peak_block is None
    for axis in ("x", "y", "z"):
        assert result.axes[axis] == AxisResult(0.0, 0.0, None, 0.0, 0.0, None, 0.0)


_EDGE_WINDOWS = pytest.mark.parametrize(
    ("first_play", "last_play", "cut"),
    [
        pytest.param(2503, 2507, True, id="edges_in_blocks"),
        pytest.param(2500, 2510, False, id="edges_on_block_edges"),
    ],
)


def _window_over_tr_edges(index, first_play, last_play, cut):
    """The window from the start of block `first_play` to the start of block `last_play`. With
    `cut`, its start is a third of the way into the first block and its end is half way into
    the last block, so each edge cuts a block."""
    start, end = float(index.start_s[first_play]), float(index.start_s[last_play])
    if cut:
        start += float(index.duration_s[first_play]) / 3
        end += float(index.duration_s[last_play]) / 2
    return start, end


@_EDGE_WINDOWS
def test_a_window_does_not_calculate_the_values_over_all_the_blocks_again(
    monkeypatch, first_play, last_play, cut
):
    """In `build_repeating(1000)` (5000 blocks), with the kept data built by a first call, a
    window over several TRs calculates no column of a block (`_axis_columns`), no vector peak
    of a block again, for a window with its edges in
    blocks and for one with its edges on block edges."""
    seq = build_repeating(1000)
    snap = load(seq)
    index = sequence_index(snap)
    gradient_peaks(snap, window=(index.start_s[10], index.start_s[20]))  # builds the kept data
    window = _window_over_tr_edges(index, first_play, last_play, cut)

    # The values over all the blocks are kept, so a window does not calculate them again.
    def fail(*args, **kwargs):
        raise AssertionError("a value over all the blocks was calculated again")

    for name in (
        "_axis_columns",
        "_exact_vector_peaks",
    ):
        monkeypatch.setattr(grad_peaks, name, fail)

    assert gradient_peaks(snap, window=window).reason is None


# ---- The gradient between two events (the model of the module docstring) ----
#
# The sequences are those of `gap_sequences.py`, with the hand-computed values of its
# tests. A gap is a zero gap (a step), a short gap (a line) or a long gap (the ramps). Each
# value, its time and its block are those that the model gives. The tests use values by hand.
# The test of the gap rule at another raster, which also compares with the oracle, is in the
# tests of the `cpp-siemens` plugin.


def _assert_axis(
    axis: AxisResult,
    peak: float,
    peak_time: float,
    peak_block: int | None,
    slew: float,
    slew_time: float,
    slew_block: int | None,
    rms: float,
) -> None:
    """The values of `axis` are the hand-computed ones. The times are equal to 1 ps."""
    assert axis.peak_hz_per_m == pytest.approx(peak, rel=1e-9, abs=1e-6)
    assert axis.peak_time_s == pytest.approx(peak_time, rel=0, abs=1e-12)
    assert axis.peak_block == peak_block
    assert axis.max_slew_hz_per_m_per_s == pytest.approx(slew, rel=1e-9)
    assert axis.slew_time_s == pytest.approx(slew_time, rel=0, abs=1e-12)
    assert axis.slew_block == slew_block
    assert axis.rms_hz_per_m == pytest.approx(rms, rel=1e-9, abs=1e-6)


def test_a_zero_gap_with_two_different_values_gives_a_step_credited_to_the_later_block():
    """Block 1 goes from 0 through U to 2 U in 200 us, and block 2 from U to 0 in 100 us: the step
    is -U at 200 us. The whole file has the peak 2 U at 200 us in block 1, and the slew of the
    step, U / DT, at 200 us in block 2 (each segment has only 1e8 Hz/m/s). The RMS is U: the
    integral of the square is 3 U^2 times 100 us, over 300 us. The junction of block 2 is U / DT,
    and the slew of each block is that of its segments: U / 100 us, in the rise of block 1, and
    in the fall of block 2."""
    seq = zero_gap_sequence()
    block_1, block_2 = seq.block_events

    snap = load(seq)
    _assert_axis(
        gradient_peaks(snap).axes["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=block_1,
        slew=U / DT,
        slew_time=200e-6,
        slew_block=block_2,
        rms=U,
    )

    values = block_gradient_values(snap)
    np.testing.assert_allclose(values.junction_hz_per_m_per_s["x"], [0.0, U / DT], rtol=1e-9)
    np.testing.assert_allclose(values.slew_hz_per_m_per_s["x"], [U / 100e-6] * 2, rtol=1e-9)


def test_a_window_has_the_step_at_its_start_and_not_the_step_at_its_end():
    """For the sequence of the test above, a window has a step when the time of the step is at its
    start or inside it, and it does not have a step at its end. From 150 to 250 us: the slew is the
    step (block 2), the peak is 2 U in block 1, and the RMS is U times sqrt(11/6). From 100 to
    200 us, which ends at the step: no step, and the first point of block 2 is not in the window:
    the slew is that of the rise, U / 100 us from 100 us in block 1, and the RMS is U times
    sqrt(7/3). From 200 to 300 us, which starts at the step: the step is in it, and the last point
    of block 1 is not: the peak is U in block 2, and the RMS is U / sqrt(3)."""
    seq = zero_gap_sequence()
    block_1, block_2 = seq.block_events

    snap = load(seq)
    _assert_axis(
        gradient_peaks(snap, window=(150e-6, 250e-6)).axes["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=block_1,
        slew=U / DT,
        slew_time=200e-6,
        slew_block=block_2,
        rms=U * math.sqrt(11 / 6),
    )
    _assert_axis(
        gradient_peaks(snap, window=(100e-6, 200e-6)).axes["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=block_1,
        slew=U / 100e-6,
        slew_time=100e-6,
        slew_block=block_1,
        rms=U * math.sqrt(7 / 3),
    )
    _assert_axis(
        gradient_peaks(snap, window=(200e-6, 300e-6)).axes["x"],
        peak=U,
        peak_time=200e-6,
        peak_block=block_2,
        slew=U / DT,
        slew_time=200e-6,
        slew_block=block_2,
        rms=U / math.sqrt(3),
    )


def test_a_window_that_ends_at_a_step_up_does_not_have_the_value_after_the_step():
    """Block 1 on x goes from 0 to U in 100 us and stays at U to 200 us, and block 2 starts at 3 U
    and goes to 0 in 100 us: a step of 2 U at 200 us, with no gap. The window from 100 to 200 us
    ends at the step, so the value after the step (3 U) is not in it: the vector peak is U at the
    start of the window, in block 1, the peak of x is U at 100 us in block 1, the slew is 0 (the
    step is not in the window, and the segment of the window is flat) and the RMS is U. A window
    from 100 to 250 us has the step: the vector peak is 3 U at 200 us, in block 2, and the slew is
    the step, 2 U / DT, in block 2."""
    seq = sequence(
        [extended([0, 100e-6, 200e-6], [0, U, U])],
        [extended([0, 100e-6], [3 * U, 0])],
    )
    block_1, block_2 = seq.block_events

    snap = load(seq)
    at_the_step = gradient_peaks(snap, window=(100e-6, 200e-6))

    assert at_the_step.vector_peak_hz_per_m == pytest.approx(U, rel=1e-9)
    assert at_the_step.vector_peak_time_s == pytest.approx(100e-6, rel=0, abs=1e-12)
    assert at_the_step.vector_peak_block == block_1
    _assert_axis(
        at_the_step.axes["x"],
        peak=U,
        peak_time=100e-6,
        peak_block=block_1,
        slew=0.0,
        slew_time=0.0,
        slew_block=None,
        rms=U,
    )
    assert oracle.peaks(seq, (100e-6, 200e-6))["vector_peak"] == pytest.approx(U, rel=1e-9)

    past_the_step = gradient_peaks(snap, window=(100e-6, 250e-6))

    assert past_the_step.vector_peak_hz_per_m == pytest.approx(3 * U, rel=1e-9)
    assert past_the_step.vector_peak_time_s == pytest.approx(200e-6, rel=0, abs=1e-12)
    assert past_the_step.vector_peak_block == block_2
    assert past_the_step.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(2 * U / DT, rel=1e-9)
    assert past_the_step.axes["x"].slew_block == block_2


def test_a_long_gap_gives_the_ramps_of_its_ends_credited_to_the_blocks_of_their_events():
    """Block 1 has a gradient from 0 to 3 U in 100 us, block 2 is a delay of 200 us, and block 3
    has a gradient from 2 U to 0 in 100 us. The gap is 200 us, a long gap, so the gradient is 3 U
    to 0 from 100 to 105 us (the ramp to 0, credited to block 1), 0 until 295 us, and 0 to 2 U
    from 295 to 300 us (the ramp from 0, credited to block 3). The slew of the whole file is the
    ramp to 0, 3 U / 5 us = 6e9, from 100 us in block 1. The peak is 3 U at 100 us in block 1, and
    the RMS is U times sqrt(455/400). The junction is 0 in each block. The slew of block 3 is the
    ramp from 0, 2 U / 5 us = 4e9, from 295 us. The vector peak of block 2 is 3 U at 100 us:
    block 2 starts at 100 us, and the value after 100 us is the start of the ramp to 0.

    A window from 150 to 250 us is in the gap: its values are 0, it has no gradient event and no
    block. A window from 102.5 to 150 us has half of the ramp to 0: the peak is 1.5 U and the slew
    is 6e9, each at 102.5 us in block 1, but the vector peak is in block 2, the block that has
    102.5 us."""
    seq = long_gap_sequence()
    block_1, block_2, _block_3 = seq.block_events

    snap = load(seq)
    _assert_axis(
        gradient_peaks(snap).axes["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=block_1,
        slew=3 * U / 5e-6,
        slew_time=100e-6,
        slew_block=block_1,
        rms=U * math.sqrt(455 / 400),
    )
    values = block_gradient_values(snap)
    np.testing.assert_array_equal(values.junction_hz_per_m_per_s["x"], [0.0] * 3)
    np.testing.assert_allclose(values.slew_hz_per_m_per_s["x"], [6e9, 0.0, 4e9], rtol=1e-9)
    np.testing.assert_allclose(
        values.slew_time_s["x"], [100e-6, 100e-6, 295e-6], rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(values.peak_hz_per_m["x"], [3 * U, 0.0, 2 * U], rtol=1e-9)
    np.testing.assert_allclose(values.vector_peak_hz_per_m, [3 * U, 3 * U, 2 * U], rtol=1e-9)
    np.testing.assert_allclose(
        values.vector_peak_time_s, [100e-6, 100e-6, 300e-6], rtol=0, atol=1e-12
    )

    in_the_gap = gradient_peaks(snap, window=(150e-6, 250e-6))
    assert in_the_gap.reason == NO_GRADIENTS_IN_WINDOW
    _assert_axis(in_the_gap.axes["x"], 0.0, 0.0, None, 0.0, 0.0, None, 0.0)
    assert (in_the_gap.vector_peak_hz_per_m, in_the_gap.vector_peak_block) == (0.0, None)

    half_ramp = gradient_peaks(snap, window=(102.5e-6, 150e-6))
    assert half_ramp.reason is None
    _assert_axis(
        half_ramp.axes["x"],
        peak=1.5 * U,
        peak_time=102.5e-6,
        peak_block=block_1,
        slew=3 * U / 5e-6,
        slew_time=102.5e-6,
        slew_block=block_1,
        rms=math.sqrt((1.5 * U) ** 2 * 2.5e-6 / 3 / 47.5e-6),
    )
    assert half_ramp.vector_peak_hz_per_m == pytest.approx(1.5 * U, rel=1e-9)
    assert half_ramp.vector_peak_time_s == pytest.approx(102.5e-6, rel=0, abs=1e-12)
    assert half_ramp.vector_peak_block == block_2


def test_a_first_value_and_a_last_value_that_are_not_zero_are_steps_at_the_ends_of_the_axis():
    """Block 1 has a gradient from 3 U to 0 in 100 us (a first value that is not 0), and block 2
    has one from 0 to 2 U in 100 us (a last value that is not 0, at the end of the sequence). The
    whole file has the step from 0 to 3 U at 0, 3 U / DT = 3e9, in block 1, as its slew. The step
    after the last point is at 200 us, the end: it is not in the whole file, so the slew of block 2
    is the slope of its segment, 2 U / 100 us. The peak is 3 U at 0 in block 1, and the RMS is U
    times sqrt(13/6). The junction of block 1 is 3 U / DT, and that of block 2 is 0.

    A window from 100 to 200 us has neither step: the slew is the segment, from 100 us in block
    2, and the RMS is 2 U / sqrt(3). A window from 50 to 200 us cuts the first segment at 1.5 U:
    its slope, 3 U / 100 us, is more than that of the second segment, and its time is the window
    start."""
    seq = non_zero_ends_sequence()
    block_1, block_2 = seq.block_events

    snap = load(seq)
    _assert_axis(
        gradient_peaks(snap).axes["x"],
        peak=3 * U,
        peak_time=0.0,
        peak_block=block_1,
        slew=3 * U / DT,
        slew_time=0.0,
        slew_block=block_1,
        rms=U * math.sqrt(13 / 6),
    )
    values = block_gradient_values(snap)
    np.testing.assert_allclose(values.junction_hz_per_m_per_s["x"], [3 * U / DT, 0.0], rtol=1e-9)
    np.testing.assert_allclose(
        values.slew_hz_per_m_per_s["x"], [3 * U / 100e-6, 2 * U / 100e-6], rtol=1e-9
    )

    _assert_axis(
        gradient_peaks(snap, window=(100e-6, 200e-6)).axes["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=block_2,
        slew=2 * U / 100e-6,
        slew_time=100e-6,
        slew_block=block_2,
        rms=2 * U / math.sqrt(3),
    )
    _assert_axis(
        gradient_peaks(snap, window=(50e-6, 200e-6)).axes["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=block_2,
        slew=3 * U / 100e-6,
        slew_time=50e-6,
        slew_block=block_1,
        rms=U * math.sqrt(((1.5**2 / 3) * 50 + (4 / 3) * 100) / 150),
    )


def test_the_vector_peak_of_one_block_with_two_axes_is_at_a_point_of_one_axis():
    """One block of 400 us: x is a trapezoid of 3 U (rise 100 us, flat 200 us, fall 100 us) and y
    is a triangle of 4 U with the top at 150 us. The vector peak is 5 U at 150 us, the time of a
    point of y only (it is hypot(3 U, 2.667 U) at 100 us and hypot(3 U, 1.6 U) at 300 us). From
    160 to 400 us, the largest vector is at the start of the window, where y is 4 U x 240 / 250."""
    seq = vector_sequence()
    (block,) = seq.block_events

    snap = load(seq)
    result = gradient_peaks(snap)
    assert result.vector_peak_hz_per_m == pytest.approx(5 * U, rel=1e-9)
    assert result.vector_peak_time_s == pytest.approx(150e-6, rel=0, abs=1e-12)
    assert result.vector_peak_block == block

    window = gradient_peaks(snap, window=(160e-6, 400e-6))
    assert window.vector_peak_hz_per_m == pytest.approx(math.hypot(3 * U, 3.84 * U), rel=1e-9)
    assert window.vector_peak_time_s == pytest.approx(160e-6, rel=0, abs=1e-12)
    assert window.vector_peak_block == block


def test_a_window_credits_the_segment_before_a_step_of_the_same_slew():
    """Block 1 on x is a trapezoid of U with a rise of 10 us, no flat time and a fall of 10 us, and
    block 2 starts at U: a step of U at 20 us, and then goes to 0 in 100 us. The fall of block 1
    (U / 10 us, the last segment of its event) and the step (U / DT) have the same slew, and no
    other value is as large. The window from 12 to 60 us cuts block 1 in its fall and block 2 in
    its fall. The fall is before the step in the polyline, so the slew is credited to block 1,
    at the start of the cut, 12 us. The peak is U at 20 us, the start of block 2."""
    trapezoid = pp.make_trapezoid(
        channel="x", amplitude=U, rise_time=10e-6, flat_time=0.0, fall_time=10e-6, system=SYSTEM
    )
    seq = sequence([trapezoid], [extended([0, 100e-6], [U, 0])])
    block_1, block_2 = seq.block_events

    snap = load(seq)
    x = gradient_peaks(snap, window=(12e-6, 60e-6)).axes["x"]

    assert x.peak_hz_per_m == pytest.approx(U, rel=1e-9)
    assert x.peak_time_s == pytest.approx(20e-6, rel=0, abs=1e-12)
    assert x.peak_block == block_2
    assert x.max_slew_hz_per_m_per_s == pytest.approx(U / DT, rel=1e-9)
    assert x.slew_time_s == pytest.approx(12e-6, rel=0, abs=1e-12)
    assert x.slew_block == block_1


@pytest.mark.parametrize("function", [gradient_peaks, block_gradient_values])
@pytest.mark.parametrize("build", [gre_sequence, lambda: "sequence.seq"], ids=["sequence", "path"])
def test_a_measurement_raises_type_error_that_names_load_for_a_non_snapshot(function, build):
    """`gradient_peaks` and `block_gradient_values` raise `TypeError` that names `load` for a
    `pp.Sequence` and for a path: they take a `Snapshot`."""
    with pytest.raises(TypeError, match="load"):
        function(build())


@pytest.mark.parametrize(
    ("window", "error", "match"),
    [
        pytest.param((0.5, 0.5), ValueError, "start before its end", id="start_equals_end"),
        pytest.param((0.0, math.inf), ValueError, "window end", id="end_inf"),
        pytest.param([0.0], TypeError, "window", id="not_a_pair"),
    ],
)
def test_gradient_peaks_refuses_a_bad_window_before_the_snapshot_type(window, error, match):
    """A bad `window` raises its own error, before the type of the first argument is checked:
    the first argument is a `pp.Sequence`, which is not a snapshot and would raise the `TypeError`
    that names `load`."""
    with pytest.raises(error, match=match):
        gradient_peaks(gre_sequence(), window=window)
