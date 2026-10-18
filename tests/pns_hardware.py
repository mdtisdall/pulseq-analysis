"""PNS hardware for the tests: the example hardware of pypulseq as a `SafeHardware`
(`EXAMPLE_HW`, from `safe_example_hw` of `synthetic.py`), the example hardware with a scaled
stimulation limit, so that a sequence has a chosen PNS peak, and the values of `hardware` that
are not a `SafeHardware`. It uses the package (`pns_levels`, `SafeHardware`), so it is not in
`synthetic.py`, which does not use the package. It does not import pypulseq: a test of
`test_safe.py` with the `pypulseq` marker checks the example against pypulseq's
`safe_example_hw()`."""

import pytest
from synthetic import GAMMA_1H, safe_example_hw

from pulseq_analysis.analyses.pns_levels import pns_levels
from pulseq_analysis.analyses.safe import SafeHardware
from pulseq_analysis.synth.snapshot import Snapshot

# The example SAFE hardware, the `SafeHardware` of `safe_example_hw()` with this label as its
# name. The package has no default hardware: the tests give this one.
EXAMPLE_HW = SafeHardware.from_namespace(
    safe_example_hw(), "pypulseq example hardware (not a real scanner)"
)


# Values of `hardware` that are not a `SafeHardware`: a namespace in the form of pypulseq's
# `asc_to_hw`, the pair `(struct, label)` of the earlier interface (of a namespace and of a
# `SafeHardware`), a list, a path string, and `None`.
NOT_A_SAFE_HARDWARE = [
    pytest.param(safe_example_hw(), id="namespace"),
    pytest.param((safe_example_hw(), "LABEL"), id="pair"),
    pytest.param((EXAMPLE_HW, "LABEL"), id="safe-hardware-pair"),
    pytest.param([EXAMPLE_HW], id="list"),
    pytest.param("MP_GPA_TEST.asc", id="path"),
    pytest.param(None, id="none"),
]


def _scaled_hardware(factor: float) -> SafeHardware:
    """The example hardware with the stimulation limit of each axis multiplied by `factor`
    (a smaller limit gives a larger total: the total is the percent of the limit), with the
    name "SCALED", as the `hardware` argument of `pns_levels`."""
    hw = safe_example_hw()
    for axis in "xyz":
        getattr(hw, axis).stim_limit *= factor
    return SafeHardware.from_namespace(hw, "SCALED")


def hardware_for_peak(snap: Snapshot, peak: float) -> SafeHardware:
    """Hardware with which `snap` has the peak `peak` (up to float rounding), a fraction of
    the limit: the peak of the example hardware (Hz/T) is divided by `peak` times the
    stimulation limit for 1H (Hz/T) to give the factor of the stimulation limit."""
    return _scaled_hardware(pns_levels(snap, hardware=EXAMPLE_HW).peak_hz_per_t / (peak * GAMMA_1H))
