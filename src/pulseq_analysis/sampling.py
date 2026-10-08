"""The gradient waveform of one axis at given times, from the sequence index.

The waveform is a polyline in Hz/m, the model of MATLAB Pulseq (`docs/implementation.md`, "The
gradient waveform"). With `dt = seq.grad_raster_time`:

1. The points. For each block, in play order, that has an event on the axis: the corner
   or sample points of that event (`seq_utils.gradient_offsets`), at the times
   `(block start + delay) + offsets`, with the event's amplitudes.
2. Between two consecutive events on the axis, with `last_time` and `last` of the earlier
   event, `first_time` and `first` of the later one, and `gap = first_time - last_time`:
   - `gap <= TIME_TOLERANCE` (a zero gap): no point. When `first != last`, the waveform
     steps from `last` to `first` at that time. The value at the time of the step is `last`.
   - `gap <= dt + TIME_TOLERANCE` (a short gap): no point. The waveform is the straight line
     from `last` to `first`.
   - A longer gap: the point `(last_time + dt / 2, 0)` when `last != 0`, and the point
     `(first_time - dt / 2, 0)` when `first != 0`. The waveform is 0 between them.
3. Straight lines between consecutive points. 0 before the first point and after the last
   point (a first or a last value that is not 0 is a step).

The rule of the gaps (the first and the last point of each event, the zero, the short and
the long gap, and the ramp points) is in `_events` (`axis_events`, `gap_kinds`, `ramps`
and `polyline`), where `grad_peaks` uses it too.

pypulseq's `Sequence.get_gradients()` draws a straight line across each gap, also across
a long gap (pypulseq-issues 12). The two waveforms differ where an event starts or ends at
a value that is not 0 next to a long gap, and at the step of a zero gap (pypulseq's line
starts at `last` and ends at the second point of the later event).

`GradientSampler.block_samples` gives the same waveform for the SAFE PNS model
(`pns_levels.pns_levels`), in a second form: each block on its own, at the local times
`(j + 0.5) * dt` from the block start, with the values of the block's own event, and the
line of a short gap and the ramps of a long gap written over the samples that they cover. The
sample times of the own event do not drift with the sums of the block durations, so one block
gives the same samples wherever it is in the sequence, except for the samples that a gap
covers.
"""

import math
from dataclasses import dataclass

import numpy as np

from ._equality import _freeze
from ._events import (
    AxisEvents,
    GapKinds,
    Ramps,
    axis_events,
    event_points,
    gap_kinds,
    polyline,
    ramps,
)
from .seq_index import SequenceIndex, sequence_index
from .seq_utils import GRAD_COLUMNS, TIME_TOLERANCE
from .snapshot import Snapshot, _check_snapshot, _kept_results


@dataclass(frozen=True, eq=False)
class _AxisGaps:
    """The gaps of one axis that are not a step: the places where the waveform is not the
    own event of a block. Each array is read-only and sorted by time.

    A piece is a straight line from `(start_s, start_hz_per_m)` to `(end_s, end_hz_per_m)`:
    the line across a short gap whose two ends are not both 0, the ramp to 0 after an event
    that ends at a value that is not 0, and the ramp from 0 before an event that starts at
    a value that is not 0 (the last two are the ramps of a long gap). The pieces do not
    overlap."""

    start_s: np.ndarray
    end_s: np.ndarray
    start_hz_per_m: np.ndarray
    end_hz_per_m: np.ndarray
    max_length_s: float  # the length of the longest piece, 0 without pieces


class GradientSampler:
    """The waveform of each axis of one sequence, sampled at any sorted times.

    The index and the points of the unique gradient events of the snapshot come from
    `seq_index.sequence_index` and `_events.event_points`, which make each one time. The
    sampler does not copy them. The gaps between the events of an axis (the module docstring)
    are found one time for each snapshot and axis, from the index and the points, and kept on
    the snapshot (the key `("gaps", axis)`). Only the sampler keeps them: `gradient_peaks`
    uses the same rule (`_events.gap_kinds`) for its own values. A new sampler also finds
    the events of an axis one time, in its first `sample` or gap search on that axis
    (`_axis_events`). Apart from these, a call to `sample` costs O(samples + blocks between
    the first and the last sample), not O(all blocks).

    `gradient_sampler(snap)` makes a sampler of a snapshot. Raises TypeError for an
    argument that is not a `Snapshot`.
    """

    def __init__(self, snap: Snapshot) -> None:
        _check_snapshot(snap)
        self._snapshot = snap
        self._index = sequence_index(snap)
        points = event_points(snap)
        self._points = points
        self._grad_raster_time = points.grad_raster_time
        self._delay = points.delay
        self._n = points.count
        # The start position of each event's points in the pooled `_offsets`/`_amp` arrays.
        self._at = points.at
        self._offsets = points.offsets
        self._amp = points.amp
        # Filled lazily, one time for each axis that `sample` or `_find_gaps` is called with.
        self._events: dict[str, tuple[AxisEvents, GapKinds, Ramps]] = {}
        # The samples of each (event, dt) that `block_samples` has computed, from the first
        # to the last one at or before the last point of the event (`_kept_samples`). A block
        # of `n` samples has the first `n` of them.
        self._block_sample_cache: dict[tuple[int, float], np.ndarray] = {}

    def _axis_events(self, axis: str) -> tuple[AxisEvents, GapKinds, Ramps]:
        """The `AxisEvents` of `axis` with their `gap_kinds` and `ramps`, computed one time and
        kept for later calls."""
        found = self._events.get(axis)
        if found is None:
            events = axis_events(self._index, self._points, axis)
            gaps = gap_kinds(events, self._grad_raster_time)
            found = (events, gaps, ramps(events, gaps, self._grad_raster_time))
            self._events[axis] = found
        return found

    def _gaps(self, axis: str) -> _AxisGaps:
        """The gaps of `axis`, found one time for each snapshot and kept on it."""
        kept = _kept_results(self._snapshot)
        key = ("gaps", axis)
        if key not in kept:
            kept[key] = self._find_gaps(axis)
        return kept[key]

    def _find_gaps(self, axis: str) -> _AxisGaps:
        """The `_AxisGaps` of `axis`, from the first and the last point of each event, with
        the rule of the module docstring. O(blocks with an event on `axis`)."""
        events, kinds, ramp = self._axis_events(axis)
        if events.pos.size < 2:
            empty = np.empty(0, dtype=np.float64)
            return _frozen_gaps(empty, empty, empty, empty)

        before_s, before_v = events.lt[:-1], events.last[:-1]  # the end of the earlier event
        after_s, after_v = events.ft[1:], events.first[1:]  # the start of the later event
        short = kinds.short & ((before_v != 0.0) | (after_v != 0.0))
        down = ramp.after[:-1]  # the ramp to 0 after the earlier event of the gap
        up = ramp.before[1:]  # the ramp from 0 before the later event of the gap
        down_s, up_s = ramp.to_s[:-1], ramp.from_s[1:]  # the times of the points of the ramps

        # Each piece has its gap number and its place in the gap (the ramp to 0 is before
        # the ramp from 0), which give the order in time.
        number = np.arange(kinds.gap.size)
        key = np.concatenate([2 * number[short], 2 * number[down], 2 * number[up] + 1])
        order = np.argsort(key, kind="stable")
        start_s = np.concatenate([before_s[short], before_s[down], up_s[up]])[order]
        end_s = np.concatenate([after_s[short], down_s[down], after_s[up]])[order]
        start_v = np.concatenate([before_v[short], before_v[down], np.zeros(up.sum())])[order]
        end_v = np.concatenate([after_v[short], np.zeros(down.sum()), after_v[up]])[order]
        return _frozen_gaps(start_s, end_s, start_v, end_v)

    def sample(self, axis: str, t: np.ndarray) -> np.ndarray:
        """The waveform of `axis` ("gx", "gy" or "gz") in Hz/m at the times `t` (s), which
        must be sorted in increasing order, by the model of the module docstring. The value
        at the time of a step is the value before the step. It equals the values of the
        oracle `tests/oracles/waveform.py` to the float rounding."""
        if axis not in GRAD_COLUMNS:
            raise ValueError(f"axis must be one of {GRAD_COLUMNS}: {axis!r}")
        t = np.asarray(t, dtype=np.float64)
        if t.size == 0:
            return np.empty(0, dtype=np.float64)

        events, gaps, ramp = self._axis_events(axis)
        if events.pos.size == 0:
            return np.zeros(t.size, dtype=np.float64)

        # The block that contains (or, past the sequence end, precedes) each end of the
        # sample range: the last block whose start is not after that time.
        start_s = self._index.start_s
        lo_block = max(int(np.searchsorted(start_s, t[0], side="right")) - 1, 0)
        hi_block = max(int(np.searchsorted(start_s, t[-1], side="right")) - 1, 0)

        # The events of `axis` in that block range, plus the nearest one before it and
        # the nearest one after it, so that a gap at the edge of the range has the same
        # points as it does for the whole file.
        lo_pos = int(np.searchsorted(events.pos, lo_block, side="left"))
        hi_pos = int(np.searchsorted(events.pos, hi_block, side="right"))
        e0, e1 = max(lo_pos - 1, 0), min(hi_pos + 1, events.pos.size)

        # The points of the run, with the ramp points of the long gaps between its events. A
        # point with the time and the value of the point before it changes no value (the
        # triangle of a trapezoid without a flat time has two such points). Without them,
        # most sequences have no two points at one time, and `_polyline_values` needs no
        # step rule.
        points = polyline(
            events.part(e0, e1), self._points, start_s, gaps.part(e0, e1), ramp.part(e0, e1)
        )
        distinct = np.ones(points.t.size, dtype=bool)
        distinct[1:] = (points.t[1:] != points.t[:-1]) | (points.g[1:] != points.g[:-1])
        times, values = points.t[distinct], points.g[distinct]
        return _polyline_values(times, values, t)

    def _kept_samples(self, event_k: int, dt: float) -> int:
        """The number of the first samples of a block that can be nonzero for gradient event
        `event_k`: the samples at or before its last point, or within `TIME_TOLERANCE`
        after it (`block_samples` gives 0 after that). A block of `n` samples has the
        first `min(n, _kept_samples)` of them."""
        last_t = self._delay[event_k] + self._offsets[int(self._at[event_k] + self._n[event_k]) - 1]
        limit = last_t + TIME_TOLERANCE
        # The count of j with (j + 0.5) * dt <= limit, from a guess that the two loops
        # correct with the same float product that `_event_samples` uses.
        j = math.floor(limit / dt - 0.5)
        while (j + 1.5) * dt <= limit:
            j += 1
        while j >= 0 and (j + 0.5) * dt > limit:
            j -= 1
        return j + 1

    def _event_samples(self, event_k: int, first: int, stop: int, dt: float) -> np.ndarray:
        """The samples (Hz/m) `first` to `stop - 1` of a block with gradient event
        `event_k`, by the rule of `block_samples`: the polyline of the event, with the value
        before a step, and a time within `TIME_TOLERANCE` after the last point taken as the
        time of that point."""
        at = int(self._at[event_k])
        num_points = int(self._n[event_k])
        points_t = self._delay[event_k] + self._offsets[at : at + num_points]
        points_v = self._amp[at : at + num_points]
        t = (np.arange(first, stop, dtype=np.float64) + 0.5) * dt
        t = np.where(t <= points_t[-1] + TIME_TOLERANCE, np.minimum(t, points_t[-1]), t)
        return _polyline_values(points_t, points_v, t)

    def block_samples(
        self,
        axis: str,
        first: int,
        stop: int,
        dt: float,
        *,
        skip: int = 0,
        count: int | None = None,
    ) -> np.ndarray:
        """The samples of `axis` ("gx", "gy" or "gz") in Hz/m of the blocks `first` to
        `stop - 1` (play indexes), joined in play order (float64), from the sample `skip`
        of that range, `count` samples (`count=None`: all the samples after `skip`).

        Block `i` has `n_i` samples (`raster_block_lengths`), at the local times
        `(j + 0.5) * dt`, `j = 0 .. n_i - 1`, from the block start. The value of a sample
        is the waveform of the module docstring at that time. It is the block's own event
        on `axis` (its points at `delay + offset`, `seq_utils.gradient_offsets`, a
        straight line between two points, and 0 before the first point and after the last
        point; at a local time that two points have (a step), the value before the step, as
        `sample` has it; a sample within `TIME_TOLERANCE` after the last point has the value
        of that point), with one change: a sample that a gap covers has the value of the
        line of a short gap or of the ramp of a long gap, whichever block the sample is in
        (also a block with no event on `axis`). A ramp from a raster edge ends at a sample time, where it is 0,
        so for events on the raster only the samples in a short gap change, and a sequence
        with no end that is not 0 next to a gap has the samples of the own events only.
        `sample` gives the same waveform, apart from the float drift of the block start sums
        (`tests/test_sampling.py`): the sample time of a gap is `start + (j + 0.5) * dt` with
        the start of the block from `seq_index`, as the oracle gives it.

        The result is, bit for bit, the samples `skip` to `skip + count - 1` of the result
        for `skip=0, count=None`. The first and the last block of that sample range give
        only their samples inside it; they are computed for that part only and are not
        kept, so the cost does not grow with the parts of these blocks outside the
        range. The samples of each unique event of a block that lies whole in the
        range are computed one time and kept, up to the last sample at or before the
        last point of the event, or within `TIME_TOLERANCE` after it (the samples after it
        are 0 and are not kept), and a call gathers them with one indexed copy for all these
        blocks, not with a Python loop over the blocks: a block of `n` samples has the first
        `n` of the kept samples of its event, whatever the length of the other blocks that
        have the event. The samples in a gap are written after that, for the pieces of the
        gaps that overlap the range (`_write_gaps`). Cost: O(samples in the range + blocks in
        the range + points of the events not yet kept), and one time for each sequence and
        axis O(blocks with an event on the axis) for the gaps (`_find_gaps`). Memory: the
        result, and the kept samples of the events of whole blocks, so it does not grow with
        the length of a block that the range cuts.

        Raises ValueError for an unknown axis, for `first`/`stop` outside
        `0 <= first <= stop <= num_blocks`, when a block of the range is not on the
        raster (`raster_block_lengths`), and when `skip` or `count` is negative or
        `skip + count` is more than the samples of the range."""
        if axis not in GRAD_COLUMNS:
            raise ValueError(f"axis must be one of {GRAD_COLUMNS}: {axis!r}")
        num_blocks = self._index.num_blocks
        if not (0 <= first <= stop <= num_blocks):
            raise ValueError(
                f"first/stop must satisfy 0 <= first <= stop <= {num_blocks}: "
                f"first={first!r}, stop={stop!r}"
            )

        # The lengths and the raster check of the range only, so that the cost does not
        # grow with the whole file.
        n, on_raster = _raster_lengths(self._index.duration_s[first:stop], dt)
        if not on_raster:
            raise ValueError(
                f"block_samples: a block in [{first}, {stop}) is not on the raster (dt={dt!r})"
            )

        total = int(n.sum())
        end = total if count is None else skip + count
        if skip < 0 or (count is not None and count < 0) or end > total or skip > end:
            raise ValueError(
                f"block_samples: skip and count must be 0 or more, and skip + count not more "
                f"than the {total} samples of the range: skip={skip!r}, count={count!r}"
            )
        skip = int(skip)
        count = int(end) - skip

        out = np.zeros(count, dtype=np.float64)
        if count == 0:
            return out

        # The start of each block's samples in the result (the prefix sum of `n`, as
        # `_points` builds `group_start`, less `skip`).
        ends = np.cumsum(n)
        starts = ends - n - skip
        self._fill_events(out, axis, first, stop, n, starts, dt)
        self._write_gaps(out, axis, first, n, starts, dt)
        return out

    def _fill_events(
        self,
        out: np.ndarray,
        axis: str,
        first: int,
        stop: int,
        n: np.ndarray,
        starts: np.ndarray,
        dt: float,
    ) -> None:
        """Write into `out` (zeros) the samples of the own event of each block `first` to
        `stop - 1` with an event on `axis`, that have a sample in `out`. `n` and `starts` are
        the sample counts of the blocks and the positions of their first samples in `out`
        (negative when the range cuts the block)."""
        count = out.size
        ends = starts + n
        # The blocks with an event on `axis` that have a sample in the result are the ones
        # to fill.
        col = getattr(self._index, axis)[first:stop].astype(np.int64)
        touched = (col > 0) & (n > 0) & (ends > 0) & (starts < count)
        if not np.any(touched):
            return

        k = col[touched] - 1  # 0-based event index, into `self._n`/`self._at`/pools
        n_touched = n[touched]
        starts_touched = starts[touched]

        # A block that the range cuts (at most the first and the last) is computed for
        # the part inside the range only. The other blocks are whole.
        whole = (starts_touched >= 0) & (starts_touched + n_touched <= count)
        for position in np.flatnonzero(~whole):
            event_k = int(k[position])
            block_start = int(starts_touched[position])
            lo = max(-block_start, 0)
            hi = min(int(n_touched[position]), count - block_start)
            hi = min(hi, self._kept_samples(event_k, dt))
            if lo < hi:
                out[block_start + lo : block_start + hi] = self._event_samples(event_k, lo, hi, dt)

        if not np.any(whole):
            return

        cache = self._block_sample_cache
        # One entry for each distinct event in the range: a Python loop over these (normally
        # few), not over the blocks themselves. A block of `n` samples has the first `n` of
        # the samples of its event (the samples do not depend on `n`), or all of them when
        # there are fewer.
        unique_k, inverse = np.unique(k[whole], return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        kept = []
        for event_k in unique_k.tolist():
            samples = cache.get((event_k, dt))
            if samples is None:
                samples = self._event_samples(event_k, 0, self._kept_samples(event_k, dt), dt)
                cache[(event_k, dt)] = samples
            kept.append(samples)
        sizes = np.fromiter((samples.size for samples in kept), dtype=np.int64, count=len(kept))
        pool = np.concatenate(kept)
        pool_starts = np.cumsum(sizes) - sizes

        # The samples of block `b` are `pool[pool_starts[inverse[b]] :][:length[b]]`, written
        # at `starts_touched[whole][b]`: one gather over the blocks.
        length = np.minimum(n_touched[whole], sizes[inverse])
        total = int(length.sum())
        if total == 0:
            return
        group_starts = np.cumsum(length) - length
        local = np.arange(total, dtype=np.int64)
        source = local + np.repeat(pool_starts[inverse] - group_starts, length)
        target = local + np.repeat(starts_touched[whole] - group_starts, length)
        out[target] = pool[source]

    def _write_gaps(
        self,
        out: np.ndarray,
        axis: str,
        first: int,
        n: np.ndarray,
        starts: np.ndarray,
        dt: float,
    ) -> None:
        """Write into `out` the samples that a piece of the gaps of `axis` covers
        (`_AxisGaps`): the samples whose time is inside the piece, not at an end of it, with
        the value of the line of the piece. The time of the sample `j` of block `b` is
        `start_s[b] + (j + 0.5) * dt`, as the oracle `tests/oracles/waveform.py` gives it,
        so a sample is the same for any `skip` and `count`. `n`, `starts` and `first` are
        those of `block_samples`: the sample counts of the blocks of the range, the positions
        of their first samples in `out` (negative when `skip` cuts the block), and the first
        block.

        The pieces are found with `numpy.searchsorted`, for the times of the first and of
        the last sample of `out`. A piece is at most one raster time long, so a piece
        has a few samples at most, and the work is O(pieces in the range), with no loop over
        the pieces."""
        gaps = self._gaps(axis)
        if gaps.start_s.size == 0:
            return
        start_s = self._index.start_s
        ends = starts + n

        def sample_time(position: int) -> float:
            block = int(np.searchsorted(ends, position, side="right"))
            return float(start_s[first + block] + ((position - starts[block]) + 0.5) * dt)

        first_time, last_time = sample_time(0), sample_time(out.size - 1)
        # The pieces that start before the last sample and end after the first sample. The
        # pieces are sorted by their start, and none is longer than `max_length_s`.
        lo = int(np.searchsorted(gaps.start_s, first_time - gaps.max_length_s, side="left"))
        hi = int(np.searchsorted(gaps.start_s, last_time, side="left"))
        near = np.flatnonzero(gaps.end_s[lo:hi] > first_time) + lo
        if near.size == 0:
            return
        t0, t1 = gaps.start_s[near], gaps.end_s[near]
        v0, v1 = gaps.start_hz_per_m[near], gaps.end_hz_per_m[near]

        # The blocks of the range that each piece overlaps: from the block that has the
        # start of the piece to the last block that starts before its end.
        last_block = first + n.size - 1
        a = np.maximum(np.searchsorted(start_s, t0, side="right") - 1, first)
        b = np.minimum(np.searchsorted(start_s, t1, side="left") - 1, last_block)
        blocks_of = np.maximum(b - a + 1, 0)
        piece = np.repeat(np.arange(near.size), blocks_of)
        block = a[piece] + (
            np.arange(piece.size) - np.repeat(np.cumsum(blocks_of) - blocks_of, blocks_of)
        )
        if block.size == 0:
            return

        # The samples of each (piece, block) that can be inside the piece: `width`
        # samples from one before the first one that can be.
        width = math.ceil(gaps.max_length_s / dt) + 3
        j = np.floor((t0[piece] - start_s[block]) / dt - 0.5).astype(np.int64) - 1
        j = np.maximum(j, 0)[:, None] + np.arange(width, dtype=np.int64)[None, :]
        time = start_s[block][:, None] + (j + 0.5) * dt
        position = starts[block - first][:, None] + j
        inside = (
            (j < n[block - first][:, None])
            & (time > t0[piece][:, None])
            & (time < t1[piece][:, None])
            & (position >= 0)
            & (position < out.size)
        )
        t0_in = np.broadcast_to(t0[piece][:, None], time.shape)[inside]
        t1_in = np.broadcast_to(t1[piece][:, None], time.shape)[inside]
        v0_in = np.broadcast_to(v0[piece][:, None], time.shape)[inside]
        v1_in = np.broadcast_to(v1[piece][:, None], time.shape)[inside]
        out[position[inside]] = v0_in + (v1_in - v0_in) * ((time[inside] - t0_in) / (t1_in - t0_in))


def gradient_sampler(snap: Snapshot) -> GradientSampler:
    """The `GradientSampler` of `snap`: the public way to make a sampler.

    It is `GradientSampler(snap)`. The index, the event points and the gaps are kept on the
    snapshot, so the sampler is not kept. Raises TypeError for an argument that is not a
    `Snapshot`."""
    return GradientSampler(snap)


def _frozen_gaps(*arrays: np.ndarray) -> _AxisGaps:
    """An `_AxisGaps` of the arrays (start, end, start value, end value), read-only
    (`_equality._freeze`): all callers share the kept result."""
    start_s, end_s, start_hz_per_m, end_hz_per_m = _freeze(*arrays)
    max_length_s = float(np.max(end_s - start_s)) if start_s.size else 0.0
    return _AxisGaps(start_s, end_s, start_hz_per_m, end_hz_per_m, max_length_s=max_length_s)


def _polyline_values(times: np.ndarray, values: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The values of the polyline through the points `(times, values)` at the times `q`:
    0 before the first point and after the last point. `times` is sorted and not empty. A
    time that two points have (a step) gives the value of the first of them at that time,
    and the line after it starts at the second one."""
    if np.all(times[1:] > times[:-1]):
        # No two points have one time, so there is no step: numpy's interpolation is the
        # same polyline, and faster.
        return np.interp(q, times, values, left=0.0, right=0.0)
    n = times.size
    i = np.clip(np.searchsorted(times, q, side="left"), 0, n - 1)
    j = np.maximum(i - 1, 0)
    span = times[i] - times[j]
    positive = span > 0.0
    fraction = np.where(positive, (q - times[j]) / np.where(positive, span, 1.0), 0.0)
    inside = values[j] + (values[i] - values[j]) * fraction
    value = np.where(times[i] == q, values[i], inside)
    return np.where((q >= times[0]) & (q <= times[-1]), value, 0.0)


# A block is on the raster when its duration is within this many samples of a whole
# number of samples. Otherwise `pns_levels.pns_levels` samples the whole file with
# `GradientSampler.sample`, not block by block.
ON_RASTER_TOLERANCE = 1e-6


def raster_block_lengths(index: SequenceIndex, dt: float) -> tuple[np.ndarray, bool]:
    """The number of samples of each block, `round(duration / dt)` (int64, length N, in
    play order), and whether every block is on the raster (`ON_RASTER_TOLERANCE`).

    The samples of block `i` start at sample `sum(n[:i])` of the whole sequence. A caller
    that draws the PNS samples of `pns_levels.pns_levels` uses the same numbers to find
    the samples of a block."""
    return _raster_lengths(index.duration_s, dt)


def _raster_lengths(duration_s: np.ndarray, dt: float) -> tuple[np.ndarray, bool]:
    """`raster_block_lengths` of the given block durations."""
    ratio = duration_s / dt
    n = np.rint(ratio).astype(np.int64)
    return n, bool(np.all(np.abs(ratio - n) <= ON_RASTER_TOLERANCE))


def sequence_samples(index: SequenceIndex, dt: float) -> int:
    """The number of samples of the whole sequence at the raster `dt`: the one rule of the
    package, which `pns_levels.pns_levels` and `grad_spectrum.gradient_spectrum` use.

    When every block is on the raster (`raster_block_lengths`), it is the sum of the block
    lengths. Otherwise it is `ceil((index.end_s - 1e-10) / dt)`, and at least 0 (the
    value of an empty sequence). `index.end_s` is the sequential sum of the block
    durations. A `ceil` of the compensated sum of Python's `sum`, or of `index.end_s`
    without the 1e-10, can give one sample more (`tests/test_sampling.py`)."""
    n, on_raster = raster_block_lengths(index, dt)
    if on_raster:
        return int(n.sum())
    return max(math.ceil((index.end_s - 1e-10) / dt), 0)
