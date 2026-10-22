"""Tests of the scanner session (`synth.scanner`, task R16 of `docs/plans/parser-redesign.md`, P20
section 7.8 and P22): the `Session`, its shared simulation, the records of what a decoding applied,
`SettingError`, the stored and actual durations of `spec`'s decoding, `load` with a session, and
the version of the plugin protocol.

The fixture `tests/session/scanner_session.seq` (1.5.1) has, in play order from 0: 0 gx; 1 a soft
delay TE (num 0, offset -100 us, factor 2); 2 gx rotated by 90 degrees about z; 3 gx with NOROT 1;
4 gy with NOROT 0 and NOSLC 1; 5 gz with NOSCL 1 and NOSLC 0; 6 a soft delay TE (num 0, offset
5000 us, factor -1); 7 a soft delay TR (num 1, offset 0, factor 1); 8 gx. The tests through
`cpp-siemens` are in the plugin's tests (`packages/pulseq-cpp-siemens/tests/test_session.py`).
"""

import copy
import dataclasses
import math
import pickle
import re
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from test_interpreters import _install
from test_played import check_the_points_are_the_gradients

from pulseq_analysis import seqfile, synth
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import gradient_peaks
from pulseq_analysis.seqfile import Spec, interpreters, read_seqfile
from pulseq_analysis.synth import (
    FovRecord,
    Session,
    SettingError,
    SoftDelayRecord,
)
from pulseq_analysis.synth.scanner import SoftDelay, fov_flags, soft_delay_durations
from pulseq_analysis.synth.seq_index import sequence_index

ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = ROOT / "tests" / "session" / "scanner_session.seq"
SEQFILES = ROOT / "tests" / "seqfiles"

# 90 degrees about x: y goes to z, z to -y.
QUARTER_X = (np.sqrt(0.5), np.sqrt(0.5), 0.0, 0.0)
# The matrix of a quaternion (q0, qx, qy, qz), the active rotation.


def _matrix(q) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _edited(tmp_path: Path, old: str, new: str, name: str = "edited.seq") -> Path:
    """The session fixture with the text `old` replaced by `new` (once)."""
    text = SESSION_FILE.read_text()
    assert old in text
    path = tmp_path / name
    path.write_text(text.replace(old, new, 1))
    return path


def _with_version(tmp_path: Path, minor: int, revision: int) -> Path:
    return _edited(tmp_path, "minor 5\nrevision 1", f"minor {minor}\nrevision {revision}")


# ---- The session ----


def test_the_default_session_is_neutral_and_a_session_compares_by_value():
    """`Session()` is the neutral session (rule 1). A session is frozen, compares by value, is a
    key of a dict, keeps the soft delays as (hint, value) pairs sorted by hint, divides the
    quaternion by its norm, and says what is set in `str`."""
    neutral = Session()
    assert neutral.neutral and not neutral.rotates and not neutral.scales
    assert neutral.soft_delays == () and str(neutral) == "session: neutral"
    assert neutral.fov_rotation == (1.0, 0.0, 0.0, 0.0)
    assert neutral.gradient_scaling == (1.0, 1.0, 1.0)
    session = Session(soft_delays={"TR": 2, "TE": 5e-3}, gradient_scaling=(1, 2, 1))
    assert session.soft_delays == (("TE", 5e-3), ("TR", 2.0))
    assert session == Session(soft_delays=[("TE", 5e-3), ("TR", 2.0)], gradient_scaling=(1, 2, 1))
    assert {session: 1}[Session(soft_delays={"TE": 5e-3, "TR": 2}, gradient_scaling=(1, 2, 1))]
    assert str(session) == (
        "session(soft_delays={'TE': 0.005, 'TR': 2.0}, gradient_scaling=(1.0, 2.0, 1.0))"
    )
    near = Session(fov_rotation=(1 + 5e-7, 0, 0, 0))
    assert near.fov_rotation == (1.0, 0.0, 0.0, 0.0) and near.neutral
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.soft_delays = ()  # type: ignore[misc]
    assert pickle.loads(pickle.dumps(session)) == session


@pytest.mark.parametrize(
    "kwargs, error, message",
    [
        ({"soft_delays": {"": 1.0}}, TypeError, "hint is a text"),
        ({"soft_delays": {3: 1.0}}, TypeError, "hint is a text"),
        ({"soft_delays": {"TE": "5"}}, TypeError, "real number"),
        ({"soft_delays": {"TE": True}}, TypeError, "real number"),
        ({"soft_delays": {"TE": float("nan")}}, ValueError, "not a finite number"),
        ({"soft_delays": [("TE", 1.0), ("TE", 2.0)]}, ValueError, "two values"),
        ({"soft_delays": "TE"}, TypeError, "mapping"),
        ({"fov_rotation": (1, 0, 0)}, ValueError, "4 values"),
        ({"fov_rotation": (1, 1, 0, 0)}, ValueError, "not 1 within 1e-6"),
        ({"fov_rotation": (0, 0, 0, 0)}, ValueError, "not 1 within 1e-6"),
        ({"gradient_scaling": (1, 1)}, ValueError, "3 values"),
        ({"gradient_scaling": (1, 0, 1)}, ValueError, "above 0"),
        ({"gradient_scaling": (1, -1, 1)}, ValueError, "above 0"),
        ({"gradient_scaling": (1, float("inf"), 1)}, ValueError, "not a finite number"),
    ],
)
def test_a_session_refuses_a_value_that_is_not_a_setting(kwargs, error, message):
    with pytest.raises(error, match=re.escape(message)):
        Session(**kwargs)


def test_a_setting_that_the_session_does_not_have_is_a_type_error():
    """Rule 8: a setting that is not one of the session's is a TypeError when it is made."""
    with pytest.raises(TypeError):
        Session(repetitions=2)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="Session"):
        synth.decode(read_seqfile(SESSION_FILE), session={"TE": 1})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Session"):
        load(SESSION_FILE, session={"TE": 1})  # type: ignore[arg-type]


# ---- The shared simulation ----


def test_a_soft_delay_is_the_rule_of_the_specification_rounded_half_away_from_zero():
    """`soft_delay_durations`: `value / factor + offset` (spec:550-563) in units of the raster,
    rounded half away from 0 as MATLAB Pulseq's `round` (Sequence.m:2564-2576)."""
    delays = [SoftDelay(0, 0, 25e-6, 1.0, "TD"), SoftDelay(1, 1, 0.0, 1.0, "TS")]
    stored = np.array([7, 8])
    pure = np.array([True, True])
    actual, record = soft_delay_durations(
        Session(soft_delays={"TD": 0.0}), delays, stored, 10e-6, pure, interpreter="spec",
        version=(1, 5, 1),
    )  # fmt: skip
    assert actual.tolist() == [3, 8]  # 2.5 rounds to 3, the block of TS keeps its stored 8
    assert record == SoftDelayRecord((("TD", 0.0),), ("TD", "TS"), blocks=2, applied=1)
    assert record.unset == ("TS",)
    actual, _ = soft_delay_durations(
        Session(soft_delays={"TD": 1e-3, "TS": 14e-6}), delays, stored, 10e-6, pure,
        interpreter="spec", version=(1, 5, 1),
    )  # fmt: skip
    assert actual.tolist() == [103, 1]


def test_the_flags_of_the_field_of_view_are_a_state_across_blocks():
    """`fov_flags`: a LABELSET sets a flag for its block and the blocks after it, in the order
    of the block's list; a flag of another name, or no scaling flag, changes nothing."""
    sets = [(1, "NOROT", 1), (3, "NOROT", 0), (3, "NOSLC", 1), (4, "NOSLC", 0), (4, "NOSLC", 2)]
    norot, noscale = fov_flags(6, sets, "NOSLC")
    assert norot.tolist() == [False, True, True, False, False, False]
    assert noscale.tolist() == [False, False, False, True, True, True]
    norot, noscale = fov_flags(6, sets, None)
    assert noscale.tolist() == [False] * 6 and norot.any()
    norot, noscale = fov_flags(6, sets, "NOSCL")
    assert not noscale.any()


# ---- `spec`'s decoding under a session ----


def test_spec_decodes_with_the_neutral_session_by_default():
    """With no session, the decoding has `Session()`, the actual durations are the stored ones,
    and the records say what the file has: two hints at their stored durations, and the blocks
    with NOROT and with NOSLC (the specification's spelling; NOSCL is an unknown label for
    `spec`, D2.19)."""
    data = read_seqfile(SESSION_FILE)
    decoding = synth.decode(data)
    assert decoding.session == Session()
    assert np.array_equal(decoding.block_durations, data.block_durations_s)
    assert np.array_equal(decoding.stored_block_durations, data.block_durations_s)
    assert not decoding.block_durations.flags.writeable
    record = decoding.soft_delay_record
    assert record == SoftDelayRecord((), ("TE", "TR"), blocks=3, applied=0)
    assert (
        str(record)
        == "soft delays: 0 of 3 block(s) set by the session; TE, TR at the stored durations"
    )
    norot, noscale = decoding.fov_flags()
    assert np.flatnonzero(norot).tolist() == [3]
    assert np.flatnonzero(noscale).tolist() == [4]
    assert decoding.fov_record == FovRecord(
        (1.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0), "NOSLC", norot=1, noscale=1, rotated=0, scaled=0
    )
    assert synth.decode(data, Session()).fov_record == decoding.fov_record


def test_spec_sets_the_duration_of_each_soft_delay_by_its_hint():
    """`Session(soft_delays=...)`: TE = 2 ms gives block 1 2e-3 / 2 - 100 us = 900 us and block
    6 2e-3 / -1 + 5000 us = 3 ms; TR = 10 ms gives block 7 10 ms. The stored durations do not
    change, and `gradients_at` is 0 after the actual end of a block."""
    data = read_seqfile(SESSION_FILE)
    decoding = synth.decode(data, Session(soft_delays={"TE": 2e-3, "TR": 10e-3}))
    expected = data.block_durations_s.copy()
    expected[[1, 6, 7]] = [900e-6, 3e-3, 10e-3]
    np.testing.assert_allclose(decoding.block_durations, expected, rtol=1e-12)
    assert np.array_equal(decoding.stored_block_durations, data.block_durations_s)
    assert decoding.soft_delay_record == SoftDelayRecord(
        (("TE", 2e-3), ("TR", 10e-3)), ("TE", "TR"), blocks=3, applied=3
    )
    only_te = synth.decode(data, Session(soft_delays={"TE": 2e-3}))
    assert only_te.soft_delay_record.unset == ("TR",)
    assert only_te.block_durations[7] == data.block_durations_s[7]
    short = _short_block_decoding(data)
    assert short.gradients_at([0], [450e-6])[0, 0] == 0


def _short_block_decoding(data: seqfile.SequenceData):
    """A decoding whose block 0 ends at 400 us: `SpecDecoding` with the actual durations
    changed, to check that `gradients_at` stops at the actual end."""
    decoding = synth.decode(data)
    durations = decoding.block_durations.copy()
    durations[0] = 400e-6
    return dataclasses.replace(decoding, block_durations=durations)


@pytest.mark.parametrize(
    "session, reason",
    [
        (Session(soft_delays={"TX": 1e-3}), "no soft delay of a block has this hint (the hints: 'TE', 'TR')"),
        (Session(soft_delays={"TE": 20e-3}), "the block at play index 6 gets the negative duration -0.015 s"),
    ],
)  # fmt: skip
def test_a_soft_delay_that_the_file_does_not_have_is_a_setting_error(session, reason):
    """Rule 8: a hint that no block has, and a value that gives a negative duration, raise
    `SettingError`, a ValueError that names the setting, the interpreter, the version and the
    reason; `load` raises it too."""
    data = read_seqfile(SESSION_FILE)
    with pytest.raises(SettingError) as caught:
        synth.decode(data, session)
    error = caught.value
    assert isinstance(error, ValueError) and error.reason == reason
    assert error.interpreter == "spec" and error.version == (1, 5, 1)
    hint = session.soft_delays[0][0]
    assert error.setting == f"soft_delays[{hint!r}]"
    assert str(error) == (
        f"the setting soft_delays[{hint!r}] does not apply to this file (version 1.5.1) under the "
        f"interpreter spec: {reason}"
    )
    assert pickle.loads(pickle.dumps(error)).reason == reason
    with pytest.raises(SettingError):
        load(SESSION_FILE, session=session)


@pytest.mark.parametrize("value", [1e14, 1e15])
def test_a_soft_delay_whose_duration_does_not_fit_an_int64_is_a_setting_error(value):
    """Rule 8: TR = 1e14 s or 1e15 s gives block 7 (factor 1, offset 0) more ticks of the 10 us
    raster than an int64 holds (1e19 or 1e20): a `SettingError` for the hint that names the
    block's play index, as for a duration that is negative; `load` raises it too. At the
    boundary, with a raster of 1 s: the largest float below 2**63 is the duration, and 2**63 is
    a `SettingError`."""
    data = read_seqfile(SESSION_FILE)
    session = Session(soft_delays={"TR": value})
    with pytest.raises(SettingError) as caught:
        synth.decode(data, session)
    assert caught.value.setting == "soft_delays['TR']"
    assert caught.value.reason == (
        f"the block at play index 7 gets the duration {value:g} s, more ticks of the raster "
        "than an int64 holds"
    )
    with pytest.raises(SettingError):
        load(SESSION_FILE, session=session)
    delays = [SoftDelay(0, 0, 0.0, 1.0, "TD")]
    stored = np.array([7])
    pure = np.array([True])
    below = math.nextafter(2.0**63, 0.0)
    actual, _ = soft_delay_durations(
        Session(soft_delays={"TD": below}), delays, stored, 1.0, pure, interpreter="spec",
        version=(1, 5, 1),
    )  # fmt: skip
    assert actual.tolist() == [int(below)]
    with pytest.raises(SettingError, match="the block at play index 0 gets the duration"):
        soft_delay_durations(
            Session(soft_delays={"TD": 2.0**63}), delays, stored, 1.0, pure, interpreter="spec",
            version=(1, 5, 1),
        )  # fmt: skip


@pytest.mark.parametrize(
    "old, new, hint, reason",
    [
        # Block 2 (a gx block) gets the soft delay TR in place of its rotation.
        ("3 50 0 1 0 0 0 1\n", "3 50 0 1 0 0 0 10\n", "TR", "the block at play index 2 has an RF, gradient or ADC event"),
        # Block 1 gets a second soft delay (TR) after its TE.
        ("7 2 1 0\n", "7 2 1 10\n", "TR", "the block at play index 1 has more than one soft delay"),
        # The second TE has the numeric ID 2.
        ("2 0 5000 -1 TE", "2 2 5000 -1 TE", "TE", "its soft delays have the numeric IDs [0, 2], not one"),
        # TR has the numeric ID of TE.
        ("3 1 0 1 TR", "3 0 0 1 TR", "TR", "its numeric ID 0 is also that of the hints ['TE']"),
    ],
)  # fmt: skip
def test_a_soft_delay_that_is_not_one_value_of_a_pure_delay_block_is_a_setting_error(
    tmp_path, old, new, hint, reason
):
    """The user, 2026-10-13: a soft delay of a block with an event (spec:545), a block with two
    soft delays, and a hint whose rows disagree on the numeric ID (or a numeric ID with two
    hints, as MATLAB Pulseq refuses, Sequence.m:2544-2557) raise `SettingError` for that hint.
    With no value for the hint, the file decodes. The list entry 10 is the soft delay TR."""
    text = SESSION_FILE.read_text()
    text = text.replace("[EXTENSIONS]\n", "[EXTENSIONS]\n10 2 3 0\n", 1)
    path = tmp_path / "edited.seq"
    path.write_text(text.replace(old, new, 1))
    data = read_seqfile(path)
    synth.decode(data)
    with pytest.raises(SettingError) as caught:
        synth.decode(data, Session(soft_delays={hint: 2e-3}))
    assert caught.value.reason.startswith(reason)


def test_soft_delays_in_a_file_older_than_1_5_0_are_a_setting_error(tmp_path):
    """Before 1.5.0 extension DELAYS is an extension that `spec` does not know (D4.6): a value for
    any hint is a `SettingError` that says so; the neutral session decodes."""
    data = read_seqfile(_with_version(tmp_path, 4, 2))
    assert synth.decode(data).soft_delay_record == SoftDelayRecord((), (), blocks=0, applied=0)
    with pytest.raises(
        SettingError, match=r"version 1\.4\.2.*soft delays came in revision 1\.5\.0"
    ):
        synth.decode(data, Session(soft_delays={"TE": 2e-3}))


def test_spec_turns_and_scales_the_field_of_view_in_the_order_of_matlab_pulseq():
    """The physical gradients are R_fov R_block S g (MATLAB's `mr.TransformFOV`, the user,
    2026-10-13): the scaling of the logical axes, except in a block with NOSLC (block 4); the
    block's rotation (block 2, 90 degrees about z); the rotation of the field of view, except in
    a block with NOROT (block 3). NOSCL (block 5) is an unknown label for `spec`: its block is
    scaled. `rotated=False` gives the logical gradients."""
    data = read_seqfile(SESSION_FILE)
    session = Session(fov_rotation=QUARTER_X, gradient_scaling=(2, 3, 4))
    decoding = synth.decode(data, session)
    blocks = np.array([0, 2, 3, 4, 5, 8])
    times = np.full(blocks.size, 300e-6)
    logical = decoding.gradients_at(blocks, times, rotated=False)
    np.testing.assert_array_equal(logical, synth.decode(data).gradients_at(blocks, times, False))
    fov, block_rotation = _matrix(session.fov_rotation), _matrix((np.sqrt(0.5), 0, 0, np.sqrt(0.5)))
    scale = np.diag([2.0, 3.0, 4.0])
    expected = [
        fov @ scale @ logical[0],
        fov @ block_rotation @ scale @ logical[1],
        scale @ logical[2],
        fov @ logical[3],
        fov @ scale @ logical[4],
        fov @ scale @ logical[5],
    ]
    got = decoding.gradients_at(blocks, times)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-6)
    np.testing.assert_array_equal(got, decoding.gradients_at(blocks, times, rotated=True))
    assert decoding.fov_record == FovRecord(
        session.fov_rotation, (2.0, 3.0, 4.0), "NOSLC", norot=1, noscale=1, rotated=8, scaled=8
    )
    assert str(decoding.fov_record).startswith("field of view: rotation")


def test_the_flags_of_1_4_1_have_no_effect_in_an_older_file(tmp_path):
    """Before 1.4.1 NOROT and NOSLC are labels that `spec` does not apply (D4.7): every block is
    turned and scaled by the field of view, and the records have no flag."""
    data = read_seqfile(_with_version(tmp_path, 4, 0))
    decoding = synth.decode(data, Session(fov_rotation=QUARTER_X, gradient_scaling=(2, 1, 1)))
    norot, noscale = decoding.fov_flags()
    assert not norot.any() and not noscale.any()
    assert decoding.fov_record.rotated == decoding.fov_record.scaled == 9
    # Block 3 plays gx with NOROT: turned about x and scaled, so 2 * 1e6 on x.
    assert decoding.gradients_at([3], [300e-6])[0, 0] == pytest.approx(2e6)


# ---- `load` and the measurements ----


def test_load_decodes_under_the_session_and_the_snapshot_records_it():
    """`load(path, session=...)` gives a snapshot of the decoding under the session, with its
    records; the index of the blocks has the actual durations; a copy keeps the session."""
    session = Session(soft_delays={"TE": 2e-3, "TR": 10e-3}, gradient_scaling=(2, 1, 1))
    snap = load(SESSION_FILE, session=session)
    assert snap.session == session and snap.decoding.session == session
    assert snap.soft_delay_record == snap.decoding.soft_delay_record
    assert snap.fov_record == snap.decoding.fov_record and snap.fov_record.scaled == 8
    index = sequence_index(snap)
    np.testing.assert_allclose(index.duration_s, snap.decoding.block_durations, rtol=0)
    assert index.end_s == pytest.approx(float(snap.decoding.block_durations.sum()))
    for copied in (pickle.loads(pickle.dumps(snap)), copy.deepcopy(snap)):
        assert copied.session == session
    assert load(SESSION_FILE).session == Session()


def test_the_measurements_take_the_gradients_of_the_session():
    """The peaks of the gradients follow the session: a scaling of x by 2 doubles the peak of x,
    and the rotation of the field of view by 90 degrees about x moves the peak of y to z."""
    neutral = gradient_peaks(load(SESSION_FILE))
    scaled = gradient_peaks(load(SESSION_FILE, session=Session(gradient_scaling=(2, 1, 1))))
    assert scaled.axes["x"].peak_hz_per_m == pytest.approx(2 * neutral.axes["x"].peak_hz_per_m)
    turned = gradient_peaks(load(SESSION_FILE, session=Session(fov_rotation=QUARTER_X)))
    assert turned.axes["z"].peak_hz_per_m == pytest.approx(neutral.axes["y"].peak_hz_per_m)


@pytest.mark.parametrize(
    "session",
    [
        Session(),
        Session(soft_delays={"TE": 2e-3, "TR": 10e-3}),
        Session(fov_rotation=QUARTER_X),
        Session(gradient_scaling=(2, 3, 4)),
        Session(fov_rotation=QUARTER_X, gradient_scaling=(2, 3, 4)),
    ],
    ids=["neutral", "soft-delays", "rotation", "scaling", "both"],
)
def test_the_points_of_the_played_events_are_the_gradients_under_a_session(session, monkeypatch):
    """The played gradients (`_played`) under a session are the gradients of the decoding: the
    blocks that the field of view turns or scales are given by `gradients_at`."""
    real_load = load

    def load_with_session(path, interpreter):
        return real_load(path, interpreter, session=session)

    import test_played

    monkeypatch.setattr(test_played, "load", load_with_session)
    check_the_points_are_the_gradients(SESSION_FILE, "spec")


# ---- The plugin protocol (P22) ----


@dataclasses.dataclass(frozen=True, slots=True)
class SessionPlugin:
    """A plugin interpreter of protocol version 1: `spec`'s model and decoding under its own
    name. Its `decode` takes the session."""

    name: ClassVar[str] = "session-plugin"
    protocol: ClassVar[int] = 1
    max_shape_samples: int | None = interpreters.DEFAULT_MAX_SHAPE_SAMPLES

    def read(self, path: Path) -> seqfile.SequenceData:
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: seqfile.SequenceData, session=None):
        return synth.decode(dataclasses.replace(data, interpreter=Spec()), session)


@dataclasses.dataclass(frozen=True, slots=True)
class OldPlugin:
    """A plugin interpreter of the protocol before R16: no version, `decode(data)`."""

    name: ClassVar[str] = "old-plugin"

    def read(self, path: Path) -> seqfile.SequenceData:
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: seqfile.SequenceData):
        return synth.decode(dataclasses.replace(data, interpreter=Spec()))


def test_the_plugin_protocol_has_a_version_and_decode_takes_the_session(monkeypatch):
    """P22: the package uses a plugin of its protocol version (`seqfile.PROTOCOL`, 1); another
    version, or none, is a TypeError that names both; `synth.decode` and `load` give the plugin
    the session (the neutral one when none is given)."""
    assert seqfile.PROTOCOL == interpreters.PROTOCOL == 1
    _install(monkeypatch, **{"session-plugin": f"{__name__}:SessionPlugin"})
    plugin = seqfile.interpreter("session-plugin")
    data = read_seqfile(SESSION_FILE, plugin)
    session = Session(soft_delays={"TE": 2e-3})
    assert synth.decode(data).session == Session()
    assert synth.decode(data, session).session == session
    assert load(SESSION_FILE, plugin, session=session).soft_delay_record.applied == 2
    message = "implements the plugin protocol version None, and this pulseq-analysis uses version 1"
    _install(monkeypatch, **{"old-plugin": f"{__name__}:OldPlugin"})
    with pytest.raises(TypeError, match=message):
        seqfile.interpreter("old-plugin")
    with pytest.raises(TypeError, match=message):
        read_seqfile(SESSION_FILE, OldPlugin())
