"""The waveforms layer: the decoding of a file by its interpreter (`decode`), the snapshot, the
events and the waveform of each block, the block index and the sampling. It imports from the
files layer and the base modules, not from the analyses.

`decode(data)` decodes a `seqfile.SequenceData` by its interpreter: for `cpp-siemens` the C++
reader's own decoding and `gradientsAt`, for `spec` the events of `events` and the gradients of each block, rotated from 1.5.1. `scanner` has what
a decoding records of the scanner-side settings (`RotationRecord`) and `ScannerSettingWarning`."""

from .decoding import CppSiemensDecoding, SpecDecoding, decode
from .scanner import RotationRecord, ScannerSettingWarning

__all__ = [
    "CppSiemensDecoding",
    "RotationRecord",
    "ScannerSettingWarning",
    "SpecDecoding",
    "decode",
]
