"""The checks of undefined behaviour (`_checks.py`) on the paths where the reader reads a file
that looks like a case: they must not reject it. Where the sanitized C++ oracle is on the PATH,
each file is also run through it."""

import re
import shutil
import subprocess
import time

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import SEQFILES, TIMEOUT, UB_FIXTURES
from pulseq_cpp_siemens import _checks

SANITIZED = shutil.which("pulseq-cpp-oracle-sanitized")
VALID = (SEQFILES / "valid_no_signature.seq").read_text()


def f32(*values):
    return np.array(values, dtype=np.float32)


def with_rf_time_shape(num: str, values: list[str]) -> str:
    """valid_no_signature.seq with a new shape 20 as the time shape of its RF event. [SHAPES] is
    the file's last section, and the file ends with a blank line."""
    text = re.sub(r"(\[RF\]\n1 \S+ 1 2) 0 ", r"\1 20 ", VALID)
    assert " 20 " in text
    return text + f"shape_id 20\nnum_samples {num}\n" + "".join(v + "\n" for v in values) + "\n"


def sanitized_verdict(path) -> str:
    if SANITIZED is None:
        pytest.skip("pulseq-cpp-oracle-sanitized is not on the PATH")
    result = subprocess.run(
        [SANITIZED, str(path)], capture_output=True, timeout=TIMEOUT, check=False
    )
    return {0: "accept", 1: "reject", 3: "undefined"}.get(result.returncode, "crash")


def test_a_run_with_a_count_below_minus_one_writes_nothing():
    # rep = count + 2 <= 0: the loop of the run writes no sample, and countUnpack goes back.
    assert _checks._decompression(4, True, f32(1, 1, -2, 0.5)) == ("ok", "")
    assert _checks._decompression(4, True, f32(1, 1, -3)) == ("ok", "")
    # ... and a literal after it writes before the buffer.
    status, reason = _checks._decompression(4, True, f32(1, 1, -3, 2, 3))
    assert status == "ub" and "sample -1" in reason


def test_the_tolerance_of_a_count_is_computed_in_float():
    # 1 + 2**-23: in double the fraction is 1.2e-7, below 1e-6; in float 3.0000001 rounds to 3.
    assert _checks._decompression(8, True, f32(1, 1, 1.0000001, 5))[0] == "ok"
    # A fraction of 0.5 is a format error that the reader detects: a clean rejection.
    assert _checks._decompression(8, True, f32(1, 1, 0.5, 5)) == ("false", "")


def test_a_count_whose_sum_overflows_an_int_is_undefined_behaviour():
    # countUnpack + rep overflows an int before the bounds of the buffer are compared.
    packed = f32(0, 0, 2147483520, 1, 1, 2147483520)
    assert _checks._decompression(2**31 - 1, True, packed)[0] == "ub"
    assert _checks._decompression(4, True, f32(1, 1, np.nan))[0] == "ub"
    assert _checks._decompression(4, True, f32(1, 1, 3e9))[0] == "ub"


def test_the_resampling_jumps_over_the_cells_where_it_stays():
    """A time shape whose last time is near 2**31: about 2e9 cells, checked in a few steps."""
    t = f32(0, 1, 2, 2147483520)
    began = time.monotonic()
    assert _checks._resampling("RF", t, 2147483520, 4, 4) is None
    assert _checks._resampling("RF", f32(0, 1, 2, 3), 2147483520, 4, 4).code == (
        "ub.rf-time-overrun"
    )
    assert time.monotonic() - began < 1


def test_the_resampling_reads_past_the_times_at_the_cell_centres():
    # D5.8: MATLAB's short pulses, times at the cell centres; nSamples = int(0.5 + 3.5) = 4.
    case = _checks._resampling("RF", f32(0.5, 1.5, 2.5, 3.5), 4, 4, 4)
    assert case is not None and case.code == "ub.rf-time-overrun"
    assert _checks._resampling("RF", f32(1, 2, 3, 4), 4, 4, 4) is None


def test_a_nan_time_stops_the_resampling():
    assert _checks._resampling("RF", f32(np.nan, 1, 2), 3, 3, 3) is None


def test_a_regular_time_shape_is_not_decompressed(tmp_path):
    """A time shape of 3 stored values with another num_samples is regular (cpp:2012-2021): the
    reader reads its dwell and never decompresses it, also when num_samples is 0 or negative."""
    for num in ("100", "0", "-1"):
        path = tmp_path / f"regular_{num}.seq"
        path.write_text(with_rf_time_shape(num, ["1", "1", "98"]))
        cs.load(path).decode()
        if SANITIZED is not None:
            assert sanitized_verdict(path) == "accept"


def test_a_negative_number_of_cells_is_a_clean_rejection(tmp_path):
    """int(0.5 + t) < 0 makes std::vector throw: the reader rejects the block, with no undefined
    behaviour."""
    path = tmp_path / "negative_cells.seq"
    path.write_text(with_rf_time_shape("5", ["-9", "-8", "-7", "-6", "-5"]))  # int(-4.5) = -4
    sequence = cs.load(path)
    with pytest.raises(cs.Rejected) as error:
        sequence.decode()
    assert not isinstance(error.value, cs.UndefinedBehaviour)
    if SANITIZED is not None:
        assert sanitized_verdict(path) == "reject"


ONE_POINT = UB_FIXTURES / "gradient_one_point.seq"


def one_point_file(tmp_path, time: str, delay: str = "0", amplitude: str = "400000") -> object:
    """gradient_one_point.seq with the time of its one point, the delay and the amplitude of
    gradient 5 changed. Block 5 lasts 100 us."""
    text = ONE_POINT.read_text()
    text = text.replace(
        "\n5 400000 0 400000 21 20 0\n", f"\n5 {amplitude} 0 400000 21 20 {delay}\n"
    )
    text = text.replace("shape_id 20\nnum_samples 1\n4\n", f"shape_id 20\nnum_samples 1\n{time}\n")
    path = tmp_path / f"one_point_{time}_{delay}_{amplitude}.seq"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("time", "delay", "amplitude", "code"),
    [
        ("4", "0", "400000", "ub.gradient-one-point"),
        ("4", "90", "400000", "ub.gradient-one-point"),  # 90 to 100 us: inside the block
        ("0", "0", "400000", None),  # times[0] is 0: no time is before it
        ("-3", "0", "400000", None),
        ("4", "100", "400000", "ub.gradient-one-point"),  # gradientsAt takes t == duration
        ("4", "101", "400000", None),  # from its delay on, the block has ended
        ("4", "0", "0", None),  # gradientsAt returns 0 for an amplitude of 0
        ("4", "0", "nan", "ub.gradient-one-point"),
    ],
)
def test_an_extended_trapezoid_of_one_point(tmp_path, time, delay, amplitude, code):
    path = one_point_file(tmp_path, time, delay, amplitude)
    if code is None:
        sequence = cs.load(path)
        sequence.decode()
        times = np.arange(-1.0, 101.0, 0.5)
        sequence.gradients_at(np.full(times.size, 4), times)
        return
    with pytest.raises(cs.UndefinedBehaviour) as error:
        cs.load(path)
    assert error.value.code == code
    if SANITIZED is not None:
        result = subprocess.run(
            [SANITIZED, "--sample", str(path)], input=f"4 {error.value.time_us!r}\n",
            capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )  # fmt: skip
        assert result.returncode == 3, result.stderr


def test_a_trap_row_of_the_same_id_replaces_a_gradients_row_of_shape_0(tmp_path):
    """load reads [TRAP] after [GRADIENTS]: a [TRAP] row with the ID of a [GRADIENTS] row of shape
    0 replaces it, and its times are set."""
    text = VALID.replace("\n2 500000 0 0 3 0 100\n", "\n2 500000 0 0 0 0 100\n")
    text = text.replace(
        "\n1 1000000 100 200 100 100\n", "\n1 1000000 100 200 100 100\n2 250000 10 20 10 5\n"
    )
    path = tmp_path / "trap_replaces.seq"
    path.write_text(text)
    sequence = cs.load(path)
    grad = sequence.decode_block(1)["grad"][1]
    assert (grad["kind"], grad["ramp_up_us"], grad["flat_us"], grad["delay_us"]) == (
        "trap",
        10,
        20,
        5,
    )
    # With the same amplitude and delay the two rows cannot be told apart: rejected.
    path.write_text(text.replace("\n2 250000 10 20 10 5\n", "\n2 500000 10 20 10 100\n"))
    with pytest.raises(cs.UndefinedBehaviour) as error:
        cs.load(path)
    assert error.value.code == "ub.gradient-shape-0"


def test_a_gradients_row_of_shape_0_that_no_block_uses_reads(tmp_path):
    text = VALID.replace("\n2 500000 0 0 3 0 100\n", "\n2 500000 0 0 3 0 100\n9 1 0 0 0 0 0\n")
    path = tmp_path / "unused_shape_0.seq"
    path.write_text(text)
    cs.load(path).decode()


def test_an_extended_trapezoid_keeps_the_values_of_the_shape_before_it(tmp_path):
    """decodeExtTrapGradInBlock decodes every shape of a block into one buffer. A time shape that
    writes no sample (a run of count -2) keeps what the buffer held: nothing on the first channel
    (time 0, safe), the waveform 0.5 of the channel before it on the second (time 5 us, so
    gradientsAt reads past the times)."""
    text = VALID.replace("\n5 400000 0 400000 5 6 0\n", "\n5 400000 0 400000 21 20 0\n")
    text += "shape_id 20\nnum_samples 1\n0\n0\n-2\n\nshape_id 21\nnum_samples 1\n0.5\n\n"
    path = tmp_path / "one_channel.seq"
    path.write_text(text)
    sequence = cs.load(path)
    assert sequence.decode_block(4)["grad"][0]["times_us"].tolist() == [0]
    two = tmp_path / "two_channels.seq"
    two.write_text(text.replace("\n5  10  0  5  0  0  0  3\n", "\n5  10  0  5  5  0  0  3\n"))
    with pytest.raises(cs.UndefinedBehaviour) as error:
        cs.load(two)
    assert (error.value.code, error.value.block) == ("ub.gradient-one-point", 4)
    if SANITIZED is not None:
        result = subprocess.run(
            [SANITIZED, "--sample", str(two)], input=f"4 {error.value.time_us!r}\n",
            capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )  # fmt: skip
        assert result.returncode == 3, result.stderr
