"""The snapshot: one file as an interpreter read and decoded it, and the results kept for it.

A `Snapshot` holds the `seqfile.SequenceData` of one interpreter (`data`) and its decoding under
a scanner session (`decoding.decode(data, session)`: the package's decoder for `spec`, the
plugin's decoding for a plugin interpreter).
Both are immutable, so a measurement describes one fixed sequence, and its result can be kept
for later calls. `analyses.load` makes a snapshot of a file, of a pypulseq sequence or of a
`SequenceData`, one time, and each measurement takes the snapshot. `load` is the one way to make
a snapshot (Q22 of `docs/plans/remaining-review-fixes.md`): `Snapshot` is the type, and
`Snapshot(...)` raises `TypeError` that names `load`. The measurements take the gradients only
through the decoding: its decoded events, and `gradients_at` for a block whose gradients the
decoding rotates (`_played`).

The results that the measurements make from a snapshot (`seq_index.sequence_index`, the played
gradients of `_played`, `_events.event_points`, the gaps of `sampling` and the results of
`grad_peaks`, `pns_levels` and `grad_spectrum`) are kept in a private dict of the snapshot, and
made on their first use. The data of a snapshot does not change, so a kept result is never old.

Private interface for the modules of the package:

- `_snapshot(data, source, session)` makes the snapshot of `data`, decoded under `session`, for
  `analyses.load` and the copies of a snapshot. It emits no warning.
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
from .scanner import FovRecord, RotationRecord, Session, SoftDelayRecord

__all__ = ["Snapshot"]


class Snapshot:
    """One file as an interpreter read and decoded it, made by `analyses.load`.

    - `data`: the `SequenceData` of the interpreter; `interpreter` and `records` are its fields.
    - `session`: the scanner session (`scanner.Session`, the neutral one by default).
    - `decoding`: `decoding.decode(data, session)`.
    - `rotation_record`, `soft_delay_record` and `fov_record`: what the decoding does with the
      rotations of the file, and with the session's soft delays and field of view (the
      decoding's records, rule 4 of section 7.8 of `docs/plans/parser-redesign.md`).
    - `source`: the path that `load` read, or `None` for a pypulseq sequence and a
      `SequenceData`.

    Two snapshots are equal only when they are the same object, and the hash is the identity
    hash of `object`, so a snapshot can be the key of a dict. A copy from `pickle` or
    `copy.deepcopy` is a new snapshot of the same data, with no kept results: it makes them
    again.

    Make a snapshot with `analyses.load`, also of a `SequenceData`. `Snapshot(...)` raises
    `TypeError` that names `load`: the class is the type of a snapshot, not a way to make one.
    """

    __slots__ = ("__weakref__", "_data", "_decoding", "_kept", "_session", "_source")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(
            "a Snapshot is made by pulseq_analysis.analyses.load(source), of a path, a pypulseq "
            "Sequence or a seqfile.SequenceData, not by Snapshot(...)"
        )

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
    def session(self) -> Session:
        """The scanner session of the decoding."""
        return self._session

    @property
    def soft_delay_record(self) -> SoftDelayRecord:
        """What the decoding does with the session's soft delays (`decoding.soft_delay_record`)."""
        return self._decoding.soft_delay_record

    @property
    def fov_record(self) -> FovRecord:
        """What the decoding does with the session's field of view (`decoding.fov_record`)."""
        return self._decoding.fov_record

    @property
    def source(self) -> str | None:
        """The path that `load` read (a `str`, as `os.fspath` gives it), or `None` when the
        snapshot is of a pypulseq sequence or of a `SequenceData`."""
        return self._source

    def __reduce__(self) -> tuple[Any, ...]:
        return (_snapshot, (self._data, self._source, self._session))

    def __deepcopy__(self, memo: dict[int, Any]) -> "Snapshot":
        return _snapshot(self._data, self._source, self._session)


def _snapshot(data: SequenceData, source: str | None, session: Session | None) -> Snapshot:
    """The snapshot of `data` with `source`, decoded under `session` (`decoding.decode`), with no
    kept results: the one maker of a `Snapshot`, for `analyses.load` and the copies. It emits no
    warning (`load` emits the `ScannerSettingWarning` of the decoding)."""
    snap = object.__new__(Snapshot)
    snap._data = data
    snap._decoding = decode(data, session)
    snap._session = snap._decoding.session
    snap._source = source
    # The kept results of the measurements: `_kept_results`.
    snap._kept = {}
    return snap


def _check_snapshot(snap: object) -> None:
    """Raise `TypeError` that names `load` when `snap` is not a `Snapshot`. The public
    functions of the package take a snapshot, not a sequence or a path."""
    if not isinstance(snap, Snapshot):
        raise TypeError(
            f"expected a pulseq_analysis.synth.snapshot.Snapshot, not {type(snap)!r}: make one "
            "with pulseq_analysis.analyses.load(path, sequence or SequenceData)"
        )


def _kept_results(snap: Snapshot) -> dict[Any, Any]:
    """The dict of the kept results of `snap` (the module docstring gives the rule of the
    keys). `snap` must be a `Snapshot`: the caller has called `_check_snapshot`."""
    return snap._kept
