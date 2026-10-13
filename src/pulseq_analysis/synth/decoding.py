"""The decoding of a file by its interpreter (stage 2 of section 7.2 of
`docs/plans/parser-redesign.md`): `decode(data)` picks the decoder from `data.interpreter`.

- `cpp-siemens`: the C++ reader's own decoding, `CppSiemensDecoding`: `GetBlock` and
  `decodeBlock` of each block (`block`, `blocks`), and `SeqBlock::gradientsAt`
  (`gradients_at`). These are the values that the reader gives, bit for bit: its float32
  values, the resampling of RF pulses, the clamps of `checkRF` and `checkGradient`, the sampling
  mode of an oversampled gradient (the setting `oversampling` of the interpreter), and its
  misreadings. The reader gives each block's rotation (`rotations`) and applies it to nothing;
  with the setting `rotation="apply"`, `gradients_at` rotates the gradients of each block that
  has one, with the reader's own `rotate_vec3_by_quat` (the package's simulation of the
  scanner). `rotation_record` records what was applied (`scanner.RotationRecord`).
- `spec`: the package's decoder of the events (`events`), `SpecDecoding`: each event of the
  model by its ID.

The two kinds differ: the C++ reader decodes a block at a time, and an event can decode
differently in two blocks (an extended trapezoid reuses the buffer of the block's shapes). Task
R14 builds the measurements (`load`) on these decodings.
"""

import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any

import numpy as np

from ..seqfile.interpreters import CppSiemens, Spec
from ..seqfile.model import SequenceData
from . import events
from .scanner import RotationRecord

__all__ = ["CppSiemensDecoding", "SpecDecoding", "decode"]


@dataclasses.dataclass(frozen=True, slots=True)
class SpecDecoding:
    """The events of a file that the `spec` interpreter read (`events`), by file ID."""

    interpreter: Spec
    rf: Mapping[int, events.RfEvent]
    gradients: Mapping[int, events.GradEvent]
    adc: Mapping[int, events.AdcEvent]


class CppSiemensDecoding:
    """The C++ reader's decoding of a file that `cpp-siemens` read: a view of
    `SequenceData.reading` (a `pulseq_cpp_siemens.Sequence`). Blocks are indexed in play order
    from 0; the reader decodes each on request, and keeps it for `gradients_at`."""

    def __init__(self, data: SequenceData) -> None:
        self.interpreter: CppSiemens = data.interpreter
        self._reading = data.reading
        self._rotation_record: RotationRecord | None = None

    @property
    def block_count(self) -> int:
        return int(self._reading.block_count)

    def block(self, index: int) -> dict[str, Any]:
        """`GetBlock` and `decodeBlock` of the block `index`: the fields of the C++ oracle's
        `--dump` (`tests/cpp_oracle/README.md`), in the reader's units (us, Hz, Hz/m, rad), with
        the RF and gradient samples after the resampling and the clamps."""
        return self._reading.decode_block(index)

    def blocks(self) -> Iterator[dict[str, Any]]:
        """`block` of each block, in play order."""
        for index in range(self.block_count):
            yield self.block(index)

    def rotations(self) -> tuple[np.ndarray, np.ndarray]:
        """The rotation of each block, as the reader gives it: the play indices (from 0) of the
        blocks to which `GetBlock` attaches a rotation (the first of the block's extension list,
        D48), and their quaternions, an array (n, 4) of q0, qx, qy and qz, as the reader divided
        them by their norm (D49). The same in each setting."""
        return self._reading.block_rotations()

    @property
    def rotation_record(self) -> RotationRecord:
        """What the decoding does with the rotations of the file (rule 4 of P20): the setting,
        the blocks with a rotation, those that are not the identity, and those rotated."""
        if self._rotation_record is None:
            indices, quaternions = self.rotations()
            setting = self.interpreter.rotation
            self._rotation_record = RotationRecord(
                setting=setting,
                blocks=int(indices.size),
                not_identity=int(np.count_nonzero(np.any(quaternions[:, 1:] != 0, axis=1))),
                rotated=int(indices.size) if setting == "apply" else 0,
            )
        return self._rotation_record

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray:
        """`SeqBlock::gradientsAt` (Hz/m) at each pair of a block index and a time in us from the
        start of that block: an array (n, 3) of gx, gy and gz (0 before and after the block).

        `rotated` None follows the interpreter's setting `rotation`. False gives the values as
        the reader gives them, the logical gradients. True turns the values of each block with a
        rotation (`rotations`) by its quaternion, with the reader's `rotate_vec3_by_quat`: the
        gradients that the scanner plays when it applies the rotation."""
        if rotated is None:
            rotated = self.interpreter.rotation == "apply"
        return self._reading.gradients_at(block_index, time_us, rotated=rotated)


def decode(data: SequenceData) -> SpecDecoding | CppSiemensDecoding:
    """The decoding of `data` by its interpreter (the module docstring)."""
    if isinstance(data.interpreter, CppSiemens):
        return CppSiemensDecoding(data)
    return SpecDecoding(
        interpreter=data.interpreter,
        rf=events.decode_rf(data),
        gradients=events.decode_gradients(data),
        adc=events.decode_adc(data),
    )
