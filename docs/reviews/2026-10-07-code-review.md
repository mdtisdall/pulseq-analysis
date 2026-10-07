# Code review, 2026-10-07

A review of the whole package at commit `83af015`, after the fixes of
[the review of 2026-10-06](2026-10-06-code-review.md)
(`docs/plans/third-review-fixes.md`) and the documentation split of #65 and
#66. The release task 2.6 of that plan (`0.1.0rc6`) is not done yet.

The review looks for these things:

- Code that is incorrect, mis-documented, duplicative or inefficient.
- Speed improvements that do not add much complexity, and simplifications that
  do not change much of the function.
- Tests that are unnecessary, that do not test what they claim, or that test
  only code outside this repository.
- Parts of the API that do not fit the goals of the project.

It does not repeat a finding of an earlier review that is fixed. The line
numbers are of commit `83af015`.

Method:

- A read of every module of `src/pulseq_analysis/`, each test file,
  `TESTS.md`, `docs/usage.md`, `docs/implementation.md`, `README.md` and
  `CHANGELOG.md`.
- Random tests against the oracle `tests/oracles/waveform.py`:
  - 300 new seeds of `_random_gap_sequence`, each with 40 windows;
  - 200 sequences off the raster;
  - 240 sequences through `write` and `read`;
  - 600 random sequences through `sample`, `block_samples` (with `skip` and
    `count`) and `pns_levels` with chunks of 1, 3 and 7 samples.

  No result differed from the oracle, except the cases of section 1.
- 101 single-line mutations of a copy of `src/`. 32 of them pass all the
  tests, and about 10 of these cannot change a result (section 5).
- Small scripts against the pinned pypulseq fork. The findings marked
  *reproduced* were run against `src/` of `83af015`.

At this commit, `nix develop --command scripts/check` passes: ruff, 1049
tests, the `TESTS.md` check (354 entries) and shellcheck.

## 1. Correctness

1. **A kept result does not see `mod_grad_axis`, `flip_grad_axis` or
   `set_block`** (*reproduced*). The stamp of
   [_kept.py:45](../../src/pulseq_analysis/_kept.py#L45) compares the identity
   of `grad_library`, `block_events` and `block_durations`, the number of
   blocks, the last block ID and the raster. pypulseq's public
   `seq.mod_grad_axis(axis, scale)` changes the data of `grad_library` in
   place, and `set_block` on an existing ID changes a block in place. None of
   the stamp's values changes.

   - On `build_repeating(3)`: `gradient_peaks` gives the x peak 714 286 Hz/m.
     After `seq.mod_grad_axis("x", 0.5)` it gives the kept 714 286 Hz/m. A new
     object with the same change gives 357 143 Hz/m.
   - The same holds for `pns_levels` (2.65e7 Hz/T kept, against 1.33e7) and
     for `sequence_index` after `set_block(2, make_delay(30e-3))` (`end_s`
     0.0466 kept, against 0.0616).

   The documents warn only about "a block replaced in place".
   `mod_grad_axis` is the usual pypulseq call to turn off an axis (for
   example `mod_grad_axis("y", 0)` to remove the phase encoding), so the
   wrong values come with no warning. Fix: add a fingerprint of the data of
   the gradient library to the stamp, O(K), for example
   `hash(tuple(seq.grad_library.data.values()))`. Also name the three
   functions in the documents.

2. **The step after the last point at the end of the sequence depends on one
   ulp** (*reproduced*). `_axis_columns`
   ([grad_peaks.py:409](../../src/pulseq_analysis/grad_peaks.py#L409)) has
   `final_step = ... lt[-1] < index.end_s`, and the range test of
   `_evaluate_axis` (lines 905-910) and of the oracle is `lo <= t < hi`. No
   one of them uses `TIME_TOLERANCE`. `docs/implementation.md` section 1.7
   says that a last point at the end of the sequence gives no step. But
   whether `(start + delay) + shape_dur` rounds to `end_s` or to one ulp
   before it decides the result.

   A trapezoid, then an extended trapezoid that ends at A = 31 932 Hz/m at
   the end of the sequence (`times=[0, 1e-4, 6e-4]`):

   | | Largest slew of x | Block |
   |---|---|---|
   | In memory | 3.19e9 Hz/m/s (the step) | 2 |
   | After `write` and `read` | 1e9 Hz/m/s | 1 |

   9 of 100 such files count the step after `read`. Fix: `lt[-1] < index.end_s
   - TIME_TOLERANCE`, and the same tolerance at the end of a range in
   `_evaluate_axis`, in the oracle and in section 1.7.

3. **`block_samples` gives 0 at the last point of an event after a one-ulp
   rounding** (*reproduced*). `_kept_samples` and `_event_samples`
   ([sampling.py:236-287](../../src/pulseq_analysis/sampling.py#L236)) give 0
   from the first local time `(j + 0.5) * dt` after the last point of the
   event. When the last point is at a sample time and the local product
   rounds one ulp above it, that sample is 0. `_write_gaps` (lines 510-516)
   writes the ramp only where the global time is strictly in the piece, and
   the global time can round to the end of the piece. So no code writes the
   value back. The trigger is a gradient delay off the raster by half a raster
   time, which `add_block` accepts. 8 of 8 such cases give 0 in place of the
   end value A, which moves the falling edge of the PNS input one sample
   earlier. Fix: count a sample within `TIME_TOLERANCE` after the last point
   as at the point (in `_kept_samples` and in the `at_last` test of
   `_event_samples`). With this fix the 8 cases and all the tests pass.

4. **At a step inside one event, `block_samples` takes the later value**
   (*reproduced*). `docs/implementation.md` section 1.3 and `sample` take the
   value before a step. `_event_samples` (lines 263-287) takes the value
   after it, when the step is at a sample time. A natural case: pypulseq gives
   an arbitrary gradient of 4 samples or fewer its own time shape, so
   `get_block` puts the points `(tt[-1], wf[-1])` and `(shape_dur, last)` at
   one time. For a 3-sample `make_arbitrary_grad`, `block_samples` gives
   15 000 (`last`) and the oracle gives 20 000 (`wf[-1]`). Fix, which is also
   a simplification: the body of `_event_samples` becomes
   `_polyline_values(points_t, points_v, t)`, the rule of `sample`. This
   removes about 25 lines. The time per sample does not change, and all the
   tests pass. The docstring of `block_samples` (lines 307-308) then needs the
   same change.

5. **`rf_events`, `grad_events` and `adc_events` keep the block cache off
   across `yield`** (*reproduced*). `_first_events`
   ([seq_index.py:199](../../src/pulseq_analysis/seq_index.py#L199)) is a
   generator inside `block_cache_off`. A generator that a caller does not run
   to its end leaves `seq.use_block_cache` False:
   `it = grad_events(seq, index); next(it)` changes the flag of the caller's
   sequence. Two such generators at the same time also restore the flag in the
   wrong order. Fix: turn the cache off around each `get_block` call, not
   around the loop.

6. **`Series.from_obj` and `decode_array` can raise `OverflowError`.** The
   contract is one exception type, `ValueError`. A `"length"` of `10**30`
   ([series.py:458](../../src/pulseq_analysis/series.py#L458)) and a
   coordinate of `10**400` (`_float_from_json`, line 494) raise
   `OverflowError`. Fix: catch it in `_float_from_json`, and refuse
   `length * itemsize > sys.maxsize`.

7. **A kept result skips the signature check of `pns_levels` and
   `gradient_spectrum`.** These two functions call `refuse_unsigned` (through
   `sequence_index`) only when they build a result. After one call,
   `seq.signature_value = ""` and a second call give the kept result with no
   error. `gradient_peaks` and `block_gradient_values` raise `ValueError` in
   the same case. The three functions also check in different orders:
   `gradient_peaks` and `gradient_spectrum` call `refuse_rotations` before
   they check their arguments, and `pns_levels` after. Fix: one order in all
   of them (arguments, then the refusals, then the kept result), or document
   the order.

8. **The read-only rule has two holes** (low severity). Each frozen array owns
   its data, so `a.flags.writeable = True` makes it writable again, and then a
   change reaches every caller of the kept result. A `Series` from `pickle` or
   `copy.deepcopy` has writable arrays and no new check, so its rules can
   break after the copy. Fix: a `__reduce__` of `Series` that goes through
   the constructor. Optionally, freeze with `np.frombuffer(a.tobytes(),
   dtype)`, whose `bytes` base cannot become writable, in one `_freeze`
   helper in place of the 7 copies of the rule.

## 2. Efficiency

Each change below gives the same values, bit for bit, unless it says
otherwise. The times are on an Apple M1 Max.

1. **`_event_values` is about 2/3 of the cost of each unique event.**
   The Python loop over the K events
   ([grad_peaks.py:262-283](../../src/pulseq_analysis/grad_peaks.py#L262))
   takes 255 ms on `build_worst(20000)` (K = 20 002). The reads of the events
   take 139 ms. A vectorised form over the pooled points (`np.repeat`,
   `np.maximum.reduceat`, `np.add.reduceat`, about 25 lines) takes 2.5 ms.
   The integral differs by at most 4e-16 (the order of the sum). The first
   call of `gradient_peaks` on the worst case goes from about 0.39 s to
   0.12 s.

2. **`_vector_candidates` can be about 1.8 times faster.** It is 54 of the 76
   ms of the first call on `build_repeating(20000)`.
   - Line 635: `np.unique` sorts three sorted runs. `np.concatenate` with
     `sort(kind="stable")` and a mask takes 0.6 ms, not 9.8 ms.
   - `_limit_before` and `_limit_after` each run a `searchsorted`. For a
     polyline with no step, which is most axes, the values after are the
     values before, except at the first and the last point.

   This makes the step 57 → 31 ms. (`np.interp` is faster again, but changes
   the last bits and breaks the ties with the oracle.)

3. **`gradient_spectrum` is 75 % FFT.** `scipy.fft.rfft` in place of
   `np.fft.rfft` ([grad_spectrum.py:309](../../src/pulseq_analysis/grad_spectrum.py#L309))
   is 21 % faster (1.11 → 0.88 s on `build_repeating(20000)`). The result
   differs by at most 1.9e-16, and all the spectrum tests pass. scipy is a
   dependency already. With `workers=-1` it is 2.6 times faster, but the
   threads change the last bits, so the test that one chunk equals many
   chunks fails. That needs a decision on bit-exact chunks.

4. **`sequence_index` reads the block dict five times.** `column()`
   ([seq_index.py:141-157](../../src/pulseq_analysis/seq_index.py#L141)) runs
   one generator over `block_events.values()` for each column: 52 of 63 ms for
   100 000 blocks. One `np.array(list(be.values()), dtype=np.int32)`, then
   slices, takes 13 ms. `np.fromiter(block_durations.values())` in place of a
   lookup for each key takes 1.4 ms, not 5.1 ms. The index then takes about a
   third of its time now.

5. **The loop over the unique pairs of `block_samples`**
   ([sampling.py:433-445](../../src/pulseq_analysis/sampling.py#L433)) does a
   mask over all the blocks of the part for each pair. One gather over a pool
   of the pairs (about 10 lines, no mask, no `np.tile`) is 5 % faster on the
   scale sequences and 35 % faster on a sequence with a new event in each
   block of 3 samples.

6. **The cache key of `block_samples` can be `(event, dt)`, not
   `(event, n, dt)`** (lines 99-101, 417-429). The samples depend on `n` only
   through `min(n, samples to the last point)`, so `samples[:n]` gives them.
   One event in blocks of different lengths is then made once, and a 1-D
   `np.unique` replaces `np.unique(pairs, axis=0)`. Optionally, keep only the
   events that play in more than one block: an event that plays once costs
   the same either way, and the cache then does not grow with K (section 3,
   item 2).

7. **`has_gradients(index)`** scans 3N values
   ([seq_index.py:76](../../src/pulseq_analysis/seq_index.py#L76)).
   `index.grad_first.size > 0` is the same test in O(1).

## 3. Mis-documentation

1. **`README.md` installs a release that does not have the documented API.**
   It pins `v0.1.0rc5` (lines 14-34). That tag has `grad_limits.py` and
   `pns.py`, and no `grad_peaks.py`, `hardware_from_asc`, `bin_s` or
   `gradient_sampler`. So the example of the README fails at its import, and
   each name of `docs/usage.md` is unreleased. `pyproject.toml` still says
   `0.1.0rc5`. `CHANGELOG.md` has no entry for the 51 commits since that
   tag, and no "Unreleased" section to collect them. Its entry of rc5 refers
   to section 8 of `docs/usage.md` for the units, which is now section 9.
   Fix: task 2.6 of the third plan, or until then a note that the documents
   are of `main`.

2. **Section 3 of `docs/implementation.md` has errors** (it was written in
   #65):
   - Section 3.3 says that the spectrum makes each sample for each window
     that has it. The code samples each chunk one time, and the windows are a
     view with no copy. Only the overlap of two chunks (half a window for
     each 256 windows) is sampled twice.
   - Sections 3.2 and 4 say that all the measurements share the gaps of each
     axis. `grad_peaks` finds its gaps itself; only `GradientSampler`
     (`pns_levels`, `gradient_spectrum`, `gradient_sampler`) shares them.
   - "About 19 µs for each unique event" is put on the reads of the events.
     About 13 µs of it is `_event_values` (section 2, item 1).
   - `pns_levels` is given as O(S) in time and O(chunk) in memory. It also
     costs about 26 µs for each unique event (`build_worst` takes 1.48 s
     against 0.96 s for the same number of samples), and its sample cache
     holds the samples of each unique event: 16 MB for 1000 different
     arbitrary gradients of 2000 samples. The chunk is about 30 000 samples
     or one bin, whichever is longer, so a `bin_s` of 2 s gives chunks of
     200 000 samples (34 MB).
   - The spectrum's memory is about 55 MB at the defaults (measured, and the
     comment at `grad_spectrum.py:297`), not 40 MB.
   - The cost of `sample` leaves out the first call: `gradient_sampler(seq)`
     makes a new sampler each time, and its first `sample` on an axis scans
     all B blocks (`_event_blocks`). The summary table gives the memory as
     O(Q), where the text says O(Q + points).
   - Sections 2.1 and 3.3 say that an edge block of a window is within half
     a raster time of the edge, "one or two at each edge". The line across a
     short gap starts up to `dt + TIME_TOLERANCE` before its event, and it
     can cross blocks that are shorter than `dt`. The code uses the right
     extent; the text does not.

3. **A `FrozenDict` equals a `dict` with the same items in any order**
   (`dict.__eq__`), not "in the same order" (`docs/implementation.md`
   section 5). Only `==` of a result checks the order.

4. **"No result" is too broad** (`docs/usage.md` section 2: "Its numbers are
   0.0 and its arrays are empty"). A `PnsLevels` with `NO_GRADIENTS` keeps
   `dt_s` and `bin_samples` and has `peak_time_s` `None`. `GradientPeaks`
   keeps `range_s`, and `GradientSpectrum` keeps its arguments.
   `block_gradient_values` of a sequence with no gradients gives zero arrays
   of length N, with no `reason`.

5. **Docstrings that do not agree with the code:**
   - `GradientPeaks` ([grad_peaks.py:135](../../src/pulseq_analysis/grad_peaks.py#L135)):
     `reason` is None "when the range has at least one gradient event". A
     window that has only a ramp, a line or a step also gives None (a window
     of 101-104 µs in the delay block of `long_gap_sequence` gives the peak
     24 000 Hz/m). Section 2.1 of `docs/implementation.md` gives the rule
     correctly.
   - `_AxisColumns` (line 337) says that "the first six" columns go to
     `block_gradient_values`. Five do.
   - `_build_polyline` (lines 499-502) reads as if it adds the neighbour
     events and the end steps. It adds the end steps only at the ends of the
     axis, and the caller adds the neighbours.
   - `extensions.py:19` and `docs/usage.md` section 8 say that each
     measurement calls the refusals "first". See section 1, item 7.

6. **The descriptions of the analyses, which are the contract of the value:**
   - `gradient.peaks` ([analyses.py:185](../../src/pulseq_analysis/analyses.py#L185))
     says that the peak, the slew and the RMS each come "with its block ID and
     its time". The RMS has neither.
   - `gradient.spectrum` (lines 414-417) gives the ramps and the junction
     step, then says that the waveform "is not the line that pypulseq draws
     across each gap". Across a gap of one raster time or less, it is that
     line. The other three descriptions say so.
   - No description says that an unsigned sequence raises `ValueError`, but
     each says that the rotation extension raises `NotImplementedError`.

7. **The kept-result caveat** of `docs/usage.md` section 2 and
   `docs/implementation.md` section 4 must name `mod_grad_axis`,
   `flip_grad_axis` and `set_block` until section 1, item 1 is fixed.

8. **pypulseq-issues in docstrings.** `help()` shows the module docstrings of
   `extensions` (line 58), `grad_peaks` (27), `sampling` (21) and
   `pns_levels` (33), which cite pypulseq-issues. The plan is to remove all
   these references before 0.1.0, so this is listed here only.

## 4. Duplication and simplification

1. **The gap rule and the polyline are made in three places.** The first and
   the last point of each event, the kind of each gap (zero, short or long
   with `TIME_TOLERANCE` and `dt`) and the ramps of `dt / 2` are in
   `sampling._find_gaps` (lines 141-180), `grad_peaks._axis_events` and
   `_axis_columns` (lines 316-331, 375-392) and `grad_peaks._build_polyline`
   (lines 505-516). `GradientSampler.sample` (lines 210-232) makes the
   polyline of `_build_polyline` again. `_polyline_values` is the name of two
   different functions in `sampling` and `grad_peaks`. Fix: one
   `_axis_events` and one gap classifier in `_events.py` (or a new
   `_polyline.py`), used by both modules, and another name for one of the two
   functions. Section 1, items 2 to 4 are each a case where the copies can
   disagree.

2. **`_event_samples` is a second interpolation routine** next to
   `_polyline_values`. See section 1, item 4.

3. **Dead code for an event with no points.** `gradient_offsets` always gives
   two points or more, so the branches at `sampling.py` lines 120-121,
   146-147, 211-212, 241-242 and 257-258 cannot run. Remove them, or assert
   once in `_events._read_points`.

4. **`_sum_of_squares`** (`grad_peaks.py:604-618`) copies the compensated
   `sum` of CPython 3.12 so that the ties of the vector peak match the
   oracle's arithmetic. The production arithmetic follows the test oracle.
   A plain `gx*gx + gy*gy + gz*gz` in both, or ties with a tolerance in the
   tests, removes it.

5. **`_EventData` is kept** (lines 292-296), but after `_BlockData` is made
   nothing reads it, and each call of `gradient_peaks` looks it up. Make it
   in `_kept_block_data` and do not keep it.

6. **Six `WeakKeyDictionary`s** (one for each module) each keep their own
   copy of the stamp. One cache with keys by module would keep one stamp, and
   section 1, item 1 would then be one change.

## 5. Tests

The mutation run: 101 single-line mutations, 32 pass all the tests. About 10
of them cannot change a result. Each of the others below was confirmed with
an input that gives a different result.

| Mutation | Should be caught by |
|---|---|
| `_find_gaps`: a long gap is more than `2 * dt` | a gap between `dt` and `2 * dt` |
| `_find_gaps`: a short gap gets its line only when the earlier value is not 0 | a short gap from 0 to a value |
| `_find_gaps`: ramps only for values above 0 (two mutations) | negative end values |
| `_hardware_key` without `g_scale` | a key test over each field |
| `_vector_candidates` without `after[times == hi] = 0.0` | a window that ends at a step up |
| `_axis_columns` without the slew time of a zero event | `block_gradient_values` of a zero event |
| `_range_result`: vector tie gives the first tied block | a hand-made tie where a later block has the earlier time |
| `decode_array` without the `unused_data` check | bytes after the gzip stream |
| `_A_SUM_TOLERANCE` 0.001 → 0.01 | `a1 + a2 + a3 = 1.005` |
| dtype limits `<` for `<=` | 255 and 65 535 unique events |
| `_evaluate_axis`: the order of a step and a segment | a tie of a step and a segment in a window |

1. **The gap model of `GradientSampler` is tested only on positive values
   and on two gap lengths.** Each sequence of `gap_sequences.py` and of the
   gap helpers of `test_sampling.py` has positive end values, and each gap is
   one raster time or 49 raster times or more. `_random_gap_sequence`, which
   has random signs and delays of 1, 2, 3 and 7 raster times, goes only to
   `gradient_peaks`. So four mutations of `_find_gaps` (the first three rows
   of the table) pass, and two of them change the PNS input. Fix: give the
   seeds of `_random_gap_sequence` and negated copies of the gap sequences to
   the oracle comparisons of the sampler, PNS and the spectrum, and add a gap
   of 1.5 raster times.

2. **`test_the_defaults_are_those_of_pypulseq`**
   ([test_grad_spectrum.py:390](../../tests/test_grad_spectrum.py#L390))
   compares an object with itself. pypulseq's defaults give the same kept key
   as a call with no arguments, so `explicit is default`, and each
   `array_equal` is true by construction. What is left is a guard on
   pypulseq's signature. `TESTS.md` says that it gives "the same spectrum as a
   call with no arguments". Fix: compare `_compute_spectrum` with the
   explicit values, or keep only the constants and label the test as a guard
   on pypulseq.

3. **The key of the PNS hardware is tested for `stim_limit` only**
   (`test_pns_levels_computes_again_for_another_label_or_value`,
   `test_pns_levels_kept.py:217`). Two structs that differ only in `g_scale`
   (or another field) could share one kept result. Fix: parametrize over the
   8 fields of `_HW_FIELDS`.

4. **A window that ends at a step up, and the slew time of a zero event,
   are not tested** (rows 5 and 6 of the table). The zero event is the
   k-space centre of a phase-encode loop, so it is common. Fix: one test with
   hand values for each.

5. **The oracles share code with the package.**
   - `oracles/waveform.values_at` is, line for line, the step branch of
     `sampling._polyline_values`.
   - `_vector_peak` credits a block with the same two `searchsorted` calls as
     `_vector_candidates`.
   - `_assert_block_values_agree_with_gradient_peaks` makes the vector tie
     rule of `_range_result` again, so a wrong rule passes (row 7 of the
     table).

   Fix: write `values_at` another way (for example a loop over the
   segments), and add one hand-made vector tie.

6. **Tests that repeat others:**
   - `test_example_hardware_for_spin_echo` (`test_pns_levels_kept.py:34`)
     repeats `test_summary_matches_calculate_pns_within_the_fork_tolerance[spin_echo]`
     and adds only "highest on y".
   - `test_grad_dense_numbering_follows_gx_then_gy_then_gz_within_a_block`
     (`test_seq_index.py:150`) is a subset of
     `test_dense_numbering_follows_the_first_use_and_not_the_order_in_the_libraries`.
   - `test_gradient_sampler_equals_the_sampler_of_the_constructor`
     (`test_sampling.py:1174`) compares the function with its own one-line
     body.
   - The prune of task 1.5 of the third plan is not complete:
     `test_a_gradient_on_one_axis_has_a_prediction`
     (`test_pns_levels_kept.py:115`) and the copy `_points_from_grad_events`
     (`test_events.py:38`) are still there.
     `test_event_values_of_the_points_equal_the_values_of_gradient_points`
     takes its expected values from `_polyline_values`, the function under
     test.
   - Smaller overlaps:
     - `test_the_levels_from_pickle_and_deepcopy_equal_the_original` and
       `test_levels_compare_by_value`;
     - `test_pns_levels_is_a_frozen_dataclass`, which `test_equality` covers;
     - `test_gradient_points_trapezoid` and `test_gradient_points_arbitrary`,
       which the tests of `gradient_offsets` cover;
     - `bin_samples_for(0, dt, 10.0 / 1624) == 615` in two tests;
     - `test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file`,
       which repeats the body of `hardware_from_asc` (still open from the
       last review).

7. **`TESTS.md`.** The contents list the sections in an order that is not
   their numbers. The tests of `asc.py` are in `test_pns_levels_kept.py`,
   under "The kept PNS levels". The pypulseq-issues references (22 in
   `TESTS.md`, 22 in the tests, and the names `test_*_pypulseq_issue_12_*`)
   go with the cleanup before 0.1.0.

8. **Two slow tests** (the suite takes 6 s):
   `test_matches_oracle_on_long_sequences` (0.97 s) can get many chunks from
   `CHUNK_WINDOWS = 4` on a short sequence, as
   `test_matches_scipy_spectrogram` does.
   `test_a_window_gives_the_same_result_with_and_without_the_kept_data`
   (0.83 s for 600 windows) needs about 30 windows for each sequence.

No new test checks only pypulseq. The tests of `write` and `read` and of the
timing check are labelled as guards on the pin. After item 2,
`test_the_defaults_are_those_of_pypulseq` is one too.

## 6. The API and the goals of the project

1. **Names that the interface needs are not in the two documents.**
   `docs/usage.md` says that a name the documents do not give can change in
   any release. But:
   - `SeriesKind`, which a caller needs to make a `Series`, is not named.
   - The `Analysis` protocol, which pulseq-checks imports (`run.py`,
     `registry.py`), is not named.
   - `FrozenDict`, the type of each dict of a result, is named only by its
     private path `_equality.FrozenDict`.

   Fix: name them, and export `FrozenDict` from a public module. Give `_` to
   the public names that no document needs (for example
   `asc.INCLUDE_LINE`).

2. **`AnalysisSpec` does not check the fields that a runner uses.**
   pulseq-checks branches on `spec.cost == "fast"` and matches the strings of
   `spec.rasters`. `cost="medium"`, a wrong raster name (which turns off the
   raster guard of the runner with no message), `version="one"`, `id=""` and
   `params` with a repeated name are accepted. A NaN default is accepted,
   although the defaults must go into JSON. "fast" and "slow" are not
   defined. Fix: check that `id` is a str that is not empty, `version` is an
   `int` of 1 or more, `cost` is "fast" or "slow", each raster is a known
   name, `params` is a tuple of unique str, and a float default is finite.
   Define the two costs in the documents: "fast" grows with the blocks and
   the unique events, "slow" with the duration.

3. **The JSON form of a `Series` has no format version, and refuses unknown
   keys** ([series.py:497-506](../../src/pulseq_analysis/series.py#L497)).
   A field added later breaks each older reader, and a reader cannot tell the
   versions apart. Before 0.1.0 is the cheap time to add `"format": 1`, or to
   document that the keys do not change.

4. **`registry()` is all or nothing.** One entry point of another package
   that does not load makes `registry()` raise, so a runner cannot run any
   analysis, also those of this package. This is documented, but it is
   fragile for pulseq-checks. Fix: give the errors next to the analyses that
   loaded, or an argument to skip them.

5. **`Series` treats its inputs unevenly.**
   - `meta` takes `np.float64` (a subclass of `float`) but refuses
     `np.float32`, `np.int64` and `np.bool_`, while the coordinates take
     each `numbers.Real`. So `meta={"peak": a.max()}` of a float32 array
     raises `TypeError`.
   - A str subclass in `name`, `unit` or a key stays, so
     `from_obj(to_obj(s)) != s`.
   - `ENVELOPE` takes complex `min` and `max`, two dtypes, and `min > max`;
     `POINTS` takes a complex `coord`. `RUNS` refuses a complex `start`.

   Fix: `str()` of each string, `.item()` of a numpy scalar, a real dtype for
   `min`, `max` and `coord`, and `min <= max`.

6. **`asc` ignores some `$INCLUDE` lines with no message**
   ([asc.py:16](../../src/pulseq_analysis/asc.py#L16)): a quoted name with
   spaces, a comment after the name, and `$include` in lower case. The user
   then gets a `KeyError` from `asc_to_hw`. An included field also wins over
   a field that the file sets after the `$INCLUDE` line. That is documented,
   but the order of the file would give the other value. Fix: match these
   forms, or raise for a `$INCLUDE` line that does not match.

7. **Robustness against a file from another source:**
   - The decompression limit of `decode_array` is the `"length"` of the
     object, which its producer gives. A 64 KB text with a true length
     decodes to 50 MB. An optional `max_bytes` would bound it.
   - `_dense` (`seq_index.py:124-132`) allocates in proportion to the largest
     event ID. One ID of 10^8 takes 900 MB. Use `np.unique` when the largest
     ID is much more than the number of blocks.

## 7. Order of the fixes

1. Section 1, items 1 to 5. These are wrong values or a changed caller
   state. Item 1 is the most likely to reach a user.
2. Section 3, items 1 and 2, and the documents of section 1, items 1 and 7:
   the README, the changelog and the cost section that #65 added.
3. Section 5, items 1 to 5: the tests that let the bugs of section 1 and the
   mutations through.
4. Section 6, items 1 to 3, before 0.1.0, because they change the contract.
5. Section 2, items 1 to 4: a large gain for a small change.
6. Section 4: the shared gap rule (item 1) after the fixes of section 1, so
   that the fixes are made one time.
7. The other items.
