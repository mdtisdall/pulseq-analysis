# Implementation plan: the fixes of the review of 2026-10-21

Status: written on 2026-10-21. The user decided D-a and D-b, and answered
every decision of section 9, on 2026-10-21; each answer is recorded there.

## 1. Scope

`docs/reviews/2026-10-21-code-review.md` (in this plan, "the review") is a
review of `ef891d5`, before the release `0.1.0rc7`. This plan covers every
finding of the review, the low ones too (D-b). The release comes after the
plan (section 11).

On 2026-10-21 each finding was checked again on `ef891d5` by reading its
lines, and the scripts of the reviewers were run again where this plan says
so. Every finding holds. Section 7 gives the corrections of detail, and what
the check of `spec` and `synth` for D-a found. The line numbers in this plan
are of `ef891d5`.

The work has four tracks:

| Track | Findings | Kind |
|---|---|---|
| C | 1.1, 1.2, 1.3, and 3.1 with 1.1.1 | Correctness of the code |
| D | 3.2, 3.3, 4, 7.2 | Documents, the release notes, and duplication |
| T | 5 | The tests |
| R | 7.1 | Release readiness: the locks and the versions |

Sections 2 (efficiency) and 6 (the API) of the review have no finding apart
from 1.1.1, which is task C1.

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern).
Each follows the rule of section 2.

## 2. The rule for the tests of each task

This is the rule of the plan of the fixes of the review of 2026-10-13. It
still holds.

1. **A task that changes behaviour.** The first commit adds the tests of the
   task, and no fix. They fail on that commit, and the PR quotes the
   failure. The fix commits then make the same tests pass, with no change to
   them except a name or a message. A test that pins a behaviour that does
   not change (the task says so) passes on the first commit.
2. **A refactor.** Behaviour does not change. The existing tests must pass
   unchanged, and the PR gives the tests that cover the code it moves.
3. **A documentation task.** Where a check can keep the text right, the first
   commit adds the check (in `tests/test_documents.py`), and it fails on
   `main`. The text fix then makes it pass.
4. **A test task.** A test that is made stronger gets a mutation: a one-line
   change to `src/` that the old test misses and the new one catches. The PR
   quotes both runs. The mutation is applied only in the PR's runs, never
   committed. Each task below names its mutation where one was found.
5. **A check of `scripts/check` (track R).** The PR shows the check failing
   on a one-line edit, and passing without it.
6. **Always.** Each new test gets an entry in `TESTS.md`, and each removed
   test loses its entry. No task adds a fixture to `tests/seqfiles/`, because
   each such fixture needs a new entry in the plugin's `expected_digests.json`
   from the driver. A test builds its file in `tmp_path` instead.
7. **The plugin's tests.** A test that imports `pulseq_analysis` goes in a
   module of `conftest.ANALYSIS_TESTS`. The wheel tests run without
   pulseq-analysis (the lesson of #137).

## 3. Track C: correctness

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| C1 | `fix/limit-of-resampled-rf-cells` | 1.1.1, 3.1 | M | Q1 |
| C2 | `fix/cpp-siemens-gradient-times-below-0` | 1.1.2 | S | Q2 |
| C3 | `fix/sampler-zero-duration-block-start` | 1.3.1 | S | — |
| C4 | `fix/quaternion-norm-overflow` | 1.2.1 | S | — |
| C5 | `fix/gradient-shape-0-replaced-by-trap` | 1.1.3 | S | Q3; after C1 |
| C6 | `fix/soft-delays-of-a-sequence` | 1.1.4 | S | Q4; after C1 |
| C7 | `docs/max-locations-order` | 1.2.2 | S | Q5; after C1 |
| C8 | `fix/decompress-shape-infinite-count` | 1.2.3 | S | after T3 |
| C9 | `fix/signature-repeated-key` | 1.2.4 | S | Q6; after C1, C8 |
| C10 | `fix/soft-delay-that-does-not-fit` | 1.3.2 (soft delay) | S | — |
| C11 | `fix/bin-longer-than-the-sequence` | 1.3.2 (`bin_s`) | S | Q7; after C9 |
| C12 | `fix/block-index-is-an-integer` | 1.3.3 | S | after C2, C6 |
| C13 | `fix/safe-axis-signs` | 1.3.4 | S | Q8 |
| C14 | `fix/asc-component-name-errors` | 1.3.5 | S | — |

### C1. The limit covers the RF cells of `cpp-siemens` (1.1.1, 3.1)

- **The bug (1.1.1):**
  - `decodeBlock` resamples an RF pulse with a time shape into
    `nSamples = int(0.5 + waveform_t.back())` cells (cpp:2031), and builds
    `wv_a` and `wv_p` of that size (cpp:2034-2035). The binding copies them
    into Python.
  - The number is the last time of the time shape, not the number of
    samples that a shape declares. `load` (`__init__.py:502-507`) compares
    only `shape.num_samples` with the limit. `_check_rf`
    (`_checks.py:330-362`) computes the number (`n_cells`) and accepts any
    number that fits an `int`.
  - Reproduced by the review: three shapes of two samples, the time shape
    `1, 5e7`, `max_shape_samples=1000`: `decode_block(0)` gives 50 000 000
    samples, at a peak of 1180 MB. Through `read_seqfile` with
    `CppSiemens(max_shape_samples=1000)`, the time shape `1, 2e7` reads, at
    347 MB.
  - The docstring of `load` (`__init__.py:463-470`) says that the limit is
    there "so that a short file cannot make the process allocate without
    bound". That is not true for this path.
- **The documents of `NotSupported` (3.1):** `errors.py:9-11` and `:93-96`
  say that `NotSupported` means that no interpreter reads the file, and list
  only the scope. A shape over `max_shape_samples` is `NotSupported` too
  (#198), and the same interpreter reads the file with a larger setting.
  `interpreters.py:21` sends the reader to `errors` for it. This task widens
  the same convention, so it corrects these lines too.
- **The fix (D-a):**
  - The convention (`interpreters.py:17-21`, and the item
    `max_shape_samples` of `Plugin`, `interpreters.py:130-138`): the setting
    limits every array of samples that a reader makes from a shape, the
    samples that a shape declares and the samples that the reader resamples
    from it. Over the limit is `NotSupported`, before the allocation.
  - Plugin `_checks.py`: one function gives the number of cells of each RF
    event that `decodeBlock` resamples (a time shape that is not 0, not a
    regular time shape of 3 or 4 stored values, and that decompresses), as
    `0.5 + t[-1]` in double, before the conversion to `int`. `_check_rf`
    uses it.
  - Plugin `load`: after the check of the shapes and before
    `_checks.undefined_behaviour`, it compares the cells of each RF event,
    by ID, with the limit, and raises `NotSupported`. The message gives the
    path, the RF event, its time shape, the number of cells and the limit,
    and names the setting. With no limit, a last time that does not fit an
    `int` stays `ub.rf-time-range` (D5.9).
  - `conformance.check_shape_limit` (Q1 (a)): a check with a file whose RF
    time shape ends at 2^21 RF rasters and whose three shapes have 2
    samples. With the limit 2^20, `read_seqfile` reads the file or raises
    `NotSupported`; a `NotSupported` gives the path, the number of cells
    (2^21) and the limit, and names the setting. With the limit 2^21 and
    with None, the file reads. The docstring says that the check cannot see
    a plugin that resamples and ignores the limit (its C++ memory is not a
    Python allocation), so each plugin guards that in its own tests.
  - `spec` gets no new check: `spec` and `synth` make no array whose size is
    a value of a shape (section 7).
  - `errors.py` (3.1): `NotSupported` is a file outside the scope, or a file
    with an array of samples over the setting `max_shape_samples` of the
    interpreter, which a larger setting reads.
  - The documents: the docstring of `load`; the plugin's `README.md`
    (46-52, 155) and `docs/specification.md` (412-418); `docs/usage.md`
    (849-864); `docs/specification.md` (243-246: `spec` makes no array from
    the times of a shape); `docs/migration.md` (181);
    `docs/findings-for-pulseq-checks.md` (150-168, 338); `CHANGELOG.md`.
- **The tests:**
  - `test_an_rf_pulse_whose_resampling_has_more_cells_than_max_shape_samples_is_not_supported`
    (plugin `test_api.py`, a wheel test): an inline 1.5.0 file with three
    shapes of two samples and the time shape `1, 2000`. `load` with the
    limit 1000 raises `NotSupported` that names the RF event, the time
    shape, 2000, 1000 and the setting. With 2000 and with None it loads, and
    `decode_block(0)` gives 2000 samples. It fails on `main`.
  - `test_an_rf_pulse_over_max_shape_samples_is_not_supported_with_the_path_of_the_file`
    (plugin `test_interpreter.py`): the same file in `tmp_path`, through
    `read_seqfile` with `CppSiemens(max_shape_samples=1000)`; the message
    has the path.
  - `test_spec_reads_an_rf_pulse_of_more_cells_than_max_shape_samples`
    (`tests/test_interpreters.py`): `spec` reads the file with the limit
    1000, and `decode_rf` gives the pulse of its 2 points. It passes on
    `main`: it pins the result of section 7.
  - The new check, with a class that breaks it (a `NotSupported` of the RF
    file with no path or number, or a refusal at the limit 2^21) as a new
    case of
    `test_the_check_of_the_shape_limit_fails_for_a_plugin_that_does_not_follow_it`.
    `test_cpp_siemens_follows_the_convention_of_max_shape_samples` runs the
    new check.

### C2. An extended trapezoid whose first time is below 0 (1.1.2)

- **The bug:**
  - `_points` (plugin `interpreter.py:945-960`) handles the times before the
    first point only when `times_us[0] > 0`. With a first time below 0 the
    points `(0, v0), (-9 us, v0), (10 us, v1), ...` are not in order.
  - `gradientsAt` does a binary search on the times (cpp:3638-3649), and
    ends the event at the last time, `times.back()` (cpp:3621), also
    when an earlier time is larger. At the first and the last time it gives
    the first and the last sample (cpp:3628-3636).
  - Reproduced by the review: the times -9, 10 and 20 us and the shape 0.5,
    1, 0.5 at 1000 Hz/m. The reader plays 736.8, 789.5, 868.4 and
    947.4 Hz/m at 0, 2, 5 and 8 us; the measurements see 500, 600, 750 and
    900.
  - `spec` rejects the file (`shape.time-order`, D3.9). The reader reads
    it.
- **Times out of order (Q2 (b)): no fix.** Reproduced for this plan (the
  review called it plausible): the times 0, 20, 10 and 30 us and the shape
  0.5, 1, 0.25, 0.5 at 1000 Hz/m. At 12, 15, 18 and 20 us the reader plays
  275, 312.5, 350 and 375 Hz/m; the measurements give 800, 875, 950 and
  1000. The user decided on 2026-10-21 that this stays: the measurements of
  `cpp-siemens` differ from the reader on such a file. C2 records it.
- **The fix (Q2 (b)):**
  - For a time shape in order (each time at or after the one before it)
    whose first time is below 0, `_points` cuts the polyline at the delay:
    the first point is at 0, with the value of the segment that holds 0 (in
    the arithmetic of the existing branch for `times_us[0] > 0`, which
    copies the reader's `linear_interpolation`), and the points before 0
    go. On such times the binary search reads that segment at each time
    between 0 and its end, so the cut polyline is the reader's. The task
    checks a last time at or below 0 against the reader too.
  - A time shape out of order keeps the points of today.
- **The record (the lasting fact):**
  - The plugin's `docs/specification.md` gets an entry in its section 2.4
    (D7.7, or the next free ID of the group that fits): an extended
    trapezoid whose first time is below 0, or whose times are out of order.
    The reader: the binary search (cpp:3638-3649), the end at the last time
    (cpp:3621). `cpp-siemens`: the measurements cut the polyline at 0 for a
    first time below 0, as the reader plays it; for times out of order they
    take the vertices in the order of the file, and differ from the reader:
    the times 0, 20, 10 and 30 us of the shape 0.5, 1, 0.25, 0.5 at
    1000 Hz/m give 275 Hz/m at 12 us on the reader and 800 in the
    measurements (the user, 2026-10-21). `gradients_at` gives the reader's
    values in both cases. Why: no writer makes such times
    (`makeExtendedTrapezoid.m:51`, `make_extended_trapezoid.py:87-88`), and
    the user chose to fix only a first time below 0 (2026-10-21).
  - `TODO.md` gets an item: the measurements of `cpp-siemens` on an
    extended trapezoid whose times are out of order differ from the reader,
    with the same numbers, "(the user, 2026-10-21)", and the entry of the
    record.
- **The tests:**
  - `test_the_measurements_of_an_extended_trapezoid_whose_first_time_is_below_0_are_the_gradients_of_the_reader`
    (plugin `test_load_in_pulseq_analysis.py`), parametrized over the time
    shapes `-1, 1, 2` and `-2, -1, 1, 2`, and a control `0, 1, 2`. Each
    file is in `tmp_path`. The sampler equals `reading.gradients_at` on a
    grid of 1 us over the block, not only at the probes of
    `_reader_probes`, which come from the points under test. The values of
    the review are written as numbers (736.8 Hz/m at 0 us).
  - `gradient_peaks` of each file gives the largest value of the reader on
    that grid as the peak.
  - Times out of order get no test: a test would assert the wrong value.
    The record and `TODO.md` hold the fact.

### C3. The sampler at the start of a block of duration 0 (1.3.1)

- **The bug:** `lo_block` (`sampling.py:211`) is the last block whose start
  is not after `t[0]` (`side="right"`). When blocks of duration 0 start at
  `t[0]`, the run (`:217-219`) leaves out the event before them, which holds
  the value at the step. Reproduced (the review's script, run again): a
  block of 100 us that ends at 1000 Hz/m, a block of duration 0 with a
  trapezoid of times 0 (C17, C18 of the review of 2026-10-13), and a block
  that starts at 1000 Hz/m. `sample("x", [100e-6])` gives 0.0, and
  `sample("x", [95e-6, 100e-6])[1]` gives 1000.0.
- **The fix:** `lo_block` is
  `searchsorted(start_s, t[0], side="left") - 1`, clipped at 0.
- **The tests:**
  - `test_sample_at_the_start_of_a_block_of_duration_0_does_not_depend_on_the_first_time`
    (`tests/test_sampling.py`): the file above in `tmp_path`;
    `sample("x", [100e-6])` equals `sample("x", [95e-6, 100e-6])[1]` and the
    value of the oracle `tests/oracles/waveform.py`.
  - The sequence joins the sequences of
    `test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`
    (`_TIME_RANGE_NAMES`), so that each time range of the comparison with
    the oracle meets it.

### C4. A quaternion with large or small components (1.2.1)

- **The bug:** `_normalized` (`spec.py:1761-1768`) and `_check_rotations`
  (`spec.py:1746-1758`) compute the norm as `sqrt(sum(q**2))`, and the
  squares overflow or underflow. Reproduced (run again): the row
  `1 1e200 0 0 1e200` reads, the model has the quaternion `(0, 0, 0, 0)`,
  `rotations()` gives `[0, 0, 0, 0]`, and `synth.decoding.rotate` with it
  returns the gradients unchanged. The intended rotation is 90 degrees about
  z. The row `1 1e-170 0 0 0` is rejected as `rotation.zero`.
- **The fix:** divide each quaternion by its largest absolute component
  before the norm. `rotation.zero` is for four zeros only. D3.10 of
  `docs/discrepancies.md` says so.
- **Not affected:** the C++ reader rejects a quaternion whose norm is more
  than 1e-3 from 1 (cpp:1285-1290), and `Session` refuses a `fov_rotation`
  whose norm is more than 1e-6 from 1 (`scanner.py:151-153`).
- **The test:**
  `test_a_quaternion_with_large_or_small_components_is_normalized_and_only_four_zeros_are_rejected`
  (`tests/test_seqfile.py`): `1 1e200 0 0 1e200` gives
  `(sqrt(0.5), 0, 0, sqrt(0.5))`, `1 1e-170 0 0 0` gives `(1, 0, 0, 0)`,
  and `1 0 0 0 0` is `rotation.zero`.

### C5. A `[TRAP]` row that replaced a `[GRADIENTS]` row (1.1.3)

- **The bug:** `_gradients_of_shape_0` (plugin `_checks.py:428-452`) tells
  the two rows apart by the amplitude and the delay only. Reproduced (run
  again): `[GRADIENTS] 1 1000 0 0 0 0 0` and `[TRAP] 1 1000 10 100 10 0`.
  `load` read the `[TRAP]` row (ramps 10, 100, 10), but the file is rejected
  as `ub.gradient-shape-0`. With a delay of 5 in the `[GRADIENTS]` row, it
  loads.
- **The fix (Q3 (a)):** the check follows the order in which `load` reads
  the sections: the event is the `[GRADIENTS]` row of shape 0 when no row of
  `[TRAP]` (`Reader.gradient_rows`) has its ID. The test of the amplitude
  and the delay goes. D5.2 of the plugin's record says so.
- **The test:**
  `test_a_gradients_row_of_shape_0_that_a_trap_row_replaced_is_read`
  (plugin `test_undefined_behaviour.py`, a wheel test): the file above
  loads, and `gradients_at` gives the trapezoid of the `[TRAP]` row. The
  same file without the `[TRAP]` row is still `ub.gradient-shape-0`.

### C6. `block_soft_delays` gives its kept arrays (1.1.4)

- **The bug:** `block_soft_delays` (plugin `__init__.py:307-317`) returns
  the arrays that it keeps, so a caller can change them, and the next call
  and the decoding (`interpreter.py:735`) read the changed values.
  `block_rotations` and `block_label_sets` give copies (`:295-305`,
  `:319-328`). The docstring of `Sequence` (`__init__.py:214-217`) says that
  nothing that a caller can reach changes after `load`.
- **The fix (Q4 (a)):** copies, as `block_rotations` and
  `block_label_sets` give.
- **The test:**
  `test_a_change_to_the_soft_delays_that_a_sequence_gives_does_not_change_the_sequence`
  (plugin `test_api.py`): a change to each array of one result does not
  change the next result.

### C7. The order of the kept violations of a code (1.2.2)

- **The text that is wrong:** `_Report.add` (`spec.py:460-473`) and
  `_Report.rows` (`:475-488`) keep the first `MAX_LOCATIONS` violations of
  each code that `spec` finds, and `spec` reads the shapes before the tables
  (`spec.py:1801`); `_Report.error` (`:490-493`) sorts the kept by line.
  `errors.py:51-52` says "in the order of the file". Reproduced (run again):
  an RF amplitude `nan` and 57 bad samples of shapes; the kept
  `syntax.number` lines are 111 to 139, and the RF row is left out. The same
  docstring covers `cpp-siemens`, which keeps its cases in play order
  (plugin `interpreter.py:42`, `:360-368`).
- **The fix (Q5 (b)):** a documentation task; the code does not change.
  `errors.py:51-52` says what each interpreter keeps: `spec` the first
  `MAX_LOCATIONS` that it finds for each code, in the order of its checks,
  sorted by line; `cpp-siemens` its cases in play order (as its module
  docstring says). `docs/usage.md:1009` and
  `docs/findings-for-pulseq-checks.md:354` give no order, so they do not
  change.
- **No check (rule 3):** no check of `tests/test_documents.py` can read the
  order that a docstring gives. The PR gives the lines.

### C8. `decompress_shape` and a count that is not finite (1.2.3)

- **The bug:** `model.py:271-273`: `int(count)` comes before the check.
  `decompress_shape([1, 1, inf], 5)` raises `OverflowError`, and
  `[1, 1, nan]` a `ValueError` of Python's own message. The docstring gives
  `ValueError` with a message that says what is wrong. `spec` does not reach
  it: it rejects a sample that is not finite first.
- **The fix:** a count that is not finite is the same `ValueError` as a
  count that is not a whole number of at least 0.
- **The test:** two new cases of
  `test_decompress_shape_rejects_a_code_that_is_not_num_samples_long`
  (`tests/test_seqfile.py`): `[1, 1, inf]` and `[1, 1, nan]` with the
  message of the repeat count.

### C9. A repeated `Type` or `Hash` of `[SIGNATURE]` (1.2.4)

- **The bug:** `signature.invalid` says "[SIGNATURE] has not one Type and
  one Hash" (`spec.py:368-371`), but `_read_signature` (`spec.py:1155-1167`)
  reads two of each and keeps the last, as D2.6 does for the definitions.
  Reproduced (run again): `Type sha1`, `Type md5`, `Hash 0000`, `Hash <md5>`
  read as an md5 signature that matches. `docs/specification.md:239` does
  not say so.
- **The fix (Q6 (b)):** the code does not change: the last `Type` and the
  last `Hash` win, as D2.6 does for the definitions. The text of the rule
  (`spec.py:369`), `docs/specification.md:239` and `docs/usage.md:1050`
  say "no `Type` or no `Hash`, or one that is not one value", and D2.6 of
  `docs/discrepancies.md` names the signature, with the readers' sources
  of Q6.
- **The test:**
  `test_a_repeated_type_or_hash_of_the_signature_is_read_and_the_last_wins`
  (`tests/test_seqfile.py`): the file of the reproduction reads as an md5
  signature that matches. It passes on `main` (rule 1: it pins a behaviour
  that does not change). No check of `tests/test_documents.py` reads the
  text of a rule: `test_the_codes_of_spec_in_the_documents_are_spec_rules`
  compares the codes only.

### C10. A soft delay that does not fit an int64 (1.3.2, the soft delay)

- **The bug:** `soft_delay_durations` (`scanner.py:379-390`) raises
  `OverflowError`, not `SettingError`, for a soft delay of `1e14` s: the
  number of ticks does not fit an int64 (run again: `1e14` and `1e15`).
- **The fix:** a duration of more ticks than an int64 holds is a
  `SettingError` for that hint, with the play index of the block, as for a
  duration that is not finite. The docstring says so.
- **The test:**
  `test_a_soft_delay_whose_duration_does_not_fit_an_int64_is_a_setting_error`
  (`tests/test_session.py`).

### C11. A bin longer than the sequence (1.3.2, `bin_s`)

- **The bug:** `bin_samples_for` (`pns_levels.py:178-191`) raises
  `OverflowError` for a `bin_s` of `1e304` (`round` of an infinite ratio).
  With `1e295`, `pns_levels` gives one bin, and `to_series` refuses the
  result: the tolerance of the envelope (`series.py:395-403`, `1e-9` of
  `coord_step`) is larger than `coord_end`. Run again on `ef891d5`.
- **The fix (Q7 (a)):** a bin is at most the whole sequence: `wanted` is at
  most `max(num_samples, 1)`, the `num_samples` of the snapshot, compared in
  float before `round`. So the cap follows the reading of each interpreter,
  and the rule is the same for every interpreter. The docstrings of
  `bin_samples_for` and
  `pns_levels`, the text of the analysis in `registry.py:384-390`, and
  `docs/usage.md` follow.
- **The test:**
  `test_a_bin_longer_than_the_sequence_is_the_whole_sequence`
  (`tests/test_pns_levels.py`): `bin_s` of `1e304`, `1e295` and 1000 s on a
  short file give `bin_samples == num_samples`, one bin, and a series that
  `to_series` makes.

### C12. A block index that is not an integer (1.3.3)

- **The bug:** `SpecDecoding.gradients_at` (`decoding.py:222`) casts the
  block index with `np.asarray(..., dtype=np.int64)`, which cuts a float:
  `gradients_at([1.9], [2e-4])` gives the gradients of block 1 (run again).
  The plugin does the same, in `CppSiemensDecoding.gradients_at` (plugin
  `interpreter.py:829`) and in `Sequence.gradients_at` (plugin
  `__init__.py:362`); the review asked whether it does.
- **The fix:** each `gradients_at` raises `TypeError` for a block index whose
  dtype is not an integer (a bool too). An empty list, which numpy makes
  float64, stays allowed. The protocol `Decoding.gradients_at`
  (`decoding.py:81-84`) says so.
- **The tests:**
  - `test_gradients_at_refuses_a_block_index_that_is_not_an_integer`
    (`tests/test_decoding.py`): `[1.9]`, `[1.0]` and `[True]` raise
    `TypeError`; `[1]`, `np.int32` indices and `[]` read.
  - The same through `cpp-siemens` (plugin
    `test_interpreter_in_pulseq_analysis.py`), and for `Sequence.gradients_at`
    (plugin `test_api.py`).

### C13. `SafeAxis` and the sign of its fields (1.3.4)

- **The bug:** `SafeAxis` (`safe.py:115-140`, the check of `:98-101`)
  accepts a negative `g_scale`, `a1`, `a2` or `a3`. With a negative
  `g_scale`, every value of the axis is 0 or less, and its
  `axis_peaks_hz_per_t` is 0.0: the axis peak starts at 0
  (`pns_levels.py:419`, `np.maximum`), while the total is the root of the
  sum of the squares (`pns_levels.py:545`), which is positive.
- **The fix (Q8 (b)):** `SafeAxis` refuses a `g_scale` that is not above 0,
  and a negative `a1`, `a2` or `a3` (0 turns a term off), with `ValueError`
  that names the field. `tau1` to `tau3` keep what SAFE allows. Its
  docstring says so, and that the original SAFE checks no sign.
- **The test:** new cases of `test_a_safe_axis_refuses_a_bad_field`
  (`tests/test_safe.py`), one for each refused sign, and a case of each
  field at its smallest accepted value.

### C14. The errors of `hardware_from_asc` (1.3.5)

- **The bug:** `hardware_name` (`asc.py:174-179`) returns `tName` whatever
  its type, and calls `.get` on `asCOMP` whatever its type. An unquoted
  `tName = 5` gives a `TypeError` from `SafeHardware`, and a scalar
  `asCOMP = 3` an `AttributeError`. The docstring of `hardware_from_asc`
  (`asc.py:155-163`) gives `ValueError`. The module's rule
  (`asc.py:146-148`): a value of the file is a `ValueError`, not a
  `TypeError`.
- **The fix:** `hardware_name` raises `ValueError` that names the field for a
  `tName` that is not a text and for an `asCOMP` that is not a group of
  fields.
- **The test:**
  `test_a_component_name_that_is_not_a_text_is_refused_and_the_error_names_it`
  (`tests/test_asc.py`), with both files.

## 4. Track D: the documents, the release notes, and duplication

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| D1 | `docs/stale-text` | 3.2 | S | after C3, C8, D5, T2 |
| D2 | `docs/decoding-members-in-documents` | 3.3 | S | after C11 |
| D3 | `refactor/one-grad-columns` | 4 (`_GRAD_COLUMNS`) | S | after C12 |
| D4 | `refactor/remove-read-spec` | 4 (`_read_spec`) | S | Q9; after C7, C9, T7 |
| D5 | `refactor/one-gradient-ends` | 4 (`_assemble`) | S | after D4 |
| D6 | `refactor/plugin-one-limit-check` | 4 (the setting) | S | after C12 |
| D7 | `test/no-duplicate-tests` | 4 (the tests) | S | Q10; after D1, D4 |
| D8 | `docs/release-notes-gaps` | 7.2 | S-M | after D2 |

### D1. Stale text (3.2)

- `model.py:401-402`: "Task R16 adds the records ..." R16 is done (#128). The
  text gives the lasting fact: the records of the mechanisms of the session
  are on the decoding (`rotation_record`, `soft_delay_record`,
  `fov_record`).
- `spec.py:73-74`: "Today's rule names of the strict reader are kept ...".
  The strict reader is gone. The text gives the lasting fact (a code is a
  stable name, `errors`), or the sentence goes.
- `sampling.py:444`: a gap piece is "at most one raster time" long. It can
  be `dt + TIME_TOLERANCE`; the code uses `gaps.max_length_s` (`:460`,
  `:483`). The text says so.
- `tests/test_pns_levels.py:446`: "(the new test below checks the snap)". The
  text names the test,
  `test_bin_samples_for_gives_the_whole_samples_of_a_bin_s_on_the_raster`.
- No check can keep these lines right. The PR gives each line.

### D2. A document reads a member that the protocol does not have (3.3)

- **Today:** `docs/usage.md:1403-1404` reads `snap.decoding.blocks`, which
  is not a member of the protocol `synth.Decoding` (`decoding.py:64`).
  `docs/migration.md:257-258` reads `snap.data.blocks`.
- **The check (first commit):**
  `test_each_member_of_a_decoding_that_a_document_reads_is_in_the_protocol`
  (`tests/test_documents.py`): each `snap.decoding.<name>` of the documents
  is a member of `synth.Decoding`. It fails on `main` with
  `docs/usage.md:1403`.
- **The fix:** `snap.data.blocks`, as in `docs/migration.md`.

### D3. One `_GRAD_COLUMNS` (4)

`synth/decoding.py:56` defines `_GRAD_COLUMNS` again; `seq_utils.py:19` has
it, and `decoding.py` already imports from `seq_utils`. The fix imports it.
A refactor (rule 2): the tests of `gradients_at` cover it.

### D4. `spec._read_spec` (4)

- **Today:** `_read_spec` (`spec.py:527-537`) has no caller in `src/` or in
  the plugin. The tests call it at `tests/test_seqfile.py:684`, `:696` and
  `:1771`, to compare it with `read_seqfile`, and `:2543` takes its
  `__code__.co_filename` for the file of `spec`. `spec.py:8`,
  `errors.py:12-14`, `docs/implementation.md:1046` and `CHANGELOG.md:510-513`
  name it. The sentence of `CHANGELOG.md:510-513` does not read
  ("`spec.read_spec` is private, `spec._read_spec`, and `spec.read_spec`
  raises `AttributeError`").
- **The fix (Q9 (a)):** `_read_spec` goes. `_read_written` keeps the reading
  of `read_seqfile`. The tests at 684 and 696 lose the comparison, and the
  test at 696 keeps the check that `spec` has no `read_spec`. The test at
  1771 keeps `read_seqfile` and `load`. The test at 2543 takes the file
  from another function of `spec`. The text of each document names
  `read_seqfile` as the one way; the sentence of `CHANGELOG.md` is
  corrected. `TESTS.md` (6536, 6545-6549, 7027) follows.
- A refactor of private code (rule 2): the tests of `read_seqfile` cover it.

### D5. One computation of the ends of a 1.4 gradient (4)

`_assemble` (`spec.py:1882-1890`) computes the `first` and `last` of each
arbitrary gradient of a 1.4 file again, after `_gradient_ends`
(`spec.py:1520-1554`) computed them. In a file with no violation the two are
equal: every gradient that `_gradient_ends` gives NaN is a
`layer1.gradient-ends` violation. The fix keeps the result of
`_gradient_ends` on the `_File` and uses it. A refactor (rule 2): the tests
of `layer1.gradient-ends` and of the 1.4 fixtures cover it.

### D6. One check of the setting in the plugin (4)

`CppSiemens.__post_init__` (plugin `interpreter.py:176-182`) checks
`max_shape_samples` with the code of `_max_shape_samples` of the plugin's
`__init__.py` (`:426-436`), with the same messages. `interpreter.py` imports
`pulseq_cpp_siemens`, so it calls `cs._max_shape_samples`. The wheel's own
copy stays: the wheel does not import pulseq-analysis. A refactor (rule 2):
`check_shape_limit(CppSiemens)` and
`test_max_shape_samples_of_load_is_an_int_above_0_or_none` cover it.

### D7. Duplicate tests (4)

- `tests/test_seqfile.py:2968`
  (`test_oracle_unknown_extension_is_skipped_and_a_required_one_is_listed`)
  repeats the first two asserts of `:2208`: remove them from `:2968`.
- `tests/test_seqfile.py:679` and `:687` both assert
  `_read_spec(path) == read_seqfile(path)`: D4 removes both.
- Plugin `test_interpreter.py:328`
  (`test_a_binary_file_and_a_folder_are_not_supported`) is covered by `:338`
  (`test_both_interpreters_give_one_message_for_a_file_outside_the_scope`):
  remove it.
- `tests/test_session.py:47` (`_matrix`) and plugin `test_api.py:446`
  (`rotation_matrix`) are the same helper. Q10 (a): both stay, each with a
  comment that names the other and the reason (the wheel tests run without
  the root tests).
- `tests/test_pns_levels.py:403-420` (`_reference_runs`) and `:883-897`
  compute the same reference of the runs: the test at 883 calls
  `_reference_runs(total, _LIMIT, dt)`.
- A test that is removed loses its entry of `TESTS.md`.

### D8. The gaps of the release notes (7.2)

- **The gaps:**
  - `CHANGELOG.md:9-12` says that an old name raises `ImportError`,
    `AttributeError` or `TypeError`. The rc6 line
    `from pulseq_analysis.analyses import registry` raises nothing: it binds
    the submodule, and the call fails later. `docs/migration.md:133-138`
    says so; the entry "Unreleased" does not.
  - `CHANGELOG.md:636-640` says that the table of the defaults of
    `docs/usage.md` (251-262) gives each default of `load`, of the reads and
    of the analyses. It has no row for the settings of the interpreters:
    `max_shape_samples` of `Spec`, and `oversampling`, `rotation` and
    `max_shape_samples` of `CppSiemens`.
  - `CHANGELOG.md:375-376` names `gradient_offsets` only;
    `gradient_points` changed its argument too (`docs/migration.md:334`).
  - New public names that the changelog does not name, although
    `docs/migration.md:12` says that it lists every change:
    `spec.RANGE_TOLERANCE` and `MAX_LOCATIONS`, `synth.decoding.Points`,
    `model.TABLE_DTYPES`, `decompress_shape`, `Rasters` and `Shape`,
    `from_pypulseq.SOURCE`, `interpreters.GROUP`, `seqfile.Interpreter`
    and `interpreters.Interpreter`.
- **The checks (first commit, `tests/test_documents.py`):**
  - `test_each_name_of_a_public_module_is_in_the_changelog`: each name of
    the `__all__` of each public module is in a code span of `CHANGELOG.md`.
    On `ef891d5`, 18 names fail: those above, and older names that no entry
    names (`grad_spectrum.FFT_WINDOW_S`, `FREQUENCY_OVERSAMPLING`,
    `MAX_FREQUENCY_HZ`, `pns_levels.PEAK_TOLERANCE`, and the
    `registry` names `GRADIENT_BLOCKS`, `GRADIENT_SPECTRUM`, `GROUP` and
    `SEQ_INDEX`).
  - `test_the_defaults_table_of_usage_gives_each_default_and_its_field_on_the_result`
    also reads the dataclass fields of `Spec`, and those of `CppSiemens`
    from the plugin's source with `ast`, as the check of the codes of
    `cpp-siemens` does. Each row of an interpreter's setting names
    `SequenceData.interpreter` as the field that records it.
- **The fix:** the entry "Unreleased" gets each gap: the exception of
  `registry`, `gradient_points`, the new names, and the older names in one
  line. `docs/usage.md` gets the four rows.

## 5. Track T: the tests

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| T1 | `test/end-of-sequence-step` | 5.1, 5.2 | M | — |
| T2 | `test/peak-tolerance` | 5.3 | S | after C11 |
| T3 | `test/model-equality-of-each-field` | 5.4 | S | after C4 |
| T4 | `test/check-shape-limit-breakers` | 5.5 | S | after C1 |
| T5 | `test/read-pypulseq-not-supported` | 5.6 | S | — |
| T6 | `test/interpreter-names-lazy-and-sorted` | 5.7 (first item) | S | after T4 |
| T7 | `test/signature-after-a-comment` | 5.7 (second item) | S | after C9 |

### T1. The step at the end of the sequence (5.1, 5.2)

- **Today (5.1):** the rule `step_hi = min(hi, end_s - TIME_TOLERANCE)` of
  `_evaluate_axis` (`grad_peaks.py:916`) has no guard.
  `check_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end`
  (`test_grad_peaks.py:419-443`, also called by the plugin's
  `test_measurements_in_pulseq_analysis.py:133`) uses the range
  `(0, end_s)`, which is the whole file and takes another path
  (`grad_peaks.py:1030`), and a range that leaves the step out through `hi`
  alone.
- **Today (5.2):**
  - The 20 values of `k` of
    `test_a_gradient_that_ends_at_the_end_of_the_sequence_has_no_step`
    (`test_grad_peaks.py:389-411`) all give a last time exactly at `end_s`
    through `spec`. `TESTS.md` 2.6 (2563, 2576-2578) says some give one ulp
    before it.
  - The plugin's `early` of 0.5 and 0.9 of `TIME_TOLERANCE` are lost: the
    reader keeps the times of an extended trapezoid in whole us, so both
    play as `early = 0`. `TESTS.md` 3.10 (11459-11466) says that only the
    tolerance rule leaves them out.
  - So the rule `lt[-1] < index.end_s - TIME_TOLERANCE`
    (`grad_peaks.py:425`) has no guard.
- **The fix:**
  - The helper also compares the range `(1e-4, end_s)` with the oracle: a
    start above 0, which is not the whole-file path, that ends at `end_s`.
  - A new plugin test with times that the file keeps:
    `test_the_step_after_the_last_point_of_an_arbitrary_gradient_is_counted_only_beyond_the_tolerance_before_the_end`
    (plugin `test_measurements_in_pulseq_analysis.py`). One block of 100 us
    with an arbitrary gradient of 10 samples whose last sample is not 0, on
    the gradient raster `(100e-6 - early) / 10`. Measured on `ef891d5`: the
    played early (from `played_gradients` and `sequence_index`) is 5.0e-10
    and 9.0e-10 s for an `early` of 0.5 and 0.9 of `TIME_TOLERANCE`, and the
    step is not counted; at 2 `TIME_TOLERANCE` it is counted (a slew of
    1.0e11 Hz/m/s). The test asserts the played early of each case, then
    the slew of the whole file, of the ranges of the helper, and of the
    oracle. `spec` rejects this raster (it does not divide the block
    raster), so the test is the plugin's.
  - The plugin's test of the extended trapezoid keeps the `early` of one
    raster time, and loses 0.5 and 0.9 of `TIME_TOLERANCE`.
  - `TESTS.md` 2.6 and 3.10 say what each test covers.
- **The mutations:**
  - `step_hi = min(hi, end_s)` (`grad_peaks.py:916`). It survives the root
    (354 passed) and the plugin (240 passed) on `ef891d5`. With the range
    `(1e-4, end_s)`, the plugin's
    `test_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end`
    fails: `cpp-siemens` gives a slew of 3.19e9 Hz/m/s, the oracle 1e9
    (measured for this plan). The root's call through `spec` does not catch
    it: there the step is at `end_s` exactly, and `t < end_s` leaves it out.
  - `lt[-1] < index.end_s` (`grad_peaks.py:425`). The new plugin test
    catches it: the slew of the cases of 0.5 and 0.9 of `TIME_TOLERANCE`
    becomes 1.0e11 Hz/m/s (measured for this plan).

### T2. A guard of `PEAK_TOLERANCE` (5.3)

- **Today:** each expected peak time comes from the package's own
  `PEAK_TOLERANCE` (`test_pns_levels.py:157-160`, `test_safe_oracle.py:213`).
  With `PEAK_TOLERANCE` 0.3 or 0.0, the root and the plugin tests pass. This
  is the case of `TOLERANCE_NS` in the review of 2026-10-13 (5.3d).
- **The fix:**
  - `test_peak_tolerance_is_one_millionth_of_the_peak`
    (`tests/test_pns_levels.py`): `PEAK_TOLERANCE == 1e-6`, as
    `MAX_LOCATIONS == 20` is checked (`test_seqfile.py:478`).
  - `test_the_peak_time_is_the_first_sample_within_peak_tolerance_of_the_peak`:
    a file in `tmp_path` with two equal trapezoids, far enough apart that
    the filter of the first has decayed, the second with its amplitude
    times `1 + 5e-7` in one case and `1 + 5e-6` in the other (written with
    17 digits). The expected peak time is written as a number: in the first
    trapezoid for the first case, in the second for the other.
- **The mutations:** `PEAK_TOLERANCE = 0.3` and `PEAK_TOLERANCE = 0.0`.

### T3. The equality of models sees each field (5.4)

- **Today:** `test_models_are_equal_by_value_and_not_hashable`
  (`test_seqfile.py:2845`) changes only an RF amplitude. Leaving
  `interpreter`, `records` or `origin` out of `_model_eq`
  (`model.py:200-207`), or comparing the keys of a mapping sorted
  (`model.py:185`), survives the root tests. `records` with `origin`
  survives the plugin's too. `load(data, interpreter)` relies on this
  equality.
- **The fix:** `test_a_model_differs_from_itself_with_any_field_replaced`
  (`tests/test_seqfile.py`): for each compared field of `SequenceData`,
  `dataclasses.replace` of the model with another value differs from it:
  `interpreter=Spec(max_shape_samples=None)`, `records=()`,
  `origin="pypulseq"`, the definitions with their keys in another order,
  and a changed value of each other field. `reading` replaced gives an
  equal model.
- **The mutations:** `interpreter` left out of `_model_eq`, and
  `sorted(a) == sorted(b)` in place of `list(a) == list(b)`.

### T4. The checks of `check_shape_limit` that no test breaks (5.5)

- **Today:** the checks of the values `True` and `1.5`
  (`conformance.py:121-122`) and of the `str` of a setting `None`
  (`:125-127`) can be removed, and no test fails (565 passed). None of the
  eight classes of
  `test_the_check_of_the_shape_limit_fails_for_a_plugin_that_does_not_follow_it`
  (`test_interpreters.py:248-271`) breaks them.
- **The fix:** three more classes in its list: one that accepts `True`, one
  that accepts `1.5`, and one whose `str` of `max_shape_samples=None` does
  not give it.
- **The mutations:** each of the three checks deleted.

### T5. `SOURCE` in a `NotSupported` of `read_pypulseq` (5.6)

- **Today:** `from_pypulseq.py:71-72` replaces the path with `SOURCE` in a
  `NotSupported`. With #198 this is reachable
  (`read_pypulseq(seq, Spec(max_shape_samples=3))`). A bare `raise` in its
  place survives the root tests.
- **The fix:**
  `test_a_shape_over_the_limit_of_read_pypulseq_names_the_sequence_not_the_temporary_file`
  (`tests/test_from_pypulseq.py`, beside `check_a_rejection`): the message
  has `SOURCE` and not the temporary path, and the error has no cause or
  context.
- **The mutation:** `raise` in place of the `raise NotSupported(...)` of
  `from_pypulseq.py:72`.

### T6. `interpreter_names` imports no plugin and sorts the names (5.7)

- **Today:** nothing checks that `interpreter_names()`
  (`interpreters.py:162-165`) imports no plugin, or that it sorts the names
  (`test_interpreters.py:167`, `:183` have one plugin at most). An eager
  import survives.
- **The fix:** `test_interpreter_names_imports_no_plugin_and_sorts_the_names`
  (`tests/test_interpreters.py`): two entry points, `zeta` and `alpha`,
  whose modules do not exist; `interpreter_names()` is
  `("spec", "alpha", "zeta")`, with no `ImportError`.
- **The mutations:** `list(...)` in place of `sorted(...)`, and a load of
  each entry point.

### T7. A comment after the header of `[SIGNATURE]` (5.7)

- **Today:**
  `test_comments_and_blank_lines_are_skipped_after_the_header_of_any_section`
  (`test_seqfile.py:873`) compares with `same_values`, which leaves out the
  signature (`test_seqfile.py:235-240`), so its `[SIGNATURE]` case checks
  only that the file reads.
- **The fix:** the `[SIGNATURE]` case also asserts that the signature equals
  the signature of the file without the comment.
- **The mutation:** `_read_signature` gives None when a comment follows the
  header.

## 6. Track R: release readiness

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| R1 | `chore/lock-check` | 7.1 (the locks) | S | — |
| R2 | `test/release-versions` | 7.1 (the versions) | S | after D8 |

### R1. The locks match `pyproject.toml` (7.1)

- **Today:** every sync of `scripts/check` (lines 61, 78, 114) and of
  `matlab-oracle.yml` (110, 115) uses `--frozen`, which does not check the
  lock. The locks are up to date on `ef891d5`: `uv lock --check` of both
  projects passes, also with `--offline` (run for this plan).
- **Why it matters for the release:** the release changes the version of the
  root from `0.1.0rc6` to `0.1.0rc7`. The plugin's `uv.lock` records
  pulseq-analysis as `0.1.0rc6` from the path `../../` (lines 602-604), so
  both locks change at the release, and `--frozen` does not see a lock that
  was not.
- **The fix:** the full path of `scripts/check` runs `uv lock --check` for
  the root and for `packages/pulseq-cpp-siemens`, before the syncs. The
  docs-only path does not: it changes no `pyproject.toml`. `TESTS.md`
  section 1 has the check.
- **The PR (rule 5):** the check fails with the version of the root changed
  to `0.1.0rc7` and no new lock, and passes without the edit.

### R2. Both distributions have the version of the release (7.1)

- **Today:** `test_the_documents_give_the_version_of_pulseq_cpp_siemens`
  (`test_documents.py:555`) accepts the root at the last release or the
  next (`:571`), and requires an entry "Unreleased". At the release, the
  entry becomes the version, so the test fails on the release PR as it is.
- **The fix:** the test reads the newest entry of `CHANGELOG.md`.
  - "Unreleased": as today.
  - A version (`## 0.1.0rc7 (<date>)`): the root's and the plugin's
    `pyproject.toml` have that version, and it is the "to" of the title of
    `docs/migration.md`. R1 checks the locks.
- **The PR (rule 3):** the test fails on the edit that renames
  "Unreleased" to `0.1.0rc7` with the root at `0.1.0rc6`, and passes on
  `main`.

## 7. Findings that need no code fix

No finding of the review is wrong or already fixed on `ef891d5`. The check
found these details:

- **1.1.2:** the review called the case of times that are not in order
  plausible. It is reproduced. The user chose to record it, not to fix it
  (Q2 (b)): C2 writes it in the plugin's record and in `TODO.md`.
- **1.1.3:** "With a delay of 5 in both rows, it loads": the script gives
  the delay 5 to the `[GRADIENTS]` row only; the `[TRAP]` row has 0. The
  finding holds.
- **1.2.2:** the docstring of `SeqFileError` covers `cpp-siemens` too, which
  keeps its cases in play order (task C7).
- **1.3.3:** the review asked whether the plugin has the same cut. It does,
  twice (task C12).
- **4, the rotation matrix:** the two helpers are on the two sides of the
  wheel boundary (Q10).
- **7.2:** the lines of `CHANGELOG.md` are 375-376 (not 370-371) and 636-640
  (not 625-628). The finding holds.
- **D-a, `spec` and `synth`:** they make no array whose size is a value of a
  shape. `decode_rf` (`events.py:215-256`) keeps a pulse of points as its
  points (`t` is the time shape times the raster), and the cells of a
  regular time shape as the samples of the magnitude. `RfEvent.signal(times)`
  (`events.py:156-176`) gives one value for each time of the caller
  (`np.interp`, or the cell of each time). The gradients have the samples of
  their shapes (`events.py:258-300`). So the RF path needs no limit in
  `spec`, and C1 adds none.
- **The scanner's own resampling:** `applyRfPhaseModulation`
  (cpp:2686-2810) resamples an RF pulse to `nOrigN * rfDwell / raster`
  samples. The binding does not call it, so the package does not allocate
  there.

## 8. Order, and the files that tasks share

- **The shared files.** `TESTS.md` and `CHANGELOG.md` change in almost every
  task. Their changes are additions to different sections, so a PR rebases
  on `main` after the one before it merges. These files are also changed by
  more than one task:

  | File | Tasks |
  |---|---|
  | `seqfile/spec.py` | C4, C9, D4, D5, D1 |
  | `seqfile/errors.py` | C1, C7, D4 |
  | `seqfile/model.py` | C8, D1 |
  | `synth/sampling.py` | C3, D1 |
  | `synth/decoding.py` | C12, D3 |
  | `tests/test_seqfile.py` | C4, T3, C8, C9, T7, D4, D7 |
  | `tests/test_interpreters.py` | C1, T4, T6 |
  | `tests/test_pns_levels.py` | C11, T2, D1, D7 |
  | `tests/test_session.py` | C10, D7 |
  | `tests/test_documents.py` | D2, D8, R2 |
  | `docs/usage.md` | C1, C9, C11, D2, D8 |
  | `docs/specification.md` | C1, C9 |
  | plugin `__init__.py` | C1, C6, C12 |
  | plugin `_checks.py` | C1, C5 |
  | plugin `interpreter.py` | C2, C12, D6 |
  | plugin `docs/specification.md` | C1, C2, C5 |
  | plugin `tests/test_api.py` | C1, C6, C12, D7 |
  | plugin `tests/test_interpreter.py` | C1, D7 |

  Each row is done in the order of its tasks.
- **The order of the waves:**

  ```
  Wave 1:  C1  ||  C3  ||  C4  ||  T1
  Wave 2:  C2  ||  T3  ||  T5  ||  R1
  Wave 3:  C5  ||  C6  ||  C8  ||  T4
  Wave 4:  C7  ||  C9  ||  C10 ||  C13
  Wave 5:  C11 ||  C12 ||  T6  ||  T7
  Wave 6:  T2  ||  C14 ||  D2  ||  D4
  Wave 7:  D3  ||  D5  ||  D6  ||  D8
  Wave 8:  D1  ||  R2
  Wave 9:  D7
  Then:    the PR that closes this plan (section 10)
  Last:    the release 0.1.0rc7 (section 11)
  ```

  - A wave starts when each task before it, of the files it shares, has
    merged.
  - At most four tasks run at a time, so that each review stays small.
- **Value first.** In the order of value: C1 (an allocation without bound
  from a file of 321 bytes), C2, C3 and C4 (wrong values), T1 (the rule of
  the step at the end has no guard), then the medium findings (T2 to T5,
  R1, D8). Within a wave, these go first.
- **What changed with the answers.** C7 is now a documentation task that
  changes only `errors.py` (Q5 (b)), so C9, D2 and D4 no longer wait for it
  through `spec.py`, `tests/test_seqfile.py` or `docs/usage.md`; D4 still
  waits for it through `errors.py`. C9 now changes `docs/usage.md:1050`
  (Q6 (b)), so C11 waits for C9. C8 changes `tests/test_seqfile.py`, so it
  comes after T3 and before C9. C2 is smaller (Q2 (b)) and adds the item of
  `TODO.md`.

## 9. Decisions

### 9.1 Decided by the user (2026-10-21)

**D-a. The limit of the samples that a reader resamples (C1).**
1.1.1 is fixed by widening the convention `max_shape_samples`: the same
setting limits every array of samples that a reader makes from a shape, the
samples that a shape declares and the samples that the reader resamples (the
RF cells of `cpp-siemens`, `int(0.5 + t[-1])`). Over the limit is
`NotSupported`, before the allocation. The `Plugin` docstring of
`seqfile/interpreters.py`, `conformance.check_shape_limit` (a check with a
file whose RF time shape ends far out and whose shapes are small), the
plugin's `load`, and the documents follow. Section 7 gives the check of
`spec` and `synth`, which make no such array.

**D-b. Every finding before the release.** Every finding of the review goes
into this plan, the low ones too, before the release `0.1.0rc7`. The release
(its own PR in the form of #86, "docs: release 0.1.0rc6", then a tag that the
user approves) comes after the plan (section 11).

### 9.2 The questions

Each gives its evidence and a recommendation. The user answered each on
2026-10-21; each answer is recorded here.

**Q1. What `check_shape_limit` checks of the RF cells (C1).**
Answer (2026-10-21): (a), a read or a correct `NotSupported` at 2^20, and a
read at 2^21 and with None.
- **The evidence:**
  - D-a asks for a check with a file whose RF time shape ends far out and
    whose shapes are small.
  - `spec` reads such a file under any limit, with arrays of 2 samples
    (section 7). So the check cannot ask every interpreter to refuse it.
  - `cpp-siemens` makes the cells in `decodeBlock` (cpp:2031-2035), which
    `read_seqfile` runs on each block (plugin `interpreter.py:349`,
    `first_rejected_block`). Its vectors are C++ memory: `tracemalloc` does
    not see them. So the check cannot see whether a plugin resampled.
- **The options:**
  - (a) The check takes a read or a `NotSupported` with the limit 2^20.
    A `NotSupported` must give the path, the number of cells (2^21) and the
    limit, and name the setting. With the limit 2^21 and with None, the file
    must read. It catches a wrong message and a refusal at or above the
    number of cells. It does not catch a plugin that resamples and ignores
    the limit; the plugin's own tests (C1) guard `cpp-siemens`. It follows
    D-a with no change to `spec` or to the protocol. Recommended.
  - (b) The protocol gets a class attribute (for example
    `resamples_rf: ClassVar[bool]`) that says whether the reader resamples
    RF, and the check requires `NotSupported` when it is True. The check then
    catches a plugin that says so and ignores the limit. A change of
    `Plugin` and of `PROTOCOL` before the first release of protocol 1, as
    for `gradient_variants`.
  - (c) Every interpreter, `spec` too, refuses an RF time shape whose last
    time is more than `max_shape_samples` RF rasters. One verdict for each
    file, and a check that catches any plugin. `spec` then refuses a file
    that it reads with no large array; at the default and a raster of 1 us
    that is a pulse of more than 134 s, which no writer makes. It goes
    beyond D-a, which limits the arrays that a reader makes.

**Q2. The time shapes that C2 covers.**
Answer (2026-10-21): (b), only a first time below 0. The case of times out
of order stays: the measurements of `cpp-siemens` differ from the reader
there. C2 records it in the plugin's record and in `TODO.md`, with the
reproduced numbers, and adds no test that asserts the wrong value.
- **The evidence:**
  - The C++ reader reads a time shape in any order. `gradientsAt` does a
    binary search (cpp:3638-3649) and ends the event at its last time
    (cpp:3621).
  - A first time below 0 is reproduced by the review; times 0, 20, 10 and
    30 us by this plan (section 3, C2): both give values that the reader
    does not play.
  - `spec` rejects both (`shape.time-order`, D3.9).
  - MATLAB Pulseq (`makeExtendedTrapezoid.m:51`) and pypulseq
    (`make_extended_trapezoid.py:87-88`) refuse times that are not
    ascending and distinct, so neither writes such a file from that
    function. A file by hand or by another writer can have one.
  - `cpp-siemens` reproduces the C++ reader (the user's rule for the
    plugin).
- **The options:**
  - (a) Every time shape whose times are not in order, or whose first time
    is below 0: the points of `gradientsAt` itself. Recommended: one rule,
    and the measurements follow the reader on every file that it reads.
  - (b) Only a first time below 0. The case of times out of order stays a
    known difference, written in the plugin's record.

**Q3. How the check of `ub.gradient-shape-0` tells which row the event holds
(C5).**
Answer (2026-10-21): (a), the order in which `load` reads the sections.
- **The evidence:**
  - `load` reads `[GRADIENTS]` (cpp:1060-1103), then `[TRAP]`
    (cpp:1108-1124). Each `[TRAP]` row replaces the event of its ID, and a
    row that `sscanf` does not read makes `load` reject the file
    (cpp:1117-1120).
  - The binding reads both sections again with the reader's own `getline`,
    the formats of `load` and the index that `load` built
    (`reader.cpp:243-301`). So a row of `traps` is a row that `load`
    applied.
  - The check uses only the amplitude and the delay
    (`_checks.py:428-452`), and counts the event as the `[GRADIENTS]` row
    where both rows have the same ones.
- **The options:**
  - (a) The order of `load`: the event is the `[GRADIENTS]` row of shape 0
    when no `[TRAP]` row has its ID. It is exact, and the code is shorter.
    Recommended.
  - (b) All five fields: the binding gives the ramp and flat times of each
    `[TRAP]` row too (`TrapRow`, `gradient_rows`), and the event is the
    `[TRAP]` row when its five fields are those of the row. It also checks
    that the binding read the row that `load` read. It changes the C++
    binding, and so the wheels.

**Q4. The soft delays of a `Sequence` (C6).**
Answer (2026-10-21): (a), copies.
- **The evidence:** `block_rotations` and `block_label_sets` give copies of
  their kept arrays (`__init__.py:295-305`, `:319-328`). The decoding reads
  `block_soft_delays` once for each decoding (`interpreter.py:735`). The
  arrays have one entry for each block with a soft delay.
- **The options:**
  - (a) Copies, as the two others give. One rule for the three; the copy is
    small. Recommended.
  - (b) Read-only arrays, and no copy. For one rule, the two others become
    read-only too, which breaks a caller that writes to its copy.

**Q5. The kept violations of a code (C7).**
Answer (2026-10-21): (b), the docstring says what each interpreter keeps:
`spec` the first `MAX_LOCATIONS` that it finds for each code, in the order
of its checks, sorted by line; `cpp-siemens` its cases in play order. C7 is
a documentation task.
- **The evidence:**
  - `errors.py:51-52` says "in the order of the file".
    `docs/usage.md:1009` and `docs/findings-for-pulseq-checks.md:354` say
    "at most `MAX_LOCATIONS` for each code".
  - `spec` keeps the first that it checks (shapes before tables), then
    sorts the kept by line (`spec.py:490-493`).
  - `cpp-siemens` keeps its cases in play order (plugin `interpreter.py:42`,
    `:360-368`).
  - A reader of the error (pulseq-checks) sees the earliest lines of the
    file only with (a).
- **The options:**
  - (a) `spec` keeps, for each code, the `MAX_LOCATIONS` violations of the
    lowest lines. Each call of `_Report.rows` gives its rows in the order of
    the file, so at most `MAX_LOCATIONS` of each call are candidates, and
    the memory stays that of `MAX_LOCATIONS` for each code. The docstring
    gives the order of `spec` and that of `cpp-siemens` (play order).
    Recommended.
  - (b) The docstring says what `spec` keeps: the first that it finds, in
    the order of its checks, sorted by line.

**Q6. A repeated `Type` or `Hash` of `[SIGNATURE]` (C9).**
Answer (2026-10-21): (b), the last wins, as D2.6 does.
- **The evidence:**
  - The specification: the section "must contain two following fields"
    (spec:223), the format of `[DEFINITIONS]`. It says nothing of a repeat.
  - The C++ reader: a map, the last line wins (cpp:1606-1630).
  - MATLAB Pulseq: `readDefinitions`, a `containers.Map`, the last wins
    (`read.m:85-92`, `read.m:452-469`).
  - pypulseq: `__read_definitions`, a dict, the last wins
    (`read_seq.py:94-102`, `read_seq.py:466-473`).
  - The writers write one of each (`write.m:282-290`,
    `write_seq.py:265-276`).
  - `spec` reads a repeated definition, the last wins (D2.6, the user's
    choice). Its rule of choices: it rejects a file only where no current
    writer writes such a file.
- **The options:**
  - (a) Reject a repeated `Type` or `Hash` as `signature.invalid`, with the
    key and its lines. No writer writes one, so the rule of choices allows
    it; the rule is then partly a choice.
  - (b) Read it as D2.6 does: the last wins. The text of the rule
    (`spec.py:369`) and `docs/specification.md:239` say "no `Type` or no
    `Hash`, or one that is not one value", and D2.6 names the signature. It
    is what every reader does. Recommended.

**Q7. A `bin_s` longer than the sequence (C11).**
Answer (2026-10-21): (a), a bin is at most the whole sequence. The user
asked whether the rule depends on the interpreter. It does not: the cap is
at most the `num_samples` of the snapshot, so it follows the reading of the
duration of each interpreter, and the rule is the same for every
interpreter (`bin_s` is a parameter of the analysis, not a reading of the
file).
- **The evidence:**
  - `bin_s` is a parameter of the method with a default (`BIN_S`, 5 ms).
    A caller does not know the duration before the call.
  - Today a `bin_s` of 1000 s on a file of 1 ms gives
    `bin_samples = 100 000 000` and one bin, and `to_series` makes the
    series. `1e295` gives one bin that `to_series` refuses, and `1e304`
    raises `OverflowError` (run again on `ef891d5`).
- **The options:**
  - (a) A bin is at most the whole sequence: `wanted` is at most
    `max(num_samples, 1)`, compared in float before `round`. Every finite
    `bin_s` then gives a result that `to_series` makes. `PnsLevels.bin_s`
    keeps the `bin_s` of the call; `bin_samples` and the `coord_step` of the
    series change for a `bin_s` longer than the file (100 in place of
    100 000 000 in the example). Recommended.
  - (b) A `bin_s` whose bin is longer than the sequence raises
    `ValueError`. The check needs the snapshot, so it comes after the
    checks of the arguments, and a caller with one `bin_s` for many files
    gets an error on the short ones.

**Q8. The signs that `SafeAxis` refuses (C13).**
Answer (2026-10-21): (b), `g_scale <= 0` and a negative `a1`, `a2` or `a3`.
- **The evidence:**
  - The SAFE port of pypulseq says that it is a direct translation of the
    original (`safe_pns_prediction.py:1-3`). Its `safe_hw_check`
    (`safe_pns_prediction.py:193-215`) checks only that each field is there
    and that `a1 + a2 + a3` is within 0.001 of 1. So the original allows
    any sign. The original MATLAB code is not in the repository.
  - The model (`safe_pns_prediction.py:245-249`, `:388-400`): each `a` scales
    one filtered term, `g_scale` scales the axis, and the axis is divided by
    `stim_limit`. `alpha = dt / (tau + dt)`, so a `tau` between `-dt` and 0
    gives an unstable filter.
  - `SafeAxis` already refuses a `stim_limit` that is not above 0, which
    SAFE does not.
  - The fields of a Siemens `.asc` file (`flGScaleFactor`, `flGSWDA`,
    `flGSWDTau`) are positive.
  - A negative `g_scale` or `a` makes values of the axis 0 or less, and the
    axis peak 0 (C13).
- **The options:**
  - (a) Refuse `g_scale <= 0` only, as the review says.
  - (b) Refuse `g_scale <= 0` and a negative `a1`, `a2` or `a3` (0 turns a
    term off). It covers each sign that gives an axis of values 0 or less,
    and keeps `tau` as SAFE allows it. Recommended.
  - (c) Also refuse a negative `tau1`, `tau2` or `tau3`. Each field of a
    physical sign is then checked. `stim_thresh` is not used by the model
    (`pns_levels.py:91-94`), so it is not refused in any option.

**Q9. `spec._read_spec` (D4).**
Answer (2026-10-21): (a), delete it.
- **The evidence:**
  - No caller in `src/` or in the plugin. Three tests compare it with
    `read_seqfile`, and one takes its file name (D4).
  - The user's rule of 2026-10-14 (A6 of the plan of the fixes of the
    review of 2026-10-13): one way to make each object; `read_seqfile(path)`
    is the one way to read a file through `spec`, and `spec.read_spec`
    became private.
  - `_read_written` already gives the reading for `read_seqfile`.
- **The options:**
  - (a) Delete it (task D4). Recommended.
  - (b) Keep it, as a private name for the tests; remove only the duplicate
    test (D7).

**Q10. The rotation matrix of the root and of the wheel tests (D7).**
Answer (2026-10-21): (a), keep both, each with a comment that names the
other and the reason.
- **The evidence:**
  - `tests/test_session.py:47` (`_matrix`) and plugin `test_api.py:446`
    (`rotation_matrix`) are the same function.
  - `test_api.py` is a wheel test: it is not in `conftest.ANALYSIS_TESTS`,
    and the root tests are put on `sys.path` only when pulseq-analysis is
    there (plugin `conftest.py:22-25`). cibuildwheel runs the plugin's tests
    folder (plugin `pyproject.toml:86`).
  - `tests/test_session.py` imports pulseq-analysis.
- **The options:**
  - (a) Keep both, each with a comment that names the other and the reason
    (the wheel tests run without the root tests). Recommended: it keeps the
    wheel tests free of the root.
  - (b) One helper in a root module that imports only numpy (for example
    `tests/rotation.py`), which the plugin's `canonical.py` imports by path.
    One copy, and the wheel tests then read a file of the root tests.

## 10. When this plan is done

- Delete this file in the last PR of the plan (as #197 did). Its lasting
  content is in the documents of each task, in `CHANGELOG.md`, and in
  `docs/migration.md`.
- Add a section "8. Status after PRs #<first> to #<last>" to the review
  (its section 7 is the release): for each finding, the task, the PR and
  the fix, with the findings of section 7 of this plan.
- Remove the line of this plan from `README.md`, and say in the line of the
  review that it has the status of its fixes, with the PRs.
- Replace each citation of this plan with the lasting reason or decision and
  its source (the user and the date, or the finding of the review).
  `test_each_plan_that_a_file_cites_exists` (`tests/test_documents.py`)
  fails while a file outside `docs/plans/` and `docs/reviews/` cites a plan
  that does not exist.

## 11. The release 0.1.0rc7

The release comes after the PR that closes this plan (D-b). It is its own PR,
in the form of #86 ("docs: release 0.1.0rc6"):

- `CHANGELOG.md`: the entry "Unreleased" becomes `0.1.0rc7` with its date.
- `README.md` gives the release and installs `v0.1.0rc7`.
- `pyproject.toml` of the root is `0.1.0rc7`, and both locks follow (R1
  checks them; R2 checks the versions).
- The documents are corrected against the code, and the review ends with
  its status.

Then a tag `v0.1.0rc7`, which the user approves.
