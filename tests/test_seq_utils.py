import math

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


def test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system():
    """The tests convert the values of the package with GAMMA_1H. The test sequences
    convert their mT/m limits with the gamma of SYSTEM (the default of pypulseq's
    Opts). The two must be equal."""
    assert GAMMA_1H == SYSTEM.gamma == 42.576e6


def test_hold_samples_keeps_uniform_shapes_unchanged():
    rf = pp.make_sinc_pulse(
        flip_angle=math.pi / 2,
        duration=3e-3,
        slice_thickness=4e-3,
        delay=SYSTEM.rf_dead_time,
        system=SYSTEM,
        return_gz=False,
        use="excitation",
    )
    t = np.asarray(rf.t, dtype=float)
    dt_in = t[1] - t[0]
    assert np.diff(t) == pytest.approx(dt_in, abs=1e-12)
    assert len(t) * dt_in == pytest.approx(rf.shape_dur)

    signal, dt = seq_utils.hold_samples(rf, SYSTEM.rf_raster_time)
    assert dt == pytest.approx(dt_in)
    assert signal == pytest.approx(np.asarray(rf.signal, dtype=complex))


def test_hold_samples_interpolates_a_block_pulse():
    flip = math.pi / 3
    rf = pp.make_block_pulse(
        flip_angle=flip, duration=2e-3, delay=SYSTEM.rf_dead_time, system=SYSTEM
    )
    # The block pulse has samples only at its start and end, not filling shape_dur.
    assert len(rf.t) == 2
    assert len(rf.t) * (rf.t[1] - rf.t[0]) != pytest.approx(rf.shape_dur)

    raster = SYSTEM.rf_raster_time
    signal, dt = seq_utils.hold_samples(rf, raster)
    expected_n = max(1, round(rf.shape_dur / raster))
    assert len(signal) == expected_n
    assert dt * len(signal) == pytest.approx(rf.shape_dur)
    assert abs(signal.sum() * dt) == pytest.approx(flip / (2 * math.pi))


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
