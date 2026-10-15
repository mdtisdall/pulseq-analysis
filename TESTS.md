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
   the played gradients; the sequence index; the raster sampler; the gradient
   peaks; the kept PNS levels; the series; the analyses and their registry; the
   gradient spectrum; value equality; the kept results; the number arguments;
   the kept event points; the oracle of the gradient waveform; the `.asc` files; the
   snapshot; the names of the interface; the reader of Pulseq files; the C++ oracle;
   the SAFE hardware and filter; the decoded events; the decoding against the C++
   oracle; the decoding against MATLAB Pulseq; the sanitized C++ oracle; the "as
   written" reading; the plugin interpreters; a pypulseq sequence in memory; the
   scanner session; the imports of the package; the package without pypulseq; the
   documents
3. [The package pulseq-cpp-siemens](#3-the-package-pulseq-cpp-siemens): its API;
   the checks of undefined behaviour; the digests of the driver's output; the
   driver of the C++ oracle; the reader's shared state; the cases of undefined
   behaviour; the fuzzing of the checks; the interpreter `cpp-siemens`, alone and
   in the functions of pulseq-analysis

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
by default, and the package does not import pypulseq.

**How:** ruff checks every Python file in the repository. The project sets
the line length (100) and adds two rules to ruff's default set: TID251 with
`pypulseq` as a banned API (any import of it) and TID253 with `pypulseq` as a
banned module-level import. pypulseq is an optional dependency (the extra
`pypulseq`), so `src/` must not import it. The per-file ignores turn both off
for `tests/**`, `packages/*/tests/**` and `scripts/**`, which run with the
`dev` group, and TID251 for `src/pulseq_analysis/seqfile/from_pypulseq.py`,
which may import pypulseq inside a function (it does not). E402 (an import
after code) is off for `tests/**`, for the header of a test module that needs
pypulseq (see [Tests without pypulseq](#tests-without-pypulseq)). `uv.lock`
has ruff 0.16.9.

**Assumptions:**

- Apart from the two rules, the rule set is ruff's default, not a choice that
  the project makes. The project does not pin ruff in `pyproject.toml`, so an
  update of ruff in `uv.lock` can add or remove rules.
- A name imported with `importlib` is not found by ruff. `test_imports.py`
  (section 2.30) finds a module that imports pypulseq when it is imported,
  and `test_without_pypulseq.py` (section 2.31) runs the package without it.
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

### Tests without pypulseq

**Checks:** The tests that do not need pypulseq pass in an environment
without it, and each test that needs pypulseq says so.

**How:** After the pytest run of the dev environment, `scripts/check` runs
`uv run --no-dev --isolated --with pytest pytest -q -m "not pypulseq" tests`:
an environment with the package, its dependencies (numpy and scipy) and pytest,
and without the `dev` group, so without pypulseq. `pyproject.toml` declares the
markers `pypulseq` and `cpp_oracle`, and pytest runs with `--strict-markers`,
so a misspelt marker fails. A test that needs pypulseq, directly or through
a builder of `synthetic.py` or `scale_sequences.py`, has the marker (on the
test, or on one parameter, with `pytest.param(..., marks=...)`), and
`-m "not pypulseq"` leaves it out. These helpers, `tests/oracles/blocks.py`
and the test modules with tests both with and without pypulseq take `pp` from
`tests/optional_pypulseq.py`: pypulseq when it is installed, and otherwise a
stand-in whose attributes are stand-ins and whose call raises `ImportError`
("needs the `pypulseq` marker"). So these modules import without pypulseq,
and their other tests run. A module whose tests all need pypulseq (for example
`test_grad_peaks.py`, `test_sampling.py`, or a module that imports
`gap_sequences.py`, `random_gaps.py` or the waveform and spectrum oracles)
starts, after its docstring, with `pytestmark = pytest.mark.pypulseq` and
`pytest.importorskip("pypulseq")`, before its other imports: without pypulseq,
the module is skipped. `tests/conftest.py`, `tests/pns_hardware.py` and the
constants of `synthetic.py` do not need pypulseq: the example SAFE hardware of
the tests is `synthetic.safe_example_hw()`, `synthetic.EXAMPLE_HW` and
`pns_hardware.EXAMPLE_HARDWARE`, with the numbers of pypulseq's
`safe_example_hw()`, which a test of section 2.21 checks. Without pypulseq,
`synthetic.SYSTEM` is a stand-in too. The modules of the C++ oracle have the
marker `cpp_oracle`.

**Assumptions:**

- The guard: a module that imports pypulseq directly without the marker and
  the `importorskip` fails its collection in this run, and a test without the
  marker that calls pypulseq through `optional_pypulseq` fails with its
  `ImportError`. A test that only reads an attribute of the stand-in (no call),
  for example in a comparison, fails on its assertion instead.
- The dev environment pins pypulseq from the fork (`[tool.uv.sources]`), and
  the tests with the marker run only with the fork. No check runs the tests
  with a pypulseq release.
- The tests of `packages/pulseq-cpp-siemens` are not run without pypulseq:
  their environment has pulseq-analysis with its extra `pypulseq`.

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
  test selection (no `-k`), so the file of test IDs lists every test. The
  IDs of the tests of `packages/pulseq-cpp-siemens` (section 3) are added to
  the same file by a `pytest --collect-only` in the package's environment;
  without `--collected`, the check collects them the same way when that
  environment exists. The environment of the root project does not install
  pulseq-cpp-siemens, so the tests of the package are collected in its own
  environment only. That environment has pulseq-analysis (its group
  `analysis`), so it collects the two modules of the interpreter `cpp-siemens`
  (sections 3.8 and 3.9); they are not collected without it.
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

**How:** The test imports each module and subpackage of `pulseq_analysis` with
`pkgutil.walk_packages` and `importlib`. For each module, it checks the names
in `dir(module)`. It then takes each function and each method of each class
that the module defines, private ones too, and checks the names of the
parameters that `inspect.signature` gives. It skips the objects with a `__module__` outside the
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
measurements use to read the decoded gradient events: `gradient_offsets` and
`gradient_points`, the gradient corner/sample helpers.

#### `test_time_tolerance`

**Checks:** The time tolerance of `seq_utils` is 1 ns.

**How:** The test compares `seq_utils.TIME_TOLERANCE` with 1e-9.

**Assumptions:** The test checks a constant of the package (the tolerance of a comparison of
two times), not a calculation. It needs no pypulseq.

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

#### `test_gradient_points_matches_gradient_offsets_exactly`

**Checks:** `gradient_points(g, t0)` gives exactly `(t0 + delay) + offsets`
for the `delay` and `offsets` that `gradient_offsets(g)` returns, for both a
trapezoid and an arbitrary gradient. This is the relationship a later phase
depends on to rebuild point times from the stored offset tables.

**How:** The test is parametrized over a trapezoid and an arbitrary gradient: the decoded events 1
(trapezoid) and 3 (arbitrary) of `tests/seqfiles/valid_1_5_1.seq`, decoded with
`decode_gradients(seqfile.read_seqfile(...))`, not pypulseq events. For each, it calls `gradient_points` with a non-zero `t0` and
`gradient_offsets` on the same event, then compares the two with
`numpy.testing.assert_array_equal` — exact equality, not a tolerance.

**Assumptions:**

- Bit-for-bit equality is the right check here, not an approximation: the
  point in this test is that `gradient_points` is defined in terms of
  `gradient_offsets` with no room for a rounding difference to creep in.

#### `test_gradient_offsets_of_a_decoded_trapezoid`

**Checks:** `gradient_offsets` accepts an `events.Trapezoid` and gives its delay, its four corner
offsets and its amplitudes.

**How:** The test decodes trapezoid 1 of `valid_1_5_1.seq` and compares the delay, the offsets (the
running sum of 0, the rise, flat and fall times) and the amplitudes (0, the amplitude twice, 0)
exactly with the numbers of the file.

**Assumptions:** None.

#### `test_gradient_offsets_of_a_decoded_arbitrary_gradient`

**Checks:** `gradient_offsets` accepts an `events.ArbitraryGradient` with time ID 0, a time shape or
time ID -1. It gives the event's delay, and its samples with `first` at offset 0 and `last` at
`shape_dur`.

**How:** For gradients 3, 5 and 6 of `valid_1_5_1.seq` (parametrized), the test compares the offsets
with `tt` between 0 and `shape_dur`, and the amplitudes with `waveform` between `first` and `last`,
exactly.

**Assumptions:** The values of the decoded events are checked by `test_decoding.py`.

### 2.2 PNS levels (`test_pns_levels.py`)

`test_pns_levels.py` tests `pns_levels.py`: `pns_levels`, which keeps its result for the
snapshot (section 2.7 tests the keep) and, for a result that is not kept, calls
`_compute_levels`, which samples the gradients block by
block (`GradientSampler.block_samples`), runs the SAFE model of `safe.py`
(`_safe_gwf_to_pns_chunk`, ported from pypulseq's SAFE model) over them in chunks, and keeps only the stored level
(the minimum and the maximum of the total in fixed time bins) and the summary (the
peak, the peak time and the axis peaks), and the intervals of consecutive samples
whose total is at or above each threshold of the `thresholds_hz_per_t` argument
(`PnsInterval`, `PnsLevels.above`, a dict with one key for each threshold; the default is
no threshold); and `bin_samples_for`, which picks the bin size. A PNS value of
`pns_levels` is in Hz/T: the fraction of the stimulation limit times the magnitude of
gamma, because the model runs on the Hz/m samples and reads no gamma. The test file
defines `_LIMIT = GAMMA_1H`, the stimulation limit for 1H in Hz/T (a fraction of 1 times
`GAMMA_1H`), and gives a
threshold or a comparison as a fraction times `_LIMIT`.

The reference of the values is the SAFE model of the oracle samples (`_oracle_model` of the test
file): the package's own `_safe_gwf_to_pns_chunk` in one chunk, with the example hardware, on the
samples of the oracle of the gradient waveform (`tests/oracles/waveform.py`, the model of MATLAB
Pulseq) of `sequence_of(snap)`: `oracle.block_samples` at the gradient raster for a sequence on
the raster, and `oracle.sample` at the file times `(k + 0.5) * dt`, `k < num_samples`, for one
that is not. The values are the percent times 0.01 and the total is `sqrt(sum of squares)`, as
`pns_levels` computes them, in Hz/T, so no gamma is divided. The filter is the same as that of
`pns_levels`, and section 2.21 checks it against the golden values of pypulseq's fork; the
reference tests the samples, the chunks, the bins, the peak search and the summary of
`pns_levels`. The oracle reads the gradients as the snapshot plays them, so the rounding of the
written file is not in a difference, and the tolerances are tight: a relative 1e-9 for the
peaks, and for a bin a relative 1e-6 (the float32 cast) and an absolute 1e-12 of the peak (the
rounding residue of a sample that is 0). The sequences with an end that is not 0 next to a gap,
which `spec` rejects, have the same comparison in section 3.10
(`test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`).

A second call of `pns_levels` with the same snapshot and the same arguments gives the
kept object. Each test makes its snapshot with `analyses.load`, which reads the written text of a
pypulseq sequence through an interpreter (`spec`; the test of a sequence that `spec` rejects is in
section 3.10 and loads it with `cpp-siemens`). The oracles read `sequence_of(snap)` (`tests/oracles/blocks.py`), the gradients as the
snapshot plays them. A sequence with a block
of 1.5 raster times has a block duration raster of 1 µs (`_add_a_delay`), because pypulseq's writer
refuses a block duration that is not a whole number of block raster times; `spec` reads that file. A test that changes `_CHUNK_SAMPLES` or `MAX_BINS` (the kept result would hide
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

#### `test_summary_is_the_safe_model_of_the_oracle_samples`

**Checks:** For a spin echo, a gradient echo, an arbitrary gradient, and a
hand-made "border" sequence (two extended-trapezoid blocks whose gradient is not
zero at the block border between them), `pns_levels`'s peak, peak time and axis
peaks equal those of the SAFE model of the oracle samples (`_oracle_model`, example
hardware). Also checks `reason`, `hardware`, `dt_s` and `on_raster` for the
example-hardware, on-raster case.

**How:** Parametrized over `spin_echo_sequence()`, `gre_sequence()`,
`arbitrary_gradient_sequence()` and `synthetic.border_sequence()` (two
`pp.make_extended_trapezoid` blocks on x, the second continuing the first's
amplitude with no step, so `add_block` accepts the junction). `_assert_summary_is_the_model`
checks `num_samples` against the length of the model, the peak and the axis peaks with a
relative 1e-9 (the axis peaks also with an absolute 1e-12 of the peak), and the peak time
against the centre of the first sample of the model at or above `peak * (1 - PEAK_TOLERANCE)`
(as `PnsLevels.peak_time_s`), with an absolute 1e-12 s.

**Assumptions:** None of these sequences has two samples close enough together, in value, to
flip which one the tolerance-based peak-time search finds first.

#### `test_stored_bins_are_the_extremes_of_the_model_totals`

**Checks:** Each stored bin's minimum and maximum equal the minimum and the maximum of the
totals of the SAFE model of the oracle samples (`_oracle_model`) over the same samples, for
every bin, for the same four sequences.

**How:** Same parametrization as `test_summary_is_the_safe_model_of_the_oracle_samples`, with
`bin_s` of 7 raster times, so that each sequence has more than one bin and the last bin is
shorter. The reference of bin `i` is the minimum and the maximum of the model's totals from
sample `i * bin_samples` to the next bin or the end. `numpy.testing.assert_allclose` compares
`level_min_hz_per_t` and `level_max_hz_per_t` with them, with `rtol=1e-6` (the stored bins are
float32, cast outward) and `atol` of 1e-12 of the peak, and the test checks that the number of
bins is the number of references.

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
`pulseq_analysis.analyses.pns_levels.MAX_BINS` to 50 with `monkeypatch`, calls again with the
same arguments, checks that the result is not the object of the first call, and compares. A last
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
`monkeypatch.setattr` sets `_CHUNK_SAMPLES` of `pulseq_analysis.analyses.pns_levels` to it and
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

**How:** Parametrized over the four sequences of
`test_summary_is_the_safe_model_of_the_oracle_samples`. The test calls `_compute` (no keep)
with the namespace pair `EXAMPLE_HW` and with the `SafeHardware`
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
`on_raster=False`, and its peak, peak time and axis peaks equal those of the SAFE model of the
oracle samples at the file times `(k + 0.5) * dt` (`_oracle_model`).

**How:** A trapezoid on x followed by a delay block of 1.5 raster
times (pypulseq's `add_block` accepts this duration, though it is not a whole number of raster
steps; the sequence has a block duration raster of 1 µs so that the writer accepts it). The test
checks `on_raster` and then `_assert_summary_is_the_model`, as in
`test_summary_is_the_safe_model_of_the_oracle_samples`.

**Assumptions:** None.

#### `test_an_off_raster_sequence_of_many_chunks_does_not_depend_on_chunk_samples`

**Checks:** An off-raster sequence of more than three chunks gives the result of one
chunk (`==`, each field and each interval), and its `num_samples` is
`ceil((end_s - 1e-10) / dt)`, with `end_s` the end of `sequence_index(snap)`. A chunk
that reads the samples of the first chunk again, or a `num_samples` that rounds down,
gives another result.

**How:** `gre_sequence(num_trs=3)` and then a delay block of 1.5 raster times (block duration raster of 1 µs), so that the
sequence is not on the raster. The hardware gives a peak of 1.5 times `_LIMIT`
(`hardware_for_peak` of `tests/pns_hardware.py`), and `thresholds_hz_per_t=(_LIMIT,)`. Both
calls are `_compute` calls (`_compute_levels`). `monkeypatch` sets
`_CHUNK_SAMPLES` to `10**9` for the reference (one chunk) and to 1 (a chunk of one bin)
for the second call. The test checks that the second result is not the object of the
reference, `on_raster is False`, more than three chunks, an
interval above `_LIMIT`, `got == reference`, and `num_samples`.

**Assumptions:** The sequence has an interval above `_LIMIT`.

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

**How:** A trapezoid on x (area 500) and four delay blocks of 1.5 raster times (6 steps
together; block duration raster of 1 µs). `whole` is the duration of the trapezoid in steps plus 6. The test checks
`round(end_s / dt) == whole`, `end_s / dt > whole` and `(end_s - 1e-10) / dt <= whole`,
with `end_s` of `sequence_index(snap)`. Then it calls `pns_levels` with `EXAMPLE_HW` and
checks `on_raster is False` and `num_samples == whole`.

**Assumptions:** `end_s / dt` is 67.00000000000001 for this sequence (the sum of the block durations of the
written file, which are whole numbers of µs; the first version of the test, with a trapezoid of area 1000
and two delays, has 105.99999999999999 for the file and is not above the whole number). The test fails at
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
`monkeypatch.setattr` sets `_CHUNK_SAMPLES` of `pulseq_analysis.analyses.pns_levels` to 1, to that
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
`_CHUNK_SAMPLES` of `pulseq_analysis.analyses.pns_levels`), the call with both thresholds must
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

#### `test_the_levels_divided_by_the_gamma_of_the_system_are_the_fractions_of_the_limit`

**Checks:** For a sequence whose `seq.system.gamma` is not the gamma of 1H, the peak and
the axis peaks of `pns_levels`, divided by `seq.system.gamma`, are the fractions of the
stimulation limit: those of the SAFE model of the oracle samples in T/m. Its peak time is that of
the model. The peak divided by the gamma of 1H does not equal it. Thus the conversion of
`docs/usage.md` section 9 uses the gamma of the caller.

**How:** The sequence of `waveform_sequence` (`tests/synthetic.py`) with a copy of `SYSTEM` with
`gamma = 0.9 * SYSTEM.gamma`. The reference is `_oracle_model` with each sample divided by
`seq.system.gamma` (T/m), so its values are fractions (the percent times 0.01).
`_assert_summary_is_the_model` compares the values of `pns_levels` divided by
`seq.system.gamma` with it, as in `test_summary_is_the_safe_model_of_the_oracle_samples`. The
test also checks that `peak_hz_per_t / GAMMA_1H` is not within a relative 1e-5 of the reference
peak.

**Assumptions:** The model is linear in the samples, so the division by gamma of the samples
and of the values give the same fractions. The two gammas give peaks that differ by more than
the tolerance (a factor of 0.9 does).

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

### 2.3 The played gradients (`test_played.py`)

`test_played.py` tests `synth/_played.py`: the gradient event of each block and axis that the
measurements take from the decoding of a snapshot (`docs/implementation.md`, section 1.2). The
measurements join the points with straight lines, and the decoding's `gradients_at` is the
waveform of each interpreter. The fixtures are every file of `tests/seqfiles`. The interpreters
are `spec` and the fake plugin `test_snapshot.Unrotated` (section 2.17); the same checks through
`cpp-siemens` and its settings are in the plugin's tests (section 3.11), which import
`check_the_points_are_the_gradients` and `load_or_none` from this module. The fake plugin
`Doubled` (in this module) decodes the gradients of one block otherwise, and says so with
`gradient_variants`, for the tests of the variants. The fake plugin `Late` (in this module) plays
the events of one block wholly after the end of the block, or with all their points at one time.
The fake plugin `OneNaN` (in this module) gives one point of the event of one block NaN, for the
rule of a NaN in the peaks; its check, `check_a_nan_of_one_block_is_credited_to_its_first_nan`, is
imported by the tests of `bad_syntax_number.seq` through `cpp-siemens` (section 3.10).

#### `test_the_points_of_the_played_events_are_the_gradients_of_the_decoding`

**Checks:** On each fixture that the interpreter reads, the straight lines between the points of
each block's played events equal `gradients_at` of the decoding, at the middle of each segment
and at each point that is not a step, to 1e-7 of the largest value of the file
(`check_the_points_are_the_gradients`).

**How:** Parametrized over every fixture and two interpreters: `spec` and the fake plugin
`Unrotated` (its decoding gives `spec`'s events through the protocol `Decoding`, with the
rotations left unapplied). A fixture that the interpreter rejects is skipped. For each block and
axis with an event, the check takes the middle of each segment of positive length (the mean of
its two values) and each inner point whose neighbours are at other times, and reads
`gradients_at` of the decoding at the same blocks and times (µs). A NaN of the file must be NaN in
both. The rest must agree to 1e-7 times the largest value (at least 1).

**Assumptions:**

- The tolerance covers the float32 rounding of a plugin that holds float32 values (`cpp-siemens`,
  D7.2): there the points hold the float32 product of the amplitude and a sample, and
  `gradients_at` interpolates the samples before the product, in double.
- The rotated blocks of `spec` (from 1.5.1) are made from `gradients_at` itself, so for them the
  test checks the step and the end handling of `_played`, not an independent decoding.
- The points of a step (two points at one time) and the ends of an event are not probed: there
  the value of `gradients_at` depends on the side.

#### `test_each_variant_of_a_gradient_event_has_its_own_key_and_its_own_points`

**Checks:** When the decoding says that a gradient event decodes otherwise in one block
(`gradient_variants`), the played gradients give that block a new key, above the largest file
ID, with the points of the event in that block, and the other blocks keep the file ID, with the
points of the first block that plays it.

**How:** The fake plugin `Doubled` (`spec`'s model and decoding, with the gradients of block 1
twice as large in `gradient_points` and `gradients_at`, and the variant 1 at the cells of block 1
with an event) reads `oracle/koma_v1.4_gr-trapezoidal.seq`, whose nine blocks each play the
trapezoid 1 on gx. The test checks that `gx` of block 1 is above 1, that the other blocks have 1,
and that the points of the two keys equal `gradient_points` of block 1 and of block 0, bit for
bit. Then `check_the_points_are_the_gradients` runs on the file through `Doubled`.

**Assumptions:** A variant in one block of a file whose blocks all play one event stands for the
case of the C++ reader (the buffer of the gradients of a block), which the plugin's tests check
(section 3.11).

#### `test_a_block_that_the_session_rotates_takes_the_points_of_its_variant`

**Checks:** When the session's field of view rotates every block, so that the played gradients of
each block come from `gradients_at` (`_from_gradients_at`), the block with the variant gets keys
of its own, with twice the values of block 0, and the played points are the gradients of the
decoding.

**How:** `Doubled` reads the same file under `Session(fov_rotation=...)` with 90 degrees about z,
which takes gx to y. The test checks that the keys of `gy` of blocks 0 and 1 differ, and that the
values of the points of block 1 are twice those of block 0, to 1e-7 of their largest value. Then
it compares the straight lines of the points with `gradients_at` of the decoding at the probes of
`check_the_points_are_the_gradients` (`_probes`), to the same tolerance.

**Assumptions:** None.

#### `test_an_event_wholly_after_the_end_of_its_block_has_two_points_or_more`

**Checks:** When the decoding plays the events of a block wholly after the end of the block, each
played event of that block has 2 points or more, and the played points are the gradients of the
decoding; also when the session's field of view rotates the block, so that it has an event on
each axis from `gradients_at` (`_from_gradients_at`).

**How:** The fake plugin `Late` (`DoubledDecoding`'s variants and rotation record, with
`spec`'s gradients, except in block 1: there the delay of each event in `gradient_points` is
longer by twice the duration of the block, and `gradients_at` is 0 on each axis) reads
`oracle/koma_v1.4_gr-trapezoidal.seq`. Parametrized over no session and
`Session(fov_rotation=...)` with 90 degrees about z. For each axis of block 1 with a played
event, the test checks that its points have 2 offsets or more. Then it compares the straight
lines of the points with `gradients_at` of the decoding at the probes of
`check_the_points_are_the_gradients` (`_probes`), to 1e-7 of the largest value (at least 1).

**Assumptions:** `spec` rejects a file with such an event (`block.event-too-long`), so only a
plugin plays one; the case of `cpp-siemens` is in the plugin's tests (section 3.11).

#### `test_an_event_that_starts_at_the_end_of_its_block_has_two_points_or_more`

**Checks:** When the events of a block start at the end of the block, or the block lasts 0 s and
its events start at its start, each played event of that block has 2 points or more, from the
start of the block to its end, the per-block peak of the measurements is 0 there, and the played
points are the gradients of the decoding; also when the session's field of view rotates the
block.

**How:** The fake plugin `Late` with `shift=1.0` (the delay of each event of block 1 is longer by
the duration of the block) and with `duration_s=0.0` (block 1 lasts 0 s in `block_durations`, so
its trapezoid starts at the end of the block), on `oracle/koma_v1.4_gr-trapezoidal.seq`;
parametrized over these two and over no session and `Session(fov_rotation=...)` with 90 degrees
about z. For each axis of block 1 with a played event, the test checks that its points have 2
offsets or more, that its delay is 0 and that its last offset is the duration of the block. It
checks that `block_gradient_values` gives a peak of 0 in block 1 on each axis, and compares the
straight lines of the points with `gradients_at` of the decoding at the probes of
`check_the_points_are_the_gradients` (`_probes`), to 1e-7 of the largest value (at least 1).

**Assumptions:** With duration 0 the event has two points at time 0, and `_probes` has no probe
in that block; the check there is that the measurements take the event.

#### `test_a_block_whose_event_has_length_0_has_two_points_or_more_through_spec`

**Checks:** Through `spec`, when the one event of a block has all its points at one time inside
the block (a trapezoid of length 0) and the block is read through `gradients_at`, each played
event of the block has 2 points or more, the played points are the gradients of the decoding,
and `gradient_peaks` runs. The block goes through `gradients_at` because the session's field of
view rotates it, or because its rotation object does (`spec` from 1.5.1).

**How:** The test writes `valid_1_5_1.seq` to `tmp_path` with the `[TRAP]` row 1 changed to
`1 1000000 0 0 0 100` (rise, flat and fall times 0, delay 100 µs) and block 2 (play index 1)
changed so that this trapezoid on gx is its only event (`_length_0_file`). Two cases: no
extension in block 2 and `Session(fov_rotation=...)` with 90 degrees about z; and the extension
list 3 of the file in block 2 (its rotation object 1, 45 degrees about z), with no session. For
each axis of block 1 with a played event, the test checks that its points have 2 offsets or more,
then compares the straight lines of the points with `gradients_at` of the decoding at the probes
of `check_the_points_are_the_gradients` (`_probes`), to 1e-7 of the largest value (at least 1)
(`_check_block_1_has_two_points_or_more`), and calls `gradient_peaks`.

**Assumptions:** `spec` reads the changed file. With no rotation of block 2 the block keeps its
decoded event, so the test has no unrotated case.

#### `test_an_event_of_length_0_alone_in_its_block_has_two_points_or_more`

**Checks:** When a plugin's decoding plays the one event of a block with all its points at one
time inside the block, each played event of that block has 2 points or more and the played
points are the gradients of the decoding, with and without a rotation of the field of view, and
`gradient_peaks` runs.

**How:** The fake plugin `Late(shift=0.5, length_0=True)` reads
`oracle/koma_v1.4_gr-trapezoidal.seq`: in block 1 the trapezoid 1 on gx has the offsets 0 and its
delay half the duration of the block, and `gradients_at` is 0 in the block. Parametrized over no
session and `Session(fov_rotation=...)` with 90 degrees about z. The checks are those of
`_check_block_1_has_two_points_or_more`, then `gradient_peaks` is called.

**Assumptions:** With no session the block is not read through `gradients_at`: its event is the
decoded one, with its 4 points at one time.

#### `test_an_event_of_length_0_at_the_end_of_a_block_that_the_session_rotates_has_two_points`

**Checks:** When the one event of a block has all its points at the end of the block and the
session's field of view rotates the block, each played event of that block has two points, at
the start and at the end of the block, the played points are the gradients of the decoding, and
`gradient_peaks` runs.

**How:** The fake plugin `Late(shift=1.0, length_0=True)` reads
`oracle/koma_v1.4_gr-trapezoidal.seq` under `Session(fov_rotation=...)` with 90 degrees about z:
in block 1 the trapezoid 1 on gx has the offsets 0 and the delay of the duration of the block.
The checks of `_check_block_1_has_two_points_or_more`, then for each axis of block 1 the delay 0
and the offsets `[0, duration]`, bit for bit, then `gradient_peaks`.

**Assumptions:** `Late`'s `gradients_at` is 0 in the whole of block 1, so the test does not tell
whether the end of the block is a step; it checks the times of the points.

#### `test_blocks_with_the_same_events_and_duration_are_planned_once`

**Checks:** When `spec` rotates blocks with the same events and duration by different rotations,
`_played` makes one plan of the times of their points (`_plan`) for all of them, not one for each
rotation. Each block keeps keys of its own, and the played points are the gradients of the
decoding.

**How:** The test writes a 1.5.1 file to `tmp_path` (`ROTATED_READOUTS`): five blocks of 400 µs,
each with the trapezoid 1 on gx and the ADC 1, and each with its own rotation object, k times 36
degrees about z for k from 1 to 5. `_played._plan` is replaced (`monkeypatch`) by a wrapper that
counts its calls. The test reads the file through `spec`, takes `played_gradients`, and checks
that `gx` has five distinct keys and that `_plan` ran once. Then
`check_the_points_are_the_gradients` runs on the file through `spec`.

**Assumptions:** `_from_gradients_at` calls `_plan` through the module, so the wrapper sees each
call. The values of rotated blocks with the same events and different rotations are also checked
on `oracle/pulseq_make_radial.seq` and `oracle/koma_v1.5_rotation_radial_tiny.seq`, by
`test_the_points_of_the_played_events_are_the_gradients_of_the_decoding`.

#### `test_a_nan_point_of_a_block_is_credited_to_the_block_at_its_first_nan`

**Checks:** When the decoding gives one point of the event of a block NaN, `gradient_peaks` and
`block_gradient_values` follow the rule of a NaN in the peaks (a NaN propagates), for a decoded
event and for the events of a block read through `gradients_at`. On each axis with the NaN, the peak, the slew and the RMS of the file are NaN, credited to that
block, the peak at the time of its first NaN point and the slew at the start of its first NaN
segment; the vector peak of the block and of the file is NaN at the first time at which the
vector is NaN. Every other value is the value of the same decoding with no NaN.

**How:** The fake plugin `OneNaN` reads `oracle/koma_v1.4_gr-trapezoidal.seq` (the trapezoid 1
on gx in each block): in block 1 the point 1 of the event, the end of the rise, is NaN, and its
`gradients_at` is NaN strictly between the points 0 and 2 of the event. `OneNaN(nan=False)` is the
same decoding with no NaN. Parametrized over no session (the event of block 1 is decoded, the NaN
on x) and `Session(fov_rotation=...)` with 90 degrees about z (every block is read through
`gradients_at`, and the fake gives NaN on every axis, as a rotation of a NaN does). The check
`check_a_nan_of_one_block_is_credited_to_its_first_nan` compares:
- `gradient_peaks`: on each NaN axis, a NaN peak, slew and RMS, with the block ID of block 1 for
  the peak and the slew, the peak at 1.06 ms and the slew at 1 ms; the other axes equal those of
  the clean decoding; a NaN vector peak at 1.06 ms in block 1.
- `block_gradient_values`: in block 1 on each NaN axis, a NaN peak at 1.06 ms and a NaN slew at
  1 ms; the vector peak of block 1 NaN at 1.06 ms; every value of the other blocks, and of the
  other axes and the junctions of block 1, equal to the clean decoding.
The times agree to `TIME_TOLERANCE`; the other values are compared exactly.

**Assumptions:** Block 1 starts at 1 ms, and its trapezoid has the delay 0 and rises in 60 µs. At
the start of block 1 the polyline of gx is 0 on both sides (a zero gap from the event of block 0),
so the vector is NaN first at the NaN point. The test does not cover a NaN at the first or the last
point of an event (a step), or a NaN in a gap.

### 2.4 Sequence index (`test_seq_index.py`)

`test_seq_index.py` tests `seq_index.py`: the dense RF, gradient and ADC event numbering of
`sequence_index`, its block times, its dtypes and its keep for a snapshot. The
reference numbering, `_reference_index`, is a plain loop over the blocks with one dict
for each event kind: the loop that `diagram_data.diagram_tables` had before it used the
index. Its `*_first` arrays hold play indexes, as `SequenceIndex` does (the old loop
kept block ids). The tests load `build_repeating` and `build_worst` from
`tests/scale_sequences.py`. The functions take a `Snapshot`, which `analyses.load` makes. The
reference reads the stand-in of the oracles (`oracles.blocks.sequence_of(snap)`), whose rows
are the played gradient events of the snapshot.

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
g2, gy g3, ADC a2) and (e1, g1 on gx, a1). It checks the IDs of the file in the block table
of the snapshot (`snap.data.blocks`), and that the file has three trapezoids,
first (RF 2, 1, 2, gx 0, 2, 3, gy 0, 1, 0, gz 3, 0, 0, ADC 2, 1, 2), so the order differs
from the first use. Then it checks the dense columns against the hand-worked values (`rf`
1, 2, 1, `gx` 0, 2, 1, `gy` 0, 3, 0, `gz` 1, 0, 0, `adc` 1, 2, 1), the `*_first` arrays,
`_assert_index_matches_reference`, and the amplitudes of the decoded events of `spec` at the
file IDs of the dense numbers (`_dense_ids`): 1e5, 2e5, 3e5.

**Assumptions:** The registration of an event before `add_block` gives the event its
library id, and `add_block` finds the same event again; pypulseq's writer keeps the IDs
(the test checks them in the file).

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

**Checks:** A file with an event ID of 10^8 builds its index (with the played gradients) with a
`tracemalloc` peak below 100 MB, and its dense numbers are as for small IDs.

**How:** A sequence of three blocks with a trapezoid on x (the first and the third are the same
event) is written with no signature, and the second trapezoid gets the ID 10^8 in `[BLOCKS]` and
`[TRAP]` of the text. The test loads the file with `spec`, checks the gx IDs (1, 10^8, 1), measures
`sequence_index` with `tracemalloc`, and checks `gx` (1, 2, 1) and `grad_first` (0, 1). A lookup
table over the IDs would take 800 MB.

**Assumptions:** `tracemalloc` sees the numpy allocations.

#### `test_start_s_is_the_sequential_sum_and_end_s_is_its_final_value`

**Checks:** `index.start_s` is the sequential sum of the block durations from 0.0,
`index.end_s` is that sum's final value, and `index.duration_s` is the block durations
of the file in play order.

**How:** The test builds `build_repeating(50)`, computes `sequence_index(snap)`, and
independently walks `seq.block_events.keys()` of `sequence_of(snap)` with a running total `t` (starting at
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

**How:** Parametrized over five sequences: the synthetic spin echo; one `make_trapezoid` block
on x, on y and on z; and one delay block. The test checks
`has_gradients(sequence_index(snap)) is expected`: True for the first four, False for the last.

**Assumptions:** None.

#### `test_has_gradients_is_false_for_a_file_with_no_blocks`

**Checks:** `has_gradients` is False for the index of a model with no block.

**How:** The snapshot of the model of `valid_no_signature.seq` through `spec`, with its block
table replaced by an empty one (`spec` rejects a file with no block, `blocks.empty`, and
pypulseq's writer cannot write a sequence with no block; the plugin's tests read
`bad_blocks_empty.seq` through `cpp-siemens`, section 3.11).

**Assumptions:** None.

#### `test_sequence_index_of_a_sequence_with_no_blocks`

**Checks:** `sequence_index` of a model with no block has `num_blocks` 0, `end_s` 0.0, and every
array (`block_id`, `start_s`, `duration_s`, `rf`, `gx`, `gy`, `gz`, `adc`, `rf_first`,
`grad_first`, `grad_first_axis`, `adc_first`) empty.

**How:** The snapshot with an empty block table (as above); the test checks `num_blocks`,
`end_s`, and the size of each of the twelve arrays.

**Assumptions:** None.

#### `test_a_function_of_the_index_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `sequence_index` raises `TypeError` with a message that names `load` when its first
argument is a `pp.Sequence` or a path, and not a `Snapshot`.

**How:** Parametrized over a `gre_sequence()` and the path string `"sequence.seq"`. The call
must raise `TypeError` with `match="load"`.

**Assumptions:** The path `"sequence.seq"` is not read: the type check comes before any read.

#### `test_sequence_index_is_kept_for_one_snapshot_and_made_again_for_another`

**Checks:** `sequence_index(snap)` returns the same object on a second call for the same
snapshot, and a snapshot made again from the same sequence gives its own, equal index.

**How:** The test builds `gre_sequence()` and makes a snapshot with `load`. Two calls of
`sequence_index` must give the same object (`is`). The index of a second snapshot of the
same sequence must be another object (`is not`) and equal (`==`) to the first.

**Assumptions:** `SequenceIndex` compares by value (tested by
`test_two_indexes_of_two_equal_sequences_are_equal_and_not_hashable`).

#### `test_the_index_of_a_snapshot_is_the_index_of_its_model_for_each_file`

**Checks:** For each file of `tests/seqfiles` (`valid_*.seq` and `oracle/*.seq`) that `spec`
reads, and whose blocks all play the events of the file (no block whose gradients come from
`gradients_at`: a rotation applied, or an event after its block's end), `sequence_index` of the
snapshot equals `seq_index._index_from_data` of its model
(`check_the_index_of_a_snapshot_is_the_index_of_its_model`, which the plugin's tests run for
`cpp-siemens`).

**How:** A file that `spec` rejects is skipped; so is a file whose played gradient columns have a
key above the largest file ID (`test_played.py` covers those). The two indexes are compared by
`==`; at least 15 files are compared.

**Assumptions:** None.

#### `test_the_index_from_the_columns_of_a_sequence_equals_its_index`

**Checks:** `seq_index._index_from_columns`, called with the block IDs, the durations and the event
columns of the sequence of a snapshot, equals `sequence_index` of the snapshot.

**How:** Parametrized over the synthetic spin echo, gradient echo, empty and arbitrary-gradient
sequences. The test reads `block_events` and `block_durations` of `sequence_of(snap)` itself
(the IDs as uint32, the durations as float64, the event columns as int64) and compares
the result with `sequence_index(snap)` by `==` of the value dataclass.

**Assumptions:** None.

#### `test_dense_ids_are_the_file_ids_of_the_first_use_by_hand`

**Checks:** `seq_index._dense_ids` gives, for each dense RF, gradient and ADC index, the file ID of
its event at its first use, as int64. The dense gradient columns of `_index_from_data` share one
index space across the three axes.

**How:** The test replaces the block table of the model of `valid_1_5_1.seq` (with
`dataclasses.replace`) with a hand table of 5 blocks, in which the event IDs are not in their order
of first use and gradient 5 is used on gz and then on gy. It compares with hand values: RF IDs
`[3, 1]`, gradient IDs `[5, 2, 7]`, ADC IDs `[4, 2]`, and the dense columns `gx` `[0, 2, 0, 3, 0]`,
`gy` `[0, 1, 0, 0, 0]` and `gz` `[1, 0, 0, 2, 0]`.

**Assumptions:** `_dense_ids` and `_index_from_data` read only the block table and the durations, so
the event IDs of the hand table need not exist in the event tables of the model.

#### `test_a_block_id_that_does_not_fit_in_uint32_raises_value_error_that_names_it`

**Checks:** `seq_index._index_from_data` builds the index of a model with the block ID 2**32 - 1,
as uint32. For the block ID 2**32 it raises `ValueError` that names the ID.

**How:** The test copies the block table of `valid_1_5_1.seq`, sets the ID of the last block to
2**32 - 1, makes a model with `dataclasses.replace` and a frozen copy of the table, and checks the
dtype and the last `block_id`. It then sets the ID to 2**32 and checks that `ValueError` matches
`4294967296`.

**Assumptions:** None.

### 2.5 Raster sampler (`test_sampling.py`)

`test_sampling.py` tests `sampling.py`: `GradientSampler`, which gives the gradient waveform of one axis
at sorted times, from the sequence index and the kept points of the unique gradient events
(`_events._read_points`), made with `gradient_sampler(snap)`. `snap` is made by
`analyses.load(seq)`: `spec` for the sequences that it accepts. The sequences of the model that `spec`
rejects (a gradient that ends above 0 before its block ends, `gradient.nonzero-end-align`, a gradient
that starts above 0 after a delay, `gradient.nonzero-start-delay`, or a delay off the gradient raster,
`raster.gradient-delay`) are the sequences in `_REJECTED_BY_SPEC`; their tests are in section 3.10, and
load them with `cpp-siemens`. `load` writes the sequence with pypulseq's writer and reads the
file, so the values are those of the file: about 6 significant digits of an amplitude, times in whole
microseconds, and float32 for `cpp-siemens` (D7.2). A block duration in a file is a whole number of block
raster times (10 µs here, the gradient raster time), so a block cannot be off the gradient raster. The
tests of blocks off the raster use a sample raster `dt` that is not a divisor of the block. The waveform
is the gradient waveform of MATLAB Pulseq (`docs/implementation.md`, section 1). The reference is the
oracle waveform of `tests/oracles/waveform.py` (section 2.15), read from `sequence_of(snap)`
(`tests/oracles/blocks.py`). pypulseq's `seq.get_gradients()` is not a reference: it draws a line
across each gap and has no step at a junction (pypulseq-issues 12). The snapshot has no pypulseq
object. `_assert_matches_oracle` compares `sample(axis, t)` with `oracle.sample`, with a relative
1e-12 and an absolute 1e-12 times the largest |value| of the reference. The oracle makes its points
with the same sums as the sampler, so the difference is the rounding of the interpolation formula
only. The oracle comparisons of the synthetic sequences (`test_sample_equals_the_oracle_for_the_whole_sequence`
and the tests after it) cover the whole file and sub-ranges that cut blocks.

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

#### `test_amplitude_continues_across_a_block_junction`

**Checks:** Two extended trapezoids that together make one trapezoid, split into two
blocks at the middle of the flat top so the amplitude continues unchanged from one
block into the next, give the waveform of the oracle around the junction: the junction does
not create a spurious step.

**How:** `_junction_sequence(step_hz_per_m=0.0)` builds the two extended trapezoids
from the rise, flat and fall of one area-1000 trapezoid, split at the middle of the
flat top, and returns the junction time. `t` is 41 points evenly spaced over 40
gradient-raster periods centred on the junction. Compares with `_assert_matches_oracle`.

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
step, within a relative 1e-5 (the file holds the amplitude to 6 significant digits: 1190480 Hz/m for
1190476.19). The test does not check that `add_block` accepts the step. That is pypulseq's own check,
exercised here only because building the sequence requires it to pass.

**Assumptions:** None.

#### `test_triangle_trapezoid_matches_the_oracle`

**Checks:** A trapezoid with no flat time (`make_trapezoid` gives `flat_time == 0.0`),
whose `gradient_offsets` therefore has two points at the same time with the same
value, gives the waveform of the oracle: the removal of a point that has the time and the
value of the point before it does not change the value.

**How:** `_triangle_sequence` builds a single-block sequence with one small-area trapezoid on
x and asserts `flat_time == 0.0` to confirm the construction is the intended triangle. The test
samples the raster centres and the points of the oracle's polyline (`_model_times`) and compares
with `_assert_matches_oracle`.

**Assumptions:** None.

#### `test_sample_matches_the_added_events_for_an_oversampled_arbitrary_gradient`

**Checks:** `sample` gives the correct waveform for a file with an oversampled
arbitrary gradient (`make_arbitrary_grad(oversampling=True)`). The reference is not
`seq.get_gradients()`: pypulseq's `waveforms()` leaves out the first and the last point
of an oversampled gradient (draft 03 of `github.com/mdtisdall/pypulseq-issues`). The
reference is instead the polyline of the added events (the objects `make_*` returns,
before `add_block`), which does not depend on that.

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
3999 points evenly spaced over the file, within an absolute 1e-5 times the peak of the
reference (`rtol=0`; the file holds the amplitudes to 6 significant digits). The test cannot call
`load(seq)`: `read_pypulseq` calls pypulseq's `seq.remove_duplicates()`, which raises `KeyError: -1`
for the time shape -1 of an oversampled gradient. The test writes the file with
`seq.write(path, create_signature=True, remove_duplicates=False, check_timing=False)`, as
`read_pypulseq` does after the removal, and loads the path (`spec` accepts it).

**Assumptions:**

- pypulseq's writer writes `remove_duplicates=False` for this sequence (the time shape id -1 of an
  oversampled gradient is in the file as `-1`).

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

**How:** Parametrized over the 12 sequences of the model (`_MODEL_SEQUENCES`) that `spec` accepts
(`zero_gap`, `long_gap`, `non_zero_ends`, `gap_between_extended_trapezoids`, `step_then_gap`,
`spin_echo`, `gre`, `arbitrary_gradient`, `short_gap_from_0`, `negated_zero_gap`,
`negated_long_gap`, `negated_non_zero_ends`), loaded by `_load_model(name)` with `spec`. The 17
that `spec` rejects (`_REJECTED_BY_SPEC`: `short_gap`, `issue_12_delayed`, `issue_12_early_end`,
`off_raster_events`, `gap_of_1_5_raster_times`, `short_gap_to_0`, their negated copies that exist,
and the 8 `random_gaps` sequences) are in the test of the same name of section 3.10, which loads
them with `cpp-siemens`. `gap_of_1_5_raster_times_sequence` is a long gap of 1.5 raster times between two values that
are not 0, `short_gap_from_0_sequence` and `short_gap_to_0_sequence` have a short gap from 0 to a value
and from a value to 0, `gap_sequences.negated` gives a copy of each sequence of `tests/gap_sequences.py`
with each amplitude negated, and the 8 sequences of `random_gaps.random_gap_sequence` have the seeds 0 to
7 (random signs, delays of 0 to 7 raster times, and zero, short and long gaps). The oracle reads
`sequence_of(snap)`. `t` is the raster centres, 2001
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

**How:** Parametrized over `long_gap`, `zero_gap`, `short_gap_from_0` and `negated_long_gap`, the
cases of `_TIME_RANGE_NAMES` that `spec` accepts (`short_gap`, `issue_12_delayed`,
`off_raster_events` and `gap_of_1_5_raster_times` are in the test of the same name of section
3.10). The body is `check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`, which
that test calls too. The grid is about 40 times, every n-th time of the grid of the test above.
For each axis, the check compares the whole grid with the oracle. It then compares
`sample(t[i:j])` with `whole[i:j]` (`numpy.array_equal`) for each pair `i < j`. The sequences load through `_load_model`, and the oracle reads `sequence_of(snap)`.

**Assumptions:** None.

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

#### `test_range_inside_the_file_equals_the_same_slice_of_the_whole_file`

**Checks:** `block_samples` for a range that starts and ends inside the file gives
exactly the same values as the matching slice of `block_samples` for the whole file.

**How:** Builds `gre_sequence(num_trs=3)`. `raster_block_lengths` gives each block's
sample count, used to find the sample offset and length of a block range `[2, num_blocks
- 1)`. For each axis, `block_samples(axis, 0, num_blocks, dt)` and `block_samples(axis,
2, num_blocks - 1, dt)` are compared with `numpy.array_equal` after slicing the whole-file
result to the same sample offset and length.

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

**Checks:** `block_samples` raises `ValueError` for a block whose duration is not a whole number of
sample raster steps.

**How:** A file holds a block duration in whole block raster times, which is the gradient raster time
here, so the block is made off the sample raster by `dt`. `pp.make_delay(3 * raster)` is one block of 3
gradient raster times, and `block_samples("gx", 0, 1, 2 * raster)` (1.5 samples) must raise `ValueError`.

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

**How:** A two-block sequence: `pp.make_delay(4 * raster)`, then `pp.make_delay(3 * raster)`, with the
sample raster `dt = 2 * raster` (2 and 1.5 samples). `raster_block_lengths(index, dt)` must give `on_raster = False` and `n =
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

**How:** Two sequences of delay blocks, with a sample raster `dt` that the blocks are off (a file holds
whole gradient raster times). Blocks of 7 and 7 gradient raster times with `dt` of 5: 1.4 and 1.4
samples, the end is 2.8 samples and the result must be 3 (the sum of the rounded block lengths is 2).
Blocks of 1 and 2 gradient raster times with `dt = 3 * raster / 3.000005`: 1.0000017 and 2.0000033
samples, the end is 3.000005 samples, which is less than 1e-10 s above 3 samples, and the result must be
3 (a `ceil` of the end without the 1e-10 s gives 4). Each sequence must be off the raster in
`raster_block_lengths`, and the result must equal `ceil((index.end_s - 1e-10) /
dt)`.

#### `test_raster_block_lengths_tolerance_is_a_millionth_of_a_sample`

**Checks:** A block whose length is within 5e-7 samples of a whole number is on the
raster, and one that is 2e-6 samples away is not (`ON_RASTER_TOLERANCE` is 1e-6). The
number of samples is the whole number in each case.

**How:** Parametrized on the ratio `1 + 5e-7`, `1 - 5e-7`, `1 + 2e-6` and `1 - 2e-6`. A
one-block sequence with `pp.make_delay(raster)` (the file holds the block as one gradient raster time)
and the sample raster `dt = raster / ratio`. The test checks that `duration_s /
dt` equals the ratio within 1e-12, then that `raster_block_lengths(index, dt)` gives the
expected `on_raster` and `n == [1]`.

**Assumptions:** None.

#### `test_block_samples_equals_the_oracle_for_the_whole_sequence`

**Checks:** `block_samples` of the whole sequence equals `oracle.block_samples` for each axis,
at the gradient raster and, for the sequences with a gap, at finer rasters (one half and one
fifth of it). At the finer rasters, a ramp of half a raster time has samples in it.

**How:** Parametrized over the cases of `_WHOLE_CASES` that `spec` accepts (20 of the 49): the 12
sequences of the model that `spec` accepts (see `test_sample_equals_the_oracle_for_the_whole_sequence`)
at the gradient raster, and `long_gap`, `step_then_gap`, `short_gap_from_0` and `negated_long_gap`
at one half and one fifth of it. The cases with a sequence that `spec` rejects (29) are in the test
of the same name of section 3.10. The body is
`check_block_samples_equal_the_oracle_for_the_whole_sequence`, which that test calls too. The check
compares each axis with an absolute 1e-9 of the largest value. The sequences load through
`_load_model`, and the oracle reads `sequence_of(snap)`.

**Assumptions:** The two are not bit-equal. `block_samples` takes the sample time from the block
start, and the oracle from the sum of the block durations before it. The sum drifts by float
rounding. The difference is that drift only.

#### `test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range`

**Checks:** Each range of blocks and each range of samples (`skip` and `count`) of
`block_samples` equals the same samples of the oracle. It also equals the same slice of the whole
range exactly. The ranges start or end inside a gap, inside a ramp, and at a block edge. A new
sampler gives the same values as one that made the whole range first.

**How:** Parametrized over the four cases of `_ANY_RANGE_CASES` (a sequence and a sample raster)
that `spec` accepts: `long_gap` at one half of the gradient raster, `zero_gap` and `step_then_gap`
at the gradient raster, and `negated_long_gap` at one half. The other five (`short_gap` at the
gradient raster, `issue_12_delayed` at one fifth, `off_raster_events` at the gradient raster and
at one fifth, and `gap_of_1_5_raster_times` at the gradient raster) are in the test of the same
name of section 3.10. The body is
`check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range`, which that
test calls too. For each axis and each block range, the check compares the samples with the oracle and with the slice of the whole
range (`numpy.array_equal`). It does the same for each `(skip, count)` of `_sample_ranges`, on the
sampler of the test and on a new one. The sequences load through `_load_model`, and the oracle reads `sequence_of(snap)`.

**Assumptions:** The tolerance to the oracle is the one of the test above.

#### `test_one_event_in_blocks_of_two_lengths_gives_the_samples_of_each_length`

**Checks:** One gradient event in two blocks of different lengths gives the samples of each
length: the samples of `oracle.block_samples` for the block, and exactly the samples of a new
sampler that meets only that range. `block_samples` keeps the samples of an event for all the
lengths (the cache key is `(event, dt)`, and a block of `n` samples has the first `n` of them), so
this holds whichever length the sampler meets first.

**How:** Parametrized by the order of the two blocks (short then long, long then short). A
trapezoid on x (rise 50 us, flat 30 us, fall 50 us) is in both. The oracle reads
`sequence_of(snap)`. The short block has the trapezoid
alone: 13 samples. The long block has it and a delay of 400 us: 40 samples, of which the last 27
are 0. The test checks that the two blocks have one event ID. For each of two orders of calls
(block 0 first, block 1 first), a new sampler gives block 0, block 1 and both blocks. Each range
is compared with the same samples of the oracle (1e-9 of the peak), and with the same range from
a new sampler (`numpy.array_equal`).

**Assumptions:** A block is never shorter than its event, so no block cuts the samples of its
event: the number of samples of an event is at most the number of samples of each block that has
it.

#### `test_a_ramp_from_a_raster_edge_changes_no_sample_at_the_gradient_raster`

**Checks:** `block_samples` at the gradient raster for events on the raster edges has the
samples of the own events and 0 in a long gap. The ramps of half a raster time end at the raster
centres, where they are 0 (D7 of `docs/plans/third-review-fixes.md`).

**How:** `long_gap_sequence` has ends that are not 0 next to a long gap. The test checks that the
samples 10 to 29 are 0 (absolute 1e-9 of 3e4), that sample 9 is 2.85e4 and that sample 30 is
1.9e4.

**Assumptions:** A sample at the end of a ramp can be a rounding error from 0 (below 1e-9 of the
peak), because the ramp end and the sample time are each a sum of floats.

#### `test_gradient_sampler_raises_type_error_that_names_load_for_a_non_snapshot`

**Checks:** `gradient_sampler` and the constructor `GradientSampler` raise `TypeError` with
a message that names `load` for a `pp.Sequence` and for a path.

**How:** Parametrized over `gre_sequence()` and the path string `"sequence.seq"`. Both calls
must raise `TypeError` with `match="load"`.

**Assumptions:** The path is not read: the type check comes before any read.

#### `test_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`

**Checks:** A sampler made by `GradientSampler._from_parts` gives, bit for bit, the `sample` and
`block_samples` values of `GradientSampler(snap)`. It keeps its gaps in the dict that was passed,
not on the snapshot, and these gaps equal those of the snapshot's sampler.

**How:** Parametrized over the model sequences `long_gap`, `zero_gap`, `gre` and `spin_echo`, the
cases of `_FROM_PARTS_NAMES` that `spec` accepts (`short_gap`, `off_raster_events` and
`random_gaps_0` are in the test of the same name of section 3.10). The body is
`check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`, which that test
calls too. The check builds a new index with
`seq_index._index_from_data(snap.data, (played.gx, played.gy, played.gz))` (`played =
_played.played_gradients(snap)`; not the kept index) and new points with `_events._read_points(snap)`,
and makes a sampler with
`_from_parts(index, points, {})`. For each axis it compares `sample` at `_model_times(snap)` and
`block_samples` of all blocks at the gradient raster with `numpy.array_equal`. Then it checks that
the dict has exactly the keys `("gaps", axis)` for the three axes, that each entry is the sampler's
`_gaps(axis)` and not the snapshot sampler's object, and that the four arrays of each entry equal
the snapshot sampler's.

**Assumptions:** None.

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

`grad_peaks.py` computes its values from the per-event values of the decoding
(`_played.played_gradients`) and the columns of `seq_index.sequence_index`, not from every block. It
uses the gradient waveform of MATLAB Pulseq: a step across a zero gap, a line across a short gap,
and a ramp to 0 and a ramp from 0 across a long gap (`docs/implementation.md`, section 1). The slew
includes the steps, the lines and the ramps. The tests below the first group add: the credited
block for a value that several blocks and axes share, a window that keeps
only part of a ramp's slew, the vector peak of two blocks with different triples of active
gradients, the step at a junction, the step at the last point of an axis, the ramps of a first
value after a delay, the gap sequences of `tests/gap_sequences.py` with their hand-computed
values, the refusal of a bad window before the sequence is read, the range of a window past an
end of the sequence, and a comparison with the oracle of the gradient waveform
(`tests/oracles/waveform.py`, section 2.15) on random sequences. The oracle builds the polyline
of each axis one time and reads every value from it, so it shares no code with the package. The
comparisons with the oracle on the synthetic sequences and on the sequences of the oracle's own
tests are in section 3.10: they load the sequences through `cpp-siemens`, with the helpers of this
file.

Every test reads a pypulseq sequence with `load(seq)` (`spec`; `pulseq_analysis.analyses.load`):
the sequence is written by pypulseq's writer and read as a file. The
values are those of the file: the writer rounds amplitudes (and the values of a shape) to 6 significant
digits. The module constants `_WRITER_REL` (1e-5) and `_WRITER_STEP_REL` (1e-4, for a step, which is a
difference of two written values) are the relative tolerances for a value or a slope that is compared
with the value of the builder. `spec` rejects a gradient that starts at a value that is not 0 after a
delay (`gradient.nonzero-start-delay`), a gradient that ends at a value that is not 0 before the end
of its block (`gradient.nonzero-end-align`), and a gradient raster of 4 µs with a block duration
raster of 10 µs (`definitions.raster-commensurate`). Tests of the waveform model with such a
sequence are in section 3.10, and use `cpp-siemens`, which plays it. The oracle reads `sequence_of(snap)`
(`tests/oracles/blocks.py`), the gradients as the snapshot plays them, where the test compares exactly or
the sequence is rejected as a `pp.Sequence`.

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

**Assumptions:** The file holds the amplitudes of the event with 6 significant digits, so the slew
has a relative tolerance of 1e-5.

#### `test_slew_time_is_the_start_of_the_steepest_segment`

**Checks:** The slew time of an axis is the start of its steepest segment.

**How:** The test builds one x extended trapezoid whose last segment (900 to
1100 µs) is its steepest. It checks that the x slew is that segment's slope,
computed by hand, and that `slew_time_s` is 900 µs.

**Assumptions:** The file holds the amplitudes of the event with 6 significant digits, so the slew
has a relative tolerance of 1e-5.

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

#### `test_a_gradient_that_ends_at_the_end_of_the_sequence_has_no_step`

**Checks:** A gradient that ends at a value that is not 0 at the end of the sequence has no step
after its last point. The result does not depend on one ulp of `(start + delay) + shape_dur`.
Review 1.2 of `docs/reviews/2026-10-07-code-review.md` and decision D1 of
`docs/plans/fourth-review-fixes.md`.

**How:** The test is run for 20 values of `k`. It builds an x trapezoid with a slope of
1e9 Hz/m/s and a flat time of `(5 + k)` raster times, then a block of 0.6 ms with an x extended
trapezoid that rises to `A` in 100 µs and holds it to the end of the block. The step to 0 after
the last point would be `A / DT` (3.19e9 Hz/m/s), above the slope of the trapezoid. It checks
that the largest x slew of `gradient_peaks` is 1e9 Hz/m/s and is credited to block 1, that the
slew of block 1 in `block_gradient_values` is 1e9, and that the slew of block 2 is `A / 100 µs`
(the rise: the step is not counted). It checks the same slew and credit in the oracle.

**Assumptions:** The 20 end times do not each give a different rounding of the last time: the
test relies on some of them giving a last time one ulp before `end_s` and others giving it equal
to `end_s`. The slew of 1e9 Hz/m/s and the values of `A` hold for the system of
`tests/synthetic.py`, and the compare has a relative tolerance of 1e-6 because the file keeps
the amplitudes with fewer digits. A sequence that pypulseq writes and reads again has the same
written text (checked for the 20 values), so the test does not read the file again.

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

#### `test_matches_oracle_on_random_gradient_sequences`

**Checks:** 50 random sequences of trapezoids, extended trapezoids and arbitrary gradients on
random axes, each event built so that it starts and ends at 0 (so no gap has a step, a line or
a ramp, and the values come from the events alone): `gradient_peaks` matches the oracle on the
whole file and on up to 6 windows. The oracle reads the gradients that the
snapshot plays (`sequence_of(snap)`).

**How:** For each of 50 seeds, the test builds a sequence of 2 to 6 blocks, each with 0 to 3
random axes, each a trapezoid, an extended trapezoid or an arbitrary gradient built with
pypulseq's `make_*` functions (so pypulseq's own limit checks apply) and an explicit `first`
and `last` of 0 where the function does not default to that. It compares the whole-file result
and the results of up to 6 windows from `_oracle_windows` with the oracle, as
`test_matches_oracle_on_synthetic_sequences` (section 3.10) does.

**Assumptions:**

- `make_arbitrary_grad`'s `first` and `last` default to a linear extrapolation of the
  waveform's own edge samples, not to 0, so the random arbitrary-gradient builder passes
  `first=0.0, last=0.0` explicitly to keep every event zero-ended. This is a fact about
  pypulseq, not about the function under test, and is not itself checked here.

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
of `pulseq_analysis.analyses.pns_levels` with a wrapper that counts its calls.
`pns_levels` keeps one `PnsLevels` for each (snapshot, hardware, thresholds, `bin_s`),
the hardware being a pair `(struct, label)` (its key is the label and the 24 values of
the struct without `stim_thresh`, so two pairs with the same label and values are one
hardware, whatever their structs are or where they came from), so that a caller that needs
the PNS of one sequence more than once runs the SAFE model once. A snapshot never changes, so a kept result is
never old (section 2.12). Each test makes its snapshot with `analyses.load`. The thresholds of the key are the tuple of
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
`pulseq_analysis.analyses.asc`.

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

#### `test_prediction_does_not_sample_at_the_file_times_for_an_on_raster_sequence`

**Checks:** `pns_levels` never calls `GradientSampler.sample` (the samples at the file times of a
sequence that is not on the raster) for an on-raster sequence, and it calls
`GradientSampler.block_samples`.

**How:** The test replaces `GradientSampler.sample` and `GradientSampler.block_samples` with
wrappers that count the calls, and calls `pns_levels` on a synthetic spin echo sequence. There
must be no call of `sample` and at least one call of `block_samples`.

**Assumptions:**

- `_compute_levels` samples an on-raster sequence with `GradientSampler.block_samples`.
  `test_pns_levels.py` and `test_sampling.py` test `block_samples` and its agreement with `sample`
  and the oracle directly; this test only checks that the fast path is taken from `pns_levels`.

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

#### `test_prediction_propagates_an_error`

**Checks:** An error deep inside the SAFE model propagates out of `pns_levels`.

**How:** The test makes a snapshot of a synthetic spin echo sequence and replaces
`pns_levels._safe_gwf_to_pns_chunk` (the chunk function of `safe.py`) with a function that
raises `RuntimeError`. The call must raise the error.

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
sequence of `tests/synthetic.py` that has a builder without arguments and that `spec` reads (the
spin echo with the prephaser before and after, the GRE, the empty sequence, the arbitrary
gradient, the border) and for `build_repeating(10)`; the 4 µs raster sequence is in the test of
the same name of section 3.10; with no threshold, with
one, and with two; with the default bin and with bins of 3.7 ms and 0.1 ms. The `coord_end`
of `pns_total` is `num_samples * dt_s` and its `coord_step` is `bin_samples * dt_s`, so the
test checks that the tolerance of the `coord_end` check holds for these float products. The
empty sequence gives no series.

**How:** Parametrized over the sequence and the case of thresholds and bin. The body is
`check_the_series_of_pns_safe_levels_are_valid`, which the test of section 3.10 calls too: it runs
the analysis with `synthetic.EXAMPLE_HW`, calls `to_series`, checks the names, and checks
that each series equals its round trip through the strict JSON text. Constructing a
series that is not valid would raise.

**Assumptions:** The bin of 3.7 ms (370 samples) is not a divisor of the number of samples of
most sequences, so their last bin is short. The sequences with a rotation library and the
one of `waveform_sequence` are not in the list. `raster_4us_sequence` is not in the list: `spec`
rejects a gradient raster of 4 µs with a block duration raster of 10 µs
(`definitions.raster-commensurate`), so the test of section 3.10 loads it with `cpp-siemens`.

#### `test_the_series_of_gradient_spectrum_is_valid`

**Checks:** The series of `gradient.spectrum` for each sequence of the test above is a valid
`Series` that equals the series that `from_obj` reads from its `to_obj`. The empty sequence
gives no series, and the other sequences give one.

**How:** Parametrized over the sequences. The body is
`check_the_series_of_gradient_spectrum_is_valid`, which the test of section 3.10 calls too: it
runs the analysis with the default arguments, calls `to_series`, and checks the round trip and the
number of series.

**Assumptions:** No sequence is too short for the default window: the spectrum pads a short
sequence to one window. `raster_4us_sequence` is not in the list: `spec` rejects a gradient raster
of 4 µs with a block duration raster of 10 µs (`definitions.raster-commensurate`), so the test of
section 3.10 loads it with `cpp-siemens`.

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

`test_analyses.py` tests `analyses/registry.py`: the entry-point registry of the group
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
`pulseq_analysis.analyses.registry:`.
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
within a relative 1e-12 or an absolute 1e-12 times the array's own peak. The oracle reads
`sequence_of(snap)`, the gradients as the snapshot plays them (the written file's values), not the
builder's `pp.Sequence`, so the 1e-12 holds. `seq.system.gamma` is that of the stand-in (1H).

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
and a shorter last chunk: the comparison covers the joins of the chunks.

**How:** The test sets `grad_spectrum._CHUNK_WINDOWS` to 4 (`monkeypatch`), builds each sequence
with `1000 / TR_BLOCKS` TRs, and compares this module's spectrum (times `1e3 / gamma`) with the
oracle's, as the test above does, with the tolerance `1e-12 * max(1, duration in s)` instead of
1e-12. The oracle reads `sequence_of(snap)`. The tolerance uses `seq.duration()` of the builder's
`pp.Sequence`.

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

#### `test_the_defaults_are_those_of_docs_usage`

**Checks:** The spectrum calculated with the three arguments at the defaults that
`docs/usage.md` gives (2000.0 Hz, 0.05 s and 3.0, the defaults of pypulseq's
`calculate_gradient_spectrum`) equals the spectrum of a call with no arguments. The result of
a call with no arguments has these defaults in its fields `max_frequency_hz`, `window_s` and
`frequency_oversampling`.

**How:** The test gives the three literal values to `grad_spectrum._compute_spectrum` for the
synthetic spin echo, so the result is calculated and is not the kept result (a call of
`gradient_spectrum` with these values would give the kept object of the call with no
arguments, because the key is the same). It checks that the two results are not one object,
and that the frequencies, each axis spectrum and the RSS are exactly equal. The test also
compares the three fields of the result with the values.

**Assumptions:**

- The values are those of `docs/usage.md`; the test does not read pypulseq, so a change of
  pypulseq's defaults does not fail it.
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
types of the arrays, the empty sequence). Each test makes its snapshot with `analyses.load`.
The tests of the kept results are here too: a measurement gives one object for one snapshot, a
windowed `gradient_peaks` uses the kept values of the events, and a kept result does not keep its
snapshot alive. A snapshot never changes, so a kept result is never old (section 2.12).

#### `test_the_measurements_of_one_sequence_read_each_unique_gradient_event_once`

**Checks:** `gradient_peaks`, `block_gradient_values`, `pns_levels` and `gradient_spectrum` of one
snapshot take the points of each unique gradient event from the decoding one time in total, not
one time for each measurement.

**How:** Parametrized over the three sequences. The test replaces `SpecDecoding.gradient_points`
(the method of the protocol `Decoding` that `played_gradients` calls for each unique decoded
event) with a wrapper that counts
its calls, takes the number K of unique gradient events from the sequence index
(`grad_first.size`, which is the first call that makes the played gradients), and calls the four
functions on the snapshot (`pns_levels` with pypulseq's example hardware). The count must be K.

**Assumptions:**

- The measurements take the points of an event only from `played_gradients`, which the snapshot
  keeps. `spec` is the interpreter; `cpp-siemens` does not call `gradient_offsets`.
- The wrapper counts the calls of the module `_played`, so a call from another module (for
  example `_events` for an event that is not a tuple) does not count.

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
(rise/3 + flat + fall/3). The arbitrary gradient has the waveform `[1, 2, -4, -1, 2] u`
with u = 1e4 Hz/m, first and last 0, and raster r. Its points are at 0, 0.5 r, 1.5 r, 2.5
r, 3.5 r, 4.5 r and 5 r. Expected: peak 4 u at 2.5 r, slew 6 u / r from 1.5 r, integral
91/6 r u² (the sum of dt (a² + ab + b²) / 3 over the six segments). The slopes are 2 u / r, 1 u / r,
6 u / r, 3 u / r, 3 u / r and 4 u / r; the integral is (1/6 + 7/3 + 4 + 7 + 1 + 2/3) r u². The test compares with
`pytest.approx` (relative 1e-12, and absolute 1e-12 s for the times). The test above
compares `_event_values` with `_polyline_values`, so a wrong `_polyline_values` does not
fail it. This test does.

**Assumptions:** The trapezoid has a fall longer than its rise, so the rise is the
steepest segment without a tie. The arbitrary gradient has 5 samples, because pypulseq
reads back an arbitrary gradient of 4 samples or fewer with a shape that ends at the last
sample, not half a raster after it. The largest value of the waveform is 4 u, so that the shape in the
file (the waveform divided by the largest value: 0.25, 0.5, -1, -0.25, 0.5) is exact in the 6 digits that
pypulseq's writer keeps. With 3 u the shape has thirds, the writer rounds them, and the slew differs by
2e-10 of its value.

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

#### `test_event_points_raises_type_error_that_names_load_for_a_sequence`

**Checks:** `event_points` raises `TypeError` with a message that names `load` for a
`pp.Sequence`.

**How:** `event_points` is called with `spin_echo_sequence()` and must raise `TypeError` with
`match="load"`.

**Assumptions:** Each measurement and `GradientSampler` has the same test in its own test file
(`test_grad_peaks.py`, `test_pns_levels.py`, `test_grad_spectrum.py`, `test_sampling.py`).

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

**Assumptions:** The other errors of `SafeAxis` are tested in section 2.21.

### 2.17 The snapshot (`test_snapshot.py`)

`test_snapshot.py` tests `analyses.load` and `synth/snapshot.py` (task R14): `load` reads a file
or a pypulseq sequence through an interpreter, and the `Snapshot` holds the interpreter's
`SequenceData` and its decoding. The files are `tests/seqfiles/oracle/pulseq_seq4.seq` (a
gradient echo of pypulseq), the two radial files with rotations
(`oracle/pulseq_make_radial.seq`, `oracle/koma_v1.5_rotation_radial_tiny.seq`) and other
fixtures named below; the sequences are the synthetic spin echo, gradient echo, arbitrary
gradient, border and empty (one delay block) sequences. The results that the tests compare are
the index, the event points, the samples of the sampler on the raster, and the four
measurements of the gradients (`gradient_peaks`, `block_gradient_values`, `pns_levels` with
pypulseq's example hardware and `gradient_spectrum`), each with its default arguments, compared
with `values_equal`.

The tests run without any plugin interpreter installed. A fake plugin of the module, `Unrotated`,
stands for one: it reads with `spec`, under its own name, and its decoding (`UnrotatedDecoding`)
gives `spec`'s decoding through the methods of the protocol `synth.Decoding`, with the rotations
left unapplied (setting `"unrotated"`, a hint, no block rotated), as `cpp-siemens`'s default
leaves them. It implements version 1 of the plugin protocol (P22): its `decode` takes the session,
and its decoding gives `spec`'s durations, records and flags. The `check_*` helpers of the module take the interpreter; the plugin's tests run
them for `cpp-siemens` (section 3.11).

#### `test_load_of_a_file_is_the_reading_of_the_interpreter`

**Checks:** `load(path, interpreter)` holds `read_seqfile(path, interpreter)`: equal data, the same
interpreter, the path as `source`, and a decoding of the protocol `Decoding`, of the class of that
interpreter (`check_load_of_a_file`).

**How:** Parametrized over `"spec"` (a `SpecDecoding`) and `Unrotated()` (an
`UnrotatedDecoding`), on the gradient echo file.

**Assumptions:** `SequenceData` equality compares every field but the reader's object.

#### `test_the_default_interpreter_of_load_is_spec`

**Checks:** `load` with no interpreter reads through `spec` (P19).

**How:** `load(path).interpreter == Spec()`.

**Assumptions:** None.

#### `test_load_of_a_sequence_is_read_pypulseq_of_it`

**Checks:** `load(seq, interpreter)` holds `read_pypulseq(seq, interpreter)`, with `origin`
`"pypulseq"` and `source` None, and a second `load` of the same sequence gives equal data
(`check_load_of_a_sequence`).

**How:** Parametrized over the five synthetic sequences and `spec` and `Unrotated()`.

**Assumptions:** `test_from_pypulseq.py` tests `read_pypulseq` itself.

#### `test_load_raises_the_rejection_of_the_interpreter`

**Checks:** A file that `spec` rejects raises its `SeqFileError` from `load`, with the code of the
reason.

**How:** `bad_gradient_nonzero_end_align.seq` (`gradient.nonzero-end-align`) and
`bad_raster_gradient_delay.seq` (`raster.gradient-delay`). The plugin's tests load both through
`cpp-siemens`, which plays them.

**Assumptions:** None.

#### `test_load_raises_not_supported_for_a_version_outside_the_package`

**Checks:** A file of version 1.3 raises `NotSupported` from `load` (Q1).

**How:** `bad_version_unsupported_1_3.seq` through `spec`.

**Assumptions:** None.

#### `test_load_accepts_a_file_with_no_signature`

**Checks:** A file with no `[SIGNATURE]` section loads, and its data has no signature.

**How:** `valid_no_signature.seq` through `spec`; the index has blocks.

**Assumptions:** None.

#### `test_the_snapshot_records_the_interpreter_with_its_settings_and_the_records`

**Checks:** `snap.interpreter` is the interpreter object given, and `snap.records` is the records
of the reading (P20, rule 4).

**How:** `Unrotated()` on the gradient echo file: the same object. `valid_1_5_1.seq` through
`spec`: the records equal those of `read_seqfile`, one unknown extension `UNKNOWN` (D2.17).

**Assumptions:** None.

#### `test_load_warns_for_a_rotation_that_a_plugin_leaves_unapplied`

**Checks:** With a plugin whose decoding leaves the rotations unapplied, `load` of a file whose
blocks play rotations emits one `ScannerSettingWarning`, which ends with the plugin's hint, and
keeps the decoding's rotation record, with no block rotated and some blocks left unapplied
(`check_load_warns_for_an_unapplied_rotation`).

**How:** Parametrized over the two radial files, with `Unrotated()`, in `pytest.warns`.

**Assumptions:** None.

#### `test_load_does_not_refuse_rotations_and_does_not_warn_when_they_are_applied`

**Checks:** `load` reads a file with played rotations through `spec` (from 1.5.1) with no
`ScannerSettingWarning`; the record has the setting `"apply"`, every block with a rotation
rotated and none unapplied, and `gradient_peaks` gives values
(`check_load_applies_rotations_without_a_warning`).

**How:** Parametrized over the two radial files, with the warning made an error.

**Assumptions:** Both radial files are of version 1.5.1 or later.

#### `test_load_does_not_warn_for_a_rotation_that_no_block_plays`

**Checks:** A file that defines a rotation that no block uses loads through a plugin that leaves
the rotations unapplied with no warning, and the record has no block with a rotation
(`check_load_does_not_warn_for_a_rotation_that_no_block_plays`).

**How:** `valid_1_5_1_rotation_not_played.seq` with `Unrotated()`, with the warning made an error.

**Assumptions:** None.

#### `test_the_rotation_changes_the_measured_gradients_only_where_it_is_applied`

**Checks:** On a radial file, the peaks of `spec`, which rotates, differ from those of a plugin
that leaves the rotations unapplied: the measurements take the gradients of the decoding.

**How:** `pulseq_make_radial.seq`; `gradient_peaks` of the two snapshots.

**Assumptions:** None.

#### `test_a_change_of_the_sequence_changes_no_result_of_its_snapshot`

**Checks:** After `load(seq)`, scaling a trapezoid of `seq` in its library changes no result of
the snapshot, made after the change or kept before it, and a new `load(seq)` gives other results.

**How:** The spin echo; the reference is a snapshot of a new spin echo. Parametrized over the
results made after the change and kept before it.

**Assumptions:** One kind of change; the snapshot holds no object of the sequence, which is what
makes every kind of change safe.

#### `test_a_copy_of_a_snapshot_is_a_new_snapshot_with_no_kept_results`

**Checks:** A copy from `pickle` or `copy.deepcopy` is a new `Snapshot` with equal data, the same
interpreter and `source`, no kept results, and equal results, made again
(`check_a_copy_of_a_snapshot`).

**How:** Parametrized over the two copies, through `spec`, on the gradient echo file.

**Assumptions:** None.

#### `test_load_refuses_another_type_and_a_snapshot`

**Checks:** `load` raises `TypeError` that names `load` for `None`, an `int`, `bytes`, a list and a
`Snapshot`.

**How:** Parametrized over the five values.

**Assumptions:** None.

#### `test_load_raises_for_an_interpreter_that_does_not_exist`

**Checks:** An interpreter name that does not exist (`"strict"`, removed in R11) raises the
`ValueError` of `seqfile.interpreter`.

**How:** `load(path, "strict")` in `pytest.raises`.

**Assumptions:** None.

#### `test_check_snapshot_raises_a_type_error_that_names_load`

**Checks:** `_check_snapshot` raises `TypeError` that names `load` for a `pp.Sequence`, `None`
and a path, and nothing for a `Snapshot`.

**How:** Parametrized over functions that make the three values, so that the
`pp.Sequence` is built when the test runs; that case has the marker `pypulseq`.

**Assumptions:** None.

#### `test_a_snapshot_takes_only_a_sequence_data`

**Checks:** `Snapshot(x)` raises `TypeError` that names `SequenceData` when `x` is not one.

**How:** With a `pp.Sequence`.

**Assumptions:** None.

#### `test_a_snapshot_has_read_only_properties_no_new_attribute_and_the_hash_of_its_identity`

**Checks:** The properties (`data`, `decoding`, `interpreter`, `records`, `rotation_record`,
`source`) cannot be set, a new attribute cannot be added, two snapshots of one file are not
equal, and a snapshot is a key of a dict by identity.

**How:** `setattr` of each name raises `AttributeError`; equality, hash and a dict lookup.

**Assumptions:** None.

#### `test_load_accepts_a_path_like_and_source_is_its_str`

**Checks:** `load` takes a `str` and a `pathlib.Path`, and `snapshot.source` is the `str` of the
path.

**How:** Parametrized over the two; the spin echo written to a file has 6 blocks.

**Assumptions:** None.

### 2.18 The names of the interface (`test_interface.py`)

The tests read the backtick spans and the code blocks of `docs/usage.md` and
`docs/implementation.md`. A dotted name that starts (after an optional `pulseq_analysis.`) with
the path of a module or subpackage of the package (the longest one, for example
`synth.snapshot`), or with the last part of the path of a module (`snapshot`), is a name with a
module, and so is each name of a `from pulseq_analysis.module import ...` line of a Python code
block. A bare name in a span or a block is a name of any module.

#### `test_each_name_that_the_documents_give_with_a_module_can_be_imported`

**Checks:** Each module and each name that the documents give with a module
(`registry.registry`, `series.FrozenDict`, `pulseq_analysis.synth.snapshot`, the names of the
imports of the code blocks) exists in the package.

**How:** The test reads the dotted names and the imports of the documents, checks that it found
`series.FrozenDict`, the subpackage `analyses` and the import of `gradient_peaks` (so the reading
is not empty), imports each module, and collects each name that the module does not have.

**Assumptions:** A further part of a dotted name (a method, as in `Series.to_obj`) is not read.
A name that a document gives in a private module (for example `_events._read_points`) is also
checked. The last parts of the paths of the modules are unique (the test asserts it), so a short
name gives one module.

#### `test_the_interface_names_of_the_review_are_in_the_documents`

**Checks:** The documents give `series.SeriesKind`, `registry.Analysis` and `series.FrozenDict`,
and the three names are at their public paths: `series.FrozenDict` is the `FrozenDict` of
`_equality`, and the other two are defined in `analyses.series` and `analyses.registry`.

**How:** The test reads the dotted names of the documents, imports the three names, and compares
the object and the `__module__` of each.

**Assumptions:** None.

#### `test_each_public_name_of_a_module_is_in_the_documents_or_an_exception`

**Checks:** Each name that a public module defines (a module without a `_` at the start of the
last part of its path, a name without a `_` at the start) is in the documents, or is in
`EXCEPTIONS` of the test.

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

### 2.19 The reader of Pulseq files (`test_seqfile.py`)

`test_seqfile.py` tests `seqfile.spec.read_spec` (the `spec` interpreter, the default of `read_seqfile`) and the model of `model.py`. A plugin interpreter has its own tests (sections 2.27 and 3.8). The files are in `tests/seqfiles`: the valid fixtures (`valid_*.seq`), one fixture for each rule or row of the plan (`bad_*.seq`, each made from a valid fixture with one change, by hand; some read under `spec`), and `tests/seqfiles/oracle`, the copies of files that MATLAB Pulseq, pypulseq and KomaMRI.jl wrote (`SOURCES.md` of that folder gives the source, the commit and the license of each). The table `VERDICTS` has the verdict of `spec` on each file. A test for a row of section 6 of `docs/plans/parser-redesign.md` cites the specification (`spec:N` is line N of `doc/specification.tex` at `c7469123`), the slides (`slide N`, of `doc/pulseq_shapes_and_times.pdf`) and the entry of `docs/discrepancies.md`, and says when the behaviour is the package's choice. The tests need no pypulseq.

#### `test_each_fixture_gives_its_verdict`

**Checks:** Each `.seq` file of `tests/seqfiles` (also `oracle` and `undefined`) gives the verdict of the table `VERDICTS`: `spec` reads it, or rejects it with exactly the code of the table and no other (the three codes of `bad_many.seq`), or raises `NotSupported` (a version outside 1.4.0 to 1.5.x). A rejection has no omitted violation, the interpreter name `spec`, a message for each violation, and the path of the file in its text.

**How:** For each file (parametrized), the test reads it through `read_seqfile` and compares the verdict ("reads", "NotSupported" or the codes joined by a comma) with the table.

**Assumptions:** The table was made from a run of `spec` and checked file by file against the plan (section 6) and the record. A fixture that gets a second violation fails the test, and the fixture is changed, not the test.

#### `test_the_verdict_table_names_every_fixture`

**Checks:** The table `VERDICTS` has every `.seq` file under `tests/seqfiles` and no other.

**How:** The test lists the folder recursively and compares the relative paths with the keys.

**Assumptions:** None.

#### `test_each_rule_that_a_fixture_can_give_has_a_fixture`

**Checks:** Each code of `spec.RULES` is given by a fixture of the table, or is in `NO_FIXTURE` with its reason. Only `rotation.zero` has no fixture (a quaternion of norm 0; its test writes the file). Each code of the table is a rule, and a code is not in both.

**How:** The test collects the codes of the table and compares them with the keys of `RULES` and of `NO_FIXTURE`.

**Assumptions:** A rule that a fixture gives only for some of its conditions (`syntax.number`, `id.unique`, `syntax.shape`) counts as covered; the tests of the basis cover the other conditions.

#### `test_violation_names_the_section_and_the_line`

**Checks:** A violation of one rule has the section and the line number (from 1) of the row that breaks it, of the `shape_id` line for a shape, of the header for a section (`SIGNATURE`, `extension LABELSET`), or `None` where the rule is about the file or a missing definition. The test covers 51 fixtures.

**How:** For each fixture of the table (parametrized), the test compares the one violation with the section and the line that the test writes. For a row it also checks that the line of the file is not blank, and for a shape that the line starts with `shape_id`.

**Assumptions:** The line numbers are those of the fixture files, which do not change.

#### `test_each_rule_has_a_text_and_a_source`

**Checks:** Each rule of `spec.RULES` has a non-empty text and a non-empty source. A rule that is partly a choice has a choice.

**How:** The test reads the fields of each `Rule`.

**Assumptions:** The test cannot tell whether the source is right; the tests of the rows cite the specification.

#### `test_the_message_of_a_violation_has_the_choice_of_its_rule_when_the_rule_is_one`

**Checks:** For every violation of every rejected fixture: when the rule is wholly the package's choice (`Rule.choice` and not `partial`), the message ends with "(the specification does not state this rule: <choice>)"; when the specification states the rule, the message has no such text. A partial rule is skipped (the next test).

**How:** The test reads each rejected fixture of the table and checks each violation against `RULES`. It checks that both kinds of rule were seen.

**Assumptions:** None.

#### `test_a_partial_rule_carries_the_choice_for_its_choice_conditions_only`

**Checks:** For the three rules that the specification states only in part, the message has the choice only for the conditions that it does not state: `syntax.number` for `nan` (not for a text that is not a number, next test), `id.unique` for a block ID (not for an ADC ID), `syntax.shape` for a shape with no blank line before the next `shape_id` or at the end of the section (not for a shape with no `num_samples` line).

**How:** For each case (parametrized), the test reads the fixture, takes its one violation and checks its rule and whether its message has the choice.

**Assumptions:** None.

#### `test_a_float_column_that_does_not_hold_a_number_has_no_choice_and_nan_has_one`

**Checks:** In a float column, `1,5` and `abc` give `syntax.number` without the choice in the message, and `nan` and `-inf` give it with the choice.

**How:** The test replaces the amplitude of the trapezoid in a valid fixture and reads the file, four times.

**Assumptions:** None.

#### `test_a_file_with_several_violations_gives_all_of_them_in_file_order`

**Checks:** A file that breaks three rules gives the violations of the three, in the order of the lines of the file, each with a section and a line.

**How:** The test reads `bad_many.seq` (a required unknown extension, an unresolved RF reference and an ADC dwell time off the raster) and compares the rules, the order of the lines, and that each violation has a section and a line.

**Assumptions:** None.

#### `test_a_file_with_violations_in_five_sections_gives_each_with_its_section_and_line`

**Checks:** A file with one violation in each of five sections (DEFINITIONS, BLOCKS, TRAP, ADC, SHAPES) gives all five, in the order of the file, each with its section and the line of its row (of the `shape_id` line for the shape).

**How:** The test changes one row in each section of a valid fixture, computes the expected line of each from the text, and compares the (rule, section, line) of the violations.

**Assumptions:** The five rules are chosen so that no violation hides another: a row that breaks a rule of syntax (`syntax.use`, `syntax.columns`) makes `spec` skip the checks across tables for that file (an RF row with `use` `x` hides an ADC dwell time off the raster).

#### `test_each_violation_of_a_rule_is_in_the_error`

**Checks:** A rule that a file breaks twice gives two violations, not one: two blocks with two ROTATIONS objects, a version file with two bad lines, and a file with two shapes that decompress to more samples than declared.

**How:** For each fixture (parametrized), the test compares the lines of the violations and checks that they have one rule.

**Assumptions:** The line numbers are those of the fixtures.

#### `test_an_error_lists_20_locations_of_a_rule_and_counts_the_rest`

**Checks:** For a rule that 25 rows break, the error lists 20 violations and `omitted` has the
other 5; the text of the error says "5 more".

**How:** The test writes a copy of the valid fixture with 25 more RF rows whose `use` is `x`.

**Assumptions:** The limit of 20 is `MAX_LOCATIONS` (the test checks its value).

#### `test_seqfile_error_is_a_value_error_and_can_be_pickled`

**Checks:** `SeqFileError` is a `ValueError`, a copy from `pickle` has the same violations, omitted
counts and path, and a `Violation` cannot be changed.

**How:** The test pickles the error of `bad_many.seq` and compares the fields.

**Assumptions:** None.

#### `test_valid_fixture_loads_with_its_version`

**Checks:** Each valid fixture loads into a `SequenceData` of its version, with `origin` `"file"` and the interpreter `Spec()`: the versions 1.4.0, 1.4.1, 1.5.0 and 1.5.1, a 1.5.0 file with the extensions of 1.5.1, a file with CRLF line ends, a file with comments between sections, a `#` line inside a shape, no signature, a wrong signature hash, a gradient raster of 5 us, a rotation that no block plays (`valid_1_5_1_rotation_not_played.seq`: the MATLAB waveform test skips a file that plays a rotation, and compares its gradients), a last section with no blank line, an unknown label, a soft delay with a fraction, and RF time shapes of each kind.

**How:** For each file (parametrized), the test calls `read_seqfile` and compares the version, the origin and the interpreter.

**Assumptions:** The fixtures are valid by the specification and the choices of `spec`: the test cannot find a rule that `spec` lacks.

#### `test_valid_1_5_1_fixture_has_the_values_of_the_file`

**Checks:** The model of the 1.5.1 fixture has the values that the text gives: the rasters, the
definitions (as text, in file order), `RequiredExtensions`, the block table, the RF event, the
gradients, the trapezoid and the ADC events in seconds, and the shapes as stored and decompressed.

**How:** The test reads the fixture and compares each table and each shape with the numbers of the
text, which it writes in the test.

**Assumptions:** The expected numbers were read from the text of the fixture by hand, and the
conversion to seconds is a division by 1e6 (microseconds) or 1e9 (the ADC dwell time in ns).

#### `test_valid_1_5_1_fixture_has_the_extensions_of_the_file`

**Checks:** The extension list table, the type ID of each `extension` section, and the tables of LABELSET, LABELINC, TRIGGERS, DELAYS (soft delays), ROTATIONS (the quaternion normalized) and RF_SHIMS are those of the text, and an extension that the parser does not know is in `skipped_extensions`.

**How:** The test compares each table with the rows of the fixture, with the trigger times and the soft delay offset in seconds, and the quaternion with the quaternion of the file divided by its norm.

**Assumptions:** None.

#### `test_extension_tables_of_a_file_without_extensions_are_empty`

**Checks:** A file with no extension has empty extension tables, an empty RF_SHIMS mapping and no
type ID.

**How:** The test reads the 1.4.0 fixture and checks the length of each table.

**Assumptions:** None.

#### `test_valid_1_4_fixtures_have_the_1_5_layout_with_the_values_of_the_format`

**Checks:** A 1.4.x file gives the 1.5 layout with the values that the format defines: RF `freq_ppm`
and `phase_ppm` 0, `use` `u`, `center` NaN, ADC ppm terms and `phase_shape_id` 0. The `first` and
`last` of a gradient with a time shape are the amplitude times its first and last sample.

**How:** The test reads the 1.4.0 and 1.4.1 fixtures and compares the RF and ADC rows, and the
gradient of the 1.4.1 fixture with `400000 * 0.2`.

**Assumptions:** Those values are the decision of the plan (3.4); the test checks that the parser
follows it, not that the decision is right.

#### `test_signature_matches_is_reported_and_is_not_a_rule`

**Checks:** `signature.matches` is `True` for a hash that is the MD5 of the file by the rule of the specification, `False` for another hash, and the signature is `None` for a file without the section. A wrong hash does not make the file fail. (The file with CRLF line ends is in `test_a_signature_hash_covers_the_bytes_before_the_newline_that_precedes_it`.)

**How:** The test reads three fixtures and compares the signature.

**Assumptions:** The hash of `valid_1_5_1.seq` is the MD5 of the bytes that the rule covers.

#### `test_signature_matches_hashes_the_bytes_before_the_newline_that_precedes_the_signature`

**Checks:** `signature.matches` is `True` when the stored MD5 is that of every byte before the `\n` that precedes the first `[SIGNATURE]` line (spec:223): a `\r` before that `\n` is hashed. The six cases: one empty line, two empty lines, a line of spaces, CRLF with an empty line, an LF file with a CRLF empty line, and a CRLF file with an LF empty line. The hash of the bytes that the scanner's reader hashes (it holds back and drops the last empty line) matches only where the two rules hash the same bytes.

**How:** The test (parametrized) builds each file from `valid_no_signature.seq` with the line ends of the case and a `[SIGNATURE]` section with the MD5, reads it, then replaces the hash with that of the scanner's bytes and checks that `matches` is true only when the two byte strings are equal.

**Assumptions:** The bytes of the scanner's reader come from the former version of this test, which compared them with the oracle; `test_cpp_oracle.py` now compares the oracle's own check with `spec`'s (section 2.20). Each case has a blank line after the last shape, since a shape needs one (D3.11). The test does not cover a NUL byte in a line.

#### `test_read_seqfile_takes_a_str_or_a_path_and_raises_oserror_for_a_missing_file`

**Checks:** `read_seqfile` takes a `str` or a `pathlib.Path` with the same result, and raises `FileNotFoundError` for a file that is not there.

**How:** The test reads the same fixture by both, compares the models, and reads a path that does not exist.

**Assumptions:** None.

#### `test_the_default_interpreter_is_spec`

**Checks:** `read_seqfile(path)` gives the model of the interpreter `spec`: its `interpreter` field is `Spec()` (named `spec`), and the model equals that of `read_seqfile(path, "spec")` and of `read_spec(path)`.

**How:** The test reads one fixture the three ways and compares.

**Assumptions:** None.

#### `test_a_row_with_another_number_of_fields_than_its_table_is_syntax_columns`

**Checks:** D1.2, D4.2: a row of `[RF]` with 11 or 13 fields, of `[GRADIENTS]` with 6 or 8, of `[ADC]` with 8 or 10, and of `[TRAP]` with 5, gives `syntax.columns` in its section. The tables of the specification have 12, 7, 9 and 6 fields (spec:341-359, spec:386-399, spec:431-445, spec:379-381); the prose before each table (7, 4, 6 numbers) disagrees, and `spec` follows the tables and the examples.

**How:** For each case (parametrized), the test changes one row of a valid fixture and reads the file.

**Assumptions:** The specification's own prose is wrong about the counts (the record, D1.2).

#### `test_a_1_4_file_has_the_rows_of_the_1_4_tables_and_not_those_of_1_5`

**Checks:** D1.2, D4.2: a 1.4.x file has 8 fields in an RF row, 5 in a gradient row and 6 in an ADC row; a row of the 1.5 layout in a 1.4.1 file (`[RF]`), and a row of the 1.4 layout in a 1.5.1 file (`[GRADIENTS]`), give `syntax.columns`.

**How:** The test replaces one row in each file and reads it.

**Assumptions:** The 1.4 tables are those of the fixtures; the specification gives only the 1.5 tables.

#### `test_a_file_without_a_version_section_is_version_missing`

**Checks:** D1.1, spec:201: a file with no `[VERSION]` section gives `version.missing`, with no section and no line; so does a valid file with its `[VERSION]` section removed.

**How:** The test reads `bad_version_missing.seq` and an edited valid fixture.

**Assumptions:** The specification only recommends the rejection; the plan makes it one (D1.1).

#### `test_a_version_outside_1_4_to_1_5_is_not_supported`

**Checks:** D4.1: `read_seqfile` raises `NotSupported` (a `NotImplementedError`) for the fixtures of version 1.3.1 and 1.6.0, with a message that names the range and the version (Q1 of `docs/plans/parser-redesign.md`): no rule is broken, the package does not read them.

**How:** For each fixture (parametrized), the test reads it and checks the exception and its message.

**Assumptions:** The versions of the fixtures are 1.3.x and 1.6.x (the message names `1.3` and `1.6`).

#### `test_the_versions_1_5_0_to_1_5_x_are_read`

**Checks:** D4.1: a file of version 1.5.0 or 1.5.9 loads (the range is from 1.4.0 up to, not including, 1.6.0).

**How:** The test (two cases) changes the revision of a valid fixture and reads it.

**Assumptions:** The 1.4.x boundary is covered by the fixtures `valid_1_4_0.seq` and `valid_1_4_1.seq`.

#### `test_a_version_line_that_is_not_an_integer_is_version_invalid`

**Checks:** spec:193-198: `minor 5.0` gives `version.invalid`, at the line of `minor`.

**How:** The test reads `bad_version_invalid.seq`, checks the rule and that line 6 is in the violations and is `minor 5.0`.

**Assumptions:** The fixture also has a violation for the `minor` key as missing (at the header), so the test checks that the line of the row is among the lines.

#### `test_a_file_may_have_its_sections_in_any_order`

**Checks:** D2.1: a file with `[VERSION]` last (`undefined/version_last.seq`) and a file with `[SHAPES]` before `[VERSION]` load with the model of the valid file (but for the definitions and the signature).

**How:** The test reads the first file, and writes the second from `valid_no_signature.seq` with its sections moved. It compares the models without the definitions and the signature.

**Assumptions:** The sections of the moved file are cut at the lines that start with `[` or `extension `.

#### `test_a_comment_or_blank_line_in_a_table_is_skipped_and_the_rows_after_it_are_read`

**Checks:** D2.5, spec:171: a file with a `#` line inside a table and rows after it (`bad_syntax_line_after_comment.seq`) loads with the model of the valid file (but for the definitions and the signature): all its blocks are read.

**How:** The test reads the fixture and compares it with `valid_no_signature.seq`.

**Assumptions:** The reading is the user's choice (the specification is silent); `cpp-siemens` reads such a file differently.

#### `test_the_rows_after_a_comment_or_blank_line_of_any_section_are_read`

**Checks:** D2.5: a `#` line, a blank line or a line of spaces inside `[BLOCKS]`, `[GRADIENTS]`, the list of `[EXTENSIONS]`, a LABELSET table or a TRIGGERS table does not change the model: the rows after it are read.

**How:** For each case (parametrized), the test inserts the line after a row of a valid fixture and compares the model with the one of the fixture.

**Assumptions:** None.

#### `test_comments_and_blank_lines_are_skipped_after_the_header_of_any_section`

**Checks:** D2.5: a comment and a blank line right after the header of `[VERSION]`, `[DEFINITIONS]`, `[TRAP]`, `[SIGNATURE]` or `extension DELAYS` do not change the model, and a comment between `Type` and `Hash` of `[SIGNATURE]` does not change the hash.

**How:** The test inserts the lines after each header of the 1.5.1 fixture and compares the model without the signature (whose `matches` changes with the bytes).

**Assumptions:** None.

#### `test_a_comment_in_a_shape_is_skipped_and_a_blank_line_ends_it`

**Checks:** D2.5, D3.11: a `#` line among the samples of a shape and one between its `shape_id` and `num_samples` lines are skipped (`valid_comment_in_shape.seq` has the shapes of `valid_1_5_1.seq`). A blank line among the samples ends the shape: `syntax.shape` for the lines after it, and `shape.length`.

**How:** The test reads the fixture and compares the shapes and the model with those of the 1.5.1 fixture; then it adds a blank line among the samples of a shape and compares the set of rules.

**Assumptions:** None.

#### `test_a_blank_line_between_shape_id_and_num_samples_ends_the_shape`

**Checks:** D2.5, D3.11, spec:602: a blank line between `shape_id` and `num_samples` ends the shape: `syntax.shape` for the shape with no `num_samples` line (at its `shape_id` line, with no choice in the message) and for the lines after it.

**How:** The test inserts the blank line in a valid fixture and reads the file.

**Assumptions:** The record (D3.11) says that a shape without its two header lines is `syntax.shape`, also when a blank line comes between them.

#### `test_a_data_line_before_the_first_header_is_syntax_line`

**Checks:** D3.2: a data line before the first section header gives `syntax.line` at line 1, with the choice in the message. It is the only line outside a table that `spec` rejects.

**How:** The test reads `bad_syntax_line.seq`.

**Assumptions:** None.

#### `test_a_shape_with_no_blank_line_after_it_is_syntax_shape`

**Checks:** D3.11, spec:602: a shape followed by the next `shape_id` line (`bad_syntax_shape_no_blank_line.seq`, line 147) or by the end of its section (`bad_syntax_shape_end.seq`, line 178) gives `syntax.shape` with the choice in the message, which says "before it" or "after it".

**How:** The test reads both fixtures and compares the rule, the line, the choice and the text.

**Assumptions:** The rejection is the user's choice: the specification does not say what such a shape is.

#### `test_a_shape_ends_only_at_a_blank_line`

**Checks:** A `shape_id` line right after the samples of a shape, with no blank line between, is `syntax.shape` at the line of the `shape_id`, with the choice in the message. The shapes are still read, so the file has no other violation.

**How:** The test removes the blank line before each `shape_id` line of a valid fixture except the first, and checks that there is one `syntax.shape` violation for each, each at a `shape_id` line.

**Assumptions:** The specification (section 2.9) says that a blank line ends a shape.

#### `test_a_section_that_the_format_does_not_have_is_ignored`

**Checks:** D2.4: a section that the format does not have (`[FOO]`, also with lines that are not rows) is ignored: the model is that of the valid file (but for the definitions and the signature).

**How:** The test reads `bad_section_unknown.seq` and a valid fixture with a `[FOO]` section of junk lines, and compares the models.

**Assumptions:** The reading is the user's choice (the specification has no rule for another section).

#### `test_a_delays_section_is_ignored`

**Checks:** A `[DELAYS]` section in a 1.5.1 file is ignored (the model is that of the valid file), and `extension DELAYS` is still read.

**How:** The test reads `bad_section_delays.seq`, compares it and checks the soft delay table.

**Assumptions:** The reading is the user's choice; MATLAB Pulseq and pypulseq reject the section.

#### `test_a_section_that_appears_twice_is_section_duplicate_and_only_the_first_is_read`

**Checks:** D3.3: `bad_section_duplicate.seq` (a second `[TRAP]` with the ID of the first) gives `section.duplicate` at the header of the second copy (line 53), with the choice in the message, and no `id.unique`: only the first copy is read.

**How:** The test reads the fixture, checks the one violation and that its line is the second `[TRAP]` header.

**Assumptions:** The rejection is the user's choice (2026-10-13): the specification is silent, the readers disagree (the C++ reader keeps the last copy; MATLAB Pulseq and pypulseq add the copies of some sections and keep the last of others), and no writer writes one.

#### `test_any_named_section_and_any_extension_that_appears_twice_is_section_duplicate`

**Checks:** D3.3: a second `[BLOCKS]`, `[VERSION]` (also with one key of its own), `[DEFINITIONS]`, `[ADC]` or `[SHAPES]` section, and a second `extension TRIGGERS` section with the same type ID or another, give `section.duplicate` at the second header, once, with the choice in the message.

**How:** For each case (parametrized), the test inserts a second header in a valid fixture and reads the file. It looks at the `section.duplicate` violations only: the changed file may break other rules.

**Assumptions:** None.

#### `test_a_second_signature_section_and_an_extension_with_two_types_are_section_duplicate`

**Checks:** D3.3: a second `[SIGNATURE]` section (`bad_section_duplicate_signature.seq`) and an `extension` STRING_ID with two type IDs (`bad_section_duplicate_extension.seq`) give `section.duplicate` at the second header, with the choice in the message.

**How:** The test reads both fixtures and compares the rule, the section, the line and the choice.

**Assumptions:** None.

#### `test_a_version_key_repeated_in_one_section_is_version_invalid`

**Checks:** spec:193-198: a key repeated inside one `[VERSION]` section gives `version.invalid`, at the second row. (A key in a second copy of the section is `section.duplicate`.)

**How:** The test repeats `major 1` in a valid fixture.

**Assumptions:** None.

#### `test_a_last_section_with_no_blank_line_after_it_is_read`

**Checks:** D2.2: a file whose last section `[TRAP]` ends with no line end after its row loads, with the trapezoid and the blocks of the 1.5.1 fixture.

**How:** The test reads `valid_last_section_no_blank.seq`, checks that the file has no final line end, and compares the tables.

**Assumptions:** None.

#### `test_a_raster_that_is_not_one_finite_number_above_0_is_rejected`

**Checks:** spec:267-276: an RF raster of 0, -1e-6, nan, inf, a word, two numbers, or nothing gives `definitions.raster-invalid` at its line.

**How:** For each value (parametrized), the test changes `RadiofrequencyRasterTime` in a valid fixture and reads the file.

**Assumptions:** None.

#### `test_a_missing_raster_is_definitions_raster_missing`

**Checks:** spec:267-276: a file without one of the four rasters gives `definitions.raster-missing`, with the key in the message.

**How:** The test removes each of the four definitions from a valid fixture and reads the file.

**Assumptions:** None.

#### `test_a_definition_that_appears_twice_has_its_last_value`

**Checks:** D2.6: with `Name` twice (`bad_definitions_duplicate.seq`) the definition is the last; a raster defined twice has its last value.

**How:** The test reads the fixture and a valid fixture with a repeated `BlockDurationRaster`.

**Assumptions:** The reading is the user's choice (the specification is silent); the C++ reader, MATLAB Pulseq and pypulseq take the last too.

#### `test_a_definition_and_a_signature_hash_are_text_even_when_they_read_as_a_number`

**Checks:** D2.7: a hash of 32 digits, a definition `Name 007` and a definition `Exponent 1E5 +3` keep their text as written.

**How:** The test edits the 1.5.1 fixture and compares the signature hash and the definitions.

**Assumptions:** None.

#### `test_syntax_of_numbers_in_a_table`

**Checks:** An integer column rejects `3e1`, `0x1e` and `30.0` (`syntax.integer`) and reads `+30` as 30; a float column takes `1e+06`, `+1000000` and `1000000.`, and rejects `inf`, `1,5` and `1e999` (`syntax.number`).

**How:** The test changes one value of a valid fixture and reads it.

**Assumptions:** The syntax of numbers is not in the specification. These are the rules of `spec`: an integer is an optional sign and digits; a float has the form of a decimal number and is finite.

#### `test_an_integer_column_rejects_a_fraction_in_a_time`

**Checks:** spec:351, spec:396-399, spec:438: `100.5` as the delay of an RF event, as the rise of a trapezoid and as the delay of an ADC event gives `syntax.integer`.

**How:** The test changes each value of a valid fixture and reads the file.

**Assumptions:** None.

#### `test_nan_and_inf_in_a_float_column_are_syntax_number_with_the_choice`

**Checks:** D3.5: `nan`, `inf` and `-inf` in a float column give `syntax.number` with the choice in the message, whose reason is that they give no waveform, not the writers. The twelve cases cover the amplitude, `center`, `freq_offset` and `phase_offset` of an RF row, the amplitude and `first` of a gradient, the amplitude of a trapezoid, the dwell time and `freq_ppm` of an ADC, a soft delay offset, a quaternion and an RF shim value.

**How:** For each case (parametrized), the test changes one value of a valid fixture and reads the file.

**Assumptions:** The rejection is the user's choice (the specification does not say whether NaN and infinity are floats of a file).

#### `test_a_negative_time_or_count_is_syntax_negative_with_the_choice`

**Checks:** D3.6: a negative delay of an RF, gradient or trapezoid row, block duration, rise, flat or fall time, ADC number of samples or dwell time, trigger delay or duration, or shape `num_samples` gives `syntax.negative` with the choice in the message, which starts with the column name, at a row of the file. The reason of the choice is that a negative time or count gives no waveform, not the writers.

**How:** For each case (parametrized), the test changes one value of a valid fixture and reads the file. It looks at the `syntax.negative` violation only: a negative block duration also gives `block.event-too-long`.

**Assumptions:** The rejection is the user's choice (it is not literally spec:176).

#### `test_a_byte_that_is_not_utf8_is_syntax_encoding_at_its_line`

**Checks:** D3.1: a file with a byte that is not UTF-8 gives `syntax.encoding` only, at the line of the first such byte, with the choice in the message.

**How:** The test reads `bad_syntax_encoding.seq` (line 31), and a valid fixture with `\xb5` (Latin-1) in a comment, and checks the line.

**Assumptions:** The rejection is the user's choice (the specification gives no encoding).

#### `test_an_adc_dwell_time_is_a_float_in_ns_and_a_multiple_of_the_adc_raster`

**Checks:** `25000.0` is a dwell time of 25 us; `25000.5` reads with `AdcRasterTime` 1e-10 (a multiple), and is `raster.adc-dwell` with 1e-7.

**How:** The test changes the dwell time and the raster of a valid fixture, three ways.

**Assumptions:** None.

#### `test_a_soft_delay_offset_is_a_float_in_us_and_its_hint_is_kept_whole`

**Checks:** D2.16: the soft delay of `valid_soft_delay_fraction.seq` has the offset -100.5 us (-100.5e-6 s) and the hint `TE`; a hint of 40 characters is kept whole.

**How:** The test reads the fixture and a valid fixture with a long hint.

**Assumptions:** The reading is the user's choice (the specification has no table of types for this extension).

#### `test_the_rf_use_is_one_of_seven_letters`

**Checks:** spec:356-357: the RF `use` `e r i s p o u` loads; `x`, `E` and `ee` give `syntax.use`.

**How:** The test changes the `use` of a valid fixture ten times.

**Assumptions:** None.

#### `test_values_are_float64_with_all_their_digits`

**Checks:** An RF amplitude of `1000.123456789012` and a shape sample of `0.123456789012345` are read with all their digits (float64).

**How:** The test edits a valid fixture and compares the values exactly.

**Assumptions:** None.

#### `test_ids_that_are_not_positive_or_not_unique_are_rejected`

**Checks:** spec:181-183: a shape ID used twice gives `id.unique`, and a shape ID of -3 gives `id.positive`, with no choice in the message; the RF ID of `bad_id_positive.seq` too.

**How:** The test appends a shape to a valid fixture two ways, and reads the fixture.

**Assumptions:** None.

#### `test_a_gradient_id_is_unique_across_gradients_and_trapezoids`

**Checks:** spec:183, spec:403: an ID in both `[GRADIENTS]` and `[TRAP]` gives `id.gradient-unique` (`bad_id_gradient_unique.seq`).

**How:** The test reads the fixture.

**Assumptions:** None.

#### `test_a_repeated_block_id_is_id_unique_with_the_choice`

**Checks:** D3.4: a block ID that is used twice (after a larger ID, or after a smaller one) gives `id.unique` only, with the choice in the message.

**How:** The test changes the ID of one block of a valid fixture to a repeat, two ways.

**Assumptions:** The rejection is the user's choice: the specification states uniqueness for shapes and events only.

#### `test_blocks_play_in_file_order_whatever_their_ids`

**Checks:** spec:185, spec:318: `bad_blocks_order.seq` (block 3 before block 2) loads with the blocks in file order (IDs 1, 3, 2, ...); a file with the nine blocks in reverse order has the IDs 9 to 1.

**How:** The test reads the fixture and a valid fixture with its block rows reversed, and compares the IDs and a column.

**Assumptions:** None.

#### `test_a_reference_to_something_that_is_not_defined_is_ref_unresolved`

**Checks:** spec:178-186, spec:478: a block that names an RF, gradient, ADC or extension list that is not defined, an event that names a shape that is not defined (magnitude, phase, time, gradient waveform, gradient time, ADC phase), and an entry of `[EXTENSIONS]` with a next entry, a type or an object that is not defined, give `ref.unresolved` only.

**How:** For each case (parametrized), the test changes one reference in a valid fixture and reads the file.

**Assumptions:** None.

#### `test_time_id_minus_1_is_for_a_gradient_from_1_5_0_only`

**Checks:** D4.3, spec:349, spec:395, slide 4: time ID -1 gives `ref.unresolved` for an RF event (`undefined/rf_time_id_minus_1.seq`) and for a gradient of a 1.4 file (`bad_ref_time_id_minus_1_in_1_4.seq`); a gradient of a 1.5.1 file has it.

**How:** The test reads the two fixtures and `valid_1_5_1.seq`.

**Assumptions:** None.

#### `test_a_cycle_in_an_extension_list_is_ref_unresolved`

**Checks:** spec:478: a list of extensions that never ends gives `ref.unresolved` at the block that starts it, with "cycle" in the message.

**How:** The test reads `bad_ref_extension_cycle.seq`.

**Assumptions:** None.

#### `test_a_file_with_no_block_is_blocks_empty`

**Checks:** spec:318: a file with no block gives `blocks.empty`.

**How:** The test reads `bad_blocks_empty.seq`.

**Assumptions:** None.

#### `test_an_event_that_lasts_longer_than_its_block_is_block_event_too_long`

**Checks:** spec:318: an RF event, an ADC event and a trigger that end after their block give `block.event-too-long`, with the event named in the message.

**How:** The test reads the three fixtures.

**Assumptions:** None.

#### `test_a_time_that_is_not_a_multiple_of_its_raster_is_rejected`

**Checks:** spec:290, spec:275, slide 5: an ADC dwell time, a gradient delay, the end of a gradient with a time shape, a ramp and a flat time off their raster each give their rule only (`raster.adc-dwell`, `raster.gradient-delay`, `-end`, `-ramp`, `-flat`), with no choice in the message.

**How:** For each fixture (parametrized), the test reads it and checks the rule and the message.

**Assumptions:** None.

#### `test_a_gradient_that_is_not_aligned_to_its_block_is_rejected`

**Checks:** spec:420, slide 6: a gradient that starts above 0 and has a delay gives `gradient.nonzero-start-delay`; one that ends above 0 and does not end with its block gives `gradient.nonzero-end-align`.

**How:** For each fixture (parametrized), the test reads it and checks the rule and the message.

**Assumptions:** None.

#### `test_an_arbitrary_gradient_plays_on_the_raster_of_the_file`

**Checks:** `valid_arbitrary_gradient_5us_raster.seq` (gradient raster 5 us, block raster 10 us) loads, and its gradient is decoded on the raster of the file (the first sample times 2.5 us and 7.5 us).

**How:** The test reads the fixture and decodes its gradient with `synth.events`.

**Assumptions:** The test uses the decoder only for the times of the samples; the decoder has its own tests (`test_decoding.py`).

#### `test_a_raster_that_is_not_commensurate_with_the_block_raster_is_rejected`

**Checks:** Slide 11: a gradient raster of 4 us with a block raster of 10 us (`valid_arbitrary_gradient_4us_raster.seq`, a name that is historical: the file was valid) and an RF raster of 3 us with 10 us give `definitions.raster-commensurate`, with no choice in the message, which names the raster.

**How:** The test reads the fixture and a valid fixture with an RF raster of 3 us. In the second file other rules are broken too, so the test selects the violation.

**Assumptions:** None.

#### `test_a_raster_that_divides_or_is_a_multiple_of_the_block_raster_is_commensurate`

**Checks:** Slide 11: a gradient raster of 5 us (a divisor of 10 us) and an RF raster of 20 us (a multiple) load.

**How:** The test reads `valid_arbitrary_gradient_5us_raster.seq` and a valid fixture with an RF raster of 20 us and a longer first block (for its RF event of 100 samples).

**Assumptions:** None.

#### `test_an_rf_or_adc_event_must_start_on_an_edge_of_the_rf_raster`

**Checks:** Slide 9, slide 10, spec:290: with an RF raster of 2 us, an RF event with delay 99 us gives `raster.rf-delay` and an ADC with delay 101 us gives `raster.adc-delay`, with no choice in the message; the same files with 100 us load.

**How:** For each fixture (parametrized), the test reads it, checks the rule, changes the delay to 100 us and reads the file.

**Assumptions:** None.

#### `test_a_shape_that_does_not_have_its_declared_number_of_samples_is_shape_length`

**Checks:** spec:626: a shape that decompresses to more samples than declared (`undefined/shape_decompress_longer.seq`) or fewer (`bad_shape_length.seq`, and 10 uncompressed values with 11 declared) gives `shape.length` only, with no choice in the message.

**How:** The test reads the two fixtures and a valid fixture with `num_samples 11` for a shape of 10 values.

**Assumptions:** None.

#### `test_an_amplitude_shape_must_be_in_minus_1_to_1_to_within_the_tolerance`

**Checks:** spec:624: the magnitude shape of an RF event and the waveform of an arbitrary gradient with a sample beyond 1 in absolute value by more than `RANGE_TOLERANCE` (1e-9) give `shape.range` once for the shape, with no choice in the message; samples within the tolerance, and a gradient sample of -5e-10, load.

**How:** The test (eight cases) replaces shape 1 (the RF magnitude, 100 samples) or shape 4 (a gradient waveform, 10 samples) of `valid_no_signature.seq` and reads the file.

**Assumptions:** The tolerance is the package's choice (MATLAB Pulseq writes 9 significant digits). The test does not cover a sample at exactly 1 + `RANGE_TOLERANCE`.

#### `test_a_negative_rf_magnitude_plays_as_written`

**Checks:** D2.8, spec:624: `bad_shape_rf_magnitude_negative.seq` (a magnitude of -0.5) loads; its shape has the samples as written and its decoded event has a negative magnitude (-500 Hz for an amplitude of 1000).

**How:** The test reads the fixture and decodes its RF event with `synth.events`.

**Assumptions:** The decoder has its own tests; this checks only that the sign is kept.

#### `test_an_rf_phase_shape_plays_as_written_with_no_range`

**Checks:** D2.9: `bad_shape_rf_phase_range.seq` (a phase of 1.5 turns) loads; its shape has the samples as written and its decoded event has the phase 3 pi, with no wrap.

**How:** The test reads the fixture and decodes its RF event.

**Assumptions:** None.

#### `test_an_unused_shape_id_0_is_not_taken_for_the_time_shape_of_the_default_raster`

**Checks:** Regression: a shape with the ID 0, with three samples that are not on the raster or with none, that no event uses gives `id.positive` only, and no `raster.gradient-vertex`, `shape.time-order` or `shape.empty` (time ID 0 is the default raster, not a shape).

**How:** The test appends the shape to a valid fixture, two ways (parametrized in the test body), and reads the file.

**Assumptions:** None.

#### `test_the_phase_shapes_have_no_range_and_a_gradient_shape_may_be_negative`

**Checks:** D2.8, D2.9, D2.15: a gradient waveform of -0.5, an RF phase shape with the samples -3 and 100, and an ADC phase shape with the samples -2 and 3 load.

**How:** The test replaces shape 4 (a gradient), shape 2 (the RF phase) and shape 8 (the phase of an ADC) of `valid_no_signature.seq` and reads each file.

**Assumptions:** The test does not check a shape that an RF event and a gradient share.

#### `test_a_shape_with_no_sample_that_an_event_uses_is_shape_empty`

**Checks:** D3.7: a shape with `num_samples 0` that an RF event uses (magnitude and phase, or magnitude, phase and time shape) or that an arbitrary gradient uses (waveform, or waveform and time shape) gives `shape.empty` once for each empty shape that is used, with the choice in the message. As the phase shape of an ADC it also gives `shape.event-length` (it has no sample for each ADC sample).

**How:** The test (six cases) changes one row of `valid_no_signature.seq`, adds the shapes 10 and 11 with `num_samples 0` at the end of `[SHAPES]`, and reads the file. It counts the violations.

**Assumptions:** The rule is the user's choice: the specification is silent. The test does not cover a shape that is empty with samples after it, which is also `shape.length`.

#### `test_an_unused_empty_shape_is_read`

**Checks:** D3.7: a shape with no sample that no event uses loads.

**How:** The test adds shape 10 with `num_samples 0` to a valid fixture and reads it.

**Assumptions:** None.

#### `test_the_shapes_of_one_event_must_have_one_number_of_samples`

**Checks:** D3.8, spec:349, spec:443: an RF event whose phase, magnitude or time shape has another number of samples than the others, and a gradient whose time shape has another number than its waveform (shorter or longer), give `shape.event-length` with the choice in the message.

**How:** The test (five cases) changes one reference of a valid fixture and reads the file.

**Assumptions:** The rejection is the user's choice (the specification is silent).

#### `test_the_shapes_of_one_event_with_one_number_of_samples_read`

**Checks:** D3.8: the gradient of `valid_1_5_1.seq` has a waveform and a time shape of 5 samples each.

**How:** The test compares the `num_samples` of the two shapes.

**Assumptions:** None.

#### `test_a_regular_rf_time_shape_is_cells_and_any_other_is_points`

**Checks:** D2.10, spec:349, slide 9, slide 4: in `valid_rf_time_shapes.seq`, the time shape `1 2 2 47` (RF 2) and `0.5 1.5 2.5` (RF 3) are regular (`rf_time_step` 2 and 1, decoded as cells of 2 us and 1 us), and the block pulse `0 100` (RF 4) and the vertices `1 2 4 7 10` (RF 5) are points (`rf_time_step` None, no dwell).

**How:** The test reads the fixture, calls `rf_time_step` on the time shapes and decodes the RF events with `synth.events`.

**Assumptions:** The split (equal steps, first time half a step) is the package's choice.

#### `test_an_rf_time_shape_of_points_is_joined_by_straight_lines_of_the_complex_signal`

**Checks:** D2.11: for the vertices of RF 5, the decoded times are those of the file, and the signal halfway between the first two points is the mean of the two complex values (100 + 300i), and is 0 before the first time and after the last.

**How:** The test decodes the RF event and calls `signal` at three times.

**Assumptions:** The straight line of the complex signal is the user's choice.

#### `test_an_rf_time_shape_that_other_tools_write_is_read`

**Checks:** D2.10, D2.11: `bad_shape_rf_time_grid.seq` (`1 1 98`, times 1 to 100) and `bad_shape_rf_time_end.seq` (times 0 and 99.6) load and are points that end at their last time (100 us, 99.6 us); so does `1 1 98` in a new file.

**How:** The test reads the fixtures and a new file, and decodes the RF event.

**Assumptions:** The two fixtures were rejected by the interim reader; their names are historical.

#### `test_the_end_of_an_rf_event_with_a_time_shape_is_n_dwells_or_the_last_time`

**Checks:** D2.12, slide 9: an RF event with a delay of 100 us in a block of 300 us. A regular shape of 100 samples with a step of 2 RF rasters ends at 300 us and loads; with a step of 4 it ends at 500 us (`block.event-too-long`). Points that end at 200 us load; at 200.5 us they end after the block (`block.event-too-long`).

**How:** The test (five cases) writes the file with a time shape of the case and reads it.

**Assumptions:** The end of a pulse of points is the last time (the user's choice).

#### `test_an_rf_time_shape_that_defines_no_line_is_shape_time_order`

**Checks:** D2.10-D2.12, D3.9: an RF time shape of one sample at 0 or below 0, with times that do not increase (decreasing, or equal), or with a first time below 0 gives `shape.time-order` once, with the choice in the message; `bad_shape_time_order.seq` (`100 -1 -1 97`) too.

**How:** The test (five cases) writes the file with a time shape of the case, reads it and checks the message; then it reads the fixture.

**Assumptions:** The rejection is the user's choice.

#### `test_an_rf_time_shape_of_one_sample_above_0_is_one_cell`

**Checks:** D3.9, D2.10: an RF time shape of one sample `5` (the file that MATLAB Pulseq writes for an arbitrary pulse of one sample with a dwell of 10 µs) reads: `rf_time_step` gives 10, and the decoded RF event has a dwell of 10 µs, a `shape_dur` of 10 µs, and its sample at 5 µs.

**How:** The test writes a valid fixture with an RF event of one sample on that time shape (RF raster 1 µs), reads it and decodes the RF events.

**Assumptions:** The user's decision (2026-10-13): one sample `t0` above 0 is one cell of `2 t0`, the form `(i + 0.5) d` with N = 1.

#### `test_a_gradient_time_shape_must_increase_and_have_its_vertices_on_the_raster`

**Checks:** A vertex of a gradient time shape off the gradient raster gives `raster.gradient-vertex` (`bad_raster_gradient_vertex.seq`, `0 1.5 3 6 10`); times that decrease or repeat give `shape.time-order`. Both have the choice in the message.

**How:** The test reads the fixture, and a valid fixture with a time shape that decreases or repeats.

**Assumptions:** The slides conflict about the vertices (slide 6 against slide 4); the rejection is the package's choice.

#### `test_a_1_4_gradient_with_a_time_shape_must_start_at_time_0`

**Checks:** In a 1.4.1 file, an arbitrary gradient whose time shape starts at 0, 5e-7 or -5e-7 gradient rasters loads. One that starts at 2e-6 or 0.5 gives `layer1.gradient-ends` and `raster.gradient-vertex` (the first time is a vertex off the raster). A 1.5.1 file with a time shape that starts at 0.5 gives no `layer1.gradient-ends`.

**How:** The test (five cases) changes the first sample of the time shape 4 of `valid_1_4_1.seq` and the time shape 6 of `valid_1_5_1.seq`, writes the files to `tmp_path` and reads them.

**Assumptions:** The tolerance of 1e-6 gradient rasters (`FIRST_TIME_TOLERANCE`) is a choice of this package.

#### `test_a_1_4_gradient_with_no_values_at_its_ends_is_layer1_gradient_ends`

**Checks:** D4.4: `bad_layer1_gradient_ends.seq` and the two 1.4.x oracle files with a gradient on the default raster give `layer1.gradient-ends` once, with the choice in the message.

**How:** The test reads the three files.

**Assumptions:** The rejection is the user's choice.

#### `test_an_arbitrary_gradient_on_the_default_raster_has_a_sample_at_each_cell_centre`

**Checks:** D2.13, spec:290, slide 7: the decoded gradient 3 of `valid_1_5_1.seq` has its samples at `(i + 0.5)` gradient rasters, `first` 0 and `last` 500000 Hz/m from the file, and lasts 100 us.

**How:** The test decodes the gradients with `synth.events`.

**Assumptions:** The straight lines between the points are drawn by `seq_utils.gradient_offsets`, which this test does not check.

#### `test_an_oversampled_gradient_has_its_samples_half_a_raster_apart_and_an_odd_count`

**Checks:** spec:395, spec:420, slides 4 and 8: `bad_shape_oversampled_length.seq` (time ID -1 with 4 samples) gives `shape.oversampled-length`, with no choice in the message; the decoded oversampled gradient of `valid_1_5_1.seq` (5 samples) has its samples half a raster apart and lasts 3 half rasters.

**How:** The test reads the fixture and decodes the gradients of the 1.5.1 fixture.

**Assumptions:** The odd count is derived from the slides, not stated.

#### `test_the_phase_modulation_of_an_adc_event_is_in_rad_one_value_for_each_sample`

**Checks:** D2.15, D3.8, spec:443, spec:120: `bad_shape_adc_phase_length.seq` (9 samples for 8) gives `shape.event-length` with the choice in the message; an ADC phase shape of 8 samples is decoded as the same 8 values, with no factor.

**How:** The test reads the fixture, then replaces shape 8 of a valid fixture with eight values and decodes the ADC events.

**Assumptions:** The unit rad is the user's choice (the specification gives no unit).

#### `test_an_unknown_extension_that_is_not_required_is_skipped`

**Checks:** D2.17, spec:460: the unknown extensions of `koma_v1.5_unknown_ext.seq` and of `valid_1_5_1.seq` are in `skipped_extensions`; their type IDs are in `type_ids`.

**How:** The test reads both files.

**Assumptions:** None.

#### `test_a_file_whose_last_header_is_extensions_is_read`

**Checks:** D2.3: `koma_v1.5_unknown_ext.seq`, whose last section that starts with `[` is `[EXTENSIONS]`, loads.

**How:** The test checks the last header of the file and reads it.

**Assumptions:** None.

#### `test_a_required_extension_that_is_not_known_is_extension_required_unknown`

**Checks:** spec:460: a required extension that `spec` does not know gives `extension.required-unknown` at the definition, with no choice in the message.

**How:** The test reads `bad_extension_required_unknown.seq`.

**Assumptions:** None.

#### `test_a_block_with_two_rotations_or_two_rf_shims_is_extension_per_block`

**Checks:** spec:567, spec:584: two blocks of `bad_extension_per_block.seq` that have two ROTATIONS objects, and a block with two RF_SHIMS objects, give `extension.per-block` with the count in the message and no choice.

**How:** The test reads the fixture, and a valid fixture with an entry added to the list of block 9.

**Assumptions:** None.

#### `test_rotation_quaternions_are_normalized_and_a_quaternion_of_norm_0_is_rejected`

**Checks:** D2.18, D3.10, P20, spec:567: from 1.5.1 each quaternion of ROTATIONS is divided by its norm: the quaternion of `valid_1_5_1.seq` has norm 1 in the model, `1 1.01 0 0 0` is `1 1 0 0 0` and `0 3 4 0` is `0 0.6 0.8 0`. A quaternion `0 0 0 0` gives `rotation.zero` at its row, with the choice in the message.

**How:** The test reads the 1.5.1 fixture and takes the norm of the table, then edits the table of `valid_no_signature.seq` two ways and reads each file.

**Assumptions:** The normalization and the rejection are the user's choice (P20). Applying the rotation is task R9's, not tested here. `rotation.zero` has no fixture (it is in `NO_FIXTURE`); this test writes the file.

#### `test_what_spec_ignores_is_in_the_records_in_file_order`

**Checks:** P20, D2.4, D2.17, D2.19, D4.6: `SequenceData.records` has a `Record(kind, subject, reason, line)` for each thing that `spec` ignores, in file order: the unknown extension of `valid_1_5_1.seq`; ROTATIONS and RF_SHIMS (reason `version`) and UNKNOWN (reason `unknown`) of `valid_1_5_0_extensions_of_1_5_1.seq`; the unknown label `FOO` and the unknown extension of `valid_label_unknown.seq`; the section `[FOO]` (`unknown`) of `bad_section_unknown.seq` and `[DELAYS]` (`removed`) of `bad_section_delays.seq`; none for `valid_1_4_0.seq`. The line is that of the header or of the label row.

**How:** The test reads each file and compares the records with the ones that it builds, with the line numbers searched in the text of the file.

**Assumptions:** The subject of a section is its header as in the file (`[FOO]`).

#### `test_the_records_of_labels_and_of_an_extension_of_a_later_revision`

**Checks:** D2.19, D4.6, spec:519-520, spec:526, spec:545: `NOSCL` (a misspelling of `NOSLC`) is an unknown label; `PMC` in a 1.4.1 file has no record and in a 1.4.0 file has the reason `version`; `extension DELAYS` in a 1.4.1 file is an extension with the reason `version`. The label rows stay in the label table.

**How:** The test edits `valid_1_4_1.seq` four ways and compares the records and the label table.

**Assumptions:** None.

#### `test_a_label_that_is_not_known_is_kept_as_text`

**Checks:** D2.19, spec:519-520, spec:526: the label `FOO` (`valid_label_unknown.seq`) and the name `PMC` in a 1.4.0 and a 1.4.1 file are kept as text in the LABELSET table.

**How:** The test reads the fixture and edits `valid_1_4_1.seq`.

**Assumptions:** None.

#### `test_two_events_with_equal_values_and_different_ids_are_both_kept`

**Checks:** The trapezoids 39 and 40 of `pypulseq_simple_mprage150.seq` (amplitudes 0 and -0) are both in the model, with their IDs and the sign of the zero, and the rise time of 1e-5 s.

**How:** The test selects the rows by ID.

**Assumptions:** None.

#### `test_the_model_has_no_value_of_a_scanner`

**Checks:** The rasters of the model are the four of the file, and no value of a scanner (`test_model_without_values_of_a_target` checks the fields).

**How:** The test compares the field names of `Rasters`.

**Assumptions:** The row of the plan says that the file holds no value of a scanner; this checks that the model adds none.

#### `test_a_signature_hash_covers_the_bytes_before_the_newline_that_precedes_it`

**Checks:** spec:223: `valid_1_5_1.seq` matches; `valid_crlf.seq` (CRLF line ends, signed by the rule of the C++ reader) does not, and is read.

**How:** The test reads both fixtures.

**Assumptions:** None.

#### `test_a_signature_section_must_have_a_type_and_a_hash`

**Checks:** spec:223-232: a `[SIGNATURE]` section without `Hash` (`bad_signature_invalid.seq`), with `Hash` of no or two values, or without `Type` gives `signature.invalid`; an additional key loads, and the last of a repeated `Hash` is used.

**How:** The test reads the fixture and edits the 1.5.1 fixture five ways.

**Assumptions:** The last value of a repeated key is the choice of `spec` (D3.3).

#### `test_an_extension_header_has_a_word_and_a_type_id`

**Checks:** D1.4, spec:493, spec:498, spec:507: the STRING_ID is a word and the type ID an integer. A type that is not an integer gives `syntax.integer`; a header with one word or three gives `syntax.columns`.

**How:** The test reads the 1.5.1 fixture and edits the LABELSET header three ways.

**Assumptions:** None.

#### `test_the_extensions_of_a_later_revision_are_skipped_in_an_older_file`

**Checks:** The version gate: in `valid_1_5_0_extensions_of_1_5_1.seq` (1.5.0), ROTATIONS and RF_SHIMS are in `skipped_extensions` (with UNKNOWN), their tables are empty, their type IDs are in `type_ids`, and the soft delay (from 1.5.0) is read. In a 1.4.1 file `extension DELAYS` is skipped and its rows are not read.

**How:** The test reads the fixture and a 1.4.1 fixture with a `DELAYS` section of a row that is not a table.

**Assumptions:** The versions are the user's decision.

#### `test_required_extensions_is_an_extension_rule_from_1_5_1_only`

**Checks:** In a 1.5.0 file, the definition `RequiredExtensions` is an ordinary definition: the file
loads with an unknown name in it, and `required_extensions` is empty.

**How:** The test adds `RequiredExtensions FOO` to the 1.5.0 fixture.

**Assumptions:** The concept of required extensions is from 1.5.1 (the specification).

#### `test_an_empty_file_and_a_file_with_only_a_version_list_what_is_missing`

**Checks:** An empty file gives `version.missing`. A file with only a version gives the four missing
rasters and no block.

**How:** The test writes both files and compares the rules.

**Assumptions:** None.

#### `test_a_comment_with_a_non_ascii_character_is_read`

**Checks:** A comment line with a non-ASCII character (µ) does not change the model.

**How:** The test adds the character to a comment line of a valid fixture and compares the model with
the one of the fixture.

**Assumptions:** The file is UTF-8.

#### `test_comments_and_blank_lines_between_sections_are_read_as_nothing`

**Checks:** A file with comment lines and blank lines before each of nine section headers (and a comment
after the `[SIGNATURE]` header) loads with all its blocks, shapes and extensions.

**How:** The test reads `valid_comments_between_sections.seq` and checks the blocks, the number of
shapes and the label table. The file has no unknown extension, so that the C++ reader can read it too.

**Assumptions:** None.

#### `test_sample_lines_of_two_values_are_syntax_number`

**Checks:** A file whose every sample line has two values gives `syntax.number` only, with the
message of a sample that is not one finite number.

**How:** The test adds a second value, 0, to each sample line of a valid fixture.

**Assumptions:** Before the reader was built on the "as written" reading, `numpy.loadtxt` read
such lines as a table of two columns, and the error was `shape.length` with numpy's message. The
test covers the case where every sample line has the same number of values; a file with a mix
was `syntax.number` before too.

#### `test_a_nan_or_inf_shape_sample_is_syntax_number_with_the_choice`

**Checks:** D3.5: a shape sample `nan` or `inf` gives `syntax.number` with the choice; `1,5` gives it without; `+0.4` is read as 0.4.

**How:** The test replaces one sample of a valid fixture and reads the file four times.

**Assumptions:** None.

#### `test_the_same_file_with_revision_1_5_1_reads_the_1_5_1_extensions`

**Checks:** The version gate: the file of `valid_1_5_0_extensions_of_1_5_1.seq` with `revision 1` reads ROTATIONS and RF_SHIMS and skips only UNKNOWN.

**How:** The test changes the revision and reads the file.

**Assumptions:** None.

#### `test_random_edits_of_valid_files_give_a_model_or_a_seqfile_error`

**Checks:** After a random edit of a valid fixture (a deleted, repeated, changed or cut line, or a
line added), `read_seqfile` gives a model, `SeqFileError` with at least one violation, or
`NotSupported` (an edit of the version), and raises no other exception.

**How:** The test makes 400 edits with a seeded random generator and reads each file. It checks that
some files load and more than 100 do not.

**Assumptions:** The edits are random pieces (`nan`, `-1`, a very large integer, a section header);
this does not cover every possible edit.

#### `test_decompress_shape_of_the_three_examples_of_the_specification`

**Checks:** `decompress_shape` gives the shapes of the three examples of the specification (section
2.9.1): the ramp, the constant and the ramp down (15 samples), 100 zeros, and 100 ones.

**How:** The test decompresses the stored values of the examples (`... 0 0 4 ...`, `0 0 98`,
`1 0 0 97`) and compares the samples.

**Assumptions:** The stored values of example 1 were read from the table of the specification (the
derivative with the run `0 0 4` of six zeros, and `-0.25 -0.25 2`).

#### `test_decompress_shape_keeps_a_shape_with_as_many_values_as_samples`

**Checks:** A shape with as many stored values as `num_samples` is uncompressed, also where two
values are equal.

**How:** The test decompresses `[0.5, 0.5, 3, 1]` with `num_samples` 4.

**Assumptions:** The specification says this (section 2.9).

#### `test_decompress_shape_of_values_that_look_like_a_repeat`

**Checks:** Shapes whose stored values have a repeat count equal to the next value, or a value three
times, are decompressed to the original samples.

**How:** The test compresses three shapes with the compression of the test and decompresses them.

**Assumptions:** The compression of the test (`_compress`) follows the specification: a run of two
or more equal derivative values is stored as the value twice and the number of further repeats.

#### `test_decompress_shape_inverts_compress_on_random_shapes`

**Checks:** For 300 random shapes of integer values, with and without repeats, `decompress_shape` of
the compressed form gives the original shape, and more than 50 of them are compressed.

**How:** The test compresses with `_compress` (a run-length code of the derivative, uncompressed when
it is not shorter) and decompresses.

**Assumptions:** The shapes have integer values, so the sums are exact. The test cannot find an error
that `_compress` has too.

#### `test_decompress_shape_rejects_a_code_that_is_not_num_samples_long`

**Checks:** `decompress_shape` raises `ValueError` with a message that says why, when the code gives
more or fewer samples than `num_samples`, when a repeat is cut at the end, and when a repeat count
is negative or not a whole number.

**How:** The test decompresses six stored shapes (parametrized) and matches the message.

**Assumptions:** None.

#### `test_a_shape_of_the_file_is_decompressed_to_num_samples_when_read`

**Checks:** The shapes of the 1.5.1 fixture decompress to the number of samples that they declare,
and a compressed shape gives the values that the text means.

**How:** The test decompresses shapes 9 and 2.

**Assumptions:** None.

#### `test_model_arrays_are_read_only_and_cannot_be_made_writable`

**Checks:** Each array of the model is read-only, writing to it raises `ValueError`, and
`flags.writeable = True` raises `ValueError` also for a field view of a structured array.

**How:** The test tries both on the tables, a shape and an RF shim.

**Assumptions:** None.

#### `test_model_mappings_and_fields_cannot_be_changed`

**Checks:** The mappings of the model refuse an assignment (`TypeError`), a field cannot be set
(`FrozenInstanceError`, also in `Rasters` and `Shape`), and the sequences of the model are tuples.

**How:** The test tries to change each.

**Assumptions:** None.

#### `test_model_without_values_of_a_target`

**Checks:** `SequenceData` has exactly the fields of the plan (with `records`, `interpreter` and `reading`, the things that were ignored, the interpreter that read the file and the C++ reader's object), and no table has a field for a dead time, a ringdown time, gamma, B0 or a limit.

**How:** The test compares the names of the fields and searches the field names of the tables.

**Assumptions:** The search words are those of the plan.

#### `test_models_are_equal_by_value_and_not_hashable`

**Checks:** Two reads of one file are equal (also with NaN in `center`), models of two files are not,
a model is not equal to a string, `hash` raises `TypeError`, and a changed number makes the models
different.

**How:** The test reads fixtures twice and compares them, and changes one RF amplitude.

**Assumptions:** None.

#### `test_models_survive_pickle_and_deepcopy_with_their_values_and_immutability`

**Checks:** A copy from `pickle` or `copy.deepcopy` is equal to the model, and has read-only arrays
and read-only mappings.

**How:** The test copies the 1.5.1 model both ways and repeats the immutability checks on the copy.

**Assumptions:** None.

#### `test_oracle_file_loads_or_breaks_the_rule_that_it_must`

**Checks:** Each oracle file of version 1.4 or later loads, except the 1.4.x files with a gradient on
the default raster, which break `layer1.gradient-ends` only. The version is the one of the file, and
`signature.matches` is the recorded value.

**How:** For each file (parametrized), the test reads it and compares the version, the violation and
the signature.

**Assumptions:** The recorded signature values come from one run of the parser. For the files that
MATLAB wrote they are `True`, except `koma_v1.4_epi.seq`, which differs from the file that was
signed. The test cannot tell whether the parser is wrong for that file, except by the MD5 check that
the other files pass.

#### `test_oracle_directory_has_the_files_of_the_test_and_sources_md_names_each`

**Checks:** The oracle folder has the files of the test and no other, and `SOURCES.md` names each.

**How:** The test lists the folder and searches `SOURCES.md` for each name in backticks.

**Assumptions:** None.

#### `test_oracle_corpus_has_each_feature_of_the_task`

**Checks:** The oracle files that load cover 1.4 and 1.5.x, gradients with time ID 0, -1 and a time
shape, compressed and uncompressed shapes, labels, triggers, soft delays, rotations, a skipped
extension, a required extension, a signature that matches, and an ADC phase shape.

**How:** The test reads the files and searches the tables.

**Assumptions:** None.

#### `test_oracle_amplitude_shapes_are_within_the_tolerance_of_the_range`

**Checks:** The largest excess of an RF magnitude shape or gradient waveform of the oracle files over 1
is below 1e-12, far below `RANGE_TOLERANCE` (1e-9), so the tolerance does not let an oracle file
load.

**How:** The test decompresses the amplitude shapes of the files that load and takes the maximum.

**Assumptions:** The tolerance is chosen above the excess of the corpus (1.3e-15) because MATLAB
writes a shape with 9 significant digits; the corpus does not show that choice to be right.

#### `test_oracle_spiral_of_1_5_has_the_oversampled_gradients_of_the_file`

**Checks:** The 1.5.1 spiral has gradients with time ID -1, and their waveforms have an odd number
of samples.

**How:** The test selects the rows with `time_id` -1 and checks `num_samples`.

**Assumptions:** The odd number of samples is the layout of an oversampled waveform (`Sequence.m`
of MATLAB Pulseq asserts it).

#### `test_oracle_fid_of_the_pulseq_repository_has_the_values_of_the_text`

**Checks:** The first blocks of `pulseq_fid.seq` have the durations and the RF IDs of the text, and
the block durations in seconds.

**How:** The test compares the block table with the first rows of the file.

**Assumptions:** The numbers are those of the first rows of the file.

#### `test_oracle_1_4_gradient_with_a_time_shape_has_its_end_samples`

**Checks:** The gradient of `koma_v1.4_gr-time-shaped.seq` has the amplitude, the time ID and the
delay of the text, `first` and `last` 0 (the end samples of its waveform), and its time shape is the
list of the text.

**How:** The test reads the file and compares the row and the decompressed time shape.

**Assumptions:** The waveform of that file starts and ends at 0 (the text shows it).

#### `test_oracle_label_extensions_of_a_1_4_file`

**Checks:** A 1.4.0 file gives its LABELSET rows with the label names and values of the text, and its
LABELINC row.

**How:** The test compares the label tables of `koma_v1.4_label_test.seq`.

**Assumptions:** None.

#### `test_oracle_unknown_extension_is_skipped_and_a_required_one_is_listed`

**Checks:** The two unknown extensions of `koma_v1.5_unknown_ext.seq` are skipped and have type IDs, and `RequiredExtensions` of `koma_v1.5_rotation_radial_tiny.seq` is `ROTATIONS`, with the real parts of the three quaternions of its rows (normalized, so equal to those of the file to 1e-5).

**How:** The test compares the fields.

**Assumptions:** None.

### 2.20 The C++ oracle (`test_cpp_oracle.py`)

`test_cpp_oracle.py` tests `pulseq-cpp-oracle`, the program that `flake.nix` builds from the
driver in `tests/cpp_oracle/` and the reader `ExternalSequence` of pulseq/pulseq (the reader of
the Pulseq interpreter on the scanner; MIT; the commit is in `flake.nix`). The program reads one
`.seq` file with `ExternalSequence::load` and then decodes each block with `decodeBlock`, as the
scanner does when it runs a sequence. It exits 0 when the file loads and each block decodes, 1
when it does not (the messages are on stderr), and 70 when the reader receives a signal such as
SIGSEGV. The devShell and the `ci` devShell have the program on the PATH. The whole module skips
when it is not on the PATH. The test helper counts an exit status other than 0 and 1, and a run
that takes more than 10 s, as a "crash". A cycle in an extension list makes the reader loop with
no end, so a file with such a cycle costs the 10 s.

The comparison with the package is with the `spec` interpreter (the default of `read_seqfile`).
The tables `NOT_CHECKED_BY_THE_READER` and `ORACLE_KNOWN_WRONG` of the module list each file on
which the two verdicts differ, with the entry of `docs/discrepancies.md` that explains it.

#### `test_the_oracle_accepts_a_minimal_valid_file`

**Checks:** The oracle accepts a Pulseq 1.5.0 file of one block (a delay), with the four
rasters in `[DEFINITIONS]`.

**How:** The test writes the text of the file to `tmp_path`, runs the oracle and checks that the
exit status is 0.

**Assumptions:** The test shows that the program runs and that it accepts one file. It does not
test that the file is valid by another reader.

#### `test_the_oracle_rejects_a_file_without_a_required_part`

**Checks:** The oracle rejects the minimal file when `GradientRasterTime` is removed from
`[DEFINITIONS]`, and when the `[VERSION]` section is removed. It exits with 1 and prints a
message with `ERROR`.

**How:** The test (two cases) removes the line or the section from the text of the minimal file
with a regular expression, checks that the text changed, runs the oracle on it and checks the
exit status and the message.

**Assumptions:** The test does not check the text of the message beyond `ERROR`. Its two
cases are two of the checks that the reader does when it loads a file.

#### `test_the_oracle_does_not_accept_a_file_that_it_cannot_decode`

**Checks:** A file with one RF event whose phase shape is not in `[SHAPES]`, one whose time
shape is not there, and one whose phase shape has `num_samples 0` is a rejection or a crash of
the oracle, not an acceptance. On the aarch64-darwin build, each of the three ends with exit
70 (a crash).

**How:** The test (three cases) writes the file (the minimal file with an RF event of 6 samples
and the shapes of the case), runs the oracle and checks that the verdict is "reject" or "crash".

**Assumptions:** The test does not tell a rejection from a crash, because the result depends on
the build of the reader (a build can end the process with a signal where another reports an
error). It does not check that the oracle crashes the same way on every platform.

#### `test_the_oracle_accepts_the_rf_file_with_both_shapes`

**Checks:** The file of the previous test with both shapes defined (6 samples each, time shape 0)
is accepted: the files of that test are rejected because of their shapes, not because of
the RF event.

**How:** The test writes the file, runs the oracle and checks that the verdict is "accept".

**Assumptions:** The test does not test that the file is valid by another reader.

#### `test_the_skip_of_the_comparison_is_for_an_arbitrary_gradient_off_the_10_us_raster_only`

**Checks:** The rule of the skip of the comparison (`arbitrary_gradient_off_the_10_us_raster`) is
true for the 5 us fixture, false for `valid_1_5_1.seq` (arbitrary gradients on 10 us), and false
for the 5 us fixture with a trapezoid (5, 10 and 5 us) in place of the arbitrary gradient.

**How:** The test reads each file with `read_seqfile` (the `spec` interpreter) and applies the rule
to the model (the rows of `grad` that the blocks use, and `rasters.gradient`). It writes the
trapezoid file to `tmp_path`.

**Assumptions:** The rule uses the 1e-3 us tolerance on the raster that `decodeBlock` uses. The rule
needs a model that `spec` reads, so it cannot be applied to the 4 us fixture.

#### `test_the_oracle_rejects_an_arbitrary_gradient_on_a_5_us_raster_and_accepts_it_on_10_us`

**Checks:** The oracle rejects `valid_arbitrary_gradient_5us_raster.seq` (which `spec` reads) with the
message "decodeBlock returned false for block 0", and accepts the same file with
`GradientRasterTime` 1e-05 and a block of 100 us. So the skip of the comparison is needed, and the
raster is the cause.

**How:** The test runs the oracle on the fixture, changes the text of the file (the raster and the
block duration), writes it to `tmp_path` and runs the oracle on it.

**Assumptions:** The message text is that of the driver, not of the reader (the reader prints its
text on a debug level only). The test shows the effect on one file. `valid_arbitrary_gradient_4us_raster.seq`
is no longer the file of this test: `spec` rejects it (`definitions.raster-commensurate`).

#### `test_the_oracle_and_spec_check_the_same_signature_hash_of_an_lf_file`

**Checks:** For the two signed files built from the minimal file where `spec` and the oracle hash
the same bytes (an LF file with one empty line before `[SIGNATURE]`, and the same with a line of 255
bytes and then its line end before the empty line), the oracle reports `signature_ok` true and `spec`
gives `matches` true when the stored md5 is that of the bytes before `[SIGNATURE]` less the empty
line right before it. With the md5 of other bytes, both report false.

**How:** The test (parametrized, two cases) writes the file with the bytes to hash stated in the test,
runs the oracle with `--dump` for `signature_ok` and calls `read_seqfile` for `matches`.

**Assumptions:** The test needs an oracle with `--dump`. `spec` hashes the bytes before the `\n`
that precedes `[SIGNATURE]` (spec:223); for an LF file with exactly one empty line this is the
oracle's rule. The cases where the rules differ are in the next test.

#### `test_spec_hashes_the_bytes_before_the_newline_before_signature_where_the_oracle_does_not`

**Checks:** For the six other signed files of the cases of the oracle's rule (no empty line, a
line of spaces, CRLF with and without the empty line, an LF file with a CRLF empty line, a line of
255 bytes with its end), the oracle reports `signature_ok` true for its own hash, which `spec`
finds not matching; and for the bytes before the `\n` that precedes `[SIGNATURE]` (the rule of the
specification, which keeps a `\r`) `spec` gives `matches` true and the oracle reports false.

**How:** The test (parametrized, six cases) writes each file twice (the hash of the oracle's bytes, then
the hash of the specification's bytes) and checks `signature_ok` of the oracle and `matches` of
`read_seqfile`. It first checks that the two sets of bytes differ.

**Assumptions:** The specification's bytes are `before[:-1]` in the test, computed without the
package. A hash that does not match is not a rejection.

#### `test_the_signature_of_a_crlf_file_matches_in_the_oracle_and_not_in_spec`

**Checks:** For `valid_crlf.seq` the oracle's `signature_ok` is true and `spec` gives `matches`
false; `spec` reads the file. The bytes that `spec` hashes (`AsWritten.signed_bytes`) end with `\r`,
the `\r` of the empty line.

**How:** The test runs the oracle with `--dump`, reads the file with `read_seqfile` and reads the
signed bytes with `as_written.read_as_written`.

**Assumptions:** None beyond the rule of the specification (spec:223).

#### `test_the_oracle_and_spec_accept_and_reject_the_same_files_but_those_of_the_tables`

**Checks:** For each `.seq` file under `tests/seqfiles/`, `spec` (`read_seqfile`, the default
interpreter) and the oracle accept the file or reject it alike. The exceptions are three tables of
the test:

- `NOT_CHECKED_BY_THE_READER`: a file that `spec` rejects and that the oracle (one of its builds)
  accepts, because the oracle does not check the rule. Each file has the entry of
  `docs/discrepancies.md` that explains it (D1.2, D1.3, D3.1 to D3.9, D3.11, D4.3, D4.4, or the code of the rule in `spec.RULES` where
  the record has no entry). A file that `spec` rejects and that is not in the
  table must be rejected, or crash, in the oracle. `bad_ref_shape.seq`, `bad_shape_empty.seq` and
  `bad_syntax_shape_no_blank_line.seq` are there because the Linux build accepts them (the macOS
  build crashes; `bad_ref_shape.seq` was found by CI on the Linux build), and `undefined/shape_decompress_longer.seq` because the macOS build accepts it.
- `ORACLE_KNOWN_WRONG`: a file that `spec` reads and that the oracle rejects or crashes on, not
  compared. Each has its entry: `bad_shape_rf_time_end.seq` and `valid_rf_time_shapes.seq` (D2.10, D2.11: the
  oracle crashes on the macOS build, the resampling reads past the stored samples),
  `bad_syntax_line_after_comment.seq` and `valid_comment_in_shape.seq` (D2.5: the oracle reads a `#`
  line inside a table or a shape as a row), `oracle/koma_v1.5_unknown_ext.seq` (D2.3),
  `undefined/version_last.seq` (D2.1, undefined behaviour of the reader, section 2.25) and
  `valid_last_section_no_blank.seq` (D2.2).
- A file that `spec` reads and that has an arbitrary gradient (a row of `grad` that a block uses) on
  a gradient raster other than 10 us is not compared, because `decodeBlock` fails on it
  (`ExternalSequence.cpp:2114-2119`); the test records the skipped files with
  `record_property("skipped", ...)` (in the junit XML). Today it skips
  `valid_arbitrary_gradient_5us_raster.seq`.

A file of a version outside 1.4.0 to 1.5.x is not compared: `spec` raises `NotSupported` for it (Q1).
The `cpp-siemens` interpreter gives the oracle's verdict on every fixture, with no exception
(section 3.8). The test skips when `tests/seqfiles/` has no `.seq` file.

**How:** The test calls `read_seqfile` on each file, then runs the oracle (a crash counts as a
rejection), except for a file of `ORACLE_KNOWN_WRONG` and the raster skip. It collects each file where
`spec` accepts and the oracle does not, and each file where `spec` rejects, the oracle accepts and the
file is not in `NOT_CHECKED_BY_THE_READER`. It fails with the list.

**Assumptions:**

- When both readers reject a file, the test does not check that they reject it for the same rule.
- The tables come from a run on the macOS arm64 build, and the comments of the entries that a
  crash depends on the build come from the acceptance matrix (`scripts/discrepancy_matrix.py`, run on 2026-10-13) and from
  earlier runs on the Linux build. The test does not show that the oracle never checks a rule.
- A file of `ORACLE_KNOWN_WRONG` is skipped whatever the verdicts are, also when the oracle changes.
- The raster skip is a rule on the model, never a file name.

#### `test_the_tables_of_differences_name_files_that_spec_rejects_or_reads`

**Checks:** Each file of `NOT_CHECKED_BY_THE_READER` is a file that `spec` rejects, each file of
`ORACLE_KNOWN_WRONG` is a file that `spec` reads, and each entry starts with the ID of an entry
of `docs/discrepancies.md` (`D`, a group number, a dot and a number) or with a code of `spec.RULES`.
So no entry of the tables is out of date.

**How:** The test reads each named file with `read_seqfile` and checks `SeqFileError` or not, and
matches the start of the entry with a regular expression; a code must be a key of `RULES`.

**Assumptions:** It does not read `docs/discrepancies.md`, so it does not show that the entry
exists, or that it explains the file.

### 2.21 The SAFE hardware and filter (`test_safe.py`)

`test_safe.py` tests `safe.py`: `SafeAxis` and `SafeHardware` (immutable, checked when they are
made), `SafeHardware.from_namespace` (the form of pypulseq's `asc_to_hw` and
`safe_example_hw()`), and `_safe_gwf_to_pns_chunk`, the chunked SAFE filter that `pns_levels`
runs. The module is ported from pypulseq's `safe_hw_check` and `_safe_gwf_to_pns_chunk`, which
only the pinned fork has as the tests use them. The tests that compare with them compare with
golden values, the outputs of the fork's functions for the same inputs, in
`tests/golden/safe_fork.npz`: `tests/golden/make_golden.py` wrote them with the fork pinned,
and `tests/golden/README.md` gives the fork commit. The comparisons (`_assert_golden`) require
the dtype and the shape, the integer and bool values exactly, and the float values within
`_GOLDEN_RTOL` of the value or of the largest magnitude of its array: 1e-14 for float64 and two
float32 ulp for float32. (A value that comes out of a cancellation, as a filter state can,
carries the rounding of the large terms of its array.) The port does the
same float operations as the fork, but the golden values come from one platform (macOS), and
numpy and scipy on another (Linux in CI) round some of them differently in the last bit (1 to 2
ulp of a float64, measured on 2026-10-13); a float32 level, the outward cast of a float64 total,
can then move by one float32 ulp.
The numbers of pypulseq's example hardware are those of `synthetic.EXAMPLE_AXES`, and one
test compares them with `safe_example_hw()`. Only that test and the comparison of the levels
(which builds synthetic sequences) need pypulseq; they have the marker `pypulseq`.

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

#### `test_the_example_hardware_of_the_tests_is_pypulseqs_example_hardware`

**Checks:** `synthetic.safe_example_hw()` has the attributes and values of pypulseq's
`safe_example_hw()` (the name, `checksum`, `dependency` and the nine fields of each axis), and
`pns_hardware.EXAMPLE_HARDWARE` equals `SafeHardware.from_namespace` of pypulseq's.

**How:** Marker `pypulseq`, and `pytest.importorskip` of pypulseq's module; the test compares
the `vars` of the namespaces and their axes with `==`.

**Assumptions:** None.

#### `test_the_chunk_function_equals_the_forks_for_every_chunk_and_state`

**Checks:** The rows and the state of each chunk equal those of `_safe_gwf_to_pns_chunk` of the
pinned fork (the golden values, within `_GOLDEN_RTOL`), for the example hardware and for hardware with other
numbers in every field (the filters differ, the `a` sum is 1), at the rasters 10 µs and 2.5 µs.

**How:** Parametrized over the hardware and the raster. A random walk of 2000 samples
(`chunk_waveform`) goes through chunks of 1, 1, 698, 1 and 1299 samples (`CHUNKS`); the
function gets the state that it returned. The rows, `g_last` and `zi` of each chunk are compared
with the keys `chunk/<hardware>/<raster>/<i>/...` of the golden file.

**Assumptions:** The random walk is a waveform, not a gradient of a real sequence. The golden
values are those of the fork commit of `tests/golden/README.md`; a change of the inputs needs
`make_golden.py` to run again with the fork. A difference below the tolerance (a change of the
order of the float operations of the port) is not found.

#### `test_the_hardware_check_accepts_and_refuses_what_the_forks_safe_hw_check_does`

**Checks:** `SafeHardware.from_namespace` accepts a namespace if and only if the fork's
`safe_hw_check` does (the golden values): an `a` sum 0.0009 from 1 on `x` and `y` (valid), and
0.0011 from 1 on `x` and `z`, a sum of 5.6, no `x`, no `y.stim_thresh` and no `z.g_scale` (not
valid).

**How:** Parametrized over the eight namespaces of `HW_CHECK_CASES`. The golden value of a case
is whether `safe_hw_check` returned (a refusal was a `ValueError`, or an `AttributeError` for a
namespace with no `x`); a refusal of `from_namespace` is a `ValueError`.

**Assumptions:** `safe_hw_check` does not check that a field is finite, a number or above 0.
`from_namespace` does, and the test does not compare that.

#### `test_pns_levels_equals_the_levels_with_the_forks_chunk_function`

**Checks:** `_compute_levels` with the package's chunk function gives the same fields of
`PnsLevels` as with the pinned fork's `_safe_gwf_to_pns_chunk` in its place (the golden
values): the level, the summary and the intervals above each threshold.

**How:** Marker `pypulseq` (the sequences are built with it). Parametrized over the four
sequences of `test_summary_is_the_safe_model_of_the_oracle_samples` and over the default bin and bins of one
sample. `_CHUNK_SAMPLES` is 1000, so the state passes from chunk to chunk; two thresholds make
intervals (the test checks that some interval exists and that the peak is above 0).
`levels_arrays` gives the fields as arrays (`num_samples`, `bin_samples`, the two levels, the
peak, its time, the axis peaks, `on_raster`, and the rows `start_s, end_s, peak_hz_per_t,
peak_time_s, num_samples` of the intervals of each threshold); each must have the dtype, shape
and values of its golden array (`_assert_golden`), and the set of names must be that of the
golden file.

**Assumptions:** The sequences are the synthetic sequences, with the example hardware, as
pypulseq builds them in the dev environment (the fork). The fields that the chunk function does
not change (`reason`, `hardware`, `hw`, `dt_s`) are not compared.

#### `test_safe_and_asc_import_neither_pypulseq_nor_matplotlib`

**Checks:** A new interpreter that imports `pulseq_analysis.analyses.safe` and
`pulseq_analysis.analyses.asc` has no module of `pypulseq` or `matplotlib` in `sys.modules`.

**How:** A subprocess runs the import and the check.

**Assumptions:** `pulseq_analysis.analyses.pns_levels` is not tested: it imports the snapshot,
which imports pypulseq, and `import pypulseq` imports matplotlib and
`pypulseq.utils.safe_pns_prediction` (checked on 2026-10-08).

#### `test_no_module_imports_pypulseq`

**Checks:** No module of `src/pulseq_analysis` or its subpackages has an `import` of pypulseq.

**How:** The test parses each file with `ast` and collects the modules that have an `import` or an
`import from` of a name that starts with `pypulseq`, in any scope. The set must be empty.

**Assumptions:** A name that is imported with `importlib` is not found. `read_pypulseq` calls the
`write` method of the sequence that the caller gives, so the package needs no import.

### 2.22 The decoded events (`test_decoding.py`)

`test_decoding.py` tests `events.decode_rf`, `events.decode_gradients` and `events.decode_adc` (the decoder
of the `spec` interpreter), `RfEvent.signal`, `model.rf_time_step`, and `synth.decode` for `spec`. It
reads the fixtures of `tests/seqfiles` with `seqfile.read_seqfile` and a 1.5.1 file that a test writes to a
temporary folder: an RF event with an irregular time shape (points), an RF event with a regular time shape
(cells), an ADC phase shape, and an RF event and a trapezoid that no block uses. The RF time shapes of
`valid_rf_time_shapes.seq` (RF 2 to 5) are the main fixture. The expected values are written in the test
from the text of the files. Each docstring names the source of the rule: the specification (`spec:N`, its
line N), the slide set of its section 2.6 (`slide N`; normative for timing) or the entry of
`docs/discrepancies.md`. The tests need no pypulseq.

#### `test_trapezoid_has_the_values_of_the_file`

**Checks:** The trapezoid of the 1.5.1 fixture decodes to a `Trapezoid` with the amplitude, the rise,
flat and fall times and the delay of the file in s. Its `shape_dur` is the sum of the three times,
and its `first` and `last` are 0.0.

**How:** The test decodes the gradients of `valid_1_5_1.seq` and compares gradient 1 with a
`Trapezoid` made from the numbers of the text, and its properties with the sum and with 0.0.

**Assumptions:** The model has converted the µs of the file to s (`test_seqfile.py` checks it).

#### `test_arbitrary_gradient_on_the_default_raster`

**Checks:** An arbitrary gradient with time ID 0 has `waveform` equal to the amplitude times the
samples, a sample at the centre of each gradient raster cell (`tt = (i + 0.5) dt`), `shape_dur = n
dt`, and the `first`, `last` and delay of the file.

**How:** The test decodes gradient 3 of `valid_1_5_1.seq` (10 samples, raster 10 µs) and compares
it, field by field and exactly, with an `ArbitraryGradient` whose arrays it computes from the
numbers of the text.

**Assumptions:** The expected arrays are computed with the same floating-point operations as the
code, so the comparison is exact.

#### `test_arbitrary_gradient_oversampled`

**Checks:** An arbitrary gradient with time ID -1 has samples half a gradient raster apart, the
first at half a raster (`tt = (i + 1) / 2 dt`), and `shape_dur = (n + 1) / 2 dt`.

**How:** The test decodes gradient 6 of `valid_1_5_1.seq` (5 samples) and compares it exactly with
an `ArbitraryGradient` made from the numbers of the text.

**Assumptions:** As in `test_arbitrary_gradient_on_the_default_raster`.

#### `test_arbitrary_gradient_with_a_time_shape`

**Checks:** An arbitrary gradient with a time shape has `tt` equal to the time shape times the
gradient raster, and `shape_dur` equal to the last time.

**How:** The test decodes gradient 5 of `valid_1_5_1.seq` (time shape 0, 1, 3, 6, 10) and compares
it exactly with an `ArbitraryGradient` made from the numbers of the text.

**Assumptions:** As in `test_arbitrary_gradient_on_the_default_raster`.

#### `test_arbitrary_gradient_with_a_time_shape_in_a_1_4_file`

**Checks:** In a 1.4 file, an arbitrary gradient with a time shape decodes with the same time rule,
and its `first` and `last` are those of the model: the amplitude times the first and the last
sample.

**How:** The test decodes gradient 2 of `valid_1_4_1.seq` and compares it exactly with an
`ArbitraryGradient` made from the numbers of the text.

**Assumptions:** The model's `first` and `last` of a 1.4 file are correct (`test_seqfile.py` checks
them).

#### `test_gradients_and_trapezoids_are_in_one_mapping_by_id`

**Checks:** `decode_gradients` gives the arbitrary gradients and the trapezoids in one read-only
mapping, keyed by the file ID of each event, with the right type for each.

**How:** The test decodes `valid_1_5_1.seq`. It checks that the result is a `MappingProxyType`,
that its keys are the IDs 1 to 6, that 1 is a `Trapezoid` and the others are `ArbitraryGradient`
objects, and that each event's `id` is its key.

**Assumptions:** None.

#### `test_rf_event_without_a_time_shape`

**Checks:** An RF event without a time shape has `magnitude` in Hz (the amplitude times the magnitude
shape), `phase` in rad, a sample at the centre of each RF raster cell (spec:290), `dwell` equal to the RF
raster, `shape_dur = n` RF raster times, and the center, delay, offsets and use of the 1.5 file.

**How:** The test decodes the RF event of `valid_1_5_1.seq` (100 samples of a compressed shape) and
compares it exactly with an `RfEvent` made from the numbers of the text.

**Assumptions:** The phase shape of this fixture is all zeros. The factor 2π is checked by
`test_rf_event_with_an_irregular_time_shape_is_points`.

#### `test_rf_event_of_a_1_4_file_has_no_center`

**Checks:** The RF event of a 1.4 file has `center` `None`, `use` `"u"`, ppm offsets of 0.0, `dwell` equal to
the RF raster, and the default time rule.

**How:** The test decodes the RF event of `valid_1_4_0.seq` and checks these fields, `t` and `shape_dur`.

**Assumptions:** None.

#### `test_rf_event_with_a_regular_time_shape`

**Checks:** An RF event whose time shape is regular (here `5 10 10 2`: the times 5, 15, 25, 35, 45, a step
of 10 and a first time of half a step) is cells: `dwell` is the step times the RF raster, `t` is at the
centre of each cell, and `shape_dur` is the number of samples times `dwell` (slide 9, D2.10, D2.12). The samples
are kept as stored.

**How:** In the written file, RF 2 has this time shape, stored compressed in 4 values for 5 samples. The
test compares the decoded event exactly with an `RfEvent` with a dwell of 10 µs, made from the numbers of
the text.

**Assumptions:** As in `test_rf_event_with_an_irregular_time_shape_is_points`.

#### `test_rf_event_with_a_time_shape_in_a_1_4_file`

**Checks:** The RF event with a time shape of a 1.4 file is read by the same rule: the block pulse of the file
(the magnitude 1, 1 at the times 0, 100) is two points at 0 and 100 µs, with `dwell` `None`, and has no
center (slides 4 and 9, D2.11).

**How:** The test decodes `oracle/koma_v1.4_rf-time-shaped.seq`: amplitude 2500 Hz. It checks the 2
magnitudes of 2500 Hz, the 2 phases of 0, `dwell` `None`, `t` at 0 and 100 µs and `shape_dur` of 100 µs (to a
relative 1e-12), and that `center` is `None`.

**Assumptions:** None.

#### `test_adc_events_with_and_without_a_phase_shape`

**Checks:** An ADC event has the values of its row in s, Hz and rad. Its `phase_modulation` is the
decompressed phase shape as the file stores it, in rad, with no factor (D2.15), or `None` when
`phase_shape_id` is 0. The result is a read-only mapping.

**How:** The test decodes the ADC events of the file of `test_rf_event_with_an_irregular_time_shape_is_points`.
It compares ADC 1 (phase shape 0, 0.5, 1, 1.5) exactly with an `AdcEvent` made from the numbers of the text,
and checks that ADC 2 has `phase_modulation` `None`.

**Assumptions:** None.

#### `test_each_row_is_decoded_whether_a_block_uses_it_or_not`

**Checks:** Each decode function gives every row of its table, in table order, including an event
that no block uses.

**How:** The file of `test_rf_event_with_a_time_shape` has RF 3 and trapezoid 7, which no block
uses. The test checks the keys of the three mappings and the values of RF 3 and trapezoid 7.

**Assumptions:** None.

#### `test_a_shape_that_several_events_use_is_decompressed_once`

**Checks:** In one call of `decode_rf`, a shape that several events use is decompressed once, and the time
shape of a regular pulse is decompressed too (to find its step).

**How:** The test wraps `model.Shape.samples` to count its calls, and decodes the RF events of the written
file. The events use the shapes 1, 2 (twice), 3, 6, 7 and 8, and the time shape 4. The test checks 7 calls.

**Assumptions:** `events` decompresses a shape only through `Shape.samples`.

#### `test_events_are_read_only_equal_by_value_and_pickle`

**Checks:** Each decoded event equals the same event of another call, survives `pickle`, cannot be
changed, and has read-only arrays that cannot be made writable.

**How:** For each decode function on the file of `test_rf_event_with_a_time_shape`, the test
compares each event with the same event of a second call and with a pickled copy. For each array
field it checks that `writeable` is false and that setting it raises `ValueError`, and that setting
a field raises `AttributeError`.

**Assumptions:** None.

#### `test_every_file_that_loads_decodes`

**Checks:** Every valid fixture and every oracle file that the `spec` interpreter accepts decodes: each
mapping has the IDs of its table; the scalar fields equal the model's columns; the arrays of an RF event
have one value for each sample of its magnitude shape, and the arrays of a gradient one for each sample of
its shape; an RF event is points exactly when its time shape is not regular (`dwell` `None`, `shape_dur`
equal to the last time), and else cells (`dwell` is the step times the RF raster, `shape_dur = n dwell`, the
last time is before `shape_dur`); the signal of an RF event at its times `t` is `magnitude * exp(1j *
phase)`; the last sample time of a gradient is not after `shape_dur`; RF `center` is `None` exactly for a 1.4
file; `phase_modulation` is `None` exactly when `phase_shape_id` is 0, and else has one value for each ADC
sample (D2.15); an RF or gradient event ends (delay plus `shape_dur`) within 1 ps of the end of each block that
plays it, or before.

**How:** For each file (parametrized), the test reads the file, skips a file that the `spec` interpreter
rejects (with the rules in the reason), decodes the three tables, and checks each statement row by row and
block by block. It uses `model.rf_time_step` to know whether an RF time shape is regular.

**Assumptions:** The check of the ends is a consistency check with the rule `block.event-too-long` of the
reader, not a check against an independent reader. The MATLAB and C++ oracle tests compare the values.
The signal at the times `t` is compared to a relative 1e-12 with an absolute tolerance of 1e-9 Hz.

#### `test_oversampled_gradients_of_a_spiral_keep_all_samples`

**Checks:** The arbitrary gradients with time ID -1 of a file keep all their samples: an odd number of
samples, `tt = (i + 1) / 2 dt` (half a raster apart, from the centre of the first cell to the centre of
the last), and `shape_dur = (n + 1) / 2 dt` (spec:420, slides 4 and 8).

**How:** The test decodes `oracle/koma_v1.5_spiral.seq`, takes the gradients whose `time_id` is -1 (IDs 4
and 5, checked), and for each checks that the number of samples is odd, that `tt` equals
`np.arange(1, n + 1) / 2 * dt` exactly, and the `shape_dur`.

**Assumptions:** The gradient IDs 4 and 5 are those of the file. The expected values are computed with the
same floating-point operations as the code.

#### `test_the_dwell_of_an_rf_event_without_a_time_shape_is_the_rf_raster`

**Checks:** The `dwell` of an RF event without a time shape is the RF raster of the file (spec:290), and an
RF time shape is in RF rasters (spec:349): with the RF raster 2 µs, the cells of a regular time shape of
step 10 are 20 µs, and the points of an irregular time shape are at the shape times times 2 µs.

**How:** The test writes the 1.5.1 file of the other tests with `RadiofrequencyRasterTime` 2e-06 and
decodes it. RF 3 (no time shape, 4 samples) has `dwell` 2 µs, `t` at the centres of 4 cells of 2 µs and
`shape_dur` 8 µs. RF 2 (time shape `5 10 10 2`) has `dwell` 20 µs. RF 1 (time shape 0.5, 1, 2, 4) has `dwell`
`None`, `t` at 1, 2, 4 and 8 µs and `shape_dur` 8 µs. The values are compared to a relative 1e-12.

**Assumptions:** The file is also valid with the RF raster of 2 µs (the test reads it with `spec`).

#### `test_rf_event_with_an_irregular_time_shape_is_points`

**Checks:** An RF event whose time shape is not regular (unequal steps) is points: `t` is the time shape
times the RF raster, `dwell` is `None`, and `shape_dur` is the last time (slides 4 and 9, D2.11, D2.12). No sample is
dropped or repeated. The magnitude is the amplitude times the magnitude shape (Hz), and the phase is 2π
times the phase shape (rad). The center, delay, ppm offsets, frequency and phase offsets and use are those
of the file.

**How:** In the written file, RF 1 has the time shape 0.5, 1, 2, 4, stored uncompressed. The test compares
the decoded event exactly with an `RfEvent` made from the numbers of the text.

**Assumptions:** The expected arrays are computed with the same floating-point operations as the code.

#### `test_rf_event_with_a_regular_time_shape_of_step_2_is_cells_of_two_rasters`

**Checks:** The time shape `1 2 2 47` (50 samples, the times 1, 3, ..., 99) is cells of 2 µs: `dwell` 2 µs, `t`
at the centres of the cells, and `shape_dur` 100 µs, not 99 µs (slide 9, D2.10, D2.12).

**How:** The test decodes RF 2 of `valid_rf_time_shapes.seq` and compares `dwell`, `t` and `shape_dur` to a
relative 1e-12, and checks that the 50 magnitudes are 1000 Hz.

**Assumptions:** None.

#### `test_rf_event_with_the_time_shape_of_a_short_pulse_is_cells_of_one_raster`

**Checks:** The uncompressed time shape 0.5, 1.5, 2.5 (3 samples) is cells of 1 µs: `dwell` 1 µs, `t` at 0.5,
1.5 and 2.5 µs, and `shape_dur` 3 µs (slide 9, D2.10, D2.12).

**How:** The test decodes RF 3 of `valid_rf_time_shapes.seq` and compares `dwell`, `t` and `shape_dur` to a
relative 1e-12, and checks the magnitudes 1000, 500 and 250 Hz.

**Assumptions:** None.

#### `test_rf_event_of_a_block_pulse_is_two_points`

**Checks:** The time shape 0, 100 with the magnitude 1, 1 is two points, at 0 and 100 µs, with `dwell`
`None` and `shape_dur` 100 µs (slides 4 and 9, D2.11, D2.12).

**How:** The test decodes RF 4 of `valid_rf_time_shapes.seq` and checks `dwell`, `t` and `shape_dur` (to a
relative 1e-12) and the two magnitudes of 1000 Hz.

**Assumptions:** None.

#### `test_rf_event_with_vertices_is_points`

**Checks:** The time shape 1, 2, 4, 7, 10 (5 samples) is 5 points at 1, 2, 4, 7 and 10 µs, with `dwell`
`None`, `shape_dur` 10 µs, the magnitudes 200, 600, 1000, 600 and 200 Hz, and the phases 2π times 0, 0.25,
0.5, 0.25 and 0 (slides 4 and 9, D2.11, D2.12).

**How:** The test decodes RF 5 of `valid_rf_time_shapes.seq` and compares the fields to a relative 1e-12.

**Assumptions:** None.

#### `test_the_signal_of_cells_holds_each_sample_over_its_cell_and_is_0_outside`

**Checks:** `RfEvent.signal` of a pulse of cells holds each sample from `i dwell` to `(i + 1) dwell`, and is
0 before the start and from `shape_dur` on (slide 9, D2.10 to D2.12).

**How:** The test calls `signal` of RF 3 of `valid_rf_time_shapes.seq` (cells of 1 µs: 1000, 500, 250 Hz) at
-0.5, 0, 0.5, 1, 1.5, 2, 2.5, 3 and 3.5 µs and compares with 0, 1000, 1000, 500, 500, 250, 250, 0, 0. It calls
`signal` of RF 2 (cells of 2 µs, 1000 Hz) at -1, 0, 1, 99 and 101 µs and compares with 0, 1000, 1000, 1000, 0.

**Assumptions:** The times that are not on a cell edge are half a dwell from one. At the edges 0, 1 µs, 2 µs and
3 µs, `time / dwell` is within 1e-6 of a whole number in float64 (on this platform it is exactly one), so these
times are in the cell after the edge.

#### `test_the_signal_of_cells_is_the_complex_sample`

**Checks:** A cell holds the complex sample `magnitude * exp(1j * phase)`, the phase included.

**How:** In the written file, RF 2 has cells of 10 µs, and its sample 1 has the magnitude 200 Hz and the
phase 2π 0.1. The test calls `signal` at 12 µs and 19 µs and compares both values with
`200 * exp(1j * 2 * pi * 0.1)` to a relative 1e-12.

**Assumptions:** None.

#### `test_the_signal_of_cells_puts_each_cell_boundary_in_the_cell_after_it`

**Checks:** `RfEvent.signal` of a pulse of cells puts each cell boundary `k dwell` in the cell `k`, the cell
after it, although `k dwell / dwell` is a rounding error under `k` for some `k`; a time 2e-6 dwells below a
boundary stays in the cell before it.

**How:** The test builds an `RfEvent` of 5000 cells of 1 µs whose samples are 1 to 5000 Hz, so each cell has
its own value. It calls `signal` at `(k - 2e-6) dwell` for `k` from 1 to 5000 and compares with the sample
`k - 1`. It calls `signal` at the boundaries `k dwell` for `k` from 0 to 5000, computed as `decode_rf` computes
`shape_dur = n dwell`, and compares with the sample `k`, and 0 at the end `5000 dwell`. With
`floor(time / dwell)`, 89 of these boundaries give the cell before.

**Assumptions:** A boundary is the float64 product `k dwell`; a time computed in another way (for example
`delay + k dwell`, less `delay`) can round to another side. The test covers one dwell, 1 µs, and a time below a
boundary only at 2e-6 dwells.

#### `test_the_signal_of_points_is_the_straight_line_of_the_complex_signal`

**Checks:** Between two points, `RfEvent.signal` is the straight line of the complex signal: the linear
interpolation of the real and imaginary parts (D2.11), not the interpolation of the magnitude and the phase.

**How:** The test calls `signal` of RF 5 of `valid_rf_time_shapes.seq` at 1, 2, 3, 4, 5.5 and 7 µs. The points
at 2 µs (0.6 at the phase 0.25 turn: 600j Hz) and 4 µs (1 at 0.5 turn: -1000 Hz) give, at 3 µs, their average,
-500 + 300j Hz. The test compares the six values with the expected complex numbers (the points, and the
averages of the two neighbours at 3 µs and 5.5 µs), and checks that the magnitude at 3 µs is hypot(500, 300),
about 583 Hz, and not 800 Hz, the average of the magnitudes.

**Assumptions:** The times 3 µs and 5.5 µs are the midpoints of their segments to within a rounding error;
the comparison has an absolute tolerance of 1e-9 Hz.

#### `test_the_signal_of_points_is_0_before_the_first_point_and_after_the_last`

**Checks:** The signal of a pulse of points is 0 before its first point and after its last point, and the
block pulse (two points) is constant between its two points (slides 4 and 9).

**How:** The test calls `signal` of RF 5 of `valid_rf_time_shapes.seq` at -1, 0, 0.5, 1, 10.5 and 11 µs and
compares with 0, 0, 0, 200, 0, 0. It calls `signal` of RF 4 (the block pulse, 1000 Hz) at -1, 0, 50 and 100.5 µs
and compares with 0, 1000, 1000, 0.

**Assumptions:** The test does not call `signal` at the last point (`shape_dur`): its value there is not
tested (`signal` gives the last sample at the last point, and the docstring says 0 from `shape_dur` on).

#### `test_rf_time_step_of_a_time_shape`

**Checks:** `model.rf_time_step` gives the step, in RF raster times, of a regular time shape (2 or more
samples, equal steps, a first time of half a step; or one sample `t0` above 0, a step of `2 t0`), and `None`
for any other shape (slide 9, D2.10, D2.11, D3.9).

**How:** For thirteen shapes (parametrized), the test makes a `model.Shape` from the stored values, decompresses
it, and compares the result: `0.5 1 1 97` (100 samples) gives 1; `1 2 2 47` (50 samples) gives 2; the
uncompressed 0.5, 1.5, 2.5 gives 1; and `None` for `1 1 3` (the times 1 to 5: the first time is a whole step),
the block pulse 0, 100, the vertices 1, 2, 4, 7, 10, the unequal steps 0.5, 1, 2, 4, decreasing
times 2.5, 1.5, 0.5, the times 0.5, 0.5 (a step of 0), and one sample at 0 or at -1; one sample 0.5 gives 1,
and one sample 5 gives 10. A step is compared to a relative 1e-12.

**Assumptions:** The decompression of the shapes (`Shape.samples`) is right.

#### `test_rf_time_step_has_the_tolerance_of_the_model`

**Checks:** The steps must be equal, and the first time must be half a step, to within
`model.TIME_TOLERANCE` RF raster times.

**How:** For four cases (parametrized), the times 0.5, 1.5, 2.5, 3.5, 4.5 are made late by a multiple of the
tolerance: one time late by 0.4 tolerances gives the step 1 (to the tolerance); one time late by 3 tolerances,
and all the times late by 3 tolerances (the first time is then not half a step), give `None`; all the times
late by 0.4 tolerances give the step 1.

**Assumptions:** The test uses `model.TIME_TOLERANCE` itself, not its value.

#### `test_adc_phase_modulation_has_one_value_for_each_sample`

**Checks:** The phase modulation of an ADC event has one value for each ADC sample (D2.15).

**How:** The test decodes ADC 2 of `valid_1_5_1.seq` (phase shape 8, 8 samples, all 0) and checks that
`num_samples` is 8 and that `phase_modulation` equals 8 zeros.

**Assumptions:** The values of the shape are 0, so this test checks the length; the unit is checked by
`test_adc_events_with_and_without_a_phase_shape`.

#### `test_synth_decode_gives_the_events_of_spec`

**Checks:** `synth.decode` of the model of `spec` is a `SpecDecoding` whose interpreter is `Spec()` and whose
`rf`, `gradients` and `adc` equal the results of `decode_rf`, `decode_gradients` and `decode_adc`.

**How:** The test reads `valid_1_5_1.seq` and compares the four fields.

**Assumptions:** The decoding of a plugin interpreter is tested with the plugin (`cpp-siemens`: `test_interpreter.py`,
section 3.8; a fake plugin: `test_interpreters.py`, section 2.27).

#### `test_spec_gradients_at_are_the_lines_between_the_points_of_each_event`

**Checks:** `SpecDecoding.gradients_at` gives the gradients (Hz/m) at block-relative times in µs, an
array (n, 3): on block 2 of `valid_1_4_1.seq` (a trapezoid on gx of 1e6 Hz/m, delay 100 µs, rise
100 µs, flat 200 µs, fall 100 µs, block 500 µs), 0 at -1 and 50 µs, 0.5e6 at 150 µs, 1e6 at 250 µs,
0.5e6 at 450 µs, 0 at 500 and 501 µs, and 0 on gy and gz. `block_count` is 4. Empty arguments give
an array (0, 3); arguments of different lengths and a NaN time raise `ValueError`; a block index of
-1 or 4 raises `IndexError`, as for the decoding of a plugin.

**How:** The test reads the file with `spec` and calls `gradients_at`.

**Assumptions:** The arbitrary gradients and extended trapezoids are compared with `cpp-siemens` by
`test_spec_rotates_the_gradients_as_cpp_siemens_with_rotation_apply` (`test_interpreter.py`) and with
MATLAB by `test_the_rotated_gradients_of_spec_are_those_of_matlab_pulseq`.

#### `test_rotate_is_the_active_rotation_of_a_unit_quaternion`

**Checks:** `decoding.rotate(q, v)` is the active rotation `R(q) v`, q0 the scalar part: a quarter turn
about z takes x to y, about x takes y to z, about y takes z to x, and the identity keeps a vector (to
1e-15); for 20 random unit quaternions and vectors it equals `q v q*` with the Hamilton product, to
1e-12.

**How:** The test computes `q v q*` with its own Hamilton product (seed 0).

**Assumptions:** None.

#### `test_spec_rotates_the_gradients_of_each_block_that_has_a_rotation`

**Checks:** From 1.5.1, `spec` rotates each block's gradients by its normalized quaternion (D2.18, P20
rule 2): in `koma_v1.5_rotation_radial_tiny.seq`, `rotations()` gives blocks 0 to 4 with quaternions
of norm 1 (to 1e-15); the logical gradients (`rotated=False`) are on x only; the rotated ones
(`rotated` None, the same as True) are those turned by 0, 45, 90, 45 and 0 degrees about z (to 1e-3
Hz/m). `rotation_record` is `RotationRecord("apply", 5, 3, 5)`, with no warning and the text
"rotation: apply, 5 block(s) rotated"; the decoding emits no `ScannerSettingWarning`.
`valid_1_5_1_rotation_not_played.seq` and `valid_1_4_1.seq` have the record
`RotationRecord("apply", 0, 0, 0)`.

**How:** The test samples 4 times in each of the 5 blocks, with `recwarn`.

**Assumptions:** The angles are those of the file's quaternions, as in
`test_rotation_apply_rotates_the_gradients_of_each_block_that_has_a_rotation`.

#### `test_a_file_older_than_1_5_1_with_rotations_is_not_rotated`

**Checks:** Before 1.5.1, ROTATIONS is an unknown extension for `spec` (P20 rule 2, D4.6): its
`records` have the record ("extension", "ROTATIONS", "version"), `rotations()` is empty (shape (0,)
and (0, 4)), `rotation_record` is `RotationRecord("apply", 0, 0, 0)`, and the gradients of a block
whose extension list has a ROTATIONS object are not 0 and equal the logical ones (`rotated=False`).

**How:** The test reads `valid_1_5_0_extensions_of_1_5_1.seq` (block 5 plays gx, its list has
ROTATIONS) and a copy of `valid_1_4_1.seq` in `tmp_path` with a ROTATIONS object (45 degrees about z)
in the list of block 2, which plays a trapezoid on gx; it samples 10 times inside the block.

**Assumptions:** None.

### 2.23 The decoding against the C++ oracle (`test_cpp_oracle_decode.py`)

`test_cpp_oracle_decode.py` compares the model of `read_seqfile` (the `spec` interpreter), the events of
`pulseq_analysis.synth.events` and the gradient waveform of `GradientSampler` with the reader
`ExternalSequence` of the scanner, through the modes `--dump` and `--sample` of `pulseq-cpp-oracle`
(`tests/oracles/cpp.py`; `tests/cpp_oracle/README.md` has the fields and their units). It compares
each `.seq` file under `tests/seqfiles/` that both `spec` and the oracle accept (34 files today),
except the files of `ORACLE_KNOWN_WRONG` (section 2.20), the files that the two read as different
sequences (`READ_DIFFERENTLY`: none today, `spec` rejects a section that appears twice, D3.3), and a file with an arbitrary gradient on a gradient
raster other than 10 us (`decodeBlock` fails on it). The module skips when the binary is not on the
PATH. A difference is not skipped: the test fails with the file, the block, the field, both values and,
for a field that the reader computes, the reader's rule and its line in `ExternalSequence.cpp`.

Where `spec` differs from the reader by design, the test compares the field after the change that the
design makes, or does not compare it, and records the difference with `record_property("by_design",
...)` (in the junit XML), with the entry of `docs/discrepancies.md` and the files. The differences
found today:

- RF pulse of points, an RF time shape that is not regular (D2.11): the duration, the dwell and the
  samples are not compared. 8 files (`bad_shape_rf_time_grid.seq` and the files of the
  `oracle/` folder with a block pulse or a time shape other than the half step).
- RF magnitude below 0 (D2.8, `bad_shape_rf_magnitude_negative.seq`) and RF phase outside
  [0, 2 pi - 1e-4] (D2.9, `bad_shape_rf_phase_range.seq`): `spec` plays them as written, the reader
  clamps. Only an event whose magnitude shape has a sample below 0, or whose phase is outside that
  range, differs by design; the values of other events are compared as they are, and the clamped
  values of those two kinds of event agree.
- The samples of an oversampled gradient (D6.1; 19 files, among them `oracle/koma_v1.5_spiral.seq` and
  `valid_1_5_1.seq`): `spec` keeps all of them, the reader the even ones; the even ones agree.
- ROTATIONS and RF_SHIMS in a file of version 1.5.0 (D4.6, `valid_1_5_0_extensions_of_1_5_1.seq`): `spec`
  skips them, the reader reads them.
- A soft delay offset with a fraction (D2.16, `valid_soft_delay_fraction.seq`): the reader misreads the row.
- The signature of a file with CRLF line ends (`valid_crlf.seq`, spec:223): see the test of the signature.

#### `test_the_decoded_events_equal_the_dump_of_the_cpp_reader`

**Checks:** For each compared file and each block in play order, the reader's dump and the package
agree on the block duration in block rasters; which events the block has; every field of the RF
event, including its samples, dwell and `shape_dur`, when the pulse is cells (no time shape, or a
regular time shape whose first time is half a step); the other fields of an RF event of points; every field of
each gradient (trapezoid, arbitrary, or with a time shape), `first` and `last` of an arbitrary
gradient included; every field of the ADC event; and the trigger, soft delay, labels, rotation and RF
shim of the block. The differences by design (the intro) are not failures.

**How:**

- The test converts the units of the package to those of the dump (µs, ns, Hz, rad). It compares
  integer fields, IDs and text exactly, and float values to 1e-6 times the largest magnitude of the
  event, because the reader holds `float`.
- RF: the magnitude is compared as the dump's fraction times the amplitude, and the phase as the dump
  holds it, directly with the package's values. Only an event whose magnitude shape has a sample below 0
  (D2.8) or whose phase is outside [0, 2 pi - 1e-4] (D2.9) differs by design (the reader clamps in
  `checkRF`): a difference of that field is recorded as D2.8 or D2.9, and the package's clamped values (the
  magnitude below 0 set to 0, the phase clipped to [0, 2 pi - 1e-4]) are compared with the dump too. For a
  pulse of points, the duration, dwell, magnitude and phase are compared the same way, and a difference
  is recorded as D2.11. The package's dwell is `RfEvent.dwell`.
- Gradients: the samples of an arbitrary gradient are compared as fraction times amplitude, after
  `checkGradient`. For an oversampled gradient, the package's samples at the even indices (the
  centres of the raster cells) are compared, and the comparison of all of them is recorded as D6.1.
  For a gradient with a time shape, the package's times in µs must equal the times that the reader
  rounds to µs, and the waveform the samples.
- Extensions: the test walks the extension list of each block in the model, without the extensions that
  `spec` skipped (`skipped_extensions`), and keeps the object that the reader keeps (a trigger of type 0,
  a soft delay with a negative number and an RF shim with no channel count as none; otherwise the
  first one). It cuts the hint to 31 characters, normalizes the rotation, and keeps only the labels
  that the reader knows (a flag as 0 or 1). An object that the reader has and the model has not,
  for an extension that `spec` skipped, is recorded as D4.6. A soft delay offset with a fraction is
  recorded as D2.16.
- It records the skipped files with `record_property("skipped", ...)` and the differences by design with
  `record_property("by_design", ...)`.

**Assumptions:**

- A file that the oracle does not accept is left out here; the accept/reject test of 2.20 reports it.
- The ADC phase-modulation samples are not in the dump, so they are not compared; the phase shape ID is.
  So the unit of the shape (rad, D2.15) is not tested here.
- The dump has `first` and `last` for an arbitrary gradient only, not for a gradient with a time shape,
  so those of a 1.4 gradient with a time shape (D4.5) are not compared. `spec` rejects a 1.4 arbitrary
  gradient of time ID 0 (D4.4).
- The list of labels that the reader knows is a copy of `decodeLabel`.
- A difference by design is hidden for the whole field of an event that the rule names (the points of
  an RF pulse, say), so another difference in that field is not found.
- The planned skip of `first` and `last` of a 1.4 gradient is gone with the rule that made it needed.

#### `test_signature_matches_equals_the_signature_check_of_the_cpp_reader`

**Checks:** For each compared file with a signature of type md5 (in any case), `signature.matches` of
the model equals `signature_ok` of the reader, except `valid_crlf.seq` (`SIGNATURE_BY_DESIGN`, spec:223), where
`spec` gives false and the reader true (the file is signed by the reader's rule, whose empty line before
`[SIGNATURE]` ends with `\r\n`, and `spec` hashes the bytes before the `\n` of the specification).

**How:** The test compares the two values for each such file, and for the file of the table checks the two
values that spec:223 states. It fails with the files where they differ and the reader's rule for the hash. It
also checks that the file of the table is among the compared files.

**Assumptions:** A file without a signature, or with another type, is not compared. The test does not
compute a hash itself (the test of 2.20 does).

#### `test_the_gradient_waveform_equals_gradients_at_of_the_cpp_reader`

**Checks:** Inside each block, `GradientSampler` (made with `_from_parts` from the model's index and
gradient events) and `SeqBlock::gradientsAt` of the reader give the same value on each axis, at the
centre of each gradient raster cell from the start of the block's first gradient event to the end of
its last one, and at the start and the end of each gradient event when they are strictly inside the
block.

**How:** For each block with a gradient event, the test computes the times in µs from the block
start, gets the reader's values with one `--sample` call for each file and the package's values at
the block start plus the time, and compares each value to 1e-6 times the largest magnitude of the
block's event on that axis. When the block has no event on that axis, the scale is the largest magnitude
of the axis in the file: the sampler joins the events of neighbouring blocks with a ramp (D2.14), so
the block can hold the start of a ramp, at a value that is rounding noise against the amplitudes
(`bad_blocks_order.seq`: 2e-8 Hz/m against 5e5 Hz/m at 495 us of a block). It records the number of
times sampled in each file with `record_property("sampled", ...)`.

**Assumptions:**

- Planned skip: a time at a block boundary, because `gradientsAt` works inside one block.
- The test does not sample the cells of a block before its first gradient event or after its last
  one, where the reader gives 0 (the corpus has about 10 M cells in all, far over the time budget).
  So the package's value outside the events of a block is not tested here.
- The times are the cell centres and the event ends, where the lines between all the samples of an
  oversampled gradient (`spec`) and those between its even samples (the reader) agree: the test does not
  show the difference of D6.1 between the centres.
- The package's step rule at an event start or end inside a block is not exercised: the parser rules
  `gradient.nonzero-start-delay` and `gradient.nonzero-end-align` make these values 0.

#### `test_a_regular_rf_time_shape_equals_the_dump_and_a_pulse_of_points_does_not`

**Checks:** For `valid_rf_time_shapes.seq` without its block 11 (RF 3, the short uncompressed pulse
`0.5 1.5 2.5`, on which the oracle crashes, D2.10): RF 2, whose time shape `1 2 2 47` has 50 samples
and times 1, 3, ..., 99 (cells of 2 us, a first time of half a step), has the dwell 2 us, the duration
100 us and the samples of the reader; RF 4 (times 0 and 100) and RF 5 (times 1, 2, 4, 7, 10 with
other values) are points in `spec`, and the reader plays them as cells of 1 us (100 and 10 cells),
so the test finds the difference of D2.11 there and no other.

**How:** The test removes the line of block 11 from the text of the fixture, writes the file to `tmp_path`,
reads it and runs the oracle with `--dump`, compares the two with the function of the test above
(`_compare_file`), and checks the dwell and the duration of RF 2, that RF 4 and 5 have no dwell, and the
dwells and durations of the reader's events.

**Assumptions:** The file keeps the signature of the whole fixture, which does not match (a mismatch is
not a rejection). The duration and the samples of the points are not compared with the reader's.

### 2.24 The decoding against MATLAB Pulseq (`test_matlab_oracle.py`)

`test_matlab_oracle.py` compares the decoding of the package with MATLAB Pulseq (the `matlab` folder of
pulseq/pulseq at the commit in `flake.nix`), run under GNU Octave by the command `pulseq-matlab-oracle`
(`tests/matlab_oracle/`). The files are those of `tests/seqfiles/valid_*.seq` and
`tests/seqfiles/oracle/*.seq` that the `spec` interpreter (`seqfile.read_seqfile`) accepts. A file that it
rejects is skipped with its rules; MATLAB never reads it, because such a file can make MATLAB loop with no
end. Two files that `spec` reads are skipped with a reason when MATLAB fails on them (the dictionary
`MATLAB_CANNOT_READ`): `valid_comment_in_shape.seq` (D2.5) and `valid_label_unknown.seq` (D2.19). `tests/oracles/matlab.py` runs the command at most one time per test
session, on all the files that are not in its cache (`.pytest_cache/d/matlab-oracle`). The cache key of a
file is the SHA-256 of the store path of the command and of the bytes of the file, so a later run with the
same files and the same command does not start Octave. The whole module skips when the command is not on the
PATH: only the default devShell has it, not the `ci` shell. Block `b` of the model, in play order, is block
`b + 1` of MATLAB. A value is compared to a relative 1e-12 of the largest magnitude of its event or axis, and
a time to an absolute 1e-12 s. Each failure lists every difference with the file, the block, the field and
the two values. Where the package decodes a file otherwise than MATLAB, the tests do not compare that part,
and the test gives the reason: `shape_dur` of an RF event of cells whose dwell is more than one RF raster, and
of one of points whose last time is not a whole number of RF rasters (D2.12); `first` of a 1.4 gradient with a
time shape (U23); MATLAB's restored points of an arbitrary gradient of time ID 0 (U21); and the waveform of a
file in which a block plays a rotation (U22).

#### `test_the_events_of_each_block_are_those_of_matlab_pulseq`

**Checks:** For each file, the number of blocks is MATLAB's, and each block has an RF, gx, gy, gz and ADC
event where MATLAB's `getBlock` has one. Each event of `decode_rf`, `decode_gradients` and `decode_adc` has
MATLAB's values:

- RF: always `center` (for a 1.4 file the package's is None), `delay`, the four offsets, and `use` as
  MATLAB's word; for every RF event, cells and points, also `magnitude` against `signal_abs`, `phase` against
  `signal_angle` modulo 2π where the magnitude is not 0, and `t`; and `shape_dur` where MATLAB's rounding
  gives the end of the package: with no time shape, for cells of one RF raster, and for points whose last time
  is a whole number of RF rasters;
- a trapezoid: amplitude, rise, flat and fall times, delay;
- an arbitrary gradient: `waveform`, `tt`, `shape_dur`, `first` (not for a 1.4 file with a time shape),
  `last`, `delay`, `shape_id`, `time_id`;
- ADC: `num_samples`, `dwell`, `delay`, the four offsets, `phase_modulation` (MATLAB's `[]` is the
  package's None).

**How:** The test (one case for each file) reads MATLAB's JSON from the oracle and compares each event of
each block field by field. Values are compared to a relative 1e-12 of the largest magnitude of the event,
times to 1e-12 s, and IDs, counts and words exactly. RF `use` maps `e r i s p` to MATLAB's words and `o` and
`u` to `'undefined'`, as `rfFromLibData` of `Sequence.m` does.

**Assumptions:**

- MATLAB's `rf.t` is the decompressed time shape times the RF raster, and `rf.signal` the samples
  (`Sequence.m:526-531`). The package's `t` is the same for points, and for the cells of a regular time shape
  (the first time is half a step, so the cell centres are the shape times), so `t`, `magnitude` and `phase`
  agree for every RF event.
- MATLAB's `shape_dur` is the last time rounded up to the RF raster, `ceil((t_last - eps) / raster) raster`
  (`Sequence.m:531`), or the number of samples times the RF raster without a time shape (`Sequence.m:535`).
  The package's is `n dwell` for cells and the last time for points. They are equal for cells of one RF
  raster (the last time `n - 0.5` rounds up to `n`) and for points whose last time is a whole number of RF
  rasters; the test compares only those. In the corpus the cells of a regular time shape with a step of more
  than one raster (`valid_rf_time_shapes.seq` RF 2, `oracle/koma_v1.5_spiral.seq` RF 1) differ by half a
  step (D2.12): they are not compared. No file of the corpus has points with a last time that is not a whole
  number of rasters; that these differ is read from the MATLAB code, and not run.
- In a 1.4 file, MATLAB carries `first` of a gradient with a time shape over from the block before
  (`read.m:339-350`), and the package takes the sample at time 0 (U23), so that field is not compared.
- MATLAB gives no event IDs, no RF amplitude or shape IDs, no arbitrary-gradient amplitude and no ADC phase
  shape ID, so the test does not compare them. The trapezoid properties `shape_dur`, `first` and `last` are
  not compared.
- The test trusts MATLAB Pulseq under Octave as the reference, and its JSON as written by `dump.m`.

#### `test_the_block_durations_are_those_of_matlab_pulseq`

**Checks:** For each file, `SequenceData.block_durations_s` equals MATLAB's `blockDurations` to
1e-12 s.

**How:** The test (one case for each file) compares the two arrays element by element.

**Assumptions:** Both are the duration in ticks times `BlockDurationRaster`. The test does not check
a block that only MATLAB has.

#### `test_the_gradient_waveform_of_each_axis_is_that_of_matlab_pulseq`

**Checks:** For each file in which no block plays a rotation, and each axis, `GradientSampler` of the
package's model has the values of MATLAB's polyline from `waveforms_and_times(true)`, at each time
of the polyline and at the midpoint of each pair of consecutive points with distinct times. An axis
where MATLAB has no point has no event in the package's model.

**How:**

- The test (one case for each file) skips a file in which the extension list of a block reaches a
  `ROTATIONS` object: MATLAB rotates the gradients of the block and `strict` does not (U18, U22).
  `test_the_rotated_gradients_of_each_interpreter_are_those_of_matlab_pulseq` compares such files.
- It builds the sampler from the model with `_index_from_data`, `_dense_ids`, `decode_gradients`,
  `_points_from_events` and `GradientSampler._from_parts`, and samples it at MATLAB's times.
- Where MATLAB has several points at one time (a step), the expected value is the first of them: the
  value before the step, as the package gives it. At a midpoint, the expected value is MATLAB's
  segment line at the float midpoint, so that the rounding of the time is not a difference.
- Inside an arbitrary gradient of time ID 0, more than 1e-12 s from its ends, a MATLAB point that is
  not at a sample centre (more than 1e-6 raster from one) is not compared, and neither are the
  midpoints next to it: MATLAB draws such a gradient with `mr.restoreAdditionalShapeSamples`
  (`Sequence.m:2018`), which guesses values at the raster edges, and the package keeps the straight
  lines between the sample centres (U21). Its sample centres and its two ends are compared.
- The tolerance is a relative 1e-12 of the largest absolute value of MATLAB's axis.

**Assumptions:**

- MATLAB's polyline is sampled only between its first and last points; the value before and after
  them is not compared.
- A file with a played rotation has no waveform comparison at all, also on its blocks without a
  rotation. `valid_1_5_1_rotation_not_played.seq` has the gradients of `valid_1_5_1.seq` without the
  played rotation, so they are compared.
- A sample centre of a gradient of time ID 0 that MATLAB drops (it removes points on a straight line)
  is not compared.

#### `test_the_adc_sample_times_are_those_of_matlab_pulseq`

**Checks:** For each file, the time of each ADC sample, block start + `delay` + `(k + 0.5) * dwell`
in play order, equals MATLAB's `t_adc` to 1e-12 s.

**How:** The test (one case for each file) computes the times from the index of the model (`start_s`)
and `decode_adc`, joins them in play order and compares them with `t_adc`.

**Assumptions:** The block start is the sum in play order of the block durations (`_index_from_data`).
The test does not check the phase or frequency of the samples.

#### `test_the_rotated_gradients_of_spec_are_those_of_matlab_pulseq`

**Checks:** For each file with a `ROTATIONS` section, the rotated gradients of `spec` (each block
turned by the model's normalized quaternion with `decoding.rotate`), from 1.5.1, equal MATLAB's
rotated polyline from `waveforms_and_times` (`mr.rotate3D`) on each axis, to 1e-6 of the axis's
largest value. The record has as many blocks rotated as blocks with a rotation (0 for
`valid_1_5_1_rotation_not_played.seq`). Where a block plays a rotation that is not the identity,
the unrotated gradients (`rotated=False`) differ from MATLAB's. The comparison is the helper
`compare_rotated_gradients`, which `test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq`
(section 3.9) also calls for `cpp-siemens`.

**How:**

- The test (one case for each file) reads the file with `spec`, and the helper samples the
  decoding's `gradients_at` at the midpoint of each segment of MATLAB's polyline, with the block and
  the time in it from the cumulative block durations.
- It leaves out the segments where MATLAB guesses the edges of an arbitrary gradient (U21, as the
  test of the waveform), and each segment with an end within 1e-12 s of a block boundary: there
  MATLAB can join the last point of one block to the first sample of the next (in
  `valid_1_5_1.seq`, from a gradient that ends at 282 842 Hz/m to an oversampled gradient whose
  first sample is 5 µs later), and each interpreter decodes each block alone (D2.14).
- It skips a file older than 1.5.1 (`valid_1_5_0_extensions_of_1_5_1.seq`): MATLAB rotates in any
  version, and `spec` reads ROTATIONS from 1.5.1 only (P20, rule 2).
  `test_a_file_older_than_1_5_1_with_rotations_is_not_rotated` checks that file.

**Assumptions:** The tolerance of 1e-6 (`FLOAT32_REL`) covers the float32 amplitudes of a plugin
interpreter such as `cpp-siemens` (P6) against MATLAB's float64; `spec` is in float64.
`koma_v1.5_rotation_radial_tiny.seq` and `pulseq_make_radial.seq` are the radial cases of
`docs/plans/scanner-settings-study.md` section 3.5; the `valid_1_5_1` family adds an extended
trapezoid in a rotated block. A file that `spec` rejects or that MATLAB cannot read is skipped.

### 2.25 The sanitized C++ oracle (`test_cpp_oracle_sanitized.py`)

`test_cpp_oracle_sanitized.py` tests `pulseq-cpp-oracle-sanitized`: the driver of
`tests/cpp_oracle/` and the reader `ExternalSequence`, built by `flake.nix` with clang (LLVM 22),
AddressSanitizer, UndefinedBehaviorSanitizer and the assertions of the C++ standard library
(`_GLIBCXX_ASSERTIONS` for libstdc++ on Linux, the debug hardening mode of libc++ on macOS), and
the annotation of the capacity of a vector (`_GLIBCXX_SANITIZE_VECTOR` on Linux). It
exits with 3 when one of them fires, so "undefined behaviour" is a verdict of its own, the same on
each platform, while an ordinary build of the reader crashes, accepts or rejects such a file by
platform (section 5.3 of `docs/plans/parser-redesign.md`). The devShell and the `ci` devShell have
the program on the PATH; the whole module skips when it is not. The verdicts of the test helper
are "accept" (exit 0), "reject" (1), "undefined" (3), "no end" (no end in 10 s, `TIMEOUT` of
`test_cpp_oracle.py`) and "crash" (another exit status or a signal). The fixtures of
`tests/seqfiles/undefined/` are the cases of section 5.3 that had no fixture: `version_last.seq`
(D5.1), `rf_time_id_minus_1.seq` (D5.3) and `shape_decompress_longer.seq` (D5.5), each a change of
`valid_no_signature.seq` that its comment states.

#### `test_the_tables_name_only_fixtures_that_exist`

**Checks:** Each file that `UNDEFINED`, `NO_END` and `REJECTED` name is a fixture under
`tests/seqfiles/`, and no file is in two of them.

**How:** The test compares the names with the `.seq` files under `tests/seqfiles/`.

**Assumptions:** None beyond the names.

#### `test_the_sanitized_oracle_accepts_a_minimal_valid_file`

**Checks:** The sanitized oracle accepts the minimal Pulseq 1.5.0 file of `test_cpp_oracle.py`.

**How:** The test writes the file to `tmp_path`, runs the oracle and checks the verdict "accept".

**Assumptions:** The test shows that the program starts (AddressSanitizer of LLVM 21 hangs at the
start of each process on macOS 26) and that it accepts one file.

#### `test_the_sanitized_verdict_of_each_fixture`

**Checks:** For each `.seq` file under `tests/seqfiles/`, the verdict of the sanitized oracle is
the one of the tables: "undefined" for the files of `UNDEFINED`, "no end" for those of `NO_END`,
"reject" for those of `REJECTED`, and "accept" for each other file. A verdict "undefined" comes
with the report of a sanitizer or of the driver (`undefined behaviour`) on stderr.

**How:** The test (one case for each file) runs the oracle on the file once and compares the
verdict.

**Assumptions:**

- `UNDEFINED` gives each file its entry of section 5.3 and, where the test author had it, the line of
  `ExternalSequence.cpp` where the build stops. The lines come from a build of the same flags at `-O0` with
  debug information and a symbolizer, which the test does not have; the test checks the verdict only,
  not the line. `valid_rf_time_shapes.seq` (D5.8: the resampling of its RF 3 `0.5 1.5 2.5` reads
  past the stored samples) has no line, because the stack trace of the macOS build has none.
- The new fixtures `bad_syntax_shape_end.seq`, `valid_arbitrary_gradient_5us_raster.seq`,
  `valid_comment_in_shape.seq` and `valid_last_section_no_blank.seq` are in `REJECTED` (the oracle
  exits with 1, without undefined behaviour); `valid_rf_time_shapes.seq` is in `UNDEFINED`.
- `bad_ref_extension_cycle.seq` (D5.4) is "no end", not "undefined": the loop over a cycle in an
  extension list appends a label to a vector in each turn, so no sanitizer fires, and the memory
  grows with no end (about 3 GB in the 10 s of the sanitized build). A machine with less memory
  could end it earlier.
- `bad_syntax_shape_no_blank_line.seq` is "undefined" by D5.1: the reader does not read the shapes
  after the shape with no blank line (D3.11), and a gradient names one of them.
- A sanitizer finds undefined behaviour only on the paths that a file takes. The test covers the
  first mode of the driver (load and decode each block), not `--dump` or `--sample`.

#### `test_each_case_of_undefined_behaviour_of_the_plan_has_a_fixture`

**Checks:** The entries of `UNDEFINED` are D5.1, D5.3, D5.5, D5.6, D5.7 and D5.8, and the entry
of `NO_END` is D5.4: each case of section 5.3 of the plan has a fixture.

**How:** The test compares the sets of entries.

**Assumptions:** The entries are the labels that the tables give; the test does not read the plan.

#### `test_the_ordinary_oracle_gives_the_same_verdict_where_the_reader_has_no_undefined_behaviour`

**Checks:** For each fixture where the sanitized oracle accepts or rejects, `pulseq-cpp-oracle`
(the build of `test_cpp_oracle.py`) gives the same verdict: the sanitized build does not change
what the reader does with such a file.

**How:** The test runs the ordinary oracle on each such fixture and lists each file with another
verdict. It skips when `pulseq-cpp-oracle` is not on the PATH.

**Assumptions:** It compares the exit status only, not the dump.

#### `test_the_sanitized_oracle_reports_a_missing_shape_built_in_the_test`

**Checks:** The minimal file with an RF event whose phase shape is not in `[SHAPES]` (D5.1) is
"undefined", where `test_the_oracle_does_not_accept_a_file_that_it_cannot_decode` of
`test_cpp_oracle.py` can only say "reject or crash".

**How:** The test writes the file to `tmp_path`, runs the sanitized oracle and checks the verdict.

**Assumptions:** One case of D5.1; the fixtures cover the others.

### 2.26 The "as written" reading (`test_as_written.py`)

`test_as_written.py` tests `as_written.read_as_written`, the "as written" reading of a Pulseq text
file: the sections, the rows and their typed fields, with line numbers, without loss. The files are
the fixtures of `tests/seqfiles` (all of them, the subfolders included) and small files that the
tests write. The `spec` interpreter (`seqfile.spec`) reads every file through this reading; its
tests are section 2.19.

#### `test_every_fixture_is_read_without_loss`

**Checks:** For each fixture, the reading keeps every byte (`raw`), and each line of the file is in
the reading once, with its number and its text: a header, a blank or `#` line, a `shape_id` or
`num_samples` line of a shape, or a row of a table. `line_count` is the number of lines, and the
`header` of each section is its line, stripped.

**How:** For each file (parametrized), the test collects the lines of the preamble and of each
section with their numbers, sorts them, and compares them with the lines of the text split at
`\n`.

**Assumptions:** The text of a header is compared stripped: its white space is not in
`Section.header`, only in `raw`.

#### `test_random_edits_are_read_without_loss_and_without_an_error`

**Checks:** For 300 random edits of the valid fixtures (a line added, removed, or changed by a
token such as `nan`, `+2`, `[BLOCKS]`, `extension`, `shape_id`, a no-break space or `\r`, some with
CRLF line ends and some with a byte that is not UTF-8), the reading raises nothing, keeps every
line as `test_every_fixture_is_read_without_loss` checks, and the count of fields of each row is
that of its text.

**How:** The test edits the text with a seeded random generator, writes it, reads it, and checks
each file.

**Assumptions:** The edits are those of the list in the test; the seed fixes them.

#### `test_a_byte_that_is_not_utf_8_is_kept_and_its_offset_given`

**Checks:** The reading of `bad_syntax_encoding.seq` gives in `not_utf8` the offset of its byte
0xB5, and keeps that byte in the text of its comment line as the lone surrogate U+DCB5. A valid
fixture has `not_utf8` None.

**How:** The test reads both files and looks for the byte and the surrogate.

**Assumptions:** None.

#### `test_blank_and_comment_lines_do_not_end_a_section`

**Checks:** A blank or `#` line inside a section is in its `blank` or `comments` with its number
and text, and the rows after it are rows of the same section. A data line before the first header
is a row of the preamble. `version` is read from rows on both sides of a blank line.

**How:** The test writes a small file with such lines and compares the line numbers.

**Assumptions:** None.

#### `test_headers_and_their_names_as_written`

**Checks:** A line whose first character that is not white space is `[` is a header, with its name
as written between the brackets (`[ BLOCKS ]` gives " BLOCKS "), and None for a header with no `]`
at its end. A line whose first word is `extension`, followed by a space, a tab or the end of the
line, is an `extension` header with its fields and its type as an int (None if it is not one); a
line that starts with `extensions` is a row.

**How:** The test writes six such lines and compares `header`, `name`, `extension` and
`extension_type`.

**Assumptions:** None.

#### `test_the_signed_bytes_are_those_of_the_specification`

**Checks:** `signed_bytes()` is every byte before the `\n[SIGNATURE]` of the 1.5.1 fixture, and
its md5 is the stored hash. For `valid_crlf.seq` its md5 is `e06b91d84d3fba7303a915e068320754`, the
md5 that the rule of the specification gives (spec:223). A file with no
`[SIGNATURE]` gives None, and a file that starts with it gives no byte.

**How:** The test reads the files and compares the bytes and the md5.

**Assumptions:** The md5 of the CRLF fixture was computed for the rule of the specification (spec:223), outside this test.

#### `test_the_arrays_of_the_reading_are_read_only`

**Checks:** `lines`, `counts`, `values` and `valid` of each table of the 1.5.1 fixture are
read-only.

**How:** The test reads the `writeable` flag of each array.

**Assumptions:** The flag can be set back to True by a caller; the test does not cover that.

#### `test_seqfile_exports_the_reading`

**Checks:** `pulseq_analysis.seqfile` gives `read_as_written`, `AsWritten` and `Table`, the names of
`as_written`.

**How:** The test compares the objects.

**Assumptions:** None.

#### `test_the_1_5_1_fixture_has_its_values_as_written`

**Checks:** The 1.5.1 fixture has the version (1, 5, 1); its `[RF]` table has the columns of 1.5,
the values of its row as written and the line of the row; its ADC dwell times are in ns as
written; `[DEFINITIONS]` has one text column `key`, with the values as text after it; and
`extension RF_SHIMS` has the ID and the number of channels as int and its values as float.

**How:** The test compares the tables with the numbers of the text, which it writes in the test.

**Assumptions:** The expected numbers were read from the text of the fixture by hand.

#### `test_a_1_4_file_has_the_columns_of_1_4`

**Checks:** The reading of the 1.4.1 fixture has the version (1, 4, 1), and the columns of 1.4 for
`[RF]`, `[GRADIENTS]` and `[ADC]`.

**How:** The test compares the names of the columns.

**Assumptions:** None.

#### `test_a_file_with_no_version_has_the_columns_of_1_5`

**Checks:** A file with no `[VERSION]` has `version` None, and its `[RF]` table has the columns of
1.5.

**How:** The test reads a file of one `[RF]` row.

**Assumptions:** None.

#### `test_each_field_is_read_by_the_kind_of_its_column`

**Checks:** The fields of the tables as written (spec:176, spec:293-455): `30.5` in an int column is not valid and its value is 0,
`+30` is 30, a row of 7 values has no valid eighth field, a row of 9 keeps its ninth as text, `nan`
is a valid float, `1e999` is infinite, -2**63 is a valid int and 2**63 is not, and the text of a
field is kept.

**How:** The test writes `[BLOCKS]` and `[TRAP]` rows and compares `counts`, `values`, `valid`,
`fields` and `cells`.

**Assumptions:** None.

#### `test_the_fast_and_the_slow_typing_agree`

**Checks:** The typing by `numpy.loadtxt` and the typing one field at a time give the same values,
validity, counts and dtypes, for 400 random tables of int, float and text columns whose fields are
taken from tokens at the edges of each kind (signs, leading zeros, -2**63 and 2**63, `nan`,
`Infinity`, `1_0`, `0x10`, a non-ASCII letter) and whose rows have other separators (tabs, a
no-break space, a vertical tab), white space at their ends, and missing or extra fields.

**How:** For each table, the test calls `as_written._fast` and, when it gives a table,
`as_written._slow`, and compares the arrays.

**Assumptions:** The tokens are those of the list in the test. A table that `_fast` leaves to
`_slow` is not compared.

#### `test_the_other_spaces_are_the_white_space_of_str_split`

**Checks:** The characters that `_fast` replaces with a space are the white space of
`str.isspace`, but `\n`, the space and the tab.

**How:** The test compares the set with the characters of Unicode for which `str.isspace` is true.

**Assumptions:** The Unicode database of the Python of the devShell.

#### `test_the_shapes_and_their_rows`

**Checks:** In `[SHAPES]`, a `shape_id` line starts a shape, with its ID as an int (None for
`shape_id x`); the line right after it is its `num_samples` line; its rows run to the next
`shape_id` line past a blank line; a line `shape_idX 2` is a row (a sample that is not valid);
the rows before the first shape belong to no shape; and the blank lines are in `blank`.

**How:** The test writes a section of three shapes and compares the shapes, the lines of their
rows and the validity of the samples.

**Assumptions:** None.

#### `test_a_section_other_than_shapes_has_no_shapes`

**Checks:** No section of the 1.5.1 fixture but `[SHAPES]` has shapes.

**How:** The test reads the `shapes` of each section.

**Assumptions:** None.

#### `test_a_text_field_of_any_length_is_kept`

**Checks:** A label name of 1, 63, 64 and 100 characters is kept whole, and the text column is as
wide as the longest name.

**How:** For each length (parametrized), the test writes an `extension LABELSET` section and
compares the names and the dtype. `numpy.loadtxt` reads text into 64 characters, so a name of 64
or more is read one field at a time.

**Assumptions:** None.

---

### 2.27 The plugin interpreters (`test_interpreters.py`)

`test_interpreters.py` tests how pulseq-analysis finds and uses an interpreter of another
distribution (`seqfile.interpreters`, P21 of `docs/plans/parser-redesign.md`): the entry-point
group `pulseq_analysis.interpreters`, the protocol `Plugin`, and `synth.decode` of a plugin's
model. It needs no plugin: a fake plugin (the class `Fake` of the module, a frozen dataclass
that reads with `spec` and decodes to a tuple) stands for one, and the tests give its entry point
by replacing `importlib.metadata.entry_points` in the module `interpreters` (`monkeypatch`). `Fake`
implements version 1 of the protocol (`protocol`, and `decode(data, session=None)`); the version
is tested in section 2.29. The interpreter `cpp-siemens` is tested with its distribution (sections
3.8 and 3.9).

#### `test_no_plugin_is_installed_with_the_package`

**Checks:** In the environment of the tests, `interpreters.interpreter_names()` is `("spec",)`:
pulseq-analysis installs no plugin.

**How:** The test calls the function.

**Assumptions:** The environment has no distribution that gives an entry point of the group. The
test fails in an environment that has one (for example pulseq-cpp-siemens).

#### `test_a_name_that_no_interpreter_has_names_the_installed_ones_and_the_group`

**Checks:** `read_seqfile` with the name `cpp-siemens`, with no plugin installed, raises
`ValueError` with the message "no interpreter is named 'cpp-siemens'; the installed interpreters
are spec. A distribution adds one through the entry-point group pulseq_analysis.interpreters."
`seqfile.interpreter(3)` raises `TypeError`.

**How:** The test calls both and compares the message of the first.

**Assumptions:** No plugin is installed (the test above).

#### `test_a_plugin_reads_and_decodes_a_file_by_name_and_as_an_object`

**Checks:** With the entry point `fake`, `interpreter_names()` is `("spec", "fake")` and
`interpreter("fake")` is `Fake()`. `Fake()` is a `Plugin` and `Spec()` is not. `read_seqfile` of
`valid_1_5_1.seq` with the name `fake` gives a model whose `interpreter` is `Fake()`; with an
object `Fake("other")` and the path as a text it records that object. `synth.decode` of the model
gives what `Fake.decode` gives. `events.decode_rf` of the model raises `TypeError` that names
`synth.decode`.

**How:** The test installs the entry point and calls each function.

**Assumptions:** The fake plugin reads with `spec`, so the test does not check what a plugin
reads.

#### `test_a_plugin_that_does_not_load_or_has_another_name_or_two_entry_points_is_an_error`

**Checks:** An entry point whose module does not exist raises `ImportError` that names the
interpreter and says that it did not load, chained to the `ModuleNotFoundError`. An entry point
whose class has another `name` raises `TypeError` ("whose name is not 'fake'"). Two entry points
with one name raise `ValueError` ("more than one interpreter is named 'fake'").

**How:** For each case, the test installs the entry points and asks `interpreter("fake")` (or
`"broken"`).

**Assumptions:** None.

#### `test_a_class_is_not_an_interpreter_and_the_error_names_its_call`

**Checks:** A class in place of an interpreter object raises `TypeError` whose message names the
call that makes the object (finding 1.2.4c of `docs/reviews/2026-10-13-code-review.md`): the class
`Fake`, which has every member of `Plugin`, to `interpreter` and to `read_seqfile` of
`valid_1_5_1.seq` gives a message with `Fake()`, and the class `Spec` to `interpreter` gives a
message with `Spec()`.

**How:** The test calls each function with the class, with no entry point installed.

**Assumptions:** The test does not check the rest of the message. The message of a call of an
unbound method (`Fake.read()`) does not contain `Fake()`, so the test fails when the class
reaches `read`.

#### `test_a_plugin_cannot_be_spec`

**Checks:** An entry point named `spec` is not an interpreter: `interpreter_names()` is still
`("spec",)` and `interpreter("spec")` is `Spec()`.

**How:** The test installs an entry point named `spec` and calls both.

**Assumptions:** None.

#### `test_the_package_has_no_reference_to_a_plugin`

**Checks:** No line of a Python file of `src` and no line of `pyproject.toml` names pulseq-cpp-siemens,
`CppSiemens` or `cpp-siemens` (in any case, with `-` or `_`). So the package has no import of the
plugin and no dependency on it (P21).

**How:** The test matches a regular expression against each line of those files and lists the
matches by file and line.

**Assumptions:** The test reads text only. A reference through a different name, or in a file
outside `src` and `pyproject.toml` (the documents, the tests), is not found.

### 2.28 A pypulseq sequence in memory (`test_from_pypulseq.py`)

`test_from_pypulseq.py` tests `seqfile.read_pypulseq` (`seqfile.from_pypulseq`, task R15 of
`docs/plans/parser-redesign.md`): a `pypulseq.Sequence` in memory, written with pypulseq's writer
and read through an interpreter. The interpreters are `"spec"` and `Spec()`. The checks are
functions of the module (`check_reads_as_its_written_file`, `check_the_mixed_sequence`,
`check_the_sequence_is_not_changed`, `check_a_rejection`). The tests of `cpp-siemens`
(`test_interpreter_in_pulseq_analysis.py`, section 3.9) call all but
`check_the_sequence_is_not_changed` for their interpreter: the interpreter reads only the
written text, so the tests here cover it. The sequences are `mixed_sequence` of the module (a slice-selective sinc RF
with its gradient, a phase encode, a readout trapezoid with its ADC, an arbitrary gradient,
labels `LIN` (SET) and `SLC` (INC), a delay block, two repetitions with repeated events) and
five synthetic sequences: `gre_sequence`, `spin_echo_sequence`,
`arbitrary_gradient_sequence`, `border_sequence` (extended trapezoids) and `empty_sequence`.

#### `test_a_sequence_in_memory_reads_as_its_written_file`

**Checks:** For each sequence and each interpreter (`check_reads_as_its_written_file`), `read_pypulseq(seq, interpreter)` equals
`read_seqfile` of the file that `seq.write(path)` writes with the writer's defaults, except
`origin`, which is `"pypulseq"` in place of `"file"`. The result has the signature of the file.

**How:** The test reads the sequence with `read_pypulseq`, then writes a deep copy of it to a
file of `tmp_path` with `write(path)` and reads the file with the same interpreter. It compares
the two models with `==` (the model's value equality, every field but `reading`) after it sets
`origin` to `"file"`, and compares the interpreters and the signatures.

**Assumptions:** `write` with the defaults runs pypulseq's timing check, which only warns, and
`read_pypulseq` does not run it; the bytes are otherwise the same, which the equal signatures
(the MD5 hash of the text) confirm. The `reading` of `cpp-siemens` is not compared by `==`; it is
the reader's reading of the same bytes.

#### `test_the_mixed_sequence_has_each_kind_of_event`

**Checks:** The model of `mixed_sequence` has 10 blocks, one RF event (the writer merged the
repeated one), one ADC event, one arbitrary gradient, at least three trapezoids, two `LABELSET`
rows and one `LABELINC` row, with each interpreter (`check_the_mixed_sequence`). So the comparison above covers RF, gradients
of both kinds, the ADC and the labels.

**How:** The test counts the rows of the tables of the model.

**Assumptions:** The counts are those of pypulseq's writer at the version of `uv.lock`.

#### `test_the_sequence_is_not_changed`

**Checks:** `read_pypulseq` does not change the caller's sequence (`check_the_sequence_is_not_changed`): every attribute but
pypulseq's block cache is the same after the reading, the definitions have no `TotalDuration`
(which `write` sets), and the signature value is still empty (which `write` sets).

**How:** For each sequence and each interpreter, the test pickles the attributes of the sequence
(`vars(seq)`, without `block_cache`) before and after the reading, and compares the bytes.

**Assumptions:** pickle gives the same bytes for the same state of the attributes. The block
cache is left out: it holds the decoded blocks that `get_block` caches, not the sequence.

#### `test_the_temporary_folder_is_removed_and_nothing_is_written_next_to_the_caller`

**Checks:** `read_pypulseq` writes nothing to the current folder, and the temporary folder that
it writes to is removed after the reading.

**How:** The test changes to an empty folder of `tmp_path`, sets `TMPDIR` to a folder in it
(and resets `tempfile.tempdir`, so that `tempfile` reads `TMPDIR` again), reads a sequence, and
lists both folders.

**Assumptions:** `tempfile` uses `TMPDIR` on the platforms of CI.

#### `test_a_rejection_is_the_file_s_and_names_the_sequence_not_the_temporary_file`

**Checks:** A sequence that an interpreter rejects raises the `SeqFileError` of its written file
(the same code and violations), whose `path` is `from_pypulseq.SOURCE`
(`"<pypulseq.Sequence>"`), whose message names the sequence and not the temporary file, and
which does not chain the error of the temporary file. The case is `spec` with a trapezoid of
1 ms in a block of 0.5 ms (`block.event-too-long`); `cpp-siemens` has its own case (section 3.9).

**How:** The test calls `check_a_rejection`: it reads the sequence with `read_pypulseq` and its
written file with `read_seqfile`, and compares the two errors.

**Assumptions:** None.

#### `test_an_unknown_interpreter_and_an_object_that_is_not_a_sequence_raise`

**Checks:** An unknown interpreter name raises `ValueError`, and an object that is not a pypulseq
sequence (a path) raises `TypeError` that names `pypulseq.Sequence`.

**How:** The test calls `read_pypulseq` with each.

**Assumptions:** None.

### 2.29 The scanner session (`test_session.py`)

`test_session.py` tests the scanner session of task R16 (`synth.scanner`, section 7.8 of
`docs/plans/parser-redesign.md`, P20 and P22): `Session`, the shared simulation
(`soft_delay_durations`, `fov_flags`, `physical_gradients`), `SettingError`, the records
(`SoftDelayRecord`, `FovRecord`), the stored and actual durations of `spec`'s decoding, `load` with
a session, and the version of the plugin protocol. Most tests use `tests/session/scanner_session.seq`
(1.5.1), outside `tests/seqfiles` so that the tests of every fixture do not read it. In play order
from 0 it has: 0 gx; 1 a soft delay TE (num 0, offset -100 us, factor 2); 2 gx rotated by 90 degrees
about z; 3 gx with NOROT 1; 4 gy with NOROT 0 and NOSLC 1; 5 gz with NOSCL 1 and NOSLC 0; 6 a soft
delay TE (num 0, offset 5000 us, factor -1); 7 a soft delay TR (num 1, offset 0, factor 1); 8 gx.
Each trapezoid has a delay of 50 us, ramps of 100 us and a flat top of 200 us, in a block of 500
us. Edited copies of it are written to `tmp_path`. The tests through `cpp-siemens` are in section
3.12.

#### `test_the_default_session_is_neutral_and_a_session_compares_by_value`

**Checks:** `Session()` is neutral (no soft delay, the identity rotation (1, 0, 0, 0), the scaling
(1, 1, 1)) and its `str` is "session: neutral". A session keeps its soft delays as (hint, value)
pairs sorted by hint, whatever order and form (a dict or pairs) they are given in; two sessions
with the same values are equal and one is the key of the other in a dict; `str` names each
setting that is not its default. A quaternion within 1e-6 of norm 1 is divided by its norm. A
session is frozen and survives `pickle`.

**How:** The test makes sessions and compares them.

**Assumptions:** None.

#### `test_a_session_refuses_a_value_that_is_not_a_setting`

**Checks:** An empty or non-text hint, a value that is not a real number (a text, a bool), a value
that is NaN, a hint given twice, soft delays that are a text, a quaternion of 3 values or whose
norm is not 1 within 1e-6 (also 0), a scaling of 2 values, of 0 or below, or infinite: each raises
`TypeError` or `ValueError` with a message that names the problem.

**How:** Parametrized over the cases, with the error type and a part of the message.

**Assumptions:** None.

#### `test_a_setting_that_the_session_does_not_have_is_a_type_error`

**Checks:** Rule 8: `Session(repetitions=2)` raises `TypeError`, and so do `synth.decode` and
`load` given a session that is not a `Session` (a dict); their message names `Session`.

**How:** The test calls each.

**Assumptions:** None.

#### `test_a_soft_delay_is_the_rule_of_the_specification_rounded_half_away_from_zero`

**Checks:** `soft_delay_durations` gives `value / factor + offset` in units of the raster, rounded
half away from 0 (as MATLAB's `round`): with a 10 us raster, the value 0 and the offset 25 us give 3
(2.5 rounds up); the value 1 ms gives 103 and the value 14 us 1 (1.4 rounds down). A block whose
hint has no value keeps its stored duration. The record has the values, the two hints, 2 blocks,
the blocks applied, and `unset` the hint with no value.

**How:** The test calls the function on two `SoftDelay` values, each in a pure delay block.

**Assumptions:** None.

#### `test_the_flags_of_the_field_of_view_are_a_state_across_blocks`

**Checks:** `fov_flags` sets a flag for the block of its LABELSET and the blocks after it, until a
LABELSET sets it to 0; in one block the last LABELSET of a name wins, and any value that is not 0
sets it. With no scaling flag, or another name, the scaling flag is never set.

**How:** Five LABELSET events on six blocks; the test compares the two bool arrays with the
expected ones.

**Assumptions:** None.

#### `test_spec_decodes_with_the_neutral_session_by_default`

**Checks:** `synth.decode(data)` of the fixture has the session `Session()`; its actual and stored
durations equal the model's (read-only); its `soft_delay_record` has no value, the hints TE and TR,
3 blocks and 0 applied, and says so in `str`; its flags are NOROT in block 3 and NOSLC in block 4
(not NOSCL in block 5, which `spec` does not know); its `fov_record` has the identity, the scaling
flag "NOSLC", one block with each flag, and 0 blocks rotated or scaled. `synth.decode(data,
Session())` gives the same record.

**How:** The test decodes the fixture and compares each field.

**Assumptions:** None.

#### `test_spec_sets_the_duration_of_each_soft_delay_by_its_hint`

**Checks:** With TE = 2 ms and TR = 10 ms, block 1 lasts 900 us (2e-3 / 2 - 100 us), block 6 3 ms
(2e-3 / -1 + 5000 us) and block 7 10 ms; the other blocks and the stored durations do not change;
the record has 3 blocks applied. With TE only, `unset` is TR and block 7 keeps its stored
duration. `gradients_at` is 0 after the actual end of a block (a decoding whose block 0 ends at
400 us gives 0 at 450 us).

**How:** The test decodes the fixture under the sessions, and changes `block_durations` of a
decoding with `dataclasses.replace` for the last check.

**Assumptions:** The last check makes the actual duration by hand, since a soft delay sets only a
pure delay block, which has no gradient.

#### `test_a_soft_delay_that_the_file_does_not_have_is_a_setting_error`

**Checks:** Rule 8: the hint TX (no block has it) and TE = 20 ms (block 6 gets -15 ms) raise
`SettingError`, a `ValueError` whose `reason`, `interpreter` ("spec"), `version` (1, 5, 1) and
`setting` (`soft_delays['TX']`) are those expected, whose message is "the setting ... does not
apply to this file (version 1.5.1) under the interpreter spec: REASON", and which survives `pickle`.
`load` raises it too.

**How:** Parametrized over the two sessions.

**Assumptions:** None.

#### `test_a_soft_delay_that_is_not_one_value_of_a_pure_delay_block_is_a_setting_error`

**Checks:** The user's decisions (2026-10-13), each a `SettingError` for the hint of the session,
while the file decodes with the neutral session: TR in block 2, which plays gx ("has an RF,
gradient or ADC event"); TR after TE in block 1 ("more than one soft delay"); the second TE with the
numeric ID 2 ("the numeric IDs [0, 2], not one"); TR with the numeric ID 0 of TE ("its numeric ID 0
is also that of the hints ['TE']").

**How:** Parametrized over four edits of the fixture, each with an extension list entry 10 for the
soft delay TR.

**Assumptions:** None.

#### `test_soft_delays_in_a_file_older_than_1_5_0_are_a_setting_error`

**Checks:** In the fixture as 1.4.2, the soft delays are an extension that `spec` does not know
(D4.6): the neutral session decodes with a record of no soft delay, and a value for TE raises
`SettingError` that names the version and says that soft delays came in 1.5.0.

**How:** The test edits the version of the fixture.

**Assumptions:** None.

#### `test_spec_turns_and_scales_the_field_of_view_in_the_order_of_matlab_pulseq`

**Checks:** With the field of view turned 90 degrees about x and the scaling (2, 3, 4), the
gradients of blocks 0, 2, 3, 4, 5 and 8 at 300 us are R_fov R_block S g of their logical values
(D2.20): block 2 also turned by its rotation about z, block 3 (NOROT) not turned by the field of
view, block 4 (NOSLC) not scaled, block 5 (NOSCL, unknown to `spec`) scaled. `rotated=False` gives
the logical values of the neutral session, and `rotated=True` the same as None. The record has 8
blocks rotated and 8 scaled.

**How:** The test computes the expected values with rotation matrices in numpy, to 1e-6 Hz/m.

**Assumptions:** None.

#### `test_the_flags_of_1_4_1_have_no_effect_in_an_older_file`

**Checks:** In the fixture as 1.4.0, NOROT and NOSLC are labels that `spec` does not apply (D4.7):
no block has a flag, all 9 blocks are rotated and scaled, and block 3 (NOROT in the file) gives
2e6 Hz/m on x.

**How:** The test edits the version of the fixture.

**Assumptions:** None.

#### `test_load_decodes_under_the_session_and_the_snapshot_records_it`

**Checks:** `load(path, session=...)` gives a snapshot whose `session`, decoding's session,
`soft_delay_record` and `fov_record` are those of the decoding; the block table has the actual
durations, and its end is their sum; a copy (`pickle`, `copy.deepcopy`) keeps the session; `load`
with no session has `Session()`.

**How:** The test loads the fixture with soft delays and a scaling.

**Assumptions:** None.

#### `test_the_measurements_take_the_gradients_of_the_session`

**Checks:** `gradient_peaks` under the scaling (2, 1, 1) has twice the peak of x of the neutral
session, and under the field of view turned 90 degrees about x the peak of z is the neutral peak
of y.

**How:** The test measures three snapshots of the fixture.

**Assumptions:** None.

#### `test_the_points_of_the_played_events_are_the_gradients_under_a_session`

**Checks:** Under the neutral session, soft delays, a rotation, a scaling, and both, the played
gradients of the fixture are the decoding's `gradients_at`
(`test_played.check_the_points_are_the_gradients`, section 2.3).

**How:** Parametrized over the five sessions; `test_played.load` is replaced (`monkeypatch`) by
`load` with the session.

**Assumptions:** None.

#### `test_the_plugin_protocol_has_a_version_and_decode_takes_the_session`

**Checks:** P22: `seqfile.PROTOCOL` is `interpreters.PROTOCOL`, 1. A plugin of version 1 (the
class `SessionPlugin` of the module) is found by name, and `synth.decode` gives it `Session()` by
default and the session given; `load` gives it the session. A plugin of the protocol before R16
(`OldPlugin`: no version, `decode(data)`) raises `TypeError` ("implements the plugin protocol
version None, and this pulseq-analysis uses version 1") by name and as an object.

**How:** The test installs the entry points as `test_interpreters` does.

**Assumptions:** None.

### 2.30 The imports of the package (`test_imports.py`)

`test_imports.py` tests that the package imports without pypulseq and matplotlib: pypulseq is an
optional dependency (the extra `pypulseq`), and the package draws nothing.

#### `test_the_package_and_each_module_import_neither_pypulseq_nor_matplotlib`

**Checks:** A new interpreter that imports `pulseq_analysis` and each of its modules has no
module of `pypulseq` or `matplotlib` in `sys.modules`.

**How:** A subprocess imports the package, lists its modules with `pkgutil.walk_packages`
(the subpackages and their modules), imports each with `importlib.import_module`, and checks
`sys.modules`. The test checks that more than 10 modules were found.

**Assumptions:** The test runs in the dev environment, where pypulseq is installed, so an
import of it would be found. A module that imports pypulseq only when a function runs is not
found (`test_without_pypulseq.py` runs the functions).

### 2.31 The package without pypulseq (`test_without_pypulseq.py`)

`test_without_pypulseq.py` tests that the package works without pypulseq. A subprocess sets
`sys.modules["pypulseq"] = None`, so `import pypulseq` raises `ImportError` (the subprocess
checks it), then loads each `.seq` file of `tests/seqfiles/oracle/` with `load(path)`, skips a
file that `spec` rejects (`SeqFileError` or `NotSupported`), runs `compute` and then
`to_series` of each analysis of `registry()` on each snapshot (`pns.safe.levels` with the
hardware `(pns_hardware.EXAMPLE_HARDWARE, label)`, the others with their defaults), and calls
`read_pypulseq(object())`. It prints what it loaded and ran as JSON; the module fixture runs it
one time, and each test reads its output.

#### `test_load_reads_the_oracle_files_that_it_reads_with_pypulseq`

**Checks:** The oracle files that load without pypulseq are those that load in the test's own
interpreter, and there is at least one.

**How:** The test loads each oracle file in its own interpreter, with the same skip, and
compares the lists of names.

**Assumptions:** Only `load(path)` with the default interpreter `spec` is run. The results are
not compared with those of the dev environment, only run.

#### `test_each_analysis_of_the_registry_runs_on_each_oracle_file`

**Checks:** `compute` and `to_series` of each analysis of the registry ran without an error for
each file that loaded, and the registry has `pns.safe.levels`.

**How:** The test compares the list of `file:analysis` pairs that the subprocess ran with each
loaded file times each analysis ID.

**Assumptions:** The optional parameters have their defaults (no `window`, no thresholds).

#### `test_read_pypulseq_refuses_an_object_that_is_not_a_sequence`

**Checks:** Without pypulseq, `read_pypulseq` imports, and refuses an object that is not a
pypulseq sequence with its `TypeError` ("read_pypulseq takes a pypulseq.Sequence").

**How:** The subprocess calls `read_pypulseq(object())` and records the message.

**Assumptions:** `read_pypulseq` needs pypulseq only through its argument: without pypulseq, a
caller has no sequence to give it, so no `ImportError` that names the extra is needed
(docs/plans/own-parser-tasks.md, section 8, after R14).

### 2.32 The documents (`test_documents.py`)

`test_documents.py` checks what the documents cite and link, and the tables of the documents that
repeat a table of the code. The documents are the Markdown files at the top of the repository, of
`docs/` and of `tests/` (and its folders), and the same of `packages/pulseq-cpp-siemens/`. The
plans and the reviews (`docs/plans/`, `docs/reviews/`) are not read: they keep the text of the
time they were written. The module imports only `pulseq_analysis` and the standard library, so
the docs-only path of `scripts/check` runs it with `test_interface.py`, with no build of the
plugin.

#### `test_each_record_id_that_a_document_cites_is_an_entry_of_the_record`

**Checks:** Each record ID (`D1.1` to `D7.n`) that a document cites is an entry of
`docs/discrepancies.md` or of `packages/pulseq-cpp-siemens/docs/specification.md`.

**How:** The entries are the headings `#### D<group>.<n>: ...` of the two files. The test checks
that it found entries of both files and a citation of `docs/usage.md` (so the reading is not
empty), and collects each citation of each line of each document, code blocks too, that is not an
entry.

**Assumptions:** An ID is `D`, a group from 1 to 7, a dot and a number, with no letter, digit, `_`
or dot before it and no letter, digit or `_` after it. The test does not check that the entry is
the one that the text means.

#### `test_each_relative_link_with_an_anchor_resolves`

**Checks:** Each relative link with an anchor of a document (`file.md#heading`, `#heading`) names
a file that exists, and the anchor is in that file: a heading or an `<a id>` / `<a name>` of a
Markdown file, or a line (`L12`) or a range of lines (`L12-L20`) of another file.

**How:** The test reads the inline links (`](target#anchor)`) outside the code blocks and the code
spans, and leaves out the links with a scheme (`https:`). The anchor of a heading is GitHub's: the
text of the heading without the marks of a code span or a link, in lower case, without each
character that is not a letter, a mark, a digit, `_`, `-` or a space, with each space a `-`, and
`-n` for the n-th repeat in the file. The test checks that it found a link to another document
and one within a document.

**Assumptions:** Only ATX headings (`#` to `######`) are read, and the reference links
(`[text][ref]`) are not. A `_` of emphasis in a heading stays in its anchor, where GitHub drops
it.

#### `test_the_codes_of_spec_in_the_documents_are_spec_rules`

**Checks:** The table of the codes of `docs/specification.md` (section 3) is the keys of
`spec.RULES`, in their order. The table of the codes of `docs/usage.md` ("The interpreters") and
the list of the codes of `docs/findings-for-pulseq-checks.md` (section 2.5) give each key once,
and the findings give the number of the keys.

**How:** The test reads the code spans of the first column of each table, and the number and the
code spans of the paragraph "The codes of `spec`" of the findings, and compares them with
`spec.RULES` (the lists sorted for the last two).

**Assumptions:** The ID, the basis and the text of each row are not compared with the `Rule`.

#### `test_the_codes_of_cpp_siemens_in_the_documents_are_interpreter_codes`

**Checks:** The table of the codes of `packages/pulseq-cpp-siemens/docs/specification.md` (section
2.5) gives each code of `CODES` of the plugin's `interpreter.py` once, with the ID of its entry in
`CODES`. The table of the codes of `docs/findings-for-pulseq-checks.md` (section 2.5) is the codes
of `CODES`, in their order, and the findings give their number.

**How:** The test reads `CODES` from the source of `interpreter.py` with `ast.literal_eval` of the
dict that `MappingProxyType` takes (the plugin is not imported), and compares the pairs (code, ID)
of the plugin's table, sorted, and the codes of the table of the findings with it.

**Assumptions:** `CODES` is a dict of literals in the source. The column "Entry" of the findings
is not the ID of `CODES` (it gives `D1.1` for `version.missing`, where `CODES` has "—"), and is not
compared. The text of each row is not compared.

#### `test_the_analyses_table_of_usage_is_the_registry`

**Checks:** The table of the analyses of `docs/usage.md` (section 7) has one row for each analysis
of `registry()`, and each row gives the `spec` of its analysis: the names of `params`,
`necessary`, `defaults` and `cost`.

**How:** The parameters are the keyword arguments of the call in the column `compute`, in order.
`none` is no name. A default `name=value` is the literal, or, for a name (`BIN_S`), the attribute
of the module that defines the function of the call; "the defaults of `grad_spectrum`" is the
defaults of the parameters of that function in the module `grad_spectrum`.

**Assumptions:** The columns `compute` (beyond the names of its arguments) and `to_series` are not
compared. `registry()` has only the analyses of this package in the test environment.

## 3. The package pulseq-cpp-siemens

`packages/pulseq-cpp-siemens` is the C++ reader `ExternalSequence` of pulseq/pulseq as a nanobind
extension, its own distribution with compiled wheels (P12 of `docs/plans/parser-redesign.md`;
its `README.md`). `scripts/check` builds it in its own uv project (`uv sync --frozen --project
packages/pulseq-cpp-siemens --no-editable --reinstall-package pulseq-cpp-siemens
--reinstall-package pulseq-analysis`, from its `uv.lock`, with the reader's files from the devShell's
`PULSEQ_SOURCE_DIR`), runs its tests in that environment, and adds their IDs to the file of the
TESTS.md check. The environment also has pulseq-analysis, from this checkout (the dependency group
`analysis`), for the two modules of the interpreter `cpp-siemens` (sections 3.8 and 3.9); without it
`tests/conftest.py` does not collect them, as in the wheel tests below. Those modules use the fixtures
and the helpers of the tests of pulseq-analysis (`tests/conftest.py` puts the `tests` folder of the
repository on `sys.path`). The tests use the fixtures of `tests/seqfiles`
and the package's `tests/fixtures`, and the helpers of its `tests/canonical.py`: the canonical
form of the driver's `--dump` and `--sample` (each float as the bits of the float32 that the
reader holds), and `read`, the package's verdict on a file in the words of
`tests/expected_digests.json` ("read", "rejected", "not-supported", "undefined-behaviour:CODE").
`load` takes the reader's sampling mode of an oversampled arbitrary gradient (`oversampling`:
"center", the reader's default, "edge" or "preserve"; D6.1), and the tests that compare with the
driver run in each mode (`--oversampling` of the driver).

`.github/workflows/pulseq-cpp-siemens-wheels.yml` runs on each pull request that changes the
package or the fixtures. It builds the wheels with cibuildwheel on the five platforms of the R2
report (macOS arm64 and x86_64, the latter tested under Rosetta; manylinux x86_64 and aarch64;
Windows x86_64), with the stable ABI `cp312-abi3`, and cibuildwheel runs these tests on each
wheel in a clean environment with Python 3.12. It runs them again on the native wheel of each
runner with Python 3.14. There the tests that need the C++ oracles skip, and
`test_digests.py` stands in for the driver. pulseq-analysis is not installed there, so the modules
of the interpreter `cpp-siemens` are not collected. Its sdist job checks that the sdist carries the
reader's files and builds a wheel from it with no download. It publishes nothing.

### 3.1 The API (`test_api.py`)

#### `test_each_decoded_block_is_built_from_the_libraries`

**Checks:** For each fixture that the package reads, each decoded block has the duration and the
events of its row of `libraries.blocks`: the RF event's fields are those of `libraries.rf`
(except the fields that `decodeBlock` computes or adds), each gradient has the amplitude and the
delay of its event and is a trapezoid exactly when the event's wave shape is 0, and the ADC event
is that of `libraries.adc`.

**How:** The test (one case for each fixture with the verdict "read" in
`expected_digests.json`) decodes the blocks and compares them in the canonical form, where NaN
equals NaN.

**Assumptions:** The libraries are read from the reader's private members, so the test shows
that the extension reads the right members and converts them as the decoded blocks are
converted, not that the reader's reading is right.

#### `test_the_libraries_of_a_file`

**Checks:** The libraries of `valid_1_5_1.seq` have its version, its rasters, its definitions as
text and as numbers, an MD5 signature that matches, shapes of float32 values and an int64 block
table.

**How:** The test compares each with the values of the file.

**Assumptions:** One file.

#### `test_a_block_decodes_on_its_own_in_any_order`

**Checks:** Each block of `oracle/pulseq_epi_rs.seq` decoded on its own, in reverse order, is the
block that `decode` gives.

**How:** The test compares the canonical forms.

**Assumptions:** `decodeBlock` keeps no state from one block to the next in this file.

#### `test_gradients_at_decodes_the_blocks_that_it_needs`

**Checks:** `gradients_at` on a sequence with no decoded block gives the values that it gives
after `decode`.

**How:** The test samples `valid_1_5_1.seq` at the points of `canonical.sample_points` before and
after `decode`.

**Assumptions:** One file.

#### `test_gradients_at_refuses_a_nan_time_and_a_block_that_does_not_exist`

**Checks:** `gradients_at` raises ValueError for a NaN time (`gradientsAt` would convert it to an
int, which is undefined behaviour) and for arrays of different lengths, and IndexError for a
block index outside the sequence; it gives an array (0, 3) for no point.

**How:** The test calls it with each.

**Assumptions:** None.

#### `test_a_block_that_decodeblock_rejects_raises_rejected`

**Checks:** For `valid_arbitrary_gradient_4us_raster.seq`, which `load` reads and whose block 0
`decodeBlock` rejects (an arbitrary gradient on a raster other than 10 us), `decode_block`,
`decode` and `gradients_at` raise `Rejected`, not `UndefinedBehaviour`, with the reader's message.

**How:** The test calls each.

**Assumptions:** One file.

#### `test_a_rejection_of_load_carries_the_reader_s_messages`

**Checks:** The `Rejected` of `bad_version_missing.seq` carries what the reader printed.

**How:** The test looks for `[VERSION]` in its `messages`.

**Assumptions:** None.

#### `test_a_file_whose_messages_are_not_utf_8_loads`

**Checks:** `load` returns a `Sequence` for a file that the reader loads and whose messages have
a byte that is not UTF-8, and its `messages` have that byte as its escape `\xb5`.

**How:** The test changes the name of the unknown extension of `valid_1_5_1.seq` to
`UNKN\xb5WN`, in the bytes of the file. The reader quotes that line in a warning
(cpp:1248).

**Assumptions:** One byte, 0xB5, in one message of `load`.

#### `test_a_rejection_whose_messages_are_not_utf_8_keeps_its_class_and_its_code`

**Checks:** For a file that `load` rejects with a byte that is not UTF-8 in its messages, `load`
raises `Rejected` with the byte escaped (`\xNN`) in its `messages`.

**How:** The test changes the ADC row `1 8 25000 ...` of `valid_1_5_1.seq` to `1 \xb5x 25000 ...`
in the bytes of the file. The reader fails to decode the row and quotes it (cpp:1150). The codes
that `read_seqfile` gives for it are checked by
`test_a_rejection_whose_messages_are_not_utf_8_has_the_code_of_the_ascii_row` (section 3.9),
which needs pulseq-analysis.

**Assumptions:** One row of one section.

#### `test_load_reads_the_bytes_of_a_file`

**Checks:** `load` of the bytes of a file gives what `load` of its path gives.

**How:** The test compares the canonical forms of both.

**Assumptions:** None.

#### `test_a_binary_file_and_a_folder_are_not_supported`

**Checks:** `load` raises `NotSupported` for the bytes of a binary Pulseq file and for a folder.

**How:** The test calls it with each.

**Assumptions:** The binary file is only its 8 bytes of magic and zeros.

#### `test_a_version_outside_1_4_to_1_5_is_refused_before_the_reader_loads_the_file`

**Checks:** For versions 1.3.1, 1.2.0, 1.6.0, 1.4.-1, a repeated field whose last value is 1.3,
and a revision that `sscanf` wraps, `load` raises `NotSupported`, and `ExternalSequence::load`
does not run. For a file older than 1.4.0, `load` would call `GetBlock` itself (cpp:1656-1663),
before any check.

**How:** The test (one case for each version) replaces the `[VERSION]` lines of
`valid_1_5_1.seq` and replaces the extension's `Reader` with one whose `load` fails the test.

**Assumptions:** None.

#### `test_the_version_gate_reads_the_version_as_load_does`

**Checks:** For [VERSION] sections that the reader reads in unusual ways (no revision, a comment,
a tab, `5x`, major 0 and minor 1004, a major that `sscanf` wraps to 1), the version gate gives
the major, minor and revision that `load` holds.

**How:** The test (one case for each) compares `Reader.read_version` with the libraries after
`Reader.load`.

**Assumptions:** The gate and `load` run the same code (the reader's `buildFileIndex`,
`skipComments` and `sscanf`), so the cases show the copy of the loop of cpp:878-909, not every
possible text.

#### `test_the_version_gate_reads_each_fixture_as_load_does`

**Checks:** For each fixture, where the gate finds a supported version and `load` reads the
file, `load` holds the same version; where the gate finds no version, `load` rejects the file.

**How:** The test (one case for each fixture) compares the two. It does not run `load` on a
version outside 1.4.0-1.5.x.

**Assumptions:** None.

#### `test_oversampling_keeps_the_samples_of_its_mode`

**Checks:** For an oversampled arbitrary gradient (time shape -1) of 7 samples, `load` keeps the
samples at the even positions in the mode "center" (the default), those at the odd positions in
"edge", and all of them in "preserve"; for 4 samples, 2, 1 and 4. `Sequence.oversampling` is the
mode, and `OVERSAMPLING` lists the three.

**How:** The test writes a file with one such gradient and decodes its block in each mode.

**Assumptions:** One gradient, with samples that tell the positions apart.

#### `test_an_oversampling_mode_that_is_not_one_of_the_three_raises_value_error`

**Checks:** `load` raises ValueError for a mode that is not one of `OVERSAMPLING` (also another
case, an empty text or None), and so does the extension's `Reader`.

**How:** The test calls each.

**Assumptions:** None.

#### `test_an_edge_gradient_with_no_sample_leaves_no_value_from_the_sample_before`

**Checks:** In the mode "edge", an oversampled gradient of 1 or 2 samples has none, and
`gradientsAt` returns early for it at its delay (cpp:3673-3677), after the channels before it and
before the channels after it. The values of the channels after it are 0, as the driver gives for
a line of its own (a new vector for each line), not the values of the time before in the same
call. The same file gives the same Y in the other modes, and in the driver.

**How:** The test samples a block with X oversampled and Y a trapezoid at 50 us (Y on its
plateau), 0 us (X's delay), 50 us and 0 us in one call. Without the fix, the extension keeps the
vector from one time to the next, and the Y at 0 us is 1e6. It compares with the driver where the
driver exists.

**Assumptions:** Two sizes (1 and 2 samples), one delay, one channel after the gradient.

#### `test_a_sequence_survives_pickle_and_copy`

**Checks:** In each mode, a pickle round trip of a `Sequence` (after a block is decoded) gives a
sequence with the same mode, messages, block table, decoded blocks and `gradients_at` values;
`copy.copy` and `copy.deepcopy` return the same object, also inside a dict.

**How:** The test pickles `valid_1_5_1.seq` and compares the canonical forms.

**Assumptions:** One file. A pickle carries the bytes of the file, and loading it reads and checks
the file again.

#### `test_first_rejected_block_is_the_first_block_that_decodeblock_rejects`

**Checks:** `first_rejected_block` gives None for `valid_1_5_1.seq`, and 0 for a file whose block
0 `decodeBlock` rejects (a gradient raster of 4 us) with the reader's message in
`rejection_messages`. For a file with two such blocks it gives the first and keeps the message of
that block only. It keeps no block: `gradients_at` still decodes and rejects block 0.

**How:** The test calls it on the three files.

**Assumptions:** The comparison with the driver's first mode is in `test_driver_parity.py`.

#### `test_block_rotations_are_the_quaternions_that_getblock_attaches`

**Checks:** `block_rotations()` of `koma_v1.5_rotation_radial_tiny.seq` gives blocks 0 to 4 (int64)
with the quaternions of rotations 1, 2, 3, 2 and 1 of the libraries, the same as each decoded
block's `rotation`, of norm 1. The result is a copy.

**How:** The test compares with `libraries.rotations` by the file's extension lists, and changes a
result.

**Assumptions:** None.

#### `test_block_rotations_of_a_file_with_no_rotation_are_empty`

**Checks:** For `valid_1_5_0.seq`, `block_rotations()` gives arrays of shape (0,) and (0, 4).

**How:** The test calls it.

**Assumptions:** None.

#### `test_a_block_with_two_rotations_has_the_first`

**Checks:** A block whose extension list has two rotations gets the first, as `GetBlock` does.

**How:** The test links the list entry of block 1 of the radial file to the entry of rotation 3,
and reads the bytes.

**Assumptions:** None.

#### `test_rotated_gradients_are_the_reader_s_turned_by_each_block_s_quaternion`

**Checks:** `gradients_at(..., rotated=True)` of the radial file equals the reader's values times
the matrix of the active rotation of each block's quaternion, to 1e-9 of the largest value; it keeps
the length of each vector, changes nothing for the identity, turns x into y at 90 degrees, and
leaves the reader's own values unchanged.

**How:** The test samples each block every 10 us and computes the matrices in numpy.

**Assumptions:** The convention (q0 the scalar part, the active rotation) is that of
`rotate_vec3_by_quat` with `c = +1`; pulseq-analysis's MATLAB test checks it against `mr.rotate3D`.

#### `test_rotated_gradients_turn_only_the_blocks_with_a_rotation`

**Checks:** In `valid_1_5_1.seq`, where some blocks have a rotation, `rotated=True` changes nothing
in the other blocks and turns each rotated block by its matrix.

**How:** The test samples the file at the points of `sample_points`.

**Assumptions:** None.

#### `test_rotated_gradients_of_a_file_with_no_rotation_are_the_reader_s`

**Checks:** For `valid_1_5_0.seq`, `rotated=True` gives the reader's values exactly.

**How:** The test samples the file at the points of `sample_points`.

**Assumptions:** None.

#### `test_rotate_vec3_by_quat_is_the_rotation_of_rotated_gradients`

**Checks:** `rotate_vec3_by_quat` of each block's quaternion and the reader's logical values is
`gradients_at(..., rotated=True)` bit for bit; it takes no row, and raises `ValueError` for
quaternions and vectors of different lengths.

**How:** `koma_v1.5_rotation_radial_tiny.seq`, every block sampled every 10 us.

**Assumptions:** None.

#### `test_block_soft_delays_are_those_that_getblock_attaches`

**Checks:** In `tests/session/scanner_session.seq` the blocks with a soft delay are 1, 6 and 7,
with the numeric IDs, offsets (int, us), factors and hints of the file. In
`valid_soft_delay_fraction.seq` the row `1 0 -100.5 1 TE` is the offset -100, the factor 0.5 and
the hint `1 TE` in block 7, as `load` misreads it (D2.16 of pulseq-analysis). `valid_1_4_0.seq` has
none.

**How:** The test calls `block_soft_delays` on the three files.

**Assumptions:** None.

#### `test_block_label_sets_are_the_labels_that_decodelabel_knows`

**Checks:** The LABELSET events of `tests/session/scanner_session.seq` are NOROT 1 (block 3), NOROT
0 (block 4) and NOSCL 1 (block 5): the reader leaves out the two `NOSLC` rows.

**How:** The test calls `block_label_sets`.

**Assumptions:** None.

#### `test_the_soft_delay_hook_sets_the_duration_and_the_end_of_gradients_at`

**Checks:** `block_durations_ru` with -1 everywhere is the stored durations; with 40 for block 0
and 90 for block 1 it is the reader's `GetDuration_ru` after `setActualSoftDelay_ru`. `gradients_at`
with `actual_ru` is 0 at 420 us in block 0 (cut at 400 us), where the next call without it is not,
and gives the flat top at 300 us. A wrong length raises `ValueError` in both.

**How:** `tests/session/scanner_session.seq`.

**Assumptions:** None.

### 3.2 The checks of undefined behaviour (`test_checks.py`)

The paths of `GetBlock` and `decodeBlock` where the reader reads a file that looks like a case of
section 5.3. Where `pulseq-cpp-oracle-sanitized` is on the PATH, the tests that write a file also
check its verdict.

#### `test_a_run_with_a_count_below_minus_one_writes_nothing`

**Checks:** A run whose count is -2 or -3 (`rep` 0 or -1) writes no sample, so its decompression
is not undefined behaviour; a value after it writes before the buffer, which is.

**How:** The test calls `_decompression` on stored values.

**Assumptions:** None.

#### `test_a_decompression_that_ends_before_num_samples_does_not_write_every_sample`

**Checks:** `_writes_every_sample` says whether `decompressShape` (cpp:2200-2247) writes each of
the `num_samples` values of a shape: it does for an uncompressed shape (memcpy, cpp:2202-2205)
and for runs and literals that end at `num_samples`, and it does not for a run of count -2 (0
repeats), with or without a literal after it, or for runs that end before `num_samples`.

**How:** The test calls `_writes_every_sample` on stored values, each of whose decompressions is
"ok" (`_decompression`).

**Assumptions:** None.

#### `test_the_tolerance_of_a_count_is_computed_in_float`

**Checks:** The test of `fabs(count + 2 - rep) > 1e-6` (cpp:2219) is computed in float: a count of
1 + 2^-23 decompresses, a count of 0.5 is a clean rejection.

**How:** The test calls `_decompression`.

**Assumptions:** The reader's float arithmetic is IEEE single precision with no extended
precision (SSE on x86_64, arm64).

#### `test_a_count_whose_sum_overflows_an_int_is_undefined_behaviour`

**Checks:** A count that makes `countUnpack + rep` overflow an `int`, a NaN count and a count past
the range of an `int` are undefined behaviour.

**How:** The test calls `_decompression`.

**Assumptions:** None.

#### `test_the_resampling_jumps_over_the_cells_where_it_stays`

**Checks:** The simulation of the resampling of an RF pulse (cpp:2032-2047) with about 2^31 cells
ends in less than a second, with no case for times that end at the last cell and with
`ub.rf-time-overrun` for times that end before it.

**How:** The test calls `_resampling` and times it.

**Assumptions:** One second is far above the few steps that the jumps take.

#### `test_the_resampling_reads_past_the_times_at_the_cell_centres`

**Checks:** Times at the cell centres of a pulse of 4 samples (D5.8, as MATLAB writes short
pulses) read past the times; times at the cell ends do not.

**How:** The test calls `_resampling`.

**Assumptions:** None.

#### `test_a_nan_time_stops_the_resampling`

**Checks:** A NaN time never moves the index of the resampling on, so the reads stay in the
samples.

**How:** The test calls `_resampling`.

**Assumptions:** None.

#### `test_a_regular_time_shape_is_not_decompressed`

**Checks:** An RF time shape of 3 stored values with `num_samples` 100, 0 or -1 is regular: the
package loads and decodes the file, and the sanitized oracle accepts it.

**How:** The test adds the shape to `valid_no_signature.seq` as its RF event's time shape.

**Assumptions:** None.

#### `test_a_negative_number_of_cells_is_a_clean_rejection`

**Checks:** An RF time shape whose last time is -5 (so `int(0.5 + t)` is -4) makes `decodeBlock`
throw: the package raises `Rejected`, not `UndefinedBehaviour`, and the sanitized oracle rejects
the file.

**How:** The test adds the shape to `valid_no_signature.seq` and decodes it.

**Assumptions:** The C++ library throws `std::length_error` for a negative size; the package's
extension turns an exception of the reader into a rejection.

#### `test_an_extended_trapezoid_of_one_point`

**Checks:** `ub.gradient-one-point` is raised exactly where `gradientsAt` reads past the times of
an extended trapezoid of one point (cpp:3639-3650): for a time of 4 (40 us) with a delay of 0,
90 or 100 us in a block of 100 us (`gradientsAt` takes a time equal to the block's duration),
and for a NaN amplitude. It is not raised for a time of 0 or below, a delay past the block's end,
or an amplitude of 0: then the package decodes the file and `gradients_at` samples the whole block.
Where the case is raised, the sanitized oracle's `--sample` at its block and time exits with 3.

**How:** The test (one case for each) changes `tests/fixtures/gradient_one_point.seq`.

**Assumptions:** `gradients_at` samples every 0.5 us; the cases with no rejection show that those
times are safe, with the C++ library of the devShell, whose hardening traps a read past a vector.

#### `test_the_checks_give_the_one_point_reads_that_the_stored_duration_hides`

**Checks:** On `tests/fixtures/gradient_one_point_after_block.seq` (the delay of the extended
trapezoid of one point at 200 us, past the 100 us of block 4), `_checks.undefined_behaviour`
gives no case and the interval of the read that the stored duration hides, `{4: [(200.0,
240.0)]}` (from the delay to the one point, 40 us after it). On `gradient_one_point.seq` it still
gives `ub.gradient-one-point` at block 4 and 0 us.

**How:** The test loads each file with the extension's `Reader` and calls the checks as `load`
does. The result has the fields `case` and `hidden_one_point`.

**Assumptions:** The intervals are a list of `(start_us, end_us)` for each block that has one;
`end_us` is not in the interval (`gradientsAt` gives the one point's value there).

#### `test_a_trap_row_of_the_same_id_replaces_a_gradients_row_of_shape_0`

**Checks:** A `[TRAP]` row with the ID of a `[GRADIENTS]` row of shape 0 replaces it (load reads
`[TRAP]` after `[GRADIENTS]`): the file reads, and the block plays the `[TRAP]` row's times. When
the two rows have the same amplitude and delay, the check cannot tell which the event holds, and
it raises `ub.gradient-shape-0`.

**How:** The test changes `valid_no_signature.seq` and decodes the block.

**Assumptions:** None.

#### `test_an_extended_trapezoid_keeps_the_values_of_the_shape_before_it`

**Checks:** The checks follow the buffer that `decodeExtTrapGradInBlock` reuses for each shape of
a block: an extended trapezoid of one point whose time shape writes no sample (a run of count
-2) has time 0 on the first channel of a block (the file reads), and the waveform 0.5 of the
channel before it, so 5 us, on the second, where `ub.gradient-one-point` is raised and the
sanitized oracle's `--sample` exits with 3.

**How:** The test changes `valid_no_signature.seq`, decodes the one-channel file and loads the
two-channel one.

**Assumptions:** The fuzzing found this (seed 3, file 17010): a check that decompressed each shape
into a new buffer let the second file through.

#### `test_a_gradients_row_of_shape_0_that_no_block_uses_reads`

**Checks:** A `[GRADIENTS]` row of shape 0 that no block uses is not a case: the file reads.

**How:** The test adds such a row to `valid_no_signature.seq`.

**Assumptions:** None.

### 3.3 The digests of the driver's output (`test_digests.py`)

#### `test_each_fixture_has_a_digest`

**Checks:** `tests/expected_digests.json` names each fixture of `tests/seqfiles` and of the
package's `tests/fixtures`, and no other file.

**How:** The test compares the names.

**Assumptions:** `scripts/make_digests.py` must run again when a fixture is added or changes.

#### `test_the_package_matches_the_digest_of_the_driver`

**Checks:** For each fixture and each sampling mode of oversampled gradients, the package's
verdict is the one of `expected_digests.json`, and for a file that it reads, the SHA-256 of the
canonical form of its decoded blocks and of `gradients_at` at `canonical.sample_points` is the
digest of the driver's `--dump` and `--sample` in that mode (`--oversampling`).

**How:** The test (one case for each fixture and mode) computes the digest; `make_digests.py`
computed the expected ones from the driver of the devShell (built with the package's flags), and
stopped where the two differ. The digests of the mode "center" are those of before the other
modes were added.

**Assumptions:**

- The digest counts one NaN for all: MSVC's NaN for `nan` in a file has other bits.
- The sample points are about 400 times in each block; values between them are not compared.

### 3.4 The driver of the C++ oracle (`test_driver_parity.py`)

#### `test_the_package_gives_what_the_driver_gives`

**Checks:** For each fixture, in each sampling mode of oversampled gradients (the driver's
`--oversampling`): where the package reads the file, `pulseq-cpp-oracle --dump` gives
the same dump and `--sample` the same values, bit for bit; where the package rejects it, the
driver rejects it too; where the package finds undefined behaviour, `pulseq-cpp-oracle-sanitized`
exits with 3 or does not end (D5.4). For `ub.gradient-one-point` the sanitized driver runs in its
`--sample` mode at the case's block and time; `ub.gradient-shape-0` is skipped (indeterminate
values, which no sanitizer sees).

**How:** The test (one case for each fixture and mode) runs the drivers and compares the canonical
forms. It skips a file outside the package's scope (Q1), a mode other than "center" for a file
with no oversampled gradient in a block, and the cycle of an extension list (it needs the
driver's whole timeout) in the modes other than "center". The module skips without the driver.

**Assumptions:** The drivers are built from the same commit with `-fsigned-char
-ffp-contract=off` (flake.nix), as the package.

#### `test_first_rejected_block_agrees_with_the_driver_s_first_mode`

**Checks:** For each fixture that `load` reads, in each sampling mode: `first_rejected_block` is
None exactly when the driver's first mode (`pulseq-cpp-oracle FILE`) accepts the file; otherwise
it is the index of the first block that the driver names ("decodeBlock returned false for block
N") and the first block for which `decode_block` raises `Rejected`, and `rejection_messages` has
the message of that block. It is "" for None.

**How:** The test (one case for each fixture and mode) runs the driver and `decode_block` of each
block.

**Assumptions:** Two fixtures are files that `load` reads and `decodeBlock` rejects
(`valid_arbitrary_gradient_4us_raster.seq`, `bad_definitions_raster_invalid.seq`); the others
agree on None. A file that `load` rejects is skipped (the test above covers it).

#### `test_the_driver_option_sets_the_sampling_mode`

**Checks:** `--oversampling=center` gives the dump of a call with no option; on `koma_v1.5_spiral.seq`
the oversampled gradient has 2112 samples in the mode "center", 2111 in "edge" and 4223 in
"preserve"; another value of the option exits with 2; with one argument, the option is a file name
(exit status 1, not a mode).

**How:** The test calls the driver.

**Assumptions:** One file.

### 3.5 The reader's shared state (`test_shared_state.py`)

#### `test_the_two_files_give_the_same_gradients`

**Checks:** `valid_1_5_1.seq` and the same file with a block raster of 1 us (each duration times
10) give the same gradients.

**How:** The test samples both at the points of `canonical.sample_points`.

**Assumptions:** None.

#### `test_a_sequence_samples_with_its_own_raster_after_another_load`

**Checks:** A sequence sampled after another file with another block raster has loaded keeps its
values: the extension sets `SeqBlock::s_blockDurationRaster` for each call.

**How:** The test samples, loads the other file, and samples again.

**Assumptions:** None.

#### `test_loads_and_samples_in_threads_give_the_values_of_one_thread`

**Checks:** Three files, two of them with different rasters, loaded and sampled in 6 threads, 12
times each, give the values of one thread.

**How:** The test compares each thread's dumps and samples with those of one thread.

**Assumptions:** The threads interleave as the scheduler decides; the test shows no race on this
run, not that there is none.

#### `test_each_rejection_of_decode_block_has_the_messages_of_its_own_block`

**Checks:** Two threads that share one `Sequence` and call `decode_block` on two blocks that
`decodeBlock` rejects each get `Rejected` with the messages of their own block.

**How:** The file is `valid_1_5_1.seq` with time shape 6 (5 samples) on the gradients 2 and 4,
whose wave shapes have 10, so `decodeBlock` rejects blocks 1 and 3 (play order from 0). After a
`threading.Barrier`, one thread calls `decode_block(1)` 2000 times and the other
`decode_block(3)` 2000 times. Each `Rejected.messages` must have exactly one line
`decodeBlock returned false for block <n>`, for the block of its own call.

**Assumptions:** The threads interleave as the scheduler decides; a pass shows no mixed messages
on this run, not that there are none.

#### `test_gradients_at_and_first_rejected_block_have_the_messages_of_their_own_block`

**Checks:** With two threads on one `Sequence`, each `Rejected` of `gradients_at` has the messages
of its own block, and after each call of `first_rejected_block` `rejection_messages` has the
messages of the block that the call returns.

**How:** The file of the test above. After a `threading.Barrier`, one thread calls
`gradients_at([3], [0.0])` 2000 times, and the other calls `first_rejected_block()` 2000 times.
Each `Rejected.messages` must name block 3 alone. Each call of `first_rejected_block` must return
1, and `rejection_messages`, read by the same thread just after the call, must name block 1 alone.

**Assumptions:** Only one thread calls `first_rejected_block`, so no other call sets
`rejection_messages` between the call and the read. The threads interleave as the scheduler
decides, as in the test above.

#### `test_the_c_library_of_the_process_reads_numbers_by_its_locale`

**Checks:** With a locale with a decimal comma, `strtod` of the process reads "0.5" as 0: the
hazard that the extension guards against is real on this machine.

**How:** The test calls `strtod` through ctypes. It skips on Windows and where no such locale is
installed (the Linux images of the wheels).

**Assumptions:** `strtod` reads as `sscanf`'s `%f` does.

#### `test_the_reader_reads_in_the_c_locale_whatever_the_process_locale`

**Checks:** With a process locale with a decimal comma, the package reads `valid_1_5_1.seq` as in
the "C" locale.

**How:** The test sets `LC_NUMERIC` and compares the dumps. It skips where no such locale is
installed.

**Assumptions:** The global C++ locale is not changed (it is outside the extension's guard).

### 3.6 The cases of undefined behaviour (`test_undefined_behaviour.py`)

#### `test_a_case_of_undefined_behaviour_is_rejected_with_its_code`

**Checks:** Each fixture of a case of section 5.3 raises `UndefinedBehaviour` with its code and
its entry: D5.1 (`undefined/version_last.seq` and others) as `ub.shape-missing`, D5.3, D5.4, D5.5 (a
shape longer than `num_samples`, and a repeated value with no count), D5.6, D5.7 and D5.8, and
the two cases that the fuzzing found: `ub.gradient-one-point` (`gradient_one_point.seq`) and
`ub.gradient-shape-0` (`gradient_shape_0.seq`).

**How:** The test (one case for each fixture) loads the file.

**Assumptions:** `ub.rf-time-range` and `ub.gradient-time-range` have no fixture; the fuzzing
reaches them (`test_fuzz.py`).

#### `test_the_process_reads_a_valid_file_after_every_case`

**Checks:** After each case is rejected, the process reads `valid_1_5_1.seq` as before.

**How:** The test compares the dumps before and after.

**Assumptions:** None.

#### `test_the_extension_refuses_to_decode_a_file_that_is_not_checked`

**Checks:** The extension's `decode_block` and `ensure_decoded` refuse to run before the file is
marked checked.

**How:** The test calls them on a `Reader` that has only loaded a file.

**Assumptions:** None.

#### `test_a_soft_delay_that_reaches_a_hidden_one_point_read_raises`

**Checks:** On `tests/fixtures/gradient_one_point_after_block.seq`, which `load` reads, `gradients_at`
of block 4 at 205 us with an `actual_ru` of 100 for block 4 (1000 us, so the block reaches the
delay of 200 us) and -1 for the others raises `UndefinedBehaviour` with the code
`ub.gradient-one-point`, block 4 and time 205.0, and the process ends with 0. Without the check,
`gradientsAt` reads past the times of the extended trapezoid of one point there; on macOS in the
devShell the process then ends with SIGTRAP (the hardened C++ library traps the read).

**How:** The test runs `load` and `gradients_at` in a process of its own (`sys.executable -c`),
which writes the result as JSON, and asserts on its exit status and its output.

**Assumptions:** None.

#### `test_a_time_outside_the_hidden_read_gives_the_value_of_the_reader`

**Checks:** With the same `actual_ru`, the times 100 and 199 us (before the delay), 240 us (the
one point: 200 000 Hz/m) and 250 and 900 us (after it, inside the 1000 us of the block) give the
values of the reader, with no exception: the check refuses only the times of the read. Where
`pulseq-cpp-oracle-sanitized` is on the PATH, its `--sample` with the soft delay as the third
field of each line exits with 0 and gives the same values.

**How:** As above, in a process of its own; the oracle reads the same times.

**Assumptions:** None.

#### `test_a_soft_delay_that_ends_before_the_hidden_read_gives_0`

**Checks:** An `actual_ru` of 10 for block 4 (100 us, its stored duration) or of 15 (150 us,
longer than stored but before the delay of 200 us) gives 0 at 205 us, with no exception: a soft
delay that does not reach the delay is not refused.

**How:** As above (one case for each value).

**Assumptions:** None.

### 3.7 The fuzzing of the checks (`test_fuzz.py`)

`tests/seqfuzz.py` generates `.seq` files from the grammar of the format, each a function of a
seed and an index: a random valid file of version 1.4 or 1.5, then up to three of 26 mutations
(the shapes of section 5.3 and their neighbours, values at the edges of their types, sections,
IDs, definitions and versions), and for one file in eight a change to its text. Each file also
gets one of the three sampling modes of oversampled gradients, from its seed and index, and
both readers read it in that mode. The generator makes oversampled gradients often and of any
size, 1 and 2 samples included (none of them is kept in the mode "edge"). Each file is read
by the package in a process of its own (`tests/fuzz_worker.py`, which decodes every block and
samples `gradients_at`, at the stored durations and again with an `actual_ru` that makes each
sampled block last past the end of its last gradient event) and by `pulseq-cpp-oracle-sanitized`, with ASan's largest allocation set
to 256 MB so that the growth of D5.4 ends quickly. The package's `README.md` ("Fuzzing") gives the
four tiers. `scripts/check` runs the first: the regression corpus (`tests/fuzz_corpus/`) and 200
seeded files. `.github/workflows/pulseq-cpp-siemens-fuzz.yml` runs the second on a pull request
or a push to `main` that changes the package, `tests/cpp_oracle/`, `flake.nix` or `flake.lock`:
the module's `fuzz` tests with `PULSEQ_CPP_SIEMENS_FUZZ_COUNT=3000`. Its weekly job (30 000 new
files of the date's seed) and the run before each release are not tests: they block nothing.

#### `test_a_file_is_the_same_for_the_same_seed_and_index`

**Checks:** The generator gives the same bytes for the same seed and index, and others for
another index or seed.

**How:** The test generates them twice.

**Assumptions:** `random.Random` seeded with a string gives the same numbers on each platform and
Python version.

#### `test_a_file_has_a_sampling_mode_from_its_seed_and_index`

**Checks:** `oversampling_mode(seed, index)` gives the same mode for the same two numbers, all
three modes occur among 300 indices (each more than 60 times), another seed gives other modes,
and the fuzzing's list of modes is `OVERSAMPLING` of the package.

**How:** The test calls it twice for each index.

**Assumptions:** `random.Random` seeded with a string gives the same numbers on each platform
and Python version.

#### `test_a_file_with_no_mutation_reads`

**Checks:** The generator's files with no mutation (among its first 400) load and decode.

**How:** The test reads each with the package.

**Assumptions:** None.

#### `test_the_corpus_has_a_file_of_each_code`

**Checks:** `tests/fuzz_corpus/expected.json` names each file of the corpus and no other, and the
corpus has a file of each of the 11 codes.

**How:** The test compares the names and the codes of the verdicts.

**Assumptions:** None.

#### `test_the_corpus_agrees_with_the_sanitized_oracle`

**Checks:** On each file of the regression corpus, in each of the three sampling modes, no file
fails (as on the seeded files below), and the package's verdict is the one of `expected.json`
(the checks do not depend on the mode).

**How:** `seqfuzz.run_files` runs both readers on each file in each mode and compares.

**Assumptions:** The corpus is the smallest file of each code in the full seeded set, the files
that once failed the fuzzing (an extended trapezoid of one point, the buffer that the reader
reuses for extended trapezoids, three `[GRADIENTS]` rows of shape 0, a write past the size of a
vector inside its capacity that the Linux oracle missed before `_GLIBCXX_SANITIZE_VECTOR`), and
six valid files (one of them has oversampled gradients of 1 to 4 samples, for the stale values of
`gradientsAt` in the mode "edge", and one has bytes that are not UTF-8 in the messages of the
reader). A new failure is added to it by hand.

#### `test_the_checks_agree_with_the_sanitized_oracle_on_the_seeded_files`

**Checks:** On the files 0 to COUNT-1 of seed 20261012 (200 in `scripts/check`, 3 000 in the
fuzzing workflow), no file fails: the oracle flags no file
(undefined behaviour, no end or a crash) that the package decodes; the package's process neither
dies nor hangs; the checks raise no `UndefinedBehaviour` for a file that the oracle accepts; the
two give the same verdict; and where both read the file, `gradients_at` gives the bits of the
oracle's `--sample` at the same times, with the same soft delays (the third field of a line of
`--sample`), which also runs `gradientsAt` under the sanitizers. A rejection
`ub.gradient-one-point` of a file that the oracle accepts is confirmed by the oracle's `--sample`
at the case's block and time, with the worker's soft delay where the case needs one, and a
rejection `ub.gradient-shape-0` by a reading of the file's text (`seqfuzz.known_cases`). The
mutation `gradient-one-point-after-block` puts the delay of an extended trapezoid of one point past
the end of each block that plays it, so that the seeded files have the case that only a soft
delay reaches.

**How:** `seqfuzz.run` runs the package and the oracle on each file in its sampling mode, in as
many threads as CPUs, and compares. The failing files are kept in a temporary folder that the
message names.

**Assumptions:**

- The sanitizers see only the paths that a file takes; indeterminate values (MemorySanitizer's
  domain) are seen only where they change the values of `gradientsAt`.
- The generator never makes the reader allocate more than 20 000 samples on a path that the
  checks let through, so the reader's behaviour with larger sizes is not fuzzed.
- "Memory" (an allocation above 256 MB in the oracle) passes when the package rejects the file.

#### `test_the_seeded_files_have_oversampled_gradients_of_each_size_in_each_mode`

**Checks:** In the full set of 3 000 files, the files that the package reads have, in each of the
three modes, at least 30 with an oversampled gradient that a block uses, of 1, of 2, of 3 and of
4 or more samples. So the sizes where the modes keep none, one or more samples are all reached
(none in the mode "edge" for 1 and 2). It skips on a smaller set.

**How:** The test loads each file in its mode and counts the sizes of the oversampled gradients
of its blocks. It needs no oracle.

**Assumptions:** The count is of files the package reads, not of files the oracle accepts.

#### `test_the_seeded_files_reach_each_case_of_undefined_behaviour`

**Checks:** In the full set of 3 000 files, each of the 11 codes of section 5.3 is among the
files that the oracle flags (or confirms as above) and the checks reject at least 10 times, so the
seeded set reaches every case. It skips on a smaller set (the 200 files of `scripts/check`).

**How:** The test counts the codes in the report of the seeded files.

**Assumptions:** None.

### 3.8 The interpreter `cpp-siemens` (`test_interpreter.py`)

`test_interpreter.py` tests the interpreter `cpp-siemens` (`pulseq_cpp_siemens.interpreter`), the
plugin of pulseq-analysis (P21 of `docs/plans/parser-redesign.md`): the C++ reader of the scanner
through `read_seqfile` and `synth.decode` of pulseq-analysis, which each test names (the default
interpreter of pulseq-analysis is `spec`). It needs pulseq-analysis (the group `analysis`) and is
not collected without it. It uses the fixtures and the helpers of the tests of pulseq-analysis
(`test_cpp_oracle`, `test_cpp_oracle_sanitized`; sections 2.20 and 2.25). The tests that compare with
the C++ oracle (`pulseq-cpp-oracle`) and its sanitized build (`pulseq-cpp-oracle-sanitized`) skip
when they are not on the PATH. The other tests of this package (sections 3.1 to 3.7) compare the
reader's values with the driver bit for bit; these tests check what the interpreter builds on it:
the verdict, the codes, the version gate, the model and the decoding.

#### `test_cpp_siemens_gives_the_verdict_of_the_oracle_on_each_fixture`

**Checks:** For each fixture of `tests/seqfiles` (the subfolders included), `cpp-siemens` reads
the file when the oracle accepts it, rejects it with a `ub.*` code when the sanitized oracle finds
undefined behaviour (exit status 3) or does not end, and rejects it with another code when the
oracle rejects it otherwise. The two fixtures of a version outside 1.4.0 to 1.5.x raise
`NotSupported`, whatever the oracle does (Q1 of `docs/plans/parser-redesign.md`). No fixture is
left out.

**How:** For each fixture (parametrized), the test runs the sanitized oracle, then the oracle, and
reads the file with `read_seqfile`.

**Assumptions:** The oracles are the reader at the pinned commit with the flags of the package
(`-fsigned-char -ffp-contract=off`). A crash of the plain oracle without undefined behaviour in the
sanitized one fails the test.

#### `test_each_fixture_has_its_rejection_code`

**Checks:** Each fixture gives its expected verdict: the code of `REJECTED` (for example
`gradient.raster` for `valid_arbitrary_gradient_4us_raster.seq` and
`valid_arbitrary_gradient_5us_raster.seq`, `section.extensions-last` for
`oracle/koma_v1.5_unknown_ext.seq`, `syntax.comment-row` for `bad_syntax_line_after_comment.seq` and
`valid_comment_in_shape.seq`, `definitions.skipped` for `valid_last_section_no_blank.seq`,
`ub.rf-time-overrun` for `valid_rf_time_shapes.seq` and `syntax.shape` for
`bad_syntax_shape_end.seq`), `NotSupported` for the two versions outside the range, and a model for every
other fixture. The codes are stable, so pulseq-checks and the tests can name a rejection.

**How:** For each fixture (parametrized), the test compares the codes of the `SeqFileError` with
the table. It needs no oracle.

**Assumptions:** The table was made from a run and checked against the oracle by the test above.

#### `test_the_fixtures_of_pulseq_cpp_siemens_are_rejected_with_their_code`

**Checks:** The three fixtures of `packages/pulseq-cpp-siemens/tests/fixtures` are rejected with the
code of their case of undefined behaviour: `ub.gradient-one-point`, `ub.gradient-shape-0` and
`ub.shape-decompression` (a repeated value with no count at the end of a shape), and `CODES` gives
each code the ID of its entry in `packages/pulseq-cpp-siemens/docs/specification.md`: D5.10, D5.2
and D5.5.

**How:** For each fixture (parametrized), the test reads it and compares the code and the ID.

**Assumptions:** The package's tests confirm each case with the sanitized oracle.

#### `test_each_code_of_a_rejection_has_a_file_that_gives_it`

**Checks:** For each code of a rejection by `load` or `decodeBlock` (`CODES`, except the fallback
`cpp.rejected` and the `ub.*` codes), a small file gives that code and only it, with the reader's
message, and the oracle rejects the file too: `version.invalid`, `version.missing`,
`definitions.raster-missing`, `definitions.raster-invalid` (`nan`), `definitions.skipped` (D2.2: a
last section with no blank line after it, so the reader skips `[DEFINITIONS]`),
`extension.required-unknown`, `section.extensions-last`, `blocks.missing`, `ref.unresolved`,
`syntax.row` (`100.5` in `[BLOCKS]`), `syntax.comment-row`, `syntax.shape`, `rotation.norm`,
`gradient.raster`, `shape.decompression` (a repeat count of 1.5), `shape.ext-trap-lengths` and
`cpp.exception` (an RF time shape that ends before 0).

**How:** For each code (parametrized), the test writes an edit of a small valid file, reads it,
and runs the oracle when it is on the PATH.

**Assumptions:** The classification of a rejection reads the reader's messages, which are fixed at
the pinned commit.

#### `test_every_code_is_given_by_a_file_or_is_the_fallback_or_a_case_of_undefined_behaviour`

**Checks:** Each code of `CODES` that is not a `ub.*` code is given by a file of the test above or
by a fixture, except `cpp.rejected`; and the `ub.*` codes are those of `pulseq_cpp_siemens.CODES`.

**How:** The test compares the sets.

**Assumptions:** None.

#### `test_a_rejection_quotes_the_line_of_the_row_that_does_not_decode`

**Checks:** For a `#` line in `[RF]`, the reason of the rejection has the section `RF`, the line
of the `#` line in the file, and the reader's message "failed to decode RF event".

**How:** The test reads the file of `syntax.comment-row` and looks up the line.

**Assumptions:** None.

#### `test_the_dwell_with_a_decimal_point_is_a_row_that_does_not_decode`

**Checks:** An ADC dwell time of `2500.0` is `syntax.row` in `[ADC]` (the reader reads the
dwell as an integer), and the same file with `2500` reads, with a dwell of 2.5 us.

**How:** The test reads both files.

**Assumptions:** The file ends with a blank line: with none, the reader skips the sections after
`[ADC]` (D2.2).

#### `test_a_version_outside_1_4_to_1_5_is_not_supported_before_the_reader_runs`

**Checks:** A file of version 1.3.1, 1.6.0 or 2.0.0 raises `NotSupported` (a
`NotImplementedError`), and so does a file whose `[VERSION]` has `minor 5` and then `minor 6`
(the "as written" reading takes the first row, 1.5.0; the reader the last, 1.6.0, so the gate of
`cpp-siemens` refuses it). Each file also has a cycle in an extension list, on which the
reader of a version before 1.4.0 does not end inside `load`: the test ends, so the gate runs
before the reader.

**How:** For each version (parametrized), the test writes the file and reads it.

**Assumptions:** None.

#### `test_a_binary_file_and_a_folder_are_not_supported`

**Checks:** A file that starts with the magic bytes of a binary Pulseq file, and a folder, raise
`NotSupported`.

**How:** The test writes the bytes and reads the file and its folder.

**Assumptions:** None.

#### `test_the_model_is_the_readers_libraries_in_the_units_of_the_model`

**Checks:** The model of `valid_1_5_1.seq` holds the reader's libraries: the version, the gradient
raster in s, the block IDs as positions from 1 (the reader keeps no ID), the durations and event
IDs of the blocks, the RF delay, centre and use, the trapezoids and the arbitrary gradients split
by shape ID 0, the dwell times, the stored shape values (float32), the signature, the required
extensions, the extension that the reader ignores in `skipped_extensions` (not in `type_ids`), and
the float32 value of an RF shim phase.

**How:** The test compares the model with `data.reading.libraries`.

**Assumptions:** None.

#### `test_a_1_4_rf_event_has_no_center_and_the_use_u`

**Checks:** The RF event of `valid_1_4_0.seq` has `center` NaN (the reader holds -1, D7.5) and
`use` `u`.

**How:** The test reads the fixture.

**Assumptions:** None.

#### `test_the_rotations_are_the_readers_normalized_quaternions`

**Checks:** A quaternion of norm 1.0005 (within the reader's 1e-3) in a 1.5.1 file is divided by its
norm in the model of `cpp-siemens`, and in the model of `spec` too (from 1.5.1, D2.18): both give q0 1.0.

**How:** The test writes a file with a rotation and reads it with both interpreters.

**Assumptions:** The file is 1.5.1: `spec` skips ROTATIONS in a file of an older version (D4.6).

#### `test_the_interpreter_is_a_name_or_an_object_and_the_result_records_it`

**Checks:** `read_seqfile` takes no interpreter (`spec`, the default), a name, or an object with its
settings, and `SequenceData.interpreter` records it (`str` names a setting that is not the default);
`spec` has no reading. Another name, such as `matlab`, raises `ValueError` ("no interpreter"), another value `TypeError`, and
an unknown oversampling mode `ValueError`.

**How:** The test reads `valid_1_5_1.seq` in each way.

**Assumptions:** None.

#### `test_the_oversampling_setting_changes_the_decoding_of_an_oversampled_gradient`

**Checks:** The oversampled gradient of `valid_1_5_1.seq` decodes to all its samples with
`oversampling="preserve"`, to the even samples ((n + 1) / 2) with `"center"`, and to the odd
samples ((n - 1) / 2) with `"edge"` (D6.1).

**How:** The test decodes the file in each mode with `synth.decode` and compares the samples of
the oversampled gradient.

**Assumptions:** pulseq-cpp-siemens's tests compare each mode with the driver.

#### `test_a_cpp_siemens_model_compares_and_survives_pickle_and_deepcopy`

**Checks:** Two reads of a file are equal (the reading is not compared), a read with another
setting is not, and a copy by `pickle` or `copy.deepcopy` is equal and gives the same
`gradients_at`. The reading cannot be set.

**How:** The test reads the fixture, copies the model, and samples a block.

**Assumptions:** `pickle` reads the file's bytes again (pulseq-cpp-siemens).

#### `test_the_rotation_setting_is_one_of_two_and_a_setting_that_an_interpreter_lacks_is_typeerror`

**Checks:** `CppSiemens().rotation` is `"reader"`, `ROTATION` (of `pulseq_cpp_siemens.interpreter`) is `("reader", "apply")`,
`str` names each setting that is not its default (one or both), and a read records the setting.
Another value raises `ValueError`; a setting that the interpreter does not have
(`Spec(rotation=...)`, `CppSiemens(rotate=...)`) raises `TypeError` (rule 8 of P20).

**How:** The test makes the objects and reads `koma_v1.5_rotation_radial_tiny.seq` with both
settings.

**Assumptions:** None.

#### `test_each_block_s_rotation_is_the_quaternion_that_the_reader_attaches`

**Checks:** `CppSiemensDecoding.rotations()` gives the blocks whose decoded block (`GetBlock`) has a
rotation, in play order, with the same quaternions, in both settings; each is one of the model's
normalized quaternions.

**How:** The test reads `koma_v1.5_rotation_radial_tiny.seq` and `valid_1_5_1.seq` (some blocks
with a rotation) in each setting, and compares `rotations()` with the `rotation` of each block of
`blocks()`.

**Assumptions:** pulseq-cpp-siemens's tests check the first of two rotations in a block.

#### `test_rotation_apply_rotates_the_gradients_of_each_block_that_has_a_rotation`

**Checks:** With `rotation="apply"`, `gradients_at` gives the reader's gradients of
`koma_v1.5_rotation_radial_tiny.seq` (all on x) turned by 0, 45, 90, 45 and 0 degrees about z in
blocks 1 to 5; `rotated=False` gives the reader's values, and the default setting with
`rotated=True` gives the same values as `"apply"`.

**How:** The test samples each block at four times in both settings and compares with
`(cos, sin, 0)` times the x values, to 1e-3 Hz/m (the quaternions have six digits).

**Assumptions:** None.

#### `test_the_rotation_record_and_the_warning_for_rotations_left_unapplied`

**Checks:** The record of `koma_v1.5_rotation_radial_tiny.seq` is 5 blocks with a rotation, 3 not
the identity, 0 rotated with `"reader"` and 5 with `"apply"`, with its text; `"reader"` gives a
`ScannerSettingWarning` for 3 blocks that names `rotation='apply'`, and `"apply"` none. A file with
no rotation, and one with a rotation that no block plays, record 0 blocks in both settings with no
warning (rule 8: `"apply"` is valid there). A file whose rotations are all the identity records 5
blocks, 0 not the identity, and no warning.

**How:** The test reads the fixtures, and a copy of the radial file with its two other quaternions
replaced by `1 0 0 0`.

**Assumptions:** None.

#### `test_the_decoding_emits_no_warning_for_rotations`

**Checks:** Decoding and sampling a file whose rotations the default leaves unapplied emits no
`ScannerSettingWarning`: the measurements emit it (task R14), not the decoding.

**How:** The test decodes the radial file with `recwarn`.

**Assumptions:** None.

#### `test_spec_rotates_the_gradients_as_cpp_siemens_with_rotation_apply`

**Checks:** On each fixture with a `ROTATIONS` section (`valid_*.seq` and `oracle/*.seq`) that both
interpreters read: from 1.5.1, `spec` gives the blocks with a rotation that the reader attaches, with
the same quaternions (to 1e-12), the same `rotation_record`, and the rotated gradients of
`CppSiemens(rotation="apply")` at 7 times inside each block, to 1e-6 of the largest value. In a file
older than 1.5.1 (`valid_1_5_0_extensions_of_1_5_1.seq`), `spec` has no rotation, `cpp-siemens`
rotates a block that is not the identity, and `spec`'s gradients are the reader's unrotated ones.

**How:** The test (one case for each file) samples both decodings at 5 % to 95 % of each block
duration, in 7 steps.

**Assumptions:** The tolerance covers the reader's float32 amplitudes (P6). A file that an
interpreter rejects is skipped (`valid_comment_in_shape.seq`, `valid_last_section_no_blank.seq`,
`valid_rf_time_shapes.seq`). The times avoid the block boundaries and are where the two decoders draw
the same lines in these files.

#### `test_synth_decode_gives_the_readers_decoding_or_the_spec_events`

**Checks:** `synth.decode` gives a `CppSiemensDecoding` for `cpp-siemens`, with the interpreter,
the number of blocks, each block in play order, and the reader's `gradients_at`; and a
`SpecDecoding` with the events for `spec`. `events.decode_rf` refuses the model of
`cpp-siemens` with `TypeError` that names `synth.decode`.

**How:** The test decodes `valid_1_5_1.seq` with both interpreters.

**Assumptions:** None.

#### `test_the_entry_point_gives_cpp_siemens_to_pulseq_analysis`

**Checks:** pulseq-analysis finds `cpp-siemens` through the entry-point group
`pulseq_analysis.interpreters` (P21): its name is in `seqfile.interpreter_names()`,
`seqfile.interpreter("cpp-siemens")` is `CppSiemens()`, `CppSiemens()` is a `seqfile.Plugin`, and
`synth.decode` of a model that it read gives a `synth.Decoding`.

**How:** The test calls the functions and reads `valid_1_5_1.seq` by the name.

**Assumptions:** The entry point is in the metadata of the installed distribution
pulseq-cpp-siemens, so a change to its `pyproject.toml` takes effect after the next install
(`scripts/check` reinstalls it).

#### `test_the_reader_imports_without_pulseq_analysis`

**Checks:** `import pulseq_cpp_siemens` imports no module of `pulseq_analysis`: only
`pulseq_cpp_siemens.interpreter` needs pulseq-analysis.

**How:** The test runs a Python process that imports the package and asserts that `sys.modules`
has no name that starts with `pulseq_analysis`.

**Assumptions:** The environment of the test has pulseq-analysis installed (the module is not
collected without it), so the test shows that the import does not use it, not that it is absent.
The wheel tests, where it is absent, do not collect this module.

#### `test_the_gradient_points_are_the_values_of_gradients_at`

**Checks:** For each gradient event of five files of `tests/seqfiles/oracle` (a trapezoid, a
time-shaped and a uniformly shaped gradient of 1.4, the radial file with rotations, and a spiral of
1.5), `CppSiemensDecoding.gradient_points` of the first block that plays it gives points whose
values, apart from the first and the last point and the points at or after the end of the block,
are the values of `gradients_at` (not rotated) at the times of the points, to a relative 1e-6 and
1e-3 Hz/m.

**How:** For each file, axis and gradient ID, the test takes the first block that plays it and
compares `gradients_at` at `delay + offsets` (in µs) with the values of the points.

**Assumptions:** The first and the last point of an event are not compared. The test asserts that it
compared at least one event in each file.

### 3.9 The interpreter `cpp-siemens` in pulseq-analysis (`test_interpreter_in_pulseq_analysis.py`)

`test_interpreter_in_pulseq_analysis.py` runs the checks of pulseq-analysis that take any
interpreter for `cpp-siemens`: the helpers `check_*` of `test_from_pypulseq.py` (section 2.28) and
`compare_rotated_gradients` of `test_matlab_oracle.py` (section 2.24), and tests what
pulseq-analysis gives for the model of a plugin. The interpreters are `"cpp-siemens"` and
`CppSiemens(oversampling="edge")`. Like `test_interpreter.py`, it needs pulseq-analysis and is not
collected without it; the MATLAB test skips as the tests of pulseq-analysis do, when
`pulseq-matlab-oracle` is not on the PATH.

#### `test_a_sequence_in_memory_reads_as_its_written_file_through_cpp_siemens`

**Checks:** For each sequence of `test_from_pypulseq.py` and each of the two interpreters,
`read_pypulseq(seq, interpreter)` equals `read_seqfile` of the file that `seq.write(path)` writes,
except `origin`, with the signature of the file (`check_reads_as_its_written_file`; the check of
`test_a_sequence_in_memory_reads_as_its_written_file`, section 2.28).

**How:** The test calls the helper for the sequence and the interpreter.

**Assumptions:** The `reading` is not compared by `==`; it is the reader's reading of the same
bytes.

#### `test_the_mixed_sequence_has_each_kind_of_event_through_cpp_siemens`

**Checks:** The model of `mixed_sequence` through each of the two interpreters has 10 blocks and
each kind of event (`check_the_mixed_sequence`; the check of
`test_the_mixed_sequence_has_each_kind_of_event`, section 2.28).

**How:** The test calls the helper for the interpreter.

**Assumptions:** The counts are those of pypulseq's writer at the version of `uv.lock`.

#### `test_a_rejection_of_cpp_siemens_names_the_sequence_not_the_temporary_file`

**Checks:** A sequence with an arbitrary gradient on a gradient raster of 4 µs raises, through
`cpp-siemens`, the `SeqFileError` of its written file (`gradient.raster`), whose `path` is
`from_pypulseq.SOURCE` and whose message names the sequence, not the temporary file
(`check_a_rejection`; the check of
`test_a_rejection_is_the_file_s_and_names_the_sequence_not_the_temporary_file`, section 2.28).

**How:** The test builds the sequence and calls the helper.

**Assumptions:** None.

#### `test_the_events_of_spec_refuse_a_model_of_cpp_siemens`

**Checks:** `decode_rf`, `decode_gradients` and `decode_adc` of `synth.events`, which decode the
model of `spec`, raise `TypeError` for the model of `cpp-siemens`, with a message that names
`synth.decode`.

**How:** The test reads `valid_1_5_1.seq` with `cpp-siemens` and checks the `TypeError` and its
message for the three functions.

**Assumptions:** None.

#### `test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq`

**Checks:** For each file with a `ROTATIONS` section, the rotated gradients of
`CppSiemens(rotation="apply")` (each block turned by its quaternion with the reader's
`rotate_vec3_by_quat`), in any version of the file, equal MATLAB's rotated polyline from
`waveforms_and_times` (`mr.rotate3D`) on each axis, to 1e-6 of the axis's largest value, as
`compare_rotated_gradients` says (section 2.24).

**How:** The test (one case for each file) reads the file with `cpp-siemens` and
`rotation="apply"`, and calls `compare_rotated_gradients` with the MATLAB case of the file.

**Assumptions:** The tolerance of 1e-6 covers the reader's float32 amplitudes (P6) against MATLAB's
float64. A file that `cpp-siemens` rejects (`valid_last_section_no_blank.seq`,
`definitions.skipped`, and `valid_rf_time_shapes.seq`, `ub.rf-time-overrun`) or that MATLAB cannot
read is skipped.

#### `test_a_rejection_whose_messages_are_not_utf_8_has_the_code_of_the_ascii_row`

**Checks:** `read_seqfile` with `cpp-siemens` gives the same codes for a row that the reader fails
to decode with a byte that is not UTF-8 as for the same row with an ASCII byte in its place.

**How:** The test changes the ADC row `1 8 25000 ...` of `valid_1_5_1.seq` to `1 \xb5x 25000 ...`
and to `1 x 25000 ...`, writes each file, and compares the codes of the two `SeqFileError`s. The
comparison is differential, so it does not depend on the text of the message.

**Assumptions:** One row of one section.

### 3.10 The measurements through `cpp-siemens` (`test_measurements_in_pulseq_analysis.py`)

`test_measurements_in_pulseq_analysis.py` has the tests of the measurements of pulseq-analysis
(`gradient_peaks`, `block_gradient_values`, `gradient_spectrum`, `pns_levels` and
`GradientSampler`) for the sequences that `spec` rejects, which the root tests loaded with
`cpp-siemens`: a gradient that ends above 0 before its block ends
(`gradient.nonzero-end-align`), a gradient that starts above 0 after a delay
(`gradient.nonzero-start-delay`), a delay off the gradient raster (`raster.gradient-delay`), and a
gradient raster of 4 µs with a block duration raster of 10 µs
(`definitions.raster-commensurate`). The root suite runs without the plugin, so these tests are
here. A test that was whole in sections 2.2, 2.5, 2.6, 2.8 and 2.10 moved with its entry, and keeps
its name and its values. A test that had cases for both interpreters is two tests of one name: the
root test keeps the cases that `spec` reads, and the test here has the others, with the same body
(a helper `check_*` of the root module, imported here). The module imports the helpers and the
cases of the root modules, as `test_interpreter_in_pulseq_analysis.py` does. Like
`test_interpreter.py`, it needs pulseq-analysis and is not collected without it. The tests of a
NaN of the file are here too (`bad_syntax_number.seq`, which `spec` rejects, `syntax.number`),
with the check of the root module `test_played.py` (section 2.3).

#### `test_junction_step_uses_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The step at a block junction is divided by the gradient raster that the file declares
(`GradientRasterTime`, `snap.data.rasters.gradient`), not by the 10 µs of the pypulseq `Opts` default.
`load` of the file and `load` of the sequence object that wrote it give the same value.

**How:** `raster_4us_sequence` builds two y extended trapezoids with a 4 µs gradient
raster: the slopes are 40 and 39.4 T/m/s and the junction step is 0.24 mT/m, so the
junction is 60 T/m/s with 4 µs (24 T/m/s with 10 µs). The test writes the sequence to
a file in `tmp_path`. For `load(path, "cpp-siemens")` and `load(seq, "cpp-siemens")`, it checks that
the gradient raster of the data is 4 µs and that the y slew is 60 T/m/s times `GAMMA_1H` (Hz/m/s),
credited to the second block, at the junction (0.8 ms).

**Assumptions:** `spec` rejects a gradient raster of 4 µs with a block duration raster of 10 µs (it is
neither a multiple nor a divisor of it), so the test uses `cpp-siemens`. The file stores the amplitudes
with fewer digits than the sequence object, so the comparison has a relative tolerance of 1e-4.

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
`A / DT` (3.19e9 Hz/m/s). Only the one raster time counts it. The snapshot is `load(seq, "cpp-siemens")`. Then the oracle (on
the sequence object), the whole file and the window `(0.0, end_s)` of `gradient_peaks` give `A / DT` credited to block 2 at
`end_s - early`. For the other values they give 1e9 Hz/m/s in block 1. The window
`(0.0, end_s - 0.5 * TIME_TOLERANCE)`, in the oracle and in `gradient_peaks`, gives the same
slew and block: for an `early` of 0.9 of `TIME_TOLERANCE` the step is before the end of this
window, so only the rule `t < end_s - TIME_TOLERANCE` leaves it out. In every case the slew of
block 2 in `block_gradient_values` is `A / DT` (counted) or `A / 100 µs` (not counted).

**Assumptions:** `spec` rejects an extended trapezoid that ends at `A` before the end of its block (`gradient.nonzero-end-align`),
and a last point that is off the raster, so the test uses `cpp-siemens`. pypulseq accepts a last time off
the gradient raster by 1e-9 s or less, and no more, so a value of `early` between `TIME_TOLERANCE` and one raster time cannot be built with
`make_extended_trapezoid`. The test does not cover a value between them. The window ends at
`end_s` of the index of the package, and the oracle uses the end of its last block: the two are
the same number for this sequence. The 1e-6 relative tolerance of the comparison with the oracle on the
sequence object covers the rounding of the writer.

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
`spec` rejects the first value that is not 0 after a delay (`gradient.nonzero-start-delay`), so the test uses `cpp-siemens`, which
plays it.

#### `test_window_that_cuts_the_ramp_from_zero_of_a_delayed_event_has_the_part_inside_it`

**Checks:** For the sequence of the test above, a window that starts in the middle of the ramp
from 0 has the second half of it. A window that ends where the ramp starts does not have the
ramp.

**How:** The ramp is from 395 µs to 400 µs. The window from 397.5 µs to the end must have the
same slew, `slew_block` equal to block 2, and `slew_time_s` equal to the window start (the
start of the cut). The window from 0 to 395 µs must have the slope of the ramps of block 1 (0.3
of the largest amplitude in 100 µs) and block 1.

**Assumptions:** The ramp is steeper than the slope of the ramps of block 1, which the test
checks. `spec` rejects the sequence (`gradient.nonzero-start-delay`), so the test uses `cpp-siemens`. The slope of the ramps of
block 1 has a relative tolerance of 1e-5 (the writer's rounding of the amplitude).

#### `test_matches_oracle_on_synthetic_sequences`

**Checks:** `gradient_peaks` matches the oracle of the gradient waveform
(`tests/oracles/waveform.py`, section 2.15) on the whole file and on windows, for each of
`tests/synthetic.py`'s sequences (parametrized: `spin_echo_sequence`, `gre_sequence`,
`empty_sequence`, `arbitrary_gradient_sequence`, `border_sequence`, `raster_4us_sequence`).
`border_sequence` and `raster_4us_sequence` have a gradient that is not 0 at a block junction.

**How:** The sequences are read with `load(seq, "cpp-siemens")`, and the oracle reads the gradients that
the snapshot plays (`sequence_of(snap)`). The windows are up to 12 windows from `_oracle_windows` (seed 20261007) and one window
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
- `spec` rejects `raster_4us_sequence` (a gradient raster of 4 µs with a block duration raster of 10 µs),
  so the test reads all the sequences with `cpp-siemens`. The oracle reads the same played gradients
  as the package (`sequence_of(snap)`), so the comparison has no rounding of the writer. The scale of
  the tolerance is the `SYSTEM.max_grad` and `SYSTEM.max_slew` of `tests/synthetic.py`.

#### `test_matches_oracle_on_the_sequences_of_the_oracle_tests`

**Checks:** `gradient_peaks` matches the oracle of the gradient waveform on the whole file and
on up to 40 windows, for each sequence of `tests/gap_sequences.py` (parametrized): the two
sequences of pypulseq-issues 12 (a first value after a delay, and an end before the end of its
block), a zero gap with a step, a short gap, a long gap, a first value and a last value that
are not 0, and one block with two axes.

**How:** The test loads each sequence with `load(seq, "cpp-siemens")`. The windows come from `_oracle_windows`
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
- `spec` rejects most of these sequences (a first value that is not 0 after a delay, `gradient.nonzero-start-delay`, or an end
  that is not 0 before the end of the block, `gradient.nonzero-end-align`), so the test uses `cpp-siemens`, which plays them.
  The oracle reads the gradients that the snapshot plays (`sequence_of(snap)`).
- The test makes no window shorter than `TIME_TOLERANCE` (1 ns). The values of such a window
  are of a part of a segment that is shorter than the tolerance of a time.

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
added. The test reads each sequence with `load(seq, "cpp-siemens")`: `spec` rejects
a first value that is not 0 after a delay (`gradient.nonzero-start-delay`) and an end that is not 0 before the end of its block
(`gradient.nonzero-end-align`). The oracle reads `sequence_of(snap)`. The windows and the comparison are those of
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
sequence the test makes the snapshot `load(make_seq(), "cpp-siemens")` (`spec` rejects some of the
sequences: `gradient.nonzero-start-delay`, `gradient.nonzero-end-align`, and the 4 µs raster of `raster_4us_sequence`), calls `block_gradient_values` and `gradient_peaks` and compares them with
`==`, not `pytest.approx`. `_junction_time` reads the first point of the event of the credited
block with `get_block` of
`sequence_of(snap)`, the gradients that the snapshot plays. For a line across a short gap, it reads the last point of the event
before it, with `gradient_offsets`.

**Assumptions:**

- Exact equality holds because both functions use the same arithmetic on the same values of
  each block: the columns of `_BlockData`.
- The 4 random sequences of `_random_gradient_sequence` have no gap with a value that is not 0
  (every event starts and ends at 0), so their junctions are 0. The 8 sequences of
  `random_gap_sequence` have steps, lines and ramps.
- The test does not compare a window: `block_gradient_values` has no window.

#### `test_block_gradient_values_use_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The `junction_hz_per_m_per_s` of `block_gradient_values` is divided by the gradient
raster that the file declares, not by 10 µs. `load` of the file and `load` of the sequence object that
wrote it give the same values.

**How:** `raster_4us_sequence` has a junction of 60 T/m/s with 4 µs (24 T/m/s with 10 µs).
The test writes the sequence to a file in `tmp_path`. For `load(path, "cpp-siemens")` and
`load(seq, "cpp-siemens")`, it checks that the y junction step of block 2 is 60 T/m/s times `GAMMA_1H`
(Hz/m/s), that the step of block 1 is 0, and that the x and z steps are 0 everywhere.

**Assumptions:** `spec` rejects this raster (see the test above), so the test uses `cpp-siemens`. The
file stores the amplitudes with fewer digits than the sequence object, so the comparison has a relative
tolerance of 1e-4.

#### `test_a_window_gives_the_same_result_with_and_without_the_kept_data`

**Checks:** For a window, `gradient_peaks` of a snapshot that has its kept data (the per-event
values and the values over the blocks: the end of each block, the junction and its time, the
ramps, the extent in time of each block, and the RMS of the whole file) gives a result equal
(`==`) to the result of the same call on a snapshot whose kept data is empty. The kept values
over the blocks and the search of the block range (`np.searchsorted`) do not change a result,
also for a window edge on a block edge, and for a block of zero duration at a window edge or
inside the window.

**How:** Both snapshots are `load(seq, "cpp-siemens")`: `spec` rejects the delayed junction sequence
(`gradient.nonzero-start-delay`). For six sequences (`build_repeating(30)`, a sequence of trapezoids with blocks of zero
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
ramp to 0 starts. In the second sequence, the value after 300 µs is in block 2. `spec` rejects both
sequences (`gradient.nonzero-start-delay` for the first, `gradient.nonzero-end-align` for the second), so the test reads them with `cpp-siemens`. A is
31932 Hz/m, which the file holds exactly.

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

**Assumptions:** `spec` rejects the first gradient, which ends at 3 U before its block ends (`gradient.nonzero-end-align`), so the
test reads the sequence with `cpp-siemens`. U (1e4 Hz/m) and the multiples of it that the test uses are
held exactly by the file.

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
block 2 are one time for the credit of the vector peak. The sequence is read with `cpp-siemens` (`spec`
rejects the 4 µs raster). The file holds 16 mT/m and 15.76 mT/m in Hz/m with 6 significant digits, so the
peaks have a relative tolerance of 1e-5.

#### `test_the_gap_rule_uses_the_gradient_raster_of_the_file_not_of_seq_system`

**Checks:** The gap rule (zero, short, long) and the ramps use the gradient raster that the file declares
(`snap.data.rasters.gradient`), not the 10 µs of the pypulseq `Opts` default.

**How:** With a 4 µs gradient raster, the test builds an x gradient from 0 to V in 400 µs in a
block of 410 µs, and an x gradient from W to 0 in 400 µs in the second block. The gap is 10 µs,
which is more than one raster time of 4 µs. It is a long gap: the slope of the ramp to 0 is
V / 2 µs, the slope of the ramp from 0 is W / 2 µs, and the junction of block 2 is 0. (With
10 µs, it would be a short gap, with a line and a junction.) The test writes the sequence to a file in
`tmp_path`. For `load(path, "cpp-siemens")` and `load(seq, "cpp-siemens")`, it checks that the gradient
raster is 4 µs, the junction, the slews and their times, and `gradient_peaks` on two windows against the
oracle.

**Assumptions:** `spec` rejects this sequence (the 4 µs raster with a block duration raster of 10 µs, and
a gradient that ends at V before its block ends, `gradient.nonzero-end-align`), so the test uses `cpp-siemens`. The file stores
the amplitudes with fewer digits, so the slews have a relative tolerance of 1e-4.

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
of the sequence), give the slew. The snapshot is `load(make_seq(), "cpp-siemens")`
(`spec` rejects some of the sequences: `gradient.nonzero-start-delay`, `gradient.nonzero-end-align`, and the 4 µs raster), and the polyline is that of
`sequence_of(snap)`, the gradients that the snapshot plays, so that the peak agrees to 1e-12 with
the value in the file and not with the value of the builder (the writer rounds it). The test compares the peak (and its time where it is above 0),
the junction and the slew of each block with the values of the package
(`numpy.testing.assert_allclose`, 1e-12 for the peak and 1e-9 for the junction and the slew).
The time of the slew of a block must be the time of one of its items that have the largest
slope.

**Assumptions:** The slopes of two items of one block can be equal up to the rounding of the
times, so the test accepts the time of each item that has the largest slope. The test does not
compare the time of a slew of 0.

#### `test_a_gap_with_ends_that_are_not_0_gives_the_spectrum_of_the_oracle_waveform`

**Checks:** The spectrum of a sequence with a short gap, a long gap or a step at a junction, and
ends that are not 0 next to it, equals the spectrum that the oracle calculates from the oracle
waveform (`tests/oracles/waveform.py`, the model of MATLAB Pulseq). The sequences also have a
first value and a last value that are not 0.

**How:** Parametrized over 23 sequences: `zero_gap_sequence`, `short_gap_sequence`,
`long_gap_sequence`, `non_zero_ends_sequence`, the two sequences of pypulseq-issues 12, and 17
more, `gap_of_1_5_raster_times_sequence` (a long gap of 1.5 raster times between two values that are not 0), `short_gap_from_0_sequence` and `short_gap_to_0_sequence` (a short gap from 0 to a value, and from a value to 0), a copy of each sequence of `tests/gap_sequences.py` with each amplitude negated (`gap_sequences.negated`), and the 8 sequences of `random_gaps.random_gap_sequence` with the seeds 0 to 7 (random signs, delays of 0 to 7 raster times, and zero, short and long gaps). Each sequence is loaded with `cpp-siemens`, because `spec` rejects a gradient that ends above 0
before its block ends (`gradient.nonzero-end-align`), one that starts above 0 after a delay (`gradient.nonzero-start-delay`), and a delay off the
gradient raster (`raster.gradient-delay`) in these sequences. The oracle reads `sequence_of(snap)`. `_assert_matches_oracle`
compares the axis spectra and the RSS (times `1e3 / gamma`) with `tests/oracles/grad_spectrum.py`
within 1e-12.

**Assumptions:** pypulseq's `calculate_gradient_spectrum` draws a line across a long gap and has
no step at a junction (pypulseq-issues 12), so it is not the reference.

#### `test_the_levels_of_a_gap_with_ends_that_are_not_0_are_the_safe_model_of_the_oracle_samples`

**Checks:** For a sequence with a short gap or a long gap and ends that are not 0 next to it,
`pns_levels` equals the SAFE model of the package on the samples of the oracle. This includes a
first value and a last value of an axis that are not 0. It also covers a sequence with a block
that is not on the raster, where `pns_levels` samples with `GradientSampler.sample`. The sequence is loaded with `cpp-siemens`,
because `spec` rejects a gradient that ends above 0 before its block ends (`gradient.nonzero-end-align`), a gradient that
starts above 0 after a delay (`gradient.nonzero-start-delay`) and a delay off the gradient raster (`raster.gradient-delay`), and the oracle reads the
gradients as the snapshot plays them (`tests/oracles/blocks.sequence_of`), so the rounding of the
written file is not in the difference.

**How:** Parametrized over 51 sequences. Six are a two-axis short gap with a first value and a
last value that are not 0, `long_gap_sequence`, the two sequences of pypulseq-issues 12,
`non_zero_ends_sequence`, and `long_gap_sequence` with a last block of 1.5 raster times (a block raster of 1 µs, `_add_a_delay`). On the
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
reference stacks the samples of the oracle, which reads `sequence_of(snap)` and not the builder's
`pp.Sequence`, into `(N, 3)`. They are `oracle.block_samples` at the
gradient raster, and `oracle.sample` at `(k + 0.5) * dt` for the sequence that is not on the
raster. It runs `_safe_gwf_to_pns_chunk` of `pulseq_analysis.analyses.safe` in one chunk with the example hardware. The
axis values are 0.01 times the percent, and the total is the root of the sum of squares.
`pns_levels` runs with `bin_s=dt`, so each bin is one sample. The test checks the number of
samples, `on_raster` (false only for the names that end in `_off_raster`), the peak and the axis peaks (relative 1e-9), the peak time, and the minimum
and maximum of each bin against the total (relative 1e-6, because of the float32 cast, and absolute 1e-12 of the largest total,
because the total of a sample at 0 can be a rounding residue of about 1e-16 of the peak where one of the
two paths holds the last point of a ramp as a value that is not exactly 0).

**Assumptions:** `calculate_pns` is not the reference, because it draws a line across each gap
(pypulseq-issues 12).

#### `test_sample_equals_the_oracle_for_the_whole_sequence`

**Checks:** `GradientSampler.sample` equals `oracle.sample` on a grid across each sequence of the
model that `spec` rejects, as the test of the same name of section 2.5 does for the sequences that
`spec` reads: the same grid and the same tolerance.

**How:** Parametrized over the 17 sequences of `_MODEL_SEQUENCES` in `_REJECTED_BY_SPEC`
(`short_gap`, `issue_12_delayed`, `issue_12_early_end`, `off_raster_events`,
`gap_of_1_5_raster_times`, `short_gap_to_0`, their negated copies that exist, and the 8
`random_gaps` sequences). Each is loaded with `cpp-siemens`. The test calls `_assert_matches_oracle`
of `test_sampling.py` on `_model_times(snap)`.

**Assumptions:** As the test of section 2.5.

#### `test_sample_of_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`

**Checks:** For each time range `t[i:j]` of a grid, `sample` equals the oracle, and the same
slice of `sample` of the whole grid exactly, for the sequences that `spec` rejects (the test of
the same name of section 2.5 has the others).

**How:** Parametrized over `short_gap`, `issue_12_delayed`, `off_raster_events` and
`gap_of_1_5_raster_times`. Each is loaded with `cpp-siemens`. The test calls
`check_a_time_range_equals_the_oracle_and_the_slice_of_the_whole_grid`.

**Assumptions:** None.

#### `test_block_samples_equals_the_oracle_for_the_whole_sequence`

**Checks:** `block_samples` of the whole sequence equals `oracle.block_samples` for each axis, at
the gradient raster and at one half and one fifth of it, for the sequences that `spec` rejects (the
test of the same name of section 2.5 has the others).

**How:** Parametrized over the 29 cases of `_WHOLE_CASES` with a sequence of `_REJECTED_BY_SPEC`:
the 17 sequences at the gradient raster, and `short_gap`, `issue_12_delayed`, `off_raster_events`,
`gap_of_1_5_raster_times`, `short_gap_to_0` and `negated_short_gap` at one half and one fifth of
it. Each is loaded with `cpp-siemens`. The test calls
`check_block_samples_equal_the_oracle_for_the_whole_sequence`.

**Assumptions:** As the test of section 2.5: the two are not bit-equal, and the difference is the
float drift of the block starts.

#### `test_block_samples_of_any_range_equals_the_oracle_and_the_slice_of_the_whole_range`

**Checks:** Each range of blocks and each range of samples (`skip` and `count`) of
`block_samples` equals the same samples of the oracle, and the same slice of the whole range
exactly, for the sequences that `spec` rejects (the test of the same name of section 2.5 has the
others). A new sampler gives the same values as one that made the whole range first.

**How:** Parametrized over the five cases of `_ANY_RANGE_CASES` with a sequence of
`_REJECTED_BY_SPEC`: `short_gap` at the gradient raster, `issue_12_delayed` at one fifth,
`off_raster_events` at the gradient raster and at one fifth, and `gap_of_1_5_raster_times` at the
gradient raster. Each is loaded with `cpp-siemens`. The test calls
`check_block_samples_of_any_range_equal_the_oracle_and_the_slice_of_the_whole_range`.

**Assumptions:** The tolerance to the oracle is that of the test of section 2.5.

#### `test_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`

**Checks:** A sampler made by `GradientSampler._from_parts` gives, bit for bit, the `sample` and
`block_samples` values of `GradientSampler(snap)`, and keeps its gaps in the dict that was passed,
for the sequences that `spec` rejects (the test of the same name of section 2.5 has the others).

**How:** Parametrized over `short_gap`, `off_raster_events` and `random_gaps_0`. Each is loaded
with `cpp-siemens`. The test calls
`check_a_sampler_from_parts_gives_the_samples_of_the_sampler_of_the_snapshot`.

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
values `A * [1, 0.6, 0, 0, 0, 0.3, 0.5, 0, 0]` (absolute 1e-9 of `A`).
`_off_raster_events_sequence` is loaded with `cpp-siemens` (`_load_model("off_raster_events")`): `spec`
rejects it (`raster.gradient-delay`, `gradient.nonzero-start-delay`, `gradient.nonzero-end-align`).

**Assumptions:** `add_block` accepts the delays that are not on the raster and the start value
that is not 0 after a delay, because the value is below `max_slew * grad_raster_time`.

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
zero with `numpy.testing.assert_array_equal`. The sequence is loaded with `cpp-siemens`. `spec` rejects a gradient that ends above 0 before its block ends (`gradient.nonzero-end-align`). `cpp-siemens` plays it. The values are exact in float32 (1000.0 Hz/m), so the assertions are exact.

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
to 119 of block 2 are all 0 and that samples 20 to 59 are not. The sequence is loaded with `cpp-siemens`. `spec` rejects a gradient that ends above 0 before its block ends (`gradient.nonzero-end-align`). The sequence also has a gradient that starts above 0 after a delay (`gradient.nonzero-start-delay`). `cpp-siemens` plays it. The values are exact in float32 (1000.0 Hz/m), so the assertions are exact.

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
must be `[0.0]`, with `numpy.testing.assert_array_equal`. The sequence is loaded with `cpp-siemens`. `spec` rejects a gradient that ends above 0 before its block ends (`gradient.nonzero-end-align`). `cpp-siemens` plays it. The values are exact in float32 (1000.0 Hz/m), so the assertions are exact.

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
1000.0. The sequence is loaded with `cpp-siemens`. `spec` rejects a gradient that ends above 0 before its block ends (`gradient.nonzero-end-align`). `cpp-siemens` plays it. The values are exact in float32 (1000.0 Hz/m), so the assertions are exact.

**Assumptions:** The float product `(13 + 0.5) * dt` equals `27 * raster`. This is why the
test uses 27 steps, and the test asserts it.

#### `test_the_samples_in_a_short_gap_are_the_line_by_hand`

**Checks:** A sample in a short gap (one raster time) is on the line from the last value of the
earlier event to the first value of the later event. It is 0 in the own event after its last
point.

**How:** `short_gap_sequence` has a gradient that ends at 3 U at 100 µs in a block of 110 µs, and
a second block that starts at 2 U. U is 1e4 Hz/m. The test checks the first 20 of the 21 samples
at the gradient raster with the hand values. The 11 samples of block 0 are 0.15, 0.45, ...,
2.85 U on the ramp, then 2.5 U at 105 µs on the line. The first 9 samples of block 1 are 1.9,
1.7, ..., 0.3 U. The sequence is loaded with `cpp-siemens` (`_load_model`): `spec` rejects it (`gradient.nonzero-end-align` for `short_gap_sequence`). The hand values are the same, within the same tolerance.

**Assumptions:** The sample at 105 µs is not 0, so this test fails for a rule that gives 0 in
every gap.

#### `test_the_samples_in_a_ramp_of_a_long_gap_that_are_not_at_its_ends_are_the_ramp_by_hand`

**Checks:** A sample inside the ramp to 0 or the ramp from 0 of a long gap has the value of the
ramp, in the block of the event and in the next block.

**How:** `_off_raster_events_sequence` at the gradient raster. The ramp to 0 is from 3.3 to 3.8
raster times and has the sample at 3.5. The ramp from 0 is from 8.2 to 8.7 and has the first
sample of block 1 at 8.5. The test compares the 16 samples with the hand values (absolute 1e-9
of `A`). The values at 3.5 and 8.5 are 0.6 A and 0.3 A. The other samples are those of the own
events. The sequence is loaded with `cpp-siemens` (`_load_model`): `spec` rejects it (`raster.gradient-delay`, `gradient.nonzero-start-delay` and `gradient.nonzero-end-align` for `_off_raster_events_sequence`). The hand values are the same, within the same tolerance.

**Assumptions:** None.

#### `test_block_samples_at_the_last_point_of_an_event_and_at_a_step_equals_the_oracle`

**Checks:** `block_samples` of the whole sequence equals `oracle.block_samples` at the gradient
raster where a sample falls at the last point of an event, and where it falls at a step inside
one event. The sample at the last point has the value of that point, also when the sum of the
delay and the offset of the point is one ulp before the sample time (review 1.3 of
`docs/reviews/2026-10-07-code-review.md`). The sample at a step has the value before the step,
the rule of `sample` (review 1.4).

**How:** Parametrized over 15 sequences, all loaded with `cpp-siemens`: `spec` rejects them (`gradient.nonzero-start-delay`, `gradient.nonzero-end-align`). The
oracle reads `sequence_of(snap)`, the gradients as the snapshot plays them. Fourteen are `gap_sequences.delayed_ramp_sequence`:
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

#### `test_the_series_of_pns_safe_levels_are_valid`

**Checks:** Each series of `pns.safe.levels` of `raster_4us_sequence` is a valid `Series` and equals
its round trip through the strict JSON text, with no threshold, with one and with two, and with the
default bin and with bins of 3.7 ms and 0.1 ms (the test of the same name of section 2.8 has the
other sequences).

**How:** Parametrized over the four cases of `_PNS_CASES`. The test loads
`raster_4us_sequence()` with `cpp-siemens`, because `spec` rejects a gradient raster of 4 µs with a
block duration raster of 10 µs (`definitions.raster-commensurate`), and calls
`check_the_series_of_pns_safe_levels_are_valid`.

**Assumptions:** None.

#### `test_the_series_of_gradient_spectrum_is_valid`

**Checks:** The series of `gradient.spectrum` of `raster_4us_sequence` is one valid `Series` that
equals the series that `from_obj` reads from its `to_obj` (the test of the same name of section 2.8
has the other sequences).

**How:** The test loads `raster_4us_sequence()` with `cpp-siemens` and calls
`check_the_series_of_gradient_spectrum_is_valid` with a sequence that has a gradient.

**Assumptions:** None.

#### `test_a_nan_of_the_file_is_credited_to_its_block_at_its_first_nan`

**Checks:** In `tests/seqfiles/bad_syntax_number.seq` through `cpp-siemens`, whose trapezoid 1
has the amplitude `nan`, `gradient_peaks` and `block_gradient_values` follow the rule of a NaN
(a NaN propagates), with no rotation, with `CppSiemens(rotation="apply")`, with the rotation
applied to the block of the NaN, and with a session that rotates the field of view. Every other
value is the value of the same file with the amplitude 0.

**How:** The trapezoid is gx of block 2 (play index 1, from 300 µs to 800 µs), with gy. The test
writes the file in `tmp_path`, and the same file with the amplitude 0 for the clean values
(`_bad_number_files`). Parametrized over four settings (`_NAN_SETTINGS`):
- `"cpp-siemens"` (the warning of the unapplied rotation of block 5 is ignored), and
  `CppSiemens(rotation="apply")`: block 2 has no rotation, its event is decoded, and the NaN is on
  x only.
- `CppSiemens(rotation="apply")` with block 2 given the extension list 3 of the file (the rotation
  object 1, 45 degrees about z), and `"cpp-siemens"` with `Session(fov_rotation=...)`, 90 degrees
  about z: block 2 is read through `gradients_at`, and the reader's rotation gives NaN on every
  axis of the block.
The check `check_a_nan_of_one_block_is_credited_to_its_first_nan` (section 2.3) is called with
block 1 (play index), the block ID 2, the slew at 400 µs (the start of the rise) and the vector
peak at 405 µs. The peak is at 500 µs (the end of the rise) for the decoded event, and at 405 µs
when the block is read through `gradients_at`: its points are at the times of the points of gx and
gy, and gy has one at 405 µs.

**Assumptions:** The vector is NaN first at 405 µs in each setting: in the decoded block the
polyline of gx is NaN between 0 at 400 µs and the NaN at 500 µs, and gy has a point at 405 µs.

#### `test_the_pns_peak_of_a_nan_of_the_file_is_nan_at_the_first_nan_sample`

**Checks:** In `bad_syntax_number.seq` through `cpp-siemens`, the summary of `pns_levels` gives a
NaN peak of the total, at the time of the first sample whose total is NaN, in each setting of
`_NAN_SETTINGS`.

**How:** Parametrized over the four settings of the test above. `pns_levels` with `EXAMPLE_HW`
(pypulseq's example hardware and a label); `peak_hz_per_t` must be NaN and `peak_time_s` the time
of sample 40, `(40 + 0.5) * dt_s` (405 µs), to `TIME_TOLERANCE`.

**Assumptions:** Sample 40 is the first sample inside the NaN trapezoid, which starts at 400 µs;
the samples before it are finite, and the filters of the SAFE model carry the NaN to every later
sample. The test does not check the level or the intervals of a threshold.

### 3.11 `load` through `cpp-siemens` (`test_load_in_pulseq_analysis.py`)

`test_load_in_pulseq_analysis.py` tests `load` of pulseq-analysis through `cpp-siemens`: the
snapshot and the warning of an unapplied rotation (`test_snapshot.py`, section 2.17), the block
table (`test_seq_index.py`, section 2.4) and the played gradients (`test_played.py`, section 2.3).
The tests of pulseq-analysis run without the plugin, so these are their cases for `cpp-siemens`:
the tests call the `check_*` helpers of those modules, or test what only the reader's decoding
has. Like `test_interpreter.py`, the module needs pulseq-analysis and is not collected without it.

#### `test_load_of_a_file_is_the_reading_of_cpp_siemens`

**Checks:** `load(path, interpreter)` holds `read_seqfile(path, interpreter)`, with a
`CppSiemensDecoding` (`check_load_of_a_file`).

**How:** Parametrized over `"cpp-siemens"` and `CppSiemens(oversampling="edge",
rotation="apply")`, on the gradient echo file `oracle/pulseq_seq4.seq`.

**Assumptions:** None.

#### `test_load_through_cpp_siemens_gives_a_snapshot_of_a_file_that_spec_rejects`

**Checks:** A file that `spec` rejects gives, through `cpp-siemens`, which plays it as the C++
reader does, a snapshot with blocks.

**How:** `bad_gradient_nonzero_end_align.seq` and `bad_raster_gradient_delay.seq`: `load` through
`spec` raises `SeqFileError`, and the index of the `cpp-siemens` snapshot has blocks.

**Assumptions:** None.

#### `test_load_raises_not_supported_for_a_version_outside_the_package_through_cpp_siemens`

**Checks:** A file of version 1.3 raises `NotSupported` from `load` through `cpp-siemens` (Q1).

**How:** `bad_version_unsupported_1_3.seq`.

**Assumptions:** None.

#### `test_the_snapshot_records_cpp_siemens_with_its_settings`

**Checks:** `snap.interpreter` is the `CppSiemens` object given, and its `str` names the settings
that are not the defaults.

**How:** `CppSiemens(oversampling="edge")` on the gradient echo file: the same object and
`"cpp-siemens(oversampling='edge')"`.

**Assumptions:** None.

#### `test_load_warns_for_a_rotation_that_cpp_siemens_leaves_unapplied`

**Checks:** With `cpp-siemens`'s default (D6.2), `load` of a file whose blocks play rotations
emits one `ScannerSettingWarning`, whose hint names `rotation='apply'`, and keeps the decoding's
rotation record with the setting `"reader"`, no block rotated and some left unapplied
(`check_load_warns_for_an_unapplied_rotation`).

**How:** Parametrized over the two radial files.

**Assumptions:** None.

#### `test_load_does_not_warn_when_cpp_siemens_applies_the_rotations`

**Checks:** With `CppSiemens(rotation="apply")`, `load` of a file with played rotations emits no
warning, and every block with a rotation is rotated
(`check_load_applies_rotations_without_a_warning`).

**How:** Parametrized over the two radial files.

**Assumptions:** None.

#### `test_load_does_not_warn_for_a_rotation_that_no_block_plays_through_cpp_siemens`

**Checks:** A rotation that no block plays gives no warning with `cpp-siemens`'s default
(`check_load_does_not_warn_for_a_rotation_that_no_block_plays`).

**How:** `valid_1_5_1_rotation_not_played.seq`.

**Assumptions:** None.

#### `test_the_rotation_of_cpp_siemens_changes_the_measured_gradients_only_where_it_is_applied`

**Checks:** On a radial file, `CppSiemens(rotation="apply")` and `spec` give the same x and y peaks
(to 1e-6 relative: both rotate, one with the reader's helper and float32 values, one with the
package's), and they differ from the peaks of `cpp-siemens`'s unrotated default.

**How:** `pulseq_make_radial.seq`; `gradient_peaks` of the three snapshots.

**Assumptions:** None.

#### `test_a_copy_of_a_cpp_siemens_snapshot_is_a_new_snapshot_with_no_kept_results`

**Checks:** A copy of a `cpp-siemens` snapshot from `pickle` or `copy.deepcopy` is a new snapshot
with no kept results, equal data and equal results, which decodes the data again
(`check_a_copy_of_a_snapshot`).

**How:** Parametrized over the two copies, on the gradient echo file.

**Assumptions:** None.

#### `test_the_index_of_a_cpp_siemens_file_with_no_blocks_is_empty`

**Checks:** `cpp-siemens` reads a file with an empty `[BLOCKS]` section (`spec` rejects it,
`blocks.empty`): its index has no block, `end_s` 0.0 and no gradient.

**How:** `bad_blocks_empty.seq`.

**Assumptions:** None.

#### `test_the_index_of_a_cpp_siemens_snapshot_is_the_index_of_its_model_for_each_file`

**Checks:** Through `cpp-siemens`, the index of a snapshot of each file whose blocks play the
events of the file is that of its model
(`check_the_index_of_a_snapshot_is_the_index_of_its_model`).

**How:** The files of `test_seq_index.py`; at least 15 are compared.

**Assumptions:** None.

#### `test_the_index_of_spec_and_of_cpp_siemens_are_equal_where_both_play_the_file_ids`

**Checks:** For each file that both interpreters read and that has no block with a rotation, the
two indexes are equal: both keep the block and event IDs of the file.

**How:** The files of `test_seq_index.py` (`valid_*.seq` and `oracle/*.seq`); at least 10 are
compared.

**Assumptions:** The fixtures whose IDs are not unique are rejected by `spec` (`id.unique`), so
the two readings of the IDs do not differ on a compared file.

#### `test_the_points_of_the_played_events_are_the_gradients_of_cpp_siemens`

**Checks:** On each fixture that `cpp-siemens` reads, in each setting, the points of the played
events are the reader's `gradientsAt`, to 1e-7 of the largest value
(`check_the_points_are_the_gradients` of `test_played.py`, section 2.3): for the decoded events,
for the rotated blocks of `rotation="apply"`, and for the blocks with an event after the block's
end (`oversampling="preserve"` of the spiral, D6.1, D7.4).

**How:** Parametrized over every fixture and four settings: `CppSiemens()`,
`CppSiemens(oversampling="edge")`, `CppSiemens(oversampling="preserve")` and
`CppSiemens(rotation="apply")`. A fixture that the setting rejects is skipped.

**Assumptions:** The tolerance covers the float32 rounding of the reader's values (D7.2). The
blocks made from `gradients_at` test the step and end handling of `_played`, not an independent
decoding.

#### `test_a_rotated_block_has_an_event_on_each_axis_from_gradients_at`

**Checks:** In a radial file read with `CppSiemens(rotation="apply")`, each block with a rotation
that is not the identity and a gradient has an event on each axis with a key above the largest
file ID, and each other block keeps the file IDs of its events.

**How:** `tests/seqfiles/oracle/pulseq_make_radial.seq`. The rotated blocks are those of
`decoding.rotations()` with a vector part that is not 0 and a gradient event. The test checks
their keys on the three axes, and that the played columns of the other blocks equal the columns
of the block table.

**Assumptions:** The fixture has at least one such block (checked).

#### `test_an_event_that_cpp_siemens_plays_after_the_end_of_its_block_ends_at_the_block_end`

**Checks:** With `CppSiemens(oversampling="preserve")`, the oversampled gradient of the spiral
lasts longer than its block (the reader keeps all the samples on the 10 µs raster, D6.1); the
played event of every block ends at or before the end of its block, and at least one event is
made from `gradients_at` (a key above the largest file ID).

**How:** `tests/seqfiles/oracle/koma_v1.5_spiral.seq`; for each block and axis with an event, the
last point time is at most the block duration plus 1e-12 s.

**Assumptions:** None.

#### `test_the_waveform_of_the_measurements_is_the_gradients_of_the_reader`

**Checks:** On each fixture that `cpp-siemens` reads, the waveform of the measurements
(`gradient_sampler(snap).sample`) is the reader's own `gradientsAt`
(`snap.data.reading.gradients_at`), on each axis, to 1e-7 of the largest value of the axis.

**How:** Parametrized over every file of `tests/seqfiles` and of the package's `tests/fixtures`;
a file that `cpp-siemens` rejects is skipped. For each axis the probes (`_reader_probes`) are
the middle of each segment of the played points of each block, and a quarter, a half and three
quarters of each block of positive duration. A probe within `TIME_TOLERANCE` of a step of the
played points (two points at one time with two values, or an end of an event at a value that is
not 0) is left out, and so is a probe in a gap where the sampler draws a line between two events
(the line across a short gap, the ramps of a long gap; `sampling`, the module docstring). The
sampler is read at the block start plus the probe's time, the reader at the block and the time
(µs). A NaN must be NaN in both, and the rest must agree to 1e-7 times the largest value of the
reader on the axis (at least 1).

**Assumptions:**

- The tolerance covers the float32 rounding of the reader's values (D7.2): the played points hold
  the float32 product of the amplitude and a sample, and `gradientsAt` interpolates the samples
  before the product.
- The comparisons of the oracles build the oracle from `played_gradients`
  (`tests/oracles/blocks.py`), so they cannot find a played event that is not the reader's;
  this test compares with the reader itself. On the two files of the buffer of a block
  (`gradient_buffer_ext_trap.seq`, `gradient_buffer_arbitrary.seq`) it fails where the played
  gradients take the decoding of an event in the first block that plays it.
- Only the default settings of `cpp-siemens` are checked: with them, the reader's values are those
  of the decoding.

#### `test_the_measurements_of_an_event_that_keeps_the_buffer_of_its_block_are_the_reader_s`

**Checks:** In block 1 of `tests/fixtures/gradient_buffer_ext_trap.seq` the reader and the sampler
give 250, 750, 1000, 750 and 0 Hz/m on gy at 5, 15, 25, 35 and 45 µs, and `gradient_peaks` gives
a peak of 1000 Hz/m on y; in `tests/fixtures/gradient_buffer_arbitrary.seq` the peak on y is 1000
Hz/m.

**How:** In both files gradient event 2 is alone on gx in block 0, and on gy after event 1 on gx
in block 1; its time shape (the extended trapezoid) or its wave shape (the arbitrary gradient) is
`0 0 -2`, which writes none of its 4 samples, so in block 1 it keeps the values of the wave shape
of event 1, which the reader decompressed before it into the same buffer
(`decodeExtTrapGradInBlock`, `decodeArbGradInBlock`). The values are compared to 1e-4 Hz/m, the
peaks to a relative 1e-7.

**Assumptions:** The values of the reader are those that it gives on this platform; the test
checks them too.

#### `test_the_measurements_of_an_event_wholly_after_the_end_of_its_block_are_the_reader_s`

**Checks:** In block 4 (play index) of `tests/fixtures/gradient_one_point_after_block.seq`, whose
gx event lies wholly after the end of the block, the sampler gives the reader's values on gx at a
quarter, a half and three quarters of the block, and these are 0; the peak of block 4 on x
(`block_gradient_values`) is 0.

**How:** Block 4 lasts 100 µs, and its gx is an extended trapezoid of one point with the delay
200 µs. The reader (`snap.data.reading.gradients_at`) is read at the block and the times (µs),
the sampler at the block start plus the times. The values are compared exactly.

**Assumptions:** None.

#### `test_an_edge_gradient_with_no_sample_plays_0_in_the_measurements`

**Checks:** With `CppSiemens(oversampling="edge")`, an oversampled gradient of 1 or 2 samples has
no sample, and the reader plays 0 on its axis: the points of the event
(`CppSiemensDecoding.gradient_points`) are 0, `gradient_peaks` gives a peak and a slew of 0 on
x, and the sampler gives the reader's 0 on gx.

**How:** Parametrized over 1 and 2 samples. The file is that of `test_api.oversampled_file`
(one block of 200 µs, X the oversampled gradient with no delay), written in `tmp_path`, with the
`first` and the `last` of X at 300 000 Hz/m. The reader (`snap.data.reading.gradients_at`) is
read at 0, 5, 50, 100 and 199 µs of block 0, the sampler at the block start plus the times. The
values are compared exactly. Without the fix, the points are the `first` and the `last` at the
delay, and `gradient_peaks` gives a peak of 300 000 Hz/m and a slew of 3e10 Hz/m/s on x.

**Assumptions:** One delay (0), one value of `first` and `last`. `gradientsAt` plays 0 on X at
every time of the block (cpp:3653-3678): before the delay, after it, and at the delay, where it
returns early.

#### `test_the_waveform_of_an_event_of_length_0_that_the_session_rotates_is_the_reader_s`

**Checks:** In `tests/fixtures/gradient_buffer_ext_trap.seq` under a session that rotates the
field of view, the waveform of the measurements (`gradient_sampler(snap).sample`) is the reader's
`gradientsAt` turned by the session's rotation, on each axis, to 1e-7 of the largest value of the
axis.

**How:** In block 0 the reader decodes event 2 with all its times at 0 (an event of length 0).
The file is loaded through `cpp-siemens` with `Session(fov_rotation=...)`, 90 degrees about z.
The probes are those of `_reader_probes`; the sampler is read at the block start plus the probe's
time, and `CppSiemensDecoding.gradients_at` (the reader's `gradientsAt` with the session's
rotation, `rotate_vec3_by_quat`) at the block and the time (µs). The values must agree to 1e-7
times the largest value of the axis (at least 1).

**Assumptions:** The file has no NaN, so the test does not compare NaNs.

#### `test_the_cells_of_one_event_and_one_variant_decode_alike`

**Checks:** `CppSiemensDecoding.gradient_variants()` is what `_played` needs of a plugin: each two
cells (a block and an axis) with the same gradient event and the same variant decode alike, and
with None every cell of an event does. It is None on each file of `tests/seqfiles` that `spec`
reads, and it gives event 2 two variants in each of the two files of the buffer of a block.

**How:** Parametrized over every file of `tests/seqfiles` and of the package's `tests/fixtures`;
a file that `cpp-siemens` rejects is skipped. A result that is not None must be an int64 array
(blocks, 3), read-only, with 0 at each cell with no event. For each cell with an event, in play
order, the test takes `gradient_points` and checks that it equals, bit for bit, that of the first
cell with the same event and variant (with None, the same event).

**Assumptions:** The fixtures have the cases; that the variants hold for every file is the
reader's code, which the test does not check.

#### `test_cpp_siemens_decodes_one_block_for_each_unique_gradient_event`

**Checks:** `played_gradients` of a `cpp-siemens` snapshot decodes one block for each unique
gradient event, and its result is kept: a second call decodes nothing.

**How:** `tests/seqfiles/oracle/pulseq_epi_rs.seq`. `CppSiemensDecoding.block` is replaced by a
counting wrapper; the count after the first call is the number of unique nonzero gradient IDs of
the block table, and stays so after the second call, which returns the same object.

**Assumptions:** None.

### 3.12 The scanner session through `cpp-siemens` (`test_session_in_pulseq_analysis.py`)

`test_session_in_pulseq_analysis.py` tests the scanner session of pulseq-analysis (section 2.29)
through `cpp-siemens`: `CppSiemens.decode(data, session)` (P22), with the reader's hook
`setActualSoftDelay_ru` and its `rotate_vec3_by_quat`, and the records of what the reader ignores.
Like `test_interpreter.py`, the module needs pulseq-analysis and is not collected without it. It
uses `tests/session/scanner_session.seq` of pulseq-analysis.

#### `test_cpp_siemens_implements_the_protocol_version_of_pulseq_analysis`

**Checks:** `CppSiemens.protocol` is `seqfile.PROTOCOL`, 1, and `seqfile.interpreter("cpp-siemens")`
is `CppSiemens()`.

**How:** The test compares them.

**Assumptions:** None.

#### `test_cpp_siemens_records_what_the_reader_ignored`

**Checks:** The model of the session fixture records the two `NOSLC` rows (lines 61 and 63) as
labels with the reason "unknown"; `valid_1_5_1.seq` records the extension `UNKNOWN`; and
`valid_label_unknown.seq` the label `FOO`.

**How:** The test reads the three files with `cpp-siemens`.

**Assumptions:** None.

#### `test_the_soft_delays_of_cpp_siemens_are_those_of_spec_through_the_reader_s_hook`

**Checks:** Rule 3: under TE = 2 ms and TR = 10 ms, the actual and stored durations of
`cpp-siemens` equal those of `spec` exactly, and the two `soft_delay_record`s are equal. The neutral
session keeps the stored durations.

**How:** The test decodes the session fixture with both interpreters.

**Assumptions:** The durations are whole rasters in both, so they are equal exactly.

#### `test_a_soft_delay_that_the_reader_did_not_attach_is_a_setting_error`

**Checks:** In `valid_soft_delay_fraction.seq` the reader reads the hint `1 TE` (D2.16), so the hint
`TE` raises `SettingError` (interpreter `cpp-siemens`, version 1.5.1) that lists the hint `1 TE`;
`1 TE` = 1 ms gives block 7 1e-3 / 0.5 - 100 us = 1.9 ms; and `1 TE` = 0 a negative duration.

**How:** The test decodes the file under each session.

**Assumptions:** None.

#### `test_the_field_of_view_of_cpp_siemens_is_that_of_spec_where_the_flags_agree`

**Checks:** With `rotation="apply"`, the field of view turned 90 degrees about x and the scaling
(2, 3, 4), `cpp-siemens` gives `spec`'s gradients to float32 precision in blocks 0, 2 and 3, and
other values in blocks 4, 5 and 8, where the flags differ (`NOSLC` dropped by the reader, `NOSCL`
never set back; D2.22, D6.4). Its flags are NOROT in block 3 and NOSCL in blocks 5 to 8, and its
`fov_record` says so. With the default `rotation="reader"`, block 2 is scaled and turned by the
field of view but not by its rotation, and `rotated=True` gives the values of `"apply"`.

**How:** The test samples five times in each of six blocks.

**Assumptions:** None.

#### `test_load_through_cpp_siemens_takes_the_session`

**Checks:** `load(path, "cpp-siemens", session=...)` has the session, 3 soft delays applied, the
scaling flag "NOSCL", and a block table with the decoding's actual durations; it still warns for
the rotation of block 2 that the default leaves unapplied.

**How:** The test loads the session fixture.

**Assumptions:** None.

#### `test_the_points_of_the_played_events_are_the_gradients_of_cpp_siemens_under_a_session`

**Checks:** Under soft delays, and under a field of view, with `rotation="reader"` and `"apply"`,
the played gradients of the session fixture are the decoding's `gradients_at`
(`test_played.check_the_points_are_the_gradients`).

**How:** Parametrized over the two sessions and the two settings; `test_played.load` is replaced
(`monkeypatch`) by `load` with the session.

**Assumptions:** None.
