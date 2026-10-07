"""`Series`: the JSON-ready form of an analysis value.

A series is a named set of one-dimensional numpy arrays with a kind that says what the
arrays mean. The coordinate of a series is the quantity of its horizontal axis, for example
the time (unit "s") or the frequency (unit "Hz"). `coord_unit` is the unit of the coordinate.

- `SAMPLES`: `value[k]` is at the coordinate `coord_start + k * coord_step`.
- `ENVELOPE`: `min[i]` and `max[i]` are the least and the greatest value in the bin
  `[coord_start + i * coord_step, coord_start + (i + 1) * coord_step)`. The last bin stops
  at `coord_end`.
- `POINTS`: `value[k]` is at the coordinate `coord[k]`. The coordinates need not be regular.
- `RUNS`: a boolean that is true from `start[k]` to `end[k]`, and false elsewhere.

`Series.to_obj` gives a dict that `json.dumps(obj, allow_nan=False)` writes, and
`Series.from_obj` reads it back. Each array is one dict `{"dtype", "length", "data"}`
(`encode_array`, `decode_array`), where `data` is the little-endian bytes of the array,
gzipped and base64-encoded. This is the same text as `encode_tables` of pulseq-reports
(`pulseq_reports.diagram_data`), so a report can put the text into its
page with no new encoding. The encoding is deterministic: one array always gives the same
text.

The JSON form cannot hold a float that is not finite (strict JSON). In an array, such a
float is in the bytes. In `meta`, `to_obj` writes infinity and "not a number" as the strings
"inf", "-inf" and "nan", and `from_obj` reads them back. The coordinate fields are always
finite (see `Series`), and `from_obj` raises `ValueError` for an object with one that is not.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import math
import sys
import zlib
from collections.abc import Mapping
from dataclasses import field
from enum import Enum
from typing import Any

import numpy as np

from ._equality import FrozenDict, _freeze, value_dataclass
from ._validate import real

# The strings that stand for a float that is not finite in the JSON form.
_NON_FINITE = ("inf", "-inf", "nan")

# The `dtype.kind` letters of the arrays that a series holds: bool, signed integer,
# unsigned integer, float and complex.
_KINDS = "biufc"

_ARRAY_KEYS = ("dtype", "length", "data")


class SeriesKind(Enum):
    SAMPLES = "samples"  # value[k] at coord_start + k * coord_step
    ENVELOPE = "envelope"  # min[i] and max[i] of the bin
    # [coord_start + i * coord_step, coord_start + (i + 1) * coord_step);
    # the last bin stops at coord_end
    POINTS = "points"  # value[k] at coord[k] (not regular, for example one for each block)
    RUNS = "runs"  # a boolean that is true from start[k] to end[k], else false


# The arrays that each kind must have. `SAMPLES`, `POINTS` and `RUNS` can have more
# arrays; `ENVELOPE` cannot.
_NECESSARY = {
    SeriesKind.SAMPLES: ("value",),
    SeriesKind.ENVELOPE: ("min", "max"),
    SeriesKind.POINTS: ("coord", "value"),
    SeriesKind.RUNS: ("start", "end"),
}


def _check_array(name: str, a: Any) -> None:
    """Raise when `a` is not a one-dimensional numpy array of a bool, integer, float or
    complex dtype. `name` is for the message."""
    if not isinstance(a, np.ndarray):
        raise TypeError(f"the array {name!r} must be a numpy array, not {type(a).__name__}")
    if a.ndim != 1:
        raise ValueError(f"the array {name!r} must be one-dimensional, not {a.ndim}-dimensional")
    if a.dtype.kind not in _KINDS:
        raise ValueError(f"the array {name!r} must have a numeric or bool dtype, not {a.dtype}")


def _check_runs(start: np.ndarray, end: np.ndarray) -> None:
    """Raise `ValueError` when `start` or `end` of a RUNS series has a bool or complex dtype,
    has a value that is not finite, or when `end[k] < start[k]` for a `k`. A run is an interval
    of the coordinate, so `start` and `end` are real numbers."""
    for name, a in (("start", start), ("end", end)):
        if a.dtype.kind in "bc":
            raise ValueError(
                f"the array {name!r} of a runs series must have an integer or float dtype, "
                f"not {a.dtype}"
            )
        if not np.isfinite(a).all():
            raise ValueError(f"the array {name!r} of a runs series must be finite")
    if (end < start).any():
        k = int(np.argmax(end < start))
        raise ValueError(
            f"a run of a runs series must not end before it starts, but end[{k}] is "
            f"{end[k]!r} and start[{k}] is {start[k]!r}"
        )


def _check_real(series: str, name: str, a: np.ndarray) -> None:
    """Raise `ValueError` when the array `name` has a bool or complex dtype. `series` is
    for the message: for example "an envelope series"."""
    if a.dtype.kind not in "iuf":
        raise ValueError(
            f"the array {name!r} of {series} must have an integer or float dtype, not {a.dtype}"
        )


def _check_envelope(low: np.ndarray, high: np.ndarray) -> None:
    """Raise `ValueError` when `low` or `high` of an ENVELOPE series has a bool or complex
    dtype, when they have two dtypes, or when `low[i] > high[i]` for an `i` where neither is
    NaN."""
    _check_real("an envelope series", "min", low)
    _check_real("an envelope series", "max", high)
    if low.dtype != high.dtype:
        raise ValueError(
            f"the arrays 'min' and 'max' of an envelope series must have one dtype, not "
            f"{low.dtype} and {high.dtype}"
        )
    # A comparison with a NaN is false, so a bin with a NaN is not refused.
    if (low > high).any():
        i = int(np.argmax(low > high))
        raise ValueError(
            f"the min of a bin of an envelope series must not be above its max, but min[{i}] "
            f"is {low[i].item()!r} and max[{i}] is {high[i].item()!r}"
        )


def _plain_meta(meta: Any) -> dict[str, str | int | float | bool | None]:
    """A new dict with the values of `meta`, in the same order, as plain `str`, `int`,
    `float`, `bool` or None. A key must be a `str`. A value must be a `str`, an `int`, a
    `float`, a `bool`, a numpy scalar of a bool, integer or float dtype, or None, and a `str`
    value cannot be "inf", "-inf" or "nan", because the JSON form uses these strings for a
    float that is not finite. Another key or value raises `TypeError` or `ValueError`."""
    if not isinstance(meta, Mapping):
        raise TypeError(f"the meta of a series must be a mapping, not {meta!r}")
    out: dict[str, str | int | float | bool | None] = {}
    for key, value in meta.items():
        if not isinstance(key, str):
            raise TypeError(f"a key of the meta of a series must be a string, not {key!r}")
        if isinstance(value, np.generic) and value.dtype.kind in "biuf":
            value = {"b": bool, "i": int, "u": int, "f": float}[value.dtype.kind](value)
        if value is not None and not isinstance(value, (str, int, float)):
            raise TypeError(
                f"the meta value {key!r} of a series must be a string, a number, a bool "
                f"or None, not {value!r}"
            )
        if isinstance(value, str):
            if value in _NON_FINITE:
                raise ValueError(
                    f"the meta value {key!r} of a series must not be the string {value!r}: "
                    "the JSON form uses it for a float that is not finite"
                )
            value = str(value)
        elif isinstance(value, bool):
            pass
        elif isinstance(value, int):
            value = int(value)
        elif isinstance(value, float):
            value = float(value)
        out[str(key)] = value
    return out


@value_dataclass
class Series:
    """One named series of an analysis value.

    The coordinate of a series is the quantity of its horizontal axis, for example the time
    (unit "s") or the frequency (unit "Hz").

    `name` is a short, stable name that a caller can match on: for example "pns_total".
    `unit` is the unit of the values, for example "Hz/T", "Hz/m" or "s". `coord_unit` is the
    unit of the coordinate, and it is not empty. `arrays` maps a name to a one-dimensional
    numpy array of a bool, integer, float or complex dtype. All arrays of one series have the
    same length. The kind says which arrays are necessary:

    - `SAMPLES`: `value`, and more arrays of the same length (for example one for each
      gradient axis).
    - `ENVELOPE`: `min` and `max`, and no other array.
    - `POINTS`: `coord` and `value`, and more arrays of the same length.
    - `RUNS`: `start` and `end`, and more arrays of the same length (a value of each run).

    The other arrays can be in any order. `coord_start` and `coord_step` (above 0, finite)
    give the coordinate of a sample or of a bin, and `coord_end` gives the end of the last
    bin. `SAMPLES` and `ENVELOPE` need `coord_step`, and `ENVELOPE` needs `coord_end`. A field
    that the kind does not use must have its default: `coord_end` None for `SAMPLES`, and
    `coord_start` 0.0 with `coord_step` and `coord_end` None for `POINTS` and `RUNS`. So each
    kind has one form.

    The coordinates are finite and in order. `coord_start` is finite for `SAMPLES` and
    `ENVELOPE`. For an `ENVELOPE` of n bins, `coord_end` is finite and
    `coord_start + (n - 1) * coord_step < coord_end <= coord_start + n * coord_step`, so the
    last bin is not empty and not longer than a step. A `coord_end` within the tolerance
    `1e-9 * coord_step` of a limit counts as equal to the limit (the rounding of a float
    product): it must be above the lower limit by more than the tolerance, and it can be
    above the upper limit by the tolerance. With no bin (n is 0),
    `coord_end >= coord_start`, with no tolerance. For `RUNS`, `start` and `end` have an
    integer or float dtype (not bool or complex), every value is finite, and
    `end[k] >= start[k]` for each run. For `ENVELOPE`, `min` and `max` have one integer or
    float dtype (not bool or complex), and `min[i] <= max[i]` where neither is NaN. For
    `POINTS`, `coord` has an integer or float dtype, and a value that is not finite is valid
    there.

    `meta` holds the values of the series by name, for a machine: only JSON
    scalars. A numpy scalar of a bool, integer or float dtype is stored as a Python `bool`,
    `int` or `float`. A string value of `meta` cannot be "inf", "-inf" or "nan", because the
    JSON form writes a float that is not finite as one of these strings.

    A series raises `TypeError` for a value of a wrong type and `ValueError` for a wrong
    value. It keeps a `FrozenDict` for `arrays` and one for `meta`, so a change to the caller's
    dict does not change the series, and a change to the dict of the series raises
    `TypeError`. It keeps a copy of each array, in native byte order, and
    the copy is read-only (its flag `writeable` cannot be set to True: the base is `bytes`).
    A copy from `pickle` or `copy.deepcopy` is made by the constructor, so it is checked and
    read-only too. A string field and a key of `arrays` or `meta` is stored as a plain `str`.
    The caller's own array stays writable, and a change to it does not change the series.
    An int in `coord_start`, `coord_step` or `coord_end` becomes a float.

    `==` is true when the fields are the same (`_equality.fields_equal`), the array names
    are the same and in the same order, and each pair of arrays has the same dtype and is
    equal by `np.array_equal(a, b, equal_nan=True)`. A float of `meta` that is NaN
    equals a NaN. The keys of `meta` must be the same and in the same order, as for each
    other dict of the package. `to_obj` and `from_obj` keep that order. A series is not
    hashable.
    """

    name: str
    kind: SeriesKind
    unit: str
    coord_unit: str
    arrays: Mapping[str, np.ndarray]
    coord_start: float = 0.0  # SAMPLES and ENVELOPE
    coord_step: float | None = None  # SAMPLES and ENVELOPE
    coord_end: float | None = None  # ENVELOPE
    meta: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(f"the name of a series must be a string, not {self.name!r}")
        if not self.name:
            raise ValueError("the name of a series must not be empty")
        if not isinstance(self.kind, SeriesKind):
            raise TypeError(f"the kind of a series must be a SeriesKind, not {self.kind!r}")
        if not isinstance(self.unit, str):
            raise TypeError(f"the unit of a series must be a string, not {self.unit!r}")
        if not isinstance(self.coord_unit, str):
            raise TypeError(f"the coord_unit of a series must be a string, not {self.coord_unit!r}")
        if not self.coord_unit:
            raise ValueError("the coord_unit of a series must not be empty")
        if not isinstance(self.arrays, Mapping):
            raise TypeError(f"the arrays of a series must be a mapping, not {self.arrays!r}")
        for key, a in self.arrays.items():
            if not isinstance(key, str):
                raise TypeError(f"a key of the arrays of a series must be a string, not {key!r}")
            _check_array(key, a)
        necessary = _NECESSARY[self.kind]
        for key in necessary:
            if key not in self.arrays:
                raise ValueError(f"a {self.kind.value} series needs the array {key!r}")
        if self.kind is SeriesKind.ENVELOPE:
            for key in self.arrays:
                if key not in necessary:
                    raise ValueError(
                        f"an envelope series has only the arrays 'min' and 'max', not {key!r}"
                    )
        lengths = {key: a.size for key, a in self.arrays.items()}
        if len(set(lengths.values())) > 1:
            raise ValueError(f"the arrays of a series must have one length, not {lengths}")

        coord_start = real("coord_start of a series", self.coord_start, finite=False)
        coord_step = (
            None
            if self.coord_step is None
            else real("coord_step of a series", self.coord_step, finite=False)
        )
        coord_end = (
            None
            if self.coord_end is None
            else real("coord_end of a series", self.coord_end, finite=False)
        )
        needs_step = self.kind in (SeriesKind.SAMPLES, SeriesKind.ENVELOPE)
        if coord_step is None and needs_step:
            raise ValueError(f"a {self.kind.value} series needs coord_step")
        if coord_step is not None and not (math.isfinite(coord_step) and coord_step > 0):
            raise ValueError(
                f"coord_step of a series must be finite and above 0, not {coord_step!r}"
            )
        if coord_end is None and self.kind is SeriesKind.ENVELOPE:
            raise ValueError("an envelope series needs coord_end")
        if self.kind is not SeriesKind.ENVELOPE and coord_end is not None:
            raise ValueError(
                f"a {self.kind.value} series does not use coord_end, so it must be None"
            )
        if not needs_step:
            if coord_start != 0.0:
                raise ValueError(
                    f"a {self.kind.value} series does not use coord_start, so it must be 0"
                )
            if coord_step is not None:
                raise ValueError(
                    f"a {self.kind.value} series does not use coord_step, so it must be None"
                )

        meta = _plain_meta(self.meta)
        self._check_coordinates(coord_start, coord_step, coord_end)

        # Each array is a read-only copy in native byte order, so that a change to the
        # caller's array does not change the series, the flag cannot be set again, and the
        # dtype of a round trip is the same. Each string is a plain `str` (not a subclass,
        # for example `np.str_`).
        keys = [str(key) for key in self.arrays]
        native = [a.astype(a.dtype.newbyteorder("="), copy=False) for a in self.arrays.values()]
        arrays = dict(zip(keys, _freeze(*native), strict=True))
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "unit", str(self.unit))
        object.__setattr__(self, "coord_unit", str(self.coord_unit))
        object.__setattr__(self, "arrays", FrozenDict(arrays))
        object.__setattr__(self, "coord_start", coord_start)
        object.__setattr__(self, "coord_step", coord_step)
        object.__setattr__(self, "coord_end", coord_end)
        object.__setattr__(self, "meta", FrozenDict(meta))

    def __reduce__(self) -> tuple[Any, ...]:
        """Rebuild the series with the constructor, so that a copy from `pickle` or
        `copy.deepcopy` is checked, and has read-only arrays and `FrozenDict`s."""
        return (
            type(self),
            (
                self.name,
                self.kind,
                self.unit,
                self.coord_unit,
                dict(self.arrays),
                self.coord_start,
                self.coord_step,
                self.coord_end,
                dict(self.meta),
            ),
        )

    def _check_coordinates(
        self, coord_start: float, coord_step: float | None, coord_end: float | None
    ) -> None:
        """Raise `ValueError` for a coordinate that is not finite or not in order. This is
        after each check of a type, so that a wrong type is a `TypeError` first."""
        if self.kind is SeriesKind.RUNS:
            _check_runs(self.arrays["start"], self.arrays["end"])
        if self.kind is SeriesKind.ENVELOPE:
            _check_envelope(self.arrays["min"], self.arrays["max"])
        if self.kind is SeriesKind.POINTS:
            _check_real("a points series", "coord", self.arrays["coord"])
        if self.kind not in (SeriesKind.SAMPLES, SeriesKind.ENVELOPE):
            return
        if not math.isfinite(coord_start):
            raise ValueError(
                f"coord_start of a {self.kind.value} series must be finite, not {coord_start!r}"
            )
        if self.kind is not SeriesKind.ENVELOPE:
            return
        assert coord_step is not None
        assert coord_end is not None
        if not math.isfinite(coord_end):
            raise ValueError(f"coord_end of an envelope series must be finite, not {coord_end!r}")
        n = self.arrays["min"].size
        if n == 0:
            # No bin and no float product, so there is no tolerance.
            if coord_end < coord_start:
                raise ValueError(
                    f"coord_end of an envelope series with no bin must not be below "
                    f"coord_start, but coord_end is {coord_end!r} and coord_start is "
                    f"{coord_start!r}"
                )
            return
        # `coord_end` is `n * coord_step` after `coord_start` when the last bin is full, and
        # the tolerance covers the rounding of a float product (for example `pns_total`, whose
        # `coord_end` and `coord_step` are `num_samples * dt_s` and `bin_samples * dt_s`). A
        # `coord_end` within the tolerance of a limit counts as equal to it: the lower limit
        # is not in the range, and the upper limit is.
        tolerance = 1e-9 * coord_step
        low = coord_start + (n - 1) * coord_step
        high = coord_start + n * coord_step
        if not coord_end > low + tolerance:
            raise ValueError(
                f"coord_end of an envelope series with {n} bins must be above "
                f"coord_start + (n - 1) * coord_step = {low!r}, so that the last bin is not "
                f"empty, not {coord_end!r}"
            )
        if not coord_end <= high + tolerance:
            raise ValueError(
                f"coord_end of an envelope series with {n} bins must not be above "
                f"coord_start + n * coord_step = {high!r}, not {coord_end!r}"
            )

    def to_obj(self) -> dict[str, Any]:
        """A dict of JSON values, with the keys `name`, `kind`, `unit`, `coord_unit`,
        `coord_start`, `coord_step`, `coord_end`, `meta` and `arrays`, in this order. `kind`
        is the value of the `SeriesKind`. `arrays` maps each name to `encode_array`, in the
        order of `arrays`. A float of `meta` that is not finite is a string (module
        docstring). An int stays an int and a bool stays a bool.
        `json.dumps(obj, allow_nan=False)` writes the dict."""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "unit": self.unit,
            "coord_unit": self.coord_unit,
            "coord_start": _float_to_json(self.coord_start),
            "coord_step": _float_to_json(self.coord_step),
            "coord_end": _float_to_json(self.coord_end),
            "meta": {
                k: _float_to_json(v) if isinstance(v, float) else v for k, v in self.meta.items()
            },
            "arrays": {key: encode_array(a) for key, a in self.arrays.items()},
        }

    @classmethod
    def from_obj(cls, obj: Any) -> Series:
        """The series of `to_obj`: `Series.from_obj(s.to_obj()) == s`, also after
        `json.dumps` and `json.loads`. An unknown key, a missing key, an unknown kind, or a
        bad value is a `ValueError`."""
        _check_keys(obj, _SERIES_KEYS, "a series")
        try:
            kind = SeriesKind(obj["kind"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"unknown kind {obj['kind']!r} in a series") from exc
        meta = obj["meta"]
        if not isinstance(meta, dict):
            raise ValueError('"meta" of a series must be a JSON object')  # noqa: TRY004
        meta = {
            k: float(v) if isinstance(v, str) and v in _NON_FINITE else v for k, v in meta.items()
        }
        arrays = obj["arrays"]
        if not isinstance(arrays, dict):
            raise ValueError('"arrays" of a series must be a JSON object')  # noqa: TRY004
        try:
            return cls(
                name=obj["name"],
                kind=kind,
                unit=obj["unit"],
                coord_unit=obj["coord_unit"],
                arrays={key: decode_array(d) for key, d in arrays.items()},
                coord_start=_float_from_json(obj["coord_start"], '"coord_start"'),
                coord_step=_float_from_json(obj["coord_step"], '"coord_step"'),
                coord_end=_float_from_json(obj["coord_end"], '"coord_end"'),
                meta=meta,
            )
        except TypeError as exc:
            # A value of a wrong type is a `ValueError` too: a caller of `from_obj` catches
            # one type for a bad object.
            raise ValueError(f"a bad series: {exc}") from exc


_SERIES_KEYS = (
    "name",
    "kind",
    "unit",
    "coord_unit",
    "coord_start",
    "coord_step",
    "coord_end",
    "meta",
    "arrays",
)


def encode_array(a: np.ndarray) -> dict[str, Any]:
    """The array `a` as `{"dtype", "length", "data"}`: the same dict as `encode_tables` of
    pulseq-reports gives for one array. `dtype` is the name of the numpy dtype (for example
    "float32"), `length` is the number of elements, and `data` is the little-endian bytes of
    the array, gzipped (level 6) and base64-encoded as ASCII text. The gzip header has no
    time stamp and a fixed OS byte, so one array always gives the same text, whatever its
    byte order.

    `a` must be a one-dimensional numpy array of a bool, integer, float or complex dtype,
    else `TypeError` or `ValueError`."""
    _check_array("a", a)
    little = a.astype(a.dtype.newbyteorder("<"), copy=False)
    # mtime=0: no time stamp in header bytes 4-7 (else a rebuilt report differs).
    # With mtime=0, Python 3.12 lets zlib write the header, and zlib's OS byte (byte 9)
    # depends on the platform (3 on Linux, 19 on macOS). Set it to 255 ("unknown"), the
    # value that Python's own gzip header uses. No decoder reads either.
    compressed = gzip.compress(little.tobytes(), compresslevel=6, mtime=0)
    compressed = compressed[:9] + b"\xff" + compressed[10:]
    return {
        "dtype": a.dtype.name,
        "length": int(a.size),
        "data": base64.b64encode(compressed).decode("ascii"),
    }


def decode_array(d: Any) -> np.ndarray:
    """The array of `encode_array`: a new writable array in native byte order. `d` must be a
    dict with exactly the keys `dtype`, `length` and `data`, else `ValueError`. It is also a
    `ValueError` when `dtype` is not the name of a bool, integer, float or complex numpy
    dtype, when `data` does not decode, or when `length` is not the number of elements in
    the decoded bytes, or when `length` items need more than `sys.maxsize` bytes. It
    decompresses at most `length` items and one byte more. A bool byte other than 0 is
    True."""
    _check_keys(d, _ARRAY_KEYS, "an encoded array")
    name, length, data = d["dtype"], d["length"], d["data"]
    try:
        dtype = np.dtype(name)
    except TypeError as exc:
        raise ValueError(f"unknown dtype {name!r} in an encoded array") from exc
    if dtype.kind not in _KINDS or dtype.name != name:
        raise ValueError(
            f"the dtype of an encoded array must be a numeric or bool dtype, not {name!r}"
        )
    if not isinstance(length, int) or isinstance(length, bool) or length < 0:
        raise ValueError(
            f'"length" of an encoded array must be an integer of 0 or more, not {length!r}'
        )
    if not isinstance(data, str):
        raise ValueError('"data" of an encoded array must be a string')  # noqa: TRY004
    # One byte more than `length` items, so that more data than `length` shows, and no more
    # than that is decompressed (wbits=31 reads the gzip format).
    limit = length * dtype.itemsize
    if limit + 1 > sys.maxsize:  # `limit + 1` is the `max_length` of `decompress` below
        raise ValueError(f'"length" of an encoded array is too large: {length}')
    try:
        decompressor = zlib.decompressobj(wbits=31)
        raw = decompressor.decompress(base64.b64decode(data, validate=True), limit + 1)
    except (binascii.Error, zlib.error, ValueError) as exc:
        raise ValueError(f'"data" of an encoded array does not decode: {exc}') from exc
    if len(raw) > limit:
        raise ValueError(
            f'"length" of an encoded array is {length}, but its data has more than {limit} '
            f"bytes of {name}"
        )
    if not decompressor.eof:
        raise ValueError('"data" of an encoded array does not decode: the stream is not complete')
    if decompressor.unused_data:
        raise ValueError('"data" of an encoded array does not decode: there are bytes after it')
    count, rest = divmod(len(raw), dtype.itemsize)
    if rest or count != length:
        raise ValueError(
            f'"length" of an encoded array is {length}, but its data has {len(raw)} bytes of {name}'
        )
    a = np.frombuffer(raw, dtype=dtype.newbyteorder("<"))
    if dtype.kind == "b":
        # A byte other than 0 or 1 is True, so one array always gives the same text.
        return a.view(np.uint8) != 0
    return a.astype(dtype)


def _float_to_json(x: float | None) -> float | str | None:
    if x is None or math.isfinite(x):
        return x
    return "nan" if math.isnan(x) else ("inf" if x > 0 else "-inf")


def _float_from_json(x: Any, where: str) -> float | None:
    if x is None:
        return None
    if isinstance(x, str) and x in _NON_FINITE:
        return float(x)
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"{where} must be a number or null, not {x!r}")  # noqa: TRY004
    try:
        return float(x)
    except OverflowError as exc:
        raise ValueError(f"{where} is too large for a float: {x!r}") from exc


def _check_keys(obj: Any, keys: tuple[str, ...], what: str) -> None:
    """Raise `ValueError` when `obj` is not an object with exactly `keys`."""
    if not isinstance(obj, dict):
        raise ValueError(f"{what} must be a JSON object")  # noqa: TRY004
    for key in obj:
        if key not in keys:
            raise ValueError(f"unknown key {key!r} in {what}")
    for key in keys:
        if key not in obj:
            raise ValueError(f"missing key {key!r} in {what}")
