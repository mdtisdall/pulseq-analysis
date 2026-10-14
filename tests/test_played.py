"""Tests of the gradients that the measurements play (`synth/_played.py`, task R14): the points of
each block's events, taken from the decoding of the snapshot.

The measurements join the points with straight lines. The decoding's `gradients_at` is the
waveform of each interpreter. So on every fixture that an interpreter reads, in each of its
settings, the straight lines of the points are `gradients_at`, in each block: at the middle of
each segment, and at each point that is not a step (`check_the_points_are_the_gradients`).

Here for `spec`, and for a fake plugin (`test_snapshot.Unrotated`, rotations left unapplied);
the tests through `cpp-siemens` and its settings are in the plugin's tests
(`packages/pulseq-cpp-siemens/tests/test_load_in_pulseq_analysis.py`). The fake plugin `Doubled`
decodes one event otherwise in one block (`gradient_variants`), and that block gets its own key.
The fake plugin `Late` plays the events of one block wholly after the end of the block.
"""

import dataclasses
import pathlib
import warnings
from typing import Any, ClassVar

import numpy as np
import pytest
from test_snapshot import Unrotated, UnrotatedDecoding

from pulseq_analysis.analyses import load
from pulseq_analysis.seqfile import NotSupported, SeqFileError, SequenceData, Spec
from pulseq_analysis.synth import ScannerSettingWarning, Session, decode
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


# Nine blocks, each of which plays the trapezoid 1 on gx.
TRAPEZOIDS = SEQFILES / "oracle" / "koma_v1.4_gr-trapezoidal.seq"
# 90 degrees about z: x goes to y.
QUARTER_Z = (np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5))


@dataclasses.dataclass(frozen=True, slots=True)
class Doubled(Unrotated):
    """A plugin interpreter of the tests whose decoding plays the gradients of block 1 at twice
    the amplitude of the file: in block 1 each gradient event decodes otherwise than in the other
    blocks, as the C++ reader can decode an event (the buffer of the gradients of a block).
    `spec`'s model and decoding otherwise, with the session."""

    name: ClassVar[str] = "doubled"

    def decode(self, data: SequenceData, session=None) -> "DoubledDecoding":
        return DoubledDecoding(self, decode(dataclasses.replace(data, interpreter=Spec()), session))


@dataclasses.dataclass(frozen=True, eq=False)
class DoubledDecoding(UnrotatedDecoding):
    """The decoding of `Doubled`: `spec`'s gradients, rotated as `spec` rotates them, twice as
    large in block 1, and a `gradient_variants` with the variant 1 at each cell of block 1 with
    an event."""

    @property
    def rotation_record(self):
        return self.spec.rotation_record

    def gradients_at(self, block_index: Any, time_us: Any, rotated: bool | None = None):
        values = self.spec.gradients_at(block_index, time_us, rotated)
        in_block_1 = np.asarray(block_index).reshape(-1) == 1
        return np.where(in_block_1[:, None], 2 * values, values)

    def gradient_points(self, key: int, block: int, axis: int):
        delay, offsets, amp = self.spec.gradient_points(key, block, axis)
        return (delay, offsets, 2 * amp) if block == 1 else (delay, offsets, amp)

    def gradient_variants(self) -> np.ndarray:
        variants = np.zeros((self.block_count, 3), dtype=np.int64)
        variants[1] = [self.spec.blocks[column][1] != 0 for column in ("gx", "gy", "gz")]
        variants.flags.writeable = False
        return variants


def test_each_variant_of_a_gradient_event_has_its_own_key_and_its_own_points():
    """When the decoding gives an event a variant in one block (`gradient_variants`), the played
    gradients give that block a new key, above the largest file ID, with the points of the event
    in that block; the other blocks keep the file ID, with the points of the first block that
    plays it. The points are the gradients of the decoding (`check_the_points_are_the_gradients`)."""
    snap = load(TRAPEZOIDS, Doubled())
    played = played_gradients(snap)
    assert played.gx[1] > 1
    assert played.gx[0] == 1 and np.all(played.gx[2:] == 1)
    for key, block in ((int(played.gx[1]), 1), (1, 0)):
        delay, offsets, amp = played.points[key]
        expected = snap.decoding.gradient_points(1, block, 0)
        assert delay == expected[0]
        assert np.array_equal(offsets, expected[1])
        assert np.array_equal(amp, expected[2])
    check_the_points_are_the_gradients(TRAPEZOIDS, Doubled())


def test_a_block_that_the_session_rotates_takes_the_points_of_its_variant():
    """When the session's field of view rotates every block, the played gradients of each block
    come from `gradients_at` (`_from_gradients_at`): block 1, with the variant of its event, has
    its own keys and twice the values of block 0 on y, where the rotation takes gx. The points
    are the gradients of the decoding, at the middle of each segment and at each point that is
    not a step (`_probes`)."""
    snap = load(TRAPEZOIDS, Doubled(), session=Session(fov_rotation=QUARTER_Z))
    played = played_gradients(snap)
    assert played.gy[1] != played.gy[0]
    _, _, block_0 = played.points[int(played.gy[0])]
    _, _, block_1 = played.points[int(played.gy[1])]
    scale = float(np.abs(block_1).max())
    np.testing.assert_allclose(block_1, 2 * block_0, rtol=0, atol=RTOL * scale)
    blocks, axes, times, values = _probes(snap)
    got = snap.decoding.gradients_at(blocks, times * 1e6)[np.arange(blocks.size), axes]
    assert np.abs(got - values).max() <= RTOL * scale


@dataclasses.dataclass(frozen=True, slots=True)
class Late(Unrotated):
    """A plugin interpreter of the tests whose decoding plays each gradient event of block 1
    wholly after the end of the block, as a plugin can play an event that `spec` rejects
    (`block.event-too-long`). `spec`'s model and decoding otherwise, with the session."""

    name: ClassVar[str] = "late"

    def decode(self, data: SequenceData, session=None) -> "LateDecoding":
        return LateDecoding(self, decode(dataclasses.replace(data, interpreter=Spec()), session))


@dataclasses.dataclass(frozen=True, eq=False)
class LateDecoding(DoubledDecoding):
    """The decoding of `Late`: `spec`'s gradients, rotated as `spec` rotates them, with the delay
    of each event of block 1 longer by twice the duration of the block, so that the event starts
    one block duration after the end of the block. `gradients_at` is 0 after the end of a block,
    so it is 0 in the whole of block 1. The variants and the rotation record are those of
    `DoubledDecoding`."""

    def gradients_at(self, block_index: Any, time_us: Any, rotated: bool | None = None):
        values = self.spec.gradients_at(block_index, time_us, rotated)
        in_block_1 = np.asarray(block_index).reshape(-1) == 1
        return np.where(in_block_1[:, None], 0.0, values)

    def gradient_points(self, key: int, block: int, axis: int):
        delay, offsets, amp = self.spec.gradient_points(key, block, axis)
        if block == 1:
            delay += 2 * float(self.block_durations[1])
        return delay, offsets, amp


@pytest.mark.parametrize(
    "session",
    [pytest.param(None, id="unrotated"), pytest.param(Session(fov_rotation=QUARTER_Z), id="fov")],
)
def test_an_event_wholly_after_the_end_of_its_block_has_two_points_or_more(session):
    """When the decoding plays the event of a block wholly after the end of the block (`Late`),
    each played event of that block has 2 points or more, also when the session's field of view
    rotates the block (an event on each axis, `_from_gradients_at`). The points are the
    gradients of the decoding, at the middle of each segment and at each point that is not a
    step (`_probes`)."""
    snap = load(TRAPEZOIDS, Late(), session=session)
    played = played_gradients(snap)
    columns = (played.gx, played.gy, played.gz)
    assert any(column[1] != 0 for column in columns)
    for column in columns:
        if column[1] != 0:
            _, offsets, _ = played.points[int(column[1])]
            assert offsets.size >= 2
    blocks, axes, times, values = _probes(snap)
    got = snap.decoding.gradients_at(blocks, times * 1e6)[np.arange(blocks.size), axes]
    scale = max(float(np.abs(values).max()), 1.0)
    assert np.abs(got - values).max() <= RTOL * scale
