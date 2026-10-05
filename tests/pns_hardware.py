"""PNS hardware for the tests: the example hardware of pypulseq with a scaled
stimulation limit, so that a sequence has a chosen PNS peak. It uses the package
(`pns_levels`), so it is not in `synthetic.py`, which the oracles import."""

from types import SimpleNamespace

import pypulseq as pp
from pypulseq.utils.safe_pns_prediction import safe_example_hw
from synthetic import GAMMA_1H

from pulseq_analysis.pns_levels import PNS_LIMIT, pns_levels


def _scaled_hardware(factor: float) -> tuple[SimpleNamespace, str]:
    """The example hardware with the stimulation limit of each axis multiplied by `factor`
    (a smaller limit gives a larger total: the total is the percent of the limit), as the
    `hardware` argument of `pns_levels`."""
    hw = safe_example_hw()
    for axis in "xyz":
        getattr(hw, axis).stim_limit *= factor
    return hw, "SCALED"


def hardware_for_peak(seq: pp.Sequence, peak: float) -> tuple[SimpleNamespace, str]:
    """Hardware with which `seq` has the peak `peak` (up to float rounding), a fraction of
    the limit: the peak of the example hardware (Hz/T) is divided by `peak` times the
    stimulation limit for 1H (Hz/T) to give the factor of the stimulation limit."""
    return _scaled_hardware(pns_levels(seq).peak_hz_per_t / (peak * PNS_LIMIT * GAMMA_1H))
