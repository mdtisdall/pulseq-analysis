# Where the readers of a Pulseq file disagree

This document records each place where the sources that define how a Pulseq
file is read disagree, or where they leave a question open. For each one it
gives what each source does, an example, and what pulseq-analysis does and why.
It records the package as it is on 2026-10-12, with its two interpreters,
`cpp-siemens` and `strict` (section 1). The sources and the runs on them are
those of 2026-10-09, unless an entry says otherwise. Section 4 compares the
strict reader with the order of preference of 2026-10-09, which section 1
explains.

Contents:

1. [The sources](#1-the-sources)
2. [Summary](#2-summary)
3. [The entries](#3-the-entries)
4. [Review against the order of preference](#4-review-against-the-order-of-preference)
5. [Appendix A: the acceptance matrix](#appendix-a-the-acceptance-matrix)
6. [Appendix B: how to regenerate the matrix and the figures](#appendix-b-how-to-regenerate-the-matrix-and-the-figures)

## 1. The sources

Four sources define how a file is read. Each is fixed at one version.

| Source | Version | Where it is used | Cited as |
|---|---|---|---|
| The specification | `doc/specification.tex` of [pulseq/pulseq](https://github.com/pulseq/pulseq) at commit `c7469123c2f381f065986e6cc3a7d09730ed16ef`: "Version 1.5.3 (DRAFT)". The PDF of that commit (`doc/specification.pdf`) is made from it. | The definition of the format. | `spec:N`, line N of `specification.tex`, with the section number of the PDF |
| The C++ reader | `src/ExternalSequence.cpp` and `src/ExternalSequence.h` of pulseq/pulseq at the same commit, built by `flake.nix` as `pulseq-cpp-oracle` with the driver of `tests/cpp_oracle/` | The reader of the Pulseq interpreter on the scanner: what the scanner plays. | `cpp:N` (`.cpp`), `cpp.h:N` (`.h`) |
| MATLAB Pulseq | `matlab/` of pulseq/pulseq at the same commit, run under GNU Octave 11.3.0 by `pulseq-matlab-oracle` (`tests/matlab_oracle/`) | The toolbox that writes most Pulseq files. | `read.m:N`, `Sequence.m:N` (`matlab/+mr/@Sequence/`), `restoreAdditionalShapeSamples.m:N` (`matlab/+mr/`) |
| pypulseq | The pin of `pyproject.toml`: the fork [mdtisdall/pypulseq](https://github.com/mdtisdall/pypulseq) at `3c3bd8515e591ef859399aa20db64b1bd2c3a725` (pypulseq 1.5.0.post1 and six commits) | The reader behind `load(path)`, which does not use the interpreters yet (task R14). | `read_seq.py:N`, `sequence.py:N` (`pypulseq/Sequence/`), `event_lib.py:N` (`pypulseq/`) |

pulseq-analysis ("the package") reads a file with `read_seqfile(path,
interpreter)`, through one of its two interpreters (`docs/usage.md`, "The
interpreters"):

- `cpp-siemens` (by name: `read_seqfile(path, "cpp-siemens")`) reads a file as
  the C++ reader of the scanner's interpreter on Siemens systems reads it. Its
  engine is the C++ reader itself, run in the process by the package
  pulseq-cpp-siemens. It makes the waveforms that the reader makes, and rejects
  what the reader rejects, with a code (`cpp_siemens.CODES`). Where the reader's
  behaviour is undefined (it reads or writes memory that it does not own, or it
  does not end), it rejects the file with a `ub.*` code (section 5.3 of the
  plan).
- `strict` (the default until the `spec` interpreter of task R11 replaces it) is
  the strict reader that the package had before the interpreters. It rejects a
  file that breaks a rule, with the rule IDs of `reader.RULES`. The module
  docstring of `reader` gives each rule and its source.

A version outside 1.4.0 to 1.5.x raises `NotSupported` in both (decision Q1),
and says nothing about the file. The package reports no discrepancy itself:
pulseq-checks does (P17). The decisions P1 to P19 and Q1 to Q6 that this
document cites are those of sections 2 and 3 of `docs/plans/parser-redesign.md`
("the plan"). The entries of section 3 give, for each interpreter, what it does
and why.

Each statement about a source was checked in one of three ways:

- by reading its code at the commit above (the citation gives the file and the
  line);
- by a run on 2026-10-09, on an Apple M1 Max (macOS 26.6.2, arm64): the
  acceptance matrix of appendix A, or a small file that the entry shows (run
  through the same four readers as the matrix). The C++ reader is the macOS
  build of `pulseq-cpp-oracle`. "Crash" is a signal (exit status 70 of the
  driver). Where the reader reads memory that it does not own, the result can
  depend on the build; or
- by a run on 2026-10-12 of the two interpreters on the fixture or the small
  file that the entry names (`read_seqfile(path, "cpp-siemens")` and
  `read_seqfile(path, "strict")`), with `pulseq-cpp-oracle` on the same file.

The matrix gives two columns for pypulseq. Most fixtures have a `ROTATIONS`
extension, and pypulseq's `read` rejects every file with one, so the column
"pypulseq, probe" reads a copy of each file without the extensions that
pypulseq does not read, without `RequiredExtensions`, and with time ID -1 set
to 0. An entry says "probe" when it cites that column.

pulseq-analysis does not judge whether a file is valid. On 2026-10-09 its goal
was to read a file with the meaning that the first source in this order gives
it:

1. the C++ reader;
2. the specification;
3. MATLAB Pulseq;
4. pypulseq.

A source gave no meaning where it was unclear (for example where it differs
between builds), rejected the file, crashed, did not end, or had undefined
behaviour; then the next source decided. Section 4.1 gives these rules in full.

The plan (section 1) replaced this goal with the two interpreters above. The
entries of section 3 give what each interpreter does and why. Section 4 reviews
the strict reader against the older order of preference, and is rewritten for
the two interpreters later (plan section 11).

## 2. Summary

The verdicts are short. "Accepts" and "reads" mean that the source goes on with
no error; "rejects" means an error; "silent" means that the source has no rule.
The last two columns are the package's interpreters. "As C++" means that
`cpp-siemens` does what the C++ reader does; "not supported" is the
`NotSupported` exception.

| ID | Condition in the file | Specification | C++ reader | MATLAB Pulseq | pypulseq | `cpp-siemens` | `strict` |
|---|---|---|---|---|---|---|---|
| [D01a](#d01a-an-rf-row-with-12-fields) | `[RF]` row with 12 fields | prose: 7 numbers, line: 8 fields; table and example: 12 | 12 | 12 | 12 | 12 | 12 |
| [D01b](#d01b-a-gradients-row-with-7-fields) | `[GRADIENTS]` row with 7 fields | prose: 4 numbers; line, table and example: 7 | 7 | 7 | 7 | 7 | 7 |
| [D01c](#d01c-an-adc-row-with-9-fields) | `[ADC]` row with 9 fields | prose: 6 numbers; line, table and example: 9 | 9 | 9 | 9 | 9 | 9 |
| [D02](#d02-a-file-with-no-version-section) | No `[VERSION]` | recommends to reject | rejects | rejects | fails (`UnboundLocalError`) | rejects (`version.missing`) | rejects |
| [D03](#d03-a-file-whose-version-is-before-140-or-after-15x) | Version outside 1.4.0 to 1.5.x | silent | 1.2.0 and later | 1.2.0 and later, major 1 | 1.2.0 and later | not supported | not supported |
| [D04](#d04-a-version-line-whose-value-is-not-a-plain-integer-such-as-minor-50) | `[VERSION]` value such as `5.0` | `major <major>` | reads `5.0` as 5 | reads `5.0` | rejects `5.0`; cuts `revision` | as C++ (`5.0` is 5) | rejects |
| [D05](#d05-sections-in-an-unusual-order-such-as-version-after-blocks-or-last-in-the-file) | `[VERSION]` after `[BLOCKS]` or last | silent | any order; crash with `[VERSION]` last | `[VERSION]` before `[BLOCKS]` | `[VERSION]` before `[BLOCKS]` | as C++; `[VERSION]` last loses the shapes | any order |
| [D06](#d06-a-blank-or--line-inside-a-section-with-data-after-it) | Blank or `#` line inside a section | silent | blank line; `#` is data | blank or `#` line | blank line or a lone `#` | as C++: drops rows after a blank line | blank or `#` line |
| [D07](#d07-a-shape-whose-last-sample-is-followed-by-the-next-shape_id-with-no-blank-line) | No blank line after a shape | blank line | `shape_id` line too; drops the rest | blank or `#` line | blank or a lone `#` | as C++: later shapes lost | blank line |
| [D08](#d08-a-section-that-the-format-does-not-have) | Unknown section | silent | ignores | rejects | rejects | ignores | rejects |
| [D09](#d09-a-delays-section-in-a-file-of-140-or-later) | `[DELAYS]` from 1.4.0 | removed in 1.4.0 | ignores | rejects | rejects | ignores | rejects |
| [D10](#d10-a-section-that-appears-twice) | A section twice | silent | reads the last | reads | reads | reads the last | rejects |
| [D56](#d56-the-last-section-with-no-blank-line-after-it) | Last section with no blank line after it | silent | skips the sections it reads after it | reads | fails (`AttributeError`) | as C++ (`definitions.skipped`) | reads |
| [D11](#d11-a-required-raster-that-is-missing-zero-negative-or-not-finite) | Missing or invalid raster | required | presence; value partly | presence | defaults | rejects missing, `nan`, text; partly | presence and value |
| [D12](#d12-a-definition-that-appears-twice) | A definition twice | silent | last wins | last wins | last wins | last wins | rejects |
| [D13](#d13-a-definition-or-a-signature-hash-whose-text-reads-as-a-number) | Definition or hash that reads as a number | `any`, hash `string` | text and numbers | numbers when they parse; hash too | numbers; hash text | text | text |
| [D14](#d14-a-number-with-a-fraction-in-an-integer-column-a-sign-or-nan-a-row-with-too-few-or-too-many-columns-bytes-that-are-not-utf-8) | Number syntax, columns, encoding | types only | partly | lenient | partly | as C++ | strict |
| [D15](#d15-an-adc-dwell-time-written-with-a-decimal-point-such-as-25000) | ADC dwell `2500.0` | float | rejects | reads | reads | rejects (`syntax.row`) | reads |
| [D16](#d16-a-soft-delay-row-with-a-fractional-offset-such-as--1005-or-a-hint-longer-than-31-characters) | Soft delay offset `-100.5`; long hint | integer in the example | misreads `-100.5`; cuts the hint | reads | rejects `-100.5` | as C++ (misreads `-100.5`) | reads |
| [D17](#d17-an-rf-use-letter-that-is-not-one-of-e-r-i-s-p-o-u) | RF `use` letter not in the list | one of 7 letters | any character | any | any | any character | rejects |
| [D18](#d18-a-value-with-more-digits-than-a-32-bit-float-holds) | Value beyond 32-bit precision | shapes float32 | float32 | double | float64 | float32 | float64 |
| [D19](#d19-ids-that-are-not-positive-or-not-unique) | IDs not positive or not unique | must | silent (last wins) | mixed | silent | last wins | rejects |
| [D20](#d20-block-ids-that-are-not-in-increasing-order) | Block IDs out of order | no restriction | file order | ID order | file order | file order | rejects |
| [D21](#d21-a-reference-to-an-event-shape-or-extension-that-does-not-exist) | Reference that does not resolve | implied | partly; crashes | mostly rejects | partly | rejects event, shape; extensions as C++ | rejects |
| [D22](#d22-time-id--1-for-an-rf-event-or-in-a-14-file) | Time ID -1 for RF, in 1.4 | gradients only | crashes (RF) | default raster (RF) | fails (`KeyError`) | rejects RF (`ub.rf-time-id-minus-1`); reads 1.4 gradient | rejects |
| [D23](#d23-a-cycle-in-an-extension-list) | Cycle in an extension list | implied | no end | no end (code) | reads | rejects (`ub.extension-cycle`) | rejects |
| [D24](#d24-a-file-with-no-block) | No block | must | accepts | reads | reads | reads | rejects |
| [D25](#d25-an-event-that-lasts-longer-than-its-block) | Event longer than its block | interpreter must reject | accepts | reads | reads | reads | rejects |
| [D26](#d26-a-time-that-is-not-a-multiple-of-its-raster) | Times off a raster | must | accepts | reads | reads | reads | rejects |
| [D27](#d27-a-gradient-that-starts-above-0-after-a-delay-or-ends-above-0-before-the-end-of-its-block) | Gradient non-zero at an end | must / need to | accepts | reads | reads | reads | rejects |
| [D28](#d28-an-arbitrary-gradient-on-a-gradient-raster-other-than-10-µs) | Arbitrary gradient off 10 µs | allowed | rejects | reads | reads | rejects (`gradient.raster`) | accepts |
| [D29](#d29-a-shape-that-does-not-have-the-number-of-samples-that-it-declares) | Shape length | must | accepts | reads | reads | longer rejects; shorter reads | rejects |
| [D30](#d30-an-amplitude-shape-with-a-sample-outside--1-1) | Shape outside [-1, 1] | must | clamps | reads | reads | clamps | rejects |
| [D31](#d31-an-rf-magnitude-shape-with-a-sample-below-0) | RF magnitude below 0 | allowed | clamps to 0 | reads | reads | clamps to 0 | rejects |
| [D32](#d32-an-rf-phase-shape-with-a-sample-outside-0-1) | RF phase outside [0, 1) | silent | clamps | reads | reads | clamps | rejects |
| [D33](#d33-a-shape-with-no-sample-that-an-event-uses) | Empty shape | silent | crashes | rejects | rejects | rejects (`ub.shape-empty`) | rejects |
| [D34](#d34-the-shapes-of-one-event-with-different-numbers-of-samples) | Shapes of one event, two lengths | silent | crashes | rejects | reads | shorter phase rejects; longer reads | rejects |
| [D35](#d35-an-rf-time-shape-stored-compressed-in-3-or-4-values-a-regular-step) | Regular RF time shape (3 or 4 stored values) | times in the shape | dwell from the shape; first time ignored | times of the shape | times of the shape | as C++ | as C++; rejects off-centre |
| [D36](#d36-an-rf-time-shape-stored-in-any-other-form) | Other RF time shape | times in the shape | resamples; can read past the end | times of the shape | times of the shape | as C++; past the end rejects | as C++; rejects past the end |
| [D37](#d37-an-rf-time-shape-whose-last-time-is-before-the-end-of-the-last-samples-dwell) | RF time shape that ends inside its last dwell | silent | dwell × samples | last time rounded up | last time rounded up | as C++ | as C++ |
| [D38](#d38-an-rf-event-of-a-14-file-which-has-no-center-column) | 1.4 RF event, no `center` | not in 1.4 | -1 (invalid) | computed | computed | absent | absent |
| [D39](#d39-a-14-arbitrary-gradient-on-the-default-raster-which-has-no-first-and-last-columns) | 1.4 gradient on the default raster | not in 1.4 | about 0 | alternating sum | extrapolation | reads; ends about 0 | rejects |
| [D40](#d40-a-14-arbitrary-gradient-with-a-time-shape-which-has-no-first-column) | 1.4 time-shaped gradient, no `first` | not in 1.4 | first sample | from the block before | from the block before | as C++ (first sample) | first sample |
| [D41](#d41-an-arbitrary-gradient-on-the-default-raster-time-id-0-whose-samples-are-at-the-centres-of-the-raster-cells) | Time-ID-0 gradient between its samples | centres of cells | lines | restores the edges | lines | lines | lines |
| [D42](#d42-a-gap-between-two-gradient-events-on-one-axis) | Gap between gradient events | silent | one block only | ramps to 0 | straight line | one block at a time | ramps (MATLAB) |
| [D43](#d43-an-oversampled-arbitrary-gradient-time-id--1) | Oversampled gradient | defined | keeps the centres | reads | fails (`KeyError`) | centre samples (the reader's default) | reads |
| [D44](#d44-an-adc-event-with-a-phase-modulation-shape) | ADC phase modulation shape | none | rad | as stored | not checked | as C++ (rad) | as stored |
| [D45](#d45-an-unknown-extension-that-the-file-does-not-require) | Unknown extension, not required | may ignore | ignores | ignores | rejects | ignores | ignores |
| [D46](#d46-a-file-whose-last-section-that-starts-with--is-extensions) | `[EXTENSIONS]` last | silent | rejects | reads | reads | rejects (`section.extensions-last`) | accepts |
| [D47](#d47-an-unknown-extension-that-the-file-requires) | Unknown required extension | must reject | rejects | reads | reads | rejects (`extension.required-unknown`) | rejects |
| [D48](#d48-a-block-with-more-than-one-rotations-or-rf_shims-object) | Two ROTATIONS or RF_SHIMS in a block | one only | warns, uses the first | rejects | rejects any ROTATIONS | the first, as C++ | rejects |
| [D49](#d49-a-block-that-plays-a-rotation-or-a-quaternion-that-is-not-normalized) | Played rotation; quaternion norm | normalized quaternion | normalizes; rejects off by 1e-3 | normalizes, rotates | rejects | normalizes; rejects off by 1e-3 (`rotation.norm`) | reads as written |
| [D50](#d50-a-labelset-or-labelinc-row-with-a-label-name-that-a-reader-does-not-know) | Unknown label name | lists labels | ignores the label | rejects | rejects | ignores the label | reads |
| [D51](#d51-two-event-rows-with-equal-values-and-different-ids-such-as-amplitudes-0-and--0) | Equal events, different IDs | silent | keeps | keeps | merges, renumbers | keeps | keeps |
| [D52](#d52-any-file-it-holds-no-dead-time-ringdown-time-or-default-raster-of-a-scanner) | No values of a target in the file | not in the file | none | dead times | dead times, default rasters | none | none |
| [D53](#d53-a-signature-hash-in-a-file-with-crlf-line-ends-or-a-hash-that-does-not-match-the-file) | Signature: CRLF line ends, mismatch | strip the `\n` | drops the empty line | no check | no check | as C++ | as C++ |
| [D54](#d54-a-signature-section-without-type-or-hash) | `[SIGNATURE]` without `Type` or `Hash` | must have both | accepts | reads | reads | reads | rejects |
| [D55](#d55-an-extension-header-whose-string_id-is-a-word-where-the-specifications-table-gives-the-type-integer) | `STRING_ID` that is a word | integer in the table; a word in the examples | text | text | text | text | text |

## 3. The entries

### Format and structure

#### D01a: An `[RF]` row with 12 fields

| Source | What it does |
|---|---|
| Specification | Section 2.8.1 describes the row three ways. The prose says "a single line containing seven numbers", and the line under it has 8 fields: `<id> <amp> <mag_id> <phase_id> <time_id> <delay> <freq> <phase>` (`spec:334-336`). The table has 12 fields: `<center>` before `<delay>`, and `<freq_ppm>`, `<phase_ppm>` and `<use>` (`spec:341-359`). The example has 12 (`spec:366-369`). |
| C++ reader | Reads 12 values in a 1.5 file (`cpp:1042-1048`). |
| MATLAB Pulseq | Reads 12 values (`read.m:120`). |
| pypulseq | Reads 12 values (`read_seq.py:151`). |

Example: the first row of the example of section 2.8.1,
`1 550 1 2 0 1000 100 0.000 0.0000 0.000 0.000 e`. By the line of the prose,
the delay is 1000 µs and the frequency offset is 100 Hz. By the table, the
center is at 1000 µs and the delay is 100 µs, as the text under the example
says (`spec:372`).

Package (`cpp-siemens`): reads the 12 fields of the table, in its order, as the
C++ reader does. A row with fewer fields is `syntax.row`; the reader reads a row
with more, and ignores the extra fields. A 1.4.x file has its own layout of 8
fields, with no `center`, ppm offsets or `use` (D38).

Package (`strict`): reads the 12 fields of the table, in its order (`_RF_15` of
`reader`). A row with another number of fields is `syntax.columns`. A 1.4.x file
has its own layout of 8 fields (D38).

Reason: `cpp-siemens` reads what the C++ reader reads, the 12 fields of the
table. Where the prose of the specification contradicts its tables and examples,
`strict` follows the tables and examples, as the C++ reader and MATLAB's files
do: they agree with each other.

Note: the specification has another slip of the text that does not change how a
file is read: the paragraph of the soft delay extension starts "Label extension
can be used" (`spec:545`).

#### D01b: A `[GRADIENTS]` row with 7 fields

| Source | What it does |
|---|---|
| Specification | Section 2.8.2 says that each arbitrary gradient is "specified by four numbers", and the line under it has 7 fields: `<id> <amp> <first> <last> <shape_id> <time_id> <delay>` (`spec:375-377`). The table and the example have 7 (`spec:386-413`). Only the count of the prose differs; the line, the table and the example agree. |
| C++ reader | Reads 7 values in a 1.5 file (`cpp:1073`). |
| MATLAB Pulseq | Reads 7 values (`read.m:130`). |
| pypulseq | Reads 7 values (`read_seq.py:165`). |

Example: the example row of section 2.8.2, `1 790127 0 -550073 6 0 980`.

Package (`cpp-siemens`): reads the 7 fields of the table, as the C++ reader
does. A row with fewer fields is `syntax.row`; the reader reads a row with more,
and ignores the extra fields. A 1.4.x file has its own layout of 5 fields, with
no `first` and `last` (D39, D40).

Package (`strict`): reads the 7 fields of the table (`_GRAD_15` of `reader`). A
row with another number of fields is `syntax.columns`. A 1.4.x file has its own
layout of 5 fields (D39, D40).

Reason: as in D01a.

#### D01c: An `[ADC]` row with 9 fields

| Source | What it does |
|---|---|
| Specification | Section 2.8.3 says that each ADC event is "specified by six numbers", and the line under it has 9 fields: `<id> <num> <dwell> <delay> <freq_ppm> <phase_ppm> <freq> <phase> <phase_shape_id>` (`spec:424-426`). The table and the example have 9 (`spec:431-453`). Only the count of the prose differs; the line, the table and the example agree. |
| C++ reader | Reads 9 values in a 1.5 file (`cpp:1148-1149`). |
| MATLAB Pulseq | Reads 9 values (`read.m:140`). |
| pypulseq | Reads 9 values (`read_seq.py:176`). |

Example: the example rows of section 2.8.3.

Package (`cpp-siemens`): reads the 9 fields of the table, as the C++ reader
does. A row with fewer fields is `syntax.row`; the reader reads a row with more,
and ignores the extra fields. A 1.4.x file has its own layout of 6 fields, with
no ppm offsets and no phase shape.

Package (`strict`): reads the 9 fields of the table (`_ADC_15` of `reader`). A
row with another number of fields is `syntax.columns`. A 1.4.x file has its own
layout of 6 fields.

Reason: as in D01a.

#### D02: A file with no `[VERSION]` section

| Source | What it does |
|---|---|
| Specification | "the interpreter sequence may either refuse execution or assume version 1.0.0. It is recommended to reject Pulseq files without [VERSION] section." (section 2.3, `spec:201`) |
| C++ reader | Rejects: "supported Pulseq files MUST contain the [VERSION] section" (`cpp:912-916`). |
| MATLAB Pulseq | Rejects at `[BLOCKS]`: "Pulseq file MUST include [VERSION] section prior to [BLOCKS] section" (`read.m:114-116`). |
| pypulseq | Fails with `UnboundLocalError` at `[BLOCKS]` (`read_seq.py:139`): its variable of the version is not set. |

Example: `tests/seqfiles/bad_version_missing.seq` (matrix: C++ rejects,
MATLAB rejects, pypulseq `UnboundLocalError`).

Package (`cpp-siemens`): `version.missing`, as the C++ reader rejects it.

Package (`strict`): `version.missing`.

Reason: `cpp-siemens` rejects what the C++ reader rejects (P2). The
specification recommends to reject a file without `[VERSION]`, and `strict`
needs the version to know the layout of the tables.

#### D03: A file whose version is before 1.4.0 or after 1.5.x

| Source | What it does |
|---|---|
| Specification | Gives the format of 1.5.3. It has no rule for a reader and a version that the reader does not know. |
| C++ reader | Rejects a version before 1.2.0 (`cpp:918-922`) and ports 1.2 and 1.3 files (`cpp:1656-1711`). It has no upper bound: it accepts 1.6.0 (matrix, `bad_version_unsupported_1_6.seq`). |
| MATLAB Pulseq | Asserts major 1 (`read.m:98`), rejects before 1.2.0 (`read.m:103-105`), and ports older files (`read.m:216-321`). It reads 1.6.0 (matrix). |
| pypulseq | Rejects before 1.2.0 (`read_seq.py:118-122`). A version above its own gives a warning (`read_seq.py:111-116`). It reads 1.6.0 (probe). |

Example: `tests/seqfiles/bad_version_unsupported_1_6.seq` (a 1.5.1 file with
`minor 6`) and `bad_version_unsupported_1_3.seq` (`minor 3`). The 1.3 fixture
keeps the 1.5 tables, so the other readers fail on its tables, not on its
version (matrix: C++ rejects, MATLAB "nonconformant arguments", pypulseq
"Mismatch between number of tokens and format spec").

Package (`cpp-siemens`): raises `NotSupported` for a version before 1.4.0 or
from 1.6.0, before the C++ reader runs: the version gate reads the version on
the "as written" reading. The C++ reader would read 1.6.0 and port 1.2 and 1.3
files. Both fixtures of the example raise `NotSupported`.

Package (`strict`): raises `NotSupported` for the same versions. Before the
interpreters it rejected them with `version.unsupported`.

Reason: the package reads the versions 1.4.0 to 1.5.x (decision Q1). In both
interpreters it refuses another version as not supported by the package, with an
exception that says nothing about the file, so that a new version fails loudly,
not wrongly.

#### D04: A `[VERSION]` line whose value is not a plain integer, such as `minor 5.0`

| Source | What it does |
|---|---|
| Specification | Three lines `major <major>`, `minor <minor>`, `revision <revision>` (section 2.3, `spec:193-198`). |
| C++ reader | Reads each number with `sscanf("%d")` (`cpp:882-901`), so `minor 5.0` is 5. An unknown key makes it reject (`cpp:902-906`). |
| MATLAB Pulseq | Reads each number with `str2double` (`read.m:479-491`): `5.0` is 5. An unknown key is skipped. |
| pypulseq | Reads each number with `int()` (`read_seq.py:504-512`): `5.0` raises `ValueError`. It keeps only the first character of a revision of more than one character (`read_seq.py:510-511`): `revision 10` is read as 1. |

Example: `tests/seqfiles/bad_version_invalid.seq` has `minor 5.0` (matrix: C++
accepts, MATLAB reads, pypulseq `ValueError`).

Package (`cpp-siemens`): reads `minor 5.0` as 5, as the C++ reader does
(`sscanf` with `%d`). A line that does not decode (`minor abc`), or a key other
than `major`, `minor` and `revision`, is `version.invalid`.

Package (`strict`): `version.invalid`: each line is one of the three keys with
one integer, and each key appears once.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P2). `strict` follows
section 2.3 of the specification, which gives the three lines (the docstring of
`reader` gives it as the source).

#### D05: Sections in an unusual order, such as `[VERSION]` after `[BLOCKS]` or last in the file

| Source | What it does |
|---|---|
| Specification | Silent, except that the file "may end with" `[SIGNATURE]` (section 2.4, `spec:213`). |
| C++ reader | Finds each section by an index of the file (`cpp:870`, `cpp:1750-1801`), so the order does not matter. |
| MATLAB Pulseq | Reads the sections in file order, and rejects `[BLOCKS]` before `[VERSION]` (`read.m:114-116`). |
| pypulseq | Reads in file order; `[BLOCKS]` before `[VERSION]` fails with `UnboundLocalError` (`read_seq.py:139`). |

Example: a run of `valid_1_5_1.seq` with its sections in the order
`[DEFINITIONS]`, `[BLOCKS]`, `[VERSION]`, `[RF]`, `[GRADIENTS]`, `[TRAP]`,
`[ADC]`, `[EXTENSIONS]` with its extension sections, and `[SHAPES]`, and with no
`[SIGNATURE]`: `cpp-siemens`, `strict` and the C++ reader accept it; MATLAB
rejects it ("MUST include [VERSION] section prior to [BLOCKS]"); pypulseq fails
with `UnboundLocalError`. The same file with `[VERSION]` as the last section
made the C++ reader crash in the run
(`tests/seqfiles/undefined/version_last.seq` is such a file).

Package (`cpp-siemens`): reads the sections in any order, as the C++ reader
does: it finds each section through an index of the file. The exception is
`[VERSION]` as the last section, a case of D56: reading it to the end of the
file fails the reader's stream, the seek to `[SHAPES]` then fails, and the
reader reads no shape. With no `[SHAPES]` section the stream stays failed, the
reader skips `[DEFINITIONS]` too, and the file is `definitions.skipped`. With a
`[SHAPES]` section that no event uses, the file is read, with no shape. If an
event uses a shape, the file is `ub.shape-missing` (D21).

Package (`strict`): reads the sections by name in any order
(`reader._sections`).

Reason: `cpp-siemens` reproduces the C++ reader (P1, P2); its failure with
`[VERSION]` last comes from its stream, not from a rule of the format (D56). The
specification is silent on the order, and `strict` accepts any.

#### D06: A blank or `#` line inside a section, with data after it

| Source | What it does |
|---|---|
| Specification | "Comments are specified by a line starting with a hash" (section 2.1, `spec:171`). It does not say whether a blank line or a comment can be inside a section, except in `[SHAPES]` (D07). |
| C++ reader | Its line reader keeps white space (`cpp:2295-2342`). A table ends at an empty line or a `[` line (`cpp:1004`, `cpp:1064`, `cpp:1112`, `cpp:1141`, `cpp:1558`). A `#` line inside a table is read as a row, and its decoding fails: reject. `[VERSION]` and `[EXTENSIONS]` skip blank and `#` lines (`cpp:878`, `cpp:908`, `cpp:1219`). It never reads a line after the end of a table: only `[` lines start a section (`cpp:1762-1769`). |
| MATLAB Pulseq | A section ends at an empty line or a line whose first character is `#` (`read.m:503`, `read.m:564`, `read.m:606`, `read.m:633`). The next line that is not blank or `#` must be a section header, else "Unknown section code" (`read.m:50`, `read.m:192`). |
| pypulseq | A section ends at an empty line or a line that is exactly `#` (`read_seq.py:545`, `read_seq.py:606`, `read_seq.py:656`). A line `# comment` inside a table is read as a row and fails (probe, `bad_syntax_line_after_comment.seq`: `ValueError`). |

Example: `tests/seqfiles/bad_syntax_line_after_comment.seq` has a `#` line
after the first row of `[BLOCKS]`, and the other rows after it: the C++ reader
rejects it (it decodes the `#` line as a block), MATLAB rejects it ("Unknown
section code: 2  50  0  1 …"), pypulseq rejects it. `bad_syntax_line.seq` has
a row `1 2 3` before the first section: the C++ reader accepts it (the row is
never read), MATLAB and pypulseq reject it ("Unknown section code: 1 2 3").
`valid_comments_between_sections.seq` has comments between sections: all
accept (pypulseq: probe).

Package (`cpp-siemens`): ends a table at a blank line, and never reads the rows
after it (only `[` lines start a section), as the C++ reader does: a misreading
(P3). A run with a blank line after block 4 of `valid_1_5_1.seq` reads 4 of its
9 blocks. A `#` line inside a table is read as a row and fails:
`syntax.comment-row`. `[VERSION]` and `[EXTENSIONS]` skip blank and `#` lines. A
data line before the first header is never read (`bad_syntax_line.seq` is read).

Package (`strict`): a blank or `#` line ends a section, as in `read.m`. A data
line after the end and before the next header is `syntax.line`.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P2, P3); pulseq-checks
reports the dropped rows. The specification is silent, so `strict` follows the
reference implementation, `read.m` (the docstring of `reader` says so).

#### D07: A shape whose last sample is followed by the next `shape_id` with no blank line

| Source | What it does |
|---|---|
| Specification | "The end of the shape definition is declared with a blank line." (section 2.9, `spec:602`) |
| C++ reader | The samples of a shape end at an empty line or a line that starts with `s` (`cpp:955-958`). After a shape it reads the next non-comment line (`cpp:978`), and it stops reading `[SHAPES]` when that line does not start with `s` (`cpp:939`). So after a `shape_id` line with no blank line before it, the reader reads the `num_samples` line as the next line and stops: the later shapes are not read. |
| MATLAB Pulseq | The samples end at an empty or `#` line (`read.m:653`). A `shape_id` line before that is read as a sample. |
| pypulseq | The samples end at an empty line or a lone `#` (`read_seq.py:699`). A `shape_id` line is read as a sample with `float()` (`read_seq.py:700`). |

Example: `tests/seqfiles/bad_syntax_shape_no_blank_line.seq` has `shape_id 5`
right after the last sample of shape 4. Matrix: the C++ reader crashes, MATLAB
rejects ("mr.decompressShape() failed for shapeId 4"), pypulseq rejects
("could not convert string to float: 'shape_id 5'", probe).
`bad_syntax_shape.seq` has a shape with no `num_samples` line: C++ rejects,
MATLAB rejects, pypulseq `IndexError` (probe).

Package (`cpp-siemens`): reads as the C++ reader does: it stops reading
`[SHAPES]` at the line that follows a `shape_id` line with no blank line before
it, so the later shapes are lost (the shape before it is read). A block that
uses a lost shape is `ub.shape-missing` (D21):
`bad_syntax_shape_no_blank_line.seq`. A file whose events use none of the lost
shapes is read (run: `valid_1_5_1.seq` with the blank line before its unused
shape 9 removed). A shape without its two header lines is `syntax.shape`.

Package (`strict`): `syntax.shape` for a `shape_id` line with no blank line
before it (the shape before it is still read), and for a shape without its two
header lines. A `#` line ends a shape like a blank line.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P3); a lost shape that an
event uses is the reader's undefined behaviour (Q2). `strict` rejects the
missing blank line, which the specification states only as the end of a shape
(section 2.9); the docstring of `reader` lists `syntax.shape` as added.

#### D08: A section that the format does not have

| Source | What it does |
|---|---|
| Specification | Lists the sections (sections 2.3 to 2.9). It has no rule for another. |
| C++ reader | Indexes every `[` line (`cpp:1762-1769`) and reads only the sections that it knows: it ignores another (matrix: accepts). |
| MATLAB Pulseq | "Unknown section code" (`read.m:192`). |
| pypulseq | `ValueError` "Unknown section code" (`read_seq.py:229-230`). |

Example: `tests/seqfiles/bad_section_unknown.seq` has `[FOO]`.

Package (`cpp-siemens`): reads the file and ignores the section, as the C++
reader does (it reads only the sections that it knows).

Package (`strict`): `section.unknown`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). `strict` reads only the
sections of the format (sections 2.3 to 2.9 of the specification).

#### D09: A `[DELAYS]` section in a file of 1.4.0 or later

| Source | What it does |
|---|---|
| Specification | The table of revisions gives, for 1.4.0, "removed [DELAYS]" (`spec:114`). The binary format lists `[DELAYS]` as "legacy, deprecated" and says "Current readers ignore this section for compatibility with old files" (`spec:743`, `spec:772`). |
| C++ reader | Reads it (`cpp:1172-1192`) and uses it only for a file before 1.4.0 (`cpp:1656-1711`): accepts. |
| MATLAB Pulseq | "Pulseq file revision 1.4.0 and above MUST NOT contain the [DELAYS] section" (`read.m:146-149`). |
| pypulseq | `RuntimeError`: "Pulseq file revision 1.4.0 and above MUST NOT contain [DELAYS] section" (`read_seq.py:184-186`). |

Example: `tests/seqfiles/bad_section_delays.seq`.

Package (`cpp-siemens`): reads the file and ignores `[DELAYS]` from 1.4.0, as
the C++ reader does.

Package (`strict`): `section.delays`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). `strict` follows MATLAB's
rule: a file of 1.4.0 or later "MUST NOT" have `[DELAYS]` (`read.m`).

#### D10: A section that appears twice

| Source | What it does |
|---|---|
| Specification | Silent. |
| C++ reader | Its index keeps the position of the last header with a name (`cpp:1768`), so it reads the last section of that name: accepts. |
| MATLAB Pulseq | Reads both, in file order (matrix: reads). |
| pypulseq | Reads both (probe: reads). |

Example: `tests/seqfiles/bad_section_duplicate.seq` has a second `[TRAP]`.

Package (`cpp-siemens`): reads the last section of a name, as the C++ reader
does (its index keeps the last header).

Package (`strict`): `section.duplicate`, also for two `extension` sections with
one `STRING_ID`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). The specification does not
state this rule for `strict`; the docstring of `reader` lists it as added.

#### D56: The last section with no blank line after it

| Source | What it does |
|---|---|
| Specification | Silent. It declares the end of a shape with a blank line (section 2.9, `spec:602`) and says nothing about a blank line after another section, or about the end of the file. |
| C++ reader | Reads a table with its `getline` up to an empty line or a `[` line. At the end of the file, `is.get()` sets the failbit of the stream (`cpp:2301`), and `getline` also seeks to -1 when it has read nothing (`cpp:2322-2326`). So a section that runs to the end of the file, with no blank line after its last row, leaves the stream failed, and the reader skips each section that it reads after it, in its own order: `[VERSION]` (`cpp:877`), `[SHAPES]` (`cpp:933`), `[RF]`, `[GRADIENTS]`, `[TRAP]`, `[ADC]`, `[DELAYS]`, `[EXTENSIONS]` (`cpp:999-1204`), `[DEFINITIONS]` (`cpp:1399`), `[BLOCKS]` (`cpp:1550`), `[SIGNATURE]` (`cpp:1602`). Only `[SHAPES]` resets the stream, after it has read the section (`cpp:980`). |
| MATLAB Pulseq | Reads a section up to an empty line or the end of the file with `fgetl`: reads the files of the example (run). |
| pypulseq | An event table at the end of the file fails with `AttributeError` (run): `__strip_line` returns -1 at the end of the file, and `__read_events` takes it for a line (`read_seq.py:604-607`, `read_seq.py:757-772`). `[DEFINITIONS]` as the last section is read (run). |

Example: a 1.5.1 file with `[VERSION]`, `[DEFINITIONS]`, `[BLOCKS]` (two blocks,
the first with a trapezoid) and `[TRAP]` as the last section, with no `[SHAPES]`
section. If the last row of `[TRAP]` has no blank line after it (a newline or
none, which is the same to the reader), the C++ reader skips `[DEFINITIONS]` and
rejects the file ("Required: definition AdcRasterTime is not present");
`cpp-siemens` rejects it with `definitions.skipped`; `strict` and MATLAB read
it, and pypulseq fails (`AttributeError`). With a blank line after the row, all
four read it. A `[SHAPES]` section before `[TRAP]` does not help: the reader
resets the stream after `[SHAPES]`, and reads `[TRAP]` later. A `[SHAPES]`
section after `[TRAP]` makes `[SHAPES]` the last section, which ends the file
and resets the stream: the file is read. With `[DEFINITIONS]` as the last
section the reader reads the definitions and then no block: the file is read as
a sequence of 0 blocks, with no error. With `[BLOCKS]` last, the file is read
(only `[SIGNATURE]` comes after it). `[VERSION]` as the last section is D05.

Writers: MATLAB `write.m` and pypulseq `write_seq.py` end every section with a
blank line (`write.m:25-259`, `write_seq.py:14-265`) and write `[SIGNATURE]`
last, which the reader reads last. So no file that they write is affected.

Package (`cpp-siemens`): reads or rejects as the C++ reader does, because the
reader itself reads the file. When the reader skips `[DEFINITIONS]`, the file is
`definitions.skipped`, so that the code names the cause and not a missing
raster. A skipped `[BLOCKS]` is a sequence of 0 blocks (D24). The reader's
skipping of `[SHAPES]` (`[VERSION]` last) is D05.

Package (`strict`): reads the sections by name, and needs no blank line at the
end of a section.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P2). The loss comes from
the state of the reader's stream, not from a rule of the format, and the
specification is silent. `strict` does not follow it.

### Definitions and the syntax of values

#### D11: A required raster that is missing, zero, negative or not finite

| Source | What it does |
|---|---|
| Specification | `GradientRasterTime`, `RadiofrequencyRasterTime`, `AdcRasterTime` and `BlockDurationRaster` are required from 1.4.0 (section 2.5, `spec:267-276`). |
| C++ reader | Rejects a missing one (`cpp:1476-1500`), and rejects `GradientRasterTime nan` (run). It accepts 0 for `AdcRasterTime` and -1e-06 for `RadiofrequencyRasterTime` (runs), and rejects 0 for `GradientRasterTime` when it decodes an arbitrary gradient (`cpp:2115-2121`; matrix, `bad_definitions_raster_invalid.seq`). |
| MATLAB Pulseq | Rejects a missing one when `[DEFINITIONS]` comes after `[VERSION]` (`read.m:80-83`). It reads `GradientRasterTime 0` (matrix), `AdcRasterTime 0` and `RadiofrequencyRasterTime -1e-06` (runs). |
| pypulseq | Takes the raster of its `Opts` when the file has none (`read_seq.py:57-60`); only a missing `BlockDurationRaster` gives a warning (`read_seq.py:91-92`). It does not check a value (probe: reads both fixtures). |

Example: `tests/seqfiles/bad_definitions_raster_missing.seq` (no
`AdcRasterTime`) and `bad_definitions_raster_invalid.seq`
(`GradientRasterTime 0`). The runs changed `valid_1_5_1.seq` to
`AdcRasterTime 0`, `RadiofrequencyRasterTime -1e-06` and
`GradientRasterTime nan`.

Package (`cpp-siemens`): `definitions.raster-missing` for a raster that the file
does not define; `definitions.raster-invalid` for a value that the reader does
not read as a number (`nan`, `inf`, text). A `GradientRasterTime` of 0 or below
is `gradient.raster` when a block has an arbitrary gradient, as in D28
(`bad_definitions_raster_invalid.seq`). The other values are read as the reader
reads them: `AdcRasterTime 0`, `RadiofrequencyRasterTime -1e-06` and
`BlockDurationRaster 0` are read, and so is `GradientRasterTime 0` in a file
with no arbitrary gradient. A raster that is missing only because the reader
skipped `[DEFINITIONS]` is `definitions.skipped` (D56).

Package (`strict`): `definitions.raster-missing`; `definitions.raster-invalid`
for a value that is not one finite number above 0.

Reason: `cpp-siemens` rejects what the C++ reader rejects and reads the rest
(P1, P2). `strict` follows the specification, which requires the four rasters
from 1.4.0: it rejects a file that breaks a "must" rule of the specification,
and a file that does not define layer 1.

#### D12: A definition that appears twice

| Source | What it does |
|---|---|
| Specification | Silent ("a list of user-specified key/value pairs", `spec:240`). |
| C++ reader | A map: the last line wins (`cpp:1432`, `cpp:1445`). |
| MATLAB Pulseq | A `containers.Map`: the last line wins (`read.m:463`). |
| pypulseq | A `dict`: the last line wins (`read_seq.py:479`, `read_seq.py:481`). |

Example: `tests/seqfiles/bad_definitions_duplicate.seq` has `Name` twice (all
three accept; pypulseq: probe).

Package (`cpp-siemens`): the last definition wins, as the C++ reader does (it
keeps a map): `bad_definitions_duplicate.seq` has `Name again`.

Package (`strict`): `definitions.duplicate`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). The specification does not
state this rule for `strict`; the docstring of `reader` lists it as added.

#### D13: A definition or a `[SIGNATURE]` hash whose text reads as a number

| Source | What it does |
|---|---|
| Specification | `<value>` has the type "any" (section 2.5, `spec:247`); `Hash` is a "string" in hexadecimal (section 2.4, `spec:230`). |
| C++ reader | Keeps the text of each definition and its numbers (`cpp:1432`, `cpp:1445`), and the hash as text (`cpp:1618`, `cpp:1631`). |
| MATLAB Pulseq | Holds a definition as numbers when each token reads as a finite number with `str2double`, else as text (`read.m:461-466`). It reads `[SIGNATURE]` with the same function (`read.m:86-91`), so a hash that reads as a finite number is held as a number. Run: a definition of 32 digits is held as a number (`definitions_numeric` of the oracle). |
| pypulseq | Holds a definition as floats when each token reads as one (`read_seq.py:474-479`), and the values of `[SIGNATURE]` as text (`read_seq.py:95-97`). |

Example: `Hash 12345678901234567890123456789012`, a hex digest with no letter.
A double cannot hold its 32 digits.

Package (`cpp-siemens`): the tokens of each definition as text
(`SequenceData.definitions`); only the four rasters are numbers (`Rasters`),
read as the C++ reader reads them. The hash is text.

Package (`strict`): the same: the tokens as text, the four rasters as numbers,
the hash as text.

Reason: the package does not convert the text of a definition to a float. The
example shows why: a double cannot hold the 32 digits of such a hash. The C++
reader keeps the text too.

#### D14: A number with a fraction in an integer column, a sign or `nan`; a row with too few or too many columns; bytes that are not UTF-8

| Source | What it does |
|---|---|
| Specification | Gives the type of each column (integer or float) in its tables; "integer types are stored as 64-bit unsigned integers" (section 2.1, `spec:176`). It does not give the syntax of a number or the encoding of the file. |
| C++ reader | `sscanf`: `30.5` in `[BLOCKS]` fails (reject, `cpp:1565-1577`), and so does `100.5` as the rise time in `[TRAP]` (run); `100.5` as the delay in `[RF]` is read as 100 µs, and the rest of the row moves one column (run: `freq_ppm` 0.5, `use` `0`). `+30` and `nan` are read, a block row of 7 values is read with 0 for the eighth (`cpp:1572`), and a negative delay is read. It does not check the encoding. |
| MATLAB Pulseq | `sscanf("%f")` (`read.m:504`, `read.m:565`): reads `30.5`, `+30`, `nan` and a negative delay. A block row of 7 values fails later (`eventInd(7): out of bound`). A byte that is not UTF-8 fails in `regexp`. |
| pypulseq | Rejects `30.5` in `[BLOCKS]` (`np.fromstring` with `int`, `read_seq.py:546`), reads `+30`, a row of 7 values and a negative delay (probe), and fails on `nan` in `[TRAP]` ("cannot convert float NaN to integer", probe). A byte that is not UTF-8 raises `UnicodeDecodeError`. |

Example: the fixtures `bad_syntax_integer.seq` (`30.5`),
`bad_syntax_integer_plus.seq` (`+30`), `bad_syntax_number.seq` (`nan`),
`bad_syntax_columns.seq` (7 values), `bad_syntax_negative.seq` (delay -10) and
`bad_syntax_encoding.seq` (a byte 0xB5 in a comment).

Package (`cpp-siemens`): per form, as the C++ reader reads it (`sscanf`). `30.5`
in an integer column of `[BLOCKS]`, and `100.5` as the rise time in `[TRAP]`,
are `syntax.row`, and so is a row with too few fields. `100.5` as the delay in
`[RF]` is read as 100 µs, and the rest of the row moves one column (run:
`freq_ppm` 0.5, `use` `0`): a misreading (P3). `+30` and `nan` are read; a block
row of 7 values is read with 0 for the eighth; a negative delay is read; bytes
that are not UTF-8 are read. pulseq-checks reports the misreading.

Package (`strict`): `syntax.integer`, `syntax.number`, `syntax.columns`,
`syntax.negative`, `syntax.encoding`.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P2, P3). The tables and
examples of the specification give the number of columns of each row for the
version, and the type of each value; `strict` reads integers as integers, and
floats as finite numbers. The specification does not state `syntax.negative` and
`syntax.encoding`; the docstring of `reader` lists them as added.

#### D15: An ADC dwell time written with a decimal point, such as `2500.0`

| Source | What it does |
|---|---|
| Specification | `<dwell>` is a float in ns (section 2.8.3, `spec:437`). |
| C++ reader | Holds it as an `int` (`cpp.h:140`) and reads it with `%d` (`cpp:1148`). A dwell written with a decimal point makes the row fail: reject. |
| MATLAB Pulseq | Reads a float (`read.m:140`). |
| pypulseq | Reads a float (`read_seq.py:176`). |

Example: a run of a 1.5.1 file with `AdcRasterTime 1e-10` and the ADC row
`1 8 2500.0 0 0 0 0 0 0`: the C++ reader rejects it ("failed to decode ADC
event"), and so it does with `2500.5`; `strict`, MATLAB and pypulseq read
both, and `cpp-siemens` rejects both. With `2500` all four read it.

Package (`cpp-siemens`): `syntax.row` for a dwell time with a decimal point
(`2500.0` and `2500.5`), as the C++ reader rejects it. Both writers write the
dwell time with `%.0f`, so no file that they write is affected.

Package (`strict`): a float; `raster.adc-dwell` checks it against
`AdcRasterTime`. Both examples are read.

Reason: `cpp-siemens` rejects what the C++ reader rejects (P2): the reader holds
the dwell time as an `int`. The specification types it as a float, and `strict`
follows it.

#### D16: A soft delay row with a fractional offset, such as `-100.5`, or a hint longer than 31 characters

| Source | What it does |
|---|---|
| Specification | Gives an example with the comment `# id num offset factor hint` and the units `us` for the offset; the offsets of the example are integers (section 2.8.4, `spec:550-558`). It has no table of types. |
| C++ reader | Reads `%d%d%d%f` (`cpp:1330`), so an offset with a fraction is cut and the rest is read as the factor. It keeps the first 31 characters of the hint (`cpp:1334-1335`, `cpp.h:194`). |
| MATLAB Pulseq | Reads the offset with `str2num` and 1e-6 (`read.m:173`). |
| pypulseq | Reads the offset with `int()` (`read_seq.py:223`). |

Example: a run of a 1.5.1 file with the soft delay row `1 0 -100.5 1 TE`. The
C++ dump has offset -100 µs, factor 0.5 and hint `1 TE`, and so does
`cpp-siemens`. `strict` reads offset -100.5 µs, factor 1 and hint `TE`. MATLAB
reads the file; pypulseq raises `ValueError`.

Package (`cpp-siemens`): reproduces the misreading of the C++ reader (P3): the
offset `-100.5` is read as -100 µs, and the rest as the factor 0.5 and the hint
`1 TE`. The hint is cut to 31 characters.

Package (`strict`): the offset is a float (µs), and the hint is the whole text.

Reason: `cpp-siemens` reproduces the C++ reader (P1, P3). The example of the
specification has integer offsets and no table of types; `strict` reads the
offset as a float, as MATLAB writes and reads it.

#### D17: An RF `use` letter that is not one of `e r i s p o u`

| Source | What it does |
|---|---|
| Specification | "the initial of one of: excitation, refocusing, inversion, saturation, preparation, other or undefined" (section 2.8.1, `spec:356-357`). |
| C++ reader | Reads any character (`%c`, `cpp:1042`). |
| MATLAB Pulseq | Reads any character (`read.m:120`, `read.m:568`). |
| pypulseq | Reads any text (`read_seq.py:151`). |

Example: `tests/seqfiles/bad_syntax_use.seq` has `x` (all three accept;
pypulseq: probe).

Package (`cpp-siemens`): reads any character as the `use`, as the C++ reader
does (`bad_syntax_use.seq` has `x`).

Package (`strict`): `syntax.use`: one of `e r i s p o u`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). `strict` follows the
specification, which gives the `use` as the initial of one of seven words.

#### D18: A value with more digits than a 32-bit float holds

| Source | What it does |
|---|---|
| Specification | "floating-point numbers are in the 64-bit IEEE 754 floating-point format. Exceptions are `<id>` values, which are 32-bit integers. Shapes are stored as 32-bit single-precision floats." (section 2.1, `spec:176`) |
| C++ reader | Holds amplitudes, `center`, `first`, `last`, offsets and shape samples as `float` (32 bits; for example `cpp.h:90`, `cpp.h:115`, `cpp.h:124`, `cpp:937`). |
| MATLAB Pulseq | Doubles (`sscanf` and `str2double`). |
| pypulseq | Doubles (`float()`). |

Example: a comparison of the package's values with the C++ dump needs a
relative tolerance of about 1e-6 for this reason.

Package (`cpp-siemens`): the model holds the reader's `float` values, converted
to float64 (P6): a trapezoid amplitude `1234567.891` is 1234567.875. IDs are
int64.

Package (`strict`): float64 values and int64 IDs: the same amplitude is
1234567.891.

Reason: `cpp-siemens` gives the values that the C++ reader holds (P1, P6).
`strict` keeps the values of the file.

### IDs and references

#### D19: IDs that are not positive or not unique

| Source | What it does |
|---|---|
| Specification | "IDs must be positive integers"; shape IDs and event IDs of one class must be unique; `[GRADIENTS]` and `[TRAP]` share one set (section 2.2, `spec:181-183`; `spec:403`). |
| C++ reader | Keeps each table in a map by ID: a later row with the same ID replaces the earlier one, and a negative ID is kept (`cpp:1051`, `cpp:1100`, `cpp:1124`, `cpp:1168`). It does not use the block ID (`cpp:1565`, `cpp:1586`). It accepts all four fixtures (matrix). |
| MATLAB Pulseq | Fails on a negative RF ID (`obj(-2): subscripts must be …`) and on a block ID used twice; reads an ADC ID used twice and a gradient ID in both tables (matrix). |
| pypulseq | Reads all four (probe). |

Example: `tests/seqfiles/bad_id_positive.seq` (RF ID -2), `bad_id_unique.seq`
(ADC ID 1 twice), `bad_id_unique_block.seq` (block ID 2 twice),
`bad_id_gradient_unique.seq` (ID 2 in `[GRADIENTS]` and `[TRAP]`).

Package (`cpp-siemens`): reads all four fixtures, and keeps each table as the
C++ reader does: a later row with the same ID replaces the earlier one, a
negative ID is kept, and the block ID is not used. `[GRADIENTS]` and `[TRAP]`
are one library in the reader, so a `[TRAP]` row (read later) replaces a
`[GRADIENTS]` row of the same ID.

Package (`strict`): `id.positive`, `id.unique`, `id.gradient-unique`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). Section 2.2 of the
specification states these rules, and `strict` enforces them.

#### D20: Block IDs that are not in increasing order

| Source | What it does |
|---|---|
| Specification | "There are no restrictions on the ordering of IDs" (section 2.2, `spec:185`). "The blocks are executed sequentially." (section 2.7, `spec:318`) |
| C++ reader | Plays the blocks in file order and does not keep their IDs (`cpp:1565`, `cpp:1586`). |
| MATLAB Pulseq | Stores each block at its ID (`read.m:507-512`), so it plays them in the order of the IDs. |
| pypulseq | Keeps `block_events` as a `dict` by ID in file order (`read_seq.py:549-555`). |

Example: `tests/seqfiles/bad_blocks_order.seq` has the blocks in the order
1, 3, 2, 4, … The C++ dump has block 3 (a gz gradient) second; MATLAB's
`getBlock(2)` is block 2 (gx, gy and an ADC); pypulseq's keys are 1, 3, 2, 4
(runs).

Package (`cpp-siemens`): plays the blocks in file order, as the C++ reader does.
The reader keeps no block ID, so the `id` of a block in the model is its
position from 1.

Package (`strict`): `blocks.order`: block IDs increase through the file, so the
order of the file and the order of the IDs are one play order.

Reason: `cpp-siemens` reproduces the C++ reader (P1). The specification does not
state the rule `strict` enforces; the docstring of `reader` lists it as added.

#### D21: A reference to an event, shape or extension that does not exist

| Source | What it does |
|---|---|
| Specification | Implied by the format (section 2.2). |
| C++ reader | Rejects a block that names an RF, gradient or ADC event that does not exist (`cpp:1579-1584`, `cpp:2250-2262`). A missing shape: crash (matrix, `bad_ref_shape.seq`, `bad_ref_time_shape.seq`). A missing extension list entry: a message, and the list ends there (`cpp:1852-1856`). A missing object: a label is left out (`cpp:1884-1886`); a trigger, rotation, soft delay or RF shim is made empty by the `[]` of its map (`cpp:1868`, `cpp:1877`, `cpp:1906`, `cpp:1915`). A type that no `extension` section declares: a warning (`cpp:1924`). It accepts the three extension fixtures. |
| MATLAB Pulseq | Fails with "out of bound" on a missing event, shape, extension entry or object; reads an undeclared extension type (matrix). |
| pypulseq | `KeyError` on a missing RF event or shape; reads the three extension fixtures (probe). |

Example: `tests/seqfiles/bad_ref_block_rf.seq`, `bad_ref_shape.seq`,
`bad_ref_time_shape.seq`, `bad_ref_extension_entry.seq`,
`bad_ref_extension_object.seq`, `bad_ref_extension_type.seq`.

Package (`cpp-siemens`): `ref.unresolved` for a block that names an RF, gradient
or ADC event that the reader did not read, as the C++ reader rejects it. A block
that uses a shape that was not read is `ub.shape-missing` (the reader takes a
null reference, `cpp:1995`, `cpp:2177`). The extension cases are read as the
reader reads them: an entry that does not exist ends the list; a label whose
object is missing is left out; a missing trigger, rotation, soft delay or RF
shim is empty; an undeclared extension type is read.

Package (`strict`): `ref.unresolved`.

Reason: `cpp-siemens` rejects what the C++ reader rejects (P2), and rejects a
missing shape because the reader's behaviour is undefined (Q2). `strict` follows
the format, which implies that each reference to an event, a shape or an
extension resolves.

#### D22: Time ID -1 for an RF event, or in a 1.4 file

| Source | What it does |
|---|---|
| Specification | Time ID -1 is "1/2 of the default time raster (gradient oversampling case)" for a gradient (section 2.8.2, `spec:395`); for RF, 0 is the default and nothing else is defined (`spec:349`). |
| C++ reader | A 1.4 gradient with time ID -1: accepts (matrix). An RF event with time ID -1: crash (run). |
| MATLAB Pulseq | Reads both. For RF, a time ID that is not above 0 is the default raster (`Sequence.m:526`, `Sequence.m:532-535`). |
| pypulseq | `KeyError: -1` for both: `remove_duplicates` maps the time ID through its table of shapes (`sequence.py:1167`, `sequence.py:1174`). |

Example: `tests/seqfiles/bad_ref_time_id_minus_1_in_1_4.seq`, and a run of a
1.5.1 file with the RF row `1 1000 1 2 -1 50 0 0 0 0 0 e`.

Package (`cpp-siemens`): an RF event with time ID -1 is `ub.rf-time-id-minus-1`:
the reader looks up the time shape -1, which does not exist (run:
`valid_1_5_1.seq` with the RF row `1 1000 1 2 -1 50 0 0 0 0 0 e`). A 1.4
gradient with time ID -1 is read (`bad_ref_time_id_minus_1_in_1_4.seq`).

Package (`strict`): `ref.unresolved`: time ID -1 is valid from 1.5.0 and for a
gradient only.

Reason: `cpp-siemens` rejects the RF event because the reader's behaviour is
undefined (Q2), and reads the 1.4 gradient as the reader does (P1). `strict`
follows section 2.8.2 of the specification, which defines time ID -1 for
gradients only (the docstring of `reader` gives it as the source).

#### D23: A cycle in an extension list

| Source | What it does |
|---|---|
| Specification | "Extensions form zero-terminated single-linked list" (section 2.8.4, `spec:478`). |
| C++ reader | Follows the list until `next` is 0 (`cpp:1849-1928`): no end in 10 s (matrix). |
| MATLAB Pulseq | Follows the list until `next` is 0 (`Sequence.m:1180-1184`), so it has no end on a cycle. Not run: `tests/matlab_oracle/README.md` records a run that did not end in 15 s. |
| pypulseq | `read` does not follow the lists (probe: reads). |

Example: `tests/seqfiles/bad_ref_extension_cycle.seq` (entry 2 points back to
entry 1).

Package (`cpp-siemens`): `ub.extension-cycle`: the reader follows the list with
no end, and in the process it would hold the reader's lock.

Package (`strict`): `ref.unresolved` ("the extension list of this block has a
cycle").

Reason: the C++ reader does not end on a cycle, so `cpp-siemens` rejects the
file (Q2). The specification describes a zero-terminated list, so `strict`
rejects a cycle too.

#### D24: A file with no block

| Source | What it does |
|---|---|
| Specification | "The sequence must declare at least one block." (section 2.7, `spec:318`) |
| C++ reader | Accepts (matrix). |
| MATLAB Pulseq | Reads (matrix). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/bad_blocks_empty.seq`.

Package (`cpp-siemens`): reads the file as an empty sequence (0 blocks), as the
C++ reader does.

Package (`strict`): `blocks.empty`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). The specification says
that the sequence must declare at least one block, and `strict` follows it.

### Timing

#### D25: An event that lasts longer than its block

| Source | What it does |
|---|---|
| Specification | "No event comprising this block is allowed to last longer than the specified block duration. The interpreters must to throw an error, should they detect such condition." (section 2.7, `spec:318`) |
| C++ reader | `load` and `decodeBlock` do not check it (matrix: accepts the three fixtures). |
| MATLAB Pulseq | `read` does not check it (matrix: reads). |
| pypulseq | `read` does not check it (probe: reads). |

Example: `tests/seqfiles/bad_block_event_too_long_rf.seq`,
`bad_block_event_too_long_adc.seq`, `bad_block_event_too_long_trigger.seq`.

Package (`cpp-siemens`): reads the file. The events are as the C++ reader holds
them, and `gradients_at` gives 0 after the end of the block.

Package (`strict`): `block.event-too-long`. The end of an RF event with a time
shape is the end that the C++ reader plays (D37).

Reason: `cpp-siemens` reproduces the C++ reader (P1), which does not check it.
The specification says that the interpreters must throw an error, and `strict`
checks the event that the scanner plays, so the end of an RF event is the end
that the C++ reader plays (D35, D36).

#### D26: A time that is not a multiple of its raster

| Source | What it does |
|---|---|
| Specification | Gradient events start and end on `GradientRasterTime`, and the ramps and flat top of a trapezoid are multiples of it (section 2.6, `spec:290`); the ADC dwell "must be integer multiple" of `AdcRasterTime` (`spec:275`). |
| C++ reader | Does not check (matrix: accepts the five fixtures). |
| MATLAB Pulseq | `read` does not check (matrix: reads). |
| pypulseq | `read` does not check (probe: reads). |

Example: `tests/seqfiles/bad_raster_adc_dwell.seq` (25050 ns on 100 ns),
`bad_raster_gradient_delay.seq` (105 µs), `bad_raster_gradient_end.seq`,
`bad_raster_gradient_flat.seq` (195 µs), `bad_raster_gradient_ramp.seq`
(95 µs).

Package (`cpp-siemens`): reads the file, with the times as written, as the C++
reader does.

Package (`strict`): `raster.adc-dwell`, `raster.gradient-delay`,
`raster.gradient-end`, `raster.gradient-ramp`, `raster.gradient-flat`, with the
tolerance `reader.TOLERANCE_NS` (1 ps).

Reason: `cpp-siemens` reproduces the C++ reader (P1), which does not check it.
The specification states these rules ("must"), and `strict` enforces them. It
compares a time with a raster in integer nanoseconds where the file gives
integers in µs, and with an absolute tolerance of 1 ps for the floats in ns (the
dwell time).

#### D27: A gradient that starts above 0 after a delay, or ends above 0 before the end of its block

| Source | What it does |
|---|---|
| Specification | "Gradients that start at non-zero values must be aligned to the beginning of the block, meaning that the start delay of such gradients must be 0." Gradients that end above 0 "need to be aligned to the end of the block" (section 2.8.2, `spec:420`). |
| C++ reader | Does not check (matrix: accepts both fixtures). |
| MATLAB Pulseq | `read` does not check (matrix: reads). |
| pypulseq | `read` does not check (probe: reads). |

Example: `tests/seqfiles/bad_gradient_nonzero_start_delay.seq` (delay 10 µs,
first 500000 Hz/m) and `bad_gradient_nonzero_end_align.seq` (ends 100 µs
before its block, last 500000 Hz/m).

Package (`cpp-siemens`): reads the file, with the gradients as written, as the
C++ reader does.

Package (`strict`): `gradient.nonzero-start-delay`,
`gradient.nonzero-end-align`.

Reason: `cpp-siemens` reproduces the C++ reader (P1), which does not check it.
`strict` enforces the rules that the specification phrases "need to" or "can be
specified" as "must" (`gradient.nonzero-end-align`, `extension.per-block`): they
state the format, not a preference.

#### D28: An arbitrary gradient on a gradient raster other than 10 µs

| Source | What it does |
|---|---|
| Specification | `GradientRasterTime` is any raster (section 2.5). |
| C++ reader | `decodeBlock` fails for such a gradient: "Shape is on a raster that is different from the system raster" (`cpp:2115-2121`). |
| MATLAB Pulseq | Reads (matrix). |
| pypulseq | Reads (matrix). |

Example: `tests/seqfiles/valid_arbitrary_gradient_4us_raster.seq`
(`GradientRasterTime 4e-06`).

Package (`cpp-siemens`): `gradient.raster`: an arbitrary gradient (time ID 0 or
-1) in a file whose gradient raster is not 10 µs is rejected, as `decodeBlock`
of the C++ reader rejects it.

Package (`strict`): accepts. The C++ reader rejects such a file.

Reason: the failure is a limit of the C++ reader, whose sampling uses a fixed
gradient raster of 10 µs (`SeqBlock::s_gradientRaster`, `cpp:90`); `cpp-siemens`
reproduces it (P2). The specification allows any raster, and `strict` follows
it: `valid_arbitrary_gradient_4us_raster.seq` is read by `strict` and rejected
by `cpp-siemens`.

### Shapes

#### D29: A shape that does not have the number of samples that it declares

| Source | What it does |
|---|---|
| Specification | "The number of points after decompressing all samples defined in a shape must be equal the number declared in `<num_samples>`." (section 2.9, `spec:626`) |
| C++ reader | Does not check (matrix: accepts). |
| MATLAB Pulseq | Reads (matrix). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/bad_shape_length.seq` declares 16 samples for a shape
that decompresses to 15.

Package (`cpp-siemens`): as the C++ reader reads it. A shape that decompresses
to more than `num_samples`, or that ends in a repeated value with no count, is
`ub.shape-decompression`: the reader writes or reads past its buffer. A shorter
shape is read, and its last value repeats to `num_samples` (run: a shape of 10
values declared with 12 gives 12, the last 3 equal). `bad_shape_length.seq` is
read.

Package (`strict`): `shape.length`.

Reason: `cpp-siemens` reproduces the C++ reader (P1) for a shorter shape, and
rejects a longer one because the reader's behaviour is undefined (Q2). Section
2.9 of the specification states the rule ("must"), and `strict` enforces it.

#### D30: An amplitude shape with a sample outside [-1, 1]

| Source | What it does |
|---|---|
| Specification | "When used as amplitude shapes for gradient or RF objects, the decompressed samples must be in the normalised range of [-1, 1]" (section 2.9, `spec:624`). |
| C++ reader | Clamps each sample of an arbitrary gradient to [-1, 1] (`checkGradient`, `cpp:2265-2278`) and each RF magnitude sample to [0, 1] (`checkRF`, `cpp:2282-2291`), with no message. |
| MATLAB Pulseq | Does not check (matrix: reads). |
| pypulseq | Does not check (probe: reads). |

Example: `tests/seqfiles/bad_shape_range.seq` has a gradient sample of 1.5.
The C++ dump has 1 for it (run): the scanner plays 1 where the file says 1.5.

Package (`cpp-siemens`): clamps each sample of an arbitrary gradient to [-1, 1],
as the C++ reader does (`bad_shape_range.seq`: the sample 1.5 is 1).

Package (`strict`): `shape.range`, within `reader.RANGE_TOLERANCE` (1e-9).

Reason: `cpp-siemens` reproduces the C++ reader (P1). The specification states
the rule, and `strict` enforces it. The tolerance is the largest error of
decompression found on the oracle files, rounded up, so that no oracle file
fails the rule: the text of a file has 9 significant digits, and decompression
adds to the error.

#### D31: An RF magnitude shape with a sample below 0

| Source | What it does |
|---|---|
| Specification | Allows [-1, 1] for an amplitude shape (`spec:624`). |
| C++ reader | Sets a negative sample to 0 (`cpp:2287`), with no message. |
| MATLAB Pulseq | Writes the magnitude as an absolute value (`registerRfEvent`, `Sequence.m:584-586`). It reads a negative sample (matrix). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/bad_shape_rf_magnitude_negative.seq` has a magnitude
sample of -0.5. The C++ dump has 0 for it (run).

Package (`cpp-siemens`): sets a negative magnitude sample to 0, as the C++
reader does (`bad_shape_rf_magnitude_negative.seq`).

Package (`strict`): `shape.rf-magnitude-negative`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). The rule of `strict` is
stricter than the specification, which allows [-1, 1]. It agrees with the
reference implementations: MATLAB writes the magnitude as an absolute value, and
the scanner's reader sets a negative sample to 0. It has the tolerance of
`shape.range`.

#### D32: An RF phase shape with a sample outside [0, 1)

| Source | What it does |
|---|---|
| Specification | Silent on the range of the phase shape. |
| C++ reader | Multiplies the phase by 2π (`cpp:2005`) and clamps it to [0, 2π - 1e-4] (`cpp:2288-2289`), with no wrap and no message. |
| MATLAB Pulseq | Writes the phase as a fraction of a turn in [0, 1) (`Sequence.m:587-589`). It reads any phase and plays `exp(1i 2π phase)` (`Sequence.m:524`). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/bad_shape_rf_phase_range.seq` has a phase of 1.5 turns
(3π rad, the same as π). The C++ dump has 6.28308535 rad (2π - 1e-4) for each
sample (run): the scanner plays about 0 rad where the file says π.

Package (`cpp-siemens`): clamps the phase to [0, 2π - 1e-4], as the C++ reader
does (`bad_shape_rf_phase_range.seq`: 6.2830853 rad for each sample).

Package (`strict`): `shape.rf-phase-range`. A sample of 1 within
`RANGE_TOLERANCE` is a full turn and is allowed.

Reason: `cpp-siemens` reproduces the C++ reader (P1). For `strict`, a clamped
phase is a different pulse than the file says.

#### D33: A shape with no sample that an event uses

| Source | What it does |
|---|---|
| Specification | Silent. |
| C++ reader | Undefined behaviour: it takes `&waveform[0]` of an empty vector and copies from `samples.front()` of an empty vector (`cpp:1995`, `cpp:2203`). The macOS build crashes (matrix, `bad_shape_empty.seq`); the Linux build accepts the file. |
| MATLAB Pulseq | Fails (matrix: "Unknown section code: Hash …"). |
| pypulseq | Fails (probe: "could not convert string to float: '[SIGNATURE]'"). |

Example: `tests/seqfiles/bad_shape_empty.seq` has `num_samples 0` for the
magnitude and phase of an RF event.

Package (`cpp-siemens`): `ub.shape-empty`, for a shape that an event uses: the
reader's behaviour is undefined.

Package (`strict`): `shape.empty`, for a shape that an RF event or an arbitrary
gradient uses.

Reason: the C++ reader's behaviour depends on the build, so `cpp-siemens`
rejects the file (Q2). The rule of `strict` is stricter than the specification,
which says nothing; MATLAB fails on such an event.

#### D34: The shapes of one event with different numbers of samples

| Source | What it does |
|---|---|
| Specification | Silent. |
| C++ reader | Crash (matrix). `checkRF` reads the phase at each index of the magnitude (`cpp:2284-2290`). |
| MATLAB Pulseq | Fails: "product: nonconformant arguments" (`Sequence.m:524`; matrix). It asserts equal lengths for a gradient with a time shape (`Sequence.m:1401`). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/bad_shape_event_length.seq`: an RF event with a
magnitude of 100 samples and a phase of 8.

Package (`cpp-siemens`): a phase shorter than the magnitude, or a resampling
that reads past either shape, is `ub.rf-shape-lengths`
(`bad_shape_event_length.seq`, `checkRF` reads past the phase). A longer phase
is read, and the reader plays the length of the magnitude (run: a phase of 110
samples with a magnitude of 100 gives 100).

Package (`strict`): `shape.event-length`.

Reason: `cpp-siemens` rejects the cases where the reader reads past a shape
because its behaviour is undefined (Q2), and reproduces the longer phase (P1).
The specification does not state the rule of `strict`; the docstring of `reader`
lists it as added.

### RF decoding

![What MATLAB reads and what the C++ reader plays, for three RF time shapes](figures/discrepancy-rf-time-shapes.svg)

The figure is made from the outputs of the readers (appendix B). Each panel is
one RF event of amplitude 1000 Hz with a Hann magnitude. The dots are MATLAB's
`rf.t` and `|rf.signal|`, the steps are the samples of the C++ dump, each for
one dwell time, and the crosses are the package's `RfEvent.t` and
`RfEvent.magnitude`.

#### D35: An RF time shape stored compressed in 3 or 4 values (a regular step)

| Source | What it does |
|---|---|
| Specification | The time shape gives "the time sampling points, specified in the units of `RadiofrequencyRasterTime`" (section 2.8.1, `spec:349`). |
| C++ reader | Takes a time shape that is stored compressed in 3 or 4 values as regular: the dwell time is the second stored value times the RF raster, and it does not decompress the shape (`cpp:2015-2021`). It keeps only the samples and the dwell time (`cpp:2063-2067`), so the first time of the shape is not used. |
| MATLAB Pulseq | `t` is the decompressed shape times the RF raster (`Sequence.m:526-531`). It writes a time shape `0.5 1 1 N-3` as time ID 0 (`Sequence.m:607-614`). |
| pypulseq | As MATLAB (`sequence.py:1233-1239`). |

Example: the time shape `10 1 1 17` of 20 samples (times 10, 11, …, 29 µs;
middle panel). MATLAB puts the samples at 10 to 29 µs; the C++ reader plays
them from 0 to 20 µs. The fixture `tests/seqfiles/bad_shape_rf_time_grid.seq`
has `1 1 98` (times 1 to 100 µs, which the reader plays at 0.5 to 99.5 µs);
matrix: the C++ reader, MATLAB and pypulseq (probe) accept it. The top panel is
a regular shape on its cell centres (`1 2 2 17`: 1, 3, …, 39 µs): there the
samples agree, and only the end differs (D37).

Package (`cpp-siemens`): plays the event as the C++ reader does, off-centre
times included (P5): a regular time shape has the dwell time of its second
stored value, and its first time is not used (run: the time shape `10 1 1 17` of
20 samples gives a dwell of 1 µs and a shape duration of 20 µs).
`bad_shape_rf_time_grid.seq` is read.

Package (`strict`): decodes the event as the C++ reader plays it
(`events.decode_rf`, `model._rf_time_step`): `t = (i + 0.5) d`, `shape_dur = N
d`. `shape.rf-time-grid` rejects a regular shape whose times are not the centres
of its cells, within `reader.RF_TIME_TOLERANCE` (1e-6 RF rasters).

Reason: `cpp-siemens` plays what the C++ reader plays (P1, P5). `strict` decodes
the event as the scanner's reader plays it, and rejects a regular shape whose
times are not the centres of its cells, because the reader would play its
samples at other times than the file says. In general both follow the C++ reader
here: MATLAB is a writer, not an ideal reader.

#### D36: An RF time shape stored in any other form

| Source | What it does |
|---|---|
| Specification | As D35. |
| C++ reader | Resamples the pulse to the RF raster (`cpp:2022-2050`): `int(0.5 + t_last)` cells; in cell `c` the index goes to the next sample when the time of the sample at the index is below `c + 1`, and the cell plays the sample at the index. The index can reach the number of samples, one past the last stored sample (`cpp:2039-2045`): for such a shape the loop reads after the end of the stored samples. |
| MATLAB Pulseq | The times of the shape (`Sequence.m:530`). |
| pypulseq | The times of the shape (`sequence.py:1238`). |

Example: the bottom panel, an uncompressed time shape 1, 2, 4, 7, 10 µs with
magnitudes 0.2, 0.6, 1, 0.6, 0.2. MATLAB has each sample at its time; the C++
reader plays 10 cells of 1 µs: 0.2, 0.6, 1, 1, 0.6, 0.6, 0.6, 0.2, 0.2, 0.2
(times 1000 Hz). The fixture `tests/seqfiles/bad_shape_rf_time_end.seq` has the
time shape 0, 99.6: the loop reads past the 2 stored samples; matrix: the
macOS build of the C++ reader crashes (the Linux build accepts the file),
MATLAB reads, pypulseq reads (probe).

Package (`cpp-siemens`): resamples the pulse to the RF raster as the C++ reader
does (P5), artefacts included (run: the time shape 1, 2, 4, 7, 10 µs of the
example gives the 10 cells listed). When the loop reads past the stored samples,
the reader's behaviour is undefined: `ub.rf-time-overrun`
(`bad_shape_rf_time_end.seq`).

Package (`strict`): decodes the event as the C++ reader plays it
(`model._rf_resample`). `shape.rf-time-end` rejects a shape for which the index
of the loop reaches the number of stored samples.

Reason: `cpp-siemens` plays what the C++ reader plays (P1, P5), and rejects the
read past the end (Q2). `strict` decodes the event as the reader plays it:
`round(t_last)` samples on the RF raster, each the stored value that the
reader's loop picks. `shape.rf-time-end` rejects an RF time shape whose last
time rounds up (`int(0.5 + t_last) > t_last`): then the reader reads past the
stored samples, which is undefined behaviour in the scanner. The reason is that
of `shape.empty` (D33).

#### D37: An RF time shape whose last time is before the end of the last sample's dwell

| Source | What it does |
|---|---|
| Specification | Silent on the end of a pulse with a time shape. |
| C++ reader | `shape_dur` is the dwell time times the number of samples (`cpp:2063`). |
| MATLAB Pulseq | With a time shape, `shape_dur` is the last time rounded up to the RF raster (`Sequence.m:531`); without one, the number of samples times the RF raster (`Sequence.m:535`). |
| pypulseq | As MATLAB (`sequence.py:1239`, `sequence.py:1242`). |

Example: the top panel of the figure, the regular time shape `1 2 2 17` (20
samples, times 1, 3, …, 39 µs): MATLAB ends the pulse at 39 µs, the C++ reader
at 40 µs. With a block of 39 µs, MATLAB's pulse fits and the C++ reader's does
not. No fixture of `tests/seqfiles/` has an RF event that only the C++ end
makes too long.

Package (`cpp-siemens`): `shape_dur` is the dwell time times the number of
samples, as in the C++ reader (run: the shape `1 2 2 17` with 20 samples gives 2
µs and 40 µs).

Package (`strict`): `RfEvent.shape_dur` and the end that `block.event-too-long`
checks are those of the C++ reader.

Reason: `cpp-siemens` plays what the C++ reader plays (P1); `strict` uses the
end that the scanner plays, as in D25, D35 and D36.

#### D38: An RF event of a 1.4 file, which has no `center` column

| Source | What it does |
|---|---|
| Specification | A 1.4 file has no `center` column (the 1.5 table adds it, `spec:350`). |
| C++ reader | Sets `center` to -1, "mark as invalid" (`cpp:1037`). |
| MATLAB Pulseq | Computes it with `mr.calcRfCenter` (`read.m:302-309`). |
| pypulseq | Computes it with `calc_rf_center` (`read_seq.py:327-339`). |

Example: `tests/seqfiles/oracle/koma_v1.4_fid.seq`, RF row
`1 2500 1 2 3 100 0 0`. Run: MATLAB 50 µs, pypulseq 50 µs (`get_block`), C++
-1 µs, both interpreters NaN in the model, and `strict` `None` in
`RfEvent.center`. All give
the use `u` (undefined).

Package (`cpp-siemens`): `center` is NaN in the model; the reader holds -1
("invalid"), which `decode_block` gives as `center_us`. The `use` is `u`.

Package (`strict`): `center` absent (NaN in the model); `use` is `u`.

Reason: layer 1 holds the values of the file, and a 1.4 file has no center: the
reader's -1 is a mark, not a value. A caller that needs the center computes it
(pulseq-reports uses `calc_rf_center` today).

### Gradient decoding

#### D39: A 1.4 arbitrary gradient on the default raster, which has no `first` and `last` columns

| Source | What it does |
|---|---|
| Specification | A 1.4 file has no `first` and `last`; the samples of time ID 0 are at the centres of the raster cells (section 2.6, `spec:290`), so the values at the two ends of the event are not in the file. |
| C++ reader | Sets `first` and `last` to `FLOAT_UNDEFINED` (1.18e-38, `cpp:1085-1086`, `cpp.h:128`). `gradientsAt` interpolates to them at the ends of the event (`cpp:3681`, `cpp:3686`), so the waveform goes to about 0 there. |
| MATLAB Pulseq | `first` is the `last` of the gradient of the block before when that gradient ends at the end of its block, else 0 (`read.m:344-350`, `read.m:365-368`). `last` is an alternating sum from `first`: `edge[k+1] = 2 w[k] - edge[k]` (`read.m:356-361`). |
| pypulseq | `first` as MATLAB (`read_seq.py:372-380`); `last` is the extrapolation `(3 w[-1] - w[-2]) / 2` (`read_seq.py:389`). |

Example: `tests/seqfiles/oracle/koma_v1.4_gr-uniformly-shaped.seq`, a half
sine of 10 samples (amplitude 42576 Hz/m, first and last sample 0) in three
blocks. Run: `last` is 0 Hz/m in MATLAB, -7280.92 Hz/m in pypulseq, and
1.18e-38 Hz/m in the C++ reader. `tests/seqfiles/bad_layer1_gradient_ends.seq`
is the fixture of the rule; pypulseq fails on it with `TypeError` (matrix).

Package (`cpp-siemens`): reads the file. The model holds the reader's
`FLOAT_UNDEFINED` (1.18e-38 Hz/m) for `first` and `last`, and `gradients_at`
interpolates to it at the ends of the event, so the waveform goes to about 0
there (P7; run: `koma_v1.4_gr-uniformly-shaped.seq`, 1.18e-38 Hz/m at 0 and 100
µs).

Package (`strict`): `layer1.gradient-ends` rejects a 1.4 file with an arbitrary
gradient of time ID 0.

Reason: `cpp-siemens` follows the reader's default (P7). For `strict` the file
does not define the values at the two ends of such a gradient; it rejects the
file with a message that names the gradients and says that Pulseq 1.5 stores the
ends. Other 1.4.x files are read: trapezoids and time-shaped gradients define
their ends.

#### D40: A 1.4 arbitrary gradient with a time shape, which has no `first` column

| Source | What it does |
|---|---|
| Specification | As D39: a 1.4 file has no `first`. |
| C++ reader | Holds `FLOAT_UNDEFINED` (`cpp:1085-1086`), but a gradient with a time shape is an extended trapezoid there (`cpp.h:698`), and `gradientsAt` starts it at the amplitude times its first sample (`cpp:3628-3630`). |
| MATLAB Pulseq | `first` from the block before, as in D39 (`read.m:350`); `last` is the last sample (`read.m:352-354`). |
| pypulseq | As MATLAB (`read_seq.py:380`, `read_seq.py:383-385`). |

Example: `tests/seqfiles/valid_1_4_1.seq`, block 3: gradient 2 (amplitude
400000 Hz/m, samples 0.2, 0.6, 1, 0.6, 0.2 at the times 0, 1, 3, 6, 10) after
a block with no gz. Run: MATLAB `first` 0 Hz/m; `strict` 80000 Hz/m, the
value of the first sample, which is at time 0.

Package (`cpp-siemens`): reads the file. The model holds the reader's
`FLOAT_UNDEFINED` for `first` and `last`, and `gradients_at` starts the gradient
at the amplitude times its first sample (run: 80000 Hz/m at 0 µs for the
gradient of `valid_1_4_1.seq`). A time shape that starts after 0 is read too:
with the times 1, 2, 4, 7, 10 µs, `gradients_at` gives -80000 Hz/m at 0 µs, 0 at
5 µs and 80000 Hz/m at 10 µs, since the first segment extends backwards.

Package (`strict`): `first` and `last` are the amplitude times the first and
last samples. `layer1.gradient-ends` also rejects a 1.4 time shape whose first
time is not 0 (within `reader.FIRST_TIME_TOLERANCE`).

Reason: `cpp-siemens` plays what the C++ reader plays (P1, P7). `strict` keeps
the value that the file gives at the start of the event, the amplitude times the
first sample. It rejects a 1.4 time shape that does not start at 0, since then
the file has no value at the start of the event.

#### D41: An arbitrary gradient on the default raster (time ID 0), whose samples are at the centres of the raster cells

![MATLAB's restored values at the raster edges, and the lines of the package and the C++ reader](figures/discrepancy-arbitrary-gradient-edges.svg)

| Source | What it does |
|---|---|
| Specification | The samples are at the centres of the raster cells (section 2.6, `spec:290`). Silent between them. |
| C++ reader | `gradientsAt` interpolates linearly between the samples, from `first` at the start to the first sample and from the last sample to `last` at the end (`cpp:3653-3693`). |
| MATLAB Pulseq | `waveforms_and_times` restores values at the raster edges with an alternating sum from `first` (`Sequence.m:2009-2021`, `restoreAdditionalShapeSamples.m:10-31`): where the restored value differs from the mean of the two neighbouring samples by more than 2e-5 of the largest sample, it takes the restored value. When the restored end differs from `last` by more than that, it skips the restoration and joins `first`, the samples and `last` (`restoreAdditionalShapeSamples.m:14-27`). |
| pypulseq | `waveforms` joins `first`, the samples and `last` with lines; the restoration is a `TODO` (`sequence.py:1583-1604`). |

Example: the figure: the samples of the half sine of D39 in a 1.5.1 file with
`first` and `last` 0. MATLAB's polyline has only the raster edges, with
29124, 25611, 48133 and 35726 Hz/m at 20, 30, 40 and 50 µs, where the samples
rise smoothly; the package and the C++
reader draw straight lines between the samples.

Package (`cpp-siemens`): straight lines between the sample centres, and to
`first` and `last`, as `gradients_at` of the C++ reader does (run: block 2 of
`valid_1_5_1.seq`).

Package (`strict`): straight lines between the sample centres, and to `first`
and `last` (`docs/implementation.md` §1).

Reason: `cpp-siemens` plays what the C++ reader plays (P1). `strict` draws the
same lines, as `docs/implementation.md` section 1 describes. Layer 1 does not
guess.

#### D42: A gap between two gradient events on one axis

| Source | What it does |
|---|---|
| Specification | Silent on the waveform between events. |
| C++ reader | `gradientsAt` works inside one block (`cpp:3561-3566`); it does not join blocks. |
| MATLAB Pulseq | `waveforms_and_times` adds a ramp to 0 over half a raster after an event that ends at a value other than 0, and a ramp from 0 before one that starts at such a value, when the gap is longer than one raster, with a warning; a value of at most 1e-6 Hz/m is set to 0 instead (`Sequence.m:2114-2134`). |
| pypulseq | `waveforms` joins the points of the events with a straight line across the gap (run). |

Example: a run of a 1.5.1 file of three blocks: a gradient from 0 to
30000 Hz/m (0 to 30 µs), a delay of 40 µs, a gradient from 15000 Hz/m to 0
(70 to 100 µs). MATLAB's polyline has (35 µs, 0) and (65 µs, 0); pypulseq's
goes straight from (30 µs, 30000) to (70 µs, 15000).
[`docs/implementation.md` §1.3](implementation.md#13-the-gaps) has the figure
of the four cases, `figures/waveform-gaps.svg`.

Package (`cpp-siemens`): plays one block at a time, as the C++ reader does:
`gradients_at` gives the gradients inside a block and 0 after its end, and a
block with no gradient event gives 0 (run: the three blocks of the example give
0 in the gap). It joins no blocks; the timeline across blocks comes with task
R14.

Package (`strict`): MATLAB's ramps, `docs/implementation.md` §1.3 and §1.9 (in
the waveform code, not in the reader).

Reason: `cpp-siemens` shows what the C++ reader plays, and the reader decodes
one block at a time. `strict`: `docs/implementation.md` §1 gives the waveform as
"the gradient waveform of MATLAB Pulseq", and §1.1 gives the reason: a step can
be the largest slew of a file and is part of the PNS.

#### D43: An oversampled arbitrary gradient (time ID -1)

| Source | What it does |
|---|---|
| Specification | "-1 means 1/2 of the default time raster (gradient oversampling case)" (section 2.8.2, `spec:395`, `spec:420`). |
| C++ reader | Keeps only the samples at the centres of the raster, every second stored sample (`cpp:2123-2135`, the default sampling of the driver). |
| MATLAB Pulseq | `tt = (1:n)/2 dt`, `shape_dur = (n + 1)/2 dt`, and asserts an odd number of samples (`Sequence.m:1384-1390`). |
| pypulseq | `read` fails with `KeyError: -1` in `remove_duplicates` (`sequence.py:1167`; matrix: `oracle/koma_v1.5_spiral.seq`, `valid_1_5_0.seq`). |

Example: `tests/seqfiles/oracle/koma_v1.5_spiral.seq`.

Package (`cpp-siemens`): the reader's sampling mode of an oversampled gradient,
`CppSiemens(oversampling=...)`. The default `"center"` keeps the samples at the
centres of the raster, every second stored sample (run: block 3 of
`koma_v1.5_spiral.seq` has 2112 samples; `"edge"` 2111 and `"preserve"` 4223,
all of them).

Package (`strict`): all the samples, with MATLAB's times
(`events.decode_gradients`).

Reason: `cpp-siemens` follows the reader's default, as the scanner's interpreter
can set another (P7, P18). `strict` decodes the oversampled spiral (time ID -1),
on which pypulseq fails.

#### D44: An ADC event with a phase modulation shape

| Source | What it does |
|---|---|
| Specification | "Shape ID of the phase modulation", with no unit (section 2.8.3, `spec:443`). |
| C++ reader | Uses the decompressed shape as radians: its multiplication by 2π is commented out (`cpp:3059-3060`). |
| MATLAB Pulseq | Holds the decompressed shape with no factor (`Sequence.m:1431-1453`). |
| pypulseq | Not checked for this document. |

Example: `tests/seqfiles/valid_1_5_1.seq`, ADC 2 with phase shape 8.

Package (`cpp-siemens`): the reader uses the decompressed shape as radians. The
model holds the shape ID of the ADC event (`adc['phase_shape']`) and the shape
as stored, with no factor (run: ADC 2 of `valid_1_5_1.seq` used by a block).

Package (`strict`): `AdcEvent.phase_modulation` is the decompressed shape as
stored, with no factor.

Reason: the specification gives the shape no unit, and the C++ reader uses it as
radians. `cpp-siemens` reproduces the reader (P1); `strict` keeps the
decompressed shape as stored, or `None` when the event has no phase shape.

### Extensions

#### D45: An unknown extension that the file does not require

| Source | What it does |
|---|---|
| Specification | "The interpreter MUST detect unknown extensions and MAY chose to ignore them. It is recommended that the interpreter issues a warning in this case." (section 2.8.4, `spec:460`) |
| C++ reader | A warning for the header and a message for each row, and goes on (`cpp:1245-1249`, `cpp:1375-1377`). Run: `oracle/koma_v1.5_unknown_ext.seq` with a `[SIGNATURE]` section added after its extensions: accepts. |
| MATLAB Pulseq | A warning, and skips the section (`read.m:185-189`). |
| pypulseq | `ValueError` "Unknown section code: extension …" (`read_seq.py:229-230`). It reads only TRIGGERS, LABELSET, LABELINC and DELAYS (`read_seq.py:193-224`). |

Example: `tests/seqfiles/oracle/koma_v1.5_unknown_ext.seq` (UNKNOWN1,
UNKNOWN2). `valid_1_5_1.seq` and most `bad_*` fixtures have an extension
UNKNOWN.

Package (`cpp-siemens`): reads the section and does not interpret it, as the C++
reader does; its `STRING_ID` is in `SequenceData.skipped_extensions`
(`valid_1_5_1.seq`: `UNKNOWN`).

Package (`strict`): the same: its `STRING_ID` is in
`SequenceData.skipped_extensions`.

Reason: the specification allows a reader to ignore an unknown extension that
the file does not require. Both interpreters read such a section and do not
interpret it, as the C++ reader does.

#### D46: A file whose last section that starts with `[` is `[EXTENSIONS]`

| Source | What it does |
|---|---|
| Specification | Silent on the order of the sections. |
| C++ reader | Reads `[EXTENSIONS]` up to the next section header of its index, and rejects the file when there is none: "failed find the end of the section while reading EXTENSIONS" (`cpp:1202-1211`). Its index has only the lines that start with `[` (`cpp:1762-1769`), so the `extension` sections after `[EXTENSIONS]` do not end it. |
| MATLAB Pulseq | Reads (matrix). |
| pypulseq | Reads (probe). |

Example: `tests/seqfiles/oracle/koma_v1.5_unknown_ext.seq` ends with its
`extension` sections and has no `[SHAPES]` or `[SIGNATURE]`. Runs: it is
rejected; the same file with `UNKNOWN1` and `UNKNOWN2` renamed to `LABELSET`
and `LABELINC` is rejected with the same message; each of the two is accepted
with a `[SIGNATURE]` section added at the end.

Package (`cpp-siemens`): `section.extensions-last`, as the C++ reader rejects it
(run: `koma_v1.5_unknown_ext.seq` is rejected; with a `[SIGNATURE]` section
added at the end it is read, and so is the version with `LABELSET` and
`LABELINC`).

Package (`strict`): accepts.

Reason: `cpp-siemens` rejects what the C++ reader rejects (P9, P2). The
specification does not set an order of the sections. The reader rejects this
file because of how it finds the end of `[EXTENSIONS]`, not because of a rule of
the format, so `strict` does not follow it here. Both writers write
`[EXTENSIONS]` before `[SHAPES]` and `[SIGNATURE]`, so a file of theirs ends
with `[EXTENSIONS]` only when it has no shape and no signature.

#### D47: An unknown extension that the file requires

| Source | What it does |
|---|---|
| Specification | From 1.5.1: "If any of the declared required extensions are unknown to the interpreter, it MUST generate an error and MUST not attempt executing the sequence." (section 2.8.4, `spec:460`) |
| C++ reader | Rejects (`cpp:1505-1538`). |
| MATLAB Pulseq | `read.m` does not read `RequiredExtensions` (it appears only in `write.m` and `writeBinary.m`): reads (matrix). |
| pypulseq | No code reads `RequiredExtensions`. |

Example: `tests/seqfiles/bad_extension_required_unknown.seq`
(`RequiredExtensions ROTATIONS FOO`).

Package (`cpp-siemens`): `extension.required-unknown`, as the C++ reader rejects
it.

Package (`strict`): `extension.required-unknown`.

Reason: from 1.5.1 the specification says that the interpreter must generate an
error, and the C++ reader rejects the file (P2).

#### D48: A block with more than one ROTATIONS or RF_SHIMS object

| Source | What it does |
|---|---|
| Specification | "Only one rotation extension object can be specified per block." "Only one RF shimming extension object can be specified per block." (section 2.8.4, `spec:567`, `spec:584`) |
| C++ reader | A warning, and keeps the first (`cpp:1872-1874`, `cpp:1910-1912`): accepts. |
| MATLAB Pulseq | "Only one rotation extension object per block is allowed" (`Sequence.m:1300`; the same for RF shims, `Sequence.m:1287`). |
| pypulseq | Rejects every file with ROTATIONS or RF_SHIMS (`read_seq.py:229-230`). |

Example: `tests/seqfiles/bad_extension_per_block.seq` (two ROTATIONS entries in
one list).

Package (`cpp-siemens`): reads the file and keeps the first object, as the C++
reader does (it warns).

Package (`strict`): `extension.per-block`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). `strict` is as in D27: the
specification says "can", and `strict` enforces it as "must".

#### D49: A block that plays a rotation, or a quaternion that is not normalized

| Source | What it does |
|---|---|
| Specification | A rotation is "a normalized rotation quaternion" applied to the whole block (section 2.8.4, `spec:567`). |
| C++ reader | Rejects a quaternion whose norm is more than 1e-3 from 1, and divides the others by their norm (`cpp:1286-1292`). |
| MATLAB Pulseq | Divides each quaternion by its norm (`read.m:182-184`), and rotates the gradients of the block in `waveforms_and_times` (`Sequence.m:1988-1999`). |
| pypulseq | Rejects every file with ROTATIONS (`read_seq.py:229-230`). |

Example: runs of a 1.5.1 file whose block plays the rotation `1 1.01 0 0 0`: the
C++ reader rejects it, MATLAB reads it, pypulseq rejects it, `strict` reads it,
and `cpp-siemens` rejects it (`rotation.norm`). With `1 1.0005 0 0 0` the C++
reader accepts it. `tests/seqfiles/oracle/pulseq_make_radial.seq` and
`koma_v1.5_rotation_radial_tiny.seq` have rotations.

Package (`cpp-siemens`): divides a quaternion whose norm is within 1e-3 of 1 by
its norm, as the C++ reader does (`1 1.0005 0 0 0` is read as `1 1 0 0 0`), and
rejects another with `rotation.norm` (`1 1.01 0 0 0`, and a quaternion of norm
0). The rotation is not applied to the gradients yet (task R9, decision Q3).

Package (`strict`): `read_seqfile` reads the quaternions as the file writes
them, with no check of the norm (`SequenceData.extensions.rotations`). The
measurements do not support rotations.

Reason: `cpp-siemens` rejects what the C++ reader rejects (P2). `strict` does
not check the norm, and `load` refuses a sequence with the rotation extension
(`extensions.refuse_rotations`).

#### D50: A `LABELSET` or `LABELINC` row with a label name that a reader does not know

| Source | What it does |
|---|---|
| Specification | Lists the counters and flags that "are supported at the moment" (section 2.8.4, `spec:519-520`). |
| C++ reader | `decodeLabel` returns "unknown"; the reader prints a message and leaves the label out (`cpp:1302-1310`). |
| MATLAB Pulseq | Fails (run: "nonconformant arguments"; `read.m:165` looks the name up in `mr.getSupportedLabels`). |
| pypulseq | `ValueError` (run; `read_seq.py:204-205`). |

Example: a run of a 1.5.1 file with `extension LABELSET 1` and the row
`1 3 FOO`: `cpp-siemens`, `strict` and the C++ reader accept it; MATLAB and
pypulseq reject it.

Package (`cpp-siemens`): reads the file and leaves the label out, as the C++
reader does (run: `1 3 FOO` gives no label).

Package (`strict`): keeps the name as text (`Extensions.labelset`), with no
check.

Reason: `cpp-siemens` reproduces the C++ reader (P1). `strict` does not check
the name; labels do not change the waveforms.

### Values that a reader changes

#### D51: Two event rows with equal values and different IDs, such as amplitudes 0 and -0

| Source | What it does |
|---|---|
| Specification | "The ID of events within a single class must be unique"; it has no rule on equal events. |
| C++ reader | Keeps each event by its ID (`cpp:1051`, `cpp:1124`). |
| MATLAB Pulseq | Keeps each event by its ID (`read.m:566-582`). |
| pypulseq | `read` calls `remove_duplicates` by default (`read_seq.py:445-446`): it rounds each value (`event_lib.py:249-299`): shape samples to 9 significant digits and gradient amplitudes to 6, gradient times to 6 decimal places (`sequence.py:1161`, `sequence.py:1179`), merges the events that become equal, and renumbers the IDs (`sequence.py:1134-1201`). |

Example: `tests/seqfiles/oracle/pypulseq_simple_mprage150.seq`, `[TRAP]` rows
`39 0 10 980 10 0` and `40 -0 10 980 10 0`. Run: pypulseq's default `read` has
39 gradient events, with `remove_duplicates=False` 40; its rise time of 10 µs
is `9.999999999999999e-06` s. The package has both trapezoids, with amplitudes
0.0 and -0.0, and a rise time of `1e-05` s.

Package (`cpp-siemens`): keeps both rows with their IDs and values, as the C++
reader does (`pypulseq_simple_mprage150.seq`: amplitudes 0.0 and -0.0, rise time
`1e-05` s).

Package (`strict`): the IDs and the values of the file; a time is the number of
the file divided by 1e6 or 1e9 (`reader` docstring: no rounding, no
renumbering).

Reason: the block and event IDs are those of the file: the package does not
renumber them.

#### D52: Any file: it holds no dead time, ringdown time or default raster of a scanner

| Source | What it does |
|---|---|
| Specification | A file has no dead time; the rasters are in `[DEFINITIONS]`. |
| C++ reader | Adds no value of a target. |
| MATLAB Pulseq | `getBlock` adds the RF dead time and ringdown time and the ADC dead time of its system (`Sequence.m:545-546`, `Sequence.m:1446`). |
| pypulseq | `read` appends the ADC dead time of its `Opts` to each ADC event (`read_seq.py:176-183`) and takes a missing raster from `Opts` (D11); `rf_from_lib_data` adds the RF dead and ringdown times (`sequence.py:1251-1252`). |

Example: any file with an ADC event, such as `tests/seqfiles/valid_1_5_1.seq`.

Package (`cpp-siemens`): no value of a target in the model.

Package (`strict`): no value of a target in the model.

Reason: no dead time, ringdown time, gamma, B0, limit or other value of a target
is in the model: such values belong to the target, not to the file.

### The signature

#### D53: A `[SIGNATURE]` hash in a file with CRLF line ends, or a hash that does not match the file

| Source | What it does |
|---|---|
| Specification | "The new line character preceding the keyword [SIGNATURE] is part of the signature and needs to be stripped away for the signature verification." (section 2.4, `spec:223`) It has no "must" to verify the hash. |
| C++ reader | Hashes each line with its line end, and holds back a line that is only `\n` or `\r\n`: it drops that line when the next line is `[SIGNATURE]` (`cpp:1778-1788`). It compares the md5 with the stored hash in lower case (`cpp:1631`, `cpp:1645-1653`); a mismatch is a warning. |
| MATLAB Pulseq | `read` stores the hash and does not check it (`read.m:85-93`). |
| pypulseq | `read` stores the hash and does not check it (`read_seq.py:94-102`). |

Example: `tests/seqfiles/valid_crlf.seq` (CRLF line ends) ends with
`2\r\n\r\n[SIGNATURE]\r\n`. Run: the md5 of the bytes before
`\n[SIGNATURE]` (the rule of the specification, which keeps the `\r` of the
empty line) is `e06b91d84d3fba7303a915e068320754`; the md5 by the C++ rule is
the stored hash `f29fa772d7baf2ca58d083e4f4cd1f18`. The C++ dump has
`signature_ok` true. `valid_signature_mismatch.seq` has a hash that does not
match: the package, the C++ reader and MATLAB read it, and so does pypulseq
(probe).

Package (`cpp-siemens`): `Signature.matches` is the C++ reader's own check of
its hash (`valid_crlf.seq` matches; `valid_signature_mismatch.seq` does not, and
is read). A hash that does not match is not a rejection.

Package (`strict`): `Signature.matches` by the rule of the C++ reader
(`reader._scanner_hash_input`). A hash that does not match is not a violation.

Reason: both follow the C++ reader. `strict` checks and reports the signature
(`matches`), and a mismatch is not a rule: the specification has no "must" to
verify it.

#### D54: A `[SIGNATURE]` section without `Type` or `Hash`

| Source | What it does |
|---|---|
| Specification | "The [SIGNATURE] section must contain two following fields" (`Type`, `Hash`; section 2.4, `spec:223-232`). |
| C++ reader | With no `Hash` it takes the file as unsigned; with no `Type` it does not verify the hash (`cpp:1629-1647`). It accepts both. |
| MATLAB Pulseq | Reads either, both or neither (`read.m:87-93`). |
| pypulseq | Reads either, both or neither (`read_seq.py:98-102`). |

Example: `tests/seqfiles/bad_signature_invalid.seq` has `Type md5` and no
`Hash` (all three accept; pypulseq: probe).

Package (`cpp-siemens`): reads the file, and takes it as unsigned when `Hash` is
missing (`SequenceData.signature` is `None` for `bad_signature_invalid.seq`), as
the C++ reader does.

Package (`strict`): `signature.invalid`.

Reason: `cpp-siemens` reproduces the C++ reader (P1). Section 2.4 of the
specification says that the section must contain both fields, and `strict`
enforces it (the docstring of `reader` gives it as the source).

#### D55: An `extension` header whose `STRING_ID` is a word, where the specification's table gives the type integer

| Source | What it does |
|---|---|
| Specification | Section 2.8.4 gives the type of `<STRING_ID>` as "integer" in its table (`spec:493`); the text calls it a text ID, and each example has a word, such as `extension TRIGGERS 1` (`spec:498`, `spec:507`, `spec:553`). |
| C++ reader | Reads `STRING_ID` as text (`cpp:1228-1244`). |
| MATLAB Pulseq | Reads `STRING_ID` as text (`read.m:156-189`). |
| pypulseq | Reads `STRING_ID` as text (`read_seq.py:193-230`). |

Example: `extension LABELSET 2` in `tests/seqfiles/valid_1_5_1.seq`, and every
`extension` header of the oracle files.

Package (`cpp-siemens`): reads `STRING_ID` as text; `Extensions.type_ids` maps
it to the type ID of the file.

Package (`strict`): the same.

Reason: here the table and the examples of the specification disagree with each
other (D01a is about the prose against the tables). Both interpreters follow the
examples and the three readers.

## 4. Review against the order of preference

This section reviews the strict reader (now the interim interpreter `strict`)
against the order of preference of 2026-10-09, which the plan replaced with the
two interpreters (section 1). It is rewritten for the two interpreters later
(plan section 11); until then "the package" in this section means `strict`.

pulseq-analysis does not judge whether a file is valid: there are several
readers, and the specification leaves grey areas between them. Its policy is to
replicate the meaning of a file that the order of section 1 implies. Where
the C++ reader is unclear, crashes, or has undefined behaviour, the next source
in the order decides. This section compares the package as it is now with that
meaning.

### 4.1 The rules

- The order is (1) the C++ reader, (2) the specification, (3) MATLAB Pulseq,
  (4) pypulseq.
- For each entry, the implied meaning is that of the first source in the order
  that gives the file a meaning. Then the next sources do not matter.
- A source gives a meaning when it reads the file and gives it a definite
  interpretation. This includes a source that clamps, ignores, takes the last
  or the first, rounds, or warns and goes on: the meaning is what it does. For
  the C++ reader it is what the reader holds after `load` and `decodeBlock`,
  which is what the interpreter plays.
- A source gives no meaning when it rejects the file, crashes, does not end, or
  reads memory that it does not own (undefined behaviour). It also gives no
  meaning where its behaviour is unclear: where it differs between builds,
  where its code is ambiguous, or where what it plays cannot be established.
  Such a case is marked "unclear: <why>".
- The specification gives no meaning where it is silent, and where the file
  breaks one of its "must" rules (the file is then outside what it defines).
  It gives a meaning where it defines what the file means.
- Where a source gives a meaning only for a part of a file (for example the
  C++ reader inside one block, not across blocks), the next source decides the
  rest.
- Where no source gives a meaning, the implied result is: reject.

The table gives, for each entry, the source that decides, the implied meaning,
what the package does now, and whether the two agree. Where they differ, the
last column says what the package would have to change to follow the order.
Several entries have cases (1), (2), …, which are decided separately.

The facts are those of section 3, and these runs and readings of 2026-10-09,
made for this section:

- `valid_1_5_1.seq` with no `revision` line, and with a second line
  `revision 0`: the C++ dump has version 1005000 (1.5.0) for both. The reader
  starts the three numbers at 0 (`cpp:96-98`).
- `valid_1_5_1.seq` with a blank line after block 4: the C++ dump has 4 blocks.
- `valid_1_5_1.seq` with the RF delay `100.5`: the C++ reader accepts it, with
  delay 100 µs, `freq_ppm` 0.5 and `use` `0`. With the trapezoid rise time
  `100.5`: it rejects it.
- `valid_1_5_1.seq` with shapes 1 and 2 of the RF event declared with 101
  samples (they decode to 100 and 99): the C++ reader accepts it, and its RF
  magnitude has 101 samples, all 1. Declared with 99: the C++ reader accepts
  it; MATLAB fails ("nonconformant arguments": its magnitude has 100 samples
  and its phase 99); pypulseq, on a copy without extensions, decodes 99
  samples.
- `valid_1_4_1.seq` with the time shape of gradient 2 changed to 1, 2, 4, 7,
  10 (the first time is 10 µs, not 0): the C++ reader accepts it; its dump has
  the points at 10, 20, 40, 70 and 100 µs, and `gradientsAt` gives
  -80000 Hz/m at 0 µs, 0 at 5 µs and 80000 Hz/m at 10 µs (it extends the first
  segment backwards). MATLAB and pypulseq read it; the package rejects it
  (`layer1.gradient-ends`).
- pypulseq on copies of fixtures without any extension (`[EXTENSIONS]`, the
  extension sections and the `ext` column set to 0), with `read`, `get_block`
  for each block and `waveforms`: `bad_shape_event_length.seq` fails ("operands
  could not be broadcast together with shapes (100,) (8,)");
  `bad_shape_empty.seq` fails; `bad_definitions_raster_missing.seq` and
  `GradientRasterTime nan` are read (with `nan`, its waveform times are NaN).
  `bad_ref_extension_cycle.seq` with its extensions kept: `get_block` did not
  end in 10 s.
- The C++ reader holds a missing extension object as a value-initialised
  struct (`std::map::operator[]`): a trigger of type 0, a rotation with
  `defined` false and an RF shim with 0 channels are no event (`cpp.h:702-703`,
  `cpp.h:720`); a soft delay with `numID` 0 is a soft delay (`cpp.h:704`). It
  stores a label only when it knows the name, and it ignores `PMC` and `TRID`
  on purpose (`cpp:2381-2382`, `cpp:1306-1310`).
- The C++ reader keeps only the centre samples of an oversampled gradient by
  default (`cpp:103`), but the interpreter can set another mode
  (`SetArbGradCenterSampling` and the mode that keeps the oversampling,
  `cpp.h:978-991`). It takes a time ID of -1 as oversampling in any version
  (`cpp.h:700`). The text of version 1.4.1 of the specification (its title
  page) defines time ID 0 and no other value without a shape.
- The C++ reader uses the `center` of an RF event only in
  `findOrInsertRfEvent` (`cpp:2594`), so -1 is not used as a value.

### 4.2 The entries

| ID | Decides | Implied meaning | Package now | Result | Change needed |
|---|---|---|---|---|---|
| [D01a](#d01a-an-rf-row-with-12-fields) | C++ | The 12 fields of the table. | The same. | agrees | — |
| [D01b](#d01b-a-gradients-row-with-7-fields) | C++ | The 7 fields of the table. | The same. | agrees | — |
| [D01c](#d01c-an-adc-row-with-9-fields) | C++ | The 9 fields of the table. | The same. | agrees | — |
| [D02](#d02-a-file-with-no-version-section) | none | C++ rejects. The specification allows two readings ("refuse execution or assume version 1.0.0"): unclear. MATLAB rejects; pypulseq fails. Reject. | Rejects (`version.missing`). | agrees | — |
| [D03](#d03-a-file-whose-version-is-before-140-or-after-15x) | C++ | (1) 1.6.0 and later: read with the 1.5 layouts, which the reader uses for every version from 1.5.0 (`cpp:1039-1049`, `cpp:1070`, `cpp:1145`); it has no upper bound (`cpp:918-922`). (2) 1.2.0 to 1.3.x: the reader's port, with its own rasters (`cpp:1466-1473`) and block durations computed from the events (`cpp:1656-1711`). (3) `bad_version_unsupported_1_3.seq` (1.5 tables labelled 1.3): C++ rejects, the specification gives no meaning, MATLAB and pypulseq fail: reject. | Rejects all three (`version.unsupported`). | (1), (2) differ; (3) agrees | Accept 1.6.0 and later with the 1.5 layouts, and read 1.2 and 1.3 files as the C++ port does; reject only before 1.2.0. |
| [D04](#d04-a-version-line-whose-value-is-not-a-plain-integer-such-as-minor-50) | C++; MATLAB for (4) | (1) `minor 5.0` is 5. (2) A key twice: the last. (3) A missing key: 0, so a file with no `revision` line is 1.5.0. (4) An unknown key: C++ rejects (`cpp:902-906`); the specification has only the three keys: no meaning; MATLAB skips it. | Rejects all (`version.invalid`). | differs | Accept; read the numbers as C++ does, and skip an unknown key. A missing `revision` makes a 1.5.1 file 1.5.0, which changes the checks that depend on the version (`RequiredExtensions` from 1.5.1). |
| [D05](#d05-sections-in-an-unusual-order-such-as-version-after-blocks-or-last-in-the-file) | C++; none for (2) | (1) The sections in any order, found by name. (2) `[VERSION]` as the last section: C++ crashed in the run; the specification is silent; MATLAB and pypulseq reject: reject. The condition of the crash is not known beyond that run. | Accepts both. | (1) agrees; (2) differs | A new rejection for (2), once its condition is known. |
| [D06](#d06-a-blank-or--line-inside-a-section-with-data-after-it) | C++ for (1), (2); the specification for (3) | (1) A line before the first section, and the lines after the blank line that ends a table: never read, so ignored (run: a blank line after block 4 leaves 4 blocks). (2) In `[EXTENSIONS]` and the extension tables after it, blank and `#` lines are skipped and the table goes on (`cpp:1216-1221`). (3) A `#` line inside another table: C++ rejects (it decodes the line as a row); the specification defines a line that starts with `#` as a comment (`spec:171`): it is ignored, and the table goes on. | A blank or `#` line ends the section; a data line after it, or before the first section, is `syntax.line`. | differs | (1) Drop those lines with no violation. (2) Skip blank and `#` lines in the extension region. (3) Skip a `#` line inside a table. |
| [D07](#d07-a-shape-whose-last-sample-is-followed-by-the-next-shape_id-with-no-blank-line) | none for (1), (4); the specification for (2); the specification and MATLAB for (3) | (1) A `shape_id` line right after the samples: C++ stops reading `[SHAPES]` and crashed on the fixture; for the specification the line is a sample that is not a number: no meaning; MATLAB and pypulseq reject: reject. (2) A `#` line among the samples: C++ rejects (`cpp:959-962`); the specification: a comment, ignored, and the shape goes on. (3) A blank or `#` line between `shape_id` and `num_samples` or before the first sample: C++ rejects (`cpp:946`, `cpp:959`). A `#` line: a comment for the specification, ignored. A blank line ends the shape for the specification: no meaning; MATLAB skips it (`read.m:648`, `read.m:652`). (4) No `num_samples` line: all reject. | (1), (4) reject; (2) a `#` line ends the shape, and the samples after it are `syntax.shape`; (3) `syntax.shape`. | (1), (4) agree; (2), (3) differ | Skip a `#` line among the samples; skip blank and `#` lines between the header lines and before the first sample. |
| [D08](#d08-a-section-that-the-format-does-not-have) | C++ | The section is ignored. | Rejects (`section.unknown`). | differs | Accept and ignore it. |
| [D09](#d09-a-delays-section-in-a-file-of-140-or-later) | C++ | `[DELAYS]` is ignored in a file of 1.4.0 or later. | Rejects (`section.delays`). | differs | Accept and ignore it. |
| [D10](#d10-a-section-that-appears-twice) | C++ | A `[...]` section twice: the last one (`cpp:1768`). Two `extension` sections with one `STRING_ID`: their rows go to one table, and a later ID replaces an earlier one (`cpp:1223-1250`). | Rejects (`section.duplicate`). | differs | Read the last section; merge extension sections. |
| [D11](#d11-a-required-raster-that-is-missing-zero-negative-or-not-finite) | none for (1), (4); MATLAB for (2), (3) | (1) A missing raster: C++ rejects; the specification requires it; MATLAB rejects; pypulseq takes the raster of the caller's `Opts`, which is a value of the caller, not of the file: unclear. Reject. (2) `AdcRasterTime 0`, `RadiofrequencyRasterTime -1e-06`: C++ holds them, but what it plays with such a raster cannot be established: unclear; the specification does not bound the value; MATLAB reads the value as written. (3) `GradientRasterTime 0` with an arbitrary gradient: C++ rejects; the specification is silent; MATLAB reads 0. (4) `nan`: C++ rejects; MATLAB fails; pypulseq reads it but its times are NaN: unclear. Reject. | Rejects all. | (1), (4) agree; (2), (3) differ | Accept a raster of 0 or below with the value as written; reject only one that is not a finite number. |
| [D12](#d12-a-definition-that-appears-twice) | C++ | The last line. | Rejects (`definitions.duplicate`). | differs | Keep the last line. |
| [D13](#d13-a-definition-or-a-signature-hash-whose-text-reads-as-a-number) | C++ | Definitions as text (and numbers); the hash as text in lower case. | Text. | agrees | — |
| [D14](#d14-a-number-with-a-fraction-in-an-integer-column-a-sign-or-nan-a-row-with-too-few-or-too-many-columns-bytes-that-are-not-utf-8) | C++ for (1), (3), (5), (7); MATLAB for (2), (4), (6) | (1) `+30`: 30. (2) `30.5` in `[BLOCKS]`, `100.5` as a trapezoid time: C++ rejects; the column is an integer in the specification: no meaning; MATLAB reads 30.5 (305 µs) and 100.5 µs. (3) `100.5` as the RF delay: delay 100 µs, and the rest of the row one column later (`freq_ppm` 0.5, `use` `0`). (4) `nan` as an amplitude: C++ holds NaN, but what it plays cannot be established: unclear; the specification is silent; MATLAB reads NaN. (5) A block row of 7 values: `ext` 0 (`cpp:1562`, `cpp:1572`); more values than the table has: the extra values are not read (`sscanf`, `cpp:1565`). (6) A negative delay: C++ holds it, but what it plays cannot be established: unclear; the specification types it as an unsigned integer (`spec:176`): no meaning; MATLAB reads -10 µs. (7) A byte that is not UTF-8 in a comment: ignored. | Rejects all (`syntax.integer`, `syntax.number`, `syntax.columns`, `syntax.negative`, `syntax.encoding`). | differs | Accept with these values, including the moved columns of (3). |
| [D15](#d15-an-adc-dwell-time-written-with-a-decimal-point-such-as-25000) | the specification | C++ rejects `2500.0`; the specification: a float in ns, so 2500 ns (and 2500.5 ns). | Reads the float. | agrees | — |
| [D16](#d16-a-soft-delay-row-with-a-fractional-offset-such-as--1005-or-a-hint-longer-than-31-characters) | C++ | `-100.5`: offset -100 µs, factor 0.5, hint `1 TE`. A hint longer than 31 characters: its first 31. | Offset -100.5 µs, factor 1, hint `TE`; the whole hint. | differs | Decode the offset, the factor and the hint as C++ does. |
| [D17](#d17-an-rf-use-letter-that-is-not-one-of-e-r-i-s-p-o-u) | C++ | The character as written, for example `x`. | Rejects (`syntax.use`). | differs | Accept any character. |
| [D18](#d18-a-value-with-more-digits-than-a-32-bit-float-holds) | C++ | Amplitudes, `center`, `first`, `last`, offsets and shape samples as 32-bit floats. | 64-bit floats. | differs | Round these values to 32-bit floats. |
| [D19](#d19-ids-that-are-not-positive-or-not-unique) | C++ | A negative ID is an ID. An ID twice in a table: the later row (also for shapes, `cpp:976`). A block ID twice: both blocks, in file order. An ID in `[GRADIENTS]` and `[TRAP]`: the `[TRAP]` row, which the reader reads later into the same map (`cpp:1108-1125`). | Rejects (`id.positive`, `id.unique`, `id.gradient-unique`). | differs | Accept, with these choices. |
| [D20](#d20-block-ids-that-are-not-in-increasing-order) | C++ | The blocks play in file order; their IDs are not used. | Rejects (`blocks.order`); plays in file order. | differs | Accept. |
| [D21](#d21-a-reference-to-an-event-shape-or-extension-that-does-not-exist) | none for (1), (2), (7); C++ for (3), (4), (6); not known for (5) | (1) A block that names an RF, gradient or ADC event that does not exist: all reject. (2) A missing shape: C++ crashes, MATLAB and pypulseq fail: reject. (3) A missing list entry: the list ends there. (4) A missing label object: left out; a missing trigger, rotation or RF shim object: no event. (5) A missing soft delay object: C++ holds a soft delay with `numID` 0 and factor 0: unclear (a factor of 0); the specification gives no meaning; MATLAB and pypulseq not run. (6) A type that no `extension` section declares: the entry is ignored. (7) A time ID that is not a shape: C++ crashes, all others fail: reject. | Rejects all (`ref.unresolved`). | (1), (2), (7) agree; (3), (4), (6) differ; (5) not known | Accept (3), (4) and (6) with these meanings. |
| [D22](#d22-time-id--1-for-an-rf-event-or-in-a-14-file) | MATLAB | (1) RF time ID -1: C++ crashes; the specification defines -1 for gradients only: no meaning; MATLAB uses the default raster. (2) Time ID -1 for a gradient of a 1.4 file: C++ takes it as oversampling, with a sampling mode that the interpreter sets: unclear; the 1.4.1 text has no -1: no meaning; MATLAB decodes it as oversampled (`Sequence.m:1384-1390`). | Rejects both (`ref.unresolved`). | differs | Decode (1) on the default raster and (2) as an oversampled gradient. |
| [D23](#d23-a-cycle-in-an-extension-list) | none | C++ and MATLAB do not end; the list must end with 0 in the specification; pypulseq's `get_block` does not end (run). Reject. | Rejects (`ref.unresolved`). | agrees | — |
| [D24](#d24-a-file-with-no-block) | C++ | A sequence with no block. | Rejects (`blocks.empty`). | differs | Accept an empty sequence. |
| [D25](#d25-an-event-that-lasts-longer-than-its-block) | MATLAB | C++ holds the event and the block; its `gradientsAt` is 0 after the block, but what the interpreter plays after the end of the block cannot be established: unclear. The file breaks a "must" of the specification: no meaning. MATLAB reads the event as written in a block of the stored duration. What MATLAB draws after the block end is not checked. | Rejects (`block.event-too-long`). | differs | Accept, with the events as written. |
| [D26](#d26-a-time-that-is-not-a-multiple-of-its-raster) | MATLAB | C++ holds the times as written, but what it plays off the raster cannot be established: unclear. The specification says that gradients "may only start and end" on the raster: no meaning. MATLAB reads the times as written. | Rejects (`raster.*`). | differs | Accept, with the times as written. |
| [D27](#d27-a-gradient-that-starts-above-0-after-a-delay-or-ends-above-0-before-the-end-of-its-block) | MATLAB | C++ holds the event as written: a jump from 0 to `first` at the delay, or a value other than 0 at an end inside the block, which the hardware cannot play exactly: unclear. The specification: "must" (start) and "need to" (end): no meaning. MATLAB reads the event as written. | Rejects (`gradient.nonzero-*`). | differs | Accept, with the events as written. |
| [D28](#d28-an-arbitrary-gradient-on-a-gradient-raster-other-than-10-µs) | the specification | C++ rejects; the specification allows any raster: the samples at the centres of its cells. | Accepts. | agrees | — |
| [D29](#d29-a-shape-that-does-not-have-the-number-of-samples-that-it-declares) | C++ for (1), (2); not known for (3) | (1) A shape that no event uses (the fixture's shape 9): never decoded, so it does not matter. (2) A shape that declares more samples than it decodes to, used by an RF event: the last value repeated up to the declared number (run). Used by an arbitrary gradient: the buffer is reused across the axes (`cpp:2099`, `cpp:2109`), so the extra samples can hold the values of another axis: unclear; then the specification gives no meaning, and MATLAB and pypulseq were not run. (3) A shape that declares fewer: C++ writes past its buffer (`cpp:2230-2238`): unclear; no meaning in the specification; MATLAB failed in the run for another reason (the two shapes of its event decoded to 100 and 99 samples); pypulseq decoded the declared 99. The general case is not known. | Rejects all (`shape.length`). | (1), (2) for RF differ; the rest not known | Accept an unused shape; for an RF shape, repeat the last value. |
| [D30](#d30-an-amplitude-shape-with-a-sample-outside--1-1) | C++ | The clamped value: 1 for a gradient sample of 1.5; an RF magnitude in [0, 1]. | Rejects (`shape.range`). | differs | Accept, and decode the clamped values. |
| [D31](#d31-an-rf-magnitude-shape-with-a-sample-below-0) | C++ | The clamped value 0. | Rejects (`shape.rf-magnitude-negative`). | differs | Accept, and decode 0. |
| [D32](#d32-an-rf-phase-shape-with-a-sample-outside-0-1) | C++ | The phase in rad clamped to [0, 2π - 1e-4]: 2π - 1e-4 for 1.5 turns. | Rejects (`shape.rf-phase-range`). | differs | Accept, and decode the clamped phase. |
| [D33](#d33-a-shape-with-no-sample-that-an-event-uses) | none | C++ has undefined behaviour (the macOS build crashes, the Linux build accepts); the specification is silent; MATLAB and pypulseq fail. Reject. | Rejects (`shape.empty`). | agrees | — |
| [D34](#d34-the-shapes-of-one-event-with-different-numbers-of-samples) | none for RF; not known for a gradient | RF: C++ crashes; the specification is silent; MATLAB fails; pypulseq's `get_block` fails (run). Reject. A gradient whose time shape has another length: C++ rejects (`cpp:2190`), MATLAB asserts, pypulseq not run. | Rejects (`shape.event-length`). | agrees for RF; not known for a gradient | — |
| [D35](#d35-an-rf-time-shape-stored-compressed-in-3-or-4-values-a-regular-step) | C++ | Each sample for one dwell (the second stored value times the RF raster) from the delay; the first time is not used. This also holds where the times are not the centres of the cells. | Decodes as C++; rejects off-centre times (`shape.rf-time-grid`). | agrees on the centres; differs off them | Accept off-centre times. |
| [D36](#d36-an-rf-time-shape-stored-in-any-other-form) | C++ for (1); the specification for (2) | (1) A shape that the loop reads within its samples: the resampled pulse. (2) A shape for which the loop reads past its samples: undefined behaviour in C++; the specification: the samples at the times of the shape, in RF rasters (`spec:349`), as MATLAB and pypulseq read them. | (1) Decodes as C++; (2) rejects (`shape.rf-time-end`). | (1) agrees; (2) differs | Accept (2) and decode it at the times of the shape. |
| [D37](#d37-an-rf-time-shape-whose-last-time-is-before-the-end-of-the-last-samples-dwell) | C++ | The dwell times the number of samples. | The same. | agrees | — |
| [D38](#d38-an-rf-event-of-a-14-file-which-has-no-center-column) | C++ | No center (-1, "mark as invalid", not used as a value). | Absent. | agrees | — |
| [D39](#d39-a-14-arbitrary-gradient-on-the-default-raster-which-has-no-first-and-last-columns) | MATLAB | C++ holds the marker `FLOAT_UNDEFINED`, which `gradientsAt` uses as a value near 0: unclear (code ambiguous). The 1.4 format has no ends: no meaning. MATLAB: `first` from the block before, `last` by the alternating sum. | Rejects (`layer1.gradient-ends`). | differs | Accept, with MATLAB's ends. |
| [D40](#d40-a-14-arbitrary-gradient-with-a-time-shape-which-has-no-first-column) | C++ for (1); MATLAB for (2) | (1) A time shape that starts at 0: the amplitude times the first sample. (2) A time shape that starts later: C++ holds no point before the first time, and `gradientsAt` extends the first segment backwards (run): unclear; the file has no value there: no meaning; MATLAB: `first` from the block before (0 in the run). What MATLAB draws before the first point is not checked. | (1) The same; (2) rejects (`layer1.gradient-ends`). | (1) agrees; (2) differs | Accept (2), with MATLAB's `first`. |
| [D41](#d41-an-arbitrary-gradient-on-the-default-raster-time-id-0-whose-samples-are-at-the-centres-of-the-raster-cells) | C++ | Straight lines between the sample centres, and to `first` and `last` (`gradientsAt`). | The same. | agrees | — |
| [D42](#d42-a-gap-between-two-gradient-events-on-one-axis) | MATLAB, across blocks | C++ gives the waveform inside a block only; the specification is silent between events; MATLAB: ramps over half a raster. | The same. | agrees | — |
| [D43](#d43-an-oversampled-arbitrary-gradient-time-id--1) | the specification | C++ keeps the centre samples in its default mode, but the interpreter can set another mode: unclear. The specification: N - 1 more points between the samples, on the raster edges (`spec:420`). | All the samples, half a raster apart. | agrees | — |
| [D44](#d44-an-adc-event-with-a-phase-modulation-shape) | C++ | The phase shape in rad (its use in `updateAdcPhaseModulation`, `cpp:3059-3060`). | The shape as stored, with no unit. | differs | State the unit rad (the numbers are the same). |
| [D45](#d45-an-unknown-extension-that-the-file-does-not-require) | C++ | The extension is ignored. | Ignored. | agrees | — |
| [D46](#d46-a-file-whose-last-section-that-starts-with--is-extensions) | the specification | C++ rejects. The specification defines the sections and not their order: the file as written. | Accepts. | agrees | — |
| [D47](#d47-an-unknown-extension-that-the-file-requires) | none | C++ rejects; the specification says that the interpreter must stop. Reject. | Rejects (`extension.required-unknown`). | agrees | — |
| [D48](#d48-a-block-with-more-than-one-rotations-or-rf_shims-object) | C++ | The first object of the list, with a warning. | Rejects (`extension.per-block`). | differs | Accept, and keep the first object. |
| [D49](#d49-a-block-that-plays-a-rotation-or-a-quaternion-that-is-not-normalized) | C++ for (1); MATLAB for (2) | (1) A norm within 1e-3 of 1: the quaternion divided by its norm. (2) Further from 1: C++ rejects; the specification describes a normalized quaternion: no meaning; MATLAB divides it by its norm. | Keeps the quaternion as written. | differs | Divide each quaternion by its norm. |
| [D50](#d50-a-labelset-or-labelinc-row-with-a-label-name-that-a-reader-does-not-know) | C++ | A label whose name the reader does not know is left out, and so are `PMC` and `TRID`. | Keeps every name. | differs | Leave such labels out of the model, or mark them. |
| [D51](#d51-two-event-rows-with-equal-values-and-different-ids-such-as-amplitudes-0-and--0) | C++ | Each event by its ID; no merge, no renumbering. | The same. | agrees | — |
| [D52](#d52-any-file-it-holds-no-dead-time-ringdown-time-or-default-raster-of-a-scanner) | C++ | No value of a target. | None. | agrees | — |
| [D53](#d53-a-signature-hash-in-a-file-with-crlf-line-ends-or-a-hash-that-does-not-match-the-file) | C++ | Its hash rule; a mismatch is a warning. | The same. | agrees | — |
| [D54](#d54-a-signature-section-without-type-or-hash) | C++ | No `Hash`: an unsigned file. No `Type`: the hash is not verified. | Rejects (`signature.invalid`). | differs | Accept: no signature, or a signature with `matches` unknown. |
| [D55](#d55-an-extension-header-whose-string_id-is-a-word-where-the-specifications-table-gives-the-type-integer) | C++ | `STRING_ID` is text. | The same. | agrees | — |

### 4.3 The entries that differ

(a) The package rejects a file to which the order gives a meaning:

| Rule ID | Entries |
|---|---|
| `version.unsupported` | D03 |
| `version.invalid` | D04 |
| `syntax.line` | D06 |
| `syntax.shape` | D07 (2), (3) |
| `section.unknown`, `section.delays`, `section.duplicate` | D08, D09, D10 |
| `definitions.raster-invalid` | D11 (2), (3) |
| `definitions.duplicate` | D12 |
| `syntax.integer`, `syntax.number`, `syntax.columns`, `syntax.negative`, `syntax.encoding` | D14 |
| `syntax.use` | D17 |
| `id.positive`, `id.unique`, `id.gradient-unique` | D19 |
| `blocks.order` | D20 |
| `ref.unresolved` | D21 (3), (4), (6); D22 |
| `blocks.empty` | D24 |
| `block.event-too-long` | D25 |
| `raster.adc-dwell`, `raster.gradient-delay`, `raster.gradient-end`, `raster.gradient-ramp`, `raster.gradient-flat` | D26 |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | D27 |
| `shape.length` | D29 (1), (2) for RF |
| `shape.range`, `shape.rf-magnitude-negative`, `shape.rf-phase-range` | D30, D31, D32 |
| `shape.rf-time-grid` | D35 |
| `shape.rf-time-end` | D36 (2) |
| `layer1.gradient-ends` | D39, D40 (2) |
| `extension.per-block` | D48 |
| `signature.invalid` | D54 |

The rules that agree with the order are `version.missing` (D02),
`definitions.raster-missing` (D11 (1)), `shape.empty` (D33),
`shape.event-length` (D34, for RF) and `extension.required-unknown` (D47), and
the parts of `ref.unresolved` of D21 (1), (2), (7) and D23.

(b) The package decodes a value differently from the implied meaning:

- D14 (3): an RF delay with a fraction, and the columns after it.
- D16: the soft delay offset and factor of a fraction.
- D18: 64-bit floats in place of 32-bit floats.
- D30, D31, D32: the clamped values, once the file is accepted.
- D36 (2): the times of the shape in place of the C++ resampling.
- D39, D40 (2): MATLAB's ends of a 1.4 gradient.
- D49: the quaternion divided by its norm.
- D29 (2): the repeated last value of an RF shape.

A fact that no entry of section 3 has: the C++ reader rounds each time of the
time shape of an extended trapezoid to a whole µs (`cpp:2182`). The package
keeps the times of the file. A time shape with a time that is not a whole µs
(for example 0.25 rasters of 10 µs) would decode differently. It was not run.

(c) The package accepts a file to which no source gives a meaning:

- D05 (2): `[VERSION]` as the last section (the C++ reader crashed in the run).

(d) Differences in what the model keeps:

- D16: the whole soft delay hint, where C++ keeps 31 characters.
- D44: the ADC phase shape with no unit, where C++ uses rad.
- D50: label names that C++ does not keep (unknown names, `PMC`, `TRID`).

### 4.4 Cases that are not clear-cut

- D02: the specification allows two readings ("refuse execution or assume
  version 1.0.0") and recommends to reject. It was taken as unclear. Read as
  "assume 1.0.0", the specification would decide, and the file would be read
  as a 1.0.0 file, which no reader here reads.
- D11 (1), (4): pypulseq's default raster comes from the `Opts` of the caller,
  and its NaN times give no waveform; both were taken as unclear. D11 (2):
  MATLAB decides, and a raster of 0 or below gives times that no scanner can
  play.
- D14 (3), D16: the C++ reader reads a fraction as two values and moves the
  rest of the row. This is a definite meaning by the rules, but it is a
  misreading of the text.
- D14 (4), (6), D25, D26, D27: the C++ reader holds definite values, and the
  case was taken as unclear because what the interpreter plays cannot be
  established from the reader. Each then goes to MATLAB, past the
  specification, whose "must" rules the file breaks. D25 is the clearest: the
  specification says "The interpreters must to throw an error", and by the
  rules that sentence gives no meaning.
- D18: whether the 32-bit precision of the C++ reader is a meaning (a
  rounding) or a detail of its implementation.
- D29: the result depends on the event that uses the shape and on the buffer
  that the reader reuses; the cases that were not run are not known.
- D36 (2): the package would decode most RF time shapes as the C++ reader
  plays them, and these few by the specification.
- D39, D40, D41: whether `gradientsAt` is a meaning of the C++ reader. D41
  takes it as one: it is the reader's definition of the gradient between the
  samples. D39 and D40 (2) do not: there it computes a value from a marker
  (`FLOAT_UNDEFINED`) or before the first point that the reader holds. If
  only the held samples counted, MATLAB would decide D41 too, and the package
  would differ: MATLAB restores the values at the raster edges.
- D43, D22 (2): the sampling mode of an oversampled gradient is a setting of
  the interpreter, so the C++ reader was taken as unclear.
- D06 (3), D07 (2), (3): this takes the sentence of the specification on
  comments (`spec:171`) to apply inside a section too. It does not say where a
  comment may be.
- D49 (2): whether "described as a normalized rotation quaternion" is a rule
  that the file breaks.
- D05 (2), D21 (5): the condition of the crash, and what a missing soft delay
  object means, are not known.

## Appendix A: the acceptance matrix

`scripts/discrepancy_matrix.py` made this table on 2026-10-09 (appendix B).
The column "pulseq-analysis" is the strict interpreter's: the matrix does not
have a column for `cpp-siemens`.
The C++ column is the macOS arm64 build. "crash (70)" is a signal. The MATLAB
column is the oracle, which calls `read`, `getBlock` for each block and
`waveforms_and_times`, so an error can come from any of them. The column
"pypulseq, probe" is described in section 1; "=" means that the probe is the
file.

| File | pulseq-analysis | C++ reader | MATLAB Pulseq | pypulseq | pypulseq, probe |
|---|---|---|---|---|---|
| `bad_block_event_too_long_adc.seq` | `block.event-too-long` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_block_event_too_long_rf.seq` | `block.event-too-long` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_block_event_too_long_trigger.seq` | `block.event-too-long` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_blocks_empty.seq` | `blocks.empty` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_blocks_order.seq` | `blocks.order` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_definitions_duplicate.seq` | `definitions.duplicate` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_definitions_raster_invalid.seq` | `definitions.raster-invalid` | reject | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_definitions_raster_missing.seq` | `definitions.raster-missing` | reject | error: Required definitions AdcRasterTime are missing in the file | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_extension_per_block.seq` | `extension.per-block` | accept | error: Only one rotation extension object per block is allowed | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_extension_required_unknown.seq` | `extension.required-unknown` | reject | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_gradient_nonzero_end_align.seq` | `gradient.nonzero-end-align` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_gradient_nonzero_start_delay.seq` | `gradient.nonzero-start-delay` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_id_gradient_unique.seq` | `id.gradient-unique` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_id_positive.seq` | `id.positive` | accept | error: obj(-2): subscripts must be either integers 1 to (2^31)-1 or l… | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_id_unique.seq` | `id.unique` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_id_unique_block.seq` | `id.unique` | accept | error: eventInd(7): out of bound 0 (dimensions are 0x0) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_layer1_gradient_ends.seq` | `layer1.gradient-ends` | accept | read | TypeError: type NoneType doesn't define __round__ method | = |
| `bad_many.seq` | `extension.required-unknown` `raster.adc-dwell` `ref.unresolved` | reject | error: obj(9): out of bound 1 (dimensions are 1x1) | ValueError: Unknown section code: extension ROTATIONS 5 | KeyError: np.int64(9) |
| `bad_raster_adc_dwell.seq` | `raster.adc-dwell` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_raster_gradient_delay.seq` | `raster.gradient-delay` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_raster_gradient_end.seq` | `raster.gradient-end` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_raster_gradient_flat.seq` | `raster.gradient-flat` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_raster_gradient_ramp.seq` | `raster.gradient-ramp` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_ref_block_rf.seq` | `ref.unresolved` | reject | error: obj(9): out of bound 1 (dimensions are 1x1) | ValueError: Unknown section code: extension ROTATIONS 5 | KeyError: np.int64(9) |
| `bad_ref_extension_cycle.seq` | `ref.unresolved` | no end in 10 s | not run (a cycle in an extension list) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_ref_extension_entry.seq` | `ref.unresolved` | accept | error: obj(99): out of bound 7 (dimensions are 1x7) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_ref_extension_object.seq` | `ref.unresolved` | accept | error: obj(9): out of bound 1 (dimensions are 1x1) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_ref_extension_type.seq` | `ref.unresolved` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_ref_shape.seq` | `ref.unresolved` | crash (70) | error: obj(99): out of bound 9 (dimensions are 1x9) | ValueError: Unknown section code: extension ROTATIONS 5 | KeyError: np.float64(99.0) |
| `bad_ref_time_id_minus_1_in_1_4.seq` | `ref.unresolved` | accept | read | KeyError: np.float64(-1.0) | = |
| `bad_ref_time_shape.seq` | `ref.unresolved` | crash (70) | error: obj(99): out of bound 9 (dimensions are 1x9) | ValueError: Unknown section code: extension ROTATIONS 5 | KeyError: np.float64(99.0) |
| `bad_section_delays.seq` | `section.delays` | accept | error: Pulseq file revision 1.4.0 and above MUST NOT contain the [DEL… | ValueError: Unknown section code: extension ROTATIONS 5 | RuntimeError: Pulseq file revision 1.4.0 and above MUST NOT contain [… |
| `bad_section_duplicate.seq` | `section.duplicate` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_section_unknown.seq` | `section.unknown` | accept | error: Unknown section code: [FOO] | ValueError: Unknown section code: extension ROTATIONS 5 | ValueError: Unknown section code: [FOO] |
| `bad_shape_empty.seq` | `shape.empty` | crash (70) | error: Unknown section code: Hash 44dfe65515bd7a5503f1a8c4aee60be8 | ValueError: Unknown section code: extension ROTATIONS 5 | ValueError: could not convert string to float: '[SIGNATURE]' |
| `bad_shape_event_length.seq` | `shape.event-length` | crash (70) | error: product: nonconformant arguments (op1 is 100x1, op2 is 8x1) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_length.seq` | `shape.length` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_range.seq` | `shape.range` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_rf_magnitude_negative.seq` | `shape.rf-magnitude-negative` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_rf_phase_range.seq` | `shape.rf-phase-range` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_rf_time_end.seq` | `shape.rf-time-end` | crash (70) | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_shape_rf_time_grid.seq` | `shape.rf-time-grid` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_signature_invalid.seq` | `signature.invalid` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_syntax_columns.seq` | `syntax.columns` | accept | error: eventInd(7): out of bound 6 (dimensions are 1x6) | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_syntax_encoding.seq` | `syntax.encoding` | accept | error: regexp: the input string is invalid UTF-8 | UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5 in position … | UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5 in position … |
| `bad_syntax_integer.seq` | `syntax.integer` | reject | read | ValueError: string or file could not be read to its end due to unmatc… | ValueError: string or file could not be read to its end due to unmatc… |
| `bad_syntax_integer_plus.seq` | `syntax.integer` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_syntax_line.seq` | `syntax.line` | accept | error: Unknown section code: 1 2 3 | ValueError: Unknown section code: 1 2 3 | ValueError: Unknown section code: 1 2 3 |
| `bad_syntax_line_after_comment.seq` | `syntax.line` | reject | error: Unknown section code: 2  50  0  1  2  0  1  0 | ValueError: string or file could not be read to its end due to unmatc… | ValueError: string or file could not be read to its end due to unmatc… |
| `bad_syntax_negative.seq` | `syntax.negative` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_syntax_number.seq` | `syntax.number` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | ValueError: cannot convert float NaN to integer |
| `bad_syntax_shape.seq` | `syntax.shape` | reject | error: tok(2): out of bound 1 (dimensions are 1x1) | ValueError: Unknown section code: extension ROTATIONS 5 | IndexError: list index out of range |
| `bad_syntax_shape_no_blank_line.seq` | `syntax.shape` | crash (70) | error: mr.decompressShape() failed for shapeId 4 | ValueError: Unknown section code: extension ROTATIONS 5 | ValueError: could not convert string to float: 'shape_id 5' |
| `bad_syntax_use.seq` | `syntax.use` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `bad_version_invalid.seq` | `version.invalid` | accept | read | ValueError: invalid literal for int() with base 10: '5.0' | ValueError: invalid literal for int() with base 10: '5.0' |
| `bad_version_missing.seq` | `version.missing` | reject | error: Pulseq file MUST include [VERSION] section prior to [BLOCKS] s… | UnboundLocalError: cannot access local variable 'file_version_major' … | UnboundLocalError: cannot access local variable 'file_version_major' … |
| `bad_version_unsupported_1_3.seq` | `version.unsupported` | reject | error: product: nonconformant arguments (op1 is 1x6, op2 is 1x10) | ValueError: Mismatch between number of tokens and format spec | ValueError: Mismatch between number of tokens and format spec |
| `bad_version_unsupported_1_6.seq` | `version.unsupported` | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `oracle/koma_v1.4_epi.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.4_fid.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.4_gr-time-shaped.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.4_gr-trapezoidal.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.4_gr-uniformly-shaped.seq` | `layer1.gradient-ends` | accept | read | read | = |
| `oracle/koma_v1.4_label_test.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.4_rf-time-shaped.seq` | accept | accept | read | read | = |
| `oracle/koma_v1.5_rotation_radial_tiny.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 1 | read |
| `oracle/koma_v1.5_spiral.seq` | accept | accept | read | KeyError: np.float64(-1.0) | read |
| `oracle/koma_v1.5_unknown_ext.seq` | accept | reject | read | ValueError: Unknown section code: extension UNKNOWN1 1 | read |
| `oracle/pulseq_epi_rs.seq` | accept | accept | read | read | = |
| `oracle/pulseq_fid.seq` | accept | accept | read | read | = |
| `oracle/pulseq_make_radial.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 1 | read |
| `oracle/pulseq_seq4.seq` | accept | accept | read | read | = |
| `oracle/pypulseq_seq6.seq` | accept | accept | read | read | = |
| `oracle/pypulseq_simple_mprage140.seq` | `layer1.gradient-ends` | accept | read | read | = |
| `oracle/pypulseq_simple_mprage150.seq` | accept | accept | read | read | = |
| `valid_1_4_0.seq` | accept | accept | read | read | = |
| `valid_1_4_1.seq` | accept | accept | read | read | = |
| `valid_1_5_0.seq` | accept | accept | read | KeyError: np.float64(-1.0) | read |
| `valid_1_5_1.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `valid_1_5_1_rotation_not_played.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `valid_arbitrary_gradient_4us_raster.seq` | accept | reject | read | read | = |
| `valid_comments_between_sections.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `valid_crlf.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `valid_no_signature.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |
| `valid_signature_mismatch.seq` | accept | accept | read | ValueError: Unknown section code: extension ROTATIONS 5 | read |

## Appendix B: how to regenerate the matrix and the figures

Both scripts need the two oracles, which are in the default devShell (not in
the `ci` shell):

```
nix develop --command uv run python scripts/discrepancy_matrix.py > matrix.md
nix develop --command uv run python scripts/discrepancy_figures.py
```

- `scripts/discrepancy_matrix.py` writes the table of appendix A to stdout and
  its time to stderr. `--cpp PATH` and `--matlab PATH` give an oracle that is
  not on the `PATH`. On the computer of section 1 it took 45 s and 46 s
  for the 85 files in two runs, and 81 s in a run while other processes loaded
  the computer.
- `scripts/discrepancy_figures.py` writes the small Pulseq files of the figures
  to a temporary folder, runs MATLAB Pulseq (`pulseq-matlab-oracle`), the C++
  reader (`pulseq-cpp-oracle --dump` and `--sample`) and the package on them,
  and writes `docs/figures/discrepancy-rf-time-shapes.svg` and
  `docs/figures/discrepancy-arbitrary-gradient-edges.svg`. The SVG files are
  reproducible (`svg.hashsalt`, no date). With `DOC_FIGURES_PREVIEW=<dir>` it
  also writes a PNG of each.
- `figures/waveform-gaps.svg` (D42) comes from `scripts/doc_figures.py`.
