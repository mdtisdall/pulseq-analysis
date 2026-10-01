# Using pulseq-analysis

This document is the reference for a user of `pulseq-analysis`: the modules
that measure a Pulseq sequence. pulseq-checks uses them for its checks, and
pulseq-reports uses them for its plots. The names in this document are the
interface of these modules. A name that this document does not give, or that
starts with `_`, can change in any release.

Contents:

1. [`seq_index`: the block table](#1-seq_index-the-block-table)
2. [`grad_limits`: gradient amplitude and slew](#2-grad_limits-gradient-amplitude-and-slew)
3. [`pns` and `pns_levels`: SAFE PNS](#3-pns-and-pns_levels-safe-pns)
4. [The other modules](#4-the-other-modules)

| Module | What it gives |
|---|---|
| `pulseq_analysis.seq_index` | The block table of a sequence, and the unique events. |
| `pulseq_analysis.grad_limits` | The peak amplitude, peak slew and RMS of the gradients, for the whole file and for each block. |
| `pulseq_analysis.pns` and `pulseq_analysis.pns_levels` | The SAFE PNS prediction. |
| `pulseq_analysis.sampling` | The gradient waveform of one axis at given times. |
| `pulseq_analysis.seq_utils` | The points of one gradient event, the samples of one RF event, and the constants. |
| `pulseq_analysis.asc` | The read of a Siemens gradient `.asc` file. |
| `pulseq_analysis.extensions` | The refusal of the Pulseq extensions that the measurements do not support. |

These rules apply to all the modules:

- **Logical axes.** The gradient and PNS values are of the logical axes of
  the file (x, y, z), not of the physical axes of a scanner. On an oblique
  slice, one physical axis can get the magnitude of the three-axis vector.
- **Rotation extension.** `gradient_limits`, `block_gradient_values` and
  `pns_levels` raise `NotImplementedError` for a file with the Pulseq
  rotation extension (`extensions.refuse_rotations`), because the gradients
  of the file are not the gradients on the scanner.
- **Block ID and play index.** The *block ID* is the ID of pypulseq (a key of
  `seq.block_events`). The *play index* is the
  position of a block in play order, from 0. The arrays of `SequenceIndex` and
  of `BlockGradientValues` have one entry for each play index. Use
  `block_id[i]` to get the block ID of play index `i`: the IDs do not have to
  be 1, 2, 3 and so on.
- **Times.** A time is in seconds from the start of the sequence. The start of
  a block is the sum of the durations of the blocks before it, added in play
  order.
- **Rasters.** The gradient and PNS measurements use the `GradientRasterTime`
  and the `BlockDurationRaster` of the sequence.
- **Units.** Gradient amplitudes are in mT/m and slew rates in T/m/s. The
  conversion from the Hz/m of pypulseq uses the `gamma` argument (Hz/T). A
  PNS value is a fraction of the stimulation limit: 1 is 100 %.
- **Kept results.** `sequence_index` and `pns.pns_levels_for` keep their
  result for the sequence object. They build it again when the number of
  blocks or the ID of the last block changed, for example after `add_block`.
  A change that keeps both (a block replaced in place) is not seen: make a new
  sequence object for it. The other functions keep nothing.

## 1. `seq_index`: the block table

`sequence_index(seq) -> SequenceIndex` reads `seq.block_events` and
`seq.block_durations`, with no `get_block`. It numbers the unique events of
each kind from 1, in the order of their first use: block by block in play
order, and in one block in the order gx, gy, gz. The three gradient axes share
one number space, so one event that plays on x and on y has one number.

`SequenceIndex` is a frozen dataclass. N is the number of blocks, and K the
number of unique events of one kind.

| Field | Meaning |
|---|---|
| `num_blocks` | N. |
| `block_id` | uint32, N: the block ID of each play index. |
| `start_s` | float64, N: the start of each block. |
| `duration_s` | float64, N: the duration of each block. |
| `end_s` | The end of the last block. 0.0 without blocks. |
| `rf`, `adc` | N: the number of the RF (ADC) event of each block, 0 for no event. |
| `gx`, `gy`, `gz` | N: the number of the gradient event of each block on that axis, 0 for no event. |
| `rf_first`, `adc_first` | int64, K: the play index of the first block of event `k + 1`. |
| `grad_first` | int64, K: the same for gradient event `k + 1`. |
| `grad_first_axis` | uint8, K: 0, 1 or 2 for gx, gy or gz in that first block. |

The event columns use the smallest of uint8, uint16 and uint32 that holds K.
Convert a value with `int(x)` when you need a Python `int`.

`rf_events(seq, index)`, `grad_events(seq, index)` and `adc_events(seq, index)`
give `(number, event)` for each unique event, in the order of the numbers.
The event is the pypulseq event of the first block that uses it. They read
one block with `get_block` for each event, not for each block, with
pypulseq's block cache off. `block_cache_off(seq)` is the context manager that
they use: pypulseq keeps each block that `get_block` reads when
`seq.use_block_cache` is true, and nothing removes it.

## 2. `grad_limits`: gradient amplitude and slew

A gradient event is the straight lines between its corner points (a
trapezoid) or its sample points (an arbitrary gradient), as the Pulseq
specification treats it (`seq_utils.gradient_points`). The slew is the
largest of two kinds of value:

- the slope of each straight line of each event;
- the step at each block junction, |last value of the block before - first
  value of this block|, divided by the gradient raster of the file
  (`seq.grad_raster_time`). An axis with no event in a block has the value 0
  there, and the value before the first block is 0. The scanner plays a step
  in one raster time, so a step is a slew like a slope. `add_block` accepts a
  step up to `max_slew * grad_raster_time`.

When several blocks have the largest value, the first of them in play order
gets it. A junction step comes before the lines of its block. A largest value
of 0 gives no block (`None`) and the time 0.0.

`gradient_limits(seq, *, window=None, limits=None, gamma=GAMMA) ->
GradientLimits` gives the largest values over the whole file, or over
`window = (start_s, end_s)`. A window must be in the sequence (each end within
`seq_utils.TIME_TOLERANCE`) and have `start_s < end_s`, or the function raises
`ValueError`. A line that crosses an end of the window is cut there. The
numbers do not depend on `limits`: the function gives `limits` back, so that
a caller can compare. With `limits=None`, it uses the limits of `seq.system`.
The default `gamma` is 42.576 MHz/T.

`GradientLimits`, a frozen dataclass:

| Field | Meaning |
|---|---|
| `reason` | `None` when the range has a gradient event. Otherwise a short text (`"no gradient events in the sequence"`, or `"no gradient events in the window"`), each number is 0.0 (except `whole_rms_mt_per_m`) and each block is `None`. |
| `range_s` | The range of the measurement: `(0.0, end_s)`, or the window. |
| `axes` | A dict from `"x"`, `"y"` and `"z"` to an `AxisResult`. |
| `vector_peak_mt_per_m` | The largest magnitude of the three-axis vector in the range. |
| `vector_peak_time_s`, `vector_peak_block` | The first time with that magnitude, and the block ID of the block that has it. |
| `limits` | The `HardwareLimits` of the call. |
| `whole_rms_mt_per_m` | With a window: a dict from each axis to its RMS over the whole file. `None` without a window. |

`AxisResult`, a frozen dataclass, for one axis:

| Field | Meaning |
|---|---|
| `peak_mt_per_m` | The largest absolute amplitude in the range. |
| `peak_time_s`, `peak_block` | The first time with it, and the block ID. |
| `max_slew_t_per_m_per_s` | The largest slew in the range (a slope or a junction step). |
| `slew_time_s`, `slew_block` | The start of that line (the start of the range when the range cuts the line), or the time of the junction; and the block ID. For a junction, the block is the block after the junction. |
| `rms_mt_per_m` | The RMS amplitude over the range. |

`HardwareLimits(max_grad_mt_per_m, max_slew_t_per_m_per_s, label)`, a frozen
dataclass that the package exports: the limits in mT/m and T/m/s, and a name
for them.

`block_gradient_values(seq, *, gamma=GAMMA) -> BlockGradientValues` gives the
same values for each block, not only the largest. The largest of each array is
the value of `gradient_limits` for the whole file, and its first play index is
the block of that value. It reads no block with `get_block`.

`BlockGradientValues`, a frozen dataclass. Each array has N entries, in play
order. A dict has the keys `"x"`, `"y"` and `"z"`, each with an array.

| Field | Meaning |
|---|---|
| `block_id`, `start_s` | int64 and float64: the block ID and the start of each block. |
| `peak_mt_per_m`, `peak_time_s` | Dicts: the largest absolute amplitude of the event of the block on the axis, and its time. |
| `slew_t_per_m_per_s`, `slew_time_s` | Dicts: the largest slope of a line of that event, and the start of that line. |
| `junction_t_per_m_per_s` | Dict: the junction step at the start of the block. Its time is `start_s`. |
| `vector_peak_mt_per_m`, `vector_peak_time_s` | The largest magnitude of the three-axis vector in the block, and its first time. |

A block with no event on an axis has the peak and the slope 0 there, at the
time `start_s`. Its junction step is not 0 when the block before it ends at a
value that is not 0.

## 3. `pns` and `pns_levels`: SAFE PNS

`pns.pns_levels_for(seq, *, gradient_asc=None, hardware=None) -> PnsLevels`
runs the SAFE model of the pinned pypulseq fork on the gradients of `seq`, and
keeps the result for the sequence object and the hardware. The hardware is
one of:

- `hardware=(struct, label)`: a SAFE hardware struct in the form of
  pypulseq's `asc_to_hw`, and a name for it.
- `gradient_asc`: the path of a Siemens gradient `.asc` file
  (`asc.read_gradient_asc`).
- neither: pypulseq's example hardware, which is not a real scanner
  (`asc.EXAMPLE_HARDWARE`).

Both together raise `ValueError`. `pns_levels.pns_levels` has the same
arguments, and keeps nothing.

The model takes one sample of each axis for each gradient raster time
`dt = seq.grad_raster_time`. Sample `k` is at the time `(k + 0.5) * dt`. The
samples of a block start at the start of that block. The value of an axis is
the output of the model for that axis, and the total of a sample is
`sqrt(x^2 + y^2 + z^2)` of the three values.

`PnsLevels`, a frozen dataclass:

| Field | Meaning |
|---|---|
| `reason` | `pns_levels.NO_GRADIENTS` when the sequence has no gradient event, or `None`. With `NO_GRADIENTS`, the peaks are 0, `peak_time_s` is `None` and there are no bins and no intervals. |
| `hardware`, `asc_file` | The name of the hardware, and the name of the `.asc` file or `None`. |
| `hw` | The SAFE parameters of each axis that the model used (a dict from `"x"`, `"y"` and `"z"` to a dict). |
| `dt_s`, `num_samples` | The time step and the number of samples. |
| `peak` | The largest total. The limit is `pns_levels.PNS_LIMIT` (1.0). |
| `peak_time_s` | The time of the first sample whose total is within `pns_levels.PEAK_TOLERANCE` (a fraction) of the peak. |
| `axis_peaks` | A dict from each axis to its largest value. |
| `above_limit` | A tuple of `PnsInterval`, in time order: each run of consecutive samples whose total is at or above 1.0. It is empty when `peak < 1.0`, and otherwise the largest `PnsInterval.peak` is `peak`. |
| `bin_samples`, `level_min`, `level_max` | The level, for a plot: float32 arrays with the minimum and the maximum total of each bin of `bin_samples` samples (the last bin can have fewer). Each total of a bin is in `[level_min, level_max]` of the bin. |
| `on_raster` | `True` when the duration of each block is a whole number of samples. Otherwise the samples come from the waveform of the whole file at the same times (`GradientSampler.sample`). |

`PnsInterval`, a frozen dataclass: `start_s` and `end_s` (the times of the
first and the last sample), `peak` (the largest total), `peak_time_s` (the
first sample with it) and `num_samples`.

`pns_levels.SAFE_FIELDS` is the nine fields of each axis of a SAFE hardware
struct, in the order of `safe_example_hw` and `asc_to_hw`. pulseq-checks makes
the `hardware` argument from a target profile (see the `docs/usage.md` of
pulseq-checks).

For a report, `pns.pns_prediction(seq, *, gradient_asc=None) -> PnsPrediction`
gives the summary only (`reason`, `hardware`, `asc_file`, `peak`,
`peak_time_s`, `axis_peaks`), and `pns.peak_tr_window(seq, peak_time_s)` gives
the start and end of the TR that holds a time (from the `TR` definition of the
file), or `None`.

## 4. The other modules

`sampling.GradientSampler(seq, index)` gives the gradient waveform of one axis
(`"gx"`, `"gy"` or `"gz"`), in Hz/m:

- `sample(axis, t)`: the values at the sorted times `t`. They are the straight
  lines between the points of all the events of the axis, also across a gap
  between two events, and 0 before the first point and after the last point.
  This is the waveform of pypulseq's `Sequence.get_gradients()`. Where two
  events have a point at the same time (a step at a block junction), it keeps
  the point of the earlier event.
- `block_samples(axis, first, stop, dt)`: the samples of the play indexes
  `first` to `stop - 1`, each block on its own at the times `(j + 0.5) * dt`
  from its start, with the values of its own event and 0 outside it. This is
  what the PNS model uses. It raises `ValueError` when a block of the range is
  not a whole number of samples long.

`sampling.raster_block_lengths(index, dt)` gives the number of samples of each
block, `round(duration / dt)`, and whether each block is within
`sampling.ON_RASTER_TOLERANCE` samples of that number.

`seq_utils`:

| Name | Meaning |
|---|---|
| `gradient_offsets(g)` | The delay, and the times after the delay and the amplitudes (Hz/m) of the points of the gradient event `g`. |
| `gradient_points(g, t0)` | The times (`t0` + delay + offset) and the amplitudes of the points of `g`. |
| `hold_samples(rf, raster)` | The complex samples (Hz) of the RF event `rf`, each held for one time step, and that time step. |
| `GAMMA` | 42.576e6 Hz/T, the default gamma of `grad_limits`. |
| `TIME_TOLERANCE` | 1e-9 s. A line shorter than this has no slope. |

`asc.read_gradient_asc(path)` gives the fields of a Siemens gradient `.asc`
file (`MP_GPA_*.asc` or `MP_GradSys_*.asc`), with the fields of each file that
an `$INCLUDE` line names. `asc.hardware_name(asc)` gives the name of the
component in those fields.

`extensions.refuse_rotations(seq)` raises `NotImplementedError` when `seq`
uses the Pulseq rotation extension. A function that measures the gradients of
the file calls it first.
