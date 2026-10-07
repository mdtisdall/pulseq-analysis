# Implementation plan: the fixes of the fourth code review, and the snapshot API

Status: draft, written on 2026-10-07. The user answered its questions on
2026-10-07 (U4 to U10).

## 1. Scope

`docs/reviews/2026-10-07-code-review.md` (in this plan, "the review") gives
the findings of a review of `main` at `83af015`. This plan gives the work that
corrects them, and one change of the interface that the user chose on
2026-10-07 after the review: an explicit snapshot step (section 5.1, U1 to
U3). `docs/plans/third-review-fixes.md` is "the third plan".

The snapshot step changes the cause of review 1.1, 1.5 and 1.7, and it makes
review 4.6 moot. Each other finding has its own task, or an item in section 9
with its reason.

The work has two phases:

- **Phase 1** corrects the code, the tests and the documents, and makes the
  measured speedups. It changes no public name. A few values change, each in
  a rare case or in the last bits (section 5.3).
- **Phase 2** adds the snapshot step, changes the other parts of the
  interface that the review names before 0.1.0, and makes the release. It
  changes the first argument of each public function (section 8).

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/fourth-review-fixes-plan` | This plan, and one line for it in `README.md`. No code. |
| 1.1 | `test/fourth-review-test-gaps` | The tests of the mutations that pass, the vacuous test, and the shared oracle code (review 5.1 to 5.5). |
| 1.2 | `fix/series-robustness` | `Series` and `decode_array` give `ValueError` only, a `Series` copy is checked, and `Series` treats its inputs alike (review 1.6, 1.8, 6.5). |
| 1.3 | `docs/fourth-review-doc-errors` | The documentation errors of the review section 3, and a note in `README.md` that the documents are of `main` (review 3.1 to 3.7). |
| 1.4 | `fix/end-step-tolerance` | The step after the last point of an axis uses `TIME_TOLERANCE`, and the vector peak uses plain arithmetic (review 1.2, 4.4). |
| 1.5 | `fix/block-samples-edges` | `block_samples` with the step rule of `sample` and a tolerance at the last point of an event; no dead branches (review 1.3, 1.4, 4.2, 4.3). |
| 1.6 | `test/fourth-review-test-prune` | The tests that repeat others, the unfinished prune of the third plan, the slow tests, and `TESTS.md` (review 5.6 to 5.8). |
| 1.7 | `perf/grad-peaks-first-call` | A vectorised `_event_values`, a faster `_vector_candidates`, and no kept `_EventData` (review 2.1, 2.2, 4.5). |
| 1.8 | `perf/block-samples` | One gather for the unique events of a part, and the cache key `(event, dt)` (review 2.5, 2.6). |
| 1.9 | `perf/sequence-index` | One read of the block dict, `has_gradients` in O(1), and `_dense` for large IDs (review 2.4, 2.7, 6.7). |
| 1.10 | `perf/spectrum-fft` | `scipy.fft.rfft` in one thread (review 2.3). |
| 1.11 | `refactor/one-gap-rule` | One classification of the gaps and one polyline, used by `grad_peaks` and `sampling` (review 4.1). No value changes. |
| 2.1 | `feature/snapshot` | `snapshot.load(path or sequence)`, and each measurement and analysis takes the snapshot (section 5.1). |
| 2.2 | `feature/analysis-spec-checks` | `AnalysisSpec` checks `id`, `version`, `cost`, `rasters` and `params`, and the documents define the costs (review 6.2). |
| 2.3 | `feature/series-format` | A `"format"` key in the JSON form of a `Series`, and an optional limit of `decode_array` (review 6.3, 6.7). |
| 2.4 | `feature/registry-strict` | `registry(strict=False)` skips the entry points that do not load (review 6.4). |
| 2.5 | `feature/interface-names` | `SeriesKind`, `Analysis` and `FrozenDict` in the documents and at public paths; a `_` for the public names that no document gives (review 6.1). |
| 2.6 | `fix/asc-include-lines` | A `$INCLUDE` line that does not parse raises `ValueError` (review 6.6). |
| 2.7 | `docs/release-0.1.0rc6` | `CHANGELOG.md`, `README.md`, the documents, the status of the four reviews, the version, and the tag (U4). |

Section 8 gives the facts for the follow-up work in pulseq-checks and in
pulseq-reports.

### 1.1 Order

A wave starts when each task of the wave before it has merged. The tasks of
one wave run at the same time, each in its own worktree and session.

```
This plan merged
  Wave 1:  1.1 test gaps  ||  1.2 series robustness  ||  1.3 doc errors
  Wave 2:  1.4 end step  ||  1.5 block_samples edges  ||  1.6 test prune
  Wave 3:  1.7 grad_peaks speed  ||  1.8 block_samples speed
           ||  1.9 index speed  ||  1.10 spectrum FFT
  Wave 4:  1.11 one gap rule
  Wave 5:  2.1 snapshot
  Wave 6:  2.2 spec checks  ||  2.3 series format  ||  2.4 registry
           ||  2.5 interface names (merges last)  ||  2.6 asc includes
  Wave 7:  2.7 release  ->  tag v0.1.0rc6
                              |
                              +->  pulseq-checks: pin v0.1.0rc6 (section 8.1)
                              +->  pulseq-reports: pin v0.1.0rc6 (section 8.2)
```

Why this order:

- Task 1.1 adds the tests that would find a wrong change in tasks 1.4, 1.5,
  1.11 and 2.1. It merges before them.
- Task 1.6 deletes tests in files that task 1.1 changes, so it waits for
  task 1.1, as in the third plan.
- Tasks 1.4 and 1.5 change values (section 5.3). The speedups of wave 3 and
  the refactor of wave 4 must keep each value, so they come after: their
  baselines (section 4.2) then compare the corrected code.
- The tasks of wave 3 change different modules: `grad_peaks.py`,
  `sampling.py`, `seq_index.py` and `grad_spectrum.py`.
- Task 1.11 changes `grad_peaks.py` and `sampling.py` together. No other task
  runs with it.
- Task 2.1 changes the first argument of each public function and each test
  that calls one. No other task runs with it. It comes after the refactors,
  so that their baselines compare one interface.
- The tasks of wave 6 change different modules. Task 2.5 changes the
  documents that the others change, so it merges last, and its branch is
  rebased on the others if it conflicts.

pulseq-checks and pulseq-reports pin `v0.1.0rc5`. No task before the tag
breaks them.

## 2. Context (verified on 2026-10-07)

1. **The repository.** `origin/main` is at `710b70b` (PR #67, the review).
   The tags `v0.1.0rc1` to `v0.1.0rc5` exist. `v0.1.0rc6` does not.
   `pyproject.toml` has the version `0.1.0rc5`. Task 2.6 of the third plan
   (the release) is not done.
2. **The checks.** `nix develop --command scripts/check` passes on `710b70b`:
   ruff, 1049 tests, the `TESTS.md` check (354 entries) and shellcheck.
3. **The release draft.** The worktree `.worktrees/release-0.1.0rc6` has the
   branch `docs/release-0.1.0rc6` with one local commit, `341ebec`, on
   `9197c5d`. The third plan (D22) renames it `wip/release-0.1.0rc6-draft`
   before its release task, with the approval of the user.
4. **The callers.** pulseq-checks and pulseq-reports both pin `v0.1.0rc5`.
   The user decided on 2026-10-07 that their use does not constrain the
   design of this plan (U3).
5. **How pypulseq changes a sequence in place** (the pinned fork `3c3bd85`):
   - `mod_grad_axis` and `flip_grad_axis` call `grad_library.update` for each
     gradient of the axis.
   - `set_block` on an existing ID replaces `block_events[id]`.
   - `apply_soft_delay` writes new values into `block_durations`.
   - `remove_duplicates(in_place=True)` rewrites the libraries and the IDs in
     `block_events`.
   - A caller can also write into `seq.block_events`, the libraries,
     `seq.definitions` or `seq.grad_raster_time` directly. pypulseq does not
     protect them.

   The stamp of `_kept.py` (the identity of three containers, the number of
   blocks, the last ID and the raster) sees none of these (review 1.1).
   `apply_soft_delay` was found after the review, by a read of the code, and
   is not reproduced.
6. **The signature hash.** `extensions.refuse_unsigned` checks only that
   `seq.signature_value` is a `str` that is not `''`. No code uses the hash as
   an identity: D21 of the second plan keeps it out of the stamp, because the
   hash can be stale (pypulseq-issues 11: `read`, `add_block` and `set_block`
   do not clear it). Issue 11 does not name the calls of fact 5.
7. **The cost of a copy** (Apple M1 Max, `tests/scale_sequences.py`):

   | | 100k blocks | 100k blocks, K = 20k | 1M blocks |
   |---|---|---|---|
   | `copy.deepcopy(seq)` | 0.52 s, +30 MB | 1.2 s, +33 MB | 5.5 s, +273 MB |
   | A copy of each mutable object, by type | 84 ms | 138 ms | 0.83 s |
   | `write` + `read` | 1.7 s | 3.8 s | 17.9 s |
   | A full analysis (index, peaks, PNS, spectrum) | about 2.1 s | | about 21 s |

   `copy.deepcopy` of a sequence shares no mutable object with the original
   (checked by a walk of both object graphs), and gives the same results.
8. **The reproductions of the review** are in the session scratchpad, not in
   the repository. Section 6 gives each case that a task must test.

## 3. Decisions

### 3.1 Decisions of the user

The user made U1 to U3 on 2026-10-07, in the discussion of review 1.1, and U4
to U10 on 2026-10-07, in answer to the questions of the draft of this plan.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The kept results and the changes of pypulseq in place | An explicit step makes a snapshot that the package owns. The measurements and the kept results work on it. The documents say that the step is necessary, because pypulseq lets a caller change a sequence in place. | (a) A content hash in the stamp on each call (25 ms for 100k blocks, 25 times the cost of a window). (b) The signature hash as the stamp, after a fork fix of issue 11 for every call that changes a sequence. (c) Document the limit. |
| U2 | The copy | `load(path)` reads the file into a sequence that only the package holds: no copy. `load(seq)` makes `copy.deepcopy(seq)`. | A copy of each mutable object by type (6 times faster, about 50 lines and its own tests). |
| U3 | The callers | The design of this package does not follow the present use of pulseq-checks and pulseq-reports. They change to fit it. | Keep the present call shapes. |
| U4 | The release | All the work goes into `0.1.0rc6`. Task 2.7 replaces task 2.6 of the third plan. The callers move one time. | Tag `0.1.0rc6` now, and this plan makes `0.1.0rc7`. |
| U5 | The first argument of a measurement | A `Snapshot` only. Another type raises `TypeError` that names `load`. | A `pp.Sequence` too, loaded (copied) on each call, with nothing kept. |
| U6 | The names | The module `pulseq_analysis.snapshot`, the function `load` and the class `Snapshot`. `FrozenDict` at `pulseq_analysis.series.FrozenDict`. | `freeze` or `prepare`; `FrozenDict` in a new module `results`. |
| U7 | The sequence of a snapshot | `snapshot.sequence` gives the private `pp.Sequence`. The documents say that a caller and an analysis must not change it. The user prefers a sealed snapshot only if read-only access could be made automatically and simply; it cannot (a proxy needs a list of safe methods kept by hand, and objects from `get_block` can share arrays). | (a) A sealed snapshot with `copy_sequence()`, a new `deepcopy` for each call. (b) A read-only proxy with a list of safe methods. |
| U8 | The threads of the FFT | One thread: chunks stay equal bit for bit. | `workers=-1`: 2.6 times faster, with a tolerance in the chunk test. |
| U9 | The JSON form of a `Series` | A key `"format": 1`. `from_obj` refuses no format, another format, and an unknown key. | Unknown keys ignored; or no change, and the documents say that the keys do not change. |
| U10 | `registry()` and an entry point that does not load | `registry(strict=True)` by default, as now. `registry(strict=False)` leaves the entry point out with a warning that names it. | Always skip with a warning; keep only the strict form; or defer it. |

### 3.2 Decisions of this plan

These decisions follow from the code, from the facts of section 2, or from
the decisions of section 3.1. The approval of this plan approves them. L1,
L2, L17 to L20 of the first plan stay true (a branch and a PR for each task,
no deprecated alias, `spec.version` stays 1, the documents change with each
task, `TESTS.md` by the executing agent in a parallel group, `mv` for a
move).

| # | Decision | Reason |
|---|---|---|
| D1 | The step after the last point of an axis is in no range when the last point is within `TIME_TOLERANCE` of `end_s`. A step at `t` is in a range `[lo, hi]` when `lo <= t < hi - TIME_TOLERANCE`, or `t < hi` when `hi` is not `end_s`. The oracle and `docs/implementation.md` section 1.7 get the same rule. | Review 1.2. The result must not depend on one ulp of `(start + delay) + shape_dur`. |
| D2 | The vector peak uses `gx * gx + gy * gy + gz * gz` in the package and in the oracle. `_sum_of_squares` goes away. | Review 4.4. The arithmetic of the package must not follow the test oracle. A tie can then change in the last bit; the oracle has the same arithmetic. |
| D3 | `_event_samples` gives `_polyline_values(points_t, points_v, t)`: the value before a step, the rule of `sample`. A sample within `TIME_TOLERANCE` after the last point of an event has the value of that point. | Review 1.3, 1.4. One step rule (`docs/implementation.md` section 1.3), and about 25 lines fewer. |
| D4 | The branches for an event with no points go away. `_events._read_points` asserts that each event has two points or more. | Review 4.3. `gradient_offsets` gives two points or more. |
| D5 | `_float_from_json` and `decode_array` raise `ValueError` for a number that overflows, and `decode_array` refuses `length * itemsize > sys.maxsize`. | Review 1.6. One exception type for a bad object. |
| D6 | `Series` gets a `__reduce__` that builds the copy with the constructor, so a copy from `pickle` or `copy.deepcopy` is checked and read-only. `_equality._freeze(*arrays)` makes an array read-only with a base of `bytes` (`np.frombuffer(a.tobytes(), a.dtype)`); `Series` uses it, and task 2.1 uses it in the other modules. | Review 1.8. One rule, in one place, that `flags.writeable = True` cannot undo. |
| D7 | `Series` stores `str(x)` for each string field and each key, and `x.item()` for a numpy scalar of kind `b`, `i`, `u` or `f` in `meta`. `ENVELOPE` needs a real dtype for `min` and `max`, one dtype for both, and `min <= max` where neither is NaN. `POINTS` needs a real dtype for `coord`. | Review 6.5. The round trip is then exact, and the kinds are checked alike. |
| D8 | The values of each unique event (`_event_values`) are made with `np.repeat`, `np.maximum.reduceat` and `np.add.reduceat` over the pooled points. The RMS integral may change by 1e-15 relative or less (the order of the sum). | Review 2.1. 255 ms to 2.5 ms for 20 000 unique events. |
| D9 | `_vector_candidates` merges the sorted point times with `np.concatenate` and `sort(kind="stable")`, and gives the values after each time from the values before it when a polyline has no step. No value changes. `_EventData` is made in `_kept_block_data` and not kept. | Review 2.2, 4.5. |
| D10 | `block_samples` gathers the samples of the unique events of a part with one indexed copy from a pool, with no mask for each event. The cache key is `(event, dt)`; a block uses `samples[:n]`. No value changes. | Review 2.5, 2.6. |
| D11 | `sequence_index` reads the rows of `block_events` with one `np.asarray(list(values))`, and the durations with `np.fromiter`. A file whose rows differ in length uses the present code. `has_gradients` is `index.grad_first.size > 0`. `_dense` uses `np.unique` when the largest ID is more than 16 times the number of entries. No value changes. | Review 2.4, 2.7, 6.7. |
| D12 | `gradient_spectrum` calls `scipy.fft.rfft(..., axis=1)` in one thread. A value may change by 2e-16 relative or less. The test that one chunk equals many chunks stays bit-exact. | Review 2.3 and U8. |
| D13 | `_events.py` gets `axis_events(index, points, axis)` (the first and the last time and value of each event of an axis), `gap_kinds(events, dt)` (zero, short or long, by `TIME_TOLERANCE`) and `polyline(events, ...)` (the points with the ramps and the end steps). `grad_peaks` and `sampling` use them. `grad_peaks._polyline_values` gets another name. No value changes. | Review 4.1. Review 1.2 to 1.4 were each a case where the copies could disagree. |
| D14 | The snapshot of section 5.1. | U1, U2. |
| D15 | `_kept.py` goes away. The kept results of a snapshot are in a dict on the snapshot, with keys by measurement and arguments. | The private sequence of a snapshot does not change, so no stamp is needed. Review 4.6 is then moot. |
| D16 | `load` calls `refuse_unsigned` and `refuse_rotations`. The measurements do not call them again. | Review 1.7: one place and one order for the checks. |
| D17 | `rf_events(snapshot)`, `grad_events(snapshot)` and `adc_events(snapshot)` give a tuple of `(number, event)`, made one time and kept. The private sequence has `use_block_cache = False`, set by `load`. `block_cache_off` goes away from the interface. | Review 1.5. The block cache of a sequence that the package owns cannot reach the caller. |
| D18 | `Analysis.compute(snapshot, **params)`. A runner calls `load` one time for each file. | U1. An analysis must not see a sequence that can change. |
| D19 | `AnalysisSpec` checks: `id` is a `str` that is not empty; `version` is an `int` of 1 or more, not a `bool`; `cost` is `"fast"` or `"slow"`; each name of `rasters` is in `analyses.RASTERS` (`"GradientRasterTime"`, `"BlockDurationRaster"`, `"RadiofrequencyRasterTime"`, `"AdcRasterTime"`); `params` is a tuple of unique `str`; a float default is finite. Each refusal raises `ValueError` (or `TypeError` for a wrong type). The documents define the costs: "fast" grows with the blocks and the unique events, "slow" with the duration. | Review 6.2. pulseq-checks branches on `cost` and matches `rasters`. |
| D20 | `Series.to_obj()` gives a key `"format": 1`. `from_obj` refuses an object with no `"format"`, with another format, or with a key that format 1 does not have. `decode_array(d, *, max_bytes=None)` and `from_obj(obj, *, max_bytes=None)` refuse more than `max_bytes` decompressed bytes. | Review 6.3, 6.7 and U9. A reader can then tell the forms apart. |
| D21 | `registry(*, strict=True)`. With `strict=False`, an entry point that does not load, or that breaks a rule of the registry, is left out with a `RegistryWarning` (a subclass of `UserWarning`) that names it. The analyses of this package always load. | Review 6.4 and U10. |
| D22 | `docs/usage.md` names `SeriesKind` and the `Analysis` protocol. `FrozenDict` is exported at the public path of U6. Each public name that no document gives gets a `_` (for example `asc.INCLUDE_LINE`), unless a document gives it in this task. | Review 6.1. |
| D23 | `asc` matches `$INCLUDE` with any case, a quoted name with spaces, and a comment after the name. Any other line that starts with `$INCLUDE` (any case) raises `ValueError` that names the file and the line. The order of the fields (an included field wins) stays, and the docstring says it. | Review 6.6. |

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
| 1.1 | 1 | 2: S (H), G (H) | S and G at the same time |
| 1.2 | 1 | 1 (M) | — |
| 1.3 | 1 | 1 (M) | — |
| 1.4 | 2 | 1 (H) | — |
| 1.5 | 2 | 1 (H) | — |
| 1.6 | 2 | 1 (M) | — |
| 1.7 | 3 | 1 (H), after a baseline by X | — |
| 1.8 | 3 | 1 (H), after a baseline by X | — |
| 1.9 | 3 | 1 (M), after a baseline by X | — |
| 1.10 | 3 | 1 (M) | — |
| 1.11 | 4 | 1 (H), after a baseline by X | — |
| 2.1 | 5 | 4: C (H), then M (H), T (M) and D (M) | C first, then M, T and D at the same time |
| 2.2 | 6 | 1 (M) | — |
| 2.3 | 6 | 1 (M) | — |
| 2.4 | 6 | 1 (M) | — |
| 2.5 | 6 | 1 (M) | — |
| 2.6 | 6 | 1 (M) | — |
| 2.7 | 7 | 3: L (H), D (M), U (H) | L, D and U at the same time |

### 4.2 The baseline of a refactor

Tasks 1.7, 1.8, 1.9 and 1.11 must not change a value, except the RMS
integral of D8. X uses the baseline worktree `.worktrees/base` and the script
of section 4.2 of the second plan, with these inputs added:

- `build_worst(2000)`, for the unique events of task 1.7;
- 20 seeds of `_random_gap_sequence` of `tests/test_grad_peaks.py`, with 40
  windows each, for task 1.11;
- `block_samples` of each axis of these sequences with `skip` and `count` at
  the edges of a chunk, for tasks 1.8 and 1.11.

X moves the worktree to the current `origin/main` before each task:

```bash
git -C /Users/dylan/dev/pulseq-analysis/.worktrees/base checkout --detach origin/main
(cd /Users/dylan/dev/pulseq-analysis/.worktrees/base && nix develop --command uv sync --frozen)
```

X compares the two outputs with `cmp`. For task 1.7, the RMS values are
compared to 1e-15 relative and each other value with `cmp`. Remove the
baseline worktree after task 1.11.

## 5. The design

### 5.1 The snapshot (task 2.1)

```python
from pulseq_analysis.snapshot import load
from pulseq_analysis.grad_peaks import gradient_peaks
from pulseq_analysis.pns_levels import pns_levels

snap = load("sequence.seq")  # or load(seq) for a pp.Sequence
peaks = gradient_peaks(snap)
levels = pns_levels(snap, hardware=hardware)
```

`load(source)`:

1. `source` is a path (`str` or `os.PathLike`): `seq = pp.Sequence()` and
   `seq.read(source)`. No other object holds `seq`, so no copy is made.
2. `source` is a `pp.Sequence`: `seq = copy.deepcopy(source)`, with the block
   cache of `source` set aside during the copy and put back after it, as
   pypulseq's `remove_duplicates` does. `source` is not changed.
3. Any other type raises `TypeError`.
4. `refuse_unsigned(seq)` and `refuse_rotations(seq)` (D16).
5. `seq.use_block_cache = False` (D17).
6. It gives a `Snapshot` that holds `seq`. It builds no result: each result is
   made on its first use and kept (D15).

`Snapshot`:

- `sequence`: the private `pp.Sequence` (U7). The documents say that a caller
  and an analysis must not change it. It is the one way to reach it.
- `source`: the path that `load` read, or `None` for a `pp.Sequence`.
- `==` and the hash are those of `object`, by identity. A snapshot can be a
  key of a dict.
- `pickle` gives a snapshot with no kept results, which builds them again.

Each public function of the package takes a `Snapshot` as its first argument
(U5), and raises `TypeError` for another type with a message that names
`load`:

| At `710b70b` | After task 2.1 |
|---|---|
| `sequence_index(seq)` | `sequence_index(snap)` |
| `rf_events(seq, index)`, `grad_events(seq, index)`, `adc_events(seq, index)` (generators) | `rf_events(snap)`, `grad_events(snap)`, `adc_events(snap)` (tuples, kept, D17) |
| `block_cache_off(seq)` | gone (D17) |
| `gradient_peaks(seq, *, window=None)` | `gradient_peaks(snap, *, window=None)` |
| `block_gradient_values(seq)` | `block_gradient_values(snap)` |
| `pns_levels(seq, *, hardware, ...)` | `pns_levels(snap, *, hardware, ...)` |
| `gradient_spectrum(seq, *, ...)` | `gradient_spectrum(snap, *, ...)` |
| `gradient_sampler(seq)` | `gradient_sampler(snap)` |
| `Analysis.compute(seq, **params)` | `Analysis.compute(snap, **params)` (D18) |
| `extensions.refuse_rotations(seq)`, `refuse_unsigned(seq)` | unchanged, called by `load` |

The guard tests of the snapshot (`tests/test_snapshot.py`):

1. **No shared mutable object.** A walk of every object reachable from the
   source and from `snapshot.sequence` (attributes, dicts, lists, tuples,
   sets, object arrays) finds no object in both, except numbers, strings,
   `None`, tuples of these and read-only arrays. An object of a type that the
   walk does not know counts as mutable. It runs on sequences made by
   `add_block` with each kind of event, and by `read` of a file with
   definitions, labels, extensions and soft delays.
2. **Fidelity.** `snapshot.sequence.write(path)` gives the same bytes as
   `source.write(path)`, and each measurement gives an equal result for
   `load(seq)` and for `load(path)` of the written file.
3. **Independence.** After `load(seq)`, `seq.mod_grad_axis("x", 0.5)`,
   `seq.set_block(...)` on an existing ID, `seq.apply_soft_delay(...)` and a
   direct write into `seq.block_events` change no result of the snapshot. A
   new `load(seq)` gives the new values. (These are examples. Test 1 is the
   proof for every way to change `seq`.)
4. **The checks.** `load` of an unsigned sequence raises `ValueError`, and of
   a sequence with the rotation extension raises `NotImplementedError`. A
   measurement of a snapshot calls neither again.

The documents: `docs/usage.md` section 1 starts from `load`, and section 2
says why the step is necessary (pypulseq lets a caller change a sequence in
place, and a measurement must describe one fixed sequence). `docs/implementation.md`
section 4 ("Kept results") is rewritten for the snapshot, and section 7 says
that the signature hash is checked for its presence only and is not an
identity.

### 5.2 The tests of the gap model (task 1.1)

Review 5.1. The oracle comparisons of `GradientSampler.sample`,
`block_samples`, `pns_levels` (on the raster and off it) and
`gradient_spectrum` get:

- the 8 seeds of `_random_gap_sequence` that `test_grad_peaks.py` uses, moved
  to a helper module of `tests/` so that each test file can use them;
- a negated copy of each sequence of `tests/gap_sequences.py`;
- a sequence with a gap of 1.5 raster times, with end values that are not 0;
- a short gap from 0 to a value that is not 0.

Each of the mutations of `_find_gaps` in the table of the review section 5
must fail a test.

### 5.3 The values that change

| Task | Change | Where |
|---|---|---|
| 1.4 | The step after the last point of an axis at the end of the sequence is never counted (D1). | `gradient_peaks`, `block_gradient_values`: a sequence whose last gradient ends at a value that is not 0 at `end_s`. |
| 1.4 | The vector peak in the last bit, and a tie between two times (D2). | `GradientPeaks.vector_peak_*`, `BlockGradientValues.vector_peak_*`. |
| 1.5 | A sample at the last point of an event, or at a step inside one event, that lands on a sample time (D3). | `block_samples`, and so `pns_levels` on the raster: a gradient delay off the raster, or an arbitrary gradient of 4 samples or fewer. |
| 1.7 | The RMS integral, 1e-15 relative or less (D8). | `AxisResult.rms_hz_per_m`. |
| 1.10 | The spectrum, 2e-16 relative or less (D12). | `GradientSpectrum`. |

## 6. The change

### 6.1 Task 0: this plan

This file, and a line in the "Documents" list of `README.md`.

### 6.2 Task 1.1: the test gaps (wave 1)

Worker S (`test_sampling.py`, `test_pns_levels.py`, `test_pns_levels_kept.py`,
`test_grad_spectrum.py`, a new helper module for the random gap sequences)
and worker G (`test_grad_peaks.py`, `test_series.py`, `test_seq_index.py`,
`tests/oracles/waveform.py`). No change to `src/`. X checks each mutation of
the table of the review section 5 on a copy of `src/`: each must fail a test.

Worker S:

- Section 5.2.
- `test_the_defaults_are_those_of_pypulseq` compares `_compute_spectrum` with
  the explicit values, so that the two results are not one kept object, and
  its `TESTS.md` entry says that it also guards pypulseq's defaults (review
  5.2).
- The key of the PNS hardware: a test parametrized over the 8 fields of
  `_HW_FIELDS` (review 5.3).
- `a1 + a2 + a3 = 1.005` raises `ValueError` (the mutation of
  `_A_SUM_TOLERANCE`).

Worker G:

- A window that ends at a step up, with hand values: a block that ends at U,
  the next block starts at 3U, and the window ends at the junction. The vector
  peak is U (review 5.4).
- `block_gradient_values` of a zero event (`scale_grad(trap, 0)`) after a
  long gap: its slew time is the block start (review 5.4).
- `oracles/waveform.values_at` is written as a loop over the segments, with
  no code of `sampling._polyline_values` (review 5.5).
- A hand-made vector tie in which a later block has the earlier time
  (review 5.5).
- A tie of a step and a segment in a window (the mutation of the order key of
  `_evaluate_axis`).
- `decode_array` of data with bytes after the gzip stream raises `ValueError`.
- The dtypes of the index at 255 and at 65 535 unique events.

### 6.3 Task 1.2: the robustness of `Series` (wave 1)

D5, D6 and D7, each with a test: a `"length"` of `10**30` and a coordinate of
`10**400` raise `ValueError`; a `Series` from `pickle` and from
`copy.deepcopy` has read-only arrays and is checked (a copy of a bad state
cannot be made); `flags.writeable = True` raises on a frozen array; `meta`
takes `np.float32`, `np.int64` and `np.bool_` and stores Python scalars; a
`str` subclass round-trips to an equal series; the new refusals of
`ENVELOPE` and `POINTS`. `decode_array` stores a bool as 0 or 1.

### 6.4 Task 1.3: the documentation errors (wave 1)

Each item of the review section 3, in `docs/usage.md`,
`docs/implementation.md`, the docstrings and the descriptions of the analyses:

- `README.md` gets a note above the install line: the documents describe
  `main`, and `v0.1.0rc5` has an older interface. Task 2.7 replaces the note
  with the install line of the new tag.
- `docs/implementation.md` section 3, with the corrections of review 3.2. The
  costs measured again where a correction changes them.
- The kept-result caveat names `mod_grad_axis`, `flip_grad_axis`,
  `set_block` and `apply_soft_delay`, until task 2.1 (review 3.7).
- The descriptions of `gradient.peaks` (the RMS has no block and no time) and
  of `gradient.spectrum` (the line across a short gap), and the
  `ValueError` of an unsigned sequence in each description (review 3.6).

The items of review 3.1 that are the release (the version and
`CHANGELOG.md`) wait for task 2.7.

### 6.5 Task 1.4: the end step (wave 2)

D1 and D2. In `grad_peaks.py`, `tests/oracles/waveform.py` and
`docs/implementation.md` section 1.7. Tests: the sequence of review 1.2
(an extended trapezoid that ends at A at the end of the sequence) gives the
same largest slew in memory and after `write` and `read`, for 20 end times;
the step is counted when the last point is more than `TIME_TOLERANCE` before
`end_s`.

### 6.6 Task 1.5: the edges of `block_samples` (wave 2)

D3 and D4, in `sampling.py` and `_events.py`. Tests: the 8 cases of review
1.3 (a gradient delay off the raster by half a raster time, behind filler
blocks) and the 3-sample arbitrary gradient of review 1.4 equal the oracle in
`block_samples` and in `pns_levels`. The docstring of `block_samples` gives
the step rule. `test_gradient_sampler_equals_the_sampler_of_the_constructor`
goes away (review 5.6), here because this task owns `test_sampling.py` in
wave 2.

### 6.7 Task 1.6: the test prune (wave 2)

Review 5.6 to 5.8, except the test of `test_sampling.py` (task 1.5):

- Delete `test_example_hardware_for_spin_echo` (or keep only its "highest on
  y" assertion in the test it repeats),
  `test_grad_dense_numbering_follows_gx_then_gy_then_gz_within_a_block`,
  `test_a_gradient_on_one_axis_has_a_prediction`, `_points_from_grad_events`
  and its test, and the smaller overlaps of review 5.6.
- `test_event_values_of_the_points_equal_the_values_of_gradient_points` uses
  hand values, or goes away if the hand-computed test covers it.
- `test_matches_oracle_on_long_sequences` uses `CHUNK_WINDOWS = 4` on a short
  sequence; `test_a_window_gives_the_same_result_with_and_without_the_kept_data`
  uses 30 windows for each sequence.
- `TESTS.md`: the contents in the order of the sections, and the tests of
  `asc.py` in a section of their own (the tests move to `tests/test_asc.py`
  with `mv` of their code).

### 6.8 Task 1.7: the first call of `gradient_peaks` (wave 3)

D8 and D9. No test changes. X makes the baseline before and after
(section 4.2), and times `build_worst(20000)` and `build_repeating(20000)`
before and after for the PR description. `docs/implementation.md` section 3
gets the new times.

### 6.9 Task 1.8: the speed of `block_samples` (wave 3)

D10. No test changes, except a test that one event in blocks of two lengths
gives the samples of each length. Baseline as in section 4.2.

### 6.10 Task 1.9: the speed of `sequence_index` (wave 3)

D11. A test: a sequence with an event ID of 10^8 builds its index with less
than 100 MB (`tracemalloc`). Baseline as in section 4.2.

### 6.11 Task 1.10: the FFT of the spectrum (wave 3)

D12. The spectrum tests pass with no change of tolerance, and
`test_chunks_give_the_same_spectrum_as_one_chunk` stays bit-exact.
`docs/implementation.md` section 3 gets the new time.

### 6.12 Task 1.11: one gap rule (wave 4)

D13. `grad_peaks.py`, `sampling.py` and `_events.py`. No test changes.
Baseline as in section 4.2. The module docstrings of `grad_peaks` and
`sampling` say that the rule is in `_events`.

### 6.13 Task 2.1: the snapshot (wave 5)

D14 to D18 (section 5.1). Worker C first: `snapshot.py`, `seq_index.py`,
`_events.py`, `sampling.py`, the removal of `_kept.py`, `_freeze` in each
module (D6), and `tests/test_snapshot.py` (the four guard tests). Then, at
the same time:

- Worker M: `grad_peaks.py`, `pns_levels.py`, `grad_spectrum.py`,
  `analyses.py` (the descriptions too), and `scripts/` (the timing scripts and
  `doc_figures.py`).
- Worker T: each other test file. `tests/synthetic.py` gets `loaded(seq)`,
  which gives `load(signed(seq))`. `tests/test_kept.py` and the stamp tests of
  `tests/test_pns_levels_kept.py` go away; test 3 of section 5.1 replaces
  them. Each test of a function's checks keeps its order: the arguments
  first, then the type of the first argument.
- Worker D: `docs/usage.md`, `docs/implementation.md` (sections 3 and 4, and
  each example), the module docstrings, and `README.md`'s example.

### 6.14 Task 2.2: the checks of `AnalysisSpec` (wave 6)

D19. A test for each refusal, and a test that the five analyses of the
package pass. `docs/usage.md` section 7 defines "fast" and "slow".

### 6.15 Task 2.3: the format of a `Series` (wave 6)

D20 and U9. Tests: `to_obj` has `"format": 1`; `from_obj` refuses no format,
format 2 and an unknown key; `max_bytes` refuses a larger array. The JSON
example of `docs/usage.md` and `docs/implementation.md` section 8.

### 6.16 Task 2.4: a registry that skips (wave 6)

D21 and U10. Tests with a fake entry point that does not load: `registry()`
raises `RegistryError`; `registry(strict=False)` warns with
`RegistryWarning` and gives the other analyses.

### 6.17 Task 2.5: the names of the interface (wave 6)

D22 and U6. A test that each name that `docs/usage.md` and
`docs/implementation.md` give in backticks with a module path can be
imported, and that no other public name of a module exists without a `_`
(a list of exceptions in the test, with a reason for each).

### 6.18 Task 2.6: the `$INCLUDE` lines (wave 6)

D23. Tests: the three forms that match, and a line that does not parse
raises `ValueError` that names the file.

### 6.19 Task 2.7: the documents and the release (wave 7)

As task 2.6 of the third plan (with its D22), and U4, with these additions:

- The `CHANGELOG.md` entry of `0.1.0rc6` has the changes of the four plans.
  "Changed" leads with the snapshot (section 5.1, with its table), then the
  values of section 5.3 and of the third plan. "Added" gives `snapshot.load`,
  `registry(strict=...)`, `max_bytes` and the `"format"` key. "Removed" gives
  `block_cache_off`.
- A section "Status at 0.1.0rc6" at the end of
  `docs/reviews/2026-10-07-code-review.md`: each finding with its task, or
  "not changed" with the reason.
- `README.md`: the line of this plan, the example with `load`, and the
  install line of `v0.1.0rc6` in place of the note of task 1.3.

## 7. Checks of the release

Before the tag, X checks:

1. `nix develop --command scripts/check` passes on `main`.
2. Each mutation of the table of the review section 5 fails a test.
3. The reproductions of review 1.1 to 1.6 give the corrected result: the
   values after `mod_grad_axis` of the source do not change a snapshot; the
   sequence of review 1.2 gives one largest slew before and after `write`;
   `block_samples` equals the oracle for review 1.3 and 1.4; `grad_events`
   does not touch the block cache of the source; `from_obj` raises only
   `ValueError`.
4. A sequence of `tests/synthetic.py` gives the values of `710b70b`, except
   for the changes of section 5.3.
5. The number of tests is that of `710b70b`, less the deleted tests, plus the
   new tests, and `TESTS.md` has an entry for each.
6. `scripts/time_measurements.py` and `scripts/time_pns_levels.py` on
   100 000 blocks, with the times in `docs/implementation.md` section 3.5 and
   the cost of `load(seq)` and `load(path)` added.

## 8. Facts for the follow-up work

### 8.1 pulseq-checks

- Each file is loaded one time with `load(path)`, and each analysis gets the
  snapshot: `analysis.compute(snap, **params)` (D18). The analyses of other
  packages change their `compute` in the same way.
- `spec.cost` is `"fast"` or `"slow"` and `spec.rasters` holds only the names
  of `analyses.RASTERS` (D19).
- `registry(strict=False)` lets a run go on when an entry point of another
  package does not load (D21).
- The JSON form of a series has `"format": 1` (D20).
- The values change in the cases of section 5.3.

### 8.2 pulseq-reports

- `rf_events(snap)`, `grad_events(snap)` and `adc_events(snap)` take no index
  and give tuples. `block_cache_off` goes away (D17): the snapshot's sequence
  has no block cache.
- The cards get a snapshot from the caller, not a `pp.Sequence`. A card that
  needs pypulseq reads `snap.sequence` and does not change it (U7).
- `encode_array` does not change. `Series.to_obj` has the `"format"` key.

## 9. Later

- **Extend pypulseq-issues 11** to each call of fact 5 (`mod_grad_axis`,
  `flip_grad_axis`, `apply_soft_delay`, `remove_duplicates(in_place=True)`,
  `set_definition`), in 11a and 11b, with the rule "a method that changes what
  `write` writes clears the signature fields". After task 2.1 the package
  does not depend on it, so it is a report for pypulseq, not a task here.
- **The pypulseq-issues references** in the docstrings, `TESTS.md`,
  `TODO.md`, `pyproject.toml` and the tests go away before 0.1.0.
- **A faster `load(seq)`.** A copy of each mutable object by type (fact 7),
  if a profile shows that `copy.deepcopy` is a cost for the callers. Guard
  test 1 of section 5.1 then checks it with no change.
- **The FFT in threads** (U8), if the spectrum's time matters more than
  chunks that are equal bit for bit.
- **The order of the fields of an `.asc` file** (review 6.6): file order, if a
  real file needs it.
- **A check that the data model of pypulseq has not changed** at a change of
  the pin: a test that fails when the attributes of `Sequence` change, to
  prompt a review of what the measurements read. It goes with the move from
  the fork (`TODO.md`).
