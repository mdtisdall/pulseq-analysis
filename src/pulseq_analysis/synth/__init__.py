"""The waveforms layer: the decoding of a file by its interpreter (`decode`), the snapshot, the
events and the waveform of each block, the block index and the sampling. It imports from the
files layer and the base modules, not from the analyses.

`decode(data)` decodes a `seqfile.SequenceData` by its interpreter: for `cpp-siemens` the C++
reader's own decoding and `gradientsAt`, for `strict` the events of `events`."""

from .decoding import CppSiemensDecoding, StrictDecoding, decode

__all__ = ["CppSiemensDecoding", "StrictDecoding", "decode"]
