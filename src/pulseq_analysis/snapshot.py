"""The snapshot: a sequence that only this package holds, and the results kept for it.

pypulseq lets a caller change a `pp.Sequence` in place: `mod_grad_axis` and `flip_grad_axis`
rewrite the entries of `grad_library`, `set_block` on an existing block ID replaces its row of
`block_events`, `apply_soft_delay` writes into `block_durations`, and a caller can write into
the block table or a library directly. A measurement must describe one fixed sequence, and
its result is kept for later calls, so the measurements do not take a `pp.Sequence`. `load`
makes a `Snapshot` of a file or of a sequence, one time, and each measurement takes the
snapshot.

`load(path)` reads the file into a sequence that no other object holds, so it makes no copy.
`load(seq)` makes `copy.deepcopy(seq)`, which shares no mutable object with `seq` (the
guard tests of `tests/test_snapshot.py` walk both object graphs for this). `load` then
refuses a sequence with no `[SIGNATURE]` hash (`extensions.refuse_unsigned`) and a sequence
with a rotation (`extensions.refuse_rotations`), and turns pypulseq's block cache off for the
private sequence, so no measurement calls either check again and no block of the
snapshot is kept by pypulseq.

The results that the measurements make from a snapshot (`seq_index.sequence_index`, the
events, `_events.event_points`, the gaps of `sampling` and the results of `grad_peaks`,
`pns_levels` and `grad_spectrum`) are kept in a private dict of the snapshot, and made on
their first use. The sequence of a snapshot does not change, so a kept result is never old.
No rule of a stamp is needed.

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

import copy
import os
from typing import Any

import pypulseq as pp

from .extensions import refuse_rotations, refuse_unsigned


class Snapshot:
    """One sequence that only this package holds, made by `load`.

    `sequence` is the private `pp.Sequence`. A caller and an analysis must not change it, and
    must not change an object that they get from it (for example a block from `get_block`):
    the kept results are made from it, and a change would make them wrong. The measurements
    of the package take a snapshot as their first argument.

    `source` is the path that `load` read, or `None` for a sequence.

    Two snapshots are equal only when they are the same object, and the hash is the identity
    hash of `object`, so a snapshot can be the key of a dict. A copy from `pickle` or
    `copy.deepcopy` is a new snapshot with a copy of the sequence and no kept results: it
    makes them again.

    Make a snapshot with `load`. `Snapshot(sequence, source)` does not check the sequence.
    """

    __slots__ = ("__weakref__", "_kept", "_sequence", "_source")

    def __init__(self, sequence: pp.Sequence, source: str | None = None) -> None:
        self._sequence = sequence
        self._source = source
        # The kept results of the measurements: `_kept_results`.
        self._kept: dict[Any, Any] = {}

    @property
    def sequence(self) -> pp.Sequence:
        """The private `pp.Sequence`. It must not change."""
        return self._sequence

    @property
    def source(self) -> str | None:
        """The path that `load` read (a `str`, as `os.fspath` gives it), or `None` when the
        snapshot is of a `pp.Sequence`."""
        return self._source

    def __reduce__(self) -> tuple[Any, ...]:
        return (Snapshot, (self._sequence, self._source))


def load(source: str | os.PathLike | pp.Sequence) -> Snapshot:
    """The `Snapshot` of `source`, a path to a `.seq` file or a `pp.Sequence`.

    - A path (`str` or `os.PathLike`): the file is read into a new `pp.Sequence` that no other
      object holds. No copy is made.
    - A `pp.Sequence`: the snapshot holds `copy.deepcopy(source)`. `source` is not changed,
      and its block cache is not copied: it is set aside during the copy and put back after
      it, as pypulseq's `Sequence.remove_duplicates` does. A later change of `source` does not
      change the snapshot.

    Then the sequence is checked, and pypulseq's block cache is turned off for it
    (`use_block_cache` is False), so a call of `get_block` keeps no block. Nothing else is
    built: each result is made on its first use.

    Raises TypeError for another type of `source`; ValueError for a sequence with no
    `[SIGNATURE]` hash (`extensions.refuse_unsigned`; a sequence that was built in memory gets
    its hash from `seq.write(path)`); NotImplementedError for a sequence with the rotation
    extension (`extensions.refuse_rotations`). A file that pypulseq cannot read raises the
    error of `Sequence.read`.
    """
    if isinstance(source, pp.Sequence):
        # The block cache of `source` is not part of the copy, and pypulseq keeps in it every
        # block that `get_block` reads. `source` gets its cache back also after an error.
        cache = source.block_cache
        source.block_cache = {}
        try:
            seq = copy.deepcopy(source)
        finally:
            source.block_cache = cache
        path = None
    elif isinstance(source, str | os.PathLike):
        path = os.fspath(source)
        seq = pp.Sequence(use_block_cache=False)
        seq.read(path)
    else:
        raise TypeError(
            f"load takes the path of a .seq file or a pypulseq Sequence, not {type(source)!r}"
        )
    refuse_unsigned(seq)
    refuse_rotations(seq)
    seq.use_block_cache = False
    return Snapshot(seq, path)


def _check_snapshot(snap: object) -> None:
    """Raise `TypeError` that names `load` when `snap` is not a `Snapshot`. The public
    functions of the package take a snapshot, not a `pp.Sequence` or a path."""
    if not isinstance(snap, Snapshot):
        raise TypeError(
            f"expected a pulseq_analysis.snapshot.Snapshot, not {type(snap)!r}: make one with "
            "pulseq_analysis.snapshot.load(path or sequence)"
        )


def _kept_results(snap: Snapshot) -> dict[Any, Any]:
    """The dict of the kept results of `snap` (the module docstring gives the rule of the
    keys). `snap` must be a `Snapshot`: the caller has called `_check_snapshot`."""
    return snap._kept
