"""Peripheral nerve stimulation (PNS) prediction for a Pulseq sequence with the SAFE model.

`pns_levels_for` gives the `PnsLevels` of a sequence (the summary: the peak, the peak time
and the axis peaks; and the level), cached one time for each (sequence object, hardware,
thresholds). It is the one place that runs the SAFE model (`pns_levels.pns_levels`, which
uses the pinned pypulseq fork's chunk function), so a caller that needs both the summary
and the level of one sequence runs the model one time.

The model needs the scanner's gradient hardware parameters, which Siemens keeps in the
gradient system's .asc file (MP_GPA_*.asc, or MP_GradSys_*.asc on newer software). The
files are confidential, so this library does not include any. Without them, the
prediction uses pypulseq's example hardware, which is not a real scanner.

A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of gamma.
Divide it by the magnitude of the gamma of the target, in Hz/T, to get the fraction (1 is
100 %). The model reads no gamma (`docs/usage.md` section 8).
"""

import weakref
from pathlib import Path
from types import SimpleNamespace

import pypulseq as pp

from ._kept import _Entry, kept_results
from .pns_levels import SAFE_FIELDS, PnsLevels, _validated_thresholds, pns_levels

# For each sequence object: the kept results (`_kept.kept_results`), which hold one
# `PnsLevels` for each pair of a hardware and the thresholds. The hardware is `None` (the
# example hardware), the resolved path of the gradient .asc file, or the tuple of
# `_hardware_key` (a tuple is never equal to a path or to `None`). The thresholds are the
# tuple of `float(t)`.
_Hardware = tuple[SimpleNamespace, str]
_HardwareKey = str | None | tuple
_LEVELS_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


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
    thresholds_hz_per_t: tuple[float, ...] = (),
) -> PnsLevels:
    """The `PnsLevels` of `seq` with the hardware of the gradient .asc file `gradient_asc`,
    with `hardware` (a pair of a SAFE hardware struct and its label), or with pypulseq's
    example hardware when both are None (`pns_levels.pns_levels`, which has the rules of
    the arguments: both together raise ValueError), and with `thresholds_hz_per_t` (in Hz/T,
    the same rules and the same default, `()`; a refused value raises ValueError before the
    sequence is read).

    The result is kept for the sequence object, the hardware and the thresholds, so that a
    caller that needs the levels of one sequence for one hardware and one tuple of
    thresholds more than once runs the SAFE model one time
    for each pair. The same thresholds in another order, or other thresholds, are another
    result (the order of the keys of `PnsLevels.above`). A relative and an
    absolute spelling of one file are one hardware, and two `hardware` pairs with the same
    label and the same field values are one hardware (`_hardware_key`). The kept results
    are built again after `add_block`, after a new read of a file into the object, and
    after a change of `seq.grad_raster_time` (the rule of `_kept`). A block replaced in
    place is not seen (`seq_index.sequence_index`). The arrays of a result are read-only,
    because all callers share them.
    """
    if gradient_asc is not None and hardware is not None:
        raise ValueError("give gradient_asc or hardware, not both")
    threshold_keys = _validated_thresholds(thresholds_hz_per_t)
    key: _HardwareKey
    if hardware is not None:
        key = _hardware_key(hardware)
    else:
        key = None if gradient_asc is None else str(Path(gradient_asc).resolve())

    by_key = kept_results(_LEVELS_CACHE, seq)
    kept_key = (key, threshold_keys)
    if kept_key not in by_key:
        by_key[kept_key] = pns_levels(
            seq,
            gradient_asc=gradient_asc,
            hardware=hardware,
            thresholds_hz_per_t=thresholds_hz_per_t,
        )
    return by_key[kept_key]
