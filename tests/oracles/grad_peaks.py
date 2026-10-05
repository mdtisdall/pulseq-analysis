"""How near a sequence's gradients get to the hardware limits.

Each gradient event is piecewise linear between its corner or sample points, as the
Pulseq specification treats it (`_gradient_points` here). This module
computes, for each logical axis (x, y, z) and for the three-axis vector, the peak
amplitude, the peak slew rate, and the RMS amplitude over a time range, and compares
the peak amplitude and the peak slew rate with the hardware limits.

The axes are the logical sequence axes, not the physical gradient axes of a scanner.
The scanner rotates the logical axes onto the physical ones for the prescribed
orientation, so on an oblique slice one physical axis can see amplitude up to the
vector peak, `GradientPeaks.vector_peak_mt_per_m`, even when no single logical axis
is near the limit.

Oracle: the implementation before phase 4 of docs/plans/cards-at-scale.md. Do not
change it.
"""

import math
from dataclasses import dataclass

import numpy as np
import pypulseq as pp
from oracles.blocks import iter_blocks
from synthetic import GAMMA_1H as GAMMA

# The value of the package's `seq_utils.TIME_TOLERANCE` (s), kept separately so that the
# oracle does not depend on the package for it.
TIME_TOLERANCE = 1e-9

_AXES = ("x", "y", "z")


def _gradient_points(g, t0: float) -> tuple[np.ndarray, np.ndarray]:
    """The corner or sample times (s) and amplitudes (Hz/m) of one pypulseq gradient
    event that starts in a block that starts at `t0`, from the fields of the event.
    Written here, not imported from the package, so that the oracle is independent of
    `seq_utils.gradient_points`."""
    if g.type == "trap":
        times = np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
        amp = np.array([0.0, g.amplitude, g.amplitude, 0.0])
    else:
        times = np.concatenate([[0.0], np.asarray(g.tt, dtype=float), [g.shape_dur]])
        amp = np.concatenate([[g.first], np.asarray(g.waveform, dtype=float), [g.last]])
    return t0 + g.delay + times, amp


@dataclass(frozen=True)
class HardwareLimits:
    """The gradient hardware limits that a sequence is compared with.

    `label` is shown in the report, for example "pypulseq system limits" or a name for
    a specific scanner and gradient coil.
    """

    max_grad_mt_per_m: float
    max_slew_t_per_m_per_s: float
    label: str


@dataclass(frozen=True)
class AxisResult:
    """The peak values for one logical axis, over a time range.

    `peak_block` and `slew_block` are the block ID (`oracles.blocks.BlockTiming.block_id`)
    where the peak amplitude, respectively the peak slew, was found. `rms_mt_per_m` is
    the RMS amplitude over the range that `GradientPeaks.range_s` gives, not over the
    whole sequence when a window is used.
    """

    peak_mt_per_m: float
    peak_time_s: float
    peak_block: int | None
    max_slew_t_per_m_per_s: float
    slew_block: int | None
    rms_mt_per_m: float


@dataclass(frozen=True)
class GradientPeaks:
    """The result of `gradient_peaks`.

    `reason` is None when the range has at least one gradient event on some axis.
    Otherwise it is "no gradients" or "no gradients in the window" (the texts of
    `seq_index.NO_GRADIENTS` and `NO_GRADIENTS_IN_WINDOW`, written here), and every numeric field is its zero value: 0.0 for an amplitude,
    slew or RMS field, and 0.0 for `vector_peak_time_s`; every block field
    (`AxisResult.peak_block`, `AxisResult.slew_block`) is None. `range_s` still holds
    the range that was used.

    `vector_peak_mt_per_m` is the largest magnitude of the three-axis gradient vector
    over the range. There is no vector slew field. The RMS of the vector magnitude is
    the square root of the sum of the squares of the three axis RMS values, because the
    mean of |G|² is the sum of the three axis means of G².
    """

    reason: str | None
    range_s: tuple[float, float]
    axes: dict[str, AxisResult]
    vector_peak_mt_per_m: float
    vector_peak_time_s: float
    limits: HardwareLimits


def _default_limits(seq: pp.Sequence) -> HardwareLimits:
    # seq.system.max_grad and seq.system.max_slew are always stored in Hz/m and
    # Hz/m/s, whatever unit the caller gave pp.Opts, because pp.Opts.__init__
    # converts every unit to Hz/m (respectively Hz/m/s) with the sequence's own gamma
    # before it stores the value (verified in pypulseq's opts.py).
    return HardwareLimits(
        max_grad_mt_per_m=seq.system.max_grad / GAMMA * 1e3,
        max_slew_t_per_m_per_s=seq.system.max_slew / GAMMA,
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


class _AxisAccumulator:
    """The O(1) running state for one axis: the peak amplitude, the peak slew and the
    RMS accumulator, updated one clipped piece (one block's worth of points) at a time.
    All amplitudes here are in Hz/m, and slew in Hz/m/s, the units of `_gradient_points`.
    """

    def __init__(self) -> None:
        self.has_event = False
        self.peak_amp = 0.0
        self.peak_time = 0.0
        self.peak_block: int | None = None
        self.max_slew = 0.0
        self.slew_block: int | None = None
        self.rms_sum = 0.0  # sum of Δt · (a² + a·b + b²) / 3 over every piece so far

    def add_piece(self, t: np.ndarray, amp: np.ndarray, block_id: int) -> None:
        self.has_event = True
        abs_amp = np.abs(amp)
        i = int(np.argmax(abs_amp))
        if abs_amp[i] > self.peak_amp:
            self.peak_amp, self.peak_time, self.peak_block = (
                float(abs_amp[i]),
                float(t[i]),
                block_id,
            )

        dt = np.diff(t)
        a, b = amp[:-1], amp[1:]
        self.rms_sum += float(np.sum(dt * (a * a + a * b + b * b) / 3.0))

        valid = dt >= TIME_TOLERANCE
        if np.any(valid):
            slew = np.abs((b - a)[valid] / dt[valid])
            j = int(np.argmax(slew))
            if slew[j] > self.max_slew:
                self.max_slew, self.slew_block = float(slew[j]), block_id

    def result(self, range_length: float) -> AxisResult:
        rms_hz_per_m = math.sqrt(self.rms_sum / range_length)
        return AxisResult(
            peak_mt_per_m=self.peak_amp / GAMMA * 1e3,
            peak_time_s=self.peak_time,
            peak_block=self.peak_block,
            max_slew_t_per_m_per_s=self.max_slew / GAMMA,
            slew_block=self.slew_block,
            rms_mt_per_m=rms_hz_per_m / GAMMA * 1e3,
        )


def _vector_peak_in_block(
    axis_points: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[float, float]:
    """The time and the |G| value of the largest three-axis vector magnitude in one
    block, evaluated at the union of the breakpoints of the axes that have a clipped
    piece in `axis_points` (a subset of `_AXES`). An axis with no piece here is zero
    for the whole block. |G| is convex on a stretch where every axis is linear, so its
    maximum over the block is at one of these breakpoints."""
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


def gradient_peaks(
    seq: pp.Sequence,
    window: tuple[float, float] | None = None,
    limits: HardwareLimits | None = None,
) -> GradientPeaks:
    """The peak amplitude, the peak slew rate and the RMS amplitude of `seq`'s
    gradients, on each logical axis and as a three-axis vector, compared with
    `limits`.

    With `window=None`, the range is the whole sequence, `(0.0, total_duration)`.
    Otherwise `window` is `(start_s, end_s)` in seconds from the sequence start; it
    must have `start_s < end_s` and lie within the sequence
    (`0.0 <= start_s` and `end_s <= total_duration`, each within `TIME_TOLERANCE`),
    or this function raises `ValueError`. A gradient piece that crosses a range edge
    is cut at the edge, with the amplitude at the edge found by linear interpolation.

    With `limits=None`, the limits are `seq.system.max_grad` and `seq.system.max_slew`
    (see `HardwareLimits`).

    This function reads one block at a time (`oracles.blocks.iter_blocks`) and keeps only a
    constant amount of state for each axis, so its memory does not grow with the
    number of blocks.
    """
    if limits is None:
        limits = _default_limits(seq)

    # The same expression pypulseq's own Sequence.sequence module uses for a
    # sequence's total duration (verified by reading pypulseq's opts.py and
    # sequence.py at the version this project depends on).
    total_duration = sum(seq.block_durations.values())

    if window is None:
        range_s = (0.0, total_duration)
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
    lo, hi = range_s
    range_length = hi - lo

    axis_state = {axis: _AxisAccumulator() for axis in _AXES}
    vector_peak, vector_peak_time = 0.0, 0.0

    for block_id, block_start, block_duration, block in iter_blocks(seq):
        block_end = block_start + block_duration
        if block_end <= lo or block_start >= hi:
            continue
        axis_points: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for axis in _AXES:
            g = getattr(block, f"g{axis}", None)
            if g is None:
                continue
            t, amp = _gradient_points(g, block_start)
            t_clipped, amp_clipped = _clip_polyline(t, amp, lo, hi)
            if t_clipped.size < 2:
                continue
            axis_points[axis] = (t_clipped, amp_clipped)
            axis_state[axis].add_piece(t_clipped, amp_clipped, block_id)
        if axis_points:
            block_time, block_peak = _vector_peak_in_block(axis_points)
            if block_peak > vector_peak:
                vector_peak, vector_peak_time = block_peak, block_time

    has_event = any(state.has_event for state in axis_state.values())
    if not has_event:
        reason = "no gradients in the window" if window is not None else "no gradients"
        axes = {axis: AxisResult(0.0, 0.0, None, 0.0, None, 0.0) for axis in _AXES}
        return GradientPeaks(reason, range_s, axes, 0.0, 0.0, limits)

    axes = {axis: axis_state[axis].result(range_length) for axis in _AXES}
    return GradientPeaks(
        reason=None,
        range_s=range_s,
        axes=axes,
        vector_peak_mt_per_m=vector_peak / GAMMA * 1e3,
        vector_peak_time_s=vector_peak_time,
        limits=limits,
    )
