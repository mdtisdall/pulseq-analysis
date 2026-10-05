# Changelog

Each version of `pulseq-analysis` has an entry here. The version numbers
follow [PEP 440](https://peps.python.org/pep-0440/).

## 0.1.0rc5 (2026-10-04)

The fifth release candidate: values with no gamma
(`docs/plans/gamma-free-units.md`), and read-only arrays in `PnsLevels`, an
item of section 9 of `docs/plans/gradient-spectrum.md`. `pns_levels_for` gives
its kept result to each caller, as `gradient_spectrum_for` does (decision L12
of that plan). `PnsLevels` and `GradientSpectrum` compare by value. No value
of the package uses a gamma now. Section 8 of `docs/usage.md` gives the
conversion.

### Changed

- **The units.** Each value is in a unit that needs no gamma:

  | Values | `0.1.0rc4` | `0.1.0rc5` |
  |---|---|---|
  | `grad_limits`: amplitudes and RMS | mT/m, with the argument `gamma` (default `seq_utils.GAMMA`) | Hz/m |
  | `grad_limits`: slew rates and junction steps | T/m/s, with the argument `gamma` | Hz/m/s |
  | `pns_levels` and `pns`: PNS values | a fraction of the stimulation limit, with `seq.system.gamma` | Hz/T: the fraction times \|γ\| |
  | `pns_levels`: thresholds (an input) | a fraction | Hz/T |
  | `grad_spectrum` | Hz/m/√Hz | no change |

  The measurements do not change. Only the last division by a gamma goes
  away. The PNS model does not use `seq.system.gamma` any more: it runs on the
  Hz/m samples. The rule for the caller is the same for every value: divide
  the value by |γ| in Hz/T to get the unit with tesla. The result is the old
  value for that gamma, to the float rounding. pypulseq's
  `seq.calculate_pns` still divides by `seq.system.gamma`, so it gives
  fractions.
- **The names of `grad_limits`.** Only the unit part of a name changes. The
  field order does not change.

  | `0.1.0rc4` | `0.1.0rc5` |
  |---|---|
  | `AxisResult.peak_mt_per_m` | `AxisResult.peak_hz_per_m` |
  | `AxisResult.max_slew_t_per_m_per_s` | `AxisResult.max_slew_hz_per_m_per_s` |
  | `AxisResult.rms_mt_per_m` | `AxisResult.rms_hz_per_m` |
  | `GradientLimits.vector_peak_mt_per_m` | `GradientLimits.vector_peak_hz_per_m` |
  | `GradientLimits.whole_rms_mt_per_m` | `GradientLimits.whole_rms_hz_per_m` |
  | `BlockGradientValues.peak_mt_per_m` | `BlockGradientValues.peak_hz_per_m` |
  | `BlockGradientValues.slew_t_per_m_per_s` | `BlockGradientValues.slew_hz_per_m_per_s` |
  | `BlockGradientValues.junction_t_per_m_per_s` | `BlockGradientValues.junction_hz_per_m_per_s` |
  | `BlockGradientValues.vector_peak_mt_per_m` | `BlockGradientValues.vector_peak_hz_per_m` |
  | `gradient_limits(seq, *, window=None, gamma=GAMMA)` | `gradient_limits(seq, *, window=None)` |
  | `block_gradient_values(seq, *, gamma=GAMMA)` | `block_gradient_values(seq)` |

- **The names of `pns_levels` and `pns`.** The fields get the unit of the
  new value, and the argument `thresholds` becomes `thresholds_hz_per_t`. The
  other fields keep their names. The keys of `above` are the Hz/T thresholds.

  | `0.1.0rc4` | `0.1.0rc5` |
  |---|---|
  | `PnsLevels.level_min`, `PnsLevels.level_max` | `PnsLevels.level_min_hz_per_t`, `PnsLevels.level_max_hz_per_t` |
  | `PnsLevels.peak` | `PnsLevels.peak_hz_per_t` |
  | `PnsLevels.axis_peaks` | `PnsLevels.axis_peaks_hz_per_t` |
  | `PnsInterval.peak` | `PnsInterval.peak_hz_per_t` |
  | `PnsPrediction.peak` | `PnsPrediction.peak_hz_per_t` |
  | `PnsPrediction.axis_peaks` | `PnsPrediction.axis_peaks_hz_per_t` |
  | the argument `thresholds=(PNS_LIMIT,)` of `pns_levels` and `pns_levels_for` | the argument `thresholds_hz_per_t=()` |

  The default of `thresholds_hz_per_t` is `()`. An empty tuple is valid and
  gives `above == {}`. The other rules of a threshold do not change. For a
  fraction f of the stimulation limit, give `f * abs(gamma)`. `PNS_LIMIT`
  stays 1.0, the limit as a fraction. It is not a default any more.
- **The analyses.** `gradient.limits` and `gradient.blocks` have no
  parameters. The parameters of `pns.safe.levels` are `hardware` and
  `thresholds_hz_per_t` (defaults `None` and `()`). The descriptions of the
  three analyses give the new units.
- **The series of `pns.safe.levels`.** The series `pns_total` and
  `pns_above_<k>` have the unit `"Hz/T"`. `<k>` is the position of the
  threshold in `thresholds_hz_per_t`, from 0: the names were `pns_above_<t>`,
  with `f"{t:g}"` of the threshold. The arrays and the `meta` keys keep their
  names, and their values are in Hz/T. `meta["threshold"]` gives the
  threshold. With no thresholds, `to_series` gives only `pns_total`.
- `level_min_hz_per_t` and `level_max_hz_per_t` of a `PnsLevels` are
  read-only, also for `NO_GRADIENTS` and also in the result of `pns_levels`. A
  change in place (for example `levels.level_max_hz_per_t *= 100`) raises
  `ValueError`. Convert to a new array
  (`levels.level_max_hz_per_t / abs(gamma) * 100`).
- The documents say that a caller must not change the dicts `hw`,
  `axis_peaks_hz_per_t` and `above`. Before, they said this only for `above`.
  The dicts stay plain dicts.
- **Equality.** `PnsLevels` and `GradientSpectrum` compare by value, as
  `Series` does. `==` compares each field: an array by its dtype, its shape
  and its values (a NaN equals a NaN, and the read-only flag does not count),
  and a dict with its keys in order. Before, `==` of two `PnsLevels` raised
  `ValueError` when the level had more than one bin, and `==` of two
  `GradientSpectrum` objects was true only for one object. Neither is
  hashable: before, a `GradientSpectrum` was hashable by identity.
- Each specification version stays 1 (decision L3 of the plan). In the
  release candidates, an incompatible change edits version 1.

### Removed

- `seq_utils.GAMMA`. The package has no gamma value.
- The argument `gamma` of `gradient_limits` and `block_gradient_values`, and
  the parameter `gamma` of `gradient.limits` and `gradient.blocks`. A call of
  either function with `gamma=` raises `TypeError`.
- The `ValueError` of `to_series` of `pns.safe.levels` for two thresholds
  with one series name. The names are by position, so no two are equal.

## 0.1.0rc4 (2026-10-04)

The fourth release candidate: the gradient spectrum
(`docs/plans/gradient-spectrum.md`). The module moves from pulseq-reports
(`src/pulseq_reports/grad_spectrum.py` at `cc87563`). It is the first analysis
that uses the coordinate unit of `0.1.0rc3`.

### Added

- **`grad_spectrum`**: `gradient_spectrum`, `gradient_spectrum_for`,
  `GradientSpectrum` and `NO_GRADIENTS`. The functions take the keyword
  arguments `max_frequency_hz`, `window_s` and `frequency_oversampling`, with
  the defaults of pypulseq's `calculate_gradient_spectrum`.
  `gradient_spectrum_for` keeps the result for each sequence object and each
  set of arguments. The arrays of a `GradientSpectrum` are read-only.
  `gradient_spectrum` raises `NotImplementedError` for a file with the
  rotation extension.
- The analysis `gradient.spectrum`, with no parameters, and its series
  `gradient_spectrum` (`SAMPLES`, coordinate unit `"Hz"`). Its arrays are
  `value` (the RSS), `x`, `y` and `z`.
- The values are in Hz/m/√Hz, with no gamma. To get mT/m/√Hz for a gamma γ in
  Hz/T, multiply each value by `1e3 / γ`. The module has no resonance bands,
  unlike the module of pulseq-reports. The bands are data of the target.

### Changed

- `scipy` is a runtime dependency. It was a dev dependency. pypulseq installs
  it already, so no new package comes in.

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
