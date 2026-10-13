"""`read_seqfile`: a Pulseq text file through one interpreter (`interpreters`), into the model
of layer 1 (`model.SequenceData`)."""

from pathlib import Path

from . import cpp_siemens, reader
from .interpreters import CppSiemens, Interpreter
from .interpreters import interpreter as _interpreter
from .model import SequenceData

__all__ = ["read_seqfile"]


def read_seqfile(path: str | Path, interpreter: "str | Interpreter" = "strict") -> SequenceData:
    """Read the Pulseq text file `path` through `interpreter`, a name (`"strict"`, the default
    until the `spec` interpreter replaces it, or `"cpp-siemens"`) or an interpreter object
    (`CppSiemens(oversampling="edge")`). The default is the fast interpreter; `cpp-siemens`, the
    C++ reader of the scanner, is read by name (the user, 2026-10-12).

    Returns the `SequenceData` of the interpreter; its `interpreter` field records the
    interpreter and its settings. Raises `SeqFileError` (a `ValueError`) when the interpreter
    rejects the file, with the code of each reason, `NotSupported` (a `NotImplementedError`) for
    a file that the package does not read (a version outside 1.4.0 to 1.5.x), and `OSError` when
    the file cannot be read. `cpp-siemens` needs the extra `pulseq-analysis[cpp-siemens]`
    (`ImportError` without it)."""
    chosen = _interpreter(interpreter)
    if isinstance(chosen, CppSiemens):
        return cpp_siemens.read_cpp_siemens(path, chosen)
    return reader.read_strict(path)
