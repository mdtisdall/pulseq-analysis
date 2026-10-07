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
    signed,
    spin_echo_sequence,
)

from pulseq_analysis import pns_levels as pns_levels_module
from pulseq_analysis.asc import hardware_from_asc, hardware_name, read_gradient_asc
from pulseq_analysis.pns_levels import BIN_S, NO_GRADIENTS, PEAK_TOLERANCE, pns_levels

_LIMIT = GAMMA_1H  # Hz/T: the stimulation limit for 1H, a fraction of 1 times GAMMA_1H


@pytest.fixture(scope="module")
def default_seq():
    return spin_echo_sequence()


@pytest.fixture(scope="module")
def example(default_seq):
    return pns_levels(default_seq, hardware=EXAMPLE_HW)


def test_example_hardware_for_spin_echo(example, default_seq):
    """`pns_levels` with the example hardware gives, for the spin echo sequence, the peak,
    the peak time and the axis peaks of `seq.calculate_pns` of the pinned fork (each
    divided by `seq.system.gamma`, within a relative 1e-6 of the peak, as in
    `test_summary_matches_calculate_pns_within_the_fork_tolerance`), and they are below the
    stimulation limit and highest on y."""
    _, norm, comp, t = default_seq.calculate_pns(safe_example_hw(), do_plots=False)
    ref_peak = float(norm.max())
    ref_peak_time = float(t[int(np.flatnonzero(norm >= ref_peak * (1 - PEAK_TOLERANCE))[0])])
    tol = 1e-6 * ref_peak
    gamma = default_seq.system.gamma
    assert example.reason is None
    assert example.hardware == EXAMPLE_HW[1]
    assert list(example.axis_peaks_hz_per_t) == ["x", "y", "z"]
    assert 0 < example.peak_hz_per_t < _LIMIT
    peaks = example.axis_peaks_hz_per_t
    assert max(peaks, key=peaks.get) == "y"  # the crushers
    assert example.peak_hz_per_t / gamma == pytest.approx(ref_peak, abs=tol)
    assert example.peak_time_s == pytest.approx(ref_peak_time, abs=1e-9)
    for i, axis in enumerate("xyz"):
        assert peaks[axis] / gamma == pytest.approx(float(comp[:, i].max()), abs=tol)


def test_asc_file_with_a_missing_include(write_gradient_asc):
    path = write_gradient_asc(split=True)
    safety = path.with_name(f"{path.stem}_GSWD_SAFETY.asc")
    safety.unlink()
    with pytest.raises(FileNotFoundError, match=f"{path.name} includes {safety.name}"):
        read_gradient_asc(path)


def test_asc_files_that_include_each_other(tmp_path):
    (tmp_path / "a.asc").write_text("x = 1\n$INCLUDE b.asc\n")
    (tmp_path / "b.asc").write_text("y = 2\n$INCLUDE a.asc\n")
    with pytest.raises(ValueError, match=r"a\.asc.*b\.asc.*a\.asc"):
        read_gradient_asc(tmp_path / "a.asc")


def test_asc_file_that_includes_itself(tmp_path):
    (tmp_path / "a.asc").write_text("x = 1\n$INCLUDE a.asc\n")
    with pytest.raises(ValueError, match=r"a\.asc.*a\.asc"):
        read_gradient_asc(tmp_path / "a.asc")


def test_asc_file_included_by_two_branches_is_not_a_cycle(tmp_path):
    (tmp_path / "shared.asc").write_text("z = 3\n")
    (tmp_path / "b.asc").write_text("$INCLUDE shared.asc\n")
    (tmp_path / "c.asc").write_text("$INCLUDE shared.asc\n")
    main = tmp_path / "main.asc"
    main.write_text("x = 1\n$INCLUDE b.asc\n$INCLUDE c.asc\n")
    assert read_gradient_asc(main) == {"x": 1, "z": 3}


def test_included_fields_replace_fields_with_the_same_name(tmp_path):
    (tmp_path / "inc.asc").write_text('a.b[1] = 3\nc = "new"\n')
    main = tmp_path / "main.asc"
    main.write_text('a.b[0] = 1\na.b[1] = 2\nc = "old"\n$INCLUDE inc.asc\n')
    assert read_gradient_asc(main) == {"a": {"b": {0: 1, 1: 3}}, "c": "new"}


def test_hardware_name():
    assert hardware_name({"asCOMP": {0: {"tName": "GPAK2309"}}}) == "GPAK2309"
    assert hardware_name({"asCOMP": {"tName": "MP_GPA_TEST"}}) == "MP_GPA_TEST"
    assert hardware_name({}) == "unknown"


def test_prediction_scales_with_the_stimulation_limit(default_seq, example, write_gradient_asc):
    p = pns_levels(default_seq, hardware=hardware_from_asc(write_gradient_asc(limit_scale=0.1)))
    assert p.peak_hz_per_t == pytest.approx(10 * example.peak_hz_per_t, rel=1e-9)
    assert p.peak_hz_per_t > _LIMIT


def test_no_gradients_with_rf_and_adc():
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(block_pulse("excitation", np.pi / 2))
    seq.add_block(
        pp.make_adc(num_samples=64, dwell=20e-6, delay=SYSTEM.adc_dead_time, system=SYSTEM)
    )
    assert pns_levels(seq, hardware=EXAMPLE_HW).reason == NO_GRADIENTS


@pytest.mark.parametrize("channel", ["x", "y", "z"])
def test_a_gradient_on_one_axis_has_a_prediction(channel):
    seq = signed(pp.Sequence(SYSTEM))
    seq.add_block(pp.make_delay(1e-3))
    seq.add_block(pp.make_trapezoid(channel=channel, area=1000, system=SYSTEM))
    p = pns_levels(seq, hardware=EXAMPLE_HW)
    assert p.reason is None
    assert p.peak_hz_per_t > 0


def test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence(monkeypatch):
    """`pns_levels` samples an on-raster sequence with
    `GradientSampler.block_samples`, not `seq.get_gradients()` (unlike the old
    `seq.calculate_pns`-based prediction), so `get_gradients` is never called."""
    seq = spin_echo_sequence()
    calls = []
    get_gradients = seq.get_gradients

    def counted(*args, **kwargs):
        calls.append(1)
        return get_gradients(*args, **kwargs)

    monkeypatch.setattr(seq, "get_gradients", counted)
    pns_levels(seq, hardware=EXAMPLE_HW)
    assert calls == []


@pytest.mark.parametrize("use_block_cache", [True, False])
def test_prediction_keeps_no_blocks_and_gives_back_the_cache_setting(use_block_cache):
    seq = spin_echo_sequence()
    seq.use_block_cache = use_block_cache
    seq.block_cache.clear()
    pns_levels(seq, hardware=EXAMPLE_HW)
    assert seq.use_block_cache is use_block_cache
    assert not seq.block_cache


def test_prediction_propagates_an_error_and_keeps_the_cache_setting(monkeypatch):
    """An error deep inside the SAFE model (the pinned fork's chunk function)
    propagates out of `pns_levels`, and the sequence's block-cache setting and
    contents are unaffected: the block cache is only ever touched inside
    `seq_index.block_cache_off`'s own `try`/`finally`, which has already restored it
    by the time the chunk function runs (`GradientSampler` is built first)."""
    seq = spin_echo_sequence()
    seq.use_block_cache = True

    def fail(*args, **kwargs):
        raise RuntimeError("chunk failed")

    monkeypatch.setattr(pns_levels_module, "_safe_gwf_to_pns_chunk", fail)
    with pytest.raises(RuntimeError, match="chunk failed"):
        pns_levels(seq, hardware=EXAMPLE_HW)
    assert seq.use_block_cache is True
    assert not seq.block_cache


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


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file(write_gradient_asc, split):
    """`hardware_from_asc(path)` is the pair `(asc_to_hw(asc), hardware_name(asc))` of
    `asc = read_gradient_asc(path)`, field by field, for the plain layout and for the layout
    of a scanner file (a main file that includes the PNS parameters with `$INCLUDE`)."""
    path = write_gradient_asc(split=split)
    asc = read_gradient_asc(path)
    expected = asc_to_hw(asc)

    hardware = hardware_from_asc(path)
    assert isinstance(hardware, tuple)
    struct, label = hardware
    assert label == hardware_name(asc) == "MP_GPA_TEST"
    assert vars(struct).keys() == vars(expected).keys()
    for axis in "xyz":
        assert vars(getattr(struct, axis)) == vars(getattr(expected, axis))


def test_pns_levels_keeps_one_result_for_equal_hardware_pairs(monkeypatch):
    """Two `hardware` pairs with the same label and the same field values, with two
    different struct objects, are one hardware: the second call runs no model and gives
    the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()

    first = pns_levels(seq, hardware=(safe_example_hw(), "LABEL"))
    second = pns_levels(seq, hardware=(safe_example_hw(), "LABEL"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_computes_again_for_another_label_or_value(monkeypatch):
    """A `hardware` pair with another label, or with one other field value, is another
    hardware and runs the model; going back to an earlier pair does not run it again (the
    calls for pairs a, a, b (label), c (value), a, c give 3)."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    other_value = safe_example_hw()
    other_value.z.stim_limit += 1.0

    pns_levels(seq, hardware=(safe_example_hw(), "A"))
    pns_levels(seq, hardware=(safe_example_hw(), "A"))
    assert len(calls) == 1
    pns_levels(seq, hardware=(safe_example_hw(), "B"))
    assert len(calls) == 2
    pns_levels(seq, hardware=(other_value, "A"))
    assert len(calls) == 3
    pns_levels(seq, hardware=(safe_example_hw(), "A"))
    pns_levels(seq, hardware=(other_value, "A"))
    assert len(calls) == 3


@pytest.mark.parametrize("axis", "xyz")
@pytest.mark.parametrize("field", pns_levels_module._HW_FIELDS)
def test_pns_levels_keys_the_hardware_on_each_field_of_each_axis(default_seq, axis, field):
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

    kept = pns_levels(default_seq, hardware=(safe_example_hw(), "LABEL"))
    changed = pns_levels(default_seq, hardware=(struct, "LABEL"))
    assert changed is not kept
    assert pns_levels(default_seq, hardware=(safe_example_hw(), "LABEL")) is kept


def test_pns_levels_ignores_stim_thresh_in_the_hardware_key(monkeypatch):
    """Two `hardware` pairs with the same label that differ only in `z.stim_thresh` are one
    hardware: the second call runs no model and gives the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    other_thresh = safe_example_hw()
    other_thresh.z.stim_thresh += 1.0

    first = pns_levels(seq, hardware=(safe_example_hw(), "A"))
    second = pns_levels(seq, hardware=(other_thresh, "A"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_keys_a_hardware_from_an_asc_file_by_its_label_and_values(
    monkeypatch, write_gradient_asc
):
    """The key of a pair from a file is its label and its values, as for any pair: the
    pair of `hardware_from_asc`, a pair made again by hand from the same file, and a pair
    from the file read again are one hardware; the same values with another label are
    another, and so is `EXAMPLE_HW` (the same values, another label). Each of the two
    hardwares runs the model one time, in two rounds."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    path = write_gradient_asc()
    asc = read_gradient_asc(path)
    from_file = hardware_from_asc(path)
    relabelled = (from_file[0], "OTHER")

    first = pns_levels(seq, hardware=from_file)
    assert len(calls) == 1
    for _ in range(2):
        assert pns_levels(seq, hardware=hardware_from_asc(path)) is first
        assert pns_levels(seq, hardware=(asc_to_hw(asc), hardware_name(asc))) is first
    assert len(calls) == 1

    for _ in range(2):
        pns_levels(seq, hardware=relabelled)
        pns_levels(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 3


def test_pns_levels_needs_hardware(monkeypatch):
    """`pns_levels` without `hardware` raises `TypeError` ("hardware"), before the
    sequence is read: the functions that read the rotations and the block table of the
    sequence are replaced by ones that fail, and the error is still the `TypeError`."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence was read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    with pytest.raises(TypeError, match="hardware"):
        pns_levels(spin_echo_sequence())  # type: ignore[call-arg]


@pytest.mark.parametrize("hardware", NOT_A_PAIR)
def test_pns_levels_refuses_a_hardware_that_is_not_a_pair_before_any_work(monkeypatch, hardware):
    """`pns_levels` with a `hardware` that is not a tuple of two items with a `str`
    second item raises `TypeError` ("hardware"), before the sequence is read and before the
    kept results are touched: the functions that read the sequence and `kept_results` are
    replaced by ones that fail, and the error is still the `TypeError`."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence or the kept results were read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    monkeypatch.setattr(pns_levels_module, "kept_results", fail)
    with pytest.raises(TypeError, match="hardware"):
        pns_levels(spin_echo_sequence(), hardware=hardware)


@pytest.mark.parametrize(("struct", "error", "match"), BAD_STRUCTS)
def test_pns_levels_refuses_a_bad_struct_before_any_work(monkeypatch, struct, error, match):
    """`pns_levels` with a pair whose struct has no `x`, no `x.stim_thresh`,
    `x.a1 = 5.0`, `x.stim_limit = 0.0`, `x.tau1 = nan` or `x.tau1 = "0.2"` raises the error
    of that defect, with its message, before the sequence is read and before the kept
    results are touched: the functions that read the sequence and `kept_results` are
    replaced by ones that fail."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence or the kept results were read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    monkeypatch.setattr(pns_levels_module, "kept_results", fail)
    with pytest.raises(error, match=match):
        pns_levels(spin_echo_sequence(), hardware=(struct, "BAD"))


@pytest.mark.parametrize(("struct", "error", "match"), BAD_STRUCTS)
def test_pns_levels_refuses_a_bad_struct_for_a_sequence_without_gradients(struct, error, match):
    """The bad structs of `BAD_STRUCTS` raise the same errors for a sequence with no
    gradient event, which gives a result for a good struct."""
    with pytest.raises(error, match=match):
        pns_levels(empty_sequence(), hardware=(struct, "BAD"))


def test_pns_levels_refuses_a_sum_of_the_a_fields_below_1_for_a_sequence_without_gradients():
    """A struct whose `x.a1 + x.a2 + x.a3` is 0.9, more than 0.001 below 1, raises
    `ValueError` (the message names `a1 + a2 + a3`) for a sequence with no gradient event:
    the check is of the distance from 1, not of the signed difference."""
    struct = safe_example_hw()
    struct.x.a1 -= 0.1
    assert struct.x.a1 + struct.x.a2 + struct.x.a3 == pytest.approx(0.9)
    with pytest.raises(ValueError, match=r"x\.a1 \+ x\.a2 \+ x\.a3 must be 1"):
        pns_levels(empty_sequence(), hardware=(struct, "BAD"))


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
        pns_levels(empty_sequence(), hardware=(struct, "BAD"))


def test_pns_levels_keeps_one_result_for_each_tuple_of_thresholds(monkeypatch):
    """The thresholds are part of the key of a kept result: other thresholds, or the same
    ones in another order, run the model and do not give the result of the default (no
    thresholds, the key `()`); the same thresholds again give the kept result (the same
    object), and an `int` threshold is the key of the equal `float`."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    thresholds = (_LIMIT, 0.5 * _LIMIT)

    default = pns_levels(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    other = pns_levels(seq, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
    assert len(calls) == 2
    assert other is not default
    assert list(default.above) == []
    assert list(other.above) == list(thresholds)
    assert pns_levels(seq, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW) is other
    assert pns_levels(seq, hardware=EXAMPLE_HW) is default
    assert pns_levels(seq, thresholds_hz_per_t=(), hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    whole = round(_LIMIT)  # an int that is equal to the float `_LIMIT`
    assert float(whole) == _LIMIT
    assert pns_levels(seq, thresholds_hz_per_t=(whole, 0.5 * _LIMIT), hardware=EXAMPLE_HW) is other
    assert len(calls) == 2
    reordered = pns_levels(seq, thresholds_hz_per_t=thresholds[::-1], hardware=EXAMPLE_HW)
    assert len(calls) == 3
    assert list(reordered.above) == list(thresholds[::-1])


def test_pns_levels_keeps_one_result_for_each_bin_s(monkeypatch):
    """`bin_s` is part of the key of a kept result: another `bin_s` runs the model and does
    not give the result of the default (`BIN_S`); the same `bin_s` again gives the kept
    result (the same object); the default and `bin_s=BIN_S` are one key; an `int` `bin_s`
    and the equal `float` are one key; and the bins are those of the `bin_s`."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()

    default = pns_levels(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    assert pns_levels(seq, hardware=EXAMPLE_HW, bin_s=BIN_S) is default
    assert len(calls) == 1
    six = pns_levels(seq, hardware=EXAMPLE_HW, bin_s=0.006)
    assert len(calls) == 2
    assert six is not default
    assert six.bin_samples == 600
    assert default.bin_samples == 500
    assert pns_levels(seq, hardware=EXAMPLE_HW, bin_s=0.006) is six
    assert pns_levels(seq, hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    one = pns_levels(seq, hardware=EXAMPLE_HW, bin_s=1)
    assert len(calls) == 3
    assert pns_levels(seq, hardware=EXAMPLE_HW, bin_s=1.0) is one
    assert len(calls) == 3
    with_thresholds = pns_levels(
        seq, hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,), bin_s=0.006
    )
    assert with_thresholds is not six  # the thresholds and `bin_s` are both in the key
    assert len(calls) == 4


def test_pns_levels_shares_a_read_only_result():
    """Two callers of `pns_levels` get the same kept result. A change in place of its
    level by the first caller raises `ValueError`, and the second caller gets the level as
    it was."""
    seq = spin_echo_sequence()
    first = pns_levels(seq, hardware=EXAMPLE_HW)
    before_min, before_max = first.level_min_hz_per_t.copy(), first.level_max_hz_per_t.copy()
    # Through a local name: `first.level_max_hz_per_t *= 100` would also set the field of the frozen
    # dataclass.
    level_max = first.level_max_hz_per_t
    with pytest.raises(ValueError):
        level_max *= 100
    with pytest.raises(ValueError):
        first.level_min_hz_per_t[0] = 0.0
    second = pns_levels(seq, hardware=EXAMPLE_HW)
    assert second is first
    np.testing.assert_array_equal(second.level_min_hz_per_t, before_min)
    np.testing.assert_array_equal(second.level_max_hz_per_t, before_max)
