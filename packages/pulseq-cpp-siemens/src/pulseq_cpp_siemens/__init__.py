"""The C++ reader of Pulseq files on Siemens scanners, in the process: `ExternalSequence` of
pulseq/pulseq at c7469123 (MIT; `LICENSE.pulseq` in this package's metadata), the reader of the
Pulseq interpreter on Siemens systems, compiled with a signed `char` and no fused multiply-add as
its x86_64 build.

    sequence = load("file.seq")       # ExternalSequence::load, then the checks
    load("file.seq", oversampling="edge")  # the reader's other sampling modes (OVERSAMPLING)
    load("file.seq", max_shape_samples=None)  # no limit of the samples of a shape
    sequence.libraries                # what load read: events, shapes, blocks, definitions
    sequence.decode_block(0)          # GetBlock and decodeBlock of one block
    sequence.decode()                 # every block, in play order
    sequence.gradients_at([0], [5.0]) # SeqBlock::gradientsAt (Hz/m)
    sequence.gradients_at([0], [5.0], rotated=True)  # turned by each block's rotation
    sequence.block_rotations()        # the blocks with a rotation, and their quaternions
    sequence.block_soft_delays()      # the blocks with a soft delay, and its fields
    sequence.block_label_sets()       # the LABELSET events of each block
    sequence.block_durations_ru(actual)  # GetDuration_ru after setActualSoftDelay_ru
    sequence.first_rejected_block()   # the driver's first mode, keeping no block
    rotate_vec3_by_quat(q, v)         # the reader's rotation of vectors by quaternions

`load` refuses a version outside 1.4.0-1.5.x before the reader reads the file (`NotSupported`),
and a shape that declares more samples than `max_shape_samples` (2^27 by default) after
`ExternalSequence::load` and before any shape is decompressed, or an RF pulse that `decodeBlock`
would resample into more cells, before any block is decoded (`NotSupported`). It rejects a file
with a case of undefined behaviour of the reader before any block is decoded
(`UndefinedBehaviour`, with every case and its code), so that the process survives the file.
The checks take a `long` of 32 bits, as the Windows build of the reader has, on every host
(D5.11). A case that only a soft delay reaches (`actual_ru` longer than the stored duration of a
block) is refused by `gradients_at`, at the times where the reader would meet it.

Calls are safe from several threads, also on one `Sequence`: the extension holds one lock for
each call into the reader, sets the reader's shared state for the sequence it works on, reads
numbers in the "C" locale, and returns the reader's messages of each call with its result, so that
each `Rejected` has the messages of its own call. `Sequence.rejection_messages` is an attribute of
the `Sequence`: with several threads, it has the messages of the last call of
`first_rejected_block` to return.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import NamedTuple

import numpy as np

from . import _checks, _reader
from ._checks import CODES

__all__ = [
    "BLOCK_COLUMNS",
    "CODES",
    "OVERSAMPLING",
    "PULSEQ_COMMIT",
    "Libraries",
    "NotSupported",
    "Rejected",
    "Sequence",
    "Shape",
    "SoftDelays",
    "UndefinedBehaviour",
    "load",
    "rotate_vec3_by_quat",
]

PULSEQ_COMMIT: str = _reader.PULSEQ_COMMIT

# The columns of `Libraries.blocks`: the block duration in units of BlockDurationRaster, then
# the IDs of the events (0 for none), as the reader holds them.
BLOCK_COLUMNS = ("duration_ru", "rf", "gx", "gy", "gz", "adc", "ext")

# The reader's sampling modes of an oversampled arbitrary gradient (a wave shape and time shape -1;
# cpp:2123-2146), the values of `load`'s `oversampling`: the samples at the centres of the rasters
# (the reader's default), those on the edges (SetArbGradCenterSampling(false); the stored samples
# at odd positions, one fewer), or all the stored samples (SetArbGradPreserveOversampling).
OVERSAMPLING = ("center", "edge", "preserve")

# The versions that the package reads (Q1 of docs/plans/parser-redesign.md): 1.4.0 to 1.5.x, as
# major*1000000 + minor*1000 + revision.
_SUPPORTED = range(1_004_000, 1_006_000)

# The default of `load`'s `max_shape_samples`: the most samples of each array that the reader
# makes from a shape, 2^27, 1 GiB of float64. It is `DEFAULT_MAX_SHAPE_SAMPLES` of
# `pulseq_analysis.seqfile.interpreters`, the default of the setting of every interpreter of
# pulseq-analysis, which this module does not import (the tests of the interpreter check that the
# two are equal).
_DEFAULT_MAX_SHAPE_SAMPLES = 2**27

# The first 8 bytes of a binary Pulseq file, which `ExternalSequence::load(path)` reads with
# `loadBinary` (out of the package's scope).
_BINARY_MAGIC = b"\x01pulseq\x02"


class Rejected(Exception):
    """The C++ reader rejects the file: `load` or a `decodeBlock` returns false, or the reader
    throws. `messages` is what the reader printed, with each byte that is not UTF-8 as `\\xNN`."""

    def __init__(self, message: str, messages: str = ""):
        super().__init__(message)
        self.messages = messages


class UndefinedBehaviour(Rejected):
    """The C++ reader would have undefined behaviour on the file, or would not end, so no block
    of it is decoded. `cases` has every case that the checks find, in play order, each with its
    `code` (a key of `CODES`), its `entry` (the ID of its condition, section 2.2 of
    docs/specification.md) and its `message`. `code`, `entry`, `block` and `time_us` are those of
    the first case."""

    def __init__(self, cases: tuple[_checks.Case, ...]):
        case = cases[0]
        more = f" and {len(cases) - 1} more (see the `cases` attribute)" if len(cases) > 1 else ""
        super().__init__(f"{case}{more}")
        self.cases = tuple(cases)
        self.code = case.code
        self.entry = case.entry
        # For a case that only gradientsAt meets (ub.gradient-one-point): a block and a time (us)
        # where the reader has it; otherwise None.
        self.block = case.block
        self.time_us = case.time_us


class NotSupported(NotImplementedError):
    """The file is outside what the package reads. A version outside 1.4.0-1.5.x, a binary Pulseq
    file, or a folder of three files (Q1 of docs/plans/parser-redesign.md): the reader is not
    run. A shape that declares more samples than `load`'s `max_shape_samples`:
    `ExternalSequence::load` ran, and no shape is decompressed and no block decoded. An RF pulse
    that `decodeBlock` would resample into more cells than `max_shape_samples`: no block is
    decoded. A larger `max_shape_samples` reads such a file. The exception says nothing about
    whether the file is valid."""


class Shape(NamedTuple):
    """A shape as `load` stores it: `num_samples` as the file gives it, whether the reader keeps
    it compressed, and its stored values (float32), before decompression."""

    num_samples: int
    compressed: bool
    samples: np.ndarray


@dataclass(frozen=True, eq=False)
class Libraries:
    """What `ExternalSequence::load` read from the file, as the reader holds it (its private
    members): the reader's own reading, misreadings included. Event IDs are those of the file.

    Each event is a dict with the fields of the reader's struct; the keys are those of the
    decoded blocks (`Sequence.decode_block`). Floats are the float32 values that the reader
    holds, as Python floats; text is bytes, as in the file."""

    version: int  # major*1000000 + minor*1000 + revision, as the reader computes it
    version_parts: tuple[int, int, int]
    adc_raster_us: float
    gradient_raster_us: float
    rf_raster_us: float
    block_raster_us: float
    definitions: dict[bytes, bytes]  # each key of [DEFINITIONS] to the rest of its line
    definition_values: dict[bytes, np.ndarray]  # the same, as the doubles that the reader parsed
    blocks: np.ndarray  # int64 (number of blocks, 7): BLOCK_COLUMNS
    shapes: dict[int, Shape]
    rf: dict[int, dict]
    grad: dict[int, dict]  # [GRADIENTS] and [TRAP]: wave_shape 0 is a trapezoid
    adc: dict[int, dict]
    extension_list: dict[int, tuple[int, int, int]]  # each entry: (type, ref, next)
    extension_types: dict[int, tuple[bytes, int]]  # each type ID: (its name, the reader's ExtType)
    triggers: dict[int, dict]
    rotations: dict[int, tuple[float, float, float, float]]
    labelset: dict[int, dict]
    labelinc: dict[int, dict]
    soft_delays: dict[int, dict]
    rf_shims: dict[int, dict]
    signature: dict  # defined, type, value, calculated (the reader's MD5), ok

    @classmethod
    def _from_reader(cls, raw: dict) -> Libraries:
        raw = dict(raw)
        raw["version_parts"] = tuple(raw["version_parts"])
        raw["shapes"] = {key: Shape(*value) for key, value in raw["shapes"].items()}
        raw["extension_list"] = {key: tuple(value) for key, value in raw["extension_list"].items()}
        raw["extension_types"] = {
            key: tuple(value) for key, value in raw["extension_types"].items()
        }
        return cls(**raw)


class SoftDelays(NamedTuple):
    """The soft delay of each block, as `GetBlock` attaches it (`Sequence.block_soft_delays`):
    one entry for each block with a soft delay, in play order."""

    blocks: np.ndarray  # int64: the play index of the block, from 0
    num: np.ndarray  # int64: the numeric ID
    offset_us: np.ndarray  # int64: the offset in us, an int as load reads it (cpp:1330)
    factor: np.ndarray  # float64: the factor, a float32 of the reader
    hint: tuple[bytes, ...]  # the hint, the bytes up to the first zero, at most 31


def rotate_vec3_by_quat(quaternions, vectors) -> np.ndarray:
    """Each vector of `vectors` (n, 3) turned by the quaternion of the same row of `quaternions`
    (n, 4: q0, qx, qy, qz) with the reader's own `rotate_vec3_by_quat` (cpp:2666-2684) and the
    sign +1, the active rotation: the arithmetic of `Sequence.gradients_at(..., rotated=True)`.
    The reader uses it only on its position offsets; this package uses it for the simulation of
    the scanner."""
    q = np.ascontiguousarray(quaternions, dtype=np.float64).reshape(-1, 4)
    v = np.ascontiguousarray(vectors, dtype=np.float64).reshape(-1, 3)
    if q.shape[0] != v.shape[0]:
        raise ValueError("quaternions and vectors differ in length")
    return _reader.rotate_vec3_by_quat(q, v)


class Sequence:
    """A file that `load` read and checked. Blocks are decoded on request; each decoded block is
    kept for `gradients_at`. `oversampling` is the reader's sampling mode of an oversampled
    arbitrary gradient (one of `OVERSAMPLING`), which `load` sets before any block is decoded.
    `max_shape_samples` is the limit of the samples of a shape of that `load` (an int, or None).

    A `Sequence` can be pickled and copied. A pickle carries the bytes of the file, the mode and
    the limit, and loading it reads and checks the file again under that limit. `copy.copy` and
    `copy.deepcopy` return the same object: nothing that a caller can reach changes after `load`
    (the decoded blocks are a cache)."""

    def __init__(
        self,
        reader: _reader.Reader,
        libraries: Libraries,
        messages: str,
        data: bytes,
        oversampling: str,
        max_shape_samples: int | None,
        hidden_one_point: dict[int, list[tuple[float, float]]],
    ):
        self._reader = reader
        self._data = data
        self.libraries = libraries
        self.messages = messages  # what the reader printed while it loaded the file
        self.oversampling = oversampling
        self.max_shape_samples = max_shape_samples
        # The reader's messages for the block that `first_rejected_block` last found rejected:
        # with several threads, those of the last call of it to return.
        self.rejection_messages = ""
        self._block_rotations: tuple[np.ndarray, np.ndarray] | None = None
        self._block_soft_delays: SoftDelays | None = None
        self._block_label_sets: tuple[np.ndarray, tuple[str, ...], np.ndarray] | None = None
        # The reads past the times of an extended trapezoid of one point that the stored duration
        # of a block hides (`_checks.Checked`): gradients_at refuses the times of a soft delay
        # that reaches them. Not changed after `load`.
        self._hidden_one_point = hidden_one_point

    def __reduce__(self):
        return _load_again, (self._data, self.oversampling, self.max_shape_samples)

    def __copy__(self) -> Sequence:
        return self

    def __deepcopy__(self, memo) -> Sequence:
        return self

    @property
    def version(self) -> int:
        return self.libraries.version

    @property
    def block_count(self) -> int:
        return len(self.libraries.blocks)

    @property
    def signature_ok(self) -> bool:
        """`ExternalSequence::isSignatureCheckSucceeded`: an MD5 signature that matches."""
        return bool(self.libraries.signature["ok"])

    def decode_block(self, index: int) -> dict:
        """`GetBlock` and `decodeBlock` of the block `index` (play order from 0), with the fields
        of the driver's `--dump` (tests/cpp_oracle/README.md of pulseq-analysis): float32 arrays
        for the RF and gradient samples (after the resampling, `checkRF` and `checkGradient`),
        int64 arrays for the times. Raises `Rejected` when `decodeBlock` returns false."""
        block, messages = self._reader.decode_block(int(index))
        if block is None:
            raise Rejected(f"decodeBlock rejects block {index}", _messages(messages))
        return block

    def decode(self) -> list[dict]:
        """`decode_block` of each block in play order, as the driver's `--dump`. Raises `Rejected`
        at the first block that `decodeBlock` rejects: the C++ reader then rejects the file."""
        return [self.decode_block(index) for index in range(self.block_count)]

    def first_rejected_block(self) -> int | None:
        """The index (play order from 0) of the first block that `decodeBlock` rejects, or None:
        the verdict of the driver's first mode. It decodes every block in play order, also after
        one that is rejected, and keeps none (it frees each block), so a file of many blocks
        needs the memory of one. `rejection_messages` has what the reader printed for the block
        that it returns (and is empty for None). It is set from the result of the call, so it
        always holds the messages of one whole call; with several threads that call
        `first_rejected_block` on one `Sequence`, it holds those of the last call to return."""
        index, messages = self._reader.first_rejected_block()
        self.rejection_messages = _messages(messages)
        return None if index < 0 else index

    def block_rotations(self) -> tuple[np.ndarray, np.ndarray]:
        """The rotation of each block as `GetBlock` attaches it (the first rotation of the block's
        extension list, cpp:1871-1879): the play indices (int64, from 0) of the blocks for which
        `SeqBlock::isRotation` is true, in play order, and their quaternions (float64, (n, 4):
        q0, qx, qy, qz), as `load` divided them by their norm (cpp:1291-1292). The reader applies
        none of them to its gradients. No block is decoded; the result is kept."""
        if self._block_rotations is None:
            indices, quaternions = self._reader.block_rotations()
            self._block_rotations = (np.asarray(indices), np.asarray(quaternions))
        indices, quaternions = self._block_rotations
        return indices.copy(), quaternions.copy()

    def block_soft_delays(self) -> SoftDelays:
        """The soft delay of each block as `GetBlock` attaches it (the first soft delay of the
        block's extension list, cpp:1900-1907), for each block for which `SeqBlock::isSoftDelay`
        is true, as `load` read it. No block is decoded; the result is kept."""
        if self._block_soft_delays is None:
            blocks, num, offset, factor, hint = self._reader.block_soft_delays()
            self._block_soft_delays = SoftDelays(
                np.asarray(blocks), np.asarray(num), np.asarray(offset), np.asarray(factor),
                tuple(hint),
            )  # fmt: skip
        return self._block_soft_delays

    def block_label_sets(self) -> tuple[np.ndarray, tuple[str, ...], np.ndarray]:
        """The LABELSET events of each block as `GetBlock` attaches them (the labels that
        `decodeLabel` knows, in the order of each block's list): the play index of the block
        (int64), the name and the value (int64; a flag is 0 or 1) of each, in play order. No block
        is decoded; the result is kept."""
        if self._block_label_sets is None:
            blocks, names, values = self._reader.block_label_sets()
            self._block_label_sets = (np.asarray(blocks), tuple(names), np.asarray(values))
        blocks, names, values = self._block_label_sets
        return blocks.copy(), names, values.copy()

    def block_durations_ru(self, actual_ru) -> np.ndarray:
        """`SeqBlock::GetDuration_ru` of each block (int64, in units of BlockDurationRaster)
        after the reader's hook `SeqBlock::setActualSoftDelay_ru` with the value of `actual_ru`
        for that block (one int for each block; below 0 sets nothing, and the block keeps its
        stored duration, `GetStoredDuration_ru`). No block is decoded."""
        actual = np.ascontiguousarray(actual_ru, dtype=np.int64).reshape(-1)
        if actual.size != self.block_count:
            raise ValueError("actual_ru has one value for each block")
        return self._reader.block_durations_ru(actual)

    def gradients_at(
        self, block_index, time_us, rotated: bool = False, actual_ru=None
    ) -> np.ndarray:
        """`SeqBlock::gradientsAt` (Hz/m) at each pair of a block index (play order from 0) and a
        time in us from the start of that block, as an array (n, 3): gx, gy, gz. A block that is
        not decoded yet is decoded first (`Rejected` if it does not decode). A NaN time raises
        ValueError: the reader converts it to an int, which is undefined behaviour.

        With `rotated`, the values of a block that has a rotation (`block_rotations`) are turned
        by its quaternion with the reader's own `rotate_vec3_by_quat` (cpp:2666-2684, the active
        rotation): the gradients that the scanner plays if it applies the rotation. The reader
        never does this; it is a simulation, with the reader's arithmetic.

        `actual_ru` None leaves each block at its stored duration. Otherwise it has one int for
        each block: the actual soft delay that the reader's hook `setActualSoftDelay_ru` sets on
        the block for the call (below 0 for none), so that `gradientsAt` is 0 after
        `GetDuration`. A soft delay longer than the stored duration can reach a read past the
        times of an extended trapezoid of one point that `load` let through because it starts
        after the stored duration (D5.10): a pair of a block and a time where the reader would
        meet it raises `UndefinedBehaviour` (`ub.gradient-one-point`, with that block and
        time) before the reader runs. The other pairs, also those of the same block, give the
        reader's values."""
        block_index = np.ascontiguousarray(block_index, dtype=np.int64).reshape(-1)
        time_us = np.ascontiguousarray(time_us, dtype=np.float64).reshape(-1)
        if block_index.shape != time_us.shape:
            raise ValueError("block_index and time_us differ in length")
        if np.isnan(time_us).any():
            raise ValueError("a time is NaN")
        if block_index.size and (block_index.min() < 0 or block_index.max() >= self.block_count):
            raise IndexError("a block index is not a block of the sequence")
        if actual_ru is None:
            actual = np.zeros(0, dtype=np.int64)
        else:
            actual = np.ascontiguousarray(actual_ru, dtype=np.int64).reshape(-1)
            if actual.size != self.block_count:
                raise ValueError("actual_ru has one value for each block")
            self._refuse_hidden_one_point(block_index, time_us, actual)
        failed, messages = self._reader.ensure_decoded(np.unique(block_index))
        if failed >= 0:
            raise Rejected(f"decodeBlock rejects block {failed}", _messages(messages))
        return self._reader.gradients_at(block_index, time_us, bool(rotated), actual)

    def _refuse_hidden_one_point(
        self, block_index: np.ndarray, time_us: np.ndarray, actual: np.ndarray
    ) -> None:
        """`UndefinedBehaviour` at the first pair (in the order of the call) whose block has a
        read that its stored duration hides (`_hidden_one_point`) and a soft delay (`actual` of
        0 or more), and whose time is in an interval of that read and not after `GetDuration`,
        the soft delay times the block raster (gradientsAt gives 0 after it, cpp:3561)."""
        if not self._hidden_one_point:
            return
        hidden = np.fromiter(self._hidden_one_point, dtype=np.int64)
        hidden = hidden[actual[hidden] >= 0]
        positions = np.flatnonzero(np.isin(block_index, hidden))
        if not positions.size:
            return
        blocks, times = block_index[positions], time_us[positions]
        # GetDuration() in double: the long soft delay times s_blockDurationRaster (h:705).
        reached = times <= actual[blocks].astype(np.float64) * self.libraries.block_raster_us
        inside = np.zeros(positions.size, dtype=bool)
        for block in np.unique(blocks):
            of_block = blocks == block
            for start, end in self._hidden_one_point[int(block)]:
                inside |= of_block & (start <= times) & (times < end)
        refused = np.flatnonzero(inside & reached)
        if refused.size:
            position = positions[refused[0]]
            block, time = int(block_index[position]), float(time_us[position])
            case = _checks._case(
                "ub.gradient-one-point",
                f"block {block}: with a soft delay of {int(actual[block])} block rasters, "
                f"gradientsAt at {time} us reads past the times of an extended trapezoid of "
                "one point (cpp:3639-3650), a read that starts after the stored duration of the block",
                block,
                time,
            )
            raise UndefinedBehaviour((case,))


def _messages(messages: bytes) -> str:
    """What the reader printed in one call, as the call returns it. It quotes lines of the file,
    which can have bytes that are not UTF-8: each such byte is `\\xNN`, so that the text can be
    printed and written as UTF-8."""
    return messages.decode("utf-8", "backslashreplace")


def _max_shape_samples(value) -> int | None:
    """`value`, a `max_shape_samples` of `load`, as an int, or None. Raises `TypeError` when it
    is a bool or not an integer (a numpy int is one), and `ValueError` when it is not above 0."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"max_shape_samples is an int above 0 or None, not {value!r}")
    if value <= 0:
        raise ValueError(f"max_shape_samples is an int above 0 or None, not {value!r}")
    return int(value)


def _read_bytes(source: str | PathLike | bytes) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        data, name = source, "<bytes>"
    else:
        path = Path(source)
        if path.is_dir():
            raise NotSupported(f"{path} is a folder; the package reads one .seq file")
        data, name = path.read_bytes(), str(path)
    if data[:8] == _BINARY_MAGIC:
        raise NotSupported(f"{name} is a binary Pulseq file")
    return data, name


def load(
    source: str | PathLike | bytes,
    oversampling: str = "center",
    max_shape_samples: int | None = _DEFAULT_MAX_SHAPE_SAMPLES,
) -> Sequence:
    """Read the file `source` (a path, or the bytes of a file) with `ExternalSequence::load`,
    and check it. Decodes no block.

    `oversampling` is the reader's sampling mode of an oversampled arbitrary gradient (one of
    `OVERSAMPLING`; ValueError otherwise). It is set before any block is decoded and stays for
    the life of the `Sequence`. "center" is the reader's default.

    `max_shape_samples` is the most samples of each array that the reader makes from a shape:
    the samples that a shape declares, and the cells into which `decodeBlock` resamples an RF
    pulse on its time shape. It is 2^27 by default (the setting `max_shape_samples` of every
    interpreter of pulseq-analysis), or None for no limit. It is an int above 0: a numpy int is
    kept as an int, a bool or another type is a `TypeError`, and 0 or less a `ValueError`. After
    `ExternalSequence::load`, which stores each shape as the file stores it, `load` compares the
    number of samples of each shape of the reader's libraries, as the reader read it, with the
    limit, before any shape is decompressed. Then it compares the number of cells of each RF event
    that `decodeBlock` resamples (`int(0.5 + waveform_t.back())` of its time shape, cpp:2031) with
    the limit, before the checks and before any block is decoded. The scanner's reader has no
    limit: it is the package's, so that a short file cannot make the process allocate without
    bound (`decodeBlock` resizes a vector to each of these numbers). A number of cells above the
    range of an `int` (infinity too) is over any limit; with no limit, and for NaN or a number
    below the range, it is the case `ub.rf-time-range`.

    Raises `NotSupported` for a file outside the package's scope (the reader is not run), for
    the shape of the lowest ID that declares more samples than `max_shape_samples`, and then for
    the RF event of the lowest ID that `decodeBlock` resamples into more cells; `Rejected` when
    `load` rejects the file, and `UndefinedBehaviour` (a `Rejected`) for the cases of undefined
    behaviour of `GetBlock` or `decodeBlock` on any block, with every case."""
    if oversampling not in OVERSAMPLING:
        raise ValueError(f"oversampling is one of {OVERSAMPLING}, not {oversampling!r}")
    limit = _max_shape_samples(max_shape_samples)
    data, name = _read_bytes(source)
    reader = _reader.Reader(oversampling)
    # The version gate. For a file older than 1.4.0, load converts the blocks with GetBlock, before
    # any check could run (cpp:1656-1663), so the version is read first, with the reader's own
    # code, and the version as written decides (an int overflow in the reader's arithmetic
    # cannot bring it back in range).
    found, major, minor, revision = reader.read_version(data)
    version = major * 1_000_000 + minor * 1_000 + revision
    if found and version not in _SUPPORTED:
        raise NotSupported(
            f"{name}: version {major}.{minor}.{revision} is outside 1.4.0-1.5.x; the package "
            "does not read it"
        )
    ok, printed = reader.load(data)
    if not ok:
        raise Rejected(f"ExternalSequence::load rejects {name}", _messages(printed))
    messages = _messages(printed)
    libraries = Libraries._from_reader(reader.libraries())
    if not found or libraries.version != version:
        raise RuntimeError(
            f"{name}: the version gate read {found, major, minor, revision}, the reader "
            f"{libraries.version_parts}: the gate does not read the version as load does"
        )
    for shape_id, shape in libraries.shapes.items():  # by ID, as the reader keeps them
        if limit is not None and shape.num_samples > limit:
            raise NotSupported(
                f"{name}: shape {shape_id} declares {shape.num_samples} samples, more than the "
                f"limit of {limit} (the setting max_shape_samples), and the package does not "
                "decompress it. A larger max_shape_samples, or None for no limit, reads the file."
            )
    if limit is not None:
        shapes = _checks._Shapes(libraries.shapes)
        for rf_id, rf in libraries.rf.items():  # by ID, as the reader keeps them
            cells = _checks.rf_cells(shapes, rf)
            if cells is None:
                continue
            # int(cells) of the reader where it is finite; NaN is never over the limit, and stays
            # a case of the checks (ub.rf-time-range).
            n_cells = math.trunc(cells) if math.isfinite(cells) else cells
            if n_cells > limit:
                raise NotSupported(
                    f"{name}: RF event {rf_id} is resampled on its time shape {rf['time_shape']} "
                    f"into {n_cells} cells, more than the limit of {limit} (the setting "
                    "max_shape_samples), and the package does not decode it. A larger "
                    "max_shape_samples, or None for no limit, reads the file."
                )
    checked = _checks.undefined_behaviour(
        libraries, _checks.CHECKED_SIZEOF_LONG, reader.gradient_rows()
    )
    if checked.cases:
        raise UndefinedBehaviour(checked.cases)
    reader.mark_checked()
    return Sequence(
        reader, libraries, messages, data, oversampling, limit, checked.hidden_one_point
    )


def _load_again(data: bytes, oversampling: str, max_shape_samples: int | None) -> Sequence:
    """What unpickling a `Sequence` calls: `load` with the mode and the limit of the `Sequence`."""
    return load(data, oversampling=oversampling, max_shape_samples=max_shape_samples)
