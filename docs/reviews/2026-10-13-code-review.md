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
of PRs #134 to #141.

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

## 7. Status after PRs #134 to #141

The plan `docs/plans/cpp-siemens-review-fixes.md` (#134, closed in #141)
fixed findings 1.1.1 to 1.1.4, each with tests that failed before the fix.
Its work found three more bugs (B5 to B7). The other findings are open:
`TODO.md` points to this review.

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
  flat and fall times are all 0.
