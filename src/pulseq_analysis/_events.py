"""The points of the unique gradient events of one sequence, read one time.

`event_points` reads each unique gradient event of a sequence one time, with one
`get_block` call for each event (`seq_index.grad_events`), and keeps the result for the
sequence object. `sampling.GradientSampler` and `grad_peaks._event_values` both build
their data from it, so the measurements of one sequence read each event one time, and
hold one copy of its points.

The points of the K unique events are in two pools, event by event, in the dense order
of `seq_index`. Event `k` (0-based) has its points at `offsets[at[k] : at[k] + count[k]]`
and `amp[at[k] : at[k] + count[k]]`, and the times of its points from the start of the
block that plays it are `delay[k] + offsets[...]`. The values are those of
`seq_utils.gradient_offsets`. `grad_raster_time` is the gradient raster of the sequence.

All the arrays are read-only: all callers share the kept result. The rule that makes the
kept result old is the one of `_kept`.
"""

import weakref
from dataclasses import dataclass

import numpy as np
import pypulseq as pp

from ._kept import _Entry, kept_results
from .seq_index import grad_events, sequence_index
from .seq_utils import gradient_offsets


@dataclass(frozen=True, eq=False)
class EventPoints:
    """The points of the K unique gradient events of one sequence."""

    delay: np.ndarray  # float64, K: the delay of each event
    count: np.ndarray  # int64, K: the number of points of each event
    at: np.ndarray  # int64, K: the start of the points of each event in `offsets` and `amp`
    offsets: np.ndarray  # float64: the offsets of all the points, event by event (s)
    amp: np.ndarray  # float64: the amplitudes of all the points, event by event (Hz/m)
    # The gradient raster of the sequence (s), `seq.grad_raster_time`. The gap rule of
    # `sampling` needs it, and the kept result is read again when it changes (`_kept`).
    grad_raster_time: float


# One `EventPoints` for each sequence object, under the key "points" of its kept results.
_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


def event_points(seq: pp.Sequence) -> EventPoints:
    """The `EventPoints` of `seq`.

    The result is kept for the sequence object, so that several measurements of one
    sequence read each unique gradient event one time. It is read again after the changes
    that make the kept index old (the rule of `_kept`).
    """
    kept = kept_results(_CACHE, seq)
    if "points" not in kept:
        kept["points"] = _read_points(seq)
    return kept["points"]


def _read_points(seq: pp.Sequence) -> EventPoints:
    """The `EventPoints` of `seq`, read without the cache of `event_points`."""
    delays: list[float] = []
    counts: list[int] = []
    offset_chunks: list[np.ndarray] = []
    amp_chunks: list[np.ndarray] = []
    for number, g in grad_events(seq, sequence_index(seq)):
        delay, offsets, amp = gradient_offsets(g)
        offsets = np.asarray(offsets, dtype=np.float64)
        amp = np.asarray(amp, dtype=np.float64)
        # `sampling` relies on this: no code there handles an event with no point.
        assert offsets.size >= 2, f"gradient event {number} has {offsets.size} points"
        delays.append(float(delay))
        counts.append(offsets.size)
        offset_chunks.append(offsets)
        amp_chunks.append(amp)

    count = np.asarray(counts, dtype=np.int64)
    arrays = (
        np.asarray(delays, dtype=np.float64),
        count,
        # The exclusive prefix sum: the start of the points of each event in the pools.
        np.cumsum(count, dtype=np.int64) - count,
        np.concatenate(offset_chunks) if offset_chunks else np.empty(0, dtype=np.float64),
        np.concatenate(amp_chunks) if amp_chunks else np.empty(0, dtype=np.float64),
    )
    for array in arrays:
        array.flags.writeable = False  # shared by all callers through the kept result
    return EventPoints(*arrays, grad_raster_time=float(seq.grad_raster_time))
