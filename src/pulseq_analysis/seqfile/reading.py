"""`read_seqfile`: a Pulseq text file through one interpreter (`interpreters`), into the model
of layer 1 (`model.SequenceData`)."""

from pathlib import Path

from . import spec
from .errors import _read_in_scope
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
    a file that the package does not read, and `OSError` when the file cannot be read. A name
    that no installed interpreter has is a `ValueError`. A shape that declares more samples than
    the setting `max_shape_samples` of the interpreter is `NotSupported` too: each interpreter
    checks it with its own reading of the file, before it decompresses the shape
    (`interpreters.Plugin`).

    The scope is checked before the interpreter reads the file, so it is one for every
    interpreter, with one message for each case (`errors._read_in_scope`; the
    user, 2026-10-14): a folder, a binary Pulseq file, or a version
    outside 1.4.0 to 1.5.x is `NotSupported`. `spec` reads the "as written" reading of the check;
    a plugin reads the file again from `path`."""
    chosen = _interpreter(interpreter)
    written = _read_in_scope(path)
    if isinstance(chosen, Spec):
        return spec._read_written(written, chosen)
    return chosen.read(Path(path))
