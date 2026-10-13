# Where the specification does not decide, and what `spec` does

This document records the decisions of the interpreter `spec` of pulseq-analysis
that the Pulseq specification does not settle. For each decision it gives what
the specification and the C++ reader of the scanner do, an example, what `spec`
does, and why. It records the package as it is on 2026-10-13. The sources and
the runs on them are those of 2026-10-09, unless an entry says otherwise.

An entry exists only for such a decision: the specification is unclear (it
contradicts itself, or it only recommends), or it is silent, or it does not
cover a version that the package reads. Where the specification states a rule
there is no entry, because each interpreter follows its own rule: `spec` the
specification, `cpp-siemens` the C++ reader. [`docs/specification.md`](specification.md)
gives the decisions of this record by rule, and its section 3 gives the rule and
the code of each rejection of `spec` (`spec.RULES`), with the lines of the
specification that state it.

The entries are in four groups, by the kind of decision:

- D1: the specification is unclear. It contradicts itself, or it only
  recommends, and `spec` resolves it.
- D2: the specification is silent, and `spec` reads the file.
- D3: the specification is silent, and `spec` rejects the file by choice. The
  message of such a rejection says that the specification does not state the
  rule, and why `spec` rejects the file (`Rule.choice` in `spec.RULES`). The
  rule of the user (2026-10-12) is to reject only where no current writer
  writes such a file, so each entry says what the two writers write. Runs of
  2026-10-13 found writers that write the files of D3.5, D3.6 and D3.9; each of
  those entries gives the user's decision.
- D4: versions. The gate (both interpreters), and each version as its own
  format.

An ID names a decision, not a condition in a file. A condition on which each
interpreter decides has two IDs, and the two entries link to each other. The
other interpreter, `cpp-siemens`, has its own record:
[`packages/pulseq-cpp-siemens/docs/specification.md`](../packages/pulseq-cpp-siemens/docs/specification.md),
in the plugin pulseq-cpp-siemens. Its rule is to do what the C++ reader does;
that record holds the decisions D5 to D7, where it departs from the reader. D4.1,
the version gate, is the decision of both interpreters: it is in this record, and
the record of `cpp-siemens` cites it.

On 2026-10-13 the entries were regrouped by kind of decision. Before, each
condition of a file had one entry (D01a to D60), with a row for each of four
sources. MATLAB Pulseq and pypulseq are no longer sources of the record, and an
entry for a condition in which the specification states the rule, or that
concerns only MATLAB Pulseq or pypulseq, was removed. The appendix maps each old
ID to its new IDs. Historical documents (`docs/plans/`, except
`parser-redesign.md`, `docs/reviews/`, and the released sections of
`CHANGELOG.md`) keep the old IDs.

Until 2026-10-13 this document also had a section 4, a review of the package's
former strict reader against an order of preference of the sources (the C++
reader, the specification, MATLAB Pulseq, pypulseq). The two interpreters
replaced that goal (section 1 of the plan), so the section was removed; commit
`49a7e2c` is the last that has it.

Contents:

1. [The sources](#1-the-sources)
2. [Summary](#2-summary)
3. [The entries](#3-the-entries)
4. [Appendix: the old IDs, the acceptance matrix and the figures](#appendix-the-old-ids-the-acceptance-matrix-and-the-figures)

## 1. The sources

Two sources define how a file is read: the specification, with the slide set that it cites, and the C++ reader. Each is fixed at one version.

| Source | Version | Where it is used | Cited as |
|---|---|---|---|
| The specification | `doc/specification.tex` of [pulseq/pulseq](https://github.com/pulseq/pulseq) at commit `c7469123c2f381f065986e6cc3a7d09730ed16ef`: "Version 1.5.3 (DRAFT)". The PDF of that commit (`doc/specification.pdf`) is made from it. | The definition of the format. | `spec:N`, line N of `specification.tex`, with the section number of the PDF |
| The slide set of the specification | `doc/pulseq_shapes_and_times.pdf` of the same commit, which section 2.6 of the specification cites for timing. Normative for timing (the user, 2026-10-12). | The definition of the timing of the events. | "slide N" |
| The C++ reader | `src/ExternalSequence.cpp` and `src/ExternalSequence.h` of pulseq/pulseq at the same commit, built by `flake.nix` as `pulseq-cpp-oracle` with the driver of `tests/cpp_oracle/` | The reader of the Pulseq interpreter on the scanner: what the scanner plays. | `cpp:N` (`.cpp`), `cpp.h:N` (`.h`) |

pulseq-analysis ("the package") reads a file with `read_seqfile(path,
interpreter)` (`docs/usage.md`, "The interpreters"). Its built-in interpreter,
`spec` (the default: `read_seqfile(path)`), reads a file as the Pulseq
specification describes it, and for timing as the slide set. It rejects a file
where they say "must", with every violation and a code for each (`spec.RULES`).
Where they are silent it reads the file as section 6 of the plan chose, and
rejects a file only as group D3 lists; the message of such a rejection says that
it is the package's choice and why. It replaced the strict reader that the
package had before the interpreters (task R11).

A version outside 1.4.0 to 1.5.x raises `NotSupported` (D4.1, decision Q1), and
says nothing about the file. The package reports no discrepancy itself:
pulseq-checks does (P17). The decisions P1 to P21 and Q1 to Q6 that this
document cites are those of sections 2 and 3 of `docs/plans/parser-redesign.md`
("the plan"). The entries of section 3 give what `spec` does and why.

MATLAB Pulseq and pypulseq are not sources of this record. They are not the
definition of the format, and not the reader on the scanner. They appear as
writers only: where a decision of `spec` rests on what the two toolboxes write
(a rejection of choice in D3, or a reading in D2), the entry says what they
write, and cites their code.

| Writer | Version | Cited as |
|---|---|---|
| MATLAB Pulseq | `matlab/` of pulseq/pulseq at the same commit | `write.m:N`, `write_v141.m:N`, `Sequence.m:N` (`matlab/+mr/@Sequence/`); `makeArbitraryRf.m:N`, `compressShape.m:N` and the other makers (`matlab/+mr/`) |
| pypulseq | The pin of `pyproject.toml`: the fork [mdtisdall/pypulseq](https://github.com/mdtisdall/pypulseq) at `3c3bd8515e591ef859399aa20db64b1bd2c3a725` (pypulseq 1.5.0.post1 and six commits) | `write_seq.py:N`, `block.py:N`, `sequence.py:N` (`pypulseq/Sequence/`); `make_arbitrary_rf.py:N`, `compress_shape.py:N` and the other makers (`pypulseq/`) |

Each statement about a source was checked in one of these ways:

- by reading its code at the commit above (the citation gives the file and the
  line);
- by a run on 2026-10-09, on an Apple M1 Max (macOS 26.6.2, arm64): the
  acceptance matrix (`scripts/discrepancy_matrix.py`, appendix; run again on
  2026-10-13 with the fixtures of R11, and the same verdicts of the C++ reader
  for the earlier fixtures), or a small file that the entry shows (run through
  the same readers as the matrix). The C++ reader is the macOS build of
  `pulseq-cpp-oracle`. "Crash" is a signal (exit status 70 of the driver). Where
  the reader reads memory that it does not own, the result can depend on the
  build, and the entry says so;
- by a run on 2026-10-12 of `spec` (before task R11, of the strict reader) on
  the fixture or the small file that the entry names, with `pulseq-cpp-oracle`
  on the same file; or
- for a writer, by a run on 2026-10-13 of the toolbox on a small script, which
  the entry names: MATLAB Pulseq under GNU Octave 11.3.0, pypulseq in the project
  environment. Such a run shows what the toolbox accepts and writes for the value
  that it was given.

## 2. Summary

The verdicts are short. "Accepts" and "reads" mean that the source goes on with
no error; "rejects" means an error; "silent" means that the source has no rule.
The last column is the interpreter `spec`: "not supported" is the
`NotSupported` exception; "(choice)" marks a rejection of `spec` that the
specification does not state, which its message says.

| ID | Condition in the file | Specification | C++ reader | `spec` |
|---|---|---|---|---|
| [D1.1](#d11-a-file-with-no-version-section-a-recommendation) | No `[VERSION]` | recommends to reject | rejects | rejects |
| [D1.2](#d12-the-number-of-fields-of-an-rf-gradients-or-adc-row-prose-against-tables) | `[RF]` row of 12 fields, `[GRADIENTS]` of 7, `[ADC]` of 9 | prose: 7, 4 and 6 numbers; tables and examples: 12, 7, 9 | 12, 7, 9 | 12, 7, 9 |
| [D1.3](#d13-a-vertex-of-a-gradient-time-shape-off-the-gradient-raster-slide-6-against-slide-4) | Vertex of a gradient time shape off the gradient raster | slide 6: on the edges; slide 4: not a requirement | accepts; rounds to µs | rejects (choice) |
| [D1.4](#d14-an-extension-header-whose-string_id-is-a-word-table-against-examples) | `STRING_ID` that is a word | integer in the table; a word in the examples | text | text |
| [D2.1](#d21-sections-in-any-order) | Sections in any order | silent | any order; crash with `[VERSION]` last | any order |
| [D2.2](#d22-the-last-section-with-no-blank-line-after-it) | Last section with no blank line after it | silent | skips the sections it reads after it | reads |
| [D2.3](#d23-extensions-as-the-last-section) | `[EXTENSIONS]` as the last section | silent | rejects | accepts |
| [D2.4](#d24-a-section-that-the-format-does-not-have) | Unknown section | silent | ignores | ignores |
| [D2.5](#d25-a-blank-or--line-inside-a-section) | Blank or `#` line inside a section | silent | blank line ends a table; `#` is data | skips both |
| [D2.6](#d26-a-definition-that-appears-twice) | A definition twice | silent | last wins | last wins |
| [D2.7](#d27-a-definition-or-a-signature-hash-whose-text-reads-as-a-number) | Definition or hash that reads as a number | `any`, hash `string` | text and numbers | text |
| [D2.8](#d28-an-rf-magnitude-sample-below-0) | RF magnitude below 0 | allows [-1, 1] | clamps to 0 | plays as written |
| [D2.9](#d29-an-rf-phase-sample-outside-0-1) | RF phase outside [0, 1) | silent | clamps | plays as written |
| [D2.10](#d210-an-rf-time-shape-whose-times-are-i--05-d-cells) | RF time shape of `(i + 0.5) d` | times in the shape | 3 or 4 stored values: dwell from the shape, first time ignored | cells |
| [D2.11](#d211-any-other-rf-time-shape-points) | Any other RF time shape | times in the shape | resamples; can read past the end | points, complex lines |
| [D2.12](#d212-where-an-rf-pulse-with-a-time-shape-ends) | End of an RF pulse with a time shape | silent | dwell × samples | `N d`, or the last point |
| [D2.13](#d213-an-arbitrary-gradient-between-its-samples-time-id-0) | Time-ID-0 gradient between its samples | centres of cells | lines | lines |
| [D2.14](#d214-a-gap-between-two-gradient-events-on-one-axis) | Gap between gradient events | silent | one block only | 0 in a block; across blocks R14 |
| [D2.15](#d215-an-adc-phase-modulation-shape-rad-one-value-per-sample) | ADC phase modulation shape | none | rad | rad, one per sample |
| [D2.16](#d216-a-soft-delay-offset-with-a-fraction-or-a-long-hint) | Soft delay offset `-100.5`; long hint | integer in the example | misreads `-100.5`; cuts the hint | reads (float) |
| [D2.17](#d217-an-unknown-extension-that-the-file-does-not-require) | Unknown extension, not required | may ignore | ignores | ignores; records it |
| [D2.18](#d218-a-rotation-quaternion-divided-by-its-norm) | Quaternion norm | normalized quaternion | normalizes; rejects off by 1e-3 | normalizes |
| [D2.19](#d219-a-label-that-the-specification-does-not-list) | Unknown label name | lists labels | ignores the label | reads; records it |
| [D3.1](#d31-a-byte-that-is-not-utf-8) | Byte that is not UTF-8 | silent | does not check | rejects (choice) |
| [D3.2](#d32-a-data-line-before-the-first-section) | Data line before the first section | silent | never reads it | rejects (choice) |
| [D3.3](#d33-a-section-that-appears-twice) | A section twice | silent | reads the last | rejects (choice) |
| [D3.4](#d34-a-block-id-used-twice) | A block ID twice | silent for blocks | does not use the ID | rejects (choice) |
| [D3.5](#d35-nan-or-infinity-in-a-float-column) | NaN or infinity in a float column | silent | reads | rejects (choice) |
| [D3.6](#d36-a-negative-time-or-count) | Negative time or count | integers unsigned; negatives elsewhere | reads | rejects (choice) |
| [D3.7](#d37-an-event-that-uses-a-shape-with-no-sample) | Empty shape that an event uses | silent | crashes (macOS build) | rejects (choice) |
| [D3.8](#d38-the-shapes-of-one-event-with-different-numbers-of-samples) | Shapes of one event, two lengths | silent | crashes (RF) | rejects (choice) |
| [D3.9](#d39-an-rf-time-shape-of-one-sample-or-times-that-do-not-increase-or-start-below-0) | RF time shape of one sample, or times not increasing | times in the shape | resamples; no check | rejects (choice) |
| [D3.10](#d310-a-rotation-quaternion-of-norm-0) | Quaternion of norm 0 | normalized quaternion | rejects | rejects (choice) |
| [D3.11](#d311-a-shape-with-no-blank-line-after-it) | No blank line after a shape | blank line ends a shape | reads the next header as a sample line; stops | rejects (choice) |
| [D4.1](#d41-a-version-before-140-or-from-160-both-interpreters) | Version before 1.4.0 or from 1.6.0 | silent | 1.2.0 and later | not supported |
| [D4.2](#d42-the-rows-of-a-14-file-and-the-rf-center-that-it-does-not-have) | Rows of a 1.4 file; RF center | no `center` in 1.4 | 1.4 rows; center -1 | 1.4 rows; center absent |
| [D4.3](#d43-time-id--1-in-a-14-file) | Time ID -1 in a 1.4 file | gradients only; slide 4: 1.5.0 | accepts | rejects |
| [D4.4](#d44-a-14-arbitrary-gradient-on-the-default-raster-no-ends) | 1.4 gradient on the default raster | no `first`, `last` in 1.4 | about 0 | rejects (choice) |
| [D4.5](#d45-a-14-arbitrary-gradient-with-a-time-shape) | 1.4 time-shaped gradient | no `first` in 1.4 | first sample | first sample |
| [D4.6](#d46-an-extension-before-the-revision-that-introduced-it) | Extension before its revision | revision of each extension | any version | ignores; records it |
| [D4.7](#d47-a-label-flag-of-141-in-an-older-file) | Label flag of 1.4.1 in an older file | flags new in 1.4.1 | decodes in any version | reads; records it |

## 3. The entries

Each entry has a table with what the specification and the C++ reader do, the
example (fixtures of `tests/seqfiles/` and runs), what `spec` does, and the
reason. An entry that pairs with a decision of `cpp-siemens` ends with a link to
it. The user's decisions carry the date where it is known.

### D1. The specification is unclear

#### D1.1: A file with no [VERSION] section (a recommendation)

| Source | What it does |
|---|---|
| Specification | "the interpreter sequence may either refuse execution or assume version 1.0.0. It is recommended to reject Pulseq files without [VERSION] section." (section 2.3, `spec:201`) |
| C++ reader | Rejects: "supported Pulseq files MUST contain the [VERSION] section" (`cpp:912-916`). |

Example: `tests/seqfiles/bad_version_missing.seq` (matrix: the C++ reader rejects).

`spec`: `version.missing`.

Reason: the specification recommends to reject a file without `[VERSION]`
(spec:201), and `spec` needs the version to know the layout of the tables.

#### D1.2: The number of fields of an [RF], [GRADIENTS] or [ADC] row (prose against tables)

| Source | What it does |
|---|---|
| Specification | Section 2.8 describes each row three ways. `[RF]` (section 2.8.1): the prose says "a single line containing seven numbers", and the line under it has 8 fields: `<id> <amp> <mag_id> <phase_id> <time_id> <delay> <freq> <phase>` (`spec:334-336`); the table has 12 fields, with `<center>` before `<delay>`, and `<freq_ppm>`, `<phase_ppm>` and `<use>` (`spec:341-359`); the example has 12 (`spec:366-369`). `[GRADIENTS]` (section 2.8.2): "specified by four numbers", a line of 7 fields: `<id> <amp> <first> <last> <shape_id> <time_id> <delay>` (`spec:375-377`); the table and the example have 7 (`spec:386-413`). `[ADC]` (section 2.8.3): "specified by six numbers", a line of 9 fields: `<id> <num> <dwell> <delay> <freq_ppm> <phase_ppm> <freq> <phase> <phase_shape_id>` (`spec:424-426`); the table and the example have 9 (`spec:431-453`). Only the count of the prose differs for `[GRADIENTS]` and `[ADC]`; the line, the table and the example agree. |
| C++ reader | Reads 12 values of an `[RF]` row, 7 of a `[GRADIENTS]` row and 9 of an `[ADC]` row in a 1.5 file (`cpp:1042-1048`, `cpp:1073`, `cpp:1148-1149`). |

Example: the first row of the example of section 2.8.1,
`1 550 1 2 0 1000 100 0.000 0.0000 0.000 0.000 e`. By the line of the prose,
the delay is 1000 µs and the frequency offset is 100 Hz. By the table, the
center is at 1000 µs and the delay is 100 µs, as the text under the example
says (`spec:372`). For `[GRADIENTS]`, the example row `1 790127 0 -550073 6 0
980`; for `[ADC]`, the example rows of section 2.8.3.

`spec`: reads the 12, 7 and 9 fields of the tables, in their order (the columns
of `as_written`). A row with another number of fields is `syntax.columns`. A
1.4.x file has its own layouts, of 8, 5 and 6 fields (D4.2, D4.4, D4.5).

Reason: where the prose of the specification contradicts its tables and
examples, `spec` follows the tables and examples. The C++ reader and the files of
both writers agree with them: the writers write 12, 7 and 9 fields (`write.m:86`,
`write.m:102`, `write.m:131`; `write_seq.py:111`, `write_seq.py:134`,
`write_seq.py:169`).

Note: the specification has another slip of the text that does not change how a
file is read: the paragraph of the soft delay extension starts "Label extension
can be used" (`spec:545`).

#### D1.3: A vertex of a gradient time shape off the gradient raster (slide 6 against slide 4)

| Source | What it does |
|---|---|
| Specification | The slides conflict on the vertices of an extended trapezoid. Slide 6 puts them "all aligned on raster edges"; slide 4 puts the points of a time shape on the edges "typically", and calls it "not a requirement". Section 2.6 of the specification states the last vertex (a gradient with a time shape ends on the gradient raster, `spec:290`). |
| C++ reader | Does not check (matrix: accepts `bad_raster_gradient_vertex.seq`). It rounds each time of the shape, in gradient rasters, to a whole µs: `long(0.5 + raster_us * t)` (`cpp:2182`). |

Example: `tests/seqfiles/bad_raster_gradient_vertex.seq`.

`spec`: `raster.gradient-vertex` for a vertex of a gradient time shape off the
gradient raster, within `spec.FIRST_TIME_TOLERANCE` (1e-6 gradient rasters). The
last vertex is `raster.gradient-end`, which the specification states.

Reason: the slides conflict, and `spec` follows slide 6, so it rejects the file
(the user's choice; the message says that this is the package's choice). The
makers of both writers refuse a vertex off the raster
(`makeExtendedTrapezoid.m:84-85`, `make_extended_trapezoid.py:115-116`), unless
they are asked to resample the shape onto the regular grid (`convert2arbitrary`,
`makeExtendedTrapezoid.m:75-81`; `convert_to_arbitrary`,
`make_extended_trapezoid.py:102-112`), which gives an arbitrary gradient with no
time shape.

#### D1.4: An extension header whose STRING_ID is a word (table against examples)

| Source | What it does |
|---|---|
| Specification | Section 2.8.4 gives the type of `<STRING_ID>` as "integer" in its table (`spec:493`); the text calls it a text ID, and each example has a word, such as `extension TRIGGERS 1` (`spec:498`, `spec:507`, `spec:553`). |
| C++ reader | Reads `STRING_ID` as text (`cpp:1228-1244`). |

Example: `extension LABELSET 2` in `tests/seqfiles/valid_1_5_1.seq`, and every
`extension` header of the oracle files.

`spec`: reads `STRING_ID` as text; `Extensions.type_ids` maps it to the type ID of
the file.

Reason: here the table and the examples of the specification disagree with each
other (D1.2 is about the prose against the tables). `spec` follows the examples
and the C++ reader. Both writers write a word (`write.m:166`, `write.m:183`,
`write.m:195`, `write.m:210`, `write.m:223`, `write.m:237`; `write_seq.py:191`,
`write_seq.py:204`, `write_seq.py:219`, `write_seq.py:234`).

### D2. The specification is silent, and `spec` reads the file

#### D2.1: Sections in any order

| Source | What it does |
|---|---|
| Specification | Silent, except that the file "may end with" `[SIGNATURE]` (section 2.4, `spec:213`). |
| C++ reader | Finds each section by an index of the file (`cpp:870`, `cpp:1750-1801`), so the order does not matter. |

Example: a run of `valid_1_5_1.seq` with its sections in the order
`[DEFINITIONS]`, `[BLOCKS]`, `[VERSION]`, `[RF]`, `[GRADIENTS]`, `[TRAP]`,
`[ADC]`, `[EXTENSIONS]` with its extension sections, and `[SHAPES]`, and with no
`[SIGNATURE]`: `spec` and the C++ reader accept it. The same file with
`[VERSION]` as the last section made the C++ reader crash in the run
(`tests/seqfiles/undefined/version_last.seq` is such a file).

`spec`: reads the sections in any order (`undefined/version_last.seq` is read).

Reason: the specification is silent on the order, and `spec` accepts any. The
C++ reader's failure with `[VERSION]` last comes from its stream, not from a
rule of the format (D2.2).

The same condition in `cpp-siemens`: [D5.1](../packages/pulseq-cpp-siemens/docs/specification.md#d51-a-block-uses-a-shape-that-the-reader-did-not-read)

#### D2.2: The last section with no blank line after it

| Source | What it does |
|---|---|
| Specification | Silent. It declares the end of a shape with a blank line (section 2.9, `spec:602`) and says nothing about a blank line after another section, or about the end of the file. |
| C++ reader | Reads a table with its `getline` up to an empty line or a `[` line. At the end of the file, `is.get()` sets the failbit of the stream (`cpp:2301`), and `getline` also seeks to -1 when it has read nothing (`cpp:2322-2326`). So a section that runs to the end of the file, with no blank line after its last row, leaves the stream failed, and the reader skips each section that it reads after it, in its own order: `[VERSION]` (`cpp:877`), `[SHAPES]` (`cpp:933`), `[RF]`, `[GRADIENTS]`, `[TRAP]`, `[ADC]`, `[DELAYS]`, `[EXTENSIONS]` (`cpp:999-1204`), `[DEFINITIONS]` (`cpp:1399`), `[BLOCKS]` (`cpp:1550`), `[SIGNATURE]` (`cpp:1602`). Only `[SHAPES]` resets the stream, after it has read the section (`cpp:980`). |

Example: a 1.5.1 file with `[VERSION]`, `[DEFINITIONS]`, `[BLOCKS]` (two blocks,
the first with a trapezoid) and `[TRAP]` as the last section, with no `[SHAPES]`
section. If the last row of `[TRAP]` has no blank line after it (a newline or
none, which is the same to the reader), the C++ reader skips `[DEFINITIONS]` and
rejects the file ("Required: definition AdcRasterTime is not present"); `spec`
reads it. With a blank line after the row, both read it. A `[SHAPES]` section
before `[TRAP]` does not help: the reader resets the stream after `[SHAPES]`, and
reads `[TRAP]` later. A `[SHAPES]` section after `[TRAP]` makes `[SHAPES]` the
last section, which ends the file and resets the stream: the file is read. With
`[DEFINITIONS]` as the last section the reader reads the definitions and then no
block: the file is read as a sequence of 0 blocks, with no error. With
`[BLOCKS]` last, the file is read (only `[SIGNATURE]` comes after it).
`[VERSION]` as the last section is D2.1.

Writers: MATLAB Pulseq and pypulseq end every section with a blank line
(`write.m:25-259`, `write_seq.py:14-265`) and write `[SIGNATURE]` last, which
the reader reads last. So no file that they write is affected.

`spec`: reads the sections by name, and needs no blank line at the end of a
section other than a shape (D3.11): `valid_last_section_no_blank.seq`, whose last
section `[TRAP]` ends with no line end, is read (the C++ reader rejects it).

Reason: the C++ reader's loss comes from the state of its stream, not from a
rule of the format. The specification declares the end of a shape with a blank
line, and of no other section, so `spec` does not follow the C++ reader here.

#### D2.3: [EXTENSIONS] as the last section

| Source | What it does |
|---|---|
| Specification | Silent on the order of the sections. |
| C++ reader | Reads `[EXTENSIONS]` up to the next section header of its index, and rejects the file when there is none: "failed find the end of the section while reading EXTENSIONS" (`cpp:1202-1211`). Its index has only the lines that start with `[` (`cpp:1762-1769`), so the `extension` sections after `[EXTENSIONS]` do not end it. |

Example: `tests/seqfiles/oracle/koma_v1.5_unknown_ext.seq` ends with its
`extension` sections and has no `[SHAPES]` or `[SIGNATURE]`. Runs: the C++
reader rejects it; the same file with `UNKNOWN1` and `UNKNOWN2` renamed to
`LABELSET` and `LABELINC` is rejected with the same message; each of the two is
accepted with a `[SIGNATURE]` section added at the end.

`spec`: accepts (`oracle/koma_v1.5_unknown_ext.seq` is read).

Reason: the specification does not set an order of the sections. The reader
rejects this file because of how it finds the end of `[EXTENSIONS]`, not because
of a rule of the format, so `spec` does not follow it here. Both writers write
`[EXTENSIONS]` before `[SHAPES]` and `[SIGNATURE]` (`write.m:153`, `write.m:250`,
`write.m:282`; `write_seq.py:181`, `write_seq.py:245`, `write_seq.py:265`), so a
file of theirs ends with `[EXTENSIONS]` only when it has no shape and no
signature.

#### D2.4: A section that the format does not have

| Source | What it does |
|---|---|
| Specification | Lists the sections (sections 2.3 to 2.9). It has no rule for another. |
| C++ reader | Indexes every `[` line (`cpp:1762-1769`) and reads only the sections that it knows: it ignores another (matrix: accepts). |

Example: `tests/seqfiles/bad_section_unknown.seq` has `[FOO]`.

`spec`: ignores the section (`bad_section_unknown.seq` is read).

Reason: the specification lists its sections and has no rule for another one;
the user chose to ignore it (section 6 of the plan), as the C++ reader does.
pulseq-checks reports it.

#### D2.5: A blank or # line inside a section

| Source | What it does |
|---|---|
| Specification | "Comments are specified by a line starting with a hash" (section 2.1, `spec:171`). It does not say whether a blank line or a comment can be inside a section, except in `[SHAPES]` (D3.11). |
| C++ reader | Its line reader keeps white space (`cpp:2295-2342`). A table ends at an empty line or a `[` line (`cpp:1004`, `cpp:1064`, `cpp:1112`, `cpp:1141`, `cpp:1558`). A `#` line inside a table is read as a row, and its decoding fails: reject. `[VERSION]` and `[EXTENSIONS]` skip blank and `#` lines (`cpp:878`, `cpp:908`, `cpp:1219`). It never reads a line after the end of a table: only `[` lines start a section (`cpp:1762-1769`). |

Example: `tests/seqfiles/bad_syntax_line_after_comment.seq` has a `#` line after the
first row of `[BLOCKS]`, and the other rows after it: the C++ reader rejects it
(it decodes the `#` line as a block). `valid_comments_between_sections.seq` has
comments between sections: the C++ reader accepts it.

`spec`: skips a blank or `#` line anywhere: between sections, inside a table
(`bad_syntax_line_after_comment.seq` is read, with all its blocks) and inside a
shape, where a `#` line is skipped and a blank line ends the shape (D3.11;
`valid_comment_in_shape.seq`).

Reason: the specification makes a comment of any line that starts with a hash
(spec:171), and gives no rule that a blank line ends a table; the user chose to
skip both (section 6 of the plan).

#### D2.6: A definition that appears twice

| Source | What it does |
|---|---|
| Specification | Silent ("a list of user-specified key/value pairs", `spec:240`). |
| C++ reader | A map: the last line wins (`cpp:1432`, `cpp:1445`). |

Example: `tests/seqfiles/bad_definitions_duplicate.seq` has `Name` twice (the C++
reader accepts it).

`spec`: the last definition wins (`bad_definitions_duplicate.seq` has `Name
again`).

Reason: the specification is silent; the user chose the last, as the C++ reader
does (section 6 of the plan).

#### D2.7: A definition or a signature hash whose text reads as a number

| Source | What it does |
|---|---|
| Specification | `<value>` has the type "any" (section 2.5, `spec:247`); `Hash` is a "string" in hexadecimal (section 2.4, `spec:230`). |
| C++ reader | Keeps the text of each definition and its numbers (`cpp:1432`, `cpp:1445`), and the hash as text (`cpp:1618`, `cpp:1631`). |

Example: `Hash 12345678901234567890123456789012`, a hex digest with no letter.
A double cannot hold its 32 digits.

`spec`: the tokens of each definition as text (`SequenceData.definitions`); only
the four rasters are numbers (`Rasters`). The hash is text.

Reason: the package does not convert the text of a definition to a float. The
example shows why: a double cannot hold the 32 digits of such a hash. The C++
reader keeps the text too.

The same condition in `cpp-siemens`: [D7.1](../packages/pulseq-cpp-siemens/docs/specification.md#d71-definitions-as-text)

#### D2.8: An RF magnitude sample below 0

| Source | What it does |
|---|---|
| Specification | Allows [-1, 1] for an amplitude shape (`spec:624`). |
| C++ reader | Sets a negative sample to 0 (`cpp:2287`), with no message. |

Example: `tests/seqfiles/bad_shape_rf_magnitude_negative.seq` has a magnitude
sample of -0.5. The C++ dump has 0 for it (run).

`spec`: plays a negative magnitude as written
(`bad_shape_rf_magnitude_negative.seq` is read: the sample -0.5 is a magnitude of
0.5 with a phase of π).

Reason: the specification allows [-1, 1] for an amplitude shape (spec:624), and
the magnitude shape of an RF event is one, so `spec` plays it as written, a
signed amplitude. Both writers write the magnitude as an absolute value
divided by its maximum, so a file of theirs has no sample below 0
(`Sequence.m:584-586`; `block.py:832-834`).

#### D2.9: An RF phase sample outside [0, 1)

| Source | What it does |
|---|---|
| Specification | Silent on the range of the phase shape. |
| C++ reader | Multiplies the phase by 2π (`cpp:2005`) and clamps it to [0, 2π - 1e-4] (`cpp:2288-2289`), with no wrap and no message. |

Example: `tests/seqfiles/bad_shape_rf_phase_range.seq` has a phase of 1.5 turns
(3π rad, the same as π). The C++ dump has 6.28308535 rad (2π - 1e-4) for each
sample (run): the scanner plays about 0 rad where the file says π.

`spec`: plays the phase as written: 2π times the value, with no wrap and no clamp
(`bad_shape_rf_phase_range.seq` is read: a phase of 1.5 turns is the waveform of
0.5 turns).

Reason: the specification is silent on the range of the phase; `spec` plays the
phase that the file gives (section 6 of the plan). Both writers write the phase as
a fraction of a turn in [0, 1) (`Sequence.m:587-589`; `block.py:838-840`), which
is what `spec` reads.

#### D2.10: An RF time shape whose times are (i + 0.5) d: cells

![What the C++ reader plays and what `spec` reads, for three RF time shapes](figures/discrepancy-rf-time-shapes.svg)

The figure (D2.10 to D2.12) is made from the outputs of the readers (the
appendix). Each panel is one RF event of amplitude 1000 Hz with a Hann
magnitude, except the bottom one (its magnitudes are in D2.11). The steps are the
samples of the C++ dump, each for one dwell time, and the crosses are the
package's `RfEvent.t` and `RfEvent.magnitude`, which is what `spec` reads. From
the top: a regular time shape on its cell centres (`1 2 2 17`), a regular time
shape whose first time is not half a step (`10 1 1 17`), and an uncompressed
time shape (`1 2 4 7 10`).

| Source | What it does |
|---|---|
| Specification | The time shape gives "the time sampling points, specified in the units of `RadiofrequencyRasterTime`" (section 2.8.1, `spec:349`). |
| C++ reader | Takes a time shape that is stored compressed in 3 or 4 values as regular: the dwell time is the second stored value times the RF raster, and it does not decompress the shape (`cpp:2015-2021`). It keeps only the samples and the dwell time (`cpp:2063-2067`), so the first time of the shape is not used. |

Example: the top panel, the regular time shape `1 2 2 17` of 20 samples (times
1, 3, …, 39 µs): `spec` and the C++ reader hold each sample for one dwell of 2
µs around its time. The middle panel, the time shape `10 1 1 17` of 20 samples
(times 10, 11, …, 29 µs): the C++ reader plays the samples from 0 to 20 µs, and
`spec` puts them at 10 to 29 µs (D2.11). The fixture
`tests/seqfiles/bad_shape_rf_time_grid.seq` has `1 1 98` (times 1 to 100 µs,
which the reader plays at 0.5 to 99.5 µs); matrix: the C++ reader accepts it.
`valid_rf_time_shapes.seq` has an uncompressed time shape `0.5 1.5 2.5`: the C++
reader resamples it, and the macOS build crashes (`tests/test_cpp_oracle.py`).

`spec`: a time shape whose times are `(i + 0.5) d` (2 or more samples, equal
steps, the first half a step, within `model.TIME_TOLERANCE`) is cells of `d`:
each sample is held for one dwell around its time, from the start of the pulse,
and the pulse lasts `N d` (`model.rf_time_step`, `events.RfEvent.dwell`). Any
other time shape is points (D2.11). `bad_shape_rf_time_grid.seq` (`1 1 98`,
times 1 to 100 µs) is read as points: the C++ reader plays it as cells from 0,
half a µs earlier. `valid_rf_time_shapes.seq` has a step of 2 µs (`1 2 2 47`) and
a short pulse of cells stored uncompressed (`0.5 1.5 2.5`), both cells.

Reason: the slide set that section 2.6 of the specification cites places the
samples of a regularly sampled RF pulse at the centres of their dwell periods,
from the start of the pulse (slide 9), so a shape whose first time is not half a
step cannot be a regular pulse: it is a pulse "defined by vertices" (slide 9).
That a shape of the form `(i + 0.5) d` is a regular pulse, and not points at
those times, is the user's choice. The makers of both writers that build a pulse
from N samples put the sample i at `(i - 0.5)` dwell (`makeArbitraryRf.m:70`,
`makeSincPulse.m:75`; `make_arbitrary_rf.py:114`, `make_sinc_pulse.py:113`); the
one maker that does not, `make_sigpy_pulse` of pypulseq (`t = i` rasters in
`make_slr` and `make_sms`, `make_sigpy_pulse.py:226`, `make_sigpy_pulse.py:278`,
passed on at `make_sigpy_pulse.py:152`), gives points that `spec` reads as such. MATLAB Pulseq writes the regular time shape as time ID 0 when it
has more than 4 samples (`0.5 1 1 N-3`, `Sequence.m:607-609`) and as a time shape
of N values otherwise, since `compressShape` does not compress a shape of 4
samples or fewer (`compressShape.m:20-24`); pypulseq writes it as time ID 0
(`block.py:858-861`). The split does not depend on how the shape is stored: the
specification makes storage only a matter of compression (spec:602), and the C++
reader's split by storage reads a pulse of 4 samples or fewer, which a writer
stores uncompressed, past its end (D2.11). pulseq-checks reports where the C++
reader plays a shape otherwise.

#### D2.11: Any other RF time shape: points

| Source | What it does |
|---|---|
| Specification | As D2.10. |
| C++ reader | Resamples the pulse to the RF raster (`cpp:2022-2050`): `int(0.5 + t_last)` cells; in cell `c` the index goes to the next sample when the time of the sample at the index is below `c + 1`, and the cell plays the sample at the index. The index can reach the number of samples, one past the last stored sample (`cpp:2039-2045`): for such a shape the loop reads after the end of the stored samples. |

Example: the bottom panel, an uncompressed time shape 1, 2, 4, 7, 10 µs with
magnitudes 0.2, 0.6, 1, 0.6, 0.2. `spec` has each sample at its time; the C++
reader plays 10 cells of 1 µs: 0.2, 0.6, 1, 1, 0.6, 0.6, 0.6, 0.2, 0.2, 0.2
(times 1000 Hz). The fixture `tests/seqfiles/bad_shape_rf_time_end.seq` has the
time shape 0, 99.6: the loop reads past the 2 stored samples; matrix: the macOS
build of the C++ reader crashes (the Linux build accepts the file).

`spec`: any other time shape is points at its times, joined by straight lines of
the complex signal: the linear interpolation of its real and imaginary parts
(`events.RfEvent.signal`). The pulse ends at its last time (D2.12). The points
need not be on the edges of the RF raster: `bad_shape_rf_time_end.seq` (0, 99.6)
is read, a straight line from 0 to 99.6 µs. The block pulse of both writers
(`0 N`) is points, a flat line (`makeBlockPulse.m:73`, `make_block_pulse.py:102`).
A time shape of one sample, times that do not increase, or a first time below 0
are `shape.time-order` (D3.9).

Reason: the specification gives the times only as "the time sampling points"
(spec:349); the slide set calls such a pulse one "defined by vertices" (slide 9),
whose points need not be on the raster edges (slide 4), and draws the vertices of
gradients joined by straight lines (slides 5 to 8). The user chose the straight
line of the complex signal, which the C++ reader names as its intent and does not
do (its FIXME, `cpp:2033`: "convert to complex, use linear interpolation and
convert back to magnitude&phase").

The same condition in `cpp-siemens`: [D5.8](../packages/pulseq-cpp-siemens/docs/specification.md#d58-the-rf-resampling-reads-past-the-samples), [D5.9](../packages/pulseq-cpp-siemens/docs/specification.md#d59-an-rf-time-shape-whose-last-time-does-not-fit-an-int)

#### D2.12: Where an RF pulse with a time shape ends

| Source | What it does |
|---|---|
| Specification | Silent on the end of a pulse with a time shape. |
| C++ reader | `shape_dur` is the dwell time times the number of samples (`cpp:2063`); for a time shape that it resamples, the samples are the resampled cells (`cpp:2031`, `cpp:2048-2049`). |

Example: the top panel of the figure, the regular time shape `1 2 2 17` (20
samples, times 1, 3, …, 39 µs): `spec` and the C++ reader end the pulse at 40
µs, so with a block of 39 µs the pulse does not fit in either. The fixture
`bad_shape_rf_time_end.seq` (time shape 0, 99.6): `spec` ends the pulse at 99.6
µs; the C++ reader resamples to `int(0.5 + 99.6)` = 100 cells of 1 µs and ends it
at 100 µs (`cpp:2031`, `cpp:2063`).

`spec`: a pulse of cells lasts `N d`, as in the C++ reader; a pulse of points ends
at its last time, as the block pulses of both writers set it
(`makeBlockPulse.m:79`, `make_block_pulse.py:109`). `RfEvent.shape_dur` and the
end that `block.event-too-long` checks are these.

Reason: `spec` uses the end that the slides give a regular pulse (N dwell periods
from its start, slide 9) and the last vertex of a pulse of vertices.

#### D2.13: An arbitrary gradient between its samples (time ID 0)

![The lines of spec and of the C++ reader between the samples of an arbitrary gradient](figures/discrepancy-arbitrary-gradient-edges.svg)

The figure (D2.13) is made from the outputs of the readers (the appendix): the
samples of the half sine of the example, as open circles; the line of `spec`
between them and to `first` and `last` at the edges; and the waveform that the
C++ reader's `gradientsAt` gives (dashed). The dotted lines are the edges of the
gradient raster.

| Source | What it does |
|---|---|
| Specification | The samples are at the centres of the raster cells (section 2.6, `spec:290`). Silent between them. |
| C++ reader | `gradientsAt` interpolates linearly between the samples, from `first` at the start to the first sample and from the last sample to `last` at the end (`cpp:3653-3693`). |

Example: the figure: the samples of the half sine of D4.4 in a 1.5.1 file with
`first` and `last` 0. `spec` and the C++ reader draw straight lines between the
samples, and to `first` and `last` at the edges.

`spec`: straight lines between the sample centres, and to `first` and `last` at
the edges (`seq_utils.gradient_offsets`).

Reason: the specification puts the samples at the centres of the cells (spec:290)
and is silent between them; the user chose straight lines, to `first` and `last`
at the edges, as the C++ reader draws them (section 6 of the plan), and as the
slide set draws them (slide 7). Layer 1 does not guess.

#### D2.14: A gap between two gradient events on one axis

| Source | What it does |
|---|---|
| Specification | Silent on the waveform between events. |
| C++ reader | `gradientsAt` works inside one block (`cpp:3561-3566`); it does not join blocks. |

Example: a run of a 1.5.1 file of three blocks: a gradient from 0 to
30000 Hz/m (0 to 30 µs), a delay of 40 µs, a gradient from 15000 Hz/m to 0
(70 to 100 µs). What the waveform is between 30 µs and 70 µs is the question.
[`docs/implementation.md` §1.3](implementation.md#13-the-gaps) has the figure
of the four cases, `figures/waveform-gaps.svg`.

`spec`: 0 where no gradient event plays: with `gradient.nonzero-start-delay` and
`gradient.nonzero-end-align` (which the specification states, `spec:420`), every
gap inside a block lies between zeros. The waveform across blocks comes with task
R14; today's waveform code draws MATLAB's ramps (`docs/implementation.md` §1.3).

Reason: a gap inside a block lies between zeros (those rules), and the waveform
across blocks is task R14's.

The same condition in `cpp-siemens`: [D7.4](../packages/pulseq-cpp-siemens/docs/specification.md#d74-gradients_at-between-blocks-and-after-a-blocks-end)

#### D2.15: An ADC phase modulation shape: rad, one value per sample

| Source | What it does |
|---|---|
| Specification | "Shape ID of the phase modulation", with no unit (section 2.8.3, `spec:443`). |
| C++ reader | Uses the decompressed shape as radians: its multiplication by 2π is commented out (`cpp:3059-3060`). |

Example: `tests/seqfiles/valid_1_5_1.seq`, ADC 2 with phase shape 8.

`spec`: `AdcEvent.phase_modulation` is the decompressed shape in rad, one value for
each ADC sample; a shape of another length is `shape.event-length` (D3.8;
`bad_shape_adc_phase_length.seq`).

Reason: the specification gives the shape no unit (spec:443), and its table of
revisions gives the ADC a "phase offset per sample as a vector" (spec:120). The
C++ reader uses the shape as radians; the user chose rad for `spec` too, one
value for each ADC sample (section 6 of the plan).

The same condition in `cpp-siemens`: [D7.6](../packages/pulseq-cpp-siemens/docs/specification.md#d76-the-adc-phase-shape-as-stored)

#### D2.16: A soft delay offset with a fraction, or a long hint

| Source | What it does |
|---|---|
| Specification | Gives an example with the comment `# id num offset factor hint` and the units `us` for the offset; the offsets of the example are integers (section 2.8.4, `spec:550-558`). It has no table of types. |
| C++ reader | Reads `%d%d%d%f` (`cpp:1330`), so an offset with a fraction is cut and the rest is read as the factor. It keeps the first 31 characters of the hint (`cpp:1334-1335`, `cpp.h:194`). |

Example: a run of a 1.5.1 file with the soft delay row `1 0 -100.5 1 TE`. The C++
dump has offset -100 µs, factor 0.5 and hint `1 TE`. `spec` reads offset
-100.5 µs, factor 1 and hint `TE`.

`spec`: the offset is a float (µs), and the hint is the whole text
(`valid_soft_delay_fraction.seq`: -100.5 µs).

Reason: the example of the specification has integer offsets and no table of
types; the user chose a float (section 6 of the plan), as the binary format
stores it (a time in ps, spec:723). MATLAB Pulseq writes the offset in µs with
`%g` (`write.m:214-215`), so a fraction can reach the file; pypulseq rounds it
to a whole µs (`write_seq.py:235`, `write_seq.py:239`).

#### D2.17: An unknown extension that the file does not require

| Source | What it does |
|---|---|
| Specification | "The interpreter MUST detect unknown extensions and MAY chose to ignore them. It is recommended that the interpreter issues a warning in this case." (section 2.8.4, `spec:460`) |
| C++ reader | A warning for the header and a message for each row, and goes on (`cpp:1245-1249`, `cpp:1375-1377`). Run: `oracle/koma_v1.5_unknown_ext.seq` with a `[SIGNATURE]` section added after its extensions: accepts. |

Example: `tests/seqfiles/oracle/koma_v1.5_unknown_ext.seq` (UNKNOWN1, UNKNOWN2).
`valid_1_5_1.seq` and most `bad_*` fixtures have an extension UNKNOWN.

`spec`: reads the section and does not interpret it; its `STRING_ID` is in
`SequenceData.skipped_extensions` (`valid_1_5_1.seq`: `UNKNOWN`), and
`SequenceData.records` has a `model.Record` (`"extension"`, reason `"unknown"`).
An extension that the version of the file does not have yet is D4.6.

Reason: the specification allows a reader to ignore an unknown extension that
the file does not require (spec:460). `spec` reads such a section and does not
interpret it, as the C++ reader does.

#### D2.18: A rotation quaternion: divided by its norm

| Source | What it does |
|---|---|
| Specification | A rotation is "a normalized rotation quaternion" applied to the whole block (section 2.8.4, `spec:567`). |
| C++ reader | Rejects a quaternion whose norm is more than 1e-3 from 1, and divides the others by their norm (`cpp:1286-1292`). `GetBlock` attaches the block's first rotation (`cpp:1871-1879`), in any version of the file. It never rotates the gradients: `gradientsAt` does not read the rotation (`cpp:3558-3698`), and its helper `rotate_vec3_by_quat` (`cpp:2666-2684`) turns only the position offsets, with the conjugate rotation (`cpp:3024`). It leaves the rotation to the scanner's interpreter. |

Example: runs of a 1.5.1 file whose block plays the rotation `1 1.01 0 0 0`: the
C++ reader rejects it, `spec` reads it. With `1 1.0005 0 0 0` the C++ reader
accepts it. `tests/seqfiles/oracle/pulseq_make_radial.seq` and
`koma_v1.5_rotation_radial_tiny.seq` have rotations.

`spec`: from 1.5.1, divides each quaternion by its norm
(`SequenceData.extensions.rotations`; `1 1.01 0 0 0` reads as `1 0 0 0`); a
quaternion of norm 0 is `rotation.zero` (D3.10). Its
decoding rotates the gradients of each block with a rotation by its quaternion
(`SpecDecoding.gradients_at`, with the package's `decoding.rotate`, the active
rotation in float64; `SpecDecoding.rotations` gives the blocks and their
quaternions), as the specification describes (spec:567). It applies the content
of the file, so it has no setting and no warning: `rotation_record` has the
setting `"apply"` (P20, rules 2 and 4). It agrees with
`CppSiemens(rotation="apply")` of the plugin `cpp-siemens` to float32 precision,
on each fixture with rotations from 1.5.1. The measurements do not support
rotations yet (task R14).

Reason: the specification describes a normalized rotation quaternion applied to
the whole block, from revision 1.5.1 (spec:567); `spec` applies it from that
revision (rule 2 of P20) and normalizes each quaternion, as the C++ reader does.
MATLAB Pulseq registers a quaternion only if its squares sum to 1 within 1e-6
(`Sequence.m:802-806`), and pypulseq writes no rotation extension
(`write_seq.py:14-265` has no such section), so a quaternion in a file of the
writers is normalized, to the precision of the text. pulseq-checks reports a
norm far from 1. `load` refuses a sequence with the rotation extension
(`extensions.refuse_rotations`) until it runs on the interpreters (task R14).

The same condition in `cpp-siemens`: [D6.2](../packages/pulseq-cpp-siemens/docs/specification.md#d62-a-block-that-plays-a-rotation)

#### D2.19: A label that the specification does not list

| Source | What it does |
|---|---|
| Specification | Lists the counters and flags that "are supported at the moment" (section 2.8.4, `spec:519-520`). |
| C++ reader | `decodeLabel` returns "unknown"; the reader prints a message and leaves the label out (`cpp:1302-1310`). |

Example: a run of a 1.5.1 file with `extension LABELSET 1` and the row
`1 3 FOO`: `spec` and the C++ reader accept it.

`spec`: keeps the name as text (`Extensions.labelset`), and records a label that
the specification does not list in `SequenceData.records` (`"label"`, reason
`"unknown"`; `valid_label_unknown.seq`: `FOO`). So is `NOSCL`, the spelling of the
C++ reader (`cpp:825`) and of both writers (`getSupportedLabels.m:17`,
`supported_labels_rf_use.py:31`) for the flag that the specification spells
`NOSLC` (spec:520).

Reason: the specification lists the labels "supported at the moment"
(spec:519-520); `spec` keeps an unknown one, since labels do not change the
waveforms (section 6 of the plan).

### D3. The specification is silent, and `spec` rejects the file by choice

#### D3.1: A byte that is not UTF-8

| Source | What it does |
|---|---|
| Specification | Silent: it gives no encoding of the file. |
| C++ reader | Does not check the encoding (matrix: accepts `bad_syntax_encoding.seq`). |

Example: `tests/seqfiles/bad_syntax_encoding.seq` (a byte 0xB5 in a comment).

`spec`: `syntax.encoding`.

Reason: the specification gives no encoding, and the text of the model must be
UTF-8 (the user's choice; the message says so). The fixed text that both writers
write is ASCII (`write.m` and `write_seq.py` have no other byte). The text of a
definition or of a soft delay hint is the script's, and is written as it is:
pypulseq opens the file with the encoding of the locale (`write_seq.py:52`) and
hashes it as UTF-8 (`write_seq.py:258-261`), and MATLAB Pulseq opens it with no
encoding (`write.m:17`). Not checked: which bytes either writer writes for text
outside ASCII.

#### D3.2: A data line before the first section

| Source | What it does |
|---|---|
| Specification | Silent: it has no line outside a section, except a comment (`spec:171`). |
| C++ reader | Accepts: the row is never read, because only `[` lines start a section (`cpp:1762-1769`). |

Example: `tests/seqfiles/bad_syntax_line.seq` has a row `1 2 3` before the first
section (matrix: the C++ reader accepts).

`spec`: `syntax.line`.

Reason: a data line before the first section is in no section: the specification
has no such line, so `spec` rejects it (the user's choice; the message says
so). Both writers start the file with two comment lines and a blank line, then
`[VERSION]` (`write.m:19-25`, `write_seq.py:53-56`), and put only comments and
blank lines between sections.

#### D3.3: A section that appears twice

| Source | What it does |
|---|---|
| Specification | Silent. |
| C++ reader | Its index keeps the position of the last header with a name (`cpp:1768`), so it reads the last section of that name: accepts. |

Example: `tests/seqfiles/bad_section_duplicate.seq` has a second `[TRAP]` (the C++
reader reads the second only).

`spec`: `section.duplicate` for a section that appears twice, `[VERSION]` and
`[SIGNATURE]` included (`bad_section_duplicate.seq`,
`bad_section_duplicate_signature.seq`), and for two `extension` sections with one
`STRING_ID` (`bad_section_duplicate_extension.seq`); only the first copy is read.

Reason: the specification is silent, and a second copy of a section has no one
meaning (the C++ reader reads the last copy only), so `spec` rejects the file (the
user's choice, 2026-10-13, which replaced the reading of the copies as one; the
message says so). Both writers write each section once, in one block of code
(`write.m:25-282`, `write_seq.py:56-277`).

#### D3.4: A block ID used twice

| Source | What it does |
|---|---|
| Specification | States that IDs are positive and unique for shapes and for the events of one class (section 2.2, `spec:181-183`). It does not state it for blocks, which nothing refers to. |
| C++ reader | Does not use the block ID (`cpp:1565`, `cpp:1586`): accepts (matrix). |

Example: `tests/seqfiles/bad_id_unique_block.seq` (block ID 2 twice).

`spec`: `id.unique`, also for a block ID used twice.

Reason: the specification does not state the rule for blocks, and `spec`
rejects a block ID used twice because both writers number the blocks 1, 2, …
(`write.m:61-68`; `write_seq.py:88-99`, with `next_free_block_ID` from 1,
`sequence.py:81`, `sequence.py:198-199`); the message says that this is the
package's choice.

#### D3.5: NaN or infinity in a float column

| Source | What it does |
|---|---|
| Specification | Types the columns as floats (tables of section 2.8) and does not say whether NaN and infinity are floats of the file. |
| C++ reader | Reads `nan` with `sscanf` (matrix: accepts `bad_syntax_number.seq`). |

Example: `tests/seqfiles/bad_syntax_number.seq` (`nan`).

`spec`: `syntax.number` for a value that is not a number and for NaN or infinity
in a float column.

Reason: the specification does not say whether NaN and infinity are floats of the
file, so `spec` rejects them (the user's choice; the message says so). Both
toolboxes refuse a shape sample that is not finite (`compressShape.m:16-18`,
`compress_shape.py:27-28`). For the other columns, the toolboxes differ (runs of
2026-10-13): MATLAB Pulseq wrote `NaN` in `[TRAP]` for a trapezoid of amplitude
NaN, and in the frequency offset of `[RF]` for a block pulse with a frequency
offset NaN, while it refused an amplitude of infinity; pypulseq failed on both
(`make_trapezoid.py:212`, `event_lib.py:282`). So the rejection does not rest on
what the writers write: `spec` keeps it because NaN and infinity give no waveform,
and MATLAB Pulseq writes NaN only when a script passes it (the user, 2026-10-13).
The message of `syntax.number` still gives the writers as the reason; a
follow-up task changes it.

#### D3.6: A negative time or count

| Source | What it does |
|---|---|
| Specification | Stores integers as unsigned (section 2.1, `spec:176`), and defines negative values elsewhere: the time ID -1, a soft delay offset. |
| C++ reader | Reads a negative delay with `sscanf` (matrix: accepts `bad_syntax_negative.seq`). |

Example: `tests/seqfiles/bad_syntax_negative.seq` (a delay of -10).

`spec`: `syntax.negative` for a negative block duration, delay, rise, flat or fall
time, number of samples, dwell time or trigger duration.

Reason: this is not literally the specification (spec:176 stores integers as
unsigned, but the specification defines negative values elsewhere), and a
negative time or count has no waveform, so `spec` rejects it (the user's choice;
the message says so). The toolboxes do not check the sign of a time in their
makers: in runs of 2026-10-13, `makeTrapezoid` of MATLAB Pulseq wrote a delay of
-10 µs, and a flat time of -10 µs, in `[TRAP]`, and `make_trapezoid` of pypulseq
wrote the delay of -10 µs. So a script that passes a negative time gets a file
with it, and the rejection does not rest on what the writers write: `spec` keeps
it because a negative time or count gives no waveform (the user, 2026-10-13).
The message of `syntax.negative` still gives the writers as a reason; a
follow-up task changes it. The number of samples of a shape is the length of an array in both
(`compressShape.m:21`, `compressShape.m:53`; `compress_shape.py:32`,
`compress_shape.py:59`), so it is never negative.

#### D3.7: An event that uses a shape with no sample

| Source | What it does |
|---|---|
| Specification | Silent. |
| C++ reader | Undefined behaviour: it takes `&waveform[0]` of an empty vector and copies from `samples.front()` of an empty vector (`cpp:1995`, `cpp:2203`). The macOS build crashes (matrix, `bad_shape_empty.seq`); the Linux build accepts the file. |

Example: `tests/seqfiles/bad_shape_empty.seq` has `num_samples 0` for the
magnitude and phase of an RF event.

`spec`: `shape.empty`, for a shape that any event uses (an RF, gradient or ADC
phase shape).

Reason: the specification is silent; an event with no samples has no waveform,
so `spec` rejects it (the user's choice; the message says so). The C++ reader's
behaviour depends on the build. The writers do not write such an event in the
runs of 2026-10-13: MATLAB Pulseq failed on an arbitrary RF and on an arbitrary
gradient with no sample, pypulseq failed on both (`calc_rf_center.py:29`,
`make_arbitrary_grad.py:90`), and an ADC with no phase modulation gets no shape
(`Sequence.m:713-714`; `block.py:584-585`). Not checked: an event built by hand,
with no maker.

The same condition in `cpp-siemens`: [D5.6](../packages/pulseq-cpp-siemens/docs/specification.md#d56-an-event-that-uses-a-shape-with-no-sample)

#### D3.8: The shapes of one event with different numbers of samples

| Source | What it does |
|---|---|
| Specification | Silent. It pairs the magnitude, phase and time of an RF event by sample (`spec:349`), and gives the ADC a "phase offset per sample" (`spec:443`, `spec:120`). |
| C++ reader | RF: crash (matrix). `checkRF` reads the phase at each index of the magnitude (`cpp:2284-2290`). A gradient with a time shape: rejects when the shapes differ in length (`cpp:2190-2192`). ADC phase shape: accepts (matrix, `bad_shape_adc_phase_length.seq`). |

Example: `tests/seqfiles/bad_shape_event_length.seq`: an RF event with a magnitude
of 100 samples and a phase of 8. `bad_shape_adc_phase_length.seq`: an ADC phase
shape whose length is not the number of ADC samples.

`spec`: `shape.event-length`: the magnitude, phase and time shapes of an RF event;
the waveform and the time shape of an arbitrary gradient; and an ADC phase shape
whose length is not the number of ADC samples (D2.15).

Reason: the specification pairs the magnitude, phase and time of an RF event by
sample (spec:349) and says nothing of other lengths; some samples would have no
partner, so `spec` rejects such an event (the user's choice; the message says
so). Both writers take the magnitude and the phase of an RF event from one signal
(`Sequence.m:584-589`; `block.py:832-840`), and its times from the number of its
samples (`makeArbitraryRf.m:68-74`, `makeBlockPulse.m:73`;
`make_arbitrary_rf.py:112-114`, `make_block_pulse.py:102`); their makers refuse an
ADC phase modulation of another length (`makeAdc.m:124-126`, `make_adc.py:79-80`)
and an extended trapezoid with times and amplitudes of different lengths
(`makeExtendedTrapezoid.m:42-43`, `make_extended_trapezoid.py:81-82`).

The same condition in `cpp-siemens`: [D5.7](../packages/pulseq-cpp-siemens/docs/specification.md#d57-an-rf-phase-shorter-than-its-magnitude)

#### D3.9: An RF time shape of one sample, or times that do not increase or start below 0

| Source | What it does |
|---|---|
| Specification | Gives the times only as "the time sampling points" (`spec:349`; for a gradient `spec:395`). |
| C++ reader | Resamples any time shape that is not stored in 3 or 4 values as in D2.11 (`cpp:2022-2050`), and does not check that the times increase or start at 0 or later (matrix: accepts `bad_shape_time_order.seq`). |

Example: `tests/seqfiles/bad_shape_time_order.seq` has an RF time shape of 100
samples that decrease, 100, 99, …, 1.

`spec`: `shape.time-order` for an RF time shape of one sample, an RF time shape
whose first time is below 0, and a time shape (of RF or of a gradient) whose
times do not increase.

Reason: a time shape of one sample defines no step and no line, and times that do
not increase or start before the event define no waveform, so `spec` rejects
them (the user's choice; the message says so). The makers of both writers give
times that increase: `(i - 0.5)` dwell, or `0` and `N` for a block pulse
(`makeArbitraryRf.m:70`, `makeBlockPulse.m:73`; `make_arbitrary_rf.py:114`,
`make_block_pulse.py:102`), and refuse an extended trapezoid whose times do not
increase (`makeExtendedTrapezoid.m:50-51`, `make_extended_trapezoid.py:87-88`).
A time shape of one sample is the exception: MATLAB Pulseq writes one for an
arbitrary pulse of one sample (`makeArbitraryRf.m:68-74`, `Sequence.m:607-614`;
run of 2026-10-13: a pulse of one sample with a dwell of 10 µs gives a time
shape of one sample, with the value 5), where pypulseq fails on a signal of one sample
(`make_arbitrary_rf.py:105-112`). So the rejection of a time shape of one sample
does not rest on what the writers write. The user decided (2026-10-13) that
`spec` reads a time shape of one sample `t0` above 0 as one cell of `d = 2 t0`,
the form `(i + 0.5) d` of D2.10 with N = 1, so that MATLAB's pulse plays for one
dwell; a follow-up task makes the change (`model.rf_time_step`). Until then
`spec` rejects it.

The same condition in `cpp-siemens`: [D5.8](../packages/pulseq-cpp-siemens/docs/specification.md#d58-the-rf-resampling-reads-past-the-samples), [D5.9](../packages/pulseq-cpp-siemens/docs/specification.md#d59-an-rf-time-shape-whose-last-time-does-not-fit-an-int)

#### D3.10: A rotation quaternion of norm 0

| Source | What it does |
|---|---|
| Specification | A rotation is "a normalized rotation quaternion" (section 2.8.4, `spec:567`). |
| C++ reader | Rejects a quaternion whose norm is more than 1e-3 from 1, so one of norm 0 too (`cpp:1286-1290`). |

Example: no fixture has a quaternion of norm 0. The test
`test_rotation_quaternions_are_normalized_and_a_quaternion_of_norm_0_is_rejected`
writes a 1.5.1 file whose rotation row is `1 0 0 0 0`.

`spec`: `rotation.zero`.

Reason: `spec` divides each quaternion by its norm (D2.18), and a quaternion of
norm 0 is no rotation, so `spec` rejects it (the user's choice; the message says
so). MATLAB Pulseq refuses to register such a rotation: `registerRotationEvent`
accepts a quaternion only if its squares sum to 1 within 1e-6 (`Sequence.m:802-806`),
and `makeRotation` normalizes the quaternion it is given (`makeRotation.m:35`);
in a run of 2026-10-13, adding the rotation made by `makeRotation([0 0 0 0])` to
a block failed with "invalid rotation quaternion detected during
registerRotationEvent()". pypulseq writes no rotation
extension (`write_seq.py:14-265` has no such section).

#### D3.11: A shape with no blank line after it

| Source | What it does |
|---|---|
| Specification | "The end of the shape definition is declared with a blank line." (section 2.9, `spec:602`) |
| C++ reader | The samples of a shape end at an empty line or a line that starts with `s` (`cpp:955-958`). After a shape it reads the next non-comment line (`cpp:978`), and it stops reading `[SHAPES]` when that line does not start with `s` (`cpp:939`). So after a `shape_id` line with no blank line before it, the reader reads the `num_samples` line as the next line and stops: the later shapes are not read. |

Example: `tests/seqfiles/bad_syntax_shape_no_blank_line.seq` has `shape_id 5` right
after the last sample of shape 4. Matrix: the macOS build of the C++ reader
crashes (on the unknown extension of the file, by `tests/test_cpp_oracle.py`); the
Linux build accepts the file.
`bad_syntax_shape.seq` has a shape with no `num_samples` line: the C++ reader
rejects it.

`spec`: `syntax.shape` for a shape with no blank line after it: a `shape_id` line
right after its samples (`bad_syntax_shape_no_blank_line.seq`; the shape before
it is still read), or a header or the end of the section right after the last
shape (`bad_syntax_shape_end.seq`); and for a shape without its two header lines
(`bad_syntax_shape.seq`), also when a blank line comes between them. A `#` line
inside a shape is skipped (D2.5).

Reason: `spec` follows section 2.9 of the specification: the end of a shape is
declared with a blank line (spec:602). The specification does not say what a
shape without one is, so `spec` rejects it (the user's choice; the message says
so). Both writers end every shape with a blank line (`write.m:254-257`,
`write_seq.py:248-254`).

The same condition in `cpp-siemens`: [D5.1](../packages/pulseq-cpp-siemens/docs/specification.md#d51-a-block-uses-a-shape-that-the-reader-did-not-read)

### D4. Versions

#### D4.1: A version before 1.4.0 or from 1.6.0 (both interpreters)

| Source | What it does |
|---|---|
| Specification | Gives the format of 1.5.3. It has no rule for a reader and a version that the reader does not know. |
| C++ reader | Rejects a version before 1.2.0 (`cpp:918-922`) and ports 1.2 and 1.3 files (`cpp:1656-1711`). It has no upper bound: it accepts 1.6.0 (matrix, `bad_version_unsupported_1_6.seq`). |

Example: `tests/seqfiles/bad_version_unsupported_1_6.seq` (a 1.5.1 file with
`minor 6`) and `bad_version_unsupported_1_3.seq` (`minor 3`). The 1.3 fixture
keeps the 1.5 tables, so the C++ reader fails on its tables, not on its version.

`spec`: raises `NotSupported` for a version before 1.4.0 or from 1.6.0, and also
for a binary file or a folder. Both fixtures of the example raise it.
`cpp-siemens` has the same gate (its record cites this entry).

Reason: the package reads the versions 1.4.0 to 1.5.x (decision Q1). It refuses
another version as not supported by the package, with an exception that says
nothing about the file, so that a new version fails loudly, not wrongly.

#### D4.2: The rows of a 1.4 file, and the RF center that it does not have

| Source | What it does |
|---|---|
| Specification | Its table of revisions gives the revision of each column: 1.5.0 added the RF center and use, the ppm offsets and the ADC phase shape (`spec:117-122`), and the 1.5 table adds `center` (`spec:350`). A 1.4 file has the earlier columns. |
| C++ reader | Reads a 1.4 file by the layouts of 1.4: 8 values of an `[RF]` row, 5 of a `[GRADIENTS]` row and 6 of an `[ADC]` row (`cpp:1027-1029`, `cpp:1081`, `cpp:1157-1158`). It sets `center` to -1, "mark as invalid" (`cpp:1037`). |

Example: `tests/seqfiles/oracle/koma_v1.4_fid.seq`, RF row `1 2500 1 2 3 100 0 0`.
Run: the C++ reader -1 µs, and `spec` `None` in `RfEvent.center`. Both give the
use `u` (undefined).

`spec`: reads a 1.4.x file by its own tables: `[RF]`, `[GRADIENTS]` and `[ADC]`
rows of 8, 5 and 6 fields, with no `center`, no `first` and `last`, no ppm
offsets, no `use` and no ADC phase shape. `center` is absent (NaN in the model,
`None` in `RfEvent.center`) and `use` is `u`. A row with another number of fields
is `syntax.columns` (D1.2).

Reason: `spec` reads each version as its own format (the user, 2026-10-12; rule 2
of P20). Layer 1 holds the values of the file, and a 1.4 file has no center: the
reader's -1 is a mark, not a value. A caller that needs the center computes it
(pulseq-reports uses `calc_rf_center` today).

The same condition in `cpp-siemens`: [D7.5](../packages/pulseq-cpp-siemens/docs/specification.md#d75-the-center-of-a-14-rf-event-nan)

#### D4.3: Time ID -1 in a 1.4 file

| Source | What it does |
|---|---|
| Specification | Time ID -1 is "1/2 of the default time raster (gradient oversampling case)" for a gradient (section 2.8.2, `spec:395`). The slide set dates it from 1.5.0 ("Updated in v1.5.0", slide 4). |
| C++ reader | A 1.4 gradient with time ID -1: accepts (matrix). |

Example: `tests/seqfiles/bad_ref_time_id_minus_1_in_1_4.seq`.

`spec`: `ref.unresolved` for time ID -1 of a gradient in a 1.4 file.

Reason: the slide set dates time ID -1 from 1.5.0 (slide 4), and `spec` reads each
version as its own format (the user, 2026-10-12).

The same condition in `cpp-siemens`: [D5.3](../packages/pulseq-cpp-siemens/docs/specification.md#d53-an-rf-event-with-time-id--1)

#### D4.4: A 1.4 arbitrary gradient on the default raster: no ends

| Source | What it does |
|---|---|
| Specification | A 1.4 file has no `first` and `last`; the samples of time ID 0 are at the centres of the raster cells (section 2.6, `spec:290`), so the values at the two ends of the event are not in the file. |
| C++ reader | Sets `first` and `last` to `FLOAT_UNDEFINED` (1.18e-38, `cpp:1085-1086`, `cpp.h:128`). `gradientsAt` interpolates to them at the ends of the event (`cpp:3681`, `cpp:3686`), so the waveform goes to about 0 there. |

Example: `tests/seqfiles/oracle/koma_v1.4_gr-uniformly-shaped.seq`, a half sine of
10 samples (amplitude 42576 Hz/m, first and last sample 0) in three blocks. Run:
`last` is 1.18e-38 Hz/m in the C++ reader. `tests/seqfiles/bad_layer1_gradient_ends.seq`
is the fixture of the rule.

`spec`: `layer1.gradient-ends` rejects a 1.4 file with an arbitrary gradient of
time ID 0.

Reason: the file does not define the values at the two ends of such a gradient (a
1.4 file has no `first` and `last`, and the samples are at the cell centres,
spec:290), and the C++ reader fills them with a mark of about 0, so `spec`
rejects the file (the user's choice); its message names the gradients and says
that Pulseq 1.5 stores the ends. The writers do write such files: the 1.4.1
writers of both write the `[GRADIENTS]` rows of 5 fields (`write_v141.m:93-95`,
`write_seq.py:401-410`), and `tests/seqfiles/oracle/pypulseq_simple_mprage140.seq`
is one. Other 1.4.x files are read: trapezoids and time-shaped gradients define
their ends.

#### D4.5: A 1.4 arbitrary gradient with a time shape

| Source | What it does |
|---|---|
| Specification | As D4.4: a 1.4 file has no `first`. |
| C++ reader | Holds `FLOAT_UNDEFINED` (`cpp:1085-1086`), but a gradient with a time shape is an extended trapezoid there (`cpp.h:698`), and `gradientsAt` starts it at the amplitude times its first sample (`cpp:3628-3630`). |

Example: `tests/seqfiles/valid_1_4_1.seq`, block 3: gradient 2 (amplitude
400000 Hz/m, samples 0.2, 0.6, 1, 0.6, 0.2 at the times 0, 1, 3, 6, 10) after
a block with no gz. Run: `spec` `first` 80000 Hz/m, the value of the first
sample, which is at time 0.

`spec`: `first` and `last` are the amplitude times the first and last samples.
`layer1.gradient-ends` also rejects a 1.4 time shape whose first time is not 0
(within `spec.FIRST_TIME_TOLERANCE`).

Reason: `spec` keeps the value that the file gives at the start of the event, the
amplitude times the first sample, as the C++ reader does. It rejects a 1.4 time
shape that does not start at 0 (the user's choice), since then the file has no
value at the start of the event.

#### D4.6: An extension before the revision that introduced it

| Source | What it does |
|---|---|
| Specification | Gives the revision of each mechanism: the soft delay extension from 1.5.0 (`spec:545`), the rotation and RF shimming extensions and the required extensions from 1.5.1 (`spec:567`, `spec:584`, `spec:460`; table of revisions, `spec:121-126`). It does not say what a reader does with such an extension in an older file. |
| C++ reader | Recognizes the extensions in any version: it attaches the block's first rotation in any version (`cpp:1871-1879`). It reads `RequiredExtensions` from 1.5.1 (`cpp:1505`). |

Example: `tests/seqfiles/valid_1_5_0_extensions_of_1_5_1.seq` (extensions of 1.5.1
in a 1.5.0 file).

`spec`: reads each extension from the revision of the format that introduced it
(section 7.8 of the plan). `extension DELAYS` before 1.5.0, and ROTATIONS and
RF_SHIMS before 1.5.1, are extensions that `spec` does not know: ignored, with a
record in `SequenceData.records` (`"extension"`, reason `"version"`).
`RequiredExtensions` is read from 1.5.1. Before 1.5.1 no block is rotated, where
`CppSiemens(rotation="apply")` rotates.

Reason: the specification gives the revision of each mechanism (above), and a
reader of a version has only the mechanisms of that version (the user,
2026-10-12; rule 2 of P20). The C++ reader recognizes the extensions in any
version.

The same condition in `cpp-siemens`: [D6.2](../packages/pulseq-cpp-siemens/docs/specification.md#d62-a-block-that-plays-a-rotation)

#### D4.7: A label flag of 1.4.1 in an older file

| Source | What it does |
|---|---|
| Specification | "New experimental labels have been introduced in revision 1.4.1. These include `PMC`, `NOROT`, `NOPOS`, `NOSLC` and `ONCE` flags" (section 2.8.4, `spec:526`). It does not say what a reader does with such a flag in an older file. |
| C++ reader | Decodes a label by its name in any version (`cpp:1297-1311`, `cpp:825`). |

Example: no fixture. The test
`test_the_records_of_labels_and_of_an_extension_of_a_later_revision` edits the
label row of `valid_1_4_1.seq` to `1 0 PMC`: `spec` records nothing for it, and
records the label with the reason `"version"` when the file says `revision 0`.

`spec`: keeps a flag of 1.4.1 (`PMC`, `NOROT`, `NOPOS`, `NOSLC`, `ONCE`) in an
older file as text, and records it in `SequenceData.records` (`"label"`, reason
`"version"`).

Reason: as D4.6: a reader of a version has only the mechanisms of that version
(the user, 2026-10-12; rule 2 of P20), and labels do not change the waveforms.

## Appendix: the old IDs, the acceptance matrix and the figures

### The old IDs

Until 2026-10-13 each condition of a file had one entry, with the IDs D01a to
D60. The table maps each old ID to its new IDs, and gives what was removed: the
conditions in which the specification states the rule (the rule is in
`spec.RULES` and in [`docs/specification.md`](specification.md) section 3), and
those that concern only MATLAB Pulseq or pypulseq. It is the output of
`nix develop --command uv run python scripts/record_ids.py table`. Historical
documents keep the old IDs.

| Old ID | New IDs | Removed (no decision of the interpreters) |
|---|---|---|
| D01a | D1.2, D4.2 |  |
| D01b | D1.2, D4.2 |  |
| D01c | D1.2, D4.2 |  |
| D02 | D1.1 |  |
| D03 | D4.1 |  |
| D04 | — | a [VERSION] value such as 5.0 (spec:193-198 states integers) |
| D05 | D2.1, D5.1 |  |
| D06 | D2.5, D3.2 |  |
| D07 | D3.11, D5.1 |  |
| D08 | D2.4 |  |
| D09 | — | [DELAYS] from 1.4.0 (spec:114, spec:772; both ignore it) |
| D10 | D3.3 |  |
| D11 | — | a required raster missing or invalid (spec:267-276, slide 11) |
| D12 | D2.6 |  |
| D13 | D2.7, D7.1 |  |
| D14 | D3.1, D3.5, D3.6 | the types of the columns (spec:176, spec:293-455); the C++ reader's misreading of a fraction |
| D15 | — | an ADC dwell time with a decimal point (spec:437: a float) |
| D16 | D2.16 |  |
| D17 | — | an RF use letter (spec:356-357) |
| D18 | D7.2 | values beyond float32 (spec:176), for spec |
| D19 | D3.4 | IDs of shapes and events not positive or not unique (spec:181-183, spec:403) |
| D20 | D7.3 | block IDs out of order (spec:185, spec:318), for spec |
| D21 | D5.1, D5.2 | a reference that does not resolve (spec:178-186), for spec |
| D22 | D4.3, D5.3 | time ID -1 of an RF event (spec:349, spec:395), for spec |
| D23 | D5.4 | a cycle in an extension list (spec:478), for spec |
| D24 | — | a file with no block (spec:318) |
| D25 | D7.4 | an event longer than its block (spec:318) |
| D26 | D1.3 | times off a raster (spec:275, spec:290, slides 5, 9, 10), except the vertex (D1.3) |
| D27 | — | a gradient non-zero at an end (spec:420, slide 6) |
| D28 | — | an arbitrary gradient off 10 us (spec section 2.5, slide 11) |
| D29 | D5.5 | a shape whose length is not num_samples (spec:626), for spec |
| D30 | — | an amplitude shape outside [-1, 1] (spec:624) |
| D31 | D2.8 |  |
| D32 | D2.9 |  |
| D33 | D3.7, D5.6 |  |
| D34 | D3.8, D5.7 |  |
| D35 | D2.10 |  |
| D36 | D2.11, D3.9, D5.8, D5.9 |  |
| D37 | D2.12 |  |
| D38 | D4.2, D7.5 |  |
| D39 | D4.4 |  |
| D40 | D4.5 |  |
| D41 | D2.13 |  |
| D42 | D2.14, D7.4 |  |
| D43 | D6.1 | an oversampled gradient (spec:420, slides 4, 8), for spec |
| D44 | D2.15, D3.8, D7.6 |  |
| D45 | D2.17, D4.6 |  |
| D46 | D2.3 |  |
| D47 | D4.6 | an unknown required extension (spec:460), except the revision (D4.6) |
| D48 | — | two ROTATIONS or RF_SHIMS objects in a block (spec:567, spec:584) |
| D49 | D2.18, D3.10, D4.6, D6.2 |  |
| D50 | D2.19, D4.7 |  |
| D51 | — | equal events with different IDs (only pypulseq merges them) |
| D52 | — | no dead time or default raster of a scanner (only MATLAB and pypulseq add them) |
| D53 | — | the signature hash (spec:223) |
| D54 | — | [SIGNATURE] without Type or Hash (spec:223-232) |
| D55 | D1.4 |  |
| D56 | D2.2 |  |
| D58 | D4.6 |  |
| D59 | D5.10 |  |
| D60 | D5.11 |  |

### The acceptance matrix and the figures

The acceptance matrix runs each `.seq` file of `tests/seqfiles` through `spec`,
`cpp-siemens` and the C++ reader (`pulseq-cpp-oracle`), and writes a Markdown
table of their verdicts. The entries cite it as "matrix". It is not kept in this
document, since it goes out of date with each change of a fixture or of `spec`:
run it to see the verdicts of today. The script may suit a separate report on the
discrepancies better than this package.

Both scripts need the C++ oracle, which is in the default devShell (not in the
`ci` shell); the column of `cpp-siemens` needs the plugin `pulseq-cpp-siemens`
installed:

```
nix develop --command uv run python scripts/discrepancy_matrix.py > matrix.md
nix develop --command uv run python scripts/discrepancy_figures.py
```

- `scripts/discrepancy_matrix.py` writes the table, with the columns `spec`,
  `cpp-siemens` and the C++ reader, to stdout and its time to stderr. `--cpp PATH`
  gives an oracle that is not on the `PATH`. The C++ column is the build that runs
  it ("crash (70)" is a signal); a reader that cannot run gives "not run".
- `scripts/discrepancy_figures.py` writes the small Pulseq files of the figures
  to a temporary folder, runs the C++ reader (`pulseq-cpp-oracle --dump` and
  `--sample`) and `spec` on them, and writes
  `docs/figures/discrepancy-rf-time-shapes.svg` and
  `docs/figures/discrepancy-arbitrary-gradient-edges.svg`: `spec` against the C++
  reader. The SVG files are reproducible (`svg.hashsalt`, no date). With
  `DOC_FIGURES_PREVIEW=<dir>` it also writes a PNG of each.
- `figures/waveform-gaps.svg` (D2.14) comes from `scripts/doc_figures.py`.
