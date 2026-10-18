"""The rejection of a file by an interpreter, the exception for a file outside the package's
scope, and the check of that scope.

- `SeqFileError` (a `ValueError`): an interpreter gives no waveform for the file. It has every
  reason that the interpreter gives, each a `Violation` with a stable code (`Violation.rule`):
  for `spec`, every violation of its rules (`spec.RULES`, each with its basis); for a plugin
  interpreter, the codes that it documents. pulseq-checks and the tests name a rejection by its
  code.
- `NotSupported` (a `NotImplementedError`): the package does not read the file, whatever the
  interpreter (Q1 of `docs/plans/parser-redesign.md`): a version outside 1.4.0 to 1.5.x, a binary
  Pulseq file, or a folder. It says nothing about whether the file is valid.
- `_read_in_scope(path)`: the check of the scope, with one message for each case, which
  `reading.read_seqfile` makes before an interpreter reads the file, so for every interpreter
  (the user, 2026-10-14), and `spec._read_spec` too.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .as_written import AsWritten, read_as_written

__all__ = ["NotSupported", "SeqFileError", "Violation"]

# The versions that the package reads (Q1): 1.4.0 up to, not including, 1.6.0.
_MIN_VERSION, _MAX_VERSION = (1, 4, 0), (1, 6, 0)

# The first 8 bytes of a binary Pulseq file: those that `ExternalSequence::load(path)` of the C++
# reader reads as one, with `loadBinary` (`pulseqBinaryMagic`, cpp:48-54).
_BINARY_MAGIC = b"\x01pulseq\x02"


@dataclasses.dataclass(frozen=True, slots=True)
class Violation:
    """One reason why an interpreter rejects a file.

    `rule` is its code, `section` is the section (`BLOCKS`, `extension ROTATIONS`) or `None` for
    the file, `line` is the line number in the file (from 1) or `None`, and `message` says what
    is wrong.
    """

    rule: str
    section: str | None
    line: int | None
    message: str


class SeqFileError(ValueError):
    """An interpreter rejects a file. `violations` has its reasons, at most `MAX_LOCATIONS` of
    `seqfile.spec` for each code, in the order of the file. `omitted` maps a code to the number
    of its further reasons that are not in `violations`. `path` is the file, and `interpreter`
    the name of the interpreter that rejects it."""

    def __init__(
        self,
        path: str,
        violations: Sequence[Violation],
        omitted: Mapping[str, int] | None = None,
        interpreter: str = "spec",
    ):
        self.path = path
        self.violations = tuple(violations)
        self.omitted = MappingProxyType(dict(omitted or {}))
        self.interpreter = interpreter
        total = len(self.violations) + sum(self.omitted.values())
        shown = [
            f"  {v.rule} ({v.section or 'file'}"
            + (f", line {v.line}" if v.line is not None else "")
            + f"): {v.message}"
            for v in self.violations[:10]
        ]
        if total > len(shown):
            shown.append(f"  and {total - len(shown)} more (see the `violations` attribute)")
        super().__init__(
            f"the interpreter {interpreter} rejects {path}, with {total} reason(s):\n"
            + "\n".join(shown)
        )

    @property
    def codes(self) -> frozenset[str]:
        """The code of each reason."""
        return frozenset(v.rule for v in self.violations) | frozenset(self.omitted)

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            SeqFileError,
            (self.path, self.violations, dict(self.omitted), self.interpreter),
        )


class NotSupported(NotImplementedError):
    """The package does not read the file (Q1 of `docs/plans/parser-redesign.md`): a version
    outside 1.4.0 to 1.5.x, a binary Pulseq file, or a folder. No interpreter reads it, and the
    exception says nothing about whether the file is valid."""


def _read_in_scope(path: str | Path) -> AsWritten:
    """The "as written" reading of the file `path` (`as_written.read_as_written`), after the
    check of the package's scope. Raises `NotSupported` for a folder, a binary Pulseq file (its
    first 8 bytes are `_BINARY_MAGIC`) and a version outside 1.4.0 to 1.5.x (`AsWritten.version`),
    in this order, and `OSError` when the file cannot be read. A file whose version the "as
    written" reading does not give (`AsWritten.version` None) is in the scope: the interpreter
    rejects it."""
    if Path(path).is_dir():
        raise NotSupported(f"{path} is a folder; the package reads one Pulseq text file")
    written = read_as_written(path)
    if written.raw[:8] == _BINARY_MAGIC:
        raise NotSupported(f"{path} is a binary Pulseq file; the package reads the text format")
    version = written.version
    if version is not None and not _MIN_VERSION <= version < _MAX_VERSION:
        name = ".".join(map(str, version))
        raise NotSupported(
            f"{path}: version {name} is outside 1.4.0 to 1.5.x; the package does not read it"
        )
    return written
