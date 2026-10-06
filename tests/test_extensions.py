import pypulseq as pp
import pytest
from pypulseq.event_lib import EventLibrary
from synthetic import (
    EXAMPLE_HW,
    SYSTEM,
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
    with_rotation_library,
)

from pulseq_analysis import grad_peaks, grad_spectrum, pns_levels
from pulseq_analysis.extensions import refuse_rotations, refuse_unsigned

_MEASUREMENTS = {
    "gradient_peaks": grad_peaks.gradient_peaks,
    "block_gradient_values": grad_peaks.block_gradient_values,
    "pns_levels": lambda seq: pns_levels.pns_levels(seq, hardware=EXAMPLE_HW),
    "gradient_spectrum": grad_spectrum.gradient_spectrum,
}


def _in_memory_sequence() -> pp.Sequence:
    """A sequence that only `add_block` built: one trapezoid on x and a delay. It has no
    `[SIGNATURE]` hash (`signature_value` is `''`), unlike the builders of `synthetic.py`."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=1000, system=SYSTEM))
    seq.add_block(pp.make_delay(1e-3))
    return seq


def _write_unsigned_file(path) -> None:
    """Write `_in_memory_sequence()` to `path` as a `.seq` file, and remove its `[SIGNATURE]`
    section."""
    _in_memory_sequence().write(str(path))
    text = path.read_text()
    path.write_text(text[: text.index("[SIGNATURE]")])


def _with_rotations_extension_type() -> pp.Sequence:
    """A `gre_sequence` with the `"ROTATIONS"` extension type registered, the way PR
    #372's `Sequence.read` registers it while reading a file with a rotation section."""
    seq = gre_sequence(num_trs=2)
    seq.set_extension_string_ID("ROTATIONS", 1)
    return seq


def _write_rotation_file(path) -> None:
    """Write a `.seq` file with a rotation extension on its second block, in the format
    that PR #372's writer uses: an `[EXTENSIONS]` section, an `extension ROTATIONS`
    section with one quaternion, and the second block's extension list id set to that
    extension list. The `[SIGNATURE]` section is removed, so its MD5 does not matter."""
    seq = gre_sequence(num_trs=2)
    seq.write(str(path))
    text = path.read_text()

    lines = text.split("\n")
    i = lines.index("[BLOCKS]") + 1
    while lines[i].startswith("#") or not lines[i].strip():
        i += 1
    row = lines[i + 1].split()
    row[-1] = "1"  # point the second block at extension list 1
    lines[i + 1] = " ".join(row)
    text = "\n".join(lines)

    extensions_section = (
        "[EXTENSIONS]\n1 1 1 0\n\n"
        "# id RotQuat0 RotQuatX RotQuatY RotQuatZ\n"
        "extension ROTATIONS 1\n1 0.923880 0 0 0.382683\n\n"
    )
    marker = "# Sequence Shapes" if "# Sequence Shapes" in text else "[SIGNATURE]"
    text = text.replace(marker, extensions_section + marker, 1)
    text = text[: text.index("[SIGNATURE]")] if "[SIGNATURE]" in text else text
    path.write_text(text)


@pytest.mark.parametrize(
    "factory",
    [spin_echo_sequence, gre_sequence, arbitrary_gradient_sequence, empty_sequence],
)
def test_refuse_rotations_accepts_synthetic_sequences(factory):
    """`refuse_rotations` raises nothing for the synthetic sequences: none of them uses
    the rotation extension."""
    refuse_rotations(factory())


def test_refuse_rotations_raises_for_a_rotation_library():
    """A non-empty `seq.rotation_library` (as PR #372 stores rotations in memory) is
    refused."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        refuse_rotations(with_rotation_library())


def test_refuse_rotations_raises_for_a_rotations_extension_type():
    """A `"ROTATIONS"` entry in `seq.extension_string_idx` (as PR #372's `Sequence.read`
    adds it) is refused."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        refuse_rotations(_with_rotations_extension_type())


def test_refuse_rotations_ignores_an_empty_rotation_library():
    """A `seq.rotation_library` attribute that exists but holds no data is not a
    rotation: `refuse_rotations` raises nothing."""
    seq = gre_sequence(num_trs=2)
    seq.rotation_library = EventLibrary()
    refuse_rotations(seq)


def test_refuse_unsigned_raises_for_a_sequence_built_in_memory():
    """A sequence that only `add_block` built has no hash: `refuse_unsigned` raises
    `ValueError`, and the message names the `[SIGNATURE]` hash."""
    seq = _in_memory_sequence()
    assert seq.signature_value == ""
    with pytest.raises(ValueError, match=r"no \[SIGNATURE\] hash"):
        refuse_unsigned(seq)


@pytest.mark.parametrize(
    "factory",
    [spin_echo_sequence, gre_sequence, arbitrary_gradient_sequence, empty_sequence],
)
def test_refuse_unsigned_accepts_synthetic_sequences(factory):
    """`refuse_unsigned` raises nothing for the synthetic sequences: each builder in
    `tests/synthetic.py` gives a signed sequence."""
    refuse_unsigned(factory())


@pytest.mark.parametrize("value", [0.0, 1, None, b"0123"])
def test_refuse_unsigned_raises_for_a_signature_value_that_is_not_a_str(value):
    """A `signature_value` that is not a `str` is not a hash: `refuse_unsigned` raises
    `ValueError`. pypulseq's `read` of `pulseq-reports-pin-1` kept a hash that looks like
    a number as a float."""
    seq = _in_memory_sequence()
    seq.signature_value = value
    with pytest.raises(ValueError, match=r"no \[SIGNATURE\] hash"):
        refuse_unsigned(seq)


def test_refuse_unsigned_accepts_a_sequence_after_write(tmp_path):
    """`write` signs the sequence it writes: the same object that `refuse_unsigned`
    refused before passes after `write`."""
    seq = _in_memory_sequence()
    with pytest.raises(ValueError, match=r"no \[SIGNATURE\] hash"):
        refuse_unsigned(seq)
    seq.write(str(tmp_path / "a.seq"))
    refuse_unsigned(seq)


def test_refuse_unsigned_accepts_a_read_of_a_signed_file(tmp_path):
    """A new `Sequence` that `read` a signed file has the hash of the file: it passes."""
    path = tmp_path / "a.seq"
    _in_memory_sequence().write(str(path))
    seq = pp.Sequence(SYSTEM)
    seq.read(str(path))
    refuse_unsigned(seq)


def test_refuse_unsigned_raises_for_a_read_of_an_unsigned_file(tmp_path):
    """A new `Sequence` that `read` a file with no `[SIGNATURE]` section has no hash:
    `refuse_unsigned` raises `ValueError`."""
    path = tmp_path / "a.seq"
    _write_unsigned_file(path)
    assert "[SIGNATURE]" not in path.read_text()
    seq = pp.Sequence(SYSTEM)
    seq.read(str(path))
    with pytest.raises(ValueError, match=r"no \[SIGNATURE\] hash"):
        refuse_unsigned(seq)


@pytest.mark.parametrize("name", list(_MEASUREMENTS))
def test_each_measurement_raises_for_a_sequence_built_in_memory(name):
    """Each public measurement raises `ValueError` for a sequence with no hash. They
    reach `refuse_unsigned` through `sequence_index`."""
    with pytest.raises(ValueError, match=r"no \[SIGNATURE\] hash"):
        _MEASUREMENTS[name](_in_memory_sequence())


@pytest.mark.parametrize("name", list(_MEASUREMENTS))
def test_each_measurement_accepts_a_sequence_after_write(name, tmp_path):
    """After `write` signs a sequence, each public measurement gives a result for it."""
    seq = _in_memory_sequence()
    seq.write(str(tmp_path / "a.seq"))
    assert _MEASUREMENTS[name](seq) is not None
