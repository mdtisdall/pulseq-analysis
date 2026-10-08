# Code review, 2026-10-05

A review of the whole package at commit `dfdb044`, after the fixes of
[the review of 2026-10-04](2026-10-04-code-review.md) (each task of
`docs/plans/review-fixes.md` has merged, except the release, task 2.6). It
looks for things that are incorrect, mis-documented, duplicative or
inefficient, and for parts of the API that do not fit the goals of the
project. The line numbers are of that commit.

Method: a read of every module of `src/pulseq_analysis/`; a check of
`docs/usage.md`, `README.md`, `CHANGELOG.md`, `TESTS.md` and the docstrings
against the code; small scripts against the pinned pypulseq fork
(`a74ab06`); and 31 single-line mutations of a copy of `src/` to find tests
that cannot fail. The findings marked *reproduced* were run against the fork.

At this commit, `nix develop --command scripts/check` passes: ruff, 839
tests, the `TESTS.md` check (256 entries) and shellcheck.

## 1. Correctness

1. **`bin_s` loses one sample for about half of the values on the raster**
   (*reproduced*). `bin_samples_for` computes `math.floor(bin_s / dt)`
   ([pns_levels.py:138](../../src/pulseq_analysis/pns_levels.py#L138)). The
   division is not exact, so `bin_s=0.01` at the 10 us raster gives 999
   samples, not 1000. For `bin_s = k * 10 us`, `k = 1 .. 2000`, 1047 values
   give `k - 1` samples. A test keeps the floor (the mutation `floor` to
   `round` fails `test_analyses::…passes_bin_s_on`), and the docstring says
   "rounded down". Fix: a tolerance before the floor, as the raster check
   uses (`ON_RASTER_TOLERANCE`).

2. **A bad hardware struct gives different errors** (*reproduced*).
   `_require_hardware`
   ([pns_levels.py:143](../../src/pulseq_analysis/pns_levels.py#L143)) checks
   only the shape of the pair. For a struct without `stim_thresh`:

   - `pns_levels_for` raises `AttributeError` from `_hardware_key`
     ([pns.py:51](../../src/pulseq_analysis/pns.py#L51)), before the model;
   - `pns_levels` raises `ValueError` from pypulseq's `safe_hw_check`, in the
     first chunk.

   A struct with `a1 + a2 + a3 != 1` gives a result for a sequence with no
   gradient event, and `ValueError` for a sequence with gradients. Fix:
   call `safe_hw_check` in `_require_hardware`, so that each entry point
   refuses the same structs before it reads the sequence.

3. **`gradient_peaks` checks `window` after it reads the events**
   (*reproduced*). `_event_values`
   ([grad_peaks.py:655](../../src/pulseq_analysis/grad_peaks.py#L655)) reads
   one block for each unique gradient event before the checks of `window`
   (line 663). A bad window costs that read. The other functions of the
   package check their arguments before they read the sequence. Only the
   check against `total_duration` needs the index.

4. **A window past the end within the tolerance gives a reversed range**
   (*reproduced*). For a sequence of length `T`,
   `window=(T + 5e-10, T + 9e-10)` passes the check, and the clip at
   [grad_peaks.py:675](../../src/pulseq_analysis/grad_peaks.py#L675) gives
   `range_s == (0.0060000005, 0.006)`: the start is after the end. The
   result has `reason == NO_GRADIENTS_IN_WINDOW`, so the effect is small.

5. **The junction step of a delayed event has the time of the block start**
   (*reproduced*). For an event with `delay > 0` and a first value that is
   not 0 (pypulseq's `add_block` accepts it), the step from 0 is at
   `start + delay`. `_junction_steps`
   ([grad_peaks.py:303](../../src/pulseq_analysis/grad_peaks.py#L303)) gives
   it the time `start_s`. Minor.

## 2. Efficiency

1. **Each analysis reads each unique gradient event again**
   (*reproduced*). `gradient.peaks`, `gradient.blocks`, `gradient.spectrum`
   and `pns.safe.levels` each call `get_block` one time for each unique
   gradient event (`seq_index.grad_events`). On a sequence with 50 unique
   events, the four analyses made 200 calls. `gradient_peaks` keeps nothing,
   so each call with a window reads the events again. `_EventData`
   ([grad_peaks.py:245](../../src/pulseq_analysis/grad_peaks.py#L245)) and
   `GradientSampler`
   ([sampling.py:45](../../src/pulseq_analysis/sampling.py#L45)) also hold
   the same points of each event. Proposal: keep the points of the events
   in `_kept`, beside the index, and build both from them.

2. **A window of `gradient_peaks` costs O(N).** `_range_result` calculates
   `_junction_steps` over all the blocks of the file for each axis
   ([grad_peaks.py:566](../../src/pulseq_analysis/grad_peaks.py#L566)), and
   the masks of lines 474 to 477 are of all the blocks. A caller with many
   short windows pays this for each window.

## 3. Mis-documentation

- **The install line of `README.md` does not work with its example**
  (*reproduced*). `README.md` line 29 pins `@v0.1.0rc5`, and the example
  imports `asc.hardware_from_asc`, which is not in that tag. A user who
  follows the README gets `ImportError`. `pyproject.toml` has the version
  `0.1.0rc5`. Task 2.6 of `docs/plans/review-fixes.md` (the release) fixes
  both.
- **`CHANGELOG.md` has no entry for PRs #17 to #32**, which include changes
  that break callers: the rename to `grad_peaks`, the removed helpers and
  `PNS_LIMIT`, the necessary hardware, `bin_s`, `FrozenDict` and the
  read-only results. Task 2.6 writes it.
- **The rule of equality is wrong in three places.**
  - `docs/usage.md` lines 64 to 67 say that `Series` compares a dict with
    its keys in order. `Series` does not count the order of the keys of
    `meta` ([series.py:267](../../src/pulseq_analysis/series.py#L267)); the
    class docstring says so.
  - The docstring of `_equality`
    ([_equality.py:7](../../src/pulseq_analysis/_equality.py#L7)) says that
    `Series` uses `fields_equal`. It has its own `__eq__`. Lines 1 and 2 name
    only `PnsLevels` and `GradientSpectrum`; `SequenceIndex` and
    `BlockGradientValues` also use it.
  - `docs/usage.md` lines 67 to 69 say that `GradientPeaks` has the `==` of
    `dataclasses`, which is true, but `hash()` of a `GradientPeaks` raises
    `TypeError`, because its `FrozenDict` fields are not hashable. The other
    results set `__hash__ = None` and the documentation says so.
- `docs/usage.md` lines 58 and 59 give the key of `pns_levels_for` without
  `bin_s` (lines 224 and 263 give it).
- The `description` of `pyproject.toml` names "waveforms". The package gives
  no waveform.
- The docstring of `pns_levels_for`
  ([pns.py:63](../../src/pulseq_analysis/pns.py#L63)) says "the same rules
  and the same default" without the name of the function that it compares
  with.
- `series.py` gives its contract by references to `Finding` of
  pulseq-checks and to plan documents of other repositories (lines 1, 86,
  117, 123 and 144). PRs #31 and #32 removed references of this kind from
  the tests.

## 4. Duplication

- **Two rules of equality.** `Series.__eq__`
  ([series.py:251](../../src/pulseq_analysis/series.py#L251)) and
  `_equality.values_equal` differ on the order of dict keys. PR #30 had the
  aim of one rule.
- **`pns.py` is only the cache of `pns_levels`.** It imports the private
  `_require_hardware` and `_validated_thresholds` of `pns_levels.py`, and
  the arguments are checked two times on each call that is not kept. One
  module would remove the private imports.
- **Constants in more than one place:** `SAFE_FIELDS` and `_HW_FIELDS`
  ([pns_levels.py:374](../../src/pulseq_analysis/pns_levels.py#L374),
  [567](../../src/pulseq_analysis/pns_levels.py#L567)); the tuples of the
  axis names, five times (`seq_index`, `sampling`, `grad_peaks`,
  `pns_levels` two times); and the time tolerance 1e-9 as `pp.eps` in
  `sampling` and as `TIME_TOLERANCE` in `seq_utils`.
- `scripts/check_tests_md.py` (`javascript_tests`, line 94) reads the
  JavaScript tests of `tests/js`. This repository has no such directory.

## 5. Tests

For 14 of the 31 mutations, all the tests passed. 3 of them cannot change
the behaviour. The other 11 are gaps; each, except the last, was shown with
an input that gives a different result:

- **The stamp of `_kept`.** When the check of `block_events`,
  `block_durations`, `grad_library` or the number of blocks is removed
  ([_kept.py:47](../../src/pulseq_analysis/_kept.py#L47) to 50), all the
  tests pass. The one test of a new object reads a file, which replaces the
  three objects together. A new `seq.block_durations` alone, or a block
  removed from the middle, shows each gap.
- **`_IntervalFinder`.** With `>=` for the tie rule
  ([pns_levels.py:489](../../src/pulseq_analysis/pns_levels.py#L489)), or
  without `a == 0` in the join of two chunks (line 487), all the tests pass.
  Without `a == 0`, two runs with a gap between them become one interval.
- **`_cast_outward`.** With `>=` for `>`
  ([pns_levels.py:557](../../src/pulseq_analysis/pns_levels.py#L557)), a bin
  of zeros gets a `level_min` below 0, and all the tests pass.
- **`_kept_samples`.** With `<` for `<=`
  ([sampling.py:151](../../src/pulseq_analysis/sampling.py#L151)), the sample
  at the last point of an event is 0, and all the tests pass.
- **The tie of a junction step and a segment of one block**
  ([grad_peaks.py:587](../../src/pulseq_analysis/grad_peaks.py#L587)). With
  `<` for `<=`, the slew time is that of the segment, and all the tests
  pass.
- **The tolerance of `keep_n`**
  ([grad_spectrum.py:180](../../src/pulseq_analysis/grad_spectrum.py#L180)).
  Without `+ 1e-6`, all the tests pass. At a 4 us raster with
  `window_s=0.01`, the bin of 2000 Hz is 2000.0000000000002 Hz, and the
  result loses it. All the tests use the 10 us raster.
- **Weak checks.** Most cases of
  `test_gradient_spectrum_refuses_bad_arguments` have `match=None`, so a
  different `ValueError` passes them.

## 6. The API and the goals of the project

The README says that an analysis takes a sequence and *explicit* physical
parameters, and gives values with no limit and no finding.

1. **A runner cannot know that `hardware` is necessary.**
   `AnalysisSpec.params`
   ([analyses.py:73](../../src/pulseq_analysis/analyses.py#L73)) gives only
   the names. With the hardware necessary, `compute(seq)` of
   `pns.safe.levels` raises `TypeError`, and the spec does not say which
   parameter is necessary, or the default of the others.
2. **The analyses do not agree on parameters.** `pns.safe.levels` gives all
   the arguments of its function. `gradient.peaks` has no `window`, and
   `gradient.spectrum` has only the defaults. Through the registry, a caller
   cannot get a window or a different spectrum.
3. **The kept results do not agree.** `sequence_index` is only kept.
   `pns_levels` and `pns_levels_for`, and `gradient_spectrum` and
   `gradient_spectrum_for`, are pairs. `gradient_peaks` is never kept. The
   suffix `_for` does not say "kept". `GradientPeaks.whole_rms_hz_per_m`
   exists so that a caller does not make a second call, which is a cost
   only because nothing is kept (section 2, item 1).
4. **The default bin is the plot of one caller.** `BIN_S = 10.0 / 1624`
   ([pns_levels.py:47](../../src/pulseq_analysis/pns_levels.py#L47)) is the
   bin of the 10 s view of pulseq-reports. The argument `bin_s` removed the
   constants of that plot, but not the default. A round default fits the
   goals better, after the fix of section 1, item 1.
5. **`seq.index` makes the inside of the package an interface.** The
   analysis gives `SequenceIndex` with version 1, so its dense numbers and
   its rule for the dtype (uint8, uint16 or uint32) are a contract for
   callers.
6. **Each `PnsLevels` holds 24 values of the `.asc` file.** `PnsLevels.hw`
   ([pns_levels.py:108](../../src/pulseq_analysis/pns_levels.py#L108)) has
   eight fields for each axis. The package says that these files are
   confidential, and a caller that keeps or pickles a result keeps them.
   `to_series` does not write them.
7. **`Series` accepts coordinates that are not valid** (*reproduced*). It
   accepts a `coord_start` that is NaN or an infinity, a `coord_end` before
   `coord_start`, and a run with `end < start`
   ([series.py:202](../../src/pulseq_analysis/series.py#L202) to 235).
8. **"No result" has two forms.** For a sequence with no gradient event,
   `GradientSpectrum.axes` is empty
   ([grad_spectrum.py:166](../../src/pulseq_analysis/grad_spectrum.py#L166)),
   and `PnsLevels.axis_peaks_hz_per_t` has `x`, `y` and `z` at 0.

## 7. Order of the fixes

1. The bin of `bin_s` (section 1, item 1), before a change of the default
   (section 6, item 4).
2. One check of the hardware (section 1, item 2).
3. The tests of section 5.
4. The release `0.1.0rc6` (task 2.6 of `docs/plans/review-fixes.md`), which
   corrects the README and `CHANGELOG.md`.
5. The documentation errors and the duplication of sections 3 and 4.
6. The events kept with the index (section 2, item 1), and then the choices
   of section 6.

## 8. Status at 0.1.0rc6

Written on 2026-10-07, for the release `0.1.0rc6`. The numbers of the items are
those of sections 1 to 6 of this review (the bullets of sections 3, 4 and 5 are
numbered in their order). The tasks are those of
`docs/plans/second-review-fixes.md` (the second plan). The names in sections 1
to 7 are those of `dfdb044`. This section uses the names of `0.1.0rc6` where a
name has changed (`pns_levels` for `pns_levels_for`, `gradient_spectrum` for
`gradient_spectrum_for`). A name of a test is the name on `main` at the release.

The third plan and the fourth plan (`docs/plans/third-review-fixes.md` and
`docs/plans/fourth-review-fixes.md`) changed some of this code again. Where a
later change makes the first fix different, the table says so.

The pull requests of the second plan:

| Task | PR | Branch |
|---|---|---|
| 1.1 | #35 | `fix/second-review-test-gaps` |
| 1.2 | #36 | `fix/pns-bin-snap` |
| 1.3 | #37 | `fix/pns-hardware-check` |
| 1.4 | #38 | `fix/gradient-peaks-window` |
| 1.5 | #39 | `docs/second-review-doc-errors` |
| 1.6 | #41 | `refactor/second-review-duplicates` |
| 1.8 | #42 | `chore/pypulseq-pin-2` |
| 1.9 | #43 | `feature/require-signature` |
| 1.7 | #44 | `refactor/kept-event-points` |
| 2.1 | #45 | `refactor/one-kept-entry-point` |
| 2.2 | #46 | `refactor/window-cost` |
| 2.3 | #47 | `feature/analysis-parameters` |
| 2.4 | #48 | `feature/consistent-result-shapes` |
| 2.5 | task 2.7 of the fourth plan, this release | `docs/release-0.1.0rc6` |

Tasks 1.8 and 1.9 (the pin of pypulseq and the refusal of a sequence with no
`[SIGNATURE]` hash) were added to the plan after wave 1, so no finding of this
review names them. The pull request of the plan is #34, and its amendment is
#40.

The status is "done", "done in another way" (the result differs from the
proposal of this review) or "not changed" (with the reason).

### 8.1 Section 1: correctness

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 1.1 | `bin_s` loses one sample for about half of the values on the raster | Done. `bin_samples_for` takes the nearest whole number when `bin_s / dt` is within `ON_RASTER_TOLERANCE` of it, and the floor otherwise. The default `bin_s` is 5 ms, which is 500 samples at 10 us. `bin_s=10.0 / 1624` still gives the 615 samples of `0.1.0rc5`. Tests: `test_bin_samples_for_gives_the_whole_samples_of_a_bin_s_on_the_raster` and `test_bin_samples_for_matches_the_formula`. | 1.2, #36 |
| 1.2 | A bad hardware struct gives different errors | Done. `_check_hardware` refuses a missing axis or field (`ValueError` that names the field), a field that is not a finite real number, a `stim_limit` that is not above 0, and an `a1 + a2 + a3` that is not within 0.001 of 1, before the sequence is read, also for a sequence with no gradient event. Tests: `test_pns_levels_refuses_a_bad_struct_before_the_snapshot_type`, `test_pns_levels_refuses_a_bad_struct_for_a_sequence_without_gradients` and `test_pns_levels_refuses_a_sum_of_the_a_fields_that_is_1_005`. | 1.3, #37 |
| 1.3 | `gradient_peaks` checks `window` after it reads the events | Done. `gradient_peaks` checks the form and the numbers of `window` first. Test: `test_gradient_peaks_refuses_a_bad_window_before_the_snapshot_type`. | 1.4, #38 |
| 1.4 | A window past the end within the tolerance gives a reversed range | Done. The range is clipped to `[0, T]`, so its start is never after its end, and a range of length 0 gives `NO_GRADIENTS_IN_WINDOW`. Test: `test_a_window_outside_the_sequence_within_the_tolerance_gives_an_empty_range`. | 1.4, #38 |
| 1.5 | The junction step of a delayed event has the time of the block start | Done. The step had the time `start + delay` (decision D4 of the second plan). The waveform model of task 2.1 of the third plan (#58) later replaced this rule: a first value that is not 0 after a long gap now has a ramp from 0 in the block of its event (`test_a_first_value_that_is_not_zero_after_a_delay_has_a_ramp_from_zero_in_its_block`), and the review of 2026-10-06 (1.1) gives the reason. | 1.4, #38 (rewritten by #58) |

### 8.2 Section 2: efficiency

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 2.1 | Each analysis reads each unique gradient event again | Done. `_events.event_points` reads each unique gradient event one time for each sequence, and keeps its points. `GradientSampler` and the per-event values of `grad_peaks` use them and call no `get_block`. Test: `test_the_measurements_of_one_sequence_read_each_unique_gradient_event_once`. Each public measurement keeps its result (task 2.1, #45). Since #80 the points are kept on the snapshot. | 1.7, #44 (and 2.1, #45) |
| 2.2 | A window of `gradient_peaks` costs O(N) | Done. The end of each block and the junction steps are kept, and `_range_result` finds the blocks of the range with `np.searchsorted`. 1000 windows of one TR on 500,000 blocks took 0.21 s, not 16.2 s. The review of 2026-10-06 (2.1) found an O(K) term in a window, and task 1.6 of the third plan (#56) removed it. Test: `test_a_window_does_not_calculate_the_values_over_all_the_blocks_again`. | 2.2, #46 (and #56) |

### 8.3 Section 3: mis-documentation

| Finding | Status | Task / PR |
|---|---|---|
| The install line of `README.md` pins `v0.1.0rc5`, and its example does not work with that tag | Done by the release. `README.md` pins `v0.1.0rc6`, and `pyproject.toml` has the version `0.1.0rc6`. | Task 2.7 of the fourth plan, this release |
| `CHANGELOG.md` has no entry for PRs #17 to #32 | Done by the release. `CHANGELOG.md` has the entry `0.1.0rc6` for the work of the four plans. | Task 2.7 of the fourth plan, this release |
| The rule of equality is wrong in three places (`docs/usage.md` on `Series`, the docstring of `_equality`, and the hash of `GradientPeaks`) | Done. `Series` now uses `fields_equal` (so the order of the keys of `meta` counts, as for each other dict), and the docstring of `_equality` and section 5 of `docs/implementation.md` (which holds the rule since the split of `docs/usage.md`) say so (#39, #41). `GradientPeaks` compares by value and is not hashable, as the other results with a dict (decision D16: `test_gradient_peaks_of_two_equal_computations_are_equal_and_not_hashable`). `@value_dataclass` has the rule in one place (#64). | 1.5, #39. Also #41, #48, #64 |
| `docs/usage.md` lines 58 and 59 give the key of `pns_levels_for` without `bin_s` | Done. | 1.5, #39 |
| The `description` of `pyproject.toml` names "waveforms" | Done. It reads: "Derived values of a Pulseq sequence: the block table, gradient peaks, SAFE PNS and the gradient spectrum". | 1.5, #39 |
| The docstring of `pns_levels_for` says "the same rules and the same default" with no name | Done by a removal. `pns_levels_for` and the module `pns` are gone (#45), so the docstring is gone. | 2.1, #45 |
| `series.py` gives its contract by references to `Finding` of pulseq-checks and to plan documents of other repositories | Done. `series.py` states the rules of `name` and `meta` in place. | 1.5, #39 |

### 8.4 Section 4: duplication

| Finding | Status | Task / PR |
|---|---|---|
| Two rules of equality (`Series.__eq__` and `values_equal`) | Done. `Series` uses `_equality.fields_equal`. `series._same_value` is gone. | 1.6, #41 (and #64) |
| `pns.py` is only the cache of `pns_levels` | Done. `pns.py` is removed. `pns_levels` keeps its own results, and no module imports a private name of another. | 2.1, #45 |
| Constants in more than one place: `SAFE_FIELDS` and `_HW_FIELDS`, the axis tuples, `pp.eps` and `TIME_TOLERANCE` | Done. `_HW_FIELDS` is `SAFE_FIELDS` without `stim_thresh`. One pair of axis tuples, `seq_utils._AXES` and `seq_utils._GRAD_COLUMNS` (the names `AXES` and `GRAD_COLUMNS` in #41, made private by #85). `sampling` uses `TIME_TOLERANCE`. | 1.6, #41 |
| `scripts/check_tests_md.py` reads the JavaScript tests of `tests/js` | Done. The reader of JavaScript tests is removed. | 1.6, #41 |

### 8.5 Section 5: tests

Each mutation of the plan (N1 to N10) failed its new test when #35 merged.

| Finding | Status | Task / PR |
|---|---|---|
| The stamp of `_kept` (N1 to N4) | Done, and then moot. #35 added one test for each part of the stamp (`tests/test_kept.py`). Task 2.1 of the fourth plan (#80) removed the stamp and the tests with it: a snapshot has no stamp, because its sequence does not change. | 1.1, #35. Moot since #80 |
| `_IntervalFinder`: `>=` for the tie rule (N6), and no `a == 0` in the join of two chunks (N7) | Done. Tests: `test_interval_finder_tie_across_a_chunk_boundary_keeps_the_earlier_peak_sample` and `test_interval_finder_gap_at_the_start_of_a_chunk_does_not_join_the_open_run`. | 1.1, #35 |
| `_cast_outward`: `>=` for `>` (N8) | Done. Test: `test_cast_outward_keeps_zero_at_zero`. | 1.1, #35 |
| `_kept_samples`: `<` for `<=` (N5) | Done. Test: `test_the_sample_at_a_last_point_that_is_many_steps_in_has_the_value_of_that_point`. | 1.1, #35 |
| The tie of a junction step and a segment of one block (N9) | Done. Test: `test_junction_step_equal_to_a_segment_slope_of_its_block_takes_the_credit`. | 1.1, #35 |
| The tolerance of `keep_n` (N10) | Done. Test: `test_gradient_spectrum_keeps_the_bin_at_the_maximum_frequency_on_a_4_us_raster`. | 1.1, #35 |
| Weak checks: `match=None` in `test_gradient_spectrum_refuses_bad_arguments` | Done. Each case has a `match=`. | 1.1, #35 |

### 8.6 Section 6: the API and the goals of the project

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 6.1 | A runner cannot know that `hardware` is necessary | Done. `AnalysisSpec` has `necessary` (the parameters with no default) and `defaults` (the others, with their values), checked against `params`. `pns.safe.levels` has `necessary=("hardware",)`. Test: `test_the_spec_of_each_analysis_agrees_with_the_signature_of_compute`. | 2.3, #47 |
| 6.2 | The analyses do not agree on parameters | Done. `gradient.peaks` takes `window`, and `gradient.spectrum` takes the three arguments of `gradient_spectrum`, with their defaults. | 2.3, #47 |
| 6.3 | The kept results do not agree (`_for` pairs, `gradient_peaks` never kept) | Done. One public function for each measurement keeps its result: `sequence_index`, `gradient_peaks` (for `window=None`), `block_gradient_values`, `pns_levels` and `gradient_spectrum`. `pns_levels_for`, `gradient_spectrum_for` and the module `pns` are removed. `GradientPeaks.whole_rms_hz_per_m` was then removed (task 2.5 of the third plan, #63), because `gradient_peaks(seq).axes[axis].rms_hz_per_m` costs nothing. | 2.1, #45 (and #63) |
| 6.4 | The default bin is the plot of one caller | Done. The default is 5 ms (decision U3 of the second plan). | 1.2, #36 |
| 6.5 | `seq.index` makes the inside of the package an interface | Not changed in the code. Decision U5: `seq.index` stays in the registry, because pulseq-checks uses it. The layout of `SequenceIndex` (its fields, the dense numbers and the dtype rule) is the contract of `seq.index` version 1, and a change of it raises `spec.version`. | 2.3, #47 |
| 6.6 | Each `PnsLevels` holds 24 values of the `.asc` file | Not changed. pulseq-reports runs the SAFE model again in the browser from `PnsLevels.hw`, so the field stays (fact 5 of the second plan). A result for people outside the site needs a choice of the user (section 9 of the plan, "Later"). | — |
| 6.7 | `Series` accepts coordinates that are not valid | Done. `Series` refuses a `coord_start` that is not finite, an `ENVELOPE` whose `coord_end` is not in range (with the tolerance of float products), and a run with `end < start`. Tests: `test_series_refuses_a_coord_start_that_is_not_finite`, `test_envelope_refuses_a_coord_end_out_of_range` and `test_the_series_of_pns_safe_levels_are_valid`. | 2.4, #48 |
| 6.8 | "No result" has two forms | Done. `GradientSpectrum.axes` of a sequence with no gradient event has the keys `x`, `y` and `z`, each an empty read-only float64 array (`test_no_gradients`). | 2.4, #48 |

### 8.7 What stays

Item 6.5 (the layout of `seq.index`) and item 6.6 (the hardware values in
`PnsLevels.hw`) are not changed, for the reasons in the tables. Neither is a
defect to fix: the first is a documented contract, and the second waits for a
choice of the user.
