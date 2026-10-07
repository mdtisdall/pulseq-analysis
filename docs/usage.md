# Using pulseq-analysis

This document is the reference for a user of `pulseq-analysis`: the modules
that measure a Pulseq sequence. pulseq-checks uses them for its checks, and
pulseq-reports uses them for its plots. The names in this document are the
interface of these modules. A name that this document does not give, or that
starts with `_`, can change in any release.

Contents:

1. [`seq_index`: the block table](#1-seq_index-the-block-table)
2. [The gradient waveform](#2-the-gradient-waveform)
3. [`grad_peaks`: gradient amplitude and slew](#3-grad_peaks-gradient-amplitude-and-slew)
4. [`pns_levels`: SAFE PNS](#4-pns_levels-safe-pns)
5. [The other modules](#5-the-other-modules)
6. [`series`: values for JSON](#6-series-values-for-json)
7. [`analyses`: the analyses and their registry](#7-analyses-the-analyses-and-their-registry)
8. [`grad_spectrum`: the gradient spectrum](#8-grad_spectrum-the-gradient-spectrum)
9. [Units and gamma](#9-units-and-gamma)

| Module | What it gives |
|---|---|
| `pulseq_analysis.seq_index` | The block table of a sequence, and the unique events. |
| `pulseq_analysis.grad_peaks` | The peak amplitude, peak slew and RMS of the gradients, for the whole file and for each block. |
| `pulseq_analysis.pns_levels` | The SAFE PNS prediction. |
| `pulseq_analysis.grad_spectrum` | The spectrum of the gradients (section 8). |
| `pulseq_analysis.sampling` | The gradient waveform of one axis at given times (section 2). |
| `pulseq_analysis.seq_utils` | The points of one gradient event, and the constant. |
| `pulseq_analysis.asc` | The optional read of a Siemens gradient `.asc` file into the hardware pair of the PNS functions. |
| `pulseq_analysis.extensions` | The refusal of the Pulseq extensions that the measurements do not support, and of a sequence with no `[SIGNATURE]` hash. |
| `pulseq_analysis.series` | `Series`, the form of a value that can go into JSON, and the encoding of an array. |
| `pulseq_analysis.analyses` | The `Analysis` protocol, the registry of the installed analyses, and the five analyses of this package. |

These rules apply to all the modules:

- **Logical axes.** The gradient and PNS values are of the logical axes of
  the file (x, y, z), not of the physical axes of a scanner. On an oblique
  slice, one physical axis can get the magnitude of the three-axis vector.
- **Rotation extension.** `gradient_peaks`, `block_gradient_values`,
  `pns_levels` and `gradient_spectrum` raise `NotImplementedError` for a file
  with the Pulseq rotation extension (`extensions.refuse_rotations`), because the gradients
  of the file are not the gradients on the scanner.
- **Signature.** A sequence must have a `[SIGNATURE]` hash. `sequence_index`
  and each measurement raise `ValueError` for a sequence with none
  (`extensions.refuse_unsigned`): `seq.signature_value` must be a `str` that
  is not `''`. A sequence that `add_block` built in memory has none, and
  `seq.write(path)` signs it. The package checks only that the hash is there:
  it does not compute it again, and pypulseq's `read` does not check it against
  the file. The hash stays on the object when the object changes (pypulseq-issues
  11), so two cases pass the check with a stale hash: a sequence changed with
  `add_block` after `read` of a signed file, and a `read` of an unsigned file
  into an object that read a signed file. Use a new `Sequence` object for each
  file.
- **Block ID and play index.** The *block ID* is the ID of pypulseq (a key of
  `seq.block_events`). The *play index* is the
  position of a block in play order, from 0. The arrays of `SequenceIndex` and
  of `BlockGradientValues` have one entry for each play index. Use
  `block_id[i]` to get the block ID of play index `i`: the IDs do not have to
  be 1, 2, 3 and so on.
- **Times.** A time is in seconds from the start of the sequence. The start of
  a block is the sum of the durations of the blocks before it, added in play
  order.
- **Gradient waveform.** Each measurement of the gradients uses the gradient
  waveform of MATLAB Pulseq ([section 2](#2-the-gradient-waveform)), not the line
  that pypulseq draws across each gap between two events.
- **Rasters.** The `rasters` of an analysis are the rasters of the file whose
  value changes the value of the analysis. `Sequence.read` makes each block
  duration from the `BlockDurationRaster`, and each analysis reads the
  durations. The block table (`seq.index`) does not use the
  `GradientRasterTime`. The gradient, PNS and spectrum measurements use both
  rasters.
- **Units.** No value uses a gamma. The gradient values are in Hz/m and
  Hz/m/s, the spectrum in Hz/m/√Hz, and the PNS values in Hz/T. Divide a value
  by |γ| to get the unit with tesla ([section 9](#9-units-and-gamma)).
- **Kept results.** Each measurement is one public function, and it keeps its
  result for the sequence object: `sequence_index`; `gradient_peaks` for
  `window=None` (a result with a window is not kept, because a caller can ask
  for many windows, but it uses the kept values of each block);
  `block_gradient_values`; `pns_levels` for each hardware, each tuple of
  thresholds and each `bin_s` of that object; and `gradient_spectrum` for each
  set of its arguments. A second call with the same arguments gives the same
  object. They build the result again after `add_block`, after a new read of a
  file into the object (`seq.read`), and after a change of
  `seq.grad_raster_time`.
  A block replaced in place is not seen: make a new sequence object for it.
  The other functions keep nothing.
- **Equality.** `SequenceIndex`, `BlockGradientValues`, `GradientPeaks`,
  `PnsLevels`, `GradientSpectrum` and `Series` compare by value: `==` compares
  each field, an array by its dtype, its shape and its values (a NaN equals a
  NaN), and a dict with its keys in order (for a `Series`, also the keys of
  `meta`). They are not hashable. The other frozen dataclasses (for example
  `AxisResult` and `PnsInterval`) have the `==` and the hash of `dataclasses`.
- **Read-only results.** A result can be shared (the kept results above), so
  the arrays of a result are read-only (a change in place raises
  `ValueError`), and the dicts of a result are `FrozenDict`s, subclasses of
  `dict` that raise `TypeError` for a change. A `FrozenDict` equals a `dict`
  with the same items in the same order, and `json.dumps`, `pickle` and
  `copy.deepcopy` take it. Make a copy (`np.array(a)`, `dict(d)`) to change one.
- **Number arguments.** A number argument (a threshold, `bin_s`, the
  arguments of the spectrum, the ends of a `window`, a coordinate of a
  `Series`) is a real number (`numbers.Real`, not a `bool`). A value of
  another type raises `TypeError`. A value that is too large, not finite or
  out of range raises `ValueError`.
- **No result.** A result without a value has the `reason`
  `seq_index.NO_GRADIENTS` ("no gradients"), or
  `seq_index.NO_GRADIENTS_IN_WINDOW` for a window of `gradient_peaks`.

## 1. `seq_index`: the block table

`sequence_index(seq) -> SequenceIndex` raises `ValueError` for a sequence with
no `[SIGNATURE]` hash (the rule of all the modules above). Then it reads
`seq.block_events` and `seq.block_durations`, with no `get_block`. It numbers
the unique events of each kind from 1, in the order of their first use: block
by block in play order, and in one block in the order gx, gy, gz. The three
gradient axes share one number space, so one event that plays on x and on y has
one number.

`SequenceIndex` is a frozen dataclass. N is the number of blocks, and K the
number of unique events of one kind. Two indexes are equal (`==`) when each
field is equal, an array by its dtype, its shape and its values: the indexes of
two reads of one file are equal. An index is not hashable (`hash(index)` raises
`TypeError`).

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

The layout of `SequenceIndex` is the contract of the analysis `seq.index`
version 1 ([section 7](#7-analyses-the-analyses-and-their-registry)): its
fields, the dense numbers from 1 in the order of first use, one number space
for the three gradient axes, and the dtype rule above. A caller that reads
the index through the registry (for example pulseq-checks) can rely on them. A
change of the layout raises `spec.version` of `seq.index`.

The arrays of a `SequenceIndex` are read-only: a change in place, such as
`index.start_s[0] = 1.0`, raises `ValueError`. All callers share the index that
`sequence_index` keeps for a sequence object, so a change would reach all of them.
Make a copy to change one: `np.array(index.start_s)`.

`has_gradients(index) -> bool` is true when the index has a gradient event on
any axis. `seq_index.NO_GRADIENTS` (`"no gradients"`) and
`seq_index.NO_GRADIENTS_IN_WINDOW` (`"no gradients in the window"`) are the
two texts of a `reason` ([section 3](#3-grad_peaks-gradient-amplitude-and-slew)
and the other results that have one).

`rf_events(seq, index)`, `grad_events(seq, index)` and `adc_events(seq, index)`
give `(number, event)` for each unique event, in the order of the numbers.
The event is the pypulseq event of the first block that uses it. They read
one block with `get_block` for each event, not for each block, with
pypulseq's block cache off. `block_cache_off(seq)` is the context manager that
they use: pypulseq keeps each block that `get_block` reads when
`seq.use_block_cache` is true, and nothing removes it.

## 2. The gradient waveform

Each measurement of the gradients uses one waveform for each axis:
`gradient_peaks`, `block_gradient_values`, `pns_levels` and
`gradient_spectrum`. It is the gradient waveform of MATLAB Pulseq
(`waveforms_and_times` in `Sequence.m`). This section gives it. The sections
of the measurements ([3](#3-grad_peaks-gradient-amplitude-and-slew),
[4](#4-pns_levels-safe-pns), [5](#5-the-other-modules) and
[8](#8-grad_spectrum-the-gradient-spectrum)) refer to it.

The waveform of one axis is a polyline. In this section, `dt` is
`seq.grad_raster_time`, the `GradientRasterTime` of the file. It is not the
raster of `seq.system`. `TIME_TOLERANCE` is 1e-9 s
(`seq_utils.TIME_TOLERANCE`).

**The events.** A gradient event gives its points at the times
`(block start + delay) + offset`, with its amplitudes
(`seq_utils.gradient_points`). A trapezoid has its corner points. An extended
trapezoid has its corner points, and an arbitrary gradient has its sample points.
Between two points of one event, the waveform is a straight line.

**The gaps.** Take two consecutive events of one axis. The blocks between them
have no event on the axis. `last_time` and `last` are the time and the value of
the last point of the earlier event. `first_time` and `first` are the time and
the value of the first point of the later event. The gap is
`first_time - last_time`.

| Gap | Rule | Waveform |
|---|---|---|
| Zero gap | The gap is at most `TIME_TOLERANCE`. | No point. When `first` is not `last`, the waveform has a step from `last` to `first` at `first_time`. The value at the time of the step is `last`. |
| Short gap | The gap is more than `TIME_TOLERANCE` and at most `dt + TIME_TOLERANCE`. | No point. The waveform is the straight line from the last point to the first point. |
| Long gap | The gap is more than `dt + TIME_TOLERANCE`. | A ramp to 0 from the last point to the time `last_time + dt / 2`, when `last` is not 0. A ramp from 0 from the time `first_time - dt / 2` to the first point, when `first` is not 0. The value is 0 between the ramps. |

A value of 1e-6 Hz/m or less also gets its ramp. MATLAB Pulseq sets such a
value to 0 and adds no ramp. The difference is at most 1e-6 Hz/m in half a
raster time.

**The ends of the axis.** The value is 0 before the first point of the axis and
after its last point. A first value that is not 0 is a step from 0 at the first
point. A last value that is not 0 is a step to 0 at the last point.

**The slew.** The slew of a segment (a segment of an event, a ramp or a line) is
its slope. The slope of a ramp is `2 * |value| / dt`. The slope of the line across
a short gap is `|first - last| / (first_time - last_time)`. A segment shorter
than `TIME_TOLERANCE` has no slope. The slew of a step is `|step| / dt`. The
scanner plays a step in one raster time, so a step is a slew like a slope.
`add_block` accepts a step up to `max_slew * grad_raster_time`. The slew of an
axis is the largest of these values.

**The credit of each item to a block.** A value, a slew and an RMS integral have
the credit of a block (a play index). The credit is:

- The points and the segments of an event: the block of the event.
- A ramp to 0: the block of the earlier event, also when the ramp is after the
  end of that block.
- A ramp from 0: the block of the later event.
- A step across a zero gap and the line across a short gap: the block of the
  later event.
- The step before the first point of the axis: the block of the first event. The
  step after the last point: the block of the last event.

The time of a segment is its start. For a segment that the edge of a range cuts,
it is the start of the cut. The time of a step is its time: `first_time` for a step
across a zero gap, and the time of the point for the step at an end of the axis.
The time of a ramp to 0 is `last_time`, the time of a ramp from 0 is
`first_time - dt / 2` and the time of a line is `last_time`. When several items
have the largest value, the first of them in play order gets the credit. The step
or the line into an event is before the segments of that event.

**A range.** A range is `[lo, hi]` (the whole file, or a window of
`gradient_peaks`). A segment that crosses an edge of the range is cut at the
edge. The value at the edge is found by linear interpolation. A step is in the
range when `lo <= t < hi`. So a step at the start of a window is in it, and a
step at the end of a window is not. The step after the last point of the axis is
at the time of that point. When that point is at the end of the sequence, no range
has the step: the whole file does not have it.

**The RMS.** The RMS integral is the integral of the square of the polyline,
with the ramps and the lines. A step adds nothing.

**The vector peak.** The vector peak is the largest `sqrt(gx^2 + gy^2 + gz^2)` at
the union of the times of the points of the three axes. The ramp points are
points. At a time, the value is found on both sides of the time, so a step has
two values. The credit goes by the time, not by the axis. The value before the
time goes to the first block that ends at or after the time. The value after
the time goes to the last block that starts at or before the time. Each is
within `TIME_TOLERANCE`. Of equal values, the earliest time wins.

**The difference from pypulseq.** pypulseq's `Sequence.waveforms()` joins the
points of the events of an axis and does nothing at a gap. `get_gradients()`,
`calculate_pns` and `calculate_gradient_spectrum` use these points. So pypulseq
draws a straight line across each gap, also across a long gap. At a zero gap it
drops the first point of the later event, so it has no step. pypulseq-issues 12
describes the difference. The two waveforms are equal when the file has no end
that is not 0 next to a long gap, and no step at a block junction. A sequence
that `add_block` accepts can have both: it refuses an end that is not 0 and
a step only above `max_slew * grad_raster_time`.

## 3. `grad_peaks`: gradient amplitude and slew

The gradient of each logical axis is the waveform of MATLAB Pulseq
([section 2](#2-the-gradient-waveform)). The values of this section are the
largest values of that waveform, over the whole file, over a window, or for
each block:

- The peak is the largest absolute amplitude.
- The slew is the largest of the slopes of the segments (of the events, the
  ramps and the lines) and of the steps. The slew of a step is `|step|` divided
  by the gradient raster of the file (`seq.grad_raster_time`).
- The RMS is the root of the mean of the square of the waveform over the range.
- The vector peak is the largest magnitude of the three-axis vector.

An axis with no event in a block has the amplitude 0 there.

When several blocks have the largest value, the first of them in play order gets
the credit. The step or the line into the event of a block comes before the
segments of the event. A largest value of 0 gives no block (`None`) and the time
0.0. [Section 2](#2-the-gradient-waveform) gives the credit of each item to a
block, the time of each value, and the rule for a step at the edge of a window.

`gradient_peaks(seq, *, window=None) -> GradientPeaks` gives the largest
values over the whole file, or over `window = (start_s, end_s)`. A window must
be a tuple or a list of two real numbers (an `int`, a `float` or a numpy real
scalar; not a `bool`), in the sequence (each end within
`seq_utils.TIME_TOLERANCE`), and have `start_s < end_s`. The function raises
`TypeError` for a window that is not a pair, and for a start or an end that is
a `bool` or not a real number. It raises `ValueError` for a start or an end
that is NaN or an infinity (the message says "finite"), for a window with no
start before its end, and for a window that is not in the sequence. The
function checks the form and the numbers of the window before it reads the
sequence. A segment that crosses an end of the window is cut there, and a step
is in the window when `start_s <= t < end_s`
([section 2](#2-the-gradient-waveform)). `range_s` is
the window with each end clipped to `(0.0, end_s)` of the sequence, so its
start is never after its end. A window that is past an end of the sequence by
less than `seq_utils.TIME_TOLERANCE` has the range `(end_s, end_s)` (or
`(0.0, 0.0)`), of length 0, with the `reason`
`seq_index.NO_GRADIENTS_IN_WINDOW` and the zero values. The values are in Hz/m and
Hz/m/s, the units of pypulseq, with no gamma. To get T/m and T/m/s, divide
them by |γ| ([section 9](#9-units-and-gamma)). The function does not compare the values
with limits: a caller that has the limits of a scanner compares them.

`gradient_peaks(seq)` (`window=None`) keeps its result for the sequence object,
by the rule "Kept results" at the top of this document: a second call gives the
same object, and `add_block`, a new read of a file into the object and a change
of `seq.grad_raster_time` give a new one. A result with a window is a new
object for each call and is not kept, because a caller can ask for many
windows. A call with a window uses the values of each block that the object
keeps (the peak, the slew, the junction, the RMS integral and the vector peak,
with their times) for the blocks that are whole in the window. It makes the
blocks that an edge of the window cuts from the exact waveform. A ramp can be up
to half a raster time outside the block of its event, so a block that is near an
edge is one of them. A window reads no block with `get_block`. Its cost is the
number of blocks in the window plus a constant. It has no term for the number of
blocks of the file or for the number of unique gradient events. On one machine, for
a sequence of 20,000 blocks, a window inside one block takes about 0.4 ms, and a
window of 1500 blocks takes about 0.8 ms. The first call for a sequence also
makes the values of all its blocks, in time that is proportional to the number of
blocks (about 20 ms for 20,000 blocks).

`GradientPeaks`, a frozen dataclass:

| Field | Meaning |
|---|---|
| `reason` | `None` when the range has a part of a gradient event, or a ramp, a line or a step with a value that is not 0. Otherwise `seq_index.NO_GRADIENTS` (no window) or `seq_index.NO_GRADIENTS_IN_WINDOW` (with a window), each number is 0.0 and each block is `None`. |
| `range_s` | The range of the measurement: `(0.0, end_s)`, or the window. |
| `axes` | A read-only dict (`_equality.FrozenDict`) from `"x"`, `"y"` and `"z"` to an `AxisResult`. |
| `vector_peak_hz_per_m` | The largest magnitude of the three-axis vector in the range (Hz/m). |
| `vector_peak_time_s`, `vector_peak_block` | The first time with that magnitude, and the block ID of the block that has that time, seen from the side where the value is ([section 2](#2-the-gradient-waveform)). |

A `FrozenDict` is a `dict` (`isinstance(x, dict)`, `json.dumps` and `pickle`
work) whose methods that change it raise `TypeError`. A result is shared by all
its callers, so a change of a dict would change it for all of them. Two
`GradientPeaks` are equal (`==`) when each field is equal, a dict with its keys
in order. A `GradientPeaks` is not hashable.

`AxisResult`, a frozen dataclass, for one axis:

| Field | Meaning |
|---|---|
| `peak_hz_per_m` | The largest absolute amplitude in the range (Hz/m). |
| `peak_time_s`, `peak_block` | The first time with it, and the block ID. |
| `max_slew_hz_per_m_per_s` | The largest slew in the range (the slope of a segment, or a step), in Hz/m/s. |
| `slew_time_s`, `slew_block` | The time is the start of that segment (the start of the range when the range cuts the segment), or the time of that step. The block is the block ID of its credit: the block of the event of the segment. For a step, a line and a ramp from 0 it is the later block. For a ramp to 0 it is the earlier block. For the step after the last point of the axis it is the block of the last event ([section 2](#2-the-gradient-waveform)). |
| `rms_hz_per_m` | The RMS amplitude over the range (Hz/m). |

`block_gradient_values(seq) -> BlockGradientValues` gives the same values for
each block, not only the largest, in the same units. The largest of each
amplitude array is the value of `gradient_peaks` for the whole file. Its slew
is the larger of the largest segment slew and the largest junction. The
first play index of a largest value is the block of that value. For the vector
peak, it is the block with the earliest `vector_peak_time_s` of the blocks that
have the largest value. It keeps its
result for the sequence object, as `gradient_peaks(seq)` does. It reads one
block with `get_block` for each unique gradient event, and no other block.
`gradient_peaks` does the same, and a window of `gradient_peaks` reads no
block with `get_block`.

`BlockGradientValues`, a frozen dataclass. Each array has N entries, in play
order. A dict has the keys `"x"`, `"y"` and `"z"`, each with an array. Each of
the five dicts is a read-only `FrozenDict`, and each array is read-only and its
own array (not a view of the index): `values.start_s[0] = 1.0` raises
`ValueError`, and `values.peak_hz_per_m["x"] = ...` raises `TypeError`. Make a
copy to change an array: `np.array(values.start_s)`. Two results are equal
(`==`) when each field is equal, as for `SequenceIndex`; a result is not
hashable.

| Field | Meaning |
|---|---|
| `block_id`, `start_s` | int64 and float64: the block ID and the start of each block. |
| `peak_hz_per_m`, `peak_time_s` | Dicts: the largest absolute amplitude of the event of the block on the axis (Hz/m), and its time. |
| `slew_hz_per_m_per_s`, `slew_time_s` | Dicts: the largest slope of a segment of the event of the block or of its ramps (Hz/m/s), and the start of that segment. The ramp to 0 after the event and the ramp from 0 before it are in the slew of this block. So is the step after the last point of the axis, in the block of the last event, when that point is before the end of the sequence. |
| `junction_hz_per_m_per_s` | Dict: the step into the event of the block across a zero gap, `\|last - first\|` divided by `seq.grad_raster_time`, or the slope of the line into it across a short gap, `\|last - first\|` divided by the gap (Hz/m/s). It is 0 for a long gap, and for a block with no event on the axis. For the first event of the axis it is the step from 0. Its time is the time of the first point of the event for a step, and the time of the last point of the earlier event for a line. There is no field for it. |
| `vector_peak_hz_per_m`, `vector_peak_time_s` | The largest magnitude of the three-axis vector that the block has (Hz/m), and its first time. |

A block with no event on an axis has the peak, the slope and the junction 0
there, at the time `start_s`. The largest of the slew array and of the junction
array is the slew of the whole file. The vector peak of a block goes by time
([section 2](#2-the-gradient-waveform)), so a block with no event can have a
vector peak that is not 0: the value of a ramp or a line at its start or its end.

## 4. `pns_levels`: SAFE PNS

`pns_levels.pns_levels(seq, *, hardware, thresholds_hz_per_t=(), bin_s=BIN_S) -> PnsLevels`
runs the SAFE model of the pinned pypulseq fork on the gradients of `seq`, and
keeps the result for the sequence object, the hardware, the thresholds and the
bin size. It is the one entry point of the SAFE model: there is no module `pns`
and no second function, and a second call with the same arguments gives the
kept object. The
hardware is necessary: `hardware` is a required keyword argument. It is the
vendor-neutral pair `(struct, label)`: a SAFE hardware struct in the form of
pypulseq's `asc_to_hw`, and a name for it. The package does not take a file
path here. `asc.hardware_from_asc(path)` makes the pair from a Siemens gradient
`.asc` file ([section 5](#5-the-other-modules)).

A call without `hardware` raises Python's own `TypeError`. A value that is not
a tuple of two items with a `str` second item raises `TypeError` with a message
that says how to make a hardware. The struct is checked too. A struct with no
`x`, `y` or `z`, or an axis with no field of `pns_levels.SAFE_FIELDS`
(`stim_thresh` too), raises `ValueError` that names it, for example `'x.stim_thresh'
missing in the hardware struct`. Each field is a finite real number: a value
that is not a real number raises `TypeError`, and one that is not finite raises
`ValueError`. `stim_limit` must be above 0, and `a1 + a2 + a3` of each axis must
be within 0.001 of 1 (the rule of pypulseq's `safe_hw_check`), or `ValueError`.
Each of these is raised before the sequence is read, also for a sequence with no
gradient event, and `pns_levels` raises it before it reads the kept
results. There is no default hardware. For pypulseq's
example hardware, which is not a real scanner, make the pair with
`safe_example_hw()` (in `pypulseq.utils.safe_pns_prediction`):
`hardware=(safe_example_hw(), "a label")`. `thresholds_hz_per_t` is a tuple of the
totals, in Hz/T, whose runs `PnsLevels.above` gives. It can be empty. Each
element is a finite real number above 0 (an `int`, a `float`, a `Fraction` or
a numpy real scalar; not a `bool`), and no two are equal as floats. A value
that is not a tuple, and an element that is a `bool` or not a real number,
raise `TypeError`. An element that is not finite, not above 0 or too large for
a float, and two elements that are equal as floats, raise `ValueError`. Both
are raised before the sequence is read. The default is `()`: `above` is `{}`. For a fraction f of the stimulation limit, give
`f * abs(gamma)` ([section 9](#9-units-and-gamma)). The same thresholds in
another order are another kept result, because the order of `above` is the
order of `thresholds_hz_per_t`.

`bin_s` is the length of a bin of the level, in seconds. The default,
`pns_levels.BIN_S`, is 5 ms (500 samples at the 10 µs raster).
`bin_samples_for(num_samples, dt, bin_s)` gives its whole number of samples.
When `bin_s / dt` is within `ON_RASTER_TOLERANCE` (1e-6) of a whole number, that
is the number, so `bin_s=0.01` gives 1000 samples at the 10 µs raster. Else it
is the number rounded down: `bin_s=10.0 / 1624` (the default of 0.1.0rc5) gives
615 samples. The bin has at least one sample, so a `bin_s` shorter than `dt`
gives bins of one sample. When the level would have more than
`pns_levels.MAX_BINS` (2,000,000) bins, the bins are longer, so that the level
has at most that many. `bin_s` is a finite `int` or `float` above 0 (any real
number, not a `bool`). A `bool` or a value that is not a real number raises
`TypeError`, and a value that is not finite, not above 0 or too large for a
float raises `ValueError`, both before the sequence is read. Only the level depends on
`bin_s`: the summary and the intervals do not. A different `bin_s` is another
kept result, also when it gives the same `bin_samples`. The bin of a result is
`bin_samples * dt_s`.

The stimulation limit is the fraction 1. In Hz/T, the limit is `abs(gamma)`.

The model runs on the Hz/m samples of the gradients, and reads no gamma. A PNS
value is in Hz/T: the fraction of the stimulation limit times |γ|. pypulseq's
`seq.calculate_pns` divides by `seq.system.gamma`, so it gives fractions.

The model takes one sample of each axis for each gradient raster time
`dt = seq.grad_raster_time`. Sample `k` is at the time `(k + 0.5) * dt`. The
value of a sample is the gradient waveform of MATLAB Pulseq at that time
([section 2](#2-the-gradient-waveform)): a line across a gap of one raster time
or less, a ramp to 0 and a ramp from 0 across a longer gap, and a step at a block
junction. The samples of a block start at the start of that block, so a block
gives the same samples wherever it is in the sequence. Only the samples in a gap
use the sum of the durations of the blocks before them. When every event is on the
edges of the gradient raster, a ramp of half a raster time ends at a time of a
sample, where it is 0. So on the raster, a long gap changes no sample, and a short
gap gives its samples the value of the line. The value of an axis is the output
of the model for that axis, and the total of a sample is `sqrt(x^2 + y^2 + z^2)`
of the three values.

pypulseq's `seq.calculate_pns` samples a line across each gap
([section 2](#2-the-gradient-waveform)). `pns_levels` equals it, times |γ|, for a
sequence with no end that is not 0 next to a gap of more than one raster time and
no step at a block junction. For another sequence, it gives other values. They
are the SAFE model of the pinned fork on the samples of the waveform of section 2.

`PnsLevels`, a frozen dataclass:

| Field | Meaning |
|---|---|
| `reason` | `pns_levels.NO_GRADIENTS` (the object `seq_index.NO_GRADIENTS`) when the sequence has no gradient event, or `None`. With `NO_GRADIENTS`, the peaks are 0, `peak_time_s` is `None` and there are no bins and no intervals. |
| `hardware` | The label of the `hardware` pair. |
| `hw` | The SAFE parameters of each axis that the model used (a read-only dict from `"x"`, `"y"` and `"z"` to a read-only dict). |
| `dt_s`, `num_samples` | The time step and the number of samples. |
| `peak_hz_per_t` | The largest total, in Hz/T. The limit is `abs(gamma)`. |
| `peak_time_s` | The time of the first sample whose total is within `pns_levels.PEAK_TOLERANCE` (a fraction) of the peak. `None` when the peak is 0: with `NO_GRADIENTS`, and for gradients that all have the amplitude 0 (then the model does not run a second time to find the time). |
| `axis_peaks_hz_per_t` | A read-only dict from each axis to its largest value, in Hz/T. |
| `above` | A read-only dict from each threshold (`float(t)`, in the order of `thresholds_hz_per_t`) to a tuple of `PnsInterval`, in time order: each run of consecutive samples whose float64 total is at or above that threshold. A tuple is empty when `peak_hz_per_t` is below its threshold, and otherwise its largest `PnsInterval.peak_hz_per_t` is `peak_hz_per_t`. All thresholds are found in one pass. Without thresholds, `above` is `{}`. |
| `bin_samples`, `level_min_hz_per_t`, `level_max_hz_per_t` | The level, for a plot: read-only float32 arrays with the minimum and the maximum total of each bin of `bin_samples` samples (the last bin can have fewer), in Hz/T. Each total of a bin is in `[level_min_hz_per_t, level_max_hz_per_t]` of the bin. |
| `on_raster` | `True` when the duration of each block is a whole number of samples. Otherwise the samples come from the waveform of the whole file at the same times (`GradientSampler.sample`). |

All the callers of `pns_levels` with the same sequence object, hardware,
thresholds and `bin_s` share the kept result. For this reason, `level_min_hz_per_t`
and `level_max_hz_per_t` are read-only, also for `NO_GRADIENTS` and also in
the kept result: a change in place raises `ValueError`. Convert to a
new array:

```python
from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")
levels = pns_levels(seq, hardware=hardware)
level_max_percent = levels.level_max_hz_per_t / abs(gamma) * 100  # a new array
```

The dicts `hw` (the outer dict and each inner dict), `axis_peaks_hz_per_t` and
`above` are `_equality.FrozenDict`s: read-only subclasses of `dict`. A change
(`d[key] = x`, `del d[key]`, `update`, `pop` and the like) raises `TypeError`.
They are still `dict`s for `isinstance`, `json.dumps`, `pickle` and
`copy.deepcopy`, and a `FrozenDict` equals a `dict` with the same items. To
change one, make a plain dict: `dict(levels.hw)`.

`==` compares two `PnsLevels` by the values of their fields: the arrays by
dtype, shape and values, and the dicts with their keys in order. Thus the same
thresholds in another order give a result that is not equal. The read-only
flag does not count, so a copy from `pickle` or `copy.deepcopy` equals the
original. A `PnsLevels` is not hashable.

`PnsInterval`, a frozen dataclass: `start_s` and `end_s` (the edges of the
samples of the run, `first * dt` and `(last + 1) * dt`, so a run of one sample
has `end_s - start_s == dt`), `peak_hz_per_t` (the largest total, in Hz/T),
`peak_time_s` (the first sample with it) and `num_samples`.

`pns_levels.SAFE_FIELDS` is the nine fields of each axis of a SAFE hardware
struct, in the order of `safe_example_hw` and `asc_to_hw`. pulseq-checks makes
the `hardware` argument from a target profile (see the `docs/usage.md` of
pulseq-checks).

## 5. The other modules

`sampling.gradient_sampler(seq)` gives a `GradientSampler`. The sampler gives
the gradient waveform of one axis (`"gx"`, `"gy"` or `"gz"`), in Hz/m. It is the
waveform of MATLAB Pulseq ([section 2](#2-the-gradient-waveform)).
`gradient_sampler` raises `NotImplementedError` for a sequence with the Pulseq
rotation extension (`extensions.refuse_rotations`). The sampler does not copy
the points of the unique gradient events. They are read one time for each
sequence object and kept (the rule of the kept results above), with the
sequence index. The sampler finds the gaps of each axis one time for each
sequence, and keeps them with the points. The sampler itself is not kept.

- `sample(axis, t)`: the values at the sorted times `t`. They are the straight
  lines between the points of all the events of the axis, with the ramps to 0
  and from 0 across a long gap, and 0 before the first point and after the last
  point. The value at the time of a step is the value before the step. This is
  not the waveform of pypulseq's `Sequence.get_gradients()`, which draws a line
  across each gap and has no step at a zero gap. A call costs the number of
  samples and of blocks in its range.
- `block_samples(axis, first, stop, dt, *, skip=0, count=None)`: the samples
  of the play indexes `first` to `stop - 1`, each block on its own at the times
  `(j + 0.5) * dt` from its start, with the values of its own event and 0
  outside it. A sample in a gap has the value of the waveform there: the line
  across a short gap, or the ramp of a long gap. This holds in any block, also
  in a block with no event on the axis. The time of a sample in a gap is
  `start + (j + 0.5) * dt`, with `start` the sum of the durations of the blocks
  before the block, so it has the float drift of that sum. The own-event samples
  have none. This is what the PNS model uses. `skip` and `count` (0 or more)
  choose a part of that range: the result is, bit for bit, the samples `skip`
  to `skip + count - 1` of the result for the default arguments, and
  `count=None` gives all the samples after `skip`. The first and the last
  block give only their samples inside the part, so the cost and the memory do
  not grow with the length of a block that the part cuts. It raises
  `ValueError` when a block of the range is not a whole number of samples
  long, or when `skip` or `count` is negative or `skip + count` is more than
  the samples of the range.

`sampling.raster_block_lengths(index, dt)` gives the number of samples of each
block, `round(duration / dt)`, and one bool for all the blocks: whether every
block is within `sampling.ON_RASTER_TOLERANCE` samples of a whole number.

`sampling.sequence_samples(index, dt)` gives the number of samples of the whole
sequence, as an `int`. This is the one rule of the package: `pns_levels` and
`grad_spectrum` call it. When every block is on the raster, it is the sum of the
block lengths. Otherwise it is `ceil((index.end_s - 1e-10) / dt)`, and at least 0.

`seq_utils`:

| Name | Meaning |
|---|---|
| `gradient_offsets(g)` | The delay, and the times after the delay and the amplitudes (Hz/m) of the points of the gradient event `g`. |
| `gradient_points(g, t0)` | The times (`t0` + delay + offset) and the amplitudes of the points of `g`. |
| `TIME_TOLERANCE` | 1e-9 s. A segment shorter than this has no slope, and a gap of this length or less is a zero gap ([section 2](#2-the-gradient-waveform)). |

`asc.hardware_from_asc(path)` makes the `hardware` pair of the PNS functions
from a Siemens gradient `.asc` file (`MP_GPA_*.asc` or `MP_GradSys_*.asc`):
`(asc_to_hw(asc), hardware_name(asc))`. It is the optional reader of a vendor
file; the PNS functions take only the pair. Two parts of it are public.
`asc.read_gradient_asc(path)` gives the fields of the file, with the fields of
each file that an `$INCLUDE` line names. A `$INCLUDE` cycle (a file that
includes itself, or two files that include each other) raises `ValueError` that
names the files. A file that two branches include is not a cycle.
`asc.hardware_name(asc)` gives the name
of the component in those fields. Two pairs of one file, whatever the spelling
of its path, have the same label and values, so `pns_levels` keeps one
result for them.

`extensions.refuse_rotations(seq)` raises `NotImplementedError` when `seq`
uses the Pulseq rotation extension. A function that measures the gradients of
the file calls it first.

## 6. `series`: values for JSON

A `Series` is the part of an analysis value that can go into JSON
(`Analysis.to_series`, [section 7](#7-analyses-the-analyses-and-their-registry)).
It is a frozen dataclass:

| Field | Meaning |
|---|---|
| `name` | A short, stable name, not empty, for example `"pns_total"`. |
| `kind` | A `SeriesKind` (below). |
| `unit` | The unit of the values, for example `"Hz/T"`, `"Hz/m"` or `"s"`. |
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
spectrum series ([section 7](#7-analyses-the-analyses-and-their-registry)).
The other rows are examples.

`coord_unit` uses the SI symbol. No code checks it against a list of units.
A series has one coordinate, so it cannot hold a map on two coordinates. The
unit gives the quantity of the coordinate (`"s"` is the time, `"Hz"` is the
frequency, `"m"` is a position). When the unit does not give all of it, for
example which position, the analysis puts it in `meta`.

`coord_start`, `coord_step` and `coord_end` are checked with `_validate.real`:
a `bool` or a value that is not a `numbers.Real` is a `TypeError` (an `int`, a
`float`, a `fractions.Fraction` and a numpy real scalar are valid), and an
`int` too large for a `float` is a `ValueError`. Each is a `float` after the
check.

The coordinates must be finite and in order, else `ValueError`:

- `coord_step` is finite and above 0.
- `coord_start` is finite for `SAMPLES` and `ENVELOPE`. (`POINTS` and `RUNS`
  need 0.0.)
- For an `ENVELOPE` of `n` bins, `coord_end` is finite and
  `coord_start + (n - 1) * coord_step < coord_end <= coord_start + n * coord_step`.
  So the last bin is not empty, and it is not longer than a step. A
  `coord_end` within `1e-9 * coord_step` of a limit counts as equal to the
  limit, because a `coord_end` that is a product of floats has a rounding
  error. So it must be above the lower limit by more than the tolerance, and it
  can be above the upper limit by the tolerance. (`pns_total` has `coord_end`
  `num_samples * dt_s` and `coord_step` `bin_samples * dt_s`.) With no bin
  (`n` is 0), `coord_end >= coord_start`, with no tolerance.
- For `RUNS`, `start` and `end` have an integer or float dtype (not bool or
  complex), every value is finite, and `end[k] >= start[k]` for each run. A run
  with `end == start` is valid.

`coord` of `POINTS` and the other arrays are not checked: a value that is not
finite is valid there. A float in `meta` can be not finite too.

A `Series` raises `TypeError` for a value of a wrong type and `ValueError` for
a wrong value. It keeps its own `FrozenDict`s for `arrays` and `meta`, and a read-only copy of
each array, in native byte order. A change to the caller's dicts or arrays does
not change it, and a change to `arrays` or `meta` of the series raises
`TypeError`. `==` compares the fields, the array names in their order, and each array
with its dtype and `np.array_equal(..., equal_nan=True)`. A NaN equals a NaN.
The keys of `meta` count in their order, as for each other dict of the
package, and `to_obj` and `from_obj` keep that order. A `Series` is not
hashable.

`Series.to_obj()` gives a dict with the keys `name`, `kind`, `unit`,
`coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta` and `arrays`,
which `json.dumps(obj, allow_nan=False)` writes. A float of `meta` that is not
finite is the string `"inf"`, `"-inf"` or `"nan"`. `Series.from_obj(obj)` is
the inverse, and raises `ValueError` for a bad object, also for a coordinate
field that is not finite or not in order.

`encode_array(a)` gives an array as `{"dtype", "length", "data"}`: the numpy
dtype name, the number of elements, and the little-endian bytes of the array,
gzipped (level 6, no time stamp, OS byte 255) and base64-encoded. This is the
text of `encode_tables` of pulseq-reports, so a report puts it into its page
with no new encoding. One array always gives the same text. A float that is
not finite is in the bytes. `decode_array(d)` is the inverse, and raises
`ValueError` when `"length"` does not agree with the data.

## 7. `analyses`: the analyses and their registry

An *analysis* calculates information about a sequence and does not change it.
It has:

- `spec`, an `AnalysisSpec` (a frozen dataclass): `id`, `version`, `title`,
  `description` (the contract of the value), `params` (the names of all the
  keyword arguments of `compute`), `necessary` (the names of `params` that
  have no default), `defaults` (a pair `(name, default)` for each other name of
  `params`, in the order of `params`), `rasters` (the rasters of the file
  whose value changes the value of the analysis), `cost` (`"fast"` or
  `"slow"`) and `series` (what `to_series` gives, or `None`).
- `compute(seq, **params)`: the full Python value. The parameters are
  keyword-only. A runner gives the necessary parameters (`spec.necessary`) and
  can leave out the others, which then have the values of `spec.defaults`.
- `to_series(value)`: a tuple of `Series`, the part of the value that can go
  into JSON. An analysis with nothing for JSON gives `()`.

Each name of `params` is in `necessary` or in `defaults`, and not in both. A
default is `None`, a `bool`, an `int`, a `float`, a `str` or a tuple of these
(recursively), so `AnalysisSpec` stays hashable. `AnalysisSpec(...)` raises
`ValueError` for a `necessary` name that is not in `params`, a name that has
both a default and a place in `necessary`, a name of `params` with neither, a
default for a name that is not in `params` or is repeated, defaults not in
the order of `params`, and a default of another kind. The signature of
`compute` agrees with the spec (a test checks it): the names of `params` are
its keyword-only parameters in the same order, the names of `necessary` have no
default, and each default of `defaults` is the default of the signature.

A package gives its analyses as entry points of the group
`pulseq_analysis.analyses` (`analyses.GROUP`). The name of an entry point is
the ID, and its object is the analysis. `analyses.registry()` gives a dict
from each installed ID to its analysis. Two analyses with one ID, an entry
point that cannot load, an object with no `spec.id`, and an entry point whose
name is not the `spec.id` of its object raise `analyses.RegistryError`, with
the names of the packages (and, for the name that is not the `spec.id`, the
name of the entry point and the `spec.id`).

The analyses of this package (each `version` is 1). Each `compute` gives the
result that its function keeps for the sequence object (the rule "Kept results"
at the top of this document), so a second call for one sequence gives the same
object:

| ID | Object | `compute` | `necessary` | `defaults` | `cost` | `to_series` |
|---|---|---|---|---|---|---|
| `seq.index` | `SEQ_INDEX` | `sequence_index(seq)` | none | none | fast | `()` |
| `gradient.peaks` | `GRADIENT_PEAKS` | `gradient_peaks(seq, window=window)` | none | `window=None` | fast | `()` |
| `gradient.blocks` | `GRADIENT_BLOCKS` | `block_gradient_values(seq)` | none | none | fast | `()` |
| `pns.safe.levels` | `PNS_SAFE_LEVELS` | `pns_levels(seq, hardware=hardware, thresholds_hz_per_t=thresholds_hz_per_t, bin_s=bin_s)` | `hardware` | `thresholds_hz_per_t=()`, `bin_s=pns_levels.BIN_S` | slow | below |
| `gradient.spectrum` | `GRADIENT_SPECTRUM` | `gradient_spectrum(seq, max_frequency_hz=..., window_s=..., frequency_oversampling=...)` | none | the three defaults of `grad_spectrum` | slow | below |

`spec.params` is `necessary` and the names of `defaults`, in the order of the
signature of `compute`: `hardware`, `thresholds_hz_per_t`, `bin_s` for
`pns.safe.levels`; `window` for `gradient.peaks`; `max_frequency_hz`,
`window_s`, `frequency_oversampling` for `gradient.spectrum`; none for the
other two.

`hardware` has no default, `thresholds_hz_per_t` has the default `()`, and `bin_s` has
the default `pns_levels.BIN_S` ([section 4](#4-pns_levels-safe-pns)).
`compute` without `hardware` raises `TypeError`, before the sequence is read.
No analysis has a gamma. `seq.index` has the rasters `("BlockDurationRaster",)`.
The four other analyses have the rasters
`("GradientRasterTime", "BlockDurationRaster")`.

`gradient.peaks` with `window=None` (the default) gives the kept result of the
whole sequence. With `window=(start_s, end_s)` it gives the values of that
range, as `gradient_peaks(seq, window=window)` does ([section
3](#3-grad_peaks-gradient-amplitude-and-slew)), and the result is not kept.
`seq.index` has the layout of the contract of version 1 ([section
1](#1-seq_index-the-block-table)): a change of it raises its `spec.version`.

`to_series` of `pns.safe.levels` gives `()` for a sequence with no gradient
event (`reason == NO_GRADIENTS`, the constant of `seq_index`). Else it gives:

| Name | Kind | Unit | `coord_unit` | Arrays | `meta` |
|---|---|---|---|---|---|
| `pns_total` | `ENVELOPE` | `"Hz/T"` | `"s"` | `min`, `max`: `level_min_hz_per_t` and `level_max_hz_per_t` (float32) | `hardware`, `dt_s`, `bin_samples`, `num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y`, `axis_peaks_z` |
| `pns_above_<k>`, one for each threshold, `k` from 0 in the order of `above` | `RUNS` | `"Hz/T"` | `"s"` | `start`, `end`, `num_samples` (int64), `peak`, `peak_time_s` (float64): one entry for each `PnsInterval` | `threshold` |

`<k>` is the position of the threshold in `thresholds_hz_per_t`, from 0. The
names are `pns_above_0`, `pns_above_1` and so on, in the order of the
thresholds. The value of the threshold, in Hz/T, is `meta["threshold"]`. No
two names are equal, so `to_series` has no `ValueError` for the names. With no
thresholds, `to_series` gives only `pns_total`. The arrays and the `meta` keys
keep their names. `meta["peak"]`, `meta["axis_peaks_<axis>"]`, the array
`peak` and `meta["threshold"]` are in Hz/T, the `unit` of the series.

In `pns_total`, `coord_start` is 0, `coord_step` is `bin_samples * dt_s` and
`coord_end` is `num_samples * dt_s`. The sample with the index `j` is at
`(j + 0.5) * dt_s`. `start` and `end` of a run are the edges of its samples,
`first * dt_s` and `(last + 1) * dt_s`, and `peak_time_s` is the time of a
sample.
`peak_time_s` and the `meta` keys `dt_s` and `peak_time_s` are times in
seconds.

`gradient.spectrum` has the three arguments of `gradient_spectrum`
([section 8](#8-grad_spectrum-the-gradient-spectrum)), each with its default
(`MAX_FREQUENCY_HZ`, `FFT_WINDOW_S` and `FREQUENCY_OVERSAMPLING` of
`grad_spectrum`, the defaults of pypulseq). Its result is kept for each tuple of
the three values.

`to_series` of `gradient.spectrum` gives `()` for a sequence with no gradient
event (`reason == NO_GRADIENTS`, the constant of `seq_index`). Else it gives one
series:

| Name | Kind | Unit | `coord_unit` | Arrays | `meta` |
|---|---|---|---|---|---|
| `gradient_spectrum` | `SAMPLES` | `"Hz/m/sqrt(Hz)"` | `"Hz"` | `value` (`rss`), `x`, `y`, `z`, in this order (float64) | `max_frequency_hz`, `window_s`, `frequency_oversampling` |

`coord_start` is 0.0 and `coord_step` is `frequency_hz[1]`, so
`coord_start + k * coord_step` is `frequency_hz[k]`. The `meta` values are
those of the call.

To use an analysis by its ID:

```python
from pulseq_analysis.analyses import registry
from pulseq_analysis.asc import hardware_from_asc

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

analysis = registry()["pns.safe.levels"]
levels = analysis.compute(
    seq,
    hardware=hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc"),
    thresholds_hz_per_t=(abs(gamma), 0.8 * abs(gamma)),
)
series = analysis.to_series(levels)
```

## 8. `grad_spectrum`: the gradient spectrum

The gradient spectrum shows which frequencies the gradient waveform has. The
waveform is that of MATLAB Pulseq ([section 2](#2-the-gradient-waveform)),
sampled with `GradientSampler.sample`. The method is that of pypulseq's
`calculate_gradient_spectrum`:

- Each window is a 50 ms Hann window, and the windows overlap by 50 %. The
  mean of each window is removed. The spectrum of a window is the magnitude
  of its FFT, scaled as an amplitude spectral density: thus the unit has
  √Hz.
- The gradients are sampled to the end of the sequence (`sampling.sequence_samples`
  gives the number of samples). The sampled waveform has half a window of zeros at the
  start. At the end it has half a window or more: the fewest zeros that make the
  padded waveform one window plus a whole number of hops long. (A hop is the step
  between two windows, 25 ms by default.) Thus each sample, the last one too, is
  within half a hop of the centre of some window, and a gradient at the end of the
  sequence is attenuated by the window no more than one in the middle.
- In each window, the three axes combine as the RSS (the root of the sum of
  squares). The spectrum of an axis is its maximum over the windows. The RSS
  spectrum is the maximum over the windows of the RSS.
- The windows go through the FFT in chunks, so the memory does not grow with
  the length of the sequence.

`calculate_gradient_spectrum` takes its waveform from `get_gradients()`. So the
two spectra differ for a sequence with an end that is not 0 next to a gap of
more than one raster time, or with a step at a block junction (pypulseq-issues
12). For other sequences, the waveforms are equal.

`GradientSpectrum` is a frozen dataclass. F is the number of frequencies.

| Field | Meaning |
|---|---|
| `reason` | `grad_spectrum.NO_GRADIENTS` (the object `seq_index.NO_GRADIENTS`) when the sequence has no gradient event, or `None`. With `NO_GRADIENTS`, `frequency_hz` and `rss` are empty, and `axes` has the keys `"x"`, `"y"` and `"z"`, each an empty float64 array. |
| `frequency_hz` | float64, F: the frequencies, from 0 to the highest frequency. |
| `axes` | A read-only dict (`_equality.FrozenDict`, a subclass of `dict`) from `"x"`, `"y"` and `"z"` to a float64 array of F values in Hz/m/√Hz. For `NO_GRADIENTS`, each array is empty and read-only. |
| `rss` | float64, F: the RSS of the three axes, in Hz/m/√Hz. |
| `max_frequency_hz`, `window_s`, `frequency_oversampling` | The arguments of the call, as floats. The series of `gradient.spectrum` gives them in its `meta`. |

`gradient_spectrum(seq, *, max_frequency_hz=MAX_FREQUENCY_HZ,
window_s=FFT_WINDOW_S, frequency_oversampling=FREQUENCY_OVERSAMPLING) ->
GradientSpectrum` measures the whole sequence, and keeps its result (below).

| Argument | Default | Argument of pypulseq | Meaning |
|---|---|---|---|
| `max_frequency_hz` | `MAX_FREQUENCY_HZ` (2000.0) | `max_frequency` | The highest frequency of the result. |
| `window_s` | `FFT_WINDOW_S` (0.05) | `window_width` | The length of a Hann window. |
| `frequency_oversampling` | `FREQUENCY_OVERSAMPLING` (3.0) | `frequency_oversampling` | The length of the FFT is `round(frequency_oversampling * nwin)`, where `nwin = round(window_s / dt)` is the number of samples of a window. |

The three arguments are keyword-only. A value that the function refuses
raises `ValueError`, or `TypeError` for a value that is not a real number (an
`int`, a `float`, a `Fraction` or a numpy real scalar are valid) or is a
`bool`. The function raises before it reads the blocks and before it looks up
the kept result. The rules:

- Each argument is a finite number, and not too large for a float.
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
- `time_range`. The spectrum is of the whole sequence, as `gradient_peaks`
  without `window`.
- `acoustic_resonances`. The resonances are data of a target, not of a
  sequence.

`gradient_spectrum` calls `extensions.refuse_rotations` first, so it raises
`NotImplementedError` for a file with the Pulseq rotation extension.

`gradient_spectrum` keeps its result for the sequence object, with one
result for each set of the three arguments. It builds the result again after
`add_block`, after a new read of a file into the object, and after a change of
`seq.grad_raster_time` (the rule "Kept results" at the top of this document).
A block replaced in place is not seen: make a new sequence object for it. All
the callers share the kept result. For this reason, each array of
a `GradientSpectrum` is read-only, also for `NO_GRADIENTS`: a change in place
raises `ValueError`. `axes` is a `FrozenDict`: a change of the dict raises
`TypeError`.

`==` compares two `GradientSpectrum` objects by the values of their fields, as
for a `PnsLevels` (section 4), not by identity. A `GradientSpectrum` is not
hashable.

The spectrum is in Hz/m/√Hz, the unit of the gradients of a `.seq` file, with
no gamma. Thus the spectrum depends only on the sequence. To get the unit with
tesla, divide it by |γ| ([section 9](#9-units-and-gamma)).

```python
from pulseq_analysis.grad_spectrum import gradient_spectrum

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

s = gradient_spectrum(seq)
rss_mt = s.rss / abs(gamma) * 1e3  # mT/m/sqrt(Hz): a new array
```

The arrays of the result are read-only, so `s.rss *= 1e3 / abs(gamma)` raises
`ValueError`. Convert to a new array, as in the example.

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
values. An RMS is the root of a mean of squares. The spectrum is linear
([section 8](#8-grad_spectrum-the-gradient-spectrum)). The SAFE model is a sum
of linear filters and absolute values of the slew, divided by the stimulation
limit. Thus the value divided by |γ| is the value of the same measurement in
tesla, to the float rounding. The tests compare it with the oracles and with
pypulseq's `calculate_pns`.

**The limits of a scanner.** Convert the values to the unit of the limits, or
convert the limits to the unit of the values. pypulseq's `Opts` keeps
`max_grad` in Hz/m and `max_slew` in Hz/m/s, converted with its own gamma.
Thus the `Opts` of a target gives limits in the units of the values.

```python
from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.grad_peaks import gradient_peaks
from pulseq_analysis.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

limits = gradient_peaks(seq)
peak_mt_per_m = limits.axes["x"].peak_hz_per_m / abs(gamma) * 1e3
slew_t_per_m_per_s = limits.axes["x"].max_slew_hz_per_m_per_s / abs(gamma)

hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")  # the .asc file of the scanner
fraction = pns_levels(seq, hardware=hardware).peak_hz_per_t / abs(gamma)  # 1.0 is the limit

limit_hz_per_t = abs(gamma)
levels = pns_levels(seq, hardware=hardware, thresholds_hz_per_t=(limit_hz_per_t,))
runs = levels.above[limit_hz_per_t]  # the runs at or above the limit
```

The arrays of a `GradientSpectrum` and of a `PnsLevels` are read-only. Convert
an array to a new array (`s.rss / abs(gamma) * 1e3`,
`levels.level_max_hz_per_t / abs(gamma) * 100`). Do not change it in place.
