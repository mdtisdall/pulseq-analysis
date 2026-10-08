# Implementation plan: explicit inputs, their documented sources, and the drift test

Status: approved by the user on 2026-10-08. Written on 2026-10-08. The user
took the recommendation of each question of section 3.1 (U1 to U4).

## 1. Scope

pulseq-checks reported on 2026-10-08 that `snapshot.load(path)` reads a file
with pypulseq's default `Opts`, so a file that does not declare a raster gets
the raster of pypulseq's default (section 2, facts 2 and 3). The review of
that report found that the package states its rule about target data nowhere,
and that pypulseq can change which values it takes from `Opts` at any version.

The user chose on 2026-10-08:

- **The rule is "explicit".** Each value of the package is a function of the
  sequence of its snapshot and of the explicit arguments of the call. Data of
  a target (a scanner, a coil, a nucleus) enters only through an explicit
  argument. The PNS `hardware` argument follows this rule. "Hardware agnostic"
  in the strict sense (no data of a target anywhere) is not the rule: the SAFE
  PNS model is a model of one coil.
- **Assume that any pypulseq call can read any field of `Opts`.** Do not track
  which call reads which field. Instead, document where each input of each
  pypulseq call that the package makes comes from, and say which of them can
  change a value of the package.
- **Detect drift; do not prevent it.** A test checks that no value of the
  package changes when the `Opts` change. It runs in the normal suite, and it
  is the gate for each move of the pypulseq pin. The swap of `Opts.default`
  around each call was considered and rejected: it changes process-wide state
  during the call, it is not thread-safe, and it depends on a mechanism of
  pypulseq that can itself change.

This plan gives the work in this repository:

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/explicit-sourcing-plan` | This plan, and one line for it in `README.md`. No code. |
| 1 | `docs/explicit-sourcing` | The rule, the table of the sources, the corrections of the documents, and the drift tests (section 4). No change to the behavior of the package and no release. |

Not in scope (section 7):

- A change of what `load(path)` reads with, or of what the package does with a
  file that does not declare a raster. This plan documents and tests the
  behavior now. The policy is U1.
- A change of `asc.hardware_from_asc` for an `.asc` file with no gradient
  scale factors (fact 7). The policy is U2.
- A job that runs the drift tests against the latest pypulseq release, and a
  version range in place of the pin. Both wait for the item "Move from the
  pypulseq fork to a pypulseq release" of `TODO.md` (fact 10).
- `load(path, *, system=None)`, the second optional request of pulseq-checks.

## 2. Context (verified on 2026-10-08)

`main` is at `41ae97b`. The version is `0.1.0rc6` (no release since). The
pypulseq pin is the fork commit `3c3bd85`. Line numbers of pypulseq are of
that commit.

1. **The pypulseq calls of the package.** After `load`, the package calls only
   `Sequence.get_block` (`seq_index.py`, through `_events`). `load(path)` calls
   `pp.Sequence(use_block_cache=False)` and `Sequence.read`. `pns_levels` calls
   `_safe_gwf_to_pns_chunk(gwf, dt, hw, state)`, which takes all its inputs as
   arguments. `asc.py` calls `readasc` and `asc_to_hw`. The package reads these
   attributes of the sequence: `block_events`, `block_durations`,
   `grad_raster_time`, `extension_string_idx`, `rotation_library` and
   `use_block_cache`. No code of `src/` reads `seq.system`.
2. **The `Opts` of `load(path)`.** `pp.Sequence(system=None)` makes `Opts()`
   (`sequence.py:54–56`). `Opts()` copies each field from the class attribute
   `Opts.default` at that time (`opts.py`). `Opts.default` is process-wide and
   mutable: `set_as_default` (`opts.py:141`) replaces it. Checked: after
   `pp.Opts(grad_raster_time=4e-6).set_as_default()`, a new `pp.Sequence()` has
   a raster of 4 µs. A later `set_as_default` does not change a sequence that
   exists: its `system` is its own copy.
3. **What `read` takes from `seq.system`.**

   | Value | Where (`read_seq.py`) | When |
   |---|---|---|
   | The four rasters (`grad_raster_time`, `rf_raster_time`, `adc_raster_time`, `block_duration_raster`) of the sequence | 57–60, then 77–90 | Each raster that `[DEFINITIONS]` does not declare. |
   | Each block duration | 555: the count of the file times `block_duration_raster` | Files of 1.4 and later. |
   | The dead time of each ADC event | 173–182 (`append=self.system.adc_dead_time`) | Each file: the format has no field for it. |
   | The use of each RF pulse | 428 (`B0`, `gamma`) | Files before 1.5 (`detect_rf_use`). |

   `read` never changes `seq.system`. So the sequence has two copies of each
   raster: its attribute (the file's value, or the `Opts` value if the file
   does not declare it) and the field of `seq.system` (always the `Opts`
   value).
4. **The warnings of `read`.** For a file before 1.4, `read` warns for each
   raster that the file does not declare (lines 249–261). For a file of 1.4
   or later, it warns only for `BlockDurationRaster` (line 92). A file of 1.4
   or later with no `GradientRasterTime` is read with no warning.
5. **What `get_block` takes from `seq.system`.** On each call: the dead time of
   each ADC event (`block.py:483`), and the dead time and the ringdown time of
   each RF event (`rf_from_lib_data`, `sequence.py:1251–1252`). No other global
   or `Opts` read is in `get_block` or `rf_from_lib_data`. The package returns
   these events in `rf_events` and `adc_events`, so these three values reach
   its public interface. No measurement uses them.
6. **The measurements do not depend on `Opts` for a file that declares its
   rasters.** A prototype (a scratch script, not in the repository) read
   `spin_echo_sequence`, `gre_sequence` and `arbitrary_gradient_sequence`
   files three ways: with odd values in each of the 14 fields of `Opts` on the
   reading object; with those values as `Opts.default` during `load(path)`;
   and with those values as `Opts.default` after `load(path)`. In each case
   `sequence_index`, `gradient_peaks`, `block_gradient_values`,
   `gradient_spectrum`, `pns_levels` and the gradient events were equal to the
   values with the default `Opts`. The RF and ADC dead times were the odd
   values (fact 5). NaN does not work for all fields: `read` copies
   `adc_dead_time` into each ADC event and `remove_duplicates` then rounds it,
   which raises for NaN. The odd values must be finite.
7. **A file that does not declare a raster.** A file written on a 4 µs raster,
   with its four raster lines removed, and read with `load(path)`: the
   duration is 4.690 ms instead of 1.876 ms, and the slew of its arbitrary
   gradient is 1.0e9 Hz/m/s instead of 2.5e9 (2.5 times too low). The slew of
   its trapezoid does not change: a trapezoid stores its times in µs. Read
   with an `Opts` of 4 µs and then `load(seq)`, the values are right.
8. **The `.asc` path.** `asc_to_hw` (`asc_to_hw.py`) takes each SAFE field from
   the file, with two exceptions: `name` is `'unknown'` when `asCOMP.tName` is
   missing (line 53; the package uses its own label, `hardware_name`), and
   `g_scale` is `1/π` on each axis when `asGPAParameters` is missing (lines
   100–104, with a `print`, not a warning). `g_scale` multiplies each PNS
   value (`safe_pns_prediction.py:400`). `readasc` has no defaults.
9. **The documents that are wrong now.**
   - `docs/implementation.md` §1.2: "`dt` is `snap.sequence.grad_raster_time`,
     the `GradientRasterTime` of the file. It is not the raster of
     `snap.sequence.system`." For a file that does not declare it, `dt` is the
     raster of the `Opts` at the read.
   - `docs/implementation.md` §4, "The rasters", `docs/usage.md` §7 and the
     comment of `AnalysisSpec.rasters` (`analyses.py:125`): "the rasters of the
     file". The same correction.
   - No document says that `load(path)` reads with `Opts()`, or what `read`
     takes from it.
10. **The pin.** `_safe_gwf_to_pns_chunk` is in the fork only. So the package
    cannot run with an upstream release of pypulseq until the item "Move from
    the pypulseq fork to a pypulseq release" of `TODO.md` is done.

## 3. Decisions

### 3.1 Questions for the user (answered)

| ID | Question | Recommendation | Alternatives |
|---|---|---|---|
| U1 | Does this plan decide what `load` does with a file that does not declare a raster? | Answered on 2026-10-08: No. This plan documents the behavior now as a known exception to the rule, and a characterization test (task 1.4) fixes it, so a later change of the policy changes the test on purpose. The policy is a separate plan. | (a) Decide it here: refuse such a file, or take the rasters from an explicit argument. |
| U2 | The same question for `hardware_from_asc` and an `.asc` file with no `asGPAParameters` (`g_scale` of `1/π`, fact 8). | Answered on 2026-10-08: No. Document it as the second known exception, with a characterization test (task 1.4). | (a) Decide it here: refuse such a file. |
| U3 | Where does the table of the sources go? | Answered on 2026-10-08: A new section 9 of `docs/implementation.md`, "Where each input comes from", after section 8, so no section changes its number. `docs/usage.md` §2 gets a short bullet with the rule and a link, and the docstring of `load` says what `load(path)` reads with (the first optional request of pulseq-checks). | (a) A new document `docs/sources.md`. (b) All in `docs/usage.md`. |
| U4 | The two exceptions of U1 and U2 are against the rule. Does the rule in the documents name them? | Answered on 2026-10-08: Yes. The rule is stated with its known exceptions, each with a link to its row of the table. A rule with silent exceptions is the failure that this plan corrects. | (a) State the rule only, and list the exceptions in the table. |

### 3.2 Decisions with no question

| ID | Decision | Reason |
|---|---|---|
| D1 | The table lists the source of each input of each pypulseq call, by entry point (`load(path)`, `load(seq)`, the calls after `load`, `hardware_from_asc`). For each, it says whether a value of the package can change with it. | The user's rule: assume any call can read any field, so the source of each field must be known. |
| D2 | The table covers outputs too: the RF and ADC dead and ringdown times in `rf_events` and `adc_events` come from `seq.system` (fact 5). | A value that the package returns is part of its interface, even when no measurement uses it. |
| D3 | The table says that the facts are of the pin `3c3bd85`, and that the drift tests are the check when the pin moves. | Text cannot see that it is out of date. |
| D4 | The drift tests use odd finite values for each field of `Opts`, not NaN. | Fact 6: NaN breaks `read`. |
| D5 | The drift tests compare the results of the snapshot test helper `_results` of `tests/test_snapshot.py` (the index, the events, the event points, the sampler and the four measurements). The helper moves to a shared test module so both test files use it. | One list of the results to compare, so a new measurement is checked by both. |
| D6 | The drift tests use only files that `write` makes, so each file declares its rasters. The files that do not declare a raster are the characterization test of U1. | The rule holds only for a file that declares its rasters (fact 7). |
| D7 | No change to the behavior of the package. `load`, the measurements and `asc.py` do not change, other than docstrings. | Scope: the documents and the tests. U1 and U2 are the changes of behavior. |
| D8 | `TODO.md`, the item "Move from the pypulseq fork to a pypulseq release", gets a step: run the drift tests with the new pin, and check the table of section 9 against it. | The pin move is the time when pypulseq can change under the package. |

## 4. Task 1: `docs/explicit-sourcing`

Start the branch with the `start-task` skill. Run
`nix develop --command uv sync --frozen` one time in the worktree. Write the
tests (tasks 1.3 and 1.4) first.

### 4.1 The rule

1. `docs/usage.md` §2: a new bullet after "`load(source)`":

   > **Explicit inputs.** Each value is a function of the sequence of the
   > snapshot and of the explicit arguments of the call. Data of a target (a
   > scanner, a coil, a nucleus) enters only through an argument, such as the
   > PNS `hardware`. pypulseq takes some values from the `Opts` of the object
   > that reads a file. `load(path)` reads with `pp.Opts()`, which copies
   > pypulseq's process-wide `Opts.default`, and `load(seq)` keeps the `Opts`
   > of `seq`. For a file that declares its four rasters, no value of the
   > package depends on these `Opts`. Two known exceptions: a file that does
   > not declare a raster gets the raster of these `Opts`, and an `.asc` file
   > with no gradient scale factors gets a factor of 1/π
   > ([implementation, section 9](implementation.md#9-where-each-input-comes-from)).

   The text of the exceptions follows U4.
2. `README.md`, the first paragraph: after "explicit physical parameters",
   add "; data of a target enters only through such a parameter".

### 4.2 The table of the sources (`docs/implementation.md` §9)

A new section 9, "Where each input comes from", and its line in the contents.
Its parts:

1. **The rule**, as in task 4.1, with the two exceptions.
2. **`load(path)`.** A table with a row for each input: the events, shapes and
   definitions (the file); the four rasters of the sequence (the file if
   declared, else the `Opts` at the read, with the warnings of fact 4); the
   block durations (the counts of the file times `block_duration_raster`);
   `seq.system` (a copy of `Opts.default` at the call of `load`); the ADC dead
   time (fact 3); the RF use of a file before 1.5 (fact 3); the signature (the
   file). A column says whether a value of the package depends on it.
3. **`load(seq)`.** The snapshot holds a copy of `seq`, its attributes and its
   `seq.system`. The package does not know how the caller set them: the
   caller's `Opts` and the caller's changes are the source. To read a file
   with other `Opts`, read it into a `pp.Sequence(system=...)` and call
   `load(seq)`.
4. **After `load`.** `get_block` reads `seq.system` of the snapshot on each
   call (fact 5). Neither it nor any other call of the package reads
   process-wide state after `load`.
5. **Outputs that echo `Opts`.** The dead and ringdown times of the events of
   `rf_events` and `adc_events` (D2).
6. **`hardware_from_asc`.** Each SAFE field comes from the file, except
   `g_scale` when `asGPAParameters` is missing (fact 8). The label is
   `hardware_name`, not the `name` of `asc_to_hw`.
7. **The other inputs.** gamma: none (section 9 of `docs/usage.md`). The
   limits of a scanner: the caller. The constants of the package
   (`TIME_TOLERANCE`, `ON_RASTER_TOLERANCE`, `BIN_S`): not data of a target.
8. **The version.** These facts are of the pypulseq pin (`pyproject.toml`). The
   drift tests (`TESTS.md`, section of `test_sources.py`) check them, and the
   pin move of `TODO.md` runs them (D3, D8).

The section gives no `pypulseq-issues` reference (user documents do not cite
it).

### 4.3 The drift tests (`tests/test_sources.py`)

Move `_results`, `_gradient_results` and `_differences` of
`tests/test_snapshot.py` to a new helper module `tests/snapshot_results.py`
(D5), and import them in both files. The helper `_odd_opts()` gives a
`pp.Opts` with a finite odd value in each of the 14 fields (D4; for example
the values of the prototype of fact 6). A fixture restores `Opts.default`
after each test (`monkeypatch.setattr(pp.Opts, "default", ...)`).

Each test is parametrized over the files that `write` makes from the
synthetic builders that `write` accepts (D6), at least the spin echo, the
gradient echo and the arbitrary gradient sequence, and
`raster_4us_sequence` of `tests/synthetic.py` (a 4 µs gradient raster, so a
raster of the odd `Opts` that the code used by mistake would show).

1. `test_no_result_depends_on_the_opts_of_the_reading_object`: read the file
   into `pp.Sequence(_odd_opts())`, `load` it, and compare `_results` with
   those of `load(path)`.
2. `test_no_result_depends_on_the_default_opts_at_load`: set `_odd_opts()` as
   `Opts.default`, call `load(path)`, and compare.
3. `test_no_result_depends_on_the_default_opts_after_load`: `load(path)`, then
   set `_odd_opts()` as `Opts.default`, and compare `_results` of the snapshot
   with the reference.
4. `test_the_outputs_that_echo_opts_have_the_values_of_opts`: with the snapshot
   of test 1, the dead time of each ADC event of `adc_events`, and the dead
   time and the ringdown time of each RF event of `rf_events`, equal the odd
   values; and `snap.sequence.system` has the odd values in each field.
5. `test_the_system_of_a_snapshot_keeps_its_rasters_apart_from_the_sequence`:
   for a file that declares a 4 µs raster, read with the default `Opts`,
   `snap.sequence.grad_raster_time` is 4e-6 and
   `snap.sequence.system.grad_raster_time` is 1e-5 (fact 3).

### 4.4 The characterization tests of the two exceptions

In `tests/test_sources.py`. Each docstring says that the test fixes the
behavior now, that the behavior is a known exception to the rule, and which
question (U1, U2) owns it.

1. `test_an_undeclared_raster_comes_from_the_opts_at_the_read`: the 4 µs file
   of fact 7 with its raster lines removed. `load(path)` gives
   `grad_raster_time` and `block_duration_raster` of `Opts()`. Read with
   an `Opts` of 4 µs, `load(seq)` gives the values of the file with the
   lines. The test also checks the warnings of fact 4: one warning, for
   `BlockDurationRaster`, and none for `GradientRasterTime`.
2. `test_hardware_from_asc_assumes_a_gradient_scale_factor_of_1_over_pi`: an
   `.asc` file made by the fixture `write_gradient_asc` of `tests/conftest.py`,
   with a new keyword argument that leaves out the `asGPAParameters` lines (the
   fixture writes them now). `hardware_from_asc` gives `g_scale` of `1/π` on
   each axis, and pypulseq prints its warning (`capsys`).

### 4.5 The corrections of the documents

1. `docs/implementation.md` §1.2: "`dt` is `snap.sequence.grad_raster_time`: the
   `GradientRasterTime` of the file, or, when the file does not declare it,
   the raster of the `Opts` at the read (section 9). It is not the raster of
   `snap.sequence.system`, which can differ from it."
2. `docs/implementation.md` §4, "The rasters": "the rasters of the sequence of
   the snapshot (the file's, or the `Opts` at the read for a raster that the
   file does not declare; section 9)".
3. `docs/usage.md` §7 (`rasters` of `AnalysisSpec`) and the comment of
   `AnalysisSpec.rasters` in `analyses.py`: the same words.
4. The docstring of `load`: a paragraph "The reading context": `load(path)`
   reads with `pp.Opts()` (a copy of `Opts.default`); what `read` takes from it
   (fact 3); a file that declares its four rasters gives values that do not
   depend on it; to read with other `Opts`, read the file into
   `pp.Sequence(system=...)` and call `load(seq)`. A link to section 9 of
   `docs/implementation.md`.
5. The docstring of `asc.hardware_from_asc`: the `g_scale` default of fact 8.
6. `TODO.md`, the pin item: the step of D8.

### 4.6 `TESTS.md` and the checks

1. `TESTS.md`: a new section for `tests/test_sources.py` with an entry for each
   test (Checks, How, Assumptions), and the note in the section of
   `test_snapshot.py` that `_results` is in `tests/snapshot_results.py`.
2. `CHANGELOG.md`: an item under `## Unreleased`, "Documented": the rule, the
   table, and that `load(path)` reads with `pp.Opts()`. No change of behavior.
3. `nix develop --command scripts/check`. Then the `ship` skill.

## 5. Verification

- The drift tests pass at the pin, as the prototype of fact 6 did.
- Each drift test can fail. Check it one time on the branch, then remove the
  change: make `_events.event_points` take `dt` from
  `snap.sequence.system.grad_raster_time` in place of
  `snap.sequence.grad_raster_time`. Tests 1 to 3 must fail for the 37 µs odd
  raster.
- `test_interface.py` passes: the new text names no public name that does not
  exist.

## 6. What the drift tests do not cover

- A file that does not declare a raster: the exception of U1.
- An input of pypulseq that is not `Opts` and not a function argument, such as
  a module constant of pypulseq that a new version adds. The tests see it only
  if it changes a result between the reference and the odd case, and they
  change only `Opts`.
- `load(seq)` of a sequence that the caller changed: the source is the caller.

## 7. Follow-up

- **U1, the policy for an undeclared raster.** A later plan. Its choices
  include: refuse the file; take the rasters from an explicit argument of
  `load`; keep the behavior and mark the result. pulseq-checks reads each file
  with the `Opts` of each target, so a change of `load(path)` does not break
  it.
- **U2, the policy for `g_scale`.** A later plan, with U1 or alone.
- **A version range and a drift job against the latest pypulseq.** After the
  pin item of `TODO.md`: a scheduled CI job that runs the drift tests with the
  latest pypulseq release, and a range in `pyproject.toml` that grows only when
  that job passes.
- **pulseq-checks.** The ADC dead time comes from `Opts` for each file (fact
  3), not only for a file that does not declare a value. No value of
  pulseq-analysis uses it, so pulseq-checks can leave it out of the values by
  which it groups its targets. Tell pulseq-checks when this plan is merged.
