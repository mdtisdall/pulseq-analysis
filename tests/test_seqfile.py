import copy
import dataclasses
import pickle
import re
import warnings
from pathlib import Path

import numpy as np
import pytest

from pulseq_analysis import seqfile
from pulseq_analysis.model import Rasters, SequenceData, Shape, decompress_shape
from pulseq_analysis.seqfile import (
    MAX_LOCATIONS,
    RANGE_TOLERANCE,
    RULES,
    SeqFileError,
    Violation,
    read_seqfile,
)

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ORACLE = SEQFILES / "oracle"

# The rule that each `bad_*.seq` fixture of `tests/seqfiles` breaks, and only that rule. Each
# fixture is a copy of a valid fixture with one change.
FIXTURE_RULES = {
    "bad_version_missing.seq": "version.missing",
    "bad_version_invalid.seq": "version.invalid",
    "bad_version_unsupported_1_3.seq": "version.unsupported",
    "bad_version_unsupported_1_6.seq": "version.unsupported",
    "bad_definitions_raster_missing.seq": "definitions.raster-missing",
    "bad_definitions_raster_invalid.seq": "definitions.raster-invalid",
    "bad_definitions_duplicate.seq": "definitions.duplicate",
    "bad_section_unknown.seq": "section.unknown",
    "bad_section_delays.seq": "section.delays",
    "bad_section_duplicate.seq": "section.duplicate",
    "bad_syntax_encoding.seq": "syntax.encoding",
    "bad_syntax_line.seq": "syntax.line",
    "bad_syntax_line_after_comment.seq": "syntax.line",
    "bad_syntax_columns.seq": "syntax.columns",
    "bad_syntax_integer.seq": "syntax.integer",
    "bad_syntax_integer_plus.seq": "syntax.integer",
    "bad_syntax_number.seq": "syntax.number",
    "bad_syntax_use.seq": "syntax.use",
    "bad_syntax_negative.seq": "syntax.negative",
    "bad_syntax_shape.seq": "syntax.shape",
    "bad_syntax_shape_no_blank_line.seq": "syntax.shape",
    "bad_id_positive.seq": "id.positive",
    "bad_id_unique.seq": "id.unique",
    "bad_id_unique_block.seq": "id.unique",
    "bad_id_gradient_unique.seq": "id.gradient-unique",
    "bad_ref_block_rf.seq": "ref.unresolved",
    "bad_ref_shape.seq": "ref.unresolved",
    "bad_ref_time_shape.seq": "ref.unresolved",
    "bad_ref_extension_entry.seq": "ref.unresolved",
    "bad_ref_extension_object.seq": "ref.unresolved",
    "bad_ref_extension_type.seq": "ref.unresolved",
    "bad_ref_extension_cycle.seq": "ref.unresolved",
    "bad_ref_time_id_minus_1_in_1_4.seq": "ref.unresolved",
    "bad_blocks_empty.seq": "blocks.empty",
    "bad_blocks_order.seq": "blocks.order",
    "bad_block_event_too_long_rf.seq": "block.event-too-long",
    "bad_block_event_too_long_adc.seq": "block.event-too-long",
    "bad_block_event_too_long_trigger.seq": "block.event-too-long",
    "bad_raster_adc_dwell.seq": "raster.adc-dwell",
    "bad_raster_gradient_delay.seq": "raster.gradient-delay",
    "bad_raster_gradient_end.seq": "raster.gradient-end",
    "bad_raster_gradient_ramp.seq": "raster.gradient-ramp",
    "bad_raster_gradient_flat.seq": "raster.gradient-flat",
    "bad_gradient_nonzero_start_delay.seq": "gradient.nonzero-start-delay",
    "bad_gradient_nonzero_end_align.seq": "gradient.nonzero-end-align",
    "bad_shape_length.seq": "shape.length",
    "bad_shape_range.seq": "shape.range",
    "bad_shape_event_length.seq": "shape.event-length",
    "bad_extension_required_unknown.seq": "extension.required-unknown",
    "bad_extension_per_block.seq": "extension.per-block",
    "bad_layer1_gradient_ends.seq": "layer1.gradient-ends",
    "bad_signature_invalid.seq": "signature.invalid",
}

# The oracle files (`tests/seqfiles/oracle/SOURCES.md`): the version, the rule that the file
# breaks (None if it loads), and whether its `[SIGNATURE]` hash matches the file (None without a
# hash). The hash of `koma_v1.4_epi.seq` does not match: the file differs from the file that
# MATLAB signed (its version line was edited).
ORACLE_FILES = {
    "pulseq_fid.seq": ((1, 5, 1), None, True),
    "pulseq_epi_rs.seq": ((1, 5, 1), None, True),
    "pulseq_make_radial.seq": ((1, 5, 1), None, True),
    "pulseq_seq4.seq": ((1, 5, 0), None, True),
    "koma_v1.4_fid.seq": ((1, 4, 1), None, True),
    "koma_v1.4_epi.seq": ((1, 4, 1), None, False),
    "koma_v1.4_gr-trapezoidal.seq": ((1, 4, 1), None, True),
    "koma_v1.4_gr-time-shaped.seq": ((1, 4, 1), None, None),
    "koma_v1.4_gr-uniformly-shaped.seq": ((1, 4, 1), "layer1.gradient-ends", None),
    "koma_v1.4_rf-time-shaped.seq": ((1, 4, 1), None, True),
    "koma_v1.4_label_test.seq": ((1, 4, 0), None, True),
    "koma_v1.5_spiral.seq": ((1, 5, 1), None, True),
    "koma_v1.5_unknown_ext.seq": ((1, 5, 0), None, None),
    "koma_v1.5_rotation_radial_tiny.seq": ((1, 5, 1), None, True),
    "pypulseq_simple_mprage140.seq": ((1, 4, 0), "layer1.gradient-ends", None),
    "pypulseq_simple_mprage150.seq": ((1, 5, 0), None, True),
    "pypulseq_seq6.seq": ((1, 5, 0), None, True),
}


def _write(directory, text, name):
    path = directory / name
    path.write_text(text)
    return path


def violations_of(path):
    with pytest.raises(SeqFileError) as info:
        read_seqfile(path)
    return info.value


# ---- The valid fixtures ----


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("valid_1_4_0.seq", (1, 4, 0)),
        ("valid_1_4_1.seq", (1, 4, 1)),
        ("valid_1_5_0.seq", (1, 5, 0)),
        ("valid_1_5_1.seq", (1, 5, 1)),
        ("valid_crlf.seq", (1, 5, 1)),
        ("valid_comments_between_sections.seq", (1, 5, 1)),
        ("valid_no_signature.seq", (1, 5, 1)),
        ("valid_signature_mismatch.seq", (1, 5, 1)),
    ],
)
def test_valid_fixture_loads_with_its_version(name, version):
    data = read_seqfile(SEQFILES / name)
    assert isinstance(data, SequenceData)
    assert data.version == version
    assert data.origin == "file"


def test_valid_1_5_1_fixture_has_the_values_of_the_file():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert data.rasters == Rasters(gradient=1e-5, rf=1e-6, adc=1e-7, block_duration=1e-5)
    assert data.definitions["FOV"] == ("0.1", "0.1", "0.005")
    assert data.definitions["Name"] == ("valid_1_5_1",)
    assert list(data.definitions)[:2] == ["AdcRasterTime", "BlockDurationRaster"]
    assert data.required_extensions == ("ROTATIONS",)
    blocks = data.blocks
    assert blocks.dtype.names == ("id", "duration_ticks", "rf", "gx", "gy", "gz", "adc", "ext")
    assert blocks["id"].tolist() == list(range(1, 10))
    assert blocks["duration_ticks"].tolist() == [30, 50, 50, 10, 10, 5, 2, 100, 10]
    assert blocks["gx"].tolist() == [0, 1, 0, 0, 5, 0, 0, 0, 0]
    assert blocks["ext"].tolist() == [1, 0, 0, 7, 3, 0, 4, 5, 6]
    assert data.block_durations_s.tolist() == pytest.approx(
        [3e-4, 5e-4, 5e-4, 1e-4, 1e-4, 5e-5, 2e-5, 1e-3, 1e-4]
    )
    (rf,) = data.rf
    assert (rf["amplitude"], rf["mag_id"], rf["phase_id"], rf["time_id"]) == (1000, 1, 2, 0)
    assert (rf["center"], rf["delay"], rf["use"]) == (5e-5, 1e-4, "e")
    assert (rf["freq_ppm"], rf["phase_ppm"], rf["freq_offset"], rf["phase_offset"]) == (0, 0, 0, 0)
    assert data.grad["id"].tolist() == [2, 3, 4, 5, 6]
    assert data.grad["first"].tolist() == [0, 0, 500000, 0, 0]
    assert data.grad["last"].tolist() == [0, 500000, 0, 400000, 0]
    assert data.grad["time_id"].tolist() == [0, 0, 0, 6, -1]
    assert data.grad["delay"].tolist() == [1e-4, 4e-4, 0, 0, 0]
    (trap,) = data.trap
    assert (trap["id"], trap["amplitude"]) == (1, 1000000)
    assert (trap["rise"], trap["flat"], trap["fall"], trap["delay"]) == (1e-4, 2e-4, 1e-4, 1e-4)
    assert data.adc["num_samples"].tolist() == [8, 8]
    assert data.adc["dwell"].tolist() == [2.5e-5, 2.5e-5]
    assert data.adc["delay"].tolist() == [1e-4, 1e-4]
    assert data.adc["phase_shape_id"].tolist() == [0, 8]
    assert list(data.shapes) == list(range(1, 10))
    assert data.shapes[1].num_samples == 100
    assert data.shapes[1].packed.tolist() == [1, 0, 0, 97]
    assert data.shapes[1].samples().tolist() == [1.0] * 100
    assert data.shapes[3].packed.tolist() == pytest.approx([0.1 * i for i in range(1, 11)])
    assert data.shapes[6].samples().tolist() == [0, 1, 3, 6, 10]


def test_valid_1_5_1_fixture_has_the_extensions_of_the_file():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    ext = data.extensions
    assert ext.entries["next"].tolist() == [2, 0, 0, 0, 0, 3, 0]
    assert ext.type_ids == {
        "LABELSET": 1,
        "LABELINC": 2,
        "TRIGGERS": 3,
        "DELAYS": 4,
        "ROTATIONS": 5,
        "RF_SHIMS": 6,
        "UNKNOWN": 7,
    }
    assert ext.labelset.tolist() == [(1, 0, "LIN")]
    assert ext.labelinc.tolist() == [(1, 1, "LIN")]
    assert ext.triggers.tolist() == [(1, 1, 2, 0.0, 1e-5)]
    assert ext.soft_delays.tolist() == [(1, 0, -1e-4, 1.0, "TE")]
    assert ext.rotations.tolist() == [(1, 0.92388, 0.0, 0.0, 0.382683)]
    assert list(ext.rf_shims) == [1]
    assert ext.rf_shims[1].tolist() == [[1.0, 0.0], [1.0, 1.5708]]
    assert data.skipped_extensions == ("UNKNOWN",)


def test_extension_tables_of_a_file_without_extensions_are_empty():
    ext = read_seqfile(SEQFILES / "valid_1_4_0.seq").extensions
    for table in (ext.entries, ext.triggers, ext.labelset, ext.labelinc, ext.soft_delays):
        assert len(table) == 0
    assert len(ext.rotations) == 0
    assert len(ext.rf_shims) == 0
    assert ext.type_ids == {}


def test_valid_1_4_fixtures_have_the_1_5_layout_with_the_values_of_the_format():
    for name in ("valid_1_4_0.seq", "valid_1_4_1.seq"):
        data = read_seqfile(SEQFILES / name)
        (rf,) = data.rf
        assert (rf["freq_ppm"], rf["phase_ppm"], rf["use"]) == (0, 0, "u")
        assert np.isnan(rf["center"])
        assert rf["delay"] == 1e-4
        assert data.adc["phase_shape_id"].tolist() == [0]
        assert (data.adc["freq_ppm"][0], data.adc["phase_ppm"][0]) == (0, 0)
    data = read_seqfile(SEQFILES / "valid_1_4_1.seq")
    # The gradient with a time shape: the amplitude times the first and last sample.
    (grad,) = data.grad
    assert grad["first"] == pytest.approx(400000 * 0.2)
    assert grad["last"] == pytest.approx(400000 * 0.2)
    assert grad["time_id"] == 4


def test_signature_matches_is_reported_and_is_not_a_rule():
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq").signature.matches is True
    assert read_seqfile(SEQFILES / "valid_crlf.seq").signature.matches is True
    signature = read_seqfile(SEQFILES / "valid_signature_mismatch.seq").signature
    assert (signature.type, signature.hash, signature.matches) == ("md5", "0" * 32, False)
    assert read_seqfile(SEQFILES / "valid_no_signature.seq").signature is None


def test_read_seqfile_takes_a_str_or_a_path_and_raises_oserror_for_a_missing_file(tmp_path):
    path = SEQFILES / "valid_1_4_0.seq"
    assert read_seqfile(str(path)) == read_seqfile(path)
    with pytest.raises(FileNotFoundError):
        read_seqfile(tmp_path / "missing.seq")


# ---- The rules ----


def test_each_bad_fixture_is_listed_and_each_rule_has_a_fixture():
    files = {p.name for p in SEQFILES.glob("bad_*.seq")}
    assert files - {"bad_many.seq"} == set(FIXTURE_RULES)
    covered = set(FIXTURE_RULES.values()) | {
        rule for _, rule, _ in ORACLE_FILES.values() if rule is not None
    }
    assert covered == set(RULES)


@pytest.mark.parametrize(("name", "rule"), sorted(FIXTURE_RULES.items()))
def test_bad_fixture_breaks_its_rule_and_no_other(name, rule):
    error = violations_of(SEQFILES / name)
    assert {v.rule for v in error.violations} == {rule}
    assert not error.omitted
    assert all(isinstance(v, Violation) and v.message for v in error.violations)
    assert str(SEQFILES / name) in str(error)


@pytest.mark.parametrize(
    ("name", "section", "line"),
    [
        ("bad_version_unsupported_1_3.seq", "VERSION", 4),
        ("bad_version_missing.seq", None, None),
        ("bad_definitions_raster_missing.seq", "DEFINITIONS", None),
        ("bad_definitions_raster_invalid.seq", "DEFINITIONS", 13),
        ("bad_section_unknown.seq", None, 106),
        ("bad_syntax_line.seq", None, 1),
        ("bad_syntax_columns.seq", "BLOCKS", 21),
        ("bad_syntax_shape_no_blank_line.seq", "SHAPES", 147),
        ("bad_blocks_order.seq", "BLOCKS", 23),
        ("bad_id_unique_block.seq", "BLOCKS", 23),
        ("bad_id_positive.seq", "RF", 36),
        ("bad_id_gradient_unique.seq", "TRAP", 52),
        ("bad_id_unique.seq", "ADC", 58),
        ("bad_ref_extension_object.seq", "EXTENSIONS", 64),
        ("bad_raster_adc_dwell.seq", "ADC", 57),
        ("bad_raster_gradient_ramp.seq", "TRAP", 51),
        ("bad_shape_length.seq", "SHAPES", 178),
        ("bad_extension_required_unknown.seq", "DEFINITIONS", 16),
        ("bad_block_event_too_long_trigger.seq", "BLOCKS", 27),
        ("bad_layer1_gradient_ends.seq", "GRADIENTS", 30),
    ],
)
def test_violation_names_the_section_and_the_line(name, section, line):
    (violation, *rest) = violations_of(SEQFILES / name).violations
    assert not rest
    assert (violation.section, violation.line) == (section, line)
    text = (SEQFILES / name).read_bytes().split(b"\n")
    if line is not None and section not in (None, "SHAPES", "DEFINITIONS"):
        assert text[line - 1].strip()  # the line is a row of the file, not a comment


def test_a_file_with_several_violations_gives_all_of_them_in_file_order():
    error = violations_of(SEQFILES / "bad_many.seq")
    assert [v.rule for v in error.violations] == [
        "extension.required-unknown",
        "ref.unresolved",
        "raster.adc-dwell",
    ]
    lines = [v.line for v in error.violations]
    assert lines == sorted(lines)


def test_an_error_lists_20_locations_of_a_rule_and_counts_the_rest(tmp_path):
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    rows = "".join(f"{i} 1000 1 2 0 50 100 0 0 0 0 x\n" for i in range(2, 27))
    old = "1 1000 1 2 0 50 100 0 0 0 0 e\n"
    path = tmp_path / "many.seq"
    path.write_text(text.replace(old, old + rows))
    error = violations_of(path)
    assert MAX_LOCATIONS == 20
    assert len(error.violations) == 20
    assert {v.rule for v in error.violations} == {"syntax.use"}
    assert dict(error.omitted) == {"syntax.use": 5}
    assert "5 more" in str(error)


def test_seqfile_error_is_a_value_error_and_can_be_pickled():
    error = violations_of(SEQFILES / "bad_many.seq")
    assert isinstance(error, ValueError)
    copy_ = pickle.loads(pickle.dumps(error))
    assert copy_.violations == error.violations
    assert dict(copy_.omitted) == dict(error.omitted)
    assert copy_.path == error.path
    with pytest.raises(dataclasses.FrozenInstanceError):
        error.violations[0].rule = "x"


def test_each_rule_of_the_module_docstring_is_a_rule_of_the_table():
    named = set(re.findall(r"`([a-z0-9]+\.[a-z0-9-]+)`", seqfile.__doc__))
    named = {n for n in named if n.split(".")[0] in {r.split(".")[0] for r in RULES}}
    assert named == set(RULES)


def test_syntax_of_numbers_in_a_table(tmp_path):
    """Rejected: a float or a sign in an integer column, hex, an exponent; a float column
    takes an exponent and a sign."""
    base = (SEQFILES / "valid_no_signature.seq").read_text()
    row = "1  30  1  0  0  0  0  1\n"
    for bad in (
        "1  3e1  1  0  0  0  0  1\n",
        "1  0x1e  1  0  0  0  0  1\n",
        "1  30.0  1  0  0  0  0  1\n",
    ):
        error = violations_of(_write(tmp_path, base.replace(row, bad), "n.seq"))
        assert {v.rule for v in error.violations} == {"syntax.integer"}
    amplitude = "1 1000000 100 200 100 100\n"
    for good in (
        "1 1e+06 100 200 100 100\n",
        "1 +1000000 100 200 100 100\n",
        "1 1000000. 100 200 100 100\n",
    ):
        assert (
            read_seqfile(_write(tmp_path, base.replace(amplitude, good), "g.seq")).trap[
                "amplitude"
            ][0]
            == 1e6
        )
    for bad in ("1 inf 100 200 100 100\n", "1 1,5 100 200 100 100\n", "1 1e999 100 200 100 100\n"):
        error = violations_of(_write(tmp_path, base.replace(amplitude, bad), "b.seq"))
        assert {v.rule for v in error.violations} == {"syntax.number"}


def test_an_empty_file_and_a_file_with_only_a_version_list_what_is_missing(tmp_path):
    empty = violations_of(_write(tmp_path, "", "empty.seq"))
    assert [v.rule for v in empty.violations] == ["version.missing"]
    version = "[VERSION]\nmajor 1\nminor 5\nrevision 0\n"
    error = violations_of(_write(tmp_path, version, "version.seq"))
    assert sorted(v.rule for v in error.violations) == [
        "blocks.empty",
        "definitions.raster-missing",
        "definitions.raster-missing",
        "definitions.raster-missing",
        "definitions.raster-missing",
    ]


def test_a_comment_with_a_non_ascii_character_is_read(tmp_path):
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    path = _write(tmp_path, text.replace("# NUM DUR", "# duration in \u00b5s, NUM DUR"), "mu.seq")
    assert read_seqfile(path) == read_seqfile(SEQFILES / "valid_no_signature.seq")


def test_comments_and_blank_lines_between_sections_are_read_as_nothing():
    plain = read_seqfile(SEQFILES / "valid_comments_between_sections.seq")
    assert plain.skipped_extensions == ()
    assert plain.blocks["id"].tolist() == list(range(1, 10))
    assert len(plain.shapes) == 9 and len(plain.extensions.labelset) == 1


@pytest.mark.parametrize(
    ("after", "line"),
    [
        ("1  30  1  0  0  0  0  1\n", "# a comment\n"),
        ("1  30  1  0  0  0  0  1\n", "\n"),
        ("1  30  1  0  0  0  0  1\n", "   \n"),
        ("2 500000 0 0 3 0 100\n", "# a comment\n"),
        ("1 1 1 2\n", "# a comment\n"),
        ("1 1 1 2\n", "\n"),
    ],
    ids=[
        "comment-blocks",
        "blank-blocks",
        "spaces-blocks",
        "comment-trap",
        "comment-list",
        "blank-ext",
    ],
)
def test_a_comment_or_blank_line_ends_a_section_and_a_later_row_is_syntax_line(
    tmp_path, after, line
):
    """`read.m` reads a table up to the first blank or `#` line (lines 502 to 516, 528 to 587, 589
    to 626): the rows after it are not rows of the table. Here they are `syntax.line`."""
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    assert text.count(after) == 1
    path = _write(tmp_path, text.replace(after, after + line), "split.seq")
    error = violations_of(path)
    # The rows that are dropped can leave a reference with no target: `ref.unresolved` too.
    assert "syntax.line" in {v.rule for v in error.violations}
    if after.startswith("1  30"):
        assert {v.rule for v in error.violations} == {"syntax.line"}
    lines = path.read_text().split("\n")
    for v in error.violations:
        if v.rule == "syntax.line":
            assert lines[v.line - 1].strip() and lines[v.line - 1][0] != "#"


def test_a_comment_right_after_a_table_header_ends_the_table(tmp_path):
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    path = _write(tmp_path, text.replace("[TRAP]\n", "[TRAP]\n# a comment\n"), "c.seq")
    error = violations_of(path)
    (first, *_) = (v for v in error.violations if v.rule == "syntax.line")
    assert first.section == "TRAP"


def test_definitions_and_signature_skip_comments_and_blanks_before_the_first_line(tmp_path):
    """`read.m` skips them for these two sections (`skipComments`, line 460), and for no other."""
    text = (SEQFILES / "valid_1_5_1.seq").read_text()
    path = _write(tmp_path, text.replace("[DEFINITIONS]\n", "[DEFINITIONS]\n# a\n\n# b\n"), "d.seq")
    expected = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    unsigned = dataclasses.replace(read_seqfile(path), signature=None)  # the hash changes
    assert unsigned == dataclasses.replace(expected, signature=None)
    # After the first line, a comment ends the section: the rest of the signature is not read.
    signed = (SEQFILES / "valid_1_5_1.seq").read_text()
    path = _write(tmp_path, signed.replace("Type md5\n", "Type md5\n# a\n"), "s.seq")
    assert {v.rule for v in violations_of(path).violations} == {"syntax.line", "signature.invalid"}
    # [VERSION] has no such skip (line 479): a comment after the header ends the section.
    path = _write(tmp_path, signed.replace("[VERSION]\n", "[VERSION]\n# a\n"), "v.seq")
    assert "syntax.line" in {v.rule for v in violations_of(path).violations}


def test_a_comment_line_ends_a_shape_like_a_blank_line(tmp_path):
    """`read.m` ends the samples of a shape at a blank or `#` line (line 653), and then skips
    blank and `#` lines to the next `shape_id` (line 659)."""
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    path = _write(tmp_path, text.replace("\n\nshape_id 2", "\n# a comment\nshape_id 2"), "e.seq")
    assert read_seqfile(path) == read_seqfile(SEQFILES / "valid_no_signature.seq")
    # A comment among the samples cuts the shape: the samples after it are outside a shape.
    cut = text.replace("0.3\n0.4\n0.5\n", "0.3\n# a comment\n0.4\n0.5\n")
    rules = {v.rule for v in violations_of(_write(tmp_path, cut, "cut.seq")).violations}
    assert rules == {"syntax.shape", "shape.length"}
    # `read.m` skips a comment between `shape_id` and `num_samples`; this reader does not.
    head = text.replace("shape_id 5\n", "shape_id 5\n# a comment\n")
    error = violations_of(_write(tmp_path, head, "head.seq"))
    assert "syntax.shape" in {v.rule for v in error.violations}


def test_a_shape_ends_only_at_a_blank_line(tmp_path):
    """A `shape_id` line right after the samples of a shape, with no blank line, is
    `syntax.shape` at that line; the shapes are still read, so there is no second violation."""
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    path = _write(tmp_path, text.replace("\n\nshape_id", "\nshape_id"), "tight.seq")
    error = violations_of(path)
    assert {v.rule for v in error.violations} == {"syntax.shape"}
    assert len(error.violations) == text.count("\n\nshape_id") - 1  # not the first shape
    lines = path.read_text().split("\n")
    assert all(lines[v.line - 1].startswith("shape_id") for v in error.violations)


def test_a_repeated_block_id_is_id_unique_and_not_blocks_order(tmp_path):
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    row = "3  50  0  0  0  3  0  0\n"
    for old, new in (
        (row, "2  50  0  0  0  3  0  0\n"),
        ("2  50  0  1  2  0  1  0\n", "1  50  0  1  2  0  1  0\n"),
    ):
        error = violations_of(_write(tmp_path, text.replace(old, new), "repeat.seq"))
        assert [v.rule for v in error.violations] == ["id.unique"]
    # IDs that fall below an earlier ID are out of order, each one a violation.
    swapped = text.replace("2  50  0  1  2  0  1  0\n" + row, row + "2  50  0  1  2  0  1  0\n")
    error = violations_of(_write(tmp_path, swapped, "swapped.seq"))
    assert [v.rule for v in error.violations] == ["blocks.order"]


def test_required_extensions_is_an_extension_rule_from_1_5_1_only(tmp_path):
    text = (SEQFILES / "valid_1_5_0.seq").read_text()
    path = _write(tmp_path, text.replace("Name valid_1_5_0", "RequiredExtensions FOO"), "r.seq")
    data = read_seqfile(path)
    assert data.definitions["RequiredExtensions"] == ("FOO",)
    assert data.required_extensions == ()


def test_random_edits_of_valid_files_give_a_model_or_a_seqfile_error(tmp_path):
    """Whatever the edit, the reader gives a model, or `SeqFileError` with a violation. It
    raises no other exception."""
    rng = np.random.default_rng(11)
    texts = [
        (SEQFILES / name).read_text()
        for name in ("valid_1_4_0.seq", "valid_1_4_1.seq", "valid_1_5_0.seq", "valid_1_5_1.seq")
    ]
    pieces = ["0", "-1", "99", "1.5", "nan", "inf", "+2", "x", "", "1e999", "99999999999999999999"]
    pieces += ["[BLOCKS]", "[SHAPES]", "extension FOO 3", "shape_id 3", "num_samples 4", "#"]
    path = tmp_path / "edited.seq"
    outcomes = {"model": 0, "error": 0}
    for _ in range(400):
        lines = texts[int(rng.integers(len(texts)))].split("\n")
        for _ in range(int(rng.integers(1, 4))):
            i = int(rng.integers(len(lines)))
            kind = int(rng.integers(5))
            if kind == 0:
                del lines[i]
            elif kind == 1:
                lines.insert(i, lines[i])
            elif kind == 2:
                words = lines[i].split(" ")
                words[int(rng.integers(len(words)))] = pieces[int(rng.integers(len(pieces)))]
                lines[i] = " ".join(words)
            elif kind == 3:
                lines[i] = lines[i][: int(rng.integers(len(lines[i]) + 1))]
            else:
                lines.insert(i, pieces[int(rng.integers(len(pieces)))])
            lines = lines or [""]
        path.write_text("\n".join(lines))
        try:
            read_seqfile(path)
            outcomes["model"] += 1
        except SeqFileError as error:
            assert error.violations
            outcomes["error"] += 1
    assert outcomes["model"] > 0 and outcomes["error"] > 100


# ---- Shapes ----


def _compress(samples):
    """The compression of the specification, section 2.9.1 (MATLAB `compressShape`): the
    derivative with a run-length code, or the samples themselves when that is not shorter."""
    samples = np.asarray(samples, dtype=float)
    derivative = np.diff(samples, prepend=0.0)
    packed, i = [], 0
    while i < len(derivative):
        j = i
        while j + 1 < len(derivative) and derivative[j + 1] == derivative[i]:
            j += 1
        run = j - i + 1
        packed += [derivative[i]] if run == 1 else [derivative[i], derivative[i], run - 2]
        i = j + 1
    return np.array(packed) if len(packed) < len(samples) else samples


def test_decompress_shape_of_the_three_examples_of_the_specification():
    # Example 1: a ramp up, a constant and a ramp down (15 samples).
    packed = np.array([0, 0.1, 0.15, 0.25, 0.5, 0, 0, 4, -0.25, -0.25, 2])
    expected = [0, 0.1, 0.25, 0.5] + [1.0] * 7 + [0.75, 0.5, 0.25, 0]
    assert decompress_shape(packed, 15).tolist() == pytest.approx(expected)
    # Example 2: 100 zeros.
    assert decompress_shape(np.array([0, 0, 98.0]), 100).tolist() == [0.0] * 100
    # Example 3: a constant of 1.0 for 100 samples.
    assert decompress_shape(np.array([1, 0, 0, 97.0]), 100).tolist() == [1.0] * 100


def test_decompress_shape_keeps_a_shape_with_as_many_values_as_samples():
    """A shape is uncompressed when the number of stored values is `num_samples`, even where
    two stored values are equal."""
    packed = np.array([0.5, 0.5, 3.0, 1.0])
    assert decompress_shape(packed, 4).tolist() == packed.tolist()


def test_decompress_shape_of_values_that_look_like_a_repeat():
    """A repeat count equal to the value that follows, and the same value three times, are not
    read as a second repeat (the false markers that MATLAB's `decompressShape.m` skips)."""
    for samples in ([2, 2, 2, 2, 3, 3, 3, 4], [1, 1, 1, 1, 6, 11, 16, 21], [0, 3, 6, 9, 12, 15]):
        packed = _compress(samples)
        assert decompress_shape(packed, len(samples)).tolist() == samples


def test_decompress_shape_inverts_compress_on_random_shapes():
    rng = np.random.default_rng(7)
    compressed = 0
    for _ in range(300):
        n = int(rng.integers(1, 60))
        samples = np.cumsum(rng.integers(-2, 3, size=n)).astype(float)
        if rng.random() < 0.3:
            samples[rng.integers(0, n) :] = samples[rng.integers(0, n)]
        packed = _compress(samples)
        compressed += len(packed) < n
        assert decompress_shape(packed, n).tolist() == samples.tolist()
    assert compressed > 50  # the loop did test the compressed form


@pytest.mark.parametrize(
    ("packed", "num_samples", "message"),
    [
        ([1.0, 0, 0, 97], 99, "more than the 99"),
        ([1.0, 0, 0, 97], 101, "it has 100 samples, not the 101"),
        ([1.0, 2, 2], 5, "cut at the end"),
        ([1.0, 0, 0, -3], 10, "repeat count is -3"),
        ([1.0, 0, 0, 1.5], 10, "repeat count is 1.5"),
        ([1.0, 2.0, 3.0], 4, "it has 3 samples, not the 4"),
    ],
)
def test_decompress_shape_rejects_a_code_that_is_not_num_samples_long(packed, num_samples, message):
    with pytest.raises(ValueError, match=message):
        decompress_shape(np.array(packed), num_samples)


def test_a_shape_of_the_file_is_decompressed_to_num_samples_when_read():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert data.shapes[9].num_samples == 15
    assert len(data.shapes[9].samples()) == 15
    assert data.shapes[9].samples()[-1] == pytest.approx(0.0)
    assert data.shapes[2].samples().tolist() == [0.0] * 100


# ---- The model ----


def test_model_arrays_are_read_only_and_cannot_be_made_writable():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    arrays = [data.blocks, data.rf, data.grad, data.trap, data.adc, data.extensions.entries]
    arrays += [data.extensions.rotations, data.shapes[1].packed, data.extensions.rf_shims[1]]
    for array in arrays:
        assert not array.flags.writeable
        with pytest.raises(ValueError, match="read-only"):
            array[0] = array[0]
        with pytest.raises(ValueError):
            array.flags.writeable = True
    with pytest.raises(ValueError):
        data.blocks["id"][0] = 7
    with pytest.raises(ValueError):
        data.blocks["id"].flags.writeable = True


def test_model_mappings_and_fields_cannot_be_changed():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    for mapping in (
        data.definitions,
        data.shapes,
        data.extensions.type_ids,
        data.extensions.rf_shims,
    ):
        with pytest.raises(TypeError):
            mapping["x"] = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.version = (1, 4, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.rasters.gradient = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.shapes[1].num_samples = 1
    assert not hasattr(data, "__dict__")
    assert isinstance(data.version, tuple) and isinstance(data.required_extensions, tuple)
    assert isinstance(data.skipped_extensions, tuple)


def test_model_without_values_of_a_target():
    """The model has no dead time, gamma, B0 or limit field (they are layer 2)."""
    names = {f.name for f in dataclasses.fields(SequenceData)}
    assert names == {
        "version",
        "definitions",
        "rasters",
        "required_extensions",
        "blocks",
        "rf",
        "grad",
        "trap",
        "adc",
        "shapes",
        "extensions",
        "skipped_extensions",
        "signature",
        "origin",
    }
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    text = " ".join(str(t.dtype.names) for t in (data.rf, data.grad, data.trap, data.adc))
    assert not re.search(r"dead|ringdown|gamma|limit|b0", text)


def test_models_are_equal_by_value_and_not_hashable(tmp_path):
    first = read_seqfile(SEQFILES / "valid_1_4_1.seq")
    second = read_seqfile(SEQFILES / "valid_1_4_1.seq")
    assert first is not second
    assert first == second  # also with the NaN `center`
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq") == read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert first != read_seqfile(SEQFILES / "valid_1_4_0.seq")
    assert first != "valid_1_4_1.seq"
    with pytest.raises(TypeError):
        hash(first)
    # One changed number makes the models different.
    text = (
        (SEQFILES / "valid_1_4_1.seq")
        .read_text()
        .replace("1 1000 1 2 0 100 0 0", "1 1001 1 2 0 100 0 0")
    )
    assert read_seqfile(_write(tmp_path, text, "changed.seq")) != first


def test_models_survive_pickle_and_deepcopy_with_their_values_and_immutability():
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    for clone in (pickle.loads(pickle.dumps(data)), copy.deepcopy(data)):
        assert clone == data
        assert not clone.blocks.flags.writeable
        with pytest.raises(ValueError):
            clone.blocks.flags.writeable = True
        with pytest.raises(TypeError):
            clone.definitions["x"] = ("1",)
        assert clone.shapes[1].samples().tolist() == data.shapes[1].samples().tolist()
    assert isinstance(Shape(2, np.array([0.0, 1.0])).packed, np.ndarray)
    assert not Shape(2, np.array([0.0, 1.0])).packed.flags.writeable


# ---- The oracle files ----


@pytest.mark.parametrize(("name", "expected"), sorted(ORACLE_FILES.items()))
def test_oracle_file_loads_or_breaks_the_rule_that_it_must(name, expected):
    version, rule, matches = expected
    path = ORACLE / name
    if rule is not None:
        error = violations_of(path)
        assert {v.rule for v in error.violations} == {rule}
        return
    data = read_seqfile(path)
    assert data.version == version
    assert (data.signature.matches if data.signature else None) is matches
    assert len(data.blocks) > 0


def test_oracle_directory_has_the_files_of_the_test_and_sources_md_names_each():
    files = {p.name for p in ORACLE.glob("*.seq")}
    assert files == set(ORACLE_FILES)
    sources = (ORACLE / "SOURCES.md").read_text()
    for name in files:
        assert f"`{name}`" in sources


def test_oracle_corpus_has_each_feature_of_the_task():
    """The corpus covers 1.4 and 1.5.x, gradients on the default raster, with a time shape and
    oversampled, compressed and uncompressed shapes, labels, triggers, soft delays, rotations,
    an extension that the parser skips, and signatures."""
    loaded = {
        n: read_seqfile(ORACLE / n) for n, (_, rule, _) in ORACLE_FILES.items() if rule is None
    }
    assert {d.version[:2] for d in loaded.values()} == {(1, 4), (1, 5)}
    time_ids = {t for d in loaded.values() for t in d.grad["time_id"].tolist()}
    assert {-1, 0} <= time_ids and any(t > 0 for t in time_ids)
    packed = [len(s.packed) < s.num_samples for d in loaded.values() for s in d.shapes.values()]
    assert any(packed) and not all(packed)
    ext = [d.extensions for d in loaded.values()]
    assert any(len(e.labelset) for e in ext) and any(len(e.labelinc) for e in ext)
    assert any(len(e.triggers) for e in ext) and any(len(e.soft_delays) for e in ext)
    assert any(len(e.rotations) for e in ext)
    assert any(d.skipped_extensions for d in loaded.values())
    assert any(d.required_extensions for d in loaded.values())
    assert any(d.signature and d.signature.matches for d in loaded.values())
    assert any(d.adc["phase_shape_id"].any() for d in loaded.values() if d.version >= (1, 5, 0))


def test_oracle_amplitude_shapes_are_within_the_tolerance_of_the_range():
    """The largest excess of an amplitude shape over 1 in the oracle files is far below
    `RANGE_TOLERANCE`, so the tolerance is not what lets an oracle file load."""
    excess = []
    for name, (_, rule, _) in ORACLE_FILES.items():
        if rule is not None:
            continue
        data = read_seqfile(ORACLE / name)
        ids = set(data.rf["mag_id"].tolist()) | set(data.grad["shape_id"].tolist())
        excess += [
            np.abs(data.shapes[i].samples()).max() - 1 for i in ids if data.shapes[i].num_samples
        ]
    assert max(excess) < 1e-12
    assert RANGE_TOLERANCE == 1e-9


def test_oracle_spiral_of_1_5_has_the_oversampled_gradients_of_the_file():
    data = read_seqfile(ORACLE / "koma_v1.5_spiral.seq")
    oversampled = data.grad[data.grad["time_id"] == -1]
    assert len(oversampled) > 0
    for row in oversampled:
        assert data.shapes[row["shape_id"]].num_samples % 2 == 1


def test_oracle_fid_of_the_pulseq_repository_has_the_values_of_the_text():
    data = read_seqfile(ORACLE / "pulseq_fid.seq")
    assert data.definitions["Name"] == ("fid",)
    assert data.blocks["duration_ticks"][:4].tolist() == [43, 2000, 324, 100000]
    assert data.blocks["rf"][:4].tolist() == [1, 0, 0, 0]
    assert data.block_durations_s[:4].tolist() == pytest.approx([4.3e-4, 2e-2, 3.24e-3, 1.0])


def test_oracle_1_4_gradient_with_a_time_shape_has_its_end_samples():
    data = read_seqfile(ORACLE / "koma_v1.4_gr-time-shaped.seq")
    (grad,) = data.grad
    assert (grad["amplitude"], grad["time_id"], grad["delay"]) == (1257918.64134, 2, 0.0)
    assert (grad["first"], grad["last"]) == (0.0, 0.0)
    assert data.shapes[2].samples().tolist() == [0, 1, 3, 6, 7, 9, 12, 13, 15, 18]


def test_oracle_label_extensions_of_a_1_4_file():
    ext = read_seqfile(ORACLE / "koma_v1.4_label_test.seq").extensions
    assert ext.labelset["name"].tolist() == ["REV", "ECO", "ECO", "ECO", "LIN"]
    assert ext.labelset["value"].tolist() == [0, 0, 2, 1, 0]
    assert ext.labelinc.tolist() == [(1, 1, "LIN")]


def test_oracle_unknown_extension_is_skipped_and_a_required_one_is_listed():
    data = read_seqfile(ORACLE / "koma_v1.5_unknown_ext.seq")
    assert data.skipped_extensions == ("UNKNOWN1", "UNKNOWN2")
    assert data.extensions.type_ids == {"UNKNOWN1": 1, "UNKNOWN2": 2}
    radial = read_seqfile(ORACLE / "koma_v1.5_rotation_radial_tiny.seq")
    assert radial.required_extensions == ("ROTATIONS",)
    assert radial.extensions.rotations["q0"].tolist() == [1.0, 0.92388, 0.707107]


def test_files_of_pypulseq_are_read(tmp_path):
    """The parser reads files that pypulseq writes (the sequences of `scale_sequences`)."""
    pytest.importorskip("pypulseq")
    from scale_sequences import TR_BLOCKS, build_repeating, build_worst

    for build in (build_repeating, build_worst):
        path = tmp_path / f"{build.__name__}.seq"
        build(40).write(str(path))
        data = read_seqfile(path)
        assert len(data.blocks) == 40 * TR_BLOCKS
        assert data.version >= (1, 5, 0)
        assert data.signature is not None


def test_tables_agree_with_pypulseq_read_without_merging(tmp_path):
    """Compare, not trust: where pypulseq can read an oracle file (`remove_duplicates=False`),
    its block table, block durations, trapezoids and shapes are those of the model."""
    pp = pytest.importorskip("pypulseq")
    compared = 0
    for name, (_, rule, _) in ORACLE_FILES.items():
        if rule is not None:
            continue
        data = read_seqfile(ORACLE / name)
        seq = pp.Sequence()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # it warns about a file version it does not know
                seq.read(str(ORACLE / name), remove_duplicates=False)
        except ValueError as error:
            assert "Unknown section code: extension" in str(error)  # an extension it cannot read
            continue
        compared += 1
        ids = list(seq.block_events)
        assert ids == data.blocks["id"].tolist(), name
        rows = np.array([seq.block_events[i] for i in ids])
        for column, key in enumerate(("rf", "gx", "gy", "gz", "adc", "ext"), 1):
            assert rows[:, column].tolist() == data.blocks[key].tolist(), (name, key)
        durations = np.array([seq.block_durations[i] for i in ids])
        assert durations == pytest.approx(data.block_durations_s, abs=1e-9)
        for row in data.trap:
            library = seq.grad_library.data[int(row["id"])]
            expected = [row[k] for k in ("amplitude", "rise", "flat", "fall", "delay")]
            assert library[:5] == pytest.approx(expected, rel=1e-6, abs=1e-12), (name, row["id"])
        for shape_id, shape in data.shapes.items():
            library = seq.shape_library.data[shape_id]
            assert int(library[0]) == shape.num_samples
            assert library[1:].tolist() == shape.packed.tolist()
    assert compared >= 10
