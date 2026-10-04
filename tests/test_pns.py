import dataclasses

import numpy as np
import pypulseq as pp
import pytest
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw
from synthetic import SYSTEM, block_pulse, empty_sequence, spin_echo_sequence

from pulseq_analysis import pns
from pulseq_analysis import pns_levels as pns_levels_module
from pulseq_analysis.asc import EXAMPLE_HARDWARE, hardware_name, read_gradient_asc
from pulseq_analysis.pns import pns_levels_for
from pulseq_analysis.pns_levels import NO_GRADIENTS, PnsLevels


@pytest.fixture(scope="module")
def default_seq():
    return spin_echo_sequence()


@pytest.fixture(scope="module")
def example(default_seq):
    return pns.pns_prediction(default_seq)


def test_example_hardware_for_spin_echo(example, default_seq):
    """The summary equals `pns_levels.pns_levels` of the same sequence and hardware
    (task 4.4 of `docs/plans/diagram-lanes.md`: `PnsPrediction` is now built from
    `PnsLevels`)."""
    ref = pns_levels_module.pns_levels(default_seq)
    assert example.reason is None
    assert example.hardware == EXAMPLE_HARDWARE
    assert example.asc_file is None
    assert list(example.axis_peaks) == ["x", "y", "z"]
    assert 0 < example.peak < 1
    assert max(example.axis_peaks, key=example.axis_peaks.get) == "y"  # the crushers
    assert example.peak == ref.peak
    assert example.peak_time_s == ref.peak_time_s
    assert example.axis_peaks == ref.axis_peaks


def test_asc_file_with_the_example_parameters(default_seq, example, write_gradient_asc):
    path = write_gradient_asc()
    p = pns.pns_prediction(default_seq, gradient_asc=path)
    assert p.reason is None
    assert p.hardware == "MP_GPA_TEST"
    assert p.asc_file == path.name
    assert p.peak == pytest.approx(example.peak, rel=1e-9)
    assert p.peak_time_s == pytest.approx(example.peak_time_s, rel=1e-9)
    for axis in "xyz":
        assert p.axis_peaks[axis] == pytest.approx(example.axis_peaks[axis], rel=1e-9)


def test_asc_file_that_includes_the_pns_parameters(default_seq, example, write_gradient_asc):
    path = write_gradient_asc(split=True)
    p = pns.pns_prediction(default_seq, gradient_asc=path)
    assert p.reason is None
    assert p.hardware == "MP_GPA_TEST"
    assert p.asc_file == path.name
    assert p.peak == pytest.approx(example.peak, rel=1e-9)
    assert p.peak_time_s == pytest.approx(example.peak_time_s, rel=1e-9)
    for axis in "xyz":
        assert p.axis_peaks[axis] == pytest.approx(example.axis_peaks[axis], rel=1e-9)


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
    p = pns.pns_prediction(default_seq, gradient_asc=write_gradient_asc(limit_scale=0.1))
    assert p.peak == pytest.approx(10 * example.peak, rel=1e-9)
    assert p.peak > 1


def test_no_gradients():
    p = pns.pns_prediction(empty_sequence())
    assert p.reason == NO_GRADIENTS
    assert p.hardware == EXAMPLE_HARDWARE
    assert p.peak == 0
    assert p.peak_time_s is None


def test_no_gradients_with_rf_and_adc():
    seq = pp.Sequence(SYSTEM)
    seq.add_block(block_pulse("excitation", np.pi / 2))
    seq.add_block(
        pp.make_adc(num_samples=64, dwell=20e-6, delay=SYSTEM.adc_dead_time, system=SYSTEM)
    )
    assert pns.pns_prediction(seq).reason == NO_GRADIENTS


@pytest.mark.parametrize("channel", ["x", "y", "z"])
def test_a_gradient_on_one_axis_has_a_prediction(channel):
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(1e-3))
    seq.add_block(pp.make_trapezoid(channel=channel, area=1000, system=SYSTEM))
    p = pns.pns_prediction(seq)
    assert p.reason is None
    assert p.peak > 0


def test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence(monkeypatch):
    """`pns_prediction` (`pns_levels.pns_levels`) samples an on-raster sequence with
    `GradientSampler.block_samples`, not `seq.get_gradients()` (unlike the old
    `seq.calculate_pns`-based prediction), so `get_gradients` is never called."""
    seq = spin_echo_sequence()
    calls = []
    get_gradients = seq.get_gradients

    def counted(*args, **kwargs):
        calls.append(1)
        return get_gradients(*args, **kwargs)

    monkeypatch.setattr(seq, "get_gradients", counted)
    pns.pns_prediction(seq)
    assert calls == []


@pytest.mark.parametrize("use_block_cache", [True, False])
def test_prediction_keeps_no_blocks_and_gives_back_the_cache_setting(use_block_cache):
    seq = spin_echo_sequence()
    seq.use_block_cache = use_block_cache
    seq.block_cache.clear()
    pns.pns_prediction(seq)
    assert seq.use_block_cache is use_block_cache
    assert not seq.block_cache


def test_prediction_propagates_an_error_and_keeps_the_cache_setting(monkeypatch):
    """An error deep inside the SAFE model (the pinned fork's chunk function)
    propagates out of `pns_prediction`, and the sequence's block-cache setting and
    contents are unaffected: the block cache is only ever touched inside
    `seq_index.block_cache_off`'s own `try`/`finally`, which has already restored it
    by the time the chunk function runs (`GradientSampler` is built first)."""
    seq = spin_echo_sequence()
    seq.use_block_cache = True

    def fail(*args, **kwargs):
        raise RuntimeError("chunk failed")

    monkeypatch.setattr(pns_levels_module, "_safe_gwf_to_pns_chunk", fail)
    with pytest.raises(RuntimeError, match="chunk failed"):
        pns.pns_prediction(seq)
    assert seq.use_block_cache is True
    assert not seq.block_cache


def _three_trs(peak_tr: int) -> pp.Sequence:
    """Three 50 ms TRs on the synthetic system, each a Gy trapezoid and a delay. TR
    `peak_tr` has the fastest slew (0.1 ms rise/fall instead of 0.4 ms), so its PNS is the
    highest."""
    seq = pp.Sequence(SYSTEM)
    for i in range(3):
        g = pp.make_trapezoid(
            channel="y",
            amplitude=0.3 * SYSTEM.max_grad,
            rise_time=0.1e-3 if i == peak_tr else 0.4e-3,
            flat_time=2e-3,
            system=SYSTEM,
        )
        seq.add_block(g)
        seq.add_block(pp.make_delay(50e-3 - pp.calc_duration(g)))
    seq.set_definition("TR", 50e-3)
    return seq


@pytest.mark.parametrize("peak_tr", [0, 1, 2])
def test_peak_tr_window_finds_the_tr_with_the_peak(peak_tr):
    seq = _three_trs(peak_tr)
    p = pns.pns_prediction(seq)
    window = pns.peak_tr_window(seq, p.peak_time_s)
    lo, hi = 50e-3 * peak_tr, 50e-3 * (peak_tr + 1)
    assert window == pytest.approx((lo, hi))
    assert lo <= p.peak_time_s <= hi


def test_peak_tr_window_without_a_tr_definition_is_none():
    seq = _three_trs(1)
    del seq.definitions["TR"]
    p = pns.pns_prediction(seq)
    assert pns.peak_tr_window(seq, p.peak_time_s) is None


def test_peak_tr_window_with_one_tr_is_none():
    seq = spin_echo_sequence()  # much shorter than a TR, and no TR definition
    seq.set_definition("TR", seq.duration()[0])
    assert pns.peak_tr_window(seq, 0.0) is None


def test_peak_tr_window_without_a_peak_time_is_none():
    seq = _three_trs(1)
    assert pns.peak_tr_window(seq, None) is None


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
    """`pns_levels_for` keeps one result for each (sequence, gradient .asc file): the same
    file is cached, a different file computes once, and going back to the first file does
    not compute again (a, a, b, a gives 2 calls)."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    path_a = write_gradient_asc(name="MP_GPA_A")
    path_b = write_gradient_asc(name="MP_GPA_B")

    pns_levels_for(seq, gradient_asc=path_a)
    assert len(calls) == 1
    pns_levels_for(seq, gradient_asc=path_a)  # same sequence, same file: cached
    assert len(calls) == 1
    pns_levels_for(seq, gradient_asc=path_b)  # a different file: computes
    assert len(calls) == 2
    pns_levels_for(seq, gradient_asc=path_a)  # back to path_a: cached
    assert len(calls) == 2


def test_pns_levels_for_alternating_two_hardwares_runs_the_model_two_times(
    monkeypatch, write_gradient_asc
):
    """Two keys alternated (a, b, a, b) run the model two times, not four: the example
    hardware (key None) and a file are two hardwares of one sequence."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    path = write_gradient_asc()

    for gradient_asc in (None, path, None, path):
        pns_levels_for(seq, gradient_asc=gradient_asc)
    assert len(calls) == 2


def _assert_levels_equal(a: PnsLevels, b: PnsLevels, *, ignore: tuple[str, ...]) -> None:
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


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_pns_levels_for_hardware_from_an_asc_file_gives_the_levels_of_the_file(
    write_gradient_asc, split
):
    """`pns_levels_for` with `hardware=(asc_to_hw(read_gradient_asc(path)), label)` gives the
    levels of `gradient_asc=path`, except the hardware name (the label) and `asc_file`
    (None), for the plain layout and for the layout of a scanner file."""
    seq = spin_echo_sequence()
    path = write_gradient_asc(split=split)
    from_file = pns_levels_for(seq, gradient_asc=path)
    levels = pns_levels_for(seq, hardware=(asc_to_hw(read_gradient_asc(path)), "LABEL"))
    assert from_file.asc_file == path.name
    assert levels.hardware == "LABEL"
    assert levels.asc_file is None
    _assert_levels_equal(levels, from_file, ignore=("hardware", "asc_file"))


def test_pns_levels_for_refuses_both_gradient_asc_and_hardware(monkeypatch, write_gradient_asc):
    """`pns_levels_for` with `gradient_asc` and `hardware` together raises `ValueError`,
    and does not run the SAFE model."""
    calls = _count_pns_levels_calls(monkeypatch)
    with pytest.raises(ValueError, match="not both"):
        pns_levels_for(
            spin_echo_sequence(),
            gradient_asc=write_gradient_asc(),
            hardware=(safe_example_hw(), "LABEL"),
        )
    assert calls == []


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


def test_pns_levels_for_hardware_pair_is_not_the_example_hardware_or_a_file(
    monkeypatch, write_gradient_asc
):
    """A `hardware` pair is its own key: the example hardware (`None`), a `.asc` file and
    a pair with the values of the example hardware are three hardwares of one sequence,
    and each runs the model one time."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()
    path = write_gradient_asc()

    for _ in range(2):
        pns_levels_for(seq)
        pns_levels_for(seq, gradient_asc=path)
        pns_levels_for(seq, hardware=(safe_example_hw(), EXAMPLE_HARDWARE))
    assert len(calls) == 3


def test_pns_levels_for_keeps_one_result_for_each_tuple_of_thresholds(monkeypatch):
    """The thresholds are part of the key of a kept result: other thresholds, or the same
    ones in another order, run the model and do not give the result of the default; the
    same thresholds again give the kept result (the same object), and `(1,)` is the key of
    the default `(1.0,)`."""
    calls = _count_pns_levels_calls(monkeypatch)
    seq = spin_echo_sequence()

    default = pns_levels_for(seq)
    assert len(calls) == 1
    other = pns_levels_for(seq, thresholds=(1.0, 0.5))
    assert len(calls) == 2
    assert other is not default
    assert list(default.above) == [1.0]
    assert list(other.above) == [1.0, 0.5]
    assert pns_levels_for(seq, thresholds=(1.0, 0.5)) is other
    assert pns_levels_for(seq) is default
    assert pns_levels_for(seq, thresholds=(1,)) is default
    assert len(calls) == 2
    reordered = pns_levels_for(seq, thresholds=(0.5, 1.0))
    assert len(calls) == 3
    assert list(reordered.above) == [0.5, 1.0]


def test_pns_levels_for_shares_a_read_only_result():
    """Two callers of `pns_levels_for` get the same kept result. A change in place of its
    level by the first caller raises `ValueError`, and the second caller gets the level as
    it was."""
    seq = spin_echo_sequence()
    first = pns_levels_for(seq)
    before_min, before_max = first.level_min.copy(), first.level_max.copy()
    # Through a local name: `first.level_max *= 100` would also set the field of the frozen
    # dataclass.
    level_max = first.level_max
    with pytest.raises(ValueError):
        level_max *= 100
    with pytest.raises(ValueError):
        first.level_min[0] = 0.0
    second = pns_levels_for(seq)
    assert second is first
    np.testing.assert_array_equal(second.level_min, before_min)
    np.testing.assert_array_equal(second.level_max, before_max)
