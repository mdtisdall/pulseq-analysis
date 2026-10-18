"""The scanner session through `cpp-siemens` (task R16 of `docs/plans/parser-redesign.md` of
pulseq-analysis, P20 section 7.8 and P22): `CppSiemens.decode(data, session)` applies the soft
delays with the reader's hook `setActualSoftDelay_ru` and the field of view with the reader's
`rotate_vec3_by_quat`, by the shared rules of `pulseq_analysis.synth.scanner`; and it records what
the reader ignored. The fixture `tests/session/scanner_session.seq` of pulseq-analysis is described
in its `tests/test_session.py`.
"""

import tracemalloc
from pathlib import Path

import numpy as np
import pytest
import test_played
from pulseq_cpp_siemens.interpreter import CppSiemens
from test_played import check_the_points_are_the_gradients

from pulseq_analysis import seqfile, synth
from pulseq_analysis.analyses import load
from pulseq_analysis.seqfile import model, read_seqfile
from pulseq_analysis.synth import (
    FovRecord,
    ScannerSettingWarning,
    Session,
    SettingError,
    SoftDelayRecord,
)
from pulseq_analysis.synth.seq_index import sequence_index

ROOT = Path(__file__).resolve().parents[3]
SESSION_FILE = ROOT / "tests" / "session" / "scanner_session.seq"
SEQFILES = ROOT / "tests" / "seqfiles"
QUARTER_X = (np.sqrt(0.5), np.sqrt(0.5), 0.0, 0.0)
# The relative tolerance between the gradients of `spec` (float64) and of `cpp-siemens` (its
# float32 amplitudes, D7.2 of the package's record).
FLOAT32 = 1e-7


def test_cpp_siemens_implements_the_protocol_version_of_pulseq_analysis():
    """P22: `CppSiemens.protocol` is the version that pulseq-analysis uses, and the name gives
    the interpreter."""
    assert CppSiemens.protocol == seqfile.PROTOCOL == 1
    assert seqfile.interpreter("cpp-siemens") == CppSiemens()


def test_cpp_siemens_records_what_the_reader_ignored():
    """Rule 4: an extension that the reader does not know, and a label row that `decodeLabel`
    does not know (the reader leaves it out): `NOSLC`, the specification's spelling of `NOSCL`
    (D6.4), and `FOO`."""
    data = read_seqfile(SESSION_FILE, "cpp-siemens")
    assert data.records == (
        model.Record("label", "NOSLC", "unknown", 61),
        model.Record("label", "NOSLC", "unknown", 63),
    )
    records = read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens").records
    assert [(r.kind, r.subject, r.reason) for r in records] == [("extension", "UNKNOWN", "unknown")]
    labels = read_seqfile(SEQFILES / "valid_label_unknown.seq", "cpp-siemens").records
    assert ("label", "FOO", "unknown") in [(r.kind, r.subject, r.reason) for r in labels]


def test_the_soft_delays_of_cpp_siemens_are_those_of_spec_through_the_reader_s_hook():
    """The durations under a session's soft delays are `spec`'s on the fixture, set with the
    reader's hook (rule 3: a test checks that the interpreters agree), and the records agree."""
    session = Session(soft_delays={"TE": 2e-3, "TR": 10e-3})
    cpp = synth.decode(read_seqfile(SESSION_FILE, "cpp-siemens"), session)
    spec = synth.decode(read_seqfile(SESSION_FILE), session)
    assert np.array_equal(cpp.block_durations, spec.block_durations)
    assert np.array_equal(cpp.stored_block_durations, spec.stored_block_durations)
    assert (
        cpp.soft_delay_record
        == spec.soft_delay_record
        == SoftDelayRecord((("TE", 2e-3), ("TR", 10e-3)), ("TE", "TR"), blocks=3, applied=3)
    )
    neutral = synth.decode(read_seqfile(SESSION_FILE, "cpp-siemens"))
    assert neutral.session == Session()
    assert np.array_equal(neutral.block_durations, neutral.stored_block_durations)


def test_a_soft_delay_that_the_reader_did_not_attach_is_a_setting_error():
    """Rule 8 under `cpp-siemens`: the reader reads the row `1 0 -100.5 1 TE` as the offset -100
    us, the factor 0.5 and the hint `1 TE` (D2.16 of pulseq-analysis), so `TE` is a hint that it
    did not attach, and `1 TE` sets block 7 to 1e-3 / 0.5 - 100 us = 1.9 ms."""
    data = read_seqfile(SEQFILES / "valid_soft_delay_fraction.seq", "cpp-siemens")
    with pytest.raises(SettingError) as caught:
        synth.decode(data, Session(soft_delays={"TE": 1e-3}))
    assert caught.value.interpreter == "cpp-siemens" and caught.value.version == (1, 5, 1)
    assert "the hints: '1 TE'" in caught.value.reason
    decoding = synth.decode(data, Session(soft_delays={"1 TE": 1e-3}))
    assert decoding.block_durations[7] == pytest.approx(1.9e-3, rel=1e-12)
    with pytest.raises(SettingError, match="negative duration"):
        synth.decode(data, Session(soft_delays={"1 TE": 0.0}))


def test_the_field_of_view_of_cpp_siemens_is_that_of_spec_where_the_flags_agree():
    """The field of view through `cpp-siemens` (rotation "apply") gives `spec`'s gradients to
    float32 precision in each block where the flags agree. Block 4 (NOSLC) is scaled by
    `cpp-siemens`, whose reader leaves out `NOSLC`, and blocks 5 to 8 (NOSCL, never reset) are not
    (D6.4); `spec` does the reverse for block 4 and scales blocks 5 to 8 (D2.22)."""
    session = Session(fov_rotation=QUARTER_X, gradient_scaling=(2, 3, 4))
    cpp = synth.decode(read_seqfile(SESSION_FILE, CppSiemens(rotation="apply")), session)
    spec = synth.decode(read_seqfile(SESSION_FILE), session)
    blocks = np.repeat([0, 2, 3, 4, 5, 8], 5)
    times = np.tile([60e-6, 150e-6, 300e-6, 420e-6, 470e-6], 6)
    got, expected = cpp.gradients_at(blocks, times), spec.gradients_at(blocks, times)
    same = np.isin(blocks, [0, 2, 3])
    np.testing.assert_allclose(got[same], expected[same], rtol=0, atol=FLOAT32 * 4e6)
    assert not np.allclose(got[~same], expected[~same], rtol=0, atol=1.0)
    norot, noscale = cpp.fov_flags()
    assert np.flatnonzero(norot).tolist() == [3]
    assert np.flatnonzero(noscale).tolist() == [5, 6, 7, 8]
    assert cpp.fov_record == FovRecord(
        session.fov_rotation, (2.0, 3.0, 4.0), "NOSCL", norot=1, noscale=4, rotated=8, scaled=5
    )
    # The reader's default leaves the block's rotation unapplied, and the field of view applied.
    reader = synth.decode(read_seqfile(SESSION_FILE, "cpp-siemens"), session)
    logical = reader.gradients_at([2], [300e-6], rotated=False)[0]
    np.testing.assert_allclose(
        reader.gradients_at([2], [300e-6])[0], [2 * logical[0], 0, 0], rtol=0, atol=1e-6
    )
    np.testing.assert_array_equal(
        reader.gradients_at([2], [300e-6], rotated=True), cpp.gradients_at([2], [300e-6])
    )


def test_load_through_cpp_siemens_takes_the_session():
    """`load(path, "cpp-siemens", session=...)` gives the session and the records on the
    snapshot, and the index of the blocks has the actual durations. The session does not change
    the warning for the rotation that the reader's default leaves unapplied (block 2)."""
    session = Session(soft_delays={"TE": 2e-3, "TR": 10e-3}, gradient_scaling=(2, 1, 1))
    with pytest.warns(ScannerSettingWarning, match="1 block"):
        snap = load(SESSION_FILE, "cpp-siemens", session=session)
    assert snap.session == session and snap.soft_delay_record.applied == 3
    assert snap.fov_record.scaling_flag == "NOSCL"
    np.testing.assert_array_equal(sequence_index(snap).duration_s, snap.decoding.block_durations)


@pytest.mark.parametrize(
    "interpreter", [CppSiemens(), CppSiemens(rotation="apply")], ids=["reader", "apply"]
)
@pytest.mark.parametrize(
    "session",
    [
        Session(soft_delays={"TE": 2e-3, "TR": 10e-3}),
        Session(fov_rotation=QUARTER_X, gradient_scaling=(2, 3, 4)),
    ],
    ids=["soft-delays", "field-of-view"],
)
def test_the_points_of_the_played_events_are_the_gradients_of_cpp_siemens_under_a_session(
    interpreter, session, monkeypatch
):
    """The played gradients under a session are the gradients of the `cpp-siemens` decoding."""
    real_load = load

    def load_with_session(path, chosen):
        return real_load(path, chosen, session=session)

    monkeypatch.setattr(test_played, "load", load_with_session)
    check_the_points_are_the_gradients(SESSION_FILE, interpreter)


def test_the_gradients_of_cpp_siemens_allocate_no_array_of_the_size_of_the_sequence(tmp_path):
    """A call of `gradients_at` of `cpp-siemens` (rotation "apply") with one read, under a session
    that scales the gradients, allocates nothing in proportion to the blocks (3 of 2.1 of
    `docs/reviews/2026-10-13-code-review.md` of pulseq-analysis, C10 of its
    `docs/plans/remaining-review-fixes.md`): in a file of 100 000 blocks, the first of which has a
    rotation, the peak of `tracemalloc` over the second call is below 100 kB, with `rotated`
    False, None and True. A map of 8 bytes for each block is 800 kB."""
    blocks = 100_000
    rows = "".join(f"{i} 50 0 1 0 0 0 0\n" for i in range(2, blocks + 1))
    path = tmp_path / "long.seq"
    # A blank line ends the last section: the reader reads one with none to the end of the file,
    # and then skips [DEFINITIONS] (`definitions.skipped`).
    path.write_text(
        "[VERSION]\nmajor 1\nminor 5\nrevision 1\n\n[DEFINITIONS]\nAdcRasterTime 1e-07\n"
        "BlockDurationRaster 1e-05\nGradientRasterTime 1e-05\nRadiofrequencyRasterTime 1e-06\n\n"
        f"[BLOCKS]\n1 50 0 1 0 0 0 1\n{rows}\n"
        "[EXTENSIONS]\n1 1 1 0\n\nextension ROTATIONS 1\n1 0.92388 0 0 0.382683\n\n"
        "[TRAP]\n1 1000 100 200 100 0\n\n"
    )
    session = Session(gradient_scaling=(2, 1, 1))
    decoding = synth.decode(read_seqfile(path, CppSiemens(rotation="apply")), session)
    assert decoding.block_count == blocks
    turned = 2000 * np.sqrt(0.5)
    for rotated in (False, None, True):
        decoding.gradients_at([0], [250e-6], rotated)
        tracemalloc.start()
        try:
            values = decoding.gradients_at([0], [250e-6], rotated)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        expected = [1000, 0, 0] if rotated is False else [turned, turned, 0]
        np.testing.assert_allclose(values, [expected], rtol=0, atol=1e-2)
        assert peak < 100e3, (rotated, peak)
