# Implementation plan: the fixes of the third code review (0.1.0rc6)

Status: draft. Written on 2026-10-07.

## 1. Scope

`docs/reviews/2026-10-06-code-review.md` (in this plan, "the review") gives
the findings of a review of `main` at `efe4f46`. This plan gives the work that
corrects them, and the changes of the interface that the user chose on
2026-10-07 (section 3.1).

The release `0.1.0rc6` is not tagged yet. All the work of this plan goes into
it (U2). Thus task 2.6 of this plan replaces task 2.5 of
`docs/plans/second-review-fixes.md` (in this plan, "the second plan").
`docs/plans/review-fixes.md` is "the first plan".

The work has two phases:

- **Phase 1** corrects the code, the tests and the documents. It changes no
  public name. It changes the values of `gradient_spectrum` (section 5.2).
- **Phase 2** changes the model of the gradient waveform, changes the
  interface, and makes the release. It breaks callers of `0.1.0rc5` more than
  the second plan does (section 8).

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/third-review-fixes-plan` | This plan, and one line for it in `README.md`. No code. |
| 1.1 | `test/third-review-test-fixes` | The tests that do not test what they claim, and the gaps of the mutations (review 5.1, 5.2). |
| 1.2 | `fix/spectrum-ends` | The end padding of the spectrum and one rule for the number of samples (review 1.2, 1.3). |
| 1.3 | `fix/third-review-small-fixes` | A read-only `Series`, a limit on `decode_array`, and an `$INCLUDE` cycle (review 1.4, 1.5). |
| 1.4 | `docs/third-review-doc-errors` | The documentation errors of the review section 3 that no other task changes. |
| 1.5 | `test/third-review-test-prune` | The unnecessary tests and the dead test code (review 5.3, 5.4). |
| 1.6 | `refactor/block-columns` | One calculation of the values of each block, and no `get_block` for a window (review 2, 4.1). No value changes. |
| 1.7 | `refactor/third-review-small-duplicates` | `_hardware_key` without `stim_thresh`, and the helpers of the registry (review 4.2, 4.3). |
| 2.1 | `feature/gradient-gap-model` | One model of the gradient waveform, the model of MATLAB Pulseq (review 1.1, 6.3). |
| 2.2 | `feature/analysis-rasters` | A rule for `AnalysisSpec.rasters` (review 6.1). |
| 2.3 | `feature/public-sampler` | A public way to make a `GradientSampler` (review 6.2). |
| 2.4 | `feature/pns-runs-at-edges` | The runs of the PNS model from the start of the first sample to the end of the last (review 6.5). |
| 2.5 | `feature/drop-whole-rms` | No `GradientPeaks.whole_rms_hz_per_m` (review 6.4). |
| 2.6 | `docs/release-0.1.0rc6` | `CHANGELOG.md`, the README, `docs/usage.md`, the status of the three reviews, the version, and tag `v0.1.0rc6`. |

Section 8 gives the facts for the follow-up work in pulseq-checks and in
pulseq-reports.

### 1.1 Order

A wave starts when each task of the wave before it has merged. The tasks of
one wave run at the same time, each in its own worktree and session.

```
This plan merged
  Wave 1:  1.1 test fixes  ||  1.2 spectrum ends  ||  1.3 small fixes
           ||  1.4 doc errors
  Wave 2:  1.5 test prune  ||  1.6 block columns  ||  1.7 small duplicates
  Wave 3:  2.1 gradient gap model
  Wave 4:  2.2 rasters  ||  2.3 public sampler  ||  2.4 runs at edges
           ||  2.5 drop whole_rms
  Wave 5:  2.6 release  ->  tag v0.1.0rc6
                              |
                              +->  pulseq-checks: pin v0.1.0rc6 (section 8.1)
                              +->  pulseq-reports: pin v0.1.0rc6 (section 8.2)
```

Why this order:

- Task 1.1 makes the tests able to find a wrong change in tasks 1.6 and 2.1.
  It merges before them.
- Task 1.5 deletes tests that task 1.1 does not change. It waits for task 1.1,
  because both change `test_pns_levels.py`, `test_grad_peaks.py` and
  `TESTS.md` in many places.
- Task 1.6 is a refactor that keeps each value. It must merge before task
  2.1, which changes the values. Then the baseline of task 1.6 (section 4.2)
  can compare the outputs bit for bit.
- Task 1.2 changes `grad_spectrum.py` and `sampling.py` (a new function for the
  number of samples). Task 2.1 changes `sampling.py` again, so task 1.2 merges
  first.
- Task 2.1 changes `grad_peaks.py`, `sampling.py`, `pns_levels.py` and their
  tests. No other task of wave 3 runs with it.
- The tasks of wave 4 change different functions. Tasks 2.2 and 2.4 both
  change `analyses.py`, in different specs.

pulseq-checks and pulseq-reports pin `v0.1.0rc5`. No task before the tag
breaks them.

## 2. Context (verified on 2026-10-07)

1. **The repository.** `origin/main` is at `bf27eff` (PR #49, the review). The
   tags `v0.1.0rc1` to `v0.1.0rc5` exist. `v0.1.0rc6` does not.
   `pyproject.toml` has the version `0.1.0rc5`.
2. **The checks.** `nix develop --command scripts/check` passes on `efe4f46`:
   ruff, 1045 tests, the `TESTS.md` check (319 entries) and shellcheck.
3. **The release draft.** The worktree `.worktrees/release-0.1.0rc6` has the
   branch `docs/release-0.1.0rc6` with one local commit, `341ebec` ("wip: the
   draft of 0.1.0rc6"), on `9197c5d`. It has no remote branch. It is step 0
   of the second plan.
4. **The callers.** pulseq-checks `origin/main` (`100c3bc`) and
   pulseq-reports `origin/main` (`68682bd`) both pin `v0.1.0rc5`.
5. **What the callers use that this plan changes:**
   - pulseq-checks reads `spec.rasters` (`src/pulseq_checks/run.py` line 304,
     `src/pulseq_checks/bindings.py` line 118). A raster of the spec that the
     file does not declare, and that the target does not give, makes the check
     not evaluated.
   - pulseq-checks reads `BlockGradientValues.junction_hz_per_m_per_s`
     (`src/pulseq_checks/checks/gradient.py` line 468).
   - pulseq-reports reads `GradientPeaks.whole_rms_hz_per_m`
     (`src/pulseq_reports/cards/gradient_limits.py` lines 84 to 95).
   - pulseq-reports reads `start` and `end` of the series `pns_above_0` as the
     times of the first and the last sample of a run, and widens a run of one
     sample (`src/pulseq_reports/assets/pns_lanes.js` lines 659 to 662,
     `cards/diagram.py` lines 87 and 88).
   - pulseq-reports runs the SAFE model again in the browser
     (`src/pulseq_reports/assets/pns_lanes.js` lines 31 to 44). Its model of
     the gradient is "0 before the first point and after the last" of each
     event, block by block, with no ramp.
6. **The gradient between two events** (verified at pypulseq `f2c582b`, at the
   pinned fork `3c3bd85`, and at MATLAB Pulseq `c746912`. pypulseq-issues 12
   gives the examples):
   - The specification (`doc/specification.tex` line 420 at `c746912`) says
     that a gradient that starts at a value that is not 0 must have the delay
     0, and that a gradient that ends at a value that is not 0 must end at the
     end of its block. It gives no limit. It does not say what the gradient is
     between two events.
   - `add_block` of pypulseq and `setBlock` of MATLAB Pulseq refuse these two
     cases only above `max_slew * grad_raster_time`.
   - pypulseq's `waveforms()`, and thus `get_gradients()`, `calculate_pns`
     and `calculate_gradient_spectrum`, draw a straight line across each gap.
   - MATLAB Pulseq's `waveforms_and_times()` (`Sequence.m` lines 2113 to 2135
     at `c746912`) draws a line across a gap of one gradient raster time or
     less. Across a longer gap, it adds a ramp to 0 in half a raster time after
     the earlier event, and a ramp from 0 in half a raster time before the later
     event, with a warning. A value of 1e-6 Hz/m or less becomes 0 with no
     warning. Before the first point and after the last point of an axis, its
     `getGradients` steps to 0 in 1e-12 s.
   - pulseq-analysis at `efe4f46` has three models (review 6.3):
     `GradientSampler.sample` draws a line, `GradientSampler.block_samples`
     and the RMS of `grad_peaks` use 0, and the junction step of `grad_peaks`
     joins the last value of a block to the first value of the next.
7. **The events are on the raster.** The specification says that gradient
   events start and end on the edges of the gradient raster. Then a gap
   between two events is 0, 1, 2 or more raster times, and a ramp of half a
   raster time from an edge ends at a sample time `(j + 0.5) * dt`.
8. **The tests that use a gradient end that is not 0 next to a gap**
   (`efe4f46`): in `test_grad_peaks.py`, `_junction_sequence` (line 842),
   `_gradient_ends_non_zero_before_delay_sequence` (line 886),
   `_delayed_junction_sequence` (line 904),
   `test_gradient_ending_non_zero_before_a_block_with_no_gradient_is_a_junction_step`
   (line 460) and
   `test_window_with_the_junction_time_inside_it_has_the_step_of_a_delayed_event`
   (line 532). In `test_sampling.py`, `_junction_sequence` (line 81) and
   `_step_then_gap_sequence` (line 112). Task 2.1 changes the expected values
   of the tests that use them.
9. **The mutation runs of the review** are in the session scratchpad, not in
   the repository. Section 6.2 gives each mutation that task 1.1 must kill.

## 3. Decisions

### 3.1 Decisions of the user

The user made U1 to U5 on 2026-10-07.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The gradient between two events | The model of MATLAB Pulseq: a line across a gap of one raster time or less, and ramps to and from 0 in half a raster time across a longer gap (section 5.1). One model for each measurement. | (a) 0 outside the events, with a step over one raster time. (b) pypulseq's line across each gap. (c) Keep the three models and document them. |
| U2 | The release | All the work goes into `0.1.0rc6`. Task 2.6 of this plan replaces task 2.5 of the second plan. | `0.1.0rc6` now, then `0.1.0rc7` for this plan. |
| U3 | The interface of section 6 of the review | All four: a rule for `rasters` (6.1), a public way to make a sampler (6.2), no `whole_rms_hz_per_m` (6.4), and runs at the edges of the samples (6.5). | Fewer of them. |
| U4 | The tests | Correct the tests of review 5.1 and 5.2, and delete the tests and the test code of review 5.3 and 5.4. The tests of pypulseq's `write` and `read` stay, and `TESTS.md` says that they check the pin. | (a) Corrections only. (b) Also delete the tests that call no code of the package. |
| U5 | The discrepancy of pypulseq | A new draft issue in pypulseq-issues (12). | No report. |

### 3.2 Decisions of this plan

These decisions follow from the code, from the facts of section 2, or from
the decisions of section 3.1. The approval of this plan approves them. L1,
L2, L17 to L20 of the first plan stay true (a branch and a PR for each task,
no deprecated alias, `spec.version` stays 1, `docs/usage.md` changes with
each task, `TESTS.md` by the executing agent in a parallel group, `mv` for a
move).

| # | Decision | Reason |
|---|---|---|
| D1 | The model of section 5.1 is the gradient waveform of the package. Each measurement uses it: `grad_peaks` (the peak, the slew, the RMS and the vector peak), `GradientSampler.sample` (the spectrum, and the PNS off the raster) and `GradientSampler.block_samples` (the PNS on the raster). | U1. |
| D2 | A ramp is added for each end value that is not 0, also for a value of 1e-6 Hz/m or less. MATLAB Pulseq sets such a value to 0 with no ramp. The difference is 1e-6 Hz/m or less over half a raster time. | The points of an event then do not depend on the events next to it. The difference is below each tolerance of the tests. |
| D3 | A gap is "long" when `first_time - last_time > dt + TIME_TOLERANCE`, with `dt = seq.grad_raster_time`. It is "zero" when it is `TIME_TOLERANCE` or less. Else it is "short". | MATLAB Pulseq compares with no tolerance. The times of the package are sums of floats. |
| D4 | The slew of a step (a zero gap with two different values, the first point of the sequence, or the last point of the sequence) is `abs(step) / dt`, at the time of the step. This is the rule of the junction step at `efe4f46`. | `Sequence.add_block` accepts a step up to `max_slew * dt`, and the scanner plays it in one raster time. MATLAB Pulseq's step of 1e-12 s has no physical slew. |
| D5 | The credit of a segment between two events: a ramp to 0 goes to the block of the earlier event, a ramp from 0 to the block of the later event, and a step or a short-gap line to the block of the later event. Its time is the start of the segment. | The rule "the first block in play order" of the review of 2026-10-04 stays true for each kind. |
| D6 | `BlockGradientValues.slew_hz_per_m_per_s` of a block includes the ramps of its event. `junction_hz_per_m_per_s` is the step or the short-gap line into its event, and 0 for a long gap. A block with no event on the axis has 0 for both. | D5. The field keeps its name and its meaning ("the slew at the start of the event of the block"). |
| D7 | `GradientSampler.block_samples` gives the samples of section 5.1. A ramp from a raster edge ends at a sample time, where its value is 0, so a ramp changes no sample of a sequence on the raster (fact 7). Only the samples in a short gap change: they get the line. | D1. The block-by-block rule of pulseq-reports (fact 5) changes for short gaps only. |
| D8 | The oracle of `grad_peaks` and of `sampling` becomes one function in `tests/oracles/waveform.py`. It takes the points of pypulseq's `waveforms()` for each axis, and adds the ramps of section 5.1 as MATLAB Pulseq does (a port of `waveforms_and_times`, lines 2113 to 2135). It then calculates the peak, the slew and the RMS on the whole polyline, with no per-block code. The copies of `_clip_polyline` and `_vector_peak_in_block` go away (review 5.3). | The oracle must not share the code of `src/`. |
| D9 | `sampling.sequence_samples(index, dt)` gives the number of samples of a sequence: `sum(raster_block_lengths(index, dt)[0])` when each block is on the raster, else `max(ceil((index.end_s - 1e-10) / dt), 0)`. `pns_levels` and `grad_spectrum` call it. | Review 1.3. It is the rule of `pns_levels` at `efe4f46`, so the PNS values do not change. |
| D10 | The end padding of the spectrum is `pad + (-nt) % hop` zeros, so that the last sample is at the centre of a window. The start padding stays `pad`. | Review 1.2. |
| D11 | `Series.arrays` and `Series.meta` are `FrozenDict`s. | Review 1.4. The rule of each result. |
| D12 | `decode_array` decompresses at most `length * itemsize + 1` bytes (`zlib.decompressobj(wbits=31)` with `max_length`), and raises `ValueError` when there are more. | Review 1.5. |
| D13 | `read_gradient_asc` keeps the resolved paths of the files that it reads, and raises `ValueError` that names the cycle when a `$INCLUDE` names one of them. | Review 1.5. |
| D14 | The values of each block are calculated one time for each sequence and kept: for each axis, the peak, the slew of the segments, the junction step, their times, and the RMS integral of the event. Also the vector peak of the block, with its time. `_BlockData` keeps them with a prefix sum of each RMS integral. A range is then an `argmax` over the blocks `[a, b)` and a difference of two prefix sums, plus the blocks that its edges cut. `block_gradient_values` gives the same arrays. | Review 2.1, 2.2 and 4.1. The cost of a window is then the number of its blocks, with no O(K) term. |
| D15 | A block that a window edge cuts uses the points of `_events.event_points`, with the times `(start + delay[k]) + offsets`, not `get_block`. | Review 2.1. The floats are those of `gradient_points`. |
| D16 | `_hardware_key` uses `_HW_FIELDS`, not `SAFE_FIELDS`. `_check_hardware` still requires `stim_thresh`, as pypulseq's `safe_hw_check` does. | Review 4.2. |
| D17 | `registry()` calls `ep.load()` and adds to the dict in its own loop. `_load` and `_add` go away. | Review 4.3. |
| D18 | The rule of `AnalysisSpec.rasters`: each raster of the file whose value changes the value of the analysis. `seq.index` gives `("BlockDurationRaster",)`. The four other analyses keep `("GradientRasterTime", "BlockDurationRaster")`. | U3, review 6.1. `Sequence.read` makes each block duration from `BlockDurationRaster`, and each analysis reads the durations. |
| D19 | `sampling.gradient_sampler(seq) -> GradientSampler` is the public way to make a sampler: `GradientSampler(sequence_index(seq), event_points(seq))`. It calls `refuse_rotations` first. The constructor stays, but `docs/usage.md` gives only `gradient_sampler`. The sampler is not kept: the index and the event points are. | U3, review 6.2. |
| D20 | `PnsInterval.start_s` is `first * dt` and `PnsInterval.end_s` is `(last + 1) * dt`, the edges of the samples of the run. `peak_time_s` stays the time of a sample, `(k + 0.5) * dt`. The series `pns_above_<k>` gives these values. | U3, review 6.5. The bins of `pns_total` use the same edges. |
| D21 | `GradientPeaks.whole_rms_hz_per_m` goes away. A caller uses `gradient_peaks(seq).axes[axis].rms_hz_per_m`, which is kept. | U3, review 6.4. |
| D22 | Task 2.6 starts a new branch from `origin/main` for the release, and uses the text of `341ebec` and of task 2.5 of the second plan as a start. It does not rebase the draft. The draft branch is renamed `wip/release-0.1.0rc6-draft` first, with the approval of the user. | Fact 3. |

## 4. How to execute this plan

Section 4 of the second plan applies: the `dev-workflow:start-task` skill,
`nix develop --command uv sync --frozen` one time in each worktree, a
`TESTS.md` entry for each new or changed test in the same PR, the checks
before each PR, the commit message shown to the user and approved, a merge
only when the user says so, a review of each worker diff by the executing
agent (X), and a stop and a question to the user when this plan is wrong.
The tiers M (`worker-medium`), H (`worker-high`) and X are those of the first
plan.

### 4.1 Parallel work

| Task | Wave | Workers | Groups |
|---|---|---|---|
| 1.1 | 1 | 3: S (M), P (H), G (H) | S, P and G at the same time |
| 1.2 | 1 | 1 (H) | — |
| 1.3 | 1 | 1 (M) | — |
| 1.4 | 1 | 1 (M) | — |
| 1.5 | 2 | 2: A (M), B (M) | A and B at the same time |
| 1.6 | 2 | 1 (H), after a baseline by X | — |
| 1.7 | 2 | 1 (M) | — |
| 2.1 | 3 | 3: O (H), then W (H) and Q (H) | O first, then W and Q at the same time |
| 2.2 | 4 | 1 (M) | — |
| 2.3 | 4 | 1 (M) | — |
| 2.4 | 4 | 1 (M) | — |
| 2.5 | 4 | 1 (M) | — |
| 2.6 | 5 | 3: L (H), D (M), U (H) | L, D and U at the same time |

### 4.2 The baseline of a refactor

Tasks 1.6 and 1.7 must not change a value. X uses the baseline worktree
`.worktrees/base` and the script of section 4.2 of the second plan, with the
inputs of that section, and moves the worktree to the current `origin/main`
before each task:

```bash
git -C /Users/dylan/dev/pulseq-analysis/.worktrees/base checkout --detach origin/main
(cd /Users/dylan/dev/pulseq-analysis/.worktrees/base && nix develop --command uv sync --frozen)
```

For task 1.6 the script also writes `block_gradient_values` and 200 random
windows of `gradient_peaks` on `build_repeating(1000)`. X compares
the two outputs with `cmp`. Remove the baseline worktree after task 1.7.

## 5. The design

### 5.1 The gradient waveform (task 2.1)

The waveform of one axis is a polyline. Its points are, in play order:

1. The points of each event on the axis, at the times
   `(block start + delay) + offset` (`seq_utils.gradient_offsets`), with the
   values of the event.
2. Between two consecutive events on the axis (the blocks between them have
   no event on the axis), with `last_time` and `last` of the earlier event and
   `first_time` and `first` of the later event, and the gap
   `first_time - last_time` (D3):
   - **Zero gap.** No point. When `first != last`, it is a step (D4). The
     value at the time of the step is `last`, as `sample` gives it now.
   - **Short gap.** No point: the line from `last` to `first`.
   - **Long gap.** The point `(last_time + dt / 2, 0)` when `last != 0`, and
     the point `(first_time - dt / 2, 0)` when `first != 0` (D2). The value
     is 0 between them.
3. Before the first point and after the last point of the axis, the value is
   0. A first or last value that is not 0 is a step (D4).

The slew of the axis is the largest of the slopes of its segments (a segment
shorter than `TIME_TOLERANCE` has no slope) and of the steps (D4). The RMS
is the integral of the square of the polyline. The vector peak is at the
union of the points of the three axes, as now.

What changes, by measurement:

| Measurement | At `efe4f46` | After task 2.1 |
|---|---|---|
| `grad_peaks`, zero gap | the step `abs(last - first) / dt` | no change |
| `grad_peaks`, short gap | the step `abs(last - first) / dt` at `start + delay` | the slope of the line, `abs(first - last) / gap`, from `last_time` |
| `grad_peaks`, long gap | the step `abs(last - first) / dt` | two ramps, `2 * abs(last) / dt` and `2 * abs(first) / dt` |
| RMS | 0 in each gap | the line, or the ramps |
| `sample` (the spectrum, the PNS off the raster) | the line across each gap | the ramps across a long gap |
| `block_samples` (the PNS on the raster) | 0 in each gap | the line in a short gap (D7) |

`block_samples` keeps its block-by-block samples and its cache. After it
gathers the samples of a range, it writes the samples whose times are in a
short gap of the axis with the line of that gap. The short gaps of each axis
are found one time for each sequence, from the index and the event points,
and kept with the event points (`_kept`).

The edges of a window of `gradient_peaks` cut the polyline of section 5.1,
not the points of one block. A ramp can be up to `dt / 2` outside the block
of its event, so a block within `dt / 2` of an edge is an edge block.

### 5.2 The spectrum (task 1.2)

D9 and D10. The first sample stays at the centre of the first window. With
`nt` samples and the end padding `pad + (-nt) % hop`, the number of padded
samples `n = nt + pad + pad + (-nt) % hop` gives
`num_windows = (n - nwin) // hop + 1` windows, and the last sample is at the
centre of the last window. The values of a sequence whose `nt` is a whole
number of hops do not change. The other values change. The comment "Do not
change it to `index.end_s`" goes away. The oracle
(`tests/oracles/grad_spectrum.py`) gets the same two rules, from its own code.

### 5.3 The values of each block (task 1.6)

D14 and D15. `_axis_slice_stats`, the vector peak loop of `_range_result` and
`_block_vector_peaks` go away. `_BlockData` gets, for each axis, the arrays of
`block_gradient_values` and the prefix sum of the RMS integral of each block,
and the vector peak of each block with its time. `block_gradient_values` makes
its result from `_BlockData`, with copies of the arrays. A range `[lo, hi]`:

- `a` and `b` as now (`np.searchsorted`).
- The blocks of `[a, b)` that lie whole in the range: the first `argmax` of
  each column over the slice gives the credited block, and the RMS integral is
  `prefix[i1] - prefix[i0]`.
- The edge blocks: the clipped polyline of their points (D15), as now.
- The credit rule of `_credit_goes_to`, as now.

No value changes (section 4.2).

### 5.4 The interface (tasks 2.2 to 2.5)

D18 to D21. Each task changes the spec description, the docstrings and
`docs/usage.md` of its names.

## 6. The change

### 6.1 Task 0: this plan

This file, and a line in the "Documents" list of `README.md`.

### 6.2 Task 1.1: the test fixes (wave 1)

Worker S (`test_series.py`, `test_analyses.py`), worker P
(`test_pns_levels.py`, `test_pns_levels_kept.py`, `test_sampling.py`,
`test_grad_spectrum.py`) and worker G (`test_grad_peaks.py`,
`test_seq_index.py`, `test_events.py`). No change to `src/`. Each item names
the mutation of the review that its test must fail on. X checks each one on a
copy of `src/`.

Worker S:

- `test_series_refuses_bad_arrays`: each ENVELOPE case gets a valid
  `coord_end` for its arrays, and a `match=` of its own message. Mutation:
  no "only `min` and `max`" check (`series.py` lines 228 to 233).
- `test_series_refuses_bad_meta`: `np.float64(1.5)` in `meta` becomes a
  `float`, and the series equals the series with `1.5` and its round trip.
  Mutation: `series.py` line 134.
- `test_decode_array_refuses[data-not-base64]`: data with a character that is
  not base64 and a valid padding. Mutation: no `validate=True`.
- `test_from_obj_refuses[coord-start-a-bool]` and
  `test_decode_array_refuses[length-a-bool]`: `match=` of the `bool` message.
- `test_series_not_equal_for_a_different_field_or_array[kind]`: POINTS and
  RUNS with the same four arrays.
- The ENVELOPE boundaries: `coord_end = low + tolerance` is refused, and
  `coord_end = high + tolerance` is accepted (`series.py` lines 325 and 331).
- `test_analysis_spec_raises_for_params_that_disagree_with_necessary_and_defaults`:
  a `match=` for each case, and a case of a repeated name in `params`.
- The docstring of `test_compute_of_gradient_spectrum_passes_its_arguments_on`.

Worker P:

- `test_pns_levels_takes_numpy_and_fraction_thresholds`: the float call uses
  `_compute`, and the test asserts that the two results are not one object.
- `test_example_hardware_for_spin_echo`: compare with `calculate_pns`, as
  `test_summary_matches_calculate_pns_within_the_fork_tolerance` does, or
  delete it when that test covers the spin echo.
- A threshold equal to the peak gives one interval or more. Mutation: `>` at
  `pns_levels.py` line 579.
- `a1 + a2 + a3 = 0.9` on a sequence with no gradient raises `ValueError`.
  Mutation: no `abs` at `pns_levels.py` line 211.
- `test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples`:
  a sequence whose `end_s / dt` is within 1e-10 of a whole number. Mutation: no
  `- 1e-10`.
- The raster tolerance: a block of `1 + 2e-6` samples is off the raster and
  one of `1 + 5e-7` samples is on it. Mutation: `ON_RASTER_TOLERANCE = 0.4`.
- `test_subrange_inside_a_gap_matches_pypulseq`: a gap between two events with
  ends that are not 0. Mutation: `event_blocks[lo_pos:hi_pos]`.
- `GradientSampler.sample` with times in a gap that ends at a junction step.
  Mutation: `side="left"` at `sampling.py` line 107.

Worker G:

- `_assert_matches_oracle`: compare `peak_time_s`, `slew_time_s`,
  `vector_peak_time_s` and the credited blocks, to 1e-12 s. Mutation:
  `start_s[peak_play] - start_s[i0] + ...` in `_axis_slice_stats`.
- `test_a_window_gives_the_same_result_with_and_without_the_kept_data`: keep
  the kept data of the earlier windows. Mutation:
  `kept.setdefault("first_range", range_s)`.
- `_assert_block_values_agree_with_gradient_peaks`: the junction time is
  `start_s + delay` of the event. `_delayed_junction_sequence` goes into
  `_AGREEMENT_SEQUENCES`.
- `block_gradient_values` of the 4 us file. Mutation:
  `seq.system.grad_raster_time` at `grad_peaks.py` line 880.
- A segment of block 1 with the slew of the junction step of block 2 credits
  block 1. Mutation: `>=` at `grad_peaks.py` line 684.
- `test_junction_step_and_segment_of_one_block_with_the_same_slew_give_the_junction_time`:
  a segment that starts after the junction time, or delete it as a duplicate
  of the test at line 346.
- The index tests: a sequence whose events are added to the libraries in an
  order that is not the order of first use. Mutation: `order = used` at
  `seq_index.py` line 134.
- `test_events.py`: the expected values of
  `test_event_values_of_the_points_equal_the_values_of_gradient_points` are
  hand-computed for one trapezoid and one arbitrary gradient.

### 6.3 Task 1.2: the spectrum ends (wave 1)

D9 and D10 (section 5.2). New tests:

- One trapezoid at the end of a sequence of N samples, for N = 5000, 6000,
  7000 and 7499: `rss.max()` equals that of the trapezoid at the start, to
  1e-9 relative. The test fails at `efe4f46`.
- `sequence_samples` for the blocks `[0.01938, 0.01268]` s is 3206.

`test_gradients_at_the_end_are_not_attenuated` gets a length that is not a
whole number of hops, or goes away. `TESTS.md` line 4284 ("because scipy
computes the") changes to the rule of chunks that are equal bit for bit, and
`test_chunks_give_the_same_spectrum_as_one_chunk` uses `array_equal`.

### 6.4 Task 1.3: the small fixes (wave 1)

D11, D12 and D13, each with a test: a change of `s.arrays` or `s.meta` raises
`TypeError`. A gzip of more bytes than `length` is refused before it is
decompressed whole. Two `.asc` files that include each other raise
`ValueError`.

### 6.5 Task 1.4: the documentation errors (wave 1)

Each item of the review section 3, except the items that tasks 1.2 and 2.1
change (the ends of the spectrum, the cost of a window, the rasters).
`grad_peaks.py` line 45 is wrapped at 100 characters.

### 6.6 Task 1.5: the test prune (wave 2)

Worker A (`test_pns_levels.py`, `test_pns_levels_kept.py`,
`test_analyses.py`, `test_grad_spectrum.py`, `test_sampling.py`) and worker
B (`test_grad_peaks.py`, `test_seq_index.py`, `test_series.py`,
`test_seq_utils.py`, `test_equality.py`, `test_extensions.py`,
`test_events.py`, `test_package.py`, `conftest.py`, `synthetic.py`,
`scripts/check_tests_md.py`, `tests/oracles/grad_spectrum.py`):

- Delete the duplicates of the review section 5.4. When two tests of one name
  are in `test_pns_levels.py` and `test_pns_levels_kept.py`, keep the stronger
  one (the one that patches `kept_results`).
- Delete the dead test code of the review section 5.4.
- Keep the tests of the review section 5.3 that call no code of the package
  (U4): `test_time_tolerance`,
  `test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system`,
  `test_synthetic_sequences_pass_the_timing_check` and the four `FrozenDict`
  tests of `dict` behaviour. `TESTS.md` says what each one checks: a
  constant, the test helpers, or the behaviour that `FrozenDict` gets from
  `dict`.
- Keep the four tests of pypulseq's `write` and `read` of
  `test_extensions.py` (U4). `TESTS.md` says that they check the pin
  (`TODO.md`), not the package. The test at line 181 asserts a field of each
  result, not only `is not None`.
- `test_events.py`: `_points_from_grad_events` and the sampler test go away
  when task 1.1 gives hand-computed values.
- `test_series_round_trip_of_two_million_float32_values` uses 2000 values.

Each deleted test leaves `TESTS.md` in the same PR. The number of tests goes
down. Section 7 gives the check.

### 6.7 Task 1.6: the values of each block (wave 2)

D14 and D15 (section 5.3). No test changes, except a new test that a window
calls no `get_block`. X makes the baseline before and after (section 4.2).

### 6.8 Task 1.7: the small duplicates (wave 2)

D16 and D17. A test: two hardware structs that differ only in `stim_thresh`
give one kept result.

### 6.9 Task 2.1: the gradient gap model (wave 3)

D1 to D8 (section 5.1). Worker O first: `tests/oracles/waveform.py` (D8), its
own tests on hand-computed polylines, and the sequences of fact 8 with the
values of MATLAB Pulseq. The values of the two sequences of pypulseq-issues 12
are `[0, a, a, 0, 0, a, 0]` at `[0, 100, 200, 205, 295, 300, 400]` us. Then
worker W (`grad_peaks.py`, `test_grad_peaks.py`) and worker Q (`sampling.py`,
`pns_levels.py`, `grad_spectrum.py`, `_events.py`, `test_sampling.py`,
`test_pns_levels.py`, `test_grad_spectrum.py`).

- The tests that compare with pypulseq (`get_gradients`, `calculate_pns`,
  `calculate_gradient_spectrum`) keep the sequences with no end that is not 0
  next to a gap. For the sequences of fact 8 they compare with the oracle.
- `docs/usage.md` gets a section "The gradient waveform", with section 5.1,
  and the difference from pypulseq (pypulseq-issues 12). The module
  docstrings of `grad_peaks`, `sampling`, `pns_levels` and `grad_spectrum`
  refer to it.
- The descriptions of `gradient.peaks`, `gradient.blocks`,
  `pns.safe.levels` and `gradient.spectrum` say "the model of MATLAB Pulseq"
  where they describe the slew and the samples. `spec.version` stays 1 (L17
  of the first plan: a release candidate has no compatibility promise).

### 6.10 Task 2.2: the rasters (wave 4)

D18. The `rasters` text of `AnalysisSpec`, of the module docstring of
`analyses` and of `docs/usage.md` ("Rasters" and section 6) gives the rule.
`test_the_spec_of_each_analysis_has_the_documented_values` checks
`("BlockDurationRaster",)` for `seq.index`.

### 6.11 Task 2.3: the public sampler (wave 4)

D19. `docs/usage.md` section 4 gives `sampling.gradient_sampler(seq)`. The
tests of `test_sampling.py` that make a sampler use it, except one test of the
constructor.

### 6.12 Task 2.4: the runs at the edges (wave 4)

D20. `_IntervalFinder._interval`, the docstrings of `PnsInterval` and
`PnsLevels.above`, the `series` text of `pns.safe.levels`, and
`docs/usage.md` sections 3 and 6. A run of one sample has
`end_s - start_s == dt`. The tests of the intervals change their expected
times.

### 6.13 Task 2.5: no `whole_rms_hz_per_m` (wave 4)

D21. The field, its docstring, `_BlockData.whole_rms` if nothing else uses
it, its tests, and `docs/usage.md` sections 2 and 8.

### 6.14 Task 2.6: the documents and the release (wave 5)

As task 2.5 of the second plan, and D22, with these additions:

- The `CHANGELOG.md` entry of `0.1.0rc6` has the changes of the three plans.
  "Changed" gives the gradient waveform (section 5.1, with the table of what
  changes), the spectrum ends, the runs at the edges, the rasters of
  `seq.index`, and the removed `whole_rms_hz_per_m`. "Added" gives
  `gradient_sampler` and `sequence_samples`.
- A section "Status at 0.1.0rc6" at the end of
  `docs/reviews/2026-10-06-code-review.md`: each finding with its task, or
  "not changed" with the reason.
- `README.md`: the line of this plan, and the install line of `v0.1.0rc6`.

## 7. Checks of the release

Before the tag, X checks:

1. `nix develop --command scripts/check` passes on `main`.
2. Each mutation of section 6.2 fails a test.
3. The values of the sequences of pypulseq-issues 12 are those of section
   6.9, in `gradient_peaks`, `block_gradient_values`,
   `GradientSampler.sample` and `block_samples`.
4. A sequence of `tests/synthetic.py` gives the values of `0.1.0rc5`, except
   for the changes that `CHANGELOG.md` gives (the names, the units, the bin,
   the spectrum ends).
5. The number of tests is that of `efe4f46`, less the deleted tests, plus the
   new tests, and `TESTS.md` has an entry for each.

## 8. Facts for the follow-up work

### 8.1 pulseq-checks (`100c3bc`)

- `seq.index` gives the raster `BlockDurationRaster` (D18). A check that uses
  `seq.index`, on a file with no `BlockDurationRaster` and a target that does
  not give it, is not evaluated (`run.py` line 304).
- `junction_hz_per_m_per_s` (`checks/gradient.py` line 468) is 0 for a long
  gap, and the ramps are in `slew_hz_per_m_per_s` (D6). The largest of the two
  is still the slew of the block.
- The values of the gradient checks, of the PNS and of the spectrum change for
  the sequences of section 5.1, and the spectrum changes at the end of each
  sequence whose length is not a whole number of hops (section 5.2).

### 8.2 pulseq-reports (`68682bd`)

- `whole_rms_hz_per_m` goes away (D21). `cards/gradient_limits.py` lines 84 to
  95 call `gradient_peaks(seq)` for the RMS of the whole file.
- `start` and `end` of `pns_above_0` are the edges of the samples (D20).
  `runMarks` of `pns_lanes.js` (lines 659 to 670) does not need to widen a run
  of one sample.
- The model of `pns_lanes.js` (lines 31 to 44) is "0 outside each event". It
  must give the line in a short gap (D7) to give the values of `pns_levels`.
  A ramp changes no sample of a sequence on the raster.

## 9. Later

- Report pypulseq-issues 12 upstream, and a fix of `waveforms()` in the fork
  if the maintainers agree. Then the tests of task 2.1 can compare with
  `get_gradients` for each sequence.
- The question of pypulseq-issues 12 for both toolboxes: should `add_block`
  refuse an end that is not 0 next to a gap for any value, as the
  specification says?
