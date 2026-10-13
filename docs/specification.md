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
"slide N". The IDs (D02, D21, …) name a condition in a file. They are the IDs
of [`docs/discrepancies.md`](discrepancies.md), whose entry for each ID gives
what the specification, the C++ reader, MATLAB Pulseq and pypulseq do, with
citations, and the fixtures. P1 to P21 and Q1 to Q6 are the decisions of
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

**D03: a version before 1.4.0 or from 1.6.0.** `spec` raises `NotSupported`,
which says nothing about the file, and also for a binary file or a folder
(`bad_version_unsupported_1_3.seq`, `bad_version_unsupported_1_6.seq`). The
specification has no rule for a version that a reader does not know.

Why: the package reads 1.4.0 to 1.5.x only (Q1), so a version that it does not
know fails loudly, not wrongly.

### 2.2 Each version is its own format

`spec` reads a file of 1.4.x by the tables of that version, and reads each
mechanism of the format only from the revision that introduced it.

| ID | Condition | What `spec` does |
|---|---|---|
| D01a-c, D38 | a 1.4.x `[RF]`, `[GRADIENTS]` or `[ADC]` row | the 1.4 layout: 8, 5 and 6 fields, with no `center`, no `first` and `last`, no ppm offsets, no `use` and no ADC phase shape; `center` is absent and `use` is `u` |
| D22 | time ID -1 of a gradient in a 1.4 file | `ref.unresolved`: -1 is "Updated in v1.5.0" (slide 4) |
| D45 | `extension DELAYS` before 1.5.0; ROTATIONS or RF_SHIMS before 1.5.1 | an extension that `spec` does not know: ignored, with a record (reason `"version"`; `valid_1_5_0_extensions_of_1_5_1.seq`) |
| D47 | `RequiredExtensions` before 1.5.1 | not read |
| D49 | a rotation in a file before 1.5.1 | not applied (the extension is ignored, D45) |
| D50 | a flag of 1.4.1 (`PMC`, `NOROT`, `NOPOS`, `NOSLC`, `ONCE`, spec:526) in an older file | kept, with a record (reason `"version"`) |

Why: the specification gives the revision of each mechanism (its table of
revisions, spec:109-120, and spec:526, spec:545, spec:567, spec:584), and a
reader of a version has only the mechanisms of that version (the user,
2026-10-12; rule 2 of P20).

### 2.3 Where the specification disagrees with itself

| ID | The disagreement | What `spec` follows |
|---|---|---|
| D01a-c | the prose counts 7, 4 and 6 numbers (spec:334, spec:375, spec:424); the tables and examples have 12, 7 and 9 fields | the tables and examples, as all three readers and MATLAB's files do; another count is `syntax.columns` |
| D55 | the table types `STRING_ID` as an integer (spec:493); the text and every example give a word | the text and the examples: `STRING_ID` is text, as all three readers read it |
| D02 | a reader "may either refuse execution or assume version 1.0.0", and "It is recommended to reject" (spec:201) | the recommendation: `version.missing` |
| D26 | slide 6 puts the vertices of an extended trapezoid "all aligned on raster edges"; slide 4 calls it "not a requirement" of a time shape | slide 6: `raster.gradient-vertex`, a rejection of choice (2.5), since the makers of both writers refuse a vertex off the raster (`makeExtendedTrapezoid.m:84-85`, `make_extended_trapezoid.py:115-116`) |

Why: where the parts of the specification disagree, `spec` follows the part
that the readers and the writers' files agree with.

### 2.4 Where the specification is silent: the readings

Where the specification and the slide set are silent, `spec` reads the file as
section 6 of the plan chose (Q5).

| ID | Condition | What `spec` does | Why |
|---|---|---|---|
| D05 | sections in any order | reads them by name (`undefined/version_last.seq` is read) | the specification sets no order, except that the file "may end with" `[SIGNATURE]` (spec:213) |
| D56 | the last section with no blank line after it | reads it (`valid_last_section_no_blank.seq`) | the specification ends only a shape with a blank line (spec:602) |
| D06 | a blank or `#` line inside a section | skipped anywhere; inside a shape, a blank line ends the shape and a `#` line is skipped (`valid_comment_in_shape.seq`) | "Comments are specified by a line starting with a hash" (spec:171); the specification gives no rule that a blank line ends a table |
| D08, D09 | a section that the format does not have, or `[DELAYS]` | ignored, with a record | `[DELAYS]` was removed in 1.4.0 (spec:114), and "Current readers ignore this section" (spec:772); an unknown section is ignored as the C++ reader does |
| D12 | a definition twice | the last | as all three readers do |
| D13 | a definition or a hash that reads as a number | the text; only the four rasters are numbers | `<value>` is "any" (spec:247) and the hash a "string" (spec:230); a double cannot hold the 32 digits of a hash |
| D16 | a soft delay offset with a fraction; a long hint | the offset is a float in µs; the hint is the whole text (`valid_soft_delay_fraction.seq`) | the specification has no table of types for the row; MATLAB writes and reads a float, and the binary format stores a time in ps (spec:723) |
| D31 | an RF magnitude below 0 | played as written: a signed amplitude | the specification allows [-1, 1] for an amplitude shape (spec:624) |
| D32 | an RF phase outside [0, 1) | played as written: 2π times the value, as MATLAB does | the specification gives no range for the phase |
| D35 | an RF time shape whose times are `(i + 0.5) d` | cells of `d`: each sample held for one dwell, and the pulse lasts `N d` | slide 9 places the samples of a regular pulse at the centres of their dwell periods; every regular pulse of MATLAB Pulseq and pypulseq has this form (the user's choice). The split does not depend on how the shape is stored (spec:602) |
| D36 | any other RF time shape | points at its times, joined by straight lines of the complex signal; the pulse ends at its last time (`bad_shape_rf_time_end.seq`) | slide 9: a pulse "defined by vertices", which need not be on the raster (slide 4); the straight line of the complex signal is the C++ reader's stated intent (`cpp:2033`) and MATLAB's for RF power, bandwidth and simulation (the user's choice) |
| D37 | where a pulse with a time shape ends | `N d` for cells, the last time for points | slide 9 (N dwell periods from the start), and the last vertex |
| D41 | an arbitrary gradient between its samples (time ID 0) | straight lines between the cell centres, and to `first` and `last` at the edges | spec:290 puts the samples at the centres and is silent between them; slide 7 draws lines |
| D42 | a gap between gradient events | 0 where no gradient event plays; with D27, a gap inside a block lies between zeros | the specification is silent between events |
| D43 | an oversampled gradient (time ID -1) | all the samples, half a raster apart, the first and last at cell centres | spec:420 and slides 4 and 8: N − 1 extra points on the cell edges |
| D44 | an ADC phase modulation shape | rad, one value for each ADC sample | the specification gives no unit (spec:443) and a "phase offset per sample" (spec:120) |
| D45 | an unknown extension that the file does not require | ignored, with a record | "The interpreter MUST detect unknown extensions and MAY chose to ignore them" (spec:460) |
| D46 | `[EXTENSIONS]` as the last section | read (`oracle/koma_v1.5_unknown_ext.seq`) | the specification sets no order of the sections |
| D50 | a label that the specification does not list | kept as text, with a record; so is `NOSCL`, which the specification spells `NOSLC` (spec:520) | labels do not change the waveforms |
| D53 | a signature hash | `Signature.matches` by the rule of spec:223: the md5 of the bytes before `[SIGNATURE]`, without the `\n` right before it; a mismatch is not a rejection (`valid_crlf.seq`, `valid_signature_mismatch.seq`) | the specification says to strip that new line, and has no "must" to verify the hash |

### 2.5 Where the specification is silent: the rejections of choice

`spec` rejects a file where the specification is silent only where no current
writer (MATLAB Pulseq, pypulseq) writes such a file (the user, 2026-10-12). The
message of each such rejection says that the specification does not state the
rule, and why `spec` rejects the file (`Rule.choice` in `spec.RULES`).

| ID | Code | Condition | Why |
|---|---|---|---|
| D06 | `syntax.line` | a data line before the first section | the specification has no line outside a section; MATLAB Pulseq and pypulseq reject one |
| D07 | `syntax.shape` | a shape with no blank line after it | spec:602 declares the end of a shape with a blank line, and does not say what a shape without one is |
| D10 | `section.duplicate` | a section twice, or two `extension` sections with one `STRING_ID` | the three readers read a second copy in three ways |
| D14 | `syntax.number` | NaN or infinity in a float column | the specification does not say whether they are floats of the file |
| D14 | `syntax.negative` | a negative time or count | spec:176 stores integers as unsigned, but defines negative values elsewhere (time ID -1, a soft delay offset); a negative time or count has no waveform |
| D14 | `syntax.encoding` | a byte that is not UTF-8 | the specification gives no encoding; MATLAB Pulseq and pypulseq fail on such a byte, and the text of the model must be UTF-8 |
| D19 | `id.unique` | a block ID twice | the specification states uniqueness for shapes and events, not for blocks; both writers number the blocks 1, 2, …, and MATLAB Pulseq stores them by ID |
| D26 | `raster.gradient-vertex` | a vertex of a gradient time shape off the gradient raster | section 2.3 |
| D33 | `shape.empty` | an event uses a shape with no sample | an event with no samples has no waveform |
| D34, D44 | `shape.event-length` | the shapes of one event with different numbers of samples | the shapes of an event pair up by sample (spec:349, spec:443); some samples would have no partner |
| D36 | `shape.time-order` | an RF time shape of one sample, times that do not increase, or a first time below 0 | such time points define no step, no line, or no waveform |
| D49 | `rotation.zero` | a quaternion of norm 0 | `spec` divides each quaternion by its norm (spec:567: "a normalized rotation quaternion"), and one of norm 0 is no rotation |
| D39, D40 | `layer1.gradient-ends` | a 1.4.x arbitrary gradient on the default raster, or with a time shape whose first time is not 0 | an exception to the rule of this section: writers do write such files (`oracle/pypulseq_simple_mprage140.seq`). A 1.4 file has no `first` and `last`, so it does not define the values at the ends, and the readers guess them differently; Pulseq 1.5 stores them |

### 2.6 Settings of the scanner

`spec` has no setting. It reads the file with a neutral scanner session, and
applies the content of the file from the revision that introduced it: from
1.5.1 its decoding rotates each block's gradients by the block's quaternion,
divided by its norm (D49, `SpecDecoding`), and its `rotation_record` has the
setting `"apply"`.

Why: each interpreter's default is its own source with a neutral scanner
session (rule 1 of P20), and the specification describes the rotation as part
of the file (spec:567; rule 2 of P20).

### 2.7 The values in the model

`spec` gives the model of pulseq-analysis (`SequenceData`) with the values of
the file.

| ID | The file | The model holds |
|---|---|---|
| D13 | the text of each definition and of the hash | the text; the four rasters as numbers |
| D18 | values with more digits than a 32-bit float | float64 values and int64 IDs, as written |
| D38 | a 1.4 RF event, with no `center` | `center` absent (NaN in the model, `None` in `RfEvent.center`) |
| D51 | equal events with different IDs | the IDs and values of the file: no rounding and no renumbering; a time is the number of the file divided by 1e6 or 1e9 |
| D52 | no dead time, ringdown time or default raster of a scanner | none of them: such values belong to the target, not to the file |

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
| `version.missing` | D02 | no `[VERSION]` section | spec:201 |
| `version.invalid` | D04 | a `[VERSION]` line that is not `major`, `minor` or `revision` with an integer, or a key missing or repeated | spec:193-198 |
| `definitions.raster-missing` | D11 | a required raster that is not defined | spec:267-276 |
| `definitions.raster-invalid` | D11 | a raster that is not one finite number above 0 | spec:267-276 |
| `definitions.raster-commensurate` | D11, D28 | an RF or gradient raster that is neither an integer multiple nor an integer divisor of `BlockDurationRaster` | slide 11 |
| `section.duplicate` | D10 | a section twice | choice |
| `syntax.encoding` | D14 | a file that is not UTF-8 | choice |
| `syntax.line` | D06 | a data line before the first section | choice |
| `syntax.columns` | D01a-c, D14 | a row without the number of fields of its table for the version | spec:293-455, spec:476-596 |
| `syntax.integer` | D14 | a value of an integer column that is not an integer | spec:176, spec:293-455 |
| `syntax.number` | D14 | a value of a float column that is not a finite number | spec:176, spec:293-455; partly choice |
| `syntax.use` | D17 | an RF `use` that is not one of `e r i s p o u` | spec:356-357 |
| `syntax.negative` | D14 | a negative time or count | spec:176; choice |
| `syntax.shape` | D07 | a shape without its two header lines, a line outside a shape, or a shape with no blank line after it | spec:602-612; partly choice |
| `id.positive` | D19 | an ID that is not positive | spec:181 |
| `id.unique` | D19 | an ID used twice in one class | spec:182-183; partly choice (blocks) |
| `id.gradient-unique` | D19 | a gradient ID in `[GRADIENTS]` and in `[TRAP]` | spec:183, spec:403 |
| `ref.unresolved` | D21, D22, D23 | a reference that names nothing, an extension list that does not end, or a time ID -1 where it is not defined | spec:178-186, spec:478, spec:349, spec:395, slide 4 |
| `blocks.empty` | D24 | no block | spec:318 |
| `block.event-too-long` | D25 | an event longer than its block | spec:318 |
| `raster.adc-dwell` | D26 | an ADC dwell time off `AdcRasterTime` | spec:275, slide 10 |
| `raster.adc-delay` | D26 | an ADC that does not start on an edge of the RF raster | slide 10 |
| `raster.rf-delay` | D26 | an RF event that does not start on an edge of the RF raster | slide 9, spec:290 |
| `raster.gradient-delay` | D26 | a gradient that starts off the gradient raster | spec:290, slide 5 |
| `raster.gradient-end` | D26 | a gradient with a time shape that ends off the gradient raster | spec:290, slide 5 |
| `raster.gradient-ramp` | D26 | a rise or fall time off the gradient raster | spec:290, slide 5 |
| `raster.gradient-flat` | D26 | a flat time off the gradient raster | spec:290, slide 5 |
| `raster.gradient-vertex` | D26 | a vertex of a gradient time shape off the gradient raster | slide 6 against slide 4; choice |
| `gradient.nonzero-start-delay` | D27 | a gradient that starts above 0 after a delay | spec:420, slide 6 |
| `gradient.nonzero-end-align` | D27 | a gradient that ends above 0 before the end of its block | spec:420, slide 6 |
| `shape.length` | D29 | a shape that does not have the number of samples that it declares | spec:626 |
| `shape.range` | D30 | an amplitude shape outside [-1, 1] (within `spec.RANGE_TOLERANCE`) | spec:624 |
| `shape.empty` | D33 | an event that uses a shape with no sample | choice |
| `shape.event-length` | D34, D44 | the shapes of one event with different numbers of samples, or an ADC phase shape without one sample for each ADC sample | spec:349, spec:443, spec:120; choice |
| `shape.time-order` | D35-D37 | an RF time shape of one sample, times that do not increase, or an RF first time below 0 | spec:349, spec:395; choice |
| `shape.oversampled-length` | D43 | an oversampled gradient with an even number of samples | spec:420, slides 4 and 8 |
| `rotation.zero` | D49 | a quaternion of norm 0 | spec:567; choice |
| `extension.required-unknown` | D47 | a required extension that `spec` does not know | spec:460 |
| `extension.per-block` | D48 | a block with more than one ROTATIONS or RF_SHIMS object | spec:567, spec:584 |
| `layer1.gradient-ends` | D39, D40 | a 1.4.x arbitrary gradient with no value at its start or end | spec:290; choice |
| `signature.invalid` | D54 | a `[SIGNATURE]` without one `Type` and one `Hash` | spec:223-232 |

A version outside 1.4.0 to 1.5.x, a binary file and a folder are not a
rejection: they raise `NotSupported` (section 2.1).
