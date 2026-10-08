# Code review, 2026-10-04

A review of the whole package at commit `8043553` (`0.1.0rc5`), for things
that are incorrect, mis-documented, duplicative or inefficient, and for parts
of the API that do not fit the goals of the project. The line numbers are of
that commit.

Method: a read of every module of `src/pulseq_analysis/`; a check of
`docs/usage.md`, `README.md`, `CHANGELOG.md` (the `0.1.0rc5` entry), the
docstrings, `pyproject.toml` and `TODO.md` against the code; and a review of
`tests/` and `scripts/`, with 14 single-line mutations of a copy of `src/` to
find tests that cannot fail. The findings marked *reproduced* were run against
the pinned pypulseq fork (`a74ab06`).

At this commit, `pytest` gives 678 passed and `nix develop --command
scripts/check` passes.

## 1. Correctness

1. **The kept results go stale when a file is read into the same `Sequence`
   again** (*reproduced*). The caches key on the sequence object, the number
   of blocks and the last block ID. When file B is read into the object that
   held file A, and B has the same number of blocks:

   - `sequence_index` gives the `end_s` of A (0.0034 s, where B has 0.0074 s);
   - `pns_prediction` and `gradient_spectrum_for` give the values of A;
   - `gradient_limits` uses the block times of A with the events of B.

   Files of one protocol often have the same number of blocks. pypulseq's
   `read` sets a new dict in `seq.block_events` (`Sequence/read_seq.py` line 61
   of the fork), so a key on the identity of that dict (with a reference to it
   in the cache entry) finds a new read. The rule is written three times, so
   one shared helper is the place for the fix:
   [seq_index.py:71](../../src/pulseq_analysis/seq_index.py#L71),
   [pns.py:104](../../src/pulseq_analysis/pns.py#L104),
   [grad_spectrum.py:245](../../src/pulseq_analysis/grad_spectrum.py#L245).

   ```python
   seq = pp.Sequence()
   seq.read("a.seq")
   pns_prediction(seq)
   seq.read("b.seq")  # the same number of blocks as a.seq
   pns_prediction(seq)  # the result of a.seq
   ```

2. **The kept `SequenceIndex` is writable** (*reproduced*). Every measurement
   of a sequence shares one index, and its arrays have `writeable` True. A
   change by one caller (`idx.start_s[...] = ...`) changes each later gradient,
   PNS and spectrum result of that sequence. `PnsLevels` is read-only for this
   reason.

3. **The triple key of `_range_result` can overflow int64.**
   [grad_limits.py:457](../../src/pulseq_analysis/grad_limits.py#L457) computes
   `(gx * base + gy) * base + gz`. Two triples can get one key above about
   2.6 million unique gradient events. `_block_vector_peaks`
   ([grad_limits.py:647](../../src/pulseq_analysis/grad_limits.py#L647)) has
   the safe two-step key. The risk is low; share the code.

4. **A peak of 0 has a peak time.** When all the gradients have the amplitude
   0, `peak_time_s` is `0.5 * dt`, not `None`
   ([pns_levels.py:317](../../src/pulseq_analysis/pns_levels.py#L317)).
   `grad_limits` gives no credited block and the time 0.0 for a largest value
   of 0. Minor.

## 2. Efficiency

1. **`pns_levels` is quadratic in the length of one block** (*reproduced*).
   `_read_block_range`
   ([pns_levels.py:414](../../src/pulseq_analysis/pns_levels.py#L414)) asks
   `block_samples` for each whole block that touches a chunk of 30,000
   samples. Thus a block longer than a chunk is made again, for three axes,
   for each chunk. This includes a delay with no gradient, which gets
   `np.zeros` of its full length
   ([sampling.py:182](../../src/pulseq_analysis/sampling.py#L182)).

   | 120 s of sequence | `pns_levels` |
   |---|---|
   | 1200 blocks of 0.1 s delay, each after a trapezoid | 0.87 s |
   | 1 block of 120 s delay, after a trapezoid | 9.78 s |

   Fix: let `block_samples` take a sample range inside its first and last
   block.

2. **The spectrum calculates about 25 times the bins that it keeps.** At the
   defaults, each spectrogram has 7501 frequency bins and the result keeps
   about 300 ([grad_spectrum.py:199](../../src/pulseq_analysis/grad_spectrum.py#L199)).
   That is about 15 MB for each axis and each chunk. An `rfft` of the windows,
   cut before the `abs`, does not make the bins that are not kept.

## 3. Mis-documentation

- `block_gradient_values` "does not read a block with `get_block`"
  ([grad_limits.py:676](../../src/pulseq_analysis/grad_limits.py#L676),
  `docs/usage.md` line 158), and `gradient_limits` reads blocks only where a
  window edge cuts them ([grad_limits.py:18](../../src/pulseq_analysis/grad_limits.py#L18),
  [575](../../src/pulseq_analysis/grad_limits.py#L575)). Both read one block
  for each unique gradient event, through `_event_values` and `grad_events`.
- References to files that do not exist:
  [seq_index.py:121](../../src/pulseq_analysis/seq_index.py#L121) names
  `waveforms._timed_blocks`; `tests/oracles/blocks.py` line 1 names
  `tests/test_waveforms.py`; a docstring of `tests/test_pns_levels.py` names
  `docs/plans/cards-at-scale.md`.
- [grad_limits.py:116](../../src/pulseq_analysis/grad_limits.py#L116):
  "The four dicts". `BlockGradientValues` has five.
- [grad_limits.py:126](../../src/pulseq_analysis/grad_limits.py#L126): the
  junction step is "0 for the first block". It is not 0 when the first event
  starts at a value that is not 0. `docs/usage.md` gives the correct rule.
- "The largest of each array is the value of `gradient.limits`"
  (`docs/usage.md` line 156,
  [analyses.py:166](../../src/pulseq_analysis/analyses.py#L166)) is false for
  the slew: `gradient_limits` takes the larger of the segment slew and the
  junction step.
- [extensions.py:11](../../src/pulseq_analysis/extensions.py#L11) names two
  callers of `refuse_rotations`. There are four (`block_gradient_values` and
  `gradient_spectrum` also call it).
- `pyproject.toml` line 39 says `calculate_pns` in chunks, and `TODO.md` line 8
  says `calc_pns`. The fork has both; the chunks are in `calc_pns`.
- [series.py:130](../../src/pulseq_analysis/series.py#L130) gives units from
  before `0.1.0rc5` as examples (`"1"`, a fraction, and `"mT/m"`), and
  [series.py:1](../../src/pulseq_analysis/series.py#L1) names "design
  section 4.2", a document of pulseq-checks.
- `docs/usage.md` lines 283-285: `raster_block_lengths` gives one bool for all
  the blocks, not one for each block. The text can be read either way.

## 4. Duplication

- In `grad_limits`: the polyline values (peak, integral, slew) in
  `_event_values` and again in the edge-block loop of `_range_result`; the
  junction steps in `_range_result` and again in `block_gradient_values`; the
  deduplication of the event triples in `_range_result` and again in
  `_block_vector_peaks`, with different overflow handling (section 1, item 3).
- Two equalities with different rules: `Series.__eq__` and `_same_value`
  ([series.py:253](../../src/pulseq_analysis/series.py#L253)) ignore the order
  of the keys of `meta`; `_equality.values_equal` compares dicts with their
  keys in order.
- Three validators of a number with different rules:
  `grad_spectrum._number` (any `numbers.Real`, `TypeError`), `series._real`
  (Python and numpy ints and floats, `TypeError`) and the threshold check of
  `pns_levels` (`int` or `float` only, so `np.float32` and `np.int64` are
  refused, with `ValueError` for a wrong type).
- Constants: `NO_GRADIENTS` in `pns_levels` and in `grad_spectrum`; the axis
  tuples in four modules; `_HW_FIELDS` and `SAFE_FIELDS`; `_has_gradients` of
  `pns_levels` and the same test inline in
  [grad_spectrum.py:163](../../src/pulseq_analysis/grad_spectrum.py#L163).
- Tests: the fixture `write_gradient_asc` in `tests/conftest.py` and again in
  `tests/test_pns_levels.py` line 512, where it overrides the first;
  `tests/scale_sequences.py` copies constants and builders of
  `tests/synthetic.py`, with a reason that is not true now (the file is in
  `tests/`); and `_assert_levels_equal`, `_with_rotation_library`,
  `_waveform_sequence`, `_hardware_for_peak` and `_assert_block_values_equal`
  are each written twice.

## 5. Tests

For 10 of the 14 mutations, all the tests passed. The gaps that matter:

- **The off-raster path with more than one chunk.** When `_read_sampled_range`
  ignores `s0`, all the tests pass, and each chunk of a long off-raster file
  gets the gradients of the first chunk: a wrong PNS result with no error.
  `test_off_raster_block_falls_back_to_sampling` has one chunk.
- **The neighbour events of `GradientSampler.sample`**
  ([sampling.py:121](../../src/pulseq_analysis/sampling.py#L121)). When the
  neighbours are removed, all the tests pass: the gap test uses trapezoids
  that end at 0. Without them, a range that starts after a step at a junction
  is 2.6 % off `get_gradients`. The spectrum chunks and the off-raster PNS
  chunks use this path.
- **No test** for the rebuild of the kept result of `pns_levels_for` after
  `add_block`, an interval across three or more chunks, the two `ValueError`s
  of a bad `window` of `gradient_limits`, or one key for a relative and an
  absolute path of one `.asc` file.
- **Weak checks.** The `window_of_one_sample` case of `tests/test_grad_spectrum.py`
  has no `match=`, so a different `ValueError` passes it.
  `test_pns_levels_is_a_frozen_dataclass` checks only `isinstance`. The oracle
  `tests/oracles/grad_limits.py` imports the production `gradient_points`, so
  it cannot find an error there.
- **Scripts.** `scripts/check_tests_md.py` line 80 splits a test ID on `::`,
  which fails for a parametrize ID that contains `::` (none does now).
  `scripts/time_pns_levels.py` matches the current API.

## 6. The API and the goals of the project

The README says that an analysis takes a sequence and *explicit* physical
parameters, and that it has no limit, no pass or fail and no finding.

1. **The default hardware is not a real scanner.** `pns_levels`,
   `pns_levels_for`, `pns_prediction` and the analysis `pns.safe.levels` use
   pypulseq's example hardware when no hardware is given. A generic runner
   that calls `compute(seq)` gets values for a scanner that does not exist,
   with only the label to show it. `AnalysisSpec.params` gives only the names,
   so a runner cannot know what the default is. Proposal: make the hardware
   necessary, or an explicit value such as `"example"`.
2. **The plot of one caller is in the analysis.** `EXACT_MAX_S` and
   `DISPLAY_BINS` ([pns_levels.py:46](../../src/pulseq_analysis/pns_levels.py#L46))
   are the PNS plot of pulseq-reports (a 10 s view, 812 columns). They set
   `bin_samples`, and thus the series `pns_total`, and no parameter changes
   them.
3. **Helpers of a report are in the analysis package.** `pns.peak_tr_window`
   is for a drawing; `seq_utils.hold_samples` is RF sampling for
   pulseq-reports, and no module of the package uses it;
   `pns_prediction` and `PnsPrediction` give a part of `PnsLevels`, a second
   way to get one value.
4. **Words of limits.** `PNS_LIMIT` is in the interface, but only the tests
   use it. The names `grad_limits`, `GradientLimits` and `gradient.limits`
   suggest a check against limits, which the package does not do. A change of
   these names breaks the callers, so the time for it is before `0.1.0`.
5. **The hardware arguments are not the same.** `pns_prediction` takes only
   `gradient_asc`, `pns_levels_for` takes `gradient_asc` or `hardware`, and
   the analysis takes only `hardware`. Thus a caller of the registry cannot
   give an `.asc` file.
6. **"No result" is given in different ways.** There are two `NO_GRADIENTS`
   constants, and `GradientLimits.reason` has two free strings with no
   constant.
7. **The results have different contracts.** The shared `SequenceIndex` is
   writable (section 1, item 2). The shared `PnsLevels` has dicts that a
   caller can change, and only the documentation says not to.
   `BlockGradientValues` compares by identity, and `PnsLevels`,
   `GradientSpectrum` and `Series` compare by value.
8. **`registry()` does not use the name of the entry point.** The docstring
   says that the name is the ID, but
   [analyses.py:376](../../src/pulseq_analysis/analyses.py#L376) uses
   `spec.id` and does not compare the two. An entry point with a different
   name gets the ID of its `spec`, with no error.

The thresholds of `PnsLevels.above` agree with the goals: the caller gives
them, and the result tells where the values are high, not whether a check
passed.

## 7. Order of the fixes

1. The stale kept results (section 1, item 1), with one shared cache helper.
2. Read-only arrays in `SequenceIndex` (section 1, item 2).
3. Tests for the off-raster path with more than one chunk and for a sampled
   range after a step at a junction (section 5).
4. The block range of `block_samples` (section 2, item 1).
5. The documentation errors of section 3.

## 8. Status at 0.1.0rc6

Written on 2026-10-07, for the release `0.1.0rc6`. The numbers of the items are
those of sections 1 to 6 of this review (the bullets of sections 3, 4 and 5 are
numbered in their order). The tasks are those of `docs/plans/review-fixes.md`
(the first plan). The names in sections 1 to 7 are those of `0.1.0rc5`. This
section uses the names of `0.1.0rc6` where a name has changed (`grad_peaks` for
`grad_limits`, `pns_levels` for `pns_levels_for`). A name of a test is the name
on `main` at the release.

Three later plans changed some of this code again (the second plan, the third
plan and the fourth plan: `docs/plans/second-review-fixes.md`,
`docs/plans/third-review-fixes.md` and `docs/plans/fourth-review-fixes.md`).
Where a later change makes the first fix different, the table says so.

The pull requests of the first plan:

| Task | PR | Branch |
|---|---|---|
| 1.1 | #18 | `fix/test-gaps` |
| 1.2 | #19 | `fix/stale-kept-results` |
| 1.3 | #20 | `fix/read-only-index` |
| 1.5 | #21 | `refactor/grad-limits-internals` |
| 1.6 | #22 | `refactor/spectrum-bins` |
| 1.4 | #23 | `fix/long-block-sampling` |
| 1.7 | #24 | `refactor/test-helpers` |
| 2.1 | #25 | `refactor/remove-report-helpers` |
| 2.2 | #26 | `refactor/rename-peaks` |
| 2.3 | #27, #28 | `feature/explicit-pns-hardware` |
| 2.4 | #29 | `feature/pns-bin-size` |
| 2.5 | #30 | `feature/consistent-results` |
| 2.6 | task 2.7 of the fourth plan, this release | `docs/release-0.1.0rc6` |

The status is "done", "done in another way" (the result differs from the
proposal of this review) or "not changed" (with the reason).

### 8.1 Section 1: correctness

| Finding | Status | Task / PR |
|---|---|---|
| 1.1 The kept results go stale after a new read into the same `Sequence` | Done, and then replaced. The first fix (#19) was one private module, `_kept.py`, with one stamp for `sequence_index`, `pns_levels` and `gradient_spectrum`: the objects `block_events`, `block_durations` and `grad_library`, the number of blocks, the last block ID and `grad_raster_time`. A new read makes new objects, so it empties the kept results. That stamp did not see a block changed in place. The review of 2026-10-07 (1.1) showed this for `mod_grad_axis` and `set_block`. Task 2.1 of the fourth plan (#80) removed the stamp and `_kept.py`: `snapshot.load` makes a sequence that only the package holds, and the kept results are in a dict of the snapshot. Test: `test_a_change_of_the_source_changes_no_result_of_the_snapshot`. | 1.2, #19. Replaced by task 2.1 of the fourth plan, #80 |
| 1.2 The kept `SequenceIndex` is writable | Done. Each array is read-only. Since #69 and #80 the arrays are made with `_equality._freeze`, so `flags.writeable = True` raises too. Test: `test_the_arrays_of_the_index_are_read_only_and_a_copy_is_writable`. | 1.3, #20 (`_freeze`: #69, #80) |
| 1.3 The triple key of `_range_result` can overflow int64 | Done. `_distinct_triples` had the two-step key (#21). Then the vector peak of each block was made from the merged point times of the three axes, so no key of triples is made now. | 1.5, #21. Replaced by task 1.6 of the third plan, #56 |
| 1.4 A peak of 0 has a peak time | Done. `PnsLevels.peak_time_s` is `None` when the peak is 0, and the model does not run a second time. Test: `test_gradients_that_all_have_the_amplitude_zero_have_no_peak_time_and_one_run`. | 2.5, #30 |

### 8.2 Section 2: efficiency

| Finding | Status | Task / PR |
|---|---|---|
| 2.1 `pns_levels` is quadratic in the length of one block | Done. `GradientSampler.block_samples` has the arguments `skip` and `count`, and the result is bit for bit the slice of the old result. One block of 120 s: 9.99 s before, 0.83 s after. Tests: `test_skip_and_count_equal_the_same_slice_of_the_whole_range`, `test_a_block_longer_than_a_chunk_does_not_depend_on_chunk_samples` and `test_one_long_delay_block_gives_the_result_of_the_same_time_in_short_blocks`. | 1.4, #23 |
| 2.2 The spectrum calculates about 25 times the bins that it keeps | Done. The windows are a view, and only the kept bins are made into magnitudes. On `build_repeating(10000)` the peak memory fell from 85 MB to 54 MB and the time from 0.63 s to 0.53 s. scipy's `ZoomFFT` was slower and used more memory, so it is not used. The values agree with scipy's `spectrogram` (`test_matches_scipy_spectrogram`). Since #78 the FFT is `scipy.fft.rfft` in one thread, with the same kept bins. | 1.6, #22 (the FFT: #78) |

### 8.3 Section 3: mis-documentation

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 3.1 | `get_block` sentences of `block_gradient_values`, `gradient_limits` and `docs/usage.md` | Done. The text said that one block is read for each unique gradient event, and that `gradient_peaks` also reads the blocks that a window edge cuts (#21). Task 1.6 of the third plan (#56) then stopped the reads for a window, and the docstrings now say so: the one `get_block` call for each unique gradient event is in `_events.event_points`, one time for each sequence. | 1.5, #21 (rewritten with #56) |
| 3.2 | References to files that do not exist | Done. The three that this review names are corrected (`waveforms._timed_blocks` in `seq_index.py`: #20; `tests/test_waveforms.py` in `tests/oracles/blocks.py` and `docs/plans/cards-at-scale.md` in `tests/test_pns_levels.py`: #24). The other references to `docs/plans/cards-at-scale.md` (a plan of pulseq-reports) were removed from `tests/` and `TESTS.md` by #31, and the references to other documents of other repositories by #32. `git grep cards-at-scale` now finds only `docs/plans/` and `docs/reviews/`, which do not change. | `_timed_blocks`: 1.3, #20. The other two: 1.7, #24. The rest: #31, #32 |
| 3.3 | "The four dicts" (`BlockGradientValues` has five) | Done. | 1.5, #21 |
| 3.4 | The junction step is "0 for the first block" | Done. The docstring said: the step from 0 to the first value of the block. Task 2.1 of the third plan (#58) changed the junction again (a step or a line into the event, and 0 for a long gap), and its docstring and `docs/usage.md` give the new rule. | 1.5, #21 (rewritten with #58) |
| 3.5 | "The largest of each array is the value of `gradient.limits`" is false for the slew | Done. The text says: the largest of each amplitude array, and the slew is the larger of the largest segment slew and the largest junction. The description of `gradient.blocks` has it. | 2.2, #26 |
| 3.6 | `extensions.py` names two callers of `refuse_rotations` | Done. It named the four (#26). Since #80 the module docstring says that `snapshot.load` makes the call. | 2.2, #26 |
| 3.7 | `pyproject.toml` says `calculate_pns` in chunks, `TODO.md` says `calc_pns` | Done. The comment of `pyproject.toml` says `calc_pns`, as `TODO.md` does. It changed with the new pin of pypulseq. | #42 (task 1.8 of the second plan) |
| 3.8 | `series.py` gives units from before `0.1.0rc5`, and names "design section 4.2" | Done. The examples are `"Hz/T"`, `"Hz/m"` and `"s"`. #30 named the design document of pulseq-checks, and #39 later removed the references to documents of other repositories from `series.py`. | 2.5, #30 (and #39) |
| 3.9 | `docs/usage.md`: `raster_block_lengths` gives one bool for all the blocks | Done. `docs/implementation.md` (section 2.4) says it. | 1.4, #23 |

### 8.4 Section 4: duplication

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 4.1 | `grad_limits`: the polyline values, the junction steps and the triples are each written twice | Done (#21). The code of `grad_peaks.py` was then replaced: the values of each block are calculated one time for each sequence (`_BlockData`, #56), and the gap rule is in `_events.py` (#79). | 1.5, #21 (#56, #79) |
| 4.2 | Two equalities with different rules (`Series.__eq__` and `values_equal`) | Done in another way. The first plan did not change it. `Series` now uses `_equality.fields_equal`, so the order of the keys of `meta` counts as for each other dict of the package, and `series._same_value` is gone (decision D5 of the second plan). Since #64, `@value_dataclass` sets the rule for `Series` and for the other five result classes. | #41 (task 1.6 of the second plan), #64 |
| 4.3 | Three validators of a number with different rules | Done. `_validate.real` checks every number argument: the thresholds, `bin_s`, the arguments of `gradient_spectrum`, the `window` of `gradient_peaks` and the coordinates of a `Series`. A wrong type raises `TypeError` and a wrong value `ValueError`, and `np.float32` and `np.int64` thresholds are valid. | 2.5, #30 |
| 4.4 | Constants: `NO_GRADIENTS` twice, the axis tuples in four modules, `_HW_FIELDS` and `SAFE_FIELDS`, `_has_gradients` twice | Done. `seq_index.NO_GRADIENTS` is the one object and `seq_index.has_gradients` replaces the two tests (#30). The axis tuples are `seq_utils._AXES` and `seq_utils._GRAD_COLUMNS`, used by each module (#41, with the name `AXES` and `GRAD_COLUMNS`; made private by #85). `_HW_FIELDS` is `SAFE_FIELDS` without `stim_thresh` (#41). | `NO_GRADIENTS`, `has_gradients`: 2.5, #30. The rest: #41 (task 1.6 of the second plan) |
| 4.5 | Tests: the fixture `write_gradient_asc` twice, `scale_sequences.py` copies `synthetic.py`, five helpers each written twice | Done. | 1.7, #24 |

### 8.5 Section 5: tests

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 5.1 | The off-raster path with more than one chunk | Done. Tests with small chunks and with the real chunk size (against `calculate_pns`): `test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples` and `test_an_off_raster_sequence_of_more_than_one_real_chunk_matches_calculate_pns`. | 1.1, #18 |
| 5.2 | The neighbour events of `GradientSampler.sample` | Done. A sequence with a step at a junction and a gap, compared on ranges of the whole grid (for example `test_range_across_a_step_and_a_ramp_equals_the_same_slice_of_the_whole_grid`). The second review (5, `_kept_samples`) and the fourth review (5.1) added more cases of the sampler. | 1.1, #18 |
| 5.3 | No test for: the rebuild after `add_block`; an interval across three or more chunks; the two `ValueError`s of a bad `window`; one key for a relative and an absolute path of one `.asc` file | Done. The interval test is `test_an_interval_across_three_chunks_does_not_depend_on_chunk_samples`. The `window` tests are `test_gradient_peaks_refuses_a_window_with_no_start_before_its_end` and `test_gradient_peaks_refuses_a_window_outside_the_sequence`. The path test is `test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result`. The rebuild test (`tests/test_kept.py`) went away with `_kept.py` (#80): a snapshot is never rebuilt, and the independence test of `tests/test_snapshot.py` replaces it. | The interval and the `window`: 1.1, #18. The rebuild and the path: 1.2, #19 (the path again in 2.3, #27; the rebuild replaced in #80) |
| 5.4 | Weak checks: `window_of_one_sample` without `match=`; `test_pns_levels_is_a_frozen_dataclass`; the oracle imports `gradient_points` | Done. `window_of_one_sample` has a `match=`. The frozen test checked `FrozenInstanceError` (#18), and task 1.6 of the fourth plan (#74) deleted it, because `test_value_dataclass_makes_a_frozen_class_with_value_equality` covers it. The oracle makes its own corner points and has its own tolerance; the oracle of `grad_peaks` was then replaced by `tests/oracles/waveform.py` (#58). | 1.1, #18 |
| 5.5 | Scripts: `check_tests_md.py` splits a parametrize ID on `::`; `time_pns_levels.py` | Done. The name of a test is read after the parametrize ID is cut off. `time_pns_levels.py` refuses `--blocks` below one TR and checks the thresholds before it builds the sequence. | 1.7, #24 |

The mutation check of the plan (section 6.1: each of M1 to M4 fails a test) is
a check of the release (section 7 of the plan), not a finding of this review.
Each of the four failed a test when #18 merged (the table of the PR gives the
count of failing tests).

### 8.6 Section 6: the API and the goals of the project

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 6.1 | The default hardware is not a real scanner | Done in another way (decision U4, and U8 of 2026-10-05). `hardware` is a required keyword argument of `pns_levels` and of `PNS_SAFE_LEVELS.compute`, with no default. It is the pair `(struct, label)`. For pypulseq's example hardware, a caller gives `(safe_example_hw(), "<a label>")`. There is no sentinel value. `AnalysisSpec.params` gave only the names when this review was fixed (this was a known limit, plan section 9, "Later"). Task 2.3 of the second plan (#47) added `AnalysisSpec.necessary` and `defaults`: `pns.safe.levels` has `necessary=("hardware",)`, so a runner can know which parameter it must give. | 2.3, #27 (and #28, the wording of `TESTS.md`). The spec: #47 |
| 6.2 | The plot of one caller is in the analysis (`EXACT_MAX_S`, `DISPLAY_BINS`) | Done. The bin is the argument `bin_s` (seconds). `MAX_BINS` still limits the memory. The default was `BIN_S = 10.0 / 1624`, the bins of `0.1.0rc5`. The second review (1.1 and 6.4) found that `bin_s` on the raster lost one sample for about half of the values, and the default is now 5 ms (#36, decision U3 of 2026-10-05). | 2.4, #29 (the snap and the default: #36) |
| 6.3 | Helpers of a report are in the analysis package | Done. `pns.peak_tr_window`, `seq_utils.hold_samples`, `pns_prediction` and `PnsPrediction` are removed. pulseq-reports takes over the first two, and `pns_levels` gives the fields of the others. | 2.1, #25 |
| 6.4 | Words of limits (`PNS_LIMIT`, `grad_limits`, `GradientLimits`, `gradient_limits`, `gradient.limits`) | Done. `PNS_LIMIT` is removed (the limit in Hz/T is `abs(gamma)`). `grad_limits` is `grad_peaks`, `GradientLimits` is `GradientPeaks`, `gradient_limits` is `gradient_peaks`, and `gradient.limits` is `gradient.peaks`. | `PNS_LIMIT`: 2.1, #25. The names: 2.2, #26 |
| 6.5 | The hardware arguments are not the same | Done in another way. Each entry point takes only `hardware`, the pair `(struct, label)`. `gradient_asc`, `PnsLevels.asc_file` and the `meta` key `asc_file` are removed, and `asc.hardware_from_asc(path)` makes the pair from a Siemens `.asc` file. A caller of the registry gives the pair, not a path. | 2.3, #27 |
| 6.6 | "No result" is given in different ways | Done. `seq_index.NO_GRADIENTS` and `seq_index.NO_GRADIENTS_IN_WINDOW` are the only reasons, and `GradientPeaks.reason` is one of them or `None`. | 2.5, #30 |
| 6.7 | The results have different contracts | Done. Each dict of a result is a `FrozenDict` (a `dict` that raises `TypeError` for a change), `SequenceIndex` and `BlockGradientValues` compare by value, and the arrays of `BlockGradientValues` are read-only. The `SequenceIndex` arrays are read-only since task 1.3. `Series` had its own rule of equality (item 4.2), and now has the one rule. `GradientPeaks` compares by value and is not hashable since #48. | 2.5, #30 (the index: 1.3, #20. `GradientPeaks`: #48) |
| 6.8 | `registry()` does not use the name of the entry point | Done. An entry point whose name is not the `spec.id` of its object raises `RegistryError`. Since #83, `registry(strict=False)` leaves it out with a `RegistryWarning`. | 2.5, #30 |

### 8.7 What stays

No item of this review stays open at `0.1.0rc6`. The two limits that were known
when the first plan was done (a block replaced in place is not seen by the kept
results, and `AnalysisSpec.params` gives only names) are corrected by
`snapshot.load` (#80) and by `AnalysisSpec.necessary` and `defaults` (#47).
