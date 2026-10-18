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
all their points at one time. The fake plugin `OneNaN` gives the event of one block a NaN point,
for the rule of a NaN in the peaks (`check_a_nan_of_one_block_is_credited_to_its_first_nan`).
"""

import dataclasses
import math
import pathlib
import warnings
from typing import Any, ClassVar

import numpy as np
import pytest
from test_snapshot import Unrotated, UnrotatedDecoding

from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.seqfile import NotSupported, SeqFileError, SequenceData, Spec
from pulseq_analysis.synth import ScannerSettingWarning, Session, _played, decode
from pulseq_analysis.synth._played import played_gradients
from pulseq_analysis.synth.seq_index import sequence_index
from pulseq_analysis.synth.seq_utils import TIME_TOLERANCE

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


# The rows of `valid_1_5_1.seq` that `_length_0_file` changes: the trapezoid 1 and block 2, and
# the last arbitrary gradient and the end of the shapes, after which it adds a gradient and two
# shapes.
VALID_1_5_1 = SEQFILES / "valid_1_5_1.seq"
TRAP_1_ROW = "1 1000000 100 200 100 100\n"
BLOCK_2_ROW = "2  50  0  1  2  0  1  0\n"
GRADIENT_6_ROW = "6 300000 0 0 7 -1 0\n"
SIGNATURE_HEADER = "\n[SIGNATURE]\n"


def _length_0_file(
    directory: pathlib.Path,
    extension: int,
    amplitude: int = 1000000,
    kind: str = "trapezoid",
) -> pathlib.Path:
    """`valid_1_5_1.seq`, written in `directory`, with one gradient event of length 0 (delay 100
    us, amplitude `amplitude` Hz/m) alone on gx in block 2 (play index 1), whose extension list
    is `extension`: 0 for none, 3 for the rotation object 1 of the file (45 degrees about z).

    `kind` "trapezoid": the trapezoid 1 with rise, flat and fall times 0. `kind` "extended": the
    new arbitrary gradient 7, an extended trapezoid with first and last 0, the wave shape 10 (one
    sample, 1) and the time shape 11 (one sample, 0): its one vertex is at its delay."""
    text = VALID_1_5_1.read_text()
    assert text.count(TRAP_1_ROW) == 1 and text.count(BLOCK_2_ROW) == 1
    assert text.count(GRADIENT_6_ROW) == 1 and text.count(SIGNATURE_HEADER) == 1
    if kind == "trapezoid":
        text = text.replace(TRAP_1_ROW, f"1 {amplitude} 0 0 0 100\n")
        text = text.replace(BLOCK_2_ROW, f"2  50  0  1  0  0  0  {extension}\n")
    else:
        assert kind == "extended"
        text = text.replace(GRADIENT_6_ROW, f"{GRADIENT_6_ROW}7 {amplitude} 0 0 10 11 100\n")
        text = text.replace(BLOCK_2_ROW, f"2  50  0  7  0  0  0  {extension}\n")
        shapes = "shape_id 10\nnum_samples 1\n1\n\nshape_id 11\nnum_samples 1\n0\n"
        text = text.replace(SIGNATURE_HEADER, f"\n{shapes}{SIGNATURE_HEADER}")
    path = directory / f"valid_1_5_1_length_0_{kind}_{amplitude}.seq"
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


def test_an_event_of_length_0_at_the_end_of_a_block_that_the_session_rotates_has_two_points():
    """When the one event of a block has all its points at the end of the block
    (`Late(shift=1.0, length_0=True)`) and the session's field of view rotates the block, each
    played event of that block has the points at the start and at the end of the block, with
    the values of the decoding (`_check_block_1_has_two_points_or_more`), and `gradient_peaks`
    runs."""
    snap = load(TRAPEZOIDS, Late(shift=1.0, length_0=True), session=Session(fov_rotation=QUARTER_Z))
    _check_block_1_has_two_points_or_more(snap)
    played = played_gradients(snap)
    duration = float(snap.decoding.block_durations[1])
    for column in (played.gx, played.gy, played.gz):
        delay, offsets, _ = played.points[int(column[1])]
        assert delay == 0.0 and np.array_equal(offsets, [0.0, duration])
    gradient_peaks(snap)


# The kinds of the event of length 0 of `_length_0_file`, the sessions, and the ranges of
# `gradient_peaks`: the whole file, and a window around block 2 (play index 1, 300 to 800 us)
# with a part of each block next to it.
LENGTH_0_KINDS = ["trapezoid", "extended"]
LENGTH_0_SESSIONS = [
    pytest.param(None, id="unrotated"),
    pytest.param(Session(fov_rotation=QUARTER_Z), id="fov"),
]
LENGTH_0_WINDOWS = [pytest.param(None, id="whole"), pytest.param((200e-6, 900e-6), id="window")]
# Times of block 2 (us from its start, 500 us long) away from the one time of the event (100 us).
LENGTH_0_TIMES_US = np.array([0.0, 50.0, 99.0, 101.0, 250.0, 499.0])


def check_an_event_of_length_0_plays_0_in_the_measurements(
    directory: pathlib.Path, interpreter, kind: str, session, window
) -> None:
    """The measurements of `_length_0_file` of `kind` (written in `directory`) through
    `interpreter` with `session` are those of the same file with the amplitude 0:
    `gradient_peaks` with `range_s` (the peak of x, its block and its time, the vector peak, then
    the whole result), and `block_gradient_values` (the peak of x in block 2, then the whole
    result). A warning of the scanner settings (an interpreter that leaves the rotations of the
    file unapplied) is ignored."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        snap = load(_length_0_file(directory, 0, kind=kind), interpreter, session=session)
        zero = load(_length_0_file(directory, 0, 0, kind), interpreter, session=session)
    peaks, expected = gradient_peaks(snap, range_s=window), gradient_peaks(zero, range_s=window)
    x, x_zero = peaks.axes["x"], expected.axes["x"]
    assert (x.peak_hz_per_m, x.peak_block, x.peak_time_s) == (
        x_zero.peak_hz_per_m,
        x_zero.peak_block,
        x_zero.peak_time_s,
    )
    assert peaks.vector_peak_hz_per_m == expected.vector_peak_hz_per_m
    assert peaks == expected
    values, expected_values = block_gradient_values(snap), block_gradient_values(zero)
    assert values.peak_hz_per_m["x"][1] == expected_values.peak_hz_per_m["x"][1]
    assert values == expected_values


def check_the_played_points_of_an_event_of_length_0_are_0(
    directory: pathlib.Path, interpreter, kind: str
):
    """With no session, block 2 of `_length_0_file` of `kind` (written in `directory`) keeps the
    decoded event of `interpreter` on gx, whose points are all at one time and not all 0. The
    decoding's `gradients_at` is 0 on each axis at `LENGTH_0_TIMES_US` of the block, and the
    played points of the event have the delay and the offsets of the decoding and the values 0.
    Returns the snapshot. A warning of the scanner settings is ignored."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        snap = load(_length_0_file(directory, 0, kind=kind), interpreter)
    event = 1 if kind == "trapezoid" else 7
    played = played_gradients(snap)
    assert int(played.gx[1]) == event
    delay, offsets, amp = snap.decoding.gradient_points(event, 1, 0)
    assert np.all(offsets == offsets[0]) and np.any(amp != 0)
    blocks = np.ones(LENGTH_0_TIMES_US.size, dtype=np.int64)
    assert np.array_equal(snap.decoding.gradients_at(blocks, LENGTH_0_TIMES_US), np.zeros((6, 3)))
    played_delay, played_offsets, played_amp = played.points[event]
    assert played_delay == delay and np.array_equal(played_offsets, offsets)
    assert np.array_equal(played_amp, np.zeros(amp.size)), played_amp
    return snap


@pytest.mark.parametrize("window", LENGTH_0_WINDOWS)
@pytest.mark.parametrize("session", LENGTH_0_SESSIONS)
@pytest.mark.parametrize("kind", LENGTH_0_KINDS)
def test_an_event_of_length_0_plays_0_in_the_measurements_through_spec(
    tmp_path, kind, session, window
):
    """Through `spec`, a gradient event of length 0 with an amplitude that is not 0 (a trapezoid
    with rise, flat and fall times 0, or an extended trapezoid of one vertex) alone in a block
    gives the measurements of the same file with the amplitude 0, over the whole file and in a
    window around the block, with and without a rotation of the field of view
    (`check_an_event_of_length_0_plays_0_in_the_measurements`)."""
    check_an_event_of_length_0_plays_0_in_the_measurements(tmp_path, "spec", kind, session, window)


@pytest.mark.parametrize("kind", LENGTH_0_KINDS)
def test_the_played_points_of_an_event_of_length_0_are_0_through_spec(tmp_path, kind):
    """Through `spec`, the played points of a gradient event of length 0 with an amplitude that
    is not 0, decoded in a block that is not read through `gradients_at`, are 0 at the times of
    the decoding, as `gradients_at` plays the block
    (`check_the_played_points_of_an_event_of_length_0_are_0`)."""
    check_the_played_points_of_an_event_of_length_0_are_0(tmp_path, "spec", kind)


# Five readouts with the same events and duration (the trapezoid 1 on gx and the ADC 1, 400 us),
# each with its own rotation object: k times 36 degrees about z, for k from 1 to 5.
ROTATED_READOUTS = """\
[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06
RequiredExtensions ROTATIONS

[BLOCKS]
1 40 0 1 0 0 1 1
2 40 0 1 0 0 1 2
3 40 0 1 0 0 1 3
4 40 0 1 0 0 1 4
5 40 0 1 0 0 1 5

[TRAP]
1 100000 100 200 100 0

[ADC]
1 8 25000 100 0 0 0 0 0

[EXTENSIONS]
1 1 1 0
2 1 2 0
3 1 3 0
4 1 4 0
5 1 5 0

extension ROTATIONS 1
{rotations}
"""


def test_blocks_with_the_same_events_and_duration_are_planned_once(tmp_path, monkeypatch):
    """Five blocks that `spec` rotates (1.5.1), with the same events and duration and five
    rotations, get one plan of the times of their points (`_played._plan`), not one for each
    rotation. Each block keeps keys of its own, and the points are the gradients of the decoding
    (`check_the_points_are_the_gradients`)."""
    rows = []
    for k in range(1, 6):
        half = math.radians(36 * k) / 2
        rows.append(f"{k} {math.cos(half):.6f} 0 0 {math.sin(half):.6f}")
    path = tmp_path / "rotated_readouts.seq"
    path.write_text(ROTATED_READOUTS.format(rotations="\n".join(rows)))
    calls: list[int] = []
    plan = _played._plan

    def counted(*args, **kwargs):
        calls.append(1)
        return plan(*args, **kwargs)

    monkeypatch.setattr(_played, "_plan", counted)
    snap = load(path, "spec")
    played = played_gradients(snap)
    assert np.unique(played.gx).size == 5
    assert len(calls) == 1
    check_the_points_are_the_gradients(path, "spec")


# ---- A NaN of the gradients in the peaks ----


def check_a_nan_of_one_block_is_credited_to_its_first_nan(
    snap,
    clean,
    play: int,
    axes: str,
    peak_time_s: float,
    slew_time_s: float,
    vector_time_s: float,
) -> None:
    """`gradient_peaks` and `block_gradient_values` of `snap`, whose gradients are NaN in the
    block `play` (play index) on the axes `axes` (some of "xyz") and nowhere else, follow the
    rule of a NaN in the peaks (a NaN propagates). On each axis of `axes`:

    - `gradient_peaks` gives a NaN peak, slew and RMS, and credits the peak and the slew to that
      block (its block ID), at `peak_time_s` (its first NaN point) and at `slew_time_s` (the
      start of its first NaN segment);
    - `block_gradient_values` gives that block a NaN peak at `peak_time_s` and a NaN slew at
      `slew_time_s`.

    The vector peak of the block is NaN at `vector_time_s` (the first time of the points of the
    three axes at which the vector is NaN), and so is the vector peak of `gradient_peaks`,
    credited to that block. Every other value is the value of `clean`, the same sequence with
    no NaN: the other axes of `gradient_peaks`, each value of `block_gradient_values` in the
    other blocks, and the other axes and the junctions of the block `play`. The times agree to
    `TIME_TOLERANCE`."""
    at = {"rel": 0, "abs": TIME_TOLERANCE}
    block_id = int(sequence_index(snap).block_id[play])

    peaks, expected = gradient_peaks(snap), gradient_peaks(clean)
    assert peaks.reason is None and peaks.range_s == expected.range_s
    for axis in "xyz":
        got = peaks.axes[axis]
        if axis not in axes:
            assert got == expected.axes[axis], axis
            continue
        assert math.isnan(got.peak_hz_per_m), axis
        assert got.peak_time_s == pytest.approx(peak_time_s, **at), axis
        assert got.peak_block == block_id, axis
        assert math.isnan(got.max_slew_hz_per_m_per_s), axis
        assert got.slew_time_s == pytest.approx(slew_time_s, **at), axis
        assert got.slew_block == block_id, axis
        assert math.isnan(got.rms_hz_per_m), axis
    assert math.isnan(peaks.vector_peak_hz_per_m)
    assert peaks.vector_peak_time_s == pytest.approx(vector_time_s, **at)
    assert peaks.vector_peak_block == block_id

    values, expected = block_gradient_values(snap), block_gradient_values(clean)
    assert np.array_equal(values.block_id, expected.block_id)
    assert np.array_equal(values.start_s, expected.start_s)
    other = np.arange(values.block_id.size) != play
    fields = (
        "peak_hz_per_m",
        "peak_time_s",
        "slew_hz_per_m_per_s",
        "slew_time_s",
        "junction_hz_per_m_per_s",
    )
    for field in fields:
        for axis in "xyz":
            got, want = getattr(values, field)[axis], getattr(expected, field)[axis]
            assert np.array_equal(got[other], want[other]), (field, axis)
            if axis not in axes or field == "junction_hz_per_m_per_s":
                assert got[play] == want[play], (field, axis)
    for axis in axes:
        assert np.isnan(values.peak_hz_per_m[axis][play]), axis
        assert values.peak_time_s[axis][play] == pytest.approx(peak_time_s, **at), axis
        assert np.isnan(values.slew_hz_per_m_per_s[axis][play]), axis
        assert values.slew_time_s[axis][play] == pytest.approx(slew_time_s, **at), axis
    assert np.array_equal(values.vector_peak_hz_per_m[other], expected.vector_peak_hz_per_m[other])
    assert np.array_equal(values.vector_peak_time_s[other], expected.vector_peak_time_s[other])
    assert np.isnan(values.vector_peak_hz_per_m[play])
    assert values.vector_peak_time_s[play] == pytest.approx(vector_time_s, **at)


@dataclasses.dataclass(frozen=True, slots=True)
class OneNaN(Unrotated):
    """A plugin interpreter of the tests whose decoding gives the gradient event of block 1 one
    NaN point, as a plugin can read a NaN that `spec` rejects (`syntax.number`): the point 1 of
    the event on gx (in `TRAPEZOIDS`, the end of the rise of the trapezoid). With `nan` False it
    gives no NaN. `spec`'s model and decoding otherwise, with the session."""

    name: ClassVar[str] = "one-nan"
    nan: bool = True

    def decode(self, data: SequenceData, session=None) -> "OneNaNDecoding":
        return OneNaNDecoding(self, decode(dataclasses.replace(data, interpreter=Spec()), session))


@dataclasses.dataclass(frozen=True, eq=False)
class OneNaNDecoding(DoubledDecoding):
    """The decoding of `OneNaN`: `spec`'s gradients, rotated as `spec` rotates them, with the
    point 1 of the gx event of block 1 NaN (when `nan`). `gradients_at` is NaN where the straight
    lines of those points are: in block 1, strictly between the points 0 and 2 of the event. It is
    NaN on gx, and on every axis when the session's field of view rotates the block: the
    rotation of a vector with a NaN is NaN on each axis (NaN times 0 is NaN), as with
    `cpp-siemens`. The variants and the rotation record are those of `DoubledDecoding`."""

    def gradients_at(self, block_index: Any, time_us: Any, rotated: bool | None = None):
        values = self.spec.gradients_at(block_index, time_us, rotated)
        if not self.interpreter.nan:
            return values
        delay, offsets, _ = self.spec.gradient_points(1, 1, 0)
        t = np.asarray(time_us, dtype=np.float64).reshape(-1) * 1e-6 - delay
        in_block_1 = np.asarray(block_index).reshape(-1) == 1
        inside = in_block_1 & (t > offsets[0]) & (t < offsets[2])
        axes = slice(None) if rotated is not False and self.session.rotates else 0
        values = values.copy()
        values[inside, axes] = np.nan
        return values

    def gradient_points(self, key: int, block: int, axis: int):
        delay, offsets, amp = self.spec.gradient_points(key, block, axis)
        if block == 1 and self.interpreter.nan:
            amp = amp.copy()
            amp[1] = np.nan
        return delay, offsets, amp


@pytest.mark.parametrize(
    ("session", "axes"),
    [
        pytest.param(None, "x", id="decoded"),
        pytest.param(Session(fov_rotation=QUARTER_Z), "xyz", id="fov"),
    ],
)
def test_a_nan_point_of_a_block_is_credited_to_the_block_at_its_first_nan(session, axes):
    """When the decoding gives one point of the event of a block NaN (`OneNaN`), the peaks follow
    the rule of a NaN (`check_a_nan_of_one_block_is_credited_to_its_first_nan`), with the event
    of the block decoded (no session), and read through `gradients_at` (the session's field of
    view rotates every block, and the NaN is on every axis). The time of the first NaN point is
    the end of the rise of block 1, and the first NaN segment is the rise."""
    snap = load(TRAPEZOIDS, OneNaN(), session=session)
    clean = load(TRAPEZOIDS, OneNaN(nan=False), session=session)
    # Block 1 starts at 1 ms. Its trapezoid 1 on gx has the delay 0 and rises in 60 us: its point
    # 1, the NaN, is at 1.06 ms, and the segment before it starts at 1 ms. The vector is NaN
    # first at that point too: the polyline of gx at the start of block 1 is 0 on both sides.
    check_a_nan_of_one_block_is_credited_to_its_first_nan(
        snap, clean, 1, axes, peak_time_s=1.06e-3, slew_time_s=1e-3, vector_time_s=1.06e-3
    )
