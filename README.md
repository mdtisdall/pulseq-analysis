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
The fifth, `0.1.0rc5`, makes the arrays of a `PnsLevels` read-only.

## Install

With uv, from the git URL:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis@v0.1.0rc5"
```

The package needs pypulseq 1.5.0.post1 with four commits that are not in a
release. `pyproject.toml` pins them from a fork in `[tool.uv.sources]`. uv
applies this pin for a project that depends on `pulseq-analysis` by git URL.
pip does not.

## Example

The SAFE PNS peak of a `.seq` file:

```python
import pypulseq as pp

from pulseq_analysis.pns import pns_prediction

seq = pp.Sequence()
seq.read("sequence.seq")
prediction = pns_prediction(seq, gradient_asc="MP_GPA_K2309_2250V_951A_AS82.asc")
print(f"{prediction.peak:.0%} of the stimulation limit at {prediction.peak_time_s:.4f} s")
```

`gradient_asc` is the Siemens gradient `.asc` file of the scanner. Without
it, the model uses pypulseq's example hardware, which is not a real scanner.
[`docs/usage.md`](docs/usage.md) gives the other values and modules.

## Documents

- [`docs/usage.md`](docs/usage.md): the modules and their interface.
- [`TESTS.md`](TESTS.md): each check that CI runs.
- [`docs/plans/implementation.md`](docs/plans/implementation.md): the
  implementation plan.
- [`docs/plans/series-coordinate.md`](docs/plans/series-coordinate.md): the
  plan of the coordinate unit of a series (`0.1.0rc3`).
- [`docs/plans/gradient-spectrum.md`](docs/plans/gradient-spectrum.md): the
  plan of the gradient spectrum analysis (`0.1.0rc4`).
- [`docs/plans/gamma-free-units.md`](docs/plans/gamma-free-units.md): the
  plan of the values with no gamma (`0.1.0rc5`).
