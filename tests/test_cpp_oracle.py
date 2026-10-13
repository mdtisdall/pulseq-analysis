"""Tests of the C++ oracle: the reader `ExternalSequence` of pulseq/pulseq (the reader of the
Pulseq interpreter on the scanner), built by `flake.nix` as `pulseq-cpp-oracle` from the driver in
`tests/cpp_oracle/`. The oracle accepts a file when `load` succeeds and `decodeBlock` succeeds for
each block.

The module skips when the binary is not on the PATH, as outside the Nix devShell.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
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

# The rules of `read_strict` (the docstring of `pulseq_analysis.seqfile.reader` lists them) that
# the oracle does not check, in `load` or in `decodeBlock`, so it may accept a file that breaks only
# these rules. The value says what the oracle accepted: a fixture of `tests/seqfiles/`, or a
# change to a valid 1.5.0 file of four blocks (RF, trapezoid, arbitrary gradient, ADC and delay
# events) that was tried by hand. A rule that is not here, such as `version.missing` and
# `shape.event-length`, is one where the oracle rejected or crashed on the fixture of the rule.
# A crash can depend on the build (the macOS clang build and the Linux gcc build of CI differ on
# some fixtures), so a rule is here when either build accepts its fixture.
NOT_CHECKED_BY_THE_READER = {
    "version.invalid": "`bad_version_invalid.seq`",
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
    "syntax.shape": "`bad_syntax_shape_no_blank_line.seq` (accepted by the Linux build; the "
    "macOS build crashes on its unknown extension)",
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
    "shape.empty": "`bad_shape_empty.seq` (accepted by the Linux build; the macOS build crashes: "
    "it indexes an empty vector, ExternalSequence.cpp:1995 and 2203)",
    "shape.rf-magnitude-negative": "`bad_shape_rf_magnitude_negative.seq` (the reader sets a "
    "negative sample to 0 in `checkRF`)",
    "shape.rf-phase-range": "`bad_shape_rf_phase_range.seq` (the reader clamps the phase to "
    "[0, 2 pi - 1e-4] in `checkRF`)",
    "shape.rf-time-end": "`bad_shape_rf_time_end.seq` (accepted by the Linux build; the macOS "
    "build crashes: its resampling loop reads past the stored samples, "
    "ExternalSequence.cpp:2039-2045)",
    "shape.rf-time-grid": "`bad_shape_rf_time_grid.seq` (the reader takes the shape `1 1 98` as "
    "regular and ignores its first time)",
    "extension.per-block": "`bad_extension_per_block.seq`",
    "layer1.gradient-ends": "`bad_layer1_gradient_ends.seq`",
    "signature.invalid": "`bad_signature_invalid.seq`",
}


# Files under tests/seqfiles that the oracle does not accept and `read_strict` accepts, where the
# oracle is wrong against the specification. The comparison test skips them. Each entry has the
# reason.
ORACLE_KNOWN_WRONG = {
    "oracle/koma_v1.5_unknown_ext.seq": 'the oracle fails with "failed find the end of the '
    'section while reading EXTENSIONS" because `[EXTENSIONS]` is the last section that starts '
    "with `[` (its index of sections has only those lines, ExternalSequence.cpp:1762-1769, "
    "1202-1211); the same file with a `[SIGNATURE]` section at the end is accepted. The "
    "specification does not fix the order of the sections (docs/discrepancies.md, D46)",
    "undefined/version_last.seq": "with `[VERSION]` as the last section, the oracle reads no "
    "shape (the stream stays failed after it reads `[VERSION]` to the end of the file), and the "
    "RF event names shape 1: undefined behaviour (ExternalSequence.cpp:1995, "
    "`tests/test_cpp_oracle_sanitized.py`). The specification does not fix the order of the "
    "sections (docs/discrepancies.md, D05)",
}


# The reason why the comparison of the accept/reject verdicts skips a file that `read_strict`
# accepts and that has an arbitrary gradient on a gradient raster other than 10 us: `decodeBlock`
# returns false for the block (ExternalSequence.cpp:2114-2119, "Shape is on a raster that is
# different from the system raster").
SKIPPED_ARBITRARY_GRADIENT_RASTER = (
    "an arbitrary gradient on a gradient raster other than 10 us: decodeBlock fails"
)


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


def arbitrary_gradient_off_the_10_us_raster(data):
    """True for a model (`SequenceData`) where a block uses an arbitrary gradient (a row of
    `grad`) and the gradient raster is not 10 us, to the 1e-3 us that the reader allows."""
    used = np.concatenate([data.blocks[column] for column in ("gx", "gy", "gz")])
    uses_arbitrary_gradient = np.isin(used, data.grad["id"][data.grad["id"] != 0]).any()
    return bool(uses_arbitrary_gradient and abs(data.rasters.gradient * 1e6 - 10) > 1e-3)


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


def test_the_oracle_rejects_an_arbitrary_gradient_on_a_4_us_raster_and_accepts_it_on_10_us(
    tmp_path,
):
    """The skip of the comparison is needed: the oracle rejects the valid fixture because of the
    raster, and accepts the same file on the raster of 10 us."""
    fixture = SEQFILES / "valid_arbitrary_gradient_4us_raster.seq"
    verdict, messages = run_oracle(fixture)
    assert verdict == "reject", messages
    assert "decodeBlock returned false for block 0" in messages
    text = fixture.read_text()
    changed = text.replace("GradientRasterTime 4e-06", "GradientRasterTime 1e-05")
    changed = changed.replace("1   5  0  1  0  0  0  0", "1  10  0  1  0  0  0  0")
    assert changed.count("1e-05") == 2 and "1  10  0  1" in changed
    path = tmp_path / "10us.seq"
    path.write_text(changed)
    verdict, messages = run_oracle(path)
    assert verdict == "accept", messages


def test_the_skip_of_the_comparison_is_for_an_arbitrary_gradient_off_the_10_us_raster_only(
    tmp_path,
):
    reader = pytest.importorskip("pulseq_analysis.seqfile.reader")

    def skipped(path):
        return arbitrary_gradient_off_the_10_us_raster(reader.read_strict(path))

    fixture = SEQFILES / "valid_arbitrary_gradient_4us_raster.seq"
    assert skipped(fixture)
    assert not skipped(SEQFILES / "valid_1_5_1.seq")  # arbitrary gradients on 10 us
    # The same file with a trapezoid in place of the arbitrary gradient is not skipped.
    text = fixture.read_text()
    trapezoid = text.replace("[GRADIENTS]", "[TRAP]").replace(
        "1 500000 0 0 1 0 0", "1 500000 8 16 8 0"
    )
    assert trapezoid != text
    path = tmp_path / "trap.seq"
    path.write_text(trapezoid)
    assert not skipped(path)


def signature_ok(path):
    """`signature_ok` of the dump of the oracle for a file: whether the md5 of the file, as the
    oracle computes it, is the stored one."""
    result = subprocess.run(
        [ORACLE, "--dump", str(path)], capture_output=True, text=True, timeout=TIMEOUT, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["signature_ok"]


def signature_variants():
    """(name, the bytes of a file up to the line `[SIGNATURE]`, the bytes that the hash covers,
    the line end). The hash covers every byte before `[SIGNATURE]` except one empty line right
    before it (the oracle holds back an empty line and drops it at `[SIGNATURE]`)."""
    lf = MINIMAL_SEQ.rstrip("\n").encode()
    crlf = lf.replace(b"\n", b"\r\n")
    return [
        ("lf-one-empty-line", lf + b"\n\n", lf + b"\n", b"\n"),
        ("lf-no-empty-line", lf + b"\n", lf + b"\n", b"\n"),
        ("lf-spaces-on-the-line", lf + b"\n\n  \n", lf + b"\n\n  \n", b"\n"),
        ("crlf-one-empty-line", crlf + b"\r\n\r\n", crlf + b"\r\n", b"\r\n"),
        ("crlf-no-empty-line", crlf + b"\r\n", crlf + b"\r\n", b"\r\n"),
        ("lf-file-with-a-crlf-empty-line", lf + b"\n\r\n", lf + b"\n", b"\n"),
        # The reader reads at most 255 bytes of a line at a time, so the line end of a line of
        # 255 bytes comes alone as the next line, which is empty.
        (
            "long-line-then-its-line-end",
            lf + b"\n\n#" + b"x" * 254 + b"\n",
            lf + b"\n\n#" + b"x" * 254,
            b"\n",
        ),
        (
            "line-of-255-bytes-with-its-end",
            lf + b"\n\n#" + b"x" * 253 + b"\n",
            lf + b"\n\n#" + b"x" * 253 + b"\n",
            b"\n",
        ),
    ]


@pytest.mark.parametrize(
    ("before", "hashed", "newline"),
    [v[1:] for v in signature_variants()],
    ids=[v[0] for v in signature_variants()],
)
def test_the_oracle_and_read_strict_check_the_same_signature_hash(
    tmp_path, before, hashed, newline
):
    reader = pytest.importorskip("pulseq_analysis.seqfile.reader")
    digest = hashlib.md5(hashed).hexdigest().encode()
    tail = b"[SIGNATURE]" + newline + b"Type md5" + newline + b"Hash "
    path = tmp_path / "signed.seq"
    path.write_bytes(before + tail + digest + newline)
    assert signature_ok(path) is True
    assert reader.read_strict(path).signature.matches is True
    # A hash of other bytes matches in neither reader.
    path.write_bytes(before + tail + hashlib.md5(before + b"x").hexdigest().encode() + newline)
    assert signature_ok(path) is False
    assert reader.read_strict(path).signature.matches is False


def test_the_oracle_and_read_strict_accept_and_reject_the_same_files(record_property):
    reader = pytest.importorskip("pulseq_analysis.seqfile.reader")
    paths = sorted(SEQFILES.rglob("*.seq"))
    if not paths:
        pytest.skip(f"no .seq file in {SEQFILES}")
    differences = []
    skipped = []
    for path in paths:
        if path.relative_to(SEQFILES).as_posix() in ORACLE_KNOWN_WRONG:
            continue
        try:
            data = reader.read_strict(path)
        except reader.NotSupported:
            continue  # a version outside 1.4.0-1.5.x (Q1): neither interpreter reads it
        except reader.SeqFileError as error:
            rules = {violation.rule for violation in error.violations}
            verdict, messages = run_oracle(path)
            # A file that breaks only rules which the oracle does not check may be accepted.
            if verdict == "accept" and not all(not_checked(rule) for rule in rules):
                differences.append(f"{path}: read_strict rejects {sorted(rules)}, oracle accepts")
            continue
        if arbitrary_gradient_off_the_10_us_raster(data):
            skipped.append(path.relative_to(SEQFILES).as_posix())
            continue
        verdict, messages = run_oracle(path)
        if verdict != "accept":
            differences.append(f"{path}: read_strict accepts, oracle: {verdict}\n{messages}")
    record_property(
        "skipped",
        f"{len(skipped)} files skipped, {SKIPPED_ARBITRARY_GRADIENT_RASTER}: {', '.join(skipped)}",
    )
    assert not differences, "\n".join(differences)
