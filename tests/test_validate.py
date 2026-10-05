"""Tests of `_validate.real`: the one rule for the number arguments of the package."""

import fractions

import numpy as np
import pytest

from pulseq_analysis._validate import real


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(3, 3.0, id="int"),
        pytest.param(2.5, 2.5, id="float"),
        pytest.param(np.float64(2.5), 2.5, id="numpy-float64"),
        pytest.param(np.float32(0.5), 0.5, id="numpy-float32"),
        pytest.param(np.int64(7), 7.0, id="numpy-int64"),
        pytest.param(fractions.Fraction(1, 4), 0.25, id="fraction"),
        pytest.param(-1.5, -1.5, id="negative"),
        pytest.param(0, 0.0, id="zero"),
    ],
)
def test_real_returns_a_float(value, expected):
    """`real` accepts the real numbers and returns `float(value)`."""
    result = real("x", value)
    assert type(result) is float
    assert result == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="bool"),
        pytest.param(np.bool_(True), id="numpy-bool"),
        pytest.param("1.0", id="str"),
        pytest.param(None, id="none"),
        pytest.param(1 + 2j, id="complex"),
        pytest.param([1.0], id="list"),
    ],
)
def test_real_refuses_a_value_that_is_not_a_real_number_with_type_error(value):
    """A `bool`, or a value that is not a `numbers.Real`, raises `TypeError`, with the name
    and the value in the message."""
    with pytest.raises(TypeError, match=r"my_arg must be a real number, not .*"):
        real("my_arg", value)
    with pytest.raises(TypeError, match="my_arg"):
        real("my_arg", value, finite=False, positive=True)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="inf"),
        pytest.param(float("-inf"), id="minus-inf"),
        pytest.param(np.float32("inf"), id="numpy-inf"),
    ],
)
def test_real_refuses_a_value_that_is_not_finite_with_value_error(value):
    """With `finite=True` (the default), NaN and the infinities raise `ValueError` with
    the name in the message."""
    with pytest.raises(ValueError, match="my_arg"):
        real("my_arg", value)


def test_real_with_finite_false_accepts_an_infinity_and_nan():
    """With `finite=False`, an infinity is returned, and NaN is returned."""
    assert real("x", float("inf"), finite=False) == float("inf")
    assert real("x", float("-inf"), finite=False) == float("-inf")
    assert np.isnan(real("x", float("nan"), finite=False))


def test_real_refuses_an_int_too_large_for_a_float_with_value_error():
    """An int above the range of a float raises `ValueError`, also with `finite=False`."""
    with pytest.raises(ValueError, match="my_arg"):
        real("my_arg", 10**400)
    with pytest.raises(ValueError, match="my_arg"):
        real("my_arg", -(10**400), finite=False)


@pytest.mark.parametrize("value", [0, 0.0, -1, -0.5, np.float32(-2.0)])
def test_real_with_positive_refuses_zero_and_a_negative_value(value):
    """With `positive=True`, a value not above 0 raises `ValueError` with the name in the
    message."""
    with pytest.raises(ValueError, match="my_arg"):
        real("my_arg", value, positive=True)


def test_real_with_positive_accepts_a_positive_value_and_nan_is_not_positive():
    """With `positive=True`, a positive value is returned; with `finite=False` NaN is not
    above 0 and raises `ValueError`, and an infinity is above 0 and is returned."""
    assert real("x", 1e-300, positive=True) == 1e-300
    assert real("x", float("inf"), finite=False, positive=True) == float("inf")
    with pytest.raises(ValueError, match="x"):
        real("x", float("nan"), finite=False, positive=True)
