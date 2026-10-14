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
The fake plugin `Late` plays the events of one block wholly after the end of the block, or with
all their points at one time.
"""

import dataclasses
import pathlib
import warnings
from typing import Any, ClassVar

import numpy as np
import pytest
from test_snapshot import Unrotated, UnrotatedDecoding

from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import block_gradient_values, gradient_peaks
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
    (`block.event-too-long`). `spec`'s model and decoding otherwise, with the session.

    `shift` is the delay that the decoding adds to each event of block 1, in durations of the
    block: with 2 the event starts one block duration after the end of the block, with 1 at its
    end, and with less than 1 inside the block. `duration_s`, when not None, is the actual
    duration of block 1 in the decoding. With `length_0`, each event of block 1 has all its
    points at its delay (an event of length 0)."""

    name: ClassVar[str] = "late"
    shift: float = 2.0
    duration_s: float | None = None
    length_0: bool = False

    def decode(self, data: SequenceData, session=None) -> "LateDecoding":
        return LateDecoding(self, decode(dataclasses.replace(data, interpreter=Spec()), session))


@dataclasses.dataclass(frozen=True, eq=False)
class LateDecoding(DoubledDecoding):
    """The decoding of `Late`: `spec`'s gradients, rotated as `spec` rotates them, with the delay
    of each event of block 1 longer by `shift` times the duration of the block (its
    `duration_s`, when that is not None), so that the event starts at or after the end of the
    block, and with `length_0` with the offsets 0. `gradients_at` is 0 in the whole of block 1:
    it is 0 after the end of a block, and an event of length 0 plays for no time. The variants
    and the rotation record are those of `DoubledDecoding`."""

    @property
    def block_durations(self):
        durations = self.spec.block_durations
        if self.interpreter.duration_s is None:
            return durations
        durations = durations.copy()
        durations[1] = self.interpreter.duration_s
        durations.flags.writeable = False
        return durations

    def gradients_at(self, block_index: Any, time_us: Any, rotated: bool | None = None):
        values = self.spec.gradients_at(block_index, time_us, rotated)
        in_block_1 = np.asarray(block_index).reshape(-1) == 1
        return np.where(in_block_1[:, None], 0.0, values)

    def gradient_points(self, key: int, block: int, axis: int):
        delay, offsets, amp = self.spec.gradient_points(key, block, axis)
        if block == 1:
            delay += self.interpreter.shift * float(self.block_durations[1])
            if self.interpreter.length_0:
                offsets = np.zeros_like(offsets)
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


@pytest.mark.parametrize(
    "session",
    [pytest.param(None, id="unrotated"), pytest.param(Session(fov_rotation=QUARTER_Z), id="fov")],
)
@pytest.mark.parametrize(
    "interpreter",
    [pytest.param(Late(shift=1.0), id="at-the-end"), pytest.param(Late(duration_s=0.0), id="zero")],
)
def test_an_event_that_starts_at_the_end_of_its_block_has_two_points_or_more(interpreter, session):
    """When the events of a block start at the end of the block (`Late(shift=1.0)`), or the
    block lasts 0 s and its events start at its start (`Late(duration_s=0.0)`), each played event
    of that block has 2 points or more, from the start of the block to its end, and the
    measurements take them (`block_gradient_values`: a peak of 0 in block 1). The points are the
    gradients of the decoding, at the middle of each segment and at each point that is not a
    step (`_probes`)."""
    snap = load(TRAPEZOIDS, interpreter, session=session)
    played = played_gradients(snap)
    columns = (played.gx, played.gy, played.gz)
    assert any(column[1] != 0 for column in columns)
    duration = float(snap.decoding.block_durations[1])
    for column in columns:
        if column[1] != 0:
            delay, offsets, _ = played.points[int(column[1])]
            assert offsets.size >= 2
            assert delay == 0.0 and offsets[-1] == duration
    for axis in ("x", "y", "z"):
        assert block_gradient_values(snap).peak_hz_per_m[axis][1] == 0.0
    blocks, axes, times, values = _probes(snap)
    got = snap.decoding.gradients_at(blocks, times * 1e6)[np.arange(blocks.size), axes]
    scale = max(float(np.abs(values).max()), 1.0)
    assert np.abs(got - values).max() <= RTOL * scale


# The rows of `valid_1_5_1.seq` that `_length_0_file` changes: the trapezoid 1 and block 2.
VALID_1_5_1 = SEQFILES / "valid_1_5_1.seq"
TRAP_1_ROW = "1 1000000 100 200 100 100\n"
BLOCK_2_ROW = "2  50  0  1  2  0  1  0\n"


def _length_0_file(directory: pathlib.Path, extension: int) -> pathlib.Path:
    """`valid_1_5_1.seq`, written in `directory`, with the trapezoid 1 of length 0 (rise, flat
    and fall times 0, delay 100 us) alone in block 2 (play index 1), whose extension list is
    `extension`: 0 for none, 3 for the rotation object 1 of the file (45 degrees about z)."""
    text = VALID_1_5_1.read_text()
    assert text.count(TRAP_1_ROW) == 1 and text.count(BLOCK_2_ROW) == 1
    text = text.replace(TRAP_1_ROW, "1 1000000 0 0 0 100\n")
    text = text.replace(BLOCK_2_ROW, f"2  50  0  1  0  0  0  {extension}\n")
    path = directory / "valid_1_5_1_length_0.seq"
    path.write_text(text)
    return path


def _check_block_1_has_two_points_or_more(snap) -> None:
    """Block 1 of `snap` has a played event, each played event of block 1 has 2 points or more,
    and the points are the gradients of the decoding, at the middle of each segment and at each
    point that is not a step (`_probes`), to `RTOL` of the largest value (at least 1)."""
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


@pytest.mark.parametrize(
    ("extension", "session"),
    [
        pytest.param(0, Session(fov_rotation=QUARTER_Z), id="fov"),
        pytest.param(3, None, id="rotation"),
    ],
)
def test_a_block_whose_event_has_length_0_has_two_points_or_more_through_spec(
    tmp_path, extension, session
):
    """When the one event of a block has all its points at one time inside the block (a
    trapezoid of length 0), and the block is read through `gradients_at` (the session's field of
    view rotates it, or its rotation object does, `spec` from 1.5.1), each played event of the
    block has 2 points or more, the points are the gradients of the decoding
    (`_check_block_1_has_two_points_or_more`), and `gradient_peaks` runs."""
    snap = load(_length_0_file(tmp_path, extension), "spec", session=session)
    _check_block_1_has_two_points_or_more(snap)
    gradient_peaks(snap)


@pytest.mark.parametrize(
    "session",
    [pytest.param(None, id="unrotated"), pytest.param(Session(fov_rotation=QUARTER_Z), id="fov")],
)
def test_an_event_of_length_0_alone_in_its_block_has_two_points_or_more(session):
    """When the decoding plays the one event of a block with all its points at one time, in the
    middle of the block (`Late(shift=0.5, length_0=True)`), each played event of that block has 2
    points or more, also when the session's field of view rotates the block, and the points are
    the gradients of the decoding (`_check_block_1_has_two_points_or_more`)."""
    snap = load(TRAPEZOIDS, Late(shift=0.5, length_0=True), session=session)
    _check_block_1_has_two_points_or_more(snap)
    gradient_peaks(snap)
