# Implementation plan: the remaining findings of the review of 2026-10-13

Status: written on 2026-10-14. The user answered every decision of section 9
on 2026-10-14; each answer is recorded there.

## 1. Scope

`docs/reviews/2026-10-13-code-review.md` (in this plan, "the review") is a
review of `74fa0b2`. Its section 7 gives what PRs #134 to #141 fixed: the
review's findings 1.1.1 to 1.1.4, and three bugs that the work found (B5 to
B7). This plan covers every other finding.

On 2026-10-14, three read-only reviewers checked each finding again on
`main` at `35e7747`. Every finding is still present, except 5.1b: the
waveform test of B1 compares the measurements of `cpp-siemens` with the
reader. Section 6 gives the findings that need no code fix. Each task below
gives the current file and line where the review's numbers have moved.

The work has four tracks:

| Track | Findings | Kind |
|---|---|---|
| C | 1.1.5, 1.1.6, 1.2, 1.3, 2 | Correctness and speed of the code |
| D | 3, 4 | Documents, the checks that keep them right, and duplication |
| A | 6 | The API, one change at a time |
| T | 5 | The tests |

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern).
Each follows the rule of section 2.

## 2. The rule for the tests of each task

This is the rule of `docs/plans/cpp-siemens-review-fixes.md`, extended to
the kinds of task here.

1. **A task that changes behaviour.** The first commit adds the tests of the
   task, and no fix. They fail on that commit, and the PR quotes the
   failure. The fix commits then make the same tests pass, with no change to
   them except a name or a message.
2. **A speed task.** The first commit adds a test that fails on `main`, where
   one exists: a call count, or an operation count. Where none exists, the
   test is an equality test of the old and new results, and the PR gives the
   measured times. Decision Q8 says whether a timing test may be the failing
   test.
3. **A refactor.** Behaviour does not change. The existing tests must pass
   unchanged, and the PR gives the tests that cover the code it moves.
4. **A documentation task.** Where a check can keep the text right, the first
   commit adds the check (in `tests/test_documents.py`, task D0), and it
   fails on `main`. The text fix then makes it pass.
5. **A test task.** A test that is made stronger gets a mutation: a one-line
   change to `src/` that the old test misses and the new one catches. The PR
   quotes both runs. The mutation is applied only in the PR's runs, never
   committed. Each review below names its mutation where one was found.
6. **Always.** Each new test gets an entry in `TESTS.md`, and each removed
   test loses its entry. No task adds a fixture to `tests/seqfiles/`, because
   each such fixture needs a new entry in the plugin's `expected_digests.json`
   from the driver. A test builds its file in `tmp_path` instead.
7. **The plugin's tests.** A test that imports `pulseq_analysis` goes in a
   module of `conftest.ANALYSIS_TESTS`. The wheel tests run without
   pulseq-analysis (the lesson of #137).

## 3. Track C: correctness and speed

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| C1 | `fix/edge-gradient-no-sample` | 1.1.5 | S | — |
| C2 | `fix/spec-checks-with-a-missing-value` | 1.2.2, 1.2.3 | S-M | — |
| C3 | `fix/rotation-ids-int64` | 1.2.4a | S | — |
| C4 | `fix/interpreter-refuses-a-class` | 1.2.4c | S | — |
| C5 | `fix/rf-signal-cell-boundaries` | 1.3.1 | S | — |
| C6 | `fix/value-guarantees` | 1.3.3 | S | Q6 |
| C7 | `perf/one-plan-per-events-and-duration` | 2.2 | M | — |
| C8 | `fix/every-undefined-behaviour-case` | 1.1.6 | M | Q1, Q2; after C1 |
| C9 | `fix/extension-type-ids` | 1.2.4b | S | Q4; after C2 |
| C10 | `perf/gradients-at-grouped` | 2.1 | S | Q8; after C5 |
| C11 | `fix/asc-reader-forms` | 1.3.2 | S | Q5 |
| C12 | `perf/pns-threshold-runs` | 2.5c | S | Q8; after C6 |
| C13 | `fix/gradient-time-shape-before-0` | 1.2.1 | S | Q3; after C9 |
| C14 | `fix/shape-size-limit-code` | 1.2.4d | S | Q7; after C13 |
| C15 | `perf/shapes-of-vectorized` | 2.5b | S | Q8; after C14 |
| C16 | `perf/lazy-rf-adc-and-labels` | 2.4 | M | Q9; after C5, C10 |
| C17 | `fix/spec-zero-time-trapezoid` | `TODO.md` | S | Q10 |
| C18 | `fix/zero-length-event-plays-0` | C17 | S | Q10; after C17 |

### C1. An oversampled gradient of 0 samples in the "edge" mode (1.1.5)

- **The bug:**
  - With 1 or 2 samples, the edge mode keeps none.
  - `_points` (`interpreter.py:913-918`) gives `[(0, first), (0, last)]`.
  - The reader plays 0. Reproduced: `gradient_peaks` gives x a peak of
    300 000 Hz/m and a slew of 3e10 on an axis that plays 0.
- **The fix:** `_points` gives values of 0 for an arbitrary event with no
  sample kept, as it does for an amplitude of 0.
- **The test:** `test_an_edge_gradient_with_no_sample_plays_0_in_the_measurements`
  (plugin `test_load_in_pulseq_analysis.py`), with the inline file of
  `test_api.oversampled_file` of 1 sample. The points are 0, the peak and
  the slew are 0, and the reader gives 0.

### C2. `spec`'s checks when a table or a value is missing (1.2.2, 1.2.3)

- **1.2.2:**
  - `_event_ends` (`spec.py:1301`) returns None when any event table has a
    syntax error, which skips every `raster.*`, `block.event-too-long` and
    `gradient.*` rule.
  - The fix: an empty stand-in for a table that is None, so that its events
    have NaN ends and `found` False.
  - `_check_trigger_ends` runs whenever the blocks read.
- **1.2.3:** `last != 0` (`spec.py:1620`) is True for NaN. The fix is to add
  `np.isfinite(last)`.
- **The tests (`tests/test_seqfile.py`):**
  - `test_a_syntax_error_in_one_event_table_keeps_the_checks_of_the_others`,
    for each event table. It breaks one row and adds a raster violation in
    another table, and both codes are reported.
  - A 1.4 file whose gradient end is not defined gives only
    `layer1.gradient-ends`.

### C3. Rotation IDs are int64 (1.2.4a)

- **The fix:** in `model.py:127`, `id` becomes `<i8`. The plugin uses the same
  table, so it follows.
- **The test:** the `id` dtype of the rotations of a 1.5.1 file is int64,
  through `spec` and through `cpp-siemens`.
- **The documents:** `CHANGELOG.md`.

### C4. `interpreter()` refuses a plugin class (1.2.4c)

- **The fix:** `interpreters.py:162`. A value that is a class raises
  `TypeError`, with a message that names `()`.
- **The test:** in `tests/test_interpreters.py`, with a fake plugin class.

### C5. `RfEvent.signal` and the cell boundaries (1.3.1)

- **The bug:** `np.floor(times / dwell)` (`events.py:154`) puts 89 of 5000
  boundaries in the cell before, at a dwell of 1 us.
- **The fix:** `np.floor(times / dwell + 1e-6)`. The docstring says that a
  time within 1e-6 dwells of a boundary is in the next cell.
- **The test:** `test_the_signal_of_cells_puts_each_cell_boundary_in_the_cell_after_it`
  (`tests/test_decoding.py`).

### C6. Values that break their own guarantees (1.3.3)

- **`FrozenDict`:** `__new__` fills it, and `__init__` does nothing, so
  `d.__init__(b=2)` no longer changes it. That `dict.__setitem__` cannot be
  blocked is documented.
- **The hardware label:** `pns_levels` refuses a label that the JSON form of
  a `Series` refuses (`"nan"`, `"inf"`, `"-inf"`), before any work (Q6).
- **`AnalysisSpec`:** it checks that `necessary` is a tuple of unique strs,
  that `title` and `description` are strs, and that `series` is None or a
  str.
- **The tests:** one in each of `test_equality.py`, `test_pns_levels.py` and
  `test_analyses.py`.

### C7. One plan per events and duration, for rotated blocks (2.2)

- **The cost:** `_plan` and `_points` (`_played.py:177-206`) run in Python
  for each group of (events, quaternion, flags, duration). That is about
  65 us per rotated block: 6.7 s for a radial file of 300 000 blocks.
- **The fix:**
  - Group the plans by (events, duration).
  - Read `gradients_at` once for all the groups of a plan.
  - Vectorise `_points` over them.
  - The estimate is 0.5 s instead of 6.7 s.
- **The test:** `test_blocks_with_the_same_events_and_duration_are_planned_once`
  (`tests/test_played.py`). It counts `_plan` calls on 5 readouts with 5
  rotations: 1 after the fix, 5 today. The existing tests of the values
  guard the result.

### C8. Every case of undefined behaviour, and the size of `long` (1.1.6)

- **Every case (Q1: A):**
  - `_checks` collects every case, with each event checked once.
  - `UndefinedBehaviour` carries `cases`; `.code` stays the first.
  - `read_cpp_siemens` gives a `Violation` for each, capped at
    `MAX_LOCATIONS` for each code, with `omitted`.
  - `hidden_one_point` covers every block.
- **The size of `long` (Q2: a):** the checks use a fixed 32-bit
  `long`, so that a file has one verdict on every host.
  - `test_fuzz` compares with the 64-bit sanitized build, so it must accept
    "rejected for the 32-bit build". This matters only for a time past 2^31
    us (D5.11).
- **The tests:**
  - `test_every_case_of_undefined_behaviour_is_a_violation`
    (`test_interpreter.py`), with two cases in two blocks;
  - `test_the_verdict_does_not_depend_on_the_size_of_long` (`test_checks.py`).
- **The documents:** the plugin's `docs/specification.md` (2.2, D5.11) and
  its README.

### C9. Extension type IDs are positive (1.2.4b)

- **The fix:** `_read_extensions` (`spec.py:1012-1031`) reports `id.positive`
  for a type ID of 0 or less, in the header and in the `type` column (Q4).
- **The test:** in `tests/test_seqfile.py`, for 0 and -1.
- **The documents:** `docs/specification.md`.

### C10. `SpecDecoding.gradients_at` in one sort (2.1)

- **The cost:** a loop of `np.flatnonzero(ids == gid)` over the unique IDs
  (`decoding.py:221-226`) is quadratic. `gradients_at` took 0.26 s for
  40 000 blocks and 3.42 s for 160 000.
- **The fix:**
  - Sort the IDs once, and loop over the slices (a prototype is 13 times as
    fast, with an equal result).
  - Keep the row map of the rotations on the decoding, in place of
    `np.full(block_count, -1)` on each call (`decoding.py:231`, and the
    plugin's `interpreter.py:799`).
- **The test:** an equality test of the old and new results on large random
  inputs, with the times in the PR, or a scaling test (Q8).

### C11. The `.asc` reader (1.3.2)

- **The fix (`asc.py`):**
  - Read ints with a sign.
  - Read hex as `int(..., 16)`.
  - Read floats with an exponent sign (`1.5E-3`, `1e+02`).
  - Test `if ended: continue` before the `=` check.
  - Read the file in the encoding of Q5.
- **The tests:** extend `_FORMS` and `_FORMS_FIELDS` of `tests/test_asc.py`
  with these forms (the expected `"k": -1.0` becomes `-1`), and add one test
  of a byte that is not ASCII.

### C12. The runs of a threshold in `pns_levels` (2.5c)

- **The cost:** `_IntervalFinder.add_chunk` (`pns_levels.py:587-600`) loops in
  Python over the runs. A threshold inside the range of the levels costs
  about 10 % each.
- **The fix:** `np.maximum.reduceat` for the largest value of each run and its
  first index, with only the join of an open run in Python. Correct
  `docs/implementation.md:642` ("a few percent").
- **The test:** equality of the intervals (the existing tests), and an
  operation count or the times (Q8).

### C13. A gradient time shape that starts before 0 (1.2.1)

- **The bug:** `spec` checks a first time below 0 for RF only
  (`spec.py:1514`). A gradient time shape `-2 1 3 6 10` reads, and its
  offsets do not increase.
- **The fix (Q3: reject):**
  - The gradient loop reports `shape.time-order`.
  - `RULES["shape.time-order"]` says "a time shape".
  - D3.9 of `docs/discrepancies.md` covers gradients.
- **The test:** in `tests/test_seqfile.py`.

### C14. The shape size limit has its own code (1.2.4d)

- **The bug:** the package's limit of 2^27 samples (`spec.py:375, 853-861`) is
  reported as `shape.length`, a rule of the specification (spec:626).
- **The fix (Q7: a):** its own code, `limit.shape-samples`. Its
  `Rule` says that it is the package's limit of memory, not the
  specification's. It goes in the `NO_FIXTURE` list of `test_seqfile.py`.
- **The test:** a shape that declares 200 000 000 samples gives the new code,
  and not `shape.length`.

### C15. `spec._shapes_of` with no loop over the samples (2.5b)

- **The cost:** the loop at `spec.py:959` takes 0.77 s of the 1.81 s of
  `read_seqfile` on a file of 4 000 000 shape samples.
- **The fix:** the vectorised form, which takes 0.021 s with an equal result.
  `index` is negative for the head lines, so it must not index `good`
  directly.
- **The test:** the existing tests of bad samples, and an operation count or
  the times (Q8).

### C16. The work of `load` that no analysis reads (2.4)

- **The cost:** on a file of 1e6 blocks with 200 000 RF pulses of 2000 samples,
  `load` takes 10.4 s and 10.2 GiB. With no RF and ADC decoding it takes
  3.4 s and 0.8 GiB, and with no walk of the labels 2.6 s.
- **The fix:**
  - `SpecDecoding.rf` and `.adc` are removed (Q9). A caller uses
    `decode_rf(snap.data)` and `decode_adc(snap.data)`, as `docs/usage.md` says.
    `docs/findings-for-pulseq-checks.md` 2.3 and `docs/migration.md` follow.
  - The LABELSET objects are filtered to NOROT and NOSLC before the walk.
- **The tests:**
  - `test_load_decodes_no_rf_event` (`tests/test_decoding.py`): it counts the
    `RfEvent`s that `load` builds, which is 0 after the fix. The test of
    `decoding.rf == decode_rf(data)` goes with the fields;
  - a file with LABELSET LIN only never walks its lists for the labels.
- **Also found:** most of the rest of the time, for 200 000 trapezoids, is in
  the checks of each model object (`model._post_init`). That is a later
  study, not part of this task.

### C17. `spec` and a trapezoid whose times are all 0 (`TODO.md`)

Decision Q10 (from `TODO.md`): if `spec` should reject such a row, this task
adds the rule, its record entry, and a test. If it reads it, this task is
only the removal of the item from `TODO.md`.

### C18. An event of length 0 plays 0 in the measurements (C17)

The check of C17 found it; the user made it a task on 2026-10-18.

- **The bug:**
  - A gradient event whose points are all at one time (an event of length 0)
    has no segment. `spec`'s `gradients_at` and the reader's `gradientsAt`
    give 0 for it at each time of its block but its one time, where a
    decoding can give another value (the reader gives the vertex of an
    extended trapezoid of one vertex).
  - In a block that is not read through `gradients_at`, `_played` keeps the
    values of the decoding, and the measurements take them. Reproduced:
    `valid_1_5_1.seq` with the `[TRAP]` row `1 1000000 0 0 0 100` alone in
    block 2. `gradient_peaks` gives x a peak of 1 000 000 Hz/m in block 2,
    above the vector peak of the file (500 000 Hz/m). With a rotation of the
    field of view, the block is read through `gradients_at` and the peak is
    gone. A window can leave it out too.
  - The same through `cpp-siemens`, and with an extended trapezoid whose time
    shape has one sample, which both interpreters read.
- **The fix:** `_played` gives the values 0 to the points of each decoded
  event whose points are all at one time, for every interpreter. It does so
  after `_from_gradients_at`, whose plans take the steps of a block from the
  decoded values (B6).
- **The tests:**
  - `test_an_event_of_length_0_plays_0_in_the_measurements_through_spec`
    (`tests/test_played.py`): the measurements of the file equal those of the
    same file with the amplitude 0, for a trapezoid and an extended
    trapezoid, with and without a window and a rotation of the field of view;
  - `test_the_played_points_of_an_event_of_length_0_are_0_through_spec`: the
    played points are 0;
  - the same two through `cpp-siemens` (plugin
    `test_load_in_pulseq_analysis.py`), with the reader's 0.

## 4. Track D: the documents, their checks, and duplication

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| D0 | `test/document-checks` | 3.9, 4.1, 4.2 | S-M | — |
| D1 | `docs/findings-relative-links` | 3.1 | S | Q11; after D0 |
| D2 | `docs/plugin-version` | 3.2 | S | Q12; after D0 |
| D3 | `docs/readme-example` | 3.3 | S | after D0 |
| D4 | `docs/implementation-claims` | 3.7, 4.2; 2.3, 2.4c, 2.5a | S | after D0 |
| D5 | `docs/stale-names` | 3.8 (not pypulseq-issues) | S | after D0, D4 |
| D6 | `docs/usage-not-a-checker` | 6 | S | after D4 |
| D7 | `fix/analysis-contracts` | 3.4 | S | Q13 |
| D8 | `fix/one-scope-gate` | 3.5, 4.3 | M | Q14 |
| D9 | `refactor/one-extension-walk` | 4.5 | S | after C10, C16 |
| D10 | `refactor/plugin-shared-helpers` | 4.4 | M | after D9, C8 |
| D11 | `docs/no-pypulseq-issues` | 3.8 (pypulseq-issues) | M | Q15; last, before 0.1.0 |

### D0. The checks of the documents (3.9, 4.1, 4.2)

- **A new module, `tests/test_documents.py`.** It imports only
  `pulseq_analysis` and the standard library, so it needs no plugin build.
  Its checks pass on `main` today:
  - each record ID that a document cites (`D[1-7].n`) is an entry of
    `docs/discrepancies.md` or of the plugin's `docs/specification.md`;
  - each relative link with an anchor resolves (202 today);
  - the code tables of `docs/usage.md` and `docs/specification.md` are
    `spec.RULES`;
  - the codes in `findings-for-pulseq-checks.md` are `interpreter.CODES`,
    read with `ast` from the plugin's source;
  - the analyses table of `docs/usage.md` is `registry()`: the ID, the
    parameter names, `necessary`, the defaults and the cost.
- **The docs-only path.** `scripts/check` runs this module with
  `test_interface.py`, and `README.md` joins `DOCS` of
  `tests/test_interface.py`.
- **The test:** none fails first, because the checks are new and true. The
  PR shows each check failing on a one-line edit of a document.
- **Later checks.** The tasks D1 to D5 add their checks here, each of which
  fails on `main`.

### D1. `findings-for-pulseq-checks.md` and its pinned commit (3.1)

- **The bug:** the document says it describes `6fa807d`, and its links name
  that commit, which has none of the record IDs that it cites (D2.18).
- **The fix (Q11):** relative links. The text says the document describes
  `main`, and that the release tag pins it.
- **The check:** `test_no_document_links_a_commit`, for `docs/*.md` outside
  `plans/` and `reviews/`.

### D2. The version of pulseq-cpp-siemens (3.2)

- **The bug:** `CHANGELOG.md:115-116` and `docs/migration.md:87-89` promise
  the same version as pulseq-analysis and `pulseq-analysis>=0.1.0rc7,<0.2`.
  The plugin's `pyproject.toml` has `0.1.0` and only `numpy`.
- **The fix (Q12):** the documents and the plugin's `pyproject.toml` agree
  before rc7.
- **The check:** `test_the_documents_give_the_version_of_pulseq_cpp_siemens`
  reads both `pyproject.toml` files with `tomllib`.

### D3. The README's example and its install line (3.3)

- **The bug:** the install line pins `v0.1.0rc6`, at which the example's
  imports do not exist.
- **The fix:** the main install line is `@main` until rc7, and the rc6 line
  stays only as the last release.
- **The check:** `README.md` in `DOCS` (D0) resolves the example's names on
  `main`.
- **Also:** `levels.peak_time_s:.4f` fails for a file with no gradients, where
  it is None.

### D4. The claims of `docs/implementation.md` (3.7, 4.2)

Correct:

- the cost of `sequence_index`: O(B log B + K + P), not O(B);
- which calls share the kept gaps: `block_samples`, not `gradient_spectrum`;
- section 1.2: the session's field of view as a reason a block is read
  through `gradients_at`;
- "a shape is decompressed once": in one call.

Also:

- The cost table of `docs/usage.md` becomes a link to section 3.5 of
  implementation.md.
- Close 2.3, 2.4c and 2.5a with what section 6 of this plan says. C12 fixes
  the "few percent".

### D5. Stale names (3.8, but not "pypulseq-issues")

- **The fixes:**
  - `Sequence.read`: `implementation.md:774`, and the comment
    `grad_spectrum.py:203`.
  - `pns_levels.SAFE_FIELDS`: it is `safe.SAFE_FIELDS` at
    `implementation.md:414, 827` and `usage.md:401`.
  - `test_matches_scipy_spectrogram`: `grad_spectrum.py:35, 289` and
    `tests/test_grad_spectrum.py:189` name the oracle tests that exist.
- **The check:** `test_each_test_that_a_document_names_exists`. It finds the
  three citations of the test that does not exist.

### D6. `docs/usage.md` does not read as a checker (6)

- **The fix:**
  - "3. Check the gradient limits" becomes "3. The gradient peaks".
  - "6. Check the acoustic resonances" becomes "6. The gradient spectrum".
  - The examples print the values, and one sentence says that the
    comparison with a scanner's limits is the caller's.
- **The check:** the anchors check of D0 finds the links that the new headings
  break.

### D7. The contracts of the analyses (3.4)

- **The tie of the vector peak.** `registry.py:245-246` and `usage.md:312`
  give it to "the first in play order". The code and
  `implementation.md:347` give the earliest time.
- **The axes.** "The logical axes of the file" (`registry.py:234, 247, 283,
  471`) becomes the axes as the decoding gives them (`usage.md:182-186`).
- **The version:** see Q13.
- **The test:** a tie of the vector peak where the earliest time is not in
  the first block (`tests/test_grad_peaks.py`), if no test pins it today.

### D8. One gate of the scope for every interpreter (3.5, 4.3)

- **The bug:**
  - For a folder, `spec` gives `IsADirectoryError`, and `SeqFileError` for a
    binary Pulseq file. `cpp-siemens` gives `NotSupported` for both.
  - Five documents say `NotSupported` "whatever the interpreter"
    (`CHANGELOG.md:66`, `migration.md:161`, `specification.md:43, 234`,
    `errors.py:10, 82`).
  - The version gate is written in both interpreters, with two messages.
- **The fix (Q14: a):** `read_seqfile` checks the scope (a folder,
  the binary magic, and the version) before it chooses the interpreter,
  with one function and one message.
- **The tests:**
  - `test_spec_raises_not_supported_for_a_folder`;
  - `test_spec_raises_not_supported_for_a_binary_pulseq_file`;
  - a plugin test of one message from both interpreters.

### D9. One walk of the extension lists (4.5)

`_rotation_refs` (`decoding.py:388-406`) uses `_extension_objects`. This is a
refactor, and the rotation tests cover it. It goes after C10 and C16, which
change `decoding.py`.

### D10. The plugin uses the main package's helpers (4.4)

- **The duplicated code:** the plugin re-implements `Points`, the test of a
  pure delay, and the path of the physical gradients
  (`interpreter.py:655-657, 699, 786-811`).
- **The fix:** it imports `Points`. `scanner` gets public helpers for the
  other two, used by both decodings.
- **The tests:** this is a refactor, and the session tests cover it.

### D11. No "pypulseq-issues" (3.8)

- **Where it is:** 66 lines in 18 files:
  - `TESTS.md`, three module docstrings, and tests;
  - `pyproject.toml:47` and `TODO.md:13`;
  - plans and reviews.
- **The fix (Q15):** each citation becomes the behaviour, with its source in
  pypulseq.
- **The check:** `scripts/check` fails on the string, in both paths.
- **When:** this task goes last, after the API track, and before 0.1.0.

## 5. Track A: the API

Each task changes `CHANGELOG.md`, `docs/migration.md`, `docs/usage.md`,
`TESTS.md` and many tests, so the tasks run one at a time, in this order. A0
goes first: it makes `test_interface.py` check `__all__`, so that each later
rename is checked.

| Task | Branch | Decision | Size |
|---|---|---|---|
| A0 | `feature/all-of-each-module` | Q16 | M |
| A1 | `feature/hardware-is-safe-hardware` | Q17 | M-L |
| A2 | `feature/time-range-of-peaks` | Q18 | M |
| A3 | `feature/sampler-axis-names` | Q19 | M |
| A4 | `feature/peak-time-none` | Q20 | M |
| A5 | `refactor/model-tolerance-name` | Q21 | S |
| A6 | `feature/one-entry-point` | Q22 | S-M |
| A7 | `feature/protocol-times-in-seconds` | Q23 | M |
| A8 | `docs/method-defaults` | Q24 | S |

Each task is test-first:

- A test of the new interface fails on `main`.
- The old name raises (`ImportError`, `AttributeError` or `TypeError`), as
  for the other changes of the release candidates.
- `docs/migration.md` gives the old and the new name.

The details are in each decision of section 9.

## 6. Findings that need no code fix

These were measured on 2026-10-14. D4 closes them in the documents.

- **2.3, the kept work of the sampler.** Keeping the sampler between calls
  saves 2 % on a file of 40 000 blocks and 13 % on a spiral file. Most of the
  cost is filling each chunk, which a cache cannot avoid without keeping the
  whole waveform.
- **2.4c, a shape decompressed twice.** 0.05 s for 1000 shapes of 4000
  samples. With C16, only gradient shapes are decompressed.
- **2.5a, the plugin decodes a kept block again.** 0.02 s for 1000 calls, and
  0.10 s for 32 000.

## 7. Track T: the tests

| Task | Branch | Finding | Size | Needs |
|---|---|---|---|---|
| T1 | `test/fast-slow-typing` | 5.3a | S | — |
| T2 | `test/tolerance-ns` | 5.3d | S | — |
| T3 | `test/spectrum-oracle-arguments` | 5.3c | S-M | — |
| T4 | `test/matlab-rotated-float64` | 5.3b, 5.3e, 5.6b | M | — |
| T5 | `test/no-tautologies` | 5.6a, 5.6c, 5.7 | S | — |
| T6 | `docs/tests-say-what-they-test` | 5.9c, 5.1a (the claims) | S | — |
| T7 | `test/strict-credit` | 5.6d | S | Q30; after T6 |
| T8 | `test/no-duplicates` | 5.8a-c | M | after T2 |
| T9 | `test/external-code` | 5.5 | M | Q25; after T8 |
| T10 | `chore/matlab-oracle-in-ci` | 5.4 | S | Q26 |
| T11 | `test/root-oracles-through-spec` | 5.8d, 5.9b | L | Q29; after T3, T5, T7 |
| T12 | — | 5.1a | — | dropped (Q27: T6 corrects the claims) |
| T13 | `test/original-safe-oracle` | 5.2 | L | after T8, T9, T10 |
| T14 | `test/rotated-analyses-matlab` | 5.9a | M | after T4 (and T10) |

### T1. The fast and the slow typing compare most tables (5.3a)

- **Today:** `_fast` gives up on 395 of the 400 tables of the test
  (`test_as_written.py:276`).
- **The fix:** draw most rows from tokens that are valid for their kind, and
  assert at least 300 compared tables.
- **The mutation:** `float_trailing_dot`, which makes `_FLOAT` refuse `5.`.
  Every test misses it today.

### T2. A guard of `TOLERANCE_NS` (5.3d)

- **Today:** with `spec.TOLERANCE_NS = 0`, the whole root suite passes.
- **The fix:**
  - a test of `_off_raster` on both sides of the tolerance;
  - a file test with `AdcRasterTime 3e-08` and a dwell of 30 ns, which is off
    by 7e-12 ns in floats.
- **The mutation:** `tolerance_ns_0`.

### T3. The spectrum oracle takes its three arguments (5.3c)

- **The fix:** `tests/oracles/grad_spectrum.py` takes `max_frequency_hz`,
  `window_s` and `frequency_oversampling`, and a parametrised test uses an
  odd window and a maximum off the bins.
- **The mutation:** `spectrum_pad_odd`. With `pad = (nwin + 1) // 2`, the RSS
  of an odd window changes by 0.39 %, and every test misses it today.

### T4. MATLAB's waveform of a rotated file, in float64 (5.3b, 5.3e, 5.6b)

- **The fix:**
  - For a rotated file of 1.5.1 or later, compare MATLAB's points and
    midpoints with the sampler of `load(path)`, to 1e-12, and leave out only
    the midpoints at a boundary of a rotated block (D2.14).
  - Replace the stale skip (the interpreter `strict`).
  - `compare_rotated_gradients` takes the tolerance: 1e-12 for `spec`, and
    the float32 one for the plugin.
  - The assert `rotated == blocks` becomes `setting == "apply"`.
- **The mutation:** `no_normalize`. With the quaternions as written, the
  oracle tests miss it today, and 10 of the 11 fail at 1e-12. Every MATLAB
  point agrees to 1.6e-15 on `main`.

### T5. Asserts that cannot fail, and tautologies (5.6a, 5.6c, 5.7)

- **The gamma test (`test_pns_levels.py:1020`):** remove it, and add its
  sequence to `_SEQUENCES`.
- **The second oversampled `diff.close` (`test_cpp_oracle_decode.py:342`):**
  it becomes an explicit `designed` entry.
- **The tautologies (`test_seq_utils.py:53`, `test_sampling.py:791, 852`,
  `test_pns_levels.py:545`):** they compare with hand values or with the
  documented rule.

### T6. The tests say what they test (5.9c, 5.1a)

- **`TESTS.md` 2.6** describes tests that are not there: the polyline items,
  and the refusal of the rotation extension.
- **"Shares no code"** (`test_grad_peaks.py:500`, `TESTS.md:2128`): the
  oracles take the package's `played_gradients`.
- **This is a documentation task:** it corrects the text, and the decoding
  is tested on its own elsewhere.

### T7. Strict credit in the peaks oracle (5.6d)

- **Today:** the "later block" relaxation of `_assert_same_credit`
  (`test_grad_peaks.py:551`) never fired in 3066 calls.
- **The fix (Q30):** require equal credit.
- **The mutation:** `peak_credit_first_of_event`. The plugin's oracle tests
  catch it once the relaxation is gone, and the root tests do only after
  T11.

### T8. Duplicate tests (5.8a-c)

Remove:

- `test_safe_and_asc_import_neither_pypulseq_nor_matplotlib`, whose assumption
  is also false;
- the decoding tails of `test_seqfile.py:1504, 1787, 1808, 1981, 1996`.
  Move the non-zero ADC phases into `test_decoding.py` first;
- the CRLF assert of `test_cpp_oracle.py:370`.

### T9. Tests of code outside this repository (5.5)

See Q25.

### T10. The MATLAB oracle in CI (5.4)

See Q26.

### T11. The root's oracle comparisons through `spec` (5.8d, 5.9b)

- **The fix:**
  - Move the cases of the plugin's measurements file that `spec` reads to the
    root tests, through `spec`.
  - Give `random_gap_sequence` a mode that `spec` reads, so that the root
    runs gaps and blocks of duration 0 (Q29).
- **The mutation:** `peak_credit_first_of_event`. The root catches it after
  the move.

### T12. Oracles whose input is independent of the package (5.1a)

- **The fix (Q27):** the oracles take pypulseq's reading of the written file
  (`pp.Sequence().read`), where pypulseq reads it, in place of
  `sequence_of`.
- **The tolerance stays 1e-12:** on three sequences the oracle's peaks are
  equal, with a difference of 0.0.

### T13. An independent reference for SAFE (5.2)

See Q28.

### T14. The rotated analyses against MATLAB (5.9a)

- **The test:** `gradient_peaks` of the rotated files that MATLAB reads,
  against the values of MATLAB's rotated polylines. It leaves out the
  boundaries of D2.14.
- **The mutation:** to be found in the task, for example dropping the times
  of the other axes in a rotated block of `_played`.
- **CI:** it runs in CI only with Q26 (a) or (b).

## 8. Order, and the files that tasks share

- **The shared files.** `TESTS.md` and `CHANGELOG.md` change in almost every
  task. Their changes are additions to different sections, so a PR rebases
  on `main` after the one before it merges. These files are also changed by
  more than one task:

  | File | Tasks |
  |---|---|
  | `spec.py` | C2, C9, C13, C14, C15, D8 |
  | `tests/test_seqfile.py` | C2, C3, C9, C13, C14, T2, T8, D8 |
  | `synth/decoding.py` | C10, C16, D9, D10 |
  | plugin `interpreter.py` | C1, C8, D8, D10 |
  | `docs/usage.md` | D4, D5, D6, D7, D8, every task of track A |
  | `docs/implementation.md` | D4, D5, C12, T6, C18 |
  | `tests/test_grad_peaks.py` | D7, T6, T7, T11, T12, A2, A4 |
  | `tests/test_safe.py` | T8, T9, T13 |
  | `tests/test_matlab_oracle.py` | T4, T14 |

  Each row is done in the order of its tasks.
- **The order of the waves:**

  ```
  Wave 1:  D0  ||  C1  ||  C4  ||  C5  ||  C7  ||  T1  ||  T3  ||  T4
  Wave 2:  C2  ||  C3  ||  C6  ||  C11 ||  D1 .. D3  ||  T5  ||  T6  ||  T2
  Wave 3:  C8  ||  C9  ||  C10 ||  C12 ||  D4  ||  D7  ||  T7  ||  T8  ||  T10
  Wave 4:  C13 ||  C16 ||  D5  ||  D8  ||  T9  ||  T14
  Wave 5:  C14 ||  D6  ||  D9  ||  T11
  Wave 6:  C15 ||  D10 ||  T13 ||  C17
  Wave 7:  C18
  Then:    A0, A1, ..., A8, one at a time
  Last:    D11, then the release 0.1.0rc7
  ```

  - A wave starts when each task before it, of the files it shares, has
    merged.
  - A task whose decision is open waits for it.
  - At most four tasks run at a time, so that each review stays small.
- **Value first.** In the order of value: C16 (10 s and 10 GiB down to 2.6 s
  and 0.8 GiB), C7 (13 times on rotated files), C10 (quadratic), C1 and C13
  (wrong values), D8 (one contract for the scope). Within a wave, these go
  first.

## 9. Decisions

Each gives its evidence and a recommendation. The user answers them a few
at a time; each answer is recorded here with its date.

### Correctness and speed

**Q1. Every case of undefined behaviour, as data (C8).**
Answer (2026-10-14): (A), every case as a `Violation`.
- **The evidence:**
  - The C++ reader has no single behaviour on these files (D5).
  - The writers make none of them.
  - Today `load` gives the first case only, and pulseq-checks would want
    them all.
- **The options:**
  - (A) every case as a `Violation` of the one `SeqFileError`, with no change
    of the protocol. Recommended.
  - (B) a channel of findings in the plugin protocol, which bumps
    `PROTOCOL`. Undefined behaviour still blocks the decoding.
  - (C) keep the first case, and document it.

**Q2. The size of `long` in the checks (C8).**
Answer (2026-10-14): (a), always 32 bits.
- **The evidence:** `long` is 32 bits on the Windows build of the Siemens host
  and 64 bits on Linux (MARS), and the checks use the size of the host that
  runs them. So one file can have two verdicts.
- **The options:**
  - (a) always 32 bits, so that a file is rejected where any build has
    undefined behaviour. Recommended.
  - (b) always 64 bits.
  - (c) a setting of `CppSiemens`.
  - (d) the host's size, as now.

**Q3. A gradient time shape that starts before 0 (C13).**
Answer (2026-10-14): (1), reject, and extend D3.9 to gradients, because the
specification does not say how to read such a shape. The user first chose
"accept it but warn", then decided that it is an error. The rule for RF
does not change.
- **The evidence:**
  - The specification says nothing on the order or the start (spec:395).
  - D3.9 rejects an RF time shape that starts before 0, because such times
    "define no waveform".
  - The C++ reader reads it, and clips it at the delay.
  - MATLAB Pulseq and pypulseq write a first time of 0 (`delay =
    round(times(1))`).
- **The options:**
  - (1) reject, and extend D3.9 to gradients. Recommended.
  - (2) read it, clipped at 0.
  - (3) keep it, which leaves an undefined waveform.

**Q4. Extension type IDs (C9).**
Answer (2026-10-14): (a), spec:181 covers `<type>`.
- **The evidence:** spec:181 says "IDs must be positive integers", and
  spec:472 and spec:494 call `<type>` the "ID of the type". MATLAB Pulseq and
  pypulseq number the types from 1.
- **The options:**
  - (a) the rule of spec:181 covers `<type>`, so the rule is the
    specification's, with no record entry. Recommended.
  - (b) it does not, and `spec` decides, with an entry of D2.

**Q5. The encoding of an `.asc` file (C11).**
Answer (2026-10-14): (a), latin-1.
- **The evidence:** Siemens `.asc` files come from Windows tools, so latin-1
  or cp1252 is likely. Every field is ASCII. There is no real non-ASCII file
  in the repository to check.
- **The options:**
  - (a) latin-1, which never fails. Recommended.
  - (b) strict UTF-8, with a `ValueError` that names the file and the line.

**Q6. A hardware label that is not a finite number (C6).**
Answer (2026-10-14): (a), refused at the input. With Q17 (A), the check is on
the name of the `SafeHardware`.
- **The evidence:** the JSON form of a `Series` refuses the strings `"nan"`,
  `"inf"` and `"-inf"` in `meta`, so `to_series` fails for such a label.
- **The options:**
  - (a) `pns_levels` refuses such a label, before any work. Recommended.
  - (b) a JSON form of `meta` that tells such a string from a number that is
    not finite. That changes the format that pulseq-reports reads.

**Q7. The package's limit of shape samples (C14).**
Answer (2026-10-14): (a), its own code.
- **The evidence:** the specification has no limit. The C++ reader stores the
  count in an `int`. Real shapes have at most about 1e6 samples. Without the
  limit, a 30-byte file could make the process allocate without bound.
- **The options:**
  - (a) its own code, `limit.shape-samples`, with a `Rule` that says it is the
    package's limit. Recommended.
  - (b) `NotSupported`, as outside the package's scope. `cpp-siemens` would
    then need the same gate.
  - (c) no limit.

**Q8. Timing tests (C10, C12, C15).**
Answer (2026-10-14): (a), no timing tests: an equality test, and the times in
the PR.
- **The evidence:** the repository has no timing test. A test that counts
  calls or operations fails first where a fix changes how often a function
  runs (C7, C16). For a fix of the cost of one call (C10, C15), only a time
  or a scaling ratio shows it, and those are noisy on a shared CI runner.
- **The options:**
  - (a) no timing tests: an equality test of the old and new results, and
    the measured times in the PR. Recommended.
  - (b) a scaling test with a loose bound: twice the input takes less than
    three times as long, as the least of three runs.

**Q9. The RF and ADC events of a decoding (C16).**
Answer (2026-10-14): (b), remove `rf` and `adc` from `SpecDecoding`. The
documented way is `decode_rf(snap.data)` and `decode_adc(snap.data)`; the
MATLAB oracle already calls them, and the only reader of the fields was a test
of the fields.
- **The evidence:** no analysis reads `decoding.rf` or `decoding.adc`; only
  the decoding tests and the MATLAB oracle do. Decoding them takes 7 of the
  10 s, and 9.4 GiB, of a realistic file of 1e6 blocks.
- **The options:**
  - (a) read-only mappings that decode an event on its first read, with the
    same type and the same equality. Recommended.
  - (b) remove them from the decoding (`decode_rf(data)` stays).

**Q10. `spec` and a trapezoid whose times are all 0 (C17; open in
`TODO.md`).**
Answer (2026-10-14): (a), check the specification and the writers first, in
C17, then decide.
Decided (2026-10-18): `spec` reads it, as now (option (c)). The specification
allows it (0 is a multiple of the raster, spec:290); `makeTrapezoid` and
`make_trapezoid` never make one, but MATLAB Pulseq and pypulseq write it when
the times are set on the event, and their timing checks pass it; the C++
reader, MATLAB Pulseq and pypulseq play 0 for it. C17 removes the item of
`TODO.md`. The check also found that MATLAB Pulseq can write a gradient
amplitude of NaN (`makeTrapezoid` with `FlatArea` 0 and `FlatTime` 0), and
that `gradient_peaks` counts the amplitude of such an event, which plays 0, as
a peak: task C18.
- **The evidence:** `spec` reads one today, and its event has all its points
  at one time. B6 (#138) makes the measurements handle it. Not yet checked:
  what the specification says, and whether pypulseq or MATLAB Pulseq write
  one.
- **The options:**
  - (a) check those first, in C17, then decide. Recommended.
  - (b) reject it now, as D3.
  - (c) read it, as now.

### The documents

**Q11. The links of `findings-for-pulseq-checks.md` (D1).**
Answer (2026-10-14): (a), relative links.
- (a) relative links, with the document describing `main` and the tag
  pinning it at a release. Recommended.
- (b) a pinned commit, updated in every PR that changes what the document
  describes.

**Q12. The version and the dependency of pulseq-cpp-siemens (D2).**
Answer (2026-10-14): (a), the same version (`0.1.0rc7`) and
`pulseq-analysis>=0.1.0rc7,<0.2`. This settles the "decided at release" of
2026-10-13.
Refined (2026-10-15): the requirement is the extra `analysis`
(`pulseq-cpp-siemens[analysis]`), not a dependency, because neither package is
on PyPI and the wheel tests run without pulseq-analysis.
- **The evidence:** the user decided on 2026-10-13 that this is "decided at
  release". `CHANGELOG.md` and `docs/migration.md` promise the same version
  and `>=0.1.0rc7,<0.2`. The protocol version ties the two distributions
  together.
- **The options:**
  - (a) the same version as pulseq-analysis (`0.1.0rc7`), and
    `pulseq-analysis>=0.1.0rc7,<0.2` in the plugin's `pyproject.toml`.
    Recommended for rc7.
  - (b) its own version, with the documents saying "decided at release".

**Q13. The version of an analysis after the changes of rc7 (D7).**
Answer (2026-10-14): (a), keep 1 until 0.1.0.
- **The evidence:** the meaning of the axes changed in rc7 (rotations and the
  session), and so did the tie text. Every analysis is still version 1, and
  `docs/usage.md:686-688` says that a change of the contract raises it.
  pulseq-checks may store the version.
- **The options:**
  - (a) keep 1, and say in `docs/migration.md` that versions count from
    0.1.0. Recommended.
  - (b) raise the versions of the analyses whose contract changed.

**Q14. `spec` and a folder or a binary Pulseq file (D8).**
Answer (2026-10-14): (a), one gate in `read_seqfile` for every interpreter.
- (a) one gate in `read_seqfile` for every interpreter: a folder, the binary
  magic, and the version give `NotSupported`. Recommended. It matches what
  `cpp-siemens` does, and removes the duplicated gate.
- (b) document the difference between the two interpreters.

**Q15. What replaces each "pypulseq-issues" citation (D11).**
Answer (2026-10-14): (a), the behaviour with the file and line of the pinned
fork, in every file, the plans and the reviews too.
- **The evidence:** 66 lines in 18 files. Of the drafts, 12 is cited 32 times
  (pypulseq draws a line across a long gap); the others cited are 11, 09, 13,
  10, 04 and 03.
- **The options, for each citation:**
  - (a) the behaviour, with the file and line of the pinned pypulseq fork.
    Recommended.
  - (b) an upstream issue or PR, where one is filed.
  - (c) the behaviour alone.
- **Also to decide:** whether the plans and the reviews are edited too.
  "Gone from everything" says yes; git history keeps the old text either
  way.

### The API

**Q16. `__all__` (A0).**
Answer (2026-10-14): (a), an `__all__` in every public module.
- **The evidence:**
  - 11 public modules have no `__all__`.
  - `NO_GRADIENTS` is importable from 5 modules; the documents give only
    `seq_index.NO_GRADIENTS`.
  - `test_interface.py` checks names with `hasattr`, so it misses
    `pns_levels.SAFE_FIELDS`.
- **The options:**
  - (a) every public module has an `__all__`, which is the public contract,
    and `test_interface.py` checks it. Recommended. A re-export leaves the
    `__all__` of the module that re-exports it.
  - (b) as now.

**Q17. The PNS hardware (A1).**
Answer (2026-10-14): (A), `hardware: SafeHardware` only.
- **The evidence:**
  - Today it is `hardware=(struct, label)`, where `struct` is a
    `SafeHardware` or pypulseq's namespace.
  - `SafeHardware.name` repeats the label.
  - `SafeAxis` requires `stim_thresh`, which the model does not use.
  - `CHANGELOG.md` step 6 says to pass a `SafeHardware`, which raises
    `TypeError`.
  - 182 lines use `hardware=`.
  - The hardware is converted three times in each call (4.6).
- **The options:**
  - (A) `hardware: SafeHardware` only, with the label `hardware.name`.
    Recommended.
    - `hardware_from_asc(path)` returns a `SafeHardware`, so its callers do
      not change.
    - A namespace is given as `SafeHardware.from_namespace(ns, "label")`.
    - One validation, at construction.
    - `stim_thresh` stays required, as in pypulseq's `safe_hw_check`.
  - (B) also accept the pair: two forms.
  - (C) keep the pair, and fix only the CHANGELOG.

**Q18. `window` of `gradient_peaks` (A2).**
Answer (2026-10-14): (a), `window` becomes `range_s`; `window_s` stays.
- **The evidence:** `window` is a time range in `gradient_peaks`, and
  `window_s` is the length of the Hann window in `gradient_spectrum`.
  pypulseq calls them `time_range` and `window_width`, and the result field
  is `GradientPeaks.range_s`.
- **The options:**
  - (a) `window` becomes `range_s`, to match the field. About 100 lines.
    Recommended.
  - (b) also `window_s` becomes `window_width_s`. About 180 lines.
  - (c) keep both, and document them.

**Q19. The names of the axes (A3).**
Answer (2026-10-14): (a), the sampler takes `"x"`, `"y"` and `"z"`.
- **The evidence:**
  - The results use `"x"`, `"y"` and `"z"`.
  - `GradientSampler.sample` and `block_samples` take `"gx"`, `"gy"` and
    `"gz"`.
  - The protocol's `gradient_points` takes 0, 1 and 2.
  - The block table keeps the file's columns, `gx`, `gy` and `gz`.
- **The options:**
  - (a) the sampler takes `"x"`, `"y"` and `"z"`, as the results do. The
    protocol keeps the index into its (n, 3) arrays, and the table keeps the
    file's names. About 45 lines. Recommended.
  - (b) accept every form.
  - (c) document the three roles.

**Q20. A peak time with no peak (A4).**
Answer (2026-10-14): (a), None in both.
- **The evidence:** `GradientPeaks` gives a time of 0.0, with `peak_block`
  None, when the largest value is 0. `PnsLevels` gives None. 150 lines use
  `peak_time_s`.
- **The options:**
  - (a) None in both, whenever the block is None. Recommended.
    `GradientPeaks` has no series, so no JSON changes.
  - (b) 0.0 in both, which puts 0.0 into the JSON of the PNS.

**Q21. `model.TIME_TOLERANCE` (A5).**
Answer (2026-10-14): (a), `RF_TIME_SHAPE_TOLERANCE`.
- **The evidence:** `model.TIME_TOLERANCE` is 1e-6 RF rasters, and
  `seq_utils.TIME_TOLERANCE` is 1e-9 s. The model's is used only in
  `model.py`.
- **The options:**
  - (a) rename it `RF_TIME_SHAPE_TOLERANCE`. 7 lines. Recommended.
  - (b) make it private.

**Q22. One way to make each object (A6).**
Answer (2026-10-14): (a), one function for each.
- **The evidence:**
  - `gradient_sampler(snap)` and `GradientSampler(snap)` are the same.
  - `Snapshot(data)` and `load` both make a snapshot, and `Snapshot(data)`
    gives no `ScannerSettingWarning`.
  - `spec.read_spec(path)` and `read_seqfile(path)` are the same.
- **The options:**
  - (a) the classes stay public as types; one function makes each. `load`
    also takes a `SequenceData`, `Snapshot(...)` is not documented as a
    constructor, and `read_spec` becomes private. Recommended.
  - (b) remove `gradient_sampler`, and use the class.
  - (c) document the overlaps.

**Q23. Microseconds in `Decoding.gradients_at` (A7).**
Answer (2026-10-14): (b), seconds in the protocol (`time_s`); microseconds
only in the plugin's low-level `cs.Sequence.gradients_at`. Protocol version 1
changes before its first release, as for `gradient_variants` (D1 of
`docs/plans/cpp-siemens-review-fixes.md`).
- **The evidence:** the protocol takes `time_us`, the reader's unit, because
  the reader's times are whole microseconds. The rest of the API is in
  seconds.
- **The options:**
  - (a) keep microseconds, and state it as the one exception. Recommended.
  - (b) seconds in the protocol, and microseconds only in `cs.Sequence`. That
    changes protocol version 1 before 0.1.0.

**Q24. The defaults that the caller does not see (A8).**
Answer (2026-10-14): (a), the method defaults stay, and `docs/usage.md` states
the rule.
- **The evidence:**
  - The spectrum's maximum frequency, window and oversampling are pypulseq's
    defaults.
  - The bins of `pns_levels` have a default `bin_s`.
  - The session is neutral, and the interpreter is `spec`.
  - Each is recorded on the result.
  - The rule "explicit inputs" is about target data (the scanner, the coil
    and the nucleus), which is why `hardware` has no default.
- **The options:**
  - (a) keep the method defaults, and state the rule in `docs/usage.md`:
    target data is necessary, and method parameters have documented
    defaults, recorded on the result. Recommended.
  - (b) make the three parameters of the spectrum necessary.
  - (c) make all of them necessary.

### The tests

**Q25. The tests of code outside this repository (T9).**
Answer (2026-10-14): (b), prune selectively.
- **The evidence:**
  - `test_cpp_oracle_sanitized.py` calls no package code. Its literal test
    compares a set with a set, and the plugin's `test_driver_parity.py`
    compares the plugin with the sanitized build for each fixture.
  - `test_cpp_oracle.py:184-234` characterise the reader. Two of them show
    that the harness works, so that no comparison passes as one rejection
    against another.
  - The `strtod` test is a precondition of another test.
  - `test_prediction_propagates_an_error` tests Python.
  - The hash tests of `AxisResult` and `SafeHardware` guard a documented
    contract.
- **The options:**
  - (a) remove them all.
  - (b) Recommended:
    - keep one smoke test of the harness;
    - keep the sanitized module, but not its literal test, as a
      characterisation of the build;
    - merge the `strtod` test into the test that needs it;
    - remove `test_prediction_propagates_an_error`;
    - keep the hash tests.
  - (c) remove only the literal test.

**Q26. The MATLAB oracle in CI (T10).**
Answer (2026-10-14): (b), a separate workflow.
- **The evidence:**
  - The `ci` shell lacks it, so 150 root tests and one plugin test skip in
    CI, and `TESTS.md` says it "describes each check that CI runs".
  - Octave's closure is 2.5 GiB, from cache.nixos.org.
  - The tests take 22 s locally. The estimate is 1 to 3 more minutes for
    each CI run, on top of the 4.5 now; this was not measured on a runner.
  - T4 and T14 add value only where MATLAB runs.
- **The options:**
  - (a) add it to the `ci` shell.
  - (b) a separate workflow, run only when the decoding, the fixtures or the
    oracle change, so that the required check stays as fast as now.
    Recommended.
  - (c) keep CI as it is, and say in `TESTS.md` which modules CI skips.

**Q27. Oracles whose input is independent of the package (T12).**
Answer (2026-10-14): (a), correct the claims only (T6). T12 is dropped.
- **The evidence:**
  - The oracles take the package's `played_gradients`, so they cannot find
    an error of the decoding.
  - The decoding is tested on its own: by hand, against the C++ reader in
    CI, and against MATLAB. Two mutations of the decoding were both caught.
  - pypulseq's reading of the written file gives the same oracle peaks, with
    a difference of 0.0, but makes the oracle tests depend on pypulseq's
    reader and its known differences.
- **The options:**
  - (a) correct the claims only (T6).
  - (b) also the input from pypulseq's reading, where pypulseq reads the
    file. Recommended only if the user wants defence in depth: no mutation
    yet shows a gap.

**Q28. An independent reference for SAFE (T13).**
Answer (2026-10-14): (a), the original SAFE under Octave as an oracle. T13
checks its licence first, pins it as a source of the flake, and runs in the
workflow of T10.
- **The evidence:**
  - The filter is compared only with the fork it was ported from.
  - The "levels" golden values come from the package's own pipeline, so
    they pin it, and do not test it.
  - The original SAFE package (github.com/filip-szczepankiewicz/safe_pns_prediction)
    is what MATLAB Pulseq's `calcPNS` calls.
- **The options:**
  - (a) the original SAFE under Octave as an oracle: a new source in the
    flake (its licence to check), and a dump script. It runs only where
    Octave runs (Q26).
  - (b) a long test of the filter against a plain loop of its recurrence, and
    remove the "levels" golden values. Recommended as the first step.
  - (c) as now, with the limit documented.

**Q29. The plugin's measurement tests on files that `spec` reads (T11).**
Answer (2026-10-14): (a), move them to the root, through `spec`.
- **The evidence:**
  - The plugin's file says it holds only sequences that `spec` rejects, but
    it runs gre, spin_echo, empty, arbitrary_gradient and border.
  - So the root has no window comparison on sequences that repeat events,
    and misses the mutation `peak_credit_first_of_event`.
- **The options:**
  - (a) move them to the root, through `spec`. Recommended.
  - (b) copy them to the root, and keep the plugin's.
  - (c) correct the docstring only.

**Q30. The "later block" relaxation of the peaks oracle (T7).**
Answer (2026-10-14): (a), remove it.
- **The evidence:** it was for the rounding of absolute times. The oracle now
  builds its points with the same sums as the package, the relaxation fired
  0 times in 3066 calls, and it hides a mutation.
- **The options:**
  - (a) remove it. Recommended.
  - (b) keep it, if it was part of the choice of 2026-09-28 on the
    tolerances.

## 10. When this plan is done

- Delete this file in the last PR of the plan. Its lasting content is in the
  documents of each task, in `CHANGELOG.md`, and in `docs/migration.md`.
- Remove its line from `README.md`, and the item of `TODO.md` that points to
  the review's open findings.
- Mark section 7 of the review: what each PR fixed.
