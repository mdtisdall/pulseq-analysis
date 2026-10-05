import numpy as np
import pypulseq as pp
import pytest
from pns_hardware import NOT_A_PAIR
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw
from synthetic import EXAMPLE_HW, GAMMA_1H, SYSTEM, block_pulse, empty_sequence, spin_echo_sequence

from pulseq_analysis import pns
from pulseq_analysis import pns_levels as pns_levels_module
from pulseq_analysis.asc import hardware_from_asc, hardware_name, read_gradient_asc
from pulseq_analysis.pns import pns_levels_for
from pulseq_analysis.pns_levels import BIN_S, NO_GRADIENTS

_LIMIT = GAMMA_1H  # Hz/T: the stimulation limit for 1H, a fraction of 1 times GAMMA_1H


@pytest.fixture(scope="module")
def default_seq():
    return spin_echo_sequence()


@pytest.fixture(scope="module")
def example(default_seq):
    return pns_levels_for(default_seq, hardware=EXAMPLE_HW)


def test_example_hardware_for_spin_echo(example, default_seq):
    """`pns_levels_for` with the example hardware gives the same summary fields as
    `pns_levels.pns_levels` of the same sequence and hardware."""
    ref = pns_levels_module.pns_levels(default_seq, hardware=EXAMPLE_HW)
    assert example.reason is None
    assert example.hardware == EXAMPLE_HW[1]
    assert list(example.axis_peaks_hz_per_t) == ["x", "y", "z"]
    assert 0 < example.peak_hz_per_t < _LIMIT
    peaks = example.axis_peaks_hz_per_t
    assert max(peaks, key=peaks.get) == "y"  # the crushers
    assert example.peak_hz_per_t == ref.peak_hz_per_t
    assert example.peak_time_s == ref.peak_time_s
    assert example.axis_peaks_hz_per_t == ref.axis_peaks_hz_per_t


def test_asc_file_with_the_example_parameters(default_seq, example, write_gradient_asc):
    path = write_gradient_asc()
    p = pns_levels_for(default_seq, hardware=hardware_from_asc(path))
    assert p.reason is None
    assert p.hardware == "MP_GPA_TEST"
    assert p.peak_hz_per_t == pytest.approx(example.peak_hz_per_t, rel=1e-9)
    assert p.peak_time_s == pytest.approx(example.peak_time_s, rel=1e-9)
    for axis in "xyz":
        assert p.axis_peaks_hz_per_t[axis] == pytest.approx(
            example.axis_peaks_hz_per_t[axis], rel=1e-9
        )


def test_asc_file_that_includes_the_pns_parameters(default_seq, example, write_gradient_asc):
    path = write_gradient_asc(split=True)
    p = pns_levels_for(default_seq, hardware=hardware_from_asc(path))
    assert p.reason is None
    assert p.hardware == "MP_GPA_TEST"
    assert p.peak_hz_per_t == pytest.approx(example.peak_hz_per_t, rel=1e-9)
    assert p.peak_time_s == pytest.approx(example.peak_time_s, rel=1e-9)
    for axis in "xyz":
        assert p.axis_peaks_hz_per_t[axis] == pytest.approx(
            example.axis_peaks_hz_per_t[axis], rel=1e-9
        )


def test_asc_file_with_a_missing_include(write_gradient_asc):
    path = write_gradient_asc(split=True)
    safety = path.with_name(f"{path.stem}_GSWD_SAFETY.asc")
    safety.unlink()
    with pytest.raises(FileNotFoundError, match=f"{path.name} includes {safety.name}"):
        read_gradient_asc(path)


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
    p = pns_levels_for(default_seq, hardware=hardware_from_asc(write_gradient_asc(limit_scale=0.1)))
    assert p.peak_hz_per_t == pytest.approx(10 * example.peak_hz_per_t, rel=1e-9)
    assert p.peak_hz_per_t > _LIMIT


def test_no_gradients():
    p = pns_levels_for(empty_sequence(), hardware=EXAMPLE_HW)
    assert p.reason == NO_GRADIENTS
    assert p.hardware == EXAMPLE_HW[1]
    assert p.peak_hz_per_t == 0
    assert p.peak_time_s is None


def test_no_gradients_with_rf_and_adc():
    seq = pp.Sequence(SYSTEM)
    seq.add_block(block_pulse("excitation", np.pi / 2))
    seq.add_block(
        pp.make_adc(num_samples=64, dwell=20e-6, delay=SYSTEM.adc_dead_time, system=SYSTEM)
    )
    assert pns_levels_for(seq, hardware=EXAMPLE_HW).reason == NO_GRADIENTS


@pytest.mark.parametrize("channel", ["x", "y", "z"])
def test_a_gradient_on_one_axis_has_a_prediction(channel):
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(1e-3))
    seq.add_block(pp.make_trapezoid(channel=channel, area=1000, system=SYSTEM))
    p = pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert p.reason is None
    assert p.peak_hz_per_t > 0


def test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence(monkeypatch):
    """`pns_levels_for` (`pns_levels.pns_levels`) samples an on-raster sequence with
    `GradientSampler.block_samples`, not `seq.get_gradients()` (unlike the old
    `seq.calculate_pns`-based prediction), so `get_gradients` is never called."""
    seq = spin_echo_sequence()
    calls = []
    get_gradients = seq.get_gradients

    def counted(*args, **kwargs):
        calls.append(1)
        return get_gradients(*args, **kwargs)

    monkeypatch.setattr(seq, "get_gradients", counted)
    pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert calls == []


@pytest.mark.parametrize("use_block_cache", [True, False])
def test_prediction_keeps_no_blocks_and_gives_back_the_cache_setting(use_block_cache):
    seq = spin_echo_sequence()
    seq.use_block_cache = use_block_cache
    seq.block_cache.clear()
    pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert seq.use_block_cache is use_block_cache
    assert not seq.block_cache


def test_prediction_propagates_an_error_and_keeps_the_cache_setting(monkeypatch):
    """An error deep inside the SAFE model (the pinned fork's chunk function)
    propagates out of `pns_levels_for`, and the sequence's block-cache setting and
    contents are unaffected: the block cache is only ever touched inside
    `seq_index.block_cache_off`'s own `try`/`finally`, which has already restored it
    by the time the chunk function runs (`GradientSampler` is built first)."""
    seq = spin_echo_sequence()
    seq.use_block_cache = True

    def fail(*args, **kwargs):
        raise RuntimeError("chunk failed")

    monkeypatch.setattr(pns_levels_module, "_safe_gwf_to_pns_chunk", fail)
    with pytest.raises(RuntimeError, match="chunk failed"):
        pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert seq.use_block_cache is True
    assert not seq.block_cache


def _count_pns_levels_calls(monkeypatch) -> list:
    """Patches `pns.pns_levels` (the name that `pns.pns_levels_for` calls) with a wrapper
    that records one entry for each call, and returns the list."""
    calls: list = []
    original = pns.pns_levels

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pns, "pns_levels", counted)
    return calls


def test_pns_levels_for_keeps_one_result_for_each_asc_file(monkeypatch, write_gradient_asc):
    """`pns_levels_for` keeps one result for each (sequence, `hardware_from_asc` of a
    gradient .asc file): the same file is cached, a different file computes once, and going
    back to the first file does not compute again (a, a, b, a gives 2 calls)."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    hardware_a = hardware_from_asc(write_gradient_asc(name="MP_GPA_A"))
    hardware_b = hardware_from_asc(write_gradient_asc(name="MP_GPA_B"))

    pns_levels_for(seq, hardware=hardware_a)
    assert len(calls) == 1
    pns_levels_for(seq, hardware=hardware_a)  # same sequence, same hardware: cached
    assert len(calls) == 1
    pns_levels_for(seq, hardware=hardware_b)  # a different hardware: computes
    assert len(calls) == 2
    pns_levels_for(seq, hardware=hardware_a)  # back to hardware_a: cached
    assert len(calls) == 2


def test_pns_levels_for_alternating_two_hardwares_runs_the_model_two_times(
    monkeypatch, write_gradient_asc
):
    """Two keys alternated (a, b, a, b) run the model two times, not four: the example
    hardware and the pair of a file are two hardwares of one sequence."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    from_file = hardware_from_asc(write_gradient_asc())

    for hardware in (EXAMPLE_HW, from_file) * 2:
        pns_levels_for(seq, hardware=hardware)
    assert len(calls) == 2


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


def test_pns_levels_for_keeps_one_result_for_equal_hardware_pairs(monkeypatch):
    """Two `hardware` pairs with the same label and the same field values, with two
    different struct objects, are one hardware: the second call runs no model and gives
    the kept result."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()

    first = pns_levels_for(seq, hardware=(safe_example_hw(), "LABEL"))
    second = pns_levels_for(seq, hardware=(safe_example_hw(), "LABEL"))
    assert len(calls) == 1
    assert second is first


def test_pns_levels_for_computes_again_for_another_label_or_value(monkeypatch):
    """A `hardware` pair with another label, or with one other field value, is another
    hardware and runs the model; going back to an earlier pair does not run it again (the
    calls for pairs a, a, b (label), c (value), a, c give 3)."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    other_value = safe_example_hw()
    other_value.z.stim_thresh += 1.0

    pns_levels_for(seq, hardware=(safe_example_hw(), "A"))
    pns_levels_for(seq, hardware=(safe_example_hw(), "A"))
    assert len(calls) == 1
    pns_levels_for(seq, hardware=(safe_example_hw(), "B"))
    assert len(calls) == 2
    pns_levels_for(seq, hardware=(other_value, "A"))
    assert len(calls) == 3
    pns_levels_for(seq, hardware=(safe_example_hw(), "A"))
    pns_levels_for(seq, hardware=(other_value, "A"))
    assert len(calls) == 3


def test_pns_levels_for_keys_a_hardware_from_an_asc_file_by_its_label_and_values(
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

    first = pns_levels_for(seq, hardware=from_file)
    assert len(calls) == 1
    for _ in range(2):
        assert pns_levels_for(seq, hardware=hardware_from_asc(path)) is first
        assert pns_levels_for(seq, hardware=(asc_to_hw(asc), hardware_name(asc))) is first
    assert len(calls) == 1

    for _ in range(2):
        pns_levels_for(seq, hardware=relabelled)
        pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 3


def test_pns_levels_for_needs_hardware(monkeypatch):
    """`pns_levels_for` without `hardware` raises `TypeError` ("hardware"), before the
    sequence is read: the functions that read the rotations and the block table of the
    sequence are replaced by ones that fail, and the error is still the `TypeError`."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence was read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    with pytest.raises(TypeError, match="hardware"):
        pns_levels_for(spin_echo_sequence())  # type: ignore[call-arg]


@pytest.mark.parametrize("hardware", NOT_A_PAIR)
def test_pns_levels_for_refuses_a_hardware_that_is_not_a_pair_before_any_work(
    monkeypatch, hardware
):
    """`pns_levels_for` with a `hardware` that is not a tuple of two items with a `str`
    second item raises `TypeError` ("hardware"), before the sequence is read and before the
    kept results are touched: the functions that read the sequence and `kept_results` are
    replaced by ones that fail, and the error is still the `TypeError`."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence or the kept results were read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    monkeypatch.setattr(pns, "kept_results", fail)
    with pytest.raises(TypeError, match="hardware"):
        pns_levels_for(spin_echo_sequence(), hardware=hardware)


def test_pns_levels_for_keeps_one_result_for_each_tuple_of_thresholds(monkeypatch):
    """The thresholds are part of the key of a kept result: other thresholds, or the same
    ones in another order, run the model and do not give the result of the default (no
    thresholds, the key `()`); the same thresholds again give the kept result (the same
    object), and an `int` threshold is the key of the equal `float`."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    thresholds = (_LIMIT, 0.5 * _LIMIT)

    default = pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    other = pns_levels_for(seq, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW)
    assert len(calls) == 2
    assert other is not default
    assert list(default.above) == []
    assert list(other.above) == list(thresholds)
    assert pns_levels_for(seq, thresholds_hz_per_t=thresholds, hardware=EXAMPLE_HW) is other
    assert pns_levels_for(seq, hardware=EXAMPLE_HW) is default
    assert pns_levels_for(seq, thresholds_hz_per_t=(), hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    whole = round(_LIMIT)  # an int that is equal to the float `_LIMIT`
    assert float(whole) == _LIMIT
    assert (
        pns_levels_for(seq, thresholds_hz_per_t=(whole, 0.5 * _LIMIT), hardware=EXAMPLE_HW) is other
    )
    assert len(calls) == 2
    reordered = pns_levels_for(seq, thresholds_hz_per_t=thresholds[::-1], hardware=EXAMPLE_HW)
    assert len(calls) == 3
    assert list(reordered.above) == list(thresholds[::-1])


def test_pns_levels_for_keeps_one_result_for_each_bin_s(monkeypatch):
    """`bin_s` is part of the key of a kept result: another `bin_s` runs the model and does
    not give the result of the default (`BIN_S`); the same `bin_s` again gives the kept
    result (the same object); the default and `bin_s=BIN_S` are one key; an `int` `bin_s`
    and the equal `float` are one key; and the bins are those of the `bin_s`."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()

    default = pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert len(calls) == 1
    assert pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=BIN_S) is default
    assert len(calls) == 1
    six = pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=0.006)
    assert len(calls) == 2
    assert six is not default
    assert six.bin_samples == 600
    assert default.bin_samples == 615
    assert pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=0.006) is six
    assert pns_levels_for(seq, hardware=EXAMPLE_HW) is default
    assert len(calls) == 2
    one = pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=1)
    assert len(calls) == 3
    assert pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=1.0) is one
    assert len(calls) == 3
    with_thresholds = pns_levels_for(
        seq, hardware=EXAMPLE_HW, thresholds_hz_per_t=(_LIMIT,), bin_s=0.006
    )
    assert with_thresholds is not six  # the thresholds and `bin_s` are both in the key
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("bin_s", "error"),
    [
        pytest.param(True, TypeError, id="bool"),
        pytest.param("0.006", TypeError, id="string"),
        pytest.param(None, TypeError, id="none"),
        pytest.param(float("nan"), ValueError, id="nan"),
        pytest.param(float("inf"), ValueError, id="inf"),
        pytest.param(0, ValueError, id="zero"),
        pytest.param(-0.006, ValueError, id="negative"),
    ],
)
def test_pns_levels_for_refuses_a_bad_bin_s_before_any_work(monkeypatch, bin_s, error):
    """`pns_levels_for` raises `TypeError` for a `bin_s` that is a `bool` or not a real
    number and `ValueError` for one that is not finite or not above 0, before the sequence
    is read and before the kept results are touched: the functions that read the sequence
    and `kept_results` are replaced by ones that fail, and the error is still the one of
    `bin_s`."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence or the kept results were read")

    monkeypatch.setattr("pulseq_analysis.pns_levels.refuse_rotations", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    monkeypatch.setattr(pns, "kept_results", fail)
    with pytest.raises(error, match="bin_s"):
        pns_levels_for(spin_echo_sequence(), hardware=EXAMPLE_HW, bin_s=bin_s)


@pytest.mark.parametrize(
    ("thresholds", "error"),
    [
        pytest.param([1.0], TypeError, id="list"),
        pytest.param((True,), TypeError, id="bool"),
        pytest.param(("1.0",), TypeError, id="string"),
        pytest.param((0.0,), ValueError, id="zero"),
        pytest.param((1.0, 1.0), ValueError, id="equal floats"),
    ],
)
def test_pns_levels_for_refuses_bad_thresholds_before_any_work(monkeypatch, thresholds, error):
    """`pns_levels_for` raises `TypeError` for thresholds that are not a tuple or have a
    `bool` or a value that is not a real number, and `ValueError` for a value not above 0
    or a repeat, before the sequence is read and before the kept results are read."""

    def fail(*args, **kwargs):
        raise RuntimeError("the sequence was read")

    monkeypatch.setattr(pns, "kept_results", fail)
    monkeypatch.setattr("pulseq_analysis.pns_levels.sequence_index", fail)
    with pytest.raises(error, match="threshold"):
        pns_levels_for(spin_echo_sequence(), hardware=EXAMPLE_HW, thresholds_hz_per_t=thresholds)


def test_pns_levels_for_shares_a_read_only_result():
    """Two callers of `pns_levels_for` get the same kept result. A change in place of its
    level by the first caller raises `ValueError`, and the second caller gets the level as
    it was."""
    seq = spin_echo_sequence()
    first = pns_levels_for(seq, hardware=EXAMPLE_HW)
    before_min, before_max = first.level_min_hz_per_t.copy(), first.level_max_hz_per_t.copy()
    # Through a local name: `first.level_max_hz_per_t *= 100` would also set the field of the frozen
    # dataclass.
    level_max = first.level_max_hz_per_t
    with pytest.raises(ValueError):
        level_max *= 100
    with pytest.raises(ValueError):
        first.level_min_hz_per_t[0] = 0.0
    second = pns_levels_for(seq, hardware=EXAMPLE_HW)
    assert second is first
    np.testing.assert_array_equal(second.level_min_hz_per_t, before_min)
    np.testing.assert_array_equal(second.level_max_hz_per_t, before_max)
