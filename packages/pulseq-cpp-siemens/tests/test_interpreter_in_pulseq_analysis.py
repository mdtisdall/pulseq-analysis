"""Tests of the `cpp-siemens` interpreter in the functions of pulseq-analysis that take any
interpreter: the checks of pulseq-analysis's own tests (`test_from_pypulseq`,
`test_matlab_oracle`) run for `cpp-siemens`, and what pulseq-analysis gives for the model of a
plugin interpreter (its records, and the refusal of the events of `spec`).

The module is not collected without pulseq-analysis (`conftest.py`); the MATLAB test skips as the tests of
pulseq-analysis do, when the MATLAB oracle is not on the PATH.
"""

import copy
from pathlib import Path

import numpy as np
import pypulseq as pp
import pytest
import test_matlab_oracle
from pulseq_cpp_siemens.interpreter import CppSiemens
from synthetic import RASTER_4US, SYSTEM
from test_from_pypulseq import (
    SEQUENCES,
    check_a_rejection,
    check_reads_as_its_written_file,
    check_the_mixed_sequence,
)
from test_matlab_oracle import cases  # noqa: F401 (the fixture of the MATLAB oracle)

from pulseq_analysis import seqfile, synth
from pulseq_analysis.seqfile import SeqFileError, read_seqfile
from pulseq_analysis.synth.events import decode_adc, decode_gradients, decode_rf

SEQFILES = Path(__file__).resolve().parents[3] / "tests" / "seqfiles"

# `cpp-siemens` by name, and as an object with a setting.
INTERPRETERS = [
    pytest.param("cpp-siemens", id="cpp-siemens"),
    pytest.param(CppSiemens(oversampling="edge"), id="CppSiemens-edge"),
]


@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize("name", SEQUENCES)
def test_a_sequence_in_memory_reads_as_its_written_file_through_cpp_siemens(
    name, interpreter, tmp_path
):
    check_reads_as_its_written_file(SEQUENCES[name](), interpreter, tmp_path)


@pytest.mark.parametrize("interpreter", INTERPRETERS)
def test_the_mixed_sequence_has_each_kind_of_event_through_cpp_siemens(interpreter):
    check_the_mixed_sequence(interpreter)


def arbitrary_gradient_4us_sequence() -> pp.Sequence:
    """An arbitrary gradient on a gradient raster of 4 us (`cpp-siemens` rejects it:
    `gradient.raster`)."""
    system = copy.copy(SYSTEM)
    system.grad_raster_time = RASTER_4US
    seq = pp.Sequence(system)
    waveform = 0.1 * SYSTEM.max_grad * np.sin(np.pi * (np.arange(40) + 0.5) / 40)
    seq.add_block(pp.make_arbitrary_grad(channel="x", waveform=waveform, system=system))
    return seq


def test_a_rejection_of_cpp_siemens_names_the_sequence_not_the_temporary_file(tmp_path):
    check_a_rejection(arbitrary_gradient_4us_sequence(), "cpp-siemens", "gradient.raster", tmp_path)


def test_the_events_of_spec_refuse_a_model_of_cpp_siemens():
    """`decode_rf`, `decode_gradients` and `decode_adc` of pulseq-analysis decode the model of
    `spec` only: they raise `TypeError` for the model of `cpp-siemens`, and name
    `synth.decode`."""
    data = seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq", interpreter="cpp-siemens")
    for decode in (decode_rf, decode_gradients, decode_adc):
        with pytest.raises(TypeError, match="synth.decode"):
            decode(data)


def test_gradients_at_refuses_a_block_index_that_is_not_an_integer_through_cpp_siemens():
    """`CppSiemensDecoding.gradients_at` raises `TypeError`, with a message that names
    `block_index`, for a block index whose dtype is not an integer (1.3.3 of
    `docs/reviews/2026-10-21-code-review.md`: `[1.9]` gave the gradients of block 1): a float, also
    one with an integer value, and a bool. A list of ints and arrays of int32 and uint8 read block 1
    of valid_1_5_1.seq (the trapezoid of 1e6 Hz/m on gx at 250 us), and an empty list, which numpy
    makes float64, gives an array (0, 3)."""
    decoding = synth.decode(
        seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq", interpreter="cpp-siemens")
    )
    for index in ([1.9], [1.0], np.array([1.0]), [True], np.array([True])):
        with pytest.raises(TypeError, match="block_index"):
            decoding.gradients_at(index, [250e-6])
    expected = decoding.gradients_at([1], [250e-6])
    assert expected[0, 0] == 1e6
    for index in (np.array([1], np.int32), np.array([1], np.uint8)):
        assert np.array_equal(decoding.gradients_at(index, [250e-6]), expected)
    assert decoding.gradients_at([], []).shape == (0, 3)


@test_matlab_oracle.pytestmark
@pytest.mark.parametrize(
    "path", test_matlab_oracle.ROTATION_FILES, ids=lambda p: str(p.relative_to(SEQFILES))
)
def test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq(cases, path):  # noqa: F811
    """`CppSiemens(rotation="apply")` rotates each block's gradients by the reader's quaternion
    with the reader's `rotate_vec3_by_quat`, and MATLAB's `waveforms_and_times` rotates them
    with `mr.rotate3D` (Sequence.m:1988-1999), in any version: they agree as
    `test_matlab_oracle.compare_rotated_gradients` says, to the relative tolerance of the
    reader's float32 amplitudes (`FLOAT32_REL`). The test skips without the MATLAB oracle, as
    `test_matlab_oracle` does."""
    case = test_matlab_oracle.case_of(cases, path)
    try:
        data = read_seqfile(path, CppSiemens(rotation="apply"))
    except SeqFileError as error:
        pytest.skip(f"cpp-siemens rejects the file ({', '.join(sorted(error.codes))})")
    test_matlab_oracle.compare_rotated_gradients(case, data, test_matlab_oracle.FLOAT32_REL)


def test_a_rejection_whose_messages_are_not_utf_8_has_the_code_of_the_ascii_row(tmp_path):
    """`load` quotes the ADC row that it fails to decode (cpp:1150). With a byte there that is not
    UTF-8, `read_seqfile` with `cpp-siemens` gives the codes of the same row with an ASCII byte in
    its place: the messages, decoded with `backslashreplace`, map to the same codes."""
    text = (SEQFILES / "valid_1_5_1.seq").read_bytes()
    row = b"\n1 8 25000 100 0 0 0 0 0\n"
    assert text.count(row) == 1
    codes = {}
    for name, byte in (("ascii", b"x"), ("not_utf_8", b"\xb5x")):
        path = tmp_path / f"{name}.seq"
        path.write_bytes(text.replace(row, b"\n1 " + byte + b" 25000 100 0 0 0 0 0\n"))
        with pytest.raises(SeqFileError) as caught:
            read_seqfile(path, "cpp-siemens")
        codes[name] = caught.value.codes
    assert codes["not_utf_8"] == codes["ascii"]
