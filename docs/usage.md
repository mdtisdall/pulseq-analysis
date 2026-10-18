# Using pulseq-analysis

`pulseq-analysis` measures a Pulseq sequence: the gradient amplitude and slew,
the SAFE PNS prediction, the gradient spectrum and the block table.
pulseq-checks uses it to check a sequence against the limits of a scanner, and
pulseq-reports uses it for its plots. This guide shows how to use it for its
main tasks.

[`docs/implementation.md`](implementation.md) gives the exact definitions, the
rules for the rare cases, and the algorithms and the cost of each call. The
names that the two documents give are the interface of the package, and each
public module gives its names of the interface in its `__all__`. A name that
they do not give, or that starts with `_`, can change in any release. So can a
name that a module only imports from another module (for example
`NO_GRADIENTS` in `analyses.pns_levels`): import it from the module whose
`__all__` gives it (`synth.seq_index`).

Contents:

0. [Install](#0-install)
1. [Quick start](#1-quick-start)
2. [Before you start](#2-before-you-start)
3. [The gradient peaks](#3-the-gradient-peaks)
4. [Find where a value occurs](#4-find-where-a-value-occurs)
5. [Predict the PNS on a scanner](#5-predict-the-pns-on-a-scanner)
6. [The gradient spectrum](#6-the-gradient-spectrum)
7. [Run the analyses and write JSON](#7-run-the-analyses-and-write-json)
8. [The block table and the other modules](#8-the-block-table-and-the-other-modules)
9. [Units and gamma](#9-units-and-gamma)

## 0. Install

pulseq-analysis needs Python 3.12 or later. With uv, from the git URL:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@main"
```

**The extra `pypulseq`.** The package does not import pypulseq. The extra
`pypulseq` (`pulseq-analysis[pypulseq]`) installs it (`pypulseq>=1.5.0`), for the
calls that take or use a pypulseq object:

```
uv add "pulseq-analysis[pypulseq] @ git+https://github.com/mdtisdall/pulseq-analysis@main"
```

- `load(seq)` and `seqfile.read_pypulseq(seq)` read a `pypulseq.Sequence`, which
  you build with pypulseq.
- `asc_to_hw` and `safe_example_hw` are functions of pypulseq. They make a
  hardware struct, which `safe.SafeHardware.from_namespace` makes into the
  hardware of `pns_levels` ([section 5](#5-predict-the-pns-on-a-scanner)).

`load(path)`, all the measurements, `asc.hardware_from_asc` and `safe.SafeHardware`
need no pypulseq. Each example below that needs the extra says so.

**pulseq-cpp-siemens.** The interpreter `cpp-siemens` is in another
distribution, `pulseq-cpp-siemens` (`packages/pulseq-cpp-siemens/`). pulseq-analysis
has no dependency on it, in its code or in its metadata. To use `cpp-siemens`,
install both distributions:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@main" "pulseq-cpp-siemens @ git+https://github.com/mdtisdall/pulseq-analysis@main#subdirectory=packages/pulseq-cpp-siemens"
```

uv builds pulseq-cpp-siemens from source: this needs a C++ compiler and the
network (CMake fetches the reader's files from pulseq/pulseq). Without it,
`load(path, "cpp-siemens")` raises `ValueError` ([The interpreters](#the-interpreters)).

## 1. Quick start

```python
from pulseq_analysis.analyses.asc import hardware_from_asc
from pulseq_analysis.analyses.grad_peaks import gradient_peaks
from pulseq_analysis.analyses.grad_spectrum import gradient_spectrum
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

# A .seq file, read through the `spec` interpreter. It needs no [SIGNATURE] hash.
# `load(seq)` takes a pypulseq Sequence instead (it needs the extra `pypulseq`);
# `load(path, "cpp-siemens")` reads the file as the scanner's C++ reader does (it
# needs pulseq-cpp-siemens).
snap = load("sequence.seq")

peaks = gradient_peaks(snap)
print((peaks.axes["x"].peak_hz_per_m / abs(gamma)) * 1e3, "mT/m")  # T/m -> mT/m
print(peaks.axes["x"].max_slew_hz_per_m_per_s / abs(gamma), "T/m/s")

levels = pns_levels(snap, hardware=hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc"))
print(f"PNS: {levels.peak_hz_per_t / abs(gamma):.0%} of the stimulation limit")

spectrum = gradient_spectrum(snap)
print(spectrum.frequency_hz[spectrum.rss.argmax()], "Hz")
```

Each measurement takes a `Snapshot` as its first argument, not a file or a
`pp.Sequence`. `load` reads the file through an interpreter and makes the
snapshot, and [section 2](#2-before-you-start) says why.

The modules are in three subpackages: `pulseq_analysis.analyses` (the
measurements), `pulseq_analysis.synth` (the snapshot, the decoding, the events
and the waveforms) and `pulseq_analysis.seqfile` (the "as written" reading and
the interpreters of Pulseq files). This
guide writes a module by the last part of its path: `snapshot.Snapshot` is
`pulseq_analysis.synth.snapshot.Snapshot`. `load` is `pulseq_analysis.analyses.load`.

| Module | What it gives | Section |
|---|---|---|
| `pulseq_analysis.analyses` | `load`: a file or a pypulseq sequence, read through an interpreter, as a `Snapshot`. | [2](#2-before-you-start) |
| `pulseq_analysis.synth.snapshot` | `Snapshot`: the interpreter's reading and its decoding, which the measurements read. | [2](#2-before-you-start) |
| `pulseq_analysis.synth.scanner` | `Session`: the inputs of the scanner that are not in the file; the records of what a decoding applied; `ScannerSettingWarning` and `SettingError`. | [8](#the-scanner-session) |
| `pulseq_analysis.synth.events` | `decode_rf`, `decode_gradients` and `decode_adc`: the events of a `spec` model by file ID, as `RfEvent`, `Trapezoid`, `ArbitraryGradient` and `AdcEvent`. | [8](#the-events) |
| `pulseq_analysis.analyses.grad_peaks` | The peak amplitude, the peak slew and the RMS of the gradients, for the whole file, for a window and for each block. | [3](#3-the-gradient-peaks), [4](#4-find-where-a-value-occurs) |
| `pulseq_analysis.analyses.pns_levels` | The SAFE PNS prediction. | [5](#5-predict-the-pns-on-a-scanner) |
| `pulseq_analysis.analyses.safe` | `SafeHardware` and `SafeAxis`: the SAFE hardware that `pns_levels` takes. | [5](#5-predict-the-pns-on-a-scanner) |
| `pulseq_analysis.analyses.asc` | The read of a Siemens gradient `.asc` file into the hardware of `pns_levels`. | [5](#5-predict-the-pns-on-a-scanner) |
| `pulseq_analysis.analyses.grad_spectrum` | The spectrum of the gradients. | [6](#6-the-gradient-spectrum) |
| `pulseq_analysis.analyses.registry` | The analyses of the package by ID, their registry, and the `Analysis` protocol. | [7](#7-run-the-analyses-and-write-json) |
| `pulseq_analysis.analyses.series` | `Series`, the part of a value that goes into JSON, its `SeriesKind`, and `FrozenDict`. | [7](#7-run-the-analyses-and-write-json) |
| `pulseq_analysis.synth.seq_index` | The block table. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.synth.sampling` | The gradient waveform of one axis at given times. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.synth.seq_utils` | The points of one gradient event, and `TIME_TOLERANCE`. | [8](#8-the-block-table-and-the-other-modules) |
| `pulseq_analysis.seqfile.as_written` | The "as written" reading of a Pulseq text file: its sections, rows and typed fields, with line numbers. | [8](#the-as-written-reading) |
| `pulseq_analysis.seqfile.model` | `SequenceData`: what an interpreter read of a file, as read-only values, and the classes it is made of. | [8](#the-model) |
| `pulseq_analysis.seqfile.spec` | `read_spec`: the reading of the interpreter `spec`, its rules (`RULES`) and their codes. | [8](#the-interpreters) |
| `pulseq_analysis.seqfile.from_pypulseq` | `read_pypulseq`: a `pypulseq.Sequence` in memory, written to text and read through an interpreter. | [8](#a-pypulseq-sequence-in-memory) |
| `pulseq_analysis.seqfile.reading` | `read_seqfile`: a Pulseq text file through an interpreter, into a `SequenceData`. | [8](#the-interpreters) |
| `pulseq_analysis.seqfile.interpreters` | The interpreter `spec`, the protocol of a plugin interpreter, and the names of the installed interpreters. | [8](#the-interpreters) |
| `pulseq_analysis.seqfile.errors` | `SeqFileError` and `NotSupported`. | [8](#the-interpreters) |
| `pulseq_analysis.synth.decoding` | `decode`: the decoding of a file by its interpreter, and the protocol `Decoding` of a decoding. | [8](#the-interpreters) |

## 2. Before you start

- **Why a snapshot.** A measurement must describe one fixed sequence, and the
  package keeps its results, so it cannot take a sequence that can change.
  `load` reads the file, or the text of a pypulseq sequence, through an
  interpreter one time, into a `Snapshot` that only the package holds, and each
  measurement takes the snapshot. A measurement of a `pp.Sequence` or of a path
  raises `TypeError` that names `load`.
- **`load(source, interpreter="spec")`.** `source` is the path of a `.seq` file
  or a `pp.Sequence` (you have one only with pypulseq: the extra `pypulseq`,
  [Install](#0-install)). `interpreter` is a name (`"spec"`, the default, or
  the name of an installed plugin, such as `"cpp-siemens"`) or an interpreter
  object with its settings, for example `CppSiemens(rotation="apply")`
  ([The interpreters](#the-interpreters)).
  `load(path, interpreter)` is `read_seqfile(path, interpreter)`, and
  `load(seq, interpreter)` is `read_pypulseq(seq, interpreter)`: the sequence
  written with pypulseq's writer, then read as a file
  ([A pypulseq sequence in memory](#a-pypulseq-sequence-in-memory)). So the
  values are those of the file that the scanner receives (the writer rounds
  them), a later change of `seq` does not change the snapshot, and `load(seq)`
  and `load` of the file of `seq.write` give the same results. A file that the
  interpreter rejects raises its `SeqFileError` (with the code of each reason),
  a file outside the package's scope `NotSupported`, and another type of
  `source` `TypeError`. Call `load` one time for each file and interpreter, and
  give the snapshot to each measurement.
- **What a snapshot records.** `snap.interpreter` is the interpreter with its
  settings, `snap.session` the scanner session (`synth.Session`), `snap.records`
  what the interpreter recorded of the file (an extension, a label or a
  section that it ignored, `SequenceData.records`), and `snap.rotation_record`,
  `snap.soft_delay_record` and `snap.fov_record` what the decoding did with the
  rotations of the file and with the session (`synth.RotationRecord`,
  `synth.SoftDelayRecord`, `synth.FovRecord`). `snap.data` is the `SequenceData`, `snap.decoding`
  its decoding, and `snap.source` the path that `load` read (a `str`), or `None`
  for a `pp.Sequence`. A snapshot is equal only to itself.
- **Rotations.** `load` reads a file with the rotation extension (ROTATIONS,
  D2.18, D6.2). The measurements take the gradients of the decoding: `spec` rotates each
  block by its rotation from version 1.5.1, and `cpp-siemens` gives the reader's
  unrotated gradients by default, or rotates them with
  `CppSiemens(rotation="apply")`. When blocks play a rotation that the
  measurements leave unapplied (`cpp-siemens`'s default), `load` emits a
  `synth.ScannerSettingWarning`: the values are then those of the logical
  gradients, not those that the scanner plays. `load` does not read the
  `[SIGNATURE]` hash for a result: a sequence built in memory and a file with no
  `[SIGNATURE]` section load
  ([implementation, section 7](implementation.md#7-what-load-does)).
- **The scanner session.** `load(path, interpreter, session=Session(...))`
  decodes the file under the inputs of the scanner session: the values of soft
  delays, and the rotation and gradient scaling of the field of view
  ([The scanner session](#the-scanner-session)). The default is the neutral
  session: each block at its stored duration, and the field of view at the
  isocentre, not rotated or scaled.
- **The axes.** The values are of the axes of the gradients as the decoding
  gives them: the logical axes of the file (x, y, z), each block turned by its
  rotation where the decoding applies it, and turned and scaled by the field of
  view of the session. With the neutral session they are not the physical axes
  of a scanner. On an oblique slice, one physical axis can get the magnitude of
  the three-axis vector.
- **Units with no gamma.** The gradients are in Hz/m and Hz/m/s, the spectrum
  in Hz/m/√Hz and the PNS in Hz/T, as in pypulseq. Divide a value by |γ| to get
  the unit with tesla ([section 9](#9-units-and-gamma)).
- **The gradient waveform.** The measurements use the gradient waveform of
  MATLAB Pulseq. For almost all sequences it is the waveform that pypulseq
  draws. They differ only where an event starts or ends at a value that is not
  0 next to a gap, or at a step at a block junction
  ([implementation, section 1](implementation.md#1-the-gradient-waveform)).
- **Block ID and play index.** The *block ID* is the ID of the block in the
  file (`SequenceData.blocks["id"]`). The *play index* is the position of a block in play
  order, from 0. The arrays of a result have one entry for each play index.
  Use `block_id[i]` to get the block ID of play index `i`. A time is in
  seconds from the start of the sequence.
- **Kept, read-only results.** Each measurement keeps its result on the
  snapshot, so a second call with the same arguments costs nothing and gives the
  same object. The data of a snapshot does not change, so a kept result is
  never old. A copy of a snapshot from `pickle` or `copy.deepcopy` has no kept
  results and makes them again. All callers share a kept result, so its arrays
  and dicts are read-only (`series.FrozenDict`, a subclass of `dict`: a change raises
  `TypeError`). Make a copy to change one: `np.array(a)`, `dict(d)`. The result
  classes compare by value (`==`): the results of two reads of one file are equal
  ([implementation, sections 4 and 5](implementation.md#4-kept-results)).
- **No result.** A result without a value has the `reason`
  `seq_index.NO_GRADIENTS` ("no gradients"), or
  `seq_index.NO_GRADIENTS_IN_WINDOW` for a window of `gradient_peaks`. Its
  numbers are 0.0, its block fields are `None` and its arrays are empty, but
  the fields that say how it was made stay. `GradientPeaks` keeps `range_s`.
  `PnsLevels` keeps `hardware`, `hw`, `dt_s`, `bin_samples` and `on_raster`, has
  `num_samples` 0, and has `peak_time_s` `None` and an empty tuple in `above`
  for each threshold (`peak_time_s` is also `None` when all the gradients have
  the amplitude 0). `GradientSpectrum` keeps its three arguments.
  `block_gradient_values` has no `reason`: for a sequence with no gradient it
  gives zero arrays of length N.
- **Bad arguments.** A function checks its other arguments before it reads the
  snapshot: an argument of a wrong type raises `TypeError`, and a value out of
  range raises `ValueError`. Then a first argument that is not a `Snapshot`
  raises `TypeError` that names `load`. (`gradient_spectrum` checks
  that each argument is a finite number, then the snapshot, then the limits that
  need the gradient raster of the file.) The arguments after `snap` are keyword-only:
  `window`, `hardware`, `thresholds_hz_per_t`, `bin_s` and the three arguments of
  `gradient_spectrum`
  ([implementation, section 6](implementation.md#6-argument-checks)).

**The cost of each call.** The time of a call grows with the size of the
sequence: with the number of blocks, with the number of unique gradient events,
or with the duration (the number of gradient raster samples).
[Implementation, section 3.5](implementation.md#35-measured-times) gives the
measured times of each call, and
[section 3](implementation.md#3-algorithms-and-cost) the algorithms and their
complexity.

## 3. The gradient peaks

`gradient_peaks(snap)` gives the largest values of the gradients over the whole
file: for each axis the peak amplitude, the peak slew and the RMS, and the
peak of the three-axis vector. The package has no limits: the comparison of
the values with the limits of a scanner is the caller's
([section 9](#9-units-and-gamma) gives the units).

```python
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import gradient_peaks

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

snap = load("sequence.seq")
peaks = gradient_peaks(snap)
for axis, result in peaks.axes.items():
    amplitude = (result.peak_hz_per_m / abs(gamma)) * 1e3  # T/m -> mT/m
    slew = result.max_slew_hz_per_m_per_s / abs(gamma)  # T/m/s
    print(f"{axis}: amplitude {amplitude:.2f} mT/m in block {result.peak_block}")
    print(f"{axis}: slew {slew:.1f} T/m/s at {result.slew_time_s:.6f} s")
```

The slew includes the steps of the waveform: a step at a block junction counts
as a slew of `|step| / grad_raster_time`, because the scanner plays it in one
raster time.

`GradientPeaks`:

| Field | Meaning |
|---|---|
| `reason` | `None`, or `NO_GRADIENTS` (or `NO_GRADIENTS_IN_WINDOW`) when the range has no gradient. |
| `range_s` | The range of the measurement: `(0.0, end_s)`, or the window clipped to `(0.0, end_s)` ([section 4](#4-find-where-a-value-occurs)). |
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
is the block of the value. For the vector peak, the block is the block of the
earliest time with the largest value
([implementation, section 1.8](implementation.md#18-the-rms-and-the-vector-peak)).
A largest value of 0 has the block `None` and the
time 0.0. A ramp or a line between two events can belong to the block before
or after it ([implementation, section 1.6](implementation.md#16-the-credit-of-each-item-to-a-block)).

A NaN of the gradients (a plugin can read the amplitude `nan` of a file, which
`spec` rejects) propagates. A NaN is larger than every number: the peak, the
slew, the RMS and the vector peak of a range with a NaN are NaN, credited to the
first block in play order with the NaN (for the vector peak, the block of the
earliest time), at the time of its first NaN. In
`block_gradient_values`, each block with a NaN has its NaN values at the time
of its first NaN ([implementation, section 2.1](implementation.md#21-gradient_peaks-and-block_gradient_values)).

## 4. Find where a value occurs

Each value of `gradient_peaks` has its block and its time. For more, there are
two ways.

**The values of each block.** `block_gradient_values(snap)` gives the same
values for each block, as arrays in play order. Use it to plot the values
along the sequence, or to find the blocks with the largest values:

```python
import numpy as np

from pulseq_analysis.analyses.grad_peaks import block_gradient_values

values = block_gradient_values(snap)
slew_x = np.maximum(values.slew_hz_per_m_per_s["x"], values.junction_hz_per_m_per_s["x"])
for i in np.argsort(-slew_x, kind="stable")[:5]:  # the 5 largest; on a tie, play order
    slew = slew_x[i] / abs(gamma)  # T/m/s
    print(f"block {values.block_id[i]} at {values.start_s[i]:.6f} s: {slew:.1f} T/m/s")
```

| Field | Meaning |
|---|---|
| `block_id`, `start_s` | The block ID and the start of each block. |
| `peak_hz_per_m`, `peak_time_s` | Dicts by axis: the largest absolute amplitude of the block (Hz/m), and its time. |
| `slew_hz_per_m_per_s`, `slew_time_s` | Dicts by axis: the largest slope in the block, with the ramps of its event (Hz/m/s), and its time. |
| `junction_hz_per_m_per_s` | Dict by axis: the step or the line into the event of the block from the event before it (Hz/m/s). |
| `vector_peak_hz_per_m`, `vector_peak_time_s` | The largest magnitude of the three-axis vector in the block (Hz/m), and its first time. |

The slew of a block is the larger of `slew_hz_per_m_per_s` and
`junction_hz_per_m_per_s`. The largest of each amplitude array over all the
blocks is the value of `gradient_peaks(snap)`, and its slew is the larger of the
largest of `slew_hz_per_m_per_s` and the largest of `junction_hz_per_m_per_s`. A
block with no event on an axis has the values 0 there, at the time `start_s`.
[Implementation, section 2.1](implementation.md#21-gradient_peaks-and-block_gradient_values)
gives each field exactly.

**A window.** `gradient_peaks(snap, window=(start_s, end_s))` gives the largest
values in that range of time, for example one TR or the time of one ADC:

```python
tr = 6e-3
peaks_tr_10 = gradient_peaks(snap, window=(10 * tr, 11 * tr))
```

`window` is a tuple or a list of two real numbers. It must be in the sequence
(each end within `seq_utils.TIME_TOLERANCE`, 1e-9 s), with `start_s < end_s`.
A window that is not a pair, or has an end that is not a real number, raises
`TypeError`, and another bad window raises `ValueError`. A segment that crosses
an end of the window is cut there. A step is in the window when
`start_s <= t < end_s` (and more than `seq_utils.TIME_TOLERANCE` before the end
of the sequence). A result with a window is not kept, because a caller can ask
for many windows, but it uses the kept values of each block. So after the first
call, a window costs about the number of blocks in it.

## 5. Predict the PNS on a scanner

`pns_levels(snap, hardware=..., thresholds_hz_per_t=(), bin_s=BIN_S)` runs the
SAFE PNS model of pypulseq on the gradients of the sequence. The three
arguments after `snap` are keyword-only.

**The hardware.** The model needs the SAFE parameters of the gradient coil of
the scanner. There is no default. `hardware` is a `safe.SafeHardware`: a
`name`, which is the label of the result, and the `SafeAxis` of `x`, `y` and
`z`. `asc.hardware_from_asc(path)` makes it from the Siemens gradient `.asc`
file of the scanner (`MP_GPA_*.asc` or `MP_GradSys_*.asc`), with the files of
its `$INCLUDE` lines, and names it after the component in the file. A file
with no gradient scale factors
(`asGPAParameters[0].sGCParameters.flGScaleFactorX`, `Y` and `Z`) raises
`ValueError`: the model multiplies each PNS value by the factor, so the
package does not assume one. `SafeHardware.from_namespace(struct, "a label")`
makes it from a struct in the form of pypulseq's `asc_to_hw` (which needs the
extra `pypulseq`). For a test, pypulseq's example hardware, which is not a
real scanner, is
`hardware=SafeHardware.from_namespace(safe_example_hw(), "a label")`
(`safe_example_hw` is in `pypulseq.utils.safe_pns_prediction`, so it needs the
extra `pypulseq`). A `hardware` that is not a `SafeHardware` raises
`TypeError`, also the pair `(struct, label)` of `0.1.0rc6`, also for a
sequence with no gradient.

A `SafeHardware` is checked when it is made, so `pns_levels` does not check it
again. A struct with a missing axis or a missing field of `safe.SAFE_FIELDS`, a
field that is not a finite number, a `stim_limit` not above 0, or an axis with
`a1 + a2 + a3` more than 0.001 from 1 raises `ValueError` (or `TypeError` for a
field that is not a number). A name `"nan"`, `"inf"` or `"-inf"` raises
`ValueError`: the JSON form of a `Series` uses these strings for a float that
is not finite, so the name could not go into the `meta` of `pns_total`.

**The limit.** The PNS values are in Hz/T. The stimulation limit is `abs(gamma)`,
and a value divided by `abs(gamma)` is the fraction of the limit. To find the
times above a fraction `f` of the limit, give the threshold `f * abs(gamma)`.
`thresholds_hz_per_t` is a tuple of numbers above 0, finite, with no two equal
(a value that is not a tuple, or an element that is not a number, raises
`TypeError`; another bad value raises `ValueError`):

```python
from pulseq_analysis.analyses.asc import hardware_from_asc
from pulseq_analysis.analyses.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")
levels = pns_levels(snap, hardware=hardware, thresholds_hz_per_t=(abs(gamma), 0.8 * abs(gamma)))

if levels.peak_time_s is None:  # the peak is 0: no gradient, or all have the amplitude 0
    print(f"peak {levels.peak_hz_per_t / abs(gamma):.0%}")
else:
    print(f"peak {levels.peak_hz_per_t / abs(gamma):.0%} at {levels.peak_time_s:.4f} s")
for run in levels.above[0.8 * abs(gamma)]:
    print(f"at or above 80 % from {run.start_s:.4f} s to {run.end_s:.4f} s")
```

**The level, for a plot.** `level_min_hz_per_t` and `level_max_hz_per_t`
are the least and the greatest total of each bin of `bin_s` (5 ms by
default). A bin is a whole number of samples, at least one: `bin_samples` is
`bin_s / dt_s` rounded to the nearest whole number when it is within 1e-6 of
one, and else rounded down. A very long sequence has longer bins, so that the
level has at most `pns_levels.MAX_BINS` (2,000,000) bins. `bin_s` changes only
the level, not the peak or the runs:

```python
import numpy as np

t_s = np.arange(levels.level_max_hz_per_t.size) * levels.bin_samples * levels.dt_s
percent = (levels.level_max_hz_per_t / abs(gamma)) * 100  # fraction -> %, a new array
```

`PnsLevels`:

| Field | Meaning |
|---|---|
| `reason` | `None`, or `NO_GRADIENTS`: then the peaks are 0, `peak_time_s` is `None`, and there are no bins and no runs. |
| `hardware` | The label of the hardware: its `SafeHardware.name`. |
| `hw` | The SAFE parameters of each axis that the model used. |
| `peak_hz_per_t`, `peak_time_s` | The largest total (Hz/T), and the time of its first sample (`None` when the peak is 0). A NaN of the gradients makes the totals from it NaN: then the peak is NaN, at the time of the first NaN total. |
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

## 6. The gradient spectrum

`gradient_spectrum(snap)` gives the spectrum of the gradients: for each
frequency, the largest amplitude over 50 ms windows of the sequence. This
example prints the largest value of each band of frequencies that the caller
gives (the centre and the width of each), for example the bands of the acoustic
resonances of a gradient coil:

```python
import numpy as np

from pulseq_analysis.analyses.grad_spectrum import gradient_spectrum

gamma = 42.576e6  # Hz/T

bands = [(590.0, 100.0), (1140.0, 220.0)]  # (Hz, Hz): the centre and the width

s = gradient_spectrum(snap)
for frequency, width in bands:
    band = np.abs(s.frequency_hz - frequency) <= width / 2
    peak = (s.rss[band].max() / abs(gamma)) * 1e3  # T/m/sqrt(Hz) -> mT/m/sqrt(Hz)
    print(f"{frequency:.0f} Hz: {peak:.3g} mT/m/sqrt(Hz)")
```

The method is that of pypulseq's `calculate_gradient_spectrum`: Hann windows
that overlap by 50 %, the magnitude of the FFT of each window as an amplitude
spectral density, the RSS of the three axes in each window, and the maximum
over the windows. It differs from pypulseq in two ways. The waveform is the one
of MATLAB Pulseq ([section 2](#2-before-you-start)). And the gradients are
sampled to the end of the sequence, with half a window of zeros before them and
half a window or more after them, so a sequence shorter than one window has a
spectrum ([implementation, section 2.3](implementation.md#23-gradient_spectrum)).

| Argument | Default | Argument of pypulseq | Meaning |
|---|---|---|---|
| `max_frequency_hz` | `MAX_FREQUENCY_HZ` (2000.0) | `max_frequency` | The highest frequency of the result. |
| `window_s` | `FFT_WINDOW_S` (0.05) | `window_width` | The length of a window. |
| `frequency_oversampling` | `FREQUENCY_OVERSAMPLING` (3.0) | `frequency_oversampling` | The length of the FFT, as a multiple of the samples of a window. |

The three arguments are keyword-only. Each is a finite number. `window_s` is
above 0 and at least 2 samples of the gradient raster of the file, and
`frequency_oversampling` is 1 or more. `max_frequency_hz` is above 0, at most the
Nyquist frequency of the gradient raster, and at least the frequency step
`1 / (nfft * dt)` (`nfft` is the length of the FFT and `dt` the gradient raster).
A value of a wrong type raises `TypeError`, and a value that breaks a limit
raises `ValueError`.

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
installed analyses with `registry.registry()`, and runs them by ID:

```python
import json

from pulseq_analysis.analyses.registry import registry
from pulseq_analysis.analyses.asc import hardware_from_asc

gamma = 42.576e6  # Hz/T

analysis = registry()["pns.safe.levels"]
levels = analysis.compute(
    snap,
    hardware=hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc"),
    thresholds_hz_per_t=(abs(gamma),),
)
text = json.dumps([s.to_obj() for s in analysis.to_series(levels)], allow_nan=False)
```

An analysis is an object that has the following, as the protocol
`registry.Analysis` says:

- `spec`, an `AnalysisSpec`: `id`, `version`, `title`, `description` (the
  contract of the value), `params` (the keyword arguments of `compute`),
  `necessary` (the arguments with no default), `defaults` (pairs
  `(name, default)`), `rasters` (the rasters of the file that change its
  value), `cost` and `series` (the text that says what `to_series` gives).
- `compute(snap, **params)`: the full Python value, the kept result of its
  function (`gradient.peaks` with a `window` is not kept). `snap` is a
  `Snapshot`. The parameters are keyword-only: a runner gives the names in
  `Analysis.spec.necessary` and can leave out the others, which then have their
  `Analysis.spec.defaults`.
- `to_series(value)`: a tuple of `Series`, the part of the value that can go
  into JSON. `()` for an analysis with nothing for JSON, and for a value with
  `NO_GRADIENTS`.

The analyses of this package (each `version` is 1):

| ID | `compute` | Necessary | Defaults | Cost | `to_series` |
|---|---|---|---|---|---|
| `seq.index` | `sequence_index(snap)` | none | none | fast | `()` |
| `gradient.peaks` | `gradient_peaks(snap, window=window)` | none | `window=None` | fast | `()` |
| `gradient.blocks` | `block_gradient_values(snap)` | none | none | fast | `()` |
| `pns.safe.levels` | `pns_levels(snap, hardware=..., thresholds_hz_per_t=..., bin_s=...)` | `hardware` | `thresholds_hz_per_t=()`, `bin_s=BIN_S` | slow | `pns_total`, `pns_above_<k>` |
| `gradient.spectrum` | `gradient_spectrum(snap, max_frequency_hz=..., window_s=..., frequency_oversampling=...)` | none | the defaults of `grad_spectrum` | slow | `gradient_spectrum` |

The `cost` is `"fast"` when the time grows with the number of blocks and of
unique events, and `"slow"` when it grows with the duration of the sequence. The
`rasters` are names from `registry.RASTERS` (`GradientRasterTime`,
`BlockDurationRaster`, `RadiofrequencyRasterTime`, `AdcRasterTime`). `AnalysisSpec`
checks its fields: `id` is a `str` that is not empty, `version` is an `int` of 1
or more, `title` and `description` are `str`, `series` is None or a `str`,
`cost` is `"fast"` or `"slow"`, each raster is in `RASTERS`, `params` and
`necessary` are tuples of unique `str`, each name of `params` is in `necessary`
or has one default (in the order of `params`), and each default is `None`, a
`bool`, an `int`, a finite `float`, a `str` or a tuple of these. It raises
`ValueError` for a bad value and `TypeError` for a wrong type.

The objects of this package are `registry.SEQ_INDEX`, `registry.GRADIENT_PEAKS`,
`registry.GRADIENT_BLOCKS`, `registry.PNS_SAFE_LEVELS` and
`registry.GRADIENT_SPECTRUM`, in the order of the table (the targets of its entry
points).

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
`arrays` and `meta` are `series.FrozenDict`s, and `kind` is a member of the enum
`series.SeriesKind`: `SAMPLES`, `ENVELOPE`, `POINTS` or `RUNS`.
The kind gives the shape of the data:

| Kind | Meaning | Necessary arrays | Fields |
|---|---|---|---|
| `SAMPLES` | `value[k]` is at `coord_start + k * coord_step`. | `value`, and more of the same length | `coord_start`, `coord_step`; `coord_end` is `None` |
| `ENVELOPE` | `min[i]` and `max[i]` are the least and the greatest value in bin `i`, from `coord_start + i * coord_step`. The last bin stops at `coord_end`. | `min`, `max`, and no other | `coord_start`, `coord_step`, `coord_end` |
| `POINTS` | `value[k]` is at `coord[k]`. | `coord`, `value`, and more of the same length | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |
| `RUNS` | A boolean that is true from `start[k]` to `end[k]`. | `start`, `end`, and a value of each run | `coord_start` is 0.0, `coord_step` and `coord_end` are `None` |

A `Series` is read-only: its arrays cannot be made writable, also in a copy from
`pickle` or `copy.deepcopy`. An `ENVELOPE` has `min` and `max` of one integer or
float dtype with `min <= max`, `POINTS` has a `coord` of an integer or float
dtype, and `RUNS` has `start` and `end` of an integer or float dtype, finite,
with `end >= start` for each run. A `Series` raises `TypeError` for a value of a
wrong type and `ValueError` for a wrong value. A numpy scalar in `meta` is stored
as a Python scalar. Two series with the same fields and arrays are equal
(`==`).

`Series.to_obj()` gives a dict that `json.dumps(obj, allow_nan=False)` writes. Its keys
are `format` (the number 1), `name`, `kind` (the value of the `SeriesKind`, for example
`"envelope"`), `unit`, `coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta` and
`arrays`. A float of `meta` that is not finite is the string `"inf"`, `"-inf"` or `"nan"`.
`Series.from_obj(obj)` is the inverse (it
raises `ValueError` for a bad object: with no `format`, with a `format` other than 1, with
a key that format 1 does not have, or with a number that is too large for a float).
`Series.from_obj(obj, max_bytes=n)` also raises `ValueError` when the arrays together have
more than `n` bytes after decompression. `encode_array(a)` gives an array as
compact text (`{"dtype", "length", "data"}`, gzipped and base64-encoded), the
encoding of the tables of pulseq-reports, and `decode_array(d, max_bytes=None)` is the
inverse ([implementation, section 8](implementation.md#8-series-checks-and-the-array-encoding)).

**Your own analysis.** A package gives its analyses as entry points of the
group `pulseq_analysis.analyses` (`registry.GROUP`). The name of an entry point
is the ID, and its object is the analysis. `registry.registry()` gives a dict
from each installed ID to its analysis, and raises `registry.RegistryError`
for two analyses with one ID, an entry point that does not load, an object
with no `Analysis.spec.id`, or an entry point whose name is not the `Analysis.spec.id` of its
object. `registry.registry(strict=False)` leaves such an entry point out
instead, with an `registry.RegistryWarning` (a `UserWarning`) that has the text
of the error, and gives the other analyses. Of two entry points with one ID, the
one of this package stays, or else the first. The analyses of this package are
always in the result.

## 8. The block table and the other modules

**The block table.** `sequence_index(snap)` gives a `SequenceIndex`: one entry
for each block in play order, with the unique events of each kind numbered
from 1 in the order of their first use. The gradient events are those that the
measurements play: the events of the file by their IDs, and in a block whose
gradients the decoding gives from `gradients_at` (a block with a gradient event
that it or the session's field of view rotates, or that the field of view
scales, or a block with an event after its end), an event of its own on each
axis of a rotated block, and on each axis with an event of another block
([implementation, section 2.5](implementation.md#25-the-block-table)).
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
`Analysis.spec.version` of `seq.index`.

`has_gradients(index)` is true when the index has a gradient event on any
axis. The numbers of the table are not the IDs of the file. The events
themselves, by the IDs of the file, are in the decoding of the snapshot
([The events](#the-events)).

**The gradient waveform.** `sampling.gradient_sampler(snap)` gives a
`GradientSampler`. `sampler.sample(axis, t)` gives the waveform of one axis
(`"gx"`, `"gy"` or `"gz"`) in Hz/m at the sorted times `t`, for a plot:

```python
import numpy as np

from pulseq_analysis.synth.sampling import gradient_sampler

t = np.linspace(0.0, 0.01, 2001)  # the first 10 ms
gx = gradient_sampler(snap).sample("gx", t)
```

`GradientSampler.block_samples`, `sampling.raster_block_lengths` and
`sampling.sequence_samples` give the
samples on the gradient raster that the PNS model and the spectrum use
([implementation, section 2.4](implementation.md#24-the-sampler-and-the-number-of-samples)).

**`seq_utils`.** `gradient_offsets(g)` gives the delay, and the times after
the delay and the amplitudes (Hz/m) of the points of the gradient event `g`.
`gradient_points(g, t0)` gives the times (`t0` + delay + offset) and the
amplitudes. `TIME_TOLERANCE` is 1e-9 s.

**`asc`.** Besides `hardware_from_asc`, `asc.read_gradient_asc(path)` gives
the fields of a `.asc` file, with the fields of each file that an `$INCLUDE`
line names (an included field wins over a field that the file sets after the
`$INCLUDE` line), `asc.hardware_name(asc)` gives the name of the component
in those fields, and `asc.safe_hardware(asc)` gives the `SafeHardware` of
those fields (`ValueError` that names a missing field, also the gradient scale
factors). A `$INCLUDE` line is `$INCLUDE` in any case, a name (in double
quotes when it has spaces) and optionally a comment that starts with `#` or
`//`. An included file is in the directory of the file that includes it. Any
other line that starts with `$INCLUDE` raises `ValueError` that names the file
and the line, a file that includes itself (or a cycle of files) raises
`ValueError` that names the cycle, and a missing included file raises
`FileNotFoundError`.

### The interpreters

pulseq-analysis reads a Pulseq text file through one of its **interpreters**
(`docs/plans/parser-redesign.md`, section 1). It reads, interprets and
measures; it does not judge whether a file is valid. pulseq-checks reports
where the interpreters and the other readers of the format disagree.

| Interpreter | Name | What it reads |
|---|---|---|
| `interpreters.Spec` | `"spec"` (the default) | The file as the Pulseq specification (1.5.3 draft) and the slide set that its section 2.6 cites for timing describe it: a rejection, with every violation, where they say "must"; a documented reading where they are silent (`spec`). Pure Python. Part of the package. |
| A plugin (`interpreters.Plugin`) | The name of its entry point | The file as the plugin reads it. Another distribution gives it (below). |

pulseq-analysis has one plugin in this repository, and no reference to it in
its code or its metadata: the sub-project `packages/pulseq-cpp-siemens/` gives
the interpreter `cpp-siemens`, which reads a file as the C++ reader of the
scanner's interpreter on Siemens systems reads it. To use it, install both
distributions ([Install](#0-install)). Its settings, the codes
of its rejections, its model and its decoding are in
`packages/pulseq-cpp-siemens/README.md`.

The default is the fast interpreter: `cpp-siemens` decodes every block with the
C++ reader to give its verdict, and takes about six times as long as `spec`. On an
Apple M1 Max, a file of 20 MB with 900 000 blocks (the blocks of
`tests/seqfiles/valid_1_5_0.seq`, repeated) takes 0.3 s to read as written, 0.5 s
with `spec` and 2.9 s with `cpp-siemens`.
Name `"cpp-siemens"` to get what the scanner's reader reads.

```python
from pulseq_analysis.seqfile import interpreter_names, read_seqfile
from pulseq_analysis.synth import decode

interpreter_names()  # ('spec',), and the name of each plugin that is installed
spec = read_seqfile("sequence.seq")  # interpreter="spec", the default
data = read_seqfile("sequence.seq", interpreter="cpp-siemens")  # a plugin, by name
data.interpreter  # CppSiemens(oversampling='center', rotation='reader'); str() is 'cpp-siemens'

plugin = decode(data)  # the plugin's own decoding
plugin.gradients_at([0, 0], [10.0, 20.0])  # Hz/m, times in us from the start of each block
plugin.rotations()  # the blocks with a rotation, and their quaternions
plugin.rotation_record  # what the decoding does with the rotations

decode(spec).gradients_at([0], [10.0])  # spec: rotated from 1.5.1, as the file says
```

With pulseq-cpp-siemens installed, an interpreter object gives the settings:
`from pulseq_cpp_siemens.interpreter import CppSiemens` and
`read_seqfile("sequence.seq", interpreter=CppSiemens(oversampling="edge"))`.

**`reading.read_seqfile(path, interpreter="spec")`** (also
`seqfile.read_seqfile`) takes an interpreter by name or as an object;
`interpreters.interpreter(value)` gives the object of a name, with its default
settings, and `interpreters.interpreter_names()` lists the names: `"spec"`,
then the name of each plugin, sorted. (`interpreters.Interpreter` is `Spec` or
a `Plugin`.) It returns a
`model.SequenceData`, whose `interpreter` field records the interpreter and its
settings. It raises:

- `errors.SeqFileError` (a `ValueError`) when the interpreter rejects the
  file. Its `violations` are its reasons, each an `errors.Violation` (`rule`,
  the code; `section`; `line`; `message`), `codes` is the set of the codes,
  `interpreter` the name of the interpreter, and `path` the file.
- `errors.NotSupported` (a `NotImplementedError`) for a file that the package
  does not read, whatever the interpreter: a version outside 1.4.0 to 1.5.x (Q1
  of the plan), a binary Pulseq file or a folder. `read_seqfile` checks them
  before the interpreter reads the file, with one message for each. It says
  nothing about whether the file is valid.
- `ValueError` for a name that no installed interpreter has. The message gives
  the installed names and the entry-point group: "no interpreter is named
  'cpp-siemens'; the installed interpreters are spec. A distribution adds one
  through the entry-point group pulseq_analysis.interpreters." This is what
  `read_seqfile(path, "cpp-siemens")` raises when pulseq-cpp-siemens is not
  installed.
- `ImportError` (chained to the cause) for a plugin that does not load;
  `OSError` when the file cannot be read.
- `TypeError` for a value that is neither a name nor an interpreter object. A
  class is not an interpreter: `read_seqfile(path, Spec)` raises `TypeError`
  whose message names `Spec()`, the object to give.

**Plugin interpreters.** A distribution adds an interpreter through the
entry-point group `interpreters.GROUP` (`"pulseq_analysis.interpreters"`). The
name of the entry point is the name of the interpreter, and its value is a
class. In the `pyproject.toml` of the distribution:

```toml
[project.entry-points."pulseq_analysis.interpreters"]
cpp-siemens = "pulseq_cpp_siemens.interpreter:CppSiemens"
```

`interpreters.interpreter_names()` reads the entry points and imports no
plugin. `interpreters.interpreter(name)` imports the plugin of that name, only
then, and makes an object of its class with no argument: the interpreter with
its default settings. The package has no import of a plugin, so it works with
no plugin installed.

The class is of the protocol `interpreters.Plugin`:

- `name`: a class attribute, equal to the name of the entry point (the name of
  the plugin cannot be `spec`).
- `protocol`: a class attribute, the version of this protocol that the plugin
  implements. The package uses a plugin only of its own version,
  `interpreters.PROTOCOL` (also `seqfile.PROTOCOL`; it is 1 now), and
  `interpreters.interpreter` raises `TypeError` that names both versions for
  another.
- `read(path)`: the Pulseq text file `path` (a `Path`) into a
  `model.SequenceData` whose `interpreter` is this object; it raises
  `SeqFileError`, `NotSupported` and `OSError` as `read_seqfile` does.
  `SequenceData.reading` is the plugin's own object (None for `spec`).
- `decode(data, session=None)`: the decoding of a `SequenceData` that `read`
  made, under the scanner session `session` (`scanner.Session`), an object of
  the protocol `decoding.Decoding`. `decoding.decode` calls it with a session.
  The plugin applies the session with its own hooks, and may use the shared
  simulation of `scanner` ([The scanner session](#the-scanner-session)).
- `str()`: the name, with each setting that is not its default.

A plugin is a frozen dataclass, as `Spec` is: two with the same settings are
equal. A setting that the interpreter does not have (`Spec(rotation="apply")`)
raises `TypeError` when the object is made. `interpreters.interpreter(name)`
raises `ValueError` for two entry points with one name, `TypeError` for a class
whose `name` is not the name of its entry point, and `ImportError` for an entry
point that does not load.

**The decoding.** `decoding.decode(data, session=None)` (also `synth.decode`)
decodes a model by its interpreter, under the scanner session `session` (the
neutral `Session()` for None). For `spec` it gives a `decoding.SpecDecoding` with the
gradient events of the model by file ID (`gradients`, from `events.decode_gradients`).
The events of the model come from `events.decode_rf`, `events.decode_gradients`
and `events.decode_adc`, into `events.RfEvent`, `events.Trapezoid`,
`events.ArbitraryGradient` (together `events.GradEvent`) and `events.AdcEvent`.
These three refuse the model of a plugin (`TypeError`); [The events](#the-events)
gives their fields. For a plugin it gives what `Plugin.decode` gives. Both are of the protocol `decoding.Decoding`, which
is what the package uses of a decoding. Blocks are indexed in play order from 0:

- `interpreter`: the interpreter of the model, with its settings.
- `session`: the scanner session that the decoding applies.
- `block_count`: the number of blocks.
- `block_durations` and `stored_block_durations`: the actual and the stored
  duration of each block in s (read-only arrays). The actual one is the stored
  one, except for a block whose soft delay the session sets; the measurements
  use it.
- `rotations()`: the play indices of the blocks with a rotation, and their
  quaternions, an array (n, 4) of q0, qx, qy, qz, of norm 1.
- `rotation_record`: what the decoding does with the rotations
  (`scanner.RotationRecord`), below.
- `soft_delay_record` and `fov_record`: what it does with the session's soft
  delays and field of view (`scanner.SoftDelayRecord`, `scanner.FovRecord`),
  and `fov_flags()`: the flag NOROT and the scaling flag of each block (two
  bool arrays) ([The scanner session](#the-scanner-session)).
- `gradients_at(block_index, time_us, rotated=None)`: the gradients in Hz/m at
  each pair of a block index and a time in us from the start of that block, an
  array (n, 3), 0 after the actual end of the block. `rotated=None` follows the
  interpreter and the session; `False` gives the logical gradients, and `True`
  also rotates each block by its rotation, for one call.
- `gradient_points(key, block, axis)`: the `decoding.Points` of the gradient
  event with the file ID `key` that the block `block` plays on the axis `axis`
  (0, 1, 2 for x, y, z), not rotated. `Points` is a tuple of the delay in s, the
  offsets in s from the delay and the values in Hz/m of the points between
  which the event is straight lines (`seq_utils.gradient_offsets`).
- `gradient_variants()`: which blocks and axes decode their gradient event
  alike. None when each gradient event decodes alike in every block that plays
  it. Otherwise an int64 array (blocks, 3), read-only: two cells with the same
  event and the same value decode alike (`gradient_points` gives the same
  points for both). The values mean nothing more, and a cell with no event has 0.

`SpecDecoding` also has the blocks (`blocks`, the block table of the model) and
the flags (`norot`, `noscale`). In it, each event is the straight lines between its
points, 0 before its delay and after its end, and every value is 0 outside the
block, and `gradient_variants()` is None. A plugin that decodes a block at a
time can decode one event differently in two blocks: `gradient_points` takes the
block, and `gradient_variants()` says which blocks decode an event alike. The
measurements ask `gradient_points` once for each event and variant, and count
each variant as an event of its own. `load` keeps the decoding on the snapshot
(`Snapshot.decoding`), and the measurements take their gradients from it, by
`gradient_points`, `gradient_variants` and `gradients_at`.

**Rotations.** A decoding gives the rotation of each block (the ROTATIONS
extension, D2.18 and D4.6) with `rotations()` and what it did with them with
`rotation_record`. `rotation_record` is a `scanner.RotationRecord` (also
`synth.RotationRecord`): `setting`, `blocks` (with a rotation), `not_identity`
(whose rotation is not the identity: the blocks that play a rotation),
`rotated` and `hint`. `str` gives, for example, "rotation: apply, 5 block(s)
rotated". Its `warning()` is a `scanner.ScannerSettingWarning` (a
`UserWarning`) when the decoding leaves a rotation unapplied, and None
otherwise. The text of the warning ends with `hint`, the advice of the
interpreter for the gradients that the scanner plays (empty for none; it is not
compared by `==`). The decoding does not emit the warning; `load` emits it, and
keeps the record on the snapshot (`Snapshot.rotation_record`).

**Rotations in `spec`.** `spec` applies the content of the file from the
revision that introduced it (P20, rule 2): from 1.5.1, `SpecDecoding` rotates
the gradients of each block whose extension list has a ROTATIONS object by its
quaternion, divided by its norm (D2.18). It has no setting for this
(`Spec(rotation=...)` raises `TypeError`) and nothing to warn about (rule 4).

- `rotations()` gives the play index of each block with a rotation and its
  quaternion (q0, qx, qy, qz); both are empty for a file older than 1.5.1.
- `gradients_at` turns each block's values by its quaternion with
  `decoding.rotate`, the active rotation `R(q) v` with q0 the scalar part, in
  float64: the rotation of the C++ reader's `rotate_vec3_by_quat`, and of
  MATLAB's `mr.rotate3D`. On each fixture with rotations from 1.5.1 it gives the
  gradients of MATLAB's `waveforms_and_times`, and those of `cpp-siemens` with
  `rotation="apply"` to float32 precision. `rotated=False` gives the logical
  gradients for one call.
- `rotation_record` is a `RotationRecord` with the setting `"apply"` and every
  block with a rotation rotated, so its `warning()` is always None.
- In a file older than 1.5.1, ROTATIONS is an unknown extension: ignored and
  recorded (`SequenceData.records`, reason `"version"`, D4.6), and no block is
  rotated. `cpp-siemens` with `rotation="apply"` rotates such a file, as the
  reader attaches the rotation in any version.

**`spec`.** `spec.read_spec(path)` reads with the rules of `spec.RULES`, and its
`SeqFileError` has every violation (at most `spec.MAX_LOCATIONS` for each rule,
and a count of the rest). Its sources are the specification
(`doc/specification.tex` of pulseq/pulseq at `c7469123`, 1.5.3 draft) and, for
timing, the slide set that its section 2.6 cites
(`doc/pulseq_shapes_and_times.pdf`). Where they say "must", `spec` rejects the
file. Where they are silent, section 6 of `docs/plans/parser-redesign.md` gives
the reading, and `spec` rejects a file only where no current writer (MATLAB
Pulseq, pypulseq) writes such a file. Each rule is a `spec.Rule`: `text`,
`source` (the lines of the specification, the slides, the entries of
`docs/discrepancies.md`), and `choice`, which says why the package rejects the
file when the specification does not state the rule. The message of a violation
of such a rule ends with "(the specification does not state this rule: …)", so a
reader of the error sees that it is the package's choice and why.

| Code | Basis | `spec` rejects |
|---|---|---|
| `version.missing` | spec:201; D1.1 | no `[VERSION]` section |
| `version.invalid` | spec:193-198 | a line of `[VERSION]` that is not `major`, `minor` or `revision` with an integer (`minor 5.0`), a key missing, or repeated |
| `definitions.raster-missing`, `definitions.raster-invalid` | spec:267-276 | a required raster that is missing, or not one finite number above 0 |
| `definitions.raster-commensurate` | slide 11 | an RF or gradient raster that is neither an integer multiple nor a divisor of the block duration raster |
| `section.duplicate` | choice; D3.3 | a section that appears twice, or two `extension` sections with one `STRING_ID` (the readers disagree on what a second copy means; only the first is read) |
| `syntax.encoding` | choice; D3.1 | a byte that is not UTF-8 (the specification gives no encoding; MATLAB Pulseq and pypulseq fail on it) |
| `syntax.line` | choice; D3.2 | a data line before the first section |
| `syntax.columns`, `syntax.integer`, `syntax.number` | the tables of spec:293-455; D1.2, D3.5 | a row with too few or too many fields; a value that is not of its column's type (`30.5` in an integer column); NaN or infinity in a float column (a choice) |
| `syntax.use` | spec:356-357 | an RF `use` that is not one of `e r i s p o u` |
| `syntax.negative` | choice; D3.6 | a negative block duration, delay, rise, flat or fall time, number of samples, dwell time or trigger duration (spec:176 stores integers as unsigned, but defines negative values elsewhere) |
| `syntax.shape` | spec:602-612; D3.11 | a shape without its `shape_id` and `num_samples` lines, a line of `[SHAPES]` outside a shape, or a shape with no blank line after it (a choice) |
| `id.positive`, `id.unique`, `id.gradient-unique` | spec:181-183, spec:403, spec:472, spec:494; D3.4 | an ID that is not positive, also the type ID of an extension (in an `extension` header or in `[EXTENSIONS]`); an ID used twice in a class (for blocks a choice); a gradient ID in `[GRADIENTS]` and `[TRAP]` |
| `ref.unresolved` | spec:178-186, spec:478, spec:349, spec:395, slide 4; D4.3 | a reference to nothing; a list of extensions that does not end; time ID -1 for an RF event, or in a 1.4 file |
| `blocks.empty`, `block.event-too-long` | spec:318 | no block; an event longer than its block |
| `raster.adc-dwell`, `raster.gradient-delay`, `raster.gradient-end`, `raster.gradient-ramp`, `raster.gradient-flat` | spec:275, spec:290; slides 5, 10 | a time off its raster |
| `raster.rf-delay`, `raster.adc-delay` | slides 9, 10 | an RF event or an ADC that does not start on an edge of the RF raster |
| `raster.gradient-vertex` | choice (slides 4 and 6 conflict); D1.3 | a vertex of a gradient time shape off the gradient raster |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | spec:420; slide 6 | a gradient that starts above 0 after a delay, or ends above 0 before its block ends |
| `shape.length`, `shape.range` | spec:626, spec:624 | a shape that does not decompress to `num_samples`; an amplitude shape outside [-1, 1] |
| `shape.empty`, `shape.event-length` | choice; D3.7, D3.8 | a shape with no sample that an event uses; the shapes of one event of different lengths, or an ADC phase shape whose length is not the number of ADC samples |
| `shape.time-order` | choice; D3.9 | an RF time shape of one sample at 0 or before, a time shape whose times do not increase, a time shape (RF or gradient) that starts before 0 |
| `shape.oversampled-length` | spec:420, slides 4, 8 | an oversampled gradient (time ID -1) with an even number of samples |
| `limit.shape-samples` | the package's limit of memory (the specification has none) | a shape that declares more than 2^27 samples: `spec` does not decompress it |
| `extension.required-unknown`, `extension.per-block` | spec:460, spec:567, spec:584 | an unknown required extension (from 1.5.1); two ROTATIONS or RF_SHIMS objects in a block |
| `layer1.gradient-ends` | choice; D4.4, D4.5 | a 1.4 arbitrary gradient on the default raster, or with a time shape that starts after 0: the file has no value at its ends |
| `rotation.zero` | choice; D3.10 | a quaternion of ROTATIONS of norm 0 (from 1.5.1 `spec` divides each quaternion by its norm) |
| `signature.invalid` | spec:223-232 | `[SIGNATURE]` without one `Type` and one `Hash` |

What `spec` reads where the specification is silent (section 6 of the plan, and
`docs/discrepancies.md` entry by entry): a blank or `#` line anywhere, also
inside a table or a shape (in a shape a blank line ends it); a section that the
format does not have, and `[DELAYS]`, are ignored; a definition that appears
twice is the last; blocks play in file order, whatever their IDs; an extension
is read from the version that introduced it (`extension DELAYS` from 1.5.0,
ROTATIONS and RF_SHIMS from 1.5.1, section 7.8 of the plan), and in an older
file it is unknown and ignored (`SequenceData.skipped_extensions`); from 1.5.1
a quaternion of ROTATIONS is divided by its norm, and the decoding rotates the
block's gradients by it; an RF magnitude below 0 and an RF phase
outside [0, 1) play as written; any gradient raster that the slides allow plays
on its own raster; the signature is checked by the rule of the specification
(`AsWritten.signed_bytes()`), and a mismatch is not a rejection.

**Records.** `SequenceData.records` has a `model.Record` (`kind`, `subject`,
`reason`, `line`) for each thing that `spec` ignored, in file order: an
`"extension"` that it does not know (`reason` `"unknown"`, D2.17) or that the
version of the file does not have yet (`"version"`); a `"section"` that the
format does not have (`"unknown"`, D2.4) or removed (`"removed"`: `[DELAYS]`); and a `"label"` of `LABELSET` or `LABELINC` that the specification does not
list (`"unknown"`, D2.19: also `NOSCL`, which the specification spells `NOSLC`)
or that the version does not have yet (`"version"`: the flags `PMC`, `NOROT`,
`NOPOS`, `NOSLC` and `ONCE` of 1.4.1). The row of such a label stays in the
table. The records are part of the contract with pulseq-checks. `cpp-siemens`
also records what its reader ignores, in the same form: an `"extension"` that the
reader does not know (`reason` `"unknown"`), and a `"label"` of LABELSET or
LABELINC that the reader leaves out (`"unknown"`: a label that its `decodeLabel`
does not know, such as `NOSLC`, or one that it ignores on purpose, `PMC` and
`TRID`). It has no record of kind `"section"`, and none with the reason
`"version"` (`packages/pulseq-cpp-siemens/README.md`). What a decoding does with the
rotations of the file, and with the soft delays and the field of view of the
session, is in the three records of the decoding, not in `SequenceData.records`
([The scanner session](#the-scanner-session)).

**The decoder of `spec`** (`synth.events`) follows the specification and the
slides. An RF event with no time shape is cells of the RF raster, each sample at
the centre of its cell. An RF time shape whose times are `(i + 0.5) d`
(`model.rf_time_step`) is cells of `d` (slide 9); any other is points at its
times, joined by straight lines of the complex signal, the linear interpolation
that the C++ reader names as its intent (its FIXME, `ExternalSequence.cpp:2033`)
but does not do. `RfEvent.dwell` is the dwell of cells, or None for points, and
`RfEvent.signal(times)` gives the complex signal at any times. An arbitrary
gradient is a straight line between its samples (at the cell centres for time ID
0; all the samples, half a raster apart, for time ID -1; the vertices of a time
shape), from `first` to `last` (`seq_utils.gradient_offsets`). An ADC phase
modulation is in rad, one value for each sample. The model is made of
`model.Rasters`, `model.Shape`, `model.Signature` and `model.Extensions`;
`model.TABLE_DTYPES` has the dtype of each table, and `model.decompress_shape`
decompresses a shape. `spec.RANGE_TOLERANCE`, `spec.TOLERANCE_NS`,
`spec.FIRST_TIME_TOLERANCE`, `spec.RATIO_TOLERANCE` and `model.TIME_TOLERANCE`
are the limits of its rules.

**The contract with pulseq-checks.** The "as written" reading, the
reading of a plugin (`SequenceData.reading`), the protocols `Plugin` and `Decoding`, the
decoding of each interpreter (`gradients_at`, `gradient_points`, `rotations` and `rotation_record`
included), the codes of the rejections, and the model of each interpreter are public, and kept
stable for pulseq-checks (section 7.3 of the plan). The codes of `cpp-siemens` are
`pulseq_cpp_siemens.interpreter.CODES`. A change to any of them is noted in `CHANGELOG.md`.

### The scanner session

The scanner's interpreter acts on inputs that are not in the file. A
`synth.Session` (module `scanner`) gives them to a decoding, the same for each
interpreter (section 7.8 of `docs/plans/parser-redesign.md`, rules 3 to 8):

```python
from pulseq_analysis.synth import Session

session = Session(
    soft_delays={"TE": 5e-3, "TR": 2.0},  # s, by the hint of the soft delay
    fov_rotation=(0.7071068, 0.7071068, 0, 0),  # q0, qx, qy, qz: 90 degrees about x
    gradient_scaling=(1.0, 1.0, 2.0),  # x, y, z, each above 0
)
snap = load("my_sequence.seq", session=session)
```

- **The neutral session** `Session()` is the default: each block at its stored
  duration, and the field of view at the isocentre, not rotated or scaled. It is
  a defined case (rule 1), recorded and not warned about. `Session.neutral`,
  `rotates` and `scales` say what is set. A session is frozen, compares by value
  and keeps `soft_delays` as (hint, value) pairs sorted by hint. A value that is
  not a number, a quaternion whose norm is not 1 within 1e-6 (it is divided by
  its norm), and a scaling of 0 or below raise `ValueError` or `TypeError`; a
  setting that the session does not have raises `TypeError`.
- **Soft delays** (extension DELAYS, from 1.5.0). The duration of a block whose
  soft delay has a value is `value / factor + offset` (spec:550-563) on the
  block duration raster, rounded half away from 0, as MATLAB Pulseq's
  `applySoftDelay` rounds it (D2.21). `scanner.SettingError` (a `ValueError`
  that names the setting, the interpreter, the file's version and the reason)
  is raised when the setting addresses something that the file does not have
  under the interpreter: no soft delay with that hint, a file older than 1.5.0
  under `spec`, a hint whose rows have two numeric IDs (or whose numeric ID has
  another hint), a block with that hint that has an RF, gradient or ADC event
  (spec:545) or two soft delays, and a duration below 0. `soft_delay_record`
  (`scanner.SoftDelayRecord`) has the values, the hints of the file, the blocks
  with a soft delay, those that the session set (`applied`) and the hints at
  their stored durations (`unset`).
- **The field of view.** The gradients of each block are scaled on the logical
  axes, then turned by the block's rotation, then by the rotation of the field
  of view: R_fov R_block S g, the order of MATLAB Pulseq's `mr.TransformFOV`.
  No source gives the order of the scanner's interpreter (D2.20). A block whose
  flag NOROT is set is not turned by the field of view, and a block whose scaling
  flag is set is not scaled. The flags are a state: a LABELSET sets a flag for
  its block and the blocks after it. The scaling flag of `spec` is `NOSLC`, the
  specification's spelling, from 1.4.1; `NOSCL`, the spelling of the C++
  reader, MATLAB Pulseq and pypulseq, is a label that `spec` does not know
  (D2.19, D2.22). `cpp-siemens` applies `NOSCL`, which its reader keeps.
  `fov_record` (`scanner.FovRecord`) has the rotation, the scaling, the name of
  the scaling flag, the blocks with each flag, and the blocks rotated and
  scaled.
- **The stored and the actual durations.** A decoding gives both
  (`stored_block_durations`, `block_durations`); `gradients_at` is 0 after the
  actual end of a block, and the block table and the measurements use the
  actual durations.

The simulation is the package's own, shared by the interpreters (rule 6):
`scanner.soft_delay_durations`, `scanner.fov_flags`,
`scanner.physical_gradients` and `scanner.fov_record`, with `scanner.SoftDelay`
for the soft delays that an interpreter attaches to its blocks,
`scanner.pure_delay_blocks` for the pure delay blocks, and
`scanner.block_physical_gradients` and `scanner.rotation_rows` for the
gradients of the blocks of a call of `gradients_at`. A plugin applies
the session in its own decoding, with its reader's hooks where they exist;
`cpp-siemens` sets the duration of a block with the reader's
`setActualSoftDelay_ru`, and turns the gradients with the reader's
`rotate_vec3_by_quat` (`packages/pulseq-cpp-siemens/docs/specification.md`,
D6.3 and D6.4).

### A pypulseq sequence in memory

`seqfile.read_pypulseq(seq, interpreter="spec")` (also
`from_pypulseq.read_pypulseq`) reads a `pypulseq.Sequence` built in memory
through an interpreter, by name or as an object, as `read_seqfile` reads a
file. It writes the sequence to Pulseq text with pypulseq's own writer, so what
it reads is what the scanner would receive from `seq.write(path)`, the writer's
rounding included. The result is the `SequenceData` that `read_seqfile` gives
for that file, with `origin` `"pypulseq"` in place of `"file"`.
A `pypulseq.Sequence` needs the extra `pypulseq` ([Install](#0-install)).

```python
from pulseq_analysis.seqfile import read_pypulseq

data = read_pypulseq(seq)  # interpreter="spec", the default
cpp = read_pypulseq(seq, interpreter="cpp-siemens")  # a plugin: needs pulseq-cpp-siemens
```

- **The writer's options** are those of `seq.write(path)`, except the timing
  check: the text has its `[SIGNATURE]` section (`create_signature=True`, read
  into `SequenceData.signature`), the duplicate events and shapes are merged
  (`remove_duplicates=True`), and the version is the one that pypulseq writes.
  pypulseq's timing check is not run (`check_timing=False`): the package does
  not check a sequence, and the interpreter reads or rejects it. pypulseq's
  warning about a gradient that does not ramp down in the last block is not
  suppressed.
- **The sequence is not changed.** `seq.write` sets the definition
  `TotalDuration` and the signature fields of the sequence that it writes, so
  `read_pypulseq` writes a copy (`seq.remove_duplicates()`, the deep copy that
  `seq.write` also makes).
- **The text goes to a private temporary folder**, never next to your files,
  and the folder is removed after the reading.
- **It raises** what `read_seqfile` raises. A `SeqFileError` has
  `from_pypulseq.SOURCE` (`"<pypulseq.Sequence>"`) as its `path`, in place of the
  temporary file. An exception of pypulseq's writer (for example for an event
  that it cannot write) is raised as it is, and an object that is not a
  pypulseq sequence raises `TypeError`.

`load(seq, interpreter)` uses it: the snapshot of a sequence is that of its
text. A sequence that pypulseq cannot write, or whose `remove_duplicates`
fails, raises pypulseq's exception: pypulseq 1.5.0.post1 raises `KeyError` for
an oversampled arbitrary gradient (time ID -1) in `remove_duplicates`.

### The "as written" reading

`seqfile.read_as_written(path)` (also `as_written.read_as_written`) reads a
Pulseq text file as written: its bytes into sections and typed fields, with
line numbers, without loss and without interpretation. It returns an
`as_written.AsWritten`. It reads every file, whatever the version or the
errors in it, and raises only `OSError` when the file cannot be read. It
applies no rule of the specification and no default; the interpreters read
the file through it. pulseq-checks compares it with
what an interpreter read, so its types are part of the contract between the two
projects: a change to them is noted in `CHANGELOG.md`.

```python
from pulseq_analysis.seqfile import read_as_written

written = read_as_written("sequence.seq")
written.version  # (1, 5, 1), or None
(blocks,) = written.named("BLOCKS")
blocks.rows.values["duration_ticks"]  # int64, as written (units of BlockDurationRaster)
blocks.rows.valid["duration_ticks"]  # False where the field is not an int, or missing
blocks.rows.lines  # the line of each row
blocks.blank, blocks.comments  # the blank and `#` lines of the section
```

**Lines and sections.** The text is split at each `\n` only; line numbers start
at 1. A line is blank (only white space), a comment (its first character that
is not white space is `#`), a header (`[NAME]`, or `extension STRING_ID type`)
or data. A section runs from its header to the line before the next header: a
blank or `#` line does not end it, and the rows after it belong to the section.
Which rows a reader takes is the reader's choice (`spec` skips a blank or `#`
line anywhere; the C++ reader ends a table at a blank line and reads a `#` line
as a row; MATLAB's `read.m` ends a section at either). A byte that is not UTF-8 is kept,
as a lone surrogate in its line, and `AsWritten.not_utf8` gives the offset of
the first one.

| `AsWritten` | Meaning |
|---|---|
| `path`, `raw` | The path as given, and every byte of the file. |
| `not_utf8` | The offset of the first byte that is not UTF-8, or None. |
| `line_count` | The number of lines. A file that ends with `\n` ends with an empty line. |
| `preamble` | The lines before the first header, as a `Section` with no header (`line` 0). |
| `sections` | Each `Section` in file order, as many times as the file has it. |
| `version` | (major, minor, revision) of the first `[VERSION]` section: for each key, its first row of two fields with an int; None if a key has none. It picks the columns of `[RF]`, `[GRADIENTS]` and `[ADC]`: those of 1.4 below 1.5.0, else those of 1.5. |
| `named(name)`, `extensions()` | The sections `[name]`, and the `extension` sections, in file order. |
| `signed_bytes()` | The bytes that the `[SIGNATURE]` hash covers by the specification (section 2.4): every byte before the first `[SIGNATURE]` header line, without the `\n` right before it. None with no such header. The C++ reader hashes other bytes in a CRLF file (`docs/discrepancies.md`). |

| `Section` | Meaning |
|---|---|
| `line`, `header` | The line of the header, and the header with its white space stripped. |
| `name` | For `[NAME]`, the text between the brackets as written; None for a header with no `]` at its end, an `extension` header, and the preamble. |
| `extension`, `extension_type` | For an `extension` header, its fields after the word `extension`, and the second of them as an int (or None); None for another header. |
| `end` | The last line of the section. |
| `rows` | Its data lines, a `Table`. In `[SHAPES]`, the lines that are not the `shape_id` or `num_samples` line of a shape. |
| `blank`, `comments` | Its blank lines and `#` lines, each an `as_written.Line` (`number`, `text`). |
| `shapes` | In `[SHAPES]`, each `ShapeWritten`; empty in another section. |

**Fields.** Each row is split at white space (`str.split`). A column of a
table is an `as_written.Column` (`name`, `kind`), and a field's value is read
by its column's kind: `int` (an optional sign and digits, in the range of a
signed 64-bit integer: `+30` is 30), `float` (an optional sign and a decimal
number with an optional exponent, or `nan`, `inf` or `infinity` in any case:
`1e999` is infinite) or `text`. A field that is not of its kind, or that a row
lacks, is not valid, and its value is 0, NaN or "". The columns have the names
of `model.SequenceData` and the units of the file (µs, and ns for the ADC
dwell time); `[VERSION]` has `key` and `value` (int), `[DEFINITIONS]` has
`key` and its values as text, and `[SIGNATURE]` has `key` and `value`. A
section that the format does not have, an unknown extension and the preamble
have no column: each field is text. The docstring of `as_written` lists every
column.

| `Table` | Meaning |
|---|---|
| `columns`, `extra` | The columns, and the kind of the fields after the last column (`float` in `extension RF_SHIMS`, else `text`). |
| `lines` | int64: the line of each row. |
| `counts` | int64: the number of fields of each row. |
| `values` | A structured array, one field for each column: the value of each row's field by kind (int64, float64, or str as wide as the longest text). |
| `valid` | A structured array of bool, one field for each column: the row has the field, and it is of the column's kind. |
| `text` | The rows as written, joined with `\n`. |
| `row(i)`, `fields(i)`, `cells(i)` | The text of row `i`, its fields, and the value of each of its fields by kind (None where it is not of its kind), the fields after the last column included. |

**Shapes.** In `[SHAPES]`, a data line whose first field is `shape_id` starts
a `ShapeWritten`, and the line right after it is its `num_samples` line when
the first field of that line is `num_samples`. The other data lines are the
rows of the section, with one column `sample` (float).

| `ShapeWritten` | Meaning |
|---|---|
| `line`, `fields` | The `shape_id` line (a `Line`) and its fields. |
| `id` | The second field of that line as an int, or None. |
| `num_samples_line`, `num_samples` | The `num_samples` line, and its second field as an int; None if there is none. |
| `rows` | A `range` of row indices of `Section.rows`: the rows after these lines, up to the next `shape_id` line or the end of the section. A blank line does not end them here. |

Every array of the reading is read-only. On an Apple M1 Max, a file of 21 MB
with 916 266 blocks takes about 0.3 s to read as written.

### The model

An interpreter reads a file into a `seqfile.model.SequenceData` (`snap.data`):
what the file defines, as plain read-only values. IDs are those of the file, with
no renumbering. A time is in s, an RF amplitude in Hz, a gradient amplitude in
Hz/m and a phase in rad, converted from the units of the file. No value of a
target (gamma, dead times, limits) is in it. `SequenceData` is a frozen
dataclass. Its arrays are read-only and cannot be made writable again, its
mappings are `types.MappingProxyType` and its sequences are tuples. Two models are
equal (`==`) when each field is equal (a NaN equals a NaN); a model can be pickled
and copied, and is not hashable. The fields:

| Field | Type | Meaning |
|---|---|---|
| `version` | `tuple[int, int, int]` | The version of the file: major, minor, revision. |
| `definitions` | read-only mapping from `str` to `tuple[str, ...]` | The tokens of each line of `[DEFINITIONS]`, as text: no value is converted to a number. The rasters are in `rasters`. |
| `rasters` | `model.Rasters` | `gradient`, `rf`, `adc` and `block_duration`: the four rasters of `[DEFINITIONS]` in s (`GradientRasterTime`, `RadiofrequencyRasterTime`, `AdcRasterTime`, `BlockDurationRaster`). |
| `required_extensions` | `tuple[str, ...]` | The STRING_IDs of the definition `RequiredExtensions`. |
| `blocks` | structured array | One row for each block, in file order, which is play order. The fields (all int64) are `id`, `duration_ticks` (in units of `BlockDurationRaster`), `rf`, `gx`, `gy`, `gz`, `adc` (the ID of the event of the block, 0 for none) and `ext` (the ID of the first entry of the block's extension list in `extensions.entries`, 0 for none). |
| `rf` | structured array | One row for each RF event: `id`, `amplitude` (Hz), `mag_id`, `phase_id`, `time_id` (0 is the default raster), `center` (s), `delay` (s), `freq_ppm` (ppm), `phase_ppm` (rad/MHz), `freq_offset` (Hz), `phase_offset` (rad) and `use` (one of `e r i s p o u`). |
| `grad` | structured array | One row for each arbitrary gradient of `[GRADIENTS]`: `id`, `amplitude` (Hz/m), `first` and `last` (Hz/m, the values at the start and at the end), `shape_id`, `time_id` (0 is the default raster, -1 is half of it) and `delay` (s). |
| `trap` | structured array | One row for each trapezoid of `[TRAP]`: `id`, `amplitude` (Hz/m), `rise`, `flat`, `fall` and `delay` (s). `grad` and `trap` share one ID space. |
| `adc` | structured array | One row for each ADC event: `id`, `num_samples`, `dwell` (s), `delay` (s), `freq_ppm`, `phase_ppm`, `freq_offset` (Hz), `phase_offset` (rad) and `phase_shape_id` (0 is no modulation). |
| `shapes` | read-only mapping from `int` to `model.Shape` | The shapes by shape ID. A `Shape` has `num_samples` and `packed`, the values as the file stores them (compressed or not). `Shape.samples()` gives the decompressed samples, a new float64 array. |
| `extensions` | `model.Extensions` | The extensions of the file (`model.Extensions`, below). |
| `skipped_extensions` | `tuple[str, ...]` | The STRING_IDs of the extensions that the interpreter does not know. It does not read their rows. |
| `records` | `tuple[model.Record, ...]` | What the interpreter ignored, in file order ([Records](#the-interpreters)). `cpp-siemens` records an extension or a label that its reader does not know. |
| `signature` | `model.Signature` or `None` | The `[SIGNATURE]` section: `type` (for example `"md5"`), `hash` as in the file, and `matches`, which says whether `hash` is the hash of the file (`None` when it cannot be known, for an algorithm that `hashlib` does not have). `None` when the file has no `[SIGNATURE]` section. |
| `origin` | `str` | `"file"`, or `"pypulseq"` for a sequence in memory that `read_pypulseq` wrote and read. |
| `interpreter` | `Spec` or a plugin interpreter | The interpreter that read the file, with its settings. |
| `reading` | `Any` | For a plugin, its own object for the file, which its decoding uses (opaque to the package; `None` for `spec`). `==` does not compare it. |

`SequenceData.block_durations_s` is the stored duration of each block in s:
`duration_ticks` times `rasters.block_duration`. The duration under a scanner
session is `snap.decoding.block_durations` ([The decoding](#the-interpreters)).

In a 1.4.x file, the model has the 1.5 layout with these values: RF `freq_ppm`
and `phase_ppm` are 0, `use` is `u` (undefined) and `center` is NaN (the format
has no center), and ADC `freq_ppm`, `phase_ppm` and `phase_shape_id` are 0.
The `first` and `last` of a gradient with a time shape (`time_id` above 0) are the
amplitude times the first and the last sample of the shape.

**`model.Extensions`.** `entries` is the table of `[EXTENSIONS]` (`id`, `type`,
`ref`, `next`; `next` 0 ends a list). `type_ids` maps the STRING_ID of each
`extension` section of the file, known or not, to its type ID in this file. Each of
the other fields is the table of one extension, empty when the file has none:

| Field | Extension | Fields of a row |
|---|---|---|
| `triggers` | TRIGGERS | `id`, `type`, `channel`, `delay` and `duration` (s) |
| `labelset` | LABELSET | `id`, `value`, `name` |
| `labelinc` | LABELINC | `id`, `value`, `name` |
| `soft_delays` | DELAYS | `id`, `num`, `offset` (s), `factor`, `hint` |
| `rotations` | ROTATIONS | `id`, `q0`, `qx`, `qy`, `qz`: the quaternion, divided by its norm |
| `rf_shims` | RF_SHIMS | a read-only mapping from the object ID to an array with one row for each channel: the magnitude and the phase |

The model of a plugin has the same fields. It fills the tables in its own way, so
it differs from the model of `spec` where the plugin says so: for `cpp-siemens`,
the paragraph "The model" of `packages/pulseq-cpp-siemens/README.md`. For example,
the reader keeps no block ID, so `blocks["id"]` of `cpp-siemens` is the position in
play order, from 1.

### The events

`synth.events` decodes the tables of the model of `spec` into events with
fields. `decode_rf(data)`, `decode_gradients(data)` and `decode_adc(data)` take
the `SequenceData` of the interpreter `spec` (`snap.data`) and give a read-only
mapping (`types.MappingProxyType`) from the **ID of the file** to the event. They
give every row of the table, whether a block uses it or not, in the order of the
table; `decode_gradients` gives the rows of `[GRADIENTS]` first, then those of
`[TRAP]`, as the two share one ID space. The decoding of the snapshot has the
same gradient events: `snap.decoding.gradients` is equal to the result of
`decode_gradients`, and `load` made it once (each call of a `decode_*` function
decodes again). `load` decodes no RF or ADC event, which no measurement reads:
`decode_rf` and `decode_adc` decode them.

```python
from pulseq_analysis.analyses import load
from pulseq_analysis.synth.events import decode_adc, decode_gradients, decode_rf

snap = load("sequence.seq")
rf = decode_rf(snap.data)  # {RF ID: RfEvent}
grad = decode_gradients(snap.data)  # {gradient ID: Trapezoid or ArbitraryGradient}
adc = decode_adc(snap.data)  # {ADC ID: AdcEvent}

# The events of a block: the block table has their IDs, 0 for none.
row = snap.decoding.blocks[0]  # play index 0
pulse = rf[int(row["rf"])] if row["rf"] else None
gx = grad[int(row["gx"])] if row["gx"] else None
readout = adc[int(row["adc"])] if row["adc"] else None
```

The keys are the IDs of the file, not the numbers of the block table
(`sequence_index`). The block table of the decoding (`snap.decoding.blocks`, the
`blocks` table of the model) gives the IDs of the events of each block, in play
order. A key that the file does not have raises `KeyError`.

Each event is a frozen dataclass. Its arrays are read-only, two events are equal
(`==`) when each field is equal, and an event can be pickled. A time is in s from
the start of the event, which is after its `delay`. The events are as the file
defines them: the decoding of the scanner session, and the rotation of a block,
are not applied. No value of a target (gamma, dead time, ringdown time) is used.
`AdcEvent.delay` is the delay as written in the file: no dead time is added.

`events.RfEvent`:

| Field | Meaning |
|---|---|
| `id` | The RF ID. |
| `amplitude` | Hz. |
| `mag_id`, `phase_id`, `time_id` | The IDs of the magnitude, phase and time shapes (`time_id` 0 is the default raster). |
| `magnitude` | The amplitude times the magnitude shape, as written (a negative sample stays negative), at the times `t` (Hz). |
| `phase` | 2 pi times the phase shape, as written, with no wrap, at the times `t` (rad). |
| `t` | The time of each sample (s). |
| `dwell` | The dwell of a pulse of cells (s), or `None` for a pulse of points. |
| `shape_dur` | The duration of the pulse after the delay (s). |
| `center` | The center of the pulse in s, or `None` for a file of version 1.4, which has no center. |
| `delay` | s. |
| `freq_ppm` | ppm. |
| `phase_ppm` | rad/MHz. |
| `freq_offset` | Hz. |
| `phase_offset` | rad. |
| `use` | One character as in the file (`e r i s p o u`), or `u` for a file of version 1.4. |

`RfEvent.signal(times)` gives the complex signal `magnitude * exp(1j * phase)`
(Hz) at `times` (s from the start of the event), without the offsets. It is 0
outside the pulse. How `t`, `dwell` and `shape_dur` follow from the shapes is in
[The decoder of `spec`](#the-interpreters).

`events.Trapezoid`, for a row of `[TRAP]`:

| Field | Meaning |
|---|---|
| `id` | The gradient ID. |
| `amplitude` | Hz/m. |
| `rise_time`, `flat_time`, `fall_time` | s. |
| `delay` | s. |

`Trapezoid.shape_dur` is the sum of the three times (s), and `Trapezoid.first`
and `Trapezoid.last` are 0.0 (Hz/m).

`events.ArbitraryGradient`, for a row of `[GRADIENTS]`:

| Field | Meaning |
|---|---|
| `id` | The gradient ID. |
| `amplitude` | Hz/m. |
| `shape_id` | The ID of the shape of the waveform. |
| `time_id` | 0 is the default raster, -1 is half of it (an oversampled gradient), above 0 is the ID of a time shape. |
| `waveform` | The amplitude times the samples of the shape (Hz/m). |
| `tt` | The time of each sample (s). |
| `shape_dur` | The duration after the delay (s). |
| `first`, `last` | The amplitude at the start and at the end of the event (Hz/m), from the model. |
| `delay` | s. |

Between its points, a gradient is straight lines: `seq_utils.gradient_offsets`
gives the points of an event of either kind. `events.GradEvent` is
`Trapezoid | ArbitraryGradient`.

`events.AdcEvent`:

| Field | Meaning |
|---|---|
| `id` | The ADC ID. |
| `num_samples` | The number of samples. |
| `dwell` | s. |
| `delay` | s, as written. |
| `freq_ppm` | ppm. |
| `phase_ppm` | rad/MHz. |
| `freq_offset` | Hz. |
| `phase_offset` | rad. |
| `phase_shape_id` | The ID of the phase modulation shape (0 is no modulation). |
| `phase_modulation` | The shape in rad, one value for each sample, or `None` when `phase_shape_id` is 0. |

The three functions refuse the model of a plugin: `TypeError` for a
`SequenceData` whose `interpreter` is not `Spec`, for example the data of
`cpp-siemens`. The decoding of a plugin is its own (`snap.decoding`,
[The interpreters](#the-interpreters)).

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
the oracles.

**The limits of a scanner.** Convert the values to the unit of the limits, or
convert the limits to the unit of the values. pypulseq's `Opts` keeps
`max_grad` in Hz/m and `max_slew` in Hz/m/s, converted with its own gamma.
Thus the `Opts` of a target gives limits in the units of the values of
`gradient_peaks` ([section 3](#3-the-gradient-peaks)).

The arrays of a result are read-only. Convert an array to a new array
(`(s.rss / abs(gamma)) * 1e3`, `(levels.level_max_hz_per_t / abs(gamma)) * 100`).
Do not change it in place: `s.rss *= 1e3 / abs(gamma)` raises `ValueError`.
