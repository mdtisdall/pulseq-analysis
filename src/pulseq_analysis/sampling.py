"""The gradient waveform of one axis at given times, from the sequence index.

The waveform is the polyline of pypulseq's `Sequence.get_gradients()`, in Hz/m:

1. The points. For each block, in play order, that has an event on the axis: the
   corner or sample points of that event (`seq_utils.gradient_offsets`), at the times
   `(block start + delay) + offsets`, with the event's amplitudes.
2. The join. The points of all these blocks make one list. A point whose time is not
   more than `pypulseq.eps` (1e-9 s) after the time of the point before it in the list
   is left out. pypulseq's `waveforms()` leaves out the first point of an event at the
   time of the last point of the event before it, so the step at such a junction takes
   the value of the earlier event. The same rule removes the repeated points that
   `gradient_offsets` gives inside some events (for example a trapezoid without a flat
   time), which have the same value.
3. The values. Straight lines between consecutive points, also across a gap between
   two events. 0 before the first point and after the last point.

`GradientSampler.block_samples` gives a second form of the same waveform, for the SAFE
PNS model (`pns_levels.pns_levels`): each block on its own, at the local times
`(j + 0.5) * dt` from the block start, with the values of the block's own event and 0
outside it. It has no line across a gap between two events, and its sample times do not
drift with the sums of the block durations, so one block gives the same samples wherever
it is in the sequence.
"""

import math

import numpy as np
import pypulseq as pp

from .seq_index import SequenceIndex, grad_events
from .seq_utils import GRAD_COLUMNS, TIME_TOLERANCE, gradient_offsets


class GradientSampler:
    """The waveform of each axis of one sequence, sampled at any sorted times.

    The unique gradient events are read one time (`seq_index.grad_events`). A call to
    `sample` costs O(samples + blocks between the first and the last sample), not
    O(all blocks).
    """

    def __init__(self, seq: pp.Sequence, index: SequenceIndex) -> None:
        delays: list[float] = []
        counts: list[int] = []
        offset_chunks: list[np.ndarray] = []
        amp_chunks: list[np.ndarray] = []
        for _, g in grad_events(seq, index):
            delay, offsets, amp = gradient_offsets(g)
            offsets = np.asarray(offsets, dtype=np.float64)
            amp = np.asarray(amp, dtype=np.float64)
            delays.append(float(delay))
            counts.append(offsets.size)
            offset_chunks.append(offsets)
            amp_chunks.append(amp)

        self._index = index
        self._delay = np.asarray(delays, dtype=np.float64)
        self._n = np.asarray(counts, dtype=np.int64)
        # The exclusive prefix sum: the start position of each event's points in the
        # pooled `_offsets`/`_amp` arrays.
        self._at = np.cumsum(self._n, dtype=np.int64) - self._n
        self._offsets = (
            np.concatenate(offset_chunks) if offset_chunks else np.empty(0, dtype=np.float64)
        )
        self._amp = np.concatenate(amp_chunks) if amp_chunks else np.empty(0, dtype=np.float64)
        # Filled lazily, one time for each axis that `sample` is called with.
        self._axis_blocks: dict[str, np.ndarray] = {}
        # The samples of each (event, n, dt) that `block_samples` has computed, up to the last
        # one at or before the last point of the event.
        self._block_sample_cache: dict[tuple[int, int, float], np.ndarray] = {}

    def _event_blocks(self, axis: str) -> np.ndarray:
        """The play indexes that have an event on `axis`, sorted, computed one time and
        kept for later calls."""
        blocks = self._axis_blocks.get(axis)
        if blocks is None:
            blocks = np.flatnonzero(getattr(self._index, axis))
            self._axis_blocks[axis] = blocks
        return blocks

    def _points(self, axis: str, blocks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Times (s) and values (Hz/m) of the corner or sample points of the gradient
        events of `axis` at the play indexes `blocks` (sorted, each with an event on
        `axis`), in block order, before the join rule is applied."""
        col = getattr(self._index, axis)
        k = col[blocks].astype(np.int64) - 1  # 0-based event index
        counts = self._n[k]
        total = int(counts.sum())
        if total == 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
        base = np.repeat(self._index.start_s[blocks] + self._delay[k], counts)
        group_start = np.cumsum(counts) - counts
        local = np.arange(total, dtype=np.int64) - np.repeat(group_start, counts)
        pool_index = np.repeat(self._at[k], counts) + local
        times = base + self._offsets[pool_index]
        values = self._amp[pool_index]
        return times, values

    def sample(self, axis: str, t: np.ndarray) -> np.ndarray:
        """The waveform of `axis` ("gx", "gy" or "gz") in Hz/m at the times `t` (s),
        which must be sorted in increasing order."""
        if axis not in GRAD_COLUMNS:
            raise ValueError(f"axis must be one of {GRAD_COLUMNS}: {axis!r}")
        t = np.asarray(t, dtype=np.float64)
        if t.size == 0:
            return np.empty(0, dtype=np.float64)

        event_blocks = self._event_blocks(axis)
        if event_blocks.size == 0:
            return np.zeros(t.size, dtype=np.float64)

        # The block that contains (or, past the sequence end, precedes) each end of the
        # sample range: the last block whose start is not after that time.
        start_s = self._index.start_s
        lo_block = max(int(np.searchsorted(start_s, t[0], side="right")) - 1, 0)
        hi_block = max(int(np.searchsorted(start_s, t[-1], side="right")) - 1, 0)

        # The events of `axis` in that block range, plus the nearest one before it and
        # the nearest one after it, so that a gap at the edge of the range interpolates
        # between the same two points as it does for the whole file.
        lo_pos = int(np.searchsorted(event_blocks, lo_block, side="left"))
        hi_pos = int(np.searchsorted(event_blocks, hi_block, side="right"))
        blocks = event_blocks[max(lo_pos - 1, 0) : min(hi_pos + 1, event_blocks.size)]

        times, values = self._points(axis, blocks)
        if times.size == 0:
            return np.zeros(t.size, dtype=np.float64)

        keep = np.ones(times.size, dtype=bool)
        if times.size > 1:
            keep[1:] = times[1:] > times[:-1] + TIME_TOLERANCE
        times = times[keep]
        values = values[keep]

        return np.interp(t, times, values, left=0.0, right=0.0)

    def _kept_samples(self, event_k: int, count_n: int, dt: float) -> int:
        """The number of the first samples of a block of `count_n` samples that can be
        nonzero for gradient event `event_k`: the samples at or before its last point
        (`block_samples` gives 0 after it)."""
        num_points = int(self._n[event_k])
        if num_points == 0:
            return 0
        last_t = self._delay[event_k] + self._offsets[int(self._at[event_k]) + num_points - 1]
        # The count of j with (j + 0.5) * dt <= last_t, from a guess that the two loops
        # correct with the same float product that `_event_samples` uses.
        j = math.floor(last_t / dt - 0.5)
        while (j + 1.5) * dt <= last_t:
            j += 1
        while j >= 0 and (j + 0.5) * dt > last_t:
            j -= 1
        return min(count_n, j + 1)

    def _event_samples(self, event_k: int, first: int, stop: int, dt: float) -> np.ndarray:
        """The samples (Hz/m) `first` to `stop - 1` of a block with gradient event
        `event_k`, by the rule of `block_samples`."""
        num_points = int(self._n[event_k])
        if num_points == 0:
            return np.zeros(stop - first, dtype=np.float64)
        at = int(self._at[event_k])
        points_t = self._delay[event_k] + self._offsets[at : at + num_points]
        points_v = self._amp[at : at + num_points]
        t = (np.arange(first, stop, dtype=np.float64) + 0.5) * dt
        # The point at or before `t`: the largest p with points_t[p] <= t. It depends only
        # on `t` and `points_t`, so a tool that walks the points and the samples in order
        # with the same comparisons gets the same p.
        p = np.searchsorted(points_t, t, side="right") - 1
        p = np.clip(p, 0, num_points - 1)
        t0 = points_t[p]
        before = t < t0
        last = p == num_points - 1
        samples = np.zeros(stop - first, dtype=np.float64)
        # The last point's own value, only at exactly its time.
        at_last = last & ~before & (t == t0)
        samples[at_last] = points_v[p[at_last]]
        # Between two points: linear.
        # t0 <= t < t1 here: `searchsorted(side="right") - 1` gives the last point at or
        # before t, so t1 > t0. At a step (two points at one time), p is the later point.
        mid = ~before & ~last
        if np.any(mid):
            p_mid = p[mid]
            t0_mid = t0[mid]
            t1_mid = points_t[p_mid + 1]
            v0_mid = points_v[p_mid]
            v1_mid = points_v[p_mid + 1]
            t_mid = t[mid]
            samples[mid] = v0_mid + (v1_mid - v0_mid) / (t1_mid - t0_mid) * (t_mid - t0_mid)
        return samples

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
        is the block's own event on `axis`: its points at `delay + offset`
        (`seq_utils.gradient_offsets`), a straight line between two points, and 0
        before the first point and after the last point. At a local time equal to a
        point time where two points have the same time (a step), the later point's
        value is used. A block with no event on `axis` gives zeros. It differs from `sample`
        at a step at a block junction (`add_block` accepts a step up to
        `max_slew * grad_raster_time`), and by the float drift of the block start sums
        (`tests/test_sampling.py`).

        The result is, bit for bit, the samples `skip` to `skip + count - 1` of the result
        for `skip=0, count=None`. The first and the last block of that sample range give
        only their samples inside it; they are computed for that part only and are not
        kept, so the cost does not grow with the parts of these blocks outside the
        range. The samples of each unique (event, n) of a block that lies whole in the
        range are computed one time and kept, up to the last sample at or before the
        last point of the event (the samples after it are 0 and are not kept), and a
        call gathers them with numpy for all these blocks, not with a Python loop over
        the blocks. Cost: O(samples in the range + blocks in the range + points of the
        events not yet kept). Memory: the result, and the kept samples of the events of
        whole blocks, so it does not grow with the length of a block that the range cuts.

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
        # `_points` builds `group_start`, less `skip`). The blocks with an event on
        # `axis` that have a sample in the result are the ones to fill.
        ends = np.cumsum(n)
        starts = ends - n - skip
        col = getattr(self._index, axis)[first:stop].astype(np.int64)
        touched = (col > 0) & (n > 0) & (ends - skip > 0) & (starts < count)
        if not np.any(touched):
            return out

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
            hi = min(hi, self._kept_samples(event_k, int(n_touched[position]), dt))
            if lo < hi:
                out[block_start + lo : block_start + hi] = self._event_samples(event_k, lo, hi, dt)

        if not np.any(whole):
            return out

        cache = self._block_sample_cache

        def event_samples(event_k: int, count_n: int) -> np.ndarray:
            """The samples (Hz/m) of gradient event `event_k` in a block of `count_n`
            samples, up to the last one at or before its last point, cached by
            `(event_k, count_n, dt)`."""
            cache_key = (event_k, count_n, dt)
            samples = cache.get(cache_key)
            if samples is None:
                kept = self._kept_samples(event_k, count_n, dt)
                samples = self._event_samples(event_k, 0, kept, dt)
                cache[cache_key] = samples
            return samples

        # One (event, n) pair for each distinct combination in the range: a Python loop
        # over these (normally few), not over the blocks themselves.
        pairs = np.stack([k[whole], n_touched[whole]], axis=1)
        starts_whole = starts_touched[whole]
        unique_pairs, inverse = np.unique(pairs, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        for pair_index in range(unique_pairs.shape[0]):
            event_k = int(unique_pairs[pair_index, 0])
            count_n = int(unique_pairs[pair_index, 1])
            samples = event_samples(event_k, count_n)
            if samples.size == 0:
                continue
            block_starts = starts_whole[inverse == pair_index]
            idx = (block_starts[:, None] + np.arange(samples.size, dtype=np.int64)[None, :]).ravel()
            out[idx] = np.tile(samples, block_starts.size)

        return out


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
