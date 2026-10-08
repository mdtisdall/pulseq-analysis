# Implementation plan: the own parser, the model of layer 1, and pypulseq as an optional extra

Status: approved by the user on 2026-10-08. Written on 2026-10-08. The user
took the recommendation of each question of section 7 (U1 to U8).

## 1. Scope

`docs/plans/own-parser-study.md` ("the study") compared three ways to read a
Pulseq file. The user chose option B on 2026-10-08 (study, section 7):

- The package parses Pulseq text files itself, versions 1.4.0 to 1.5.x, into
  its own immutable model of layer 1 (the file as specified). The binary
  format is out of scope.
- The parser rejects a file that breaks any "must" rule of the specification,
  and a file that does not define layer 1. A 1.4.x file with an arbitrary
  gradient on the default raster (time_id 0) is rejected: its end values are
  not in the file (study, section 2.4).
- `load(seq)` converts a sequence built in pypulseq to the same model.
- Python and numpy. pypulseq is an optional extra, needed only by `load(seq)`.
- The defects of today's `load(path)` (study, section 2.2) are not fixed
  separately: this plan replaces it.
- Oracle files are copied into the repository after a check of the license of
  each file.

From `docs/plans/explicit-sourcing.md` (superseded) this plan keeps the rule
"explicit" (target data enters only through an explicit argument), the two
layers, and the contract of an analysis (it reads layer 1 from the snapshot,
and takes layer 2 data as parameters).

The user's instructions for this plan (2026-10-08):

- Avoid any unintentional dependence on pypulseq: in imports, and in meaning
  (section 4).
- Use existing Python libraries where they fit, rather than new code
  (section 2.3).
- This is a major change. pulseq-checks and pulseq-reports will change their
  code for the new interface, so the interface is not constrained by the old
  one. But it must serve what they need (section 2.2, section 5).

The tasks (`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/own-parser-plan` | This plan, and one line for it in `README.md`. No code. |
| 1 | `feature/seqfile-parser` | The parser, the model, the rules and the violations, the oracle files. `load` does not change (section 6.1). |
| 1b | `chore/cpp-oracle` | The C++ `ExternalSequence` of pulseq/pulseq built in the devShell and CI, and the test that compares its acceptance of each file with the parser's (section 6.1b, U5). |
| 2 | `feature/event-decoding` | The gradient, RF and ADC events of the model (section 6.2). |
| 3 | `feature/own-safe-and-asc` | The package's own SAFE functions, `.asc` reader and SAFE hardware type (section 6.3). |
| 4 | `feature/pypulseq-converter` | `pp.Sequence` to the model, the only module that imports pypulseq (section 6.4). |
| 5 | `feature/load-on-model` | `load` and every measurement on the model; the new public interface; pypulseq an optional extra; the guards against a dependence (section 6.5). |
| 6 | `docs/own-parser-docs` | `docs/usage.md`, `docs/implementation.md`, the migration guide and `CHANGELOG.md` (section 6.6). |

Tasks 1, 1b and 3 can run in parallel (the test of 1b compares with the
parser when task 1 is merged, and is skipped before). 2 needs 1; 4 needs 1 and
2; 5 needs 1 to 4; 6 needs 5. Each task merges into `main` with no release; the work goes under
`## Unreleased` of `CHANGELOG.md`. The release is a separate decision of the
user.

Not in scope: the binary format; writing `.seq` files; measurements under the
rotation extension (the model reads ROTATIONS, the measurements still refuse
it); timing checks against a target (pulseq-checks); the conversion of a
`pp.Sequence` that pypulseq read from a file (section 3.6).

## 2. Context (verified on 2026-10-08)

`main` is at `c24655d`. The version is `0.1.0rc6`; `## Unreleased` has the
removal of `refuse_unsigned` (#89). pypulseq is pinned to the fork commit
`3c3bd85`.

### 2.1 This package (from the study, section 2.1)

- The measurements read only gradient events (`type`, `delay`, `rise_time`,
  `flat_time`, `fall_time`, `amplitude`, `tt`, `waveform`, `shape_dur`,
  `first`, `last`), the block table (`block_events`, `block_durations`) and
  `grad_raster_time`.
- pypulseq outside the sequence: `_safe_gwf_to_pns_chunk` and `safe_hw_check`
  (fork only), `readasc`, `asc_to_hw`. Importing `pns_levels` imports
  matplotlib through pypulseq.
- pypulseq types in the public interface: `load(pp.Sequence)`,
  `Snapshot.sequence`, the `SimpleNamespace` events of `rf_events`,
  `grad_events` and `adc_events`, `SequenceIndex.block_id` ("the pypulseq
  block id"), and the SAFE hardware in the form of `asc_to_hw`.
- pypulseq's `read` keys `block_events` by the block ID of the file. Checked:
  a file whose first block has ID 7 gives the keys `[7, 2, 3]`. So block IDs
  of the file are the IDs that downstream sees today.

### 2.2 pulseq-checks and pulseq-reports

Both pin pulseq-analysis `v0.1.0rc5` (before the snapshot) and the pypulseq
fork `a74ab06`. Each will move once, from rc5 to the interface of this plan.
pulseq-checks has a draft (not merged) plan for rc6.

**pulseq-checks** (`main` at `100c3bc`):

- Uses the registry, `Analysis.compute`, `to_series`, `Series`, the
  `AnalysisSpec` fields `id`, `version`, `params` and `rasters`, and the
  values of `seq.index` (`block_id`, `start_s`), `gradient.limits`,
  `gradient.blocks`, `pns.safe.levels` and `gradient.spectrum`. It reads no
  `Snapshot.sequence` and no event object of this package.
- Reads each file itself, one time for each target, with the target's
  `pp.Opts`, for pypulseq's `check_timing` (rasters, delays, dead times,
  ringdown, soft delays). This is the only place where RF, ADC and soft-delay
  timing enter its checks. The user said on 2026-10-08 that pulseq-checks will
  not use pypulseq's checks: it will compute them from layer 1 and the target
  data. For that it needs from this package the RF and ADC events (delays,
  durations, dwell), the block durations, the rasters and the soft delays.
- Its check `timing.rasters` reports a missing or invalid raster definition.
  After this plan such a file does not load, so pulseq-checks needs the
  violations as data, to show them as findings (D6).
- Builds the SAFE hardware itself (`safe_model.hw_from_dict`) as a
  `SimpleNamespace` in the form of `asc_to_hw`, and reads `.asc` files with
  `asc.read_gradient_asc` and `asc.hardware_name`, and pypulseq's `asc_to_hw`.
- Needs `SequenceIndex.block_id` to be the block ID that its findings name.
- Its plans name later needs: RF checks (peak B1, SAR, frequency offsets),
  interpreter compatibility (file version, supported extensions, library
  size, number of blocks, ADC samples, labels), and `ResultMatrix` with the
  `[SIGNATURE]` of the file.

**pulseq-reports** (`main` at `68682bd`):

- Reads the file itself with `pp.Sequence().read`, and passes the path to
  `run_checks`. Its cards and the result matrix of pulseq-checks come from two
  reads, so their block IDs must agree.
- Reads pypulseq internals: `rf_library.data` rows by position,
  `rf_library.type`, `block_events` columns, `block_durations`, `definitions`,
  `rf_raster_time`, `get_block`, `seq.system.gamma` (a fallback gamma),
  `pp.calc_rf_center`, `pp.calc_duration`.
- Needs, for each unique RF event: the magnitude and phase samples and their
  times, `center`, `shape_dur`, `delay`, the frequency and phase offsets
  (with the ppm terms) and `use`, and an identity of the pulse without its
  offsets (the shape IDs and the amplitude). For each unique ADC event:
  `delay`, `num_samples`, `dwell`. For each block in play order: its ID,
  start, duration and event IDs. All the definitions (`TR`, `FOV`,
  `SliceThickness` and others) and the RF raster.
- Its plans name later needs: support of ROTATIONS, a compact RF table by
  shape, validation against MATLAB's waveforms.

### 2.3 Libraries (survey of 2026-10-08)

- **No existing parser can be the parser.** pydisseqt does not read 1.5 and
  gives no IDs. pulseq-rs (MIT, strict, reads 1.4 and 1.5.x) has no Python
  binding of its own; the one that exists ships in MRzero-Core under AGPL and
  a non-commercial EULA. pypulseqpp imports pypulseq and defaults the rasters.
  The C++ `ExternalSequence` of pulseq/pulseq (MIT, the reader of the
  scanner) has no Python binding.
- **Two are oracles.** The C++ `ExternalSequence` builds with a 30-line driver
  and is strict in the ways that matter (rasters, version, required
  extensions); its acceptance of a file is "would the interpreter load it".
  pulseq-rs is strict too, but has no usable Python binding (U5).
- **Parsing:** numpy and the standard library suffice. `np.loadtxt` with a
  structured dtype parses a table strictly (an `int` column rejects `1.5`,
  `1e2` and `nan`, with the row and column) and fast (22 ms for 100,000
  blocks). A `bytes.translate` check of the characters of an integer section
  (2 ms) rejects `+`, `.`, `e`, `nan`, `0x` before it. Float columns accept
  `nan` and `inf`, so an explicit `np.isfinite` check follows. A `U1` field
  truncates silently, so the `use` column is checked by hand. pandas and
  pyarrow add nothing (pandas accepts `1e2` in an int column; pyarrow cannot
  read the aligned tables); pydantic is heavy.
- **Containers:** read-only numpy arrays (`flags.writeable = False`; a view
  cannot be made writeable again), `dataclasses(frozen=True, slots=True,
  eq=False)` with a value comparison that handles arrays (the package has
  `_equality`), and `types.MappingProxyType` for the definitions. attrs and
  msgspec are not needed.
- **Hash:** `hashlib.md5(raw[:raw.index(b"\n[SIGNATURE]")],
  usedforsecurity=False)` reproduces the hash of a MATLAB-written file.
- **Version:** a tuple of three ints. `packaging` is not needed.
- **Shape decompression:** MATLAB's algorithm in numpy:
  `np.flatnonzero(np.diff(packed) == 0)`, a short loop over the markers,
  `np.repeat` and `np.cumsum`.
- **`.asc`:** nibabel cannot parse `$INCLUDE`; twixtools and pyMapVBVD ignore
  it, cut values at spaces and bring heavy dependencies. The package's own
  reader, with its `$INCLUDE` rule, stays; pypulseq's `readasc` and
  `asc_to_hw` (about 175 lines) are replaced by the package's own code.
- **SAFE:** the reference is `filip-szczepankiewicz/safe_pns_prediction`
  (MATLAB, BSD-3). pypulseq's Python version (BSD-3 notice in an MIT package)
  is what the package uses now; PySAFE_pns_prediction (BSD-3, not on PyPI) is
  a possible second oracle.
- **Guards:** ruff's `TID251` (banned API) and `TID253` (banned at module
  level) are in the ruff that the project has. A subprocess test can check
  `sys.modules` after `import pulseq_analysis`. `uv run --no-dev --isolated
  --with pytest pytest` runs with pypulseq not installed.

### 2.4 Oracle files (study, section 2.6; survey)

- KomaMRI.jl `read_comparison/v1.4`, `v1.5`: `.seq` files with `.mat`
  waveforms that MATLAB Pulseq sampled. KomaMRI is MIT; some files come from
  other projects.
- pulseq/pulseq `tests/expected_output/` and `tests/legacy/approved/`
  (MATLAB-written 1.5.0 and 1.5.1, with labels, ROTATIONS, soft delays,
  triggers, an ADC phase shape). MIT.
- pypulseq `tests/expected_output/` (MATLAB-written `simple_mprage` 1.4.0 to
  1.5.0, and pypulseq-written 1.5.0 files). MIT since 2026-01-28.
- `pulseq-frame/test-seqs` has no license: not usable.
- The survey's 31 mutated copies of one file show which of pulseq-rs, the C++
  reader, pypulseqpp and pypulseq reject each defect (study scratch; the
  table is in the survey report, section 1).

## 3. Design

### 3.1 Modules

| Module | Content | Imports pypulseq |
|---|---|---|
| `pulseq_analysis.seqfile` | `read_seqfile(path) -> SequenceData`; the parser and the rules; `SeqFileError` and `Violation` | no |
| `pulseq_analysis.model` | `SequenceData` and its tables (section 3.2) | no |
| `pulseq_analysis.events` | `GradEvent`, `RfEvent`, `AdcEvent`; decoding from `SequenceData` | no |
| `pulseq_analysis.convert` | `from_pypulseq(seq) -> SequenceData` | yes, inside the function |
| `pulseq_analysis.safe` | `SafeHardware`, `SafeAxis`, the SAFE check and the chunked filter | no |
| `pulseq_analysis.asc` | the `.asc` reader (own `readasc`), `hardware_from_asc` | no |
| `pulseq_analysis.snapshot` | `load`, `Snapshot` (holds a `SequenceData`) | no (it calls `convert` lazily) |
| measurements, `analyses`, `series`, `sampling`, `seq_index` | as now, on `SequenceData` | no |

### 3.2 The model: `SequenceData`

A frozen dataclass of read-only numpy arrays and read-only mappings, in the
units of the file converted to seconds (and Hz, Hz/m, rad as in the file; no
gamma). IDs are those of the file. Fields:

- `version`: `(major, minor, revision)`.
- `definitions`: `MappingProxyType[str, tuple[str, ...]]`, the tokens of each
  line as text (no float conversion: the signature lesson of pypulseq-issues
  09). `rasters`: a frozen dataclass of the four required rasters as floats.
  `required_extensions`: a tuple of STRING_IDs.
- `blocks`: a structured array in file order, which is play order: `id`,
  `duration_ticks` (int, in `BlockDurationRaster` units), `rf`, `gx`, `gy`,
  `gz`, `adc`, `ext`. `block_durations_s` is derived.
- `rf`, `grad`, `trap`, `adc`: one structured array for each table, with an
  `id` column and the columns of the 1.5 layout. A 1.4 file maps to that layout
  (section 3.4).
- `shapes`: `MappingProxyType[int, Shape]`, each with `num_samples` and its
  stored (packed) samples; decoded on use and kept (section 3.5).
- `extensions`: the list table (`id`, `type`, `ref`, `next`), the
  STRING_ID of each type, and one table for each known extension: `triggers`,
  `labelset`, `labelinc` (label name as text), `soft_delays` (hint as text),
  `rotations`, `rf_shims`. `skipped_extensions`: the STRING_IDs of unknown
  extensions that are not required (read, not interpreted).
- `signature`: `None`, or `type`, `hash` and `matches` (the hash of the bytes
  before `\n[SIGNATURE]` compared with `hash`; `None` for a converted
  sequence).
- `origin`: `"file"` or `"pypulseq"`.

No dead time, ringdown time, gamma, B0, limit or other value of a target is in
the model: they are layer 2.

### 3.3 The rules

The parser rejects a file when one of these rules is broken. Each rule has a
stable ID (part of the public interface: pulseq-checks maps it to a finding).
The plan of task 1 makes the list exact; the list below is the minimum.

| ID | Rule | Source |
|---|---|---|
| `version.missing`, `version.unsupported` | `[VERSION]` present; major 1; 1.4.0 ≤ version < 1.6.0 | the specification recommends rejecting a file without it; layer 1 needs it |
| `definitions.raster-missing`, `definitions.raster-invalid` | the four rasters present, finite, above 0 | "required" from 1.4.0 |
| `section.unknown`, `section.delays` | no unknown section; no `[DELAYS]` | `[DELAYS]` "MUST NOT" from 1.4.0 (`read.m`) |
| `syntax.*` | the number of columns of each row for the version; integers as integers; floats finite; `use` one of `e r i s p o u` | the tables and examples of the specification |
| `id.positive`, `id.unique`, `id.gradient-unique` | IDs positive and unique in each class; GRADIENTS and TRAP share one ID space | section 2.2 of the specification |
| `ref.unresolved` | each event, shape and extension reference resolves; each extension list ends with no cycle | implied by the format |
| `blocks.empty` | at least one block | "must declare at least one block" |
| `block.event-too-long` | no event lasts longer than its block | "interpreters must throw an error" |
| `raster.*` | ADC dwell a multiple of `AdcRasterTime`; gradient start, end, ramps and flat top on `GradientRasterTime` | section 2.6 and the ADC table |
| `gradient.nonzero-start-delay`, `gradient.nonzero-end-align` | a gradient that starts above 0 has delay 0; one that ends above 0 ends at the end of its block | section 2.8.2 |
| `shape.length`, `shape.range` | decompressed length equals `num_samples`; an amplitude shape is in [-1, 1] | section 2.9 |
| `extension.required-unknown`, `extension.per-block` | a required STRING_ID is known; at most one ROTATIONS and one RF_SHIMS object for each block | 1.5.1; section 2.8.4 |
| `layer1.gradient-ends` | a 1.4.x file has no arbitrary gradient with time_id 0 | study U1 |

Decisions about the rules: D1 to D5.

### 3.4 Versions

- 1.5.x: the layout of the tables of the specification.
- 1.4.x: RF has 8 columns: `freq_ppm` and `phase_ppm` are 0 (the format had no
  ppm offsets), `use` is `u` (undefined, the specification's meaning), and
  `center` is absent (U6). ADC has 6 columns: the ppm terms and
  `phase_shape_id` are 0. GRADIENTS has 5 columns: for a time-shaped gradient
  (time_id > 0), `first` and `last` are the amplitude times the first and
  last samples, which are at the ends of the event; time_id 0 is rejected
  (`layer1.gradient-ends`). Time_id -1 does not exist in 1.4.
- A version that the parser does not know (1.6 or later, or 1.5 with a layout
  that it cannot read) is rejected with a message that names it. A new
  version fails loudly, not wrongly.

### 3.5 Events

`pulseq_analysis.events` decodes each unique event one time and keeps it on the
snapshot:

- `GradEvent`: the fields that the measurements read today (section 2.1), with
  the rules of time shapes of the specification (time_id 0: samples at the
  centres of the raster cells; -1: the half raster, with `first` and `last`
  from the event; > 0: explicit times). The same fields keep
  `seq_utils.gradient_offsets` and the measurements unchanged in meaning.
- `RfEvent`: `amplitude`, `mag_id`, `phase_id`, `time_id`, `magnitude`,
  `phase`, `t`, `shape_dur`, `center` (or absent), `delay`, `freq_ppm`,
  `phase_ppm`, `freq_offset`, `phase_offset`, `use`. The shape IDs and the
  amplitude are the identity of the pulse without its offsets.
- `AdcEvent`: `num_samples`, `dwell`, `delay`, `freq_ppm`, `phase_ppm`,
  `freq_offset`, `phase_offset`, `phase_modulation`.
- No dead time or ringdown time (layer 2).
- Shape decompression follows MATLAB's `decompressShape.m`, as the
  specification defines it only by examples.

### 3.6 `load` and the converter

- `load(path)` reads with `read_seqfile` and makes a `Snapshot`.
- `load(seq)` takes a `pp.Sequence` built in memory, converts it with
  `from_pypulseq`, and checks the result with the same rules. pypulseq is
  imported inside `from_pypulseq`; without it, `load(seq)` raises
  `ImportError` that names the extra.
- The converter reads pypulseq's in-memory form (`block_events`,
  `block_durations`, the `EventLibrary` data of each kind, the shape library,
  the extension libraries, `definitions`, the rasters), not `get_block`.
  `block_durations` of a built sequence is in seconds, not on the raster; the
  converter rounds it to ticks with the tolerance of pypulseq's `write`, and a
  duration off the raster is the violation `raster.block-duration`.
- A `pp.Sequence` that pypulseq read from a file brings pypulseq's changes
  with it (study, section 2.2). The documents say: load a file with
  `load(path)`.

## 4. No unintentional dependence on pypulseq

Two kinds of dependence are guarded.

**In imports.**

- ruff `TID251` bans `pypulseq` in `src/`, except `convert.py`; `TID253` bans
  it at module level everywhere in `src/`, so `convert.py` imports it inside
  the function. Tests are exempt. In `scripts/check` through `ruff check`.
- A subprocess test imports `pulseq_analysis` and each of its modules
  (`pkgutil.walk_packages`) and checks that neither `pypulseq` nor
  `matplotlib` is in `sys.modules`.
- A test with `sys.modules["pypulseq"] = None` checks that `load(path)` and
  each measurement work, and that `load(seq)` raises the `ImportError` that
  names the extra.
- A step of `scripts/check` and of CI runs the tests without pypulseq
  (`uv run --no-dev --isolated --with pytest pytest -m "not pypulseq"`). Each
  test that needs pypulseq has the marker `pypulseq` and uses
  `pytest.importorskip`. (The pytest marker and the extra have one name.)
- `pyproject.toml`: pypulseq moves to `[project.optional-dependencies]`
  `pypulseq = ["pypulseq>=1.5.0"]` and stays in the `dev` group. The fork pin
  goes (U8).

**In meaning.** The parser must not copy pypulseq's conventions by accident.

- Each rule and each decoding step cites the specification or MATLAB's
  `read.m` / `decompressShape.m`, not pypulseq.
- The parser's tests do not use files that pypulseq wrote as their only
  oracle: each rule has a hand-written fixture (a small text file in
  `tests/seqfiles/`), and the decoding is checked against the waveforms that
  MATLAB sampled (KomaMRI's `.mat` files) and the C++ reader (U5).
- pypulseq stays an oracle where it is right for 1.5 files (`get_block` of
  trapezoids and of arbitrary gradients on the default raster), and is
  compared, not trusted, elsewhere.
- The tests that build sequences with pypulseq's makers stay (they are the
  input of `load(seq)`), and are marked `pypulseq`.

## 5. The interface for pulseq-checks and pulseq-reports

| Need (section 2.2) | Today | After this plan |
|---|---|---|
| Read a file | each reads it with pypulseq | `load(path)`, one time; `snap.data` is the `SequenceData` |
| A file that breaks a rule | pypulseq accepts or crashes | `SeqFileError` (a `ValueError`) with `violations`: each a `Violation(rule, section, line, message)` (D6) |
| Block IDs | pypulseq keys = file IDs | file IDs (`snap.data.blocks["id"]`, `SequenceIndex.block_id`), the same in both packages |
| Blocks in play order, start, duration, event IDs | `block_events`, `block_durations`, `get_block` | `snap.data.blocks`, `sequence_index(snap)` |
| RF events (samples, times, center, delay, offsets, use, identity) | `rf_library.data` by position, `get_block`, `calc_rf_center` | `rf_events(snap)` → `RfEvent` |
| ADC events | `get_block` | `adc_events(snap)` → `AdcEvent` |
| Gradient events | `get_block` | `grad_events(snap)` → `GradEvent` |
| Definitions, RF raster | `seq.definitions`, `seq.rf_raster_time` | `snap.data.definitions` (text), `snap.data.rasters` |
| Soft delays, labels, triggers, rotations | pypulseq's libraries, `check_timing` | `snap.data.extensions` |
| Signature | `seq.signature_*` | `snap.data.signature` (with `matches`) |
| Timing checks against a target | pypulseq's `check_timing` with the target's `Opts` | pulseq-checks computes them from `snap.data` and its target (not this package) |
| SAFE hardware | `SimpleNamespace` in the form of `asc_to_hw` | `SafeHardware` (U3); `SafeHardware.from_namespace` accepts the old form |
| `.asc` | `read_gradient_asc`, `hardware_name`, pypulseq's `asc_to_hw` | the same names, and `asc.safe_hardware(asc)` in place of `asc_to_hw` |
| A gamma when there is no target | `seq.system.gamma` | none in the model: the caller chooses (the rule "explicit") |
| The measurements, the registry, `Series` | as rc6 | no change of meaning; the first argument is still the snapshot |

Consequences to tell the two projects (in the migration guide of task 6):

- pulseq-checks: one `load(path)` for all targets; the check `timing.rasters`
  becomes the mapping of violations to findings; `limits_from_sequence` and
  the `gamma` of a `pp.Sequence` stay pulseq-checks' own; its plugin
  `ctx.sequence` becomes the snapshot.
- pulseq-reports: no `pp.Sequence().read`; the cards read `snap.data` and the
  event types; `hold_samples` and `peak_tr_window` stay in pulseq-reports;
  the fallback gamma becomes an explicit choice in pulseq-reports.
- Both: pypulseq is not needed unless they build sequences in memory.

## 6. Tasks

Each task: start the branch with the `start-task` skill; run
`nix develop --command uv sync --frozen` one time; write the tests first;
`nix develop --command scripts/check`; the `ship` skill.

### 6.1 Task 1: `feature/seqfile-parser`

1. `pulseq_analysis.seqfile` and `pulseq_analysis.model` (sections 3.2 to 3.4).
   The parser reads the file as bytes (for the signature) and as text; it
   splits sections at header lines; it skips blank and `#` lines inside a
   section, except in `[SHAPES]`, where a blank line ends a shape; it parses
   each table with `np.loadtxt` and a structured dtype after the character
   check (section 2.3); it collects violations and raises `SeqFileError` with
   all of them at the end (D6).
2. The rules of section 3.3, each with its ID, tested by one hand-written
   fixture that breaks only that rule, and by the mutated files of the survey.
3. The oracle corpus in `tests/seqfiles/oracle/` (D7, U7 of the study): each
   file with its source URL and commit, its license, and its use, in a
   `SOURCES.md`. Every oracle file that the C++ reader accepts and that is
   1.4 or later must load, except the 1.4.x files with time_id 0 arbitrary
   gradients, which must give `layer1.gradient-ends`.
4. Shapes decoded with MATLAB's algorithm, tested on the three examples of the
   specification and on the oracle files.
5. The signature: `matches` for the MATLAB-written files.
6. Speed: `read_seqfile` of `build_repeating(20000)` and `build_worst(20000)`
   files, measured and recorded; it must be faster than today's `load(path)`
   (0.36 s and 1.09 s).
7. No change to `load`. `TESTS.md` for the new tests.

### 6.1b Task 1b: `chore/cpp-oracle`

1. `flake.nix`: a derivation that builds the C++ `ExternalSequence` of
   pulseq/pulseq (MIT; the `src/` folder at the commit of the oracle corpus)
   with a small driver that reads a `.seq` file and exits 0 when it loads,
   and non-zero with the message when it does not. The driver goes in
   `tests/cpp_oracle/` with its license notice. The binary is on the `PATH`
   of the devShell and of the CI shell.
2. A test with the marker `cpp_oracle`: each file of `tests/seqfiles/`
   (fixtures and oracle corpus) is accepted by both readers or rejected by
   both, except the rules that the C++ reader does not check (listed in the
   test with the reason: for example `block.event-too-long`, which it checks
   at run time). Skipped when the binary is absent.
3. `scripts/check` and CI run the test.

### 6.2 Task 2: `feature/event-decoding`

1. `pulseq_analysis.events` (section 3.5): decoding from `SequenceData`,
   functions that take the model (not yet the snapshot).
2. Tests against the MATLAB-sampled waveforms of KomaMRI's
   `read_comparison/v1.4` and `v1.5` (gradients and RF, block by block, to the
   precision of the text format), and against pypulseq's `get_block` for 1.5
   files (marker `pypulseq`).
3. The oversampled spiral (time_id -1) decodes; today pypulseq crashes on it.

### 6.3 Task 3: `feature/own-safe-and-asc`

1. `pulseq_analysis.safe`: `SafeAxis` (`tau1`, `tau2`, `tau3`, `a1`, `a2`,
   `a3`, `stim_limit`, `stim_thresh`, `g_scale`), `SafeHardware` (`name`, `x`,
   `y`, `z`), `SafeHardware.from_namespace`, the hardware check, and the
   chunked SAFE filter, from pypulseq's `safe_hw_check` and
   `_safe_gwf_to_pns_chunk` with the BSD-3 notice of Szczepankiewicz and
   Witzel and the MIT notice of pypulseq (U3).
2. `pulseq_analysis.asc`: the package's own reader in place of `readasc`, and
   `asc.safe_hardware(asc)` in place of `asc_to_hw`, with the policy of U4 for
   a missing gradient scale factor.
3. `pns_levels` uses them. Its values do not change: a test compares with
   pypulseq's functions at the pin (marker `pypulseq`).

### 6.4 Task 4: `feature/pypulseq-converter`

1. `pulseq_analysis.convert.from_pypulseq` (section 3.6), the only import of
   pypulseq in `src/`, inside the function.
2. Tests: for each synthetic builder that `write` accepts, `from_pypulseq(seq)`
   and `read_seqfile` of `seq.write(path)` give equal models, to the
   precision of the text format; for builders that `write` refuses
   (oversampled arbitrary gradients), the converted events equal the built
   events.
3. A built sequence that breaks a rule gives the same violation as its file
   would.

### 6.5 Task 5: `feature/load-on-model`

This is the change of the public interface.

1. `load(path)` uses `read_seqfile`; `load(seq)` uses `from_pypulseq`.
   `Snapshot.sequence` goes; `Snapshot.data` is the `SequenceData`. The block
   cache, the deep copy of a file, `block_cache_off` and their tests go: the
   model is immutable.
2. `seq_index`, `_events`, `sampling` and the measurements read the model and
   `events`. `rf_events`, `grad_events` and `adc_events` give the package's
   event types. `refuse_rotations` reads `snap.data.extensions`.
3. `pns_levels` takes `hardware: SafeHardware` (U3).
4. `pyproject.toml`: pypulseq an optional extra; the fork pin goes (U8);
   `TODO.md`'s pin item closes for this package.
5. The guards of section 4.
6. The spec of each analysis: `seq.index` counts unique events by the file's
   IDs (pypulseq's `remove_duplicates` merged some). Its `spec.version`
   changes if its value changes for a valid file; the same check for each
   analysis (a value that changes is a new version).
7. The tests that build sequences go through `load(seq)`; the tests of the
   snapshot's deep copy become tests of `from_pypulseq`.

### 6.6 Task 6: `docs/own-parser-docs`

1. `docs/usage.md` and `docs/implementation.md`: the rule "explicit", the two
   layers, the model, the rules and the violations, the events, `load`, the
   contract of an analysis, the extra.
2. `docs/migration.md`: for each name of rc6 (and rc5, as both projects pin
   rc5), its replacement; the consequences of section 5.
3. `CHANGELOG.md`, `## Unreleased`.
4. `README.md`: the install line with the extra.

## 7. Questions for the user (answered on 2026-10-08)

| ID | Question | Decision (the recommendation) | Alternatives |
|---|---|---|---|
| U1 | The names: `SequenceData`, `Snapshot.data`, `read_seqfile`, `SeqFileError`, `Violation`, `from_pypulseq`, the extra `pypulseq`. | As written. | Other names. |
| U2 | Does `Snapshot` stay, or does `load` give the model with the kept results on it? | `Snapshot` stays: it holds the kept results, and the model stays a plain value that a caller can compare and pickle. | One object. |
| U3 | The SAFE hardware: a new type, or the `SimpleNamespace` of `asc_to_hw`? | `SafeHardware` (frozen, checked on construction), with `from_namespace` for the old form and for `safe_example_hw()`. The `hardware` argument is a `SafeHardware`; its `name` is the label (no pair). | Keep the pair `(namespace, label)`. |
| U4 | The package's `.asc` reader and a file with no gradient scale factors (`g_scale`; explicit-sourcing U2). | Reject, with a message: the rule of the parser, and the factor multiplies each PNS value. | Assume 1/π as pypulseq does, documented. |
| U5 | The C++ `ExternalSequence` as an oracle: in the devShell and CI, or by hand? | In the devShell (a small Nix derivation of the MIT source and the driver), and a test with the marker `cpp_oracle` that each oracle and fixture file is accepted or rejected by both readers alike, skipped where the binary is absent. | By hand only; or not at all. |
| U6 | The `center` of an RF event of a 1.4 file is not in the file. | Absent (`None`): layer 1. A caller that needs it computes it (pulseq-reports uses `calc_rf_center` today). | Compute it with MATLAB's `calcRfCenter` and document it as derived. |
| U7 | A file with many violations: all of them, or the first? | All, with at most 20 locations for each rule (the count of the rest is kept), so that pulseq-checks can show each kind. | The first only. |
| U8 | The pypulseq fork pin. | Remove it. After task 3 no code of `src/` needs the fork; the converter reads pypulseq's in-memory form, and the extra requires `pypulseq>=1.5.0`. Tests that used the fork's fixes compare with MATLAB's waveforms instead. | Keep the pin for the tests. |

## 8. Decisions with no question

| ID | Decision | Reason |
|---|---|---|
| D1 | A comparison of a time with a raster is in integer nanoseconds where the file gives µs integers, and with an absolute tolerance of 1 ps for the ns floats (dwell). | The units of the file; the reference implementation uses 1e-12 s. |
| D2 | `shape.range` allows [-1 - ε, 1 + ε], with ε the largest error of decompression found on the oracle corpus, rounded up; no oracle file may fail it. | The text has 9 significant digits and decompression adds. |
| D3 | Where the prose of the specification contradicts its tables and examples (pypulseq-issues 13), the tables and examples decide. | They agree with each other and with MATLAB's files. |
| D4 | The signature is checked and reported (`matches`), not a rule: the specification has no "must" to verify it. | Section 2.4 of the specification. |
| D5 | Rules phrased "need to" or "can be specified" are enforced as "must" (`gradient.nonzero-end-align`, `extension.per-block`). | The user's decision U2 of the study; they state the format, not a preference. |
| D6 | `SeqFileError(ValueError)` has `violations: tuple[Violation, ...]`, and `Violation` has `rule` (the ID of section 3.3), `section`, `line` (or `None`), `message`. | pulseq-checks shows them as findings. |
| D7 | Oracle files go in `tests/seqfiles/oracle/` with `SOURCES.md` (source, commit, license, use). A file without a license that allows it is not copied. | Study U7. |
| D8 | The `.mat` waveforms are read with `scipy.io.loadmat` (scipy is a dependency already). | No new library. |
| D9 | No new runtime dependency. Only numpy and scipy. | Section 2.3. |

## 9. Risks

- The semantics of the format are now the package's: shapes, time shapes, the
  half raster, extensions. The MATLAB waveforms and the C++ reader are the
  checks.
- A strict parser rejects files that other tools load. That is the purpose;
  the violations must say exactly why.
- The specification is a draft and changes. A new version is rejected by
  name until the parser learns it.
- Downstream moves from rc5 in one step. The migration guide must cover both
  rc5 and rc6 names.
