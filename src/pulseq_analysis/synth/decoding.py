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
  model by its ID, and `gradients_at`, each block's gradients as the straight lines between the
  points of its events (`seq_utils.gradient_offsets`). From version 1.5.1 `gradients_at` rotates
  the gradients of each block that has a rotation (ROTATIONS, D49) by its quaternion, which the
  model has divided by its norm: `spec` applies this content of the file from the revision that
  introduced it (P20, rule 2), with the package's own rotation (`rotate`). It has no setting for
  it, and nothing to warn about (rule 4). In an older file ROTATIONS is an unknown extension,
  ignored and recorded (`SequenceData.records`).

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
from .seq_utils import gradient_offsets

__all__ = ["CppSiemensDecoding", "SpecDecoding", "decode", "rotate"]

_GRAD_COLUMNS = ("gx", "gy", "gz")


def rotate(quaternions: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Each vector of `vectors` (n, 3) turned by the quaternion of the same row of `quaternions`
    (n, 4: q0, qx, qy, qz, q0 the scalar part, of norm 1): the active rotation `R(q) v`, which is
    `q v q*`. It is the rotation of the C++ reader's `rotate_vec3_by_quat` with the sign +1
    (cpp:2666-2684), which `CppSiemens(rotation="apply")` uses, and of MATLAB Pulseq's
    `mr.rotate3D`, in float64."""
    q = np.asarray(quaternions, dtype=np.float64).reshape(-1, 4)
    v = np.asarray(vectors, dtype=np.float64).reshape(-1, 3)
    w, u = q[:, :1], q[:, 1:]
    t = 2 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class SpecDecoding:
    """The decoding of a file that the `spec` interpreter read: its events (`events`) by file
    ID, and its blocks: `blocks` is the block table of the model and `block_durations` the
    duration of each block (s), in play order from 0.

    `rotation_blocks` and `rotation_quaternions` are the rotation of each block (`rotations`).
    Both are empty for a file older than 1.5.1. The arrays are read-only."""

    interpreter: Spec
    rf: Mapping[int, events.RfEvent]
    gradients: Mapping[int, events.GradEvent]
    adc: Mapping[int, events.AdcEvent]
    blocks: np.ndarray
    block_durations: np.ndarray
    rotation_blocks: np.ndarray
    rotation_quaternions: np.ndarray

    @property
    def block_count(self) -> int:
        return int(self.blocks.size)

    def rotations(self) -> tuple[np.ndarray, np.ndarray]:
        """The rotation of each block, as `CppSiemensDecoding.rotations` gives it: the play
        indices (from 0) of the blocks whose extension list has a ROTATIONS object (at most one,
        `extension.per-block`), and their quaternions, an array (n, 4) of q0, qx, qy and qz,
        divided by their norm (D49). Empty for a file older than 1.5.1, where ROTATIONS is an
        unknown extension (D58)."""
        return self.rotation_blocks.copy(), self.rotation_quaternions.copy()

    @property
    def rotation_record(self) -> RotationRecord:
        """What the decoding does with the rotations of the file (rule 4 of P20): `spec`
        applies them, so the setting is `"apply"` and every block with a rotation is rotated;
        the record never has a warning."""
        blocks = int(self.rotation_blocks.size)
        not_identity = np.any(self.rotation_quaternions[:, 1:] != 0, axis=1)
        return RotationRecord(
            setting="apply",
            blocks=blocks,
            not_identity=int(np.count_nonzero(not_identity)),
            rotated=blocks,
        )

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray:
        """The gradients (Hz/m) at each pair of a block index (play order from 0) and a time in
        us from the start of that block: an array (n, 3) of gx, gy and gz, as
        `CppSiemensDecoding.gradients_at` gives them. Each event is the straight lines between
        its points (`seq_utils.gradient_offsets`), from its delay to its end, and 0 before and
        after it; every value is 0 before and after the block.

        `rotated` None or True turns the values of each block with a rotation (`rotations`) by
        its quaternion (`rotate`): `spec` applies the rotations of the file, from version 1.5.1.
        False gives the logical gradients, as the events store them."""
        block_index = np.asarray(block_index, dtype=np.int64).reshape(-1)
        time_us = np.asarray(time_us, dtype=np.float64).reshape(-1)
        if block_index.shape != time_us.shape:
            raise ValueError("block_index and time_us differ in length")
        if np.isnan(time_us).any():
            raise ValueError("a time is NaN")
        if block_index.size and (block_index.min() < 0 or block_index.max() >= self.block_count):
            raise IndexError("a block index is not a block of the sequence")
        t = time_us * 1e-6
        out = np.zeros((block_index.size, 3))
        for axis, column in enumerate(_GRAD_COLUMNS):
            ids = self.blocks[column][block_index]
            for gid in np.unique(ids[ids != 0]):
                rows = np.flatnonzero(ids == gid)
                delay, offsets, amp = gradient_offsets(self.gradients[int(gid)])
                out[rows, axis] = np.interp(t[rows] - delay, offsets, amp, left=0.0, right=0.0)
        outside = (t < 0) | (t > self.block_durations[block_index])
        out[outside] = 0.0
        if rotated is None or rotated:
            row = np.full(self.block_count, -1)
            row[self.rotation_blocks] = np.arange(self.rotation_blocks.size)
            turned = np.flatnonzero(row[block_index] >= 0)
            q = self.rotation_quaternions[row[block_index[turned]]]
            out[turned] = rotate(q, out[turned])
        return out


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
    blocks, quaternions = _block_rotations(data)
    return SpecDecoding(
        interpreter=data.interpreter,
        rf=events.decode_rf(data),
        gradients=events.decode_gradients(data),
        adc=events.decode_adc(data),
        blocks=data.blocks,
        block_durations=data.block_durations_s,
        rotation_blocks=blocks,
        rotation_quaternions=quaternions,
    )


def _block_rotations(data: SequenceData) -> tuple[np.ndarray, np.ndarray]:
    """`SpecDecoding.rotations` of the model of `spec`, as read-only arrays: the ROTATIONS object
    of each block's extension list. The model's ROTATIONS table is empty before 1.5.1 (P20, rule
    2), and `spec` rejects a block with more than one rotation, a list that does not end, and a
    reference to no object."""
    rotations = data.extensions.rotations
    refs = _rotation_refs(data) if rotations.size else np.zeros(data.blocks.size, np.int64)
    blocks = np.flatnonzero(refs).astype(np.int64)
    row = {int(i): r for r, i in enumerate(rotations["id"])}
    table = np.stack([rotations[c] for c in ("q0", "qx", "qy", "qz")], axis=1)
    quaternions = table[[row[int(ref)] for ref in refs[blocks]]].reshape(-1, 4)
    blocks.flags.writeable = False
    quaternions.flags.writeable = False
    return blocks, quaternions


def _rotation_refs(data: SequenceData) -> np.ndarray:
    """The ID of the ROTATIONS object in the extension list of each block, 0 for none."""
    by_id = {
        int(e["id"]): (int(e["type"]), int(e["ref"]), int(e["next"]))
        for e in data.extensions.entries
    }
    rotation_type = data.extensions.type_ids["ROTATIONS"]
    found = {0: 0}  # list head -> the ROTATIONS ID, 0 for none

    def rotation_of(head: int) -> int:
        if head not in found:
            entry, ref = head, 0
            while entry and not ref:
                kind, row_ref, entry = by_id[entry]
                ref = row_ref if kind == rotation_type else 0
            found[head] = ref
        return found[head]

    return np.array([rotation_of(int(head)) for head in data.blocks["ext"]], dtype=np.int64)
