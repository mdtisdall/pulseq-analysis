import copy
import inspect
import math
import pickle

import numpy as np
import pypulseq as pp
import pytest
from oracles import grad_spectrum as oracle
from scale_sequences import TR_BLOCKS, build_repeating, build_worst
from scipy.signal import spectrogram
from synthetic import (
    GAMMA_1H,
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)
from test_extensions import _with_rotation_library

from pulseq_analysis import grad_spectrum
from pulseq_analysis.sampling import GradientSampler
from pulseq_analysis.seq_index import sequence_index

# A Hann window's amplitude spectral density of a 1 mT/m sine on a frequency bin:
# A/2 * sum(w) / sqrt(fs * sum(w^2)), with 5000 samples at 100 kHz.
SINE_1MT_PEAK = 0.5 * 0.5 / math.sqrt(1e5 * 0.375 / 5000)
# The same peak in Hz/m/sqrt(Hz): the sine of `_sine_sequence` is 1 mT/m, which is
# 1e-3 * gamma Hz/m, and the spectrum is linear in the amplitude.
SINE_PEAK = SINE_1MT_PEAK * 1e-3 * SYSTEM.gamma


def _sine_sequence(frequency_hz: float, duration_s: float = 0.5, delay_s: float = 0.0):
    seq = pp.Sequence(SYSTEM)
    t = np.arange(round(duration_s / SYSTEM.grad_raster_time)) * SYSTEM.grad_raster_time
    waveform = 1e-3 * SYSTEM.gamma * np.sin(2 * np.pi * frequency_hz * t)  # 1 mT/m
    seq.add_block(
        pp.make_arbitrary_grad("x", waveform, first=0, last=0, delay=delay_s, system=SYSTEM)
    )
    return seq


def _assert_same_spectrum(a, b):
    np.testing.assert_array_equal(a.frequency_hz, b.frequency_hz)
    assert list(a.axes) == list(b.axes)
    for axis in a.axes:
        np.testing.assert_allclose(a.axes[axis], b.axes[axis], rtol=1e-12, atol=0)
    np.testing.assert_allclose(a.rss, b.rss, rtol=1e-12, atol=0)


def test_spin_echo_spectrum():
    s = grad_spectrum.gradient_spectrum(spin_echo_sequence())
    assert s.reason is None
    assert s.frequency_hz[0] == 0
    assert s.frequency_hz[-1] == pytest.approx(grad_spectrum.MAX_FREQUENCY_HZ)
    assert list(s.axes) == ["x", "y", "z"]
    for axis in ("x", "y"):
        assert s.axes[axis].max() > 0
    for spectrum in s.axes.values():
        assert spectrum.shape == s.frequency_hz.shape
        assert np.all(s.rss >= spectrum - 1e-12)


def test_sine_peak_is_at_its_frequency():
    s = grad_spectrum.gradient_spectrum(_sine_sequence(600))
    assert s.frequency_hz[np.argmax(s.rss)] == pytest.approx(600)
    assert s.rss.max() == pytest.approx(SINE_PEAK, rel=0.01)


def test_short_sequence_is_padded_to_one_window():
    s = grad_spectrum.gradient_spectrum(_sine_sequence(600, duration_s=0.02))
    assert s.reason is None
    assert abs(s.frequency_hz[np.argmax(s.rss)] - 600) <= 20


def test_gradients_at_the_end_are_not_attenuated():
    # 60 ms of sine after 440 ms of nothing: the last sample is at the sequence end.
    s = grad_spectrum.gradient_spectrum(_sine_sequence(600, duration_s=0.06, delay_s=0.44))
    assert s.rss.max() == pytest.approx(SINE_PEAK, rel=0.02)


def test_no_gradients():
    seq = pp.Sequence(SYSTEM)
    seq.add_block(
        pp.make_block_pulse(
            flip_angle=math.pi / 2, duration=1e-3, delay=SYSTEM.rf_dead_time, system=SYSTEM
        )
    )
    s = grad_spectrum.gradient_spectrum(seq)
    assert s.reason == grad_spectrum.NO_GRADIENTS
    assert s.frequency_hz.shape == (0,)
    assert s.rss.shape == (0,)
    assert s.axes == {}


def test_chunks_give_the_same_spectrum_as_one_chunk(monkeypatch):
    # 30 TRs of 20 ms: 600 ms, 25 windows of 50 ms with a 25 ms hop, so chunks of 4
    # windows make 7 chunks, and the last chunk is shorter than the others.
    seq = gre_sequence(num_trs=30)
    monkeypatch.setattr(grad_spectrum, "CHUNK_WINDOWS", 1_000_000)
    whole = grad_spectrum.gradient_spectrum(seq)
    monkeypatch.setattr(grad_spectrum, "CHUNK_WINDOWS", 4)
    chunked = grad_spectrum.gradient_spectrum(seq)
    _assert_same_spectrum(chunked, whole)


@pytest.mark.parametrize(
    "seq",
    [spin_echo_sequence(), gre_sequence(num_trs=30), arbitrary_gradient_sequence()],
    ids=["spin_echo", "gre_30_trs", "arbitrary_gradient"],
)
def test_matches_scipy_spectrogram(seq, monkeypatch):
    """The whole `gradient_spectrum`, not one call of `_chunk_spectrogram`: the reference
    is scipy's `spectrogram` of the whole padded waveform of each axis, with the arguments
    that the code used before it made the FFTs itself, so the reference does not use the
    chunks, the strided windows, the kept-bin count or the scale of this module. Only the
    samples come from `GradientSampler`, with the time rule of the module (sample i at
    `(i + 0.5) * dt`, half a window of zeros at each end). `CHUNK_WINDOWS` is 4, so the
    comparison also covers the joins of the chunks and a shorter last chunk."""
    monkeypatch.setattr(grad_spectrum, "CHUNK_WINDOWS", 4)
    got = grad_spectrum.gradient_spectrum(seq)

    sampler = GradientSampler(seq, sequence_index(seq))
    dt = seq.grad_raster_time
    nwin = round(grad_spectrum.FFT_WINDOW_S / dt)
    nfft = round(grad_spectrum.FREQUENCY_OVERSAMPLING * nwin)
    pad = nwin // 2
    nt = math.ceil(sum(seq.block_durations.values()) / dt)
    t = (np.arange(nt) + 0.5) * dt
    window_maxima = {}
    rss_sq = 0.0
    for axis in "xyz":
        w = np.zeros(nt + 2 * pad)
        w[pad : pad + nt] = sampler.sample(f"g{axis}", t)
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
        keep = freq <= grad_spectrum.MAX_FREQUENCY_HZ + 1e-6
        sxx = sxx[keep]
        window_maxima[axis] = sxx.max(axis=1)
        rss_sq = rss_sq + sxx**2
    expected_rss = np.sqrt(rss_sq).max(axis=1)

    np.testing.assert_array_equal(got.frequency_hz, freq[keep])
    assert list(got.axes) == ["x", "y", "z"]
    for axis, expected in window_maxima.items():
        np.testing.assert_allclose(got.axes[axis], expected, rtol=0, atol=1e-12 * expected.max())
    np.testing.assert_allclose(got.rss, expected_rss, rtol=0, atol=1e-12 * expected_rss.max())


def _assert_matches_oracle(
    got: grad_spectrum.GradientSpectrum, ref, seq: pp.Sequence, tol: float = 1e-12
) -> None:
    """`got` (this module, the sampler-based implementation, in Hz/m/sqrt(Hz)) times
    `1e3 / seq.system.gamma` equals `ref` (`tests/oracles/grad_spectrum.py`, the
    implementation before phase 5, which samples through `Sequence.get_gradients()` and
    gives mT/m/sqrt(Hz)) within the tolerance of section 3.5, item 2 of
    `docs/plans/cards-at-scale.md`: the sampler builds the waveform from each block's own
    corner points and `numpy.interp`, in a different order of float operations than
    `Sequence.get_gradients()`'s one whole-axis `scipy.interpolate.PPoly`, so the tests
    allow a relative difference of 1e-12, or an absolute difference of 1e-12 times the
    largest value of the same array. `tol` replaces 1e-12 for a long sequence (see
    `test_matches_oracle_on_long_sequences`). This also tests the conversion of the
    module docstring: the values of this module times `1e3 / gamma` are the values of the
    oracle.
    """
    to_mt = 1e3 / seq.system.gamma
    assert got.reason == ref.reason
    if ref.reason is not None:
        return
    np.testing.assert_array_equal(got.frequency_hz, ref.frequency_hz)
    assert list(got.axes) == list(ref.axes)
    for axis in ref.axes:
        r = ref.axes[axis]
        peak = float(r.max()) if r.size else 0.0
        np.testing.assert_allclose(got.axes[axis] * to_mt, r, rtol=tol, atol=tol * peak)
    rss_peak = float(ref.rss.max()) if ref.rss.size else 0.0
    np.testing.assert_allclose(got.rss * to_mt, ref.rss, rtol=tol, atol=tol * rss_peak)


@pytest.mark.parametrize(
    "seq",
    [
        spin_echo_sequence(),
        gre_sequence(),
        arbitrary_gradient_sequence(),
        empty_sequence(),
        _sine_sequence(600),
    ],
    ids=["spin_echo", "gre", "arbitrary_gradient", "empty", "sine"],
)
def test_matches_oracle_on_synthetic_sequences(seq):
    _assert_matches_oracle(grad_spectrum.gradient_spectrum(seq), oracle.gradient_spectrum(seq), seq)


@pytest.mark.parametrize("case", ["repeating", "worst"])
def test_matches_oracle_on_long_sequences(case):
    """The builders of `scale_sequences` (`build_repeating` and `build_worst`) at 10^4
    blocks (task 5.3 of docs/plans/cards-at-scale.md). The tolerance is
    `1e-12 * max(1, duration in s)`, not 1e-12 (the user, 2026-09-28). Both
    implementations place each gradient corner at an absolute time with float rounding, in
    a different order of additions: the sampler adds `(block start + delay) + offset`, and
    pypulseq's `get_gradients()` adds the segment durations one at a time. The rounding of
    an absolute time grows with the time, and a gradient ramp turns it into a value
    difference, so the difference grows with the duration of the sequence. Measured: 2.5e-12
    of the peak at 10^4 repeating blocks (12 s), 3.6e-12 at 10^5 blocks. Neither is more
    correct than the other."""
    n_trs = 10_000 // TR_BLOCKS
    build = build_repeating if case == "repeating" else build_worst
    seq = build(n_trs)
    tol = 1e-12 * max(1.0, seq.duration()[0])
    _assert_matches_oracle(
        grad_spectrum.gradient_spectrum(seq), oracle.gradient_spectrum(seq), seq, tol=tol
    )


def test_spectrum_does_not_depend_on_the_gamma_of_the_system():
    other = copy.copy(SYSTEM)
    other.gamma = 0.9 * SYSTEM.gamma
    waveform_hz_per_m = 1e-3 * SYSTEM.gamma * np.sin(2 * np.pi * 600 * np.arange(5000) * 1e-5)
    spectra = []
    for system in (SYSTEM, other):
        seq = pp.Sequence(system)
        seq.add_block(
            pp.make_arbitrary_grad("x", waveform_hz_per_m, first=0, last=0, system=system)
        )
        spectra.append(grad_spectrum.gradient_spectrum(seq))
    assert spectra[0].reason is None
    assert other.gamma != SYSTEM.gamma
    np.testing.assert_array_equal(spectra[0].frequency_hz, spectra[1].frequency_hz)
    assert list(spectra[0].axes) == list(spectra[1].axes)
    for axis in spectra[0].axes:
        np.testing.assert_array_equal(spectra[0].axes[axis], spectra[1].axes[axis])
    np.testing.assert_array_equal(spectra[0].rss, spectra[1].rss)


def test_gradient_spectrum_refuses_rotations():
    """`gradient_spectrum` raises `NotImplementedError` for a sequence with a rotation
    library (`extensions.refuse_rotations`): the sampler does not apply a rotation."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        grad_spectrum.gradient_spectrum(_with_rotation_library())


def test_gradient_spectrum_for_keeps_the_result():
    seq = gre_sequence(num_trs=2)
    first = grad_spectrum.gradient_spectrum_for(seq)
    assert grad_spectrum.gradient_spectrum_for(seq) is first
    seq.add_block(pp.make_delay(1e-3))
    assert grad_spectrum.gradient_spectrum_for(seq) is not first


@pytest.mark.parametrize(
    ("make_seq", "num_arrays"),
    [(spin_echo_sequence, 5), (empty_sequence, 2)],
    ids=["spin_echo", "no_gradients"],
)
def test_the_arrays_of_a_spectrum_are_read_only(make_seq, num_arrays):
    s = grad_spectrum.gradient_spectrum(make_seq())
    arrays = [s.frequency_hz, s.rss, *s.axes.values()]
    assert len(arrays) == num_arrays
    for a in arrays:
        assert not a.flags.writeable
        with pytest.raises(ValueError):
            a *= 1e3 / GAMMA_1H
    # A conversion to a new array works, and the spectrum stays as it was.
    before = s.rss.copy()
    converted = s.rss * 1e3 / GAMMA_1H
    assert converted.flags.writeable
    np.testing.assert_array_equal(s.rss, before)


def test_spectra_compare_by_value():
    """`==` compares the fields of two spectra by value, not the objects, and a
    `GradientSpectrum` is not hashable."""
    s = grad_spectrum.gradient_spectrum(spin_echo_sequence())
    other = grad_spectrum.gradient_spectrum(spin_echo_sequence())
    assert other is not s
    assert other == s
    assert pickle.loads(pickle.dumps(s)) == s
    assert grad_spectrum.gradient_spectrum(empty_sequence()) == grad_spectrum.gradient_spectrum(
        empty_sequence()
    )
    assert grad_spectrum.gradient_spectrum(spin_echo_sequence(), window_s=0.1) != s
    assert grad_spectrum.gradient_spectrum(empty_sequence()) != s
    assert s != "spectrum"
    with pytest.raises(TypeError):
        hash(s)


def test_the_defaults_are_those_of_pypulseq():
    parameters = inspect.signature(pp.Sequence.calculate_gradient_spectrum).parameters
    seq = spin_echo_sequence()
    explicit = grad_spectrum.gradient_spectrum(
        seq,
        max_frequency_hz=parameters["max_frequency"].default,
        window_s=parameters["window_width"].default,
        frequency_oversampling=parameters["frequency_oversampling"].default,
    )
    default = grad_spectrum.gradient_spectrum(seq)
    np.testing.assert_array_equal(explicit.frequency_hz, default.frequency_hz)
    assert list(explicit.axes) == list(default.axes)
    for axis in default.axes:
        np.testing.assert_array_equal(explicit.axes[axis], default.axes[axis])
    np.testing.assert_array_equal(explicit.rss, default.rss)
    assert (default.max_frequency_hz, default.window_s, default.frequency_oversampling) == (
        parameters["max_frequency"].default,
        parameters["window_width"].default,
        parameters["frequency_oversampling"].default,
    )


def test_the_arguments_change_the_frequencies():
    seq = _sine_sequence(600)
    wide = grad_spectrum.gradient_spectrum(seq, window_s=0.1)
    assert (wide.max_frequency_hz, wide.window_s, wide.frequency_oversampling) == (
        2000.0,
        0.1,
        3.0,
    )
    assert wide.frequency_hz[1] == pytest.approx(1 / (3 * 0.1))
    # The sine has a whole number of cycles in the 0.1 s window, so its peak stays on a bin.
    assert wide.frequency_hz[np.argmax(wide.rss)] == pytest.approx(600)
    coarse = grad_spectrum.gradient_spectrum(seq, frequency_oversampling=1)
    assert type(coarse.frequency_oversampling) is float
    assert coarse.frequency_hz[1] == pytest.approx(1 / 0.05)
    low = grad_spectrum.gradient_spectrum(seq, max_frequency_hz=500)
    assert low.frequency_hz[-1] <= 500


_NAN, _INF = float("nan"), float("inf")


@pytest.mark.parametrize(
    "function", [grad_spectrum.gradient_spectrum, grad_spectrum.gradient_spectrum_for]
)
@pytest.mark.parametrize(
    ("arguments", "error", "match"),
    [
        pytest.param({"max_frequency_hz": _NAN}, ValueError, None, id="max_frequency_nan"),
        pytest.param({"window_s": _NAN}, ValueError, None, id="window_nan"),
        pytest.param({"frequency_oversampling": _NAN}, ValueError, None, id="oversampling_nan"),
        pytest.param({"max_frequency_hz": _INF}, ValueError, None, id="max_frequency_infinity"),
        pytest.param({"window_s": _INF}, ValueError, None, id="window_infinity"),
        pytest.param(
            {"frequency_oversampling": _INF}, ValueError, None, id="oversampling_infinity"
        ),
        pytest.param({"max_frequency_hz": "2000"}, TypeError, None, id="max_frequency_string"),
        pytest.param({"window_s": "0.05"}, TypeError, None, id="window_string"),
        pytest.param({"frequency_oversampling": "3"}, TypeError, None, id="oversampling_string"),
        pytest.param({"max_frequency_hz": True}, TypeError, None, id="max_frequency_bool"),
        pytest.param({"window_s": True}, TypeError, None, id="window_bool"),
        pytest.param({"frequency_oversampling": True}, TypeError, None, id="oversampling_bool"),
        pytest.param({"window_s": 0.0}, ValueError, None, id="window_zero"),
        pytest.param({"window_s": -0.05}, ValueError, None, id="window_negative"),
        pytest.param(
            {"window_s": 1e-5},
            ValueError,
            "samples at the gradient raster",
            id="window_of_one_sample",
        ),
        pytest.param({"frequency_oversampling": 0.5}, ValueError, None, id="oversampling_below_1"),
        pytest.param({"max_frequency_hz": 0.0}, ValueError, None, id="max_frequency_zero"),
        pytest.param({"max_frequency_hz": -1.0}, ValueError, None, id="max_frequency_negative"),
        pytest.param(
            {"max_frequency_hz": 60000.0}, ValueError, None, id="max_frequency_above_nyquist"
        ),
        pytest.param(
            {"max_frequency_hz": 1.0}, ValueError, None, id="max_frequency_below_the_step"
        ),
        # The step is 20 Hz with no oversampling, so 10 Hz is above the step of the defaults.
        pytest.param(
            {"max_frequency_hz": 10.0, "frequency_oversampling": 1},
            ValueError,
            None,
            id="max_frequency_below_the_step_of_the_arguments",
        ),
    ],
)
def test_gradient_spectrum_refuses_bad_arguments(function, arguments, error, match, monkeypatch):
    def fail(seq):
        raise AssertionError("the sequence was read")

    monkeypatch.setattr(grad_spectrum, "sequence_index", fail)
    with pytest.raises(error, match=match):
        function(spin_echo_sequence(), **arguments)


def test_gradient_spectrum_for_keeps_one_result_for_each_set_of_arguments():
    seq = gre_sequence(num_trs=2)
    default = grad_spectrum.gradient_spectrum_for(seq)
    low = grad_spectrum.gradient_spectrum_for(seq, max_frequency_hz=1000.0)
    assert low is not default
    assert low.frequency_hz[-1] <= 1000.0
    assert grad_spectrum.gradient_spectrum_for(seq) is default
    # The key is the arguments as floats, so 1000 and 1000.0 are one set.
    assert grad_spectrum.gradient_spectrum_for(seq, max_frequency_hz=1000) is low
