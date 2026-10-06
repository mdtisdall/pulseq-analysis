# Implementation plan: the fixes of the second code review (0.1.0rc6)

Status: approved. Written on 2026-10-05. Amended on 2026-10-05 after wave 1
(PRs #35 to #39): the pin of pypulseq and the hash of a sequence (U7 to U11,
D19 to D23, tasks 1.8 and 1.9).

## 1. Scope

`docs/reviews/2026-10-05-code-review.md` (in this plan, "the review") gives
the findings of a review of `main` at `dfdb044`, after the fixes of
`docs/plans/review-fixes.md` (in this plan, "the first plan"). This plan
gives the work that corrects them, and the changes of the interface that the
user chose on 2026-10-05 (section 3.1). The release `0.1.0rc6` is not tagged
yet. All the work of this plan goes into it (U1), so task 2.6 of the first
plan is replaced by task 2.6 of this plan.

The work has two phases:

- **Phase 1** corrects the code, the tests and the documents. It changes no
  public name. It changes the default bin of the PNS level (U3), which is
  not in a release yet.
- **Phase 2** changes the interface, and makes the release. It breaks
  callers of `0.1.0rc5` more than the first plan does (section 8).

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/second-review-fixes-plan` | This plan, and one line for it in `README.md`. No code. |
| 1.1 | `fix/second-review-test-gaps` | The tests that the review section 5 asks for. No change to `src/`. |
| 1.2 | `fix/pns-bin-snap` | `bin_s` on the raster gives its whole number of samples; the default is 5 ms (review 1.1, 6.4). |
| 1.3 | `fix/pns-hardware-check` | One check of the hardware struct, before the sequence is read (review 1.2). |
| 1.4 | `fix/gradient-peaks-window` | The window checked before the events are read, a range that is never reversed, and the time of a delayed junction step (review 1.3 to 1.5). |
| 1.5 | `docs/second-review-doc-errors` | The documentation errors of the review section 3 that no other task changes. |
| 1.6 | `refactor/second-review-duplicates` | One rule of equality for `Series`, and one copy of each constant (review section 4). |
| 1.8 | `chore/pypulseq-pin-2` | pypulseq from the fork tag `pulseq-reports-pin-2`, which reads the `[SIGNATURE]` hash as text (U7). |
| 1.9 | `feature/require-signature` | Each measurement refuses a sequence with no `[SIGNATURE]` hash (U8 to U10). |
| 1.7 | `refactor/kept-event-points` | The points of each gradient event read one time for each sequence (review 2.1). |
| 2.1 | `refactor/one-kept-entry-point` | One public function for each measurement, which keeps its result. No `pns.py`, no `_for` names (review 6.3). |
| 2.2 | `refactor/window-cost` | A window of `gradient_peaks` costs the blocks in the window, not all the blocks (review 2.2). |
| 2.3 | `feature/analysis-parameters` | `AnalysisSpec` gives the necessary parameters and the defaults; `gradient.peaks` and `gradient.spectrum` get parameters; the contract of `seq.index` (review 6.1, 6.2, 6.5). |
| 2.4 | `feature/consistent-result-shapes` | The checks of `Series`, the "no result" of the spectrum, and the equality of `GradientPeaks` (review 6.7, 6.8, 3). |
| 2.5 | `docs/release-0.1.0rc6` | `CHANGELOG.md`, the README, `docs/usage.md`, the status of both reviews, the version, and tag `v0.1.0rc6`. |

Section 8 gives the facts for the follow-up work in pulseq-checks and in
pulseq-reports, in addition to section 8 of the first plan.

### 1.1 Order

A wave starts when each task of the wave before it has merged. The tasks of
one wave run at the same time, each in its own worktree and session.

```
This plan merged, and the release draft saved (step 0, section 4)
  Wave 1:  1.1 test gaps  ||  1.2 bin snap  ||  1.3 hardware check
           ||  1.4 peaks window  ||  1.5 doc errors
  Wave 2:  1.6 duplicates  ||  1.8 pypulseq pin
  Wave 3:  1.7 kept event points  ||  1.9 require a signature
  Wave 4:  2.1 one kept entry point
  Wave 5:  2.2 window cost  ||  2.3 analysis parameters
  Wave 6:  2.4 consistent result shapes
  Wave 7:  2.5 release  ->  tag v0.1.0rc6
                              |
                              +->  pulseq-checks: pin v0.1.0rc6 (section 8.1)
                              +->  pulseq-reports: pin v0.1.0rc6 (section 8.2)
```

Why this order:

- Task 1.1 adds the tests that find a wrong change in tasks 1.6, 1.7 and
  2.1. It merges before them.
- The tasks of wave 1 change different functions. Their only shared files
  are `TESTS.md` and `docs/usage.md`, in different sections or in
  neighbouring lines.
- Task 1.6 changes the constants that tasks 1.7 and 2.1 use, and
  `sampling.py` and `grad_peaks.py`, which task 1.7 changes again.
- Task 1.7 makes the kept event points. Task 2.1 keeps the results that use
  them, and task 2.2 makes a window cheap with them.
- Task 2.1 removes the `_for` names. Tasks 2.3 and 2.4 then change one
  function for each measurement, not two.
- Tasks 2.2 and 2.4 both change `grad_peaks.py`, so task 2.4 waits.
- Task 1.8 changes only `pyproject.toml`, `uv.lock` and `TODO.md`, so it
  runs with task 1.6.
- Task 1.9 needs the pin of task 1.8: with the old pin, `read` can make a
  hash that looks like a number into a float (fact 10), which a check of
  presence can take for no hash. Task 1.9 changes `seq_index.py`,
  `extensions.py` and the sequences of the tests; task 1.7 changes other
  modules. Their tests are in neighbouring lines only.

pulseq-checks and pulseq-reports pin `v0.1.0rc5`. No task before the tag
breaks them.

## 2. Context (verified on 2026-10-05)

1. **The repository.** `origin/main` is at `2833a20` (PR #33, the review).
   The tags `v0.1.0rc1` to `v0.1.0rc5` exist; `v0.1.0rc6` does not.
   `pyproject.toml` has the version `0.1.0rc5`.
2. **The checks.** `nix develop --command scripts/check` passes on
   `2833a20`: ruff, 839 tests, the `TESTS.md` check (256 entries) and
   shellcheck.
3. **The release draft.** The worktree `.worktrees/release-0.1.0rc6`
   (branch `docs/release-0.1.0rc6`, at `9197c5d`, with no commit of its own
   and no remote branch) has changes that are not committed: a `CHANGELOG.md`
   entry for `0.1.0rc6` (276 lines), the README, a section "Status at
   0.1.0rc6" of `docs/reviews/2026-10-04-code-review.md`, corrections of
   `docs/usage.md`, the version and `uv.lock`. It is task 2.6 of the first
   plan, not finished.
4. **The callers.** pulseq-checks `origin/main` (`100c3bc`) and
   pulseq-reports `origin/main` (`68682bd`) both pin `v0.1.0rc5`.
5. **What the callers use that the review questioned:**
   - pulseq-reports runs the SAFE model again in the browser from
     `PnsLevels.hw` (`src/pulseq_reports/assets/pns_lanes.js` line 239), so
     `hw` stays (review 6.6: no change).
   - pulseq-reports uses `GradientPeaks.whole_rms_hz_per_m`
     (`src/pulseq_reports/cards/gradient_limits.py` lines 84 to 155), so it
     stays.
   - pulseq-checks uses the analysis `seq.index` by its ID
     (`src/pulseq_checks/checks/pns.py` lines 64, 139 and 171,
     `checks/timing.py` lines 315 and 372), so it stays (U5).
   - pulseq-checks imports `pns_levels.SAFE_FIELDS`
     (`src/pulseq_checks/safe_model.py`), so the name stays.
   - pulseq-checks `bindings.unavailable` (lines 104 to 109) calls an
     analysis with no binding unavailable when `spec.params` is not empty.
     `gradient.spectrum` has no binding.
6. **The floor of `bin_s`** (review 1.1) was reproduced: `bin_s=0.01` at
   the 10 us raster gives 999 samples. The new default has the same error:
   `0.005 / 1e-5 == 499.99999999999994`, so the floor gives 499.
7. **The mutations** of the review section 5, which pass all the tests on
   `dfdb044` (the runner and the log are not in the repository):

   | # | Mutation |
   |---|---|
   | N1 | `_kept.py` line 47: no `seq.block_events is self.block_events` |
   | N2 | `_kept.py` line 48: no `seq.block_durations is ...` |
   | N3 | `_kept.py` line 49: no `seq.grad_library is ...` |
   | N4 | `_kept.py` line 50: no `num_blocks == self.num_blocks` |
   | N5 | `sampling.py` line 151: `<=` becomes `<` |
   | N6 | `pns_levels.py` line 489: `run[2] > peak` becomes `>=` |
   | N7 | `pns_levels.py` line 487: no `a == 0` |
   | N8 | `pns_levels.py` line 557: `back > values` becomes `>=` |
   | N9 | `grad_peaks.py` line 587: `junction_play <= seg_play` becomes `<` |
   | N10 | `grad_spectrum.py` line 180: no `+ 1e-6` |

8. **The use of the names that phase 2 changes** (lines, from `git grep -c`
   in `src`, `tests`, `scripts`, `docs/usage.md`, `README.md` and
   `TESTS.md`):

   | Names | Lines |
   |---|---|
   | `pns_levels_for` | 188 |
   | `gradient_spectrum_for` | 55 |
   | imports of the module `pns` | 11 |
   | `BIN_S` | 29 |
   | `615` (the default bin in samples) | 14 |

   Eleven tests change `CHUNK_SAMPLES` of `pns_levels` or `CHUNK_WINDOWS` of
   `grad_spectrum` with `monkeypatch` (nine in `tests/test_pns_levels.py`,
   two in `tests/test_grad_spectrum.py`). Most of them compare two results
   of one sequence object.
9. **Wave 1.** Tasks 1.1 to 1.5 merged on 2026-10-05: PRs #35 to #39, with
   `main` at `a076d2d`. 878 tests, 274 `TESTS.md` entries. The oracle of
   task 1.4 did not change (U11).
10. **The new pin.** The fork tag `pulseq-reports-pin-2` (commit
    `3c3bd85`, pushed to `mdtisdall/pypulseq`) is `a74ab06` with two
    commits: `read` keeps the `[SIGNATURE]` values as text (the hash was a
    float when the hex digest looked like a number, pypulseq-issues 09),
    and `read` sets `signature_file` to `'text'`, as `write` does
    (pypulseq-issues 10b).
11. **The hash of a sequence** (verified at `3c3bd85` and at upstream
    `f2c582b`). `read` does not check the hash against the file. The
    hash stays on the object after the object changes (pypulseq-issues 11):

    | Case | `seq.signature_value` |
    |---|---|
    | A sequence built with `add_block` | `''` |
    | After `write` | the hash of the file written |
    | After `read` of a signed file | the hash |
    | `add_block` after that `read` | the old hash |
    | `read` of an unsigned file into an object that read a signed file | the old hash |
    | `read` of an unsigned file into a new object | `''` |

12. **The sequences of the tests.** `pp.Sequence(` is in the tests 67
    times, 7 of them in `tests/synthetic.py`. pypulseq's `write` fails for
    an oversampled arbitrary gradient (pypulseq-issues 04), so `write`
    cannot sign each test sequence.

## 3. Decisions

### 3.1 Decisions of the user

The user made U1 to U6 on 2026-10-05.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The release | All the work goes into `0.1.0rc6`. The release of the first plan waits, and task 2.5 of this plan finishes it. | `0.1.0rc6` as it is now, then `0.1.0rc7` for this plan. |
| U2 | The samples of `bin_s` | When `bin_s / dt` is within `ON_RASTER_TOLERANCE` of a whole number, that number. Otherwise the floor. | (a) Always `round`. (b) Keep the floor, and document it. |
| U3 | The default of `bin_s` | 5 ms. | (a) Keep `10.0 / 1624`. (b) No default. |
| U4 | The interface of section 6 of the review | The parameters in `AnalysisSpec` (6.1), the parameters of `gradient.peaks` and `gradient.spectrum` (6.2), and one kept entry point for each measurement (6.3). | Fewer of them. |
| U5 | `seq.index` | It stays in the registry. Its layout is a versioned contract in `docs/usage.md`. | Remove it from the registry (pulseq-checks uses it, fact 5). |
| U6 | The form of one kept entry point | One public function for each measurement, and it keeps its result: `sequence_index`, `gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum`. `pns_levels_for`, `gradient_spectrum_for` and the module `pns` go away. | Keep the pairs of names, and only merge `pns.py` into `pns_levels.py`. |
| U7 | The pypulseq pin | The fork tag `pulseq-reports-pin-2` (`3c3bd85`). | Stay at `pulseq-reports-pin-1`. |
| U8 | A sequence with no hash | Each measurement refuses it, `sequence_index` too. | (a) The measurements but not `sequence_index`. (b) Only the callers, which read the files. |
| U9 | The check of the hash | Presence only: the package does not compute the hash again. | The fork computes the MD5 of the file in `read` and refuses a mismatch. |
| U10 | The stale hash (fact 11) | Pin `pulseq-reports-pin-2`, document the two stale cases here, and report them (pypulseq-issues 11). | A fork fix first, and a pin of a third tag. |
| U11 | The oracle of `grad_peaks` (task 1.4) | It stays the earlier implementation, with no junction steps. The tests of a delayed junction check hand-computed values. | The oracle gets the rule of D4. |

### 3.2 Decisions of this plan

These decisions follow from the code, from the facts of section 2, or from
the decisions of section 3.1. The approval of this plan approves them. L1,
L2, L17 to L20 of the first plan stay true (a branch and a PR for each task,
no deprecated alias, `spec.version` stays 1, `docs/usage.md` changes with
each task, `TESTS.md` by the executing agent in a parallel group, `mv` for a
move).

| # | Decision | Reason |
|---|---|---|
| D1 | `bin_samples_for(num_samples, dt, bin_s=BIN_S)`: `ratio = bin_s / dt`, `nearest = round(ratio)`, `wanted = nearest if abs(ratio - nearest) <= ON_RASTER_TOLERANCE else floor(ratio)`, then `max(wanted, ceil(num_samples / MAX_BINS), 1)`. `BIN_S = 0.005`. | U2, U3, fact 6. `ON_RASTER_TOLERANCE` is the rule of the blocks on the raster. `10.0 / 1624` (615.76 samples) still gives 615, so a caller that gives it gets the bins of `0.1.0rc5`. |
| D2 | One private check of the hardware, `_check_hardware(hardware)`, in `pns_levels.py`. A value that is not a tuple of two items with a `str` label raises `TypeError`. A struct without `x`, `y` or `z`, or without a field of `SAFE_FIELDS` on an axis, raises `ValueError` that names the field. A field that is not a real number raises `TypeError`, and one that is not finite raises `ValueError` (`_validate.real`). `stim_limit` must be above 0. `a1 + a2 + a3` of each axis must be within 0.001 of 1 (the rule of pypulseq's `safe_hw_check`), else `ValueError`. It runs before the sequence is read and before the kept results are read. | Review 1.2. pypulseq's `safe_hw_check` raises `AttributeError` for a struct with no `x`, because its sum check comes before its field check, so the package does not call it. |
| D3 | `gradient_peaks` checks the form and the numbers of `window` first, then reads the index (no block) for the range check, then the events. The range is `(min(max(start, 0), T), min(max(end, 0), T))` for a sequence of length `T`, so its start is never after its end. A range of length 0 gives `reason == NO_GRADIENTS_IN_WINDOW`. | Review 1.3 and 1.4. The rule of the other functions: the arguments first. |
| D4 | The time of a junction step is `start_s + delay` of the event of the block (its first point), and `start_s` for a block with no event on the axis. A step counts in a range when `lo <= time < hi`. `BlockGradientValues` has no time field for the junction; its docstring gives the rule. | Review 1.5. pypulseq refuses a step at a junction between two events unless the value at the connection is the same, so a step at `start_s + delay > start_s` is the step from 0 to the first value. |
| D5 | `Series` uses `_equality.fields_equal`. The order of the keys of `meta` counts, as for each other dict of the package. `series._same_value` goes away. | Review section 4. The JSON form keeps the order of `meta`, so the order is part of the value. This changes `==` of two series whose `meta` has other order; no caller makes one (section 8). |
| D6 | `seq_utils.AXES = ("x", "y", "z")` and `seq_utils.GRAD_COLUMNS = ("gx", "gy", "gz")` replace the five tuples. `sampling` uses `TIME_TOLERANCE` in place of `pp.eps`, and a test checks that they are equal. `SAFE_FIELDS` moves to the top of `pns_levels.py`; `_HW_FIELDS` is `SAFE_FIELDS` without `stim_thresh`. `scripts/check_tests_md.py` loses `javascript_tests` and its pattern. | Review section 4. `SAFE_FIELDS` keeps its name (fact 5). |
| D7 | A private module `_events.py` has `EventPoints` (for the K unique gradient events: `delay`, `count`, `at`, and the pooled `offsets` and `amp`, all read-only) and `event_points(seq)`, which keeps it for the sequence object (`_kept`). It reads each unique event one time (`seq_index.grad_events`). `GradientSampler(index, points)` and `grad_peaks._event_values(points)` use it and call no `get_block`. | Review 2.1. One read of each event for each sequence, and one copy of its points. `delay + offsets` is the value of `gradient_points(g, 0.0)` bit for bit, because `0.0 + delay == delay`. |
| D8 | Each public measurement keeps its result for the sequence object (`_kept`): `sequence_index`; `gradient_peaks` for `window=None` (with its `_EventData`); `block_gradient_values`; `pns_levels` for each (hardware, thresholds, `bin_s`) as `pns_levels_for` keys it now; `gradient_spectrum` for each tuple of its three arguments. A `gradient_peaks` result with a window is not kept (a caller can ask for many windows), but it uses the kept `_EventData`. | U6. |
| D9 | The calculation without the keep is private: `pns_levels._compute_levels` and `grad_spectrum._compute_spectrum`. Each test that changes `CHUNK_SAMPLES` or `CHUNK_WINDOWS`, or that needs two calculations, calls it, and asserts that its two results are not the same object. | Fact 8. With the keep, such a test calls the public function a second time and gets the kept object, so it cannot fail. |
| D10 | `pns.py` goes away. Its key (`_hardware_key`) and its `WeakKeyDictionary` move into `pns_levels.py`. `tests/test_pns.py` becomes `tests/test_pns_levels_kept.py` (`TESTS.md` section 2.7). | U6. No private import between two modules. |
| D11 | `_range_result` finds the blocks of the range with `np.searchsorted`: the first block whose end is after `lo`, and the blocks whose start is before `hi`. The end of each block, and the junction steps of each axis, are calculated one time and kept with the `_EventData` of the sequence. | Review 2.2. The cost of a window is then O(blocks in the window + unique events), not O(all blocks). |
| D12 | `AnalysisSpec` gets `necessary: tuple[str, ...] = ()` and `defaults: tuple[tuple[str, Any], ...] = ()`. `necessary` is the names of `params` with no default, and `defaults` gives each other name of `params` with its default, in the order of `params`. Each default is None, a `bool`, an `int`, a `float`, a `str` or a tuple of these. `__post_init__` raises `ValueError` when the three fields disagree. `params` stays the tuple of all the names. | U4, 6.1. A field that is a tuple keeps `AnalysisSpec` hashable, and `params` does not change for pulseq-checks. |
| D13 | `pns.safe.levels`: `necessary=("hardware",)`, `defaults=(("thresholds_hz_per_t", ()), ("bin_s", BIN_S))`. `gradient.peaks`: `params=("window",)`, `defaults=(("window", None),)`, and `compute(seq, *, window=None)`. `gradient.spectrum`: the three arguments of `gradient_spectrum`, with its defaults. `seq.index` and `gradient.blocks` have no parameters. A test compares each spec with `inspect.signature` of its `compute`. | U4, 6.2. |
| D14 | The layout of `SequenceIndex` (its fields, the dense numbers from 1 in the order of first use, one number space for the three gradient axes, and the dtype rule) is the contract of `seq.index` version 1. A change of it raises `spec.version` of `seq.index`. `docs/usage.md` section 1 and the spec description say so. | U5. |
| D15 | `GradientSpectrum` with `reason == NO_GRADIENTS` has `axes` with the keys `x`, `y` and `z`, each an empty read-only float64 array, as `rss` and `frequency_hz` are. | Review 6.8. A caller reads `axes["x"]` for each result. |
| D16 | `GradientPeaks` compares by value (`fields_equal`) and is not hashable (`__hash__ = None`). `AxisResult` and `PnsInterval` stay hashable dataclasses: they have no dict and no array. | Review section 3. The rule of each result with a dict. |
| D17 | `Series` adds these checks, each a `ValueError`: `coord_start` finite for `SAMPLES` and `ENVELOPE`; `coord_end` finite for `ENVELOPE`, with `coord_start + (n - 1) * coord_step < coord_end <= coord_start + n * coord_step` for `n` bins, each side with the tolerance `1e-9 * coord_step` (and `coord_end >= coord_start` for `n == 0`); for `RUNS`, `start` and `end` finite and `end >= start` for each run. | Review 6.7. The tolerance is for the float products: `pns_total` has `coord_end == num_samples * dt_s` and `coord_step == bin_samples * dt_s`. |
| D18 | Task 2.5 starts a new branch `docs/release-0.1.0rc6` from `origin/main`, and uses the saved draft (step 0) as text to start from. It does not rebase the draft. | The draft is at `9197c5d` and changes `docs/usage.md`, which tasks 1.2 to 2.4 change again. |
| D19 | `[tool.uv.sources]` pins `rev = "3c3bd8515e591ef859399aa20db64b1bd2c3a725"` (the full commit of `pulseq-reports-pin-2`). The comment above it, and the `TODO.md` item of the fork, list the six commits on top of 1.5.0.post1. `uv.lock` is made again with `uv lock`. | U7. `TODO.md`: pulseq-analysis, pulseq-checks and pulseq-reports pin one commit (section 8). |
| D20 | `extensions.refuse_unsigned(seq)` raises `ValueError` when `seq.signature_value` is not a `str` or is `''`. The message says that a `.seq` file must have a `[SIGNATURE]` hash, and that `write` signs a sequence built in memory. `sequence_index` calls it first, before the kept results are read, so each measurement refuses an unsigned sequence through it. The docstring of `extensions.py` covers both guards. | U8, U9. One place for the rule. Each measurement reads the index before it reads a block. |
| D21 | The stamp of `_kept` does not use the hash. | Fact 11: a hash can be stale, so a stamp of the hash gives the result of another file (the error of the first review, 1.1). |
| D22 | `tests/synthetic.py` gets `signed(seq)`: it sets `signature_type = "md5"`, `signature_file = "text"` and `signature_value` to a fixed hex string, and gives back `seq`. Each builder of `synthetic.py` and `scale_sequences.py` gives a signed sequence, and each test that builds a sequence for the package calls `signed`. A test that reads a file writes it with `write` first. The oracles do not change: they do not call `sequence_index`. | Fact 12. U9: only the presence counts, so a fixed value is enough. |
| D23 | The baseline script of section 4.2 calls `signed` on each input (D22). The baseline side before task 1.9 accepts a signed sequence too. | The two sides read the same inputs. |

## 4. How to execute this plan

Section 4 of the first plan applies: the `dev-workflow:start-task` skill,
`nix develop --command uv sync --frozen` one time in each worktree, a
`TESTS.md` entry for each new or changed test in the same PR, the checks
before each PR, the commit message shown to the user and approved, a merge
only when the user says so, a review of each worker diff by the executing
agent (X), and a stop and a question to the user when this plan is wrong.
The tiers M (`worker-medium`), H (`worker-high`) and X are those of the first
plan.

**Step 0, before wave 1.** X shows the user the state of
`.worktrees/release-0.1.0rc6` (fact 3), and asks for approval to save it as
one local commit on `docs/release-0.1.0rc6`, with the message
`wip: the draft of 0.1.0rc6 (task 2.6 of the first plan)`, not pushed. With
approval, X makes the commit. Without approval, X copies `git diff` of the
worktree into the session scratchpad and tells the user where it is. X
changes nothing else in that worktree.

### 4.1 Parallel work

| Task | Wave | Workers | Groups |
|---|---|---|---|
| 1.1 | 1 | 3: K (H), P (H), G (M) | K, P and G at the same time |
| 1.2 | 1 | 1 (H) | — |
| 1.3 | 1 | 1 (H) | — |
| 1.4 | 1 | 1 (H) | — |
| 1.5 | 1 | 1 (M) | — |
| 1.6 | 2 | 2: E (H), C (M) | E and C at the same time |
| 1.8 | 2 | X | — |
| 1.7 | 3 | 1 (H), after a baseline by X | — |
| 1.9 | 3 | 2: A (H), then T (M) | A first, then T |
| 2.1 | 4 | 3: N (H), S (M), R (H) | N and S at the same time, then R |
| 2.2 | 5 | 1 (H), after a baseline by X | — |
| 2.3 | 5 | 1 (H) | — |
| 2.4 | 6 | 2: Q (M), V (H) | Q and V at the same time |
| 2.5 | 7 | 3: L (H), D (M), U (H) | L, D and U at the same time |

### 4.2 The baseline of a refactor

Tasks 1.6 (except D5), 1.7, 2.1 (except the removed names) and 2.2 must not
change a value. X uses the baseline worktree of section 4.2 of the first
plan. `.worktrees/base` exists, detached at `8043553`; X moves it to the
current `origin/main` before each of these tasks:

```bash
git -C /Users/dylan/dev/pulseq-analysis/.worktrees/base checkout --detach origin/main
(cd /Users/dylan/dev/pulseq-analysis/.worktrees/base && nix develop --command uv sync --frozen)
```

The script writes each float with `float.hex` and each array with
`tobytes().hex()`, for these inputs: the sequences of `tests/synthetic.py`,
`build_repeating(10)` and `build_repeating(1000)` of
`tests/scale_sequences.py`, and an off-raster sequence; `gradient_peaks`
with no window and with 20 windows (edges inside blocks, on block edges and
at the ends); `block_gradient_values`; `pns_levels` with the example
hardware, `thresholds_hz_per_t=(GAMMA_1H,)` and `bin_s=10.0 / 1624`; and
`gradient_spectrum` with the defaults. Each input is signed (D23). For task
2.1 the baseline side calls `pns_levels_for` and `gradient_spectrum_for`. X compares the two outputs
with `cmp`. Remove the baseline worktree after task 2.2.

## 5. The design

### 5.1 The bin of `bin_s` (task 1.2)

D1. `docs/usage.md` section 3, the docstrings of `bin_samples_for`,
`pns_levels`, `PnsLevels` and the `pns.safe.levels` description change from
"rounded down" to the rule of D1, and from "about 6.16 ms" to "5 ms". The
spec's `series` text does not change. With the default, the level has 500
samples in each bin at the 10 us raster, and the summary and the intervals
do not change (they do not depend on `bin_s`).

### 5.2 The check of the hardware (task 1.3)

D2. `_check_hardware` replaces `_require_hardware`. `pns_levels_for` (until
task 2.1) and `pns_levels` call it first. `_hardware_key` then reads only
fields that the check found. The sequence with no gradient event refuses a
bad struct as a sequence with gradients does.

### 5.3 The window of `gradient_peaks` (task 1.4)

D3 and D4. In `gradient_peaks`, the order is: `refuse_rotations`; the form
of `window` and `real` of its two numbers; `start < end`; `sequence_index`;
the range check against `T`; the clip of D3; then `_event_values`. For D4,
`_EventData` gets `first_offset` (K values: the time of the first point from
the block start, the delay of the event), and the junction times of an axis
are `start_s + _event_column(col, ev.first_offset)`. `AxisResult.slew_time_s`
of a junction step and the credit rule ("a junction step is before every
segment of its block") use that time.

### 5.4 Equality and constants (task 1.6)

D5 and D6. `Series` sets `eq=False` (it is already), `__eq__ = fields_equal`
and `__hash__ = None`. `values_equal` already compares two arrays with
`equal_nan` only for the float and complex kinds, and a `Series` holds only
bool, integer, float and complex arrays, so the arrays compare as now.

### 5.5 The kept event points (task 1.7)

D7. `_events.py`:

```python
@dataclass(frozen=True, eq=False)
class EventPoints:
    delay: np.ndarray  # float64, K: the delay of each unique gradient event
    count: np.ndarray  # int64, K: its number of points
    at: np.ndarray  # int64, K: the start of its points in `offsets` and `amp`
    offsets: np.ndarray  # float64: the offsets of all the points, event by event
    amp: np.ndarray  # float64: their amplitudes (Hz/m)


def event_points(seq: pp.Sequence) -> EventPoints: ...
```

`GradientSampler.__init__(self, index, points)` takes its arrays from
`points` (it does not copy them). `_event_values(points)` makes `t_rel[k]`
as `points.delay[k] + points.offsets[at : at + count]`. `_kept.py`'s
docstring lists the new module. A test counts `get_block` calls: the five
measurements of one sequence make K calls in total, where K is the number
of unique gradient events.

### 5.6 One kept entry point (task 2.1)

D8 to D10. The public functions after the task:

| Before | After |
|---|---|
| `pns.pns_levels_for(seq, *, hardware, thresholds_hz_per_t=(), bin_s=BIN_S)` | `pns_levels.pns_levels(seq, *, hardware, thresholds_hz_per_t=(), bin_s=BIN_S)`, kept |
| `pns_levels.pns_levels(...)`, not kept | `pns_levels._compute_levels(...)`, private |
| `grad_spectrum.gradient_spectrum_for(seq, ...)` | `grad_spectrum.gradient_spectrum(seq, ...)`, kept |
| `grad_spectrum.gradient_spectrum(seq, ...)`, not kept | `grad_spectrum._compute_spectrum(...)`, private |
| `grad_peaks.gradient_peaks(seq, *, window=None)`, not kept | the same, kept for `window=None` |
| `grad_peaks.block_gradient_values(seq)`, not kept | the same, kept |
| the module `pns` | none |

The docstrings that say "kept for the sequence object" move from the `_for`
functions to the public functions. `asc.py`, `analyses.py`, `_kept.py`,
`scripts/time_pns_levels.py` (which then times the kept call: it calls
`_compute_levels`, so that each repeat runs the model) and `README.md`
change their references.

### 5.7 The cost of a window (task 2.2)

D11. The kept `_EventData` of task 2.1 gets `end_s` (the end of each block)
and `junction` (for each axis, the steps and their times of D4, for all the
blocks). `_range_result` uses the block range `[a, b)`, where
`a = searchsorted(end_s, lo, side="right")` and
`b = searchsorted(start_s, hi, side="left")`. In that range, a block is
fully inside, or cut by an edge; the masks of lines 474 to 477 are made for
the range only.

### 5.8 The parameters of an analysis (task 2.3)

D12 to D14. `gradient.peaks` with a window gives the result of
`gradient_peaks(seq, window=window)`; its `spec.description` says so.
`gradient.spectrum` gives `gradient_spectrum(seq, ...)` with the three
arguments; its description loses "This analysis has no parameters".
`docs/usage.md` section 6 documents `necessary` and `defaults`, and says
that a runner gives the necessary parameters and can leave out the others.

### 5.9 Consistent result shapes (task 2.4)

D15 to D17. `docs/usage.md`: the bullet "Equality" names `GradientPeaks`
with the results that compare by value, and section 5 gives the checks of
D17.

### 5.10 The pypulseq pin (task 1.8)

D19. The pin changes only `read` of the `[SIGNATURE]` section, so the
values of the package do not change. The tests that read a file get the
hash as text.

### 5.11 The hash of a sequence (task 1.9)

D20 to D22. The order of the checks of each measurement does not change:
its own arguments first, then `refuse_rotations`, then `sequence_index`,
which refuses an unsigned sequence. `docs/usage.md` gets a bullet in the
rules of all the modules: a sequence must have a `[SIGNATURE]` hash, the
package checks only that it is there, and the two stale cases of fact 11
(a sequence changed with `add_block` after `read`, and an unsigned file read
into an object that read a signed file) pass the check. The bullet tells a
caller to use a new `Sequence` object for each file.

## 6. The change

### 6.1 Task 1.1: the test gaps (wave 1)

Branch `fix/second-review-test-gaps`. No change to `src/`. X runs each
mutation of fact 7 on the branch; each must fail a test (N1 to N10).

- **K (H).** Owns `tests/test_kept.py` and `TESTS.md` section 2.12. Four
  tests, one for each of N1 to N4: a new `seq.block_durations` (a new dict
  with each duration doubled, the same keys) gives a new `end_s`; a new
  `seq.block_events` with the same keys and other events gives a new index;
  a new `seq.grad_library` with other amplitudes gives a new
  `pns_levels_for` result; one block removed from the middle (from
  `block_events` and `block_durations`) gives an index of one block less.
- **P (H).** Owns `tests/test_pns_levels.py` and `tests/test_sampling.py`,
  and `TESTS.md` sections 2.2 and 2.5. N6: `_IntervalFinder(1.0, 0.5)` with
  `add_chunk(0, [0, 1])` and `add_chunk(2, [1, 0])` gives one interval with
  `peak_time_s == 1.5`. N7: with `add_chunk(0, [0, 1])` and
  `add_chunk(2, [0, 1])`, two intervals. N8: `_cast_outward` of an array of
  zeros gives zeros, for `down=True` and `down=False`. N5: a ramp from 0 to
  1000 Hz/m whose last point is on a sample time of `dt = 2 * raster`
  (27 raster steps) gives 1000.0 at that sample in `block_samples`.
- **G (M).** Owns `tests/test_grad_peaks.py`, `tests/test_grad_spectrum.py`
  and `TESTS.md` sections 2.6 and 2.10. N9: block 1 ramps x from 0 to A and
  holds A; block 2 is the extended trapezoid `[0, 0, A, A, 0]` in time and
  amplitude such that its steepest segment has the slew of the junction
  step; `slew_time_s` is the time of the junction. N10: a sequence at a
  4 us gradient raster with `window_s=0.01` has the frequency 2000 Hz in
  `frequency_hz`. Each case of `test_gradient_spectrum_refuses_bad_arguments`
  gets a `match=` with a part of its own message.

X changes `TESTS.md` (L19 of the first plan).

### 6.2 Task 1.2: the bin snap (wave 1)

Branch `fix/pns-bin-snap`. One worker (H). Owns `pns_levels.py`, `pns.py`,
`analyses.py` (`_PnsSafeLevels`), `tests/test_pns_levels.py`,
`tests/test_pns.py`, `tests/test_analyses.py`, `TESTS.md` sections 2.2, 2.7
and 2.9, and `docs/usage.md` sections 3 and 6. Section 5.1.

Tests:

- `bin_samples_for(n, 1e-5)` is 500 for the default, and 615 for
  `bin_s=10.0 / 1624`.
- For each `k` from 1 to 2000, `bin_s = k * 1e-5` gives `k` samples (with
  `bin_s` made as `k * 1e-5`, and as `round(k * 1e-5, 10)`).
- `bin_s = 615.5 * 1e-5` gives 615 (a value between two samples is the
  floor).
- The tests that expect 615 for the default expect 500.

### 6.3 Task 1.3: the hardware check (wave 1)

Branch `fix/pns-hardware-check`. One worker (H). Owns `pns_levels.py`
(`_require_hardware`, `_check_hardware`), `pns.py`, `tests/test_pns_levels.py`,
`tests/test_pns.py`, and `TESTS.md` sections 2.2 and 2.7, and
`docs/usage.md` section 3. Section 5.2.

Tests, each for `pns_levels` and for `pns_levels_for`, each with a
`sequence_index` that fails when it is called (as
`test_gradient_spectrum_refuses_bad_arguments` does):

- a struct with no `x`, with no `x.stim_thresh`, with `x.a1 = 5.0`, with
  `x.stim_limit = 0.0`, with `x.tau1 = float("nan")`, and with
  `x.tau1 = "0.2"`, each with its error type and a `match=`;
- the same bad structs on a sequence with no gradient event raise the same
  errors.

Conflict with task 1.2: both change `pns_levels.py` and `pns.py` in other
functions. The second to merge rebases.

### 6.4 Task 1.4: the window of `gradient_peaks` (wave 1)

Branch `fix/gradient-peaks-window`. One worker (H). Owns `grad_peaks.py`,
`tests/test_grad_peaks.py`, `tests/oracles/grad_peaks.py`, `TESTS.md`
section 2.6, and `docs/usage.md` section 2. Section 5.3.

Tests:

- A bad window (each case of the existing window tests) raises before
  `_event_values` is called (a `monkeypatch` that fails).
- `window=(T + 5e-10, T + 9e-10)` gives `range_s == (T, T)` and
  `NO_GRADIENTS_IN_WINDOW`.
- A block with a delayed extended trapezoid that starts at a value that is
  not 0: the junction step has the time `start_s + delay` in
  `gradient_peaks`; a window that starts after `start_s` and before
  `start_s + delay` has that step; a window that ends at `start_s + delay`
  does not.

The oracle does not change (U11): the tests of a delayed junction check
hand-computed values, as the other junction tests do.

### 6.5 Task 1.5: the documentation errors (wave 1)

Branch `docs/second-review-doc-errors`. One worker (M). Owns
`pyproject.toml` (the `description` only), `series.py` (docstrings only),
`_equality.py` (docstring only), and `docs/usage.md` lines 1 to 84.

- `description`: "Derived values of a Pulseq sequence: the block table,
  gradient peaks, SAFE PNS and the gradient spectrum".
- `series.py`: the module and class docstrings give the rules of `meta`
  and of `name` in place, with no reference to `Finding`, to
  "section 4.2 of the design in pulseq-checks" or to a commit of
  pulseq-reports. The sentence that the encoding is that of
  `encode_tables` of pulseq-reports stays, without the commit.
- `_equality.py` lines 1 and 2 name the four classes that use it, and
  line 7 does not name `Series` (task 1.6 adds it again).
- `docs/usage.md` lines 58 and 59: the key has `bin_s`.

Check of X: `git grep -n -E "pulseq-checks|Finding" -- src` finds nothing.

### 6.6 Task 1.6: the duplicates (wave 2)

Branch `refactor/second-review-duplicates`. Section 5.4. The baseline
script gives the same bytes, except for `Series.__eq__`.

- **E (H).** Owns `series.py`, `_equality.py`, `tests/test_series.py`,
  `tests/test_equality.py`, `TESTS.md` sections 2.8 and 2.11, and the bullet
  "Equality" of `docs/usage.md` and its section 5. D5. A test: two series
  whose `meta` differ only in order are not equal; the round trip of
  `to_obj` keeps the order.
- **C (M).** Owns `seq_utils.py`, `seq_index.py`, `sampling.py`,
  `grad_peaks.py`, `pns_levels.py` (the constants only), `grad_spectrum.py`
  (the axes only), `scripts/check_tests_md.py`, `tests/test_seq_utils.py`
  and `TESTS.md` section 2.1. D6. A test: `TIME_TOLERANCE == pp.eps`.

Checks of X:

- [ ] `git grep -n -E "_AXES3?\s*=|_GRAD_COLUMNS\s*=|_AXES\s*=" -- src`
      finds nothing.
- [ ] `git grep -n "pp.eps" -- src` finds nothing.
- [ ] `git grep -n "_same_value\|javascript" -- src scripts` finds nothing.

### 6.7 Task 1.7: the kept event points (wave 3)

Branch `refactor/kept-event-points`. One worker (H). Owns `_events.py`
(new), `_kept.py` (docstring), `sampling.py`, `grad_peaks.py`
(`_event_values`), `pns_levels.py` and `grad_spectrum.py` (the
construction of `GradientSampler`), `tests/test_sampling.py`,
`tests/test_kept.py`, a new `tests/test_events.py`, and `TESTS.md`
sections 2.5, 2.12 and 2.14 (new, "Kept event points (`test_events.py`)").
Section 5.5.

Tests: the `get_block` count of section 5.5; `event_points` is kept, and is
made again after a new read of a file (the stamp of `_kept`); its arrays
are read-only; `GradientSampler` and `_event_values` give the same values as
from `grad_events` (a test that builds them both ways).

Checks of X:

- [ ] The baseline script gives the same bytes.
- [ ] `git grep -n "grad_events(" -- src` finds only `_events.py`.

### 6.8 Task 2.1: one kept entry point (wave 4)

Branch `refactor/one-kept-entry-point`. Section 5.6.

1. At the same time:
   - **N (H).** Owns `pns_levels.py`, `pns.py` (removed),
     `tests/test_pns_levels.py`, `tests/test_pns.py` (moved to
     `tests/test_pns_levels_kept.py`), `asc.py` (docstrings),
     `scripts/time_pns_levels.py`, and `docs/usage.md` section 3. D8 to D10
     for the PNS levels.
   - **S (M).** Owns `grad_spectrum.py`, `tests/test_grad_spectrum.py` and
     `docs/usage.md` section 7. D8 and D9 for the spectrum.
2. Then **R (H).** Owns `grad_peaks.py`, `analyses.py`,
   `tests/test_grad_peaks.py`, `tests/test_analyses.py`, `tests/test_kept.py`,
   `_kept.py` (docstring), `README.md` (the example), and `docs/usage.md`
   sections 2 and 6 and lines 1 to 84. D8 for `gradient_peaks` and
   `block_gradient_values`; `analyses.py` calls the new names; the tests of
   `test_kept.py` call the new names.

Tests: each public measurement gives the same object for a second call, and
a new object after `add_block`; `gradient_peaks` with a window is a new
object for each call; each test of fact 8 calls `_compute_levels` or
`_compute_spectrum` and asserts `first is not second` (D9).

Checks of X:

- [ ] `git grep -n -E "pns_levels_for|gradient_spectrum_for|pulseq_analysis\.pns\b|from \.pns |import pns\b" -- src tests scripts README.md docs/usage.md`
      finds nothing.
- [ ] The baseline script gives the same bytes (`_for` names on the
      baseline side).
- [ ] With the mutation "`_compute_levels` ignores `CHUNK_SAMPLES`" the
      tests still pass (the result does not depend on it), and with the
      mutation "the tests of fact 8 call `pns_levels`" a test fails (the
      `is not` assertion).

### 6.9 Task 2.2: the cost of a window (wave 5)

Branch `refactor/window-cost`. One worker (H). Owns `grad_peaks.py`,
`tests/test_grad_peaks.py`, and `TESTS.md` section 2.6. Section 5.7.

Tests: the results of the window tests do not change; a window in
`build_repeating(1000)` reads no block outside it (a `monkeypatch` of
`_axis_slice_stats` or of `get_block` that records the play indexes).

Checks of X:

- [ ] The baseline script gives the same bytes.
- [ ] On `build_repeating(100_000)` (about 10^6 blocks), 1000 windows of one
      TR take at least 5 times less time than on `origin/main`. X writes
      the two times in the PR description.

### 6.10 Task 2.3: the analysis parameters (wave 5)

Branch `feature/analysis-parameters`. One worker (H). Owns `analyses.py`,
`tests/test_analyses.py`, `TESTS.md` section 2.9, and `docs/usage.md`
sections 1 and 6. Section 5.8.

Tests: the check of `inspect.signature` (D13) for each analysis of
`registry()`; `AnalysisSpec` raises for a `necessary` name that is not in
`params`, for a default of a name in `necessary`, for a name with neither,
and for a default that is not a JSON value; `GRADIENT_PEAKS.compute(seq,
window=w)` equals `gradient_peaks(seq, window=w)`; `GRADIENT_SPECTRUM.compute`
with other arguments equals `gradient_spectrum` with them.

Conflict with task 2.2: none in the files. Both add entries to `TESTS.md`.

### 6.11 Task 2.4: consistent result shapes (wave 6)

Branch `feature/consistent-result-shapes`. Section 5.9.

- **Q (M).** Owns `grad_spectrum.py`, `grad_peaks.py` (`GradientPeaks`
  only), `tests/test_grad_spectrum.py`, `tests/test_grad_peaks.py`,
  `TESTS.md` sections 2.6 and 2.10, and `docs/usage.md` sections 2 and 7,
  and the bullet "Equality". D15 and D16. Tests: `axes` of a sequence with
  no gradient event has the three keys and empty read-only arrays;
  `hash()` of a `GradientPeaks` raises `TypeError`, and two equal results
  are `==`.
- **V (H).** Owns `series.py`, `tests/test_series.py`, `TESTS.md`
  section 2.8, and `docs/usage.md` section 5. D17. Tests: each refused
  value; each series of `pns.safe.levels` and `gradient.spectrum` for the
  sequences of `tests/synthetic.py` and `build_repeating(10)`, with and
  without thresholds, is valid (the tolerance holds).

### 6.12 Task 2.5: the documents and the release (wave 7)

Branch `docs/release-0.1.0rc6`, new from `origin/main` (D18). The text of
the saved draft (step 0) is the start of each document.

- **L (H).** Owns `CHANGELOG.md`. The entry `0.1.0rc6 (<date>)` of the
  draft, with the changes of this plan added: "Fixed" (sections 6.2 to 6.4
  and the test gaps), "Changed" (the bin and its default, the hardware
  errors, the equality of `Series` and `GradientPeaks`, the shapes of
  D15 and D17, the parameters of the analyses, the table of section 5.6),
  "Removed" (`pns`, `pns_levels_for`, `gradient_spectrum_for`). It also
  gives the pin of pypulseq (D19) and the refusal of a sequence with no
  hash (D20), with the stale cases of fact 11. The paragraph "A caller
  moves in this order" gets the new names, the pin, and the signature.
- **D (M).** Owns `README.md`. The line for `0.1.0rc6` of the draft, with
  the changes of this plan. The install line names `v0.1.0rc6`. The example
  runs (D runs it with the example hardware).
- **U (H).** Owns `docs/usage.md`, `docs/reviews/2026-10-04-code-review.md`
  and `docs/reviews/2026-10-05-code-review.md`. A full read of
  `docs/usage.md` against the code, and the corrections. The section
  "Status at 0.1.0rc6" of the draft in the first review, and the same
  section in the second review: for each finding, the task and the PR that
  corrected it, or the reason that it stays (for example review 6.6,
  fact 5).

X changes `version` in `pyproject.toml` to `0.1.0rc6` and the comment of
the draft (`calc_pns` in chunks), runs `nix develop --command uv lock`, does
the checks of section 7, and the tag (L21 of the first plan). After the
merge, X asks the user to remove the old worktree
`.worktrees/release-0.1.0rc6` and its local branch.

### 6.13 Task 1.8: the pypulseq pin (wave 2)

Branch `chore/pypulseq-pin-2`. X alone. Owns `pyproject.toml` (the
`[tool.uv.sources]` entry and its comment), `uv.lock` and `TODO.md`.
Section 5.10.

Checks of X:

- [ ] `uv.lock` has pypulseq at `3c3bd85`, and `uv lock --check` passes.
- [ ] `nix develop --command scripts/check` passes, with no change to a
      test.
- [ ] A file whose hash looks like a number (pypulseq-issues 09) gives that
      hash as a `str` after `read` (a check in the scratchpad, not a test of
      this package).

### 6.14 Task 1.9: require a signature (wave 3)

Branch `feature/require-signature`. Section 5.11.

1. **A (H), first.** Owns `extensions.py`, `seq_index.py`
   (`sequence_index`), `tests/synthetic.py`, `tests/scale_sequences.py`,
   `tests/test_extensions.py`, `tests/test_seq_index.py`, `TESTS.md`
   sections 2.3 and 2.4, and `docs/usage.md` lines 1 to 84 and section 1.
   D20 and D22. Tests: a sequence built in memory raises `ValueError` from
   `sequence_index` and from each public measurement; after `write` it
   passes; `read` of a signed file passes and of an unsigned file (into a
   new object) raises; a `signature_value` that is not a `str` raises; the
   check runs before the kept results are read.
2. **Then T (M).** Owns each other test file and its `TESTS.md` section.
   Each sequence that a test builds for the package goes through `signed`
   (D22). No test changes what it checks.

Checks of X:

- [ ] `nix develop --command scripts/check` passes.
- [ ] With the call of `refuse_unsigned` removed from `sequence_index`, the
      tests of A fail and the others pass.
- [ ] The baseline script (D23) gives the same bytes as on `origin/main`.

## 7. Checks of the release

- [ ] `nix develop --command scripts/check` passes.
- [ ] Each mutation of fact 7, and M1 to M4 of the first plan, fails a test
      (with the names of `0.1.0rc6`).
- [ ] `uv.lock` pins pypulseq at `3c3bd85`.
- [ ] For `build_repeating(10)` (signed, D22), with the example hardware,
      `thresholds_hz_per_t=(GAMMA_1H,)` and `bin_s=10.0 / 1624`: each field
      of `pns_levels` on `0.1.0rc6` equals the field of `v0.1.0rc5`, after
      `dict(...)` of each `FrozenDict`. Run the `v0.1.0rc5` side in a
      worktree of the tag.
- [ ] `scripts/time_pns_levels.py` is not more than 10 % slower than on
      `v0.1.0rc5`.
- [ ] The PR description gives the JSON of `to_obj` of each series of
      `pns.safe.levels` and `gradient.spectrum` for the sequence above, with
      each `data` abbreviated, and the `spec` of each analysis, with
      `necessary` and `defaults`.
- [ ] CI passes on the PR.

## 8. Facts for the follow-up work

These facts are in addition to section 8 of the first plan. Each repository
does its work on its own branch, after the tag `v0.1.0rc6`. The line numbers
are at the commits of section 2, fact 4.

### 8.1 pulseq-checks (`100c3bc`)

1. **`pns_levels_for` becomes `pns_levels`**, from `pulseq_analysis.pns_levels`:
   `tests/test_run.py` lines 9 and 804, and the docstring of
   `src/pulseq_checks/safe_model.py` line 2.
2. **`gradient_spectrum_for` becomes `gradient_spectrum`**: the text of
   `src/pulseq_checks/checks/acoustic.py` line 62, and the `monkeypatch` of
   `tests/test_check_acoustic.py` lines 238 and 244 (the name in the module
   `pulseq_analysis.analyses`).
3. **The bindings.** `gradient.peaks` and `gradient.spectrum` now have
   parameters. `bindings.unavailable` (lines 104 to 109) must call an
   analysis with no binding unavailable only when `spec.necessary` is not
   empty; otherwise `gradient.spectrum` becomes unavailable.
   `Binding.arguments` of `gradient.peaks` gives nothing, so it gets its
   default (the whole sequence).
4. **The hardware.** A bad SAFE struct raises `ValueError` or `TypeError`
   before the sequence is read (D2), for a sequence with or without
   gradients. `hw_from_dict` (`safe_model.py`) makes the struct.
5. **The bin.** The default bin is 5 ms (500 samples at 10 us). The checks
   read only the summary and the intervals, which do not change.
6. **`seq.index`** stays (U5). `SAFE_FIELDS` stays (D6).
7. **The pin.** `pyproject.toml` pins pypulseq at `3c3bd85`
   (`pulseq-reports-pin-2`), as this package does (D19, `TODO.md`).
8. **The hash.** Each analysis and `sequence_index` raise `ValueError` for
   a sequence with no `[SIGNATURE]` hash (D20). A `.seq` file without one
   now fails each analysis of the result matrix. The tests that build a
   sequence in memory must sign it (`write`, or the fields of D22).

### 8.2 pulseq-reports (`68682bd`)

1. **The bin of the PNS diagram.** `src/pulseq_reports/cards/diagram.py`
   line 75 reads `bin_samples` from `meta`, so the diagram follows the new
   default (500 samples at 10 us). For the bins of `0.1.0rc5`, give
   `bin_s=10.0 / 1624` where the report gets the levels.
2. **`PnsLevels.hw`** (`assets/pns_lanes.js` line 239) and
   **`GradientPeaks.whole_rms_hz_per_m`** (`cards/gradient_limits.py`) do
   not change.
3. **`gradient_peaks` with a window** keeps the same values, and costs the
   blocks of the window (task 2.2). `cards/gradient_limits.py` line 312 does
   one call for each window.
4. `rf_events`, `grad_events`, `adc_events` and `block_cache_off` of
   `seq_index` do not change. `sequence_index` refuses a sequence with no
   `[SIGNATURE]` hash (D20), so the cards that call it (`waveforms.py`,
   `rf_exposure.py`, `diagram_data.py`, `rf_profiles.py`) refuse an
   unsigned file too.
5. **The pin.** pypulseq at `3c3bd85` (`pulseq-reports-pin-2`), the same
   commit as this package (D19).

## 9. Later

- **A block replaced in place** is still not seen by the kept results (L3 of
  the first plan).
- **The confidential hardware in a result.** `PnsLevels.hw` holds 24 values
  of an `.asc` file, and pulseq-reports writes them into a report page
  (fact 5). A report for people outside the site would need a choice of the
  user.
- **A kept result for each window** of `gradient_peaks`, with a limit of
  size, if a caller asks for the same windows again.
- **The stale hash** (fact 11, pypulseq-issues 11). When the fork clears
  the signature fields in `read`, `add_block` and `set_block`, pin that
  tag; then the check of D20 has no stale case, and the stamp of `_kept`
  can use the hash.
- **A check of the hash against the file** (U9, alternative): the fork
  computes the MD5 in `read`.
