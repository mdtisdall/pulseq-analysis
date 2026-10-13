"""The interpreters of the package: the ways in which it reads a Pulseq file
(`docs/plans/parser-redesign.md`, section 1 and Q6).

- `CppSiemens` (`"cpp-siemens"`): the C++ reader of the scanner's interpreter on
  Siemens systems (`ExternalSequence` of pulseq/pulseq at `c7469123`), run in the process
  through the package pulseq-cpp-siemens (the extra `pulseq-analysis[cpp-siemens]`). It reads
  what that reader reads and rejects what it rejects. Its setting `oversampling` is the reader's
  sampling mode of an oversampled arbitrary gradient (D43).
- `Strict` (`"strict"`, the default): the strict reader of the package before the interpreters
  (`seqfile.reader`), with its rules. It is interim: the `spec` interpreter (task R11) replaces
  it, as the default too. The default is the fast interpreter: `cpp-siemens` decodes every block
  of a file with the C++ reader, about seven times as long (`docs/usage.md`).

A function that reads a file takes an interpreter by name or as an object;
`interpreter(value)` gives the object. A name gives the interpreter with its default settings.
An interpreter is a frozen dataclass: two with the same settings are equal, and a result
records the interpreter that made it.
"""

import dataclasses
from typing import ClassVar

__all__ = ["INTERPRETERS", "OVERSAMPLING", "CppSiemens", "Interpreter", "Strict", "interpreter"]

# The sampling modes of an oversampled arbitrary gradient (time shape -1) of the C++ reader
# (`ExternalSequence::m_ArbGradSamplingMode`): the samples at the centres of the gradient raster
# (the reader's default), those at its edges, or all of them.
OVERSAMPLING = ("center", "edge", "preserve")


@dataclasses.dataclass(frozen=True, slots=True)
class CppSiemens:
    """The `cpp-siemens` interpreter: the C++ reader, with its settings.

    `oversampling` is the reader's mode for an oversampled arbitrary gradient (D43): `"center"`
    (the default, `SetArbGradCenterSampling(true)`) keeps the samples at the centres of the
    raster, `"edge"` (`SetArbGradCenterSampling(false)`) those at its edges, and `"preserve"`
    (`SetArbGradPreserveOversampling()`) all of them."""

    name: ClassVar[str] = "cpp-siemens"
    oversampling: str = "center"

    def __post_init__(self) -> None:
        if self.oversampling not in OVERSAMPLING:
            raise ValueError(
                f"oversampling is {self.oversampling!r}, not one of {', '.join(OVERSAMPLING)}"
            )

    def __str__(self) -> str:
        if self == CppSiemens():
            return self.name
        return f"{self.name}(oversampling={self.oversampling!r})"


@dataclasses.dataclass(frozen=True, slots=True)
class Strict:
    """The interim `strict` interpreter: the rules of `seqfile.reader`, and the decoding of
    `synth.events`. It has no setting."""

    name: ClassVar[str] = "strict"

    def __str__(self) -> str:
        return self.name


Interpreter = CppSiemens | Strict

# Each interpreter by its name.
INTERPRETERS: dict[str, type[CppSiemens] | type[Strict]] = {
    CppSiemens.name: CppSiemens,
    Strict.name: Strict,
}


def interpreter(value: "str | Interpreter") -> Interpreter:
    """The interpreter `value`: an interpreter object as it is, or a name of `INTERPRETERS` with
    its default settings. Raises `ValueError` for another name, and `TypeError` for another
    value."""
    if isinstance(value, CppSiemens | Strict):
        return value
    if isinstance(value, str):
        if value == "spec":
            raise ValueError("the interpreter spec is not there yet (task R11); use 'strict'")
        try:
            return INTERPRETERS[value]()
        except KeyError:
            raise ValueError(
                f"no interpreter is named {value!r}; the names are {', '.join(INTERPRETERS)}"
            ) from None
    raise TypeError(f"an interpreter is a name or an interpreter object, not {type(value)}")
