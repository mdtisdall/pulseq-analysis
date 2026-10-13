"""The decoding of a file by its interpreter (stage 2 of section 7.2 of
`docs/plans/parser-redesign.md`): `decode(data)` picks the decoder from `data.interpreter`.

- `spec`: the package's decoder of the events (`events`), `SpecDecoding`: each event of the
  model by its ID, and `gradients_at`, each block's gradients as the straight lines between the
  points of its events (`seq_utils.gradient_offsets`). From version 1.5.1 `gradients_at` rotates
  the gradients of each block that has a rotation (ROTATIONS, D2.18) by its quaternion, which the
  model has divided by its norm: `spec` applies this content of the file from the revision that
  introduced it (P20, rule 2), with the package's own rotation (`rotate`). It has no setting for
  it, and nothing to warn about (rule 4). In an older file ROTATIONS is an unknown extension,
  ignored and recorded (`SequenceData.records`).
- A plugin interpreter (`seqfile.interpreters.Plugin`): its own decoding, which its `decode`
  method gives (P21). It has the methods of the protocol `Decoding`, which is what the package
  uses of a decoding.

The decodings can differ: a plugin can decode a block at a time, so that an event decodes
differently in two blocks. Task R14 builds the measurements (`load`) on these decodings.
"""

import dataclasses
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import numpy as np

from ..seqfile.interpreters import Spec
from ..seqfile.model import SequenceData
from . import events
from .scanner import RotationRecord
from .seq_utils import gradient_offsets

__all__ = ["Decoding", "Points", "SpecDecoding", "decode", "rotate"]

_GRAD_COLUMNS = ("gx", "gy", "gz")

# The points of one gradient event: its delay (s), and the offsets (s, from the delay) and the
# values (Hz/m) of the points between which it is straight lines (`seq_utils.gradient_offsets`).
Points = tuple[float, np.ndarray, np.ndarray]


@runtime_checkable
class Decoding(Protocol):
    """What the package uses of the decoding of a file (`decode`): `SpecDecoding`, or the
    decoding of a plugin interpreter. Blocks are indexed in play order from 0.

    - `interpreter`: the interpreter of the model, with its settings.
    - `block_count`: the number of blocks.
    - `rotations()`: the play indices of the blocks with a rotation (int64), and their
      quaternions, an array (n, 4) of q0, qx, qy and qz of norm 1.
    - `rotation_record`: what the decoding does with the rotations (`scanner.RotationRecord`).
    - `gradients_at(block_index, time_us, rotated=None)`: the gradients (Hz/m) at each pair of
      a block index and a time in us from the start of that block, an array (n, 3); `rotated`
      None follows the interpreter.
    - `gradient_points(key, block, axis)`: the `Points` of the gradient event with the file ID
      `key` that the block `block` plays on the axis `axis` (0, 1, 2 for x, y, z), not
      rotated."""

    interpreter: Any

    @property
    def block_count(self) -> int: ...

    def rotations(self) -> tuple[np.ndarray, np.ndarray]: ...

    @property
    def rotation_record(self) -> RotationRecord: ...

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray: ...

    def gradient_points(self, key: int, block: int, axis: int) -> Points: ...


def rotate(quaternions: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Each vector of `vectors` (n, 3) turned by the quaternion of the same row of `quaternions`
    (n, 4: q0, qx, qy, qz, q0 the scalar part, of norm 1): the active rotation `R(q) v`, which is
    `q v q*`. It is the rotation of the C++ reader's `rotate_vec3_by_quat` with the sign +1
    (cpp:2666-2684), and of MATLAB Pulseq's
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
        """The rotation of each block (`Decoding.rotations`): the play
        indices (from 0) of the blocks whose extension list has a ROTATIONS object (at most one,
        `extension.per-block`), and their quaternions, an array (n, 4) of q0, qx, qy and qz,
        divided by their norm (D2.18). Empty for a file older than 1.5.1, where ROTATIONS is an
        unknown extension (D4.6)."""
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
        us from the start of that block: an array (n, 3) of gx, gy and gz
        (`Decoding.gradients_at`). Each event is the straight lines between
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

    def gradient_points(self, key: int, block: int, axis: int) -> Points:
        """The `Points` of the gradient event `key` (`Decoding.gradient_points`): the points of
        `seq_utils.gradient_offsets`, the same in each block that plays it."""
        return gradient_offsets(self.gradients[key])


def decode(data: SequenceData) -> Decoding:
    """The decoding of `data` by its interpreter (the module docstring)."""
    if not isinstance(data.interpreter, Spec):
        return data.interpreter.decode(data)
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
