"""Value equality for the frozen dataclasses of results that hold numpy arrays
(`pns_levels.PnsLevels` and `grad_spectrum.GradientSpectrum`).

The `__eq__` that `dataclasses` makes compares the fields as one tuple, and a numpy array
with more than one element raises `ValueError` in that comparison. `fields_equal` compares
each field with `values_equal` instead, and finds the fields with `dataclasses.fields`, so
that a new or a renamed field needs no change here. A class that uses it sets
`eq=False`, `__eq__ = fields_equal` and `__hash__ = None`, as `series.Series` does.

The rules of `values_equal`:

- Two numpy arrays are equal when they have the same dtype, the same shape and the same
  values. A NaN equals a NaN. The `writeable` flag does not count, so a copy (for example
  from `pickle` or `copy.deepcopy`) equals the read-only original.
- Two dicts are equal when they have the same keys in the same order, and equal values.
  The order counts because it is part of the interface (`PnsLevels.above` follows the
  order of the thresholds).
- Two tuples or two lists are equal when they have the same length and equal elements.
- Two dataclasses of the same class are equal when each pair of fields is equal.
- Other values are equal when they have the same type and are equal by `==`, where a
  NaN equals a NaN (as `series._same_value`). Thus `1` does not equal `1.0`.
"""

import dataclasses
from typing import Any

import numpy as np


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
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(values_equal(a[k], b[k]) for k in a)
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
