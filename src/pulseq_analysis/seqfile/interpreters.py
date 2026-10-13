"""The interpreters of the package: the ways in which it reads a Pulseq file
(`docs/plans/parser-redesign.md`, section 1, Q6 and P21).

- `Spec` (`"spec"`, the default): as true as possible to the Pulseq specification (1.5.3 draft)
  and to the slide set that its section 2.6 cites for timing (`doc/pulseq_shapes_and_times.pdf`).
  It rejects a file where they say "must", and where they are unclear it makes a documented choice
  (`spec`, section 6 of the plan). It is fast: the default is the fast interpreter (P19). It is
  part of the package.
- A plugin interpreter: a class that another distribution gives through the entry-point group
  `pulseq_analysis.interpreters` (`GROUP`). The name of the entry point is the name of the
  interpreter, and its value is the class (`Plugin`). The package lists the names without
  importing a plugin, and imports a plugin only when its name is asked for.

A function that reads a file takes an interpreter by name or as an object;
`interpreter(value)` gives the object. A name gives the interpreter with its default settings.
An interpreter is a frozen dataclass: two with the same settings are equal, and a result
records the interpreter that made it. A setting that the interpreter does not have (for example
`Spec(rotation="apply")`) is a `TypeError` when the object is made (rule 8 of section 7.8 of
`docs/plans/parser-redesign.md`).
"""

import dataclasses
import importlib.metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .model import SequenceData

__all__ = [
    "GROUP",
    "Interpreter",
    "Plugin",
    "Spec",
    "interpreter",
    "interpreter_names",
]

# The entry-point group of the plugin interpreters.
GROUP = "pulseq_analysis.interpreters"


@dataclasses.dataclass(frozen=True, slots=True)
class Spec:
    """The `spec` interpreter: the rules of `seqfile.spec`, and the decoding of `synth.events`.
    It has no setting."""

    name: ClassVar[str] = "spec"

    def __str__(self) -> str:
        return self.name


@runtime_checkable
class Plugin(Protocol):
    """What a plugin interpreter is: an object of the class of its entry point, made with no
    argument for its default settings.

    - `name`: the name of its entry point (a class attribute).
    - `read(path)`: the Pulseq text file `path` (a `Path`) into a `SequenceData` whose
      `interpreter` is this object, as `seqfile.read_seqfile` returns it: `SeqFileError` with the
      code of each reason when the interpreter rejects the file, `NotSupported` for a file
      outside the package's scope (Q1), `OSError` when the file cannot be read.
    - `decode(data)`: the decoding of a `SequenceData` that `read` made, an object of the
      protocol `synth.Decoding`; `synth.decode` calls it.
    - `str()`: the name, with each setting that is not its default.

    It is frozen and compares by its settings, as `Spec` does."""

    name: ClassVar[str]

    def read(self, path: Path) -> "SequenceData": ...

    def decode(self, data: "SequenceData") -> Any: ...


Interpreter = Spec | Plugin


def _entry_points() -> dict[str, list[importlib.metadata.EntryPoint]]:
    """The entry points of `GROUP` by name; a name can have more than one."""
    found: dict[str, list[importlib.metadata.EntryPoint]] = {}
    for ep in importlib.metadata.entry_points(group=GROUP):
        found.setdefault(ep.name, []).append(ep)
    return found


def interpreter_names() -> tuple[str, ...]:
    """The names of the interpreters: `spec`, then each plugin's, sorted. No plugin is
    imported."""
    return (Spec.name, *sorted(set(_entry_points()) - {Spec.name}))


def _plugin(name: str) -> type:
    """The class of the plugin interpreter `name`. Raises `ValueError` when no entry point or
    more than one has the name, `ImportError` when the entry point does not load, and
    `TypeError` when the class it gives has another name."""
    eps = _entry_points().get(name, [])
    if not eps:
        raise ValueError(
            f"no interpreter is named {name!r}; the installed interpreters are "
            f"{', '.join(interpreter_names())}. A distribution adds one through the entry-point "
            f"group {GROUP}."
        )
    if len(eps) > 1:
        values = ", ".join(ep.value for ep in eps)
        raise ValueError(f"more than one interpreter is named {name!r}: {values}")
    try:
        cls = eps[0].load()
    except Exception as error:
        raise ImportError(
            f"the interpreter {name!r} ({eps[0].value}) did not load: {error}"
        ) from error
    if getattr(cls, "name", None) != name:
        raise TypeError(f"the entry point {name!r} gives {cls!r}, whose name is not {name!r}")
    return cls


def interpreter(value: "str | Interpreter") -> Interpreter:
    """The interpreter `value`: an interpreter object as it is, or a name (`interpreter_names`)
    with its default settings. Raises `ValueError` for another name (a plugin cannot be named
    `spec`), `ImportError` for a plugin that does not load, and `TypeError` for another
    value."""
    if isinstance(value, Spec):
        return value
    if isinstance(value, str):
        if value == Spec.name:
            return Spec()
        return _plugin(value)()
    if isinstance(value, Plugin) and value.name != Spec.name:
        return value
    raise TypeError(f"an interpreter is a name or an interpreter object, not {type(value)}")
