"""`read_pypulseq`: a `pypulseq.Sequence` built in memory, written to Pulseq text with pypulseq's
own writer and read through one interpreter (task R15 of `docs/plans/parser-redesign.md`, P16).
What is read is what the scanner would receive from `seq.write(path)`, the writer's rounding
included, so a sequence in memory gets the same interpreters and the same readings as a file.

The writer's options are fixed, and are those of `seq.write(path)` except one:

- `create_signature=True`: the file has its `[SIGNATURE]` section, as a written file does, and
  the interpreters read it (`SequenceData.signature`).
- `remove_duplicates=True`: the writer merges the duplicate events and shapes, as
  `seq.write(path)` does.
- `check_timing=False`: pypulseq's timing check only warns, and the package does not check a
  sequence; the interpreter gives a reading or a rejection. The writer's warning about a
  gradient that does not ramp down in the last block is pypulseq's, and is not suppressed.
- The version is the one that pypulseq writes (not `v141_compat`).

The caller's sequence is not changed. `Sequence.write` changes the sequence that it writes: it
sets the definition `TotalDuration`, and the signature fields (`signature_type`,
`signature_file`, `signature_value`). So the text is written from a copy:
`seq.remove_duplicates()` (with `in_place=False`, a deep copy, which `Sequence.write` makes
too), which is then written with `remove_duplicates=False`. The bytes are those of
`seq.write(path)`.

The text is written to a file in a private temporary folder (`tempfile.TemporaryDirectory`),
never next to the caller's files, because the interpreters read a path. The folder is removed
after the reading. A rejection names the sequence as `SOURCE`, not the temporary path.

The module imports nothing of pypulseq (`seq` is typed `Any`): it calls the methods of the
`pypulseq.Sequence` that it is given, so it needs pypulseq only where the caller has it.
"""

import dataclasses
import tempfile
from pathlib import Path
from typing import Any

from .errors import NotSupported, SeqFileError
from .interpreters import Interpreter
from .interpreters import interpreter as _interpreter
from .model import SequenceData
from .reading import read_seqfile

__all__ = ["SOURCE", "read_pypulseq"]

# The name of the sequence in a rejection, in place of the temporary path.
SOURCE = "<pypulseq.Sequence>"


def read_pypulseq(seq: Any, interpreter: "str | Interpreter" = "strict") -> SequenceData:
    """Write `seq` with pypulseq's writer, and read the text through `interpreter`, as
    `read_seqfile` reads a file (the module docstring). `seq` is not changed.

    Returns the `SequenceData` that `read_seqfile` gives for the file of `seq.write(path)`, with
    `origin` `"pypulseq"` in place of `"file"`. Raises what `read_seqfile` raises, with `SOURCE`
    in place of the path (`SeqFileError.path`), `TypeError` when `seq` is not a sequence of
    pypulseq, and any exception of pypulseq's writer."""
    if not callable(getattr(seq, "write", None)) or not callable(
        getattr(seq, "remove_duplicates", None)
    ):
        raise TypeError(f"read_pypulseq takes a pypulseq.Sequence, not {type(seq)}")
    chosen = _interpreter(interpreter)
    with tempfile.TemporaryDirectory(prefix="pulseq-analysis-") as folder:
        path = Path(folder) / "sequence.seq"
        seq.remove_duplicates().write(
            str(path), create_signature=True, remove_duplicates=False, check_timing=False
        )
        try:
            data = read_seqfile(path, chosen)
        except SeqFileError as error:
            raise SeqFileError(SOURCE, error.violations, error.omitted, error.interpreter) from None
        except NotSupported as error:
            raise NotSupported(str(error).replace(str(path), SOURCE)) from None
    return dataclasses.replace(data, origin="pypulseq")
