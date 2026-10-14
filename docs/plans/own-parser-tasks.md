# Implementation plan: tasks 2, 4, 5a, 5b and 6 of the own parser

Status: draft for review. Written on 2026-10-08, after tasks 1, 1b and 3 were
merged (#95, #96, #97) and the amendment #98. The user answered the questions
of section 2 on 2026-10-08. Section 9 (task 6 and the release 0.1.0rc7) was
revised on 2026-10-13, after the redesign.

This plan makes the remaining tasks of `docs/plans/own-parser.md` ("the parent
plan") exact: the interfaces, the order of the work, the files of each
sub-agent, the oracles, the tolerances and the skips. Where it differs from the
parent plan, this plan decides, and the parent plan points here.

## 1. Changes to the parent plan

| Parent plan | Now | Why |
|---|---|---|
| Task 5, one branch | Task 5a `feature/load-on-model` and task 5b `chore/pypulseq-optional` (section 7, section 8) | U15 |
| Task 2 checks the decoding against KomaMRI's `.mat` files, copied into the repository | Task 2 checks it against MATLAB Pulseq at the commit of the C++ oracle, run under GNU Octave in the default devShell (section 4.4). No KomaMRI `.mat` file is used. | U14, section 3.1 |
| Task 2 checks against pypulseq's `get_block` (marker `pypulseq`) | Not done (D10) | MATLAB and the C++ reader are the references. pypulseq derives from MATLAB. |
| Task 5: a value that changes raises `spec.version` | No `spec.version` changes before the first release. A change of value is a line in `CHANGELOG.md`. | U17 |
| Section 3.5: `GradEvent` | Two types, `Trapezoid` and `ArbitraryGradient` (section 4.2) | U12 |
| Section 3.6: the converter rounds block durations | It also rejects a value that a file cannot hold (`convert.precision`, section 6) | U13 |

## 2. Questions (answered on 2026-10-08)

| ID | Question | Decision |
|---|---|---|
| U11 | The units of the samples of an `RfEvent`. | Physical: `magnitude` in Hz (amplitude times the shape), `phase` in rad (2π times the shape), `t` in s. The amplitude and the shape IDs stay on the event as the identity of the pulse. |
| U12 | One gradient event type, or one for each kind? | Two: `Trapezoid` and `ArbitraryGradient`, and the alias `GradEvent = Trapezoid \| ArbitraryGradient`. |
| U13 | A built `pp.Sequence` with a value that a file cannot hold, such as a delay that is not a whole µs. | Reject: the rule `convert.precision`. A file cannot hold the value (the specification gives the RF, gradient and ADC delays as integers of µs), and the interpreter reads only the file, so no scanner plays it. pypulseq's own `check_timing` flags such a delay. |
| U14 | Where does the MATLAB oracle come from? | MATLAB Pulseq at the commit of the C++ oracle (`c746912`), run under Octave by a script of this repository. Not KomaMRI's `.mat` files: their generator, its Pulseq version and its units are not under our control (section 3.1). |
| U15 | Split task 5? | Yes: 5a (the model behind `load`) and 5b (pypulseq optional, and the guards). |
| U16 | Does a change only of float rounding count as a change of a value? | No. The comparison of task 5a allows a relative 1e-12, and 1e-15 s for times. |
| U17 | Does a changed parameter or value raise `spec.version`? | Not before the first release: version 1 of each analysis is not released, so it can still change. The change is a line in `CHANGELOG.md`. |
| U18 | When does `load` refuse a file with rotations? | When a block plays one: the extension list of a block reaches a `ROTATIONS` object. A file that defines a rotation that no block uses loads. |
| U19 | Where does the MATLAB oracle run? | Locally only. Octave is in the default devShell, not in the `ci` shell. `scripts/check`, which `CLAUDE.md` requires before each PR, runs it. In CI the test is skipped with the reason. |

## 3. Facts (verified on 2026-10-08)

### 3.1 KomaMRI's `.mat` files

- Each `read_comparison` `.mat` holds one struct for each block, with the
  channels `rf`, `df`, `gx`, `gy`, `gz` and `adc`, and `t` and `A` for each
  channel.
- Their units are KomaMRI's, not MATLAB Pulseq's. Gradients are in T/m and RF
  in T: the amplitude of the file divided by 42577468.8 Hz/T, the γ of
  KomaMRI. That γ is the same for the v1.4 and v1.5 trapezoid files and for
  v1.5 `epi`. The times are absolute. RF has a zero point at each end. `df` is
  the frequency offset.
- The headers say that MATLAB wrote them (`Platform: GLNXA64`, April 2024 and
  December 2025; `MACA64`, July 2026). The script that made them is not in
  KomaMRI.jl at `f58d6c8`.
- KomaMRI's #812 (`d4723bb3`, 2026-07-06) rewrote `gr-time-shaped.seq` and
  `gr-uniformly-shaped.seq` (v1.4 and v1.5) with KomaMRI's own writer, and
  replaced their `.mat` files.

So their generator and its version are not ours to fix (U14).

### 3.2 MATLAB Pulseq under Octave

- MATLAB Pulseq at `c746912` (the `matlab` folder of the source that
  `flake.nix` already fetches for the C++ oracle) runs under Octave from
  nixpkgs. Tested: `mr.Sequence().read`, `getBlock`, `waveforms_and_times(true)`
  and `checkTiming`.
- Octave 11.3.0, from the nixpkgs of `flake.lock`, read every file of
  `tests/seqfiles/valid_*.seq` and `tests/seqfiles/oracle/` (25 files) in one
  process in 14 s. The slowest files were `pulseq_epi_rs.seq` (4.1 s) and
  `pypulseq_simple_mprage140.seq` (1.4 s). Octave 9.3.0 gave the same values
  to a relative 1e-12.
- For block 3 of `koma_v1.5_spiral.seq` (an oversampled gradient, time ID -1),
  the `waveform`, `tt`, `shape_dur`, `first` and `last` that MATLAB gives
  equal the values from the model of `read_seqfile` exactly.
- Octave's `jsonencode` drops the imaginary part of a complex array without a
  message. The dump script must write a complex signal as two real arrays.
- The Octave closure is 2.5 GiB (`nix path-info -S`), so it does not go in the
  `ci` shell (U19).

### 3.3 MATLAB's rules of decoding (`matlab/+mr/@Sequence/Sequence.m` at `c746912`)

- Arbitrary gradient (`Sequence.m:1379-1410`): time ID 0 gives
  `tt = ((1:n) - 0.5) * dt` and `shape_dur = n * dt`; time ID -1 gives
  `tt = (1:n) / 2 * dt` and `shape_dur = (n + 1) / 2 * dt`, with n odd; a time
  shape gives `tt = shape * dt` and `shape_dur = tt(end)`. The waveform is the
  amplitude times the shape.
- RF (`Sequence.m:520-535`): `signal = amplitude * mag * exp(1i * 2π * phase)`;
  with a time shape, `t = shape * rf_raster` and
  `shape_dur = ceil((t(end) - eps) / rf_raster) * rf_raster`; without one,
  `t = ((1:n) - 0.5) * rf_raster` and `shape_dur = n * rf_raster`.
- The ADC phase modulation is the decompressed shape (`Sequence.m:1440-1453`).
  The specification gives it no unit. The C++ reader uses it as radians: its
  multiplication by 2π is commented out (`ExternalSequence.cpp:3059-3060`).

### 3.4 The C++ reader (`ExternalSequence.cpp` at `c746912`)

- An RF event with a time shape (`decodeBlock`, `ExternalSequence.cpp:2010-2049`):
  - A "regular" time shape (3 or 4 stored values) gives the dwell as the
    second stored value times the RF raster. It ignores the start offset `t0`.
  - Another time shape is resampled to the RF raster by nearest neighbour.

  So its RF samples are comparable only for an RF event without a time shape.
- `shape_dur` of its RF is the dwell times the number of samples
  (`ExternalSequence.cpp:2061`).
- It has no accessor for the block ID: a block is known by its index in play
  order (`SeqBlock::GetIndex`). Events are known by their IDs
  (`GetEventIndex`).
- Its event values are `float` (32 bits). Its delays and trapezoid times are
  integers of µs, and the ADC dwell is an integer of ns
  (`ExternalSequence.h:88-150`).

### 3.5 The specification and pypulseq

- The RF, gradient and ADC delays are integers of µs
  (`pulseq-spec-1.5.3-draft.txt` lines 431, 499, 544). The ADC dwell is a
  float of ns (line 541).
- pypulseq's `check_timing` checks an RF or ADC delay against `rf_raster_time`,
  and a gradient delay against `grad_raster_time` (`pypulseq/check_timing.py`
  lines 85-104, at the fork pin).
- pypulseq's `write` asserts that a block duration is within 1e-6 ticks of the
  raster (`write_seq.py:89-92`). It rounds the RF delay to the RF raster, and
  the gradient delays and the trapezoid times to µs (`write_seq.py:117, 140, 154`).

### 3.6 The repository

- `tests/conftest.py` imports pypulseq at module level (`safe_example_hw`).
- 20 of the 28 test modules import pypulseq or a helper that does
  (`synthetic`, `gap_sequences`, `scale_sequences`, `random_gaps`,
  `pns_hardware`, `oracles`).
- `scripts/check` on `main` (`c31b1de`) runs 1,664 tests in 19.3 s, in the
  default devShell, with the C++ oracle.
- `_events._read_points`, `seq_index._build_index`, `seq_index._first_events`
  and `GradientSampler.__init__` read the `pp.Sequence` of the snapshot
  (`get_block`, `block_events`, `block_durations`, `grad_raster_time`).
  `grad_spectrum.py:106` and `:205` read `snap.sequence.grad_raster_time`.

## 4. Task 2: `feature/event-decoding`

The worktree `.worktrees/event-decoding` exists and is synced.

### 4.1 Result

- `pulseq_analysis.events`: the event types, decoded from a `SequenceData`.
- The seam: the index, the points of the gradient events and the sampler can be
  built from a `SequenceData` (private functions), with no change to any value
  of the snapshot path.
- The rules `shape.rf-magnitude-negative` and `shape.rf-phase-range` (U9, U10 of
  the parent plan).
- The C++ driver gets the modes `--dump` and `--sample`.
- The MATLAB oracle: Octave and MATLAB Pulseq `c746912` in the default
  devShell, and a dump script.
- Tests of the model, the events and the waveform against both oracles.

`load` and the measurements do not change: they still read the `pp.Sequence`.

### 4.2 The event types (`src/pulseq_analysis/events.py`)

Frozen dataclasses made with `model._model`: read-only arrays, equality by
value, and pickling. Times are in s, from the start of the event (after
`delay`) unless the field says otherwise.

| Type | Fields |
|---|---|
| `Trapezoid` | `id`, `amplitude` (Hz/m), `rise_time`, `flat_time`, `fall_time`, `delay`. Properties: `shape_dur` (rise + flat + fall), `first` and `last` (0.0). |
| `ArbitraryGradient` | `id`, `amplitude` (Hz/m), `shape_id`, `time_id`, `waveform` (Hz/m, the amplitude times the samples), `tt`, `shape_dur`, `first`, `last` (Hz/m), `delay`. |
| `RfEvent` | `id`, `amplitude` (Hz), `mag_id`, `phase_id`, `time_id`, `magnitude` (Hz), `phase` (rad, 2π times the shape), `t`, `shape_dur`, `center` (`None` for a 1.4 file, U6), `delay`, `freq_ppm` (ppm), `phase_ppm` (rad/MHz), `freq_offset` (Hz), `phase_offset` (rad), `use` (one character, as in the file). |
| `AdcEvent` | `id`, `num_samples`, `dwell`, `delay`, `freq_ppm`, `phase_ppm`, `freq_offset`, `phase_offset`, `phase_shape_id`, `phase_modulation` (the decompressed shape as stored, or `None`; section 3.3). |

`GradEvent = Trapezoid | ArbitraryGradient`.

- The names `rise_time`, `tt`, `shape_dur`, `first` and `last` are the ones
  that `seq_utils.gradient_offsets` and the measurements read now, so their
  meaning does not change. The model's table keeps its own column names
  (`rise`).
- The time rules are those of section 3.3. The specification's rules for
  time shapes give the same values.

Functions, each by file ID, over every row of its table (used or not), made
eagerly, as a `MappingProxyType`:

- `decode_rf(data) -> Mapping[int, RfEvent]`
- `decode_gradients(data) -> Mapping[int, GradEvent]` (`[GRADIENTS]` and
  `[TRAP]` share one ID space)
- `decode_adc(data) -> Mapping[int, AdcEvent]`

A shape that several events use is decompressed once in one call.

`seq_utils.gradient_offsets(g)` accepts a `Trapezoid` or an
`ArbitraryGradient`, and still accepts pypulseq's event until task 5a.

### 4.3 The seam (a refactor that keeps the behaviour)

| Function | Where | Content |
|---|---|---|
| `_points_from_events(events, grad_raster_time)` | `_events.py` | The body of `_read_points`. `events` is a sequence of `(dense index, event)`. `_read_points(snap)` calls it. |
| `_index_from_columns(block_id, duration_s, rf, gx, gy, gz, adc)` | `seq_index.py` | The body of `_build_index` after it reads the arrays. `_build_index(seq)` calls it. |
| `_index_from_data(data)` | `seq_index.py` | The index of a `SequenceData`: block IDs from `data.blocks["id"]`; durations from `data.block_durations_s`. |
| `_dense_ids(data, index)` | `seq_index.py` | For each dense RF, gradient and ADC index, the file ID of its event. |
| `GradientSampler._from_parts(index, points, kept)` | `sampling.py` | A sampler from an index, the points and a dict for the kept gaps. `__init__(snap)` calls it with `_kept_results(snap)`. |

The baseline (the `parallel-agents` skill, "Refactors that must not change
behavior"):

- The main agent runs a script in the baseline worktree and in the task
  worktree, for each synthetic builder of `tests/` and each file that `load`
  accepts today.
- The script writes the pickled results of the five analyses (`compute` and
  `to_series`, with fixed parameters and the example hardware).
- The two output folders must be equal byte for byte. The refactor adds code
  paths. It changes no value.

### 4.4 The MATLAB oracle

- `flake.nix`:
  - One binding of the pulseq/pulseq source at `c746912`, shared by the C++
    oracle and the MATLAB oracle.
  - `pulseq-matlab-oracle`, a `writeShellApplication` that runs `octave-cli`
    with `addpath` of `<source>/matlab` and of `tests/matlab_oracle`:
    `pulseq-matlab-oracle OUT_DIR FILE.seq...` writes `OUT_DIR/<stem>.json` for
    each file, in one Octave process.
  - It goes in the default devShell only (U19).
- `tests/matlab_oracle/dump.m`, for each file:
  - `version`, `definitions` (as text), `block_durations`;
  - for each block, the decoded events of `getBlock`: every field, with RF
    `signal` as `signal_abs` and `signal_angle`;
  - the gradient polyline of each axis from `waveforms_and_times(true)`, and
    `t_adc`.

  A file that MATLAB cannot read gives `{"error": message}`. The script has its
  README, which gives the commit and what it calls.
- `tests/oracles/matlab.py` runs the oracle at most one time per test session,
  on all the files, into a cache under `.pytest_cache`. The cache key is the
  SHA-256 of each file and the store path of the oracle, so a later run reads
  the cache.

### 4.5 The C++ driver: `--dump` and `--sample`

`tests/cpp_oracle/driver.cpp`. The present mode (one argument, the file) does
not change.

`--dump FILE` writes one JSON object to stdout. The values are as the C++
structs hold them, with no conversion of units: µs, ns, Hz, rad, raster units.
`float` values are printed with `%.9g` and `double` values with `%.17g`, so
each value is exact. The standard library of C++ writes it, with no new
dependency.

```json
{
  "version": 1005001,
  "definitions": {"GradientRasterTime": "1e-05", "...": "..."},
  "signature_ok": true,
  "blocks": [
    {
      "index": 0,
      "duration_ru": 100,
      "rf": null,
      "grad": [null, {"kind": "trap", "...": "..."}, null],
      "adc": null,
      "trigger": null,
      "soft_delay": null,
      "labelset": [],
      "labelinc": [],
      "rotation": null,
      "rf_shim": null
    }
  ]
}
```

- `rf`: `amplitude`, `mag_shape`, `phase_shape`, `time_shape`, `shape_dur_us`,
  `center_us`, `delay_us`, `freq_ppm`, `phase_ppm`, `freq_offset`,
  `phase_offset`, `use`, `dwell_us`, `magnitude`, `phase`. The two shapes are
  after `checkRF`.
- `grad[c]`:
  - every one: `kind` (`trap`, `arbitrary` or `ext_trap`), `amplitude`,
    `delay_us`;
  - a trapezoid: `ramp_up_us`, `flat_us`, `ramp_down_us`;
  - an arbitrary gradient: `wave_shape`, `time_shape`, `first`, `last`,
    `oversampled`, `samples` (after `checkGradient`);
  - an extended trapezoid: `times_us`, `shape`.
- `adc`: `num_samples`, `dwell_ns`, `delay_us`, `freq_ppm`, `phase_ppm`,
  `freq_offset`, `phase_offset`, `phase_shape`.
- The extension fields are from the accessors of section 2.5 of the parent
  plan. The driver writes `null` or `[]` when the block has none.

`--sample FILE` reads lines `block_index time_us` on stdin, and for each line
writes `gx gy gz` (`%.17g`, the `double` values of `gradientsAt`). It decodes
each block once.

Exit status as now: 0, 1, 2, 70.

### 4.6 The rules U9 and U10

In `seqfile.py`:

- `shape.rf-magnitude-negative`: an RF magnitude sample below
  `-RANGE_TOLERANCE`.
- `shape.rf-phase-range`: an RF phase sample below `-RANGE_TOLERANCE`, or at
  or above `1 + RANGE_TOLERANCE`. A sample of 1 within the tolerance is a full
  turn: the same phase as 0.

Each rule has:

- a fixture (`bad_shape_rf_magnitude_negative.seq`, `bad_shape_rf_phase_range.seq`);
- its line in `NOT_CHECKED_BY_THE_READER` (the reader clamps and accepts);
- its source in the docstring, with the text of section 6.2 item 6 of the
  parent plan.

Every oracle file must still load. If one does not, the agent stops and
reports: the bound of a rule is the user's decision.

### 4.7 Tests

| Test (new file) | Oracle | Compared | Tolerance |
|---|---|---|---|
| `tests/test_decoding.py` | Hand values; the three examples of decompression of the specification | Each field of each event type, for each fixture and kind (time ID 0, -1, >0; 1.4 and 1.5) | Exact, or 1 ulp where a product is involved |
| `tests/test_matlab_oracle.py` (skipped when `pulseq-matlab-oracle` is not on the `PATH`) | MATLAB Pulseq under Octave | (1) For each file that both accept, the events of each block: every field of section 4.2 against `getBlock`. RF `magnitude` and `phase` against `signal_abs` and `signal_angle`, with the phase compared modulo 2π where the magnitude is not 0. (2) The gradient waveform of each axis: `GradientSampler` (from `_from_parts`) at each time of MATLAB's polyline. At a time where MATLAB has two points (a step), the value before the step. Also at the midpoint of each pair of consecutive points. (3) ADC sample times: the block start + `delay` + `(k + 0.5) * dwell` against `t_adc`. | Values: relative 1e-12 of the largest magnitude of the event or the axis. Times: absolute 1e-12 s. Both read the same text in float64. |
| `tests/test_cpp_oracle_decode.py` (marker `cpp_oracle`, skipped when the binary is absent) | The C++ reader | (1) For each file that both accept and that is not in `ORACLE_KNOWN_WRONG`: block durations, and each field of each decoded event against the dump, after the conversion of units in the test. The shapes after `checkGradient` and `checkRF` must equal the package's. A difference means that the scanner plays something else than the file says, for a file that the parser accepts. (2) `signature.matches` against `signature_ok`, for an md5 signature. (3) `--sample` at the centre of each raster cell inside each block, and at the start and end of each event when they are strictly inside the block, against the package's waveform. | Relative 1e-6 of the largest magnitude of the event (`float`). Integer fields exact. |

Skips, each with its reason in the test, by rule and never by file name:

- C++, RF samples of an event with a time shape: the reader resamples it
  (section 3.4). Its scalar fields are still compared.
- C++, a file with an arbitrary gradient and a gradient raster other than
  10 µs: `decodeBlock` fails. The accept/reject test of task 1b gets the same
  skip, and the valid fixture `valid_arbitrary_gradient_4us_raster.seq` shows
  it.
- C++, `first` and `last` of a 1.4 file: `FLOAT_UNDEFINED`.
- C++ `--sample` at a block boundary: the reader works inside one block
  (parent plan, section 2.5).
- MATLAB: a 1.4 file with an arbitrary gradient of time ID 0. The parser
  rejects it. MATLAB guesses the ends from the block before.

A difference that is not one of these skips is not made to pass by a larger
tolerance. The main agent reports it to the user with the file, the block and
the values.

The comparison of `ORACLE_KNOWN_WRONG` stays as it is.

Time budget: the new tests add at most 5 s to `scripts/check` with a warm
MATLAB cache, and at most 20 s with a cold one. A test that is slower uses a
part of the corpus and says which part.

### 4.8 Order and files of each sub-agent

The main agent owns `TESTS.md` and `CHANGELOG.md`. The sub-agents give their
entries in their reports. The main agent writes them and runs the baseline.

**Group 1, in parallel:**

| Agent | Tier | Owns |
|---|---|---|
| E: events | T3 | `src/pulseq_analysis/events.py`, `src/pulseq_analysis/seq_utils.py`, `tests/test_decoding.py`, `tests/test_seq_utils.py` |
| S: seam | T3 | `src/pulseq_analysis/_events.py`, `src/pulseq_analysis/seq_index.py`, `src/pulseq_analysis/sampling.py`, `tests/test_seq_index.py`, `tests/test_sampling.py` |
| R: rules | T2 | `src/pulseq_analysis/seqfile.py`, `tests/test_seqfile.py`, `tests/test_cpp_oracle.py`, the new fixtures of `tests/seqfiles/` |
| C: driver | T2 | `tests/cpp_oracle/driver.cpp`, `tests/cpp_oracle/README.md` |
| M: MATLAB oracle | T2 | `flake.nix`, `tests/matlab_oracle/` |

**Group 2, after the main agent reviewed group 1, in parallel:**

| Agent | Tier | Owns |
|---|---|---|
| MT | T3 | `tests/oracles/matlab.py`, `tests/test_matlab_oracle.py` |
| CT | T2 | `tests/oracles/cpp.py`, `tests/test_cpp_oracle_decode.py` |

`flake.nix` changes the devShell, so the main agent re-enters it after group 1.

## 5. Common rules of each task

- Start with the `start-task` skill. Run `nix develop --command uv sync --frozen`
  one time.
- Only the main agent syncs or locks.
- Write the tests first.
- Read each sub-agent's diff before the checks.
- Run `nix develop --command scripts/check`.
- Show the commit message and wait for approval. Merge only when told.
- No docstring or comment states a fact that was not verified. A sub-agent
  reports what it could not verify.
- `docs/usage.md` and `docs/implementation.md` do not cite pypulseq-issues.

## 6. Task 4: `feature/pypulseq-converter`

**Replaced by task R15 of `docs/plans/parser-redesign.md` (P16), done on branch
`feature/pypulseq-via-seq`.** There is no converter and no `convert.py`: a
`pypulseq.Sequence` in memory is written to Pulseq text with pypulseq's own
writer and read through an interpreter, `seqfile.read_pypulseq(seq,
interpreter)` (`docs/usage.md`, "A pypulseq sequence in memory"). The rules
`convert.precision` and `raster.block-duration`, and the split of
`seqfile._build`, are not made: the writer's rounding is what the scanner
receives, and the interpreter reads it. The rest of this section is kept as the
record of the first plan.

### 6.1 Result

`pulseq_analysis.convert.from_pypulseq(seq) -> SequenceData`:

- It imports pypulseq inside the function. Without pypulseq it raises
  `ImportError` that names the extra `pulseq-analysis[pypulseq]`.
- It checks the result with the parser's rules and raises `SeqFileError` with
  the violations.
- `origin` is `"pypulseq"`, `signature` is `None`, and `version` is the version
  that pypulseq's `write` would write.

### 6.2 The way

1. **Split `seqfile._build`** (a refactor; every test of `test_seqfile.py`
   passes unchanged):
   - reading: the text into a `_File` in the units of the file (µs and ns
     numbers, file IDs, the shape library);
   - `_check_and_assemble(f, definitions, required, signature)`: the checks
     across tables and `_assemble`.

   `_Table.nums` may be `None`. Then a violation has `line=None`, and its
   message names the event ID.
2. **`convert.py` builds a `_File` from pypulseq's in-memory form:**
   - `block_events`, `block_durations` and the event libraries;
   - the shape library, as stored (compressed);
   - the extension libraries, `definitions` and the rasters.

   It does not use `get_block`. The module docstring lists each attribute that
   it reads, checked against the pypulseq of `uv.lock`.
3. **Units:**
   - Each column that a file stores as an integer of µs: the RF, gradient and
     ADC delays, the trapezoid times, and the trigger delay and duration (the
     `i` columns of the layouts of `seqfile`).
   - The converter multiplies the seconds by 1e6. When the result is more than
     1e-6 µs (1 ps, D1 of the parent plan) from an integer, that is the
     violation `convert.precision` (U13). The message has the column, the
     event ID and the value.
   - Float columns (amplitudes, `center`, the ADC dwell in ns, the shapes) are
     converted by multiplication and are not checked.
   - A block duration more than 1e-6 ticks from an integer is
     `raster.block-duration`, the tolerance of pypulseq's `write` (section
     3.5).
4. **Definitions:** the text of each definition as pypulseq's `write` writes
   it. The four rasters come from the sequence.
5. **The new rule IDs:** `convert.precision` and `raster.block-duration` go in
   `RULES`, with their source in the docstring.

### 6.3 Tests (`tests/test_convert.py`, marker `pypulseq`)

1. For each builder of `tests/synthetic.py`, `gap_sequences.py`,
   `scale_sequences.py` and `random_gaps.py` that `write` accepts:
   `from_pypulseq(seq)` equals `read_seqfile` of `seq.write(path)`. A float
   column is compared to the precision with which `write` prints it. The test
   gives that precision for each column, from `write_seq.py`.
2. A builder that `write` refuses (an oversampled arbitrary gradient): the
   decoded events (`events.decode_*` of the converted model) equal the events
   that the builder made.
3. For each rule that a built sequence can break, a built sequence that breaks
   it gives the violation that its file gives. The rules include
   `convert.precision`, `raster.block-duration`, `raster.gradient-ramp`,
   `block.event-too-long` and `gradient.nonzero-start-delay`.
4. `from_pypulseq` without pypulseq (`sys.modules["pypulseq"] = None`, in a
   subprocess) raises the `ImportError` that names the extra.
5. The report of the task lists each test builder that `from_pypulseq`
   rejects. Task 5a fixes those builders: from 5a, every built sequence of the
   tests goes through the converter.

### 6.4 Files

One T3 agent: `src/pulseq_analysis/seqfile.py`,
`src/pulseq_analysis/convert.py`, `tests/test_convert.py`, and the tests of
`test_seqfile.py` that the split needs. The split comes first, and the main
agent reviews it before the converter.

## 7. Task 5a: `feature/load-on-model`

**Replaced by task R14 of `docs/plans/parser-redesign.md` (P15), done on branch
`feature/load-on-interpreters`.** `load(source, interpreter="spec")` is
`pulseq_analysis.analyses.load`: a path through `seqfile.read_seqfile`, a
`pypulseq.Sequence` through `seqfile.read_pypulseq` (R15, which replaced task 4's
`from_pypulseq`). The `Snapshot` holds the interpreter's `SequenceData` and its
decoding, and the measurements take their gradients only through the decoding
(`synth._played`); the rotation extension is no longer refused (the decoding's
`rotation_record` and its warning, P20). The deep copy, the block cache,
`extensions` and `seq_index.rf_events`, `grad_events` and `adc_events` are gone,
and no module of `src/` imports pypulseq. Items 6 (the `hardware` of
`pns_levels`) and 7.3's builder fixes were not needed in this form: the
`SafeHardware` and its namespace form stayed as they were, and the tests that
load a builder that `spec` rejects do it with `cpp-siemens`, in the tests of the
plugin (packages/pulseq-cpp-siemens). The baseline comparison of 7.2
was run for both interpreters; its differences and their causes are in the PR
of R14 and in `CHANGELOG.md`. The rest of this section is kept as the record of
the first plan.

The change of the public interface. pypulseq is still a required dependency.

### 7.1 Result

1. **`snapshot.py`:**
   - `Snapshot(data, source)` holds a `SequenceData`. `Snapshot.data` is the
     model; `Snapshot.sequence` goes.
   - `load(path)` calls `read_seqfile`. `load(seq)` calls `from_pypulseq`.
   - `load` knows a `pp.Sequence` without an import of pypulseq: when
     `sys.modules.get("pypulseq")` is `None`, no argument can be one.
   - The deep copy, the block cache, `block_cache_off` and their tests go: the
     model is immutable. Pickling keeps `data` and `source`.
2. **`extensions.refuse_rotations(data)`:** `NotImplementedError` when a block
   plays a rotation (U18).
3. **`seq_index.py`:**
   - `sequence_index(snap)` is `_index_from_data(snap.data)`.
   - `block_id` holds the file IDs. An ID above the range of uint32 raises
     `ValueError` that names it.
   - `rf_events`, `grad_events` and `adc_events` keep their shape, a tuple of
     `(dense index, event)`, with the event types of task 2 (from
     `events.decode_*` and `_dense_ids`). They no longer call `get_block`.
4. **`_events._read_points`:** `_points_from_events(grad_events(snap),
   snap.data.rasters.gradient)`.
5. **Other modules:**
   - `grad_spectrum`: `snap.data.rasters.gradient`.
   - `seq_utils.gradient_offsets`: the pypulseq branch goes.
6. **`pns_levels(snap, hardware: SafeHardware, ...)`:**
   - The pair goes. `PnsLevels.hardware` is `hardware.name`.
   - `asc.hardware_from_asc(path)` returns a `SafeHardware`.
   - The parameter of `pns.safe.levels` changes with it. Its version stays 1
     (U17).
7. **Docstrings:** every docstring that names `get_block`, the `pp.Sequence` of
   the snapshot or the block cache is updated.

### 7.2 The comparison with the baseline

The main agent runs the script of section 4.3 in the baseline (`main` before
5a) and in the task worktree, and compares with the tolerance of U16.

Each difference beyond it is listed with its cause:

- for example, `seq.index` numbering where pypulseq merged duplicate event
  rows;
- a file that pypulseq read and the parser rejects;
- a file that pypulseq rejected and the parser reads.

The list goes in the PR and in `CHANGELOG.md`. A difference without a cause
stops the task: the main agent reports it to the user.

### 7.3 Tests

- `test_snapshot.py`: the deep-copy and block-cache tests go. In their place:
  - a snapshot of a sequence does not change when the sequence changes after
    `load`;
  - pickling;
  - `load(object())` raises `TypeError`;
  - rotations (U18), with a fixture that defines a rotation that no block uses.
- `test_events.py`: the test that counts `get_block` calls becomes a test that
  `events.decode_gradients` runs one time for each snapshot.
- PNS tests: the `hardware` argument is a `SafeHardware`. The tests of the old
  pair go.
- Each test builder that task 4 reported as rejected is fixed. The fix moves
  its values onto whole µs, and the test's expected values move with it.

### 7.4 Files

| Agent | Tier | Owns |
|---|---|---|
| A: model path | T3 | `snapshot.py`, `extensions.py`, `seq_index.py`, `_events.py`, `sampling.py`, `seq_utils.py`, `grad_spectrum.py`, `grad_peaks.py` (docstrings only), and their tests: `test_snapshot.py`, `test_extensions.py`, `test_seq_index.py`, `test_events.py`, `test_sampling.py`, `test_seq_utils.py`, `test_interface.py` |
| B: PNS and registry | T2 | `pns_levels.py`, `asc.py`, `analyses.py`, `tests/pns_hardware.py`, `test_pns_levels.py`, `test_pns_levels_kept.py`, `test_asc.py`, `test_analyses.py` |
| C: builders | T2, after A | the test builders that task 4 listed (`tests/synthetic.py` and the others) and the expected values that move with them |

The main agent owns `TESTS.md`, `CHANGELOG.md` and the baseline.

## 8. Task 5b: `chore/pypulseq-optional`

No change of behaviour. The order matters.

**After R14 (2026-10-13).** No module of `src/` imports pypulseq: `read_pypulseq`
calls the methods of the sequence that it is given. What is left for this task:
the steps below as written, with `from_pypulseq` (`seqfile/from_pypulseq.py`,
R15) in place of `convert.py` in step 4, and `read_pypulseq` in place of
`from_pypulseq` in step 7 (it needs pypulseq only through its argument, so
without pypulseq a caller has no sequence to give it, and no `ImportError` is
needed). The tests still import pypulseq widely (the builders of
`tests/synthetic.py`, `tests/gap_sequences.py`, `tests/random_gaps.py`,
`tests/scale_sequences.py`, the oracles' comparisons with pypulseq's
`get_gradients`, `calculate_pns` and `calculate_gradient_spectrum`, and the
fork-only functions of step 1). `scripts/doc_figures.py`,
`scripts/discrepancy_matrix.py` and `scripts/time_pns_levels.py` import it too.
pypulseq 1.5.0.post1's `Sequence.remove_duplicates`, which `read_pypulseq`
calls, raises `KeyError` for an oversampled arbitrary gradient (time ID -1,
D43): a release with that fixed, or a way around it in `read_pypulseq`, belongs
with the move to a release (step 2).

1. **Golden values first, with the fork still pinned.** Some tests compare with
   functions that only the fork has (`_safe_gwf_to_pns_chunk` and
   `safe_hw_check` in `test_safe.py`, `test_pns_levels_kept.py`). The main
   agent:
   - records their outputs for the inputs of those tests in `.npz` fixtures
     under `tests/golden/`;
   - writes a `README.md` there with the fork commit and the script that made
     them.

   The tests then compare with the fixtures.
2. **`pyproject.toml`:**
   - `dependencies` are `numpy` and `scipy`;
   - `[project.optional-dependencies] pypulseq = ["pypulseq>=1.5.0"]`;
   - the `dev` group gets the latest pypulseq release from PyPI;
   - `[tool.uv.sources]` goes.

   The main agent locks. `TODO.md`'s pin item is closed for this package.
3. **Tests that the release breaks.** Each test that fails with the release is
   listed in the PR with its cause, for example the `get_block` of an
   oversampled gradient (fork fix, upstream #424). It is fixed in one of two
   ways:
   - it compares with the golden values or with the MATLAB oracle;
   - it skips by rule, with the reason.
4. **ruff:**
   - `extend-select = ["TID251", "TID253"]`;
   - `banned-api` `pypulseq`, and `banned-module-level-imports = ["pypulseq"]`;
   - per-file ignores: `tests/**` for both rules, and
     `src/pulseq_analysis/convert.py` for `TID251`.
5. **pytest markers** in `pyproject.toml`: `pypulseq` and `cpp_oracle`, with
   `--strict-markers`.
   - A module that needs pypulseq starts with `pytestmark = pytest.mark.pypulseq`
     and `pytest.importorskip("pypulseq")`, before its other imports. ruff `E402`
     is ignored for `tests/**`.
   - `tests/conftest.py` no longer imports pypulseq. The example hardware comes
     from `tests/pns_hardware.py` as a `SafeHardware` constant whose values are
     those of `safe_example_hw()`, checked against it by a `pypulseq` test.
6. **`tests/test_imports.py`:** a subprocess imports `pulseq_analysis` and
   each module (`pkgutil.walk_packages`). Then neither `pypulseq` nor
   `matplotlib` is in `sys.modules`.
7. **`tests/test_without_pypulseq.py`:** a subprocess with
   `sys.modules["pypulseq"] = None`:
   - `load(path)` and each analysis of the registry (`compute` and
     `to_series`) run on each oracle file that loads;
   - `from_pypulseq` raises the `ImportError` that names the extra.
8. **`scripts/check`:** a step after pytest,
   `uv run --no-dev --isolated --with pytest pytest -q -m "not pypulseq" tests`.
   A module that imports pypulseq without the marker fails its collection
   here: that is the guard.

**Decisions during task 5b (the user, 2026-10-13).**

- The tests stay on the fork: the `dev` group keeps pypulseq from
  `[tool.uv.sources]` (commit `3c3bd85`), not the latest PyPI release. The fork's
  `calculate_pns` in chunks makes the tests much faster (a run with 1.5.0.post1
  had not ended after 10 minutes). So step 3 has no test to list, and `TODO.md`'s
  pin item stays open, reworded: the package no longer depends on pypulseq.
- `read_pypulseq` is not changed for the `KeyError` of `remove_duplicates` on an
  oversampled arbitrary gradient: the fork raises it too, as does
  `seq.write(path)`.
- ruff's TID251 and TID253 are off for `scripts/**` too: the scripts are in use
  (`doc_figures.py`, `time_pns_levels.py`, `time_measurements.py`) and run with
  the `dev` group.
- The group `analysis` of `packages/pulseq-cpp-siemens` is
  `pulseq-analysis[pypulseq]`, because its tests import pypulseq.

| Agent | Tier | Owns |
|---|---|---|
| main | — | step 1, `pyproject.toml`, `uv.lock`, `TODO.md`, `TESTS.md`, `CHANGELOG.md` |
| K: markers | T2 | every `tests/test_*.py` header, `tests/conftest.py`, `tests/pns_hardware.py`, and the tests of step 3 |
| G: guards | T2 | `tests/test_imports.py`, `tests/test_without_pypulseq.py`, `scripts/check` |

K and G start after step 2.

## 9. Task 6 and the release 0.1.0rc7

Revised on 2026-10-13, after R16 (#128), task 5b (#129) and #130. The first
version of this section was written before the redesign
(`docs/plans/parser-redesign.md`); commit `1e317a1` is the last that has it.
Two audits of `main` at `1e317a1` (the documents against the code, and the
public names of `v0.1.0rc6` against `main`) and a review of what pulseq-checks
and pulseq-reports read from the events give the facts below.

### 9.1 Decisions (the user, 2026-10-13)

| ID | Decision |
|---|---|
| V1 | No code review task before rc7: the user reviews by hand before the release. A fix that the review asks for is its own branch. |
| V2 | The events: no `rf_events(snap)`, `grad_events(snap)` or `adc_events(snap)` (promised in section 5 of the parent plan, never built). The replacement is `synth.events.decode_rf`, `decode_gradients` and `decode_adc` on `snap.data`. pulseq-checks reads no event attribute in its code (its check `timing.pypulseq` runs pypulseq's `check_timing` on its own read); pulseq-reports reads events, from pypulseq reads only, and `decode_*` gives each attribute it reads except the center of a 1.4 RF pulse (section 9.3). That gap is decided when pulseq-reports moves to rc7. |
| V3 | The release of pulseq-cpp-siemens: its wheels and its sdist go on the GitHub release of the tag `v0.1.0rc7`. The sdist carries the reader's files, so an install from the release does not reach pulseq/pulseq; only the build in CI does, at the commit and with the SHA-256 of `pulseq-reader.sha256`. |
| V4 | The plugin's metadata declares `pulseq-analysis>=0.1.0rc7,<0.2`. |
| V5 | Both distributions are `0.1.0rc7` and move in step from now on. The release also carries the wheel and the sdist of pulseq-analysis; the install from the git tag still works. |

### 9.2 Order

| Step | Branch | Result |
|---|---|---|
| 1 | `docs/own-parser-docs` | Task 6, section 9.3. Documentation only. |
| 2 | `chore/release-artifacts` | `.github/workflows/pulseq-cpp-siemens-wheels.yml` (or a new workflow that uses its jobs): on a push of a tag `v*`, build the wheels and the sdist of both distributions, check that each version is the tag's, and create the GitHub release with the files. On pull requests nothing changes. The release section of `packages/pulseq-cpp-siemens/README.md` says how. |
| 3 | — | The user's review (V1), and its fixes, each on its own branch. |
| 4 | `docs/release-0.1.0rc7` | The release commit, as `v0.1.0rc6` (#86): both versions `0.1.0rc7`, the plugin's dependency (V4), both `uv.lock`; `## 0.1.0rc7 (date)` in `CHANGELOG.md`; the install lines of `README.md` and `docs/usage.md` from `@main` to the tag and to the release's files; the links of `docs/findings-for-pulseq-checks.md` to the tag `v0.1.0rc7`. |
| 5 | — | The user pushes the tag; the workflow of step 2 makes the release. |

Steps 1 and 2 touch different files and can run in parallel.

### 9.3 Task 6: `docs/own-parser-docs`

The main agent first runs `scripts/time_measurements.py` and
`scripts/time_pns_levels.py` on `main` and gives the times to U and I: the
times of both documents were taken with the code of R14, before R16.

1. **`docs/usage.md`** (U):
   - a section "Install": pulseq-analysis from the git URL at `@main` (the
     release commit changes it), the extra `pypulseq` and what needs it
     (`load(seq)`, `read_pypulseq`, `asc_to_hw`, `safe_example_hw`), and
     pulseq-cpp-siemens for `cpp-siemens`. Each example that needs the extra
     says so (lines 38, 91, 222, 330 to 340 at `1e317a1`);
   - the module table (lines 63 to 83) gets `synth.scanner`, `synth.events`,
     `seqfile.model`, `seqfile.spec` and `seqfile.from_pypulseq`;
   - a section on the model: each field of `SequenceData` (`version`,
     `definitions`, `rasters`, `required_extensions`, `rf`, `grad`, `trap`,
     `adc`, `shapes`, `extensions`, `origin`, `interpreter`, `records`);
   - a section on the events (V2), in place of `rf_events(snap)` and its
     siblings (lines 632 to 635, which name functions that do not exist):
     `decode_rf`, `decode_gradients` and `decode_adc` on `snap.data`, the
     fields of `RfEvent`, `Trapezoid`, `ArbitraryGradient` and `AdcEvent`,
     the keys (file IDs; a block's events through `decoding.blocks`), and the
     `TypeError` for data of `cpp-siemens`;
   - corrections: the comment of line 708 (the repr of `CppSiemens` has both
     fields; only `str` leaves out the defaults); lines 936 to 938 ("no record
     until R16"; `cpp-siemens` records unknown extensions and labels); line
     770 without the plan's IDs; the cost table (lines 182 to 201) with the
     new times.
2. **`docs/implementation.md`** (I):
   - a section on the oracles: the C++ driver and its sanitized build, MATLAB
     Pulseq under Octave, the golden values of `tests/golden/`, the markers
     `pypulseq` and `cpp_oracle`, and when each test skips;
   - section 3.5 with the new times;
   - line 491: `read_cpp_siemens` decodes every block during the read; only
     the decoding object is lazy.
   - Obsolete items of the first version: the converter and
     `convert.precision` (there is no converter module).
3. **`docs/migration.md`** (new, M): from `v0.1.0rc6` to rc7, for
   pulseq-checks and pulseq-reports. The rows that section 2.2 or section 5
   of the parent plan names come first.
   - The install and the dependencies: the extra `pypulseq`; the fork pin of
     `[tool.uv.sources]`, which stays for the `dev` group and the extra
     (`TODO.md`); pulseq-cpp-siemens and how its version pairs (V4, V5).
   - The modules that moved, with no aliases: `analyses` to
     `analyses.registry` (the API and each `spec.version` unchanged; the
     entry points renamed, the group the same); `snapshot.Snapshot` to
     `synth.Snapshot`, `snapshot.load` to `analyses.load`; `seq_index`,
     `sampling`, `seq_utils` to `synth.*`; `grad_peaks`, `grad_spectrum`,
     `pns_levels`, `series`, `asc` to `analyses.*`; `extensions` removed.
   - `load(source, interpreter="spec", session=None)`: its exceptions
     (`SeqFileError`, `NotSupported`, `SettingError`, `TypeError`) and
     `ScannerSettingWarning`, in place of rc6's `ValueError` for no hash and
     `NotImplementedError` for rotations; a pypulseq sequence is found by its
     methods.
   - `Snapshot.sequence` is gone: `Snapshot(data, source, session)`, with
     `.data`, `.decoding`, `.interpreter`, `.records`, `.session` and the
     three records. The hash is `snap.data.signature`.
   - The events (V2): a table from each attribute of rc6's events to the
     field of `decode_*`, with the keys (file IDs, not the dense index), the
     ADC delay as written in both, the dead time (pypulseq's read copies
     `adc_dead_time`, a value of the target, into `adc.dead_time`; `decode_adc`
     has none; corrected during the task), and `RfEvent.center`, which is `None` in a 1.4 file
     (pypulseq's `calc_rf_center` gives the peak).
   - `SequenceIndex.block_id` is the file's block ID; gradient numbers differ
     where blocks are rotated or have events past their end, and equal events
     with different IDs are no longer merged.
   - `asc.hardware_from_asc` gives `(SafeHardware, label)`;
     `read_gradient_asc` raises `ValueError` with the file and line;
     `pns_levels` takes `SafeHardware` too; `seq_utils.gradient_offsets`
     takes a `Trapezoid` or an `ArbitraryGradient`.
   - The values that changed (from `CHANGELOG.md`).
   - The new names, as an index into `docs/usage.md`.
4. **`README.md`** (M): the document list gets
   `docs/plans/parser-redesign.md`, `docs/discrepancies.md`,
   `docs/specification.md`, `docs/findings-for-pulseq-checks.md`,
   `docs/migration.md`, `CHANGELOG.md`, and the plugin's `README.md` and
   `docs/specification.md`; the line of `own-parser-tasks.md` says that
   R14 and R15 replaced its tasks 4 and 5a; the example says that
   `safe_example_hw` needs the extra. The install lines stay for step 4.
5. **`packages/pulseq-cpp-siemens/README.md`** (P): the comment of line 170
   (as in usage.md); line 295 (records since R16); the names that it does not
   give: `PULSEQ_COMMIT`, `Libraries`, `SoftDelays`, the top-level `CODES`;
   that the group `analysis` installs `pulseq-analysis[pypulseq]`; line 9
   without the plan's IDs.
6. **`CHANGELOG.md`** (main): `## Unreleased` rewritten relative to
   `v0.1.0rc6`, grouped by what a caller sees (reading and the interpreters,
   the plugin, `load` and the snapshot, the events, the scanner session, SAFE
   and `.asc`, the dependencies, the values). Out: what was added and removed
   again since rc6 (the reader `strict`, `read_strict`, `StrictDecoding`, the
   moves of modules that were never released, the empty records of
   `cpp-siemens`, `decode(data)` without `session`). In: #125 (a one-sample
   RF time shape plays for one dwell, D3.9; the reasons of D3.5 and D3.6),
   the distribution pulseq-cpp-siemens (#109), and
   `docs/findings-for-pulseq-checks.md` (#118). The advice of lines 425 to
   429 uses `snap.data.signature`. Lines 30 to 33 and 292 (a 1.4 time shape
   that does not start at 0) are checked against the code and made to agree.
7. **`docs/plans/own-parser.md`** (main): status "done"; section 5 says that
   the event functions became `decode_*` (V2).

| Agent | Tier | Owns |
|---|---|---|
| U | T3 | `docs/usage.md` |
| I | T2 | `docs/implementation.md` |
| M | T3 | `docs/migration.md`, `README.md` |
| P | T2 | `packages/pulseq-cpp-siemens/README.md` |
| main | — | the times, `CHANGELOG.md`, `docs/plans/own-parser.md`, `TESTS.md` (if a test name changed) |

M writes the events table from `src/pulseq_analysis/synth/events.py`, and U
the events section from the same file; the main agent reads both against
each other before the PR.

## 10. Decisions with no question

| ID | Decision | Reason |
|---|---|---|
| D10 | No comparison with pypulseq's `get_block` in task 2. | MATLAB and the C++ reader are the references, and pypulseq derives from MATLAB. Fewer tests depend on pypulseq. |
| D11 | The decode functions give every row of a table by file ID, not only the events that a block uses. | The file defines them, and the mapping by ID is what pulseq-reports needs. |
| D12 | The C++ dump has the units of the C++ structs. The test converts. | Less C++ code to trust. One place of conversion. |
| D13 | No new oracle file is copied in task 2. | MATLAB under Octave reads the files that the repository has. |
| D14 | `TESTS.md` and `CHANGELOG.md` belong to the main agent in each task. | Every sub-agent would change them. |
| D15 | The cache of the MATLAB oracle is keyed by the SHA-256 of the file and the store path of the oracle. | A change of a file or of the oracle runs it again. Nothing else does. |

## 11. Risks

- MATLAB's waveform may differ from the package's in places that the docs say
  agree (`docs/implementation.md` section 1). Such a difference is a finding
  for the user, not a tolerance.
- The pypulseq release may lack fixes that tests rely on (task 5b step 3).
- `convert.precision` may reject many of the test builders (task 4 step 5).
- Octave is not in CI (U19): a change that breaks MATLAB parity is caught only
  by the local `scripts/check`.

## 12. Decisions during task 2 (2026-10-08 and 2026-10-09)

The oracle tests of task 2 found differences between the package, MATLAB Pulseq and the C++
reader. The user decided each one.

| ID | Question | Decision |
|---|---|---|
| U20 | A shape with no sample that an RF event or an arbitrary gradient uses: the parser accepted it, and decoding failed. | A new rule `shape.empty`, stricter than the specification (which says nothing). MATLAB fails on such an event, and the C++ reader crashes or rejects it. |
| U21 | MATLAB draws an arbitrary gradient of time ID 0 with `restoreAdditionalShapeSamples`: it guesses values at the raster edges. | Keep the package's straight lines between the sample centres, as `gradientsAt` of the C++ reader and `docs/implementation.md` section 1. Layer 1 does not guess. The MATLAB test compares such a gradient at its sample centres and its ends. |
| U22 | MATLAB rotates the gradients of a block that plays a rotation. | No change: the measurements do not support rotations, and `load` refuses a file in which a block plays one (U18). The MATLAB waveform test skips such a file by that rule. |
| U23 | `first` of a 1.4 gradient with a time shape: MATLAB carries it over from the block before. | Keep the package's value (the amplitude times the first sample). `layer1.gradient-ends` also rejects a 1.4 time shape that does not start at 0, since then the file has no value at the start of the event. The MATLAB test does not compare `first` of a 1.4 time-shaped gradient. |
| U24 | MATLAB and the C++ reader decode a file differently. | In general, follow the C++ reader: MATLAB is a writer, not an ideal reader. Each such difference still goes to the user. |
| U25 | An RF time shape that the C++ reader takes as regular (3 or 4 stored values): it plays N samples in cells of the step d from the delay, and ignores the first time. | Decode it as the reader plays it: `t = (i + 0.5) d`, `shape_dur = N d`. A new rule `shape.rf-time-grid` rejects such a shape whose times are not the centres of its cells: the reader would play its samples at other times than the file says. |
| U26 | Any other RF time shape: the C++ reader resamples it to the RF raster (`decodeBlock`, `ExternalSequence.cpp:2026-2046`). | Decode it as the reader plays it: `int(0.5 + t_last)` samples on the RF raster, each the stored value that the reader's loop picks. |
| U27 | The signature of a CRLF file: the C++ reader drops the whole empty line (`\r\n`) before `[SIGNATURE]`; the specification strips only the `\n`. | Follow the C++ reader. The discrepancy is issue 14 of pypulseq-issues. |

Decisions with no question:

| ID | Decision | Reason |
|---|---|---|
| D16 | A new rule `shape.rf-time-end` rejects an RF time shape that the reader's resampling reads past the end of (its loop, `ExternalSequence.cpp:2026-2046`, moves to an index equal to the number of stored samples; `model._rf_resample` raises there). | That is undefined behaviour in the scanner. As `shape.empty` for its crash. (Corrected on 2026-10-09: the first text said "whose last time rounds up", which is not the same condition.) |
| D17 | The helpers `model._rf_time_step` and `model._rf_resample` are private. | `events` and `seqfile` share them; they are not part of the interface. |
| D18 | `block.event-too-long` uses the end of an RF event as the reader plays it (U25, U26). | The parser checks the event that the scanner plays. |
