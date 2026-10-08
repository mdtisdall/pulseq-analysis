import pypulseq as pp
import pytest
from pypulseq.event_lib import EventLibrary
from synthetic import (
    arbitrary_gradient_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
    with_rotation_library,
)

from pulseq_analysis.extensions import refuse_rotations


def _with_rotations_extension_type() -> pp.Sequence:
    """A `gre_sequence` with the `"ROTATIONS"` extension type registered, the way PR
    #372's `Sequence.read` registers it while reading a file with a rotation section."""
    seq = gre_sequence(num_trs=2)
    seq.set_extension_string_ID("ROTATIONS", 1)
    return seq


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
