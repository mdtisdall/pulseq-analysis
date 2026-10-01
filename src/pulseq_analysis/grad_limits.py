"""How near a sequence's gradients get to the hardware limits.

Each gradient event is piecewise linear between the points that `seq_utils.gradient_points`
gives, as the Pulseq specification treats it. This module computes, for each logical axis
(x, y, z) and for the three-axis vector, the peak amplitude, the peak slew rate, and the RMS
amplitude over a time range, and compares the peak amplitude and the peak slew rate with the
hardware limits.

The axes are the logical sequence axes, not the physical gradient axes of a scanner. The
scanner rotates the logical axes onto the physical ones for the prescribed orientation, so on
an oblique slice one physical axis can see amplitude up to the vector peak,
`GradientLimits.vector_peak_mt_per_m`, even when no single logical axis is near the limit.

This computes the per-event values one time for each unique gradient event
(`seq_index.grad_events`), then combines them over the blocks of `seq_index.sequence_index`
with numpy, instead of reading every block with `get_block`. Thus its cost grows with the
number of unique events and the number of blocks, but it makes no pypulseq call for each
block. It reads individual blocks only for the few blocks that a window edge cuts.

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

`block_gradient_values` gives the same measurements for each block of the whole file, in play
order, instead of the one largest value for each axis that `gradient_limits` gives. It is for a
caller that needs each place where a value is above a limit. `gradient_limits` does not call it.
"""

import math
from dataclasses import dataclass

import numpy as np
import pypulseq as pp

from .extensions import refuse_rotations
from .seq_index import SequenceIndex, block_cache_off, grad_events, sequence_index
from .seq_utils import GAMMA, TIME_TOLERANCE, gradient_points

_AXES = ("x", "y", "z")


@dataclass(frozen=True)
class HardwareLimits:
    """The gradient hardware limits that a sequence is compared with.

    `max_grad_mt_per_m` is in mT/m and `max_slew_t_per_m_per_s` in T/m/s. `label` names
    the limits, for example "pypulseq system limits" (the limits of `seq.system`) or the
    name of a target profile. The numbers of `gradient_limits` do not depend on `limits`:
    it only gives them back in `GradientLimits.limits`, so that a caller can compare.
    """

    max_grad_mt_per_m: float
    max_slew_t_per_m_per_s: float
    label: str


@dataclass(frozen=True)
class AxisResult:
    """The gradient limit numbers for one logical axis, over a time range.

    `peak_block` and `slew_block` are the block ID (`seq_index.SequenceIndex.block_id`)
    where the peak amplitude, respectively the peak slew, was found. For the slew, this is
    the block after the junction when the peak slew is a junction step (see the module
    docstring), otherwise the block whose event has the segment. `peak_time_s` is the time of
    the peak, and `slew_time_s` the start of the steepest segment (the start of the range
    when a range edge cuts that segment), or the time of the junction for a junction step;
    both are in seconds from the sequence start. When several blocks reach the same largest
    value, the credited block is the first of them in play order, and the time is the first
    time in that block where the value is reached (a junction step is before every segment
    of its block). A largest value of 0 credits no block (None) and has the time 0.0.
    `rms_mt_per_m` is the RMS amplitude over the range that `GradientLimits.range_s` gives,
    not over the whole sequence when a window is used.
    """

    peak_mt_per_m: float
    peak_time_s: float
    peak_block: int | None
    max_slew_t_per_m_per_s: float
    slew_time_s: float
    slew_block: int | None
    rms_mt_per_m: float


@dataclass(frozen=True)
class GradientLimits:
    """The result of `gradient_limits`.

    `reason` is None when the range has at least one gradient event on some axis. Otherwise it
    is a short human-readable string, for example "no gradient events in the sequence", and
    every numeric field is its zero value, except `whole_rms_mt_per_m`, which is the RMS of the
    whole file when `window` is given. The zero value is 0.0 for an amplitude, slew or RMS
    field, and 0.0 for a time field; every block field (`AxisResult.peak_block`,
    `AxisResult.slew_block`, `vector_peak_block`) is None. `range_s` still holds the range that was used.

    `vector_peak_mt_per_m` is the largest magnitude of the three-axis gradient vector over the
    range, `vector_peak_time_s` is the first time in the range where it is reached, and
    `vector_peak_block` is the block ID of the block that holds that time, by the rule of
    `AxisResult` (0.0 and None when the peak is 0). There is no vector slew field. The RMS of the vector magnitude is the square
    root of the sum of the squares of the three axis RMS values, because the mean of |G|² is the
    sum of the three axis means of G².

    `whole_rms_mt_per_m` is the RMS amplitude of each axis (mT/m) over the whole sequence,
    computed in the same call that computes `axes`, so that a caller that wants both the
    window's values and the whole file's RMS needs only one call. It is None when `window` was None (then `axes`' own RMS already is the whole file's).
    """

    reason: str | None
    range_s: tuple[float, float]
    axes: dict[str, AxisResult]
    vector_peak_mt_per_m: float
    vector_peak_time_s: float
    vector_peak_block: int | None
    limits: HardwareLimits
    whole_rms_mt_per_m: dict[str, float] | None = None


@dataclass(frozen=True, eq=False)
class BlockGradientValues:
    """The gradient values of each block of a sequence, from `block_gradient_values`.

    Each array has one entry for each block, in play order (`seq_index.SequenceIndex`); N is
    the number of blocks. `block_id` is the block ID and `start_s` the start of the block in
    seconds from the sequence start. The four dicts have the keys "x", "y" and "z", and each
    value is a float array of length N. For an axis that has no event in a block, the peak and
    the slew are 0 and their times are `start_s`; the junction step is the step from the last
    value of the previous block to 0, which is not 0 when the previous block ends at a value
    that is not 0.

    `peak_mt_per_m` is the largest absolute amplitude of the block's event on the axis, and
    `peak_time_s` its time. `slew_t_per_m_per_s` is the largest slope of a straight segment of
    that event, and `slew_time_s` the start of that segment. `junction_t_per_m_per_s` is the
    step at the start of the block, `|last value of the previous block - first value of this
    block|` divided by `seq.grad_raster_time`, as the module docstring describes it (0 for
    the first block). Its time is `start_s`. `vector_peak_mt_per_m` is the largest magnitude
    of the three-axis vector in the block, and `vector_peak_time_s` the first time in the block
    where it is reached (0 and `start_s` for a block without gradients).

    The maximum of each of these over the blocks is the value that `gradient_limits` gives for
    the whole file. The first block with that value is its credited block, and for the slew
    the junction step of a block comes before the segments of that block.
    """

    block_id: np.ndarray
    start_s: np.ndarray
    peak_mt_per_m: dict[str, np.ndarray]
    peak_time_s: dict[str, np.ndarray]
    slew_t_per_m_per_s: dict[str, np.ndarray]
    slew_time_s: dict[str, np.ndarray]
    junction_t_per_m_per_s: dict[str, np.ndarray]
    vector_peak_mt_per_m: np.ndarray
    vector_peak_time_s: np.ndarray


def _default_limits(seq: pp.Sequence, gamma: float) -> HardwareLimits:
    # seq.system.max_grad and seq.system.max_slew are always stored in Hz/m and
    # Hz/m/s, whatever unit the caller gave pp.Opts, because pp.Opts.__init__
    # converts every unit to Hz/m (respectively Hz/m/s) with the sequence's own gamma
    # before it stores the value (verified in pypulseq's opts.py). The conversion back to mT/m
    # (T/m/s) uses `gamma`, the same gamma as the measured values.
    return HardwareLimits(
        max_grad_mt_per_m=seq.system.max_grad / gamma * 1e3,
        max_slew_t_per_m_per_s=seq.system.max_slew / gamma,
        label="pypulseq system limits",
    )


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
    `_AXES`, each `(t, amp)`, all sharing one time origin). An axis with no piece here is zero
    for the whole range. |G| is convex on a stretch where every axis is linear, so its maximum
    is at one of these breakpoints."""
    times = np.unique(np.concatenate([t for t, _ in axis_points.values()]))
    sum_sq = np.zeros_like(times)
    for axis in _AXES:
        piece = axis_points.get(axis)
        if piece is None:
            continue
        t, amp = piece
        values = np.interp(times, t, amp, left=0.0, right=0.0)
        sum_sq = sum_sq + values * values
    magnitude = np.sqrt(sum_sq)
    i = int(np.argmax(magnitude))
    return float(times[i]), float(magnitude[i])


@dataclass
class _EventData:
    """The per-unique-gradient-event values that `gradient_limits` needs, indexed by the dense
    event index minus 1 (`seq_index.SequenceIndex.gx`/`gy`/`gz`, 0 = no event). All amplitudes
    are in Hz/m, slew in Hz/m/s, and times in seconds from the start of the block that plays the
    event (`seq_utils.gradient_points(g, 0.0)`: the event's own delay is included, the block's
    start is not)."""

    peak: np.ndarray  # K: the largest |amplitude| of the event's own corner points
    peak_offset: np.ndarray  # K: the time (from the block start) of that peak
    slew: np.ndarray  # K: the largest slope between neighbouring corner points
    slew_offset: np.ndarray  # K: the start time (from the block start) of the first such segment
    first: np.ndarray  # K: the value of the event's first corner point
    last: np.ndarray  # K: the value of the event's last corner point
    integral: np.ndarray  # K: the integral of amplitude^2 dt over the whole event
    t_rel: list[np.ndarray]  # K arrays: the corner point times, from the block start
    amp: list[np.ndarray]  # K arrays: the corner point amplitudes


def _event_values(seq: pp.Sequence, index: SequenceIndex) -> _EventData:
    """`_EventData` for every unique gradient event of `seq`, computed one time for each event
    (`seq_index.grad_events`, which calls `get_block` only for the event's first block, with the
    block cache off)."""
    k = index.grad_first.size
    peak = np.zeros(k)
    peak_offset = np.zeros(k)
    slew = np.zeros(k)
    slew_offset = np.zeros(k)
    first = np.zeros(k)
    last = np.zeros(k)
    integral = np.zeros(k)
    t_rel: list[np.ndarray] = [np.array([])] * k
    amp_list: list[np.ndarray] = [np.array([])] * k

    for dense_k, g in grad_events(seq, index):
        t, amp = gradient_points(g, 0.0)
        i = dense_k - 1
        abs_amp = np.abs(amp)
        pk = int(np.argmax(abs_amp))
        peak[i] = float(abs_amp[pk])
        peak_offset[i] = float(t[pk])
        first[i] = float(amp[0])
        last[i] = float(amp[-1])

        dt = np.diff(t)
        a, b = amp[:-1], amp[1:]
        integral[i] = float(np.sum(dt * (a * a + a * b + b * b) / 3.0))
        valid = dt >= TIME_TOLERANCE
        if np.any(valid):
            seg_slew = np.abs((b - a)[valid] / dt[valid])
            j = int(np.argmax(seg_slew))
            slew[i] = float(seg_slew[j])
            slew_offset[i] = float(t[:-1][valid][j])

        t_rel[i] = t
        amp_list[i] = amp

    return _EventData(peak, peak_offset, slew, slew_offset, first, last, integral, t_rel, amp_list)


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
    index: SequenceIndex, ev: _EventData, total_duration: float, gamma: float
) -> dict[str, float]:
    """The RMS amplitude (mT/m) of each axis over the whole sequence, from the per-event
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
        result[axis] = math.sqrt(rms_sum / total_duration) / gamma * 1e3
    return result


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
    lo: float,
    hi: float,
    grad_raster: float,
    gamma: float,
) -> tuple[dict[str, AxisResult], float, float, int | None, bool]:
    """`axes`, `vector_peak_mt_per_m`, `vector_peak_time_s`, `vector_peak_block` and whether any
    axis has an event, for the range `[lo, hi]`.

    Blocks fully inside the range use the per-event values (`_axis_slice_stats`,
    `_triple_vector_peak`), over the contiguous play-index range that
    `seq_index.SequenceIndex.start_s` gives (blocks are in time order, so the "fully inside"
    blocks are one contiguous run). The few blocks that a range edge cuts (at most two: a
    block of zero duration at a range edge is skipped) are read with `get_block` and clipped
    exactly as the oracle (`tests/oracles/grad_limits.py`) clips every block. Passing
    `lo=0.0, hi=index.end_s` (`window=None`) makes every block of non-zero duration fully
    inside (a block of zero duration at 0 or at the end is skipped, and it has no gradient), so
    this same code computes the whole-file result too.

    The slice is computed before the edge blocks, and its triples are not in play order, so
    each candidate for a credit (an edge block, a triple of the slice) is compared with
    `_credit_goes_to`, which gives the result of a single pass over the blocks in play order.
    The junction steps follow the same rule.
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
        for axis in _AXES
    }

    if n == 0:
        axes = {axis: AxisResult(0.0, 0.0, None, 0.0, 0.0, None, 0.0) for axis in _AXES}
        return axes, 0.0, 0.0, None, False

    end_s = start_s + index.duration_s
    skip = (end_s <= lo) | (start_s >= hi)
    processed = ~skip
    fully_inside = processed & (start_s >= lo) & (end_s <= hi)
    inside_idx = np.flatnonzero(fully_inside)
    i0, i1 = (int(inside_idx[0]), int(inside_idx[-1]) + 1) if inside_idx.size else (0, 0)

    if i1 > i0:
        for axis in _AXES:
            stats = _axis_slice_stats(axis_cols[axis][i0:i1], ev, i0, start_s)
            if stats is not None:
                state[axis].update(stats)
                state[axis]["has_event"] = True

    # The blocks a range edge cuts: read individually and clipped, as the oracle does.
    edge_positions = np.flatnonzero(processed & ~fully_inside)
    axis_points_by_play: dict[int, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    if edge_positions.size:
        with block_cache_off(seq):
            for play in edge_positions.tolist():
                block = seq.get_block(int(index.block_id[play]))
                block_start = float(start_s[play])
                axis_points: dict[str, tuple[np.ndarray, np.ndarray]] = {}
                for axis in _AXES:
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
                    abs_amp = np.abs(amp_c)
                    i = int(np.argmax(abs_amp))
                    if _credit_goes_to(abs_amp[i], play, st["peak"], st["peak_play"]):
                        st["peak"], st["peak_time"], st["peak_play"] = (
                            float(abs_amp[i]),
                            float(t_c[i]),
                            play,
                        )
                    dt = np.diff(t_c)
                    a, b = amp_c[:-1], amp_c[1:]
                    st["rms_sum"] += float(np.sum(dt * (a * a + a * b + b * b) / 3.0))
                    valid = dt >= TIME_TOLERANCE
                    if np.any(valid):
                        seg_slew = np.abs((b - a)[valid] / dt[valid])
                        j = int(np.argmax(seg_slew))
                        if _credit_goes_to(seg_slew[j], play, st["slew"], st["slew_play"]):
                            st["slew"], st["slew_play"], st["slew_time"] = (
                                float(seg_slew[j]),
                                play,
                                float(t_c[:-1][valid][j]),
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
        any_grad = (gx_s > 0) | (gy_s > 0) | (gz_s > 0)
        if np.any(any_grad):
            base = k + 1
            combo = (gx_s * base + gy_s) * base + gz_s
            _, first_local = np.unique(combo, return_index=True)
            for local in first_local.tolist():
                if not any_grad[local]:
                    continue
                triple = _triple_vector_peak(
                    ev, int(gx_s[local]), int(gy_s[local]), int(gz_s[local])
                )
                if triple is None:
                    continue
                rel_t, mag = triple
                # `first_local` is in the order of `combo`, not of play.
                if _credit_goes_to(mag, i0 + local, vector_peak_hz, vector_peak_play):
                    vector_peak_hz, vector_peak_play = mag, i0 + local
                    vector_peak_time = float(start_s[i0 + local]) + rel_t

    for play, axis_points in axis_points_by_play.items():
        block_time, block_peak = _vector_peak_in_block(axis_points)
        if _credit_goes_to(block_peak, play, vector_peak_hz, vector_peak_play):
            vector_peak_hz, vector_peak_time, vector_peak_play = block_peak, block_time, play

    # The junction steps (see the module docstring): for each axis, the step at the
    # incoming junction of each processed block that starts at or after the range
    # start (0 before the very first block of the file, or where either side has no
    # event on the axis). The junction of a block that the range start cuts is before
    # the range, so it is not used. A junction at the range end belongs to the block
    # after it, which is not processed.
    junction_in_range = processed & (start_s >= lo)
    axes: dict[str, AxisResult] = {}
    has_event_any = False
    for axis in _AXES:
        col = axis_cols[axis].astype(np.int64)
        if k:
            idx = np.clip(col - 1, 0, k - 1)
            first_vals = np.where(col == 0, 0.0, ev.first[idx])
            last_vals = np.where(col == 0, 0.0, ev.last[idx])
        else:
            first_vals = np.zeros(n)
            last_vals = np.zeros(n)
        prev_last = np.concatenate(([0.0], last_vals[:-1]))
        steps = np.abs(prev_last - first_vals) / grad_raster

        junction_max, junction_play = 0.0, None
        if np.any(junction_in_range):
            masked = np.where(junction_in_range, steps, -np.inf)
            j = int(np.argmax(masked))
            candidate = float(masked[j])
            # Only a strictly positive step is a real junction, matching the segment
            # search below (which starts its running max at 0.0 too): a step of
            # exactly 0.0 everywhere (for example an axis with no event at all) must
            # stay uncredited (slew_block None).
            if candidate > junction_max:
                junction_max, junction_play = candidate, j

        st = state[axis]
        seg_max, seg_play = st["slew"], st["slew_play"]
        # A junction is at its block's start, before every segment of that block, so it
        # also takes the credit from a segment of equal slew in the same block.
        if junction_play is not None and (
            seg_play is None
            or junction_max > seg_max
            or (junction_max == seg_max and junction_play <= seg_play)
        ):
            final_slew, final_slew_play = junction_max, junction_play
            final_slew_time = float(start_s[junction_play])
        else:
            final_slew, final_slew_play, final_slew_time = seg_max, seg_play, st["slew_time"]

        # A credited junction step means a real, non-zero step was found even when no
        # segment of this axis lies inside the range (for example a window that starts
        # at the junction after a gradient event that ends at a value that is not 0):
        # that is real gradient information about the range, so it counts as "has an
        # event" too.
        has_event = st["has_event"] or final_slew_play is not None
        has_event_any = has_event_any or has_event
        range_length = hi - lo
        rms = (
            math.sqrt(st["rms_sum"] / range_length) / gamma * 1e3
            if has_event and range_length > 0
            else 0.0
        )
        axes[axis] = AxisResult(
            peak_mt_per_m=st["peak"] / gamma * 1e3,
            peak_time_s=st["peak_time"],
            peak_block=int(index.block_id[st["peak_play"]])
            if st["peak_play"] is not None
            else None,
            max_slew_t_per_m_per_s=final_slew / gamma,
            slew_time_s=final_slew_time,
            slew_block=(
                int(index.block_id[final_slew_play]) if final_slew_play is not None else None
            ),
            rms_mt_per_m=rms,
        )

    vector_peak_block = (
        int(index.block_id[vector_peak_play]) if vector_peak_play is not None else None
    )
    return axes, vector_peak_hz / gamma * 1e3, vector_peak_time, vector_peak_block, has_event_any


def gradient_limits(
    seq: pp.Sequence,
    *,
    window: tuple[float, float] | None = None,
    limits: HardwareLimits | None = None,
    gamma: float = GAMMA,
) -> GradientLimits:
    """The peak amplitude, the peak slew rate and the RMS amplitude of `seq`'s
    gradients, on each logical axis and as a three-axis vector, compared with
    `limits`.

    With `window=None`, the range is the whole sequence, `(0.0, total_duration)`.
    Otherwise `window` is `(start_s, end_s)` in seconds from the sequence start; it
    must have `start_s < end_s` and lie within the sequence
    (`0.0 <= start_s` and `end_s <= total_duration`, each within `TIME_TOLERANCE`),
    or this function raises `ValueError`. A gradient piece that crosses a range edge
    is cut at the edge, with the amplitude at the edge found by linear interpolation.
    With `window` given, `GradientLimits.whole_rms_mt_per_m` also gives each axis's RMS
    over the whole sequence, computed in this same call.

    With `limits=None`, the limits are `seq.system.max_grad` and `seq.system.max_slew`
    (see `HardwareLimits`).

    `gamma` (Hz/T) converts every value from Hz/m (Hz/m/s) to mT/m (T/m/s), and the default
    limits too. The default is 42.576 MHz/T. A caller that compares the values with limits
    of its own passes the gamma that converted those limits.

    This builds `seq_index.sequence_index(seq)` and the per-event values of
    `seq_index.grad_events` one time (`_event_values`), then combines them with numpy over the
    blocks of the range. It reads individual blocks with `get_block` only for the few blocks
    that a range edge cuts, so its cost does not grow with the number of blocks the way that
    reading every block would.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`): the numbers are of the logical axes as they are stored.
    """
    refuse_rotations(seq)
    if limits is None:
        limits = _default_limits(seq, gamma)

    index = sequence_index(seq)
    ev = _event_values(seq, index)
    total_duration = index.end_s
    grad_raster = seq.grad_raster_time

    if window is None:
        range_s = (0.0, total_duration)
        whole_rms_mt_per_m = None
    else:
        start_s, end_s = window
        if not start_s < end_s:
            raise ValueError(f"window {window!r} must have a start before its end")
        if start_s < -TIME_TOLERANCE or end_s > total_duration + TIME_TOLERANCE:
            raise ValueError(
                f"window {window!r} is not within the sequence (0.0, {total_duration})"
            )
        # Clip to the sequence exactly: start_s/end_s can be off by a rounding error of
        # up to TIME_TOLERANCE and still pass the check above.
        range_s = (max(0.0, start_s), min(total_duration, end_s))
        whole_rms_mt_per_m = _whole_file_rms(index, ev, total_duration, gamma)

    lo, hi = range_s
    axes, vector_peak_mt_per_m, vector_peak_time_s, vector_peak_block, has_event = _range_result(
        seq, index, ev, lo, hi, grad_raster, gamma
    )

    if has_event:
        reason = None
    elif window is not None:
        reason = "no gradient events in the window"
    else:
        reason = "no gradient events in the sequence"

    return GradientLimits(
        reason=reason,
        range_s=range_s,
        axes=axes,
        vector_peak_mt_per_m=vector_peak_mt_per_m,
        vector_peak_time_s=vector_peak_time_s,
        vector_peak_block=vector_peak_block,
        limits=limits,
        whole_rms_mt_per_m=whole_rms_mt_per_m,
    )


def _event_column(col: np.ndarray, values: np.ndarray) -> np.ndarray:
    """For each block, the entry of `values` (K entries, one for each unique gradient event) of
    the block's event on one axis, and 0.0 for a block without an event on it. `col` is the
    dense event column of that axis (`seq_index.SequenceIndex.gx`/`gy`/`gz`, 0 = no event)."""
    return np.concatenate(([0.0], values))[col]


def _block_vector_peaks(index: SequenceIndex, ev: _EventData) -> tuple[np.ndarray, np.ndarray]:
    """The peak of |G| of each block in Hz/m, and its time from the block start, from
    `_triple_vector_peak` one time for each distinct triple of dense event indexes
    (`np.unique` over the blocks that have a gradient, mapped back to every such block). A
    block without a gradient has 0 and 0."""
    peak = np.zeros(index.num_blocks)
    offset = np.zeros(index.num_blocks)
    gx, gy, gz = (col.astype(np.int64) for col in (index.gx, index.gy, index.gz))
    selected = np.flatnonzero((gx > 0) | (gy > 0) | (gz > 0))
    if selected.size == 0:
        return peak, offset
    gx, gy, gz = gx[selected], gy[selected], gz[selected]
    # The triple as one number, in two steps so that it stays far from the int64 limit.
    base = ev.peak.size + 1
    _, pair = np.unique(gx * base + gy, return_inverse=True)
    _, first, inverse = np.unique(
        pair.astype(np.int64) * base + gz, return_index=True, return_inverse=True
    )
    triple_peak = np.zeros(first.size)
    triple_offset = np.zeros(first.size)
    for t, local in enumerate(first.tolist()):
        triple = _triple_vector_peak(ev, int(gx[local]), int(gy[local]), int(gz[local]))
        if triple is not None:
            triple_offset[t], triple_peak[t] = triple
    peak[selected] = triple_peak[inverse]
    offset[selected] = triple_offset[inverse]
    return peak, offset


def block_gradient_values(seq: pp.Sequence, *, gamma: float = GAMMA) -> BlockGradientValues:
    """The gradient values of each block of `seq`, in play order (`BlockGradientValues`).

    These are the values that `gradient_limits` takes the largest of for the whole file, kept
    for each block: the peak amplitude and the peak slew of the block's event on each logical
    axis, the junction step at the start of the block, and the peak of the three-axis vector.
    The slope and the junction step follow the rules of the module docstring.

    `gamma` (Hz/T) converts the values from Hz/m (Hz/m/s) to mT/m (T/m/s), as it does for
    `gradient_limits`. The default is 42.576 MHz/T.

    This builds `seq_index.sequence_index(seq)` and the per-event values of
    `seq_index.grad_events` one time (`_event_values`), then combines them with numpy over the
    blocks. It computes the peak of |G| one time for each distinct triple of events. It does
    not read a block with `get_block`.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`): the values are of the logical axes as they are stored.
    """
    refuse_rotations(seq)
    index = sequence_index(seq)
    ev = _event_values(seq, index)
    grad_raster = seq.grad_raster_time
    start_s = index.start_s

    peak_mt_per_m: dict[str, np.ndarray] = {}
    peak_time_s: dict[str, np.ndarray] = {}
    slew_t_per_m_per_s: dict[str, np.ndarray] = {}
    slew_time_s: dict[str, np.ndarray] = {}
    junction_t_per_m_per_s: dict[str, np.ndarray] = {}
    for axis, col in zip(_AXES, (index.gx, index.gy, index.gz), strict=True):
        peak_mt_per_m[axis] = _event_column(col, ev.peak) / gamma * 1e3
        peak_time_s[axis] = start_s + _event_column(col, ev.peak_offset)
        slew_t_per_m_per_s[axis] = _event_column(col, ev.slew) / gamma
        slew_time_s[axis] = start_s + _event_column(col, ev.slew_offset)
        first_vals = _event_column(col, ev.first)
        last_vals = _event_column(col, ev.last)
        prev_last = np.concatenate(([0.0], last_vals[:-1]))
        junction_t_per_m_per_s[axis] = np.abs(prev_last - first_vals) / grad_raster / gamma

    vector_peak_hz, vector_offset = _block_vector_peaks(index, ev)
    return BlockGradientValues(
        block_id=index.block_id.astype(np.int64),
        start_s=start_s.copy(),
        peak_mt_per_m=peak_mt_per_m,
        peak_time_s=peak_time_s,
        slew_t_per_m_per_s=slew_t_per_m_per_s,
        slew_time_s=slew_time_s,
        junction_t_per_m_per_s=junction_t_per_m_per_s,
        vector_peak_mt_per_m=vector_peak_hz / gamma * 1e3,
        vector_peak_time_s=start_s + vector_offset,
    )
