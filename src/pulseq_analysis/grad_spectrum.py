"""Gradient spectrum of a Pulseq sequence.

`gradient_spectrum` uses the same method as pypulseq's
`calculate_gradient_spectrum`: Hann windows (50 ms by default) with 50% overlap, the
magnitude spectrum of each window, and the maximum over windows. pypulseq
stops sampling at the last gradient point and starts the first window at 0.
Here the gradients are sampled to the end of the sequence and padded with half
a window of zeros at each end, so a sequence shorter than one window still has
a spectrum and gradients near either end are not attenuated by the window.

The gradients are sampled in chunks of `CHUNK_WINDOWS` windows, so the memory does not
grow with the length of the sequence. Each chunk starts at a multiple of the hop and
overlaps the next chunk by one window less one hop, so the chunks give the same windows
as one spectrogram of the whole padded waveform.

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

`docs/usage.md` section 8 gives the rule for all the values of the package.
"""

import math
import numbers
import weakref
from dataclasses import dataclass

import numpy as np
import pypulseq as pp
from scipy.signal import spectrogram

from ._equality import fields_equal
from .extensions import refuse_rotations
from .sampling import GradientSampler
from .seq_index import sequence_index

MAX_FREQUENCY_HZ = 2000.0
FFT_WINDOW_S = 0.05
FREQUENCY_OVERSAMPLING = 3.0
CHUNK_WINDOWS = 256  # windows in each chunk of samples

NO_GRADIENTS = "no gradients"


@dataclass(frozen=True, eq=False)
class GradientSpectrum:
    """The spectrum of one sequence, in Hz/m/sqrt(Hz). Each array is read-only, so that
    the callers of `gradient_spectrum_for` can share one result: convert to a new array
    (`s.rss * 1e3 / abs(gamma)`), not in place.

    `==` compares the values of the fields (`_equality.values_equal`): the arrays by dtype,
    shape and values, and `axes` with its keys in order. A `GradientSpectrum` is not
    hashable."""

    reason: str | None  # why there is no spectrum, or None
    frequency_hz: np.ndarray  # float64, F: 0 up to max_frequency_hz
    axes: dict[str, np.ndarray]  # "x", "y", "z": float64, F, spectrum, Hz/m/sqrt(Hz)
    rss: np.ndarray  # float64, F: RSS of the axes in each window, then the maximum
    # The arguments of the call, as floats, so that the result says how it was made.
    max_frequency_hz: float
    window_s: float
    frequency_oversampling: float

    __eq__ = fields_equal
    __hash__ = None  # type: ignore[assignment]


def _read_only(spectrum: GradientSpectrum) -> GradientSpectrum:
    """`spectrum`, with `writeable` off for each of its arrays."""
    for a in (spectrum.frequency_hz, spectrum.rss, *spectrum.axes.values()):
        a.flags.writeable = False
    return spectrum


def _number(name: str, value) -> float:
    """`value` as a float. Raises TypeError for a value that is not a real number (a bool
    is not) and ValueError for one that is not finite."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a number, not {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, not {value}")
    return value


def _validated_arguments(
    seq: pp.Sequence,
    max_frequency_hz: float,
    window_s: float,
    frequency_oversampling: float,
) -> tuple[float, float, float]:
    """The three arguments of `gradient_spectrum` as floats, in this order. Raises
    TypeError or ValueError for a refused value (the rules are in the docstring of
    `gradient_spectrum`). It reads the gradient raster of `seq`, and no block."""
    max_frequency_hz = _number("max_frequency_hz", max_frequency_hz)
    window_s = _number("window_s", window_s)
    frequency_oversampling = _number("frequency_oversampling", frequency_oversampling)
    if window_s <= 0:
        raise ValueError(f"window_s must be above 0, not {window_s}")
    dt = seq.grad_raster_time
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


def gradient_spectrum(
    seq: pp.Sequence,
    *,
    max_frequency_hz: float = MAX_FREQUENCY_HZ,
    window_s: float = FFT_WINDOW_S,
    frequency_oversampling: float = FREQUENCY_OVERSAMPLING,
) -> GradientSpectrum:
    """The spectrum of each gradient axis up to `max_frequency_hz`, and its RSS, in
    Hz/m/sqrt(Hz) (see the module docstring for the conversion).

    The arguments are those of pypulseq's `calculate_gradient_spectrum`, with the same
    defaults: `max_frequency_hz` is the highest frequency of the result (`max_frequency`),
    `window_s` is the length of a Hann window (`window_width`), and
    `frequency_oversampling` gives the FFT length, `nfft = round(frequency_oversampling *
    nwin)` for a window of `nwin` samples. The overlap is `nwin // 2`.

    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`), TypeError for an argument that is not a number (a
    bool is not), and ValueError for an argument that is not finite, for `window_s` not
    above 0 or less than 2 samples at the gradient raster of the file, for
    `frequency_oversampling` below 1, and for `max_frequency_hz` not above 0, above the
    Nyquist frequency `1 / (2 * dt)`, or below the frequency step `1 / (nfft * dt)`
    (the result then has fewer than two frequencies). The arguments are checked before the
    blocks are read.
    """
    refuse_rotations(seq)
    max_frequency_hz, window_s, frequency_oversampling = _validated_arguments(
        seq, max_frequency_hz, window_s, frequency_oversampling
    )
    index = sequence_index(seq)
    if not (index.gx.any() or index.gy.any() or index.gz.any()):
        empty = np.zeros(0)
        return _read_only(
            GradientSpectrum(
                NO_GRADIENTS, empty, {}, empty, max_frequency_hz, window_s, frequency_oversampling
            )
        )
    sampler = GradientSampler(seq, index)

    # The file's raster ([DEFINITIONS]): `Sequence.read` does not change `seq.system`.
    dt = seq.grad_raster_time
    nwin = round(window_s / dt)
    nfft = round(frequency_oversampling * nwin)
    pad = nwin // 2
    # Python's `sum` is compensated (Python 3.12), so this total can differ from
    # `index.end_s`, the sequential sum, by one sample. The oracle
    # (tests/oracles/grad_spectrum.py) has the same line, and the oracle tests
    # compare the two. Do not change it to `index.end_s`.
    nt = math.ceil(sum(seq.block_durations.values()) / dt)

    # The padded waveform has n samples: pad zeros, the nt gradient samples, pad zeros.
    # scipy's spectrogram does not pad, so window j covers samples [j * hop, j * hop + nwin).
    n = nt + 2 * pad  # n >= nwin: after the NO_GRADIENTS return, nt >= 1
    hop = nwin - nwin // 2
    num_windows = (n - nwin) // hop + 1

    axes_max: dict[str, np.ndarray] = {}
    rss_max = None
    keep = None  # the frequencies to keep: the same for each chunk
    for first in range(0, num_windows, CHUNK_WINDOWS):
        last = min(first + CHUNK_WINDOWS, num_windows)
        # The samples of windows first to last - 1.
        start = first * hop
        stop = (last - 1) * hop + nwin
        rss_sq = 0.0
        for axis in "xyz":
            freq, sxx = _chunk_spectrogram(
                sampler, f"g{axis}", start, stop, pad, nt, dt, nwin, nfft
            )
            if keep is None:
                keep = freq <= max_frequency_hz + 1e-6
            sxx = sxx[keep]
            chunk_max = sxx.max(axis=1)
            axes_max[axis] = (
                chunk_max if axis not in axes_max else np.maximum(axes_max[axis], chunk_max)
            )
            rss_sq = rss_sq + sxx**2
        chunk_rss = np.sqrt(rss_sq).max(axis=1)
        rss_max = chunk_rss if rss_max is None else np.maximum(rss_max, chunk_rss)
    freq = freq[keep]
    return _read_only(
        GradientSpectrum(
            None, freq, axes_max, rss_max, max_frequency_hz, window_s, frequency_oversampling
        )
    )


# For each sequence object: the number of blocks, the last block id (the rule of
# `seq_index.sequence_index`) and one `GradientSpectrum` for each tuple of
# (max_frequency_hz, window_s, frequency_oversampling) as floats.
_Kept = tuple[int, int, dict[tuple[float, float, float], GradientSpectrum]]
_SPECTRUM_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Kept]" = weakref.WeakKeyDictionary()


def gradient_spectrum_for(
    seq: pp.Sequence,
    *,
    max_frequency_hz: float = MAX_FREQUENCY_HZ,
    window_s: float = FFT_WINDOW_S,
    frequency_oversampling: float = FREQUENCY_OVERSAMPLING,
) -> GradientSpectrum:
    """The `GradientSpectrum` of `seq` (`gradient_spectrum`, which has the rules of the
    arguments: a refused value raises before the kept result is looked up).

    The result is kept for the sequence object and for each tuple of the three arguments as
    floats, so that callers of one sequence that need the same spectrum (for example the
    analysis of each target of one sequence) calculate it one time. The kept results are
    built again when the number of blocks or the last block id changed, for example after
    `add_block` (the rule of `seq_index.sequence_index`). The arrays of a result are
    read-only, because all callers share them.
    """
    key = _validated_arguments(seq, max_frequency_hz, window_s, frequency_oversampling)
    block_events = seq.block_events
    num_blocks = len(block_events)
    last_id = int(next(reversed(block_events))) if num_blocks else 0
    kept = _SPECTRUM_CACHE.get(seq)
    if kept is None or kept[0] != num_blocks or kept[1] != last_id:
        kept = (num_blocks, last_id, {})
        _SPECTRUM_CACHE[seq] = kept
    by_key = kept[2]
    if key not in by_key:
        by_key[key] = gradient_spectrum(
            seq,
            max_frequency_hz=key[0],
            window_s=key[1],
            frequency_oversampling=key[2],
        )
    return by_key[key]


def _chunk_spectrogram(sampler, axis, start, stop, pad, nt, dt, nwin, nfft):
    """The frequencies and the magnitude spectrogram of samples [start, stop) of one
    axis's padded waveform, with the arguments of pypulseq's
    `calculate_gradient_spectrum`. `axis` is "gx", "gy" or "gz" (`sampling.GradientSampler`'s
    axis names); `sampler` gives the axis's waveform (Hz/m), 0 before the first event and
    after the last one, so an axis with no gradient gives an all-zero chunk. `nfft` is the
    FFT length."""
    w = np.zeros(stop - start)
    # Sequence sample i is at (i + 0.5) * dt, and is padded sample i + pad.
    lo, hi = max(start - pad, 0), min(stop - pad, nt)
    if hi > lo:
        t = (np.arange(lo, hi) + 0.5) * dt
        w[lo + pad - start : hi + pad - start] = sampler.sample(axis, t)
    freq, _, sxx = spectrogram(
        w,
        fs=1 / dt,
        mode="magnitude",
        nperseg=nwin,
        noverlap=nwin // 2,
        nfft=nfft,
        detrend="constant",
        window=("tukey", 1),
    )
    return freq, sxx
