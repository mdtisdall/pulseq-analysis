import numpy as np
import pypulseq as pp
import pytest
from synthetic import (
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.sampling import GradientSampler, raster_block_lengths
from pulseq_analysis.seq_index import sequence_index

_AXES = ("gx", "gy", "gz")


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
    """
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
    pp_gradients = seq.get_gradients()
    for axis_index, axis in enumerate(_AXES):
        ppoly = pp_gradients[axis_index]
        ref = np.zeros(t.shape, dtype=np.float64) if ppoly is None else ppoly(t)
        got = sampler.sample(axis, t)
        assert got.dtype == np.float64
        assert got.shape == t.shape
        peak = float(np.max(np.abs(ref))) if ref.size else 0.0
        np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-12 * peak)


def _triangle_sequence() -> pp.Sequence:
    """One trapezoid on x with an area small enough that `make_trapezoid` gives it no
    flat time (a triangle): `gradient_offsets` then gives two points at the same middle
    time (both with the peak amplitude), which the join rule must remove one of."""
    seq = pp.Sequence(SYSTEM)
    g = pp.make_trapezoid(channel="x", area=10.0, system=SYSTEM)
    assert g.flat_time == 0.0
    seq.add_block(g)
    return seq


def _gap_sequence() -> pp.Sequence:
    """A trapezoid on x, a delay block with no gradient on x, and a second trapezoid on
    x: the gap between the two events."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=500, system=SYSTEM))
    seq.add_block(pp.make_delay(2e-3))
    seq.add_block(pp.make_trapezoid(channel="x", area=-500, system=SYSTEM))
    return seq


def _delay_padded_sequence() -> pp.Sequence:
    """A delay block, a trapezoid on x, and a second delay block: a leading and a
    trailing gap with no gradient event at all."""
    seq = pp.Sequence(SYSTEM)
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
    seq = pp.Sequence(SYSTEM)
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
    second block, inside the gap (where the waveform is the line from that last value
    to the first value of the trapezoid) and around the start of the trapezoid."""
    raster = SYSTEM.grad_raster_time
    small = 0.5 * SYSTEM.max_slew * raster
    base = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    half_flat = round((base.flat_time / 2) / raster) * raster
    amp = base.amplitude
    seq = pp.Sequence(SYSTEM)
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


def test_subrange_inside_a_gap_matches_pypulseq():
    seq = _gap_sequence()
    index = sequence_index(seq)
    gap_start = index.start_s[1]
    gap_end = index.start_s[1] + index.duration_s[1]
    margin = 50e-6
    t = np.linspace(gap_start + margin, gap_end - margin, 200)
    _assert_matches_pypulseq(seq, t)


def test_range_across_a_step_and_a_gap_equals_the_same_slice_of_the_whole_grid():
    seq, t = _step_then_gap_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
    whole = sampler.sample("gx", t)
    # The gap has a nonzero waveform (the line from the last value of block 1), so a
    # range that starts in the gap needs the event before it.
    in_gap = (t > index.start_s[2]) & (t < index.start_s[3])
    assert in_gap.sum() >= 7
    assert np.all(whole[in_gap] != 0.0)
    for i in range(t.size):
        for j in range(i + 1, t.size + 1):
            assert np.array_equal(sampler.sample("gx", t[i:j]), whole[i:j]), (i, j)


def test_single_sample_matches_pypulseq():
    seq = gre_sequence(num_trs=1)
    index = sequence_index(seq)
    t = np.array([index.start_s[2] + index.duration_s[2] / 2])
    _assert_matches_pypulseq(seq, t)


def test_amplitude_continues_across_a_block_junction():
    seq, junction_s = _junction_sequence(step_hz_per_m=0.0)
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * SYSTEM.grad_raster_time)
    _assert_matches_pypulseq(seq, t)


def test_tolerated_step_at_a_block_junction_matches_pypulseq():
    step = 0.5 * SYSTEM.max_slew * SYSTEM.grad_raster_time
    seq, junction_s = _junction_sequence(step_hz_per_m=step)
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * SYSTEM.grad_raster_time)
    _assert_matches_pypulseq(seq, t)


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

    Needs the fix of pypulseq PR #424, which the pinned fork has (`pulseq-reports-pin-1`):
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
    seq = pp.Sequence(SYSTEM)
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

    sampler = GradientSampler(seq, sequence_index(seq))
    got = sampler.sample("gx", grid)
    np.testing.assert_allclose(got, truth, rtol=0, atol=1e-12 * peak)


def test_axis_without_events_is_zero():
    # spin_echo_sequence uses gx and gy only: gz has no event.
    seq = spin_echo_sequence()
    index = sequence_index(seq)
    assert seq.get_gradients()[2] is None
    t = _raster_centers(index.end_s)
    sampler = GradientSampler(seq, index)
    got = sampler.sample("gz", t)
    assert got.dtype == np.float64
    np.testing.assert_array_equal(got, np.zeros(t.shape, dtype=np.float64))


def test_zero_before_the_first_event_and_after_the_last():
    seq = _delay_padded_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
    before = np.linspace(0.0, index.start_s[1] - 1e-6, 50)
    after = np.linspace(index.start_s[2] + 1e-6, index.end_s, 50)
    got_before = sampler.sample("gx", before)
    got_after = sampler.sample("gx", after)
    np.testing.assert_array_equal(got_before, np.zeros(before.shape, dtype=np.float64))
    np.testing.assert_array_equal(got_after, np.zeros(after.shape, dtype=np.float64))


def test_empty_sequence_is_zero_for_any_t():
    seq = empty_sequence()
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
    t = np.array([0.0, 1e-3, 5.0])  # 5.0 s is well past the sequence's own duration
    for axis in _AXES:
        got = sampler.sample(axis, t)
        assert got.dtype == np.float64
        np.testing.assert_array_equal(got, np.zeros(t.shape, dtype=np.float64))


def test_empty_times_gives_empty_output():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(seq, sequence_index(seq))
    got = sampler.sample("gx", np.array([]))
    assert got.dtype == np.float64
    assert got.shape == (0,)


def test_invalid_axis_name_raises_value_error():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(seq, sequence_index(seq))
    with pytest.raises(ValueError):
        sampler.sample("gw", np.array([0.0]))


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
    sampler = GradientSampler(seq, index)
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
    seq = pp.Sequence(SYSTEM)
    seq.add_block(gx, gz)
    seq.add_block(pp.make_delay(n_block * dt))
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)

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
    sampler = GradientSampler(seq, index)
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
    sampler = GradientSampler(seq, index)
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
                fresh = GradientSampler(seq, index)
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
    seq = pp.Sequence(SYSTEM)
    trapezoid = pp.make_trapezoid(channel="x", area=1000.0, system=SYSTEM)
    seq.add_block(trapezoid, pp.make_delay(n_block * dt))
    seq.add_block(pp.make_trapezoid(channel="x", area=500.0, system=SYSTEM))
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    assert n[0] == n_block
    sampler = GradientSampler(seq, index)
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
    seq = pp.Sequence(SYSTEM)
    seq.add_block(ramp, pp.make_delay(4 * raster))
    sampler = GradientSampler(seq, sequence_index(seq))
    dt = 2 * raster
    assert 0.5 * dt == raster
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt), [amp, 0.0])
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt, skip=0, count=1), [amp])
    np.testing.assert_array_equal(sampler.block_samples("gx", 0, 1, dt, skip=1, count=1), [0.0])


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
    sampler = GradientSampler(seq, sequence_index(seq))
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("gx", 1, 3, SYSTEM.grad_raster_time, skip=skip, count=count)


def test_skip_plus_count_up_to_the_range_end_is_accepted():
    """`skip + count` equal to the samples of the range is not an error (the edge of the
    check), also for an empty range of blocks."""
    seq = gre_sequence(num_trs=1)
    dt = SYSTEM.grad_raster_time
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
    n, _ = raster_block_lengths(index, dt)
    total = int(n[1:3].sum())
    assert sampler.block_samples("gx", 1, 3, dt, skip=total, count=0).size == 0
    assert sampler.block_samples("gx", 1, 3, dt, skip=total - 4, count=4).size == 4
    assert sampler.block_samples("gx", 2, 2, dt, skip=0, count=0).size == 0
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("gx", 2, 2, dt, skip=0, count=1)


def test_block_samples_invalid_axis_name_raises_value_error():
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(seq, sequence_index(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("gw", 0, 1, SYSTEM.grad_raster_time)


@pytest.mark.parametrize(
    "first,stop",
    [(-1, 1), (3, 1), (0, 100)],
    ids=["negative_first", "first_greater_than_stop", "stop_past_num_blocks"],
)
def test_block_samples_bad_range_raises_value_error(first, stop):
    seq = gre_sequence(num_trs=1)
    sampler = GradientSampler(seq, sequence_index(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("gx", first, stop, SYSTEM.grad_raster_time)


def test_block_samples_off_raster_block_raises_value_error():
    # pypulseq's make_delay accepts a duration that is not a whole number of raster
    # steps (1.5 here); block_samples must still refuse to sample it.
    dt = SYSTEM.grad_raster_time
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(1.5 * dt))
    index = sequence_index(seq)
    sampler = GradientSampler(seq, index)
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
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(2 * dt))
    seq.add_block(pp.make_delay(1.5 * dt))
    index = sequence_index(seq)
    n, on_raster = raster_block_lengths(index, dt)
    assert not on_raster
    np.testing.assert_array_equal(n, np.array([2, 2]))
