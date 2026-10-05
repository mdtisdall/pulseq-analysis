# Tests

This file describes each check that CI runs. CI runs `scripts/check` in the
`ci` Nix devShell on every pull request and on every push to `main`. The `ci`
devShell has only the tools that `scripts/check` uses. Run the same checks
locally with:

```bash
nix develop --command scripts/check
```

Each check below has:

- **Checks:** one statement of what the check makes sure of.
- **How:** the logic of the check, in words.
- **Assumptions:** what the check takes as true without testing it, and what
  it does not cover. A check can pass while one of its assumptions is false.

When you add, remove or change a test, update this file in the same pull
request. CI fails when a test has no entry here (see
[TESTS.md coverage](#testsmd-coverage)).

Terms used below:

- **Synthetic sequences** are the small sequences in `tests/synthetic.py`,
  built with pypulseq only. They use the system limits 28 mT/m and
  150 T/m/s, RF dead time 100 µs, RF ringdown 20 µs and ADC dead time 10 µs.

Contents:

1. [Static checks](#1-static-checks)
2. [Tests](#2-tests): the package; the shared sequence helpers, the sequence
   index, the raster sampler and the sequence extensions; the analyses (PNS and
   the PNS levels, and the gradient limits); the series; the analyses and their registry;
   the gradient spectrum; the kept results

---

## 1. Static checks

### Dependency install

**Checks:** The locked dependencies install.

**How:** uv installs the project and its dependencies at the exact versions in
`uv.lock`, into the project environment. Every later step uses this
environment.

**Assumptions:**

- The install uses `--frozen`, which reads `uv.lock` and does not compare it to
  `pyproject.toml`. CI does not fail when `pyproject.toml` has a dependency
  change that is not in `uv.lock`.
- The Python version is the one from the Nix devShell (3.12). No other version
  is tested.

### Lint

**Checks:** The Python code has no findings from the rules that ruff turns on
by default.

**How:** ruff checks every Python file in the repository. The project sets
only the line length (100), so ruff uses its default rule set. `uv.lock` has
ruff 0.16.9.

**Assumptions:**

- The rule set is ruff's default, not a choice that the project makes. The
  project does not pin ruff in `pyproject.toml`, so an update of ruff in
  `uv.lock` can add or remove rules.
- Some common rules are not in the default set, so ruff does not report them:
  line length (E501), function complexity (C901), `print` calls (T201),
  `assert` statements (S101), too many arguments (PLR0913) and magic numbers
  (PLR2004). The format check wraps most long lines of code, but it does not
  split long strings or comments, so a line can still be longer than 100.
- ruff does not check types. No type checker runs in CI.

### Format

**Checks:** The Python code is formatted as ruff format would format it.

**How:** ruff format runs in check mode. It fails when any file would change.
The line length is 100.

**Assumptions:** None.

### Shell scripts

**Checks:** The shell scripts have no shellcheck warnings or errors.

**How:** shellcheck runs on `scripts/check` and the hook
`.claude/hooks/block-main-writes.sh`, at severity warning and above.

**Assumptions:**

- Only these two files are checked. A new shell script is not checked until
  it is added to the list in `scripts/check`.
- Info and style findings do not fail the check.

### TESTS.md coverage

**Checks:** TESTS.md has exactly one entry for each test that pytest collects,
in the section of that test's file, and no entry for a test that does not
exist.

**How:** In `scripts/check`, the pytest run writes the ID of each test that
it collects to a temporary file (option `--collected-tests-file`, from
`tests/conftest.py`), and the check reads that file (option `--collected`).
When the check runs alone, without `--collected`, it runs
`pytest --collect-only`, which lists the tests without running them. Each
pytest test is identified by its file name and its function name. A
parametrized test is one test. The check also reads each file that matches
`tests/js/test_*.js` as a file of JavaScript tests. This repository has no
JavaScript tests, so the check finds none. The check reads TESTS.md and takes
each level-4 heading that is a test name in backticks as an entry. The entry
belongs to the test file named in the nearest level-3 heading above it. The
check then reports:

- each pytest test with no entry in its file's section;
- each entry for a test that does not exist in that file;
- each test with more than one entry;
- each entry that is not under a test file's heading.

It fails if it reports anything, if pytest cannot collect the tests, or if it
cannot read the file of test IDs.

**Assumptions:**

- In `scripts/check`, the check runs after pytest, although this file lists
  it before the tests. When a test fails, `scripts/check` stops, and the
  check does not run.
- In `scripts/check`, pytest runs on the `tests` directory without other
  test selection (no `-k`), so the file of test IDs lists every test.
- Test files are identified by file name only, without the directory. The
  check fails if two test files have the same name.
- The check looks only at the headings. It does not check that an entry has
  its Checks, How and Assumptions parts, or that the text is still correct
  after a test changes.
- A level-4 heading that is not a test name in backticks (for example a
  description of shared test sequences) is not an entry and is ignored.

---

## 2. Tests

### 2.0 The package (`test_package.py`)

`test_package.py` tests that the package installs and imports, and that the
installed package has the version that `pyproject.toml` gives.

#### `test_the_package_imports_and_has_the_version_of_pyproject`

**Checks:** The package `pulseq_analysis` imports from `src/pulseq_analysis` of
this repository, and the installed distribution `pulseq-analysis` has the
version that `pyproject.toml` gives in `[project]`.

**How:** The test imports `pulseq_analysis` and compares the directory of the
imported package with `src/pulseq_analysis` of the repository root. It reads `pyproject.toml` from the
repository root with `tomllib` and takes the value of `[project] version`. It
asks `importlib.metadata` for the version of the distribution `pulseq-analysis`
and compares the two versions.

**Assumptions:**

- The metadata of the distribution `pulseq-analysis` is the metadata of the
  editable install that `uv sync` makes. The test does not check where the
  metadata comes from.
- The version in the installed metadata is the version from the time of the
  last `uv sync`. After a change to the version in `pyproject.toml`, the test
  fails until `uv sync` runs again.

#### `test_the_package_has_no_gamma`

**Checks:** No module of the package has a gyromagnetic ratio. No module has an
attribute with "gamma" in its name, and no function or method that the package
defines has a parameter with "gamma" in its name. Each value is in the units of
pypulseq and the caller divides by the magnitude of gamma (`docs/usage.md`
section 8).

**How:** The test imports each module of `pulseq_analysis` with `pkgutil` and
`importlib`. For each module, it checks the names in `dir(module)`. It then
takes each function and each method of each class that the module defines,
private ones too, and checks the names of the parameters that
`inspect.signature` gives. It skips the objects with a `__module__` outside the
package, such as numpy and pypulseq objects, and the objects whose signature
cannot be read. The comparison ignores the case.

**Assumptions:**

- The test finds only the functions in the namespace of a module and in the
  namespace of its classes. It does not find a function that a call makes at
  run time, or a function nested in another function.
- A parameter that has a different name for the gamma, for example `gyro`, is
  not found.

### 2.1 Shared sequence helpers (`test_seq_utils.py`)

`test_seq_utils.py` tests the shared helpers in `seq_utils.py` that the
report cards use to read a pypulseq sequence: the RF resampling helper and
the gradient corner/sample helper. It also checks that the synthetic
sequences in `tests/synthetic.py` are legal Pulseq.

#### `test_time_tolerance`

**Checks:** The time tolerance is 1 ns.

**How:** The test compares `seq_utils.TIME_TOLERANCE` with 1e-9.

**Assumptions:** None.

#### `test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system`

**Checks:** `GAMMA_1H` from `tests/synthetic.py` is equal to the gamma of `SYSTEM`, and both
are 42.576 MHz/T.

**How:** The test compares `GAMMA_1H` with `SYSTEM.gamma` and with the literal value. The tests
convert the values of the package with `GAMMA_1H`. The test sequences convert their mT/m
limits with the gamma of `SYSTEM`, so the two must be equal.

**Assumptions:** `SYSTEM` leaves `gamma` at the default of pypulseq's `Opts`.

#### `test_hold_samples_keeps_uniform_shapes_unchanged`

**Checks:** An RF shape with uniform samples that fill the pulse duration is
used as it is.

**How:** The test makes a 3 ms sinc pulse. It checks that the sample times
are uniform and that the number of samples times the step is the pulse
duration. It then gets the held samples, and checks that the sample time and
the sample values are the same as the pulse's own.

**Assumptions:**

- pypulseq's sinc pulse has uniform samples that fill its duration. The test
  checks that before it tests the helper.

#### `test_hold_samples_interpolates_a_block_pulse`

**Checks:** A block pulse, which has samples only at its start and end, is
resampled on the RF raster with the correct number of samples, the correct
duration, and the correct flip angle.

**How:** The test makes a 2 ms, 60° block pulse. It checks that the pulse has
only two samples, which do not fill the duration. It gets the held samples on
the RF raster, and checks that the number of samples is the duration divided
by the raster, that the samples fill the duration, and that the sum of the
samples times the sample time is 60° as a fraction of a cycle (1/6).

**Assumptions:**

- The flip angle in cycles is the sum of B1 (Hz) × dt, which is correct for a
  pulse with constant phase.

#### `test_gradient_offsets_trapezoid`

**Checks:** `gradient_offsets` gives the delay and the four corner offsets and
amplitudes of a trapezoid gradient, with the offsets relative to the delay
(not including it).

**How:** The test makes an x trapezoid and calls `gradient_offsets`. It
compares the returned delay with the gradient's own `delay`, the returned
offsets with the running sum of the rise time, the flat time and the fall
time (starting at zero), and the returned amplitudes with zero, the plateau
amplitude twice, and zero.

**Assumptions:** None.

#### `test_gradient_offsets_arbitrary`

**Checks:** `gradient_offsets` gives the delay and the sample offsets and
amplitudes of an arbitrary gradient, with one added point at each end, at
offset 0.0 and at the shape duration, for the shape's `first` and `last`
values.

**How:** The test makes an x arbitrary gradient from a 10-point waveform and
calls `gradient_offsets`. It checks
that the first and last returned amplitudes are the gradient's `first` and
`last` values, and that the first and last returned offsets are 0.0 and the
shape duration. It checks that the interior offsets and amplitudes are the
gradient's own sample times (`g.tt`) and waveform, unchanged.

**Assumptions:**

- pypulseq's `make_arbitrary_grad` gives the shape both `first` and
  `shape_dur` by default. The test checks that before it tests the helper,
  so the case without them (used only for a shape that already has points at
  its own ends) is not covered here.

#### `test_gradient_points_matches_gradient_offsets_exactly`

**Checks:** `gradient_points(g, t0)` gives exactly `(t0 + delay) + offsets`
for the `delay` and `offsets` that `gradient_offsets(g)` returns, for both a
trapezoid and an arbitrary gradient. This is the relationship a later phase
depends on to rebuild point times from the stored offset tables.

**How:** The test is parametrized over a trapezoid and an arbitrary
gradient. For each, it calls `gradient_points` with a non-zero `t0` and
`gradient_offsets` on the same event, then compares the two with
`numpy.testing.assert_array_equal` — exact equality, not a tolerance.

**Assumptions:**

- Bit-for-bit equality is the right check here, not an approximation: the
  point in this test is that `gradient_points` is defined in terms of
  `gradient_offsets` with no room for a rounding difference to creep in.

#### `test_gradient_points_trapezoid`

**Checks:** `gradient_points` gives the four corner times and amplitudes of a
trapezoid gradient.

**How:** The test makes an x trapezoid and calls `gradient_points` with a
start time `t0`. It compares the returned times with `t0` plus the
gradient's delay plus the running sum of the rise time, the flat time and
the fall time, and compares the returned amplitudes with zero, the plateau
amplitude twice, and zero.

**Assumptions:** None.

#### `test_gradient_points_arbitrary`

**Checks:** `gradient_points` gives the sample times and amplitudes of an
arbitrary gradient, with one added point at each end for the shape's first
and last values.

**How:** The test makes an x arbitrary gradient from a 10-point waveform and
calls `gradient_points` with a start time `t0`. It checks that the first and
last returned amplitudes are the gradient's `first` and `last` values, and
that the first and last returned times are `t0` plus the delay, and `t0`
plus the delay plus the shape duration. It checks that the interior points
are the waveform samples unchanged, at `t0` plus the delay plus the
gradient's own sample times (`g.tt`).

**Assumptions:** None.

#### `test_synthetic_sequences_pass_the_timing_check`

**Checks:** Each synthetic sequence builder in `tests/synthetic.py` passes
pypulseq's timing check.

**How:** The test runs once for each of four builders — `spin_echo_sequence`,
`gre_sequence`, `empty_sequence` and `arbitrary_gradient_sequence` — builds
the sequence, calls its `check_timing` method, and asserts that the check
passes, showing the report if it does not.

**Assumptions:**

- pypulseq's timing check is trusted to cover raster alignment, RF dead time
  and ringdown, and ADC dead time before and after the ADC. This test does
  not check the report cards' own reading of the sequence, only that the
  synthetic sequences are legal Pulseq.

### 2.2 PNS levels (`test_pns_levels.py`)

`test_pns_levels.py` tests `pns_levels.py` (`docs/plans/diagram-lanes.md`, section
4.1, item 2, and section 4.2): `pns_levels`, which samples the gradients block by
block (`GradientSampler.block_samples`), runs the SAFE model of the pinned pypulseq
fork (`_safe_gwf_to_pns_chunk`) over them in chunks, and keeps only the stored level
(the minimum and the maximum of the total in fixed time bins) and the summary (the
peak, the peak time and the axis peaks), and the intervals of consecutive samples
whose total is at or above each threshold of the `thresholds_hz_per_t` argument
(`PnsInterval`, `PnsLevels.above`, a dict with one key for each threshold; the default is
no threshold); and `bin_samples_for`, which picks the bin size. A PNS value of
`pns_levels` is in Hz/T: the fraction of the stimulation limit times the magnitude of
gamma, because the model runs on the Hz/m samples and reads no gamma. The test file
defines `_LIMIT = PNS_LIMIT * GAMMA_1H`, the stimulation limit for 1H in Hz/T, and gives a
threshold or a comparison as a fraction times `_LIMIT`. The reference for most tests is
`seq.calculate_pns` of the pinned fork
(decision 6 of section 2.2 of the plan: this project does not test pypulseq itself,
only compares this library's output with pypulseq's or with its own other output).
`calc_pns` samples `seq.get_gradients()` at the file times `(k + 0.5) * dt`, which
drift off the ideal raster grid by float rounding of the block start time sums
(section 2.3, item 1, of the plan); `pns_levels` samples each block at its own local
raster times, with no such drift. Both then run the same chunk function, so a
relative 1e-6-of-peak tolerance (section 3.5, item 2, of the plan) covers the whole
difference, except for a file with a block off the gradient raster, where both
sample at file times and a relative 1e-9 suffices. `calc_pns` divides the gradients by
`seq.system.gamma` and so gives fractions: the tests divide each value of `pns_levels` by
`seq.system.gamma` before they compare it with `calc_pns`.

`pns_levels` takes the hardware of the SAFE model from one of three sources: the
example hardware (`safe_example_hw()`, with no argument), a gradient `.asc` file
(`gradient_asc`), or a pair `(struct, label)` (`hardware`), where `struct` is a SAFE
hardware struct in the form of pypulseq's `asc_to_hw`. The last tests of this section
check the `hardware` keyword against the other two sources. They compare the results
exactly: the same struct values give the same float operations.

#### `test_summary_matches_calculate_pns_within_the_fork_tolerance`

**Checks:** For a spin echo, a gradient echo, an arbitrary gradient, and a
hand-made "border" sequence (two extended-trapezoid blocks whose gradient is not
zero at the block border between them), `pns_levels`'s peak, peak time and axis
peaks equal `seq.calculate_pns`'s (example hardware) within a relative 1e-6 of the
peak, after the peak and the axis peaks are divided by `seq.system.gamma`. Also checks
`reason`, `hardware`, `asc_file`, `dt_s` and `on_raster` for the example-hardware,
on-raster case. The division is the conversion of `docs/usage.md` section 8, so this
test also tests it.

**How:** Parametrized over `spin_echo_sequence()`, `gre_sequence()`,
`arbitrary_gradient_sequence()` and `synthetic.border_sequence()` (two
`pp.make_extended_trapezoid` blocks on x, the second continuing the first's
amplitude with no step, so `add_block` accepts the junction). The reference peak,
peak time (the first sample at or above `peak * (1 - PEAK_TOLERANCE)`, as
`PnsPrediction.peak_time_s`) and axis peaks come from
`seq.calculate_pns(safe_example_hw(), do_plots=False)`. `pns_levels(seq)`'s fields
are compared with `pytest.approx`: the
peak and axis peaks (`peak_hz_per_t` and `axis_peaks_hz_per_t`, each divided by
`seq.system.gamma`) with `abs = 1e-6 * ref_peak`, the peak time (not divided) with
`abs = 1e-9` (both use the same `(k + 0.5) * dt` formula, so the same sample index gives
the same float).

**Assumptions:** None of these sequences has two samples close enough together, in
value, to flip which one the tolerance-based peak-time search finds first.

#### `test_stored_bins_match_calculate_pns_totals`

**Checks:** Each stored bin's minimum and maximum equal the minimum and the maximum
of `seq.calculate_pns`'s totals over the same samples, within the same 1e-6-of-peak
tolerance, for the same four sequences, after each value of `pns_levels` is divided by
`seq.system.gamma`.

**How:** Same parametrization and reference call as
`test_summary_matches_calculate_pns_within_the_fork_tolerance`. For each bin `i` of
`pns_levels(seq)`, `s0 = i * bin_samples`, `s1 = min(s0 + bin_samples,
levels.num_samples)` (the last bin can be shorter); the loop stops before a bin
whose `s1` is past the end of `calc_pns`'s own array (shorter than `pns_levels`'s
when a trailing block has no gradient event, for example `gre_sequence`'s TR
padding: `pns_levels` keeps sampling into the filters' own decay past where
`calc_pns` stopped, so a bin that straddles that point is not comparable). Each
compared bin's `level_min_hz_per_t[i]`/`level_max_hz_per_t[i]` (each divided by
`seq.system.gamma`) are checked against `norm[s0:s1].min()`/`.max()` with
`pytest.approx(abs = 1e-6 * levels.peak_hz_per_t / gamma)`. Asserts at least one bin was
compared.

**Assumptions:** None.

#### `test_cast_outward_bounds_every_input_value`

**Checks:** `_cast_outward` (the float32 rounding that keeps every bin's minimum and
maximum outside the float64 samples it was built from) never lands on the wrong
side of its input: the downward cast is at most the input, the upward cast is at
least the input.

**How:** 2000 uniform random float64 values in `[-1000, 1000)`
(`numpy.random.default_rng(0)`). Checks `_cast_outward(values,
down=True).astype(float64) <= values` and `_cast_outward(values,
down=False).astype(float64) >= values` elementwise, and that both results are
`float32`.

**Assumptions:** None of the 2000 values happens to already be exactly representable
in float32 for every one of them (which would make the nudging branch untested);
not arranged, only overwhelmingly likely for uniform random values.

#### `test_bin_samples_for_matches_the_formula`

**Checks:** `bin_samples_for` follows `max(floor(EXACT_MAX_S / (2 * DISPLAY_BINS) /
dt), ceil(num_samples / MAX_BINS), 1)`: 615 samples at the 10 us raster for any file
of up to 1,230,000,000 samples, and a coarser bin above that size or at a coarser
`dt`. A `pns_levels` call on a real sequence follows the same formula and gives that
many bins.

**How:** Direct calls: `bin_samples_for(0, 1e-5) == 615`,
`bin_samples_for(1_230_000_000, 1e-5) == 615`, `bin_samples_for(1_230_000_001, 1e-5)
== 616`, `bin_samples_for(2_000_000_000, 1e-5) == 1000`, `bin_samples_for(0, 2e-5) ==
307`. Then `pns_levels(gre_sequence(num_trs=6))`'s `bin_samples` is compared with
`bin_samples_for(levels.num_samples, levels.dt_s)`, and `len(levels.level_min_hz_per_t) ==
len(levels.level_max_hz_per_t)` equals the ceiling division of `num_samples` by
`bin_samples`.

**Assumptions:** None.

#### `test_result_does_not_depend_on_chunk_samples`

**Checks:** The stored level and the summary do not depend on the chunk size: exact
equality for chunks of 1, 2 and 7 bins and one chunk larger than the whole file.

**How:** `gre_sequence(num_trs=20)`, long enough that the smallest case (1 bin per
chunk) still has more than one chunk. `reference = pns_levels(seq)` (with the
`CHUNK_SAMPLES` of the module); then, for each size in `1`, `bin_samples + 1`,
`7 * bin_samples - 1` and `bin_samples * (num_samples // bin_samples + 10)`,
`monkeypatch.setattr` sets `CHUNK_SAMPLES` of `pulseq_reports.pns_levels` to it and
`pns_levels(seq)` runs again. `pns_levels` rounds the chunk up to a whole number of
bins, so the sizes give chunks of 1, 2 and 7 bins and one chunk bigger than the file.
`level_min_hz_per_t`/`level_max_hz_per_t` are compared with `numpy.array_equal`;
`peak_hz_per_t`, `peak_time_s`, `axis_peaks_hz_per_t`, `num_samples` and `bin_samples`
with `==`.

**Assumptions:** None.

#### `test_a_block_longer_than_a_chunk_does_not_depend_on_chunk_samples`

**Checks:** A block of 10,000 samples, with events on x and z and a delay before the
first one, that many chunk ends cut, gives the same result with chunks of 1 bin, of 2
bins and one chunk bigger than the file: every field of `PnsLevels`, including the
intervals of a threshold below the peak. Each chunk reads only its part of the block.

**How:** A block with a trapezoid on x (`delay` of 2000 samples), a trapezoid on z and
a delay event of 10,000 samples, then a trapezoid block on y. The threshold is `0.05 *
_LIMIT`. `CHUNK_SAMPLES` is set to `10**9` for the reference (the test checks that
four bins are fewer than 10,000 samples, and that the reference has an interval), then
to 1 and `bin_samples + 1`. `assert_levels_equal` (`tests/asserts.py`) compares each result with the
reference, every field.

**Assumptions:** None.

#### `test_one_long_delay_block_gives_the_result_of_the_same_time_in_short_blocks`

**Checks:** A trapezoid and one delay block of 1 s (more than three chunks of the real
`CHUNK_SAMPLES`) gives exactly the same result as the trapezoid and ten delay blocks of
0.1 s.

**How:** Two sequences with the same trapezoid on x. The threshold is `0.1 * _LIMIT`.
The test checks that the long sequence has more than `3 * CHUNK_SAMPLES` samples and
that the result of the short blocks has an interval. `assert_levels_equal` (`tests/asserts.py`) compares
every field. The samples of a delay are 0 in both, so the totals are equal.

**Assumptions:** None.

#### `test_no_gradients`

**Checks:** A sequence with no gradient event gives `reason=NO_GRADIENTS`, no
stored bins, a peak of 0, `peak_time_s` of `None`, zero axis peaks, no threshold (the
default, so `above == {}`), and still the example hardware and its `hw` fields.

**How:** `pns_levels(empty_sequence())`. Checks `reason`, `hardware`, `asc_file`,
the `(0,)` shape of `level_min_hz_per_t`/`level_max_hz_per_t`, `peak_hz_per_t == 0.0`,
`peak_time_s is None`, `axis_peaks_hz_per_t == {"x": 0.0, "y": 0.0, "z": 0.0}`, `hw`
against the 8 kept fields of `safe_example_hw()`, and `above == {}`.

**Assumptions:** None.

#### `test_no_gradients_gives_an_empty_tuple_for_each_threshold`

**Checks:** A sequence with no gradient event and two thresholds gives `above` with the
two keys, in the order of `thresholds_hz_per_t`, each with `()`.

**How:** `pns_levels(empty_sequence(), thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT))`.
Checks `reason`, `list(levels.above) == [_LIMIT, 0.5 * _LIMIT]` and
`levels.above == {_LIMIT: (), 0.5 * _LIMIT: ()}`.

**Assumptions:** None.

#### `test_off_raster_block_falls_back_to_sampling`

**Checks:** A file with a block that is not on the gradient raster is reported as
`on_raster=False`, and its peak, peak time and axis peaks equal `seq.calculate_pns`
within a relative 1e-9 of the peak, after the peak and the axis peaks are divided by
`seq.system.gamma` (the conversion of `docs/usage.md` section 8; tighter than the drift-based 1e-6 elsewhere in
this section, because both now sample with `GradientSampler.sample`/
`seq.get_gradients()` at the same file times; `test_sampling.py` established that
those two agree to about float rounding).

**How:** A trapezoid on x followed by `pp.make_delay(1.5 * dt)` (pypulseq's
`add_block` accepts this duration, though it is not a whole number of raster
steps). Compares `pns_levels(seq)`'s `on_raster`, `peak_hz_per_t` and `axis_peaks_hz_per_t`
(each divided by `seq.system.gamma`) and `peak_time_s` with the values from
`seq.calculate_pns(safe_example_hw(), do_plots=False)`, as in
`test_summary_matches_calculate_pns_within_the_fork_tolerance` but with
`abs = 1e-9 * ref_peak` (and `abs = 1e-9` for the peak time). It also checks
that `num_samples` is at least the length of `calculate_pns`'s result: `pns_levels`
covers the whole sequence, and `calc_pns` stops at the last gradient point.

**Assumptions:** None.

#### `test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples`

**Checks:** An off-raster sequence of more than three chunks gives the result of one
chunk (`==`, each field and each interval), and its `num_samples` is
`ceil((end_s - 1e-10) / dt)`, with `end_s` the end of `sequence_index(seq)`. A chunk
that reads the samples of the first chunk again, or a `num_samples` that rounds down,
gives another result.

**How:** `gre_sequence(num_trs=3)` and then `pp.make_delay(1.5 * dt)`, so that the
sequence is not on the raster. The hardware gives a peak of 1.5 times `_LIMIT`
(`hardware_for_peak` of `tests/pns_hardware.py`), and `thresholds_hz_per_t=(_LIMIT,)`. `monkeypatch` sets
`CHUNK_SAMPLES` to `10**9` for the reference (one chunk) and to 1 (a chunk of one bin)
for the second call. The test checks `on_raster is False`, more than three chunks, an
interval above `_LIMIT`, `got == reference`, and `num_samples`.

**Assumptions:** The sequence has an interval above `_LIMIT`.

#### `test_an_off_raster_sequence_of_more_than_one_real_chunk_matches_calculate_pns`

**Checks:** An off-raster sequence that is longer than one chunk at the real
`CHUNK_SAMPLES` has the peak, the peak time and the axis peaks of `seq.calculate_pns`,
within the tolerances of `test_off_raster_block_falls_back_to_sampling` (each value
divided by `seq.system.gamma`). The peak is in the second chunk.

**How:** A trapezoid on x (area 200), `pp.make_delay(0.35)`, a trapezoid on y (area
1000) and `pp.make_delay(1.5 * dt)`. The reference is
`seq.calculate_pns(safe_example_hw(), do_plots=False)`. The test checks
`on_raster is False`, `num_samples` more than one chunk
(`bin_samples * ceil(CHUNK_SAMPLES / bin_samples)`), a peak time after the first chunk,
and then the peak, the peak time and the axis peaks.

**Assumptions:** None.

#### `test_a_sequence_below_the_limit_has_no_interval_and_one_above_it_has_some`

**Checks:** `above[_LIMIT]` is empty if and only if `peak_hz_per_t < _LIMIT`. For a
sequence above the limit, the largest interval peak equals `peak_hz_per_t`, each interval
has a peak of at least `_LIMIT` and a peak time between its start and its end, its `num_samples` is the number of
samples from its start to its end, and the intervals are in time order with at least
one sample below the limit between two of them.

**How:** `pns_levels(seq, thresholds_hz_per_t=(_LIMIT,))` for
`gre_sequence(num_trs=20)` with the example hardware has a peak below `_LIMIT` and no
interval. Then the stimulation limit of each axis is scaled with the peak of the example
hardware, so that the peak is 1.5 times `_LIMIT` (`hardware_for_peak` of `tests/pns_hardware.py`; the total is the
percent of the limit), and `pns_levels` runs with that hardware as `hardware`. The sample of a time is `round(t / dt - 0.5)`.

**Assumptions:** The sequence gives more than one interval at that peak.

#### `test_the_intervals_do_not_depend_on_chunk_samples`

**Checks:** The result, every field and so every interval, is exactly the same for a
chunk of 1 bin, for a chunk with an interval across its end (the interval is one
interval, not two), and for one chunk larger than the whole file.

**How:** `gre_sequence(num_trs=20)` with hardware that gives a peak of 3 times `_LIMIT`,
and `thresholds_hz_per_t=(_LIMIT,)`. `reference` is `pns_levels` with the `CHUNK_SAMPLES`
of the module.
The test searches the chunks of 1 to 19 bins for the first one where the last sample of
an interval is in a later chunk than its first sample, and fails if there is none. Then
`monkeypatch.setattr` sets `CHUNK_SAMPLES` of `pulseq_analysis.pns_levels` to 1, to that
size and to a size larger than the file, and the whole `PnsLevels` is compared with the
reference (`numpy.array_equal` for the arrays, `==` for the rest).

**Assumptions:** The test checks that the second size has an interval across a chunk
end and the third has none. Setting a chunk of 1 sample gives chunks of 1 bin
(`pns_levels` rounds the chunk up to a whole number of bins).

#### `test_an_interval_across_three_chunks_does_not_depend_on_chunk_samples`

**Checks:** An interval with samples in three chunks or more (the open run goes over
more than one chunk end) is the same interval with chunks of one bin and with one
chunk.

**How:** `gre_sequence(num_trs=3)` with the example hardware and
`thresholds_hz_per_t=(1e-5 * _LIMIT,)`, a threshold far below the peak. `monkeypatch`
sets `CHUNK_SAMPLES` to `10**9` for the reference and to 1 (a chunk of one bin) for the
second call. The test checks that an interval of the reference has
`last // chunk - first // chunk >= 2` (with `_sample_range`), and that the two `above`
are equal.

**Assumptions:** The interval of the threshold `1e-5 * _LIMIT` is longer than two
bins.

#### `test_the_intervals_match_the_runs_of_the_totals`

**Checks:** The start, the end, the peak, the peak time and the number of samples of
each interval equal the runs of `total >= _LIMIT` in the totals of the whole sequence, for a
sequence on the raster and for one with a block off it (the path of
`GradientSampler.sample`).

**How:** Parametrized with `gre_sequence(num_trs=20)` and `_off_raster_sequence()`, each
with hardware that gives a peak of 1.5 times `_LIMIT`, and
`thresholds_hz_per_t=(_LIMIT,)`. The test sets `CHUNK_SAMPLES` to `10**9` (one chunk) and
wraps `_chunk_total` to keep the totals it returns. It finds the runs of
`total >= _LIMIT` with `itertools.groupby`, and takes the peak as the maximum of the run
and the peak time as its first sample with that value. The expected `PnsInterval` tuple is
compared with `above[_LIMIT]` with `==` (exact).

**Assumptions:** The off-raster sequence has at least one interval at that peak.

#### `test_two_separate_intervals_are_in_time_order`

**Checks:** Two trapezoids on x with a gap of 50 ms give two intervals: the first ends
before the middle of the gap and the second starts at or after the end of the gap.

**How:** The hardware has a peak of 1.02 times `_LIMIT` for one trapezoid, so that only
the larger of the two humps of the total of a trapezoid is at or above `_LIMIT`. The
thresholds are `(_LIMIT,)`. The test checks that one
trapezoid gives one interval, then compares the two intervals of the sequence of two
trapezoids (a trapezoid, `pp.make_delay(50e-3)`, the same trapezoid) with the
trapezoid duration and the gap.

**Assumptions:** The decay of the filters after a trapezoid does not keep the total at
or above `_LIMIT` for half of the gap.

#### `test_two_thresholds_in_one_call_give_the_runs_of_two_calls`

**Checks:** `thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)` gives, for each threshold, the
intervals of the call with that one threshold, and every other field is unchanged. The
keys of `above` are `float(t)` in the order of `thresholds_hz_per_t` (the thresholds in
the other order give the keys in that order, and an `int` is the key of the equal
`float`). It holds with the normal chunk size, with chunks of 1 bin and with a chunk size
that has an interval of each threshold across a chunk end.

**How:** `gre_sequence(num_trs=20)` with hardware that gives a peak of 3 times `_LIMIT`.
`single` has one call with `thresholds_hz_per_t=(t,)` for each of `_LIMIT` and
`0.5 * _LIMIT`. The test checks that the intervals of `_LIMIT` are more than one and that
those of `0.5 * _LIMIT` have more samples in total (so the two thresholds do not give the
same runs). For each chunk size (the normal one, 1,
and for each threshold the first of 1 to 19 bins with an interval across its end, found
as in `test_the_intervals_do_not_depend_on_chunk_samples`; `monkeypatch.setattr` sets
`CHUNK_SAMPLES` of `pulseq_analysis.pns_levels`), the call with both thresholds must
have the keys `[_LIMIT, 0.5 * _LIMIT]`, the same tuple as `single` for each threshold, and
every other field equal (`assert_levels_equal` (`tests/asserts.py`) with `ignore=("above",)`). After the chunk
sizes are restored, the thresholds in the other order give the keys in that order and the
same tuples, and the `int` `round(_LIMIT)` in place of `_LIMIT` (the test checks that it
equals `_LIMIT` as a float) gives the key `_LIMIT` as a `float`.

**Assumptions:** The intervals of 1.0 and of 0.5 each cross a chunk end for a chunk of 1
to 19 bins (`_chunk_across_an_interval` fails if there is none).

#### `test_pns_levels_refuses_bad_thresholds_before_any_work`

**Checks:** `pns_levels` raises `ValueError` for `thresholds_hz_per_t` that is not a tuple
(a list, a float, `None`), has a `bool`, has an element that is not an `int` or a `float`
(a string, `None`, a NumPy `float32`), has an element that is not finite (NaN, the two
infinities, an `int` too large for a float) or not above 0 (0 and a negative number), or
has two elements that are equal as floats (`(1.0, 1.0)`, `(1, 1.0)` and a pair that is not
next to each other). The refusal is before the sequence is read.

**How:** Parametrized on the value. The test replaces `refuse_rotations` and
`sequence_index` of `pulseq_analysis.pns_levels` with functions that raise
`RuntimeError`, and calls `pns_levels(spin_echo_sequence(), thresholds_hz_per_t=value)` inside
`pytest.raises(ValueError, match="threshold")`. A `RuntimeError` would show that the work
started before the check. The empty tuple is not a case: it is valid (the default).

**Assumptions:** `pns_levels` calls `refuse_rotations` and `sequence_index` as module
globals, so the replacements are used when it reads the sequence.

#### `test_asc_hardware_file_is_used_for_the_levels`

**Checks:** `pns_levels` reads the hardware name and the 8 kept fields of each axis
from a given gradient .asc file, instead of the example hardware, and its stored
level and summary then equal the default (example-hardware) call exactly, because
this .asc file encodes the example hardware's own numbers.

**How:** The `write_gradient_asc` fixture of `tests/conftest.py` (not confidential
data: real .asc files are confidential, so this one is built from pypulseq's own public
`safe_example_hw()`) writes an `asCOMP.tName` line and the `flGSWDTau*`,
`flGSWDA*`, `flGSWDStimulationLimit*`/`Threshold*` and `flGScaleFactor*` fields for
each axis. `pns_levels(spin_echo_sequence(), path)`'s `hardware`, `asc_file` and
`hw` are checked, then its `level_min_hz_per_t`, `level_max_hz_per_t`, `peak_hz_per_t` and
`peak_time_s` are compared with a plain `pns_levels(seq)` call (`numpy.array_equal` for the arrays,
`==` for the scalars).

**Assumptions:** None.

#### `test_pns_levels_refuses_rotations`

**Checks:** `pns_levels` raises `NotImplementedError` for a sequence with a
rotation library, as `gradient_limits` does.

**How:** `gre_sequence(num_trs=2)` with a non-empty `rotation_library` (the
`with_rotation_library` helper of `tests/synthetic.py`), inside
`pytest.raises(NotImplementedError, match="rotation extension")`.

**Assumptions:** None.

#### `test_pns_levels_is_a_frozen_dataclass`

**Checks:** `pns_levels` returns a `PnsLevels` instance, and an assignment to a field
raises `dataclasses.FrozenInstanceError`.

**How:** `isinstance(pns_levels(spin_echo_sequence()), PnsLevels)`, then
`levels.num_samples = 0` in `pytest.raises(dataclasses.FrozenInstanceError)`. A smoke
test of the interface; the other tests of this section check individual fields.

**Assumptions:** None.

#### `test_the_arrays_of_the_levels_are_read_only`

**Checks:** `level_min_hz_per_t` and `level_max_hz_per_t` are read-only, also for a
sequence without gradients. A conversion to a new array works.

**How:** The test runs for the synthetic spin echo and for a sequence without gradients
(the two arrays are empty). Each array must have `flags.writeable` off, and a change in
place (`a *= 100`) must raise `ValueError`. Then `levels.level_max_hz_per_t * 100` must
give a writable array, and `levels.level_max_hz_per_t` must not change.

**Assumptions:** None.

#### `test_levels_compare_by_value`

**Checks:** `==` compares two `PnsLevels` by the values of their fields, also with more
than one bin, where the `__eq__` of `dataclasses` raises `ValueError`. A `PnsLevels` is
not hashable.

**How:** The test calls `pns_levels` on a GRE sequence of 4 TRs with two thresholds
(the stimulation limit and half of it), and asserts that the level has more than one bin.
A second call must give another object that is equal. A `pickle` round trip and
`copy.deepcopy` must give equal objects (the copies are writable, and the flag does not
count). These must not be equal:

- the result with one bin of `level_max_hz_per_t` moved up by one float32 step
  (`dataclasses.replace`);
- the result with the thresholds in the other order: its `above` is equal as a dict, but
  the order of its keys differs;
- a string.

`hash` must raise `TypeError`.

**Assumptions:** None.

#### `test_hardware_with_the_example_struct_gives_the_default_levels`

**Checks:** `pns_levels(seq, hardware=(safe_example_hw(), label))` gives the levels of
`pns_levels(seq)`, except `hardware`, which is the label: `asc_file` is None, and each
other field is exactly equal.

**How:** For `spin_echo_sequence()` (on the raster) and for a sequence with a block off
the raster, the test calls both and compares each field of the `PnsLevels` but
`hardware` (`numpy.array_equal` for the arrays, `==` for the rest).

**Assumptions:** None.

#### `test_hardware_from_an_asc_file_gives_the_levels_of_the_file`

**Checks:** `pns_levels(seq, hardware=(asc_to_hw(read_gradient_asc(path)), label))`
gives the levels of `pns_levels(seq, gradient_asc=path)`, except `hardware` (the label)
and `asc_file` (None).

**How:** The `write_gradient_asc` fixture of `tests/conftest.py` writes the `.asc` file (the
plain layout; `test_pns.py` tests the layout of a scanner file). The test compares each
field but the two with `numpy.array_equal` and `==`.

**Assumptions:** None.

#### `test_pns_levels_refuses_both_gradient_asc_and_hardware`

**Checks:** `pns_levels` with `gradient_asc` and `hardware` together raises
`ValueError`.

**How:** `pns_levels(spin_echo_sequence(), gradient_asc=path, hardware=(safe_example_hw(),
"LABEL"))` inside `pytest.raises(ValueError, match="not both")`.

**Assumptions:** None.

#### `test_the_levels_do_not_depend_on_the_gamma_of_the_system`

**Checks:** The same waveform in Hz/m, in a sequence of `SYSTEM` and in one of a copy of
`SYSTEM` with another gamma, gives exactly equal levels in every field, including the
intervals. The model runs on the Hz/m samples and reads no gamma.

**How:** `waveform_sequence` (`tests/synthetic.py`) builds a trapezoid on x and an arbitrary gradient on y, each
with an explicit amplitude in Hz/m (the arbitrary gradient has `first=0.0, last=0.0`), in
three blocks. One sequence has `SYSTEM`, and the other has `copy.copy(SYSTEM)` with
`gamma = 0.9 * SYSTEM.gamma`. The hardware gives a peak of 1.5 times `_LIMIT`
(`hardware_for_peak` of `tests/pns_hardware.py`), and `thresholds_hz_per_t=(_LIMIT,)`. The test checks that the two
gammas differ, that there is no reason and that `above[_LIMIT]` is not empty. Then
`assert_levels_equal` (`tests/asserts.py`) with `ignore=()` compares the two results.

**Assumptions:** None.

#### `test_the_levels_divided_by_the_gamma_of_the_system_are_the_fractions_of_calculate_pns`

**Checks:** For a sequence whose `seq.system.gamma` is not the gamma of 1H, the peak and
the axis peaks of `pns_levels`, divided by `seq.system.gamma`, and its peak time equal
`seq.calculate_pns` within a relative 1e-6 of the peak. The peak divided by the gamma of
1H does not equal it. Thus the conversion of `docs/usage.md` section 8 uses the gamma of
the caller.

**How:** The sequence of `waveform_sequence` (`tests/synthetic.py`) with a copy of `SYSTEM` with
`gamma = 0.9 * SYSTEM.gamma`. The reference peak, peak time and axis peaks come from
`seq.calculate_pns(safe_example_hw(), do_plots=False)`, as in
`test_summary_matches_calculate_pns_within_the_fork_tolerance`, with the same tolerances.
The test also checks that `peak_hz_per_t / GAMMA_1H` is not within that tolerance of the
reference peak.

**Assumptions:** The two gammas give peaks that differ by more than the tolerance (a
factor of 0.9 does).

#### `test_the_levels_of_a_negated_waveform_are_equal`

**Checks:** The same sequence with each amplitude times -1 gives exactly equal levels in
every field, including the intervals of two thresholds. The model of `-g` is equal to the
model of `g`, bit for bit.

**How:** `waveform_sequence(SYSTEM)` and `waveform_sequence(SYSTEM, sign=-1.0)` (`tests/synthetic.py`), with the
hardware of a peak of 1.5 times `_LIMIT` and `thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`.
The test checks that each threshold has intervals, then compares the two results with
`assert_levels_equal` (`tests/asserts.py`) and `ignore=()`.

**Assumptions:** None.

#### `test_the_default_has_no_thresholds`

**Checks:** `pns_levels(seq)` has `above == {}`, and `thresholds_hz_per_t=()` gives the
same result in every field. This is also so with hardware for a peak above the limit.

**How:** `gre_sequence(num_trs=4)`, with the example hardware and with the hardware of a
peak of 1.5 times `_LIMIT`. For each, the test calls `pns_levels` with no threshold argument
and with `thresholds_hz_per_t=()`, checks `above == {}`, and compares the two results with
`assert_levels_equal` (`tests/asserts.py`) and `ignore=()`.

**Assumptions:** None.

### 2.3 Sequence extensions (`test_extensions.py`)

`test_extensions.py` tests `extensions.refuse_rotations`, the guard that
`cards/spectrum.py`, `cards/pns.py` and `cards/gradient_limits.py` call
before they read any gradient. Task 6.1 of
`docs/plans/diagram-event-table.md` found that pypulseq 1.5.0.post1 cannot
make a rotation and that its `Sequence.read` raises `ValueError` for a
`.seq` file with a rotation section. This file therefore makes its own
rotation sequences by hand, the way pypulseq draft PR #372 stores a
rotation: a `rotation_library` event library on the `pp.Sequence`, a
`"ROTATIONS"` entry in `seq.extension_string_idx`, or, for the one test that
checks a `.seq` file directly, an `[EXTENSIONS]` section and an `extension
ROTATIONS` section written into the file text after `pp.Sequence.write`.

#### `test_refuse_rotations_accepts_synthetic_sequences`

**Checks:** `refuse_rotations` raises nothing for each synthetic sequence
builder in `tests/synthetic.py`: none of them uses the rotation extension.

**How:** The test is parametrized over `spin_echo_sequence`, `gre_sequence`,
`arbitrary_gradient_sequence` and `empty_sequence`. For each, it builds the
sequence and calls `refuse_rotations` on it.

**Assumptions:** None.

#### `test_refuse_rotations_raises_for_a_rotation_library`

**Checks:** `refuse_rotations` raises `NotImplementedError`, with "rotation
extension" in the message, for a sequence with a non-empty
`rotation_library`.

**How:** The test builds a `gre_sequence`, sets its `rotation_library` to a
new `EventLibrary` holding one scalar-first unit quaternion (the format PR
#372 uses), and calls `refuse_rotations` inside `pytest.raises`.

**Assumptions:** None.

#### `test_refuse_rotations_raises_for_a_rotations_extension_type`

**Checks:** `refuse_rotations` raises `NotImplementedError`, with "rotation
extension" in the message, for a sequence that has registered the
`"ROTATIONS"` extension type.

**How:** The test builds a `gre_sequence`, calls
`seq.set_extension_string_ID("ROTATIONS", 1)` (as PR #372's `Sequence.read`
does while reading a file with a rotation section), and calls
`refuse_rotations` inside `pytest.raises`.

**Assumptions:** None.

#### `test_refuse_rotations_ignores_an_empty_rotation_library`

**Checks:** A `rotation_library` attribute that exists but holds no data is
not a rotation: `refuse_rotations` raises nothing.

**How:** The test builds a `gre_sequence`, sets its `rotation_library` to a
new, empty `EventLibrary`, and calls `refuse_rotations` on it.

**Assumptions:** None.

### 2.4 Sequence index (`test_seq_index.py`)

`test_seq_index.py` tests `seq_index.py` (section 4.1 of
`docs/plans/cards-at-scale.md` of pulseq-reports): the dense RF, gradient and ADC event numbering of
`sequence_index`, its block times, its dtypes and its cache; `block_cache_off`; and
`rf_events`, `grad_events` and `adc_events`, which read each unique event one time with
the block cache off. The
reference numbering, `_reference_index`, is a plain loop over the blocks with one dict
for each event kind: the loop that `diagram_data.diagram_tables` had before it used the
index. Its `*_first` arrays hold play indexes, as `SequenceIndex` does (the old loop
kept block ids). The tests load `build_repeating` and `build_worst` from
`tests/scale_sequences.py`.

#### `test_dense_columns_and_first_arrays_match_the_reference_numbering`

**Checks:** `sequence_index`'s `rf`, `gx`, `gy`, `gz` and `adc` columns, `rf_first`,
`grad_first`, `grad_first_axis`, `adc_first` and `block_id` equal `_reference_index`'s,
for a synthetic spin echo, gradient echo, empty and arbitrary-gradient sequence, and
for `build_repeating`/`build_worst` at 50 TRs (250 blocks).

**How:** The test is parametrized over the four synthetic builders and two lambdas
wrapping `build_repeating(50)`/`build_worst(50)`. For each, it builds the sequence,
computes `sequence_index(seq)` and `_reference_index(seq)`, and compares every one of
those nine arrays with `numpy.array_equal` (the dense columns cast to `int64` first,
since `sequence_index` narrows their dtype while the reference always uses `int64`).

**Assumptions:** None.

#### `test_grad_dense_numbering_follows_gx_then_gy_then_gz_within_a_block`

**Checks:** The dense numbering of gradient events follows gx before gy before gz
within one block, and reusing an already-numbered event on a different axis of a later
block does not add a new dense index, with the expected numbers worked out by hand.

**How:** The test builds a 3-block sequence by hand: block 0 has only a gz trapezoid;
block 1 has a gx and a gy trapezoid, each a different amplitude; block 2 reuses block
0's gz trapezoid object (a shallow copy with its `channel` changed to `"x"`) on gx. It
checks `index.gx`, `gy`, `gz`, `grad_first` and `grad_first_axis` against the
hand-worked values, then checks that `grad_events` yields the three events in dense
order 1, 2, 3 with the expected amplitudes (1e5, 2e5, 3e5).

**Assumptions:**

- pypulseq's gradient library keys an event by its shape and amplitude data, not by
  the channel it is later read from, so the same trapezoid object can be reused on a
  different axis and keep the same library id. This was checked directly against
  `seq.block_events` and `seq.grad_library` while writing this test; the test itself
  then relies on it to make the hand-worked expected numbers correct.

#### `test_start_s_is_the_sequential_sum_and_end_s_is_its_final_value`

**Checks:** `index.start_s` is the sequential sum of the block durations from 0.0,
`index.end_s` is that sum's final value, and `index.duration_s` is
`seq.block_durations` in play order.

**How:** The test builds `build_repeating(50)`, computes `sequence_index(seq)`, and
independently walks `seq.block_events.keys()` with a running total `t` (starting at
0.0, recording `t` before adding each block's own duration from
`seq.block_durations`). It compares `index.start_s` to that running list with
`numpy.array_equal`, `index.end_s` to the final `t` with `==`, and `index.duration_s`
to a plain array of the `seq.block_durations` values in play order with
`numpy.array_equal`.

**Assumptions:** None.

#### `test_dtype_is_uint8_for_a_sequence_with_few_unique_events`

**Checks:** For a sequence with 255 or fewer unique events of each kind, every one of
`sequence_index`'s dense columns (`rf`, `gx`, `gy`, `gz`, `adc`) has dtype `uint8`.

**How:** The test builds `gre_sequence()` (the default 4 TRs), checks that
`rf_first`, `grad_first` and `adc_first` each have at most 255 entries, and checks the
dtype of each of the five dense columns.

**Assumptions:** None.

#### `test_dtype_widens_to_uint16_past_255_unique_gradient_events`

**Checks:** Once a sequence has more than 255 unique gradient events, `gx`, `gy` and
`gz` widen to `uint16`.

**How:** The test builds `build_repeating(260)`. `build_repeating`'s phase-encode
table has 256 amplitudes (`PE_STEPS`), so 260 TRs give more than 255 unique gradient
events overall (the phase-encode events, plus the readout and the spoiler, each reused
every TR). It checks that `grad_first` has more than 255 entries and that `gx`, `gy`
and `gz` have dtype `uint16`.

**Assumptions:**

- `build_repeating`'s phase-encode table size (`PE_STEPS = 256` in
  `tests/scale_sequences.py`) is large enough, on its own, to push the total past 255
  once combined with the readout and spoiler events; this is read from that script,
  not re-derived here.

#### `test_the_arrays_of_the_index_are_read_only_and_a_copy_is_writable`

**Checks:** Each of the twelve array fields of `sequence_index(seq)` has `writeable`
False, a write into it raises `ValueError`, and `np.array(a)` of it is writable, for a
gradient echo sequence and for an empty one.

**How:** The test is parametrized over `gre_sequence` and `empty_sequence`. It finds the
array fields with `dataclasses.fields` and `isinstance(np.ndarray)` and checks that
there are twelve. For each, it checks the flag. For an array with elements it writes
one value inside `pytest.raises(ValueError)`. It then copies the array and checks that
the copy is writable (and takes a write when it has elements). An empty array has no
element to write, so only its flag is checked.

**Assumptions:** None.

#### `test_sequence_index_of_a_sequence_with_no_blocks`

**Checks:** `sequence_index` of a `pp.Sequence` with no blocks added has `num_blocks`
0, `end_s` 0.0, and every array (`block_id`, `start_s`, `duration_s`, `rf`, `gx`,
`gy`, `gz`, `adc`, `rf_first`, `grad_first`, `grad_first_axis`, `adc_first`) empty.

**How:** The test builds `pp.Sequence(SYSTEM)` with no `add_block` call, computes
`sequence_index(seq)`, and checks `num_blocks`, `end_s`, and the size of each of the
twelve arrays.

**Assumptions:** None.

#### `test_sequence_index_is_kept_for_one_sequence_object_and_rebuilt_after_add_block`

**Checks:** `sequence_index(seq)` returns the same object on a second call for the
same sequence, and a new, longer index after `add_block`.

**How:** The test builds `gre_sequence()`, calls `sequence_index(seq)` twice and
checks the two results are the same object (`is`), then calls
`seq.add_block(pp.make_delay(1e-3))` and checks that a third call returns a different
object whose `num_blocks` is one more than the first.

**Assumptions:** None.

#### `test_block_cache_off_restores_use_block_cache_true`

**Checks:** `block_cache_off` sets `use_block_cache` to `False` inside the block, and
restores it to `True` afterward when that was the value beforehand.

**How:** The test sets `seq.use_block_cache = True`, checks it is `False` inside
`block_cache_off`, and checks it is `True` again afterward.

**Assumptions:** None.

#### `test_block_cache_off_restores_use_block_cache_false`

**Checks:** `block_cache_off` sets `use_block_cache` to `False` inside the block, and
restores it to `False` afterward when that was already the value beforehand.

**How:** The test sets `seq.use_block_cache = False`, checks it is still `False`
inside `block_cache_off`, and checks it is `False` again afterward.

**Assumptions:** None.

#### `test_block_cache_off_restores_the_old_value_after_an_exception`

**Checks:** `block_cache_off` restores the old `use_block_cache` value even when an
exception is raised inside the block.

**How:** The test sets `seq.use_block_cache = True`, raises a `ValueError` inside
`block_cache_off` (after checking it reads `False` there), catches it with
`pytest.raises`, and checks `use_block_cache` is `True` again afterward.

**Assumptions:** None.

#### `test_block_cache_off_does_not_remove_blocks_already_in_the_cache`

**Checks:** `block_cache_off` does not remove a block that was already in
`seq.block_cache` before it ran.

**How:** The test builds `gre_sequence()`, calls `seq.get_block` on the first block id
to populate the cache, checks it is in `seq.block_cache`, runs an empty
`block_cache_off` block, and checks the block is still in `seq.block_cache` afterward.

**Assumptions:** None.

#### `test_rf_events_reads_each_unique_event_once_with_the_cache_off`

**Checks:** `rf_events` calls `seq.get_block` exactly once for each unique RF event,
with the block cache off during every call and restored afterward; it yields dense
indexes 1 to K in order; and each yielded event equals the same block's `rf` event
read separately.

**How:** The test builds `spin_echo_sequence()` (two distinct RF events), wraps
`seq.get_block` with a counting wrapper (monkeypatched onto the instance) that also
records `seq.use_block_cache` at each call, sets `seq.use_block_cache = True`, and
calls `rf_events(seq, index)`, collecting its results. It checks the call count
against the number of unique first-use blocks (`numpy.unique(index.rf_first).size`),
that every recorded cache flag is `False`, and that `use_block_cache` is `True` again
afterward. It checks the yielded dense indexes are 1 to K in order, and, for each
result, that its `delay`, `type` and `signal` equal the `rf` attribute of
`seq.get_block(block_id)` read again through the saved, unwrapped `get_block`.

**Assumptions:** None.

#### `test_grad_events_reads_each_unique_first_use_block_once_with_the_cache_off`

**Checks:** `grad_events` calls `seq.get_block` exactly once for each distinct
first-use block, not once for each unique gradient event, when two axes of one block
are both first uses; the block cache is off during every call and restored afterward;
the yielded dense indexes are 1 to K in order; and each yielded event equals the
corresponding axis attribute of that block, read separately.

**How:** The test builds a 3-block sequence where block 1 introduces both a gx and a
gy event (so it is the first-use block of two dense indexes at once), wraps
`seq.get_block` as in the RF test, and calls `grad_events(seq, index)`. It checks the
call count is 2 (the two distinct first-use blocks, not the three dense events), that
every recorded cache flag is `False`, and that `use_block_cache` is restored to
`True`. It checks the yielded dense indexes are 1, 2, 3 in order, and, for each, that
its `delay`, `type` and `amplitude` equal the `gx`/`gy`/`gz` attribute (picked by
`grad_first_axis`) of that block, read separately with the saved, unwrapped
`get_block`.

**Assumptions:** None.

#### `test_adc_events_reads_each_unique_event_once_with_the_cache_off`

**Checks:** `adc_events` calls `seq.get_block` exactly once for the sequence's one
unique ADC event (reused every TR), with the block cache off during the call and
restored afterward, and the yielded event equals that block's `adc` attribute read
separately.

**How:** The test builds `gre_sequence(num_trs=5)`, whose ADC event is the same
object reused every TR, and repeats the wrapper technique of the RF and gradient
tests. It checks the call count is 1, that the recorded cache flag is `False`, that
`use_block_cache` is restored to `True`, and that the yielded event's `delay`,
`num_samples` and `dwell` equal the `adc` attribute of that block read separately.

**Assumptions:** None.

### 2.5 Raster sampler (`test_sampling.py`)

`test_sampling.py` tests `sampling.py` (section 4.3 of
`docs/plans/cards-at-scale.md` of pulseq-reports): `GradientSampler`, which gives the gradient waveform of one axis at sorted times, from
the sequence index and the unique gradient events. The reference is pypulseq's
`seq.get_gradients()`: `_assert_matches_pypulseq` compares `sample(axis, t)` with the
`PPoly` of each axis at the same times, within a relative 1e-12 and an absolute 1e-12
times the largest |value| of the reference (section 3.5, item 2, of the plan). They are
not bit-exact: `seq_utils.gradient_offsets` adds a trapezoid's corner times in a
different order than pypulseq's `waveforms()`, and `PPoly` evaluates a line segment with
a different formula than `numpy.interp`. The comparison checks `GradientSampler`, not
pypulseq.

#### `test_whole_file_matches_pypulseq_for_synthetic_sequences`

**Checks:** For each of the four synthetic sequence builders (a spin echo, a gradient
echo, the arbitrary gradient, and the empty sequence), `GradientSampler.sample` gives
the same three-axis waveform as `seq.get_gradients()`, sampled at the raster centres
of the whole file.

**How:** Parametrized over `spin_echo_sequence()`, `gre_sequence()`,
`arbitrary_gradient_sequence()` and `empty_sequence()`. For each, `t` is
`(k + 0.5) * grad_raster_time` for `k` in `range(ceil(duration / raster))`, with
`duration` the sequence index's `end_s`; the test compares all three axes against
`seq.get_gradients()` with `_assert_matches_pypulseq`.

**Assumptions:**

- None of these raster-centre times falls within `get_gradients()`'s excluded 1e-12 s
  band around the first or last point of an axis (the `teps` zero points it adds); this
  was not arranged, only observed to hold for these four sequences.

#### `test_subrange_that_cuts_blocks_matches_pypulseq`

**Checks:** A sample range that starts in the middle of one block and ends in the
middle of another gives the same waveform as `seq.get_gradients()` on all three axes,
including an axis whose only event in the file is entirely before the range.

**How:** Builds `gre_sequence(num_trs=1)` (5 blocks: RF, phase-encode on y, readout on
x with an ADC, spoiler on z, delay). `t` is 500 evenly spaced points from the middle of
block 2 (the readout, which the range cuts) to the middle of block 4 (the delay, after
the spoiler); the phase-encode event of block 1 is entirely before this range, so it
also checks that gy is 0 for the rest of the file after its one event. Compares with
`_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_subrange_inside_a_gap_matches_pypulseq`

**Checks:** A sample range entirely inside a gap between two gradient events on the
same axis (a block with no event of its own) still gives the pypulseq value: a
straight line between the earlier event's last point and the later event's first
point.

**How:** Builds a trapezoid on x, a 2 ms delay block, and a second trapezoid on x. `t`
is 200 evenly spaced points strictly inside the delay block, 50 µs in from each edge.
Compares with `_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_range_across_a_step_and_a_gap_equals_the_same_slice_of_the_whole_grid`

**Checks:** `GradientSampler.sample` of each sub-range of a sorted grid of times, around
a step at a block junction and in a gap after it, gives exactly the matching slice of
`sample` of the whole grid. A range that starts in the gap uses the last point of the
event before the gap, and a range that ends in the gap uses the first point of the
event after it.

**How:** `_step_then_gap_sequence` has four blocks with events on x: the rise and half
of the flat top of a trapezoid (area 1000), the rest of the flat top and the fall
(`make_extended_trapezoid`), `make_delay(2e-3)` (the gap), and a trapezoid (area
-500). The second block starts `0.5 * max_slew * grad_raster_time` below the end of the
first (a step that `add_block` accepts) and ends at the same value above 0, so the
waveform in the gap is not 0. The grid has 28 times: steps of half a raster time around
the junction, the start of the gap and the start of the last trapezoid, and 7 times in
the gap. The test checks that the 7 or more values in the gap are not 0, then compares
`sample("gx", t[i:j])` with `whole[i:j]` (`numpy.array_equal`) for each of the 406
pairs `i < j`.

**Assumptions:** With a last value of 0 for the second block, the gap is 0 with and
without the neighbour events, and the test cannot find their removal. The value that is
not 0 lets it.

#### `test_single_sample_matches_pypulseq`

**Checks:** `sample` gives the pypulseq value for a `t` array of length 1.

**How:** Builds `gre_sequence(num_trs=1)`, samples at one time (the middle of the
readout block), and compares with `_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_amplitude_continues_across_a_block_junction`

**Checks:** Two extended trapezoids that together make one trapezoid, split into two
blocks at the middle of the flat top so the amplitude continues unchanged from one
block into the next, give the same waveform as `seq.get_gradients()` around the
junction: the join rule's dropped point does not create a spurious step.

**How:** `_junction_sequence(step_hz_per_m=0.0)` builds the two extended trapezoids
from the rise, flat and fall of one area-1000 trapezoid, split at the middle of the
flat top, and returns the junction time. `t` is 41 points evenly spaced over 40
gradient-raster periods centred on the junction. Compares with
`_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_tolerated_step_at_a_block_junction_matches_pypulseq`

**Checks:** A step at a block junction that is inside what pypulseq's `add_block`
accepts (up to `max_slew * grad_raster_time`) still gives the same waveform as
`seq.get_gradients()`: the join rule keeps the value of the earlier event at the
junction time even when the two events do not meet exactly.

**How:** Same construction as `test_amplitude_continues_across_a_block_junction`, with
`_junction_sequence`'s `step_hz_per_m` set to half of `max_slew * grad_raster_time`
instead of 0. The test does not check that `add_block` accepts the step; that is
pypulseq's own check, exercised here only because building the sequence requires it to
pass.

**Assumptions:** None.

#### `test_triangle_trapezoid_matches_pypulseq`

**Checks:** A trapezoid with no flat time (`make_trapezoid` gives `flat_time == 0.0`),
whose `gradient_offsets` therefore has two points at the same time with the same
value, gives the same waveform as `seq.get_gradients()`: the join rule's
duplicate-point removal does not change the value.

**How:** Builds a single-block sequence with one small-area trapezoid on x, asserts
`flat_time == 0.0` to confirm the construction is the intended triangle, samples the
whole file at the raster centres, and compares with `_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_sample_matches_the_added_events_for_an_oversampled_arbitrary_gradient`

**Checks:** `sample` gives the correct waveform for a file with an oversampled
arbitrary gradient (`make_arbitrary_grad(oversampling=True)`): B4 of
`docs/reviews/2026-09-28-code-review.md` (pypulseq issue #423), fixed by the project's
pypulseq pin (`pulseq-reports-pin-1`, the fix of pypulseq PR #424). The reference is not
`seq.get_gradients()`: pypulseq's `waveforms()` leaves out the first and the last point
of an oversampled gradient (a separate pypulseq bug, draft 03 of
`github.com/mdtisdall/pypulseq-issues`), so `_assert_matches_pypulseq`'s own reference
would be wrong for this event by construction, not only by the bug under test. The
reference is instead the polyline of the added events (the objects `make_*` returns,
before `add_block`), which does not depend on either pypulseq bug.

**How:** Builds three blocks with `SYSTEM` of `synthetic.py`: an oversampled ramp
(`make_arbitrary_grad("x", ..., oversampling=True)`, 21 samples at 50 % of `max_slew`
over half a raster, ending at a value that is not 0), an extended trapezoid back down to
0, and an ordinary trapezoid. The waveform is kept within the real `max_slew` by the
test itself, because `make_arbitrary_grad(oversampling=True)` checks the slew rate 4
times too leniently (pypulseq issue #421). The reference polyline is built from each
added event's own corner or sample points (`[0, *g.tt, g.shape_dur]` and `[g.first,
*g.waveform, g.last]` for the arbitrary and extended-trapezoid events, the rise/flat/fall
corners for the trapezoid), offset by each block's start (`numpy.cumsum` of
`seq.block_durations`) and the event's own delay, with a point dropped when it is not
more than 1e-9 s after the point before it (the same join rule as `GradientSampler`).
`GradientSampler.sample("gx", t)` is compared with `numpy.interp` on that polyline at
3999 points evenly spaced over the file, within an absolute 1e-12 times the peak of the
reference (`rtol=0`). Before the pin's fix, this test's own error is about 40 % of the
peak (checked against a pypulseq checkout at the old pin, `20b9e5e`).

**Assumptions:**

- The pin (`pulseq-reports-pin-1`) has the fix of pypulseq PR #424. A pypulseq without
  it fails this test: checked against a checkout of the old pin (`20b9e5e`).

#### `test_axis_without_events_is_zero`

**Checks:** An axis with no gradient event anywhere in the file (`get_gradients()`
gives `None` for it) samples to exactly 0 at every time.

**How:** Builds `spin_echo_sequence()` (gx and gy only), asserts
`seq.get_gradients()[2] is None` to document that gz has no event, samples gz at the
raster centres of the whole file, and checks the result against `numpy.zeros` with
`numpy.testing.assert_array_equal` (an exact check, not a tolerance).

**Assumptions:** None.

#### `test_zero_before_the_first_event_and_after_the_last`

**Checks:** The waveform is exactly 0 before the first gradient event of the file and
after the last one.

**How:** Builds a delay block, one trapezoid on x, and a second delay block. Samples
50 points inside the first delay block (before the event) and 50 points inside the
second delay block (after the event), and checks both against `numpy.zeros` exactly.

**Assumptions:** None.

#### `test_empty_sequence_is_zero_for_any_t`

**Checks:** A sequence with no gradient event on any axis gives exactly 0 for any `t`,
including a time past the sequence's own duration.

**How:** Builds `empty_sequence()` (one delay block; no RF, gradients or ADC). Samples
all three axes at `t = [0.0, 1e-3, 5.0]` (5.0 s is far past the sequence's 2 ms), and
checks each result against `numpy.zeros` exactly, with `dtype == float64`.

**Assumptions:** None.

#### `test_empty_times_gives_empty_output`

**Checks:** `sample` with an empty `t` returns an empty `float64` array, not an error.

**How:** Builds `gre_sequence(num_trs=1)`, calls `sample("gx", numpy.array([]))`, and
checks the result's dtype and shape.

**Assumptions:** None.

#### `test_invalid_axis_name_raises_value_error`

**Checks:** `sample` raises `ValueError` for an axis name other than "gx", "gy" or
"gz".

**How:** Builds `gre_sequence(num_trs=1)`, calls `sample("gw", ...)` inside
`pytest.raises(ValueError)`.

**Assumptions:** None.

The remaining tests of this section are for `GradientSampler.block_samples` and
`raster_block_lengths` (`docs/plans/diagram-lanes.md`, phase 2, task 2.0, section 4.1,
item 3): the PNS lane's per-block samples at the local times `(j + 0.5) * dt`, 0 before
a block's first gradient point and after its last, with no line across a gap and no
time drift from the block start sums. This is the rule of `PnsLanes` (`_eventSamples`
in `assets/pns_lanes.js`), not the rule of `sample`.

#### `test_block_samples_matches_sample_at_file_raster_times`

**Checks:** `block_samples` over all the blocks of a file agrees with `sample` at the
file times `(k + 0.5) * dt`, within 1e-9 of the largest |g| of the axis, for the
spin-echo, gradient-echo and arbitrary-gradient synthetic sequences.

**How:** Parametrized over `spin_echo_sequence()`, `gre_sequence()` and
`arbitrary_gradient_sequence()`. `raster_block_lengths(index, dt)` gives each block's
sample count and confirms the file is on the raster; `t_file` is `(k + 0.5) * dt` for
`k` in `range(total_samples)`. For each axis, `block_samples(axis, 0, num_blocks, dt)`
is compared with `sample(axis, t_file)` with `numpy.testing.assert_allclose`, `atol =
1e-9 * peak` and `rtol = 0`, `peak` the largest `|value|` of `sample`'s result. The two
are not exactly equal: `block_samples` computes each block's samples from its own local
raster grid, with no accumulated float error, while `sample` reads the waveform at the
block's actual start time (the sequential sum of the durations before it), which drifts
off the ideal raster grid by float rounding (`docs/plans/diagram-lanes.md`, section 2.3,
item 1). The difference is that drift only.

**Assumptions:** None.

#### `test_hand_made_ramp_and_no_event_block`

**Checks:** `block_samples` gives the exact values of a hand-made sequence: a gradient
that ramps to a nonzero value and stops there (unlike an ordinary trapezoid, whose
event is 0 at both ends), inside a block longer than the ramp, and a later block with
no gradient event on any axis.

**How:** Builds a two-block sequence: block 0 has `pp.make_extended_trapezoid` on x,
ramping from 0 to `amp = 1000.0` Hz/m over `n_ramp = 4` raster steps, and
`pp.make_trapezoid` on z with an explicit `duration` of `n_block = 7` raster steps (so
the block is longer than the x ramp); block 1 is `pp.make_delay(n_block * dt)`, with no
gradient event at all. The expected x samples of block 0 are computed by hand from the
linear-interpolation rule (`amp * t / rise` while `t` is before the ramp's own last
point, 0 after it) and compared with `numpy.testing.assert_allclose` (`rtol = atol =
1e-12`): a division (the same rule, computed by a different sequence of floating-point
operations) makes exact equality unlikely. gy, which has no event anywhere in the file,
and block 1's gx and gz, which have no event in that block, are checked against exact
zero with `numpy.testing.assert_array_equal`.

**Assumptions:** None.

#### `test_range_inside_the_file_equals_the_same_slice_of_the_whole_file`

**Checks:** `block_samples` for a range that starts and ends inside the file gives
exactly the same values as the matching slice of `block_samples` for the whole file.

**How:** Builds `gre_sequence(num_trs=3)`. `raster_block_lengths` gives each block's
sample count, used to find the sample offset and length of a block range `[2, num_blocks
- 1)`. For each axis, `block_samples(axis, 0, num_blocks, dt)` and `block_samples(axis,
2, num_blocks - 1, dt)` are compared with `numpy.array_equal` after slicing the whole-file
result to the same sample offset and length.

**Assumptions:** None.

#### `test_skip_and_count_equal_the_same_slice_of_the_whole_range`

**Checks:** `block_samples(axis, first, stop, dt, skip=s, count=c)` equals
`block_samples(axis, first, stop, dt)[s : s + c]` exactly (`numpy.array_equal`), for
each axis, for block ranges of the whole file and of its inner blocks, and for sample
ranges that start and end inside a block, at the edge of a block, inside a block with
no event, and after the last point of a block's event (the samples that are 0 and
that the sampler does not keep). `count=None` gives all the samples after `skip`.

**How:** `_blocks_with_long_events_sequence()` has five blocks: a trapezoid on x and
a longer one on z; a delay of 300 samples; an arbitrary gradient on x that starts 20
samples after the block start, in a block of 120 samples held by a delay event (its
last point is 60 samples before the block end); a triangle on y; and the arbitrary
block again. The test checks that blocks 2 and 4 have 120 samples. For each block
range in `(0, 5)`, `(1, 5)`, `(2, 5)`, `(1, 4)`, `(2, 3)`, `(3, 5)`, `(0, 2)` and `(4,
5)` and each axis, `whole` is the result with no `skip` and `count`. `_sample_ranges`
makes the `(skip, count)` pairs of the blocks of that range: the whole range, an empty
range at each end, one sample at each end, and for each block its own samples, a range
across each edge, and five ranges that cover the block in fifths. For each pair, the
result with `skip` and `count` is compared with `whole[skip : skip + count]`, for the
sampler that made `whole` (with samples kept) and for a new `GradientSampler`. For
four values of `skip` (0, 1, half the range and the end), the result with `count`
left out is compared with `whole[skip:]`. At the end, the test checks that samples 60
to 119 of block 2 are all 0 and that samples 20 to 59 are not.

**Assumptions:** None.

#### `test_a_range_inside_a_block_longer_than_the_range_is_the_same_slice`

**Checks:** A sample range that cuts a block much longer than the range, the case of
`pns_levels` with a chunk, gives exactly the matching slice of the samples of the whole
block, for ranges before, across and after the end of the block's event, and inside
the block after it.

**How:** One block with a trapezoid on x held by a delay event for 100,000 samples,
then a second trapezoid block. The whole result is computed. The index of the last
nonzero sample of block 0 is found from it (and the number of nonzero samples is
checked to be fewer than 1000). For eight `(skip, count)` pairs (the start of the
block, across the last nonzero sample, just after it, the middle of the block, across
the end of the block, across the end of the block and the whole next block, the next
block, and a range that starts in the first block and ends past its end), the result
with `skip` and `count` is compared with the slice of the whole result with
`numpy.array_equal`.

**Assumptions:** None.

#### `test_the_sample_at_the_time_of_the_last_point_has_the_value_of_that_point`

**Checks:** A sample at exactly the time of the last point of a block's event has the
value of that point, which is not 0, and the next sample is 0, with no `skip`/`count`
and when the range cuts the block to one sample.

**How:** `dt` is two raster steps, so the time of sample 0, `dt / 2`, is exactly one
raster step (the test asserts this). A block with `pp.make_extended_trapezoid` that
ramps from 0 to 1000.0 Hz/m over one raster step, and a delay event that makes the
block four raster steps (two samples). `block_samples("gx", 0, 1, dt)` must be `[1000.0,
0.0]`; with `skip=0, count=1` it must be `[1000.0]`, and with `skip=1, count=1` it
must be `[0.0]`, with `numpy.testing.assert_array_equal`.

**Assumptions:** The ramp's last point is at exactly `raster` (the event stores the
times that it is given).

#### `test_block_samples_bad_skip_or_count_raises_value_error`

**Checks:** `block_samples` raises `ValueError`, with a message that names `skip`,
for a negative `skip`, a negative `count`, a negative `skip` with `count=None`, a
`skip + count` past the samples of the range, a `skip` past them, and a `skip` past
them with `count=None`.

**How:** Parametrized over `(skip, count) = (-1, 1)`, `(0, -1)`, `(-1, None)`, `(1,
10**9)`, `(10**9, 0)` and `(10**9, None)` on blocks 1 to 2 of `gre_sequence(num_trs=1)`,
each inside `pytest.raises(ValueError, match="skip")`.

**Assumptions:** None.

#### `test_skip_plus_count_up_to_the_range_end_is_accepted`

**Checks:** A `skip + count` equal to the samples of the range is not an error: an
empty range at the end, and the last four samples. For an empty range of blocks, only
`skip=0, count=0` is valid.

**How:** `gre_sequence(num_trs=1)`, blocks 1 to 2. `raster_block_lengths` gives the
number of samples. `block_samples("gx", 1, 3, dt, skip=total, count=0)` has size 0 and
`skip=total - 4, count=4` has size 4. For the empty block range `(2, 2)`, `skip=0,
count=0` has size 0, and `skip=0, count=1` raises `ValueError` (match `skip`).

**Assumptions:** None.

#### `test_block_samples_invalid_axis_name_raises_value_error`

**Checks:** `block_samples` raises `ValueError` for an axis name other than "gx", "gy"
or "gz".

**How:** Builds `gre_sequence(num_trs=1)`, calls `block_samples("gw", 0, 1, dt)` inside
`pytest.raises(ValueError)`.

**Assumptions:** None.

#### `test_block_samples_bad_range_raises_value_error`

**Checks:** `block_samples` raises `ValueError` when `first`/`stop` are outside `0 <=
first <= stop <= num_blocks`: a negative `first`, a `first` greater than `stop`, and a
`stop` past the number of blocks.

**How:** Parametrized over `(first, stop) = (-1, 1)`, `(3, 1)` and `(0, 100)` on
`gre_sequence(num_trs=1)` (5 blocks), each inside `pytest.raises(ValueError)`.

**Assumptions:** None.

#### `test_block_samples_off_raster_block_raises_value_error`

**Checks:** `block_samples` raises `ValueError` for a block whose duration is not a
whole number of raster steps.

**How:** `pp.make_delay(1.5 * dt)` (pypulseq accepts this duration), the block's own
sequence, and `block_samples("gx", 0, 1, dt)` inside `pytest.raises(ValueError)`.

**Assumptions:** None.

#### `test_raster_block_lengths_with_different_block_lengths`

**Checks:** `raster_block_lengths` gives `round(duration / dt)` for each block of a
file whose blocks do not all have the same duration, and reports the file as on the
raster.

**How:** Builds `gre_sequence(num_trs=2)` (RF, phase-encode, readout, spoiler and delay
blocks, of different durations; confirmed with `len(set(index.duration_s.tolist())) >
1`). Compares `raster_block_lengths(index, dt)`'s `n` with `numpy.rint(index.duration_s
/ dt)` cast to `int64`, with `numpy.testing.assert_array_equal`, and checks `on_raster`
is `True`.

**Assumptions:** None.

#### `test_raster_block_lengths_detects_a_block_off_the_raster`

**Checks:** `raster_block_lengths` reports a file as not on the raster when one block's
duration is not within `ON_RASTER_TOLERANCE` samples of a whole number, while still
giving a sample count (the nearest whole number) for every block.

**How:** A two-block sequence: `pp.make_delay(2 * dt)`, then `pp.make_delay(1.5 *
dt)`. `raster_block_lengths(index, dt)` must give `on_raster = False` and `n =
[2, 2]` (`numpy.rint` rounds 1.5 to 2, ties-to-even).

**Assumptions:** None.

### 2.6 Gradient limits (`test_grad_limits.py`)

`test_grad_limits.py` tests `grad_limits.py`: the peak amplitude, the peak slew
rate and the RMS amplitude of a sequence's gradients, on each logical axis and
as a three-axis vector, over the whole sequence or over a window. Every
expected value is computed by hand from the parameters of the trapezoid or
arbitrary gradient that the test builds, not by calling `gradient_limits`
itself for the expected value. The values are in Hz/m and Hz/m/s, the units of pypulseq,
with no gamma, so the hand-computed values have no conversion. Only the comparisons with the
oracle convert the values (`GAMMA_1H` from `tests/synthetic.py`).

Since phase 4 of `docs/plans/cards-at-scale.md` of pulseq-reports, `grad_limits.py` computes its values from
the per-event values of `seq_index.grad_events` and the columns of `seq_index.sequence_index`,
instead of reading every block with `get_block`, and its slew also includes the step at each
block junction (decision 6 of section 2.5 of that plan). The tests below the first group add:
the largest slew of an arbitrary gradient and of an extended trapezoid (computed from the
event's own corner points, the same way as the peak amplitude tests above), the credited block
for a value that several blocks and axes share, a window that keeps only part of a ramp's
slew, the vector peak of two blocks with different triples of active gradients, the three
junction-step cases of section 4.6 item 6, a window that starts inside a block after a
junction step, and comparisons with the oracle
(`tests/oracles/grad_limits.py`, the implementation from before phase 4).

The last group tests `block_gradient_values` (`docs/plans/gradient-pns-findings.md` of
pulseq-checks, section 3.1): the values of each block, in play order. Its
main test compares the maxima over the blocks with the whole-file result of `gradient_limits`.
The other tests check the blocks without an event on an axis, the junction step of each block,
the arrays, and the refusal of the rotation extension.

#### `test_trapezoid_peak_slew_and_rms_match_hand_computed_values`

**Checks:** For a single x trapezoid, `gradient_limits` gives the peak
amplitude, the peak slew rate and the RMS amplitude that hand computation from
the trapezoid's own rise time, flat time and amplitude predicts.

**How:** The test builds one block with an x trapezoid of a given amplitude,
rise time and flat time, and calls `gradient_limits` on it. It computes the
expected peak as the amplitude (Hz/m), the expected slew as the amplitude
divided by the rise time (Hz/m/s), and the expected RMS from the energy of the
two ramps (each `amplitude^2 * rise_time / 3`) plus the flat top
(`amplitude^2 * flat_time`), divided by the block's duration and square
rooted. It checks that the x axis result matches each expected value, that
`reason` is None, and that the peak and the slew are attributed to the
trapezoid's own block ID.

**Assumptions:**

- The trapezoid's `fall_time` equals its `rise_time`, which is
  `pp.make_trapezoid`'s default when only `rise_time` is given.

#### `test_the_values_do_not_depend_on_the_gamma_of_the_system`

**Checks:** The values of `gradient_limits` (with and without a window) and of
`block_gradient_values` do not depend on `seq.system.gamma`. For one waveform in Hz/m, the
values of a sequence of `SYSTEM` and of a sequence of a copy of `SYSTEM` with another gamma are
exactly equal, in every field.

**How:** The test makes a copy of `SYSTEM` with `gamma = 0.9 * SYSTEM.gamma`. It builds the
same sequence for each system: an x trapezoid with an explicit amplitude in Hz/m, a y arbitrary
gradient with an explicit waveform in Hz/m (`first` and `last` 0), and a block with both. It
checks that the two gammas differ and that the sequence has gradients. It compares the
`GradientLimits` of the whole sequence and of a window of the first half field by field with
`==` (the axes, the vector peak, its time and block, and the RMS over the whole file of the
window result), and each array and each dict entry of the two `BlockGradientValues` with
`numpy.array_equal`.

**Assumptions:** `pp.make_trapezoid` with an explicit `amplitude` and `pp.make_arbitrary_grad`
with a waveform in Hz/m use no gamma, so the two sequences have the same events. The test
follows `test_spectrum_does_not_depend_on_the_gamma_of_the_system` in section 2.10.

#### `test_the_values_of_a_negated_waveform_are_equal`

**Checks:** A value is a magnitude, so a sequence with each amplitude times -1 gives exactly
equal values of `gradient_limits` (with and without a window) and of `block_gradient_values`,
in every field. This is why the documents use the magnitude of gamma, which can be negative.

**How:** The test builds the sequence of the test above for `SYSTEM`, one time with the
amplitude of the trapezoid and the waveform of the arbitrary gradient as they are, and one
time with each of them times -1 (an exact operation). It checks that the sequence has
gradients, then compares the results as the test above does: field by field with `==` for
`GradientLimits`, with `numpy.array_equal` for each array of `BlockGradientValues`.

**Assumptions:** The multiplication by -1 of a float is exact, so the two sequences differ only
in the sign. The test checks that the values are equal for this sequence.

#### `test_same_trapezoid_on_x_and_y_gives_vector_peak_root_2_times_axis_peak`

**Checks:** The same trapezoid, played on x and on y at the same time, gives a
vector peak that is the axis peak times the square root of 2.

**How:** The test builds one block with the same trapezoid on x and on y, and
calls `gradient_limits`. Because Gx equals Gy at every point, `|G|` is
`sqrt(2)` times `|Gx|` at every point, and so at the peak. It checks that the
vector peak equals the x axis peak times `sqrt(2)`, and that the x and y axis
peaks are equal.

**Assumptions:** None.

#### `test_window_that_cuts_a_ramp_gives_hand_computed_rms`

**Checks:** A window that ends partway up a trapezoid's rising ramp gives an
RMS amplitude equal to the value hand-computed from the piece that the window
keeps, cut at the window edge.

**How:** The test builds one block with an x trapezoid and a window from 0 to
half the rise time. It computes the expected RMS from the one linear piece the
window keeps, from `(0, 0)` to `(rise_time / 2, amplitude / 2)`, with
`Delta t * (a^2 + a*b + b^2) / 3` divided by the window length. It checks that
`range_s` equals the window and that the x axis RMS matches.

**Assumptions:** None.

#### `test_arbitrary_gradient_peak_is_the_largest_of_first_last_and_waveform`

**Checks:** For an arbitrary gradient, the peak amplitude is the largest
absolute value among the shape's `first`, `last` and interior waveform
samples.

**How:** The test builds an x arbitrary gradient from an asymmetric sine-lobe
waveform, whose largest magnitude is not at the shape's first or last sample,
and calls `gradient_limits`. It computes the expected peak as the largest of
`abs(first)`, `abs(last)` and the largest absolute waveform sample, taken from
the block's own gradient event. It checks that the x axis peak matches (Hz/m).

**Assumptions:**

- `seq_utils.gradient_points` adds `first` and `last` as extra points at the
  ends of an arbitrary gradient's shape (checked by `test_gradient_points_arbitrary`
  in `test_seq_utils.py`), so they can hold the largest magnitude even when
  every interior waveform sample is smaller.

#### `test_no_gradients_sets_reason`

**Checks:** A sequence with no gradient events at all gives a set `reason`,
and every numeric field is its zero value: 0.0 for an amplitude, slew or RMS
field, and None for a block field.

**How:** The test builds a sequence with one delay block and no gradients, and
calls `gradient_limits`. It checks that `reason` is
"no gradient events in the sequence", that the vector peak and its time are
0.0, and that every axis's peak, slew and RMS are 0.0 with `peak_block` and
`slew_block` both None.

**Assumptions:** None.

#### `test_arbitrary_gradient_max_slew_is_the_largest_neighbouring_slope`

**Checks:** The largest slew of an arbitrary gradient is the largest
`|delta g / delta t|` between its neighbouring corner points (the shape's
`first`, its waveform samples, and its `last`).

**How:** The test builds an x arbitrary gradient from an asymmetric sine-lobe
waveform and calls `gradient_limits`. It computes the expected slew from
`block.gx.first`, `block.gx.waveform`, `block.gx.last` and their own offset
and shape-duration fields (the same corner points `gradient_offsets` builds),
as the largest `|diff(amplitude) / diff(time)|`, not by calling
`gradient_limits` for the expected value. It checks that the x axis slew
matches.

**Assumptions:** None.

#### `test_extended_trapezoid_max_slew_is_the_largest_segment_slope`

**Checks:** The largest slew of an extended trapezoid is the largest
`|delta g / delta t|` between its neighbouring control points.

**How:** The test builds an x extended trapezoid from five explicit times and
amplitudes and calls `gradient_limits`. It computes the expected slew as the
largest `|diff(amplitudes) / diff(times)|` of the same arrays given to
`make_extended_trapezoid`. It checks that the x axis slew matches.

**Assumptions:** None.

#### `test_largest_over_several_blocks_and_axes_credits_the_first_block_with_that_value`

**Checks:** With several blocks on several axes, the peak amplitude and the
peak slew of each axis are the largest over every block with an event on that
axis, credited to the first block, in play order, whose event reaches that
value; a later block that repeats the very same event does not move the
credit.

**How:** The test builds four blocks: a small x trapezoid, a y trapezoid, a
larger x trapezoid, and the same larger x trapezoid again. It checks that the
x axis peak and slew equal the larger trapezoid's own amplitude and slew
(divided by its rise time), each credited to the third block (the first
block with that event, not the fourth), and that the y axis peak equals the y
trapezoid's amplitude.

**Assumptions:** None.

#### `test_window_that_cuts_a_ramp_gives_the_slew_of_the_part_inside_the_window`

**Checks:** A window that includes only part of an extended trapezoid, over a
segment with a smaller slope than another segment outside the window: the
slew over the window is the slope of the part inside the window, not the
largest slope of the whole event, and the slew time is the window start, where
the window cuts that segment.

**How:** The test builds an x extended trapezoid with four segments of
different slopes and a window that lies inside the two segments with the
smallest slopes, excluding the segment with the largest. It computes the
expected slew by hand from the times and amplitudes of the segment the window
keeps. It checks that the x axis slew matches, not the whole event's own
largest segment slope, and that `slew_time_s` is the window start (100 µs).

**Assumptions:** None.

#### `test_slew_time_is_the_start_of_the_steepest_segment`

**Checks:** The slew time of an axis is the start of its steepest segment.

**How:** The test builds one x extended trapezoid whose last segment (900 to
1100 µs) is its steepest. It checks that the x slew is that segment's slope,
computed by hand, and that `slew_time_s` is 900 µs.

**Assumptions:** None.

#### `test_vector_peak_of_g_compares_different_triples_across_blocks`

**Checks:** Two blocks with different triples of active gradients: the
vector peak of `|G|` is the largest magnitude found across the two different
triples, not just the largest single-axis peak, and the vector peak block and
time are those of the block that reaches it.

**How:** The test builds one block with a large x trapezoid alone, and a
second block with a smaller, equal-amplitude trapezoid on both x and y (whose
combined vector magnitude, `sqrt(2)` times the smaller amplitude, is larger
than the first block's lone peak). It checks that the vector peak equals the
hand-computed combined magnitude of the second block's triple, that
`vector_peak_block` is the second block, and that `vector_peak_time_s` is the
end of the second block's rise (1.0 ms, after the 0.8 ms of the first block).

**Assumptions:** None.

#### `test_junction_step_between_extended_trapezoids_is_reported_as_the_slew`

**Checks:** A step at the junction between two extended trapezoids, within
the tolerance that `add_block` accepts (`max_slew * grad_raster_time`) and
larger than any segment's own slope: the reported slew is the step divided
by `grad_raster_time`, credited to the block after the junction, at the time
of the junction.

**How:** The test builds two x extended trapezoids whose junction step is 90%
of the largest step `add_block` accepts, and whose own segment slopes are
smaller than that step. It computes the expected slew by hand as the step
divided by `grad_raster_time`. It checks that the x axis slew matches, is
credited to the second block, and that `slew_time_s` is the junction (0.2 ms).

**Assumptions:** None.

#### `test_junction_step_uses_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The step at a block junction is divided by the gradient raster of the
sequence, `seq.grad_raster_time` (the `GradientRasterTime` that the file declares),
not by `seq.system.grad_raster_time`. A sequence read from a file gives the same value
as the sequence object that wrote it.

**How:** `raster_4us_sequence` builds two y extended trapezoids with a 4 µs gradient
raster: the slopes are 40 and 39.4 T/m/s and the junction step is 0.24 mT/m, so the
junction is 60 T/m/s with 4 µs (24 T/m/s with 10 µs). The test writes the sequence to
a file in `tmp_path` and reads it with `pp.Sequence()`, whose `system` has 10 µs. For
the sequence that was read and for the sequence object, it checks that the y slew is
60 T/m/s times `GAMMA_1H` (Hz/m/s), credited to the second block, at the junction (0.8 ms).

**Assumptions:** The file stores the amplitudes with fewer digits than the sequence
object, so the comparison has a relative tolerance of 1e-4.

#### `test_gradient_ending_non_zero_before_a_block_with_no_gradient_is_a_junction_step`

**Checks:** A gradient that ends at a non-zero value (within the tolerance
`add_block` accepts) right before a block with no gradient on that axis: the
junction step uses 0 for the block with no event, and is credited to that
block (the block after the junction).

**How:** The test builds an x extended trapezoid ending at 90% of the largest
step `add_block` accepts, followed by a delay block with no gradient. It
computes the expected slew by hand as that ending value divided by
`grad_raster_time`. It checks that the x axis slew matches and is credited to
the delay block.

**Assumptions:** None.

#### `test_first_block_not_starting_at_zero_is_a_junction_step_before_the_first_block`

**Checks:** A first block whose gradient starts at a non-zero value within
the tolerance `add_block` accepts: the junction before the first block uses 0
for "the block before" (there is none), and is credited to the first block.

**How:** The test builds a single x extended trapezoid starting at 90% of the
largest step `add_block` accepts. It computes the expected slew by hand as
that starting value divided by `grad_raster_time`. It checks that the x axis
slew matches and is credited to the first (only) block.

**Assumptions:** None.

#### `test_window_inside_a_block_with_no_gradient_ignores_the_junction_before_it`

**Checks:** A window entirely inside a block with no gradient, right after a gradient
event that ends at a non-zero value (within the tolerance `add_block` accepts) in the
block before: the window does not use the junction between the two blocks, because
that block starts before the window (`docs/plans/review-bugs.md`, B1, decision 14), so
the window has no gradient event and 0 slew. A window that starts exactly at that
junction still uses it.

**How:** The test builds an x extended trapezoid ending at 90% of the largest step
`add_block` accepts, followed by a delay block with no gradient. It calls
`gradient_limits` with a window from partway into the delay block to its end, and
checks that `reason` is "no gradient events in the window", the x slew is 0.0, and
`slew_block` is None. It then calls `gradient_limits` with a window that starts
exactly at the junction (the end of the trapezoid block) and checks that the x slew
equals the ending value divided by `grad_raster_time` and is credited to the delay
block.

**Assumptions:** None.

#### `test_window_that_cuts_a_block_credits_it_on_a_tie_with_a_later_block`

**Checks:** When a block that the window start cuts and a later block fully inside the
window reach the same peak and the same slew, both are credited to the cut block, the first
in play order, as a single pass over the blocks would (finding L3 of
`docs/reviews/2026-09-28-code-review.md`). The peak time and the vector peak time are the
first time the cut block reaches the peak.

**How:** The test builds two blocks with the same x trapezoid (rise 0.2 ms, flat 0.4 ms,
fall 0.2 ms), then a delay block. The window starts at 0.4 ms, in the flat top of block 1,
so block 1's fall ramp and all of block 2 are inside the window. It checks that the x
`peak_block` and `slew_block` are block 1, and that the x `peak_time_s` and
`vector_peak_time_s` are 0.4 ms, the window start.

**Assumptions:** The slope of block 1's fall ramp, clipped by the window, equals bit for bit
the slope of the same event in block 2, because block 1 starts at 0 and the clip keeps the
ramp's own corner points. The oracle is not used: it computes slopes from absolute corner
times, so its slope of block 2 differs by a rounding error.

#### `test_vector_peak_time_on_a_tie_is_the_first_time_in_play_order`

**Checks:** When two blocks with different triples of events reach the same |G| peak, the
vector peak time is the first time the earlier block reaches it, not a time in the later
block, and the vector peak block is the earlier block. The triples are found with
`numpy.unique`, whose order is not the play order.

**How:** The test builds the same trapezoid on x in block 1 and on y in block 2, and checks
that `vector_peak_time_s` is 0.2 ms, the end of block 1's rise, and that
`vector_peak_block` is block 1.

**Assumptions:** None.

#### `test_axis_whose_only_event_is_zero_credits_no_block`

**Checks:** An axis whose only event has amplitude 0 has a peak and a slew of 0, and no block
is credited for either (`peak_block` and `slew_block` are None).

**How:** The test builds one block with an x trapezoid and a y trapezoid scaled to amplitude
0 with `pp.scale_grad`, and checks the y axis's peak, slew and block fields.

**Assumptions:** None.

#### `test_matches_oracle_on_synthetic_sequences`

**Checks:** `gradient_limits` matches the oracle (`tests/oracles/grad_limits.py`, the
implementation from before phase 4 of `docs/plans/cards-at-scale.md` of pulseq-reports) on the whole file, and
on a window covering the first half of the sequence, for each of `tests/synthetic.py`'s
sequences (parametrized: `spin_echo_sequence`, `gre_sequence`, `empty_sequence`,
`arbitrary_gradient_sequence`).

**How:** For each sequence, the test calls both `gradient_limits` and the oracle's, with no
window and with a window from 0 to half the total duration. The oracle gives mT/m and T/m/s with
`GAMMA_1H`, so `_assert_matches_oracle` converts the values of this package first: the
amplitudes, the RMS and the vector peak times `1e3 / GAMMA_1H`, the slews times `1 / GAMMA_1H`
(the conversion of `docs/usage.md` section 8, which the test also checks). It compares every
field (`reason`, `range_s`, each axis's peak, slew and RMS, and the vector peak), within a
tolerance derived from the sequence (`_rounding_tol`):
`1e-12 + 4 * eps * duration / shortest segment`, relative to the value or to the limit of the
same kind (the limit of the oracle result: `gradient_limits` itself has no limits). It checks
only whether a block is credited, not which one, because `gre_sequence` repeats its readout, phase-encode and spoiler events every TR,
and the oracle's own choice among such a tie can depend on the same rounding.

**Assumptions:**

- The user chose this tolerance on 2026-09-28. The oracle adds each block's absolute start
  time to an event's corner points before it takes a slope, so each corner time is rounded to
  about eps times the start time, and a slope divides the difference of two such times by the
  segment's duration. The new code computes each event one time from its own offsets. On the
  synthetic and random sequences the differences are at most about 2% of this bound.

#### `test_matches_oracle_on_random_gradient_sequences`

**Checks:** 200 random sequences of trapezoids, extended trapezoids and arbitrary gradients on
random axes, each event built so that it starts and ends at 0 (so every block junction step is
0, and the result is only the per-event, non-junction part that the tests above cover on their
own): `gradient_limits` matches the oracle, on the whole file and on a random window, and the
window's `whole_rms_hz_per_m` (computed in the same call, for the card's "RMS over whole file"
column) matches the oracle's own whole-file RMS.

**How:** For each of 200 seeds, the test builds a sequence of 2 to 6 blocks, each with 0 to 3
random axes, each a trapezoid, an extended trapezoid or an arbitrary gradient built with
pypulseq's `make_*` functions (so pypulseq's own limit checks apply) and an explicit `first` and
`last` of 0 where the function does not default to that. It compares the whole-file result and
a random window's result with the oracle's, field by field, with the same derived tolerance and
the same block-attribution exception and the same conversion to the units of the oracle as
`test_matches_oracle_on_synthetic_sequences`, and separately compares `whole_rms_hz_per_m`
(times `1e3 / GAMMA_1H`) against a fresh whole-file oracle call.

**Assumptions:**

- `make_arbitrary_grad`'s `first` and `last` default to a linear extrapolation of the
  waveform's own edge samples, not to 0 (`docs/notes/slew-definitions.md`'s pypulseq source
  reading confirms this), so the random arbitrary-gradient builder passes `first=0.0, last=0.0`
  explicitly to keep every event zero-ended. This is a fact about pypulseq, not about the
  function under test, and is not itself checked here.

#### `test_gradient_limits_refuses_rotations`

**Checks:** `gradient_limits` raises `NotImplementedError` for a sequence with a
rotation library.

**How:** `gre_sequence(num_trs=2)` with a non-empty `rotation_library` (the
`with_rotation_library` helper of `tests/synthetic.py`), inside
`pytest.raises(NotImplementedError, match="rotation extension")`.

**Assumptions:** None.

#### `test_block_gradient_values_agree_with_gradient_limits_for_the_whole_file`

**Checks:** For each of 32 sequences (parametrized), the maxima of `block_gradient_values`
over the blocks are the whole-file values of `gradient_limits`, with the same block and the
same time. For each axis: the maximum of `peak_hz_per_m` is `peak_hz_per_m` of the axis, and
the first block in play order with that maximum has the `peak_block` and the `peak_time_s`. The
maximum over the blocks of the larger of `slew_hz_per_m_per_s` and `junction_hz_per_m_per_s` is
`max_slew_hz_per_m_per_s`, and the first block with that maximum has the `slew_block`, with the
start of the block as the time when its junction step has the maximum (the junction is before
every segment of its block), otherwise the `slew_time_s` of its segment. The maximum of
`vector_peak_hz_per_m` is `vector_peak_hz_per_m` of the result, with the same block and time.
When the maximum is 0, `gradient_limits` has no block (None).

**How:** The sequences are `spin_echo_sequence`, `gre_sequence`, `empty_sequence`,
`arbitrary_gradient_sequence`, `border_sequence`, `raster_4us_sequence`, `build_repeating(50)`
and `build_worst(50)` of `tests/scale_sequences.py`, four junction sequences of this file (a
step between two extended trapezoids, the same with a segment of the second block that has the
same slew as the step, a gradient that ends non-zero before a delay, a first block that starts
non-zero), and 20 random sequences of `_random_gradient_sequence` (seeds 0 to 19). For each
sequence the test calls `block_gradient_values` and `gradient_limits` and compares them
with `==`, not `pytest.approx`.

**Assumptions:**

- Exact equality holds because both functions use the same arithmetic on the same
  per-event values: the same `_event_values`, `start_s + offset` for the times, the values of
  the events as they are for an amplitude and a slew, and the junction step divided by
  `seq.grad_raster_time`.
- The 20 random sequences have no junction step (every event starts and ends at 0), the junction
  sequences have no random part. The test does not compare a window: `block_gradient_values` has
  no window.

#### `test_block_without_an_event_on_an_axis_has_zero_values_and_its_start_as_time`

**Checks:** An axis without an event in a block has a peak, a slew and a junction step of 0
there, and the start of the block as the peak time and the slew time. A block without gradients
has a vector peak of 0 at the start of the block. The values of the axes with an event are the
hand-computed ones.

**How:** The test builds three blocks: x and y trapezoids (x: 0.5 of the maximum gradient, a rise
of 0.2 ms; y: 0.25 of it, a rise of 0.1 ms, a flat top of 0.2 ms), a z trapezoid, and a delay.
It checks the peak, the peak time and the slew of x in block 1, the peak of y in block 1 and of z
in block 2, the zero values and the start times on every axis and block without an event, the
vector peak of block 1 (`hypot(0.5, 0.25)` of the maximum gradient, at 0.2 ms), of block 2 and
of the delay block (0 at its start), with `pytest.approx` for the hand-computed values and exact
equality for the zeros and the start times.

**Assumptions:** None.

#### `test_first_block_junction_step_uses_zero_before_the_block`

**Checks:** For a first block whose gradient starts at a non-zero value, the junction step of
its axis is that value divided by `seq.grad_raster_time`, and the junction step of the other
axes is 0.

**How:** One extended trapezoid on x that starts at 0.9 of the largest step that `add_block`
accepts (`max_slew * grad_raster_time`). The test checks `junction_hz_per_m_per_s` of the block
for x, y and z.

**Assumptions:** None.

#### `test_junction_step_is_at_the_start_of_the_block_after_the_junction`

**Checks:** The step at a junction is in the block after the junction. For two x extended
trapezoids with a step between them, followed by a delay, block 1 and block 3 have a step of 0
and block 2 has the step divided by the raster. A gradient that ends at a non-zero value before a
delay gives that value divided by the raster as the step of the delay block, and 0 for the
first block.

**How:** The test builds the two sequences and compares `junction_hz_per_m_per_s["x"]` with the
hand-computed value (`pytest.approx`) and with 0 (exact).

**Assumptions:** None.

#### `test_junction_step_and_segment_of_one_block_with_the_same_slew_give_the_junction_time`

**Checks:** When the junction step and the first segment of the same block have the same slew,
and it is the largest of the file, `gradient_limits` credits that block and gives the start of the
block (the junction) as the time, and `block_gradient_values` has equal `junction_hz_per_m_per_s`
and `slew_hz_per_m_per_s` in that block.

**How:** Block 1 is an x extended trapezoid that ends at `x`. Block 2 starts at `x - step` and
reaches `x` in one gradient raster, with `step` 0.9 of the largest step that `add_block` accepts.
The test checks the two slews with `==`, then the `slew_block`, `slew_time_s` and
`max_slew_hz_per_m_per_s` of `gradient_limits`.

**Assumptions:** The two slews are equal in floating point for these values (the value of both is
0.9 of the maximum slew of `SYSTEM`). The test checks this with `==`.

#### `test_block_gradient_values_are_in_play_order_with_one_entry_for_each_block`

**Checks:** Each array has one entry for each block, `block_id` and `start_s` equal the arrays of
`sequence_index(seq)` (play order), the five dicts have the keys x, y and z, and the arrays are of
type float64 (`block_id` aside).

**How:** The test calls `block_gradient_values` on `gre_sequence(num_trs=3)`, compares `block_id`
and `start_s` with `assert_array_equal`, and checks the shape and the dtype of each of the 17
float arrays and that `start_s` increases.

**Assumptions:** None.

#### `test_block_gradient_values_refuses_rotations`

**Checks:** `block_gradient_values` raises `NotImplementedError` for a sequence with a rotation
library.

**How:** The same as `test_gradient_limits_refuses_rotations`: the `with_rotation_library`
sequence of `tests/synthetic.py`, inside `pytest.raises(NotImplementedError, match="rotation
extension")`.

**Assumptions:** None.

#### `test_gradient_limits_refuses_a_window_with_no_start_before_its_end`

**Checks:** `gradient_limits` raises `ValueError` for a `window` whose start is not
before its end.

**How:** The synthetic spin echo, with three cases: a start equal to the end, a start
after the end, and a NaN start. Each call is in
`pytest.raises(ValueError, match="must have a start before its end")`.

**Assumptions:** None.

#### `test_gradient_limits_refuses_a_window_outside_the_sequence`

**Checks:** `gradient_limits` raises `ValueError` for a `window` that is outside the
sequence by more than `TIME_TOLERANCE`.

**How:** The synthetic spin echo, with two cases: a start of `-2 * TIME_TOLERANCE`, and
an end of `total_duration + 2 * TIME_TOLERANCE`. Each call is in
`pytest.raises(ValueError, match="is not within the sequence")`.

**Assumptions:** None.

#### `test_gradient_limits_accepts_a_window_within_the_tolerance_of_the_sequence`

**Checks:** `gradient_limits` accepts a `window` that is outside the sequence by less
than `TIME_TOLERANCE`, and `range_s` is the sequence.

**How:** The synthetic spin echo and the window
`(-TIME_TOLERANCE / 2, total_duration + TIME_TOLERANCE / 2)`. The call does not raise,
and `range_s` equals `(0.0, total_duration)`.

**Assumptions:** None.

#### `test_distinct_triples_are_the_groups_of_np_unique_with_up_to_3_million_events`

**Checks:** For triples of dense event numbers up to 3,000,000, `_distinct_triples` (used by
`_range_result` and `_block_vector_peaks`) gives the groups of
`np.unique(np.stack([gx, gy, gz], axis=1), axis=0, return_index=True, return_inverse=True)`: the
same partition of the positions and the same first position of each group.

**How:** With the seed 20261005, a pool of 300 random triples, 100 triples that differ from a
triple of the pool in one number, and six triples with the extremes 0 and 3,000,000. 5,000
positions are drawn from the pool (so triples repeat), and every triple of the pool is put in a
random position at least once. The test checks that the numbers of groups are equal, that the
pairs (group of the helper, group of the reference) are one-to-one, that the first position of
each group of the helper is the first position of its group in the reference, and that the
inverse at each first position is the number of its group.

**Assumptions:** `np.unique` with `axis=0` is correct. The test calls the private helper
directly, because the 3 million events are too many for a sequence.

#### `test_distinct_triples_keep_apart_two_triples_that_one_int64_key_gives_one_number`

**Checks:** Two triples whose one-step key `(gx * base + gy) * base + gz` is equal in int64 are
two groups in `_distinct_triples`. The old key of `_range_result` fails this test.

**How:** With `num_events = 2**22 - 1` (`base = 2**22`), the triples `(2**20, 1, 1)` and
`(0, 1, 1)` have keys that differ by `2**64`. The test first checks that the two one-step keys
are equal (with int64 overflow allowed in numpy). Then, for the triples `(2**20, 1, 1)`,
`(0, 1, 1)`, `(2**20, 1, 1)`, it checks that the helper gives two groups, that the first and the
second position are in different groups, and that the first and the third are in one group, and
that the groups are those of `np.unique(..., axis=0)`.

**Assumptions:** int64 arithmetic of numpy wraps around without an error.

### 2.7 PNS prediction (`test_pns.py`)

`test_pns.py` tests `pns.py`. `PnsPrediction` is now summary-only (`reason`,
`hardware`, `asc_file`, `peak_hz_per_t`, `peak_time_s`, `axis_peaks_hz_per_t`; no `t_s`,
`norm` or `axes`), built by `pns_prediction` from `pns_levels_for(seq,
gradient_asc=...)` — the SAFE model itself (`pns_levels.pns_levels`, the pinned
pypulseq fork's chunked SAFE recursion) has moved there. `pns_levels_for`
keeps one `PnsLevels` for each (sequence object, hardware, thresholds), the hardware
being the example hardware, the resolved path of the gradient `.asc`
file, or a `hardware` pair `(struct, label)` (its key is the label and the 27
values of the struct, so two pairs with the same label and values are one
hardware), and the rule of `seq_index.sequence_index` for staleness (all are
rebuilt when the number of blocks or the last block id changes), so that a page with both the PNS summary card and the
diagram's PNS lane for one sequence runs the SAFE model once. The thresholds of the key are
the tuple of `float(t)`, so an `int` threshold and the equal `float` are one key, and the
default `()` is its own key. A PNS value is in Hz/T (the fraction of the stimulation limit
times the magnitude of gamma). The test file defines `_LIMIT = PNS_LIMIT * GAMMA_1H`, the
stimulation limit for 1H in Hz/T.
`peak_tr_window` is the start and end of the TR that holds the
prediction's peak, counted from the sequence start in steps of the TR
definition. Without a gradient `.asc` file, the prediction uses pypulseq's
example hardware, which is not a real scanner. The tests of `hardware` are the last
ones of this section.

The real `.asc` files are confidential, so the tests write a test `.asc` file
with the PNS parameters of pypulseq's example hardware, with the
`write_gradient_asc` fixture of `tests/conftest.py`. The stimulation limits
and thresholds in it can be multiplied by a scale factor. The test file can
also have the layout of a scanner file: a main file with an `ASCCONV` block,
CRLF line ends and the name in `asCOMP[0].tName`, which includes a
`_GSWD_SAFETY.asc` file with the PNS parameters under `GradPatSup.Phys.PNS`.

Most of the tests use the synthetic spin echo sequence
(`tests/synthetic.py`'s `spin_echo_sequence`). The `peak_tr_window` tests use
a three-TR sequence built in this file (`_three_trs`): three 50 ms TRs, each a
y trapezoid on the synthetic system and a delay, with a TR definition of
50 ms. One of the three TRs (the "peak TR") has a 0.1 ms rise and fall time,
against 0.4 ms for the others, so its faster slew rate gives it the highest
PNS.

**Assumptions for the whole file:**

- pypulseq's SAFE model is correct. No test compares it with a published
  result or with a scanner.
- No test uses the parameters of a real scanner. A PNS value for the
  synthetic sequences on the scanner is not tested.
- A faster slew rate gives a higher PNS prediction. The SAFE model is driven
  by the slew rate, so this is expected but not calculated in the tests.

#### `test_example_hardware_for_spin_echo`

**Checks:** For the synthetic spin echo sequence on the example hardware, the summary
equals `pns_levels.pns_levels` of the same sequence and hardware, is below the
stimulation limit, and is highest on y.

**How:** The test runs the prediction without an `.asc` file (the module-scoped
`example` fixture) and, separately, `pns_levels.pns_levels` on the same sequence
object. It checks that there is no reason, that the hardware is the example hardware,
and that there is no `.asc` file name. It checks that the axis peaks are keyed x, y and
z, and that the peak is more than 0 and less than `_LIMIT` (100 % of the limit, in Hz/T).
The axis with the highest peak must be y, where the crushers are. `peak_hz_per_t`,
`peak_time_s` and `axis_peaks_hz_per_t` must equal `pns_levels`'s own fields exactly.

**Assumptions:**

- "Below the limit" is for the example hardware only.
- The crushers (on y) give the synthetic sequence's highest per-axis PNS. This was
  checked against a direct run of the prediction, not derived by hand.
- `pns_prediction` and a fresh `pns_levels.pns_levels` call on the same sequence and
  hardware give bit-identical numbers (no randomness in the pipeline), so the
  comparison is exact equality, not a tolerance.

#### `test_asc_file_with_the_example_parameters`

**Checks:** An `.asc` file with the example hardware's parameters gives the same
prediction as the example hardware, and the file's hardware name and file name.

**How:** The test writes a test `.asc` file with scale factor 1 and runs the
prediction with it. There must be no reason, the hardware name must be the name in the
file, and the file name must be the name of the file. `peak_hz_per_t`, `peak_time_s` and
each axis of `axis_peaks_hz_per_t` must equal the example hardware's own summary within a
relative 10⁻⁹.

**Assumptions:**

- The test file has only the fields that pypulseq's `.asc` reader needs for PNS. A
  real file has many more fields, in the same format.

#### `test_asc_file_that_includes_the_pns_parameters`

**Checks:** A main `.asc` file that includes the PNS parameters from a second file
with `$INCLUDE` gives the same prediction as the example hardware, and the hardware
name in `asCOMP[0].tName`.

**How:** The test writes a test `.asc` file with the scanner layout and scale factor
1, and runs the prediction with the main file. There must be no reason, the hardware
name must be the name in the main file, and the file name must be the name of the main
file. `peak_hz_per_t`, `peak_time_s` and each axis of `axis_peaks_hz_per_t` must equal the
example hardware's own summary within a relative 10⁻⁹.

**Assumptions:**

- The layout is the layout of the `MP_GradSys_K2309_2250V_951A_XR_AS82.asc` files from
  the XA60 IDEA installation: the `$INCLUDE` line names a file in the same directory,
  without quotes. Other software versions are not tested.

#### `test_asc_file_with_a_missing_include`

**Checks:** When a file that `$INCLUDE` names is not there, reading the `.asc`
file stops with an error that names both files.

**How:** The test writes a test `.asc` file with the scanner layout, deletes
the `_GSWD_SAFETY.asc` file, and reads the main file. It must raise
`FileNotFoundError` with a message that has the main file name and the
included file name.

**Assumptions:** None.

#### `test_included_fields_replace_fields_with_the_same_name`

**Checks:** The fields of an included file are merged into the fields of the
main file, and a field in both files gets the value of the included file.

**How:** The test writes a main file with `a.b[0] = 1`, `a.b[1] = 2`,
`c = "old"` and a `$INCLUDE` line, and an included file with `a.b[1] = 3` and
`c = "new"`. The fields read must be `a.b[0] = 1`, `a.b[1] = 3` and
`c = "new"`.

**Assumptions:**

- In the real files, the `$INCLUDE` line is the last field of the main file,
  so the included values are the last values, as in the file order. A field
  after a `$INCLUDE` line that is also in the included file is not tested.

#### `test_hardware_name`

**Checks:** The hardware name comes from `asCOMP[0].tName` (a scanner file) or
`asCOMP.tName`, and is "unknown" without either.

**How:** The test gives the name function the fields for each of the three
cases and checks the name.

**Assumptions:** None.

#### `test_prediction_scales_with_the_stimulation_limit`

**Checks:** A stimulation limit 10 times lower gives a prediction 10 times
higher, above the limit.

**How:** The test writes a test `.asc` file with scale factor 0.1 and runs the
prediction. The peak must be 10 times the example hardware peak within a
relative 10⁻⁹, and more than `_LIMIT`.

**Assumptions:**

- In the SAFE model, the prediction is inversely proportional to the
  stimulation limit.

#### `test_no_gradients`

**Checks:** A sequence without gradients has no prediction, with the reason
"no gradients", a peak of 0 and no peak time.

**How:** The test makes the synthetic sequence with only a delay block
(`tests/synthetic.py`'s `empty_sequence`) and checks the reason, the hardware
name, the peak and the peak time.

**Assumptions:** None.

#### `test_no_gradients_with_rf_and_adc`

**Checks:** A sequence with RF and ADC events but no gradient events has no
prediction, with the reason "no gradients".

**How:** The test makes a sequence with a block pulse block and an ADC block,
and checks the reason.

**Assumptions:**

- `pns.py` finds "no gradients" from the gradient columns of
  `seq.block_events`. This test and `test_no_gradients` check that other
  events do not count as gradients.

#### `test_a_gradient_on_one_axis_has_a_prediction`

**Checks:** A sequence with a gradient on one axis only, x, y or z, has a
prediction.

**How:** For each axis, the test makes a sequence with a delay block and a
trapezoid block on that axis. There must be no reason, and the peak must be
more than 0.

**Assumptions:**

- A gradient in a block after the first block counts. The delay block comes
  first, so a check of the first block only would fail.

#### `test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence`

**Checks:** The prediction never calls `seq.get_gradients()` for an on-raster sequence.

**How:** The test replaces `get_gradients` of a synthetic spin echo sequence with a
wrapper that counts the calls, and runs the prediction. There must be no calls.

**Assumptions:**

- `pns_levels.pns_levels` samples an on-raster sequence with
  `GradientSampler.block_samples`, not `seq.get_gradients()`/`seq.calculate_pns` (that
  was the old, now-removed, implementation, which is why the old test expected exactly
  one call). `test_pns_levels.py` and `test_sampling.py` test `block_samples` and its
  agreement with `sample`/`get_gradients()` directly; this test only checks that the
  fast path is actually taken from `pns_prediction`.

#### `test_prediction_keeps_no_blocks_and_gives_back_the_cache_setting`

**Checks:** The prediction does not fill pypulseq's block cache, and the
cache setting of the sequence is the same after the prediction.

**How:** For `use_block_cache` True and False, the test sets it on a
synthetic spin echo sequence, empties `seq.block_cache`, and runs the
prediction. After it, `use_block_cache` must have the same value and
`seq.block_cache` must be empty.

**Assumptions:**

- `calculate_pns` reads every block with `get_block`, which keeps each block
  in `seq.block_cache` when `use_block_cache` is True. An empty cache after
  the prediction shows that the cache was off while it ran.

#### `test_prediction_propagates_an_error_and_keeps_the_cache_setting`

**Checks:** An error deep inside the SAFE model propagates out of `pns_prediction`, and
the sequence's block-cache setting and contents are unaffected.

**How:** The test sets `use_block_cache` to True on a synthetic spin echo sequence and
replaces `pns_levels._safe_gwf_to_pns_chunk` (the pinned fork's chunk function) with a
function that raises `RuntimeError`. The prediction must raise the error,
`use_block_cache` must be True and `seq.block_cache` must be empty afterward.

**Assumptions:**

- The block cache is touched only inside `seq_index.block_cache_off`'s own
  `try`/`finally`, which has already restored `use_block_cache` by the time the chunk
  function runs (`GradientSampler` is built, with the block cache off, before the
  chunk loop starts). So this test checks that the error propagates and that nothing
  else in `pns_levels_for`/`pns_prediction` touches the cache setting outside that
  narrower guarantee, not that the guarantee itself is new.

#### `test_peak_tr_window_finds_the_tr_with_the_peak`

**Checks:** For each position of the peak TR (first, second or third) in the
three-TR sequence, `peak_tr_window` returns that whole TR, and the
prediction's peak time is inside it.

**How:** For peak TR k = 0, 1 and 2, the test builds `_three_trs(k)`, runs the
prediction, and calls `peak_tr_window` with the peak time. The window must be
50k s to 50(k + 1) ms (converted to seconds), and the peak time must be
inside it.

**Assumptions:**

- TRs are counted from the start of the sequence, in steps of the TR
  definition.

#### `test_peak_tr_window_without_a_tr_definition_is_none`

**Checks:** Without a TR definition, `peak_tr_window` returns None.

**How:** The test builds the three-TR sequence, removes its TR definition,
runs the prediction, and calls `peak_tr_window` with the peak time. The
result must be None.

**Assumptions:** None.

#### `test_peak_tr_window_with_one_tr_is_none`

**Checks:** When the sequence is not longer than one TR, `peak_tr_window`
returns None.

**How:** The test takes the synthetic spin echo sequence, whose duration is
much less than a TR, and sets its TR definition to its own duration exactly.
`peak_tr_window` with any peak time must return None.

**Assumptions:** None.

#### `test_peak_tr_window_without_a_peak_time_is_none`

**Checks:** With no peak time (`None`), `peak_tr_window` returns None.

**How:** The test builds the three-TR sequence and calls `peak_tr_window`
with `peak_time_s=None`. The result must be None.

**Assumptions:** None.

#### `test_pns_levels_for_keeps_one_result_for_each_asc_file`

**Checks:** `pns_levels_for` keeps one result for each (sequence, gradient `.asc`
file): a different `.asc` file for the same sequence computes once, and going back to
an earlier file does not compute again.

**How:** The test patches `pns.pns_levels` the same way as the test above, and calls
`pns.pns_levels_for(seq, gradient_asc=path)` for two different `.asc` files (`path_a`,
`path_b`) built by the `write_gradient_asc` fixture of `tests/conftest.py`, in the order a, a, b, a. It
checks the call count is 1, 1 (cached), 2 (a different file), 2 (back to `path_a`,
restored from the kept results).

**Assumptions:** None.

#### `test_pns_levels_for_alternating_two_hardwares_runs_the_model_two_times`

**Checks:** Two hardwares of one sequence alternated (a, b, a, b) run the SAFE model two
times, not four: the cache keeps one result for each hardware.

**How:** The test patches `pns.pns_levels` as above, and calls
`pns.pns_levels_for(seq, gradient_asc=...)` with the keys `None` (the example hardware),
a `.asc` file, `None`, the same file. It checks there were 2 calls.

**Assumptions:** None.

#### `test_pns_levels_for_hardware_from_an_asc_file_gives_the_levels_of_the_file`

**Checks:** `pns_levels_for(seq, hardware=(asc_to_hw(read_gradient_asc(path)), label))`
gives the levels of `pns_levels_for(seq, gradient_asc=path)`, except `hardware` (the
label) and `asc_file` (None), for the plain layout and for the layout of a scanner file.

**How:** Parametrized on `split`. The `write_gradient_asc` fixture of `tests/conftest.py`
writes the file. The test compares each field but the two (`numpy.array_equal` for the
arrays, `==` for the rest).

**Assumptions:** None.

#### `test_pns_levels_for_refuses_both_gradient_asc_and_hardware`

**Checks:** `pns_levels_for` with `gradient_asc` and `hardware` together raises
`ValueError`, and does not run the SAFE model.

**How:** The test patches `pns.pns_levels` as in the tests below, calls
`pns_levels_for` with both inside `pytest.raises(ValueError, match="not both")`, and
checks that the patch recorded no call.

**Assumptions:** None.

#### `test_pns_levels_for_keeps_one_result_for_equal_hardware_pairs`

**Checks:** Two `hardware` pairs with the same label and the same field values, with two
different struct objects, are one hardware: the second call runs no model and gives the
kept result.

**How:** The test patches `pns.pns_levels` as above and calls `pns_levels_for(seq,
hardware=(safe_example_hw(), "LABEL"))` two times, each with a new struct. It checks
that there was 1 call and that the second result `is` the first.

**Assumptions:** None.

#### `test_pns_levels_for_computes_again_for_another_label_or_value`

**Checks:** A `hardware` pair with another label, or with one other field value, runs
the model; going back to an earlier pair does not run it again.

**How:** The test patches `pns.pns_levels` as above and calls with the pairs a, a, b (the
label "B"), c (`z.stim_thresh` plus 1), a, c, each with a new struct where the values are
the same. It checks the call count after each change: 1, 1, 2, 3, 3.

**Assumptions:** None.

#### `test_pns_levels_for_hardware_pair_is_not_the_example_hardware_or_a_file`

**Checks:** A `hardware` pair has its own key: the example hardware (no argument), a
`.asc` file, and a pair with the values and the label of the example hardware are three
hardwares of one sequence. Each runs the model one time.

**How:** The test patches `pns.pns_levels` as above, and calls the three two times in
the same order. It checks that there were 3 calls.

#### `test_pns_levels_for_keeps_one_result_for_each_tuple_of_thresholds`

**Checks:** The thresholds are part of the key of a kept result: other thresholds, or
the same ones in another order, run the model and do not give the result of the default
(no threshold, the key `()`); the same thresholds again give the kept result (the same
object); an `int` threshold is the key of the equal `float`.

**How:** The test patches `pns.pns_levels` as above and calls `pns_levels_for(seq)`, then
`thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`, again the same, the default again, `()`,
`(round(_LIMIT), 0.5 * _LIMIT)` (an `int` that equals `_LIMIT` as a float, which the test
checks), and the two thresholds in the other order. It checks that the call count is 1
after the default, 2 after the two thresholds and still 2 after the repeats, the call with
`()` and the call with the `int`, and 3 after the other order. It also checks that the
second result is not the first, that the repeated results are the same objects as the kept
ones (the `int` call gives the second result), and that `list(result.above)` is `[]`,
`[_LIMIT, 0.5 * _LIMIT]` and `[0.5 * _LIMIT, _LIMIT]`.

**Assumptions:** None.

#### `test_pns_levels_for_shares_a_read_only_result`

**Checks:** Two callers of `pns_levels_for` get the same kept result. A change in place
of its level by the first caller raises `ValueError`, and the second caller gets the
level as it was.

**How:** The test calls `pns_levels_for` for the synthetic spin echo and keeps a copy of
`level_min_hz_per_t` and `level_max_hz_per_t`. `level_max *= 100` (through a local name,
so that the statement does not also assign the field of the frozen dataclass) and
`level_min_hz_per_t[0] = 0.0` must each raise `ValueError`. A second call must give the same
object, with arrays equal to the copies.

**Assumptions:** None.

### 2.8 Series (`test_series.py`)

`test_series.py` tests `series.py`: `Series`, the JSON-ready form of an analysis value
(design section 4.2, with the names of `docs/plans/series-coordinate.md`), with its four
kinds (`SAMPLES`, `ENVELOPE`, `POINTS` and `RUNS`), and `encode_array` and `decode_array`,
which write one numpy array as `{"dtype", "length", "data"}`. The encoding is the one of
`encode_tables` of pulseq-reports (commit `a322517`): the little-endian bytes of the array,
gzipped and base64-encoded.

The tests build small series by hand, with no sequence and no pypulseq. The round trip
of a series is `Series.from_obj(json.loads(json.dumps(s.to_obj(), allow_nan=False)))`,
the path that a report takes.

**Assumptions for the whole file:**

- The tests compare `encode_array` with the pulseq-reports encoding only through the
  fixed texts of `test_encode_array_gives_the_fixed_text`. They do not import
  pulseq-reports.
- The gzip bytes depend on the version of zlib. The Nix devShell fixes it, so a local
  run and CI use the same zlib.

#### `test_series_refuses_a_bad_field`

**Checks:** A series with a name that is not a string or is empty, a kind that is not a
`SeriesKind`, a unit that is not a string, a `coord_unit` that is not a string (IDs
`coord-unit-not-a-string`) or is empty (`coord-unit-empty`), a `coord_step` that is missing,
zero, negative, infinite, NaN, a string or a bool, or a `coord_start` that is not a number,
raises `TypeError` (a wrong type) or `ValueError` (a wrong value).

**How:** Parametrized. Each case changes one field of a valid SAMPLES series and checks
that the constructor raises the named error.

**Assumptions:** None.

#### `test_series_refuses_a_field_that_the_kind_does_not_use`

**Checks:** A SAMPLES series with `coord_end`, and a POINTS or RUNS series with a
`coord_start` other than 0 (also NaN), a `coord_step` or a `coord_end`, raises
`ValueError`, so that each kind has one form. The same series with the defaults is valid.

**How:** Parametrized. Each case first builds a valid series of the kind with its necessary
fields only, then sets one field that the kind does not use and checks for `ValueError`
whose message says that the series "does not use" the field.

**Assumptions:** ENVELOPE uses all three fields, so it has no case here.

#### `test_envelope_refuses_a_missing_end`

**Checks:** An ENVELOPE series without `coord_end` raises `ValueError`.

**How:** The test builds the arguments of a valid ENVELOPE series, leaves out `coord_end`,
and checks the error and that its message names `coord_end`.

**Assumptions:** None.

#### `test_series_refuses_bad_arrays`

**Checks:** A series raises when a necessary array of its kind is missing (for each kind),
when an ENVELOPE has an array other than `min` and `max`, when `arrays` is not a mapping
or has a key that is not a string, when an array is not a numpy array, is zero-dimensional
or two-dimensional, or has a string, object or datetime dtype, and when two arrays have
two lengths (for SAMPLES, ENVELOPE and RUNS).

**How:** Parametrized. Each case builds a series of one kind with the bad `arrays` (with
the valid `coord_step` and `coord_end` that the kind uses) and checks for `TypeError` or
`ValueError`, as the wrong type or the wrong value.

**Assumptions:** The test does not try each necessary array of each kind with a bad
dtype, only the dtypes in the list.

#### `test_series_refuses_bad_meta`

**Checks:** A series raises when `meta` is not a mapping, has a key that is not a string,
has a value that is a list, a dict or a numpy number, or has the string value "inf",
"-inf" or "nan".

**How:** Parametrized. Each case builds a valid SAMPLES series with the bad `meta` and
checks for `TypeError` (a wrong type) or `ValueError` (the three strings). The rules are
the rules of `Finding.data` in pulseq-checks.

**Assumptions:** None.

#### `test_series_copies_arrays_and_meta`

**Checks:** A change to the `arrays` dict, to the `meta` dict, or to one of the arrays
that the caller gave does not change the series, and the series keeps the order of the
arrays that the caller gave.

**How:** The test builds a series from a dict of three arrays (the necessary one first,
then two more) and a `meta` dict. It then adds and removes an array in the dict, changes
and adds a `meta` key, and writes into the caller's `value` array. It checks that the
array names and their order, `meta`, and the first value of `value` are as they were, and
that the series has other dict objects.

**Assumptions:** The series keeps a copy of each array, not a view, so a change to the
caller's array does not reach it. The docstring of `Series` says so.

#### `test_series_arrays_are_read_only_and_the_callers_array_is_not`

**Checks:** Each array of a series is read-only, and the array that the caller gave stays
writable.

**How:** The test builds a series, checks the `writeable` flag of its array, and checks
that a write into it raises `ValueError`. It then checks that the caller's array is still
writable, writes into it, and checks that the series is unchanged.

**Assumptions:** None.

#### `test_series_keeps_native_byte_order`

**Checks:** A big-endian array is kept as a native-byte-order array of the same type of
number, so the round trip gives an equal series.

**How:** The test builds a series from an array with dtype `>f4`, checks that the dtype
of the stored array is `float32` (native), and checks that the round trip equals the
series.

**Assumptions:** The machine is little-endian. On a big-endian machine the native dtype
is `>f4`, and the first check is the same, but it does not test a change of byte order.

#### `test_series_equal_treats_nan_as_equal`

**Checks:** Two series with NaN in an array, in `coord_start` and in a `meta` value are
equal, a series equals itself, and `!=` is false for them.

**How:** The test builds two series from equal data with a NaN in each of the three
places and checks `==` and `!=`.

**Assumptions:** None.

#### `test_series_not_equal_for_a_different_field_or_array`

**Checks:** A series is not equal to a series with another array dtype, another array
length, another value, NaN in place of a number, another name, unit, `coord_unit` (ID
`coord-unit`, "Hz" in place of "s"), `coord_start`, `coord_step`, `meta` or kind, and not
equal to a value that is not a series.

**How:** Parametrized. Each case builds one series that differs from a base SAMPLES series
in one thing, and checks `!=`. The test also checks `!=` of the base series and a string.

**Assumptions:** None.

#### `test_envelope_series_not_equal_for_a_different_end`

**Checks:** Two ENVELOPE series that differ only in `coord_end` are not equal.

**How:** The test builds an ENVELOPE series, copies it with `dataclasses.replace` and
another `coord_end`, and checks `!=`. A SAMPLES series cannot have `coord_end`, so the case
is not in the parametrized test above.

**Assumptions:** None.

#### `test_series_equality_compares_the_order_of_the_arrays`

**Checks:** Two series with the same arrays in a different order are not equal, but two
series with the same `meta` keys in a different order are equal.

**How:** The test builds each pair and checks `==` or `!=`.

**Assumptions:** The order of the `meta` keys does not matter for `==`, but `to_obj` keeps
it. The docstring of `Series` says so.

#### `test_series_equality_compares_the_type_of_a_meta_value`

**Checks:** A `meta` value 1 (an int) is not equal to 1.0 (a float) or to True (a bool).

**How:** The test builds series that differ only in this value and checks `!=`.

**Assumptions:** None.

#### `test_series_is_not_hashable`

**Checks:** `hash` of a series raises `TypeError`.

**How:** The test calls `hash` in `pytest.raises` and matches "unhashable".

**Assumptions:** None.

#### `test_series_round_trip_for_each_kind`

**Checks:** For a series of each of the four kinds, the strict JSON text of `to_obj` is read
by `from_obj` as a series equal to the original, with the arrays in the same order, and
`to_obj` of the result equals `to_obj` of the original.

**How:** Parametrized over one series of each kind: SAMPLES, ENVELOPE (with `meta` of a
string, a float, an int and a bool), POINTS (with an extra `uint32` array and a `None` in
`meta`) and RUNS (with an extra `int64` array). Each goes through `json.dumps` with
`allow_nan=False` and `json.loads`.

**Assumptions:** None.

#### `test_series_round_trip_of_two_million_float32_values`

**Checks:** A SAMPLES series of 2 × 10⁶ float32 values with a second array of int16
values gives an equal series after the round trip, with the same dtypes.

**How:** The test makes random values with a fixed seed, builds the series, and checks the
round trip, the dtype of each array, and that the values are equal.

**Assumptions:** The size is a check of the time and the memory of the path, not of a
limit. The test has no time limit.

#### `test_series_round_trip_of_values_that_are_not_finite`

**Checks:** Infinity and NaN in an array, in `coord_start` and `coord_end`, and in `meta`
survive the round trip, `to_obj` writes the floats of the fields and of `meta` as "inf",
"-inf" and "nan", and `json.dumps(allow_nan=False)` accepts the object.

**How:** The test builds an ENVELOPE series with the four kinds of value in the arrays,
`coord_start` of -infinity, `coord_end` of NaN, and `meta` with infinity, -infinity, NaN,
a finite float and the string "nan?" (a string that is not one of the three). It checks
the strings in `to_obj`, that `json.dumps` accepts the object, that the round trip is
equal, and that the non-finite values are floats again.

**Assumptions:** None.

#### `test_to_obj_keys_and_types`

**Checks:** `to_obj` has the keys `name`, `kind`, `unit`, `coord_unit`, `coord_start`,
`coord_step`, `coord_end`, `meta` and `arrays` in this order. `kind` is the string value,
and `coord_unit` is the string of the series. A `meta` int stays an int, a bool stays a
bool and a float stays a float, also after `json.dumps` and `json.loads`. `arrays` has the
arrays in their order, each as `dtype`, `length` and `data`. A `coord_step` that the kind
does not use is null.

**How:** The test calls `to_obj` on an ENVELOPE and on a RUNS series and checks the keys,
their order, `coord_unit`, the types of the `meta` values, and the null `coord_step` of the
RUNS series.

**Assumptions:** None.

#### `test_from_obj_refuses`

**Checks:** `from_obj` raises `ValueError` (and no other error) for an object that is not
a dict, an unknown key, a missing key (also `coord_unit`, ID `missing-coord-unit`), an
object of rc2 (ID `rc2-object`), an unknown kind or a kind that is not a string, an empty
name, a name or unit that is not a string, a `coord_unit` that is null or a number (IDs
`coord-unit-null` and `coord-unit-a-number`), a `coord_step` that is zero, a string or
null, a null `coord_end` or `coord_start`, a `coord_start` that is a bool, a `meta` or
`arrays` that is not an object, a `meta` value that is a list, and an array that is not an
object or an object with no arrays.

**How:** Parametrized. Each case changes or removes one key of the `to_obj` of a valid
ENVELOPE series and checks for `ValueError`. The case `rc2-object` has no `coord_unit` and
the rc2 keys of the three coordinate fields, with their values, so it also has unknown
keys. The `TypeError` of the series is a `ValueError` here, so a caller catches one type.

**Assumptions:** None.

#### `test_series_with_a_coordinate_other_than_time`

**Checks:** A spectrum (SAMPLES, `coord_unit` "Hz"), the two frequency ranges where it is
above a level (RUNS, "Hz"), its peaks (POINTS, "Hz") and a profile along a position
(SAMPLES, "m", with a NaN and a complex array) each give an equal series after the round
trip, and `to_obj` keeps `coord_unit`.

**How:** The test builds the four series from synthetic data, in the forms of section 1.2 of
`docs/plans/series-coordinate.md`. For each one it checks `coord_unit`, the `coord_unit` of
`to_obj`, and that the round trip through strict JSON text is equal. It also checks that the
`a` array of the profile is `complex128` and that its `coord_start` survives.

**Assumptions:** The data are synthetic. They are not the output of a spectrum or a
profile of pulseq-reports, which the tests do not import. A spectrum or a profile uses the
same kinds as a time series.

#### `test_encode_array_gives_the_same_text_each_time`

**Checks:** One array encoded two times gives the same dict, a copy of it gives the same
dict, an array of the other byte order (`>f4`) gives the same dict, and a strided view
gives the dict of its copy. The gzip header has no time stamp, its OS byte is 255, and
the data decompress to the little-endian bytes.

**How:** The test encodes a float32 array with 1000 values in each form and compares the
dicts. It decodes the base64 text and checks bytes 4 to 7 and byte 9 of the header, and
that `gzip.decompress` gives `a.tobytes()`.

**Assumptions:** The machine is little-endian, so `a.tobytes()` is the little-endian
bytes.

#### `test_encode_array_gives_the_fixed_text`

**Checks:** `encode_array` gives the text that `encode_tables` of pulseq-reports gave for
the same array, for a float32 array with finite and non-finite values and for an int64
array. `decode_array` of the text gives the array back.

**How:** Parametrized over the two arrays. The expected dicts are literals in the test,
made by running `encode_tables` of pulseq-reports at commit `a322517` (in
`src/pulseq_reports/diagram_data.py`). The test compares the dict, and decodes the dict and
compares the array (NaN equal).

**Assumptions:**

- The literals are correct for `encode_tables` at that commit. The test does not run
  pulseq-reports.
- The gzip bytes depend on the version of zlib. The Nix devShell fixes it, so a local run
  and CI use the same zlib. A different zlib can give other bytes for the same data, and
  the test then fails with no fault in the code.

#### `test_decode_array_gives_back_the_array`

**Checks:** For each of the dtypes bool, int8 to int64, uint8 to uint64, float16, float32,
float64, complex64 and complex128, and for an empty array, `decode_array` of `encode_array`
gives an equal array, with the same dtype, in native byte order, that is writable, and that
is not the original object.

**How:** Parametrized over the dtypes. The test makes 33 random values, converts them to
the dtype, and checks each property for the array and for its empty slice.

**Assumptions:** None.

#### `test_encode_array_refuses_a_bad_array`

**Checks:** `encode_array` raises `TypeError` or `ValueError` for a list, a two-dimensional
array, an array of strings and an array of objects.

**How:** Parametrized. The test calls `encode_array` in `pytest.raises` for each.

**Assumptions:** None.

#### `test_decode_array_refuses`

**Checks:** `decode_array` raises `ValueError` for a value that is not a dict, a dict with
a missing key or an unknown key, a `length` that is too large, too small, negative, a float
or a bool, a dtype that is `object`, `datetime64[s]`, a string dtype, an unknown name, a
short name (`f4`) or not a string, `data` that is not a string, not base64, not gzip or cut
short, and data with a number of bytes that is not a whole number of items, more than
`length` or fewer than `length`.

**How:** Parametrized. Each case changes one key of a valid dict (or builds a gzip text of
zero bytes) and checks for `ValueError`.

**Assumptions:** The test does not check each byte of a damaged gzip stream, only the cases
in the list.

### 2.9 Analyses (`test_analyses.py`)

`test_analyses.py` tests `analyses.py`: the entry-point registry of the group
`pulseq_analysis.analyses`, the specification of each of the five analyses of the package
(`seq.index`, `gradient.limits`, `gradient.blocks`, `pns.safe.levels` and `gradient.spectrum`),
`compute`, and `to_series` of `pns.safe.levels` and `gradient.spectrum` (design section 4.4 of
the plan of pulseq-analysis).

The registry tests that need two packages, a broken entry point or an object without
`spec.id` replace `importlib.metadata.entry_points` with a function that gives fake entry
points (an object with a `name`, a `dist` with the package name, and a `load`). The test of
the real registry uses the entry points that `uv sync` installs from `pyproject.toml`. The
tests of the series use `gre_sequence(num_trs=20)` with the example hardware of pypulseq, with
the stimulation limit multiplied so that the peak is 1.5 times `_LIMIT`, so that the total is
above `_LIMIT` in several runs (`hardware_for_peak` of `tests/pns_hardware.py`). `_LIMIT` is
`PNS_LIMIT * GAMMA_1H`, the stimulation limit for 1H in Hz/T: a PNS value and a threshold are
in Hz/T. The test of the spectrum series
uses `spin_echo_sequence()`.

**Assumptions for the whole file:**

- The package is installed in the environment of the tests, with its entry points: a run
  of `pytest` without `uv sync` after a change of the entry points in `pyproject.toml`
  fails the test of the real registry.

#### `test_the_registry_has_the_five_analyses_of_the_package`

**Checks:** With the installed entry points, `registry()` has the five IDs
`gradient.blocks`, `gradient.limits`, `gradient.spectrum`, `pns.safe.levels` and `seq.index`, no other ID, each
with the object of this package, and each key is the `spec.id` of its analysis.

**How:** The test calls `registry()` and compares the sorted keys, the identity of each value
with `SEQ_INDEX`, `GRADIENT_LIMITS`, `GRADIENT_BLOCKS`, `PNS_SAFE_LEVELS` and
`GRADIENT_SPECTRUM`, and each key with `spec.id`.

**Assumptions:** No other installed package gives an analysis (the test environment has only
this package).

#### `test_two_analyses_with_one_id_raise_an_error_that_names_both_packages`

**Checks:** Two entry points whose analyses have the same ID raise `RegistryError`, and the
message has the ID and the names of the two packages.

**How:** The test makes two fake entry points with two analyses of the ID `t.a`, from the
packages `pkg-one` and `pkg-two`, and checks the message of the error that `registry()`
raises.

**Assumptions:** None.

#### `test_an_entry_point_that_cannot_load_raises_an_error_that_names_it`

**Checks:** An entry point whose `load` raises gives a `RegistryError` with the name of the
entry point, the name of its package, and the type and the text of the exception.

**How:** The test makes one fake entry point whose `load` raises `ImportError("no module named
foo")`, and checks the message of the error that `registry()` raises.

**Assumptions:** None.

#### `test_an_entry_point_without_a_spec_id_raises_an_error_that_names_it`

**Checks:** An entry point whose object has no `spec`, and one whose `spec` has no `id`, give
a `RegistryError` with the name of the entry point and the name of its package.

**How:** For each of the two objects (`object()` and a namespace with an empty `spec`), the
test makes one fake entry point and checks the message of the error that `registry()` raises.

**Assumptions:** None.

#### `test_the_spec_of_each_analysis_has_the_documented_values`

**Checks:** The ID, the version 1, `params`, `rasters` and `cost` of each analysis are the
values of section 8.3 of `docs/plans/implementation.md`. The title and the description are not
empty. `series` is None for `seq.index`, `gradient.limits` and `gradient.blocks`, and a text
for `pns.safe.levels` and `gradient.spectrum`.

**How:** Parametrized over the five analyses. The test compares each field with the table of
the plan, which the test file holds as a list.

**Assumptions:** The test does not check the words of the title, the description or the text
of `series`: they are for a reader.

#### `test_params_name_the_keyword_only_parameters_of_compute`

**Checks:** The parameters of `compute` after `seq` are all keyword-only, their names are
`spec.params` in order, and their defaults are those of the function that `compute` calls
(`None` and `()` for `pns.safe.levels`, whose parameters are `hardware` and
`thresholds_hz_per_t`). `seq.index`, `gradient.limits`,
`gradient.blocks` and `gradient.spectrum` have no parameter, so no default: there are no gamma
defaults. A keyword that is not a parameter is a `TypeError`.

**How:** Parametrized over the five analyses. The test reads `inspect.signature(compute)`, and
calls `compute` on `empty_sequence()` with `unknown=1`.

**Assumptions:** None.

#### `test_compute_gives_the_value_of_its_function_with_the_same_arguments`

**Checks:** `compute` of each analysis gives the value of the function that it calls, with
the same arguments, with the defaults and with others (a hardware with
`thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`). `seq.index`, `pns.safe.levels` and `gradient.spectrum` give the same
object as `sequence_index`, `pns_levels_for` and `gradient_spectrum_for`, which keep their
result for the sequence object. `gradient.spectrum` has no other arguments. The gradient
analyses have no arguments after `seq`: `gradient_limits(seq)` and `block_gradient_values(seq)`
give an equal value.

**How:** The test builds `gre_sequence(num_trs=4)` and compares `compute` with the function:
`is` for the kept results, `==` for `GradientLimits`, and `numpy.array_equal` for each array of
`BlockGradientValues` (the block IDs, the starts, the vector peak and its time, and for each
axis the peak, the slew, the junction step and the times of the peak and of the slew).

**Assumptions:** `BlockGradientValues` has no `__eq__` for its arrays, so the test compares
each array one by one. `GradientSpectrum` is compared by identity only.

#### `test_the_pns_series_equal_the_level_and_the_runs_of_the_same_call`

**Checks:** For a sequence with more than one run above `_LIMIT` and `thresholds_hz_per_t=(_LIMIT,)`,
`to_series` gives `pns_total`, an ENVELOPE of unit "Hz/T" with the arrays `min` and `max`
(float32) equal to `level_min_hz_per_t` and `level_max_hz_per_t`, `coord_unit` "s",
`coord_start` 0, `coord_step` `bin_samples * dt_s`, `coord_end` `num_samples * dt_s`, and the
`meta` of design 4.4 (`hardware`, `asc_file`, `dt_s`, `bin_samples`, `num_samples`, `peak`,
`peak_time_s` and the three `axis_peaks_*`, the values from `peak_hz_per_t` and
`axis_peaks_hz_per_t`). It gives `pns_above_0`, a RUNS series of unit "Hz/T"
and `coord_unit` "s", with the arrays `start`, `end`, `num_samples` (int64), `peak` and `peak_time_s` (float64),
in this order, with one entry for each interval of `above[_LIMIT]` (`start` and `end` are
`start_s` and `end_s` of the interval, `peak` is `peak_hz_per_t`) and the `meta`
`{"threshold": _LIMIT}`. For a `PnsLevels` of a gradient `.asc` file, `meta["hardware"]` is the
name in the file and `meta["asc_file"]` is the file name.

**How:** The test calls `compute` with the hardware of `hardware_for_peak(seq, 1.5)` (`tests/pns_hardware.py`) and
`thresholds_hz_per_t=(_LIMIT,)`, and compares each field of `to_series` with the field of the same `PnsLevels` (`numpy.array_equal`
for the arrays, `tolist` for the intervals). For the file it writes a gradient `.asc` file with
the `write_gradient_asc` fixture and calls `pns_levels` with it.

**Assumptions:** The test does not build the expected `Series` with the code under test: each
field is compared by itself.

#### `test_the_pns_series_of_two_thresholds_are_in_the_order_of_the_thresholds`

**Checks:** With `thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`, `to_series` gives
`pns_total`, `pns_above_0` and `pns_above_1`, in this order, of the kinds ENVELOPE, RUNS and
RUNS, and the `coord_unit` of each RUNS series is "s". The `start`, `end` and `peak` of each
RUNS series are those of `above` of its threshold (`start_s`, `end_s` and `peak_hz_per_t` of
the intervals), which are not empty and not equal. With the thresholds in the other order,
the names are the same (they are the positions of the thresholds): the two RUNS series swap
their runs and their `meta`.

**How:** The test calls `compute` with the hardware for the peak 1.5 times `_LIMIT`, and
compares the names, the kinds, the `meta` and the arrays with `levels.above`. For the swapped
thresholds, it compares the names, the `meta` and the `start` array of each RUNS series with
those of the first call.

**Assumptions:** None.

#### `test_the_pns_series_survive_the_json_round_trip`

**Checks:** Each series of `to_series` (the ENVELOPE and two RUNS series, for the thresholds
`_LIMIT` and `0.8 * _LIMIT`) is equal to the series that `Series.from_obj` reads from the text of
`json.dumps(s.to_obj(), allow_nan=False)`.

**How:** The test writes and reads each series and compares it with `==` (the `Series`
equality).

**Assumptions:** None.

#### `test_to_series_gives_nothing_for_a_sequence_without_gradients`

**Checks:** For `empty_sequence()` the `PnsLevels` has a `reason` (`NO_GRADIENTS`), and
`to_series` gives `()`, with no threshold, with one threshold and with two thresholds.

**How:** The test calls `compute` and `to_series` for each of the tuples `()`, `(_LIMIT,)`
and `(_LIMIT, 0.5 * _LIMIT)`.

**Assumptions:** None.

#### `test_the_pns_series_without_thresholds_are_the_level_only`

**Checks:** With the default thresholds (`()`), `to_series` gives one series, `pns_total`,
an ENVELOPE whose `max` array is `level_max_hz_per_t` of the same call, and `above` is
empty.

**How:** The test calls `compute` on `gre_sequence(num_trs=4)` with the hardware for the peak
1.5 times `_LIMIT` and no `thresholds_hz_per_t`, then `to_series`.

**Assumptions:** None.

#### `test_the_spectrum_series_equals_the_spectrum_of_the_same_call`

**Checks:** For `spin_echo_sequence()`, `to_series` of `gradient.spectrum` gives one series,
`gradient_spectrum`, of the kind SAMPLES, the unit "Hz/m/sqrt(Hz)" and `coord_unit` "Hz". Its
arrays are `value`, `x`, `y` and `z` in this order, all float64, equal to `rss` and to the three
axes of the same spectrum. `coord_start` is 0.0 and `coord_step` is `frequency_hz[1]`, and
`coord_start + k * coord_step` is `frequency_hz` bit for bit. The `meta` is
`max_frequency_hz`, `window_s` and `frequency_oversampling`, with the defaults of
`gradient_spectrum_for`. For a spectrum of `window_s=0.1`, the `meta` has `window_s` 0.1: the
`meta` comes from the value, not from the defaults.

**How:** The test calls `compute` and `to_series` and compares each field by itself.
It compares the arrays with `numpy.array_equal`, and the frequencies with an `arange` of the
length of `frequency_hz`.

**Assumptions:** The test does not build the expected `Series` with the code under test. It
checks that the spectrum is not all zero, so that equal arrays are not empty of signal.

#### `test_the_spectrum_series_of_a_sequence_without_gradients_is_empty`

**Checks:** For `empty_sequence()` the `GradientSpectrum` has `reason == NO_GRADIENTS`, and
`to_series` gives `()`.

**How:** The test calls `compute` and `to_series`.

**Assumptions:** None.

#### `test_the_other_three_analyses_give_no_series`

**Checks:** `to_series` of `seq.index`, `gradient.limits` and `gradient.blocks` gives `()`,
for a sequence with gradients and for one without.

**How:** For `gre_sequence(num_trs=2)` and `empty_sequence()`, the test gives the value of
`compute` to `to_series`.

**Assumptions:** None.

### 2.10 Gradient spectrum (`test_grad_spectrum.py`)

The spectrum is calculated as in pypulseq: Hann windows (50 ms by default) with
50 % overlap, the magnitude spectrum of each window, and the maximum over
windows. Here the gradients are sampled to the end of the sequence, with half a
window of zeros added at each end. The RSS spectrum is the root-sum-of-squares
of the three axes in each window, then the maximum over windows. The values are
in Hz/m/√Hz, the unit of the gradients of a `.seq` file, with no gamma. To get
mT/m/√Hz, a caller multiplies the values by `1e3 / gamma`. The gradients are
sampled through the raster sampler (`sampling.GradientSampler`), in chunks of
`CHUNK_WINDOWS` windows, so the memory does not grow with the sequence length.
`tests/oracles/grad_spectrum.py` is the module before the raster sampler,
sampling through `Sequence.get_gradients()` instead. It gives mT/m/√Hz with
`seq.system.gamma`. The oracle comparison multiplies this module's values by
`1e3 / seq.system.gamma`, so it also tests the conversion. The tests call the
oracle with no resonances. The oracle is a copy of the file of pulseq-reports,
and it still has the code for the resonance bands.

Several tests use a 1 mT/m sine on x, on the synthetic system. On a frequency
bin, a Hann window gives an amplitude spectral density of
(A/2) × Σw / √(fs × Σw²). With 5000 samples at 100 kHz, that is the expected
peak for A = 1 mT/m. The test file multiplies it by `1e-3 * gamma` to get the
peak in Hz/m/√Hz (`SINE_PEAK`).

**Assumptions for the whole file:**

- The test sine frequency (600 Hz) is exactly on a frequency bin, and each
  window holds a whole number of cycles. So there is no scalloping loss, and
  the peak is the full value.
- The tests do not compare the result with vb-pulseq. Parity with vb-pulseq
  (rtol 1e-12, several chunk sizes) was checked outside CI when this module
  moved from vb-pulseq.

#### `test_spin_echo_spectrum`

**Checks:** For the synthetic spin echo, the spectrum runs from 0 to 2 kHz, the
x and y axes have a non-zero spectrum, and the RSS is at least each axis at
every frequency.

**How:** The test calculates the spectrum of the synthetic spin echo. It
checks that there is no reason, that the frequencies start at 0 and end at
2 kHz, and that there are x, y and z spectra. The x and y spectra must have a
maximum above 0 (the synthetic spin echo has no z gradient). Each axis
spectrum must have the same length as the frequencies, and the RSS must be at
least that axis at every frequency.

**Assumptions:** None.

#### `test_sine_peak_is_at_its_frequency`

**Checks:** A 600 Hz sine gives an RSS peak at 600 Hz with the expected
amplitude in Hz/m/√Hz.

**How:** The test makes a 0.5 s, 1 mT/m, 600 Hz sine on x. The RSS peak must
be at 600 Hz, with a value within 1 % of `SINE_PEAK`.

**Assumptions:** None.

#### `test_short_sequence_is_padded_to_one_window`

**Checks:** A sequence shorter than one window still has a spectrum, with its
peak at the sine frequency.

**How:** The test makes a 20 ms, 600 Hz sine. There must be no reason, and the
RSS peak must be within 20 Hz of 600 Hz.

**Assumptions:**

- A 20 ms sine has a wide spectral peak, so the tolerance is wider than one
  frequency bin.

#### `test_gradients_at_the_end_are_not_attenuated`

**Checks:** A sine at the end of the sequence has its full amplitude in the
spectrum.

**How:** The test makes a sequence with 440 ms of no gradient and then 60 ms
of a 600 Hz sine, so the last sample is at the end of the sequence. The RSS
peak must be within 2 % of `SINE_PEAK`.

**Assumptions:**

- The sine is 60 ms long, so at least one 50 ms window is fully inside it and
  the full amplitude is expected. The test fails if the gradient samples near
  the end of the sequence are lost, or are only at the edge of a window.

#### `test_no_gradients`

**Checks:** A sequence without gradients has no spectrum, with the reason
"no gradients", empty frequencies and RSS, and no axes.

**How:** The test makes a sequence with only a block pulse. It checks the
reason, that `frequency_hz` and `rss` have shape (0,), and that `axes` is `{}`.

**Assumptions:** None.

#### `test_chunks_give_the_same_spectrum_as_one_chunk`

**Checks:** The spectrum does not depend on the chunk size.

**How:** The test makes a synthetic GRE sequence of 30 TRs of 20 ms (600 ms,
25 windows). It calculates the spectrum with `CHUNK_WINDOWS` set to 1,000,000
(one chunk) and to 4 (7 chunks, the last one shorter). The frequencies must be
equal, and each axis spectrum and the RSS must agree with a relative tolerance
of 1e-12.

**Assumptions:**

- The results are not always bit-for-bit equal, because scipy computes the
  FFTs of a different number of windows in each call. The tolerance allows for
  that rounding.

#### `test_matches_scipy_spectrogram`

**Checks:** `gradient_spectrum` makes the FFTs itself, for the kept bins only
(`_chunk_spectrogram`). This test checks that its axis spectra and RSS equal
those made with scipy's `spectrogram`, the call that the module used before and
that pypulseq's `calculate_gradient_spectrum` uses, on the synthetic spin echo,
a GRE of 30 TRs and the arbitrary-gradient sequence.

**How:** The test sets `CHUNK_WINDOWS` to 4, so the sequences make several
chunks, and calculates the spectrum. For the reference, it samples each axis
with `GradientSampler` at the sample times of the module, pads half a window of
zeros at each end, and calls `scipy.signal.spectrogram` on the whole padded
waveform with `mode="magnitude"`, `nperseg=nwin`, `noverlap=nwin // 2`,
`nfft=nfft`, `detrend="constant"`, `window=("tukey", 1)` and `fs=1 / dt`. It
keeps the bins up to `MAX_FREQUENCY_HZ + 1e-6`, takes the maximum over windows
for each axis, and the root-sum-of-squares of the axes in each window and then
the maximum for the RSS. The frequencies must be equal. Each axis spectrum and
the RSS must agree within an absolute 1e-12 times the largest value of the same
array (so a zero axis must be exactly 0).

**Assumptions:**

- The test compares the whole function, so it covers the windows, the detrend,
  the window function and the scale of the new code, and the joins of the
  chunks. The reference does not use the chunks, the strided windows or the
  scale of the module. The samples come from the same sampler, and the time rule
  `(i + 0.5) * dt` is the module's own. The oracle tests check the sampler
  against `Sequence.get_gradients()`.
- The result differs from scipy's only by float rounding (measured: 4.6e-16 of the
  peak on `build_repeating(10000)`), because the two take the FFTs of the same windows with a
  different order of operations.

#### `test_matches_oracle_on_synthetic_sequences`

**Checks:** The raster sampler replaced `Sequence.get_gradients()` in
`gradient_spectrum`. This test checks that the axis spectra and the RSS
spectrum, times `1e3 / gamma`, still agree with the oracle
(`tests/oracles/grad_spectrum.py`, the module before that change), on the
synthetic spin echo, GRE, arbitrary-gradient, empty and 600 Hz sine
sequences.

**How:** For each sequence, the test calculates the spectrum with this
module and with the oracle. The reasons must be equal. When there is a
spectrum, the frequencies must be equal. The axis spectra and the RSS of this
module, multiplied by `1e3 / seq.system.gamma`, must agree with the oracle
within a relative 1e-12 or an absolute 1e-12 times the array's own peak.

**Assumptions:**

- The sampler builds the waveform from each block's own corner points and
  `numpy.interp`, a different order of float operations than
  `Sequence.get_gradients()`'s one whole-axis `PPoly`, so the values are not
  always bit-for-bit equal (section 3.5, item 2 of
  `docs/plans/cards-at-scale.md` of pulseq-reports).
- The multiplication by `1e3 / gamma` is exact only to the float rounding, and
  the tolerance allows for it.
- The long sequences are in `test_matches_oracle_on_long_sequences`, with a
  tolerance that grows with the duration.

#### `test_matches_oracle_on_long_sequences`

**Checks:** The same comparison with the oracle as
`test_matches_oracle_on_synthetic_sequences`, on the builders of
`tests/scale_sequences.py` (`build_repeating` and `build_worst`) at 10^4
blocks.

**How:** The test builds each sequence with `10^4 / TR_BLOCKS` TRs, and
compares this module's spectrum (times `1e3 / gamma`) with the oracle's, as the
test above does, with the tolerance `1e-12 * max(1, duration in s)` instead of
1e-12.

**Assumptions:**

- The user chose this tolerance on 2026-09-28, in the work on pulseq-reports.
  Both implementations place each gradient corner at an absolute time with
  float rounding, in a different order of additions: the sampler adds
  `(block start + delay) + offset`, and `Sequence.get_gradients()` adds the
  segment durations one at a time. The rounding of an absolute time grows with
  the time, and a gradient ramp turns it into a value difference. Measured in
  pulseq-reports: 2.5e-12 of the peak at 10^4 repeating blocks (12 s), 3.6e-12
  at 10^5 blocks. Neither value is more correct.

#### `test_spectrum_does_not_depend_on_the_gamma_of_the_system`

**Checks:** The spectrum depends on the gradient values of the file only, not
on `seq.system.gamma`.

**How:** The test makes one 600 Hz sine waveform in Hz/m. It puts the waveform
in two sequences, one with `SYSTEM` and one with a copy of `SYSTEM` that has
another gamma (0.9 times). It checks that the two gammas differ. The
frequencies, each axis spectrum and the RSS must be exactly equal.

**Assumptions:** None.

#### `test_gradient_spectrum_refuses_rotations`

**Checks:** `gradient_spectrum` raises `NotImplementedError` for a sequence
with the rotation extension.

**How:** The test gives `gradient_spectrum` a GRE sequence with a rotation
library (`with_rotation_library` of `tests/synthetic.py`). The error message
must contain "rotation extension".

**Assumptions:**

- pypulseq 1.5.0.post1 cannot make a rotation, so the test adds a rotation
  library by hand, as `test_gradient_limits_refuses_rotations` does.

#### `test_gradient_spectrum_for_keeps_the_result`

**Checks:** `gradient_spectrum_for` gives the same object for two calls on one
sequence, and a new object after the sequence changed.

**How:** The test calls `gradient_spectrum_for` two times on a GRE sequence of
2 TRs, and checks that the objects are the same (`is`). It then adds a delay
block and checks that the next call gives another object.

**Assumptions:**

- The test changes the number of blocks and the last block id, the changes that
  the kept result sees. A block replaced in place is not seen, as for
  `sequence_index`.

#### `test_the_arrays_of_a_spectrum_are_read_only`

**Checks:** Each array of a spectrum is read-only, also for a sequence without
gradients. A conversion to a new array works.

**How:** The test runs for the synthetic spin echo (the frequencies, the RSS
and the three axes) and for a sequence without gradients (the frequencies and
the RSS, empty). Each array must have `flags.writeable` off, and a change in
place (`a *= 1e3 / GAMMA_1H`, with `GAMMA_1H` from `tests/synthetic.py`) must
raise `ValueError`. Then `s.rss * 1e3 / GAMMA_1H` must give a writable array,
and `s.rss` must not change.

**Assumptions:** None.

#### `test_spectra_compare_by_value`

**Checks:** `==` compares two `GradientSpectrum` objects by the values of their fields,
not by identity. A `GradientSpectrum` is not hashable.

**How:** Two `gradient_spectrum` calls on the synthetic spin echo must give two objects
that are equal, and a `pickle` round trip must give an equal object. Two calls on a
sequence without gradients must give equal objects. The spectrum with `window_s=0.1`, the
spectrum of a sequence without gradients, and a string must not equal the spin echo
spectrum. `hash` must raise `TypeError`.

**Assumptions:** None.

#### `test_the_defaults_are_those_of_pypulseq`

**Checks:** A call with the three arguments at the defaults of pypulseq's
`calculate_gradient_spectrum` gives the same spectrum as a call with no
arguments. The result of a call with no arguments has these defaults in its
fields `max_frequency_hz`, `window_s` and `frequency_oversampling`.

**How:** The test reads the defaults of `max_frequency`, `window_width` and
`frequency_oversampling` from the signature of
`pp.Sequence.calculate_gradient_spectrum`. It gives them as `max_frequency_hz`,
`window_s` and `frequency_oversampling` for the synthetic spin echo. The
frequencies, each axis spectrum and the RSS must be exactly equal to those of a
call with no arguments. The test also compares the three fields of the result
with the defaults.

**Assumptions:**

- The test compares the defaults only. It does not compare the spectrum with
  the spectrum of pypulseq, which differs in the padding and in the start of
  the first window.

#### `test_the_arguments_change_the_frequencies`

**Checks:** `window_s`, `frequency_oversampling` and `max_frequency_hz` change
the frequencies as documented, and the result keeps the arguments of the call
as floats.

**How:** For a 0.5 s, 600 Hz sine, the test calculates three spectra. With
`window_s=0.1`, the frequency step is `1 / (3 * 0.1)` Hz, and the RSS peak is
at 600 Hz. With `frequency_oversampling=1`, the step is `1 / 0.05` Hz. With
`max_frequency_hz=500`, the last frequency is at most 500 Hz. The result of
`window_s=0.1` has the fields 2000.0, 0.1 and 3.0, and the int
`frequency_oversampling=1` becomes a float.

**Assumptions:**

- The sine has a whole number of cycles in a 0.1 s window, so its peak stays on
  a frequency bin.

#### `test_gradient_spectrum_refuses_bad_arguments`

**Checks:** `gradient_spectrum` and `gradient_spectrum_for` refuse each bad
argument with the right error type, before they read the blocks.

**How:** The test runs for both functions. It replaces `sequence_index` of the
module with a function that fails, so a call that reads the blocks fails the
test. Each case gives one bad argument to the synthetic spin echo. The error
must be `TypeError` for a string and for a bool, in each argument. It must be
`ValueError` for NaN and for infinity, in each argument, for `window_s` of 0,
below 0 and of one sample, for a `frequency_oversampling` of 0.5, and for a
`max_frequency_hz` of 0, below 0, above the Nyquist frequency (60 kHz) and
below the frequency step. One case has a `max_frequency_hz` of 10 Hz with
`frequency_oversampling=1`: it is above the step of the defaults and below the
step of 20 Hz of the arguments. The case of one sample also gives
`match="samples at the gradient raster"`, the text of the check `nwin < 2`. The
other cases give no `match`.

**Assumptions:**

- The synthetic sequence has the default gradient raster of 10 µs, so the
  Nyquist frequency is 50 kHz and the step of the defaults is 6.67 Hz.
- The test checks the message text only for the case of one sample. Without it,
  the check of the frequency step (also a `ValueError`) hides a missing check
  `nwin < 2`.

#### `test_gradient_spectrum_for_keeps_one_result_for_each_set_of_arguments`

**Checks:** `gradient_spectrum_for` keeps one result for each tuple of the
three arguments, as floats.

**How:** For a GRE sequence of 2 TRs, the test calls `gradient_spectrum_for`
with no arguments, and then with `max_frequency_hz=1000.0`. The two objects
must be different, and the second has no frequency above 1000 Hz. A call with
no arguments again must give the first object. A call with
`max_frequency_hz=1000` (an integer) must give the second object.

**Assumptions:** None.

### 2.11 Value equality (`test_equality.py`)

`test_equality.py` tests `_equality.py`: `values_equal`, the rules by which two values
are equal, and `fields_equal`, the `__eq__` of `PnsLevels` and `GradientSpectrum`. The
tests use small values and two dataclasses of the test file, not results of the package.
Sections 2.2 and 2.10 test the `==` of the results.

#### `test_values_equal`

**Checks:** `values_equal` follows the rules of the module docstring of `_equality`, in
both orders of its arguments.

**How:** One case for each rule, with the expected result:

- arrays: the same values (equal); another dtype, another shape, another value (not
  equal); NaN at the same place (equal); int, bool and empty arrays (equal); a read-only
  and a writable array with the same values (equal); an array and a list, an array and a
  float (not equal).
- dicts: the same keys and values (equal); the same items in another order (not equal);
  another key (not equal); nested dicts with an array (equal, and not equal when the
  array differs).
- tuples: the same elements (equal); another length, a tuple and a list (not equal).
- dataclasses in a tuple: the same fields (equal); another field (not equal); a NaN field
  (equal).
- scalars: NaN and NaN (equal); `1` and `1.0`, `True` and `1`, `None` and `0.0` (not
  equal); `None` and `None`, two equal strings (equal).

**Assumptions:** None.

#### `test_fields_equal_as_the_eq_of_a_dataclass`

**Checks:** A dataclass with `__eq__ = fields_equal` compares its fields by value, is not
equal to an object of another class, and is not hashable.

**How:** A frozen dataclass of the test file with an array and a dict, with
`eq=False`, `__eq__ = fields_equal` and `__hash__ = None`. Two objects with the same
values must be equal. An object with another array value or another dict value must not
be equal. An object must not equal a string, and `fields_equal(a, "a")` must be
`NotImplemented`. `hash` must raise `TypeError`.

**Assumptions:** None.

### 2.12 Kept results (`test_kept.py`)

`test_kept.py` tests `_kept.py`, the rule that says when the kept results of a sequence
object are old, through `sequence_index`, `pns_levels_for` and `gradient_spectrum_for`.
The tests use small sequences that they write with pypulseq or that
`tests/synthetic.py` builds.

#### `test_a_second_read_into_one_object_gives_the_values_of_a_new_object`

**Checks:** After a second file is read into one `Sequence`, the four measurements give
the values of that file, not the kept values of the first file.

**How:** The test writes two files with pypulseq. Both have 6 blocks. File A has three
times an x trapezoid and a delay of 15 ms. File B has three times a y trapezoid of
another area and a delay of 22 ms. The test reads A into an object, and calls
`sequence_index`, `pns_levels_for` (with pypulseq's example hardware), `gradient_spectrum_for`
and `gradient_limits`. It then reads B into the same object, and reads B into a new
object. The index of the new object must have another `end_s` than the index of A. For the
object that read both files, the index must have the same values as the index of the new
object (each array with `array_equal`), and the levels, the spectrum and the limits must
be equal (`==`) to those of the new object and not equal to those of A.

**Assumptions:**

- A and B are different in the values that the four results hold, so a kept result of A
  is not equal to the result of B.
- `GradientLimits`, `PnsLevels` and `GradientSpectrum` compare by value.

#### `test_pns_levels_for_gives_a_new_result_after_add_block_and_the_same_without_a_change`

**Checks:** `pns_levels_for` keeps its result until a block is added, and then makes it
again.

**How:** For the synthetic spin echo, two calls with the same arguments must give one
object. The test then adds a z trapezoid with `add_block`. The next call must give a new
object, a second call must give that object again, and the new result must be equal to
the result for a second sequence built with the same blocks.

**Assumptions:** None.

#### `test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result`

**Checks:** `pns_levels_for` has one kept result for the relative and the absolute
spelling of one gradient `.asc` file.

**How:** The test writes an `.asc` file, and changes the working directory to its
directory. For each order of the two spellings, on a new sequence, the call with the first
spelling and the call with the second spelling must give one object.

**Assumptions:**

- The file is not changed or replaced between the calls.

#### `test_a_change_of_the_last_block_id_with_the_same_number_of_blocks_gives_a_new_index`

**Checks:** `sequence_index` makes the index again when the last block ID changes and the
number of blocks does not.

**How:** For the synthetic spin echo, two calls must give one object. The test then moves
the first entry of `seq.block_events` and of `seq.block_durations` to a new key, the
largest ID plus 1. The number of blocks is the same. The next call must give a new object,
with the same number of blocks, and with the block IDs of the old index without the first,
then the new ID.

**Assumptions:**

- `seq.block_events` and `seq.block_durations` are dicts that keep their order, as in the
  pinned pypulseq fork.

#### `test_a_change_of_the_gradient_raster_time_gives_a_new_index_and_new_levels`

**Checks:** A change of `seq.grad_raster_time` makes the three kept results again.

**How:** For the synthetic spin echo, the test calls `sequence_index`, `pns_levels_for`
and `gradient_spectrum_for`, and calls each again: each must give the same object. It
then halves `seq.grad_raster_time`. Each of the three must give a new object, and a call
again must give that new object.

**Assumptions:**

- The functions can run with a gradient raster time that is not the raster of the
  blocks. The test does not check the values of the new results.

#### `test_a_kept_result_does_not_keep_the_sequence_alive`

**Checks:** The kept results of `sequence_index`, `pns_levels_for` and
`gradient_spectrum_for` do not keep a reference to the sequence, so the sequence can be
collected.

**How:** For each function, the test calls it for the synthetic spin echo, keeps a
`weakref` to the sequence and the result, deletes the sequence and runs `gc.collect()`.
The `weakref` must be dead.

**Assumptions:**

- CPython collects the sequence at once, or in the `gc.collect()` call. The test does not
  cover another Python.
