"""Tests of the C++ oracle: the reader `ExternalSequence` of pulseq/pulseq (the reader of the
Pulseq interpreter on the scanner), built by `flake.nix` as `pulseq-cpp-oracle` from the driver in
`tests/cpp_oracle/`. The oracle accepts a file when `load` succeeds and `decodeBlock` succeeds for
each block.

The module skips when the binary is not on the PATH, as outside the Nix devShell.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ORACLE = shutil.which("pulseq-cpp-oracle")

pytestmark = pytest.mark.skipif(ORACLE is None, reason="pulseq-cpp-oracle is not on the PATH")

# The reader gets this long for a file. A process that does not end in this time counts as a
# crash. A cycle in an extension list makes the reader loop with no end
# (`tests/seqfiles/bad_ref_extension_cycle.seq`: no end in 10 s), so this is the time that such a
# file costs.
TIMEOUT = 10

# A Pulseq 1.5.0 file of one block, with a delay of 1 ms and no event.
MINIMAL_SEQ = """\
[VERSION]
major 1
minor 5
revision 0

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

[BLOCKS]
1 100 0 0 0 0 0 0
"""

# The rules of `read_seqfile` (the docstring of `pulseq_analysis.seqfile` lists them) that the
# oracle does not check, in `load` or in `decodeBlock`, so it may accept a file that breaks only
# these rules. The value says what the oracle accepted: a fixture of `tests/seqfiles/`, or a
# change to a valid 1.5.0 file of four blocks (RF, trapezoid, arbitrary gradient, ADC and delay
# events) that was tried by hand. A rule that is not here, such as `version.missing`,
# `syntax.shape` and `shape.event-length`, is one where the oracle rejected or crashed on the
# fixture of the rule.
NOT_CHECKED_BY_THE_READER = {
    "version.invalid": "`bad_version_invalid.seq`",
    "version.unsupported": "version 1.6.0 (`bad_version_unsupported_1_6.seq`) and version 2.0.0 "
    "(it rejects 1.3.0)",
    "definitions.duplicate": "`bad_definitions_duplicate.seq`",
    "definitions.raster-invalid": "a raster of 0 or of -1e-5 for AdcRasterTime, "
    "BlockDurationRaster and RadiofrequencyRasterTime (it rejects 0 and -1e-5 for "
    "GradientRasterTime, in `decodeBlock`, and nan and inf for each raster, as a missing "
    "definition)",
    "section.unknown": "`bad_section_unknown.seq`",
    "section.delays": "`bad_section_delays.seq`",
    "section.duplicate": "`bad_section_duplicate.seq`",
    "syntax.encoding": "`bad_syntax_encoding.seq`",
    "syntax.line": "`bad_syntax_line.seq`",
    "syntax.columns": "`bad_syntax_columns.seq`",
    "syntax.integer": "`bad_syntax_integer_plus.seq` (it rejects `126.5` and `1e2` in an integer "
    "column, `bad_syntax_integer.seq`)",
    "syntax.number": "`bad_syntax_number.seq`",
    "syntax.use": "`bad_syntax_use.seq`",
    "syntax.negative": "`bad_syntax_negative.seq`",
    "id.positive": "`bad_id_positive.seq`",
    "id.unique": "`bad_id_unique.seq` and `bad_id_unique_block.seq`",
    "id.gradient-unique": "`bad_id_gradient_unique.seq`",
    "ref.unresolved": "`bad_ref_extension_entry.seq`, `bad_ref_extension_object.seq`, "
    "`bad_ref_extension_type.seq` and `bad_ref_time_id_minus_1_in_1_4.seq` (it rejects a block "
    "that names an RF, gradient, trapezoid or ADC event that does not exist, and it crashes or "
    "rejects in `decodeBlock` on a missing shape: `bad_ref_shape.seq`, "
    "`bad_ref_time_shape.seq`)",
    "blocks.empty": "`bad_blocks_empty.seq`",
    "blocks.order": "`bad_blocks_order.seq`",
    "block.event-too-long": "`bad_block_event_too_long_adc.seq`, "
    "`bad_block_event_too_long_rf.seq` and `bad_block_event_too_long_trigger.seq`",
    "raster.adc-dwell": "`bad_raster_adc_dwell.seq`",
    "raster.gradient-delay": "`bad_raster_gradient_delay.seq`",
    "raster.gradient-end": "`bad_raster_gradient_end.seq`",
    "raster.gradient-ramp": "`bad_raster_gradient_ramp.seq`",
    "raster.gradient-flat": "`bad_raster_gradient_flat.seq`",
    "gradient.nonzero-start-delay": "`bad_gradient_nonzero_start_delay.seq`",
    "gradient.nonzero-end-align": "`bad_gradient_nonzero_end_align.seq`",
    "shape.length": "`bad_shape_length.seq` (it crashes or rejects a shape with `num_samples` of "
    "0, in `decodeBlock`)",
    "shape.range": "`bad_shape_range.seq`",
    "extension.per-block": "`bad_extension_per_block.seq`",
    "layer1.gradient-ends": "`bad_layer1_gradient_ends.seq`",
    "signature.invalid": "`bad_signature_invalid.seq`",
}


# Files under tests/seqfiles that the oracle rejects and `read_seqfile` accepts, where the oracle
# is wrong against the specification. The comparison test skips them. Each entry has the reason.
ORACLE_KNOWN_WRONG = {
    "oracle/koma_v1.5_unknown_ext.seq": 'the oracle fails with "failed find the end of the '
    'section while reading EXTENSIONS" on the rows of an extension that it does not know and '
    "that the file does not require; section 2.8.4 of the specification says that the "
    "interpreter MUST detect unknown extensions and MAY ignore them",
}


def run_oracle(path):
    """The verdict of the oracle on a file and its messages. The verdict is "accept" (exit 0),
    "reject" (exit 1) or "crash" (a signal, a timeout or another exit status)."""
    try:
        result = subprocess.run(
            [ORACLE, str(path)], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return "crash", f"no end after {TIMEOUT} s"
    messages = result.stdout + result.stderr
    if result.returncode == 0:
        return "accept", messages
    if result.returncode == 1:
        return "reject", messages
    return "crash", f"exit status {result.returncode}\n{messages}"


def not_checked(rule):
    """True when the oracle does not check this rule."""
    return rule in NOT_CHECKED_BY_THE_READER


def test_the_oracle_accepts_a_minimal_valid_file(tmp_path):
    path = tmp_path / "minimal.seq"
    path.write_text(MINIMAL_SEQ)
    verdict, messages = run_oracle(path)
    assert verdict == "accept", messages


@pytest.mark.parametrize(
    "removed",
    [r"GradientRasterTime .*\n", r"\[VERSION\]\nmajor 1\nminor 5\nrevision 0\n\n"],
    ids=["GradientRasterTime", "VERSION"],
)
def test_the_oracle_rejects_a_file_without_a_required_part(tmp_path, removed):
    text = re.sub(removed, "", MINIMAL_SEQ)
    assert text != MINIMAL_SEQ
    path = tmp_path / "broken.seq"
    path.write_text(text)
    verdict, messages = run_oracle(path)
    assert verdict == "reject", messages
    assert "ERROR" in messages


def rf_seq(shapes, time_id=0):
    """The minimal file with one block of 110 us and one RF event of 6 samples, with the shapes
    1 (magnitude) and 2 (phase), the time shape `time_id` and the `[SHAPES]` section `shapes`."""
    return MINIMAL_SEQ.replace("1 100 0 0 0 0 0 0", "1 11 1 0 0 0 0 0") + (
        f"\n[RF]\n1 1000 1 2 {time_id} 0 10 0 0 0 0 u\n\n[SHAPES]\n{shapes}"
    )


def shape(shape_id, values):
    return f"shape_id {shape_id}\nnum_samples {len(values)}\n" + "\n".join(values) + "\n\n"


@pytest.mark.parametrize(
    "text",
    [
        rf_seq(shape(1, ["0.5"] * 6)),
        rf_seq(shape(1, ["0.5"] * 6) + shape(2, ["0"] * 6), time_id=7),
        rf_seq(shape(1, ["0.5"] * 6) + shape(2, [])),
    ],
    ids=["missing-phase-shape", "missing-time-shape", "empty-phase-shape"],
)
def test_the_oracle_does_not_accept_a_file_that_it_cannot_decode(tmp_path, text):
    path = tmp_path / "undecodable.seq"
    path.write_text(text)
    verdict, messages = run_oracle(path)
    assert verdict in {"reject", "crash"}, messages


def test_the_oracle_accepts_the_rf_file_with_both_shapes(tmp_path):
    path = tmp_path / "rf.seq"
    path.write_text(rf_seq(shape(1, ["0.5"] * 6) + shape(2, ["0"] * 6)))
    verdict, messages = run_oracle(path)
    assert verdict == "accept", messages


def test_the_oracle_and_read_seqfile_accept_and_reject_the_same_files():
    seqfile = pytest.importorskip("pulseq_analysis.seqfile")
    paths = sorted(SEQFILES.rglob("*.seq"))
    if not paths:
        pytest.skip(f"no .seq file in {SEQFILES}")
    differences = []
    for path in paths:
        if path.relative_to(SEQFILES).as_posix() in ORACLE_KNOWN_WRONG:
            continue
        verdict, messages = run_oracle(path)
        try:
            seqfile.read_seqfile(path)
        except seqfile.SeqFileError as error:
            rules = {violation.rule for violation in error.violations}
            # A file that breaks only rules which the oracle does not check may be accepted.
            if verdict == "accept" and not all(not_checked(rule) for rule in rules):
                differences.append(f"{path}: read_seqfile rejects {sorted(rules)}, oracle accepts")
        else:
            if verdict != "accept":
                differences.append(f"{path}: read_seqfile accepts, oracle: {verdict}\n{messages}")
    assert not differences, "\n".join(differences)
