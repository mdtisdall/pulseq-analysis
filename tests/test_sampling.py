import math

import numpy as np
import pypulseq as pp
import pytest
from gap_sequences import (
    delayed_sequence,
    early_end_sequence,
    long_gap_sequence,
    non_zero_ends_sequence,
    short_gap_sequence,
    zero_gap_sequence,
)
from oracles import waveform as oracle
from synthetic import (
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    signed,
    spin_echo_sequence,
)

from pulseq_analysis._events import event_points
from pulseq_analysis.sampling import GradientSampler, raster_block_lengths, sequence_samples
from pulseq_analysis.seq_index import sequence_index

_AXES = ("gx", "gy", "gz")
_RASTER = SYSTEM.grad_raster_time
# The largest end value that `add_block` accepts next to a gap, halved (the value of the
# sequences of pypulseq-issues 12).
_A = 0.5 * SYSTEM.max_slew * _RASTER


def _raster_centers(duration_s: float, raster: float = SYSTEM.grad_raster_time) -> np.ndarray:
    """`(k + 0.5) * raster` for `k` in `range(ceil(duration_s / raster))`."""
    n = int(np.ceil(duration_s / raster)) if duration_s > 0 else 0
    return (np.arange(n) + 0.5) * raster


def _assert_matches_pypulseq(seq: pp.Sequence, t: np.ndarray) -> None:
    """`GradientSampler.sample(axis, t)` equals `seq.get_gradients()[axis](t)` within
    a relative 1e-12 and an absolute 1e-12 times the largest |value| of that axis's
    reference at `t`.

    Not bit-exact: `seq_utils.gradient_offsets` adds a trapezoid's corner times in a
    different order than pypulseq's `waveforms()` (`start + (rise + flat)` against
    `(start + rise) + flat`), and scipy's `PPoly` evaluates a line segment with its own
    formula (`c[0] * (t - x[i]) + c[1]`), not `numpy.interp`'s. Both differ by float
    rounding only.

    pypulseq draws a line across each gap and does not step at a junction, so this holds
    only for a sequence with no end that is not 0 next to a gap of more than one raster
    time, and with no step at a junction. `_assert_matches_oracle` is for the others.
    """
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    pp_gradients = seq.get_gradients()
    for axis_index, axis in enumerate(_AXES):
        ppoly = pp_gradients[axis_index]
        ref = np.zeros(t.shape, dtype=np.float64) if ppoly is None else ppoly(t)
        got = sampler.sample(axis, t)
        assert got.dtype == np.float64
        assert got.shape == t.shape
        peak = float(np.max(np.abs(ref))) if ref.size else 0.0
        np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-12 * peak)


def _assert_matches_oracle(seq: pp.Sequence, t: np.ndarray) -> None:
    """`GradientSampler.sample(axis, t)` equals `oracle.sample(seq, axis, t)` (the model of
    MATLAB Pulseq, `tests/oracles/waveform.py`) within a relative 1e-12 and an absolute
    1e-12 times the largest |value| of that axis's reference at `t`. The two build the same
    points and differ by the float rounding of the interpolation formula only."""
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    for axis in "xyz":
        ref = oracle.sample(seq, axis, t)
        got = sampler.sample(f"g{axis}", t)
        assert got.dtype == np.float64
        assert got.shape == t.shape
        peak = float(np.max(np.abs(ref))) if ref.size else 0.0
        np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-12 * peak)


def _triangle_sequence() -> pp.Sequence:
    """One trapezoid on x with an area small enough that `make_trapezoid` gives it no
    flat time (a triangle): `gradient_offsets` then gives two points at the same middle
    time (both with the peak amplitude), which the join rule must remove one of."""
    seq = signed(pp.Sequence(SYSTEM))
    g = pp.make_trapezoid(channel="x", area=10.0, system=SYSTEM)
    assert g.flat_time == 0.0
    seq.add_block(g)
    return seq


def _gap_sequence() -> pp.Sequence:
    """A gap between two events on x, with a value that is not 0 at each end of it: an
    extended trapezoid that ramps from 0 to half of `max_slew * grad_raster_time` (the
    largest value that pypulseq's `add_block` accepts next to a block with no gradient is
    `max_slew * grad_raster_time`), a delay block with no gradient on x, and an extended
    trapezoid that starts at a quarter of `max_slew * grad_raster_time` and ramps to 0."""
    raster = SYSTEM.grad_raster_time
    unit = SYSTEM.max_slew * raster
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            amplitudes=np.array([0.0, 0.5 * unit]),
            times=np.array([0.0, 5 * raster]),
            system=SYSTEM,
        )
    )
    seq.add_block(pp.make_delay(2e-3))
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            amplitudes=np.array([0.25 * unit, 0.0]),
            times=np.array([0.0, 5 * raster]),
            system=SYSTEM,
        )
    )
    return seq


def _delay_padded_sequence() -> pp.Sequence:
    """A delay block, a trapezoid on x, and a second delay block: a leading and a
    trailing gap with no gradient event at all."""
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(pp.make_delay(1e-3))
    seq.add_block(pp.make_trapezoid(channel="x", area=500, system=SYSTEM))
    seq.add_block(pp.make_delay(1e-3))
    return seq


def _junction_sequence(step_hz_per_m: float) -> tuple[pp.Sequence, float]:
    """Two extended trapezoids on x that together make one ordinary trapezoid (the
    rise, flat and fall of an area-1000 trapezoid), split into two blocks at the middle
    of the flat top. The second block's first value is `step_hz_per_m` less than the
    first block's last value: 0 gives an amplitude that exactly continues into the next
    block, and a value up to `max_slew * grad_raster_time` is a step that pypulseq's
    `add_block` still accepts. Returns the sequence and the junction time (s)."""
    base = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    raster = SYSTEM.grad_raster_time
    half_flat = round((base.flat_time / 2) / raster) * raster
    amp = base.amplitude
    seq = signed(pp.Sequence(SYSTEM))
    g1 = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([0.0, amp, amp]),
        times=np.array([0.0, base.rise_time, base.rise_time + half_flat]),
        system=SYSTEM,
    )
    g2 = pp.make_extended_trapezoid(
        channel="x",
        amplitudes=np.array([amp - step_hz_per_m, amp - step_hz_per_m, 0.0]),
        times=np.array(
            [0.0, base.flat_time - half_flat, base.flat_time - half_flat + base.fall_time]
        ),
        system=SYSTEM,
    )
    seq.add_block(g1)
    seq.add_block(g2)
    return seq, base.rise_time + half_flat


def _step_then_gap_sequence() -> tuple[pp.Sequence, np.ndarray]:
    """A step at a block junction, then a gap, then a second event, all on x: the
    trapezoid of `_junction_sequence` in two blocks, with a step of half of
    `max_slew * grad_raster_time` at the junction and a last value of the same size
    (not 0), a delay block with no gradient, and a trapezoid. Returns the sequence and
    a sorted grid of sample times (s): around the junction, around the end of the
    second block, inside the ramp to 0 after the last value (half a raster time long),
    inside the rest of the gap (where the waveform is 0) and around the start of the
    trapezoid."""
    raster = SYSTEM.grad_raster_time
    small = 0.5 * SYSTEM.max_slew * raster
    base = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    half_flat = round((base.flat_time / 2) / raster) * raster
    amp = base.amplitude
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            amplitudes=np.array([0.0, amp, amp]),
            times=np.array([0.0, base.rise_time, base.rise_time + half_flat]),
            system=SYSTEM,
        )
    )
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            amplitudes=np.array([amp - small, amp - small, small]),
            times=np.array(
                [0.0, base.flat_time - half_flat, base.flat_time - half_flat + base.fall_time]
            ),
            system=SYSTEM,
        )
    )
    seq.add_block(pp.make_delay(2e-3))
    seq.add_block(pp.make_trapezoid(channel="x", area=-500, system=SYSTEM))
    index = sequence_index(seq)
    assert index.num_blocks == 4
    junction_s = float(index.start_s[1])
    gap_start_s = float(index.start_s[2])
    trapezoid_start_s = float(index.start_s[3])
    t = np.concatenate(
        [
            junction_s + np.arange(-4, 5) * (raster / 2),
            gap_start_s + np.arange(-2, 3) * (raster / 2),
            gap_start_s + np.array([0.1, 0.25, 0.5, 0.75, 0.9]) * (raster / 2),
            gap_start_s + np.linspace(0.1, 0.9, 7) * (trapezoid_start_s - gap_start_s),
            trapezoid_start_s + np.arange(-2, 5) * (raster / 2),
        ]
    )
    return seq, np.unique(t)


@pytest.mark.parametrize(
    "seq",
    [spin_echo_sequence(), gre_sequence(), arbitrary_gradient_sequence(), empty_sequence()],
    ids=["spin_echo", "gre", "arbitrary_gradient", "empty"],
)
def test_whole_file_matches_pypulseq_for_synthetic_sequences(seq):
    index = sequence_index(seq)
    t = _raster_centers(index.end_s)
    _assert_matches_pypulseq(seq, t)


def test_subrange_that_cuts_blocks_matches_pypulseq():
    # gre_sequence(num_trs=1) has 5 blocks: rf, phase-encode (gy), readout (gx) with
    # ADC, spoiler (gz), delay. The middle of block 2 to the middle of block 4 cuts
    # through the gx event, includes the whole gz event, and leaves the gy event (block
    # 1) entirely before the range, so this also checks that gy is correctly 0 after
    # its one and only event.
    seq = gre_sequence(num_trs=1)
    index = sequence_index(seq)
    t0 = index.start_s[2] + index.duration_s[2] / 2
    t1 = index.start_s[4] + index.duration_s[4] / 2
    t = np.linspace(t0, t1, 500)
    _assert_matches_pypulseq(seq, t)


def test_a_subrange_inside_a_long_gap_has_its_ramps_and_zero_and_matches_the_oracle():
    """`_gap_sequence` has a long gap (2 ms) with a value that is not 0 at each end of it.
    A time range inside the gap that has the ramp to 0 after the first end, the 0 between
    the ramps and the ramp from 0 before the second end gives the values of the oracle.
    The ramps are half a raster time long. The range has times only in the gap, so the
    events before and after it are not in the block range of the call."""
    seq = _gap_sequence()
    index = sequence_index(seq)
    gap_start = index.start_s[1]
    gap_end = index.start_s[2]
    assert gap_end - gap_start == pytest.approx(2e-3)
    # The ramps are at the start and at the end of the gap, and the middle is 0.
    ramp = _RASTER / 2
    t = np.sort(
        np.concatenate(
            [
                gap_start + np.linspace(0.1, 0.9, 5) * ramp,
                np.linspace(gap_start + 2 * ramp, gap_end - 2 * ramp, 20),
                gap_end - np.linspace(0.1, 0.9, 5) * ramp,
            ]
        )
    )
    got = GradientSampler(index, event_points(seq)).sample("gx", t)
    assert np.all(got[:5] != 0.0)
    assert np.all(got[5:25] == 0.0)
    assert np.all(got[25:] != 0.0)
    _assert_matches_oracle(seq, t)


def test_range_across_a_step_and_a_ramp_equals_the_same_slice_of_the_whole_grid():
    seq, t = _step_then_gap_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    whole = sampler.sample("gx", t)
    # The waveform after the last value of block 1 is the ramp to 0 (half a raster time),
    # and 0 after it, so a range that starts in the gap needs the event before it.
    gap_start = index.start_s[2]
    in_ramp = (t > gap_start) & (t < gap_start + _RASTER / 2)
    after_ramp = (t >= gap_start + _RASTER / 2) & (t < index.start_s[3])
    assert in_ramp.sum() >= 5
    assert after_ramp.sum() >= 7
    assert np.all(whole[in_ramp] != 0.0)
    assert np.all(whole[after_ramp] == 0.0)
    for i in range(t.size):
        for j in range(i + 1, t.size + 1):
            assert np.array_equal(sampler.sample("gx", t[i:j]), whole[i:j]), (i, j)
    _assert_matches_oracle(seq, t)


def test_times_before_an_event_that_starts_at_a_value_that_is_not_0_have_the_ramp_from_0():
    """The gap is the end of block 0 (a trapezoid that ends at 300 us, in a block held for
    1 ms by a delay) and the next event starts with block 1, at half of
    `max_slew * grad_raster_time` and with no delay. The gap is long and the trapezoid ends
    at 0, so the waveform is 0 in the gap except the ramp from 0 in the last half raster time
    before the next event: the line from (995 us, 0) to (1 ms, the value). Hand values."""
    raster = SYSTEM.grad_raster_time
    step = 0.5 * SYSTEM.max_slew * raster
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(
        pp.make_trapezoid(
            channel="x", amplitude=0.1 * SYSTEM.max_grad, duration=300e-6, system=SYSTEM
        ),
        pp.make_delay(1e-3),
    )
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="x",
            amplitudes=np.array([step, 0.0]),
            times=np.array([0.0, 5 * raster]),
            system=SYSTEM,
        )
    )
    index = sequence_index(seq)
    assert index.num_blocks == 2
    assert index.start_s[1] == pytest.approx(1e-3)
    t = np.array([600e-6, 800e-6, 995e-6, 996e-6, 997.5e-6, 999e-6, 1e-3])
    expected = np.array([0.0, 0.0, 0.0, 0.2 * step, 0.5 * step, 0.8 * step, step])
    sampler = GradientSampler(index, event_points(seq))
    got = sampler.sample("gx", t)
    np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9 * step)
    _assert_matches_oracle(seq, t)


def test_single_sample_matches_pypulseq():
    seq = gre_sequence(num_trs=1)
    index = sequence_index(seq)
    t = np.array([index.start_s[2] + index.duration_s[2] / 2])
    _assert_matches_pypulseq(seq, t)


def test_amplitude_continues_across_a_block_junction():
    seq, junction_s = _junction_sequence(step_hz_per_m=0.0)
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * SYSTEM.grad_raster_time)
    _assert_matches_pypulseq(seq, t)


def test_a_tolerated_step_at_a_block_junction_is_a_step_that_the_oracle_has():
    """A step of half of `max_slew * grad_raster_time` at the junction in the middle of the
    flat top: the value at the time of the step is the earlier value, and the value after
    it is the later one (flat) until the fall. pypulseq draws a line from the earlier value
    to the end of the flat of the later block instead (pypulseq-issues 12), so the test
    compares with the oracle and with the hand values."""
    step = 0.5 * SYSTEM.max_slew * SYSTEM.grad_raster_time
    seq, junction_s = _junction_sequence(step_hz_per_m=step)
    base = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    raster = SYSTEM.grad_raster_time
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * raster)
    _assert_matches_oracle(seq, t)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    got = sampler.sample(
        "gx", np.array([junction_s - 10 * raster, junction_s, junction_s + 10 * raster])
    )
    np.testing.assert_allclose(
        got, [base.amplitude, base.amplitude, base.amplitude - step], rtol=1e-12
    )


def test_triangle_trapezoid_matches_pypulseq():
    seq = _triangle_sequence()
    index = sequence_index(seq)
    t = _raster_centers(index.end_s)
    _assert_matches_pypulseq(seq, t)


def test_sample_matches_the_added_events_for_an_oversampled_arbitrary_gradient():
    """`sample` for a file with an oversampled arbitrary gradient against a reference built
    from the added events (the objects that `make_*` returns, before `add_block`), not
    from `get_block` and not from `seq.get_gradients()`: `get_gradients()` itself leaves
    out the first and the last point of an oversampled gradient (draft 03 of
    `github.com/mdtisdall/pypulseq-issues`).

    Needs the fix of pypulseq PR #424, which the pinned fork has (`pulseq-reports-pin-2`):
    with the old pin (`20b9e5e`), `get_block` gave this oversampled gradient's `shape_dur`
    as twice the value `make_arbitrary_grad` set, and the sampler error was about 40 % of
    the peak.

    The sequence: an oversampled ramp of 21 samples at 50 % of
    `max_slew` over half a raster (`make_arbitrary_grad(oversampling=True)` checks the
    slew rate 4 times too leniently, pypulseq issue #421, so the waveform is kept within
    the real `max_slew` by itself), ending at a value that is not 0; an extended
    trapezoid back down to 0; and an ordinary trapezoid.
    """
    dt = SYSTEM.grad_raster_time
    step = 0.5 * SYSTEM.max_slew * dt / 2  # 50 % of the real max_slew over half a raster
    n = 21
    g_os = pp.make_arbitrary_grad(
        "x",
        step * np.arange(1, n + 1),
        first=0.0,
        last=step * (n + 1),
        oversampling=True,
        system=SYSTEM,
    )
    g_down = pp.make_extended_trapezoid(
        "x", times=[0.0, 20 * dt], amplitudes=[step * (n + 1), 0.0], system=SYSTEM
    )
    g_trap = pp.make_trapezoid("x", amplitude=0.4 * SYSTEM.max_grad, duration=0.5e-3, system=SYSTEM)
    seq = signed(pp.Sequence(SYSTEM))
    for g in (g_os, g_down, g_trap):
        seq.add_block(g)

    # The reference polyline, from the added events (not get_block, not get_gradients).
    starts = np.concatenate([[0.0], np.cumsum([seq.block_durations[i] for i in (1, 2, 3)])])
    ts, vs = [], []
    for g, t0 in zip((g_os, g_down, g_trap), starts):
        if g.type == "trap":
            off = np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
            amp = np.array([0.0, g.amplitude, g.amplitude, 0.0])
        else:
            off = np.concatenate([[0.0], g.tt, [g.shape_dur]])
            amp = np.concatenate([[g.first], g.waveform, [g.last]])
        ts.append(t0 + g.delay + off)
        vs.append(amp)
    tt, vv = np.concatenate(ts), np.concatenate(vs)
    keep = np.concatenate([[True], tt[1:] > tt[:-1] + 1e-9])
    tt, vv = tt[keep], vv[keep]

    grid = np.linspace(0, starts[-1], 4001)[1:-1]
    truth = np.interp(grid, tt, vv)
    peak = np.abs(truth).max()

    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    got = sampler.sample("gx", grid)
    np.testing.assert_allclose(got, truth, rtol=0, atol=1e-12 * peak)


def test_zero_before_the_first_event_and_after_the_last():
    seq = _delay_padded_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    before = np.linspace(0.0, index.start_s[1] - 1e-6, 50)
    after = np.linspace(index.start_s[2] + 1e-6, index.end_s, 50)
    got_before = sampler.sample("gx", before)
    got_after = sampler.sample("gx", after)
    np.testing.assert_array_equal(got_before, np.zeros(before.shape, dtype=np.float64))
    np.testing.assert_array_equal(got_after, np.zeros(after.shape, dtype=np.float64))


def test_empty_sequence_is_zero_for_any_t():
    seq = empty_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    t = np.array([0.0, 1e-3, 5.0])  # 5.0 s is well past the sequence's own duration
    for axis in _AXES:
        got = sampler.sample(axis, t)
        assert got.dtype == np.float64
        np.testing.assert_array_equal(got, np.zeros(t.shape, dtype=np.float64))


def test_empty_times_gives_empty_output():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    got = sampler.sample("gx", np.array([]))
    assert got.dtype == np.float64
    assert got.shape == (0,)


def test_invalid_axis_name_raises_value_error():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    with pytest.raises(ValueError):
        sampler.sample("gw", np.array([0.0]))


def _off_raster_events_sequence() -> pp.Sequence:
    """Two blocks of 8 raster times on x, with events that do not start or end on a raster
    edge (a delay of `0.3` and of `0.7` raster times, which `add_block` accepts). Block 0:
    a ramp from 0 to `max_slew * grad_raster_time / 2` over 3 raster times, from 0.3 to 3.3.
    Block 1 starts at 8: a ramp from half of that value down to 0 over 3 raster times, from
    8.7 to 11.7 (it starts at a value that is not 0 after a delay, which `add_block` accepts
    below `max_slew * grad_raster_time`). The gap is long, so the ramp to 0 is from 3.3 to
    3.8 and the ramp from 0 is from 8.2 to 8.7 (in raster times). Both contain a sample
    time of the raster, 3.5 and 8.5."""
    first = pp.make_extended_trapezoid(
        channel="x", times=[0.0, 3 * _RASTER], amplitudes=[0.0, _A], system=SYSTEM
    )
    first.delay = 0.3 * _RASTER
    second = pp.make_extended_trapezoid(
        channel="x", times=[0.0, 3 * _RASTER], amplitudes=[_A / 2, 0.0], system=SYSTEM
    )
    second.delay = 0.7 * _RASTER
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(first, pp.make_delay(8 * _RASTER))
    seq.add_block(second, pp.make_delay(8 * _RASTER))
    return seq


# The sequences of the model: each gap rule (a zero gap, a short gap, a long gap, the first and the
# last value not 0, the two sequences of pypulseq-issues 12), the synthetic sequences, and
# events that are not on a raster edge.
_MODEL_SEQUENCES = {
    "zero_gap": zero_gap_sequence,
    "short_gap": short_gap_sequence,
    "long_gap": long_gap_sequence,
    "non_zero_ends": non_zero_ends_sequence,
    "issue_12_delayed": delayed_sequence,
    "issue_12_early_end": early_end_sequence,
    "gap_between_extended_trapezoids": _gap_sequence,
    "step_then_gap": lambda: _step_then_gap_sequence()[0],
    "off_raster_events": _off_raster_events_sequence,
    "spin_echo": spin_echo_sequence,
    "gre": gre_sequence,
    "arbitrary_gradient": arbitrary_gradient_sequence,
}


def _model_sequence(name: str) -> pp.Sequence:
    """The sequence `name` of `_MODEL_SEQUENCES`, signed (the builders of the oracle test
    do not sign it)."""
    return signed(_MODEL_SEQUENCES[name]())


def _model_times(seq: pp.Sequence) -> np.ndarray:
    """A sorted grid of times (s) of `seq`: the raster centres, an even grid across the
    sequence (a little before and after), and the points of the polyline of the oracle on
    each axis, each also a little before and after (so the ramp points, the steps and the
    ends are there)."""
    end = sequence_index(seq).end_s
    times = [_raster_centers(end), np.linspace(-_RASTER, end + _RASTER, 2001)]
    for axis in "xyz":
        t = oracle.axis_polyline(seq, axis).t
        times += [t, t - 1e-7, t + 1e-7]
    return np.unique(np.concatenate(times))


@pytest.mark.parametrize("name", _MODEL_SEQUENCES)
def test_sample_equals_the_oracle_for_the_whole_sequence(name):
    """`sample` equals the oracle (the model of MATLAB Pulseq) on a grid across each
    sequence of the model, with times at the points, the steps and the ramps."""
    seq = _model_sequence(name)
    _assert_matches_oracle(seq, _model_times(seq))


@pytest.mark.parametrize(
    "name", ["long_gap", "short_gap", "zero_gap", "issue_12_delayed", "off_raster_events"]
)
def test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(name):
    """Each time range `t[i:j]` of a grid of times at the ends of the events, inside the
    gap, at the ramps and at the steps: `sample` equals the oracle, and the same slice of
    the whole grid exactly (a range that starts or ends inside a gap or a ramp has the
    events around it)."""
    seq = _model_sequence(name)
    index = sequence_index(seq)
    full = _model_times(seq)
    t = full[:: max(1, full.size // 40)]
    sampler = GradientSampler(index, event_points(seq))
    for axis in "xyz":
        whole = sampler.sample(f"g{axis}", t)
        ref = oracle.sample(seq, axis, t)
        peak = float(np.max(np.abs(ref)))
        np.testing.assert_allclose(whole, ref, rtol=1e-12, atol=1e-12 * peak)
        for i in range(t.size):
            for j in range(i + 1, t.size + 1):
                assert np.array_equal(sampler.sample(f"g{axis}", t[i:j]), whole[i:j]), (axis, i, j)


def test_a_ramp_to_0_and_a_ramp_from_0_cross_a_long_gap_by_hand():
    """`_off_raster_events_sequence` at times in the two ramps (half a raster time long, at 3.3
    to 3.8 and 8.2 to 8.7 raster times), with hand values, and 0 between the ramps and after
    the last point."""
    seq = _off_raster_events_sequence()
    t = _RASTER * np.array([3.3, 3.5, 3.8, 5.0, 8.2, 8.5, 8.7, 11.7, 12.0])
    expected = _A * np.array([1.0, 0.6, 0.0, 0.0, 0.0, 0.3, 0.5, 0.0, 0.0])
    got = GradientSampler(sequence_index(seq), event_points(seq)).sample("gx", t)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-9 * _A)
    # A line across the gap, which pypulseq draws, would give about 0.8 A at 5.
    assert abs(seq.get_gradients()[0](t[3]) - 0.0) > 0.5 * _A


def test_the_gaps_are_found_one_time_for_each_sequence_and_axis():
    """The pieces of `long_gap_sequence` (gx): the ramp to 0 from 100 us to 105 us, and the
    ramp from 0 from 295 us to 300 us. Two samplers of one sequence have the same kept
    `_AxisGaps` object (read-only arrays). An axis with no event has none. A block added to the
    sequence gives new points, so the gaps are found again."""
    seq = _model_sequence("long_gap")
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    gaps = sampler._gaps("gx")
    assert GradientSampler(index, event_points(seq))._gaps("gx") is gaps
    np.testing.assert_allclose(gaps.start_s, [100e-6, 295e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(gaps.end_s, [105e-6, 300e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(gaps.start_hz_per_m, [3e4, 0.0])
    np.testing.assert_allclose(gaps.end_hz_per_m, [0.0, 2e4])
    np.testing.assert_allclose(gaps.ramp_s, [105e-6, 295e-6], rtol=0, atol=1e-12)
    for array in (gaps.start_s, gaps.end_s, gaps.start_hz_per_m, gaps.end_hz_per_m, gaps.ramp_s):
        assert not array.flags.writeable
    assert sampler._gaps("gy").start_s.size == 0
    seq.add_block(pp.make_delay(1e-3))
    again = GradientSampler(sequence_index(seq), event_points(seq))._gaps("gx")
    assert again is not gaps
    np.testing.assert_array_equal(again.start_s, gaps.start_s)


# ---- GradientSampler.block_samples and raster_block_lengths ----


@pytest.mark.parametrize(
    "seq",
    [spin_echo_sequence(), gre_sequence(), arbitrary_gradient_sequence()],
    ids=["spin_echo", "gre", "arbitrary_gradient"],
)
def test_block_samples_matches_sample_at_file_raster_times(seq):
    """`block_samples` over all blocks agrees with `sample` at the file times
    `(k + 0.5) * dt`, within 1e-9 of the largest |g| of the axis.

    The two are not exactly equal: `block_samples` computes each block's samples from
    its own local raster grid `(j + 0.5) * dt`, with no accumulated float error, while
    `sample` reads the waveform at the block's actual start time, the sequential sum of
    the durations before it, which drifts off the ideal `k * dt` raster grid by float
    rounding. The difference is that drift only.
    """
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    total = int(n.sum())
    t_file = (np.arange(total, dtype=np.float64) + 0.5) * dt
    sampler = GradientSampler(index, event_points(seq))
    for axis in _AXES:
        got = sampler.block_samples(axis, 0, index.num_blocks, dt)
        ref = sampler.sample(axis, t_file)
        assert got.shape == ref.shape
        peak = float(np.max(np.abs(ref))) if ref.size else 0.0
        np.testing.assert_allclose(got, ref, atol=1e-9 * peak, rtol=0.0)


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
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(gx, gz)
    seq.add_block(pp.make_delay(n_block * dt))
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))

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


def test_range_inside_the_file_equals_the_same_slice_of_the_whole_file():
    seq = gre_sequence(num_trs=3)
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    first, stop = 2, index.num_blocks - 1
    assert 0 < first < stop < index.num_blocks
    offset = int(n[:first].sum())
    length = int(n[first:stop].sum())
    for axis in _AXES:
        whole = sampler.block_samples(axis, 0, index.num_blocks, dt)
        part = sampler.block_samples(axis, first, stop, dt)
        assert np.array_equal(part, whole[offset : offset + length])


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
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(
        pp.make_trapezoid(channel="x", area=1000.0, system=SYSTEM),
        pp.make_trapezoid(channel="z", area=3000.0, system=SYSTEM),
    )
    seq.add_block(pp.make_delay(300 * dt))
    seq.add_block(arbitrary, pp.make_delay(120 * dt))
    seq.add_block(pp.make_trapezoid(channel="y", area=10.0, system=SYSTEM))
    seq.add_block(arbitrary, pp.make_delay(120 * dt))
    return seq


def _sample_ranges(n: np.ndarray) -> list[tuple[int, int]]:
    """`(skip, count)` pairs for blocks of `n` samples each: the whole range, an empty range
    at each end, one sample at each end, and for each block its whole samples, a range across
    each of its edges, and ranges that cover it in fifths (each inside the block or across
    its edges)."""
    total = int(n.sum())
    ends = np.cumsum(n)
    starts = ends - n
    ranges = {(0, total), (0, 0), (total, 0), (0, 1), (total - 1, 1)}
    for start, length in zip(starts.tolist(), n.tolist(), strict=True):
        ranges.add((start, length))
        ranges.add((start - 2, 5))
        ranges.add((start + length - 3, 6))
        for fifth in range(5):
            ranges.add((start + fifth * length // 5, length // 5 + 3))
    return sorted((skip, count) for skip, count in ranges if skip >= 0 and skip + count <= total)


def test_skip_and_count_equal_the_same_slice_of_the_whole_range():
    """`block_samples(axis, first, stop, dt, skip=s, count=c)` equals `block_samples(axis, first,
    stop, dt)[s : s + c]` exactly, for each axis, for block ranges of the whole file and of
    its inner blocks, and for sample ranges that start and end inside a block, at the edge
    of a block, inside a block with no event, and after the last point of the event of a
    block (the samples that are 0 and that the sampler does not keep). `count=None` gives all
    the samples after `skip`. The sampler that made the whole range first (with samples kept)
    and a new one give the same part."""
    seq = _blocks_with_long_events_sequence()
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    n_all, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    assert n_all[2] == n_all[4] == 120  # the event of block 2 stops 60 samples before its end
    sampler = GradientSampler(index, event_points(seq))
    checked = 0
    for first, stop in [(0, 5), (1, 5), (2, 5), (1, 4), (2, 3), (3, 5), (0, 2), (4, 5)]:
        n = n_all[first:stop]
        for axis in _AXES:
            whole = sampler.block_samples(axis, first, stop, dt)
            for skip, count in _sample_ranges(n):
                expected = whole[skip : skip + count]
                got = sampler.block_samples(axis, first, stop, dt, skip=skip, count=count)
                assert got.dtype == np.float64
                assert np.array_equal(got, expected), (axis, first, stop, skip, count)
                fresh = GradientSampler(index, event_points(seq))
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


def test_a_range_inside_a_block_longer_than_the_range_is_the_same_slice():
    """A range inside one block that is much longer than the range (a trapezoid on x in a
    block held by a delay for 100000 samples, then another block) gives exactly the slice of the
    samples of the whole block, for ranges before, across and after the end of the trapezoid and
    inside the block after it. It checks the part of a block that the range cuts, which the
    sampler computes for the range only."""
    dt = SYSTEM.grad_raster_time
    n_block = 100_000
    seq = signed(pp.Sequence(SYSTEM))
    trapezoid = pp.make_trapezoid(channel="x", area=1000.0, system=SYSTEM)
    seq.add_block(trapezoid, pp.make_delay(n_block * dt))
    seq.add_block(pp.make_trapezoid(channel="x", area=500.0, system=SYSTEM))
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    assert n[0] == n_block
    sampler = GradientSampler(index, event_points(seq))
    whole = sampler.block_samples("gx", 0, 2, dt)
    nonzero = np.flatnonzero(whole[:n_block])
    assert 0 < nonzero.size < 1000
    last = int(nonzero[-1])
    for skip, count in [
        (0, 10),
        (last - 5, 10),
        (last + 1, 10),
        (n_block // 2, 50_000),
        (n_block - 3, 6),
        (n_block - 3, int(n[1]) + 3),
        (n_block, int(n[1])),
        (5, n_block + 10),
    ]:
        got = sampler.block_samples("gx", 0, 2, dt, skip=skip, count=count)
        assert np.array_equal(got, whole[skip : skip + count]), (skip, count)


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
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(ramp, pp.make_delay(4 * raster))
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
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
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(ramp, pp.make_delay((n_ramp + 3) * raster))
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    got = sampler.block_samples("gx", 0, 1, dt)
    assert got.shape == (last + 2,)
    assert got[last] == amp
    assert got[last + 1] == 0.0
    assert np.all(got[:last] < amp)


@pytest.mark.parametrize(
    "skip,count",
    [(-1, 1), (0, -1), (-1, None), (1, 10**9), (10**9, 0), (10**9, None)],
    ids=[
        "negative_skip",
        "negative_count",
        "negative_skip_and_count_none",
        "skip_plus_count_past_the_range",
        "skip_past_the_range",
        "skip_past_the_range_and_count_none",
    ],
)
def test_block_samples_bad_skip_or_count_raises_value_error(skip, count):
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("gx", 1, 3, SYSTEM.grad_raster_time, skip=skip, count=count)


def test_skip_plus_count_up_to_the_range_end_is_accepted():
    """`skip + count` equal to the samples of the range is not an error (the edge of the
    check), also for an empty range of blocks."""
    seq = gre_sequence(num_trs=1)
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    n, _ = raster_block_lengths(index, dt)
    total = int(n[1:3].sum())
    assert sampler.block_samples("gx", 1, 3, dt, skip=total, count=0).size == 0
    assert sampler.block_samples("gx", 1, 3, dt, skip=total - 4, count=4).size == 4
    assert sampler.block_samples("gx", 2, 2, dt, skip=0, count=0).size == 0
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("gx", 2, 2, dt, skip=0, count=1)


def test_block_samples_invalid_axis_name_raises_value_error():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("gw", 0, 1, SYSTEM.grad_raster_time)


@pytest.mark.parametrize(
    "first,stop",
    [(-1, 1), (3, 1), (0, 100)],
    ids=["negative_first", "first_greater_than_stop", "stop_past_num_blocks"],
)
def test_block_samples_bad_range_raises_value_error(first, stop):
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("gx", first, stop, SYSTEM.grad_raster_time)


def test_block_samples_off_raster_block_raises_value_error():
    # pypulseq's make_delay accepts a duration that is not a whole number of raster
    # steps (1.5 here); block_samples must still refuse to sample it.
    dt = SYSTEM.grad_raster_time
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(pp.make_delay(1.5 * dt))
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("gx", 0, 1, dt)


def test_raster_block_lengths_with_different_block_lengths():
    seq = gre_sequence(num_trs=2)
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    expected = np.rint(index.duration_s / dt).astype(np.int64)
    np.testing.assert_array_equal(n, expected)
    # gre_sequence's TR has blocks of different lengths (RF, phase-encode, readout,
    # spoiler, delay): not every block has the same duration.
    assert len(set(index.duration_s.tolist())) > 1


def test_raster_block_lengths_detects_a_block_off_the_raster():
    dt = SYSTEM.grad_raster_time
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(pp.make_delay(2 * dt))
    seq.add_block(pp.make_delay(1.5 * dt))
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert not on_raster
    np.testing.assert_array_equal(n, np.array([2, 2]))


def _delay_sequence(durations_s: list[float]) -> pp.Sequence:
    seq = signed(pp.Sequence(SYSTEM))
    for duration_s in durations_s:
        seq.add_block(pp.make_delay(duration_s))
    return seq


def test_sequence_samples_on_the_raster_is_the_sum_of_the_block_lengths():
    """The blocks 0.01938 s and 0.01268 s are 1938 and 1268 samples at 1e-5 s. The sequence
    has 3206 samples. `index.end_s` is 3206.0000000000005 samples, so a `ceil` of it gives
    3207."""
    dt = SYSTEM.grad_raster_time
    index = sequence_index(_delay_sequence([0.01938, 0.01268]))
    assert sequence_samples(index, dt) == 3206
    assert math.ceil(index.end_s / dt) == 3207


@pytest.mark.parametrize(
    ("durations_s", "expected"),
    [
        # 2.8 samples. The rounded block lengths sum to 2.
        pytest.param([1.4e-5, 1.4e-5], 3, id="more_than_the_rounded_lengths"),
        # 3.000005 samples less 1e-10 s is 3.000000 samples.
        pytest.param([1.5e-5, 1.500005e-5], 3, id="end_within_1e-10_s_above_a_sample"),
    ],
)
def test_sequence_samples_off_the_raster_is_the_ceil_of_the_end(durations_s, expected):
    dt = SYSTEM.grad_raster_time
    index = sequence_index(_delay_sequence(durations_s))
    assert not raster_block_lengths(index, dt)[1]
    assert sequence_samples(index, dt) == expected
    assert sequence_samples(index, dt) == math.ceil((index.end_s - 1e-10) / dt)


@pytest.mark.parametrize(
    ("ratio", "on_raster"),
    [
        pytest.param(1 + 5e-7, True, id="above-inside"),
        pytest.param(1 - 5e-7, True, id="below-inside"),
        pytest.param(1 + 2e-6, False, id="above-outside"),
        pytest.param(1 - 2e-6, False, id="below-outside"),
    ],
)
def test_raster_block_lengths_tolerance_is_a_millionth_of_a_sample(ratio, on_raster):
    """A block of `ratio` samples, with `ratio` within 5e-7 of a whole number, is on the
    raster, and one of 2e-6 away is not. The number of samples is the whole number in each
    case."""
    dt = SYSTEM.grad_raster_time
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(pp.make_delay(ratio * dt))
    index = sequence_index(seq)
    assert index.duration_s[0] / dt == pytest.approx(ratio, rel=0, abs=1e-12)
    n, got = raster_block_lengths(index, dt)
    assert got is on_raster
    np.testing.assert_array_equal(n, np.array([1]))


def _assert_samples_match(got: np.ndarray, ref: np.ndarray) -> None:
    """`got` equals `ref` (the samples of the oracle) within 1e-9 of the largest |value|.
    The two are not bit-equal: `block_samples` takes the sample time from the block start, and
    the oracle from the sum of the block durations before it, which drifts by float
    rounding (the same tolerance as `test_block_samples_matches_sample_at_file_raster_times`)."""
    assert got.dtype == np.float64
    assert got.shape == ref.shape
    peak = float(np.max(np.abs(ref))) if ref.size else 0.0
    np.testing.assert_allclose(got, ref, rtol=0.0, atol=1e-9 * peak)


# The cases of the tests of `block_samples` against the oracle: (sequence, divisor of the gradient
# raster). The sample raster is the gradient raster, or a half or a fifth of it, where a ramp of
# half a raster time (and the line of a short gap) has more samples. The block durations of the
# model sequences are whole numbers of gradient rasters, so they are whole numbers of these too.
# Each sequence of the model is at the gradient raster, and the sequences with a gap at the finer
# rasters.
_GAP_NAMES = (
    "short_gap",
    "long_gap",
    "issue_12_delayed",
    "step_then_gap",
    "off_raster_events",
)
_WHOLE_CASES = [(name, 1) for name in _MODEL_SEQUENCES] + [
    (name, divisor) for name in _GAP_NAMES for divisor in (2, 5)
]


@pytest.mark.parametrize(("name", "divisor"), _WHOLE_CASES)
def test_block_samples_equals_the_oracle_for_the_whole_sequence(name, divisor):
    """`block_samples` of the whole sequence equals `oracle.block_samples` (the values of the
    polyline of the model of MATLAB Pulseq at the block-local times) for each axis, at the
    gradient raster and at finer rasters."""
    seq = _model_sequence(name)
    index = sequence_index(seq)
    dt = _RASTER / divisor
    assert raster_block_lengths(index, dt)[1]
    sampler = GradientSampler(index, event_points(seq))
    for axis in "xyz":
        got = sampler.block_samples(f"g{axis}", 0, index.num_blocks, dt)
        _assert_samples_match(got, oracle.block_samples(seq, axis, dt))


@pytest.mark.parametrize(
    ("name", "divisor"),
    [
        ("long_gap", 2),
        ("short_gap", 1),
        ("zero_gap", 1),
        ("issue_12_delayed", 5),
        ("step_then_gap", 1),
        ("off_raster_events", 1),
        ("off_raster_events", 5),
    ],
)
def test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range(
    name, divisor
):
    """Each range of blocks, and each range of samples (`skip` and `count`, with ranges that
    start or end inside a gap or a ramp), of `block_samples` equals the same samples of the
    oracle, and the same slice of the whole range exactly (a sampler that made the whole range
    first, and a new one)."""
    seq = _model_sequence(name)
    index = sequence_index(seq)
    dt = _RASTER / divisor
    n_all, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    sampler = GradientSampler(index, event_points(seq))
    for axis in "xyz":
        reference = oracle.block_samples(seq, axis, dt)
        whole = sampler.block_samples(f"g{axis}", 0, index.num_blocks, dt)
        for first in range(index.num_blocks):
            for stop in range(first + 1, index.num_blocks + 1):
                offset = int(n_all[:first].sum())
                length = int(n_all[first:stop].sum())
                part = sampler.block_samples(f"g{axis}", first, stop, dt)
                assert np.array_equal(part, whole[offset : offset + length])
                _assert_samples_match(part, reference[offset : offset + length])
                for skip, count in _sample_ranges(n_all[first:stop]):
                    got = sampler.block_samples(f"g{axis}", first, stop, dt, skip=skip, count=count)
                    assert np.array_equal(got, part[skip : skip + count]), (
                        first,
                        stop,
                        skip,
                        count,
                    )
                    fresh = GradientSampler(index, event_points(seq))
                    got = fresh.block_samples(f"g{axis}", first, stop, dt, skip=skip, count=count)
                    assert np.array_equal(got, part[skip : skip + count]), (
                        first,
                        stop,
                        skip,
                        count,
                    )


def test_the_samples_in_a_short_gap_are_the_line_by_hand():
    """`short_gap_sequence`: the first gradient ends at 3 U at 100 us, its block ends at 110
    us, and the second block starts at 2 U. The gap is one raster time, so the sample at 105
    us (the last of block 0) is on the line from 3 U to 2 U: 2.5 U. It is 0 in the own event
    of block 0, after its last point. The other samples are those of the own events. The
    first sample of block 1 (5 us) is on the ramp down of block 1."""
    seq = _model_sequence("short_gap")
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
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
    seq = _off_raster_events_sequence()
    sampler = GradientSampler(sequence_index(seq), event_points(seq))
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


def test_a_ramp_from_a_raster_edge_changes_no_sample_at_the_gradient_raster():
    """`long_gap_sequence` has events on the raster edges and ends that are not 0 next to a
    long gap. Its ramps of half a raster time end at the raster centres, where they are 0, so
    `block_samples` at the gradient raster has the samples of the own events, 0 in the gap
    (D7 of `docs/plans/third-review-fixes.md`)."""
    seq = _model_sequence("long_gap")
    index = sequence_index(seq)
    sampler = GradientSampler(index, event_points(seq))
    got = sampler.block_samples("gx", 0, 3, _RASTER)
    assert got.shape == (40,)
    np.testing.assert_allclose(got[10:30], 0.0, rtol=0, atol=1e-9 * 3e4)
    assert got[9] == pytest.approx(2.85e4)
    assert got[30] == pytest.approx(1.9e4, rel=1e-9)
