import pytest

pytestmark = pytest.mark.pypulseq
pytest.importorskip("pypulseq")

import math
import pathlib

import numpy as np
import pypulseq as pp
from gap_sequences import (
    delayed_sequence,
    early_end_sequence,
    gap_of_1_5_raster_times_sequence,
    long_gap_sequence,
    negated,
    non_zero_ends_sequence,
    short_gap_from_0_sequence,
    short_gap_sequence,
    short_gap_to_0_sequence,
    zero_gap_sequence,
)
from oracles import waveform as oracle
from oracles.blocks import sequence_of
from random_gaps import random_gap_sequence
from synthetic import (
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.analyses import load
from pulseq_analysis.synth import _events, seq_index
from pulseq_analysis.synth._played import played_gradients
from pulseq_analysis.synth.sampling import (
    GradientSampler,
    gradient_sampler,
    raster_block_lengths,
    sequence_samples,
)
from pulseq_analysis.synth.seq_index import sequence_index
from pulseq_analysis.synth.snapshot import Snapshot

_AXES = ("x", "y", "z")
_RASTER = SYSTEM.grad_raster_time
# The largest end value that `add_block` accepts next to a gap, halved (the value A of
# `delayed_sequence` and `early_end_sequence`).
_A = 0.5 * SYSTEM.max_slew * _RASTER


def _raster_centers(duration_s: float, raster: float = SYSTEM.grad_raster_time) -> np.ndarray:
    """`(k + 0.5) * raster` for `k` in `range(ceil(duration_s / raster))`."""
    n = int(np.ceil(duration_s / raster)) if duration_s > 0 else 0
    return (np.arange(n) + 0.5) * raster


def _assert_matches_oracle(snap: Snapshot, t: np.ndarray) -> None:
    """`GradientSampler.sample(axis, t)` equals `oracle.sample(sequence_of(snap), axis, t)` (the model of
    MATLAB Pulseq, `tests/oracles/waveform.py`) within a relative 1e-12 and an absolute
    1e-12 times the largest |value| of that axis's reference at `t`. The two build the same
    points and differ by the float rounding of the interpolation formula only."""
    sampler = gradient_sampler(snap)
    for axis in "xyz":
        ref = oracle.sample(sequence_of(snap), axis, t)
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
    """A gap between two events on x, with a value that is not 0 at each end of it: an
    extended trapezoid that ramps from 0 to half of `max_slew * grad_raster_time` (the
    largest value that pypulseq's `add_block` accepts next to a block with no gradient is
    `max_slew * grad_raster_time`), a delay block with no gradient on x, and an extended
    trapezoid that starts at a quarter of `max_slew * grad_raster_time` and ramps to 0."""
    raster = SYSTEM.grad_raster_time
    unit = SYSTEM.max_slew * raster
    seq = pp.Sequence(SYSTEM)
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
    second block, inside the ramp to 0 after the last value (half a raster time long),
    inside the rest of the gap (where the waveform is 0) and around the start of the
    trapezoid."""
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
    index = sequence_index(load(seq))
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


def test_a_subrange_inside_a_long_gap_has_its_ramps_and_zero_and_matches_the_oracle():
    """`_gap_sequence` has a long gap (2 ms) with a value that is not 0 at each end of it.
    A time range inside the gap that has the ramp to 0 after the first end, the 0 between
    the ramps and the ramp from 0 before the second end gives the values of the oracle.
    The ramps are half a raster time long. The range has times only in the gap, so the
    events before and after it are not in the block range of the call."""
    snap = load(_gap_sequence())
    index = sequence_index(snap)
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
    got = gradient_sampler(snap).sample("x", t)
    assert np.all(got[:5] != 0.0)
    assert np.all(got[5:25] == 0.0)
    assert np.all(got[25:] != 0.0)
    _assert_matches_oracle(snap, t)


def test_range_across_a_step_and_a_ramp_equals_the_same_slice_of_the_whole_grid():
    seq, t = _step_then_gap_sequence()
    snap = load(seq)
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
    whole = sampler.sample("x", t)
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
            assert np.array_equal(sampler.sample("x", t[i:j]), whole[i:j]), (i, j)
    _assert_matches_oracle(snap, t)


def test_times_before_an_event_that_starts_at_a_value_that_is_not_0_have_the_ramp_from_0():
    """The gap is the end of block 0 (a trapezoid that ends at 300 us, in a block held for
    1 ms by a delay) and the next event starts with block 1, at half of
    `max_slew * grad_raster_time` and with no delay. The gap is long and the trapezoid ends
    at 0, so the waveform is 0 in the gap except the ramp from 0 in the last half raster time
    before the next event: the line from (995 us, 0) to (1 ms, the value). Hand values."""
    raster = SYSTEM.grad_raster_time
    step = 0.5 * SYSTEM.max_slew * raster
    seq = pp.Sequence(SYSTEM)
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
    snap = load(seq)
    index = sequence_index(snap)
    assert index.num_blocks == 2
    assert index.start_s[1] == pytest.approx(1e-3)
    t = np.array([600e-6, 800e-6, 995e-6, 996e-6, 997.5e-6, 999e-6, 1e-3])
    expected = np.array([0.0, 0.0, 0.0, 0.2 * step, 0.5 * step, 0.8 * step, step])
    sampler = gradient_sampler(snap)
    got = sampler.sample("x", t)
    np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9 * step)
    _assert_matches_oracle(snap, t)


def test_amplitude_continues_across_a_block_junction():
    seq, junction_s = _junction_sequence(step_hz_per_m=0.0)
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * SYSTEM.grad_raster_time)
    _assert_matches_oracle(load(seq), t)


def test_a_tolerated_step_at_a_block_junction_is_a_step_that_the_oracle_has():
    """A step of half of `max_slew * grad_raster_time` at the junction in the middle of the
    flat top: the value at the time of the step is the earlier value, and the value after
    it is the later one (flat) until the fall. pypulseq draws a line from the earlier value
    to the end of the flat of the later block instead: it drops the first point of the later
    event, at the time of the last point of the earlier event (pypulseq
    `Sequence/sequence.py:1683-1689`, at the fork commit `3c3bd85` that uv.lock pins). So the
    test compares with the oracle and with the hand values."""
    step = 0.5 * SYSTEM.max_slew * SYSTEM.grad_raster_time
    seq, junction_s = _junction_sequence(step_hz_per_m=step)
    base = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    raster = SYSTEM.grad_raster_time
    t = np.sort(junction_s + np.linspace(-20, 20, 41) * raster)
    snap = load(seq)
    _assert_matches_oracle(snap, t)
    sampler = gradient_sampler(snap)
    got = sampler.sample(
        "x", np.array([junction_s - 10 * raster, junction_s, junction_s + 10 * raster])
    )
    # The values are those of the written file: 6 significant digits (relative 5e-6 at most).
    np.testing.assert_allclose(
        got, [base.amplitude, base.amplitude, base.amplitude - step], rtol=1e-5
    )


def test_triangle_trapezoid_matches_the_oracle():
    """A trapezoid with no flat time (`_triangle_sequence`, two points at the middle time):
    `sample` equals the oracle on the raster centres and the points of its polyline."""
    snap = load(_triangle_sequence())
    _assert_matches_oracle(snap, _model_times(snap))


def test_sample_matches_the_added_events_for_an_oversampled_arbitrary_gradient(tmp_path):
    """`sample` for a file with an oversampled arbitrary gradient against a reference built
    from the added events (the objects that `make_*` returns, before `add_block`), not
    from `get_block` and not from `seq.get_gradients()`: `get_gradients()` itself leaves
    out the first and the last point of an oversampled gradient. Its times are not at the
    centres of the raster, so `waveforms()` takes the branch of an extended trapezoid, which
    has no `first` and no `last` (pypulseq `Sequence/sequence.py:1582-1614`, at the fork
    commit `3c3bd85` that uv.lock pins).

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

    # `load(seq)` fails here: `seq.remove_duplicates()` of pypulseq raises `KeyError` for the
    # time shape -1 of an oversampled gradient. The file is written without it, as `load` writes it.
    path = tmp_path / "oversampled.seq"
    seq.write(str(path), create_signature=True, remove_duplicates=False, check_timing=False)
    sampler = gradient_sampler(load(path))
    got = sampler.sample("x", grid)
    # The values are those of the written file: 6 significant digits of the amplitudes.
    np.testing.assert_allclose(got, truth, rtol=0, atol=1e-5 * peak)


def test_zero_before_the_first_event_and_after_the_last():
    snap = load(_delay_padded_sequence())
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
    before = np.linspace(0.0, index.start_s[1] - 1e-6, 50)
    after = np.linspace(index.start_s[2] + 1e-6, index.end_s, 50)
    got_before = sampler.sample("x", before)
    got_after = sampler.sample("x", after)
    np.testing.assert_array_equal(got_before, np.zeros(before.shape, dtype=np.float64))
    np.testing.assert_array_equal(got_after, np.zeros(after.shape, dtype=np.float64))


def test_empty_sequence_is_zero_for_any_t():
    snap = load(empty_sequence())
    sampler = gradient_sampler(snap)
    t = np.array([0.0, 1e-3, 5.0])  # 5.0 s is well past the sequence's own duration
    for axis in _AXES:
        got = sampler.sample(axis, t)
        assert got.dtype == np.float64
        np.testing.assert_array_equal(got, np.zeros(t.shape, dtype=np.float64))


def test_empty_times_gives_empty_output():
    snap = load(gre_sequence(num_trs=1))
    sampler = gradient_sampler(snap)
    got = sampler.sample("x", np.array([]))
    assert got.dtype == np.float64
    assert got.shape == (0,)


def test_invalid_axis_name_raises_value_error():
    snap = load(gre_sequence(num_trs=1))
    sampler = gradient_sampler(snap)
    with pytest.raises(ValueError):
        sampler.sample("gw", np.array([0.0]))


def test_the_axes_are_x_y_and_z():
    """`sample` and `block_samples` take the axis names of the results, "x", "y" and "z", and
    give the waveform of that axis: the values of `oracle.sample` and `oracle.block_samples`
    on a sequence with gradient events on each of the three axes."""
    snap = load(gre_sequence(num_trs=2))
    seq = sequence_of(snap)
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
    t = _model_times(snap)
    for axis in "xyz":
        ref = oracle.sample(seq, axis, t)
        assert np.any(ref), axis
        peak = float(np.max(np.abs(ref)))
        np.testing.assert_allclose(sampler.sample(axis, t), ref, rtol=1e-12, atol=1e-12 * peak)
        got = sampler.block_samples(axis, 0, index.num_blocks, _RASTER)
        _assert_samples_match(got, oracle.block_samples(seq, axis, _RASTER))


@pytest.mark.parametrize("column", ["gx", "gy", "gz"])
def test_the_block_table_column_names_are_not_axis_names(column):
    """`sample` and `block_samples` raise `ValueError` for the names of the block table's
    gradient columns, "gx", "gy" and "gz", with a message that names the axes "x", "y" and
    "z"."""
    sampler = gradient_sampler(load(gre_sequence(num_trs=1)))
    with pytest.raises(ValueError, match=r"\('x', 'y', 'z'\)"):
        sampler.sample(column, np.array([0.0]))
    with pytest.raises(ValueError, match=r"\('x', 'y', 'z'\)"):
        sampler.block_samples(column, 0, 1, _RASTER)


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
    seq = pp.Sequence(SYSTEM)
    seq.add_block(first, pp.make_delay(8 * _RASTER))
    seq.add_block(second, pp.make_delay(8 * _RASTER))
    return seq


def _random_gap_builder(seed: int, for_spec: bool = False):
    return lambda: random_gap_sequence(np.random.default_rng(seed), for_spec=for_spec)


# The sequences of the model: each gap rule (a zero gap, a short gap, a long gap, the first and the
# last value not 0, `delayed_sequence` and `early_end_sequence`), the synthetic sequences, and
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
    "gap_of_1_5_raster_times": gap_of_1_5_raster_times_sequence,
    "short_gap_from_0": short_gap_from_0_sequence,
    "short_gap_to_0": short_gap_to_0_sequence,
}
# The sequences of `gap_sequences` with every amplitude negated (the gap rules do not depend on the
# sign), and the random sequences of `random_gaps` (random signs, zero, short and long gaps): those
# of `random_gap_sequence(rng)`, which `spec` rejects, and those of `random_gap_sequence(rng,
# for_spec=True)`, which it reads (with blocks of zero duration).
_MODEL_SEQUENCES |= {
    f"negated_{name}": (lambda build=_MODEL_SEQUENCES[name]: negated(build()))
    for name in (
        "zero_gap",
        "short_gap",
        "long_gap",
        "non_zero_ends",
        "issue_12_delayed",
        "issue_12_early_end",
    )
}
_MODEL_SEQUENCES |= {f"random_gaps_{seed}": _random_gap_builder(seed) for seed in range(8)}
_MODEL_SEQUENCES |= {
    f"random_gaps_for_spec_{seed}": _random_gap_builder(seed, for_spec=True) for seed in range(8)
}


def _model_sequence(name: str) -> pp.Sequence:
    """The sequence `name` of `_MODEL_SEQUENCES`."""
    return _MODEL_SEQUENCES[name]()


# The sequences of the model that the interpreter `spec` rejects: a gradient that ends above 0
# before its block ends (`gradient.nonzero-end-align`), a gradient that starts above 0 after a
# delay (`gradient.nonzero-start-delay`) or a delay off the gradient raster
# (`raster.gradient-delay`). The tests are about the waveform model, not about the specification,
# so the tests of these sequences are in `test_measurements_in_pulseq_analysis.py` of
# `pulseq-cpp-siemens`, which loads them with `cpp-siemens`, which plays them.
_REJECTED_BY_SPEC = {
    "short_gap",
    "issue_12_delayed",
    "issue_12_early_end",
    "off_raster_events",
    "gap_of_1_5_raster_times",
    "short_gap_to_0",
    "negated_short_gap",
    "negated_issue_12_delayed",
    "negated_issue_12_early_end",
} | {f"random_gaps_{seed}" for seed in range(8)}


def _name_of(case):
    """The name of a case of a test: the case, or the first item of the case."""
    return case if isinstance(case, str) else case[0]


def _read_by_spec(cases: list) -> list:
    """The cases of `cases` whose sequence `spec` reads (not `_REJECTED_BY_SPEC`)."""
    return [case for case in cases if _name_of(case) not in _REJECTED_BY_SPEC]


def _load_model(name: str) -> Snapshot:
    """The snapshot of the sequence `name` of `_MODEL_SEQUENCES`, read by `spec`."""
    assert name not in _REJECTED_BY_SPEC
    return load(_model_sequence(name))


def _model_times(snap: Snapshot) -> np.ndarray:
    """A sorted grid of times (s) of `snap`: the raster centres, an even grid across the
    sequence (a little before and after), and the points of the polyline of the oracle on
    each axis, each also a little before and after (so the ramp points, the steps and the
    ends are there)."""
    end = sequence_index(snap).end_s
    times = [_raster_centers(end), np.linspace(-_RASTER, end + _RASTER, 2001)]
    for axis in "xyz":
        t = oracle.axis_polyline(sequence_of(snap), axis).t
        times += [t, t - 1e-7, t + 1e-7]
    return np.unique(np.concatenate(times))


@pytest.mark.parametrize("name", _read_by_spec(list(_MODEL_SEQUENCES)))
def test_sample_equals_the_oracle_for_the_whole_sequence(name):
    """`sample` equals the oracle (the model of MATLAB Pulseq) on a grid across each
    sequence of the model that `spec` reads, with times at the points, the steps and the
    ramps."""
    snap = _load_model(name)
    _assert_matches_oracle(snap, _model_times(snap))


# Block 1 (100 us) has x from 0 to 1000 Hz/m, which ends at 1000 Hz/m at 100 us. Block 2, of
# duration 0, has the trapezoid 2 on x with rise, flat and fall times 0, which plays 0. Block 3
# (100 us) has x from 1000 Hz/m at 100 us to 0. Blocks 2 and 3 start at 100 us, the time of the
# step of x from 1000 Hz/m to 0 and back.
_BLOCK_OF_DURATION_0_AT_A_STEP = """\
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
1 10 0 1 0 0 0 0
2 0 0 2 0 0 0 0
3 10 0 3 0 0 0 0

[GRADIENTS]
1 1000 0 1000 1 0 0
3 1000 1000 0 1 0 0

[TRAP]
2 500 0 0 0 0

[SHAPES]

shape_id 1
num_samples 10
1
1
1
1
1
1
1
1
1
1
"""


def _load_text(directory: pathlib.Path, name: str, text: str) -> Snapshot:
    """The snapshot, read by `spec`, of the file `name`.seq with the text `text`, written in
    `directory`."""
    path = directory / f"{name}.seq"
    path.write_text(text)
    return load(path)


def test_sample_at_the_start_of_a_block_of_duration_0_does_not_depend_on_the_first_time(tmp_path):
    """At 100 us, where block 1 of `_BLOCK_OF_DURATION_0_AT_A_STEP` ends and a block of duration 0
    and the block after it start, `sample` gives the same value whether 100 us is the first time
    or the second, and the value of the oracle: the value before the step, 1000 Hz/m. The
    sample range of 100 us alone starts at the block of duration 0, so it needs the event of
    block 1, before that block."""
    snap = _load_text(tmp_path, "block_of_duration_0_at_a_step", _BLOCK_OF_DURATION_0_AT_A_STEP)
    sampler = gradient_sampler(snap)
    alone = sampler.sample("x", np.array([100e-6]))
    second = sampler.sample("x", np.array([95e-6, 100e-6]))
    ref = oracle.sample(sequence_of(snap), "x", np.array([100e-6]))
    assert alone[0] == second[1]
    assert alone[0] == 1000.0
    np.testing.assert_allclose(alone, ref, rtol=1e-12, atol=0.0)


# The sequences of `_TIME_RANGE_NAMES` that are the text of a file, not a sequence of
# `_MODEL_SEQUENCES`. The test writes each file in its `tmp_path`.
_TIME_RANGE_TEXTS = {"block_of_duration_0_at_a_step": _BLOCK_OF_DURATION_0_AT_A_STEP}

_TIME_RANGE_NAMES = [
    "long_gap",
    "short_gap",
    "zero_gap",
    "issue_12_delayed",
    "off_raster_events",
    "gap_of_1_5_raster_times",
    "short_gap_from_0",
    "negated_long_gap",
    "block_of_duration_0_at_a_step",
]


def check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(snap: Snapshot) -> None:
    """Each time range `t[i:j]` of a grid of times of `snap` at the ends of the events, inside the
    gap, at the ramps and at the steps: `sample` equals the oracle, and the same slice of
    the whole grid exactly (a range that starts or ends inside a gap or a ramp has the
    events around it). The grid has each block start, so that a range starts and ends at
    each one, also where blocks of duration 0 start."""
    full = _model_times(snap)
    t = np.unique(np.concatenate([full[:: max(1, full.size // 40)], sequence_index(snap).start_s]))
    sampler = gradient_sampler(snap)
    for axis in "xyz":
        whole = sampler.sample(axis, t)
        ref = oracle.sample(sequence_of(snap), axis, t)
        peak = float(np.max(np.abs(ref)))
        np.testing.assert_allclose(whole, ref, rtol=1e-12, atol=1e-12 * peak)
        for i in range(t.size):
            for j in range(i + 1, t.size + 1):
                assert np.array_equal(sampler.sample(axis, t[i:j]), whole[i:j]), (axis, i, j)


@pytest.mark.parametrize("name", _read_by_spec(_TIME_RANGE_NAMES))
def test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(name, tmp_path):
    """Each time range of a grid of times, for the sequences of the model that `spec` reads and
    the files of `_TIME_RANGE_TEXTS`
    (`check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`)."""
    if name in _TIME_RANGE_TEXTS:
        snap = _load_text(tmp_path, name, _TIME_RANGE_TEXTS[name])
    else:
        snap = _load_model(name)
    check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid(snap)


def test_the_gaps_are_found_one_time_for_each_sequence_and_axis():
    """The pieces of `long_gap_sequence` (gx): the ramp to 0 from 100 us to 105 us, and the
    ramp from 0 from 295 us to 300 us, with the points of the two ramps at 105 us and 295 us
    (`_events.ramps`, kept with the events of the axis). Two samplers of one snapshot have the same kept
    `_AxisGaps` object (read-only arrays). An axis with no event has none. A second snapshot of the
    same sequence finds its own gaps, with equal arrays."""
    seq = _model_sequence("long_gap")
    snap = load(seq)
    sampler = gradient_sampler(snap)
    gaps = sampler._gaps("x")
    assert gradient_sampler(snap)._gaps("x") is gaps
    np.testing.assert_allclose(gaps.start_s, [100e-6, 295e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(gaps.end_s, [105e-6, 300e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(gaps.start_hz_per_m, [3e4, 0.0])
    np.testing.assert_allclose(gaps.end_hz_per_m, [0.0, 2e4])
    _, _, ramp = sampler._axis_events("x")
    np.testing.assert_allclose(ramp.to_s[ramp.after], [105e-6], rtol=0, atol=1e-12)
    np.testing.assert_allclose(ramp.from_s[ramp.before], [295e-6], rtol=0, atol=1e-12)
    for array in (gaps.start_s, gaps.end_s, gaps.start_hz_per_m, gaps.end_hz_per_m):
        assert not array.flags.writeable
    assert sampler._gaps("y").start_s.size == 0
    again = gradient_sampler(load(seq))._gaps("x")
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
    snap = load(seq)
    index = sequence_index(snap)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    total = int(n.sum())
    t_file = (np.arange(total, dtype=np.float64) + 0.5) * dt
    sampler = gradient_sampler(snap)
    for axis in _AXES:
        got = sampler.block_samples(axis, 0, index.num_blocks, dt)
        ref = sampler.sample(axis, t_file)
        assert got.shape == ref.shape
        peak = float(np.max(np.abs(ref))) if ref.size else 0.0
        np.testing.assert_allclose(got, ref, atol=1e-9 * peak, rtol=0.0)


def test_range_inside_the_file_equals_the_same_slice_of_the_whole_file():
    snap = load(gre_sequence(num_trs=3))
    dt = SYSTEM.grad_raster_time
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
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
    snap = load(seq)
    index = sequence_index(snap)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    assert n[0] == n_block
    sampler = gradient_sampler(snap)
    whole = sampler.block_samples("x", 0, 2, dt)
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
        got = sampler.block_samples("x", 0, 2, dt, skip=skip, count=count)
        assert np.array_equal(got, whole[skip : skip + count]), (skip, count)


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
    snap = load(gre_sequence(num_trs=1))
    sampler = gradient_sampler(snap)
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("x", 1, 3, SYSTEM.grad_raster_time, skip=skip, count=count)


def test_skip_plus_count_up_to_the_range_end_is_accepted():
    """`skip + count` equal to the samples of the range is not an error (the edge of the
    check), also for an empty range of blocks."""
    snap = load(gre_sequence(num_trs=1))
    dt = SYSTEM.grad_raster_time
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
    n, _ = raster_block_lengths(index, dt)
    total = int(n[1:3].sum())
    assert sampler.block_samples("x", 1, 3, dt, skip=total, count=0).size == 0
    assert sampler.block_samples("x", 1, 3, dt, skip=total - 4, count=4).size == 4
    assert sampler.block_samples("x", 2, 2, dt, skip=0, count=0).size == 0
    with pytest.raises(ValueError, match="skip"):
        sampler.block_samples("x", 2, 2, dt, skip=0, count=1)


def test_block_samples_invalid_axis_name_raises_value_error():
    snap = load(gre_sequence(num_trs=1))
    sampler = gradient_sampler(snap)
    with pytest.raises(ValueError):
        sampler.block_samples("gw", 0, 1, SYSTEM.grad_raster_time)


@pytest.mark.parametrize(
    "first,stop",
    [(-1, 1), (3, 1), (0, 100)],
    ids=["negative_first", "first_greater_than_stop", "stop_past_num_blocks"],
)
def test_block_samples_bad_range_raises_value_error(first, stop):
    snap = load(gre_sequence(num_trs=1))
    sampler = gradient_sampler(snap)
    with pytest.raises(ValueError):
        sampler.block_samples("x", first, stop, SYSTEM.grad_raster_time)


def test_block_samples_off_raster_block_raises_value_error():
    # A file holds a block duration in whole block raster times, which is the gradient raster
    # time here, so a block is off the raster of the samples when that raster is 2 gradient
    # raster times and the block is 3 (1.5 samples); block_samples must refuse to sample it.
    raster = SYSTEM.grad_raster_time
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(3 * raster))
    sampler = gradient_sampler(load(seq))
    with pytest.raises(ValueError):
        sampler.block_samples("x", 0, 1, 2 * raster)


def test_raster_block_lengths_with_different_block_lengths():
    snap = load(gre_sequence(num_trs=2))
    dt = SYSTEM.grad_raster_time
    index = sequence_index(snap)
    n, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    # Each TR of 20 ms is 2000 samples: the RF block of 1.12 ms, the phase encode of 0.36 ms,
    # the readout of 1.64 ms, the spoiler of 0.87 ms and the delay of 16.01 ms.
    np.testing.assert_array_equal(n, np.array([112, 36, 164, 87, 1601] * 2))
    # gre_sequence's TR has blocks of different lengths (RF, phase-encode, readout,
    # spoiler, delay): not every block has the same duration.
    assert len(set(index.duration_s.tolist())) > 1


def test_raster_block_lengths_detects_a_block_off_the_raster():
    # Blocks of 4 and 3 gradient raster times, with a sample raster of 2: 2 and 1.5 samples.
    raster = SYSTEM.grad_raster_time
    dt = 2 * raster
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(4 * raster))
    seq.add_block(pp.make_delay(3 * raster))
    index = sequence_index(load(seq))
    n, on_raster = raster_block_lengths(index, dt)
    assert not on_raster
    np.testing.assert_array_equal(n, np.array([2, 2]))


def _delay_sequence(durations_s: list[float]) -> pp.Sequence:
    seq = pp.Sequence(SYSTEM)
    for duration_s in durations_s:
        seq.add_block(pp.make_delay(duration_s))
    return seq


def test_sequence_samples_on_the_raster_is_the_sum_of_the_block_lengths():
    """The blocks 0.01938 s and 0.01268 s are 1938 and 1268 samples at 1e-5 s. The sequence
    has 3206 samples. `index.end_s` is 3206.0000000000005 samples, so a `ceil` of it gives
    3207."""
    dt = SYSTEM.grad_raster_time
    index = sequence_index(load(_delay_sequence([0.01938, 0.01268])))
    assert sequence_samples(index, dt) == 3206
    assert math.ceil(index.end_s / dt) == 3207


@pytest.mark.parametrize(
    ("durations_s", "dt", "expected"),
    [
        # Blocks of 7 gradient raster times with a sample raster of 5: 2.8 samples. The rounded
        # block lengths sum to 2.
        pytest.param(
            [7 * _RASTER, 7 * _RASTER], 5 * _RASTER, 3, id="more_than_the_rounded_lengths"
        ),
        # Blocks of 1 and 2 gradient raster times with a sample raster that is 3 gradient
        # raster times over 3.000005: 3.000005 samples less 1e-10 s is 3.000000 samples.
        pytest.param(
            [_RASTER, 2 * _RASTER],
            3 * _RASTER / 3.000005,
            3,
            id="end_within_1e-10_s_above_a_sample",
        ),
    ],
)
def test_sequence_samples_off_the_raster_is_the_ceil_of_the_end(durations_s, dt, expected):
    """A file holds a block duration in whole block raster times (the gradient raster time
    here), so the blocks are off the raster of the samples through `dt`."""
    index = sequence_index(load(_delay_sequence(durations_s)))
    assert not raster_block_lengths(index, dt)[1]
    assert sequence_samples(index, dt) == expected


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
    case. A file holds a block duration in whole block raster times, so the block is one
    gradient raster time and the sample raster is `1 / ratio` of it."""
    dt = SYSTEM.grad_raster_time / ratio
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(SYSTEM.grad_raster_time))
    index = sequence_index(load(seq))
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
    "gap_of_1_5_raster_times",
    "short_gap_from_0",
    "short_gap_to_0",
    "negated_long_gap",
    "negated_short_gap",
)
_WHOLE_CASES = [(name, 1) for name in _MODEL_SEQUENCES] + [
    (name, divisor) for name in _GAP_NAMES for divisor in (2, 5)
]


def check_block_samples_equal_the_oracle_for_the_whole_sequence(snap: Snapshot, divisor: int):
    """`block_samples` of the whole sequence of `snap` equals `oracle.block_samples` (the values
    of the polyline of the model of MATLAB Pulseq at the block-local times) for each axis, at
    the sample raster of the gradient raster divided by `divisor`."""
    index = sequence_index(snap)
    dt = _RASTER / divisor
    assert raster_block_lengths(index, dt)[1]
    sampler = gradient_sampler(snap)
    for axis in "xyz":
        got = sampler.block_samples(axis, 0, index.num_blocks, dt)
        _assert_samples_match(got, oracle.block_samples(sequence_of(snap), axis, dt))


@pytest.mark.parametrize(("name", "divisor"), _read_by_spec(_WHOLE_CASES))
def test_block_samples_equals_the_oracle_for_the_whole_sequence(name, divisor):
    """`block_samples` of the whole sequence equals `oracle.block_samples` for each axis, at the
    gradient raster and at finer rasters, for the sequences of the model that `spec` reads
    (`check_block_samples_equal_the_oracle_for_the_whole_sequence`)."""
    check_block_samples_equal_the_oracle_for_the_whole_sequence(_load_model(name), divisor)


_ANY_RANGE_CASES = [
    ("long_gap", 2),
    ("short_gap", 1),
    ("zero_gap", 1),
    ("issue_12_delayed", 5),
    ("step_then_gap", 1),
    ("off_raster_events", 1),
    ("off_raster_events", 5),
    ("gap_of_1_5_raster_times", 1),
    ("negated_long_gap", 2),
]


def check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range(
    snap: Snapshot, divisor: int
) -> None:
    """Each range of blocks, and each range of samples (`skip` and `count`, with ranges that
    start or end inside a gap or a ramp), of `block_samples` of `snap` at the sample raster of the
    gradient raster divided by `divisor` equals the same samples of the oracle, and the same
    slice of the whole range exactly (a sampler that made the whole range first, and a new
    one)."""
    index = sequence_index(snap)
    dt = _RASTER / divisor
    n_all, on_raster = raster_block_lengths(index, dt)
    assert on_raster
    sampler = gradient_sampler(snap)
    for axis in "xyz":
        reference = oracle.block_samples(sequence_of(snap), axis, dt)
        whole = sampler.block_samples(axis, 0, index.num_blocks, dt)
        for first in range(index.num_blocks):
            for stop in range(first + 1, index.num_blocks + 1):
                offset = int(n_all[:first].sum())
                length = int(n_all[first:stop].sum())
                part = sampler.block_samples(axis, first, stop, dt)
                assert np.array_equal(part, whole[offset : offset + length])
                _assert_samples_match(part, reference[offset : offset + length])
                for skip, count in _sample_ranges(n_all[first:stop]):
                    got = sampler.block_samples(axis, first, stop, dt, skip=skip, count=count)
                    assert np.array_equal(got, part[skip : skip + count]), (
                        first,
                        stop,
                        skip,
                        count,
                    )
                    fresh = gradient_sampler(snap)
                    got = fresh.block_samples(axis, first, stop, dt, skip=skip, count=count)
                    assert np.array_equal(got, part[skip : skip + count]), (
                        first,
                        stop,
                        skip,
                        count,
                    )


@pytest.mark.parametrize(("name", "divisor"), _read_by_spec(_ANY_RANGE_CASES))
def test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range(
    name, divisor
):
    """Each range of blocks, and each range of samples, of `block_samples` equals the same
    samples of the oracle, and the same slice of the whole range exactly, for the sequences of
    the model that `spec` reads
    (`check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range`)."""
    check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range(
        _load_model(name), divisor
    )


@pytest.mark.parametrize("long_first", [False, True])
def test_one_event_in_blocks_of_two_lengths_gives_the_samples_of_each_length(long_first):
    """One gradient event in two blocks of 13 and 40 samples (the second has a delay event
    of 400 us) gives the samples of each length: the oracle's samples for the block, whichever
    of the two lengths the sampler meets first, and exactly the samples of a new sampler that
    meets only that range."""
    g = pp.make_trapezoid("x", amplitude=1e4, rise_time=50e-6, flat_time=30e-6, fall_time=50e-6)
    short, long = [g], [g, pp.make_delay(400e-6)]
    seq = pp.Sequence(SYSTEM)
    for events in (long, short) if long_first else (short, long):
        seq.add_block(*events)
    snap = load(seq)
    index = sequence_index(snap)
    n_all, on_raster = raster_block_lengths(index, _RASTER)
    assert on_raster
    assert sorted(n_all) == [13, 40]
    assert index.gx[0] == index.gx[1] > 0  # one event
    reference = oracle.block_samples(sequence_of(snap), "x", _RASTER)
    ends = np.cumsum(n_all)
    for calls in ([(0, 1), (1, 2), (0, 2)], [(1, 2), (0, 1), (0, 2)]):
        sampler = gradient_sampler(snap)
        for first, stop in calls:
            got = sampler.block_samples("x", first, stop, _RASTER)
            lo = int(ends[first] - n_all[first])
            _assert_samples_match(got, reference[lo : int(ends[stop - 1])])
            fresh = gradient_sampler(snap).block_samples("x", first, stop, _RASTER)
            assert np.array_equal(got, fresh), (calls, first, stop)


def test_a_ramp_from_a_raster_edge_changes_no_sample_at_the_gradient_raster():
    """`long_gap_sequence` has events on the raster edges and ends that are not 0 next to a
    long gap. Its ramps of half a raster time end at the raster centres, where they are 0, so
    `block_samples` at the gradient raster has the samples of the own events, 0 in the gap
    (D7 of `docs/plans/third-review-fixes.md`)."""
    snap = _load_model("long_gap")
    sampler = gradient_sampler(snap)
    got = sampler.block_samples("x", 0, 3, _RASTER)
    assert got.shape == (40,)
    np.testing.assert_allclose(got[10:30], 0.0, rtol=0, atol=1e-9 * 3e4)
    assert got[9] == pytest.approx(2.85e4)
    assert got[30] == pytest.approx(1.9e4, rel=1e-9)


@pytest.mark.parametrize("build", [gre_sequence, lambda: "sequence.seq"], ids=["sequence", "path"])
def test_gradient_sampler_raises_type_error_that_names_load_for_a_non_snapshot(build):
    """`gradient_sampler` raises `TypeError` that names `load` for a `pp.Sequence` and for a
    path: it takes a `Snapshot`."""
    with pytest.raises(TypeError, match="load"):
        gradient_sampler(build())


def test_a_sampler_is_made_only_by_gradient_sampler():
    """`gradient_sampler(snap)` is the one way to make a sampler (the user, 2026-10-14):
    `GradientSampler(snap)` raises `TypeError` that names `gradient_sampler`, and `GradientSampler`
    stays the type of a sampler."""
    snap = _load_model("gre")
    with pytest.raises(TypeError, match="gradient_sampler"):
        GradientSampler(snap)
    assert isinstance(gradient_sampler(snap), GradientSampler)


# ---- GradientSampler._from_parts ----


_FROM_PARTS_NAMES = [
    "long_gap",
    "short_gap",
    "zero_gap",
    "off_raster_events",
    "gre",
    "spin_echo",
    "random_gaps_0",
]


def check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot(
    snap: Snapshot,
) -> None:
    """`GradientSampler._from_parts` with an index and points made again from `snap`
    (not the kept ones) and an empty dict gives, bit for bit, the `sample` and
    `block_samples` values of `gradient_sampler(snap)`. Its gaps are kept in the dict that
    was passed, equal to those of the snapshot's sampler, and not on the snapshot."""
    played = played_gradients(snap)
    index = seq_index._index_from_data(snap.data, (played.gx, played.gy, played.gz))
    points = _events._read_points(snap)
    assert index is not sequence_index(snap)
    kept: dict = {}
    parts = GradientSampler._from_parts(index, points, kept)
    whole = gradient_sampler(snap)
    t = _model_times(snap)
    for axis in _AXES:
        assert np.array_equal(parts.sample(axis, t), whole.sample(axis, t))
        got = parts.block_samples(axis, 0, index.num_blocks, _RASTER)
        assert np.array_equal(got, whole.block_samples(axis, 0, index.num_blocks, _RASTER))
    assert set(kept) == {("gaps", axis) for axis in _AXES}
    for axis in _AXES:
        assert kept[("gaps", axis)] is parts._gaps(axis)
        assert kept[("gaps", axis)] is not whole._gaps(axis)
        for field in ("start_s", "end_s", "start_hz_per_m", "end_hz_per_m"):
            mine, theirs = getattr(kept[("gaps", axis)], field), getattr(whole._gaps(axis), field)
            assert np.array_equal(mine, theirs)


@pytest.mark.parametrize("name", _read_by_spec(_FROM_PARTS_NAMES))
def test_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot(name):
    """`GradientSampler._from_parts` gives, bit for bit, the values of `gradient_sampler(snap)`,
    for the sequences that `spec` reads
    (`check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`)."""
    check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot(_load_model(name))
