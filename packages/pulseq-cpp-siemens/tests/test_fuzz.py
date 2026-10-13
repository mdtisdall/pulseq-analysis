"""The fuzzing of the checks of undefined behaviour against the sanitized C++ oracle (seqfuzz.py;
README.md, "Fuzzing", has the four tiers). Here:

- the regression corpus (tests/fuzz_corpus): a file of each code, each file that once failed the
  fuzzing, and a few valid files, with the package's verdict on each in expected.json (the same in
  each sampling mode of oversampled gradients; each file runs in all three);
- the seeded files 0..COUNT-1 of SEED, each with a sampling mode that its seed and index give: a smoke set of 200 in scripts/check, and the full set of
  3 000 (PULSEQ_CPP_SIEMENS_FUZZ_COUNT=3000) in .github/workflows/pulseq-cpp-siemens-fuzz.yml,
  where the package or the oracle changes.

The tests that need `pulseq-cpp-oracle-sanitized` skip without it (outside the Nix devShell)."""

import json
import os
import shutil
from collections import Counter
from pathlib import Path

import pulseq_cpp_siemens as cs
import pytest
import seqfuzz

ORACLE = shutil.which("pulseq-cpp-oracle-sanitized")
CORPUS = Path(__file__).resolve().parent / "fuzz_corpus"
EXPECTED = json.loads((CORPUS / "expected.json").read_text())

SEED = 20261012
COUNT = int(os.environ.get("PULSEQ_CPP_SIEMENS_FUZZ_COUNT", "200"))
# The full set: each code must be confirmed at least MIN_CONFIRMED times in it, so that it reaches
# every case and its neighbours.
FULL = 3000
MIN_CONFIRMED = 10
# Files in the full set with an oversampled gradient of each size (1, 2, 3, 4 or more) in each mode.
MIN_OVERSAMPLED = 30

needs_oracle = pytest.mark.skipif(
    ORACLE is None, reason="pulseq-cpp-oracle-sanitized is not on the PATH"
)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    keep = tmp_path_factory.mktemp("fuzz-failures")
    return seqfuzz.run(SEED, 0, COUNT, ORACLE, keep=keep), keep


def failures(result, keep) -> str:
    lines = "\n".join(
        f"{f.name} {f.mutations} [{f.known or 'not known'}]: {f.failure}"
        for f in result.failures[:40]
    )
    return f"{result.summary()}\nThe failing files are in {keep}.\n{lines}"


def test_a_file_is_the_same_for_the_same_seed_and_index():
    assert seqfuzz.generate(SEED, 7) == seqfuzz.generate(SEED, 7)
    assert seqfuzz.generate(SEED, 7) != seqfuzz.generate(SEED, 8)
    assert seqfuzz.generate(SEED, 7) != seqfuzz.generate(SEED + 1, 7)


def test_a_file_has_a_sampling_mode_from_its_seed_and_index():
    assert seqfuzz.OVERSAMPLING == cs.OVERSAMPLING
    modes = [seqfuzz.oversampling_mode(SEED, index) for index in range(300)]
    assert modes == [seqfuzz.oversampling_mode(SEED, index) for index in range(300)]
    assert set(modes) == set(cs.OVERSAMPLING)
    assert min(modes.count(mode) for mode in cs.OVERSAMPLING) > 60
    assert modes != [seqfuzz.oversampling_mode(SEED + 1, index) for index in range(300)]


def test_a_file_with_no_mutation_reads():
    """The generator's files are valid before their mutations: the package reads them."""
    read = 0
    for index in range(400):
        data, mutations = seqfuzz.generate(SEED, index)
        if mutations:
            continue
        cs.load(data).decode()
        read += 1
    assert read > 10


def test_the_corpus_has_a_file_of_each_code():
    files = sorted(path.name for path in CORPUS.glob("*.seq"))
    assert sorted(EXPECTED) == files
    codes = {verdict.split(":", 1)[1] for verdict in EXPECTED.values() if ":" in verdict}
    assert codes == set(cs.CODES)


@needs_oracle
def test_the_corpus_agrees_with_the_sanitized_oracle(tmp_path):
    result = seqfuzz.run_files(sorted(CORPUS.glob("*.seq")), ORACLE, keep=tmp_path)
    assert not result.failures, failures(result, tmp_path)
    verdicts = {
        (r.name, r.oversampling): r.package + (f":{r.code}" if r.code else "")
        for r in result.results
    }
    assert verdicts == {
        (name, mode): EXPECTED[name] for name in EXPECTED for mode in cs.OVERSAMPLING
    }


@pytest.mark.fuzz
@pytest.mark.skipif(
    COUNT < FULL, reason=f"the full set only (PULSEQ_CPP_SIEMENS_FUZZ_COUNT={FULL})"
)
def test_the_seeded_files_have_oversampled_gradients_of_each_size_in_each_mode():
    """The files that the package reads (no oracle needed) have, in each
    sampling mode, oversampled gradients that a block uses, of 1, 2, 3 and 4 or more samples: the
    reader keeps (n + 1) / 2, (n - 1) / 2 or n of them by its mode, and none in the "edge" mode
    for 1 and 2 (gradientsAt returns early for such a gradient at its delay)."""
    seen = Counter()
    for index in range(COUNT):
        mode = seqfuzz.oversampling_mode(SEED, index)
        try:
            libraries = cs.load(seqfuzz.generate(SEED, index)[0], oversampling=mode).libraries
        except (cs.Rejected, cs.NotSupported):
            continue
        used = {g for row in libraries.blocks.tolist() for g in row[2:5] if g in libraries.grad}
        sizes = {
            min(libraries.shapes[libraries.grad[g]["wave_shape"]].num_samples, 4)
            for g in used
            if libraries.grad[g]["wave_shape"] in libraries.shapes
            and libraries.grad[g]["wave_shape"] != 0
            and libraries.grad[g]["time_shape"] == -1
        }
        seen.update((mode, size) for size in sizes)
    short = {
        (mode, size): seen[mode, size]
        for mode in cs.OVERSAMPLING
        for size in (1, 2, 3, 4)
        if seen[mode, size] < MIN_OVERSAMPLED
    }
    assert not short, f"files read with an oversampled gradient of this many samples: {seen}"


@pytest.mark.fuzz
@needs_oracle
def test_the_checks_agree_with_the_sanitized_oracle_on_the_seeded_files(report):
    result, keep = report
    assert not result.failures, (
        f"{failures(result, keep)}\nReproduce one with scripts/fuzz.py --seed {SEED} --start "
        "INDEX --count 1."
    )


@pytest.mark.fuzz
@needs_oracle
@pytest.mark.skipif(
    COUNT < FULL, reason=f"the full set only (PULSEQ_CPP_SIEMENS_FUZZ_COUNT={FULL})"
)
def test_the_seeded_files_reach_each_case_of_undefined_behaviour(report):
    confirmed = report[0].confirmed_codes()
    short = {code: confirmed[code] for code in cs.CODES if confirmed[code] < MIN_CONFIRMED}
    assert not short, f"cases that the seeded files reach too rarely: {short}; all: {confirmed}"
