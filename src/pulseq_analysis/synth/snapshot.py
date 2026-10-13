"""The snapshot: one file as an interpreter read and decoded it, and the results kept for it.

A `Snapshot` holds the `seqfile.SequenceData` of one interpreter (`data`) and its decoding
(`decoding.decode(data)`: the package's decoder for `spec`, the plugin's decoding for a plugin
interpreter).
Both are immutable, so a measurement describes one fixed sequence, and its result can be kept
for later calls. `analyses.load` makes a snapshot of a file or of a pypulseq sequence, one time,
and each measurement takes the snapshot. The measurements take the gradients only through the
decoding: its decoded events, and `gradients_at` for a block whose gradients the decoding rotates
(`_played`).

The results that the measurements make from a snapshot (`seq_index.sequence_index`, the played
gradients of `_played`, `_events.event_points`, the gaps of `sampling` and the results of
`grad_peaks`, `pns_levels` and `grad_spectrum`) are kept in a private dict of the snapshot, and
made on their first use. The data of a snapshot does not change, so a kept result is never old.

Private interface for the modules of the package:

- `_check_snapshot(snap)` raises `TypeError` that names `load` when `snap` is not a
  `Snapshot`. A public function calls it for its first argument, after the checks of its
  other arguments.
- `_kept_results(snap)` is the dict of the kept results of `snap`. A module reads and sets
  the keys of its own results, as `kept = _kept_results(snap)`, `if key not in kept:
  kept[key] = ...`. A key is a `str` for a result with no argument, and a tuple whose first
  item is a `str` that names the result for a result that depends on arguments. No two
  modules use one key.
"""

from typing import Any

from ..seqfile.interpreters import Interpreter
from ..seqfile.model import Record, SequenceData
from .decoding import Decoding, decode
from .scanner import RotationRecord

__all__ = ["Snapshot"]


class Snapshot:
    """One file as an interpreter read and decoded it, made by `analyses.load`.

    - `data`: the `SequenceData` of the interpreter; `interpreter` and `records` are its fields.
    - `decoding`: `decoding.decode(data)`.
    - `rotation_record`: what the decoding does with the rotations of the file
      (`decoding.rotation_record`, rule 4 of section 7.8 of `docs/plans/parser-redesign.md`).
    - `source`: the path that `load` read, or `None` for a pypulseq sequence.

    Two snapshots are equal only when they are the same object, and the hash is the identity
    hash of `object`, so a snapshot can be the key of a dict. A copy from `pickle` or
    `copy.deepcopy` is a new snapshot of the same data, with no kept results: it makes them
    again.

    Make a snapshot with `analyses.load`. `Snapshot(data, source)` decodes `data`, and does not
    emit the `ScannerSettingWarning` that `load` emits.
    """

    __slots__ = ("__weakref__", "_data", "_decoding", "_kept", "_source")

    def __init__(self, data: SequenceData, source: str | None = None) -> None:
        if not isinstance(data, SequenceData):
            raise TypeError(f"a Snapshot holds a SequenceData, not {type(data)!r}")
        self._data = data
        self._decoding = decode(data)
        self._source = source
        # The kept results of the measurements: `_kept_results`.
        self._kept: dict[Any, Any] = {}

    @property
    def data(self) -> SequenceData:
        """The `SequenceData` that the interpreter read."""
        return self._data

    @property
    def decoding(self) -> Decoding:
        """The decoding of `data` by its interpreter (`decoding.decode`)."""
        return self._decoding

    @property
    def interpreter(self) -> Interpreter:
        """The interpreter that read the file, with its settings (`data.interpreter`)."""
        return self._data.interpreter

    @property
    def records(self) -> tuple[Record, ...]:
        """What the interpreter recorded of the file (`data.records`, rule 4 of P20)."""
        return self._data.records

    @property
    def rotation_record(self) -> RotationRecord:
        """What the decoding does with the rotations of the file (`decoding.rotation_record`)."""
        return self._decoding.rotation_record

    @property
    def source(self) -> str | None:
        """The path that `load` read (a `str`, as `os.fspath` gives it), or `None` when the
        snapshot is of a pypulseq sequence."""
        return self._source

    def __reduce__(self) -> tuple[Any, ...]:
        return (Snapshot, (self._data, self._source))

    def __deepcopy__(self, memo: dict[int, Any]) -> "Snapshot":
        return Snapshot(self._data, self._source)


def _check_snapshot(snap: object) -> None:
    """Raise `TypeError` that names `load` when `snap` is not a `Snapshot`. The public
    functions of the package take a snapshot, not a sequence or a path."""
    if not isinstance(snap, Snapshot):
        raise TypeError(
            f"expected a pulseq_analysis.synth.snapshot.Snapshot, not {type(snap)!r}: make one "
            "with pulseq_analysis.analyses.load(path or sequence)"
        )


def _kept_results(snap: Snapshot) -> dict[Any, Any]:
    """The dict of the kept results of `snap` (the module docstring gives the rule of the
    keys). `snap` must be a `Snapshot`: the caller has called `_check_snapshot`."""
    return snap._kept
