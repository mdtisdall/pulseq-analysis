"""The block iteration that the oracles use, and the sequence that they read from a snapshot.

`iter_blocks` was `seq_utils.iter_blocks`. No library code calls it, so it lives with the tests.
It reads a `pp.Sequence`, or the stand-in that `sequence_of(snap)` makes of a snapshot.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import NamedTuple

import numpy as np
import pypulseq as pp

from pulseq_analysis.synth._played import played_gradients
from pulseq_analysis.synth.snapshot import Snapshot

# The gamma of 1H (Hz/T), the default of pypulseq's Opts: the stand-in's `system.gamma`.
_GAMMA_1H = 42.576e6


class BlockTiming(NamedTuple):
    block_id: int
    start_s: float  # sum of the durations of the blocks before this one
    duration_s: float
    block: SimpleNamespace  # from Sequence.get_block


def iter_blocks(seq: pp.Sequence) -> Iterator[BlockTiming]:
    """Each block of `seq` in play order, with its start time and duration (s).

    The start times are added in play order from 0.0, one block duration at a time,
    so they are equal to `t += seq.block_durations[block_id]` in a loop. The end of
    the sequence is `start_s + duration_s` of the last block.
    """
    start = 0.0
    for block_id in seq.block_events:
        duration = seq.block_durations[block_id]
        yield BlockTiming(int(block_id), start, duration, seq.get_block(block_id))
        start += duration


def _grad_event(points: tuple[float, np.ndarray, np.ndarray]) -> SimpleNamespace:
    """A pypulseq arbitrary gradient (`type` "grad") with the points of a played event: the
    first point is `first`, the last is `last`, and the others are `tt` and `waveform`."""
    delay, offsets, amp = points
    return SimpleNamespace(
        type="grad",
        delay=float(delay),
        tt=np.asarray(offsets[1:-1], dtype=float),
        waveform=np.asarray(amp[1:-1], dtype=float),
        first=float(amp[0]),
        last=float(amp[-1]),
        shape_dur=float(offsets[-1]),
    )


def sequence_of(snap: Snapshot) -> SimpleNamespace:
    """A stand-in of a `pp.Sequence` for the oracles, with the gradients of `snap` as the
    measurements play them (`_played.played_gradients`: the decoded events, and the events of a
    block that `gradients_at` gives): `block_events` (block ID -> the row: 0, rf, gx, gy, gz,
    adc, as keys of the played events), `block_durations` (block ID -> s), `grad_raster_time`,
    `system.gamma` (1H) and `get_block(block_id)` with `gx`, `gy` and `gz` as pypulseq
    arbitrary gradients (`_grad_event`), or None. The block IDs of `snap` must be unique."""
    data = snap.data
    played = played_gradients(snap)
    ids = [int(i) for i in data.blocks["id"]]
    assert len(set(ids)) == len(ids), "the oracles need unique block IDs"
    durations = data.block_durations_s
    columns = (played.gx, played.gy, played.gz)
    block_events = {}
    blocks = {}
    for play, block_id in enumerate(ids):
        keys = [int(column[play]) for column in columns]
        block_events[block_id] = (
            0,
            int(data.blocks["rf"][play]),
            *keys,
            int(data.blocks["adc"][play]),
        )
        blocks[block_id] = SimpleNamespace(
            **{
                axis: _grad_event(played.points[key]) if key else None
                for axis, key in zip(("gx", "gy", "gz"), keys, strict=True)
            }
        )
    return SimpleNamespace(
        block_events=block_events,
        block_durations={b: float(d) for b, d in zip(ids, durations, strict=True)},
        grad_raster_time=float(data.rasters.gradient),
        system=SimpleNamespace(gamma=_GAMMA_1H),
        get_block=blocks.__getitem__,
    )
