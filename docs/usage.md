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
5. [`series`: values for JSON](#5-series-values-for-json)
6. [`analyses`: the analyses and their registry](#6-analyses-the-analyses-and-their-registry)
7. [`grad_spectrum`: the gradient spectrum](#7-grad_spectrum-the-gradient-spectrum)

| Module | What it gives |
|---|---|
| `pulseq_analysis.seq_index` | The block table of a sequence, and the unique events. |
| `pulseq_analysis.grad_limits` | The peak amplitude, peak slew and RMS of the gradients, for the whole file and for each block. |
| `pulseq_analysis.pns` and `pulseq_analysis.pns_levels` | The SAFE PNS prediction. |
| `pulseq_analysis.grad_spectrum` | The spectrum of the gradients (section 7). |
| `pulseq_analysis.sampling` | The gradient waveform of one axis at given times. |
| `pulseq_analysis.seq_utils` | The points of one gradient event, the samples of one RF event, and the constants. |
| `pulseq_analysis.asc` | The read of a Siemens gradient `.asc` file. |
| `pulseq_analysis.extensions` | The refusal of the Pulseq extensions that the measurements do not support. |
| `pulseq_analysis.series` | `Series`, the form of a value that can go into JSON, and the encoding of an array. |
| `pulseq_analysis.analyses` | The `Analysis` protocol, the registry of the installed analyses, and the five analyses of this package. |

These rules apply to all the modules:

- **Logical axes.** The gradient and PNS values are of the logical axes of
  the file (x, y, z), not of the physical axes of a scanner. On an oblique
  slice, one physical axis can get the magnitude of the three-axis vector.
- **Rotation extension.** `gradient_limits`, `block_gradient_values`,
  `pns_levels` and `gradient_spectrum` raise `NotImplementedError` for a file
  with the Pulseq rotation extension (`extensions.refuse_rotations`), because the gradients
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
- **Rasters.** The gradient, PNS and spectrum measurements use the
  `GradientRasterTime` and the `BlockDurationRaster` of the sequence.
- **Units.** Gradient amplitudes are in mT/m and slew rates in T/m/s. The
  conversion from the Hz/m of pypulseq uses the `gamma` argument (Hz/T). A
  PNS value is a fraction of the stimulation limit: 1 is 100 %. The gradient
  spectrum is the exception: it is in Hz/m/√Hz, with no gamma
  ([section 7](#7-grad_spectrum-the-gradient-spectrum)).
- **Kept results.** `sequence_index`, `pns.pns_levels_for` and
  `grad_spectrum.gradient_spectrum_for` keep their result for the sequence
  object (`pns_levels_for` for each hardware and each tuple of thresholds of
  that object, `gradient_spectrum_for` for each set of its arguments). They
  build it again when the number of blocks or the ID of the last block
  changed, for example after `add_block`.
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

`gradient_limits(seq, *, window=None, gamma=GAMMA) -> GradientLimits` gives
the largest values over the whole file, or over `window = (start_s, end_s)`. A
window must be in the sequence (each end within `seq_utils.TIME_TOLERANCE`)
and have `start_s < end_s`, or the function raises `ValueError`. A line that
crosses an end of the window is cut there. The default `gamma` is
42.576 MHz/T. The function does not compare the values with limits: a caller
that has the limits of a scanner compares them, with the gamma that converted
those limits.

`GradientLimits`, a frozen dataclass:

| Field | Meaning |
|---|---|
| `reason` | `None` when the range has a gradient event. Otherwise a short text (`"no gradient events in the sequence"`, or `"no gradient events in the window"`), each number is 0.0 (except `whole_rms_mt_per_m`) and each block is `None`. |
| `range_s` | The range of the measurement: `(0.0, end_s)`, or the window. |
| `axes` | A dict from `"x"`, `"y"` and `"z"` to an `AxisResult`. |
| `vector_peak_mt_per_m` | The largest magnitude of the three-axis vector in the range. |
| `vector_peak_time_s`, `vector_peak_block` | The first time with that magnitude, and the block ID of the block that has it. |
| `whole_rms_mt_per_m` | With a window: a dict from each axis to its RMS over the whole file. `None` without a window. |

`AxisResult`, a frozen dataclass, for one axis:

| Field | Meaning |
|---|---|
| `peak_mt_per_m` | The largest absolute amplitude in the range. |
| `peak_time_s`, `peak_block` | The first time with it, and the block ID. |
| `max_slew_t_per_m_per_s` | The largest slew in the range (a slope or a junction step). |
| `slew_time_s`, `slew_block` | The start of that line (the start of the range when the range cuts the line), or the time of the junction; and the block ID. For a junction, the block is the block after the junction. |
| `rms_mt_per_m` | The RMS amplitude over the range. |

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

`pns.pns_levels_for(seq, *, gradient_asc=None, hardware=None,
thresholds=(PNS_LIMIT,)) -> PnsLevels` runs the SAFE model of the pinned
pypulseq fork on the gradients of `seq`, and keeps the result for the sequence
object, the hardware and the thresholds. The hardware is one of:

- `hardware=(struct, label)`: a SAFE hardware struct in the form of
  pypulseq's `asc_to_hw`, and a name for it.
- `gradient_asc`: the path of a Siemens gradient `.asc` file
  (`asc.read_gradient_asc`).
- neither: pypulseq's example hardware, which is not a real scanner
  (`asc.EXAMPLE_HARDWARE`).

Both together raise `ValueError`. `thresholds` is a tuple of the totals
whose runs `PnsLevels.above` gives: finite `int` or `float` values above 0
(not a `bool`), with no two equal as floats, and at least one. Else
`ValueError`, before the sequence is read. The default is `(PNS_LIMIT,)`, the
stimulation limit 1.0. The same thresholds in another order are another kept
result, because the order of `above` is the order of `thresholds`.
`pns_levels.pns_levels` has the same arguments, and keeps nothing.

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
| `above` | A dict from each threshold (`float(t)`, in the order of `thresholds`) to a tuple of `PnsInterval`, in time order: each run of consecutive samples whose float64 total is at or above that threshold. A tuple is empty when `peak` is below its threshold, and otherwise its largest `PnsInterval.peak` is `peak`. All thresholds are found in one pass. Do not change the dict. |
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

## 5. `series`: values for JSON

A `Series` is the part of an analysis value that can go into JSON
(`Analysis.to_series`, [section 6](#6-analyses-the-analyses-and-their-registry)).
It is a frozen dataclass:

| Field | Meaning |
|---|---|
| `name` | A short, stable name, not empty, for example `"pns_total"`. |
| `kind` | A `SeriesKind` (below). |
| `unit` | The unit of the values, for example `"1"` (a fraction), `"mT/m"` or `"s"`. |
| `coord_unit` | The unit of the coordinate (below), not empty, for example `"s"` or `"Hz"`. It has no default. |
| `arrays` | A dict from a name to a one-dimensional numpy array of a bool, integer, float or complex dtype. All arrays of one series have the same length. |
| `coord_start`, `coord_step` | The coordinate of the first sample or bin, and the step of the coordinate (finite, above 0). |
| `coord_end` | The end of the last bin, in the coordinate. |
| `meta` | A dict of JSON scalars (`str`, `int`, `float`, `bool` or `None`) by name. A string cannot be `"inf"`, `"-inf"` or `"nan"`. |

The coordinate of a series is the quantity of its horizontal axis, for example
the time (unit "s") or the frequency (unit "Hz"). `unit` is the unit of the
values. `coord_unit` is the unit of the coordinate.

`SeriesKind`, and the arrays and fields of each kind:

| Kind | Meaning | Necessary arrays | Fields |
|---|---|---|---|
| `SAMPLES` | `value[k]` is at `coord_start + k * coord_step`. | `value`, and more of the same length | `coord_start`, `coord_step`; `coord_end` is `None` |
| `ENVELOPE` | `min[i]` and `max[i]` are the least and the greatest value in the bin `[coord_start + i * coord_step, coord_start + (i + 1) * coord_step)`. The last bin stops at `coord_end`. | `min`, `max`, and no other | `coord_start`, `coord_step`, `coord_end` |
| `POINTS` | `value[k]` is at `coord[k]`. | `coord`, `value`, and more of the same length | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |
| `RUNS` | A boolean that is true from `start[k]` to `end[k]`, and false elsewhere. | `start`, `end`, and a value of each run | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |

One `Series` can hold a time series, a spectrum or a profile along a position.
The kinds describe the shape of the data. They do not depend on the quantity
of the coordinate:

| Data | Kind | `coord_unit` |
|---|---|---|
| The SAFE PNS level | `ENVELOPE` | `"s"` |
| The runs above a PNS threshold | `RUNS` | `"s"` |
| A gradient spectrum | `SAMPLES` | `"Hz"` |
| The frequency ranges where a spectrum is at or above a level | `RUNS` | `"Hz"` |
| The peaks of a spectrum | `POINTS` | `"Hz"` |
| A 1D RF profile along a position | `SAMPLES` | `"m"` |
| A 1D RF profile along the frequency offset | `SAMPLES` | `"Hz"` |

The analyses of this package give only the PNS series and the gradient
spectrum series ([section 6](#6-analyses-the-analyses-and-their-registry)).
The other rows are examples.

`coord_unit` uses the SI symbol. No code checks it against a list of units.
A series has one coordinate, so it cannot hold a map on two coordinates. The
unit gives the quantity of the coordinate (`"s"` is the time, `"Hz"` is the
frequency, `"m"` is a position). When the unit does not give all of it, for
example which position, the analysis puts it in `meta`.

A `Series` raises `TypeError` for a value of a wrong type and `ValueError` for
a wrong value. It keeps its own dicts and a read-only copy of each array, in
native byte order, so a change to the caller's dicts or arrays does not change
it. `==` compares the fields, the array names in their order, and each array
with its dtype and `np.array_equal(..., equal_nan=True)`. A NaN equals a NaN.
A `Series` is not hashable.

`Series.to_obj()` gives a dict with the keys `name`, `kind`, `unit`,
`coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta` and `arrays`,
which `json.dumps(obj, allow_nan=False)` writes. A float field or a float of `meta` that is not
finite is the string `"inf"`, `"-inf"` or `"nan"`. `Series.from_obj(obj)` is
the inverse, and raises `ValueError` for a bad object.

`encode_array(a)` gives an array as `{"dtype", "length", "data"}`: the numpy
dtype name, the number of elements, and the little-endian bytes of the array,
gzipped (level 6, no time stamp, OS byte 255) and base64-encoded. This is the
text of `encode_tables` of pulseq-reports, so a report puts it into its page
with no new encoding. One array always gives the same text. A float that is
not finite is in the bytes. `decode_array(d)` is the inverse, and raises
`ValueError` when `"length"` does not agree with the data.

## 6. `analyses`: the analyses and their registry

An *analysis* calculates information about a sequence and does not change it.
It has:

- `spec`, an `AnalysisSpec` (a frozen dataclass): `id`, `version`, `title`,
  `description` (the contract of the value), `params` (the names of the
  keyword arguments of `compute`), `rasters` (the rasters of the sequence that
  it uses), `cost` (`"fast"` or `"slow"`) and `series` (what `to_series`
  gives, or `None`).
- `compute(seq, **params)`: the full Python value. The parameters are
  keyword-only.
- `to_series(value)`: a tuple of `Series`, the part of the value that can go
  into JSON. An analysis with nothing for JSON gives `()`.

A package gives its analyses as entry points of the group
`pulseq_analysis.analyses` (`analyses.GROUP`). The name of an entry point is
the ID, and its object is the analysis. `analyses.registry()` gives a dict
from each installed ID to its analysis. Two analyses with one ID, an entry
point that cannot load, and an object with no `spec.id` raise
`analyses.RegistryError`, with the names of the packages.

The analyses of this package (each `version` is 1):

| ID | Object | `compute` | `params` | `cost` | `to_series` |
|---|---|---|---|---|---|
| `seq.index` | `SEQ_INDEX` | `sequence_index(seq)` | none | fast | `()` |
| `gradient.limits` | `GRADIENT_LIMITS` | `gradient_limits(seq, gamma=gamma)`, the whole file | `gamma` | fast | `()` |
| `gradient.blocks` | `GRADIENT_BLOCKS` | `block_gradient_values(seq, gamma=gamma)` | `gamma` | fast | `()` |
| `pns.safe.levels` | `PNS_SAFE_LEVELS` | `pns_levels_for(seq, hardware=hardware, thresholds=thresholds)` | `hardware`, `thresholds` | slow | below |
| `gradient.spectrum` | `GRADIENT_SPECTRUM` | `gradient_spectrum_for(seq)`, with the defaults | none | slow | below |

The parameters have the defaults of the functions (`gamma=GAMMA`,
`hardware=None`, `thresholds=(PNS_LIMIT,)`). All the analyses except
`seq.index` use the rasters `GradientRasterTime` and `BlockDurationRaster`.

`to_series` of `pns.safe.levels` gives `()` for a sequence with no gradient
event (`NO_GRADIENTS`). Else it gives:

| Name | Kind | Unit | `coord_unit` | Arrays | `meta` |
|---|---|---|---|---|---|
| `pns_total` | `ENVELOPE` | `"1"` | `"s"` | `min`, `max`: `level_min` and `level_max` (float32) | `hardware`, `asc_file`, `dt_s`, `bin_samples`, `num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y`, `axis_peaks_z` |
| `pns_above_<t>`, one for each threshold in the order of `above` | `RUNS` | `"1"` | `"s"` | `start`, `end`, `num_samples` (int64), `peak`, `peak_time_s` (float64): one entry for each `PnsInterval` | `threshold` |

`<t>` is the threshold as `f"{t:g}"`, for example `pns_above_1` or
`pns_above_0.8`. Two thresholds with the same text (for example 1.0000001 and
1.0000002) raise `ValueError`. In `pns_total`, `coord_start` is 0, `coord_step`
is `bin_samples * dt_s` and `coord_end` is `num_samples * dt_s`. Sample `k` is
at `(k + 0.5) * dt_s`, and `start` and `end` of a run are the times of its
first and last sample. `peak_time_s` and the `meta` keys `dt_s` and
`peak_time_s` are times in seconds.

`gradient.spectrum` has no parameters. It uses the defaults of
`gradient_spectrum_for`, which are the defaults of pypulseq. A caller that
needs other values calls `gradient_spectrum_for` with them. This is as
`gradient.limits`, which has no `window`.

`to_series` of `gradient.spectrum` gives `()` for a sequence with no gradient
event (`NO_GRADIENTS`). Else it gives one series:

| Name | Kind | Unit | `coord_unit` | Arrays | `meta` |
|---|---|---|---|---|---|
| `gradient_spectrum` | `SAMPLES` | `"Hz/m/sqrt(Hz)"` | `"Hz"` | `value` (`rss`), `x`, `y`, `z`, in this order (float64) | `max_frequency_hz`, `window_s`, `frequency_oversampling` |

`coord_start` is 0.0 and `coord_step` is `frequency_hz[1]`, so
`coord_start + k * coord_step` is `frequency_hz[k]`. The `meta` values are
those of the call.

To use an analysis by its ID:

```python
from pulseq_analysis.analyses import registry

analysis = registry()["pns.safe.levels"]
levels = analysis.compute(seq, thresholds=(1.0, 0.8))
series = analysis.to_series(levels)
```

## 7. `grad_spectrum`: the gradient spectrum

The gradient spectrum shows which frequencies the gradient waveform has. The
method is that of pypulseq's `calculate_gradient_spectrum`:

- Each window is a 50 ms Hann window, and the windows overlap by 50 %. The
  mean of each window is removed. The spectrum of a window is the magnitude
  of its FFT, scaled as an amplitude spectral density: thus the unit has
  √Hz.
- The gradients are sampled to the end of the sequence. The sampled waveform
  has half a window of zeros at each end.
- In each window, the three axes combine as the RSS (the root of the sum of
  squares). The spectrum of an axis is its maximum over the windows. The RSS
  spectrum is the maximum over the windows of the RSS.
- The windows go through the FFT in chunks, so the memory does not grow with
  the length of the sequence.

`GradientSpectrum` is a frozen dataclass. F is the number of frequencies.

| Field | Meaning |
|---|---|
| `reason` | `grad_spectrum.NO_GRADIENTS` when the sequence has no gradient event, or `None`. With `NO_GRADIENTS`, `frequency_hz` and `rss` are empty and `axes` is `{}`. |
| `frequency_hz` | float64, F: the frequencies, from 0 to the highest frequency. |
| `axes` | A dict from `"x"`, `"y"` and `"z"` to a float64 array of F values in Hz/m/√Hz. |
| `rss` | float64, F: the RSS of the three axes, in Hz/m/√Hz. |
| `max_frequency_hz`, `window_s`, `frequency_oversampling` | The arguments of the call, as floats. The series of `gradient.spectrum` gives them in its `meta`. |

`gradient_spectrum(seq, *, max_frequency_hz=MAX_FREQUENCY_HZ,
window_s=FFT_WINDOW_S, frequency_oversampling=FREQUENCY_OVERSAMPLING) ->
GradientSpectrum` measures the whole sequence. `gradient_spectrum_for(seq, *,
...)` has the same arguments and the same result, and keeps the result.

| Argument | Default | Argument of pypulseq | Meaning |
|---|---|---|---|
| `max_frequency_hz` | `MAX_FREQUENCY_HZ` (2000.0) | `max_frequency` | The highest frequency of the result. |
| `window_s` | `FFT_WINDOW_S` (0.05) | `window_width` | The length of a Hann window. |
| `frequency_oversampling` | `FREQUENCY_OVERSAMPLING` (3.0) | `frequency_oversampling` | The length of the FFT is `round(frequency_oversampling * nwin)`, where `nwin = round(window_s / dt)` is the number of samples of a window. |

The three arguments are keyword-only. A value that the function refuses
raises `ValueError`, or `TypeError` for a value that is not a number or is a
`bool`. The function raises before it reads the blocks. The rules:

- Each argument is a finite number.
- `window_s` is above 0, and `nwin` is 2 or more at the gradient raster of the
  file.
- `frequency_oversampling` is 1 or more.
- `max_frequency_hz` is above 0, and at most the Nyquist frequency
  `1 / (2 * dt)`. It is at least the frequency step `1 / (nfft * dt)`, so that
  the result has two or more frequencies.

These arguments of pypulseq are not arguments here:

- The overlap. pypulseq has no argument for it. It stays 50 % (`nwin // 2`).
- `combine_mode` and `use_derivative`. They change what a value is, for
  example a spectrum of the slew rate. A later quantity gets its own function.
- `time_range`. The spectrum is of the whole sequence, as `gradient_limits`
  without `window`.
- `acoustic_resonances`. The resonances are data of a target, not of a
  sequence.

`gradient_spectrum` calls `extensions.refuse_rotations` first, so it raises
`NotImplementedError` for a file with the Pulseq rotation extension.

`gradient_spectrum_for` keeps its result for the sequence object, with one
result for each set of the three arguments. It builds the result again when
the number of blocks or the ID of the last block changed, for example after
`add_block`. A change that keeps both is not seen: make a new sequence object
for it. All the callers share the kept result. For this reason, each array of
a `GradientSpectrum` is read-only, also for `NO_GRADIENTS`: a change in place
raises `ValueError`.

The spectrum is in Hz/m/√Hz, the unit of the gradients of a `.seq` file. A
change to T/m needs gamma, the gyromagnetic ratio of the nucleus that the
scanner images. The `.seq` file does not give gamma. It is data of the
target, not of the sequence. Thus the spectrum depends only on the sequence.

To get mT/m/√Hz for a gamma γ in Hz/T, multiply each value by `1e3 / γ`. For
¹H, γ is 42.576 MHz/T (`seq_utils.GAMMA`), and 1 Hz/m/√Hz is
2.3487 × 10⁻⁵ mT/m/√Hz. The conversion is exact to the float rounding,
because each step of the method changes in proportion to a positive scale of
the waveform. This includes the RSS spectrum.

`gradient.limits` and `gradient.blocks` take `gamma` and give mT/m. The
spectrum does not.

```python
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.seq_utils import GAMMA

s = gradient_spectrum(seq)
rss_mt = s.rss * 1e3 / GAMMA  # mT/m/sqrt(Hz), for 1H: a new array
```

The arrays of the result are read-only, so `s.rss *= 1e3 / GAMMA` raises
`ValueError`. Convert to a new array, as in the example.
