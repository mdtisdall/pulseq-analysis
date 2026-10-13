"""Tests of the sanitized C++ oracle `pulseq-cpp-oracle-sanitized`: the driver of
`tests/cpp_oracle/` and the reader `ExternalSequence` of pulseq/pulseq, built by `flake.nix` with
AddressSanitizer, UndefinedBehaviorSanitizer and the assertions of the C++ standard library. It
exits with 3 when one of them fires: the reader has undefined behaviour on the file. An ordinary
build of the reader can then crash, accept or reject, by platform (section 5.3 of
`docs/plans/parser-redesign.md`); this verdict is the same on each platform.

The module skips when the binary is not on the PATH, as outside the Nix devShell.
"""

import functools
import shutil
import subprocess

import pytest
from test_cpp_oracle import MINIMAL_SEQ, ORACLE, SEQFILES, TIMEOUT

SANITIZED = shutil.which("pulseq-cpp-oracle-sanitized")

pytestmark = pytest.mark.skipif(
    SANITIZED is None, reason="pulseq-cpp-oracle-sanitized is not on the PATH"
)

# The exit status of the sanitized driver when a sanitizer or an assertion of the standard
# library fires.
UNDEFINED_BEHAVIOUR = 3

# Each fixture of `tests/seqfiles` on which the reader has undefined behaviour: the entry of
# section 5.3 of `docs/plans/parser-redesign.md`, and the line of ExternalSequence.cpp where the
# sanitized build stops (found with a build that has the line numbers).
UNDEFINED = {
    "undefined/version_last.seq": ("D05", "1995: the reader reads no shape after [VERSION]"),
    "bad_ref_shape.seq": ("D21", "1995: the RF magnitude shape 99 does not exist"),
    "bad_ref_time_shape.seq": ("D21", "2177: the gradient time shape 99 does not exist"),
    "bad_syntax_shape_no_blank_line.seq": (
        "D21",
        "2177: the shapes after the one with no blank line are not read (D07), and a gradient "
        + "names one",
    ),
    "undefined/rf_time_id_minus_1.seq": ("D22", "2026: an RF event with time ID -1"),
    "undefined/shape_decompress_longer.seq": (
        "D29",
        "2231: heap-buffer-overflow; the RF shapes decompress to 100 samples, num_samples 99",
    ),
    "bad_shape_empty.seq": ("D33", "1995: element 0 of an empty shape"),
    "bad_shape_event_length.seq": ("D34", "2288: a phase shape shorter than the magnitude"),
    "bad_shape_rf_time_end.seq": ("D36 (2)", "2044: the resampling reads one sample too far"),
    "valid_rf_time_shapes.seq": (
        "D36 (2)",
        "decodeBlock indexes past the stored samples: the RF 3 time shape 0.5 1.5 2.5 (the "
        + "stack trace has no line number)",
    ),
}

# The fixtures on which the reader does not end. The sanitizers do not see this: the loop over a
# cycle in an extension list (ExternalSequence.cpp:1850-1928) appends a label to a vector in
# each turn, so it is not undefined behaviour, and the memory grows with no end (about 3 GB in
# 10 s in this build).
NO_END = {
    "bad_ref_extension_cycle.seq": "D23",
}

# Each fixture that the reader rejects (exit status 1) without undefined behaviour.
REJECTED = {
    "bad_definitions_raster_invalid.seq",
    "bad_definitions_raster_missing.seq",
    "bad_extension_required_unknown.seq",
    "bad_many.seq",
    "bad_ref_block_rf.seq",
    "bad_syntax_integer.seq",
    "bad_syntax_line_after_comment.seq",
    "bad_syntax_shape.seq",
    "bad_syntax_shape_end.seq",
    "bad_version_missing.seq",
    "bad_version_unsupported_1_3.seq",
    "oracle/koma_v1.5_unknown_ext.seq",
    "valid_arbitrary_gradient_4us_raster.seq",
    "valid_arbitrary_gradient_5us_raster.seq",
    "valid_comment_in_shape.seq",
    "valid_last_section_no_blank.seq",
}

FIXTURES = sorted(path.relative_to(SEQFILES).as_posix() for path in SEQFILES.rglob("*.seq"))


def expected_verdict(name):
    """The verdict of the sanitized oracle that the tables give for a fixture."""
    if name in UNDEFINED:
        return "undefined"
    if name in NO_END:
        return "no end"
    return "reject" if name in REJECTED else "accept"


def run(binary, path):
    """The verdict of an oracle binary on a file and its messages: "accept" (exit 0), "reject"
    (exit 1), "undefined" (exit 3, from the sanitized build only), "no end" (no end in `TIMEOUT`
    s) or "crash" (a signal or another exit status)."""
    try:
        result = subprocess.run(
            [binary, str(path)], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return "no end", f"no end after {TIMEOUT} s"
    verdict = {0: "accept", 1: "reject", UNDEFINED_BEHAVIOUR: "undefined"}.get(
        result.returncode, "crash"
    )
    return verdict, f"exit status {result.returncode}\n{result.stdout}{result.stderr}"


@functools.cache
def sanitized_verdict(name):
    """The verdict and the messages of the sanitized oracle on a fixture, run once."""
    return run(SANITIZED, SEQFILES / name)


def test_the_tables_name_only_fixtures_that_exist():
    named = set(UNDEFINED) | set(NO_END) | REJECTED
    assert named <= set(FIXTURES)
    assert not set(UNDEFINED) & set(NO_END) and not (set(UNDEFINED) | set(NO_END)) & REJECTED


def test_the_sanitized_oracle_accepts_a_minimal_valid_file(tmp_path):
    path = tmp_path / "minimal.seq"
    path.write_text(MINIMAL_SEQ)
    verdict, messages = run(SANITIZED, path)
    assert verdict == "accept", messages


@pytest.mark.parametrize("name", FIXTURES)
def test_the_sanitized_verdict_of_each_fixture(name):
    verdict, messages = sanitized_verdict(name)
    assert verdict == expected_verdict(name), messages
    if verdict == "undefined":
        assert "Sanitizer" in messages or "undefined behaviour" in messages, messages


def test_each_case_of_undefined_behaviour_of_the_plan_has_a_fixture():
    """Section 5.3 of the plan: each entry has a fixture with the verdict "undefined", except
    D23, which has a fixture with no end."""
    entries = {entry for entry, _ in UNDEFINED.values()}
    assert entries == {"D05", "D21", "D22", "D29", "D33", "D34", "D36 (2)"}
    assert set(NO_END.values()) == {"D23"}


@pytest.mark.skipif(ORACLE is None, reason="pulseq-cpp-oracle is not on the PATH")
def test_the_ordinary_oracle_gives_the_same_verdict_where_the_reader_has_no_undefined_behaviour():
    """The sanitized build does not change what the reader does with a file that it accepts or
    rejects."""
    differences = []
    for name in FIXTURES:
        verdict, _ = sanitized_verdict(name)
        if verdict not in {"accept", "reject"}:
            continue
        ordinary, messages = run(ORACLE, SEQFILES / name)
        if ordinary != verdict:
            differences.append(f"{name}: sanitized {verdict}, ordinary {ordinary}\n{messages}")
    assert not differences, "\n".join(differences)


def test_the_sanitized_oracle_reports_a_missing_shape_built_in_the_test(tmp_path):
    """The minimal file with an RF event whose phase shape 2 is not in `[SHAPES]` (D21)."""
    text = MINIMAL_SEQ.replace("1 100 0 0 0 0 0 0", "1 11 1 0 0 0 0 0") + (
        "\n[RF]\n1 1000 1 2 0 0 10 0 0 0 0 u\n\n[SHAPES]\nshape_id 1\nnum_samples 6\n"
        + "0.5\n" * 6
        + "\n"
    )
    path = tmp_path / "missing_phase_shape.seq"
    path.write_text(text)
    verdict, messages = run(SANITIZED, path)
    assert verdict == "undefined", messages
