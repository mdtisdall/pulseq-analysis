# Implementation plan: pulseq-analysis, phases 0, 1 and 3

Mode: Strict STE100. Structural rules are enforced. Lexical rules are a
direction of travel, not a verified dictionary match.

Status: draft, not approved. Written on 2026-10-01.

## 1. Scope

The design is `docs/plans/pulseq-analysis.md` of pulseq-checks, at commit
`e46f0bf` (PR #39 of that repository). In this plan, "the design" is that
file, and "design 4.4" is its section 4.4. This plan does not change a
decision of design section 6.

This plan gives the work in this repository:

| Phase | Branch | Result |
|---|---|---|
| 0 | `chore/python-scaffolding` | The rest of design task 1.1 (section 5). |
| 1 | `feature/initial-move` | Design tasks 1.2 and 1.3: the move, the usage document, tag `v0.1.0rc1` (section 6). |
| 1T | `chore/time-pns-levels` | The time script of decision D3, and the baseline time (section 7). |
| 3 | `feature/series-and-analyses` | Design phase 3: `Series`, `Analysis`, the thresholds, tag `v0.1.0rc2` (section 8). |

Design phases 2 and 4 are in pulseq-checks, with their own implementation
plan in that repository. Section 10 lists the facts of this plan that the
plan of phase 2 must use.

### 1.1 Order

```
PR #1 (merged)  ->  Phase 0  ->  Phase 1  ->  tag v0.1.0rc1
                                    |
                                    +->  Phase 1T (after phase 1 merges)
                                    +->  pulseq-checks phase 2 (pins v0.1.0rc1)
Phase 1T merged  ->  Phase 3  ->  tag v0.1.0rc2  ->  pulseq-checks phase 4
```

- Phase 1T needs the moved modules. It must merge before phase 3 starts,
  because task 3.2 compares with its baseline.
- Phase 3 does not need pulseq-checks phase 2. Phase 2 pins `v0.1.0rc1`, so
  the interface changes of phase 3 (`above`, no `limits`) do not break it.
  Phase 2 and phase 3 can run at the same time.

## 2. Context (verified on 2026-10-01)

pulseq-checks `origin/main` is at `e46f0bf`. This repository's `main` is at
`7ee2456`.

1. **The skeleton is in place (PR #1).** `flake.nix` (Python 3.12, uv, gh,
   git, jq, shellcheck, and a `ci` shell), `.envrc`, `.gitignore`, the hook,
   `.claude/settings.json`, `.claude/gh-token-permissions`, CI
   (`.github/workflows/check.yml`, a copy of the pulseq-checks file),
   `CLAUDE.md`, and `scripts/check` (uv sync, ruff, pytest, shellcheck).
   `pyproject.toml` has version `0.1.0`, no dependencies and no fork pin.
   `src/pulseq_analysis/__init__.py` has a docstring only.
   `tests/test_import.py` is a placeholder test.
2. **The source files of the move.** In `src/pulseq_checks/` at `e46f0bf`:
   `asc.py` (50 lines), `extensions.py` (36), `grad_limits.py` (758),
   `pns.py` (138), `pns_levels.py` (552), `sampling.py` (279),
   `seq_index.py` (194), `seq_utils.py` (56). They import each other with
   relative imports (`from .seq_index import ...`). Thus their import lines
   do not change in the move.
3. **The tests of the move.** `tests/test_seq_utils.py`, `test_pns_levels.py`,
   `test_extensions.py`, `test_seq_index.py`, `test_sampling.py`,
   `test_grad_limits.py` and `test_pns.py` (3069 lines). They import
   `pulseq_checks` with absolute imports. `test_pns_levels.py` also names
   `pulseq_checks.pns_levels` in five `monkeypatch.setattr` strings.
4. **The test helpers.** The moved tests use these files, and no other file
   of `tests/`:
   - `tests/synthetic.py` (170 lines). The moved tests use each of its
     functions. It imports `GAMMA` from `pulseq_checks.seq_utils`.
   - `tests/scale_sequences.py` (154 lines). `test_seq_index.py` and
     `test_grad_limits.py` import `build_repeating` and `build_worst`. The
     design (fact 9) does not name this file.
   - `tests/oracles/blocks.py` and `tests/oracles/grad_limits.py` (no
     `__init__.py`). The oracle imports `pulseq_checks.seq_utils`.
   - `tests/conftest.py` (87 lines): the option `--collected-tests-file` (for
     the TESTS.md check) and the fixture `write_gradient_asc` (used by
     `test_pns.py` and `test_pns_levels.py`).
5. **`SAFE_FIELDS` has a user in the moved code.** `pns.py` imports
   `SAFE_FIELDS` from `pns_levels.py` for `_hardware_key`, the key of the
   kept results. Design 4.1 moves `SAFE_FIELDS` to `safe_model.py` of
   pulseq-checks. Decision D1 corrects this.
6. **The check-layer part of `pns_levels.py`.** Lines 483 to 552: the
   comment "The SAFE model of the target profile", `SAFE_FIELDS`, `_real`,
   `_SafeModel`, `SAFE_MODEL` and `hw_from_dict`. After their removal, the
   import of `Mapping` has no user. Five tests of `test_pns_levels.py` and
   their helper `_safe_dict` test this part (lines 493 to 585).
7. **`scipy`.** Only `tests/test_sampling.py` imports `scipy`. No module of
   the move imports it. pypulseq depends on it.
8. **`TESTS.md` of pulseq-checks.** Sections 2.1 to 2.7 describe the seven
   moved test files, in this order: 2.1 `test_seq_utils.py`, 2.2
   `test_pns_levels.py`, 2.3 `test_extensions.py`, 2.4 `test_seq_index.py`,
   2.5 `test_sampling.py`, 2.6 `test_grad_limits.py`, 2.7 `test_pns.py`.
   Section 1 describes the static checks. Section 2.0 describes
   `test_package.py`. `scripts/check_tests_md.py` (175 lines) checks that
   each test has one entry.
9. **The fork pin.** `[tool.uv.sources]` of pulseq-checks pins pypulseq from
   `https://github.com/mdtisdall/pypulseq`, rev
   `a74ab06e51ca09707ff54837cf5ff652f6e69e94` (tag `pulseq-reports-pin-1`).
   The `TODO.md` item "Move from the pypulseq fork to a pypulseq release"
   names two repositories.
10. **The workers.** `.claude/agents/worker-medium.md` and `worker-high.md`
    of pulseq-checks are the agents of the tiers M and H. Their text names
    "pulseq-checks" one time each.
11. **The time budget sequence.** `scripts/budget.py` of pulseq-checks
    builds `build_repeating(blocks // TR_BLOCKS)` of `tests/scale_sequences.py`
    with about 10⁶ blocks. pulseq-analysis has no time script.
12. **The array encoding of pulseq-reports.** `encode_tables` in
    `src/pulseq_reports/diagram_data.py` (pulseq-reports `a322517`) writes
    each array as `{"dtype": arr.dtype.name, "length": arr.size, "data":
    base64(gzip(little-endian bytes))}`, with `compresslevel=6`, `mtime=0`,
    and byte 9 of the gzip header set to `0xff`. On Python 3.12 with
    `mtime=0`, zlib writes the header, and its OS byte depends on the
    platform. Thus the code sets byte 9 itself.
13. **The `cost` values of pulseq-checks.** The gradient checks are "fast".
    `pns.safe` is "slow".

## 3. Decisions

### 3.1 Decisions of the user (approved on 2026-10-01)

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| D1 | Where `SAFE_FIELDS` goes | It stays in `pulseq_analysis.pns_levels`. It is the field list of the SAFE hardware struct of pypulseq, not of the target profile. `safe_model.py` of pulseq-checks imports it. Only `_real`, `_SafeModel`, `SAFE_MODEL` and `hw_from_dict` leave `pns_levels.py`. | A private copy of the field list in `pns.py`. |
| D2 | The branch of the rest of design task 1.1 | A separate branch, `chore/python-scaffolding`, before `feature/initial-move`. Then the diff of the move is a move only. | All of phase 1 in `feature/initial-move`. |
| D3 | The time measurement of task 3.2 | A tracked script, `scripts/time_pns_levels.py`, on its own branch after phase 1. It measures the baseline on `v0.1.0rc1` code. Task 3.2 runs it again. | A script in the scratchpad. |
| D4 | PR #1 before this plan | PR #1 merged first. This plan starts from its merge commit. | — |

### 3.2 Decisions of this plan

These decisions follow from the code. The approval of this plan approves
them.

| # | Decision | Reason |
|---|---|---|
| L1 | `tests/scale_sequences.py` moves with the tests. | Fact 4. Two moved test files import it. |
| L2 | `tests/synthetic.py`, `tests/conftest.py` and `tests/oracles/` move whole. | Fact 4. The moved tests use each function and fixture. |
| L3 | The runtime dependencies are `pypulseq>=1.5.0.post1` and `numpy`. `scipy` goes in the `dev` group. | Fact 7. |
| L4 | The new `TESTS.md` keeps the numbers 2.1 to 2.7 and their titles. Phase 3 adds 2.8 (`test_series.py`) and 2.9 (`test_analyses.py`). | A reader can compare the two files section by section. |
| L5 | `PNS_LIMIT` stays in `pns_levels.py`. Its comment names the SAFE stimulation threshold, not `pns.safe`. In phase 3, the default of `thresholds` is `(PNS_LIMIT,)`. | It is a fact of the SAFE model (1 is 100 %). Design 4.5 and 4.7 use `PNS_LIMIT`. |
| L6 | The four analysis objects of design 4.3 are in `analyses.py`, with `AnalysisSpec`, `Analysis` and the registry. | Design 4.1 lists only `series` and `analyses` as new modules. |
| L7 | In phase 3, `tests/oracles/grad_limits.py` does not change. It keeps its own `HardwareLimits` and `limits`. The tests take their tolerance scale from the oracle result. | The oracle is an independent reference. It does not have to follow the interface. |
| L8 | Phase 0 sets the version `0.1.0.dev0`. Task 1.3 sets `0.1.0rc1`, and task 3.4 sets `0.1.0rc2`. | PEP 440: `0.1.0.dev0 < 0.1.0rc1`. The version `0.1.0` of PR #1 is above both release candidates. |
| L9 | A tag is an annotated tag on the merge commit of its release PR. The executing agent shows the command, and pushes the tag only after the user approves. | A pushed tag is permanent for the users of the git URL. |
| L10 | Each moved file keeps the docstrings that name pulseq-reports or "the plan" (an old plan of pulseq-reports). | The design's move rule changes only the text that names pulseq-checks, its checks or its plans. |

## 4. How to execute this plan

The workflow is that of design section 7, with the worker tiers of
`docs/plans/pulseq-checks-v1.md` section 3.2 of pulseq-checks:

1. Start each branch with the `dev-workflow:start-task` skill, from the
   latest `origin/main`. Then run `nix develop --command uv sync --frozen`
   one time in the worktree, before a worker starts.
2. Each test that a task adds, moves or changes gets its `TESTS.md` entry in
   the same PR.
3. Run `nix develop --command scripts/check` before each PR.
4. Show the commit message to the user, and wait for approval before
   `git commit`. Merge only when the user tells you to.
5. The executing agent reviews each worker's diff line by line.
6. When a task finds that this plan or the design is wrong, stop and ask the
   user.

Tiers:

| Tier | Agent | Use it for |
|---|---|---|
| M | `worker-medium` | A copy, a move or a removal with an exact file list, or code that this plan gives exactly. |
| H | `worker-high` | A public interface with local decisions, its tests, or a long document. |
| X | The executing agent | The move comparison, the measurements, the tags, the questions to the user, and the review. |

Give each worker: the task, the worktree, this plan and the sections of the
task, the files that it owns, the files that it may read, and the checks to
run. Workers put scratch files in the session scratchpad.

### 4.1 The move rule (phase 1)

A moved file is equal to its source at pulseq-checks `e46f0bf`, with only
these changes:

1. `pulseq_checks` becomes `pulseq_analysis`.
2. The changes that section 6.2 lists for that file.

The executing agent verifies each moved file:

```bash
diff <(git -C /Users/dylan/dev/pulseq-checks show e46f0bf:<source path> | sed 's/pulseq_checks/pulseq_analysis/g') <destination path>
```

The output must show only the changes of section 6.2. Put the output of each
file in the PR description.

## 5. Phase 0: the scaffolding

Branch: `chore/python-scaffolding`. One task, tier M. Files:

| File | Change |
|---|---|
| `pyproject.toml` | Version `0.1.0.dev0`. Description "Derived values of a Pulseq sequence: waveforms, PNS and gradient summaries". `license = "MIT"`, `license-files = ["LICENSE"]`. Dependencies of L3. `[tool.uv.sources]` with the pin of fact 9 and the comment of pulseq-checks, with "pulseq-checks" changed to "pulseq-analysis". Keep `[tool.ruff]` of PR #1 (line length 100, `.worktrees` excluded). |
| `uv.lock` | `nix develop --command uv lock`. |
| `LICENSE` | A copy of the pulseq-checks file (MIT, 2026, Matthew Dylan Tisdall). |
| `README.md` | What the package is (design 1, item 1), the install line with the git URL (no tag yet), the fork note of the pulseq-checks README, and a link to `docs/usage.md` (phase 1). |
| `CHANGELOG.md` | The header of the pulseq-checks file, with the package name changed. No version entry yet. |
| `TODO.md` | The fork item of pulseq-checks, with the three repositories named (T12). |
| `scripts/check_tests_md.py` | A copy, with no change. |
| `scripts/check` | The steps of the pulseq-checks file, without the `docs/checks.md` step: uv sync, ruff, pytest with `--collected-tests-file`, the TESTS.md check, shellcheck. |
| `tests/conftest.py` | Lines 1 and 3 to 22 of the pulseq-checks file (the option and its hook), with no change. Line 2 (the import of `safe_example_hw`) comes in phase 1 with the fixture. |
| `tests/test_package.py` | A copy, with `pulseq_checks` changed to `pulseq_analysis` and `pulseq-checks` changed to `pulseq-analysis`. |
| `tests/test_import.py` | Delete. `test_package.py` replaces it. |
| `TESTS.md` | The introduction, section 1 (without "Check documents") and section 2.0, from the pulseq-checks file. Change the names. Remove the "Terms" paragraph until phase 1. |
| `.claude/agents/worker-medium.md`, `worker-high.md` | Copies, with "pulseq-checks" changed to "pulseq-analysis". |

Checks:

- [ ] `scripts/check` passes.
- [ ] `diff` of `scripts/check_tests_md.py` with the pulseq-checks file is empty.
- [ ] CI passes on the PR.

## 6. Phase 1: the move

Branch: `feature/initial-move`. Start after phase 0 merges.

### 6.1 Task 1.2: move the modules and tests (tier M)

Copy each file of this table from pulseq-checks `e46f0bf`. Then apply the
changes of section 6.2.

| Source (pulseq-checks) | Destination |
|---|---|
| `src/pulseq_checks/asc.py` | `src/pulseq_analysis/asc.py` |
| `src/pulseq_checks/extensions.py` | `src/pulseq_analysis/extensions.py` |
| `src/pulseq_checks/grad_limits.py` | `src/pulseq_analysis/grad_limits.py` |
| `src/pulseq_checks/pns.py` | `src/pulseq_analysis/pns.py` |
| `src/pulseq_checks/pns_levels.py` | `src/pulseq_analysis/pns_levels.py` |
| `src/pulseq_checks/sampling.py` | `src/pulseq_analysis/sampling.py` |
| `src/pulseq_checks/seq_index.py` | `src/pulseq_analysis/seq_index.py` |
| `src/pulseq_checks/seq_utils.py` | `src/pulseq_analysis/seq_utils.py` |
| `tests/test_seq_utils.py`, `test_pns_levels.py`, `test_extensions.py`, `test_seq_index.py`, `test_sampling.py`, `test_grad_limits.py`, `test_pns.py` | the same names in `tests/` |
| `tests/synthetic.py`, `tests/scale_sequences.py` | the same names in `tests/` |
| `tests/oracles/blocks.py`, `tests/oracles/grad_limits.py` | the same names in `tests/oracles/` |
| `tests/conftest.py` | `tests/conftest.py` (the whole file: phase 0 has lines 1 and 3 to 22) |

Do not copy `src/pulseq_checks/__init__.py`. Keep the `__init__.py` of
PR #1.

### 6.2 The changes of each moved file

Line numbers are at `e46f0bf`. Find the text by its content.

| File | Changes other than `pulseq_checks` to `pulseq_analysis` |
|---|---|
| `asc.py`, `extensions.py`, `sampling.py`, `seq_index.py`, `grad_limits.py` | None. `HardwareLimits` stays until phase 3. |
| `seq_utils.py` | Docstring, lines 6 to 8: remove "No check of this package uses it yet:" and "and for a later RF check". Keep that it is for a caller that measures or draws the RF. Line 15: remove "A check uses the gamma of its target." |
| `pns.py` | Docstring of `pns_prediction`, lines 110 and 111: remove the sentence "The checks of this package do not use this function: ...". |
| `pns_levels.py` | (a) Module docstring, lines 6 and 7: remove "The checks of this package use the summary and the intervals, not the level." (b) Lines 20 to 22: remove the paragraph on `SAFE_MODEL` and `hw_from_dict`. (c) Lines 62 to 64, the comment of `PNS_LIMIT` (L5): "The stimulation threshold of the SAFE model: a total of 1 is 100 %. An interval of `PnsLevels.above_limit` is a run of samples with `total >= PNS_LIMIT`." (d) Lines 483 to 552: remove the section comment, `_real`, `_SafeModel`, `SAFE_MODEL` and `hw_from_dict`. Keep `SAFE_FIELDS` and its comment, with no change (D1). (e) Remove the import of `Mapping` (fact 6). |
| `test_pns_levels.py` | Remove `SAFE_MODEL`, `SAFE_FIELDS` and `hw_from_dict` from the import. Remove `_safe_dict` and the five tests `test_safe_model_reads_a_valid_dict`, `test_safe_model_refuses_an_unknown_key`, `test_safe_model_refuses_a_missing_field_or_axis`, `test_safe_model_refuses_a_value_that_is_not_a_real_number` and `test_hw_from_dict_gives_the_example_hardware`. Remove the imports that then have no user. |
| `synthetic.py`, `oracles/grad_limits.py`, the other six test files | None. |
| `scale_sequences.py`, `oracles/blocks.py`, `conftest.py` | None. |

`TESTS.md`: add sections 2.1 to 2.7 of the pulseq-checks file after
section 2.0, with these changes:

- Remove the entries of the five removed tests from section 2.2.
- Change `pulseq_checks` to `pulseq_analysis`.
- Change each text that names a check or the target profile of
  pulseq-checks. List each changed sentence in the PR description.
- Add the "Terms" paragraph (synthetic sequences) to the introduction, and
  the item of the analyses to the contents list.

Checks of task 1.2:

- [ ] The move rule (section 4.1) for each file of section 6.1.
- [ ] `grep -rn 'pulseq_checks\|pulseq-checks' src tests` finds nothing.
- [ ] Each moved test passes. The number of tests is the number in
      pulseq-checks for the seven files, minus five.

### 6.3 Task 1.3: the usage document and the release (tier M)

After task 1.2. Files:

- `docs/usage.md` (new): section 8 of the `docs/usage.md` of pulseq-checks,
  as the whole document. Title "Using pulseq-analysis". Change:
  - each `pulseq_checks.` to `pulseq_analysis.`.
  - remove the text on checks, the run function and the target profile.
    These sentences start with:
    - "In a check, the run function turns the exception ..."
    - "A check that uses them lists both in `CheckSpec.rasters` ..."
    - "which a check must not do ..." (with its link)
    - "A check uses the gamma of its target ..."
    - "A check makes the struct from its target ..."
    - "A check must not use it."
    - "No check uses it yet."
  - remove the paragraph on `SAFE_MODEL` and `hw_from_dict`, and the plugin
    example of section 8.3. Keep `SAFE_FIELDS`. Add one sentence: pulseq-checks
    makes the hardware argument from a target profile (its `docs/usage.md`).
  - renumber the sections 8.1 to 8.4 as 1 to 4, and correct each link.
- `README.md`: the install line with `@v0.1.0rc1`, and one example: the PNS
  peak of a `.seq` file with `pns.pns_prediction`.
- `CHANGELOG.md`: the entry `0.1.0rc1`: the modules moved from pulseq-checks
  `0.1.0rc2`, the two removals (`SAFE_MODEL`, `hw_from_dict`), and the date.
- `pyproject.toml`: version `0.1.0rc1` (L8). Then `uv lock`.

After the merge, the executing agent tags `v0.1.0rc1` (L9):

```bash
git -C /Users/dylan/dev/pulseq-analysis tag -a v0.1.0rc1 -m "pulseq-analysis 0.1.0rc1" origin/main
```

Checks of phase 1:

- [ ] `scripts/check` passes.
- [ ] Each moved test passes with no change other than those of section 6.2.

## 7. Phase 1T: the time script

Branch: `chore/time-pns-levels`. Start after phase 1 merges. One task,
tier M, then a measurement, tier X.

`scripts/time_pns_levels.py` (new). The form of `scripts/budget.py` of
pulseq-checks, made smaller:

- It adds `tests/` to `sys.path` and builds
  `build_repeating(blocks // TR_BLOCKS)`. The default is `--blocks 1000000`.
- It times `pns_levels.pns_levels(seq)` (the example hardware), `--repeat`
  times (default 3), in one process, and gives the minimum and each time.
  The build is timed and printed, but it is not part of the result.
- It prints the machine, the Python, numpy and pypulseq versions, the
  version of the package and the git commit. `--json OUT` writes the same
  values as JSON.
- Phase 3 adds `--thresholds` (task 3.2). This phase has no such option.

No test and no `TESTS.md` entry: the script is not a check. ruff checks it.

The executing agent then runs the script on the merge commit of phase 1,
with `--blocks 1000000 --repeat 3`. Record the result in section 9 of this
plan, in the same PR.

## 8. Phase 3: series and analyses

Branch: `feature/series-and-analyses`. Start after phase 1T merges. Tasks
3.1 and 3.2 share no file, except their own `TESTS.md` sections. They can
run at the same time. Task 3.3 comes after both.

### 8.1 Task 3.1: `series.py` (tier H)

Files: `src/pulseq_analysis/series.py` (new), `tests/test_series.py` (new),
`TESTS.md` section 2.8 (new).

`SeriesKind`, `Series`, `encode_array` and `decode_array` as design 4.2.
Local rules:

- `encode_array(a)` gives `{"dtype", "length", "data"}` with the bytes of
  fact 12, byte for byte: `a.astype(a.dtype.newbyteorder("<"), copy=False)`,
  `gzip.compress(..., compresslevel=6, mtime=0)`, byte 9 set to `0xff`, and
  base64. `decode_array(d)` raises `ValueError` when `"length"` does not
  agree with the decoded byte count.
- `Series.to_obj()` gives `{"name", "kind", "unit", "t0_s", "step_s",
  "end_s", "meta", "arrays"}`. `"arrays"` maps each name to
  `encode_array`, in the order of `arrays`. A float field or a `meta` value
  that is not finite is written as `"inf"`, `"-inf"` or `"nan"` (design 4.2).
  `Series.from_obj(obj)` is the inverse, and raises `ValueError` for an
  unknown key or kind.
- `__post_init__` copies `arrays` and `meta` into new dicts, so that a change
  to the caller's dict does not change the series.

Tests (design task 3.1):

- each refusal of `__post_init__`.
- `__eq__` with NaN, with another dtype and with another length.
- the round trip of `to_obj` and `from_obj` for each kind, with an array of
  2 × 10⁶ float32 values and with values that are not finite.
- the same text for one array two times.
- `encode_array` of a small float32 array gives a fixed expected text. The
  executing agent makes that text one time with `encode_tables` of
  pulseq-reports `a322517`. The test docstring names the commit.

### 8.2 Task 3.2: thresholds (tier H, then tier X)

Files: `src/pulseq_analysis/pns_levels.py`, `src/pulseq_analysis/pns.py`,
`tests/test_pns_levels.py`, `tests/test_pns.py`, `scripts/time_pns_levels.py`,
`TESTS.md` sections 2.2 and 2.7.

As design 4.4, with these local rules:

- `pns_levels(seq, *, gradient_asc=None, hardware=None,
  thresholds=(PNS_LIMIT,))`. `thresholds` is a tuple of finite floats above
  0, with no two equal. Else `ValueError`, before any work.
- `_IntervalFinder(dt, threshold)`: one finder for each threshold. Each
  chunk goes to each finder. The total of a chunk is calculated one time.
- `PnsLevels.above: dict[float, tuple[PnsInterval, ...]]`, with one key for
  each threshold, in the order of `thresholds`. `above_limit` is removed.
  With `NO_GRADIENTS`, each threshold has `()`.
- `pns_levels_for` gets the same argument. The key of a kept result is the
  pair (hardware key, `tuple(thresholds)`).
- `pns_prediction` does not change. It uses the default.
- The comment of `PNS_LIMIT` names `above[PNS_LIMIT]`.

Tests: each test of `above_limit` uses `above[1.0]`, with no other change.
New tests:

- two thresholds in one call give the same runs as two calls with one
  threshold each.
- each refusal of `thresholds`.
- `pns_levels_for` with other thresholds does not give the kept result of
  the default.

`scripts/time_pns_levels.py`: the option `--thresholds T [T ...]` (default:
no argument, the default of `pns_levels`).

Measurement (tier X): run the script on the branch with no `--thresholds`,
and with `--thresholds 1.0 0.9 0.8`. Compare the first with the baseline of
section 9, on the same machine. When it is more than 5 % slower, stop and ask
the user. Record both results in section 9.

### 8.3 Task 3.3: `analyses.py` and `grad_limits.py` (tier H)

After tasks 3.1 and 3.2. Files: `src/pulseq_analysis/analyses.py` (new),
`src/pulseq_analysis/grad_limits.py`, `pyproject.toml` (the entry points
only), `uv.lock`, `tests/test_analyses.py` (new), `tests/test_grad_limits.py`,
`TESTS.md` sections 2.6 and 2.9 (new).

`analyses.py`, as design 4.3:

- `AnalysisSpec`, `Analysis`, `GROUP = "pulseq_analysis.analyses"`,
  `RegistryError(Exception)` and `registry() -> dict[str, Analysis]`. The
  registry follows `registry.check_rules` and `_add` of pulseq-checks: an
  entry point that cannot load, and two analyses with one ID, raise
  `RegistryError` with the names of the packages.
- The four analyses (L6), with these specification values:

  | ID | `params` | `rasters` | `cost` |
  |---|---|---|---|
  | `seq.index` | `()` | `()` | `"fast"` |
  | `gradient.limits` | `("gamma",)` | `("GradientRasterTime", "BlockDurationRaster")` | `"fast"` |
  | `gradient.blocks` | `("gamma",)` | `("GradientRasterTime", "BlockDurationRaster")` | `"fast"` |
  | `pns.safe.levels` | `("hardware", "thresholds")` | `("GradientRasterTime", "BlockDurationRaster")` | `"slow"` |

  Each `version` is 1. The `description` of each states the contract of its
  value, from `docs/usage.md`.
- `to_series` of `pns.safe.levels` as design 4.4. The other three give `()`.
- `pyproject.toml`: `[project.entry-points."pulseq_analysis.analyses"]`, one
  line for each analysis. Then `uv lock` and `uv sync`, so that the entry
  points are installed.

`grad_limits.py` (T4): remove `HardwareLimits`, `_default_limits`, the
`limits` argument of `gradient_limits` and the field
`GradientLimits.limits`. Change the docstrings that name them.

`tests/test_grad_limits.py` (L7):

- Remove the two `result.limits` assertions of the gamma test (lines 86
  and 87 at `e46f0bf`).
- Remove `test_default_limits_come_from_seq_system`.
- `_assert_matches_oracle`: take `grad_scale` and `slew_scale` from
  `theirs.limits`, not `ours.limits`. Do the same for
  `ours_window.limits` (line 752).
- `_assert_block_values_agree_with_gradient_limits`: call
  `gradient_limits(seq, gamma=gamma)`.
- Remove `HardwareLimits` from the import.

`tests/test_analyses.py`:

- the registry has the four IDs.
- two analyses with one ID raise `RegistryError` (with a monkeypatched
  `importlib.metadata.entry_points`).
- an entry point that cannot load raises `RegistryError`.
- the series of `pns.safe.levels` are equal to `level_min`, `level_max` and
  `above[1.0]` of the same call, with the `meta` of design 4.4.
- `to_series` gives `()` for a sequence without gradients.
- `compute` of each analysis gives the value of its function.

### 8.4 Task 3.4: documents and the release (tier M)

After task 3.3. Files: `docs/usage.md` (a section on `Series`, the encoding
and the `Analysis` protocol and registry, and the changes of `pns_levels`
and `grad_limits`), `README.md` (the tag), `CHANGELOG.md` (the entry
`0.1.0rc2`, with "Changed": `above_limit` replaced by `above`, and no
`limits` in `grad_limits`), `pyproject.toml` (version `0.1.0rc2`), and
`uv.lock`.

After the merge, the executing agent tags `v0.1.0rc2` (L9).

Checks of phase 3:

- [ ] `scripts/check` passes.
- [ ] The time of task 3.2 is in section 9, and is not more than 5 % above
      the baseline.

## 9. Measurements

None yet. Phase 1T records the baseline. Task 3.2 records the time with one
and with three thresholds.

## 10. Facts for the plan of pulseq-checks phase 2

1. `safe_model.py` imports `SAFE_FIELDS` from `pulseq_analysis.pns_levels`
   (D1). It does not define it.
2. `tests/synthetic.py` and `tests/scale_sequences.py` stay in pulseq-checks:
   `test_check_*.py`, `test_cli.py`, `test_run.py`, `test_budget.py` and
   `scripts/budget.py` use them. `synthetic.py` imports `GAMMA` from
   `pulseq_analysis.seq_utils`.
3. `tests/oracles/` has no user in pulseq-checks after the move. Delete it.
4. `tests/conftest.py` stays whole in pulseq-checks: `test_asc_profile.py`
   and `test_check_pns.py` use `write_gradient_asc`.
5. The five tests of `SAFE_MODEL` and `hw_from_dict` (section 6.2) move to a
   new `tests/test_safe_model.py`, with their `TESTS.md` entries.
6. `PNS_LIMIT` and `PnsInterval` stay in `pulseq_analysis.pns_levels`.
   `checks/pns.py` imports them from there.
