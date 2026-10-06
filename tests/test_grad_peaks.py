import copy
import math

import numpy as np
import pypulseq as pp
import pytest
from asserts import assert_block_values_equal
from oracles import grad_peaks as oracle
from scale_sequences import build_repeating, build_worst
from synthetic import (
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
    waveform_sequence,
    with_rotation_library,
)

from pulseq_analysis._equality import FrozenDict
from pulseq_analysis.grad_peaks import (
    GradientPeaks,
    _distinct_triples,
    block_gradient_values,
    gradient_peaks,
)
from pulseq_analysis.seq_index import (
    NO_GRADIENTS,
    NO_GRADIENTS_IN_WINDOW,
    grad_events,
    sequence_index,
)
from pulseq_analysis.seq_utils import TIME_TOLERANCE, gradient_offsets


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

    result = gradient_peaks(seq)

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
    assert a.whole_rms_hz_per_m == b.whole_rms_hz_per_m


def test_the_values_do_not_depend_on_the_gamma_of_the_system():
    """The same waveform in Hz/m (a trapezoid with an explicit amplitude and an arbitrary
    gradient), in a sequence of `SYSTEM` and in one of a copy of `SYSTEM` with another gamma:
    `gradient_peaks`, with and without a window, and `block_gradient_values` give exactly
    equal values. The values are in the units of pypulseq, with no gamma."""
    other = copy.copy(SYSTEM)
    other.gamma = 0.9 * SYSTEM.gamma
    first, second = waveform_sequence(SYSTEM), waveform_sequence(other)
    window = (0.0, sequence_index(first).end_s / 2)

    assert other.gamma != SYSTEM.gamma
    assert gradient_peaks(first).reason is None
    _assert_limits_equal(gradient_peaks(first), gradient_peaks(second))
    _assert_limits_equal(
        gradient_peaks(first, window=window), gradient_peaks(second, window=window)
    )
    assert_block_values_equal(block_gradient_values(first), block_gradient_values(second))


def test_the_values_of_a_negated_waveform_are_equal():
    """The same sequence with each amplitude times -1 gives exactly equal values of
    `gradient_peaks` (with and without a window) and `block_gradient_values`: a value is
    a magnitude, so it does not depend on the sign of a gradient, or of a gamma."""
    positive, negative = waveform_sequence(SYSTEM), waveform_sequence(SYSTEM, sign=-1.0)
    window = (0.0, sequence_index(positive).end_s / 2)

    assert gradient_peaks(positive).reason is None
    _assert_limits_equal(gradient_peaks(positive), gradient_peaks(negative))
    _assert_limits_equal(
        gradient_peaks(positive, window=window), gradient_peaks(negative, window=window)
    )
    assert_block_values_equal(block_gradient_values(positive), block_gradient_values(negative))


def test_same_trapezoid_on_x_and_y_gives_vector_peak_root_2_times_axis_peak():
    """The same trapezoid, played on x and on y at the same time: the vector peak is
    the axis peak times sqrt(2), because at every point Gx == Gy, so
    |G| = sqrt(Gx^2 + Gy^2) = sqrt(2) * |Gx|."""
    gx = pp.make_trapezoid(
        channel="x",
        amplitude=0.5 * SYSTEM.max_grad,
        rise_time=200e-6,
        flat_time=1e-3,
        system=SYSTEM,
    )
    gy = pp.make_trapezoid(
        channel="y",
        amplitude=0.5 * SYSTEM.max_grad,
        rise_time=200e-6,
        flat_time=1e-3,
        system=SYSTEM,
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx, gy)

    result = gradient_peaks(seq)

    assert result.vector_peak_hz_per_m == pytest.approx(
        result.axes["x"].peak_hz_per_m * math.sqrt(2)
    )
    assert result.axes["x"].peak_hz_per_m == pytest.approx(result.axes["y"].peak_hz_per_m)


def test_window_that_cuts_a_ramp_gives_hand_computed_rms():
    """A window that ends halfway up the rising ramp of a trapezoid: the RMS amplitude
    over the window equals the value computed by hand from the piece that the window
    keeps, cut at the window edge."""
    amplitude = 0.5 * SYSTEM.max_grad
    rise_time = 200e-6
    gx = pp.make_trapezoid(
        channel="x", amplitude=amplitude, rise_time=rise_time, flat_time=1e-3, system=SYSTEM
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)
    window = (0.0, gx.delay + rise_time / 2)

    result = gradient_peaks(seq, window=window)

    # The window keeps the ramp from (0, 0) to (rise_time / 2, amplitude / 2), a
    # straight line, so Delta t * (a^2 + a*b + b^2) / 3 with a = 0, b = amplitude / 2.
    mid_amplitude = amplitude / 2
    length = window[1] - window[0]
    energy = (rise_time / 2) * (mid_amplitude**2) / 3
    rms_hz_per_m = math.sqrt(energy / length)

    assert result.range_s == window
    assert result.axes["x"].rms_hz_per_m == pytest.approx(rms_hz_per_m)


def test_arbitrary_gradient_peak_is_the_largest_of_first_last_and_waveform():
    """An arbitrary gradient: the peak amplitude is the largest absolute value among
    the shape's `first`, `last` and interior waveform samples, since `gradient_points`
    (seq_utils) adds `first` and `last` as extra points at the shape's ends."""
    n = 40
    dt = SYSTEM.grad_raster_time
    t = (np.arange(n) + 0.5) * dt
    # A waveform that is not symmetric, so its largest magnitude is not at the center.
    waveform = 0.3 * SYSTEM.max_grad * np.sin(np.pi * t / (1.5 * n * dt))
    gx = pp.make_arbitrary_grad(channel="x", waveform=waveform, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)

    result = gradient_peaks(seq)

    block = seq.get_block(1)
    peak_hz_per_m = max(abs(block.gx.first), abs(block.gx.last), np.max(np.abs(waveform)))
    assert result.axes["x"].peak_hz_per_m == pytest.approx(peak_hz_per_m)


def test_no_gradients_sets_reason():
    """A sequence with no gradient at all: `reason` is set, and every numeric
    field is its zero value (0.0, or None for a block field)."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(2e-3))

    result = gradient_peaks(seq)

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


def test_arbitrary_gradient_max_slew_is_the_largest_neighbouring_slope():
    """The largest slew of an arbitrary gradient is the largest `|delta g / delta t|`
    between its neighbouring corner points (the shape's `first`, its waveform samples,
    and its `last`), computed by hand from the event's own fields, not by calling
    `gradient_peaks` for the expected value."""
    n = 40
    dt = SYSTEM.grad_raster_time
    t = (np.arange(n) + 0.5) * dt
    # An asymmetric waveform, so the largest slope is not obviously at one place.
    waveform = 0.3 * SYSTEM.max_grad * np.sin(2 * np.pi * t / (1.3 * n * dt))
    gx = pp.make_arbitrary_grad(channel="x", waveform=waveform, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)
    block = seq.get_block(1)

    result = gradient_peaks(seq)

    times = np.concatenate(([0.0], block.gx.tt, [block.gx.shape_dur]))
    amps = np.concatenate(([block.gx.first], block.gx.waveform, [block.gx.last]))
    expected_slew_hz_per_m_per_s = float(np.max(np.abs(np.diff(amps) / np.diff(times))))

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)


def test_extended_trapezoid_max_slew_is_the_largest_segment_slope():
    """The largest slew of an extended trapezoid is the largest `|delta g / delta t|`
    between its neighbouring control points, computed by hand from the times and the
    amplitudes given to `make_extended_trapezoid`."""
    mg = SYSTEM.max_grad
    times = [0.0, 200e-6, 400e-6, 900e-6, 1100e-6]
    amplitudes = [0.0, 0.1 * mg, 0.15 * mg, 0.15 * mg, 0.0]
    gx = pp.make_extended_trapezoid(channel="x", times=times, amplitudes=amplitudes, system=SYSTEM)
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx)

    result = gradient_peaks(seq)

    expected_slew_hz_per_m_per_s = float(np.max(np.abs(np.diff(amplitudes) / np.diff(times))))

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)


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

    result = gradient_peaks(seq)

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

    result = gradient_peaks(seq, window=window)

    expected_slew_hz_per_m_per_s = 500 * mg  # the slope of the 0-200 us segment

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)
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

    result = gradient_peaks(seq)

    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(750 * mg)
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

    x = gradient_peaks(seq).axes["x"]

    assert x.max_slew_hz_per_m_per_s == pytest.approx(a / raster)
    assert x.slew_time_s == pytest.approx(3 * raster)
    assert x.slew_block == block_ids[1]


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

    result = gradient_peaks(seq)

    expected_vector_peak_hz_per_m = math.sqrt(2) * amp_b
    assert expected_vector_peak_hz_per_m > amp_a  # block B's triple wins
    assert result.vector_peak_hz_per_m == pytest.approx(expected_vector_peak_hz_per_m)
    _block_a_id, block_b_id = seq.block_events
    assert result.vector_peak_block == block_b_id
    assert result.vector_peak_time_s == pytest.approx(1.0e-3)


# ---- Junction steps ----
#
# `add_block` checks the step at every block junction against
# `max_slew * grad_raster_time`. The gradient limits card (pulseq-reports) now reports that
# step, divided by `grad_raster_time`, as part of the axis's slew, whenever it is the largest
# value found (segment or junction). These sequences are built so that the junction step is
# larger than every segment's own slope, so the tests show the junction is really included.

_RASTER = SYSTEM.grad_raster_time
_MAX_STEP = SYSTEM.max_slew * _RASTER  # the largest step add_block accepts


def test_junction_step_between_extended_trapezoids_is_reported_as_the_slew():
    """A step at the junction between two extended trapezoids, within the tolerance that
    `add_block` accepts (`max_slew * grad_raster_time`) and larger than any segment's own
    slope: the reported slew is the step divided by `grad_raster_time`, credited to the
    block after the junction, and its time is the junction (0.2 ms)."""
    step = 0.9 * _MAX_STEP
    seq = _junction_sequence()
    _block_a_id, block_b_id = seq.block_events

    result = gradient_peaks(seq)

    expected_slew_hz_per_m_per_s = step / _RASTER
    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)
    assert result.axes["x"].slew_block == block_b_id
    assert result.axes["x"].slew_time_s == pytest.approx(200e-6)


def test_junction_step_uses_the_gradient_raster_of_the_file_not_of_seq_system(tmp_path):
    """A sequence built with a 4 µs gradient raster, written to a file and read with
    `pp.Sequence()` (10 µs in `seq.system`): the junction step is divided by 4 µs, the
    raster of the file. The sequence object before the write gives the same value."""
    built = raster_4us_sequence()
    path = tmp_path / "raster_4us.seq"
    built.write(str(path))
    read = pp.Sequence()
    read.read(str(path))
    assert read.system.grad_raster_time == pytest.approx(10e-6)
    assert read.grad_raster_time == pytest.approx(RASTER_4US)
    _block_a_id, block_b_id = built.block_events

    for seq in (read, built):
        result = gradient_peaks(seq)

        # The file stores the amplitudes with fewer digits: 2e-5 relative in the value.
        assert result.axes["y"].max_slew_hz_per_m_per_s == pytest.approx(
            RASTER_4US_JUNCTION * GAMMA_1H, rel=1e-4
        )
        assert result.axes["y"].slew_block == block_b_id
        assert result.axes["y"].slew_time_s == pytest.approx(RASTER_4US_JUNCTION_TIME)


def test_gradient_ending_non_zero_before_a_block_with_no_gradient_is_a_junction_step():
    """A gradient that ends at a non-zero value (within the tolerance `add_block`
    accepts) right before a block with no gradient on that axis: the junction step
    uses 0 for the block with no event, and is credited to that block (the block after
    the junction)."""
    last_value = 0.9 * _MAX_STEP
    seq = _gradient_ends_non_zero_before_delay_sequence()
    _block_a_id, block_b_id = seq.block_events

    result = gradient_peaks(seq)

    expected_slew_hz_per_m_per_s = last_value / _RASTER
    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)
    assert result.axes["x"].slew_block == block_b_id


def test_first_block_not_starting_at_zero_is_a_junction_step_before_the_first_block():
    """A first block whose gradient starts at a non-zero value within the tolerance
    `add_block` accepts: the junction before the first block uses 0 for "the block
    before" (there is none), and is credited to the first block."""
    start_value = 0.9 * _MAX_STEP
    seq = _first_block_starts_non_zero_sequence()
    (block_id,) = seq.block_events

    result = gradient_peaks(seq)

    expected_slew_hz_per_m_per_s = start_value / _RASTER
    assert result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(expected_slew_hz_per_m_per_s)
    assert result.axes["x"].slew_block == block_id


def test_window_inside_a_block_with_no_gradient_ignores_the_junction_before_it():
    """A window entirely inside a block with no gradient, after a gradient event that
    ends at a non-zero value (within the tolerance `add_block` accepts) in the block
    before: the junction between the two blocks is before the window start, so it is
    not used, and the window has no gradient event and 0 slew. A window that starts
    exactly at that junction still uses it."""
    step = 0.9 * _MAX_STEP
    seq = _gradient_ends_non_zero_before_delay_sequence()
    _block_a_id, block_b_id = seq.block_events

    inside_result = gradient_peaks(seq, window=(0.5e-3, 1.0e-3))
    assert inside_result.reason == NO_GRADIENTS_IN_WINDOW
    assert inside_result.axes["x"].max_slew_hz_per_m_per_s == 0.0
    assert inside_result.axes["x"].slew_block is None

    junction_result = gradient_peaks(seq, window=(0.2e-3, 1.0e-3))
    expected_slew_hz_per_m_per_s = step / _RASTER
    assert junction_result.reason is None
    assert junction_result.axes["x"].max_slew_hz_per_m_per_s == pytest.approx(
        expected_slew_hz_per_m_per_s
    )
    assert junction_result.axes["x"].slew_block == block_b_id


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

    result = gradient_peaks(seq, window=(0.4e-3, 2.0e-3))

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

    result = gradient_peaks(seq)

    assert result.vector_peak_time_s == pytest.approx(200e-6)
    assert result.vector_peak_block == next(iter(seq.block_events))


def test_axis_whose_only_event_is_zero_credits_no_block():
    """A y event scaled to amplitude 0 (as a phase encode loop makes for the centre line of
    k-space), with an x trapezoid in the same block: the y axis has a peak and a slew of 0, and
    no block is credited for either."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(_tie_trapezoid("x"), pp.scale_grad(_tie_trapezoid("y"), 0.0))

    result = gradient_peaks(seq)

    axis = result.axes["y"]
    assert axis.peak_hz_per_m == 0.0
    assert axis.max_slew_hz_per_m_per_s == 0.0
    assert axis.peak_block is None
    assert axis.slew_block is None


# ---- Comparisons with the oracle ----
#
# `tests/oracles/grad_peaks.py` is the earlier implementation. It reads every block with
# `get_block` and has no junction steps. The random sequences below build every gradient
# event so that it starts and ends at 0, so every block junction step is 0 (the junction
# tests above cover the junction steps on their own, against hand-computed values). With
# no junction contribution, the new code's slew is the segment part only, so the whole
# result can be compared with the oracle's.
#
# The new code sums and maxes per unique event; the oracle sums and maxes per block, after
# adding that block's own start time to the event's corner points before differencing them
# for a slope. When a sequence plays one event in several blocks at different start times
# (for example `tests/synthetic.gre_sequence`'s readout, once each TR), the oracle gets a
# very slightly different slope for the same event at each occurrence: each corner time
# `start + offset` is rounded to about machine eps times the start time, and a slope divides
# the difference of two such times by the segment's duration. The tolerance is therefore
# derived from each sequence (the user, 2026-09-28): `1e-12 + 4 * eps * duration / shortest
# segment` (`_rounding_tol`), relative to the value or to the limit of the same kind. The
# oracle can also credit a peak or a slew of a repeated event to a later block, from the
# same rounding, so these general comparisons check only whether a block is credited; the
# dedicated block-attribution tests above use events that are not repeated and check the
# block exactly.


def _rounding_tol(seq: pp.Sequence) -> float:
    """`1e-12 + 4 * eps * duration / shortest segment`: the rounding of the oracle's
    absolute corner times (`block start + offset`, about eps times the duration), divided
    by the shortest time between two corner points of any gradient event of `seq`."""
    duration = float(sum(seq.block_durations.values()))
    index = sequence_index(seq)
    shortest = math.inf
    for _, g in grad_events(seq, index):
        _, offsets, _ = gradient_offsets(g)
        steps = np.diff(np.asarray(offsets, dtype=float))
        steps = steps[steps > 0]
        if steps.size:
            shortest = min(shortest, float(steps.min()))
    if not math.isfinite(shortest):
        return 1e-12
    return 1e-12 + 4 * np.finfo(float).eps * duration / shortest


def _assert_close(actual: float, expected: float, scale: float, tol: float, label: str) -> None:
    bound = max(abs(expected) * tol, scale * tol)
    assert abs(actual - expected) <= bound, (
        f"{label}: {actual!r} != {expected!r} (tolerance {bound!r})"
    )


def _assert_matches_oracle(ours: GradientPeaks, theirs, tol: float) -> None:
    """The values of this package, converted to mT/m and T/m/s with `GAMMA_1H`, match the
    oracle's. The conversion is that of `docs/usage.md` section 8, so this also tests it."""
    assert ours.reason == theirs.reason
    assert ours.range_s == pytest.approx(theirs.range_s, abs=1e-9)
    grad_scale = theirs.limits.max_grad_mt_per_m
    slew_scale = theirs.limits.max_slew_t_per_m_per_s
    to_mt_per_m = 1e3 / GAMMA_1H
    to_t_per_m_per_s = 1 / GAMMA_1H
    for axis in ("x", "y", "z"):
        a, b = ours.axes[axis], theirs.axes[axis]
        _assert_close(
            a.peak_hz_per_m * to_mt_per_m, b.peak_mt_per_m, grad_scale, tol, f"{axis} peak"
        )
        _assert_close(
            a.max_slew_hz_per_m_per_s * to_t_per_m_per_s,
            b.max_slew_t_per_m_per_s,
            slew_scale,
            tol,
            f"{axis} slew",
        )
        _assert_close(a.rms_hz_per_m * to_mt_per_m, b.rms_mt_per_m, grad_scale, tol, f"{axis} rms")
        assert (a.peak_block is None) == (b.peak_block is None), f"{axis} peak_block presence"
        assert (a.slew_block is None) == (b.slew_block is None), f"{axis} slew_block presence"
    _assert_close(
        ours.vector_peak_hz_per_m * to_mt_per_m,
        theirs.vector_peak_mt_per_m,
        grad_scale,
        tol,
        "vector peak",
    )


@pytest.mark.parametrize(
    "make_seq",
    [spin_echo_sequence, gre_sequence, empty_sequence, arbitrary_gradient_sequence],
    ids=["spin_echo", "gre", "empty", "arbitrary_gradient"],
)
def test_matches_oracle_on_synthetic_sequences(make_seq):
    """`gradient_peaks` matches the oracle on the whole file, and on a window that
    covers the first half of the sequence, for each of `tests/synthetic.py`'s
    sequences."""
    seq = make_seq()
    total = sum(seq.block_durations.values())

    assert_ours = gradient_peaks(seq)
    assert_theirs = oracle.gradient_peaks(seq)
    tol = _rounding_tol(seq)
    _assert_matches_oracle(assert_ours, assert_theirs, tol)

    if total > 0:
        window = (0.0, total / 2)
        _assert_matches_oracle(
            gradient_peaks(seq, window=window), oracle.gradient_peaks(seq, window=window), tol
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
    step is 0."""
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


@pytest.mark.parametrize("seed", range(200))
def test_matches_oracle_on_random_gradient_sequences(seed):
    """200 random sequences of trapezoids, extended trapezoids and arbitrary gradients
    on random axes, each event starting and ending at 0 (so no block junction has a
    step, and the result is only the per-event, non-junction part): `gradient_peaks`
    matches the oracle, on the whole file and on a random window, within
    `_rounding_tol` (see the comment above)."""
    rng = np.random.default_rng(seed)
    seq = _random_gradient_sequence(rng)
    total = sum(seq.block_durations.values())

    ours_whole = gradient_peaks(seq)
    theirs_whole = oracle.gradient_peaks(seq)
    tol = _rounding_tol(seq)
    _assert_matches_oracle(ours_whole, theirs_whole, tol)

    start = rng.uniform(0.0, total * 0.6)
    end = rng.uniform(start + _RASTER, total)
    window = (start, end)
    ours_window = gradient_peaks(seq, window=window)
    theirs_window = oracle.gradient_peaks(seq, window=window)
    _assert_matches_oracle(ours_window, theirs_window, tol)

    # The whole-file RMS that gradient_peaks computes in the same call, for the card's
    # "RMS over whole file" column, matches the oracle's own whole-file RMS.
    for axis in ("x", "y", "z"):
        _assert_close(
            ours_window.whole_rms_hz_per_m[axis] * 1e3 / GAMMA_1H,
            theirs_whole.axes[axis].rms_mt_per_m,
            theirs_window.limits.max_grad_mt_per_m,
            tol,
            f"whole_rms_hz_per_m[{axis}]",
        )


def test_gradient_peaks_refuses_rotations():
    """`gradient_peaks` raises `NotImplementedError` for a sequence with a rotation library
    (`extensions.refuse_rotations`): its numbers are of the logical axes as they are
    stored."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        gradient_peaks(with_rotation_library())


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


def _assert_block_values_agree_with_gradient_peaks(seq: pp.Sequence) -> None:
    """The maximum of each value of `block_gradient_values` is the value of the whole file
    in `gradient_peaks`, and the first block with that value, with its time, is the block and
    the time of `gradient_peaks`. The arithmetic is the same, so every comparison is exact."""
    values = block_gradient_values(seq)
    whole = gradient_peaks(seq)
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
            # The junction is at the block start, before every segment of the block.
            time = values.start_s[play] if junction[play] == top else values.slew_time_s[axis][play]
            assert time == result.slew_time_s
        else:
            assert result.slew_block is None

    vector = values.vector_peak_hz_per_m
    top = float(vector.max())
    assert top == whole.vector_peak_hz_per_m
    if top > 0.0:
        play = int(np.argmax(vector == top))
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
    *(
        lambda seed=seed: _random_gradient_sequence(np.random.default_rng(seed))
        for seed in range(20)
    ),
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
    *(f"random_{seed}" for seed in range(20)),
]


@pytest.mark.parametrize("make_seq", _AGREEMENT_SEQUENCES, ids=_AGREEMENT_IDS)
def test_block_gradient_values_agree_with_gradient_peaks_for_the_whole_file(make_seq):
    """The maxima of `block_gradient_values` over the blocks are the whole-file values of
    `gradient_peaks`, with the same block and time."""
    _assert_block_values_agree_with_gradient_peaks(make_seq())


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

    values = block_gradient_values(seq)

    start_s = sequence_index(seq).start_s
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


def test_first_block_junction_step_uses_zero_before_the_block():
    """A first block whose gradient starts at a non-zero value: its junction step on that axis
    is that value divided by the gradient raster, and the other axes have 0."""
    start_value = 0.9 * _MAX_STEP

    values = block_gradient_values(_first_block_starts_non_zero_sequence())

    assert values.junction_hz_per_m_per_s["x"][0] == pytest.approx(start_value / _RASTER)
    assert values.junction_hz_per_m_per_s["y"][0] == 0.0
    assert values.junction_hz_per_m_per_s["z"][0] == 0.0


def test_junction_step_is_at_the_start_of_the_block_after_the_junction():
    """Block 1 ends at `x`, block 2 starts at `x - step` and ends at 0, and block 3 has no
    gradient: the step is in block 2 and is 0 in block 1 (0 before it) and in block 3 (it
    follows a block that ends at 0). A gradient that ends at a non-zero value before a block
    without a gradient gives that value as the step of the block after it."""
    step = 0.9 * _MAX_STEP
    seq = _junction_sequence()
    seq.add_block(pp.make_delay(1e-3))

    values = block_gradient_values(seq)

    np.testing.assert_array_equal(values.junction_hz_per_m_per_s["x"][[0, 2]], [0.0, 0.0])
    assert values.junction_hz_per_m_per_s["x"][1] == pytest.approx(step / _RASTER)

    last_value = 0.9 * _MAX_STEP
    after_delay = block_gradient_values(_gradient_ends_non_zero_before_delay_sequence())
    assert after_delay.junction_hz_per_m_per_s["x"][0] == 0.0
    assert after_delay.junction_hz_per_m_per_s["x"][1] == pytest.approx(last_value / _RASTER)


def test_junction_step_and_segment_of_one_block_with_the_same_slew_give_the_junction_time():
    """A junction step and the first segment of the same block have the same slew, and it is
    the largest of the file: `gradient_peaks` gives the start of the block, the time of the
    junction, and `block_gradient_values` has the same slew for both in that block."""
    seq = _junction_and_segment_sequence()
    _block_1_id, block_2_id = seq.block_events

    values = block_gradient_values(seq)

    assert values.junction_hz_per_m_per_s["x"][1] == values.slew_hz_per_m_per_s["x"][1]
    assert values.junction_hz_per_m_per_s["x"][1] == values.slew_hz_per_m_per_s["x"].max()
    result = gradient_peaks(seq).axes["x"]
    assert result.slew_block == block_2_id
    assert result.slew_time_s == values.start_s[1]
    assert result.max_slew_hz_per_m_per_s == values.junction_hz_per_m_per_s["x"][1]


def test_block_gradient_values_are_in_play_order_with_one_entry_for_each_block():
    seq = gre_sequence(num_trs=3)
    index = sequence_index(seq)

    values = block_gradient_values(seq)

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
    first, second = block_gradient_values(gre_sequence()), block_gradient_values(gre_sequence())
    assert first is not second
    assert first == second
    assert first != block_gradient_values(gre_sequence(num_trs=5))
    assert first != block_gradient_values(spin_echo_sequence())
    with pytest.raises(TypeError):
        hash(first)


_BLOCK_VALUE_DICTS = (
    "peak_hz_per_m",
    "peak_time_s",
    "slew_hz_per_m_per_s",
    "slew_time_s",
    "junction_hz_per_m_per_s",
)


def test_the_arrays_of_block_gradient_values_are_read_only_and_not_views_of_the_index():
    seq = gre_sequence()
    values = block_gradient_values(seq)
    index = sequence_index(seq)
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
    values = block_gradient_values(gre_sequence())
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
def test_the_dicts_of_gradient_peaks_are_frozen_dicts_that_refuse_a_change(window):
    result = gradient_peaks(spin_echo_sequence(), window=window)
    assert isinstance(result.axes, FrozenDict)
    assert list(result.axes) == ["x", "y", "z"]
    with pytest.raises(TypeError):
        result.axes["x"] = result.axes["y"]
    with pytest.raises(TypeError):
        result.axes.clear()
    if window is None:
        assert result.whole_rms_hz_per_m is None
        return
    assert isinstance(result.whole_rms_hz_per_m, FrozenDict)
    assert list(result.whole_rms_hz_per_m) == ["x", "y", "z"]
    with pytest.raises(TypeError):
        result.whole_rms_hz_per_m["x"] = 0.0
    with pytest.raises(TypeError):
        result.whole_rms_hz_per_m.pop("x")


@pytest.mark.parametrize(
    "build", [empty_sequence, lambda: pp.Sequence(SYSTEM)], ids=["delay_only", "no_blocks"]
)
def test_the_reason_of_a_sequence_with_no_gradient_is_no_gradients(build):
    result = gradient_peaks(build())
    assert result.reason == NO_GRADIENTS
    assert isinstance(result.axes, FrozenDict)


def test_the_reason_of_a_window_with_no_gradient_is_no_gradients_in_the_window():
    """The spin echo has gradients, but none in a window of its first RF block."""
    seq = spin_echo_sequence()
    index = sequence_index(seq)
    assert index.gx[0] == 0 and index.gy[0] == 0 and index.gz[0] == 0
    result = gradient_peaks(seq, window=(0.0, index.duration_s[0] / 2))
    assert result.reason == NO_GRADIENTS_IN_WINDOW
    assert gradient_peaks(seq).reason is None


def test_block_gradient_values_refuses_rotations():
    """`block_gradient_values` raises `NotImplementedError` for a sequence with a rotation
    library, as `gradient_peaks` does."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        block_gradient_values(with_rotation_library())


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (total / 2, total / 2), id="start_equals_end"),
        pytest.param(lambda total: (total / 2, total / 4), id="start_after_end"),
    ],
)
def test_gradient_peaks_refuses_a_window_with_no_start_before_its_end(window_of):
    """A `window` with a start equal to its end or after its end raises `ValueError`."""
    seq = spin_echo_sequence()
    window = window_of(sequence_index(seq).end_s)
    with pytest.raises(ValueError, match="must have a start before its end"):
        gradient_peaks(seq, window=window)


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (math.nan, total / 2), id="start_nan"),
        pytest.param(lambda total: (0.0, math.nan), id="end_nan"),
        pytest.param(lambda total: (0.0, math.inf), id="end_inf"),
        pytest.param(lambda total: (-math.inf, total / 2), id="start_minus_inf"),
    ],
)
def test_gradient_peaks_refuses_a_window_with_an_end_that_is_not_finite(window_of):
    """A `window` with a start or an end that is NaN or an infinity raises `ValueError`
    ("finite"), before the rules of the order and of the range."""
    seq = spin_echo_sequence()
    window = window_of(sequence_index(seq).end_s)
    with pytest.raises(ValueError, match="finite"):
        gradient_peaks(seq, window=window)


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
def test_gradient_peaks_refuses_a_window_end_that_is_not_a_real_number(window_of):
    """A `window` with a start or an end that is a `bool`, a string or `None` raises
    `TypeError`."""
    seq = spin_echo_sequence()
    window = window_of(sequence_index(seq).end_s)
    with pytest.raises(TypeError, match="window (start|end)"):
        gradient_peaks(seq, window=window)


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
def test_gradient_peaks_refuses_a_window_that_is_not_a_pair(window_of):
    """A `window` that is not a tuple or a list of two items raises `TypeError`."""
    seq = spin_echo_sequence()
    window = window_of(sequence_index(seq).end_s)
    with pytest.raises(TypeError, match="must be a pair"):
        gradient_peaks(seq, window=window)


def test_gradient_peaks_takes_a_window_as_a_list_or_with_numpy_scalars():
    """A `window` that is a list, or has an `int` or numpy scalars, gives the result of the
    same window as a tuple of floats."""
    seq = spin_echo_sequence()
    total = sequence_index(seq).end_s
    expected = gradient_peaks(seq, window=(0.0, total / 2))
    assert gradient_peaks(seq, window=[0.0, total / 2]) == expected
    assert gradient_peaks(seq, window=(0, np.float64(total / 2))) == expected
    assert gradient_peaks(seq, window=(np.int64(0), np.float64(total / 2))) == expected


@pytest.mark.parametrize(
    "window_of",
    [
        pytest.param(lambda total: (-2 * TIME_TOLERANCE, total / 2), id="start_below_zero"),
        pytest.param(lambda total: (0.0, total + 2 * TIME_TOLERANCE), id="end_after_the_end"),
    ],
)
def test_gradient_peaks_refuses_a_window_outside_the_sequence(window_of):
    """A `window` that starts more than `TIME_TOLERANCE` before 0 or ends more than
    `TIME_TOLERANCE` after the end of the sequence raises `ValueError`."""
    seq = spin_echo_sequence()
    window = window_of(sequence_index(seq).end_s)
    with pytest.raises(ValueError, match="is not within the sequence"):
        gradient_peaks(seq, window=window)


def test_gradient_peaks_accepts_a_window_within_the_tolerance_of_the_sequence():
    """A `window` that starts `TIME_TOLERANCE / 2` before 0 and ends `TIME_TOLERANCE / 2`
    after the end of the sequence is accepted, and `range_s` is clipped to the sequence."""
    seq = spin_echo_sequence()
    total = sequence_index(seq).end_s
    result = gradient_peaks(seq, window=(-TIME_TOLERANCE / 2, total + TIME_TOLERANCE / 2))
    assert result.range_s == (0.0, total)


def _assert_same_triple_groups(gx, gy, gz, num_events):
    """`_distinct_triples` gives the groups of `np.unique(..., axis=0)`: the same partition
    of the positions, and the same first position of each group."""
    first, inverse = _distinct_triples(gx, gy, gz, num_events)
    ref, ref_first, ref_inverse = np.unique(
        np.stack([gx, gy, gz], axis=1), axis=0, return_index=True, return_inverse=True
    )
    ref_inverse = ref_inverse.reshape(-1)
    assert first.size == ref.shape[0]
    assert inverse.shape == ref_inverse.shape
    # One group of the helper for each group of the reference, and the reverse.
    pairs = set(zip(inverse.tolist(), ref_inverse.tolist(), strict=True))
    assert len(pairs) == first.size
    # The helper's first position of each group is the reference's.
    np.testing.assert_array_equal(inverse[first], np.arange(first.size))
    for group, ref_group in pairs:
        assert first[group] == ref_first[ref_group]


def test_distinct_triples_are_the_groups_of_np_unique_with_up_to_3_million_events():
    """For random triples of event numbers up to 3,000,000, with repeats, triples that share
    two numbers and the extremes 0 and 3,000,000, the groups and the first positions of
    `_distinct_triples` are those of `np.unique(..., axis=0)`."""
    top = 3_000_000
    rng = np.random.default_rng(20261005)
    pool = rng.integers(0, top + 1, size=(300, 3))
    # Triples that differ from a triple of the pool in one number only.
    near = pool[:100].copy()
    near[np.arange(100), rng.integers(0, 3, size=100)] = rng.integers(0, top + 1, size=100)
    extremes = np.array(
        [[0, 0, 0], [top, top, top], [0, top, 0], [top, 0, top], [0, 0, top], [top, 0, 0]]
    )
    pool = np.concatenate([pool, near, extremes])
    triples = pool[rng.integers(0, pool.shape[0], size=5000)]
    # Every triple of the pool occurs at least once, in a random place.
    triples[rng.permutation(triples.shape[0])[: pool.shape[0]]] = pool

    _assert_same_triple_groups(triples[:, 0], triples[:, 1], triples[:, 2], top)


def test_distinct_triples_keep_apart_two_triples_that_one_int64_key_gives_one_number():
    """With 2**22 - 1 events, the one-step key `(gx * base + gy) * base + gz` wraps around
    in int64 for `(2**20, 1, 1)` and `(0, 1, 1)` (the keys differ by 2**64), so they get one
    number. `_distinct_triples` keeps them apart."""
    num_events = 2**22 - 1
    base = num_events + 1
    gx, gy, gz = (np.array(v, dtype=np.int64) for v in ([2**20, 0, 2**20], [1, 1, 1], [1, 1, 1]))

    with np.errstate(over="ignore"):
        one_step_key = (gx * base + gy) * base + gz
    assert one_step_key[0] == one_step_key[1]

    first, inverse = _distinct_triples(gx, gy, gz, num_events)

    assert first.size == 2
    assert inverse[0] != inverse[1]
    assert inverse[0] == inverse[2]
    _assert_same_triple_groups(gx, gy, gz, num_events)
