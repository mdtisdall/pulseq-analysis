"""Tests for `seq_index.py` (task 2.4, item 1, of `docs/plans/cards-at-scale.md`).

The reference, `_reference_index`, is a plain loop over the blocks that numbers the
unique RF, gradient and ADC events by their first use, with one dict for each kind: the
loop that `diagram_data.diagram_tables` had before it used the index. Its `*_first`
lists hold play indexes, as `SequenceIndex` does (the old loop kept block ids).
"""

import copy
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

from pulseq_analysis.seq_index import (
    adc_events,
    block_cache_off,
    grad_events,
    rf_events,
    sequence_index,
)

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


def _assert_index_matches_reference(seq: pp.Sequence) -> None:
    index = sequence_index(seq)
    ref = _reference_index(seq)
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
    seq = builder()
    _assert_index_matches_reference(seq)


def test_grad_dense_numbering_follows_gx_then_gy_then_gz_within_a_block():
    """Block 0: a gz trapezoid only (event e1). Block 1: a gx trapezoid (e2, a
    different amplitude) and a gy trapezoid (e3, a third amplitude). Block 2: reuses e1
    (the same trapezoid object, amplitude and all) on the gx channel.

    Worked out by hand: block 0 introduces only e1, on gz, so e1 gets dense index 1,
    first play index 0. Block 1 introduces e2 on gx before e3 on gy (gx before gy
    within one block, section 4.1 of the plan), so they get dense indexes 2 and 3, both
    with first play index 1. Block 2's gx event is e1 again (already dense 1), so it
    adds no new dense index."""
    seq = pp.Sequence(SYSTEM)
    common = {"rise_time": 1e-4, "flat_time": 2e-4, "fall_time": 1e-4, "system": SYSTEM}
    gz = pp.make_trapezoid(channel="z", amplitude=1e5, **common)
    gx = pp.make_trapezoid(channel="x", amplitude=2e5, **common)
    gy = pp.make_trapezoid(channel="y", amplitude=3e5, **common)
    seq.add_block(gz)
    seq.add_block(gx, gy)
    gz_as_gx = copy.copy(gz)
    gz_as_gx.channel = "x"
    seq.add_block(gz_as_gx)

    index = sequence_index(seq)
    assert index.gx.tolist() == [0, 2, 1]
    assert index.gy.tolist() == [0, 3, 0]
    assert index.gz.tolist() == [1, 0, 0]
    assert index.grad_first.tolist() == [0, 1, 1]
    assert index.grad_first_axis.tolist() == [2, 0, 1]  # gz, gx, gy

    events = list(grad_events(seq, index))
    assert [k for k, _ in events] == [1, 2, 3]
    assert events[0][1].amplitude == 1e5  # dense 1: the block-0 gz event
    assert events[1][1].amplitude == 2e5  # dense 2: the block-1 gx event
    assert events[2][1].amplitude == 3e5  # dense 3: the block-1 gy event


def test_start_s_is_the_sequential_sum_and_end_s_is_its_final_value():
    seq = build_repeating(50)
    index = sequence_index(seq)

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
    seq = gre_sequence()
    index = sequence_index(seq)
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
    seq = build_repeating(260)
    index = sequence_index(seq)
    assert index.grad_first.size > 255
    assert index.gx.dtype == np.uint16
    assert index.gy.dtype == np.uint16
    assert index.gz.dtype == np.uint16


def test_sequence_index_of_a_sequence_with_no_blocks():
    seq = pp.Sequence(SYSTEM)
    index = sequence_index(seq)
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


def test_sequence_index_is_kept_for_one_sequence_object_and_rebuilt_after_add_block():
    seq = gre_sequence()
    first = sequence_index(seq)
    second = sequence_index(seq)
    assert first is second

    seq.add_block(pp.make_delay(1e-3))
    third = sequence_index(seq)
    assert third is not first
    assert third.num_blocks == first.num_blocks + 1


def test_block_cache_off_restores_use_block_cache_true():
    seq = pp.Sequence(SYSTEM)
    seq.use_block_cache = True
    with block_cache_off(seq):
        assert seq.use_block_cache is False
    assert seq.use_block_cache is True


def test_block_cache_off_restores_use_block_cache_false():
    seq = pp.Sequence(SYSTEM)
    seq.use_block_cache = False
    with block_cache_off(seq):
        assert seq.use_block_cache is False
    assert seq.use_block_cache is False


def test_block_cache_off_restores_the_old_value_after_an_exception():
    seq = pp.Sequence(SYSTEM)
    seq.use_block_cache = True
    with pytest.raises(ValueError, match="boom"), block_cache_off(seq):
        assert seq.use_block_cache is False
        raise ValueError("boom")
    assert seq.use_block_cache is True


def test_block_cache_off_does_not_remove_blocks_already_in_the_cache():
    seq = gre_sequence()
    first_block_id = next(iter(seq.block_events))
    seq.get_block(first_block_id)  # populates seq.block_cache with this one block
    assert first_block_id in seq.block_cache
    with block_cache_off(seq):
        pass
    assert first_block_id in seq.block_cache


def _wrap_get_block(seq, monkeypatch):
    """Replace `seq.get_block` with a counting wrapper that also records
    `seq.use_block_cache` at each call, and return `(original, calls, cache_flags)`."""
    original = seq.get_block
    calls: list[int] = []
    cache_flags: list[bool] = []

    def wrapper(block_id):
        calls.append(block_id)
        cache_flags.append(seq.use_block_cache)
        return original(block_id)

    monkeypatch.setattr(seq, "get_block", wrapper)
    return original, calls, cache_flags


def test_rf_events_reads_each_unique_event_once_with_the_cache_off(monkeypatch):
    seq = spin_echo_sequence()  # two distinct RF events: excitation and refocusing
    index = sequence_index(seq)
    assert index.rf_first.size == 2
    seq.use_block_cache = True
    original, calls, cache_flags = _wrap_get_block(seq, monkeypatch)

    results = list(rf_events(seq, index))

    # One RF event per block, so the number of get_block calls is exactly the number
    # of unique RF events here.
    assert len(calls) == np.unique(index.rf_first).size
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert seq.use_block_cache is True

    assert [k for k, _ in results] == list(range(1, index.rf_first.size + 1))
    for (_, ev), play_index in zip(results, index.rf_first.tolist()):
        block_id = int(index.block_id[play_index])
        expected = original(block_id).rf
        assert ev.delay == expected.delay
        assert ev.type == expected.type
        assert np.array_equal(ev.signal, expected.signal)


def test_grad_events_reads_each_unique_first_use_block_once_with_the_cache_off(
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
    index = sequence_index(seq)
    assert index.grad_first.tolist() == [0, 1, 1]
    seq.use_block_cache = True
    original, calls, cache_flags = _wrap_get_block(seq, monkeypatch)

    results = list(grad_events(seq, index))

    assert len(calls) == np.unique(index.grad_first).size == 2
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert seq.use_block_cache is True

    assert [k for k, _ in results] == [1, 2, 3]
    for (_, ev), play_index, axis in zip(
        results, index.grad_first.tolist(), index.grad_first_axis.tolist()
    ):
        block_id = int(index.block_id[play_index])
        expected = getattr(original(block_id), _AXES[axis])
        assert ev.delay == expected.delay
        assert ev.type == expected.type
        assert ev.amplitude == expected.amplitude


def test_adc_events_reads_each_unique_event_once_with_the_cache_off(monkeypatch):
    seq = gre_sequence(num_trs=5)  # the same ADC event is reused every TR
    index = sequence_index(seq)
    assert index.adc_first.size == 1
    seq.use_block_cache = True
    original, calls, cache_flags = _wrap_get_block(seq, monkeypatch)

    results = list(adc_events(seq, index))

    assert len(calls) == np.unique(index.adc_first).size == 1
    assert cache_flags and all(flag is False for flag in cache_flags)
    assert seq.use_block_cache is True

    assert [k for k, _ in results] == [1]
    for (_, ev), play_index in zip(results, index.adc_first.tolist()):
        block_id = int(index.block_id[play_index])
        expected = original(block_id).adc
        assert ev.delay == expected.delay
        assert ev.num_samples == expected.num_samples
        assert ev.dwell == expected.dwell
