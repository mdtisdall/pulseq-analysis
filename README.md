# pulseq-analysis

`pulseq-analysis` gives derived values of a [Pulseq](https://pulseq.github.io/)
sequence: the block table, the gradient amplitude and slew, the SAFE PNS
prediction and the gradient spectrum. An *analysis* takes a sequence and
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

## Install

The documents (`docs/usage.md` and `docs/implementation.md`) describe `main`.
The tag `v0.1.0rc5` of the install line below has an older interface: for
example, it has no `gradient_peaks`, `hardware_from_asc` or `gradient_sampler`,
and `pns_levels` has no `bin_s` argument. The next release replaces this note
and the tag.

With uv, from the git URL:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@v0.1.0rc5"
```

The package needs pypulseq 1.5.0.post1 with six commits that are not in a
release. `pyproject.toml` pins them from a fork in `[tool.uv.sources]`. uv
applies this pin for a project that depends on `pulseq-analysis` by git URL.
pip does not.

## Example

The SAFE PNS peak of a `.seq` file:

```python
import pypulseq as pp

from pulseq_analysis.asc import hardware_from_asc
from pulseq_analysis.pns_levels import pns_levels

gamma = 42.576e6  # Hz/T: the gamma of the nucleus of the target, here 1H

seq = pp.Sequence()
seq.read("sequence.seq")
hardware = hardware_from_asc("MP_GPA_K2309_2250V_951A_AS82.asc")
levels = pns_levels(seq, hardware=hardware)
fraction = levels.peak_hz_per_t / abs(gamma)
print(f"{fraction:.0%} of the stimulation limit at {levels.peak_time_s:.4f} s")
```

The hardware is necessary: the model has no default. It is a pair of the
SAFE parameters and a name. `hardware_from_asc` reads the Siemens gradient
`.asc` file of the scanner. For pypulseq's example hardware, which is not a
real scanner, pass `hardware=(safe_example_hw(), "a label")`
(`safe_example_hw` is in `pypulseq.utils.safe_pns_prediction`).
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
