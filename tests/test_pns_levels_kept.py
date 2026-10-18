import dataclasses
import re

import pytest

pytestmark = pytest.mark.pypulseq
pytest.importorskip("pypulseq")

import numpy as np
import pypulseq as pp
from pns_hardware import EXAMPLE_HW, NOT_A_SAFE_HARDWARE
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw
from synthetic import (
    GAMMA_1H,
    SYSTEM,
    block_pulse,
    empty_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.analyses import load
from pulseq_analysis.analyses import pns_levels as pns_levels_module
from pulseq_analysis.analyses.asc import hardware_from_asc, hardware_name, read_gradient_asc
from pulseq_analysis.analyses.pns_levels import BIN_S, NO_GRADIENTS, pns_levels
from pulseq_analysis.analyses.safe import SafeHardware
from pulseq_analysis.synth.sampling import GradientSampler

_LIMIT = GAMMA_1H  # Hz/T: the stimulation limit for 1H, a fraction of 1 times GAMMA_1H


@pytest.fixture(scope="module")
def default_snap():
    return load(spin_echo_sequence())


@pytest.fixture(scope="module")
def example(default_snap):
    return pns_levels(default_snap, hardware=EXAMPLE_HW)


def test_prediction_scales_with_the_stimulation_limit(default_snap, example, write_gradient_asc):
    p = pns_levels(default_snap, hardware=hardware_from_asc(write_gradient_asc(limit_scale=0.1)))
    assert p.peak_hz_per_t == pytest.approx(10 * example.peak_hz_per_t, rel=1e-9)
    assert p.peak_hz_per_t > _LIMIT


def test_no_gradients_with_rf_and_adc():
    seq = pp.Sequence(SYSTEM)
    seq.add_block(block_pulse("excitation", np.pi / 2))
    seq.add_block(
        pp.make_adc(num_samples=64, dwell=20e-6, delay=SYSTEM.adc_dead_time, system=SYSTEM)
    )
    assert pns_levels(load(seq), hardware=EXAMPLE_HW).reason == NO_GRADIENTS


def test_prediction_does_not_sample_at_the_file_times_for_an_on_raster_sequence(monkeypatch):
    """`pns_levels` samples an on-raster sequence with `GradientSampler.block_samples`, not
    with `GradientSampler.sample` (the samples at the file times of a sequence that is not on
    the raster), so `sample` is never called, and `block_samples` is."""
    snap = load(spin_echo_sequence())
    sample_calls = []
    block_samples_calls = []
    sample = GradientSampler.sample
    block_samples = GradientSampler.block_samples

    def counted_sample(*args, **kwargs):
        sample_calls.append(1)
        return sample(*args, **kwargs)

    def counted_block_samples(*args, **kwargs):
        block_samples_calls.append(1)
        return block_samples(*args, **kwargs)

    monkeypatch.setattr(GradientSampler, "sample", counted_sample)
    monkeypatch.setattr(GradientSampler, "block_samples", counted_block_samples)
    pns_levels(snap, hardware=EXAMPLE_HW)
    assert sample_calls == []
    assert block_samples_calls


def _count_pns_levels_calls(monkeypatch) -> list:
    """Patches `_compute_levels` (the calculation that `pns_levels` calls for a result that
    is not kept) with a wrapper that records one entry for each call, and returns the
    list."""
    calls: list = []
    original = pns_levels_module._compute_levels

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pns_levels_module, "_compute_levels", counted)
    return calls


def test_pns_levels_keeps_one_result_for_equal_safe_hardwares(monkeypatch):
    """Two `SafeHardware`s with the same name and the same field values, two different
    objects, are one hardware: the second call runs no model and gives the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())

    first = pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL"))
    second = pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_computes_again_for_another_label_or_value(monkeypatch):
    """A `SafeHardware` with another name (the label), or with one other field value, is
    another hardware and runs the model; going back to an earlier hardware does not run it
    again (the calls for the hardwares a, a, b (name), c (value), a, c give 3)."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    other_value = safe_example_hw()
    other_value.z.stim_limit += 1.0

    pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "A"))
    pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "A"))
    assert len(calls) == 1
    pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "B"))
    assert len(calls) == 2
    pns_levels(snap, hardware=SafeHardware.from_namespace(other_value, "A"))
    assert len(calls) == 3
    pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "A"))
    pns_levels(snap, hardware=SafeHardware.from_namespace(other_value, "A"))
    assert len(calls) == 3


@pytest.mark.parametrize("axis", "xyz")
@pytest.mark.parametrize("field", pns_levels_module._HW_FIELDS)
def test_pns_levels_keys_the_hardware_on_each_field_of_each_axis(default_snap, axis, field):
    """A struct that differs from the example struct in one field of one axis (`_HW_FIELDS`,
    each of the 8 fields of each of the 3 axes), with the same name, is another hardware: the
    call gives a new result and not the kept result of the example struct. The value is valid:
    `a1`, `a2` or `a3` is 0.0005 more (the sum of the three stays within 0.001 of 1), and
    another field is 1.1 times its value (`stim_limit` stays above 0). A key that left out
    a field would give the kept result."""
    struct = safe_example_hw()
    axis_struct = getattr(struct, axis)
    old = getattr(axis_struct, field)
    new = old + 0.0005 if field in ("a1", "a2", "a3") else 1.1 * old
    assert new != old
    setattr(axis_struct, field, new)

    kept = pns_levels(
        default_snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL")
    )
    changed = pns_levels(default_snap, hardware=SafeHardware.from_namespace(struct, "LABEL"))
    assert changed is not kept
    assert (
        pns_levels(default_snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "LABEL"))
        is kept
    )


def test_pns_levels_ignores_stim_thresh_in_the_hardware_key(monkeypatch):
    """Two `SafeHardware`s with the same name that differ only in `z.stim_thresh` are one
    hardware: the second call runs no model and gives the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    other_thresh = safe_example_hw()
    other_thresh.z.stim_thresh += 1.0

    first = pns_levels(snap, hardware=SafeHardware.from_namespace(safe_example_hw(), "A"))
    second = pns_levels(snap, hardware=SafeHardware.from_namespace(other_thresh, "A"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_keys_a_hardware_from_an_asc_file_by_its_label_and_values(
    monkeypatch, write_gradient_asc
):
    """The key of a `SafeHardware` from a file is its name and its values, as for any
    `SafeHardware`: the one of `hardware_from_asc`, one made again by hand from the same file
    (`SafeHardware.from_namespace` of pypulseq's `asc_to_hw`, with `hardware_name`), and one
    from the file read again are one hardware; the same values with another name are
    another, and so is `EXAMPLE_HW` (the same values, another name). Each of the two
    hardwares runs the model one time, in two rounds."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    path = write_gradient_asc()
    asc = read_gradient_asc(path)
    from_file = hardware_from_asc(path)
    relabelled = dataclasses.replace(from_file, name="OTHER")

    first = pns_levels(snap, hardware=from_file)
    assert len(calls) == 1
    for _ in range(2):
        assert pns_levels(snap, hardware=hardware_from_asc(path)) is first
        assert (
            pns_levels(
                snap, hardware=SafeHardware.from_namespace(asc_to_hw(asc), hardware_name(asc))
            )
            is first
        )
    assert len(calls) == 1

    for _ in range(2):
        pns_levels(snap, hardware=relabelled)
        pns_levels(snap, hardware=EXAMPLE_HW)
    assert len(calls) == 3


def test_pns_levels_needs_hardware():
    """`pns_levels` without `hardware` raises `TypeError` ("hardware"), also for a first
    argument that is not a snapshot: the arguments are checked first."""
    with pytest.raises(TypeError, match="hardware"):
        pns_levels(spin_echo_sequence())  # type: ignore[call-arg]


@pytest.mark.parametrize("hardware", NOT_A_SAFE_HARDWARE)
def test_pns_levels_refuses_a_hardware_that_is_not_a_safe_hardware_before_the_snapshot_type(
    hardware,
):
    """`pns_levels` with a `hardware` that is not a `SafeHardware` raises `TypeError`
    ("hardware must be a safe.SafeHardware"), before the type of the first argument is
    checked: the first argument is a `pp.Sequence`, which is not a snapshot and would raise the
    `TypeError` that names `load`, and the error is still the one of `hardware`. The same
    holds for a sequence with no gradient event, which gives a result for a `SafeHardware`."""
    with pytest.raises(TypeError, match=re.escape("hardware must be a safe.SafeHardware")):
        pns_levels(spin_echo_sequence(), hardware=hardware)
    with pytest.raises(TypeError, match=re.escape("hardware must be a safe.SafeHardware")):
        pns_levels(load(empty_sequence()), hardware=hardware)


def test_pns_levels_keeps_one_result_for_each_tuple_of_thresholds(monkeypatch):
    """The thresholds are part of the key of a kept result: other thresholds, or the same
    ones in another order, run the model and do not give the result of the default (no
    thresholds, the key `()`); the same thresholds again give the kept result (the same
    object), and an `int` threshold is the key of the equal `float`."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    thresholds = (_LIMIT, 0.5 * _LIMIT)

    default = pns_levels(snap, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    other = pns_levels(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
    assert len(calls) == 2
    assert other is not default
    assert list(default.above) == []
    assert list(other.above) == list(thresholds)
    assert pns_levels(snap, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW) is other
    assert pns_levels(snap, hardware=EXAMPLE_HW) is default
    assert pns_levels(snap, thresholds_hz_per_t=(), hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    whole = round(_LIMIT)  # an int that is equal to the float `_LIMIT`
    assert float(whole) == _LIMIT
    assert pns_levels(snap, thresholds_hz_per_t=(whole, 0.5 * _LIMIT), hardware=EXAMPLE_HW) is other
    assert len(calls) == 2
    reordered = pns_levels(snap, thresholds_hz_per_t=thresholds[::-1], hardware=EXAMPLE_HW)
    assert len(calls) == 3
    assert list(reordered.above) == list(thresholds[::-1])


def test_pns_levels_keeps_one_result_for_each_bin_s(monkeypatch):
    """`bin_s` is part of the key of a kept result: another `bin_s` runs the model and does
    not give the result of the default (`BIN_S`); the same `bin_s` again gives the kept
    result (the same object); the default and `bin_s=BIN_S` are one key; an `int` `bin_s`
    and the equal `float` are one key; a `bin_s` that gives the `bin_samples` of the default
    is another key; and the bins and `bin_s` of each result are those of its `bin_s`."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())

    default = pns_levels(snap, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    assert pns_levels(snap, hardware=EXAMPLE_HW, bin_s=BIN_S) is default
    assert len(calls) == 1
    six = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=0.006)
    assert len(calls) == 2
    assert six is not default
    assert six.bin_samples == 600
    assert default.bin_samples == 500
    assert six.bin_s == 0.006
    assert default.bin_s == BIN_S
    assert pns_levels(snap, hardware=EXAMPLE_HW, bin_s=0.006) is six
    assert pns_levels(snap, hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    one = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=1)
    assert len(calls) == 3
    assert pns_levels(snap, hardware=EXAMPLE_HW, bin_s=1.0) is one
    assert len(calls) == 3
    assert one.bin_s == 1.0
    near = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=0.0050001)  # 500.01 samples: 500
    assert len(calls) == 4
    assert near.bin_samples == default.bin_samples
    assert near.bin_s == 0.0050001  # its own `bin_s`, not `bin_samples * dt_s` or `BIN_S`
    assert near != default
    with_thresholds = pns_levels(
        snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,), bin_s=0.006
    )
    assert with_thresholds is not six  # the thresholds and `bin_s` are both in the key
    assert len(calls) == 5


def test_pns_levels_shares_a_read_only_result():
    """Two callers of `pns_levels` get the same kept result. A change in place of its
    level by the first caller raises `ValueError`, and the second caller gets the level as
    it was."""
    snap = load(spin_echo_sequence())
    first = pns_levels(snap, hardware=EXAMPLE_HW)
    before_min, before_max = first.level_min_hz_per_t.copy(), first.level_max_hz_per_t.copy()
    # Through a local name: `first.level_max_hz_per_t *= 100` would also set the field of the frozen
    # dataclass.
    level_max = first.level_max_hz_per_t
    with pytest.raises(ValueError):
        level_max *= 100
    with pytest.raises(ValueError):
        first.level_min_hz_per_t[0] = 0.0
    second = pns_levels(snap, hardware=EXAMPLE_HW)
    assert second is first
    np.testing.assert_array_equal(second.level_min_hz_per_t, before_min)
    np.testing.assert_array_equal(second.level_max_hz_per_t, before_max)


def test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result(
    write_gradient_asc, monkeypatch
):
    """`pns_levels` with `hardware_from_asc` of the relative path and with that of the
    absolute path of one `.asc` file gives one object, in both orders of the two calls."""
    path = write_gradient_asc()
    monkeypatch.chdir(path.parent)
    relative = hardware_from_asc(path.name)
    absolute = hardware_from_asc(path)
    for first, second in ((relative, absolute), (absolute, relative)):
        snap = load(spin_echo_sequence())
        result = pns_levels(snap, hardware=first)
        assert pns_levels(snap, hardware=second) is result
