# Code review, 2026-10-13

A review of the whole repository at commit `74fa0b2`, after the documentation
of the own parser (#133). It covers the package `pulseq_analysis`, the plugin
pulseq-cpp-siemens (`packages/pulseq-cpp-siemens/`), the tests, the scripts
and the documents.

The review looks for these things:

- Code that is incorrect, mis-documented, duplicative or inefficient.
- Tests that are unnecessary, that do not test what they claim, or that test
  only code outside this repository.
- Parts of the API that do not fit the goals of the project.

It does not repeat a finding of an earlier review that is fixed. The line
numbers are of commit `74fa0b2`. Section 7 gives the status after the fixes
of PRs #134 to #196.

Method:

- Seven reviewers, run at the same time, each read one area in full:
  - `seqfile/`;
  - `synth/`;
  - `analyses/` with `_equality.py` and `_validate.py`;
  - the plugin;
  - the tests of the parser, the model and the interface;
  - the tests of the analyses and the sampling;
  - the documents against the public API, with the scripts and CI.
- Small scripts against `src/` of `74fa0b2`, and runs of the tests, the
  oracles and the fuzzer. The findings marked *reproduced* were run. The
  others marked *confirmed* were checked by reading the code. *Plausible*
  marks a finding from reading alone.
- The main review checked the most severe findings itself, by rerunning the
  scripts or reading the lines.

## 1. Correctness

### 1.1 The plugin pulseq-cpp-siemens

1. **The measurements of a block can use the decoding of another block**
   (*reproduced*; B1).
   - The reader decompresses the gradients of a block, in the order gx, gy,
     gz, into one buffer: `decodeArbGradInBlock` (cpp:2094-2153) and
     `decodeExtTrapGradInBlock` (cpp:2155-2196).
   - `waveform.resize(n)` keeps the values that the buffer holds, and a
     compressed shape can write fewer than `num_samples` values (a run of
     count -2), before the cumulative sum. So the samples of an event can hold
     values of the event before it in the same block.
   - [_played.py:78-84](../../src/pulseq_analysis/synth/_played.py#L78) asks
     `Decoding.gradient_points` only at the first block of each event. Its
     docstring says that a plugin's decoding "must not depend on the block".
   - Reproduced: an extended trapezoid whose time shape is `0 0 -2` decodes
     with the times `[0, 0, 0, 0]` us alone, and `[10, 20, 30, 40]` us after
     another event on gx. The reader plays gy = 250, 750, 1000, 750 and
     0 Hz/m at 5 to 45 us of that block; the measurements see 0.
   - [`test_the_cpp_siemens_decoding_of_a_gradient_event_is_the_same_in_every_block`](../../packages/pulseq-cpp-siemens/tests/test_load_in_pulseq_analysis.py#L229)
     asserts the false rule, and passes only because no fixture has the case.
     D5.5 says a shorter decompression "is read with its last value repeated",
     which is true only in an empty buffer.
2. **A byte that is not UTF-8 in the reader's messages raises
   `UnicodeDecodeError`** (*reproduced*; B2).
   - [reader.cpp:1168](../../packages/pulseq-cpp-siemens/src/reader.cpp#L1168)
     binds `messages` as a `std::string`, which nanobind converts to `str` as
     strict UTF-8.
   - The reader quotes the text of the file in its messages, for example a row
     that it fails to decode (cpp:1150) and the line of an unknown extension
     (cpp:1248).
   - `valid_1_5_1.seq` with the extension name `UNKN\xb5WN` raises in
     `cs.load`, although the reader loads it. An ADC row `1 \xb5x` raises too,
     where the contract of `Plugin.read` is `SeqFileError` with a code.
   - The fuzzer inserts only ASCII and 0xFF, so it misses this.
3. **`Sequence.gradients_at` with `actual_ru` can end the process**
   (*reproduced*; B3).
   - The check `ub.gradient-one-point`
     ([_checks.py:466-482](../../packages/pulseq-cpp-siemens/src/pulseq_cpp_siemens/_checks.py#L466))
     tests only the stored duration of the block.
   - The soft delay `actual_ru` replaces that duration in `GetDuration`
     (`ExternalSequence.h:705`), so it can make an extended trapezoid of one
     point reach the reader's read past its times (cpp:3639-3650).
   - Reproduced: `gradient_one_point.seq` with the delay of gradient 5 at
     200 us loads. `gradients_at([4], [205.0], actual_ru=a)` with `a[4] = 100`
     ends Python with SIGTRAP from the hardened libc++.
   - The README says that `load` rejects every case of undefined behaviour "so
     that the process survives the file". `CppSiemensDecoding` does not reach
     the case, because the session sets a soft delay only on a pure delay
     block.
4. **Threads that share one `Sequence` race on the reader's messages**
   (*plausible*; B4).
   - Each call writes `messages_` under `g_reader_mutex`, with the GIL
     released. The property `messages`
     ([reader.cpp:1099](../../packages/pulseq-cpp-siemens/src/reader.cpp#L1099))
     reads it without the mutex, after the call has returned.
   - That is a data race on a `std::string`, and at best `Rejected.messages`
     of another call. The README says the calls are thread-safe;
     `test_shared_state.py` runs threads on separate `Sequence` objects only.
5. **The "edge" mode with an oversampled gradient of 0 samples** gives
   points that the reader never plays (*reproduced*).
   [interpreter.py:854-860](../../packages/pulseq-cpp-siemens/src/pulseq_cpp_siemens/interpreter.py#L854)
   gives `[(0, first), (0, last)]`, where `gradientsAt` returns early and
   plays 0. `gradient_peaks` reports a peak of 300 000 Hz/m and a slew of
   3e10 on an axis that plays 0.
6. **Undefined behaviour is one first-found rejection, by the host**
   (*confirmed*).
   - `_checks.undefined_behaviour` returns the first case only, so the other
     cases of a file are invisible.
   - `ub.gradient-time-range` uses `sizeof(long)` of the machine that runs
     the analysis, so one file can have two verdicts, on Windows and on
     Linux.
   - The goal is a finding for each case, with the severity in pulseq-checks.
     The protocol carries no findings from a plugin.

### 1.2 `spec` and the model

1. **A gradient time shape that starts before 0 is accepted**
   (*reproduced*). The test `times[0] < 0` of
   [spec.py:1514](../../src/pulseq_analysis/seqfile/spec.py#L1514) is in the
   RF branch only. A time shape `-2 1 3 6 10` reads, and its decoded times go
   back to before the block start. D3.9 is not limited to RF.
2. **A syntax error in one event table turns off the checks of the others**
   (*reproduced*). `_event_ends`
   ([spec.py:1301](../../src/pulseq_analysis/seqfile/spec.py#L1301)) returns
   None when any of `rf`, `grad`, `trap` or `adc` is None. That skips every
   `raster.*` rule, `block.event-too-long` and the `gradient.*` rules, against
   the module docstring ("the error has every violation of the tables that
   read").
3. **NaN counts as a non-zero end** (*reproduced*). `last != 0`
   ([spec.py:1620](../../src/pulseq_analysis/seqfile/spec.py#L1620)) is True
   for NaN, so a 1.4 gradient whose end the file does not define also gets
   `gradient.nonzero-end-align`.
4. Smaller ones:
   - **Rotation IDs:** `Extensions.rotations["id"]` is float64
     ([model.py:127](../../src/pulseq_analysis/seqfile/model.py#L127)); every
     other ID is int64.
   - **Extension type IDs:** a negative or zero type ID is accepted
     ([spec.py:1022-1031](../../src/pulseq_analysis/seqfile/spec.py#L1022)).
   - **`interpreter()`:** it accepts a plugin class where it needs an object
     ([interpreters.py:162](../../src/pulseq_analysis/seqfile/interpreters.py#L162)).
   - **The shape size limit:** `shape.length` is reported for the package's
     own limit of 2^27 samples, as if the specification stated it.

### 1.3 `synth/` and the analyses

1. **`RfEvent.signal` puts a cell-boundary time in the cell before**
   (*reproduced*).
   [events.py:154](../../src/pulseq_analysis/synth/events.py#L154) uses
   `np.floor(times / dwell)`. With a dwell of 1 us, 89 of 5000 boundaries are
   in the wrong cell.
2. **The `.asc` reader** (*reproduced*):
   - [asc.py:26-30](../../src/pulseq_analysis/analyses/asc.py#L26) refuses
     `1.5E-3`, `1e+02` and `0x10`, and reads `-5` as a float.
   - A latin-1 byte raises `UnicodeDecodeError`, not a `ValueError` that
     names the file.
   - A line with `=` after `### ASCCONV END ###` can still raise, against
     its docstring.
3. **Values that break their own guarantees** (*reproduced*):
   - `FrozenDict` can be changed in place with `d.__init__(b=2)`
     ([_equality.py:33-55](../../src/pulseq_analysis/_equality.py#L33)).
   - A hardware label of `"nan"` or `"inf"` breaks `to_series`
     ([registry.py:419](../../src/pulseq_analysis/analyses/registry.py#L419)).
   - `AnalysisSpec` does not check `necessary`, `title`, `description` or
     `series`, so a bad one can be built that then fails to hash.

## 2. Efficiency

1. **`SpecDecoding.gradients_at` is quadratic** (*reproduced*).
   - [decoding.py:212-217](../../src/pulseq_analysis/synth/decoding.py#L212)
     loops `np.flatnonzero(ids == gid)` over the unique IDs, so its cost is
     O(reads x unique IDs).
   - With a field-of-view rotation, `sequence_index` of 40 000 blocks of
     distinct trapezoids took 6.3 s, against 0.03 s neutral.
   - The fix is one sort by ID, or `np.unique(..., return_inverse=True)`.
2. **Rotated blocks run Python per block.** `_plan` and `_points` of
   `_played` run for each distinct block, although the plan does not depend on
   the rotation: about 40 us per block, and 40 s at 1e6 blocks.
3. **Kept work is lost between calls:**
   - `pns_levels` and `gradient_sampler` rebuild the O(B) axis events, gaps
     and ramps, and the cache of samples, on every call. That is 37 % of a call
     with new hardware.
   - `gradients_at` allocates an O(B) array on every call.
4. **Every load does work that no analysis reads:**
   - it expands each block's LABELSET objects in Python only to find NOROT
     and NOSLC (0.93 s of 1.0 s at 1e6 blocks);
   - it decodes every RF and ADC event;
   - it decompresses each shape twice (`spec._read_shapes`, then
     `events._Shapes`).
5. **Other loops:**
   - The plugin decodes a kept block again for each `gradient_points` call,
     up to three times a block.
   - `spec._shapes_of` loops in Python over every sample of every shape (0.33 s
     of a 1.0 s read).
   - Each threshold of `pns_levels` adds about 8 %, not the documented "a few
     percent".

## 3. Mis-documentation

1. **`docs/findings-for-pulseq-checks.md`** pins commit `6fa807d`. That commit
   has none of the record IDs that the document links (no D2.18), and it is
   older than the session work. The document gives the protocol without
   `protocol` and `session`.
2. **The version of pulseq-cpp-siemens.** `CHANGELOG.md:113` and
   `docs/migration.md:87-89` say it has the version of pulseq-analysis and
   requires `pulseq-analysis>=0.1.0rc7,<0.2`. Its `pyproject.toml` has
   `version = "0.1.0"` and only `numpy`.
3. **The README example** does not run with the install line above it
   (`@v0.1.0rc6`). At that tag `analyses` is a module, so
   `from pulseq_analysis.analyses import load` fails.
4. **The contracts of the analyses:**
   - `gradient.peaks`
     ([registry.py:245-246](../../src/pulseq_analysis/analyses/registry.py#L245))
     and `docs/usage.md:312` give a tied vector peak to "the first in play
     order"; the code gives it to the earliest time.
   - The descriptions say "the logical axes of the file", but rotations (1.5.1)
     and the session change that, and `spec.version` stays 1.
5. **`NotSupported` "whatever the interpreter".** For a folder or a binary
   file, `CHANGELOG.md`, `docs/migration.md`, `docs/specification.md` and
   `errors.py` say so. Under `spec`, a folder gives `IsADirectoryError` and a
   binary file `SeqFileError` (`syntax.encoding`).
6. **The protocol of `gradient_points`.** `docs/usage.md:881-882` says a
   plugin can decode one event differently in two blocks, and
   `docs/implementation.md:97-99` and `_played.py` say it must not (finding
   1.1.1).
7. **Cost and behaviour claims:**
   - `sequence_index` is O(B log B), not O(B).
   - The spectrum does not share the kept gaps.
   - Section 1.2 of `implementation.md` leaves out the session's rotation and
     scaling as a reason a block is read through `gradients_at`.
   - "A shape that several events use is decompressed once" holds only within
     one call.
8. **Stale text:**
   - `Sequence.read` (`implementation.md:721`).
   - `pns_levels.SAFE_FIELDS`, which moved to `analyses.safe`.
   - The test `test_matches_scipy_spectrogram`, cited in three places and gone.
   - Citations of the private drafts of upstream pypulseq reports in three
     module docstrings that `help()` shows, and 14 times in `TESTS.md`.
9. **The docs-only path of CI** checks only `usage.md` and
   `implementation.md`, so findings 3.1 to 3.3 got through.

## 4. Duplication

- **The rejection codes** are in four places: `spec.RULES`, `docs/usage.md`,
  `docs/specification.md` and `findings-for-pulseq-checks.md`. They agree now,
  and no test compares them.
- **The cost tables and the `pns_levels` contract** are in several documents.
  One copy has already drifted (finding 3.4).
- **The version gate** is in both `spec` and the plugin, with different
  messages.
- **The plugin:** it re-implements `_pure_delay`, `Points` and the
  physical-gradients path of the main package.
- **The extension-list walk** is written twice in `decoding.py`.
- **The hardware** is validated and converted three times for each call of
  `pns_levels`.

## 5. Tests

1. **Oracles that share the package's code:**
   - `tests/oracles/blocks.py:63` (`sequence_of`) builds the oracle's input
     from the package's own `played_gradients`. The comparisons of the
     sampler, the peaks, the spectrum, the PNS and the index can therefore not
     find an error of the decoding. `test_grad_peaks.py:500` and `TESTS.md`
     say it "shares no code".
   - No test compared the measurements of `cpp-siemens` with the reader's own
     `gradientsAt`, which is how finding 1.1.1 got through.
2. **The SAFE filter** is compared only with the fork it was ported from. The
   "levels" golden values come from the package's own pipeline.
3. **Weak or circular tests:**
   - `test_the_fast_and_the_slow_typing_agree` compares 5 of its 400 tables.
   - The MATLAB waveform test skips 11 fixtures, with a stale reason (the
     interpreter `strict`), and its rotated replacement checks to 1e-6.
   - The spectrum oracle uses only the default arguments.
   - No test pins `TOLERANCE_NS`: with it at 0, the suite passes.
   - The rotation tolerances cannot see a missing normalization of the
     quaternion.
4. **CI does not run what `TESTS.md` says.** The `ci` devShell has no MATLAB
   oracle, so `test_matlab_oracle.py` always skips in CI.
5. **Tests of code outside this repository:**
   - `test_cpp_oracle_sanitized.py` calls no code of pulseq_analysis, and its
     coverage test of undefined behaviour compares a literal with a literal;
   - the `test_the_oracle_*` tests of `test_cpp_oracle.py`;
   - the libc `strtod` test of `test_shared_state.py`;
   - `test_prediction_propagates_an_error`;
   - the hash tests of frozen dataclasses.
6. **Asserts that cannot fail:**
   - the gamma test of `test_pns_levels.py`;
   - `rotated == blocks` in the MATLAB test;
   - the second oversampled `diff.close` of `test_cpp_oracle_decode.py`;
   - the "later block" relaxation of `test_grad_peaks.py`.
7. **Tautologies:**
   - `test_gradient_points_matches_gradient_offsets_exactly`;
   - expected values computed with the implementation's own formula
     (`np.rint(duration / dt)`).
8. **Duplicates:**
   - `test_safe_and_asc_import_neither_pypulseq_nor_matplotlib` repeats
     `test_imports`, and its assumption in `TESTS.md` is false.
   - Decoding tests of `test_seqfile.py` repeat `test_decoding.py`.
   - The CRLF signature is asserted in five places.
   - `test_measurements_in_pulseq_analysis.py` re-tests most analyses of the
     main package.
9. **Gaps:**
   - No analysis test ran on a rotated file against the oracle.
   - The root suite never runs `random_gaps` or zero-duration blocks, against
     their docstrings.
   - `TESTS.md` 2.6 describes tests that do not exist, among them a refusal of
     the rotation extension, which was removed.

## 6. The API and the goals of the project

- **The plugin protocol carries no findings** (finding 1.1.6). It also had a
  `block` argument of `gradient_points` that the package ignored (finding
  1.1.1).
- **`pns_levels(hardware=(struct, label))`** repeats `SafeHardware.name`, and
  needs a `stim_thresh` that the model does not use. `CHANGELOG.md` step 6
  says to pass a `SafeHardware`, which raises `TypeError`.
- **Names and units are not the same across the API:**
  - `window` is a time range in `gradient_peaks`, and `window_s` the Hann
    length of the spectrum.
  - The results name the axes `"x"`, the sampler `"gx"` and the decoding `0`.
  - `gradients_at` takes us, and the rest of the API seconds.
  - There are two `TIME_TOLERANCE`s, of 1e-9 s and of 1e-6 RF rasters.
  - `peak_time_s` is None in one result and 0.0 in another.
- **`docs/usage.md` reads as a checker:** its sections are "Check the
  gradient limits", and its examples print "over the limit", although the
  package has no limits.
- **The public surface:**
  - Most analysis modules have no `__all__`.
  - `NO_GRADIENTS` is importable from four modules.
  - Entry points overlap: `gradient_sampler` and `GradientSampler`,
    `Snapshot(...)` and `load`, and `spec.read_spec` and `read_seqfile`.
- **Defaults the caller does not see:** `gradient_spectrum`'s
  `max_frequency_hz` and `window_s`, `pns_levels`'s `bin_s`, and the neutral
  `Session()`. Each is recorded on the result. Which must be explicit is a
  decision.

## 7. Status after PRs #134 to #196

The plan `docs/plans/cpp-siemens-review-fixes.md` (#134, closed in #141)
fixed findings 1.1.1 to 1.1.4, each with tests that failed before the fix.
Its work found three more bugs (B5 to B7). The plan
`docs/plans/remaining-review-fixes.md` covered the other findings (below).

| Finding | Bug | PR | Fix |
|---|---|---|---|
| 1.1.1 | B1 | #135 | The protocol `Decoding` has `gradient_variants()`; `_played` gives each pair of an event and a variant its own key and points. |
| 1.1.3 | B3 | #136 | The checks give the one-point reads that the stored duration hides; `Sequence.gradients_at` refuses each (block, time) that reaches one. |
| 1.1.2 | B2 | #137 | The reader's messages reach Python as bytes, decoded with `backslashreplace`. |
| 1.1.4 | B4 | #139 | Each call of the reader returns its own messages; the shared member is gone. The race was reproduced: the new tests failed on every run before the fix. |
| none | B5 | #138 | A block whose event lies wholly after its end gets two points or more. |
| none | B6 | #138 | A block whose events have all their points at one time gets two points or more, also through `spec`. |
| none | B7 | #140 | A NaN of the gradients propagates to the peaks and to the PNS summary. |

Notes:

- **Findings 3.6 and 6 (the `block` argument)** are fixed by B1: the
  protocol now uses the block, through `gradient_variants`.
- **Finding 5.1:** B1 added
  `test_the_waveform_of_the_measurements_is_the_gradients_of_the_reader`,
  which compares the measurements of `cpp-siemens` with the reader's
  `gradientsAt` on every fixture. The oracles of the root tests still share
  the package's decoding.
- **Corrections to this review.** These came from the later work:
  - **B2:** the extension names that `GetBlock` prints are not text of the
    file. Only `load` quotes the file (task 3).
  - **B6** is a bug of the package, not of `cpp-siemens`: `spec` reaches it
    with a trapezoid of times 0 alone in a rotated block.
  - **B7:** the crash on `bad_syntax_number.seq` happens with no rotation
    too. Its cause is in `grad_peaks._event_values`, and it is not tied to
    `gradients_at`.
- **Open decision** (`TODO.md`): whether `spec` reads a trapezoid whose rise,
  flat and fall times are all 0. C17 (#172) decided it below.

### The plan `docs/plans/remaining-review-fixes.md` (#143, closed in #197)

The plan covered every finding that the PRs above did not fix, in four
tracks: the code (C), the documents and the duplication (D), the API (A) and
the tests (T). Each task was one PR, and the title of each PR ends with its
task. A task that changed behaviour added its tests first, and they failed
before the fix. A9 and C18 were added after the plan was written.

| Finding | Task | PR | Fix |
|---|---|---|---|
| 1.1.5 | C1 | #145 | The points of an "edge" gradient with no sample kept have the values 0, as the reader plays it. |
| 1.1.6; 6 (no findings from a plugin) | C8 | #163 | The checks give every case of undefined behaviour, each a `Violation` of the one `SeqFileError` (the user, 2026-10-14), and use a 32-bit `long`, so that a file has one verdict on every host. |
| 1.2.1 | C13 | #177 | A gradient time shape whose first time is below 0 is `shape.time-order`; D3.9 covers gradients (the user, 2026-10-14). |
| 1.2.2, 1.2.3 | C2 | #155 | A syntax error in one event table keeps `spec`'s checks of the others, and a NaN end is not a non-zero end. |
| 1.2.4a | C3 | #153 | Rotation IDs are int64, as every other ID. |
| 1.2.4b | C9 | #165 | An extension type ID that is not positive is `id.positive`: the rule of spec:181 covers it (the user, 2026-10-14). |
| 1.2.4c | C4 | #151 | A class is not an interpreter: `interpreter()` raises `TypeError`, which names its call. |
| 1.2.4d | C14 | #182 | A shape over the package's limit of 2^27 samples is `limit.shape-samples`, not `shape.length`. |
| 1.3.1 | C5 | #144 | `RfEvent.signal` puts each cell boundary in the cell after it. |
| 1.3.2 | C11 | #152 | The `.asc` reader reads a hex int, an int with a sign and a float with an exponent sign, leaves out a line after the end marker, and reads the file as latin-1 (the user, 2026-10-14). |
| 1.3.3 | C6 | #154 | A second `FrozenDict.__init__` changes nothing, `pns_levels` refuses a hardware label `"nan"`, `"inf"` or `"-inf"`, and `AnalysisSpec` checks its fields. |
| 2.1; 2.3 (the array of each call of `gradients_at`) | C10 | #162 | `gradients_at` sorts the reads once, and each decoding keeps its row map of the rotations. |
| 2.2 | C7 | #147 | One plan for each events and duration of the rotated blocks. |
| 2.3 (the kept work of the sampler) | — | — | No code fix: keeping the sampler between calls saves 2 % on a file of 40 000 blocks and 13 % on a spiral file, and most of the cost is filling each chunk (measured on 2026-10-14; D4, #166, gives it in `docs/implementation.md`). |
| 2.4 (the labels, the RF and ADC events) | C16 | #171 | `load` decodes no RF or ADC event (`SpecDecoding` has no `rf` and no `adc`; the user, 2026-10-14), and walks the extension lists for NOROT and NOSLC only. |
| 2.4c | — | — | No code fix: a shape decompressed twice costs 0.05 s for 1000 shapes of 4000 samples, and after C16 only gradient shapes are decompressed (D4, #166). |
| 2.5a | — | — | No code fix: the plugin's decoding of a kept block again costs 0.02 s for 1000 calls and 0.10 s for 32 000 (D4, #166). |
| 2.5b | C15 | #185 | `spec._shapes_of` has no loop over the samples. |
| 2.5c | C12 | #167 | The runs of a threshold of `pns_levels` have no loop over the runs, and `docs/implementation.md` gives the measured cost in place of "a few percent". |
| 3.1 | D1 | #157 | `docs/findings-for-pulseq-checks.md` describes `main`, with relative links. |
| 3.2 | D2 | #159 | pulseq-cpp-siemens is `0.1.0rc7`, with pulseq-analysis in its extra `analysis`. |
| 3.3 | D3 | #156 | The README installs `main` until rc7, and its example handles a file with no peak. |
| 3.4 | D7 | #164 | The contracts of the analyses give the axes as the decoding gives them and the tie of the code; the versions stay 1 until 0.1.0 (the user, 2026-10-14). |
| 3.5, 4.3 | D8 | #178 | `read_seqfile` checks the scope for every interpreter, with one message (the user, 2026-10-14). |
| 3.7, 4.2 | D4 | #166 | The claims of `docs/implementation.md` match the code, and the cost table of `docs/usage.md` is a link to its section 3.5. |
| 3.8 (the stale names) | D5 | #173 | No stale names of tests and modules. |
| 3.8 (the private drafts) | D11 | #196 | Each citation of the private drafts is the behaviour and its line in pypulseq, and `scripts/check` fails on the name of their folder. |
| 3.9, 4.1, 4.2 | D0 | #146 | `tests/test_documents.py` checks the documents, also in the docs-only path. |
| 4.4 | D10 | #181 | The plugin uses the main package's `Points` and the helpers of `synth.scanner`. |
| 4.5 | D9 | #176 | One walk of the extension lists in `decoding.py`. |
| 4.6; 6 (the hardware) | A1 | #187 | `pns_levels` takes a `SafeHardware`, whose name is the label, checked once when it is made. |
| 5.1a (the claims), 5.9c | T6 | #161 | The tests say what they test: the input of the oracles is made from the package's played gradients. T12, the oracles on pypulseq's reading of the file, is dropped (the user, 2026-10-14): the decoding is tested on its own. |
| 5.2 | T13 | #184 | The original SAFE under Octave is an oracle. |
| 5.3a | T1 | #148 | The fast and the slow typing compare most tables. |
| 5.3b, 5.3e, 5.6b | T4 | #150 | MATLAB's waveform of a rotated file is compared in float64. |
| 5.3c | T3 | #149 | The spectrum oracle takes its three arguments. |
| 5.3d | T2 | #158 | A guard of `spec`'s `TOLERANCE_NS`. |
| 5.4 | T10 | #168 | A workflow runs the MATLAB oracle (the user, 2026-10-14: a separate workflow). |
| 5.5 | T9 | #174 | No tests of code outside this repository: one smoke test of the harness stays, and the hash tests (the user, 2026-10-14). |
| 5.6a, 5.6c, 5.7 | T5 | #160 | No asserts that cannot fail, and no tautologies. |
| 5.6d | T7 | #169 | Strict credit in the peaks oracle. |
| 5.8a-c | T8 | #170 | No duplicate tests. |
| 5.8d, 5.9b | T11 | #179 | The root's oracle comparisons run through `spec`. |
| 5.9a | T14 | #183 | The gradient peaks of a rotated file against MATLAB Pulseq. |
| 6 (`__all__`) | A0 | #186 | An `__all__` in every public module. |
| 6 (`window`) | A2 | #188 | `gradient_peaks` takes its time range as `range_s`. |
| 6 (the names of the axes) | A3 | #189 | The sampler takes the axes `"x"`, `"y"` and `"z"`. |
| 6 (`peak_time_s`) | A4 | #190 | A peak time is None when its block is None. |
| 6 (two `TIME_TOLERANCE`s) | A5 | #191 | The tolerance of an RF time shape is `RF_TIME_SHAPE_TOLERANCE`. |
| 6 (the entry points) | A6 | #192 | One way to make each object. |
| 6 (`gradients_at` in µs) | A7 | #193 | The protocol's `gradients_at` takes seconds. |
| 6 (the defaults) | A8 | #194 | The target data is necessary, and the method parameters have their documented defaults, recorded on the result (`docs/usage.md`, section 2). |
| 6 (the defaults) | A9 | #195 | A `PnsLevels` records the `bin_s` of its call, by the rule of A8. |
| 6 (`docs/usage.md` reads as a checker) | D6 | #175 | `docs/usage.md` gives values, not checks. |
| the open decision above | C17 | #172 | `spec` reads a trapezoid whose times are all 0, as now (the user, 2026-10-18; `docs/specification.md`, section 2.4). |
| none | C18 | #180 | An event of length 0 plays 0 in the measurements, with each interpreter. The check of C17 found it. |

Notes:

- **Finding 5.1b** was fixed by B1 (above), so the plan had no task for it.
- **The speed tasks** (C10, C12, C15) have no timing test (the user,
  2026-10-14): an equality test of the old and the new results, or a count,
  and the measured times in the PR.
- **Found in this work, and open** (`TODO.md`): `cpp-siemens` has no limit of
  the samples of a shape, where `spec` has `limit.shape-samples` (C14); and
  most of the rest of the time of `load` is in the checks of each model
  object (C16).
