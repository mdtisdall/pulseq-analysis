"""Tests of the kept results (`_kept.py`): when `sequence_index`, `pns_levels_for` and
`gradient_spectrum_for` keep a result for a sequence object, and when they make it again.
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

from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.grad_peaks import gradient_peaks
from pulseq_analysis.grad_spectrum import gradient_spectrum_for
from pulseq_analysis.pns import pns_levels_for
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
    `sequence_index`, `gradient_peaks`, `pns_levels_for` and `gradient_spectrum_for` give
    the values of a new object that read B only, and not the kept values of A."""
    path_a, path_b = _file_a(tmp_path), _file_b(tmp_path)
    reused = _read(path_a)
    index_a = sequence_index(reused)
    levels_a = pns_levels_for(reused, hardware=_HARDWARE)
    spectrum_a = gradient_spectrum_for(reused)
    limits_a = gradient_peaks(reused)
    reused.read(str(path_b))
    fresh = _read(path_b)
    assert len(reused.block_events) == len(fresh.block_events) == len(index_a.block_id)

    expected_index = sequence_index(fresh)
    assert expected_index.end_s != index_a.end_s
    _assert_index_equal(sequence_index(reused), expected_index)
    levels = pns_levels_for(reused, hardware=_HARDWARE)
    assert levels == pns_levels_for(fresh, hardware=_HARDWARE)
    assert levels != levels_a
    spectrum = gradient_spectrum_for(reused)
    assert spectrum == gradient_spectrum_for(fresh)
    assert spectrum != spectrum_a
    limits = gradient_peaks(reused)
    assert limits == gradient_peaks(fresh)
    assert limits != limits_a


def test_pns_levels_for_gives_a_new_result_after_add_block_and_the_same_without_a_change():
    """Two calls with no change between them give one object. After `add_block` the
    result is a new object, and it is the result of a new sequence with the same blocks."""
    seq = spin_echo_sequence()
    first = pns_levels_for(seq, hardware=_HARDWARE)
    assert pns_levels_for(seq, hardware=_HARDWARE) is first

    seq.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    second = pns_levels_for(seq, hardware=_HARDWARE)
    assert second is not first
    assert pns_levels_for(seq, hardware=_HARDWARE) is second
    expected = spin_echo_sequence()
    expected.add_block(pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM))
    assert second == pns_levels_for(expected, hardware=_HARDWARE)


def test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result(
    write_gradient_asc, monkeypatch
):
    """`pns_levels_for` with `hardware_from_asc` of the relative path and with that of the
    absolute path of one `.asc` file gives one object, in both orders of the two calls."""
    path = write_gradient_asc()
    monkeypatch.chdir(path.parent)
    relative = hardware_from_asc(path.name)
    absolute = hardware_from_asc(path)
    for first, second in ((relative, absolute), (absolute, relative)):
        seq = spin_echo_sequence()
        result = pns_levels_for(seq, hardware=first)
        assert pns_levels_for(seq, hardware=second) is result


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
    `pns_levels_for` gives a new result, whose peak level is the double of the old one."""
    seq = spin_echo_sequence()
    first = pns_levels_for(seq, hardware=_HARDWARE)
    assert pns_levels_for(seq, hardware=_HARDWARE) is first
    library = copy.deepcopy(seq.grad_library)
    library.data = {k: (2 * v[0], *v[1:]) for k, v in library.data.items()}
    seq.grad_library = library

    second = pns_levels_for(seq, hardware=_HARDWARE)
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


def test_a_change_of_the_gradient_raster_time_gives_a_new_index_and_new_levels():
    """`seq.grad_raster_time` changes with the blocks the same: `sequence_index`,
    `pns_levels_for` and `gradient_spectrum_for` each give a new object, and a call with
    no change after it gives that object again."""
    seq = spin_echo_sequence()
    index = sequence_index(seq)
    levels = pns_levels_for(seq, hardware=_HARDWARE)
    spectrum = gradient_spectrum_for(seq)
    assert sequence_index(seq) is index
    assert pns_levels_for(seq, hardware=_HARDWARE) is levels
    assert gradient_spectrum_for(seq) is spectrum

    seq.grad_raster_time = seq.grad_raster_time / 2
    new_index = sequence_index(seq)
    new_levels = pns_levels_for(seq, hardware=_HARDWARE)
    new_spectrum = gradient_spectrum_for(seq)
    assert new_index is not index
    assert new_levels is not levels
    assert new_spectrum is not spectrum
    assert sequence_index(seq) is new_index
    assert pns_levels_for(seq, hardware=_HARDWARE) is new_levels
    assert gradient_spectrum_for(seq) is new_spectrum


@pytest.mark.parametrize(
    "keep",
    [
        sequence_index,
        lambda seq: pns_levels_for(seq, hardware=_HARDWARE),
        gradient_spectrum_for,
    ],
    ids=["sequence_index", "pns_levels_for", "gradient_spectrum_for"],
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
