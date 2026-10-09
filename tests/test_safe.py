"""Tests of `safe.py`: `SafeAxis`, `SafeHardware`, and the chunked SAFE filter. The tests that
compare with pypulseq's functions use `pytest.importorskip`."""

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from synthetic import (
    EXAMPLE_HW,
    arbitrary_gradient_sequence,
    border_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis import pns_levels as pns_levels_module
from pulseq_analysis.pns_levels import BIN_S, _compute_levels
from pulseq_analysis.safe import SAFE_FIELDS, SafeAxis, SafeHardware, _safe_gwf_to_pns_chunk
from pulseq_analysis.snapshot import load

# The numbers of pypulseq's `safe_example_hw()`: three axes, with the fields of `SAFE_FIELDS`.
_EXAMPLE_AXES = {
    "x": (0.20, 0.03, 3.00, 0.40, 0.10, 0.50, 30.0, 24.0, 0.35),
    "y": (1.50, 2.50, 0.15, 0.55, 0.15, 0.30, 15.0, 12.0, 0.31),
    "z": (2.00, 0.12, 1.00, 0.42, 0.40, 0.18, 25.0, 20.0, 0.25),
}
_SRC = Path(__file__).resolve().parent.parent / "src" / "pulseq_analysis"


def _namespace(name: str | None = "EXAMPLE") -> SimpleNamespace:
    """A hardware `SimpleNamespace` of the example numbers, in the form of `asc_to_hw`."""
    ns = SimpleNamespace(
        **{
            axis: SimpleNamespace(**dict(zip(SAFE_FIELDS, values, strict=True)))
            for axis, values in _EXAMPLE_AXES.items()
        }
    )
    if name is not None:
        ns.name = name
    return ns


def _namespace_with(axis: str, field: str, value: object) -> SimpleNamespace:
    ns = _namespace()
    setattr(getattr(ns, axis), field, value)
    return ns


def _namespace_without(axis: str, field: str | None = None) -> SimpleNamespace:
    ns = _namespace()
    if field is None:
        delattr(ns, axis)
    else:
        delattr(getattr(ns, axis), field)
    return ns


def _example_axis(**changes: float) -> SafeAxis:
    return SafeAxis(**{**dict(zip(SAFE_FIELDS, _EXAMPLE_AXES["x"], strict=True)), **changes})


def _example_hardware() -> SafeHardware:
    return SafeHardware.from_namespace(_namespace())


def test_a_safe_axis_keeps_its_fields_as_floats_and_is_frozen():
    axis = SafeAxis(1, 2, 3, 0.5, 0.25, 0.25, 30, 24, 1)
    for field in SAFE_FIELDS:
        assert type(getattr(axis, field)) is float
    assert axis.tau1 == 1.0
    assert axis.stim_limit == 30.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        axis.tau1 = 2.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        _example_hardware().x = axis  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "error", "match"),
    [
        ({"tau1": float("nan")}, ValueError, "SafeAxis.tau1 must be finite"),
        ({"g_scale": float("inf")}, ValueError, "SafeAxis.g_scale must be finite"),
        ({"stim_thresh": "24"}, TypeError, "SafeAxis.stim_thresh must be a real number"),
        ({"tau2": True}, TypeError, "SafeAxis.tau2 must be a real number"),
        ({"tau3": None}, TypeError, "SafeAxis.tau3 must be a real number"),
        ({"stim_limit": 0.0}, ValueError, "SafeAxis.stim_limit must be above 0"),
        ({"stim_limit": -1.0}, ValueError, "SafeAxis.stim_limit must be above 0"),
        (
            {"a1": 0.5},
            ValueError,
            r"SafeAxis\.a1 \+ SafeAxis\.a2 \+ SafeAxis\.a3 must be 1",
        ),
        (
            {"a3": 0.4},
            ValueError,
            r"SafeAxis\.a1 \+ SafeAxis\.a2 \+ SafeAxis\.a3 must be 1",
        ),
    ],
)
def test_a_safe_axis_refuses_a_bad_field(changes, error, match):
    with pytest.raises(error, match=match):
        _example_axis(**changes)


def test_a_safe_axis_takes_a_sum_of_the_a_fields_within_0_001_of_1():
    _example_axis(a1=0.4 + 0.0009)
    _example_axis(a1=0.4 - 0.0009)
    for beyond in (0.4 + 0.0011, 0.4 - 0.0011):
        with pytest.raises(ValueError, match="must be 1"):
            _example_axis(a1=beyond)


def test_a_safe_hardware_refuses_a_name_that_is_not_a_str_and_an_axis_that_is_not_a_safe_axis():
    axis = _example_axis()
    with pytest.raises(TypeError, match="SafeHardware.name must be a str"):
        SafeHardware(1, axis, axis, axis)  # type: ignore[arg-type]
    for position in range(3):
        axes = [axis, axis, axis]
        axes[position] = SimpleNamespace(**dataclasses.asdict(axis))
        with pytest.raises(TypeError, match=rf"SafeHardware.{'xyz'[position]} must be a SafeAxis"):
            SafeHardware("NAME", *axes)


def test_safe_hardware_values_compare_and_hash_by_their_fields():
    first, second = _example_hardware(), _example_hardware()
    assert first == second
    assert hash(first) == hash(second)
    changed = dataclasses.replace(first, z=_example_axis(g_scale=0.5))
    assert changed != first
    assert changed.x == first.x


def test_from_namespace_reads_the_fields_of_each_axis():
    """The fields of the namespace of `asc_to_hw` and `safe_example_hw()` are the fields of
    the result, with the name of the namespace; an extra field is ignored."""
    ns = _namespace("MP_GPA_EXAMPLE")
    ns.checksum = "1234567890"
    ns.y.extra = 5.0
    hardware = SafeHardware.from_namespace(ns)
    assert hardware.name == "MP_GPA_EXAMPLE"
    for axis, values in _EXAMPLE_AXES.items():
        assert dataclasses.astuple(getattr(hardware, axis)) == values


def test_from_namespace_takes_the_name_from_the_argument_then_the_namespace_then_unknown():
    assert SafeHardware.from_namespace(_namespace("OWN")).name == "OWN"
    assert SafeHardware.from_namespace(_namespace("OWN"), "GIVEN").name == "GIVEN"
    assert SafeHardware.from_namespace(_namespace(None)).name == "unknown"
    assert SafeHardware.from_namespace(_namespace(None), "GIVEN").name == "GIVEN"
    with pytest.raises(TypeError, match="SafeHardware.name must be a str"):
        SafeHardware.from_namespace(_namespace(None), 3)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("ns", "error", "match"),
    [
        (_namespace_without("x"), ValueError, "'x' missing in the hardware struct"),
        (_namespace_without("z"), ValueError, "'z' missing in the hardware struct"),
        (
            _namespace_without("x", "stim_thresh"),
            ValueError,
            "'x.stim_thresh' missing in the hardware struct",
        ),
        (
            _namespace_without("y", "g_scale"),
            ValueError,
            "'y.g_scale' missing in the hardware struct",
        ),
        (
            _namespace_with("x", "a1", 5.0),
            ValueError,
            r"hardware x\.a1 \+ x\.a2 \+ x\.a3 must be 1 \(within 0\.001\), not 5\.6",
        ),
        (
            _namespace_with("z", "a1", 0.9),
            ValueError,
            r"hardware z\.a1 \+ z\.a2 \+ z\.a3 must be 1",
        ),
        (
            _namespace_with("x", "stim_limit", 0.0),
            ValueError,
            "hardware x.stim_limit must be above",
        ),
        (_namespace_with("x", "tau1", float("nan")), ValueError, "hardware x.tau1 must be finite"),
        (
            _namespace_with("y", "tau1", "0.2"),
            TypeError,
            "hardware y.tau1 must be a real number",
        ),
    ],
)
def test_from_namespace_refuses_a_bad_struct_and_names_the_field(ns, error, match):
    with pytest.raises(error, match=match):
        SafeHardware.from_namespace(ns)


def test_the_chunk_function_gives_the_values_of_the_formula_for_two_samples():
    """The percent of one axis for the waveform `[g, g]` from the zero state, from the
    formula of the SAFE model (low-pass `y[i] = alpha * x[i] + (1 - alpha) * y[i - 1]` of
    the slew with `tau1` and `tau3`, and of its absolute value with `tau2`, `alpha = dt_ms /
    (tau + dt_ms)`), written out here: the first sample is the difference from 0, the second
    has a slew of 0 and the filters decay."""
    hardware = _example_hardware()
    dt, g = 1e-5, 2.0
    gwf = np.zeros((2, 3))
    gwf[:, 1] = g  # the y axis
    pns, state = _safe_gwf_to_pns_chunk(gwf, dt, hardware, None)

    axis = hardware.y
    dt_ms = dt * 1000
    alpha = [dt_ms / (tau + dt_ms) for tau in (axis.tau1, axis.tau2, axis.tau3)]
    slew = g / dt
    first_filters = [a * slew for a in alpha]
    second_filters = [(1 - a) * f for a, f in zip(alpha, first_filters, strict=True)]
    expected = []
    for l1, l2, l3 in (first_filters, second_filters):
        stim = axis.a1 * abs(l1) + axis.a2 * l2 + axis.a3 * abs(l3)
        expected.append(stim / axis.stim_limit * axis.g_scale * 100)
    np.testing.assert_allclose(pns[:, 1], expected, rtol=1e-12)
    assert np.all(pns[:, 0] == 0)
    assert np.all(pns[:, 2] == 0)
    np.testing.assert_array_equal(state.g_last, [0.0, g, 0.0])
    assert state.zi.shape == (3, 3)


def test_the_chunks_of_a_waveform_give_the_rows_of_the_waveform_in_one_chunk():
    """The chunks in order, with the state of each passed to the next, concatenate to the
    result of one chunk (exact equality), and the first row of a chunk is the difference from
    the last sample of the chunk before."""
    rng = np.random.default_rng(0)
    gwf = np.cumsum(rng.normal(size=(1000, 3)), axis=0) * 1e3
    hardware = _example_hardware()
    whole, whole_state = _safe_gwf_to_pns_chunk(gwf, 1e-5, hardware, None)

    rows, state = [], None
    for start, stop in ((0, 1), (1, 8), (8, 300), (300, 1000)):
        pns, state = _safe_gwf_to_pns_chunk(gwf[start:stop], 1e-5, hardware, state)
        rows.append(pns)
    np.testing.assert_array_equal(np.concatenate(rows), whole)
    np.testing.assert_array_equal(state.g_last, whole_state.g_last)
    np.testing.assert_array_equal(state.zi, whole_state.zi)


def test_the_chunk_function_gives_the_same_values_with_a_namespace_as_with_a_safe_hardware():
    gwf = np.cumsum(np.random.default_rng(1).normal(size=(50, 3)), axis=0)
    from_hardware, _ = _safe_gwf_to_pns_chunk(gwf, 1e-5, _example_hardware(), None)
    from_namespace, _ = _safe_gwf_to_pns_chunk(gwf, 1e-5, _namespace(), None)
    np.testing.assert_array_equal(from_hardware, from_namespace)


def _scaled_namespace() -> SimpleNamespace:
    """The example namespace with other numbers in every field (the three filters differ,
    the sum of the a fields is 1)."""
    ns = _namespace()
    for i, axis in enumerate("xyz"):
        axis_ns = getattr(ns, axis)
        axis_ns.tau1 *= 1.7 + i
        axis_ns.tau2 *= 0.6 + 0.3 * i
        axis_ns.tau3 *= 2.1 - 0.4 * i
        axis_ns.a1, axis_ns.a2, axis_ns.a3 = 0.2 + 0.1 * i, 0.5 - 0.1 * i, 0.3
        axis_ns.stim_limit *= 1.3 + i
        axis_ns.g_scale *= 0.9 + 0.2 * i
    return ns


def test_the_example_numbers_of_these_tests_are_those_of_pypulseqs_example_hardware():
    module = pytest.importorskip("pypulseq.utils.safe_pns_prediction")
    hardware = module.safe_example_hw()
    for axis, values in _EXAMPLE_AXES.items():
        assert tuple(getattr(getattr(hardware, axis), f) for f in SAFE_FIELDS) == values


@pytest.mark.parametrize("dt", [1e-5, 2.5e-6], ids=["10us", "2.5us"])
@pytest.mark.parametrize("scaled", [False, True], ids=["example", "other-numbers"])
def test_the_chunk_function_equals_pypulseqs_for_every_chunk_and_state(scaled, dt):
    """The `pns` array and the state of each chunk equal the pinned fork's
    `_safe_gwf_to_pns_chunk` exactly (`array_equal`), over the same chunks and with each
    function given the state that it returned."""
    module = pytest.importorskip("pypulseq.utils.safe_pns_prediction")
    ns = _scaled_namespace() if scaled else _namespace()
    hardware = SafeHardware.from_namespace(ns)
    rng = np.random.default_rng(2)
    gwf = np.cumsum(rng.normal(size=(2000, 3)), axis=0) * 1e3

    own_state = other_state = None
    for start, stop in ((0, 1), (1, 2), (2, 700), (700, 701), (701, 2000)):
        own, own_state = _safe_gwf_to_pns_chunk(gwf[start:stop], dt, hardware, own_state)
        other, other_state = module._safe_gwf_to_pns_chunk(gwf[start:stop], dt, ns, other_state)
        np.testing.assert_array_equal(own, other)
        np.testing.assert_array_equal(own_state.g_last, other_state.g_last)
        np.testing.assert_array_equal(own_state.zi, other_state.zi)


@pytest.mark.parametrize(
    "ns",
    [
        _namespace_with("x", "a1", 0.4 + 0.0009),
        _namespace_with("y", "a1", 0.55 - 0.0009),
        _namespace_with("x", "a1", 0.4 + 0.0011),
        _namespace_with("z", "a1", 0.42 - 0.0011),
        _namespace_with("x", "a1", 5.0),
        _namespace_without("x"),
        _namespace_without("y", "stim_thresh"),
        _namespace_without("z", "g_scale"),
    ],
    ids=[
        "x-just-within",
        "y-just-within",
        "x-just-beyond",
        "z-just-below",
        "a-sum",
        "no-x",
        "no-thresh",
        "no-g-scale",
    ],
)
def test_the_hardware_check_accepts_and_refuses_what_pypulseqs_safe_hw_check_does(ns):
    """A namespace is valid for `SafeHardware.from_namespace` if and only if pypulseq's
    `safe_hw_check` accepts it (it raises `ValueError`; for a struct with no `x` it raises
    `AttributeError` instead, which the package does not copy)."""
    module = pytest.importorskip("pypulseq.utils.safe_pns_prediction")
    try:
        module.safe_hw_check(ns)
    except (ValueError, AttributeError):
        pypulseq_accepts = False
    else:
        pypulseq_accepts = True
    try:
        SafeHardware.from_namespace(ns)
    except ValueError:
        own_accepts = False
    else:
        own_accepts = True
    assert own_accepts is pypulseq_accepts


_SEQUENCES = {
    "spin_echo": spin_echo_sequence,
    "gre": gre_sequence,
    "arbitrary_gradient": arbitrary_gradient_sequence,
    "border": border_sequence,
}


@pytest.mark.parametrize("build", _SEQUENCES.values(), ids=_SEQUENCES.keys())
@pytest.mark.parametrize("bin_s", [BIN_S, 1e-5], ids=["default-bin", "one-sample-bins"])
def test_pns_levels_equals_the_levels_with_pypulseqs_chunk_function_exactly(
    monkeypatch, build, bin_s
):
    """`_compute_levels` with the package's SAFE filter gives the same `PnsLevels` (`==`: every
    field, the arrays by dtype, shape and values) as with the pinned fork's
    `_safe_gwf_to_pns_chunk` in its place, for the example hardware, with thresholds (so
    that the intervals are compared) and a chunk size of 1000 samples (so that the state
    passes from chunk to chunk)."""
    module = pytest.importorskip("pypulseq.utils.safe_pns_prediction")
    snap = load(build())
    thresholds = (1e5, 1e6)
    monkeypatch.setattr(pns_levels_module, "_CHUNK_SAMPLES", 1000)
    own = _compute_levels(snap, EXAMPLE_HW, thresholds, bin_s)
    monkeypatch.setattr(pns_levels_module, "_safe_gwf_to_pns_chunk", module._safe_gwf_to_pns_chunk)
    other = _compute_levels(snap, EXAMPLE_HW, thresholds, bin_s)
    assert own.peak_hz_per_t > 0
    assert any(own.above.values())
    assert own == other


def test_safe_and_asc_import_neither_pypulseq_nor_matplotlib():
    """Importing `pulseq_analysis.safe` and `pulseq_analysis.asc` in a new interpreter does
    not import pypulseq or matplotlib."""
    code = (
        "import sys, pulseq_analysis.safe, pulseq_analysis.asc; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('pypulseq', 'matplotlib')]; "
        "assert not bad, bad"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_only_snapshot_extensions_and_seq_index_import_pypulseq():
    """Of the modules of `src/pulseq_analysis`, only `snapshot`, `extensions` and `seq_index`
    have an `import` of pypulseq (found in the syntax tree of each file)."""
    importing = set()
    for path in sorted(_SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == "pypulseq" for name in names):
                importing.add(path.stem)
    assert importing == {"snapshot", "extensions", "seq_index"}
