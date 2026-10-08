"""Helpers that read one event of a pypulseq sequence, and the time tolerance of the
measurements.

`gradient_offsets` and `gradient_points` give the corner or sample points of a gradient
event, the points that `grad_peaks` and `sampling` join with straight lines.
"""

import numpy as np

# The tolerance of a comparison of two times. A segment shorter than this has no slope.
TIME_TOLERANCE = 1e-9  # s
# The names of the three gradient axes, as the keys of the per-axis results.
_AXES = ("x", "y", "z")
# The names of the gradient columns of a block, one for each axis of `_AXES`.
_GRAD_COLUMNS = ("gx", "gy", "gz")


def gradient_offsets(g) -> tuple[float, np.ndarray, np.ndarray]:
    """The delay (s) and the offsets (s) and amplitudes (Hz/m) of one gradient event's
    corner or sample points, relative to the delay."""
    if g.type == "trap":
        offsets = np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
        amp = np.array([0.0, g.amplitude, g.amplitude, 0.0])
    else:
        offsets = np.concatenate([[0.0], np.asarray(g.tt, dtype=float), [g.shape_dur]])
        amp = np.concatenate([[g.first], np.asarray(g.waveform, dtype=float), [g.last]])
    return g.delay, offsets, amp


def gradient_points(g, t0: float) -> tuple[np.ndarray, np.ndarray]:
    """Corner or sample times (s) and amplitudes (Hz/m) of one gradient event."""
    delay, offsets, amp = gradient_offsets(g)
    return (t0 + delay) + offsets, amp
