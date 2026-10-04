# Changelog

Each version of `pulseq-analysis` has an entry here. The version numbers
follow [PEP 440](https://peps.python.org/pep-0440/).

## 0.1.0rc3 (2026-10-04)

The third release candidate: the coordinate unit of a series
(`docs/plans/series-coordinate.md`). Each `Series` has a coordinate with its
own unit, so that a series can be in seconds or in hertz.

### Changed

- The names of `Series` change:

  | `0.1.0rc2` | `0.1.0rc3` |
  |---|---|
  | none | field `coord_unit` (new) |
  | field `t0_s` | field `coord_start` |
  | field `step_s` | field `coord_step` |
  | field `end_s` | field `coord_end` |
  | `POINTS` array `time_s` | `POINTS` array `coord` |
  | `RUNS` arrays `start_s`, `end_s` | `RUNS` arrays `start`, `end` |

- `coord_unit` is a new field. It is required and has no default. It is a
  string and it is not empty. The keys of `Series.to_obj` are `name`, `kind`,
  `unit`, `coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta` and
  `arrays`.
- The series of `pns.safe.levels` have `coord_unit` `"s"` and the new names.
  The `RUNS` arrays of `pns_above_<t>` are `start`, `end`, `num_samples`,
  `peak` and `peak_time_s`. `peak_time_s` and the `meta` keys `dt_s` and
  `peak_time_s` keep their names.
- `Series.from_obj` does not read a series object of `0.1.0rc2`. It raises
  `ValueError`, because `t0_s` is an unknown key.
- The specification version of `pns.safe.levels` stays 1. In the release
  candidates, an incompatible change edits version 1.

## 0.1.0rc2 (2026-10-01)

The second release candidate: phase 3 of `docs/plans/pulseq-analysis.md` of
pulseq-checks (`docs/plans/implementation.md`, section 8). pulseq-checks pins
this tag for its phase 4. The time of `pns_levels` on 10^6 blocks does not
change: 9.34 s with the default threshold, 9.47 s with three thresholds, and
9.47 s before (`docs/plans/implementation.md`, section 9).

### Added

- **`series`**: `Series` and `SeriesKind` (`SAMPLES`, `ENVELOPE`, `POINTS`,
  `RUNS`), the form of a value that can go into JSON, with `to_obj` and
  `from_obj`. `encode_array` and `decode_array` give an array as the text of
  `encode_tables` of pulseq-reports (gzip and base64).
- **`analyses`**: `AnalysisSpec`, the `Analysis` protocol, the entry-point
  group `pulseq_analysis.analyses`, `registry()` and `RegistryError`. The
  analyses `seq.index`, `gradient.limits`, `gradient.blocks` and
  `pns.safe.levels`, with their entry points. `pns.safe.levels` gives the
  series `pns_total` (the level) and `pns_above_<t>` (the runs above each
  threshold).
- **`thresholds`**: an argument of `pns_levels.pns_levels` and
  `pns.pns_levels_for`, default `(PNS_LIMIT,)`. The runs of all the
  thresholds are found in one pass.

### Changed

- `PnsLevels.above_limit` is replaced by `PnsLevels.above`, a dict from each
  threshold to its runs. `above_limit` is `above[1.0]` (`above[PNS_LIMIT]`).
- The kept result of `pns_levels_for` is keyed by the hardware and the
  thresholds.

### Removed

- `grad_limits.HardwareLimits`, the `limits` argument of `gradient_limits`
  and the field `GradientLimits.limits`. The numbers did not depend on them.
  A caller that has the limits of a scanner compares the values with them;
  pulseq-checks keeps `HardwareLimits` (decision T4 of its plan).

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
