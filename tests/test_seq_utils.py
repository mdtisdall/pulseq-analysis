import numpy as np
import numpy.testing as npt
import pypulseq as pp
import pytest
from synthetic import (
    GAMMA_1H,
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis import seq_utils


def test_time_tolerance():
    assert seq_utils.TIME_TOLERANCE == 1e-9
    assert seq_utils.TIME_TOLERANCE == pp.eps


def test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system():
    """The tests convert the values of the package with GAMMA_1H. The test sequences
    convert their mT/m limits with the gamma of SYSTEM (the default of pypulseq's
    Opts). The two must be equal."""
    assert GAMMA_1H == SYSTEM.gamma == 42.576e6


def test_gradient_offsets_trapezoid():
    g = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    delay, offsets, amp = seq_utils.gradient_offsets(g)
    expected_offsets = np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
    expected_amp = np.array([0.0, g.amplitude, g.amplitude, 0.0])
    assert delay == g.delay
    assert offsets == pytest.approx(expected_offsets)
    assert amp == pytest.approx(expected_amp)


def test_gradient_offsets_arbitrary():
    n = 10
    waveform = np.linspace(100.0, 500.0, n)
    g = pp.make_arbitrary_grad(channel="x", waveform=waveform, system=SYSTEM)

    delay, offsets, amp = seq_utils.gradient_offsets(g)
    assert delay == g.delay
    assert offsets[0] == pytest.approx(0.0)
    assert offsets[-1] == pytest.approx(g.shape_dur)
    assert amp[0] == pytest.approx(g.first)
    assert amp[-1] == pytest.approx(g.last)

    # The interior points are the waveform's own sample offsets and values, unchanged.
    assert offsets[1:-1] == pytest.approx(np.asarray(g.tt, dtype=float))
    assert amp[1:-1] == pytest.approx(waveform)


def test_gradient_points_trapezoid():
    g = pp.make_trapezoid(channel="x", area=1000, system=SYSTEM)
    t0 = 1e-3
    t, amp = seq_utils.gradient_points(g, t0)
    expected_t = t0 + g.delay + np.cumsum([0.0, g.rise_time, g.flat_time, g.fall_time])
    expected_amp = np.array([0.0, g.amplitude, g.amplitude, 0.0])
    assert t == pytest.approx(expected_t)
    assert amp == pytest.approx(expected_amp)


def test_gradient_points_arbitrary():
    n = 10
    waveform = np.linspace(100.0, 500.0, n)
    g = pp.make_arbitrary_grad(channel="x", waveform=waveform, system=SYSTEM)
    t0 = 2e-3
    t, amp = seq_utils.gradient_points(g, t0)

    # The first and last points are g.first and g.last at the ends of the shape.
    assert amp[0] == pytest.approx(g.first)
    assert amp[-1] == pytest.approx(g.last)
    assert t[0] == pytest.approx(t0 + g.delay)
    assert t[-1] == pytest.approx(t0 + g.delay + g.shape_dur)

    # The interior points are the waveform samples, unchanged (already Hz/m).
    assert amp[1:-1] == pytest.approx(waveform)
    assert t[1:-1] == pytest.approx(t0 + g.delay + np.asarray(g.tt, dtype=float))


@pytest.mark.parametrize(
    "g",
    [
        pp.make_trapezoid(channel="x", area=1000, system=SYSTEM),
        pp.make_arbitrary_grad(channel="x", waveform=np.linspace(100.0, 500.0, 10), system=SYSTEM),
    ],
    ids=["trapezoid", "arbitrary"],
)
def test_gradient_points_matches_gradient_offsets_exactly(g):
    # This is the relationship the diagram tables rest on: gradient_points must be
    # exactly (not just approximately) t0 + delay + offsets, for every bit, because a
    # later phase rebuilds the same times from the stored offsets.
    t0 = 1.234e-3
    t, _ = seq_utils.gradient_points(g, t0)
    delay, offsets, _ = seq_utils.gradient_offsets(g)
    npt.assert_array_equal(t, (t0 + delay) + offsets)


@pytest.mark.parametrize(
    "builder",
    [spin_echo_sequence, gre_sequence, empty_sequence, arbitrary_gradient_sequence],
)
def test_synthetic_sequences_pass_the_timing_check(builder):
    seq = builder()
    ok, report = seq.check_timing()
    assert ok, report
