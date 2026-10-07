# Using pulseq-analysis

`pulseq-analysis` measures a Pulseq sequence: the gradient amplitude and slew,
the SAFE PNS prediction, the gradient spectrum and the block table.
pulseq-checks uses it to check a sequence against the limits of a scanner, and
pulseq-reports uses it for its plots. This guide shows how to use it for its
main tasks.

[`docs/implementation.md`](implementation.md) gives the exact definitions, the
rules for the rare cases, and the algorithms and the cost of each call. The
names that the two documents give are the interface of the package. A name
that they do not give, or that starts with `_`, can change in any release.

Contents:

1. [Quick start](#1-quick-start)
2. [Before you start](#2-before-you-start)
3. [Check the gradient limits](#3-check-the-gradient-limits)
4. [Find where a value occurs](#4-find-where-a-value-occurs)
5. [Predict the PNS on a scanner](#5-predict-the-pns-on-a-scanner)
6. [Check the acoustic resonances](#6-check-the-acoustic-resonances)
7. [Run the analyses and write JSON](#7-run-the-analyses-and-write-json)
8. [The block table and the other modules](#8-the-block-table-and-the-other-modules)
9. [Units and gamma](#9-units-and-gamma)

## 1. Quick start

```python
import pypulseq as pp

from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.grad_peaks import gradient_peaks
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

seq = pp.Sequence()
seq.read("sequence.seq")  # a file that seq.write made: it has a [SIGNATURE] hash

peaks = gradient_peaks(seq)
print((peaks.axes["x"].peak_hz_per_m / abs(gamma)) * 1e3, "mT/m")  # T/m -> mT/m
print(peaks.axes["x"].max_slew_hz_per_m_per_s / abs(gamma), "T/m/s")

levels = pns_levels(seq, hardware=hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc"))
print(f"PNS: {levels.peak_hz_per_t / abs(gamma):.0%} of the limit")

spectrum = gradient_spectrum(seq)
print(spectrum.frequency_hz[spectrum.rss.argmax()], "Hz")
```

| Module | What it gives | Section |
|---|---|---|
| `pulseq_analysis.grad_peaks` | The peak amplitude, the peak slew and the RMS of the gradients, for the whole file, for a window and for each block. | [3](#3-check-the-gradient-limits), [4](#4-find-where-a-value-occurs) |
| `pulseq_analysis.pns_levels` | The SAFE PNS prediction. | [5](#5-predict-the-pns-on-a-scanner) |
| `pulseq_analysis.asc` | The read of a Siemens gradient `.asc` file into the hardware of `pns_levels`. | [5](#5-predict-the-pns-on-a-scanner) |
| `pulseq_analysis.grad_spectrum` | The spectrum of the gradients. | [6](#6-check-the-acoustic-resonances) |
| `pulseq_analysis.analyses` | The analyses of the package by ID, and their registry. | [7](#7-run-the-analyses-and-write-json) |
| `pulseq_analysis.series` | `Series`, the part of a value that goes into JSON. | [7](#7-run-the-analyses-and-write-json) |
| `pulseq_analysis.seq_index` | The block table, and the unique events. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.sampling` | The gradient waveform of one axis at given times. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.seq_utils` | The points of one gradient event, and `TIME_TOLERANCE`. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.extensions` | The refusal of the Pulseq extensions that the measurements do not support. | [2](#2-before-you-start) |

## 2. Before you start

- **A signed file.** A sequence must have a `[SIGNATURE]` hash, or each
  measurement raises `ValueError`. `seq.write(path)` signs a file. A sequence
  that `add_block` built in memory has none: write it and read it. Use a new
  `Sequence` object for each file
  ([implementation, section 7](implementation.md#7-the-signature-check)).
- **No rotation extension.** The gradient measurements raise
  `NotImplementedError` for a file with the Pulseq rotation extension
  (`extensions.refuse_rotations`), because the gradients of the file are not
  the gradients on the scanner.
- **Logical axes.** The values are of the logical axes of the file (x, y, z),
  not of the physical axes of a scanner. On an oblique slice, one physical
  axis can get the magnitude of the three-axis vector.
- **Units with no gamma.** The gradients are in Hz/m and Hz/m/s, the spectrum
  in Hz/m/√Hz and the PNS in Hz/T, as in pypulseq. Divide a value by |γ| to get
  the unit with tesla ([section 9](#9-units-and-gamma)).
- **The gradient waveform.** The measurements use the gradient waveform of
  MATLAB Pulseq. For almost all sequences it is the waveform that pypulseq
  draws. They differ only where an event starts or ends at a value that is not
  0 next to a gap, or at a step at a block junction
  ([implementation, section 1](implementation.md#1-the-gradient-waveform)).
- **Block ID and play index.** The *block ID* is the ID of pypulseq (a key of
  `seq.block_events`). The *play index* is the position of a block in play
  order, from 0. The arrays of a result have one entry for each play index.
  Use `block_id[i]` to get the block ID of play index `i`. A time is in
  seconds from the start of the sequence.
- **Kept, read-only results.** Each measurement keeps its result for the
  sequence object, so a second call with the same arguments costs nothing and
  gives the same object. The package builds it again after `add_block`, after
  a new `seq.read` and after a change of `seq.grad_raster_time`. All callers
  share a kept result, so its arrays and dicts are read-only. Make a copy to
  change one: `np.array(a)`, `dict(d)`
  ([implementation, sections 4 and 5](implementation.md#4-kept-results)).
- **Changes that the kept results do not see.** Some pypulseq calls change a
  sequence in place and keep the number of blocks and the last block ID:
  `mod_grad_axis` and `flip_grad_axis` (they rewrite the entries of the
  gradient library), `set_block` on a block ID that exists, `apply_soft_delay`
  (it writes the block durations), and a direct write into `seq.block_events`,
  `seq.block_durations` or a library. The package does not see them, so a
  measurement that the object has kept gives the old value. After such a
  change, make a new `Sequence` object, for example by reading the file again.
- **No result.** A result without a value has the `reason`
  `seq_index.NO_GRADIENTS` ("no gradients"), or
  `seq_index.NO_GRADIENTS_IN_WINDOW` for a window of `gradient_peaks`. Its
  numbers are 0.0, its block fields are `None` and its arrays are empty, but
  the fields that say how it was made stay. `GradientPeaks` keeps `range_s`.
  `PnsLevels` keeps `hardware`, `hw`, `dt_s`, `bin_samples` and `on_raster`, has
  `num_samples` 0, and has `peak_time_s` `None` and an empty tuple in `above`
  for each threshold. `GradientSpectrum` keeps its three arguments.
  `block_gradient_values` has no `reason`: for a sequence with no gradient it
  gives zero arrays of length N.
- **Bad arguments.** An argument of a wrong type raises `TypeError`, and a
  value out of range raises `ValueError`, before the sequence is read
  ([implementation, section 6](implementation.md#6-argument-checks)).

**The cost of each call.** The time of a call grows with the size of the
sequence in one of two ways: with the number of blocks, or with the duration
(the number of gradient raster samples). On an Apple M1 Max, for a GRE
sequence of 100,000 blocks (120 s, 258 unique gradient events):

| Call | Grows with | Time |
|---|---|---|
| `sequence_index` | blocks | 60 ms |
| `gradient_peaks(seq)`, `block_gradient_values` | blocks, and unique gradient events | 75 ms |
| `gradient_peaks(seq, window=...)`, after the first call | (almost constant) | 1 ms |
| `pns_levels` | duration | 1.0 s |
| `gradient_spectrum` | duration | 1.0 s |

The first gradient measurement of a sequence also reads its block table and
the points of its unique gradient events, and the later measurements use them.
[Implementation, section 3](implementation.md#3-algorithms-and-cost) gives the
algorithms, their complexity and more measured times.

## 3. Check the gradient limits

`gradient_peaks(seq)` gives the largest values of the gradients over the whole
file: for each axis the peak amplitude, the peak slew and the RMS, and the
peak of the three-axis vector. The function does not compare them with
limits: compare them with the limits of your scanner. pypulseq's `Opts` keeps
`max_grad` in Hz/m and `max_slew` in Hz/m/s, so the limits and the values have
the same units.

```python
import pypulseq as pp

from pulseq_analysis.grad_peaks import gradient_peaks

system = pp.Opts(max_grad=40, grad_unit="mT/m", max_slew=200, slew_unit="T/m/s")

peaks = gradient_peaks(seq)
for axis, result in peaks.axes.items():
    if result.peak_hz_per_m > system.max_grad:
        print(f"{axis}: amplitude over the limit in block {result.peak_block}")
    if result.max_slew_hz_per_m_per_s > system.max_slew:
        print(f"{axis}: slew over the limit at {result.slew_time_s:.6f} s")
```

The slew includes the steps of the waveform: a step at a block junction counts
as a slew of `|step| / grad_raster_time`, because the scanner plays it in one
raster time.

`GradientPeaks`:

| Field | Meaning |
|---|---|
| `reason` | `None`, or `NO_GRADIENTS` (or `NO_GRADIENTS_IN_WINDOW`) when the range has no gradient. |
| `range_s` | The range of the measurement: `(0.0, end_s)`, or the window ([section 4](#4-find-where-a-value-occurs)). |
| `axes` | A dict from `"x"`, `"y"` and `"z"` to an `AxisResult`. |
| `vector_peak_hz_per_m` | The largest magnitude of the three-axis vector (Hz/m). |
| `vector_peak_time_s`, `vector_peak_block` | The first time with that magnitude, and its block ID. |

`AxisResult`, for one axis:

| Field | Meaning |
|---|---|
| `peak_hz_per_m` | The largest absolute amplitude (Hz/m). |
| `peak_time_s`, `peak_block` | The first time with it, and its block ID. |
| `max_slew_hz_per_m_per_s` | The largest slew: the slope of a segment, or a step (Hz/m/s). |
| `slew_time_s`, `slew_block` | The start of that segment or the time of that step, and its block ID. |
| `rms_hz_per_m` | The RMS amplitude over the range (Hz/m). |

When several blocks have the largest value, the first of them in play order
is the block of the value. A largest value of 0 has the block `None` and the
time 0.0. A ramp or a line between two events can belong to the block before
or after it ([implementation, section 1.6](implementation.md#16-the-credit-of-each-item-to-a-block)).

## 4. Find where a value occurs

Each value of `gradient_peaks` has its block and its time. For more, there are
two ways.

**The values of each block.** `block_gradient_values(seq)` gives the same
values for each block, as arrays in play order. Use it to plot the values
along the sequence, or to find all the blocks over a limit:

```python
import numpy as np

from pulseq_analysis.grad_peaks import block_gradient_values

values = block_gradient_values(seq)
slew_x = np.maximum(values.slew_hz_per_m_per_s["x"], values.junction_hz_per_m_per_s["x"])
over = np.flatnonzero(slew_x > system.max_slew)
for i in over:
    print(f"block {values.block_id[i]} at {values.start_s[i]:.6f} s")
```

| Field | Meaning |
|---|---|
| `block_id`, `start_s` | The block ID and the start of each block. |
| `peak_hz_per_m`, `peak_time_s` | Dicts by axis: the largest absolute amplitude of the block (Hz/m), and its time. |
| `slew_hz_per_m_per_s`, `slew_time_s` | Dicts by axis: the largest slope in the block, with the ramps of its event (Hz/m/s), and its time. |
| `junction_hz_per_m_per_s` | Dict by axis: the step or the line into the event of the block from the event before it (Hz/m/s). |
| `vector_peak_hz_per_m`, `vector_peak_time_s` | The largest magnitude of the three-axis vector in the block (Hz/m), and its first time. |

The slew of a block is the larger of `slew_hz_per_m_per_s` and
`junction_hz_per_m_per_s`. The largest of each array over all the blocks is
the value of `gradient_peaks(seq)`. A block with no event on an axis has the
values 0 there.
[Implementation, section 2.1](implementation.md#21-gradient_peaks-and-block_gradient_values)
gives each field exactly.

**A window.** `gradient_peaks(seq, window=(start_s, end_s))` gives the largest
values in that range of time, for example one TR or the time of one ADC:

```python
tr = 6e-3
peaks_tr_10 = gradient_peaks(seq, window=(10 * tr, 11 * tr))
```

The window must be in the sequence, with `start_s < end_s`. A segment that
crosses an end of the window is cut there. A step is in the window when
`start_s <= t < end_s`. A result with a window is not kept, because a caller
can ask for many windows, but it uses the kept values of each block. So after
the first call, a window costs about the number of blocks in it.

## 5. Predict the PNS on a scanner

`pns_levels(seq, hardware=..., thresholds_hz_per_t=(), bin_s=BIN_S)` runs the
SAFE PNS model of pypulseq on the gradients of the sequence.

**The hardware.** The model needs the SAFE parameters of the gradient coil of
the scanner. There is no default. `hardware` is a pair `(struct, label)`: a
SAFE hardware struct in the form of pypulseq's `asc_to_hw`, and a name for it.
`asc.hardware_from_asc(path)` makes the pair from the Siemens gradient `.asc`
file of the scanner (`MP_GPA_*.asc` or `MP_GradSys_*.asc`), with the files of
its `$INCLUDE` lines. For a test, pypulseq's example hardware, which is not a
real scanner, is `hardware=(safe_example_hw(), "a label")` (`safe_example_hw`
is in `pypulseq.utils.safe_pns_prediction`).

**The limit.** The PNS values are in Hz/T. The stimulation limit is `abs(gamma)`,
and a value divided by `abs(gamma)` is the fraction of the limit. To find the
times above a fraction `f` of the limit, give the threshold `f * abs(gamma)`:

```python
from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")
levels = pns_levels(seq, hardware=hardware, thresholds_hz_per_t=(abs(gamma), 0.8 * abs(gamma)))

print(f"peak {levels.peak_hz_per_t / abs(gamma):.0%} at {levels.peak_time_s:.4f} s")
for run in levels.above[0.8 * abs(gamma)]:
    print(f"over 80 % from {run.start_s:.4f} s to {run.end_s:.4f} s")
```

**The level, for a plot.** `level_min_hz_per_t` and `level_max_hz_per_t`
are the least and the greatest total of each bin of `bin_s` (5 ms by
default):

```python
import numpy as np

t_s = np.arange(levels.level_max_hz_per_t.size) * levels.bin_samples * levels.dt_s
percent = (levels.level_max_hz_per_t / abs(gamma)) * 100  # fraction -> %, a new array
```

`PnsLevels`:

| Field | Meaning |
|---|---|
| `reason` | `None`, or `NO_GRADIENTS`: then the peaks are 0, `peak_time_s` is `None`, and there are no bins and no runs. |
| `hardware` | The label of the hardware. |
| `hw` | The SAFE parameters of each axis that the model used. |
| `peak_hz_per_t`, `peak_time_s` | The largest total (Hz/T), and the time of its first sample. |
| `axis_peaks_hz_per_t` | A dict from each axis to its largest value (Hz/T). |
| `above` | A dict from each threshold to a tuple of `PnsInterval`: the runs at or above it, in time order. `{}` with no threshold. |
| `dt_s`, `num_samples` | The time step (the gradient raster) and the number of samples. |
| `bin_samples`, `level_min_hz_per_t`, `level_max_hz_per_t` | The level: the samples of a bin, and the least and the greatest total of each bin (float32, Hz/T). |
| `on_raster` | `True` when each block is a whole number of raster times. |

`PnsInterval`: `start_s` and `end_s` (the edges of the samples of the run),
`peak_hz_per_t` and `peak_time_s` (its largest total and the time of its first
sample with it), and `num_samples`.

The model takes one sample of each axis at the middle of each raster time. The
total of a sample is `sqrt(x^2 + y^2 + z^2)` of the outputs of the model for
the three axes. pypulseq's `seq.calculate_pns` gives the same values divided by
`seq.system.gamma`, for almost all sequences
([implementation, section 2.2](implementation.md#22-pns_levels)).

The cost of `pns_levels` grows with the duration of the sequence, not with the
number of blocks: about 80 ns for each raster time (10 µs) of the sequence,
or 1 s for 2 minutes. A change of
`hardware`, of the thresholds or of `bin_s` is a new result, which runs the
model again.

## 6. Check the acoustic resonances

`gradient_spectrum(seq)` gives the spectrum of the gradients: for each
frequency, the largest amplitude over 50 ms windows of the sequence. Compare
it with the acoustic resonances of the gradient coil of the scanner (the
frequency and the bandwidth of each):

```python
import numpy as np

from pulseq_analysis.grad_spectrum import gradient_spectrum

gamma = 42.576e6  # Hz/T

resonances = [(590.0, 100.0), (1140.0, 220.0)]  # (Hz, Hz): the resonances of the coil

s = gradient_spectrum(seq)
for frequency, bandwidth in resonances:
    band = np.abs(s.frequency_hz - frequency) <= bandwidth / 2
    peak = (s.rss[band].max() / abs(gamma)) * 1e3  # T/m/sqrt(Hz) -> mT/m/sqrt(Hz)
    print(f"{frequency:.0f} Hz: {peak:.3g} mT/m/sqrt(Hz)")
```

The method is that of pypulseq's `calculate_gradient_spectrum`: Hann windows
that overlap by 50 %, the magnitude of the FFT of each window as an amplitude
spectral density, the RSS of the three axes in each window, and the maximum
over the windows ([implementation, section 2.3](implementation.md#23-gradient_spectrum)).

| Argument | Default | Argument of pypulseq | Meaning |
|---|---|---|---|
| `max_frequency_hz` | `MAX_FREQUENCY_HZ` (2000.0) | `max_frequency` | The highest frequency of the result. |
| `window_s` | `FFT_WINDOW_S` (0.05) | `window_width` | The length of a window. |
| `frequency_oversampling` | `FREQUENCY_OVERSAMPLING` (3.0) | `frequency_oversampling` | The length of the FFT, as a multiple of the samples of a window. |

The three arguments are keyword-only. `max_frequency_hz` is at most the
Nyquist frequency of the gradient raster.

`GradientSpectrum`:

| Field | Meaning |
|---|---|
| `reason` | `None`, or `NO_GRADIENTS`: then the arrays are empty. |
| `frequency_hz` | The frequencies, from 0 to the highest frequency. |
| `axes` | A dict from `"x"`, `"y"` and `"z"` to the spectrum of that axis (Hz/m/√Hz). |
| `rss` | The RSS spectrum of the three axes (Hz/m/√Hz). |
| `max_frequency_hz`, `window_s`, `frequency_oversampling` | The arguments of the call. |

The cost grows with the duration of the sequence. The memory does not: the
windows go through the FFT in chunks.

## 7. Run the analyses and write JSON

An *analysis* is a measurement with an ID, a version, a specification of its
parameters and a form for JSON. A runner such as pulseq-checks finds the
installed analyses with `analyses.registry()`, and runs them by ID:

```python
import json

from pulseq_analysis.analyses import registry
from pulseq_analysis.asc import hardware_from_asc

gamma = 42.576e6  # Hz/T

analysis = registry()["pns.safe.levels"]
levels = analysis.compute(
    seq,
    hardware=hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc"),
    thresholds_hz_per_t=(abs(gamma),),
)
text = json.dumps([s.to_obj() for s in analysis.to_series(levels)], allow_nan=False)
```

An analysis has:

- `spec`, an `AnalysisSpec`: `id`, `version`, `title`, `description` (the
  contract of the value), `params` (the keyword arguments of `compute`),
  `necessary` (the arguments with no default), `defaults` (pairs
  `(name, default)`), `rasters` (the rasters of the file that change its
  value), `cost` (`"fast"` or `"slow"`) and `series` (what `to_series` gives).
- `compute(seq, **params)`: the full Python value, the kept result of its
  function.
- `to_series(value)`: a tuple of `Series`, the part of the value that can go
  into JSON. `()` for an analysis with nothing for JSON, and for a value with
  `NO_GRADIENTS`.

The analyses of this package (each `version` is 1):

| ID | `compute` | Necessary | Defaults | Cost | `to_series` |
|---|---|---|---|---|---|
| `seq.index` | `sequence_index(seq)` | none | none | fast | `()` |
| `gradient.peaks` | `gradient_peaks(seq, window=window)` | none | `window=None` | fast | `()` |
| `gradient.blocks` | `block_gradient_values(seq)` | none | none | fast | `()` |
| `pns.safe.levels` | `pns_levels(seq, hardware=..., thresholds_hz_per_t=..., bin_s=...)` | `hardware` | `thresholds_hz_per_t=()`, `bin_s=BIN_S` | slow | `pns_total`, `pns_above_<k>` |
| `gradient.spectrum` | `gradient_spectrum(seq, max_frequency_hz=..., window_s=..., frequency_oversampling=...)` | none | the defaults of `grad_spectrum` | slow | `gradient_spectrum` |

`seq.index` has the rasters `("BlockDurationRaster",)`. The other four have
`("GradientRasterTime", "BlockDurationRaster")`.

The series:

| Name | Kind | Unit | `coord_unit` | Arrays | `meta` |
|---|---|---|---|---|---|
| `pns_total` | `ENVELOPE` | `"Hz/T"` | `"s"` | `min`, `max`: the level (float32) | `hardware`, `dt_s`, `bin_samples`, `num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y`, `axis_peaks_z` |
| `pns_above_<k>`, one for each threshold, `k` from 0 in the order of `thresholds_hz_per_t` | `RUNS` | `"Hz/T"` | `"s"` | `start`, `end`, `num_samples` (int64), `peak`, `peak_time_s` (float64): one entry for each run | `threshold` |
| `gradient_spectrum` | `SAMPLES` | `"Hz/m/sqrt(Hz)"` | `"Hz"` | `value` (the RSS), `x`, `y`, `z` (float64) | `max_frequency_hz`, `window_s`, `frequency_oversampling` |

In `pns_total`, `coord_start` is 0, `coord_step` is `bin_samples * dt_s` and
`coord_end` is `num_samples * dt_s`. In `gradient_spectrum`, `coord_start` is
0.0 and `coord_step` is `frequency_hz[1]`.

**`Series`.** A `Series` is a frozen dataclass with the fields `name`, `kind`,
`unit` (of the values), `coord_unit` (of the coordinate, for example `"s"` or
`"Hz"`), `arrays` (a dict of one-dimensional arrays of one length),
`coord_start`, `coord_step`, `coord_end` and `meta` (a dict of JSON scalars).
The kind gives the shape of the data:

| Kind | Meaning | Necessary arrays | Fields |
|---|---|---|---|
| `SAMPLES` | `value[k]` is at `coord_start + k * coord_step`. | `value`, and more of the same length | `coord_start`, `coord_step`; `coord_end` is `None` |
| `ENVELOPE` | `min[i]` and `max[i]` are the least and the greatest value in bin `i`, from `coord_start + i * coord_step`. The last bin stops at `coord_end`. | `min`, `max`, and no other | `coord_start`, `coord_step`, `coord_end` |
| `POINTS` | `value[k]` is at `coord[k]`. | `coord`, `value`, and more of the same length | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |
| `RUNS` | A boolean that is true from `start[k]` to `end[k]`. | `start`, `end`, and a value of each run | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |

A `Series` is read-only: its arrays cannot be made writable, also in a copy from
`pickle` or `copy.deepcopy`. An `ENVELOPE` has `min` and `max` of one integer or
float dtype with `min <= max`, and `POINTS` has a `coord` of an integer or float
dtype. A numpy scalar in `meta` is stored as a Python scalar.

`Series.to_obj()` gives a dict that `json.dumps(obj, allow_nan=False)` writes,
and `Series.from_obj(obj)` is the inverse (it raises `ValueError` for a bad
object, also for a number that is too large for a float). `encode_array(a)` gives an array as
compact text (`{"dtype", "length", "data"}`, gzipped and base64-encoded), the
encoding of the tables of pulseq-reports, and `decode_array(d)` is the
inverse ([implementation, section 8](implementation.md#8-series-checks-and-the-array-encoding)).

**Your own analysis.** A package gives its analyses as entry points of the
group `pulseq_analysis.analyses` (`analyses.GROUP`). The name of an entry point
is the ID, and its object is the analysis. `analyses.registry()` gives a dict
from each installed ID to its analysis, and raises `analyses.RegistryError`
for two analyses with one ID or an entry point that does not load.

## 8. The block table and the other modules

**The block table.** `sequence_index(seq)` gives a `SequenceIndex`: one entry
for each block in play order, with the unique events of each kind numbered
from 1 in the order of their first use. It reads no block with `get_block`.
N is the number of blocks, and K the number of unique events of one kind.

| Field | Meaning |
|---|---|
| `num_blocks` | N. |
| `block_id` | uint32, N: the block ID of each play index. |
| `start_s`, `duration_s` | float64, N: the start and the duration of each block. |
| `end_s` | The end of the last block. 0.0 without blocks. |
| `rf`, `adc` | N: the number of the RF (ADC) event of each block, 0 for no event. |
| `gx`, `gy`, `gz` | N: the number of the gradient event of each block on that axis, 0 for no event. The three axes share one number space. |
| `rf_first`, `adc_first` | int64, K: the play index of the first block of event `k + 1`. |
| `grad_first` | int64, K: the same for gradient event `k + 1`. |
| `grad_first_axis` | uint8, K: 0, 1 or 2 for gx, gy or gz in that first block. |

The event columns use the smallest of uint8, uint16 and uint32 that holds K.
Convert a value with `int(x)` when you need a Python `int`. This layout is the
contract of the analysis `seq.index` version 1: a caller that reads the index
through the registry can rely on it, and a change of the layout raises
`spec.version` of `seq.index`.

`has_gradients(index)` is true when the index has a gradient event on any
axis. `rf_events(seq, index)`, `grad_events(seq, index)` and
`adc_events(seq, index)` give `(number, event)` for each unique event, in the
order of the numbers: the pypulseq event of the first block that uses it.

**The gradient waveform.** `sampling.gradient_sampler(seq)` gives a
`GradientSampler`. `sampler.sample(axis, t)` gives the waveform of one axis
(`"gx"`, `"gy"` or `"gz"`) in Hz/m at the sorted times `t`, for a plot:

```python
import numpy as np

from pulseq_analysis.sampling import gradient_sampler

t = np.linspace(0.0, 0.01, 2001)  # the first 10 ms
gx = gradient_sampler(seq).sample("gx", t)
```

`block_samples`, `raster_block_lengths` and `sequence_samples` give the
samples on the gradient raster that the PNS model and the spectrum use
([implementation, section 2.4](implementation.md#24-the-sampler-and-the-number-of-samples)).

**`seq_utils`.** `gradient_offsets(g)` gives the delay, and the times after
the delay and the amplitudes (Hz/m) of the points of the gradient event `g`.
`gradient_points(g, t0)` gives the times (`t0` + delay + offset) and the
amplitudes. `TIME_TOLERANCE` is 1e-9 s.

**`asc`.** Besides `hardware_from_asc`, `asc.read_gradient_asc(path)` gives
the fields of a `.asc` file, with the fields of each file that an `$INCLUDE`
line names, and `asc.hardware_name(asc)` gives the name of the component in
those fields.

**`extensions`.** `refuse_rotations(seq)` raises `NotImplementedError` when
`seq` uses the Pulseq rotation extension, and `refuse_unsigned(seq)` raises
`ValueError` for a sequence with no `[SIGNATURE]` hash. The gradient
measurements call them, in this order:

- `gradient_peaks`, `block_gradient_values`, `gradient_spectrum` and
  `gradient_sampler` call `refuse_rotations` first, before they check their other
  arguments. `gradient_peaks` checks the form of `window` next, and then
  `sequence_index`, which calls `refuse_unsigned`, so a window that is not a
  pair of numbers in order raises before an unsigned sequence does.
  `gradient_spectrum` checks its arguments before `sequence_index`.
- `pns_levels` checks its arguments first. It calls `refuse_rotations` and
  `sequence_index` (so `refuse_unsigned`) only when it builds a result: a result
  that it has kept for the sequence object skips them. `gradient_spectrum` skips
  `sequence_index` for a kept result in the same way.

## 9. Units and gamma

No value of this package uses a gamma. Gamma (γ) is the gyromagnetic ratio of
the nucleus that the scanner images. A `.seq` file does not give it: it is
data of the target, not of the sequence. pypulseq keeps the gradients in Hz/m.
Thus the values of this package are in Hz/m, Hz/m/s, Hz/m/√Hz and Hz/T.

**The rule.** To get the unit with tesla, divide the value by |γ| in Hz/T.
Each of these values is a magnitude (0 or above), so use the magnitude of γ.
pypulseq's `Opts` also converts with `abs(gamma)`.

| Values | Unit | Divided by \|γ\| | For ¹H (γ = 42.576 MHz/T) |
|---|---|---|---|
| Amplitudes: `AxisResult.peak_hz_per_m`, `AxisResult.rms_hz_per_m`, `GradientPeaks.vector_peak_hz_per_m`, `BlockGradientValues.peak_hz_per_m`, `BlockGradientValues.vector_peak_hz_per_m` | Hz/m | T/m (times 1e3: mT/m) | 1 mT/m is 42 576 Hz/m |
| Slew rates: `AxisResult.max_slew_hz_per_m_per_s`, `BlockGradientValues.slew_hz_per_m_per_s`, `BlockGradientValues.junction_hz_per_m_per_s` | Hz/m/s | T/m/s | 1 T/m/s is 4.2576 × 10⁷ Hz/m/s |
| The spectrum: `GradientSpectrum.axes`, `GradientSpectrum.rss`, the series `gradient_spectrum` | Hz/m/√Hz | T/m/√Hz (times 1e3: mT/m/√Hz) | 1 Hz/m/√Hz is 2.3487 × 10⁻⁵ mT/m/√Hz |
| PNS: `PnsLevels.peak_hz_per_t`, `PnsLevels.axis_peaks_hz_per_t`, `PnsLevels.level_min_hz_per_t`, `PnsLevels.level_max_hz_per_t`, `PnsInterval.peak_hz_per_t`, the series `pns_total` and `pns_above_<k>` | Hz/T | The fraction of the stimulation limit (1 is 100 %) | The limit is 4.2576 × 10⁷ Hz/T |

**The thresholds, an input.** `thresholds_hz_per_t` of `pns_levels`
and `pns.safe.levels` is in Hz/T. For a fraction f of the
stimulation limit, give `f * abs(gamma)`. The limit is the fraction 1, so it is
`abs(gamma)`. The keys of `PnsLevels.above` and `meta["threshold"]` of
`pns_above_<k>` are the Hz/T values that you gave.

**The values with no gamma.** The times (each name that ends in `_s`), the
block IDs, the frequencies (`frequency_hz`), the numbers of samples,
`PnsLevels.hw` and `PEAK_TOLERANCE` do not change with gamma.

**Why the division is exact.** Each value changes in proportion to a scale of
the gradients. A peak, a slope and a step are magnitudes of the Hz/m
values. An RMS is the root of a mean of squares. The spectrum is linear. The
SAFE model is a sum of linear filters and absolute values of the slew, divided
by the stimulation limit. Thus the value divided by |γ| is the value of the
same measurement in tesla, to the float rounding. The tests compare it with
the oracles and with pypulseq's `calculate_pns`.

**The limits of a scanner.** Convert the values to the unit of the limits, or
convert the limits to the unit of the values. pypulseq's `Opts` keeps
`max_grad` in Hz/m and `max_slew` in Hz/m/s, converted with its own gamma.
Thus the `Opts` of a target gives limits in the units of the values
([section 3](#3-check-the-gradient-limits)).

The arrays of a result are read-only. Convert an array to a new array
(`(s.rss / abs(gamma)) * 1e3`, `(levels.level_max_hz_per_t / abs(gamma)) * 100`).
Do not change it in place: `s.rss *= 1e3 / abs(gamma)` raises `ValueError`.
