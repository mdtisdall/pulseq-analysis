"""The SAFE PNS prediction of a whole sequence: the summary (the peak, its time and the
peak of each axis), the intervals at or above each threshold (none by default), and the
level.

The level is the minimum and the maximum of the PNS total in fixed time bins. It is for a
caller that draws the PNS of a long sequence (pulseq-reports, for example) and cannot keep
one value for each sample.

A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of
gamma. Divide it by the magnitude of the gamma of the target, in Hz/T, to get the fraction
(1 is 100 %). The model runs on the gradient samples in Hz/m and reads no gamma
(`docs/usage.md` section 9).

`pns_levels` is the one entry point. It keeps its result for the sequence object, for each
(hardware, thresholds, bin size), so a caller that needs both the summary and the level of
one sequence runs the model one time. On a miss it calls `_compute_levels`, which samples
the gradients block by block (`GradientSampler.block_samples`), runs the SAFE model of the
pinned pypulseq fork over them in chunks (`_safe_gwf_to_pns_chunk`, which carries the
filter state from one chunk to the next), and keeps only the level, the summary and the
intervals. Its memory does not grow with the duration of the sequence, except for the
level (at most `MAX_BINS` bins) and the intervals of each threshold.

The model needs the scanner's gradient hardware parameters, which Siemens keeps in the
gradient system's .asc file (MP_GPA_*.asc, or MP_GradSys_*.asc on newer software). The
files are confidential, so this library does not include any. The hardware is necessary,
and is the vendor-neutral pair `(struct, label)`: the package has no default. A caller makes
the pair from the .asc file with `asc.hardware_from_asc(path)`, or, for pypulseq's example
hardware (not a real scanner), gives `hardware=(safe_example_hw(), "<a label>")`.

The gradient waveform is the model of MATLAB Pulseq (`sampling`, `docs/usage.md` "The
gradient waveform"): a line across a gap of one raster time or less between two events, a
ramp to 0 and from 0 (half a raster time each) across a longer gap, and a step at a block
junction. pypulseq's `calculate_pns` draws a line across each gap (pypulseq-issues 12), so it
gives other values for a sequence with an event that starts or ends at a value that is not 0
next to a gap, or with a step at a junction.

The samples of each block start at the start of that block, not at a time summed over the
earlier blocks. Thus a block gives the same samples wherever it is in the sequence (apart
from the samples in a gap, which use the sum of the block durations before the block), and
a drawing tool that samples one block with the same rule gets the same values.
"""

import math
import weakref
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pypulseq as pp

# The chunk function of the pypulseq fork (TODO.md, "Move from the pypulseq fork to a
# pypulseq release"). The fork keeps it private, so that the proposal to upstream
# pypulseq adds no public name. This is the only module that imports it.
from pypulseq.utils.safe_pns_prediction import _safe_gwf_to_pns_chunk

from ._equality import FrozenDict, fields_equal
from ._events import event_points
from ._kept import _Entry, kept_results
from ._validate import real
from .extensions import refuse_rotations
from .sampling import (
    ON_RASTER_TOLERANCE,
    GradientSampler,
    raster_block_lengths,
    sequence_samples,
)
from .seq_index import NO_GRADIENTS, has_gradients, sequence_index
from .seq_utils import AXES, GRAD_COLUMNS

# The default bin of the level, in seconds: 5 ms (500 samples at the 10 us raster). A caller
# that needs another bin gives `bin_s`. It changes only the bin size, not the summary or the
# intervals.
BIN_S = 0.005
# The largest number of bins of the level for one file. It limits the memory of the level
# to 16 MB (two float32 arrays) for any duration and any `bin_s`: a longer file gets
# longer bins.
MAX_BINS = 2_000_000
# The fork's chunk size (samples): smaller chunks add time, larger ones add memory. A
# chunk of `pns_levels` is the whole number of bins nearest at or above it.
CHUNK_SAMPLES = 30_000
# Samples within this fraction of the peak count as the peak. Identical TRs differ only by
# rounding, so the peak time is in the first of them.
PEAK_TOLERANCE = 1e-6
# The nine fields of each axis of a SAFE hardware struct, in the order of `safe_example_hw`
# and `asc_to_hw`.
SAFE_FIELDS = ("tau1", "tau2", "tau3", "a1", "a2", "a3", "stim_limit", "stim_thresh", "g_scale")
# The 8 hardware fields of one axis that the dataclass keeps (not `stim_thresh`, which
# `_safe_gwf_to_pns_chunk` does not use). `_hardware_key` keys the kept results on them.
_HW_FIELDS = tuple(f for f in SAFE_FIELDS if f != "stim_thresh")
# The largest distance of `a1 + a2 + a3` from 1 for an axis (the rule of pypulseq's
# `safe_hw_check`).
_A_SUM_TOLERANCE = 0.001

# For each sequence object: the kept results (`_kept.kept_results`), which hold one
# `PnsLevels` for each triple of a hardware, the thresholds and the bin size. The hardware
# is the tuple of `_hardware_key`. The thresholds are the tuple of `float(t)`. The bin size
# is `float(bin_s)`.
_Hardware = tuple[SimpleNamespace, str]
_LEVELS_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class PnsInterval:
    """A run of consecutive samples whose total is at or above a threshold
    (`PnsLevels.above`). The time of sample `k` is `(k + 0.5) * dt`. `start_s` and `end_s`
    are the edges of the samples of the run: `first * dt` and `(last + 1) * dt`, so a run of
    one sample has `end_s - start_s == dt`. `peak_time_s` is the time of a sample."""

    start_s: float  # the start of the first sample of the interval, `first * dt`
    end_s: float  # the end of the last sample of the interval, `(last + 1) * dt`
    peak_hz_per_t: float  # the largest total (float64) in the interval, in Hz/T
    peak_time_s: float  # the time of the first sample of the interval with that total
    num_samples: int  # the number of samples of the interval


@dataclass(frozen=True, eq=False)
class PnsLevels:
    """The result of `pns_levels` for one sequence and one hardware.

    A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of
    gamma. Divide it by the magnitude of the gamma of the target, in Hz/T, to get the
    fraction (1 is 100 %). The value of an axis is the SAFE model output of that logical
    axis. The total of a sample is `sqrt(x^2 + y^2 + z^2)` of the axis values. Sample `k` is
    at the time `(k + 0.5) * dt_s`, in seconds from the start of the sequence.

    `peak_hz_per_t`, `peak_time_s`, `axis_peaks_hz_per_t` and `above` are the summary.
    `level_min_hz_per_t` and `level_max_hz_per_t` are the level: bin `i` holds the samples
    `i * bin_samples` to `(i + 1) * bin_samples - 1` (the last bin can have fewer), and every
    total of those samples is in `[level_min_hz_per_t[i], level_max_hz_per_t[i]]`.

    Without a gradient event in the sequence, `reason` is `NO_GRADIENTS` (the object of
    `seq_index.NO_GRADIENTS`), `num_samples` is 0, the level has no bins, `peak_hz_per_t`
    and each axis peak are 0, `peak_time_s` is None and `above` has an empty tuple for each
    threshold. When the gradients all have the amplitude 0, the peak is 0 and `peak_time_s`
    is None too, and the model does not run a second time for the peak time.

    `level_min_hz_per_t` and `level_max_hz_per_t` are read-only, so that the callers of
    `pns_levels` can share one result: convert to a new array
    (`levels.level_max_hz_per_t / abs(gamma) * 100`), not in place.
    `hw` (the outer dict and each inner dict), `axis_peaks_hz_per_t` and `above` are
    read-only `_equality.FrozenDict`s (subclasses of `dict`): a change raises `TypeError`.
    They keep `isinstance(x, dict)`, `json.dumps`, `pickle` and `copy.deepcopy`, and a
    `FrozenDict` equals a `dict` with the same items.

    `==` compares the values of the fields (`_equality.values_equal`): the arrays by dtype,
    shape and values, and the dicts with their keys in order. A `PnsLevels` is not hashable.
    """

    reason: str | None  # why there is no prediction (NO_GRADIENTS), or None
    hardware: str  # the label of the `hardware` pair
    hw: FrozenDict[str, FrozenDict[str, float]]  # "x", "y", "z": tau1, tau2, tau3, a1, a2,
    # a3, stim_limit, g_scale, as pypulseq's hardware namespace has them
    dt_s: float  # the gradient raster
    num_samples: int  # the number of samples of the whole sequence
    bin_samples: int  # samples in each bin of the level (`bin_samples_for`)
    level_min_hz_per_t: np.ndarray  # float32, one for each bin: the minimum of the total
    level_max_hz_per_t: np.ndarray  # float32, one for each bin: the maximum of the total
    peak_hz_per_t: float  # the largest total
    # The first sample time within PEAK_TOLERANCE of the peak; None when the peak is 0
    # (no gradient event, or gradients that all have the amplitude 0)
    peak_time_s: float | None
    axis_peaks_hz_per_t: FrozenDict[str, float]  # "x", "y", "z": the largest value of each axis
    on_raster: bool  # every block is a whole number of samples (`raster_block_lengths`)
    above: FrozenDict[float, tuple[PnsInterval, ...]]  # one key for each threshold of
    # `pns_levels`, as `float(t)` in the order of `thresholds_hz_per_t`: the intervals with
    # total >= that threshold, in time order; the tuple of a threshold is not empty if and
    # only if `peak_hz_per_t >=` that threshold, and then the largest
    # `PnsInterval.peak_hz_per_t` equals `peak_hz_per_t`

    __eq__ = fields_equal
    __hash__ = None  # type: ignore[assignment]


def bin_samples_for(num_samples: int, dt: float, bin_s: float = BIN_S) -> int:
    """The number of samples in each bin of the level:
    `max(wanted, ceil(num_samples / MAX_BINS), 1)`. `wanted` is the bin that the caller
    asks for (`bin_s`, in seconds): with `ratio = bin_s / dt`, it is the nearest whole
    number when `ratio` is within `ON_RASTER_TOLERANCE` of it (the division is not exact,
    so `0.01 / 1e-5` is a hair under 1000), and else `floor(ratio)`. The second term keeps
    the level at `MAX_BINS` bins or fewer, and the last is the shortest bin, one sample (a
    `bin_s` shorter than `dt` gives it). With the default `bin_s` (`BIN_S`, 5 ms): 500 at
    the 10 us raster for a file of up to 1,000,000,000 samples (2.8 hours)."""
    ratio = bin_s / dt
    nearest = round(ratio)
    wanted = nearest if abs(ratio - nearest) <= ON_RASTER_TOLERANCE else math.floor(ratio)
    coarsest_for_size = math.ceil(num_samples / MAX_BINS)
    return max(wanted, coarsest_for_size, 1)


def _check_hardware(hardware: object) -> None:
    """Raise unless `hardware` is a pair `(struct, label)` of a SAFE hardware struct and its
    `str` label. `pns_levels` calls it first, before it reads the sequence
    or the kept results, also for a sequence with no gradient event. It raises:

    - TypeError, when `hardware` is not a tuple of two items with a `str` second item;
    - ValueError, when the struct has no `x`, `y` or `z`, or an axis has no field of
      `SAFE_FIELDS` (the message names it, for example "'x.stim_thresh' missing in the
      hardware struct");
    - TypeError, when a field is not a real number, and ValueError, when it is not finite
      (`_validate.real`);
    - ValueError, when `stim_limit` is not above 0, or when `a1 + a2 + a3` of an axis is
      more than 0.001 from 1 (the rule of pypulseq's `safe_hw_check`, which the package does
      not call: it raises AttributeError for a struct with no `x`).
    """
    if not (isinstance(hardware, tuple) and len(hardware) == 2 and isinstance(hardware[1], str)):
        raise TypeError(
            "hardware must be a tuple (struct, label): a SAFE hardware struct in the form of "
            "pypulseq's asc_to_hw, and its name as a str. For a Siemens gradient .asc file, "
            "give hardware=asc.hardware_from_asc(path); for pypulseq's example hardware (not "
            'a real scanner), give hardware=(safe_example_hw(), "<a label>")'
        )
    struct = hardware[0]
    for axis in AXES:
        axis_struct = getattr(struct, axis, None)
        if axis_struct is None:
            raise ValueError(f"'{axis}' missing in the hardware struct")
        values = {}
        for field in SAFE_FIELDS:
            if not hasattr(axis_struct, field):
                raise ValueError(f"'{axis}.{field}' missing in the hardware struct")
            values[field] = real(
                f"hardware {axis}.{field}",
                getattr(axis_struct, field),
                positive=field == "stim_limit",
            )
        if abs(values["a1"] + values["a2"] + values["a3"] - 1) > _A_SUM_TOLERANCE:
            raise ValueError(
                f"hardware {axis}.a1 + {axis}.a2 + {axis}.a3 must be 1 (within "
                f"{_A_SUM_TOLERANCE}), not {values['a1'] + values['a2'] + values['a3']!r}"
            )


def pns_levels(
    seq: pp.Sequence,
    *,
    hardware: _Hardware,
    thresholds_hz_per_t: tuple[float, ...] = (),
    bin_s: float = BIN_S,
) -> PnsLevels:
    """The stored level and the summary of the SAFE PNS total of `seq`, with `hardware`. The
    result is kept for the sequence object (see "The kept result" below).

    `hardware` is necessary: the package has no default hardware. It is a pair
    `(struct, label)`: `struct` is a SAFE hardware struct in the form of pypulseq's
    `asc_to_hw` (a `SimpleNamespace` with `.x`, `.y` and `.z`, each with `tau1` to `tau3`,
    `a1` to `a3`, `stim_limit`, `stim_thresh` and `g_scale`), and `label` is the string that
    `PnsLevels.hardware` gives. `asc.hardware_from_asc(path)` makes the pair from a Siemens
    gradient .asc file. For pypulseq's example hardware, which is not a real scanner, give
    `hardware=(safe_example_hw(), "<a label>")`. `_check_hardware` checks it first, before
    the sequence is read, also for a sequence with no gradient event. Anything that is not
    a tuple of two items with a `str` second item raises TypeError; the call without
    `hardware` raises Python's own TypeError. A struct with no `x`, `y` or `z`, or an axis
    with no field of `SAFE_FIELDS` (`stim_thresh` too), raises ValueError that names it.
    Each field is a finite real number (`_validate.real`: not a real number raises
    TypeError, not finite raises ValueError); `stim_limit` is above 0; and `a1 + a2 + a3`
    of each axis is within 0.001 of 1 (the rule of pypulseq's `safe_hw_check`), or
    ValueError.

    `thresholds_hz_per_t` is a tuple of the totals, in Hz/T, whose intervals
    `PnsLevels.above` gives. For a fraction f of the stimulation limit, give
    `f * abs(gamma)` (the stimulation limit is the fraction 1, so the limit is
    `abs(gamma)`). The default is `()`: no threshold and no interval. Each is a finite
    real number above 0 (`_validate.real`: an `int`, a `float`, a `Fraction` or a NumPy real
    scalar, not a `bool`), and no two are equal as floats. A value that is not a tuple, or
    an element that is a `bool` or not a real number, raises TypeError; an element that is
    not finite, not above 0 or too large for a float, and two elements that are equal as
    floats, raise ValueError. Both are raised before the sequence is read. The keys of
    `PnsLevels.above` are `float(t)`, in the order of `thresholds_hz_per_t`.

    `bin_s` is the length of a bin of the level, in seconds. The default is `BIN_S` (5 ms:
    500 samples at the 10 us raster). `bin_samples_for` gives its whole number of samples
    (the nearest number when `bin_s / dt` is within `ON_RASTER_TOLERANCE` of it, else the
    number rounded down), at least one sample (a `bin_s` shorter than `dt` gives bins of one
    sample), and longer bins when the level would have more than `MAX_BINS` bins. It is a
    `float` or an `int` (any `numbers.Real`, not a `bool`) that is finite and above 0
    (`_validate.real`): a `bool` or a value that is not a real number raises TypeError, and
    a value that is not finite, not above 0 or too large for a float raises ValueError,
    both before the sequence is read. `bin_s` changes only the bins of
    the level: the summary and the intervals do not depend on it.

    The model is `calc_pns` of the pinned fork, on other samples:

    1. `dt = seq.grad_raster_time`. The samples are `GradientSampler.block_samples` of
       each axis, in Hz/m, the waveform of the model of MATLAB Pulseq (see the module
       docstring). They are not divided by a gamma. (`calc_pns` divides them by
       `seq.system.gamma`.) Thus each value is the value of `calc_pns` times the magnitude
       of `seq.system.gamma`, to the float rounding, for a sequence with no end that is not
       0 next to a gap of more than one raster time and no step at a block junction (there
       `calc_pns` has pypulseq's line across the gap, and a line from the earlier value
       across the first segment of the later event). When a block is not on the raster
       (`on_raster` False), the samples are `GradientSampler.sample` at the file times
       `(k + 0.5) * dt`, as `calc_pns` samples, with `k = 0 .. ceil((end - 1e-10) / dt) - 1`
       and `end` the end of the last block (`calc_pns` stops at the last gradient point
       instead; the samples after it are the decay of the filters).
    2. The samples go through `_safe_gwf_to_pns_chunk` in chunks of
       `bin_samples * ceil(CHUNK_SAMPLES / bin_samples)` samples (the whole number of
       bins nearest at or above `CHUNK_SAMPLES`), with `state=None` for the first chunk
       and the returned state after.
    3. The axis values are `0.01 *` the returned percent, and the total of a sample is
       `sqrt(x^2 + y^2 + z^2)` of them, with the numpy operations of `calc_pns`
       (`np.sqrt((comp ** 2).sum(axis=1))`).
    4. The level: the minimum and the maximum of the total in each bin of
       `bin_samples_for(num_samples, dt, bin_s)` samples (the last bin can be shorter), cast
       to float32 outward: the minimum rounds down and the maximum rounds up
       (`numpy.nextafter` when the cast value is on the wrong side), so that each
       stored bin holds every total of its samples.
    5. The summary: the peak (float64), the axis peaks, and the peak time: the time
       `(k + 0.5) * dt` of the first sample whose total is at or above
       `peak * (1 - PEAK_TOLERANCE)`, as `PnsLevels.peak_time_s`. The peak is
       known only at the end, so `pns_levels` keeps the start state of each chunk
       (12 numbers) and the float64 maximum of each chunk, and runs again only the
       first chunk whose maximum reaches `peak * (1 - PEAK_TOLERANCE)`. When the peak is 0
       (gradients that all have the amplitude 0), `peak_time_s` is None and the model does
       not run again.
    6. The intervals (`above`): for each threshold, the runs of consecutive samples whose
       float64 total is at or above it. There is one finder for each threshold, and every
       chunk goes to every finder in the same loop as the peak (no second pass; the total
       of a chunk is calculated one time). A run that reaches the end of a chunk
       continues in the next chunk when the first sample of that chunk is also at or
       above the threshold: it is one interval. An interval keeps its first and last
       sample, its largest total and the first sample with it. They use the totals of
       item 3, not the float32 bins, so the tuple of a threshold is not empty if and only
       if `peak_hz_per_t` is at or above it.

    The result does not depend on the chunk size (exact equality). A sequence without
    a gradient event gives `reason=NO_GRADIENTS`, no bins, peak 0, `peak_time_s` None
    and no interval (an empty tuple for each threshold). Memory: the chunk, the kept
    samples of the events of the blocks that lie whole in a chunk (each up to the last
    point of its event), the stored level and a few numbers for each chunk and for each
    interval; it does not grow with the length of a block. The arrays of the result are
    read-only.

    Raises TypeError when `hardware` is not a pair or has a field that is not a real number,
    `thresholds_hz_per_t` is not a tuple or has an element that is a `bool` or not a real
    number, or `bin_s` is a `bool` or not a real number; ValueError when the struct of
    `hardware` lacks an axis or a field, has a field that is not finite, a `stim_limit` not
    above 0, or an axis with `a1 + a2 + a3` not within 0.001 of 1, when a threshold or
    `bin_s` is not finite or not above 0, or when two thresholds are equal; and
    NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`).

    The kept result: `pns_levels` keeps the result for the sequence object, the hardware, the
    thresholds and the bin size, so that a caller that needs the levels of one sequence for
    one hardware, one tuple of thresholds and one `bin_s` more than once runs the SAFE model
    one time for each triple. A `bin_s` is the key as `float(bin_s)`: an `int` and the equal
    `float` are one key, and another `bin_s` is another result, also when it gives the same
    `bin_samples`. The same thresholds in another order, or other thresholds, are another
    result (the order of the keys of `PnsLevels.above`). Two `hardware` pairs with the same
    label and the same field values are one hardware (`_hardware_key`; `stim_thresh` is not
    one of the values, as the model does not use it), so the pairs that
    `asc.hardware_from_asc` makes from one file, whatever the spelling of its path, give one
    result. The kept results are built again after `add_block`, after a new read of a file
    into the object, and after a change of `seq.grad_raster_time` (the rule of `_kept`). A
    block replaced in place is not seen (`seq_index.sequence_index`). The arrays of a result
    are read-only and its dicts are `FrozenDict`s, because all callers share them.
    """
    _check_hardware(hardware)
    bin_key = real("bin_s", bin_s, positive=True)
    threshold_keys = _validated_thresholds(thresholds_hz_per_t)
    key = _hardware_key(hardware)

    by_key = kept_results(_LEVELS_CACHE, seq)
    kept_key = (key, threshold_keys, bin_key)
    if kept_key not in by_key:
        by_key[kept_key] = _compute_levels(seq, hardware, threshold_keys, bin_key)
    return by_key[kept_key]


# ---- Private helpers ----


def _hardware_key(hardware: _Hardware) -> tuple:
    """The key of a `hardware` pair: its label and the 24 values of its struct as floats
    (`_HW_FIELDS` of `x`, `y` and `z`, in this order; not `stim_thresh`, which the model
    does not use). Two pairs with the same label and the same values have one key, whatever
    their structs are. `_check_hardware` has found each field before this reads it."""
    struct, label = hardware
    values = tuple(
        float(getattr(getattr(struct, axis), field)) for axis in "xyz" for field in _HW_FIELDS
    )
    return ("hardware", label, values)


def _compute_levels(
    seq: pp.Sequence, hardware: _Hardware, keys: tuple[float, ...], bin_s: float
) -> PnsLevels:
    """The calculation of `pns_levels`, with no keep. `hardware`, `keys` (the thresholds as
    floats) and `bin_s` (a float) are the values that `pns_levels` has checked
    (`_check_hardware`, `_validated_thresholds`, `real`): this does not check them again.
    Raises NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`). The model is the one of `pns_levels`."""
    refuse_rotations(seq)
    dt = seq.grad_raster_time

    hw_ns, hardware_label = hardware
    hw = _hw_to_dict(hw_ns)

    index = sequence_index(seq)
    block_lengths, on_raster = raster_block_lengths(index, dt)

    if not has_gradients(index):
        empty = np.zeros(0, dtype=np.float32)
        return _read_only(
            PnsLevels(
                reason=NO_GRADIENTS,
                hardware=hardware_label,
                hw=hw,
                dt_s=dt,
                num_samples=0,
                bin_samples=bin_samples_for(0, dt, bin_s),
                level_min_hz_per_t=empty,
                level_max_hz_per_t=empty,
                peak_hz_per_t=0.0,
                peak_time_s=None,
                axis_peaks_hz_per_t=FrozenDict(dict.fromkeys(AXES, 0.0)),
                on_raster=on_raster,
                above=FrozenDict({key: () for key in keys}),
            )
        )

    sampler = GradientSampler(index, event_points(seq))

    # After `has_gradients`, `num_samples >= 1`, and each chunk has one sample or more.
    num_samples = sequence_samples(index, dt)
    if on_raster:
        cumulative = np.cumsum(block_lengths)

        def read_range(s0: int, s1: int) -> np.ndarray:
            return _read_block_range(sampler, dt, cumulative, s0, s1)
    else:
        # The whole sequence, as the blocks give it, not `seq.get_gradients()`: that
        # builds the gradients of the whole file.
        def read_range(s0: int, s1: int) -> np.ndarray:
            return _read_sampled_range(sampler, dt, s0, s1)

    bin_samples = bin_samples_for(num_samples, dt, bin_s)
    chunk_samples = bin_samples * math.ceil(CHUNK_SAMPLES / bin_samples)

    num_bins = math.ceil(num_samples / bin_samples)
    level_min = np.empty(num_bins, dtype=np.float32)
    level_max = np.empty(num_bins, dtype=np.float32)

    num_chunks = math.ceil(num_samples / chunk_samples)
    state = None
    peak = 0.0
    axis_peak = np.zeros(3, dtype=np.float64)
    # The start state and the float64 maximum of each chunk (item 5 of `pns_levels`):
    # enough to run again only the one chunk that holds the peak, instead of keeping every
    # sample.
    chunk_records: list[tuple[int, object, float]] = []
    finders = [_IntervalFinder(dt, key) for key in keys]

    bin_cursor = 0
    for chunk_index in range(num_chunks):
        s0 = chunk_index * chunk_samples
        s1 = min(s0 + chunk_samples, num_samples)
        gwf = read_range(s0, s1)
        state_before = state
        total, axis_frac, state = _chunk_total(gwf, dt, hw_ns, state_before)

        axis_peak = np.maximum(axis_peak, axis_frac.max(axis=0))
        chunk_max = float(total.max())
        peak = max(peak, chunk_max)
        chunk_records.append((s0, state_before, chunk_max))
        for finder in finders:
            finder.add_chunk(s0, total)

        bin_cursor = _store_bins(level_min, level_max, bin_cursor, total, bin_samples)

    # With a peak of 0 (gradients that all have the amplitude 0) there is no peak time, and
    # no second run.
    peak_time_s = None
    threshold = peak * (1 - PEAK_TOLERANCE)
    for s0, state_before, chunk_max in chunk_records if peak > 0 else ():
        if chunk_max < threshold:
            continue
        s1 = min(s0 + chunk_samples, num_samples)
        gwf = read_range(s0, s1)
        total, _, _ = _chunk_total(gwf, dt, hw_ns, state_before)
        first = int(np.flatnonzero(total >= threshold)[0])
        peak_time_s = (s0 + first + 0.5) * dt
        break

    return _read_only(
        PnsLevels(
            reason=None,
            hardware=hardware_label,
            hw=hw,
            dt_s=dt,
            num_samples=num_samples,
            bin_samples=bin_samples,
            level_min_hz_per_t=level_min,
            level_max_hz_per_t=level_max,
            peak_hz_per_t=peak,
            peak_time_s=peak_time_s,
            axis_peaks_hz_per_t=FrozenDict(zip(AXES, axis_peak.tolist(), strict=True)),
            on_raster=on_raster,
            above=FrozenDict(
                {key: finder.finish() for key, finder in zip(keys, finders, strict=True)}
            ),
        )
    )


def _read_only(levels: PnsLevels) -> PnsLevels:
    """`levels`, with `writeable` off for `level_min_hz_per_t` and `level_max_hz_per_t`."""
    for a in (levels.level_min_hz_per_t, levels.level_max_hz_per_t):
        a.flags.writeable = False
    return levels


def _validated_thresholds(thresholds_hz_per_t: object) -> tuple[float, ...]:
    """`thresholds_hz_per_t` of `pns_levels` as the tuple of `float(t)`, in the same order.
    The empty tuple is valid. Raises TypeError for a value that is not a tuple and for an
    element that is a `bool` or not a real number (`_validate.real`: an `int`, a `float`, a
    `Fraction` and the NumPy real scalars are valid), and ValueError for an element that is
    not finite, not above 0 or too large for a float, and for two elements that are equal
    as floats. `pns_levels` uses it."""
    if not isinstance(thresholds_hz_per_t, tuple):
        raise TypeError(
            f"thresholds_hz_per_t must be a tuple, not {type(thresholds_hz_per_t).__name__}"
        )
    keys = [real("each threshold", t, positive=True) for t in thresholds_hz_per_t]
    if len(set(keys)) != len(keys):
        raise ValueError(
            f"thresholds_hz_per_t must not repeat a value, got {thresholds_hz_per_t!r}"
        )
    return tuple(keys)


def _hw_to_dict(hw_ns) -> FrozenDict[str, FrozenDict[str, float]]:
    """`hw_ns` (pypulseq's hardware `SimpleNamespace`, with `.x`, `.y`, `.z`) as a
    `FrozenDict` of the 8 fields of `_HW_FIELDS` for each axis, each a `FrozenDict`."""
    return FrozenDict(
        {
            axis: FrozenDict(
                {field: float(getattr(getattr(hw_ns, axis), field)) for field in _HW_FIELDS}
            )
            for axis in AXES
        }
    )


def _read_block_range(
    sampler: GradientSampler, dt: float, cumulative: np.ndarray, s0: int, s1: int
) -> np.ndarray:
    """The gwf (Hz/m, shape `(s1 - s0, 3)`) of the global sample range `[s0, s1)`, from
    `GradientSampler.block_samples` over the block range that covers it (found in
    `cumulative`, the cumulative sample count of each block), with `skip` and `count`
    for the range. The two blocks at its ends give only their samples inside it, so
    the memory and the cost do not grow with the length of a block."""
    first_block = int(np.searchsorted(cumulative, s0, side="right"))
    stop_block = int(np.searchsorted(cumulative, s1 - 1, side="right")) + 1
    offset = int(cumulative[first_block - 1]) if first_block > 0 else 0
    columns = [
        sampler.block_samples(axis, first_block, stop_block, dt, skip=s0 - offset, count=s1 - s0)
        for axis in GRAD_COLUMNS
    ]
    return np.stack(columns, axis=1)


def _read_sampled_range(sampler: GradientSampler, dt: float, s0: int, s1: int) -> np.ndarray:
    """The gwf (Hz/m, shape `(s1 - s0, 3)`) of the global sample range `[s0, s1)`, from
    `GradientSampler.sample` at the file times `(k + 0.5) * dt` (the fallback for a
    sequence with a block that is not on the raster)."""
    t = (np.arange(s0, s1, dtype=np.float64) + 0.5) * dt
    columns = [sampler.sample(axis, t) for axis in GRAD_COLUMNS]
    return np.stack(columns, axis=1)


def _chunk_total(gwf: np.ndarray, dt: float, hw_ns, state) -> tuple[np.ndarray, np.ndarray, object]:
    """Runs `_safe_gwf_to_pns_chunk` on `gwf` (Hz/m) and returns the total (float64, in Hz/T,
    `sqrt(x^2 + y^2 + z^2)`), the axis values (in Hz/T, `0.01 *` the returned percent) and
    the state for the next chunk, as `calc_pns` computes them (but from Hz/m, not T/m)."""
    percent, new_state = _safe_gwf_to_pns_chunk(gwf, dt, hw_ns, state)
    axis_frac = 0.01 * percent
    total = np.sqrt((axis_frac**2).sum(axis=1))
    return total, axis_frac, new_state


class _IntervalFinder:
    """The intervals of consecutive samples with `total >= threshold` (item 6 of
    `pns_levels`; one finder for each threshold), from the chunks in order. A run that
    reaches the end of a chunk stays open until the next chunk shows whether it continues.
    Each open or closed interval is the global indices of its first sample, its last sample
    and the first sample of its largest total, and that total."""

    def __init__(self, dt: float, threshold: float):
        self._dt = dt
        self._threshold = threshold
        self._closed: list[PnsInterval] = []
        # The run at the end of the last chunk: (first, last, peak, peak sample), or None.
        self._open: tuple[int, int, float, int] | None = None

    def add_chunk(self, s0: int, total: np.ndarray) -> None:
        """Adds the next chunk: `total` (float64, Hz/T) starts at the global sample `s0`."""
        mask = total >= self._threshold
        if not mask.any():
            self._close_open()
            return
        # Zero-copy view as int8: a change of the mask is a nonzero step. `edges` are the
        # indices where a run starts or where the sample after a run is.
        edges = np.flatnonzero(np.diff(mask.view(np.int8))) + 1
        if mask[0]:
            starts = np.concatenate(([0], edges[1::2]))
            ends = edges[0::2]
        else:
            starts = edges[0::2]
            ends = edges[1::2]
        if mask[-1]:
            ends = np.concatenate((ends, [total.shape[0]]))
        for i, (a, b) in enumerate(zip(starts.tolist(), ends.tolist(), strict=True)):
            local = int(np.argmax(total[a:b]))  # the first sample of the largest total
            run = (s0 + a, s0 + b - 1, float(total[a + local]), s0 + a + local)
            if i == 0 and a == 0 and self._open is not None:
                first, _, peak, peak_sample = self._open
                if run[2] > peak:  # a tie keeps the earlier sample
                    peak, peak_sample = run[2], run[3]
                run = (first, run[1], peak, peak_sample)
            else:
                self._close_open()
            if b == total.shape[0]:
                self._open = run
            else:
                self._closed.append(self._interval(run))
                self._open = None

    def finish(self) -> tuple[PnsInterval, ...]:
        """The intervals in time order, after the last chunk."""
        self._close_open()
        return tuple(self._closed)

    def _close_open(self) -> None:
        if self._open is not None:
            self._closed.append(self._interval(self._open))
            self._open = None

    def _interval(self, run: tuple[int, int, float, int]) -> PnsInterval:
        first, last, peak, peak_sample = run
        return PnsInterval(
            start_s=first * self._dt,
            end_s=(last + 1) * self._dt,
            peak_hz_per_t=peak,
            peak_time_s=(peak_sample + 0.5) * self._dt,
            num_samples=last - first + 1,
        )


def _store_bins(
    level_min: np.ndarray,
    level_max: np.ndarray,
    bin_cursor: int,
    total: np.ndarray,
    bin_samples: int,
) -> int:
    """Stores the minimum and the maximum of `total` (float64, Hz/T) in consecutive bins of
    `bin_samples` samples of `level_min`/`level_max`, starting at `bin_cursor`, cast
    outward to float32 (item 4 of `pns_levels`). Only the last bin of `total` can be shorter than
    `bin_samples`: `pns_levels` builds every chunk except the last as a whole number of
    bins, so no bin crosses a chunk. Returns the new bin cursor."""
    chunk_len = total.shape[0]
    n_full = chunk_len // bin_samples
    if n_full:
        reshaped = total[: n_full * bin_samples].reshape(n_full, bin_samples)
        level_min[bin_cursor : bin_cursor + n_full] = _cast_outward(reshaped.min(axis=1), down=True)
        level_max[bin_cursor : bin_cursor + n_full] = _cast_outward(
            reshaped.max(axis=1), down=False
        )
        bin_cursor += n_full
    remainder = chunk_len - n_full * bin_samples
    if remainder:
        tail = total[n_full * bin_samples :]
        level_min[bin_cursor] = _cast_outward(np.array([tail.min()]), down=True)[0]
        level_max[bin_cursor] = _cast_outward(np.array([tail.max()]), down=False)[0]
        bin_cursor += 1
    return bin_cursor


def _cast_outward(values: np.ndarray, *, down: bool) -> np.ndarray:
    """`values` (float64) cast to float32, nudged with `numpy.nextafter` so the cast
    holds every input value: `down` moves a value that rounded the wrong way toward
    `-inf` (for a minimum), otherwise toward `+inf` (for a maximum)."""
    cast = values.astype(np.float32)
    back = cast.astype(np.float64)
    wrong_side = back > values if down else back < values
    if np.any(wrong_side):
        direction = np.float32(-np.inf) if down else np.float32(np.inf)
        cast = cast.copy()
        cast[wrong_side] = np.nextafter(cast[wrong_side], direction)
    return cast
