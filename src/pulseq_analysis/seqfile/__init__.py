"""The files layer: the "as written" reading of Pulseq text files, the interpreters that read
them into the model (`SequenceData`), and their rejections. It imports only from the base modules
of the package.

- `read_as_written(path)`: the "as written" reading (`as_written`), with its types.
- `read_seqfile(path, interpreter="strict")`: the file through an interpreter
  (`interpreters`): the interim `strict` (`reader`), the default until `spec` (task R11)
  replaces it, or `cpp-siemens` (`cpp_siemens`, the C++ reader of the scanner's interpreter on
  Siemens systems), by name. It returns a `SequenceData`, or raises
  `SeqFileError` (with a code for each reason) or `NotSupported`.
- `read_pypulseq(seq, interpreter="strict")`: a `pypulseq.Sequence` in memory, written with
  pypulseq's writer and read as `read_seqfile` reads the file (`from_pypulseq`, task R15).

These readings are the contract with pulseq-checks (section 7.3 of
`docs/plans/parser-redesign.md`); a change to them is noted in `CHANGELOG.md`.
"""

from .as_written import AsWritten, Column, Line, Section, ShapeWritten, Table, read_as_written
from .errors import NotSupported, SeqFileError, Violation
from .from_pypulseq import read_pypulseq
from .interpreters import (
    INTERPRETERS,
    OVERSAMPLING,
    ROTATION,
    CppSiemens,
    Interpreter,
    Strict,
    interpreter,
)
from .model import SequenceData
from .reading import read_seqfile

__all__ = [
    "INTERPRETERS",
    "OVERSAMPLING",
    "ROTATION",
    "AsWritten",
    "Column",
    "CppSiemens",
    "Interpreter",
    "Line",
    "NotSupported",
    "Section",
    "SeqFileError",
    "SequenceData",
    "ShapeWritten",
    "Strict",
    "Table",
    "Violation",
    "interpreter",
    "read_as_written",
    "read_pypulseq",
    "read_seqfile",
]
