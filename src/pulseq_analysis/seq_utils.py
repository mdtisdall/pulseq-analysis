"""Helpers that read one event of a pypulseq sequence, and the constants of the
measurements.

`gradient_offsets` and `gradient_points` give the corner or sample points of a gradient
event, the points that `grad_limits` and `sampling` join with straight lines.
`hold_samples` gives the samples of an RF event on a regular raster. It is for a caller
that measures or draws the RF (pulseq-reports, for example).
"""

from types import SimpleNamespace

import numpy as np

# The default gamma of `grad_limits` (1H), in Hz/T.
GAMMA = 42.576e6  # Hz/T
# The tolerance of a comparison of two times. A segment shorter than this has no slope.
TIME_TOLERANCE = 1e-9  # s


def hold_samples(rf: SimpleNamespace, raster: float) -> tuple[np.ndarray, float]:
    """RF samples (Hz, complex), each held for dt (s).

    A shape with uniform samples that fill shape_dur is used as it is. Other shapes,
    for example a block pulse with samples at its start and end, are interpolated
    linearly at the centers of raster intervals.
    """
    t = np.asarray(rf.t, dtype=float)
    signal = np.asarray(rf.signal, dtype=complex)
    if len(t) > 1:
        dt = t[1] - t[0]
        uniform = np.allclose(np.diff(t), dt, rtol=1e-6, atol=TIME_TOLERANCE)
        if uniform and abs(len(t) * dt - rf.shape_dur) <= TIME_TOLERANCE:
            return signal, dt
    n = max(1, round(rf.shape_dur / raster))
    dt = rf.shape_dur / n
    centers = (np.arange(n) + 0.5) * dt
    return np.interp(centers, t, signal.real) + 1j * np.interp(centers, t, signal.imag), dt


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
