"""The peak amplitude, the peak slew rate and the RMS amplitude of a sequence's gradients.

The gradient of each logical axis (x, y, z) is the polyline of the model of MATLAB Pulseq
(`docs/implementation.md`, "The gradient waveform"). This module computes the values of that polyline
for each axis and for the three-axis vector, over a time range. It does not compare them with
limits: a caller that has the hardware limits compares the values with them.

The axes are the logical sequence axes, not the physical gradient axes of a scanner. The
scanner rotates the logical axes onto the physical ones for the prescribed orientation, so on
an oblique slice one physical axis can see amplitude up to the vector peak,
`GradientPeaks.vector_peak_hz_per_m`, even when no single logical axis is near the limit.

The model of one axis. `dt` is `seq.grad_raster_time` (the `GradientRasterTime` that the file
declares), not the raster of `seq.system`. The points of each gradient event are those of
`seq_utils.gradient_offsets`, at the times `(block start + delay) + offset`, as the Pulseq
specification treats them: the event is piecewise linear between them. Between two consecutive
events on the axis (the blocks between them have no event on the axis), the gap is `first_time -
last_time`, with the first point of the later event and the last point of the earlier event:

- A zero gap (at most `TIME_TOLERANCE`) has no point. When the first value is not the last
  value, it is a step at `first_time`: the value at the time of the step is the last value.
- A short gap (more than that, and at most `dt + TIME_TOLERANCE`) has no point: the gradient is
  the straight line from the last point to the first point.
- A long gap has a ramp to 0 in `dt / 2` after the earlier event when its last value is not 0,
  and a ramp from 0 in `dt / 2` before the later event when its first value is not 0. The value
  is 0 between them. This is MATLAB Pulseq's rule (`waveforms_and_times`); pypulseq's
  `waveforms()` draws a line across a long gap (pypulseq-issues 12). A value of 1e-6 Hz/m or
  less also gets its ramp.

Before the first point and after the last point of the axis the value is 0, and a first value or
a last value that is not 0 is a step at that point.

The peak is the largest absolute value at the points (a ramp or a line adds no point). The peak
slew rate is the largest of the slopes of the segments of `TIME_TOLERANCE` or more (the segments
of the events, the ramps and the lines) and of the steps, `abs(step) / dt`. A step is a change of
the gradient within one raster time on the scanner, and `Sequence.add_block` accepts one up to
`max_slew * grad_raster_time`, so a sequence can have its largest slew there. The slope of a
ramp is `2 * abs(value) / dt`. The RMS integral is the integral of the square of the polyline,
with the ramps and the lines in it. A step adds nothing. The vector peak is the largest
magnitude `sqrt(gx² + gy² + gz²)` at the union of the times of the points of the three axes,
including the ramp points, evaluated on both sides of a time (a step is in it).

Each value of a block is credited to a block, as a play index. The points and the segments of an
event are credited to the block of the event. A ramp to 0 is credited to the block of the earlier
event, a ramp from 0 to the block of the later event, and the step or the line across a zero gap
or a short gap to the block of the later event. The step before the first point is credited to
the block of the first event, and the step after the last point to the block of the last event.
The time of a segment is its start (the start of the cut when a range edge cuts it), and the time
of a step is its time. A step is in the range `[lo, hi]` when its time `t` has `lo <= t < hi`. The
block of the vector peak is the block that has its time, seen from the side where the value is
(`_vector_candidates`). Of equal values, the first in time order wins, and in one block the line
or the step into the event is before the segments of the event.

This computes the per-event values one time for each unique gradient event, from the points of
`_events.event_points` (which reads one block with `get_block` for each unique event, one time for
each sequence). It then makes the values of each block one time for each sequence (`_BlockData`):
for each axis the peak, the slew with the ramps, the junction (the step or the line into the
event) and the RMS integral of the piece of the block, with their times, and the vector peak. The
piece of a block is its event, the ramps of its event, the line into it and the step after the
last point of the axis. A window of `gradient_peaks` is then an `argmax` over the columns of the
blocks whose time range is whole in the window and a sum of their RMS integrals, plus the edge
blocks: the blocks that a window edge cuts, and a block within `dt / 2` of an edge (a ramp is
`dt / 2` outside the block of its event). It reads no block with `get_block` for a window, and
its cost is the number of blocks of the window, not the number of unique events or the number
of blocks of the file. An edge block is made from the exact polylines of the axes near it
(`_exact_edge_blocks`, from the points of `_events.event_points`). The vector peak of each block
is read from the exact polylines of the whole file (`_exact_vector_peaks`).

`block_gradient_values` gives the same measurements for each block of the whole file, in play
order, instead of the one largest value for each axis that `gradient_peaks` gives. It is for a
caller that needs each place where a value is above a limit. It gives copies of the columns of
`_BlockData` that `gradient_peaks` takes its values from. The slew of a block includes the ramps
of its event. The junction of a block is the step or the line into its event, and 0 for a long
gap and for a block with no event on the axis.

Both public functions keep their results for the sequence object (`_kept.kept_results`):
`gradient_peaks` for `window=None`, and `block_gradient_values`. The per-event values
(`_EventData`) are kept too, with the values of each block (`_BlockData`), so a call of
`gradient_peaks` with a window uses them. A result with a window is not kept, because a caller
can ask for many windows. The kept results are built again after `add_block`, after a new read of
a file into the object, and after a change of `seq.grad_raster_time` (the rule of `_kept`). A
block replaced in place is not seen (`seq_index.sequence_index`). Each kept result is read-only,
because all callers share it.
"""

import math
import weakref
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pypulseq as pp

from ._equality import FrozenDict, value_dataclass
from ._events import EventPoints, event_points
from ._kept import _Entry, kept_results
from ._validate import real
from .extensions import refuse_rotations
from .seq_index import NO_GRADIENTS, NO_GRADIENTS_IN_WINDOW, SequenceIndex, sequence_index
from .seq_utils import AXES, TIME_TOLERANCE


@dataclass(frozen=True)
class AxisResult:
    """The peak values for one logical axis, over a time range.

    `peak_block` and `slew_block` are the block ID (`seq_index.SequenceIndex.block_id`) that
    has the credit of the peak amplitude, respectively the peak slew (see the module docstring
    for the credit of each item): for the slew, the block of the event of the segment, the block
    after the gap for a step or a line across a zero gap or a short gap and for a ramp from 0,
    the block before the gap for a ramp to 0, and the block of the last event for the step after
    the last point of the axis. `peak_time_s` is the time of the peak, and `slew_time_s` the
    start of the steepest segment (the start of the range when a range edge cuts that segment),
    or the time of the step; both are in seconds from the sequence start. When several items
    reach the same largest value, the credited block is the first of them in play order, and the
    time is the first time in that block where the value is reached (the step or the line into
    the event of a block is before the segments of that block). A largest value of 0 credits no
    block (None) and has the time 0.0. `rms_hz_per_m` is the RMS amplitude over the range that
    `GradientPeaks.range_s` gives, not over the whole sequence when a window is used.
    """

    peak_hz_per_m: float
    peak_time_s: float
    peak_block: int | None
    max_slew_hz_per_m_per_s: float
    slew_time_s: float
    slew_block: int | None
    rms_hz_per_m: float


@value_dataclass
class GradientPeaks:
    """The result of `gradient_peaks`.

    `reason` is None when the range has at least one gradient event on some axis. Otherwise
    it is `seq_index.NO_GRADIENTS` (`window` was None) or `seq_index.NO_GRADIENTS_IN_WINDOW`
    (`window` was given), and every numeric field is its zero value. The
    zero value is 0.0 for an amplitude, slew or RMS field, and 0.0 for a time field; every
    block field (`AxisResult.peak_block`, `AxisResult.slew_block`, `vector_peak_block`) is
    None. `range_s` still holds the range that was used.

    `vector_peak_hz_per_m` is the largest magnitude of the three-axis gradient vector over the
    range, `vector_peak_time_s` is the first time in the range where it is reached, and
    `vector_peak_block` is the block ID of the block that has that time, seen from the side where
    the value is (the module docstring; 0.0 and None when the peak is 0). There is no vector
    slew field. The RMS of the vector magnitude is the square root of the sum of the squares of
    the three axis RMS values, because the mean of |G|² is the sum of the three axis means of G².

    `axes` is a `_equality.FrozenDict` (a read-only dict): all callers of a result share it,
    so a change of the dict would change it for all of them.

    `==` compares the values of the fields (`_equality.fields_equal`), the dicts with their keys
    in order. A `GradientPeaks` is not hashable.
    """

    reason: str | None
    range_s: tuple[float, float]
    axes: dict[str, AxisResult]  # a FrozenDict
    vector_peak_hz_per_m: float
    vector_peak_time_s: float
    vector_peak_block: int | None


@value_dataclass
class BlockGradientValues:
    """The gradient values of each block of a sequence, from `block_gradient_values`.

    Each array has one entry for each block, in play order (`seq_index.SequenceIndex`); N is
    the number of blocks. `block_id` is the block ID and `start_s` the start of the block in
    seconds from the sequence start. The five dicts have the keys "x", "y" and "z", and each
    value is a float array of length N. For an axis that has no event in a block, the peak, the
    slew and the junction are 0 and their times are `start_s`.

    `peak_hz_per_m` is the largest absolute amplitude of the block's event on the axis, and
    `peak_time_s` its time. `slew_hz_per_m_per_s` is the largest slope among the segments of that
    event and the ramps of that event, and `slew_time_s` the start of that segment. The ramps
    are the ramp from 0 before the event and the ramp to 0 after it, across a long gap (the module
    docstring); the step after the last point of the axis, when that point is before the end of
    the sequence and its value is not 0, is also in the slew of the block of the last event.
    `junction_hz_per_m_per_s` is the step into the event, `|last value of the earlier event -
    first value of this event|` divided by `seq.grad_raster_time`, across a zero gap, or the
    slope of the line into the event across a short gap, `|last value - first value|` divided by
    the gap. It is 0 for a long gap, whose ramps are in the slew, and for a block with no event on
    the axis. For the first event of the axis it is the step from 0 to its first value, which is
    not 0 when the first event starts at a value that is not 0. The time of the junction is the
    time of the first point of the event for a step, and the time of the last point of the earlier
    event for a line; this class has no field for it.
    `vector_peak_hz_per_m` is the largest magnitude of the three-axis vector at the times that
    the block has (the module docstring), and `vector_peak_time_s` the first time where it is
    reached (0 and `start_s` for a block without a value that is not 0).

    The maximum of each amplitude array over the blocks is the value that `gradient_peaks`
    gives for the whole file. Its slew is the larger of the maximum of `slew_hz_per_m_per_s`
    and the maximum of `junction_hz_per_m_per_s`. The first block with that value is its
    credited block, and for the slew the junction of a block comes before the segments of that
    block. The credited block of the vector peak is the block with the earliest
    `vector_peak_time_s` among the blocks with the largest value.

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
    shorter than `TIME_TOLERANCE` has no slope. `_event_values` uses it for a whole event."""
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
    start is not). These are the values of the event alone: the ramps and the line of the gap
    before and after it are not in them (`_axis_columns` adds them)."""

    peak: np.ndarray  # K: the largest |amplitude| of the event's own corner points
    peak_offset: np.ndarray  # K: the time (from the block start) of that peak
    slew: np.ndarray  # K: the largest slope between neighbouring corner points
    slew_offset: np.ndarray  # K: the start time (from the block start) of the first such segment
    integral: np.ndarray  # K: the integral of amplitude^2 dt over the whole event


def _event_values(points: EventPoints) -> _EventData:
    """`_EventData` for every unique gradient event of `points` (`_events.event_points`, which
    reads each event one time). The corner times of event `k` are `points.delay[k] +
    points.offsets[...]`, the same values as `seq_utils.gradient_points(g, 0.0)`."""
    k = points.delay.size
    peak = np.zeros(k)
    peak_offset = np.zeros(k)
    slew = np.zeros(k)
    slew_offset = np.zeros(k)
    integral = np.zeros(k)

    for i, (start, count) in enumerate(zip(points.at.tolist(), points.count.tolist(), strict=True)):
        t = points.delay[i] + points.offsets[start : start + count]
        amp = points.amp[start : start + count]
        values = _polyline_values(t, amp)
        peak[i] = values.peak
        peak_offset[i] = values.peak_time
        integral[i] = values.integral
        slew[i] = values.slew
        slew_offset[i] = values.slew_time

    return _EventData(peak, peak_offset, slew, slew_offset, integral)


# For each sequence object: the kept results (`_kept.kept_results`), under the keys "events" (the
# `_EventData`), "block_data" (the `_BlockData`), "peaks" (the `GradientPeaks` of `window=None`)
# and "block_values" (the `BlockGradientValues`).
_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


def _kept_event_values(seq: pp.Sequence, kept: dict) -> _EventData:
    """The `_EventData` of `seq`, built one time for the kept results `kept` of `seq`."""
    if "events" not in kept:
        kept["events"] = _event_values(event_points(seq))
    return kept["events"]


# ---- The events of one axis, and the gaps between them ----


@dataclass(frozen=True, eq=False)
class _AxisEvents:
    """The events on one axis, in play order. M is the number of blocks that have an event on
    the axis. Times are in seconds from the sequence start, computed as the oracle and the
    sample times are: `(block start + delay) + offset`."""

    pos: np.ndarray  # int64, M: the play index of the block of each event
    k: np.ndarray  # int64, M: the dense event index minus 1, into the pools of `EventPoints`
    ft: np.ndarray  # float64, M: the time of the first point of the event
    lt: np.ndarray  # float64, M: the time of the last point of the event
    first: np.ndarray  # float64, M: the value of the first point (Hz/m)
    last: np.ndarray  # float64, M: the value of the last point (Hz/m)


def _axis_events(col: np.ndarray, points: EventPoints, start_s: np.ndarray) -> _AxisEvents:
    """The `_AxisEvents` of the axis whose dense event column (`seq_index.SequenceIndex.gx`,
    `gy` or `gz`) is `col`."""
    pos = np.flatnonzero(col)
    k = col[pos].astype(np.int64) - 1
    base = start_s[pos] + points.delay[k]
    first_at = points.at[k]
    last_at = first_at + points.count[k] - 1
    return _AxisEvents(
        pos,
        k,
        base + points.offsets[first_at],
        base + points.offsets[last_at],
        points.amp[first_at],
        points.amp[last_at],
    )


@dataclass
class _AxisColumns:
    """The values of each block on one axis (N entries, one for each block). The columns that
    `block_gradient_values` gives are the first six. A block with no event on the axis has 0 in
    the values, its start in the times, and an empty piece (`piece_start` is `inf` and
    `piece_end` is `-inf`)."""

    peak: np.ndarray  # the largest |value| of the points of the block's event
    peak_time: np.ndarray  # the time of the first point with that value
    slew: np.ndarray  # the largest slope of the event and of its ramps (see `_axis_columns`)
    slew_time: np.ndarray  # the start of the first item with that slope
    junction: np.ndarray  # the step, or the slope of the line, into the event
    junction_time: np.ndarray  # its time
    rms_integral: np.ndarray  # the integral of the square of the piece of the block
    piece_start: np.ndarray  # the earliest time of the piece of the block
    piece_end: np.ndarray  # the latest time of the piece of the block


def _axis_columns(index: SequenceIndex, ev: _EventData, ae: _AxisEvents, dt: float) -> _AxisColumns:
    """The `_AxisColumns` of one axis, by the model of the module docstring, for the whole
    file: the window `[0, index.end_s]` of the oracle (a step at the last point of the axis is
    in it when that point is before the end of the sequence). `dt` is the gradient raster of
    the sequence.

    The piece of a block is its event, the line or the step into it (at its first point, or
    from the last point of the earlier event across a short gap), the ramp from 0 before it
    (after a long gap), the ramp to 0 after it (before a long gap) and the step after the last
    point of the axis. Each item is credited to this block (the module docstring). The `slew` of
    the block is the first largest of the ramp from 0, the segments of the event, and the ramp to
    0 or the last step, in this order, and the `junction` is the step or the line. A gap is zero,
    short or long by the rule of the module docstring."""
    n = index.num_blocks
    start_s = index.start_s
    c = _AxisColumns(
        np.zeros(n),
        start_s.copy(),
        np.zeros(n),
        start_s.copy(),
        np.zeros(n),
        start_s.copy(),
        np.zeros(n),
        np.full(n, np.inf),
        np.full(n, -np.inf),
    )
    m = ae.pos.size
    if m == 0:
        return c
    pos, k, ft, lt, first, last = ae.pos, ae.k, ae.ft, ae.lt, ae.first, ae.last
    half = dt / 2

    # The gap before each event. The first event has the step from 0 at its first point: it is
    # a zero gap after a point with the value 0.
    prev_last = np.concatenate(([0.0], last[:-1]))
    prev_lt = np.concatenate(([ft[0]], lt[:-1]))
    gap = ft - prev_lt
    zero = gap <= TIME_TOLERANCE
    long = gap > dt + TIME_TOLERANCE
    short = ~(zero | long)

    jump = np.abs(first - prev_last)
    junction = np.where(zero, jump / dt, np.where(short, jump / np.where(short, gap, 1.0), 0.0))
    junction_time = np.where(short, prev_lt, ft)

    # The ramps across a long gap: from 0 to the first point, and from the last point to 0.
    t_from = ft - half
    from_len = ft - t_from
    has_from = long & (first != 0.0)
    from_slope = np.where(has_from, np.abs(first) / from_len, 0.0)
    t_to = lt + half
    to_len = t_to - lt
    has_to = np.zeros(m, dtype=bool)
    has_to[:-1] = long[1:] & (last[:-1] != 0.0)
    after = np.where(has_to, np.abs(last) / to_len, 0.0)
    # The step to 0 after the last point of the axis, at that point, counts in the window
    # `[0, end]` when its time is before the end.
    final_step = bool(last[-1] != 0.0 and lt[-1] < index.end_s)
    if final_step:
        after[-1] = abs(last[-1]) / dt

    own_time = start_s[pos] + ev.slew_offset[k]
    candidates = np.stack([from_slope, ev.slew[k], after])
    candidate_times = np.stack([t_from, own_time, lt])
    which = np.argmax(candidates, axis=0)
    rows = np.arange(m)
    slew = candidates[which, rows]
    # An event with no slope of its own and no ramp has the time of its own first segment.
    which = np.where(slew > 0.0, which, 1)
    slew_time = candidate_times[which, rows]

    line = np.where(
        zero | short,
        np.maximum(gap, 0.0) * (prev_last**2 + prev_last * first + first**2) / 3.0,
        0.0,
    )
    integral = (
        ev.integral[k]
        + np.where(has_from, from_len * first**2 / 3.0, 0.0)
        + np.where(has_to, to_len * last**2 / 3.0, 0.0)
        + line
    )

    piece_start = np.where(has_from, t_from, ft)
    piece_start = np.where(zero | short, np.minimum(piece_start, prev_lt), piece_start)
    piece_end = np.where(has_to, t_to, lt)

    c.peak[pos] = ev.peak[k]
    c.peak_time[pos] = start_s[pos] + ev.peak_offset[k]
    c.slew[pos] = slew
    c.slew_time[pos] = slew_time
    c.junction[pos] = junction
    c.junction_time[pos] = junction_time
    c.rms_integral[pos] = integral
    c.piece_start[pos] = piece_start
    c.piece_end[pos] = piece_end
    return c


# ---- The exact polyline of an axis ----
#
# The code below builds the polyline of the model of the module docstring from a run of
# consecutive events of one axis, and reads the values of a window from it. It is the same
# calculation as the oracle (`tests/oracles/waveform.py`), done with numpy over the events of the
# run. The package uses it for the vector peak of each block and for the blocks that a window
# edge cuts.


class _Polyline(NamedTuple):
    """The waveform of the events of one axis: a run of consecutive events, with the ramp points
    of the long gaps between them. The point `i` has the time `t[i]`, the value `g[i]` and the
    play index `play[i]` that gets the credit of it, and a point is never before the point
    before it. The segment `s` joins the points `s` and `s + 1`, and its credit is `play[s +
    1]`. `own[s]` is True for a segment inside one event, and `step[s]` for the segment between
    two events with a zero gap (the step, not a slope).

    A step has a time, a size, the play index of its credit and `step_point`, the index of the
    point before it (-1 for the step before the first point). A step is in the arrays when its
    size is not 0."""

    t: np.ndarray
    g: np.ndarray
    play: np.ndarray
    own: np.ndarray
    step: np.ndarray
    step_time: np.ndarray
    step_size: np.ndarray
    step_play: np.ndarray
    step_point: np.ndarray


_EMPTY_POLYLINE = _Polyline(
    np.empty(0),
    np.empty(0),
    np.empty(0, dtype=np.int64),
    np.empty(0, dtype=bool),
    np.empty(0, dtype=bool),
    np.empty(0),
    np.empty(0),
    np.empty(0, dtype=np.int64),
    np.empty(0, dtype=np.int64),
)


def _build_polyline(
    ae: _AxisEvents, e0: int, e1: int, points: EventPoints, start_s: np.ndarray, dt: float
) -> _Polyline:
    """The `_Polyline` of the events `e0` to `e1` (exclusive) of `ae`. The run is closed: the
    event before `e0` and the event after `e1 - 1` are in it, when they exist, unless the run
    starts at the first event or ends at the last event of the axis. The first point of the axis
    that is not 0 has a step, and so has the last point of the axis."""
    if e1 <= e0:
        return _EMPTY_POLYLINE
    pos, k = ae.pos[e0:e1], ae.k[e0:e1]
    ft, lt, first, last = ae.ft[e0:e1], ae.lt[e0:e1], ae.first[e0:e1], ae.last[e0:e1]
    n = pos.size
    half = dt / 2
    gap = ft[1:] - lt[:-1]
    zero = gap <= TIME_TOLERANCE
    long = gap > dt + TIME_TOLERANCE
    # The ramp from 0 before an event, and the ramp to 0 after it: one point each.
    before = np.zeros(n, dtype=bool)
    before[1:] = long & (first[1:] != 0.0)
    after = np.zeros(n, dtype=bool)
    after[:-1] = long & (last[:-1] != 0.0)
    count = points.count[k]
    width = before.astype(np.int64) + count + after.astype(np.int64)
    out0 = np.cumsum(width) - width
    total = int(width.sum())

    event = np.repeat(np.arange(n), width)
    j = np.arange(total) - out0[event]
    is_before = before[event] & (j == 0)
    is_after = after[event] & (j == width[event] - 1)
    is_event_point = ~(is_before | is_after)
    pool = points.at[k][event] + j - before[event]
    base = start_s[pos] + points.delay[k]
    t = np.where(
        is_before,
        ft[event] - half,
        np.where(is_after, lt[event] + half, base[event] + points.offsets[pool * is_event_point]),
    )
    g = np.where(is_event_point, points.amp[pool * is_event_point], 0.0)
    t = np.maximum.accumulate(t)
    play = pos[event]

    own = is_event_point[:-1] & is_event_point[1:] & (event[:-1] == event[1:])
    step = np.zeros(max(total - 1, 0), dtype=bool)
    # The events after a zero gap: the first point is the point after the last point of the
    # event before it.
    joined = np.flatnonzero(zero) + 1
    step[out0[joined] - 1] = True
    differs = joined[first[joined] != last[joined - 1]]

    step_time, step_size, step_play, step_point = [], [], [], []
    if e0 == 0 and first[0] != 0.0:
        step_time.append(ft[:1])
        step_size.append(first[:1])
        step_play.append(pos[:1])
        step_point.append(np.array([-1]))
    step_time.append(ft[differs])
    step_size.append(first[differs] - last[differs - 1])
    step_play.append(pos[differs])
    step_point.append(out0[differs] - 1)
    if e1 == ae.pos.size and last[-1] != 0.0:
        step_time.append(t[-1:])
        step_size.append(-last[-1:])
        step_play.append(pos[-1:])
        step_point.append(np.array([total - 1]))
    return _Polyline(
        t,
        g,
        play,
        own,
        step,
        np.concatenate(step_time),
        np.concatenate(step_size),
        np.concatenate(step_play).astype(np.int64),
        np.concatenate(step_point).astype(np.int64),
    )


def _limit_before(t: np.ndarray, g: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The values of the polyline `(t, g)` just before the times `q`: 0 at the first point and
    outside the polyline, and at the time of a point the value of the first point at that
    time."""
    if t.size < 2:
        return np.zeros(q.shape)
    i = np.clip(np.searchsorted(t, q, side="left"), 1, t.size - 1)
    j = i - 1
    exact = t[i] == q
    span = t[i] - t[j]
    span = np.where(exact | (span <= 0.0), 1.0, span)
    value = np.where(exact, g[i], g[j] + (g[i] - g[j]) * (q - t[j]) / span)
    return np.where((q > t[0]) & (q <= t[-1]), value, 0.0)


def _limit_after(t: np.ndarray, g: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The values of the polyline `(t, g)` just after the times `q`: 0 at the last point and
    outside the polyline, and at the time of a point the value of the last point at that
    time."""
    if t.size < 2:
        return np.zeros(q.shape)
    j = np.clip(np.searchsorted(t, q, side="right") - 1, 0, t.size - 2)
    i = j + 1
    exact = t[j] == q
    span = t[i] - t[j]
    span = np.where(exact | (span <= 0.0), 1.0, span)
    value = np.where(exact, g[j], g[j] + (g[i] - g[j]) * (q - t[j]) / span)
    return np.where((q >= t[0]) & (q < t[-1]), value, 0.0)


def _sum_of_squares(values: list[np.ndarray]) -> np.ndarray:
    """The sum of the squares of the arrays `values`, with the arithmetic of Python's `sum` of
    floats (Python 3.12 adds with a running compensation). The squares are products, and the
    sum is not numpy's: two values of the vector peak that are equal up to the last bit are
    found in the same order as the oracle finds them, so a tie goes to the same time."""
    total = np.zeros(values[0].shape)
    compensation = np.zeros(values[0].shape)
    for value in values:
        square = value * value
        new = total + square
        compensation += np.where(
            np.abs(total) >= np.abs(square), (total - new) + square, (square - new) + total
        )
        total = new
    return total + compensation


def _vector_candidates(
    polys: list[_Polyline], start_s: np.ndarray, end_s: np.ndarray, lo: float, hi: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The candidates of the vector peak in the window `[lo, hi]`, in time order, as `(values,
    times, plays)`: only the candidates with a value above 0.

    A candidate is a time that is `lo`, `hi` or the time of a point of a polyline in the window,
    and a side. At a time that is not `lo`, the side "before" has the values of the polylines
    just before the time, and at a time that is not `hi` the side "after" has the values just
    after it (`_limit_before`, `_limit_after`). The value is the magnitude of the three values.
    The block of a candidate is the block that has the time on that side: the first block that
    ends at or after the time, for "before", and the last block that starts at or before the
    time, for "after", each within `TIME_TOLERANCE`. `start_s` and `end_s` are the start and
    the end of each block."""
    times = np.unique(np.concatenate([[lo, hi]] + [p.t[(p.t >= lo) & (p.t <= hi)] for p in polys]))
    before = np.sqrt(_sum_of_squares([_limit_before(p.t, p.g, times) for p in polys]))
    after = np.sqrt(_sum_of_squares([_limit_after(p.t, p.g, times) for p in polys]))
    before[times == lo] = 0.0
    after[times == hi] = 0.0
    last = start_s.size - 1
    play_before = np.minimum(np.searchsorted(end_s, times - TIME_TOLERANCE, side="left"), last)
    play_after = np.maximum(np.searchsorted(start_s, times + TIME_TOLERANCE, side="right") - 1, 0)
    values = np.stack([before, after], axis=1).ravel()
    both_times = np.repeat(times, 2)
    plays = np.stack([play_before, play_after], axis=1).ravel()
    keep = values > 0.0
    return values[keep], both_times[keep], plays[keep]


def _best_by_play(
    values: np.ndarray, times: np.ndarray, plays: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each play index that has a candidate, the largest value and the time of the first
    candidate (in the order of the arrays) that has it, as `(plays, values, times)`, sorted by
    play index."""
    if values.size == 0:
        return plays, values, times
    order = np.argsort(plays, kind="stable")
    plays, values, times = plays[order], values[order], times[order]
    starts = np.flatnonzero(np.concatenate(([True], plays[1:] != plays[:-1])))
    group = np.repeat(np.arange(starts.size), np.diff(np.append(starts, plays.size)))
    top = np.maximum.reduceat(values, starts)
    is_top = np.flatnonzero(values == top[group])
    _, first_of_group = np.unique(group[is_top], return_index=True)
    chosen = is_top[first_of_group]
    return plays[chosen], values[chosen], times[chosen]


def _exact_vector_peaks(
    index: SequenceIndex,
    points: EventPoints,
    axis_events: dict[str, _AxisEvents],
    end_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The peak of |G| of each block, and its time from the sequence start, from the candidates
    of the whole file (`_vector_candidates` with the window `[0, index.end_s]`) over the
    polylines of all the events. A block with no candidate has 0 and its start as the time."""
    peak = np.zeros(index.num_blocks)
    time = np.array(index.start_s)
    dt = points.grad_raster_time
    polys = [
        _build_polyline(ae, 0, ae.pos.size, points, index.start_s, dt)
        for ae in axis_events.values()
    ]
    values, times, plays = _vector_candidates(polys, index.start_s, end_s, 0.0, index.end_s)
    plays, values, times = _best_by_play(values, times, plays)
    peak[plays] = values
    time[plays] = times
    return peak, time


# ---- The values of each block ----


@dataclass
class _BlockData:
    """The values of each block that `gradient_peaks` and `block_gradient_values` take from,
    built one time for each sequence object (`_kept_block_data`), so that a window does not
    calculate them again and does not read the K unique events. N is the number of blocks. The
    arrays are read-only and the dicts are `FrozenDict`s, because all callers share them. The
    dicts have the keys "x", "y" and "z"."""

    end_s: np.ndarray  # N: the end of each block, `start_s + duration_s`
    peak: dict[str, np.ndarray]  # N: the largest |amplitude| of the block's event on the axis
    peak_time: dict[str, np.ndarray]  # N: the time of that peak, from the sequence start
    slew: dict[str, np.ndarray]  # N: the largest slope of the event and its ramps
    slew_time: dict[str, np.ndarray]  # N: the start of that segment, from the sequence start
    junction: dict[str, np.ndarray]  # N: the step, or the line, into the block's event
    junction_time: dict[str, np.ndarray]  # N: the time of that step or of the start of the line
    rms_integral: dict[str, np.ndarray]  # N: the integral of amplitude^2 dt of the piece of the
    # block on the axis (its event, its ramps and the line into it; 0.0 for a block with no
    # event on it)
    vector_peak: np.ndarray  # N: the largest |G| of the block (`_exact_vector_peaks`)
    vector_peak_time: np.ndarray  # N: the first time of that peak, from the sequence start
    whole_integral: dict[str, float]  # for each axis, the sum of `rms_integral`
    axis_events: dict[str, _AxisEvents]  # the events of each axis, for the exact blocks
    reach_start: np.ndarray  # N: the earliest time that the block (its pieces, its vector peak
    # range) has, from the sequence start
    reach_end: np.ndarray  # N: the latest time of the same
    start_envelope: np.ndarray  # N: the minimum of `reach_start` from the block to the last
    end_envelope: np.ndarray  # N: the maximum of `reach_end` from the first block to the block


def _kept_block_data(
    seq: pp.Sequence, kept: dict, index: SequenceIndex, points: EventPoints, ev: _EventData
) -> _BlockData:
    """The `_BlockData` of `seq`, built one time for the kept results `kept` of `seq`. `index`,
    `points` and `ev` are the index, the event points and the `_EventData` of `seq`."""
    if "block_data" not in kept:
        dt = points.grad_raster_time
        start_s = index.start_s
        end_s = start_s + index.duration_s
        axis_cols = dict(zip(AXES, (index.gx, index.gy, index.gz), strict=True))
        axis_events = {axis: _axis_events(col, points, start_s) for axis, col in axis_cols.items()}
        columns = {axis: _axis_columns(index, ev, axis_events[axis], dt) for axis in AXES}
        vector_peak, vector_peak_time = _exact_vector_peaks(index, points, axis_events, end_s)

        # The range of time of a block: its pieces, and the range in which a candidate of the
        # vector peak can be credited to it (`_vector_candidates`). The margin of that range also
        # makes a block an edge block when a window edge is next to the step after its last
        # point (a step counts for `lo <= time < hi`, and the step is at the end of the block).
        margin = 2 * TIME_TOLERANCE
        reach_start = start_s - margin
        reach_end = end_s + margin
        for axis in AXES:
            reach_start = np.minimum(reach_start, columns[axis].piece_start)
            reach_end = np.maximum(reach_end, columns[axis].piece_end)
        start_envelope = np.ascontiguousarray(np.minimum.accumulate(reach_start[::-1])[::-1])
        end_envelope = np.maximum.accumulate(reach_end)

        def column(name: str) -> dict[str, np.ndarray]:
            return {axis: getattr(columns[axis], name) for axis in AXES}

        peak, peak_time = column("peak"), column("peak_time")
        slew, slew_time = column("slew"), column("slew_time")
        junction, junction_time = column("junction"), column("junction_time")
        rms_integral = column("rms_integral")
        dicts = (peak, peak_time, slew, slew_time, junction, junction_time, rms_integral)
        arrays = (
            end_s, vector_peak, vector_peak_time, reach_start, reach_end,
            start_envelope, end_envelope,
            *(array for values in dicts for array in values.values()),
        )  # fmt: skip
        for array in arrays:
            array.flags.writeable = False
        whole_integral = {axis: float(np.sum(rms_integral[axis])) for axis in AXES}
        kept["block_data"] = _BlockData(
            end_s,
            FrozenDict(peak),
            FrozenDict(peak_time),
            FrozenDict(slew),
            FrozenDict(slew_time),
            FrozenDict(junction),
            FrozenDict(junction_time),
            FrozenDict(rms_integral),
            vector_peak,
            vector_peak_time,
            FrozenDict(whole_integral),
            FrozenDict(axis_events),
            reach_start,
            reach_end,
            start_envelope,
            end_envelope,
        )
    return kept["block_data"]


# ---- The values of a range ----


def _credit_goes_to(value: float, play: int, best: float, best_play: int | None) -> bool:
    """Whether a candidate `value` at play index `play` takes the credit from the current
    `best` at `best_play`: it is larger, or equal (and not 0) at a smaller play index. This
    gives the result of a single pass over the blocks in play order that keeps a value only when
    a later one is strictly larger, whatever order the candidates come in. A value of 0 never
    takes the credit, because `best` starts at 0.0 with `best_play` None."""
    if value > best:
        return True
    return value == best and best_play is not None and play < best_play


def _first_largest(column: np.ndarray, i0: int, i1: int) -> tuple[float, int | None]:
    """The largest value of `column[i0:i1]` (not empty) and the first play index that has it,
    the credit rule of `_credit_goes_to` over the slice. A largest value of 0 credits no block:
    it is `(0.0, None)`."""
    j = int(np.argmax(column[i0:i1]))
    value = float(column[i0 + j])
    if value > 0.0:
        return value, i0 + j
    return 0.0, None


class _Best:
    """The largest value so far, with its time and the play index that has the credit
    (`_credit_goes_to`). With `by_time`, the credit of an equal value goes to the earlier time
    (and, at one time, to the smaller play index), not to the smaller play index: the vector
    peak is credited to the block that has its time within `TIME_TOLERANCE`, so a later block
    can have an earlier time."""

    __slots__ = ("by_time", "play", "time", "value")

    def __init__(self, by_time: bool = False) -> None:
        self.by_time = by_time
        self.value = 0.0
        self.time = 0.0
        self.play: int | None = None

    def offer(self, value: float, time: float, play: int | None) -> None:
        if play is None:
            return
        if self.by_time:
            takes = value > self.value or (
                value == self.value
                and self.play is not None
                and (time, play) < (self.time, self.play)
            )
        else:
            takes = _credit_goes_to(value, play, self.value, self.play)
        if takes:
            self.value, self.time, self.play = value, time, play


class _AxisState:
    """The values of one axis over a range, while the blocks of the range are added."""

    __slots__ = ("has_event", "peak", "rms_sum", "slew")

    def __init__(self) -> None:
        self.peak = _Best()
        self.slew = _Best()
        self.rms_sum = 0.0
        self.has_event = False


def _evaluate_axis(
    poly: _Polyline, dt: float, lo: float, hi: float, play_lo: int, play_hi: int
) -> tuple[_AxisState, bool]:
    """The values of the window `[lo, hi]` of the polyline `poly` that are credited to the play
    indexes `play_lo` to `play_hi` (exclusive), with the rules of the oracle: the peak from the
    end points of the segments of positive length in the window, a segment that an edge cuts
    with its value at the edge; the slew from the segments of `TIME_TOLERANCE` or more in the
    window (not the steps between events) and from the steps with `lo <= time < hi`; the
    integral of the square over the cut segments. Of equal values, the first in the order of the
    polyline wins. Also whether a segment of an event of those blocks is in the window."""
    state = _AxisState()
    t, g, play = poly.t, poly.g, poly.play
    own = False
    if t.size >= 2:
        t0, t1, g0, g1 = t[:-1], t[1:], g[:-1], g[1:]
        a = np.maximum(t0, lo)
        b = np.minimum(t1, hi)
        valid = b > a
        span = np.where(valid, t1 - t0, 1.0)
        dg = g1 - g0
        ga = np.where(a == t0, g0, g0 + dg * (a - t0) / span)
        gb = np.where(b == t1, g1, g0 + dg * (b - t0) / span)
        credit_end = play[1:]
        credit_start = np.where(a == t0, play[:-1], credit_end)
        in_end = valid & (credit_end >= play_lo) & (credit_end < play_hi)
        in_start = valid & (credit_start >= play_lo) & (credit_start < play_hi)

        values = np.empty(2 * valid.size)
        values[0::2] = np.where(in_start, np.abs(ga), -1.0)
        values[1::2] = np.where(in_end, np.abs(gb), -1.0)
        j = int(np.argmax(values)) if values.size else 0
        if values.size and values[j] > 0.0:
            moment = (a, b)[j % 2][j // 2]
            credit = (credit_start, credit_end)[j % 2][j // 2]
            state.peak.offer(float(values[j]), float(moment), int(credit))

        state.rms_sum = float(
            np.sum(np.where(in_end, (b - a) * (ga * ga + ga * gb + gb * gb), 0.0))
        )
        state.rms_sum /= 3.0
        own = bool(np.any(in_end & poly.own))

        segment = in_end & ((b - a) >= TIME_TOLERANCE) & ~poly.step
        slopes = np.where(segment, np.abs(dg) / span, -1.0)
    else:
        slopes = np.empty(0)
        a = np.empty(0)
        credit_end = np.empty(0, dtype=np.int64)
    # The steps are in the order of the polyline: a step after the point `p` is before the
    # segment `p` (the segment from the point `p`), and after the segment `p - 1`.
    step_in = (
        (poly.step_time >= lo)
        & (poly.step_time < hi)
        & (poly.step_play >= play_lo)
        & (poly.step_play < play_hi)
    )
    step_values = np.where(step_in, np.abs(poly.step_size) / dt, -1.0)
    keys = np.concatenate([np.arange(slopes.size), poly.step_point - 0.5])
    all_values = np.concatenate([slopes, step_values])
    if all_values.size:
        order = np.argsort(keys, kind="stable")
        j = int(np.argmax(all_values[order]))
        if all_values[order[j]] > 0.0:
            i = int(order[j])
            if i < slopes.size:
                state.slew.offer(float(slopes[i]), float(a[i]), int(credit_end[i]))
            else:
                i -= slopes.size
                state.slew.offer(
                    float(step_values[i]), float(poly.step_time[i]), int(poly.step_play[i])
                )
    return state, own


def _exact_edge_blocks(
    index: SequenceIndex,
    points: EventPoints,
    blocks: _BlockData,
    state: dict[str, _AxisState],
    vector: _Best,
    lo: float,
    hi: float,
    first_play: int,
    stop_play: int,
) -> None:
    """Add the values of the blocks `first_play` to `stop_play` (exclusive), for the window `[lo,
    hi]`, to `state` and `vector`, from the exact polylines of the events near them.

    For each axis, the run of events that have a piece in the time range of these blocks, with
    the event before it and the event after it (so that each gap is known), makes a polyline
    (`_build_polyline`). The values of the window that are credited to these blocks are read
    from it (`_evaluate_axis`), and so are the candidates of the vector peak
    (`_vector_candidates`)."""
    dt = points.grad_raster_time
    reach = dt + 2 * TIME_TOLERANCE
    t_lo = float(blocks.reach_start[first_play:stop_play].min()) - reach
    t_hi = float(blocks.reach_end[first_play:stop_play].max()) + reach
    polys = []
    for axis in AXES:
        ae = blocks.axis_events[axis]
        e0 = int(np.searchsorted(ae.lt, t_lo, side="left"))
        e1 = int(np.searchsorted(ae.ft, t_hi, side="right"))
        poly = _build_polyline(
            ae, max(e0 - 1, 0), min(max(e1, e0) + 1, ae.pos.size), points, index.start_s, dt
        )
        polys.append(poly)
        axis_state, own = _evaluate_axis(poly, dt, lo, hi, first_play, stop_play)
        st = state[axis]
        st.has_event |= own or axis_state.peak.play is not None or axis_state.slew.play is not None
        st.rms_sum += axis_state.rms_sum
        st.peak.offer(axis_state.peak.value, axis_state.peak.time, axis_state.peak.play)
        st.slew.offer(axis_state.slew.value, axis_state.slew.time, axis_state.slew.play)
    values, times, plays = _vector_candidates(polys, index.start_s, blocks.end_s, lo, hi)
    keep = (plays >= first_play) & (plays < stop_play)
    for play, value, time in zip(
        *_best_by_play(values[keep], times[keep], plays[keep]), strict=True
    ):
        vector.offer(float(value), float(time), int(play))


def _range_result(
    index: SequenceIndex,
    points: EventPoints,
    blocks: _BlockData,
    lo: float,
    hi: float,
) -> tuple[dict[str, AxisResult], float, float, int | None, bool]:
    """`axes`, `vector_peak_hz_per_m`, `vector_peak_time_s`, `vector_peak_block` and whether any
    axis has an event, for the range `[lo, hi]`.

    The range `(0.0, index.end_s)` (`window=None`) is the whole file: the largest of each column
    of `blocks` over all the blocks (`_first_largest`) and the sum of the RMS integrals.

    For another range, the blocks that can have a value in it are the play indexes `[a, b)`:
    `a` is the first block of which no earlier block reaches `lo` or later, and `b` is the first
    block from which no block starts before `hi` (`blocks.end_envelope`, `blocks.start_envelope`
    are the largest end and the smallest start of the time range of the blocks, so
    `np.searchsorted` finds them). The time range of a block is its piece (its event, its ramps,
    the line into it, the step after the last point), and the range in which a candidate of
    the vector peak is credited to it. The blocks of `[a, b)` whose time range is whole in the
    range are one contiguous run of play indexes `[i0, i1)`: for each axis, the credited block
    of the peak is the first `argmax` of its column over the run, the credited block of the slew
    is the first of the `argmax` of the junction column and the slew column (the junction is
    first in a block), and the RMS integral is the sum of `blocks.rms_integral` over the run. The
    other blocks of `[a, b)` are the edge blocks, at most a few for each edge (a ramp is `dt / 2`
    outside the block of its event). They are made from the exact polylines of the events near
    them (`_exact_edge_blocks`, from the points of `_events.event_points`). No block is read with
    `get_block`.

    The run is computed before the edge blocks, so each candidate for a credit (an edge block)
    is compared with `_credit_goes_to`, which gives the result of a single pass over the blocks
    in play order. The vector peak is compared by time (`_Best`): of equal values, the earliest
    time wins. A range with `hi <= lo` has no event."""
    n = index.num_blocks
    axis_cols = {"x": index.gx, "y": index.gy, "z": index.gz}
    state = {axis: _AxisState() for axis in AXES}
    vector = _Best(by_time=True)

    if n == 0 or not lo < hi:
        axes = {axis: AxisResult(0.0, 0.0, None, 0.0, 0.0, None, 0.0) for axis in AXES}
        return axes, 0.0, 0.0, None, False

    whole_file = lo == 0.0 and hi == index.end_s
    if whole_file:
        a, i0, i1, b = 0, 0, n, n
    else:
        a = int(np.searchsorted(blocks.end_envelope, lo, side="left"))
        b = int(np.searchsorted(blocks.start_envelope, hi, side="right"))
        i0 = max(int(np.searchsorted(blocks.start_envelope, lo, side="left")), a)
        i1 = min(int(np.searchsorted(blocks.end_envelope, hi, side="right")), b)
        if i1 <= i0:
            i0 = i1 = a

    if i1 > i0:
        for axis in AXES:
            if not np.any(axis_cols[axis][i0:i1]):
                continue
            st = state[axis]
            st.has_event = True
            value, play = _first_largest(blocks.peak[axis], i0, i1)
            if play is not None:
                st.peak.offer(value, float(blocks.peak_time[axis][play]), play)
            # The junction is before every other item of its block: offer it first.
            value, play = _first_largest(blocks.junction[axis], i0, i1)
            if play is not None:
                st.slew.offer(value, float(blocks.junction_time[axis][play]), play)
            value, play = _first_largest(blocks.slew[axis], i0, i1)
            if play is not None:
                st.slew.offer(value, float(blocks.slew_time[axis][play]), play)
            if whole_file:
                st.rms_sum = blocks.whole_integral[axis]
            else:
                st.rms_sum = float(np.sum(blocks.rms_integral[axis][i0:i1]))
        value, play = _first_largest(blocks.vector_peak, i0, i1)
        if play is not None:
            # The first block in time order of the blocks that have the largest value.
            tied = i0 + np.flatnonzero(blocks.vector_peak[i0:i1] == value)
            play = int(tied[np.argmin(blocks.vector_peak_time[tied])])
            vector.offer(value, float(blocks.vector_peak_time[play]), play)

    for first_play, stop_play in ((a, i0), (i1, b)) if i1 > i0 else ((a, b),):
        if stop_play <= first_play:
            continue
        _exact_edge_blocks(index, points, blocks, state, vector, lo, hi, first_play, stop_play)

    axes: dict[str, AxisResult] = {}
    has_event_any = False
    for axis in AXES:
        st = state[axis]
        has_event_any = has_event_any or st.has_event
        rms = math.sqrt(st.rms_sum / (hi - lo)) if st.has_event else 0.0
        axes[axis] = AxisResult(
            peak_hz_per_m=st.peak.value,
            peak_time_s=st.peak.time,
            peak_block=int(index.block_id[st.peak.play]) if st.peak.play is not None else None,
            max_slew_hz_per_m_per_s=st.slew.value,
            slew_time_s=st.slew.time,
            slew_block=int(index.block_id[st.slew.play]) if st.slew.play is not None else None,
            rms_hz_per_m=rms,
        )

    vector_peak_block = int(index.block_id[vector.play]) if vector.play is not None else None
    return axes, vector.value, vector.time, vector_peak_block, has_event_any


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
    is not within the sequence raise `ValueError`. A segment of the gradient (of an event, a
    ramp or a line, see the module docstring) that crosses a range edge is cut at the edge, with
    the amplitude at the edge found by linear interpolation. A step counts in the range when its
    time is at the start of the range or after it, and before the end of the range.
    `range_s` is the window clipped to `(0.0, total_duration)`, so its start is never after its
    end: a window that lies past an end of the sequence by less than `TIME_TOLERANCE` gives a
    range of length 0, which has `reason == NO_GRADIENTS_IN_WINDOW` and zero values.

    The result for `window=None` is kept for the sequence object, so that callers of one
    sequence calculate it one time. A result with a window is not kept, because a caller can
    ask for many windows, but it uses the kept values of each block (`_BlockData`), so its cost is
    the number of blocks in the window. The kept results are built again after `add_block`,
    after a new read of a file into the object, and after a change of `seq.grad_raster_time` (the
    rule of `_kept`). A block replaced in place is not seen (`seq_index.sequence_index`). The
    kept result is read-only: `axes` is a `FrozenDict` and the result is a
    frozen dataclass.

    The values are in Hz/m and Hz/m/s, the units of pypulseq, with no gamma. To get T/m and
    T/m/s, divide them by the magnitude of the gamma of the target, in Hz/T (`docs/usage.md`
    section 9).

    This checks `window` first (its form, its numbers and their order), before it reads the
    sequence. Then it builds `seq_index.sequence_index(seq)`, returns the kept result for
    `window=None` when there is one, and checks the window against the length of the
    sequence. Only then does it take the per-event values (`_event_values` of the points of
    `_events.event_points`) and the values of each block (`_BlockData`), both built one time for
    each sequence, and combine them with numpy over the blocks of the range: an `argmax` and a
    sum of the RMS integrals over the blocks that lie whole in the range, and the points of
    `_events.event_points` for the few edge blocks (`_range_result`). It reads no block with
    `get_block` for a window. The one `get_block` call for each unique gradient event is in
    `_events.event_points`, one time for each sequence.

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

    points = event_points(seq)
    ev = _kept_event_values(seq, kept)
    blocks = _kept_block_data(seq, kept, index, points, ev)

    lo, hi = range_s
    axes, vector_peak_hz_per_m, vector_peak_time_s, vector_peak_block, has_event = _range_result(
        index, points, blocks, lo, hi
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
    )
    if window is None:
        kept["peaks"] = result
    return result


def block_gradient_values(seq: pp.Sequence) -> BlockGradientValues:
    """The gradient values of each block of `seq`, in play order (`BlockGradientValues`).

    These are the values that `gradient_peaks` takes the largest of for the whole file, kept
    for each block: the peak amplitude and the peak slew of the block's event and its ramps on
    each logical axis, the junction (the step or the line into its event), and the peak of the
    three-axis vector. The slope, the ramps and the junction follow the rules of the module
    docstring.

    The values are in Hz/m and Hz/m/s, with no gamma, as for `gradient_peaks`.

    The result is kept for the sequence object, with the same rule as `gradient_peaks` for
    `window=None` (the module docstring), so a second call gives the same object. The result
    is read-only: its arrays are not writeable and its dicts are `FrozenDict`s.

    This builds `seq_index.sequence_index(seq)`, the per-event values of
    `_events.event_points` (`_event_values`) and the values of each block (`_BlockData`), all
    shared with `gradient_peaks` and built one time for each sequence. Its result holds copies
    of the arrays of `_BlockData`, so a caller cannot change what `gradient_peaks` uses. It
    computes the peak of |G| of each block from the exact polylines of the whole file. It reads
    one block with `get_block` for each unique gradient event (in `_events.event_points`, one
    time for each sequence), and no other block.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`): the values are of the logical axes as they are stored.
    """
    refuse_rotations(seq)
    index = sequence_index(seq)
    kept = kept_results(_CACHE, seq)
    if "block_values" in kept:
        return kept["block_values"]
    ev = _kept_event_values(seq, kept)
    blocks = _kept_block_data(seq, kept, index, event_points(seq), ev)

    peak_hz_per_m = {axis: array.copy() for axis, array in blocks.peak.items()}
    peak_time_s = {axis: array.copy() for axis, array in blocks.peak_time.items()}
    slew_hz_per_m_per_s = {axis: array.copy() for axis, array in blocks.slew.items()}
    slew_time_s = {axis: array.copy() for axis, array in blocks.slew_time.items()}
    junction_hz_per_m_per_s = {axis: array.copy() for axis, array in blocks.junction.items()}
    vector_peak_hz_per_m = blocks.vector_peak.copy()
    vector_peak_time_s = blocks.vector_peak_time.copy()
    block_id = index.block_id.astype(np.int64)
    result_start_s = index.start_s.copy()
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
