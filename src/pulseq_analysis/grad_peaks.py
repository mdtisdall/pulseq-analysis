"""The peak amplitude, the peak slew rate and the RMS amplitude of a sequence's gradients.

Each gradient event is piecewise linear between the points that `seq_utils.gradient_points`
gives, as the Pulseq specification treats it. This module computes these values for each
logical axis (x, y, z) and for the three-axis vector, over a time range. It does not compare
them with limits: a caller that has the hardware limits compares the values with them.

The axes are the logical sequence axes, not the physical gradient axes of a scanner. The
scanner rotates the logical axes onto the physical ones for the prescribed orientation, so on
an oblique slice one physical axis can see amplitude up to the vector peak,
`GradientPeaks.vector_peak_hz_per_m`, even when no single logical axis is near the limit.

This computes the per-event values one time for each unique gradient event, from the points
of `_events.event_points` (which reads one block with `get_block` for each unique event, one
time for each sequence), then combines them over the blocks of `seq_index.sequence_index`
with numpy, instead of reading every block with `get_block`. Thus its cost grows with the
number of unique events and the number of blocks, but it makes no pypulseq call for each
block. `gradient_peaks` also reads the blocks that a window edge cuts.

The peak slew rate is the largest of two kinds of value: the slope of each straight segment
of each gradient event, and the step at each block junction divided by the gradient raster
of the sequence, `seq.grad_raster_time` (the
`GradientRasterTime` that the file declares), not the raster of `seq.system`. The segment slopes
use the times of the file, and `Sequence.add_block` checked this step against the raster that
built the file. The step uses 0 for a block with no event on the axis, and 0 before the first
block. A step at a junction is a change of the gradient within one raster time on the
scanner, so it is a slew like the slope of a segment. A junction step is legal in Pulseq
(`Sequence.add_block` accepts one up to `max_slew * grad_raster_time`), so a sequence can
have its largest slew there.

The time of a junction step is the time of the first point of the block's event on the axis:
the block start plus the delay of the event. It is the block start for a block with no event
on the axis. An event with a delay and a first value that is not 0 has its step from 0 at the
end of the delay. A junction step is in a range `[lo, hi]` when its time `t` has
`lo <= t < hi`.

`block_gradient_values` gives the same measurements for each block of the whole file, in play
order, instead of the one largest value for each axis that `gradient_peaks` gives. It is for a
caller that needs each place where a value is above a limit. `gradient_peaks` does not call it.

Both public functions keep their results for the sequence object (`_kept.kept_results`):
`gradient_peaks` for `window=None`, and `block_gradient_values`. The per-event values
(`_EventData`) are kept too, with the values over the blocks that a window needs (`_BlockData`),
so a call of `gradient_peaks` with a window uses them. A result with a window is not kept,
because a caller can ask for many windows. The kept results are built again after `add_block`, after a new read of a file into the object, and after a change
of `seq.grad_raster_time` (the rule of `_kept`). A block replaced in place is not seen
(`seq_index.sequence_index`). Each kept result is read-only, because all callers share it.
"""

import math
import weakref
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pypulseq as pp

from ._equality import FrozenDict, fields_equal
from ._events import EventPoints, event_points
from ._kept import _Entry, kept_results
from ._validate import real
from .extensions import refuse_rotations
from .seq_index import (
    NO_GRADIENTS,
    NO_GRADIENTS_IN_WINDOW,
    SequenceIndex,
    block_cache_off,
    sequence_index,
)
from .seq_utils import AXES, TIME_TOLERANCE, gradient_points


@dataclass(frozen=True)
class AxisResult:
    """The peak values for one logical axis, over a time range.

    `peak_block` and `slew_block` are the block ID (`seq_index.SequenceIndex.block_id`)
    where the peak amplitude, respectively the peak slew, was found. For the slew, this is
    the block after the junction when the peak slew is a junction step (see the module
    docstring), otherwise the block whose event has the segment. `peak_time_s` is the time of
    the peak, and `slew_time_s` the start of the steepest segment (the start of the range
    when a range edge cuts that segment), or the time of the junction for a junction step (the
    block start plus the delay of the block's event on the axis, see the module docstring);
    both are in seconds from the sequence start. When several blocks reach the same largest
    value, the credited block is the first of them in play order, and the time is the first
    time in that block where the value is reached (a junction step is before every segment
    of its block). A largest value of 0 credits no block (None) and has the time 0.0.
    `rms_hz_per_m` is the RMS amplitude over the range that `GradientPeaks.range_s` gives,
    not over the whole sequence when a window is used.
    """

    peak_hz_per_m: float
    peak_time_s: float
    peak_block: int | None
    max_slew_hz_per_m_per_s: float
    slew_time_s: float
    slew_block: int | None
    rms_hz_per_m: float


@dataclass(frozen=True)
class GradientPeaks:
    """The result of `gradient_peaks`.

    `reason` is None when the range has at least one gradient event on some axis. Otherwise
    it is `seq_index.NO_GRADIENTS` (`window` was None) or `seq_index.NO_GRADIENTS_IN_WINDOW`
    (`window` was given), and every numeric field is its zero value, except
    `whole_rms_hz_per_m`, which is the RMS of the whole file when `window` is given. The
    zero value is 0.0 for an amplitude, slew or RMS field, and 0.0 for a time field; every
    block field (`AxisResult.peak_block`, `AxisResult.slew_block`, `vector_peak_block`) is
    None. `range_s` still holds the range that was used.

    `vector_peak_hz_per_m` is the largest magnitude of the three-axis gradient vector over the
    range, `vector_peak_time_s` is the first time in the range where it is reached, and
    `vector_peak_block` is the block ID of the block that holds that time, by the rule of
    `AxisResult` (0.0 and None when the peak is 0). There is no vector slew field. The RMS of
    the vector magnitude is the square root of the sum of the squares of the three axis RMS
    values, because the mean of |G|² is the sum of the three axis means of G².

    `whole_rms_hz_per_m` is the RMS amplitude of each axis (Hz/m) over the whole sequence,
    computed in the same call that computes `axes`, so that a caller that wants both the
    window's values and the whole file's RMS needs only one call. It is None when `window` was
    None (then `axes`' own RMS already is the whole file's).

    `axes` and `whole_rms_hz_per_m` are `_equality.FrozenDict`s (read-only dicts): all callers
    of a result share it, so a change of a dict would change it for all of them.
    """

    reason: str | None
    range_s: tuple[float, float]
    axes: dict[str, AxisResult]  # a FrozenDict
    vector_peak_hz_per_m: float
    vector_peak_time_s: float
    vector_peak_block: int | None
    whole_rms_hz_per_m: dict[str, float] | None = None  # a FrozenDict


@dataclass(frozen=True, eq=False)
class BlockGradientValues:
    """The gradient values of each block of a sequence, from `block_gradient_values`.

    Each array has one entry for each block, in play order (`seq_index.SequenceIndex`); N is
    the number of blocks. `block_id` is the block ID and `start_s` the start of the block in
    seconds from the sequence start. The five dicts have the keys "x", "y" and "z", and each
    value is a float array of length N. For an axis that has no event in a block, the peak and
    the slew are 0 and their times are `start_s`; the junction step is the step from the last
    value of the previous block to 0, which is not 0 when the previous block ends at a value
    that is not 0.

    `peak_hz_per_m` is the largest absolute amplitude of the block's event on the axis, and
    `peak_time_s` its time. `slew_hz_per_m_per_s` is the largest slope of a straight segment of
    that event, and `slew_time_s` the start of that segment. `junction_hz_per_m_per_s` is the
    step at the start of the block, `|last value of the previous block - first value of this
    block|` divided by `seq.grad_raster_time`, as the module docstring describes it. For the
    first block it is the step from 0 to the first value of the block, which is not 0 when
    the first event starts at a value that is not 0. Its time is `start_s` plus the delay of the
    block's event on the axis (`start_s` for a block with no event on the axis); this class has
    no field for it.
    `vector_peak_hz_per_m` is the largest magnitude of the three-axis vector in the block, and
    `vector_peak_time_s` the first time in the block where it is reached (0 and `start_s` for
    a block without gradients).

    The maximum of each amplitude array over the blocks is the value that `gradient_peaks`
    gives for the whole file. Its slew is the larger of the maximum of `slew_hz_per_m_per_s`
    and the maximum of `junction_hz_per_m_per_s`. The first block with that value is its
    credited block, and for the slew the junction step of a block comes before the segments
    of that block.

    Each array is read-only (`writeable` is False) and is its own array, not a view of the
    index that `sequence_index` keeps. Each of the five dicts is a `_equality.FrozenDict`
    (a read-only dict). A caller that needs a writable array makes a copy. Two results are
    equal when each field is equal (`_equality.values_equal`), for example the results of
    two reads of one file. A result is not hashable.
    """

    block_id: np.ndarray
    start_s: np.ndarray
    peak_hz_per_m: dict[str, np.ndarray]
    peak_time_s: dict[str, np.ndarray]
    slew_hz_per_m_per_s: dict[str, np.ndarray]
    slew_time_s: dict[str, np.ndarray]
    junction_hz_per_m_per_s: dict[str, np.ndarray]
    vector_peak_hz_per_m: np.ndarray
    vector_peak_time_s: np.ndarray

    __eq__ = fields_equal
    __hash__ = None  # type: ignore[assignment]


def _clip_polyline(
    t: np.ndarray, amp: np.ndarray, lo: float, hi: float
) -> tuple[np.ndarray, np.ndarray]:
    """The points of the piecewise-linear `(t, amp)` polyline that lie in `[lo, hi]`,
    with a point added at `lo` and/or `hi` (linearly interpolated) when the polyline
    extends past that edge. Empty when the polyline does not overlap `[lo, hi]`."""
    if t[-1] <= lo or t[0] >= hi:
        return np.array([]), np.array([])
    mask = (t >= lo) & (t <= hi)
    t_out, amp_out = t[mask], amp[mask]
    if lo > t[0]:
        t_out = np.concatenate(([lo], t_out))
        amp_out = np.concatenate(([np.interp(lo, t, amp)], amp_out))
    if hi < t[-1]:
        t_out = np.concatenate((t_out, [hi]))
        amp_out = np.concatenate((amp_out, [np.interp(hi, t, amp)]))
    return t_out, amp_out


def _vector_peak_in_block(
    axis_points: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[float, float]:
    """The time and the |G| value of the largest three-axis vector magnitude, evaluated at the
    union of the breakpoints of the axes that have a piece in `axis_points` (a subset of
    `AXES`, each `(t, amp)`, all sharing one time origin). An axis with no piece here is zero
    for the whole range. |G| is convex on a stretch where every axis is linear, so its maximum
    is at one of these breakpoints."""
    times = np.unique(np.concatenate([t for t, _ in axis_points.values()]))
    sum_sq = np.zeros_like(times)
    for axis in AXES:
        piece = axis_points.get(axis)
        if piece is None:
            continue
        t, amp = piece
        values = np.interp(times, t, amp, left=0.0, right=0.0)
        sum_sq = sum_sq + values * values
    magnitude = np.sqrt(sum_sq)
    i = int(np.argmax(magnitude))
    return float(times[i]), float(magnitude[i])


class _PolylineValues(NamedTuple):
    """The values of one polyline, from `_polyline_values`."""

    peak: float  # the largest |amplitude| of the points
    peak_time: float  # the time of the first point with that value
    slew: float  # the largest |slope| of a segment of `TIME_TOLERANCE` or more (0.0 if none)
    slew_time: float  # the start time of the first such segment (0.0 if none)
    integral: float  # the integral of amplitude^2 dt over the polyline


def _polyline_values(t: np.ndarray, amp: np.ndarray) -> _PolylineValues:
    """The peak, the slew and the integral of the piecewise-linear polyline `(t, amp)`. The
    first point wins a tie of the peak, and the first segment wins a tie of the slew. A segment
    shorter than `TIME_TOLERANCE` has no slope. Both `_event_values` (a whole event) and the
    edge-block loop of `_range_result` (an event clipped to the range) use it."""
    abs_amp = np.abs(amp)
    pk = int(np.argmax(abs_amp))
    dt = np.diff(t)
    a, b = amp[:-1], amp[1:]
    integral = float(np.sum(dt * (a * a + a * b + b * b) / 3.0))
    slew, slew_time = 0.0, 0.0
    valid = dt >= TIME_TOLERANCE
    if np.any(valid):
        seg_slew = np.abs((b - a)[valid] / dt[valid])
        j = int(np.argmax(seg_slew))
        slew = float(seg_slew[j])
        slew_time = float(t[:-1][valid][j])
    return _PolylineValues(float(abs_amp[pk]), float(t[pk]), slew, slew_time, integral)


@dataclass
class _EventData:
    """The per-unique-gradient-event values that `gradient_peaks` needs, indexed by the dense
    event index minus 1 (`seq_index.SequenceIndex.gx`/`gy`/`gz`, 0 = no event). All amplitudes
    are in Hz/m, slew in Hz/m/s, and times in seconds from the start of the block that plays the
    event (`seq_utils.gradient_points(g, 0.0)`: the event's own delay is included, the block's
    start is not)."""

    peak: np.ndarray  # K: the largest |amplitude| of the event's own corner points
    peak_offset: np.ndarray  # K: the time (from the block start) of that peak
    slew: np.ndarray  # K: the largest slope between neighbouring corner points
    slew_offset: np.ndarray  # K: the start time (from the block start) of the first such segment
    first: np.ndarray  # K: the value of the event's first corner point
    first_offset: np.ndarray  # K: the time (from the block start) of that point: the delay
    last: np.ndarray  # K: the value of the event's last corner point
    integral: np.ndarray  # K: the integral of amplitude^2 dt over the whole event
    t_rel: list[np.ndarray]  # K arrays: the corner point times, from the block start
    amp: list[np.ndarray]  # K arrays: the corner point amplitudes


def _event_values(points: EventPoints) -> _EventData:
    """`_EventData` for every unique gradient event of `points` (`_events.event_points`, which
    reads each event one time). The corner times of event `k` are `points.delay[k] +
    points.offsets[...]`, the same values as `seq_utils.gradient_points(g, 0.0)`."""
    k = points.delay.size
    peak = np.zeros(k)
    peak_offset = np.zeros(k)
    slew = np.zeros(k)
    slew_offset = np.zeros(k)
    first = np.zeros(k)
    first_offset = np.zeros(k)
    last = np.zeros(k)
    integral = np.zeros(k)
    t_rel: list[np.ndarray] = [np.array([])] * k
    amp_list: list[np.ndarray] = [np.array([])] * k

    for i, (start, count) in enumerate(zip(points.at.tolist(), points.count.tolist(), strict=True)):
        t = points.delay[i] + points.offsets[start : start + count]
        amp = points.amp[start : start + count]
        values = _polyline_values(t, amp)
        peak[i] = values.peak
        peak_offset[i] = values.peak_time
        first[i] = float(amp[0])
        first_offset[i] = float(t[0])
        last[i] = float(amp[-1])
        integral[i] = values.integral
        slew[i] = values.slew
        slew_offset[i] = values.slew_time

        t_rel[i] = t
        amp_list[i] = amp

    return _EventData(
        peak, peak_offset, slew, slew_offset, first, first_offset, last, integral, t_rel, amp_list
    )


# For each sequence object: the kept results (`_kept.kept_results`), under the keys "events" (the
# `_EventData`), "block_data" (the `_BlockData`), "peaks" (the `GradientPeaks` of `window=None`)
# and "block_values" (the `BlockGradientValues`).
_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


def _kept_event_values(seq: pp.Sequence, kept: dict) -> _EventData:
    """The `_EventData` of `seq`, built one time for the kept results `kept` of `seq`."""
    if "events" not in kept:
        kept["events"] = _event_values(event_points(seq))
    return kept["events"]


def _event_column(col: np.ndarray, values: np.ndarray) -> np.ndarray:
    """For each block, the entry of `values` (K entries, one for each unique gradient event) of
    the block's event on one axis, and 0.0 for a block without an event on it. `col` is the
    dense event column of that axis (`seq_index.SequenceIndex.gx`/`gy`/`gz`, 0 = no event)."""
    return np.concatenate(([0.0], values))[col]


def _junction_steps(col: np.ndarray, ev: _EventData, grad_raster: float) -> np.ndarray:
    """For each block, the step at its incoming junction on one axis, in Hz/m/s:
    |last value of the previous block - first value of this block| / `grad_raster`. The value
    of a block without an event on the axis is 0.0, and the value before the first block is
    0.0. `col` is the dense event column of the axis. Both `_range_result` and
    `block_gradient_values` use it."""
    first_vals = _event_column(col, ev.first)
    last_vals = _event_column(col, ev.last)
    prev_last = np.concatenate(([0.0], last_vals[:-1]))
    return np.abs(prev_last - first_vals) / grad_raster


def _junction_times(col: np.ndarray, ev: _EventData, start_s: np.ndarray) -> np.ndarray:
    """For each block, the time of its incoming junction step on one axis, in seconds from the
    sequence start: the block start plus the delay of the block's event on the axis (the time of
    its first point), and the block start for a block without an event on the axis. `col` is the
    dense event column of the axis. `_range_result` uses it."""
    return start_s + _event_column(col, ev.first_offset)


def _distinct_triples(
    gx: np.ndarray, gy: np.ndarray, gz: np.ndarray, num_events: int
) -> tuple[np.ndarray, np.ndarray]:
    """The distinct triples `(gx, gy, gz)` of dense event indexes (0 = no event) of a set of
    blocks, as `(first, inverse)`: `first[t]` is the first position in `gx` of triple number
    `t`, and `inverse[i]` is the number of the triple at position `i`. `num_events` is the
    number of unique gradient events (the largest index).

    The triple is one number in two steps, `(rank of (gx, gy)) * base + gz`, so that the number
    stays far from the int64 limit: `(gx * base + gy) * base + gz` can wrap around above about
    2.6 million unique events. Both `_range_result` and `_block_vector_peaks` use it."""
    base = num_events + 1
    gx, gy, gz = (np.asarray(g, dtype=np.int64) for g in (gx, gy, gz))
    _, pair = np.unique(gx * base + gy, return_inverse=True)
    _, first, inverse = np.unique(
        pair.astype(np.int64) * base + gz, return_index=True, return_inverse=True
    )
    return first, inverse


def _triple_vector_peak(
    ev: _EventData, gx_id: int, gy_id: int, gz_id: int
) -> tuple[float, float] | None:
    """`_vector_peak_in_block` for one triple of dense gradient event indexes (0 = no event on
    that axis), from the events' own corner points (`ev.t_rel`, `ev.amp`), relative to the block
    start. None when no axis of the triple has an event."""
    ids = {"x": gx_id, "y": gy_id, "z": gz_id}
    axis_points = {}
    for axis, eid in ids.items():
        if eid == 0:
            continue
        axis_points[axis] = (ev.t_rel[eid - 1], ev.amp[eid - 1])
    if not axis_points:
        return None
    return _vector_peak_in_block(axis_points)


def _whole_file_rms(
    index: SequenceIndex, ev: _EventData, total_duration: float
) -> dict[str, float]:
    """The RMS amplitude (Hz/m) of each axis over the whole sequence, from the per-event
    integrals and how many times each event plays on each axis (`numpy.bincount`)."""
    axis_cols = {"x": index.gx, "y": index.gy, "z": index.gz}
    k = ev.integral.size
    result = {}
    for axis, col in axis_cols.items():
        if k == 0 or total_duration <= 0.0:
            result[axis] = 0.0
            continue
        counts = np.bincount(col, minlength=k + 1)[1:]
        rms_sum = float(np.sum(counts * ev.integral))
        result[axis] = math.sqrt(rms_sum / total_duration)
    return result


@dataclass
class _BlockData:
    """The values over all the blocks that `_range_result` and `gradient_peaks` take from for each
    window, built one time for each sequence object (`_kept_block_data`), so that a window does
    not calculate them again. The arrays are read-only and the dicts are `FrozenDict`s, because
    all callers share them."""

    end_s: np.ndarray  # N: the end of each block, `start_s + duration_s`
    junction_steps: dict[str, np.ndarray]  # for each axis, `_junction_steps` over all the blocks
    junction_times: dict[str, np.ndarray]  # for each axis, `_junction_times` over all the blocks
    whole_rms: dict[str, float]  # for each axis, `_whole_file_rms`


def _kept_block_data(
    seq: pp.Sequence, kept: dict, index: SequenceIndex, ev: _EventData
) -> _BlockData:
    """The `_BlockData` of `seq`, built one time for the kept results `kept` of `seq`. `index` and
    `ev` are the index and the `_EventData` of `seq`."""
    if "block_data" not in kept:
        grad_raster = seq.grad_raster_time
        axis_cols = {"x": index.gx, "y": index.gy, "z": index.gz}
        end_s = index.start_s + index.duration_s
        steps = {axis: _junction_steps(col, ev, grad_raster) for axis, col in axis_cols.items()}
        times = {axis: _junction_times(col, ev, index.start_s) for axis, col in axis_cols.items()}
        for array in (end_s, *steps.values(), *times.values()):
            array.flags.writeable = False
        kept["block_data"] = _BlockData(
            end_s,
            FrozenDict(steps),
            FrozenDict(times),
            FrozenDict(_whole_file_rms(index, ev, index.end_s)),
        )
    return kept["block_data"]


def _credit_goes_to(value: float, play: int, best: float, best_play: int | None) -> bool:
    """Whether a candidate `value` at play index `play` takes the credit from the current
    `best` at `best_play`: it is larger, or equal (and not 0) at a smaller play index. This
    gives the result of a single pass over the blocks in play order that keeps a value only when
    a later one is strictly larger, whatever order the candidates come in. A value of 0 never
    takes the credit, because `best` starts at 0.0 with `best_play` None."""
    if value > best:
        return True
    return value == best and best_play is not None and play < best_play


def _axis_slice_stats(
    col_slice: np.ndarray, ev: _EventData, i0: int, start_s: np.ndarray
) -> dict | None:
    """The peak amplitude, the peak slew (segments only) and the RMS sum for one axis, from the
    per-event values, restricted to the contiguous play-index slice `col_slice = axis_col[i0:i1]`
    (every block of the slice fully inside the range). None when the axis has no event there.

    The credited block for the peak (respectively the slew) is the smallest play index in the
    slice whose event reaches the largest value (`_credit_goes_to`); a largest value of 0
    credits no block (`None`).
    """
    k = ev.peak.size
    if k == 0 or col_slice.size == 0:
        return None
    counts = np.bincount(col_slice, minlength=k + 1)[1:]
    present = counts > 0
    if not np.any(present):
        return None

    peak_vals = np.where(present, ev.peak, -np.inf)
    slew_vals = np.where(present, ev.slew, -np.inf)
    max_peak = float(np.max(peak_vals))
    max_slew = float(np.max(slew_vals))
    peak_events = np.flatnonzero(peak_vals == max_peak) + 1
    slew_events = np.flatnonzero(slew_vals == max_slew) + 1
    peak_play, peak_time, slew_play, slew_time = None, 0.0, None, 0.0
    if max_peak > 0.0:
        peak_local = int(np.argmax(np.isin(col_slice, peak_events)))
        peak_play = i0 + peak_local
        peak_time = float(start_s[peak_play] + ev.peak_offset[int(col_slice[peak_local]) - 1])
    if max_slew > 0.0:
        slew_local = int(np.argmax(np.isin(col_slice, slew_events)))
        slew_play = i0 + slew_local
        slew_time = float(start_s[slew_play] + ev.slew_offset[int(col_slice[slew_local]) - 1])

    return {
        "peak": max_peak,
        "peak_play": peak_play,
        "peak_time": peak_time,
        "slew": max_slew,
        "slew_play": slew_play,
        "slew_time": slew_time,
        "rms_sum": float(np.sum(counts * ev.integral)),
    }


def _range_result(
    seq: pp.Sequence,
    index: SequenceIndex,
    ev: _EventData,
    blocks: _BlockData,
    lo: float,
    hi: float,
) -> tuple[dict[str, AxisResult], float, float, int | None, bool]:
    """`axes`, `vector_peak_hz_per_m`, `vector_peak_time_s`, `vector_peak_block` and whether any
    axis has an event, for the range `[lo, hi]`.

    The blocks of the range are the play indexes `[a, b)` that `np.searchsorted` finds in the
    start and the end of the blocks (both are non-decreasing, because a block starts where the
    one before it ends): `a` is the first block whose end is after `lo`, and `b` is the first
    block whose start is not before `hi`. A block of zero duration at `lo` or at `hi`, or
    outside the range, is not in `[a, b)`. Every mask, the selection of the junction steps and
    the slices are of `[a, b)` only, and index the arrays of `blocks` (`_BlockData`, kept for the
    sequence), so the cost of a range is the number of blocks in it, not the number of blocks of
    the file.

    Blocks fully inside the range use the per-event values (`_axis_slice_stats`,
    `_triple_vector_peak`), over the contiguous play-index range that
    `seq_index.SequenceIndex.start_s` gives (blocks are in time order, so the "fully inside"
    blocks are one contiguous run). The few blocks that a range edge cuts (at most two: a
    block of zero duration at a range edge is not in `[a, b)`) are read with `get_block` and
    clipped exactly as the oracle (`tests/oracles/grad_peaks.py`) clips every block. Passing
    `lo=0.0, hi=index.end_s` (`window=None`) makes every block of non-zero duration fully
    inside (a block of zero duration at 0 or at the end is not in `[a, b)`, and it has no
    gradient), so this same code computes the whole-file result too.

    The slice is computed before the edge blocks, and its triples are not in play order, so
    each candidate for a credit (an edge block, a triple of the slice) is compared with
    `_credit_goes_to`, which gives the result of a single pass over the blocks in play order.
    The junction steps follow the same rule. A range with `hi <= lo` has no event.
    """
    n = index.num_blocks
    start_s = index.start_s
    axis_cols = {"x": index.gx, "y": index.gy, "z": index.gz}
    state = {
        axis: {
            "peak": 0.0,
            "peak_play": None,
            "peak_time": 0.0,
            "slew": 0.0,
            "slew_play": None,
            "slew_time": 0.0,
            "rms_sum": 0.0,
            "has_event": False,
        }
        for axis in AXES
    }

    if n == 0 or not lo < hi:
        axes = {axis: AxisResult(0.0, 0.0, None, 0.0, 0.0, None, 0.0) for axis in AXES}
        return axes, 0.0, 0.0, None, False

    end_s = blocks.end_s
    a = int(np.searchsorted(end_s, lo, side="right"))
    b = int(np.searchsorted(start_s, hi, side="left"))
    # The blocks of the range, `[a, b)`; the masks are of these blocks only, so `fully_inside[j]`
    # is of the play index `a + j`. `b < a` is an empty range, which `a:b` slices as empty.
    fully_inside = (start_s[a:b] >= lo) & (end_s[a:b] <= hi)
    inside_idx = np.flatnonzero(fully_inside)
    i0, i1 = (a + int(inside_idx[0]), a + int(inside_idx[-1]) + 1) if inside_idx.size else (0, 0)

    if i1 > i0:
        for axis in AXES:
            stats = _axis_slice_stats(axis_cols[axis][i0:i1], ev, i0, start_s)
            if stats is not None:
                state[axis].update(stats)
                state[axis]["has_event"] = True

    # The blocks a range edge cuts: read individually and clipped, as the oracle does.
    edge_positions = a + np.flatnonzero(~fully_inside)
    axis_points_by_play: dict[int, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    if edge_positions.size:
        with block_cache_off(seq):
            for play in edge_positions.tolist():
                block = seq.get_block(int(index.block_id[play]))
                block_start = float(start_s[play])
                axis_points: dict[str, tuple[np.ndarray, np.ndarray]] = {}
                for axis in AXES:
                    g = getattr(block, f"g{axis}", None)
                    if g is None:
                        continue
                    t, amp = gradient_points(g, block_start)
                    t_c, amp_c = _clip_polyline(t, amp, lo, hi)
                    if t_c.size < 2:
                        continue
                    axis_points[axis] = (t_c, amp_c)
                    st = state[axis]
                    st["has_event"] = True
                    values = _polyline_values(t_c, amp_c)
                    if _credit_goes_to(values.peak, play, st["peak"], st["peak_play"]):
                        st["peak"], st["peak_time"], st["peak_play"] = (
                            values.peak,
                            values.peak_time,
                            play,
                        )
                    st["rms_sum"] += values.integral
                    # A clipped event with no segment of `TIME_TOLERANCE` or more has the
                    # slew 0.0, which `_credit_goes_to` never credits.
                    if _credit_goes_to(values.slew, play, st["slew"], st["slew_play"]):
                        st["slew"], st["slew_play"], st["slew_time"] = (
                            values.slew,
                            play,
                            values.slew_time,
                        )
                if axis_points:
                    axis_points_by_play[play] = axis_points

    # The vector peak of |G|: the distinct triples of the "fully inside" range, one
    # _triple_vector_peak call for each, plus the edge blocks' own
    # clipped points, exactly as the oracle computes them.
    vector_peak_hz, vector_peak_time, vector_peak_play = 0.0, 0.0, None
    k = ev.peak.size
    if i1 > i0 and k:
        gx_s = index.gx[i0:i1].astype(np.int64)
        gy_s = index.gy[i0:i1].astype(np.int64)
        gz_s = index.gz[i0:i1].astype(np.int64)
        selected = np.flatnonzero((gx_s > 0) | (gy_s > 0) | (gz_s > 0))
        if selected.size:
            first, _ = _distinct_triples(gx_s[selected], gy_s[selected], gz_s[selected], k)
            for local in selected[first].tolist():
                triple = _triple_vector_peak(
                    ev, int(gx_s[local]), int(gy_s[local]), int(gz_s[local])
                )
                if triple is None:
                    continue
                rel_t, mag = triple
                # `first` is in the order of the triples, not of play.
                if _credit_goes_to(mag, i0 + local, vector_peak_hz, vector_peak_play):
                    vector_peak_hz, vector_peak_play = mag, i0 + local
                    vector_peak_time = float(start_s[i0 + local]) + rel_t

    for play, axis_points in axis_points_by_play.items():
        block_time, block_peak = _vector_peak_in_block(axis_points)
        if _credit_goes_to(block_peak, play, vector_peak_hz, vector_peak_play):
            vector_peak_hz, vector_peak_time, vector_peak_play = block_peak, block_time, play

    # The junction steps (see the module docstring): for each axis, the step at the
    # incoming junction of each block of the range whose junction time is in `[lo, hi)`
    # (0 before the very first block of the file, or where either side has no event on
    # the axis). The time is the block start plus the delay of the block's event on the
    # axis. The junction of a block that the range start cuts, before the first point of
    # its event, is before the range, so it is not used. A junction at the range end
    # belongs to the block after it, which is not processed.
    axes: dict[str, AxisResult] = {}
    has_event_any = False
    for axis in AXES:
        steps = blocks.junction_steps[axis]
        times = blocks.junction_times[axis]
        range_times = times[a:b]
        junction_in_range = (range_times >= lo) & (range_times < hi)

        junction_max, junction_play = 0.0, None
        if np.any(junction_in_range):
            masked = np.where(junction_in_range, steps[a:b], -np.inf)
            j = int(np.argmax(masked))
            candidate = float(masked[j])
            # Only a strictly positive step is a real junction, matching the segment
            # search below (which starts its running max at 0.0 too): a step of
            # exactly 0.0 everywhere (for example an axis with no event at all) must
            # stay uncredited (slew_block None).
            if candidate > junction_max:
                junction_max, junction_play = candidate, a + j

        st = state[axis]
        seg_max, seg_play = st["slew"], st["slew_play"]
        # A junction is at the first point of its block's event, before every segment of that
        # block, so it also takes the credit from a segment of equal slew in the same block.
        if junction_play is not None and (
            seg_play is None
            or junction_max > seg_max
            or (junction_max == seg_max and junction_play <= seg_play)
        ):
            final_slew, final_slew_play = junction_max, junction_play
            final_slew_time = float(times[junction_play])
        else:
            final_slew, final_slew_play, final_slew_time = seg_max, seg_play, st["slew_time"]

        # A credited junction step means a real, non-zero step was found even when no
        # segment of this axis lies inside the range (for example a window that starts
        # at the junction after a gradient event that ends at a value that is not 0):
        # that is real gradient information about the range, so it counts as "has an
        # event" too.
        has_event = st["has_event"] or final_slew_play is not None
        has_event_any = has_event_any or has_event
        rms = math.sqrt(st["rms_sum"] / (hi - lo)) if has_event else 0.0
        axes[axis] = AxisResult(
            peak_hz_per_m=st["peak"],
            peak_time_s=st["peak_time"],
            peak_block=int(index.block_id[st["peak_play"]])
            if st["peak_play"] is not None
            else None,
            max_slew_hz_per_m_per_s=final_slew,
            slew_time_s=final_slew_time,
            slew_block=(
                int(index.block_id[final_slew_play]) if final_slew_play is not None else None
            ),
            rms_hz_per_m=rms,
        )

    vector_peak_block = (
        int(index.block_id[vector_peak_play]) if vector_peak_play is not None else None
    )
    return axes, vector_peak_hz, vector_peak_time, vector_peak_block, has_event_any


def gradient_peaks(seq: pp.Sequence, *, window: tuple[float, float] | None = None) -> GradientPeaks:
    """The peak amplitude, the peak slew rate and the RMS amplitude of `seq`'s
    gradients, on each logical axis and as a three-axis vector.

    With `window=None`, the range is the whole sequence, `(0.0, total_duration)`.
    Otherwise `window` is `(start_s, end_s)` in seconds from the sequence start; it
    must have `start_s < end_s` and lie within the sequence
    (`0.0 <= start_s` and `end_s <= total_duration`, each within `TIME_TOLERANCE`).
    A `window` that is not a tuple or a list of two items raises `TypeError`, as does a
    start or an end that is a `bool` or not a real number (`_validate.real`). A start or an
    end that is NaN or an infinity, a window with no start before its end, and a window that
    is not within the sequence raise `ValueError`. A gradient piece that crosses a range edge
    is cut at the edge, with the amplitude at the edge found by linear interpolation.
    `range_s` is the window clipped to `(0.0, total_duration)`, so its start is never after its
    end: a window that lies past an end of the sequence by less than `TIME_TOLERANCE` gives a
    range of length 0, which has `reason == NO_GRADIENTS_IN_WINDOW` and zero values.
    With `window` given, `GradientPeaks.whole_rms_hz_per_m` also gives each axis's RMS
    over the whole sequence, computed in this same call.

    The result for `window=None` is kept for the sequence object, so that callers of one
    sequence calculate it one time. A result with a window is not kept, because a caller can
    ask for many windows, but it uses the kept per-event values and the kept values over the
    blocks (`_BlockData`), so its cost is the number of blocks in the window. The kept results
    are built again after `add_block`, after a new read of a file into the object, and after a
    change of `seq.grad_raster_time` (the rule of `_kept`). A block replaced in place is not seen
    (`seq_index.sequence_index`). The kept result is read-only: `axes` and
    `whole_rms_hz_per_m` are `FrozenDict`s and the result is a frozen dataclass.

    The values are in Hz/m and Hz/m/s, the units of pypulseq, with no gamma. To get T/m and
    T/m/s, divide them by the magnitude of the gamma of the target, in Hz/T (`docs/usage.md`
    section 8).

    This checks `window` first (its form, its numbers and their order), before it reads the
    sequence. Then it builds `seq_index.sequence_index(seq)`, returns the kept result for
    `window=None` when there is one, and checks the window against the length of the
    sequence. Only then does it take the per-event values (`_event_values` of
    `_events.event_points`, which uses the points of the unique gradient events and calls no
    `get_block`, built one time for each sequence) and the values over the blocks (the end of
    each block, the junction steps and times, and the RMS of the whole file, built one time for
    each sequence), and combine them with numpy over the blocks of the range. It also reads the
    few blocks that a range edge cuts with `get_block`, so its cost does not grow with the
    number of blocks of the file the way that reading every block would.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`): the numbers are of the logical axes as they are stored.
    """
    refuse_rotations(seq)

    if window is not None:
        if not isinstance(window, tuple | list) or len(window) != 2:
            raise TypeError(f"window must be a pair (start_s, end_s), not {window!r}")
        start_s = real("window start", window[0])
        end_s = real("window end", window[1])
        if not start_s < end_s:
            raise ValueError(f"window {window!r} must have a start before its end")

    index = sequence_index(seq)
    kept = kept_results(_CACHE, seq)
    if window is None and "peaks" in kept:
        return kept["peaks"]
    total_duration = index.end_s

    if window is None:
        range_s = (0.0, total_duration)
    else:
        if start_s < -TIME_TOLERANCE or end_s > total_duration + TIME_TOLERANCE:
            raise ValueError(
                f"window {window!r} is not within the sequence (0.0, {total_duration})"
            )
        # Clip to the sequence exactly: start_s/end_s can be off by a rounding error of
        # up to TIME_TOLERANCE and still pass the check above. Each end is clipped to
        # `[0.0, total_duration]`, so the start is never after the end.
        range_s = (
            min(max(start_s, 0.0), total_duration),
            min(max(end_s, 0.0), total_duration),
        )

    ev = _kept_event_values(seq, kept)
    blocks = _kept_block_data(seq, kept, index, ev)
    whole_rms_hz_per_m = None if window is None else blocks.whole_rms

    lo, hi = range_s
    axes, vector_peak_hz_per_m, vector_peak_time_s, vector_peak_block, has_event = _range_result(
        seq, index, ev, blocks, lo, hi
    )

    if has_event:
        reason = None
    elif window is not None:
        reason = NO_GRADIENTS_IN_WINDOW
    else:
        reason = NO_GRADIENTS

    result = GradientPeaks(
        reason=reason,
        range_s=range_s,
        axes=FrozenDict(axes),
        vector_peak_hz_per_m=vector_peak_hz_per_m,
        vector_peak_time_s=vector_peak_time_s,
        vector_peak_block=vector_peak_block,
        whole_rms_hz_per_m=whole_rms_hz_per_m,
    )
    if window is None:
        kept["peaks"] = result
    return result


def _block_vector_peaks(index: SequenceIndex, ev: _EventData) -> tuple[np.ndarray, np.ndarray]:
    """The peak of |G| of each block in Hz/m, and its time from the block start, from
    `_triple_vector_peak` one time for each distinct triple of dense event indexes
    (`_distinct_triples` over the blocks that have a gradient, mapped back to every such
    block). A block without a gradient has 0 and 0."""
    peak = np.zeros(index.num_blocks)
    offset = np.zeros(index.num_blocks)
    gx, gy, gz = (col.astype(np.int64) for col in (index.gx, index.gy, index.gz))
    selected = np.flatnonzero((gx > 0) | (gy > 0) | (gz > 0))
    if selected.size == 0:
        return peak, offset
    gx, gy, gz = gx[selected], gy[selected], gz[selected]
    first, inverse = _distinct_triples(gx, gy, gz, ev.peak.size)
    triple_peak = np.zeros(first.size)
    triple_offset = np.zeros(first.size)
    for t, local in enumerate(first.tolist()):
        triple = _triple_vector_peak(ev, int(gx[local]), int(gy[local]), int(gz[local]))
        if triple is not None:
            triple_offset[t], triple_peak[t] = triple
    peak[selected] = triple_peak[inverse]
    offset[selected] = triple_offset[inverse]
    return peak, offset


def block_gradient_values(seq: pp.Sequence) -> BlockGradientValues:
    """The gradient values of each block of `seq`, in play order (`BlockGradientValues`).

    These are the values that `gradient_peaks` takes the largest of for the whole file, kept
    for each block: the peak amplitude and the peak slew of the block's event on each logical
    axis, the junction step at the start of the block, and the peak of the three-axis vector.
    The slope and the junction step follow the rules of the module docstring.

    The values are in Hz/m and Hz/m/s, with no gamma, as for `gradient_peaks`.

    The result is kept for the sequence object, with the same rule as `gradient_peaks` for
    `window=None` (the module docstring), so a second call gives the same object. The result
    is read-only: its arrays are not writeable and its dicts are `FrozenDict`s.

    This builds `seq_index.sequence_index(seq)` and the per-event values of
    `_events.event_points` one time (`_event_values`, shared with `gradient_peaks`), then
    combines them with numpy over the blocks. It computes the peak of |G| one time for each
    distinct triple of events. It reads one block with `get_block` for each unique gradient
    event (in `_events.event_points`, one time for each sequence), and no other block.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`): the values are of the logical axes as they are stored.
    """
    refuse_rotations(seq)
    index = sequence_index(seq)
    kept = kept_results(_CACHE, seq)
    if "block_values" in kept:
        return kept["block_values"]
    ev = _kept_event_values(seq, kept)
    grad_raster = seq.grad_raster_time
    start_s = index.start_s

    peak_hz_per_m: dict[str, np.ndarray] = {}
    peak_time_s: dict[str, np.ndarray] = {}
    slew_hz_per_m_per_s: dict[str, np.ndarray] = {}
    slew_time_s: dict[str, np.ndarray] = {}
    junction_hz_per_m_per_s: dict[str, np.ndarray] = {}
    for axis, col in zip(AXES, (index.gx, index.gy, index.gz), strict=True):
        peak_hz_per_m[axis] = _event_column(col, ev.peak)
        peak_time_s[axis] = start_s + _event_column(col, ev.peak_offset)
        slew_hz_per_m_per_s[axis] = _event_column(col, ev.slew)
        slew_time_s[axis] = start_s + _event_column(col, ev.slew_offset)
        junction_hz_per_m_per_s[axis] = _junction_steps(col, ev, grad_raster)

    vector_peak_hz_per_m, vector_offset = _block_vector_peaks(index, ev)
    block_id = index.block_id.astype(np.int64)
    result_start_s = start_s.copy()
    vector_peak_time_s = start_s + vector_offset
    dicts = (peak_hz_per_m, peak_time_s, slew_hz_per_m_per_s, slew_time_s, junction_hz_per_m_per_s)
    arrays = (
        block_id, result_start_s, vector_peak_hz_per_m, vector_peak_time_s,
        *(array for values in dicts for array in values.values()),
    )  # fmt: skip
    for array in arrays:
        array.flags.writeable = False  # each is its own array, shared by all callers of the result
    result = BlockGradientValues(
        block_id=block_id,
        start_s=result_start_s,
        peak_hz_per_m=FrozenDict(peak_hz_per_m),
        peak_time_s=FrozenDict(peak_time_s),
        slew_hz_per_m_per_s=FrozenDict(slew_hz_per_m_per_s),
        slew_time_s=FrozenDict(slew_time_s),
        junction_hz_per_m_per_s=FrozenDict(junction_hz_per_m_per_s),
        vector_peak_hz_per_m=vector_peak_hz_per_m,
        vector_peak_time_s=vector_peak_time_s,
    )
    kept["block_values"] = result
    return result
