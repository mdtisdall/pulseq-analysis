"""Tests of `_equality`: the value equality of the results that hold numpy arrays."""

import copy
import dataclasses
import json
import pickle

import numpy as np
import pytest

from pulseq_analysis._equality import FrozenDict, fields_equal, values_equal


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


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.__setitem__("a", 2), id="setitem"),
        pytest.param(lambda d: d.__delitem__("a"), id="delitem"),
        pytest.param(lambda d: d.clear(), id="clear"),
        pytest.param(lambda d: d.pop("a"), id="pop"),
        pytest.param(lambda d: d.popitem(), id="popitem"),
        pytest.param(lambda d: d.setdefault("c", 3), id="setdefault"),
        pytest.param(lambda d: d.update(c=3), id="update"),
        pytest.param(lambda d: d.__ior__({"c": 3}), id="ior"),
    ],
)
def test_a_frozen_dict_refuses_each_change(change):
    """Each method of a `FrozenDict` that changes it raises `TypeError`, and the items are
    the same after."""
    d = FrozenDict({"a": 1, "b": 2})
    with pytest.raises(TypeError, match="cannot be changed"):
        change(d)
    assert dict(d) == {"a": 1, "b": 2}


def test_a_frozen_dict_reads_like_a_dict():
    """A `FrozenDict` is a `dict` and can be read like one."""
    d = FrozenDict({"b": 1, "a": 2})
    assert isinstance(d, dict)
    assert d["a"] == 2
    assert len(d) == 2
    assert "b" in d
    assert "c" not in d
    assert list(d) == ["b", "a"]
    assert dict(d) == {"b": 1, "a": 2}
    assert d.get("c") is None
    assert FrozenDict(b=1, a=2) == d


def test_a_frozen_dict_is_made_from_pairs_and_keywords():
    """`FrozenDict(...)` takes the arguments of `dict`, so `dict.__init__` can fill it
    although `__setitem__` is closed."""
    assert dict(FrozenDict([("a", 1)], b=2)) == {"a": 1, "b": 2}


@pytest.mark.parametrize(
    "clone",
    [
        pytest.param(lambda d: pickle.loads(pickle.dumps(d)), id="pickle"),
        pytest.param(copy.deepcopy, id="deepcopy"),
        pytest.param(copy.copy, id="copy"),
    ],
)
def test_a_frozen_dict_survives_pickle_and_copy(clone):
    """A copy of a `FrozenDict` from `pickle`, `copy.deepcopy` or `copy.copy` is an equal
    `FrozenDict` that still refuses changes."""
    d = FrozenDict({"a": 1, "b": (2.0, 3.0)})
    c = clone(d)
    assert type(c) is FrozenDict
    assert list(c.items()) == list(d.items())
    with pytest.raises(TypeError):
        c["a"] = 5


def test_a_frozen_dict_is_written_by_json_as_an_object_and_is_not_hashable():
    """`json.dumps` writes a `FrozenDict` as an object, and `hash` raises `TypeError`."""
    d = FrozenDict({"a": 1, "b": [2, 3]})
    assert json.loads(json.dumps(d)) == {"a": 1, "b": [2, 3]}
    with pytest.raises(TypeError):
        hash(d)


def test_the_union_of_a_frozen_dict_is_a_plain_dict():
    """`|` of a `FrozenDict` with a dict, in both orders, gives a new plain `dict` and
    leaves the `FrozenDict` as it was."""
    d = FrozenDict({"a": 1})
    left = d | {"b": 2}
    right = {"b": 2} | d
    assert type(left) is dict
    assert left == {"a": 1, "b": 2}
    assert type(right) is dict
    assert right == {"b": 2, "a": 1}
    assert dict(d) == {"a": 1}


@pytest.mark.parametrize(
    ("other", "equal"),
    [
        pytest.param({"a": np.array([1.0]), "b": 2}, True, id="same-items"),
        pytest.param({"b": 2, "a": np.array([1.0])}, False, id="another-order"),
        pytest.param({"a": np.array([1.0]), "b": 3}, False, id="another-value"),
        pytest.param({"a": np.array([1.0])}, False, id="another-key"),
    ],
)
def test_values_equal_does_not_separate_a_frozen_dict_from_a_dict(other, equal):
    """A `FrozenDict` and a `dict` are equal by the rules of two dicts, in both orders and
    for two `FrozenDict`s."""
    frozen = FrozenDict({"a": np.array([1.0]), "b": 2})
    assert values_equal(frozen, other) is equal
    assert values_equal(other, frozen) is equal
    assert values_equal(frozen, FrozenDict(other)) is equal
    assert values_equal(frozen, [1.0]) is False
