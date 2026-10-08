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

## 8. Status at 0.1.0rc6

Written on 2026-10-07, for the release `0.1.0rc6`. The numbers of the items
are those of sections 1 to 6 of this review. A bullet of section 3, 4 or 5 is
named by its words, and a bullet of section 5 by the test or the mutation that
it names. The tasks are those of `docs/plans/third-review-fixes.md` (the third
plan). The names in sections 1 to 7 are those of `efe4f46`. This section uses
the names of `0.1.0rc6` where a name has changed. A name of a test is the name
on `main` at the release.

The fourth plan (`docs/plans/fourth-review-fixes.md`) changed some of this
code again. Where a later change makes the first fix different, the table says
so.

The pull requests of the third plan:

| Task | PR | Branch |
|---|---|---|
| 1.1 | #51 | `test/third-review-test-fixes` |
| 1.2 | #52 | `fix/spectrum-ends` |
| 1.3 | #53 | `fix/third-review-small-fixes` |
| 1.4 | #54 | `docs/third-review-doc-errors` |
| 1.6 | #56 | `refactor/block-columns` |
| 1.7 | #55 | `refactor/third-review-small-duplicates` |
| 1.5 | #57 | `test/third-review-test-prune` |
| 2.1 | #58 | `feature/gradient-gap-model` |
| 2.2 | #60 | `feature/analysis-rasters` |
| 2.3 | #61 | `feature/public-sampler` |
| 2.4 | #62 | `feature/pns-runs-at-edges` |
| 2.5 | #63 | `feature/drop-whole-rms` |
| 2.7 | #64 | `refactor/value-dataclass` |
| 2.6 | task 2.7 of the fourth plan, this release | `docs/release-0.1.0rc6` |

The pull request of the plan is #50. #59 added task 2.7 to it.

The status is "done", "done in another way" (the result differs from the
proposal of this review) or "not changed" (with the reason).

### 8.1 Section 1: correctness

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 1.1 | A junction into a delayed event loses its steps | Done. One model of the waveform between two events, the model of MATLAB Pulseq (decision U1): a step across a zero gap, a line across a gap of one raster time or less, and a ramp to 0 and a ramp from 0 of half a raster time across a longer gap. `gradient_peaks`, `block_gradient_values`, `GradientSampler.sample` and `GradientSampler.block_samples` all use it, and `tests/oracles/waveform.py` has its own code for it. The delay of an event after a block that ends at a value that is not 0 now has the ramp to 0 and the ramp from 0, each credited to its block. Tests: `test_a_long_gap_gives_the_ramps_of_its_ends_credited_to_the_blocks_of_their_events` and `test_a_first_value_that_is_not_zero_after_a_delay_has_a_ramp_from_zero_in_its_block`. The section "The gradient waveform" of `docs/implementation.md` gives the rule. | 2.1, #58 |
| 1.2 | The spectrum attenuates the gradients at the end of a sequence | Done in another way. The end padding is the fewest zeros, at least half a window, that make the padded waveform one window plus a whole number of hops. The proposal of this review (the last sample at the centre of a window) cannot hold for each length, because the start padding fixes the grid of windows. Now each sample, the last one too, is within half a hop of the centre of some window, as a sample in the middle of the sequence is, for a window of an even and of an odd number of samples. Test: `test_gradients_at_the_end_are_attenuated_no_more_than_in_the_middle` (N = 5000, 6000, 7000 and 7499 samples, an even and an odd window). | 1.2, #52 |
| 1.3 | The spectrum counts the samples with its own rule | Done. `sampling.sequence_samples(index, dt)` is the one rule for the number of samples (the sum of the block lengths on the raster, and `ceil((end_s - 1e-10) / dt)` off it). `pns_levels` and `gradient_spectrum` both call it, and the oracle of the spectrum follows it with its own code. Tests: `test_sequence_samples_on_the_raster_is_the_sum_of_the_block_lengths` and `test_sequence_samples_off_the_raster_is_the_ceil_of_the_end`. | 1.2, #52 |
| 1.4 | A `Series` can be changed after its checks | Done. `Series.arrays` and `Series.meta` are `FrozenDict`s, so a change raises `TypeError`. Since #69, a copy from `pickle` or `copy.deepcopy` is made through the constructor and is checked too. | 1.3, #53 (the copy: #69) |
| 1.5 | An `$INCLUDE` cycle recurses until `RecursionError`; `decode_array` decompresses all the data before it compares the length | Done. `read_gradient_asc` raises `ValueError` that names the cycle (`test_asc_files_that_include_each_other`, `test_asc_file_that_includes_itself`; a file that two branches include is not a cycle). `decode_array` decompresses at most `length * itemsize + 1` bytes (`test_decode_array_does_not_decompress_more_than_length_needs`). The fourth review (6.7) asked for an optional `max_bytes` for a producer that gives a false `length`, and #82 added it. | 1.3, #53 (`max_bytes`: #82) |

### 8.2 Section 2: efficiency

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 2.1 | A window of `gradient_peaks` costs O(K) and two `get_block` calls | Done. The values of each block are calculated one time for each sequence and kept in `_BlockData`, with a prefix sum of the RMS integral. A window is an `argmax` over the blocks that lie whole in it. A block that a window edge cuts is made from the kept event points, with no `get_block`. A window of one block on 20,000 unique events: 0.045 ms (0.194 ms before). Test: `test_a_window_of_gradient_peaks_calls_no_get_block`. The values do not change, except the RMS of a window, in the last digit. | 1.6, #56 |
| 2.2 | Each window calculates the vector peak of each triple again | Done. The vector peak of each block, with its time, is part of `_BlockData`. | 1.6, #56 |

### 8.3 Section 3: mis-documentation

| Finding | Status | Task / PR |
|---|---|---|
| The module docstring of `seq_index` says that only three functions call `get_block` | Done. The docstring says which functions call it. | 1.4, #54 |
| The docstring of `gradient_peaks` says that `_events.event_points` calls no `get_block` | Done. It says that `get_block` is called one time for each unique gradient event. | 1.4, #54 |
| `docs/usage.md` and the docstring of `gradient_peaks` say that the cost of a window is the number of blocks in the window | Not wrong after the fix of the cost (review 2.1): a window costs the blocks that it touches, with no term in the number of unique events. Section 3 of `docs/implementation.md` gives the costs. | 1.6, #56 |
| The module docstring of `grad_spectrum` says that the ends are not attenuated | Done. It gives the end padding of item 1.2. | 1.2, #52 |
| The module docstring of `sampling` names `pypulseq.eps` | Done. It names `seq_utils.TIME_TOLERANCE`. | 1.4, #54 |
| `docs/usage.md` says that the measurements use `BlockDurationRaster` | Done. The rule for `AnalysisSpec.rasters` (item 6.1) is in the documents: each raster of the file whose value changes the value of the analysis. | 2.2, #60 |
| `grad_peaks.py:45` is 157 characters long | Done for that line, which is wrapped. Not changed: no check of the line length (the default rules of ruff have none), and some other lines of `src/` are longer than 100 characters. | 1.4, #54 |
| `TESTS.md` has text that is not true (ten statements) | Done. #54 corrected each of the ten. | 1.4, #54 |
| The docstring of `test_compute_of_gradient_spectrum_passes_its_arguments_on` says that `to_series` gives the arguments | Not changed. The plan listed the correction (task 1.1), but the docstring on `main` is the same, and the test does not call `to_series`. | — |

### 8.4 Section 4: duplication and simplification

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 4.1 | Two calculations of the same values for each block | Done, as the proposal. The columns of each block are calculated one time for each sequence and kept, and `block_gradient_values` and `gradient_peaks` both read them. `_axis_slice_stats`, the vector peak loop and `_block_vector_peaks` are removed. | 1.6, #56 |
| 4.2 | `_hardware_key` uses `stim_thresh`, which the model does not use | Done. The key uses the 8 fields of each axis that the model uses. Two structs that differ only in `stim_thresh` share one kept result (`test_pns_levels_ignores_stim_thresh_in_the_hardware_key`). `_check_hardware` still requires `stim_thresh`, as pypulseq does. | 1.7, #55 |
| 4.3 | `_load(ep, group)` and `_add(...)` are general helpers with one caller | Done. `registry()` loaded and added in its own loop (#55). Task 2.4 of the fourth plan (#83) added a private `_load(ep)` with one caller, for the rule of `registry(strict=False)`. It has no `group` argument. | 1.7, #55 |

### 8.5 Section 5: tests

#### 8.5.1 Tests that do not test what they claim

The tests of this group were corrected in task 1.1 (#51), so that each fails on
the change of `src/` that it guards, except where the table says more. Section
6.2 of the plan names the mutation that each test must fail on.

| Test or mutation of the review | Status | Task / PR |
|---|---|---|
| `test_series_refuses_bad_arrays` | Done. Each ENVELOPE case has a `coord_end` that is valid for its arrays, and a `match=` of its own message. | 1.1, #51 |
| The order of first use in the index | Done. `test_dense_numbering_follows_the_first_use_and_not_the_order_in_the_libraries` has events that are added to the libraries in another order. | 1.1, #51 |
| A threshold equal to the peak | Done. `test_a_threshold_equal_to_the_peak_gives_an_interval`. | 1.1, #51 |
| `test_pns_levels_takes_numpy_and_fraction_thresholds` | Done. The float call is not the kept object. | 1.1, #51 |
| `test_example_hardware_for_spin_echo` | Done in another way. #51 compared it with `seq.calculate_pns` of the fork. Task 1.6 of the fourth plan (#74) then deleted it, because `test_summary_matches_calculate_pns_within_the_fork_tolerance[spin_echo]` covers it. | 1.1, #51 (deleted by #74) |
| `test_gradients_at_the_end_are_not_attenuated` | Done. It went away. `test_gradients_at_the_end_are_attenuated_no_more_than_in_the_middle` replaces it (item 1.2). | 1.2, #52 |
| `_assert_matches_oracle` of `test_grad_peaks.py` | Done. It compares `peak_time_s`, `slew_time_s`, `vector_peak_time_s` to 1e-12 s, and the credited blocks. | 1.1, #51 |
| `test_a_window_gives_the_same_result_with_and_without_the_kept_data` | Done. The snapshot keeps its data across the 30 windows, and a new snapshot gives the result with no kept data. | 1.1, #51 |
| The agreement of `block_gradient_values` and `gradient_peaks`, and the delayed junction | Done. The junction time is the time of the event, and the sequences of the delayed event are in the agreement test. The waveform model of #58 then gave a new set of sequences with hand-computed values. | 1.1, #51 (and 2.1, #58) |
| The raster of `block_gradient_values` | Done. `test_block_gradient_values_use_the_gradient_raster_of_the_file_not_of_seq_system`. | 1.1, #51 |
| The raster tolerance, `ON_RASTER_TOLERANCE = 0.4` | Done. `test_raster_block_lengths_tolerance_is_a_millionth_of_a_sample`. | 1.1, #51 |
| `test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples` | Done. `test_an_off_raster_sequence_that_ends_at_a_whole_number_of_samples_has_that_number` has a sequence whose `end_s / dt` is within 1e-10 of a whole number. | 1.1, #51 |
| `test_subrange_inside_a_gap_matches_pypulseq` | Done. The gap has ends that are not 0. The waveform model of #58 then gave `test_a_subrange_inside_a_long_gap_has_its_ramps_and_zero_and_matches_the_oracle`. | 1.1, #51 (and #58) |
| `test_junction_step_and_segment_of_one_block_with_the_same_slew_give_the_junction_time` | Done. The test is removed as a duplicate of `test_junction_step_equal_to_a_segment_slope_of_its_block_takes_the_credit`. | 1.1, #51 |
| `test_series_not_equal_for_a_different_field_or_array[kind]` | Done. `test_series_not_equal_for_a_different_kind` has POINTS and RUNS with the same arrays. | 1.1, #51 |
| Cases that pass for another reason (`decode_array` base64, `bool` in `from_obj` and in `decode_array`, `test_analysis_spec_raises_...`) | Done. Each has its own case and a `match=`. | 1.1, #51 |
| `test_series_refuses_bad_meta` and the `TESTS.md` text "a numpy number" | Done. `test_series_meta_makes_a_numpy_float64_a_plain_float`. Since #69, `meta` makes every numpy bool, integer and float scalar a Python scalar (`test_series_meta_makes_a_numpy_scalar_a_python_scalar`). | 1.1, #51 (and #69) |

#### 8.5.2 Gaps that the mutation script found

| Line | Mutation | Status | Task / PR |
|---|---|---|---|
| `grad_peaks.py:684` | `junction_max > seg_max` to `>=` | Done. A segment of an earlier block with the slew of a junction step credits the earlier block: `test_segment_of_an_earlier_block_with_the_slew_of_a_junction_step_takes_the_credit`. | 1.1, #51 |
| `sampling.py:107` | `side="right"` to `"left"` for `hi_pos` | Done. #51 added a test of `GradientSampler.sample` with times in a gap that ends at a step. #58 replaced the model of the gaps, and with it that test and this line of code. The oracle comparisons of `sample` (#58, and #71 with more gap sequences) now test gaps that end at a step. | 1.1, #51 (and #58, #71) |
| `series.py:134` | `value = float(value)` to `pass` | Done. `test_series_meta_makes_a_numpy_float64_a_plain_float`. | 1.1, #51 |
| `series.py:325` and `series.py:331` | `>` to `>=`, and `<=` to `<`, in the limits of an ENVELOPE `coord_end` | Done. `test_envelope_coord_end_limits_are_exact_at_the_tolerance`. | 1.1, #51 |
| `pns_levels.py:211` | `abs(sum - 1)` to `sum - 1` | Done. `test_pns_levels_refuses_a_sum_of_the_a_fields_below_1_for_a_sequence_without_gradients`. | 1.1, #51 |
| `pns_levels.py:579` | `>=` to `>` | Done. `test_a_threshold_equal_to_the_peak_gives_an_interval`. | 1.1, #51 |

#### 8.5.3 Tests of code outside this repository, and oracles that copy `src/`

| Finding | Status | Task / PR |
|---|---|---|
| Tests that call no code of the package (`test_time_tolerance`, the gamma of the tests, `test_synthetic_sequences_pass_the_timing_check`, four `FrozenDict` tests) | Not changed. Decision U4: they stay. `TESTS.md` says what each one checks: a constant, the test helpers, or the behaviour that `FrozenDict` gets from `dict`. | 1.5, #57 |
| Tests of pypulseq's `write` and `read` (four tests of `test_extensions.py`) | Not changed. Decision U4: they stay. `TESTS.md` says that they check the pin (`TODO.md`), not the package. The fourth, `test_each_measurement_accepts_a_sequence_after_write`, was removed later (#80), when the refusal of an unsigned sequence moved from each measurement to `snapshot.load`. | 1.5, #57 (the fourth: #80) |
| Tests whose expected value comes from the code under test (`test_events.py`, `test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file`) | Done for `test_events.py`: the event values have hand-computed expected values (#51), and the copy `_points_from_grad_events` and its tests were deleted (#74). Not changed for `test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file`: #74 kept it (moved to `tests/test_asc.py`) because it is the only test of the split `$INCLUDE` layout. | 1.1, #51. Also 1.6 of the fourth plan, #74 |
| Oracles that copy `src/` (`tests/oracles/grad_peaks.py`, `tests/oracles/grad_spectrum.py`) | Done for `grad_peaks`: decision D8 of the third plan. `tests/oracles/waveform.py` has its own code, and the copies `_clip_polyline` and `_vector_peak_in_block` are gone. The oracle of the spectrum follows the new rules of items 1.2 and 1.3 with its own code (#52). The fourth review (5.5) found that `values_at` of the new oracle shared one branch with the package, and #71 rewrote it. | 2.1, #58. The spectrum: 1.2, #52 |
| The conversion with gamma in `_assert_matches_oracle` | Done. The values have no gamma (since `0.1.0rc5`), and the helper and `TESTS.md` no longer say that the test checks a conversion to tesla. | 1.1, #51 and 2.1, #58 |

#### 8.5.4 Unnecessary tests and dead test code

| Finding | Status | Task / PR |
|---|---|---|
| `test_pns_levels.py` and `test_pns_levels_kept.py` overlap | Done. One test of each name is left, the stronger (the one that patches `kept_results` at that time), and the tests that other tests cover are deleted. | 1.5, #57 |
| Duplicates in `test_grad_peaks.py`, `test_seq_index.py`, `test_analyses.py`, `test_sampling.py` and `test_grad_spectrum.py` | Done. Each deleted test was checked against the test that covers it. The fourth review (5.6) found five more of this kind, which task 1.6 of the fourth plan (#74) deleted. | 1.5, #57 (and #74) |
| A slow test: `test_series_round_trip_of_two_million_float32_values` | Done. The round trip uses 2000 values. | 1.5, #57 |
| Dead test code (`gpa` of `write_gradient_asc`, `_write_rotation_file`, the check of duplicate names in `check_tests_md.py`, the `except` branch of `test_package.py`, the unused branches of the synthetic sequences, the resonances of the spectrum oracle, `num_arrays`) | Done. | 1.5, #57 |

### 8.6 Section 6: the API and the goals of the project

| # | Finding | Status | Task / PR |
|---|---|---|---|
| 6.1 | `AnalysisSpec.rasters` does not agree with the code | Done. The rule is: each raster of the file whose value changes the value of the analysis. `seq.index` gives `("BlockDurationRaster",)`, and the four other analyses keep `("GradientRasterTime", "BlockDurationRaster")`. Since #81, each raster name must be one of `analyses.RASTERS`. | 2.2, #60 (the check: #81) |
| 6.2 | The public `GradientSampler` needs a private name | Done. `sampling.gradient_sampler(...)` is the public way to make a sampler, and `docs/usage.md` gives only it. Since #80 it takes a snapshot: `gradient_sampler(snap)`. | 2.3, #61 (and #80) |
| 6.3 | One sequence has three waveforms | Done. See item 1.1. One documented model for each measurement. | 2.1, #58 |
| 6.4 | `GradientPeaks.whole_rms_hz_per_m` is not necessary now | Done. The field is removed. A caller uses `gradient_peaks(snap).axes[axis].rms_hz_per_m`, which is kept. | 2.5, #63 |
| 6.5 | The runs of `pns.safe.levels` use the times of the samples | Done. `PnsInterval.start_s` is `first * dt` and `end_s` is `(last + 1) * dt`, the edges of the samples of the run, as the bins of `pns_total`. A run of one sample has `end_s - start_s == dt` (`test_an_interval_of_one_sample_spans_one_sample_interval_from_its_first_sample_edge`). `peak_time_s` is still the time of a sample. | 2.4, #62 |
| 6.6 | `Series` is the one value of the package that is not read-only | Done. See item 1.4. | 1.3, #53 |

Task 2.7 (#64) is not a finding of this review. The classes that compare by
value now use one decorator, `_equality.value_dataclass`.

### 8.7 What stays

Two items of this review stay as they are, by decision U4 of the third plan:
the tests that call no code of the package (section 5.3), and the tests of
pypulseq's `write` and `read`. `TESTS.md` says what each one checks. One
correction of the plan is not made: the docstring of
`test_compute_of_gradient_spectrum_passes_its_arguments_on` (section 3, last
bullet). The check of the length of a line (section 3, the bullet about
`grad_peaks.py:45`) is not added.
