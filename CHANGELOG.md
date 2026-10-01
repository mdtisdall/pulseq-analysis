# Changelog

Each version of `pulseq-analysis` has an entry here. The version numbers
follow [PEP 440](https://peps.python.org/pep-0440/).

## 0.1.0rc1 (2026-10-01)

The first release candidate. The measurement modules move from pulseq-checks
`0.1.0rc2` (`docs/plans/pulseq-analysis.md` of pulseq-checks, tasks 1.2 and
1.3), with the package name `pulseq_analysis`. pulseq-checks pins this tag for
its phase 2.

### Added

- The modules `asc`, `extensions`, `grad_limits`, `pns`, `pns_levels`,
  `sampling`, `seq_index` and `seq_utils`, from pulseq-checks `0.1.0rc2`, with
  their tests. Their interface is in `docs/usage.md`.

### Removed

- `pns_levels.SAFE_MODEL` and `pns_levels.hw_from_dict`, the model `pns.safe`
  of the target profile of pulseq-checks. They stay in pulseq-checks.
  `pns_levels.SAFE_FIELDS` stays in this package.
