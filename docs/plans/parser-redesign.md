# Plan: the parser redesign — two interpreters, and findings in place of checks

Branch `docs/parser-redesign`. This plan changes the goal of `read_seqfile` and of the decoding
of task 2 (`docs/plans/own-parser-tasks.md`, merged in #100). It comes before tasks 4, 5a, 5b
and 6 of that plan, and section 10 says how they fit.

The entries D1.1 to D4.7 are those of `docs/discrepancies.md` (the record of `spec`) and D5.1 to
D7.6 those of `packages/pulseq-cpp-siemens/docs/specification.md` (the record of `cpp-siemens`).
Since 2026-10-13 an ID names a decision of an interpreter (section 11 says how the entries were
regrouped); the old IDs, numbered in the order of discovery, are mapped in the appendix of the record. "The C++ reader" is
`ExternalSequence` of pulseq/pulseq at `c746912`, the reader of the scanner's interpreter on
Siemens systems. "cpp:N" is a line of `src/ExternalSequence.cpp` at that commit. "The
specification" is the Pulseq specification 1.5.3 (draft), cited by section. In this plan an
"interpreter" is one of the package's two ways of reading a file (`cpp-siemens`, `spec`); the
program on the scanner that plays a Pulseq file is "the scanner's interpreter".

## 1. Goal

pulseq-analysis turns a Pulseq file into waveforms, and it measures them. It does not judge
whether a file is valid, and it performs no checks. It reads a file through one of two
**interpreters**:

- **`cpp-siemens`** (by name, P19): a faithful replica of the C++ reader, the reader of the
  scanner's interpreter on Siemens systems, with all its limits. If the C++ reader makes a
  waveform, `cpp-siemens` makes the same waveform, including the reader's misreadings, clamps,
  resampling, defaults and its 10 µs gradient raster. If the C++ reader rejects a file,
  `cpp-siemens` rejects it. Its engine is the C++ reader itself, wrapped and run in the
  process (P11, 7.6), in its own precompiled package (P12). It is an optional plugin of
  pulseq-analysis (P21): installed separately, found through the entry-point group
  `pulseq_analysis.interpreters`, with no import of it in pulseq-analysis.
- **`spec`** (the default, P19): as true as possible to the written specification. It reads each field as the
  specification types it, takes any raster that the file defines, and gives no waveform where
  the specification says a file "must" not be as it is. Where the specification is silent, it
  makes a documented choice (section 6).

pulseq-analysis reads, interprets and measures. Each interpreter gives a waveform, or a
rejection with its code and reasons. It reports nothing else about a file.

Where the sources read a file differently, **pulseq-checks** reports a **finding** (P17). It
reads the file through pulseq-analysis's public readings, as often as it needs (a read costs
about 0.03 s per MB), and finds each discrepancy that `docs/discrepancies.md` records (7.4).
In this plan, "with a finding" or "Finding." means that pulseq-checks reports the condition;
pulseq-analysis only plays it.

This replaces the order of preference of 2026-10-09 (C++ reader, then the specification, then
MATLAB, then pypulseq). The record's section 4 reviewed the package's former reader against that
order; it was removed when the record was split by interpreter (section 11).

## 2. Decisions (the user, 2026-10-12)

P12 to P17 follow the review of R2, R3 and R4 (2026-10-12).

| ID | Decision |
|---|---|
| P1 | `cpp-siemens` makes the waveform that the C++ reader makes. |
| P2 | `cpp-siemens` rejects a file that the C++ reader rejects. |
| P3 | Where the C++ reader misreads a row and still makes a waveform (a fraction in an integer column, D2.16), `cpp-siemens` reproduces the misreading, with a finding. |
| P4 | Behaviour of the C++ reader that depends on the build (undefined behaviour: reads out of bounds, crashes in one build only) is decided case by case, and each case is its own kind of finding (section 5.3). |
| P5 | An RF time shape whose points are not on the raster edges: `cpp-siemens` resamples it as the C++ reader does, artefacts included, with a finding. Only a shape where the resampling reads past its samples is undefined behaviour (P4). |
| P6 | float32: `cpp-siemens` gives the reader's float32 values, as the wrapper computes them (P11). A finding compares them with the values as written, in float64, where float32 rounding changes a value noticeably (D7.2). |
| P7 | Where the C++ reader uses a sentinel or a mode that the scanner's interpreter can set (D4.4 `FLOAT_UNDEFINED`, D6.1 oversampling), `cpp-siemens` follows the reader's default, with a finding. |
| P8 | Superseded by P17: findings are pulseq-checks', not data on pulseq-analysis's results. |
| P9 | `[EXTENSIONS]` as the last section (D2.3): `cpp-siemens` rejects it, as the C++ reader does, with its own code (section 8). |
| P10 | Two interpreters: `cpp-siemens`, a replica of the C++ reader with all its limits, and `spec`, as true as possible to the specification. Other rasters are the `spec` interpreter's; there is no "C++ reader on any raster" interpreter for now. |
| P11 | The engine of `cpp-siemens` is a wrapper of the C++ reader, run in the process, after the prototype of task R2 (7.6). |
| P12 | The wrapper is its own precompiled distribution, `pulseq-cpp-siemens`, kept in this repository (`packages/pulseq-cpp-siemens/`, its own `pyproject.toml`): the extension, the checks of 5.3, the lock and the locale handling. It ships wheels for the five platforms of the R2 report. pulseq-analysis stays pure Python (7.7). ~~pulseq-analysis depends on it~~: superseded by P21. |
| P13 | Task R5 is the **"as written" reading**: a lossless, typed reading of the text, with line numbers. It is the base of the `spec` reader, of the version gate before the C++ reader (Q1), and of pulseq-checks' findings, which compare it with what the reader read (7.4). |
| P14 | The `SequenceData` of `cpp-siemens` is the reader's own reading, built from its libraries (blocks, events, shapes, extensions as it read them), misreadings included. |
| P15 | Task 5a of `own-parser-tasks.md` is re-planned here as R14: `load` runs on an interpreter's output. The C++-replica code of task 2 (`_rf_resample`, `_rf_time_step`, the RF decoding of `events.py`) is retired once the wrapper covers it. |
| P16 | Task 4 of `own-parser-tasks.md` is re-planned here as R15: a `pypulseq.Sequence` built in memory is written to `.seq` text with pypulseq's writer, then read through an interpreter. |
| P17 | The findings move to pulseq-checks (the user, 2026-10-12, after the review). pulseq-analysis keeps the readings, the interpreters, their coded rejections and the measurements; it has no `Finding` type, catalogue, `compare` or warnings. pulseq-checks finds each discrepancy from pulseq-analysis's public readings (7.4), and owns the catalogue, the severity and the reports (7.5). |
| P18 | R6b (2026-10-12): ~~`pulseq-cpp-siemens` is the extra `cpp-siemens` of pulseq-analysis~~ (superseded by P21); how a git-URL install gets it is decided at release time; today's strict reader stays as the interim interpreter `strict` until R11 (5.4); and `CppSiemens(oversampling=...)` exposes the reader's three sampling modes of an oversampled gradient (`"center"`, `"edge"`, `"preserve"`), in pulseq-cpp-siemens and its oracle. |
| P19 | The default interpreter is the fast one (the user, 2026-10-12, in R6b): `strict` until R11, then `spec`. `cpp-siemens` decodes every block with the C++ reader to give its verdict (P2), about seven times as long (4 s for a file of 21 MB with 900 000 blocks, against 0.6 s), so it is read by name: `interpreter="cpp-siemens"`. This replaces "`cpp-siemens` (the default)" of section 1 and Q6. |
| P20 | Scanner-side settings (the user, 2026-10-12, after `docs/plans/scanner-settings-study.md`): the eight rules of section 7.8. Each interpreter's default is its own source with a neutral scanner session; `spec` applies content of the file only from the revision that introduced it; `cpp-siemens` gives the reader's output and offers the package's simulation as opt-in settings; scanner-session inputs are one `Session`, the same for both; every result records what was applied; a setting that addresses something the file does not have is an error. Amends Q3 and R9. |
| P21 | `cpp-siemens` is a plugin of pulseq-analysis (the user, 2026-10-13: "It should be an optional sub-project that can be installed, but we shouldn't have any import-level dependencies on it."). pulseq-analysis has no reference to pulseq-cpp-siemens in its code or metadata (no extra, no dev dependency). It finds a plugin interpreter through the entry-point group `pulseq_analysis.interpreters` (the name of the entry point is the interpreter's name, its value the class); `spec` stays built in, and a plugin cannot be named `spec`. A plugin interpreter has `name`, `read(path)` and `decode(data)` (`seqfile.interpreters.Plugin`); its decoding has the methods that the package uses (`synth.Decoding`, with `gradient_points` for R14). The settings class `CppSiemens`, the adapter and `CppSiemensDecoding` move to `pulseq_cpp_siemens.interpreter`, the only module of the package that imports pulseq-analysis; the tests that read through `cpp-siemens` move to the package's tests. A name that no installed interpreter has is a `ValueError` that names the group, not a plugin. How a release of pulseq-cpp-siemens depends on pulseq-analysis is decided at release time; until then a dependency group (`analysis`) takes pulseq-analysis from this repository (7.7). The cpp-siemens record of `docs/discrepancies.md` moves to the package after this change (the user, 2026-10-13). |
| P22 | The `Session` reaches a plugin through its protocol (the user, 2026-10-13): `Plugin.decode(data, session=None)`, with a protocol version on the plugin, so that `cpp-siemens` applies the session with the reader's own hooks inside the plugin (P20 rule 3). R16 is built in pulseq-analysis and in `pulseq-cpp-siemens`, and the change of the protocol is a change of the contract (7.3), recorded in `CHANGELOG.md` and in the document of C1. |

The choice between "C++ reader first" and "specification first" is no longer open, so
`docs/plans/spec-first-study.md` is not needed. It is not committed; its readings of the
specification feed section 6.

## 3. Answers (the user, 2026-10-12)

| ID | Question | Answer |
|---|---|---|
| Q1 | Versions outside 1.4.0–1.5.x (D4.1) | Both interpreters refuse them as **not supported by the package**: a separate exception (for example `NotImplementedError`), which says nothing about the file. |
| Q2 | The undefined behaviour of the C++ reader (section 5.3) | `cpp-siemens` rejects each case, with its own code. |
| Q3 | Rotations (D2.18, D6.2) | Amended by P20 (section 7.8): `cpp-siemens` gives the reader's unrotated gradients and the quaternion by default, with a `ScannerSettingWarning` from `load`, and rotates them with `CppSiemens(rotation="apply")`, in any version (the user, 2026-10-12); `spec` rotates from version 1.5.1. `load` no longer refuses the rotation extension: it runs on the interpreters (R14), keeps the rotation record and emits the warning (the user, in R9). |
| Q4 | `spec` where the specification says "must" | No waveform: `spec` rejects the file, with every violation. pulseq-checks reports that `cpp-siemens` reads it. |
| Q5 | `spec` where the specification is silent | Section 6, row by row. |
| Q6 | The API (section 7.3) | The functions take an interpreter by name or as an object: `interpreter="cpp-siemens"` (the default was changed by P19: `strict`, then `spec`), or `interpreter=CppSiemens(oversampling="edge")` for its settings. Results carry the interpreter and its settings (not findings, P17). |

Two choices give a finding of pulseq-checks although the file reads: a repeated section or
definition (D3.3, D2.6), and an RF time shape read as points (D2.10, D2.11), where the reading goes
beyond what the specification states.

## 4. The classes

For each interpreter, each entry falls in one class:

- **Agree**: the sources read it the same way. No change, no finding.
- **Play**: the interpreter makes a waveform. The package reproduces it, with a finding where
  another source reads it differently.
- **Reject**: the interpreter gives no waveform (`SeqFileError`).
- **UB**: the C++ reader has undefined behaviour or does not end (`cpp-siemens` only). It
  rejects the file (Q2).
- **Scope**: the package does not support it in either interpreter (Q1): the "not supported"
  exception.

"To establish" marks an entry where what the C++ reader plays is not yet known in detail. With
the wrapper (P11), `cpp-siemens` reproduces it with no work; the task that writes its finding
and its record entry establishes it with the oracle first.

## 5. The `cpp-siemens` interpreter

Since #122, the record of `cpp-siemens` is `packages/pulseq-cpp-siemens/docs/specification.md`
(D5 to D7), and its codes are `pulseq_cpp_siemens.interpreter.CODES` (P21). Where this section
and that record differ, the record is right; this section keeps the decisions as they were made.

### 5.1 The entries

| Entry | Class | Today | `cpp-siemens` |
|---|---|---|---|
| D1.2, D4.2 | Agree | 12, 7, 9 fields | No change. |
| D1.1 | Reject | Rejects | No change. |
| D4.1 | Scope | Rejects outside 1.4.0–1.5.x | The "not supported" exception (Q1). |
| `version.invalid` | Play | Rejects `5.0` | Read `5.0` as 5, as C++. Finding. |
| D2.1, D5.1 | Play / Reject | Any order | Any order, except `[VERSION]` as the last section: the stream then stays failed after `[VERSION]`, the seek to `[SHAPES]` fails, and the reader reads no shape (R4). A file with no `[SHAPES]` section is rejected (`load` fails); one whose events use a shape is rejected by `ub.shape-missing` (D5.1, 5.3); one with an unused `[SHAPES]` section is played. The wrapper (P11) reproduces all three. Finding. |
| D2.5, D3.2 | Reject / Play | Blank or `#` line | A blank line inside a table ends it, and C++ never reads the rows after it (only `[` lines start a section): drop them, a misreading (P3), with a finding. A `#` line inside a table is read as a row and fails: reject. `[VERSION]` and `[EXTENSIONS]` skip both. |
| D3.11, D5.1 | Play | Rejects | No blank line after a shape: C++ stops reading `[SHAPES]`, and the later shapes are not read (cpp:939, 955-958, 978). Reproduce; a later reference to a lost shape then follows D5.1. Finding. |
| D2.4 | Play | Rejects | Ignore an unknown section, as C++. Finding. |
| `[DELAYS]` from 1.4.0 | Play | Rejects | Ignore `[DELAYS]` from 1.4.0, as C++. Finding. |
| D3.3 | Play | Rejects | A section twice: the last, as C++. Finding. |
| `definitions.raster-missing`, `definitions.raster-invalid` | Reject / Play | Presence and value | Reject what C++ rejects (a missing raster; nan and inf; a `GradientRasterTime` other than 10 µs, 0 and below included, only in a file with an arbitrary gradient: `gradient.raster`); accept the other values as C++ does (R6b's runs: a gradient raster of 0 with trapezoids only, and 0 or negative values of the other rasters, read). Finding. |
| D2.6 | Play | Rejects | A definition twice: the last. Finding. |
| D2.7, D7.1 | Play | Text | As C++ (text and numbers). Finding where they differ. |
| D3.1, D3.5, D3.6; `syntax.columns`, `syntax.integer` | Reject / Play | Strict | Per form: reject what C++ rejects (`30.5` in an integer column of `[BLOCKS]`); reproduce `+30`, the misread `100.5` RF delay (P3), short and long rows, NaN and negative values as C++ holds them. Finding. |
| `raster.adc-dwell` | Reject | Reads | Reject a dwell with a decimal point, as C++. Both writers write the dwell with `%.0f`, so no file written by them is affected. |
| D2.16 | Play | Reads | Reproduce the misreading of `-100.5` and the 31-character hint (P3). Finding. |
| `syntax.use` | Play | Rejects | Any `use` character, as C++. Finding. |
| D7.2 | Play | float64 | P6. Finding where float32 changes a value. |
| D3.4; `id.positive`, `id.unique`, `id.gradient-unique` | Play | Rejects | IDs that are not positive or not unique: the last wins, as C++; a `[TRAP]` row replaces a `[GRADIENTS]` row of the same ID (one library, `[TRAP]` read later; R6b's runs). Finding. |
| D7.3 | Play | Rejects | Block IDs out of order: file order, as C++. Finding. |
| D5.1, D5.2; `ref.unresolved` | Reject / Play | Rejects | Reject an event that does not exist (as C++) and a missing shape (UB, 5.3). Reproduce the extension cases (the list ends; an empty object; a label left out). Finding. |
| D4.3, D5.3 | Play / Reject | Rejects | Time ID -1 for a 1.4 gradient: as C++. For an RF event, the reader looks up the time shape -1, which does not exist (a case of D5.1): reject (`ub.rf-time-id-minus-1`, 5.3). |
| D5.4 | Reject | Rejects | A cycle in an extension list: C++ does not end: reject (5.3). |
| `blocks.empty` | Play | Rejects | No block: an empty sequence, as C++. Finding. |
| `block.event-too-long`, D7.4 | Play | Rejects | An event longer than its block: the events as C++ holds them, `gradientsAt` 0 after the block. Finding. |
| D1.3; `raster.*` | Play | Rejects | Times off a raster: as written, as C++. Finding. |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | Play | Rejects | A gradient that is not 0 at an end: as written, as C++. Finding. |
| `definitions.raster-commensurate`, `gradient.raster` | Reject | Accepts | An arbitrary gradient on a time ID of 0 or -1, in a file whose gradient raster is not 10 µs: C++ fails in `decodeBlock` (cpp:2114-2119), and `gradientsAt` uses a fixed 10 µs (`SeqBlock::s_gradientRaster`, cpp:90). Reject. `valid_arbitrary_gradient_4us_raster.seq` changes class. |
| D5.5; `shape.length` | Play / Reject | Rejects | A shape whose decompressed length differs from `num_samples`. `decompressShape` has no bound (cpp:2213-2236): a longer result writes past its buffer, and a shape that ends in a repeated value with no count reads one value past the stored ones (cpp:2222): reject (`ub.shape-decompression`, 5.3). A shorter one leaves the rest of the derivative at 0, so after the cumulative sum the last value repeats to `num_samples`: played, with a finding. |
| `shape.range` | Play | Rejects | Outside [-1, 1]: clamped, as C++. Finding. |
| D2.8 | Play | Rejects | RF magnitude below 0: 0, as `checkRF`. Finding. |
| D2.9 | Play | Rejects | RF phase outside [0, 1): clamped, as `checkRF`. Finding. |
| D3.7, D5.6 | Reject | Rejects | Empty shape: UB, reject (5.3). |
| D3.8, D5.7 | Play / Reject | Rejects | The shapes of one RF event of two lengths. A phase shorter than the magnitude, or a resampling that reads past either shape: `checkRF` reads past the phase (cpp:2288): reject (`ub.rf-shape-lengths`, 5.3). A longer phase: the reader plays the magnitude's length: played, with a finding. |
| D2.10 | Play | As C++; rejects off-centre | As C++, off-centre times included (P5). Finding. |
| D2.11, D3.9, D5.8, D5.9 | Play / Reject | As C++; rejects past the end | (1) As C++ (P5); (2) the read past the end: reject (5.3). |
| D2.12 | Play | As C++ | No change. Finding (MATLAB and pypulseq round the last time up). |
| D4.2, D7.5 | Play | Absent | A 1.4 RF event has `center` -1 in C++. Keep it absent in the model; finding. |
| D4.4 | Play | Rejects | `FLOAT_UNDEFINED` ends, as `gradientsAt` uses them (P7). To establish the value. Finding. |
| D4.5 | Play | (2) rejects | (2) As `gradientsAt` (the first segment extended backwards). Finding. |
| D2.13 | Play | Lines | No change. Finding (MATLAB restores the edges). |
| D2.14, D7.4 | Play | Ramps (MATLAB) | C++ makes one block at a time. To establish what the package shows between blocks. Finding. |
| D6.1 | Play | All the samples | The centre samples only, C++'s default (P7). Finding. |
| D2.15, D3.8, D7.6 | Play | As stored | As C++ (rad). Finding where they differ. |
| D2.17, D4.6 | Play | Ignores | No change. Finding (pypulseq rejects). |
| D2.3 | Reject | Accepts | Reject (P9, section 8). |
| `extension.required-unknown` | Reject | Rejects | No change. |
| `extension.per-block` | Play | Rejects | Two rotations or shims in a block: the first, as C++. Finding. |
| D2.18, D3.10, D4.6, D6.2 | Play / Reject | Reads as written; `load` refuses rotations | A quaternion within 1e-3 of unit norm: divided by its norm (cpp:1286-1292) and given with the block's unrotated gradients, as the reader gives them, in any version; rotated with `CppSiemens(rotation="apply")` (P20). Further: reject, as C++. |
| D2.19, D4.7 | Play | Reads | No change (C++ ignores the label). Finding. |
| Equal events with different IDs | Play | Keeps | No change. Finding (pypulseq merges). |
| No scanner values in the file | — | None | Not about the file. No change. |
| The signature hash | Play | As C++ | No change. Finding (CRLF). |
| `signature.invalid` | Play | Rejects | Accept, as C++. Finding. |
| D1.4 | Agree | Text | No change. |
| D2.2 | Play / Reject | Accepts | The last section with no blank line after it: reading it fails the stream at the end of the file, and the reader skips each section that it reads after it, in its own order, until it resets the stream after `[SHAPES]` (as D2.1). For example a file whose last section is `[TRAP]` loses its definitions and is rejected ("AdcRasterTime is not present", `definitions.skipped`); a `[SHAPES]` section helps only when it comes after the failing section (R6b's runs: `[SHAPES]` before `[TRAP]` does not), `[DEFINITIONS]` last gives 0 blocks, and `[BLOCKS]` last reads. Writers always end with a blank line. Reproduced by the wrapper; finding. New entry of the record (R6b). |

### 5.2 What `cpp-siemens` rejects

a file with no `[VERSION]` (D1.1), a `#` row inside a table (D2.5), a missing or invalid raster, a row that does not decode, an ADC dwell with a decimal point, a reference to nothing, an arbitrary gradient in a file whose gradient raster is not 10 µs, `[EXTENSIONS]` as the last section (D2.3), an unknown required extension,
a quaternion whose norm is off by more than 1e-3, and each case of undefined behaviour (5.3). Each rejection
keeps a stable code, so pulseq-checks and the tests can name it. A version outside 1.4.0–1.5.x
raises the "not supported" exception instead (Q1).

### 5.3 The undefined behaviour of the C++ reader (Q2)

`cpp-siemens` rejects each case (Q2), with its code. The checks run after `load`, on the
libraries that the reader built, before `GetBlock` and `decodeBlock` (the R2 report, 7.6). R2
and R4 found each case with the sanitizers.

| Code | Entry | What the reader does |
|---|---|---|
| `ub.shape-missing` | D5.1; D2.1 and D3.11 lead to it | A block uses a shape that the reader did not read: a null reference (cpp:1995, 2177). With `[VERSION]` last (D2.1) the reader reads no shape; with no blank line after a shape (D3.11) it reads none after it. |
| `ub.rf-time-id-minus-1` | D5.3 | An RF event with time ID -1: the time shape -1 does not exist (cpp:2026). |
| `ub.extension-cycle` | D5.4 | A cycle in an extension list: the reader appends to a vector with no end. Not undefined behaviour, but no end; in the process it would hold the reader's lock. |
| `ub.shape-decompression` | D5.5 | A shape that decompresses to more than `num_samples` (a write past the buffer, cpp:2231), or that ends in a repeated value with no count (a read past it, cpp:2222). |
| `ub.shape-empty` | D5.6 | An empty shape: element 0 of an empty vector (cpp:1995, 2203). |
| `ub.rf-shape-lengths` | D5.7 | An RF phase shorter than its magnitude: `checkRF` reads past it (cpp:2288). |
| `ub.rf-time-overrun` | D5.8 | The resampling index reaches the number of samples and reads one past them (cpp:2044). This includes MATLAB's RF pulses of 4 samples or fewer at the default dwell, written as an uncompressed time shape at the cell centres. |
| `ub.rf-time-range` | D5.9 | An RF time shape whose last time does not fit an `int` (cpp:2031). No fixture yet. |
| `ub.gradient-time-range` | D5.11 | An extended trapezoid time that does not fit a `long` (cpp:2182). No fixture yet. |
| `ub.gradient-one-point` | D5.10 (R6a) | An extended trapezoid of one point whose time is above 0: `gradientsAt` at a time between its delay and that time (and within the block) reads `times[1]` and `wave[1]`, past both vectors (cpp:3639-3650). `decodeBlock` reads the file; only `gradientsAt` meets it. |
| `ub.gradient-shape-0` | D5.2 (R6a) | A `[GRADIENTS]` row of shape 0 that a block uses: `load` reads the row into a `GradEvent` that it does not initialize (cpp:1069) and sets no ramp or flat time, and the reader plays it as a trapezoid with whatever those fields held. The sanitizers do not see indeterminate values. |

A sanitizer build of the C++ oracle (section 9) finds each case, so the list is not left to the
memory layout of one build. The fuzzing of R6a found the last two (the user decided to reject
both, 2026-10-12): the sanitized oracle's `--sample` confirms `ub.gradient-one-point`, and
`ub.gradient-shape-0` showed as values of `gradientsAt` that differ between two builds. The
check of `ub.gradient-shape-0` reads the rows of `[GRADIENTS]` and `[TRAP]` again with the
reader's own `getline` and `sscanf`, as the version gate reads `[VERSION]`, since in the
libraries such an event looks like a `[TRAP]` row. Their fixtures are in
`packages/pulseq-cpp-siemens/tests/fixtures/`.

### 5.4 Today's rules (R6b)

`cpp-siemens` applies none of the rules of the strict reader (`seqfile.reader`): it rejects what
the C++ reader rejects, with the codes of `seqfile.cpp_siemens.CODES` (since P21,
`pulseq_cpp_siemens.interpreter.CODES`). Until R11, the strict
reader stays as the interim interpreter `strict` (the user, 2026-10-12), with its rules, except
that a version outside 1.4.0–1.5.x raises the "not supported" exception (Q1). For R11, each rule
is kept for `spec`, changed, or removed (section 6). R11 removed the interim `strict` interpreter
(the user, 2026-10-12):

| Rule | `cpp-siemens` | `spec` (R11) |
|---|---|---|
| `version.missing` | `version.missing` | Kept (D1.1). |
| `version.invalid` | `version.invalid`, for a line that does not decode; `5.0` reads as 5 | Kept. |
| `version.unsupported` | `NotSupported` (Q1) | Removed here already: `NotSupported` (Q1). |
| `definitions.raster-missing` | `definitions.raster-missing` | Kept. |
| `definitions.raster-invalid` | `definitions.raster-invalid` for nan and inf; `gradient.raster` for a gradient raster of 0 or below with an arbitrary gradient | Kept. |
| `definitions.duplicate` | Reads the last (D2.6) | Removed: the last wins (D2.6). |
| `section.unknown` | Ignores it (D2.4) | Removed: ignored (D2.4). |
| `section.delays` | Ignores it | Removed: ignored (D2.4). |
| `section.duplicate` | Reads the last (D3.3) | Removed: the copies read as one (D3.3). |
| `syntax.encoding` | Reads the bytes | Kept (D3.1): settled in R11 (the user, 2026-10-12), any byte that is not UTF-8, documented as the package's choice (the specification gives no encoding). |
| `syntax.line` | Drops the rows after a blank line (D2.5) | Changed: rows after a blank or `#` line are read (D2.5); a data line before the first header stays. |
| `syntax.columns` | `syntax.row` for too few fields; reads a longer row | Kept. |
| `syntax.integer` | `syntax.row` for `30.5` and `1e2`; reads `+30` | Kept, but `+30` reads as 30. |
| `syntax.number` | Reads NaN and inf as the reader holds them | Kept (D3.5). |
| `syntax.use` | Any character | Kept. |
| `syntax.negative` | Reads negative values | Kept (D3.6): settled in R11 (the user, 2026-10-12) for each column of the strict reader (block duration, delay, rise, flat, fall, `num_samples`, dwell, trigger duration), documented as the package's choice (not literally spec:176). |
| `syntax.shape` | `syntax.shape` for a line that does not decode; a shape with no blank line after it ends the section (D3.11, then `ub.shape-missing`) | Kept (D3.11). |
| `id.positive`, `id.unique`, `id.gradient-unique` | The last wins | Kept (D3.4 for a block ID). |
| `ref.unresolved` | `ref.unresolved` (events), `ub.shape-missing` (shapes), `ub.extension-cycle` (D5.4); reads the extension cases | Kept. |
| `blocks.empty` | Reads an empty sequence | Kept. |
| `blocks.order` | File order | Removed: file order. |
| `block.event-too-long` | Reads it | Kept. |
| `raster.adc-dwell`, `raster.gradient-delay`, `raster.gradient-end`, `raster.gradient-ramp`, `raster.gradient-flat` | Reads it; `syntax.row` for a dwell with a decimal point | Kept. |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | Reads it | Kept. |
| `shape.length` | `ub.shape-decompression` for a longer shape; reads a shorter one | Kept. |
| `shape.range` | Clamps | Kept. |
| `shape.rf-magnitude-negative` | Clamps to 0 (D2.8) | Removed: a negative magnitude plays (D2.8). |
| `shape.rf-phase-range` | Clamps (D2.9) | Removed: the phase plays as written (D2.9). |
| `shape.empty` | `ub.shape-empty` (D5.6) | Kept (D3.7). |
| `shape.rf-time-grid` | Plays the step, the first time ignored (D2.10) | Removed: read as the format's tools read it (D2.10). |
| `shape.rf-time-end` | `ub.rf-time-overrun` (D5.8) | Removed: read as points (D2.11). |
| `shape.event-length` | `ub.rf-shape-lengths` for a shorter RF phase; plays a longer one (D5.7); `shape.ext-trap-lengths` for an extended trapezoid | Kept (D3.8). |
| `extension.required-unknown` | `extension.required-unknown` | Kept. |
| `extension.per-block` | The first | Kept. |
| `layer1.gradient-ends` | Reads it, with the reader's `FLOAT_UNDEFINED` ends (D4.4, D4.5) | Kept (D4.4, D4.5). |
| `signature.invalid` | Reads it | Kept. |

## 6. The `spec` interpreter

The `spec` interpreter reads the file as the specification describes it. "Must" in the
specification gives a rejection (Q4). Where the specification is silent, the user chose the
reading (Q5, 2026-10-12); those rows are marked **chosen**. Its readings are checked against the
text of the specification by hand, with a citation for each.

| Entry | Specification | `spec` |
|---|---|---|
| D1.2, D4.2 | Table and example: 12, 7, 9 fields | The same as `cpp-siemens`. |
| D1.1 | Recommends rejecting a file with no `[VERSION]` | Reject. |
| D4.1 | Silent | Q1. |
| `version.invalid` | `major <major>`: integers | Reject `5.0` (not an integer, as `syntax.integer`). |
| D2.1 | Silent on order | Any order. |
| D2.5, D3.2 | A comment is a line that starts with `#` (§2.1) | **Chosen**: skip blank and `#` lines anywhere; the rows after them are read. Inside a shape a `#` line is skipped too, and a blank line ends the shape (D3.11; R11). A data line before the first header: reject (R11, no writer writes one). |
| D3.11 | A blank line ends a shape (§2.9) | **Chosen**: reject a shape with no blank line after it, before the next `shape_id`, a header or the end of the section (R11). |
| D2.4 | Silent | **Chosen**: ignore an unknown section, with a finding. |
| `[DELAYS]` | Removed in 1.4.0; "current readers ignore this section" (binary format) | **Chosen**: ignore, with a finding. |
| D3.3 | Silent | **Chosen** (R11, the user, 2026-10-13): reject a section that appears twice, and two `extension` sections with one `STRING_ID` (`section.duplicate`): the readers disagree on a second copy (the C++ reader keeps the last; MATLAB adds the copies of `[GRADIENTS]` and `[TRAP]` and keeps the last of the others; pypulseq adds those of `[RF]`, `[GRADIENTS]`, `[TRAP]`, `[ADC]` and TRIGGERS), and no writer writes one. This replaces "read the copies as one (as MATLAB and pypulseq)", which their code does not do. |
| `definitions.raster-missing`, `definitions.raster-invalid`, `definitions.raster-commensurate` | Required | Reject a missing raster, and a raster that is not finite and above 0. Reject an RF or gradient raster that is neither a multiple nor a divisor of the block duration raster (slide 11, R11). |
| D2.6 | Silent | **Chosen**: the last definition wins (as all three implementations), with a finding. |
| D2.7 | `any`; the hash a string | Text. |
| D3.1, D3.5, D3.6; `syntax.columns`, `syntax.integer` | Types only; no number syntax | Each field as its type: reject `30.5` and `100.5` in integer columns, and a row with too few or too many fields; read `+30` as 30. **Chosen**: reject NaN and inf in each float column, and a negative delay. |
| `raster.adc-dwell` | A float in ns, an integer multiple of `AdcRasterTime` | Read the float; off the raster: reject. |
| D2.16 | An example only: the offset in µs, no table of types | **Chosen**: read the offset as a float (`-100.5` µs, as MATLAB writes and reads it) and keep the whole hint. |
| `syntax.use` | One of 7 letters | Reject another letter. |
| Values beyond float32 | Shapes stored as float32 in binary files | float64. |
| D3.4; `id.positive`, `id.unique`, `id.gradient-unique` | IDs must be positive and unique | Reject. A block ID used twice too, which §2.2 does not state (R11, no writer writes one). |
| Block IDs out of order | "The blocks are executed sequentially" (§2.7); no restriction on IDs | File order. |
| `ref.unresolved` | References are implied to resolve | Reject. |
| D4.3; `ref.unresolved` | Time ID -1 for gradients only | Reject it for an RF event, and for a gradient of a 1.4 file (R11; slide 4 dates it from 1.5.0). |
| `ref.unresolved` (a cycle) | Implied | Reject a cycle. |
| `blocks.empty` | "Must declare at least one block" | Reject. |
| `block.event-too-long` | The scanner's interpreter must reject it | Reject. |
| D1.3; `raster.*` | "Must" | Reject. Also an RF event and an ADC that do not start on an edge of the RF raster (slides 9, 10), and a vertex of a gradient time shape off the gradient raster (R11: slides 4 and 6 conflict, no writer writes one). |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | "Must" and "need to" | Reject. |
| `definitions.raster-commensurate` | Any gradient raster | Play on the file's raster, when it is commensurate with the block duration raster (slide 11). |
| `shape.length` | "Must" | Reject. |
| `shape.range` | "Must" be in [-1, 1] | Reject. |
| D2.8 | Allowed: the magnitude is a signed amplitude shape | Play a negative magnitude as written (a phase of π). |
| D2.9 | Silent | Play the phase as written, 2π times the value (a phase of 1.5 turns is the waveform of 0.5 turns), as MATLAB. |
| D3.7 | Silent; no minimum number of samples | **Chosen**: reject; an event with no samples has no waveform (any event, the ADC phase shape included, R11). |
| D3.8 | Silent; the magnitude, phase and time of an RF event pair up by index (§2.6, §2.8.1) | **Chosen**: reject; some samples have no partner. |
| D2.10, D2.11, D3.9 | "The time sampling points", in RF rasters; cells are defined only for the default raster (§2.6); the slide set: an RF pulse is "regularly sampled or defined by vertices", regular samples at the centres of their dwell periods from the start of the pulse (slide 9), the points of a time vector need not be on the raster edges (slide 4) | **Chosen** (R11, the user, 2026-10-12, the slides normative for timing): a time shape whose times are `(i + 0.5) d` is cells of `d` (any other cannot be a regular pulse, slide 9; that this one is cells is the package's choice, as every writer's regular pulse has this form); any other time shape is points at its times, on or off the raster edges, joined by straight lines of the complex signal (the C++ FIXME's linear interpolation). The split does not depend on the storage (§2.9). Reject a time shape of one sample, times that do not increase, a first time below 0 (no writer writes them). A shape read as points gives a finding where `cpp-siemens` plays it otherwise. |
| D2.12 | Silent | **Chosen** with D2.10, D2.11: cells last N × dwell; points end at the last time (as the writers' block pulses). |
| D4.2 | No `center` in 1.4 | Absent. |
| D4.4 | No `first` and `last` in 1.4 | **Chosen**: reject a 1.4 arbitrary gradient on the default raster: the file has no ends. `spec` then refuses many 1.4 files with arbitrary gradients, which `cpp-siemens` reads; pulseq-checks flags each. |
| D4.5 | No `first` in 1.4 | A time shape that starts at 0: its first sample. **Chosen**: one that starts later: reject, as D4.4. |
| D2.13 | Samples at the centres of the cells (§2.6) | **Chosen**: straight lines between the centres, to `first` and `last` at the edges, as `cpp-siemens` and pypulseq. |
| D2.14 | Silent | 0 where no gradient event plays. With `gradient.nonzero-start-delay` and `gradient.nonzero-end-align` rejected (Q4), every gap inside a block lies between zeros, and a gradient that ends above 0 at its block's end continues into the next block. |
| `shape.oversampled-length` | N − 1 extra points on the edges | All the samples, half a raster apart. Reject an even number of samples (slides 4, 8: the shape starts and ends at cell centres; R11). |
| D2.15, D3.8 | No unit for the ADC phase shape | **Chosen**: rad, as C++ and MATLAB use it, one value for each ADC sample (as `makeAdc` requires); reject a shape of another length. |
| D2.17, D4.6 | The scanner's interpreter may ignore an extension that is not required | Ignore. Each extension is read from the revision that introduced it (P20, section 7.8); in an older file it is unknown and ignored (D4.6). |
| D2.3 | Silent on order | Accept. |
| `extension.required-unknown` | Must reject | Reject. |
| `extension.per-block` | One rotation and one shim per block | Reject two. |
| D2.18, D3.10, D4.6 | A "normalized rotation quaternion", from revision 1.5.1 (spec:567); the specification's own example has a norm of 1 + 2.3e-7 | **Chosen**: from 1.5.1, divide the quaternion by its norm, with a finding when the norm as read is more than 1e-3 from 1, reject a quaternion of norm 0, and rotate the block's gradients (P20). Before 1.5.1, `ROTATIONS` is an unknown extension: ignored and recorded (D2.17, D4.6). |
| D2.19, D4.7 | Lists the labels "supported at the moment" | **Chosen**: ignore an unknown label, with a finding (labels do not change the waveforms). R11: its row stays in the model, and `SequenceData.records` records it (P20 rule 4; `NOSCL`; a 1.4.1 flag in an older file, D4.7). |
| Equal events with different IDs | Silent | Keep both. |
| No scanner values in the file | Not in the file | No change. |
| The signature hash | The `\n` before `[SIGNATURE]` belongs to the signature | As the specification: strip one `\n`. Differs from `cpp-siemens` for CRLF. |
| `signature.invalid` | Must have both | Reject. |
| D1.4 | A word in the examples | Text. |
| D2.2 | Silent; a blank line ends a shape only | Read (R11): no blank line is needed at the end of another section. |

**R11 (2026-10-12).** The user made the slide set that §2.6 cites
(`doc/pulseq_shapes_and_times.pdf`) normative for timing, and set the principle for the rows that
the specification leaves unclear: `spec` implements what the specification and the slides state
clearly, and rejects what no current writer (MATLAB Pulseq, pypulseq) writes. Each rule of `spec`
records its basis (`spec.Rule`), and a rejection that is the package's choice says so in its
message, so a user understands it. The rows above carry R11's refinements.

## 7. Architecture

### 7.1 Layers

One library, in three layers and a base. A layer imports only from the layers below it.

| Layer | Subpackage | Holds | Today's modules |
|---|---|---|---|
| Base | `pulseq_analysis` (top-level modules) | Shared helpers | `_equality`, `_validate` |
| Files | `pulseq_analysis.seqfile` | The "as written" reading, the `spec` reader, the protocol of plugin interpreters (`seqfile.interpreters.Plugin`), `SequenceData`, `SeqFileError`; the pypulseq path of R15 | `reader`, `model` |
| Waveforms | `pulseq_analysis.synth` | The two decoders, the snapshot, the events, the block index, sampling | `decoding`, `scanner`, `events`, `_events`, `_played`, `seq_index`, `seq_utils`, `sampling`, `snapshot` |
| Analyses | `pulseq_analysis.analyses` | The measurements and `load`; SAFE and the `.asc` reader | `loading`, `registry`, `grad_peaks`, `grad_spectrum`, `pns_levels`, `series`, `safe`, `asc` |

- **The rule is enforced.** An import-linter `layers` contract in `scripts/check` (a new dev
  dependency) fails on an import from a higher layer. The code respects the order already:
  `seqfile` and `model` import only `model` and `_equality`, and no waveform module imports an
  analysis module.
- **An interpreter spans two layers.** Its name picks a reader in `seqfile` and a decoder in
  `synth`. `SequenceData` carries the name, so `synth` picks the decoder from the data, and
  `seqfile` knows nothing of decoders. Since P21, `pulseq-cpp-siemens` is a plugin: pulseq-analysis
  does not import it; its module `pulseq_cpp_siemens.interpreter` imports pulseq-analysis and
  provides `CppSiemens` and `CppSiemensDecoding`, found through the entry-point group
  `pulseq_analysis.interpreters`.
- **R3 named the modules** `seqfile/reader.py` (the former `seqfile.py`) and
  `analyses/registry.py` (the former `analyses.py`). The subpackages export nothing yet; R6b
  exports the entry points of 7.3 from them.
- **`load` and `snapshot`** (R14): `load` is in the analyses layer (`analyses.loading`,
  exported as `analyses.load`). The class `Snapshot` stays in the waveform layer: `seq_index`,
  `_events`, `_played` and `sampling` keep their results on it, so it cannot move above them
  under the contract; it holds the `SequenceData` and its decoding, and imports nothing of
  the analyses. `extensions` is removed.
- **The public names change** (for example `pulseq_analysis.events` becomes
  `pulseq_analysis.synth.events`), with no aliases: nothing is released yet, and pulseq-checks
  adapts. The task that moves them (R3) changes no behaviour.
- **A later split** into separate libraries is then mostly a move of the subpackages. It is
  worth doing when a second user needs the files or waveform layers without the analyses, when
  their dependencies diverge, or when their interfaces have held for a release or two.

### 7.2 Stages

1. **Read as written** (shared, Python, R5, P13): the bytes into sections and typed fields,
   without loss: each field's raw text and its value by its column's type, its line number,
   the blank and `#` lines, and the bytes the signature hashes. It rejects only text it cannot
   split into sections and fields. It interprets nothing.
2. **Interpret** (per interpreter):
   - `cpp-siemens`: the version gate (Q1) on the "as written" reading; then the wrapper:
     `load`, the checks of 5.3, and `SequenceData` from the reader's libraries (P14). Its
     decoding is the reader's: `GetBlock`, `decodeBlock` and `gradientsAt`.
   - `spec`: the `spec` reader on the "as written" reading, as section 6 says, into
     `SequenceData`; its decoder in Python (R11).
3. **Find**: in pulseq-checks, not here (P17, 7.4).

The measurements (R14) take the waveforms of one interpreter.

### 7.3 API (Q6)

```python
seqfile.read_as_written(path) -> AsWritten  # the "as written" reading (P13), with line numbers
seqfile.read_seqfile(path, interpreter="spec") -> SequenceData  # .interpreter, .records
seqfile.read_pypulseq(seq, interpreter="spec") -> SequenceData  # a pypulseq.Sequence, written (R15)
synth.decode(data) -> Decoding  # the events and the waveform of each block, by data.interpreter
analyses.load(source, interpreter="spec") -> synth.Snapshot  # the measurements (R14)

# A plugin interpreter by name, or as an object with its settings (P21):
from pulseq_cpp_siemens.interpreter import CppSiemens
seqfile.read_seqfile(path, interpreter=CppSiemens(oversampling="edge"))  # D6.1
seqfile.read_seqfile(path, interpreter=CppSiemens(rotation="apply"))  # D6.2, P20
analyses.load(path, session=Session(soft_delays={"TE": 5e-3}))  # P20, P22 (R16)
```

R6b exports these names from the subpackages (R3 left them empty). `"cpp-siemens"` and
`"spec"` name the objects with their defaults. A setting of `cpp-siemens` follows a setting of
the scanner's interpreter (for example its oversampling mode, D6.1); a result records the
interpreter and its settings. `SeqFileError` is the rejection of one interpreter, with its
code and its reasons: for `spec`, every violation of the specification, not only the first.
A file outside the versions of Q1 raises the "not supported" exception in both.

**The contract with pulseq-checks.** These readings are public and kept stable enough for
pulseq-checks to compare: the "as written" reading with its line numbers; the `cpp-siemens`
reading (the reader's libraries, P14) and its decoding, `gradientsAt` included; `spec`'s
violations; both interpreters' waveforms; and the protocol of plugin interpreters
(`seqfile.interpreters.Plugin`, `synth.Decoding`, and from R16 its version and `session`, P22).
A change to any of them is a change of the contract, noted in `CHANGELOG.md`.

### 7.4 Findings, in pulseq-checks (P17)

pulseq-checks finds each discrepancy that the record documents, with four mechanisms. Each
entry of the records is titled by a condition in a file, so each maps to one of
them. (There was a fifth, a catalogue of MATLAB Pulseq and pypulseq; the user removed it on
2026-10-13, since the records keep only the decisions of the two interpreters. The conditions that
pulseq-checks finds through the second and third mechanisms below, or through the fourth, need no
entry.)

| Mechanism | What it finds | Entries |
|---|---|---|
| Diff of the "as written" reading against the `cpp-siemens` reading and decoding | The reader changes, drops or misreads | D2.1, D5.1, D2.5 (blank line), D3.11, D3.3, D2.6, D2.16, D7.2, D5.5 (shorter), D2.8, D2.9, D3.8 (longer phase), D2.19, D2.2 |
| A condition on the "as written" reading | The reader plays something a value diff cannot show | D2.4, D2.7, D7.1, D7.3, D4.3 (1.4 gradient), D2.10, D2.11 (1), D2.12, D4.2, D7.5, D4.4, D4.5, D2.14, D7.4, D6.1, D2.17, D4.6, D2.18, D3.10, D6.2 |
| `spec`'s violations on the same file | A "must" broken, which the reader plays as written | D1.3, D3.4, D3.5 |
| A comparison of the two interpreters | One rejects and the other reads, or their waveforms differ | D2.3, and every entry above where `spec` differs |

A file that `cpp-siemens` rejects still gets findings: pulseq-checks reads it as written and
through `spec` itself. The float32 finding (D7.2) needs a tolerance, which pulseq-checks sets.
Today's rule names stay as codes where the condition is the same (for example
`raster.gradient-delay`), so pulseq-checks keeps its names.

Categories describe a finding; pulseq-checks grades them: `interpreters-differ`,
`spec-departure`, `cpp-changes-value`, `cpp-default` (D4.4, D6.1).

### 7.5 pulseq-checks

pulseq-checks owns the findings (7.4), their catalogue, severity, profiles, exit codes and
reports. For example:

- "scanner": an error when `cpp-siemens` rejects the file.
- "specification": an error when `spec` rejects the file. This gives back today's strict
  parser, from the `spec` interpreter.
- "portable": an error for each `interpreters-differ` finding.

pulseq-analysis does not change when pulseq-checks makes a policy stricter.

**The hand-off (task C1).** This project writes one document for pulseq-checks,
`docs/findings-for-pulseq-checks.md`, and the user shares it with that project. Nothing is
written in pulseq-checks' repository from here, and its code is not read: what pulseq-checks
does with the document is its own plan. The document gives:

- why the findings move (P17), and what pulseq-analysis no longer reports;
- the contract of 7.3: each public reading, with its module, its type and what it holds;
- the four mechanisms of 7.4, each entry of the records with its mechanism, its
  fixture, and today's rule name where one exists;
- the categories, and the cases that need a choice of pulseq-checks (for example the float32
  tolerance of D7.2);
- the test oracles of this project's flake that a consumer can use (the C++ driver, its
  sanitized build, the MATLAB oracle);
- which readings are still to come, and from which task (R5, R6, R11).

C1 writes its first version once R5 has fixed the "as written" reading. R6 and R11 update it
when their readings are public, and each change to the contract updates it and
`CHANGELOG.md`. Its links name a commit of `main`, so a shared copy stays exact.

### 7.6 The engine of `cpp-siemens`: a replica or a wrapper (R2)

`cpp-siemens` can be built in two ways. Both give the same waveforms; they differ in what is
around them.

| | Python replica | Wrapper of the C++ reader |
|---|---|---|
| Fidelity | As good as the oracle tests prove, fixture by fixture | Exact by construction: float32, `checkRF`'s clamps, the resampling, the misreadings, `gradientsAt`, and quirks not yet found |
| Upstream changes | Ported by hand | A new pinned commit |
| Findings | Recorded while decoding | A diff of the "as written" reading (R5) against what the C++ reader decoded: the C++ reader reports no misreading or clamp, and its rejections are messages, not codes |
| Undefined behaviour | Detected in Python | Detected in Python before the call: in the process, a case either traps (macOS) or reads memory it does not own (Linux) |
| Installation | Pure Python | Compiled wheels for each platform |
| Shared state | None | `SeqBlock` keeps rasters in static variables that each load sets (cpp:807, 1540): one file at a time in a process, behind a lock |
| Work in R6 to R10 | Port each quirk and prove it | The checks for undefined behaviour and the findings diff |

The simulation of the scanner's interpreter (section 7.8: rotations, soft delays, the field of
view), the timeline across blocks, the sampling and the measurements are the package's own in
either case. The "as written" reading, the `spec` reader and the checks for
undefined behaviour are needed in either case.

**R2, the prototype.** On `chore/cpp-wrapper-prototype`:

1. A nanobind extension around `ExternalSequence` at `c746912` (MIT, with its notice), with a
   small API: load a file, decode each block, give the decoded events, the RF magnitude and
   phase after resampling and `checkRF`, and `gradientsAt` at given times.
2. The same output as the driver's `--dump` and `--sample` for each fixture of
   `tests/seqfiles`, read in the process.
3. Wheels built with cibuildwheel in CI for macOS (arm64, x86_64), Linux (manylinux x86_64,
   aarch64) and Windows (x86_64), each installed in a clean environment and run on the fixtures.
4. For each case of undefined behaviour of section 5.3, a check in Python that rejects the file
   before the call, and a run of the fixture of each case that shows the process survives.
5. The static state: which variables, and a lock that makes two loads in threads safe.

Its report adds to this section: what built and what did not, on which platform; the size of
the wheels and the time of the build; any difference from the driver; and a recommendation.
The decision then sets how R6 to R10 are built. The decision is to wrap (P11): R6 builds on
the prototype's code, which until then stays on its branch.

#### R2 report (2026-10-12)

The prototype is `prototypes/cpp-siemens-wrapper` on `chore/cpp-wrapper-prototype`: a nanobind
extension of 584 lines of C++, 380 lines of Python (the API and the checks of 5.3), and its
tests. Its README says how it works.

**The source of the reader.** CMake takes the four files and the licence from
`PULSEQ_SOURCE_DIR` (the Nix store path that flake.nix already fetches), else from
`third_party/pulseq/` (where an sdist would carry them; not done), else from
raw.githubusercontent.com at `c7469123`. It checks the SHA-256 of each file in all three cases.
The files are fetched, not vendored: flake.nix already decided not to copy pulseq into this
repository, and the hashes pin the bytes as tightly as a copy would. The cost is that a build
from the git tree needs the network or `PULSEQ_SOURCE_DIR`. A release to PyPI would put the
files in its sdist.

**What built, and where.**

| Platform | Built and tested | Tests | Wheel | Build and test |
|---|---|---|---|---|
| Linux x86_64 (manylinux_2_28) | CI, cibuildwheel 3.0.0, gcc | 106 passed | 200 KB | 38 s |
| Linux aarch64 (manylinux_2_28) | CI, native ARM runner, gcc | 106 passed | 184 KB | 30 s |
| macOS arm64 | CI, and locally in clean venvs (Python 3.12 and 3.13) | 108 passed | 159 KB | 25 s |
| macOS x86_64 | CI (built on arm64, tested under Rosetta), and locally | 108 passed | 169 KB | 73 s |
| Windows x86_64 | CI, MSVC 19.44 | 107 passed | 150 KB | 75 s |

The times are cibuildwheel's, for the build of one wheel and its tests. A local build on macOS
takes about 6 s. The CI run is 38291077415 of `.github/workflows/cpp-wrapper-wheels.yml`, on
the prototype's branch only. The tests that the runners skip are the comparisons with the
driver, which is not there; `tests/expected_digests.json` stands in for it. Linux also skips the
two locale tests: its image has no locale with a decimal comma. The wheels use the stable ABI
(`cp312-abi3`): one wheel per platform serves Python 3.12 and later (3.13 was tested locally).
Each extension links only the system C++ library.

Two failures on Windows were in the tests, not in the reader:

- Git on the Windows runners turns LF into CRLF on checkout, so the reader hashed other bytes
  for the signature. The workflow now turns that off.
- MSVC's NaN for `nan` in a file has other bits than clang's and gcc's. The digest now counts
  one NaN for all.

With these fixed, each platform gives the same bits as the driver on every fixture, MSVC
included.

**The same output as the driver.** For each of the 89 fixtures (the 85 of `tests/seqfiles` at
`cb138d4`, and 4 new ones for 5.3), the wrapper has the driver's verdict. For the 65 files that it reads, it
gives the driver's `--dump`, compared exactly in float32, and the driver's `--sample` at 770 147
times, compared bit for bit. `tests/expected_digests.json` records this from the driver, so the
wheels compare against it where there is no driver. Two notes:

- **Fused multiply-add.** The reference is a driver built like the wrapper. flake.nix builds
  the driver with the compiler's defaults; on arm64 that fuses multiplies and adds in
  `gradientsAt`. Against that driver all the dumps are identical, but 3 276 sample rows of 47
  files differ in the last bit (at most 2.5e-16 relative). The wrapper builds the reader with
  `-ffp-contract=off`, as an x86_64 build is without FMA: the x86_64 wheel gives the same bits as
  the arm64 one.
- **Signed `char`.** `ExternalSequence::getline` compares a `char` with `EOF`. With an unsigned
  `char`, the default of gcc on Linux aarch64, the reader never ends on any file (shown with
  `-funsigned-char` on macOS). The wrapper builds with `-fsigned-char`. flake.nix's
  `pulseq-cpp-oracle` for aarch64-linux has the same problem. With a signed `char`, a 0xFF byte
  in a file reads as the end of the file.

**Undefined behaviour (5.3).** A build of the driver with AddressSanitizer and
UndefinedBehaviorSanitizer found undefined behaviour in 10 fixtures, plus a loop with no end
(D5.4), and in no other fixture. Every case is in `GetBlock` or `decodeBlock`; none is in `load`.
So the wrapper calls `load`, and the checks then read the libraries that `load` built: the
reader's own reading of the file, reached through pointers to private members that an explicit
template instantiation gives, with no change to the source. Only then does it call `GetBlock`
and `decodeBlock`. The checks need no reader of the text of their own.

| Code | Entry | Fixtures | What the sanitizers report |
|---|---|---|---|
| `ub.shape-missing` | D5.1 | `bad_ref_shape`, `bad_ref_time_shape`, `bad_syntax_shape_no_blank_line` (D3.11), `ub_d05_version_last` | Null reference, cpp:1995, 2177 |
| `ub.rf-time-id-minus-1` | D5.3 | `ub_d22_rf_time_id_minus_1` | Null reference, cpp:2026 |
| `ub.extension-cycle` | D5.4 | `bad_ref_extension_cycle` | No end |
| `ub.shape-decompression` | D5.5 | `ub_d29_longer`, `ub_d29_count_missing` | Heap overflow, cpp:2231 (write), 2222 (read) |
| `ub.shape-empty` | D5.6 | `bad_shape_empty` | Null reference, cpp:1995 |
| `ub.rf-shape-lengths` | D5.7 | `bad_shape_event_length` | Heap overflow, cpp:2288 |
| `ub.rf-time-overrun` | D5.8 | `bad_shape_rf_time_end` | Heap overflow, cpp:2044 |

The prototype also checks two conversions from float to integer that are out of range: an RF
time shape (`ub.rf-time-range`, cpp:2031) and an extended trapezoid time (`ub.gradient-time-range`,
cpp:2182). No fixture has either.

With the checks, each fixture raises `UndefinedBehaviour`, and the process then reads a valid
file as before. With the checks skipped, each in its own process: D5.3 kills Python with a
segmentation fault; D5.4 does not end, and in the process it would hold the reader's lock, so no
other thread could read a file; `bad_ref_time_shape` is rejected; and the other 8 decode,
including RF waveforms read from memory the reader does not own. Silent wrong waveforms are the
most common outcome, so the checks matter more than the crashes suggest.

R4 has since added three of these cases to `tests/seqfiles/undefined/` (`version_last`,
`rf_time_id_minus_1`, `shape_decompress_longer`). R6 uses those, and adds the prototype's
`ub_d29_count_missing`.

The prototype changes 5.3 as follows:

- A file with `[VERSION]` last (D2.1) is a case of D5.1. When reading `[VERSION]` reaches the end of the file, the stream
  fails, and `[SHAPES]` is never read. Every shape is then missing. A file whose blocks use no
  shape reads correctly if it has a `[SHAPES]` section; without one, its definitions are
  skipped too and `load` fails (R4; D2.2).
- **D5.3** is a case of D5.1: the time shape ID -1 is looked up as a shape that does not exist.
- **D5.5** also covers a repeated value with no count at the end of a shape: the reader reads one
  value past the stored values.
- **D5.7** is undefined behaviour only when the phase has fewer samples than the magnitude, or
  when the resampling reads past either shape. With a longer phase, the reader plays the
  magnitude's length (P1 would play it).
- **The plain driver reads both D5.5 files with exit status 0**: it writes past its buffer and
  goes on.

**The static state.**

- `SeqBlock::s_blockDurationRaster` (cpp:89): set by `load` (cpp:807 for binary files, 1540
  for text), and read by `GetDuration`, which `gradientsAt` uses to give 0 after the end of a
  block (cpp:3561). A sequence sampled after another file has loaded would use the other file's
  raster.
- `SeqBlock::s_gradientRaster` (cpp:90): 10 µs, never written (`gradient.raster`).
- `ExternalSequence::print_fun` (cpp:23): one print function for the process.
- The C locale: `sscanf` reads every number by `LC_NUMERIC`. With a decimal comma, `0.5` reads
  as 0. A Python program can set the locale; the driver runs in its own process with "C".

Each call into the reader holds one mutex, with the GIL released. It sets
`s_blockDurationRaster` to its own sequence's value, collects the messages in a buffer of its
own, and runs with the "C" locale in its thread (`uselocale`; `_configthreadlocale` on Windows).
The tests read and sample three files, two with different rasters, in 6 threads, 12 times each,
and get the values of one thread. A sequence sampled after another load keeps its values, and a
process locale with a decimal comma does not change what the reader reads.

**Differences from the driver.** None in the values. In scope, the wrapper refuses a binary
Pulseq file and a folder of three files (`ExternalSequence::load` reads both), and a version
outside 1.4.0–1.5.x (Q1; the driver reads `bad_version_unsupported_1_6.seq`).

**Residual risks.**

1. **A case the checks miss ends the process, or corrupts it silently.** In the process there is
   no timeout and no exit status. The cases are what ASan and UBSan find on the fixtures and on
   four new files; nothing guarantees there are no others. Mitigations: fuzz the checks
   against the sanitizer build of R4; or, for files from unknown sources, run the wrapper in a
   worker process.
2. **Files older than 1.4.** For these, `load` itself calls `GetBlock` (cpp:1663), so a cycle
   in an extension list does not end inside `load`, before any check. The prototype has no gate
   on the version before `load`. R6b needs one, from the "as written" reading (R5).
3. **The scanner's build is not known.** The wrapper matches a build on x86_64 with a signed
   `char` and no FMA; MSVC's `/fp:precise` gives the same bits on the fixtures. `long` is 32
   bits on Windows (it holds the trapezoid times), which matters only past 2^31 µs.
4. **Process-wide state outside the lock.** The global C++ locale (the reader's
   `istringstream` reads the definitions with it), and any other code in the process that calls
   `ExternalSequence::SetPrintFunction`.
5. **Findings.** The reader reports no misreading or clamp, and its rejections are messages. The
   findings need a diff of the "as written" reading against what the reader decoded (as the table of
   7.6 says).
6. **Release cost.** Five wheels per release from a CI matrix, where the package today is pure
   Python. An sdist build needs the network unless it carries the source.

**Decision: wrap, in the process (P11).** The wrapper gives the reader's output bit for bit. That includes its
float32 arithmetic, `checkRF`, the resampling and its artefacts, and `gradientsAt`. It needed
about 1 000 lines and a day of work, and it reaches quirks that no oracle test has found yet. A
Python replica would have to reproduce float32 rounding and the order of operations step by step
(P6 computes in float64, so it would only ever be close), and every quirk ported by hand would
need its own proof.

A worker process would survive a case that the checks miss, at the cost of more code and slower
calls; the checks are needed either way, so the wrapper runs in the process. For it the checks of
5.3 are safety-critical: a missed case costs the process, not just a wrong finding. So R6:

- moves the prototype into the package, with its build flags and its lock;
- fuzzes the checks against R4's sanitizer build;
- gates the version with the "as written" reading (R5) before `load`.

The oracle of flake.nix gets the same flags as the wrapper (`-fsigned-char -ffp-contract=off`)
in its own task, R13.

### 7.7 The package `pulseq-cpp-siemens` (P12)

- **What it holds:** the nanobind extension of the R2 prototype around `ExternalSequence` at
  `c746912` (MIT, with its notice), the checks of 5.3, the lock and the locale handling, and a
  small Python API (load, the libraries as read, decode a block, `gradientsAt`).
- **Where:** `packages/pulseq-cpp-siemens/` in this repository, with its own `pyproject.toml`
  (scikit-build-core and CMake), sharing the flake, the fixtures and CI.
- **Wheels:** cibuildwheel for macOS (arm64, x86_64), Linux (manylinux x86_64, aarch64) and
  Windows (x86_64), stable ABI `cp312-abi3`; the sdist carries the reader's files. It is
  released only when the pinned commit or a check changes.
- **The plugin (P21, the user, 2026-10-13):** the package is also the `cpp-siemens`
  interpreter of pulseq-analysis. Its module `pulseq_cpp_siemens.interpreter` holds `CppSiemens`
  (the settings, `read` and `decode`), the adapter from the reader's libraries to the model
  (`read_cpp_siemens`, `CODES`) and `CppSiemensDecoding`, and its `pyproject.toml` declares the
  entry point `cpp-siemens` in the group `pulseq_analysis.interpreters`. `import
  pulseq_cpp_siemens` imports only the reader; only `pulseq_cpp_siemens.interpreter` imports
  pulseq-analysis, and pulseq-analysis imports it only through the entry point, when the name
  `cpp-siemens` is asked for.
- **pulseq-analysis** stays pure Python and has no reference to the package (P21): without it,
  `spec` works and the name `cpp-siemens` is a `ValueError` (no installed interpreter has it).
  A user installs both distributions.
- **The dependency on pulseq-analysis:** decided at release time (the user, 2026-10-13). Until
  then the package's dependency group `analysis` (not in the published metadata) takes
  pulseq-analysis from this repository (`[tool.uv.sources]`, `../..`, editable), so that the
  tests of the plugin run against the same commit; `scripts/check` runs them in the package's
  environment. Without pulseq-analysis, as in the wheel tests of cibuildwheel, the tests of the
  plugin are not collected (`tests/conftest.py` of the package). How a release gets the wheels
  (from an index, or this source) is decided at release time (the user, 2026-10-12).

### 7.8 Scanner-side settings (P20)

`docs/plans/scanner-settings-study.md` found that the reader applies none of the information
that the scanner's interpreter acts on, and that no driver or binding calls the reader's hooks.
`cpp-siemens` therefore gives the sequence as exported: logical axes at the isocentre, each
block's stored duration, one repetition, no trigger waits, unrotated gradients, one RF channel,
and ppm offsets not weighted. The mechanisms are of two kinds:

- **content of the file** that the reader leaves to the scanner: ROTATIONS and RF_SHIMS;
- **inputs of the scanner session**, which are not in the file: the values of soft delays, the
  orientation, position and gradient scaling of the field of view, the system frequency for the
  ppm terms, the number of repetitions (`ONCE`), and when input triggers arrive.

The rules (the user, 2026-10-12):

1. **Each interpreter's default is its own source, with a neutral scanner session**: the
   sequence as exported, as above. This is a defined case, not a missing value.
2. **Content of the file follows each interpreter's source, and `spec` gates it by version.**
   `spec` applies a mechanism only from the revision of the format that introduced it; in an
   older file the section is an unknown extension, ignored as D2.17 says and recorded (D4.6).
   `cpp-siemens` gives the reader's output, which reads these extensions by name in any version,
   and offers the package's simulation as an opt-in setting (`CppSiemens(rotation="apply")`), as
   `CppSiemens(oversampling=...)` already does for D6.1.

   | Mechanism | Introduced in | Source |
   |---|---|---|
   | `TRIGGERS` (the first generic extension) | 1.3.0 | spec:109 |
   | Labels (`LABELSET`, `LABELINC`) | 1.3.1 | spec:517 |
   | The flags `PMC`, `NOROT`, `NOPOS`, `NOSLC`, `ONCE` | 1.4.1 | spec:526 |
   | Soft delays (`DELAYS`) | 1.5.0 | spec:545 |
   | `ROTATIONS`, `RF_SHIMS`, `RequiredExtensions` | 1.5.1 | spec:567, 584; cpp:784, 1505 |

   The package reads 1.4.0 to 1.5.x (Q1), so only the last three rows are gated in practice.
3. **Scanner-session inputs are one `Session`, the same for both interpreters**, for example
   `Session(soft_delays={hint: value}, fov=..., repetitions=..., b0=...)`, given to `load` and the
   timeline (R14). `cpp-siemens` uses the reader's hooks where they exist
   (`setActualSoftDelay_ru`, the position helpers); `spec` computes the same quantity by the
   specification's rule (for example `input / factor + offset`); a test checks that they agree.
   The session reaches a plugin through `Plugin.decode(data, session=None)` (P22).
4. **Every result records what was applied, and warns only where content of the file was left
   unapplied.** A result records the interpreter and its settings, the session values used, and
   the mechanisms that the file uses that were left at the default (for example "rotations
   present, not applied", "soft delays at their stored durations"). A `ScannerSettingWarning` is
   emitted only when the file's own content is not applied: today, `cpp-siemens`'s unrotated
   default for a file that plays a rotation. A neutral session is recorded, not warned about.
   This warning describes the package's measurement, not the file, so it is consistent with P17.
5. **A setting is offered only when a measurement depends on it.** Rotations, soft delays and the
   orientation and gradient scaling of the field of view get settings (they change gradient
   measurements, the timeline, and PNS on physical axes). RF shims, the ppm terms and the RF and
   ADC position offsets change nothing the package measures: recorded, no setting. Repetitions and
   trigger waits are recorded until a measurement needs them.
6. **The simulation is the package's own, one implementation per mechanism, shared by both
   interpreters**: it lives in pulseq-analysis, which the plugin may import (P21), and documented as a simulation. `cpp-siemens` uses the reader's own helpers
   where they exist (`rotate_vec3_by_quat`), so that its arithmetic is the reader's. The order of
   the field-of-view rotation and ROTATIONS is given by no source; the documentation states the
   order the package uses.
7. **The records are part of the contract with pulseq-checks** (section 7.3): the settings, the
   session values, and the mechanisms left at the default. A change to them goes in
   `CHANGELOG.md` and the document of C1.
8. **A setting that addresses something the file does not have is an error.** A setting that
   names content of the file (for example `soft_delays={"TE": ...}`) raises `SettingError` (a
   `ValueError`, naming the setting, the interpreter, the file's version and the reason) when the
   file has no such content under the interpreter: under `spec` because the version predates the
   mechanism, or because no soft delay has that hint; under `cpp-siemens` because the reader
   attached nothing that matches. Modes and session-wide values (`rotation="apply"`,
   `oversampling`, the field of view, `b0`, `repetitions`) stay valid on any file, and the result
   records what they applied (for example "rotation: apply, 0 blocks rotated"). A setting that the
   interpreter does not have (for example `rotation=` for `spec`) is a `TypeError` when the
   interpreter object is made.

**Decided (the user, 2026-10-12):** `CppSiemens(rotation="apply")` follows the reader. It rotates
each rotation that the reader attaches to a block (`GetBlock` reads ROTATIONS by name, in any
version), also in a file older than 1.5.1; it is not gated by version as `spec` is. What the
scanner's interpreter does with a rotation in a file older than 1.5.1 is not known (no source says),
and `docs/usage.md` and D6.2 say so.

**Where the rotation record and warning live (the user, 2026-10-12, in R9; done in R14):** the
decoding of `cpp-siemens` records what it applied (`CppSiemensDecoding.rotation_record`: the
setting, the blocks with a rotation, those that are not the identity, and those rotated), and
`RotationRecord.warning()` gives the `ScannerSettingWarning`; the decoding does not emit it.
R14's `load` no longer refuses the rotation extension, keeps the record on the snapshot
(`Snapshot.rotation_record`) and emits the warning. The measurements take the rotated gradients
from the decoding's `gradients_at` (`synth._played`); the package does not rotate.

**Further decisions of the study:**

- Soft delays: by hint, as the specification and MATLAB; the duration rounded to the block
  duration raster, as MATLAB's `round`; `SettingError` for an unknown hint (rule 8) and for a
  negative duration. The decoding reports both the stored and the actual duration of a block;
  the timeline uses the actual one, which is the stored one by default (a change of the contract
  of section 7.3).
- The field of view: an orientation and a gradient scaling, the identity by default (a
  transversal slice at the isocentre). No setting for the position offsets or the ppm terms.
- New record entries: the flag `NOSLC` (the specification's spelling, spec:520, 537) against
  `NOSCL` (the reader, MATLAB and pypulseq; the reader drops `NOSLC` with a warning), an upstream
  report to consider; D4.6, an extension used in a file older than the revision that introduced it
  (the reader and MATLAB read it by name, the specification has no such extension).

## 8. D2.3: `[EXTENSIONS]` as the last section

The C++ reader finds each section through an index of the lines that start with `[`
(cpp:1762-1769, 1202-1211). It cannot find the end of `[EXTENSIONS]` when no such line follows,
and it fails with "failed find the end of the section while reading EXTENSIONS". The same file
with a `[SIGNATURE]` section at the end is read.

Both writers write `[EXTENSIONS]` before `[SHAPES]` and `[SIGNATURE]` (MATLAB `write.m`,
pypulseq `write_seq.py`). `[SHAPES]` is written only when there is a shape, and `[SIGNATURE]`
only when the signature is on, which is the default of both. So `[EXTENSIONS]` is last only in
a sequence with no shape (no RF, no arbitrary gradient or extended trapezoid, no ADC phase
shape) that is written with the signature turned off.
`tests/seqfiles/oracle/koma_v1.5_unknown_ext.seq` is such a file: written by PyPulseq, six
blocks of labels only, with no shape and no signature.

- `cpp-siemens` rejects the file, with the code `section.extensions-last`; `spec` reads it
  (the specification does not fix the order of the sections). pulseq-checks reports an
  `interpreters-differ` finding.
- The test of the C++ oracle drops the file from `ORACLE_KNOWN_WRONG`; the reader and
  `cpp-siemens` then agree.
- The record's D2.3 says why, and that the writers produce such a file only with the signature
  off.
- Worth reporting upstream (pulseq/pulseq), section 12.

## 9. Verification

- **`cpp-siemens` against the driver.** The wrapper's dump and samples against the driver's
  `--dump` and `--sample`, bit for bit, on each fixture and on each platform's wheel
  (`expected_digests.json`, the R2 report). R13 (#105) builds the driver with the wrapper's flags.
- **The checks of 5.3, fuzzed.** They are safety-critical: a case they miss costs the process.
  Files generated from the grammar of `.seq` (with values at the edges and the shapes of 5.3),
  seeded, each run through R4's sanitized oracle; the test fails on a file that the oracle
  flags and the checks pass. A seeded set runs in CI; a longer run comes before each release
  of `pulseq-cpp-siemens`. R6a sets the sizes.
- **A sanitizer build of the C++ oracle.** `pulseq-cpp-oracle-sanitized`, built with ASan,
  UBSan and `_GLIBCXX_ASSERTIONS`, in the CI devShell. Its verdict "undefined behaviour" makes
  section 5.3 reproducible, whatever an ordinary build does.
- **`spec` readings.** Each row of section 6 has a fixture and a test that cites the
  specification. MATLAB's `waveforms_and_times` is a second opinion where it follows the
  specification (for example the gradient raster, D2.10, D2.11, the oversampled gradient), not a reference.
- **The records.** Each entry of `docs/discrepancies.md` gives what `spec` does, and the record
  of `cpp-siemens` gives its rule and each exception, each with a fixture and a test of it. The tests of the findings (each disagreement of the four sources
  has a finding, and each finding matches a disagreement) are pulseq-checks' (7.5).

## 10. Tasks

| Task | Branch | Result |
|---|---|---|
| R1 | `docs/parser-redesign` | This plan. Done (#101). |
| R2 | `chore/cpp-wrapper-prototype` | A prototype of `cpp-siemens` as a wrapper of the C++ reader, and its report (7.6). Done (#104): the decision is to wrap (P11). |
| R3 | `refactor/layers` | The modules moved into the subpackages of 7.1, and the import-linter contract. Done (#102). |
| R4 | `chore/sanitized-oracle` | The sanitizer build of the C++ oracle, and its verdict on each fixture. Done (#103). |
| R5 | `refactor/as-written` | **Done (#108).** The "as written" reading (7.2, stage 1; P13), and today's parser rebuilt on it. No change of behaviour: a baseline compares the two. |
| R6a | `chore/pulseq-cpp-siemens-package` | **Done (#109).** `pulseq-cpp-siemens` from the prototype (7.7): `packages/pulseq-cpp-siemens/` with its own `pyproject.toml`, the checks of 5.3, the lock and the locale handling; its wheels for the five platforms; its build in the devShell and its tests in `scripts/check`; the fuzzing of the checks against R4's sanitized oracle (section 9). It needs only R2 and R4, so it runs in parallel with R5. |
| R6b | `feature/cpp-siemens` | **Done (#111).** The `cpp-siemens` interpreter in pulseq-analysis, on R6a: the version gate on the "as written" reading, `SequenceData` from the reader's libraries (P14), the rejection codes (5.2, 5.3), the `interpreter` argument, the exports and the contract (7.3). Each rule of today becomes a rejection of `cpp-siemens`, moves to `spec` (R11), or is removed. The record's "Package" text for `cpp-siemens`, and the new D2.2, follow; pulseq-checks adapts. |
| R7 | — | Moved to pulseq-checks (P17): the findings of D7.2, `shape.range`, D2.8, D2.9, D3.8, D2.10 to D2.12. |
| R8 | — | Moved to pulseq-checks (P17): the findings of the gradient raster, D5.5, D4.4, D4.5, D2.13, D2.14, D6.1. |
| R9 | `feature/rotations` | **Done (#115, #119).** D2.18, D6.2 (P20, section 7.8): the quaternion of each block in both readings and decodings; `CppSiemens(rotation="apply")` and `spec` (from 1.5.1) rotate each block's gradients by it; the records of rule 4 for rotations. The `cpp-siemens` part is done: `CppSiemensDecoding.rotations`, `gradients_at` rotated with the reader's `rotate_vec3_by_quat` (checked against MATLAB), `rotation_record` and its `ScannerSettingWarning`, and `rotate_vec3_by_quat` and `block_rotations` in pulseq-cpp-siemens. The `spec` part is done (`feature/rotations-spec`): `SpecDecoding.gradients_at` (the gradients of each block, as `CppSiemensDecoding` gives them), rotated from 1.5.1 by the model's normalized quaternion with the package's own `decoding.rotate` (pure Python, the active rotation), `SpecDecoding.rotations` and `rotation_record` (setting `"apply"`, never a warning); checked against `CppSiemens(rotation="apply")` and against MATLAB; a file older than 1.5.1 is not rotated. `load`'s part moved to R14 (7.8). |
| R10 | — | Moved to pulseq-checks (P17): the findings of `version.invalid`, D2.5, D3.2, D3.11, D2.4, `[DELAYS]`, D3.3, D2.6, D3.1, D3.5, D3.6, D2.16, D3.4, D7.3, `blocks.empty`, `signature.invalid`, D2.2. |
| R11 | `feature/spec-interpreter` | **Done (#117).** The `spec` reader (section 6) on the "as written" reading, with every violation in its rejection, and its decoder in Python, adapted from task 2's `events.py`, with its fixtures. The record's "Package" text for `spec` follows. |
| R12 | — | Moved to pulseq-checks (P17): the comparison of the two interpreters, and the four-source test. |
| R13 | `chore/oracle-build-flags` | The C++ oracle of flake.nix built with `-fsigned-char -ffp-contract=off`, as the wrapper (7.6). Done (#105). |
| R14 | `feature/load-on-interpreters` | Task 5a re-planned (P15): `load` on an interpreter's output. Done (#126): `analyses.load(source, interpreter="spec")` reads through `spec` or a plugin interpreter (P21) and gives a `synth.Snapshot` of the `SequenceData` and its decoding. The measurements take the gradients only through the protocol `synth.Decoding` (`synth._played`): `gradient_points` for each decoded event (for `cpp-siemens`, the reader's decoding and the points of its `gradientsAt`), and `gradients_at` for a rotated block or a block with an event after its end; between blocks, the package's waveform for every interpreter (D2.14, D7.4). `load` no longer refuses the rotation extension (`extensions` is removed), keeps the decoding's `rotation_record` on the snapshot and emits `RotationRecord.warning()` (R9, 7.8). A baseline of the pypulseq-based `load` explains each difference (CHANGELOG). The tests through `cpp-siemens` are in the plugin's tests. Task 2's C++-replica code was already retired by R11; R14 also removes the pypulseq path of `seq_index` and `seq_utils`, and `seq_index.rf_events`/`grad_events`/`adc_events`. |
| C1 | `docs/findings-hand-off` | **Done (#118).** The document for pulseq-checks of 7.5, `docs/findings-for-pulseq-checks.md`, which the user shares with that project. R6 and R11 update it. |
| R15 | `feature/pypulseq-via-seq` | **Done (#116).** Task 4 re-planned (P16): a `pypulseq.Sequence` written to `.seq` text, then read through an interpreter. |
| R16 | `feature/scanner-session` | **Done.** `synth.Session` (soft delays by hint, the field of view's rotation as a quaternion and its gradient scaling), `SoftDelayRecord`, `FovRecord` and `SettingError` (rules 3 to 8), for both interpreters, with the shared simulation in `synth.scanner`; the decoding's stored and actual durations, which the measurements use; `load(..., session=...)`. P22: `seqfile.PROTOCOL` 1 and `Plugin.decode(data, session=None)`; `cpp-siemens` sets the soft delays with the reader's hook `setActualSoftDelay_ru` and turns with its `rotate_vec3_by_quat`, and records what the reader ignores. Decisions of the user (2026-10-13): MATLAB's order R_fov R_block S g (D2.20); `NOSLC` only for `spec` (D2.22); a `SettingError` for a soft delay of a block with an event, a block with two soft delays, and a hint with two numeric IDs (D2.21); the orientation as a quaternion. The record has D2.20 to D2.22, D6.3 and D6.4; C1's document has its section 2.8. |
| R17 | `feature/cpp-siemens-as-plugin` | **Done (#121).** P21: `cpp-siemens` as a plugin of pulseq-analysis. The entry-point group `pulseq_analysis.interpreters`, the protocols `seqfile.interpreters.Plugin` and `synth.Decoding`, the adapter, `CppSiemens` and `CppSiemensDecoding` in `pulseq_cpp_siemens.interpreter`, the tests that read through `cpp-siemens` in the package's tests, and the docs. Then the cpp-siemens record of `docs/discrepancies.md` moves to the package: done (`docs/record-split`, section 11). |

R6 is split in two (2026-10-12): R6a, the package, needs only R2 and R4 and runs in parallel
with R5; R6b, the interpreter, needs R5 and R6a. Elsewhere in this plan, "R6" means both, and
a part of it names R6a or R6b. R5 needs R3. R9 needs R6. R11 needs R5 and R6 (the `interpreter`
argument). R6, R9 and R11 share `docs/discrepancies.md` and `TESTS.md`, so they merge in turn.
R14 needs R6 and R9; the `spec` interpreter joins `load` when R11 is done. R15 needs R6. R16
needs R14 (the `Session` acts on the timeline). C1
needs R5; R6 and R11 update its document. R17 and R14 both change `synth.decoding` and run in
parallel (the user, 2026-10-13): the one that merges second adapts; R14 takes the points of a
gradient event from `Decoding.gradient_points`, with no test of the decoding's type.

Tasks 4, 5a, 5b and 6 of `docs/plans/own-parser-tasks.md`:

- Task 4 is replaced by R15, and task 5a by R14 (P15, P16).
- Task 5b (pypulseq optional) follows R14; it can run alongside R16, since they touch
  different files. Task 6 (the documentation) waits until a release candidate is prepared (the
  user, 2026-10-13).
- On hold (the user, 2026-10-13): `docs/plans/cpp-siemens-verdict-predictor.md` (#112) and the
  flowcharts of the records (branch `docs/discrepancy-flowcharts`).

## 11. Documents

- `docs/discrepancies.md`: the record of `spec` (the user, 2026-10-13). Each entry keeps its
  source table (the specification, with the slides, and the C++ reader), its example, what
  `spec` does and why. Its section 4, the review of the former strict reader against the order
  of preference, was removed; commit `49a7e2c` is the last that has it. Its appendix keeps the
  scripts of the acceptance matrix and the figures, not the matrix itself.
- `docs/specification.md`: what `spec` does and why, by rule, as the record of `cpp-siemens`
  gives it (the user, 2026-10-13): its rule (Q4), each place where the rule does not decide (the
  version gate, each version as its own format, where the specification disagrees with itself,
  the readings and the rejections of choice where it is silent, the settings, the values in the
  model), and the codes of `spec.RULES`, with the IDs of `docs/discrepancies.md`.
- `packages/pulseq-cpp-siemens/docs/specification.md`: the record of `cpp-siemens` (the user,
  2026-10-13): its rule (P1 to P3) and each exception (the version gate, the undefined behaviour,
  the settings, the reader's values in the model, the codes), with the IDs D5 to D7. `CODES` and `UndefinedBehaviour.entry` cite it. Which finding pulseq-checks gives
  is pulseq-checks' documentation.
- `docs/usage.md`: the interpreters, the "as written" reading, each interpreter's rejections,
  and the contract of 7.3; a pointer to pulseq-checks for the findings.
- **The record regrouped by kind of decision (the user, 2026-10-13).** The entries are grouped
  by the kind of decision, not by the order of discovery: D1 to D4 in `docs/discrepancies.md`
  (the specification is unclear, D1; silent and `spec` reads the file, D2; silent and `spec`
  rejects by choice, D3; versions, D4) and D5 to D7 in the record of `cpp-siemens` (the
  undefined behaviour of the C++ reader, D5; the settings of the scanner, D6; the reader's values
  in the model, D7). An ID names a decision of an interpreter, not a condition, so a condition on
  which each interpreter decides has two IDs. An entry exists only where `spec` decides what the
  specification leaves unclear or silent, or where `cpp-siemens` departs from the C++ reader;
  where the specification states a rule and each interpreter follows its own core rule, there is
  none. The rows of MATLAB Pulseq and pypulseq left the source tables, and so did mechanism M5 of
  the hand-off (7.4). The old IDs, numbered in the order of discovery, are mapped to the new ones in the appendix of the
  record and by `scripts/record_ids.py`; the plans of finished tasks keep the old IDs.
- `CHANGELOG.md`: the files that `cpp-siemens` now accepts, and those it now rejects (an ADC
  dwell with a decimal point, an arbitrary gradient off 10 µs, D2.3, a quaternion off unit norm).
- `own-parser-tasks.md`: this plan supersedes the order of preference of its section 12 where
  they differ, and its tasks 4 and 5a (R15, R14); R14 and R15 mark them there.

## 12. Upstream reports to consider

The user decides whether to file each, on pulseq/pulseq:

- D2.2 and D2.1: reading the last section to the end of the file fails the stream, and the
  reader then skips the sections that it reads after it (a file with no `[SHAPES]` section
  loses its definitions).
- D2.3: `[EXTENSIONS]` as the last section is rejected.
- D5.8: the guard `if (tc < waveform_t.size())` lets the index reach the size; the reader
  then reads past the samples. MATLAB writes such shapes for RF pulses of 4 samples or fewer.
- D5.6: an empty shape is undefined behaviour.
- D5.5: `decompressShape` writes past its buffer when a shape decompresses to more samples than
  `num_samples`.
- D2.16: `-100.5` as a soft delay offset is misread as -100 and a factor of 0.5.
- `ExternalSequence::getline` compares a `char` with `EOF` (cpp:2301, 2322). With an unsigned
  `char` (gcc on Linux aarch64) the reader never ends on any file; with a signed one, a 0xFF
  byte ends the file (7.6).
- D5.5: `decompressShape` reads one value past the stored values when a shape ends in a
  repeated value with no count (cpp:2222).

## 13. Risks

- **What C++ plays is not always visible.** `ExternalSequence` decodes blocks; the scanner's
  interpreter plays them. Where the decoded block is not enough to know the waveform (D7.4,
  after the block end and between blocks), `cpp-siemens` shows what `gradientsAt` gives and
  says so in the finding.
- **The "as written" reading and the C++ reader must agree on structure.** pulseq-checks'
  diff is only as good as their agreement on which field is which; the contract of 7.3 and
  pulseq-checks' tests keep the differences deliberate.
- **pulseq-analysis alone reports no discrepancies.** A user who wants them runs
  pulseq-checks; pulseq-analysis gives only a rejection's code and reasons.
- **The document of C1 can fall behind the code.** R6, R11 and each change to the contract
  update it in the same PR.
- **The `spec` interpreter's choices** are the package's, not the specification's. Each is
  listed in section 6 and in the record, and pulseq-checks names it where it matters.
- **pulseq-checks.** It relies on today's rejections. R6 changes them at once; the
  "specification" profile of 7.5 restores them from the `spec` interpreter, and pulseq-checks
  adapts in the same release, and gains the findings (P17).
- **Reproducing misreadings** makes `cpp-siemens` read some files in a way a person would not
  expect. The record says why, and pulseq-checks reports each one.
