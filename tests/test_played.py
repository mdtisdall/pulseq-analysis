"""Tests of the gradients that the measurements play (`synth/_played.py`, task R14): the points of
each block's events, taken from the decoding of the snapshot.

The measurements join the points with straight lines. The decoding's `gradients_at` is the
waveform of each interpreter. So on every fixture that an interpreter reads, in each of its
settings, the straight lines of the points are `gradients_at`, in each block: at the middle of
each segment, and at each point that is not a step (`check_the_points_are_the_gradients`).

Here for `spec`, and for a fake plugin (`test_snapshot.Unrotated`, rotations left unapplied);
the tests through `cpp-siemens` and its settings are in the plugin's tests
(`packages/pulseq-cpp-siemens/tests/test_load_in_pulseq_analysis.py`).
"""

import pytest

pytestmark = pytest.mark.pypulseq
pytest.importorskip("pypulseq")

import pathlib
import warnings

import numpy as np
from test_snapshot import Unrotated

from pulseq_analysis.analyses import load
from pulseq_analysis.seqfile import NotSupported, SeqFileError
from pulseq_analysis.synth import ScannerSettingWarning
from pulseq_analysis.synth._played import played_gradients

SEQFILES = pathlib.Path(__file__).parent / "seqfiles"
FIXTURES = sorted(SEQFILES.rglob("*.seq"))
SETTINGS = [
    pytest.param("spec", id="spec"),
    pytest.param(Unrotated(), id="plugin"),
]
# The relative tolerance of the comparison, of the largest value of the file. A plugin can give
# the value of a sample at a point as float32 (`cpp-siemens` gives the float32 product of the
# amplitude and the sample, D7.2) and draw its lines between the samples before the product, in
# double: the two differ by the rounding of a float32.
RTOL = 1e-7


def load_or_none(path, interpreter):
    """The snapshot of `path` through `interpreter`, or None when the interpreter rejects it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        try:
            return load(path, interpreter)
        except (SeqFileError, NotSupported):
            return None


def _probes(snap):
    """The block, the axis, the time (s from the block start) and the value of the straight
    lines of the points: the middle of each segment of each event, and each point that is not a
    step (its neighbour at the same time, if any, has the same value)."""
    played = played_gradients(snap)
    columns = (played.gx, played.gy, played.gz)
    blocks, axes, times, values = [], [], [], []
    for block in range(snap.data.blocks.size):
        for axis, column in enumerate(columns):
            key = int(column[block])
            if not key:
                continue
            delay, offsets, amp = played.points[key]
            t = delay + offsets
            for i in range(t.size - 1):
                if t[i + 1] > t[i]:
                    blocks.append(block)
                    axes.append(axis)
                    times.append((t[i] + t[i + 1]) / 2)
                    values.append((amp[i] + amp[i + 1]) / 2)
            for i in range(1, t.size - 1):
                if t[i - 1] < t[i] < t[i + 1]:
                    blocks.append(block)
                    axes.append(axis)
                    times.append(t[i])
                    values.append(amp[i])
    return np.array(blocks, dtype=np.int64), np.array(axes), np.array(times), np.array(values)


def check_the_points_are_the_gradients(path, interpreter) -> None:
    """On the fixture `path`, if the interpreter reads it, the straight lines between the points
    of each block's events equal `gradients_at` of the decoding at the middle of each segment
    and at each point that is not a step, to `RTOL` of the largest value (a NaN of the file is
    NaN in both)."""
    snap = load_or_none(path, interpreter)
    if snap is None:
        pytest.skip("the interpreter rejects the file")
    blocks, axes, times, values = _probes(snap)
    if blocks.size == 0:
        return
    got = snap.decoding.gradients_at(blocks, times * 1e6)[np.arange(blocks.size), axes]
    # A value that the file writes as `nan` (a plugin can read it) is NaN in both.
    assert np.array_equal(np.isnan(got), np.isnan(values))
    finite = ~np.isnan(values)
    scale = max(float(np.abs(values[finite]).max(initial=0.0)), 1.0)
    assert np.abs(got[finite] - values[finite]).max(initial=0.0) <= RTOL * scale


@pytest.mark.parametrize("interpreter", SETTINGS)
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_points_of_the_played_events_are_the_gradients_of_the_decoding(path, interpreter):
    """On each fixture that the interpreter reads, the points of the played events are the
    gradients of the decoding (`check_the_points_are_the_gradients`). This holds for the decoded
    events, for a block that the decoding rotates (`spec` from 1.5.1), and for the unrotated
    blocks of a plugin."""
    check_the_points_are_the_gradients(path, interpreter)
