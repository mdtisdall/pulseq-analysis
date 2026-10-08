"""Gradient spectrum of a Pulseq sequence.

`gradient_spectrum` uses the same method as pypulseq's
`calculate_gradient_spectrum`: Hann windows (50 ms by default) with 50% overlap, the
magnitude spectrum of each window, and the maximum over windows. pypulseq
stops sampling at the last gradient point and starts the first window at 0.
Here the gradients are sampled to the end of the sequence and padded with half
a window of zeros at the start, and with half a window or more at the end, so a sequence
shorter than one window still has a spectrum. The end padding is the fewest zeros, at
least half a window, that make the padded waveform one window plus a whole number of hops
long (a hop is the step between two windows). Then each sample, the last one too, is within
half a hop of the centre of some window, as a sample in the middle of the sequence is, so
the window attenuates a gradient near the end no more than one in the middle. The number of
samples is `sampling.sequence_samples`, the rule of the whole package.

The gradients are the waveform of `sampling.GradientSampler.sample`, the model of MATLAB
Pulseq (`docs/implementation.md`, "The gradient waveform"). pypulseq's `calculate_gradient_spectrum`
uses `Sequence.get_gradients()`, which draws a line across each gap between two events. The
two spectra differ for a sequence with an event that starts or ends at a value that is not 0
next to a gap of more than one raster time (the model has a ramp to 0 and from 0 of half a
raster time each, and 0 between them), and with a step at a block junction.

The gradients are sampled in chunks of `_CHUNK_WINDOWS` windows, so the memory does not
grow with the length of the sequence. Each chunk starts at a multiple of the hop and
overlaps the next chunk by one window less one hop, so the chunks give the same windows
as one spectrogram of the whole padded waveform.

pypulseq makes the windows with scipy's `spectrogram` (mode="magnitude"), which calculates
the magnitude of every FFT bin. Here `_chunk_spectrogram` gives the same values with
the same steps as scipy: the windows, the constant detrend, the Hann window, the FFT
(`scipy.fft.rfft` in one thread) and the scale of the magnitude mode. The windows are a
read-only view of the samples of the chunk, and the magnitude is taken only of the bins up
to `max_frequency_hz`, about 1/25 of the bins at the defaults, so the chunk needs less
memory and time than scipy's call. The values agree with scipy's to the float rounding
(`tests/test_grad_spectrum.py`, `test_matches_scipy_spectrogram`).

The spectrum is in Hz/m/sqrt(Hz), the unit of the gradients of a .seq file, with no
gamma. A change to T/m needs gamma, the gyromagnetic ratio of the nucleus that the scanner
images. The .seq file does not give gamma: it is data of the target, not of the sequence.
Thus the spectrum depends only on the sequence.

To get mT/m/sqrt(Hz) for a gamma in Hz/T, multiply each value by `1e3 / abs(gamma)`. For
1H, gamma is 42.576 MHz/T, and 1 Hz/m/sqrt(Hz) is 2.3487e-5 mT/m/sqrt(Hz). The
conversion is exact to the float rounding, because each step of the method changes in
proportion to a positive scale of the waveform: the constant detrend, the Hann window,
the magnitude of the FFT, the maximum over windows and the root-sum-of-squares of the
three axes. This includes the RSS spectrum.

`docs/usage.md` section 9 gives the rule for all the values of the package.
"""

import numpy as np
from scipy import fft as scipy_fft
from scipy.signal import get_window

from ._equality import FrozenDict, _freeze, value_dataclass
from ._validate import real
from .sampling import gradient_sampler, sequence_samples
from .seq_index import NO_GRADIENTS, has_gradients, sequence_index
from .seq_utils import _AXES, _GRAD_COLUMNS
from .snapshot import Snapshot, _check_snapshot, _kept_results

MAX_FREQUENCY_HZ = 2000.0
FFT_WINDOW_S = 0.05
FREQUENCY_OVERSAMPLING = 3.0
_CHUNK_WINDOWS = 256  # windows in each chunk of samples


@value_dataclass
class GradientSpectrum:
    """The spectrum of one sequence, in Hz/m/sqrt(Hz). Each array is read-only, and `axes` is
    a read-only `series.FrozenDict` (a subclass of `dict`), so that the callers of
    `gradient_spectrum` can share one result: convert to a new array
    (`s.rss * 1e3 / abs(gamma)`), not in place.

    `==` compares the values of the fields (`_equality.values_equal`): the arrays by dtype,
    shape and values, and `axes` with its keys in order. A `GradientSpectrum` is not
    hashable. For `NO_GRADIENTS`, `frequency_hz` and `rss` are empty, and `axes` has the
    keys "x", "y" and "z", each an empty array."""

    reason: str | None  # why there is no spectrum (NO_GRADIENTS), or None
    frequency_hz: np.ndarray  # float64, F: 0 up to max_frequency_hz
    axes: FrozenDict[str, np.ndarray]  # "x", "y", "z": float64, F, spectrum, Hz/m/sqrt(Hz)
    rss: np.ndarray  # float64, F: RSS of the axes in each window, then the maximum
    # The arguments of the call, as floats, so that the result says how it was made.
    max_frequency_hz: float
    window_s: float
    frequency_oversampling: float


def _validated_arguments(
    snap: Snapshot,
    max_frequency_hz: float,
    window_s: float,
    frequency_oversampling: float,
) -> tuple[float, float, float]:
    """The three arguments of `gradient_spectrum` as floats, in this order. Raises
    TypeError or ValueError for a refused value (the rules are in the docstring of
    `gradient_spectrum`). The rules that need the gradient raster come after the type of
    `snap` is checked (`_check_snapshot`), because the raster is the one of the sequence of
    `snap`. It reads no block."""
    max_frequency_hz = real("max_frequency_hz", max_frequency_hz)
    window_s = real("window_s", window_s, positive=True)
    frequency_oversampling = real("frequency_oversampling", frequency_oversampling)
    _check_snapshot(snap)
    dt = snap.sequence.grad_raster_time
    nwin = round(window_s / dt)
    if nwin < 2:
        raise ValueError(
            f"window_s {window_s} is {nwin} samples at the gradient raster {dt}: it must be "
            "2 or more"
        )
    if frequency_oversampling < 1:
        raise ValueError(f"frequency_oversampling must be 1 or more, not {frequency_oversampling}")
    nfft = round(frequency_oversampling * nwin)
    nyquist_hz = 1 / (2 * dt)
    step_hz = 1 / (nfft * dt)
    if max_frequency_hz <= 0:
        raise ValueError(f"max_frequency_hz must be above 0, not {max_frequency_hz}")
    if max_frequency_hz > nyquist_hz:
        raise ValueError(
            f"max_frequency_hz {max_frequency_hz} is above the Nyquist frequency {nyquist_hz} Hz"
        )
    if max_frequency_hz < step_hz:
        raise ValueError(
            f"max_frequency_hz {max_frequency_hz} is below the frequency step {step_hz} Hz"
        )
    return max_frequency_hz, window_s, frequency_oversampling


# The kept results of a snapshot (`snapshot._kept_results`) that this module makes: one
# `GradientSpectrum` for each key `("spectrum", max_frequency_hz, window_s,
# frequency_oversampling)`, with the three arguments as floats.


def gradient_spectrum(
    snap: Snapshot,
    *,
    max_frequency_hz: float = MAX_FREQUENCY_HZ,
    window_s: float = FFT_WINDOW_S,
    frequency_oversampling: float = FREQUENCY_OVERSAMPLING,
) -> GradientSpectrum:
    """The spectrum of each gradient axis of `snap` (`snapshot.load`) up to `max_frequency_hz`,
    and its RSS, in Hz/m/sqrt(Hz) (see the module docstring for the conversion).

    The waveform is the model of MATLAB Pulseq (see the module docstring), not the one of
    pypulseq's `calculate_gradient_spectrum`, for a sequence with an event that starts or
    ends at a value that is not 0 next to a gap of more than one raster time.

    The arguments are those of pypulseq's `calculate_gradient_spectrum`, with the same
    defaults: `max_frequency_hz` is the highest frequency of the result (`max_frequency`),
    `window_s` is the length of a Hann window (`window_width`), and
    `frequency_oversampling` gives the FFT length, `nfft = round(frequency_oversampling *
    nwin)` for a window of `nwin` samples. The overlap is `nwin // 2`.

    The result is kept on the snapshot, for each tuple of the three arguments as floats, so
    that callers of one snapshot that need the same spectrum (for example the analysis of
    each target of one sequence) calculate it one time. The sequence of a snapshot does not
    change, so a kept result is never old. The arrays of a result are read-only, because all
    callers share them.

    Raises TypeError for an argument that is not a number (a bool is not) and for a `snap`
    that is not a `snapshot.Snapshot` (the message names `load`), and ValueError for an
    argument that is not finite or is too large for a float, for `window_s` not
    above 0 or less than 2 samples at the gradient raster of the file, for
    `frequency_oversampling` below 1, and for `max_frequency_hz` not above 0, above the
    Nyquist frequency `1 / (2 * dt)`, or below the frequency step `1 / (nfft * dt)`
    (the result then has fewer than two frequencies). The three arguments are checked for a
    number first, then the type of `snap` (the other rules need its gradient raster). All are
    checked before the blocks are read and before the kept result is looked up.
    """
    key = _validated_arguments(snap, max_frequency_hz, window_s, frequency_oversampling)
    kept = _kept_results(snap)
    kept_key = ("spectrum", *key)
    if kept_key not in kept:
        kept[kept_key] = _compute_spectrum(snap, *key)
    return kept[kept_key]


def _compute_spectrum(
    snap: Snapshot,
    max_frequency_hz: float,
    window_s: float,
    frequency_oversampling: float,
) -> GradientSpectrum:
    """The spectrum of `snap` for three arguments that `_validated_arguments` has checked
    (as floats). It does not check them again and does not keep the result."""
    index = sequence_index(snap)
    if not has_gradients(index):
        # Each array is its own, as `_freeze` makes a copy of each.
        frequency_hz, rss, *axes = _freeze(*(np.zeros(0) for _ in range(5)))
        return GradientSpectrum(
            NO_GRADIENTS,
            frequency_hz,
            FrozenDict(zip(_AXES, axes, strict=True)),
            rss,
            max_frequency_hz,
            window_s,
            frequency_oversampling,
        )
    sampler = gradient_sampler(snap)

    # The file's raster ([DEFINITIONS]): `Sequence.read` does not change the `system` of the
    # sequence.
    dt = snap.sequence.grad_raster_time
    nwin = round(window_s / dt)
    nfft = round(frequency_oversampling * nwin)
    freq = np.fft.rfftfreq(nfft, dt)
    keep_n = int(np.count_nonzero(freq <= max_frequency_hz + 1e-6))  # bins 0 to keep_n - 1
    window = get_window(("tukey", 1), nwin)  # the Hann window of pypulseq
    pad = nwin // 2
    nt = sequence_samples(index, dt)

    # The padded waveform is `pad` zeros, the nt gradient samples, and the end padding of
    # zeros. scipy's spectrogram does not pad, so window j covers samples
    # [j * hop, j * hop + nwin) of it. The first window is at the start, so the first
    # sample is at the centre of the first window, up to half a sample. The end padding
    # is the least that is at least `pad` and ends the padded waveform with a whole window
    # after a whole number of hops: `pad + (-nt) % hop` zeros for an even `nwin`. Then each
    # sample, the last one too, is within half a hop of the centre of some window, as a
    # sample in the middle of the sequence is, so the window attenuates a gradient at the
    # end no more than one in the middle. (`pad` zeros alone leave the last samples near
    # the edge of the last window when `nt` is not a whole number of hops.)
    # `nt >= 1` after the NO_GRADIENTS return, so `nt + 2 * pad - nwin >= 0`.
    hop = nwin - nwin // 2
    num_windows = -(-(nt + 2 * pad - nwin) // hop) + 1

    axes_max: dict[str, np.ndarray] = {}
    rss_max = None
    for first in range(0, num_windows, _CHUNK_WINDOWS):
        last = min(first + _CHUNK_WINDOWS, num_windows)
        # The samples of windows first to last - 1.
        start = first * hop
        stop = (last - 1) * hop + nwin
        rss_sq = 0.0
        for axis, column in zip(_AXES, _GRAD_COLUMNS, strict=True):
            sxx = _chunk_spectrogram(
                sampler, column, start, stop, pad, nt, dt, nwin, nfft, keep_n, window
            )
            chunk_max = sxx.max(axis=1)
            axes_max[axis] = (
                chunk_max if axis not in axes_max else np.maximum(axes_max[axis], chunk_max)
            )
            rss_sq = rss_sq + sxx**2
        chunk_rss = np.sqrt(rss_sq).max(axis=1)
        rss_max = chunk_rss if rss_max is None else np.maximum(rss_max, chunk_rss)
    frequency_hz, rss, *axes = _freeze(freq[:keep_n], rss_max, *(axes_max[axis] for axis in _AXES))
    return GradientSpectrum(
        None,
        frequency_hz,
        FrozenDict(zip(_AXES, axes, strict=True)),
        rss,
        max_frequency_hz,
        window_s,
        frequency_oversampling,
    )


def _chunk_spectrogram(sampler, axis, start, stop, pad, nt, dt, nwin, nfft, keep_n, window):
    """The magnitude spectrogram of samples [start, stop) of one axis's padded waveform, for
    the first `keep_n` frequencies (`np.fft.rfftfreq(nfft, dt)`), with shape (`keep_n`,
    windows) and dtype float64. The values are those of scipy's `spectrogram` with the
    arguments of pypulseq's `calculate_gradient_spectrum` (mode="magnitude", `nperseg=nwin`,
    `noverlap=nwin // 2`, `nfft=nfft`, detrend="constant", window=("tukey", 1), `fs=1 / dt`),
    to the float rounding. `[start, stop)` holds a whole number of windows. `axis` is "gx",
    "gy" or "gz" (`sampling.GradientSampler`'s axis names); `sampler` gives the axis's
    waveform (Hz/m), 0 before the first event and after the last one, so an axis with no
    gradient gives an all-zero chunk. `nfft` is the FFT length, and `window` is the Hann
    window of `nwin` samples.

    The steps are those of scipy's `_spectral_helper`: the windows (a read-only view with a
    hop of `nwin - nwin // 2`), the mean of each window taken off, the window function, the
    FFT with `nfft` points (`scipy.fft.rfft` in one thread), and the scale of the magnitude
    mode with the density scaling, `sqrt(1 / (fs * sum(window**2)))`. Only the `keep_n` bins
    are made into magnitudes."""
    w = np.zeros(stop - start)
    # Sequence sample i is at (i + 0.5) * dt, and is padded sample i + pad.
    lo, hi = max(start - pad, 0), min(stop - pad, nt)
    if hi > lo:
        t = (np.arange(lo, hi) + 0.5) * dt
        w[lo + pad - start : hi + pad - start] = sampler.sample(axis, t)
    # This duplicates the steps of scipy's `spectrogram` (its `_spectral_helper` with
    # mode="magnitude") to save memory. scipy makes the magnitude of all nfft // 2 + 1 bins
    # and has no argument for fewer, but the result keeps only the first `keep_n` (about
    # 1/25 at the defaults). Here the bins are cut before `np.abs`: on
    # `build_repeating(10000)` with the defaults, the peak memory of `gradient_spectrum` is
    # 54 MB instead of 85 MB, and the time 0.53 s instead of 0.63 s. scipy's `ZoomFFT`,
    # which makes only a range of bins, was slower and used more memory here.
    # `test_matches_scipy_spectrogram` compares these values with scipy's, so a change of
    # the steps in scipy fails that test.
    hop = nwin - nwin // 2
    num_windows = (w.size - nwin) // hop + 1
    windows = np.lib.stride_tricks.as_strided(
        w, shape=(num_windows, nwin), strides=(w.strides[0] * hop, w.strides[0]), writeable=False
    )
    scale = np.sqrt(1.0 / ((1 / dt) * (window * window).sum()))
    detrended = (windows - windows.mean(axis=1, keepdims=True)) * window
    kept = scipy_fft.rfft(detrended, n=nfft, axis=1, workers=1)[:, :keep_n]
    return np.abs(kept).T * scale
