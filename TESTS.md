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
2. [Tests](#2-tests): the package; the shared sequence helpers; the PNS levels;
   the sequence extensions; the sequence index; the raster sampler; the gradient
   peaks; the kept PNS levels; the series; the analyses and their registry; the
   gradient spectrum; value equality; the kept results; the number arguments;
   the kept event points; the oracle of the gradient waveform; the `.asc` files; the
   snapshot; the names of the interface; the SAFE hardware and filter

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
parametrized test is one test. The check reads TESTS.md and takes each level-4
heading that is a test name in backticks as an entry. The entry belongs to the
test file named in the nearest level-3 heading above it. The check then
reports:

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
section 9).

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
measurements use to read a pypulseq sequence: `gradient_offsets` and
`gradient_points`, the gradient corner/sample helpers. It also checks that the synthetic
sequences in `tests/synthetic.py` are legal Pulseq.

#### `test_time_tolerance`

**Checks:** The time tolerance is 1 ns, and it is the `eps` of pypulseq (the join rule
of `sampling` uses it in place of `pp.eps`).

**How:** The test compares `seq_utils.TIME_TOLERANCE` with 1e-9 and with `pp.eps`.

**Assumptions:** The test checks a constant of the tests, not code of the package.

#### `test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system`

**Checks:** `GAMMA_1H` from `tests/synthetic.py` is equal to the gamma of `SYSTEM`, and both
are 42.576 MHz/T.

**How:** The test compares `GAMMA_1H` with `SYSTEM.gamma` and with the literal value. The tests
convert the values of the package with `GAMMA_1H`. The test sequences convert their mT/m
limits with the gamma of `SYSTEM`, so the two must be equal.

**Assumptions:**

- `SYSTEM` leaves `gamma` at the default of pypulseq's `Opts`.
- The test checks the test helpers (the gamma constant against `SYSTEM`), not code of
  the package.

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
  `shape_dur` by default. The test does not check that. It takes `g.first` and
  `g.shape_dur` as the expected values of the helper, so the case without
  them (used only for a shape that already has points at
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
  not check the package's own reading of the sequence, only that the
  synthetic sequences are legal Pulseq.
- The test checks the test helpers (the synthetic sequences against the timing check
  of pypulseq), not code of the package.

### 2.2 PNS levels (`test_pns_levels.py`)

`test_pns_levels.py` tests `pns_levels.py`: `pns_levels`, which keeps its result for the
snapshot (section 2.7 tests the keep) and, for a result that is not kept, calls
`_compute_levels`, which samples the gradients block by
block (`GradientSampler.block_samples`), runs the SAFE model of `safe.py`
(`_safe_gwf_to_pns_chunk`, ported from the pinned pypulseq fork) over them in chunks, and keeps only the stored level
(the minimum and the maximum of the total in fixed time bins) and the summary (the
peak, the peak time and the axis peaks), and the intervals of consecutive samples
whose total is at or above each threshold of the `thresholds_hz_per_t` argument
(`PnsInterval`, `PnsLevels.above`, a dict with one key for each threshold; the default is
no threshold); and `bin_samples_for`, which picks the bin size. A PNS value of
`pns_levels` is in Hz/T: the fraction of the stimulation limit times the magnitude of
gamma, because the model runs on the Hz/m samples and reads no gamma. The test file
defines `_LIMIT = GAMMA_1H`, the stimulation limit for 1H in Hz/T (a fraction of 1 times
`GAMMA_1H`), and gives a
threshold or a comparison as a fraction times `_LIMIT`. The reference for most tests is
`seq.calculate_pns` of the pinned fork
(this project does not test pypulseq itself, only compares this library's output with
pypulseq's or with its own other output).
`calc_pns` samples `seq.get_gradients()` at the file times `(k + 0.5) * dt`, which
drift off the ideal raster grid by float rounding of the block start time sums;
`pns_levels` samples each block at its own local
raster times, with no such drift. Both then run the same SAFE model (the chunk function of
`safe.py` is the fork's, to the last bit: section 2.19), so a
relative 1e-6-of-peak tolerance covers the whole
difference, except for a file with a block off the gradient raster, where both
sample at file times and a relative 1e-9 suffices. `calc_pns` divides the gradients by
`seq.system.gamma` and so gives fractions: the tests divide each value of `pns_levels` by
`seq.system.gamma` before they compare it with `calc_pns`.

`pns_levels` uses the gradient waveform of MATLAB Pulseq (`docs/implementation.md`, section 1). pypulseq
draws a line across each gap between two events and has no step at a block junction
(pypulseq-issues 12). So a comparison with `calc_pns` holds only for a sequence with no end that
is not 0 next to a gap of more than one raster time, and no step at a block junction. All the
sequences of those comparisons are such sequences: the spin echo, the GRE, the arbitrary
gradient, the border sequence and the off-raster trapezoid. The sequences with an end that is
not 0 next to a gap are compared with the SAFE model of the fork on the samples of the oracle
waveform (`test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`).

A second call of `pns_levels` with the same snapshot and the same arguments gives the
kept object. Each test makes its snapshot with `snapshot.load`, and the oracles get the
`pp.Sequence`. A test that changes `_CHUNK_SAMPLES` or `MAX_BINS` (the kept result would hide
the change), or that compares two calculations of one sequence, calls `_compute_levels` through
the helper `_compute` of the test file. It checks the hardware, the thresholds and `bin_s` as
`pns_levels` does and gives `_compute_levels` the checked values, so each call runs the model
and gives a new object. Where such a test has two results of the same arguments, it asserts
that they are not the same object (`first is not second`): with `pns_levels` the second
result would be the first and the test could not fail.

`pns_levels` takes the hardware of the SAFE model as a pair `(struct, label)` (`hardware`),
which is necessary and keyword-only; `struct` is a `safe.SafeHardware` or a SAFE hardware
struct in the form of pypulseq's `asc_to_hw`. The tests give pypulseq's example hardware as the pair `EXAMPLE_HW`
of `tests/synthetic.py` (`safe_example_hw()` and a label), and the hardware of a gradient
`.asc` file as `hardware_from_asc(path)`. The tests of `hardware` in this section check
a `hardware` with the struct of `safe_example_hw()` and a `hardware` from a gradient
`.asc` file against `EXAMPLE_HW`. They compare the results exactly: the same struct
values give the same float operations. The refusal of a missing `hardware`, of a
`hardware` that is not a pair and of a struct that `_check_hardware` refuses is tested in
section 2.7.

#### `test_summary_matches_calculate_pns_within_the_fork_tolerance`

**Checks:** For a spin echo, a gradient echo, an arbitrary gradient, and a
hand-made "border" sequence (two extended-trapezoid blocks whose gradient is not
zero at the block border between them), `pns_levels`'s peak, peak time and axis
peaks equal `seq.calculate_pns`'s (example hardware) within a relative 1e-6 of the
peak, after the peak and the axis peaks are divided by `seq.system.gamma`. Also checks
`reason`, `hardware`, `dt_s` and `on_raster` for the example-hardware,
on-raster case. The division is the conversion of `docs/usage.md` section 9, so this
test also tests it.

**How:** Parametrized over `spin_echo_sequence()`, `gre_sequence()`,
`arbitrary_gradient_sequence()` and `synthetic.border_sequence()` (two
`pp.make_extended_trapezoid` blocks on x, the second continuing the first's
amplitude with no step, so `add_block` accepts the junction). The reference peak,
peak time (the first sample at or above `peak * (1 - PEAK_TOLERANCE)`, as
`PnsLevels.peak_time_s`) and axis peaks come from
`seq.calculate_pns(safe_example_hw(), do_plots=False)`. `pns_levels(snap)`'s fields
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
`pns_levels(snap)`, `s0 = i * bin_samples`, `s1 = min(s0 + bin_samples,
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

#### `test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`

**Checks:** For a sequence with a short gap or a long gap and ends that are not 0 next to it,
`pns_levels` equals the SAFE model of the fork on the samples of the oracle. This includes a
first value and a last value of an axis that are not 0. It also covers a sequence with a block
that is not on the raster, where `pns_levels` samples with `GradientSampler.sample`.

**How:** Parametrized over 51 sequences. Six are a two-axis short gap with a first value and a
last value that are not 0, `long_gap_sequence`, the two sequences of pypulseq-issues 12,
`non_zero_ends_sequence`, and `long_gap_sequence` with a last block of 1.5 raster times. On the
raster, 17 more are `gap_of_1_5_raster_times_sequence` (a long gap of 1.5 raster times between two values that are not 0), `short_gap_from_0_sequence` and `short_gap_to_0_sequence` (a short gap from 0 to a value, and from a value to 0), a copy of each sequence of `tests/gap_sequences.py` with each amplitude negated (`gap_sequences.negated`), and the 8 sequences of `random_gaps.random_gap_sequence` with the seeds 0 to 7 (random signs, delays of 0 to 7 raster times, and zero, short and long gaps). Off the raster, 13 more are
`gap_of_1_5_raster_times`, `short_gap_from_0`, `short_gap_to_0`, the negated long and short
gaps and the 8 random sequences, each with a last block of 1.5 raster times (the names end in
`_off_raster`), so `pns_levels` samples them with `GradientSampler.sample`. The new inputs have
negative end values, a gap between one and two raster times, and a short gap with an end of 0,
which the six sequences do not have. Fifteen more, on the raster, have the last sample of an event
at a sample time: the 14 ramps of `gap_sequences.DELAYED_RAMP_CASES` and `ULP_EDGE_CASES` after a
delay of a whole number of raster times and a half (`delayed_ramp_sequence`, behind filler blocks),
and `short_arbitrary_sequence`, an arbitrary
gradient of 3 samples with a step at 25 us (the values and the cases are in
`test_block_samples_at_the_last_point_of_an_event_and_at_a_step_equals_the_oracle`). The
reference stacks the samples of the oracle into `(N, 3)`. They are `oracle.block_samples` at the
gradient raster, and `oracle.sample` at `(k + 0.5) * dt` for the sequence that is not on the
raster. It runs `_safe_gwf_to_pns_chunk` of the fork in one chunk with the example hardware. The
axis values are 0.01 times the percent, and the total is the root of the sum of squares.
`pns_levels` runs with `bin_s=dt`, so each bin is one sample. The test checks the number of
samples, `on_raster` (false only for the names that end in `_off_raster`), the peak and the axis peaks (relative 1e-9), the peak time, and the minimum
and maximum of each bin against the total (relative 1e-6, because of the float32 cast).

**Assumptions:** `calculate_pns` is not the reference, because it draws a line across each gap
(pypulseq-issues 12).

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

#### `test_cast_outward_keeps_zero_at_zero`

**Checks:** `_cast_outward` of a float64 array that the float32 cast holds exactly (zeros)
gives the same zeros, for the downward and the upward cast. A bin of zeros gets no level
below or above 0.

**How:** `numpy.zeros(4)`. For `down=True` and `down=False`, the result is `float32` and
`numpy.array_equal` to four float32 zeros.

**Assumptions:** The float32 cast of 0.0 is exact, so the nudge by `numpy.nextafter` does
not apply to it.

#### `test_interval_finder_tie_across_a_chunk_boundary_keeps_the_earlier_peak_sample`

**Checks:** One run that crosses a chunk boundary, with the same largest total on both
sides, is one interval whose peak sample is the earlier one (the tie rule of the join of
two chunks).

**How:** `_IntervalFinder(1.0, 0.5)`, `add_chunk(0, [0, 1])`, `add_chunk(2, [1, 0])`.
`finish()` gives one interval with `start_s == 1.0`, `end_s == 3.0`, `num_samples == 2` and
`peak_time_s == 1.5`.

**Assumptions:** The edges of the samples `first` to `last` are `first * dt` and
`(last + 1) * dt`. The time of sample `s` is `(s + 0.5) * dt`.

#### `test_interval_finder_gap_at_the_start_of_a_chunk_does_not_join_the_open_run`

**Checks:** A run that is open at the end of a chunk is not joined to a run of the next
chunk that does not start at its first sample.

**How:** `_IntervalFinder(1.0, 0.5)`, `add_chunk(0, [0, 1])`, `add_chunk(2, [0, 1])`.
`finish()` gives two intervals, with `(start_s, end_s, num_samples)` of `(1.0, 2.0, 1)` and
`(3.0, 4.0, 1)`.

**Assumptions:** None.

#### `test_an_interval_of_one_sample_spans_one_sample_interval_from_its_first_sample_edge`

**Checks:** A run of one sample has `start_s == first * dt` and `end_s - start_s == dt`, and
its peak time is the time of the sample, `(first + 0.5) * dt`.

**How:** `_IntervalFinder(0.25, 0.5)`, `add_chunk(0, [0, 0, 1, 0])`. `finish()` gives one
interval with `num_samples == 1`, `start_s == 0.5`, `end_s - start_s == 0.25` and
`peak_time_s == 0.625`.

**Assumptions:** `dt` is 0.25, a power of 2, so the products and the difference are exact in
floats.

#### `test_bin_samples_for_matches_the_formula`

**Checks:** `bin_samples_for` follows `max(wanted, ceil(num_samples / MAX_BINS), 1)`, where
`wanted` is the whole number of samples of `bin_s` (the next test checks the snap to the
raster). With the default `bin_s`, `BIN_S` (5 ms): 500 samples at the 10 us raster for any
file of up to 1,000,000,000 samples, and a coarser bin above that size or at a coarser
`dt`. With another `bin_s`: the bin rounded down to whole samples, one sample for a `bin_s`
shorter than `dt` or equal to it, and the coarser bin of a file with more than `bin_samples
* MAX_BINS` samples. `bin_s=10.0 / 1624`, the default of 0.1.0rc5, still gives 615. A
`pns_levels` call on a real sequence follows the same formula and gives that many bins.

**How:** Direct calls: `bin_samples_for(0, 1e-5) == 500`,
`bin_samples_for(1_000_000_000, 1e-5) == 500`, `bin_samples_for(1_000_000_001, 1e-5)
== 501`, `bin_samples_for(2_000_000_000, 1e-5) == 1000`, `bin_samples_for(0, 2e-5) ==
250`, `bin_samples_for(0, 1e-5, BIN_S)` equal to the call without `bin_s`, `BIN_S ==
0.005`, and `bin_samples_for(0, 1e-5, 10.0 / 1624) == 615`. Then, at
`dt = 1e-5`: `bin_s = 1e-3` gives 100, `1.055e-3` and `1.059e-3` give 105, `1e-6` and `dt`
give 1, `bin_samples_for(0, 0.25, 1) == 4` (an `int` is a number of seconds),
`bin_samples_for(100 * MAX_BINS, 1e-5, 1e-3) == 100` and with one more sample 101, and
`bin_samples_for(2 * MAX_BINS, 1e-5, 1e-6) == 2`. Then
`pns_levels(gre_sequence(num_trs=6))`'s `bin_samples` is compared with
`bin_samples_for(levels.num_samples, levels.dt_s)`, and `len(levels.level_min_hz_per_t) ==
len(levels.level_max_hz_per_t)` equals the ceiling division of `num_samples` by
`bin_samples`.

**Assumptions:** The values between two samples (`1.055e-3`, `1.059e-3`) are far from a
whole number of samples, so the snap to the raster does not change them.

#### `test_bin_samples_for_gives_the_whole_samples_of_a_bin_s_on_the_raster`

**Checks:** A `bin_s` within `ON_RASTER_TOLERANCE` of a whole number of samples gives that
number, not one less because the division is not exact. For each `k` from 1 to 2000,
`bin_s = k * 1e-5` and `bin_s = round(k * 1e-5, 10)` give `k` samples at the 10 us raster
(the floor alone gives `k - 1` for 1047 of the values). A `bin_s` between two samples is
rounded down: `615.5 * 1e-5` gives 615, and the default gives 500.

**How:** Direct calls of `bin_samples_for(0, 1e-5, bin_s)` in a loop over `k`, then the
calls for `0.01` (1000), `615.5 * 1e-5` and the default.

**Assumptions:** The 1047 figure is from the review of 2026-10-05, for the floor without the
tolerance.

#### `test_bin_s_sets_the_bin_of_the_level_and_holds_every_total`

**Checks:** `bin_s=1e-3` at the 10 us raster gives `bin_samples == 100` (so
`bin_samples * dt_s` is the bin, which is not that of the default) and `ceil(num_samples /
100)` bins. Each total of a bin is in `[level_min_hz_per_t, level_max_hz_per_t]` of that
bin, and the two ends are the minimum and the maximum of the totals of the bin cast
outward (`_cast_outward`). Every other field (the summary, the intervals, the hardware)
equals that of the default `bin_s`. A `bin_s` of `1e-9` gives one sample in each bin, and
the minimum of the first 100 bins of that level is the minimum of the first bin of the level
of `1e-3`.

**How:** `gre_sequence(num_trs=6)` with `hardware_for_peak(snap, 1.5)` and
`thresholds_hz_per_t=(_LIMIT,)`. The calls are `_compute` calls (`_compute_levels`), and
the result of `bin_s=1e-3` must not be the object of the default one. The default call is first. For `bin_s=1e-3` the test sets
`_CHUNK_SAMPLES` to `10**9` (one chunk) and replaces `_chunk_total` with a function that
records its total, so the first recorded total is that of the whole sequence. It takes the
minimum and the maximum of each 100 samples with `numpy.minimum.reduceat` and
`numpy.maximum.reduceat`, and compares with `<=`, `>=` and `numpy.array_equal` to the
outward cast. Then `assert_levels_equal` with the three fields of the bins ignored.

**Assumptions:** The minimum of the outward casts of samples equals the outward cast of
their minimum, because the cast is monotone, so the test can use exact equality.

#### `test_max_bins_still_limits_the_bins_for_a_short_bin_s`

**Checks:** With `MAX_BINS` small, a `bin_s` that would give more bins gets a longer bin:
`bin_samples == ceil(num_samples / MAX_BINS)` and no more than `MAX_BINS` bins. The
minimum of the whole level and the maximum of the whole level are those of the level with
one sample in each bin, and every other field equals that of the call with `MAX_BINS` not
changed. A `bin_s` of the whole duration gives one bin of `num_samples` samples.

**How:** `gre_sequence(num_trs=6)` with `EXAMPLE_HW`. Each call is a `_compute` call
(`_compute_levels`): the first has `bin_s=1e-9` and the real `MAX_BINS`. Then the test sets
`pulseq_analysis.pns_levels.MAX_BINS` to 50 with `monkeypatch`, calls again with the same
arguments, checks that the result is not the object of the first call, and compares. A last
call has `bin_s = num_samples * 1e-5`.

**Assumptions:** `pns_levels` reads `MAX_BINS` as a module global (`bin_samples_for` does),
so the replacement is used.

#### `test_result_does_not_depend_on_chunk_samples`

**Checks:** The stored level and the summary do not depend on the chunk size: exact
equality for chunks of 1, 2 and 7 bins and one chunk larger than the whole file.

**How:** `gre_sequence(num_trs=20)`, long enough that the smallest case (1 bin per
chunk) still has more than one chunk. `reference` is a `_compute` call (`_compute_levels`,
with the `_CHUNK_SAMPLES` of the module); then, for each size in `1`, `bin_samples + 1`,
`7 * bin_samples - 1` and `bin_samples * (num_samples // bin_samples + 10)`,
`monkeypatch.setattr` sets `_CHUNK_SAMPLES` of `pulseq_analysis.pns_levels` to it and
`_compute` runs again; its result must not be the object of the reference. `_compute_levels`
rounds the chunk up to a whole number of
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
_LIMIT`. The calls are `_compute` calls (`_compute_levels`). `_CHUNK_SAMPLES` is set to
`10**9` for the reference (the test checks that four bins are fewer than 10,000 samples, and
that the reference has an interval), then to 1 and `bin_samples + 1`. Each result must not be
the object of the reference, and `assert_levels_equal` (`tests/asserts.py`) compares it with
the reference, every field.

**Assumptions:** None.

#### `test_one_long_delay_block_gives_the_result_of_the_same_time_in_short_blocks`

**Checks:** A trapezoid and one delay block of 1 s (more than three chunks of the real
`_CHUNK_SAMPLES`) gives exactly the same result as the trapezoid and ten delay blocks of
0.1 s.

**How:** Two sequences with the same trapezoid on x. The threshold is `0.1 * _LIMIT`.
The test checks that the long sequence has more than `3 * _CHUNK_SAMPLES` samples and
that the result of the short blocks has an interval. `assert_levels_equal` (`tests/asserts.py`) compares
every field. The samples of a delay are 0 in both, so the totals are equal.

**Assumptions:** None.

#### `test_a_safe_hardware_gives_the_levels_of_the_equal_namespace_exactly`

**Checks:** `hardware=(SafeHardware.from_namespace(struct), label)` gives the same result as
`hardware=(struct, label)`, every field exactly equal, for the example hardware.

**How:** Parametrized over the four sequences of the comparison with `calculate_pns`. The test
calls `_compute` (no keep) with the namespace pair `EXAMPLE_HW` and with the `SafeHardware`
pair, with one threshold of half of `_LIMIT`, checks that the peak is above 0, and compares the
two results with `assert_levels_equal` and `ignore=()` (`numpy.array_equal` for the arrays,
`==` for the rest, so the intervals of the threshold are also compared).

**Assumptions:** None.

#### `test_no_gradients`

**Checks:** A sequence with no gradient event gives `reason=NO_GRADIENTS`, no
stored bins, a peak of 0, `peak_time_s` of `None`, zero axis peaks, no threshold (the
default, so `above == {}`), and still the hardware of `EXAMPLE_HW` and its `hw` fields.

**How:** `pns_levels(empty_sequence(), hardware=EXAMPLE_HW)`. Checks `reason`, `hardware`,
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
`seq.system.gamma` (the conversion of `docs/usage.md` section 9; tighter than the drift-based 1e-6 elsewhere in
this section, because both now sample with `GradientSampler.sample`/
`seq.get_gradients()` at the same file times; `test_sampling.py` established that
those two agree to about float rounding). The trapezoid has no end that is not 0 next to a gap,
so pypulseq's line across a gap is 0 there, as in the model of MATLAB Pulseq.

**How:** A trapezoid on x followed by `pp.make_delay(1.5 * dt)` (pypulseq's
`add_block` accepts this duration, though it is not a whole number of raster
steps). Compares `pns_levels(snap)`'s `on_raster`, `peak_hz_per_t` and `axis_peaks_hz_per_t`
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
`ceil((end_s - 1e-10) / dt)`, with `end_s` the end of `sequence_index(snap)`. A chunk
that reads the samples of the first chunk again, or a `num_samples` that rounds down,
gives another result.

**How:** `gre_sequence(num_trs=3)` and then `pp.make_delay(1.5 * dt)`, so that the
sequence is not on the raster. The hardware gives a peak of 1.5 times `_LIMIT`
(`hardware_for_peak` of `tests/pns_hardware.py`), and `thresholds_hz_per_t=(_LIMIT,)`. Both
calls are `_compute` calls (`_compute_levels`). `monkeypatch` sets
`_CHUNK_SAMPLES` to `10**9` for the reference (one chunk) and to 1 (a chunk of one bin)
for the second call. The test checks that the second result is not the object of the
reference, `on_raster is False`, more than three chunks, an
interval above `_LIMIT`, `got == reference`, and `num_samples`.

**Assumptions:** The sequence has an interval above `_LIMIT`.

#### `test_an_off_raster_sequence_of_more_than_one_real_chunk_matches_calculate_pns`

**Checks:** An off-raster sequence that is longer than one chunk at the real
`_CHUNK_SAMPLES` has the peak, the peak time and the axis peaks of `seq.calculate_pns`,
within the tolerances of `test_off_raster_block_falls_back_to_sampling` (each value
divided by `seq.system.gamma`). The peak is in the second chunk.

**How:** A trapezoid on x (area 200), `pp.make_delay(0.35)`, a trapezoid on y (area
1000) and `pp.make_delay(1.5 * dt)`. The reference is
`seq.calculate_pns(safe_example_hw(), do_plots=False)`. The test checks
`on_raster is False`, `num_samples` more than one chunk
(`bin_samples * ceil(_CHUNK_SAMPLES / bin_samples)`), a peak time after the first chunk,
and then the peak, the peak time and the axis peaks.

**Assumptions:** None.

#### `test_a_sequence_below_the_limit_has_no_interval_and_one_above_it_has_some`

**Checks:** `above[_LIMIT]` is empty if and only if `peak_hz_per_t < _LIMIT`. For a
sequence above the limit, the largest interval peak equals `peak_hz_per_t`, each interval
has a peak of at least `_LIMIT` and a peak time between its start and its end, its `num_samples` is the number of
samples from its start to its end, and the intervals are in time order with at least
one sample below the limit between two of them.

**How:** `pns_levels(snap, thresholds_hz_per_t=(_LIMIT,))` for
`gre_sequence(num_trs=20)` with the example hardware has a peak below `_LIMIT` and no
interval. Then the stimulation limit of each axis is scaled with the peak of the example
hardware, so that the peak is 1.5 times `_LIMIT` (`hardware_for_peak` of `tests/pns_hardware.py`; the total is the
percent of the limit), and `pns_levels` runs with that hardware as `hardware`. The first sample of an interval is `round(start_s / dt)`, and the last is
`round(end_s / dt) - 1`. Two intervals are apart by more than `dt / 2`, so at least one
sample is between them.

**Assumptions:** The sequence gives more than one interval at that peak.

#### `test_a_threshold_equal_to_the_peak_gives_an_interval`

**Checks:** A threshold that is exactly `peak_hz_per_t` gives one interval or more, and
the largest interval peak is the threshold. A total at the threshold is in an interval
(`total >= threshold`).

**How:** `gre_sequence()` with `EXAMPLE_HW`. A first `pns_levels` call gives
`peak_hz_per_t`. A second call with `thresholds_hz_per_t=(peak,)` gives `above`. The test
checks that its only key is `peak`, that `above[peak]` has one interval or more, and that
the largest `peak_hz_per_t` of the intervals equals `peak`.

**Assumptions:** None.

#### `test_an_off_raster_sequence_that_ends_at_a_whole_number_of_samples_has_that_number`

**Checks:** An off-raster sequence whose `end_s / dt` is above a whole number by float
rounding only has that whole number of samples. A `num_samples` with no `- 1e-10` would be
one more.

**How:** A trapezoid on x (area 1000) and two `pp.make_delay(1.5 * dt)` blocks (3 steps
together). `whole` is the duration of the trapezoid in steps plus 3. The test checks
`round(end_s / dt) == whole`, `end_s / dt > whole` and `(end_s - 1e-10) / dt <= whole`,
with `end_s` of `sequence_index(snap)`. Then it calls `pns_levels` with `EXAMPLE_HW` and
checks `on_raster is False` and `num_samples == whole`.

**Assumptions:** `end_s / dt` is 106.00000000000001 for this sequence. The test fails at
its own checks of `end_s / dt` where float rounding gives another value.

#### `test_the_intervals_do_not_depend_on_chunk_samples`

**Checks:** The result, every field and so every interval, is exactly the same for a
chunk of 1 bin, for a chunk with an interval across its end (the interval is one
interval, not two), and for one chunk larger than the whole file.

**How:** `gre_sequence(num_trs=20)` with hardware that gives a peak of 3 times `_LIMIT`,
and `thresholds_hz_per_t=(_LIMIT,)`, and every call has `bin_s=10.0 / 1624`
(615 samples at the 10 us raster; see the assumptions). Every call is a `_compute` call
(`_compute_levels`). `reference` is the one with
the `_CHUNK_SAMPLES` of the module.
The test searches the chunks of 1 to 19 bins for the first one where the last sample of
an interval is in a later chunk than its first sample, and fails if there is none. Then
`monkeypatch.setattr` sets `_CHUNK_SAMPLES` of `pulseq_analysis.pns_levels` to 1, to that
size and to a size larger than the file, each result must not be the object of the
reference, and the whole `PnsLevels` is compared with the reference
(`numpy.array_equal` for the arrays, `==` for the rest).

**Assumptions:** The test checks that the second size has an interval across a chunk
end and the third has none. Setting a chunk of 1 sample gives chunks of 1 bin
(`pns_levels` rounds the chunk up to a whole number of bins). A chunk is a whole number of
bins, so an interval can cross a chunk end only if the bin does not align with it. The
intervals of this sequence are in samples 114 to 417 of each 2000, and none has a multiple
of 500 inside it, so with the default bin (500 samples) no chunk has an interval across its
end. The bin of 615 samples has such chunks.

#### `test_an_interval_across_three_chunks_does_not_depend_on_chunk_samples`

**Checks:** An interval with samples in three chunks or more (the open run goes over
more than one chunk end) is the same interval with chunks of one bin and with one
chunk.

**How:** `gre_sequence(num_trs=3)` with the example hardware and
`thresholds_hz_per_t=(1e-5 * _LIMIT,)`, a threshold far below the peak. Both calls are
`_compute` calls (`_compute_levels`). `monkeypatch`
sets `_CHUNK_SAMPLES` to `10**9` for the reference and to 1 (a chunk of one bin) for the
second call. The test checks that the second result is not the object of the reference,
that an interval of the reference has
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
`thresholds_hz_per_t=(_LIMIT,)`. The test sets `_CHUNK_SAMPLES` to `10**9` (one chunk) and
wraps `_chunk_total` to keep the totals it returns. The call is a `_compute` call
(`_compute_levels`), so that the model runs and the wrapper records the totals. It finds the runs of
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
`0.5 * _LIMIT`. Every `_compute` call (`_compute_levels`) of the test has `bin_s=10.0 / 1624`
(615 samples). The test checks that the intervals of `_LIMIT` are more than one and that
those of `0.5 * _LIMIT` have more samples in total (so the two thresholds do not give the
same runs). For each chunk size (the normal one, 1,
and for each threshold the first of 1 to 19 bins with an interval across its end, found
as in `test_the_intervals_do_not_depend_on_chunk_samples`; `monkeypatch.setattr` sets
`_CHUNK_SAMPLES` of `pulseq_analysis.pns_levels`), the call with both thresholds must
have the keys `[_LIMIT, 0.5 * _LIMIT]`, the same tuple as `single` for each threshold, and
every other field equal (`assert_levels_equal` (`tests/asserts.py`) with `ignore=("above",)`).
The results of the chunk sizes must be different objects (each size ran the model). After
the chunk sizes are restored, the thresholds in the other order (a `_compute` call) give the
keys in that order and the same tuples, and the `int` `round(_LIMIT)` in place of `_LIMIT`
(the test checks that it equals `_LIMIT` as a float; a `pns_levels` call, so that the
public function takes the `int`) gives the key `_LIMIT` as a `float`.

**Assumptions:** The intervals of 1.0 and of 0.5 each cross a chunk end for a chunk of 1
to 19 bins of 615 samples (`_chunk_across_an_interval` fails if there is none). With the
default bin of 500 samples none does, as in
`test_the_intervals_do_not_depend_on_chunk_samples`.

#### `test_pns_levels_takes_numpy_and_fraction_thresholds`

**Checks:** A threshold that is a NumPy real scalar (`float32`, `int64`) or a `Fraction`
is valid. The keys of `above` are `float(t)` (type `float`) in the order given. The result
equals the result of the same thresholds as floats, and the second result is a new object.

**How:** `pns_levels(spin_echo_sequence(), hardware=EXAMPLE_HW,
thresholds_hz_per_t=(np.float32(0.3 * _LIMIT), np.int64(12_345_678), Fraction(1, 3) *
_LIMIT))`. The test checks `list(above)` against `[float(t) ...]` and the type of the
keys. The thresholds as floats go to `_compute` (the calculation with no keep). A second
`pns_levels` call with those keys would give the kept object, and the test would compare
that object with itself. The test checks that the new result is not the kept object, then
calls `assert_levels_equal` (`ignore=()`).

**Assumptions:** None.

#### `test_pns_levels_takes_an_int_or_a_numpy_bin_s`

**Checks:** A `bin_s` that is an `int` (`1`) or a NumPy float (`numpy.float64(1.0)`) gives
exactly the levels of the equal `float` (`1.0`), every field. A `bin_s` of 1 s holds the
whole spin echo in one bin.

**How:** `spin_echo_sequence()` with `EXAMPLE_HW`. `expected` is a `_compute` call
(`_compute_levels`, a new calculation) with `bin_s=1.0`; the two `pns_levels` calls with
`bin_s=1` and `bin_s=numpy.float64(1.0)` are compared with it with `assert_levels_equal`
and `ignore=()`.

**Assumptions:** None.

#### `test_asc_hardware_file_is_used_for_the_levels`

**Checks:** `pns_levels` with `hardware_from_asc(path)` has the hardware name and the 8
kept fields of each axis of the gradient .asc file, instead of the example hardware, and
its stored level and summary then equal the call with `EXAMPLE_HW` exactly, because this
.asc file encodes the example hardware's own numbers. This is so for the plain layout and
for the layout of a scanner file.

**How:** Parametrized on `split`. The `write_gradient_asc` fixture of `tests/conftest.py`
(not confidential data: real .asc files are confidential, so this one is built from
pypulseq's own public `safe_example_hw()`) writes an `asCOMP.tName` line (in the scanner
layout, a main file that includes the PNS parameters) and the `flGSWDTau*`, `flGSWDA*`,
`flGSWDStimulationLimit*`/`Threshold*` and `flGScaleFactor*` fields for each axis.
`pns_levels(spin_echo_sequence(), hardware=hardware_from_asc(path))`'s `hardware` and `hw`
are checked, then its `level_min_hz_per_t`, `level_max_hz_per_t`, `peak_hz_per_t` and
`peak_time_s` are compared with a `pns_levels(snap, hardware=EXAMPLE_HW)` call
(`numpy.array_equal` for the arrays, `==` for the scalars).

**Assumptions:** None.

#### `test_the_arrays_of_the_levels_are_read_only`

**Checks:** `level_min_hz_per_t` and `level_max_hz_per_t` are read-only, also for a
sequence without gradients. A conversion to a new array works.

**How:** The test runs for the synthetic spin echo and for a sequence without gradients
(the two arrays are empty). Each array must have `flags.writeable` off, and a change in
place (`a *= 100`) must raise `ValueError`. Then `levels.level_max_hz_per_t * 100` must
give a writable array, and `levels.level_max_hz_per_t` must not change.

**Assumptions:** None.


#### `test_the_dicts_of_the_levels_are_read_only_frozen_dicts`

**Checks:** `hw` (the outer dict and each of its three inner dicts), `axis_peaks_hz_per_t` and `above`
are `FrozenDict`s and `dict`s, also for a sequence without gradients. A change of an item,
a new key, a deletion and `update` raise `TypeError`, and the dict stays as it was.

**How:** Parametrized on the spin echo and the sequence without gradients, with
`thresholds_hz_per_t=(_LIMIT,)`. The helper `_every_dict` lists the 6 dicts. For each:
`isinstance` of `FrozenDict` and of `dict`, then `d[key] = 0.0`, `d["new"] = 0.0`,
`del d[key]` and `d.update(...)` in `pytest.raises(TypeError)`, then `d == dict_before`.

**Assumptions:** None.

#### `test_the_reason_without_gradients_is_the_object_of_seq_index`

**Checks:** `pns_levels.NO_GRADIENTS` and `grad_spectrum.NO_GRADIENTS` are `seq_index.NO_GRADIENTS`
(one object), and the `reason` of a `PnsLevels` without gradients is it.

**How:** Three `is` assertions, the last on `pns_levels(empty_sequence(),
hardware=EXAMPLE_HW).reason`.

**Assumptions:** None.

#### `test_gradients_that_all_have_the_amplitude_zero_have_no_peak_time_and_one_run`

**Checks:** A sequence whose only gradient is a trapezoid of the amplitude 0 has `reason` None, a peak
of 0 and axis peaks of 0, `peak_time_s` None, and an empty tuple for a threshold. The model
runs one time for each chunk, and not a second time for the peak time.

**How:** `pp.make_trapezoid(channel="x", amplitude=0, flat_time=20e-3)` in one block.
`_CHUNK_SAMPLES` is set to 1 (a chunk of one bin), and `_chunk_total` is replaced by a
recorder. The call is a `_compute` call (`_compute_levels`), so that the model runs. The
number of calls of the recorder must equal `ceil(num_samples / bin_samples)`, which is more
than 3.

**Assumptions:** `pns_levels` calls `_chunk_total` as a module global. pypulseq accepts a
trapezoid with `amplitude=0`.
#### `test_levels_compare_by_value`

**Checks:** `==` compares two `PnsLevels` by the values of their fields, also with more
than one bin, where the `__eq__` of `dataclasses` raises `ValueError`. A `PnsLevels` is
not hashable. A copy from `pickle` or `copy.deepcopy` is equal to the original, and its
dicts are `FrozenDict`s (a `MappingProxyType` could not be pickled).

**How:** The test calls `pns_levels` on a GRE sequence of 4 TRs with two thresholds
(the stimulation limit and half of it), and asserts that the level has more than one bin.
A second call must give another object that is equal. A `pickle` round trip and
`copy.deepcopy` must give another object that is equal (the copies are writable, and the
flag does not count) and every dict of it (`_every_dict`) must be a `FrozenDict`. These must
not be equal:

- the result with one bin of `level_max_hz_per_t` moved up by one float32 step
  (`dataclasses.replace`);
- the result with the thresholds in the other order: its `above` is equal as a dict, but
  the order of its keys differs;
- a string.

`hash` must raise `TypeError`.

**Assumptions:** None.

#### `test_hardware_with_the_example_struct_gives_the_levels_of_the_example_pair`

**Checks:** `pns_levels(snap, hardware=(safe_example_hw(), label))` gives the levels of
`pns_levels(snap, hardware=EXAMPLE_HW)` (another struct object and another label), except `hardware`, which is the label, and each
other field is exactly equal.

**How:** For `spin_echo_sequence()` (on the raster) and for a sequence with a block off
the raster, the test calls both and compares each field of the `PnsLevels` but
`hardware` (`numpy.array_equal` for the arrays, `==` for the rest).

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
1H does not equal it. Thus the conversion of `docs/usage.md` section 9 uses the gamma of
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

**Checks:** `pns_levels(snap, hardware=...)` with no threshold argument has `above == {}`,
and a new calculation with `thresholds_hz_per_t=()` gives the same result in every field.
This is also so with hardware for a peak above the limit.

**How:** `gre_sequence(num_trs=4)`, with `EXAMPLE_HW` and with the hardware of a
peak of 1.5 times `_LIMIT`. For each, the test calls `pns_levels` with no threshold argument
and checks `above == {}`. It calls `_compute` (`_compute_levels`) with
`thresholds_hz_per_t=()`, checks that the result is not the object of the first, and compares
the two results with `assert_levels_equal` (`tests/asserts.py`) and `ignore=()`.

**Assumptions:** None.

#### `test_pns_levels_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `pns_levels` with good other arguments raises `TypeError` with a message that
names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over `spin_echo_sequence()` and the path string `"sequence.seq"`. The call
with pypulseq's example hardware must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

#### `test_pns_levels_refuses_bad_thresholds_before_the_snapshot_type`

**Checks:** `pns_levels` raises `TypeError` for `thresholds_hz_per_t` that is not a tuple
(a list, a float, `None`) or has an element that is a `bool` or not a real number (a
string, `None`, a complex number). It raises `ValueError` for an element that is not
finite (NaN, the two infinities, an `int` too large for a float) or not above 0 (0 and a
negative number), or for two elements that are equal as floats (`(1.0, 1.0)`, `(1, 1.0)`,
a pair that is not next to each other, a NumPy `float32` and the equal `float`). It does so before the type of the
first argument is checked.

**How:** Each case is a parameter (the value and the error). The test calls
`pns_levels(spin_echo_sequence(), thresholds_hz_per_t=value, hardware=EXAMPLE_HW)` inside
`pytest.raises(error, match="threshold")`. The first argument is a `pp.Sequence`, which is not
a snapshot and would raise the `TypeError` that names `load`, so the error is still the one
of the thresholds. The empty
tuple is not a case: it is valid (the default).

**Assumptions:** The check of the thresholds comes before the check of the type of the
first argument.

#### `test_pns_levels_refuses_a_bad_bin_s_before_the_snapshot_type`

**Checks:** `pns_levels` raises `TypeError` (the message names `bin_s`) for a `bin_s` that
is a `bool` (`True`, `False`) or not a real number (a string, `None`, a tuple, a complex
number), and `ValueError` for one that is not finite (NaN, the two infinities, an `int` too
large for a float) or not above 0 (0 as an `int` and as a `float`, a negative `int` and a
negative `float`). It does so before the type of the first argument is checked.

**How:** Each case is a parameter (the value and the error). The test calls
`pns_levels(spin_echo_sequence(), hardware=EXAMPLE_HW, bin_s=value)` inside
`pytest.raises(error, match="bin_s")`. The first argument is a `pp.Sequence`, which is not a
snapshot and would raise the `TypeError` that names `load`, so the error is still the one of
`bin_s`.

**Assumptions:** The check of `bin_s` comes before the check of the type of the first
argument.

### 2.3 Sequence extensions (`test_extensions.py`)

`test_extensions.py` tests the guard of `extensions.py`, `refuse_rotations`, which refuses a
sequence with a rotation. `snapshot.load` calls it, so the measurements, which take a snapshot, do
not (the refusal through `load` is tested in `test_snapshot.py`, section 2.17). Its tests call the
guard on a sequence. Task 6.1 of
`docs/plans/diagram-event-table.md` found that pypulseq 1.5.0.post1 cannot
make a rotation and that its `Sequence.read` raises `ValueError` for a
`.seq` file with a rotation section. This file therefore makes its own
rotation sequences by hand, the way pypulseq draft PR #372 stores a
rotation: a `rotation_library` event library on the `pp.Sequence`, or a
`"ROTATIONS"` entry in `seq.extension_string_idx`.

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

`test_seq_index.py` tests `seq_index.py`: the dense RF, gradient and ADC event numbering of
`sequence_index`, its block times, its dtypes and its keep for a snapshot; and
`rf_events`, `grad_events` and `adc_events`, which read each unique event one time and keep
the tuple on the snapshot. The
reference numbering, `_reference_index`, is a plain loop over the blocks with one dict
for each event kind: the loop that `diagram_data.diagram_tables` had before it used the
index. Its `*_first` arrays hold play indexes, as `SequenceIndex` does (the old loop
kept block ids). The tests load `build_repeating` and `build_worst` from
`tests/scale_sequences.py`. The functions take a `Snapshot`, which `snapshot.load` makes.

#### `test_dense_columns_and_first_arrays_match_the_reference_numbering`

**Checks:** `sequence_index`'s `rf`, `gx`, `gy`, `gz` and `adc` columns, `rf_first`,
`grad_first`, `grad_first_axis`, `adc_first` and `block_id` equal `_reference_index`'s,
for a synthetic spin echo, gradient echo, empty and arbitrary-gradient sequence, and
for `build_repeating`/`build_worst` at 50 TRs (250 blocks).

**How:** The test is parametrized over the four synthetic builders and two lambdas
wrapping `build_repeating(50)`/`build_worst(50)`. For each, it builds the sequence,
computes `sequence_index(snap)` and `_reference_index(seq)`, and compares every one of
those nine arrays with `numpy.array_equal` (the dense columns cast to `int64` first,
since `sequence_index` narrows their dtype while the reference always uses `int64`).

**Assumptions:** None.

#### `test_dense_numbering_follows_the_first_use_and_not_the_order_in_the_libraries`

**Checks:** The dense numbers of the RF, gradient and ADC events are in the order of first
use in play order, also when the events were registered in the libraries in another order.
`rf_first`, `grad_first`, `grad_first_axis` and `adc_first` are in the same order.

**How:** The test registers two RF events, three gradient events and two ADC events in the
libraries with `register_rf_event`, `register_grad_event` and `register_adc_event`, in the
reverse of their first use. Then it adds three blocks: (RF e1, gz g1, ADC a1), (RF e2, gx
g2, gy g3, ADC a2) and (e1, g1 on gx, a1). It checks the library ids in `seq.block_events`
first (RF 2, 1, 2, gx 0, 2, 3, gy 0, 1, 0, gz 3, 0, 0, ADC 2, 1, 2), so the order differs
from the first use. Then it checks the dense columns against the hand-worked values (`rf`
1, 2, 1, `gx` 0, 2, 1, `gy` 0, 3, 0, `gz` 1, 0, 0, `adc` 1, 2, 1), the `*_first` arrays,
`_assert_index_matches_reference`, and the amplitudes that `grad_events` yields (1e5, 2e5,
3e5).

**Assumptions:** The registration of an event before `add_block` gives the event its
library id, and `add_block` finds the same event again. This was checked against
`seq.block_events` while writing the test.

#### `test_the_dtype_of_the_dense_columns_changes_at_255_and_at_65_535_unique_events`

**Checks:** The event columns are uint8 for 255 unique events, uint16 for 256 and for 65 535, and
uint32 for 65 536.

**How:** Parametrized over the four numbers. The test calls the private `seq_index._dense` with the
event IDs 1 to K, because a sequence of 65 536 unique events would be slow to build, and checks the
dtype of the columns.

**Assumptions:** `sequence_index` uses `_dense` for its event columns. The next test checks it at
255 and 256 through `sequence_index`.

#### `test_the_dtype_of_the_index_changes_at_255_unique_events`

**Checks:** Through `sequence_index`, the gradient columns are uint8 for 255 unique gradient events
and uint16 for 256.

**How:** Parametrized over 255 and 256. A sequence of K blocks, each with a different trapezoid on
x. The test checks the dtype of `gx`, `gy` and `gz`.

**Assumptions:** None.

#### `test_an_event_id_of_1e8_builds_the_index_in_less_than_100_mb`

**Checks:** A sequence with an event ID of 10^8 builds its index with a `tracemalloc` peak below
100 MB, and its dense numbers are as for small IDs.

**How:** A sequence of three blocks with a trapezoid on x (the first and the third are the same
event). The test sets the gx ID of the second block in `seq.block_events` to 10^8 after `add_block`,
because pypulseq only gives the IDs 1, 2, ...; `sequence_index` reads only `seq.block_events` and
`seq.block_durations`, not the libraries. It measures `sequence_index` with `tracemalloc`, and checks
`gx` (1, 2, 1) and `grad_first` (0, 1). A lookup table over the IDs would take 800 MB.

**Assumptions:** `tracemalloc` sees the numpy allocations.

#### `test_start_s_is_the_sequential_sum_and_end_s_is_its_final_value`

**Checks:** `index.start_s` is the sequential sum of the block durations from 0.0,
`index.end_s` is that sum's final value, and `index.duration_s` is
`seq.block_durations` in play order.

**How:** The test builds `build_repeating(50)`, computes `sequence_index(snap)`, and
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

**Checks:** Each of the twelve array fields of `sequence_index(snap)` has `writeable`
False, a write into it raises `ValueError`, and `np.array(a)` of it is writable, for a
gradient echo sequence and for an empty one.

**How:** The test is parametrized over `gre_sequence` and `empty_sequence`. It finds the
array fields with `dataclasses.fields` and `isinstance(np.ndarray)` and checks that
there are twelve. For each, it checks the flag. For an array with elements it writes
one value inside `pytest.raises(ValueError)`. It then copies the array and checks that
the copy is writable (and takes a write when it has elements). An empty array has no
element to write, so only its flag is checked.

**Assumptions:** None.

#### `test_two_indexes_of_two_equal_sequences_are_equal_and_not_hashable`

**Checks:** Two `SequenceIndex` of two equal sequences are equal by value, the index of another
sequence is not equal, and an index is not hashable.

**How:** The test builds `gre_sequence()` two times and takes `sequence_index` of each: two
objects, and `==` is true. The index of `gre_sequence(num_trs=5)` and the index of the spin
echo are `!=` to the first. `hash(index)` is in `pytest.raises(TypeError)`.

**Assumptions:** None.

#### `test_has_gradients_is_true_only_for_an_index_with_a_gradient_event`

**Checks:** `has_gradients(index)` is True for an index with a gradient event on any axis, and
False for an index with none.

**How:** Parametrized over six sequences: the synthetic spin echo; one `make_trapezoid` block
on x, on y and on z; one delay block; and a sequence with no blocks. The test checks
`has_gradients(sequence_index(snap)) is expected`: True for the first four, False for the last
two.

**Assumptions:** None.

#### `test_sequence_index_of_a_sequence_with_no_blocks`

**Checks:** `sequence_index` of a `pp.Sequence` with no blocks added has `num_blocks`
0, `end_s` 0.0, and every array (`block_id`, `start_s`, `duration_s`, `rf`, `gx`,
`gy`, `gz`, `adc`, `rf_first`, `grad_first`, `grad_first_axis`, `adc_first`) empty.

**How:** The test builds `pp.Sequence(SYSTEM)` with no `add_block` call, computes
`sequence_index(snap)`, and checks `num_blocks`, `end_s`, and the size of each of the
twelve arrays.

**Assumptions:** None.

#### `test_a_function_of_the_index_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** The function raises `TypeError` with a message that names `load` when its first
argument is a `pp.Sequence` or a path, and not a `Snapshot`.

**How:** Parametrized over `sequence_index`, `rf_events`, `grad_events` and `adc_events`, and over
a `gre_sequence()` and the path string `"sequence.seq"`. The call must raise `TypeError`
with `match="load"`.

**Assumptions:** The path `"sequence.seq"` is not read: the type check comes before any read.

#### `test_sequence_index_is_kept_for_one_snapshot_and_made_again_for_another`

**Checks:** `sequence_index(snap)` returns the same object on a second call for the same
snapshot, and a snapshot made again from the same sequence gives its own, equal index.

**How:** The test builds `gre_sequence()` and makes a snapshot with `load`. Two calls of
`sequence_index` must give the same object (`is`). The index of a second snapshot of the
same sequence must be another object (`is not`) and equal (`==`) to the first.

**Assumptions:** `SequenceIndex` compares by value (tested by
`test_two_indexes_of_two_equal_sequences_are_equal_and_not_hashable`).

#### `test_rf_events_reads_each_unique_event_once_and_keeps_the_tuple`

**Checks:** `rf_events` calls `get_block` exactly once for each unique RF event of the
snapshot, with the block cache off, gives a tuple of `(dense index, event)` with the dense
indexes 1 to K in order, and keeps the tuple: a second call gives the same tuple and reads
no block. Each event equals the event of the same block read separately.

**How:** The snapshot is of `spin_echo_sequence()`, which has two distinct RF events (excitation and refocusing). The test replaces `get_block` of the snapshot's sequence (the instance)
with a counting wrapper that records `use_block_cache` at each call. It calls `rf_events(snap)`
and checks that the result is a `tuple`, that the call count is the number of unique
first-use blocks (`numpy.unique` of the `*_first` array of the index), that every recorded
flag is `False` and that `snap.sequence.use_block_cache` is `False`. It checks the dense
indexes and that `delay`, `type` and `signal` of each event equal those of the event of
`original(block_id).rf`, read again through the saved `get_block`. It clears the call
list and calls `rf_events(snap)` again: the result must be the same object (`is`) and the list
must stay empty.

**Assumptions:** None.

#### `test_grad_events_reads_each_unique_first_use_block_once_and_keeps_the_tuple`

**Checks:** `grad_events` calls `get_block` exactly once for each unique gradient event of the
snapshot, with the block cache off, gives a tuple of `(dense index, event)` with the dense
indexes 1 to K in order, and keeps the tuple: a second call gives the same tuple and reads
no block. Each event equals the event of the same block read separately.

**How:** The snapshot is of a sequence with a z trapezoid in block 0, and an x trapezoid and a y trapezoid in block 1, so `grad_first` is `[0, 1, 1]`: gx and gy are first used in one block, which is read one time, not two. The test replaces `get_block` of the snapshot's sequence (the instance)
with a counting wrapper that records `use_block_cache` at each call. It calls `grad_events(snap)`
and checks that the result is a `tuple`, that the call count is the number of unique
first-use blocks (`numpy.unique` of the `*_first` array of the index), that every recorded
flag is `False` and that `snap.sequence.use_block_cache` is `False`. It checks the dense
indexes and that `delay`, `type` and `amplitude` of each event equal those of the event of
`original(block_id).<axis>`, read again through the saved `get_block`. It clears the call
list and calls `grad_events(snap)` again: the result must be the same object (`is`) and the list
must stay empty.

**Assumptions:** The axis of each event is `grad_first_axis`, so the attribute is `gz`, `gx` and `gy` of the block.

#### `test_adc_events_reads_each_unique_event_once_and_keeps_the_tuple`

**Checks:** `adc_events` calls `get_block` exactly once for each unique ADC event of the
snapshot, with the block cache off, gives a tuple of `(dense index, event)` with the dense
indexes 1 to K in order, and keeps the tuple: a second call gives the same tuple and reads
no block. Each event equals the event of the same block read separately.

**How:** The snapshot is of `gre_sequence(num_trs=5)`, where one ADC event is reused every TR. The test replaces `get_block` of the snapshot's sequence (the instance)
with a counting wrapper that records `use_block_cache` at each call. It calls `adc_events(snap)`
and checks that the result is a `tuple`, that the call count is the number of unique
first-use blocks (`numpy.unique` of the `*_first` array of the index), that every recorded
flag is `False` and that `snap.sequence.use_block_cache` is `False`. It checks the dense
indexes and that `delay`, `num_samples` and `dwell` of each event equal those of the event of
`original(block_id).adc`, read again through the saved `get_block`. It clears the call
list and calls `adc_events(snap)` again: the result must be the same object (`is`) and the list
must stay empty.

**Assumptions:** None.

### 2.5 Raster sampler (`test_sampling.py`)

`test_sampling.py` tests `sampling.py`: `GradientSampler`, which gives the gradient
waveform of one axis at sorted times, from
the sequence index and the kept points of the unique gradient events
(`_events.event_points`), made with `gradient_sampler(snap)`. The waveform is the gradient
waveform of MATLAB Pulseq (`docs/implementation.md`, section 1). The reference is the oracle waveform of
`tests/oracles/waveform.py` (section 2.15) for every sequence with an end that is not 0 next to
a long gap, or with a step at a block junction. For the other sequences it is also pypulseq's
`seq.get_gradients()`, because pypulseq draws a line across each gap and has no step at a
junction (pypulseq-issues 12). `_assert_matches_oracle` compares `sample(axis, t)` with
`oracle.sample`. `_assert_matches_pypulseq` compares it with the `PPoly` of each axis. Both use
a relative 1e-12 and an absolute 1e-12 times the largest |value| of the reference. They are not
bit-exact. `seq_utils.gradient_offsets` adds a trapezoid's corner times in a different order than
pypulseq's `waveforms()`, and `PPoly` evaluates a line segment with a different formula than
`numpy.interp`. The oracle makes its points with the same sums as the sampler, so the
difference to the oracle is the rounding of the interpolation formula only. The comparisons
check `GradientSampler`, not pypulseq.

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

#### `test_a_subrange_inside_a_long_gap_has_its_ramps_and_zero_and_matches_the_oracle`

**Checks:** A time range inside a long gap between two events on one axis gives the values of
the oracle. The values are the ramp to 0 after the first end, 0 between the ramps, and the ramp
from 0 before the second end. Both ends have a value that is not 0. The call has no event inside
its block range, so it needs the events before and after.

**How:** `_gap_sequence` has an extended trapezoid on x that ramps from 0 to half of
`max_slew * grad_raster_time` over 5 raster steps, a 2 ms delay block, and an extended trapezoid
that starts at a quarter of `max_slew * grad_raster_time` and ramps to 0 over 5 steps.
(`add_block` accepts a value up to `max_slew * grad_raster_time` next to a block with no
gradient.) `t` has 5 times inside the first ramp, 20 times between the ramps and 5 times inside
the second ramp. A ramp is half a raster time long. The test checks that the ramp values are not
0 and the middle values are exactly 0. It then compares all three axes with `oracle.sample`
(`_assert_matches_oracle`).

**Assumptions:** The model of MATLAB Pulseq: a gap of more than one raster time has a ramp to 0
and a ramp from 0, each half a raster time long. pypulseq draws a line across it
(pypulseq-issues 12).

#### `test_range_across_a_step_and_a_ramp_equals_the_same_slice_of_the_whole_grid`

**Checks:** `GradientSampler.sample` of each sub-range of a sorted grid of times, around a step
at a block junction and around the ramp and the gap after it, gives exactly the matching slice of
`sample` of the whole grid. It also equals the oracle. A range that starts in the gap uses the
last point of the event before the gap. A range that ends in the gap uses the first point of the
event after it.

**How:** `_step_then_gap_sequence` has four blocks with events on x. They are the rise and half
of the flat top of a trapezoid (area 1000), the rest of the flat top and the fall
(`make_extended_trapezoid`), `make_delay(2e-3)` (the gap), and a trapezoid (area -500). The
second block starts `0.5 * max_slew * grad_raster_time` below the end of the first (a step that
`add_block` accepts) and ends at the same value above 0. So the waveform after the event is the
ramp to 0 in half a raster time, then 0. The grid has 33 times. They are steps of half a raster
time around the junction, the start of the gap and the start of the last trapezoid, 5 times
inside the ramp, and 7 times in the gap. The test checks that the values in the ramp are not 0
and the values after the ramp are 0. It compares `sample("gx", t[i:j])` with `whole[i:j]`
(`numpy.array_equal`) for each pair `i < j`. It also compares the whole grid with the oracle.

**Assumptions:** With a last value of 0 for the second block, the gap is 0 with and without the
neighbour events, and the test cannot find their removal. The value that is not 0 lets it.

#### `test_times_before_an_event_that_starts_at_a_value_that_is_not_0_have_the_ramp_from_0`

**Checks:** `GradientSampler.sample` at times in a long gap whose next event starts at a value
that is not 0 gives 0 in the gap, and the ramp from 0 in the last half raster time before the
event. pypulseq gives a line from the earlier event instead.

**How:** Block 0 has a trapezoid on x that ends at 300 µs (`duration=300e-6`, amplitude 0.1 of
`max_grad`) and a 1 ms delay in the same block. Block 1 is an extended trapezoid on x that
starts at half of `max_slew * grad_raster_time` and ramps to 0 over 5 raster steps. The gap is
700 µs, so it is a long gap. `t` is 600, 800, 995, 996, 997.5, 999 and 1000 µs. The expected
values are 0, 0, 0, 0.2, 0.5, 0.8 and 1 times the start value. The test compares them with
`numpy.testing.assert_allclose` (relative 1e-9, absolute 1e-9 of the start value) and with the
oracle.

**Assumptions:** None.

#### `test_single_sample_matches_pypulseq`

**Checks:** `sample` gives the pypulseq value for a `t` array of length 1.

**How:** Builds `gre_sequence(num_trs=1)`, samples at one time (the middle of the
readout block), and compares with `_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_amplitude_continues_across_a_block_junction`

**Checks:** Two extended trapezoids that together make one trapezoid, split into two
blocks at the middle of the flat top so the amplitude continues unchanged from one
block into the next, give the same waveform as `seq.get_gradients()` around the
junction: the junction does not create a spurious step.

**How:** `_junction_sequence(step_hz_per_m=0.0)` builds the two extended trapezoids
from the rise, flat and fall of one area-1000 trapezoid, split at the middle of the
flat top, and returns the junction time. `t` is 41 points evenly spaced over 40
gradient-raster periods centred on the junction. Compares with
`_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_a_tolerated_step_at_a_block_junction_is_a_step_that_the_oracle_has`

**Checks:** A step at a block junction inside what `add_block` accepts (up to
`max_slew * grad_raster_time`) is a step. The value at the time of the step is the earlier
value. After it, the waveform follows the later event from its first value. pypulseq draws a
line from the earlier value to the end of the flat of the later event, so the test does not
compare with pypulseq.

**How:** The construction of `test_amplitude_continues_across_a_block_junction`, with
`_junction_sequence`'s `step_hz_per_m` set to half of `max_slew * grad_raster_time`. `t` is 41
points over 40 gradient-raster periods around the junction. The test compares them with the
oracle. It also checks the hand values at 10 raster times before the junction, at the junction,
and 10 raster times after it. They are the amplitude, the amplitude, and the amplitude less the
step. The test does not check that `add_block` accepts the step. That is pypulseq's own check,
exercised here only because building the sequence requires it to pass.

**Assumptions:** None.

#### `test_triangle_trapezoid_matches_pypulseq`

**Checks:** A trapezoid with no flat time (`make_trapezoid` gives `flat_time == 0.0`),
whose `gradient_offsets` therefore has two points at the same time with the same
value, gives the same waveform as `seq.get_gradients()`: the removal of a point that
has the time and the value of the point before it does not change the value.

**How:** Builds a single-block sequence with one small-area trapezoid on x, asserts
`flat_time == 0.0` to confirm the construction is the intended triangle, samples the
whole file at the raster centres, and compares with `_assert_matches_pypulseq`.

**Assumptions:** None.

#### `test_sample_matches_the_added_events_for_an_oversampled_arbitrary_gradient`

**Checks:** `sample` gives the correct waveform for a file with an oversampled
arbitrary gradient (`make_arbitrary_grad(oversampling=True)`): pypulseq issue #423, fixed
by the project's
pypulseq pin (`pulseq-reports-pin-2`, with the fix of pypulseq PR #424). The reference is not
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
more than 1e-9 s after the point before it (the join rule of pypulseq's `waveforms()`).
`GradientSampler.sample("gx", t)` is compared with `numpy.interp` on that polyline at
3999 points evenly spaced over the file, within an absolute 1e-12 times the peak of the
reference (`rtol=0`). Before the pin's fix, this test's own error is about 40 % of the
peak (checked against a pypulseq checkout at the old pin, `20b9e5e`).

**Assumptions:**

- The pin (`pulseq-reports-pin-2`) has the fix of pypulseq PR #424. A pypulseq without
  it fails this test: checked against a checkout of the old pin (`20b9e5e`).

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
`raster_block_lengths`. `block_samples` gives the samples of the PNS lane at the local times
`(j + 0.5) * dt` of each block, with the value of the own event of the block (0 before its
first point and after its last point). The samples that a short gap (the line) or a ramp of a
long gap covers have the value of that line or ramp. It is the waveform of `sample` (the model of
MATLAB Pulseq), with no time drift from the block start sums, except in a gap.

#### `test_sample_equals_the_oracle_for_the_whole_sequence`

**Checks:** `GradientSampler.sample` equals `oracle.sample` on a grid across each sequence of
the model. The sequences cover each gap rule: a zero gap, a short gap, a long gap, the first and
the last value not 0, the two sequences of pypulseq-issues 12, a step followed by a gap, an event
that is not on a raster edge, and the synthetic spin echo, GRE and arbitrary-gradient sequences.
They also cover negative end values, a gap between one and two raster times, and a short gap
with an end of 0.

**How:** Parametrized over 29 sequences (`_MODEL_SEQUENCES`): 12 hand and synthetic sequences,
and 17 more, `gap_of_1_5_raster_times_sequence` (a long gap of 1.5 raster times between two values that are not 0), `short_gap_from_0_sequence` and `short_gap_to_0_sequence` (a short gap from 0 to a value, and from a value to 0), a copy of each sequence of `tests/gap_sequences.py` with each amplitude negated (`gap_sequences.negated`), and the 8 sequences of `random_gaps.random_gap_sequence` with the seeds 0 to 7 (random signs, delays of 0 to 7 raster times, and zero, short and long gaps). `t` is the raster centres, 2001
evenly spaced times from one raster time before the start to one after the end, and the times of
the points of the polyline of the oracle on each axis, each also 0.1 µs before and after. So the
ramp points, the steps and the ends are in the grid. The test compares all three axes with a
relative 1e-12 and an absolute 1e-12 of the peak.

**Assumptions:** The oracle makes its points with the same sums as the sampler. The difference
is the rounding of the interpolation formula only.

#### `test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`

**Checks:** For each time range `t[i:j]` of a grid, `sample` equals the oracle, and the same
slice of `sample` of the whole grid exactly. The ranges start or end at an end of an event,
inside a gap, inside a ramp, and at a step.

**How:** Parametrized over `long_gap`, `short_gap`, `zero_gap`, `issue_12_delayed`,
`off_raster_events`, `gap_of_1_5_raster_times`, `short_gap_from_0` and `negated_long_gap`. The grid is about 40 times, every n-th time of the grid of the test above.
For each axis, the test compares the whole grid with the oracle. It then compares
`sample(t[i:j])` with `whole[i:j]` (`numpy.array_equal`) for each pair `i < j`.

**Assumptions:** None.

#### `test_a_ramp_to_0_and_a_ramp_from_0_cross_a_long_gap_by_hand`

**Checks:** `sample` has the hand values at the two ramps of a long gap between events that do
not start or end on a raster edge. It has 0 between the ramps and after the last point. A line
across the gap, as pypulseq draws it, would not be 0 between them.

**How:** `_off_raster_events_sequence` has two blocks of 8 raster times on x. Block 0 has a ramp
from 0 to `A = max_slew * grad_raster_time / 2` over 3 raster times, from 0.3 to 3.3. Block 1
has a ramp from `A / 2` to 0 over 3 raster times, from 8.7 to 11.7, after a delay of 0.7 raster
times. The ramp to 0 is from 3.3 to 3.8 raster times. The ramp from 0 is from 8.2 to 8.7. The
test samples 3.3, 3.5, 3.8, 5, 8.2, 8.5, 8.7, 11.7 and 12 raster times. It compares with the
values `A * [1, 0.6, 0, 0, 0, 0.3, 0.5, 0, 0]` (absolute 1e-9 of `A`). It also checks that
`seq.get_gradients()` at 5 raster times is not 0.

**Assumptions:** `add_block` accepts the delays that are not on the raster and the start value
that is not 0 after a delay, because the value is below `max_slew * grad_raster_time`.

#### `test_the_gaps_are_found_one_time_for_each_sequence_and_axis`

**Checks:** `_find_gaps` gives the two ramps of a long gap with their times and values. Two
samplers of one snapshot share the kept result. Its arrays are read-only. An axis with no event
has no pieces. A second snapshot of the same sequence finds its own result.

**How:** `long_gap_sequence` has a gradient that ends at 3 U at 100 µs, a block with no gradient,
and a gradient that starts at 2 U at 300 µs. The test checks the pieces: 100 to 105 µs from 3 U
to 0, and 295 to 300 µs from 0 to 2 U. It checks the ramp points of `_events.ramps`: the ramp to
0 ends at 105 µs and the ramp from 0 starts at 295 µs. It checks that a second sampler gives the
same object (`is`), that `writeable` is False for each array, and that gy has no pieces. A sampler
of a second snapshot of the same sequence gives another object with equal pieces.

**Assumptions:** The test reads the private `GradientSampler._gaps` and
`GradientSampler._axis_events`.

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
off the ideal raster grid by float rounding. The difference is that drift only.

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

#### `test_the_sample_at_a_last_point_that_is_many_steps_in_has_the_value_of_that_point`

**Checks:** A sample at exactly the time of the last point of an event, many steps into
the block, has the value of that point (not 0). The sample after it is 0, and each earlier
sample is below that value.

**How:** `dt` is two raster steps. A ramp from 0 to 1000.0 Hz/m over 27 raster steps
(`pp.make_extended_trapezoid`) in a block of 30 raster steps (a delay event). The test
asserts `(13 + 0.5) * dt == 27 * raster` in floats. `block_samples("gx", 0, 1, dt)` has 15
samples. Sample 13 equals 1000.0, sample 14 equals 0.0, and samples 0 to 12 are below
1000.0.

**Assumptions:** The float product `(13 + 0.5) * dt` equals `27 * raster`. This is why the
test uses 27 steps, and the test asserts it.

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

#### `test_sequence_samples_on_the_raster_is_the_sum_of_the_block_lengths`

**Checks:** `sequence_samples` gives the sum of the block lengths for a sequence
on the raster, and not a `ceil` of the end time, which can give one sample more.

**How:** A sequence of two delay blocks of 0.01938 s and 0.01268 s (1938 and 1268
samples at 1e-5 s). `sequence_samples(index, dt)` must be 3206. The test also
checks that `ceil(index.end_s / dt)` is 3207, so the sequence has the case that
the rule is for.

**Assumptions:**

- `index.end_s` is 3206.0000000000005 samples (the float sum of the two
  durations). A change of pypulseq or of numpy that makes it exact makes the
  second check fail, and the test then needs another pair of blocks.

#### `test_sequence_samples_off_the_raster_is_the_ceil_of_the_end`

**Checks:** For a sequence with a block off the raster, `sequence_samples` gives
`ceil((index.end_s - 1e-10) / dt)`.

**How:** Two sequences of two delay blocks. For 1.4 and 1.4 samples, the end is
2.8 samples and the result must be 3 (the sum of the rounded block lengths is 2).
For 1.5 and 1.500005 samples, the end is 3.000005 samples, which is less than
1e-10 s above 3 samples, and the result must be 3 (a `ceil` of the end without
the 1e-10 s gives 4). Each sequence must be off the raster in
`raster_block_lengths`, and the result must equal `ceil((index.end_s - 1e-10) /
dt)`.

#### `test_raster_block_lengths_tolerance_is_a_millionth_of_a_sample`

**Checks:** A block whose length is within 5e-7 samples of a whole number is on the
raster, and one that is 2e-6 samples away is not (`ON_RASTER_TOLERANCE` is 1e-6). The
number of samples is the whole number in each case.

**How:** Parametrized on the ratio `1 + 5e-7`, `1 - 5e-7`, `1 + 2e-6` and `1 - 2e-6`. A
one-block sequence with `pp.make_delay(ratio * dt)`. The test checks that `duration_s /
dt` equals the ratio within 1e-12, then that `raster_block_lengths(index, dt)` gives the
expected `on_raster` and `n == [1]`.

**Assumptions:** None.

#### `test_block_samples_equals_the_oracle_for_the_whole_sequence`

**Checks:** `block_samples` of the whole sequence equals `oracle.block_samples` for each axis,
at the gradient raster and, for the sequences with a gap, at finer rasters (one half and one
fifth of it). At the finer rasters, a ramp of half a raster time has samples in it.

**How:** Parametrized over `_WHOLE_CASES`: the 29 sequences of the model (see
`test_sample_equals_the_oracle_for_the_whole_sequence`) at the gradient raster, and `short_gap`,
`long_gap`, `issue_12_delayed`, `step_then_gap`, `off_raster_events`, `gap_of_1_5_raster_times`,
`short_gap_from_0`, `short_gap_to_0`, `negated_long_gap` and `negated_short_gap` at one half and
one fifth of it (49 cases). The test compares each axis with an absolute 1e-9 of the
largest value.

**Assumptions:** The two are not bit-equal. `block_samples` takes the sample time from the block
start, and the oracle from the sum of the block durations before it. The sum drifts by float
rounding. The difference is that drift only.

#### `test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range`

**Checks:** Each range of blocks and each range of samples (`skip` and `count`) of
`block_samples` equals the same samples of the oracle. It also equals the same slice of the whole
range exactly. The ranges start or end inside a gap, inside a ramp, and at a block edge. A new
sampler gives the same values as one that made the whole range first.

**How:** Parametrized over nine cases of a sequence and a sample raster: `long_gap` at one half
of the gradient raster, `short_gap` and `zero_gap` at the gradient raster, `issue_12_delayed` at
one fifth, `step_then_gap` at the gradient raster, `off_raster_events` at the gradient
raster and at one fifth, `gap_of_1_5_raster_times` at the gradient raster, and `negated_long_gap`
at one half. Each gap kind and each raster is in at least one case. For each axis and
each block range, the test compares the samples with the oracle and with the slice of the whole
range (`numpy.array_equal`). It does the same for each `(skip, count)` of `_sample_ranges`, on the
sampler of the test and on a new one.

**Assumptions:** The tolerance to the oracle is the one of the test above.

#### `test_one_event_in_blocks_of_two_lengths_gives_the_samples_of_each_length`

**Checks:** One gradient event in two blocks of different lengths gives the samples of each
length: the samples of `oracle.block_samples` for the block, and exactly the samples of a new
sampler that meets only that range. `block_samples` keeps the samples of an event for all the
lengths (the cache key is `(event, dt)`, and a block of `n` samples has the first `n` of them), so
this holds whichever length the sampler meets first.

**How:** Parametrized by the order of the two blocks (short then long, long then short). A
trapezoid on x (rise 50 us, flat 30 us, fall 50 us) is in both. The short block has the trapezoid
alone: 13 samples. The long block has it and a delay of 400 us: 40 samples, of which the last 27
are 0. The test checks that the two blocks have one event ID. For each of two orders of calls
(block 0 first, block 1 first), a new sampler gives block 0, block 1 and both blocks. Each range
is compared with the same samples of the oracle (1e-9 of the peak), and with the same range from
a new sampler (`numpy.array_equal`).

**Assumptions:** A block is never shorter than its event, so no block cuts the samples of its
event: the number of samples of an event is at most the number of samples of each block that has
it.

#### `test_the_samples_in_a_short_gap_are_the_line_by_hand`

**Checks:** A sample in a short gap (one raster time) is on the line from the last value of the
earlier event to the first value of the later event. It is 0 in the own event after its last
point.

**How:** `short_gap_sequence` has a gradient that ends at 3 U at 100 µs in a block of 110 µs, and
a second block that starts at 2 U. U is 1e4 Hz/m. The test checks the first 20 of the 21 samples
at the gradient raster with the hand values. The 11 samples of block 0 are 0.15, 0.45, ...,
2.85 U on the ramp, then 2.5 U at 105 µs on the line. The first 9 samples of block 1 are 1.9,
1.7, ..., 0.3 U.

**Assumptions:** The sample at 105 µs is not 0, so this test fails for a rule that gives 0 in
every gap.

#### `test_the_samples_in_a_ramp_of_a_long_gap_that_are_not_at_its_ends_are_the_ramp_by_hand`

**Checks:** A sample inside the ramp to 0 or the ramp from 0 of a long gap has the value of the
ramp, in the block of the event and in the next block.

**How:** `_off_raster_events_sequence` at the gradient raster. The ramp to 0 is from 3.3 to 3.8
raster times and has the sample at 3.5. The ramp from 0 is from 8.2 to 8.7 and has the first
sample of block 1 at 8.5. The test compares the 16 samples with the hand values (absolute 1e-9
of `A`). The values at 3.5 and 8.5 are 0.6 A and 0.3 A. The other samples are those of the own
events.

**Assumptions:** None.

#### `test_a_ramp_from_a_raster_edge_changes_no_sample_at_the_gradient_raster`

**Checks:** `block_samples` at the gradient raster for events on the raster edges has the
samples of the own events and 0 in a long gap. The ramps of half a raster time end at the raster
centres, where they are 0 (D7 of `docs/plans/third-review-fixes.md`).

**How:** `long_gap_sequence` has ends that are not 0 next to a long gap. The test checks that the
samples 10 to 29 are 0 (absolute 1e-9 of 3e4), that sample 9 is 2.85e4 and that sample 30 is
1.9e4.

**Assumptions:** A sample at the end of a ramp can be a rounding error from 0 (below 1e-9 of the
peak), because the ramp end and the sample time are each a sum of floats.

#### `test_block_samples_at_the_last_point_of_an_event_and_at_a_step_equals_the_oracle`

**Checks:** `block_samples` of the whole sequence equals `oracle.block_samples` at the gradient
raster where a sample falls at the last point of an event, and where it falls at a step inside
one event. The sample at the last point has the value of that point, also when the sum of the
delay and the offset of the point is one ulp before the sample time (review 1.3 of
`docs/reviews/2026-10-07-code-review.md`). The sample at a step has the value before the step,
the rule of `sample` (review 1.4).

**How:** Parametrized over 15 sequences. Fourteen are `gap_sequences.delayed_ramp_sequence`:
filler blocks of no gradient, and a ramp on x from 0 to A, after a delay of 0.5 to 4.5 raster
times, that ends at a sample time. Eight are the cases of `DELAYED_RAMP_CASES`: the sum
`delay + offset` of the last point is one ulp before the sample time, and `block_samples` gave 0
at that sample before the fix. Six are the cases of `ULP_EDGE_CASES`, chosen from a scan of 6960
cases: the sum `(start + delay) + offset` is before the sample time `start + (j + 0.5) * dt`, so
an oracle with no tolerance after the last point gives 0 there. In three of them `block_samples`
gave the end value before the fix too, and in three it gave 0. The test fails without the
tolerance in `block_samples`, and without the same tolerance in `oracle.block_samples`. The
fifteenth is `gap_sequences.short_arbitrary_sequence`, an arbitrary gradient of 3 samples whose
points `(tt[-1], wf[-1])` and `(shape_dur, last)` are at 25 us, a sample time. The test checks
the three axes against the oracle within 1e-9 of the largest absolute value. The same sequences
are in the parameters of the PNS test
`test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`.

**Assumptions:** The oracle takes the time of a point from the sum of the block durations
(`(start + delay) + offset`), and `block_samples` from the block start and the local time. The
oracle gives the value of the last point to a sample time within `TIME_TOLERANCE` after it, so
that the two agree on the value at the last point.

#### `test_gradient_sampler_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `gradient_sampler` and the constructor `GradientSampler` raise `TypeError` with
a message that names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over `gre_sequence()` and the path string `"sequence.seq"`. Both calls
must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

### 2.6 Gradient peaks (`test_grad_peaks.py`)

`test_grad_peaks.py` tests `grad_peaks.py`: the peak amplitude, the peak slew
rate and the RMS amplitude of a sequence's gradients, on each logical axis and
as a three-axis vector, over the whole sequence or over a window. Every
expected value is computed by hand from the parameters of the trapezoid or
arbitrary gradient that the test builds, not by calling `gradient_peaks`
itself for the expected value. The values are in Hz/m and Hz/m/s, the units of pypulseq,
with no gamma, so the hand-computed values have no conversion. No comparison with the
oracle converts the values: the oracle gives Hz/m and Hz/m/s. `GAMMA_1H` from
`tests/synthetic.py` only converts the mT/m values of the sequences with a 4 µs
raster.

`grad_peaks.py` computes its values from the per-event values of `seq_index.grad_events` and
the columns of `seq_index.sequence_index`, instead of reading every block with `get_block`. It
uses the gradient waveform of MATLAB Pulseq: a step across a zero gap, a line across a short gap,
and a ramp to 0 and a ramp from 0 across a long gap (`docs/implementation.md`, section 1). The slew
includes the steps, the lines and the ramps. The tests below the first group add: the largest
slew of an arbitrary gradient and of an extended trapezoid (computed from the event's own corner
points), the credited block for a value that several blocks and axes share, a window that keeps
only part of a ramp's slew, the vector peak of two blocks with different triples of active
gradients, the step at a junction, the step at the last point of an axis, the ramps of a first
value after a delay, the gap sequences of `tests/gap_sequences.py` with their hand-computed
values, the refusal of a bad window before the sequence is read, the range of a window past an
end of the sequence, and comparisons with the oracle of the gradient waveform
(`tests/oracles/waveform.py`, section 2.15). The oracle builds the polyline of each axis one
time and reads every value from it, so it shares no code with the package.

The last group tests `block_gradient_values`: the values of each block, in play order. Its
main test compares the maxima over the blocks with the whole-file result of `gradient_peaks`.
The other tests check the blocks without an event on an axis, the junction of each block, the
items that each block has in the polyline of the oracle, the arrays, and the refusal of the
rotation extension.

#### `test_trapezoid_peak_slew_and_rms_match_hand_computed_values`

**Checks:** For a single x trapezoid, `gradient_peaks` gives the peak
amplitude, the peak slew rate and the RMS amplitude that hand computation from
the trapezoid's own rise time, flat time and amplitude predicts.

**How:** The test builds one block with an x trapezoid of a given amplitude,
rise time and flat time, and calls `gradient_peaks` on it. It computes the
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

**Checks:** The values of `gradient_peaks` (with and without a window) and of
`block_gradient_values` do not depend on `seq.system.gamma`. For one waveform in Hz/m, the
values of a sequence of `SYSTEM` and of a sequence of a copy of `SYSTEM` with another gamma are
exactly equal, in every field.

**How:** The test makes a copy of `SYSTEM` with `gamma = 0.9 * SYSTEM.gamma`. It builds the
same sequence for each system: an x trapezoid with an explicit amplitude in Hz/m, a y arbitrary
gradient with an explicit waveform in Hz/m (`first` and `last` 0), and a block with both. It
checks that the two gammas differ and that the sequence has gradients. It compares the
`GradientPeaks` of the whole sequence and of a window of the first half field by field with
`==` (the axes, the vector peak, its time and block, and the RMS over the whole file of the
window result), and each array and each dict entry of the two `BlockGradientValues` with
`numpy.array_equal`.

**Assumptions:** `pp.make_trapezoid` with an explicit `amplitude` and `pp.make_arbitrary_grad`
with a waveform in Hz/m use no gamma, so the two sequences have the same events. The test
follows `test_spectrum_does_not_depend_on_the_gamma_of_the_system` in section 2.10.

#### `test_the_values_of_a_negated_waveform_are_equal`

**Checks:** A value is a magnitude, so a sequence with each amplitude times -1 gives exactly
equal values of `gradient_peaks` (with and without a window) and of `block_gradient_values`,
in every field. This is why the documents use the magnitude of gamma, which can be negative.

**How:** The test builds the sequence of the test above for `SYSTEM`, one time with the
amplitude of the trapezoid and the waveform of the arbitrary gradient as they are, and one
time with each of them times -1 (an exact operation). It checks that the sequence has
gradients, then compares the results as the test above does: field by field with `==` for
`GradientPeaks`, with `numpy.array_equal` for each array of `BlockGradientValues`.

**Assumptions:** The multiplication by -1 of a float is exact, so the two sequences differ only
in the sign. The test checks that the values are equal for this sequence.

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
and calls `gradient_peaks`. It computes the expected peak as the largest of
`abs(first)`, `abs(last)` and the largest absolute waveform sample, taken from
the block's own gradient event. It checks that the x axis peak matches (Hz/m).

**Assumptions:**

- `seq_utils.gradient_points` adds `first` and `last` as extra points at the
  ends of an arbitrary gradient's shape (checked by `test_gradient_offsets_arbitrary`
  and `test_gradient_points_matches_gradient_offsets_exactly` in `test_seq_utils.py`), so they can hold the largest magnitude even when
  every interior waveform sample is smaller.

#### `test_no_gradients_sets_reason`

**Checks:** A sequence with no gradient at all gives a set `reason`,
and every numeric field is its zero value: 0.0 for an amplitude, slew or RMS
field, and None for a block field.

**How:** The test builds a sequence with one delay block and no gradients, and
calls `gradient_peaks`. It checks that `reason` is
`seq_index.NO_GRADIENTS`, that the vector peak and its time are
0.0, and that every axis's peak, slew and RMS are 0.0 with `peak_block` and
`slew_block` both None.

**Assumptions:** None.

#### `test_arbitrary_gradient_max_slew_is_the_largest_neighbouring_slope`

**Checks:** The largest slew of an arbitrary gradient is the largest
`|delta g / delta t|` between its neighbouring corner points (the shape's
`first`, its waveform samples, and its `last`).

**How:** The test builds an x arbitrary gradient from an asymmetric sine-lobe
waveform and calls `gradient_peaks`. It computes the expected slew from
`block.gx.first`, `block.gx.waveform`, `block.gx.last` and their own offset
and shape-duration fields (the same corner points `gradient_offsets` builds),
as the largest `|diff(amplitude) / diff(time)|`, not by calling
`gradient_peaks` for the expected value. It checks that the x axis slew
matches.

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

#### `test_junction_step_equal_to_a_segment_slope_of_its_block_takes_the_credit`

**Checks:** A junction step that equals the steepest segment slope of the next block gives
the slew credit to the junction: `slew_time_s` is the start of that block, and
`slew_block` is that block.

**How:** Block 1 ramps x from 0 to A in 2 raster steps and holds A for 1. Block 2 is an
extended trapezoid with the amplitudes `[0, 0, A, A, 0]` at `[0, 1, 2, 6, 8]` raster steps,
so its steepest segment (0 to A in one step) has the slope of the junction step (A to 0).
The test checks the slew (`A / raster`), `slew_time_s` (3 raster steps, the start of block
2) and `slew_block` (the second block ID).

**Assumptions:** A is `0.5 * max_slew * grad_raster_time`, so `add_block` accepts the
step. The two slews are equal in floats for these values.

#### `test_segment_of_an_earlier_block_with_the_slew_of_a_junction_step_takes_the_credit`

**Checks:** A segment of block 1 and the junction step of block 2 have the same slew, and
it is the largest of the file. The earlier block takes the credit: `slew_block` is block 1
and `slew_time_s` is the start of its first segment (0), not the start of block 2.

**How:** Block 1 is an x extended trapezoid with the amplitudes `[0, A, A, 0]` at `[0, 1,
3, 5]` raster steps. Block 2 has `[A, A, 0]` at `[0, 2, 4]` raster steps. A is `0.5 *
max_slew * grad_raster_time`. The slopes are A / raster (block 1, rise), 0, A / (2 raster)
(block 1, fall), 0 and A / (2 raster) (block 2, fall). The junction steps are 0 (block 1)
and A / raster (block 2). The test checks with `==` that the junction step of block 2
equals the slew of block 1 in `block_gradient_values`. Then it checks the slew (`A /
raster`), `slew_block` (the first block ID) and `slew_time_s` (0.0) of `gradient_peaks`.

**Assumptions:** A is chosen so that `add_block` accepts the step. The two slews are equal
in floats for these values, and the test checks this.

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

#### `test_block_gradient_values_use_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The `junction_hz_per_m_per_s` of `block_gradient_values` is divided by
`seq.grad_raster_time` (the `GradientRasterTime` that the file declares), not by
`seq.system.grad_raster_time`. A sequence read from a file gives the same values as the
sequence object that wrote it.

**How:** `raster_4us_sequence` has a junction of 60 T/m/s with 4 µs (24 T/m/s with 10 µs).
The test writes the sequence to a file in `tmp_path` and reads it with `pp.Sequence()`,
whose `system` has 10 µs. For the sequence that was read and for the sequence object, it
checks that the y junction step of block 2 is 60 T/m/s times `GAMMA_1H` (Hz/m/s), that the
step of block 1 is 0, and that the x and z steps are 0 everywhere.

**Assumptions:** The file stores the amplitudes with fewer digits than the sequence
object, so the comparison has a relative tolerance of 1e-4.

#### `test_gradient_ending_non_zero_at_the_last_point_of_the_axis_has_a_step_in_its_own_block`

**Checks:** A gradient that ends at a non-zero value (within the limit that `add_block`
accepts) and is the last event of its axis has a step to 0 at its last point. The step is the
slew of the whole file, and it is credited to the block of the event. It is not credited to the
block after it.

**How:** The test builds an x extended trapezoid that goes from 0 to 90% of the largest step
that `add_block` accepts, in 100 µs, and holds that value to 200 µs. A delay block of 1 ms
follows it. The step is the value divided by `grad_raster_time`, which is 10 times the slope of
the rise. The test checks that the x slew is that value, that `slew_block` is block 1, and that
`slew_time_s` is 200 µs.

**Assumptions:** The step after the last point is credited to the block of the last event
(decision D5 of `docs/plans/third-review-fixes.md`). Before task 2.1 of that plan, the step was
the junction of the block after it.

#### `test_a_gradient_that_ends_at_the_end_of_the_sequence_has_no_step_after_a_round_trip`

**Checks:** A gradient that ends at a value that is not 0 at the end of the sequence has no step
after its last point, whether the sequence is in memory or was written and read. The result does
not depend on one ulp of `(start + delay) + shape_dur`. Review 1.2 of
`docs/reviews/2026-10-07-code-review.md` and decision D1 of `docs/plans/fourth-review-fixes.md`.

**How:** The test is run for 20 values of `k`. It builds an x trapezoid with a slope of
1e9 Hz/m/s and a flat time of `(5 + k)` raster times, then a block of 0.6 ms with an x extended
trapezoid that rises to `A` in 100 µs and holds it to the end of the block. The step to 0 after
the last point would be `A / DT` (3.19e9 Hz/m/s), above the slope of the trapezoid. The test
writes the sequence to a `.seq` file in `tmp_path` and reads it. For the sequence in memory and
for the sequence that was read, it checks that the largest x slew of `gradient_peaks` is 1e9
Hz/m/s and is credited to block 1, that the slew of block 1 in `block_gradient_values` is 1e9, and
that the slew of block 2 is `A / 100 µs` (the rise: the step is not counted). It checks the same
slew and credit in the oracle.

**Assumptions:** The 20 end times do not each give a different rounding of the last time: the
test relies on some of them giving a last time one ulp before `end_s` and others giving it equal
to `end_s`. The slew of 1e9 Hz/m/s and the values of `A` hold for the system of
`tests/synthetic.py`, and the compare has a relative tolerance of 1e-6 because the file keeps
the amplitudes with fewer digits.

#### `test_the_step_after_the_last_point_is_counted_only_beyond_the_tolerance_before_the_end`

**Checks:** The step to 0 after the last point of an axis, at the end of the sequence, is counted
when the last point is more than `TIME_TOLERANCE` before the end, and is in no range when the
last point is within `TIME_TOLERANCE` of the end, also in a window that ends a little before the
end of the sequence (decision D1 of `docs/plans/fourth-review-fixes.md`: a step is in `[lo, hi]`
when `lo <= t < hi` and `t < end_s - TIME_TOLERANCE`).

**How:** The test is run for four values of `early`, the time from the last point of the
extended trapezoid to the end of the sequence: 0, half of `TIME_TOLERANCE`, 0.9 of
`TIME_TOLERANCE`, and one raster time. The sequence is an x trapezoid (slope 1e9 Hz/m/s), then a
block of 0.6 ms with an x extended trapezoid that ends at `A` at `0.6 ms - early`. The step is
`A / DT` (3.19e9 Hz/m/s). Only the one raster time counts it. Then the oracle, the whole file
and the window `(0.0, end_s)` of `gradient_peaks` give `A / DT` credited to block 2 at
`end_s - early`. For the other values they give 1e9 Hz/m/s in block 1. The window
`(0.0, end_s - 0.5 * TIME_TOLERANCE)`, in the oracle and in `gradient_peaks`, gives the same
slew and block: for an `early` of 0.9 of `TIME_TOLERANCE` the step is before the end of this
window, so only the rule `t < end_s - TIME_TOLERANCE` leaves it out. In every case the slew of
block 2 in `block_gradient_values` is `A / DT` (counted) or `A / 100 µs` (not counted).

**Assumptions:** pypulseq accepts a last time off the gradient raster by 1e-9 s or less, and no
more, so a value of `early` between `TIME_TOLERANCE` and one raster time cannot be built with
`make_extended_trapezoid`. The test does not cover a value between them. The window ends at
`end_s` of the index of the package, and the oracle uses the end of its last block: the two are
the same number for this sequence.

#### `test_first_block_not_starting_at_zero_is_a_junction_step_before_the_first_block`

**Checks:** A first block whose gradient starts at a non-zero value within
the tolerance `add_block` accepts: the step from 0 at the first point of the axis is a slew,
and it is credited to the first block.

**How:** The test builds a single x extended trapezoid starting at 90% of the
largest step `add_block` accepts. It computes the expected slew by hand as
that starting value divided by `grad_raster_time`. It checks that the x axis
slew matches and is credited to the first (only) block.

**Assumptions:** None.

#### `test_window_inside_a_block_with_no_gradient_ignores_the_step_to_zero_before_it`

**Checks:** A window that is inside the delay block after the sequence of the test above has
no gradient. A window that starts at the time of the step to 0 has the step. A window that ends
at that time does not have it, because a step counts for `lo <= time < hi`.

**How:** The test calls `gradient_peaks` with three windows. The window from 0.5 ms to 1.0 ms
must have `reason` equal to `seq_index.NO_GRADIENTS_IN_WINDOW`, an x slew of 0.0 and
`slew_block` equal to None. The window from 0.2 ms to 1.0 ms must have `reason` None, the x
slew equal to the step divided by `grad_raster_time`, and `slew_block` equal to block 1. The
window from 0 to 0.2 ms must have the slope of the rise (the value divided by 100 µs) and
block 1.

**Assumptions:** None.

#### `test_a_first_value_that_is_not_zero_after_a_delay_has_a_ramp_from_zero_in_its_block`

**Checks:** An x extended trapezoid with a delay and a first value that is not 0, after a block
that ends at 0, has a ramp from 0 in the last half raster time before its first point. It does
not have a step. The ramp is the slew of the whole file, and it is credited to the block of the
event. The junction of that block is 0.

**How:** Block 1 is an x trapezoid with ramps of 100 µs. Block 2 is an x extended trapezoid with
the amplitudes `[step, step, 0]` and `delay = 100 µs`, where `step` is 90% of the largest step
that `add_block` accepts. The gap is 100 µs, so it is a long gap. The slope of the ramp is twice
`step` divided by `grad_raster_time`, which is more than each other slope of the sequence. The
test checks the slew, `slew_block` (block 2), and `slew_time_s` (the start of block 2, plus the
delay, minus half a raster time, to 1e-12 s). It checks that the junction of block 2 is 0.

**Assumptions:** `add_block` accepts a delayed extended trapezoid with a first value that is
not 0, after a block that ends at 0. The ramp is the rule of MATLAB Pulseq (pypulseq-issues 12).

#### `test_window_that_cuts_the_ramp_from_zero_of_a_delayed_event_has_the_part_inside_it`

**Checks:** For the sequence of the test above, a window that starts in the middle of the ramp
from 0 has the second half of it. A window that ends where the ramp starts does not have the
ramp.

**How:** The ramp is from 395 µs to 400 µs. The window from 397.5 µs to the end must have the
same slew, `slew_block` equal to block 2, and `slew_time_s` equal to the window start (the
start of the cut). The window from 0 to 395 µs must have the slope of the ramps of block 1 (0.3
of the largest amplitude in 100 µs) and block 1.

**Assumptions:** The ramp is steeper than the slope of the ramps of block 1, which the test
checks.

#### `test_window_that_cuts_a_block_credits_it_on_a_tie_with_a_later_block`

**Checks:** When a block that the window start cuts and a later block fully inside the
window reach the same peak and the same slew, both are credited to the cut block, the first
in play order, as a single pass over the blocks would. The peak time and the vector peak
time are the first time the cut block reaches the peak.

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

**Checks:** When two blocks reach the same |G| peak, the vector peak time is the first time
that the earlier block reaches it, not a time in the later block, and the vector peak block is
the earlier block.

**How:** The test builds the same trapezoid on x in block 1 and on y in block 2, and checks that
`vector_peak_time_s` is 0.2 ms, the end of block 1's rise, and that `vector_peak_block` is
block 1.

**Assumptions:** The tie goes to the earliest time (the rule of the oracle). Here the earlier
time is in the earlier block.

#### `test_axis_whose_only_event_is_zero_credits_no_block`

**Checks:** An axis whose only event has amplitude 0 has a peak and a slew of 0, and no block
is credited for either (`peak_block` and `slew_block` are None).

**How:** The test builds one block with an x trapezoid and a y trapezoid scaled to amplitude
0 with `pp.scale_grad`, and checks the y axis's peak, slew and block fields.

**Assumptions:** None.

#### `test_a_zero_event_after_a_long_gap_has_the_start_of_its_block_as_slew_time`

**Checks:** In `block_gradient_values`, a block whose event has the amplitude 0 (for example the
centre of a phase-encode table) after a long gap has the slew 0 at the start of its block, not at
the time of a ramp.

**How:** Block 1 on x goes from 0 to U, then a delay block of 200 µs, then a trapezoid scaled to
the amplitude 0 (`pp.scale_grad(trapezoid, 0)`). The slew of x is `[2U/DT, 0, 0]` at the times
`[100, 100, 300]` µs: the zero block has its block start, 300 µs, not 295 µs.

**Assumptions:** None.

#### `test_a_vector_peak_tie_goes_to_the_earlier_time_when_the_later_block_has_it`

**Checks:** When two blocks have the same largest vector peak and the later block in play order has
the earlier time, the credit goes to the earlier time and its block, on the whole file and in a
window.

**How:** Parametrized over the whole file and the window from 50 to 450 µs. Two blocks have the
vector peak `hypot(A, A/2)`. Block 3 has it at 300 µs, and block 2 at 300 µs plus 1 fs (a block
whose last point is 1 fs after the end of the block). The test checks this order with
`block_gradient_values`, then checks that `gradient_peaks` credits block 3 at 300 µs, and that the
oracle gives the same.

**Assumptions:** pypulseq does not make a block longer for a point 1 fs after its end (it does for
1e-14 s). If that changes, the check of the order with `block_gradient_values` fails first.

#### `test_matches_oracle_on_synthetic_sequences`

**Checks:** `gradient_peaks` matches the oracle of the gradient waveform
(`tests/oracles/waveform.py`, section 2.15) on the whole file and on windows, for each of
`tests/synthetic.py`'s sequences (parametrized: `spin_echo_sequence`, `gre_sequence`,
`empty_sequence`, `arbitrary_gradient_sequence`, `border_sequence`, `raster_4us_sequence`).
`border_sequence` and `raster_4us_sequence` have a gradient that is not 0 at a block junction.

**How:** The windows are up to 12 windows from `_oracle_windows` (seed 20261007) and one window
from 0 to half of the total duration. For each window, `_assert_matches_oracle` compares every
field with `oracle.peaks(seq, window)`: the peak, the slew and the RMS of each axis within
`_rounding_tol`, the peak time and the vector peak time to 1e-12 s, the blocks (below) and the
vector peak. `_rounding_tol` is `1e-12 + 4 * eps * duration / shortest segment`, relative to
the value or to the limit of the same kind. The block of the peak of each axis is the oracle's,
with one exception (`_assert_same_credit`). `gre_sequence` repeats its readout, phase-encode and
spoiler events every TR, and the oracle adds the absolute block start to the corner times, so
its rounding can make it credit a later block that plays the same event. This package credits
the first block in play order. The test accepts a different block only when both blocks play
the same gradient event on that axis and the block of this package is the earlier one. The
block and the time of the slew are the oracle's, or those of another item of the polyline of
the oracle with the same slope (`_assert_slew_item`). The block of the vector peak is the
oracle's.

**Assumptions:**

- The user chose this tolerance on 2026-09-28. The oracle adds each block's absolute start time
  to an event's corner points before it takes a slope, so each corner time is rounded to about
  eps times the start time, and a slope divides the difference of two such times by the
  segment's duration. The package computes each event one time from its own offsets.
- The oracle gives Hz/m and Hz/m/s, so no value is converted.

#### `test_matches_oracle_on_the_sequences_of_the_oracle_tests`

**Checks:** `gradient_peaks` matches the oracle of the gradient waveform on the whole file and
on up to 40 windows, for each sequence of `tests/gap_sequences.py` (parametrized): the two
sequences of pypulseq-issues 12 (a first value after a delay, and an end before the end of its
block), a zero gap with a step, a short gap, a long gap, a first value and a last value that
are not 0, and one block with two axes.

**How:** The test loads each sequence (`load`). The windows come from `_oracle_windows`
(seed 20261007). Their ends are on the starts and the ends of the blocks, on the points of the
polylines of the oracle, half a raster time before and after those points, on multiples of
2.5 µs, at random, and within 1.5 ns of the start or the end of a block. A window shorter than
`TIME_TOLERANCE` is not made. For each window, `_assert_matches_oracle` compares each field with
`oracle.peaks(seq, window)`: the peak, the slew and the RMS of each axis within `_rounding_tol`,
the peak time and the vector peak time to 1e-12 s, the block of the peak of each axis, and the
block of the vector peak. The time and the block of the slew are those of the oracle, or those
of another item of the polyline with the same slope (`_assert_slew_item`).

**Assumptions:**

- The slope of the rise and the slope of the fall of a symmetric trapezoid are equal. The
  rounding of the times decides which one the oracle or the package finds first. The test
  accepts both. An item of the polyline of the oracle that has the largest slope is an accepted
  result.
- The test makes no window shorter than `TIME_TOLERANCE` (1 ns). The values of such a window
  are of a part of a segment that is shorter than the tolerance of a time.

#### `test_matches_oracle_on_random_gradient_sequences`

**Checks:** 50 random sequences of trapezoids, extended trapezoids and arbitrary gradients on
random axes, each event built so that it starts and ends at 0 (so no gap has a step, a line or
a ramp, and the values come from the events alone): `gradient_peaks` matches the oracle on the
whole file and on up to 6 windows.

**How:** For each of 50 seeds, the test builds a sequence of 2 to 6 blocks, each with 0 to 3
random axes, each a trapezoid, an extended trapezoid or an arbitrary gradient built with
pypulseq's `make_*` functions (so pypulseq's own limit checks apply) and an explicit `first`
and `last` of 0 where the function does not default to that. It compares the whole-file result
and the results of up to 6 windows from `_oracle_windows` with the oracle, as
`test_matches_oracle_on_synthetic_sequences` does.

**Assumptions:**

- `make_arbitrary_grad`'s `first` and `last` default to a linear extrapolation of the
  waveform's own edge samples, not to 0, so the random arbitrary-gradient builder passes
  `first=0.0, last=0.0` explicitly to keep every event zero-ended. This is a fact about
  pypulseq, not about the function under test, and is not itself checked here.

#### `test_matches_oracle_on_random_sequences_with_ends_that_are_not_zero_next_to_gaps`

**Checks:** 40 random sequences with events that start and end at values that are not 0 give
the values of the oracle, on the whole file and on up to 8 windows. This covers a step across a
zero gap, a line across a short gap, the ramps across a long gap, and a first value and a last
value of an axis that are not 0.

**How:** `random_gap_sequence` (`tests/random_gaps.py`) makes 2 to 8 blocks. Each of the three axes has an event for 55%
of the blocks. Each event is a trapezoid, an extended trapezoid or an arbitrary gradient, with a
delay of 0 to 7 raster times. The first value and the last value of an extended trapezoid and of
an arbitrary gradient are 0, or a random value of at most 0.9 of the largest step that
`add_block` accepts (at most 0.2 of it for an arbitrary gradient). A first value is also the
last value of the event before it for part of the calls, and it is within 0.9 of that step of
that value. A block has a delay event for 60% of the calls, which makes the block 1, 2 or 5
raster times longer than its events. A block with no event is a delay of 100 µs, 300 µs or 1 ms.
12% of the blocks are labels (a block of zero duration). A block that `add_block` refuses is not
added. The windows and the comparison are those of
`test_matches_oracle_on_the_sequences_of_the_oracle_tests`.

**Assumptions:** The seeds are fixed, so the sequences are the same in each run. The sequences
have gaps of each kind, but the test does not count them.

#### `test_block_gradient_values_agree_with_gradient_peaks_for_the_whole_file`

**Checks:** For each of 32 sequences (parametrized), the maxima of `block_gradient_values` over
the blocks are the whole-file values of `gradient_peaks`, with the same block and the same time.
For each axis, the maximum of `peak_hz_per_m` is `peak_hz_per_m` of the axis, and the first
block in play order with that maximum has the `peak_block` and the `peak_time_s`. The maximum
over the blocks of the larger of `slew_hz_per_m_per_s` and `junction_hz_per_m_per_s` is
`max_slew_hz_per_m_per_s`, and the first block with that maximum has the `slew_block`. Its time
is the time of the junction (`_junction_time`) when its junction has the maximum (the junction is
before every other item of its block), and otherwise the `slew_time_s` of the block. The maximum
of `vector_peak_hz_per_m` is `vector_peak_hz_per_m` of the result. The block with the earliest
`vector_peak_time_s` among the blocks with that maximum has the `vector_peak_block` and the
time. When the maximum is 0, `gradient_peaks` has no block (None).

**How:** The sequences are `spin_echo_sequence`, `gre_sequence`, `empty_sequence`,
`arbitrary_gradient_sequence`, `border_sequence`, `raster_4us_sequence`, `build_repeating(50)`
and `build_worst(50)` of `tests/scale_sequences.py`, five sequences of this file (a step between
two extended trapezoids, the same with a segment of the second block that has the same slew as
the step, a gradient that ends non-zero before a delay, a first block that starts non-zero, and
an x extended trapezoid with a delay and a first value that is not 0 after a trapezoid), the
seven sequences of `tests/gap_sequences.py`, 4 random sequences of `_random_gradient_sequence`
(seeds 0 to 3) and 8 random sequences of `random_gap_sequence` (seeds 0 to 7). For each
sequence the test calls `block_gradient_values` and `gradient_peaks` and compares them with
`==`, not `pytest.approx`. `_junction_time` reads the first point of the event of the credited
block with `get_block`. For a line across a short gap, it reads the last point of the event
before it, with `gradient_offsets`.

**Assumptions:**

- Exact equality holds because both functions use the same arithmetic on the same values of
  each block: the columns of `_BlockData`.
- The 4 random sequences of `_random_gradient_sequence` have no gap with a value that is not 0
  (every event starts and ends at 0), so their junctions are 0. The 8 sequences of
  `random_gap_sequence` have steps, lines and ramps.
- The test does not compare a window: `block_gradient_values` has no window.

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
trapezoids with a step between them, followed by a delay, block 1 and block 3 have a junction of
0 and block 2 has the step divided by the raster. A gradient that ends at a non-zero value before
a delay has no junction in the delay block, because the junction of a block with no event on the
axis is 0. The step to 0 is in the slew of the block of the gradient.

**How:** The test builds the two sequences. It compares `junction_hz_per_m_per_s["x"]` with the
hand-computed value (`pytest.approx`) and with 0 (exact). For the second sequence, the junction
of both blocks is 0, the slew of block 1 is the ending value divided by the raster, its time is
200 µs, and the slew of the delay block is 0.

**Assumptions:** None.

#### `test_block_gradient_values_are_in_play_order_with_one_entry_for_each_block`

**Checks:** Each array has one entry for each block, `block_id` and `start_s` equal the arrays of
`sequence_index(snap)` (play order), the five dicts have the keys x, y and z, and the arrays are of
type float64 (`block_id` aside).

**How:** The test calls `block_gradient_values` on `gre_sequence(num_trs=3)`, compares `block_id`
and `start_s` with `assert_array_equal`, and checks the shape and the dtype of each of the 17
float arrays and that `start_s` increases.

**Assumptions:** None.

#### `test_gradient_peaks_of_two_equal_computations_are_equal_and_not_hashable`

**Checks:** Two `GradientPeaks` of two separate computations of the same values are equal by
value, a result with another value in a field is unequal, and a result is not hashable.

**How:** The test calls `gradient_peaks(snap, window=(0.0, 1e-3))` two times on the spin echo (a
window is not kept): two objects, `==` true. Two calls without a window on two snapshots of separately built
spin echo sequences are `==`. A `dataclasses.replace` with another `vector_peak_hz_per_m` and the
result for the window `(0.0, 2e-3)` are `!=`. `hash(first)` is in `pytest.raises(TypeError)`.

**Assumptions:** None.

#### `test_axis_result_stays_hashable`

**Checks:** An `AxisResult` has the `==` and the hash of `dataclasses`: `hash` works, and a copy
with the same fields has the same hash.

**How:** `hash` of an `AxisResult` of the spin echo equals `hash` of its `dataclasses.replace`
copy.

**Assumptions:** None.

#### `test_block_gradient_values_of_two_equal_sequences_are_equal_and_not_hashable`

**Checks:** Two `BlockGradientValues` of two equal sequences are equal by value, another sequence
gives an unequal result, and a result is not hashable.

**How:** The test calls `block_gradient_values(gre_sequence())` two times: two objects, `==`
true. The results for `gre_sequence(num_trs=5)` and for the spin echo are `!=`.
`hash(result)` is in `pytest.raises(TypeError)`.

**Assumptions:** None.

#### `test_the_arrays_of_block_gradient_values_are_read_only_and_not_views_of_the_index`

**Checks:** All 19 arrays of a `BlockGradientValues` (`block_id`, `start_s`, the vector peak and its
time, and the 3 axes of each of the 5 dicts) are read-only, a copy is writable, and each
array is its own: none shares memory with the kept `SequenceIndex` or with another array.

**How:** For each array, a write of item 0 raises `ValueError` ("read-only"),
`np.shares_memory` with `index.block_id` and `index.start_s` is False, `np.array(array)` is
writable, and `np.shares_memory` is False for each pair of arrays.

**Assumptions:** None.

#### `test_the_dicts_of_block_gradient_values_are_frozen_dicts_that_refuse_a_change`

**Checks:** Each of the five dicts of a `BlockGradientValues` is a `FrozenDict` with the keys x, y and
z that refuses a change.

**How:** For each dict: `isinstance(d, FrozenDict)`, the keys are x, y and z, and `d["x"] = ...`,
`del d["x"]` and `d.update(...)` each raise `TypeError`, and the keys are the same after.

**Assumptions:** None.

#### `test_the_axes_of_gradient_peaks_are_a_frozen_dict_that_refuses_a_change`

**Checks:** `GradientPeaks.axes` is a `FrozenDict` with the keys `x`, `y` and `z`, and refuses
a change.

**How:** Parametrized with no window and with the window `(0.0, 1e-3)` on the spin echo. A set
item and `clear` on `axes` raise `TypeError`.

**Assumptions:** None.

#### `test_the_reason_of_a_sequence_with_no_gradient_is_no_gradients`

**Checks:** The `reason` of a sequence with no gradient is `seq_index.NO_GRADIENTS`, and its `axes`
is a `FrozenDict`.

**How:** The test loads a `pp.Sequence(SYSTEM)` with no blocks and checks
`gradient_peaks(snap).reason == NO_GRADIENTS`. A sequence with one delay block is in
`test_no_gradients_sets_reason`.

**Assumptions:** None.

#### `test_the_reason_of_a_window_with_no_gradient_is_no_gradients_in_the_window`

**Checks:** For a sequence with gradients, a window that holds none has the `reason`
`seq_index.NO_GRADIENTS_IN_WINDOW`, and the whole sequence has `reason` None.

**How:** The test takes the spin echo, checks that block 0 (the RF block) has no gradient event,
and calls `gradient_peaks` with the window from 0 to half the duration of block 0.

**Assumptions:** None.
#### `test_gradient_peaks_refuses_a_window_with_no_start_before_its_end`

**Checks:** `gradient_peaks` raises `ValueError` for a `window` whose start is not
before its end.

**How:** The synthetic spin echo, with two cases: a start equal to the end, and a start
after the end. Each call is in
`pytest.raises(ValueError, match="must have a start before its end")`. The test replaces
`grad_peaks.sequence_index` and `grad_peaks._event_values` (`monkeypatch`) with functions that
fail the test, so it also checks that the error comes before the sequence is read.

**Assumptions:** None.

#### `test_gradient_peaks_refuses_a_window_outside_the_sequence`

**Checks:** `gradient_peaks` raises `ValueError` for a `window` that is outside the
sequence by more than `TIME_TOLERANCE`.

**How:** The synthetic spin echo, with two cases: a start of `-2 * TIME_TOLERANCE`, and
an end of `total_duration + 2 * TIME_TOLERANCE`. Each call is in
`pytest.raises(ValueError, match="is not within the sequence")`. The test replaces
`grad_peaks._event_values` (`monkeypatch`) with a function that fails the test, so it also
checks that the error comes before the events are read. It does not replace `sequence_index`,
because the check needs the length of the sequence.

**Assumptions:** None.


#### `test_gradient_peaks_refuses_a_window_with_an_end_that_is_not_finite`

**Checks:** `gradient_peaks` raises `ValueError` for a window with a start or an end that is NaN or an
infinity, before the rules of the order and of the range.

**How:** The synthetic spin echo, with four cases: a NaN start, a NaN end, an infinite end and a
start of minus infinity. Each call is in `pytest.raises(ValueError, match="finite")`. The test
replaces `grad_peaks.sequence_index` and `grad_peaks._event_values` (`monkeypatch`) with
functions that fail the test, so it also checks that the error comes before the sequence is read.

**Assumptions:** None.

#### `test_gradient_peaks_refuses_a_window_end_that_is_not_a_real_number`

**Checks:** `gradient_peaks` raises `TypeError` for a window with a start or an end that is a `bool`,
a string or None.

**How:** The spin echo, with six cases (a `bool`, a `str` and `None`, each as the start and as the
end), in `pytest.raises(TypeError, match="window (start|end)")`. The test replaces
`grad_peaks.sequence_index` and `grad_peaks._event_values` (`monkeypatch`) with functions that
fail the test, so it also checks that the error comes before the sequence is read.

**Assumptions:** None.

#### `test_gradient_peaks_refuses_a_window_that_is_not_a_pair`

**Checks:** `gradient_peaks` raises `TypeError` for a window that is not a tuple or a list of two
items.

**How:** The spin echo, with six cases: 3 items, 1 item, no items, a number, a string and a set.
Each call is in `pytest.raises(TypeError, match="must be a pair")`. The test replaces
`grad_peaks.sequence_index` and `grad_peaks._event_values` (`monkeypatch`) with functions that
fail the test, so it also checks that the error comes before the sequence is read.

**Assumptions:** None.

#### `test_gradient_peaks_takes_a_window_as_a_list_or_with_numpy_scalars`

**Checks:** A window as a list, with an `int`, or with numpy scalars gives the result of the same
window as a tuple of floats.

**How:** The spin echo; the expected result is that of `(0.0, total / 2)`. The results for
`[0.0, total / 2]`, `(0, np.float64(...))` and `(np.int64(0), np.float64(...))` are
`==` to it.

**Assumptions:** None.
#### `test_gradient_peaks_accepts_a_window_within_the_tolerance_of_the_sequence`

**Checks:** `gradient_peaks` accepts a `window` that is outside the sequence by less
than `TIME_TOLERANCE`, and `range_s` is the sequence.

**How:** The synthetic spin echo and the window
`(-TIME_TOLERANCE / 2, total_duration + TIME_TOLERANCE / 2)`. The call does not raise,
and `range_s` equals `(0.0, total_duration)`.

**Assumptions:** None.

#### `test_a_window_outside_the_sequence_within_the_tolerance_gives_an_empty_range`

**Checks:** A window that is past the end of the sequence, or before 0, by less than
`TIME_TOLERANCE` is accepted. Its `range_s` is the range of length 0 at that end, `(T, T)` or
`(0.0, 0.0)`, and not a range with its start after its end. The result has the `reason`
`seq_index.NO_GRADIENTS_IN_WINDOW` and the zero values.

**How:** The synthetic spin echo, with two cases: the window `(T + 5e-10, T + 9e-10)` and the
window `(-9e-10, -5e-10)`, for `T` the length of the sequence. The test checks `range_s` with `==`,
the `reason`, the vector peak and its block, and each `AxisResult` against all zero values.

**Assumptions:** `TIME_TOLERANCE` is 1e-9, so both windows pass the check of the range.

#### `test_a_window_gives_the_same_result_with_and_without_the_kept_data`

**Checks:** For a window, `gradient_peaks` of a snapshot that has its kept data (the per-event
values and the values over the blocks: the end of each block, the junction and its time, the
ramps, the extent in time of each block, and the RMS of the whole file) gives a result equal
(`==`) to the result of the same call on a snapshot whose kept data is empty. The kept values
over the blocks and the search of the block range (`np.searchsorted`) do not change a result,
also for a window edge on a block edge, and for a block of zero duration at a window edge or
inside the window.

**How:** For six sequences (`build_repeating(30)`, a sequence of trapezoids with blocks of zero
duration before, between and after them, the junction sequence, the delayed junction sequence,
one random gradient sequence and one random sequence of `random_gap_sequence`), 30 windows
with the seed 20261006: the ends of every other window are each the start or the end of a block
(or 0 or the end of the sequence), and the ends of the others are random. The test makes a
snapshot `snap` of one build. It never empties the kept data of `snap`, so each window uses the
kept data that the windows before it built. For each window, it makes a new snapshot of the same
sequence, so that the call on it builds its own kept data, and checks that the result for `snap`
equals the result for the new snapshot. It also checks that the kept values over the blocks
(`_kept_results(snap)["block_data"]`) are one object for all the windows, so the kept data is
really reused.

**Assumptions:** The test does not compare with a second implementation of the window: the
values themselves are checked by the hand-computed tests and by the comparisons with the oracle
above. A window with an end that is not within the sequence is not used. The test reads the
private kept dict of the snapshot (`snapshot._kept_results`). The two snapshots are of one
sequence, so they have equal events and blocks. A result that uses the kept data of another
window, for example a range that the first window kept, is not equal to the result of a call with
empty kept data.

#### `test_a_window_does_not_calculate_the_values_over_all_the_blocks_again`

**Checks:** In `build_repeating(1000)` (5000 blocks), after a first call has built the kept
data, `gradient_peaks` with a window of four TRs calculates no column of a block and no vector peak
of a block again. This holds for a window with its ends inside
blocks and for a window with its ends on block edges.

**How:** After a first call with another window, the test replaces `_axis_columns` and
`_exact_vector_peaks` of `grad_peaks` with functions that fail. The window
is from play index 2503 to 2507, with its start a third of the way into block 2503 and its end
half way into block 2507, or from the start of block 2500 to the start of block 2510. The test
calls `gradient_peaks` with the window and checks that the result has gradients.

**Assumptions:** The test cannot measure the time: a loop over all the blocks in numpy is fast.
The failing functions are the ones that calculate a value over all the blocks. The test needs the
two names. It does not check the values of the result.

#### `test_a_window_of_gradient_peaks_calls_no_get_block`

**Checks:** In `build_repeating(1000)` (5000 blocks), after a first call has built the kept data,
`gradient_peaks` with a window of four TRs calls `Sequence.get_block` for no block. This holds for
a window with its ends inside blocks (two blocks are cut, one for each end) and for a window with
its ends on block edges (no block is cut).

**How:** After a first call with another window, the test finds from the index the blocks with a
start before a window end and an end after it, and checks that there are two of them for the first
window and none for the second. It then wraps `pp.Sequence.get_block` to record the block ID of
each call, calls `gradient_peaks` with the window, and checks that the result has gradients and
that no block was read.

**Assumptions:** The window is from play index 2503 to 2507, with its start a third of the way into
block 2503 and its end half way into block 2507, or from the start of block 2500 to the start of
block 2510. The wrap sees only the calls of `Sequence.get_block` on the class. The test does not
check the values of the result: the other tests of `gradient_peaks` compare them with the oracle.

#### `test_the_values_of_each_sequence_of_pypulseq_issue_12_are_those_of_matlab_pulseq`

**Checks:** The two sequences of pypulseq-issues 12 (parametrized) have the gradient of MATLAB
Pulseq, with the values by hand. The gradient is at 0, 100, 200, 205, 295, 300 and 400 µs the
values 0, A, A, 0, 0, A and 0, where A is half of `max_slew * grad_raster_time`.

**How:** For the whole file, the test checks the peak A at 100 µs in block 1, the slew
`max_slew` (a ramp of A in half a raster time), the RMS (A times sqrt(170 / 400)), and the
vector peak A at 100 µs in block 1. The slew is at 200 µs in block 1 or at 295 µs in block 2. y
and z have no block. For the values of each block, it checks the peak A, the slew `max_slew`,
the junction 0 (a long gap has ramps and no junction), and the vector peak A of both blocks. The
time of the vector peak of block 2 is 200 µs for the first sequence and 300 µs for the second.

**Assumptions:** The two ramps have one slope up to the rounding of the times, so the test
accepts the ramp to 0 or the ramp from 0 as the slew. The vector peak of block 2 is the value at
the first time on the side of block 2. Block 2 starts at 200 µs in the first sequence, where the
ramp to 0 starts. In the second sequence, the value after 300 µs is in block 2.

#### `test_a_zero_gap_with_two_different_values_gives_a_step_credited_to_the_later_block`

**Checks:** Two blocks that meet at a block edge with different values give a step. The step is
credited to the later block.

**How:** Block 1 goes from 0 through U to 2 U in 200 µs. Block 2 goes from U to 0 in 100 µs. U
is 1e4 Hz/m. The step is -U at 200 µs. The test checks, for the whole file, the peak 2 U at
200 µs in block 1, the slew U / DT at 200 µs in block 2, and the RMS U. It checks the junction of
each block (0 and U / DT) and the slew of each block (U / 100 µs).

**Assumptions:** A zero gap gives the same step as before the model of the gradient waveform
(decision D4 of `docs/plans/third-review-fixes.md`).

#### `test_a_window_has_the_step_at_its_start_and_not_the_step_at_its_end`

**Checks:** A window has a step when the time of the step is at its start or inside it. It does
not have a step at its end. A point on the other side of an edge is not in the window.

**How:** The sequence is the one of the test above. For the windows 150 to 250 µs, 100 to
200 µs and 200 to 300 µs, the test checks the peak, the slew, their times and blocks, and the
RMS, with the hand values. The first window has the step (slew U / DT in block 2, RMS
U sqrt(11 / 6)). The second window ends at the step and has the slope of the rise (U / 100 µs in
block 1, RMS U sqrt(7 / 3)). The third window starts at the step and has it (peak U in block 2,
RMS U / sqrt(3)).

**Assumptions:** The rule is `lo <= time < hi`.

#### `test_a_window_that_ends_at_a_step_up_does_not_have_the_value_after_the_step`

**Checks:** A window that ends at a step up does not have the value after the step: the vector
peak, the peak and the slew are those of the window before the step. A window that goes on past the
step has the value after it and the slew of the step.

**How:** Block 1 on x goes from 0 to U and stays at U to its end at 200 µs. Block 2 starts at 3U,
a step of 2U at 200 µs. The window from 100 to 200 µs has the vector peak U at 100 µs in block 1,
the x peak U, the slew 0 and the RMS U (hand values), and the oracle gives the same vector peak.
The window from 100 to 250 µs has the vector peak 3U at 200 µs in block 2, and the slew 2U/DT of
the step.

**Assumptions:** None.

#### `test_a_window_credits_the_segment_before_a_step_of_the_same_slew`

**Checks:** In a window, a segment of an earlier event and a step into a later event with the same
slew credit the segment, which is first in play order.

**How:** Block 1 is a trapezoid of U with a rise and a fall of 10 µs and no flat. Block 2 starts at
U, a step of U at 20 µs. The fall of block 1 and the step both have the slew U/DT, equal in floating
point. The window from 12 to 60 µs gives the slew U/DT in block 1 at 12 µs (the start of the cut),
and the peak U at 20 µs in block 2.

**Assumptions:** The single-line mutation of the order key of `_evaluate_axis` that the review of
2026-10-07 lists (`step_point - 0.5` to `step_point + 0.5`) cannot change a result: the segment
between the two keys is the step itself, which has no slope. This test fails for `- 1.5`, which
puts the step before the last segment of the earlier event.

#### `test_a_short_gap_gives_a_line_credited_to_the_later_block`

**Checks:** A gap of one raster time with ends that are not 0 is a line, not two ramps. The line
is credited to the later block.

**How:** The first gradient goes from 0 to 3 U in 100 µs. Its block lasts 110 µs. The second
block goes from 2 U to 0 in 100 µs. The line goes from 3 U at 100 µs to 2 U at 110 µs. Its slope
is U / DT. For the whole file, the test checks the peak 3 U at 100 µs in block 1, the slew
U / DT at 100 µs in block 2, and the RMS (U sqrt(149 / 63)). It checks the junction of each
block (0 and U / DT), the slew of each block (3 U / 100 µs and 2 U / 100 µs), and the peak and
its time of each block. The window from 105 µs to 150 µs has half of the line and 40 µs of
block 2. The peak is 2.5 U at 105 µs in block 2, and the slew is U / DT at 105 µs in block 2.
The vector peak has the same value and time, in block 1, the block that has 105 µs.

**Assumptions:** None.

#### `test_a_long_gap_gives_the_ramps_of_its_ends_credited_to_the_blocks_of_their_events`

**Checks:** A gap of more than one raster time with ends that are not 0 has a ramp to 0 after
the earlier event and a ramp from 0 before the later event. The ramp to 0 is credited to the
earlier block and the ramp from 0 to the later block. The gradient in the gap is 0.

**How:** Block 1 goes from 0 to 3 U in 100 µs. Block 2 is a delay of 200 µs. Block 3 goes from
2 U to 0 in 100 µs. For the whole file, the test checks the peak 3 U at 100 µs in block 1, the
slew 3 U / 5 µs at 100 µs in block 1, and the RMS (U sqrt(455 / 400)). For the blocks, it checks
the junction 0, the slew (6e9, 0 and 4e9 with the start times 100, 100 and 295 µs) and the
vector peak (3 U, 3 U and 2 U with the times 100, 100 and 300 µs). Block 2 starts at 100 µs,
where the ramp to 0 starts. The window from 150 to 250 µs is in the gap: `reason` is
`seq_index.NO_GRADIENTS_IN_WINDOW`, and all the values are 0 with no block. The window from
102.5 to 150 µs has half of the ramp to 0. The peak 1.5 U and the slew 6e9 are each at 102.5 µs
in block 1, and the vector peak is in block 2.

**Assumptions:** None.

#### `test_a_first_value_and_a_last_value_that_are_not_zero_are_steps_at_the_ends_of_the_axis`

**Checks:** A first value of an axis that is not 0 and a last value that is not 0 each give a
step. The step at the end of the sequence is not in the whole file.

**How:** Block 1 goes from 3 U to 0 in 100 µs. Block 2 goes from 0 to 2 U in 100 µs. For the
whole file, the test checks the peak 3 U at 0 in block 1, the slew 3 U / DT at 0 in block 1, and
the RMS (U sqrt(13 / 6)). The junction of the blocks is 3 U / DT and 0. The slew of block 2 is
2 U / 100 µs, because its step at 200 µs, the end, is not counted. The window from 100 to 200 µs
has neither step. The window from 50 to 200 µs cuts the first segment, and its slew is
3 U / 100 µs from 50 µs in block 1.

**Assumptions:** The step after the last point is at the end of the sequence. A step counts for
`lo <= time < hi`, so a window that ends at the end of the sequence does not have it, and the
whole file does not have it.

#### `test_the_vector_peak_of_one_block_with_two_axes_is_at_a_point_of_one_axis`

**Checks:** The vector peak is at the union of the times of the points of the axes.

**How:** One block of 400 µs has an x trapezoid of 3 U (rise 100 µs, flat 200 µs) and a y
triangle of 4 U with its top at 150 µs. The vector peak is 5 U at 150 µs, the time of a point of
y only, in the block. The window from 160 to 400 µs has its largest vector at the start:
hypot(3 U, 3.84 U) at 160 µs.

**Assumptions:** None.

#### `test_a_window_edge_next_to_a_block_edge_credits_the_vector_peak_by_time`

**Checks:** The vector peak is credited to the block that has its time within `TIME_TOLERANCE`,
seen from the side where the value is. The peak of an axis is credited to the block of its
segment. These can be two blocks.

**How:** In `raster_4us_sequence`, block 1 has the y gradient at its top (16 mT/m) until 800 µs,
and block 2 starts with a step down to 15.76 mT/m. The window that starts 1 ps before the start
of block 2 has the top at its start. The y peak is in block 1 (the segment that the window cuts),
and the vector peak is in block 2 (it starts 1 ps after the window start), at the window start.
The window that starts 1 ps after the start of block 2 has 15.76 mT/m for the y peak and the
vector peak, in block 2.

**Assumptions:** 1 ps is less than `TIME_TOLERANCE`, so the start of the window and the start of
block 2 are one time for the credit of the vector peak.

#### `test_the_gap_rule_uses_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The gap rule (zero, short, long) and the ramps use `seq.grad_raster_time` (the
`GradientRasterTime` of the file), not the raster of `seq.system`.

**How:** With a 4 µs gradient raster, the test builds an x gradient from 0 to V in 400 µs in a
block of 410 µs, and an x gradient from W to 0 in 400 µs in the second block. The gap is 10 µs,
which is more than one raster time of 4 µs. It is a long gap: the slope of the ramp to 0 is
V / 2 µs, the slope of the ramp from 0 is W / 2 µs, and the junction of block 2 is 0. (With
10 µs, it would be a short gap, with a line and a junction.) The test writes the sequence to a
file in `tmp_path` and reads it with `pp.Sequence()`, which has 10 µs in `seq.system`. For the
sequence that was read and for the sequence object, it checks the junction, the slews and their
times, and `gradient_peaks` on two windows against the oracle.

**Assumptions:** The file stores the amplitudes with fewer digits, so the slews have a relative
tolerance of 1e-4.

#### `test_block_gradient_values_are_the_items_of_the_polyline_that_each_block_has`

**Checks:** For each axis and each block, the peak, the junction and the slew of
`block_gradient_values` are the values of the items that the credit of the model gives to the
block, found in the polyline of the oracle.

**How:** For 25 sequences (parametrized: `spin_echo_sequence`, `gre_sequence`,
`border_sequence`, `raster_4us_sequence`, the seven sequences of `tests/gap_sequences.py`, and
14 sequences of `random_gap_sequence`), `_block_values_of_the_polyline` reads the polyline of
the oracle and gives each item to its play index. A point gives the peak. A segment from a point
of one block to a point of another block, and a step that is not after the last point, give the
junction. The other segments, and the step after the last point (when its time is before the end
of the sequence), give the slew. The test compares the peak (and its time where it is above 0),
the junction and the slew of each block with the values of the package
(`numpy.testing.assert_allclose`, 1e-12 for the peak and 1e-9 for the junction and the slew).
The time of the slew of a block must be the time of one of its items that have the largest
slope.

**Assumptions:** The slopes of two items of one block can be equal up to the rounding of the
times, so the test accepts the time of each item that has the largest slope. The test does not
compare the time of a slew of 0.

#### `test_a_measurement_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `gradient_peaks` and `block_gradient_values` raise `TypeError` with a message
that names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over the two functions and over `gre_sequence()` and the path string
`"sequence.seq"`. Each call must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

#### `test_gradient_peaks_refuses_a_bad_window_before_the_snapshot_type`

**Checks:** A bad `window` raises its own error before the type of the first argument is
checked: a window with its start equal to its end and a window with a non-finite end raise
`ValueError`, and a window that is not a pair raises `TypeError`.

**How:** Parametrized over `(0.5, 0.5)`, `(0.0, inf)` and `[0.0]`. The call
`gradient_peaks(gre_sequence(), window=window)` has a `pp.Sequence` as its first argument,
which is not a snapshot and would raise the `TypeError` that names `load`. The error must be
the one of the window (`match` "start before its end", "window end" and "window").

**Assumptions:** The checks of the window that need the sequence (a window outside it) come
after the type check, and are tested with a snapshot above.

### 2.7 The kept PNS levels (`test_pns_levels_kept.py`)

`test_pns_levels_kept.py` tests the keep of `pns_levels.pns_levels`, the one public function
of the SAFE model. It gives the `PnsLevels` of a
sequence: the summary fields (`reason`, `hardware`, `peak_hz_per_t`,
`peak_time_s`, `axis_peaks_hz_per_t`) and the level. The SAFE model itself
(`pns_levels._compute_levels`, the chunked SAFE recursion of `safe.py`) runs on a
result that is not kept; a test that counts the runs of the model replaces `_compute_levels`
of `pulseq_analysis.pns_levels` with a wrapper that counts its calls.
`pns_levels` keeps one `PnsLevels` for each (snapshot, hardware, thresholds, `bin_s`),
the hardware being a pair `(struct, label)` (its key is the label and the 24 values of
the struct without `stim_thresh`, so two pairs with the same label and values are one
hardware, whatever their structs are or where they came from), so that a caller that needs
the PNS of one sequence more than once runs the SAFE model once. A snapshot never changes, so a kept result is
never old (section 2.12). Each test makes its snapshot with `snapshot.load`. The thresholds of the key are the tuple of
`float(t)`, so an `int` threshold and the equal `float` are one key, and the default `()`
is its own key. A PNS value is in Hz/T (the fraction of the stimulation limit times the
magnitude of gamma). The test file defines `_LIMIT = GAMMA_1H`, the stimulation limit for
1H in Hz/T (a fraction of 1 times `GAMMA_1H`). The `hardware` pair is necessary: without
it, `pns_levels` raises `TypeError`. The tests give pypulseq's example hardware, which is not a real scanner, as the pair `EXAMPLE_HW` of
`tests/synthetic.py`.

The real `.asc` files are confidential, so the tests write a test `.asc` file
with the PNS parameters of pypulseq's example hardware, with the
`write_gradient_asc` fixture of `tests/conftest.py`. The stimulation limits
and thresholds in it can be multiplied by a scale factor. The test file can
also have the layout of a scanner file: a main file with an `ASCCONV` block,
CRLF line ends and the name in `asCOMP[0].tName`, which includes a
`_GSWD_SAFETY.asc` file with the PNS parameters under `GradPatSup.Phys.PNS`. The
tests give the hardware of such a file as `hardware_from_asc(path)` of
`pulseq_analysis.asc`.

Most of the tests use the synthetic spin echo sequence
(`tests/synthetic.py`'s `spin_echo_sequence`).

**Assumptions for the whole file:**

- pypulseq's SAFE model is correct. No test compares it with a published
  result or with a scanner.
- No test uses the parameters of a real scanner. A PNS value for the
  synthetic sequences on the scanner is not tested.

#### `test_prediction_scales_with_the_stimulation_limit`

**Checks:** A stimulation limit 10 times lower gives a peak 10 times
higher, above the limit.

**How:** The test writes a test `.asc` file with scale factor 0.1 and calls
`pns_levels`. The peak must be 10 times the example hardware peak within a
relative 10⁻⁹, and more than `_LIMIT`.

**Assumptions:**

- In the SAFE model, the result is inversely proportional to the
  stimulation limit.

#### `test_no_gradients_with_rf_and_adc`

**Checks:** A sequence with RF and ADC events but no gradient events has no PNS
result, with the reason "no gradients".

**How:** The test makes a sequence with a block pulse block and an ADC block,
and checks the reason.

**Assumptions:**

- `pns_levels` finds "no gradients" from the gradient columns of
  `seq.block_events`. This test and `test_no_gradients` check that other
  events do not count as gradients.

#### `test_prediction_does_not_build_the_gradients_for_an_on_raster_sequence`

**Checks:** `pns_levels` never calls `seq.get_gradients()` for an on-raster sequence.

**How:** The test replaces `get_gradients` of a synthetic spin echo sequence with a
wrapper that counts the calls, and calls `pns_levels`. There must be no calls.

**Assumptions:**

- `_compute_levels` samples an on-raster sequence with
  `GradientSampler.block_samples`, not `seq.get_gradients()`/`seq.calculate_pns` (that
  was the old, now-removed, implementation, which is why the old test expected exactly
  one call). `test_pns_levels.py` and `test_sampling.py` test `block_samples` and its
  agreement with `sample` and the oracle directly; this test only checks that the
  fast path is actually taken from `pns_levels`.

#### `test_pns_levels_keeps_one_result_for_equal_hardware_pairs`

**Checks:** Two `hardware` pairs with the same label and the same field values, with two
different struct objects, are one hardware: the second call runs no model and gives the
kept result.

**How:** The test counts the calls of `_compute_levels` as above and calls `pns_levels(snap,
hardware=(safe_example_hw(), "LABEL"))` two times, each with a new struct. It checks
that there was 1 call and that the second result `is` the first.

**Assumptions:** None.

#### `test_pns_levels_computes_again_for_another_label_or_value`

**Checks:** A `hardware` pair with another label, or with one other field value, runs
the model; going back to an earlier pair does not run it again.

**How:** The test counts the calls of `_compute_levels` as above and calls with the pairs a, a, b (the
label "B"), c (`z.stim_limit` plus 1), a, c, each with a new struct where the values are
the same. It checks the call count after each change: 1, 1, 2, 3, 3.

**Assumptions:** None.

#### `test_pns_levels_keys_the_hardware_on_each_field_of_each_axis`

**Checks:** Each field of the key of a hardware (`_HW_FIELDS`, on each axis) is in the key: a pair
with the same label and one field of one axis changed runs the model, and the unchanged pair still
gives its kept result.

**How:** Parametrized over the 8 fields of `_HW_FIELDS` and the axes x, y and z (24 cases). The
test changes one field of one axis of `safe_example_hw()`: `a1`, `a2` or `a3` by 0.0005, so the sum
stays within the tolerance of 1, and each other field to 1.1 times its value. It checks that the
result of the changed pair is not the kept result of the unchanged pair, and that the unchanged pair
then gives its kept object again.

**Assumptions:** None.

#### `test_pns_levels_ignores_stim_thresh_in_the_hardware_key`

**Checks:** Two `hardware` pairs with the same label that differ only in `stim_thresh`
are one hardware.

**How:** The test counts the calls of `_compute_levels` as above. It calls `pns_levels` with
a pair and with a second pair where `z.stim_thresh` is 1 higher, both with the label "A". It
checks that there was 1 call and that the second result `is` the first.

**Assumptions:** The model does not use `stim_thresh`, and `PnsLevels.hw` does not keep it.

#### `test_pns_levels_keeps_one_result_for_a_safe_hardware_and_its_namespace`

**Checks:** A `SafeHardware` and the namespace with the same values, with the same label, are
one hardware: the second call gives the kept result. The same values with another label are
another hardware.

**How:** The test counts the calls of `_compute_levels` as above. It calls `pns_levels` with
`(safe_example_hw(), "A")`, then with `(SafeHardware.from_namespace(safe_example_hw()), "A")`,
and checks that the second result is the first (`is`) and that there was 1 call. It then calls
with the `SafeHardware` and the label "B" and checks that the result is not the first and that
there were 2 calls.

**Assumptions:** None.

#### `test_pns_levels_keys_a_hardware_from_an_asc_file_by_its_label_and_values`

**Checks:** The key of a pair from a file is its label and its values, as for any pair:
the pair of `hardware_from_asc`, a second call of `hardware_from_asc`, and a pair made by
hand from the same file are one hardware; the same values with another label are another
hardware, and `EXAMPLE_HW` (the same values, another label) is a third. Each runs the
model one time.

**How:** The test counts the calls of `_compute_levels` as above, calls `pns_levels` with the pair
of the file, and then two times with `hardware_from_asc(path)` and with
`(asc_to_hw(asc), hardware_name(asc))`; each result must be the first one (`is`) and the
call count 1. It then calls two times the pair `(struct of the file, "OTHER")` and
`EXAMPLE_HW`, and checks that there were 3 calls.

**Assumptions:** None.

#### `test_pns_levels_needs_hardware`

**Checks:** `pns_levels` without `hardware` raises `TypeError` (the message names
`hardware`), also for a first argument that is not a snapshot: the arguments are checked first.

**How:** The test calls `pns_levels(spin_echo_sequence())` in
`pytest.raises(TypeError, match="hardware")`.

**Assumptions:** None.

#### `test_pns_levels_refuses_a_bad_struct_for_a_sequence_without_gradients`

**Checks:** The bad structs of the test above raise the same errors, with the same
messages, for a sequence with no gradient event, which gives a `NO_GRADIENTS` result for
a good struct.

**How:** Parametrized on `BAD_STRUCTS`. The test calls
`pns_levels(empty_sequence(), hardware=(struct, "BAD"))` in
`pytest.raises(error, match=match)`, with the real sequence.

**Assumptions:** None.

#### `test_pns_levels_refuses_a_sum_of_the_a_fields_below_1_for_a_sequence_without_gradients`

**Checks:** A struct whose `x.a1 + x.a2 + x.a3` is 0.9 raises `ValueError` (the message
names `x.a1 + x.a2 + x.a3 must be 1`) for a sequence with no gradient event. The check is
of the distance from 1, not of the signed difference.

**How:** `safe_example_hw()` with `x.a1` lowered by 0.1. The test checks that the sum is
about 0.9, then calls `pns_levels(empty_sequence(), hardware=(struct, "BAD"))` inside
`pytest.raises`.

**Assumptions:** None.

#### `test_pns_levels_refuses_a_sum_of_the_a_fields_that_is_1_005`

**Checks:** A struct whose `a1 + a2 + a3` is 1.005 on one axis raises `ValueError` that names that
axis, for a sequence with no gradient event. 1.005 is outside the tolerance of 0.001, and inside a
tolerance of 0.01.

**How:** Parametrized over the axes x, y and z. `safe_example_hw()` with `a1` of that axis raised
until the sum is 1.005, then `pns_levels(empty_sequence(), hardware=(struct, "BAD"))` inside
`pytest.raises`.

**Assumptions:** None.

#### `test_pns_levels_keeps_one_result_for_each_tuple_of_thresholds`

**Checks:** The thresholds are part of the key of a kept result: other thresholds, or
the same ones in another order, run the model and do not give the result of the default
(no threshold, the key `()`); the same thresholds again give the kept result (the same
object); an `int` threshold is the key of the equal `float`.

**How:** The test counts the calls of `_compute_levels` as above and calls `pns_levels(snap)`, then
`thresholds_hz_per_t=(_LIMIT, 0.5 * _LIMIT)`, again the same, the default again, `()`,
`(round(_LIMIT), 0.5 * _LIMIT)` (an `int` that equals `_LIMIT` as a float, which the test
checks), and the two thresholds in the other order. It checks that the call count is 1
after the default, 2 after the two thresholds and still 2 after the repeats, the call with
`()` and the call with the `int`, and 3 after the other order. It also checks that the
second result is not the first, that the repeated results are the same objects as the kept
ones (the `int` call gives the second result), and that `list(result.above)` is `[]`,
`[_LIMIT, 0.5 * _LIMIT]` and `[0.5 * _LIMIT, _LIMIT]`.

**Assumptions:** None.

#### `test_pns_levels_keeps_one_result_for_each_bin_s`

**Checks:** `bin_s` is part of the key of a kept result: another `bin_s` runs the model and
does not give the result of the default; the same `bin_s` again gives the kept result (the
same object); the default and `bin_s=BIN_S` are one key; an `int` `bin_s` and the equal
`float` are one key; the same `bin_s` with thresholds is another result. The bins of each
result are those of its `bin_s` (`bin_samples` 500 for the default and 600 for `0.006` at
the 10 us raster).

**How:** The test counts the calls of `_compute_levels` as above and calls `pns_levels(snap)` with
`EXAMPLE_HW` (the default, then `bin_s=BIN_S`), `bin_s=0.006` two times, the default again,
`bin_s=1` and `bin_s=1.0`, and `bin_s=0.006` with `thresholds_hz_per_t=(_LIMIT,)`. The call
counts are 1, 1, 2, 2, 3, 3 and 4. It checks the identities (`is`) of the repeats and
`bin_samples` of the default and of the `0.006` result.

**Assumptions:** None.

#### `test_pns_levels_shares_a_read_only_result`

**Checks:** Two callers of `pns_levels` get the same kept result. A change in place
of its level by the first caller raises `ValueError`, and the second caller gets the
level as it was.

**How:** The test calls `pns_levels` for the synthetic spin echo and keeps a copy of
`level_min_hz_per_t` and `level_max_hz_per_t`. `level_max *= 100` (through a local name,
so that the statement does not also assign the field of the frozen dataclass) and
`level_min_hz_per_t[0] = 0.0` must each raise `ValueError`. A second call must give the same
object, with arrays equal to the copies.

**Assumptions:** None.

#### `test_pns_levels_refuses_a_bad_struct_before_the_snapshot_type`

**Checks:** `pns_levels` with a pair whose struct is bad raises the error of the
defect, with a message that names it, before the type of the first argument is
checked: `ValueError` for a struct with no `x`, with no `x.stim_thresh`, with
`x.a1 = 5.0` and with `x.stim_limit = 0.0`, and for `x.tau1 = nan`; `TypeError` for
`x.tau1 = "0.2"`. Without the check, the missing field gave `AttributeError` from
`_hardware_key`.

**How:** Parametrized on `BAD_STRUCTS` of `tests/pns_hardware.py`: each is `safe_example_hw()` with
one defect. The test calls
`pns_levels(spin_echo_sequence(), hardware=(struct, "BAD"))` in
`pytest.raises(error, match=match)`. The first argument is a `pp.Sequence`, which is not a
snapshot and would raise the `TypeError` that names `load`.

**Assumptions:** The rule of the check is that of `pns_levels._check_hardware`, as in the
tests of section 2.2.

#### `test_pns_levels_refuses_a_hardware_that_is_not_a_pair_before_the_snapshot_type`

**Checks:** `pns_levels` with a `hardware` that is not a tuple of two items with a
`str` second item raises `TypeError` (the message names `hardware`), before the type of the
first argument is checked.

**How:** Parametrized on `NOT_A_PAIR` of `tests/pns_hardware.py` (a struct alone, also a
`SafeHardware` alone, a list, a tuple of three items, a label that is not a `str`, a path and
`None`). The test calls
`pns_levels(spin_echo_sequence(), hardware=hardware)` in
`pytest.raises(TypeError, match="hardware")`. The first argument is a `pp.Sequence`, which is
not a snapshot and would raise the `TypeError` that names `load`.

**Assumptions:** None.

#### `test_prediction_keeps_no_blocks`

**Checks:** `pns_levels` does not fill pypulseq's block cache: the cache of the private
sequence of a snapshot is off and empty after the call.

**How:** The test makes a snapshot of a synthetic spin echo sequence and calls `pns_levels`.
Afterward `snap.sequence.use_block_cache` must be False and `snap.sequence.block_cache` must
be empty.

**Assumptions:**

- `calculate_pns` reads every block with `get_block`, which keeps each block in
  `block_cache` when `use_block_cache` is True. `load` turns the cache off, so an empty cache
  after the call shows that the cache stayed off. That `load` turns it off is tested in
  `test_snapshot.py`.

#### `test_prediction_propagates_an_error_and_keeps_the_cache_off`

**Checks:** An error deep inside the SAFE model propagates out of `pns_levels`, and the block
cache of the snapshot's sequence stays off and empty.

**How:** The test makes a snapshot of a synthetic spin echo sequence and replaces
`pns_levels._safe_gwf_to_pns_chunk` (the pinned fork's chunk function) with a function that
raises `RuntimeError`. The call must raise the error, `use_block_cache` must be False and
`block_cache` must be empty afterward.

**Assumptions:** None.

#### `test_a_relative_and_an_absolute_path_of_one_asc_file_give_one_result`

**Checks:** `pns_levels` with `hardware_from_asc` of the relative path and with that of the
absolute path of one `.asc` file gives one object, in both orders of the two calls.

**How:** The test writes a gradient `.asc` file (the `write_gradient_asc` fixture), changes the
working directory to its folder, and makes the hardware from the relative name and from the
absolute path. For each order of the two, it makes a new snapshot of a synthetic spin echo
sequence, calls `pns_levels` with the first and with the second, and checks that the results are
the same object (`is`).

**Assumptions:** The label of the pair is the component name in the file, with no path in it
(the docstring of `hardware_from_asc`), so the two spellings give equal pairs.

### 2.8 Series (`test_series.py`)

`test_series.py` tests `series.py`: `Series`, the JSON-ready form of an analysis value
(design section 4.2, with the names of `docs/plans/series-coordinate.md`), with its four
kinds (`SAMPLES`, `ENVELOPE`, `POINTS` and `RUNS`), and `encode_array` and `decode_array`,
which write one numpy array as `{"dtype", "length", "data"}`. The encoding is the one of
`encode_tables` of pulseq-reports (commit `a322517`): the little-endian bytes of the array,
gzipped and base64-encoded.

Most tests build small series by hand, with no sequence and no pypulseq.
`test_the_series_of_pns_safe_levels_are_valid` and
`test_the_series_of_gradient_spectrum_is_valid` use synthetic sequences and pypulseq.
The round trip
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

#### `test_series_refuses_a_coord_start_that_is_not_finite`

**Checks:** A SAMPLES or an ENVELOPE series with a `coord_start` of infinity, -infinity or
NaN raises `ValueError` that names `coord_start`. A finite `coord_start` is valid. (POINTS
and RUNS need `coord_start` 0, as `test_series_refuses_a_field_that_the_kind_does_not_use`
checks.)

**How:** Parametrized over the two kinds and the three values. Each case first builds the
series with a finite negative `coord_start`, then with the bad value, and checks the error.

**Assumptions:** None.

#### `test_envelope_refuses_a_coord_end_that_is_not_finite`

**Checks:** An ENVELOPE series with a `coord_end` of infinity, -infinity or NaN raises
`ValueError` that names `coord_end`, with three bins and with no bin.

**How:** Parametrized over the three values. The test builds the series with 0 and with 3
bins and checks the error.

**Assumptions:** None.

#### `test_envelope_refuses_a_coord_end_out_of_range`

**Checks:** An ENVELOPE series of n bins raises `ValueError` when `coord_end` is not above
`coord_start + (n - 1) * coord_step` by more than the tolerance `1e-9 * coord_step` (the last
bin would be empty), and when it is above `coord_start + n * coord_step` by more than the
tolerance (the last bin would be longer than a step).

**How:** Parametrized. The cases are a `coord_end` exactly at the lower limit, within the
tolerance above it, below it (also at and below `coord_start`), for three bins and for one
bin; and a `coord_end` above the upper limit by 2 × 10⁻⁹ of a step, by a
millionth of a step, and by a tenth of a step; each with a negative `coord_start` and a
small step too.

**Assumptions:** A `coord_end` within the tolerance of the lower limit counts as equal to the
limit, so it is refused. The tolerance is for the rounding of the products of floats, as in
`pns_total`.

#### `test_envelope_accepts_a_coord_end_in_range`

**Checks:** An ENVELOPE series is valid for a `coord_end` at the upper limit
`coord_start + n * coord_step`, within the tolerance above it, inside the last bin, just
above the lower limit `coord_start + (n - 1) * coord_step` (by 0.01 step, and by 2 × 10⁻⁹ of a
step, which is beyond the tolerance), with one bin, with a negative `coord_start`, and with
no bin for `coord_end == coord_start` and above it. Each series equals its round trip.

**How:** Parametrized. Each case builds the series and checks that `coord_end` is kept and
that the round trip through strict JSON text is equal.

**Assumptions:** None.

#### `test_envelope_coord_end_limits_are_exact_at_the_tolerance`

**Checks:** For an ENVELOPE series of `n` bins, a `coord_end` that is `1e-9 * coord_step`
above the lower limit `coord_start + (n - 1) * coord_step` raises `ValueError`, and the
next float above that is valid. A `coord_end` that is the tolerance above the upper limit
`coord_start + n * coord_step` is valid, and the next float above that raises
`ValueError`.

**How:** Parametrized with three cases: unit step, negative start and one bin. The test
computes the tolerance and the limits with the same expressions as the check, so
`coord_end` is equal to the value it is compared with. It uses `np.nextafter` for the next
float.

**Assumptions:** The sums are floats that the check also makes, so the test needs the same
expression order as `Series._check_coordinates`.

#### `test_envelope_with_no_bin_refuses_a_coord_end_below_coord_start`

**Checks:** An ENVELOPE series with no bin raises `ValueError` for `coord_end < coord_start`,
also for a `coord_end` that is below by 10⁻¹², which the tolerance of the other cases
(10⁻⁹ of a step) would let through.

**How:** The test builds the series for three pairs of `coord_start` and `coord_end` and
checks the error.

**Assumptions:** With no bin there is no float product, so the tolerance does not apply.

#### `test_runs_refuses_a_start_or_end_that_is_not_finite`

**Checks:** A RUNS series with infinity, -infinity or NaN in `start` or in `end` raises
`ValueError` that names the array and says "finite", for float64 and float32.

**How:** Parametrized over the array, the three values and the two dtypes. The test builds
the valid series first, puts the value into the second run, and checks the error.

**Assumptions:** None.

#### `test_runs_refuses_an_end_before_the_start`

**Checks:** A RUNS series with `end[k] < start[k]` for one run raises `ValueError`, for float64,
float32, int64 and uint8, in the first and in the second run, and for a difference of 10⁻¹².

**How:** Parametrized. Each case builds the series with the two arrays and checks the error.

**Assumptions:** There is no tolerance for a run.

#### `test_runs_accepts_an_end_at_or_after_the_start`

**Checks:** A RUNS series is valid when `end[k] >= start[k]` for each run, also for
`end == start`, for integer and float dtypes, and with no run. Each series equals its round
trip.

**How:** Parametrized. Each case builds the series and checks the round trip through strict
JSON text.

**Assumptions:** None.

#### `test_runs_refuses_a_start_or_end_of_a_bool_or_complex_dtype`

**Checks:** A RUNS series whose `start` or `end` has a bool or a complex dtype raises
`ValueError` that names the array and says "integer or float".

**How:** Parametrized over the array and the two dtypes. The test converts one valid array
and checks the error.

**Assumptions:** The array of a series can be of a bool or complex dtype, but a run is an
interval of a real coordinate. The ordering of a complex array is not defined, and a bool
is not a coordinate, as the scalar coordinate fields refuse a bool.

#### `test_a_wrong_type_is_a_type_error_before_a_coordinate_that_is_not_finite`

**Checks:** The checks of the coordinates come after the checks of the types: a `coord_end`
that is a string is a `TypeError`, and a `meta` that is not a mapping is a `TypeError` even
when `coord_start` is NaN.

**How:** The test builds the two series and checks the error type of each.

**Assumptions:** None.

#### `test_the_series_of_pns_safe_levels_are_valid`

**Checks:** Each series of `pns.safe.levels` (`pns_total` and `pns_above_<k>`) is a valid
`Series`, and equals its round trip through `to_obj`, the strict JSON text
(`json.dumps(..., allow_nan=False)` and `json.loads`) and `from_obj`. This holds for each
sequence of `tests/synthetic.py` that has a builder without arguments (the spin echo with
the prephaser before and after, the GRE, the empty sequence, the arbitrary gradient, the
border, the 4 µs raster sequence) and for `build_repeating(10)`; with no threshold, with
one, and with two; with the default bin and with bins of 3.7 ms and 0.1 ms. The `coord_end`
of `pns_total` is `num_samples * dt_s` and its `coord_step` is `bin_samples * dt_s`, so the
test checks that the tolerance of the `coord_end` check holds for these float products. The
empty sequence gives no series.

**How:** Parametrized over the sequence and the case of thresholds and bin. The test runs
the analysis with `synthetic.EXAMPLE_HW`, calls `to_series`, checks the names, and checks
that each series equals its round trip through the strict JSON text. Constructing a
series that is not valid would raise.

**Assumptions:** The bin of 3.7 ms (370 samples) is not a divisor of the number of samples of
most sequences, so their last bin is short. The sequences with a rotation library and the
one of `waveform_sequence` are not in the list.

#### `test_the_series_of_gradient_spectrum_is_valid`

**Checks:** The series of `gradient.spectrum` for each sequence of the test above is a valid
`Series` that equals the series that `from_obj` reads from its `to_obj`. The empty sequence
gives no series, and the other sequences give one.

**How:** Parametrized over the sequences. The test runs the analysis with the default
arguments, calls `to_series`, and checks the round trip and the number of series.

**Assumptions:** No sequence is too short for the default window: the spectrum pads a short
sequence to one window.

#### `test_series_refuses_bad_arrays`

**Checks:** A series raises, with the message of its own check, when a necessary array of
its kind is missing (for each kind), when an ENVELOPE has an array other than `min` and
`max`, when `arrays` is not a mapping or has a key that is not a string, when an array is
not a numpy array, is zero-dimensional or two-dimensional, or has a string, object or
datetime dtype, and when two arrays have two lengths (for SAMPLES, ENVELOPE and RUNS).

**How:** Parametrized. Each case builds a series of one kind with the bad `arrays` and
checks for `TypeError` or `ValueError` with `match=` of the message of the check. An
ENVELOPE case has a `coord_end` that is valid for its arrays, so the check of `coord_end`
does not refuse it. The other kinds use the valid `coord_step` that the kind needs.

**Assumptions:** The test does not try each necessary array of each kind with a bad dtype,
only the dtypes in the list.

#### `test_envelope_refuses_bad_min_and_max`

**Checks:** An ENVELOPE with a complex or bool `min` or `max`, with a different dtype for `min` and `max` (two float dtypes, and an integer with a float), or with `min[i] > max[i]` (floats, integers, and reversed infinities) raises `ValueError` with the message of its own check.

**How:** Parametrized with `min`, `max` and the message. Build an ENVELOPE of valid coordinates (`_bins`) with the two arrays and check for `ValueError` with `match=`.

**Assumptions:** None.

#### `test_envelope_accepts_a_nan_and_min_equal_to_max`

**Checks:** An ENVELOPE accepts a NaN in `min`, in `max` or in both, `min[i] == max[i]`, integer arrays and arrays with no element, and the round trip is equal.

**How:** Parametrized. Build the ENVELOPE and check `_round_trip(s) == s`.

**Assumptions:** A bin with a NaN is not checked for the order, because a comparison with a NaN is false.

#### `test_points_refuses_a_coord_of_a_complex_or_bool_dtype`

**Checks:** A POINTS series with a `coord` of a complex or a bool dtype raises `ValueError`.

**How:** Parametrized over the two dtypes; check for `ValueError` with `match=` of the message.

**Assumptions:** None.

#### `test_points_accepts_a_coord_that_is_not_finite_or_not_a_float64`

**Checks:** A POINTS series accepts a `coord` of dtype int32, uint8, float32 or float64, and for a float dtype also an infinity, and the round trip is equal.

**How:** Parametrized over the four dtypes; set the last value of a float `coord` to infinity; check `_round_trip(s) == s`.

**Assumptions:** None.

#### `test_series_refuses_bad_meta`

**Checks:** A series raises when `meta` is not a mapping, has a key that is not a string,
has a value that is a list, a dict, a numpy complex, a numpy datetime or a numpy array, or
has the string value "inf", "-inf" or "nan".

**How:** Parametrized. Each case builds a valid SAMPLES series with the bad `meta` and
checks for `TypeError` (a wrong type) or `ValueError` (the three strings). The rules are
the rules of `Finding.data` in pulseq-checks.

**Assumptions:** None.

#### `test_series_meta_makes_a_numpy_float64_a_plain_float`

**Checks:** A `np.float64` in `meta` becomes a `float` of the exact type `float`. The
series equals the series with the same value as a `float`, and its JSON round trip gives
the same series with a `float`.

**How:** Build a SAMPLES series with `meta={"a": np.float64(1.5)}`. Check `type(...) is
float`, `==` with the series made with `1.5`, `_round_trip`, and the type of the value
after the round trip.

**Assumptions:** A `np.float64` is a subclass of `float`, so it passes the type check of
`meta`. Without the conversion it would stay a `np.float64`.

#### `test_series_meta_makes_a_numpy_scalar_a_python_scalar`

**Checks:** A numpy scalar of a bool, integer or float dtype in `meta` (float16, float32, float64, a NaN, int8, int64, uint32 and bool) is stored as a Python scalar of the exact type `bool`, `int` or `float`. The series equals the series made with the Python scalar, and its JSON round trip is equal.

**How:** Parametrized. Build a SAMPLES series with the numpy scalar in `meta`, check the exact type of the stored value, `values_equal` with the series made with the Python scalar (`values_equal`, because a NaN is not equal by `==` of the values), and `_round_trip`.

**Assumptions:** None.

#### `test_series_stores_a_str_subclass_as_a_str`

**Checks:** A `np.str_` as the name, the unit, the `coord_unit`, a key of `arrays`, a key of `meta` and a value of `meta` is stored as a plain `str`, and the JSON round trip gives an equal series.

**How:** Build a SAMPLES series with a `np.str_` in each of the six places, check that the type of each stored string is exactly `str`, and check `_round_trip(s) == s`.

**Assumptions:** None.

#### `test_a_copy_of_a_series_is_equal_and_read_only`

**Checks:** A series of each kind from `copy.deepcopy` or from `pickle` equals the original, is another object, has a `FrozenDict` for `arrays` and for `meta`, and has read-only arrays whose flag `writeable` cannot be set to True.

**How:** Parametrized over the four kinds and the two ways to copy. Check `==`, the type of the two dicts (and that a write raises `TypeError`), the flag of each array, and that `flags.writeable = True` raises `ValueError`.

**Assumptions:** `Series.__reduce__` rebuilds the copy with the constructor.

#### `test_series_rebuilds_a_copy_with_the_constructor`

**Checks:** `Series.__reduce__` gives the class and the fields, so the same arguments give an equal series, and a damaged state (a `coord_step` below 0, and an ENVELOPE with `min` above `max`) raises `ValueError` and does not make an invalid series.

**How:** Call `__reduce__` of an ENVELOPE series, check that the first item is `Series` and that it makes an equal series from the arguments, then change one argument to a bad value and check for `ValueError`.

**Assumptions:** `pickle` and `copy.deepcopy` call the first item of `__reduce__` with the arguments; the test calls it directly and does not make a damaged pickle stream.

#### `test_series_arrays_cannot_be_made_writable`

**Checks:** For a bool, integer, float and complex dtype, also with no element, an array of a series has the dtype and the values of the array that the caller gave, is read-only, and `flags.writeable = True` raises `ValueError`.

**How:** Parametrized. Build a POINTS series with the array of the dtype (and with an empty array), check the dtype, the values and the flag, and check for `ValueError` when the flag is set to True.

**Assumptions:** The message of numpy is "cannot set WRITEABLE flag to True of this array"; the test matches it.

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

#### `test_series_dicts_cannot_be_changed`

**Checks:** A change to `arrays` or to `meta` of a series raises `TypeError`, and
the series does not change.

**How:** The test builds a series, and for each of the two dicts it tries
`d[key] = value` (a shorter array, an `object()`), `del`, `update` and `pop`.
Each must raise `TypeError`. The test then checks that `to_obj()` is the same as
before and that `json.dumps` writes it.

**Assumptions:** None.

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

**Checks:** Two series with NaN in an array and in a `meta` value are equal, a series
equals itself, and `!=` is false for them.

**How:** The test builds two series from equal data with a NaN in each of the two places
and checks `==` and `!=`. A coordinate field cannot be NaN (`test_series_refuses_a_coord_start_that_is_not_finite`),
so it is not one of the places.

**Assumptions:** None.

#### `test_series_not_equal_for_a_different_field_or_array`

**Checks:** A series is not equal to a series with another array dtype, another array
length, another value, NaN in place of a number, another name, unit, `coord_unit` (ID
`coord-unit`, "Hz" in place of "s"), `coord_start`, `coord_step` or `meta`, and not equal
to a value that is not a series.

**How:** Parametrized. Each case builds one series that differs from a base SAMPLES series
in one thing, and checks `!=`. The test also checks `!=` of the base series and a string.

**Assumptions:** None.

#### `test_series_not_equal_for_a_different_kind`

**Checks:** A POINTS series and a RUNS series that differ only in the kind are not equal,
in both orders.

**How:** Build one `arrays` dict with `coord`, `value`, `start` and `end` (all valid for
both kinds), and one set of name, unit, `coord_unit` and `meta`. Build a POINTS and a RUNS
series from them, and check `!=` both ways. Also check that a second POINTS series with
the same fields is equal.

**Assumptions:** POINTS and RUNS accept the arrays of the other kind as extra arrays.

#### `test_envelope_series_not_equal_for_a_different_end`

**Checks:** Two ENVELOPE series that differ only in `coord_end` are not equal.

**How:** The test builds an ENVELOPE series, copies it with `dataclasses.replace` and
another `coord_end`, and checks `!=`. A SAMPLES series cannot have `coord_end`, so the case
is not in the parametrized test above.

**Assumptions:** None.

#### `test_series_equality_compares_the_order_of_the_arrays`

**Checks:** Two series with the same arrays in a different order are not equal.

**How:** The test builds the pair and checks `!=`.

**Assumptions:** None.

#### `test_series_equality_compares_the_order_of_the_meta_keys`

**Checks:** Two series whose `meta` has the same items in a different order are not equal.
`Series.from_obj(s.to_obj())`, also through `json.dumps` and `json.loads`, keeps the order
of the `meta` keys and equals `s`.

**How:** The test builds two series with `meta` `{"p": 1, "q": 2}` and `{"q": 2, "p": 1}`
and checks `!=`. It checks that a third series with the first `meta` equals the first. For
each of the two, it checks `list(meta)` and `==` after the round trip, with and without JSON
text, and that the JSON round trip of the first does not equal the second.

**Assumptions:** The order of the `meta` keys counts for `==`, as for each other dict of the
package (`_equality.values_equal`), because the JSON form keeps it. The docstring of
`Series` says so.

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

#### `test_series_round_trip_of_many_float32_values`

**Checks:** A SAMPLES series of 2000 float32 values with a second array of int16
values gives an equal series after the round trip, with the same dtypes.

**How:** The test makes random values with a fixed seed, builds the series, and checks the
round trip, the dtype of each array, and that the values are equal.

**Assumptions:** The path has no branch that depends on the size, so a small series is
enough.

#### `test_series_round_trip_of_values_that_are_not_finite`

**Checks:** Infinity and NaN in an array and in `meta` survive the round trip, `to_obj`
writes the floats of `meta` as "inf", "-inf" and "nan", and `json.dumps(allow_nan=False)`
accepts the object. The coordinate fields are finite.

**How:** The test builds an ENVELOPE series with the four kinds of value in the arrays
(`min` and `max` are in order, where neither is NaN), finite coordinate fields, and `meta` with infinity, -infinity, NaN, a finite float and the
string "nan?" (a string that is not one of the three). It checks the strings in `to_obj`,
that `json.dumps` accepts the object, that the round trip is equal, and that the non-finite
values of `meta` are floats again.

**Assumptions:** None.

#### `test_to_obj_keys_and_types`

**Checks:** `to_obj` has the keys `format` (the int 1), `name`, `kind`, `unit`,
`coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta` and `arrays` in this order. `kind` is the string value,
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
a dict, an unknown key, a missing key (also `format`, ID `no-format`, and `coord_unit`, ID
`missing-coord-unit`), a `format` other than the int 1 (2, a bool and a string; IDs `format-2`,
`format-a-bool` and `format-a-string`), an
object of rc2 (ID `rc2-object`), an unknown kind or a kind that is not a string, an empty
name, a name or unit that is not a string, a `coord_unit` that is null or a number (IDs
`coord-unit-null` and `coord-unit-a-number`), a `coord_step` that is zero, a string or
null, a null `coord_end` or `coord_start`, a `coord_start` that is a bool, a `coord_start`
or `coord_end` that is "inf", "-inf" or "nan" (IDs `coord-start-inf`,
`coord-start-minus-inf`, `coord-start-nan`, `coord-end-inf` and `coord-end-nan`), a
`coord_end` that is too small or too large for the bins (IDs `coord-end-too-small` and
`coord-end-too-large`), a `meta` or `arrays` that is not an object, a `meta` value that is
a list, and an array that is not an object or an object with no arrays. Each case raises
`ValueError` with the message of its own check, for example the case `coord-start-a-bool`
with "must be a number or null, not True".

**How:** Parametrized with the object and the message. Each case changes or removes one
key of the `to_obj` of a valid ENVELOPE series and checks for `ValueError` with `match=`
of the message. The case `rc2-object` has no `coord_unit` and the rc2 keys of the three
coordinate fields, with their values, so it also has unknown keys. The `TypeError` of the
series is a `ValueError` here, so a caller catches one type. `from_obj` goes through the
constructor, so it has the checks of the coordinate fields.

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


#### `test_a_coordinate_field_accepts_a_numpy_float_and_a_fraction`

**Checks:** `coord_start`, `coord_step` and `coord_end` accept a NumPy float and a `Fraction` (each
`numbers.Real` that is not a `bool`, the rule of `_validate.real`), and keep each as a
Python `float`.

**How:** A SAMPLES series with `coord_start=np.float32(0.5)` and `coord_step=Fraction(1, 4)`, and
an ENVELOPE series with `coord_end=np.float64(2.0)`. Each field must be the Python `float`
of its value.

**Assumptions:** None.
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

#### `test_decode_array_does_not_decompress_more_than_length_needs`

**Checks:** `decode_array` refuses data that decompresses to far more bytes than
`length` needs, and it does not decompress the whole stream.

**How:** The test replaces `zlib.decompressobj` with a spy that records the size
of each output. It decodes a gzip of 10 MB of zeros with `length` 1 and dtype
`uint8`. It must raise `ValueError`, the spy must have been called, and the sum
of the output sizes must be at most 2 bytes (`length * itemsize + 1`).

**Assumptions:** `decode_array` reads the stream with `zlib.decompressobj`. A
change to another decompressor fails this test.

#### `test_decode_array_refuses_more_than_max_bytes`

**Checks:** `decode_array(d, max_bytes=n)` raises `ValueError` for an array of more than `n`
bytes, and gives the array for `n` equal to its size or with no `max_bytes`. The check is
before the decompression: a `length` of `10**9` with data that is not base64 raises the
`max_bytes` error. A `length` that is too small for a large stream still raises the
error of the decompression bound.

**How:** The test encodes four float32 values (16 bytes) and decodes with `max_bytes` 16, 15
and 0. It decodes a dict with `length` 10**9 and `max_bytes` 100, and a gzip of 10 MB of
zeros with `length` 1 and `max_bytes` 100, and checks the messages.

**Assumptions:** None.

#### `test_from_obj_refuses_arrays_of_more_than_max_bytes`

**Checks:** `Series.from_obj(obj, max_bytes=n)` counts the bytes of all arrays of the
series together: it reads an envelope of two float32 arrays of three values (24 bytes) for
`n` 24 and with no `max_bytes`, and raises `ValueError` for 23.

**How:** The test takes `to_obj` of the ENVELOPE series and calls `from_obj` with each
`max_bytes`.

**Assumptions:** None.

#### `test_decode_array_refuses_a_length_that_overflows`

**Checks:** `decode_array` raises `ValueError` (not `OverflowError`) for a `length` of `10**30`, for a `length` of `sys.maxsize` with dtype uint8 and for a `length` with `length * itemsize` above `sys.maxsize`.

**How:** Call `decode_array` with a valid dict and each `length` in `pytest.raises(ValueError)` with `match="too large"`.

**Assumptions:** None.

#### `test_decode_array_refuses_bytes_after_the_gzip_stream`

**Checks:** `decode_array` raises `ValueError` for data that has bytes after the gzip stream (a second gzip stream, and one byte of 0), also when the first stream has the right length.

**How:** Build the text of a valid stream followed by each extra, check for `ValueError` with the message "there are bytes after it", and check that the valid stream alone decodes.

**Assumptions:** The test kills the mutation of `if decompressor.unused_data:` to `if False:`.

#### `test_decode_array_stores_a_bool_as_0_or_1`

**Checks:** A bool byte of 2 or 255 in the data decodes to True, the array has the bytes 0 and 1, and it encodes to the text of the canonical array.

**How:** Build the text of the bytes 0, 1, 2 and 255 with dtype `bool`, decode it, check the values and `view(np.uint8)`, and compare `encode_array` with that of `[False, True, True, True]`.

**Assumptions:** None.

#### `test_from_obj_refuses_a_number_that_overflows`

**Checks:** `Series.from_obj` raises `ValueError` (not `OverflowError`) for `coord_start`, `coord_step` or `coord_end` of `10**400`, and for an array with a `length` of `10**30`.

**How:** Take the object of an ENVELOPE series, change one key, and check for `ValueError` with `match=`.

**Assumptions:** None.

#### `test_decode_array_refuses`

**Checks:** `decode_array` raises `ValueError` for a value that is not a dict, a dict with
a missing key or an unknown key, a `length` that is too large, too small, negative, a
float or a bool, a dtype that is `object`, `datetime64[s]`, a string dtype, an unknown
name, a short name (`f4`) or not a string, `data` that is not a string, not base64, not
gzip or cut short, and data with a number of bytes that is not a whole number of items,
more than `length` or fewer than `length`. Each case raises `ValueError` with the message
of its own check. The case `data-not-base64` is a valid gzip text with a "!" in the middle
and its own padding, so only `validate=True` refuses it. The case `length-a-bool` is
refused as a bool, not as a wrong length.

**How:** Parametrized with the dict and the message. Each case changes one key of a valid
dict (or builds a gzip text of zero bytes) and checks for `ValueError` with `match=` of
the message.

**Assumptions:** The messages are the messages of the Python of the project (3.12), for
example "Only base64 data is allowed" of base64 and "Error -3 while decompressing data"
of zlib. The test does not check
each byte of a damaged gzip stream, only the cases in the list.

### 2.9 Analyses (`test_analyses.py`)

`test_analyses.py` tests `analyses.py`: the entry-point registry of the group
`pulseq_analysis.analyses`, the specification of each of the five analyses of the package
(`seq.index`, `gradient.peaks`, `gradient.blocks`, `pns.safe.levels` and `gradient.spectrum`),
`compute`, and `to_series` of `pns.safe.levels` and `gradient.spectrum` (design section 4.4 of
the plan of pulseq-analysis).

The registry tests that need two packages, a broken entry point or an object without
`spec.id` replace `importlib.metadata.entry_points` with a function that gives fake entry
points (an object with a `name`, a `dist` with the package name, and a `load`). The test of
the real registry uses the entry points that `uv sync` installs from `pyproject.toml`. The
tests of the series use `gre_sequence(num_trs=20)` with the example hardware of pypulseq, with
the stimulation limit multiplied so that the peak is 1.5 times `_LIMIT`, so that the total is
above `_LIMIT` in several runs (`hardware_for_peak` of `tests/pns_hardware.py`). `_LIMIT` is
`GAMMA_1H`, the stimulation limit for 1H in Hz/T (a fraction of 1 times `GAMMA_1H`): a PNS value and a threshold are
in Hz/T. The test of the spectrum series
uses `spin_echo_sequence()`.

**Assumptions for the whole file:**

- The package is installed in the environment of the tests, with its entry points: a run
  of `pytest` without `uv sync` after a change of the entry points in `pyproject.toml`
  fails the test of the real registry.

#### `test_the_registry_has_the_five_analyses_of_the_package`

**Checks:** With the installed entry points, `registry()` has the five IDs
`gradient.blocks`, `gradient.peaks`, `gradient.spectrum`, `pns.safe.levels` and `seq.index`, no other ID, each
with the object of this package, and each key is the `spec.id` of its analysis.

**How:** The test calls `registry()` and compares the sorted keys, the identity of each value
with `SEQ_INDEX`, `GRADIENT_PEAKS`, `GRADIENT_BLOCKS`, `PNS_SAFE_LEVELS` and
`GRADIENT_SPECTRUM`, and each key with `spec.id`.

**Assumptions:** No other installed package gives an analysis (the test environment has only
this package).

#### `test_two_analyses_with_one_id_raise_an_error_that_names_both_packages`

**Checks:** Two entry points whose analyses have the same ID raise `RegistryError`, and the
message has the ID and the names of the two packages.

**How:** The test makes two fake entry points, both named `t.a`, with two analyses of the ID
`t.a`, from the packages `pkg-one` and `pkg-two`, and checks the message of the error that
`registry()` raises. The names are the ID, so the rule of the duplicate ID is the one that
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


#### `test_an_entry_point_whose_name_is_not_the_spec_id_raises_an_error_that_names_both`

**Checks:** An entry point whose name is not the `spec.id` of its object raises `RegistryError`, and
the message has the name of the entry point, the name of its package and the `spec.id`.

**How:** The test makes a fake entry point named `other.name`, of the package `pkg-x`, whose
analysis has the ID `t.a`, and checks the message of the error that `registry()` raises.

**Assumptions:** None.

#### `test_the_strict_registry_raises_for_an_entry_point_that_breaks_a_rule`

**Checks:** For each rule of the registry (an entry point that cannot load, an object without
`spec.id`, a name that is not the `spec.id`, an ID that another entry point has), a fake entry
point of the package `pkg-bad` next to the installed ones raises `RegistryError` with the
name of the package, for `registry()` and for `registry(strict=True)`.

**How:** The test is parametrized over the four rules. It makes `entry_points` give the
installed entry points and then the fake one, and calls `registry()` and
`registry(strict=True)` under `pytest.raises`.

**Assumptions:** None.

#### `test_the_registry_that_is_not_strict_leaves_out_an_entry_point_and_warns`

**Checks:** With `strict=False`, a fake entry point that breaks one of the four rules is left
out with one `RegistryWarning` whose message has the name of the entry point, the name of its
package and the cause, and the result has the five analyses of this package, each the object
of this package.

**How:** The test is parametrized over the four rules. It makes `entry_points` give the
installed entry points and then the fake one, and calls `registry(strict=False)` under
`pytest.warns`.

**Assumptions:** The installed entry points are the five of this package.

#### `test_the_registry_that_is_not_strict_keeps_the_analysis_of_the_package_for_one_id`

**Checks:** When another package gives the ID of an analysis of this package, and its entry
point comes before the one of this package, `registry(strict=False)` warns with the name of
the other package, and the result has the analysis of this package for that ID.

**How:** The test makes `entry_points` give a fake entry point `seq.index` of `pkg-bad` first
and then the installed ones.

**Assumptions:** The installed entry points have a `value` that starts with
`pulseq_analysis.analyses:`.
#### `test_the_spec_of_each_analysis_has_the_documented_values`

**Checks:** The ID, the version 1, `params`, `necessary`, `defaults`, `rasters` and `cost` of
each analysis are the values of section 8.3 of `docs/plans/implementation.md` and of the
parameters of the plan `docs/plans/second-review-fixes.md` (D13) and of the rule of the
rasters of the plan `docs/plans/third-review-fixes.md` (D18). `seq.index` has the rasters
`("BlockDurationRaster",)`, and the four other analyses have
`("GradientRasterTime", "BlockDurationRaster")`. `seq.index` and
`gradient.blocks` have no parameter; `gradient.peaks` has `window` with the default None;
`pns.safe.levels` has `hardware` as the only necessary name, and the defaults `()` and `BIN_S`
for `thresholds_hz_per_t` and `bin_s`; `gradient.spectrum` has the three names
`max_frequency_hz`, `window_s` and `frequency_oversampling`, all with the defaults of
`grad_spectrum`. The title and the description are not empty. `series` is None for `seq.index`, `gradient.peaks` and `gradient.blocks`, and a text
for `pns.safe.levels` and `gradient.spectrum`.

**How:** Parametrized over the five analyses. The test compares each field with the table of
the plan, which the test file holds as a list.

**Assumptions:** The test does not check the words of the title, the description or the text
of `series`: they are for a reader.

#### `test_the_spec_of_each_analysis_agrees_with_the_signature_of_compute`

**Checks:** For each analysis, the parameters of `compute` after `seq` are all keyword-only,
and their names are `spec.params` in order. Each name of `spec.necessary` has no default in the
signature. `spec.defaults` has each other name of `params`, in the order of `params`, and each
default equals the default of the signature and has the same type (so `0.5` does not stand for
`1`, and `False` does not stand for `0`). A keyword that is not a parameter is a `TypeError`.

**How:** Parametrized over the five analyses. The test reads `inspect.signature(compute)`, and
calls `compute` on `empty_sequence()` with `unknown=1`.

**Assumptions:** The five analyses of the test are the ones that `registry()` gives (the test
of the registry checks the identity of each).

#### `test_analysis_spec_raises_for_params_that_disagree_with_necessary_and_defaults`

**Checks:** `AnalysisSpec` raises `ValueError` with the message of its own check for a
name of `necessary` that is not in `params`, a name with a default that is also in
`necessary`, a name of `params` with neither, a default name that is not in `params`, a
default name that is repeated (also when `params` repeats the name, so that the order of
defaults is right), defaults that are not in the order of `params`, and a default that is
not None, a `bool`, an `int`, a `float`, a `str` or a tuple of these.

**How:** Parametrized with `params`, `necessary`, `defaults` and the message. Each case
checks for `ValueError` with `match=` of the message.

**Assumptions:** None.

#### `test_analysis_spec_accepts_the_defaults_of_each_json_type_and_stays_hashable`

**Checks:** `AnalysisSpec` accepts the defaults None, `True`, `3`, `0.5`, `"s"`, `()` and
`(1, "a", (None, 2.5))`, with a necessary name before them in `params`. The spec is hashable
(`hash` works), and `spec.params = ()` raises `FrozenInstanceError`.

**How:** The test builds one spec with these seven defaults and one necessary name.

**Assumptions:** None.

#### `test_analysis_spec_raises_for_a_field_that_a_runner_uses`

**Checks:** `AnalysisSpec` raises `ValueError` for an empty `id`, a `version` of 0 or
below, a `cost` other than "fast" and "slow", a raster that is not in `RASTERS` (also the
empty str), a repeated name in `params`, and a default float that is NaN, infinite or
negative infinite (also inside a tuple). It raises `TypeError` for an `id` that is not a
`str`, a `version` that is a str, a float or a `bool`, a `cost` that is None, and `params`
or `rasters` that is a list or has an item that is not a `str`.

**How:** Parametrized with the changed fields, the exception type and the message. Each case
makes a valid spec with the changed fields and checks `pytest.raises` with `match=`.

**Assumptions:** None.

#### `test_analysis_spec_accepts_each_raster_cost_and_finite_default`

**Checks:** `RASTERS` is the four names `GradientRasterTime`, `BlockDurationRaster`,
`RadiofrequencyRasterTime` and `AdcRasterTime`, in this order. A spec with all of them,
version 3, cost "fast" and the finite defaults `(0.0, -1e300)` is accepted, and so is the
cost "slow".

**How:** The test builds the two specs.

**Assumptions:** None.

#### `test_the_spec_of_each_analysis_of_the_package_passes_the_checks`

**Checks:** For each of the five analyses of the package, `dataclasses.replace(spec)` (which
runs the checks again) equals the spec, and each of its rasters is in `RASTERS`.

**How:** Parametrized over the five analyses.

**Assumptions:** None.

#### `test_compute_of_gradient_peaks_with_a_window_gives_the_result_of_the_window`

**Checks:** `GRADIENT_PEAKS.compute(snap, window=w)` equals `gradient_peaks(snap, window=w)`,
and is not equal to the result of the whole sequence, for the windows `(0, T/2)`,
`(T/4, T/2)` and `(T/2, T)` of a sequence of length `T`.

**How:** Parametrized over the three windows of `gre_sequence(num_trs=4)`, in fractions of
`sequence_index(snap).end_s`. The test compares the results with `==` (the equality of
`GradientPeaks`).

**Assumptions:** The three windows have values (the RMS, at least) that differ from those of
the whole sequence, so that a `compute` that does not pass the window on fails the test.

#### `test_compute_of_gradient_peaks_without_a_window_gives_the_kept_result`

**Checks:** `GRADIENT_PEAKS.compute(snap)` and `compute(snap, window=None)` are the object
(`is`) that `gradient_peaks(snap)` gives. A result with a window is not that object, equals
`gradient_peaks(snap, window=window)`, and is not kept: a second call gives another object.
The kept result of the whole sequence is still the same object after the calls with a window.

**How:** `gre_sequence(num_trs=4)` and the window `(0, T/2)`.

**Assumptions:** None.

#### `test_compute_of_gradient_spectrum_passes_its_arguments_on`

**Checks:** `GRADIENT_SPECTRUM.compute(snap, max_frequency_hz=1000.0)` is the object (`is`)
that `gradient_spectrum(snap, max_frequency_hz=1000.0)` keeps, and it is not the object of the
defaults (which is `gradient_spectrum(snap)`). Its `frequency_hz` differs from that of the
defaults, and its `max_frequency_hz` is 1000.0. A call with `window_s=0.1` and
`frequency_oversampling=2.0` is the object that `gradient_spectrum` keeps for those two
arguments, and its `window_s` and `frequency_oversampling` are 0.1 and 2.0. So each of the
three arguments reaches the function.

**How:** `spin_echo_sequence()`. The test compares the objects with `is` and the fields of the
results.

**Assumptions:** `is` is the check because the function keeps its result for each tuple of
the three arguments.

#### `test_compute_of_seq_index_and_gradient_blocks_gives_the_kept_result`

**Checks:** `SEQ_INDEX.compute(snap)` and `GRADIENT_BLOCKS.compute(snap)` give the objects
that `sequence_index(snap)` and `block_gradient_values(snap)` keep for the sequence.

**How:** The test compares each pair with `is` for a `gre_sequence(num_trs=4)`.

**Assumptions:** Each function keeps its result for the snapshot. The other three
analyses have their own tests of `compute`.

#### `test_compute_of_pns_safe_levels_passes_bin_s_on`

**Checks:** `PNS_SAFE_LEVELS.compute(snap, hardware=EXAMPLE_HW, bin_s=1e-3)` gives the same
object (`is`) as `pns_levels` with that `bin_s`, and not the object of the default. Its
`bin_samples` is 100 (500 for the default), and the `coord_step` of its `pns_total` series
is `bin_samples * dt_s`. A `bin_s` that is a `bool` raises `TypeError` and a `bin_s` of 0
raises `ValueError`, both before the sequence is read.

**How:** `gre_sequence(num_trs=4)`. For the two refusals, `compute` gets an object that
raises `AssertionError` when the code reads any attribute of it.

**Assumptions:** None.

#### `test_compute_of_pns_safe_levels_without_hardware_raises_before_the_sequence_is_read`

**Checks:** `PNS_SAFE_LEVELS.compute(snap)` without `hardware` raises Python's own
`TypeError` (a missing required keyword-only argument `hardware`), also with
`thresholds_hz_per_t=(_LIMIT,)`. A `hardware` that is not a tuple of two items with a `str`
second item (`None`, the bare struct, a 1-tuple, a pair with a label that is not a `str`, a
list, a 3-tuple) raises `TypeError` with a message that contains
`asc.hardware_from_asc(path)` (the test checks only
that text). Both happen before the sequence is read.

**How:** The test passes an object whose `__getattr__` raises `AssertionError`, so a read of
the sequence gives another error.

**Assumptions:** A read of the sequence goes through an attribute of the object
(`__getattr__` is not called for the special methods that Python looks up on the type).

#### `test_the_pns_series_equal_the_level_and_the_runs_of_the_same_call`

**Checks:** For a sequence with more than one run above `_LIMIT` and `thresholds_hz_per_t=(_LIMIT,)`,
`to_series` gives `pns_total`, an ENVELOPE of unit "Hz/T" with the arrays `min` and `max`
(float32) equal to `level_min_hz_per_t` and `level_max_hz_per_t`, `coord_unit` "s",
`coord_start` 0, `coord_step` `bin_samples * dt_s`, `coord_end` `num_samples * dt_s`, and the
`meta` of design 4.4 (`hardware`, `dt_s`, `bin_samples`, `num_samples`, `peak`,
`peak_time_s` and the three `axis_peaks_*`, the values from `peak_hz_per_t` and
`axis_peaks_hz_per_t`). It gives `pns_above_0`, a RUNS series of unit "Hz/T"
and `coord_unit` "s", with the arrays `start`, `end`, `num_samples` (int64), `peak` and `peak_time_s` (float64),
in this order, with one entry for each interval of `above[_LIMIT]` (`start` and `end` are
`start_s` and `end_s` of the interval, `peak` is `peak_hz_per_t`) and the `meta`
`{"threshold": _LIMIT}`. For a `PnsLevels` of `hardware_from_asc(path)`, `meta["hardware"]`
is the name in the file.

**How:** The test calls `compute` with the hardware of `hardware_for_peak(snap, 1.5)` (`tests/pns_hardware.py`) and
`thresholds_hz_per_t=(_LIMIT,)`, and compares each field of `to_series` with the field of the same `PnsLevels` (`numpy.array_equal`
for the arrays, `tolist` for the intervals). For the file it writes a gradient `.asc` file with
the `write_gradient_asc` fixture and calls `pns_levels(snap, hardware=hardware_from_asc(path))`.

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

#### `test_the_spectrum_series_equals_the_spectrum_of_the_same_call`

**Checks:** For `spin_echo_sequence()`, `to_series` of `gradient.spectrum` gives one series,
`gradient_spectrum`, of the kind SAMPLES, the unit "Hz/m/sqrt(Hz)" and `coord_unit` "Hz". Its
arrays are `value`, `x`, `y` and `z` in this order, all float64, equal to `rss` and to the three
axes of the same spectrum. `coord_start` is 0.0 and `coord_step` is `frequency_hz[1]`, and
`coord_start + k * coord_step` is `frequency_hz` bit for bit. The `meta` is
`max_frequency_hz`, `window_s` and `frequency_oversampling`, with the defaults of
`gradient_spectrum`. For a spectrum of `window_s=0.1`, the `meta` has `window_s` 0.1: the
`meta` comes from the value, not from the defaults.

**How:** The test calls `compute` and `to_series` and compares each field by itself.
It compares the arrays with `numpy.array_equal`, and the frequencies with an `arange` of the
length of `frequency_hz`.

**Assumptions:** The test does not build the expected `Series` with the code under test. It
checks that the spectrum is not all zero, so that equal arrays are not empty of signal.

#### `test_the_other_three_analyses_give_no_series`

**Checks:** `to_series` of `seq.index`, `gradient.peaks` and `gradient.blocks` gives `()`,
for a sequence with gradients and for one without.

**How:** For `gre_sequence(num_trs=2)` and `empty_sequence()`, the test gives the value of
`compute` to `to_series`.

**Assumptions:** None.

#### `test_compute_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `compute` of each analysis of the registry raises `TypeError` with a message that
names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over the five analyses and over `gre_sequence()` and the path string
`"sequence.seq"`. For `pns.safe.levels` the call has `hardware=EXAMPLE_HW`, the one argument
that it needs. Each call must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

### 2.10 Gradient spectrum (`test_grad_spectrum.py`)

The spectrum is calculated as in pypulseq: Hann windows (50 ms by default) with
50 % overlap, the magnitude spectrum of each window, and the maximum over
windows. Here the gradients are sampled to the end of the sequence, with half a
window of zeros added at the start, and half a window or more at the end. The
end padding is the fewest zeros that make the padded waveform one window plus a
whole number of hops long. A hop is the step between two windows (25 ms by
default). The number of samples is `sampling.sequence_samples`. The RSS spectrum is the root-sum-of-squares
of the three axes in each window, then the maximum over windows. The values are
in Hz/m/√Hz, the unit of the gradients of a `.seq` file, with no gamma. To get
mT/m/√Hz, a caller multiplies the values by `1e3 / gamma`. The gradients are
sampled through the raster sampler (`sampling.GradientSampler`), in chunks of
`_CHUNK_WINDOWS` windows, so the memory does not grow with the sequence length.
`tests/oracles/grad_spectrum.py` is the module before the raster sampler. It samples the
polyline of `tests/oracles/waveform.py` (the model of MATLAB Pulseq) instead. It gives mT/m/√Hz with
`seq.system.gamma`. The oracle comparison multiplies this module's values by
`1e3 / seq.system.gamma`, so it also tests the conversion. The oracle is a copy of
the file of pulseq-reports.

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

#### `test_gradients_at_the_end_are_attenuated_no_more_than_in_the_middle`

**Checks:** A gradient at the end of the sequence gives the same spectrum as the
same gradient in the middle of the sequence. This holds when the number of
samples is a whole number of hops and when it is not, for a window of an even and
of an odd number of samples. The test replaces
`test_gradients_at_the_end_are_not_attenuated`: that test had a sequence of a
whole number of hops, so it could not find the bug.

**How:** For 5000, 6000, 7000 and 7499 samples, and for a window of 5000 samples
(`window_s=0.05`) and one of 4999 samples (`window_s=0.04999`), the test makes a
sequence of one block. The block has a trapezoid on x (`area=3000`) that ends at the end of the
block, and a delay that sets the length of the block to the number of samples. A
second sequence has the same block and then a delay block of 0.06 s, more than one
window, so the trapezoid is in the middle of that sequence. The spectrum of the
first sequence must have an RSS above 0. The RSS and the x spectrum of the two
sequences must agree with a relative tolerance of 1e-12 (the y and z spectra are
0 in both).

**Assumptions:**

- The window grid starts at the start of the sequence, so the test does not
  compare the trapezoid at the end with a trapezoid at the start. The end
  padding puts each sample within half a hop of the centre of a window. It cannot
  put the centre of a window on the last sample, so the value at the end can be
  below the value at the start. The test compares the end with the middle, where
  the same bound holds.
- The two spectra are equal bit for bit when measured (the maximum relative
  difference is 0). The tolerance of 1e-12 allows for a platform with another
  FFT rounding.
- With the old padding of half a window, the test fails for 7000 and 7499 samples
  (the largest RSS at the end is 48 % and 50 % of that in the middle). It passes for
  5000 and 6000 samples: for these two, the window that holds the trapezoid
  already exists, and a later window gives a smaller value.
- The test has no sequence with a window of an odd number of samples.

#### `test_no_gradients`

**Checks:** A sequence without gradients has no spectrum, with the reason
"no gradients", empty frequencies and RSS, and no axes.

**How:** The test makes a sequence with only a block pulse. It checks the
reason, that `frequency_hz` and `rss` have shape (0,), and that `axes` has the keys
`x`, `y` and `z`, each with an empty array (shape (0,)) of dtype `float64`. The
reason is the object `seq_index.NO_GRADIENTS`, and `grad_spectrum.NO_GRADIENTS` is that
object.

**Assumptions:** None.

#### `test_chunks_give_the_same_spectrum_as_one_chunk`

**Checks:** The spectrum does not depend on the chunk size.

**How:** The test makes a synthetic GRE sequence of 30 TRs of 20 ms (600 ms,
25 windows). It calls `_compute_spectrum` (the calculation without the kept
result) with the default arguments as plain floats, with `_CHUNK_WINDOWS` set to
1,000,000 (one chunk) and to 4 (7 chunks, the last one shorter). The two results
must not be the same object. The frequencies, each axis spectrum and the RSS must
be equal bit for bit (`array_equal`).

**Assumptions:**

- The results are equal bit for bit, because each window has the same samples
  and the module takes the FFT of each row of windows with numpy, so a row does
  not depend on the other rows. (Measured: also for chunks of 1 and 3 windows.) A
  change that makes the FFT of a row depend on the chunk, for example another FFT
  library, can make the test fail by a rounding difference.

#### `test_matches_scipy_spectrogram`

**Checks:** `gradient_spectrum` makes the FFTs itself, for the kept bins only
(`_chunk_spectrogram`). This test checks that its axis spectra and RSS equal
those made with scipy's `spectrogram`, the call that the module used before and
that pypulseq's `calculate_gradient_spectrum` uses, on the synthetic spin echo,
a GRE of 30 TRs and the arbitrary-gradient sequence.

**How:** The test sets `_CHUNK_WINDOWS` to 4, so the sequences make several
chunks, and calls `_compute_spectrum` with the default arguments as plain floats
(the calculation without the kept result). For the reference, it samples each axis
with `GradientSampler` at the sample times of the module (the number of samples
is `sequence_samples`), pads half a window of zeros at the start and `pad + (-nt) %
hop` zeros at the end, and calls `scipy.signal.spectrogram` on the whole padded
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
  against the oracle waveform.
- The result differs from scipy's only by float rounding (measured: 4.6e-16 of the
  peak on `build_repeating(10000)`), because the two take the FFTs of the same windows with a
  different order of operations.

#### `test_matches_oracle_on_synthetic_sequences`

**Checks:** `gradient_spectrum` samples the waveform with the raster sampler, and the
oracle samples the polyline of the oracle waveform (`tests/oracles/waveform.py`). This test
checks that the axis spectra and the RSS spectrum, times `1e3 / gamma`, agree with the oracle
(`tests/oracles/grad_spectrum.py`, the module before the raster sampler), on the
synthetic spin echo, GRE, arbitrary-gradient, empty and 600 Hz sine
sequences.

**How:** For each sequence, the test calculates the spectrum with this
module and with the oracle. The reasons must be equal. When there is a
spectrum, the frequencies must be equal. The axis spectra and the RSS of this
module, multiplied by `1e3 / seq.system.gamma`, must agree with the oracle
within a relative 1e-12 or an absolute 1e-12 times the array's own peak.

**Assumptions:**

- The sampler builds the waveform from each block's own corner points and
  `numpy.interp`, a different order of float operations than the oracle's
  whole-axis polyline, so the values are not always bit-for-bit equal.
- The multiplication by `1e3 / gamma` is exact only to the float rounding, and
  the tolerance allows for it.
- The sequences of many blocks are in `test_matches_oracle_with_many_chunks`, with a
  tolerance that grows with the duration.

#### `test_matches_oracle_with_many_chunks`

**Checks:** The same comparison with the oracle as `test_matches_oracle_on_synthetic_sequences`,
on sequences of `tests/scale_sequences.py`: `build_repeating` and `build_worst` at 1000 blocks
(200 TRs, 1.2 s and 1.4 s, 48 and 56 windows). `_CHUNK_WINDOWS` is 4, so each has 12 or 14 chunks
and a shorter last chunk, as in `test_matches_scipy_spectrogram`.

**How:** The test sets `grad_spectrum._CHUNK_WINDOWS` to 4 (`monkeypatch`), builds each sequence
with `1000 / TR_BLOCKS` TRs, and compares this module's spectrum (times `1e3 / gamma`) with the
oracle's, as the test above does, with the tolerance `1e-12 * max(1, duration in s)` instead of
1e-12.

**Assumptions:**

- The user chose this tolerance on 2026-09-28, in the work on pulseq-reports, when the oracle
  sampled `Sequence.get_gradients()`. That function adds the segment durations one at a time,
  and the sampler adds `(block start + delay) + offset`. The rounding of an absolute time grows
  with the time, and a gradient ramp turns it into a value difference. The difference was
  2.5e-12 of the peak at 10^4 repeating blocks (12 s). The oracle now makes its points with the
  same sums as the sampler, and the difference is below 1e-15 of the peak at 10^4 blocks of each
  builder. The tolerance stays.
- The test no longer runs the sequences of 10^4 blocks and 5000 blocks (14 s and 7 s) that it
  ran before 2026-10-07, so that it is faster. It does not test the rounding of an absolute
  time above 1.4 s.

#### `test_a_gap_with_ends_that_are_not_0_gives_the_spectrum_of_the_oracle_waveform`

**Checks:** The spectrum of a sequence with a short gap, a long gap or a step at a junction, and
ends that are not 0 next to it, equals the spectrum that the oracle calculates from the oracle
waveform (`tests/oracles/waveform.py`, the model of MATLAB Pulseq). The sequences also have a
first value and a last value that are not 0.

**How:** Parametrized over 23 sequences: `zero_gap_sequence`, `short_gap_sequence`,
`long_gap_sequence`, `non_zero_ends_sequence`, the two sequences of pypulseq-issues 12, and 17
more, `gap_of_1_5_raster_times_sequence` (a long gap of 1.5 raster times between two values that are not 0), `short_gap_from_0_sequence` and `short_gap_to_0_sequence` (a short gap from 0 to a value, and from a value to 0), a copy of each sequence of `tests/gap_sequences.py` with each amplitude negated (`gap_sequences.negated`), and the 8 sequences of `random_gaps.random_gap_sequence` with the seeds 0 to 7 (random signs, delays of 0 to 7 raster times, and zero, short and long gaps). `_assert_matches_oracle`
compares the axis spectra and the RSS (times `1e3 / gamma`) with `tests/oracles/grad_spectrum.py`
within 1e-12.

**Assumptions:** pypulseq's `calculate_gradient_spectrum` draws a line across a long gap and has
no step at a junction (pypulseq-issues 12), so it is not the reference.

#### `test_spectrum_does_not_depend_on_the_gamma_of_the_system`

**Checks:** The spectrum depends on the gradient values of the file only, not
on `seq.system.gamma`.

**How:** The test makes one 600 Hz sine waveform in Hz/m. It puts the waveform
in two sequences, one with `SYSTEM` and one with a copy of `SYSTEM` that has
another gamma (0.9 times). It checks that the two gammas differ. The
frequencies, each axis spectrum and the RSS must be exactly equal.

**Assumptions:** None.

#### `test_gradient_spectrum_keeps_the_result`

**Checks:** `gradient_spectrum` gives the same object for two calls on one
snapshot, and another object for a second snapshot of the same sequence.

**How:** The test calls `gradient_spectrum` two times on a snapshot of a GRE sequence of
2 TRs, and checks that the objects are the same (`is`). It then calls it on a new snapshot of
a GRE sequence of 2 TRs and checks that the result is another object.

**Assumptions:** A snapshot never changes, so there is no test of a change of the
sequence here (`test_snapshot.py` has it).

#### `test_the_arrays_of_a_spectrum_are_read_only`

**Checks:** Each array of a spectrum is read-only, also for a sequence without
gradients. A conversion to a new array works.

**How:** The test runs for the synthetic spin echo and for a sequence without
gradients (all arrays empty). It asserts 5 arrays for each: `frequency_hz`, `rss`
and the three axes. Each array must have `flags.writeable`
off, and a change in place (`a *= 1e3 / GAMMA_1H`, with `GAMMA_1H` from
`tests/synthetic.py`) must raise `ValueError`. Then `s.rss * 1e3 / GAMMA_1H` must give a writable array,
and `s.rss` must not change.

**Assumptions:** None.


#### `test_the_axes_of_a_spectrum_are_a_read_only_frozen_dict`

**Checks:** `axes` is a `FrozenDict` and a `dict`, also for a sequence without gradients. A new key,
an `update`, a change of an item and a deletion raise `TypeError`, and the keys stay as
they were. A spectrum from `pickle` or `copy.deepcopy` is equal to the original, and its
`axes` is a `FrozenDict`.

**How:** Parametrized on the spin echo and the sequence without gradients:
`gradient_spectrum(make_seq())`, then the checks above.

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

**Checks:** The spectrum calculated with the three arguments at the defaults of
pypulseq's `calculate_gradient_spectrum` equals the spectrum of a call with no
arguments. The result of a call with no arguments has these defaults in its
fields `max_frequency_hz`, `window_s` and `frequency_oversampling`. The test is
also a guard on pypulseq's defaults.

**How:** The test reads the defaults of `max_frequency`, `window_width` and
`frequency_oversampling` from the signature of
`pp.Sequence.calculate_gradient_spectrum`. It gives them to
`grad_spectrum._compute_spectrum` for the synthetic spin echo, so the result is
calculated and is not the kept result (a call of `gradient_spectrum` with these
values would give the kept object of the call with no arguments, because the key
is the same). It checks that the two results are not one object, and that the
frequencies, each axis spectrum and the RSS are exactly equal. The test also
compares the three fields of the result with the defaults.

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

#### `test_gradient_spectrum_keeps_the_bin_at_the_maximum_frequency_on_a_4_us_raster`

**Checks:** At a 4 us gradient raster and `window_s=0.01`, the bin at 2000 Hz is the last
frequency of the result: the tolerance of `keep_n` keeps a bin that float rounding puts
just above `max_frequency_hz`.

**How:** A sequence on a 4 us raster (gradient, RF and block duration rasters) with one
trapezoid. `gradient_spectrum(snap, window_s=0.01)`, and `frequency_hz[-1]` is 2000.0
(`approx`, `abs=1e-9`).

**Assumptions:** 2500 samples and an `nfft` of 7500 put a bin at 2000 Hz, and the float
rounding of `rfftfreq` puts that bin just above 2000 Hz, so the test fails without the
tolerance.

#### `test_gradient_spectrum_refuses_bad_arguments`

**Checks:** `gradient_spectrum` refuses each bad argument with the right error
type, before it reads the blocks or the kept results.

**How:** It replaces `sequence_index` of the
module with a function that fails, so a call that reads the blocks fails the
test. Each case gives one bad argument to the synthetic spin echo. The error
must be `TypeError` for a string and for a bool, in each argument. It must be
`ValueError` for NaN and for infinity, in each argument, for `window_s` of 0,
below 0 and of one sample, for a `frequency_oversampling` of 0.5, and for a
`max_frequency_hz` of 0, below 0, above the Nyquist frequency (60 kHz) and
below the frequency step. One case has a `max_frequency_hz` of 10 Hz with
`frequency_oversampling=1`: it is above the step of the defaults and below the
step of 20 Hz of the arguments. The case of one sample also gives
`match="samples at the gradient raster"`, the text of the check `nwin < 2`. Each
other case also has a `match=`, a part of the message of its own check (for example
"window_s must be above 0" or "below the frequency step"), so that a case cannot
pass on an error from another check.

**Assumptions:**

- The synthetic sequence has the default gradient raster of 10 µs, so the
  Nyquist frequency is 50 kHz and the step of the defaults is 6.67 Hz.
- The `match=` of each case matters most for the case of one sample: without it,
  the check of the frequency step (also a `ValueError`) hides a missing check
  `nwin < 2`.

#### `test_gradient_spectrum_keeps_one_result_for_each_set_of_arguments`

**Checks:** `gradient_spectrum` keeps one result for each tuple of the
three arguments, as floats.

**How:** For a GRE sequence of 2 TRs, the test calls `gradient_spectrum`
with no arguments, and then with `max_frequency_hz=1000.0`. The two objects
must be different, and the second has no frequency above 1000 Hz. A call with
no arguments again must give the first object. A call with
`max_frequency_hz=1000` (an integer) must give the second object.

**Assumptions:** None.

#### `test_gradient_spectrum_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `gradient_spectrum` with good other arguments raises `TypeError` with a message
that names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over `gre_sequence()` and the path string `"sequence.seq"`. The call with
the default arguments must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

#### `test_gradient_spectrum_refuses_arguments_that_need_no_raster_before_the_snapshot_type`

**Checks:** A `max_frequency_hz` that is NaN, a `window_s` that is negative and a
`frequency_oversampling` that is a string raise their own error before the type of the first
argument is checked.

**How:** Parametrized over the three. The first argument is `gre_sequence()`, a `pp.Sequence`
that is not a snapshot. The call must raise a `TypeError` or `ValueError` whose message does not
contain "load".

**Assumptions:** The checks that need the gradient raster of the snapshot (the window in samples,
the oversampling of 1 or more and the maximum frequency against the raster) come after the type
check, so they are not covered here; `test_gradient_spectrum_refuses_bad_arguments` covers them
with a snapshot.

### 2.11 Value equality (`test_equality.py`)

`test_equality.py` tests `_equality.py`: `values_equal`, the rules by which two values
are equal, `fields_equal`, and `value_dataclass`, the decorator that makes
`fields_equal` the `__eq__` of `SequenceIndex`, `GradientPeaks`, `BlockGradientValues`,
`PnsLevels`, `GradientSpectrum` and `Series`. The tests use small values and three
dataclasses of the test file, not results of the package.
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

#### `test_value_dataclass_makes_a_frozen_class_with_value_equality`

**Checks:** A class with `@value_dataclass` is a frozen dataclass that compares its fields
with `fields_equal`, is not equal to an object of another class with the same fields, and
is not hashable.

**How:** A class of the test file with an array and a dict, and a second class with the
same fields. A change of a field must raise `dataclasses.FrozenInstanceError`. Two objects
with the same values, a NaN in the array, must be equal. An object with another array
value, or with the same dict items in another order, must not be equal. An object of the
second class with the same values must not be equal. `hash` must raise `TypeError`.

**Assumptions:** None.

#### `test_a_frozen_dict_refuses_each_change`

**Checks:** Each method of `FrozenDict` that changes it raises `TypeError`, and the items
stay as they were.

**How:** One case for each of `__setitem__`, `__delitem__`, `clear`, `pop`, `popitem`,
`setdefault`, `update` and `__ior__`, on `FrozenDict({"a": 1, "b": 2})`. Each must raise
`TypeError` with "cannot be changed" in the message, and `dict(d)` must be the original.

**Assumptions:** The test does not call the methods of `dict` that the class does not
close through a C slot that Python code can reach in another way (for example
`dict.__setitem__(d, ...)`): a program can always change a `dict` that way.

#### `test_a_frozen_dict_reads_like_a_dict`

**Checks:** A `FrozenDict` is a `dict` and reading works as for a `dict`.

**How:** For `FrozenDict({"b": 1, "a": 2})`: `isinstance` of `dict`, `d["a"]`, `len`, `in`,
the iteration order, `dict(d)`, `get` of a missing key, and equality with `FrozenDict(b=1,
a=2)`.

**Assumptions:** The test checks the behaviour that `FrozenDict` gets from `dict`, not
code of the package.

#### `test_a_frozen_dict_is_made_from_pairs_and_keywords`

**Checks:** `FrozenDict(...)` takes the arguments of `dict`, so `dict.__init__` can fill it
although `__setitem__` is closed.

**How:** `FrozenDict([("a", 1)], b=2)` must hold `{"a": 1, "b": 2}`.

**Assumptions:**

- CPython's `dict.__init__` does not call the overridden `__setitem__`.
- The test checks the behaviour that `FrozenDict` gets from `dict`, not code of the
  package.

#### `test_a_frozen_dict_survives_pickle_and_copy`

**Checks:** A copy from `pickle`, `copy.deepcopy` or `copy.copy` is an equal `FrozenDict`
that still refuses changes.

**How:** For each of the three, the copy of `FrozenDict({"a": 1, "b": (2.0, 3.0)})` must be
of type `FrozenDict` (not a subclass, not a `dict`), have the same items in the same
order, and raise `TypeError` for `c["a"] = 5`.

**Assumptions:** None.

#### `test_a_frozen_dict_is_written_by_json_as_an_object_and_is_not_hashable`

**Checks:** `json.dumps` writes a `FrozenDict` as an object, and `hash` raises `TypeError`.

**How:** `json.loads(json.dumps(d))` must equal the plain dict of the items. `hash(d)` must
raise `TypeError`.

**Assumptions:** The test checks the behaviour that `FrozenDict` gets from `dict`, not
code of the package.

#### `test_the_union_of_a_frozen_dict_is_a_plain_dict`

**Checks:** `|` of a `FrozenDict` and a dict gives a new plain `dict`, in both orders, and
does not change the `FrozenDict`.

**How:** `d | {"b": 2}` and `{"b": 2} | d` must be of type `dict` (exactly) with the merged
items, and `dict(d)` must be the original.

**Assumptions:** The test checks the behaviour that `FrozenDict` gets from `dict`, not
code of the package.

#### `test_values_equal_does_not_separate_a_frozen_dict_from_a_dict`

**Checks:** `values_equal` compares a `FrozenDict` and a `dict`, or two `FrozenDict`s, by
the rules of two dicts.

**How:** A `FrozenDict` with an array value and an int value is compared with a dict with
the same items (equal), the same items in another order (not equal), another value (not
equal) and another key (not equal). Each case runs in both orders and with the other
dict made a `FrozenDict`. The `FrozenDict` and a list are not equal.

**Assumptions:** None.

#### `test_freeze_gives_a_read_only_copy_that_cannot_be_made_writable`

**Checks:** `_freeze` gives, for each array, a new array with the same dtype, shape and
values (a bool, integer, float and complex dtype, and an empty array), that is read-only,
whose flag `writeable` cannot be set to True (`ValueError`), and that does not share memory
with the original, which stays writable. `_freeze()` gives an empty tuple.

**How:** Parametrized over the dtypes. Freeze an array and an empty array of the dtype
together and check each property. After a write into the original, the frozen copy must be
unchanged.

**Assumptions:** The message of numpy is "cannot set WRITEABLE flag to True of this
array"; the test matches it.

### 2.12 Kept results (no test file)

The tests of `_kept.py`, which made a kept result again after a change of the sequence
object, are gone with `_kept.py`: a snapshot (section 2.17) never changes, so no stamp is
needed. Test 3 of the guard tests of the snapshot (`test_snapshot.py`) checks that a change
of the source sequence in place changes no result of a snapshot. The tests that a result is
kept for one snapshot are in `test_events.py` (section 2.14), `test_seq_index.py` (section
2.4), `test_pns_levels_kept.py` (section 2.7) and `test_grad_spectrum.py` (section 2.10).

### 2.13 Number arguments (`test_validate.py`)

`test_validate.py` tests `_validate.real`, the one rule for the number arguments of the
package. The tests call `real` with small values and do not use a result of the package.

#### `test_real_returns_a_float`

**Checks:** `real` accepts an int, a float, a numpy float64, float32 and int64, and a
`fractions.Fraction`, and returns `float(value)`.

**How:** One case for each type, and for a negative value and zero. The result must be of
type `float` (exactly) and equal to the expected float.

**Assumptions:** None.

#### `test_real_refuses_a_value_that_is_not_a_real_number_with_type_error`

**Checks:** A `bool`, a numpy bool, a string, `None`, a complex number and a list raise
`TypeError`.

**How:** `real("my_arg", value)` must raise `TypeError` with "my_arg must be a real number,
not" in the message, and so must the call with `finite=False, positive=True`.

**Assumptions:** None.

#### `test_real_refuses_a_value_that_is_not_finite_with_value_error`

**Checks:** With the default `finite=True`, NaN and the two infinities (also as a numpy
float32) raise `ValueError`.

**How:** `real("my_arg", value)` must raise `ValueError` with the name in the message.

**Assumptions:** None.

#### `test_real_with_finite_false_accepts_an_infinity_and_nan`

**Checks:** With `finite=False`, an infinity and NaN are returned.

**How:** `real` of `inf` and `-inf` must return them, and of NaN must return NaN.

**Assumptions:** None.

#### `test_real_refuses_an_int_too_large_for_a_float_with_value_error`

**Checks:** An int that a float cannot hold raises `ValueError`, not `OverflowError`.

**How:** `real` of `10**400` and, with `finite=False`, of `-(10**400)` must raise
`ValueError` with the name in the message.

**Assumptions:** None.

#### `test_real_with_positive_refuses_zero_and_a_negative_value`

**Checks:** With `positive=True`, a value not above 0 raises `ValueError`.

**How:** The values 0, 0.0, -1, -0.5 and a numpy float32 -2.0 must each raise `ValueError`
with the name in the message.

**Assumptions:** None.

#### `test_real_with_positive_accepts_a_positive_value_and_nan_is_not_positive`

**Checks:** With `positive=True`, a small positive value is returned; with `finite=False`
an infinity is returned and NaN raises `ValueError`.

**How:** `real("x", 1e-300, positive=True)` must return `1e-300`. The infinity with
`finite=False, positive=True` must return the infinity. NaN with the same arguments must
raise `ValueError`.

**Assumptions:** None.

### 2.14 Kept event points (`test_events.py`)

`test_events.py` tests `_events.py`: `event_points`, which reads the points of the unique
gradient events of a snapshot one time and keeps them on it, and the two
users of its result, `sampling.GradientSampler` and `grad_peaks._event_values`. The values of
`_event_values` are tested with hand-computed values. The tests
use the synthetic spin echo, gradient echo and arbitrary gradient sequences (and, for the
types of the arrays, the empty sequence). Each test makes its snapshot with `snapshot.load`.
The tests of the kept results are here too: a measurement gives one object for one snapshot, a
windowed `gradient_peaks` uses the kept values of the events, and a kept result does not keep its
snapshot alive. A snapshot never changes, so a kept result is never old (section 2.12).

#### `test_the_measurements_of_one_sequence_read_each_unique_gradient_event_once`

**Checks:** `gradient_peaks`, `block_gradient_values`, `pns_levels` and
`gradient_spectrum` of one sequence read each unique gradient event one time in total, not
one time for each measurement.

**How:** Parametrized over the three sequences. The test takes the number K of unique
gradient events from the sequence index (`grad_first.size`), replaces `pp.Sequence.get_block`
with a wrapper that counts its calls, and calls the four functions on one new sequence
(`pns_levels` with pypulseq's example hardware). The count must be K.

**Assumptions:**

- The measurements call `get_block` only for the unique gradient events and for the
  blocks that a window cuts. `gradient_peaks` is called without a window, so no block is
  cut.
- The wrapper counts the calls of the class, so a call from inside pypulseq counts too.

#### `test_event_points_arrays_are_read_only_and_have_the_documented_types`

**Checks:** The five arrays of `EventPoints` are read-only, have the documented dtypes and
have the documented sizes.

**How:** Parametrized over the three sequences and the empty sequence. For each array the
test checks the dtype (float64 for `delay`, `offsets` and `amp`; int64 for `count` and
`at`), that `flags.writeable` is False, and that a write raises `ValueError`. `delay`,
`count` and `at` must have K items, and `offsets` and `amp` the sum of `count`.

**Assumptions:** None.

#### `test_a_gradient_sampler_uses_the_arrays_of_event_points_without_a_copy`

**Checks:** `GradientSampler(snap)` keeps the pooled points of
`event_points` as they are, with no copy.

**How:** For each sequence of the file, the test checks `np.shares_memory` of the
sampler's offsets and amplitudes with `points.offsets` and `points.amp`.

**Assumptions:** The test reads two private attributes of the sampler. The samples of the
sampler are tested in `test_sampling.py`.

#### `test_event_values_of_a_trapezoid_and_an_arbitrary_gradient_equal_hand_computed_values`

**Checks:** `grad_peaks._event_values` gives the peak, the time of the peak, the slew, the
time of the slew and the integral of amplitude² of an x trapezoid with a delay and of a y
arbitrary gradient, equal to values that are computed by hand from the numbers given to
the `make_*` functions.

**How:** The trapezoid has A = 1e5 Hz/m, delay 100 µs, rise 200 µs, flat 400 µs and fall
300 µs. Expected: peak A at delay + rise, slew A / rise from the delay, integral A²
(rise/3 + flat + fall/3). The arbitrary gradient has the waveform `[1, 2, -3, -1, 2] u`
with u = 1e4 Hz/m, first and last 0, and raster r. Its points are at 0, 0.5 r, 1.5 r, 2.5
r, 3.5 r, 4.5 r and 5 r. Expected: peak 3 u at 2.5 r, slew 5 u / r from 1.5 r, integral
65/6 r u² (the sum of dt (a² + ab + b²) / 3 over the six segments). The test compares with
`pytest.approx` (relative 1e-12, and absolute 1e-12 s for the times). The test above
compares `_event_values` with `_polyline_values`, so a wrong `_polyline_values` does not
fail it. This test does.

**Assumptions:** The trapezoid has a fall longer than its rise, so the rise is the
steepest segment without a tie. The arbitrary gradient has 5 samples, because pypulseq
reads back an arbitrary gradient of 4 samples or fewer with a shape that ends at the last
sample, not half a raster after it.

#### `test_a_measurement_gives_the_same_object_for_one_snapshot_and_an_equal_one_for_another`

**Checks:** Two calls of a measurement with one snapshot give one object (the result is
kept). A second snapshot of the same sequence gives another object with an equal value.

**How:** Parametrized over `sequence_index`, `gradient_peaks`, `block_gradient_values`,
`pns_levels` (with pypulseq's example hardware) and `gradient_spectrum`. The test builds
`spin_echo_sequence()` and two snapshots of it. Two calls with the first snapshot must give
one object (`is`). The call with the second snapshot must give another object (`is not`)
that is `==` to the first.

**Assumptions:** Each result type compares by value.

#### `test_event_points_are_the_same_object_for_one_snapshot_and_equal_arrays_for_another`

**Checks:** Two calls of `event_points` with one snapshot give one object. A second snapshot
of the same sequence gives another object with equal arrays.

**How:** The test builds `spin_echo_sequence()` and two snapshots of it. `event_points` of
the first, twice, must be one object (`is`). `event_points` of the second must be another
object, and each field must be equal to the field of the first (`array_equal`).

**Assumptions:** `EventPoints` does not compare by value, so the fields are compared.

#### `test_a_windowed_gradient_peaks_is_a_new_object_for_each_call_and_is_not_kept`

**Checks:** Two calls of `gradient_peaks` with one window give equal results that are two
objects, and a call with a window does not change the kept result of `window=None`.

**How:** On a snapshot of `spin_echo_sequence()` with the window `(0, end_s / 2)`: two
windowed calls must give two objects (`is not`) that are `==`, and not the object of the call
with no window. After them, `gradient_peaks(snap)` must be the same object as before. On a
new snapshot, the call with the window must not make the result of `window=None`: the next
call with no window gives another object.

**Assumptions:** None.

#### `test_a_windowed_gradient_peaks_uses_the_kept_per_event_values`

**Checks:** `grad_peaks._event_values` runs one time for a snapshot, whatever the calls: a
call with a window, a call with another window, `gradient_peaks(snap)` and
`block_gradient_values(snap)` share one result. A new snapshot has its own.

**How:** The test replaces `grad_peaks._event_values` with a wrapper that records each
call. On a snapshot of `spin_echo_sequence()` it calls `gradient_peaks` with the window
`(0, end_s / 2)`, with the window `(end_s / 4, end_s)` and with none, and
`block_gradient_values`. The wrapper must have been called once. A call on a new snapshot
makes the count 2.

**Assumptions:** The window `(end_s / 4, end_s)` is inside the sequence.

#### `test_a_kept_gradient_peaks_cannot_be_changed_in_place`

**Checks:** The kept result of `gradient_peaks(snap)` refuses an assignment to a field of
the result and of an axis and a change of `axes`, and the kept `block_gradient_values(snap)`
refuses a write to an array and a change of a dict. After the refusals the next call gives the
same, equal values.

**How:** On a snapshot of `spin_echo_sequence()`, the test takes both results. Setting
`vector_peak_hz_per_m` raises `FrozenInstanceError`, setting a field of `axes["x"]` raises
`FrozenInstanceError`, setting `axes["x"]` raises `TypeError`, a write to `start_s[0]` raises
`ValueError` ("read-only") and setting `peak_hz_per_m["x"]` raises `TypeError`. Then
`gradient_peaks(snap)` must be the first object and equal to the result of a second
snapshot, and `block_gradient_values(snap)` must be the first object.

**Assumptions:** None.

#### `test_a_kept_result_does_not_keep_the_snapshot_alive`

**Checks:** A kept result has no reference to its snapshot: after the call and `del snap`,
the snapshot is collected.

**How:** Parametrized over `sequence_index`, `event_points`, `gradient_peaks`,
`block_gradient_values`, `pns_levels` (with pypulseq's example hardware) and
`gradient_spectrum`. The test makes a snapshot of `spin_echo_sequence()`, calls the
function, keeps the result, takes a `weakref` to the snapshot, deletes the snapshot and runs
`gc.collect()`. The `weakref` must be dead.

**Assumptions:**

- CPython collects the snapshot at once, or in the `gc.collect()` call. The test does not
  cover another Python.

#### `test_a_measurement_raises_type_error_that_names_load_for_a_sequence`

**Checks:** `event_points`, `gradient_peaks`, `block_gradient_values`, `pns_levels`,
`gradient_spectrum` and `GradientSampler` raise `TypeError` with a message that names `load`
for a `pp.Sequence`.

**How:** Parametrized over the six. Each is called with `spin_echo_sequence()` (and pypulseq's
example hardware for `pns_levels`) and must raise `TypeError` with `match="load"`.

**Assumptions:** None.

### 2.15 The oracle of the gradient waveform (`test_oracle_waveform.py`)

`test_oracle_waveform.py` tests `tests/oracles/waveform.py`, the oracle of the gradient
waveform (the model of `docs/implementation.md`, section 1, and of section 5.1 of
`docs/plans/third-review-fixes.md`). The oracle
does not import the package. The tests do not call the package either. Each expected value
is computed by hand from the numbers given to the `make_*` functions, and the text of the
test shows the calculation. The sequences and the constants DT, U and A are in
`tests/gap_sequences.py`, which the tests of `gradient_peaks`, `sampling`, `pns_levels` and
`grad_spectrum` use too. They use `SYSTEM`, so the gradient raster time DT is 10 µs and
`max_slew * DT` is 63864 Hz/m. U is 1e4 Hz/m. A is half of `max_slew * DT`. A block with a
gradient that starts or ends at a value that is not 0 next to a gap is below the limit that
`add_block` accepts, so pypulseq builds each sequence. Block IDs in the text are the IDs
that `add_block` gives: 1, 2, 3.

#### `test_the_polyline_of_each_sequence_of_pypulseq_issue_12_is_the_one_of_matlab_pulseq`

**Checks:** The oracle gives the points that MATLAB Pulseq gives for the two sequences of
pypulseq-issues 12, and credits the two ramp points to the right blocks.

**How:** Parametrized over the two sequences: the second gradient starts at A after a
delay, and the first gradient ends at A before the end of its block. Both have a gap of
100 µs, so it is a long gap. After the points that repeat a point are removed, the points
must be at 0, 100, 200, 205, 295, 300 and 400 µs, with the values 0, A, A, 0, 0, A and 0.
The sequence has no step. The point at 205 µs is credited to the first block, and the
point at 295 µs to the second. `sample` at 50, 150, 202.5, 250, 297.5 and 350 µs must give
A/2, A, A/2, 0, A/2 and A/2.

**Assumptions:** The values of MATLAB Pulseq are those in `issue.md` of pypulseq-issues 12.
They are not run in this repository. The test removes the repeated points with a tolerance
of 1 ps and 1e-6 Hz/m. Other tests check the repeated points.

#### `test_the_values_of_each_sequence_of_pypulseq_issue_12_are_hand_values`

**Checks:** The oracle gives the hand values of the slew, the peak, the vector peak and the
RMS of the two sequences of pypulseq-issues 12.

**How:** Parametrized over the two sequences. A ramp of A in DT/2 has the slope 2 A / DT,
which is `max_slew`, and the oracle must give it as the slew, at 200 or at 295 µs. The peak
and the vector peak must be A. The RMS is A times sqrt(170 / 400): the integral of g² is
(100/3 + 100 + 5/3 + 5/3 + 100/3) µs times A², over 400 µs. y and z have no peak block.

**Assumptions:** The ramp to 0 and the ramp from 0 have the same slope up to the last bit
of a float, so the test does not check which one is the slew. It does not check the peak
time or the peak block either, because the peak value is on several points.

#### `test_a_zero_gap_with_two_different_values_is_a_step_that_the_later_block_has`

**Checks:** Two extended trapezoids that meet at a block edge with different values give a
step, and the oracle credits the step to the later block and gives the hand values.

**How:** The first block goes from 0 through U to 2 U in 200 µs. The second goes from U to
0 in 100 µs. The step is -U at 200 µs. The points must be at 0, 100, 200, 200 and 300 µs
with the values 0, U, 2 U, U and 0. The step must have the time 200 µs, the size -U and the
second block. `sample` at the time of the step must give 2 U, the value before the step.
`sample` at 50, 150 and 250 µs must give U/2, 1.5 U and U/2. Over the whole sequence, the
peak is 2 U at 200 µs in block 1. The slew is the step, U / DT = 2e9 Hz/m/s, at 200 µs in
block 2, because each segment has only 2e8. The RMS is U: the integral of g² is 3 U² times
100 µs, over 300 µs.

**Assumptions:** The test does not check the value of `sample` at the first and the last
point.

#### `test_a_window_has_the_step_at_its_start_and_not_the_step_at_its_end`

**Checks:** A window has a step when the time of the step is at its start or inside it, and
it does not have a step at its end. A point that is on the other side of an edge is not in
the window.

**How:** The sequence is the one of the test above. The window from 150 to 250 µs has the
step: the slew is 2e9 in block 2, the peak is 2 U in block 1, and the RMS is U times
sqrt(11/6). The window from 100 to 200 µs ends at the step. It does not have the step, nor
the first point of block 2. The slew is the segment, U / 100 µs from 100 µs in block 1, the
peak is 2 U, and the RMS is U times sqrt(7/3). The window from 200 to 300 µs starts at the
step. It has the step, but not the last point of block 1. The peak is U in block 2, and the
RMS is U / sqrt(3). The vector peak at 200 µs is 2 U in block 1 for the window that ends
there, and U in block 2 for the window that starts there.

**Assumptions:** The rule for the edge is the one in the docstring of the oracle. The
plan fixes it for a step (`lo <= t < hi`), and the rule for a point follows from it.

#### `test_a_short_gap_is_a_line_that_the_later_block_has`

**Checks:** A gap of one raster time with ends that are not 0 is a straight line, not two
ramps, and the oracle credits it to the later block.

**How:** The first gradient goes from 0 to 3 U in 100 µs, and its block lasts 110 µs. The
second block starts at 2 U and goes to 0 in 100 µs. The points must be at 0, 100, 110 and
210 µs with the values 0, 3 U, 2 U and 0, and there is no step. `sample` at 105 µs must give
2.5 U. The slew is the line, U / DT = 1e9, from 100 µs, in block 2. The peak is 3 U at
100 µs in block 1. The RMS is U times sqrt(149/63): the integral of g² is 496.67 U² µs over
210 µs. The samples of the blocks (11 and 10 samples, at 5, 15, ... µs of each block) must
be the values of the two gradients, and the 11th sample of block 1 is 2.5 U, on the line.

**Assumptions:** The gap is one raster time up to the rounding of a float. The oracle
accepts a gap up to DT plus 1 ns.

#### `test_a_long_gap_has_a_ramp_to_zero_for_each_end_that_is_not_zero`

**Checks:** A gap of more than one raster time with both ends not 0 gets a ramp to 0 after
the earlier event and a ramp from 0 before the later event, credited as the plan says, and
the samples of the gap are 0.

**How:** Block 1 has a gradient from 0 to 3 U in 100 µs. Block 2 is a delay of 200 µs. Block
3 has a gradient from 2 U to 0 in 100 µs. The points must be at 0, 100, 105, 295, 300 and
400 µs with the values 0, 3 U, 0, 0, 2 U and 0. The point at 105 µs is credited to block 1
and the point at 295 µs to block 3. The slew is the ramp to 0, 3 U / 5 µs = 6e9, from 100 µs,
in block 1. The peak is 3 U at 100 µs in block 1. The RMS is U times sqrt(455/400). The 40
samples of the blocks must be the values of the two gradients, with 0 for the 20 samples
of block 2.

**Assumptions:** None.

#### `test_a_window_cuts_the_ramp_of_a_long_gap_and_credits_it_to_the_block_of_the_ramp`

**Checks:** A window that cuts a ramp has the part of the ramp with the interpolated value
at the edge, and credits it to the block of the ramp. The vector peak is credited to the
block that has its time.

**How:** The sequence is the one of the test above. The window from 150 to 250 µs is in the
gap, so each value is 0 and each block is None. The window from 102.5 to 150 µs has half of
the ramp to 0. The peak is 1.5 U at 102.5 µs, and the slew 6e9 at 102.5 µs, both in block 1.
The RMS is the square root of (1.5 U)² times 2.5 µs / 3, over 47.5 µs. The vector peak is
the same value at the same time, in block 2, because 102.5 µs is in block 2. The window
from 102.5 to 400 µs has also the ramp from 0 and block 3. The peak is 2 U at 300 µs in
block 3. The slew is the cut ramp, 6e9 from 102.5 µs, in block 1. The RMS is calculated
from the three pieces.

**Assumptions:** The time of a cut segment is the start of the cut. The block of the vector
peak is a choice of the oracle (the block that has the time), because the plan does not
say it.

#### `test_a_first_value_and_a_last_value_that_are_not_zero_are_steps_at_the_two_ends`

**Checks:** A first point of the axis that is not 0 and a last point that is not 0 each give
a step from and to 0, credited to the first and the last block, and a window has them by the
rule of its edges.

**How:** Block 1 goes from 3 U to 0 in 100 µs, and block 2 from 0 to 2 U in 100 µs. The
points must be at 0, 100 and 200 µs with the values 3 U, 0 and 2 U. The steps must be at 0
and 200 µs with the sizes 3 U and -2 U, credited to block 1 and block 2. `sample` at -1,
50, 150 and 201 µs must give 0, 1.5 U, U and 0. Over the whole sequence, the first step is
the slew, 3 U / DT = 3e9 at 0 in block 1, because the last step is at the end of the
window. The peak is 3 U at 0 in block 1, and the RMS is U times sqrt(13/6). The window from
100 to 200 µs has neither step. The slew is 2 U / 100 µs from 100 µs in block 2, and the RMS
is 2 U / sqrt(3). The window from 50 to 200 µs cuts the first segment. The slew is
3 U / 100 µs from 50 µs in block 1, and the RMS is U times sqrt((1.5²/3 × 50 + 4/3 × 100) /
150).

**Assumptions:** The test does not check the value of `sample` at the time of the first
point and of the last point.

#### `test_the_vector_peak_is_at_the_union_of_the_points_of_the_axes`

**Checks:** The vector peak is the largest magnitude at the times of the points of all the
axes, also at a time that is a point of one axis only, and the values of each axis are
correct when two axes play in one block.

**How:** One block of 400 µs has an x trapezoid of 3 U (rise 100 µs, flat 200 µs, fall
100 µs) and a y triangle of 4 U with its top at 150 µs. The vector peak must be 5 U at
150 µs in block 1: at that time x is 3 U and y is 4 U. At 100 µs and at 300 µs, the vector
is smaller. For x, the peak is 3 U at 100 µs (the first of two equal values), the slew is
3 U / 100 µs from 0, and the RMS is 3 U times sqrt(2/3). For y, the peak is 4 U at 150 µs,
the slew is 4 U / 150 µs from 0, and the RMS is 4 U / sqrt(3). In the window from 160 to
400 µs, the vector peak must be hypot(3 U, 3.84 U) at 160 µs, the start of the window,
and the peak of y must be 3.84 U at 160 µs. The peak time of x is 160 µs, the first of the
equal values 3 U.

**Assumptions:** The x slew is the rise and the fall (equal up to the last bit of a float).
The test checks its value and not its time.

#### `test_an_axis_with_no_event_has_no_point_and_is_zero`

**Checks:** An axis with no gradient event has an empty polyline, and each value of the
axis is 0 with no block.

**How:** The sequence is the one of the test above, with no z event. The polyline of z has
no point and no step, and it has the block ID of the one block. `sample` at 0, 100 and 400
µs gives 0, `block_samples` gives 40 zeros, and each value of `peaks` for z is 0 with the
blocks None.

**Assumptions:** None.

#### `test_a_segment_of_length_zero_inside_an_event_is_kept_and_has_no_slope`

**Checks:** The two points of a trapezoid with a flat time of 0 stay in the polyline, as a
segment of length 0, and that segment has no slope.

**How:** One block has a trapezoid of 3 U with a rise of 100 µs, a flat time of 0 and a
fall of 100 µs. The points must be at 0, 100, 100 and 200 µs with the values 0, 3 U, 3 U
and 0, and there is no step and no segment that is a step. The slew must be 3 U / 100 µs
from 0 in block 1 (a slope for the segment of length 0 would be a division by 0). The peak
is 3 U at 100 µs, and the RMS is 3 U / sqrt(3).

**Assumptions:** None.

#### `test_the_points_of_a_sequence_with_no_end_next_to_a_gap_are_the_points_of_pypulseq`

**Checks:** The oracle reads the points of the events as pypulseq does, for a sequence in
which no end of an event next to a gap is not 0.

**How:** Parametrized over the synthetic spin echo and gradient echo sequences (trapezoids)
and the synthetic arbitrary gradient sequence. For each axis, the points of the oracle
(without the points that repeat a point) must be equal to the points of `seq.waveforms()`:
same times (1 ps) and same values (relative 1e-9).

**Assumptions:** pypulseq's `waveforms()` is correct for these sequences, because no end
that is next to a gap is not 0. The test does not check the model of the gaps. The arbitrary
gradient sequence has a first and a last value of about 14 Hz/m, but they are at the two
ends of the axis, where `waveforms()` has no extra point.

### 2.16 The `.asc` files (`test_asc.py`)

`test_asc.py` tests `asc.py`: `read_gradient_asc`, which reads a gradient `.asc` file and the
files that it includes with `$INCLUDE` into nested fields (the package's own reader; the tests
compare it with pypulseq's `readasc`, which it replaces); `hardware_name`, which takes the
name of the hardware from the fields; `safe_hardware`, which makes the `SafeHardware` of the
fields; and `hardware_from_asc`, which gives the pair `(SafeHardware, label)` that
`pns_levels` takes. The real `.asc` files are confidential, so the tests
that need a file with the PNS parameters write one with the `write_gradient_asc` fixture of
`tests/conftest.py` (the PNS parameters of pypulseq's example hardware, in the plain layout or in
the layout of a scanner file). The tests of the include rules write small files in `tmp_path`.
That `pns_levels` keeps its result for a pair from a file is tested in section 2.7.

#### `test_asc_file_with_a_missing_include`

**Checks:** When a file that `$INCLUDE` names is not there, reading the `.asc`
file stops with an error that names both files.

**How:** The test writes a test `.asc` file with the scanner layout, deletes
the `_GSWD_SAFETY.asc` file, and reads the main file. It must raise
`FileNotFoundError` with a message that has the main file name and the
included file name.

**Assumptions:** None.

#### `test_asc_files_that_include_each_other`

**Checks:** Reading two `.asc` files that include each other stops with
`ValueError` that names the cycle. It does not recurse until `RecursionError`.

**How:** The test writes `a.asc` with a `$INCLUDE b.asc` line and `b.asc` with a
`$INCLUDE a.asc` line, and reads `a.asc`. The message must have `a.asc`, `b.asc`
and `a.asc` in this order.

**Assumptions:** None.

#### `test_asc_file_that_includes_itself`

**Checks:** Reading a `.asc` file with a `$INCLUDE` line that names itself stops
with `ValueError`.

**How:** The test writes `a.asc` with a `$INCLUDE a.asc` line and reads it. The
message must name `a.asc` twice.

**Assumptions:** None.

#### `test_asc_file_included_by_two_branches_is_not_a_cycle`

**Checks:** A file that two different included files both include is read
without an error, and its fields are in the result.

**How:** The test writes `shared.asc`, `b.asc` and `c.asc` (each includes
`shared.asc`) and `main.asc` (includes `b.asc` and `c.asc`). The fields read
must be the field of `main.asc` and the field of `shared.asc`.

**Assumptions:** None.

#### `test_include_line_forms_that_read_the_included_file`

**Checks:** A `$INCLUDE` line reads the included file when `$INCLUDE` is in
upper, lower or mixed case, when the name is in double quotes, and when a `#` or
`//` comment follows the name.

**How:** For each form (parametrized), the test writes `inc.asc` with `y = 2`
and `main.asc` with `x = 1` and the `$INCLUDE` line, and reads `main.asc`. The
fields must be `x` and `y`.

**Assumptions:** The comment marks are those that pypulseq's `readasc` accepts
after a value.

#### `test_include_line_with_a_quoted_name_with_spaces`

**Checks:** A quoted name with spaces and a comment after it names the
included file.

**How:** The test writes `my safety.asc` with `y = 2` and a main file with
`$INCLUDE "my safety.asc" # ...`, and reads the main file. The fields must be
`x` and `y`.

**Assumptions:** None.

#### `test_include_line_that_does_not_parse_raises`

**Checks:** A line that starts with `$INCLUDE` (any case) but has no name, has
junk after the name, or has an open quote raises `ValueError` that names the
file, the line number and the line.

**How:** For each line (parametrized), the test writes `main.asc` with the line
as its second line and reads it. The message must have `main.asc`, `line 2` and
the `repr` of the line in this order.

**Assumptions:** None.

#### `test_included_fields_replace_fields_with_the_same_name`

**Checks:** The fields of an included file are merged into the fields of the
main file, and a field in both files gets the value of the included file.

**How:** The test writes a main file with `a.b[0] = 1`, `a.b[1] = 2`,
`c = "old"` and a `$INCLUDE` line, and an included file with `a.b[1] = 3` and
`c = "new"`. The fields read must be `a.b[0] = 1`, `a.b[1] = 3` and
`c = "new"`.

**Assumptions:**

- The `$INCLUDE` line is the last field of the main file in this test, so the
  included values are the last values, as in the file order. A field after a
  `$INCLUDE` line that is also in the included file is not tested.

#### `test_hardware_name`

**Checks:** The hardware name comes from `asCOMP[0].tName` (a scanner file) or
`asCOMP.tName`, and is "unknown" without either.

**How:** The test gives the name function the fields for each of the three
cases and checks the name.

**Assumptions:** None.

#### `test_read_gradient_asc_reads_every_form_of_a_line`

**Checks:** `read_gradient_asc` reads a string, an integer, a float with an exponent and a
sign, a single quoted character, an empty string, indices (`e[1][2].f`) and a comment after a
value (`#` and `//`) into nested dicts of the right types, and leaves out a blank line, a
comment line, a line with no `=`, and the fields after `### ASCCONV END ###`. LF and CRLF line
ends give the same fields.

**How:** Parametrized on the line end. The test writes one file with each form (`_FORMS`) and
compares the fields with the expected dict (`_FORMS_FIELDS`). It checks the type of six
values (`int` for digits only, `float` for a number with a point, an exponent or a sign, `str`
for a quoted value).

**Assumptions:** The expected dict is written by hand from the rules of the reader, not taken
from pypulseq's `readasc`.

#### `test_read_gradient_asc_leaves_out_the_fields_after_the_end_marker_of_an_included_file`

**Checks:** The end marker `### ASCCONV END ###` of an included file also ends the fields of
that file.

**How:** The test writes `inc.asc` with `y = 2`, the marker and `z = 3`, and `main.asc` that
includes it after `x = 1`. The fields must be `x` and `y`.

**Assumptions:** None.

#### `test_read_gradient_asc_gives_the_fields_that_pypulseqs_readasc_gives`

**Checks:** For the file of every form, `read_gradient_asc` gives the fields that pypulseq's
`readasc` gives (its first result).

**How:** `pytest.importorskip` of `pypulseq.utils.siemens.readasc`. The test writes the file
of `_FORMS` and compares the two results with `==`.

**Assumptions:** The comparison covers the forms of `_FORMS` only.

#### `test_read_gradient_asc_gives_the_fields_of_a_fixture_file_that_readasc_gives`

**Checks:** For the plain file and for the scanner layout of the `write_gradient_asc` fixture,
`read_gradient_asc` gives the fields that `readasc` gives for the file (for the scanner layout,
the fields of the main file and of the included file, merged).

**How:** Parametrized on `split`, with `pytest.importorskip` as above. For the scanner layout
the expected fields are the fields of `readasc` for the main file and for the safety file, and
the test checks that their keys are `asCOMP`, `asGPAParameters` and `GradPatSup`.

**Assumptions:** `readasc` ignores `$INCLUDE`, so the test merges the two files itself.

#### `test_read_gradient_asc_raises_for_a_line_it_cannot_read`

**Checks:** A number that `float` cannot read, a line with `=` that is not a field (a bad value,
no value), a field name with an empty part or an index that is not a number, and a field under
a name that has a value, raise `ValueError` that names the file, the line number and the
reason.

**How:** Parametrized on the line. The test writes `main.asc` with `x = 5` and the line, and
reads it. The message must match `main.asc, line 2: ` and the reason.

**Assumptions:** None.

#### `test_hardware_from_asc_gives_the_safe_hardware_and_the_name_of_the_file`

**Checks:** `hardware_from_asc(path)` is the pair `(safe_hardware(asc), hardware_name(asc))` of
`asc = read_gradient_asc(path)`, for the plain layout and for the layout of a scanner file (a
main file that includes the PNS parameters with `$INCLUDE`). The `SafeHardware` has the name of
the file, also for the scanner layout, and the nine fields of each axis of pypulseq's example
hardware, which the fixture writes.

**How:** Parametrized on `split`. The `write_gradient_asc` fixture of `tests/conftest.py` writes
the file. The test checks that the result is a tuple, that the struct is a `SafeHardware`, that
the label, `hardware_name(asc)` and `struct.name` are `"MP_GPA_TEST"`, that the struct equals
`safe_hardware(asc)`, and that `dataclasses.asdict` of each axis equals the fields of
`safe_example_hw()`.

**Assumptions:** None.

#### `test_hardware_from_asc_has_the_fields_of_pypulseqs_asc_to_hw`

**Checks:** The `SafeHardware` of a file has the attributes of the namespace that pypulseq's
`asc_to_hw` gives for the same fields: the same attribute names, and for each axis the same
names and values.

**How:** Parametrized on `split`, with `pytest.importorskip` of
`pypulseq.utils.siemens.asc_to_hw`. The test compares `vars` of the struct with `vars` of the
namespace, and `dataclasses.asdict` of each axis with `vars` of the axis of the namespace.

**Assumptions:** The name is not compared: `asc_to_hw` gives "unknown" for the scanner layout.

#### `test_safe_hardware_is_named_after_the_component_of_the_file`

**Checks:** The name of the `SafeHardware` is `hardware_name(asc)`: the component name, also in
the scanner layout (`asCOMP[0].tName`), and "unknown" without one.

**How:** Parametrized on `split`. The test reads a file with the name "OTHER_NAME", checks the
name, removes `asCOMP` from the fields and checks that the name is "unknown".

**Assumptions:** None.

#### `test_a_file_without_gradient_scale_factors_is_refused`

**Checks:** A file with no `asGPAParameters` field raises `ValueError` that names the
gradient scale factor of the first axis and says that the package does not assume one, from
`hardware_from_asc` and from `safe_hardware`, in the plain and in the scanner layout.

**How:** Parametrized on `split` and on the function. The fixture writes the file with
`scale_factors=False`; the test checks that the text has no `asGPAParameters` and calls the
function in `pytest.raises(ValueError, match=...)`.

**Assumptions:** pypulseq's `asc_to_hw` prints a warning and assumes 1/pi for such a file: the
test does not call it.

#### `test_a_file_without_the_gradient_scale_factor_of_one_axis_is_refused`

**Checks:** A file that has the scale factors of two axes but not the third raises
`ValueError` that names the field of the missing axis.

**How:** Parametrized on the axis. The test removes the line of `flGScaleFactor<axis>` from a
plain file and calls `hardware_from_asc`.

**Assumptions:** None.

#### `test_a_file_without_a_pns_field_is_refused_and_the_error_names_it`

**Checks:** A file that lacks a `tau`, `a`, stimulation limit or stimulation threshold field
raises `ValueError` that names the field, with the prefix `GradPatSup.Phys.PNS.` in the
scanner layout.

**How:** Parametrized on six fields. The test removes the line of the field from the file and
from the file that it includes, and calls `hardware_from_asc`. The message must be
`the .asc file has no field <name>`.

**Assumptions:** None.

#### `test_a_scanner_file_without_the_pns_parameters_is_refused`

**Checks:** A file with a `GradPatSup` field and no `Phys.PNS` under it raises `ValueError`
that names `GradPatSup.Phys.PNS`.

**How:** The test reads a scanner file, sets `asc["GradPatSup"]` to `{"Phys": {}}` and calls
`safe_hardware(asc)`.

**Assumptions:** None.

#### `test_a_file_with_an_a_sum_that_is_not_1_is_refused`

**Checks:** A file whose `flGSWDAX[0..2]` do not sum to 1 (within 0.001) raises `ValueError`
from `SafeAxis`.

**How:** The test sets `flGSWDAX[0]` to 0.9 in a plain file and calls `hardware_from_asc`. The
message must name `a1 + SafeAxis.a2 + SafeAxis.a3 must be 1`.

**Assumptions:** The other errors of `SafeAxis` are tested in section 2.19.

### 2.17 The snapshot (`test_snapshot.py`)

`test_snapshot.py` tests `snapshot.py`: `load`, which makes a `Snapshot` of a `.seq` file or
of a `pp.Sequence`, and the four guards of the design (`docs/plans/fourth-review-fixes.md`,
section 5.1). The sequences are the synthetic sequences, a sequence with each kind of event
that `add_block` takes (a sinc pulse with its slice gradients, a trapezoid with an ADC and two
labels, an arbitrary gradient, an extended trapezoid, a digital output, a trigger, a soft
delay, a delay and definitions), and a sequence with a soft delay between two trapezoids.
The results that the tests compare are the index, the events, the event points, the samples
of the sampler and the four measurements of the gradients (`gradient_peaks`,
`block_gradient_values`, `pns_levels` with pypulseq's example hardware and
`gradient_spectrum`), each with its default arguments.

#### `test_a_snapshot_of_a_sequence_shares_no_mutable_object_with_it`

**Checks:** The object graph of a sequence and the object graph of `load(seq).sequence` have no
mutable object in common, so no change of the sequence in place can reach the snapshot. With a
warm block cache in the source, the snapshot has an empty block cache that is turned off, and
the source keeps its own cache object with the same blocks.

**How:** Parametrized over the seven sequences and over a cold and a warm block cache (each
block of the source read with `get_block` before `load`). A walk collects each object that can
be reached from a root and that can change: through attributes, `__slots__`, dicts, lists,
tuples, sets, and the items and the base of arrays. It leaves out numbers, strings, `None`,
numpy scalars and dtypes, tuples and frozensets (their items are walked), and read-only arrays
(an array and each array that it views are read-only, and the data is `bytes`). A list, dict,
set, writable array, object with attributes, or an object of a type that the walk does not
know counts as mutable. The test first checks that the walk finds shared objects between the
sequence and `copy.copy(seq)`, so that the walk can fail. It then checks that the two graphs of
the sequence and of the snapshot share none, that `snapshot.source` is `None`, that
`use_block_cache` of the snapshot's sequence is False and its `block_cache` is `{}`, and, with
the warm cache, that `seq.block_cache` is the same dict object with the same blocks and
`seq.use_block_cache` is still True.

**Assumptions:**

- The walk finds an object only through the ways above. An object that is held in a way that
  the walk does not follow (for example in a closure) is not found.
- This test is the proof for every way to change the source. The tests of
  `test_a_change_of_the_source_changes_no_result_of_the_snapshot` are examples.

#### `test_a_snapshot_of_a_sequence_read_from_a_file_shares_no_mutable_object_with_it`

**Checks:** A sequence that `read` made from a file with definitions, labels, extensions and
soft delays shares no mutable object with `load(seq).sequence`.

**How:** Parametrized over the sequence with each kind of event, the sequence with a soft
delay and the gradient echo. The test writes each one to a file, reads the file into a new
`Sequence`, and checks by the walk of the test above that the sequence and the snapshot's
sequence share no mutable object, and that they are two objects.

**Assumptions:** The walk is the one of the first test of this section.

#### `test_a_snapshot_writes_the_bytes_of_its_source`

**Checks:** `load(seq).sequence.write(path)` gives a file with the same bytes as
`seq.write(path)`.

**How:** Parametrized over the seven sequences. The test makes the snapshot first, then writes
the source and the snapshot's sequence to two files and compares the bytes. The snapshot is made
before the writes because `write` sets the definition `TotalDuration` and the signature of the
sequence that it writes.

**Assumptions:** The bytes are those of pypulseq's `write`, which removes duplicate events and
rounds the values. Two sequences with the same bytes can differ in a value that `write` does
not write.

#### `test_load_of_a_sequence_and_of_its_file_give_equal_results`

**Checks:** For a file that `write` made from a sequence, `load(seq)` of the sequence that `read`
makes from that file (a copy) and `load(path)` (no copy) have equal results, and
`snapshot.source` is the path.

**How:** Parametrized over the seven sequences. The test writes the sequence, reads the file
into a `Sequence`, and compares `_results` of `load(that sequence)` and `load(path)` with
`values_equal` (arrays: same dtype, shape and values). `_results` is the index, the events
(each as the dict of its attributes), the event points, `sample` of each axis at 501 times
from 0 to the end, `block_samples` of each axis for the whole sequence when every block is on
the raster, and the four measurements of the gradients.

**Assumptions:** The sequence is read from the file, not the sequence that was built in memory,
because `write` rounds the values of the file, so the results of the built sequence and of
the file can differ in the last digits. The next test compares the built sequence.

#### `test_a_snapshot_of_a_sequence_has_the_results_of_the_same_sequence_with_no_copy`

**Checks:** The copy that `load(seq)` makes does not change a result.

**How:** Parametrized over the seven sequences. The test builds the sequence two times and
compares `_results` (see above) of `load(first)` with `_results` of `Snapshot(second)`, which holds
the second sequence with no copy and no check.

**Assumptions:** Two builds of one builder give the same sequence. `Snapshot(sequence)` makes a
snapshot with no check, which the package does not use.

#### `test_a_change_of_the_source_changes_no_result_of_the_snapshot`

**Checks:** After `load(seq)`, a change of `seq` in place changes no result of the snapshot. A
new `load(seq)` gives the new results.

**How:** Parametrized over six changes (`mod_grad_axis("x", 0.5)` of the gradient echo,
`set_block` on the existing block 3 of the spin echo, `apply_soft_delay(TE=5e-3)` of the soft delay
sequence, a write into a row of `seq.block_events`, a write into `seq.block_durations`, and a
write into `seq.grad_raster_time`) and over two cases: the snapshot made its results before the
change, and it makes them after it. The reference is `_results` of `load` of a second sequence
of the same builder that does not change. After the change of `seq`, `_results` of the snapshot
must equal the reference. Then the test makes the same change to a third sequence, and checks
that `_results` of a new `load(seq)` equals `_results` of `load` of the third sequence and
differs from the reference.

**Assumptions:** The six changes are examples of the calls of pypulseq that change a sequence in
place; the first test of this section is the proof for every way. Each change changes at least
one result, which the last check shows.

#### `test_load_accepts_an_unsigned_sequence_and_an_unsigned_file`

**Checks:** `load` gives a snapshot of a sequence with no `[SIGNATURE]` hash and of a file with
no `[SIGNATURE]` section, adds no hash (`signature_value` stays `''`), and the hash changes no
result.

**How:** The test loads a sequence that `add_block` built, and compares `_results` with those of
the same sequence with the three signature attributes set by hand, as `write` sets them. Then it
writes the spin echo to a file, cuts a copy of the file at its `[SIGNATURE]` section, and compares
`_results` of `load` of the two files.

**Assumptions:** `write` rounds the values, so the unsigned file is compared with the signed
file, not with the sequence in memory.

#### `test_load_refuses_a_sequence_with_a_rotation`

**Checks:** `load` raises `NotImplementedError` for a sequence with the rotation extension.

**How:** Parametrized over a sequence with a `rotation_library` and a sequence with the
`"ROTATIONS"` extension type. The test calls `load` and checks the error message.

**Assumptions:** The two ways to find a rotation are those of `extensions.refuse_rotations`;
pypulseq 1.5.0.post1 cannot make a rotation.

#### `test_load_refuses_an_unsigned_sequence_with_a_rotation`

**Checks:** The rotation check of `load` does not depend on a hash: a sequence with a rotation
and no hash raises `NotImplementedError`.

**How:** A sequence with a rotation library and `signature_value` set to `''` is loaded inside
`pytest.raises(NotImplementedError)`.

**Assumptions:** None.

#### `test_load_calls_refuse_rotations_once_and_no_measurement_calls_it`

**Checks:** `load` calls `refuse_rotations` one time, and no measurement of the snapshot calls
it again.

**How:** Parametrized over the seven sequences. The test replaces `refuse_rotations` in
`snapshot` with a wrapper that counts the calls and calls the original, loads the sequence, and
checks one call. Then it replaces `refuse_rotations`, in `extensions`, in `snapshot` and in
`seq_index`, `_events`, `sampling`, `grad_peaks`, `pns_levels` and `grad_spectrum` (also where
the module has no such name), with a function that raises, and runs `_results` (the index, the
events, the event points, the sampler and the four measurements). No call is made, and the count
stays at one.

**Assumptions:** A module that reaches the check in another way than by this name is not found.

#### `test_load_refuses_another_type_and_a_snapshot`

**Checks:** `load` raises `TypeError` that names `load` for `None`, an `int`, `bytes`, a list,
and a `Snapshot`.

**How:** Parametrized over the five arguments. The test calls `load` and checks the type of the
error and that its message has `load`.

**Assumptions:** None.

#### `test_check_snapshot_raises_a_type_error_that_names_load`

**Checks:** `_check_snapshot` (the check that each public function makes of its first argument)
raises `TypeError` that names `load` for a `pp.Sequence`, `None` and a path, and nothing for a
`Snapshot`.

**How:** Parametrized over the three bad arguments. The test calls `_check_snapshot` with a
snapshot (no error), then with the argument (`TypeError`, message with `load`).

**Assumptions:** The test calls a private function; each public function calls it for its first
argument, and the tests of each public function check that.

#### `test_a_copy_of_a_snapshot_is_a_new_snapshot_with_no_kept_results`

**Checks:** A copy of a `Snapshot` from `pickle` or `copy.deepcopy` is a new snapshot with a new
sequence, the same `source`, no kept results, and the same results when it makes them again.

**How:** Parametrized over `pickle.loads(pickle.dumps(s))` and `copy.deepcopy`. The test writes
the gradient echo to a file, loads the file (so `source` is the path, not `None`) and makes its
index and event points, so the kept dict is not empty. It checks
that the copy is a `Snapshot`, is not the same object, has a sequence that is not the same
object, has the same `source`, and has an empty kept dict (`_kept_results`). It then checks
that `sequence_index` and `event_points` of the copy equal those of the original
(`values_equal`).

**Assumptions:** The test reads the kept dict through the private `_kept_results`. `source` is
`None` here, as the snapshot is of a sequence.

#### `test_a_snapshot_has_read_only_properties_no_new_attribute_and_the_hash_of_its_identity`

**Checks:** The properties `sequence` and `source` cannot be set, a new attribute cannot be
added, two snapshots of one sequence are not equal, and a snapshot is a key of a dict by
identity.

**How:** The test makes two snapshots of one sequence. Setting `sequence`, `source` or a new
attribute raises `AttributeError`. A snapshot equals itself and not the other one, its hash is
stable, and a dict with both snapshots as keys gives each one its own value.

**Assumptions:** The test does not check that the kept dict, which is private, cannot be set.

#### `test_load_accepts_a_path_like_and_source_is_its_str`

**Checks:** `load` takes the path of a file as a `str` or as an `os.PathLike`, and
`snapshot.source` is the `str` of the path.

**How:** Parametrized over `str` and `pathlib.Path`. The test writes the spin echo, loads the
path in each form, and checks that `source` equals the path as a `str`, that its type is `str`,
and that the index has the 6 blocks of the sequence.

**Assumptions:** None.

### 2.18 The names of the interface (`test_interface.py`)

The tests read the backtick spans and the code blocks of `docs/usage.md` and
`docs/implementation.md`. A dotted name whose first part (after an optional
`pulseq_analysis.`) is a module of the package is a name with a module, and so is each name of a
`from pulseq_analysis.module import ...` line of a Python code block. A bare name in a span or a
block is a name of any module.

#### `test_each_name_that_the_documents_give_with_a_module_can_be_imported`

**Checks:** Each module and each name that the documents give with a module (`analyses.registry`,
`series.FrozenDict`, `pulseq_analysis.snapshot`, the names of the imports of the code blocks)
exists in the package.

**How:** The test reads the dotted names and the imports of the documents, checks that it found
`series.FrozenDict`, `analyses` and the import of `gradient_peaks` (so the reading is not empty),
imports each module, and collects each name that the module does not have.

**Assumptions:** A further part of a dotted name (a method, as in `Series.to_obj`) is not read.
A name that a document gives in a private module (for example `_events._read_points`) is also
checked.

#### `test_the_interface_names_of_the_review_are_in_the_documents`

**Checks:** The documents give `series.SeriesKind`, `analyses.Analysis` and `series.FrozenDict`,
and the three names are at their public paths: `series.FrozenDict` is the `FrozenDict` of
`_equality`, and the other two are defined in `series` and `analyses`.

**How:** The test reads the dotted names of the documents, imports the three names, and compares
the object and the `__module__` of each.

**Assumptions:** None.

#### `test_each_public_name_of_a_module_is_in_the_documents_or_an_exception`

**Checks:** Each name that a public module defines (a module without a `_` at the start, a name
without a `_` at the start) is in the documents, or is in `EXCEPTIONS` of the test.

**How:** The test takes the names of the top level of the source of each module (def, class and
assignment, so an imported name such as `np` does not count), and compares those that no span or
code block of the documents gives with `EXCEPTIONS`.

**Assumptions:** A bare name counts for any module. The modules `_equality`, `_events` and
`_validate` are not read.

#### `test_each_exception_is_a_public_name_that_no_document_gives`

**Checks:** Each entry of `EXCEPTIONS` is a name that its module defines, that no document gives,
and has a reason.

**How:** The test loops over `EXCEPTIONS`. It passes with no entry.

**Assumptions:** None.

### 2.19 The SAFE hardware and filter (`test_safe.py`)

`test_safe.py` tests `safe.py`: `SafeAxis` and `SafeHardware` (immutable, checked when they are
made), `SafeHardware.from_namespace` (the form of pypulseq's `asc_to_hw` and
`safe_example_hw()`), and `_safe_gwf_to_pns_chunk`, the chunked SAFE filter that `pns_levels`
runs. The module is ported from pypulseq's `safe_hw_check` and `_safe_gwf_to_pns_chunk`; the
tests that compare with the functions of the pinned fork use `pytest.importorskip` of
`pypulseq.utils.safe_pns_prediction` and compare exactly (`numpy.testing.assert_array_equal`
or `==`), because the port does the same float operations. The test file has its own copy of
the numbers of pypulseq's example hardware (`_EXAMPLE_AXES`), and one test compares the copy
with `safe_example_hw()`.

#### `test_a_safe_axis_keeps_its_fields_as_floats_and_is_frozen`

**Checks:** `SafeAxis` stores each field as a `float` (an `int` argument becomes a `float`),
and a field of a `SafeAxis` and an axis of a `SafeHardware` cannot be set.

**How:** The test makes a `SafeAxis` from integers, checks `type(...) is float` for the nine
fields, and expects `dataclasses.FrozenInstanceError` for the set of `tau1` and of `x`.

**Assumptions:** None.

#### `test_a_safe_axis_refuses_a_bad_field`

**Checks:** `SafeAxis` raises `ValueError` for a NaN, an infinity, a `stim_limit` that is 0 or
negative, and an `a1 + a2 + a3` that is more than 0.001 from 1; and `TypeError` for a string, a
`bool` and `None`. The message names the field.

**How:** Parametrized over nine changes of the example axis. The test expects the error and
the message.

**Assumptions:** None.

#### `test_a_safe_axis_takes_a_sum_of_the_a_fields_within_0_001_of_1`

**Checks:** A sum of the `a` fields 0.0009 above or below 1 is valid, and one 0.0011 above or
below is not.

**How:** The test makes an axis with `a1` changed by 0.0009, and by -0.0009, and expects
`ValueError` for 0.0011 in both directions.

**Assumptions:** None.

#### `test_a_safe_hardware_refuses_a_name_that_is_not_a_str_and_an_axis_that_is_not_a_safe_axis`

**Checks:** `SafeHardware` raises `TypeError` for a name that is not a `str` and for an axis
that is not a `SafeAxis` (a namespace with the same fields), with the name of the axis.

**How:** The test makes the objects for the name and for each of `x`, `y` and `z`.

**Assumptions:** None.

#### `test_safe_hardware_values_compare_and_hash_by_their_fields`

**Checks:** Two `SafeHardware` made from equal values are equal and have one hash; a change of
one field of one axis gives a hardware that differs, while the other axes stay equal.

**How:** The test makes two from the example namespace, compares them and their hashes, and
makes a third with `dataclasses.replace` on `z`.

**Assumptions:** None.

#### `test_from_namespace_reads_the_fields_of_each_axis`

**Checks:** The nine fields of each axis and the name of a namespace are the fields of the
result; an extra field of the namespace or of an axis is ignored.

**How:** The test makes the example namespace with the name `MP_GPA_EXAMPLE`, an extra `checksum`
and an extra field on `y`, and compares `dataclasses.astuple` of each axis with the example
numbers.

**Assumptions:** None.

#### `test_from_namespace_takes_the_name_from_the_argument_then_the_namespace_then_unknown`

**Checks:** The name is the `name` argument, else the name of the namespace, else "unknown"; a
name that is not a `str` raises `TypeError`.

**How:** The test makes the four combinations of a name argument and a name of the namespace,
and one name argument that is an `int`.

**Assumptions:** None.

#### `test_from_namespace_refuses_a_bad_struct_and_names_the_field`

**Checks:** A namespace with no `x` or no `z`, with no `stim_thresh` of `x` or no `g_scale` of
`y`, with an `a` sum that is more than 0.001 from 1, a `stim_limit` of 0, a NaN and a string
raises the error of that defect, and the message names the axis and the field in the form of
the messages of `pns_levels` (`'x.stim_thresh' missing in the hardware struct`,
`hardware x.a1 + x.a2 + x.a3 must be 1`).

**How:** Parametrized over nine namespaces. The test expects the error and the message.

**Assumptions:** None.

#### `test_the_chunk_function_gives_the_values_of_the_formula_for_two_samples`

**Checks:** The percent of the y axis for the waveform `[g, g]` from the zero state equals the
SAFE formula written out in the test: three low-pass filters with `alpha = dt_ms / (tau +
dt_ms)` of the slew, of its absolute value and of the slew, weighted with `a1`, `a2` and `a3`,
divided by `stim_limit` and multiplied by `g_scale * 100`. The first sample is the difference
from 0, the second has a slew of 0 and the filters decay. The other axes are 0, `g_last` is
the last sample, and the filter state is a `(3, 3)` array.

**How:** The test calls the chunk function with `state=None` on two samples of 2.0 on `y`, and
computes the expected rows from the formula (relative 1e-12).

**Assumptions:** The value of the filter state is not checked: it is the internal state of
`scipy.signal.lfilter`.

#### `test_the_chunks_of_a_waveform_give_the_rows_of_the_waveform_in_one_chunk`

**Checks:** The chunks of a waveform, in order, with the state of each passed to the next,
concatenate to the result of one chunk, with the same final state. The chunks include one of 1
sample.

**How:** A random walk of 1000 samples in four chunks; `numpy.testing.assert_array_equal` for the
rows and for both parts of the final state.

**Assumptions:** The equality is exact: `lfilter` with an initial state does the same operations
for the samples of one chunk or of the next.

#### `test_the_chunk_function_gives_the_same_values_with_a_namespace_as_with_a_safe_hardware`

**Checks:** The chunk function reads only the attributes of the hardware, so a namespace and a
`SafeHardware` with the same values give the same rows.

**How:** The test compares the rows for 50 random samples (`assert_array_equal`).

**Assumptions:** None.

#### `test_the_example_numbers_of_these_tests_are_those_of_pypulseqs_example_hardware`

**Checks:** The numbers of `_EXAMPLE_AXES` are the numbers of `safe_example_hw()`.

**How:** `pytest.importorskip` of pypulseq's module; the test compares the nine fields of each
axis with `==`.

**Assumptions:** None.

#### `test_the_chunk_function_equals_pypulseqs_for_every_chunk_and_state`

**Checks:** The rows and the state of each chunk equal those of `_safe_gwf_to_pns_chunk` of the
pinned fork, exactly, for the example hardware and for hardware with other numbers in every
field (the filters differ, the `a` sum is 1), at the rasters 10 µs and 2.5 µs.

**How:** Parametrized over the hardware and the raster, with `pytest.importorskip`. A random
walk of 2000 samples goes through chunks of 1, 1, 698, 1 and 1299 samples; each function gets
the state that it returned.

**Assumptions:** The random walk is a waveform, not a gradient of a real sequence.

#### `test_the_hardware_check_accepts_and_refuses_what_pypulseqs_safe_hw_check_does`

**Checks:** `SafeHardware.from_namespace` accepts a namespace if and only if pypulseq's
`safe_hw_check` does: an `a` sum 0.0009 from 1 on `x` and `y` (valid), and 0.0011 from 1 on
`x` and `z`, a sum of 5.6, no `x`, no `y.stim_thresh` and no `z.g_scale` (not valid).

**How:** Parametrized over eight namespaces, with `pytest.importorskip`. A refusal of
`safe_hw_check` is a `ValueError` (or an `AttributeError`, for a namespace with no `x`); a
refusal of `from_namespace` is a `ValueError`.

**Assumptions:** `safe_hw_check` does not check that a field is finite, a number or above 0.
`from_namespace` does, and the test does not compare that.

#### `test_pns_levels_equals_the_levels_with_pypulseqs_chunk_function_exactly`

**Checks:** `_compute_levels` gives the same `PnsLevels` (`==`) with the package's chunk
function as with the pinned fork's `_safe_gwf_to_pns_chunk` in its place.

**How:** Parametrized over the four sequences of the comparison with `calculate_pns` and over
the default bin and bins of one sample, with `pytest.importorskip`. `_CHUNK_SAMPLES` is 1000,
so the state passes from chunk to chunk; two thresholds make intervals (the test checks that
some interval exists and that the peak is above 0). The first result is with the package's
function; `monkeypatch` then sets `_safe_gwf_to_pns_chunk` of `pulseq_analysis.pns_levels` to
the fork's, and the second result is compared with the first.

**Assumptions:** The sequences are the synthetic sequences, with the example hardware.

#### `test_safe_and_asc_import_neither_pypulseq_nor_matplotlib`

**Checks:** A new interpreter that imports `pulseq_analysis.safe` and `pulseq_analysis.asc`
has no module of `pypulseq` or `matplotlib` in `sys.modules`.

**How:** A subprocess runs the import and the check.

**Assumptions:** `pulseq_analysis.pns_levels` is not tested: it imports the snapshot, which
imports pypulseq, and `import pypulseq` imports matplotlib and
`pypulseq.utils.safe_pns_prediction` (checked on 2026-10-08).

#### `test_only_snapshot_extensions_and_seq_index_import_pypulseq`

**Checks:** Of the modules of `src/pulseq_analysis`, only `snapshot`, `extensions` and
`seq_index` have an `import` of pypulseq.

**How:** The test parses each file with `ast` and collects the modules that have an `import` or
an `import from` of a name that starts with `pypulseq`, in any scope.

**Assumptions:** A name that is imported with `importlib` is not found.
