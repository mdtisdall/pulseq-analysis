# Implementation plan: explicit inputs, a complete file, their documented sources, and the drift test

Status: approved by the user on 2026-10-08 (first version, #91). Amended on
2026-10-08: the two layers of a sequence, the rejection of a file before
Pulseq 1.4, the target-free snapshot, the contract of an analysis, and the
drift tests over the registry. Section 3.1 lists the decisions of the user.
The user confirmed D9 and took the recommendation of U5 on 2026-10-08.

## 1. Scope

pulseq-checks reported on 2026-10-08 that `snapshot.load(path)` reads a file
with pypulseq's default `Opts`, so a file that does not declare a raster gets
the raster of pypulseq's default (section 2, facts 2 and 3). The review of
that report found that the package states its rule about target data nowhere,
and that pypulseq can change which values it takes from `Opts` at any version.

### 1.1 The two layers of a sequence

The Pulseq specification (facts 11 and 12) is vendor independent on purpose:
the interpreter of a scanner binds a file to that scanner. So a sequence has
two layers:

1. **The file as specified**: its events, waveforms and timing, in its own
   axes and units (Hz/m, seconds). From Pulseq 1.4, a valid file defines this
   layer completely: the four rasters are required definitions, and "precise
   timing is given by the low-level specification of events".
2. **The file as played on a scanner**: the physical gradients after the
   positioning of the field of view, the gradients in T/m, the frequency of the
   nucleus, whether the delays meet the dead times of the hardware, whether the
   rasters fit the hardware, and the stimulation of a coil. This layer depends
   on the target, by the design of the format.

### 1.2 The decisions of the user (2026-10-08)

- **The rule is "explicit".** Each value of the package is a function of the
  sequence of its snapshot and of the explicit arguments of the call. Data of
  a target (a scanner, a coil, a nucleus) enters only through an explicit
  argument. "Hardware agnostic" in the strict sense (no data of a target
  anywhere) is not the rule: the SAFE PNS model is a model of one coil.
- **The snapshot is target-free: it is layer 1.** An analysis that answers a
  question of layer 2 takes the target data that it needs as explicit
  parameters, as `pns_levels` takes `hardware`. A target-bound snapshot was
  considered and rejected (section 3.3).
- **`load(path)` rejects a file before Pulseq 1.4.** Such a file does not
  define layer 1: a reader must supply its rasters. By the same reason,
  `load(path)` rejects a file of 1.4 or later that does not declare a required
  raster (D9). This replaces U1 of the first version, which kept the behavior
  as a known exception.
- **Assume that any pypulseq call can read any field of `Opts`.** Do not track
  which call reads which field. Document where each input of each pypulseq
  call that the package makes comes from, and say which of them can change a
  value of the package.
- **Detect drift; do not prevent it.** Tests check that no value of any
  analysis of the registry changes when the `Opts` change. They run in the
  normal suite and are the gate for each move of the pypulseq pin. The swap of
  `Opts.default` around each call was considered and rejected: it changes
  process-wide state during the call, it is not thread-safe, and it depends on
  a mechanism of pypulseq that can itself change.

### 1.3 The tasks

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/explicit-sourcing-plan` (#91), `docs/explicit-sourcing-plan-v2` | This plan, and its amendment. No code. |
| 1 | `feature/load-requires-layer-1` | `load(path)` rejects a file that does not define layer 1 (section 4). A change of behavior: an `## Unreleased` entry in `CHANGELOG.md`. |
| 2 | `docs/explicit-sourcing` | The rule and the two layers, the contract of an analysis, the table of the sources, the corrections of the documents, and the drift tests (section 5). No change of behavior. After task 1. |

Not in scope (section 8):

- A change of `asc.hardware_from_asc` for an `.asc` file with no gradient
  scale factors (fact 8). It stays a known exception (U2).
- A job that runs the drift tests against the latest pypulseq release, and a
  version range in place of the pin. Both wait for the item "Move from the
  pypulseq fork to a pypulseq release" of `TODO.md` (fact 10).
- `load(path, *, system=None)`, the second optional request of pulseq-checks.
  A target-free snapshot does not need it.
- A release. The work goes under `## Unreleased`.

## 2. Context (verified on 2026-10-08)

`main` is at `cdf0701`. The version is `0.1.0rc6` (no release since). The
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
   raster that the file does not declare and adds it to `seq.definitions` with
   the `Opts` value (lines 249–261). For a file of 1.4 or later, it warns only
   for `BlockDurationRaster` (line 92) and adds nothing to `seq.definitions`. A
   file of 1.4 or later with no `GradientRasterTime` is read with no warning.
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
   its trapezoid does not change: a trapezoid stores its times in µs. Task 1
   rejects this file.
8. **The `.asc` path.** `asc_to_hw` (`asc_to_hw.py`) takes each SAFE field from
   the file, with two exceptions: `name` is `'unknown'` when `asCOMP.tName` is
   missing (line 53; the package uses its own label, `hardware_name`), and
   `g_scale` is `1/π` on each axis when `asGPAParameters` is missing (lines
   100–104, with a `print`, not a warning). `g_scale` multiplies each PNS
   value (`safe_pns_prediction.py:400`). `readasc` has no defaults.
9. **The documents that are wrong now.**
   - `docs/implementation.md` §1.2: "`dt` is `snap.sequence.grad_raster_time`,
     the `GradientRasterTime` of the file. It is not the raster of
     `snap.sequence.system`." True only after task 1.
   - `docs/implementation.md` §4, "The rasters", `docs/usage.md` §7 and the
     comment of `AnalysisSpec.rasters` (`analyses.py:125`): "the rasters of the
     file". True only after task 1.
   - No document says that `load(path)` reads with `Opts()`, or what `read`
     takes from it.
10. **The pin.** `_safe_gwf_to_pns_chunk` is in the fork only. So the package
    cannot run with an upstream release of pypulseq until the item "Move from
    the pypulseq fork to a pypulseq release" of `TODO.md` is done.
11. **The Pulseq specification** (`doc/specification.pdf` of
    `pulseq/pulseq`, the draft 1.5.3, read on 2026-10-08):
    - The design goals include "Vendor independent: The sequence format must
      not contain constructs specific to a particular hardware manufacturer."
    - From revision 1.4.0, `GradientRasterTime`, `RadiofrequencyRasterTime`,
      `AdcRasterTime` and `BlockDurationRaster` are required definitions. The
      revision history of 1.4.0: "added required definitions", explicit
      sampling and raster alignment conventions, "explicit block duration".
      "Precise timing is given by the low-level specification of events."
    - Without a `[VERSION]` section, "the interpreter … may either refuse
      execution or assume version 1.0.0. It is recommended to reject Pulseq
      files without [VERSION] section."
    - These claims about 1.4 come from the 1.5.3 draft (its revision history
      and "starting from the Pulseq format revision 1.4.0"), not from the 1.4
      document.
12. **What the specification leaves to the interpreter** (layer 2):
    - The ppm offsets of RF and ADC (1.5) are "weighted with the current system
      frequency of the active nucleus" (B0 and gamma).
    - Gradients are in Hz/m: T/m needs gamma (the package gives values with no
      gamma since `0.1.0rc5`).
    - X, Y and Z "refer to physical scanner gradient channels", but the
      interpreter applies the positioning of the field of view of the scanner
      unless the experimental flags `NOROT`, `NOPOS` and `NOSLC` are set, and
      the format "omits … logical coordinate-frame transformations".
    - Dead and ringdown times are not in the file. Since 1.2.1 the tools build
      the RF dead time into the delay of the event, and the interpreter checks
      the delays.
    - "Depending on the particular hardware implementation details different
      electronic components may have different clock resolutions and
      correspondingly different raster times."
13. **The version of a file after `read`.** `read` keeps the version of the
    file in local variables only (`read_seq.py:104–105`). After `read`,
    `seq.version_major`, `seq.version_minor` and `seq.version_revision` are
    the version of pypulseq (1.5.0), not of the file. So `load` must read the
    `[VERSION]` of the file itself.
14. **A sequence built in memory.** `pp.Sequence(...)` sets the four raster
    definitions from its `Opts` (`sequence.py:88–91`), and `write` writes them
    and version 1.5.0. A sequence that a caller read from a file before 1.4
    also has the four definitions: `read` added them with the `Opts` values
    (fact 4). So `load(seq)` cannot tell where its rasters came from.
15. **A built sequence keeps the `Opts` it was built with.** `make_adc` and the
    RF makers raise the delay of the event to the dead time of their `Opts`
    (`make_adc.py:89–94`, `make_sinc_pulse.py:135–140`), and the block
    durations follow from the delays. `get_block` then gives the dead time of
    `seq.system` (fact 5). A built sequence with other `Opts` attached would
    give events whose dead time and delay disagree.
16. **`AnalysisSpec.rasters`** is the one declaration of a dependency in a
    spec (since `0.1.0rc2`, #6; its rule since #60: "the rasters of the file
    whose value changes the value"). No test checks it against behavior: the
    tests compare it with a fixed list. No field of a spec has ever named a
    field of `Opts`.
17. **The tests.** No committed `.seq` file exists: each test file is written by
    pypulseq (version 1.5.0, with the four definitions). No test needs a file
    before 1.4 or a file with no raster definition.
18. **A file of 1.4.1.** `seq.write(path, v141_compat=True)` writes version
    1.4.1 with the four raster definitions. Checked for `spin_echo_sequence`
    and `gre_sequence`: `load` of that file gives `gradient_peaks` and
    `sequence_index` equal to those of the 1.5.0 file. A file with a 1.5.0
    body and a `[VERSION]` changed to 1.4 is not a 1.4 file: pypulseq reads
    its sections in the 1.4 layout.

## 3. Decisions

### 3.1 Questions for the user

| ID | Question | Decision or recommendation |
|---|---|---|
| U1 | What does `load` do with a file that does not declare a raster? | Answered on 2026-10-08: `load(path)` rejects a file before Pulseq 1.4 (task 1). D9 extends this to a file of 1.4 or later with no required raster. |
| U2 | `hardware_from_asc` and an `.asc` file with no `asGPAParameters` (`g_scale` of `1/π`, fact 8). | Answered on 2026-10-08: document it as the known exception, with a characterization test (task 2). Its policy is a later plan. |
| U3 | Where does the table of the sources go? | Answered on 2026-10-08: a new section 9 of `docs/implementation.md`, "Where each input comes from", and a short bullet in `docs/usage.md` §2. |
| U4 | Does the rule in the documents name its known exceptions? | Answered on 2026-10-08: yes. After task 1, the one exception is `g_scale` (U2). |
| U5 | Does the package give the check of task 1 as a public function, for a caller that reads a file itself and calls `load(seq)`? | Answered on 2026-10-08: no. With a target-free snapshot, a caller loads each file one time with `load(path)`, and gives the target data to the analyses as arguments. A caller that reads a file for its own reasons (for example pypulseq's `check_timing` with the `Opts` of a target) does not give that sequence to `load`. The check stays private, and `load(seq)` documents that the caller is the source of layer 1 (fact 14). |

### 3.2 Decisions with no question

| ID | Decision | Reason |
|---|---|---|
| D1 | The table lists the source of each input of each pypulseq call, by entry point (`load(path)`, `load(seq)`, the calls after `load`, `hardware_from_asc`). For each, it says whether a value of the package can change with it. | The user's rule: assume any call can read any field, so the source of each field must be known. |
| D2 | The table covers outputs too: the RF and ADC dead and ringdown times in `rf_events` and `adc_events` come from `seq.system` (fact 5). They are layer 2 data in a layer 1 object, and the table says so. | A value that the package returns is part of its interface, even when no measurement uses it. |
| D3 | The table says that the facts are of the pin `3c3bd85`, and that the drift tests are the check when the pin moves. | Text cannot see that it is out of date. |
| D4 | The drift tests use odd finite values for each field of `Opts`, not NaN. | Fact 6: NaN breaks `read`. |
| D5 | The drift tests run each analysis of `analyses.registry()` with its defaults, and give each necessary parameter from a table in the test module (`hardware`: `EXAMPLE_HW`). An analysis with a necessary parameter that the table does not have fails the test, so its author must add a value. | A new analysis of this package is checked with no new test. |
| D6 | The drift tests use only files that `write` makes, so each file is version 1.5.0 with its four rasters. | Fact 17. After task 1, other files do not load. |
| D7 | The check of task 1 reads the `[VERSION]` and `[DEFINITIONS]` sections of the file text itself, before `read`. It does not depend on how pypulseq reads them. | Fact 13: pypulseq drops the version. Fact 4: pypulseq fills definitions for an old file. A check of the text does not drift with pypulseq. |
| D8 | `TODO.md`, the item "Move from the pypulseq fork to a pypulseq release", gets a step: run the drift tests with the new pin, and check the table of section 9 against it. | The pin move is the time when pypulseq can change under the package. |
| D9 | `load(path)` also rejects a file of 1.4 or later that does not declare each of the four required rasters, and a file with no `[VERSION]` section. Confirmed by the user on 2026-10-08. | The user's reason: layer 1 must come from the file. The specification makes the rasters required from 1.4, and recommends rejecting a file with no `[VERSION]` (fact 11). |
| D10 | The rejection raises `ValueError`. The message names the file version (or the missing `[VERSION]`) or the missing definitions, and says that the file does not define its own timing. | The type of the other errors of `load` for a bad file. |
| D11 | The contract of an analysis (task 2): an analysis reads layer 1 from the snapshot, and takes all layer 2 data as explicit parameters. It does not read `snap.sequence.system`, or the dead and ringdown times of the events. The `Analysis` protocol documents this. | Fact 15 and section 3.3: `seq.system` holds the `Opts` that were on the object, not a target. A dependency on it is not in the spec, so a runner cannot see it. |
| D12 | A behavioral test of `AnalysisSpec.rasters` (task 2): for each analysis of the registry, a file written with one raster definition changed gives a different value only when the spec names that raster. | Fact 16: the declaration is checked against a fixed list only. |

### 3.3 The target-bound snapshot (considered and rejected)

A snapshot bound to one target (`load` takes the target `Opts`, and an
analysis may read them) is explicit too. It was rejected because:

1. Each target gets its own snapshot, so each result that does not depend on
   the target (the index, the event points, the peaks, the spectrum) is made
   again for each target. To avoid it, each analysis must declare the fields of
   `Opts` that it depends on: the tracking of fields that the user rejected.
2. `Opts` is not a description of a target: it has no SAFE coil model, no
   acoustic resonances, no limit for each axis. PNS still takes `hardware` as a
   parameter, so target data would come in two ways. A full target type would
   repeat the target profiles of pulseq-checks.
3. `Opts` mixes design limits, scanner limits, hardware timings, rasters and
   physics. A caller often designs with `Opts` that are not of a target.
4. A built sequence keeps the timing of the `Opts` it was built with (fact 15).
   With other `Opts`, its events give a dead time that does not agree with
   their delay. Whether a file fits a target is a finding of pulseq-checks.
5. A file raster and a target raster that differ both live in the snapshot,
   and each analysis must choose. The difference is itself a finding.
6. Each caller must give a target to `load`, or the process-wide default comes
   back.
7. A cache key and a comparison need the target. The drift tests would need,
   for each analysis, the fields that may change its value.

## 4. Task 1: `feature/load-requires-layer-1`

Start the branch with the `start-task` skill. Run
`nix develop --command uv sync --frozen` one time in the worktree. Write the
tests (4.2) first, and see them fail before 4.1.

### 4.1 The check

1. In `snapshot.py`, a private function `_check_layer_1(path)` that reads the
   text of the file and raises
   `ValueError` (D10) when:
   - the file has no `[VERSION]` section, or its version
     (`major.minor.revision`) is before 1.4.0;
   - its `[DEFINITIONS]` section does not declare each of
     `GradientRasterTime`, `RadiofrequencyRasterTime`, `AdcRasterTime` and
     `BlockDurationRaster`.
   The parse follows the format of the specification: a section starts with a
   line `[NAME]`, `#` starts a comment, and a definition line is a name and
   values separated by white space. It reads only these two sections.
2. `load(path)` calls `_check_layer_1(path)` before `read`. `load(seq)` does not
   call it (fact 14; U5).
3. The docstring of `load`: the rejection, its reason (a file before 1.4 does
   not define its own timing), and that for `load(seq)` the caller is the
   source of the sequence.

### 4.2 Tests (`tests/test_snapshot.py`)

1. `test_load_rejects_a_file_before_pulseq_1_4`: a file that `write` made, with
   its `[VERSION]` changed to 1.3.1 and to 1.2.0, and with the four raster
   lines removed (as a file of that version has them). `ValueError` that names
   the version. A file of 1.3.1 with the four lines kept is rejected too: the
   version decides, not the lines.
2. `test_load_rejects_a_file_with_no_version_section`: the `[VERSION]` section
   removed. `ValueError`.
3. `test_load_rejects_a_file_with_no_required_raster`: parametrized over the
   four definitions. A file of 1.5.0 with that one line removed. `ValueError`
   that names the definition. This is the case of fact 7 and of the report of
   pulseq-checks.
4. `test_load_accepts_files_of_1_4_and_later`: the file of
   `write(path, v141_compat=True)` (version 1.4.1) and the file of `write`
   (1.5.0) load, and their results are equal (fact 18). A 1.4.1 file with its
   `[VERSION]` changed to 1.4.0 loads too (the two layouts are the same). The
   check reads comments, blank lines and the order of the sections as the
   specification allows: a file with a comment line inside `[DEFINITIONS]`
   and `[VERSION]` after `[DEFINITIONS]` loads.
5. `test_load_of_a_sequence_is_not_checked`: a `pp.Sequence` built in memory
   loads (its definitions are set by pypulseq, fact 14).

### 4.3 Documents

1. `docs/usage.md` §2, the bullet "`load(source)`": `load(path)` rejects a file
   before Pulseq 1.4, a file with no `[VERSION]`, and a file with a missing
   required raster, with the reason.
2. `docs/implementation.md` §7, "The checks of `load`": the same, with D7.
3. `CHANGELOG.md`, `## Unreleased`, "Changed": the rejection, the reason, and
   what a caller does with an old file (convert it with a Pulseq tool of 1.4
   or later, which writes the four definitions).
4. `TESTS.md`: the entries of 4.2.

## 5. Task 2: `docs/explicit-sourcing`

After task 1 is merged. Start the branch with the `start-task` skill. Write
the tests (5.4 and 5.5) first.

### 5.1 The rule, the two layers and the contract

1. `docs/usage.md` §2: a new bullet after "`load(source)`":

   > **Explicit inputs.** A snapshot is the file as specified: its events,
   > waveforms and timing, in its own axes and units. Each value is a function
   > of the snapshot and of the explicit arguments of the call. Data of a
   > target (the positioning on a scanner, the nucleus, a coil, the hardware
   > timings) enters only through an argument, such as the PNS `hardware`.
   > pypulseq takes some values from the `Opts` of the object that reads a
   > file: `load(path)` reads with `pp.Opts()`, which copies pypulseq's
   > process-wide `Opts.default`, and `load(seq)` keeps the `Opts` of `seq`.
   > No value of the package depends on these `Opts`. The one known exception:
   > an `.asc` file with no gradient scale factors gets a factor of 1/π
   > ([implementation, section 9](implementation.md#9-where-each-input-comes-from)).

2. `README.md`, the first paragraph: after "explicit physical parameters",
   add "; data of a target enters only through such a parameter".
3. The contract of an analysis (D11), in the docstring of `analyses.Analysis`,
   in the module docstring of `analyses`, and in `docs/usage.md` §7 (the list
   of what an analysis has): "`compute` reads the file as specified from the
   snapshot. It takes each value of a target (a coil, the nucleus, a hardware
   timing, a limit) as a parameter, and does not read `snap.sequence.system`
   or the dead and ringdown times of the events of `rf_events` and
   `adc_events`: these come from the `Opts` that were on the object, not from a
   target."

### 5.2 The table of the sources (`docs/implementation.md` §9)

A new section 9, "Where each input comes from", and its line in the contents.
Its parts:

1. **The two layers** (section 1.1), with the facts of the specification
   (facts 11 and 12) and a link to it.
2. **The rule**, as in 5.1, with the one exception.
3. **`load(path)`.** The check of task 1. Then a table with a row for each
   input: the events, shapes and definitions (the file); the four rasters (the
   file: task 1 rejects a file without them); the block durations (the counts
   of the file times `BlockDurationRaster`); `seq.system` (a copy of
   `Opts.default` at the call of `load`); the ADC dead time (fact 3); the RF
   use (fact 3: none, a file before 1.5 of version 1.4 only); the signature
   (the file). A column says whether a value of the package depends on it.
4. **`load(seq)`.** The snapshot holds a copy of `seq`, its attributes and its
   `seq.system`. The caller is the source of layer 1: a sequence that a caller
   read from a file before 1.4 has rasters from the caller's `Opts`, and `load`
   cannot see it (fact 14).
5. **After `load`.** `get_block` reads `seq.system` of the snapshot on each
   call (fact 5). Neither it nor any other call of the package reads
   process-wide state after `load`.
6. **Outputs that echo `Opts`.** The dead and ringdown times of the events of
   `rf_events` and `adc_events` (D2), and the contract (D11).
7. **`hardware_from_asc`.** Each SAFE field comes from the file, except
   `g_scale` when `asGPAParameters` is missing (fact 8). The label is
   `hardware_name`, not the `name` of `asc_to_hw`.
8. **The other inputs.** gamma: none (section 9 of `docs/usage.md`). The
   limits of a scanner: the caller. The positioning of the field of view: not
   applied; the values are of the axes of the file (`docs/usage.md` §2,
   "Logical axes"). The constants of the package (`TIME_TOLERANCE`,
   `ON_RASTER_TOLERANCE`, `BIN_S`): not data of a target.
9. **The version.** These facts are of the pypulseq pin (`pyproject.toml`). The
   drift tests (`TESTS.md`, section of `test_sources.py`) check them, and the
   pin move of `TODO.md` runs them (D3, D8).

The section gives no `pypulseq-issues` reference (user documents do not cite
it).

### 5.3 The corrections of the documents

1. `docs/implementation.md` §1.2: keep "`dt` is the `GradientRasterTime` of the
   file" (true after task 1), and add: "`snap.sequence.system.grad_raster_time`
   is the raster of the `Opts` of the object, and can differ from it (section
   9)."
2. `docs/implementation.md` §4, "The rasters", `docs/usage.md` §7 and the
   comment of `AnalysisSpec.rasters`: add that the rasters come from the file
   (task 1), and that a test checks the declaration (D12).
3. The docstring of `load`: a paragraph "The reading context": `load(path)`
   reads with `pp.Opts()` (a copy of `Opts.default`); what `read` takes from it
   (fact 3); no value of the package depends on it. A link to section 9 of
   `docs/implementation.md`.
4. The docstring of `asc.hardware_from_asc`: the `g_scale` default of fact 8.
5. `TODO.md`, the pin item: the step of D8.

### 5.4 The drift tests (`tests/test_sources.py`)

Move `_results`, `_gradient_results` and `_differences` of
`tests/test_snapshot.py` to a new helper module `tests/snapshot_results.py`,
and import them in both files. The helper `_odd_opts()` gives a `pp.Opts` with
a finite odd value in each of the 14 fields (D4; for example the values of the
prototype of fact 6). A fixture restores `Opts.default` after each test
(`monkeypatch.setattr(pp.Opts, "default", ...)`). The helper
`_registry_results(snap)` gives `compute` and `to_series` of each analysis of
`registry()`, with the parameters of D5.

Each test is parametrized over the files that `write` makes from the synthetic
builders that `write` accepts (D6): at least the spin echo, the gradient echo,
the arbitrary gradient sequence and `raster_4us_sequence` (a 4 µs gradient
raster, so a raster of the odd `Opts` that the code used by mistake would
show). Each compares `_results` and `_registry_results` with those of
`load(path)` with the default `Opts`.

1. `test_no_result_depends_on_the_opts_of_the_reading_object`: read the file
   into `pp.Sequence(_odd_opts())` and `load` it.
2. `test_no_result_depends_on_the_default_opts_at_load`: set `_odd_opts()` as
   `Opts.default`, then `load(path)`.
3. `test_no_result_depends_on_the_default_opts_after_load`: `load(path)`, then
   set `_odd_opts()` as `Opts.default`, then make the results.
4. `test_the_outputs_that_echo_opts_have_the_values_of_opts`: with the
   snapshot of test 1, the dead time of each ADC event of `adc_events`, and the
   dead time and the ringdown time of each RF event of `rf_events`, equal the
   odd values; and `snap.sequence.system` has the odd values in each field.
5. `test_the_system_of_a_snapshot_keeps_its_rasters_apart_from_the_sequence`:
   for `raster_4us_sequence` written and read with the default `Opts`,
   `snap.sequence.grad_raster_time` is 4e-6 and
   `snap.sequence.system.grad_raster_time` is 1e-5 (fact 3).
6. `test_each_analysis_declares_the_rasters_that_change_its_value` (D12): for
   each analysis of the registry and each of the four rasters, a file with that
   definition changed gives a different value exactly when `spec.rasters`
   names it. Each event must still fit in its block and on its raster after the
   change: double `BlockDurationRaster` (each block gets longer), and halve
   each of the other three (each shape gets shorter, and a multiple of the old
   raster is a multiple of the new one). The test file must have an arbitrary
   gradient, an RF shape and an ADC, so that each raster changes something
   that it times: the implementer checks this for the four rasters before the
   test relies on it.

### 5.5 The characterization test of the exception

`test_hardware_from_asc_assumes_a_gradient_scale_factor_of_1_over_pi`: an
`.asc` file made by the fixture `write_gradient_asc` of `tests/conftest.py`,
with a new keyword argument that leaves out the `asGPAParameters` lines (the
fixture writes them now). `hardware_from_asc` gives `g_scale` of `1/π` on each
axis, and pypulseq prints its warning (`capsys`). The docstring says that the
test fixes the behavior now, that it is the known exception to the rule, and
that U2 owns it.

### 5.6 `TESTS.md`, `CHANGELOG.md` and the checks

1. `TESTS.md`: a new section for `tests/test_sources.py` with an entry for each
   test, and the note in the section of `test_snapshot.py` that `_results` is
   in `tests/snapshot_results.py`.
2. `CHANGELOG.md`, `## Unreleased`, "Documented": the rule and the two layers,
   the contract of an analysis, the table, and that `load(path)` reads with
   `pp.Opts()`. No change of behavior.
3. `nix develop --command scripts/check`. Then the `ship` skill.

## 6. Verification

- Task 1: the tests of 4.2 fail before 4.1 and pass after it. No other test
  changes (fact 17).
- Task 2: the drift tests pass at the pin, as the prototype of fact 6 did. Each
  can fail: on the branch, one time, make `_events.event_points` take `dt` from
  `snap.sequence.system.grad_raster_time`; tests 1 to 3 must fail for the
  37 µs odd raster. Then remove the change. For D12, remove one raster from one
  spec one time; test 6 must fail.
- `test_interface.py` passes: the new text names no public name that does not
  exist.

## 7. What the drift tests do not cover

- An input of pypulseq that is not `Opts` and not a function argument, such as
  a module constant of pypulseq that a new version adds. The tests see it only
  if it changes a result between the reference and the odd case.
- An analysis of another package that is not installed in the test
  environment. The contract (D11) is its rule; the tests check only the
  analyses that `registry()` finds.
- `load(seq)` of a sequence that the caller read from an old file or changed:
  the caller is the source (fact 14).

## 8. Follow-up

- **U2, the policy for `g_scale`.** A later plan.
- **A version range and a drift job against the latest pypulseq.** After the
  pin item of `TODO.md`: a scheduled CI job that runs the drift tests with the
  latest pypulseq release, and a range in `pyproject.toml` that grows only when
  that job passes.
- **pulseq-checks.** Tell pulseq-checks when tasks 1 and 2 are merged:
  - The snapshot is target-free. Load each file one time with `load(path)`, and
    give all target data to the analyses as parameters. One snapshot serves all
    targets: no grouping by `Opts` is needed for the values of the package.
  - `load(path)` rejects a file before Pulseq 1.4, a file with no `[VERSION]`,
    and a file with a missing required raster. A file read by pulseq-checks
    itself and given to `load(seq)` is not checked (U5).
  - An analysis of pulseq-checks (or of another package) follows the contract
    (D11): no reading of `snap.sequence.system` or of the event dead times.
  - If pulseq-checks still gives `load(seq)` a sequence read with the `Opts` of
    a target, it must not share that snapshot across targets whose `Opts`
    differ, unless each analysis that it runs follows the contract. The first
    version of this plan said that the ADC dead time could be left out of the
    grouping; that advice is withdrawn.
