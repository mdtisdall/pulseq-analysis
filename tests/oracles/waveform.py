"""The gradient waveform of a sequence, and the values that it gives.

This is the oracle of the model of `docs/plans/third-review-fixes.md` section 5.1 (the
model of MATLAB Pulseq, with decisions D1 to D5 of that plan). It does not import the
package, and it has no per-block shortcut: it builds the polyline of each axis one time,
and every value (the samples, the peak, the slew, the RMS and the vector peak) is read
from that polyline.

The model of one axis (`dt = seq.grad_raster_time`, `TIME_TOLERANCE` below):

1. The points of each gradient event, in play order, at the times
   `(block start + delay) + offset`. A trapezoid has the points 0, rise, rise + flat and
   rise + flat + fall, with the values 0, A, A and 0. An arbitrary or extended gradient
   has the offsets `[0, tt..., shape_dur]` and the values `[first, waveform..., last]`.
   A block start is the sum of the durations of the blocks before it.
2. Between two consecutive events on the axis, with `last_time` and `last` of the earlier
   event, `first_time` and `first` of the later one, and `gap = first_time - last_time`:
   - `gap <= TIME_TOLERANCE` (zero gap): no point. When `first != last` it is a step at
     `first_time`. The value at the time of the step is `last`.
   - `gap <= dt + TIME_TOLERANCE` (short gap): no point. The polyline is the straight line
     from `last` to `first`.
   - else (long gap): the point `(last_time + dt / 2, 0)` when `last != 0`, and the point
     `(first_time - dt / 2, 0)` when `first != 0`. The value is 0 between them. A value
     that is not 0 gets its ramp, also a value of 1e-6 Hz/m or less (decision D2).
3. Before the first point and after the last point of the axis the value is 0. A first or
   a last value that is not 0 is a step at that time.
4. Points of one event at the same time (a trapezoid with a flat time of 0, or an extended
   trapezoid with `tt[0] = 0`) stay in the polyline, as segments of length 0.

The slew is the largest slope of the segments of length `TIME_TOLERANCE` or more, and of
the steps (`abs(size) / dt`, decision D4). A segment of an event, a segment of a gap and a
step of a gap all count. The slope of a segment that joins two events across a zero gap is
not a slope: that segment is the step.

The credit (decision D5) of a point, a segment and a step is a play index, the position of
a block in `seq.block_events`. A point or a segment inside an event is credited to the block
of the event. A segment is credited as its end point is. The ramp point to 0 after an
event is credited to the earlier event. The ramp point from 0 before an event is credited
to the later event. The step or the line across a short gap is credited to the later event.
The step before the first point is credited to the block of the first event, and the step
after the last point to the block of the last event. The time of a segment is its start,
and the time of a step is its time. When two items have the same value, the first item in
the order of the polyline wins. In that order, a step or a line across a gap is after the
segments of the earlier event and before the segments of the later event, as is the ramp to
0 and from 0.

A window `(lo, hi)` cuts the polyline. Its values are:

- The peak: the largest absolute value at the end points of the segments of positive
  length in the window. A segment that an edge cuts has the interpolated value at the edge,
  credited as the segment. A point that an edge touches from outside (the last point of an
  earlier event at `lo`, the first point of a later event at `hi`) is not in the window.
- The slew: the steps with `lo <= time < hi`, and the segments, cut at the edges, whose
  length in the window is `TIME_TOLERANCE` or more. The time of a cut segment is the start
  of its cut.
- The RMS: `sqrt(integral of g^2 over the cut polyline / (hi - lo))`. The value is 0 where
  there is no point. A step adds nothing.
- The vector peak: the largest `sqrt(gx^2 + gy^2 + gz^2)` at the union of the times of the
  points of the three axes in the window, and at `lo` and `hi`. At a time that is not an
  edge, it evaluates the values after and before the time. At `lo` it evaluates the
  values after `lo`, and at `hi` the values before `hi`. The block of the vector peak is the
  block that has the time, seen from the side that the value is on: a time that is the end
  of a block, and the start of the next one, is in the earlier block for the value before
  it, and in the later block for the value after it.

Unit: seconds, Hz/m, Hz/m/s.
"""

from dataclasses import dataclass

import numpy as np
import pypulseq as pp
from oracles.blocks import iter_blocks

# The value of the package's `seq_utils.TIME_TOLERANCE` (s), kept separately so that the
# oracle does not depend on the package for it.
TIME_TOLERANCE = 1e-9

_AXES = ("x", "y", "z")


@dataclass(frozen=True, eq=False)
class Polyline:
    """The waveform of one axis.

    `t` (s) and `g` (Hz/m) are the points in order, with the ramp points of the long
    gaps, and with the repeated points of the events. A point is never before the point
    before it: a time that rounding puts earlier is the time of the point before.
    `point_play` is the play index credited to each point. The segment `s` is the line from
    point `s` to point `s + 1`. It is credited to `point_play[s + 1]`
    (`segment_play`). `segment_is_step[s]` is True for the segment between two events with
    a zero gap: it is the step, not a slope.

    A step has a time (`step_time`), a size (the value after it minus the value before it),
    the play index that is credited (`step_play`) and `step_point`, the index of the point
    before it (-1 for the step before the first point). A step is only in the arrays when
    its size is not 0.

    `block_id`, `block_start` and `block_end` are the block ID, the start time and the end
    time of each play index. They are in the polyline of an axis with no event too.
    """

    t: np.ndarray
    g: np.ndarray
    point_play: np.ndarray
    segment_is_step: np.ndarray
    step_time: np.ndarray
    step_size: np.ndarray
    step_play: np.ndarray
    step_point: np.ndarray
    block_id: tuple[int, ...]
    block_start: np.ndarray
    block_end: np.ndarray

    @property
    def segment_play(self) -> np.ndarray:
        return self.point_play[1:]


def _event_points(g, t0: float) -> tuple[np.ndarray, np.ndarray]:
    """The times (s) and values (Hz/m) of the points of one pypulseq gradient event in a
    block that starts at `t0`."""
    if g.type == "trap":
        offsets = np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
        values = np.array([0.0, g.amplitude, g.amplitude, 0.0])
    else:
        offsets = np.concatenate([[0.0], np.asarray(g.tt, dtype=float), [g.shape_dur]])
        values = np.concatenate([[g.first], np.asarray(g.waveform, dtype=float), [g.last]])
    return (t0 + g.delay) + offsets, values


def _build(events, block_id, block_start, block_end, dt: float) -> Polyline:
    """The polyline of one axis from its events: a list of `(play index, times, values)`."""
    t: list[float] = []
    g: list[float] = []
    play: list[int] = []
    is_step: list[bool] = []
    steps: list[tuple[float, float, int, int]] = []  # time, size, play, point before

    def add(time: float, value: float, credit: int, step: bool = False) -> None:
        if t:
            time = max(time, t[-1])
            is_step.append(step)
        t.append(time)
        g.append(value)
        play.append(credit)

    previous = -1
    for index, times, values in events:
        first_time, first = float(times[0]), float(values[0])
        junction = False
        if not t:
            if first != 0.0:
                steps.append((first_time, first, index, -1))
        else:
            last_time, last = t[-1], g[-1]
            gap = first_time - last_time
            if gap <= TIME_TOLERANCE:
                junction = True
                if first != last:
                    steps.append((first_time, first - last, index, len(t) - 1))
            elif gap > dt + TIME_TOLERANCE:
                if last != 0.0:
                    add(last_time + dt / 2, 0.0, previous)
                if first != 0.0:
                    add(first_time - dt / 2, 0.0, index)
        for k, (time, value) in enumerate(zip(times, values, strict=True)):
            add(float(time), float(value), index, step=junction and k == 0)
        previous = index

    if t and g[-1] != 0.0:
        steps.append((t[-1], -g[-1], previous, len(t) - 1))

    return Polyline(
        t=np.array(t, dtype=float),
        g=np.array(g, dtype=float),
        point_play=np.array(play, dtype=np.int64),
        segment_is_step=np.array(is_step, dtype=bool),
        step_time=np.array([s[0] for s in steps], dtype=float),
        step_size=np.array([s[1] for s in steps], dtype=float),
        step_play=np.array([s[2] for s in steps], dtype=np.int64),
        step_point=np.array([s[3] for s in steps], dtype=np.int64),
        block_id=tuple(block_id),
        block_start=np.array(block_start, dtype=float),
        block_end=np.array(block_end, dtype=float),
    )


def polylines(seq: pp.Sequence) -> dict[str, Polyline]:
    """The polylines of the three axes ("x", "y" and "z") of `seq`, from one pass over the
    blocks. `axis_polyline` makes all three for each call."""
    block_id: list[int] = []
    block_start: list[float] = []
    block_end: list[float] = []
    events: dict[str, list] = {axis: [] for axis in _AXES}
    for play, timing in enumerate(iter_blocks(seq)):
        block_id.append(timing.block_id)
        block_start.append(timing.start_s)
        block_end.append(timing.start_s + timing.duration_s)
        for axis in _AXES:
            g = getattr(timing.block, f"g{axis}", None)
            if g is not None:
                times, values = _event_points(g, timing.start_s)
                events[axis].append((play, times, values))
    dt = seq.grad_raster_time
    return {axis: _build(events[axis], block_id, block_start, block_end, dt) for axis in _AXES}


def axis_polyline(seq: pp.Sequence, axis: str) -> Polyline:
    """The polyline of `axis` ("x", "y" or "z") of `seq`."""
    if axis not in _AXES:
        raise ValueError(f"axis {axis!r} is not one of {_AXES}")
    return polylines(seq)[axis]


def values_at(poly: Polyline, q: np.ndarray) -> np.ndarray:
    """The values of `poly` at the times `q`: 0 outside the first and the last point, and at the
    time of a step inside them the value before the step."""
    q = np.asarray(q, dtype=float)
    n = poly.t.size
    if n == 0:
        return np.zeros(q.shape)
    i = np.clip(np.searchsorted(poly.t, q, side="left"), 0, n - 1)
    j = np.maximum(i - 1, 0)
    span = poly.t[i] - poly.t[j]
    safe_span = np.where(span > 0.0, span, 1.0)
    frac = np.where(span > 0.0, (q - poly.t[j]) / safe_span, 0.0)
    inside = poly.g[j] + (poly.g[i] - poly.g[j]) * frac
    value = np.where(poly.t[i] == q, poly.g[i], inside)
    return np.where((q >= poly.t[0]) & (q <= poly.t[-1]), value, 0.0)


def sample(seq: pp.Sequence, axis: str, t) -> np.ndarray:
    """The values (Hz/m) of the polyline of `axis` at the times `t` (s), in the shape of `t`.

    The value is 0 before the first point and after the last point. At the time of a step
    between two events it is the value before the step. At the time of the first point and
    of the last point it is the value of that point."""
    return values_at(axis_polyline(seq, axis), t)


def block_samples(seq: pp.Sequence, axis: str, dt: float) -> np.ndarray:
    """The samples of each block, joined in play order: `round(duration / dt)` samples of
    a block, the values of the polyline at `block start + (j + 0.5) * dt`."""
    poly = axis_polyline(seq, axis)
    parts = []
    for block_id, start in zip(poly.block_id, poly.block_start, strict=True):
        count = round(seq.block_durations[block_id] / dt)
        parts.append(values_at(poly, start + (np.arange(count) + 0.5) * dt))
    return np.concatenate(parts) if parts else np.zeros(0)


def _limit(poly: Polyline, q: float, side: str) -> float:
    """The value of the polyline at the time `q` from the `side` ("before" or "after")."""
    t, g = poly.t, poly.g
    if t.size == 0 or q < t[0] or q > t[-1]:
        return 0.0
    if side == "before":
        if q == t[0]:
            return 0.0
        i = int(np.searchsorted(t, q, side="left"))
        j = i - 1
        if t[i] == q:
            return float(g[i])
    else:
        if q == t[-1]:
            return 0.0
        j = int(np.searchsorted(t, q, side="right")) - 1
        i = j + 1
        if t[j] == q:
            return float(g[j])
    return float(g[j] + (g[i] - g[j]) * (q - t[j]) / (t[i] - t[j]))


def _axis_values(poly: Polyline, dt: float, lo: float, hi: float) -> dict:
    peak, peak_time, peak_play = 0.0, 0.0, None
    slew, slew_time, slew_play = 0.0, 0.0, None
    integral = 0.0
    t, g, point_play = poly.t, poly.g, poly.point_play
    steps = list(zip(poly.step_point, poly.step_time, poly.step_size, poly.step_play, strict=True))
    next_step = 0

    def take_steps(before_segment: int) -> None:
        # The steps in the order of the polyline: a step at `step_point` k is before the
        # segment k (the segment that starts at the point k), and after the segment k - 1.
        nonlocal next_step, slew, slew_time, slew_play
        while next_step < len(steps) and steps[next_step][0] <= before_segment:
            _, time, size, credit = steps[next_step]
            next_step += 1
            if lo <= time < hi and abs(size) / dt > slew:
                slew, slew_time, slew_play = abs(size) / dt, float(time), int(credit)

    for s in range(t.size - 1):
        take_steps(s)
        t0, t1 = t[s], t[s + 1]
        a, b = max(t0, lo), min(t1, hi)
        if not b > a:
            continue
        ga = g[s] if a == t0 else g[s] + (g[s + 1] - g[s]) * (a - t0) / (t1 - t0)
        gb = g[s + 1] if b == t1 else g[s] + (g[s + 1] - g[s]) * (b - t0) / (t1 - t0)
        for time, value, credit in (
            (a, ga, point_play[s] if a == t0 else point_play[s + 1]),
            (b, gb, point_play[s + 1]),
        ):
            if abs(value) > peak:
                peak, peak_time, peak_play = float(abs(value)), float(time), int(credit)
        if b - a >= TIME_TOLERANCE and not poly.segment_is_step[s]:
            slope = abs(g[s + 1] - g[s]) / (t1 - t0)
            if slope > slew:
                slew, slew_time, slew_play = float(slope), float(a), int(point_play[s + 1])
        integral += (b - a) * (ga * ga + ga * gb + gb * gb) / 3.0
    take_steps(t.size)

    def block(play):
        return None if play is None else poly.block_id[play]

    return {
        "peak": peak,
        "peak_time": peak_time,
        "peak_block": block(peak_play),
        "max_slew": slew,
        "slew_time": slew_time,
        "slew_block": block(slew_play),
        "rms": float(np.sqrt(integral / (hi - lo))) if hi > lo else 0.0,
    }


def _vector_peak(
    polys: dict[str, Polyline], lo: float, hi: float
) -> tuple[float, float, int | None]:
    reference = polys["x"]
    times = np.unique(
        np.concatenate([[lo, hi]] + [p.t[(p.t >= lo) & (p.t <= hi)] for p in polys.values()])
    )
    best, best_time, best_block = 0.0, 0.0, None
    for time in times:
        for side in ("before", "after"):
            if (side == "before" and time == lo) or (side == "after" and time == hi):
                continue
            value = float(np.sqrt(sum(_limit(p, float(time), side) ** 2 for p in polys.values())))
            if value > best:
                if side == "before":
                    play = int(
                        np.searchsorted(reference.block_end, time - TIME_TOLERANCE, side="left")
                    )
                    play = min(play, len(reference.block_id) - 1)
                else:
                    play = (
                        int(
                            np.searchsorted(
                                reference.block_start, time + TIME_TOLERANCE, side="right"
                            )
                        )
                        - 1
                    )
                    play = max(play, 0)
                best, best_time, best_block = value, float(time), reference.block_id[play]
    return best, best_time, best_block


def peaks(seq: pp.Sequence, window: tuple[float, float] | None = None) -> dict:
    """The values of the polylines of `seq` in `window` `(lo, hi)` (s), or in the whole
    sequence `(0, end)` when it is None.

    The result has the keys "x", "y" and "z", each a dict with "peak" (Hz/m),
    "peak_time" (s), "peak_block" (a block ID, or None when the peak is 0), "max_slew"
    (Hz/m/s), "slew_time", "slew_block" (None when the slew is 0) and "rms" (Hz/m). It has
    also "vector_peak" (Hz/m), "vector_peak_time" and "vector_peak_block" (None when the
    peak is 0). The time of a value that is 0 is 0.0."""
    polys = polylines(seq)
    reference = polys["x"]
    if window is None:
        lo, hi = 0.0, float(reference.block_end[-1]) if reference.block_end.size else 0.0
    else:
        lo, hi = window
        if not lo < hi:
            raise ValueError(f"window {window!r} must have a start before its end")
    dt = seq.grad_raster_time
    result: dict = {axis: _axis_values(polys[axis], dt, lo, hi) for axis in _AXES}
    if hi > lo:
        vector, time, block = _vector_peak(polys, lo, hi)
    else:
        vector, time, block = 0.0, 0.0, None
    result.update(vector_peak=vector, vector_peak_time=time, vector_peak_block=block)
    return result
