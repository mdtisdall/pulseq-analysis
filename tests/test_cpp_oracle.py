"""Tests of the C++ oracle: the reader `ExternalSequence` of pulseq/pulseq (the reader of the
Pulseq interpreter on the scanner), built by `flake.nix` as `pulseq-cpp-oracle` from the driver in
`tests/cpp_oracle/`. The oracle accepts a file when `load` succeeds and `decodeBlock` succeeds for
each block. The comparison with the package is with the `spec` interpreter (the default of
`seqfile.read_seqfile`): the tables below list each file where its verdict differs from the
oracle's, with the entry of `docs/discrepancies.md` that explains it.

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

from pulseq_analysis import seqfile
from pulseq_analysis.seqfile import as_written

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

# The files of `tests/seqfiles` that `spec` rejects and that the oracle accepts, or accepts on one
# of its builds, because it does not check the rule that they break: so the comparison of the
# verdicts lets the oracle accept them. The value is the entry of `docs/discrepancies.md` that
# explains the difference, and what the oracle did with the file when it is not that it accepted
# it. A crash can depend on the build (the macOS clang build and the Linux gcc build of CI differ
# on some fixtures), so a file is here when either build accepts it. A file that `spec` rejects and
# that is not here is one that the oracle rejected or crashed on, on each build.
NOT_CHECKED_BY_THE_READER = {
    "bad_block_event_too_long_adc.seq": "D25",
    "bad_block_event_too_long_rf.seq": "D25",
    "bad_block_event_too_long_trigger.seq": "D25",
    "bad_blocks_empty.seq": "D24",
    "bad_extension_per_block.seq": "D48",
    "bad_gradient_nonzero_end_align.seq": "D27",
    "bad_gradient_nonzero_start_delay.seq": "D27",
    "bad_id_gradient_unique.seq": "D19",
    "bad_id_positive.seq": "D19",
    "bad_id_unique.seq": "D19",
    "bad_id_unique_block.seq": "D19",
    "bad_layer1_gradient_ends.seq": "D39",
    "bad_raster_adc_delay.seq": "D26",
    "bad_raster_adc_dwell.seq": "D26",
    "bad_raster_gradient_delay.seq": "D26",
    "bad_raster_gradient_end.seq": "D26",
    "bad_raster_gradient_flat.seq": "D26",
    "bad_raster_gradient_ramp.seq": "D26",
    "bad_raster_gradient_vertex.seq": "D26",
    "bad_raster_rf_delay.seq": "D26",
    "bad_ref_extension_entry.seq": "D21",
    "bad_ref_extension_object.seq": "D21",
    "bad_ref_extension_type.seq": "D21",
    "bad_ref_time_id_minus_1_in_1_4.seq": "D22",
    "bad_section_duplicate.seq": "D10",
    "bad_section_duplicate_extension.seq": "D10",
    "bad_section_duplicate_signature.seq": "D10",
    "bad_shape_adc_phase_length.seq": "D44",
    "bad_shape_empty.seq": "D33 (accepted by the Linux build; the macOS build crashes: it indexes "
    "an empty vector, ExternalSequence.cpp:1995 and 2203)",
    "bad_shape_length.seq": "D29",
    "bad_shape_oversampled_length.seq": "D43",
    "bad_shape_range.seq": "D30",
    "bad_shape_time_order.seq": "D36",
    "bad_signature_invalid.seq": "D54",
    "bad_syntax_columns.seq": "D14",
    "bad_syntax_encoding.seq": "D14",
    "bad_syntax_line.seq": "D06",
    "bad_syntax_negative.seq": "D14",
    "bad_syntax_number.seq": "D14",
    "bad_syntax_shape_no_blank_line.seq": "D07 (accepted by the Linux build; the macOS build "
    "crashes on its unknown extension)",
    "bad_syntax_use.seq": "D17",
    "bad_version_invalid.seq": "D04",
    "oracle/koma_v1.4_gr-uniformly-shaped.seq": "D39",
    "oracle/pypulseq_simple_mprage140.seq": "D39",
    "undefined/shape_decompress_longer.seq": "D29 (the macOS build accepts it; the sanitized "
    "build finds a heap buffer overflow, `tests/test_cpp_oracle_sanitized.py`)",
}


# Files under tests/seqfiles that the oracle does not accept (or, on one build, crashes on) and
# `spec` accepts, where the oracle is wrong against the specification or `spec` reads what it
# does not. The comparison test skips them. Each entry has the entry of `docs/discrepancies.md`
# and the reason.
ORACLE_KNOWN_WRONG = {
    "bad_shape_rf_time_end.seq": "D36: the oracle crashes on the macOS build and accepts on the "
    "Linux build: its resampling loop reads past the stored samples, ExternalSequence.cpp:2039-"
    "2045. `spec` reads the shape as points",
    "bad_syntax_line_after_comment.seq": "D06: the oracle reads a `#` line inside a table as a "
    "row, its decoding fails and `load` returns false (`cpp-siemens`: `syntax.comment-row`); "
    "`spec` skips it",
    "oracle/koma_v1.5_unknown_ext.seq": 'D46: the oracle fails with "failed find the end of the '
    'section while reading EXTENSIONS" because `[EXTENSIONS]` is the last section that starts '
    "with `[` (its index of sections has only those lines, ExternalSequence.cpp:1762-1769, "
    "1202-1211); the same file with a `[SIGNATURE]` section at the end is accepted. The "
    "specification does not fix the order of the sections",
    "undefined/version_last.seq": "D05: with `[VERSION]` as the last section, the oracle reads no "
    "shape (the stream stays failed after it reads `[VERSION]` to the end of the file), and the "
    "RF event names shape 1: undefined behaviour (ExternalSequence.cpp:1995, "
    "`tests/test_cpp_oracle_sanitized.py`). The specification does not fix the order of the "
    "sections",
    "valid_comment_in_shape.seq": "D06: the oracle reads a `#` line inside a shape's samples as "
    "a sample and fails to decode it (`cpp-siemens`: `syntax.comment-row`); `spec` skips it",
    "valid_last_section_no_blank.seq": "D56: the last section has no blank line after its row, so "
    "the oracle's stream fails at the end of the file and it skips [DEFINITIONS] "
    "(`cpp-siemens`: `definitions.skipped`); `spec` reads it",
    "valid_rf_time_shapes.seq": "D36: the oracle crashes on the macOS build, and `cpp-siemens` "
    "rejects it with `ub.rf-time-overrun`: the resampling of the pulse with the uncompressed "
    "time shape `0.5 1.5 2.5` reads past the stored samples; `spec` reads it as cells of 1 us",
}


# The reason why the comparison of the accept/reject verdicts skips a file that `spec`
# accepts and that has an arbitrary gradient on a gradient raster other than 10 us: `decodeBlock`
# returns false for the block (ExternalSequence.cpp:2114-2119, "Shape is on a raster that is
# different from the system raster"). The entry of the difference is D28.
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


def test_the_oracle_rejects_an_arbitrary_gradient_on_a_5_us_raster_and_accepts_it_on_10_us(
    tmp_path,
):
    """The skip of the comparison is needed: the oracle rejects the file that `spec` reads
    because of the raster (D28), and accepts the same file on the raster of 10 us."""
    fixture = SEQFILES / "valid_arbitrary_gradient_5us_raster.seq"
    verdict, messages = run_oracle(fixture)
    assert verdict == "reject", messages
    assert "decodeBlock returned false for block 0" in messages
    text = fixture.read_text()
    changed = text.replace("GradientRasterTime 5e-06", "GradientRasterTime 1e-05")
    changed = changed.replace("1   5  0  1  0  0  0  0", "1  10  0  1  0  0  0  0")
    assert changed.count("1e-05") == 2 and "1  10  0  1" in changed
    path = tmp_path / "10us.seq"
    path.write_text(changed)
    verdict, messages = run_oracle(path)
    assert verdict == "accept", messages


def test_the_skip_of_the_comparison_is_for_an_arbitrary_gradient_off_the_10_us_raster_only(
    tmp_path,
):
    def skipped(path):
        return arbitrary_gradient_off_the_10_us_raster(seqfile.read_seqfile(path))

    fixture = SEQFILES / "valid_arbitrary_gradient_5us_raster.seq"
    assert skipped(fixture)
    assert not skipped(SEQFILES / "valid_1_5_1.seq")  # arbitrary gradients on 10 us
    # The same file with a trapezoid in place of the arbitrary gradient is not skipped.
    text = fixture.read_text()
    trapezoid = text.replace("[GRADIENTS]", "[TRAP]").replace(
        "1 500000 0 0 1 0 0", "1 500000 5 10 5 0"
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


# The variants of `signature_variants` that `spec` and the oracle give the same hash: the usual
# LF file, with one empty line before `[SIGNATURE]`.
SAME_SIGNATURE_HASH = {"lf-one-empty-line", "long-line-then-its-line-end"}


@pytest.mark.parametrize(
    ("before", "hashed", "newline"),
    [v[1:] for v in signature_variants() if v[0] in SAME_SIGNATURE_HASH],
    ids=[v[0] for v in signature_variants() if v[0] in SAME_SIGNATURE_HASH],
)
def test_the_oracle_and_spec_check_the_same_signature_hash_of_an_lf_file(
    tmp_path, before, hashed, newline
):
    digest = hashlib.md5(hashed).hexdigest().encode()
    tail = b"[SIGNATURE]" + newline + b"Type md5" + newline + b"Hash "
    path = tmp_path / "signed.seq"
    path.write_bytes(before + tail + digest + newline)
    assert signature_ok(path) is True
    assert seqfile.read_seqfile(path).signature.matches is True
    # A hash of other bytes matches in neither reader.
    path.write_bytes(before + tail + hashlib.md5(before + b"x").hexdigest().encode() + newline)
    assert signature_ok(path) is False
    assert seqfile.read_seqfile(path).signature.matches is False


@pytest.mark.parametrize(
    ("before", "hashed", "newline"),
    [v[1:] for v in signature_variants() if v[0] not in SAME_SIGNATURE_HASH],
    ids=[v[0] for v in signature_variants() if v[0] not in SAME_SIGNATURE_HASH],
)
def test_spec_hashes_the_bytes_before_the_newline_before_signature_where_the_oracle_does_not(
    tmp_path, before, hashed, newline
):
    """D53: `spec` uses the rule of the specification (spec:223): the hash covers the bytes
    before the `\\n` that precedes `[SIGNATURE]`. The oracle drops an empty line only, and keeps
    the `\\r` of a CRLF line end, so the two hashes differ."""
    by_the_specification = before[:-1]
    assert by_the_specification != hashed
    tail = b"[SIGNATURE]" + newline + b"Type md5" + newline + b"Hash "
    path = tmp_path / "signed.seq"
    for covered, in_the_oracle, in_spec in [
        (hashed, True, False),
        (by_the_specification, False, True),
    ]:
        digest = hashlib.md5(covered).hexdigest().encode()
        path.write_bytes(before + tail + digest + newline)
        assert signature_ok(path) is in_the_oracle
        assert seqfile.read_seqfile(path).signature.matches is in_spec


def test_the_signature_of_a_crlf_file_matches_in_the_oracle_and_not_in_spec():
    """D53: `valid_crlf.seq` is signed by the rule of the C++ reader. The hash that `spec`
    computes is that of the bytes before the `\\n` before `[SIGNATURE]`, which keep the `\\r` of
    the empty line. Both read the file."""
    path = SEQFILES / "valid_crlf.seq"
    assert signature_ok(path) is True
    assert seqfile.read_seqfile(path).signature.matches is False
    signed = as_written.read_as_written(path).signed_bytes()
    assert signed.endswith(b"\r")


def test_the_oracle_and_spec_accept_and_reject_the_same_files_but_those_of_the_tables(
    record_property,
):
    """Each file of `tests/seqfiles`: `spec` and the oracle give the same verdict, except the
    files of `ORACLE_KNOWN_WRONG` (skipped), those of `NOT_CHECKED_BY_THE_READER` (`spec` rejects
    them, the oracle may accept) and the files with an arbitrary gradient off the 10 us raster
    (skipped). A version outside 1.4.0-1.5.x is not read by either."""
    paths = sorted(SEQFILES.rglob("*.seq"))
    if not paths:
        pytest.skip(f"no .seq file in {SEQFILES}")
    differences = []
    skipped = []
    for path in paths:
        name = path.relative_to(SEQFILES).as_posix()
        if name in ORACLE_KNOWN_WRONG:
            continue
        try:
            data = seqfile.read_seqfile(path)
        except seqfile.NotSupported:
            continue  # a version outside 1.4.0-1.5.x (Q1): neither interpreter reads it
        except seqfile.SeqFileError as error:
            verdict, messages = run_oracle(path)
            if verdict == "accept" and name not in NOT_CHECKED_BY_THE_READER:
                differences.append(f"{path}: spec rejects {sorted(error.codes)}, oracle accepts")
            continue
        if arbitrary_gradient_off_the_10_us_raster(data):
            skipped.append(name)
            continue
        verdict, messages = run_oracle(path)
        if verdict != "accept":
            differences.append(f"{path}: spec accepts, oracle: {verdict}\n{messages}")
    record_property(
        "skipped",
        f"{len(skipped)} files skipped, {SKIPPED_ARBITRARY_GRADIENT_RASTER}: {', '.join(skipped)}",
    )
    assert not differences, "\n".join(differences)


def test_the_tables_of_differences_name_files_that_spec_rejects_or_reads():
    """A file of `NOT_CHECKED_BY_THE_READER` is one that `spec` rejects and a file of
    `ORACLE_KNOWN_WRONG` one that `spec` reads, so no entry is out of date. Each has an entry
    of `docs/discrepancies.md`."""
    for name, table, rejects in [
        *((n, NOT_CHECKED_BY_THE_READER, True) for n in NOT_CHECKED_BY_THE_READER),
        *((n, ORACLE_KNOWN_WRONG, False) for n in ORACLE_KNOWN_WRONG),
    ]:
        try:
            seqfile.read_seqfile(SEQFILES / name)
        except seqfile.SeqFileError:
            assert rejects, f"{name}: spec rejects it, but the table names it as read"
        else:
            assert not rejects, f"{name}: spec reads it, but the table names it as rejected"
        assert re.match(r"D\d+", table[name]), name
