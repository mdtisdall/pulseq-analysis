"""The model of layer 1: what a Pulseq file defines, as plain read-only values.

`seqfile.read_seqfile` makes a `SequenceData` from a text file. It holds the version, the
definitions, the rasters, the block table, one table for each kind of event, the shapes, the
extensions and the signature. IDs are those of the file (no renumbering). A value is in the unit
of the file converted to seconds, or Hz, Hz/m, rad and ppm as in the file. No value of a target
(dead times, gamma, B0, limits) is in the model: they belong to layer 2.

Every class is a frozen dataclass with `slots=True` and `eq=False`, and every field is
immutable: a numpy array is read-only and cannot be made writable again
(`_equality._freeze`), a mapping is a `types.MappingProxyType`, and a sequence is a tuple.
`__post_init__` makes a field immutable if it is not, so a model is immutable whoever makes it.
Two models are equal when each field is equal (a NaN equals a NaN, and structured arrays
compare field by field). `pickle` and `copy.deepcopy` keep the values and the immutability. A
model is not hashable.

The tables are structured arrays (`TABLE_DTYPES` has the dtype of each), in file order:

- `blocks`: `id`, `duration_ticks` (in units of `BlockDurationRaster`), `rf`, `gx`, `gy`, `gz`,
  `adc`, `ext`. 0 is no event. File order is play order.
- `rf`: `id`, `amplitude` (Hz), `mag_id`, `phase_id`, `time_id`, `center` (s), `delay` (s),
  `freq_ppm`, `phase_ppm`, `freq_offset` (Hz), `phase_offset` (rad), `use` (one of
  `e r i s p o u`).
- `grad` (arbitrary gradients): `id`, `amplitude` (Hz/m), `first`, `last` (Hz/m), `shape_id`,
  `time_id` (0 is the default raster, -1 is half of it), `delay` (s).
- `trap`: `id`, `amplitude` (Hz/m), `rise`, `flat`, `fall`, `delay` (s). `grad` and `trap`
  share one ID space.
- `adc`: `id`, `num_samples`, `dwell` (s), `delay` (s), `freq_ppm`, `phase_ppm`,
  `freq_offset` (Hz), `phase_offset` (rad), `phase_shape_id` (0 is no modulation).

A 1.4.x file has fewer columns, and the model has the 1.5 layout with these values: RF
`freq_ppm` and `phase_ppm` are 0, `use` is `u` (undefined), and `center` is NaN (the format
had no center, and a caller that needs it computes it from the pulse). ADC `freq_ppm`,
`phase_ppm` and `phase_shape_id` are 0. The `first` and `last` of a gradient with a time shape
(`time_id` above 0) are the amplitude times the first and the last sample of its waveform,
which are at the two ends of the event. A 1.4.x file with a gradient on the default raster
(`time_id` 0) does not define these values, so the parser does not read it
(`seqfile`, rule `layer1.gradient-ends`).

`Extensions` holds the list table of `[EXTENSIONS]` and one table for each extension that the
parser knows. `Shape` holds a shape as the file stores it, and `Shape.samples()` decompresses
it (`decompress_shape`).
"""

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import numpy as np

from ._equality import _freeze, values_equal

# The dtype of each table of the model, by field name of `SequenceData` or `Extensions`.
# `Extensions.labelset`, `Extensions.labelinc` and `Extensions.soft_delays` have a text field
# (`name`, `hint`) whose width is that of the longest text in the table, at least 1.
TABLE_DTYPES: Mapping[str, np.dtype] = MappingProxyType(
    {
        "blocks": np.dtype(
            [(n, "<i8") for n in ("id", "duration_ticks", "rf", "gx", "gy", "gz", "adc", "ext")]
        ),
        "rf": np.dtype(
            [
                ("id", "<i8"),
                ("amplitude", "<f8"),
                ("mag_id", "<i8"),
                ("phase_id", "<i8"),
                ("time_id", "<i8"),
                ("center", "<f8"),
                ("delay", "<f8"),
                ("freq_ppm", "<f8"),
                ("phase_ppm", "<f8"),
                ("freq_offset", "<f8"),
                ("phase_offset", "<f8"),
                ("use", "<U1"),
            ]
        ),
        "grad": np.dtype(
            [
                ("id", "<i8"),
                ("amplitude", "<f8"),
                ("first", "<f8"),
                ("last", "<f8"),
                ("shape_id", "<i8"),
                ("time_id", "<i8"),
                ("delay", "<f8"),
            ]
        ),
        "trap": np.dtype(
            [
                ("id", "<i8"),
                ("amplitude", "<f8"),
                ("rise", "<f8"),
                ("flat", "<f8"),
                ("fall", "<f8"),
                ("delay", "<f8"),
            ]
        ),
        "adc": np.dtype(
            [
                ("id", "<i8"),
                ("num_samples", "<i8"),
                ("dwell", "<f8"),
                ("delay", "<f8"),
                ("freq_ppm", "<f8"),
                ("phase_ppm", "<f8"),
                ("freq_offset", "<f8"),
                ("phase_offset", "<f8"),
                ("phase_shape_id", "<i8"),
            ]
        ),
        "entries": np.dtype([(n, "<i8") for n in ("id", "type", "ref", "next")]),
        "triggers": np.dtype(
            [(n, "<i8") for n in ("id", "type", "channel")]
            + [("delay", "<f8"), ("duration", "<f8")]
        ),
        "labelset": np.dtype([("id", "<i8"), ("value", "<i8"), ("name", "<U1")]),
        "labelinc": np.dtype([("id", "<i8"), ("value", "<i8"), ("name", "<U1")]),
        "soft_delays": np.dtype(
            [("id", "<i8"), ("num", "<i8"), ("offset", "<f8"), ("factor", "<f8"), ("hint", "<U1")]
        ),
        "rotations": np.dtype([(n, "<f8") for n in ("id", "q0", "qx", "qy", "qz")]),
    }
)


def _is_immutable_array(a: np.ndarray) -> bool:
    """Whether `a` is read-only and cannot be made writable again (`_equality._freeze` makes
    such an array, and a view of one is one too)."""
    if a.flags.writeable:
        return False
    try:
        a.flags.writeable = True
    except ValueError:
        return True
    a.flags.writeable = False
    return False


def _immutable(value: Any) -> Any:
    """`value` with every numpy array read-only, every mapping a `MappingProxyType` and every
    list a tuple, or `value` itself when it is immutable already."""
    if isinstance(value, np.ndarray):
        return value if _is_immutable_array(value) else _freeze(value)[0]
    if isinstance(value, Mapping):
        items = {k: _immutable(v) for k, v in value.items()}
        same = isinstance(value, MappingProxyType) and all(items[k] is v for k, v in value.items())
        return value if same else MappingProxyType(items)
    if isinstance(value, tuple | list):
        items = [_immutable(v) for v in value]
        same = isinstance(value, tuple) and all(a is b for a, b in zip(items, value, strict=True))
        return value if same else tuple(items)
    return value


def _plain(value: Any) -> Any:
    """`value` with each mapping a `dict`, so that `pickle` can write it."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(v) for v in value)
    return value


def _equal(a: Any, b: Any) -> bool:
    """`_equality.values_equal` with mappings, structured arrays and the model classes added."""
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return list(a) == list(b) and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, np.ndarray) and isinstance(b, np.ndarray) and a.dtype.names:
        return (
            a.dtype == b.dtype
            and a.shape == b.shape
            and all(values_equal(a[name], b[name]) for name in a.dtype.names)
        )
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=True))
    if dataclasses.is_dataclass(a) and type(a) is type(b):
        return _model_eq(a, b)
    return values_equal(a, b)


def _model_eq(self: Any, other: object) -> bool:
    if other.__class__ is not self.__class__:
        return NotImplemented
    return all(
        _equal(getattr(self, f.name), getattr(other, f.name)) for f in dataclasses.fields(self)
    )


def _post_init(self: Any) -> None:
    for f in dataclasses.fields(self):
        value = getattr(self, f.name)
        frozen = _immutable(value)
        if frozen is not value:
            object.__setattr__(self, f.name, frozen)


def _getstate(self: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(self, f.name)) for f in dataclasses.fields(self)}


def _setstate(self: Any, state: dict[str, Any]) -> None:
    for name, value in state.items():
        object.__setattr__(self, name, _immutable(value))


def _model[T](cls: type[T]) -> type[T]:
    """Class decorator for a class of this module: a frozen dataclass with slots, `eq=False`,
    the value equality of the module, `__hash__ = None`, `pickle` and `copy` support, and
    immutable fields (`__post_init__`)."""
    cls.__post_init__ = _post_init  # type: ignore[attr-defined]
    cls = dataclasses.dataclass(frozen=True, slots=True, eq=False)(cls)
    cls.__eq__ = _model_eq  # type: ignore[method-assign]
    cls.__hash__ = None  # type: ignore[assignment]
    cls.__getstate__ = _getstate  # type: ignore[attr-defined]
    cls.__setstate__ = _setstate  # type: ignore[attr-defined]
    return cls


def decompress_shape(packed: np.ndarray, num_samples: int) -> np.ndarray:
    """The samples of a shape that the file stores as `packed`, with `num_samples` samples.

    This is the algorithm of MATLAB Pulseq `decompressShape.m`, since the specification defines
    the compression only by examples. If `packed` has `num_samples` values, the shape is
    stored uncompressed and `packed` is the result. Otherwise `packed` encodes the derivative
    of the shape with a run-length code: a pair of equal values `v, v` followed by `r` stands
    for `r + 2` samples of the derivative `v`. The result is the cumulative sum of the
    derivative.

    Returns a new float64 array. Raises `ValueError` (with a message that says what is wrong)
    when the code is cut at the end, when a repeat count is not a whole number of at least 0,
    or when the decompressed length is not `num_samples`.
    """
    packed = np.asarray(packed, dtype=np.float64)
    n = packed.size
    if n == num_samples:
        return packed.copy()
    markers = np.flatnonzero(packed[1:] == packed[:-1])
    pieces: list[np.ndarray] = []
    total = 0  # samples of the derivative made so far
    at = 0  # the next stored value to read
    for m in markers.tolist():
        if m < at:
            continue  # inside a run that was read already (a false marker)
        if m > at:
            pieces.append(packed[at:m])
            total += m - at
            at = m
        if at + 2 >= n:
            raise ValueError("a repeat is cut at the end of the stored values")
        count = packed[at + 2]
        if count < 0 or count != int(count):
            raise ValueError(f"a repeat count is {count:g}, not a whole number of at least 0")
        reps = int(count) + 2
        total += reps
        if total > num_samples:
            raise ValueError(f"it has more than the {num_samples} samples that it declares")
        pieces.append(np.full(reps, packed[at]))
        at += 3
    if at < n:
        pieces.append(packed[at:])
        total += n - at
    if total != num_samples:
        raise ValueError(f"it has {total} samples, not the {num_samples} that it declares")
    return np.cumsum(np.concatenate(pieces)) if pieces else np.zeros(0)


@_model
class Rasters:
    """The four rasters of `[DEFINITIONS]`, in seconds."""

    gradient: float  # GradientRasterTime
    rf: float  # RadiofrequencyRasterTime
    adc: float  # AdcRasterTime
    block_duration: float  # BlockDurationRaster


@_model
class Shape:
    """One shape as the file stores it.

    `packed` is the stored (compressed or uncompressed) values and `num_samples` the number of
    samples of the shape. `samples()` decompresses it (`decompress_shape`).
    """

    num_samples: int
    packed: np.ndarray

    def samples(self) -> np.ndarray:
        """The decompressed samples, a new float64 array."""
        return decompress_shape(self.packed, self.num_samples)


@_model
class Signature:
    """The `[SIGNATURE]` section: `type` (for example `md5`) and `hash` as in the file.

    `matches` is whether the hash of the bytes of the file before `\\n[SIGNATURE]` is `hash`, or
    `None` when it cannot be known (an algorithm that `hashlib` does not have). The parser
    reports it and does not reject a file for a mismatch.
    """

    type: str
    hash: str
    matches: bool | None


@_model
class Extensions:
    """The extensions of a file.

    `entries` is the table of `[EXTENSIONS]` (`id`, `type`, `ref`, `next`; `next` 0 ends a
    list). `type_ids` maps the STRING_ID of each `extension` section of the file, known or not,
    to its type ID in this file. Each other field is the table of the extension of that
    name, empty when the file has none (the dtypes are in `TABLE_DTYPES`). `rf_shims` maps the
    object ID to an array of one row for each channel with the magnitude and the phase.
    """

    entries: np.ndarray
    type_ids: Mapping[str, int]
    triggers: np.ndarray  # TRIGGERS: delay and duration in s
    labelset: np.ndarray  # LABELSET
    labelinc: np.ndarray  # LABELINC
    soft_delays: np.ndarray  # DELAYS: offset in s
    rotations: np.ndarray  # ROTATIONS: quaternions as in the file
    rf_shims: Mapping[int, np.ndarray]  # RF_SHIMS


@_model
class SequenceData:
    """A Pulseq file as it is specified (layer 1). The module docstring has the layout.

    - `version`: `(major, minor, revision)`.
    - `definitions`: the tokens of each line of `[DEFINITIONS]` as text, in file order. No
      value is converted to a number (the rasters are in `rasters`).
    - `rasters`, `required_extensions` (the STRING_IDs of the definition `RequiredExtensions`).
    - `blocks`, `rf`, `grad`, `trap`, `adc`: the tables of the module docstring.
    - `shapes`: `Shape` by shape ID.
    - `extensions`, and `skipped_extensions`: the STRING_IDs of the extensions that the
      parser does not know and that the file does not require (their rows are not read).
    - `signature`: `None` when the file has no `[SIGNATURE]` section.
    - `origin`: `"file"`.
    """

    version: tuple[int, int, int]
    definitions: Mapping[str, tuple[str, ...]]
    rasters: Rasters
    required_extensions: tuple[str, ...]
    blocks: np.ndarray
    rf: np.ndarray
    grad: np.ndarray
    trap: np.ndarray
    adc: np.ndarray
    shapes: Mapping[int, Shape]
    extensions: Extensions
    skipped_extensions: tuple[str, ...]
    signature: Signature | None
    origin: str

    @property
    def block_durations_s(self) -> np.ndarray:
        """The duration of each block in seconds: `duration_ticks` times `BlockDurationRaster`."""
        return self.blocks["duration_ticks"] * self.rasters.block_duration
