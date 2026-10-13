from pathlib import Path

import numpy as np
import numpy.testing as npt
import pytest
from synthetic import (
    GAMMA_1H,
    SYSTEM,
)

from pulseq_analysis import seqfile
from pulseq_analysis.synth import seq_utils
from pulseq_analysis.synth.events import decode_gradients

SEQFILES = Path(__file__).resolve().parent / "seqfiles"


def test_time_tolerance():
    assert seq_utils.TIME_TOLERANCE == 1e-9


@pytest.mark.pypulseq
def test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system():
    """The tests convert the values of the package with GAMMA_1H. The test sequences
    convert their mT/m limits with the gamma of SYSTEM (the default of pypulseq's
    Opts). The two must be equal."""
    assert GAMMA_1H == SYSTEM.gamma == 42.576e6


def _decoded_event(gradient_id: int):
    return decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))[gradient_id]


def test_gradient_offsets_of_a_decoded_trapezoid():
    g = _decoded_event(1)
    delay, offsets, amp = seq_utils.gradient_offsets(g)
    assert delay == 1e-4
    npt.assert_array_equal(offsets, np.cumsum([0.0, 1e-4, 2e-4, 1e-4]))
    npt.assert_array_equal(amp, [0.0, 1e6, 1e6, 0.0])


@pytest.mark.parametrize("gradient_id", [3, 5, 6], ids=["time_id_0", "time_shape", "time_id_-1"])
def test_gradient_offsets_of_a_decoded_arbitrary_gradient(gradient_id):
    """The samples of the event, with `first` at offset 0 and `last` at `shape_dur`."""
    g = _decoded_event(gradient_id)
    delay, offsets, amp = seq_utils.gradient_offsets(g)
    assert delay == g.delay
    npt.assert_array_equal(offsets, np.concatenate([[0.0], g.tt, [g.shape_dur]]))
    npt.assert_array_equal(amp, np.concatenate([[g.first], g.waveform, [g.last]]))


@pytest.mark.parametrize("gradient_id", [1, 3], ids=["trapezoid", "arbitrary"])
def test_gradient_points_matches_gradient_offsets_exactly(gradient_id):
    # This is the relationship the diagram tables rest on: gradient_points must be
    # exactly (not just approximately) t0 + delay + offsets, for every bit, because a
    # later phase rebuilds the same times from the stored offsets.
    g = _decoded_event(gradient_id)
    t0 = 1.234e-3
    t, _ = seq_utils.gradient_points(g, t0)
    delay, offsets, _ = seq_utils.gradient_offsets(g)
    npt.assert_array_equal(t, (t0 + delay) + offsets)
