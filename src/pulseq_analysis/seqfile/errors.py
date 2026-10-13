"""The rejection of a file by an interpreter, and the exception for a file outside the package's
scope.

- `SeqFileError` (a `ValueError`): an interpreter gives no waveform for the file. It has every
  reason that the interpreter gives, each a `Violation` with a stable code (`Violation.rule`):
  for `spec`, every violation of its rules (`spec.RULES`, each with its basis); for
  `cpp-siemens`, the reason why the C++ reader rejects the file (`cpp_siemens.CODES`). pulseq-checks and the tests name a
  rejection by its code.
- `NotSupported` (a `NotImplementedError`): the package does not read the file, whatever the
  interpreter (Q1 of `docs/plans/parser-redesign.md`): a version outside 1.4.0 to 1.5.x, a binary
  Pulseq file, or a folder. It says nothing about whether the file is valid.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

__all__ = ["NotSupported", "SeqFileError", "Violation"]


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
