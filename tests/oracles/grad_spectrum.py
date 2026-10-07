"""Gradient spectrum of a Pulseq sequence, and its largest values in the acoustic
resonance bands that the caller gives.

Oracle: the earlier implementation, which samples through `Sequence.get_gradients()`. Do
not change its method. A resonance is a pair (frequency_hz, bandwidth_hz), the centre
frequency and the full width of its band in Hz, as in the library; the default is no
resonance.

`gradient_spectrum` uses the same method as pypulseq's
`calculate_gradient_spectrum`: 50 ms Hann windows with 50% overlap, the
magnitude spectrum of each window, and the maximum over windows. pypulseq
stops sampling at the last gradient point and starts the first window at 0.
Here the gradients are sampled to the end of the sequence and padded with half
a window of zeros at the start, and with half a window or more at the end, so a sequence
shorter than one window still has a spectrum. The end padding makes the last sample
within half a hop of the centre of a window, as in the middle of the sequence.

The gradients are sampled in chunks of `CHUNK_WINDOWS` windows, so the memory does not
grow with the length of the sequence. Each chunk starts at a multiple of the hop and
overlaps the next chunk by one window less one hop, so the chunks give the same windows
as one spectrogram of the whole padded waveform.
"""

import math
from dataclasses import dataclass

import numpy as np
import pypulseq as pp
from scipy.signal import spectrogram

MAX_FREQUENCY_HZ = 2000.0
WINDOW_S = 0.05
FREQUENCY_OVERSAMPLING = 3
CHUNK_WINDOWS = 256  # windows in each chunk of samples

NO_GRADIENTS = "no gradients"


@dataclass(frozen=True)
class BandPeak:
    resonance: tuple[float, float]  # (frequency_hz, bandwidth_hz) of the band
    peak: float  # largest RSS spectrum value in the band, mT/m/sqrt(Hz)
    frequency_hz: float  # where that value is
    relative: float  # peak / the largest RSS spectrum value at any frequency


@dataclass(frozen=True)
class GradientSpectrum:
    reason: str | None  # why there is no spectrum, or None
    resonances: tuple[tuple[float, float], ...]
    frequency_hz: np.ndarray
    axes: dict[str, np.ndarray]  # "x", "y", "z": spectrum, mT/m/sqrt(Hz)
    rss: np.ndarray  # root-sum-of-squares of the axes in each window, then the maximum
    band_peaks: tuple[BandPeak, ...]


def gradient_spectrum(
    seq: pp.Sequence,
    resonances: tuple[tuple[float, float], ...] = (),
) -> GradientSpectrum:
    """The spectrum of each gradient axis up to `MAX_FREQUENCY_HZ`, and the largest
    RSS value in each resonance band."""
    gradients = seq.get_gradients()
    if all(g is None for g in gradients):
        empty = np.zeros(0)
        return GradientSpectrum(NO_GRADIENTS, resonances, empty, {}, empty, ())

    dt = seq.grad_raster_time
    nwin = round(WINDOW_S / dt)
    pad = nwin // 2
    to_mt = 1e3 / seq.system.gamma  # Hz/m to mT/m
    nt = _num_samples(seq, dt)

    # The padded waveform has n samples: pad zeros, the nt gradient samples, and the end
    # padding. scipy's spectrogram does not pad, so window j covers samples
    # [j * hop, j * hop + nwin). The end padding is `pad + (-nt) % hop` zeros for an even
    # nwin, so that n - nwin is a whole number of hops, and the last sample is within half
    # a hop of the centre of a window. For an odd nwin, n - nwin is `nt + r - 1`, so the
    # padding is `pad + (1 - nt) % hop`.
    hop = nwin - nwin // 2
    n = nt + pad + pad + (nwin % 2 - nt) % hop
    num_windows = (n - nwin) // hop + 1

    axes_max: dict[str, np.ndarray] = {}
    rss_max = None
    freq = None
    for first in range(0, num_windows, CHUNK_WINDOWS):
        last = min(first + CHUNK_WINDOWS, num_windows)
        # The samples of windows first to last - 1.
        start = first * hop
        stop = (last - 1) * hop + nwin
        rss_sq = 0.0
        for axis, g in zip("xyz", gradients):
            freq, sxx = _chunk_spectrogram(g, start, stop, pad, nt, dt, nwin, to_mt)
            keep = freq <= MAX_FREQUENCY_HZ + 1e-6
            sxx = sxx[keep]
            chunk_max = sxx.max(axis=1)
            axes_max[axis] = (
                chunk_max if axis not in axes_max else np.maximum(axes_max[axis], chunk_max)
            )
            rss_sq = rss_sq + sxx**2
        chunk_rss = np.sqrt(rss_sq).max(axis=1)
        rss_max = chunk_rss if rss_max is None else np.maximum(rss_max, chunk_rss)
    freq = freq[freq <= MAX_FREQUENCY_HZ + 1e-6]
    return GradientSpectrum(
        None, resonances, freq, axes_max, rss_max, _band_peaks(freq, rss_max, resonances)
    )


def _chunk_spectrogram(g, start, stop, pad, nt, dt, nwin, to_mt):
    """The frequencies and the magnitude spectrogram of samples [start, stop) of one
    axis's padded waveform, with the arguments of pypulseq's
    `calculate_gradient_spectrum`. `g` is the axis's piecewise polynomial from
    `Sequence.get_gradients` (Hz/m), or None for an axis with no gradient."""
    w = np.zeros(stop - start)
    if g is not None:
        # Sequence sample i is at (i + 0.5) * dt, and is padded sample i + pad.
        lo, hi = max(start - pad, 0), min(stop - pad, nt)
        if hi > lo:
            t = (np.arange(lo, hi) + 0.5) * dt
            inside = (t >= g.x[0]) & (t <= g.x[-1])
            w[lo + pad - start : hi + pad - start][inside] = g(t[inside]) * to_mt
    freq, _, sxx = spectrogram(
        w,
        fs=1 / dt,
        mode="magnitude",
        nperseg=nwin,
        noverlap=nwin // 2,
        nfft=FREQUENCY_OVERSAMPLING * nwin,
        detrend="constant",
        window=("tukey", 1),
    )
    return freq, sxx


def _num_samples(seq: pp.Sequence, dt: float) -> int:
    """The number of samples of the sequence: the sum of `round(duration / dt)` of the
    blocks when each block is within 1e-6 samples of a whole number, else
    `ceil((end - 1e-10) / dt)` with `end` the sequential sum of the block durations (at
    least 0)."""
    durations = [seq.block_durations[b] for b in seq.block_events]
    lengths = [round(d / dt) for d in durations]
    if all(abs(d / dt - n) <= 1e-6 for d, n in zip(durations, lengths)):
        return sum(lengths)
    end = 0.0
    for d in durations:
        end += d
    return max(math.ceil((end - 1e-10) / dt), 0)


def _band_peaks(
    freq: np.ndarray, rss: np.ndarray, resonances: tuple[tuple[float, float], ...]
) -> tuple[BandPeak, ...]:
    """The largest RSS value in each resonance band that has a frequency bin."""
    peak = float(rss.max())
    band_peaks = []
    for r in resonances:
        low_hz, high_hz = r[0] - r[1] / 2, r[0] + r[1] / 2
        inside = np.flatnonzero((freq >= low_hz) & (freq <= high_hz))
        if inside.size == 0:
            continue
        i = inside[np.argmax(rss[inside])]
        band_peaks.append(
            BandPeak(
                resonance=r,
                peak=float(rss[i]),
                frequency_hz=float(freq[i]),
                relative=float(rss[i]) / peak if peak > 0 else 0.0,
            )
        )
    return tuple(band_peaks)
