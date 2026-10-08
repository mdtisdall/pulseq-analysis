"""The points of the unique gradient events of one sequence, read one time, and the gap rule.

`event_points` reads each unique gradient event of a snapshot one time, with one
`get_block` call for each event (`seq_index.grad_events`), and keeps the result on the
snapshot. `sampling.GradientSampler` and `grad_peaks._event_values` both build
their data from it, so the measurements of one snapshot read each event one time, and
hold one copy of its points.

The points of the K unique events are in two pools, event by event, in the dense order
of `seq_index`. Event `k` (0-based) has its points at `offsets[at[k] : at[k] + count[k]]`
and `amp[at[k] : at[k] + count[k]]`, and the times of its points from the start of the
block that plays it are `delay[k] + offsets[...]`. The values are those of
`seq_utils.gradient_offsets`. `grad_raster_time` is the gradient raster of the sequence.

All the arrays are read-only (`_equality._freeze`): all callers share the kept result.

The gap rule of the waveform is here too, so that `grad_peaks` and `sampling` use one copy
of it (`docs/implementation.md`, "The gradient waveform"). `axis_events` gives the first and
the last point of each event of an axis, `gap_kinds` sorts the gaps between them into zero,
short and long, `ramps` says which events have a ramp across a long gap and where its point
is, and `polyline` gives the points of a run of events with the ramp points. The times are
`(block start + delay) + offset`, and each ramp point is `dt / 2` from the end that it belongs
to.
"""

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from ._equality import _freeze
from .seq_index import SequenceIndex, grad_events
from .seq_utils import TIME_TOLERANCE, gradient_offsets
from .snapshot import Snapshot, _check_snapshot, _kept_results


@dataclass(frozen=True, eq=False)
class EventPoints:
    """The points of the K unique gradient events of one sequence."""

    delay: np.ndarray  # float64, K: the delay of each event
    count: np.ndarray  # int64, K: the number of points of each event
    at: np.ndarray  # int64, K: the start of the points of each event in `offsets` and `amp`
    offsets: np.ndarray  # float64: the offsets of all the points, event by event (s)
    amp: np.ndarray  # float64: the amplitudes of all the points, event by event (Hz/m)
    # The gradient raster of the sequence (s), `seq.grad_raster_time`. The gap rule of
    # `sampling` needs it.
    grad_raster_time: float


def event_points(snap: Snapshot) -> EventPoints:
    """The `EventPoints` of `snap`.

    The result is made on the first call and kept on the snapshot, so that several
    measurements of one snapshot read each unique gradient event one time. Raises TypeError
    for an argument that is not a `Snapshot`.
    """
    _check_snapshot(snap)
    kept = _kept_results(snap)
    if "points" not in kept:
        kept["points"] = _read_points(snap)
    return kept["points"]


def _read_points(snap: Snapshot) -> EventPoints:
    """The `EventPoints` of `snap`, read without the keep of `event_points`."""
    delays: list[float] = []
    counts: list[int] = []
    offset_chunks: list[np.ndarray] = []
    amp_chunks: list[np.ndarray] = []
    for number, g in grad_events(snap):
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
    arrays = _freeze(  # read-only arrays, shared by all callers through the kept result
        np.asarray(delays, dtype=np.float64),
        count,
        # The exclusive prefix sum: the start of the points of each event in the pools.
        np.cumsum(count, dtype=np.int64) - count,
        np.concatenate(offset_chunks) if offset_chunks else np.empty(0, dtype=np.float64),
        np.concatenate(amp_chunks) if amp_chunks else np.empty(0, dtype=np.float64),
    )
    return EventPoints(*arrays, grad_raster_time=float(snap.sequence.grad_raster_time))


@dataclass(frozen=True, eq=False)
class AxisEvents:
    """The events on one axis, in play order. M is the number of blocks that have an event on
    the axis. Times are in seconds from the sequence start, computed as `(block start +
    delay) + offset`."""

    pos: np.ndarray  # int64, M: the play index of the block of each event
    k: np.ndarray  # int64, M: the dense event index minus 1, into the pools of `EventPoints`
    ft: np.ndarray  # float64, M: the time of the first point of the event
    lt: np.ndarray  # float64, M: the time of the last point of the event
    first: np.ndarray  # float64, M: the value of the first point (Hz/m)
    last: np.ndarray  # float64, M: the value of the last point (Hz/m)

    def part(self, e0: int, e1: int) -> "AxisEvents":
        """The events `e0` to `e1` (exclusive), as views."""
        return AxisEvents(
            self.pos[e0:e1],
            self.k[e0:e1],
            self.ft[e0:e1],
            self.lt[e0:e1],
            self.first[e0:e1],
            self.last[e0:e1],
        )


def axis_events(index: SequenceIndex, points: EventPoints, axis: str) -> AxisEvents:
    """The `AxisEvents` of `axis` ("gx", "gy" or "gz"), with the first and the last point of
    each event from `points`. O(blocks)."""
    col = getattr(index, axis)
    pos = np.flatnonzero(col)
    k = col[pos].astype(np.int64) - 1
    base = index.start_s[pos] + points.delay[k]
    first_at = points.at[k]
    last_at = first_at + points.count[k] - 1
    return AxisEvents(
        pos,
        k,
        base + points.offsets[first_at],
        base + points.offsets[last_at],
        points.amp[first_at],
        points.amp[last_at],
    )


class GapKinds(NamedTuple):
    """The gaps between consecutive events of an axis: M - 1 entries for M events, entry `i`
    between the events `i` and `i + 1`. `gap` is the first time of the later event less the
    last time of the earlier one (s). Each gap is in exactly one of `zero`, `short` and
    `long` (bool arrays)."""

    gap: np.ndarray
    zero: np.ndarray  # `gap <= TIME_TOLERANCE`
    short: np.ndarray  # more than that, and `gap <= dt + TIME_TOLERANCE`
    long: np.ndarray  # `gap > dt + TIME_TOLERANCE`

    def part(self, e0: int, e1: int) -> "GapKinds":
        """The gaps between the events `e0` to `e1 - 1` (`AxisEvents.part(e0, e1)`), as views."""
        run = slice(e0, e1 - 1)
        return GapKinds(self.gap[run], self.zero[run], self.short[run], self.long[run])


def gap_kinds(events: AxisEvents, dt: float) -> GapKinds:
    """The `GapKinds` of `events`, with `dt` the gradient raster of the sequence. The one rule
    of the gaps: a zero gap has no point, a short gap has no point and a straight line, and a
    long gap has the ramps of `polyline`."""
    gap = events.ft[1:] - events.lt[:-1]
    zero = gap <= TIME_TOLERANCE
    long = gap > dt + TIME_TOLERANCE
    return GapKinds(gap, zero, ~(zero | long), long)


class Ramps(NamedTuple):
    """The ramps of the long gaps next to each of M events, from `ramps`. A ramp is a line
    between a point of the event and the point `(time, 0)` that is `dt / 2` away."""

    # bool, M: a ramp from 0 before the event (a long gap before it, and its first value is not
    # 0; False for the first event)
    before: np.ndarray
    # bool, M: a ramp to 0 after the event (a long gap after it, and its last value is not 0;
    # False for the last event)
    after: np.ndarray
    from_s: np.ndarray  # float64, M: the time of the point of the ramp before, `ft - dt / 2`
    to_s: np.ndarray  # float64, M: the time of the point of the ramp after, `lt + dt / 2`

    def part(self, e0: int, e1: int) -> "Ramps":
        """The ramps of the events `e0` to `e1` (`AxisEvents.part(e0, e1)`): the gaps beyond
        the run are not known to the run, so it has no ramp from 0 before its first event and
        no ramp to 0 after its last one. `before` and `after` are copies, the times are views."""
        before, after = self.before[e0:e1].copy(), self.after[e0:e1].copy()
        before[:1] = False
        after[-1:] = False
        return Ramps(before, after, self.from_s[e0:e1], self.to_s[e0:e1])


def ramps(events: AxisEvents, gaps: GapKinds, dt: float) -> Ramps:
    """The `Ramps` of `events`, with `gaps` their `gap_kinds` and `dt` the gradient raster of
    the sequence. A ramp is only where the value at the end is not 0 (a value of 1e-6 Hz/m
    or less has its ramp)."""
    half = dt / 2
    n = events.pos.size
    before = np.zeros(n, dtype=bool)
    before[1:] = gaps.long & (events.first[1:] != 0.0)
    after = np.zeros(n, dtype=bool)
    after[:-1] = gaps.long & (events.last[:-1] != 0.0)
    return Ramps(before, after, events.ft - half, events.lt + half)


class RunPoints(NamedTuple):
    """The points of a run of events from `polyline`. The point `i` has the time `t[i]` and
    the value `g[i]` (Hz/m), and a point is never before the point before it. `event[i]` is
    the index in the run of the event that the point belongs to: a ramp point belongs to the
    event that it is the ramp of. `is_event_point[i]` is False for a ramp point. `start[e]`
    is the index of the first point of the event `e` (its ramp from 0 when it has one).
    `gaps` is `gap_kinds` of the run."""

    t: np.ndarray
    g: np.ndarray
    event: np.ndarray
    is_event_point: np.ndarray
    start: np.ndarray
    gaps: GapKinds


def polyline(
    events: AxisEvents,
    points: EventPoints,
    start_s: np.ndarray,
    gaps: GapKinds | None = None,
    ramp: Ramps | None = None,
) -> RunPoints:
    """The points of the run `events` (one or more consecutive events of one axis, in play
    order): the points of each event, the point `(first time - dt / 2, 0)` before an event
    after a long gap when its first value is not 0, and the point `(last time + dt / 2, 0)`
    after an event before a long gap when its last value is not 0. `dt` is
    `points.grad_raster_time` and `start_s` the start of each block (`SequenceIndex.start_s`).
    A caller that has `gap_kinds` and `ramps` of a longer axis passes them as `part` of the
    run (both together); without them they are found for the run.

    The function adds no event: the caller gives the run with the event before it and the
    event after it when it needs the gaps at its ends. It adds no step: the value before
    the first point and after the last point is 0, and a step is a jump between two points
    of one time."""
    pos, k = events.pos, events.k
    n = pos.size
    if gaps is None or ramp is None:
        gaps = gap_kinds(events, points.grad_raster_time)
        ramp = ramps(events, gaps, points.grad_raster_time)
    base = start_s[pos] + points.delay[k]
    if not (ramp.before.any() or ramp.after.any()):
        # No ramp point: the points of the events only, in the same arithmetic as below.
        width = points.count[k]
        start = np.cumsum(width) - width
        total = int(width.sum())
        event = np.repeat(np.arange(n), width)
        pool = points.at[k][event] + np.arange(total) - start[event]
        is_event_point = np.ones(total, dtype=bool)
        t = base[event] + points.offsets[pool]
        g = points.amp[pool]
    else:
        width = ramp.before.astype(np.int64) + points.count[k] + ramp.after.astype(np.int64)
        start = np.cumsum(width) - width
        total = int(width.sum())

        event = np.repeat(np.arange(n), width)
        j = np.arange(total) - start[event]
        is_before = ramp.before[event] & (j == 0)
        is_after = ramp.after[event] & (j == width[event] - 1)
        is_event_point = ~(is_before | is_after)
        pool = points.at[k][event] + j - ramp.before[event]
        t = np.where(
            is_before,
            ramp.from_s[event],
            np.where(
                is_after, ramp.to_s[event], base[event] + points.offsets[pool * is_event_point]
            ),
        )
        g = np.where(is_event_point, points.amp[pool * is_event_point], 0.0)
    # A point is never before the point before it (rounding can put the first point of an
    # event an ulp before the last point of the event before it).
    return RunPoints(np.maximum.accumulate(t), g, event, is_event_point, start, gaps)
