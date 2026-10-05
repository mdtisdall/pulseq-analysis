# Implementation plan: the fixes of the code review (0.1.0rc6)

Mode: Strict STE100. Structural rules are enforced. Lexical rules are a
direction of travel, not a verified dictionary match.

Status: draft, not approved. Written on 2026-10-04.

## 1. Scope

`docs/reviews/2026-10-04-code-review.md` (in this plan, "the review") gives
the findings of a review of `0.1.0rc5`. This plan gives the work that
corrects them, and the changes of the interface that the user chose on
2026-10-04 (section 3.1). All of the work goes into one release candidate,
`0.1.0rc6`.

The work has two phases:

- **Phase 1** corrects the code, the tests and the documents, and does not
  break a caller. It includes the corrections of the review sections 1 to 5.
- **Phase 2** changes the interface. It breaks callers in pulseq-checks and
  pulseq-reports. It includes the changes of the review section 6 that the
  user chose, and the release.

Each task is one branch and one PR (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/review-fixes-plan` | This plan, and one line for it in `README.md`. No code. |
| 1.1 | `fix/test-gaps` | The tests that the review section 5 asks for. No change to `src/`. |
| 1.2 | `fix/stale-kept-results` | Kept results that see a new read of a file (review 1.1). |
| 1.3 | `fix/read-only-index` | The arrays of `SequenceIndex` are read-only (review 1.2). |
| 1.4 | `fix/long-block-sampling` | `pns_levels` does not grow with the square of a block length (review 2.1). |
| 1.5 | `refactor/grad-limits-internals` | One helper for each repeated part of `grad_limits`, and the safe triple key (review 1.3, 4). |
| 1.6 | `refactor/spectrum-bins` | Fewer frequency bins in the spectrum, only if a measurement shows a gain (review 2.2). |
| 1.7 | `refactor/test-helpers` | One copy of each test helper, and the script corrections (review 4, 5). |
| 2.1 | `refactor/remove-report-helpers` | No `peak_tr_window`, `pns_prediction`, `PnsPrediction`, `hold_samples` or `PNS_LIMIT` (review 6.3, 6.4). |
| 2.2 | `refactor/rename-peaks` | `grad_limits` becomes `grad_peaks` (review 6.4). |
| 2.3 | `feature/explicit-pns-hardware` | The PNS hardware is necessary on every entry point (review 6.1, 6.5). |
| 2.4 | `feature/pns-bin-size` | The bin of the PNS level is the argument `bin_s` (review 6.2). |
| 2.5 | `feature/consistent-results` | One rule for "no result", for a number argument, for equality and for read-only results (review 1.4, 6.6 to 6.8). |
| 2.6 | `docs/release-0.1.0rc6` | `CHANGELOG.md`, the version, and tag `v0.1.0rc6`. |

Section 8 gives the facts for the follow-up work in pulseq-checks and in
pulseq-reports.

### 1.1 Order

A wave starts when each task of the wave before it has merged. The tasks of
one wave run at the same time, each in its own worktree and session.

```
This plan merged
  Wave 1:  1.1 fix/test-gaps         ||  1.2 fix/stale-kept-results
  Wave 2:  1.3 fix/read-only-index   ||  1.4 fix/long-block-sampling
           ||  1.5 refactor/grad-limits-internals  ||  1.6 refactor/spectrum-bins
  Wave 3:  1.7 refactor/test-helpers
  Wave 4:  2.1 refactor/remove-report-helpers
  Wave 5:  2.2 refactor/rename-peaks  ||  2.3 feature/explicit-pns-hardware
  Wave 6:  2.4 feature/pns-bin-size
  Wave 7:  2.5 feature/consistent-results
  Wave 8:  2.6 docs/release-0.1.0rc6  ->  tag v0.1.0rc6
                                            |
                                            +->  pulseq-checks: pin v0.1.0rc6 (section 8.1)
                                            +->  pulseq-reports: pin v0.1.0rc6 (section 8.2)
```

Why this order:

- Task 1.1 adds the tests that find the errors of tasks 1.4 and 1.5. It
  merges before them.
- Task 1.2 and task 1.3 both change `seq_index.py`, so task 1.3 waits for
  task 1.2.
- Task 1.7 changes many test files. It runs alone, after each test change of
  phase 1, and before phase 2 changes the tests again.
- Task 2.1 removes code. Tasks 2.2 and 2.3 then change less code.
- Tasks 2.3, 2.4 and 2.5 change the same functions of `pns_levels.py` and
  `pns.py`, so they run one after the other.

pulseq-checks pins `v0.1.0rc5`, and pulseq-reports pins `v0.1.0rc2`. No task
before the tag breaks them, because each keeps its pin until its own branch
changes it. `main` between two merges is not a release.

## 2. Context (verified on 2026-10-04)

1. **The repository.** `origin/main` is at `b5b6c9c` (PR #16, the review).
   The tags `v0.1.0rc1` to `v0.1.0rc5` exist. `pyproject.toml` has the
   version `0.1.0rc5`.
2. **The checks.** `nix develop --command scripts/check` passes on `b5b6c9c`:
   ruff, 678 tests (193 test functions), the `TESTS.md` check (193 entries)
   and shellcheck.
3. **The callers.** pulseq-checks `origin/main` (`100c3bc`) pins
   `v0.1.0rc5`. pulseq-reports `origin/main` (`2a516b4`) pins `v0.1.0rc2`.
4. **A new read of a file.** In the pinned pypulseq fork (`a74ab06`),
   `Sequence.read` sets a new `EventLibrary` in `seq.grad_library`
   (`pypulseq/Sequence/read_seq.py` line 49), a new dict in
   `seq.block_events` (line 61) and a new dict in `seq.block_durations`
   (line 309). `add_block` changes these objects in place.
5. **The stale results** (review 1.1) were reproduced: after a second read
   into one object, `sequence_index(seq).end_s` was 0.0034 s, and a new
   object gave 0.0074 s.
6. **The long blocks** (review 2.1) were measured: `pns_levels` took 0.87 s
   for 1200 blocks of 0.1 s delay (each after a trapezoid), and 9.78 s for
   one block of 120 s delay.
7. **The mutations** of the review section 5. Each of these single-line
   changes passes all the tests on `b5b6c9c`:
   - M1: `_read_sampled_range` ignores `s0` (`pns_levels.py` line 425).
   - M2: `floor` in place of `ceil` in `num_samples` of the off-raster path
     (`pns_levels.py` line 277).
   - M3: `GradientSampler.sample` without the neighbour events:
     `event_blocks[lo_pos:hi_pos]` (`sampling.py` line 123).
   - M4: no check `nwin < 2` (`grad_spectrum.py` line 110).
8. **The use of the names that phase 2 changes** (the count of lines, from
   `git grep -c` in `src`, `tests`, `scripts`, `docs/usage.md`, `README.md`,
   `TESTS.md` and `pyproject.toml`):

   | Names | Lines |
   |---|---|
   | `pns_prediction`, `PnsPrediction` | 41 |
   | `peak_tr_window` | 24 |
   | `hold_samples` | 9 |
   | `EXAMPLE_HARDWARE` | 14 |
   | `PNS_LIMIT` | 20 |
   | `EXACT_MAX_S`, `DISPLAY_BINS`, `bin_samples_for` | 28 |
   | `grad_limits`, `GradientLimits`, `gradient_limits`, `GRADIENT_LIMITS`, `gradient.limits` | 169 |

   The tests call `pns_levels`, `pns_levels_for` or `PNS_SAFE_LEVELS.compute`
   on 84 lines. `scripts/time_pns_levels.py` calls `pns_levels(seq)` without
   hardware (lines 97 and 99).
9. **The agents.** `.claude/agents/worker-medium.md` and
   `.claude/agents/worker-high.md` define the workers of section 4.

## 3. Decisions

### 3.1 Decisions of the user

The user made U1 to U7 on 2026-10-04.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The scope | Each finding of the review sections 1 to 5, and these changes of the review section 6: explicit PNS hardware (6.1), the bin size as an argument (6.2), the report helpers out (6.3), the new names (6.4), and one rule for the hardware arguments, for "no result", for the registry, for equality and for read-only results (6.5 to 6.8). | A smaller part of section 6. |
| U2 | The release | One release candidate, `0.1.0rc6`, for all the work. | (a) `0.1.0rc6` with no break, then `0.1.0rc7` with the breaks. (b) No release in the plan. |
| U3 | The names of `grad_limits` | `peaks`: `grad_limits` becomes `grad_peaks`, `GradientLimits` becomes `GradientPeaks`, and `gradient.limits` becomes `gradient.peaks`. `PNS_LIMIT` goes away. | (a) `values`. (b) `summary`. (c) Remove `PNS_LIMIT` only. (d) No change. |
| U4 | The PNS hardware | Necessary. There is no shortcut to pypulseq's example hardware: a caller that wants it makes the pair with `safe_example_hw()`. | (a) A sentinel value for the example hardware. (b) The two arguments, with `hardware=EXAMPLE`. |
| U5 | The bin of the PNS level | The argument `bin_s`, in seconds, with a default that gives the bins of `0.1.0rc5`. `MAX_BINS` still limits the memory. | (a) `bin_s` with no default. (b) `max_bins`. |
| U6 | The report helpers | Remove them from this package. pulseq-reports takes them over. | Keep them. |
| U7 | The callers | This plan gives the facts for pulseq-checks and pulseq-reports (section 8). Each repository does its own work. | This repository only. |
| U8 | The form of the PNS hardware (made on 2026-10-05, during task 2.3) | Only the vendor-neutral pair `(struct, label)`, in the argument `hardware`, which is necessary. The package does not take a Siemens `.asc` path in its PNS interface: `gradient_asc` and `PnsLevels.asc_file` go away. The optional helper `asc.hardware_from_asc(path)` makes the pair from a Siemens gradient `.asc` file. | (a) `gradient_asc` and `hardware`, exactly one necessary (the first version of task 2.3, PR #27 before this decision). (b) No `.asc` reader in the package at all. |

### 3.2 Decisions of this plan

These decisions follow from the code or from the decisions of section 3.1.
The approval of this plan approves them.

| # | Decision | Reason |
|---|---|---|
| L1 | Each task of section 1 is one branch and one PR. The tag is on the merge commit of task 2.6 only. | `CLAUDE.md`. U2. |
| L2 | No deprecated alias for a removed or renamed name. An old name raises `ImportError`, `AttributeError` or `TypeError`. | A release candidate has no compatibility promise (L2 of `docs/plans/gamma-free-units.md`). An error is better than a silent change. |
| L3 | The kept results have one stamp for each sequence object: the objects `seq.block_events`, `seq.block_durations` and `seq.grad_library` (compared with `is`), the number of blocks, the last block ID, and `seq.grad_raster_time`. A different stamp empties the kept results of that object. One private module, `_kept.py`, has this rule for `sequence_index`, `pns_levels_for` and `gradient_spectrum_for`. | Fact 4. A new read makes new objects, and `add_block` changes the number of blocks. The stamp keeps a reference to the three objects, not to the sequence, so the `WeakKeyDictionary` still lets the sequence go. |
| L4 | `GradientSampler.block_samples` gets the keyword arguments `skip=0` and `count=None`. Its result is `full[skip : skip + count]`, where `full` is the result of `0.1.0rc5`, bit for bit, but it does not make the samples outside that range. The kept samples of an event stop at the last point of the event. The samples after it are 0. | Review 2.1. Bit-for-bit equality keeps the results of `pns_levels` the same. |
| L5 | Task 1.6 starts with a measurement. The change merges only when the tests pass with their tolerances unchanged, and the peak memory of `gradient_spectrum` falls by 30 % or more, or its time by 20 % or more. Otherwise the task stops, and task 2.6 writes the result in the review. | The FFT makes all the bins, so the gain can be small. |
| L6 | `_range_result` and `_block_vector_peaks` use one helper for the distinct triples of events, with the two-step key of `_block_vector_peaks`. | Review 1.3 and 4. |
| L7 | (Changed by U8.) `pns_levels`, `pns_levels_for` and the analysis `pns.safe.levels` take the hardware only as the keyword argument `hardware`, with no default: a call without it raises Python's `TypeError`. A `hardware` that is not a pair with a `str` label raises `TypeError` before the sequence is read. `gradient_asc`, `PnsLevels.asc_file`, the `meta` key `asc_file` of the series `pns_total` and `asc.EXAMPLE_HARDWARE` go away. `asc.hardware_from_asc(path)` gives the pair of a Siemens gradient `.asc` file. | U4 and U8. Review 6.5: every entry point has the same hardware argument. A required keyword is the rule of Python for a necessary argument. |
| L8 | `pns_levels.BIN_S = 10.0 / 1624` (about 6.16 ms). `bin_samples_for(num_samples, dt, bin_s=BIN_S)` is `max(floor(bin_s / dt), ceil(num_samples / MAX_BINS), 1)`. `EXACT_MAX_S` and `DISPLAY_BINS` go away. `PnsLevels` gets no new field: `bin_samples * dt_s` gives the bin. | U5. `10.0 / 1624` is the float of `EXACT_MAX_S / (2 * DISPLAY_BINS)`, so the default bins are those of `0.1.0rc5`, bit for bit. |
| L9 | `_equality.FrozenDict` is a subclass of `dict` whose methods that change it raise `TypeError`. It can be pickled and copied with `copy.deepcopy`. Each dict of a result that the package makes is a `FrozenDict`. `values_equal` compares a `FrozenDict` and a `dict` as two dicts (the type rule does not separate them). | Review 6.7. A subclass of `dict` keeps `isinstance(x, dict)`, the interface that the docstring of `PnsLevels` names, and `json.dumps` (pulseq-reports puts `levels.hw` into JSON, section 8.2). `MappingProxyType` cannot be pickled. pulseq-checks makes a `PnsLevels` with `dataclasses.replace` and a plain dict (section 8.1), and compares results with `==`. |
| L10 | `SequenceIndex` and `BlockGradientValues` compare by value (`_equality.fields_equal`) and are not hashable. The arrays of `BlockGradientValues` are read-only. | Review 6.7. The rule of `PnsLevels` and `GradientSpectrum`. |
| L11 | `seq_index.NO_GRADIENTS = "no gradients"` and `seq_index.NO_GRADIENTS_IN_WINDOW = "no gradients in the window"`. `pns_levels.NO_GRADIENTS` and `grad_spectrum.NO_GRADIENTS` are the same object, imported. `GradientPeaks.reason` is one of the two, or `None`. `seq_index.has_gradients(index)` replaces the two copies of the test. | Review 6.6 and 4. |
| L12 | One private helper, `_validate.real(name, value, *, finite=True, positive=False)`, checks each number argument. A value that is a `bool` or not a `numbers.Real` raises `TypeError`. A value that is too large for a float, not finite (with `finite=True`) or not above 0 (with `positive=True`) raises `ValueError`. It is used for the thresholds, `bin_s`, the arguments of `gradient_spectrum`, the `window` of `gradient_peaks`, and the coordinates of a `Series` (with `finite=False`). | Review 4. A threshold of a wrong type then raises `TypeError`, not `ValueError`, and `np.float32` and `np.int64` thresholds are valid. |
| L13 | When the PNS peak is 0, `peak_time_s` is `None`, and the model does not run a second time. | Review 1.4. The rule of `grad_limits` for a largest value of 0. |
| L14 | `registry()` raises `RegistryError` when the name of an entry point is not the `spec.id` of its object. | Review 6.8. The docstring says that the name is the ID. |
| L15 | `pns.py` stays. After task 2.1 it holds `pns_levels_for` and its key. | The kept result of the PNS model has one place. |
| L16 | Task 2.2 also renames the test files, the oracle file and each test function whose name has `limits` in it, with their `TESTS.md` entries. `AxisResult`, `BlockGradientValues`, `block_gradient_values` and `gradient.blocks` keep their names. | U3. One name in the code and in the tests. |
| L17 | `spec.version` of each analysis stays 1. | L3 of `docs/plans/gamma-free-units.md`: a release candidate has no compatibility promise. |
| L18 | `docs/usage.md`: each task changes the sections of its own change. `CHANGELOG.md` and the version change only in task 2.6. | Tasks of one wave change different sections of `docs/usage.md`, so their merges do not conflict. Every task of a wave would change the same lines of `CHANGELOG.md`. |
| L19 | When a task has sub-agents that run at the same time, only the executing agent changes `TESTS.md`. Each worker gives the text of its entries in its report. | `dev-workflow:parallel-agents`: two sub-agents that run at the same time do not share a file. |
| L20 | A worker moves a file with `mv`, not `git mv`. | The workers do no git writes. Git finds the rename in the diff. |
| L21 | The tag `v0.1.0rc6` is an annotated tag on the merge commit of task 2.6. The executing agent shows the command, and pushes the tag only after the user approves. | L17 of `docs/plans/gamma-free-units.md`. |

## 4. How to execute this plan

The workflow is that of `docs/plans/implementation.md` section 4:

1. Start each branch with the `dev-workflow:start-task` skill, from the
   latest `origin/main`. Then run `nix develop --command uv sync --frozen`
   one time in the worktree, before a worker starts.
2. Each test that a task adds, moves or changes gets its `TESTS.md` entry in
   the same PR (L19 for a task with parallel workers).
3. Run `nix develop --command scripts/check` before each PR.
4. Show the commit message to the user, and wait for approval before
   `git commit`. Merge only when the user tells you to.
5. The executing agent reviews each worker's diff line by line.
6. When a task finds that this plan is wrong, stop and ask the user.

Tiers:

| Tier | Agent | Use it for |
|---|---|---|
| M | `worker-medium` (Sonnet, medium effort) | A rename, a move, a removal, or code or tests that this plan gives exactly. |
| H | `worker-high` (Sonnet, high effort) | A design with local decisions, subtle numerical code, an independent oracle, or a long document. |
| X | The executing agent | The baselines, the measurements, the mutation checks, `TESTS.md` in a parallel group, the review of each diff, the questions to the user, and the tag. |

Give each worker: the task, the worktree, this plan and the sections of the
task, the files that it owns, the files that it may read, and the checks to
run. Workers put scratch files in the session scratchpad.

### 4.1 Parallel work

There are two levels (`dev-workflow:parallel-agents`):

- **Between tasks:** the tasks of one wave (section 1.1) run in different
  worktrees and sessions. A later merge of a wave rebases on the earlier
  merges. The tasks of one wave change different parts of a shared file
  (`TESTS.md`, `docs/usage.md`, `analyses.py`), so a conflict is in
  neighbouring lines only. Resolve it by keeping both changes.
- **In one task:** the workers of one group start in one message. Two workers
  of one group never own the same file.

| Task | Wave | Workers | Groups |
|---|---|---|---|
| 1.1 | 1 | 4: P (H), S (H), G (M), O (H) | P, S, G and O at the same time |
| 1.2 | 1 | 1 (H) | — |
| 1.3 | 2 | 1 (M) | — |
| 1.4 | 2 | 1 (H), after a baseline by X | — |
| 1.5 | 2 | 1 (H), after a baseline by X | — |
| 1.6 | 2 | X measures, then 0 or 1 (H) | — |
| 1.7 | 3 | 2: T (M), C (M) | T and C at the same time |
| 2.1 | 4 | 2: R (M), V (H) | R and V at the same time |
| 2.2 | 5 | 1 (M) | — |
| 2.3 | 5 | 2: A (H), B (M) | A and B at the same time |
| 2.4 | 6 | 1 (H) | — |
| 2.5 | 7 | 4: F (M), then Q (H), N (H) and K (M) | F first, then Q, N and K at the same time |
| 2.6 | 8 | 3: L (H), D (M), U (H) | L, D and U at the same time |

### 4.2 The baseline of a refactor

For tasks 1.4, 1.5, 1.6 and 1.7, the behavior must not change. The executing
agent makes the baseline worktree of `dev-workflow:parallel-agents`:

```bash
git -C /Users/dylan/dev/pulseq-analysis worktree add --detach .worktrees/base origin/main
(cd /Users/dylan/dev/pulseq-analysis/.worktrees/base && nix develop --command uv sync --frozen)
```

It runs the same script, with the same inputs, in the baseline and in the
task worktree, and compares the outputs byte for byte (`cmp`). The script is
in the session scratchpad. It writes each float with `float.hex` and each
array with `tobytes().hex()`, so equal text means equal bits. Refresh the
baseline after each merge:
`git -C /Users/dylan/dev/pulseq-analysis/.worktrees/base checkout --detach origin/main`.
Remove it after task 1.7.

## 5. The design

### 5.1 The kept results (task 1.2)

`src/pulseq_analysis/_kept.py`:

```python
def kept_results(cache: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]", seq) -> dict:
    """The dict of the kept results of `seq` in `cache`. It is a new, empty dict
    when the stamp of `seq` (L3) is not the stamp of the last call."""
```

The stamp is L3. The entry holds the stamp and the dict. `sequence_index`
keeps its index in the dict with the key `"index"`. `pns_levels_for` keeps
its results with the key `(hardware key, thresholds)` (and, after task 2.4,
`bin_s`). `gradient_spectrum_for` keeps its results with the key of its
three arguments. The three functions do not compare a block count or a block
ID any more.

The docstrings of the three functions and the bullet "Kept results" of
`docs/usage.md` give the new rule: a result is made again after `add_block`,
after a new read into the object, and after a change of
`seq.grad_raster_time`. A block replaced in place is still not seen.

### 5.2 The read-only index (task 1.3)

`_build_index` sets `writeable = False` on each array of the
`SequenceIndex`. No module of the package writes into these arrays (the
worker checks each use). A caller that needs a writable array makes a copy.

### 5.3 The samples of a block range (task 1.4)

```python
def block_samples(self, axis, first, stop, dt, *, skip=0, count=None) -> np.ndarray:
```

- `count=None` means all the samples after `skip`. `skip` and `count` are 0
  or more, and `skip + count` is not more than the samples of the range.
  Else `ValueError`.
- The result is the result of `0.1.0rc5` for `(axis, first, stop, dt)`,
  sliced with `[skip : skip + count]`, bit for bit (L4).
- The first and the last block of the range give only their samples inside
  `[skip, skip + count)`. A block between them gives all its samples.
- `event_samples` keeps the samples of `(event, n)` only up to the last
  sample at or before the last point of the event. The samples after it are
  0, and the result does not keep them.
- `_read_block_range` of `pns_levels.py` gives `skip = s0 - offset` and
  `count = s1 - s0`, and does not slice.

The memory of `pns_levels` is then the chunk, the samples of the events
(each up to its last point), the level and the intervals. It does not grow
with the length of a block.

### 5.4 The new names (task 2.2)

| `0.1.0rc5` | `0.1.0rc6` |
|---|---|
| module `pulseq_analysis.grad_limits` | `pulseq_analysis.grad_peaks` |
| `GradientLimits` | `GradientPeaks` |
| `gradient_limits(seq, *, window=None)` | `gradient_peaks(seq, *, window=None)` |
| analysis ID `gradient.limits`, title "Gradient limits" | `gradient.peaks`, title "Gradient peaks" |
| `analyses.GRADIENT_LIMITS`, class `_GradientLimits` | `analyses.GRADIENT_PEAKS`, class `_GradientPeaks` |
| entry point `"gradient.limits" = "pulseq_analysis.analyses:GRADIENT_LIMITS"` | `"gradient.peaks" = "pulseq_analysis.analyses:GRADIENT_PEAKS"` |
| `tests/test_grad_limits.py`, `tests/oracles/grad_limits.py` | `tests/test_grad_peaks.py`, `tests/oracles/grad_peaks.py` |
| `TESTS.md` section 2.6 "Gradient limits (`test_grad_limits.py`)" | "Gradient peaks (`test_grad_peaks.py`)" |
| `docs/usage.md` section 2 "`grad_limits`: gradient amplitude and slew" | "`grad_peaks`: gradient amplitude and slew" |

The docstrings say "the peak values" where they say "the limit numbers". The
module docstring starts: "The peak amplitude, the peak slew rate and the RMS
amplitude of a sequence's gradients." The review section 3 sentence "The
largest of each array is the value of `gradient.limits`" becomes: "The
largest of each amplitude array is the value of `gradient.peaks`. Its slew is
the larger of the largest segment slew and the largest junction step."

### 5.5 The PNS hardware (task 2.3)

U8 and L7 give this design. It replaces the first version of task 2.3 (exactly one of
`gradient_asc` and `hardware`).

```python
pns_levels(seq, *, hardware, thresholds_hz_per_t=())
pns_levels_for(seq, *, hardware, thresholds_hz_per_t=())
PNS_SAFE_LEVELS.compute(seq, *, hardware, thresholds_hz_per_t=())
asc.hardware_from_asc(path) -> tuple[SimpleNamespace, str]
```

- `hardware` is the pair `(struct, label)`: a SAFE hardware struct in the form of
  pypulseq's `asc_to_hw`, and its name. It is necessary, with no default.
- `asc.hardware_from_asc(path)` is `(asc_to_hw(asc), hardware_name(asc))` of
  `asc = read_gradient_asc(path)`. Two calls for one file (a relative and an absolute
  path, for example) give the same label and values, so one kept result.
- For pypulseq's example hardware, which is not a real scanner, a caller gives
  `hardware=(safe_example_hw(), "<a label>")`. The documents and the `TypeError` of a
  bad `hardware` say so.
- `spec.params` of `pns.safe.levels` becomes `("hardware", "thresholds_hz_per_t")`.

The tests get one constant in `tests/synthetic.py`:

```python
# pypulseq's example SAFE hardware, which is not a real scanner. The package has no
# default hardware: the tests give this pair.
EXAMPLE_HW = (safe_example_hw(), "pypulseq example hardware (not a real scanner)")
```

### 5.6 The bin of the level (task 2.4)

`pns_levels`, `pns_levels_for` and `PNS_SAFE_LEVELS.compute` get the keyword
argument `bin_s=BIN_S` (L8). A check before the sequence is read refuses a
`bin_s` that is a `bool`, not a real number, not finite, or not above 0.
Task 2.4 writes this check in `pns_levels.py`, and task 2.5 replaces it with
`_validate.real("bin_s", bin_s, positive=True)`. A `bin_s` shorter than `dt` gives bins
of one sample. `spec.params` of `pns.safe.levels` gets `"bin_s"`. The key of
`pns_levels_for` gets `float(bin_s)`.

### 5.7 The removals (task 2.1)

| Name | Where a caller finds it after `0.1.0rc6` |
|---|---|
| `pns.pns_prediction`, `pns.PnsPrediction` | The same fields of `pns_levels_for(...)`: `reason`, `hardware`, `peak_hz_per_t`, `peak_time_s`, `axis_peaks_hz_per_t` (`asc_file` goes away with U8). |
| `pns.peak_tr_window` | pulseq-reports (section 8.2). |
| `seq_utils.hold_samples` | pulseq-reports (section 8.2). |
| `pns_levels.PNS_LIMIT` | pulseq-checks: the limit of a fraction is 1, so the limit in Hz/T is `abs(gamma)`. |

The tests that test `pns_levels_for` through `pns_prediction` call
`pns_levels_for` and read the same fields. The tests of `peak_tr_window` and
`hold_samples` go away, with their `TESTS.md` entries. The README example
uses `pns_levels_for`.

### 5.8 Consistent results (task 2.5)

- `FrozenDict` (L9) in `_equality.py`. Each dict of `PnsLevels` (`hw` and its
  inner dicts, `axis_peaks_hz_per_t`, `above`), `GradientSpectrum` (`axes`),
  `GradientPeaks` (`axes`, `whole_rms_hz_per_m`) and `BlockGradientValues`
  (its five dicts) is a `FrozenDict`.
- Equality (L10), the reasons (L11), the numbers (L12), the zero peak (L13)
  and the registry (L14).
- The docstring of `Series` gives units of `0.1.0rc6` as examples (`"Hz/T"`,
  `"Hz/m"`, `"s"`). "design section 4.2" becomes "section 4.2 of the design
  in pulseq-checks (`docs/plans/pulseq-analysis.md`)".

## 6. The change

Each task starts after its wave of section 1.1. After each task,
`nix develop --command scripts/check` passes.

### 6.1 Task 1.1: the test gaps (wave 1)

Branch `fix/test-gaps`. No change to `src/`. Four workers at the same time:

- **P (H).** Owns `tests/test_pns_levels.py`.
  - An off-raster sequence of more than three chunks (with `CHUNK_SAMPLES`
    patched small with `monkeypatch`, as the chunk tests do): its result
    equals the result with one chunk (`==`), and `num_samples` is
    `ceil((end_s - 1e-10) / dt)`.
  - An off-raster sequence longer than one chunk at the real
    `CHUNK_SAMPLES`: the summary equals `seq.calculate_pns` within the
    tolerance of `test_off_raster_block_falls_back_to_sampling`.
  - An interval that covers three chunks or more: `above` with small chunks
    equals `above` with one chunk.
  - `test_pns_levels_is_a_frozen_dataclass` also checks that an assignment
    to a field raises `dataclasses.FrozenInstanceError`.
- **S (H).** Owns `tests/test_sampling.py`. For a sequence with a step at a
  block junction and a gap after it: `sample(axis, t[i:j])` equals
  `sample(axis, t)[i:j]` exactly, for each `i` and `j` of a grid of sample
  times around the step and in the gap.
- **G (M).** Owns `tests/test_grad_limits.py` and
  `tests/test_grad_spectrum.py`. The two `ValueError`s of a bad `window` of
  `gradient_limits` (start not before end, including NaN; outside the
  sequence by more than `TIME_TOLERANCE`), each with `match=`. A `match=`
  for the case `window_of_one_sample`.
- **O (H).** Owns `tests/oracles/grad_limits.py`. The oracle stops importing
  `gradient_points` and `TIME_TOLERANCE` from the package. It gets its own
  corner points from the fields of the event (`type`, `delay`, `rise_time`,
  `flat_time`, `fall_time`, `amplitude`, `tt`, `waveform`, `first`, `last`,
  `shape_dur`) and its own tolerance `1e-9`. The oracle tests then pass
  without a change of a tolerance.

X adds the `TESTS.md` entries (L19), then does the mutation check: apply each
of M1 to M4 (section 2, fact 7) in turn to a copy of `src/` in the
scratchpad, and run the tests against it. Each mutation must fail a test.

### 6.2 Task 1.2: the stale kept results (wave 1)

Branch `fix/stale-kept-results`. One worker (H). Owns
`src/pulseq_analysis/_kept.py` (new), `sequence_index` in `seq_index.py`,
`pns_levels_for` in `pns.py`, `gradient_spectrum_for` in `grad_spectrum.py`,
`tests/test_kept.py` (new), the new `TESTS.md` section 2.12 "Kept results
(`test_kept.py`)", and the bullet "Kept results" of `docs/usage.md`.

The design is section 5.1. The tests of `tests/test_kept.py`:

- Two files with the same number of blocks and different gradients, read
  one after the other into one object: `sequence_index`, `gradient_limits`,
  `pns_levels_for` and `gradient_spectrum_for` give the values of a new
  object that read the second file.
- `pns_levels_for` gives a new result after `add_block`, and the same object
  again without a change.
- A relative and an absolute path of one `.asc` file give the same object.
- A change of the last block ID with the same number of blocks gives a new
  index.
- A change of `seq.grad_raster_time` gives a new index and new results.
- A kept result does not keep the sequence: after `del seq` and
  `gc.collect()`, a `weakref` to it is dead.

### 6.3 Task 1.3: the read-only index (wave 2)

Branch `fix/read-only-index`, after task 1.2. One worker (M). Owns
`seq_index.py` and `tests/test_seq_index.py`, `TESTS.md` section 2.4, and
`docs/usage.md` section 1.

- Section 5.2.
- A test: each array of `sequence_index(seq)` raises `ValueError` when a
  value is written into it.
- The comment at `seq_index.py` line 121 names `waveforms._timed_blocks`,
  which does not exist. The worker replaces it with the function of
  `tests/oracles/blocks.py` that adds the durations in order, after it reads
  that function. If no function does, the worker removes the name and keeps
  the rest of the comment.

### 6.4 Task 1.4: long blocks (wave 2)

Branch `fix/long-block-sampling`. X makes the baseline (section 4.2) and
measures, then one worker (H). The worker owns `sampling.py`,
`_read_block_range` in `pns_levels.py`, `tests/test_sampling.py`,
`tests/test_pns_levels.py`, `TESTS.md` sections 2.2 and 2.5, and
`docs/usage.md` section 4.

- Section 5.3.
- Tests: `block_samples(axis, first, stop, dt, skip=s, count=c)` equals
  `block_samples(axis, first, stop, dt)[s : s + c]` exactly, for ranges that
  start and end inside a block, at a block edge, inside a block without an
  event, and inside a block whose event stops before the block end. The
  `ValueError`s of a bad `skip` or `count`.
- `docs/usage.md` section 4: `raster_block_lengths` gives one bool for all
  the blocks (review section 3).

Checks of X:

- [ ] The baseline script of section 4.2 gives the same bytes for
      `pns_levels` (with all its fields) of each sequence of
      `tests/synthetic.py`, `build_repeating(1000)` and `build_worst` of
      `tests/scale_sequences.py`, the sequence of 120 s of section 2 fact 6,
      and an off-raster sequence.
- [ ] The time of the one block of 120 s is not more than two times the time
      of the 1200 blocks. The PR description gives the times before and
      after.
- [ ] `scripts/time_pns_levels.py` is not more than 10 % slower than on the
      baseline.

### 6.5 Task 1.5: the internals of `grad_limits` (wave 2)

Branch `refactor/grad-limits-internals`. X makes the baseline, then one
worker (H). The worker owns `grad_limits.py`, `tests/test_grad_limits.py`,
`TESTS.md` section 2.6, and `docs/usage.md` section 2.

- One helper for the peak, the slew, their times and the integral of one
  polyline. `_event_values` and the edge-block loop of `_range_result` use it.
- One helper for the junction steps of one axis. `_range_result` and
  `block_gradient_values` use it.
- One helper for the distinct triples of events (L6). `_range_result` and
  `_block_vector_peaks` use it. A test: for random triples with event
  numbers up to 3,000,000, the groups of the helper are the groups of
  `np.unique(np.stack(...), axis=0)`.
- The documents of the review section 3: the `get_block` sentences (module
  docstring, `gradient_limits`, `block_gradient_values`, and
  `docs/usage.md` line 158: each reads one block for each unique gradient
  event, and `gradient_limits` also reads the blocks that a window edge
  cuts), "The four dicts" (five), and "0 for the first block" (the step
  from 0 to the first value of the block).

Checks of X:

- [ ] The baseline script gives the same bytes for `gradient_limits` (the
      whole file and three windows) and `block_gradient_values` of each
      sequence of `tests/synthetic.py`, `build_repeating(1000)` and
      `build_worst`.

### 6.6 Task 1.6: the spectrum bins (wave 2)

Branch `refactor/spectrum-bins`, after task 1.2. X measures first:

1. The peak memory (`tracemalloc`) and the time of `gradient_spectrum` with
   the default arguments on `build_repeating(10000)`, in the baseline.
2. A prototype in the scratchpad: for each chunk, the windows as a strided
   view, the constant detrend and the Hann window of scipy's `spectrogram`,
   `np.fft.rfft` with `n=nfft`, and the kept bins sliced before `abs`, with
   the scale of `mode="magnitude"`.
3. The gain (L5). If there is no gain, stop. Task 2.6 writes the
   measurement in the review.

If there is a gain, one worker (H) owns `grad_spectrum.py`,
`tests/test_grad_spectrum.py` and `TESTS.md` section 2.10. A new test:
the spectrum of the new code equals the spectrum of scipy's `spectrogram`
within a relative 1e-12, for three sequences. The oracle tests do not
change.

### 6.7 Task 1.7: the test helpers (wave 3)

Branch `refactor/test-helpers`. X makes the baseline. Two workers at the same
time:

- **T (M).** Owns `tests/` (all the files).
  - `tests/test_pns_levels.py` uses the fixture `write_gradient_asc` of
    `tests/conftest.py`, and has no copy of it.
  - `tests/scale_sequences.py` imports `SYSTEM`, the constants,
    `block_pulse` and `readout` from `synthetic`. Its comment on why it
    does not import from `tests/` goes away.
  - One copy of each of these, in `tests/synthetic.py` (a sequence or a
    hardware) or in a new `tests/asserts.py` (a comparison):
    `_assert_levels_equal`, `_with_rotation_library` and `_QUATERNION`,
    `_waveform_sequence`, `_hardware_for_peak`, `_assert_block_values_equal`,
    and `crosses`/`across` with `_chunk_across_an_interval`. The builders of
    `tests/test_grad_limits.py` lines 831, 875 and 890 replace the same
    sequences that the tests at lines 417 to 527 build inline.
  - The docstring of `tests/oracles/blocks.py` does not name
    `tests/test_waveforms.py`. The docstring of
    `test_off_raster_block_falls_back_to_sampling` does not name
    `docs/plans/cards-at-scale.md`.
- **C (M).** Owns `scripts/check_tests_md.py` and
  `scripts/time_pns_levels.py`.
  - `check_tests_md.py` line 80: the name of a test is
    `node_id.split("[", 1)[0].split("::")[-1]`, so a parametrize ID with
    `::` gives the right name.
  - `time_pns_levels.py`: `--blocks` below 5 is an argument error, and the
    thresholds are checked before the sequence is built.

Checks of X:

- [ ] `nix develop --command uv run pytest --collect-only -q` gives the same
      test IDs as on the baseline, and the same number of passed tests.
- [ ] `git diff origin/main -- TESTS.md` is empty.

### 6.8 Task 2.1: remove the report helpers (wave 4)

Branch `refactor/remove-report-helpers`. Two workers at the same time:

- **R (M).** Owns `src/pulseq_analysis/pns.py`, `seq_utils.py`,
  `pns_levels.py` (only `PNS_LIMIT` and the text that names it),
  `docs/usage.md` sections 3 and 4, and `README.md` (the example). Section
  5.7. The module docstring of `pns.py` names only `pns_levels_for`. The
  module docstring of `seq_utils.py` does not name `hold_samples`.
- **V (H).** Owns `tests/test_pns.py`, `tests/test_seq_utils.py`,
  `tests/test_analyses.py`, `tests/test_pns_levels.py` and
  `tests/conftest.py`. Each test of `pns_levels_for` that calls
  `pns_prediction` calls `pns_levels_for` and checks the same fields. The
  tests of `peak_tr_window` and `hold_samples` go away. `PNS_LIMIT * GAMMA_1H`
  becomes `GAMMA_1H` (a fraction of 1 times γ). V gives X the list of the
  removed and the renamed tests.

X changes `TESTS.md`, then checks:

- [ ] `git grep -n -E "pns_prediction|PnsPrediction|peak_tr_window|hold_samples|PNS_LIMIT" -- src tests scripts docs/usage.md README.md TESTS.md`
      finds nothing.

### 6.9 Task 2.2: the new names (wave 5)

Branch `refactor/rename-peaks`. One worker (M). Owns each file that has a
name of section 5.4: `src/pulseq_analysis/grad_limits.py` (moved to
`grad_peaks.py`), `analyses.py` (only the gradient parts and the module
docstring), `extensions.py`, `seq_utils.py`, `pyproject.toml` (the entry
point), `tests/test_grad_limits.py` (moved), `tests/oracles/grad_limits.py`
(moved), `tests/test_analyses.py` (only the gradient parts),
`tests/test_pns_levels.py` and the other tests that import the module,
`TESTS.md` and `docs/usage.md` section 2 and the lines of other sections
that name it. Section 5.4 and L16, L20.

The docstring of `extensions.refuse_rotations` names the four functions
that call it: `grad_peaks.gradient_peaks`,
`grad_peaks.block_gradient_values`, `pns_levels.pns_levels` and
`grad_spectrum.gradient_spectrum` (review section 3).

Checks of X:

- [ ] This command finds only `CHANGELOG.md`, `docs/plans/` and
      `docs/reviews/`:

      ```bash
      git grep -n -i -E "grad_limits|GradientLimits|gradient_limits|gradient\.limits|GRADIENT_LIMITS"
      ```
- [ ] `nix develop --command uv run python -c "from pulseq_analysis.analyses import registry; print(sorted(registry()))"`
      gives `gradient.peaks` and not `gradient.limits`.

### 6.10 Task 2.3: explicit PNS hardware (wave 5)

Branch `feature/explicit-pns-hardware`. The text below is the first version of the
task. After U8, the same two workers, with the same files, made the design of section
5.5 on the same branch: `gradient_asc` goes away, and the tests give
`hardware=hardware_from_asc(path)` where they gave `gradient_asc=path`. Two workers at
the same time:

- **A (H).** Owns `pns_levels.py`, `pns.py`, `asc.py`, `analyses.py` (only
  `_PnsSafeLevels` and its line of the module docstring),
  `scripts/time_pns_levels.py`, `tests/test_analyses.py` (only the PNS
  parts), `docs/usage.md` section 3 and section 6, and `README.md`. Section
  5.5 and L7. New tests in `tests/test_analyses.py`: `compute` with neither
  raises `ValueError`; `compute` with `gradient_asc` gives the object of
  `pns_levels_for` with the same file. `time_pns_levels.py` gives the
  example hardware explicitly, and its docstring says so.
- **B (M).** Owns `tests/synthetic.py`, `tests/conftest.py`,
  `tests/test_pns_levels.py` and `tests/test_pns.py`. `EXAMPLE_HW` of
  section 5.5. Each call of `pns_levels` or `pns_levels_for` without
  hardware gives `hardware=EXAMPLE_HW`. Each check of
  `levels.hardware == EXAMPLE_HARDWARE` checks the label of `EXAMPLE_HW`. New
  tests: `pns_levels` and `pns_levels_for` with neither raise `ValueError`
  with the message of section 5.5, before the sequence is read (a sequence
  whose `block_events` raises when read).

X changes `TESTS.md`, then checks:

- [ ] `git grep -n "EXAMPLE_HARDWARE" -- src tests scripts docs/usage.md README.md`
      finds nothing.
- [ ] `git grep -n -E "pns_levels(_for)?\(seq\)" -- src tests scripts README.md docs/usage.md`
      finds nothing.

Task 2.2 and task 2.3 change different parts of `analyses.py`,
`tests/test_analyses.py`, `tests/test_pns_levels.py`, `TESTS.md` and
`docs/usage.md`. The second of the two to merge rebases (section 4.1).

### 6.11 Task 2.4: the bin size (wave 6)

Branch `feature/pns-bin-size`. One worker (H). Owns `pns_levels.py`,
`pns.py`, `analyses.py` (`_PnsSafeLevels`), `tests/test_pns_levels.py`,
`tests/test_pns.py`, `tests/test_analyses.py`, `TESTS.md` sections 2.2, 2.7
and 2.9, and `docs/usage.md` sections 3 and 6. Sections 5.6 and L8.

Tests:

- `bin_samples_for(n, 1e-5) == 615` for the default, as now.
- `bin_s=1e-3` at a raster of 10 us gives `bin_samples == 100`, and the
  level of each bin holds each total of its samples.
- `MAX_BINS` still limits the number of bins for a short `bin_s`.
- `pns_levels_for` keeps one result for each `bin_s`.
- `PNS_SAFE_LEVELS.compute(..., bin_s=...)` passes it on.
- A `bool`, a string, a NaN, an infinity, 0 and a negative `bin_s` raise
  before the sequence is read.

Checks of X:

- [ ] With `bin_s` not given, `pns_levels` gives the same bytes as on
      `origin/main` for the sequences of section 6.4 (the baseline script).

### 6.12 Task 2.5: consistent results (wave 7)

Branch `feature/consistent-results`. Section 5.8 and L9 to L14.

1. **F (M), first.** Owns `_equality.py`, `_validate.py` (new), the
   constants and `has_gradients` of `seq_index.py`, `tests/test_equality.py`,
   `tests/test_validate.py` (new), and `TESTS.md` sections 2.11 and 2.13
   (new, "Number arguments (`test_validate.py`)"). Tests of `FrozenDict`:
   each method that changes it raises `TypeError`; `pickle` and
   `copy.deepcopy` give an equal `FrozenDict`; `isinstance(d, dict)`;
   `json.dumps` writes it; `values_equal` of a `FrozenDict` and a `dict`
   with the same items is true (L9). Tests of `real` for each rule of L12.
2. Then three workers at the same time:
   - **Q (H).** Owns `seq_index.py` (equality), `grad_peaks.py`,
     `tests/test_seq_index.py`, `tests/test_grad_peaks.py`, and
     `docs/usage.md` sections 1 and 2. `SequenceIndex` and
     `BlockGradientValues` by value (L10). The `FrozenDict`s of
     `GradientPeaks` and `BlockGradientValues`. `GradientPeaks.reason` from
     L11. The `window` checked with `real`.
   - **N (H).** Owns `pns_levels.py`, `pns.py`, `grad_spectrum.py`,
     `tests/test_pns_levels.py`, `tests/test_pns.py`,
     `tests/test_grad_spectrum.py`, and `docs/usage.md` sections 3 and 7.
     The `FrozenDict`s of `PnsLevels` and `GradientSpectrum`. The constants
     of L11, `has_gradients`, `real` for the thresholds, `bin_s` and the
     spectrum arguments, and the zero peak (L13). A test: a sequence whose
     gradients all have the amplitude 0 gives `peak_time_s is None`.
   - **K (M).** Owns `series.py`, `analyses.py`, `tests/test_series.py`,
     `tests/test_analyses.py`, and `docs/usage.md` sections 5 and 6. `real`
     with `finite=False` in `Series`. The docstring of section 5.8. The
     registry check (L14), with a test that uses a fake entry point (as the
     registry tests do). `analyses.py` imports one `NO_GRADIENTS`.

X changes `TESTS.md` and the bullet "Equality" of `docs/usage.md`, then
checks:

- [ ] `git grep -n -E "\"no gradient events in" -- src tests` finds
      nothing.
- [ ] `git grep -n -E "def _number|def _real|def _has_gradients" -- src`
      finds nothing.

### 6.13 Task 2.6: the documents and the release (wave 8)

Branch `docs/release-0.1.0rc6`. Three workers at the same time:

- **L (H).** Owns `CHANGELOG.md`. The entry `0.1.0rc6 (<date>)`: "Fixed",
  "Changed" (with the tables of sections 5.4, 5.5, 5.6 and 5.7 and the
  changes of section 5.8) and "Removed".
- **D (M).** Owns `README.md`. The fifth line of the release history gets a
  sixth for `0.1.0rc6`. The install line names `v0.1.0rc6`. The example runs
  (D runs it with the example hardware).
- **U (H).** Owns `docs/usage.md` and `docs/reviews/2026-10-04-code-review.md`.
  A full read of `docs/usage.md` against the code, and the corrections. A
  new section at the end of the review, "Status at 0.1.0rc6": for each
  finding, the task and the PR that corrected it, or the reason that it
  stays (for example the measurement of task 1.6).

X changes `version` in `pyproject.toml` to `0.1.0rc6` and the comment at
line 39 (`calc_pns` in chunks, as `TODO.md` says), runs
`nix develop --command uv lock`, does the checks of section 7, and the tag
(L21).

## 7. Checks of the release

- [ ] `nix develop --command scripts/check` passes.
- [ ] The mutation check of section 6.1 still fails a test for each of M1 to
      M4 (with the names of `0.1.0rc6`).
- [ ] For `build_repeating(10)` of `tests/scale_sequences.py`, with the
      example hardware and `thresholds_hz_per_t=(GAMMA_1H,)`: each field of
      `pns_levels` on `0.1.0rc6` equals the field of `v0.1.0rc5`, after
      `dict(...)` of each `FrozenDict`. Run the `v0.1.0rc5` side in a
      worktree of the tag.
- [ ] `scripts/time_pns_levels.py` is not more than 10 % slower than on
      `v0.1.0rc5`.
- [ ] The PR description of task 2.6 gives the JSON of `to_obj` of each
      series of `pns.safe.levels` for the sequence above, with each `data`
      abbreviated. pulseq-checks uses it (section 8.1).
- [ ] CI passes on the PR.

## 8. Facts for the follow-up work

Each repository does this work on its own branch, after the tag
`v0.1.0rc6`, with its own plan. The line numbers are at the commits of
section 2, fact 3. The historical documents (released `CHANGELOG.md`
entries, `docs/plans/`, `docs/reviews/`) do not change.

### 8.1 pulseq-checks (`100c3bc`, pins `v0.1.0rc5`)

1. `pyproject.toml` line 13: `@v0.1.0rc6`. Then `uv lock`.
2. **The new names** (section 5.4).
   - `src/pulseq_checks/checks/gradient.py` lines 4, 5, 20, 81, 128, 132 and
     the annotations `measured: GradientLimits` (lines 192, 340, 495, 610).
   - `src/pulseq_checks/bindings.py` line 82: the key `"gradient.peaks"`.
   - The tests: `tests/test_bindings.py` lines 7, 39, 40, 60, 75, 78, 137
     and 182; `tests/test_check_gradient.py` lines 8, 9, 115 to 125, 349,
     357, 446 to 466 and 849; `tests/test_results.py` line 759;
     `tests/test_run.py` lines 819 to 824, 893, 897 and 1074.
   - The documents: `docs/checks.md` lines 89, 129 and 169;
     `docs/rasters.md` line 189; `docs/usage.md` lines 810, 1009, 1340,
     1530 and 1538; and the `TESTS.md` entries that name them.
   - `tests/test_check_gradient.py` line 346 makes an `AxisResult` by
     position. The fields of `AxisResult` do not change.
3. **`PNS_LIMIT`** goes away (section 5.7). `src/pulseq_checks/bindings.py`
   lines 19 and 66 become `abs(gamma)` (the limit of a fraction is 1).
   The tests `tests/test_bindings.py` lines 8, 91 and 108,
   `tests/test_check_pns.py` lines 9 and 97, `tests/test_run.py` lines 10
   and 803, and `docs/usage.md` lines 851 to 865, 1350 and 1354.
4. **The hardware** (section 5.5, U8). The binding gives `hardware=` already
   (`bindings.py` lines 73 to 77). `tests/test_safe_model.py` line 118 calls
   `pns_levels(seq)` with no hardware: it gives
   `hardware=(safe_example_hw(), <label>)`. The `meta` of the series
   `pns_total` has no key `asc_file` any more, and `PnsLevels` has no field
   `asc_file`: the JSON example of `docs/usage.md` (lines 1009 to 1057)
   changes with it.
5. **The bin size** (section 5.6). The default does not change, so
   `docs/usage.md` lines 1049, 1055 and 1132 (615 samples, 6.15 ms) stay
   true. The binding can give `bin_s`.
6. **The reasons** (L11). `checks/acoustic.py` line 10 and
   `checks/pns.py` line 12 import `NO_GRADIENTS` from `grad_spectrum` and
   `pns_levels`. These names stay, and are the same object. No code reads
   the text of `GradientLimits.reason`.
7. **The equality and the dicts** (L9, L10). `tests/test_check_pns.py`
   line 368 makes a `PnsLevels` with `replace(..., above={...})`, a plain
   dict. L9 keeps it equal to a `FrozenDict` with the same items.
   `tests/test_safe_model.py` lines 13 to 23 compare with `==`. No code
   writes into a result.
8. **The registry.** `tests/test_run.py` lines 1072 to 1078 give the set of
   the installed IDs: `"gradient.peaks"` in place of `"gradient.limits"`.
   The entry point names of pulseq-analysis are their IDs, so L14 does not
   affect pulseq-checks.
9. **The thresholds.** No code relies on `ValueError` for a threshold of a
   wrong type (L12).
10. The JSON of the series of section 7 is the new example of
    `docs/usage.md` lines 1009 to 1057.

### 8.2 pulseq-reports (`2a516b4`, pins `v0.1.0rc2`)

pulseq-reports pins `pulseq-analysis` `v0.1.0rc2` and `pulseq-checks`
`v0.1.0rc3` (`pyproject.toml` lines 13 and 14). Its move to `v0.1.0rc6` also
includes the changes of `0.1.0rc3` to `0.1.0rc5` (for example the units of
`docs/plans/gamma-free-units.md` section 8.2, and `seq_utils.GAMMA`, which
is gone). It must move to a pulseq-checks release that pins `v0.1.0rc6` at
the same time.

1. **The report helpers come here** (U6, section 5.7).
   - `peak_tr_window`: `src/pulseq_reports/cards/pns.py` lines 13, 50 and 52,
     and `tests/test_pns_card.py` lines 139 and 154. Copy the function of
     `pulseq_analysis/pns.py` at `v0.1.0rc5` (lines 145 to 160).
   - `pns_prediction`: `cards/pns.py` lines 35 and 144 read the summary.
     Use `pns_levels_for(seq, hardware=hardware_from_asc(...))` and its fields
     `peak_hz_per_t`, `peak_time_s` and `axis_peaks_hz_per_t`. The
     monkeypatch targets of `tests/conftest.py` lines 79, 88 and 89 and the
     tests of `tests/test_pns_card.py` change with it.
   - `hold_samples`: `cards/rf_profile.py` lines 24 and 173,
     `rf_exposure.py` lines 24 and 75, `rf_profiles.py` lines 28 and 919,
     `tests/oracles/rf_exposure.py` lines 18 and 50, and
     `tests/test_rf_profile_card.py` lines 19 and 115. Copy the function of
     `pulseq_analysis/seq_utils.py` at `v0.1.0rc5` (lines 18 to 35), with
     `TIME_TOLERANCE`.
2. **The new names** (section 5.4). `cards/gradient_limits.py` lines 11,
   68, 152, 171 and 181, and `tests/test_gradient_limits_card.py` lines 6,
   201, 246 and 313. The names of the card itself (`gradient_limits_card`,
   the card ID `gradient-limits`) belong to pulseq-reports and need not
   change.
3. **The reasons** (L11). `cards/gradient_limits.py` line 156 writes
   `GradientLimits.reason` into the HTML, and
   `tests/test_gradient_limits_card.py` line 238 expects
   "no gradient events in the sequence.". The new text is "no gradients."
4. **The hardware** (section 5.5, U8). `cards/diagram.py` line 104 and the
   PNS card give `gradient_asc=`, which goes away: they give
   `hardware=hardware_from_asc(gradient_asc)`. `tests/test_diagram_card.py`
   line 243 and `tests/test_pns_card.py` change the same way.
   `tests/test_pns_lanes_golden.py` line 165 calls `pns_levels(seq)` with no
   hardware: it gives `hardware=(safe_example_hw(), <label>)`.
   `cards/diagram.py` line 57 says "example" when `asc_file is None`:
   `PnsLevels.asc_file` goes away, so the card keeps this fact itself (it
   knows whether it was given a file).
5. **The bin size** (section 5.6). `assets/pns_lanes.js` line 56
   (`EXACT_MAX_S = 10.0`) and `assets/lane_chart.js` lines 13 and 14 (a
   plot of 812 columns) are the geometry that the default `BIN_S` comes
   from. The default does not change, so the pyramid of `pns_lanes.js` and
   the tests (`tests/js/test_pns_lanes.js` lines 953 and 954, 6.15 ms) stay
   true. pulseq-reports can now give `bin_s` from its own geometry.
6. **The dicts** (L9). `cards/diagram.py` line 59 puts `levels.hw` into
   JSON. A `FrozenDict` is a `dict`, so `json.dumps` writes it.

## 9. Later

- **The parameters of an analysis.** `AnalysisSpec.params` gives only the
  names. A runner cannot know a type or a default. Not in the scope of U1.
- **A block replaced in place** is still not seen by the kept results (L3).
  pypulseq has no counter of changes. Do it only if a user needs it.
- **One PNS result for all the gammas of one hardware** (section 9 of
  `docs/plans/gamma-free-units.md`).
