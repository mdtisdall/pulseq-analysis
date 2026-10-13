"""Tests for `seq_index.py`.

The reference, `_reference_index`, is a plain loop over the blocks that numbers the
unique RF, gradient and ADC events by their first use, with one dict for each kind: the
loop that `diagram_data.diagram_tables` had before it used the index. Its `*_first`
lists hold play indexes, as `SequenceIndex` does (the old loop kept block ids).
"""

import copy
import dataclasses
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pypulseq as pp
import pytest
from scale_sequences import build_repeating, build_worst
from synthetic import (
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis import seqfile
from pulseq_analysis._equality import _freeze, values_equal
from pulseq_analysis.seqfile import NotSupported, SeqFileError
from pulseq_analysis.seqfile.model import TABLE_DTYPES
from pulseq_analysis.synth import seq_index
from pulseq_analysis.synth.seq_index import (
    adc_events,
    grad_events,
    has_gradients,
    rf_events,
    sequence_index,
)
from pulseq_analysis.synth.snapshot import Snapshot, load

_AXES = ("gx", "gy", "gz")


def _reference_index(seq: pp.Sequence) -> SimpleNamespace:
    """The dense event numbering of `seq`, by the same one-dict-per-kind, first-use
    technique as the pre-phase-2 `diagram_tables` loop, read directly from
    `seq.block_events` (never from `seq_index.py`)."""
    block_events = seq.block_events
    n = len(block_events)
    block_id = np.fromiter(block_events.keys(), dtype=np.uint32, count=n)

    rf = np.zeros(n, dtype=np.int64)
    gx = np.zeros(n, dtype=np.int64)
    gy = np.zeros(n, dtype=np.int64)
    gz = np.zeros(n, dtype=np.int64)
    adc = np.zeros(n, dtype=np.int64)
    grad_cols = ((gx, 0), (gy, 1), (gz, 2))  # gx before gy before gz in one block

    rf_map: dict[int, int] = {}
    rf_first: list[int] = []
    grad_map: dict[int, int] = {}
    grad_first: list[int] = []
    grad_first_axis: list[int] = []
    adc_map: dict[int, int] = {}
    adc_first: list[int] = []

    for i, bid in enumerate(block_id.tolist()):
        ev = block_events[bid]

        rf_id = int(ev[1])
        if rf_id:
            dense = rf_map.get(rf_id)
            if dense is None:
                dense = len(rf_map) + 1
                rf_map[rf_id] = dense
                rf_first.append(i)
            rf[i] = dense

        for col, (arr, axis) in zip((2, 3, 4), grad_cols):
            gid = int(ev[col])
            if gid:
                dense = grad_map.get(gid)
                if dense is None:
                    dense = len(grad_map) + 1
                    grad_map[gid] = dense
                    grad_first.append(i)
                    grad_first_axis.append(axis)
                arr[i] = dense

        adc_id = int(ev[5])
        if adc_id:
            dense = adc_map.get(adc_id)
            if dense is None:
                dense = len(adc_map) + 1
                adc_map[adc_id] = dense
                adc_first.append(i)
            adc[i] = dense

    return SimpleNamespace(
        block_id=block_id,
        rf=rf,
        gx=gx,
        gy=gy,
        gz=gz,
        adc=adc,
        rf_first=np.array(rf_first, dtype=np.int64),
        grad_first=np.array(grad_first, dtype=np.int64),
        grad_first_axis=np.array(grad_first_axis, dtype=np.uint8),
        adc_first=np.array(adc_first, dtype=np.int64),
    )


def _assert_index_matches_reference(snap: Snapshot) -> None:
    index = sequence_index(snap)
    ref = _reference_index(snap.sequence)
    assert np.array_equal(index.block_id, ref.block_id)
    assert np.array_equal(index.rf.astype(np.int64), ref.rf)
    assert np.array_equal(index.gx.astype(np.int64), ref.gx)
    assert np.array_equal(index.gy.astype(np.int64), ref.gy)
    assert np.array_equal(index.gz.astype(np.int64), ref.gz)
    assert np.array_equal(index.adc.astype(np.int64), ref.adc)
    assert np.array_equal(index.rf_first, ref.rf_first)
    assert np.array_equal(index.grad_first, ref.grad_first)
    assert np.array_equal(index.grad_first_axis, ref.grad_first_axis)
    assert np.array_equal(index.adc_first, ref.adc_first)


@pytest.mark.parametrize(
    "builder",
    [
        spin_echo_sequence,
        gre_sequence,
        empty_sequence,
        arbitrary_gradient_sequence,
        lambda: build_repeating(50),
        lambda: build_worst(50),
    ],
    ids=[
        "spin_echo",
        "gre",
        "empty",
        "arbitrary_gradient",
        "build_repeating_50",
        "build_worst_50",
    ],
)
def test_dense_columns_and_first_arrays_match_the_reference_numbering(builder):
    """`sequence_index`'s `rf`/`gx`/`gy`/`gz`/`adc` columns, `rf_first`, `grad_first`,
    `grad_first_axis`, `adc_first` and `block_id` equal `_reference_index`'s, for each
    synthetic sequence and for `build_repeating`/`build_worst` at 50 TRs (250 blocks)."""
    _assert_index_matches_reference(load(builder()))


def test_dense_numbering_follows_the_first_use_and_not_the_order_in_the_libraries():
    """The RF, gradient and ADC events are registered in the libraries in the reverse of the
    order of their first use, so the library ids are 2, 1 for the two RF events, 3, 2, 1 for
    the three gradient events and 2, 1 for the two ADC events. The dense numbers are in the
    order of first use: 1, 2 (RF), 1, 2, 3 (gradient) and 1, 2 (ADC).

    Block 0: RF e1, a gz trapezoid g1 and ADC a1. Block 1: RF e2, a gx trapezoid g2, a gy
    trapezoid g3 (gx before gy in one block) and ADC a2. Block 2: e1, g1 on gx and a1 again.
    Worked out by hand: g1 is first used in block 0, g2 and g3 in block 1, so g1 has the dense
    number 1, g2 has 2 and g3 has 3."""
    common = {"rise_time": 1e-4, "flat_time": 2e-4, "fall_time": 1e-4, "system": SYSTEM}
    g1 = pp.make_trapezoid(channel="z", amplitude=1e5, **common)
    g2 = pp.make_trapezoid(channel="x", amplitude=2e5, **common)
    g3 = pp.make_trapezoid(channel="y", amplitude=3e5, **common)
    g1_as_gx = copy.copy(g1)
    g1_as_gx.channel = "x"
    rf = {"duration": 1e-3, "delay": SYSTEM.rf_dead_time, "system": SYSTEM}
    e1 = pp.make_block_pulse(flip_angle=np.pi / 2, use="excitation", **rf)
    e2 = pp.make_block_pulse(flip_angle=np.pi, use="refocusing", **rf)
    adc = {"dwell": 20e-6, "delay": SYSTEM.adc_dead_time, "system": SYSTEM}
    a1 = pp.make_adc(num_samples=16, **adc)
    a2 = pp.make_adc(num_samples=32, **adc)
    seq = pp.Sequence(SYSTEM)
    for g in (g3, g2, g1):
        seq.register_grad_event(g)
    seq.register_rf_event(e2)
    seq.register_rf_event(e1)
    seq.register_adc_event(a2)
    seq.register_adc_event(a1)
    seq.add_block(e1, g1, a1)
    seq.add_block(e2, g2, g3, a2)
    seq.add_block(e1, g1_as_gx, a1)
    snap = load(seq)
    ids = np.array(list(snap.sequence.block_events.values()))
    assert ids[:, 1].tolist() == [2, 1, 2]  # RF library ids
    assert ids[:, 2].tolist() == [0, 2, 3]  # gx
    assert ids[:, 3].tolist() == [0, 1, 0]  # gy
    assert ids[:, 4].tolist() == [3, 0, 0]  # gz
    assert ids[:, 5].tolist() == [2, 1, 2]  # ADC library ids
    assert len(snap.sequence.grad_library.data) == 3

    index = sequence_index(snap)

    assert index.rf.tolist() == [1, 2, 1]
    assert index.rf_first.tolist() == [0, 1]
    assert index.gx.tolist() == [0, 2, 1]
    assert index.gy.tolist() == [0, 3, 0]
    assert index.gz.tolist() == [1, 0, 0]
    assert index.grad_first.tolist() == [0, 1, 1]
    assert index.grad_first_axis.tolist() == [2, 0, 1]  # gz, gx, gy
    assert index.adc.tolist() == [1, 2, 1]
    assert index.adc_first.tolist() == [0, 1]
    _assert_index_matches_reference(snap)
    assert [ev.amplitude for _, ev in grad_events(snap)] == [1e5, 2e5, 3e5]


def test_start_s_is_the_sequential_sum_and_end_s_is_its_final_value():
    snap = load(build_repeating(50))
    seq = snap.sequence
    index = sequence_index(snap)

    block_ids = list(seq.block_events.keys())
    t = 0.0
    starts = []
    for bid in block_ids:
        starts.append(t)
        t += seq.block_durations[bid]

    assert np.array_equal(index.start_s, np.array(starts, dtype=np.float64))
    assert index.end_s == t
    assert np.array_equal(
        index.duration_s,
        np.array([seq.block_durations[bid] for bid in block_ids], dtype=np.float64),
    )


def test_dtype_is_uint8_for_a_sequence_with_few_unique_events():
    index = sequence_index(load(gre_sequence()))
    assert index.rf_first.size <= 255
    assert index.grad_first.size <= 255
    assert index.adc_first.size <= 255
    assert index.rf.dtype == np.uint8
    assert index.gx.dtype == np.uint8
    assert index.gy.dtype == np.uint8
    assert index.gz.dtype == np.uint8
    assert index.adc.dtype == np.uint8


def test_dtype_widens_to_uint16_past_255_unique_gradient_events():
    """`build_repeating`'s phase-encode table alone has 256 amplitudes (`PE_STEPS`), so
    260 TRs give more than 255 unique gradient events (the phase-encode events, plus
    the readout and the spoiler, each reused every TR), past the uint8 range."""
    index = sequence_index(load(build_repeating(260)))
    assert index.grad_first.size > 255
    assert index.gx.dtype == np.uint16
    assert index.gy.dtype == np.uint16
    assert index.gz.dtype == np.uint16


@pytest.mark.parametrize(
    ("unique", "dtype"),
    [
        (255, np.uint8),
        (256, np.uint16),
        (65_535, np.uint16),
        (65_536, np.uint32),
    ],
)
def test_the_dtype_of_the_dense_columns_changes_at_255_and_at_65_535_unique_events(unique, dtype):
    """The dense columns hold the numbers 1 to K, so the dtype is the smallest of uint8, uint16
    and uint32 that holds K: uint8 for K = 255, uint16 for 256 and for 65 535, and uint32 for
    65 536. This calls the private `_dense` with the event ids 1 to K, because a sequence of
    65 535 unique events is slow to build. The next test does 255 and 256 through
    `sequence_index`."""
    (dense,), first_use = seq_index._dense([np.arange(1, unique + 1, dtype=np.int32)])
    assert dense.dtype == dtype
    assert first_use.size == unique
    assert dense[0] == 1
    assert dense[-1] == unique


@pytest.mark.parametrize(("unique", "dtype"), [(255, np.uint8), (256, np.uint16)])
def test_the_dtype_of_the_index_changes_at_255_unique_events(unique, dtype):
    """A sequence with K different trapezoids on x (K unique gradient events): the index has
    K unique gradient events and its gradient columns are uint8 for K = 255 and uint16 for
    256."""
    seq = pp.Sequence(SYSTEM)
    for k in range(1, unique + 1):
        seq.add_block(
            pp.make_trapezoid(channel="x", amplitude=100.0 * k, duration=1e-3, system=SYSTEM)
        )

    index = sequence_index(load(seq))

    assert index.grad_first.size == unique
    assert index.gx.dtype == dtype
    assert index.gy.dtype == dtype
    assert index.gz.dtype == dtype
    assert index.gx[-1] == unique


def test_an_event_id_of_1e8_builds_the_index_in_less_than_100_mb():
    """A file with a large event ID must not make a table in proportion to the ID. pypulseq
    gives the IDs 1, 2, ... in order, so this sets the gx ID of the second block in
    `seq.block_events` to 10**8 after `add_block`, before `load` (`sequence_index` reads only
    `seq.block_events` and `seq.block_durations`, not the libraries). The peak of
    `tracemalloc` over the build is below 100 MB, and the dense numbers are as for small IDs.
    A lookup table over the IDs takes 800 MB."""
    seq = pp.Sequence(SYSTEM)
    for amplitude in (1e5, 2e5, 1e5):
        seq.add_block(
            pp.make_trapezoid(channel="x", amplitude=amplitude, duration=1e-3, system=SYSTEM)
        )
    big = 10**8
    seq.block_events[2][seq_index._GX] = big
    snap = load(seq)

    tracemalloc.start()
    try:
        index = sequence_index(snap)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 100e6
    assert index.gx.tolist() == [1, 2, 1]
    assert index.grad_first.tolist() == [0, 1]


@pytest.mark.parametrize("build", [gre_sequence, empty_sequence])
def test_the_arrays_of_the_index_are_read_only_and_a_copy_is_writable(build):
    index = sequence_index(load(build()))
    arrays = [
        getattr(index, f.name)
        for f in dataclasses.fields(index)
        if isinstance(getattr(index, f.name), np.ndarray)
    ]
    assert len(arrays) == 12
    for array in arrays:
        assert not array.flags.writeable
        if array.size:
            with pytest.raises(ValueError):
                array[0] = array[0]
        copied = np.array(array)
        assert copied.flags.writeable
        if copied.size:
            copied[0] = copied[0]


def test_two_indexes_of_two_equal_sequences_are_equal_and_not_hashable():
    first = sequence_index(load(gre_sequence()))
    second = sequence_index(load(gre_sequence()))
    assert first is not second
    assert first == second
    assert first != sequence_index(load(gre_sequence(num_trs=5)))
    assert first != sequence_index(load(spin_echo_sequence()))
    with pytest.raises(TypeError):
        hash(first)


def _one_trapezoid(channel: str) -> pp.Sequence:
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel=channel, area=1000, system=SYSTEM))
    return seq


def _delay_only() -> pp.Sequence:
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(1e-3))
    return seq


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (spin_echo_sequence, True),
        (lambda: _one_trapezoid("x"), True),
        (lambda: _one_trapezoid("y"), True),
        (lambda: _one_trapezoid("z"), True),
        (_delay_only, False),
        (lambda: pp.Sequence(SYSTEM), False),
    ],
    ids=["spin echo", "x", "y", "z", "delay only", "no blocks"],
)
def test_has_gradients_is_true_only_for_an_index_with_a_gradient_event(build, expected):
    assert has_gradients(sequence_index(load(build()))) is expected


def test_sequence_index_of_a_sequence_with_no_blocks():
    index = sequence_index(load(pp.Sequence(SYSTEM)))
    assert index.num_blocks == 0
    assert index.end_s == 0.0
    for arr in (
        index.block_id,
        index.start_s,
        index.duration_s,
        index.rf,
        index.gx,
        index.gy,
        index.gz,
        index.adc,
        index.rf_first,
        index.grad_first,
        index.grad_first_axis,
        index.adc_first,
    ):
        assert arr.size == 0


def test_sequence_index_is_kept_for_one_snapshot_and_made_again_for_another():
    """Two calls of `sequence_index` with one snapshot give the same object. A second snapshot
    of the same sequence gives its own, equal index."""
    seq = gre_sequence()
    snap = load(seq)
    first = sequence_index(snap)
    assert sequence_index(snap) is first

    other = sequence_index(load(seq))
    assert other is not first
    assert other == first


def _count_get_block(snap, monkeypatch):
    """Replace `get_block` of the sequence of `snap` with a counting wrapper that also records
    `use_block_cache` at each call, and return `(original, calls, cache_flags)`."""
    seq = snap.sequence
    original = seq.get_block
    calls: list[int] = []
    cache_flags: list[bool] = []

    def wrapper(block_id):
        calls.append(block_id)
        cache_flags.append(seq.use_block_cache)
        return original(block_id)

    monkeypatch.setattr(seq, "get_block", wrapper)
    return original, calls, cache_flags


def test_rf_events_reads_each_unique_event_once_and_keeps_the_tuple(monkeypatch):
    snap = load(spin_echo_sequence())  # two distinct RF events: excitation and refocusing
    index = sequence_index(snap)
    assert index.rf_first.size == 2
    original, calls, cache_flags = _count_get_block(snap, monkeypatch)

    results = rf_events(snap)

    assert isinstance(results, tuple)
    # One RF event per block, so the number of get_block calls is exactly the number
    # of unique RF events here.
    assert len(calls) == np.unique(index.rf_first).size
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert snap.sequence.use_block_cache is False

    assert [k for k, _ in results] == list(range(1, index.rf_first.size + 1))
    for (_, ev), play_index in zip(results, index.rf_first.tolist()):
        block_id = int(index.block_id[play_index])
        expected = original(block_id).rf
        assert ev.delay == expected.delay
        assert ev.type == expected.type
        assert np.array_equal(ev.signal, expected.signal)

    calls.clear()
    assert rf_events(snap) is results
    assert not calls


def test_grad_events_reads_each_unique_first_use_block_once_and_keeps_the_tuple(
    monkeypatch,
):
    seq = pp.Sequence(SYSTEM)
    common = {"rise_time": 1e-4, "flat_time": 2e-4, "fall_time": 1e-4, "system": SYSTEM}
    seq.add_block(pp.make_trapezoid(channel="z", amplitude=1e5, **common))
    # gx and gy are both first used in this second block: one get_block call, not two.
    seq.add_block(
        pp.make_trapezoid(channel="x", amplitude=2e5, **common),
        pp.make_trapezoid(channel="y", amplitude=3e5, **common),
    )
    snap = load(seq)
    index = sequence_index(snap)
    assert index.grad_first.tolist() == [0, 1, 1]
    original, calls, cache_flags = _count_get_block(snap, monkeypatch)

    results = grad_events(snap)

    assert isinstance(results, tuple)
    assert len(calls) == np.unique(index.grad_first).size == 2
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert snap.sequence.use_block_cache is False

    assert [k for k, _ in results] == [1, 2, 3]
    for (_, ev), play_index, axis in zip(
        results, index.grad_first.tolist(), index.grad_first_axis.tolist()
    ):
        block_id = int(index.block_id[play_index])
        expected = getattr(original(block_id), _AXES[axis])
        assert ev.delay == expected.delay
        assert ev.type == expected.type
        assert ev.amplitude == expected.amplitude

    calls.clear()
    assert grad_events(snap) is results
    assert not calls


def test_adc_events_reads_each_unique_event_once_and_keeps_the_tuple(monkeypatch):
    snap = load(gre_sequence(num_trs=5))  # the same ADC event is reused every TR
    index = sequence_index(snap)
    assert index.adc_first.size == 1
    original, calls, cache_flags = _count_get_block(snap, monkeypatch)

    results = adc_events(snap)

    assert isinstance(results, tuple)
    assert len(calls) == np.unique(index.adc_first).size == 1
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert snap.sequence.use_block_cache is False

    assert [k for k, _ in results] == [1]
    for (_, ev), play_index in zip(results, index.adc_first.tolist()):
        block_id = int(index.block_id[play_index])
        expected = original(block_id).adc
        assert ev.delay == expected.delay
        assert ev.num_samples == expected.num_samples
        assert ev.dwell == expected.dwell

    calls.clear()
    assert adc_events(snap) is results
    assert not calls


@pytest.mark.parametrize("function", [sequence_index, rf_events, grad_events, adc_events])
@pytest.mark.parametrize("build", [gre_sequence, lambda: "sequence.seq"], ids=["sequence", "path"])
def test_a_function_of_the_index_raises_type_error_that_names_load_for_a_non_snapshot(
    function, build
):
    """`sequence_index`, `rf_events`, `grad_events` and `adc_events` raise `TypeError` that
    names `load` for a `pp.Sequence` and for a path: they take a `Snapshot`."""
    with pytest.raises(TypeError, match="load"):
        function(build())


# ---- The index from parts: `_index_from_columns`, `_index_from_data` and `_dense_ids` ----

SEQFILES = Path(__file__).resolve().parent / "seqfiles"


def _seqfiles() -> list[Path]:
    """The valid fixtures and the oracle files of `tests/seqfiles`."""
    return sorted(SEQFILES.glob("valid_*.seq")) + sorted((SEQFILES / "oracle").glob("*.seq"))


# The fields of the gradient numbering. pypulseq's `Sequence.read` (in `load`) calls
# `remove_duplicates`, which makes one event of the gradient events of the file that are equal
# after its rounding: `pypulseq_simple_mprage150.seq` has the trapezoids 39 and 40, with the
# amplitudes 0 and -0 and the same times, and pypulseq gives the gy of its blocks 70, 200 and
# 330 the ID 39, not 40. The model keeps the IDs of the file, so the index of the model can
# have more gradient events.
_GRAD_FIELDS = ("gx", "gy", "gz", "grad_first", "grad_first_axis")


def _gradient_row(data, file_id: int) -> tuple:
    """The gradient event `file_id` of `data`: its table, and its row without the ID."""
    for name in ("trap", "grad"):
        table = getattr(data, name)
        row = table[table["id"] == file_id]
        if row.size:
            return (name, *row[0].tolist()[1:])
    raise AssertionError(f"no gradient event {file_id}")


def _assert_gradients_are_merged(data, got, expected) -> None:
    """The gradient columns of `expected` (pypulseq) number the events of `got` (the model)
    with the events that are equal by value as one: each dense index of `got` has one dense
    index of `expected` on every axis, and the events of the file that get one index of
    `expected` are equal by value (`==`, so 0 equals -0). pypulseq merges events that are
    equal after its rounding, so a file with two events that differ by less than that rounding
    fails here, and shows it."""
    mine = np.concatenate([got.gx, got.gy, got.gz]).astype(np.int64)
    theirs = np.concatenate([expected.gx, expected.gy, expected.gz]).astype(np.int64)
    to = np.zeros(got.grad_first.size + 1, dtype=np.int64)
    to[mine] = theirs
    assert np.array_equal(to[mine], theirs)
    ids = seq_index._dense_ids(data, got).grad
    for j in range(1, expected.grad_first.size + 1):
        rows = {_gradient_row(data, int(i)) for i in ids[to[1:] == j]}
        assert len(rows) == 1, (j, rows)


def test_the_index_of_a_model_equals_the_index_of_pypulseq_for_each_file():
    """For each file of `tests/seqfiles` that both `seqfile.read_seqfile` and `load` accept,
    `_index_from_data` of the model equals `sequence_index` of the snapshot, field by field,
    except the gradient numbering where pypulseq makes one event of two that are equal by
    value (`_GRAD_FIELDS`): there the numbering of pypulseq is a merging of the numbering of
    the model."""
    compared = merged = 0
    for path in _seqfiles():
        try:
            data = seqfile.read_seqfile(path)
        except (SeqFileError, NotSupported):
            continue
        try:
            snap = load(path)
        except (KeyError, ValueError, NotImplementedError):  # pypulseq refuses the file
            continue
        got, expected = seq_index._index_from_data(data), sequence_index(snap)
        if got.grad_first.size == expected.grad_first.size:
            names = [f.name for f in dataclasses.fields(got)]
        else:
            _assert_gradients_are_merged(data, got, expected)
            names = [f.name for f in dataclasses.fields(got) if f.name not in _GRAD_FIELDS]
            merged += 1
        different = [
            name for name in names if not values_equal(getattr(got, name), getattr(expected, name))
        ]
        assert not different, (path.name, different)
        compared += 1
    assert compared - merged >= 10


@pytest.mark.parametrize(
    "build",
    [spin_echo_sequence, gre_sequence, empty_sequence, arbitrary_gradient_sequence],
    ids=["spin_echo", "gre", "empty", "arbitrary_gradient"],
)
def test_the_index_from_the_columns_of_a_sequence_equals_its_index(build):
    """`_index_from_columns` with the block IDs, the durations and the event columns of the
    sequence of a snapshot (int64, read here) equals `sequence_index` of the snapshot."""
    snap = load(build())
    seq = snap.sequence
    rows = list(seq.block_events.items())
    block_id = np.array([b for b, _ in rows], dtype=np.uint32)
    duration_s = np.array([seq.block_durations[b] for b, _ in rows], dtype=np.float64)
    columns = [np.array([ev[c] for _, ev in rows], dtype=np.int64) for c in range(1, 6)]
    index = seq_index._index_from_columns(block_id, duration_s, *columns)
    assert index == sequence_index(snap)


def _hand_blocks() -> np.ndarray:
    """A block table by hand (`id`, `duration_ticks`, `rf`, `gx`, `gy`, `gz`, `adc`, `ext`) whose
    event IDs are not in the order of their first use."""
    rows = [
        (1, 10, 3, 0, 0, 5, 0, 0),
        (2, 10, 0, 2, 5, 0, 4, 0),
        (3, 10, 3, 0, 0, 0, 0, 0),
        (4, 10, 1, 7, 0, 2, 4, 0),
        (5, 10, 0, 0, 0, 0, 2, 0),
    ]
    return np.array(rows, dtype=TABLE_DTYPES["blocks"])


def test_dense_ids_are_the_file_ids_of_the_first_use_by_hand():
    """`_dense_ids` of a model of `valid_1_5_1.seq` with the block table of `_hand_blocks`:
    RF 3 then 1 (blocks 1 and 4), gradients 5 (gz of block 1), 2 (gx of block 2; its gy 5 is
    used already) and 7 (gx of block 4), ADC 4 then 2 (blocks 2 and 5)."""
    data = dataclasses.replace(
        seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"), blocks=_hand_blocks()
    )
    index = seq_index._index_from_data(data)
    ids = seq_index._dense_ids(data, index)
    assert ids.rf.tolist() == [3, 1]
    assert ids.grad.tolist() == [5, 2, 7]
    assert ids.adc.tolist() == [4, 2]
    for array in ids:
        assert array.dtype == np.int64
    assert index.gx.tolist() == [0, 2, 0, 3, 0]
    assert index.gy.tolist() == [0, 1, 0, 0, 0]
    assert index.gz.tolist() == [1, 0, 0, 2, 0]


def test_a_block_id_that_does_not_fit_in_uint32_raises_value_error_that_names_it():
    """A model with the block ID 2**32 raises ValueError that names the ID. The ID 2**32 - 1
    builds the index, as uint32."""
    data = seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq")
    blocks = np.array(data.blocks)
    blocks["id"][-1] = 2**32 - 1
    index = seq_index._index_from_data(dataclasses.replace(data, blocks=_freeze(blocks)[0]))
    assert index.block_id.dtype == np.uint32
    assert int(index.block_id[-1]) == 2**32 - 1
    blocks["id"][-1] = 2**32
    with pytest.raises(ValueError, match=str(2**32)):
        seq_index._index_from_data(dataclasses.replace(data, blocks=_freeze(blocks)[0]))
