# Code review, 2026-10-06

A review of the whole package at commit `efe4f46`, after tasks 1.1 to 2.4 of
`docs/plans/second-review-fixes.md` (the fixes of
[the review of 2026-10-05](2026-10-05-code-review.md)). Task 2.5, the release
`0.1.0rc6`, is not done yet. Thus this review does not repeat the findings that
task 2.5 corrects: the version, `README.md` and `CHANGELOG.md`.

The review looks for these things:

- Code that is incorrect, mis-documented, duplicative or inefficient.
- Tests that are unnecessary, that do not test what they claim, or that test
  only code outside this repository.
- Parts of the API that do not fit the goals of the project.

The line numbers are of commit `efe4f46`.

Method:

- A read of every module of `src/pulseq_analysis/` and of each test file.
- A check of `docs/usage.md`, `TESTS.md` and the docstrings against the code.
- Small scripts against the pinned pypulseq fork (`3c3bd85`).
- 61 single-line mutations of a copy of `src/` with a script, and more
  single-line mutations to check single tests.

The findings marked *reproduced* were run against the fork. In section 5,
"passes" means that all 1045 tests pass with the mutation.

At this commit, `nix develop --command scripts/check` passes: ruff, 1045
tests, the `TESTS.md` check (319 entries) and shellcheck.

## 1. Correctness

1. **A junction into a delayed event loses its steps** (*reproduced*).
   `_junction_steps`
   ([grad_peaks.py:344](../../src/pulseq_analysis/grad_peaks.py#L344)) gives
   the step `|prev_last - first|` at the time `start + delay`. During the
   delay the event plays nothing. Thus the waveform has two steps: from
   `prev_last` to 0 at the block start, and from 0 to `first` at the end of
   the delay. pypulseq's `add_block` accepts the sequence below, where each of
   these steps is less than `max_slew * grad_raster_time`.

   The sequence of the reproduction: block 1 ramps to
   `a = 0.9 * max_slew * grad_raster_time` and holds `a` to its end. Block 2
   has an extended trapezoid that starts at `a`, with a delay of 100 us.

   - `gradient_peaks` gives the largest slew 5.7e8 Hz/m/s, the slope of a
     ramp. `block_gradient_values` gives the junction steps `[0, 0]`.
   - `GradientSampler.block_samples`, the input of `pns_levels`, gives `a`,
     then 0 during the delay, then `a`. That is two steps of 5.7e9 Hz/m/s,
     10 times the slew that `gradient_peaks` gives.
   - The RMS of `grad_peaks` also uses 0 during the delay.

   The module docstring
   ([grad_peaks.py:33](../../src/pulseq_analysis/grad_peaks.py#L33)) says
   that such an event "has its step from 0 at the end of the delay", but the
   value of the step does not use 0. An event that ends at a value that is not
   0 before the end of its block has the same gap: the step to 0 at the end of
   the event is not counted. The cause is that the package has three models of
   the waveform between two events (section 6, item 3).

2. **The spectrum attenuates the gradients at the end of a sequence**
   (*reproduced*). `_compute_spectrum` pads the end with `nwin // 2` zeros for
   each number of samples `nt`
   ([grad_spectrum.py:220](../../src/pulseq_analysis/grad_spectrum.py#L220)).
   The first sample is always at the centre of the first window. The last
   sample is at the centre of a window only when `nt` is a whole number of
   hops. Otherwise the last samples are near the edge of the last Hann window,
   and no later window holds them.

   One trapezoid (`area=3000`) at the end of a sequence of N samples
   (hop 2500) gives these values of `rss.max()`:

   | N | 5000 | 6000 | 6500 | 7000 | 7499 | 7500 |
   |---|---|---|---|---|---|---|
   | `rss.max()` (Hz/m/sqrt(Hz)) | 21481 | 16118 | 11455 | 8743 | 10747 | 21481 |

   The same trapezoid at the start of a sequence gives 21483. The module
   docstring ([grad_spectrum.py:7](../../src/pulseq_analysis/grad_spectrum.py#L7)
   to 9) says that gradients near either end are not attenuated. Fix: pad the
   end with `pad + (-nt) % hop` zeros, so that the last sample is at the
   centre of a window.

3. **The spectrum counts the samples with its own rule** (*reproduced*).
   `nt = math.ceil(sum(seq.block_durations.values()) / dt)`
   ([grad_spectrum.py:216](../../src/pulseq_analysis/grad_spectrum.py#L216))
   uses the compensated `sum` of Python. The other modules use `index.end_s`,
   the sequential sum. Off the raster, `pns_levels` uses
   `ceil((end_s - 1e-10) / dt)`
   ([pns_levels.py:413](../../src/pulseq_analysis/pns_levels.py#L413)).

   - The blocks `[0.01938, 0.01268]` s give 3207 samples here. The exact
     count and the rule of `pns_levels` give 3206.
   - With item 2, one sample can halve the result. The blocks
     `[0.04746, 0.52753]` s with a trapezoid at the end give 21478 with this
     rule and 10747 with the rule of `pns_levels`.

   The comment says "Do not change it to `index.end_s`", because the oracle
   has the same line. No test fixes the count: `index.end_s`, `+ 1` and
   `+ 1000` each pass (section 5.3). Fix: one rule for the number of samples
   of a sequence, in one function. The oracle then follows that rule.

4. **A `Series` can be changed after its checks** (*reproduced*).
   `__post_init__` keeps `arrays` and `meta` as plain dicts
   ([series.py:282](../../src/pulseq_analysis/series.py#L282) and
   [286](../../src/pulseq_analysis/series.py#L286)). The frozen dataclass
   accepts `s.arrays["value"] = shorter_array`, a 2-D array, and
   `s.meta["k"] = object()`, and `to_obj` then raises. Each result of the
   package keeps its dicts as `FrozenDict`s. Fix: a `FrozenDict` for each of
   the two.

5. Two small items:

   - An `$INCLUDE` cycle in `.asc` files recurses until `RecursionError`
     ([asc.py:34](../../src/pulseq_analysis/asc.py#L34)).
   - `decode_array` decompresses all the data before it compares the length
     ([series.py:459](../../src/pulseq_analysis/series.py#L459)). Thus a small
     object can expand with no limit. This is a risk only for a series that
     comes from outside the package.

## 2. Efficiency

1. **A window of `gradient_peaks` costs O(K) and two `get_block` calls**
   (*reproduced*). For each window, `_axis_slice_stats` makes a `bincount`
   and two masks over all the K unique events
   ([grad_peaks.py:479](../../src/pulseq_analysis/grad_peaks.py#L479) to 485).
   On a sequence of 20,000 blocks, a window of one block costs 0.11 ms for
   K = 1 and 0.29 ms for K = 20,000.

   A window that cuts two blocks reads each of them with `get_block`
   ([grad_peaks.py:587](../../src/pulseq_analysis/grad_peaks.py#L587) to 600).
   `_events.event_points` already keeps the points of each event. The points
   from its pools, with the times `(start + delay[k]) + offsets`, give the
   same floats as `gradient_points`.

2. **Each window calculates the vector peak of each triple again.**
   `_range_result`
   ([grad_peaks.py:625](../../src/pulseq_analysis/grad_peaks.py#L625) to 644)
   calls `_triple_vector_peak` for each distinct triple of the window.
   `_block_vector_peaks`
   ([grad_peaks.py:827](../../src/pulseq_analysis/grad_peaks.py#L827) to 848)
   calculates the same values for all the blocks. Section 4, item 1 gives a
   fix.

## 3. Mis-documentation

- The module docstring of `seq_index`
  ([seq_index.py:16](../../src/pulseq_analysis/seq_index.py#L16)) says that
  only `rf_events`, `grad_events` and `adc_events` call `get_block`.
  `_range_result` also calls it
  ([grad_peaks.py:589](../../src/pulseq_analysis/grad_peaks.py#L589)).
- The docstring of `gradient_peaks`
  ([grad_peaks.py:756](../../src/pulseq_analysis/grad_peaks.py#L756)) says
  that `_events.event_points` "calls no `get_block`". It calls `get_block`
  one time for each unique event
  ([_events.py:3](../../src/pulseq_analysis/_events.py#L3)).
- `docs/usage.md` (line 210) and the docstring of `gradient_peaks`
  ([grad_peaks.py:742](../../src/pulseq_analysis/grad_peaks.py#L742)) say that
  the cost of a window is the number of blocks in the window. Section 2,
  item 1 gives the other costs.
- The module docstring of `grad_spectrum` says that the ends are not
  attenuated (section 1, item 2).
- The module docstring of `sampling`
  ([sampling.py:9](../../src/pulseq_analysis/sampling.py#L9)) names
  `pypulseq.eps`. The code uses `seq_utils.TIME_TOLERANCE`.
- `docs/usage.md` (line 62) says that the measurements use
  `BlockDurationRaster`. Section 6, item 1 gives the problem.
- [grad_peaks.py:45](../../src/pulseq_analysis/grad_peaks.py#L45) is 157
  characters long. The default rules of ruff do not check the length of a line
  (`TESTS.md`, "Lint").
- `TESTS.md` has text that is not true at this commit:
  - Lines 196 to 199 and 317 name "the report cards" and "the RF resampling
    helper". This package has neither.
  - Line 252 says that `test_gradient_offsets_arbitrary` checks that pypulseq
    gives `first` and `shape_dur`. The test does not check it.
  - Lines 1125 to 1127 say that the cards of pulseq-reports call
    `refuse_rotations`. In this package, `grad_peaks`, `pns_levels` and
    `grad_spectrum` call it.
  - Line 1136 describes "the one test that checks a `.seq` file directly".
    No test calls its helper (section 5.4).
  - Line 2734 gives `(np.float64(0.0), ...)` as a window of
    `test_gradient_peaks_takes_a_window_as_a_list_or_with_numpy_scalars`. The
    test uses `np.int64(0)`.
  - Line 3326 says that the series tests use "no sequence and no pypulseq".
    `test_the_series_of_pns_safe_levels_are_valid` and
    `test_the_series_of_gradient_spectrum_is_valid` use both.
  - Line 4056 says that the message names `safe_example_hw()`. The test
    matches only `asc.hardware_from_asc(path)`.
  - Line 4265 says that `axes` is `{}` for `NO_GRADIENTS`. The test checks the
    keys `x`, `y` and `z`, each with an empty array.
  - Line 4284 says that the chunked spectrum is not always equal bit for bit,
    "because scipy computes the" FFTs. The module does not call scipy for the
    FFT now, and the chunked result is equal bit for bit (checked).
  - Line 4557 says that `fields_equal` is the `__eq__` of `PnsLevels` and
    `GradientSpectrum`. `SequenceIndex`, `GradientPeaks`,
    `BlockGradientValues` and `Series` use it too.
- The docstring of `test_compute_of_gradient_spectrum_passes_its_arguments_on`
  ([test_analyses.py:363](../../tests/test_analyses.py#L363)) says "the
  `to_series` meta gives them". The test does not call `to_series`.

## 4. Duplication

1. **Two calculations of the same values for each block.** `gradient_peaks`
   and `block_gradient_values` calculate the peak, the slew and the vector
   peak of each block in two ways:

   - For the peak and the slew, `_axis_slice_stats` uses a `bincount` and
     `isin` over the unique events. `block_gradient_values` uses
     `_event_column`.
   - For the vector peak, two loops over the distinct triples (section 2,
     item 2).

   The docstring of `BlockGradientValues` says that the largest value of each
   of its arrays is the value of `gradient_peaks`. Proposal: keep the columns
   of each block for the sequence, with a prefix sum of the RMS integral of
   each axis. Then a range is an `argmax` and a difference of two prefix sums
   over the blocks `[a, b)`, plus the blocks that its edges cut. This removes
   `_axis_slice_stats`, the vector peak loop of `_range_result` and the O(K)
   cost of a window. It keeps a few more arrays of N values. `_BlockData`
   already keeps seven.
2. `_hardware_key`
   ([pns_levels.py:352](../../src/pulseq_analysis/pns_levels.py#L352)) uses
   `stim_thresh`, which the model does not use and `PnsLevels.hw` does not
   keep. Two hardware structs that differ only in `stim_thresh` give two kept
   results with equal values.
3. `_load(ep, group)` and `_add(found, key, obj, ep, what)`
   ([analyses.py:515](../../src/pulseq_analysis/analyses.py#L515) and
   [527](../../src/pulseq_analysis/analyses.py#L527)) are general helpers, but
   each has one caller with one group.

## 5. Tests

### 5.1 Tests that do not test what they claim

- **`test_series_refuses_bad_arrays`**
  ([test_series.py:546](../../tests/test_series.py#L546)) (*reproduced*).
  Each ENVELOPE case has `coord_end=1.0` and arrays of 3 values, so the
  `coord_end` check refuses each one, not the check that the case names. The
  removal of the rule "an envelope has only `min` and `max`"
  ([series.py:228](../../src/pulseq_analysis/series.py#L228) to 233) passes.
  The removal of the length check passes `runs-lengths-differ`, because the
  numpy broadcast in `end < start` raises.
- **The order of first use in the index** (*reproduced*). With
  `order = used` in place of the sort by first use
  ([seq_index.py:134](../../src/pulseq_analysis/seq_index.py#L134)), each test
  of `test_seq_index.py` passes, also
  `test_dense_columns_and_first_arrays_match_the_reference_numbering` and
  `test_grad_dense_numbering_follows_gx_then_gy_then_gz_within_a_block`. Each
  test sequence registers its events in the order of first use. Only
  `test_kept.py::test_a_new_block_events_object_with_the_same_keys_gives_a_new_index`
  fails.
- **A threshold equal to the peak** (*reproduced*). No test gives one. `>` in
  place of `>=` in `_IntervalFinder.add_chunk`
  ([pns_levels.py:579](../../src/pulseq_analysis/pns_levels.py#L579)) passes.
  The rule "the tuple of a threshold is not empty if and only if the peak is
  at or above it" then breaks: `gre_sequence()` with the threshold equal to
  its peak gives no interval.
- **`test_pns_levels_takes_numpy_and_fraction_thresholds`**
  ([test_pns_levels.py:803](../../tests/test_pns_levels.py#L803)). The second
  call has the same kept key as the first, so it gives the same object. The
  comparison compares one object with itself. The float call must use
  `_compute`.
- **`test_example_hardware_for_spin_echo`**
  ([test_pns_levels_kept.py:34](../../tests/test_pns_levels_kept.py#L34))
  compares `pns_levels` with `_compute_levels`, the function that
  `pns_levels` calls. `peak = max(peak, 0.9 * chunk_max)` passes it.
- **`test_gradients_at_the_end_are_not_attenuated`**
  ([test_grad_spectrum.py:90](../../tests/test_grad_spectrum.py#L90)). Its
  sequence is a whole number of hops long, and its sine is longer than a
  window. Thus it cannot find section 1, item 2: no end padding at all
  (`n = nt + pad`) passes.
- **`_assert_matches_oracle`**
  ([test_grad_peaks.py:670](../../tests/test_grad_peaks.py#L670)). `TESTS.md`
  says that it compares every field. It does not compare `peak_time_s` or
  `vector_peak_time_s`, and it checks only that a block is credited, not
  which block. The mutation `start_s[peak_play] - start_s[i0] + ...` in
  `_axis_slice_stats` passes. With a comparison of the times added, the
  helper passes on the code and fails 50 tests on that mutation.
- **`test_a_window_gives_the_same_result_with_and_without_the_kept_data`**
  ([test_grad_peaks.py:1516](../../tests/test_grad_peaks.py#L1516)). The
  docstring says that the kept data comes "from the windows before". The test
  removes the kept results before each window, so one window builds the kept
  data each time.
- **The agreement of `block_gradient_values` and `gradient_peaks`**.
  `_assert_block_values_agree_with_gradient_peaks`
  ([test_grad_peaks.py:971](../../tests/test_grad_peaks.py#L971)) uses
  `start_s` as the time of a junction step. For a delayed event the time is
  `start_s + delay`. `_delayed_junction_sequence` is not in
  `_AGREEMENT_SEQUENCES` (line 987), and the test fails when it is added.
- **The delayed junction** (`_delayed_junction_sequence`, line 904). Block 1
  ends at 0, so `prev_last` is 0. The test cannot see section 1, item 1.
- **The raster of `block_gradient_values`**. `seq.system.grad_raster_time` in
  place of `seq.grad_raster_time`
  ([grad_peaks.py:880](../../src/pulseq_analysis/grad_peaks.py#L880)) passes.
  The one test with a 4 us file
  ([test_grad_peaks.py:436](../../tests/test_grad_peaks.py#L436)) calls only
  `gradient_peaks`.
- **The raster tolerance**. `ON_RASTER_TOLERANCE = 0.4`
  ([sampling.py:312](../../src/pulseq_analysis/sampling.py#L312)) passes.
  Each off-raster input of
  `test_raster_block_lengths_detects_a_block_off_the_raster` and
  `test_block_samples_off_raster_block_raises_value_error` is 1.5 samples
  long, the farthest point from the raster.
- **`test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples`**
  ([test_pns_levels.py:482](../../tests/test_pns_levels.py#L482)). The test
  copies the formula `ceil((end_s - 1e-10) / dt)`, and its `end_s / dt` is
  6001.5. The removal of `- 1e-10` passes.
- **`test_subrange_inside_a_gap_matches_pypulseq`**
  ([test_sampling.py:187](../../tests/test_sampling.py#L187)). `TESTS.md` says
  that it checks the straight line between the two events. Both ends of the
  gap are 0, so each expected value is 0. A range with no neighbouring events
  (`event_blocks[lo_pos:hi_pos]`) passes it.
- **`test_junction_step_and_segment_of_one_block_with_the_same_slew_give_the_junction_time`**
  ([test_grad_peaks.py:1099](../../tests/test_grad_peaks.py#L1099)). Its
  segment starts at the block start, so the junction and the segment have the
  same time. `<` in place of `<=` at
  [grad_peaks.py:685](../../src/pulseq_analysis/grad_peaks.py#L685) passes
  it. Only `test_junction_step_equal_to_a_segment_slope_of_its_block_takes_the_credit`
  (line 346) fails.
- **`test_series_not_equal_for_a_different_field_or_array[kind]`**
  ([test_series.py:663](../../tests/test_series.py#L663)). The two series
  differ in their arrays and in `coord_step` too. A `_same_fields` that skips
  `kind` passes. POINTS and RUNS with the same four arrays would isolate the
  kind.
- **Cases that pass for another reason** (`test_series.py`,
  `test_analyses.py`):
  - `test_decode_array_refuses[data-not-base64]` (line 1038): `"not base64!"`
    fails on its padding. Without `validate=True`
    ([series.py:459](../../src/pulseq_analysis/series.py#L459)) all tests
    pass, and valid data followed by `"!!"` then decodes.
  - `test_from_obj_refuses[coord-start-a-bool]` (line 909): without the
    `bool` check ([series.py:481](../../src/pulseq_analysis/series.py#L481)),
    `True` is 1.0, and the `coord_end` check refuses it.
  - `test_decode_array_refuses[length-a-bool]`: without the `bool` check
    ([series.py:452](../../src/pulseq_analysis/series.py#L452)), the count
    check refuses it.
  - `test_analysis_spec_raises_for_params_that_disagree_with_necessary_and_defaults`
    ([test_analyses.py:300](../../tests/test_analyses.py#L300)) has no
    `match=`. The checks of a default that is not in `params` and of a
    repeated default
    ([analyses.py:112](../../src/pulseq_analysis/analyses.py#L112) to 116) can
    each be removed: the order check at line 123 raises for the same inputs.
- **`test_series_refuses_bad_meta`**
  ([test_series.py:568](../../tests/test_series.py#L568)) and the `TESTS.md`
  text "a numpy number". `np.float64` is a subclass of `float` and is
  accepted, then converted
  ([series.py:128](../../src/pulseq_analysis/series.py#L128) to 134). The
  removal of any of the three conversions passes. Without the `float`
  conversion, a series with `np.float64(1.5)` in `meta` is not equal to its
  own JSON round trip.

### 5.2 Gaps that the mutation script found

The script applied 61 single-line mutations to the code of the commits after
`dfdb044`. 43 of them fail a test. Of the 18 that pass, 11 cannot change a
result (for example, a different side of a `searchsorted` that only adds
earlier points, or a cache that is skipped). These 7 can change a result:

| Line | Mutation | Input that gives a different result |
|---|---|---|
| [grad_peaks.py:684](../../src/pulseq_analysis/grad_peaks.py#L684) | `junction_max > seg_max` to `>=` | A segment of block 1 with the same slew as the junction step of block 2. The credit goes to block 2, not block 1. |
| [sampling.py:107](../../src/pulseq_analysis/sampling.py#L107) | `side="right"` to `"left"` for `hi_pos` | Sample times in a gap that ends at a junction step. `sample` gives 0 in place of the line to the next event. |
| [series.py:134](../../src/pulseq_analysis/series.py#L134) | `value = float(value)` to `pass` | `meta={"x": np.float64(1.5)}`. The series is not equal to its round trip. |
| [series.py:325](../../src/pulseq_analysis/series.py#L325) | `>` to `>=` | ENVELOPE of 2 bins, `coord_end = 1.0 + 1e-9`. It is accepted. |
| [series.py:331](../../src/pulseq_analysis/series.py#L331) | `<=` to `<` | ENVELOPE of 2 bins, `coord_end = 2.0 + 1e-9`. It is refused. |
| [pns_levels.py:211](../../src/pulseq_analysis/pns_levels.py#L211) | `abs(sum - 1)` to `sum - 1` | `a1 + a2 + a3 = 0.9` on a sequence with no gradient gives a result, not `ValueError`. |
| [pns_levels.py:579](../../src/pulseq_analysis/pns_levels.py#L579) | `>=` to `>` | A threshold equal to the peak (section 5.1). |

### 5.3 Tests of code outside this repository, and oracles that copy `src/`

- **Tests that call no code of the package:**
  - `test_time_tolerance`
    ([test_seq_utils.py:17](../../tests/test_seq_utils.py#L17)) compares a
    constant with a literal and with `pp.eps`.
  - `test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system` (line 22)
    compares a constant of the tests with the default of pypulseq.
  - `test_synthetic_sequences_pass_the_timing_check` (line 106) checks the
    helpers of `tests/synthetic.py` with the timing check of pypulseq.
  - `test_a_frozen_dict_reads_like_a_dict`,
    `test_a_frozen_dict_is_made_from_pairs_and_keywords`,
    `test_a_frozen_dict_is_written_by_json_as_an_object_and_is_not_hashable`
    and `test_the_union_of_a_frozen_dict_is_a_plain_dict`
    ([test_equality.py:126](../../tests/test_equality.py#L126), 140, 165 and
    173) check the behaviour that `FrozenDict` gets from `dict`.
- **Tests of pypulseq's `write` and `read`.**
  `test_refuse_unsigned_accepts_a_sequence_after_write`,
  `..._accepts_a_read_of_a_signed_file`,
  `..._raises_for_a_read_of_an_unsigned_file` and
  `test_each_measurement_accepts_a_sequence_after_write`
  ([test_extensions.py:141](../../tests/test_extensions.py#L141), 151, 160 and
  181) call `refuse_unsigned`, which reads only `seq.signature_value`. Tests
  at lines 111 and 124 already cover its two cases. These four tests check
  that the write and the read of the pinned fork set the hash. That is a
  check of the pin (`TODO.md`), not of the package. `TESTS.md` must say so if
  they stay. The test at line 181 asserts only `is not None`.
- **Tests whose expected value comes from the code under test:**
  - `test_event_values_of_the_points_equal_the_values_of_gradient_points`
    ([test_events.py:144](../../tests/test_events.py#L144)) takes its
    expected values from `_polyline_values`. A doubled integral passes
    `test_events.py`.
  - `_points_from_grad_events`
    ([test_events.py:36](../../tests/test_events.py#L36)) copies
    `_events._read_points` line for line.
  - `test_a_gradient_sampler_from_event_points_gives_the_samples_of_the_points_from_grad_events`
    (line 119) gives the sampler two inputs that the test before it proves
    equal. A `sample` that gives 2 times the value passes `test_events.py`.
  - `test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file`
    ([test_pns_levels_kept.py:225](../../tests/test_pns_levels_kept.py#L225))
    repeats the two-line body of `hardware_from_asc`.
- **Oracles that copy `src/`.** In `tests/oracles/grad_peaks.py`,
  `_clip_polyline` (lines 116 to 132) and `_vector_peak_in_block` (lines 184
  to 203) are copies of the functions of `grad_peaks.py`. The rule of a
  segment shorter than `TIME_TOLERANCE`, the RMS formula and the skip of a
  clipped piece with fewer than 2 points are the same too. Thus the blocks
  that a window edge cuts run the same code in the package and in the oracle.
  The random oracle sequences start and end each event at 0, so their
  junction steps are 0 in all 200 seeds. In `tests/oracles/grad_spectrum.py`,
  the padding, the hop and the sample count (line 70) are those of the
  package. Thus the oracle tests cannot find section 1, items 2 and 3.
- **The conversion with gamma.** The docstring of `_assert_matches_oracle`
  and `TESTS.md` say that the test checks the conversion to tesla. Both sides
  divide by the same `GAMMA_1H` in the test code, and the package has no
  gamma. This part cannot fail because of a change of `src/`.

### 5.4 Unnecessary tests and dead test code

- **`test_pns_levels.py` and `test_pns_levels_kept.py` overlap:**
  - `test_pns_levels_needs_hardware` (lines 960 and 304) and
    `test_pns_levels_refuses_a_bad_struct_for_a_sequence_without_gradients`
    (lines 1008 and 354) are the same in the two files.
  - `test_pns_levels_refuses_a_hardware_that_is_not_a_pair_before_any_work`
    (line 975) and `test_pns_levels_refuses_a_bad_struct_before_any_work`
    (line 992) do less than the tests of the same names in the kept file
    (lines 319 and 336).
  - In the kept file, the cases of the `bin_s` and threshold refusals (lines
    433 and 460) are subsets of lines 837 and 786 of `test_pns_levels.py`.
  - In the kept file, other tests cover these: `test_no_gradients` (line
    103), `test_asc_file_with_the_example_parameters` (50),
    `test_asc_file_that_includes_the_pns_parameters` (63),
    `test_pns_levels_keeps_one_result_for_each_asc_file` (191),
    `test_pns_levels_alternating_two_hardwares_runs_the_model_two_times`
    (210), `..._gives_the_same_object_for_a_second_call_with_the_same_arguments`
    (494), `..._gives_a_new_object_after_add_block` (508) and
    `test_a_gradient_on_one_axis_has_a_prediction` (121).
- **`test_grad_peaks.py`:**
  - `test_extended_trapezoid_max_slew_is_the_largest_segment_slope` (line
    245) has the sequence and the value of
    `test_slew_time_is_the_start_of_the_steepest_segment` (line 330).
  - `test_the_reason_of_a_sequence_with_no_gradient_is_no_gradients[delay_only]`
    (line 1242) has the input of `test_no_gradients_sets_reason` (line 201).
  - `test_same_trapezoid_on_x_and_y_gives_vector_peak_root_2_times_axis_peak`
    (line 126) is block B of
    `test_vector_peak_of_g_compares_different_triples_across_blocks` (line
    377).
  - Section 5.1 gives line 1099.
- **`test_seq_index.py`:** the cases `delay only` and `empty` of
  `test_has_gradients_is_true_only_for_an_index_with_a_gradient_event` (line
  282) are both one delay block.
- **`test_analyses.py`:** `test_series.py` covers lines 583 and 646 (its
  lines 449 and 475) and line 594 (line 449). Line 568 is about the same as
  line 449 of `test_series.py`. Line 407 is covered by
  `test_pns_levels_keys_a_hardware_from_an_asc_file_by_its_label_and_values`.
  Line 383 repeats lines 345, 363 and 448.
- **Others:** `test_axis_without_events_is_zero`
  ([test_sampling.py:301](../../tests/test_sampling.py#L301)) is the `gz`
  part of `test_whole_file_matches_pypulseq_for_synthetic_sequences[spin_echo]`.
  `test_no_gradients_gives_an_empty_read_only_array_for_each_axis`
  ([test_grad_spectrum.py:114](../../tests/test_grad_spectrum.py#L114)) adds
  only a dtype check to the tests at line 96 and line 293.
- **A slow test:** `test_series_round_trip_of_two_million_float32_values`
  ([test_series.py:777](../../tests/test_series.py#L777)) takes 0.53 s, about
  10 % of the suite. No code path depends on the size.
- **Dead test code:**
  - The `gpa` argument of the fixture `write_gradient_asc`
    ([conftest.py:35](../../tests/conftest.py#L35) to 44 and 65 to 70): no
    test gives it.
  - `_write_rotation_file`
    ([test_extensions.py:50](../../tests/test_extensions.py#L50) to 76): no
    test calls it.
  - The check of duplicate base names in `scripts/check_tests_md.py` (lines
    72 to 80): each test is directly in `tests/`.
  - The `except (ValueError, TypeError): continue` of `test_package.py`
    (lines 43 and 44): it does not run for any of the 340 callables.
  - The `ValueError` branch of `spin_echo_sequence` and the argument `tr` of
    `gre_sequence` (`tests/synthetic.py`): no test uses them.
  - In `tests/oracles/grad_spectrum.py`, `_band_peaks` and the resonances
    (line 132 and after): no test gives resonances. The branches for
    `n < nwin` (lines 77 and 87) cannot run, because `nt >= 1`.
  - The argument `num_arrays` of `test_the_arrays_of_a_spectrum_are_read_only`
    ([test_grad_spectrum.py:293](../../tests/test_grad_spectrum.py#L293)) is 5
    in both cases.

## 6. The API and the goals of the project

The README says that an analysis takes a sequence and explicit physical
parameters, and gives values with no limit and no finding.

1. **`AnalysisSpec.rasters` does not agree with the code.** Four analyses give
   `("GradientRasterTime", "BlockDurationRaster")`
   ([analyses.py:143](../../src/pulseq_analysis/analyses.py#L143)), and
   `seq.index` gives `()` (line 165). No code reads
   `seq.block_duration_raster`. Each of the five analyses reads the block
   durations, which the file gives in units of `BlockDurationRaster`.
   pulseq-checks uses `spec.rasters` to decide that a check is not evaluated
   (`src/pulseq_checks/run.py` line 304), so the field changes the results of
   a caller. A rule for the field is necessary: either each raster whose value
   changes the result, or only the rasters that the code reads.
2. **The public `GradientSampler` needs a private name.** `docs/usage.md`
   (line 396) gives `sampling.GradientSampler(index, points)` with
   `points = _events.event_points(seq)`. The same document says that a name
   that starts with `_` can change in any release. A public constructor from
   a sequence, or a public `event_points`, fixes it.
3. **One sequence has three waveforms.** Between two events:

   - `GradientSampler.sample` (the spectrum, and `pns_levels` off the raster)
     draws a straight line, as pypulseq's `get_gradients` does.
   - `GradientSampler.block_samples` (`pns_levels` on the raster) and the RMS
     of `grad_peaks` use 0.
   - The junction step of `grad_peaks` joins the last value of one event to
     the first value of the next.

   Section 1, item 1 shows a sequence where the slew of `grad_peaks` is 10
   times lower than the slew of the samples that `pns_levels` uses. Also,
   one block off the raster changes the model of `pns_levels` for the whole
   sequence (`on_raster` False). A caller cannot compare the values of the
   analyses of one sequence without knowing these rules. One documented
   model is necessary, and pypulseq's own `add_block` check ("No delay
   allowed for gradients which start with a non-zero amplitude") assumes 0
   during a delay.
4. **`GradientPeaks.whole_rms_hz_per_m` is not necessary now.** It exists so
   that a caller does not make a second call for the RMS of the whole file.
   Since PR #45, `gradient_peaks(seq)` keeps its result, so
   `gradient_peaks(seq).axes[axis].rms_hz_per_m` costs nothing.
   pulseq-reports uses the field, so a removal waits for a release that breaks
   callers.
5. **The runs of `pns.safe.levels` use the times of the samples.** `start`
   and `end` of a run are the times of its first and last sample
   ([analyses.py:378](../../src/pulseq_analysis/analyses.py#L378) and 379).
   A RUNS series is "true from `start[k]` to `end[k]`", so a run of one sample
   has no length, and each run is one `dt` too short. The `pns_total` series
   of the same call uses the edges of its bins. Runs from
   `first - dt / 2` to `last + dt / 2` agree with the bins.
6. **`Series` is the one value of the package that is not read-only**
   (section 1, item 4).

## 7. Order of the fixes

1. One model of the waveform between two events (section 6, item 3). Then
   the junction steps (section 1, item 1), with a test of a delayed event
   after a block that ends at a value that is not 0, and that sequence in
   `_AGREEMENT_SEQUENCES`.
2. The spectrum: the end padding and one rule for the sample count (section
   1, items 2 and 3), with a test whose length is not a whole number of hops.
   The oracle follows the new rule.
3. The tests of sections 5.1 and 5.2.
4. `FrozenDict` for `Series` (section 1, item 4), and section 1, item 5.
5. The documentation errors of section 3, in the release task 2.5 or before
   it.
6. The duplication and the cost of a window (sections 2 and 4, item 1), and
   the unnecessary tests and dead test code of sections 5.3 and 5.4.
7. The choices of section 6, items 1, 2, 4 and 5. They change what callers
   get, so pulseq-checks and pulseq-reports must agree first.
