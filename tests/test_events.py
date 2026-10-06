"""Tests of the kept event points (`_events.py`): the points of the unique gradient events
are read one time for each sequence, they are read-only, and `GradientSampler` and
`grad_peaks._event_values` give the same values as the points read from `grad_events`."""

import numpy as np
import pypulseq as pp
import pytest
from synthetic import (
    EXAMPLE_HW,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
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
def test_a_gradient_sampler_from_event_points_gives_the_samples_of_the_points_from_grad_events(
    build,
):
    """`GradientSampler(index, event_points(seq))` and a sampler of the points that the
    test reads from `grad_events` give the same samples (`array_equal`) of `sample` at the
    raster centres, and of `block_samples` for each axis. The sampler of `event_points`
    uses its arrays without a copy."""
    seq = build()
    index = sequence_index(seq)
    points = event_points(seq)
    sampler = GradientSampler(index, points)
    reference = GradientSampler(index, _points_from_grad_events(seq))
    dt = seq.grad_raster_time
    t = (np.arange(int(np.ceil(index.end_s / dt))) + 0.5) * dt
    for axis in ("gx", "gy", "gz"):
        assert np.array_equal(sampler.sample(axis, t), reference.sample(axis, t)), axis
        assert np.array_equal(
            sampler.block_samples(axis, 0, index.num_blocks, dt),
            reference.block_samples(axis, 0, index.num_blocks, dt),
        ), axis
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
