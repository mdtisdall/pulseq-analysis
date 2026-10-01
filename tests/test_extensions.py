import pypulseq as pp
import pytest
from pypulseq.event_lib import EventLibrary
from synthetic import (
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.extensions import refuse_rotations

# A scalar-first unit quaternion (angle 45 deg about z): q0=cos(22.5deg), qz=sin(22.5deg).
_QUATERNION = (0.9238795325112867, 0.0, 0.0, 0.3826834323650898)


def _with_rotation_library() -> pp.Sequence:
    """A `gre_sequence` with one rotation stored the way pypulseq draft PR #372 stores
    it: a `rotation_library` (an `EventLibrary` of scalar-first unit quaternions)."""
    seq = gre_sequence(num_trs=2)
    seq.rotation_library = EventLibrary()
    seq.rotation_library.insert(1, _QUATERNION)
    return seq


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
        refuse_rotations(_with_rotation_library())


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
