"""Tests of the `cpp-siemens` interpreter (`seqfile.cpp_siemens`), which each test names (the
default interpreter is `strict`): its verdict on each fixture
against the C++ oracle and its sanitized build, the code of each rejection, the version gate, the
model from the reader's libraries, the `interpreter` argument, and its decoding in `synth`.

The tests that compare with the oracle skip when it is not on the PATH, as outside the Nix
devShell. The module skips without pulseq-cpp-siemens (the extra `cpp-siemens`).
"""

import copy
import dataclasses
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from test_cpp_oracle import MINIMAL_SEQ, ORACLE, SEQFILES, run_oracle
from test_cpp_oracle_sanitized import SANITIZED, run

pytest.importorskip("pulseq_cpp_siemens")

from pulseq_analysis import seqfile, synth
from pulseq_analysis.seqfile import (
    CppSiemens,
    NotSupported,
    SeqFileError,
    Strict,
    read_seqfile,
)
from pulseq_analysis.seqfile.cpp_siemens import CODES

PACKAGE_FIXTURES = (
    Path(__file__).resolve().parents[1] / "packages" / "pulseq-cpp-siemens" / "tests" / "fixtures"
)

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
    "bad_syntax_shape_no_blank_line.seq": "ub.shape-missing",
    "bad_version_missing.seq": "version.missing",
    "oracle/koma_v1.5_unknown_ext.seq": "section.extensions-last",
    "undefined/rf_time_id_minus_1.seq": "ub.rf-time-id-minus-1",
    "undefined/shape_decompress_longer.seq": "ub.shape-decompression",
    "undefined/version_last.seq": "ub.shape-missing",
    "valid_arbitrary_gradient_4us_raster.seq": "gradient.raster",
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
    ("name", "code"),
    [
        ("gradient_one_point.seq", "ub.gradient-one-point"),
        ("gradient_shape_0.seq", "ub.gradient-shape-0"),
        ("shape_decompress_count_missing.seq", "ub.shape-decompression"),
    ],
)
def test_the_fixtures_of_pulseq_cpp_siemens_are_rejected_with_their_code(name, code):
    path = PACKAGE_FIXTURES / name
    assert verdict(path) == code
    assert seqfile.cpp_siemens.CODES[code][0] in ("D29", "—")


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
ROTATION = "[EXTENSIONS]\n1 1 1 0\n\nextension ROTATIONS 1\n1 {q}\n\n[BLOCKS]\n1 100 0 0 0 0 0 1\n"

# For each code of a rejection by `load` or `decodeBlock`, a file that the reader rejects for
# that reason: an edit of a small valid file.
CODE_FILES = {
    "version.invalid": edit(MINIMAL_SEQ, "minor 5", "minor x"),
    "version.missing": edit(MINIMAL_SEQ, "[VERSION]\nmajor 1\nminor 5\nrevision 0\n\n", ""),
    "definitions.raster-missing": edit(MINIMAL_SEQ, "AdcRasterTime 1e-07\n", ""),
    "definitions.raster-invalid": edit(MINIMAL_SEQ, "AdcRasterTime 1e-07", "AdcRasterTime nan"),
    # D56: the last section has no blank line after it, so the reader's stream fails at the end
    # of the file when it reads it, and it then skips [DEFINITIONS], which it reads later.
    "definitions.skipped": MINIMAL_SEQ + "\n[TRAP]\n1 1000 10 10 10 0",
    "extension.required-unknown": edit(
        MINIMAL_15_1,
        "RadiofrequencyRasterTime 1e-06",
        "RadiofrequencyRasterTime 1e-06\nRequiredExtensions FOO",
    ),
    "section.extensions-last": MINIMAL_SEQ + "\n[EXTENSIONS]\n",
    "blocks.missing": MINIMAL_SEQ.split("[BLOCKS]")[0],
    "ref.unresolved": edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100 0 0 0 0 1 0"),
    # D14: a fraction in an integer column of [BLOCKS].
    "syntax.row": edit(MINIMAL_SEQ, "1 100 0 0 0 0 0 0", "1 100.5 0 0 0 0 0 0"),
    "syntax.comment-row": edit(RF_FILE, "[RF]\n", "[RF]\n# a note\n"),
    "syntax.shape": edit(RF_FILE, "num_samples 6\n", "num_samples six\n"),
    "rotation.norm": edit(
        MINIMAL_SEQ, "[BLOCKS]\n1 100 0 0 0 0 0 0\n", ROTATION.format(q="2 0 0 0")
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
    import pulseq_cpp_siemens

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


def test_the_dwell_with_a_decimal_point_is_a_row_that_does_not_decode(tmp_path):
    """D15: the reader reads the dwell as an integer, so `2500.0` leaves the row short."""
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
    # The reader keeps no trace of an extension that it does not know (D45).
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
        edit(MINIMAL_SEQ, "[BLOCKS]\n1 100 0 0 0 0 0 0\n", ROTATION.format(q="1.0005 0 0 0"))
    )
    (row,) = read_seqfile(path, "cpp-siemens").extensions.rotations
    assert row["q0"] == 1.0
    assert read_seqfile(path, "strict").extensions.rotations["q0"].tolist() == [1.0005]


def test_the_interpreter_is_a_name_or_an_object_and_the_result_records_it():
    path = SEQFILES / "valid_1_5_1.seq"
    assert read_seqfile(path).interpreter == Strict()  # the default, until spec (R11)
    assert read_seqfile(path, "cpp-siemens").interpreter == CppSiemens(oversampling="center")
    edge = read_seqfile(path, CppSiemens(oversampling="edge"))
    assert edge.interpreter.oversampling == "edge" and edge.reading.oversampling == "edge"
    assert str(edge.interpreter) == "cpp-siemens(oversampling='edge')"
    strict = read_seqfile(path, "strict")
    assert strict.interpreter == Strict() and strict.reading is None
    with pytest.raises(ValueError, match="R11"):
        read_seqfile(path, "spec")
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
        assert synth.decode(clone).gradients_at([1], [150.0]).tolist() == (
            synth.decode(data).gradients_at([1], [150.0]).tolist()
        )
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.reading = None


def test_synth_decode_gives_the_readers_decoding_or_the_strict_events():
    path = SEQFILES / "valid_1_5_1.seq"
    data = read_seqfile(path, "cpp-siemens")
    decoding = synth.decode(data)
    assert isinstance(decoding, synth.CppSiemensDecoding)
    assert decoding.interpreter == data.interpreter
    assert decoding.block_count == len(data.blocks)
    assert [b["index"] for b in decoding.blocks()] == list(range(len(data.blocks)))
    times = np.array([0.0, 100.0, 150.0, 300.0])
    np.testing.assert_array_equal(
        decoding.gradients_at(np.ones(4, int), times),
        data.reading.gradients_at(np.ones(4, int), times),
    )
    strict = synth.decode(read_seqfile(path, "strict"))
    assert isinstance(strict, synth.StrictDecoding)
    assert set(strict.rf) == {1}
    with pytest.raises(TypeError, match="synth.decode"):
        synth.events.decode_rf(data)


def test_cpp_siemens_without_pulseq_cpp_siemens_says_which_extra_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "pulseq_cpp_siemens", None)
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq").interpreter == Strict()
    with pytest.raises(ImportError, match=re.escape("pulseq-analysis[cpp-siemens]")):
        read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens")
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq", "strict").interpreter == Strict()
