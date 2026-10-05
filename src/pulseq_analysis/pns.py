"""Peripheral nerve stimulation (PNS) prediction for a Pulseq sequence with the SAFE model.

`pns_levels_for` gives the `PnsLevels` of a sequence (the summary: the peak, the peak time
and the axis peaks; and the level), cached one time for each (sequence object, hardware,
thresholds, bin size). It is the one place that runs the SAFE model (`pns_levels.pns_levels`, which
uses the pinned pypulseq fork's chunk function), so a caller that needs both the summary
and the level of one sequence runs the model one time.

The model needs the scanner's gradient hardware parameters, which Siemens keeps in the
gradient system's .asc file (MP_GPA_*.asc, or MP_GradSys_*.asc on newer software). The
files are confidential, so this library does not include any. The hardware is necessary,
and is the vendor-neutral pair `(struct, label)`: the package has no default. A caller makes
the pair from the .asc file with `asc.hardware_from_asc(path)`, or, for pypulseq's example
hardware (not a real scanner), gives `hardware=(safe_example_hw(), "<a label>")`.

A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of gamma.
Divide it by the magnitude of the gamma of the target, in Hz/T, to get the fraction (1 is
100 %). The model reads no gamma (`docs/usage.md` section 8).
"""

import weakref
from types import SimpleNamespace

import pypulseq as pp

from ._kept import _Entry, kept_results
from .pns_levels import (
    BIN_S,
    SAFE_FIELDS,
    PnsLevels,
    _require_hardware,
    _validated_bin_s,
    _validated_thresholds,
    pns_levels,
)

# For each sequence object: the kept results (`_kept.kept_results`), which hold one
# `PnsLevels` for each triple of a hardware, the thresholds and the bin size. The hardware
# is the tuple of `_hardware_key`. The thresholds are the tuple of `float(t)`. The bin size
# is `float(bin_s)`.
_Hardware = tuple[SimpleNamespace, str]
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
    hardware: _Hardware,
    thresholds_hz_per_t: tuple[float, ...] = (),
    bin_s: float = BIN_S,
) -> PnsLevels:
    """The `PnsLevels` of `seq` with `hardware` (a pair of a SAFE hardware struct and its
    label; `asc.hardware_from_asc` makes one from a Siemens gradient .asc file) and with
    `thresholds_hz_per_t` (in Hz/T, the same rules and the same default, `()`; a refused
    value raises ValueError before the sequence is read) and with the bin `bin_s` (in
    seconds, the same rules and the same default, `BIN_S`; a refused value raises TypeError
    or ValueError before the sequence is read). `hardware` is necessary
    (`pns_levels.pns_levels` has the rules of the arguments): a call without it, or with a
    value that is not a pair, raises TypeError, before the sequence is read and before the
    kept results are read.

    The result is kept for the sequence object, the hardware, the thresholds and the bin
    size, so that a caller that needs the levels of one sequence for one hardware, one tuple
    of thresholds and one `bin_s` more than once runs the SAFE model one time for each
    triple. A `bin_s` is the key as `float(bin_s)`: an `int` and the equal `float` are one
    key, and another `bin_s` is another result, also when it gives the same `bin_samples`.
    The same thresholds in another order, or other thresholds, are another
    result (the order of the keys of `PnsLevels.above`). Two `hardware` pairs with the same
    label and the same field values are one hardware (`_hardware_key`), so the pairs
    that `asc.hardware_from_asc` makes from one file, whatever the spelling of its path,
    give one result. The kept results
    are built again after `add_block`, after a new read of a file into the object, and
    after a change of `seq.grad_raster_time` (the rule of `_kept`). A block replaced in
    place is not seen (`seq_index.sequence_index`). The arrays of a result are read-only,
    because all callers share them.
    """
    _require_hardware(hardware)
    bin_key = _validated_bin_s(bin_s)
    threshold_keys = _validated_thresholds(thresholds_hz_per_t)
    key = _hardware_key(hardware)

    by_key = kept_results(_LEVELS_CACHE, seq)
    kept_key = (key, threshold_keys, bin_key)
    if kept_key not in by_key:
        by_key[kept_key] = pns_levels(
            seq,
            hardware=hardware,
            thresholds_hz_per_t=thresholds_hz_per_t,
            bin_s=bin_s,
        )
    return by_key[kept_key]
