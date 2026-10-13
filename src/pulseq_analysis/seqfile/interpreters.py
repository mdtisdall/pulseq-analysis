"""The interpreters of the package: the ways in which it reads a Pulseq file
(`docs/plans/parser-redesign.md`, section 1 and Q6).

- `Spec` (`"spec"`, the default): as true as possible to the Pulseq specification (1.5.3 draft)
  and to the slide set that its section 2.6 cites for timing (`doc/pulseq_shapes_and_times.pdf`).
  It rejects a file where they say "must", and where they are unclear it makes a documented choice
  (`spec`, section 6 of the plan). It is fast: the default is the fast interpreter (P19).
- `CppSiemens` (`"cpp-siemens"`): the C++ reader of the scanner's interpreter on
  Siemens systems (`ExternalSequence` of pulseq/pulseq at `c7469123`), run in the process
  through the package pulseq-cpp-siemens (the extra `pulseq-analysis[cpp-siemens]`). It reads
  what that reader reads and rejects what it rejects. Its setting `oversampling` is the reader's
  sampling mode of an oversampled arbitrary gradient (D43); its setting `rotation` says whether
  the decoding gives the reader's unrotated gradients or simulates the scanner's rotation of each
  block (D49, P20). It decodes every block of a file with the C++ reader, about six times as long
  as `spec` (`docs/usage.md`), so it is read by name.

A function that reads a file takes an interpreter by name or as an object;
`interpreter(value)` gives the object. A name gives the interpreter with its default settings.
An interpreter is a frozen dataclass: two with the same settings are equal, and a result
records the interpreter that made it. A setting that the interpreter does not have (for example
`Spec(rotation="apply")`) is a `TypeError` when the object is made (rule 8 of section 7.8 of
`docs/plans/parser-redesign.md`).
"""

import dataclasses
from typing import ClassVar

__all__ = [
    "INTERPRETERS",
    "OVERSAMPLING",
    "ROTATION",
    "CppSiemens",
    "Interpreter",
    "Spec",
    "interpreter",
]

# The sampling modes of an oversampled arbitrary gradient (time shape -1) of the C++ reader
# (`ExternalSequence::m_ArbGradSamplingMode`): the samples at the centres of the gradient raster
# (the reader's default), those at its edges, or all of them.
OVERSAMPLING = ("center", "edge", "preserve")

# What the `cpp-siemens` decoding does with the rotation of a block (the ROTATIONS extension,
# D49): the reader's own output, whose gradients are not rotated (the reader leaves the rotation
# to the scanner's interpreter), or the package's simulation of the scanner, which rotates them.
ROTATION = ("reader", "apply")


@dataclasses.dataclass(frozen=True, slots=True)
class CppSiemens:
    """The `cpp-siemens` interpreter: the C++ reader, with its settings.

    `oversampling` is the reader's mode for an oversampled arbitrary gradient (D43): `"center"`
    (the default, `SetArbGradCenterSampling(true)`) keeps the samples at the centres of the
    raster, `"edge"` (`SetArbGradCenterSampling(false)`) those at its edges, and `"preserve"`
    (`SetArbGradPreserveOversampling()`) all of them.

    `rotation` is what the decoding does with each block's rotation (D49): `"reader"` (the
    default) gives the reader's output, the logical gradients with the block's quaternion beside
    them (the reader never rotates them); `"apply"` rotates the gradients of each block to which
    the reader attached a rotation by its quaternion, with the reader's own
    `rotate_vec3_by_quat`, in any version of the file. `"apply"` is the package's simulation of
    the scanner: the scanner's behaviour for a file older than 1.5.1, the revision that defines
    the extension, is not known (the user, 2026-10-12). It is valid on a file with no rotation,
    and then rotates no block."""

    name: ClassVar[str] = "cpp-siemens"
    oversampling: str = "center"
    rotation: str = "reader"

    def __post_init__(self) -> None:
        if self.oversampling not in OVERSAMPLING:
            raise ValueError(
                f"oversampling is {self.oversampling!r}, not one of {', '.join(OVERSAMPLING)}"
            )
        if self.rotation not in ROTATION:
            raise ValueError(f"rotation is {self.rotation!r}, not one of {', '.join(ROTATION)}")

    def __str__(self) -> str:
        """The name, with each setting that is not its default."""
        default = CppSiemens()
        settings = [
            f"{field}={getattr(self, field)!r}"
            for field in ("oversampling", "rotation")
            if getattr(self, field) != getattr(default, field)
        ]
        return f"{self.name}({', '.join(settings)})" if settings else self.name


@dataclasses.dataclass(frozen=True, slots=True)
class Spec:
    """The `spec` interpreter: the rules of `seqfile.spec`, and the decoding of `synth.events`.
    It has no setting."""

    name: ClassVar[str] = "spec"

    def __str__(self) -> str:
        return self.name


Interpreter = CppSiemens | Spec

# Each interpreter by its name.
INTERPRETERS: dict[str, type[CppSiemens] | type[Spec]] = {
    Spec.name: Spec,
    CppSiemens.name: CppSiemens,
}


def interpreter(value: "str | Interpreter") -> Interpreter:
    """The interpreter `value`: an interpreter object as it is, or a name of `INTERPRETERS` with
    its default settings. Raises `ValueError` for another name, and `TypeError` for another
    value."""
    if isinstance(value, CppSiemens | Spec):
        return value
    if isinstance(value, str):
        try:
            return INTERPRETERS[value]()
        except KeyError:
            raise ValueError(
                f"no interpreter is named {value!r}; the names are {', '.join(INTERPRETERS)}"
            ) from None
    raise TypeError(f"an interpreter is a name or an interpreter object, not {type(value)}")
