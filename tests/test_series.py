"""Tests for `series.py` (task 3.1 of `docs/plans/implementation.md`).

`Series` is the JSON-ready form of an analysis value (design section 4.2), and
`encode_array` writes an array in the form of `encode_tables` of pulseq-reports.
"""

import base64
import gzip
import json
from dataclasses import replace

import numpy as np
import pytest

from pulseq_analysis.series import Series, SeriesKind, decode_array, encode_array

_NON_FINITE = np.array([0.0, np.inf, -np.inf, np.nan, 1.5], dtype=np.float32)


def _samples(**overrides) -> Series:
    """A valid SAMPLES series, with the fields in `overrides` changed."""
    fields = {
        "name": "g",
        "kind": SeriesKind.SAMPLES,
        "unit": "mT/m",
        "arrays": {"value": np.arange(4, dtype=np.float32)},
        "step_s": 1e-5,
    }
    fields.update(overrides)
    return Series(**fields)


def _envelope() -> Series:
    return Series(
        name="pns_total",
        kind=SeriesKind.ENVELOPE,
        unit="1",
        arrays={
            "min": np.array([0.0, 0.1, 0.2], dtype=np.float32),
            "max": np.array([0.5, 0.6, 0.7], dtype=np.float32),
        },
        t0_s=0.0,
        step_s=0.006,
        end_s=0.0171,
        meta={"hardware": "example", "dt_s": 1e-5, "num_samples": 1710, "on_raster": True},
    )


def _points() -> Series:
    return Series(
        name="gx_max",
        kind=SeriesKind.POINTS,
        unit="mT/m",
        arrays={
            "time_s": np.array([0.0, 0.001, 0.0035]),
            "value": np.array([1.0, -2.0, 3.0]),
            "block": np.array([1, 2, 3], dtype=np.uint32),
        },
        meta={"axis": "x", "note": None},
    )


def _runs() -> Series:
    return Series(
        name="pns_above_1",
        kind=SeriesKind.RUNS,
        unit="1",
        arrays={
            "start_s": np.array([0.001, 0.01]),
            "end_s": np.array([0.002, 0.0125]),
            "num_samples": np.array([100, 250], dtype=np.int64),
        },
        meta={"threshold": 1.0},
    )


_ONE_OF_EACH_KIND = (
    pytest.param(_samples, id="samples"),
    pytest.param(_envelope, id="envelope"),
    pytest.param(_points, id="points"),
    pytest.param(_runs, id="runs"),
)


def _used_fields(kind: SeriesKind) -> dict:
    """The fields `step_s` and `end_s` that `kind` needs, with valid values."""
    if kind is SeriesKind.SAMPLES:
        return {"step_s": 1.0}
    if kind is SeriesKind.ENVELOPE:
        return {"step_s": 1.0, "end_s": 1.0}
    return {}


def _round_trip(s: Series) -> Series:
    """`s` after `to_obj`, strict JSON text and `from_obj`."""
    return Series.from_obj(json.loads(json.dumps(s.to_obj(), allow_nan=False)))


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        pytest.param({"name": 3}, TypeError, id="name-not-a-string"),
        pytest.param({"name": ""}, ValueError, id="name-empty"),
        pytest.param({"kind": "samples"}, TypeError, id="kind-not-a-SeriesKind"),
        pytest.param({"unit": None}, TypeError, id="unit-not-a-string"),
        pytest.param({"step_s": None}, ValueError, id="step-missing"),
        pytest.param({"step_s": 0.0}, ValueError, id="step-zero"),
        pytest.param({"step_s": -1e-5}, ValueError, id="step-negative"),
        pytest.param({"step_s": float("inf")}, ValueError, id="step-infinite"),
        pytest.param({"step_s": float("nan")}, ValueError, id="step-nan"),
        pytest.param({"step_s": "1e-5"}, TypeError, id="step-not-a-number"),
        pytest.param({"step_s": True}, TypeError, id="step-a-bool"),
        pytest.param({"t0_s": "0"}, TypeError, id="t0-not-a-number"),
        pytest.param({"t0_s": None}, TypeError, id="t0-none"),
    ],
)
def test_series_refuses_a_bad_field(overrides, error):
    """Each bad name, kind, unit, `t0_s` or `step_s` raises `TypeError` or `ValueError`."""
    with pytest.raises(error):
        _samples(**overrides)


@pytest.mark.parametrize(
    ("kind", "arrays", "overrides"),
    [
        pytest.param(SeriesKind.SAMPLES, {"value": np.zeros(3)}, {"end_s": 1.0}, id="samples-end"),
        pytest.param(
            SeriesKind.POINTS,
            {"time_s": np.zeros(3), "value": np.zeros(3)},
            {"t0_s": 1.0},
            id="points-t0",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"time_s": np.zeros(3), "value": np.zeros(3)},
            {"t0_s": float("nan")},
            id="points-t0-nan",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"time_s": np.zeros(3), "value": np.zeros(3)},
            {"step_s": 1.0},
            id="points-step",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"time_s": np.zeros(3), "value": np.zeros(3)},
            {"end_s": 1.0},
            id="points-end",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start_s": np.zeros(3), "end_s": np.zeros(3)},
            {"t0_s": 1.0},
            id="runs-t0",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start_s": np.zeros(3), "end_s": np.zeros(3)},
            {"step_s": 1.0},
            id="runs-step",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start_s": np.zeros(3), "end_s": np.zeros(3)},
            {"end_s": 1.0},
            id="runs-end",
        ),
    ],
)
def test_series_refuses_a_field_that_the_kind_does_not_use(kind, arrays, overrides):
    """A SAMPLES series with `end_s`, and a POINTS or RUNS series with `t0_s` other than 0,
    `step_s` or `end_s`, raise `ValueError`. The series with the defaults is valid."""
    Series(name="s", kind=kind, unit="1", arrays=arrays, **_used_fields(kind))
    fields = _used_fields(kind) | overrides
    with pytest.raises(ValueError, match="does not use"):
        Series(name="s", kind=kind, unit="1", arrays=arrays, **fields)


def test_envelope_refuses_a_missing_end():
    """An ENVELOPE series without `end_s` raises `ValueError`."""
    s = _envelope()
    with pytest.raises(ValueError, match="end_s"):
        Series(
            name=s.name,
            kind=s.kind,
            unit=s.unit,
            arrays=s.arrays,
            step_s=s.step_s,
        )


@pytest.mark.parametrize(
    ("kind", "arrays", "error"),
    [
        pytest.param(SeriesKind.SAMPLES, {}, ValueError, id="samples-no-value"),
        pytest.param(SeriesKind.SAMPLES, {"x": np.zeros(3)}, ValueError, id="samples-only-x"),
        pytest.param(SeriesKind.ENVELOPE, {"min": np.zeros(3)}, ValueError, id="envelope-no-max"),
        pytest.param(
            SeriesKind.ENVELOPE,
            {"min": np.zeros(3), "max": np.zeros(3), "extra": np.zeros(3)},
            ValueError,
            id="envelope-extra-array",
        ),
        pytest.param(SeriesKind.POINTS, {"value": np.zeros(3)}, ValueError, id="points-no-time"),
        pytest.param(SeriesKind.POINTS, {"time_s": np.zeros(3)}, ValueError, id="points-no-value"),
        pytest.param(SeriesKind.RUNS, {"start_s": np.zeros(3)}, ValueError, id="runs-no-end"),
        pytest.param(SeriesKind.RUNS, {"end_s": np.zeros(3)}, ValueError, id="runs-no-start"),
        pytest.param(SeriesKind.SAMPLES, [np.zeros(3)], TypeError, id="arrays-not-a-mapping"),
        pytest.param(SeriesKind.SAMPLES, {1: np.zeros(3)}, TypeError, id="key-not-a-string"),
        pytest.param(SeriesKind.SAMPLES, {"value": [1.0, 2.0]}, TypeError, id="list-not-an-array"),
        pytest.param(
            SeriesKind.SAMPLES, {"value": np.zeros((2, 3))}, ValueError, id="two-dimensional"
        ),
        pytest.param(SeriesKind.SAMPLES, {"value": np.float32(1.0)}, TypeError, id="numpy-scalar"),
        pytest.param(
            SeriesKind.SAMPLES, {"value": np.array(1.0)}, ValueError, id="zero-dimensional"
        ),
        pytest.param(
            SeriesKind.SAMPLES, {"value": np.array(["a", "b"])}, ValueError, id="string-dtype"
        ),
        pytest.param(
            SeriesKind.SAMPLES, {"value": np.array([1, 2], dtype=object)}, ValueError, id="object"
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.array([1, 2], dtype="datetime64[s]")},
            ValueError,
            id="datetime-dtype",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.zeros(3), "other": np.zeros(4)},
            ValueError,
            id="samples-lengths-differ",
        ),
        pytest.param(
            SeriesKind.ENVELOPE,
            {"min": np.zeros(3), "max": np.zeros(4)},
            ValueError,
            id="envelope-lengths-differ",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start_s": np.zeros(3), "end_s": np.zeros(2)},
            ValueError,
            id="runs-lengths-differ",
        ),
    ],
)
def test_series_refuses_bad_arrays(kind, arrays, error):
    """Each missing necessary array, extra array of an ENVELOPE, array that is not a
    one-dimensional numpy array of a numeric or bool dtype, and pair of arrays of two lengths
    raises `TypeError` or `ValueError`."""
    with pytest.raises(error):
        Series(name="s", kind=kind, unit="1", arrays=arrays, **_used_fields(kind))


@pytest.mark.parametrize(
    ("meta", "error"),
    [
        pytest.param([("a", 1)], TypeError, id="not-a-mapping"),
        pytest.param({1: "a"}, TypeError, id="key-not-a-string"),
        pytest.param({"a": [1, 2]}, TypeError, id="list-value"),
        pytest.param({"a": {"b": 1}}, TypeError, id="dict-value"),
        pytest.param({"a": np.int64(3)}, TypeError, id="numpy-int-value"),
        pytest.param({"a": np.float32(3.0)}, TypeError, id="numpy-float32-value"),
        pytest.param({"a": "inf"}, ValueError, id="string-inf"),
        pytest.param({"a": "-inf"}, ValueError, id="string-minus-inf"),
        pytest.param({"a": "nan"}, ValueError, id="string-nan"),
    ],
)
def test_series_refuses_bad_meta(meta, error):
    """Each `meta` that is not a mapping of strings to JSON scalars, and each string value
    "inf", "-inf" or "nan", raises `TypeError` or `ValueError`."""
    with pytest.raises(error):
        _samples(meta=meta)


def test_series_copies_arrays_and_meta():
    """A change to the caller's `arrays` dict, `meta` dict or array does not change the
    series, and the series keeps the order of the arrays of the caller."""
    value = np.arange(4, dtype=np.float32)
    arrays = {"value": value, "b": np.ones(4), "a": np.zeros(4)}
    meta = {"k": 1}
    s = _samples(arrays=arrays, meta=meta)
    arrays["extra"] = np.zeros(4)
    del arrays["b"]
    meta["k"] = 2
    meta["new"] = "x"
    value[0] = 99.0
    assert list(s.arrays) == ["value", "b", "a"]
    assert s.meta == {"k": 1}
    assert s.arrays["value"][0] == 0.0
    assert s.arrays is not arrays
    assert s.meta is not meta


def test_series_arrays_are_read_only_and_the_callers_array_is_not():
    """Each array of a series is read-only, and the caller's own array stays writable."""
    value = np.arange(4, dtype=np.float32)
    s = _samples(arrays={"value": value})
    assert not s.arrays["value"].flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        s.arrays["value"][0] = 1.0
    assert value.flags.writeable
    value[1] = 5.0
    assert s.arrays["value"][1] == 1.0


def test_series_keeps_native_byte_order():
    """An array of the other byte order is kept in native byte order, so a round trip gives
    an equal series."""
    s = _samples(arrays={"value": np.arange(4).astype(">f4")})
    assert s.arrays["value"].dtype == np.dtype("float32")
    assert _round_trip(s) == s


def test_series_equal_treats_nan_as_equal():
    """Two series with NaN in an array, in a float field and in `meta` are equal, and a
    series equals itself."""
    arrays = {"value": np.array([1.0, np.nan])}
    one = _samples(arrays=arrays, t0_s=float("nan"), meta={"m": float("nan")})
    two = _samples(arrays=dict(arrays), t0_s=float("nan"), meta={"m": float("nan")})
    same = one
    assert one == same
    assert one == two
    assert (one != two) is False


@pytest.mark.parametrize(
    "other",
    [
        pytest.param(
            lambda: _samples(arrays={"value": np.arange(4, dtype=np.float64)}), id="dtype"
        ),
        pytest.param(
            lambda: _samples(arrays={"value": np.arange(5, dtype=np.float32)}), id="length"
        ),
        pytest.param(
            lambda: _samples(arrays={"value": np.array([0, 1, 2, 4], dtype=np.float32)}),
            id="value",
        ),
        pytest.param(
            lambda: _samples(arrays={"value": np.array([0, 1, 2, np.nan], dtype=np.float32)}),
            id="nan-against-number",
        ),
        pytest.param(lambda: _samples(name="h"), id="name"),
        pytest.param(lambda: _samples(unit="T/m"), id="unit"),
        pytest.param(lambda: _samples(t0_s=1.0), id="t0"),
        pytest.param(lambda: _samples(step_s=2e-5), id="step"),
        pytest.param(lambda: _samples(meta={"a": 1}), id="meta"),
        pytest.param(
            lambda: Series(
                name="g",
                kind=SeriesKind.POINTS,
                unit="mT/m",
                arrays={
                    "time_s": np.zeros(4, dtype=np.float32),
                    "value": np.arange(4, dtype=np.float32),
                },
            ),
            id="kind",
        ),
    ],
)
def test_series_not_equal_for_a_different_field_or_array(other):
    """A series is not equal to one that differs in a dtype, a length, a value, a name, a
    unit, `t0_s`, `step_s`, `meta` or the kind, to NaN against a number, or to a value that is
    not a series."""
    s = _samples()
    assert s != other()
    assert s != "g"


def test_envelope_series_not_equal_for_a_different_end():
    """Two ENVELOPE series that differ only in `end_s` are not equal."""
    assert _envelope() != replace(_envelope(), end_s=0.02)


def test_series_equality_compares_the_order_of_the_arrays():
    """Two series with the same arrays in another order are not equal, and `meta` of the
    same keys in another order is equal."""
    a, b = np.zeros(3), np.ones(3)
    assert _samples(arrays={"value": a, "x": b}) != _samples(arrays={"x": b, "value": a})
    assert _samples(meta={"p": 1, "q": 2}) == _samples(meta={"q": 2, "p": 1})


def test_series_equality_compares_the_type_of_a_meta_value():
    """A `meta` value 1 is not equal to 1.0 or to True."""
    assert _samples(meta={"a": 1}) != _samples(meta={"a": 1.0})
    assert _samples(meta={"a": 1}) != _samples(meta={"a": True})


def test_series_is_not_hashable():
    """`hash` of a series raises `TypeError`."""
    with pytest.raises(TypeError, match="unhashable"):
        hash(_samples())


@pytest.mark.parametrize("make", _ONE_OF_EACH_KIND)
def test_series_round_trip_for_each_kind(make):
    """`from_obj` of the strict JSON text of `to_obj` gives a series equal to the original,
    for one series of each kind, and a second `to_obj` gives the same dict."""
    s = make()
    back = _round_trip(s)
    assert back == s
    assert list(back.arrays) == list(s.arrays)
    assert back.to_obj() == s.to_obj()


def test_series_round_trip_of_two_million_float32_values():
    """A SAMPLES series of 2 x 10^6 float32 values, with a second array of int16 values,
    gives an equal series after the round trip, and the arrays keep their dtype."""
    rng = np.random.default_rng(0)
    value = rng.standard_normal(2_000_000).astype(np.float32)
    count = rng.integers(-1000, 1000, size=2_000_000, dtype=np.int16)
    s = _samples(arrays={"value": value, "count": count}, step_s=1e-5)
    back = _round_trip(s)
    assert back == s
    assert back.arrays["value"].dtype == np.float32
    assert back.arrays["count"].dtype == np.int16
    assert np.array_equal(back.arrays["value"], value)


def test_series_round_trip_of_values_that_are_not_finite():
    """A series with infinity and NaN in an array, in `t0_s` and `end_s`, and in `meta`
    gives an equal series after the round trip, and `json.dumps(allow_nan=False)` accepts
    the object."""
    s = Series(
        name="x",
        kind=SeriesKind.ENVELOPE,
        unit="1",
        arrays={"min": _NON_FINITE, "max": _NON_FINITE[::-1]},
        t0_s=float("-inf"),
        step_s=0.5,
        end_s=float("nan"),
        meta={"a": float("inf"), "b": float("-inf"), "c": float("nan"), "d": 1.5, "e": "nan?"},
    )
    obj = s.to_obj()
    json.dumps(obj, allow_nan=False)
    assert (obj["t0_s"], obj["end_s"]) == ("-inf", "nan")
    assert obj["meta"] == {"a": "inf", "b": "-inf", "c": "nan", "d": 1.5, "e": "nan?"}
    back = _round_trip(s)
    assert back == s
    assert np.isinf(back.t0_s)
    assert np.isnan(back.end_s)
    assert back.meta["a"] == float("inf")
    assert np.isnan(back.meta["c"])


def test_to_obj_keys_and_types():
    """`to_obj` has the keys `name`, `kind`, `unit`, `t0_s`, `step_s`, `end_s`, `meta` and
    `arrays` in this order. `kind` is the string value, an int and a bool of `meta` stay an
    int and a bool, a float stays a float, and `arrays` has the order of the series."""
    obj = _envelope().to_obj()
    assert list(obj) == ["name", "kind", "unit", "t0_s", "step_s", "end_s", "meta", "arrays"]
    assert obj["kind"] == "envelope"
    assert obj["step_s"] == 0.006
    assert type(obj["meta"]["num_samples"]) is int
    assert type(obj["meta"]["on_raster"]) is bool
    assert type(obj["meta"]["dt_s"]) is float
    assert list(obj["arrays"]) == ["min", "max"]
    assert list(obj["arrays"]["min"]) == ["dtype", "length", "data"]
    # A field that a kind does not use has its default: null for `step_s`.
    assert _runs().to_obj()["step_s"] is None
    text = json.dumps(obj, allow_nan=False)
    back = json.loads(text)["meta"]
    assert type(back["num_samples"]) is int
    assert type(back["on_raster"]) is bool


def _good_obj() -> dict:
    return _envelope().to_obj()


def _with(key, value) -> dict:
    obj = _good_obj()
    obj[key] = value
    return obj


def _without(key) -> dict:
    obj = _good_obj()
    del obj[key]
    return obj


@pytest.mark.parametrize(
    "obj",
    [
        pytest.param([1, 2], id="not-an-object"),
        pytest.param(_with("extra", 1), id="unknown-key"),
        pytest.param(_without("unit"), id="missing-key"),
        pytest.param(_without("arrays"), id="missing-arrays"),
        pytest.param(_with("kind", "lines"), id="unknown-kind"),
        pytest.param(_with("kind", ["samples"]), id="kind-not-a-string"),
        pytest.param(_with("name", ""), id="empty-name"),
        pytest.param(_with("name", 3), id="name-not-a-string"),
        pytest.param(_with("unit", 3), id="unit-not-a-string"),
        pytest.param(_with("step_s", 0.0), id="step-zero"),
        pytest.param(_with("step_s", "fast"), id="step-a-string"),
        pytest.param(_with("step_s", None), id="step-null"),
        pytest.param(_with("end_s", None), id="end-null"),
        pytest.param(_with("t0_s", None), id="t0-null"),
        pytest.param(_with("t0_s", True), id="t0-a-bool"),
        pytest.param(_with("meta", [1]), id="meta-not-an-object"),
        pytest.param(_with("meta", {"a": [1]}), id="meta-value-a-list"),
        pytest.param(_with("arrays", []), id="arrays-not-an-object"),
        pytest.param(_with("arrays", {"min": 3, "max": 4}), id="array-not-an-object"),
        pytest.param(_with("arrays", {}), id="no-arrays"),
    ],
)
def test_from_obj_refuses(obj):
    """`from_obj` raises `ValueError`, and no other error, for an object that is not a dict,
    an unknown key, a missing key, an unknown kind, a bad value of any field, and a bad
    array."""
    with pytest.raises(ValueError):
        Series.from_obj(obj)


def test_encode_array_gives_the_same_text_each_time():
    """One array encoded two times gives the same dict, a copy gives the same dict, and an
    array of the other byte order gives the same `data`."""
    a = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
    assert encode_array(a) == encode_array(a)
    assert encode_array(a) == encode_array(a.copy())
    big = a.astype(">f4")
    assert big.dtype != a.dtype
    assert encode_array(big) == encode_array(a)
    assert encode_array(a[::2]) == encode_array(a[::2].copy())
    # The gzip header has no time stamp (bytes 4 to 7) and the OS byte is 255.
    raw = base64.b64decode(encode_array(a)["data"])
    assert raw[4:8] == b"\x00\x00\x00\x00"
    assert raw[9] == 0xFF
    assert gzip.decompress(raw) == a.tobytes()


@pytest.mark.parametrize(
    ("array", "expected"),
    [
        pytest.param(
            np.array([0.0, 1.0, -2.5, 3.25, 1e-6, np.inf, -np.inf, np.nan], dtype=np.float32),
            {
                "dtype": "float32",
                "length": 8,
                "data": "H4sIAAAAAAAA/2NgAIEGewYGhQMMDAEOe83bTIH8eiD+z8BwoB4ARUNtQiAAAAA=",
            },
            id="float32",
        ),
        pytest.param(
            np.arange(5, dtype=np.int64),
            {
                "dtype": "int64",
                "length": 5,
                "data": "H4sIAAAAAAAA/2NggABGKM0EpZmhNAuUBgAcTo9sKAAAAA==",
            },
            id="int64",
        ),
    ],
)
def test_encode_array_gives_the_fixed_text(array, expected):
    """`encode_array` gives the text that `encode_tables` of pulseq-reports gave for the
    same array. The expected text was made with `encode_tables` in
    `src/pulseq_reports/diagram_data.py` of pulseq-reports at commit `a322517`. The array
    also decodes to itself."""
    assert encode_array(array) == expected
    assert np.array_equal(decode_array(expected), array, equal_nan=True)


@pytest.mark.parametrize(
    "dtype",
    ["bool", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64"]
    + ["float16", "float32", "float64", "complex64", "complex128"],
)
def test_decode_array_gives_back_the_array(dtype):
    """`decode_array` of `encode_array` gives an equal array of the same dtype in native
    byte order, that is writable and not the original, for each dtype; and for an empty
    array."""
    rng = np.random.default_rng(1)
    a = (rng.random(33) * 50).astype(dtype)
    for original in (a, a[:0]):
        back = decode_array(encode_array(original))
        assert back.dtype == original.dtype
        assert back.dtype.isnative
        assert back.flags.writeable
        assert np.array_equal(back, original)
        assert back is not original


@pytest.mark.parametrize(
    "array",
    [
        pytest.param([1.0, 2.0], id="a-list"),
        pytest.param(np.zeros((2, 2)), id="two-dimensional"),
        pytest.param(np.array(["a"]), id="string-dtype"),
        pytest.param(np.array([None], dtype=object), id="object-dtype"),
    ],
)
def test_encode_array_refuses_a_bad_array(array):
    """`encode_array` raises for a value that is not a one-dimensional numpy array of a
    numeric or bool dtype."""
    with pytest.raises((TypeError, ValueError)):
        encode_array(array)


def _encoded(**overrides) -> dict:
    d = encode_array(np.arange(4, dtype=np.float32))
    d.update(overrides)
    return d


def _gzip_text(raw: bytes) -> str:
    return base64.b64encode(gzip.compress(raw)).decode("ascii")


@pytest.mark.parametrize(
    "d",
    [
        pytest.param("text", id="not-a-dict"),
        pytest.param({"dtype": "float32", "length": 4}, id="missing-key"),
        pytest.param(_encoded(extra=1), id="unknown-key"),
        pytest.param(_encoded(length=5), id="length-too-large"),
        pytest.param(_encoded(length=3), id="length-too-small"),
        pytest.param(_encoded(length=-4), id="length-negative"),
        pytest.param(_encoded(length=4.0), id="length-a-float"),
        pytest.param(_encoded(length=True), id="length-a-bool"),
        pytest.param(_encoded(dtype="object"), id="dtype-object"),
        pytest.param(_encoded(dtype="datetime64[s]"), id="dtype-datetime"),
        pytest.param(_encoded(dtype="str32"), id="dtype-string"),
        pytest.param(_encoded(dtype="no-such-dtype"), id="dtype-unknown"),
        pytest.param(_encoded(dtype="f4"), id="dtype-not-the-name"),
        pytest.param(_encoded(dtype=32), id="dtype-not-a-string"),
        pytest.param(_encoded(data=3), id="data-not-a-string"),
        pytest.param(_encoded(data="not base64!"), id="data-not-base64"),
        pytest.param(_encoded(data="AAAA"), id="data-not-gzip"),
        pytest.param(_encoded(data=_encoded()["data"][:-8]), id="data-cut-short"),
        pytest.param(_encoded(data=_gzip_text(b"\x00" * 15)), id="bytes-not-a-whole-number"),
        pytest.param(_encoded(data=_gzip_text(b"\x00" * 20)), id="data-longer-than-length"),
        pytest.param(_encoded(data=_gzip_text(b"\x00" * 12)), id="data-shorter-than-length"),
    ],
)
def test_decode_array_refuses(d):
    """`decode_array` raises `ValueError` for a value that is not a dict, an unknown key, a
    missing key, a `length` that is not the decoded byte count divided by the item size, a
    dtype that is not a numeric or bool dtype name, and data that does not decode."""
    with pytest.raises(ValueError):
        decode_array(d)
