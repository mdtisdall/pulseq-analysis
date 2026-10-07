"""Value equality for the frozen dataclasses of results that hold numpy arrays
(`seq_index.SequenceIndex`, `grad_peaks.GradientPeaks`, `grad_peaks.BlockGradientValues`,
`pns_levels.PnsLevels`, `grad_spectrum.GradientSpectrum` and `series.Series`).

The `__eq__` that `dataclasses` makes compares the fields as one tuple, and a numpy array
with more than one element raises `ValueError` in that comparison. `fields_equal` compares
each field with `values_equal` instead, and finds the fields with `dataclasses.fields`, so
that a new or a renamed field needs no change here. The decorator `value_dataclass` is the
one place of the rule for the classes above: it makes the class a frozen dataclass with
`eq=False`, sets `__eq__ = fields_equal` and sets `__hash__ = None`.

The rules of `values_equal`:

- Two numpy arrays are equal when they have the same dtype, the same shape and the same
  values. A NaN equals a NaN. The `writeable` flag does not count, so a copy (for example
  from `pickle` or `copy.deepcopy`) equals the read-only original.
- Two dicts are equal when they have the same keys in the same order, and equal values.
  The order counts because it is part of the interface (`PnsLevels.above` follows the
  order of the thresholds). A `FrozenDict` and a `dict` are two dicts: the type rule below
  does not separate them.
- Two tuples or two lists are equal when they have the same length and equal elements.
- Two dataclasses of the same class are equal when each pair of fields is equal.
- Other values are equal when they have the same type and are equal by `==`, where a
  NaN equals a NaN. Thus `1` does not equal `1.0`, and `True` does not equal `1`.
"""

import dataclasses
from typing import Any, NoReturn, dataclass_transform

import numpy as np


class FrozenDict(dict):
    """A `dict` that cannot be changed, for the dicts of a result.

    The kept results (`_kept`) are shared by all callers, so a change of a dict of a result
    would change it for all of them. `MappingProxyType` cannot be pickled, and it is not a
    `dict`. A subclass of `dict` keeps `isinstance(x, dict)`, `json.dumps`, `pickle` and
    `copy`. Each method that changes the dict raises `TypeError`. `|` gives a plain `dict`.
    It is not hashable, as `dict`.
    """

    __slots__ = ()

    def _refuse(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise TypeError("a FrozenDict of a result cannot be changed")

    __setitem__ = __delitem__ = __ior__ = _refuse  # type: ignore[assignment]
    clear = pop = popitem = setdefault = update = _refuse  # type: ignore[assignment]

    def __reduce__(self) -> tuple[Any, ...]:
        return (FrozenDict, (dict(self),))

    def __repr__(self) -> str:
        return f"FrozenDict({dict.__repr__(self)})"


def values_equal(a: Any, b: Any) -> bool:
    """Whether `a` and `b` are equal by the rules of the module docstring."""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return (
            isinstance(a, np.ndarray)
            and isinstance(b, np.ndarray)
            and a.dtype == b.dtype
            and a.shape == b.shape
            and bool(np.array_equal(a, b, equal_nan=a.dtype.kind in "fc"))
        )
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(values_equal(a[k], b[k]) for k in a)
    if type(a) is not type(b):
        return False
    if isinstance(a, tuple | list):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b, strict=True))
    if dataclasses.is_dataclass(a):
        return _same_fields(a, b)
    return bool(a == b) or (a != a and b != b)  # noqa: PLR0124 (a NaN equals a NaN)


def fields_equal(self: Any, other: object) -> bool:
    """`__eq__` for a dataclass: `NotImplemented` when `other` is of another class, else
    whether each field of `self` equals the same field of `other` (`values_equal`)."""
    if other.__class__ is not self.__class__:
        return NotImplemented
    return _same_fields(self, other)


def _same_fields(a: Any, b: Any) -> bool:
    """Whether each field of the dataclass `a` equals the same field of `b`, a dataclass of
    the same class."""
    return all(values_equal(getattr(a, f.name), getattr(b, f.name)) for f in dataclasses.fields(a))


@dataclass_transform(frozen_default=True, eq_default=False)
def value_dataclass[T](cls: type[T]) -> type[T]:
    """Class decorator for a result with value equality: a frozen dataclass with `eq=False`,
    `__eq__ = fields_equal` and `__hash__ = None`. `__hash__` is set because a class with
    `eq=False` would keep the identity hash of `object`, and a value that is equal to
    another must not have a hash that depends on its identity."""
    cls = dataclasses.dataclass(frozen=True, eq=False)(cls)
    cls.__eq__ = fields_equal  # type: ignore[method-assign]
    cls.__hash__ = None  # type: ignore[assignment]
    return cls
