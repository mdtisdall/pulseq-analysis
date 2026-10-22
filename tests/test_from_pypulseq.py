"""Tests of `seqfile.read_pypulseq` (`seqfile.from_pypulseq`, task R15): a pypulseq sequence in
memory, written with pypulseq's writer and read through an interpreter, gives what the file of
`seq.write(path)` gives, and the sequence is not changed. The tests of a plugin interpreter run
the same checks (`check_*`) for their interpreter.
"""

import pytest

pytestmark = pytest.mark.pypulseq
pytest.importorskip("pypulseq")

import copy
import dataclasses
import pickle
import tempfile
import warnings

import numpy as np
import pypulseq as pp
from synthetic import (
    SYSTEM,
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.seqfile import NotSupported, SeqFileError, Spec, read_pypulseq, read_seqfile
from pulseq_analysis.seqfile.from_pypulseq import SOURCE

# The interpreter `spec`, by name and as an object.
INTERPRETERS = [
    pytest.param("spec", id="spec"),
    pytest.param(Spec(), id="Spec()"),
]


def mixed_sequence() -> pp.Sequence:
    """Slice-selective sinc RF, a phase encode and a readout trapezoid with its ADC, an
    arbitrary gradient, labels (SET and INC), a delay block, and repeated events for the
    writer's `remove_duplicates`, in two repetitions."""
    seq = pp.Sequence(SYSTEM)
    rf, gz, _ = pp.make_sinc_pulse(
        flip_angle=np.pi / 6,
        duration=1e-3,
        slice_thickness=5e-3,
        time_bw_product=4,
        system=SYSTEM,
        return_gz=True,
        delay=SYSTEM.rf_dead_time,
        use="excitation",
    )
    gx = pp.make_trapezoid(channel="x", flat_area=64 / 0.2, flat_time=1.28e-3, system=SYSTEM)
    adc = pp.make_adc(num_samples=64, duration=gx.flat_time, delay=gx.rise_time, system=SYSTEM)
    waveform = 0.1 * SYSTEM.max_grad * np.sin(np.pi * (np.arange(30) + 0.5) / 30)
    arb = pp.make_arbitrary_grad(channel="y", waveform=waveform, system=SYSTEM)
    for line in range(2):
        seq.add_block(rf, gz, pp.make_label(label="LIN", type="SET", value=line))
        gy = pp.make_trapezoid(channel="y", area=(line - 1) * 20, duration=1e-3, system=SYSTEM)
        seq.add_block(gy, pp.make_label(label="SLC", type="INC", value=1))
        seq.add_block(gx, adc)
        seq.add_block(arb)
        seq.add_block(pp.make_delay(1e-3))
    return seq


SEQUENCES = {
    "mixed": mixed_sequence,
    "gre": gre_sequence,
    "spin-echo": spin_echo_sequence,
    "arbitrary-gradient": arbitrary_gradient_sequence,
    "border": border_sequence,
    "empty": empty_sequence,
}


def state(seq: pp.Sequence) -> bytes:
    """The state of `seq`, every attribute but pypulseq's block cache, as bytes."""
    return pickle.dumps({k: v for k, v in vars(seq).items() if k != "block_cache"})


def read_written_file(seq, path, interpreter):
    """`read_seqfile` of the file that `seq.write(path)` writes, with the writer's defaults,
    from a copy of `seq` (`write` changes the sequence)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # pypulseq's own timing and ramp-down warnings
        copy.deepcopy(seq).write(str(path))
    return read_seqfile(path, interpreter)


@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize("name", SEQUENCES)
def test_a_sequence_in_memory_reads_as_its_written_file(name, interpreter, tmp_path):
    check_reads_as_its_written_file(SEQUENCES[name](), interpreter, tmp_path)


def check_reads_as_its_written_file(seq, interpreter, tmp_path):
    """`read_pypulseq` of `seq` is `read_seqfile` of its written file, with `origin`
    `"pypulseq"`."""
    data = read_pypulseq(seq, interpreter)
    assert data.origin == "pypulseq"
    expected = read_written_file(seq, tmp_path / "sequence.seq", interpreter)
    assert dataclasses.replace(data, origin="file") == expected
    assert data.interpreter == expected.interpreter
    assert data.signature is not None
    assert data.signature == expected.signature


@pytest.mark.parametrize("interpreter", INTERPRETERS)
def test_the_mixed_sequence_has_each_kind_of_event(interpreter):
    check_the_mixed_sequence(interpreter)


def check_the_mixed_sequence(interpreter):
    """The model of `mixed_sequence` through `interpreter` has each kind of event."""
    data = read_pypulseq(mixed_sequence(), interpreter)
    assert len(data.blocks) == 10
    assert len(data.rf) == 1  # the writer merged the repeated RF event
    assert len(data.adc) == 1
    assert len(data.trap) >= 3
    assert len(data.grad) == 1
    assert len(data.extensions.labelset) == 2
    assert len(data.extensions.labelinc) == 1


@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize("name", SEQUENCES)
def test_the_sequence_is_not_changed(name, interpreter):
    check_the_sequence_is_not_changed(SEQUENCES[name](), interpreter)


def check_the_sequence_is_not_changed(seq, interpreter):
    """`read_pypulseq` leaves `seq` as it was."""
    before = state(seq)
    definitions = dict(seq.definitions)
    read_pypulseq(seq, interpreter)
    assert state(seq) == before
    assert seq.definitions == definitions
    assert "TotalDuration" not in seq.definitions
    assert seq.signature_value == ""


def test_the_temporary_folder_is_removed_and_nothing_is_written_next_to_the_caller(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", None)
    read_pypulseq(gre_sequence())
    assert [p.name for p in tmp_path.iterdir()] == ["tmp"]
    assert list((tmp_path / "tmp").iterdir()) == []


def short_block_sequence() -> pp.Sequence:
    """A trapezoid of 1 ms in a block of 0.5 ms (`spec` rejects it: `block.event-too-long`)."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=100, duration=1e-3, system=SYSTEM))
    seq.block_durations[1] = 0.5e-3
    return seq


def test_a_rejection_is_the_file_s_and_names_the_sequence_not_the_temporary_file(tmp_path):
    check_a_rejection(short_block_sequence(), "spec", "block.event-too-long", tmp_path)


def check_a_rejection(seq, interpreter, code, tmp_path):
    """`interpreter` rejects `seq` with `code`, as it rejects its written file, and the error
    names the sequence (`SOURCE`), not the temporary file."""
    with pytest.raises(SeqFileError) as caught:
        read_pypulseq(seq, interpreter)
    with pytest.raises(SeqFileError) as from_file:
        read_written_file(seq, tmp_path / "sequence.seq", interpreter)
    error = caught.value
    assert error.codes == {code}
    assert error.violations == from_file.value.violations
    assert error.path == SOURCE
    assert error.interpreter == interpreter
    assert SOURCE in str(error)
    assert "sequence.seq" not in str(error)
    assert error.__cause__ is None and error.__suppress_context__


def test_a_shape_over_the_limit_of_read_pypulseq_names_the_sequence_not_the_temporary_file(
    tmp_path,
):
    interpreter = Spec(max_shape_samples=3)
    with pytest.raises(NotSupported) as caught:
        read_pypulseq(arbitrary_gradient_sequence(), interpreter)
    path = tmp_path / "sequence.seq"
    with pytest.raises(NotSupported) as from_file:
        read_written_file(arbitrary_gradient_sequence(), path, interpreter)
    error = caught.value
    assert str(error) == str(from_file.value).replace(str(path), SOURCE)
    assert SOURCE in str(error)
    assert "sequence.seq" not in str(error)
    assert error.__cause__ is None and error.__suppress_context__


def test_an_unknown_interpreter_and_an_object_that_is_not_a_sequence_raise():
    with pytest.raises(ValueError, match="no interpreter"):
        read_pypulseq(gre_sequence(), "matlab")
    with pytest.raises(TypeError, match="pypulseq.Sequence"):
        read_pypulseq("sequence.seq")
