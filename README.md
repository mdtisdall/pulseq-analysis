# pulseq-analysis

`pulseq-analysis` gives derived values of a [Pulseq](https://pulseq.github.io/)
sequence: the block table, the gradient amplitude and slew, and the SAFE PNS
prediction. An *analysis* takes a sequence and explicit physical parameters,
and gives a time series or a summary. An analysis does not change the
sequence. It has no target profile, no limit, no pass or fail and no finding.
[pulseq-checks](https://github.com/mdtisdall/pulseq-checks) uses these values
to check a sequence against the limits of a scanner.

The package is in development. The modules come from pulseq-checks in the
first release candidate.

## Install

With uv, from the git URL:

```
uv add "pulseq-analysis @ git+https://github.com/mdtisdall/pulseq-analysis"
```

The package needs pypulseq 1.5.0.post1 with four commits that are not in a
release. `pyproject.toml` pins them from a fork in `[tool.uv.sources]`. uv
applies this pin for a project that depends on `pulseq-analysis` by git URL.
pip does not.

## Documents

- [`docs/usage.md`](docs/usage.md): the modules and their interface (from the
  first release candidate).
- [`TESTS.md`](TESTS.md): each check that CI runs.
- [`docs/plans/implementation.md`](docs/plans/implementation.md): the
  implementation plan.
