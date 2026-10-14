"""Each case of undefined behaviour of section 5.3 of the plan is rejected by `load`, before
`GetBlock` and `decodeBlock` run, with its code, and the process goes on: after all of them, a
valid file still reads as before. The sanitized C++ oracle confirms each fixture
(test_driver_parity.py, and tests/test_cpp_oracle_sanitized.py of pulseq-analysis).

A case that the stored duration of a block hides (an extended trapezoid of one point whose delay
is past the end of the block) is refused by `gradients_at` at the times where a soft delay
(`actual_ru`) makes the reader meet it. Those calls run in a process of their own: a case that
the package misses ends the process."""

import json
import shutil
import subprocess
import sys

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import REPO, SEQFILES, TIMEOUT, UB_FIXTURES, canonical_dump, wrapper_dump

CASES = {
    # D5.1: [VERSION] last (D2.1 in `spec`); the reader then reads no shape, so the RF event's
    # shape is missing.
    SEQFILES / "undefined" / "version_last.seq": "ub.shape-missing",
    SEQFILES / "bad_ref_shape.seq": "ub.shape-missing",  # D5.1
    SEQFILES / "bad_ref_time_shape.seq": "ub.shape-missing",  # D5.1
    SEQFILES / "bad_syntax_shape_no_blank_line.seq": "ub.shape-missing",  # D3.11, then D5.1
    SEQFILES / "undefined" / "rf_time_id_minus_1.seq": "ub.rf-time-id-minus-1",  # D5.3
    SEQFILES / "bad_ref_extension_cycle.seq": "ub.extension-cycle",  # D5.4
    SEQFILES / "undefined" / "shape_decompress_longer.seq": "ub.shape-decompression",  # D5.5
    UB_FIXTURES / "shape_decompress_count_missing.seq": "ub.shape-decompression",  # D5.5
    SEQFILES / "bad_shape_empty.seq": "ub.shape-empty",  # D5.6
    SEQFILES / "bad_shape_event_length.seq": "ub.rf-shape-lengths",  # D5.7
    SEQFILES / "bad_shape_rf_time_end.seq": "ub.rf-time-overrun",  # D5.8
    # D5.10: gradientsAt of an extended trapezoid of one point reads past its times.
    UB_FIXTURES / "gradient_one_point.seq": "ub.gradient-one-point",
    # D5.2: a [GRADIENTS] row of shape 0: a trapezoid whose ramp and flat times load never sets.
    UB_FIXTURES / "gradient_shape_0.seq": "ub.gradient-shape-0",
}


def ids(path):
    return path.relative_to(REPO).as_posix()


@pytest.mark.parametrize(("path", "code"), CASES.items(), ids=[ids(p) for p in CASES])
def test_a_case_of_undefined_behaviour_is_rejected_with_its_code(path, code):
    with pytest.raises(cs.UndefinedBehaviour) as error:
        cs.load(path)
    assert error.value.code == code
    assert error.value.entry == cs.CODES[code]


def test_the_process_reads_a_valid_file_after_every_case():
    path = SEQFILES / "valid_1_5_1.seq"
    before = canonical_dump(wrapper_dump(cs.load(path)))
    for case in CASES:
        with pytest.raises(cs.UndefinedBehaviour):
            cs.load(case)
    assert canonical_dump(wrapper_dump(cs.load(path))) == before


def test_the_extension_refuses_to_decode_a_file_that_is_not_checked():
    reader = cs._reader.Reader()
    assert reader.load((SEQFILES / "valid_1_5_1.seq").read_bytes())
    with pytest.raises(RuntimeError, match="not checked"):
        reader.decode_block(0)
    with pytest.raises(RuntimeError, match="not checked"):
        reader.ensure_decoded(np.zeros(1, dtype=np.int64))


# gradient_one_point.seq with the delay of gradient 5 at 200 us: block 4 (ID 5) lasts 100 us, and
# its extended trapezoid of one point (40 us after its delay) has the read from 200 to 240 us.
AFTER_BLOCK = UB_FIXTURES / "gradient_one_point_after_block.seq"

# The call of `gradients_at` in a process of its own: the file, the block indices, the times and
# `actual_ru` as JSON in argv; the values, or the fields of `UndefinedBehaviour`, as JSON on stdout.
GRADIENTS_AT = """
import json, sys
import pulseq_cpp_siemens as cs
path, blocks, times, actual_ru = sys.argv[1], *map(json.loads, sys.argv[2:])
try:
    values = cs.load(path).gradients_at(blocks, times, actual_ru=actual_ru)
except cs.UndefinedBehaviour as error:
    print(json.dumps({"code": error.code, "block": error.block, "time_us": error.time_us}))
else:
    print(json.dumps({"values": values.tolist()}))
"""


def actual_ru_of_block_4(value: int) -> list[int]:
    actual = [-1] * cs.load(AFTER_BLOCK).block_count
    actual[4] = value
    return actual


def gradients_at_in_a_process(times: list[float], actual_ru: list[int]) -> dict:
    """`gradients_at` of block 4 of AFTER_BLOCK at `times`, in a process of its own, which must
    end with 0."""
    result = subprocess.run(
        [sys.executable, "-c", GRADIENTS_AT, str(AFTER_BLOCK), json.dumps([4] * len(times)),
         json.dumps(times), json.dumps(actual_ru)],
        capture_output=True, text=True, timeout=TIMEOUT, check=False,
    )  # fmt: skip
    assert result.returncode == 0, (
        f"the process ends with {result.returncode} (below 0: the number of a signal); "
        f"stdout {result.stdout!r}, stderr {result.stderr[-2000:]!r}"
    )
    return json.loads(result.stdout)


def test_a_soft_delay_that_reaches_a_hidden_one_point_read_raises():
    """a[4] = 100: block 4 lasts 1000 us, so gradientsAt at 205 us would read past the times."""
    assert gradients_at_in_a_process([205.0], actual_ru_of_block_4(100)) == {
        "code": "ub.gradient-one-point",
        "block": 4,
        "time_us": 205.0,
    }


def test_a_time_outside_the_hidden_read_gives_the_value_of_the_reader():
    """Before the delay, at its end (delay + 40 us: times[0], the one point) and after it, block 4
    with a soft delay of 1000 us gives the reader's values, and the sanitized oracle's agree."""
    actual_ru = actual_ru_of_block_4(100)
    times = [100.0, 199.0, 240.0, 250.0, 900.0]
    expected = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [200000.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0]]  # fmt: skip
    assert gradients_at_in_a_process(times, actual_ru) == {"values": expected}
    sanitized = shutil.which("pulseq-cpp-oracle-sanitized")
    if sanitized is not None:
        result = subprocess.run(
            [sanitized, "--sample", str(AFTER_BLOCK)],
            input="".join(f"4 {t!r} {actual_ru[4]}\n" for t in times),
            capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )  # fmt: skip
        assert result.returncode == 0, result.stderr
        assert np.array(result.stdout.split(), dtype=np.float64).reshape(-1, 3).tolist() == expected


@pytest.mark.parametrize("value", [10, 15], ids=["stored-100-us", "longer-150-us"])
def test_a_soft_delay_that_ends_before_the_hidden_read_gives_0(value):
    """10 (the stored 100 us) and 15 (150 us, longer than stored, before the delay of 200 us): at
    205 us the block has ended."""
    assert gradients_at_in_a_process([205.0], actual_ru_of_block_4(value)) == {
        "values": [[0.0, 0.0, 0.0]]
    }
