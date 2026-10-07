"""Tests of the kept results (`_kept.py`): when `sequence_index`, `event_points`,
`gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum` keep a result
for a sequence object, and when they make it again.
"""

import copy
import dataclasses
import gc
import weakref

import numpy as np
import pypulseq as pp
import pytest
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from synthetic import SYSTEM, WIDTH, spin_echo_sequence

from pulseq_analysis import grad_peaks
from pulseq_analysis._events import event_points
from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.pns_levels import pns_levels
from pulseq_analysis.seq_index import sequence_index

_HARDWARE = (safe_example_hw(), "example")


def _sequence(channel: str, area: float, gap_s: float, repeats: int = 3) -> pp.Sequence:
    """`repeats` times a trapezoid of `area` on `channel` and a delay of `gap_s`: 2 *
    `repeats` blocks, whatever the gradient and the delay."""
    seq = pp.Sequence(SYSTEM)
    for _ in range(repeats):
        seq.add_block(pp.make_trapezoid(channel=channel, area=area, system=SYSTEM))
        seq.add_block(pp.make_delay(gap_s))
    return seq


def _file_a(tmp_path):
    path = tmp_path / "a.seq"
    _sequence("x", 2 / WIDTH, 15e-3).write(str(path))
    return path


def _file_b(tmp_path):
    path = tmp_path / "b.seq"
    _sequence("y", 5 / WIDTH, 22e-3).write(str(path))
    return path


def _read(path) -> pp.Sequence:
    seq = pp.Sequence()
    seq.read(str(path))
    return seq


def _assert_index_equal(a, b):
    assert a.num_blocks == b.num_blocks
    assert a.end_s == b.end_s
    for field in dataclasses.fields(a):
        if isinstance(getattr(a, field.name), np.ndarray):
            assert np.array_equal(getattr(a, field.name), getattr(b, field.name)), field.name


def test_a_second_read_into_one_object_gives_the_values_of_a_new_object(tmp_path):
    """File A and file B have the same number of blocks, different gradients and different
    durations. After the results for A are made, B is read into the same `Sequence`:
    `sequence_index`, `gradient_peaks`, `block_gradient_values`, `pns_levels` and
    `gradient_spectrum` give the values of a new object that read B only, and not the kept values of A."""
    path_a, path_b = _file_a(tmp_path), _file_b(tmp_path)
    reused = _read(path_a)
    index_a = sequence_index(reused)
    levels_a = pns_levels(reused, hardware=_HARDWARE)
    spectrum_a = gradient_spectrum(reused)
    limits_a = gradient_peaks(reused)
    blocks_a = block_gradient_values(reused)
    reused.read(str(path_b))
    fresh = _read(path_b)
    assert len(reused.block_events) == len(fresh.block_events) == len(index_a.block_id)

    expected_index = sequence_index(fresh)
    assert expected_index.end_s != index_a.end_s
    _assert_index_equal(sequence_index(reused), expected_index)
    levels = pns_levels(reused, hardware=_HARDWARE)
    assert levels == pns_levels(fresh, hardware=_HARDWARE)
    assert levels != levels_a
    spectrum = gradient_spectrum(reused)
    assert spectrum == gradient_spectrum(fresh)
    assert spectrum != spectrum_a
    limits = gradient_peaks(reused)
    assert limits == gradient_peaks(fresh)
    assert limits != limits_a
    blocks = block_gradient_values(reused)
    assert blocks == block_gradient_values(fresh)
    assert blocks != blocks_a


def test_event_points_are_kept_and_made_again_after_a_second_read_into_one_object(tmp_path):
    """`event_points` gives one object for two calls with no change between them. After a
    second file with other gradients is read into the same `Sequence`, it gives a new
    object, with the points of a new object that read that file only (`array_equal` for
    each array)."""
    path_a, path_b = _file_a(tmp_path), _file_b(tmp_path)
    reused = _read(path_a)
    points_a = event_points(reused)
    assert event_points(reused) is points_a
    reused.read(str(path_b))
    points_b = event_points(reused)
    assert points_b is not points_a
    assert event_points(reused) is points_b
    expected = event_points(_read(path_b))
    for field in dataclasses.fields(expected):
        assert np.array_equal(getattr(points_b, field.name), getattr(expected, field.name))
    assert not np.array_equal(points_b.amp, points_a.amp)


def test_pns_levels_gives_a_new_result_after_add_block_and_the_same_without_a_change():
    """Two calls with no change between them give one object. After `add_block` the
    result is a new object, and it is the result of a new sequence with the same blocks."""
    seq = spin_echo_sequence()
    first = pns_levels(seq, hardware=_HARDWARE)
    assert pns_levels(seq, hardware=_HARDWARE) is first

    seq.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    second = pns_levels(seq, hardware=_HARDWARE)
    assert second is not first
    assert pns_levels(seq, hardware=_HARDWARE) is second
    expected = spin_echo_sequence()
    expected.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    assert second == pns_levels(expected, hardware=_HARDWARE)


def test_gradient_peaks_and_block_gradient_values_give_a_new_result_after_add_block_and_the_same_without_a_change():
    """Two calls with no change between them give one object, for each of the two
    functions. After `add_block` each gives a new object, and it is the result of a new
    sequence with the same blocks."""
    seq = spin_echo_sequence()
    peaks = gradient_peaks(seq)
    blocks = block_gradient_values(seq)
    assert gradient_peaks(seq) is peaks
    assert block_gradient_values(seq) is blocks

    seq.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    new_peaks = gradient_peaks(seq)
    new_blocks = block_gradient_values(seq)
    assert new_peaks is not peaks
    assert new_blocks is not blocks
    assert gradient_peaks(seq) is new_peaks
    assert block_gradient_values(seq) is new_blocks
    expected = spin_echo_sequence()
    expected.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    assert new_peaks == gradient_peaks(expected)
    assert new_blocks == block_gradient_values(expected)
    assert new_blocks != blocks


def test_gradient_peaks_with_a_window_is_a_new_object_for_each_call_and_is_not_kept():
    """Two calls with one window give equal results that are two objects, and a call with a
    window does not change the kept result of `window=None`: before and after the windowed
    calls, `gradient_peaks(seq)` is one object. A windowed result is not the whole-file
    result."""
    seq = spin_echo_sequence()
    window = (0.0, sequence_index(seq).end_s / 2)
    whole = gradient_peaks(seq)
    first = gradient_peaks(seq, window=window)
    second = gradient_peaks(seq, window=window)
    assert first is not second
    assert first == second
    assert first is not whole
    assert gradient_peaks(seq) is whole

    fresh = spin_echo_sequence()
    windowed_first = gradient_peaks(fresh, window=window)
    assert gradient_peaks(fresh) is not windowed_first


def test_a_windowed_gradient_peaks_uses_the_kept_per_event_values(monkeypatch):
    """`_event_values` runs one time for a sequence object, whatever the calls: a call with a
    window, a second call with another window, `gradient_peaks(seq)` and
    `block_gradient_values(seq)` share one `_EventData`. A new sequence object has its own,
    and so has an object after `add_block`."""
    calls = []
    original = grad_peaks._event_values

    def counting(points):
        calls.append(points)
        return original(points)

    monkeypatch.setattr(grad_peaks, "_event_values", counting)
    seq = spin_echo_sequence()
    end_s = sequence_index(seq).end_s
    gradient_peaks(seq, window=(0.0, end_s / 2))
    assert len(calls) == 1
    gradient_peaks(seq, window=(end_s / 4, end_s))
    gradient_peaks(seq)
    block_gradient_values(seq)
    assert len(calls) == 1

    gradient_peaks(spin_echo_sequence())
    assert len(calls) == 2
    seq.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    gradient_peaks(seq, window=(0.0, end_s / 2))
    assert len(calls) == 3


def test_a_kept_gradient_peaks_cannot_be_changed_in_place():
    """The kept result of `gradient_peaks(seq)` refuses an assignment to a field of the
    result and of an axis, and a change of `axes`; the kept `block_gradient_values(seq)`
    refuses a write to an array. After the refusals the next call gives an equal value."""
    seq = spin_echo_sequence()
    peaks = gradient_peaks(seq)
    blocks = block_gradient_values(seq)
    expected_peaks = gradient_peaks(spin_echo_sequence())
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
    assert gradient_peaks(seq) is peaks
    assert peaks == expected_peaks
    assert block_gradient_values(seq) is blocks


def test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result(
    write_gradient_asc, monkeypatch
):
    """`pns_levels` with `hardware_from_asc` of the relative path and with that of the
    absolute path of one `.asc` file gives one object, in both orders of the two calls."""
    path = write_gradient_asc()
    monkeypatch.chdir(path.parent)
    relative = hardware_from_asc(path.name)
    absolute = hardware_from_asc(path)
    for first, second in ((relative, absolute), (absolute, relative)):
        seq = spin_echo_sequence()
        result = pns_levels(seq, hardware=first)
        assert pns_levels(seq, hardware=second) is result


def test_a_change_of_the_last_block_id_with_the_same_number_of_blocks_gives_a_new_index():
    """The first block is removed from `seq.block_events` and `seq.block_durations`, and a
    block with the same events and a higher ID is added at the end. The number of blocks
    is the same, and the last block ID changed: `sequence_index` gives a new index, whose
    block IDs are the IDs after the change."""
    seq = spin_echo_sequence()
    first = sequence_index(seq)
    assert sequence_index(seq) is first
    first_id = next(iter(seq.block_events))
    new_id = max(seq.block_events) + 1
    seq.block_events[new_id] = seq.block_events.pop(first_id)
    seq.block_durations[new_id] = seq.block_durations.pop(first_id)

    second = sequence_index(seq)
    assert second is not first
    assert second.num_blocks == first.num_blocks
    assert second.block_id.tolist() == [*first.block_id.tolist()[1:], new_id]


def test_a_new_block_durations_object_with_the_same_keys_gives_a_new_index():
    """`seq.block_durations` is replaced by a new dict with the same IDs and each duration
    doubled. The other two objects, the number of blocks, the last block ID and the raster
    time are the same: `sequence_index` gives a new index, whose durations are doubled."""
    seq = spin_echo_sequence()
    first = sequence_index(seq)
    assert sequence_index(seq) is first
    seq.block_durations = {block_id: 2 * d for block_id, d in seq.block_durations.items()}

    second = sequence_index(seq)
    assert second is not first
    assert second.end_s == 2 * first.end_s
    assert np.array_equal(second.duration_s, 2 * first.duration_s)


def test_a_new_block_events_object_with_the_same_keys_gives_a_new_index():
    """`seq.block_events` is replaced by a new dict with the same IDs, in which blocks 2 and
    3 have changed events: block 2 has the gradient event of block 3, and block 3 has that
    of block 2. The other two objects, the number of blocks, the last block ID and the
    raster time are the same: `sequence_index` gives a new index, in which the gradient
    columns have changed."""
    seq = spin_echo_sequence()
    first = sequence_index(seq)
    assert sequence_index(seq) is first
    events = {block_id: event.copy() for block_id, event in seq.block_events.items()}
    events[2], events[3] = events[3], events[2]
    seq.block_events = events

    second = sequence_index(seq)
    assert second is not first
    assert second.num_blocks == first.num_blocks
    assert first.gx.tolist()[:3] == [0, 1, 0]
    assert first.gy.tolist()[:3] == [0, 0, 2]
    assert second.gx.tolist()[:3] == [0, 0, 2]
    assert second.gy.tolist()[:3] == [0, 1, 0]


def test_a_new_grad_library_object_with_other_amplitudes_gives_new_levels():
    """`seq.grad_library` is replaced by a copy with each amplitude doubled. The other two
    objects, the number of blocks, the last block ID and the raster time are the same:
    `pns_levels` gives a new result, whose peak level is the double of the old one."""
    seq = spin_echo_sequence()
    first = pns_levels(seq, hardware=_HARDWARE)
    assert pns_levels(seq, hardware=_HARDWARE) is first
    library = copy.deepcopy(seq.grad_library)
    library.data = {k: (2 * v[0], *v[1:]) for k, v in library.data.items()}
    seq.grad_library = library

    second = pns_levels(seq, hardware=_HARDWARE)
    assert second is not first
    assert second.peak_hz_per_t == pytest.approx(2 * first.peak_hz_per_t)


def test_a_removed_block_with_the_same_last_block_id_gives_a_new_index():
    """Block 3 is removed from `seq.block_events` and `seq.block_durations` in place. The
    three objects, the last block ID and the raster time are the same, and there is one
    block less: `sequence_index` gives a new index, without block 3."""
    seq = spin_echo_sequence()
    first = sequence_index(seq)
    assert sequence_index(seq) is first
    del seq.block_events[3]
    del seq.block_durations[3]

    second = sequence_index(seq)
    assert second is not first
    assert second.num_blocks == first.num_blocks - 1
    assert second.block_id.tolist() == [1, 2, 4, 5, 6]


def test_a_change_of_the_gradient_raster_time_gives_new_kept_results():
    """`seq.grad_raster_time` changes with the blocks the same: `sequence_index`,
    `gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum` each
    give a new object, and a call with no change after it gives that object again."""
    seq = spin_echo_sequence()
    index = sequence_index(seq)
    peaks = gradient_peaks(seq)
    blocks = block_gradient_values(seq)
    levels = pns_levels(seq, hardware=_HARDWARE)
    spectrum = gradient_spectrum(seq)
    assert sequence_index(seq) is index
    assert gradient_peaks(seq) is peaks
    assert block_gradient_values(seq) is blocks
    assert pns_levels(seq, hardware=_HARDWARE) is levels
    assert gradient_spectrum(seq) is spectrum

    seq.grad_raster_time = seq.grad_raster_time / 2
    new_index = sequence_index(seq)
    new_peaks = gradient_peaks(seq)
    new_blocks = block_gradient_values(seq)
    new_levels = pns_levels(seq, hardware=_HARDWARE)
    new_spectrum = gradient_spectrum(seq)
    assert new_index is not index
    assert new_peaks is not peaks
    assert new_blocks is not blocks
    assert new_levels is not levels
    assert new_spectrum is not spectrum
    assert sequence_index(seq) is new_index
    assert gradient_peaks(seq) is new_peaks
    assert block_gradient_values(seq) is new_blocks
    assert pns_levels(seq, hardware=_HARDWARE) is new_levels
    assert gradient_spectrum(seq) is new_spectrum


@pytest.mark.parametrize(
    "keep",
    [
        sequence_index,
        event_points,
        gradient_peaks,
        block_gradient_values,
        lambda seq: pns_levels(seq, hardware=_HARDWARE),
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
def test_a_kept_result_does_not_keep_the_sequence_alive(keep):
    """After a call of the function and `del seq`, `gc.collect()` collects the sequence:
    a `weakref` to it is dead. The kept result has no reference to the sequence."""
    seq = spin_echo_sequence()
    result = keep(seq)
    reference = weakref.ref(seq)
    del seq
    gc.collect()
    assert reference() is None
    assert result is not None
