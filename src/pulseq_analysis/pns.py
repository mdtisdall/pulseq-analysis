"""Peripheral nerve stimulation (PNS) prediction for a Pulseq sequence with the SAFE model.

`pns_prediction` gives the PNS summary (the peak, the peak time and the axis peaks) of a
sequence: the reason, hardware and asc-file fields, and the summary fields of
`pns_levels.pns_levels`, cached one time for each (sequence object, gradient .asc file) by
`pns_levels_for`. `pns_levels_for` is the one place that runs the SAFE model
(`pns_levels.pns_levels`, which uses the pinned pypulseq fork's chunk function), so a
caller that needs both the summary and the level of one sequence (a report that shows the
PNS peak and draws the PNS over time, for example) runs the model one time.

The model needs the scanner's gradient hardware parameters, which Siemens keeps in the
gradient system's .asc file (MP_GPA_*.asc, or MP_GradSys_*.asc on newer software). The
files are confidential, so this library does not include any. Without them, the
prediction uses pypulseq's example hardware, which is not a real scanner.
"""

import math
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pypulseq as pp

from .pns_levels import SAFE_FIELDS, PnsLevels, pns_levels
from .seq_index import sequence_index


@dataclass(frozen=True)
class PnsPrediction:
    """The PNS summary of one sequence (`pns_prediction`): the fields of
    `pns_levels.PnsLevels` without the level and the intervals. A caller that wants the
    samples of a short sequence can call `seq.calculate_pns` directly (the pinned fork's
    memory is near the size of its result), or use `pns_levels_for` for the level."""

    reason: str | None  # why there is no prediction, or None
    hardware: str  # the hardware name in the .asc file, or asc.EXAMPLE_HARDWARE
    asc_file: str | None  # the .asc file name, or None for the example hardware
    peak: float  # the largest total (root-sum-of-squares of the axes); 1 is the limit
    peak_time_s: float | None  # the first sample within pns_levels.PEAK_TOLERANCE of the peak
    axis_peaks: dict[str, float] = field(default_factory=dict)  # "x", "y", "z"


# For each sequence object: the number of blocks, the last block id (the rule of
# `seq_index.sequence_index`) and one `PnsLevels` for each hardware, keyed by `None` (the
# example hardware), the resolved path of the gradient .asc file, or the tuple of
# `_hardware_key` (a tuple is never equal to a path or to `None`).
_Hardware = tuple[SimpleNamespace, str]
_HardwareKey = str | None | tuple
_Kept = tuple[int, int, dict[_HardwareKey, PnsLevels]]
_LEVELS_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Kept]" = weakref.WeakKeyDictionary()


def _hardware_key(hardware: _Hardware) -> tuple:
    """The key of a `hardware` pair: its label and the 27 values of its struct as floats
    (`SAFE_FIELDS` of `x`, `y` and `z`, in this order). Two pairs with the same label and
    the same values have one key, whatever their structs are."""
    struct, label = hardware
    values = tuple(
        float(getattr(getattr(struct, axis), field)) for axis in "xyz" for field in SAFE_FIELDS
    )
    return ("hardware", label, values)


def pns_levels_for(
    seq: pp.Sequence,
    *,
    gradient_asc: str | Path | None = None,
    hardware: _Hardware | None = None,
) -> PnsLevels:
    """The `PnsLevels` of `seq` with the hardware of the gradient .asc file `gradient_asc`,
    with `hardware` (a pair of a SAFE hardware struct and its label), or with pypulseq's
    example hardware when both are None (`pns_levels.pns_levels`, which has the rules of
    the arguments: both together raise ValueError).

    The result is kept for the sequence object and the hardware, so that a caller that
    needs the levels of one sequence for one hardware more than once (`pns_prediction`,
    for example) runs the SAFE model one time for each hardware. A relative and an
    absolute spelling of one file are one hardware, and two `hardware` pairs with the same
    label and the same field values are one hardware (`_hardware_key`). The kept results
    are built again when the number of blocks or the last block id changed, for example
    after `add_block` (the rule of `seq_index.sequence_index`).
    """
    if gradient_asc is not None and hardware is not None:
        raise ValueError("give gradient_asc or hardware, not both")
    block_events = seq.block_events
    num_blocks = len(block_events)
    last_id = int(next(reversed(block_events))) if num_blocks else 0
    key: _HardwareKey
    if hardware is not None:
        key = _hardware_key(hardware)
    else:
        key = None if gradient_asc is None else str(Path(gradient_asc).resolve())

    kept = _LEVELS_CACHE.get(seq)
    if kept is None or kept[0] != num_blocks or kept[1] != last_id:
        kept = (num_blocks, last_id, {})
        _LEVELS_CACHE[seq] = kept
    by_hardware = kept[2]
    if key not in by_hardware:
        by_hardware[key] = pns_levels(seq, gradient_asc=gradient_asc, hardware=hardware)
    return by_hardware[key]


def pns_prediction(seq: pp.Sequence, *, gradient_asc: str | Path | None = None) -> PnsPrediction:
    """The SAFE PNS summary for `seq`, with the hardware in the .asc file `gradient_asc`, or
    pypulseq's example hardware when it is None. Built from `pns_levels_for`, so a caller
    that also uses `pns_levels_for` for `seq` and the same hardware does not run the SAFE
    model twice."""
    levels = pns_levels_for(seq, gradient_asc=gradient_asc)
    return PnsPrediction(
        reason=levels.reason,
        hardware=levels.hardware,
        asc_file=levels.asc_file,
        peak=levels.peak,
        peak_time_s=levels.peak_time_s,
        axis_peaks=dict(levels.axis_peaks),
    )


def peak_tr_window(seq: pp.Sequence, peak_time_s: float | None) -> tuple[float, float] | None:
    """Start and end, in seconds, of the TR that holds `peak_time_s`, counted from the
    sequence start in steps of the TR definition. None without a TR definition, or when
    the sequence is not longer than one TR.

    `peak_time_s` is in seconds, for example `PnsPrediction.peak_time_s`. A caller that
    draws the sequence can use this window to show the TR with the highest PNS."""
    tr = seq.definitions.get("TR")
    if tr is None or peak_time_s is None:
        return None
    tr = float(np.atleast_1d(tr)[0])
    duration = sequence_index(seq).end_s
    if tr <= 0 or duration <= tr * (1 + 1e-9):
        return None
    start = math.floor(peak_time_s / tr + 1e-9) * tr
    return start, min(start + tr, duration)
