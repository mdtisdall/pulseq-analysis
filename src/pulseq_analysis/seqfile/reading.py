"""`read_seqfile`: a Pulseq text file through one interpreter (`interpreters`), into the model
of layer 1 (`model.SequenceData`)."""

from pathlib import Path

from . import spec
from .interpreters import Interpreter, Spec
from .interpreters import interpreter as _interpreter
from .model import SequenceData

__all__ = ["read_seqfile"]


def read_seqfile(path: str | Path, interpreter: "str | Interpreter" = "spec") -> SequenceData:
    """Read the Pulseq text file `path` through `interpreter`, a name (`"spec"`, the default, or
    the name of a plugin interpreter, `interpreters.interpreter_names()`) or an interpreter
    object with its settings. The default is the fast interpreter; a plugin is read by name or
    object (the user, 2026-10-12).

    Returns the `SequenceData` of the interpreter; its `interpreter` field records the
    interpreter and its settings. Raises `SeqFileError` (a `ValueError`) when the interpreter
    rejects the file, with the code of each reason, `NotSupported` (a `NotImplementedError`) for
    a file that the package does not read (a version outside 1.4.0 to 1.5.x), and `OSError` when
    the file cannot be read. A name that no installed interpreter has is a `ValueError`."""
    chosen = _interpreter(interpreter)
    if isinstance(chosen, Spec):
        return spec.read_spec(path)
    return chosen.read(Path(path))
