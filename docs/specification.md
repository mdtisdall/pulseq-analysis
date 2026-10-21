# What `spec` does, and why

`spec` is the built-in interpreter of pulseq-analysis, and its default
(`read_seqfile(path)`, `seqfile/spec.py`). It reads a Pulseq file as the Pulseq
specification describes it. This document gives its rule (section 1), each
place where the rule does not decide and what `spec` does there (section 2),
with the reason, and the codes of its rejections (section 3).

The specification is `doc/specification.tex` of
[pulseq/pulseq](https://github.com/pulseq/pulseq) at `c7469123`, "Version 1.5.3
(DRAFT)", cited as `spec:N` (its line N). Its section 2.6 cites the slide set
`doc/pulseq_shapes_and_times.pdf` of the same commit for timing, cited as
"slide N". The IDs (D1.1, D3.7, …) name decisions of `spec`. They are the IDs
of [`docs/discrepancies.md`](discrepancies.md), whose entry for each ID gives
what the specification and the C++ reader do, with citations, and the fixtures.
Its groups are D1 (the specification is unclear), D2 (silent: `spec` reads the
file), D3 (silent: `spec` rejects by choice) and D4 (versions); sections 2.1 to
2.5 below correspond to the groups D4, D1, D2 and D3. A "—" in an ID column
means that the specification states the rule, so the decision has no entry.
P1 to P22 and Q1 to Q6 are the decisions of
`docs/plans/parser-redesign.md` ("the plan"). Fixtures named without a folder
are in `tests/seqfiles/`. The other interpreter, `cpp-siemens`, has its own
record in the plugin pulseq-cpp-siemens
([`packages/pulseq-cpp-siemens/docs/specification.md`](../packages/pulseq-cpp-siemens/docs/specification.md)).

## 1. The rule

`spec` reads each field as the specification types it, and the timing as the
slide set gives it. Where the specification or the slide set says that a file
"must" (or "need to", "MUST") be otherwise, `spec` gives no waveform: it
rejects the file with every violation, each with a code (Q4).

Why: `spec` shows what the file means by its format, independent of any one
reader (section 1 of the plan). The slide set is normative for timing, because
the specification's section 2.6 refers to it for timing (the user,
2026-10-12). Where `cpp-siemens`, which plays what the scanner plays, reads the
file otherwise, pulseq-checks reports a finding (P17).

## 2. Where the rule does not decide

### 2.1 The version gate

**D4.1: a version before 1.4.0 or from 1.6.0.** `spec` raises `NotSupported`,
which says nothing about the file, and also for a binary file or a folder
(`bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq`). The
check is that of `read_seqfile`, before the interpreter reads the file, so
every interpreter has it, with one message for each case (the user,
2026-10-14). The version is that of the "as written" reading
(`AsWritten.version`), and a binary Pulseq file is one whose first 8 bytes are
`\x01pulseq\x02`. The specification has no rule for a version that a reader
does not know.

Why: the package reads 1.4.0 to 1.5.x only (Q1), so a version that it does not
know fails loudly, not wrongly.

### 2.2 Each version is its own format

`spec` reads a file of 1.4.x by the tables of that version, and reads each
mechanism of the format only from the revision that introduced it.

| ID | Condition | What `spec` does |
|---|---|---|
| D4.2 | a 1.4.x `[RF]`, `[GRADIENTS]` or `[ADC]` row | the 1.4 layout: 8, 5 and 6 fields, with no `center`, no `first` and `last`, no ppm offsets, no `use` and no ADC phase shape; `center` is absent and `use` is `u` |
| D4.3 | time ID -1 of a gradient in a 1.4 file | `ref.unresolved`: -1 is "Updated in v1.5.0" (slide 4) |
| D4.6 | `extension DELAYS` before 1.5.0; ROTATIONS or RF_SHIMS before 1.5.1; a rotation in a file before 1.5.1; `RequiredExtensions` before 1.5.1 | the extension is one that `spec` does not know: ignored, with a record (reason `"version"`; `valid_1_5_0_extensions_of_1_5_1.seq`); a rotation is not applied; a session's soft delay value is a `SettingError`; `RequiredExtensions` is not read |
| D4.7 | a flag of 1.4.1 (`PMC`, `NOROT`, `NOPOS`, `NOSLC`, `ONCE`, spec:526) in an older file | kept, with a record (reason `"version"`); `NOROT` and `NOSLC` do not change the field of view of a session |

Why: the specification gives the revision of each mechanism (its table of
revisions, spec:109-120, and spec:526, spec:545, spec:567, spec:584), and a
reader of a version has only the mechanisms of that version (the user,
2026-10-12; rule 2 of P20).

### 2.3 Where the specification disagrees with itself

| ID | The disagreement | What `spec` follows |
|---|---|---|
| D1.1 | a reader "may either refuse execution or assume version 1.0.0", and "It is recommended to reject" (spec:201) | the recommendation: `version.missing` |
| D1.2 | the prose counts 7, 4 and 6 numbers (spec:334, spec:375, spec:424); the tables and examples have 12, 7 and 9 fields | the tables and examples, as all three readers and MATLAB's files do; another count is `syntax.columns` |
| D1.3 | slide 6 puts the vertices of an extended trapezoid "all aligned on raster edges"; slide 4 calls it "not a requirement" of a time shape | slide 6: `raster.gradient-vertex`, a rejection of choice (2.5), since the makers of both writers refuse a vertex off the raster (`makeExtendedTrapezoid.m:84-85`, `make_extended_trapezoid.py:115-116`) |
| D1.4 | the table types `STRING_ID` as an integer (spec:493); the text and every example give a word | the text and the examples: `STRING_ID` is text, as all three readers read it |

Why: where the parts of the specification disagree, `spec` follows the part
that the readers and the writers' files agree with.

### 2.4 Where the specification is silent: the readings

Where the specification and the slide set are silent, `spec` reads the file as
section 6 of the plan chose (Q5).

| ID | Condition | What `spec` does | Why |
|---|---|---|---|
| D2.1 | sections in any order | reads them by name (`undefined/version_last.seq` is read) | the specification sets no order, except that the file "may end with" `[SIGNATURE]` (spec:213) |
| D2.2 | the last section with no blank line after it | reads it (`valid_last_section_no_blank.seq`) | the specification ends only a shape with a blank line (spec:602) |
| D2.3 | `[EXTENSIONS]` as the last section | read (`oracle/koma_v1.5_unknown_ext.seq`) | the specification sets no order of the sections |
| D2.4 | a section that the format does not have, or `[DELAYS]` | ignored, with a record | `[DELAYS]` was removed in 1.4.0 (spec:114), and "Current readers ignore this section" (spec:772); an unknown section is ignored as the C++ reader does |
| D2.5 | a blank or `#` line inside a section | skipped anywhere; inside a shape, a blank line ends the shape and a `#` line is skipped (`valid_comment_in_shape.seq`) | "Comments are specified by a line starting with a hash" (spec:171); the specification gives no rule that a blank line ends a table |
| D2.6 | a definition twice | the last | as all three readers do |
| D2.7 | a definition or a hash that reads as a number | the text; only the four rasters are numbers | `<value>` is "any" (spec:247) and the hash a "string" (spec:230); a double cannot hold the 32 digits of a hash |
| D2.8 | an RF magnitude below 0 | played as written: a signed amplitude | the specification allows [-1, 1] for an amplitude shape (spec:624) |
| D2.9 | an RF phase outside [0, 1) | played as written: 2π times the value, as MATLAB does | the specification gives no range for the phase |
| D2.10 | an RF time shape whose times are `(i + 0.5) d`, or one sample `t0` above 0 (`d = 2 t0`, D3.9) | cells of `d`: each sample held for one dwell, and the pulse lasts `N d` | slide 9 places the samples of a regular pulse at the centres of their dwell periods; every regular pulse of MATLAB Pulseq and pypulseq has this form (the user's choice). The split does not depend on how the shape is stored (spec:602) |
| D2.11 | any other RF time shape | points at its times, joined by straight lines of the complex signal; the pulse ends at its last time (`bad_shape_rf_time_end.seq`) | slide 9: a pulse "defined by vertices", which need not be on the raster (slide 4); the straight line of the complex signal is the C++ reader's stated intent (`cpp:2033`) and MATLAB's for RF power, bandwidth and simulation (the user's choice) |
| D2.12 | where a pulse with a time shape ends | `N d` for cells, the last time for points | slide 9 (N dwell periods from the start), and the last vertex |
| D2.13 | an arbitrary gradient between its samples (time ID 0) | straight lines between the cell centres, and to `first` and `last` at the edges | spec:290 puts the samples at the centres and is silent between them; slide 7 draws lines |
| D2.14 | a gap between gradient events | 0 where no gradient event plays; with `gradient.nonzero-start-delay` and `gradient.nonzero-end-align`, a gap inside a block lies between zeros; across blocks the measurements (`load`) draw MATLAB's ramps | the specification is silent between events, and the C++ reader gives no waveform between blocks |
| D2.15 | an ADC phase modulation shape | rad, one value for each ADC sample | the specification gives no unit (spec:443) and a "phase offset per sample" (spec:120) |
| D2.16 | a soft delay offset with a fraction; a long hint | the offset is a float in µs; the hint is the whole text (`valid_soft_delay_fraction.seq`) | the specification has no table of types for the row; MATLAB writes and reads a float, and the binary format stores a time in ps (spec:723) |
| D2.17 | an unknown extension that the file does not require | ignored, with a record | "The interpreter MUST detect unknown extensions and MAY chose to ignore them" (spec:460) |
| D2.18 | a rotation quaternion | divided by its norm | spec:567: "a normalized rotation quaternion" |
| D2.19 | a label that the specification does not list | kept as text, with a record; so is `NOSCL`, which the specification spells `NOSLC` (spec:520) | labels do not change the waveforms |
| D2.20 | a session's field of view and a block's rotation | R_fov R_block S g: the scaling of the logical axes, then the block's rotation, then the rotation of the field of view; not turned in a block with `NOROT`, not scaled in a block with `NOSLC` (`tests/session/scanner_session.seq`) | the specification gives no order; MATLAB Pulseq's `mr.TransformFOV` is the only written one (TransformFOV.m:58-60; the user, 2026-10-13) |
| D2.21 | a session's soft delay value | `value / factor + offset` on the block duration raster, rounded half away from 0; `SettingError` for an unknown hint, a file before 1.5.0, a hint with two numeric IDs, a block with an event or two soft delays, and a negative duration | spec:545-563; MATLAB's `applySoftDelay` (Sequence.m:2518-2587) is the only written rounding; the user, 2026-10-13 |
| D2.22 | the flag `NOSLC`, and `NOSCL` of the writers | `NOSLC` turns off the scaling from 1.4.1; `NOSCL` is an unknown label (D2.19), without effect | the specification's spelling (spec:520, spec:537; the user, 2026-10-13) |
| — | a trapezoid whose rise, flat and fall times are all 0 | read: an event of length 0, which plays 0 (`docs/implementation.md`, section 1.2) | 0 is a multiple of the raster (spec:290). `makeTrapezoid` and `make_trapezoid` never make one, but MATLAB Pulseq and pypulseq write it when the times are set on the event, and their timing checks pass it; the C++ reader, MATLAB Pulseq and pypulseq play 0 for it (the user, 2026-10-18) |
| — | an oversampled gradient (time ID -1) | all the samples, half a raster apart, the first and last at cell centres | spec:420 and slides 4 and 8: N − 1 extra points on the cell edges |
| — | a signature hash | `Signature.matches` by the rule of spec:223: the md5 of the bytes before `[SIGNATURE]`, without the `\n` right before it; a mismatch is not a rejection (`valid_crlf.seq`, `valid_signature_mismatch.seq`) | the specification says to strip that new line, and has no "must" to verify the hash |

### 2.5 Where the specification is silent: the rejections of choice

`spec` rejects a file where the specification is silent only where no current
writer (MATLAB Pulseq, pypulseq) writes such a file (the user, 2026-10-12). The
message of each such rejection says that the specification does not state the
rule, and why `spec` rejects the file (`Rule.choice` in `spec.RULES`). Runs of
2026-10-13 found three exceptions, which the user decided the same day: the
writers write NaN (D3.5) and negative times (D3.6) when a script passes them, and
`spec` keeps rejecting them because they give no waveform (the messages give
this reason); MATLAB Pulseq writes an RF time shape of one sample (D3.9), which
`spec` reads as one cell of twice its time when that time is above 0.

| ID | Code | Condition | Why |
|---|---|---|---|
| D3.1 | `syntax.encoding` | a byte that is not UTF-8 | the specification gives no encoding; MATLAB Pulseq and pypulseq fail on such a byte, and the text of the model must be UTF-8 |
| D3.2 | `syntax.line` | a data line before the first section | the specification has no line outside a section; MATLAB Pulseq and pypulseq reject one |
| D3.3 | `section.duplicate` | a section twice, or two `extension` sections with one `STRING_ID` | the three readers read a second copy in three ways |
| D3.4 | `id.unique` | a block ID twice | the specification states uniqueness for shapes and events, not for blocks; both writers number the blocks 1, 2, …, and MATLAB Pulseq stores them by ID |
| D3.5 | `syntax.number` | NaN or infinity in a float column | the specification does not say whether they are floats of the file, and they give no waveform; MATLAB Pulseq writes NaN when a script passes it |
| D3.6 | `syntax.negative` | a negative time or count | spec:176 stores integers as unsigned, but defines negative values elsewhere (time ID -1, a soft delay offset); a negative time or count has no waveform; the writers' makers do not check the sign |
| D3.7 | `shape.empty` | an event uses a shape with no sample | an event with no samples has no waveform |
| D3.8 | `shape.event-length` | the shapes of one event with different numbers of samples | the shapes of an event pair up by sample (spec:349, spec:443); some samples would have no partner |
| D3.9 | `shape.time-order` | an RF time shape of one sample at 0 or before, or a time shape (RF or gradient) whose times do not increase or whose first time is below 0 | such time points define no cell, no line, or no waveform; a time shape of one sample above 0 is read as one cell (D2.10; the user, 2026-10-13) |
| D3.10 | `rotation.zero` | a quaternion of norm 0 | `spec` divides each quaternion by its norm (spec:567: "a normalized rotation quaternion"), and one of norm 0 is no rotation |
| D3.11 | `syntax.shape` | a shape with no blank line after it | spec:602 declares the end of a shape with a blank line, and does not say what a shape without one is |
| D1.3 | `raster.gradient-vertex` | a vertex of a gradient time shape off the gradient raster | section 2.3 |
| D4.4, D4.5 | `layer1.gradient-ends` | a 1.4.x arbitrary gradient on the default raster, or with a time shape whose first time is not 0 | an exception to the rule of this section: writers do write such files (`oracle/pypulseq_simple_mprage140.seq`). A 1.4 file has no `first` and `last`, so it does not define the values at the ends, and the readers guess them differently; Pulseq 1.5 stores them |

### 2.6 Settings of the scanner

`spec` has no setting of the scanner (its one setting, `max_shape_samples`, is
the limit of the samples of a shape: section 3). It reads the file with a
neutral scanner session, and applies the content of the file from the revision
that introduced it: from 1.5.1 its decoding rotates each block's gradients by
the block's quaternion, divided by its norm (D2.18, `SpecDecoding`), and its
`rotation_record` has the setting `"apply"`.

Why: each interpreter's default is its own source with a neutral scanner
session (rule 1 of P20), and the specification describes the rotation as part
of the file (spec:567; rule 2 of P20).

The scanner session (`synth.Session`, rule 3 of P20) is not a setting of `spec`:
`decode(data, session)` and `load(path, session=...)` take it, the same for
every interpreter. `spec` applies its soft delays from 1.5.0 (D2.21, D4.6) and
its field of view with the flags `NOROT` and `NOSLC` from 1.4.1 (D2.20, D2.22,
D4.7), by the shared simulation of `synth.scanner`, and records what it applied
(`soft_delay_record`, `fov_record`). The neutral session (the default) changes
nothing and is recorded, not warned about (rule 4). A setting that addresses
something the file does not have is a `SettingError` (rule 8).

Why: the session is an input of the scanner, not content of the file, and one
`Session` for both interpreters makes their results comparable (rules 3 and 6
of P20; P22).

### 2.7 The values in the model

`spec` gives the model of pulseq-analysis (`SequenceData`) with the values of
the file.

| ID | The file | The model holds |
|---|---|---|
| D2.7 | the text of each definition and of the hash | the text; the four rasters as numbers |
| D4.2 | a 1.4 RF event, with no `center` | `center` absent (NaN in the model, `None` in `RfEvent.center`) |
| — | values with more digits than a 32-bit float | float64 values and int64 IDs, as written |
| — | equal events with different IDs | the IDs and values of the file: no rounding and no renumbering; a time is the number of the file divided by 1e6 or 1e9 |
| — | no dead time, ringdown time or default raster of a scanner | none of them: such values belong to the target, not to the file |

Why: the model holds what the file says (layer 1), and is shared with
`cpp-siemens`, so each field means the same in both (section 7.3 of the
plan).

## 3. The codes of the rejections

Each rejection of `spec` is a `SeqFileError` with every violation, each a
`Violation` with its code, section and line. `spec.RULES` maps each code to its
rule: what it rejects, what it rests on, and, for a rejection of choice
(section 2.5), why. "Partly" marks a code of which only some conditions are
the package's choice.

| Code | ID | Rejects | Rests on |
|---|---|---|---|
| `version.missing` | D1.1 | no `[VERSION]` section | spec:201 |
| `version.invalid` | — | a `[VERSION]` line that is not `major`, `minor` or `revision` with an integer, or a key missing or repeated | spec:193-198 |
| `definitions.raster-missing` | — | a required raster that is not defined | spec:267-276 |
| `definitions.raster-invalid` | — | a raster that is not one finite number above 0 | spec:267-276 |
| `definitions.raster-commensurate` | — | an RF or gradient raster that is neither an integer multiple nor an integer divisor of `BlockDurationRaster` | slide 11 |
| `section.duplicate` | D3.3 | a section twice | choice |
| `syntax.encoding` | D3.1 | a file that is not UTF-8 | choice |
| `syntax.line` | D3.2 | a data line before the first section | choice |
| `syntax.columns` | D1.2 | a row without the number of fields of its table for the version | spec:293-455, spec:476-596 |
| `syntax.integer` | — | a value of an integer column that is not an integer | spec:176, spec:293-455 |
| `syntax.number` | D3.5 | a value of a float column that is not a finite number | spec:176, spec:293-455; partly choice |
| `syntax.use` | — | an RF `use` that is not one of `e r i s p o u` | spec:356-357 |
| `syntax.negative` | D3.6 | a negative time or count | spec:176; choice |
| `syntax.shape` | D3.11 | a shape without its two header lines, a line outside a shape, or a shape with no blank line after it | spec:602-612; partly choice |
| `id.positive` | — | an ID that is not positive, also an extension type ID (in an `extension` header or in `[EXTENSIONS]`) | spec:181, spec:472, spec:494 |
| `id.unique` | D3.4 | an ID used twice in one class | spec:182-183; partly choice (blocks) |
| `id.gradient-unique` | — | a gradient ID in `[GRADIENTS]` and in `[TRAP]` | spec:183, spec:403 |
| `ref.unresolved` | D4.3 | a reference that names nothing, an extension list that does not end, or a time ID -1 where it is not defined | spec:178-186, spec:478, spec:349, spec:395, slide 4 |
| `blocks.empty` | — | no block | spec:318 |
| `block.event-too-long` | — | an event longer than its block | spec:318 |
| `raster.adc-dwell` | — | an ADC dwell time off `AdcRasterTime` | spec:275, slide 10 |
| `raster.adc-delay` | — | an ADC that does not start on an edge of the RF raster | slide 10 |
| `raster.rf-delay` | — | an RF event that does not start on an edge of the RF raster | slide 9, spec:290 |
| `raster.gradient-delay` | — | a gradient that starts off the gradient raster | spec:290, slide 5 |
| `raster.gradient-end` | — | a gradient with a time shape that ends off the gradient raster | spec:290, slide 5 |
| `raster.gradient-ramp` | — | a rise or fall time off the gradient raster | spec:290, slide 5 |
| `raster.gradient-flat` | — | a flat time off the gradient raster | spec:290, slide 5 |
| `raster.gradient-vertex` | D1.3 | a vertex of a gradient time shape off the gradient raster | slide 6 against slide 4; choice |
| `gradient.nonzero-start-delay` | — | a gradient that starts above 0 after a delay | spec:420, slide 6 |
| `gradient.nonzero-end-align` | — | a gradient that ends above 0 before the end of its block | spec:420, slide 6 |
| `shape.length` | — | a shape that does not have the number of samples that it declares | spec:626 |
| `shape.range` | — | an amplitude shape outside [-1, 1] (within `spec.RANGE_TOLERANCE`) | spec:624 |
| `shape.empty` | D3.7 | an event that uses a shape with no sample | choice |
| `shape.event-length` | D3.8 | the shapes of one event with different numbers of samples, or an ADC phase shape without one sample for each ADC sample | spec:349, spec:443, spec:120; choice |
| `shape.time-order` | D3.9 | an RF time shape of one sample at 0 or before, or a time shape (RF or gradient) whose times do not increase or whose first time is below 0 | spec:349, spec:395; choice |
| `shape.oversampled-length` | — | an oversampled gradient with an even number of samples | spec:420, slides 4 and 8 |
| `rotation.zero` | D3.10 | a quaternion of norm 0 | spec:567; choice |
| `extension.required-unknown` | — | a required extension that `spec` does not know | spec:460 |
| `extension.per-block` | — | a block with more than one ROTATIONS or RF_SHIMS object | spec:567, spec:584 |
| `layer1.gradient-ends` | D4.4, D4.5 | a 1.4.x arbitrary gradient with no value at its start or end | spec:290; choice |
| `signature.invalid` | — | a `[SIGNATURE]` without one `Type` and one `Hash` | spec:223-232 |

A version outside 1.4.0 to 1.5.x, a binary file and a folder are not a
rejection: they raise `NotSupported` (section 2.1). A shape that declares more
samples than the setting `max_shape_samples` of `spec` is not a rejection
either: it raises `NotSupported`, before `spec` decompresses the shape, and
`Spec(max_shape_samples=None)` reads the file. The default is
`interpreters.DEFAULT_MAX_SHAPE_SAMPLES`, 2^27 samples. The limit is not a
reading of the specification, which has no limit of `num_samples` (spec:619),
but the package's limit of memory: 2^27 samples are 1 GiB of float64, and a
short file cannot make `spec` allocate without bound. It is a setting of every
interpreter (the user, 2026-10-18).
