# Findings for pulseq-checks

This document is for the maintainers of pulseq-checks. It describes what
pulseq-analysis gives pulseq-checks so that pulseq-checks can find the
discrepancies that `docs/discrepancies.md` records. It describes the code of
pulseq-analysis on `main`, and the tag of a release pins it at that release.
Each link to a file of this repository is relative, so the copy at a tag links
the files of that tag. What pulseq-checks does with it is pulseq-checks' own
plan: this project writes nothing in pulseq-checks' repository, and it does not
read its code.

The plan behind it is
[`docs/plans/parser-redesign.md`](plans/parser-redesign.md)
("the plan"), task C1 (section 7.5). "Dg.n" is an entry of
[`docs/discrepancies.md`](discrepancies.md)
("the record"), whose groups D1 to D4 give what `spec` does; what `cpp-siemens`
does is in `packages/pulseq-cpp-siemens/docs/specification.md` (its rule, to do
what the C++ reader does, and each exception), whose groups are D5 to D7. Since
2026-10-13 the entries are grouped by kind of decision, an ID names a decision of
an interpreter, and a condition on which each interpreter decides has two IDs.
Where the specification states a rule and each interpreter follows its own core
rule, there is no entry. "Pnn" and "Qnn" are decisions of the plan's sections 2 and 3.
"The C++ reader" is `ExternalSequence` of pulseq/pulseq at `c7469123`, the
reader of the scanner's interpreter on Siemens systems. Every module name below
is under `pulseq_analysis` unless it says otherwise.

Contents:

1. [Why the findings move](#1-why-the-findings-move)
2. [The contract: the public readings](#2-the-contract-the-public-readings)
3. [The four mechanisms](#3-the-four-mechanisms)
4. [Each entry of the record](#4-each-entry-of-the-record)
5. [Categories, and the choices left to pulseq-checks](#5-categories-and-the-choices-left-to-pulseq-checks)
6. [The test oracles of the flake](#6-the-test-oracles-of-the-flake)
7. [What is still to come](#7-what-is-still-to-come)

## 1. Why the findings move

pulseq-analysis turns a Pulseq file into waveforms, and it measures them. Since
P17 (the user, 2026-10-12) it does not judge whether a file is valid. It reads a
file through one of its **interpreters**, and each gives a reading or a
rejection with codes. Two are in this repository, `spec` and `cpp-siemens`
(a plugin, P21):

- **`spec`** (the default): as true as possible to the Pulseq specification
  (1.5.3 draft) and to the slide set that its section 2.6 cites for timing
  (`doc/pulseq_shapes_and_times.pdf`). It rejects a file where they say "must",
  with every violation. Where they are silent, it makes a documented choice, and
  rejects a file only where no current writer (MATLAB Pulseq, pypulseq) writes
  such a file.
- **`cpp-siemens`** (by name): the C++ reader itself, run in the process by the
  package pulseq-cpp-siemens. That distribution (the sub-project
  `packages/pulseq-cpp-siemens/`) gives the interpreter to pulseq-analysis
  through the entry-point group `pulseq_analysis.interpreters`: its class is
  `pulseq_cpp_siemens.interpreter.CppSiemens`. pulseq-analysis does not import
  it and does not list it as a dependency or an extra, so pulseq-checks installs
  both distributions to read with `cpp-siemens`. It reads what the reader reads,
  misreadings included, and rejects what the reader rejects. It rejects each
  case of the reader's undefined behaviour with a `ub.*` code (section 5.3 of
  the plan).

Where the sources of the format read a file differently, that is a
**finding**, and findings are pulseq-checks'. pulseq-checks reads the file
through the public readings of section 2, as often as it needs, and owns the
catalogue of findings, their severity, the profiles, the exit codes and the
reports (section 7.5 of the plan).

**What pulseq-analysis no longer reports.**

- No `Finding` type, no catalogue, no `compare`, and no warnings about a file.
  The one warning, `synth.ScannerSettingWarning`, is about the package's
  measurement, not the file (section 2.6): `analyses.load` emits it (section
  2.7), and the decoding does not.
- No strict reader. The former `seqfile.reader` and the interim interpreter
  `strict` are removed (R11). `spec` replaces them, with these changes to the
  former rule names (section 5.4 of the plan):

  | Former rule | Now |
  |---|---|
  | `version.unsupported` | `errors.NotSupported` in both interpreters (Q1); not a code |
  | `definitions.duplicate` | No rejection: the last definition wins (D2.6) |
  | `section.unknown` | No rejection: ignored, with a `model.Record` (D2.4) |
  | `section.delays` | No rejection: ignored, with a `model.Record` (D2.4) |
  | `blocks.order` | No rejection: file order |
  | `shape.rf-magnitude-negative` | No rejection: plays as written (D2.8) |
  | `shape.rf-phase-range` | No rejection: plays as written (D2.9) |
  | `shape.rf-time-grid` | No rejection: cells or points (D2.10) |
  | `shape.rf-time-end` | No rejection: points (D2.11) |
  | `syntax.line` | Changed: only a data line before the first section; rows after a blank or `#` line are read (D2.5, D3.2) |
  | `section.duplicate` | Changed: any section that appears twice, and two `extension` sections with one `STRING_ID` (D3.3, the user, 2026-10-13) |
  | `syntax.integer` | Changed: `+30` reads as 30 |

  Every other former rule name is a code of `spec` with the same condition, so
  pulseq-checks keeps its names (section 7.4 of the plan). The "specification"
  profile of section 7.5 of the plan is an error when `spec` rejects the file:
  it gives back the strict parser from `spec`.

## 2. The contract: the public readings

These readings are public, and kept stable for pulseq-checks (section 7.3 of
the plan). A change to any of them is a change of the contract: it is noted in
`CHANGELOG.md` and in this document, in the same pull request. The
[`docs/usage.md`](usage.md)
sections "The interpreters", "A pypulseq sequence in memory" and "The 'as
written' reading" have every field; this section is the index for
pulseq-checks.

| Entry point | Module | Returns |
|---|---|---|
| `seqfile.read_as_written(path)` | `seqfile.as_written` | `AsWritten` (2.1) |
| `seqfile.read_seqfile(path, interpreter="spec")` | `seqfile.reading` | `SequenceData` (2.2), or raises `SeqFileError` or `NotSupported` (2.5) |
| `seqfile.read_pypulseq(seq, interpreter="spec")` | `seqfile.from_pypulseq` | the `SequenceData` of the file that `seq.write(path)` gives, with `origin` `"pypulseq"` |
| `synth.decode(data, session=None)` | `synth.decoding` | `SpecDecoding` (2.3), or the decoding of a plugin (`pulseq_cpp_siemens.interpreter.CppSiemensDecoding` for `cpp-siemens`, 2.4), under the scanner session (2.8); both are a `synth.Decoding`; raises `synth.SettingError` (2.8) |
| `seqfile.interpreter_names()` | `seqfile.interpreters` | the names of the installed interpreters: `spec`, then each plugin's (none is imported) |
| `analyses.load(source, interpreter="spec", session=None)` | `analyses.loading` | `synth.Snapshot`, the measurements' input (2.7) |

On an Apple M1 Max, a file of 20 MB with 900 000 blocks takes 0.3 s to read as
written, 0.5 s with `spec` and 2.9 s with `cpp-siemens` (`docs/usage.md`).

### 2.1 The "as written" reading

`seqfile.read_as_written(path) -> AsWritten` (module `seqfile.as_written`, task
R5, P13): the bytes of a file into sections and typed fields, with line
numbers, without loss and without interpretation. It reads every file, whatever
the version or the errors in it, and raises only `OSError`. The interpreters
read the file through it. Every array is read-only.

| Type | Fields |
|---|---|
| `AsWritten` | `path`, `raw` (every byte), `not_utf8` (the offset of the first byte that is not UTF-8, or None), `line_count`, `preamble` (the lines before the first header, a `Section`), `sections` (in file order, each as many times as the file has it), `version` (of the first `[VERSION]`, or None); `named(name)`, `extensions()`, `signed_bytes()` (the bytes that the hash covers by spec section 2.4) |
| `Section` | `line` (of the header), `header`, `name` (`[NAME]` as written, or None), `extension` and `extension_type` (for an `extension` header), `end`, `rows` (a `Table`), `blank` and `comments` (each a tuple of `Line`), `shapes` (in `[SHAPES]`) |
| `Table` | `columns` (each a `Column`: `name`, `kind` `int`, `float` or `text`), `extra` (the kind of the fields after the last column), `lines` and `counts` (int64), `values` and `valid` (structured arrays, one field for each column), `text`; `row(i)`, `fields(i)`, `cells(i)` |
| `ShapeWritten` | `line` and `fields` (the `shape_id` line), `id`, `num_samples_line`, `num_samples`, `rows` (a range of row indices of `Section.rows`) |
| `Line` | `number` (from 1), `text` |

What it does not decide: which rows a reader takes. A blank or `#` line does
not end a section here, a blank line does not end a shape, and a section that
appears twice is two `Section` values. Each reader's choice is in the record
(D2.5, D3.11, D3.3). The columns have the names of `SequenceData` and the units of
the file (µs, and ns for the ADC dwell time). The columns of `[RF]`,
`[GRADIENTS]` and `[ADC]` are those of 1.4 below version 1.5.0, else those of
1.5.

### 2.2 The model of each interpreter

`seqfile.read_seqfile(path, interpreter="spec") -> SequenceData` (module
`seqfile.model`). `interpreter` is a name (`"spec"`, `"cpp-siemens"`) or an
interpreter object:

- `seqfile.interpreters.Spec()`: no setting. `Spec(rotation="apply")` is a
  `TypeError`.
- `pulseq_cpp_siemens.interpreter.CppSiemens(oversampling="center",
  rotation="reader")`: `oversampling` is one of
  `pulseq_cpp_siemens.interpreter.OVERSAMPLING` (`"center"`, `"edge"`,
  `"preserve"`), the reader's sampling mode of an oversampled gradient (D6.1);
  `rotation` is one of `pulseq_cpp_siemens.interpreter.ROTATION` (`"reader"`,
  `"apply"`), what the decoding does with each block's rotation (D6.2). `str`
  gives the name with the settings that are not the default, for example
  `cpp-siemens(rotation='apply')`.

A plugin is a class of the protocol `seqfile.interpreters.Plugin` (`name`,
`protocol`, `read(path)`, `decode(data, session=None)` and `str()`), found by
the entry-point group
`seqfile.interpreters.GROUP` (`"pulseq_analysis.interpreters"`).
`interpreters.interpreter(value)` gives the object of a name, and
`interpreters.Interpreter` is `Spec | Plugin`. The module has no `INTERPRETERS`
and no `CppSiemens`: `interpreter_names()` lists the names of the interpreters
that are installed.

`SequenceData` is an immutable frozen dataclass:

| Field | What it holds |
|---|---|
| `version` | `(major, minor, revision)` |
| `definitions` | Each key of `[DEFINITIONS]` to its tokens as text |
| `rasters` | `model.Rasters`: `gradient`, `rf`, `adc`, `block_duration`, in s |
| `required_extensions` | The STRING_IDs of `RequiredExtensions` |
| `blocks`, `rf`, `grad`, `trap`, `adc` | Structured arrays, dtypes in `model.TABLE_DTYPES`, in s, Hz, Hz/m, rad and ppm |
| `shapes` | `model.Shape` (`num_samples`, `packed`; `samples()`) by shape ID |
| `extensions` | `model.Extensions`: `entries`, `type_ids`, `triggers`, `labelset`, `labelinc`, `soft_delays`, `rotations` (normalized quaternions), `rf_shims` |
| `skipped_extensions` | The STRING_IDs of the extensions that the interpreter does not know |
| `records` | A `model.Record` for each thing that the interpreter ignored (2.6) |
| `signature` | `model.Signature` (`type`, `hash`, `matches`), or None |
| `origin` | `"file"` or `"pypulseq"` |
| `interpreter` | The interpreter object, with its settings |
| `reading` | For `cpp-siemens`, the reader's own object (2.4); None for `spec`. Not compared by `==` |

The model of `cpp-siemens` is built from the reader's own libraries (P14), so
it differs from that of `spec` where the reader does (the docstring of
`pulseq_cpp_siemens.interpreter` lists how): a block's `id` is its position in play order
from 1 (the reader keeps no block ID; D7.3); values are the reader's float32 values,
converted to float64 (P6, D7.2); a 1.4 RF event has `center` NaN (D7.5); `use` is
any character; `[GRADIENTS]` and `[TRAP]` are one library; `first`
and `last` of a 1.4 gradient with a time shape are the reader's sentinel
`FLOAT_UNDEFINED`, about 1.18e-38 (D4.4, D4.5); the definitions are in the order
of their keys, each with its last value (D2.6); and `Signature.matches` is the
reader's own MD5 check.

### 2.3 The decoding of `spec`

`synth.decode(data, session=None)` of a `spec` model gives
`synth.SpecDecoding` (`interpreter`, `session`, and `gradients`: the gradient
events of the model by file ID; `blocks`, the block table of the model;
`block_durations` and `stored_block_durations` in s, in play order from 0;
`norot` and `noscale`, the flags of the field of view, 2.8). The decoding does
not build the RF and ADC events: they are `decode_rf(snap.data)` and
`decode_adc(snap.data)`. The events are in module `synth.events`:

- `RfEvent`: `id`, `amplitude`, `mag_id`, `phase_id`, `time_id`, `magnitude`,
  `phase`, `t`, `dwell` (None for a pulse of points, D2.10, D2.11), `shape_dur`,
  `center`, `delay`, the ppm and offset fields, `use`; `signal(times)` gives
  the complex signal at any times.
- `Trapezoid` and `ArbitraryGradient` (together `GradEvent`): `waveform`, `tt`,
  `shape_dur`, `first`, `last` and the fields of the row.
- `AdcEvent`: the fields of the row, and `phase_modulation` in rad, one value
  for each sample (D2.15), or None.

The decoder follows the specification and the slides (`docs/usage.md`, "The
decoder of `spec`"). `model.rf_time_step(times)` tells a pulse of cells from a
pulse of points. As each decoding (the protocol `synth.Decoding`, 2.4), `SpecDecoding` has:

- `block_count`; `session`; `block_durations` (actual) and
  `stored_block_durations` (2.8).
- `gradients_at(block_index, time_us, rotated=None)`: the gradients in Hz/m,
  an array (n, 3), at times in µs from the start of each block. Each event is
  the straight lines between its points (`seq_utils.gradient_offsets`), 0
  before its delay and after its end, and every value is 0 outside the block
  (its actual duration). `rotated` None or True turns each block with a
  rotation by its quaternion, from 1.5.1 (`synth.decoding.rotate`, the active
  rotation `R(q) v` with q0 the scalar part, in float64), and applies the
  session's field of view (2.8); `False` gives the logical gradients.
- `rotations()`: the play indices of the blocks whose extension list has a
  ROTATIONS object, and their quaternions (n, 4), divided by their norm (D2.18).
  Both are empty for a file older than 1.5.1, where ROTATIONS is an unknown
  extension (P20, rule 2).
- `rotation_record`: a `synth.RotationRecord` (2.6) with the setting
  `"apply"`; it never has a warning, since `spec` applies the file's content.
- `soft_delay_record`, `fov_record` and `fov_flags()` (2.6, 2.8).
- `gradient_points(key, block, axis)`: the points of the gradient event with
  the file ID `key` that the block plays on the axis (0, 1, 2 for x, y, z), not
  rotated: a tuple `synth.decoding.Points` of the delay in s, the offsets in s
  from the delay and the values in Hz/m, the points between which the event is
  straight lines (`seq_utils.gradient_offsets`).
- `gradient_variants()`: None, since `spec` decodes each gradient event alike
  in every block that plays it.

On each fixture with rotations from 1.5.1, its blocks and quaternions are
those of `cpp-siemens`, and its rotated gradients are those of
`pulseq_cpp_siemens.interpreter.CppSiemens(rotation="apply")` to float32
precision and those of MATLAB's
`waveforms_and_times`.

### 2.4 The reading and decoding of `cpp-siemens`

`SequenceData.reading` is a `pulseq_cpp_siemens.Sequence`. Its `libraries`
(`pulseq_cpp_siemens.Libraries`) are what `ExternalSequence::load` read, as
the reader holds it, misreadings included, with the file's event IDs:
`version`, `version_parts`, the four rasters in µs, `definitions` and
`definition_values`, `blocks` (int64, the columns of
`pulseq_cpp_siemens.BLOCK_COLUMNS`), `shapes` (each a `pulseq_cpp_siemens.Shape`:
`num_samples`, `compressed`, `samples` in float32), `rf`, `grad`, `adc`,
`extension_list`, `extension_types`, `triggers`, `rotations`, `labelset`,
`labelinc`, `soft_delays`, `rf_shims`, and `signature`. Text is bytes, as in the
file.

`synth.decode(data, session=None)` of a `cpp-siemens` model gives
`pulseq_cpp_siemens.interpreter.CppSiemensDecoding` (the method
`CppSiemens.decode(data, session)`), a view of that reading. A decoding of a
plugin is of the protocol `synth.Decoding` (module `synth.decoding`), which
`SpecDecoding` also follows: `interpreter`, `session`, `block_count`,
`block_durations`, `stored_block_durations`, `rotations()`, `rotation_record`,
`soft_delay_record`, `fov_record`, `fov_flags()`,
`gradients_at(block_index, time_us, rotated=None)`,
`gradient_points(key, block, axis)` and `gradient_variants()`. The plugin class states the version of the
protocol that it implements (`protocol`, 1; `seqfile.PROTOCOL`), and the package
uses a plugin only of its own version (2.8). `CppSiemensDecoding` has these, and the
blocks of the reader. Blocks are in play order from 0:

- `block_count`; `block(index)` and `blocks()`: `GetBlock` and `decodeBlock`,
  the fields of the C++ oracle's `--dump` (section 6), in the reader's units
  (µs, Hz, Hz/m, rad), after the resampling and the clamps.
- `gradients_at(block_index, time_us, rotated=None)`:
  `SeqBlock::gradientsAt` in Hz/m, an array (n, 3), 0 before and after the
  block, whose end is set with the reader's hook `setActualSoftDelay_ru` under a
  session's soft delays. `rotated=None` follows the setting `rotation` and the
  session's field of view; `False` gives the reader's own values; `True` turns
  each block with a rotation by its quaternion, with the reader's own
  `rotate_vec3_by_quat`, and applies the field of view (2.8).
- `rotations()`: the play indices of the blocks to which `GetBlock` attaches a
  rotation (the first of the list), and their quaternions (n, 4), q0, qx,
  qy, qz, as the reader normalized them. The same in each setting.
- `gradient_points(key, block, axis)`: the points between which `gradientsAt`
  draws its straight lines for the gradient that the block plays on the axis,
  as the reader decoded it (not rotated), as `synth.decoding.Points` (2.3). It
  takes the block because the reader decodes an event in each block.
  For a gradient with a time shape, in any version, the points run from the
  amplitude times the first sample (the first segment carried back to the
  delay when the first time is after 0) to the amplitude times the last
  sample: `gradientsAt` never reads `first` or `last`, where `spec` plays the
  `first` and `last` of a 1.5 file. They differ when these are not the end
  samples (run, R14: the file that pypulseq writes for
  `gap_sequences.short_arbitrary_sequence`, a 3-sample gradient that the writer
  gives a time shape; `spec` rejects it, D1.3 and `gradient.nonzero-end-align`).
- `gradient_variants()`: which blocks and axes decode their gradient event
  alike, from the libraries, with no block decoded. The reader decompresses
  the shapes of the gradients of a block into one buffer (cpp:2094-2196), so a
  shape that writes fewer than its `num_samples` values keeps the values of the
  shape before it in the block. An arbitrary gradient whose wave shape does so,
  or an extended trapezoid whose time shape does so, gets a variant for each
  set of events on the earlier axes of its block; every other cell has 0. None
  when no event depends on its block, as in each file that `spec` reads.
- `rotation_record`: a `synth.RotationRecord` (2.6).

These are the reader's values bit for bit, on each platform (section 6).

### 2.5 The rejections

- `seqfile.SeqFileError` (a `ValueError`, module `seqfile.errors`): the
  interpreter gives no waveform. `violations` is a tuple of `seqfile.Violation`
  (`rule`, the code; `section`; `line`, or None; `message`); `codes` is the set
  of the codes; `omitted` maps a code to the number of its reasons left out of
  `violations`; `interpreter` is the name; `path` is the file (or
  `from_pypulseq.SOURCE`, `"<pypulseq.Sequence>"`, for a sequence in memory).
- `seqfile.NotSupported` (a `NotImplementedError`): the package does not read
  the file in either interpreter: a version outside 1.4.0 to 1.5.x (Q1), and for
  `cpp-siemens` a binary Pulseq file or a folder. It says nothing about the
  file.
- `ValueError` for a name that no installed interpreter has, for example
  `cpp-siemens` when pulseq-cpp-siemens is not installed: "no interpreter is
  named 'cpp-siemens'; the installed interpreters are spec. A distribution adds
  one through the entry-point group pulseq_analysis.interpreters." There is no
  extra to install. `ImportError` (chained) for a plugin that does not load;
  `OSError` when the file cannot be read.

**The codes of `spec`** are the keys of `seqfile.spec.RULES` (41 codes). Each
is a `spec.Rule`: `text`, `source` (the lines of the specification as
`spec:N`, the slides as "slide N", the entries of the record), `choice` (None
when the specification or the slides state the rule; otherwise why the package
rejects such a file) and `partial` (the choice covers only some of the
conditions). The message of a violation of a chosen rule ends with "(the
specification does not state this rule: …)". A rejection has every violation,
at most `spec.MAX_LOCATIONS` (20) for each code, and counts the rest in
`omitted`. The table of codes with their basis is in `docs/usage.md`, "The
interpreters"; the codes are:

`version.missing`, `version.invalid`, `definitions.raster-missing`,
`definitions.raster-invalid`, `definitions.raster-commensurate`,
`section.duplicate`, `syntax.encoding`, `syntax.line`, `syntax.columns`,
`syntax.integer`, `syntax.number`, `syntax.use`, `syntax.negative`,
`syntax.shape`, `id.positive`, `id.unique`, `id.gradient-unique`,
`ref.unresolved`, `blocks.empty`, `block.event-too-long`, `raster.adc-dwell`,
`raster.gradient-delay`, `raster.gradient-end`, `raster.gradient-ramp`,
`raster.gradient-flat`, `raster.rf-delay`, `raster.adc-delay`,
`raster.gradient-vertex`, `gradient.nonzero-start-delay`,
`gradient.nonzero-end-align`, `shape.length`, `shape.range`, `shape.empty`,
`shape.event-length`, `shape.time-order`, `shape.oversampled-length`,
`extension.required-unknown`, `extension.per-block`, `layer1.gradient-ends`,
`rotation.zero`, `signature.invalid`.

The limits of the rules are `spec.TOLERANCE_NS`, `spec.RANGE_TOLERANCE`,
`spec.FIRST_TIME_TOLERANCE`, `spec.RATIO_TOLERANCE` and
`model.TIME_TOLERANCE`.

**The codes of `cpp-siemens`** are the keys of `pulseq_cpp_siemens.interpreter.CODES`
(29 codes). Each maps to its entry of the record and what the reader rejects.
The reader stops at its first error, so a rejection has one reason, with the
reader's own message; `line` is set where the message quotes a row. The `ub.*`
codes are also `pulseq_cpp_siemens.CODES`.

| Code | Entry | The C++ reader rejects |
|---|---|---|
| `version.missing`, `version.invalid` | D1.1 (`version.missing`) | no `[VERSION]`; a line of it that does not decode, or an unknown key |
| `definitions.raster-missing`, `definitions.raster-invalid` | — | a raster that is not defined; one that the reader does not read as a number |
| `definitions.skipped` | D2.2 | the rasters, because the reader skipped `[DEFINITIONS]` after a section that ran to the end of the file |
| `extension.required-unknown` | — | an unknown required extension |
| `section.extensions-last` | D2.3 | `[EXTENSIONS]` as the last section |
| `blocks.missing` | — | no `[BLOCKS]` section |
| `syntax.row` | — | a row that does not decode with the reader's `sscanf` format |
| `syntax.comment-row` | D2.5 | a `#` line inside a table |
| `syntax.shape` | — | a line of `[SHAPES]` that does not decode |
| `ref.unresolved` | — | a block that names an event that the reader did not read |
| `rotation.norm` | — | a quaternion whose norm is more than 1e-3 from 1 |
| `gradient.raster` | — | an arbitrary gradient in a file whose gradient raster is not 10 µs |
| `shape.decompression` | — | a compression that the reader cannot decode |
| `shape.ext-trap-lengths` | — | an extended trapezoid whose time shape and waveform differ in length |
| `cpp.exception`, `cpp.rejected` | — | a C++ exception; any other rejection |
| `ub.shape-missing` | D5.1 | a block uses a shape that the reader did not read |
| `ub.rf-time-id-minus-1` | D5.3 | an RF event with time ID -1 |
| `ub.extension-cycle` | D5.4 | a cycle in an extension list (no end) |
| `ub.shape-decompression` | D5.5 | a shape that decompresses past its buffer, or reads one value past it |
| `ub.shape-empty` | D5.6 | a shape with no sample |
| `ub.rf-shape-lengths` | D5.7 | an RF phase shorter than its magnitude |
| `ub.rf-time-overrun`, `ub.rf-time-range` | D5.8, D5.9 | the RF resampling reads past the time shape; a last time that does not fit an `int` |
| `ub.gradient-time-range` | D5.11 | an extended trapezoid time that does not fit a `long` |
| `ub.gradient-one-point` | D5.10 | `gradientsAt` reads past an extended trapezoid of one point |
| `ub.gradient-shape-0` | D5.2 | a `[GRADIENTS]` row of shape 0, which `load` leaves unset |

### 2.6 What a result records

Rule 4 of section 7.8 of the plan (P20): every result records what was applied
of the scanner-side settings. Rule 7: these records are part of the contract.

- **`SequenceData.records`**: a tuple of `model.Record` (`kind`, `subject`,
  `reason`, `line`), in file order, for each thing that the interpreter ignored.
  `kind` is `"extension"`, `"section"` or `"label"`. `reason` is `"unknown"`
  (D2.4, D2.17, D2.19, and `NOSCL`, which the specification spells `NOSLC`,
  D2.22), `"version"` (the file is older than the revision that introduced it:
  an extension, or a flag of 1.4.1) or `"removed"` (`[DELAYS]`, D2.4). A label's
  row stays in its table. Since R16, `cpp-siemens` records an extension that the
  reader does not know (`"extension"`, `"unknown"`) and each LABELSET or
  LABELINC row that `decodeLabel` does not know and leaves out of its library
  (`"label"`, `"unknown"`): `NOSLC`, `PMC`, `TRID` and any unlisted name (D6.4).
- **`SequenceData.skipped_extensions`**: the extensions that the interpreter
  does not know. For `spec` it follows the version gate: `DELAYS` from 1.5.0,
  `ROTATIONS` and `RF_SHIMS` from 1.5.1 (section 7.8 of the plan, rule 2); the
  definition `RequiredExtensions` is read from 1.5.1 too. For `cpp-siemens` it is the extensions that the reader
  ignores, in any version.
- **`synth.RotationRecord`** (module `synth.scanner`), from
  `rotation_record` of each decoding (`CppSiemensDecoding`, `SpecDecoding`):
  `setting` (`"reader"` or `"apply"`; always `"apply"` for `spec`),
  `blocks` (with a rotation), `not_identity` (whose quaternion has a vector part
  that is not 0), `rotated` (`blocks` with `"apply"`, else 0); `unapplied`; `str`
  (for example "rotation: apply, 5 block(s) rotated"); and `warning()`, a
  `synth.ScannerSettingWarning` (a `UserWarning`) when the default leaves a
  rotation unapplied, else None. The decoding never emits it, so pulseq-checks
  is not warned about the reader's own output. `hint` (a `str`, empty by
  default, not compared by `==`) is the advice of the interpreter that the text
  of the warning ends with: the record names no interpreter itself. For
  `cpp-siemens` with `rotation="reader"` it says to use
  `CppSiemens(rotation='apply')` for the gradients that the scanner plays.
- **`synth.SoftDelayRecord`**, from `soft_delay_record` of each decoding (R16):
  `values` (the session's (hint, value in s) pairs, sorted by hint), `hints`
  (the hints of the soft delays that the interpreter attaches to the blocks),
  `blocks` (with a soft delay), `applied` (whose duration the session sets) and
  `unset` (the hints of the file with no value: at their stored durations).
  Never a warning: the neutral session is the exported sequence (rule 4).
- **`synth.FovRecord`**, from `fov_record` of each decoding (R16): `rotation`
  and `scaling` (the session's), `scaling_flag` (`"NOSLC"` for `spec`, `"NOSCL"`
  for `cpp-siemens`), `norot` and `noscale` (the blocks with each flag set, a
  state across blocks), `rotated` and `scaled` (the blocks that the field of
  view turns or scales). Never a warning.

### 2.7 `load` and the snapshot (R14)

Task R14 puts the measurements on the interpreters. These are part of the
contract too:

- `analyses.load(source, interpreter="spec")`: a path is read with
  `seqfile.read_seqfile`, a `pypulseq.Sequence` with `seqfile.read_pypulseq`,
  through the interpreter given by name or as an object (`spec` or a plugin's).
  It raises their `SeqFileError` and `NotSupported`. pypulseq no longer reads a
  file.
- `synth.Snapshot`: `data` (the `SequenceData`), `session` (R16), `decoding`
  (`synth.decode(data, session)`, a `synth.Decoding`), `interpreter` (with its
  settings), `records` (`SequenceData.records`), `rotation_record`,
  `soft_delay_record` and `fov_record` (the decoding's records) and `source` (the
  path, or None). `load(source, interpreter, session=None)` takes the session
  (2.8).
- `load` emits `RotationRecord.warning()` (a `ScannerSettingWarning`) when it is
  not None: under `CppSiemens(rotation="reader")`, for a file whose blocks play
  a rotation. `load` no longer refuses the rotation extension
  (`synth.extensions` is removed).
- The measurements take the gradients only through the decoding (the protocol
  `synth.Decoding`): `gradient_points` for the decoded event of each block and
  axis, once for each event and variant (`gradient_variants`; for `cpp-siemens`,
  the reader's decoding of the event and the points of its `gradientsAt`), and `gradients_at` for a block that the decoding rotates or
  that has an event after the block's end. Between blocks, every interpreter
  uses the package's waveform (MATLAB's ramps and lines, D2.14, D7.4): the
  reader gives nothing there.
- The block table (`seq.index`) keeps the file's IDs; each other variant of an
  event, and in a block measured from `gradients_at` each axis, has an event of
  its own, numbered after the file's.
  Its durations are the decoding's actual ones (R16).

### 2.8 The scanner session (R16)

Task R16 adds the inputs of the scanner session (section 7.8 of the plan, rules
3 to 8; P22). This is a change of the contract.

- **`synth.Session`** (module `synth.scanner`): `soft_delays` (s, by hint; kept
  as sorted (hint, value) pairs), `fov_rotation` (a quaternion q0, qx, qy, qz,
  norm 1 within 1e-6, divided by its norm) and `gradient_scaling` (sx, sy, sz,
  each above 0). `Session()` is the neutral session, the default everywhere:
  each block at its stored duration, the field of view not rotated or scaled.
  Frozen, compared by value, hashable. A field that it does not have is a
  `TypeError`.
- **The plugin protocol, version 1** (`seqfile.PROTOCOL`): a plugin class has
  `protocol = 1` and `decode(data, session=None)`. `synth.decode` gives it a
  `Session`. `seqfile.interpreter` raises `TypeError` for a plugin of another
  version (or of none, the protocol before R16), naming both versions.
  `CppSiemens.protocol` is 1.
- **The stored and the actual durations**: `Decoding.stored_block_durations`
  (the file's) and `Decoding.block_durations` (under the session's soft delays;
  the stored ones by default). `SpecDecoding.block_durations` was the stored
  duration before R16 and is now the actual one. `gradients_at` is 0 after the
  actual end, and the measurements and the block table use the actual one.
- **Soft delays** (D2.21, D6.3): a block's duration is `value / factor +
  offset` on the block duration raster, rounded half away from 0, for each soft
  delay with a value; `spec` from 1.5.0. `cpp-siemens` takes the soft delays as
  the reader attaches them (its misreadings included, D2.16) and sets the
  duration with the reader's hook `setActualSoftDelay_ru`.
- **The field of view** (D2.20, D2.22, D6.4): R_fov R_block S g, the order of
  MATLAB's `mr.TransformFOV`; not turned in a block with `NOROT`, not scaled in
  a block with the scaling flag: `NOSLC` for `spec` (from 1.4.1), `NOSCL` for
  `cpp-siemens` (the reader drops `NOSLC`). `Decoding.fov_flags()` gives both
  flags of each block.
- **`synth.SettingError`** (a `ValueError`, rule 8): `setting` (for example
  `"soft_delays['TE']"`), `interpreter`, `version` and `reason`. It is raised
  by `synth.decode` and `load` for a soft delay hint that the file does not have
  under the interpreter, a file before 1.5.0 under `spec`, a hint with two
  numeric IDs (or whose numeric ID another hint has), a soft delay in a block
  with an event or with two soft delays, and a negative duration. The field of
  view is valid on any file.
- **The shared simulation** (rule 6), which a plugin may import:
  `synth.scanner.soft_delay_durations`, `fov_flags`, `physical_gradients`,
  `fov_record` and `SoftDelay`.

For pulseq-checks: the records describe the package's measurement under a
session, not the file. A finding about the file (two numeric IDs for one hint, a
soft delay outside a pure delay block, `NOSCL` against `NOSLC`) stays
pulseq-checks' own; the `SettingError` is raised only when a session addresses
it.

## 3. The four mechanisms

pulseq-checks finds each discrepancy of the record with one of four mechanisms
(section 7.4 of the plan). Each entry of the record is titled by a condition in
a file, so each maps to one or more of them. Section 4 gives the mapping.

There was a fifth mechanism, M5, a catalogue of MATLAB Pulseq and pypulseq. It
is removed: the records keep only the decisions of the two interpreters, and a
disagreement of MATLAB Pulseq or pypulseq alone is not recorded (the user,
2026-10-13). The conditions that pulseq-checks finds through M3 (the violations
of `spec`) and M4 (the comparison of the two interpreters) need no entry in the
record; a condition has an entry only where an interpreter decides something
(`spec` where the specification is unclear or silent, `cpp-siemens` where it
departs from the C++ reader).

| | Mechanism | What it finds | Readings it uses |
|---|---|---|---|
| M1 | A diff of the "as written" reading against the `cpp-siemens` reading and decoding | The reader changes, drops or misreads a value | `AsWritten`; `SequenceData` of `cpp-siemens` and `reading.libraries`; `pulseq_cpp_siemens.interpreter.CppSiemensDecoding` |
| M2 | A condition on the "as written" reading | The reader plays something that a diff of values cannot show | `AsWritten` (and the version) |
| M3 | `spec`'s violations on the same file | A "must" broken, which the reader plays as written | `SeqFileError.violations` of `spec`, `spec.RULES` |
| M4 | A comparison of the two interpreters | One rejects and the other reads, or their waveforms differ | Both results: model, decoding, or rejection codes |

A file that `cpp-siemens` rejects still gets findings: pulseq-checks reads it
as written and through `spec`. The two readings must agree on which field is
which; the column names of `AsWritten` are those of `SequenceData`, but the
`cpp-siemens` model numbers blocks in play order and merges `[GRADIENTS]` and
`[TRAP]` (2.2), so M1 aligns blocks by position and events by file ID.

## 4. Each entry of the record

"Mechanism" is from section 7.4 of the plan; "—" means that section 7.4 lists
none for the entry (section 5 says which choice that leaves). M4 is marked
where the two interpreters differ. Fixtures are in
`tests/seqfiles/` unless the path says otherwise; "none" means that the record
gives a run in the text of the entry, not a fixture. Codes are today's: "reads"
means no code.

| Entries | Condition | Mechanism | Fixture | `cpp-siemens` | `spec` |
|---|---|---|---|---|---|
| D1.1 | No `[VERSION]` | — (both reject) | `bad_version_missing.seq` | `version.missing` | `version.missing` |
| D1.2, D4.2 | `[RF]` 12, `[GRADIENTS]` 7, `[ADC]` 9 fields | — (agree) | none (the specification's examples) | `syntax.row` for a short row | `syntax.columns` |
| D1.3 | A vertex of a gradient time shape off the gradient raster | M3, M4 | `bad_raster_gradient_vertex.seq` | reads | `raster.gradient-vertex` |
| D1.4 | `STRING_ID` that is a word | — (agree) | `valid_1_5_1.seq` | text | text |
| D2.1, D5.1 | Unusual section order; `[VERSION]` last | M1, M4 | `undefined/version_last.seq` | `[VERSION]` last: no shape read; `definitions.skipped` or `ub.shape-missing` | reads |
| D2.2 | Last section with no blank line after it | M1, M4 | `valid_last_section_no_blank.seq` | `definitions.skipped` | reads |
| D2.3 | `[EXTENSIONS]` last | M4 | `oracle/koma_v1.5_unknown_ext.seq` | `section.extensions-last` | reads |
| D2.4 | Unknown section; `[DELAYS]` from 1.4.0 | M2 | `bad_section_unknown.seq`, `bad_section_delays.seq` | reads (ignores) | reads (ignores); `Record("section", …, "unknown")`, and `"removed"` for `[DELAYS]` |
| D2.5, D3.2 | Blank or `#` line inside a section | M1 (blank line), M4 | `bad_syntax_line.seq`, `bad_syntax_line_after_comment.seq`, `valid_comment_in_shape.seq`, `valid_comments_between_sections.seq` | drops the rows after a blank line; `syntax.comment-row` | reads them; `syntax.line` before the first section |
| D2.6 | A definition twice | M1 | `bad_definitions_duplicate.seq` | the last | the last |
| D2.7, D7.1 | A definition or hash that reads as a number | M2 | none | text | text |
| D2.8 | RF magnitude below 0 | M1, M4 | `bad_shape_rf_magnitude_negative.seq` | clamps to 0 | plays as written |
| D2.9 | RF phase outside [0, 1) | M1, M4 | `bad_shape_rf_phase_range.seq` | clamps | plays as written |
| D2.10 | Regular RF time shape | M2, M4 | `valid_rf_time_shapes.seq`, `bad_shape_rf_time_grid.seq` | as C++ | cells when the times are `(i + 0.5) d`, else points |
| D2.11, D3.9, D5.8, D5.9 | Other RF time shape | M2 (1), M4 | `bad_shape_rf_time_end.seq`, `bad_shape_time_order.seq` | as C++; `ub.rf-time-overrun` | points; `shape.time-order` |
| D2.12 | RF time shape that ends inside its last dwell | M2, M4 | none | dwell × samples | `N d`, or the last point |
| D2.13 | Time-ID-0 gradient between its samples | — (agree) | `valid_1_5_1.seq` | straight lines | straight lines |
| D2.14, D7.4 | Gap between gradient events | M2 | none | one block at a time; `load` joins blocks with MATLAB's rule (section 2.7) | 0 in a block; across blocks MATLAB's rule |
| D2.15, D3.8, D7.6 | ADC phase modulation shape | M4 | `valid_1_5_1.seq`, `bad_shape_adc_phase_length.seq` | rad | rad, one per sample; `shape.event-length` |
| D2.16 | Soft delay offset `-100.5`; long hint | M1, M4 | `valid_soft_delay_fraction.seq` | misreads (-100 µs, factor 0.5); cuts the hint to 31 characters | reads -100.5 µs and the whole hint |
| D2.17, D4.6 | Unknown extension, not required | M2 | `oracle/koma_v1.5_unknown_ext.seq`, `valid_1_5_0_extensions_of_1_5_1.seq` | ignores (`skipped_extensions`) | ignores; `Record("extension", …)` |
| D2.18, D3.10, D4.6, D6.2 | Played rotation; quaternion norm | M2, M4 | `oracle/pulseq_make_radial.seq`, `oracle/koma_v1.5_rotation_radial_tiny.seq` | normalizes; `rotation.norm`; rotates with `rotation="apply"` | normalizes and rotates from 1.5.1; `rotation.zero` |
| D2.19, D4.7 | Unknown label name | M1 | `valid_label_unknown.seq` | leaves the label out | reads; `Record("label", …, "unknown")` |
| D3.1, D3.5, D3.6 | A byte that is not UTF-8; NaN in a float column; a negative time or count | M3, M4 | `bad_syntax_encoding.seq`, `bad_syntax_negative.seq`, `bad_syntax_number.seq` | reads | `syntax.encoding`, `syntax.negative`, `syntax.number` |
| D3.3 | A section twice | M1, M4 | `bad_section_duplicate.seq`, `bad_section_duplicate_extension.seq`, `bad_section_duplicate_signature.seq` | reads the last | `section.duplicate` |
| D3.4 | A block ID used twice | M3, M4 | `bad_id_unique_block.seq` | reads | `id.unique` |
| D3.7, D5.6 | Empty shape | — (both reject) | `bad_shape_empty.seq` | `ub.shape-empty` | `shape.empty` |
| D3.8, D5.7 | Shapes of one event, two lengths | M1 (longer phase), M4 | `bad_shape_event_length.seq` | `ub.rf-shape-lengths` (shorter phase); reads a longer one | `shape.event-length` |
| D3.11, D5.1 | No blank line after a shape | M1, M4 | `bad_syntax_shape_no_blank_line.seq`, `bad_syntax_shape.seq`, `bad_syntax_shape_end.seq` | later shapes lost, then `ub.shape-missing` | `syntax.shape` |
| D4.1 | Version outside 1.4.0–1.5.x | — (scope) | `bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq` | `NotSupported` | `NotSupported` |
| D4.2, D7.5 | 1.4 RF event, no `center` | M2 | `oracle/koma_v1.4_fid.seq` | `center` NaN | `center` NaN |
| D4.3, D5.3 | Time ID -1 for RF, or in 1.4 | M2 (1.4 gradient), M4 | `undefined/rf_time_id_minus_1.seq`, `bad_ref_time_id_minus_1_in_1_4.seq` | `ub.rf-time-id-minus-1`; reads a 1.4 gradient | `ref.unresolved` |
| D4.4 | 1.4 gradient on the default raster | M2, M4 | `bad_layer1_gradient_ends.seq`, `oracle/koma_v1.4_gr-uniformly-shaped.seq` | reads; ends `FLOAT_UNDEFINED` | `layer1.gradient-ends` |
| D4.5 | 1.4 time-shaped gradient, no `first` | M2 | `valid_1_4_1.seq` | the first sample | the first sample; `layer1.gradient-ends` when the time shape starts after 0 |
| D5.1, D5.2 | A reference that does not resolve | M1 (extension lists), M4 | `bad_ref_block_rf.seq`, `bad_ref_shape.seq`, `bad_ref_time_shape.seq`, `bad_ref_extension_entry.seq`, `bad_ref_extension_object.seq`, `bad_ref_extension_type.seq` | `ref.unresolved`, `ub.shape-missing`; reads the extension cases | `ref.unresolved` |
| D5.4 | Cycle in an extension list | — (both reject) | `bad_ref_extension_cycle.seq` | `ub.extension-cycle` | `ref.unresolved` |
| D5.5 | Shape length | M1 (shorter), M4 | `bad_shape_length.seq`, `undefined/shape_decompress_longer.seq`, `packages/pulseq-cpp-siemens/tests/fixtures/shape_decompress_count_missing.seq` | `ub.shape-decompression` (longer); reads a shorter one | `shape.length` |
| D5.10 | Extended trapezoid of one point at a time above 0 (only in the `cpp-siemens` record) | M4 | `packages/pulseq-cpp-siemens/tests/fixtures/gradient_one_point.seq` | `ub.gradient-one-point` | `gradient.nonzero-end-align` (the fixture's other condition) |
| D5.11 | Extended trapezoid time that does not fit a `long` (only in the `cpp-siemens` record) | M4 | `packages/pulseq-cpp-siemens/tests/fuzz_corpus/gradient-time-range.seq` | `ub.gradient-time-range` | `definitions.raster-invalid`, `layer1.gradient-ends` (the fixture's other conditions) |
| D6.1 | Oversampled gradient | M2, M4 | `oracle/koma_v1.5_spiral.seq`, `valid_1_5_0.seq`, `bad_shape_oversampled_length.seq` | the centre samples (`oversampling="center"`) | all the samples; `shape.oversampled-length` |
| D7.2 | Value beyond float32 | M1, M4 | none | float32 values (P6) | float64 |
| D7.3 | Block IDs out of order | M2 | `bad_blocks_order.seq` | file order | file order |

The fixture of `ub.gradient-shape-0` is
`packages/pulseq-cpp-siemens/tests/fixtures/gradient_shape_0.seq` (D5.2). Each fixture's verdict under the C++ reader is in
`packages/pulseq-cpp-siemens/tests/expected_digests.json`.

## 5. Categories, and the choices left to pulseq-checks

Section 7.4 of the plan proposed five categories; the fifth, `writers-differ`, went with M5. The other four describe a finding;
pulseq-checks grades them:

| Category | A finding where |
|---|---|
| `interpreters-differ` | `spec` and `cpp-siemens` differ: one rejects, or their waveforms differ (M4) |
| `spec-departure` | the file breaks a rule of the specification that the reader plays as written (M3) |
| `cpp-changes-value` | the reader changes, drops or misreads a value (M1) |
| `cpp-default` | the reader uses a default that the scanner's interpreter can set: D4.4 (`FLOAT_UNDEFINED`), D6.1 (oversampling) |

pulseq-analysis does not change when pulseq-checks makes a policy stricter.
These choices are pulseq-checks':

- **The float32 tolerance of D7.2.** `cpp-siemens` holds the reader's float32
  values (P6); a diff against the "as written" float64 values needs a tolerance
  for a change to be "noticeable". The record's runs compare with a relative
  tolerance of about 1e-6.
- **Severity, profiles and exit codes** (section 7.5 of the plan), for example
  "scanner" (an error when `cpp-siemens` rejects), "specification" (an error
  when `spec` rejects) and "portable" (an error for each `interpreters-differ`
  finding).
- **The entries that section 7.4 maps to no mechanism**: D1.1, D5.4 and D3.7,
  D5.6 (both interpreters reject), D1.2, D1.4 and D2.13 (all agree) and
  D4.1 (scope). Whether they get a finding, or none, is pulseq-checks' choice.
- **The chosen rules of `spec`.** A rule whose `spec.Rule.choice` is not None
  rests on the package's choice, not on the specification. pulseq-checks
  decides whether a rejection by such a rule is reported as a departure from the
  specification.
- **The records** (2.6): whether an ignored section, extension or label
  (D2.4, `[DELAYS]`, D2.17, D2.19, `NOSCL`) is a finding, and with which severity.
- **D2.18**: `spec` divides a quaternion by its norm with no rejection; section
  6 of the plan says that a norm more than 1e-3 from 1 gets a finding. The norm
  as written is in `AsWritten`; pulseq-checks sets the threshold.
- **A signature that does not match** (`Signature.matches` False) is not a
  rejection in either interpreter.
- **`cpp.exception` and `cpp.rejected`**: codes for a rejection that no other
  code names; pulseq-checks decides how to report them.
- **D7.4, across blocks and after the block end**: what the reader plays
  there is not visible in one decoded block (section 13 of the plan).

## 6. The test oracles of the flake

The flake of this repository (`flake.nix`) builds three programs from
pulseq/pulseq at `c7469123c2f381f065986e6cc3a7d09730ed16ef`. Each is an output
`packages.<system>.<name>`, so a consumer can run it from a flake reference,
for example
`nix run github:mdtisdall/pulseq-analysis#pulseq-cpp-oracle -- --dump FILE`
for `main`, or `github:mdtisdall/pulseq-analysis/<tag>#pulseq-cpp-oracle` for
a release.

| Program | What it gives | Documentation |
|---|---|---|
| `pulseq-cpp-oracle` | The C++ reader with a small driver, built with `-fsigned-char -ffp-contract=off` (the `char` and arithmetic of the scanner's x86_64 build on each system). `FILE`: the verdict as the exit status (0 reads, 1 rejects, 70 crashes). `--dump FILE`: what the reader holds after `load` and `decodeBlock`, as JSON. `--sample FILE`: `SeqBlock::gradientsAt` for lines `block_index time_us` on stdin. `--oversampling=center\|edge\|preserve` sets the reader's mode. | [`tests/cpp_oracle/README.md`](../tests/cpp_oracle/README.md) |
| `pulseq-cpp-oracle-sanitized` | The same reader and driver with AddressSanitizer, UndefinedBehaviorSanitizer and the standard library's assertions (clang of LLVM 22). Exit status 3: the reader has undefined behaviour on the file, whatever an ordinary build does. | the same README, "The sanitized build" |
| `pulseq-matlab-oracle OUT_DIR FILE.seq...` | MATLAB Pulseq run under GNU Octave: `read`, `getBlock` and `waveforms_and_times(true)` of each file, as JSON. About 2.5 GiB of closure; only in the default devShell. | [`tests/matlab_oracle/README.md`](../tests/matlab_oracle/README.md) |

`cpp-siemens` gives the same values in the process: its `decode_block` has the
fields of `--dump`, and its `gradients_at` those of `--sample`, bit for bit on
each fixture (`packages/pulseq-cpp-siemens/tests/expected_digests.json`).
pulseq-checks needs the C++ oracle only to check that, or for a file that it
must read in another process. The helpers of `tests/oracles/` are this
project's test code, not part of the contract.

## 7. What is still to come

These parts of the contract are planned; a row marked done is in the code of
`main`. Each task updates this document and `CHANGELOG.md` when it changes the
contract, and marks its row done.

| Task | What it adds |
|---|---|
| R9, the `spec` part | Done: `SpecDecoding.gradients_at`, `rotations()` and `rotation_record` (2.3). |
| P21 | Done: `cpp-siemens` is a plugin of the sub-project `packages/pulseq-cpp-siemens/` (`pulseq_cpp_siemens.interpreter`), found through the entry-point group `pulseq_analysis.interpreters`; the protocols `seqfile.interpreters.Plugin` and `synth.Decoding`; `gradient_points`; `RotationRecord.hint` (2.2 to 2.6). |
| R16 | Done: the `Session` of section 7.8 of the plan (soft delays, the field of view), given to `load` and `synth.decode`; the plugin protocol version 1 and `decode(data, session)` (P22); `SettingError`; the decoding's stored and actual block durations; `SoftDelayRecord` and `FovRecord`; the records of `cpp-siemens` (2.3, 2.4, 2.6 to 2.8). |
| R16 | Done: the record's new entries D2.20 (the order of the field of view), D2.21 (a soft delay value), D2.22 (`NOSLC` against `NOSCL`), and D6.3 and D6.4 of `cpp-siemens`; D4.6 and D4.7 say what a session does in an older file. |
