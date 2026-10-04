"""Tests for `analyses.py` (task 3.3 of `docs/plans/implementation.md`).

The registry of the entry-point group `pulseq_analysis.analyses`, the specification of each
analysis of the package, `compute`, and `to_series` of `pns.safe.levels` (design section 4.4).
"""

import importlib.metadata
import inspect
import json
from types import SimpleNamespace

import numpy as np
import pytest
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from synthetic import empty_sequence, gre_sequence

from pulseq_analysis.analyses import (
    GRADIENT_BLOCKS,
    GRADIENT_LIMITS,
    GROUP,
    PNS_SAFE_LEVELS,
    SEQ_INDEX,
    AnalysisSpec,
    RegistryError,
    registry,
)
from pulseq_analysis.grad_limits import block_gradient_values, gradient_limits
from pulseq_analysis.pns import pns_levels_for
from pulseq_analysis.pns_levels import PNS_LIMIT, pns_levels
from pulseq_analysis.seq_index import sequence_index
from pulseq_analysis.seq_utils import GAMMA
from pulseq_analysis.series import Series, SeriesKind

_RASTERS = ("GradientRasterTime", "BlockDurationRaster")

# The specification of each analysis of the package: the ID, `params`, `rasters` and `cost`.
_SPECS = [
    (SEQ_INDEX, "seq.index", (), (), "fast"),
    (GRADIENT_LIMITS, "gradient.limits", ("gamma",), _RASTERS, "fast"),
    (GRADIENT_BLOCKS, "gradient.blocks", ("gamma",), _RASTERS, "fast"),
    (PNS_SAFE_LEVELS, "pns.safe.levels", ("hardware", "thresholds"), _RASTERS, "slow"),
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


def _hardware_for_peak(seq, peak):
    """Hardware with which `seq` has the peak `peak` (up to float rounding): the stimulation
    limit of the example hardware is multiplied by the peak of the example hardware divided
    by `peak`."""
    hw = safe_example_hw()
    factor = pns_levels(seq).peak / peak
    for axis in "xyz":
        getattr(hw, axis).stim_limit *= factor
    return hw, "SCALED"


def _json_round_trip(series: Series) -> Series:
    """`series` written as strict JSON text and read again."""
    return Series.from_obj(json.loads(json.dumps(series.to_obj(), allow_nan=False)))


def test_the_registry_has_the_four_analyses_of_the_package():
    """With the installed entry points, `registry()` has the four IDs, each with the object
    of this package, and each key is the `spec.id` of its analysis."""
    found = registry()

    assert sorted(found) == ["gradient.blocks", "gradient.limits", "pns.safe.levels", "seq.index"]
    for analysis, analysis_id, *_ in _SPECS:
        assert found[analysis_id] is analysis
    assert all(key == analysis.spec.id for key, analysis in found.items())


def test_two_analyses_with_one_id_raise_an_error_that_names_both_packages(monkeypatch):
    """Two entry points whose analyses have the same ID raise `RegistryError`, and the
    message has the ID and the names of the two packages."""
    _install_entry_points(
        monkeypatch,
        [
            _EntryPoint("x", _analysis("t.a"), package="pkg-one"),
            _EntryPoint("y", _analysis("t.a"), package="pkg-two"),
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
    analyses that give `()`, and text for `pns.safe.levels`."""
    spec = analysis.spec

    assert isinstance(spec, AnalysisSpec)
    assert spec.id == analysis_id
    assert spec.version == 1
    assert spec.params == params
    assert spec.rasters == rasters
    assert spec.cost == cost
    assert spec.title.strip()
    assert spec.description.strip()
    if analysis_id == "pns.safe.levels":
        assert spec.series
    else:
        assert spec.series is None


@pytest.mark.parametrize(
    ("analysis", "defaults"),
    [
        (SEQ_INDEX, {}),
        (GRADIENT_LIMITS, {"gamma": GAMMA}),
        (GRADIENT_BLOCKS, {"gamma": GAMMA}),
        (PNS_SAFE_LEVELS, {"hardware": None, "thresholds": (PNS_LIMIT,)}),
    ],
    ids=["seq.index", "gradient.limits", "gradient.blocks", "pns.safe.levels"],
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
    default arguments and with others: the same object for `seq.index` and `pns.safe.levels`
    (both keep their result for the sequence object), an equal value for the gradient
    analyses."""
    seq = gre_sequence(num_trs=4)
    hardware = _hardware_for_peak(seq, 1.5)

    assert SEQ_INDEX.compute(seq) is sequence_index(seq)
    for gamma in (GAMMA, 40e6):
        kwargs = {} if gamma == GAMMA else {"gamma": gamma}
        assert GRADIENT_LIMITS.compute(seq, **kwargs) == gradient_limits(seq, gamma=gamma)
        got = GRADIENT_BLOCKS.compute(seq, **kwargs)
        expected = block_gradient_values(seq, gamma=gamma)
        assert np.array_equal(got.block_id, expected.block_id)
        assert np.array_equal(got.start_s, expected.start_s)
        assert np.array_equal(got.vector_peak_mt_per_m, expected.vector_peak_mt_per_m)
        assert np.array_equal(got.vector_peak_time_s, expected.vector_peak_time_s)
        for name in (
            "peak_mt_per_m",
            "peak_time_s",
            "slew_t_per_m_per_s",
            "slew_time_s",
            "junction_t_per_m_per_s",
        ):
            for axis in "xyz":
                assert np.array_equal(getattr(got, name)[axis], getattr(expected, name)[axis])
    assert PNS_SAFE_LEVELS.compute(seq) is pns_levels_for(seq)
    assert PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds=(1.0, 0.5)) is (
        pns_levels_for(seq, hardware=hardware, thresholds=(1.0, 0.5))
    )
    assert PNS_SAFE_LEVELS.compute(seq, hardware=hardware) is pns_levels_for(seq, hardware=hardware)


def test_the_pns_series_equal_the_level_and_the_runs_of_the_same_call(write_gradient_asc):
    """For a sequence with runs above 1, `to_series` gives `pns_total` (an ENVELOPE of
    `level_min` and `level_max` as they are, with the times and the `meta` of design 4.4)
    and `pns_above_1` (a RUNS series of `above[1.0]`, in the array order of design 4.4)."""
    seq = gre_sequence(num_trs=20)
    levels = PNS_SAFE_LEVELS.compute(seq, hardware=_hardware_for_peak(seq, 1.5))
    assert len(levels.above[1.0]) > 1

    total, above = PNS_SAFE_LEVELS.to_series(levels)

    assert total.name == "pns_total"
    assert total.kind is SeriesKind.ENVELOPE
    assert total.unit == "1"
    assert list(total.arrays) == ["min", "max"]
    assert total.arrays["min"].dtype == np.float32
    assert total.arrays["max"].dtype == np.float32
    assert np.array_equal(total.arrays["min"], levels.level_min)
    assert np.array_equal(total.arrays["max"], levels.level_max)
    assert total.coord_unit == "s"
    assert total.coord_start == 0.0
    assert total.coord_step == levels.bin_samples * levels.dt_s
    assert total.coord_end == levels.num_samples * levels.dt_s
    assert total.meta == {
        "hardware": "SCALED",
        "asc_file": None,
        "dt_s": levels.dt_s,
        "bin_samples": levels.bin_samples,
        "num_samples": levels.num_samples,
        "peak": levels.peak,
        "peak_time_s": levels.peak_time_s,
        "axis_peaks_x": levels.axis_peaks["x"],
        "axis_peaks_y": levels.axis_peaks["y"],
        "axis_peaks_z": levels.axis_peaks["z"],
    }

    intervals = levels.above[1.0]
    assert above.name == "pns_above_1"
    assert above.kind is SeriesKind.RUNS
    assert above.unit == "1"
    assert above.coord_unit == "s"
    assert list(above.arrays) == ["start", "end", "num_samples", "peak", "peak_time_s"]
    assert above.arrays["num_samples"].dtype == np.int64
    expected = {
        "start": [i.start_s for i in intervals],
        "end": [i.end_s for i in intervals],
        "peak": [i.peak for i in intervals],
        "peak_time_s": [i.peak_time_s for i in intervals],
    }
    for name, values in expected.items():
        assert above.arrays[name].dtype == np.float64
        assert above.arrays[name].tolist() == values
    assert above.arrays["num_samples"].tolist() == [i.num_samples for i in intervals]
    assert above.meta == {"threshold": 1.0}

    path = write_gradient_asc(name="MP_GPA_SERIES")
    from_file = PNS_SAFE_LEVELS.to_series(pns_levels(seq, gradient_asc=path))[0]
    assert from_file.meta["hardware"] == "MP_GPA_SERIES"
    assert from_file.meta["asc_file"] == path.name


def test_the_pns_series_of_two_thresholds_are_in_the_order_of_the_thresholds():
    """With `thresholds=(1.0, 0.5)`, `to_series` gives `pns_total`, `pns_above_1` and
    `pns_above_0.5`, in this order, and the runs of each are `above` of its threshold (which
    are not empty and not equal). With `(0.5, 1.0)` the two RUNS series swap."""
    seq = gre_sequence(num_trs=20)
    hardware = _hardware_for_peak(seq, 1.5)

    levels = PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds=(1.0, 0.5))
    series = PNS_SAFE_LEVELS.to_series(levels)

    assert [s.name for s in series] == ["pns_total", "pns_above_1", "pns_above_0.5"]
    assert [s.kind for s in series] == [SeriesKind.ENVELOPE, SeriesKind.RUNS, SeriesKind.RUNS]
    assert levels.above[1.0] and levels.above[0.5]
    assert levels.above[1.0] != levels.above[0.5]
    for s, threshold in zip(series[1:], (1.0, 0.5), strict=True):
        assert s.meta == {"threshold": threshold}
        assert s.coord_unit == "s"
        assert s.arrays["start"].tolist() == [i.start_s for i in levels.above[threshold]]
        assert s.arrays["end"].tolist() == [i.end_s for i in levels.above[threshold]]
        assert s.arrays["peak"].tolist() == [i.peak for i in levels.above[threshold]]

    swapped = PNS_SAFE_LEVELS.compute(seq, hardware=hardware, thresholds=(0.5, 1.0))
    assert [s.name for s in PNS_SAFE_LEVELS.to_series(swapped)] == [
        "pns_total",
        "pns_above_0.5",
        "pns_above_1",
    ]


def test_to_series_refuses_two_thresholds_with_one_series_name():
    """The thresholds 1.0000001 and 1.0000002 are two keys of `above`, but both are
    "pns_above_1" with `:g`, so `to_series` raises `ValueError`."""
    levels = PNS_SAFE_LEVELS.compute(gre_sequence(num_trs=2), thresholds=(1.0000001, 1.0000002))
    assert len(levels.above) == 2

    with pytest.raises(ValueError, match="same series name"):
        PNS_SAFE_LEVELS.to_series(levels)


def test_the_pns_series_survive_the_json_round_trip():
    """Each series of `to_series` (the ENVELOPE and two RUNS series) is equal to the series
    that `Series.from_obj` reads from the strict JSON text of its `to_obj`."""
    seq = gre_sequence(num_trs=20)
    levels = PNS_SAFE_LEVELS.compute(
        seq, hardware=_hardware_for_peak(seq, 1.5), thresholds=(1.0, 0.8)
    )

    series = PNS_SAFE_LEVELS.to_series(levels)

    assert len(series) == 3
    for s in series:
        assert _json_round_trip(s) == s


def test_to_series_gives_nothing_for_a_sequence_without_gradients():
    """`pns.safe.levels` for `empty_sequence()` has `reason == NO_GRADIENTS`, and
    `to_series` gives `()` for it, also with two thresholds."""
    seq = empty_sequence()

    for thresholds in ((PNS_LIMIT,), (1.0, 0.5)):
        levels = PNS_SAFE_LEVELS.compute(seq, thresholds=thresholds)
        assert levels.reason is not None
        assert PNS_SAFE_LEVELS.to_series(levels) == ()


def test_the_other_three_analyses_give_no_series():
    """`to_series` of `seq.index`, `gradient.limits` and `gradient.blocks` gives `()`, for
    a sequence with gradients and for one without."""
    for seq in (gre_sequence(num_trs=2), empty_sequence()):
        for analysis in (SEQ_INDEX, GRADIENT_LIMITS, GRADIENT_BLOCKS):
            assert analysis.to_series(analysis.compute(seq)) == ()
