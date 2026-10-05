"""Comparisons that more than one test file uses."""

import dataclasses

import numpy as np

from pulseq_analysis.grad_peaks import BlockGradientValues
from pulseq_analysis.pns_levels import PnsLevels


def assert_levels_equal(a: PnsLevels, b: PnsLevels, *, ignore: tuple[str, ...]) -> None:
    """Every field of `a` and `b` is exactly equal, except the fields named in `ignore`
    (`numpy.array_equal` for the arrays, `==` for the rest)."""
    for field in dataclasses.fields(PnsLevels):
        if field.name in ignore:
            continue
        x, y = getattr(a, field.name), getattr(b, field.name)
        if isinstance(x, np.ndarray):
            assert np.array_equal(x, y), field.name
        else:
            assert x == y, field.name


def assert_block_values_equal(a: BlockGradientValues, b: BlockGradientValues) -> None:
    """Every array of two `BlockGradientValues` is exactly equal."""
    np.testing.assert_array_equal(a.block_id, b.block_id)
    np.testing.assert_array_equal(a.start_s, b.start_s)
    np.testing.assert_array_equal(a.vector_peak_hz_per_m, b.vector_peak_hz_per_m)
    np.testing.assert_array_equal(a.vector_peak_time_s, b.vector_peak_time_s)
    for name in (
        "peak_hz_per_m",
        "peak_time_s",
        "slew_hz_per_m_per_s",
        "slew_time_s",
        "junction_hz_per_m_per_s",
    ):
        field_a, field_b = getattr(a, name), getattr(b, name)
        assert list(field_a) == list(field_b)
        for axis in field_a:
            assert np.array_equal(field_a[axis], field_b[axis]), f"{name}[{axis}]"
