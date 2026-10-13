"""PNS hardware for the tests: the example hardware of pypulseq (`EXAMPLE_HARDWARE`, and
`safe_example_hw` as a new namespace), the example hardware with a scaled stimulation limit, so
that a sequence has a chosen PNS peak, the values of `hardware` that are not a pair, and the
structs that the check of the hardware refuses. It uses the package (`pns_levels`), so it is
not in `synthetic.py`, which the oracles import. It does not import pypulseq: a test of
`test_safe.py` with the `pypulseq` marker checks the example against pypulseq's
`safe_example_hw()`."""

from types import SimpleNamespace

import pytest

from pulseq_analysis.analyses.pns_levels import pns_levels
from pulseq_analysis.analyses.safe import SAFE_FIELDS, SafeAxis, SafeHardware
from pulseq_analysis.synth.snapshot import Snapshot

# The numbers of pypulseq's `safe_example_hw()` (pypulseq.utils.safe_pns_prediction), by
# axis, in the order of `SAFE_FIELDS`: tau1, tau2, tau3 (ms), a1, a2, a3, stim_limit,
# stim_thresh (T/m/s), g_scale.
EXAMPLE_NAME = "MP_GPA_EXAMPLE"
EXAMPLE_AXES = {
    "x": (0.20, 0.03, 3.00, 0.40, 0.10, 0.50, 30.0, 24.0, 0.35),
    "y": (1.50, 2.50, 0.15, 0.55, 0.15, 0.30, 15.0, 12.0, 0.31),
    "z": (2.00, 0.12, 1.00, 0.42, 0.40, 0.18, 25.0, 20.0, 0.25),
}
# The `SafeHardware` of `safe_example_hw()`.
EXAMPLE_HARDWARE = SafeHardware(
    name=EXAMPLE_NAME,
    **{
        axis: SafeAxis(**dict(zip(SAFE_FIELDS, values, strict=True)))
        for axis, values in EXAMPLE_AXES.items()
    },
)


def safe_example_hw() -> SimpleNamespace:
    """A new namespace with the attributes and values of pypulseq's `safe_example_hw()`."""
    return SimpleNamespace(
        name=EXAMPLE_NAME,
        checksum="1234567890",
        dependency="",
        **{
            axis: SimpleNamespace(**dict(zip(SAFE_FIELDS, values, strict=True)))
            for axis, values in EXAMPLE_AXES.items()
        },
    )


# Values of `hardware` that are not a pair `(struct, label)`: a struct alone (a namespace or a
# `SafeHardware`), a list, a tuple of three items, a pair whose label is not a `str`, a path
# string, and `None`.
NOT_A_PAIR = [
    pytest.param(safe_example_hw(), id="struct"),
    pytest.param(SafeHardware.from_namespace(safe_example_hw()), id="safe-hardware"),
    pytest.param([safe_example_hw(), "LABEL"], id="list"),
    pytest.param((safe_example_hw(), "LABEL", "LABEL"), id="three-items"),
    pytest.param((safe_example_hw(), 1), id="label-not-a-str"),
    pytest.param("MP_GPA_TEST.asc", id="path"),
    pytest.param(None, id="none"),
]


def struct_without(axis: str, field: str | None = None):
    """The example struct without the axis `axis`, or without its field `field`."""
    hw = safe_example_hw()
    if field is None:
        delattr(hw, axis)
    else:
        delattr(getattr(hw, axis), field)
    return hw


def struct_with(field: str, value: object):
    """The example struct with `field` of its `x` axis set to `value`."""
    hw = safe_example_hw()
    setattr(hw.x, field, value)
    return hw


# Hardware structs that `_check_hardware` refuses, each with the error and a part of its
# message.
BAD_STRUCTS = [
    pytest.param(struct_without("x"), ValueError, "'x' missing", id="no-x"),
    pytest.param(
        struct_without("x", "stim_thresh"), ValueError, "'x.stim_thresh' missing", id="no-thresh"
    ),
    pytest.param(
        struct_with("a1", 5.0), ValueError, r"x\.a1 \+ x\.a2 \+ x\.a3 must be 1", id="a-sum"
    ),
    pytest.param(
        struct_with("stim_limit", 0.0), ValueError, "x.stim_limit must be above 0", id="no-limit"
    ),
    pytest.param(struct_with("tau1", float("nan")), ValueError, "x.tau1 must be finite", id="nan"),
    pytest.param(
        struct_with("tau1", "0.2"), TypeError, "x.tau1 must be a real number", id="string"
    ),
]


def _scaled_hardware(factor: float) -> tuple[SimpleNamespace, str]:
    """The example hardware with the stimulation limit of each axis multiplied by `factor`
    (a smaller limit gives a larger total: the total is the percent of the limit), as the
    `hardware` argument of `pns_levels`."""
    hw = safe_example_hw()
    for axis in "xyz":
        getattr(hw, axis).stim_limit *= factor
    return hw, "SCALED"


def hardware_for_peak(snap: Snapshot, peak: float) -> tuple[SimpleNamespace, str]:
    """Hardware with which `snap` has the peak `peak` (up to float rounding), a fraction of
    the limit: the peak of the example hardware (Hz/T) is divided by `peak` times the
    stimulation limit for 1H (Hz/T) to give the factor of the stimulation limit."""
    from synthetic import EXAMPLE_HW, GAMMA_1H  # needs pypulseq, as `snap` does

    return _scaled_hardware(pns_levels(snap, hardware=EXAMPLE_HW).peak_hz_per_t / (peak * GAMMA_1H))
