"""Tests for `series.py` (task 3.1 of `docs/plans/implementation.md`).

`Series` is the JSON-ready form of an analysis value (design section 4.2), and
`encode_array` writes an array in the form of `encode_tables` of pulseq-reports.
"""

import base64
import copy
import gzip
import json
import pickle
import re
import sys
import zlib
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from scale_sequences import build_repeating
from synthetic import (
    EXAMPLE_HW,
    GAMMA_1H,
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    loaded,
    raster_4us_sequence,
    spin_echo_sequence,
)

from pulseq_analysis._equality import FrozenDict, values_equal
from pulseq_analysis.analyses import GRADIENT_SPECTRUM, PNS_SAFE_LEVELS
from pulseq_analysis.series import Series, SeriesKind, decode_array, encode_array

_NON_FINITE_MIN = np.array([-np.inf, 0.0, np.nan, 1.5, -np.inf], dtype=np.float32)
_NON_FINITE_MAX = np.array([np.inf, np.inf, np.nan, 1.5, 0.0], dtype=np.float32)


def _samples(**overrides) -> Series:
    """A valid SAMPLES series, with the fields in `overrides` changed."""
    fields = {
        "name": "g",
        "kind": SeriesKind.SAMPLES,
        "unit": "mT/m",
        "coord_unit": "s",
        "arrays": {"value": np.arange(4, dtype=np.float32)},
        "coord_step": 1e-5,
    }
    fields.update(overrides)
    return Series(**fields)


def _envelope() -> Series:
    return Series(
        name="pns_total",
        kind=SeriesKind.ENVELOPE,
        unit="1",
        coord_unit="s",
        arrays={
            "min": np.array([0.0, 0.1, 0.2], dtype=np.float32),
            "max": np.array([0.5, 0.6, 0.7], dtype=np.float32),
        },
        coord_start=0.0,
        coord_step=0.006,
        coord_end=0.0171,
        meta={"hardware": "example", "dt_s": 1e-5, "num_samples": 1710, "on_raster": True},
    )


def _bins(n: int, **overrides) -> Series:
    """A valid ENVELOPE series of `n` bins (`coord_start` 0, `coord_step` 1, `coord_end` `n`),
    with the fields in `overrides` changed."""
    fields = {
        "name": "e",
        "kind": SeriesKind.ENVELOPE,
        "unit": "1",
        "coord_unit": "s",
        "arrays": {"min": np.zeros(n), "max": np.ones(n)},
        "coord_step": 1.0,
        "coord_end": float(n),
    }
    fields.update(overrides)
    return Series(**fields)


def _runs_of(start, end) -> Series:
    """A RUNS series with the arrays `start` and `end`."""
    return Series(
        name="r",
        kind=SeriesKind.RUNS,
        unit="1",
        coord_unit="s",
        arrays={"start": np.asarray(start), "end": np.asarray(end)},
    )


def _points() -> Series:
    return Series(
        name="gx_max",
        kind=SeriesKind.POINTS,
        unit="mT/m",
        coord_unit="s",
        arrays={
            "coord": np.array([0.0, 0.001, 0.0035]),
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
        coord_unit="s",
        arrays={
            "start": np.array([0.001, 0.01]),
            "end": np.array([0.002, 0.0125]),
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
    """The fields `coord_step` and `coord_end` that `kind` needs, with valid values."""
    if kind is SeriesKind.SAMPLES:
        return {"coord_step": 1.0}
    if kind is SeriesKind.ENVELOPE:
        return {"coord_step": 1.0, "coord_end": 1.0}
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
        pytest.param({"coord_unit": None}, TypeError, id="coord-unit-not-a-string"),
        pytest.param({"coord_unit": ""}, ValueError, id="coord-unit-empty"),
        pytest.param({"coord_step": None}, ValueError, id="coord-step-missing"),
        pytest.param({"coord_step": 0.0}, ValueError, id="coord-step-zero"),
        pytest.param({"coord_step": -1e-5}, ValueError, id="coord-step-negative"),
        pytest.param({"coord_step": float("inf")}, ValueError, id="coord-step-infinite"),
        pytest.param({"coord_step": float("nan")}, ValueError, id="coord-step-nan"),
        pytest.param({"coord_step": "1e-5"}, TypeError, id="coord-step-not-a-number"),
        pytest.param({"coord_step": True}, TypeError, id="coord-step-a-bool"),
        pytest.param({"coord_start": "0"}, TypeError, id="coord-start-not-a-number"),
        pytest.param({"coord_start": None}, TypeError, id="coord-start-none"),
    ],
)
def test_series_refuses_a_bad_field(overrides, error):
    """Each bad name, kind, unit, `coord_unit`, `coord_start` or `coord_step` raises
    `TypeError` or `ValueError`."""
    with pytest.raises(error):
        _samples(**overrides)


def test_a_coordinate_field_accepts_a_numpy_float_and_a_fraction():
    """`coord_start`, `coord_step` and `coord_end` take any real number that is not a bool:
    a numpy float and a `Fraction` become a `float`."""
    s = _samples(coord_start=np.float32(0.5), coord_step=Fraction(1, 4))
    e = _samples(
        kind=SeriesKind.ENVELOPE,
        arrays={"min": np.zeros(2), "max": np.ones(2)},
        coord_step=1.0,
        coord_end=np.float64(2.0),
    )

    assert (s.coord_start, s.coord_step) == (0.5, 0.25)
    assert type(s.coord_start) is float
    assert type(s.coord_step) is float
    assert e.coord_end == 2.0
    assert type(e.coord_end) is float


@pytest.mark.parametrize(
    ("kind", "arrays", "overrides"),
    [
        pytest.param(
            SeriesKind.SAMPLES, {"value": np.zeros(3)}, {"coord_end": 1.0}, id="samples-coord-end"
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"coord": np.zeros(3), "value": np.zeros(3)},
            {"coord_start": 1.0},
            id="points-coord-start",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"coord": np.zeros(3), "value": np.zeros(3)},
            {"coord_start": float("nan")},
            id="points-coord-start-nan",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"coord": np.zeros(3), "value": np.zeros(3)},
            {"coord_step": 1.0},
            id="points-coord-step",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"coord": np.zeros(3), "value": np.zeros(3)},
            {"coord_end": 1.0},
            id="points-coord-end",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start": np.zeros(3), "end": np.zeros(3)},
            {"coord_start": 1.0},
            id="runs-coord-start",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start": np.zeros(3), "end": np.zeros(3)},
            {"coord_step": 1.0},
            id="runs-coord-step",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start": np.zeros(3), "end": np.zeros(3)},
            {"coord_end": 1.0},
            id="runs-coord-end",
        ),
    ],
)
def test_series_refuses_a_field_that_the_kind_does_not_use(kind, arrays, overrides):
    """A SAMPLES series with `coord_end`, and a POINTS or RUNS series with `coord_start` other
    than 0, `coord_step` or `coord_end`, raise `ValueError`. The series with the defaults is
    valid."""
    Series(name="s", kind=kind, unit="1", coord_unit="s", arrays=arrays, **_used_fields(kind))
    fields = _used_fields(kind) | overrides
    with pytest.raises(ValueError, match="does not use"):
        Series(name="s", kind=kind, unit="1", coord_unit="s", arrays=arrays, **fields)


def test_envelope_refuses_a_missing_end():
    """An ENVELOPE series without `coord_end` raises `ValueError`."""
    s = _envelope()
    with pytest.raises(ValueError, match="coord_end"):
        Series(
            name=s.name,
            kind=s.kind,
            unit=s.unit,
            coord_unit=s.coord_unit,
            arrays=s.arrays,
            coord_step=s.coord_step,
        )


_INF, _NAN = float("inf"), float("nan")


@pytest.mark.parametrize("kind", [SeriesKind.SAMPLES, SeriesKind.ENVELOPE])
@pytest.mark.parametrize("coord_start", [_INF, -_INF, _NAN], ids=["inf", "minus-inf", "nan"])
def test_series_refuses_a_coord_start_that_is_not_finite(kind, coord_start):
    """A SAMPLES or ENVELOPE series with an infinite or NaN `coord_start` raises
    `ValueError`. The finite value is valid."""
    if kind is SeriesKind.SAMPLES:
        _samples(coord_start=-3.0)
        with pytest.raises(ValueError, match="coord_start.*finite"):
            _samples(coord_start=coord_start)
    else:
        _bins(2, coord_start=-3.0, coord_end=-1.0)
        with pytest.raises(ValueError, match="coord_start.*finite"):
            _bins(2, coord_start=coord_start, coord_end=2.0)


@pytest.mark.parametrize("coord_end", [_INF, -_INF, _NAN], ids=["inf", "minus-inf", "nan"])
def test_envelope_refuses_a_coord_end_that_is_not_finite(coord_end):
    """An ENVELOPE series with an infinite or NaN `coord_end` raises `ValueError`, also with
    no bin."""
    for n in (0, 3):
        with pytest.raises(ValueError, match="coord_end.*finite"):
            _bins(n, coord_end=coord_end)


@pytest.mark.parametrize(
    ("n", "coord_start", "coord_step", "coord_end"),
    [
        # The lower limit is `coord_start + (n - 1) * coord_step`: the end of the bin before
        # the last one. The tolerance is 1e-9 * coord_step.
        pytest.param(3, 0.0, 1.0, 2.0, id="at-the-lower-limit"),
        pytest.param(3, 0.0, 1.0, 2.0 + 0.5e-9, id="within-the-tolerance-of-the-lower-limit"),
        pytest.param(3, 0.0, 1.0, 1.5, id="below-the-lower-limit"),
        pytest.param(3, 0.0, 1.0, 0.0, id="at-coord-start"),
        pytest.param(3, 0.0, 1.0, -1.0, id="below-coord-start"),
        pytest.param(1, 0.0, 1.0, 0.0, id="one-bin-at-coord-start"),
        pytest.param(1, 0.0, 1.0, -0.5, id="one-bin-below-coord-start"),
        pytest.param(3, -2.0, 0.25, -1.5, id="negative-start-at-the-lower-limit"),
        pytest.param(3, -2.0, 0.25, -1.75, id="negative-start-below-the-lower-limit"),
        # The upper limit is `coord_start + n * coord_step`: the end of a full last bin.
        pytest.param(3, 0.0, 1.0, 3.1, id="above-the-upper-limit"),
        pytest.param(3, 0.0, 1.0, 3.0 + 2e-9, id="beyond-the-tolerance-of-the-upper-limit"),
        pytest.param(3, 0.0, 1.0, 3.000001, id="a-little-above-the-upper-limit"),
        pytest.param(3, -2.0, 0.25, -1.2, id="negative-start-above-the-upper-limit"),
        pytest.param(3, 0.0, 1e-5, 3e-5 * (1 + 1e-6), id="small-step-above-the-upper-limit"),
        pytest.param(3, 0.0, 1e-5, 2e-5 * (1 + 1e-10), id="small-step-within-tolerance-of-lower"),
    ],
)
def test_envelope_refuses_a_coord_end_out_of_range(n, coord_start, coord_step, coord_end):
    """An ENVELOPE series of `n` bins raises `ValueError` when `coord_end` is not above
    `coord_start + (n - 1) * coord_step` by more than the tolerance `1e-9 * coord_step`
    (the last bin would be empty), and when it is above `coord_start + n * coord_step` by more
    than the tolerance (the last bin would be longer than a step)."""
    with pytest.raises(ValueError, match="coord_end"):
        _bins(n, coord_start=coord_start, coord_step=coord_step, coord_end=coord_end)


@pytest.mark.parametrize(
    ("n", "coord_start", "coord_step", "coord_end"),
    [
        pytest.param(3, 0.0, 1.0, 3.0, id="at-the-upper-limit"),
        pytest.param(3, 0.0, 1.0, 3.0 + 0.5e-9, id="within-the-tolerance-of-the-upper-limit"),
        pytest.param(3, 0.0, 1.0, 2.5, id="inside-the-last-bin"),
        pytest.param(3, 0.0, 1.0, 2.01, id="just-above-the-lower-limit"),
        pytest.param(3, 0.0, 1.0, 2.0 + 2e-9, id="beyond-the-tolerance-of-the-lower-limit"),
        pytest.param(1, 0.0, 1.0, 1.0, id="one-full-bin"),
        pytest.param(1, 0.0, 1.0, 0.001, id="one-short-bin"),
        pytest.param(3, -2.0, 0.25, -1.25, id="negative-start-at-the-upper-limit"),
        pytest.param(3, -2.0, 0.25, -1.4, id="negative-start-inside-the-last-bin"),
        pytest.param(0, 0.0, 1.0, 0.0, id="no-bin-at-coord-start"),
        pytest.param(0, 0.0, 1.0, 7.0, id="no-bin-above-coord-start"),
        pytest.param(0, -2.0, 0.25, -2.0, id="no-bin-negative-start"),
    ],
)
def test_envelope_accepts_a_coord_end_in_range(n, coord_start, coord_step, coord_end):
    """An ENVELOPE series of `n` bins is valid when `coord_end` is above
    `coord_start + (n - 1) * coord_step` by more than the tolerance and is at most
    `coord_start + n * coord_step` plus the tolerance. With no bin, it is valid for
    `coord_end >= coord_start`."""
    s = _bins(n, coord_start=coord_start, coord_step=coord_step, coord_end=coord_end)
    assert s.coord_end == coord_end
    assert _round_trip(s) == s


@pytest.mark.parametrize(
    ("n", "coord_start", "coord_step"),
    [
        pytest.param(3, 0.0, 1.0, id="unit-step"),
        pytest.param(3, -2.0, 0.25, id="negative-start"),
        pytest.param(1, 0.0, 1.0, id="one-bin"),
    ],
)
def test_envelope_coord_end_limits_are_exact_at_the_tolerance(n, coord_start, coord_step):
    """For an ENVELOPE series of `n` bins, a `coord_end` that is `1e-9 * coord_step` above
    the lower limit `coord_start + (n - 1) * coord_step` raises `ValueError`, and a `coord_end`
    that is the tolerance above the upper limit `coord_start + n * coord_step` is valid. The
    floats are the sums that the check makes, so `coord_end` is equal to the limit that it
    is compared with. The next float above each of the two is on the other side of the check:
    valid above the lower limit and `ValueError` above the upper limit."""
    tolerance = 1e-9 * coord_step
    low = coord_start + (n - 1) * coord_step
    high = coord_start + n * coord_step
    with pytest.raises(ValueError, match="must be above"):
        _bins(n, coord_start=coord_start, coord_step=coord_step, coord_end=low + tolerance)
    nudged = np.nextafter(low + tolerance, np.inf)
    assert nudged > low + tolerance
    _bins(n, coord_start=coord_start, coord_step=coord_step, coord_end=float(nudged))
    s = _bins(n, coord_start=coord_start, coord_step=coord_step, coord_end=high + tolerance)
    assert s.coord_end == high + tolerance
    with pytest.raises(ValueError, match="must not be above"):
        _bins(
            n,
            coord_start=coord_start,
            coord_step=coord_step,
            coord_end=float(np.nextafter(high + tolerance, np.inf)),
        )


def test_envelope_with_no_bin_refuses_a_coord_end_below_coord_start():
    """An ENVELOPE series with no bin raises `ValueError` for `coord_end < coord_start`, also
    for a `coord_end` that is below by less than the tolerance of the other cases (there is no
    float product, so no tolerance)."""
    for coord_start, coord_end in ((0.0, -1.0), (1.0, 1.0 - 1e-12), (-2.0, -2.5)):
        with pytest.raises(ValueError, match="coord_end"):
            _bins(0, coord_start=coord_start, coord_end=coord_end)


@pytest.mark.parametrize("which", ["start", "end"])
@pytest.mark.parametrize("bad", [_INF, -_INF, _NAN], ids=["inf", "minus-inf", "nan"])
@pytest.mark.parametrize("dtype", [np.float64, np.float32], ids=["float64", "float32"])
def test_runs_refuses_a_start_or_end_that_is_not_finite(which, bad, dtype):
    """A RUNS series with an infinite or NaN value in `start` or in `end` raises
    `ValueError`, for float64 and float32."""
    arrays = {"start": np.array([0.0, 2.0], dtype=dtype), "end": np.array([1.0, 3.0], dtype=dtype)}
    _runs_of(**arrays)
    arrays[which][1] = bad
    with pytest.raises(ValueError, match=f"{which}.*finite"):
        _runs_of(**arrays)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param([0.0, 5.0], [1.0, 4.0], id="float64"),
        pytest.param(np.array([0.0, 5.0], dtype=np.float32), [1.0, 4.0], id="float32"),
        pytest.param([3, 5], [1, 6], id="int64"),
        pytest.param(
            np.array([3, 5], dtype=np.uint8), np.array([4, 4], dtype=np.uint8), id="uint8"
        ),
        pytest.param([0.0, 5.0], [-1.0, 6.0], id="first-run"),
        pytest.param([1.0], [1.0 - 1e-12], id="a-little-before"),
    ],
)
def test_runs_refuses_an_end_before_the_start(start, end):
    """A RUNS series with `end[k] < start[k]` for one run raises `ValueError`, for float and
    for integer dtypes. There is no tolerance."""
    with pytest.raises(ValueError, match="end before it starts"):
        _runs_of(start, end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param([1.0, 5.0], [1.0, 5.0], id="all-equal"),
        pytest.param([1.0, 5.0], [1.0, 7.5], id="one-equal"),
        pytest.param([3, 5], [3, 9], id="int64"),
        pytest.param(np.array([0.5], dtype=np.float32), np.array([0.5], dtype=np.float32), id="f4"),
        pytest.param(np.array([-2], dtype=np.int8), np.array([-2], dtype=np.int8), id="negative"),
        pytest.param([], [], id="no-run"),
    ],
)
def test_runs_accepts_an_end_at_or_after_the_start(start, end):
    """A RUNS series with `end[k] >= start[k]` for each run is valid: also `end == start`, an
    integer dtype and no run."""
    s = _runs_of(start, end)
    assert _round_trip(s) == s


@pytest.mark.parametrize("which", ["start", "end"])
@pytest.mark.parametrize("dtype", [np.bool_, np.complex128], ids=["bool", "complex128"])
def test_runs_refuses_a_start_or_end_of_a_bool_or_complex_dtype(which, dtype):
    """A RUNS series whose `start` or `end` has a bool or complex dtype raises `ValueError`:
    a run is an interval of a real coordinate."""
    arrays = {"start": np.array([0.0, 2.0]), "end": np.array([1.0, 3.0])}
    arrays[which] = arrays[which].astype(dtype)
    with pytest.raises(ValueError, match=f"{which}.*integer or float"):
        _runs_of(**arrays)


def test_a_wrong_type_is_a_type_error_before_a_coordinate_that_is_not_finite():
    """A `coord_end` that is not a number is a `TypeError`, and a bad `meta` is a `TypeError`
    even when `coord_start` is not finite."""
    with pytest.raises(TypeError, match="coord_end"):
        _bins(2, coord_end="2")
    with pytest.raises(TypeError, match="meta"):
        _samples(coord_start=_NAN, meta=[1])


_PNS_CASES = [
    pytest.param((), None, id="no-thresholds"),
    pytest.param((GAMMA_1H,), None, id="limit"),
    pytest.param((0.1 * GAMMA_1H, 0.01 * GAMMA_1H), 3.7e-3, id="two-thresholds-bin-3.7-ms"),
    pytest.param((0.1 * GAMMA_1H,), 1e-4, id="one-threshold-bin-0.1-ms"),
]

_SEQUENCES = [
    pytest.param(spin_echo_sequence, id="spin_echo"),
    pytest.param(lambda: spin_echo_sequence("after"), id="spin_echo_after"),
    pytest.param(gre_sequence, id="gre"),
    pytest.param(empty_sequence, id="empty"),
    pytest.param(arbitrary_gradient_sequence, id="arbitrary_gradient"),
    pytest.param(border_sequence, id="border"),
    pytest.param(raster_4us_sequence, id="raster_4us"),
    pytest.param(lambda: build_repeating(10), id="build_repeating_10"),
]


@pytest.mark.parametrize(("thresholds", "bin_s"), _PNS_CASES)
@pytest.mark.parametrize("builder", _SEQUENCES)
def test_the_series_of_pns_safe_levels_are_valid(builder, thresholds, bin_s):
    """Each series of `pns.safe.levels` (`pns_total`, and `pns_above_<k>` for each threshold)
    for each synthetic sequence and for `build_repeating(10)`, with and without thresholds and
    with bins that divide the level and bins that do not, is a valid `Series` (the constructor
    does not raise: the `coord_end` of `pns_total`, `num_samples * dt_s`, is in the range of its
    `coord_step`, `bin_samples * dt_s`, with the tolerance), and it equals the series that
    `from_obj` reads from the strict JSON text of its `to_obj`. A sequence with no gradient
    gives no series."""
    snap = loaded(builder())
    kwargs = {} if bin_s is None else {"bin_s": bin_s}
    levels = PNS_SAFE_LEVELS.compute(
        snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=thresholds, **kwargs
    )

    series = PNS_SAFE_LEVELS.to_series(levels)

    if levels.reason is not None:
        assert series == ()
        return
    assert [s.name for s in series] == ["pns_total"] + [
        f"pns_above_{k}" for k in range(len(thresholds))
    ]
    for s in series:
        assert _round_trip(s) == s


@pytest.mark.parametrize("builder", _SEQUENCES)
def test_the_series_of_gradient_spectrum_is_valid(builder):
    """The series of `gradient.spectrum` for each synthetic sequence and for
    `build_repeating(10)` is a valid `Series` that equals the series that `from_obj` reads from
    its `to_obj`. A sequence with no gradient gives no series."""
    snap = loaded(builder())

    series = GRADIENT_SPECTRUM.to_series(GRADIENT_SPECTRUM.compute(snap))

    for s in series:
        assert Series.from_obj(s.to_obj()) == s
    assert len(series) == (0 if builder is empty_sequence else 1)


@pytest.mark.parametrize(
    ("kind", "arrays", "error", "message"),
    [
        pytest.param(
            SeriesKind.SAMPLES, {}, ValueError, "needs the array 'value'", id="samples-no-value"
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"x": np.zeros(3)},
            ValueError,
            "needs the array 'value'",
            id="samples-only-x",
        ),
        pytest.param(
            SeriesKind.ENVELOPE,
            {"min": np.zeros(3)},
            ValueError,
            "needs the array 'max'",
            id="envelope-no-max",
        ),
        pytest.param(
            SeriesKind.ENVELOPE,
            {"min": np.zeros(3), "max": np.zeros(3), "extra": np.zeros(3)},
            ValueError,
            "has only the arrays 'min' and 'max', not 'extra'",
            id="envelope-extra-array",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"value": np.zeros(3)},
            ValueError,
            "needs the array 'coord'",
            id="points-no-coord",
        ),
        pytest.param(
            SeriesKind.POINTS,
            {"coord": np.zeros(3)},
            ValueError,
            "needs the array 'value'",
            id="points-no-value",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start": np.zeros(3)},
            ValueError,
            "needs the array 'end'",
            id="runs-no-end",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"end": np.zeros(3)},
            ValueError,
            "needs the array 'start'",
            id="runs-no-start",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            [np.zeros(3)],
            TypeError,
            "arrays of a series must be a mapping",
            id="arrays-not-a-mapping",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {1: np.zeros(3)},
            TypeError,
            "key of the arrays of a series must be a string",
            id="key-not-a-string",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": [1.0, 2.0]},
            TypeError,
            "must be a numpy array, not list",
            id="list-not-an-array",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.zeros((2, 3))},
            ValueError,
            "must be one-dimensional, not 2-dimensional",
            id="two-dimensional",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.float32(1.0)},
            TypeError,
            "must be a numpy array, not float32",
            id="numpy-scalar",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.array(1.0)},
            ValueError,
            "must be one-dimensional, not 0-dimensional",
            id="zero-dimensional",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.array(["a", "b"])},
            ValueError,
            "must have a numeric or bool dtype",
            id="string-dtype",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.array([1, 2], dtype=object)},
            ValueError,
            "must have a numeric or bool dtype",
            id="object",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.array([1, 2], dtype="datetime64[s]")},
            ValueError,
            "must have a numeric or bool dtype",
            id="datetime-dtype",
        ),
        pytest.param(
            SeriesKind.SAMPLES,
            {"value": np.zeros(3), "other": np.zeros(4)},
            ValueError,
            "must have one length",
            id="samples-lengths-differ",
        ),
        pytest.param(
            SeriesKind.ENVELOPE,
            {"min": np.zeros(3), "max": np.zeros(4)},
            ValueError,
            "must have one length",
            id="envelope-lengths-differ",
        ),
        pytest.param(
            SeriesKind.RUNS,
            {"start": np.zeros(3), "end": np.zeros(2)},
            ValueError,
            "must have one length",
            id="runs-lengths-differ",
        ),
    ],
)
def test_series_refuses_bad_arrays(kind, arrays, error, message):
    """Each missing necessary array, extra array of an ENVELOPE, array that is not a
    one-dimensional numpy array of a numeric or bool dtype, and pair of arrays of two lengths
    raises `TypeError` or `ValueError` with the message of its own check. An ENVELOPE case
    has a `coord_end` that is valid for its arrays, so the check of `coord_end` does not
    refuse it."""
    fields = _used_fields(kind)
    if kind is SeriesKind.ENVELOPE:
        fields["coord_end"] = float(next(iter(arrays.values())).size)
    with pytest.raises(error, match=message):
        Series(name="s", kind=kind, unit="1", coord_unit="s", arrays=arrays, **fields)


@pytest.mark.parametrize(
    ("low", "high", "message"),
    [
        pytest.param(
            np.zeros(2, dtype=complex),
            np.ones(2, dtype=complex),
            "must have an integer or float",
            id="complex",
        ),
        pytest.param(
            np.zeros(2, dtype=bool),
            np.ones(2, dtype=bool),
            "must have an integer or float",
            id="bool",
        ),
        pytest.param(
            np.zeros(2),
            np.ones(2, dtype=complex),
            "'max' of an envelope series must have an",
            id="complex-max",
        ),
        pytest.param(
            np.zeros(2, dtype=np.float32),
            np.ones(2),
            "must have one dtype, not float32 and float64",
            id="two-float-dtypes",
        ),
        pytest.param(
            np.zeros(2, dtype=np.int32),
            np.ones(2),
            "must have one dtype, not int32 and float64",
            id="int-and-float",
        ),
        pytest.param(
            np.array([0.0, 2.0]),
            np.array([1.0, 1.0]),
            "min[1] is 2.0 and max[1] is 1.0",
            id="min-above-max",
        ),
        pytest.param(
            np.array([0, 2]), np.array([1, 1]), "min[1] is 2 and max[1] is 1", id="int-min-above"
        ),
        pytest.param(
            np.array([np.inf]), np.array([-np.inf]), "min[0] is inf", id="infinities-reversed"
        ),
    ],
)
def test_envelope_refuses_bad_min_and_max(low, high, message):
    """An ENVELOPE with a complex or bool `min` or `max`, with two dtypes for `min` and `max`
    (also an integer and a float), or with `min[i] > max[i]` (also for integers and for
    infinities) raises `ValueError` with the message of its own check."""
    with pytest.raises(ValueError, match=re.escape(message)):
        _bins(low.size, arrays={"min": low, "max": high})


@pytest.mark.parametrize(
    ("low", "high"),
    [
        pytest.param(np.array([np.nan, 0.0]), np.array([1.0, np.nan]), id="nan-in-each"),
        pytest.param(np.array([np.nan]), np.array([np.nan]), id="nan-in-both"),
        pytest.param(np.array([1.0, 2.0]), np.array([1.0, 2.0]), id="min-equals-max"),
        pytest.param(np.array([0, 1], dtype=np.uint8), np.array([1, 1], dtype=np.uint8), id="uint"),
        pytest.param(np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32), id="empty"),
    ],
)
def test_envelope_accepts_a_nan_and_min_equal_to_max(low, high):
    """An ENVELOPE accepts `min[i]` or `max[i]` that is NaN (the check of the order is for the
    bins where neither is NaN), `min[i] == max[i]`, integer arrays and empty arrays."""
    s = _bins(low.size, arrays={"min": low, "max": high})
    assert _round_trip(s) == s


@pytest.mark.parametrize("dtype", [complex, bool])
def test_points_refuses_a_coord_of_a_complex_or_bool_dtype(dtype):
    """A POINTS series with a `coord` array of a complex or bool dtype raises `ValueError`."""
    with pytest.raises(ValueError, match="'coord' of a points series must have an integer or"):
        Series(
            name="p",
            kind=SeriesKind.POINTS,
            unit="1",
            coord_unit="s",
            arrays={"coord": np.zeros(2, dtype=dtype), "value": np.zeros(2)},
        )


@pytest.mark.parametrize("dtype", [np.int32, np.uint8, np.float32, np.float64])
def test_points_accepts_a_coord_that_is_not_finite_or_not_a_float64(dtype):
    """A POINTS series accepts a `coord` of an integer or float dtype, and for a float dtype
    also a value that is not finite."""
    coord = np.array([0, 1], dtype=dtype)
    if np.dtype(dtype).kind == "f":
        coord[1] = np.inf
    s = Series(
        name="p",
        kind=SeriesKind.POINTS,
        unit="1",
        coord_unit="s",
        arrays={"coord": coord, "value": np.zeros(2)},
    )
    assert _round_trip(s) == s


@pytest.mark.parametrize(
    ("meta", "error"),
    [
        pytest.param([("a", 1)], TypeError, id="not-a-mapping"),
        pytest.param({1: "a"}, TypeError, id="key-not-a-string"),
        pytest.param({"a": [1, 2]}, TypeError, id="list-value"),
        pytest.param({"a": {"b": 1}}, TypeError, id="dict-value"),
        pytest.param({"a": np.complex128(3)}, TypeError, id="numpy-complex-value"),
        pytest.param({"a": np.datetime64("2020-01-01")}, TypeError, id="numpy-datetime-value"),
        pytest.param({"a": np.array([1.0])}, TypeError, id="numpy-array-value"),
        pytest.param({"a": "inf"}, ValueError, id="string-inf"),
        pytest.param({"a": "-inf"}, ValueError, id="string-minus-inf"),
        pytest.param({"a": "nan"}, ValueError, id="string-nan"),
    ],
)
def test_series_refuses_bad_meta(meta, error):
    """Each `meta` that is not a mapping of strings to JSON scalars (a numpy complex, a numpy
    datetime and a numpy array are not scalars of a bool, integer or float dtype), and each
    string value "inf", "-inf" or "nan", raises `TypeError` or `ValueError`."""
    with pytest.raises(error):
        _samples(meta=meta)


def test_series_meta_makes_a_numpy_float64_a_plain_float():
    """A `np.float64` in `meta` becomes a `float` (a `np.float64` is a subclass of `float`),
    so the series equals the series with the same value as a `float`, and its JSON round trip
    gives the same series."""
    s = _samples(meta={"a": np.float64(1.5)})
    assert type(s.meta["a"]) is float
    assert s == _samples(meta={"a": 1.5})
    assert _round_trip(s) == s
    assert type(_round_trip(s).meta["a"]) is float


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(np.float32(1.5), 1.5, id="float32"),
        pytest.param(np.float16(0.5), 0.5, id="float16"),
        pytest.param(np.float64(1.5), 1.5, id="float64"),
        pytest.param(np.float32("nan"), float("nan"), id="float32-nan"),
        pytest.param(np.int64(3), 3, id="int64"),
        pytest.param(np.int8(-3), -3, id="int8"),
        pytest.param(np.uint32(7), 7, id="uint32"),
        pytest.param(np.bool_(True), True, id="bool"),
        pytest.param(np.bool_(False), False, id="bool-false"),
    ],
)
def test_series_meta_makes_a_numpy_scalar_a_python_scalar(value, expected):
    """A numpy scalar of a bool, integer or float dtype in `meta` is stored as a Python
    `bool`, `int` or `float` of the exact type (also a NaN), so the series equals the series
    made with the Python scalar and its JSON round trip is equal."""
    s = _samples(meta={"a": value})
    assert type(s.meta["a"]) is type(expected)
    assert values_equal(s, _samples(meta={"a": expected}))
    assert _round_trip(s) == s


def test_series_stores_a_str_subclass_as_a_str():
    """A `np.str_` as the name, unit, coord_unit, key of `arrays`, key of `meta` or value of
    `meta` is stored as a plain `str`, and the JSON round trip gives an equal series."""
    s = Series(
        name=np.str_("g"),
        kind=SeriesKind.SAMPLES,
        unit=np.str_("mT/m"),
        coord_unit=np.str_("s"),
        arrays={np.str_("value"): np.arange(4.0)},
        coord_step=1e-5,
        meta={np.str_("k"): np.str_("v")},
    )
    strings = [s.name, s.unit, s.coord_unit, *s.arrays, *s.meta, *s.meta.values()]
    assert [type(x) for x in strings] == [str] * 6
    assert _round_trip(s) == s


@pytest.mark.parametrize("copier", [copy.deepcopy, lambda s: pickle.loads(pickle.dumps(s))])
@pytest.mark.parametrize("make", _ONE_OF_EACH_KIND)
def test_a_copy_of_a_series_is_equal_and_read_only(make, copier):
    """A series from `copy.deepcopy` or from `pickle`, of each kind, equals the original and
    has read-only arrays whose flag cannot be set, and a `FrozenDict` for `arrays` and for
    `meta`."""
    s = make()
    c = copier(s)
    assert c is not s
    assert c == s
    for d in (c.arrays, c.meta):
        assert type(d) is FrozenDict
        with pytest.raises(TypeError):
            d["new"] = 1
    for a in c.arrays.values():
        assert not a.flags.writeable
        with pytest.raises(ValueError, match="cannot set WRITEABLE"):
            a.flags.writeable = True


def test_series_rebuilds_a_copy_with_the_constructor():
    """`Series.__reduce__` gives the class and the fields, so the copy is made by the
    constructor: the same arguments give an equal series, and an argument that is changed to
    a bad value raises `ValueError` (a copy from a damaged state is refused, and not made
    invalid)."""
    s = _envelope()
    rebuild, args = s.__reduce__()
    assert rebuild is Series
    assert rebuild(*args) == s
    bad_step = (*args[:5], args[5], -1.0, *args[7:])
    with pytest.raises(ValueError, match="coord_step"):
        rebuild(*bad_step)
    bad_arrays = {"min": np.ones(3, dtype=np.float32), "max": np.zeros(3, dtype=np.float32)}
    with pytest.raises(ValueError, match="must not be above"):
        rebuild(*args[:4], bad_arrays, *args[5:])


@pytest.mark.parametrize(
    "dtype",
    ["bool", "int8", "uint16", "int64", "float16", "float32", "float64", "complex64", "complex128"],
)
def test_series_arrays_cannot_be_made_writable(dtype):
    """The flag `writeable` of an array of a series cannot be set to True: it raises
    `ValueError`. This holds for each dtype, also with no element, and the arrays keep their
    dtype and values."""
    original = np.arange(4).astype(dtype)
    for a in (original, original[:0]):
        s = Series(
            name="p",
            kind=SeriesKind.POINTS,
            unit="1",
            coord_unit="s",
            arrays={"coord": np.zeros(a.size), "value": a},
        )
        frozen = s.arrays["value"]
        assert frozen.dtype == a.dtype
        assert np.array_equal(frozen, a)
        with pytest.raises(ValueError, match="cannot set WRITEABLE"):
            frozen.flags.writeable = True
        assert not frozen.flags.writeable


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


def test_series_dicts_cannot_be_changed():
    """A change of `arrays` or `meta` of a series (setitem, delitem, update, pop) raises
    `TypeError`, and the series is the same after it."""
    s = _samples(arrays={"value": np.arange(4.0)}, meta={"k": 1})
    before = s.to_obj()
    for d, key, value in ((s.arrays, "value", np.zeros(2)), (s.meta, "k", object())):
        with pytest.raises(TypeError):
            d[key] = value
        with pytest.raises(TypeError):
            del d[key]
        with pytest.raises(TypeError):
            d.update({key: value})
        with pytest.raises(TypeError):
            d.pop(key)
    assert s.to_obj() == before
    assert json.dumps(s.to_obj(), allow_nan=False)


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
    """Two series with NaN in an array and in `meta` are equal, and a series equals itself."""
    arrays = {"value": np.array([1.0, np.nan])}
    one = _samples(arrays=arrays, meta={"m": float("nan")})
    two = _samples(arrays=dict(arrays), meta={"m": float("nan")})
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
        pytest.param(lambda: _samples(coord_unit="Hz"), id="coord-unit"),
        pytest.param(lambda: _samples(coord_start=1.0), id="coord-start"),
        pytest.param(lambda: _samples(coord_step=2e-5), id="coord-step"),
        pytest.param(lambda: _samples(meta={"a": 1}), id="meta"),
    ],
)
def test_series_not_equal_for_a_different_field_or_array(other):
    """A series is not equal to one that differs in a dtype, a length, a value, a name, a
    unit, `coord_unit`, `coord_start`, `coord_step` or `meta`, to NaN against a number, or to a
    value that is not a series."""
    s = _samples()
    assert s != other()
    assert s != "g"


def test_series_not_equal_for_a_different_kind():
    """A POINTS series and a RUNS series with the same name, units, arrays and `meta` are not
    equal, so the kind alone makes two series differ."""
    arrays = {
        "coord": np.array([0.0, 1.0, 2.0]),
        "value": np.array([5.0, 6.0, 7.0]),
        "start": np.array([0.0, 1.0, 2.0]),
        "end": np.array([1.0, 2.0, 3.0]),
    }
    fields = {"name": "k", "unit": "1", "coord_unit": "s", "meta": {"a": 1}}
    points = Series(kind=SeriesKind.POINTS, arrays=arrays, **fields)
    runs = Series(kind=SeriesKind.RUNS, arrays=arrays, **fields)
    assert points != runs
    assert runs != points
    assert points == Series(kind=SeriesKind.POINTS, arrays=dict(arrays), **fields)


def test_envelope_series_not_equal_for_a_different_end():
    """Two ENVELOPE series that differ only in `coord_end` are not equal."""
    assert _envelope() != replace(_envelope(), coord_end=0.018)


def test_series_equality_compares_the_order_of_the_arrays():
    """Two series with the same arrays in another order are not equal."""
    a, b = np.zeros(3), np.ones(3)
    assert _samples(arrays={"value": a, "x": b}) != _samples(arrays={"x": b, "value": a})


def test_series_equality_compares_the_order_of_the_meta_keys():
    """Two series whose `meta` has the same items in another order are not equal, and the
    round trip of `to_obj` (also through JSON text) keeps the order and gives an equal
    series."""
    one = _samples(meta={"p": 1, "q": 2})
    two = _samples(meta={"q": 2, "p": 1})
    assert one != two
    assert (one == two) is False
    assert one == _samples(meta={"p": 1, "q": 2})
    for s in (one, two):
        assert list(Series.from_obj(s.to_obj()).meta) == list(s.meta)
        assert Series.from_obj(s.to_obj()) == s
        back = _round_trip(s)
        assert list(back.meta) == list(s.meta)
        assert back == s
    assert _round_trip(one) != two


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


def test_series_with_a_coordinate_other_than_time():
    """A spectrum, the frequency ranges where it is above a level, its peaks and a profile
    along a position round trip, and `to_obj` keeps `coord_unit`. The data are synthetic: a spectrum or a profile
    uses the same kinds as a time series."""
    spectrum = Series(
        name="spectrum",
        kind=SeriesKind.SAMPLES,
        unit="mT/m/√Hz",
        coord_unit="Hz",
        arrays={name: np.linspace(0.0, 1.0, 5) for name in ("value", "x", "y", "z")},
        coord_start=0.0,
        coord_step=500.0,
    )
    above = Series(
        name="spectrum_above",
        kind=SeriesKind.RUNS,
        unit="1",
        coord_unit="Hz",
        arrays={"start": np.array([540.0, 1030.0]), "end": np.array([640.0, 1250.0])},
    )
    peaks = Series(
        name="peaks",
        kind=SeriesKind.POINTS,
        unit="mT/m/√Hz",
        coord_unit="Hz",
        arrays={
            "coord": np.array([590.0, 1140.0]),
            "value": np.array([0.2, 0.7]),
            "relative": np.array([0.3, 1.0]),
        },
    )
    profile = Series(
        name="profile",
        kind=SeriesKind.SAMPLES,
        unit="1",
        coord_unit="m",
        arrays={
            "value": np.linspace(0.0, 1.0, 5),
            "phase": np.array([np.nan, 0.5, 1.0, 1.5, np.nan]),
            "a": np.linspace(0.0, 1.0, 5) * (1.0 + 0.5j),
        },
        coord_start=-0.01,
        coord_step=0.005,
        meta={"position": "select"},
    )
    for s, unit in ((spectrum, "Hz"), (above, "Hz"), (peaks, "Hz"), (profile, "m")):
        assert s.coord_unit == unit
        assert s.to_obj()["coord_unit"] == unit
        assert _round_trip(s) == s
    assert profile.arrays["a"].dtype == np.complex128
    assert _round_trip(profile).coord_start == -0.01


def test_series_round_trip_of_many_float32_values():
    """A SAMPLES series of 2000 float32 values, with a second array of int16 values,
    gives an equal series after the round trip, and the arrays keep their dtype."""
    rng = np.random.default_rng(0)
    value = rng.standard_normal(2000).astype(np.float32)
    count = rng.integers(-1000, 1000, size=2000, dtype=np.int16)
    s = _samples(arrays={"value": value, "count": count}, coord_step=1e-5)
    back = _round_trip(s)
    assert back == s
    assert back.arrays["value"].dtype == np.float32
    assert back.arrays["count"].dtype == np.int16
    assert np.array_equal(back.arrays["value"], value)


def test_series_round_trip_of_values_that_are_not_finite():
    """A series with infinity and NaN in an array and in `meta` gives an equal series after
    the round trip, and `json.dumps(allow_nan=False)` accepts the object. The coordinate
    fields are finite."""
    s = Series(
        name="x",
        kind=SeriesKind.ENVELOPE,
        unit="1",
        coord_unit="s",
        arrays={"min": _NON_FINITE_MIN, "max": _NON_FINITE_MAX},
        coord_start=-1.0,
        coord_step=0.5,
        coord_end=1.5,
        meta={"a": float("inf"), "b": float("-inf"), "c": float("nan"), "d": 1.5, "e": "nan?"},
    )
    obj = s.to_obj()
    json.dumps(obj, allow_nan=False)
    assert obj["meta"] == {"a": "inf", "b": "-inf", "c": "nan", "d": 1.5, "e": "nan?"}
    back = _round_trip(s)
    assert back == s
    assert back.meta["a"] == float("inf")
    assert np.isnan(back.meta["c"])


def test_to_obj_keys_and_types():
    """`to_obj` has the keys `name`, `kind`, `unit`, `coord_unit`, `coord_start`,
    `coord_step`, `coord_end`, `meta` and `arrays` in this order. `kind` is the string value,
    `coord_unit` is a string, an int and a bool of `meta` stay an int and a bool, a float
    stays a float, and `arrays` has the order of the series."""
    obj = _envelope().to_obj()
    assert list(obj) == [
        "name",
        "kind",
        "unit",
        "coord_unit",
        "coord_start",
        "coord_step",
        "coord_end",
        "meta",
        "arrays",
    ]
    assert obj["kind"] == "envelope"
    assert obj["coord_unit"] == "s"
    assert obj["coord_step"] == 0.006
    assert type(obj["meta"]["num_samples"]) is int
    assert type(obj["meta"]["on_raster"]) is bool
    assert type(obj["meta"]["dt_s"]) is float
    assert list(obj["arrays"]) == ["min", "max"]
    assert list(obj["arrays"]["min"]) == ["dtype", "length", "data"]
    # A field that a kind does not use has its default: null for `coord_step`.
    assert _runs().to_obj()["coord_step"] is None
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


def _rc2_obj() -> dict:
    """The object of an rc2 series: no `coord_unit`, and the rc2 keys `t0_s`, `step_s` and
    `end_s` of the three coordinate fields, with the same values."""
    obj = _without("coord_unit")
    for new, old in (("coord_start", "t0_s"), ("coord_step", "step_s"), ("coord_end", "end_s")):
        obj[old] = obj.pop(new)
    return obj


@pytest.mark.parametrize(
    ("obj", "message"),
    [
        pytest.param([1, 2], "must be a JSON object", id="not-an-object"),
        pytest.param(_with("extra", 1), "unknown key 'extra'", id="unknown-key"),
        pytest.param(_without("unit"), "missing key 'unit'", id="missing-key"),
        pytest.param(_without("arrays"), "missing key 'arrays'", id="missing-arrays"),
        pytest.param(_with("kind", "lines"), "unknown kind 'lines'", id="unknown-kind"),
        pytest.param(_with("kind", ["samples"]), "unknown kind", id="kind-not-a-string"),
        pytest.param(_with("name", ""), "name of a series must not be empty", id="empty-name"),
        pytest.param(_with("name", 3), "name of a series must be a string", id="name-not-a-string"),
        pytest.param(_with("unit", 3), "unit of a series must be a string", id="unit-not-a-string"),
        pytest.param(
            _with("coord_unit", None),
            "coord_unit of a series must be a string",
            id="coord-unit-null",
        ),
        pytest.param(
            _with("coord_unit", 3),
            "coord_unit of a series must be a string",
            id="coord-unit-a-number",
        ),
        pytest.param(_without("coord_unit"), "missing key 'coord_unit'", id="missing-coord-unit"),
        pytest.param(_rc2_obj(), "unknown key 't0_s'", id="rc2-object"),
        pytest.param(
            _with("coord_step", 0.0),
            "coord_step of a series must be finite and above 0",
            id="coord-step-zero",
        ),
        pytest.param(
            _with("coord_step", "fast"),
            '"coord_step" must be a number or null',
            id="coord-step-a-string",
        ),
        pytest.param(_with("coord_step", None), "needs coord_step", id="coord-step-null"),
        pytest.param(_with("coord_end", None), "needs coord_end", id="coord-end-null"),
        pytest.param(
            _with("coord_start", None),
            "coord_start of a series must be a real number",
            id="coord-start-null",
        ),
        pytest.param(
            _with("coord_start", True),
            '"coord_start" must be a number or null, not True',
            id="coord-start-a-bool",
        ),
        pytest.param(
            _with("coord_start", "inf"),
            "coord_start of a envelope series must be finite",
            id="coord-start-inf",
        ),
        pytest.param(
            _with("coord_start", "-inf"),
            "coord_start of a envelope series must be finite",
            id="coord-start-minus-inf",
        ),
        pytest.param(
            _with("coord_start", "nan"),
            "coord_start of a envelope series must be finite",
            id="coord-start-nan",
        ),
        pytest.param(
            _with("coord_end", "inf"),
            "coord_end of an envelope series must be finite",
            id="coord-end-inf",
        ),
        pytest.param(
            _with("coord_end", "nan"),
            "coord_end of an envelope series must be finite",
            id="coord-end-nan",
        ),
        pytest.param(
            _with("coord_end", 0.012), "with 3 bins must be above", id="coord-end-too-small"
        ),
        pytest.param(
            _with("coord_end", 0.02), "with 3 bins must not be above", id="coord-end-too-large"
        ),
        pytest.param(
            _with("meta", [1]), '"meta" of a series must be a JSON object', id="meta-not-an-object"
        ),
        pytest.param(_with("meta", {"a": [1]}), "meta value", id="meta-value-a-list"),
        pytest.param(
            _with("arrays", []),
            '"arrays" of a series must be a JSON object',
            id="arrays-not-an-object",
        ),
        pytest.param(
            _with("arrays", {"min": 3, "max": 4}),
            "an encoded array must be a JSON object",
            id="array-not-an-object",
        ),
        pytest.param(_with("arrays", {}), "needs the array 'min'", id="no-arrays"),
    ],
)
def test_from_obj_refuses(obj, message):
    """`from_obj` raises `ValueError`, and no other error, for an object that is not a dict,
    an unknown key, a missing key, an object of rc2, an unknown kind, a bad value of any
    field (also a coordinate that is not finite or not in order), and a bad array."""
    with pytest.raises(ValueError, match=re.escape(message)):
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


def test_decode_array_does_not_decompress_more_than_length_needs(monkeypatch):
    """Data that decompresses to far more bytes than `length` needs is refused, and the
    decompressor gives at most `length * itemsize + 1` bytes."""
    real = zlib.decompressobj
    produced = []

    class Spy:
        def __init__(self, *args, **kwargs):
            self.inner = real(*args, **kwargs)

        def decompress(self, data, *args, **kwargs):
            out = self.inner.decompress(data, *args, **kwargs)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(zlib, "decompressobj", Spy)
    d = _encoded(dtype="uint8", length=1, data=_gzip_text(b"\x00" * 10_000_000))
    with pytest.raises(ValueError, match="more than 1 bytes"):
        decode_array(d)
    assert produced
    assert sum(produced) <= 2


def test_decode_array_refuses_a_length_that_overflows():
    """A `length` of `10**30`, and a `length` with `length * itemsize` above `sys.maxsize` (or
    equal, so that `limit + 1` overflows), raise `ValueError` and not `OverflowError`, for
    each item size."""
    for length, dtype in (
        (10**30, "uint8"),
        (sys.maxsize, "uint8"),
        (sys.maxsize // 4 + 1, "float32"),
    ):
        with pytest.raises(ValueError, match="too large"):
            decode_array(_encoded(dtype=dtype, length=length))


def test_decode_array_refuses_bytes_after_the_gzip_stream():
    """Data that has bytes after the end of the gzip stream raises `ValueError` (here the
    bytes of a second gzip stream, and one byte of zero), also when the first stream has the
    right length."""
    raw = np.arange(4, dtype=np.float32).tobytes()
    for extra in (gzip.compress(b""), b"\x00"):
        text = base64.b64encode(gzip.compress(raw) + extra).decode("ascii")
        with pytest.raises(ValueError, match="there are bytes after it"):
            decode_array(_encoded(data=text))
    assert np.array_equal(decode_array(_encoded(data=_gzip_text(raw))), np.arange(4.0))


def test_decode_array_stores_a_bool_as_0_or_1():
    """A bool byte of 2 or 255 in the data decodes to True, and the array encodes to the
    text of the canonical array (bytes 0 and 1)."""
    raw = bytes([0, 1, 2, 255])
    d = {"dtype": "bool", "length": 4, "data": _gzip_text(raw)}
    a = decode_array(d)
    assert a.dtype == np.dtype(bool)
    assert a.flags.writeable
    assert a.tolist() == [False, True, True, True]
    assert a.view(np.uint8).tolist() == [0, 1, 1, 1]
    assert encode_array(a) == encode_array(np.array([False, True, True, True]))


def test_from_obj_refuses_a_number_that_overflows():
    """A coordinate of `10**400` (an int too large for a float) in `coord_start`,
    `coord_step` or `coord_end`, and a `length` of `10**30`, raise `ValueError` from
    `Series.from_obj`, and not `OverflowError`."""
    obj = _envelope().to_obj()
    for key in ("coord_start", "coord_step", "coord_end"):
        with pytest.raises(ValueError, match="too large for a float"):
            Series.from_obj({**obj, key: 10**400})
    arrays = {**obj["arrays"], "min": {**obj["arrays"]["min"], "length": 10**30}}
    with pytest.raises(ValueError, match="too large"):
        Series.from_obj({**obj, "arrays": arrays})


def _with_a_stray_character(text: str) -> str:
    """`text` with "!" in the middle. The padding at the end is the padding of `text`, and
    `base64.b64decode(..., validate=False)` skips the "!" and gives the bytes of `text`."""
    middle = len(text) // 2
    return text[:middle] + "!" + text[middle:]


@pytest.mark.parametrize(
    ("d", "message"),
    [
        pytest.param("text", "must be a JSON object", id="not-a-dict"),
        pytest.param({"dtype": "float32", "length": 4}, "missing key 'data'", id="missing-key"),
        pytest.param(_encoded(extra=1), "unknown key 'extra'", id="unknown-key"),
        pytest.param(
            _encoded(length=5), '"length" of an encoded array is 5', id="length-too-large"
        ),
        pytest.param(
            _encoded(length=3), '"length" of an encoded array is 3', id="length-too-small"
        ),
        pytest.param(
            _encoded(length=-4), "must be an integer of 0 or more, not -4", id="length-negative"
        ),
        pytest.param(
            _encoded(length=4.0), "must be an integer of 0 or more, not 4.0", id="length-a-float"
        ),
        pytest.param(
            _encoded(length=True), "must be an integer of 0 or more, not True", id="length-a-bool"
        ),
        pytest.param(
            _encoded(dtype="object"),
            "must be a numeric or bool dtype, not 'object'",
            id="dtype-object",
        ),
        pytest.param(
            _encoded(dtype="datetime64[s]"),
            "must be a numeric or bool dtype, not 'datetime64",
            id="dtype-datetime",
        ),
        pytest.param(_encoded(dtype="str32"), "unknown dtype 'str32'", id="dtype-string"),
        pytest.param(
            _encoded(dtype="no-such-dtype"), "unknown dtype 'no-such-dtype'", id="dtype-unknown"
        ),
        pytest.param(
            _encoded(dtype="f4"),
            "must be a numeric or bool dtype, not 'f4'",
            id="dtype-not-the-name",
        ),
        pytest.param(_encoded(dtype=32), "unknown dtype 32", id="dtype-not-a-string"),
        pytest.param(
            _encoded(data=3), '"data" of an encoded array must be a string', id="data-not-a-string"
        ),
        pytest.param(
            _encoded(data=_with_a_stray_character(_encoded()["data"])),
            "does not decode: Only base64 data is allowed",
            id="data-not-base64",
        ),
        pytest.param(
            _encoded(data="AAAA"),
            "does not decode: Error -3 while decompressing data",
            id="data-not-gzip",
        ),
        pytest.param(
            _encoded(data=_encoded()["data"][:-8]),
            "does not decode: the stream is not complete",
            id="data-cut-short",
        ),
        pytest.param(
            _encoded(data=_gzip_text(b"\x00" * 15)),
            "its data has 15 bytes",
            id="bytes-not-a-whole-number",
        ),
        pytest.param(
            _encoded(data=_gzip_text(b"\x00" * 20)),
            "its data has more than 16 bytes",
            id="data-longer-than-length",
        ),
        pytest.param(
            _encoded(data=_gzip_text(b"\x00" * 12)),
            "its data has 12 bytes",
            id="data-shorter-than-length",
        ),
    ],
)
def test_decode_array_refuses(d, message):
    """`decode_array` raises `ValueError` for a value that is not a dict, an unknown key, a
    missing key, a `length` that is not the decoded byte count divided by the item size, a
    dtype that is not a numeric or bool dtype name, and data that does not decode."""
    with pytest.raises(ValueError, match=re.escape(message)):
        decode_array(d)
