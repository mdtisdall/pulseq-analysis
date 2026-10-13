"""`load`: a file or a pypulseq sequence, read through one interpreter, as the snapshot that the
measurements take (task R14 of `docs/plans/parser-redesign.md`, P15).

`load(path, interpreter="spec")` reads the file with `seqfile.read_seqfile`, and `load(seq,
interpreter="spec")` a `pypulseq.Sequence` in memory with `seqfile.read_pypulseq` (its text as
pypulseq's writer writes it). The `SequenceData` of the interpreter and its decoding are the
`synth.snapshot.Snapshot`, decoded under the scanner session `session` (`synth.Session`, the
neutral one by default; rule 3 of section 7.8 of the plan). The snapshot records the interpreter
with its settings (`Snapshot.interpreter`), the session (`Snapshot.session`), what the
interpreter recorded of the file (`Snapshot.records`), and what the decoding does with the
rotations of the file and the session's soft delays and field of view
(`Snapshot.rotation_record`, `soft_delay_record`, `fov_record`): rule 4 of section 7.8.

`load` emits a `synth.ScannerSettingWarning` where content of the file is left unapplied
(`RotationRecord.warning()`): today, a block that plays a rotation that a plugin interpreter
leaves unapplied, whose gradients are then the logical ones. The decoding does not emit it, so
that a reader of the decoding is not warned about the interpreter's own output.
"""

import os
import warnings
from typing import Any

from ..seqfile import Interpreter, read_pypulseq, read_seqfile
from ..synth.scanner import Session
from ..synth.snapshot import Snapshot

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

    Then the snapshot decodes the data (`synth.decode(data, session)`). Nothing else is built:
    each result is made on its first use. Emits `synth.ScannerSettingWarning` when the decoding
    leaves a rotation of the file unapplied (the module docstring).

    Raises what the reading raises: `seqfile.SeqFileError` when the interpreter rejects the file,
    with its codes and reasons, and `seqfile.NotSupported` for a file outside the package's
    scope. Raises `synth.SettingError` (a ValueError) for a setting of the session that
    addresses something the file does not have under the interpreter. Raises TypeError for a
    `source` that is neither a path nor a pypulseq sequence, and for a `session` that is not a
    `synth.Session`."""
    if session is not None and not isinstance(session, Session):
        raise TypeError(f"session is a pulseq_analysis.synth.Session, not {type(session)!r}")
    if isinstance(source, str | os.PathLike):
        path: str | None = os.fspath(source)
        data = read_seqfile(path, interpreter)
    elif callable(getattr(source, "write", None)) and callable(
        getattr(source, "remove_duplicates", None)
    ):
        path = None
        data = read_pypulseq(source, interpreter)
    else:
        raise TypeError(
            f"load takes the path of a .seq file or a pypulseq Sequence, not {type(source)!r}"
        )
    snap = Snapshot(data, path, session)
    warning = snap.rotation_record.warning()
    if warning is not None:
        warnings.warn(warning, stacklevel=2)
    return snap
