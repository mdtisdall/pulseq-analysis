"""Tests of the kept event points (`_events.py`): the points of the unique gradient events
are read one time for each snapshot, they are read-only, `GradientSampler` keeps them
without a copy, and `grad_peaks._event_values` gives hand-computed values from them. The
tests of the kept results are here too: a measurement gives the same object for one snapshot,
a windowed `gradient_peaks` uses the kept values of the events, and a kept result does not keep
its snapshot alive."""

import dataclasses
import gc
import weakref

import numpy as np
import pypulseq as pp
import pytest
from synthetic import (
    EXAMPLE_HW,
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    loaded,
    spin_echo_sequence,
)

from pulseq_analysis import grad_peaks
from pulseq_analysis._events import event_points
from pulseq_analysis.grad_peaks import (
    _event_values,
    block_gradient_values,
    gradient_peaks,
)
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.pns_levels import pns_levels
from pulseq_analysis.sampling import GradientSampler
from pulseq_analysis.seq_index import sequence_index

_SEQUENCES = [
    pytest.param(spin_echo_sequence, id="spin_echo"),
    pytest.param(gre_sequence, id="gre"),
    pytest.param(arbitrary_gradient_sequence, id="arbitrary_gradient"),
]


@pytest.mark.parametrize("build", _SEQUENCES)
def test_the_measurements_of_one_sequence_read_each_unique_gradient_event_once(build, monkeypatch):
    """`gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum` of one
    snapshot together call `get_block` one time for each unique gradient event, and not
    for each measurement."""
    snap = loaded(build())
    unique = sequence_index(snap).grad_first.size
    assert unique > 0
    calls: list[int] = []
    original = pp.Sequence.get_block

    def counting(self, block_id):
        calls.append(block_id)
        return original(self, block_id)

    monkeypatch.setattr(pp.Sequence, "get_block", counting)
    gradient_peaks(snap)
    block_gradient_values(snap)
    pns_levels(snap, hardware=EXAMPLE_HW)
    gradient_spectrum(snap)
    assert len(calls) == unique


@pytest.mark.parametrize(
    "build",
    [*_SEQUENCES, pytest.param(empty_sequence, id="empty")],
)
def test_event_points_arrays_are_read_only_and_have_the_documented_types(build):
    """Each array of `event_points(snap)` has `writeable` False, so a write to it raises
    `ValueError`, and has the dtype of the documented field: float64 for `delay`,
    `offsets` and `amp`, int64 for `count` and `at`. The arrays of the K events have K
    items, and the pools have `count.sum()` items."""
    snap = loaded(build())
    points = event_points(snap)
    unique = sequence_index(snap).grad_first.size
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
def test_a_gradient_sampler_uses_the_arrays_of_event_points_without_a_copy(build):
    """`GradientSampler(snap)` keeps the pooled points of `event_points(snap)` as they are,
    with no copy."""
    snap = loaded(build())
    points = event_points(snap)
    sampler = GradientSampler(snap)
    assert np.shares_memory(sampler._offsets, points.offsets)
    assert np.shares_memory(sampler._amp, points.amp)


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
    seq = pp.Sequence(SYSTEM)
    seq.add_block(trapezoid)
    seq.add_block(arbitrary)

    ev = _event_values(event_points(loaded(seq)))

    assert ev.peak.tolist() == pytest.approx([amplitude, 3 * unit], rel=1e-12)
    assert ev.peak_offset.tolist() == pytest.approx([delay + rise, 2.5 * raster], abs=1e-12)
    assert ev.slew.tolist() == pytest.approx([amplitude / rise, 5 * unit / raster], rel=1e-12)
    assert ev.slew_offset.tolist() == pytest.approx([delay, 1.5 * raster], abs=1e-12)
    expected_integral = [
        amplitude**2 * (rise / 3 + flat + fall / 3),
        65 / 6 * raster * unit**2,
    ]
    assert ev.integral.tolist() == pytest.approx(expected_integral, rel=1e-12)


@pytest.mark.parametrize(
    "measure",
    [
        sequence_index,
        gradient_peaks,
        block_gradient_values,
        lambda snap: pns_levels(snap, hardware=EXAMPLE_HW),
        gradient_spectrum,
    ],
    ids=["sequence_index", "gradient_peaks", "block_gradient_values", "pns_levels", "spectrum"],
)
def test_a_measurement_gives_the_same_object_for_one_snapshot_and_an_equal_one_for_another(
    measure,
):
    """Two calls of the measurement with one snapshot give one object (the result is kept).
    A second snapshot of the same sequence gives another object with an equal value."""
    seq = spin_echo_sequence()
    snap = loaded(seq)
    first = measure(snap)
    assert measure(snap) is first

    other = measure(loaded(seq))
    assert other is not first
    assert other == first


def test_event_points_are_the_same_object_for_one_snapshot_and_equal_arrays_for_another():
    """Two calls of `event_points` with one snapshot give one object. A second snapshot of the
    same sequence gives another object with equal arrays."""
    seq = spin_echo_sequence()
    snap = loaded(seq)
    first = event_points(snap)
    assert event_points(snap) is first

    other = event_points(loaded(seq))
    assert other is not first
    for field in dataclasses.fields(first):
        assert np.array_equal(getattr(other, field.name), getattr(first, field.name)), field.name


def test_a_windowed_gradient_peaks_is_a_new_object_for_each_call_and_is_not_kept():
    """Two calls with one window give equal results that are two objects, and a call with a
    window does not change the kept result of `window=None`: before and after the windowed
    calls, `gradient_peaks(snap)` is one object. A windowed result is not the whole-file
    result."""
    snap = loaded(spin_echo_sequence())
    window = (0.0, sequence_index(snap).end_s / 2)
    whole = gradient_peaks(snap)
    first = gradient_peaks(snap, window=window)
    second = gradient_peaks(snap, window=window)
    assert first is not second
    assert first == second
    assert first is not whole
    assert gradient_peaks(snap) is whole

    fresh = loaded(spin_echo_sequence())
    windowed_first = gradient_peaks(fresh, window=window)
    assert gradient_peaks(fresh) is not windowed_first


def test_a_windowed_gradient_peaks_uses_the_kept_per_event_values(monkeypatch):
    """`_event_values` runs one time for a snapshot, whatever the calls: a call with a
    window, a second call with another window, `gradient_peaks(snap)` and
    `block_gradient_values(snap)` share one `_EventData`. A new snapshot has its own."""
    calls = []
    original = grad_peaks._event_values

    def counting(points):
        calls.append(points)
        return original(points)

    monkeypatch.setattr(grad_peaks, "_event_values", counting)
    snap = loaded(spin_echo_sequence())
    end_s = sequence_index(snap).end_s
    gradient_peaks(snap, window=(0.0, end_s / 2))
    assert len(calls) == 1
    gradient_peaks(snap, window=(end_s / 4, end_s))
    gradient_peaks(snap)
    block_gradient_values(snap)
    assert len(calls) == 1

    gradient_peaks(loaded(spin_echo_sequence()))
    assert len(calls) == 2


def test_a_kept_gradient_peaks_cannot_be_changed_in_place():
    """The kept result of `gradient_peaks(snap)` refuses an assignment to a field of the
    result and of an axis, and a change of `axes`; the kept `block_gradient_values(snap)`
    refuses a write to an array. After the refusals the next call gives an equal value."""
    snap = loaded(spin_echo_sequence())
    peaks = gradient_peaks(snap)
    blocks = block_gradient_values(snap)
    expected_peaks = gradient_peaks(loaded(spin_echo_sequence()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        peaks.vector_peak_hz_per_m = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        peaks.axes["x"].peak_hz_per_m = 0.0
    with pytest.raises(TypeError):
        peaks.axes["x"] = peaks.axes["y"]
    with pytest.raises(ValueError, match="read-only"):
        blocks.start_s[0] = -1.0
    with pytest.raises(TypeError):
        blocks.peak_hz_per_m["x"] = blocks.peak_hz_per_m["y"]
    assert gradient_peaks(snap) is peaks
    assert peaks == expected_peaks
    assert block_gradient_values(snap) is blocks


@pytest.mark.parametrize(
    "measure",
    [
        sequence_index,
        event_points,
        gradient_peaks,
        block_gradient_values,
        lambda snap: pns_levels(snap, hardware=EXAMPLE_HW),
        gradient_spectrum,
    ],
    ids=[
        "sequence_index",
        "event_points",
        "gradient_peaks",
        "block_gradient_values",
        "pns_levels",
        "gradient_spectrum",
    ],
)
def test_a_kept_result_does_not_keep_the_snapshot_alive(measure):
    """After a call of the measurement and `del snap`, `gc.collect()` collects the snapshot:
    a `weakref` to it is dead. The kept result has no reference to the snapshot."""
    snap = loaded(spin_echo_sequence())
    result = measure(snap)
    reference = weakref.ref(snap)
    del snap
    gc.collect()
    assert reference() is None
    assert result is not None


@pytest.mark.parametrize(
    "function",
    [
        event_points,
        gradient_peaks,
        block_gradient_values,
        lambda seq: pns_levels(seq, hardware=EXAMPLE_HW),
        gradient_spectrum,
        GradientSampler,
    ],
    ids=[
        "event_points",
        "gradient_peaks",
        "block_gradient_values",
        "pns_levels",
        "gradient_spectrum",
        "GradientSampler",
    ],
)
def test_a_measurement_raises_type_error_that_names_load_for_a_sequence(function):
    """`event_points`, the measurements and `GradientSampler` raise `TypeError` that names
    `load` for a `pp.Sequence`, which `load` has not made a snapshot of."""
    with pytest.raises(TypeError, match="load"):
        function(spin_echo_sequence())
