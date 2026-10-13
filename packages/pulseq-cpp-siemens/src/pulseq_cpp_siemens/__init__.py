"""The C++ reader of Pulseq files on Siemens scanners, in the process: `ExternalSequence` of
pulseq/pulseq at c7469123 (MIT; `LICENSE.pulseq` in this package's metadata), the reader of the
Pulseq interpreter on Siemens systems, compiled with a signed `char` and no fused multiply-add as
its x86_64 build.

    sequence = load("file.seq")       # ExternalSequence::load, then the checks
    sequence.libraries                # what load read: events, shapes, blocks, definitions
    sequence.decode_block(0)          # GetBlock and decodeBlock of one block
    sequence.decode()                 # every block, in play order
    sequence.gradients_at([0], [5.0]) # SeqBlock::gradientsAt (Hz/m)

`load` refuses a version outside 1.4.0-1.5.x before the reader reads the file (`NotSupported`),
and it rejects each case of undefined behaviour of the reader before any block is decoded
(`UndefinedBehaviour`, with its code), so that the process survives the file.

Calls are safe from several threads: the extension holds one lock for each call into the reader,
sets the reader's shared state for the sequence it works on, and reads numbers in the "C" locale.
"""

from __future__ import annotations

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
    "PULSEQ_COMMIT",
    "Libraries",
    "NotSupported",
    "Rejected",
    "Sequence",
    "Shape",
    "UndefinedBehaviour",
    "load",
]

PULSEQ_COMMIT: str = _reader.PULSEQ_COMMIT

# The columns of `Libraries.blocks`: the block duration in units of BlockDurationRaster, then
# the IDs of the events (0 for none), as the reader holds them.
BLOCK_COLUMNS = ("duration_ru", "rf", "gx", "gy", "gz", "adc", "ext")

# The versions that the package reads (Q1 of docs/plans/parser-redesign.md): 1.4.0 to 1.5.x, as
# major*1000000 + minor*1000 + revision.
_SUPPORTED = range(1_004_000, 1_006_000)

# The first 8 bytes of a binary Pulseq file, which `ExternalSequence::load(path)` reads with
# `loadBinary` (out of the package's scope).
_BINARY_MAGIC = b"\x01pulseq\x02"


class Rejected(Exception):
    """The C++ reader rejects the file: `load` or a `decodeBlock` returns false, or the reader
    throws. `messages` is what the reader printed."""

    def __init__(self, message: str, messages: str = ""):
        super().__init__(message)
        self.messages = messages


class UndefinedBehaviour(Rejected):
    """The C++ reader would have undefined behaviour on the file, or would not end, so no block
    of it is decoded. `code` names the case (a key of `CODES`); `entry` is its entry of
    docs/discrepancies.md of pulseq-analysis."""

    def __init__(self, case: _checks.Case):
        super().__init__(f"{case.code} ({case.entry}): {case.message}")
        self.code = case.code
        self.entry = case.entry
        # For a case that only gradientsAt meets (ub.gradient-one-point): a block and a time (us)
        # where the reader has it; otherwise None.
        self.block = case.block
        self.time_us = case.time_us


class NotSupported(NotImplementedError):
    """The file is outside what the package reads (Q1 of docs/plans/parser-redesign.md): a
    version outside 1.4.0-1.5.x, a binary Pulseq file, or a folder of three files. The reader is
    not run, and the exception says nothing about whether the file is valid."""


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


class Sequence:
    """A file that `load` read and checked. Blocks are decoded on request; each decoded block is
    kept for `gradients_at`."""

    def __init__(self, reader: _reader.Reader, libraries: Libraries, messages: str):
        self._reader = reader
        self.libraries = libraries
        self.messages = messages  # what the reader printed while it loaded the file

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
        block = self._reader.decode_block(int(index))
        if block is None:
            raise Rejected(f"decodeBlock rejects block {index}", self._reader.messages)
        return block

    def decode(self) -> list[dict]:
        """`decode_block` of each block in play order, as the driver's `--dump`. Raises `Rejected`
        at the first block that `decodeBlock` rejects: the C++ reader then rejects the file."""
        return [self.decode_block(index) for index in range(self.block_count)]

    def gradients_at(self, block_index, time_us) -> np.ndarray:
        """`SeqBlock::gradientsAt` (Hz/m) at each pair of a block index (play order from 0) and a
        time in us from the start of that block, as an array (n, 3): gx, gy, gz. A block that is
        not decoded yet is decoded first (`Rejected` if it does not decode). A NaN time raises
        ValueError: the reader converts it to an int, which is undefined behaviour."""
        block_index = np.ascontiguousarray(block_index, dtype=np.int64).reshape(-1)
        time_us = np.ascontiguousarray(time_us, dtype=np.float64).reshape(-1)
        if block_index.shape != time_us.shape:
            raise ValueError("block_index and time_us differ in length")
        if np.isnan(time_us).any():
            raise ValueError("a time is NaN")
        if block_index.size and (block_index.min() < 0 or block_index.max() >= self.block_count):
            raise IndexError("a block index is not a block of the sequence")
        failed = self._reader.ensure_decoded(np.unique(block_index))
        if failed >= 0:
            raise Rejected(f"decodeBlock rejects block {failed}", self._reader.messages)
        return self._reader.gradients_at(block_index, time_us)


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


def load(source: str | PathLike | bytes) -> Sequence:
    """Read the file `source` (a path, or the bytes of a file) with `ExternalSequence::load`,
    and check it. Decodes no block.

    Raises `NotSupported` for a file outside the package's scope (the reader is not run),
    `Rejected` when `load` rejects the file, and `UndefinedBehaviour` (a `Rejected`) for a case
    of undefined behaviour of `GetBlock` or `decodeBlock` on any block."""
    data, name = _read_bytes(source)
    reader = _reader.Reader()
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
    if not reader.load(data):
        raise Rejected(f"ExternalSequence::load rejects {name}", reader.messages)
    messages = reader.messages
    libraries = Libraries._from_reader(reader.libraries())
    if not found or libraries.version != version:
        raise RuntimeError(
            f"{name}: the version gate read {found, major, minor, revision}, the reader "
            f"{libraries.version_parts}: the gate does not read the version as load does"
        )
    case = _checks.undefined_behaviour(libraries, _reader.SIZEOF_LONG, reader.gradient_rows())
    if case is not None:
        raise UndefinedBehaviour(case)
    reader.mark_checked()
    return Sequence(reader, libraries, messages)
