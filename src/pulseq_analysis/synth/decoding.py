"""The decoding of a file by its interpreter (stage 2 of section 7.2 of
`docs/plans/parser-redesign.md`): `decode(data)` picks the decoder from `data.interpreter`.

- `spec`: the package's decoder of the events (`events`), `SpecDecoding`: each gradient event of
  the model by its ID, and `gradients_at`, each block's gradients as the straight lines between
  the points of its events (`seq_utils.gradient_offsets`). From version 1.5.1 `gradients_at`
  rotates the gradients of each block that has a rotation (ROTATIONS, D2.18) by its quaternion,
  which the model has divided by its norm: `spec` applies this content of the file from the
  revision that introduced it (P20, rule 2), with the package's own rotation (`rotate`). It has no
  setting for it, and nothing to warn about (rule 4). In an older file ROTATIONS is an unknown
  extension, ignored and recorded (`SequenceData.records`). The RF and ADC events are
  `events.decode_rf` and `events.decode_adc` of the model, which the decoding does not build.
- A plugin interpreter (`seqfile.interpreters.Plugin`): its own decoding, which its `decode`
  method gives (P21). It has the methods of the protocol `Decoding`, which is what the package
  uses of a decoding.

`decode(data, session)` applies the scanner session (`scanner.Session`, rule 3 of section 7.8 of
the plan; the neutral session by default): `spec` with the shared simulation of `scanner`, a
plugin with its own hooks (P22). Each decoding gives the stored and the actual duration of each
block (the actual one is the stored one, except where the session sets a soft delay), and records
what it applied (`rotation_record`, `soft_delay_record`, `fov_record`). `spec` applies the soft
delays from 1.5.0 and the flags NOROT and NOSLC (the specification's spelling, D2.22) from 1.4.1.

The decodings can differ: a plugin can decode a block at a time, `spec` decodes an event at a
time, and a plugin can decode one gradient event otherwise in two blocks (`gradient_variants`).
The measurements (`analyses.load`, R14) take their gradients from these decodings, through the
methods `gradient_points` and `gradient_variants` of the protocol (`_played`).
"""

import dataclasses
from collections.abc import Container, Mapping
from typing import Any, Protocol, runtime_checkable

import numpy as np

from ..seqfile.interpreters import Spec
from ..seqfile.model import SequenceData
from . import events
from .scanner import (
    FovRecord,
    RotationRecord,
    Session,
    SoftDelay,
    SoftDelayRecord,
    fov_flags,
    fov_record,
    physical_gradients,
    soft_delay_durations,
)
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
    - `session`: the scanner session that the decoding applies (`scanner.Session`).
    - `block_count`: the number of blocks.
    - `block_durations` and `stored_block_durations`: the actual and the stored duration of
      each block (s, float64, read-only): the actual one is the stored one, except for a block
      whose soft delay the session sets. The measurements use the actual one.
    - `rotations()`: the play indices of the blocks with a rotation (int64), and their
      quaternions, an array (n, 4) of q0, qx, qy and qz of norm 1.
    - `rotation_record`: what the decoding does with the rotations (`scanner.RotationRecord`).
    - `soft_delay_record` and `fov_record`: what it does with the session's soft delays and
      field of view (`scanner.SoftDelayRecord`, `scanner.FovRecord`).
    - `fov_flags()`: the flag NOROT and the flag that turns off the scaling, of each block
      (two bool arrays, `scanner.fov_flags`).
    - `gradients_at(block_index, time_us, rotated=None)`: the gradients (Hz/m) at each pair of
      a block index and a time in us from the start of that block, an array (n, 3), 0 after the
      actual end of the block; `rotated` None follows the interpreter and the session, False
      gives the logical gradients, True also rotates each block by its rotation.
    - `gradient_points(key, block, axis)`: the `Points` of the gradient event with the file ID
      `key` that the block `block` plays on the axis `axis` (0, 1, 2 for x, y, z), not
      rotated.
    - `gradient_variants()`: which cells (a block and an axis) decode their gradient event
      alike. None when each gradient event decodes alike in every block that plays it.
      Otherwise an int64 array (blocks, 3), read-only, one value for each block and axis: two
      cells with the same event and the same value decode alike (`gradient_points` gives the
      same points for both). The values have no meaning beyond that, and a cell with no event
      has 0."""

    interpreter: Any
    session: Session

    @property
    def block_count(self) -> int: ...

    @property
    def block_durations(self) -> np.ndarray: ...

    @property
    def stored_block_durations(self) -> np.ndarray: ...

    def rotations(self) -> tuple[np.ndarray, np.ndarray]: ...

    @property
    def rotation_record(self) -> RotationRecord: ...

    @property
    def soft_delay_record(self) -> SoftDelayRecord: ...

    @property
    def fov_record(self) -> FovRecord: ...

    def fov_flags(self) -> tuple[np.ndarray, np.ndarray]: ...

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray: ...

    def gradient_points(self, key: int, block: int, axis: int) -> Points: ...

    def gradient_variants(self) -> np.ndarray | None: ...


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
    """The decoding of a file that the `spec` interpreter read: its gradient events
    (`events.decode_gradients`) by file ID, and its blocks: `blocks` is the block table of the
    model, `block_durations` the actual duration of each block (s) under the session and
    `stored_block_durations` the duration that the file stores, in play order from 0.

    `rotation_blocks` and `rotation_quaternions` are the rotation of each block (`rotations`).
    Both are empty for a file older than 1.5.1. `norot` and `noscale` are the flags NOROT and
    NOSLC of each block (`fov_flags`), all False for a file older than 1.4.1. The arrays are
    read-only.

    No measurement reads the RF and ADC events, so the decoding does not build them: they are
    `events.decode_rf(data)` and `events.decode_adc(data)` of the model."""

    interpreter: Spec
    gradients: Mapping[int, events.GradEvent]
    blocks: np.ndarray
    block_durations: np.ndarray
    stored_block_durations: np.ndarray
    rotation_blocks: np.ndarray
    rotation_quaternions: np.ndarray
    session: Session
    soft_delay_record: SoftDelayRecord
    fov_record: FovRecord
    norot: np.ndarray
    noscale: np.ndarray
    # The row of `rotation_quaternions` of each block, -1 for a block with no rotation: built once
    # for `gradients_at` (`__post_init__`), read-only.
    _rotation_rows: np.ndarray = dataclasses.field(init=False, repr=False)

    def __post_init__(self) -> None:
        rows = np.full(self.block_count, -1, dtype=np.int64)
        rows[self.rotation_blocks] = np.arange(self.rotation_blocks.size)
        rows.flags.writeable = False
        object.__setattr__(self, "_rotation_rows", rows)

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

    def fov_flags(self) -> tuple[np.ndarray, np.ndarray]:
        """The flags NOROT and NOSLC of each block (`Decoding.fov_flags`), as copies."""
        return self.norot.copy(), self.noscale.copy()

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray:
        """The gradients (Hz/m) at each pair of a block index (play order from 0) and a time in
        us from the start of that block: an array (n, 3) of gx, gy and gz
        (`Decoding.gradients_at`). Each event is the straight lines between
        its points (`seq_utils.gradient_offsets`), from its delay to its end, and 0 before and
        after it; every value is 0 before and after the block (its actual duration).

        `rotated` None or True gives the gradients on the physical axes
        (`scanner.physical_gradients`): the session's gradient scaling of each block without
        NOSLC, the rotation of each block with a rotation (`rotations`) by its quaternion
        (`rotate`), as `spec` applies the rotations of the file from version 1.5.1, and the
        rotation of the session's field of view of each block without NOROT. False gives the
        logical gradients, as the events store them."""
        block_index = np.asarray(block_index, dtype=np.int64).reshape(-1)
        time_us = np.asarray(time_us, dtype=np.float64).reshape(-1)
        if block_index.shape != time_us.shape:
            raise ValueError("block_index and time_us differ in length")
        if np.isnan(time_us).any():
            raise ValueError("a time is NaN")
        if not block_index.size:
            return np.zeros((0, 3))
        if block_index.min() < 0 or block_index.max() >= self.block_count:
            raise IndexError("a block index is not a block of the sequence")
        t = time_us * 1e-6
        out = np.zeros((block_index.size, 3))
        for axis, column in enumerate(_GRAD_COLUMNS):
            # The reads in the order of their event ID, sorted once: the reads of one event are
            # a slice of `order`, from its start to the next.
            ids = self.blocks[column][block_index]
            order = np.argsort(ids)
            sorted_ids = ids[order]
            starts = np.flatnonzero(np.diff(sorted_ids, prepend=sorted_ids[:1] - 1))
            ends = np.append(starts[1:], sorted_ids.size)
            for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
                gid = int(sorted_ids[start])
                if gid == 0:
                    continue
                rows = order[start:end]
                delay, offsets, amp = gradient_offsets(self.gradients[gid])
                out[rows, axis] = np.interp(t[rows] - delay, offsets, amp, left=0.0, right=0.0)
        outside = (t < 0) | (t > self.block_durations[block_index])
        out[outside] = 0.0
        if rotated is not None and not rotated:
            return out
        row = self._rotation_rows
        turned = row[block_index] >= 0
        return physical_gradients(
            out,
            self.session,
            scale_rows=~self.noscale[block_index],
            block_rows=turned,
            block_quaternions=self.rotation_quaternions[row[block_index[turned]]],
            fov_rows=~self.norot[block_index],
            rotate=rotate,
        )

    def gradient_points(self, key: int, block: int, axis: int) -> Points:
        """The `Points` of the gradient event `key` (`Decoding.gradient_points`): the points of
        `seq_utils.gradient_offsets`, the same in each block that plays it."""
        return gradient_offsets(self.gradients[key])

    def gradient_variants(self) -> np.ndarray | None:
        """None (`Decoding.gradient_variants`): `spec` decodes each gradient event alike in
        every block that plays it."""
        return None


def decode(data: SequenceData, session: Session | None = None) -> Decoding:
    """The decoding of `data` by its interpreter under the scanner session `session` (the
    neutral `Session()` for None; the module docstring). Raises `scanner.SettingError` for a
    setting of the session that addresses something the file does not have under the
    interpreter, and TypeError for a `session` that is not a `Session`."""
    if session is None:
        session = Session()
    if not isinstance(session, Session):
        raise TypeError(f"session is a pulseq_analysis.synth.Session, not {type(session)!r}")
    if not isinstance(data.interpreter, Spec):
        return data.interpreter.decode(data, session=session)
    blocks, quaternions = _block_rotations(data)
    stored = data.blocks["duration_ticks"].astype(np.int64)
    ticks, soft_delay_record = soft_delay_durations(
        session,
        _soft_delays(data),
        stored,
        data.rasters.block_duration,
        _pure_delay(data.blocks),
        interpreter=Spec.name,
        version=data.version,
        unavailable=None
        if data.version >= (1, 5, 0)
        else "soft delays came in revision 1.5.0 (spec:545); in an older file extension DELAYS "
        "is an extension that spec does not know (D4.6)",
    )
    flagged = data.version >= (1, 4, 1)
    norot, noscale = fov_flags(
        data.blocks.size,
        _label_sets(data, ("NOROT", "NOSLC")) if flagged else (),
        "NOSLC" if flagged else None,
    )
    norot.flags.writeable = False
    noscale.flags.writeable = False
    durations = ticks * data.rasters.block_duration
    durations.flags.writeable = False
    stored_durations = data.block_durations_s
    stored_durations.flags.writeable = False
    return SpecDecoding(
        interpreter=data.interpreter,
        gradients=events.decode_gradients(data),
        blocks=data.blocks,
        block_durations=durations,
        stored_block_durations=stored_durations,
        rotation_blocks=blocks,
        rotation_quaternions=quaternions,
        session=session,
        soft_delay_record=soft_delay_record,
        fov_record=fov_record(session, norot, noscale, "NOSLC"),
        norot=norot,
        noscale=noscale,
    )


def _pure_delay(blocks: np.ndarray) -> np.ndarray:
    """Whether each block has no RF, gradient or ADC event (spec:545)."""
    return np.all([blocks[c] == 0 for c in ("rf", "gx", "gy", "gz", "adc")], axis=0)


def _extension_objects(
    data: SequenceData, string_id: str, refs: Container[int] | None = None
) -> list[tuple[int, int]]:
    """The (play index, object ID) of each object of the extension `string_id` in the extension
    list of each block, in play order and in the order of each list; empty when the file has no
    such extension. `refs` keeps only the objects whose ID it contains (None keeps them all).
    `spec` rejects a list that does not end and a reference to no object."""
    type_id = data.extensions.type_ids.get(string_id)
    if type_id is None:
        return []
    by_id = {
        int(e["id"]): (int(e["type"]), int(e["ref"]), int(e["next"]))
        for e in data.extensions.entries
    }
    lists: dict[int, list[int]] = {0: []}  # list head -> the object IDs of `string_id`

    def objects_of(head: int) -> list[int]:
        if head not in lists:
            found, entry = [], head
            while entry:
                kind, ref, entry = by_id[entry]
                if kind == type_id and (refs is None or ref in refs):
                    found.append(ref)
            lists[head] = found
        return lists[head]

    heads = data.blocks["ext"].tolist()
    return [(block, ref) for block, head in enumerate(heads) for ref in objects_of(int(head))]


def _soft_delays(data: SequenceData) -> list[SoftDelay]:
    """The soft delays of the blocks (`scanner.SoftDelay`), from the DELAYS objects of each
    block's extension list: the model's table is empty before 1.5.0 (P20, rule 2)."""
    table = data.extensions.soft_delays
    if not table.size:
        return []
    row = {int(i): r for r, i in enumerate(table["id"])}
    return [
        SoftDelay(
            block=block,
            num=int(table["num"][row[ref]]),
            offset=float(table["offset"][row[ref]]),
            factor=float(table["factor"][row[ref]]),
            hint=str(table["hint"][row[ref]]),
        )
        for block, ref in _extension_objects(data, "DELAYS")
    ]


def _label_sets(data: SequenceData, names: tuple[str, ...]) -> list[tuple[int, str, int]]:
    """The (play index, name, value) of each LABELSET object of a name of `names` in each block's
    extension list. The walk of the lists keeps only those objects, and a file with none of them
    walks no list (2.4 of `docs/reviews/2026-10-13-code-review.md`)."""
    table = data.extensions.labelset
    ids, labels = table["id"].tolist(), table["name"].tolist()
    row = {i: r for r, (i, name) in enumerate(zip(ids, labels, strict=True)) if name in names}
    if not row:
        return []
    return [
        (block, str(table["name"][row[ref]]), int(table["value"][row[ref]]))
        for block, ref in _extension_objects(data, "LABELSET", row.keys())
    ]


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
    refs = np.zeros(data.blocks.size, np.int64)
    for block, ref in _extension_objects(data, "ROTATIONS"):
        refs[block] = ref
    return refs
