"""Tests of the kept event points (`_events.py`): the points of the unique gradient events
are read one time for each sequence, they are read-only, and `GradientSampler` and
`grad_peaks._event_values` give the same values as the points read from `grad_events`."""

import numpy as np
import pypulseq as pp
import pytest
from synthetic import (
    EXAMPLE_HW,
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    signed,
    spin_echo_sequence,
)

from pulseq_analysis._events import EventPoints, event_points
from pulseq_analysis.grad_peaks import (
    _event_values,
    _polyline_values,
    block_gradient_values,
    gradient_peaks,
)
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.pns_levels import pns_levels
from pulseq_analysis.sampling import GradientSampler
from pulseq_analysis.seq_index import grad_events, sequence_index
from pulseq_analysis.seq_utils import gradient_offsets, gradient_points

_SEQUENCES = [
    pytest.param(spin_echo_sequence, id="spin_echo"),
    pytest.param(gre_sequence, id="gre"),
    pytest.param(arbitrary_gradient_sequence, id="arbitrary_gradient"),
]


def _points_from_grad_events(seq: pp.Sequence) -> EventPoints:
    """The `EventPoints` of `seq` built here from `grad_events` and `gradient_offsets`, with
    one list for each array, for the comparison with `event_points`."""
    delays, counts, offsets, amps = [], [], [], []
    for _, g in grad_events(seq, sequence_index(seq)):
        delay, event_offsets, amp = gradient_offsets(g)
        delays.append(delay)
        counts.append(len(event_offsets))
        offsets.extend(event_offsets)
        amps.extend(amp)
    count = np.array(counts, dtype=np.int64)
    return EventPoints(
        np.array(delays, dtype=np.float64),
        count,
        np.cumsum(count) - count,
        np.array(offsets, dtype=np.float64),
        np.array(amps, dtype=np.float64),
    )


@pytest.mark.parametrize("build", _SEQUENCES)
def test_the_measurements_of_one_sequence_read_each_unique_gradient_event_once(build, monkeypatch):
    """`gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum` of one
    sequence together call `get_block` one time for each unique gradient event, and not
    for each measurement."""
    seq = build()
    unique = sequence_index(seq).grad_first.size
    assert unique > 0
    calls: list[int] = []
    original = pp.Sequence.get_block

    def counting(self, block_id):
        calls.append(block_id)
        return original(self, block_id)

    monkeypatch.setattr(pp.Sequence, "get_block", counting)
    gradient_peaks(seq)
    block_gradient_values(seq)
    pns_levels(seq, hardware=EXAMPLE_HW)
    gradient_spectrum(seq)
    assert len(calls) == unique


@pytest.mark.parametrize(
    "build",
    [*_SEQUENCES, pytest.param(empty_sequence, id="empty")],
)
def test_event_points_arrays_are_read_only_and_have_the_documented_types(build):
    """Each array of `event_points(seq)` has `writeable` False, so a write to it raises
    `ValueError`, and has the dtype of the documented field: float64 for `delay`,
    `offsets` and `amp`, int64 for `count` and `at`. The arrays of the K events have K
    items, and the pools have `count.sum()` items."""
    seq = build()
    points = event_points(seq)
    unique = sequence_index(seq).grad_first.size
    for name, dtype in (
        ("delay", np.float64),
        ("count", np.int64),
        ("at", np.int64),
        ("offsets", np.float64),
        ("amp", np.float64),
    ):
        array = getattr(points, name)
        assert array.dtype == dtype, name
        assert not array.flags.writeable, name
        with pytest.raises(ValueError, match="read-only"):
            array[...] = 0
    assert points.delay.size == points.count.size == points.at.size == unique
    assert points.offsets.size == points.amp.size == int(points.count.sum())


@pytest.mark.parametrize("build", _SEQUENCES)
def test_event_points_has_the_points_that_grad_events_gives(build):
    """`event_points(seq)` has the same arrays (`array_equal`) as the points that this test
    reads from `grad_events` and `gradient_offsets`."""
    seq = build()
    points = event_points(seq)
    expected = _points_from_grad_events(seq)
    for name in ("delay", "count", "at", "offsets", "amp"):
        assert np.array_equal(getattr(points, name), getattr(expected, name)), name


@pytest.mark.parametrize("build", _SEQUENCES)
def test_a_gradient_sampler_uses_the_arrays_of_event_points_without_a_copy(build):
    """`GradientSampler(index, event_points(seq))` keeps the pooled points of
    `event_points` as they are, with no copy."""
    seq = build()
    points = event_points(seq)
    sampler = GradientSampler(sequence_index(seq), points)
    assert np.shares_memory(sampler._offsets, points.offsets)
    assert np.shares_memory(sampler._amp, points.amp)


@pytest.mark.parametrize("build", _SEQUENCES)
def test_event_values_of_the_points_equal_the_values_of_gradient_points(build):
    """`_event_values(event_points(seq))` has, for each unique gradient event, the points
    `t_rel` and `amp` of `gradient_points(g, 0.0)` and the values of `_polyline_values` of
    them, each equal bit for bit (`array_equal`, `==`), where `g` is the event that
    `grad_events` gives."""
    seq = build()
    ev = _event_values(event_points(seq))
    events = list(grad_events(seq, sequence_index(seq)))
    assert len(ev.t_rel) == len(ev.amp) == len(events)
    for dense_k, g in events:
        i = dense_k - 1
        t, amp = gradient_points(g, 0.0)
        values = _polyline_values(t, amp)
        assert np.array_equal(ev.t_rel[i], t)
        assert np.array_equal(ev.amp[i], amp)
        assert ev.peak[i] == values.peak
        assert ev.peak_offset[i] == values.peak_time
        assert ev.slew[i] == values.slew
        assert ev.slew_offset[i] == values.slew_time
        assert ev.integral[i] == values.integral
        assert ev.first[i] == amp[0]
        assert ev.first_offset[i] == t[0]
        assert ev.last[i] == amp[-1]


def test_event_values_of_a_trapezoid_and_an_arbitrary_gradient_equal_hand_computed_values():
    """`_event_values` of an x trapezoid with a delay and a y arbitrary gradient gives, for each
    event, the peak, the time of the peak, the slew, the time of the slew and the integral of
    amplitude^2, each equal to a value computed by hand from the numbers given to the `make_*`
    functions.

    Trapezoid: amplitude A, delay d, rise R, flat F and fall L, with L longer than R. Its points
    are at d, d + R, d + R + F and d + R + F + L, with the values 0, A, A, 0. The rise is the
    steepest segment, with the slope A / R from d. Its integral is A^2 (R / 3 + F + L / 3).

    Arbitrary gradient: raster r, unit u, the waveform [1, 2, -3, -1, 2] u and the first and last
    values 0. Its points are at 0, 0.5 r, 1.5 r, 2.5 r, 3.5 r, 4.5 r and 5 r, with the values 0,
    1 u, 2 u, -3 u, -1 u, 2 u and 0. The largest |value| is 3 u at 2.5 r. The slopes are 2 u / r,
    1 u / r, 5 u / r, 2 u / r, 3 u / r and 4 u / r, and the largest is 5 u / r, from 1.5 r. The
    integral is the sum of dt (a^2 + a b + b^2) / 3 over the six segments, which is
    (1/6 + 7/3 + 7/3 + 13/3 + 1 + 2/3) r u^2 = 65/6 r u^2. (The waveform has 5 samples because
    pypulseq reads back an arbitrary gradient of 4 samples or fewer with a shape that ends at the
    last sample, not half a raster time after it.)
    """
    amplitude, delay, rise, flat, fall = 1e5, 100e-6, 200e-6, 400e-6, 300e-6
    raster, unit = SYSTEM.grad_raster_time, 1e4
    trapezoid = pp.make_trapezoid(
        channel="x",
        amplitude=amplitude,
        delay=delay,
        rise_time=rise,
        flat_time=flat,
        fall_time=fall,
        system=SYSTEM,
    )
    arbitrary = pp.make_arbitrary_grad(
        channel="y",
        waveform=np.array([1.0, 2.0, -3.0, -1.0, 2.0]) * unit,
        first=0.0,
        last=0.0,
        system=SYSTEM,
    )
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(trapezoid)
    seq.add_block(arbitrary)

    ev = _event_values(event_points(seq))

    assert ev.peak.tolist() == pytest.approx([amplitude, 3 * unit], rel=1e-12)
    assert ev.peak_offset.tolist() == pytest.approx([delay + rise, 2.5 * raster], abs=1e-12)
    assert ev.slew.tolist() == pytest.approx([amplitude / rise, 5 * unit / raster], rel=1e-12)
    assert ev.slew_offset.tolist() == pytest.approx([delay, 1.5 * raster], abs=1e-12)
    expected_integral = [
        amplitude**2 * (rise / 3 + flat + fall / 3),
        65 / 6 * raster * unit**2,
    ]
    assert ev.integral.tolist() == pytest.approx(expected_integral, rel=1e-12)
