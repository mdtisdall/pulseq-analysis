import numpy as np
import pypulseq as pp
import pytest
from pns_hardware import BAD_STRUCTS, NOT_A_PAIR
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw
from synthetic import (
    EXAMPLE_HW,
    GAMMA_1H,
    SYSTEM,
    block_pulse,
    empty_sequence,
    spin_echo_sequence,
)

from pulseq_analysis import pns_levels as pns_levels_module
from pulseq_analysis.asc import hardware_from_asc, hardware_name, read_gradient_asc
from pulseq_analysis.pns_levels import BIN_S, NO_GRADIENTS, pns_levels
from pulseq_analysis.safe import SafeHardware
from pulseq_analysis.snapshot import load

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


def test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence(monkeypatch):
    """`pns_levels` samples an on-raster sequence with
    `GradientSampler.block_samples`, not `seq.get_gradients()` (unlike the old
    `seq.calculate_pns`-based prediction), so `get_gradients` is never called."""
    snap = load(spin_echo_sequence())
    calls = []
    get_gradients = snap.sequence.get_gradients

    def counted(*args, **kwargs):
        calls.append(1)
        return get_gradients(*args, **kwargs)

    monkeypatch.setattr(snap.sequence, "get_gradients", counted)
    pns_levels(snap, hardware=EXAMPLE_HW)
    assert calls == []


def test_prediction_keeps_no_blocks():
    """`load` turns the block cache of the private sequence off, and `pns_levels` leaves it off
    and empty: `use_block_cache` is False and `block_cache` has no block."""
    snap = load(spin_echo_sequence())
    pns_levels(snap, hardware=EXAMPLE_HW)
    assert snap.sequence.use_block_cache is False
    assert not snap.sequence.block_cache


def test_prediction_propagates_an_error_and_keeps_the_cache_off(monkeypatch):
    """An error deep inside the SAFE model (the pinned fork's chunk function)
    propagates out of `pns_levels`, and the block cache of the private sequence stays off and
    empty."""
    snap = load(spin_echo_sequence())

    def fail(*args, **kwargs):
        raise RuntimeError("chunk failed")

    monkeypatch.setattr(pns_levels_module, "_safe_gwf_to_pns_chunk", fail)
    with pytest.raises(RuntimeError, match="chunk failed"):
        pns_levels(snap, hardware=EXAMPLE_HW)
    assert snap.sequence.use_block_cache is False
    assert not snap.sequence.block_cache


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


def test_pns_levels_keeps_one_result_for_equal_hardware_pairs(monkeypatch):
    """Two `hardware` pairs with the same label and the same field values, with two
    different struct objects, are one hardware: the second call runs no model and gives
    the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())

    first = pns_levels(snap, hardware=(safe_example_hw(), "LABEL"))
    second = pns_levels(snap, hardware=(safe_example_hw(), "LABEL"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_computes_again_for_another_label_or_value(monkeypatch):
    """A `hardware` pair with another label, or with one other field value, is another
    hardware and runs the model; going back to an earlier pair does not run it again (the
    calls for pairs a, a, b (label), c (value), a, c give 3)."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    other_value = safe_example_hw()
    other_value.z.stim_limit += 1.0

    pns_levels(snap, hardware=(safe_example_hw(), "A"))
    pns_levels(snap, hardware=(safe_example_hw(), "A"))
    assert len(calls) == 1
    pns_levels(snap, hardware=(safe_example_hw(), "B"))
    assert len(calls) == 2
    pns_levels(snap, hardware=(other_value, "A"))
    assert len(calls) == 3
    pns_levels(snap, hardware=(safe_example_hw(), "A"))
    pns_levels(snap, hardware=(other_value, "A"))
    assert len(calls) == 3


@pytest.mark.parametrize("axis", "xyz")
@pytest.mark.parametrize("field", pns_levels_module._HW_FIELDS)
def test_pns_levels_keys_the_hardware_on_each_field_of_each_axis(default_snap, axis, field):
    """A struct that differs from the example struct in one field of one axis (`_HW_FIELDS`,
    each of the 8 fields of each of the 3 axes), with the same label, is another hardware: the
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

    kept = pns_levels(default_snap, hardware=(safe_example_hw(), "LABEL"))
    changed = pns_levels(default_snap, hardware=(struct, "LABEL"))
    assert changed is not kept
    assert pns_levels(default_snap, hardware=(safe_example_hw(), "LABEL")) is kept


def test_pns_levels_ignores_stim_thresh_in_the_hardware_key(monkeypatch):
    """Two `hardware` pairs with the same label that differ only in `z.stim_thresh` are one
    hardware: the second call runs no model and gives the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    other_thresh = safe_example_hw()
    other_thresh.z.stim_thresh += 1.0

    first = pns_levels(snap, hardware=(safe_example_hw(), "A"))
    second = pns_levels(snap, hardware=(other_thresh, "A"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_keeps_one_result_for_a_safe_hardware_and_its_namespace(monkeypatch):
    """A `SafeHardware` and the namespace with the same values, with the same label, are one
    hardware: the call with the namespace runs the model one time, and the call with the
    `SafeHardware` gives the kept result (`is`). The same values with another label are
    another hardware."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    namespace_pair = (safe_example_hw(), "A")
    safe_pair = (SafeHardware.from_namespace(safe_example_hw()), "A")

    first = pns_levels(snap, hardware=namespace_pair)
    assert pns_levels(snap, hardware=safe_pair) is first
    assert len(calls) == 1
    assert pns_levels(snap, hardware=(safe_pair[0], "B")) is not first
    assert len(calls) == 2


def test_pns_levels_keys_a_hardware_from_an_asc_file_by_its_label_and_values(
    monkeypatch, write_gradient_asc
):
    """The key of a pair from a file is its label and its values, as for any pair: the
    pair of `hardware_from_asc`, a pair made again by hand from the same file, and a pair
    from the file read again are one hardware; the same values with another label are
    another, and so is `EXAMPLE_HW` (the same values, another label). Each of the two
    hardwares runs the model one time, in two rounds."""
    calls = _count_pns_levels_calls(monkeypatch)
    snap = load(spin_echo_sequence())
    path = write_gradient_asc()
    asc = read_gradient_asc(path)
    from_file = hardware_from_asc(path)
    relabelled = (from_file[0], "OTHER")

    first = pns_levels(snap, hardware=from_file)
    assert len(calls) == 1
    for _ in range(2):
        assert pns_levels(snap, hardware=hardware_from_asc(path)) is first
        assert pns_levels(snap, hardware=(asc_to_hw(asc), hardware_name(asc))) is first
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


@pytest.mark.parametrize("hardware", NOT_A_PAIR)
def test_pns_levels_refuses_a_hardware_that_is_not_a_pair_before_the_snapshot_type(hardware):
    """`pns_levels` with a `hardware` that is not a tuple of two items with a `str`
    second item raises `TypeError` ("hardware"), before the type of the first argument is
    checked: the first argument is a `pp.Sequence`, which is not a snapshot and would raise the
    `TypeError` that names `load`, and the error is still the one of `hardware`."""
    with pytest.raises(TypeError, match="hardware"):
        pns_levels(spin_echo_sequence(), hardware=hardware)


@pytest.mark.parametrize(("struct", "error", "match"), BAD_STRUCTS)
def test_pns_levels_refuses_a_bad_struct_before_the_snapshot_type(struct, error, match):
    """`pns_levels` with a pair whose struct has no `x`, no `x.stim_thresh`,
    `x.a1 = 5.0`, `x.stim_limit = 0.0`, `x.tau1 = nan` or `x.tau1 = "0.2"` raises the error
    of that defect, with its message, before the type of the first argument is checked: the
    first argument is a `pp.Sequence`, which is not a snapshot."""
    with pytest.raises(error, match=match):
        pns_levels(spin_echo_sequence(), hardware=(struct, "BAD"))


@pytest.mark.parametrize(("struct", "error", "match"), BAD_STRUCTS)
def test_pns_levels_refuses_a_bad_struct_for_a_sequence_without_gradients(struct, error, match):
    """The bad structs of `BAD_STRUCTS` raise the same errors for a sequence with no
    gradient event, which gives a result for a good struct."""
    with pytest.raises(error, match=match):
        pns_levels(load(empty_sequence()), hardware=(struct, "BAD"))


def test_pns_levels_refuses_a_sum_of_the_a_fields_below_1_for_a_sequence_without_gradients():
    """A struct whose `x.a1 + x.a2 + x.a3` is 0.9, more than 0.001 below 1, raises
    `ValueError` (the message names `a1 + a2 + a3`) for a sequence with no gradient event:
    the check is of the distance from 1, not of the signed difference."""
    struct = safe_example_hw()
    struct.x.a1 -= 0.1
    assert struct.x.a1 + struct.x.a2 + struct.x.a3 == pytest.approx(0.9)
    with pytest.raises(ValueError, match=r"x\.a1 \+ x\.a2 \+ x\.a3 must be 1"):
        pns_levels(load(empty_sequence()), hardware=(struct, "BAD"))


@pytest.mark.parametrize("axis", "xyz")
def test_pns_levels_refuses_a_sum_of_the_a_fields_that_is_1_005(axis):
    """A struct whose `a1 + a2 + a3` on one axis is 1.005, more than 0.001 above 1, raises
    `ValueError` (the message names `a1 + a2 + a3` of that axis) for a sequence with no
    gradient event. The sum 0.9 of the test above is far from the limit: this one is 0.004
    beyond it, so a limit of 0.01 would accept it."""
    struct = safe_example_hw()
    axis_struct = getattr(struct, axis)
    axis_struct.a1 += 1.005 - (axis_struct.a1 + axis_struct.a2 + axis_struct.a3)
    assert axis_struct.a1 + axis_struct.a2 + axis_struct.a3 == pytest.approx(1.005, abs=1e-12)
    with pytest.raises(ValueError, match=rf"{axis}\.a1 \+ {axis}\.a2 \+ {axis}\.a3 must be 1"):
        pns_levels(load(empty_sequence()), hardware=(struct, "BAD"))


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
    and the equal `float` are one key; and the bins are those of the `bin_s`."""
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
    assert pns_levels(snap, hardware=EXAMPLE_HW, bin_s=0.006) is six
    assert pns_levels(snap, hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    one = pns_levels(snap, hardware=EXAMPLE_HW, bin_s=1)
    assert len(calls) == 3
    assert pns_levels(snap, hardware=EXAMPLE_HW, bin_s=1.0) is one
    assert len(calls) == 3
    with_thresholds = pns_levels(
        snap, hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,), bin_s=0.006
    )
    assert with_thresholds is not six  # the thresholds and `bin_s` are both in the key
    assert len(calls) == 4


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
