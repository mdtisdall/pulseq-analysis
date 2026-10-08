# Implementation plan: `load` accepts a sequence with no `[SIGNATURE]` hash

Status: approved by the user on 2026-10-07. Written on 2026-10-07. Revised on 2026-10-07:
the user chose to remove `extensions.refuse_unsigned` too, and the findings
of a review of the first draft are in. Revised again on 2026-10-07: the user
answered U1 to U3. This plan makes no release: more changes come before
`0.1.0rc7`. Section 3.1 records the answers.

## 1. Scope

pulseq-checks asked on 2026-10-07 that `snapshot.load` stop refusing a
sequence with no `[SIGNATURE]` hash. The refusal came from decision U8 of
`docs/plans/second-review-fixes.md` ("the second plan"). This plan reverses
U8. The second plan is not changed: it is the record of that decision.

The reasons:

- No code of the package uses the hash. The kept results are on the snapshot
  object, not keyed by the hash (D21 of the second plan, and the snapshot of
  #80). No result, `Series` or `meta` holds the hash. The refusal is only a
  policy check.
- The refusal blocks callers that need unsigned sequences. pulseq-checks and
  pulseq-reports run sequences that were built in memory and never written,
  and a file can have no `[SIGNATURE]` section.

pulseq-checks asked to keep `extensions.refuse_unsigned` as a public helper.
The user chose on 2026-10-07 to remove it:

- The rule is one line for a caller:
  `isinstance(seq.signature_value, str) and seq.signature_value != ""`.
- The helper costs six tests, their `TESTS.md` entries, a section of
  `docs/implementation.md`, and the documentation of a stale-hash limit of a
  check that the package does not make.
- The release candidates allow the removal of a public name with no alias, and
  the downstream packages adapt to this package.

After this plan:

| | `0.1.0rc6` | After this plan (on `main`) |
|---|---|---|
| `load` of a sequence or a file with no hash | `ValueError` | a `Snapshot` |
| `load` of a sequence with a rotation | `NotImplementedError` | no change |
| `load` of an unsigned sequence with a rotation | `ValueError` (the hash was checked first) | `NotImplementedError` |
| `extensions.refuse_unsigned` | public, and `load` calls it | removed (`ImportError`) |
| `snap.sequence.signature_value` | a non-empty `str` | the value of the source, `''` for a sequence built in memory |
| The values of the measurements | | no change |

The branches (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/load-accepts-unsigned` | This plan, and one line for it in `README.md`. No code. |
| 1 | `feature/load-unsigned` | The change, its tests and documents, and an `Unreleased` entry in `CHANGELOG.md` (section 4). No release. |
| 2 | `test/drop-signed` | The tests stop signing their sequences: `synthetic.signed` goes (section 5). Values do not change. After task 1 is merged. |

Not in scope: the release `0.1.0rc7` (the version, the install line of
`README.md` and the tag), which comes after more changes; the pypulseq pin (it
stays at `3c3bd85`, the tag `pulseq-reports-pin-2`); and any other change to
`load`.

## 2. Context (verified on 2026-10-07)

`main` is at `6b7b528`. The version is `0.1.0rc6`, and the last tag is
`v0.1.0rc6`.

1. **The call.** `snapshot.py` line 125 calls `refuse_unsigned(seq)`, and
   line 126 calls `refuse_rotations(seq)`. Line 43 imports both.
2. **No code reads the hash.** Outside `extensions.refuse_unsigned`, no module
   of `src/` reads `signature_value`, `signature_type` or `signature_file`. No
   `__init__.py` or `__all__` exports `refuse_unsigned`.
3. **Only three tests depend on the refusal.** With the line of fact 1
   replaced by `pass`, the full suite gives 9 failures and 1421 passes. The
   failures are the three tests of `tests/test_snapshot.py` that section 4.4
   changes (one of them has 7 parameter cases). No other test needs `load` to
   refuse an unsigned sequence.
4. **The measurements work on an unsigned sequence.** With the call removed
   (a patch of `snapshot.refuse_unsigned` in a scratch script):
   - `load` of a copy of `spin_echo_sequence()` and of `gre_sequence()` with
     `signature_value = ""` gives a snapshot. `snap.sequence.signature_value`
     stays `''`. `gradient_peaks`, `block_gradient_values`,
     `gradient_spectrum` and `sequence_index` equal those of the signed
     sequence. `gradient.peaks`, `gradient.blocks`, `gradient.spectrum` and
     `seq.index` run, and `to_series` runs.
   - `load` of a file of each sequence with its `[SIGNATURE]` section cut off
     gives results equal to those of the same file with the section.
   - The results of a file are not equal to those of the sequence in memory,
     with or without the hash: `write` rounds the values. A test compares a
     file with a file (section 4.4).
5. **pypulseq and old files.** pypulseq's `read` accepts files of version
   1.2.0 and later. It sets `signature_value` only when the file has a
   `[SIGNATURE]` section. Which Pulseq versions wrote that section is not
   verified, so no text of this plan names a version.
6. **`write` changes the sequence.** pypulseq's `write` sets
   `signature_value` and the definition `TotalDuration` on the object that it
   writes (`tests/test_snapshot.py` line 291 says so). A caller who calls
   `snap.sequence.write(path)` changes the private sequence of the snapshot.
7. **The interface test.** `tests/test_interface.py` imports each
   `module.name` that `docs/usage.md` and `docs/implementation.md` give. After
   the removal, these two documents must not name `extensions.refuse_unsigned`,
   or the test fails. `CHANGELOG.md` is not in its list, so the entry of
   section 6 can name it.
8. **The places that change.** From `git grep -i "unsigned\|SIGNATURE\|refus"`:

   | File | Place | Now |
   |---|---|---|
   | `src/pulseq_analysis/snapshot.py` | import, line 43; call, line 125 | both functions. |
   | | module docstring, lines 13 to 17 | `load` refuses a sequence with no hash and a sequence with a rotation. |
   | | `load` docstring, lines 101 to 104 | "ValueError for a sequence with no `[SIGNATURE]` hash ..." |
   | `src/pulseq_analysis/extensions.py` | module docstring, lines 1 to 7 | "Guards that `snapshot.load` calls", two guards. |
   | | `refuse_unsigned`, lines 47 to 74 | the function. |
   | `src/pulseq_analysis/seq_index.py` | module docstring, lines 12 and 13 | "`load` has refused an unsigned sequence and a sequence with a rotation". |
   | `src/pulseq_analysis/grad_peaks.py` | `gradient_peaks` docstring, lines 1079 and 1080 | "A snapshot has no signature hash missing and no rotation". |
   | `src/pulseq_analysis/analyses.py` | no place | No `AnalysisSpec` description names the `ValueError` now (#70 added it, and #80 removed it). No change, and each `spec.version` stays 1. |
   | `docs/usage.md` | line 37 (the example) | "A file that seq.write made: it has a [SIGNATURE] hash." |
   | | line 68 (the module table) | "The refusal of the Pulseq extensions that the measurements do not support, which `load` calls." This stays true. No change. |
   | | lines 93 to 105 (section 2) | the bullet "A signed file, no rotation extension", the order of the checks, and the link to `implementation.md#7-the-signature-check`. |
   | | lines 640 to 644 (section 8) | `refuse_unsigned` and the order of the two calls. |
   | `docs/implementation.md` | line 22 (the contents) | "7. [The signature check](#7-the-signature-check)". |
   | | line 421 | "It also checks the sequence (section 7)." This stays true with the new section 7. No change. |
   | | lines 545 and 546 (section 3.5) | the cost of the two guards. |
   | | section 7, lines 783 to 805 | "The signature check". Section 8 follows it, and `docs/usage.md` line 560 links to section 8. |
   | `TODO.md` | lines 15 and 16 | "The package refuses a sequence with no `[SIGNATURE]` hash, so it needs the last two" (of the pin commits). |
   | `tests/test_snapshot.py` | module docstring, guard 4 (line 9) | "`load` refuses an unsigned sequence and a sequence with a rotation". |
   | | `test_load_refuses_an_unsigned_sequence_and_an_unsigned_file` (line 413) | expects `ValueError`. |
   | | `test_load_checks_the_signature_before_the_rotation` (line 432) | expects `ValueError` for an unsigned sequence with a rotation. |
   | | `test_a_measurement_of_a_snapshot_calls_neither_check_again` (line 440) | expects one call of each guard by `load`. |
   | `tests/test_extensions.py` | import, line 13; `_in_memory_sequence` and `_write_unsigned_file`, lines 16 to 30; six tests, lines 73 to 131 | the tests of `refuse_unsigned`. Four of them test pypulseq's `write` and `read`, not the package. |
   | `tests/synthetic.py` | `signed` and `loaded` docstrings, lines 40 to 55 | "The package refuses a sequence with no hash". |
   | `TESTS.md` | section 2.3 intro, lines 1118 to 1124 | "the two guards", "`snapshot.load` calls both", and the signing of the synthetic sequences. |
   | | section 2.3, lines 1177 to 1258 | the six entries of `test_refuse_unsigned_*`. |
   | | section 2.4 intro, lines 1269 to 1272 | "`snapshot.load` makes and refuses a sequence with no `[SIGNATURE]` hash for". |
   | | section 2.17, lines 6060 to 6098 | the three tests of `test_snapshot.py` above. |

   `CHANGELOG.md` and `docs/reviews/` record the past. They do not change,
   except the new entry of section 6. `pyproject.toml` lines 37 to 42 list
   the pin commits with no reason, so they do not change.
9. **`signed`.** `tests/synthetic.py` signs each builder. About 370 lines in 15 files
   of the tests and scripts use `signed` or `loaded`, and `scripts/doc_figures.py` line 69
   calls `signed`. After task 1, no test needs a hash.

## 3. Decisions

### 3.1 Questions for the user (answered)

| ID | Question | Recommendation | Alternatives |
|---|---|---|---|
| U1 | One PR for the change and the release, or two? | Answered on 2026-10-07: no release in this plan. `0.1.0rc7` comes after more changes. | |
| U2 | What replaces `test_load_checks_the_signature_before_the_rotation`? | Answered on 2026-10-07: `test_load_refuses_an_unsigned_sequence_with_a_rotation`: an unsigned sequence with a rotation library gives `NotImplementedError`. It shows that the rotation check does not depend on a hash. | |
| U3 | When does `signed` go? | Answered on 2026-10-07: in task 2, a separate branch after task 1 is merged. It touches about 370 lines in 15 files and changes no value, so task 1 stays small to review. | |

### 3.2 Decisions with no question

| ID | Decision | Reason |
|---|---|---|
| D1 | `load` adds no hash and removes none. `snap.sequence.signature_value` is the value of the source. | `load` does not change the sequence other than the block cache. A fixed hash would look like a real hash. |
| D2 | `extensions.refuse_unsigned` is removed with no alias. `extensions.py` keeps `refuse_rotations`. | The user's choice (section 1). The rule of the release candidates: an old name raises `ImportError`. |
| D3 | `docs/implementation.md` section 7 becomes "The checks of `load`" (anchor `#7-the-checks-of-load`). It keeps its number, so section 8 and the link of `docs/usage.md` line 560 do not change. The link of `docs/usage.md` line 105 changes to the new anchor. | The section has content after the change: the rotation check, and why the hash is not checked. |
| D4 | The documents tell a caller who requires a hash to read `signature_value` of the source before `load`, or of `snap.sequence`, and not to call `write` on `snap.sequence`. | Fact 6: `write` changes the private sequence. |
| D5 | No text of the documents names a Pulseq version that writes no `[SIGNATURE]` section. | Fact 5: not verified. |
| D6 | No text added to `docs/usage.md` or `docs/implementation.md` cites `pypulseq-issues`. | That repository is private scratch. The user documents describe the behavior directly. |
| D7 | `test_a_measurement_of_a_snapshot_calls_neither_check_again` checks only `refuse_rotations`: one call by `load`, and no call by a measurement. Its new name is `test_load_calls_refuse_rotations_once_and_no_measurement_calls_it`. | `refuse_unsigned` does not exist after the change. |
| D8 | `TODO.md` says that the package does not need the last two pin commits, and that they stay because the three repositories pin one commit. The pin does not change. | Fact 2: no code reads the hash after the change. |
| D9 | Task 1 adds its entry to a new section `## Unreleased` at the top of `CHANGELOG.md` (section 6). The release of `0.1.0rc7` renames the section and adds the entries of the other changes. | The entry is written while the change is known in detail, and the order of the moves of a caller is not lost. |
| D10 | Task 1 adds a note to `README.md` that the documents describe `main`, and that the tag of the install line (`v0.1.0rc6`) refuses an unsigned sequence and has `extensions.refuse_unsigned`. The release removes the note. | After task 1, `docs/usage.md` describes `main`, not the tag that the install line installs. `0.1.0rc5` had such a note (removed by #86). |

## 4. Task 1: `feature/load-unsigned`

Start the branch with the `start-task` skill. Run
`nix develop --command uv sync --frozen` one time in the worktree. Each item
is exactly specified, so one `worker-medium` agent can do the task, or the
main agent can do it directly.

Order: write the new tests of section 4.4 first, and run them while `load`
still calls `refuse_unsigned`. The first two must fail (a test that cannot
fail checks nothing). Then make the change of section 4.1, and see them pass.

### 4.1 Code

1. `snapshot.py`: remove the line `refuse_unsigned(seq)` from `load`
   (line 125). Keep `refuse_rotations(seq)` and the rest of `load`. Change the
   import (line 43) to `from .extensions import refuse_rotations`.
2. `extensions.py`: remove `refuse_unsigned` (lines 47 to 74).

### 4.2 Docstrings

1. `snapshot.py` module docstring, from "`load` then refuses": "`load` then
   refuses a sequence with the rotation extension
   (`extensions.refuse_rotations`), and turns pypulseq's block cache off for
   the private sequence, so no measurement calls the check again and no block
   of the snapshot is kept by pypulseq. `load` does not read the
   `[SIGNATURE]` hash: no result uses it."
2. `load` docstring, the Raises paragraph: "Raises TypeError for another type
   of `source`; NotImplementedError for a sequence with the rotation extension
   (`extensions.refuse_rotations`). A sequence or a file with no `[SIGNATURE]`
   hash is accepted. A file that pypulseq cannot read raises the error of
   `Sequence.read`."
3. `extensions.py` module docstring: "The guard that `snapshot.load` calls.
   `refuse_rotations` refuses a Pulseq extension that the measurements do not
   support. `load` calls it one time for each snapshot. A measurement takes a
   snapshot, so it does not call it."
4. `seq_index.py` lines 12 and 13: "The sequence of a snapshot does not
   change, and `load` has refused a sequence with a rotation, so these
   functions do not check it."
5. `grad_peaks.py` lines 1079 and 1080: "A snapshot has no rotation
   (`snapshot.load` refuses it), so the numbers are of the logical axes as
   they are stored." (The text of line 1164.)
6. `tests/synthetic.py`, `signed`: replace the first paragraph of the reason
   with "`snapshot.load` does not need a hash. Task 2 of
   `docs/plans/load-accepts-unsigned.md` removes this function." Keep the
   rest. `loaded`: no change.

### 4.3 Documents

1. `docs/usage.md` line 37: "# A .seq file. It needs no [SIGNATURE] hash."
2. `docs/usage.md` section 2, the bullet at lines 93 to 105. New text:

   > **No rotation extension.** `load` checks the sequence, so the
   > measurements do not check it again. A sequence with the Pulseq rotation
   > extension raises `NotImplementedError` (`extensions.refuse_rotations`),
   > because the gradients of the file are not the gradients on the scanner.
   > `load` does not read the `[SIGNATURE]` hash, because no result uses it:
   > a sequence built in memory and a file with no `[SIGNATURE]` section
   > load. A caller who requires a hash checks `seq.signature_value` of the
   > source before `load`, or of `snap.sequence`. Do not call `write` on
   > `snap.sequence` to sign it: `write` changes the sequence
   > ([implementation, section 7](implementation.md#7-the-checks-of-load)).

3. `docs/usage.md` section 8, lines 640 to 644: "**`extensions`.**
   `refuse_rotations(seq)` raises `NotImplementedError` when `seq` uses the
   Pulseq rotation extension. `load` calls it one time for each snapshot. A
   measurement does not call it: a snapshot has passed it."
4. `docs/implementation.md` line 22: "7. [The checks of `load`](#7-the-checks-of-load)".
5. `docs/implementation.md` lines 545 and 546: "`extensions.refuse_rotations`
   takes time O(1); `load` calls it one time."
6. `docs/implementation.md` section 7. New text:

   > ## 7. The checks of `load`
   >
   > `load` refuses the Pulseq rotation extension
   > (`extensions.refuse_rotations`, `NotImplementedError`), for each sequence
   > and each file. A measurement does not call the check: a snapshot has
   > passed it.
   >
   > `load` does not read the `[SIGNATURE]` hash. No result uses it: the kept
   > results are on the snapshot object, and no result, `Series` or `meta`
   > holds the hash. So a sequence that `add_block` built in memory, which has
   > no hash, and a file with no `[SIGNATURE]` section load. `load` does not
   > change `signature_value`: `snap.sequence.signature_value` is that of the
   > source (`''` for a sequence built in memory).
   >
   > A caller who requires a hash checks that `seq.signature_value` is a
   > `str` that is not `''`, on the source before `load` or on
   > `snap.sequence`. pypulseq's `write` signs a sequence, but it also changes
   > the definition `TotalDuration`, so call it on the source and `load` the
   > file, never on `snap.sequence`. The presence of a hash does not prove
   > that it is the hash of the sequence: pypulseq keeps `signature_value` on
   > the object when the object changes (`add_block` after `read`), and its
   > `read` does not check the hash against the file.

7. `TODO.md` lines 15 and 16, as D8: "This package no longer reads the
   `[SIGNATURE]` hash, so it does not need the last two. They stay while the
   three repositories pin one commit."

### 4.4 Tests

`tests/test_snapshot.py`:

1. Module docstring, guard 4: "`load` refuses a sequence with a rotation and
   accepts a sequence and a file with no `[SIGNATURE]` hash, and no
   measurement of a snapshot calls the check again."
2. Replace `test_load_refuses_an_unsigned_sequence_and_an_unsigned_file` with
   `test_load_accepts_an_unsigned_sequence_and_an_unsigned_file(tmp_path)`.
   It does not use `signed`, so task 2 does not touch it:
   - `snap = load(_unsigned_sequence())` raises nothing, and
     `snap.sequence.signature_value == ""` (D1). A second
     `_unsigned_sequence()` gets the three signature attributes by hand
     (`signature_type = "md5"`, `signature_file = "text"`, `signature_value`
     a fixed hex `str`), as `write` sets them. `_results` of the two
     snapshots are equal: the hash changes no result.
   - Write the spin echo to `tmp_path / "signed.seq"` with `_written`, and
     write a copy cut at `[SIGNATURE]` to `tmp_path / "unsigned.seq"`. `load`
     of the unsigned file raises nothing, its `signature_value` is `''`, and
     its `_results` equal `_results` of `load` of the signed file. Compare a
     file with a file: `write` rounds the values (fact 4).
   - `_unsigned_file` is then not used: remove it, or change it to give both
     paths.
3. Replace `test_load_checks_the_signature_before_the_rotation` with
   `test_load_refuses_an_unsigned_sequence_with_a_rotation` (U2), with
   `pytest.raises(NotImplementedError, match="rotation extension")` around
   `load(_unsigned_and_rotated())`.
4. `test_a_measurement_of_a_snapshot_calls_neither_check_again`: as D7. The
   count is `{"refuse_rotations": 1}` after `load`, and the failing wrappers
   replace only `refuse_rotations`. Docstring: "`load` calls
   `refuse_rotations` one time. After that, the index, the events, the event
   points, the sampler and the four measurements of the gradients of the
   snapshot do not call it: it is replaced, in `extensions` and in each module
   that can have imported it, by a function that fails."

`tests/test_extensions.py`:

5. Remove `refuse_unsigned` from the import of line 13, the helpers
   `_in_memory_sequence` and `_write_unsigned_file`, and the six tests
   `test_refuse_unsigned_*`. The four tests of `refuse_rotations` stay. Check
   with ruff that no import is left unused.

### 4.5 `TESTS.md`

1. Section 2.3 intro, the first three sentences: "`test_extensions.py` tests
   the guard of `extensions.py`, `refuse_rotations`, which refuses a sequence
   with a rotation. `snapshot.load` calls it, so the measurements, which take
   a snapshot, do not (the refusal through `load` is tested in
   `test_snapshot.py`, section 2.17). Its tests call the guard on a
   sequence." Remove the sentence about the signing of the sequences. The
   rest (task 6.1, PR #372) stays.
2. Section 2.3: remove the six entries `test_refuse_unsigned_*`.
3. Section 2.4 intro: "The functions take a `Snapshot`, which `snapshot.load`
   makes." Remove "and refuses a sequence with no `[SIGNATURE]` hash for".
   The sentence about the signed builders stays until task 2.
4. Section 2.17: the entries of the three tests of section 4.4 (items 2 to
   4), with Checks, How and Assumptions. The assumption of the first:
   "`write` rounds the values, so the unsigned file is compared with the
   signed file, not with the sequence in memory."

### 4.6 `CHANGELOG.md`, `README.md` and the checks

1. `CHANGELOG.md`: the entry of section 6, as a new section `## Unreleased`
   above the entry of `0.1.0rc6` (D9).
2. `README.md`: at the start of the section "Install", the note of D10:

   > The documents (`docs/usage.md` and `docs/implementation.md`) describe
   > `main`. The tag `v0.1.0rc6` of the install line below has an older
   > interface: its `load` refuses a sequence with no `[SIGNATURE]` hash, and
   > it has `extensions.refuse_unsigned`. The next release replaces this note
   > and the tag.

3. No change to the version (`pyproject.toml` stays `0.1.0rc6`), to the
   install line, or to the release sentences of `README.md`.
4. Checks: `nix develop --command scripts/check`. Also
   `git grep -n refuse_unsigned -- src tests docs/usage.md docs/implementation.md TESTS.md TODO.md`
   gives nothing. Then the `ship` skill.

## 5. Task 2: `test/drop-signed`

After task 1 is merged. Start the branch with the `start-task` skill.

1. Replace each `signed(x)` with `x`, and each `loaded(x)` with `load(x)`, in
   `tests/` and in `scripts/doc_figures.py`. Remove `signed`, `loaded` and
   `SIGNATURE_VALUE` from `tests/synthetic.py`, and the imports that are then
   unused.
2. `test_load_accepts_an_unsigned_sequence_and_an_unsigned_file` and
   `_unsigned_and_rotated` set the hash by hand, so they do not change.
3. Check that no value changes: the full suite passes with no change to an
   expected value, and `scripts/doc_figures.py` gives the same figures.
4. `TESTS.md`: remove each sentence about signed builders and
   `synthetic.signed` or `synthetic.loaded` (for example the section 2.4
   intro).
5. No `CHANGELOG.md` entry and no release: the package does not change.

## 6. The `CHANGELOG.md` entry (draft, under `## Unreleased`)

```markdown
## Unreleased

`load` accepts a sequence with no `[SIGNATURE]` hash, and
`extensions.refuse_unsigned` is removed. No result of the package uses the
hash, and the refusal blocked a sequence built in memory and never written,
and a file with no `[SIGNATURE]` section. The values of the measurements do
not change.

This changes the order of `0.1.0rc6` ("A caller moves in this order"):

- Step 2: do not call `write` on a sequence before `load(seq)`. `load`
  accepts an unsigned sequence and raises no `ValueError` for a missing hash.
- Step 1: the pin stays at `3c3bd85`, because pulseq-analysis, pulseq-checks
  and pulseq-reports pin one commit. The code of this package no longer reads
  the hash, so the read of the hash as text no longer matters to it.

### Changed

- `snapshot.load` does not check the hash. A sequence or a file with no hash
  gives a `Snapshot`, and `snap.sequence.signature_value` is the value of the
  source (`''` for a sequence built in memory). `load` still refuses the
  rotation extension (`NotImplementedError`), also for an unsigned sequence,
  which gave `ValueError` before.
- The spec of each analysis is not changed: each `spec.version` stays 1.

### Removed

- `extensions.refuse_unsigned`. A caller who requires a hash checks
  `isinstance(seq.signature_value, str) and seq.signature_value != ""` on the
  source before `load`, or on `snap.sequence`. To sign a sequence, call
  `write` on the source and `load` the file: `write` changes the sequence, so
  do not call it on `snap.sequence`.
```

## 7. Follow-up in pulseq-checks and pulseq-reports

There is no tag with this change until `0.1.0rc7`. A repository that needs it
first pins the merge commit of task 1 by its git revision, and moves to the tag
`v0.1.0rc7` after the release. A caller of
`extensions.refuse_unsigned` gets `ImportError`, and replaces the call with
the check of section 6 where it requires a hash (for example on the files
that a user gives). A caller that runs sequences built in memory can drop its
`write` before `load`. The pypulseq pin is the same in the three
repositories, so it does not change.
