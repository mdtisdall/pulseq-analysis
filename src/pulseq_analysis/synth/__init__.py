"""The waveforms layer: the decoding of a file by its interpreter (`decode`), the snapshot, the
events and the waveform of each block, the block index and the sampling. It imports from the
files layer and the base modules, not from the analyses.

`decode(data)` decodes a `seqfile.SequenceData` by its interpreter (a `Decoding`): for `spec` the
events of `events` and the gradients of each block, rotated from 1.5.1; for a plugin
interpreter, the decoding that the plugin gives. `scanner` has what a decoding records of the
scanner-side settings (`RotationRecord`) and `ScannerSettingWarning`.
`snapshot.Snapshot` holds a `SequenceData` and its decoding for the measurements; the
measurements take the gradients from the decoding (`_played`). `analyses.load` makes a
snapshot."""

from .decoding import Decoding, SpecDecoding, decode
from .scanner import RotationRecord, ScannerSettingWarning
from .snapshot import Snapshot

__all__ = [
    "Decoding",
    "RotationRecord",
    "ScannerSettingWarning",
    "Snapshot",
    "SpecDecoding",
    "decode",
]
