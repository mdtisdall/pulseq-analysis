"""`Series`: the JSON-ready form of an analysis value (design section 4.2).

A series is a named set of one-dimensional numpy arrays with a kind that says what the
arrays mean:

- `SAMPLES`: `value[k]` is at the time `t0_s + k * step_s`.
- `ENVELOPE`: `min[i]` and `max[i]` are the least and the greatest value in the bin
  `[t0_s + i * step_s, t0_s + (i + 1) * step_s)`. The last bin stops at `end_s`.
- `POINTS`: `value[k]` is at the time `time_s[k]`. The times need not be regular.
- `RUNS`: a boolean that is true from `start_s[k]` to `end_s[k]`, and false elsewhere.

`Series.to_obj` gives a dict that `json.dumps(obj, allow_nan=False)` writes, and
`Series.from_obj` reads it back. Each array is one dict `{"dtype", "length", "data"}`
(`encode_array`, `decode_array`), where `data` is the little-endian bytes of the array,
gzipped and base64-encoded. This is the same text as `encode_tables` of pulseq-reports
(`pulseq_reports.diagram_data`, commit `a322517`), so a report can put the text into its
page with no new encoding. The encoding is deterministic: one array always gives the same
text.

The JSON form cannot hold a float that is not finite (strict JSON). In an array, such a
float is in the bytes. In a float field or in `meta`, `to_obj` writes infinity and "not a
number" as the strings "inf", "-inf" and "nan", and `from_obj` reads them back.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import math
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

# The strings that stand for a float that is not finite in the JSON form.
_NON_FINITE = ("inf", "-inf", "nan")

# The `dtype.kind` letters of the arrays that a series holds: bool, signed integer,
# unsigned integer, float and complex.
_KINDS = "biufc"

_ARRAY_KEYS = ("dtype", "length", "data")


class SeriesKind(Enum):
    SAMPLES = "samples"  # value[k] at t0_s + k * step_s
    ENVELOPE = "envelope"  # min[i] and max[i] of the bin [t0_s + i*step_s, t0_s + (i+1)*step_s);
    # the last bin stops at end_s
    POINTS = "points"  # value[k] at time_s[k] (not regular, for example one for each block)
    RUNS = "runs"  # a boolean that is true from start_s[k] to end_s[k], else false


# The arrays that each kind must have. `SAMPLES`, `POINTS` and `RUNS` can have more
# arrays; `ENVELOPE` cannot.
_NECESSARY = {
    SeriesKind.SAMPLES: ("value",),
    SeriesKind.ENVELOPE: ("min", "max"),
    SeriesKind.POINTS: ("time_s", "value"),
    SeriesKind.RUNS: ("start_s", "end_s"),
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


def _real(x: Any, what: str) -> float:
    """`x` as a float; `TypeError` when `x` is not a number (a bool is not)."""
    if isinstance(x, (bool, np.bool_)) or not isinstance(x, (int, float, np.integer, np.floating)):
        raise TypeError(f"{what} must be a number, not {x!r}")
    try:
        return float(x)
    except OverflowError as exc:
        raise ValueError(f"{what} is too large for a float: {x!r}") from exc


def _plain_meta(meta: Any) -> dict[str, str | int | float | bool | None]:
    """A new dict with the values of `meta`, in the same order, as plain `str`, `int`,
    `float`, `bool` or None. It raises by the rules of `Finding.data` (pulseq-checks)."""
    if not isinstance(meta, Mapping):
        raise TypeError(f"the meta of a series must be a mapping, not {meta!r}")
    out: dict[str, str | int | float | bool | None] = {}
    for key, value in meta.items():
        if not isinstance(key, str):
            raise TypeError(f"a key of the meta of a series must be a string, not {key!r}")
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
        out[key] = value
    return out


@dataclass(frozen=True, eq=False)
class Series:
    """One named series of an analysis value (design section 4.2).

    `name` is a short, stable name, as `Finding.code` is: for example "pns_total". `unit` is
    the unit of the values, for example "1" (a fraction), "mT/m" or "s". `arrays` maps a
    name to a one-dimensional numpy array of a bool, integer, float or complex dtype. All
    arrays of one series have the same length. The kind says which arrays are necessary:

    - `SAMPLES`: `value`, and more arrays of the same length (for example one for each
      gradient axis).
    - `ENVELOPE`: `min` and `max`, and no other array.
    - `POINTS`: `time_s` and `value`, and more arrays of the same length.
    - `RUNS`: `start_s` and `end_s`, and more arrays of the same length (a value of each run).

    The other arrays can be in any order. `t0_s` and `step_s` (above 0, finite) give the
    time of a sample or of a bin, and `end_s` gives the end of the last bin. `SAMPLES` and
    `ENVELOPE` need `step_s`, and `ENVELOPE` needs `end_s`. A field that the kind does not
    use must have its default: `end_s` None for `SAMPLES`, and `t0_s` 0.0 with `step_s` and
    `end_s` None for `POINTS` and `RUNS`. So each kind has one form.

    `meta` holds the values of the series by name, for a machine: only JSON
    scalars. A string value of `meta` cannot be "inf", "-inf" or "nan", because the JSON form
    writes a float that is not finite as one of these strings (as for `Finding.data` in
    pulseq-checks).

    A series raises `TypeError` for a value of a wrong type and `ValueError` for a wrong
    value. It keeps a new dict for `arrays` and one for `meta`, so a change to the caller's
    dict does not change the series. It keeps a copy of each array, in native byte order, and
    the copy is read-only. The caller's own array stays writable, and a change to it does not
    change the series. An int in `t0_s`, `step_s` or `end_s` becomes a float.

    `==` is true when the fields are the same, the array names are the same and in the same
    order, and each pair of arrays has the same dtype and is equal by
    `np.array_equal(a, b, equal_nan=True)`. A float of a field or of `meta` that is NaN
    equals a NaN. The order of the keys of `meta` does not matter. A series is not hashable.
    """

    name: str
    kind: SeriesKind
    unit: str
    arrays: Mapping[str, np.ndarray]
    t0_s: float = 0.0  # SAMPLES and ENVELOPE
    step_s: float | None = None  # SAMPLES and ENVELOPE
    end_s: float | None = None  # ENVELOPE
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

        t0_s = _real(self.t0_s, "t0_s of a series")
        step_s = None if self.step_s is None else _real(self.step_s, "step_s of a series")
        end_s = None if self.end_s is None else _real(self.end_s, "end_s of a series")
        needs_step = self.kind in (SeriesKind.SAMPLES, SeriesKind.ENVELOPE)
        if step_s is None and needs_step:
            raise ValueError(f"a {self.kind.value} series needs step_s")
        if step_s is not None and not (math.isfinite(step_s) and step_s > 0):
            raise ValueError(f"step_s of a series must be finite and above 0, not {step_s!r}")
        if end_s is None and self.kind is SeriesKind.ENVELOPE:
            raise ValueError("an envelope series needs end_s")
        if self.kind is not SeriesKind.ENVELOPE and end_s is not None:
            raise ValueError(f"a {self.kind.value} series does not use end_s, so it must be None")
        if not needs_step:
            if t0_s != 0.0:
                raise ValueError(f"a {self.kind.value} series does not use t0_s, so it must be 0")
            if step_s is not None:
                raise ValueError(
                    f"a {self.kind.value} series does not use step_s, so it must be None"
                )

        meta = _plain_meta(self.meta)

        # Each array is a copy in native byte order, so that a change to the caller's array
        # does not change the series, and the dtype of a round trip is the same.
        arrays = {}
        for key, a in self.arrays.items():
            copy = np.array(a, dtype=a.dtype.newbyteorder("="), copy=True)
            copy.flags.writeable = False
            arrays[key] = copy
        object.__setattr__(self, "arrays", arrays)
        object.__setattr__(self, "t0_s", t0_s)
        object.__setattr__(self, "step_s", step_s)
        object.__setattr__(self, "end_s", end_s)
        object.__setattr__(self, "meta", meta)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Series):
            return NotImplemented
        if (self.name, self.kind, self.unit) != (other.name, other.kind, other.unit):
            return False
        if not (
            _same_value(self.t0_s, other.t0_s)
            and _same_value(self.step_s, other.step_s)
            and _same_value(self.end_s, other.end_s)
        ):
            return False
        if self.meta.keys() != other.meta.keys():
            return False
        if not all(_same_value(v, other.meta[k]) for k, v in self.meta.items()):
            return False
        if list(self.arrays) != list(other.arrays):
            return False
        return all(
            a.dtype == b.dtype and np.array_equal(a, b, equal_nan=True)
            for a, b in zip(self.arrays.values(), other.arrays.values(), strict=True)
        )

    __hash__ = None  # type: ignore[assignment]

    def to_obj(self) -> dict[str, Any]:
        """A dict of JSON values, with the keys `name`, `kind`, `unit`, `t0_s`, `step_s`,
        `end_s`, `meta` and `arrays`, in this order. `kind` is the value of the `SeriesKind`.
        `arrays` maps each name to `encode_array`, in the order of `arrays`. A float field or
        a float of `meta` that is not finite is a string (module docstring). An int stays an
        int and a bool stays a bool. `json.dumps(obj, allow_nan=False)` writes the dict."""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "unit": self.unit,
            "t0_s": _float_to_json(self.t0_s),
            "step_s": _float_to_json(self.step_s),
            "end_s": _float_to_json(self.end_s),
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
                arrays={key: decode_array(d) for key, d in arrays.items()},
                t0_s=_float_from_json(obj["t0_s"], '"t0_s"'),
                step_s=_float_from_json(obj["step_s"], '"step_s"'),
                end_s=_float_from_json(obj["end_s"], '"end_s"'),
                meta=meta,
            )
        except TypeError as exc:
            # A value of a wrong type is a `ValueError` too: a caller of `from_obj` catches
            # one type for a bad object.
            raise ValueError(f"a bad series: {exc}") from exc


_SERIES_KEYS = ("name", "kind", "unit", "t0_s", "step_s", "end_s", "meta", "arrays")


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
    the decoded bytes."""
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
    try:
        raw = gzip.decompress(base64.b64decode(data, validate=True))
    except (binascii.Error, OSError, EOFError, zlib.error, ValueError) as exc:
        raise ValueError(f'"data" of an encoded array does not decode: {exc}') from exc
    count, rest = divmod(len(raw), dtype.itemsize)
    if rest or count != length:
        raise ValueError(
            f'"length" of an encoded array is {length}, but its data has {len(raw)} bytes of {name}'
        )
    return np.frombuffer(raw, dtype=dtype.newbyteorder("<")).astype(dtype)


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
    return float(x)


def _same_value(a: Any, b: Any) -> bool:
    """True when `a` and `b` have the same type and are equal, where a NaN equals a NaN."""
    return type(a) is type(b) and (a == b or (a != a and b != b))  # noqa: PLR0124


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
