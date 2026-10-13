# Findings for pulseq-checks

This document is for the maintainers of pulseq-checks. It describes what
pulseq-analysis gives pulseq-checks so that pulseq-checks can find the
discrepancies that `docs/discrepancies.md` records. It describes the code of
pulseq-analysis at commit
[`6fa807d`](https://github.com/mdtisdall/pulseq-analysis/tree/6fa807d) of
`main`, with the tasks that section 7 lists as done since then (the `spec`
part of R9). Each link names that commit, so a shared copy stays exact. What
pulseq-checks does with it is pulseq-checks' own plan: this project writes
nothing in pulseq-checks' repository, and it does not read its code.

The plan behind it is
[`docs/plans/parser-redesign.md`](https://github.com/mdtisdall/pulseq-analysis/blob/6fa807d/docs/plans/parser-redesign.md)
("the plan"), task C1 (section 7.5). "Dnn" is an entry of
[`docs/discrepancies.md`](https://github.com/mdtisdall/pulseq-analysis/blob/6fa807d/docs/discrepancies.md)
("the record"). "Pnn" and "Qnn" are decisions of the plan's sections 2 and 3.
"The C++ reader" is `ExternalSequence` of pulseq/pulseq at `c7469123`, the
reader of the scanner's interpreter on Siemens systems. Every module name below
is under `pulseq_analysis` unless it says otherwise.

Contents:

1. [Why the findings move](#1-why-the-findings-move)
2. [The contract: the public readings](#2-the-contract-the-public-readings)
3. [The five mechanisms](#3-the-five-mechanisms)
4. [Each entry of the record](#4-each-entry-of-the-record)
5. [Categories, and the choices left to pulseq-checks](#5-categories-and-the-choices-left-to-pulseq-checks)
6. [The test oracles of the flake](#6-the-test-oracles-of-the-flake)
7. [What is still to come](#7-what-is-still-to-come)

## 1. Why the findings move

pulseq-analysis turns a Pulseq file into waveforms, and it measures them. Since
P17 (the user, 2026-10-12) it does not judge whether a file is valid. It reads a
file through one of two **interpreters**, and each gives a reading or a
rejection with codes:

- **`spec`** (the default): as true as possible to the Pulseq specification
  (1.5.3 draft) and to the slide set that its section 2.6 cites for timing
  (`doc/pulseq_shapes_and_times.pdf`). It rejects a file where they say "must",
  with every violation. Where they are silent, it makes a documented choice, and
  rejects a file only where no current writer (MATLAB Pulseq, pypulseq) writes
  such a file.
- **`cpp-siemens`** (by name): the C++ reader itself, run in the process by the
  package pulseq-cpp-siemens (the extra `pulseq-analysis[cpp-siemens]`). It
  reads what the reader reads, misreadings included, and rejects what the reader
  rejects. It rejects each case of the reader's undefined behaviour with a
  `ub.*` code (section 5.3 of the plan).

Where the sources of the format read a file differently, that is a
**finding**, and findings are pulseq-checks'. pulseq-checks reads the file
through the public readings of section 2, as often as it needs, and owns the
catalogue of findings, their severity, the profiles, the exit codes and the
reports (section 7.5 of the plan).

**What pulseq-analysis no longer reports.**

- No `Finding` type, no catalogue, no `compare`, and no warnings about a file.
  The one warning, `synth.ScannerSettingWarning`, is about the package's
  measurement, not the file (section 2.6), and the decoding does not emit it.
- No strict reader. The former `seqfile.reader` and the interim interpreter
  `strict` are removed (R11). `spec` replaces them, with these changes to the
  former rule names (section 5.4 of the plan):

  | Former rule | Now |
  |---|---|
  | `version.unsupported` | `errors.NotSupported` in both interpreters (Q1); not a code |
  | `definitions.duplicate` | No rejection: the last definition wins (D12) |
  | `section.unknown` | No rejection: ignored, with a `model.Record` (D08) |
  | `section.delays` | No rejection: ignored, with a `model.Record` (D09) |
  | `blocks.order` | No rejection: file order (D20) |
  | `shape.rf-magnitude-negative` | No rejection: plays as written (D31) |
  | `shape.rf-phase-range` | No rejection: plays as written (D32) |
  | `shape.rf-time-grid` | No rejection: cells or points (D35) |
  | `shape.rf-time-end` | No rejection: points (D36) |
  | `syntax.line` | Changed: only a data line before the first section; rows after a blank or `#` line are read (D06) |
  | `section.duplicate` | Changed: any section that appears twice, and two `extension` sections with one `STRING_ID` (D10, the user, 2026-10-13) |
  | `syntax.integer` | Changed: `+30` reads as 30 (D14) |

  Every other former rule name is a code of `spec` with the same condition, so
  pulseq-checks keeps its names (section 7.4 of the plan). The "specification"
  profile of section 7.5 of the plan is an error when `spec` rejects the file:
  it gives back the strict parser from `spec`.

## 2. The contract: the public readings

These readings are public, and kept stable for pulseq-checks (section 7.3 of
the plan). A change to any of them is a change of the contract: it is noted in
`CHANGELOG.md` and in this document, in the same pull request. The
[`docs/usage.md`](https://github.com/mdtisdall/pulseq-analysis/blob/6fa807d/docs/usage.md)
sections "The interpreters", "A pypulseq sequence in memory" and "The 'as
written' reading" have every field; this section is the index for
pulseq-checks.

| Entry point | Module | Returns |
|---|---|---|
| `seqfile.read_as_written(path)` | `seqfile.as_written` | `AsWritten` (2.1) |
| `seqfile.read_seqfile(path, interpreter="spec")` | `seqfile.reading` | `SequenceData` (2.2), or raises `SeqFileError` or `NotSupported` (2.5) |
| `seqfile.read_pypulseq(seq, interpreter="spec")` | `seqfile.from_pypulseq` | the `SequenceData` of the file that `seq.write(path)` gives, with `origin` `"pypulseq"` |
| `synth.decode(data)` | `synth.decoding` | `SpecDecoding` or `CppSiemensDecoding` (2.3, 2.4) |

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
(D06, D07, D10). The columns have the names of `SequenceData` and the units of
the file (µs, and ns for the ADC dwell time). The columns of `[RF]`,
`[GRADIENTS]` and `[ADC]` are those of 1.4 below version 1.5.0, else those of
1.5.

### 2.2 The model of each interpreter

`seqfile.read_seqfile(path, interpreter="spec") -> SequenceData` (module
`seqfile.model`). `interpreter` is a name (`"spec"`, `"cpp-siemens"`) or an
object of `seqfile.interpreters`:

- `Spec()`: no setting. `Spec(rotation="apply")` is a `TypeError`.
- `CppSiemens(oversampling="center", rotation="reader")`: `oversampling` is one
  of `OVERSAMPLING` (`"center"`, `"edge"`, `"preserve"`), the reader's
  sampling mode of an oversampled gradient (D43); `rotation` is one of
  `ROTATION` (`"reader"`, `"apply"`), what the decoding does with each block's
  rotation (D49). `str` gives the name with the settings that are not the
  default, for example `cpp-siemens(rotation='apply')`.

`interpreters.interpreter(value)` gives the object of a name,
`interpreters.INTERPRETERS` maps each name to its class, and
`interpreters.Interpreter` is `CppSiemens | Spec`.

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
`seqfile.cpp_siemens` lists how): a block's `id` is its position in play order
from 1 (the reader keeps no block ID); values are the reader's float32 values,
converted to float64 (P6, D18); a 1.4 RF event has `center` NaN (D38); `use` is
any character (D17); `[GRADIENTS]` and `[TRAP]` are one library (D19); `first`
and `last` of a 1.4 gradient with a time shape are the reader's sentinel
`FLOAT_UNDEFINED`, about 1.18e-38 (D39, D40); the definitions are in the order
of their keys, each with its last value (D12); and `Signature.matches` is the
reader's own MD5 check (D53).

### 2.3 The decoding of `spec`

`synth.decode(data)` of a `spec` model gives `synth.SpecDecoding`
(`interpreter`, and `rf`, `gradients`, `adc`: the events of the model by file
ID; `blocks`, the block table of the model, and `block_durations` in s, in
play order from 0). The events are in module `synth.events`:

- `RfEvent`: `id`, `amplitude`, `mag_id`, `phase_id`, `time_id`, `magnitude`,
  `phase`, `t`, `dwell` (None for a pulse of points, D35, D36), `shape_dur`,
  `center`, `delay`, the ppm and offset fields, `use`; `signal(times)` gives
  the complex signal at any times.
- `Trapezoid` and `ArbitraryGradient` (together `GradEvent`): `waveform`, `tt`,
  `shape_dur`, `first`, `last` and the fields of the row.
- `AdcEvent`: the fields of the row, and `phase_modulation` in rad, one value
  for each sample (D44), or None.

The decoder follows the specification and the slides (`docs/usage.md`, "The
decoder of `spec`"). `model.rf_time_step(times)` tells a pulse of cells from a
pulse of points. As `CppSiemensDecoding` (2.4), `SpecDecoding` has:

- `block_count`.
- `gradients_at(block_index, time_us, rotated=None)`: the gradients in Hz/m,
  an array (n, 3), at times in µs from the start of each block. Each event is
  the straight lines between its points (`seq_utils.gradient_offsets`), 0
  before its delay and after its end, and every value is 0 outside the block.
  `rotated` None or True turns each block with a rotation by its quaternion,
  from 1.5.1 (`synth.decoding.rotate`, the active rotation `R(q) v` with q0
  the scalar part, in float64); `False` gives the logical gradients.
- `rotations()`: the play indices of the blocks whose extension list has a
  ROTATIONS object, and their quaternions (n, 4), divided by their norm (D49).
  Both are empty for a file older than 1.5.1, where ROTATIONS is an unknown
  extension (P20, rule 2).
- `rotation_record`: a `synth.RotationRecord` (2.6) with the setting
  `"apply"`; it never has a warning, since `spec` applies the file's content.

On each fixture with rotations from 1.5.1, its blocks and quaternions are
those of `cpp-siemens`, and its rotated gradients are those of
`CppSiemens(rotation="apply")` to float32 precision and those of MATLAB's
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

`synth.decode(data)` of a `cpp-siemens` model gives
`synth.CppSiemensDecoding`, a view of that reading. Blocks are in play order
from 0:

- `block_count`; `block(index)` and `blocks()`: `GetBlock` and `decodeBlock`,
  the fields of the C++ oracle's `--dump` (section 6), in the reader's units
  (µs, Hz, Hz/m, rad), after the resampling and the clamps.
- `gradients_at(block_index, time_us, rotated=None)`:
  `SeqBlock::gradientsAt` in Hz/m, an array (n, 3), 0 before and after the
  block. `rotated=None` follows the setting `rotation`; `False` gives the
  reader's own values; `True` turns each block with a rotation by its
  quaternion, with the reader's own `rotate_vec3_by_quat`.
- `rotations()`: the play indices of the blocks to which `GetBlock` attaches a
  rotation (the first of the list, D48), and their quaternions (n, 4), q0, qx,
  qy, qz, as the reader normalized them (D49). The same in each setting.
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
- `ImportError` for `cpp-siemens` without the extra; `OSError` when the file
  cannot be read.

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

**The codes of `cpp-siemens`** are the keys of `seqfile.cpp_siemens.CODES`
(29 codes). Each maps to its entry of the record and what the reader rejects.
The reader stops at its first error, so a rejection has one reason, with the
reader's own message; `line` is set where the message quotes a row. The `ub.*`
codes are also `pulseq_cpp_siemens.CODES`.

| Code | Entry | The C++ reader rejects |
|---|---|---|
| `version.missing`, `version.invalid` | D02 | no `[VERSION]`; a line of it that does not decode, or an unknown key |
| `definitions.raster-missing`, `definitions.raster-invalid` | D11 | a raster that is not defined; one that the reader does not read as a number |
| `definitions.skipped` | D56 | the rasters, because the reader skipped `[DEFINITIONS]` after a section that ran to the end of the file |
| `extension.required-unknown` | D47 | an unknown required extension |
| `section.extensions-last` | D46 | `[EXTENSIONS]` as the last section |
| `blocks.missing` | — | no `[BLOCKS]` section |
| `syntax.row` | D14, D15 | a row that does not decode with the reader's `sscanf` format |
| `syntax.comment-row` | D06 | a `#` line inside a table |
| `syntax.shape` | D14 | a line of `[SHAPES]` that does not decode |
| `ref.unresolved` | D21 | a block that names an event that the reader did not read |
| `rotation.norm` | D49 | a quaternion whose norm is more than 1e-3 from 1 |
| `gradient.raster` | D28 | an arbitrary gradient in a file whose gradient raster is not 10 µs |
| `shape.decompression` | D29 | a compression that the reader cannot decode |
| `shape.ext-trap-lengths` | — | an extended trapezoid whose time shape and waveform differ in length |
| `cpp.exception`, `cpp.rejected` | — | a C++ exception; any other rejection |
| `ub.shape-missing` | D21 (D05, D07) | a block uses a shape that the reader did not read |
| `ub.rf-time-id-minus-1` | D22 | an RF event with time ID -1 |
| `ub.extension-cycle` | D23 | a cycle in an extension list (no end) |
| `ub.shape-decompression` | D29 | a shape that decompresses past its buffer, or reads one value past it |
| `ub.shape-empty` | D33 | a shape with no sample |
| `ub.rf-shape-lengths` | D34 | an RF phase shorter than its magnitude |
| `ub.rf-time-overrun`, `ub.rf-time-range` | D36 | the RF resampling reads past the time shape; a last time that does not fit an `int` |
| `ub.gradient-time-range` | D29 | an extended trapezoid time that does not fit a `long` |
| `ub.gradient-one-point` | — | `gradientsAt` reads past an extended trapezoid of one point |
| `ub.gradient-shape-0` | — | a `[GRADIENTS]` row of shape 0, which `load` leaves unset |

### 2.6 What a result records

Rule 4 of section 7.8 of the plan (P20): every result records what was applied
of the scanner-side settings. Rule 7: these records are part of the contract.

- **`SequenceData.records`**: a tuple of `model.Record` (`kind`, `subject`,
  `reason`, `line`), in file order, for each thing that `spec` ignored. `kind`
  is `"extension"`, `"section"` or `"label"`. `reason` is `"unknown"` (D08,
  D45, D50, and `NOSCL`, which the specification spells `NOSLC`), `"version"`
  (the file is older than the revision that introduced it: an extension, or a
  flag of 1.4.1) or `"removed"` (`[DELAYS]`, D09). A label's row stays in its
  table. `cpp-siemens` gives `()` today (section 7).
- **`SequenceData.skipped_extensions`**: the extensions that the interpreter
  does not know. For `spec` it follows the version gate: `DELAYS` from 1.5.0,
  `ROTATIONS` and `RF_SHIMS` from 1.5.1 (section 7.8 of the plan, rule 2); the
  definition `RequiredExtensions` is read from 1.5.1 too. For `cpp-siemens` it is the extensions that the reader
  ignores, in any version.
- **`synth.RotationRecord`** (module `synth.scanner`), from
  `CppSiemensDecoding.rotation_record` and `SpecDecoding.rotation_record`:
  `setting` (`"reader"` or `"apply"`; always `"apply"` for `spec`),
  `blocks` (with a rotation), `not_identity` (whose quaternion has a vector part
  that is not 0), `rotated` (`blocks` with `"apply"`, else 0); `unapplied`; `str`
  (for example "rotation: apply, 5 block(s) rotated"); and `warning()`, a
  `synth.ScannerSettingWarning` (a `UserWarning`) when the default leaves a
  rotation unapplied, else None. The decoding never emits it, so pulseq-checks
  is not warned about the reader's own output.

## 3. The five mechanisms

pulseq-checks finds each discrepancy of the record with one of five mechanisms
(section 7.4 of the plan). Each entry of the record is titled by a condition in
a file, so each maps to one or more of them. Section 4 gives the mapping.

| | Mechanism | What it finds | Readings it uses |
|---|---|---|---|
| M1 | A diff of the "as written" reading against the `cpp-siemens` reading and decoding | The reader changes, drops or misreads a value | `AsWritten`; `SequenceData` of `cpp-siemens` and `reading.libraries`; `CppSiemensDecoding` |
| M2 | A condition on the "as written" reading | The reader plays something that a diff of values cannot show | `AsWritten` (and the version) |
| M3 | `spec`'s violations on the same file | A "must" broken, which the reader plays as written | `SeqFileError.violations` of `spec`, `spec.RULES` |
| M4 | A comparison of the two interpreters | One rejects and the other reads, or their waveforms differ | Both results: model, decoding, or rejection codes |
| M5 | A catalogue of MATLAB Pulseq and pypulseq | The writers' readers differ | The record; the MATLAB oracle (section 6) |

A file that `cpp-siemens` rejects still gets findings: pulseq-checks reads it
as written and through `spec`. The two readings must agree on which field is
which; the column names of `AsWritten` are those of `SequenceData`, but the
`cpp-siemens` model numbers blocks in play order and merges `[GRADIENTS]` and
`[TRAP]` (2.2), so M1 aligns blocks by position and events by file ID.

## 4. Each entry of the record

"Mechanism" is from section 7.4 of the plan; "—" means that section 7.4 lists
none for the entry (section 5 says which choice that leaves). M4 is marked
where the two interpreters differ in the record's summary. Fixtures are in
`tests/seqfiles/` unless the path says otherwise; "none" means that the record
gives a run in the text of the entry, not a fixture. Codes are today's: "reads"
means no code.

| Entry | Condition | Mechanism | Fixture | `cpp-siemens` | `spec` |
|---|---|---|---|---|---|
| D01a–c | `[RF]` 12, `[GRADIENTS]` 7, `[ADC]` 9 fields | — (agree) | none (the specification's examples) | `syntax.row` for a short row | `syntax.columns` |
| D02 | No `[VERSION]` | — (both reject) | `bad_version_missing.seq` | `version.missing` | `version.missing` |
| D03 | Version outside 1.4.0–1.5.x | — (scope) | `bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq` | `NotSupported` | `NotSupported` |
| D04 | `[VERSION]` value `5.0` | M2, M4 | `bad_version_invalid.seq` | reads `5.0` as 5 | `version.invalid` |
| D05 | Unusual section order; `[VERSION]` last | M1, M4 | `undefined/version_last.seq` | `[VERSION]` last: no shape read; `definitions.skipped` or `ub.shape-missing` | reads |
| D06 | Blank or `#` line inside a section | M1 (blank line), M4 | `bad_syntax_line.seq`, `bad_syntax_line_after_comment.seq`, `valid_comment_in_shape.seq`, `valid_comments_between_sections.seq` | drops the rows after a blank line; `syntax.comment-row` | reads them; `syntax.line` before the first section |
| D07 | No blank line after a shape | M1, M4 | `bad_syntax_shape_no_blank_line.seq`, `bad_syntax_shape.seq`, `bad_syntax_shape_end.seq` | later shapes lost, then `ub.shape-missing` | `syntax.shape` |
| D08 | Unknown section | M2 | `bad_section_unknown.seq` | reads (ignores) | reads (ignores); `Record("section", …, "unknown")` |
| D09 | `[DELAYS]` from 1.4.0 | M2 | `bad_section_delays.seq` | reads (ignores) | reads (ignores); `Record("section", …, "removed")` |
| D10 | A section twice | M1, M4 | `bad_section_duplicate.seq`, `bad_section_duplicate_extension.seq`, `bad_section_duplicate_signature.seq` | reads the last | `section.duplicate` |
| D56 | Last section with no blank line after it | M1, M4 | `valid_last_section_no_blank.seq` | `definitions.skipped` | reads |
| D11 | Missing or invalid raster | M2, M4 | `bad_definitions_raster_missing.seq`, `bad_definitions_raster_invalid.seq`, `valid_arbitrary_gradient_4us_raster.seq` | `definitions.raster-missing`, `definitions.raster-invalid`; reads some values | `definitions.raster-missing`, `definitions.raster-invalid`, `definitions.raster-commensurate` |
| D12 | A definition twice | M1 | `bad_definitions_duplicate.seq` | the last | the last |
| D13 | A definition or hash that reads as a number | M2 | none | text | text |
| D14 | Number syntax, columns, encoding | M1 (fraction misread, short rows), M3 (NaN), M4 | `bad_syntax_columns.seq`, `bad_syntax_encoding.seq`, `bad_syntax_integer.seq`, `bad_syntax_integer_plus.seq`, `bad_syntax_negative.seq`, `bad_syntax_number.seq` | `syntax.row` (`30.5`, a short row); reads `+30`, a long row, NaN, negatives | `syntax.columns`, `syntax.integer`, `syntax.number`, `syntax.negative`, `syntax.encoding` |
| D15 | ADC dwell `2500.0` | M4 | none | `syntax.row` | reads; `raster.adc-dwell` off the raster |
| D16 | Soft delay offset `-100.5`; long hint | M1, M4 | `valid_soft_delay_fraction.seq` | misreads (-100 µs, factor 0.5); cuts the hint to 31 characters | reads -100.5 µs and the whole hint |
| D17 | RF `use` letter not in the list | M3, M4 | `bad_syntax_use.seq` | reads any character | `syntax.use` |
| D18 | Value beyond float32 | M1, M4 | none | float32 values (P6) | float64 |
| D19 | IDs not positive or not unique | M1, M3, M4 | `bad_id_positive.seq`, `bad_id_unique.seq`, `bad_id_unique_block.seq`, `bad_id_gradient_unique.seq` | the last wins; `[TRAP]` replaces `[GRADIENTS]` | `id.positive`, `id.unique`, `id.gradient-unique` |
| D20 | Block IDs out of order | M2, M5 | `bad_blocks_order.seq` | file order | file order |
| D21 | A reference that does not resolve | M1 (extension lists), M4 | `bad_ref_block_rf.seq`, `bad_ref_shape.seq`, `bad_ref_time_shape.seq`, `bad_ref_extension_entry.seq`, `bad_ref_extension_object.seq`, `bad_ref_extension_type.seq` | `ref.unresolved`, `ub.shape-missing`; reads the extension cases | `ref.unresolved` |
| D22 | Time ID -1 for RF, or in 1.4 | M2 (1.4 gradient), M4 | `undefined/rf_time_id_minus_1.seq`, `bad_ref_time_id_minus_1_in_1_4.seq` | `ub.rf-time-id-minus-1`; reads a 1.4 gradient | `ref.unresolved` |
| D23 | Cycle in an extension list | — (both reject) | `bad_ref_extension_cycle.seq` | `ub.extension-cycle` | `ref.unresolved` |
| D24 | No block | M3, M4 | `bad_blocks_empty.seq` | reads | `blocks.empty` |
| D25 | Event longer than its block | M3, M4 | `bad_block_event_too_long_rf.seq`, `bad_block_event_too_long_adc.seq`, `bad_block_event_too_long_trigger.seq` | reads | `block.event-too-long` |
| D26 | Times off a raster | M3, M4 | `bad_raster_adc_dwell.seq`, `bad_raster_adc_delay.seq`, `bad_raster_gradient_delay.seq`, `bad_raster_gradient_end.seq`, `bad_raster_gradient_flat.seq`, `bad_raster_gradient_ramp.seq`, `bad_raster_gradient_vertex.seq`, `bad_raster_rf_delay.seq` | reads | `raster.*` |
| D27 | Gradient above 0 at an end | M3, M4 | `bad_gradient_nonzero_start_delay.seq`, `bad_gradient_nonzero_end_align.seq` | reads | `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` |
| D28 | Arbitrary gradient off 10 µs | M4 | `valid_arbitrary_gradient_5us_raster.seq`, `valid_arbitrary_gradient_4us_raster.seq` | `gradient.raster` | reads 5 µs; `definitions.raster-commensurate` for 4 µs |
| D29 | Shape length | M1 (shorter), M4 | `bad_shape_length.seq`, `undefined/shape_decompress_longer.seq`, `packages/pulseq-cpp-siemens/tests/fixtures/shape_decompress_count_missing.seq` | `ub.shape-decompression` (longer); reads a shorter one | `shape.length` |
| D30 | Shape outside [-1, 1] | M1, M4 | `bad_shape_range.seq` | clamps | `shape.range` |
| D31 | RF magnitude below 0 | M1, M4 | `bad_shape_rf_magnitude_negative.seq` | clamps to 0 | plays as written |
| D32 | RF phase outside [0, 1) | M1, M4 | `bad_shape_rf_phase_range.seq` | clamps | plays as written |
| D33 | Empty shape | — (both reject) | `bad_shape_empty.seq` | `ub.shape-empty` | `shape.empty` |
| D34 | Shapes of one event, two lengths | M1 (longer phase), M4 | `bad_shape_event_length.seq` | `ub.rf-shape-lengths` (shorter phase); reads a longer one | `shape.event-length` |
| D35 | Regular RF time shape | M2, M4 | `valid_rf_time_shapes.seq`, `bad_shape_rf_time_grid.seq` | as C++ | cells when the times are `(i + 0.5) d`, else points |
| D36 | Other RF time shape | M2 (1), M4 | `bad_shape_rf_time_end.seq`, `bad_shape_time_order.seq` | as C++; `ub.rf-time-overrun` | points; `shape.time-order` |
| D37 | RF time shape that ends inside its last dwell | M2, M4 | none | dwell × samples | `N d`, or the last point |
| D38 | 1.4 RF event, no `center` | M2 | `oracle/koma_v1.4_fid.seq` | `center` NaN | `center` NaN |
| D39 | 1.4 gradient on the default raster | M2, M4 | `bad_layer1_gradient_ends.seq`, `oracle/koma_v1.4_gr-uniformly-shaped.seq` | reads; ends `FLOAT_UNDEFINED` | `layer1.gradient-ends` |
| D40 | 1.4 time-shaped gradient, no `first` | M2 | `valid_1_4_1.seq` | the first sample | the first sample; `layer1.gradient-ends` when the time shape starts after 0 |
| D41 | Time-ID-0 gradient between its samples | M5 | `valid_1_5_1.seq` | straight lines | straight lines |
| D42 | Gap between gradient events | M2 | none | one block at a time | 0 in a block; across blocks: R14 |
| D43 | Oversampled gradient | M2, M4 | `oracle/koma_v1.5_spiral.seq`, `valid_1_5_0.seq`, `bad_shape_oversampled_length.seq` | the centre samples (`oversampling="center"`) | all the samples; `shape.oversampled-length` |
| D44 | ADC phase modulation shape | M5, M4 | `valid_1_5_1.seq`, `bad_shape_adc_phase_length.seq` | rad | rad, one per sample; `shape.event-length` |
| D45 | Unknown extension, not required | M2, M5 | `oracle/koma_v1.5_unknown_ext.seq`, `valid_1_5_0_extensions_of_1_5_1.seq` | ignores (`skipped_extensions`) | ignores; `Record("extension", …)` |
| D46 | `[EXTENSIONS]` last | M4 | `oracle/koma_v1.5_unknown_ext.seq` | `section.extensions-last` | reads |
| D47 | Unknown required extension | — (both reject) | `bad_extension_required_unknown.seq` | `extension.required-unknown` | `extension.required-unknown` |
| D48 | Two ROTATIONS or RF_SHIMS in a block | M1, M4 | `bad_extension_per_block.seq` | the first | `extension.per-block` |
| D49 | Played rotation; quaternion norm | M2, M4 | `oracle/pulseq_make_radial.seq`, `oracle/koma_v1.5_rotation_radial_tiny.seq` | normalizes; `rotation.norm`; rotates with `rotation="apply"` | normalizes and rotates from 1.5.1; `rotation.zero` |
| D50 | Unknown label name | M1 | `valid_label_unknown.seq` | leaves the label out | reads; `Record("label", …, "unknown")` |
| D51 | Equal events, different IDs | M5 | `oracle/pypulseq_simple_mprage150.seq` | keeps both | keeps both |
| D52 | No values of a target in the file | — (not about the file) | `valid_1_5_1.seq` | none | none |
| D53 | Signature: CRLF, mismatch | M1, M4 | `valid_crlf.seq`, `valid_signature_mismatch.seq` | the reader's MD5 check (`Signature.matches`) | the specification's rule (`AsWritten.signed_bytes()`) |
| D54 | `[SIGNATURE]` without `Type` or `Hash` | M3, M4 | `bad_signature_invalid.seq` | reads | `signature.invalid` |
| D55 | `STRING_ID` that is a word | — (agree) | `valid_1_5_1.seq` | text | text |

The fixtures `ub.gradient-one-point` and `ub.gradient-shape-0` have no entry of
the record: `packages/pulseq-cpp-siemens/tests/fixtures/gradient_one_point.seq`
and `gradient_shape_0.seq`. Each fixture's verdict under the C++ reader is in
`packages/pulseq-cpp-siemens/tests/expected_digests.json`.

## 5. Categories, and the choices left to pulseq-checks

Section 7.4 of the plan proposes five categories. They describe a finding;
pulseq-checks grades them:

| Category | A finding where |
|---|---|
| `interpreters-differ` | `spec` and `cpp-siemens` differ: one rejects, or their waveforms differ (M4) |
| `spec-departure` | the file breaks a rule of the specification that the reader plays as written (M3) |
| `cpp-changes-value` | the reader changes, drops or misreads a value (M1) |
| `cpp-default` | the reader uses a default that the scanner's interpreter can set: D39 (`FLOAT_UNDEFINED`), D43 (oversampling) |
| `writers-differ` | MATLAB Pulseq and pypulseq read the file differently (M5) |

pulseq-analysis does not change when pulseq-checks makes a policy stricter.
These choices are pulseq-checks':

- **The float32 tolerance of D18.** `cpp-siemens` holds the reader's float32
  values (P6); a diff against the "as written" float64 values needs a tolerance
  for a change to be "noticeable". The record's runs compare with a relative
  tolerance of about 1e-6.
- **Severity, profiles and exit codes** (section 7.5 of the plan), for example
  "scanner" (an error when `cpp-siemens` rejects), "specification" (an error
  when `spec` rejects) and "portable" (an error for each `interpreters-differ`
  finding).
- **The entries that section 7.4 maps to no mechanism**: D02, D23, D33 and D47
  (both interpreters reject; MATLAB Pulseq or pypulseq may not), D01a–c and D55
  (all agree), D03 (scope) and D52 (not about the file). Whether they get a
  `writers-differ` finding, or none, is pulseq-checks' choice.
- **The chosen rules of `spec`.** A rule whose `spec.Rule.choice` is not None
  rests on the package's choice, not on the specification. pulseq-checks
  decides whether a rejection by such a rule is reported as a departure from the
  specification.
- **The records** (2.6): whether an ignored section, extension or label
  (D08, D09, D45, D50, `NOSCL`) is a finding, and with which severity.
- **D49**: `spec` divides a quaternion by its norm with no rejection; section
  6 of the plan says that a norm more than 1e-3 from 1 gets a finding. The norm
  as written is in `AsWritten`; pulseq-checks sets the threshold.
- **A signature that does not match** (`Signature.matches` False) is not a
  rejection in either interpreter.
- **`cpp.exception` and `cpp.rejected`**: codes for a rejection that no other
  code names; pulseq-checks decides how to report them.
- **D42 across blocks** and **D25 after the block end**: what the reader plays
  there is not visible in one decoded block (section 13 of the plan).

## 6. The test oracles of the flake

The flake of this repository (`flake.nix`) builds three programs from
pulseq/pulseq at `c7469123c2f381f065986e6cc3a7d09730ed16ef`. Each is an output
`packages.<system>.<name>`, so a consumer can run it from a flake reference,
for example
`nix run github:mdtisdall/pulseq-analysis/6fa807d#pulseq-cpp-oracle -- --dump FILE`.

| Program | What it gives | Documentation |
|---|---|---|
| `pulseq-cpp-oracle` | The C++ reader with a small driver, built with `-fsigned-char -ffp-contract=off` (the `char` and arithmetic of the scanner's x86_64 build on each system). `FILE`: the verdict as the exit status (0 reads, 1 rejects, 70 crashes). `--dump FILE`: what the reader holds after `load` and `decodeBlock`, as JSON. `--sample FILE`: `SeqBlock::gradientsAt` for lines `block_index time_us` on stdin. `--oversampling=center\|edge\|preserve` sets the reader's mode. | [`tests/cpp_oracle/README.md`](https://github.com/mdtisdall/pulseq-analysis/blob/6fa807d/tests/cpp_oracle/README.md) |
| `pulseq-cpp-oracle-sanitized` | The same reader and driver with AddressSanitizer, UndefinedBehaviorSanitizer and the standard library's assertions (clang of LLVM 22). Exit status 3: the reader has undefined behaviour on the file, whatever an ordinary build does. | the same README, "The sanitized build" |
| `pulseq-matlab-oracle OUT_DIR FILE.seq...` | MATLAB Pulseq run under GNU Octave: `read`, `getBlock` and `waveforms_and_times(true)` of each file, as JSON. About 2.5 GiB of closure; only in the default devShell. | [`tests/matlab_oracle/README.md`](https://github.com/mdtisdall/pulseq-analysis/blob/6fa807d/tests/matlab_oracle/README.md) |

`cpp-siemens` gives the same values in the process: its `decode_block` has the
fields of `--dump`, and its `gradients_at` those of `--sample`, bit for bit on
each fixture (`packages/pulseq-cpp-siemens/tests/expected_digests.json`).
pulseq-checks needs the C++ oracle only to check that, or for a file that it
must read in another process. The helpers of `tests/oracles/` are this
project's test code, not part of the contract.

## 7. What is still to come

These parts of the contract are planned, not in the code at `6fa807d`. Each
task updates this document and `CHANGELOG.md` when it changes the contract,
and marks its row done.

| Task | What it adds |
|---|---|
| R9, the `spec` part | Done: `SpecDecoding.gradients_at`, `rotations()` and `rotation_record` (2.3). |
| R14 | `analyses.load` on an interpreter's output (`interpreter=`): for `cpp-siemens` the reader's decoded events and `gradientsAt`, for `spec` its decoder. `load` stops refusing the rotation extension (today `synth.extensions.refuse_rotations`), keeps the decoding's `rotation_record` in its result and emits `RotationRecord.warning()`. The waveform across blocks (D42). Today `load` reads with pypulseq. |
| R16 | The `Session` of section 7.8 of the plan (soft delays, the field of view), given to `load` and the timeline; `SettingError` (a `ValueError`) for a setting that addresses something the file does not have; the decoding's stored and actual block durations; the records of the mechanisms left at the default, in `SequenceData.records` for both interpreters (`cpp-siemens` gives no record today). |
| R16 | The record's new entries: D57, the flag `NOSLC` (the specification) against `NOSCL` (the C++ reader, MATLAB, pypulseq); D58, an extension used in a file older than the revision that introduced it. The code already records both under `spec` (`Record` reasons `"unknown"` and `"version"`), but the record has no entry for them yet. |

The order (section 10 of the plan): R14 needs R9, which is done; R16 needs
R14.
