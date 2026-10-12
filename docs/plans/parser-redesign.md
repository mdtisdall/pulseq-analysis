# Plan: the parser redesign — two interpreters, and findings in place of checks

Branch `docs/parser-redesign`. This plan changes the goal of `read_seqfile` and of the decoding
of task 2 (`docs/plans/own-parser-tasks.md`, merged in #100). It comes before tasks 4, 5a, 5b
and 6 of that plan, and section 10 says how they fit.

The entries D01a to D55 are those of `docs/discrepancies.md` (the record). "The C++ reader" is
`ExternalSequence` of pulseq/pulseq at `c746912`, the reader of the scanner's interpreter on
Siemens systems. "cpp:N" is a line of `src/ExternalSequence.cpp` at that commit. "The
specification" is the Pulseq specification 1.5.3 (draft), cited by section. In this plan an
"interpreter" is one of the package's two ways of reading a file (`cpp-siemens`, `spec`); the
program on the scanner that plays a Pulseq file is "the scanner's interpreter".

## 1. Goal

pulseq-analysis turns a Pulseq file into waveforms, and it measures them. It does not judge
whether a file is valid, and it performs no checks. It reads a file through one of two
**interpreters**:

- **`cpp-siemens`** (the default): a faithful replica of the C++ reader, the reader of the
  scanner's interpreter on Siemens systems, with all its limits. If the C++ reader makes a
  waveform, `cpp-siemens` makes the same waveform, including the reader's misreadings, clamps,
  resampling, defaults and its 10 µs gradient raster. If the C++ reader rejects a file,
  `cpp-siemens` rejects it. Its engine is a Python replica of the C++ reader or a wrapper
  of it; the prototype of task R2 decides (7.6).
- **`spec`**: as true as possible to the written specification. It reads each field as the
  specification types it, takes any raster that the file defines, and gives no waveform where
  the specification says a file "must" not be as it is. Where the specification is silent, it
  makes a documented choice (section 6).

Where the sources read a file differently, the package reports a **finding**: data that it
returns with its result. A finding has no severity; pulseq-checks maps finding codes to
warnings or errors. Findings come from two places:

- **The interpreters differ.** The package can run both interpreters and compare them: a file
  that one rejects and the other reads, or that gives different waveforms. This needs no
  hand-written test of the file.
- **MATLAB Pulseq or pypulseq differ.** These stay test oracles, not interpreters. A
  hand-written test of the file gives each such finding, and the oracle tests check the tests.

This replaces the order of preference of 2026-10-09 (C++ reader, then the specification, then
MATLAB, then pypulseq). The record's section 4 reviews the package against that order; it is
rewritten for this goal (section 11).

## 2. Decisions (the user, 2026-10-12)

| ID | Decision |
|---|---|
| P1 | `cpp-siemens` makes the waveform that the C++ reader makes. |
| P2 | `cpp-siemens` rejects a file that the C++ reader rejects. |
| P3 | Where the C++ reader misreads a row and still makes a waveform (D14 (3), D16), `cpp-siemens` reproduces the misreading, with a finding. |
| P4 | Behaviour of the C++ reader that depends on the build (undefined behaviour: reads out of bounds, crashes in one build only) is decided case by case, and each case is its own kind of finding (section 5.3). |
| P5 | An RF time shape whose points are not on the raster edges: `cpp-siemens` resamples it as the C++ reader does, artefacts included, with a finding. Only a shape where the resampling reads past its samples is undefined behaviour (P4). |
| P6 | float32: the package computes in float64 and gives a finding where float32 rounding in the C++ reader changes a value noticeably (D18). |
| P7 | Where the C++ reader uses a sentinel or a mode that the scanner's interpreter can set (D39 `FLOAT_UNDEFINED`, D43 oversampling), `cpp-siemens` follows the reader's default, with a finding. |
| P8 | Findings are data on the result. Python warnings are off by default; a caller can ask for them. |
| P9 | `[EXTENSIONS]` as the last section (D46): `cpp-siemens` rejects it, as the C++ reader does, with its own code (section 8). |
| P10 | Two interpreters: `cpp-siemens`, a replica of the C++ reader with all its limits, and `spec`, as true as possible to the specification. Other rasters are the `spec` interpreter's; there is no "C++ reader on any raster" interpreter for now. |

The choice between "C++ reader first" and "specification first" is no longer open, so
`docs/plans/spec-first-study.md` is not needed. It is not committed; its readings of the
specification feed section 6.

## 3. Answers (the user, 2026-10-12)

| ID | Question | Answer |
|---|---|---|
| Q1 | Versions outside 1.4.0–1.5.x (D03) | Both interpreters refuse them as **not supported by the package**: a separate exception (for example `NotImplementedError`), which says nothing about the file. |
| Q2 | The undefined behaviour of the C++ reader (section 5.3) | `cpp-siemens` rejects each case, with its own code. |
| Q3 | Rotations (D49) | `cpp-siemens` applies the rotation to the gradients, as the scanner plays them; `load` no longer refuses the rotation extension. `spec` applies it too. |
| Q4 | `spec` where the specification says "must" | No waveform: `spec` rejects the file. `compare` gives the finding that `cpp-siemens` reads it. |
| Q5 | `spec` where the specification is silent | Section 6, row by row. |
| Q6 | The API (section 7.3) | The functions take an interpreter by name or as an object: `interpreter="cpp-siemens"` by default, or `interpreter=CppSiemens(oversampling="edge")` for its settings. |

Two choices give a finding although the file reads: a repeated section or definition (D10,
D12), and an RF time shape read as points (D35, D36), where the reading goes beyond what the
specification states.

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

"To establish" marks an entry where what the C++ reader plays is not yet known in enough detail
to reproduce; the task that implements it establishes it with the oracle first.

## 5. The `cpp-siemens` interpreter

### 5.1 The entries

| Entry | Class | Today | `cpp-siemens` |
|---|---|---|---|
| D01a–c | Agree | 12, 7, 9 fields | No change. |
| D02 | Reject | Rejects | No change. |
| D03 | Scope | Rejects outside 1.4.0–1.5.x | The "not supported" exception (Q1). |
| D04 | Play | Rejects `5.0` | Read `5.0` as 5, as C++. Finding. |
| D05 | Play / UB | Any order | Any order; `[VERSION]` as the last section crashes C++: reject (5.3). |
| D06 | Reject / Play | Blank or `#` line | A blank line inside a table ends it, and C++ never reads the rows after it (only `[` lines start a section): drop them, a misreading (P3), with a finding. A `#` line inside a table is read as a row and fails: reject. `[VERSION]` and `[EXTENSIONS]` skip both. |
| D07 | Play | Rejects | No blank line after a shape: C++ stops reading `[SHAPES]`, and the later shapes are not read (cpp:939, 955-958, 978). Reproduce; a later reference to a lost shape then follows D21. Finding. |
| D08 | Play | Rejects | Ignore an unknown section, as C++. Finding. |
| D09 | Play | Rejects | Ignore `[DELAYS]` from 1.4.0, as C++. Finding. |
| D10 | Play | Rejects | A section twice: the last, as C++. Finding. |
| D11 | Reject / Play | Presence and value | Reject what C++ rejects (a missing raster; nan and inf; 0 or negative `GradientRasterTime`); accept the other values as C++ does. To establish what C++ plays with a raster of 0 or below for the others. Finding. |
| D12 | Play | Rejects | A definition twice: the last. Finding. |
| D13 | Play | Text | As C++ (text and numbers). Finding where they differ. |
| D14 | Reject / Play | Strict | Per form: reject what C++ rejects (`30.5` in an integer column of `[BLOCKS]`); reproduce `+30`, the misread `100.5` RF delay (P3), short and long rows, NaN and negative values as C++ holds them. Finding. |
| D15 | Reject | Reads | Reject a dwell with a decimal point, as C++. Both writers write the dwell with `%.0f`, so no file written by them is affected. |
| D16 | Play | Reads | Reproduce the misreading of `-100.5` and the 31-character hint (P3). Finding. |
| D17 | Play | Rejects | Any `use` character, as C++. Finding. |
| D18 | Play | float64 | P6. Finding where float32 changes a value. |
| D19 | Play | Rejects | IDs that are not positive or not unique: the last wins, as C++. To establish per table. Finding. |
| D20 | Play | Rejects | Block IDs out of order: file order, as C++. Finding. |
| D21 | Reject / Play | Rejects | Reject an event that does not exist (as C++) and a missing shape (UB, 5.3). Reproduce the extension cases (the list ends; an empty object; a label left out). Finding. |
| D22 | Play / Reject | Rejects | Time ID -1 for a 1.4 gradient: as C++. For an RF event: C++ crashes: reject (5.3). |
| D23 | Reject | Rejects | A cycle in an extension list: C++ does not end: reject (5.3). |
| D24 | Play | Rejects | No block: an empty sequence, as C++. Finding. |
| D25 | Play | Rejects | An event longer than its block: the events as C++ holds them, `gradientsAt` 0 after the block. Finding. |
| D26 | Play | Rejects | Times off a raster: as written, as C++. Finding. |
| D27 | Play | Rejects | A gradient that is not 0 at an end: as written, as C++. Finding. |
| D28 | Reject | Accepts | An arbitrary gradient on a time ID of 0 or -1, in a file whose gradient raster is not 10 µs: C++ fails in `decodeBlock` (cpp:2114-2119), and `gradientsAt` uses a fixed 10 µs (`SeqBlock::s_gradientRaster`, cpp:90). Reject. `valid_arbitrary_gradient_4us_raster.seq` changes class. |
| D29 | Play / Reject | Rejects | A shape whose decompressed length differs from `num_samples`. `decompressShape` has no bound (cpp:2213-2236): a longer result writes past its buffer of `num_samples`: reject (5.3). A shorter one leaves the rest of the derivative at 0, so after the cumulative sum the last value repeats to `num_samples`: reproduce, with a finding. |
| D30 | Play | Rejects | Outside [-1, 1]: clamped, as C++. Finding. |
| D31 | Play | Rejects | RF magnitude below 0: 0, as `checkRF`. Finding. |
| D32 | Play | Rejects | RF phase outside [0, 1): clamped, as `checkRF`. Finding. |
| D33 | Reject | Rejects | Empty shape: UB, reject (5.3). |
| D34 | Reject | Rejects | Shapes of one event of two lengths: C++ crashes (RF): reject (5.3). |
| D35 | Play | As C++; rejects off-centre | As C++, off-centre times included (P5). Finding. |
| D36 | Play / Reject | As C++; rejects past the end | (1) As C++ (P5); (2) the read past the end: reject (5.3). |
| D37 | Play | As C++ | No change. Finding (MATLAB and pypulseq round the last time up). |
| D38 | Play | Absent | A 1.4 RF event has `center` -1 in C++. Keep it absent in the model; finding. |
| D39 | Play | Rejects | `FLOAT_UNDEFINED` ends, as `gradientsAt` uses them (P7). To establish the value. Finding. |
| D40 | Play | (2) rejects | (2) As `gradientsAt` (the first segment extended backwards). Finding. |
| D41 | Play | Lines | No change. Finding (MATLAB restores the edges). |
| D42 | Play | Ramps (MATLAB) | C++ makes one block at a time. To establish what the package shows between blocks. Finding. |
| D43 | Play | All the samples | The centre samples only, C++'s default (P7). Finding. |
| D44 | Play | As stored | As C++ (rad). Finding where they differ. |
| D45 | Play | Ignores | No change. Finding (pypulseq rejects). |
| D46 | Reject | Accepts | Reject (P9, section 8). |
| D47 | Reject | Rejects | No change. |
| D48 | Play | Rejects | Two rotations or shims in a block: the first, as C++. Finding. |
| D49 | Play / Reject | Reads as written; `load` refuses rotations | A quaternion within 1e-3 of unit norm: divided by its norm (cpp:1286-1292), and the gradients rotated (Q3). Further: reject, as C++. Finding where the norm is not 1. |
| D50 | Play | Reads | No change (C++ ignores the label). Finding. |
| D51 | Play | Keeps | No change. Finding (pypulseq merges). |
| D52 | — | None | Not about the file. No change. |
| D53 | Play | As C++ | No change. Finding (CRLF). |
| D54 | Play | Rejects | Accept, as C++. Finding. |
| D55 | Agree | Text | No change. |

### 5.2 What `cpp-siemens` rejects

D02, D06 (a `#` row inside a table), D11 (in part), D14 (in part), D15, D21, D28, D46, D47,
D49 (norm off by more than 1e-3), and each case of undefined behaviour (5.3). Each rejection
keeps a stable code, so pulseq-checks and the tests can name it. A version outside 1.4.0–1.5.x
raises the "not supported" exception instead (Q1).

### 5.3 The undefined behaviour of the C++ reader (Q2)

`cpp-siemens` rejects each case (Q2).

| Entry | What the C++ reader does | Reason to reject |
|---|---|---|
| D05 | Crashes with `[VERSION]` as the last section. To establish where. | Reject: no build gives a waveform that is known. |
| D21 | Crashes on a missing shape. | Reject. |
| D22 | Crashes on an RF event with time ID -1. | Reject. |
| D23 | Does not end on a cycle in an extension list. | Reject. |
| D29 | Writes past its buffer when a shape decompresses to more samples than `num_samples` (cpp:2213-2236). | Reject the longer case. (The shorter case is not UB: section 5.1.) |
| D33 | Takes the address of element 0 of an empty vector (cpp:1995, 2203): the macOS build traps, the Linux build accepts and plays an RF event of 0 samples. | Reject: an RF event with no samples has no waveform to reproduce. |
| D34 | Reads the phase at each index of the magnitude (cpp:2284-2290): reads past the shorter shape. | Reject. |
| D36 (2) | The resampling index reaches the number of samples (cpp:2039-2045) and reads one sample past the end. The Linux build plays a value from outside the shape. | Reject. This includes MATLAB's RF pulses of 4 samples or fewer at the default dwell, which it writes as an uncompressed time shape at the cell centres (`compressShape` does not compress 4 samples or fewer). |

A sanitizer build of the C++ oracle (section 9) finds each case, so the list is not left to the
memory layout of one build.

## 6. The `spec` interpreter

The `spec` interpreter reads the file as the specification describes it. "Must" in the
specification gives a rejection (Q4). Where the specification is silent, the user chose the
reading (Q5, 2026-10-12); those rows are marked **chosen**. Its readings are checked against the
text of the specification by hand, with a citation for each.

| Entry | Specification | `spec` |
|---|---|---|
| D01a–c | Table and example: 12, 7, 9 fields | The same as `cpp-siemens`. |
| D02 | Recommends rejecting a file with no `[VERSION]` | Reject. |
| D03 | Silent | Q1. |
| D04 | `major <major>`: integers | Reject `5.0` (not an integer, as D14). |
| D05 | Silent on order | Any order. |
| D06 | A comment is a line that starts with `#` (§2.1) | **Chosen**: skip blank and `#` lines anywhere outside a shape; the rows after them are read. |
| D07 | A blank line ends a shape (§2.9) | **Chosen**: reject a shape with no blank line after it. |
| D08 | Silent | **Chosen**: ignore an unknown section, with a finding. |
| D09 | Removed in 1.4.0; "current readers ignore this section" (binary format) | **Chosen**: ignore, with a finding. |
| D10 | Silent | **Chosen**: read the copies of a section in file order, as one (as MATLAB and pypulseq), with a finding. An ID repeated across the copies is D19: reject. |
| D11 | Required | Reject a missing raster, and a raster that is not finite and above 0. |
| D12 | Silent | **Chosen**: the last definition wins (as all three implementations), with a finding. |
| D13 | `any`; the hash a string | Text. |
| D14 | Types only; no number syntax | Each field as its type: reject `30.5` and `100.5` in integer columns, and a row with too few or too many fields; read `+30` as 30. **Chosen**: reject NaN and inf in each float column, and a negative delay. |
| D15 | A float in ns, an integer multiple of `AdcRasterTime` | Read the float; off the raster: D26. |
| D16 | An example only: the offset in µs, no table of types | **Chosen**: read the offset as a float (`-100.5` µs, as MATLAB writes and reads it) and keep the whole hint. |
| D17 | One of 7 letters | Reject another letter. |
| D18 | Shapes stored as float32 in binary files | float64. |
| D19 | IDs must be positive and unique | Reject. |
| D20 | "The blocks are executed sequentially" (§2.7); no restriction on IDs | File order. |
| D21 | References are implied to resolve | Reject. |
| D22 | Time ID -1 for gradients only | Reject it for an RF event. |
| D23 | Implied | Reject a cycle. |
| D24 | "Must declare at least one block" | Reject. |
| D25 | The scanner's interpreter must reject it | Reject. |
| D26 | "Must" | Reject. |
| D27 | "Must" and "need to" | Reject. |
| D28 | Any gradient raster | Play on the file's raster. |
| D29 | "Must" | Reject. |
| D30 | "Must" be in [-1, 1] | Reject. |
| D31 | Allowed: the magnitude is a signed amplitude shape | Play a negative magnitude as written (a phase of π). |
| D32 | Silent | Play the phase as written, 2π times the value (a phase of 1.5 turns is the waveform of 0.5 turns), as MATLAB. |
| D33 | Silent; no minimum number of samples | **Chosen**: reject; an event with no samples has no waveform. |
| D34 | Silent; the magnitude, phase and time of an RF event pair up by index (§2.6, §2.8.1) | **Chosen**: reject; some samples have no partner. |
| D35, D36 | "The time sampling points", in RF rasters; cells are defined only for the default raster (§2.6) | **Chosen**: as the format's tools split them (C++'s two branches; MATLAB `checkTiming.m:58-69`). A regular step is cells: each sample covers one dwell. Any other shape is points on the raster edges, joined by straight lines (the intent of the C++ FIXME). A shape read as points gives a finding: the specification does not define it. |
| D37 | Silent | **Chosen** with D35, D36: a regular step lasts N × dwell; points end at the last time. |
| D38 | No `center` in 1.4 | Absent. |
| D39 | No `first` and `last` in 1.4 | **Chosen**: reject a 1.4 arbitrary gradient on the default raster: the file has no ends. `spec` then refuses many 1.4 files with arbitrary gradients, which `cpp-siemens` reads; `compare` flags each. |
| D40 | No `first` in 1.4 | A time shape that starts at 0: its first sample. **Chosen**: one that starts later: reject, as D39. |
| D41 | Samples at the centres of the cells (§2.6) | **Chosen**: straight lines between the centres, to `first` and `last` at the edges, as `cpp-siemens` and pypulseq. |
| D42 | Silent | 0 where no gradient event plays. With D27 rejected (Q4), every gap inside a block lies between zeros, and a gradient that ends above 0 at its block's end continues into the next block. |
| D43 | N − 1 extra points on the edges | All the samples, half a raster apart. |
| D44 | No unit for the ADC phase shape | **Chosen**: rad, as C++ and MATLAB use it, one value for each ADC sample (as `makeAdc` requires); reject a shape of another length. |
| D45 | The scanner's interpreter may ignore an extension that is not required | Ignore. |
| D46 | Silent on order | Accept. |
| D47 | Must reject | Reject. |
| D48 | One rotation and one shim per block | Reject two. |
| D49 | A "normalized rotation quaternion"; the specification's own example has a norm of 1 + 2.3e-7 | **Chosen**: divide the quaternion by its norm, with a finding when the norm as read is more than 1e-3 from 1; reject a quaternion of norm 0. Apply the rotation (Q3). |
| D50 | Lists the labels "supported at the moment" | **Chosen**: ignore an unknown label, with a finding (labels do not change the waveforms). |
| D51 | Silent | Keep both. |
| D52 | Not in the file | No change. |
| D53 | The `\n` before `[SIGNATURE]` belongs to the signature | As the specification: strip one `\n`. Differs from `cpp-siemens` for CRLF. |
| D54 | Must have both | Reject. |
| D55 | A word in the examples | Text. |

## 7. Architecture

### 7.1 Layers

One library, in three layers and a base. A layer imports only from the layers below it.

| Layer | Subpackage | Holds | Today's modules |
|---|---|---|---|
| Base | `pulseq_analysis` (top-level modules) | The `Finding` type and the catalogue; shared helpers | `_equality`, `_validate`; new: `findings` |
| Files | `pulseq_analysis.seqfile` | The lexer, the two readers, `SequenceData`, `SeqFileError`; the pypulseq converter of task 4 | `seqfile`, `model` |
| Waveforms | `pulseq_analysis.synth` | The two decoders, the events, the block index, sampling, `compare` | `events`, `_events`, `seq_index`, `seq_utils`, `sampling`, `snapshot`, `extensions` |
| Analyses | `pulseq_analysis.analyses` | The measurements and `load`; SAFE and the `.asc` reader | `analyses`, `grad_peaks`, `grad_spectrum`, `pns_levels`, `series`, `safe`, `asc` |

- **The rule is enforced.** An import-linter `layers` contract in `scripts/check` (a new dev
  dependency) fails on an import from a higher layer. The code respects the order already:
  `seqfile` and `model` import only `model` and `_equality`, and no waveform module imports an
  analysis module.
- **An interpreter spans two layers.** Its name picks a reader in `seqfile` and a decoder in
  `synth`. `SequenceData` carries the name, so `synth` picks the decoder from the data, and
  `seqfile` knows nothing of decoders.
- **`snapshot` and `extensions`** hold today's `load`, which is built on pypulseq, and
  `seq_index` and `_events` import `snapshot`. They sit in the waveform layer until task 5a
  builds `load` on the model; `load` then moves to the analyses layer.
- **The public names change** (for example `pulseq_analysis.events` becomes
  `pulseq_analysis.synth.events`), with no aliases: nothing is released yet, and pulseq-checks
  adapts. The task that moves them (R3) changes no behaviour.
- **A later split** into separate libraries is then mostly a move of the subpackages. It is
  worth doing when a second user needs the files or waveform layers without the analyses, when
  their dependencies diverge, or when their interfaces have held for a release or two.

### 7.2 Stages

1. **Lex** (shared): the bytes into sections and rows, without loss: each field's raw text,
   its line number, the blank and `#` lines, and the bytes the signature hashes. It rejects
   nothing that either interpreter reads.
2. **Read** (per interpreter): the rows into `SequenceData`. The two readers differ in the text
   itself (D07, D14, D16), so they cannot share one model. `cpp-siemens` reads as the C++
   reader reads; `spec` as section 6 says.
3. **Decode** (per interpreter): `SequenceData` into the events and the waveform of each block.
   `cpp-siemens` decodes as the C++ reader and its `gradientsAt` do; `spec` as section 6 says.
   Each records facts as it decodes (a clamp, a misread row, a sentinel), for the findings.
4. **Find**: the findings of one interpreter (its facts, and the hand-written tests for MATLAB
   and pypulseq), and the findings of a comparison of the two interpreters. They never raise.

The measurements of task 5a take the waveforms of one interpreter.

### 7.3 API (Q6)

```python
seqfile.read_seqfile(path, interpreter="cpp-siemens") -> SequenceData  # .interpreter, .findings
synth.compare(path) -> Comparison  # both results, and the findings of their differences
synth.findings_of(path, interpreter="cpp-siemens") -> tuple[Finding, ...]
analyses.load(path, interpreter="cpp-siemens") -> ...  # the measurements; .findings

# An interpreter by name, or as an object with its settings:
seqfile.read_seqfile(path, interpreter=CppSiemens(oversampling="edge"))  # D43
```

`"cpp-siemens"` and `"spec"` name the objects with their defaults. A setting of `cpp-siemens`
follows a setting of the scanner's interpreter (for example its oversampling mode, D43); a
result records the interpreter and its settings. `SeqFileError` is the rejection of one
interpreter, with its code. A file outside the versions of Q1 raises the "not supported"
exception in both.

### 7.4 Findings

```python
@dataclass(frozen=True)
class Finding:
    code: str  # stable: "rf.magnitude-clamped", "raster.gradient-delay", ...
    where: Location  # section and line; block; event kind and ID
    message: str  # one sentence, with the values
    interpreter: str  # "cpp-siemens", "spec", or "both" for a comparison
    readings: Readings  # cpp-siemens, spec, matlab, pypulseq: AGREES | DIFFERS | NO_WAVEFORM
    category: Category


CATALOGUE: Mapping[str, FindingKind]  # each code: title, category, record entry
```

Categories describe a finding. They do not grade it:

- `interpreters-differ`: one interpreter rejects the file and the other reads it, or their
  waveforms differ beyond a tolerance. Found by `compare`.
- `spec-departure`: the specification says "must", and `cpp-siemens` plays the file (D19,
  D24–D27, D29, D30, D54).
- `cpp-changes-value`: the C++ reader changes what the file says (D14 (3), D16, D18, D30–D32,
  D35, D36 (1)).
- `cpp-default`: the waveform depends on a sentinel or a mode (D39, D43).
- `writers-differ`: MATLAB or pypulseq reads the file differently from both interpreters.

Today's rule names stay as finding and rejection codes where the condition is the same (for
example `raster.gradient-delay`), so pulseq-checks keeps its names.

Python warnings: `findings.warn(findings)`, or `warn=True`, emits one
`PulseqDiscrepancyWarning` for each (P8).

### 7.5 pulseq-checks

pulseq-checks owns severity: a policy that maps a code, a category, or the verdict of an
interpreter to `ignore`, `warn` or `error`, and profiles built on it. For example:

- "scanner": an error when `cpp-siemens` rejects the file.
- "specification": an error when `spec` rejects the file. This gives back today's strict
  parser, from the `spec` interpreter, without a check in pulseq-analysis.
- "portable": an error for each `interpreters-differ` finding.

It also owns exit codes and reports. pulseq-analysis does not change when pulseq-checks makes a
policy stricter.

### 7.6 The engine of `cpp-siemens`: a replica or a wrapper (R2)

`cpp-siemens` can be built in two ways. Both give the same waveforms; they differ in what is
around them.

| | Python replica | Wrapper of the C++ reader |
|---|---|---|
| Fidelity | As good as the oracle tests prove, fixture by fixture | Exact by construction: float32, `checkRF`'s clamps, the resampling, the misreadings, `gradientsAt`, and quirks not yet found |
| Upstream changes | Ported by hand | A new pinned commit |
| Findings | Recorded while decoding | A diff of the lexer's reading against what the C++ reader decoded: the C++ reader reports no misreading or clamp, and its rejections are messages, not codes |
| Undefined behaviour | Detected in Python | Detected in Python before the call: in the process, a case either traps (macOS) or reads memory it does not own (Linux) |
| Installation | Pure Python | Compiled wheels for each platform |
| Shared state | None | `SeqBlock` keeps rasters in static variables that each load sets (cpp:807, 1540): one file at a time in a process, behind a lock |
| Work in R6 to R10 | Port each quirk and prove it | The checks for undefined behaviour and the findings diff |

The rotation (Q3), the timeline across blocks, the sampling and the measurements are the
package's own in either case. The lexer, the `spec` reader and the checks for undefined
behaviour are needed in either case.

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
The decision (the user's) then sets how R6 to R10 are built. The prototype's code stays on its
branch unless the decision is to wrap, in which case R6 builds on it; the report merges as a
change to this plan.

## 8. D46: `[EXTENSIONS]` as the last section

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
  (the specification does not fix the order of the sections). `compare` gives an
  `interpreters-differ` finding.
- The test of the C++ oracle drops the file from `ORACLE_KNOWN_WRONG`; the reader and
  `cpp-siemens` then agree.
- The record's D46 says why, and that the writers produce such a file only with the signature
  off.
- Worth reporting upstream (pulseq/pulseq), section 12.

## 9. Verification

- **`cpp-siemens` waveforms.** The decoded events and the waveform in each block against
  `--sample` of the C++ oracle, for each fixture and for generated files. Generated files:
  property-based (the grammar of `.seq`, with values at the edges), seeded, in a marker that CI
  runs.
- **A sanitizer build of the C++ oracle.** `pulseq-cpp-oracle-sanitized`, built with ASan,
  UBSan and `_GLIBCXX_ASSERTIONS`, in the CI devShell. Its verdict "undefined behaviour" makes
  section 5.3 reproducible, whatever an ordinary build does.
- **`spec` readings.** Each row of section 6 has a fixture and a test that cites the
  specification. MATLAB's `waveforms_and_times` is a second opinion where it follows the
  specification (for example D28, D35, D36, D43), not a reference.
- **Findings, both ways.** For each fixture and generated file, run the two interpreters, the
  MATLAB oracle and pypulseq, and compare the acceptance and the waveforms within tolerance. The
  test asserts that each disagreement has a finding, and that each finding's code matches a
  disagreement the run saw.
- **The record and the catalogue.** A test checks that each code of `CATALOGUE` has a record
  entry and a fixture, and that each record entry that an interpreter acts on has a code.

## 10. Tasks

| Task | Branch | Result |
|---|---|---|
| R1 | `docs/parser-redesign` | This plan. |
| R2 | `chore/cpp-wrapper-prototype` | A prototype of `cpp-siemens` as a wrapper of the C++ reader, and its report (7.6). It decides how R6 to R10 are built. |
| R3 | `refactor/layers` | The modules moved into the subpackages of 7.1, and the import-linter contract. No change of behaviour. |
| R4 | `chore/sanitized-oracle` | The sanitizer build of the C++ oracle, and the comparison of section 9 for the existing fixtures. It finds each case of undefined behaviour, which R6 then rejects. |
| R5 | `refactor/lexer` | The lossless lexer (7.2, stage 1), and today's parser rebuilt on it. No change of behaviour: the baseline of task 2 compares the two. |
| R6 | `feature/cpp-siemens` | The `cpp-siemens` reader, the `interpreter` argument, the findings module (7.4), and each rule of today moved to a rejection (5.2), a finding, or removed. The record and the tests follow; pulseq-checks adapts. |
| R7 | `feature/cpp-siemens-rf` | D30–D32 clamps, D35 and D36 (P5), D18 findings (P6). |
| R8 | `feature/cpp-siemens-gradients` | D39, D40 (2), D43 (P7), D28 rejection, D42. |
| R9 | `feature/cpp-siemens-rotations` | D49: the quaternion normalized and the gradients rotated (Q3); `load` no longer refuses the rotation extension. |
| R10 | `feature/cpp-siemens-misreadings` | D04, D07, D14, D16 (P3), D08–D10, D12, D19, D20, D24, D54. |
| R11 | `feature/spec-interpreter` | The `spec` reader and decoder (section 6), with its fixtures. |
| R12 | `feature/compare` | `compare`, the `interpreters-differ` findings, and the four-source test of section 9. |

R2 comes first: its report decides whether R6 to R10 port the C++ reader to Python or wrap it
(7.6). R3 and R4 do not depend on it and can run at the same time. R5 needs R3, and R6 needs R5
and R2. R7 to R10 each need R6 and are otherwise independent, but they share
`docs/discrepancies.md` and `TESTS.md`, so they merge in turn. R11 needs R5 and R6 (the
interpreter argument), and it can run in parallel with R7 to R10. R12 comes last.

Tasks 4, 5a, 5b and 6 of `docs/plans/own-parser-tasks.md`:

- Task 4 (the pypulseq converter) does not read `.seq` text, and can run in parallel with R4
  and R5. A `Sequence` built in memory has no interpreter; the converter gives no findings.
- Task 5a (`load` on the model) comes after R6 to R8, so that `load` takes an interpreter,
  passes the findings on, and samples the waveforms as `cpp-siemens` makes them. The `spec`
  interpreter joins `load` when R11 is done.
- Tasks 5b and 6 keep their order.

## 11. Documents

- `docs/discrepancies.md`: section 4 is rewritten for this goal. Each entry's "Package" and
  "Reason" text gives what each interpreter plays and which finding it gives. Each task rewrites
  the entries it changes.
- `docs/usage.md`: the interpreters, `compare`, the findings, the warnings, and each
  interpreter's rejections.
- `CHANGELOG.md`: the files that `cpp-siemens` now accepts, and those it now rejects (D15, D28,
  D46, D49).
- `own-parser-tasks.md`: this plan supersedes the order of preference of its section 12 where
  they differ.

## 12. Upstream reports to consider

The user decides whether to file each, on pulseq/pulseq:

- D46: `[EXTENSIONS]` as the last section is rejected.
- D36 (2): the guard `if (tc < waveform_t.size())` lets the index reach the size; the reader
  then reads past the samples. MATLAB writes such shapes for RF pulses of 4 samples or fewer.
- D33: an empty shape is undefined behaviour.
- D29: `decompressShape` writes past its buffer when a shape decompresses to more samples than
  `num_samples`.
- D16: `-100.5` as a soft delay offset is misread as -100 and a factor of 0.5.

## 13. Risks

- **What C++ plays is not always visible.** `ExternalSequence` decodes blocks; the scanner's
  interpreter plays them. Where the decoded block is not enough to know the waveform (D25
  after the block end, D42 between blocks), `cpp-siemens` shows what `gradientsAt` gives and
  says so in the finding.
- **Two readers to keep in step.** Each change of the format touches both. The shared lexer and
  the four-source test keep their differences deliberate.
- **The `spec` interpreter's choices** are the package's, not the specification's. Each is
  listed in section 6 and in the record, and a finding names it where it matters.
- **pulseq-checks.** It relies on today's rejections. R6 changes them at once; the
  "specification" profile of 7.5 restores them from the `spec` interpreter, and pulseq-checks
  adapts in the same release.
- **Reproducing misreadings** makes `cpp-siemens` read some files in a way a person would not
  expect. Each misreading has a finding, and the record says why.
