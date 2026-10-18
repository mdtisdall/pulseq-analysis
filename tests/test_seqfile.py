"""Tests of the `spec` interpreter (`seqfile.spec`, the default of `read_seqfile`) and of the model
of layer 1 (`seqfile.model`): the verdict on each file of `tests/seqfiles`, a test for each row of
section 6 of `docs/plans/parser-redesign.md`, the basis of each rule, and the model.

A test cites the sources of its rule: spec:N is line N of `doc/specification.tex` of pulseq/pulseq
at `c7469123` (1.5.3 draft), "slide N" a slide of `doc/pulseq_shapes_and_times.pdf` (the slide set
that section 2.6 of the specification cites, normative for timing), and Dnn an entry of
`docs/discrepancies.md`. A test says when the behaviour is the package's choice: the
specification and the slides do not state it.
"""

import copy
import dataclasses
import hashlib
import pickle
import re
from pathlib import Path

import numpy as np
import pytest

from pulseq_analysis.seqfile import (
    NotSupported,
    SeqFileError,
    Spec,
    Violation,
    read_seqfile,
)
from pulseq_analysis.seqfile.model import (
    Rasters,
    Record,
    SequenceData,
    Shape,
    decompress_shape,
    rf_time_step,
)
from pulseq_analysis.seqfile.spec import (
    MAX_LOCATIONS,
    RANGE_TOLERANCE,
    RULES,
    _off_raster,
    read_spec,
)
from pulseq_analysis.synth import events

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ORACLE = SEQFILES / "oracle"

# What the end of the message of a violation of a rule of the package's choice says (`spec`).
CHOICE = "(the specification does not state this rule: "

# The verdict of `spec` on each file of `tests/seqfiles` (also `oracle` and `undefined`): "reads",
# "NotSupported" (a version outside 1.4.0 to 1.5.x, Q1 of docs/plans/parser-redesign.md), or the
# code of its rejection, and only that code (the codes of `bad_many.seq`, joined by ","). Each
# `bad_*.seq` fixture is a copy of a valid fixture with one change.
VERDICTS = {
    "bad_block_event_too_long_adc.seq": "block.event-too-long",
    "bad_block_event_too_long_rf.seq": "block.event-too-long",
    "bad_block_event_too_long_trigger.seq": "block.event-too-long",
    "bad_blocks_empty.seq": "blocks.empty",
    "bad_blocks_order.seq": "reads",
    "bad_definitions_duplicate.seq": "reads",
    "bad_definitions_raster_invalid.seq": "definitions.raster-invalid",
    "bad_definitions_raster_missing.seq": "definitions.raster-missing",
    "bad_extension_per_block.seq": "extension.per-block",
    "bad_extension_required_unknown.seq": "extension.required-unknown",
    "bad_gradient_nonzero_end_align.seq": "gradient.nonzero-end-align",
    "bad_gradient_nonzero_start_delay.seq": "gradient.nonzero-start-delay",
    "bad_id_gradient_unique.seq": "id.gradient-unique",
    "bad_id_positive.seq": "id.positive",
    "bad_id_unique.seq": "id.unique",
    "bad_id_unique_block.seq": "id.unique",
    "bad_layer1_gradient_ends.seq": "layer1.gradient-ends",
    "bad_many.seq": "extension.required-unknown,raster.adc-dwell,ref.unresolved",
    "bad_raster_adc_delay.seq": "raster.adc-delay",
    "bad_raster_adc_dwell.seq": "raster.adc-dwell",
    "bad_raster_gradient_delay.seq": "raster.gradient-delay",
    "bad_raster_gradient_end.seq": "raster.gradient-end",
    "bad_raster_gradient_flat.seq": "raster.gradient-flat",
    "bad_raster_gradient_ramp.seq": "raster.gradient-ramp",
    "bad_raster_gradient_vertex.seq": "raster.gradient-vertex",
    "bad_raster_rf_delay.seq": "raster.rf-delay",
    "bad_ref_block_rf.seq": "ref.unresolved",
    "bad_ref_extension_cycle.seq": "ref.unresolved",
    "bad_ref_extension_entry.seq": "ref.unresolved",
    "bad_ref_extension_object.seq": "ref.unresolved",
    "bad_ref_extension_type.seq": "ref.unresolved",
    "bad_ref_shape.seq": "ref.unresolved",
    "bad_ref_time_id_minus_1_in_1_4.seq": "ref.unresolved",
    "bad_ref_time_shape.seq": "ref.unresolved",
    "bad_section_delays.seq": "reads",
    "bad_section_duplicate.seq": "section.duplicate",
    "bad_section_duplicate_extension.seq": "section.duplicate",
    "bad_section_duplicate_signature.seq": "section.duplicate",
    "bad_section_unknown.seq": "reads",
    "bad_shape_adc_phase_length.seq": "shape.event-length",
    "bad_shape_empty.seq": "shape.empty",
    "bad_shape_event_length.seq": "shape.event-length",
    "bad_shape_length.seq": "shape.length",
    "bad_shape_oversampled_length.seq": "shape.oversampled-length",
    "bad_shape_range.seq": "shape.range",
    "bad_shape_rf_magnitude_negative.seq": "reads",
    "bad_shape_rf_phase_range.seq": "reads",
    "bad_shape_rf_time_end.seq": "reads",
    "bad_shape_rf_time_grid.seq": "reads",
    "bad_shape_time_order.seq": "shape.time-order",
    "bad_signature_invalid.seq": "signature.invalid",
    "bad_syntax_columns.seq": "syntax.columns",
    "bad_syntax_encoding.seq": "syntax.encoding",
    "bad_syntax_integer.seq": "syntax.integer",
    "bad_syntax_integer_plus.seq": "reads",
    "bad_syntax_line.seq": "syntax.line",
    "bad_syntax_line_after_comment.seq": "reads",
    "bad_syntax_negative.seq": "syntax.negative",
    "bad_syntax_number.seq": "syntax.number",
    "bad_syntax_shape.seq": "syntax.shape",
    "bad_syntax_shape_end.seq": "syntax.shape",
    "bad_syntax_shape_no_blank_line.seq": "syntax.shape",
    "bad_syntax_use.seq": "syntax.use",
    "bad_version_invalid.seq": "version.invalid",
    "bad_version_missing.seq": "version.missing",
    "bad_version_unsupported_1_3.seq": "NotSupported",
    "bad_version_unsupported_1_6.seq": "NotSupported",
    "oracle/koma_v1.4_epi.seq": "reads",
    "oracle/koma_v1.4_fid.seq": "reads",
    "oracle/koma_v1.4_gr-time-shaped.seq": "reads",
    "oracle/koma_v1.4_gr-trapezoidal.seq": "reads",
    "oracle/koma_v1.4_gr-uniformly-shaped.seq": "layer1.gradient-ends",
    "oracle/koma_v1.4_label_test.seq": "reads",
    "oracle/koma_v1.4_rf-time-shaped.seq": "reads",
    "oracle/koma_v1.5_rotation_radial_tiny.seq": "reads",
    "oracle/koma_v1.5_spiral.seq": "reads",
    "oracle/koma_v1.5_unknown_ext.seq": "reads",
    "oracle/pulseq_epi_rs.seq": "reads",
    "oracle/pulseq_fid.seq": "reads",
    "oracle/pulseq_make_radial.seq": "reads",
    "oracle/pulseq_seq4.seq": "reads",
    "oracle/pypulseq_seq6.seq": "reads",
    "oracle/pypulseq_simple_mprage140.seq": "layer1.gradient-ends",
    "oracle/pypulseq_simple_mprage150.seq": "reads",
    "undefined/rf_time_id_minus_1.seq": "ref.unresolved",
    "undefined/shape_decompress_longer.seq": "shape.length",
    "undefined/version_last.seq": "reads",
    "valid_1_4_0.seq": "reads",
    "valid_1_4_1.seq": "reads",
    "valid_1_5_0.seq": "reads",
    "valid_1_5_0_extensions_of_1_5_1.seq": "reads",
    "valid_1_5_1.seq": "reads",
    "valid_1_5_1_rotation_not_played.seq": "reads",
    "valid_arbitrary_gradient_4us_raster.seq": "definitions.raster-commensurate",
    "valid_arbitrary_gradient_5us_raster.seq": "reads",
    "valid_comment_in_shape.seq": "reads",
    "valid_comments_between_sections.seq": "reads",
    "valid_crlf.seq": "reads",
    "valid_label_unknown.seq": "reads",
    "valid_last_section_no_blank.seq": "reads",
    "valid_no_signature.seq": "reads",
    "valid_rf_time_shapes.seq": "reads",
    "valid_signature_mismatch.seq": "reads",
    "valid_soft_delay_fraction.seq": "reads",
}

# The codes of `spec.RULES` that no fixture gives, each with the reason. (The rules that a fixture
# gives only in part are in `test_a_partial_rule_...`.)
NO_FIXTURE: dict[str, str] = {
    "rotation.zero": "no fixture has a quaternion of norm 0 (`test_rotation_quaternions_are_"
    "normalized_and_a_quaternion_of_norm_0_is_rejected` writes one)",
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


def _text(name):
    return (SEQFILES / name).read_text()


def violations_of(path):
    with pytest.raises(SeqFileError) as info:
        read_seqfile(path)
    return info.value


def codes_of(path):
    return {v.rule for v in violations_of(path).violations}


def verdict(path):
    """ "reads", "NotSupported", or the codes of the `SeqFileError`, joined by ","."""
    try:
        read_seqfile(path)
    except NotSupported:
        return "NotSupported"
    except SeqFileError as error:
        return ",".join(sorted(error.codes))
    return "reads"


def carries_choice(violation):
    """Whether the message of `violation` says that the specification does not state its rule."""
    return CHOICE in violation.message


def same_values(a, b):
    """Whether two models are equal but for their definitions (a file has its own `Name`), their
    signature (the hash changes with the file) and their records (which have line numbers)."""
    return dataclasses.replace(
        a, definitions={}, signature=None, records=()
    ) == dataclasses.replace(b, definitions={}, signature=None, records=())


# ---- The verdict on each fixture ----


@pytest.mark.parametrize("name", sorted(VERDICTS))
def test_each_fixture_gives_its_verdict(name):
    """The table `VERDICTS`: a file reads, or `spec` rejects it with exactly the code of the
    table and no other (the codes of `bad_many.seq`), or the version is not supported."""
    path = SEQFILES / name
    assert verdict(path) == VERDICTS[name]
    if VERDICTS[name] not in ("reads", "NotSupported"):
        error = violations_of(path)
        assert not error.omitted
        assert error.interpreter == "spec"
        assert all(isinstance(v, Violation) and v.message for v in error.violations)
        assert str(path) in str(error)


def test_the_verdict_table_names_every_fixture():
    files = {p.relative_to(SEQFILES).as_posix() for p in SEQFILES.rglob("*.seq")}
    assert files == set(VERDICTS)


def test_each_rule_that_a_fixture_can_give_has_a_fixture():
    given = {
        code
        for value in VERDICTS.values()
        if value not in ("reads", "NotSupported")
        for code in value.split(",")
    }
    assert given <= set(RULES)
    assert set(NO_FIXTURE) <= set(RULES)
    assert not set(NO_FIXTURE) & given
    assert given | set(NO_FIXTURE) == set(RULES)
    assert all(NO_FIXTURE.values())


@pytest.mark.parametrize(
    ("name", "section", "line"),
    [
        ("bad_version_missing.seq", None, None),
        ("bad_definitions_raster_missing.seq", "DEFINITIONS", None),
        ("bad_definitions_raster_invalid.seq", "DEFINITIONS", 13),
        ("valid_arbitrary_gradient_4us_raster.seq", "DEFINITIONS", 12),
        ("bad_syntax_line.seq", None, 1),
        ("bad_syntax_encoding.seq", None, 31),
        ("bad_syntax_columns.seq", "BLOCKS", 21),
        ("bad_syntax_integer.seq", "BLOCKS", 21),
        ("bad_syntax_number.seq", "TRAP", 51),
        ("bad_syntax_negative.seq", "TRAP", 51),
        ("bad_syntax_use.seq", "RF", 35),
        ("bad_syntax_shape.seq", "SHAPES", 148),
        ("bad_syntax_shape_no_blank_line.seq", "SHAPES", 147),
        ("bad_syntax_shape_end.seq", "SHAPES", 178),
        ("bad_section_duplicate.seq", "TRAP", 53),
        ("bad_section_duplicate_signature.seq", "SIGNATURE", 197),
        ("bad_section_duplicate_extension.seq", "extension LABELSET", 83),
        ("bad_id_unique_block.seq", "BLOCKS", 23),
        ("bad_id_positive.seq", "RF", 36),
        ("bad_id_gradient_unique.seq", "TRAP", 52),
        ("bad_id_unique.seq", "ADC", 58),
        ("bad_ref_block_rf.seq", "BLOCKS", 21),
        ("bad_ref_shape.seq", "RF", 35),
        ("bad_ref_extension_object.seq", "EXTENSIONS", 64),
        ("bad_ref_extension_type.seq", "EXTENSIONS", 65),
        ("bad_blocks_empty.seq", "BLOCKS", None),
        ("bad_block_event_too_long_rf.seq", "BLOCKS", 21),
        ("bad_block_event_too_long_adc.seq", "BLOCKS", 22),
        ("bad_block_event_too_long_trigger.seq", "BLOCKS", 27),
        ("bad_raster_adc_dwell.seq", "ADC", 57),
        ("bad_raster_adc_delay.seq", "ADC", 57),
        ("bad_raster_rf_delay.seq", "RF", 35),
        ("bad_raster_gradient_delay.seq", "GRADIENTS", 41),
        ("bad_raster_gradient_end.seq", "GRADIENTS", 44),
        ("bad_raster_gradient_ramp.seq", "TRAP", 51),
        ("bad_raster_gradient_flat.seq", "TRAP", 51),
        ("bad_raster_gradient_vertex.seq", "SHAPES", 156),
        ("bad_gradient_nonzero_start_delay.seq", "GRADIENTS", 43),
        ("bad_gradient_nonzero_end_align.seq", "BLOCKS", 23),
        ("bad_shape_length.seq", "SHAPES", 178),
        ("bad_shape_range.seq", "SHAPES", 122),
        ("bad_shape_empty.seq", "SHAPES", 192),
        ("bad_shape_event_length.seq", "RF", 35),
        ("bad_shape_adc_phase_length.seq", "ADC", 58),
        ("bad_shape_time_order.seq", "SHAPES", 192),
        ("bad_shape_oversampled_length.seq", "GRADIENTS", 45),
        ("bad_extension_required_unknown.seq", "DEFINITIONS", 16),
        ("bad_layer1_gradient_ends.seq", "GRADIENTS", 30),
        ("bad_signature_invalid.seq", "SIGNATURE", 193),
    ],
)
def test_violation_names_the_section_and_the_line(name, section, line):
    """A violation of one rule names its section and the line of the row (or of the `shape_id`
    line of a shape, or of the header of a section) that breaks it."""
    (violation, *rest) = violations_of(SEQFILES / name).violations
    assert not rest
    assert (violation.section, violation.line) == (section, line)
    text = (SEQFILES / name).read_bytes().split(b"\n")
    if line is not None and section == "SHAPES":
        assert text[line - 1].startswith(b"shape_id")
    elif line is not None and section not in (None, "DEFINITIONS"):
        assert text[line - 1].strip()  # the line is a row of the file, not a comment


# ---- The basis of each rule ----


def test_each_rule_has_a_text_and_a_source():
    for code, rule in RULES.items():
        assert rule.text and rule.source, code
        assert rule.choice is None or rule.choice.strip(), code
        assert not rule.partial or rule.choice, code  # a partial rule has a choice


def test_the_message_of_a_violation_has_the_choice_of_its_rule_when_the_rule_is_one():
    """Every violation of every rejected fixture: the message ends with the choice of its rule
    when the rule is wholly the package's choice, and has no choice when the specification states
    the rule. A partial rule is in the next test."""
    seen = set()
    for name, expected in VERDICTS.items():
        if expected in ("reads", "NotSupported"):
            continue
        for violation in violations_of(SEQFILES / name).violations:
            rule = RULES[violation.rule]
            seen.add(violation.rule)
            if rule.partial:
                continue
            if rule.choice is None:
                assert not carries_choice(violation), (name, violation)
            else:
                assert violation.message.endswith(f"{CHOICE}{rule.choice})"), (name, violation)
    assert any(RULES[code].choice and not RULES[code].partial for code in seen)
    assert any(RULES[code].choice is None for code in seen)


@pytest.mark.parametrize(
    ("name", "rule", "choice"),
    [
        ("bad_syntax_number.seq", "syntax.number", True),  # nan in a float column
        ("bad_id_unique_block.seq", "id.unique", True),  # a block ID
        ("bad_id_unique.seq", "id.unique", False),  # an ADC ID
        ("bad_syntax_shape_no_blank_line.seq", "syntax.shape", True),  # no blank line before
        ("bad_syntax_shape_end.seq", "syntax.shape", True),  # no blank line after
        ("bad_syntax_shape.seq", "syntax.shape", False),  # no `num_samples` line
    ],
)
def test_a_partial_rule_carries_the_choice_for_its_choice_conditions_only(name, rule, choice):
    """`syntax.number`, `id.unique` and `syntax.shape` are stated in part: only the violations
    of the conditions that the specification does not state have the choice in their message."""
    assert RULES[rule].partial
    (violation,) = violations_of(SEQFILES / name).violations
    assert violation.rule == rule
    assert carries_choice(violation) is choice
    if choice:
        assert violation.message.endswith(f"{CHOICE}{RULES[rule].choice})")


def test_a_float_column_that_does_not_hold_a_number_has_no_choice_and_nan_has_one(tmp_path):
    """`syntax.number`: a text that is not a number is a violation of the type of the column
    (spec:176, the tables); NaN and infinity are numbers that the specification does not rule on
    (the package's choice)."""
    text = _text("valid_no_signature.seq")
    amplitude = "1 1000000 100 200 100 100"
    for value, choice in (("1,5", False), ("abc", False), ("nan", True), ("-inf", True)):
        path = _write(tmp_path, text.replace(amplitude, f"1 {value} 100 200 100 100"), "n.seq")
        (violation,) = violations_of(path).violations
        assert (violation.rule, carries_choice(violation)) == ("syntax.number", choice), value


# ---- Several violations ----


def test_a_file_with_several_violations_gives_all_of_them_in_file_order():
    error = violations_of(SEQFILES / "bad_many.seq")
    assert [v.rule for v in error.violations] == [
        "extension.required-unknown",
        "ref.unresolved",
        "raster.adc-dwell",
    ]
    lines = [v.line for v in error.violations]
    assert lines == sorted(lines)
    assert all(v.section and v.line for v in error.violations)


def test_a_file_with_violations_in_five_sections_gives_each_with_its_section_and_line(tmp_path):
    """Not only the first violation: one in each of five sections, in the order of the file, each
    with its section and the line of its row (of the `shape_id` line for the shape)."""
    text = _text("valid_no_signature.seq")
    edits = [
        (
            "RequiredExtensions ROTATIONS",
            "RequiredExtensions ROTATIONS FOO",
            "DEFINITIONS",
            "extension.required-unknown",
        ),
        ("2  50  0  1  2  0  1  0", "2  50  0  9  2  0  1  0", "BLOCKS", "ref.unresolved"),
        ("1 1000000 100 200 100 100", "1 1000000 100 200 100 -10", "TRAP", "syntax.negative"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 25050 100 0 0 0 0 0", "ADC", "raster.adc-dwell"),
        ("shape_id 3\nnum_samples 10", "shape_id 3\nnum_samples 11", "SHAPES", "shape.length"),
    ]
    for old, new, _, _ in edits:
        assert text.count(old) == 1
        text = text.replace(old, new)
    path = _write(tmp_path, text, "five.seq")
    lines = text.split("\n")
    expected = []
    for _, new, section, rule in edits:
        expected.append((rule, section, lines.index(new.split("\n")[0]) + 1))
    error = violations_of(path)
    assert [(v.rule, v.section, v.line) for v in error.violations] == sorted(
        expected, key=lambda e: e[2]
    )


@pytest.mark.parametrize(
    ("name", "lines"),
    [
        ("bad_extension_per_block.seq", [25, 29]),
        ("bad_version_invalid.seq", [4, 6]),
        ("undefined/shape_decompress_longer.seq", [112, 119]),
    ],
)
def test_each_violation_of_a_rule_is_in_the_error(name, lines):
    """A rule that a file breaks twice gives two violations, not one."""
    error = violations_of(SEQFILES / name)
    assert sorted(v.line for v in error.violations) == lines
    assert len({v.rule for v in error.violations}) == 1


def test_an_error_lists_20_locations_of_a_rule_and_counts_the_rest(tmp_path):
    text = _text("valid_no_signature.seq")
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


# ---- The valid fixtures ----


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("valid_1_4_0.seq", (1, 4, 0)),
        ("valid_1_4_1.seq", (1, 4, 1)),
        ("valid_1_5_0.seq", (1, 5, 0)),
        ("valid_1_5_1.seq", (1, 5, 1)),
        ("valid_1_5_0_extensions_of_1_5_1.seq", (1, 5, 0)),
        ("valid_crlf.seq", (1, 5, 1)),
        ("valid_comments_between_sections.seq", (1, 5, 1)),
        ("valid_comment_in_shape.seq", (1, 5, 1)),
        ("valid_no_signature.seq", (1, 5, 1)),
        ("valid_signature_mismatch.seq", (1, 5, 1)),
        ("valid_arbitrary_gradient_5us_raster.seq", (1, 5, 1)),
        ("valid_1_5_1_rotation_not_played.seq", (1, 5, 1)),
        ("valid_last_section_no_blank.seq", (1, 5, 1)),
        ("valid_label_unknown.seq", (1, 5, 1)),
        ("valid_soft_delay_fraction.seq", (1, 5, 1)),
        ("valid_rf_time_shapes.seq", (1, 5, 1)),
    ],
)
def test_valid_fixture_loads_with_its_version(name, version):
    data = read_seqfile(SEQFILES / name)
    assert isinstance(data, SequenceData)
    assert data.version == version
    assert data.origin == "file"
    assert data.interpreter == Spec()


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
    quaternion = np.array([0.92388, 0.0, 0.0, 0.382683])
    (rotation,) = ext.rotations.tolist()
    assert rotation == pytest.approx((1, *(quaternion / np.linalg.norm(quaternion))), rel=1e-12)
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
    """D4.2: a 1.4 file has no `center` (spec:350 adds it to the 1.5 table), so it is NaN; the
    other columns that the 1.4 table lacks have the values that the format defines. D4.5: the
    `first` and `last` of a gradient with a time shape are the amplitude times its first and
    last sample (the package's choice, see `test_a_1_4_gradient_...`)."""
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
    signature = read_seqfile(SEQFILES / "valid_signature_mismatch.seq").signature
    assert (signature.type, signature.hash, signature.matches) == ("md5", "0" * 32, False)
    assert read_seqfile(SEQFILES / "valid_no_signature.seq").signature is None


def _signature_variants():
    """(name, the bytes of a file up to the line `[SIGNATURE]`, the bytes that the scanner's
    reader hashes, the line end of the signature section). Each has a blank line after the last
    shape (D3.11). The scanner's reader hashes each line with its line end, holds back a line that
    is only a line end, and drops it when the next line is `[SIGNATURE]`; `spec` hashes every
    byte before the `\\n` before `[SIGNATURE]`."""
    text = _text("valid_no_signature.seq").rstrip("\n")
    lf, crlf = text.encode(), text.replace("\n", "\r\n").encode()
    return [
        ("lf-one-empty-line", lf + b"\n\n", lf + b"\n", b"\n"),
        ("lf-two-empty-lines", lf + b"\n\n\n", lf + b"\n\n", b"\n"),
        ("lf-spaces-on-the-line", lf + b"\n  \n", lf + b"\n  \n", b"\n"),
        ("crlf-one-empty-line", crlf + b"\r\n\r\n", crlf + b"\r\n", b"\r\n"),
        ("lf-file-with-a-crlf-empty-line", lf + b"\n\r\n", lf + b"\n", b"\n"),
        ("crlf-file-with-an-lf-empty-line", crlf + b"\r\n\n", crlf + b"\r\n", b"\r\n"),
    ]


@pytest.mark.parametrize(
    ("before", "scanner", "newline"),
    [v[1:] for v in _signature_variants()],
    ids=[v[0] for v in _signature_variants()],
)
def test_signature_matches_hashes_the_bytes_before_the_newline_that_precedes_the_signature(
    tmp_path, before, scanner, newline
):
    """spec:223: "The new line character preceding the keyword [SIGNATURE] is part of the
    signature and needs to be stripped away": the hash covers every byte before the `\\n` that
    precedes the first `[SIGNATURE]` line (so a `\\r` stays). The hash of the bytes that the
    scanner's reader hashes matches only where the two rules hash the same bytes."""
    hashed = before[:-1]
    assert before.endswith(b"\n")
    digest = hashlib.md5(hashed).hexdigest().encode()
    signature = b"[SIGNATURE]" + newline + b"Type md5" + newline + b"Hash " + digest + newline
    path = tmp_path / "signed.seq"
    path.write_bytes(before + signature)
    assert read_seqfile(path).signature.matches is True
    other = hashlib.md5(scanner).hexdigest().encode()
    path.write_bytes(before + signature.replace(digest, other))
    assert read_seqfile(path).signature.matches is (scanner == hashed)


def test_read_seqfile_takes_a_str_or_a_path_and_raises_oserror_for_a_missing_file(tmp_path):
    path = SEQFILES / "valid_1_4_0.seq"
    assert read_seqfile(str(path)) == read_seqfile(path)
    with pytest.raises(FileNotFoundError):
        read_seqfile(tmp_path / "missing.seq")


def test_the_default_interpreter_is_spec():
    path = SEQFILES / "valid_1_5_1.seq"
    data = read_seqfile(path)
    assert data.interpreter == Spec()
    assert str(data.interpreter) == "spec"
    assert data == read_seqfile(path, "spec") == read_spec(path)


# ---- The rows of section 6 of the plan: the format and its structure ----


@pytest.mark.parametrize(
    ("old", "new", "section"),
    [
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 100 0 0 0 0", "RF"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 100 0 0 0 0 e 7", "RF"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 3 0", "GRADIENTS"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 3 0 100 1", "GRADIENTS"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 25000 100 0 0 0 0", "ADC"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 25000 100 0 0 0 0 0 0", "ADC"),
        ("1 1000000 100 200 100 100", "1 1000000 100 200 100", "TRAP"),
    ],
    ids=[
        "rf-11",
        "rf-13",
        "gradient-6",
        "gradient-8",
        "adc-8",
        "adc-10",
        "trap-5",
    ],
)
def test_a_row_with_another_number_of_fields_than_its_table_is_syntax_columns(
    tmp_path, old, new, section
):
    """D1.2, D4.2: the tables of the specification have 12 fields for an RF event (spec:341-359), 7
    for an arbitrary gradient (spec:386-399), 6 for a trapezoid (spec:379-381) and 9 for an ADC
    event (spec:431-445). The prose before each (7, 4 and 6 numbers, spec:334-336, spec:375,
    spec:424) disagrees with them and with the examples; `spec` follows the tables and the
    examples, as `cpp-siemens` does."""
    text = _text("valid_no_signature.seq")
    assert text.count(old) == 1
    error = violations_of(_write(tmp_path, text.replace(old, new), "fields.seq"))
    (violation,) = error.violations
    assert (violation.rule, violation.section) == ("syntax.columns", section)


def test_a_1_4_file_has_the_rows_of_the_1_4_tables_and_not_those_of_1_5(tmp_path):
    """D1.2, D4.2: a 1.4 file has 8 fields in an RF row, 5 in a gradient row and 6 in an ADC row
    (the 1.4.x tables have no `center`, `freq_ppm`, `phase_ppm`, `use`, `first`, `last` and
    `phase_shape_id`); a row of the 1.5 layout in a 1.4 file is `syntax.columns`."""
    text = _text("valid_1_4_1.seq")
    read_seqfile(SEQFILES / "valid_1_4_1.seq")
    rf = "1 1000 1 2 0 100 0 0"
    assert text.count(rf) == 1
    path = _write(tmp_path, text.replace(rf, "1 1000 1 2 0 50 100 0 0 0 0 e"), "rf.seq")
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("syntax.columns", "RF")
    # And a row of the 1.4 layout in a 1.5 file.
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("2 500000 0 0 3 0 100", "2 500000 3 0 100"), "grad.seq")
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("syntax.columns", "GRADIENTS")


def test_a_file_without_a_version_section_is_version_missing(tmp_path):
    """D1.1, spec:201: "It is recommended to reject Pulseq files without [VERSION] section"; `spec`
    rejects it (section 6 of the plan)."""
    (violation,) = violations_of(SEQFILES / "bad_version_missing.seq").violations
    assert (violation.rule, violation.section, violation.line) == ("version.missing", None, None)
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("[VERSION]\nmajor 1\nminor 5\nrevision 1\n", ""), "v.seq")
    assert codes_of(path) == {"version.missing"}


@pytest.mark.parametrize(
    ("name", "version"),
    [("bad_version_unsupported_1_3.seq", "1.3"), ("bad_version_unsupported_1_6.seq", "1.6")],
)
def test_a_version_outside_1_4_to_1_5_is_not_supported(name, version):
    """D4.1: the specification has no rule for a version that the reader does not know. Q1 of the
    plan: every interpreter raises `NotSupported` for a version outside 1.4.0 to 1.5.x."""
    with pytest.raises(NotSupported, match="outside 1.4.0 to 1.5.x") as caught:
        read_seqfile(SEQFILES / name)
    assert isinstance(caught.value, NotImplementedError)
    assert version in str(caught.value)


@pytest.mark.parametrize("revision", [0, 9])
def test_the_versions_1_5_0_to_1_5_x_are_read(tmp_path, revision):
    """D4.1: the boundaries of `NotSupported`: a version from 1.4.0 up to, not including, 1.6.0
    is read (the fixtures `bad_version_unsupported_1_3.seq` and `..._1_6.seq` are outside)."""
    text = _text("valid_no_signature.seq").replace("revision 1", f"revision {revision}")
    data = read_seqfile(_write(tmp_path, text, "r.seq"))
    assert data.version == (1, 5, revision)


def test_a_version_line_that_is_not_an_integer_is_version_invalid():
    """spec:193-198: the three lines `major`, `minor` and `revision` hold integers, so
    `minor 5.0` is not an integer and is rejected (as a fraction in an integer column)."""
    error = violations_of(SEQFILES / "bad_version_invalid.seq")
    assert {v.rule for v in error.violations} == {"version.invalid"}
    assert 6 in {v.line for v in error.violations}  # the line `minor 5.0`
    assert (SEQFILES / "bad_version_invalid.seq").read_text().split("\n")[5] == "minor 5.0"


def test_a_file_may_have_its_sections_in_any_order(tmp_path):
    """D2.1, spec:213: the specification says that a file "may end with" `[SIGNATURE]` and is
    silent on the order of the other sections; `spec` takes any order (`[VERSION]` last in
    `undefined/version_last.seq`, `[SHAPES]` first below)."""
    plain = read_seqfile(SEQFILES / "valid_no_signature.seq")
    last = read_seqfile(SEQFILES / "undefined" / "version_last.seq")
    assert last.version == (1, 5, 1)
    assert same_values(last, plain)
    parts = re.split(r"(?m)^(?=\[|extension )", _text("valid_no_signature.seq"))
    assert parts[-1].startswith("[SHAPES]")
    shuffled = "".join([parts[0], parts[-1], *parts[1:-1]])
    assert same_values(read_seqfile(_write(tmp_path, shuffled, "order.seq")), plain)


def test_a_comment_or_blank_line_in_a_table_is_skipped_and_the_rows_after_it_are_read():
    """D2.5, spec:171 ("Comments are specified by a line starting with a hash"): `spec` skips a
    blank line and a `#` line anywhere, so the rows after one are rows of the table (the package's
    choice: the specification is silent on a blank or comment line inside a section, except in
    a shape, D3.11). `cpp-siemens` does not read such a file as `spec` does."""
    plain = read_seqfile(SEQFILES / "valid_no_signature.seq")
    assert same_values(read_seqfile(SEQFILES / "bad_syntax_line_after_comment.seq"), plain)


@pytest.mark.parametrize(
    ("after", "line"),
    [
        ("1  30  1  0  0  0  0  1\n", "# a comment\n"),
        ("1  30  1  0  0  0  0  1\n", "\n"),
        ("1  30  1  0  0  0  0  1\n", "   \n"),
        ("2 500000 0 0 3 0 100\n", "# a comment\n"),
        ("1 1 1 2\n", "# a comment\n"),
        ("1 1 1 2\n", "\n"),
        ("1 0 LIN\n", "# a comment\n"),
        ("1 1 2 0 10\n", "\n"),
    ],
    ids=[
        "comment-blocks",
        "blank-blocks",
        "spaces-blocks",
        "comment-gradients",
        "comment-list",
        "blank-ext",
        "comment-labelset",
        "blank-triggers",
    ],
)
def test_the_rows_after_a_comment_or_blank_line_of_any_section_are_read(tmp_path, after, line):
    """D2.5: as above, in a table of each kind."""
    text = _text("valid_no_signature.seq")
    assert text.count(after) == 1
    path = _write(tmp_path, text.replace(after, after + line), "split.seq")
    assert same_values(read_seqfile(path), read_seqfile(SEQFILES / "valid_no_signature.seq"))


def test_comments_and_blank_lines_are_skipped_after_the_header_of_any_section(tmp_path):
    """D2.5: a comment or blank line right after a header, also in `[VERSION]`, `[DEFINITIONS]`
    and `[SIGNATURE]` (the package's choice, as above)."""
    text = _text("valid_1_5_1.seq")
    expected = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    for header in ("[VERSION]", "[DEFINITIONS]", "[TRAP]", "[SIGNATURE]", "extension DELAYS 4"):
        assert text.count(header + "\n") == 1
        path = _write(tmp_path, text.replace(header + "\n", header + "\n# a\n\n# b\n"), "c.seq")
        assert same_values(read_seqfile(path), expected), header
    # And inside the signature, after its first line: the signature is read to its end.
    path = _write(tmp_path, text.replace("Type md5\n", "Type md5\n# a\n"), "s.seq")
    assert read_seqfile(path).signature.hash == expected.signature.hash


def test_a_comment_in_a_shape_is_skipped_and_a_blank_line_ends_it(tmp_path):
    """D2.5, D3.11: a `#` line among the samples of a shape, and between its `shape_id` and
    `num_samples` lines, is a comment (spec:171) and is skipped
    (`valid_comment_in_shape.seq` has the shapes of `valid_1_5_1.seq`). A blank line ends the
    shape (spec:602), so the samples after it are outside a shape."""
    data = read_seqfile(SEQFILES / "valid_comment_in_shape.seq")
    plain = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert data.shapes == plain.shapes
    assert same_values(data, plain)
    text = _text("valid_no_signature.seq")
    cut = text.replace("0.3\n0.4\n0.5\n", "0.3\n\n0.4\n0.5\n")
    assert codes_of(_write(tmp_path, cut, "cut.seq")) == {"syntax.shape", "shape.length"}


def test_a_blank_line_between_shape_id_and_num_samples_ends_the_shape(tmp_path):
    """D2.5, D3.11, spec:602 ("The end of the shape definition is declared with a blank line"): a
    blank line right after `shape_id` ends the shape, so it has no `num_samples` line
    (`syntax.shape`, which the specification states: no choice in the message) and its other lines
    are outside a shape. A `#` line there is skipped (the test above)."""
    text = _text("valid_no_signature.seq")
    path = _write(
        tmp_path,
        text.replace("shape_id 5\nnum_samples 5\n", "shape_id 5\n\nnum_samples 5\n"),
        "b.seq",
    )
    error = violations_of(path)
    assert {v.rule for v in error.violations} == {"syntax.shape"}
    first = error.violations[0]
    assert "no `num_samples" in first.message
    assert not carries_choice(first)
    assert path.read_text().split("\n")[first.line - 1] == "shape_id 5"


def test_a_data_line_before_the_first_header_is_syntax_line():
    """D3.2: the one place where a line outside a table is rejected: a data line before the first
    section header (the package's choice: the specification has no line outside a section, and no
    writer writes one)."""
    (violation,) = violations_of(SEQFILES / "bad_syntax_line.seq").violations
    assert (violation.rule, violation.section, violation.line) == ("syntax.line", None, 1)
    assert carries_choice(violation)


def test_a_shape_with_no_blank_line_after_it_is_syntax_shape(tmp_path):
    """D3.11, spec:602: the end of a shape is a blank line. A shape followed by the next
    `shape_id` line (`bad_syntax_shape_no_blank_line.seq`) or by the end of its section
    (`bad_syntax_shape_end.seq`) has none: `spec` rejects it (the package's choice: the
    specification does not say what such a shape is, and writers always write the blank line;
    the message says so). `cpp-siemens` rejects the first file with `ub.shape-missing`."""
    (violation,) = violations_of(SEQFILES / "bad_syntax_shape_no_blank_line.seq").violations
    assert (violation.rule, violation.line, carries_choice(violation)) == (
        "syntax.shape",
        147,
        True,
    )
    assert "before it" in violation.message
    (violation,) = violations_of(SEQFILES / "bad_syntax_shape_end.seq").violations
    assert (violation.rule, violation.line, carries_choice(violation)) == (
        "syntax.shape",
        178,
        True,
    )
    assert "after it" in violation.message


def test_a_shape_ends_only_at_a_blank_line(tmp_path):
    """D3.11: every `shape_id` line right after the samples of a shape, with no blank line, is
    `syntax.shape` at that line; the shapes are still read, so there is no second violation."""
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("\n\nshape_id", "\nshape_id"), "tight.seq")
    error = violations_of(path)
    assert {v.rule for v in error.violations} == {"syntax.shape"}
    assert len(error.violations) == text.count("\n\nshape_id") - 1  # not the first shape
    lines = path.read_text().split("\n")
    assert all(lines[v.line - 1].startswith("shape_id") for v in error.violations)
    assert all(carries_choice(v) for v in error.violations)


def test_a_section_that_the_format_does_not_have_is_ignored(tmp_path):
    """D2.4: the specification lists its sections and has no rule for another one; `spec` ignores
    it, whatever its lines are (the user's choice, section 6 of the plan: the C++ reader ignores
    it too, MATLAB Pulseq and pypulseq reject it)."""
    plain = read_seqfile(SEQFILES / "valid_no_signature.seq")
    assert same_values(read_seqfile(SEQFILES / "bad_section_unknown.seq"), plain)
    text = _text("valid_no_signature.seq")
    junk = "\n[FOO]\n1 2 3\nnot a row at all\n\n"
    path = _write(tmp_path, text.replace("\n[SHAPES]", junk + "[SHAPES]"), "foo.seq")
    assert same_values(read_seqfile(path), plain)


def test_a_delays_section_is_ignored(tmp_path):
    """1.4.0 removed `[DELAYS]` (spec:114) and the binary format lists it as legacy: "Current
    readers ignore this section for compatibility with old files" (spec:772, spec:743). `spec`
    ignores it in the text format too (the user's choice, section 6 of the plan); `extension
    DELAYS` (soft delays) is another thing."""
    plain = read_seqfile(SEQFILES / "valid_no_signature.seq")
    data = read_seqfile(SEQFILES / "bad_section_delays.seq")
    assert same_values(data, plain)
    assert len(data.extensions.soft_delays) == 1  # `extension DELAYS` is read


def test_a_section_that_appears_twice_is_section_duplicate_and_only_the_first_is_read():
    """D3.3: the specification is silent on a section that appears twice, the readers disagree (the
    C++ reader keeps the last copy; MATLAB Pulseq and pypulseq add the copies of some sections and
    keep the last of others), and no writer writes one: `spec` rejects it with
    `section.duplicate` at the header of the second copy (the user's choice, 2026-10-13; the
    message says so). `bad_section_duplicate.seq` has a second `[TRAP]` with the ID of the first,
    and that is not also `id.unique`: only the first copy is read."""
    (violation,) = violations_of(SEQFILES / "bad_section_duplicate.seq").violations
    assert violation.rule == "section.duplicate"
    assert (violation.section, violation.line) == ("TRAP", 53)
    assert carries_choice(violation)
    lines = _text("bad_section_duplicate.seq").split("\n")
    assert [i + 1 for i, line in enumerate(lines) if line == "[TRAP]"][1] == violation.line


@pytest.mark.parametrize(
    ("old", "new", "section"),
    [
        ("[BLOCKS]\n", "[BLOCKS]\n1  30  1  0  0  0  0  1\n\n[BLOCKS]\n", "BLOCKS"),
        ("[VERSION]\n", "[VERSION]\nmajor 1\n\n[VERSION]\n", "VERSION"),
        ("[DEFINITIONS]\n", "[DEFINITIONS]\nName first\n\n[DEFINITIONS]\n", "DEFINITIONS"),
        ("[ADC]\n", "[ADC]\n\n[ADC]\n", "ADC"),
        ("[SHAPES]\n", "[SHAPES]\n\n[SHAPES]\n", "SHAPES"),
        (
            "extension TRIGGERS 3\n",
            "extension TRIGGERS 3\n\nextension TRIGGERS 3\n",
            "extension TRIGGERS",
        ),
        (
            "extension TRIGGERS 3\n",
            "extension TRIGGERS 3\n\nextension TRIGGERS 9\n",
            "extension TRIGGERS",
        ),
    ],
    ids=[
        "blocks",
        "version-key",
        "definitions",
        "adc-empty",
        "shapes-empty",
        "extension-same-type",
        "extension-other-type",
    ],
)
def test_any_named_section_and_any_extension_that_appears_twice_is_section_duplicate(
    tmp_path, old, new, section
):
    """D3.3: the rejection is for every named section (`[VERSION]` included, also when the second
    copy holds one key of its own) and for two `extension` sections with one STRING_ID, with the
    same type ID or another. The violation is at the second header, with the choice in the
    message. The test inserts the second header in a valid fixture; the other violations that
    the changed file has are not looked at."""
    text = _text("valid_no_signature.seq")
    assert text.count(old) == 1
    path = _write(tmp_path, text.replace(old, new), "twice.seq")
    found = [v for v in violations_of(path).violations if v.rule == "section.duplicate"]
    (violation,) = found
    assert violation.section == section
    assert carries_choice(violation)
    header = new.split("\n")[-2] if new.endswith("\n") else new
    assert path.read_text().split("\n")[violation.line - 1] == header


def test_a_second_signature_section_and_an_extension_with_two_types_are_section_duplicate():
    """D3.3: a second `[SIGNATURE]` section (`bad_section_duplicate_signature.seq`) and an
    `extension` STRING_ID with two type IDs (`bad_section_duplicate_extension.seq`) give
    `section.duplicate` at the second header, with the choice in the message."""
    for name, section, line in (
        ("bad_section_duplicate_signature.seq", "SIGNATURE", 197),
        ("bad_section_duplicate_extension.seq", "extension LABELSET", 83),
    ):
        (violation,) = violations_of(SEQFILES / name).violations
        assert (violation.rule, violation.section, violation.line) == (
            "section.duplicate",
            section,
            line,
        )
        assert carries_choice(violation)


def test_a_version_key_repeated_in_one_section_is_version_invalid(tmp_path):
    """spec:193-198: `[VERSION]` has one line for each of `major`, `minor` and `revision`;
    a key repeated inside one copy of the section is `version.invalid` (a key in a second copy of
    the section is `section.duplicate`)."""
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("revision 1\n", "revision 1\nmajor 1\n"), "v.seq")
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("version.invalid", "VERSION")
    assert path.read_text().split("\n")[violation.line - 1] == "major 1"


def test_a_last_section_with_no_blank_line_after_it_is_read():
    """D2.2: the specification is silent on a blank line after a section, and on the end of the file
    (it declares the end of a shape with a blank line, spec:602). `valid_last_section_no_blank.seq`
    ends with `[TRAP]` and no line end after its row; `spec` reads it."""
    data = read_seqfile(SEQFILES / "valid_last_section_no_blank.seq")
    plain = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert not (SEQFILES / "valid_last_section_no_blank.seq").read_bytes().endswith(b"\n")
    assert data.trap.tolist() == plain.trap.tolist()
    assert data.blocks.tolist() == plain.blocks.tolist()


# ---- The rows of section 6: definitions and the syntax of values ----


@pytest.mark.parametrize("value", ["0", "-1e-6", "nan", "inf", "abc", "1e-6 2e-6", ""])
def test_a_raster_that_is_not_one_finite_number_above_0_is_rejected(tmp_path, value):
    """spec:267-276: the four rasters are required, in seconds. A raster that is not one
    finite number above 0 has no meaning as a raster time: `definitions.raster-invalid`."""
    text = _text("valid_no_signature.seq")
    old = "RadiofrequencyRasterTime 1e-06"
    path = _write(tmp_path, text.replace(old, f"RadiofrequencyRasterTime {value}"), "r.seq")
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("definitions.raster-invalid", "DEFINITIONS")
    assert path.read_text().split("\n")[violation.line - 1].startswith("RadiofrequencyRasterTime")


def test_a_missing_raster_is_definitions_raster_missing(tmp_path):
    """spec:267-276: each of the four rasters is "required" from 1.4.0."""
    text = _text("valid_no_signature.seq")
    for key in (
        "GradientRasterTime",
        "RadiofrequencyRasterTime",
        "AdcRasterTime",
        "BlockDurationRaster",
    ):
        path = _write(tmp_path, re.sub(rf"(?m)^{key} .*\n", "", text), "m.seq")
        (violation,) = violations_of(path).violations
        assert violation.rule == "definitions.raster-missing"
        assert key in violation.message


def test_a_definition_that_appears_twice_has_its_last_value(tmp_path):
    """D2.6: the specification is silent ("a list of user-specified key/value pairs", spec:240);
    `spec` takes the last definition of a key (the package's choice, as the C++ reader, MATLAB
    Pulseq and pypulseq do). `bad_definitions_duplicate.seq` has `Name` twice."""
    data = read_seqfile(SEQFILES / "bad_definitions_duplicate.seq")
    assert data.definitions["Name"] == ("again",)
    text = _text("valid_no_signature.seq")
    path = _write(
        tmp_path,
        text.replace(
            "BlockDurationRaster 1e-05\n", "BlockDurationRaster 1e-04\nBlockDurationRaster 1e-05\n"
        ),
        "d.seq",
    )
    assert read_seqfile(path).rasters.block_duration == 1e-5


def test_a_definition_and_a_signature_hash_are_text_even_when_they_read_as_a_number(tmp_path):
    """D2.7: the value of a definition has the type "any" (spec:247) and `Hash` is a string
    (spec:230): `spec` keeps the text, with its digits, signs and exponent as written."""
    text = _text("valid_1_5_1.seq")
    digits = "12345678901234567890123456789012"
    path = _write(
        tmp_path,
        text.replace("Hash 46631d7f179a1a0a028842b840aaac51", f"Hash {digits}").replace(
            "Name valid_1_5_1", "Name 007\nExponent 1E5 +3"
        ),
        "t.seq",
    )
    data = read_seqfile(path)
    assert data.signature.hash == digits
    assert data.signature.matches is False
    assert data.definitions["Name"] == ("007",)
    assert data.definitions["Exponent"] == ("1E5", "+3")


def test_syntax_of_numbers_in_a_table(tmp_path):
    """spec:176: each field is read by the type of its column. An integer is an optional sign
    and digits (so `+30` is 30); `3e1`, `0x1e` and `30.0` are not integers. A float takes an
    exponent and a sign; `inf`, `1,5` and `1e999` are not finite numbers (`syntax.number`)."""
    base = _text("valid_no_signature.seq")
    row = "1  30  1  0  0  0  0  1\n"
    for bad in (
        "1  3e1  1  0  0  0  0  1\n",
        "1  0x1e  1  0  0  0  0  1\n",
        "1  30.0  1  0  0  0  0  1\n",
    ):
        assert {
            v.rule
            for v in violations_of(_write(tmp_path, base.replace(row, bad), "n.seq")).violations
        } == {"syntax.integer"}
    plus = read_seqfile(_write(tmp_path, base.replace(row, "1  +30  1  0  0  0  0  1\n"), "p.seq"))
    assert plus.blocks["duration_ticks"][0] == 30
    amplitude = "1 1000000 100 200 100 100\n"
    for good in (
        "1 1e+06 100 200 100 100\n",
        "1 +1000000 100 200 100 100\n",
        "1 1000000. 100 200 100 100\n",
    ):
        data = read_seqfile(_write(tmp_path, base.replace(amplitude, good), "g.seq"))
        assert data.trap["amplitude"][0] == 1e6
    for bad in ("1 inf 100 200 100 100\n", "1 1,5 100 200 100 100\n", "1 1e999 100 200 100 100\n"):
        assert codes_of(_write(tmp_path, base.replace(amplitude, bad), "b.seq")) == {
            "syntax.number"
        }


def test_an_integer_column_rejects_a_fraction_in_a_time(tmp_path):
    """spec:351, spec:396-399, spec:438: the delay of an RF event, the times of a trapezoid
    and the delay of an ADC event are integers (in us), so `100.5` is `syntax.integer`
    (`bad_syntax_integer.seq` has `30.5` as a block duration)."""
    text = _text("valid_no_signature.seq")
    for old, new in (
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 100.5 0 0 0 0 e"),
        ("1 1000000 100 200 100 100", "1 1000000 100.5 200 100 100"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 25000 100.5 0 0 0 0 0"),
    ):
        (violation,) = violations_of(_write(tmp_path, text.replace(old, new), "i.seq")).violations
        assert violation.rule == "syntax.integer"


@pytest.mark.parametrize(
    ("old", "new", "section"),
    [
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 nan 1 2 0 50 100 0 0 0 0 e", "RF"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 inf 100 0 0 0 0 e", "RF"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 100 0 0 nan 0 e", "RF"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 100 0 0 0 -inf e", "RF"),
        ("2 500000 0 0 3 0 100", "2 nan 0 0 3 0 100", "GRADIENTS"),
        ("2 500000 0 0 3 0 100", "2 500000 inf 0 3 0 100", "GRADIENTS"),
        ("1 1000000 100 200 100 100", "1 inf 100 200 100 100", "TRAP"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 nan 100 0 0 0 0 0", "ADC"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 25000 100 nan 0 0 0 0", "ADC"),
        ("1 0 -100 1 TE", "1 0 nan 1 TE", "extension DELAYS"),
        ("1 0.92388 0 0 0.382683", "1 nan 0 0 0.382683", "extension ROTATIONS"),
        ("1 2 1 0 1 1.5708", "1 2 1 0 1 inf", "extension RF_SHIMS"),
    ],
    ids=[
        "rf-amplitude",
        "rf-center",
        "rf-freq-offset",
        "rf-phase-offset",
        "gradient-amplitude",
        "gradient-first",
        "trap-amplitude",
        "adc-dwell",
        "adc-freq-ppm",
        "delays-offset",
        "rotations-q0",
        "rf-shims-value",
    ],
)
def test_nan_and_inf_in_a_float_column_are_syntax_number_with_the_choice(
    tmp_path, old, new, section
):
    """D3.5: spec:176 types each column as an integer or a float; it does not say whether NaN and
    infinity are floats of a file. `spec` rejects them in every float column (`syntax.number`,
    the package's choice, which the message says): they give no waveform. MATLAB Pulseq writes NaN
    when a script passes it, so the message does not give the writers as the reason."""
    text = _text("valid_no_signature.seq")
    assert text.count(old) == 1
    (violation,) = violations_of(_write(tmp_path, text.replace(old, new), "nan.seq")).violations
    assert (violation.rule, violation.section) == ("syntax.number", section)
    assert carries_choice(violation)
    assert "give no waveform" in violation.message
    assert "no current writer" not in violation.message


@pytest.mark.parametrize(
    ("old", "new", "column"),
    [
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 -100 0 0 0 0 e", "delay"),
        ("1  30  1  0  0  0  0  1", "1  -30  1  0  0  0  0  1", "duration_ticks"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 3 0 -100", "delay"),
        ("1 1000000 100 200 100 100", "1 1000000 -100 200 100 100", "rise"),
        ("1 1000000 100 200 100 100", "1 1000000 100 -200 100 100", "flat"),
        ("1 1000000 100 200 100 100", "1 1000000 100 200 -100 100", "fall"),
        ("1 1000000 100 200 100 100", "1 1000000 100 200 100 -10", "delay"),
        ("1 8 25000 100 0 0 0 0 0", "1 -8 25000 100 0 0 0 0 0", "num_samples"),
        ("1 8 25000 100 0 0 0 0 0", "1 8 -25000 100 0 0 0 0 0", "dwell"),
        ("1 1 2 0 10", "1 1 2 0 -10", "duration"),
        ("1 1 2 0 10", "1 1 2 -5 10", "delay"),
        ("shape_id 5\nnum_samples 5", "shape_id 5\nnum_samples -5", "num_samples"),
    ],
    ids=[
        "rf-delay",
        "block-duration",
        "gradient-delay",
        "trap-rise",
        "trap-flat",
        "trap-fall",
        "trap-delay",
        "adc-num-samples",
        "adc-dwell",
        "trigger-duration",
        "trigger-delay",
        "shape-num-samples",
    ],
)
def test_a_negative_time_or_count_is_syntax_negative_with_the_choice(tmp_path, old, new, column):
    """D3.6, spec:176 ("integer types are stored as 64-bit unsigned integers"): `spec` rejects a
    negative block duration, delay, rise, flat or fall time, number of samples, dwell time and
    trigger delay or duration. This is not literally the specification (it defines negative values
    elsewhere, and the dwell is a float): the package's choice, which the message says. Both
    writers write a negative delay when a script passes one, so the message gives as the reason
    that a negative time or count gives no waveform, not the writers."""
    text = _text("valid_no_signature.seq")
    assert text.count(old) == 1
    path = _write(tmp_path, text.replace(old, new), "neg.seq")
    violations = [v for v in violations_of(path).violations if v.rule == "syntax.negative"]
    (violation,) = violations
    assert carries_choice(violation)
    assert "gives no waveform" in violation.message
    assert "no current writer" not in violation.message
    assert violation.message.startswith(column)
    assert path.read_text().split("\n")[violation.line - 1].strip()


def test_a_byte_that_is_not_utf8_is_syntax_encoding_at_its_line(tmp_path):
    """D3.1: the specification gives no encoding. `spec` rejects a file with a byte that is not
    UTF-8, at the line of the first one (the package's choice, which the message says: MATLAB
    Pulseq and pypulseq fail on such a byte, and the text of the model is UTF-8)."""
    (violation,) = violations_of(SEQFILES / "bad_syntax_encoding.seq").violations
    assert (violation.rule, violation.section, violation.line) == ("syntax.encoding", None, 31)
    assert carries_choice(violation)
    raw = _text("valid_no_signature.seq").encode().replace(b"# NUM DUR", b"# \xb5s, NUM DUR")
    path = tmp_path / "latin1.seq"
    path.write_bytes(raw)
    (violation,) = violations_of(path).violations
    assert violation.rule == "syntax.encoding"
    assert raw.split(b"\n")[violation.line - 1].startswith(b"# \xb5s")


def test_an_adc_dwell_time_is_a_float_in_ns_and_a_multiple_of_the_adc_raster(tmp_path):
    """spec:437 (a float in ns), spec:275 (an integer multiple of AdcRasterTime): `25000.0`
    reads as 25 us; a dwell with a fraction of a ns reads when it is a multiple of the raster, and
    is `raster.adc-dwell` when it is not."""
    text = _text("valid_no_signature.seq")
    row = "1 8 25000 100 0 0 0 0 0"
    data = read_seqfile(_write(tmp_path, text.replace(row, "1 8 25000.0 100 0 0 0 0 0"), "a.seq"))
    assert data.adc["dwell"][0] == 2.5e-5
    fine = text.replace("AdcRasterTime 1e-07", "AdcRasterTime 1e-10").replace(
        row, "1 8 25000.5 100 0 0 0 0 0"
    )
    assert read_seqfile(_write(tmp_path, fine, "b.seq")).adc["dwell"][0] == pytest.approx(
        2.50005e-5
    )
    off = text.replace(row, "1 8 25000.5 100 0 0 0 0 0")
    assert codes_of(_write(tmp_path, off, "c.seq")) == {"raster.adc-dwell"}


def test_a_time_within_1_ps_of_a_raster_multiple_is_on_the_raster():
    """`spec.TOLERANCE_NS` (1 ps): a time 0.9 ps from a multiple of the raster, on either side, is
    on the raster; a time 1.1 ps from it is off."""
    ns = np.array([300.0, 300.0009, 299.9991, 300.0011, 299.9989])
    assert _off_raster(ns, 100.0).tolist() == [False, False, False, True, True]


def test_an_adc_dwell_time_that_is_a_multiple_of_the_adc_raster_only_to_1_ps_reads(tmp_path):
    """spec:275 and `spec.TOLERANCE_NS`: `AdcRasterTime 3e-08` is 29.999999999999996 ns in
    floats, so a dwell of 30 ns is 6.7e-15 ns from one raster step. The file reads."""
    text = _text("valid_no_signature.seq")
    fine = text.replace("AdcRasterTime 1e-07", "AdcRasterTime 3e-08").replace(
        " 8 25000 100 ", " 8 30 100 "
    )
    data = read_seqfile(_write(tmp_path, fine, "a.seq"))
    assert data.adc["dwell"].tolist() == [3e-8, 3e-8]


def test_a_soft_delay_offset_is_a_float_in_us_and_its_hint_is_kept_whole(tmp_path):
    """D2.16, spec:550-558: the example gives the offset in us (integers) and has no table of types:
    `spec` reads the offset as a float, as MATLAB Pulseq writes and reads it (the package's choice):
    `valid_soft_delay_fraction.seq` has -100.5 us. The whole hint is kept."""
    data = read_seqfile(SEQFILES / "valid_soft_delay_fraction.seq")
    ((_, num, offset, factor, hint),) = data.extensions.soft_delays.tolist()
    assert (num, offset, factor, hint) == (0, -100.5e-6, 1.0, "TE")
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("1 0 -100 1 TE", "1 0 -100 1 " + "T" * 40), "h.seq")
    assert read_seqfile(path).extensions.soft_delays["hint"][0] == "T" * 40


def test_the_rf_use_is_one_of_seven_letters(tmp_path):
    """spec:356-357: "the initial of one of" excitation, refocusing, inversion, saturation,
    preparation, other or undefined: `e r i s p o u`. Another letter, also a capital, is
    `syntax.use`."""
    text = _text("valid_no_signature.seq")
    for letter in "erispou":
        data = read_seqfile(
            _write(tmp_path, text.replace("0 0 0 0 e\n", f"0 0 0 0 {letter}\n"), "u.seq")
        )
        assert data.rf["use"][0] == letter
    for letter in ("x", "E", "ee"):
        path = _write(tmp_path, text.replace("0 0 0 0 e\n", f"0 0 0 0 {letter}\n"), "u.seq")
        assert codes_of(path) == {"syntax.use"}


def test_values_are_float64_with_all_their_digits(tmp_path):
    """spec:176 ("Shapes are stored as 32-bit single-precision floats"; the plan reads this
    as the binary format): `spec` reads float64 from the text and does not round to 32 bits."""
    text = _text("valid_no_signature.seq")
    text = text.replace(
        "1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000.123456789012 1 2 0 50 100 0 0 0 0 e"
    )
    text = text.replace("0.1\n0.2\n", "0.123456789012345\n0.2\n")
    data = read_seqfile(_write(tmp_path, text, "d.seq"))
    assert data.rf["amplitude"][0] == 1000.123456789012
    assert data.shapes[3].samples()[0] == 0.123456789012345


def test_ids_that_are_not_positive_or_not_unique_are_rejected(tmp_path):
    """spec:181-183: "IDs must be positive integers"; the ID of a shape, and of an event of
    one class, must be unique. `bad_id_positive.seq` (an RF ID), `bad_id_unique.seq` (an ADC ID);
    here a shape ID. No choice in the messages."""
    text = _text("valid_no_signature.seq").rstrip("\n")
    for tail, rule in (
        ("\n\nshape_id 9\nnum_samples 1\n0\n", "id.unique"),
        ("\n\nshape_id -3\nnum_samples 1\n0\n", "id.positive"),
    ):
        (violation,) = violations_of(_write(tmp_path, text + tail + "\n", "s.seq")).violations
        assert (violation.rule, violation.section) == (rule, "SHAPES")
        assert not carries_choice(violation)
    (violation,) = violations_of(SEQFILES / "bad_id_positive.seq").violations
    assert not carries_choice(violation)


def test_a_gradient_id_is_unique_across_gradients_and_trapezoids():
    """spec:183, spec:403: `[GRADIENTS]` and `[TRAP]` share one set of IDs
    (`bad_id_gradient_unique.seq`)."""
    (violation,) = violations_of(SEQFILES / "bad_id_gradient_unique.seq").violations
    assert (violation.rule, violation.section) == ("id.gradient-unique", "TRAP")


def test_a_repeated_block_id_is_id_unique_with_the_choice(tmp_path):
    """D3.4: the specification states uniqueness for shapes and events, not for blocks, which
    nothing refers to; `spec` rejects a repeated block ID (the package's choice: both writers
    number the blocks 1, 2, ..., and the message says so)."""
    text = _text("valid_no_signature.seq")
    row = "3  50  0  0  0  3  0  0\n"
    for old, new in (
        (row, "2  50  0  0  0  3  0  0\n"),
        ("2  50  0  1  2  0  1  0\n", "1  50  0  1  2  0  1  0\n"),
    ):
        error = violations_of(_write(tmp_path, text.replace(old, new), "repeat.seq"))
        (violation,) = error.violations
        assert (violation.rule, violation.section, carries_choice(violation)) == (
            "id.unique",
            "BLOCKS",
            True,
        )


def test_blocks_play_in_file_order_whatever_their_ids(tmp_path):
    """spec:185 ("There are no restrictions on the ordering of IDs") and spec:318 ("The
    blocks are executed sequentially"): `spec` reads the blocks in file order.
    `bad_blocks_order.seq` has block 3 before block 2."""
    data = read_seqfile(SEQFILES / "bad_blocks_order.seq")
    assert data.blocks["id"].tolist() == [1, 3, 2, 4, 5, 6, 7, 8, 9]
    assert data.blocks["gx"].tolist() == [0, 0, 1, 0, 5, 0, 0, 0, 0]
    lines = _text("valid_no_signature.seq").split("\n")
    start = lines.index("[BLOCKS]") + 1
    lines[start : start + 9] = lines[start : start + 9][::-1]
    data = read_seqfile(_write(tmp_path, "\n".join(lines), "rev.seq"))
    assert data.blocks["id"].tolist() == [9, 8, 7, 6, 5, 4, 3, 2, 1]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("1  30  1  0  0  0  0  1", "1  30  9  0  0  0  0  1"),
        ("1  30  1  0  0  0  0  1", "1  30  1  9  0  0  0  1"),
        ("2  50  0  1  2  0  1  0", "2  50  0  1  2  0  9  0"),
        ("1  30  1  0  0  0  0  1", "1  30  1  0  0  0  0  99"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 99 2 0 50 100 0 0 0 0 e"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 99 0 50 100 0 0 0 0 e"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 99 50 100 0 0 0 0 e"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 99 0 100"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 3 99 100"),
        ("2 8 25000 100 0 0 0 0 8", "2 8 25000 100 0 0 0 0 99"),
        ("1 1 1 2", "1 1 1 99"),
        ("1 1 1 2", "1 99 1 2"),
        ("2 2 1 0", "2 2 9 0"),
    ],
    ids=[
        "block-rf",
        "block-gx",
        "block-adc",
        "block-extension",
        "rf-magnitude",
        "rf-phase",
        "rf-time",
        "gradient-shape",
        "gradient-time",
        "adc-phase",
        "entry-next",
        "entry-type",
        "entry-object",
    ],
)
def test_a_reference_to_something_that_is_not_defined_is_ref_unresolved(tmp_path, old, new):
    """spec:178-186 (IDs refer to the objects one level below), spec:478 (a list of extensions
    ends with 0): a block's event or extension list, an event's shape, and an entry of
    `[EXTENSIONS]` (its next entry, its type, its object) that name nothing are rejected."""
    text = _text("valid_no_signature.seq")
    assert text.count(old + "\n") == 1
    path = _write(tmp_path, text.replace(old + "\n", new + "\n"), "ref.seq")
    assert codes_of(path) == {"ref.unresolved"}


def test_time_id_minus_1_is_for_a_gradient_from_1_5_0_only():
    """D4.3, spec:349 (an RF time ID: 0 means the default, nothing else is defined), spec:395 (-1:
    "1/2 of the default time raster (gradient oversampling case)"), slide 4 ("Updated in v1.5.0"):
    `ref.unresolved` for an RF event with time ID -1 (`undefined/rf_time_id_minus_1.seq`) and for
    a gradient with -1 in a 1.4 file (`bad_ref_time_id_minus_1_in_1_4.seq`); a 1.5 gradient has
    it (`valid_1_5_1.seq`)."""
    for name, section in (
        ("undefined/rf_time_id_minus_1.seq", "RF"),
        ("bad_ref_time_id_minus_1_in_1_4.seq", "GRADIENTS"),
    ):
        (violation,) = violations_of(SEQFILES / name).violations
        assert (violation.rule, violation.section) == ("ref.unresolved", section)
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq").grad["time_id"].tolist()[-1] == -1


def test_a_cycle_in_an_extension_list_is_ref_unresolved():
    """spec:478 ("zero-terminated single-linked list"): a list that never ends is rejected at
    the block that starts it."""
    (violation,) = violations_of(SEQFILES / "bad_ref_extension_cycle.seq").violations
    assert (violation.rule, violation.section) == ("ref.unresolved", "BLOCKS")
    assert "cycle" in violation.message


def test_a_file_with_no_block_is_blocks_empty():
    """spec:318: "The sequence must declare at least one block"."""
    (violation,) = violations_of(SEQFILES / "bad_blocks_empty.seq").violations
    assert (violation.rule, violation.section) == ("blocks.empty", "BLOCKS")


def test_an_event_that_lasts_longer_than_its_block_is_block_event_too_long():
    """spec:318: "No event comprising this block is allowed to last longer than the
    specified block duration. The interpreters must to throw an error": an RF event, an ADC event
    and a trigger that end after their block."""
    for name, text in (
        ("bad_block_event_too_long_rf.seq", "RF event"),
        ("bad_block_event_too_long_adc.seq", "ADC event"),
        ("bad_block_event_too_long_trigger.seq", "trigger"),
    ):
        (violation,) = violations_of(SEQFILES / name).violations
        assert (violation.rule, violation.section) == ("block.event-too-long", "BLOCKS")
        assert text in violation.message


@pytest.mark.parametrize(
    ("name", "rule"),
    [
        ("bad_raster_adc_dwell.seq", "raster.adc-dwell"),
        ("bad_raster_gradient_delay.seq", "raster.gradient-delay"),
        ("bad_raster_gradient_end.seq", "raster.gradient-end"),
        ("bad_raster_gradient_ramp.seq", "raster.gradient-ramp"),
        ("bad_raster_gradient_flat.seq", "raster.gradient-flat"),
    ],
)
def test_a_time_that_is_not_a_multiple_of_its_raster_is_rejected(name, rule):
    """spec:290 (a gradient starts and ends on the gradient raster; the ramps and the flat
    time of a trapezoid are multiples of it), spec:275 (the ADC dwell time "must be integer
    multiple" of AdcRasterTime), slide 5: each is a rejection. No choice in the message."""
    (violation,) = violations_of(SEQFILES / name).violations
    assert violation.rule == rule
    assert not carries_choice(violation)


@pytest.mark.parametrize(
    ("name", "rule"),
    [
        ("bad_gradient_nonzero_start_delay.seq", "gradient.nonzero-start-delay"),
        ("bad_gradient_nonzero_end_align.seq", "gradient.nonzero-end-align"),
    ],
)
def test_a_gradient_that_is_not_aligned_to_its_block_is_rejected(name, rule):
    """spec:420: "Gradients that start at non-zero values must be aligned to the beginning of
    the block, meaning that the start delay of such gradients must be 0", and a gradient that ends
    above 0 needs "to be aligned to the end of the block"; slide 6 ("Vertices with non-zero
    amplitude must touch block boundary")."""
    (violation,) = violations_of(SEQFILES / name).violations
    assert violation.rule == rule
    assert not carries_choice(violation)


# A syntax error in one row of each event table of `valid_no_signature.seq` (the row, the row with
# the error, and its code).
_BROKEN_EVENT_ROWS = {
    "RF": ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 0 50 x 0 0 0 0 e", "syntax.integer"),
    "GRADIENTS": ("6 300000 0 0 7 -1 0", "6 300000 0 0 7 -1 x", "syntax.integer"),
    "TRAP": ("1 1000000 100 200 100 100", "1 1000000 100 200 100 x", "syntax.integer"),
    "ADC": ("2 8 25000 100 0 0 0 0 8", "2 8 25000 x 0 0 0 0 8", "syntax.integer"),
}


@pytest.mark.parametrize(
    ("table", "old", "new", "rule"),
    [
        ("RF", "1 8 25000 100 0 0 0 0 0", "1 8 25050 100 0 0 0 0 0", "raster.adc-dwell"),
        (
            "GRADIENTS",
            "1 1000000 100 200 100 100",
            "1 1000000 100 195 100 100",
            "raster.gradient-flat",
        ),
        ("TRAP", "2 500000 0 0 3 0 100", "2 500000 0 0 3 0 105", "raster.gradient-delay"),
        ("ADC", "1 1000000 100 200 100 100", "1 1000000 100 195 100 100", "raster.gradient-flat"),
    ],
    ids=["RF", "GRADIENTS", "TRAP", "ADC"],
)
def test_a_syntax_error_in_one_event_table_keeps_the_checks_of_the_others(
    tmp_path, table, old, new, rule
):
    """The module docstring of `spec`: a check that needs a table with a violation of syntax is
    skipped, "so the error has every violation of the tables that read". A row of `table` that
    breaks a rule of syntax, and a time off its raster in another event table (spec:290,
    spec:275), give both codes, and no other."""
    row, broken, syntax = _BROKEN_EVENT_ROWS[table]
    text = _text("valid_no_signature.seq")
    assert row in text and old in text
    assert codes_of(_write(tmp_path, text.replace(old, new), "r.seq")) == {rule}
    path = _write(tmp_path, text.replace(row, broken).replace(old, new), "t.seq")
    assert codes_of(path) == {syntax, rule}


@pytest.mark.parametrize("table", sorted(_BROKEN_EVENT_ROWS))
def test_a_syntax_error_in_one_event_table_keeps_the_trigger_check(tmp_path, table):
    """spec:318 ("No event comprising this block is allowed to last longer than the specified
    block duration"): a trigger reads from its own extension table, so a row of an event table
    that breaks a rule of syntax does not skip it. The trigger of `valid_no_signature.seq` lasts
    30 us in a block of 20 us (as in `bad_block_event_too_long_trigger.seq`)."""
    row, broken, syntax = _BROKEN_EVENT_ROWS[table]
    text = _text("valid_no_signature.seq")
    trigger = "extension TRIGGERS 3\n1 1 2 0 10\n"
    assert row in text and trigger in text
    path = _write(
        tmp_path,
        text.replace(row, broken).replace(trigger, trigger.replace(" 10\n", " 30\n")),
        "t.seq",
    )
    assert codes_of(path) == {syntax, "block.event-too-long"}


def test_a_syntax_error_in_the_blocks_keeps_the_raster_checks_of_the_event_tables(tmp_path):
    """The module docstring of `spec` ("the error has every violation of the tables that read"):
    the raster rules of an event table do not need `[BLOCKS]`, so a row of `[BLOCKS]` that breaks a
    rule of syntax does not skip them. A flat time off the gradient raster (spec:290) gives
    `raster.gradient-flat`, and with the syntax error both codes, and no other."""
    text = _text("valid_no_signature.seq")
    row, broken = "3  50  0  0  0  3  0  0\n", "3  x  0  0  0  3  0  0\n"
    old, new = "1 1000000 100 200 100 100\n", "1 1000000 100 195 100 100\n"
    assert row in text and old in text
    assert codes_of(_write(tmp_path, text.replace(old, new), "r.seq")) == {"raster.gradient-flat"}
    path = _write(tmp_path, text.replace(row, broken).replace(old, new), "t.seq")
    assert codes_of(path) == {"syntax.integer", "raster.gradient-flat"}


def test_a_gradient_raster_of_5_us_with_a_block_raster_of_10_us_reads():
    """The specification accepts any gradient raster (spec:273: "Default raster time"). The
    raster must divide or be a multiple of the block raster (slide 11, in
    `test_a_raster_that_is_not_commensurate_with_the_block_raster_is_rejected`):
    `valid_arbitrary_gradient_5us_raster.seq` has 5 us and a block raster of 10 us, and reads
    with its gradient. `test_decoding.py` decodes the gradient on the raster of the file."""
    data = read_seqfile(SEQFILES / "valid_arbitrary_gradient_5us_raster.seq")
    assert data.rasters.gradient == 5e-6
    assert data.rasters.block_duration == 1e-5
    assert len(data.grad) == 1


def test_a_raster_that_is_not_commensurate_with_the_block_raster_is_rejected(tmp_path):
    """slide 11: "rfRasterTime and gradRasterTime must be integer-multiples of blockDurationRaster
    or vise versa", and "Edges of all types of rasters coincide at the beginning of the block".
    The 4 us gradient raster of `valid_arbitrary_gradient_4us_raster.seq` (block raster 10 us)
    breaks it (its name is historical: the file was valid before); so does an RF raster of
    3 us. The rule is stated by the slide: no choice in the message."""
    (violation,) = violations_of(SEQFILES / "valid_arbitrary_gradient_4us_raster.seq").violations
    assert (violation.rule, violation.section) == ("definitions.raster-commensurate", "DEFINITIONS")
    assert "GradientRasterTime" in violation.message
    assert not carries_choice(violation)
    text = _text("valid_no_signature.seq")
    text = text.replace("RadiofrequencyRasterTime 1e-06", "RadiofrequencyRasterTime 3e-06")
    error = violations_of(_write(tmp_path, text, "rf.seq"))
    (violation,) = (v for v in error.violations if v.rule == "definitions.raster-commensurate")
    assert "RadiofrequencyRasterTime" in violation.message


def test_a_raster_that_divides_or_is_a_multiple_of_the_block_raster_is_commensurate(tmp_path):
    """slide 11: a raster equal to the block raster (every other fixture), a divisor (5 us, in
    `valid_arbitrary_gradient_5us_raster.seq`) and a multiple read. Here the RF raster is 20 us for
    a block raster of 10 us, with a longer first block for the RF event of 100 samples."""
    assert (
        read_seqfile(SEQFILES / "valid_arbitrary_gradient_5us_raster.seq").rasters.gradient == 5e-6
    )
    text = _text("valid_no_signature.seq")
    text = text.replace("RadiofrequencyRasterTime 1e-06", "RadiofrequencyRasterTime 2e-05")
    text = text.replace("1  30  1  0  0  0  0  1", "1 300  1  0  0  0  0  1")
    data = read_seqfile(_write(tmp_path, text, "multiple.seq"))
    assert data.rasters.rf == 2e-5


@pytest.mark.parametrize(
    ("name", "rule"),
    [
        ("bad_raster_rf_delay.seq", "raster.rf-delay"),
        ("bad_raster_adc_delay.seq", "raster.adc-delay"),
    ],
)
def test_an_rf_or_adc_event_must_start_on_an_edge_of_the_rf_raster(tmp_path, name, rule):
    """slide 9 ("The beginning of an RF object must be aligned to the RF raster edge"), slide 10
    ("ADC start time must be aligned to rfRasterTime"), spec:290 ("All blocks and events are
    aligned to the corresponding edges of the time raster"): with an RF raster of 2 us, an RF
    delay of 99 us and an ADC delay of 101 us are rejected, and a delay of 100 us reads."""
    (violation,) = violations_of(SEQFILES / name).violations
    assert violation.rule == rule
    assert not carries_choice(violation)
    text = _text(name)
    ok = {"raster.rf-delay": ("0 50 99 0 0 0 0 e", "0 50 100 0 0 0 0 e")}.get(
        rule, ("25000 101 0 0 0 0 0", "25000 100 0 0 0 0 0")
    )
    assert ok[0] in text
    data = read_seqfile(_write(tmp_path, text.replace(*ok), "ok.seq"))
    assert data.rasters.rf == 2e-6


def test_a_shape_that_does_not_have_its_declared_number_of_samples_is_shape_length(tmp_path):
    """spec:626: "The number of points after decompressing all samples defined in a shape
    must be equal the number declared in `<num_samples>`": a shape that decompresses to more
    (`undefined/shape_decompress_longer.seq`) or fewer samples (`bad_shape_length.seq`, and one
    of 10 uncompressed values that declares 11)."""
    for name in ("bad_shape_length.seq", "undefined/shape_decompress_longer.seq"):
        error = violations_of(SEQFILES / name)
        assert {v.rule for v in error.violations} == {"shape.length"}
        assert not any(carries_choice(v) for v in error.violations)
    text = _text("valid_no_signature.seq")
    path = _write(
        tmp_path, text.replace("shape_id 3\nnum_samples 10", "shape_id 3\nnum_samples 11"), "s.seq"
    )
    (violation,) = violations_of(path).violations
    assert violation.rule == "shape.length"
    assert "10 samples, not the 11" in violation.message


def _with_shape(directory, shape_id, samples):
    """`valid_no_signature.seq` with the shape `shape_id` replaced by `samples`, a list of
    numbers written uncompressed. The number of samples must be the one that the events of the
    file have."""
    text = _text("valid_no_signature.seq")
    start = text.index(f"shape_id {shape_id}\n")
    end = text.index("\n\n", start)
    body = "\n".join(str(s) for s in samples)
    text = text[:start] + f"shape_id {shape_id}\nnum_samples {len(samples)}\n{body}" + text[end:]
    return _write(directory, text, "shape.seq")


@pytest.mark.parametrize(
    ("shape_id", "samples", "rule"),
    [
        (4, [0.5] * 8 + [-0.5 * RANGE_TOLERANCE, 1.0], None),
        (4, [0.5] * 8 + [1 + 0.5 * RANGE_TOLERANCE, -(1 + 0.5 * RANGE_TOLERANCE)], None),
        (4, [0.5] * 8 + [1 + 2 * RANGE_TOLERANCE, 0.0], "shape.range"),
        (4, [0.5] * 8 + [-(1 + 2 * RANGE_TOLERANCE), 0.0], "shape.range"),
        (4, [0.5] * 8 + [1.5, 1.5], "shape.range"),
        (1, [0.5] * 98 + [1 + 0.5 * RANGE_TOLERANCE, 1.0], None),
        (1, [0.5] * 98 + [1 + 2 * RANGE_TOLERANCE, 1.0], "shape.range"),
        (1, [0.5] * 98 + [-(1 + 2 * RANGE_TOLERANCE), 1.0], "shape.range"),
    ],
    ids=[
        "gradient-inside",
        "gradient-at-the-tolerance",
        "gradient-above",
        "gradient-below",
        "gradient-far-above",
        "magnitude-at-the-tolerance",
        "magnitude-above",
        "magnitude-below",
    ],
)
def test_an_amplitude_shape_must_be_in_minus_1_to_1_to_within_the_tolerance(
    tmp_path, shape_id, samples, rule
):
    """spec:624: "When used as amplitude shapes for gradient or RF objects, the decompressed
    samples must be in the normalised range of [-1, 1]": the magnitude shape of an RF event and
    the waveform of an arbitrary gradient. A sample beyond 1 in absolute value by more than
    `RANGE_TOLERANCE` (1e-9: the rounding of the 9 digits that MATLAB Pulseq writes) is
    `shape.range`, one report for the shape and not one for each sample."""
    path = _with_shape(tmp_path, shape_id, samples)
    if rule is None:
        assert read_seqfile(path).shapes[shape_id].samples().tolist() == samples
        return
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == (rule, "SHAPES")
    assert not carries_choice(violation)


def test_a_negative_rf_magnitude_plays_as_written():
    """D2.8, spec:624 (the range of an amplitude shape is [-1, 1], so a negative magnitude is
    allowed): `bad_shape_rf_magnitude_negative.seq` has a magnitude of -0.5, which `spec` reads
    and decodes as written, a negative magnitude (a phase of pi)."""
    data = read_seqfile(SEQFILES / "bad_shape_rf_magnitude_negative.seq")
    assert data.shapes[1].samples().tolist() == [-0.5] * 100
    event = events.decode_rf(data)[1]
    assert event.magnitude.tolist() == [-500.0] * 100


def test_an_rf_phase_shape_plays_as_written_with_no_range():
    """D2.9: the specification is silent on the range of the phase shape; `spec` reads the phase as
    written and decodes 2 pi times the value with no wrap (a phase of 1.5 turns is 3 pi), as MATLAB
    does. `bad_shape_rf_phase_range.seq` has a phase of 1.5."""
    data = read_seqfile(SEQFILES / "bad_shape_rf_phase_range.seq")
    assert data.shapes[2].samples().tolist() == [1.5] * 100
    event = events.decode_rf(data)[1]
    assert event.phase == pytest.approx([3 * np.pi] * 100)


def test_an_unused_shape_id_0_is_not_taken_for_the_time_shape_of_the_default_raster(tmp_path):
    """Time ID 0 is the default raster, not a shape. The ID 0 is not positive (`id.positive`,
    spec:181), but a shape with that ID, whether it has samples that are not on the raster or none,
    is not the time shape of a gradient with time ID 0: the file gives that one rule and no
    `raster.gradient-vertex`, `shape.time-order` or `shape.empty`."""
    text = _text("valid_no_signature.seq").rstrip("\n")
    for body in ("num_samples 3\n0\n0.25\n0.5\n", "num_samples 0\n"):
        path = _write(tmp_path, text + "\n\nshape_id 0\n" + body, "zero.seq")
        (violation,) = violations_of(path).violations
        assert (violation.rule, violation.section) == ("id.positive", "SHAPES")


def test_the_phase_shapes_have_no_range_and_a_gradient_shape_may_be_negative(tmp_path):
    """D2.8, D2.9, D2.15: the phase shape of an RF event and the phase modulation shape of an ADC
    event are not amplitude shapes (spec:624), so any value reads; a negative gradient waveform
    is in [-1, 1]."""
    gradient = read_seqfile(_with_shape(tmp_path, 4, [-0.5] * 10))
    assert gradient.shapes[4].samples().tolist() == [-0.5] * 10
    rf = read_seqfile(_with_shape(tmp_path, 2, [0.25] * 98 + [-3, 100]))
    assert rf.shapes[2].samples().tolist() == [0.25] * 98 + [-3, 100]
    adc = read_seqfile(_with_shape(tmp_path, 8, [-2] + [3] * 7))
    assert adc.shapes[8].samples().tolist() == [-2] + [3] * 7


@pytest.mark.parametrize(
    ("old", "new", "empty", "length"),
    [
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 10 10 0 50 100 0 0 0 0 e", 1, 0),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 10 11 0 50 100 0 0 0 0 e", 2, 0),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 10 10 11 50 100 0 0 0 0 e", 2, 0),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 10 0 100", 1, 0),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 10 11 100", 2, 0),
        ("2 8 25000 100 0 0 0 0 8", "2 8 25000 100 0 0 0 0 10", 1, 1),
    ],
    ids=[
        "rf-magnitude-and-phase",
        "rf-two-empty-shapes",
        "rf-time-shape",
        "gradient-waveform",
        "gradient-waveform-and-time-shape",
        "adc-phase-shape",
    ],
)
def test_a_shape_with_no_sample_that_an_event_uses_is_shape_empty(
    tmp_path, old, new, empty, length
):
    """D3.7: the specification is silent on a shape with no sample. `spec` rejects it where an
    event uses it, an RF, gradient or ADC phase shape (the package's choice: an event with no
    samples has no waveform; the message says so). `empty` is the number of violations (one for
    each empty shape that an event uses); an empty ADC phase shape is also not one value for each
    ADC sample (`shape.event-length`, `length` of them)."""
    text = _text("valid_no_signature.seq")
    assert old in text
    text = text.replace(old, new).rstrip("\n")
    text += "\n\nshape_id 10\nnum_samples 0\n\nshape_id 11\nnum_samples 0\n"
    error = violations_of(_write(tmp_path, text, "empty.seq"))
    found = [v for v in error.violations if v.rule == "shape.empty"]
    assert len(found) == empty
    assert all(carries_choice(v) for v in found)
    assert len(error.violations) - empty == length


def test_an_unused_empty_shape_is_read(tmp_path):
    """D3.7: only a shape that an event uses is rejected (the rule is about an event with no
    samples)."""
    text = _text("valid_no_signature.seq").rstrip("\n")
    text += "\n\nshape_id 10\nnum_samples 0\n"
    assert read_seqfile(_write(tmp_path, text, "unused.seq")).shapes[10].num_samples == 0


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 8 0 50 100 0 0 0 0 e"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 8 2 0 50 100 0 0 0 0 e"),
        ("1 1000 1 2 0 50 100 0 0 0 0 e", "1 1000 1 2 6 50 100 0 0 0 0 e"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 4 6 100"),
        ("2 500000 0 0 3 0 100", "2 500000 0 0 5 3 100"),
    ],
    ids=[
        "rf-phase-shorter",
        "rf-magnitude-shorter",
        "rf-time-shorter",
        "gradient-time-shorter",
        "gradient-time-longer",
    ],
)
def test_the_shapes_of_one_event_must_have_one_number_of_samples(tmp_path, old, new):
    """D3.8, spec:349, spec:443 (an RF event's magnitude, phase and time shape, and a gradient's
    waveform and time shape, pair up by sample): the specification does not say what an event
    plays when they differ, so `spec` rejects it (the package's choice: some samples have no
    partner; the message says so). `bad_shape_event_length.seq` is the RF phase of 8 samples
    for a magnitude of 100."""
    text = _text("valid_no_signature.seq")
    assert text.count(old) == 1
    path = _write(tmp_path, text.replace(old, new), "len.seq")
    error = violations_of(path)
    found = [v for v in error.violations if v.rule == "shape.event-length"]
    assert found and all(carries_choice(v) for v in found)


def test_the_shapes_of_one_event_with_one_number_of_samples_read():
    """D3.8: the shapes of `valid_1_5_1.seq` (a time shape of 5 samples for a waveform of 5) read."""
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    (row,) = data.grad[data.grad["time_id"] == 6]
    assert data.shapes[row["shape_id"]].num_samples == data.shapes[row["time_id"]].num_samples


def _with_rf_time_shape(directory, time_samples, packed, n=100):
    """`valid_no_signature.seq` with the RF event on new shapes: a magnitude of 1 and a phase of 0
    with `n` samples (10 and 11), and a time shape (12) that declares `n` samples (`time_samples`
    if given) and stores `packed`, a list of numbers or strings. The RF event has delay 100 us in
    a block of 300 us, with the RF raster of 1 us."""
    text = _text("valid_no_signature.seq")
    old = "1 1000 1 2 0 50 100 0 0 0 0 e"
    assert old in text
    text = text.replace(old, "1 1000 10 11 12 50 100 0 0 0 0 e").rstrip("\n")
    for shape_id, value in ((10, 1), (11, 0)):
        text += f"\n\nshape_id {shape_id}\nnum_samples {n}\n" + "\n".join([str(value)] * n)
    num = time_samples if time_samples is not None else n
    text += f"\n\nshape_id 12\nnum_samples {num}\n" + "\n".join(str(s) for s in packed) + "\n"
    return _write(directory, text, "rf_time.seq")


def test_a_regular_rf_time_shape_is_cells_and_any_other_is_points():
    """D2.10, spec:349 ("the time sampling points, specified in the units of
    RadiofrequencyRasterTime"), slide 9 ("Dwell time for regularly-sampled pulses: multiple of
    rfRasterTime"; "Sampling points of RF pulses are aligned to the centers of the dwell time
    periods"), slide 4 (explicit times "are (typically) on raster edges, but this is not a
    requirement"). A time shape with equal steps `d` and a first time of half a step is the cells
    of a regular pulse (`model.rf_time_step` gives `d`); this is the package's choice, since every
    regular pulse that MATLAB Pulseq and pypulseq write has this form. Any other time shape is
    points. `valid_rf_time_shapes.seq`: RF 2 `1 2 2 47` (cells of 2 us), RF 3 `0.5 1.5 2.5` (cells
    of 1 us), RF 4 the block pulse `0 100` and RF 5 vertices `1 2 4 7 10` (points).
    `test_decoding.py` decodes the RF events."""
    data = read_seqfile(SEQFILES / "valid_rf_time_shapes.seq")
    steps = {i: rf_time_step(data.shapes[i].samples()) for i in (12, 15, 18, 21)}
    assert steps == {12: 2.0, 15: 1.0, 18: None, 21: None}


def test_an_rf_time_shape_that_other_tools_write_is_read(tmp_path):
    """D2.10, D2.11: `bad_shape_rf_time_grid.seq` (a step of 1 and a first time of 1: `1 1 98`) and
    `bad_shape_rf_time_end.seq` (the times 0 and 99.6) were rejected by the interim reader; `spec`
    reads them as points (the package's choice: the form `1 1 N-2` is what pypulseq's sigpy pulses
    and the MATLAB UTE demo write). Such a shape ends at its last time."""
    for name, last in (
        ("bad_shape_rf_time_grid.seq", 100e-6),
        ("bad_shape_rf_time_end.seq", 99.6e-6),
    ):
        data = read_seqfile(SEQFILES / name)
        event = events.decode_rf(data)[1]
        assert event.dwell is None
        assert event.shape_dur == pytest.approx(last)
    path = _with_rf_time_shape(tmp_path, None, ["1", "1", "98"])
    assert events.decode_rf(read_seqfile(path))[1].dwell is None


@pytest.mark.parametrize(
    ("packed", "n", "rule"),
    [
        (["1", "2", "2", "97"], 100, None),
        (["2", "4", "4", "97"], 100, "block.event-too-long"),
        (["0", "200"], 2, None),
        (["0", "200.5"], 2, "block.event-too-long"),
        (["0", "99.6"], 2, None),
    ],
    ids=["cells-fit", "cells-too-long", "points-fit", "points-too-long", "points-short"],
)
def test_the_end_of_an_rf_event_with_a_time_shape_is_n_dwells_or_the_last_time(
    tmp_path, packed, n, rule
):
    """D2.12, slide 9: a regular pulse lasts `N d` (every sample is a cell of `d` from the start of
    the pulse), and a pulse of points ends at its last time (the package's choice: both makers of
    vertex pulses set the duration to the last time). The RF event starts at 100 us in a block of
    300 us (`block.event-too-long`, spec:318): 100 cells of 2 us end at 300 us, 100 cells of 4 us
    at 500 us; points that end at 200 us end at 300 us, at 200.5 us at 300.5 us."""
    path = _with_rf_time_shape(tmp_path, None, packed, n=n)
    if rule is None:
        read_seqfile(path)
        return
    assert codes_of(path) == {rule}


@pytest.mark.parametrize(
    ("packed", "n", "why"),
    [
        (["0"], 1, "one sample"),
        (["-5"], 1, "one sample"),
        (["3", "1"], 2, "do not increase"),
        (["0", "0"], 2, "do not increase"),
        (["-5", "-3"], 2, "before the start"),
    ],
    ids=["one-sample-at-0", "one-sample-below-0", "decreasing", "equal", "negative-start"],
)
def test_an_rf_time_shape_that_defines_no_line_is_shape_time_order(tmp_path, packed, n, why):
    """D2.10-D2.12, D3.9, spec:349: the specification does not define such time sampling points,
    and no writer writes them: a time shape of one sample at 0 or before (no cell), times that do
    not increase, or a first time below 0 are `shape.time-order` (the package's choice; the
    message says so). `bad_shape_time_order.seq` has `100 -1 -1 97`."""
    path = _with_rf_time_shape(tmp_path, None, packed, n=n)
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("shape.time-order", "SHAPES")
    assert why in violation.message
    assert carries_choice(violation)
    (violation,) = violations_of(SEQFILES / "bad_shape_time_order.seq").violations
    assert "do not increase" in violation.message


def test_an_rf_time_shape_of_one_sample_above_0_is_one_cell(tmp_path):
    """D3.9, D2.10: MATLAB Pulseq writes the time shape `5` for an arbitrary pulse of one sample
    with a dwell of 10 us (`makeArbitraryRf`, run of 2026-10-13). `spec` reads a time shape of one
    sample `t0` above 0 as one cell of `d = 2 t0`, the form `(i + 0.5) d` with N = 1 (the user,
    2026-10-13): the pulse plays its sample for one dwell of 10 us, centred at 5 us."""
    data = read_seqfile(_with_rf_time_shape(tmp_path, None, ["5"], n=1))
    assert rf_time_step(data.shapes[12].samples()) == pytest.approx(10.0)
    rf = events.decode_rf(data)[1]
    assert rf.dwell == pytest.approx(10e-6)
    assert rf.shape_dur == pytest.approx(10e-6)
    assert rf.t.tolist() == pytest.approx([5e-6])


def test_a_gradient_time_shape_must_increase_and_have_its_vertices_on_the_raster(tmp_path):
    """Slide 6 ("Arbitrary number of vertices, all aligned on raster edges") and slide 4
    ("Sampling points are (typically) on raster edges, but this is not a requirement") conflict on
    a vertex of a gradient time shape off the raster, and no writer writes one:
    `raster.gradient-vertex` (the package's choice; the message says so;
    `bad_raster_gradient_vertex.seq` has `0 1.5 3 6 10`). Times that do not increase are
    `shape.time-order` (the package's choice, as for an RF time shape)."""
    (violation,) = violations_of(SEQFILES / "bad_raster_gradient_vertex.seq").violations
    assert (violation.rule, violation.section) == ("raster.gradient-vertex", "SHAPES")
    assert carries_choice(violation)
    text = _text("valid_no_signature.seq")
    old = "shape_id 6\nnum_samples 5\n0\n1\n3\n6\n10\n"
    for times in ("0\n3\n1\n6\n10", "0\n1\n1\n6\n10"):
        new = f"shape_id 6\nnum_samples 5\n{times}\n"
        (violation,) = violations_of(_write(tmp_path, text.replace(old, new), "g.seq")).violations
        assert (violation.rule, violation.section) == ("shape.time-order", "SHAPES")
        assert carries_choice(violation)


@pytest.mark.parametrize(
    ("first_time", "codes"),
    [
        (0, None),
        (5e-7, None),
        (-5e-7, None),
        (2e-6, {"layer1.gradient-ends", "raster.gradient-vertex"}),
        (0.5, {"layer1.gradient-ends", "raster.gradient-vertex"}),
    ],
)
def test_a_1_4_gradient_with_a_time_shape_must_start_at_time_0(tmp_path, first_time, codes):
    """D4.5: a 1.4 file has no `first` column. A gradient with a time shape that starts at time 0
    (within 1e-6 gradient rasters) has the first sample of its shape for its start value; one that
    starts later has no value at its start: `layer1.gradient-ends` (the package's choice: the
    readers guess the value differently), and its vertex is off the raster. A 1.5 file has the
    `first` column, so it has no such rule."""
    old = "shape_id 4\nnum_samples 5\n0\n1\n3\n6\n10\n"
    new = f"shape_id 4\nnum_samples 5\n{first_time}\n1\n3\n6\n10\n"
    text = _text("valid_1_4_1.seq")
    assert old in text
    path = _write(tmp_path, text.replace(old, new), "start.seq")
    if codes is None:
        assert read_seqfile(path).grad["time_id"].tolist() == [4]
    else:
        assert codes_of(path) == codes
    text15 = _text("valid_1_5_1.seq")
    old15 = "shape_id 6\nnum_samples 5\n0\n1\n3\n6\n10\n"
    assert old15 in text15
    late = text15.replace(old15, old15.replace("\n0\n1\n", "\n0.5\n1\n"))
    assert "layer1.gradient-ends" not in verdict(_write(tmp_path, late, "late.seq"))


def test_a_1_4_gradient_with_no_values_at_its_ends_is_layer1_gradient_ends():
    """D4.4, spec:290 (the default samples are at the centres of the raster cells): a 1.4 file has
    no `first` and `last`, so the values at the two ends of an arbitrary gradient on the default
    raster are not in the file; `spec` rejects it (the package's choice: the readers guess them
    differently, Pulseq 1.5 stores them; the message says so). `cpp-siemens` reads it."""
    for name in (
        "bad_layer1_gradient_ends.seq",
        "oracle/koma_v1.4_gr-uniformly-shaped.seq",
        "oracle/pypulseq_simple_mprage140.seq",
    ):
        (violation,) = violations_of(SEQFILES / name).violations
        assert (violation.rule, violation.section) == ("layer1.gradient-ends", "GRADIENTS")
        assert carries_choice(violation)


def test_a_1_4_gradient_whose_end_is_not_defined_gives_only_layer1_gradient_ends(tmp_path):
    """D4.4: the value at the end of a 1.4 gradient on the default raster is not in the file, so
    `spec` does not know whether the gradient ends above 0 (spec:420), and gives
    `layer1.gradient-ends` only, not also `gradient.nonzero-end-align`. The gradient 3 of
    `bad_layer1_gradient_ends.seq` (50 us) is here in a block of 100 us."""
    text = _text("bad_layer1_gradient_ends.seq")
    gradient = "3 400000 3 0 0\n"
    blocks = "4   2  0  0  0  0  0  2\n"
    assert gradient in text and blocks in text
    path = _write(tmp_path, text.replace(blocks, blocks + "5  10  0  3  0  0  0  0\n"), "e.seq")
    found = [(v.rule, v.section) for v in violations_of(path).violations]
    assert found == [("layer1.gradient-ends", "GRADIENTS")]


def test_an_arbitrary_gradient_on_the_default_raster_has_a_sample_at_each_cell_centre():
    """D2.13, spec:290 ("sampling points of arbitrary-shape gradients are aligned to the centers"),
    slide 7: the sample `i` of a gradient on the default raster is at `(i + 0.5) dt`, between
    `first` at the start and `last` at the end of the event (the file's columns). The straight
    lines between the points are drawn by `seq_utils.gradient_offsets`."""
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    event = events.decode_gradients(data)[3]
    assert event.tt.tolist() == pytest.approx((np.arange(10) + 0.5) * 1e-5)
    assert (event.first, event.last) == (0.0, 500000.0)
    assert event.shape_dur == pytest.approx(1e-4)


def test_an_oversampled_gradient_of_an_even_count_is_shape_oversampled_length():
    """spec:395 and spec:420 ("N-1 additional points"), slides 4 and 8 (the shape "starts and
    ends at the cell centers"): the samples of a gradient with time ID -1 are half a raster apart,
    the first and the last at cell centres, so their number is odd (derived: the slides do not
    state a count); `shape.oversampled-length` rejects an even count
    (`bad_shape_oversampled_length.seq`, 4 samples). `test_decoding.py` decodes the samples."""
    (violation,) = violations_of(SEQFILES / "bad_shape_oversampled_length.seq").violations
    assert (violation.rule, violation.section) == ("shape.oversampled-length", "GRADIENTS")
    assert not carries_choice(violation)


def test_an_adc_phase_shape_of_another_length_is_shape_event_length():
    """D2.15, D3.8, spec:443 (the phase shape "of the phase modulation", no unit), spec:120 (an ADC phase
    offset per sample): `spec` reads it in rad, one value for each ADC sample (the package's
    choice: as C++ and MATLAB, and `makeAdc` requires); a shape of another length is
    `shape.event-length` (`bad_shape_adc_phase_length.seq`: 9 samples for 8). `test_decoding.py`
    decodes the values."""
    (violation,) = violations_of(SEQFILES / "bad_shape_adc_phase_length.seq").violations
    assert (violation.rule, violation.section) == ("shape.event-length", "ADC")
    assert carries_choice(violation)


# ---- The rows of section 6: extensions, values that a reader changes, the signature ----


def test_an_unknown_extension_that_is_not_required_is_skipped():
    """D2.17, spec:460 ("The interpreter MUST detect unknown extensions and MAY chose to ignore
    them"): `spec` ignores the rows of an extension that it does not know and lists its STRING_ID
    in `skipped_extensions`; its type ID stays in `type_ids`. `valid_1_5_1.seq` has one with rows
    that are not a table, `koma_v1.5_unknown_ext.seq` has two."""
    data = read_seqfile(ORACLE / "koma_v1.5_unknown_ext.seq")
    assert data.skipped_extensions == ("UNKNOWN1", "UNKNOWN2")
    assert data.extensions.type_ids == {"UNKNOWN1": 1, "UNKNOWN2": 2}
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq").skipped_extensions == ("UNKNOWN",)


def test_a_file_whose_last_header_is_extensions_is_read():
    """D2.3: the specification is silent on the order of the sections; `spec` takes any order.
    `koma_v1.5_unknown_ext.seq` has `[EXTENSIONS]` as its last section that starts with `[` (its
    `extension` sections follow), which the C++ reader rejects."""
    path = ORACLE / "koma_v1.5_unknown_ext.seq"
    headers = [line for line in path.read_text().split("\n") if line.startswith("[")]
    assert headers[-1] == "[EXTENSIONS]"
    assert len(read_seqfile(path).blocks) > 0


def test_a_required_extension_that_is_not_known_is_extension_required_unknown():
    """spec:460 ("If any of the declared required extensions are unknown to the interpreter,
    it MUST generate an error and MUST not attempt executing the sequence"): from 1.5.1."""
    (violation,) = violations_of(SEQFILES / "bad_extension_required_unknown.seq").violations
    assert (violation.rule, violation.section) == ("extension.required-unknown", "DEFINITIONS")
    assert "required extension" in violation.message
    assert not carries_choice(violation)


def test_a_block_with_two_rotations_or_two_rf_shims_is_extension_per_block(tmp_path):
    """spec:567 and spec:584 ("Only one rotation extension object can be specified per
    block"; the same for RF shimming): `bad_extension_per_block.seq` has two blocks with two
    ROTATIONS objects each; below, a block with two RF_SHIMS objects."""
    error = violations_of(SEQFILES / "bad_extension_per_block.seq")
    assert [(v.rule, v.section) for v in error.violations] == [
        ("extension.per-block", "BLOCKS")
    ] * 2
    assert all("2 ROTATIONS objects" in v.message for v in error.violations)
    assert not any(carries_choice(v) for v in error.violations)
    text = _text("valid_no_signature.seq")
    text = text.replace("6 6 1 3\n", "6 6 1 8\n").replace("7 7 1 0\n", "7 7 1 0\n8 6 1 0\n")
    (violation,) = violations_of(_write(tmp_path, text, "shims.seq")).violations
    assert (violation.rule, violation.section) == ("extension.per-block", "BLOCKS")
    assert "2 RF_SHIMS objects" in violation.message


def test_rotation_quaternions_are_normalized_and_a_quaternion_of_norm_0_is_rejected(tmp_path):
    """D2.18, D3.10, P20, spec:567 ("a normalized rotation quaternion"): from 1.5.1 `spec` divides each
    quaternion of the `ROTATIONS` extension by its norm, so the model holds a quaternion of norm 1
    (`1 1.01 0 0 0` is `1 1 0 0 0`, `0 3 4 0` is `0 0.6 0.8 0`). A quaternion of norm 0 has no
    rotation: `rotation.zero` (the package's choice, which the message says). Applying the rotation
    is task R9's."""
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    norms = np.linalg.norm(
        np.array([data.extensions.rotations[k] for k in ("q0", "qx", "qy", "qz")]), axis=0
    )
    assert norms.tolist() == pytest.approx([1.0], rel=1e-12)
    text = _text("valid_no_signature.seq")
    old = "1 0.92388 0 0 0.382683"
    path = _write(tmp_path, text.replace(old, "1 1.01 0 0 0\n2 0 3 4 0"), "q.seq")
    rotations = read_seqfile(path).extensions.rotations
    assert rotations.tolist() == pytest.approx([(1, 1, 0, 0, 0), (2, 0, 0.6, 0.8, 0)])
    path = _write(tmp_path, text.replace(old, "1 0 0 0 0"), "zero.seq")
    (violation,) = violations_of(path).violations
    assert (violation.rule, violation.section) == ("rotation.zero", "extension ROTATIONS")
    assert carries_choice(violation)


def _line_of(path, text):
    """The number (from 1) of the first line of the file `path` that is `text`."""
    return path.read_text().split("\n").index(text) + 1


def test_what_spec_ignores_is_in_the_records_in_file_order(tmp_path):
    """P20, D2.4, D2.17, D2.19, D4.6: `SequenceData.records` has a `Record` (kind, subject,
    reason, line) for each extension, section and label that `spec` ignores. An unknown extension
    (`valid_1_5_1.seq`), an extension of a later revision (`valid_1_5_0_extensions_of_1_5_1.seq`:
    ROTATIONS and RF_SHIMS from 1.5.1), an unknown section (`bad_section_unknown.seq`), the
    removed `[DELAYS]` (`bad_section_delays.seq`), an unknown label (`valid_label_unknown.seq`)
    and a file that ignores nothing."""
    path = SEQFILES / "valid_1_5_1.seq"
    line = _line_of(path, "extension UNKNOWN 7")
    assert read_seqfile(path).records == (Record("extension", "UNKNOWN", "unknown", line),)
    path = SEQFILES / "valid_1_5_0_extensions_of_1_5_1.seq"
    expected = tuple(
        Record("extension", name, reason, _line_of(path, f"extension {name} {number}"))
        for name, number, reason in (
            ("ROTATIONS", 5, "version"),
            ("RF_SHIMS", 6, "version"),
            ("UNKNOWN", 7, "unknown"),
        )
    )
    assert read_seqfile(path).records == expected
    path = SEQFILES / "valid_label_unknown.seq"
    label = Record("label", "FOO", "unknown", _line_of(path, "1 0 FOO"))
    extension = Record("extension", "UNKNOWN", "unknown", _line_of(path, "extension UNKNOWN 7"))
    assert read_seqfile(path).records == (label, extension)
    for name, header, reason in (
        ("bad_section_unknown.seq", "[FOO]", "unknown"),
        ("bad_section_delays.seq", "[DELAYS]", "removed"),
    ):
        path = SEQFILES / name
        (record,) = (r for r in read_seqfile(path).records if r.kind == "section")
        assert record == Record("section", header, reason, _line_of(path, header))
    assert read_seqfile(SEQFILES / "valid_1_4_0.seq").records == ()


def test_the_records_of_labels_and_of_an_extension_of_a_later_revision(tmp_path):
    """D2.19, D4.6, spec:519-520, spec:526, spec:545: a label name that the specification does
    not list is `unknown` (`NOSCL`, a misspelling of `NOSLC`); a flag of 1.4.1 (PMC, NOROT,
    NOPOS, NOSLC, ONCE) in a 1.4.0 file is `version`, and none in a 1.4.1 file; `extension DELAYS`
    in a 1.4.1 file is `version`. The label rows stay in the label table."""
    text = _text("valid_1_4_1.seq")
    assert text.count("1 0 LIN\n") == 1
    edited = text.replace("1 0 LIN\n", "1 0 NOSCL\n")
    path = _write(tmp_path, edited, "noscl.seq")
    data = read_seqfile(path)
    assert data.records == (Record("label", "NOSCL", "unknown", _line_of(path, "1 0 NOSCL")),)
    assert data.extensions.labelset["name"].tolist() == ["NOSCL"]
    edited = text.replace("1 0 LIN\n", "1 0 PMC\n")
    assert read_seqfile(_write(tmp_path, edited, "pmc1.seq")).records == ()
    path = _write(tmp_path, edited.replace("revision 1\n", "revision 0\n"), "pmc0.seq")
    data = read_seqfile(path)
    assert data.records == (Record("label", "PMC", "version", _line_of(path, "1 0 PMC")),)
    assert data.extensions.labelset["name"].tolist() == ["PMC"]
    delays = "extension DELAYS 3\n1 0 -100 1 TE\n\nextension TRIGGERS 2"
    path = _write(tmp_path, text.replace("extension TRIGGERS 2", delays), "d.seq")
    expected = Record("extension", "DELAYS", "version", _line_of(path, "extension DELAYS 3"))
    assert read_seqfile(path).records == (expected,)


def test_a_label_that_is_not_known_is_kept_as_text(tmp_path):
    """D2.19, spec:519-520 (the counters and flags "supported at the moment"): `spec` keeps the name
    of any label as text, with no check (`valid_label_unknown.seq` has `FOO`). The labels PMC,
    NOROT, NOPOS, NOSLC and ONCE are new in 1.4.1 (spec:526); the name PMC is kept as text in a
    1.4.0 file, where it is not a label of the format, and in a 1.4.1 file."""
    data = read_seqfile(SEQFILES / "valid_label_unknown.seq")
    assert data.extensions.labelset.tolist() == [(1, 0, "FOO")]
    text = _text("valid_1_4_1.seq")
    assert text.count("1 0 LIN\n") == 1 and text.count("revision 1\n") == 1
    for revision in ("revision 0\n", "revision 1\n"):
        edited = text.replace("1 0 LIN\n", "1 0 PMC\n").replace("revision 1\n", revision)
        data = read_seqfile(_write(tmp_path, edited, "l.seq"))
        assert data.extensions.labelset["name"].tolist() == ["PMC"]


def test_two_events_with_equal_values_and_different_ids_are_both_kept():
    """spec:183 ("The ID of events within a single class must be unique"; no rule on equal
    events): `spec` keeps both, with their IDs. `pypulseq_simple_mprage150.seq` has the trapezoids
    39 and 40 with the amplitudes 0 and -0."""
    data = read_seqfile(ORACLE / "pypulseq_simple_mprage150.seq")
    rows = data.trap[np.isin(data.trap["id"], [39, 40])]
    assert rows["id"].tolist() == [39, 40]
    assert rows["amplitude"].tolist() == [0.0, -0.0]
    assert np.signbit(rows["amplitude"]).tolist() == [False, True]
    assert rows["rise"].tolist() == [1e-5, 1e-5]


def test_the_model_has_no_value_of_a_scanner():
    """The file has no dead time, ringdown time or default raster of a scanner, and the
    model has none either (see `test_model_without_values_of_a_target`): no change."""
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert {f.name for f in dataclasses.fields(data.rasters)} == {
        "gradient",
        "rf",
        "adc",
        "block_duration",
    }


def test_a_signature_hash_covers_the_bytes_before_the_newline_that_precedes_it():
    """spec:223: "The new line character preceding the keyword [SIGNATURE] is part of the
    signature and needs to be stripped away": `spec` strips one `\\n`. `valid_crlf.seq` (CRLF line
    ends) was signed by the rule of the C++ reader, which drops its `\\r\\n` empty line, so its
    hash does not match here (and the file is read); `valid_1_5_1.seq` matches."""
    assert read_seqfile(SEQFILES / "valid_1_5_1.seq").signature.matches is True
    crlf = read_seqfile(SEQFILES / "valid_crlf.seq")
    assert crlf.signature.matches is False
    assert len(crlf.blocks) == 9


def test_a_signature_section_must_have_a_type_and_a_hash(tmp_path):
    """spec:223-232: "The [SIGNATURE] section must contain two following fields", `Type`
    and `Hash`, "along with any additional information in the format identical to that of
    [DEFINITIONS]": a missing field, or a field of two values, is `signature.invalid`; an
    additional key reads. The last of a key repeated wins (the package's choice, D3.3)."""
    (violation,) = violations_of(SEQFILES / "bad_signature_invalid.seq").violations
    assert (violation.rule, violation.section) == ("signature.invalid", "SIGNATURE")
    text = _text("valid_1_5_1.seq")
    hash_line = "Hash 46631d7f179a1a0a028842b840aaac51"
    for bad in ("Hash a b", "Hash"):
        assert codes_of(_write(tmp_path, text.replace(hash_line, bad), "s.seq")) == {
            "signature.invalid"
        }
    assert codes_of(_write(tmp_path, text.replace("Type md5\n", ""), "t.seq")) == {
        "signature.invalid"
    }
    extra = read_seqfile(
        _write(tmp_path, text.replace("Type md5", "Type md5\nNote anything"), "e.seq")
    )
    assert extra.signature.matches is True
    last = read_seqfile(
        _write(tmp_path, text.replace(hash_line, "Hash 0000\n" + hash_line), "l.seq")
    )
    assert last.signature.matches is True


def test_an_extension_header_has_a_word_and_a_type_id(tmp_path):
    """D1.4, spec:493 (the table types `<STRING_ID>` as "integer"), spec:498, spec:507 (each
    example has a word, `extension TRIGGERS 1`, and the interpreter uses only the STRING_ID): `spec`
    reads the word as the STRING_ID and the integer as the type ID; a type that is not an integer
    is `syntax.integer`, and a header with another number of words is `syntax.columns`."""
    data = read_seqfile(SEQFILES / "valid_1_5_1.seq")
    assert data.extensions.type_ids["LABELSET"] == 1
    text = _text("valid_no_signature.seq")
    for header, rule in (
        ("extension LABELSET x", "syntax.integer"),
        ("extension LABELSET", "syntax.columns"),
        ("extension LABELSET 1 2", "syntax.columns"),
    ):
        path = _write(tmp_path, text.replace("extension LABELSET 1", header), "e.seq")
        assert rule in codes_of(path), header


@pytest.mark.parametrize("type_id", [0, -1])
@pytest.mark.parametrize(
    ("written", "changed", "section"),
    [
        ("extension UNKNOWN 7", "extension UNKNOWN {}", "extension UNKNOWN"),
        ("2 2 1 0", "2 {} 1 0", "EXTENSIONS"),
    ],
    ids=["header", "type column"],
)
def test_an_extension_type_id_that_is_not_positive_is_id_positive(
    tmp_path, written, changed, section, type_id
):
    """spec:181 ("IDs must be positive integers"), spec:472 and spec:494 (`<type>` is the "ID of
    the type"; decision Q4: the rule of spec:181 covers it): a type ID of 0 or less in the header
    `extension <STRING_ID> <type>` or in the `type` column of a row of `[EXTENSIONS]` is
    `id.positive`, at the section and the line of that ID."""
    line = changed.format(type_id)
    path = _write(tmp_path, _text("valid_no_signature.seq").replace(written, line), "e.seq")
    found = [(v.section, v.line) for v in violations_of(path).violations if v.rule == "id.positive"]
    assert found == [(section, _line_of(path, line))]


def test_the_extensions_of_a_later_revision_are_skipped_in_an_older_file(tmp_path):
    """The version gate (the user, 2026-10-12): `spec` reads each extension from the revision that
    introduced it: `extension DELAYS` from 1.5.0 (spec:545), ROTATIONS and RF_SHIMS from 1.5.1
    (spec:567, spec:584). In an older file such an extension is one that `spec` does not know:
    ignored (D2.17) and listed in `skipped_extensions`, its rows not read.
    `valid_1_5_0_extensions_of_1_5_1.seq` is a 1.5.0 file with all of them."""
    data = read_seqfile(SEQFILES / "valid_1_5_0_extensions_of_1_5_1.seq")
    assert data.skipped_extensions == ("ROTATIONS", "RF_SHIMS", "UNKNOWN")
    assert len(data.extensions.rotations) == 0
    assert len(data.extensions.rf_shims) == 0
    assert data.extensions.soft_delays.tolist() == [(1, 0, -1e-4, 1.0, "TE")]
    assert data.extensions.type_ids["ROTATIONS"] == 5
    text = _text("valid_1_4_1.seq")
    delays = "extension DELAYS 3\n1 0 not a row\n\nextension TRIGGERS 2"
    path = _write(tmp_path, text.replace("extension TRIGGERS 2", delays), "d.seq")
    old = read_seqfile(path)
    assert old.skipped_extensions == ("DELAYS",)
    assert len(old.extensions.soft_delays) == 0


def test_required_extensions_is_an_extension_rule_from_1_5_1_only(tmp_path):
    """The version gate: `RequiredExtensions` is from 1.5.1 (spec:460), so a 1.5.0 file with it
    reads, the definition as text and no required extension."""
    text = _text("valid_1_5_0.seq")
    path = _write(tmp_path, text.replace("Name valid_1_5_0", "RequiredExtensions FOO"), "r.seq")
    data = read_seqfile(path)
    assert data.definitions["RequiredExtensions"] == ("FOO",)
    assert data.required_extensions == ()


# ---- Other tests of the reading ----


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
    text = _text("valid_no_signature.seq")
    path = _write(tmp_path, text.replace("# NUM DUR", "# duration in µs, NUM DUR"), "mu.seq")
    assert read_seqfile(path) == read_seqfile(SEQFILES / "valid_no_signature.seq")


def test_comments_and_blank_lines_between_sections_are_read_as_nothing():
    plain = read_seqfile(SEQFILES / "valid_comments_between_sections.seq")
    assert plain.skipped_extensions == ()
    assert plain.blocks["id"].tolist() == list(range(1, 10))
    assert len(plain.shapes) == 9 and len(plain.extensions.labelset) == 1


def test_sample_lines_of_two_values_are_syntax_number(tmp_path):
    """A sample line is one finite number, also when every sample line of the file has two
    values: the message has no choice (a line of two numbers is not a number)."""
    text = _text("valid_no_signature.seq")
    two = re.sub(r"^(-?[0-9.]+)$", r"\1 0", text, flags=re.MULTILINE)
    error = violations_of(_write(tmp_path, two, "two.seq"))
    assert {v.rule for v in error.violations} == {"syntax.number"}
    assert error.violations[0].message.endswith("is not one finite number")


def test_a_nan_or_inf_shape_sample_is_syntax_number_with_the_choice(tmp_path):
    """D3.5: a shape sample that is NaN or infinite is a number that the specification does not rule
    on (the package's choice, in the message); a sample that is not a number (`1,5`) is not."""
    text = _text("valid_no_signature.seq")
    for sample, choice in (("nan", True), ("inf", True), ("1,5", False), ("+0.4", None)):
        path = _write(tmp_path, text.replace("0.3\n0.4\n0.5\n", f"0.3\n{sample}\n0.5\n"), "n.seq")
        if choice is None:
            assert read_seqfile(path).shapes[3].packed[3] == 0.4  # a sign is part of a float
            continue
        (violation,) = violations_of(path).violations
        assert (violation.rule, carries_choice(violation)) == ("syntax.number", choice)


def test_the_same_file_with_revision_1_5_1_reads_the_1_5_1_extensions(tmp_path):
    """The version gate: the same file with `revision 1` reads ROTATIONS and RF_SHIMS."""
    text = _text("valid_1_5_0_extensions_of_1_5_1.seq").replace("revision 0", "revision 1")
    data = read_seqfile(_write(tmp_path, text, "g.seq"))
    assert data.skipped_extensions == ("UNKNOWN",)
    assert len(data.extensions.rotations) == 1 and len(data.extensions.rf_shims) == 1


def test_random_edits_of_valid_files_give_a_model_or_a_seqfile_error(tmp_path):
    """Whatever the edit, the reader gives a model, or `SeqFileError` with a violation. It
    raises no other exception."""
    rng = np.random.default_rng(11)
    texts = [
        _text(name)
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
        except NotSupported:
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
        "records",
        "signature",
        "origin",
        "interpreter",
        "reading",
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
    text = _text("valid_1_4_1.seq").replace("1 1000 1 2 0 100 0 0", "1 1001 1 2 0 100 0 0")
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
    assert radial.extensions.rotations["q0"].tolist() == pytest.approx(
        [1.0, 0.92388, 0.707107], rel=1e-5
    )
