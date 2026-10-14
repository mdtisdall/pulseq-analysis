# What `cpp-siemens` does, and why

`cpp-siemens` is the interpreter of pulseq-analysis that this package gives
(`pulseq_cpp_siemens.interpreter`). It reads a Pulseq file as the C++ reader of the scanner's
interpreter on Siemens systems reads it. This document gives its rule (section 1) and each
exception to the rule (section 2), with the reason.

The C++ reader is `src/ExternalSequence.cpp` and `.h` of
[pulseq/pulseq](https://github.com/pulseq/pulseq) at `c7469123` (`pulseq-reader.sha256`), cited as
`cpp:N` and `cpp.h:N`. The IDs (D5.1, D6.2, …) are those of the records of pulseq-analysis. An ID
names a decision, not a condition: a condition on which each interpreter decides has two IDs, and
the entries link to each other. D1 to D4 are the decisions of `spec`, in
[`docs/discrepancies.md`](../../../docs/discrepancies.md), where D4.1 (the version gate) is the
decision of both interpreters; D5 to D7 are the decisions of `cpp-siemens`, here. The appendix of
`docs/discrepancies.md` maps the old IDs (D01a to D60) to these. P1 to P22 and Q1 to Q6 are the
decisions of `docs/plans/parser-redesign.md` of pulseq-analysis. Fixtures named without a folder
are in `tests/seqfiles/` of pulseq-analysis.

## 1. The rule

`cpp-siemens` gives what the C++ reader gives, and rejects what it rejects (P1, P2, P14): its
waveforms, its float32 values (P6), and its misreadings of a row (P3, for example a soft delay
offset with a fraction, which `spec` decides in
[D2.16](../../../docs/discrepancies.md#d216-a-soft-delay-offset-with-a-fraction-or-a-long-hint)).

Why: the reader is what the scanner plays. The engine of `cpp-siemens` is the reader itself,
compiled unchanged into this package's extension (P11), so the rule holds by construction. `read`
runs `decodeBlock` on every block (P19), so a block that the reader rejects at play time rejects
the file when it is read.

## 2. The exceptions

### 2.1 The version gate

#### D4.1: A version before 1.4.0 or from 1.6.0 (both interpreters)

D4.1 is the decision of both interpreters; its record is in
[`docs/discrepancies.md`](../../../docs/discrepancies.md#d41-a-version-before-140-or-from-160-both-interpreters).

- Condition: a file whose version is before 1.4.0 or from 1.6.0.
- The reader: ports 1.2 and 1.3 files (`cpp:1656-1711`) and reads 1.6.0 with the 1.5 layouts (no
  upper bound, `cpp:918-922`).
- `cpp-siemens`: raises `NotSupported` before the reader runs, and also for a binary file or a
  folder.
- Why: the package reads 1.4.0 to 1.5.x only (Q1), and a version it does not know must fail
  loudly, not be read wrongly. The gate must come first: for a file older than 1.4.0, `load` itself
  calls `GetBlock` on each block (`cpp:1656-1663`), before the checks of section 2.2 can run.
- Fixtures: `bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq`.

### 2.2 The undefined behaviour of the reader

In each case below the reader reads or writes memory that it does not own, reads an
indeterminate value, or never ends. `cpp-siemens` rejects the file with a `ub.*` code
(`UndefinedBehaviour` in this package, a `SeqFileError` in pulseq-analysis), whose `entry` is the
ID of the case. The checks (`_checks.py`) run on the libraries after `load`, before any `GetBlock`
or `decodeBlock`.

Why (Q2, for each case): the reader has no single behaviour to follow (the same file crashes one
build and reads in another), and it runs in this process, where a bad write or an endless loop
under its lock would harm every later read.

#### D5.1: A block uses a shape that the reader did not read

- Code: `ub.shape-missing`.
- Condition: a block uses a shape that the reader did not read. This happens when the shape ID is
  not in `[SHAPES]`, also after a `[VERSION]` section that is last in the file (the reader then
  reads no shape at all), and after a shape with no blank line after it.
- The reader: a null reference (`cpp:1995`, `cpp:2177`).
- `cpp-siemens`: rejects the file with `ub.shape-missing`. When the library holds no shape, the
  message asks whether `[VERSION]` is the last section.
- Fixtures: `bad_ref_shape.seq`, `bad_ref_time_shape.seq`, `bad_syntax_shape_no_blank_line.seq`,
  `undefined/version_last.seq`.

The same conditions in `spec`: [D2.1](../../../docs/discrepancies.md#d21-sections-in-any-order)
(sections in any order, so `[VERSION]` last),
[D3.11](../../../docs/discrepancies.md#d311-a-shape-with-no-blank-line-after-it).

#### D5.2: A `[GRADIENTS]` row of shape ID 0 that a block uses

- Code: `ub.gradient-shape-0`.
- Condition: a `[GRADIENTS]` row of shape ID 0 that a block uses.
- The reader: plays an uninitialised `GradEvent` as a trapezoid (`cpp:1069`).
- `cpp-siemens`: rejects the file with `ub.gradient-shape-0`. A row of shape 0 that no block uses
  is read.
- Fixture: `tests/fixtures/gradient_shape_0.seq`.

#### D5.3: An RF event with time ID -1

- Code: `ub.rf-time-id-minus-1`.
- Condition: an RF event with time ID -1.
- The reader: looks up time shape -1, which does not exist (`cpp:2026`).
- `cpp-siemens`: rejects the file with `ub.rf-time-id-minus-1`.
- Fixture: `undefined/rf_time_id_minus_1.seq`.

The same condition in `spec`: [D4.3](../../../docs/discrepancies.md#d43-time-id--1-in-a-14-file).

#### D5.4: A cycle in an extension list

- Code: `ub.extension-cycle`.
- Condition: a cycle in an extension list.
- The reader: never ends, holding the reader's lock (`cpp:1849-1928`).
- `cpp-siemens`: rejects the file with `ub.extension-cycle`.
- Fixture: `bad_ref_extension_cycle.seq`.

#### D5.5: A shape that decompresses to more samples than it declares

- Code: `ub.shape-decompression`.
- Condition: a shape that decompresses to more samples than `num_samples`, or ends in a repeat
  with no count.
- The reader: writes past its buffer (`cpp:2231`), or reads past the stored values (`cpp:2222`).
- `cpp-siemens`: rejects the file with `ub.shape-decompression`. A shape that decompresses to
  fewer samples is read as the reader reads it: the samples that it does not write keep the
  values of its buffer, before the cumulative sum. The reader decompresses the shapes of the
  gradients of a block into one buffer (`cpp:2099-2110`, `cpp:2161-2190`), so these values come
  from the shape decompressed before it in the block (in a new buffer they are 0, and the sum
  repeats the last value). `cpp-siemens` follows the reader, and gives such a gradient event a
  variant for each set of events on the earlier axes of its block
  (`CppSiemensDecoding.gradient_variants`).
- Fixtures: `undefined/shape_decompress_longer.seq`,
  `tests/fixtures/shape_decompress_count_missing.seq`.

#### D5.6: An event that uses a shape with no sample

- Code: `ub.shape-empty`.
- Condition: an event uses a shape with no sample.
- The reader: element 0 of an empty vector (`cpp:1995`, `cpp:2203`).
- `cpp-siemens`: rejects the file with `ub.shape-empty`.
- Fixture: `bad_shape_empty.seq`.

The same condition in `spec`: [D3.7](../../../docs/discrepancies.md#d37-an-event-that-uses-a-shape-with-no-sample).

#### D5.7: An RF phase shorter than its magnitude

- Code: `ub.rf-shape-lengths`.
- Condition: an RF phase shorter than its magnitude.
- The reader: `checkRF` reads past the phase (`cpp:2288`).
- `cpp-siemens`: rejects the file with `ub.rf-shape-lengths`. A longer RF phase is read, and the
  reader plays the magnitude's length.
- Fixture: `bad_shape_event_length.seq`.

The same condition in `spec`: [D3.8](../../../docs/discrepancies.md#d38-the-shapes-of-one-event-with-different-numbers-of-samples).

#### D5.8: The RF resampling reads past the samples

- Code: `ub.rf-time-overrun`.
- Condition: the RF resampling reaches the number of samples.
- The reader: reads one past the samples (`cpp:2039-2045`).
- `cpp-siemens`: rejects the file with `ub.rf-time-overrun`. An RF time shape that the resampling
  reads within its samples is resampled, artefacts included (P5).
- Fixtures: `bad_shape_rf_time_end.seq`, `valid_rf_time_shapes.seq`.

The same condition in `spec`:
[D2.11](../../../docs/discrepancies.md#d211-any-other-rf-time-shape-points),
[D3.9](../../../docs/discrepancies.md#d39-an-rf-time-shape-of-one-sample-or-times-that-do-not-increase-or-start-below-0).

#### D5.9: An RF time shape whose last time does not fit an int

- Code: `ub.rf-time-range`.
- Condition: an RF time shape whose last time does not fit an `int`.
- The reader: an undefined conversion (`cpp:2031`).
- `cpp-siemens`: rejects the file with `ub.rf-time-range`.
- Fixture: `tests/fuzz_corpus/rf-time-range.seq`.

The same condition in `spec`: [D2.11](../../../docs/discrepancies.md#d211-any-other-rf-time-shape-points).

#### D5.10: An extended trapezoid of one point at a time above 0

- Code: `ub.gradient-one-point`.
- Condition: an extended trapezoid of one point at a time above 0, with an amplitude that is not
  0, in a block that `gradientsAt` samples at a time `t` with `max(delay, 0) <= t`,
  `t < delay + times[0]` and `t <= GetDuration()`. `GetDuration()` is the stored duration of the
  block, or the value of the hook `setActualSoftDelay_ru` when one is set (`ExternalSequence.h:705`):
  that value replaces the stored duration, it is not added to it.
- The reader: `gradientsAt` reads `times[1]` and `wave[1]`, past both vectors (`cpp:3639-3650`).
  The binary search starts with upper = 1 and does not run.
- `cpp-siemens`: rejects the file with `ub.gradient-one-point` when such a time is in the stored
  duration of the block (`max(delay, 0)` is not after it). A one-point extended trapezoid at
  time 0 is read. When `max(delay, 0)` is after the stored duration, `load` reads the file and
  keeps the interval from `max(delay, 0)` to `delay + times[0]` of the block;
  `Sequence.gradients_at(..., actual_ru=...)` then raises `UndefinedBehaviour`
  (`ub.gradient-one-point`, with the block and the time) for each pair of a block and a time in
  that interval and not after the soft delay times the block raster, before the reader runs.
  The other pairs give the reader's values.
- Fixtures: `tests/fixtures/gradient_one_point.seq` (in the stored duration) and
  `tests/fixtures/gradient_one_point_after_block.seq` (the delay of 200 us after the 100 us of
  the block).

#### D5.11: An extended trapezoid time that does not fit a long

- Code: `ub.gradient-time-range`.
- Condition: an extended trapezoid time that does not fit a `long`.
- The reader: an undefined conversion (`cpp:2182`).
- `cpp-siemens`: rejects the file with `ub.gradient-time-range`.
- Fixture: `tests/fuzz_corpus/gradient-time-range.seq`.

### 2.3 Settings of the scanner

The reader applies nothing that the scanner's interpreter decides, and has modes that the
scanner can set. `cpp-siemens` gives the reader's output with the reader's defaults, and offers
settings for the rest (P7, P18, P20). The inputs of the scanner session (`pulseq_analysis.synth.Session`)
are not settings: `decode(data, session)` applies them (P22; D6.3, D6.4). A result records the
settings it used and what it applied of the session.

#### D6.1: An oversampled arbitrary gradient: the reader's sampling mode

- Condition: an oversampled arbitrary gradient (time ID -1).
- The reader: keeps the samples at the centres of the raster by default (`cpp:103`,
  `cpp:2123-2135`); the scanner can set another mode (`cpp.h:978-991`).
- `cpp-siemens`: `CppSiemens(oversampling=...)` is that mode: `"center"` (the default), `"edge"`
  or `"preserve"`.
- Why: each mode is the reader's own, and the scanner can choose any.
- Fixture: block 3 of `oracle/koma_v1.5_spiral.seq` has 2112, 2111 and 4223 samples in the three
  modes.

#### D6.2: A block that plays a rotation

- Condition: a block that plays a rotation (the ROTATIONS extension).
- The reader: attaches each block's first rotation, divided by its norm (`cpp:1286-1292`,
  `cpp:1871-1879`), in any version, and never rotates the gradients (`gradientsAt`,
  `cpp:3558-3698`): the scanner does.
- `cpp-siemens`: with `CppSiemens(rotation="reader")`, the default, the gradients are the
  reader's, and the decoding's `rotation_record.warning()` says that a rotation was left
  unapplied. With `rotation="apply"`, `gradients_at` turns each block's gradients by its
  quaternion with the reader's own `rotate_vec3_by_quat`, in any version, as the reader attaches
  it.
- The measurements of pulseq-analysis (`analyses.load`, R14): `load` emits the
  `ScannerSettingWarning` of `rotation_record.warning()`, so a measurement of the default says
  that its gradients are the logical ones; the decoding does not emit it. With `"apply"`, the
  measurements take each rotated block's gradients from `gradients_at`.
- Why: the default is the reader's output (P20); `"apply"` simulates what the scanner plays, with
  the reader's arithmetic. What the scanner does with a rotation in a file older than 1.5.1 is not
  known.

The same condition in `spec`:
[D2.18](../../../docs/discrepancies.md#d218-a-rotation-quaternion-divided-by-its-norm),
[D4.6](../../../docs/discrepancies.md#d46-an-extension-before-the-revision-that-introduced-it).

#### D6.3: The soft delays of a session

- Condition: a scanner session (`pulseq_analysis.synth.Session`) with a value for a soft delay
  hint (the DELAYS extension).
- The reader: attaches the first soft delay of a block's list (`cpp:1900-1907`), as `load` read
  it (an int offset: `-100.5 1 TE` is the offset -100, the factor 0.5 and the hint `1 TE`; at most
  31 bytes of the hint, D2.16 in `spec`), in any version. It never computes the duration: the
  scanner's interpreter sets it on each block with the hook `SeqBlock::setActualSoftDelay_ru`, and
  `GetDuration`, `gradientsAt` (`cpp:3561`) and the reader's other helpers then use it
  (`cpp.h:601-610`, `cpp.h:705-708`). It does not check that the block is a pure delay block.
- `cpp-siemens`: `CppSiemens.decode(data, session)` (P22) computes each duration from the soft
  delays as the reader attaches them (`Sequence.block_soft_delays`), by the shared rule of
  pulseq-analysis (`synth.scanner.soft_delay_durations`: `value / factor + offset` on the block
  duration raster, rounded half away from 0, with the same `SettingError`s as `spec`), and sets it
  with the reader's hook (`Sequence.block_durations_ru`, and `gradients_at(..., actual_ru=...)`,
  which sets it on the block for the call). `block_durations` is then the reader's
  `GetDuration_ru`, `stored_block_durations` its `GetStoredDuration_ru`. A hint that the reader did
  not attach (for example `TE` in `valid_soft_delay_fraction.seq`, whose hint the reader reads as
  `1 TE`) is a `SettingError`. The neutral session sets nothing: each block lasts its stored
  duration, as the reader gives it. `soft_delay_record` records what was applied.
- Why: the session is the scanner's input (rule 3 of P20), the duration is set with the reader's
  own hook, and the rule is shared with `spec` so that the two interpreters agree (rule 6); the
  rule of the scanner's interpreter is not public.
- Fixture: `tests/session/scanner_session.seq` of pulseq-analysis.

The same condition in `spec`:
[D2.21](../../../docs/discrepancies.md#d221-a-soft-delay-value-of-the-session),
[D4.6](../../../docs/discrepancies.md#d46-an-extension-before-the-revision-that-introduced-it).

#### D6.4: The field of view of a session

- Condition: a scanner session with a rotation or a gradient scaling of the field of view, and
  the flags `NOROT`, `NOSCL` and `NOSLC`.
- The reader: has no code that turns or scales the gradients for the field of view. `decodeLabel`
  knows the flags `NOROT` and `NOSCL` (`cpp.h:249-262`, `cpp:2378-2380`) and attaches their
  LABELSET to the block; it does not know `NOSLC`, the specification's spelling (spec:520), and
  leaves it out with "unknown label specification". It reads labels in any version.
- `cpp-siemens`: `gradients_at` gives the gradients on the physical axes in the shared order of
  pulseq-analysis (`synth.scanner.physical_gradients`, D2.20 in `spec`): the session's scaling of
  the logical axes, except in a block with `NOSCL`; the block's rotation, with
  `rotation="apply"`; the session's rotation of the field of view, except in a block with
  `NOROT`. Each rotation is the reader's `rotate_vec3_by_quat`. The flags are a state across
  blocks (`synth.scanner.fov_flags`) from the LABELSET events that `GetBlock` attaches
  (`Sequence.block_label_sets`), in any version. `NOSLC` has no effect, and the model records
  each label that the reader left out (`SequenceData.records`, reason `"unknown"`). `fov_record`
  records what was applied, with the scaling flag `"NOSCL"`.
- Why: the session is the scanner's input, and the flags are those that the reader keeps for the
  scanner's interpreter. The order is the package's own: no source gives the scanner's.
- Fixture: `tests/session/scanner_session.seq` of pulseq-analysis: block 4 (`NOSLC`) is scaled,
  blocks 5 to 8 (`NOSCL`, never set back) are not.

The same condition in `spec`:
[D2.20](../../../docs/discrepancies.md#d220-the-order-of-the-gradient-scaling-the-blocks-rotation-and-the-field-of-view),
[D2.22](../../../docs/discrepancies.md#d222-the-flag-noslc-and-the-writers-noscl),
[D4.7](../../../docs/discrepancies.md#d47-a-label-flag-of-141-in-an-older-file).

### 2.4 The reader's values in the model

`cpp-siemens` gives the model of pulseq-analysis (`SequenceData`), built from the reader's
libraries. Where the reader holds a mark, or no value, the model holds the following. The
decoding (`GetBlock`, `decodeBlock`, `gradientsAt`) is the reader's own and is unchanged.

Why (for each entry below): the model is shared by the interpreters of pulseq-analysis, so each
field must mean the same in all of them (P14, the contract of section 7.3 of the plan).

#### D7.1: Definitions as text

- The reader holds: each definition as text and numbers (`cpp:1432`, `cpp:1445`).
- The model holds: the text; only the four rasters as numbers (a 32-digit hash does not fit a
  double).

The same condition in `spec`: [D2.7](../../../docs/discrepancies.md#d27-a-definition-or-a-signature-hash-whose-text-reads-as-a-number).

#### D7.2: The reader's float32 values, as float64

- The reader holds: `float` amplitudes, offsets and samples.
- The model holds: the same values as float64 (exact).

#### D7.3: A block's id: its position in play order

- The reader holds: no block ID (`cpp:1565`, `cpp:1586`).
- The model holds: `id` = the position in play order, from 1.

#### D7.4: gradients_at between blocks and after a block's end

- The reader holds: events inside one block; `gradientsAt` joins no blocks (`cpp:3561-3566`).
- The model holds: `gradients_at` gives 0 after a block's end and between blocks.
- The measurements of pulseq-analysis (`analyses.load`, R14): each block's events are the
  reader's decoding (`gradient_points`), and a block with an event that goes on after the block's
  end is cut there, as `gradients_at` gives it. Between blocks the measurements use the package's
  waveform, as for `spec` (MATLAB's ramps and lines, `docs/implementation.md` §1.3 of
  pulseq-analysis): the reader gives nothing there.

The same condition in `spec`: [D2.14](../../../docs/discrepancies.md#d214-a-gap-between-two-gradient-events-on-one-axis).

#### D7.5: The center of a 1.4 RF event: NaN

- The reader holds: `center` -1 in a 1.4 RF event, "mark as invalid" (`cpp:1037`).
- The model holds: `center` NaN.

The same condition in `spec`: [D4.2](../../../docs/discrepancies.md#d42-the-rows-of-a-14-file-and-the-rf-center-that-it-does-not-have).

#### D7.6: The ADC phase shape as stored

- The reader holds: the ADC phase shape, used as rad (`cpp:3059-3060`).
- The model holds: the shape as stored, with no factor.

The same condition in `spec`: [D2.15](../../../docs/discrepancies.md#d215-an-adc-phase-modulation-shape-rad-one-value-per-sample).

### 2.5 The codes of the rejections

The reader gives a message, not a code. `cpp-siemens` gives each rejection a stable code, so that
a caller can tell rejections apart (P2). `_classify` finds the code from the reader's message,
and, where the message is not enough, from the "as written" reading of pulseq-analysis. The reader
stops at its first error, so a rejection has one reason, with the reader's message.

| Code | ID | The reader rejects |
|---|---|---|
| `version.missing` | — | no `[VERSION]` section |
| `version.invalid` | — | a `[VERSION]` line that does not decode, or an unknown key |
| `definitions.raster-missing` | — | a required raster that the file does not define |
| `definitions.raster-invalid` | — | a required raster whose value is not a number to the reader (`nan`, `inf`, text) [1] |
| `definitions.skipped` | — | a required raster that is there, because the reader skipped `[DEFINITIONS]` after a section that ran to the end of the file [1] |
| `extension.required-unknown` | — | a required extension that the reader does not know |
| `section.extensions-last` | — | `[EXTENSIONS]` as the last section |
| `blocks.missing` | — | no `[BLOCKS]` section |
| `syntax.row` | — | a row that does not decode with the reader's `sscanf` format |
| `syntax.comment-row` | — | a `#` line inside a table or a shape, which the reader reads as a row [2] |
| `syntax.shape` | — | another line of `[SHAPES]` that does not decode [2] |
| `ref.unresolved` | — | a block that names an event that the reader did not read |
| `rotation.norm` | — | a quaternion whose norm is more than 1e-3 from 1 |
| `gradient.raster` | — | an arbitrary gradient on a gradient raster other than 10 µs (`decodeBlock`, `cpp:2115-2121`) [3] |
| `shape.decompression` | — | a repeat count that is not a whole number |
| `shape.ext-trap-lengths` | — | an extended trapezoid whose time shape and waveform differ in length |
| `cpp.exception` | — | a C++ exception in the reader |
| `cpp.rejected` | — | any other rejection |
| `ub.shape-missing` | D5.1 | see section 2.2 |
| `ub.gradient-shape-0` | D5.2 | see section 2.2 |
| `ub.rf-time-id-minus-1` | D5.3 | see section 2.2 |
| `ub.extension-cycle` | D5.4 | see section 2.2 |
| `ub.shape-decompression` | D5.5 | see section 2.2 |
| `ub.shape-empty` | D5.6 | see section 2.2 |
| `ub.rf-shape-lengths` | D5.7 | see section 2.2 |
| `ub.rf-time-overrun` | D5.8 | see section 2.2 |
| `ub.rf-time-range` | D5.9 | see section 2.2 |
| `ub.gradient-one-point` | D5.10 | see section 2.2 |
| `ub.gradient-time-range` | D5.11 | see section 2.2 |

"—" is a rejection with no entry: the reader rejects it, and `cpp-siemens` follows the rule
(section 1), so nothing needs a reason.

[1] The reader's message is the same for all three `definitions.*` codes ("Required: definition …
is not present"); the "as written" reading tells them apart, so the code names the cause.
[2] The message gives the row; a row that starts with `#` is a comment in the specification
(spec:171), which the reader does not skip.
[3] The reader prints this at a debug level, so it is found from the libraries.
