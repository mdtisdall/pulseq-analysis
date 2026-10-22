"""Tests of the `cpp-siemens` interpreter (`pulseq_cpp_siemens.interpreter`, the plugin of
pulseq-analysis), which each test names (the default interpreter of pulseq-analysis is `spec`):
its verdict on each fixture against the C++ oracle and its sanitized build, the code of each
rejection, the version gate, the model from the reader's libraries, the `interpreter` argument,
and its decoding through `pulseq_analysis.synth`.

The tests that compare with the oracle skip when it is not on the PATH, as outside the Nix
devShell. The module is not collected without pulseq-analysis (`conftest.py`).
"""

import copy
import dataclasses
import inspect
import pickle
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pulseq_cpp_siemens
import pytest
from pulseq_cpp_siemens.interpreter import CODES, ROTATION, CppSiemens, CppSiemensDecoding
from test_api import RESAMPLED_RF
from test_cpp_oracle import MINIMAL_SEQ, ORACLE, SEQFILES, run_oracle
from test_cpp_oracle_sanitized import SANITIZED, run

from pulseq_analysis import seqfile, synth
from pulseq_analysis.seqfile import NotSupported, SeqFileError, Spec, read_seqfile
from pulseq_analysis.seqfile.conformance import check_shape_limit
from pulseq_analysis.seqfile.interpreters import DEFAULT_MAX_SHAPE_SAMPLES
from pulseq_analysis.seqfile.spec import MAX_LOCATIONS

# The fixtures of this package.
PACKAGE_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The code of the rejection of each fixture that `cpp-siemens` rejects. Every other fixture
# reads, except those of `NOT_SUPPORTED`.
REJECTED = {
    "bad_definitions_raster_invalid.seq": "gradient.raster",
    "bad_definitions_raster_missing.seq": "definitions.raster-missing",
    "bad_extension_required_unknown.seq": "extension.required-unknown",
    "bad_many.seq": "extension.required-unknown",
    "bad_ref_block_rf.seq": "ref.unresolved",
    "bad_ref_extension_cycle.seq": "ub.extension-cycle",
    "bad_ref_shape.seq": "ub.shape-missing",
    "bad_ref_time_shape.seq": "ub.shape-missing",
    "bad_shape_empty.seq": "ub.shape-empty",
    "bad_shape_event_length.seq": "ub.rf-shape-lengths",
    "bad_shape_rf_time_end.seq": "ub.rf-time-overrun",
    "bad_syntax_integer.seq": "syntax.row",
    "bad_syntax_line_after_comment.seq": "syntax.comment-row",
    "bad_syntax_shape.seq": "syntax.shape",
    "bad_syntax_shape_end.seq": "syntax.shape",
    "bad_syntax_shape_no_blank_line.seq": "ub.shape-missing",
    "bad_version_missing.seq": "version.missing",
    "oracle/koma_v1.5_unknown_ext.seq": "section.extensions-last",
    "undefined/rf_time_id_minus_1.seq": "ub.rf-time-id-minus-1",
    "undefined/shape_decompress_longer.seq": "ub.shape-decompression",
    "undefined/version_last.seq": "ub.shape-missing",
    "valid_arbitrary_gradient_4us_raster.seq": "gradient.raster",
    "valid_arbitrary_gradient_5us_raster.seq": "gradient.raster",
    "valid_comment_in_shape.seq": "syntax.comment-row",
    "valid_last_section_no_blank.seq": "definitions.skipped",
    "valid_rf_time_shapes.seq": "ub.rf-time-overrun",
}

# The fixtures outside the versions that the package reads (Q1): `NotSupported`.
NOT_SUPPORTED = {"bad_version_unsupported_1_3.seq", "bad_version_unsupported_1_6.seq"}

FIXTURES = sorted(path.relative_to(SEQFILES).as_posix() for path in SEQFILES.rglob("*.seq"))

needs_oracles = pytest.mark.skipif(
    ORACLE is None or SANITIZED is None,
    reason="pulseq-cpp-oracle and pulseq-cpp-oracle-sanitized are not on the PATH",
)


def verdict(path, interpreter="cpp-siemens"):
    """ "read", "not-supported", or the codes of the `SeqFileError`, joined by ","."""
    try:
        read_seqfile(path, interpreter)
    except NotSupported:
        return "not-supported"
    except SeqFileError as error:
        assert error.interpreter == "cpp-siemens"
        return ",".join(sorted(error.codes))
    return "read"


def oracle_verdict(path):
    """The verdict that `cpp-siemens` must give by the two oracles: "read" when the oracle
    accepts the file, "ub" when the sanitized build finds undefined behaviour or does not end,
    and "reject" when the oracle rejects it otherwise."""
    sanitized, messages = run(SANITIZED, path)
    if sanitized in ("undefined", "no end"):
        return "ub", messages
    plain, messages = run_oracle(path)
    assert plain in ("accept", "reject"), messages
    return ("read" if plain == "accept" else "reject"), messages


@needs_oracles
@pytest.mark.parametrize("name", FIXTURES)
def test_cpp_siemens_gives_the_verdict_of_the_oracle_on_each_fixture(name):
    """Each fixture of `tests/seqfiles`: cpp-siemens reads what the oracle accepts, rejects with
    a `ub.*` code what the sanitized oracle finds undefined or never ends, and rejects with
    another code what the oracle rejects. A version outside 1.4.0-1.5.x is not supported (Q1),
    whatever the oracle does."""
    path = SEQFILES / name
    got = verdict(path)
    if name in NOT_SUPPORTED:
        assert got == "not-supported"
        return
    expected, messages = oracle_verdict(path)
    if expected == "read":
        assert got == "read", messages
    elif expected == "ub":
        assert got.startswith("ub."), (got, messages)
    else:
        assert got != "read" and not got.startswith("ub."), (got, messages)


@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_has_its_rejection_code(name):
    expected = "not-supported" if name in NOT_SUPPORTED else REJECTED.get(name, "read")
    assert verdict(SEQFILES / name) == expected


@needs_oracles
@pytest.mark.parametrize(
    ("name", "code", "entry"),
    [
        ("gradient_one_point.seq", "ub.gradient-one-point", "D5.10"),
        ("gradient_shape_0.seq", "ub.gradient-shape-0", "D5.2"),
        ("shape_decompress_count_missing.seq", "ub.shape-decompression", "D5.5"),
    ],
)
def test_the_fixtures_of_pulseq_cpp_siemens_are_rejected_with_their_code(name, code, entry):
    path = PACKAGE_FIXTURES / name
    assert verdict(path) == code
    assert CODES[code][0] == entry


def edit(text, old, new):
    assert old in text, old
    return text.replace(old, new, 1)


MINIMAL_15_1 = edit(MINIMAL_SEQ, "revision 0", "revision 1")
RF_FILE = edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 11 1 0 0 0 0 0") + (
    "\n[RF]\n1 1000 1 2 0 0 10 0 0 0 0 u\n\n[SHAPES]\nshape_id 1\nnum_samples 6\n"
    + "0.5\n" * 6
    + "\nshape_id 2\nnum_samples 6\n"
    + "0\n" * 6
    + "\n"
)
ROTATION_SECTION = (
    "[EXTENSIONS]\n1 1 1 0\n\nextension ROTATIONS 1\n1 {q}\n\n[BLOCKS]\n1 100 0 0 0 0 0 1\n"
)

# For each code of a rejection by `load` or `decodeBlock`, a file that the reader rejects for
# that reason: an edit of a small valid file.
CODE_FILES = {
    "version.invalid": edit(MINIMAL_SEQ, "minor 5", "minor x"),
    "version.missing": edit(MINIMAL_SEQ, "[VERSION]\nmajor 1\nminor 5\nrevision 0\n\n", ""),
    "definitions.raster-missing": edit(MINIMAL_SEQ, "AdcRasterTime 1e-07\n", ""),
    "definitions.raster-invalid": edit(MINIMAL_SEQ, "AdcRasterTime 1e-07", "AdcRasterTime nan"),
    # D2.2 in `spec`: the last section has no blank line after it, so the reader's stream fails at
    # the end of the file when it reads it, and it then skips [DEFINITIONS], which it reads later.
    "definitions.skipped": MINIMAL_SEQ + "\n[TRAP]\n1 1000 10 10 10 0",
    "extension.required-unknown": edit(
        MINIMAL_15_1,
        "RadiofrequencyRasterTime 1e-06",
        "RadiofrequencyRasterTime 1e-06\nRequiredExtensions FOO",
    ),
    "section.extensions-last": MINIMAL_SEQ + "\n[EXTENSIONS]\n",
    "blocks.missing": MINIMAL_SEQ.split("[BLOCKS]")[0],
    "ref.unresolved": edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100 0 0 0 0 1 0"),
    # A fraction in an integer column of [BLOCKS].
    "syntax.row": edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100.5 0 0 0 0 0 0"),
    "syntax.comment-row": edit(RF_FILE, "[RF]\n", "[RF]\n# a note\n"),
    "syntax.shape": edit(RF_FILE, "num_samples 6\n", "num_samples six\n"),
    "rotation.norm": edit(
        MINIMAL_SEQ, "[BLOCKS]\n1 100 0 0 0 0 0 0\n", ROTATION_SECTION.format(q="2 0 0 0")
    ),
    "gradient.raster": edit(
        MINIMAL_SEQ, "GradientRasterTime 1e-05", "GradientRasterTime 4e-06"
    ).replace("1 100 0 0 0 0 0 0", "1 100 0 1 0 0 0 0")
    + "\n[GRADIENTS]\n1 1000 0 0 1 0 0\n\n[SHAPES]\nshape_id 1\nnum_samples 3\n0\n1\n0\n\n",
    "shape.decompression": edit(
        RF_FILE, "num_samples 6\n" + "0.5\n" * 6, "num_samples 6\n0.5\n0.5\n1.5\n0\n"
    ),
    "shape.ext-trap-lengths": edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100 0 1 0 0 0 0")
    + "\n[GRADIENTS]\n1 1000 0 0 1 2 0\n\n[SHAPES]\nshape_id 1\nnum_samples 3\n0\n1\n0\n\n"
    "shape_id 2\nnum_samples 2\n0\n5\n\n",
    "cpp.exception": edit(RF_FILE, "1 1000 1 2 0 0 10", "1 1000 1 2 3 0 10")
    + "shape_id 3\nnum_samples 6\n0\n1\n2\n3\n4\n-9\n\n",
}


@pytest.mark.parametrize("code", sorted(CODE_FILES))
def test_each_code_of_a_rejection_has_a_file_that_gives_it(tmp_path, code):
    path = tmp_path / "file.seq"
    path.write_text(CODE_FILES[code])
    with pytest.raises(SeqFileError) as caught:
        read_seqfile(path, "cpp-siemens")
    assert caught.value.codes == {code}, str(caught.value)
    (reason,) = caught.value.violations
    assert reason.message
    if ORACLE is not None:
        plain, messages = run_oracle(path)
        assert plain == "reject", messages


def test_every_code_is_given_by_a_file_or_is_the_fallback_or_a_case_of_undefined_behaviour():
    reached = set(CODE_FILES) | set(REJECTED.values())
    untested = {c for c in CODES if c not in reached and not c.startswith("ub.")}
    assert untested == {"cpp.rejected"}
    assert {c for c in CODES if c.startswith("ub.")} == set(pulseq_cpp_siemens.CODES)


def test_a_rejection_quotes_the_line_of_the_row_that_does_not_decode(tmp_path):
    path = tmp_path / "comment.seq"
    path.write_text(CODE_FILES["syntax.comment-row"])
    with pytest.raises(SeqFileError) as caught:
        read_seqfile(path, "cpp-siemens")
    (reason,) = caught.value.violations
    assert reason.section == "RF"
    assert path.read_text().split("\n")[reason.line - 1] == "# a note"
    assert reason.message.startswith("*** ERROR: failed to decode RF event")


def gradient_events(error):
    """The (code, gradient event) of each reason of a rejection for undefined behaviour, by the
    event that its message names (None where it names none)."""
    events = [re.search(r"\bgradient event (\d+)\b", v.message) for v in error.violations]
    return [
        (v.rule, int(event.group(1)) if event else None)
        for v, event in zip(error.violations, events, strict=True)
    ]


def test_every_case_of_undefined_behaviour_is_a_violation(tmp_path):
    """valid_no_signature.seq with two cases in two blocks (play order from 0): gradient event 2
    of block 1 uses a shape of 0 samples (D5.6), and gradient event 4, of blocks 2 and 3, a shape
    that does not exist (D5.1). The error has a reason for each event, once, with the event that
    it names."""
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    text = edit(text, "\n2 500000 0 0 3 0 100\n", "\n2 500000 0 0 10 0 100\n")
    text = edit(text, "\n4 500000 500000 0 4 0 0\n", "\n4 500000 500000 0 99 0 0\n")
    text = edit(text, "\n3  50  0  0  0  3  0  0\n", "\n3  50  0  0  0  4  0  0\n")
    path = tmp_path / "two_cases.seq"
    path.write_text(text + "shape_id 10\nnum_samples 0\n\n")
    with pytest.raises(SeqFileError) as caught:
        read_seqfile(path, "cpp-siemens")
    assert sorted(gradient_events(caught.value)) == [
        ("ub.shape-empty", 2),
        ("ub.shape-missing", 4),
    ], str(caught.value)
    assert not caught.value.omitted


def test_the_cases_of_one_code_are_capped_at_max_locations(tmp_path):
    """MAX_LOCATIONS + 3 blocks, each with a gradient event of its own that uses a shape that does
    not exist: the error has the first MAX_LOCATIONS, in play order, and counts the other 3 in
    `omitted`, as `spec` does for a rule."""
    count = MAX_LOCATIONS + 3
    blocks = "".join(f"{i} 100 0 {i} 0 0 0 0\n" for i in range(1, count + 1))
    gradients = "".join(f"{i} 1000 0 0 {100 + i} 0 0\n" for i in range(1, count + 1))
    text = edit(
        MINIMAL_SEQ,
        "[BLOCKS]\n1 100 0 0 0 0 0 0\n",
        f"[BLOCKS]\n{blocks}\n[GRADIENTS]\n{gradients}\n"
        "[SHAPES]\nshape_id 1\nnum_samples 3\n0\n1\n0\n\n",
    )
    path = tmp_path / "many_cases.seq"
    path.write_text(text)
    with pytest.raises(SeqFileError) as caught:
        read_seqfile(path, "cpp-siemens")
    assert sorted(gradient_events(caught.value)) == [
        ("ub.shape-missing", i) for i in range(1, MAX_LOCATIONS + 1)
    ], str(caught.value)
    assert dict(caught.value.omitted) == {"ub.shape-missing": 3}


def test_the_dwell_with_a_decimal_point_is_a_row_that_does_not_decode(tmp_path):
    """The reader reads the dwell as an integer, so `2500.0` leaves the row short."""
    text = edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100 0 0 0 0 1 0") + (
        "\n[ADC]\n1 8 2500.0 0 0 0 0 0 0\n\n"
    )
    path = tmp_path / "dwell.seq"
    path.write_text(text)
    with pytest.raises(SeqFileError) as caught:
        read_seqfile(path, "cpp-siemens")
    assert caught.value.codes == {"syntax.row"}
    assert caught.value.violations[0].section == "ADC"
    path.write_text(text.replace("2500.0", "2500"))
    assert read_seqfile(path, "cpp-siemens").adc["dwell"].tolist() == [2.5e-6]


@pytest.mark.parametrize(
    ("version", "rows"),
    [
        ("1.3.1", "major 1\nminor 3\nrevision 1"),
        ("1.6.0", "major 1\nminor 6\nrevision 0"),
        ("2.0.0", "major 2\nminor 0\nrevision 0"),
        # The reader takes the last row of a key; the "as written" reading the first.
        ("1.6.0", "major 1\nminor 5\nminor 6\nrevision 0"),
    ],
)
def test_a_version_outside_1_4_to_1_5_is_not_supported_before_the_reader_runs(
    tmp_path, version, rows
):
    """Q1. The file also has a cycle in an extension list, on which the reader of a version
    before 1.4.0 would not end inside `load`: the gate runs before it."""
    text = MINIMAL_SEQ.replace("major 1\nminor 5\nrevision 0", rows).replace(
        "[BLOCKS]\n1 100 0 0 0 0 0 0\n",
        "[EXTENSIONS]\n1 1 1 1\n\nextension LABELSET 1\n1 0 LIN\n\n[BLOCKS]\n1 100 0 0 0 0 0 1\n",
    )
    path = tmp_path / "version.seq"
    path.write_text(text)
    with pytest.raises(NotSupported) as caught:
        read_seqfile(path, "cpp-siemens")
    assert isinstance(caught.value, NotImplementedError)
    assert version in str(caught.value) or "1.6" in str(caught.value)


def test_a_binary_file_and_a_folder_are_not_supported(tmp_path):
    path = tmp_path / "binary.seq"
    path.write_bytes(b"\x01pulseq\x02" + b"\0" * 32)
    with pytest.raises(NotSupported):
        read_seqfile(path, "cpp-siemens")
    with pytest.raises(NotSupported):
        read_seqfile(tmp_path, "cpp-siemens")


@pytest.mark.parametrize("case", ["folder", "binary", "version"])
def test_both_interpreters_give_one_message_for_a_file_outside_the_scope(tmp_path, case):
    """`read_seqfile` checks the scope (a folder, a binary Pulseq file, a version outside 1.4.0
    to 1.5.x) before it chooses the interpreter (the user, 2026-10-14), so `spec` and
    `cpp-siemens` raise `NotSupported` with one message, which names the file."""
    if case == "folder":
        path = tmp_path
    elif case == "binary":
        path = tmp_path / "binary.seq"
        path.write_bytes(b"\x01pulseq\x02" + bytes(range(256)))
    else:
        path = tmp_path / "version.seq"
        path.write_text(MINIMAL_SEQ.replace("minor 5", "minor 3"))
    messages = []
    for interpreter in ("spec", "cpp-siemens"):
        with pytest.raises(NotSupported) as caught:
            read_seqfile(path, interpreter)
        messages.append(str(caught.value))
    assert messages[0] == messages[1]
    assert str(path) in messages[0]


def test_the_model_is_the_readers_libraries_in_the_units_of_the_model():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens")
    lib = data.reading.libraries
    assert data.version == lib.version_parts == (1, 5, 1)
    assert data.rasters.gradient == lib.gradient_raster_us / 1e6
    assert data.blocks["id"].tolist() == list(range(1, len(lib.blocks) + 1))
    assert data.blocks["duration_ticks"].tolist() == lib.blocks[:, 0].tolist()
    assert data.blocks[["rf", "gx", "gy", "gz", "adc", "ext"]].tolist() == [
        tuple(row) for row in lib.blocks[:, 1:].tolist()
    ]
    (rf,) = data.rf
    assert rf["delay"] == lib.rf[1]["delay_us"] / 1e6 and rf["use"] == "e"
    assert rf["center"] == lib.rf[1]["center_us"] / 1e6
    assert set(data.trap["id"]) == {i for i, g in lib.grad.items() if g["wave_shape"] == 0}
    assert set(data.grad["id"]) == {i for i, g in lib.grad.items() if g["wave_shape"] != 0}
    assert data.adc["dwell"].tolist() == [a["dwell_ns"] / 1e9 for a in lib.adc.values()]
    for shape_id, shape in data.shapes.items():
        assert shape.packed.tolist() == lib.shapes[shape_id].samples.tolist()
    assert data.signature.matches is True and data.signature.type == "md5"
    assert data.required_extensions == ("ROTATIONS",)
    # The reader keeps no trace of an extension that it does not know (D2.17 in `spec`).
    assert data.skipped_extensions == ("UNKNOWN",)
    assert "UNKNOWN" not in data.extensions.type_ids
    # float32 values of the reader (P6): the RF shim phase pi/2 as written with 4 decimals.
    assert data.extensions.rf_shims[1][1, 1] == float(np.float32(1.5708))


def test_a_1_4_rf_event_has_no_center_and_the_use_u():
    (rf,) = read_seqfile(SEQFILES / "valid_1_4_0.seq", "cpp-siemens").rf
    assert np.isnan(rf["center"]) and rf["use"] == "u"


def test_the_rotations_are_the_readers_normalized_quaternions(tmp_path):
    path = tmp_path / "rotation.seq"
    path.write_text(
        edit(
            MINIMAL_15_1, "[BLOCKS]\n1 100 0 0 0 0 0 0\n", ROTATION_SECTION.format(q="1.0005 0 0 0")
        )
    )
    (row,) = read_seqfile(path, "cpp-siemens").extensions.rotations
    assert row["q0"] == 1.0
    # `spec` divides the quaternion by its norm too, from 1.5.1 (D2.18).
    assert read_seqfile(path, "spec").extensions.rotations["q0"].tolist() == [1.0]


def test_the_rotation_ids_are_int64():
    rotations = read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens").extensions.rotations
    assert rotations.dtype["id"] == np.int64
    assert rotations["id"].tolist() == [1]


def test_the_interpreter_is_a_name_or_an_object_and_the_result_records_it():
    path = SEQFILES / "valid_1_5_1.seq"
    assert read_seqfile(path).interpreter == Spec()  # the default
    assert read_seqfile(path, "cpp-siemens").interpreter == CppSiemens(oversampling="center")
    edge = read_seqfile(path, CppSiemens(oversampling="edge"))
    assert edge.interpreter.oversampling == "edge" and edge.reading.oversampling == "edge"
    assert str(edge.interpreter) == "cpp-siemens(oversampling='edge')"
    spec = read_seqfile(path, "spec")
    assert spec.interpreter == Spec() and spec.reading is None
    with pytest.raises(ValueError, match="no interpreter"):
        read_seqfile(path, "matlab")
    with pytest.raises(ValueError, match="oversampling"):
        CppSiemens(oversampling="middle")
    with pytest.raises(TypeError):
        read_seqfile(path, 3)


def test_the_oversampling_setting_changes_the_decoding_of_an_oversampled_gradient():
    path = SEQFILES / "valid_1_5_1.seq"
    samples = {}
    for mode in ("center", "edge", "preserve"):
        decoding = synth.decode(read_seqfile(path, CppSiemens(oversampling=mode)))
        for block in decoding.blocks():
            for grad in block["grad"]:
                if grad is not None and grad.get("oversampled"):
                    samples[mode] = grad["samples"]
    n = len(samples["preserve"])
    assert len(samples["center"]) == (n + 1) // 2 and len(samples["edge"]) == (n - 1) // 2
    assert samples["center"].tolist() == samples["preserve"][::2].tolist()
    assert samples["edge"].tolist() == samples["preserve"][1::2].tolist()


def test_a_cpp_siemens_model_compares_and_survives_pickle_and_deepcopy():
    path = SEQFILES / "valid_1_5_1.seq"
    data = read_seqfile(path, "cpp-siemens")
    assert data == read_seqfile(path, "cpp-siemens")  # the reading is not compared
    assert data != read_seqfile(path, CppSiemens(oversampling="edge"))
    for clone in (pickle.loads(pickle.dumps(data)), copy.deepcopy(data)):
        assert clone == data
        assert clone.reading.libraries.version == data.reading.libraries.version
        assert synth.decode(clone).gradients_at([1], [150e-6]).tolist() == (
            synth.decode(data).gradients_at([1], [150e-6]).tolist()
        )
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.reading = None


def test_synth_decode_gives_the_readers_decoding_or_the_spec_events():
    path = SEQFILES / "valid_1_5_1.seq"
    data = read_seqfile(path, "cpp-siemens")
    decoding = synth.decode(data)
    assert isinstance(decoding, CppSiemensDecoding)
    assert decoding.interpreter == data.interpreter
    assert decoding.block_count == len(data.blocks)
    assert [b["index"] for b in decoding.blocks()] == list(range(len(data.blocks)))
    times = np.array([0.0, 100e-6, 150e-6, 300e-6])
    np.testing.assert_array_equal(
        decoding.gradients_at(np.ones(4, int), times),
        data.reading.gradients_at(np.ones(4, int), times * 1e6),
    )
    spec_data = read_seqfile(path, "spec")
    assert isinstance(synth.decode(spec_data), synth.SpecDecoding)
    assert set(synth.events.decode_rf(spec_data)) == {1}
    with pytest.raises(TypeError, match="synth.decode"):
        synth.events.decode_rf(data)


def test_the_decoding_takes_seconds_and_the_reader_microseconds():
    """`CppSiemensDecoding.gradients_at` takes block-relative times in s, the argument `time_s` of
    the protocol `synth.Decoding` of version 1 (in s, as the rest of the API of pulseq-analysis: the
    user, 2026-10-14), and the reader's own `Sequence.gradients_at` takes us. At the times of the
    trapezoid of block 2 of valid_1_5_1.seq (1e6 Hz/m, delay 100 us, rise 100 us, flat 200 us, fall
    100 us, block 500 us) on gx, the decoding gives the reader's values at the same times in us, bit
    for bit: without a session, and with one that doubles x (the two paths of the method). The old
    keyword `time_us` raises `TypeError`."""
    parameters = ["self", "block_index", "time_s", "rotated"]
    assert list(inspect.signature(CppSiemensDecoding.gradients_at).parameters) == parameters
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens")
    seconds = np.array([-1e-6, 50e-6, 150e-6, 250e-6, 450e-6, 500e-6, 501e-6])
    blocks = np.ones(seconds.size, int)
    reader = data.reading.gradients_at(blocks, seconds * 1e6)
    np.testing.assert_allclose(reader[:, 0], [0, 0, 0.5e6, 1e6, 0.5e6, 0, 0], rtol=0, atol=1e-6)
    doubled = synth.Session(gradient_scaling=(2, 1, 1))
    for session, scale in ((synth.Session(), 1.0), (doubled, 2.0)):
        decoding = synth.decode(data, session)
        values = decoding.gradients_at(blocks, time_s=seconds)
        np.testing.assert_array_equal(values, reader * [scale, 1.0, 1.0])
        with pytest.raises(TypeError, match="time_us"):
            decoding.gradients_at(blocks, time_us=seconds * 1e6)


RADIAL = SEQFILES / "oracle" / "koma_v1.5_rotation_radial_tiny.seq"


def test_the_rotation_setting_is_one_of_two_and_a_setting_that_an_interpreter_lacks_is_typeerror():
    assert CppSiemens().rotation == "reader" and ROTATION == ("reader", "apply")
    assert str(CppSiemens(rotation="apply")) == "cpp-siemens(rotation='apply')"
    both = CppSiemens(oversampling="edge", rotation="apply")
    assert str(both) == "cpp-siemens(oversampling='edge', rotation='apply')"
    assert read_seqfile(RADIAL, both).interpreter == both
    with pytest.raises(ValueError, match="rotation"):
        CppSiemens(rotation="scanner")
    # Rule 8 of P20: a setting that the interpreter does not have.
    with pytest.raises(TypeError):
        Spec(rotation="apply")
    with pytest.raises(TypeError):
        CppSiemens(rotate="apply")


def test_cpp_siemens_follows_the_convention_of_max_shape_samples():
    """`CppSiemens` passes `check_shape_limit` of pulseq-analysis (the setting of every
    interpreter, the user, 2026-10-18), and the default of `max_shape_samples` of the reader's
    `load`, which does not import pulseq-analysis, is `DEFAULT_MAX_SHAPE_SAMPLES`."""
    check_shape_limit(CppSiemens)
    load = inspect.signature(pulseq_cpp_siemens.load)
    assert load.parameters["max_shape_samples"].default == DEFAULT_MAX_SHAPE_SAMPLES


def test_a_shape_over_max_shape_samples_is_not_supported_with_the_path_of_the_file():
    """`read_seqfile` of `valid_no_signature.seq` under `CppSiemens(max_shape_samples=99)` raises
    `NotSupported` whose message starts with the path of the file and the shape, with no name of
    the bytes that `read_cpp_siemens` gives the reader (`<bytes>`)."""
    path = SEQFILES / "valid_no_signature.seq"
    with pytest.raises(NotSupported) as caught:
        read_seqfile(path, CppSiemens(max_shape_samples=99))
    message = str(caught.value)
    assert message.startswith(f"{path}: shape 1 declares 100 samples"), message
    assert "<bytes>" not in message


def test_an_rf_pulse_over_max_shape_samples_is_not_supported_with_the_path_of_the_file(tmp_path):
    """`read_seqfile` of `RESAMPLED_RF` of `test_api` (an RF pulse that `decodeBlock` resamples
    into 2000 cells, from shapes of two samples) under `CppSiemens(max_shape_samples=1000)` raises
    `NotSupported` whose message starts with the path of the file and the RF event, with no name
    of the bytes that `read_cpp_siemens` gives the reader (`<bytes>`)."""
    path = tmp_path / "resampled_rf.seq"
    path.write_bytes(RESAMPLED_RF)
    with pytest.raises(NotSupported) as caught:
        read_seqfile(path, CppSiemens(max_shape_samples=1000))
    message = str(caught.value)
    assert message.startswith(f"{path}: RF event 1 "), message
    assert "<bytes>" not in message


def test_each_block_s_rotation_is_the_quaternion_that_the_reader_attaches():
    for path in (RADIAL, SEQFILES / "valid_1_5_1.seq"):
        for setting in ROTATION:
            data = read_seqfile(path, CppSiemens(rotation=setting))
            decoding = synth.decode(data)
            indices, quaternions = decoding.rotations()
            attached = {
                block["index"]: block["rotation"]
                for block in decoding.blocks()
                if block["rotation"] is not None
            }
            assert indices.tolist() == sorted(attached)
            assert [tuple(q) for q in quaternions] == [attached[i] for i in sorted(attached)]
            ids = {tuple(q) for q in data.extensions.rotations[["q0", "qx", "qy", "qz"]].tolist()}
            assert {tuple(q) for q in quaternions} <= ids


def test_rotation_apply_rotates_the_gradients_of_each_block_that_has_a_rotation():
    block_index = np.repeat(np.arange(5), 4)
    time_s = np.tile([50e-6, 150e-6, 200e-6, 350e-6], 5)
    reader = synth.decode(read_seqfile(RADIAL, "cpp-siemens"))
    applied = synth.decode(read_seqfile(RADIAL, CppSiemens(rotation="apply")))
    logical = reader.gradients_at(block_index, time_s)
    assert np.array_equal(logical, applied.gradients_at(block_index, time_s, rotated=False))
    rotated = applied.gradients_at(block_index, time_s)
    assert np.array_equal(rotated, reader.gradients_at(block_index, time_s, rotated=True))
    assert np.array_equal(logical[:, 1:], np.zeros((20, 2)))  # the file's gradients are on x
    # Blocks 1 to 5 are rotated by 0, 45, 90, 45 and 0 degrees about z.
    angle = np.radians(np.repeat([0, 45, 90, 45, 0], 4))
    expected = logical[:, :1] * np.stack([np.cos(angle), np.sin(angle), 0 * angle], axis=1)
    np.testing.assert_allclose(rotated, expected, rtol=0, atol=1e-3)


def test_the_rotation_record_and_the_warning_for_rotations_left_unapplied(tmp_path):
    reader = synth.decode(read_seqfile(RADIAL, "cpp-siemens")).rotation_record
    assert reader == synth.RotationRecord("reader", blocks=5, not_identity=3, rotated=0)
    assert reader.unapplied == 3
    assert str(reader) == "rotation: reader, 5 block(s) with a rotation (3 not the identity), " + (
        "not applied"
    )
    warning = reader.warning()
    assert isinstance(warning, synth.ScannerSettingWarning)
    assert "3 block(s) play a rotation" in str(warning) and "rotation='apply'" in str(warning)
    applied = synth.decode(read_seqfile(RADIAL, CppSiemens(rotation="apply"))).rotation_record
    assert applied == synth.RotationRecord("apply", blocks=5, not_identity=3, rotated=5)
    assert applied.warning() is None and str(applied) == "rotation: apply, 5 block(s) rotated"
    # Rule 8 of P20: "apply" on a file with no rotation is valid, and rotates 0 blocks.
    for name in ("valid_1_5_0.seq", "valid_1_5_1_rotation_not_played.seq"):
        for setting in ROTATION:
            data = read_seqfile(SEQFILES / name, CppSiemens(rotation=setting))
            record = synth.decode(data).rotation_record
            assert record == synth.RotationRecord(setting, 0, 0, 0)
            assert record.warning() is None
    assert str(synth.RotationRecord("apply", 0, 0, 0)) == "rotation: apply, 0 block(s) rotated"
    # Rotations that are all the identity play no rotation: no warning.
    identity = (
        RADIAL.read_bytes()
        .replace(b"\n2  0.92388 0 0 0.382683\n", b"\n2  1 0 0 0\n")
        .replace(b"\n3  0.707107 0 0 0.707107\n", b"\n3  1 0 0 0\n")
    )
    assert identity.count(b"  1 0 0 0\n") == 3
    path = tmp_path / "identity.seq"
    path.write_bytes(identity)
    record = synth.decode(read_seqfile(path, "cpp-siemens")).rotation_record
    assert record == synth.RotationRecord("reader", blocks=5, not_identity=0, rotated=0)
    assert record.warning() is None


def test_the_decoding_emits_no_warning_for_rotations(recwarn):
    decoding = synth.decode(read_seqfile(RADIAL, "cpp-siemens"))
    decoding.gradients_at([1], [200e-6])
    assert decoding.rotation_record.unapplied == 3
    assert not [w for w in recwarn if issubclass(w.category, synth.ScannerSettingWarning)]


# The fixtures with a ROTATIONS section that both interpreters may read.
ROTATION_FIXTURES = [
    path
    for path in sorted(SEQFILES.glob("valid_*.seq")) + sorted((SEQFILES / "oracle").glob("*.seq"))
    if b"extension ROTATIONS" in path.read_bytes()
]


@pytest.mark.parametrize("path", ROTATION_FIXTURES, ids=lambda p: p.name)
def test_spec_rotates_the_gradients_as_cpp_siemens_with_rotation_apply(path):
    """On each fixture with ROTATIONS that both interpreters read, from 1.5.1, `spec` gives each
    block the rotation that the reader attaches, with the same normalized quaternion, and its
    rotated gradients (`decoding.rotate`) are those of `CppSiemens(rotation="apply")` (the
    reader's `rotate_vec3_by_quat`) at 7 times inside each block, to float32 precision (P6). In
    a file older than 1.5.1 `cpp-siemens` rotates (it follows the reader) and `spec` does not:
    its gradients are the reader's unrotated ones."""
    try:
        spec_data = read_seqfile(path, "spec")
        cpp = synth.decode(read_seqfile(path, CppSiemens(rotation="apply")))
    except SeqFileError as error:
        pytest.skip(f"an interpreter rejects the file ({', '.join(sorted(error.codes))})")
    spec = synth.decode(spec_data)
    block_index = np.repeat(np.arange(spec.block_count), 7)
    fraction = np.tile(np.linspace(0.05, 0.95, 7), spec.block_count)
    time_s = fraction * spec.block_durations[block_index]
    expected = cpp.gradients_at(block_index, time_s)
    tolerance = 1e-6 * max(np.abs(expected).max(), 1.0)
    if spec_data.version < (1, 5, 1):
        assert spec.rotations()[0].size == 0 and cpp.rotation_record.not_identity
        expected = cpp.gradients_at(block_index, time_s, rotated=False)
    else:
        spec_indices, spec_quaternions = spec.rotations()
        cpp_indices, cpp_quaternions = cpp.rotations()
        assert spec_indices.tolist() == cpp_indices.tolist()
        np.testing.assert_allclose(spec_quaternions, cpp_quaternions, rtol=0, atol=1e-12)
        assert spec.rotation_record == cpp.rotation_record
    np.testing.assert_allclose(
        spec.gradients_at(block_index, time_s), expected, rtol=0, atol=tolerance
    )


def test_the_entry_point_gives_cpp_siemens_to_pulseq_analysis():
    """pulseq-analysis finds `cpp-siemens` through the entry-point group
    `pulseq_analysis.interpreters` (P21), and a name gives the default settings."""
    assert "cpp-siemens" in seqfile.interpreter_names()
    assert seqfile.interpreter("cpp-siemens") == CppSiemens()
    assert isinstance(CppSiemens(), seqfile.Plugin)
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens")
    assert isinstance(synth.decode(data), synth.Decoding)


def test_the_reader_imports_without_pulseq_analysis():
    """`import pulseq_cpp_siemens` imports the reader only: pulseq-analysis is imported by the
    module `interpreter`, and only that module needs it."""
    code = (
        "import sys, pulseq_cpp_siemens; "
        "assert not [m for m in sys.modules if m.startswith('pulseq_analysis')]"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# Files with trapezoids, extended trapezoids (a time shape), arbitrary gradients and rotations.
GRADIENT_POINT_FILES = [
    SEQFILES / "oracle" / name
    for name in (
        "koma_v1.4_gr-trapezoidal.seq",
        "koma_v1.4_gr-time-shaped.seq",
        "koma_v1.4_gr-uniformly-shaped.seq",
        "koma_v1.5_rotation_radial_tiny.seq",
        "koma_v1.5_spiral.seq",
    )
]


def test_the_gradient_points_are_the_values_of_gradients_at():
    """`gradient_points` of each gradient event, at the first block that plays it, gives the
    values of `gradients_at` (not rotated) at each of its points inside the block."""
    for path in GRADIENT_POINT_FILES:
        data = read_seqfile(path, "cpp-siemens")
        decoding = synth.decode(data)
        checked = 0
        for axis, column in enumerate(("gx", "gy", "gz")):
            ids = data.blocks[column]
            for key in np.unique(ids[ids != 0]).tolist():
                block = int(np.flatnonzero(ids == key)[0])
                delay, offsets, values = decoding.gradient_points(key, block, axis)
                times_s = delay + offsets[1:-1]
                inside = times_s < data.block_durations_s[block]
                at = decoding.gradients_at(
                    np.full(int(inside.sum()), block), times_s[inside], rotated=False
                )[:, axis]
                np.testing.assert_allclose(at, values[1:-1][inside], rtol=1e-6, atol=1e-3)
                checked += 1
        assert checked
