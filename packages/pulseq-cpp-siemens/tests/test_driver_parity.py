"""The package against the driver of the C++ oracle (`pulseq-cpp-oracle`, built by flake.nix
from the same commit and with the same flags), for each fixture: the same verdict, the same
`--dump` and the same `--sample`, exactly, in each sampling mode of oversampled gradients
(`--oversampling`). Where the package finds undefined behaviour, the sanitized driver
(`pulseq-cpp-oracle-sanitized`) must find it too, in each mode. The module skips without the
driver (outside the Nix devShell)."""

import re
import shutil
import subprocess

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import (
    SEQFILES,
    TIMEOUT,
    canonical_dump,
    driver,
    driver_samples,
    fixture_id,
    fixtures,
    has_oversampled_gradient,
    oversampling_option,
    parse_driver_dump,
    run_driver,
    sample_points,
    wrapper_dump,
)

pytestmark = pytest.mark.skipif(driver() is None, reason="pulseq-cpp-oracle is not on the PATH")

# The exit status of the sanitized driver when a sanitizer or an assertion of the standard
# library fires (tests/cpp_oracle/README.md).
UNDEFINED_BEHAVIOUR = 3


def first_difference(a, b, path="") -> str | None:
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return f"{path}: keys {sorted(a)} != {sorted(b)}"
        for key in a:
            found = first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("oversampling", cs.OVERSAMPLING)
@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_package_gives_what_the_driver_gives(path, oversampling):
    try:
        sequence = cs.load(path, oversampling=oversampling)
        blocks = sequence.decode()
    except cs.NotSupported:
        # The package's scope (Q1), not the reader's: the driver may read the file.
        pytest.skip("outside the package's scope (Q1)")
    except cs.UndefinedBehaviour as error:
        sanitized = shutil.which("pulseq-cpp-oracle-sanitized")
        if sanitized is None:
            pytest.skip("pulseq-cpp-oracle-sanitized is not on the PATH")
        if error.code == "ub.gradient-shape-0":
            # Indeterminate values: no sanitizer of the oracle sees them (MemorySanitizer would).
            pytest.skip("the sanitizers do not see indeterminate values")
        if error.code == "ub.extension-cycle" and oversampling != "center":
            pytest.skip("GetBlock never ends in any mode; the driver needs its whole timeout")
        # A case that only gradientsAt meets: the oracle's --sample at the case's time.
        sample = None if error.block is None else f"{error.block} {error.time_us!r}\n"
        command = [
            sanitized, *oversampling_option(oversampling), *(["--sample"] if sample else []),
            str(path),
        ]  # fmt: skip
        try:
            result = subprocess.run(
                command, input=sample, capture_output=True, text=True, timeout=TIMEOUT,
                check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return  # no end: D23
        assert result.returncode == UNDEFINED_BEHAVIOUR, (
            f"the sanitized driver exits with {result.returncode}, the package: {error}"
        )
        return
    except cs.Rejected as error:
        verdict, out = run_driver("", path, oversampling=oversampling)
        assert verdict == "reject", f"the driver says {verdict}, the package: {error}"
        return
    if oversampling != "center" and not has_oversampled_gradient(sequence):
        pytest.skip("no oversampled gradient: the mode changes nothing (the center run covers it)")
    verdict, out = run_driver("--dump", path, oversampling=oversampling)
    assert verdict == "ok", f"the driver says {verdict} ({out}), the package reads the file"

    theirs = canonical_dump(parse_driver_dump(out))
    ours = canonical_dump(wrapper_dump(sequence, blocks))
    assert first_difference(theirs, ours) is None, first_difference(theirs, ours)

    block_index, time_us = sample_points(theirs)
    if block_index.size:
        expected = driver_samples(path, block_index, time_us, oversampling)
        actual = sequence.gradients_at(block_index, time_us)
        same = (expected == actual) | (np.isnan(expected) & np.isnan(actual))
        mismatch = np.flatnonzero(~same.all(axis=1))
        assert mismatch.size == 0, (
            f"{mismatch.size} of {block_index.size} samples differ; first: block "
            f"{block_index[mismatch[0]]} at {time_us[mismatch[0]]} us: driver "
            f"{expected[mismatch[0]]}, package {actual[mismatch[0]]}"
        )


@pytest.mark.parametrize("oversampling", cs.OVERSAMPLING)
@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_first_rejected_block_agrees_with_the_driver_s_first_mode(path, oversampling):
    try:
        sequence = cs.load(path, oversampling=oversampling)
    except (cs.NotSupported, cs.Rejected):
        pytest.skip("the package does not decode the file (test_driver_parity above)")
    first = sequence.first_rejected_block()
    verdict, out = run_driver("", path, oversampling=oversampling)
    assert verdict == ("ok" if first is None else "reject"), (verdict, first)
    if first is None:
        assert sequence.rejection_messages == ""
    else:
        # The driver says it for each block that fails; the first one is the package's.
        assert re.search(r"decodeBlock returned false for block (\d+)", out).group(1) == str(first)
        assert f"decodeBlock returned false for block {first}\n" in sequence.rejection_messages
    # Block by block, the same: the first that decode_block rejects.
    rejected = []
    for index in range(sequence.block_count):
        try:
            sequence.decode_block(index)
        except cs.Rejected:
            rejected.append(index)
    assert (rejected[0] if rejected else None) == first


def test_the_driver_option_sets_the_sampling_mode():
    path = SEQFILES / "oracle" / "koma_v1.5_spiral.seq"  # an oversampled gradient of 4 223 samples

    def call(*arguments):
        return subprocess.run(
            [driver(), *arguments], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )

    default = call("--dump", str(path))
    assert default.returncode == 0
    assert call("--oversampling=center", "--dump", str(path)).stdout == default.stdout
    sizes = {}
    for mode in ("center", "edge", "preserve"):
        dump = parse_driver_dump(call(f"--oversampling={mode}", "--dump", str(path)).stdout)
        sizes[mode] = {
            len(grad["samples"])
            for block in dump["blocks"]
            for grad in block["grad"]
            if grad is not None and grad["kind"] == "arbitrary" and grad["oversampled"]
        }
    assert sizes == {"center": {2112}, "edge": {2111}, "preserve": {4223}}
    # A value that is not a mode is a wrong call. With one argument the option is a file name.
    assert call("--oversampling=left", "--dump", str(path)).returncode == 2
    assert call("--oversampling=edge").returncode == 1
