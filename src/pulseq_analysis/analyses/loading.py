"""`load`: a file or a pypulseq sequence, read through one interpreter, or the `SequenceData` of
such a reading, as the snapshot that the measurements take (task R14 of
`docs/plans/parser-redesign.md`, P15). `load` is the one way to make a snapshot (the user,
2026-10-14): `Snapshot(data)` made one too, with no `ScannerSettingWarning`.

`load(path, interpreter="spec")` reads the file with `seqfile.read_seqfile`, and `load(seq,
interpreter="spec")` a `pypulseq.Sequence` in memory with `seqfile.read_pypulseq` (its text as
pypulseq's writer writes it). `load(data, interpreter)` takes a `seqfile.SequenceData` that
`interpreter` read, as it is. The `SequenceData` of the interpreter and its decoding are the
`synth.snapshot.Snapshot`, decoded under the scanner session `session` (`synth.Session`, the
neutral one by default; rule 3 of section 7.8 of the plan). The snapshot records the interpreter
with its settings (`Snapshot.interpreter`), the session (`Snapshot.session`), what the
interpreter recorded of the file (`Snapshot.records`), and what the decoding does with the
rotations of the file and the session's soft delays and field of view
(`Snapshot.rotation_record`, `soft_delay_record`, `fov_record`): rule 4 of section 7.8.

`load` emits a `synth.ScannerSettingWarning` where content of the file is left unapplied
(`RotationRecord.warning()`): today, a block that plays a rotation that a plugin interpreter
leaves unapplied, whose gradients are then the logical ones. The decoding does not emit it, so
that a reader of the decoding is not warned about the interpreter's own output. `load(data)` of a
`SequenceData` emits the warning of `load` of its file: the warning is of the decoding, which is
the same.
"""

import os
import warnings
from typing import Any

from ..seqfile import Interpreter, SequenceData, read_pypulseq, read_seqfile
from ..seqfile import interpreter as _interpreter
from ..synth.scanner import Session
from ..synth.snapshot import Snapshot, _snapshot

__all__ = ["load"]


def load(
    source: Any, interpreter: "str | Interpreter" = "spec", session: Session | None = None
) -> Snapshot:
    """The `Snapshot` of `source`, read through `interpreter` (a name of
    `seqfile.interpreter_names()`, or an interpreter object with its settings; the default is
    `spec`) and decoded under the scanner session `session` (`synth.Session`; None is the
    neutral session).

    - A path (`str` or `os.PathLike`) to a `.seq` file: `seqfile.read_seqfile(source,
      interpreter)`. `Snapshot.source` is the path, as `os.fspath` gives it.
    - A `pypulseq.Sequence`: `seqfile.read_pypulseq(source, interpreter)`, the text of
      `source.write(path)` read as a file; `source` is not changed, and a later change of it does
      not change the snapshot. `Snapshot.source` is `None`.
    - A `seqfile.SequenceData` (of `read_seqfile` or `read_pypulseq`): the data as it is, with
      no reading. `interpreter` must be the interpreter that read it
      (`seqfile.interpreter(interpreter) == source.interpreter`), so the data of a plugin is
      `load(data, data.interpreter)`. `Snapshot.source` is `None`. The snapshot has the
      decoding and the warning of `load` of the file or the sequence that was read.

    Then the snapshot decodes the data (`synth.decode(data, session)`). Nothing else is built:
    each result is made on its first use. Emits `synth.ScannerSettingWarning` when the decoding
    leaves a rotation of the file unapplied (the module docstring).

    Raises what the reading raises: `seqfile.SeqFileError` when the interpreter rejects the file,
    with its codes and reasons, and `seqfile.NotSupported` for a file outside the package's
    scope. Raises `synth.SettingError` (a ValueError) for a setting of the session that
    addresses something the file does not have under the interpreter. Raises ValueError for a
    `SequenceData` that another interpreter read, which names `data.interpreter`. Raises
    TypeError for a `source` that is not a path, a pypulseq sequence or a `SequenceData`, and
    for a `session` that is not a `synth.Session`."""
    if session is not None and not isinstance(session, Session):
        raise TypeError(f"session is a pulseq_analysis.synth.Session, not {type(session)!r}")
    if isinstance(source, SequenceData):
        path: str | None = None
        chosen = _interpreter(interpreter)
        if chosen != source.interpreter:
            raise ValueError(
                f"the data was read by {source.interpreter}, not by {chosen}: give load the "
                "interpreter that read it, load(data, data.interpreter)"
            )
        data = source
    elif isinstance(source, str | os.PathLike):
        path = os.fspath(source)
        data = read_seqfile(path, interpreter)
    elif callable(getattr(source, "write", None)) and callable(
        getattr(source, "remove_duplicates", None)
    ):
        path = None
        data = read_pypulseq(source, interpreter)
    else:
        raise TypeError(
            "load takes the path of a .seq file, a pypulseq Sequence or a seqfile.SequenceData, "
            f"not {type(source)!r}"
        )
    snap = _snapshot(data, path, session)
    warning = snap.rotation_record.warning()
    if warning is not None:
        warnings.warn(warning, stacklevel=2)
    return snap
