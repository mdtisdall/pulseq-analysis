# What `cpp-siemens` does, and why

`cpp-siemens` is the interpreter of pulseq-analysis that this package gives
(`pulseq_cpp_siemens.interpreter`). It reads a Pulseq file as the C++ reader of the scanner's
interpreter on Siemens systems reads it. This document gives its rule (section 1) and each
exception to the rule (section 2), with the reason.

The C++ reader is `src/ExternalSequence.cpp` and `.h` of
[pulseq/pulseq](https://github.com/pulseq/pulseq) at `c7469123` (`pulseq-reader.sha256`), cited as
`cpp:N` and `cpp.h:N`. The IDs (D02, D21, …) name a condition in a file. They are the IDs of
[`docs/discrepancies.md`](../../../docs/discrepancies.md) of pulseq-analysis, whose source table for
each ID gives what the reader does, with citations. P1 to P21 and Q1 to Q6 are the decisions of
`docs/plans/parser-redesign.md` of pulseq-analysis. Fixtures named without a folder are in
`tests/seqfiles/` of pulseq-analysis.

## 1. The rule

`cpp-siemens` gives what the C++ reader gives, and rejects what it rejects (P1, P2, P14): its
waveforms, its float32 values (P6), and its misreadings of a row (P3, for example D14 and D16).

Why: the reader is what the scanner plays. The engine of `cpp-siemens` is the reader itself,
compiled unchanged into this package's extension (P11), so the rule holds by construction. `read`
runs `decodeBlock` on every block (P19), so a block that the reader rejects at play time rejects
the file when it is read.

## 2. The exceptions

### 2.1 The version gate

**D03: a version before 1.4.0 or from 1.6.0.** The reader ports 1.2 and 1.3 files
(`cpp:1656-1711`) and reads 1.6.0 with the 1.5 layouts (no upper bound, `cpp:918-922`).
`cpp-siemens` raises `NotSupported` before the reader runs, and also for a binary file or a
folder (for example `bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq`).

Why: the package reads 1.4.0 to 1.5.x only (Q1), and a version it does not know must fail
loudly, not be read wrongly. The gate must come first: for a file older than 1.4.0, `load` itself
calls `GetBlock` on each block (`cpp:1656-1663`), before the checks of section 2.2 can run.

### 2.2 The undefined behaviour of the reader

In each case below the reader reads or writes memory that it does not own, reads an
indeterminate value, or never ends. `cpp-siemens` rejects the file with a `ub.*` code
(`UndefinedBehaviour` in this package, a `SeqFileError` in pulseq-analysis). The checks
(`_checks.py`) run on the libraries after `load`, before any `GetBlock` or `decodeBlock`.

Why (Q2): the reader has no single behaviour to follow (the same file crashes one build and reads
in another), and it runs in this process, where a bad write or an endless loop under its lock
would harm every later read.

| ID | Code | Condition | The reader | Fixture |
|---|---|---|---|---|
| D21 | `ub.shape-missing` | a block uses a shape that the reader did not read (also after D05 `[VERSION]` last, or D07 no blank line after a shape) | null reference (`cpp:1995`, `cpp:2177`) | `bad_ref_shape.seq`, `bad_ref_time_shape.seq`, `bad_syntax_shape_no_blank_line.seq`, `undefined/version_last.seq` |
| D21 | `ub.gradient-shape-0` | a `[GRADIENTS]` row of shape ID 0 that a block uses | plays an uninitialised `GradEvent` as a trapezoid (`cpp:1069`) | `tests/fixtures/gradient_shape_0.seq` |
| D22 | `ub.rf-time-id-minus-1` | an RF event with time ID -1 | looks up time shape -1, which does not exist (`cpp:2026`) | `undefined/rf_time_id_minus_1.seq` |
| D23 | `ub.extension-cycle` | a cycle in an extension list | never ends, holding the reader's lock (`cpp:1849-1928`) | `bad_ref_extension_cycle.seq` |
| D29 | `ub.shape-decompression` | a shape that decompresses to more samples than `num_samples`, or ends in a repeat with no count | writes past its buffer (`cpp:2231`), or reads past the stored values (`cpp:2222`) | `undefined/shape_decompress_longer.seq`, `tests/fixtures/shape_decompress_count_missing.seq` |
| D33 | `ub.shape-empty` | an event uses a shape with no sample | element 0 of an empty vector (`cpp:1995`, `cpp:2203`) | `bad_shape_empty.seq` |
| D34 | `ub.rf-shape-lengths` | an RF phase shorter than its magnitude | `checkRF` reads past the phase (`cpp:2288`) | `bad_shape_event_length.seq` |
| D36 | `ub.rf-time-overrun` | the RF resampling reaches the number of samples | reads one past the samples (`cpp:2039-2045`) | `bad_shape_rf_time_end.seq`, `valid_rf_time_shapes.seq` |
| D36 | `ub.rf-time-range` | an RF time shape whose last time does not fit an `int` | undefined conversion (`cpp:2031`) | `tests/fuzz_corpus/rf-time-range.seq` |
| D59 | `ub.gradient-one-point` | an extended trapezoid of one point at a time above 0 | `gradientsAt` reads `times[1]` and `wave[1]`, past both vectors (`cpp:3639-3650`) | `tests/fixtures/gradient_one_point.seq` |
| D60 | `ub.gradient-time-range` | an extended trapezoid time that does not fit a `long` | undefined conversion (`cpp:2182`) | `tests/fuzz_corpus/gradient-time-range.seq` |

The neighbouring cases that are defined follow the rule: a shape that decompresses to fewer
samples is read with its last value repeated (D29); a longer RF phase is read, and the reader plays
the magnitude's length (D34); an RF time shape that the resampling reads within its samples is
resampled, artefacts included (D36, P5); a `[GRADIENTS]` row of shape 0 that no block uses is read;
a one-point extended trapezoid at time 0 is read.

### 2.3 Settings of the scanner

The reader applies nothing that the scanner's interpreter decides, and has modes that the
scanner can set. `cpp-siemens` gives the reader's output with the reader's defaults, and offers
settings for the rest (P7, P18, P20). A result records the settings it used.

**D43: an oversampled arbitrary gradient (time ID -1).** The reader keeps the samples at the
centres of the raster by default (`cpp:103`, `cpp:2123-2135`); the scanner can set another mode
(`cpp.h:978-991`). `CppSiemens(oversampling=...)` is that mode: `"center"` (the default),
`"edge"` or `"preserve"`. Why: each mode is the reader's own, and the scanner can choose any.
For example, block 3 of `oracle/koma_v1.5_spiral.seq` has 2112, 2111 and 4223 samples in the
three modes.

**D49: a block that plays a rotation.** The reader attaches each block's first rotation, divided
by its norm (`cpp:1286-1292`, `cpp:1871-1879`), in any version, and never rotates the gradients
(`gradientsAt`, `cpp:3558-3698`): the scanner does. With `CppSiemens(rotation="reader")`, the
default, the gradients are the reader's, and the decoding's `rotation_record.warning()` says that
a rotation was left unapplied. With `rotation="apply"`, `gradients_at` turns each block's
gradients by its quaternion with the reader's own `rotate_vec3_by_quat`, in any version, as the
reader attaches it. Why: the default is the reader's output (P20); `"apply"` simulates what the
scanner plays, with the reader's arithmetic. What the scanner does with a rotation in a file older
than 1.5.1 is not known.

### 2.4 The reader's values in the model

`cpp-siemens` gives the model of pulseq-analysis (`SequenceData`), built from the reader's
libraries. Where the reader holds a mark, or no value, the model holds the following. The
decoding (`GetBlock`, `decodeBlock`, `gradientsAt`) is the reader's own and is unchanged.

Why: the model is shared by the interpreters of pulseq-analysis, so each field must mean the same
in all of them (P14, the contract of section 7.3 of the plan).

| ID | The reader holds | The model holds |
|---|---|---|
| D13 | each definition as text and numbers (`cpp:1432`, `cpp:1445`) | the text; only the four rasters as numbers (a 32-digit hash does not fit a double) |
| D18 | `float` amplitudes, offsets and samples | the same values as float64 (exact) |
| D20 | no block ID (`cpp:1565`, `cpp:1586`) | `id` = the position in play order, from 1 |
| D25, D42 | events inside one block; `gradientsAt` joins no blocks (`cpp:3561-3566`) | `gradients_at` gives 0 after a block's end and between blocks |
| D38 | `center` -1 in a 1.4 RF event, "mark as invalid" (`cpp:1037`) | `center` NaN |
| D44 | the ADC phase shape, used as rad (`cpp:3059-3060`) | the shape as stored, with no factor |

### 2.5 The codes of the rejections

The reader gives a message, not a code. `cpp-siemens` gives each rejection a stable code, so that
a caller can tell rejections apart (P2). `_classify` finds the code from the reader's message,
and, where the message is not enough, from the "as written" reading of pulseq-analysis. The reader
stops at its first error, so a rejection has one reason, with the reader's message.

| Code | ID | The reader rejects |
|---|---|---|
| `version.missing` | D02 | no `[VERSION]` section |
| `version.invalid` | D04 | a `[VERSION]` line that does not decode, or an unknown key |
| `definitions.raster-missing` | D11 | a required raster that the file does not define |
| `definitions.raster-invalid` | D11 | a required raster whose value is not a number to the reader (`nan`, `inf`, text) [1] |
| `definitions.skipped` | D56 | a required raster that is there, because the reader skipped `[DEFINITIONS]` after a section that ran to the end of the file [1] |
| `extension.required-unknown` | D47 | a required extension that the reader does not know |
| `section.extensions-last` | D46 | `[EXTENSIONS]` as the last section |
| `blocks.missing` | — | no `[BLOCKS]` section |
| `syntax.row` | D14, D15 | a row that does not decode with the reader's `sscanf` format |
| `syntax.comment-row` | D06 | a `#` line inside a table or a shape, which the reader reads as a row [2] |
| `syntax.shape` | D07 | another line of `[SHAPES]` that does not decode [2] |
| `ref.unresolved` | D21 | a block that names an event that the reader did not read |
| `rotation.norm` | D49 | a quaternion whose norm is more than 1e-3 from 1 |
| `gradient.raster` | D28 | an arbitrary gradient on a gradient raster other than 10 µs (`decodeBlock`, `cpp:2115-2121`) [3] |
| `shape.decompression` | D29 | a repeat count that is not a whole number |
| `shape.ext-trap-lengths` | — | an extended trapezoid whose time shape and waveform differ in length |
| `cpp.exception` | — | a C++ exception in the reader |
| `cpp.rejected` | — | any other rejection |
| `ub.*` | section 2.2 | |

"—" is a condition that has no ID: the reader rejects it, and no other source disagrees.

[1] The reader's message is the same for all three D11 and D56 codes ("Required: definition …
is not present"); the "as written" reading tells them apart, so the code names the cause.
[2] The message gives the row; a row that starts with `#` is a comment in the specification
(spec:171), which the reader does not skip.
[3] The reader prints this at a debug level, so it is found from the libraries.
