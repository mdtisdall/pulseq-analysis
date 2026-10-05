"""Tests of `_equality`: the value equality of the results that hold numpy arrays."""

import dataclasses

import numpy as np
import pytest

from pulseq_analysis._equality import fields_equal, values_equal


@dataclasses.dataclass(frozen=True)
class _Point:
    x: float
    n: int


@dataclasses.dataclass(frozen=True, eq=False)
class _Holder:
    a: np.ndarray
    d: dict

    __eq__ = fields_equal
    __hash__ = None  # type: ignore[assignment]


def _read_only(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        pytest.param(np.array([1.0, 2.0]), np.array([1.0, 2.0]), True, id="same-array"),
        pytest.param(
            np.array([1.0, 2.0], dtype=np.float32),
            np.array([1.0, 2.0], dtype=np.float64),
            False,
            id="another-dtype",
        ),
        pytest.param(np.zeros((2, 2)), np.zeros(4), False, id="another-shape"),
        pytest.param(np.array([1.0, 2.0]), np.array([1.0, 3.0]), False, id="another-value"),
        pytest.param(np.array([np.nan, 1.0]), np.array([np.nan, 1.0]), True, id="nan-in-array"),
        pytest.param(np.array([1, 2]), np.array([1, 2]), True, id="int-array"),
        pytest.param(np.array([True]), np.array([True]), True, id="bool-array"),
        pytest.param(np.zeros(0), np.zeros(0), True, id="empty-arrays"),
        pytest.param(
            _read_only(np.array([1.0, 2.0])), np.array([1.0, 2.0]), True, id="read-only-vs-writable"
        ),
        pytest.param(np.array([1.0]), [1.0], False, id="array-vs-list"),
        pytest.param(np.array([1.0]), 1.0, False, id="array-vs-float"),
        pytest.param({"x": 1.0, "y": 2.0}, {"x": 1.0, "y": 2.0}, True, id="same-dict"),
        pytest.param({"x": 1.0, "y": 2.0}, {"y": 2.0, "x": 1.0}, False, id="dict-key-order"),
        pytest.param({"x": 1.0}, {"x": 1.0, "y": 2.0}, False, id="dict-another-key"),
        pytest.param(
            {"x": {"a": np.array([1.0])}},
            {"x": {"a": np.array([1.0])}},
            True,
            id="nested-dict-with-array",
        ),
        pytest.param(
            {"x": {"a": np.array([1.0])}},
            {"x": {"a": np.array([2.0])}},
            False,
            id="nested-dict-another-array",
        ),
        pytest.param((1.0, 2.0), (1.0, 2.0), True, id="same-tuple"),
        pytest.param((1.0, 2.0), (1.0,), False, id="tuple-length"),
        pytest.param((1.0,), [1.0], False, id="tuple-vs-list"),
        pytest.param((_Point(1.0, 2),), (_Point(1.0, 2),), True, id="nested-dataclass"),
        pytest.param((_Point(1.0, 2),), (_Point(1.0, 3),), False, id="nested-dataclass-field"),
        pytest.param(_Point(float("nan"), 2), _Point(float("nan"), 2), True, id="nan-in-dataclass"),
        pytest.param(float("nan"), float("nan"), True, id="nan-scalar"),
        pytest.param(1, 1.0, False, id="int-vs-float"),
        pytest.param(True, 1, False, id="bool-vs-int"),
        pytest.param(None, None, True, id="none"),
        pytest.param(None, 0.0, False, id="none-vs-value"),
        pytest.param("a", "a", True, id="same-string"),
    ],
)
def test_values_equal(a, b, equal):
    """`values_equal` follows the rules of the module docstring of `_equality`, in both
    orders of its arguments."""
    assert values_equal(a, b) is equal
    assert values_equal(b, a) is equal


def test_fields_equal_as_the_eq_of_a_dataclass():
    """A dataclass with `__eq__ = fields_equal` compares its fields by value, is not equal
    to an object of another class, and is not hashable."""
    a = _Holder(np.array([1.0, 2.0]), {"k": (1.0,)})
    assert a == _Holder(np.array([1.0, 2.0]), {"k": (1.0,)})
    assert a != _Holder(np.array([1.0, 2.5]), {"k": (1.0,)})
    assert a != _Holder(np.array([1.0, 2.0]), {"k": (2.0,)})
    assert a != "a"
    assert fields_equal(a, "a") is NotImplemented
    with pytest.raises(TypeError):
        hash(a)
