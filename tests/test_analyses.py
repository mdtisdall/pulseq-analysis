"""Tests for `analyses.py` (task 3.3 of `docs/plans/implementation.md`).

The registry of the entry-point group `pulseq_analysis.analyses`, the specification of each
analysis of the package, `compute`, and `to_series` of `pns.safe.levels` (design section 4.4).
"""

import importlib.metadata
import inspect
import json
import re
from types import SimpleNamespace

import numpy as np
import pytest
from asserts import assert_block_values_equal
from pns_hardware import hardware_for_peak
from synthetic import (
    EXAMPLE_HW,
    GAMMA_1H,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis.analyses import (
    GRADIENT_BLOCKS,
    GRADIENT_PEAKS,
    GRADIENT_SPECTRUM,
    GROUP,
    PNS_SAFE_LEVELS,
    SEQ_INDEX,
    AnalysisSpec,
    RegistryError,
    registry,
)
from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.grad_spectrum import (
    FFT_WINDOW_S,
    FREQUENCY_OVERSAMPLING,
    MAX_FREQUENCY_HZ,
    NO_GRADIENTS,
    gradient_spectrum_for,
)
from pulseq_analysis.pns import pns_levels_for
from pulseq_analysis.pns_levels import BIN_S, pns_levels
from pulseq_analysis.seq_index import sequence_index
from pulseq_analysis.series import Series, SeriesKind

_RASTERS = ("GradientRasterTime", "BlockDurationRaster")
_LIMIT = GAMMA_1H  # Hz/T: the stimulation limit for 1H, a fraction of 1 times GAMMA_1H

# The specification of each analysis of the package: the ID, `params`, `rasters` and `cost`.
_SPECS = [
    (SEQ_INDEX, "seq.index", (), (), "fast"),
    (GRADIENT_PEAKS, "gradient.peaks", (), _RASTERS, "fast"),
    (GRADIENT_BLOCKS, "gradient.blocks", (), _RASTERS, "fast"),
    (
        PNS_SAFE_LEVELS,
        "pns.safe.levels",
        ("hardware", "thresholds_hz_per_t", "bin_s"),
        _RASTERS,
        "slow",
    ),
    (GRADIENT_SPECTRUM, "gradient.spectrum", (), _RASTERS, "slow"),
]


class _EntryPoint:
    """A fake entry point: `load` gives `obj`, or raises it when it is an exception."""

    def __init__(self, name, obj, package=None):
        self.name = name
        self.obj = obj
        self.dist = None if package is None else SimpleNamespace(name=package)

    def load(self):
        if isinstance(self.obj, Exception):
            raise self.obj
        return self.obj


def _install_entry_points(monkeypatch, entry_points):
    """Make `importlib.metadata.entry_points(group=GROUP)` give `entry_points`."""
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: list(entry_points) if group == GROUP else [],
    )


def _analysis(analysis_id):
    """An object with a `spec` that has the ID `analysis_id`."""
    spec = AnalysisSpec(
        id=analysis_id, version=1, title="t", description="d", params=(), rasters=()
    )
    return SimpleNamespace(spec=spec)


def _json_round_trip(series: Series) -> Series:
    """`series` written as strict JSON text and read again."""
    return Series.from_obj(json.loads(json.dumps(series.to_obj(), allow_nan=False)))


def test_the_registry_has_the_five_analyses_of_the_package():
    """With the installed entry points, `registry()` has the five IDs, each with the object
    of this package, and each key is the `spec.id` of its analysis."""
    found = registry()

    assert sorted(found) == [
        "gradient.blocks",
        "gradient.peaks",
        "gradient.spectrum",
        "pns.safe.levels",
        "seq.index",
    ]
    for analysis, analysis_id, *_ in _SPECS:
        assert found[analysis_id] is analysis
    assert all(key == analysis.spec.id for key, analysis in found.items())


def test_two_analyses_with_one_id_raise_an_error_that_names_both_packages(monkeypatch):
    """Two entry points whose analyses have the same ID raise `RegistryError`, and the
    message has the ID and the names of the two packages."""
    _install_entry_points(
        monkeypatch,
        [
            _EntryPoint("t.a", _analysis("t.a"), package="pkg-one"),
            _EntryPoint("t.a", _analysis("t.a"), package="pkg-two"),
        ],
    )

    with pytest.raises(RegistryError) as excinfo:
        registry()

    message = str(excinfo.value)
    assert "t.a" in message
    assert "pkg-one" in message
    assert "pkg-two" in message


def test_an_entry_point_that_cannot_load_raises_an_error_that_names_it(monkeypatch):
    """An entry point whose `load` raises gives a `RegistryError` with the name of the entry
    point, the name of its package, and the type and the text of the exception."""
    _install_entry_points(
        monkeypatch,
        [_EntryPoint("broken", ImportError("no module named foo"), package="pkg-bad")],
    )

    with pytest.raises(RegistryError) as excinfo:
        registry()

    message = str(excinfo.value)
    assert "broken" in message
    assert "pkg-bad" in message
    assert "ImportError" in message
    assert "no module named foo" in message


def test_an_entry_point_without_a_spec_id_raises_an_error_that_names_it(monkeypatch):
    """An entry point whose object has no `spec`, and one whose `spec` has no `id`, give a
    `RegistryError` with the name of the entry point and the name of its package."""
    for obj in (object(), SimpleNamespace(spec=SimpleNamespace())):
        _install_entry_points(monkeypatch, [_EntryPoint("no-id", obj, package="pkg-x")])

        with pytest.raises(RegistryError) as excinfo:
            registry()

        assert "no-id" in str(excinfo.value)
        assert "pkg-x" in str(excinfo.value)


def test_an_entry_point_whose_name_is_not_the_spec_id_raises_an_error_that_names_both(
    monkeypatch,
):
    """An entry point whose name is not the `spec.id` of its object raises `RegistryError`
    with the name of the entry point, the name of its package and the `spec.id`."""
    _install_entry_points(
        monkeypatch, [_EntryPoint("other.name", _analysis("t.a"), package="pkg-x")]
    )

    with pytest.raises(RegistryError) as excinfo:
        registry()

    message = str(excinfo.value)
    assert "other.name" in message
    assert "pkg-x" in message
    assert "t.a" in message


@pytest.mark.parametrize(
    ("analysis", "analysis_id", "params", "rasters", "cost"),
    _SPECS,
    ids=[analysis_id for _, analysis_id, *_ in _SPECS],
)
def test_the_spec_of_each_analysis_has_the_documented_values(
    analysis, analysis_id, params, rasters, cost
):
    """The ID, the version 1, `params`, `rasters` and `cost` of each analysis, and a title
    and a description that are text with something in it. `series` is None for the three
    analyses that give `()`, and text for `pns.safe.levels` and `gradient.spectrum`."""
    spec = analysis.spec

    assert isinstance(spec, AnalysisSpec)
    assert spec.id == analysis_id
    assert spec.version == 1
    assert spec.params == params
    assert spec.rasters == rasters
    assert spec.cost == cost
    assert spec.title.strip()
    assert spec.description.strip()
    if analysis_id in ("pns.safe.levels", "gradient.spectrum"):
        assert spec.series
    else:
        assert spec.series is None


@pytest.mark.parametrize(
    ("analysis", "defaults"),
    [
        (SEQ_INDEX, {}),
        (GRADIENT_PEAKS, {}),
        (GRADIENT_BLOCKS, {}),
        (
            PNS_SAFE_LEVELS,
            {
                "hardware": inspect.Parameter.empty,
                "thresholds_hz_per_t": (),
                "bin_s": BIN_S,
            },
        ),
        (GRADIENT_SPECTRUM, {}),
    ],
    ids=["seq.index", "gradient.peaks", "gradient.blocks", "pns.safe.levels", "gradient.spectrum"],
)
def test_params_name_the_keyword_only_parameters_of_compute(analysis, defaults):
    """The parameters of `compute` after `seq` are all keyword-only, their names are
    `spec.params` in order, and their defaults are those of the function that `compute`
    calls. An unknown keyword is a `TypeError`."""
    parameters = list(inspect.signature(analysis.compute).parameters.values())

    assert parameters[0].name == "seq"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters[1:])
    assert tuple(p.name for p in parameters[1:]) == analysis.spec.params
    assert {p.name: p.default for p in parameters[1:]} == defaults
    with pytest.raises(TypeError):
        analysis.compute(empty_sequence(), unknown=1)


def test_compute_gives_the_value_of_its_function_with_the_same_arguments():
    """`compute` of each analysis gives the value of the function that it calls, with the
    default arguments (for `pns.safe.levels`, with `EXAMPLE_HW` as the necessary hardware)
    and with others: the same object for `seq.index`, `pns.safe.levels` and
    `gradient.spectrum` (all keep their result for the sequence object), an equal value for
    the gradient analyses (which have no other arguments)."""
    seq = gre_sequence(num_trs=4)
    hardware = hardware_for_peak(seq, 1.5)

    assert SEQ_INDEX.compute(seq) is sequence_index(seq)
    assert GRADIENT_PEAKS.compute(seq) == gradient_peaks(seq)
    got = GRADIENT_BLOCKS.compute(seq)
    expected = block_gradient_values(seq)
    assert_block_values_equal(got, expected)
    assert PNS_SAFE_LEVELS.compute(seq, hardware=EXAMPLE_HW) is pns_levels_for(
        seq, hardware=EXAMPLE_HW
    )
    thresholds = (_LIMIT, 0.5 * _LIMIT)
    assert PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds_hz_per_t=thresholds) is (
        pns_levels_for(seq, hardware=hardware, thresholds_hz_per_t=thresholds)
    )
    assert PNS_SAFE_LEVELS.compute(seq, hardware=hardware) is pns_levels_for(seq, hardware=hardware)
    assert PNS_SAFE_LEVELS.compute(seq, hardware=hardware, bin_s=1e-3) is (
        pns_levels_for(seq, hardware=hardware, bin_s=1e-3)
    )
    assert GRADIENT_SPECTRUM.compute(seq) is gradient_spectrum_for(seq)


def test_compute_of_pns_safe_levels_with_a_hardware_from_asc_gives_the_kept_result(
    write_gradient_asc,
):
    """`PNS_SAFE_LEVELS.compute(seq, hardware=hardware_from_asc(path))` is the object (`is`)
    that `pns_levels_for(seq, hardware=hardware_from_asc(path))` gives for the same file,
    with and without thresholds: two calls of `hardware_from_asc` on one file give one
    key."""
    seq = gre_sequence(num_trs=4)
    path = write_gradient_asc(name="MP_GPA_KEPT")

    levels = PNS_SAFE_LEVELS.compute(seq, hardware=hardware_from_asc(path))

    assert levels is pns_levels_for(seq, hardware=hardware_from_asc(path))
    assert levels.hardware == "MP_GPA_KEPT"
    thresholds = (_LIMIT,)
    assert PNS_SAFE_LEVELS.compute(
        seq, hardware=hardware_from_asc(path), thresholds_hz_per_t=thresholds
    ) is pns_levels_for(seq, hardware=hardware_from_asc(path), thresholds_hz_per_t=thresholds)


def test_compute_of_pns_safe_levels_without_hardware_raises_before_the_sequence_is_read():
    """`PNS_SAFE_LEVELS.compute(seq)` without `hardware` raises Python's own `TypeError`
    (a required keyword-only argument), and a `hardware` that is not a pair raises
    `TypeError` with the message that says how to make one. Both do so for an object that
    raises when the code reads any attribute of it, so the check comes before the sequence
    is read, also with thresholds."""

    class Unreadable:
        def __getattr__(self, name):
            raise AssertionError(f"the sequence was read: {name}")

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'hardware'"):
        PNS_SAFE_LEVELS.compute(Unreadable())
    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'hardware'"):
        PNS_SAFE_LEVELS.compute(Unreadable(), thresholds_hz_per_t=(_LIMIT,))
    struct = EXAMPLE_HW[0]
    for bad in (None, struct, (struct,), (struct, 3), [struct, "label"], (struct, "label", 1)):
        with pytest.raises(TypeError, match=re.escape("asc.hardware_from_asc(path)")):
            PNS_SAFE_LEVELS.compute(Unreadable(), hardware=bad)


def test_compute_of_pns_safe_levels_passes_bin_s_on():
    """`PNS_SAFE_LEVELS.compute(seq, hardware=..., bin_s=...)` is the object (`is`) that
    `pns_levels_for` gives with that `bin_s` (and not the object of the default), its
    `bin_samples` is that of the `bin_s`, and `to_series` gives `pns_total` with the
    `coord_step` of that bin. A `bin_s` that `pns_levels_for` refuses raises the same
    error before the sequence is read."""
    seq = gre_sequence(num_trs=4)

    default = PNS_SAFE_LEVELS.compute(seq, hardware=EXAMPLE_HW)
    levels = PNS_SAFE_LEVELS.compute(seq, hardware=EXAMPLE_HW, bin_s=1e-3)

    assert levels is pns_levels_for(seq, hardware=EXAMPLE_HW, bin_s=1e-3)
    assert levels is not default
    assert default.bin_samples == 500
    assert levels.bin_samples == 100
    (total,) = PNS_SAFE_LEVELS.to_series(levels)
    assert total.coord_step == levels.bin_samples * levels.dt_s

    class Unreadable:
        def __getattr__(self, name):
            raise AssertionError(f"the sequence was read: {name}")

    with pytest.raises(TypeError, match="bin_s"):
        PNS_SAFE_LEVELS.compute(Unreadable(), hardware=EXAMPLE_HW, bin_s=True)
    with pytest.raises(ValueError, match="bin_s"):
        PNS_SAFE_LEVELS.compute(Unreadable(), hardware=EXAMPLE_HW, bin_s=0)


def test_the_pns_series_equal_the_level_and_the_runs_of_the_same_call(write_gradient_asc):
    """For a sequence with runs above the limit, `to_series` gives `pns_total` (an ENVELOPE of
    `level_min_hz_per_t` and `level_max_hz_per_t` as they are, with the times and the `meta`
    of design 4.4) and `pns_above_0` (a RUNS series of `above[_LIMIT]`, in the array order of
    design 4.4), each with the unit "Hz/T"."""
    seq = gre_sequence(num_trs=20)
    levels = PNS_SAFE_LEVELS.compute(
        seq, hardware=hardware_for_peak(seq, 1.5), thresholds_hz_per_t=(_LIMIT,)
    )
    assert len(levels.above[_LIMIT]) > 1

    total, above = PNS_SAFE_LEVELS.to_series(levels)

    assert total.name == "pns_total"
    assert total.kind is SeriesKind.ENVELOPE
    assert total.unit == "Hz/T"
    assert list(total.arrays) == ["min", "max"]
    assert total.arrays["min"].dtype == np.float32
    assert total.arrays["max"].dtype == np.float32
    assert np.array_equal(total.arrays["min"], levels.level_min_hz_per_t)
    assert np.array_equal(total.arrays["max"], levels.level_max_hz_per_t)
    assert total.coord_unit == "s"
    assert total.coord_start == 0.0
    assert total.coord_step == levels.bin_samples * levels.dt_s
    assert total.coord_end == levels.num_samples * levels.dt_s
    assert total.meta == {
        "hardware": "SCALED",
        "dt_s": levels.dt_s,
        "bin_samples": levels.bin_samples,
        "num_samples": levels.num_samples,
        "peak": levels.peak_hz_per_t,
        "peak_time_s": levels.peak_time_s,
        "axis_peaks_x": levels.axis_peaks_hz_per_t["x"],
        "axis_peaks_y": levels.axis_peaks_hz_per_t["y"],
        "axis_peaks_z": levels.axis_peaks_hz_per_t["z"],
    }

    intervals = levels.above[_LIMIT]
    assert above.name == "pns_above_0"
    assert above.kind is SeriesKind.RUNS
    assert above.unit == "Hz/T"
    assert above.coord_unit == "s"
    assert list(above.arrays) == ["start", "end", "num_samples", "peak", "peak_time_s"]
    assert above.arrays["num_samples"].dtype == np.int64
    expected = {
        "start": [i.start_s for i in intervals],
        "end": [i.end_s for i in intervals],
        "peak": [i.peak_hz_per_t for i in intervals],
        "peak_time_s": [i.peak_time_s for i in intervals],
    }
    for name, values in expected.items():
        assert above.arrays[name].dtype == np.float64
        assert above.arrays[name].tolist() == values
    assert above.arrays["num_samples"].tolist() == [i.num_samples for i in intervals]
    assert above.meta == {"threshold": _LIMIT}

    path = write_gradient_asc(name="MP_GPA_SERIES")
    from_file = PNS_SAFE_LEVELS.to_series(pns_levels(seq, hardware=hardware_from_asc(path)))[0]
    assert from_file.meta["hardware"] == "MP_GPA_SERIES"


def test_the_pns_series_of_two_thresholds_are_in_the_order_of_the_thresholds():
    """With `thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`, `to_series` gives `pns_total`,
    `pns_above_0` and `pns_above_1`, in this order, and the runs of each are `above` of its
    threshold (which are not empty and not equal). With the thresholds swapped the names are
    the same: the two RUNS series swap their runs and their `meta`."""
    seq = gre_sequence(num_trs=20)
    hardware = hardware_for_peak(seq, 1.5)
    high, low = _LIMIT, 0.5 * _LIMIT

    levels = PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds_hz_per_t=(high, low))
    series = PNS_SAFE_LEVELS.to_series(levels)

    assert [s.name for s in series] == ["pns_total", "pns_above_0", "pns_above_1"]
    assert [s.kind for s in series] == [SeriesKind.ENVELOPE, SeriesKind.RUNS, SeriesKind.RUNS]
    assert levels.above[high] and levels.above[low]
    assert levels.above[high] != levels.above[low]
    for s, threshold in zip(series[1:], (high, low), strict=True):
        assert s.meta == {"threshold": threshold}
        assert s.coord_unit == "s"
        assert s.arrays["start"].tolist() == [i.start_s for i in levels.above[threshold]]
        assert s.arrays["end"].tolist() == [i.end_s for i in levels.above[threshold]]
        assert s.arrays["peak"].tolist() == [i.peak_hz_per_t for i in levels.above[threshold]]

    swapped = PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds_hz_per_t=(low, high))
    swapped_series = PNS_SAFE_LEVELS.to_series(swapped)
    assert [s.name for s in swapped_series] == ["pns_total", "pns_above_0", "pns_above_1"]
    assert [s.meta for s in swapped_series[1:]] == [{"threshold": low}, {"threshold": high}]
    assert swapped_series[1].arrays["start"].tolist() == series[2].arrays["start"].tolist()
    assert swapped_series[2].arrays["start"].tolist() == series[1].arrays["start"].tolist()


def test_the_pns_series_survive_the_json_round_trip():
    """Each series of `to_series` (the ENVELOPE and two RUNS series) is equal to the series
    that `Series.from_obj` reads from the strict JSON text of its `to_obj`."""
    seq = gre_sequence(num_trs=20)
    levels = PNS_SAFE_LEVELS.compute(
        seq, hardware=hardware_for_peak(seq, 1.5), thresholds_hz_per_t=(_LIMIT, 0.8 * _LIMIT)
    )

    series = PNS_SAFE_LEVELS.to_series(levels)

    assert len(series) == 3
    for s in series:
        assert _json_round_trip(s) == s


def test_to_series_gives_nothing_for_a_sequence_without_gradients():
    """`pns.safe.levels` for `empty_sequence()` has `reason == NO_GRADIENTS`, and
    `to_series` gives `()` for it, also with one and with two thresholds."""
    seq = empty_sequence()

    for thresholds in ((), (_LIMIT,), (_LIMIT, 0.5 * _LIMIT)):
        levels = PNS_SAFE_LEVELS.compute(seq, hardware=EXAMPLE_HW, thresholds_hz_per_t=thresholds)
        assert levels.reason is not None
        assert PNS_SAFE_LEVELS.to_series(levels) == ()


def test_the_pns_series_without_thresholds_are_the_level_only():
    """With the default thresholds (`()`), `to_series` gives one series, `pns_total`, with
    the level of the same call."""
    seq = gre_sequence(num_trs=4)
    levels = PNS_SAFE_LEVELS.compute(seq, hardware=hardware_for_peak(seq, 1.5))

    series = PNS_SAFE_LEVELS.to_series(levels)

    assert levels.above == {}
    assert [s.name for s in series] == ["pns_total"]
    assert series[0].kind is SeriesKind.ENVELOPE
    assert np.array_equal(series[0].arrays["max"], levels.level_max_hz_per_t)


def test_the_spectrum_series_equals_the_spectrum_of_the_same_call():
    """`to_series` of `gradient.spectrum` gives one SAMPLES series, `gradient_spectrum`, of
    unit "Hz/m/sqrt(Hz)" and `coord_unit` "Hz", with the arrays `value`, `x`, `y` and `z` (float64) equal to
    the RSS and the axes of the same spectrum, in this order. `coord_start` is 0 and
    `coord_start + k * coord_step` is `frequency_hz` bit for bit. The `meta` has the
    three values of the call."""
    seq = spin_echo_sequence()
    spectrum = GRADIENT_SPECTRUM.compute(seq)

    (series,) = GRADIENT_SPECTRUM.to_series(spectrum)

    assert spectrum.reason is None
    assert series.name == "gradient_spectrum"
    assert series.kind is SeriesKind.SAMPLES
    assert series.unit == "Hz/m/sqrt(Hz)"
    assert series.coord_unit == "Hz"
    assert list(series.arrays) == ["value", "x", "y", "z"]
    assert all(a.dtype == np.float64 for a in series.arrays.values())
    assert np.array_equal(series.arrays["value"], spectrum.rss)
    for axis in "xyz":
        assert np.array_equal(series.arrays[axis], spectrum.axes[axis])
    assert np.any(series.arrays["value"] > 0)
    assert series.coord_start == 0.0
    assert series.coord_step == float(spectrum.frequency_hz[1])
    n = len(spectrum.frequency_hz)
    assert np.array_equal(
        series.coord_start + np.arange(n) * series.coord_step, spectrum.frequency_hz
    )
    assert series.meta == {
        "max_frequency_hz": MAX_FREQUENCY_HZ,
        "window_s": FFT_WINDOW_S,
        "frequency_oversampling": FREQUENCY_OVERSAMPLING,
    }
    # A value of other arguments gives its own arguments, not the defaults.
    (wide,) = GRADIENT_SPECTRUM.to_series(gradient_spectrum_for(seq, window_s=0.1))
    assert wide.meta["window_s"] == 0.1


def test_the_spectrum_series_of_a_sequence_without_gradients_is_empty():
    """`gradient.spectrum` for `empty_sequence()` has `reason == NO_GRADIENTS`, and
    `to_series` gives `()` for it."""
    spectrum = GRADIENT_SPECTRUM.compute(empty_sequence())

    assert spectrum.reason == NO_GRADIENTS
    assert GRADIENT_SPECTRUM.to_series(spectrum) == ()


def test_the_other_three_analyses_give_no_series():
    """`to_series` of `seq.index`, `gradient.peaks` and `gradient.blocks` gives `()`, for
    a sequence with gradients and for one without."""
    for seq in (gre_sequence(num_trs=2), empty_sequence()):
        for analysis in (SEQ_INDEX, GRADIENT_PEAKS, GRADIENT_BLOCKS):
            assert analysis.to_series(analysis.compute(seq)) == ()
