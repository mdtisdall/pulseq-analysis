# Code review, 2026-10-21

A review of the whole repository at commit `ef891d5`, before the release
`0.1.0rc7`. It is the first review after the fixes of the review of
2026-10-13 (#134 to #197) and the limit of the samples of a shape (#198,
#199). It covers the package `pulseq_analysis`, the plugin
pulseq-cpp-siemens (`packages/pulseq-cpp-siemens/`), the tests, the scripts
and the documents.

The review looks for these things:

- Code that is incorrect, mis-documented, duplicative or inefficient.
- Tests that are unnecessary, that do not test what they claim, or that test
  only code outside this repository.
- Parts of the API that do not fit the goals of the project.
- Anything that makes the release `0.1.0rc7` wrong.

It does not repeat a finding of an earlier review that is fixed. The line
numbers are of commit `ef891d5`. Section 8 gives the status after the fixes
of PRs #202 to #233.

Method:

- Seven reviewers, run at the same time, each read one area in full:
  - `seqfile/`;
  - `synth/`;
  - `analyses/` with `_equality.py` and `_validate.py`;
  - the plugin, against the reader's source that `pulseq-reader.sha256`
    pins;
  - the tests of the parser, the model and the interface;
  - the tests of the analyses and the sampling;
  - the documents against the public API, with the scripts and CI.
- Small scripts against `src/` of `ef891d5`, and mutations of a copy of
  `src/` to see which tests fail. The findings marked *reproduced* were run.
  The findings marked *confirmed* were checked by reading the code.
- The main review ran again the scripts of every finding of high or medium
  severity that has one, on `ef891d5`, and got the same results.

The summary: one finding can make the process allocate without bound
(1.1.1), and four give a wrong value on an edge case (1.1.2, 1.2.1, 1.3.1,
1.1.3). The analyses have no finding above low. Four tests do not guard what
they claim (5.1 to 5.4). Two items concern the release (7).

## 1. Correctness

### 1.1 The plugin pulseq-cpp-siemens

1. **A file of 321 bytes makes `decodeBlock` allocate gigabytes, and
   `max_shape_samples` does not limit it** (*reproduced*; high).
   - `decodeBlock` resamples an RF pulse with a time shape into
     `nSamples = int(0.5 + waveform_t.back())` cells (cpp:2030-2047). It
     builds `wv_a` and `wv_p` of that size and copies them (cpp:2057-2058).
     The binding copies them into Python again.
   - The number comes from the last value of the time shape, not from the
     declared number of samples of a shape. So the check of #199 does not see
     it. The checks of `_checks.py:353-362` accept any number that fits an
     `int`.
   - Reproduced: three shapes of two samples, with the time shape `1, 5e7`,
     load with `max_shape_samples=1000`. `decode_block(0)` gives 50 000 000
     samples, at a peak memory of 1180 MB. Through `read_seqfile` with
     `CppSiemens(max_shape_samples=1000)`, the same file with `2e7` reads
     without an error, at 347 MB. A last time of 2e9 passes the checks.
   - The docstring of `load` (`__init__.py:463-470`) says that the limit is
     "so that a short file cannot make the process allocate without bound".
     That is not true for this path.
   - Fix: in `load`, compare the number of cells of each RF event with the
     same limit (`_check_rf` computes it), and raise `NotSupported`. Then the
     convention of `interpreters.Plugin` covers the samples that a reader
     resamples, not only those that a shape declares.
2. **An extended trapezoid whose first time is below 0 gives the
   measurements a waveform that the reader does not play** (*reproduced*;
   medium).
   - `_points` (`interpreter.py:945-960`) handles the times before the first
     point only when `times_us[0] > 0`. With a negative first time it gives
     the points `(0, v0), (-9 us, v0), (10 us, v1), ...`, which are not in
     order.
   - `gradientsAt` does a binary search on the times (cpp:3634-3645) and
     interpolates on the segment [t0, t1] at the start.
   - Reproduced: the times -9, 10 and 20 us and the shape 0.5, 1, 0.5 at
     1000 Hz/m. The reader plays 736.8, 789.5, 868.4 and 947.4 Hz/m at 0, 2,
     5 and 8 us; the measurements see 500, 600, 750 and 900.
   - `spec` rejects such a file (`shape.time-order`, C13). The reader reads
     it, so `cpp-siemens` must too.
     `test_the_waveform_of_the_measurements_is_the_gradients_of_the_reader`
     has no fixture with a negative or an unsorted time.
   - *Plausible*, not run: every time shape that is not in order has the
     same cause.
   - Fix: when the times do not increase from 0 or more, give the points of
     `gradientsAt` itself, as `_played` already does for a rotated block. Add
     the case as a fixture.
3. **`ub.gradient-shape-0` rejects a file whose `[TRAP]` row replaced the
   `[GRADIENTS]` row of the same ID** (*reproduced*; low to medium).
   - `_gradients_of_shape_0` (`_checks.py:428-452`) tells the two rows apart
     by the amplitude and the delay only.
   - Reproduced: `[GRADIENTS] 1 1000 0 0 0 0 0` and `[TRAP] 1 1000 10 100 10
     0`. `load` read the `[TRAP]` row (ramps 10, 100, 10), but the file is
     rejected as `ub.gradient-shape-0`. With a delay of 5 in both rows, it
     loads.
   - Fix: compare all five fields of the two rows, or replay the order in
     which `load` reads the sections.
4. **`block_soft_delays` gives its kept arrays, which a caller can change**
   (*confirmed*; low). `__init__.py:307-317`. `block_rotations` and
   `block_label_sets` give copies. The docstring of `Sequence` says nothing
   that a caller can reach changes after `load`. Fix: make the arrays
   read-only, or give copies.

### 1.2 `spec` and the model

1. **A quaternion with large or small components becomes the quaternion 0,
   which plays as no rotation** (*reproduced*; medium).
   - `_normalized` (`spec.py:1765`) and `_check_rotations` (`spec.py:1752`)
     compute the norm as `sqrt(sum(q**2))`. The squares overflow or
     underflow.
   - Reproduced: the row `1 1e200 0 0 1e200` is accepted. The model has the
     quaternion `(0, 0, 0, 0)`, and `rotations()` gives `[0, 0, 0, 0]`,
     although the protocol says the norm is 1. `synth.decoding.rotate` with
     it returns the gradients unchanged. The intended rotation is 90 degrees
     about z.
   - The row `1 1e-170 0 0 0` is rejected as `rotation.zero`, "a norm of 0".
   - Fix: divide by the largest component before the norm. Report
     `rotation.zero` only for four zeros.
2. **When a code has more than `MAX_LOCATIONS` violations, the kept ones are
   the first that `spec` checks, not the first in the file**
   (*reproduced*; low).
   - `_Report.add` (`spec.py:471-473`) keeps the first 20 of each code, and
     `spec` reads the shapes before the tables (`spec.py:1801`).
     `errors.py:51-52` says "in the order of the file".
   - Reproduced: an RF amplitude `nan` near line 33 and 57 bad samples of
     shapes. The kept `syntax.number` lines are 111 to 139; the RF row is
     left out.
   - Fix: sort all the violations of a code by line before the cut, or
     change the docstring.
3. **`decompress_shape` raises `OverflowError` for an infinite count**
   (*reproduced*; low). `model.py:271-273`: `int(count)` comes before the
   check. `decompress_shape([1, 1, inf], 5)` raises `OverflowError`; the
   docstring says `ValueError`. `spec` does not reach it, because it rejects
   a sample that is not finite first. A comparison with the algorithm of
   `decompressShape` on 20 000 random inputs found no other difference.
4. **`signature.invalid` says "not one `Type` and one `Hash`", but two of each
   are read** (*reproduced*; low). `spec.py:1160-1166` keeps the last copy of
   each key, as D2.6 does for the definitions. `docs/specification.md:239`
   does not say so. Fix: reject a repeated key, or say that D2.6 applies.

### 1.3 `synth/` and the analyses

1. **`GradientSampler.sample` gives a wrong value at the start of a block of
   duration 0 that has a gradient event** (*reproduced*; medium).
   - `lo_block` (`sampling.py:211`, `:217-219`) is the last block whose start
     is not after `t[0]`. When blocks of duration 0 start at `t[0]`, the run
     leaves out the event before them, which holds the value at the step.
   - Reproduced: a block of 100 us that ends at 1000 Hz/m, a block of
     duration 0 with a trapezoid of times 0 (C17, C18), and a block that
     starts at 1000 Hz/m. `sample("x", [100e-6])` gives 0.0;
     `sample("x", [95e-6, 100e-6])[1]` gives 1000.0, the value of the whole
     file. The result depends on the first time asked for.
   - Fix: `searchsorted(start_s, t[0], side="left") - 1`, clipped at 0. Add
     the case to the comparisons of the sampler with the oracle.
2. **Values that are finite but too large raise an error that the docstring
   does not give** (*reproduced*; low).
   - `soft_delay_durations` (`scanner.py:379-390`) raises `OverflowError`
     for a soft delay of `1e14`, not `SettingError`: the number of ticks does
     not fit an int64.
   - `bin_samples_for` (`pns_levels.py:187-191`) raises `OverflowError` for
     a `bin_s` of `1e304`. With `1e295`, `pns_levels` gives one bin, and
     `to_series` refuses the result, because the tolerance of the envelope is
     larger than `coord_end`.
   - Fix: raise the documented error when the value does not fit, and limit a
     bin to the whole sequence.
3. **`SpecDecoding.gradients_at` cuts a block index that is not an integer**
   (*reproduced*; low). `decoding.py:222`. `gradients_at([1.9], [2e-4])`
   gives the gradients of block 1. Fix: refuse an index whose type is not an
   integer.
4. **`SafeAxis` accepts a negative `g_scale`, `a1`, `a2` or `a3`**
   (*confirmed*; low). `safe.py:98-101`. With a negative `g_scale`, every
   value of the axis is 0 or less, and its `axis_peaks_hz_per_t` is 0.0
   (`pns_levels.py:419`, `:434`). Fix: refuse `g_scale <= 0`.
5. **`hardware_from_asc` raises errors that its docstring does not give**
   (*confirmed*; low). `asc.py:174-179`. An unquoted `tName = 5` gives a
   `TypeError` from `SafeHardware`, and a scalar `asCOMP = 3` an
   `AttributeError`. The docstring gives `ValueError`.

## 2. Efficiency

No finding apart from 1.1.1. A reviewer checked that the results of
`pns_levels` do not depend on the size of a chunk, for five values of
`bin_s` (*reproduced*).

## 3. Mis-documentation

1. **`NotSupported` was not updated for #198** (*confirmed*; medium).
   `errors.py:9-11` and `:93-96` say that `NotSupported` means that the
   package does not read the file "whatever the interpreter", and list only
   the scope. A shape over `max_shape_samples` is `NotSupported` too, and the
   same interpreter reads the file with a larger setting.
   `interpreters.py:21` sends the reader to `errors` for it.
2. **Stale text** (*confirmed*; low):
   - `model.py:401-402`: "Task R16 adds the records ..." R16 is done (#128),
     and its records are on the decoding.
   - `spec.py:73-74`: "the strict reader", which is gone.
   - `sampling.py:444`: a gap piece is "at most one raster time" long; it can
     be `dt + TIME_TOLERANCE` (the code uses `gaps.max_length_s`).
   - `tests/test_pns_levels.py:446`: "(the new test below checks the snap)".
3. **`docs/usage.md:1403-1404`** reads `snap.decoding.blocks`, which is not a
   member of the protocol `synth.Decoding` (*reproduced*; low).
   `docs/migration.md:257-258` reads `snap.data.blocks`.

## 4. Duplication

All *confirmed*, low:

- `synth/decoding.py:56` defines `_GRAD_COLUMNS` again; `seq_utils.py:19`
  has it.
- `spec._read_spec` (`spec.py:527-537`) has no caller in `src/` or in the
  plugin. Its three uses in `tests/test_seqfile.py` (684, 696, 1771) test
  that it equals `read_seqfile`. With A6 ("one way to make each object"), it
  can go.
- `_assemble` (`spec.py:1882-1890`) computes the `first` and `last` of each
  gradient of a 1.4 file again, after `_gradient_ends` (`spec.py:1520-1554`).
- The validation of `max_shape_samples` is in `CppSiemens.__post_init__` and
  in `pulseq_cpp_siemens.load`.
- Tests:
  - `test_seqfile.py:2968` repeats the first two asserts of `:2208`;
  - `test_seqfile.py:679` and `:687` both assert
    `_read_spec(path) == read_seqfile(path)`;
  - the plugin's `test_interpreter.py:328` is covered by `:338`;
  - `tests/test_session.py:47` (`_matrix`) and the plugin's
    `test_api.py:446` (`rotation_matrix`) are the same helper;
  - `tests/test_pns_levels.py:403-420` and `:883-897` are the same reference
    of the runs.

## 5. Tests

The mutations were made in a copy of `src/`. "Survives" means that the
named tests still pass.

1. **No test guards the step at the end of the sequence inside a range**
   (*reproduced*; high for the tests, the code is correct).
   - The rule is `step_hi = min(hi, end_s - TIME_TOLERANCE)` in
     `_evaluate_axis` (`grad_peaks.py:916`).
     `check_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end`
     (`test_grad_peaks.py:419-443`, and the plugin's
     `test_measurements_in_pulseq_analysis.py:133`) claims to test it. Its
     range `(0, end_s)` is the whole file, which takes another path, and its
     other range leaves the step out through `hi` alone.
   - The mutation `min(hi, end_s)` survives `test_grad_peaks.py`,
     `test_oracle_waveform.py` and `test_analyses.py` (354 passed) and the
     plugin's measurements (240 passed). With it, `range_s=(1e-4, end_s)`
     through `cpp-siemens` gives a slew of 3.19e9 against the oracle's 1e9;
     on `ef891d5` both give 1e9.
   - Fix: add a range with a start above 0 that ends at `end_s`.
2. **The cases of one ulp and below the tolerance at the end are not what
   they claim** (*reproduced*; medium).
   - The 20 values of `k` of
     `test_a_gradient_that_ends_at_the_end_of_the_sequence_has_no_step`
     (`test_grad_peaks.py:389-411`) all give a last time exactly at `end_s`
     through `spec`. TESTS.md 2.6 says some give one ulp before it.
   - The plugin's `early` of 0.5 and 0.9 of `TIME_TOLERANCE` are lost when
     the file is written: both play as `early = 0`. TESTS.md 3.10 says that
     only the tolerance rule leaves them out.
   - So the rule `lt[-1] < index.end_s - TIME_TOLERANCE`
     (`grad_peaks.py:425`) has no guard in the root tests.
   - Fix: build these cases with times that the file keeps, assert the
     played `early`, and correct TESTS.md 2.6 and 3.10.
3. **`PEAK_TOLERANCE` and the meaning of `peak_time_s` are not pinned**
   (*reproduced*; medium). Each expected peak time comes from the package's
   own `PEAK_TOLERANCE` (`test_pns_levels.py:157-160`,
   `test_safe_oracle.py:213`). With `0.3` or `0.0`, the root and the plugin
   tests pass. This is the case of finding 5.3d of 2026-10-13
   (`TOLERANCE_NS`). Fix: a guard of the value, and one case with the
   expected sample written as a number.
4. **The equality of models does not see `interpreter`, `records`,
   `origin` or the order of a mapping** (*reproduced*; medium).
   `test_models_are_equal_by_value_and_not_hashable`
   (`test_seqfile.py:2845`) changes only an RF amplitude. Leaving
   `interpreter`, `records` or `origin` out of `_model_eq`, or sorting the
   keys of a mapping, survives the root tests. `records` with `origin`
   survives the plugin's too. `load(data, interpreter)` relies on this
   equality. Fix: compare a model with `dataclasses.replace` of itself for
   each field.
5. **Three checks of `check_shape_limit` can be removed and no test fails**
   (*reproduced*; medium). The values `True` and `1.5`, and the `str` of a
   setting `None`. None of the eight classes of
   `test_the_check_of_the_shape_limit_fails_for_a_plugin_that_does_not_follow_it`
   (`test_interpreters.py:261`) breaks them. Fix: three more classes.
6. **No test of `SOURCE` in a `NotSupported` of `read_pypulseq`**
   (*reproduced*; medium). `from_pypulseq.py` replaces the path with
   `SOURCE`; with #198 this is reachable
   (`read_pypulseq(seq, Spec(max_shape_samples=3))`). A bare `raise` in its
   place survives the root tests. Fix: a test beside `check_a_rejection`
   (`test_from_pypulseq.py:168`).
7. **Smaller gaps** (*reproduced* or *confirmed*; low):
   - Nothing checks that `interpreter_names()` imports no plugin, or that it
     sorts the names (`test_interpreters.py:174`, `:187`): an eager import
     survives.
   - `test_comments_and_blank_lines_are_skipped_after_the_header_of_any_section`
     (`test_seqfile.py:873`) compares with `same_values`, which leaves out
     the signature, so its `[SIGNATURE]` case checks nothing.

## 6. The API and the goals of the project

No new finding. 1.1.1 is a gap in the convention of #198: the limit covers
what a shape declares, not what a reader makes from it.

## 7. The release `0.1.0rc7`

1. **No check confirms that the lockfiles match `pyproject.toml`**
   (*confirmed*; medium). Every sync of `scripts/check` (lines 61, 78, 114)
   and of `matlab-oracle.yml` uses `--frozen`, which does not check the
   lock. The release changes the version of the root from `0.1.0rc6` to
   `0.1.0rc7`, and `test_documents.py:571` accepts both. The locks are up to
   date today (`uv lock --check` of both projects). Fix: run `uv lock
   --check` for both projects in the full path of `scripts/check`, and make
   the release check that both distributions are `0.1.0rc7`.
2. **The entry "Unreleased" of `CHANGELOG.md`, which becomes the notes of the
   release, has gaps** (*reproduced*; medium and low):
   - It says that an old name raises `ImportError`, `AttributeError` or
     `TypeError` (`CHANGELOG.md:9-12`). The rc6 line
     `from pulseq_analysis.analyses import registry` raises nothing: it binds
     the module, and the call fails later. `docs/migration.md:133-138` says
     so; the changelog does not.
   - The table of the defaults of `docs/usage.md` (239-257), which the
     changelog says gives each default (625-628), has no row for
     `max_shape_samples`, nor for `oversampling` and `rotation` of
     `cpp-siemens`.
   - Line 370-371 names `gradient_offsets` only; `gradient_points` changed
     its argument too (`docs/migration.md:334`).
   - New public names that the changelog does not name, although
     `docs/migration.md:12` says it lists every change:
     `spec.RANGE_TOLERANCE` and `MAX_LOCATIONS`, `synth.decoding.Points`,
     `model.TABLE_DTYPES`, `decompress_shape` and `Rasters`,
     `from_pypulseq.SOURCE`, `interpreters.GROUP` and `seqfile.Interpreter`.

Checked and found correct, among others: the README example and the code
blocks of `docs/usage.md` and `docs/migration.md` (run); the errors that the
changelog and the migration guide promise for the names of rc6 (run); the
signatures and result fields of rc6 against `main`; the version
(`0.1.0rc7`) and the extra `analysis` of the plugin; every relative link of
the documents; the docs-only path of `scripts/check`.

## 8. Status after PRs #202 to #233

The plan `docs/plans/review-2026-10-21-fixes.md` (#201, closed in #233)
fixed every finding of this review, before the release `0.1.0rc7` (the user,
2026-10-21). Each task was one PR, whose title ends with the task. A task
that changed behaviour added its tests first, and they failed before the
fix; a task that made a test stronger showed a mutation that the old tests
missed and the new ones catch.

| Finding | Task | PR | Fix |
|---|---|---|---|
| 1.1.1 | C1 | #208 | `max_shape_samples` also limits the cells into which `cpp-siemens` resamples an RF pulse, before the allocation; the convention of every interpreter and `check_shape_limit` say so (the user, 2026-10-21). |
| 1.1.2 | C2 | #210 | An extended trapezoid whose first time is below 0 plays in the measurements as the reader plays it. Times out of order are recorded (D7.7 of the plugin's record, `TODO.md`), not fixed (the user, 2026-10-21). |
| 1.1.3 | C5 | #212 | `ub.gradient-shape-0` follows the order in which `load` reads the sections: a `[TRAP]` row of the ID replaces the event. |
| 1.1.4 | C6 | #211 | `block_soft_delays` gives copies. |
| 1.2.1 | C4 | #202 | A quaternion is scaled by a power of 2 before its norm; `rotation.zero` is for four zeros. |
| 1.2.2 | C7 | #213 | The docstring of `SeqFileError` says which violations `spec` keeps (the user, 2026-10-21). |
| 1.2.3 | C8 | #209 | `decompress_shape` raises `ValueError` for a count that is not finite. |
| 1.2.4 | C9 | #216 | A repeated `Type` or `Hash` is read, the last wins, as D2.6; the rule text says so (the user, 2026-10-21). |
| 1.3.1 | C3 | #206 | The sampler at the start of a block of duration 0; the time-range check has each block start. |
| 1.3.2 (soft delay) | C10 | #214 | A soft delay that does not fit an int64 is a `SettingError`. |
| 1.3.2 (`bin_s`) | C11 | #223 | A bin is at most the whole sequence (the user, 2026-10-21). |
| 1.3.3 | C12 | #217 | Each `gradients_at` refuses a block index that is not an integer. |
| 1.3.4 | C13 | #218 | `SafeAxis` refuses a `g_scale` that is not above 0 and a negative `a1` to `a3` (the user, 2026-10-21). |
| 1.3.5 | C14 | #219 | A component name of a `.asc` file that is not a text is a `ValueError`. |
| 3.1 | C1 | #208 | The docstrings of `NotSupported` include the setting. |
| 3.2 | D1 | #230 | The stale text. |
| 3.3 | D2 | #225 | `docs/usage.md` reads `snap.data.blocks`; a check reads each member of a decoding in the documents. |
| 4 | D3, D4, D5, D6, D7 | #220, #226, #228, #221, #232 | One `_GRAD_COLUMNS`; no `spec._read_spec`; one computation of the ends of a 1.4 gradient; one check of the setting in the plugin; no duplicate tests (the twin rotation helpers name each other). |
| 5.1, 5.2 | T1 | #203 | The step at the end, in a range and below the tolerance. |
| 5.3 | T2 | #227 | A guard of `PEAK_TOLERANCE` and of the rule of the peak time. |
| 5.4 | T3 | #205 | The equality of models sees each field. |
| 5.5 | T4 | #215 | The breakers of `check_shape_limit`; its files have no number in their names. |
| 5.6 | T5 | #207 | `SOURCE` in a `NotSupported` of `read_pypulseq`. |
| 5.7 | T6, T7 | #222, #224 | `interpreter_names` sorts and imports no plugin; the signature after a comment. |
| 7.1 | R1, R2 | #204, #231 | `scripts/check` checks the locks; the version test reads the newest entry of `CHANGELOG.md`. |
| 7.2 | D8 | #229 | The release notes name each public name and each setting; a check keeps them so. |

Notes:

- **What the work found:**
  - `from pulseq_analysis.analyses import pns_levels`, as `registry`, gives
    the submodule and raises nothing (D8).
  - A fuzz corpus file had an RF last time of `inf`, which the limit of C1
    now refuses; it has `nan`, which stays `ub.rf-time-range`.
  - The core package names no plugin, so the docstring of C7 names "a
    plugin interpreter".
- **Mutations that no test can catch,** because they give the same result:
  the clip at 0 of C3, the cap without `max(., 1)` of C11, and the cut of
  times out of order of C2, which the user chose not to fix.
- **Open:** the measurements of `cpp-siemens` on an extended trapezoid whose
  times are out of order (`TODO.md`).
