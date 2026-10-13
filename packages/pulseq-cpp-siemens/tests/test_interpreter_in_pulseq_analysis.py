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
    check_the_sequence_is_not_changed,
)
from test_matlab_oracle import cases  # noqa: F401 (the fixture of the MATLAB oracle)

from pulseq_analysis import seqfile
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


@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize("name", SEQUENCES)
def test_the_sequence_is_not_changed_by_cpp_siemens(name, interpreter):
    check_the_sequence_is_not_changed(SEQUENCES[name](), interpreter)


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


@test_matlab_oracle.pytestmark
@pytest.mark.parametrize(
    "path", test_matlab_oracle.ROTATION_FILES, ids=lambda p: str(p.relative_to(SEQFILES))
)
def test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq(cases, path):  # noqa: F811
    """`CppSiemens(rotation="apply")` rotates each block's gradients by the reader's quaternion
    with the reader's `rotate_vec3_by_quat`, and MATLAB's `waveforms_and_times` rotates them
    with `mr.rotate3D` (Sequence.m:1988-1999), in any version: they agree as
    `test_matlab_oracle.compare_rotated_gradients` says. The test skips without the MATLAB
    oracle, as `test_matlab_oracle` does."""
    case = test_matlab_oracle.case_of(cases, path)
    try:
        data = read_seqfile(path, CppSiemens(rotation="apply"))
    except SeqFileError as error:
        pytest.skip(f"cpp-siemens rejects the file ({', '.join(sorted(error.codes))})")
    test_matlab_oracle.compare_rotated_gradients(case, data)
