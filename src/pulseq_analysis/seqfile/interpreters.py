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
  importing a plugin, and imports a plugin only when its name is asked for. A plugin states the
  version of the protocol that it implements (`Plugin.protocol`); the package uses only a plugin
  of its own version, `PROTOCOL` (P22), whose class has the setting `max_shape_samples` of every
  interpreter, of the default `DEFAULT_MAX_SHAPE_SAMPLES` (`Plugin`).

Every interpreter has the setting `max_shape_samples`: the most samples of each array that the
interpreter makes from a shape of the file, `DEFAULT_MAX_SHAPE_SAMPLES` (2^27) by default, or None
for no limit (the user, 2026-10-18). The specification has no limit (spec:619), and a short file
can declare any number of samples, so a reader that decompresses each shape can allocate without
bound. The setting limits the samples that a shape declares, and the samples that a reader
resamples from a shape (the user, 2026-10-21): for example the cells of an RF pulse on the RF
raster, whose number comes from the last time of its time shape, not from a number that a shape
declares. Over the limit is `NotSupported` (`errors`), before the interpreter allocates the
array.

A function that reads a file takes an interpreter by name or as an object;
`interpreter(value)` gives the object. A name gives the interpreter with its default settings.
An interpreter is a frozen dataclass: two with the same settings are equal, and a result
records the interpreter that made it. A setting that the interpreter does not have (for example
`Spec(rotation="apply")`) is a `TypeError` when the object is made (rule 8 of section 7.8 of
`docs/plans/parser-redesign.md`).
"""

import dataclasses
import importlib.metadata
import numbers
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .model import SequenceData

__all__ = [
    "DEFAULT_MAX_SHAPE_SAMPLES",
    "GROUP",
    "PROTOCOL",
    "Interpreter",
    "Plugin",
    "Spec",
    "interpreter",
    "interpreter_names",
]

# The entry-point group of the plugin interpreters.
GROUP = "pulseq_analysis.interpreters"

# The version of the protocol `Plugin` (and of `synth.Decoding`) that the package uses. Version 1
# (P22, task R16): `decode(data, session)` takes the scanner session, and a decoding gives the
# actual and stored durations, the records of the session and the flags of the field of view.
# Before it the protocol had no version. A change of the protocol is a change of the contract
# with pulseq-checks (section 7.3 of the plan): a new version, noted in `CHANGELOG.md`. Version
# 1 is not released yet, and changes in place until it is, as for `gradient_variants` and the
# times of `gradients_at` in s, as the rest of the API (the user, 2026-10-14), and for the setting
# `max_shape_samples` of every interpreter, of the default `DEFAULT_MAX_SHAPE_SAMPLES` (the user,
# 2026-10-18).
PROTOCOL = 1

# The default of the setting `max_shape_samples` of every interpreter: the most samples of each
# array that an interpreter makes from a shape, 2^27, 1 GiB of float64.
DEFAULT_MAX_SHAPE_SAMPLES = 2**27


def _max_shape_samples(value: Any) -> int | None:
    """`value`, a setting `max_shape_samples`, as an int, or None. Raises `TypeError` when it is
    a bool or not an integer (a numpy int is one), and `ValueError` when it is not above 0."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"max_shape_samples is an int above 0 or None, not {value!r}")
    if value <= 0:
        raise ValueError(f"max_shape_samples is an int above 0 or None, not {value!r}")
    return int(value)


@dataclasses.dataclass(frozen=True, slots=True)
class Spec:
    """The `spec` interpreter: the rules of `seqfile.spec`, and the decoding of `synth.events`.

    `max_shape_samples` is the most samples that a shape can declare (`DEFAULT_MAX_SHAPE_SAMPLES`
    by default; None for no limit), its one setting. A shape that declares more is
    `NotSupported`, and `spec` does not decompress it. It is an int above 0: a numpy int is kept
    as an int, a bool or another type is a `TypeError`, and 0 or less a `ValueError`."""

    name: ClassVar[str] = "spec"
    max_shape_samples: int | None = DEFAULT_MAX_SHAPE_SAMPLES

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_shape_samples", _max_shape_samples(self.max_shape_samples))

    def __str__(self) -> str:
        """The name, with each setting that is not its default."""
        default = Spec()
        settings = [
            f"{field}={getattr(self, field)!r}"
            for field in ("max_shape_samples",)
            if getattr(self, field) != getattr(default, field)
        ]
        return f"{self.name}({', '.join(settings)})" if settings else self.name


@runtime_checkable
class Plugin(Protocol):
    """What a plugin interpreter is: an object of the class of its entry point, made with no
    argument for its default settings.

    - `name`: the name of its entry point (a class attribute).
    - `protocol`: the version of this protocol that it implements (a class attribute, an int);
      the package uses it only when it is `PROTOCOL`.
    - `read(path)`: the Pulseq text file `path` (a `Path`) into a `SequenceData` whose
      `interpreter` is this object, as `seqfile.read_seqfile` returns it: `SeqFileError` with the
      code of each reason when the interpreter rejects the file, `OSError` when the file cannot
      be read. `read_seqfile` checks the package's scope (Q1) before it calls `read`, so `read`
      gets no folder, binary Pulseq file or version outside 1.4.0 to 1.5.x of the "as written"
      reading; a plugin may raise `NotSupported` for a file that it reads outside the scope.
    - `decode(data, session=None)`: the decoding of a `SequenceData` that `read` made under the
      scanner session `session` (a `synth.Session`; `synth.decode` gives one, the neutral one
      by default), an object of the protocol `synth.Decoding`, whose `session` is that session.
      The plugin applies the session with its own hooks, and may use the shared simulation of
      `synth.scanner` (P22, rules 3 and 6 of section 7.8 of the plan). It raises
      `synth.SettingError` for a setting that addresses something the file does not have under
      the interpreter (rule 8).
    - `str()`: the name, with each setting that is not its default.
    - `max_shape_samples`: the most samples of each array that the plugin makes from a shape of
      the file, a dataclass field of the default `DEFAULT_MAX_SHAPE_SAMPLES`, or None for no
      limit; an int above 0 (a bool or another type is a `TypeError`, 0 or less a
      `ValueError`). `read` raises `NotSupported` for a shape that declares more, before
      anything decompresses it. The message gives the path, the ID of the shape, the number of
      samples that it declares and the limit, and names the setting. A plugin that resamples a
      shape (for example an RF pulse on the RF raster) raises `NotSupported` for more samples
      than the limit too, before it allocates them; the message gives the path, the event, the
      number of samples and the limit, and names the setting. The plugin checks the numbers of
      its own reading of the file (it can differ from the "as written" reading), so
      `read_seqfile` does not check them. `interpreter` refuses a plugin class with no such
      field or with another default (`TypeError`). `conformance.check_shape_limit(cls)` checks
      a plugin class in its tests.

    It is a frozen dataclass and compares by its settings, as `Spec` does."""

    name: ClassVar[str]
    protocol: ClassVar[int]
    max_shape_samples: int | None

    def read(self, path: Path) -> "SequenceData": ...

    def decode(self, data: "SequenceData", session: Any = None) -> Any: ...


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


def _check_protocol(value: Any) -> None:
    """Raise `TypeError` when the plugin interpreter `value` (a class or an object) does not
    implement the protocol version `PROTOCOL`."""
    found = getattr(value, "protocol", None)
    if found != PROTOCOL:
        name = getattr(value, "name", value)
        raise TypeError(
            f"the interpreter {name!r} implements the plugin protocol version {found!r}, and "
            f"this pulseq-analysis uses version {PROTOCOL}: install versions of the two that "
            "agree"
        )


def _check_max_shape_samples(value: Any) -> None:
    """Raise `TypeError` when the plugin interpreter `value` (a class or an object) has no
    dataclass field `max_shape_samples` of the default `DEFAULT_MAX_SHAPE_SAMPLES`, the
    convention of `Plugin`."""
    name = getattr(value, "name", value)
    fields = dataclasses.fields(value) if dataclasses.is_dataclass(value) else ()
    found = next((field for field in fields if field.name == "max_shape_samples"), None)
    convention = (
        "every interpreter has the setting max_shape_samples, the most samples that a shape "
        f"can declare, of the default DEFAULT_MAX_SHAPE_SAMPLES ({DEFAULT_MAX_SHAPE_SAMPLES}) "
        f"(seqfile.interpreters.Plugin, protocol version {PROTOCOL})"
    )
    if found is None:
        raise TypeError(
            f"the interpreter {name!r} has no dataclass field max_shape_samples: {convention}"
        )
    if found.default != DEFAULT_MAX_SHAPE_SAMPLES:
        raise TypeError(
            f"the interpreter {name!r} has the default {found.default!r} of max_shape_samples: "
            f"{convention}"
        )


def _plugin(name: str) -> type:
    """The class of the plugin interpreter `name`. Raises `ValueError` when no entry point or
    more than one has the name, `ImportError` when the entry point does not load, and
    `TypeError` when the class it gives has another name or another protocol version, or does
    not have the setting `max_shape_samples` of its default (`_check_max_shape_samples`)."""
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
    _check_protocol(cls)
    _check_max_shape_samples(cls)
    return cls


def interpreter(value: "str | Interpreter") -> Interpreter:
    """The interpreter `value`: an interpreter object as it is, or a name (`interpreter_names`)
    with its default settings. Raises `ValueError` for another name (a plugin cannot be named
    `spec`), `ImportError` for a plugin that does not load, and `TypeError` for a class (its
    message names the call that makes an object of it, for example `Spec()`), for another value,
    for a plugin of another protocol version (`PROTOCOL`), and for a plugin without the setting
    `max_shape_samples` of the default `DEFAULT_MAX_SHAPE_SAMPLES` (`Plugin`)."""
    if isinstance(value, type):
        # The class of a plugin has the members of `Plugin`, but an interpreter is an object.
        raise TypeError(
            f"an interpreter is a name or an interpreter object, not the class {value!r}: "
            f"give an object of it, {value.__name__}()"
        )
    if isinstance(value, Spec):
        return value
    if isinstance(value, str):
        if value == Spec.name:
            return Spec()
        return _plugin(value)()
    if isinstance(getattr(value, "name", None), str) and value.name != Spec.name:
        # A plugin object of another protocol version can lack a member of `Plugin`: its
        # version is checked first, for a message that names it.
        _check_protocol(value)
        _check_max_shape_samples(value)
        if isinstance(value, Plugin):
            return value
    raise TypeError(f"an interpreter is a name or an interpreter object, not {type(value)}")
