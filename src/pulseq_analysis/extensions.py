"""Guards for Pulseq extensions that the measurements of this package do not support."""

import pypulseq as pp

_ROTATIONS = "ROTATIONS"  # the extension type name in a .seq file and in pypulseq


def refuse_rotations(seq: pp.Sequence) -> None:
    """Raise `NotImplementedError` when `seq` uses the Pulseq rotation extension.

    The measurements of the gradients (`grad_peaks.gradient_peaks`,
    `grad_peaks.block_gradient_values`, `pns_levels.pns_levels` and
    `grad_spectrum.gradient_spectrum`) use the logical gradient events as they are stored. With a
    rotation in a block, the gradients on the scanner are different, so these
    measurements would be wrong without a warning. They call this function first.

    The check reads no block, so its cost does not grow with the number of blocks. It
    finds a rotation in two ways:

    - a non-empty `seq.rotation_library`. pypulseq 1.5.0.post1 has no such attribute.
      The rotation extension of pypulseq draft PR #372 adds it, and `make_rotation`
      events in `add_block` fill it.
    - `"ROTATIONS"` in `seq.extension_string_idx`. In PR #372, `Sequence.read` adds
      it for a file with an `extension ROTATIONS` section.

    Limit: pypulseq 1.5.0.post1 cannot make a rotation, and its `Sequence.read` raises
    `ValueError` ("Unknown section code: extension ROTATIONS ...") for a file with
    rotations. Thus, with that version, no sequence with rotations gets to this check.
    A later pypulseq that stores rotations in a different way can get past it.
    """
    library = getattr(seq, "rotation_library", None)
    if (library is not None and len(library.data) > 0) or _ROTATIONS in seq.extension_string_idx:
        raise NotImplementedError(
            "This sequence uses the Pulseq rotation extension, which the gradient "
            "measurements do not support yet: they use the logical gradients as they are "
            "stored, and a rotation changes the gradients on the scanner."
        )
