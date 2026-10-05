"""The one rule for the number arguments of the package.

`real` checks a number argument and returns it as a `float`. The thresholds and `bin_s` of
`pns_levels`, the arguments of `gradient_spectrum`, the `window` of `gradient_peaks` and
the coordinates of a `Series` use it, so that one value gives the same error everywhere.
"""

import math
import numbers


def real(name: str, value: object, *, finite: bool = True, positive: bool = False) -> float:
    """`value` as a `float`.

    Raises `TypeError` when `value` is a `bool` or is not a `numbers.Real` (so an `int`,
    a `float`, `fractions.Fraction` and the numpy real scalars are valid). Raises
    `ValueError` when `value` is too large for a `float`, when `finite` and `value` is NaN
    or an infinity, or when `positive` and `value` is not above 0. `name` is in each
    message.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, not {value!r}")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError(f"{name} is too large for a float: {value!r}") from None
    if finite and not math.isfinite(result):
        raise ValueError(f"{name} must be finite, not {value!r}")
    if positive and not result > 0:
        raise ValueError(f"{name} must be above 0, not {value!r}")
    return result
