from pathlib import Path

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

from pulseq_analysis import seqfile
from pulseq_analysis.synth import seq_utils
from pulseq_analysis.synth.events import decode_gradients

SEQFILES = Path(__file__).resolve().parent / "seqfiles"


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


def test_gradient_offsets_of_a_decoded_trapezoid():
    g = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))[1]
    delay, offsets, amp = seq_utils.gradient_offsets(g)
    assert delay == 1e-4
    npt.assert_array_equal(offsets, np.cumsum([0.0, 1e-4, 2e-4, 1e-4]))
    npt.assert_array_equal(amp, [0.0, 1e6, 1e6, 0.0])


@pytest.mark.parametrize("gradient_id", [3, 5, 6], ids=["time_id_0", "time_shape", "time_id_-1"])
def test_gradient_offsets_of_a_decoded_arbitrary_gradient(gradient_id):
    """The samples of the event, with `first` at offset 0 and `last` at `shape_dur`."""
    g = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))[gradient_id]
    delay, offsets, amp = seq_utils.gradient_offsets(g)
    assert delay == g.delay
    npt.assert_array_equal(offsets, np.concatenate([[0.0], g.tt, [g.shape_dur]]))
    npt.assert_array_equal(amp, np.concatenate([[g.first], g.waveform, [g.last]]))


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
