# pulseq-analysis

`pulseq-analysis` gives derived values of a [Pulseq](https://pulseq.github.io/)
sequence: the block table, the gradient amplitude and slew, the SAFE PNS
prediction and the gradient spectrum. An *analysis* takes a snapshot of a sequence (`load` makes it) and
explicit physical parameters, and gives a series (for example in time or in
frequency) or a summary. An analysis does not change the
sequence. It has no target profile, no limit, no pass or fail and no finding.
[pulseq-checks](https://github.com/mdtisdall/pulseq-checks) uses these values
to check a sequence against the limits of a scanner.

The package is in development. The first release candidate, `0.1.0rc1`, has
the modules of pulseq-checks `0.1.0rc2`. The second, `0.1.0rc2`, adds the
analyses and their registry, and `Series`, the form of a value for JSON.
The third, `0.1.0rc3`, gives each series a coordinate unit, so that a series
can be in seconds or in hertz.
The fourth, `0.1.0rc4`, adds the gradient spectrum and the analysis
`gradient.spectrum`.
The fifth, `0.1.0rc5`, makes the arrays of a `PnsLevels` read-only, compares
a `PnsLevels` and a `GradientSpectrum` by value, and gives each value with no
gamma, in the units of pypulseq.
The sixth, `0.1.0rc6`, has the work of four review plans. It fixes the
findings of the reviews of 2026-10-04 to 2026-10-07 and changes the interface:
`gradient_limits` becomes `gradient_peaks`, the PNS hardware is a necessary
pair, `pns_levels` takes the argument `bin_s`, the report helpers go to
pulseq-reports, and results are read-only and compare by value. The last plan
adds the snapshot step: `load` makes a `Snapshot` of a `.seq` file or of a
`Sequence`, and each measurement takes a `Snapshot`. It also adds
`registry(strict=False)`, the argument `max_bytes` of `Series.from_obj` and the
key `"format"` of a `Series`, and removes `block_cache_off`.

## Install

The documents (`docs/usage.md` and `docs/implementation.md`) describe `main`.
The tag `v0.1.0rc6` of the install line below has an older interface: its
`load` is `pulseq_analysis.snapshot.load`, it reads with pypulseq, it refuses a
sequence with no `[SIGNATURE]` hash, and it has `extensions.refuse_unsigned`.
The next release replaces this note and the tag.

With uv, from the git URL:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@v0.1.0rc6"
```

The tag `v0.1.0rc6` needs pypulseq 1.5.0.post1 with six commits that are not
in a release. `pyproject.toml` pins them from a fork in `[tool.uv.sources]`.
uv applies this pin for a project that depends on `pulseq-analysis` by git
URL. pip does not. On `main`, pypulseq is optional: the package does not
import it, and it is the extra `pypulseq` (`pulseq-analysis[pypulseq]`), which
uv resolves to the same fork.

On `main`, `read_seqfile` takes the interpreter `spec` (the default, as true as
possible to the Pulseq specification) and the interpreters that other
distributions add as plugins. The distribution pulseq-cpp-siemens
(`packages/pulseq-cpp-siemens/`) adds `cpp-siemens`, which runs the C++ reader
of the scanner. pulseq-analysis has no dependency on it, in its code or in its
metadata. To use `cpp-siemens`, install both distributions:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@main" "pulseq-cpp-siemens @ git+https://github.com/mdtisdall/pulseq-analysis@main#subdirectory=packages/pulseq-cpp-siemens"
```

uv builds pulseq-cpp-siemens from source: this needs a C++ compiler and the
network (CMake fetches the reader's files from pulseq/pulseq). How a release
of pulseq-cpp-siemens depends on pulseq-analysis is decided at release time.

## Example

The SAFE PNS peak of a `.seq` file:

```python
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.asc import hardware_from_asc
from pulseq_analysis.analyses.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T: the gamma of the nucleus of the target, here 1H

snap = load("sequence.seq")  # through `spec`; load(seq) for a pypulseq Sequence
hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")
levels = pns_levels(snap, hardware=hardware)
fraction = levels.peak_hz_per_t / abs(gamma)
print(f"{fraction:.0%} of the stimulation limit at {levels.peak_time_s:.4f} s")
```

The hardware is necessary: the model has no default. It is a pair of the
SAFE parameters and a name. `hardware_from_asc` reads the Siemens gradient
`.asc` file of the scanner. For pypulseq's example hardware, which is not a
real scanner, pass `hardware=(safe_example_hw(), "a label")`
(`safe_example_hw` is in `pypulseq.utils.safe_pns_prediction`, so it needs the
extra `pypulseq`).
The PNS values are in Hz/T, so the example divides the peak by |γ| to get the
fraction of the stimulation limit.
[`docs/usage.md`](docs/usage.md) shows the other tasks and values.

## Documents

- [`docs/usage.md`](docs/usage.md): the guide. How to use the package for
  its main tasks, and the interface of its modules.
- [`docs/implementation.md`](docs/implementation.md): the exact definitions,
  the rules for the rare cases of the gradient waveform, and the algorithms
  and the cost of each call.
- [`TESTS.md`](TESTS.md): each check that CI runs.
- [`docs/plans/implementation.md`](docs/plans/implementation.md): the
  implementation plan.
- [`docs/plans/series-coordinate.md`](docs/plans/series-coordinate.md): the
  plan of the coordinate unit of a series (`0.1.0rc3`).
- [`docs/plans/gradient-spectrum.md`](docs/plans/gradient-spectrum.md): the
  plan of the gradient spectrum analysis (`0.1.0rc4`).
- [`docs/plans/gamma-free-units.md`](docs/plans/gamma-free-units.md): the
  plan of the values with no gamma (`0.1.0rc5`).
- [`docs/reviews/2026-10-04-code-review.md`](docs/reviews/2026-10-04-code-review.md):
  a review of the code at `0.1.0rc5`, with the findings to fix.
- [`docs/plans/review-fixes.md`](docs/plans/review-fixes.md): the plan of
  the fixes of that review (`0.1.0rc6`).
- [`docs/reviews/2026-10-05-code-review.md`](docs/reviews/2026-10-05-code-review.md):
  a review of the code after those fixes.
- [`docs/plans/second-review-fixes.md`](docs/plans/second-review-fixes.md):
  the plan of the fixes of that second review (`0.1.0rc6`).
- [`docs/reviews/2026-10-06-code-review.md`](docs/reviews/2026-10-06-code-review.md):
  a review of the code after the fixes of that plan, before the release
  `0.1.0rc6`.
- [`docs/plans/third-review-fixes.md`](docs/plans/third-review-fixes.md):
  the plan of the fixes of that third review (`0.1.0rc6`).
- [`docs/reviews/2026-10-07-code-review.md`](docs/reviews/2026-10-07-code-review.md):
  a review of the code after the fixes of the third plan.
- [`docs/plans/fourth-review-fixes.md`](docs/plans/fourth-review-fixes.md):
  the plan of the fixes of that fourth review, and of the snapshot step
  (`0.1.0rc6`).
- [`docs/plans/load-accepts-unsigned.md`](docs/plans/load-accepts-unsigned.md):
  the plan by which `load` accepts a sequence with no `[SIGNATURE]` hash, and
  `refuse_unsigned` is removed (for `0.1.0rc7`).
- [`docs/plans/explicit-sourcing.md`](docs/plans/explicit-sourcing.md):
  the plan of the rule "explicit inputs", the rejection of a file before
  Pulseq 1.4, the documented source of each input of pypulseq, and the drift
  tests.
- [`docs/plans/own-parser-study.md`](docs/plans/own-parser-study.md):
  the study of an own strict parser of Pulseq files in place of pypulseq's
  `read`, and of the language of the package. Decided: option B, in Python.
- [`docs/plans/own-parser.md`](docs/plans/own-parser.md): the plan of option
  B: the own parser, the model of layer 1, and pypulseq as an optional
  extra.
- [`docs/plans/own-parser-tasks.md`](docs/plans/own-parser-tasks.md): the
  implementation plan of tasks 2, 4, 5a, 5b and 6 of that plan: the event
  types, the converter, `load` on the model, pypulseq as an extra, and the
  MATLAB oracle under Octave. R15 and R14 of
  `docs/plans/parser-redesign.md` replaced its tasks 4 and 5a.
- [`docs/plans/parser-redesign.md`](docs/plans/parser-redesign.md): the plan of
  the two interpreters (`spec` and `cpp-siemens`), the plugin protocol, the
  scanner session, and the findings for pulseq-checks in place of checks.
- [`docs/plans/cpp-siemens-review-fixes.md`](docs/plans/cpp-siemens-review-fixes.md):
  the plan of the fixes of three bugs of `cpp-siemens` that the review of
  2026-10-13 found, each with tests that fail before the fix.
- [`docs/specification.md`](docs/specification.md): what the interpreter `spec`
  does and why, rule by rule, with the codes of its rejections.
- [`docs/discrepancies.md`](docs/discrepancies.md): the record of where the
  specification is unclear or silent and what `spec` does, entry by entry, with
  the sources.
- [`docs/findings-for-pulseq-checks.md`](docs/findings-for-pulseq-checks.md):
  the public readings that pulseq-checks compares to find where the
  interpreters and the file differ, and how.
- [`docs/migration.md`](docs/migration.md): from `0.1.0rc6` to `0.1.0rc7`, for
  pulseq-checks and pulseq-reports.
- [`CHANGELOG.md`](CHANGELOG.md): the changes of each version.
- [`packages/pulseq-cpp-siemens/README.md`](packages/pulseq-cpp-siemens/README.md):
  the distribution pulseq-cpp-siemens, the C++ reader of the scanner as the
  interpreter `cpp-siemens`.
- [`packages/pulseq-cpp-siemens/docs/specification.md`](packages/pulseq-cpp-siemens/docs/specification.md):
  what `cpp-siemens` does and why: its rule, and each exception.
