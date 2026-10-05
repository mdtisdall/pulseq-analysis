"""The SAFE PNS prediction of a whole sequence: the summary (the peak, its time and the
peak of each axis), the intervals at or above each threshold (none by default), and the
level.

The level is the minimum and the maximum of the PNS total in fixed time bins. It is for a
caller that draws the PNS of a long sequence (pulseq-reports, for example) and cannot keep
one value for each sample.

A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of
gamma. Divide it by the magnitude of the gamma of the target, in Hz/T, to get the fraction
(1 is 100 %). The model runs on the gradient samples in Hz/m and reads no gamma
(`docs/usage.md` section 8).

`pns_levels` samples the gradients block by block (`GradientSampler.block_samples`),
runs the SAFE model of the pinned pypulseq fork over them in chunks
(`_safe_gwf_to_pns_chunk`, which carries the filter state from one chunk to the next),
and keeps only the level, the summary and the intervals. Its memory does not grow with
the duration of the sequence, except for the level (at most `MAX_BINS` bins) and the
intervals of each threshold.

The samples of each block start at the start of that block, not at a time summed over the
earlier blocks. Thus a block gives the same samples wherever it is in the sequence, and
a drawing tool that samples one block with the same rule gets the same values.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pypulseq as pp

# The chunk function of the pypulseq fork (TODO.md, "Move from the pypulseq fork to a
# pypulseq release"). The fork keeps it private, so that the proposal to upstream
# pypulseq adds no public name. This is the only module that imports it.
from pypulseq.utils.safe_pns_prediction import _safe_gwf_to_pns_chunk, safe_example_hw
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw

from ._equality import fields_equal
from .asc import EXAMPLE_HARDWARE, hardware_name, read_gradient_asc
from .extensions import refuse_rotations
from .sampling import GradientSampler, raster_block_lengths
from .seq_index import sequence_index

# The finest bin of the level (`bin_samples_for`): a plot of `EXACT_MAX_S` seconds that is
# `DISPLAY_BINS` columns wide has at least two bins in each column, so that a plot of
# that duration or longer can be drawn from the level. A shorter plot needs the samples
# themselves. The two values are those of the PNS plot of pulseq-reports (a 10 s view,
# 812 columns wide). They change only the bin size, not the summary or the intervals.
EXACT_MAX_S = 10.0
DISPLAY_BINS = 812
# The largest number of bins of the level for one file. It limits the memory of the level
# to 16 MB (two float32 arrays) for any duration: a longer file gets longer bins.
MAX_BINS = 2_000_000
# The fork's chunk size (samples): smaller chunks add time, larger ones add memory. A
# chunk of `pns_levels` is the whole number of bins nearest at or above it.
CHUNK_SAMPLES = 30_000
NO_GRADIENTS = "no gradients"
# Samples within this fraction of the peak count as the peak. Identical TRs differ only by
# rounding, so the peak time is in the first of them.
PEAK_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PnsInterval:
    """A run of consecutive samples whose total is at or above a threshold
    (`PnsLevels.above`). The time of sample `k` is `(k + 0.5) * dt`."""

    start_s: float  # the time of the first sample of the interval
    end_s: float  # the time of the last sample of the interval
    peak_hz_per_t: float  # the largest total (float64) in the interval, in Hz/T
    peak_time_s: float  # the time of the first sample of the interval with that total
    num_samples: int  # the number of samples of the interval


@dataclass(frozen=True, eq=False)
class PnsLevels:
    """The result of `pns_levels` (and of `pns.pns_levels_for`) for one sequence and one
    hardware.

    A PNS value is in Hz/T: the fraction of the stimulation limit times the magnitude of
    gamma. Divide it by the magnitude of the gamma of the target, in Hz/T, to get the
    fraction (1 is 100 %). The value of an axis is the SAFE model output of that logical
    axis. The total of a sample is `sqrt(x^2 + y^2 + z^2)` of the axis values. Sample `k` is
    at the time `(k + 0.5) * dt_s`, in seconds from the start of the sequence.

    `peak_hz_per_t`, `peak_time_s`, `axis_peaks_hz_per_t` and `above` are the summary.
    `level_min_hz_per_t` and `level_max_hz_per_t` are the level: bin `i` holds the samples
    `i * bin_samples` to `(i + 1) * bin_samples - 1` (the last bin can have fewer), and every
    total of those samples is in `[level_min_hz_per_t[i], level_max_hz_per_t[i]]`.

    Without a gradient event in the sequence, `reason` is `NO_GRADIENTS`, `num_samples` is
    0, the level has no bins, `peak_hz_per_t` and each axis peak are 0, `peak_time_s` is None
    and `above` has an empty tuple for each threshold.

    `level_min_hz_per_t` and `level_max_hz_per_t` are read-only, so that the callers of
    `pns.pns_levels_for` can share one result: convert to a new array
    (`levels.level_max_hz_per_t / abs(gamma) * 100`), not in place.
    `hw`, `axis_peaks_hz_per_t` and `above` are plain dicts, and the dataclass is frozen only
    in its fields: a caller must not change a dict (a `MappingProxyType` would stop that, but
    it cannot be pickled or copied with `copy.deepcopy`, and the dict type is the one of the
    interface).

    `==` compares the values of the fields (`_equality.values_equal`): the arrays by dtype,
    shape and values, and the dicts with their keys in order. A `PnsLevels` is not hashable.
    """

    reason: str | None  # why there is no prediction (NO_GRADIENTS), or None
    hardware: str  # the hardware name in the .asc file, asc.EXAMPLE_HARDWARE, or the label
    # of the `hardware` argument of `pns_levels`
    asc_file: str | None  # the .asc file name, or None without one (example hardware or
    # `hardware` argument)
    hw: dict[str, dict[str, float]]  # "x", "y", "z": tau1, tau2, tau3, a1, a2, a3,
    # stim_limit, g_scale, as pypulseq's hardware namespace has them
    dt_s: float  # the gradient raster
    num_samples: int  # the number of samples of the whole sequence
    bin_samples: int  # samples in each bin of the level (`bin_samples_for`)
    level_min_hz_per_t: np.ndarray  # float32, one for each bin: the minimum of the total
    level_max_hz_per_t: np.ndarray  # float32, one for each bin: the maximum of the total
    peak_hz_per_t: float  # the largest total
    peak_time_s: float | None  # the first sample time within PEAK_TOLERANCE of the peak
    axis_peaks_hz_per_t: dict[str, float]  # "x", "y", "z": the largest value of each axis
    on_raster: bool  # every block is a whole number of samples (`raster_block_lengths`)
    above: dict[float, tuple[PnsInterval, ...]]  # one key for each threshold of
    # `pns_levels`, as `float(t)` in the order of `thresholds_hz_per_t`: the intervals with
    # total >= that threshold, in time order; the tuple of a threshold is not empty if and
    # only if `peak_hz_per_t >=` that threshold, and then the largest
    # `PnsInterval.peak_hz_per_t` equals `peak_hz_per_t`

    __eq__ = fields_equal
    __hash__ = None  # type: ignore[assignment]


def bin_samples_for(num_samples: int, dt: float) -> int:
    """The number of samples in each bin of the level:
    `max(floor(EXACT_MAX_S / (2 * DISPLAY_BINS) / dt), ceil(num_samples / MAX_BINS))`, and
    at least 1. The first term is the finest bin (see `EXACT_MAX_S`), the second keeps the
    level at `MAX_BINS` bins or fewer. 615 at the 10 us raster for a file of up to
    1,230,000,000 samples (3.4 hours)."""
    finest = math.floor(EXACT_MAX_S / (2 * DISPLAY_BINS) / dt)
    coarsest_for_size = math.ceil(num_samples / MAX_BINS)
    return max(finest, coarsest_for_size, 1)


def pns_levels(
    seq: pp.Sequence,
    *,
    gradient_asc: str | Path | None = None,
    hardware: tuple[SimpleNamespace, str] | None = None,
    thresholds_hz_per_t: tuple[float, ...] = (),
) -> PnsLevels:
    """The stored level and the summary of the SAFE PNS total of `seq`, with the hardware
    of the gradient .asc file `gradient_asc`, with `hardware`, or with pypulseq's example
    hardware when both are None (`asc.read_gradient_asc`, `asc.hardware_name` and
    `asc.EXAMPLE_HARDWARE` choose the name and the file of the first and the last).

    `hardware` is a pair `(struct, label)`: `struct` is a SAFE hardware struct in the form
    of pypulseq's `asc_to_hw` (a `SimpleNamespace` with `.x`, `.y` and `.z`, each with
    `tau1` to `tau3`, `a1` to `a3`, `stim_limit`, `stim_thresh` and `g_scale`), and `label`
    is the string that `PnsLevels.hardware` gives. `PnsLevels.asc_file` is then None.
    `gradient_asc` and `hardware` together raise ValueError.

    `thresholds_hz_per_t` is a tuple of the totals, in Hz/T, whose intervals
    `PnsLevels.above` gives. For a fraction f of the stimulation limit, give
    `f * abs(gamma)` (the stimulation limit is the fraction 1, so the limit is
    `abs(gamma)`). The default is `()`: no threshold and no interval. Each is a finite
    `int` or `float` above 0 (not a `bool`), and no two are equal as floats. Else
    ValueError, before the sequence is read. The keys of `PnsLevels.above` are `float(t)`,
    in the order of `thresholds_hz_per_t`.

    The model is `calc_pns` of the pinned fork, on other samples:

    1. `dt = seq.grad_raster_time`. The samples are `GradientSampler.block_samples` of
       each axis, in Hz/m. They are not divided by a gamma. (`calc_pns` divides them by
       `seq.system.gamma`.) Thus each value is the value of `calc_pns` times the magnitude
       of `seq.system.gamma`, to the float rounding. When a block is not on the raster
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
       `bin_samples_for(num_samples, dt)` samples (the last bin can be shorter), cast
       to float32 outward: the minimum rounds down and the maximum rounds up
       (`numpy.nextafter` when the cast value is on the wrong side), so that each
       stored bin holds every total of its samples.
    5. The summary: the peak (float64), the axis peaks, and the peak time: the time
       `(k + 0.5) * dt` of the first sample whose total is at or above
       `peak * (1 - PEAK_TOLERANCE)`, as `PnsLevels.peak_time_s`. The peak is
       known only at the end, so `pns_levels` keeps the start state of each chunk
       (12 numbers) and the float64 maximum of each chunk, and runs again only the
       first chunk whose maximum reaches `peak * (1 - PEAK_TOLERANCE)`.
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

    Raises ValueError when both `gradient_asc` and `hardware` are given or
    `thresholds_hz_per_t` is refused, and NotImplementedError for a sequence with the rotation extension
    (`extensions.refuse_rotations`).
    """
    if gradient_asc is not None and hardware is not None:
        raise ValueError("give gradient_asc or hardware, not both")
    keys = _validated_thresholds(thresholds_hz_per_t)
    refuse_rotations(seq)
    dt = seq.grad_raster_time

    if hardware is not None:
        hw_ns, hardware_label = hardware
        asc_file = None
    elif gradient_asc is None:
        hw_ns, hardware_label, asc_file = safe_example_hw(), EXAMPLE_HARDWARE, None
    else:
        asc = read_gradient_asc(gradient_asc)
        hw_ns = asc_to_hw(asc)
        hardware_label, asc_file = hardware_name(asc), Path(gradient_asc).name
    hw = _hw_to_dict(hw_ns)

    index = sequence_index(seq)
    block_lengths, on_raster = raster_block_lengths(index, dt)

    if not _has_gradients(index):
        empty = np.zeros(0, dtype=np.float32)
        return _read_only(
            PnsLevels(
                reason=NO_GRADIENTS,
                hardware=hardware_label,
                asc_file=asc_file,
                hw=hw,
                dt_s=dt,
                num_samples=0,
                bin_samples=bin_samples_for(0, dt),
                level_min_hz_per_t=empty,
                level_max_hz_per_t=empty,
                peak_hz_per_t=0.0,
                peak_time_s=None,
                axis_peaks_hz_per_t=dict.fromkeys(_AXES3, 0.0),
                on_raster=on_raster,
                above={key: () for key in keys},
            )
        )

    sampler = GradientSampler(seq, index)

    # After `_has_gradients`, `num_samples >= 1`, and each chunk has one sample or more.
    if on_raster:
        cumulative = np.cumsum(block_lengths)
        num_samples = int(cumulative[-1])

        def read_range(s0: int, s1: int) -> np.ndarray:
            return _read_block_range(sampler, dt, cumulative, s0, s1)
    else:
        # The whole sequence, as the blocks give it, not `seq.get_gradients()`: that
        # builds the gradients of the whole file.
        num_samples = max(math.ceil((index.end_s - 1e-10) / dt), 0)

        def read_range(s0: int, s1: int) -> np.ndarray:
            return _read_sampled_range(sampler, dt, s0, s1)

    bin_samples = bin_samples_for(num_samples, dt)
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

    peak_time_s = None
    threshold = peak * (1 - PEAK_TOLERANCE)
    for s0, state_before, chunk_max in chunk_records:
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
            asc_file=asc_file,
            hw=hw,
            dt_s=dt,
            num_samples=num_samples,
            bin_samples=bin_samples,
            level_min_hz_per_t=level_min,
            level_max_hz_per_t=level_max,
            peak_hz_per_t=peak,
            peak_time_s=peak_time_s,
            axis_peaks_hz_per_t=dict(zip(_AXES3, axis_peak.tolist(), strict=True)),
            on_raster=on_raster,
            above={key: finder.finish() for key, finder in zip(keys, finders, strict=True)},
        )
    )


# ---- Private helpers ----

_AXES3 = ("x", "y", "z")
_GRAD_COLUMNS = ("gx", "gy", "gz")
# The 8 hardware fields of one axis that the dataclass keeps (not `stim_thresh`, which
# `_safe_gwf_to_pns_chunk` does not use).
_HW_FIELDS = ("tau1", "tau2", "tau3", "a1", "a2", "a3", "stim_limit", "g_scale")


def _read_only(levels: PnsLevels) -> PnsLevels:
    """`levels`, with `writeable` off for `level_min_hz_per_t` and `level_max_hz_per_t`."""
    for a in (levels.level_min_hz_per_t, levels.level_max_hz_per_t):
        a.flags.writeable = False
    return levels


def _validated_thresholds(thresholds_hz_per_t: object) -> tuple[float, ...]:
    """`thresholds_hz_per_t` of `pns_levels` as the tuple of `float(t)`, in the same order.
    The empty tuple is valid. Raises ValueError for a value that is not a tuple, an element
    that is a `bool` or not an `int` or a `float`, an element that is not finite or not
    above 0, and two elements that are equal as floats. `pns.pns_levels_for` uses it too."""
    if not isinstance(thresholds_hz_per_t, tuple):
        raise ValueError(  # noqa: TRY004
            f"thresholds_hz_per_t must be a tuple, not {type(thresholds_hz_per_t).__name__}"
        )
    keys = []
    for t in thresholds_hz_per_t:
        if isinstance(t, bool) or not isinstance(t, int | float):
            raise ValueError(f"each threshold must be an int or a float, not {t!r}")  # noqa: TRY004
        try:
            key = float(t)
        except OverflowError:  # an int too large for a float
            raise ValueError(f"each threshold must be finite, not {t!r}") from None
        if not math.isfinite(key) or key <= 0:
            raise ValueError(f"each threshold must be finite and above 0, not {t!r}")
        keys.append(key)
    if len(set(keys)) != len(keys):
        raise ValueError(
            f"thresholds_hz_per_t must not repeat a value, got {thresholds_hz_per_t!r}"
        )
    return tuple(keys)


def _has_gradients(index) -> bool:
    """Whether `index` (a `SequenceIndex`) has a gradient event on any axis, from its
    `gx`/`gy`/`gz` columns. Cheaper than `seq.get_gradients()`, which builds the
    gradients of the whole file."""
    return bool(index.gx.any() or index.gy.any() or index.gz.any())


def _hw_to_dict(hw_ns) -> dict[str, dict[str, float]]:
    """`hw_ns` (pypulseq's hardware `SimpleNamespace`, with `.x`, `.y`, `.z`) as a plain
    dict of the 8 fields of `_HW_FIELDS` for each axis."""
    return {
        axis: {field: float(getattr(getattr(hw_ns, axis), field)) for field in _HW_FIELDS}
        for axis in _AXES3
    }


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
        for axis in _GRAD_COLUMNS
    ]
    return np.stack(columns, axis=1)


def _read_sampled_range(sampler: GradientSampler, dt: float, s0: int, s1: int) -> np.ndarray:
    """The gwf (Hz/m, shape `(s1 - s0, 3)`) of the global sample range `[s0, s1)`, from
    `GradientSampler.sample` at the file times `(k + 0.5) * dt` (the fallback for a
    sequence with a block that is not on the raster)."""
    t = (np.arange(s0, s1, dtype=np.float64) + 0.5) * dt
    columns = [sampler.sample(axis, t) for axis in _GRAD_COLUMNS]
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
            start_s=(first + 0.5) * self._dt,
            end_s=(last + 0.5) * self._dt,
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


# The nine fields of each axis of a SAFE hardware struct, in the order of
# `safe_example_hw` and `asc_to_hw`. `pns.pns_levels_for` keys its results on them too.
SAFE_FIELDS = ("tau1", "tau2", "tau3", "a1", "a2", "a3", "stim_limit", "stim_thresh", "g_scale")
