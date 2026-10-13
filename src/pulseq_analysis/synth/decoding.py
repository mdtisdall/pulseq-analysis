"""The decoding of a file by its interpreter (stage 2 of section 7.2 of
`docs/plans/parser-redesign.md`): `decode(data)` picks the decoder from `data.interpreter`.

- `cpp-siemens`: the C++ reader's own decoding, `CppSiemensDecoding`: `GetBlock` and
  `decodeBlock` of each block (`block`, `blocks`), and `SeqBlock::gradientsAt`
  (`gradients_at`). These are the values that the reader gives, bit for bit: its float32
  values, the resampling of RF pulses, the clamps of `checkRF` and `checkGradient`, the sampling
  mode of an oversampled gradient (the setting `oversampling` of the interpreter), and its
  misreadings.
- `strict`: the package's decoding of the events (`events`), `StrictDecoding`: each event of the
  model by its ID.

The two kinds differ: the C++ reader decodes a block at a time, and an event can decode
differently in two blocks (an extended trapezoid reuses the buffer of the block's shapes). Task
R14 builds the measurements (`load`) on these decodings.
"""

import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any

import numpy as np

from ..seqfile.interpreters import CppSiemens, Strict
from ..seqfile.model import SequenceData
from . import events

__all__ = ["CppSiemensDecoding", "StrictDecoding", "decode"]


@dataclasses.dataclass(frozen=True, slots=True)
class StrictDecoding:
    """The events of a file that the `strict` interpreter read (`events`), by file ID."""

    interpreter: Strict
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

    def gradients_at(self, block_index: Any, time_us: Any) -> np.ndarray:
        """`SeqBlock::gradientsAt` (Hz/m) at each pair of a block index and a time in us from the
        start of that block: an array (n, 3) of gx, gy and gz, as the reader gives them (0
        before and after the block)."""
        return self._reading.gradients_at(block_index, time_us)


def decode(data: SequenceData) -> StrictDecoding | CppSiemensDecoding:
    """The decoding of `data` by its interpreter (the module docstring)."""
    if isinstance(data.interpreter, CppSiemens):
        return CppSiemensDecoding(data)
    return StrictDecoding(
        interpreter=data.interpreter,
        rf=events.decode_rf(data),
        gradients=events.decode_gradients(data),
        adc=events.decode_adc(data),
    )
