# Study: an own strict parser of Pulseq files, in place of pypulseq's `read`

Status: decided by the user on 2026-10-08 (section 7). Written on
2026-10-08. This is a study, not an implementation plan: the plan of option B
follows from the decisions of section 7. No code changes.

## 1. The question

The package tests a sequence. Its values must describe the file as specified
(layer 1 of `docs/plans/explicit-sourcing.md`, section 1.1). Today `load(path)`
gets layer 1 through pypulseq's `Sequence.read`, which was made to build a
usable object, not to test a file: it fills gaps, changes values and accepts
files that the specification calls invalid (section 2.2). The user asked on
2026-10-08:

- Should the package parse files itself, keep pypulseq only for sequences
  built in memory (`load(seq)`), or keep the status quo?
- If the package breaks free of pypulseq, is another language, such as Rust,
  better suited?

The work of `docs/plans/explicit-sourcing.md` (tasks 1 and 2) is on hold until
this decision.

## 2. Findings (verified on 2026-10-08, unless marked)

`main` is at `73f45f7`. The pypulseq pin is the fork commit `3c3bd85`. Three
investigations (the specification, the package, the reference readers) and
measurements in a scratch directory give these facts. The scratch scripts and
downloaded files are not in the repository.

### 2.1 What the package uses of pypulseq

The use is narrow.

- **Attributes of `pp.Sequence`:** `block_events` (columns rf, gx, gy, gz,
  adc; not the delay or extension columns), `block_durations`,
  `grad_raster_time`, `extension_string_idx` and `rotation_library` (for
  `refuse_rotations`), and `block_cache` / `use_block_cache` (for the
  snapshot).
- **Methods:** `read` (`snapshot.py:119`) and `get_block` (`seq_index.py:222`,
  one call for each unique event).
- **Event data that a measurement reads:** gradients only: `type`, `delay`,
  `rise_time`, `flat_time`, `fall_time`, `amplitude`, `tt`, `waveform`,
  `shape_dur`, `first`, `last` (`seq_utils.gradient_offsets`). No RF, ADC,
  label, trigger or soft-delay field is read by any measurement. RF and ADC
  events are only handed out by `rf_events` and `adc_events`.
- **pypulseq outside the sequence:** `_safe_gwf_to_pns_chunk` (fork only,
  71 lines with `safe_hw_check`, 23 lines; numpy and `scipy.signal.lfilter`),
  `readasc` (100 lines, `re` only) and `asc_to_hw` (75 lines). Importing
  `pns_levels` imports matplotlib, through pypulseq's `safe_pns_prediction`
  module.
- **Public types that are pypulseq types:** `load(pp.Sequence)`,
  `Snapshot.sequence` (a `pp.Sequence`, documented for reads such as
  `definitions`), the `SimpleNamespace` events of `rf_events`, `grad_events`
  and `adc_events`, `SequenceIndex.block_id` ("the pypulseq block id"), and
  the hardware pair in the form of `asc_to_hw`.
- **The tests:** about 12,600 lines. Almost all build sequences with
  pypulseq's makers; pypulseq is also an oracle (`calculate_pns`,
  `waveforms`, `get_gradients`). No `.seq` file is committed.

### 2.2 What pypulseq's `read` does to a file

Beyond a literal parse (`read_seq.py`, `sequence.py`, `event_lib.py` at the
pin):

1. **Defaults from `Opts`** for each raster that the file does not declare,
   and the ADC dead time appended to each ADC entry (see the explicit-sourcing
   plan, facts 2 to 5).
2. **`remove_duplicates`, on by default.** It rounds every library value
   (gradients: amplitude to 6 significant digits, times to 6 decimal places;
   shapes to 9 significant digits), merges entries that become equal, and
   renumbers the event and shape IDs densely. On the MATLAB-written
   `simple_mprage150.seq`, trapezoid 40 (amplitude `-0`) merged into
   trapezoid 39 (amplitude `0`), and 37 of 40 gradient entries changed value
   (for example `9.999999999999999e-06` to `1e-05`). (Measured by the
   reference-reader investigation; not repeated here.)
3. **A crash on oversampled gradients.** `remove_duplicates` maps the time
   shape ID through its table, and time_id `-1` (the half raster, Pulseq 1.5)
   is not in it. **Verified:** `load(path)` of the MATLAB-written 1.5.1 file
   `read_comparison/v1.5/spiral.seq` of KomaMRI.jl raises
   `KeyError: np.float64(-1.0)`. `read(..., remove_duplicates=False)` reads it.
   Upstream pypulseq has the same code.
4. **A rejection of valid extensions.** **Verified:** `load(path)` raises
   pypulseq's `ValueError: Unknown section code: extension ROTATIONS 1` for
   the MATLAB-written `seq_make_radial.seq` (pulseq/pulseq tests) and for
   KomaMRI's `rotation_radial_tiny.seq`, and `... extension UNKNOWN1 1` for
   KomaMRI's `unknown_ext.seq`. The specification says that an interpreter
   may ignore an unknown extension unless the file lists it in
   `RequiredExtensions`. So `refuse_rotations` never sees a rotation from a
   file: pypulseq fails first, with a parse error.
5. **The version.** Only the first character of `revision` is kept
   (`revision 10` is read as 1). A file with no `[VERSION]` before `[BLOCKS]`
   gives a `NameError`. The version is not kept after `read`.
6. **1.4.x arbitrary gradients** get computed `first` and `last` values
   (section 2.4).
7. **Unit scaling** by `1e-6` and `1e-9` leaves float noise (a 10 µs rise is
   `9.999999999999999e-06`). MATLAB does the same.

Items 3 and 4 are defects of `load(path)` today, whatever this study decides.

### 2.3 The specification

The text of the specification (`doc/specification.pdf` of pulseq/pulseq) was
read at 1.4.1, 1.5.0, 1.5.1, 1.5.2 and the 1.5.3 draft.

- **Every version is labelled "DRAFT".** No version is frozen. The prose
  contradicts the tables in places: the "N numbers" of the RF, GRADIENTS and
  ADC sections are wrong in both 1.4 and 1.5; the tables and the examples are
  right.
- **The text sections** of 1.4.0 and later: `[VERSION]`, `[DEFINITIONS]` (the
  four required rasters; `RequiredExtensions` from 1.5.1), `[BLOCKS]` (8
  integers, duration in `BlockDurationRaster` units), `[RF]` (8 columns in
  1.4, 12 in 1.5), `[GRADIENTS]` (5 columns in 1.4, 7 in 1.5: 1.5 adds
  `first` and `last`), `[TRAP]` (6), `[ADC]` (6 in 1.4, 9 in 1.5),
  `[EXTENSIONS]` (a linked list), the `extension <STRING_ID> <type>` tables,
  `[SHAPES]` (a header and one sample for each line; compressed or not) and
  `[SIGNATURE]`. `[DELAYS]` must not appear from 1.4.0.
- **Extensions:** TRIGGERS (1.3.0), LABELSET and LABELINC (1.3.1; the label
  name is a text token), DELAYS (soft delay, 1.5.0), ROTATIONS and RF_SHIMS
  (1.5.1). An extension is recognized only by its STRING_ID. From 1.5.1, an
  unknown extension listed in `RequiredExtensions` must stop execution;
  MATLAB's `read.m` does not check this.
- **Shapes:** a run-length encoding of the derivative, defined in the
  specification only by examples; MATLAB's `decompressShape.m` is the
  reference. A shape is uncompressed when its stored length equals
  `num_samples`. Time shapes: time_id `0` is the default raster (samples at
  the centres of the raster cells), `-1` (1.5.0, gradients only) is the half
  raster with the end values from the event, and a positive ID is an explicit
  time shape.
- **The binary format** is a separate file format (a magic number, then
  int64 section codes). It was rewritten in 1.5.2, and three incompatible
  layouts were published in one month of 2026. Recommendation: out of scope.
- **Checkable rules** (22 in the investigation): the four rasters present,
  no `[DELAYS]`, positive and unique IDs, each reference resolving, at least
  one block, no event longer than its block ("the interpreters must throw an
  error"), ADC dwell a multiple of `AdcRasterTime`, gradients on
  `GradientRasterTime` edges, a gradient that starts above 0 has delay 0,
  decompressed shapes of `num_samples` points, amplitude shapes in [-1, 1],
  and the rules of `RequiredExtensions`.
- **Not specified:** the field separator, the number syntax, whether blank
  lines may appear inside a section, the rules of time shapes (monotonic,
  integer, length), the length and units of the ADC phase shape, and whether
  a signature mismatch is an error.

### 2.4 The 1.4.x gradient ends: a gap in layer 1

In a 1.4.x file, `[GRADIENTS]` has no `first` and `last`. For an arbitrary
gradient on the default raster (time_id 0) the samples are at the centres of
the raster cells, so the values at the two ends of the event are not in the
file. Both readers reconstruct them from the neighbouring blocks, and they
disagree:

| | `last` of a time_id 0 gradient |
|---|---|
| MATLAB `read.m` | an alternating sum from `first`: `edge[k+1] = 2*w[k] - edge[k]` |
| pypulseq | the linear extrapolation `(3*w[-1] - w[-2])/2` (upstream #240, chosen on purpose) |

On KomaMRI's MATLAB-written `read_comparison/v1.4/spiral.seq`, the `last` of
gx is -947,610 Hz/m (pypulseq) and -941,673 Hz/m (MATLAB); of gy, 46,817 and
25,634 Hz/m. The waveform that MATLAB Pulseq sampled for that file agrees with
MATLAB's value. The package's waveform uses `first` and `last` of each
arbitrary gradient (`docs/implementation.md` §1), so peaks, slew, PNS and the
spectrum of such a file depend on which reader's convention is used. (Measured
by the reference-reader investigation; not repeated here.)

An extended trapezoid with a time shape stores its corner values, and a
trapezoid starts and ends at 0, so the gap is only for time_id 0 arbitrary
gradients in 1.4.x files. Pulseq 1.5 added the columns to close it.

### 2.5 Speed

From `docs/implementation.md` §3.5 (Apple M1 Max, rc6):

- `load(path)`: 0.36 s for 100,000 blocks, 1.09 s with 20,002 unique
  gradient events, 3.58 s for 1,000,000 blocks. `load(seq)` (a copy): 0.12,
  0.31 and 1.36 s.
- The other slow calls are vectorised already: `pns_levels` and
  `gradient_spectrum` take about 75 ns for each sample (numpy and scipy's
  compiled filters and FFT).
- A first unique gradient event costs about 7 µs to read through `get_block`,
  which decodes the whole block (RF and ADC too).

A scratch prototype parsed `[BLOCKS]`, `[TRAP]`, `[GRADIENTS]` and
`[SHAPES]` of the same files with numpy in 0.04 s (100,000 blocks, 258
trapezoids) and 0.05 s (100,000 blocks, 20,002 trapezoids), against 0.35 s and
1.07 s for pypulseq's `read`. The prototype checks nothing and skips RF, ADC
and extensions, so a full parser is slower; the order of magnitude is the
finding.

### 2.6 Test oracles

- **pypulseq's repository** (`tests/expected_output/`, 31 files): the
  MATLAB-written `simple_mprage` at versions 1.2.0 to 1.5.0 (the same sequence
  in each version; arbitrary gradients, compressed shapes), and 1.5.0 files
  that pypulseq wrote (labels, triggers, soft delays).
- **pulseq/pulseq** (12 MATLAB-written files): 1.5.0 and 1.5.1, with labels,
  ROTATIONS (`seq_make_radial.seq`), soft delays, triggers and an ADC phase
  shape. No time_id 0 arbitrary gradient.
- **KomaMRI.jl** (`KomaMRIFiles/test/test_files/pulseq/`): the most useful.
  `read_comparison/v1.4` and `v1.5` pair each `.seq` file with a `.mat` file
  of the waveforms that MATLAB Pulseq sampled, block by block. The 1.4 spiral
  has time_id 0 arbitrary gradients; the 1.5.1 spiral has oversampled
  (time_id -1) gradients. Also ROTATIONS and an unknown extension.
- KomaMRI.jl is MIT licensed (its `LICENSE`, checked). Its test files may
  come from other projects (pulseq/pulseq, JEMRIS), so the license of each
  file is to check before a copy. The licenses of the pulseq/pulseq and
  pypulseq test files are not verified.

### 2.7 The other pypulseq functions

- `_safe_gwf_to_pns_chunk` and `safe_hw_check` (about 94 lines) could be
  copied into the package. The file carries a BSD 3-Clause notice (Szczepankiewicz
  and Witzel); pypulseq is MIT since 2026-01-28 (before that, AGPL-3.0). A copy
  keeps both notices. With it, the fork pin is no longer needed by the package
  itself. (The license reading is not legal advice.)
- `readasc` and `asc_to_hw` (about 175 lines) could be copied the same way,
  and the copy can refuse a missing gradient scale factor instead of assuming
  1/π (U2 of the explicit-sourcing plan).

### 2.8 A converter from `pp.Sequence`

`load(seq)` stays: a sequence built in memory is a primary input. A converter
reads pypulseq's in-memory form:

- `block_events` (7 columns), `block_durations` (seconds; for a built
  sequence, the maximum of the event ends, not rounded to the raster),
  `EventLibrary.data` tuples for each kind, the shape library, the extension
  libraries and `definitions`.
- The tuple layouts changed once in two years (pypulseq 1.4.2 to 1.5.0, in
  2025); `EventLibrary` and `block_events` did not change. The converter is a
  narrower coupling than today's, and the drift tests of the explicit-sourcing
  plan would cover it.
- A built sequence has full precision; the same sequence read from its file
  has the 6 to 9 significant digits of the text. A test that compares the two
  paths needs a tolerance (as the tests do now).
- A sequence that a caller read from a file and gives to `load(seq)` brings
  pypulseq's transformations (section 2.2) with it. The documentation says
  so: files go through `load(path)`.

### 2.9 KomaMRI.jl's reader

KomaMRI.jl (Julia, MIT license, `KomaMRIFiles/src/Sequence/pulseq/`, read on
2026-10-08 at `master`) has its own reader of Pulseq files: `ReadPulseq.jl`
(about 1,030 lines), `PulseqEvents.jl` (170), `Signature.jl` (56), and a
writer. It reads versions 1.2 to 1.5.1, and it was rewritten for speed in 2026
(#747, #754).

What it confirms:

- **The architecture.** It parses a file into a Pulseq-native form,
  `PulseqSequenceData`: block event IDs and event libraries, the definitions,
  the version and the signature, "without materializing repeated" events. A
  second step decodes each library entry one time and builds Koma's own
  sequence from the decoded entries by ID. This is the model of section 5,
  arrived at independently.
- **The size.** About 1,250 lines of Julia for a reader of six versions, with
  the porting of files before 1.4 (which this package does not need).
- **The 1.4.x gradient ends.** `fix_first_last_grads!` replicates MATLAB's
  `read.m` (it cites the lines), with the alternating sum for `last`. So MATLAB
  and KomaMRI agree, and pypulseq is the one that differs. KomaMRI also makes a
  new library entry when one 1.4.x gradient ID gets different ends in
  different blocks: the ends of such an event depend on its neighbours, not
  on the event. This supports U1: the file does not define them.
- **Shape decompression** is a copy of MATLAB's `decompressShape.m`, and its
  compression mirrors `compressShape.m` with the same constants (it cites the
  lines).
- **Signature verification** is an option of `read_seq_data`
  (`verify_signature=false` by default).

How it tests against MATLAB:

- `read_comparison/v1.2` to `v1.5`: for each block of each file, the times
  and amplitudes that KomaMRI samples must equal (`≈`) those that MATLAB
  Pulseq sampled into the paired `.mat` file.
- A round trip: read, write, read again, and compare.
- A parity test with MATLAB itself (`pulseq_matlab_parity.jl`): the same
  events built by KomaMRI and by MATLAB Pulseq must match, to 6 significant
  digits for events and 9 for shapes (the precision of the text format). It
  runs only when MATLAB and a Pulseq checkout are given in the environment.

Where it is not strict, and so not a model for this package:

- A missing raster definition gets KomaMRI's default (`DEFAULT_RASTER`), as
  pypulseq's `Opts` does.
- A missing `[VERSION]` before `[BLOCKS]`, and a `[DELAYS]` section in a file
  of 1.4 or later, are logged with `@error` and the read goes on: `@error` in
  Julia logs, it does not throw.
- An unknown extension listed in `RequiredExtensions` is ignored with a
  warning; the specification says that it must stop.
- Gradient amplitudes are converted to T/m with the gamma of 1H when read: a
  value of the target (layer 2) enters the model.
- The integer parser of `[BLOCKS]` reads any byte that is not a space, a tab,
  `\r` or `-` as a digit, so a malformed line gives wrong numbers, not an
  error (unless the count of fields is wrong).
- Soft delays and RF shimming are not yet read (a message says so).

What this package can take from it: the two-level design, the tests against
MATLAB-sampled waveforms and the round trip, the parity test that runs when
MATLAB is present, and, under its MIT license with attribution, the shape
code and the test files that KomaMRI wrote. It cannot take its leniency or its
units.

## 3. The options

| | A. Keep pypulseq's `read`, with fixes | B. Own parser for files, a converter for `load(seq)` | C. Own parser, no `load(seq)` |
|---|---|---|---|
| Files | `read(..., remove_duplicates=False)`; catch the extension errors; the text check of task 1 | Parsed by the package: strict, versioned, no `Opts` | as B |
| Built sequences | `load(seq)` as now | Converted to the package's model | Must be written first: fails for oversampled arbitrary gradients |
| 1.4.x gradient ends | pypulseq's convention | A decision (U1) | as B |
| `Opts` and drift | The whole explicit-sourcing plan | Only the converter | none |
| pypulseq | Required, fork pinned | Optional (the converter), or required; no fork | None at run time |
| Public interface | No change | `Snapshot.sequence` and the event types change (section 5) | as B, and `load(seq)` goes |
| Work | Small | Large | Large, and breaks a primary use |

C is rejected: built sequences are a primary input (pulseq-checks and
pulseq-reports run them).

## 4. The language

Speed does not favour a change. The parse is a small part of the time once it
uses numpy (section 2.5), and the slow steps (PNS, spectrum) already run in
compiled numpy and scipy code at about 75 ns for each sample; a native loop
could gain a constant factor, not an order. The correctness risk is in the
semantics of the format (shapes, time shapes, the gradient ends), and that risk
is the same in any language.

What Rust would give: a stricter type system and an immutable model by
construction, one core for other languages (a C interface, WebAssembly for a
browser, a command-line tool), and fast loops where numpy cannot vectorise.

What it would cost:

- Every user of the package is Python: pulseq-checks, pulseq-reports, and
  `load(seq)`, whose input is a Python `pp.Sequence`. Rust would need Python
  bindings (PyO3 and maturin), wheels for each platform, and the Nix build.
- The test oracles are Python (pypulseq's makers and functions), so the tests
  stay Python, and each change crosses two languages.
- The people who read and change a Pulseq tool use MATLAB and Python.

Recommendation: Python and numpy. Make the model plain arrays (section 5), so
that a native core can replace the parser later without a change of the
interface, if a need appears: a standalone tool, a browser, or a profile that
shows a loop that numpy cannot vectorise.

## 5. The recommendation: option B

1. **A model of layer 1**, immutable by construction: the version, the
   definitions, the blocks as integer arrays (ID, duration in raster ticks,
   rf, gx, gy, gz, adc, ext), each event kind as a numpy table with its
   columns in the units of the file (no dead times: they are not in a file),
   the shapes (decoded on use and kept), the extensions as tables, and the
   signature. The block and event IDs are those of the file: no renumbering.
   A snapshot holds a model, not a `pp.Sequence`, so it needs no deep copy
   for a file.
2. **A strict parser of text files**, versions 1.4.0 to 1.5.x, with the
   layouts of each version. The binary format is out of scope. The parser
   rejects a file that breaks any "must" rule of the specification, or that
   does not define layer 1 (U1, U2). It ignores an unknown extension unless it
   is required (the specification allows this), and it reads ROTATIONS so that
   the measurements refuse it with their own `NotImplementedError`.
3. **The gradient events** are decoded by the package from its tables and
   shapes, with the rules of section 2.3. This replaces `get_block` for the
   measurements: only gradients are needed (section 2.1).
4. **A converter** from `pp.Sequence` for `load(seq)` (section 2.8).
5. **The SAFE functions and the `.asc` readers** copied into the package with
   their notices (section 2.7). The fork pin ends for this package.
6. **pypulseq** becomes an optional extra (U5): `load(path)` and every
   measurement work without it, and `load(seq)` needs it. It stays a
   development dependency: the tests build sequences with it and use it as an
   oracle.

The public interface changes, before 0.1.0:

- `Snapshot.sequence` (a `pp.Sequence`) gives way to the model. A caller that
  needs a `pp.Sequence` keeps its own.
- `rf_events`, `grad_events` and `adc_events` give the package's event types,
  without the dead and ringdown times (layer 2; the analysis contract of the
  explicit-sourcing plan becomes a fact of the types).
- `SequenceIndex.block_id` is the block ID of the file, and the unique events
  are those of the file: two events that pypulseq merged (for example a
  trapezoid of amplitude `-0` and one of `0`) are two events. The counts of
  `seq.index` can change for such a file, so its `spec.version` may need to
  change (to check in the plan).

The effect on `docs/plans/explicit-sourcing.md`:

- Task 1 (the text check of `[VERSION]` and `[DEFINITIONS]`) becomes the first
  part of the parser.
- Task 2 shrinks: the table of sources and the drift tests cover only the
  converter of `load(seq)`; the rule, the two layers and the contract of an
  analysis stay. The plan is replaced by the plan of option B, which keeps
  those parts.

A migration order for the plan (each a branch):

1. The model, the parser and its validation, tested against the oracle files
   (section 2.6) and against pypulseq's `read(..., remove_duplicates=False)`
   for 1.5 files, with no change to `load`.
2. The gradient decoding from the model, tested against `get_block`.
3. The converter from `pp.Sequence`, tested against the parser on files that
   pypulseq writes.
4. `load` and the measurements on the model; the public interface changes.
5. The copies of the SAFE functions and the `.asc` readers; pypulseq no
   longer pinned to the fork for this package.
6. The documents: the rule, the two layers, the contract, the converter's
   sources and drift tests.

A rough size: the parser and its checks 800 to 1,500 lines (the specification
investigation), the model and the gradient decoding a few hundred, the
converter about 200, plus their tests. The measurements change little: they
read the same gradient fields from a different object.

## 6. Risks

- **Semantics.** The package becomes responsible for reading the format
  right: shape decompression, time shapes, the half raster, the extension
  lists. The MATLAB-sampled waveforms of KomaMRI's files and the MATLAB
  reader are the references; pypulseq is a second check.
- **A moving specification.** Every version is a draft, and extensions keep
  arriving. The parser rejects a version that it does not know, with a clear
  message, so a new version fails loudly, not wrongly.
- **Divergence from pypulseq.** A file can give different values in this
  package and in pypulseq (merged events, the 1.4.x gradient ends). That is
  the purpose, but users may ask why; the documents must say it.
- **Downstream breaks.** pulseq-checks and pulseq-reports use
  `Snapshot.sequence` and the event types; they adapt (the user's rule).

## 7. The decisions of the user (2026-10-08)

| ID | Question | Decision | Consequence for the plan |
|---|---|---|---|
| U1 | 1.4.x files with time_id 0 arbitrary gradients do not define their end values (section 2.4). Accept them with a convention, or reject them? | Reject such a file, with a message that names the gradients and says that Pulseq 1.5 stores the ends. Other 1.4.x files load (trapezoids and time-shaped gradients define their ends). | The parser needs no reconstruction of the ends from the neighbouring blocks: the most intricate part of MATLAB's and KomaMRI's readers is not needed. |
| U2 | Which rules of the specification does the parser enforce (section 2.3)? | Reject a file that breaks any "must" rule of the specification, and any file that does not define layer 1. (The recommendation was to reject only the layer 1 rules and to report the rest as findings.) | The plan lists each "must" rule with its check. Three points to settle there: (a) the tolerance of the checks that compare times with a raster (the units of the file are µs and ns, and the reference implementation uses 1e-12 s); (b) the rules that the specification states in prose that contradicts its own tables (the column counts): the tables and examples decide; (c) a rule that the specification phrases as "recommended" or "can" (a `[VERSION]` section; one ROTATIONS or RF_SHIMS object for each block) is not a "must": the version is required anyway for layer 1, and the plan decides the others. |
| U3 | Option A, B or C? | B. | The explicit-sourcing plan is replaced by the plan of option B, which keeps its rule, its two layers and the contract of an analysis. |
| U4 | Python or Rust? | Python and numpy, with a model of plain arrays (section 4). | |
| U5 | pypulseq: a required dependency, or an optional extra for `load(seq)`? | An optional extra now. (The recommendation was to make it required at first.) | `load(path)`, the model, the measurements, the SAFE functions and the `.asc` readers import no pypulseq. `load(seq)` imports it when called, and raises an `ImportError` that names the extra when it is missing. pypulseq stays a development dependency. The plan names the extra and tests the package without it. |
| U6 | The defects of `load(path)` today (section 2.2, items 3 and 4): fix them now, or wait for B? | Wait for B. | Until the parser replaces `load(path)`, files with time_id -1 gradients, with ROTATIONS or with an unknown extension cannot be loaded. The documents of the release before B should say so. |
| U7 | May the repository copy the oracle files of KomaMRI.jl, pulseq/pulseq and pypulseq? | Copy after a check of the license of each file. If a file cannot be copied, a test downloads it, or the test is skipped without network. | The plan lists each oracle file with its source, its license and its use. |

## 8. Not verified

- The licenses of the oracle files (other than KomaMRI.jl's own license) and
  of copying pypulseq code (2.6, 2.7).
- The measurements of the reference-reader investigation marked as such
  (2.2 item 2, 2.4); items 3 and 4 of 2.2 were checked here.
- Whether time_id -1 is valid for RF; the length and units of the ADC phase
  shape; the C++ interpreter of the scanners.
- Whether pulseq-checks or pulseq-reports read `Snapshot.sequence` or the
  event objects beyond the documented uses.
