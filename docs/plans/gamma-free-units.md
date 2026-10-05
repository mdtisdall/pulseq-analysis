# Implementation plan: values with no gamma (0.1.0rc5)

Mode: Strict STE100. Structural rules are enforced. Lexical rules are a
direction of travel, not a verified dictionary match.

Status: draft, not approved. Written on 2026-10-04.

## 1. Scope

Gamma (γ) is the gyromagnetic ratio of the nucleus that the scanner images.
A `.seq` file does not give it. It is data of the target, not of the
sequence. The user's request of 2026-10-04: no value that this package gives
uses or assumes a gamma. Each value is in a unit that the caller can scale
with the gamma of the caller. The documents tell the caller how to do this.

In `0.1.0rc4` and on `main`, two modules use a gamma, and they get it from
two different places (section 2, facts 2 and 3). After this plan, no module
uses a gamma:

| Values | `0.1.0rc4` | `0.1.0rc5` |
|---|---|---|
| `grad_limits`: amplitudes and RMS | mT/m, with the argument `gamma` (default `seq_utils.GAMMA`) | Hz/m |
| `grad_limits`: slew rates and junction steps | T/m/s, with the argument `gamma` | Hz/m/s |
| `pns_levels` and `pns`: PNS values | a fraction of the stimulation limit, with `seq.system.gamma` | Hz/T: the fraction times \|γ\| |
| `pns_levels`: thresholds (an input) | a fraction | Hz/T |
| `grad_spectrum` | Hz/m/√Hz (no gamma since `0.1.0rc4`) | no change |

The rule for the caller is the same for every value: divide the value by
\|γ\| in Hz/T to get the unit with tesla. Section 5.5 gives the text of the
documents.

The measurements do not change. Only the last division by a gamma goes
away, and the names get the new units. Thus the new value divided by \|γ\| is
the old value with that gamma, to the float rounding (section 2, facts 5
and 6).

This plan gives the work in this repository:

| Branch | Result |
|---|---|
| `docs/gamma-free-units-plan` | This plan, and one line for it in `README.md`. No code. |
| `feature/gamma-free-units` | The change, the documents and tag `v0.1.0rc5` (section 6). The release also holds the read-only arrays of `PnsLevels` (#11, U5). |

Section 8 lists the facts for the follow-up work in pulseq-checks and in
pulseq-reports.

### 1.1 Order

```
This plan merged  ->  feature/gamma-free-units  ->  tag v0.1.0rc5
                                                       |
                                                       +->  pulseq-checks: pin v0.1.0rc5, convert in the checks (section 8.1)
                                                       +->  pulseq-reports: pin v0.1.0rc5, convert in the cards (section 8.2)
```

pulseq-checks pins `v0.1.0rc4`, and pulseq-reports pins `v0.1.0rc2`. The
tag `v0.1.0rc5` does not break them, because each keeps its pin until its
own branch changes the pin.

## 2. Context (verified on 2026-10-04)

This repository's `main` is at `910b1fd`. Its version is `0.1.0rc5`, from
#11 (the read-only arrays of `PnsLevels`). The tag `v0.1.0rc5` does not
exist, on `origin` or locally. The last tag is `v0.1.0rc4` (`0afc759`).
pulseq-checks `origin/main` is at `e38bf5c`. pulseq-reports `origin/main` is
at `2a516b4`. The pinned pypulseq is the fork commit `a74ab06`.

1. **The constant.** `seq_utils.py` lines 14 and 15 define
   `GAMMA = 42.576e6` (Hz/T), "the default gamma of `grad_limits`".
   `docs/usage.md` section 4 lists it.
2. **The gamma in this package.**

   | Place | Gamma | What it changes |
   |---|---|---|
   | `grad_limits.py` lines 279, 535 to 556 | the argument `gamma` of `gradient_limits` (default `GAMMA`) | each number of `AxisResult` and `GradientLimits` (mT/m, T/m/s) |
   | `grad_limits.py` lines 703 to 721 | the argument `gamma` of `block_gradient_values` (default `GAMMA`) | each number of `BlockGradientValues` |
   | `analyses.py` lines 138 to 178 | the parameter `gamma` of `gradient.limits` and `gradient.blocks` (default `GAMMA`) | as the two rows above |
   | `pns_levels.py` lines 247, 399 and 410 | `seq.system.gamma`, with no argument | each PNS value: the samples go to the model in T/m |
   | `grad_spectrum.py` | none | nothing (Hz/m/√Hz) |

3. **The two sources do not agree.** For a sequence with
   `seq.system.gamma != GAMMA`, `gradient_limits` without `gamma` uses the ¹H
   gamma, and `pns_levels` uses `seq.system.gamma`. `docs/usage.md` lines 52
   to 56 say that "the `gamma` argument" converts. The documents do not say
   that the PNS model uses `seq.system.gamma`.
4. **pypulseq.** `Opts` stores `max_grad` in Hz/m and `max_slew` in Hz/m/s.
   It converts other units with `abs(gamma)` (`opts.py` lines 92 and 97).
   `Sequence.read` does not set a gamma, so `seq.system.gamma` is the gamma
   of the `Opts` of the sequence object (default 42.576e6).
   `calc_pns` divides the gradients by `obj.system.gamma` (`calc_pns.py`
   line 93), so `seq.calculate_pns` gives fractions.
5. **The gradient values change in proportion to a scale.** A peak is a
   largest `|amplitude|`. A slope is `|b - a| / dt`. A junction step is
   `|step| / grad_raster_time`. An RMS is the root of a mean of squares. A
   vector peak is a largest `|G|`. Thus each value of `c * g` is `|c|` times
   the value of `g`. The code of `main` computes each value in Hz/m and
   divides by the gamma last (fact 2).
6. **The SAFE model changes in proportion to a scale.**
   `_safe_gwf_to_pns_chunk` (`safe_pns_prediction.py` lines 341 to 410)
   takes the difference of the samples, divided by `dt`. Then it runs three
   first-order `lfilter` recursions, takes absolute values, adds them with
   the weights `a1` to `a3`, and divides by `stim_limit`. Each step is linear
   or an absolute value, and the filter state of a chunk changes in the same
   proportion. The total is `sqrt(x^2 + y^2 + z^2)`. Thus the model of
   `c * g` is `|c|` times the model of `g`, to the float rounding. The model
   of `-g` is equal to the model of `g`, bit for bit.
7. **The thresholds must stay in the model pass.** `pns_levels` does not keep
   the totals. It keeps the level: at most `MAX_BINS` bins, 615 samples for
   each bin at a 10 µs raster. A caller cannot find the runs above a
   threshold from the level to the sample. Thus `above` (the runs) comes from
   the same pass as the level.
8. **The tests that use `GAMMA`.** `tests/synthetic.py` (lines 8, 157 and
   158), `tests/oracles/grad_limits.py` (line 26, and the conversions of its
   results), `tests/test_grad_limits.py` (about 40 lines),
   `tests/test_analyses.py` (lines 39 and 200 to 235),
   `tests/test_grad_spectrum.py` (lines 20, 217 and 220) and
   `tests/test_seq_utils.py` (lines 18 and 19). The PNS tests compare values
   with fractions (`1.0`, `0.5`, `peak < 1`) and with `seq.calculate_pns`.
   No test checks which gamma the PNS model uses.
9. **The oracle of `grad_limits`.** `tests/oracles/grad_limits.py` says "Do
   not change it". It imports `GAMMA` from `pulseq_analysis.seq_utils`, and
   it gives mT/m and T/m/s.
10. **pulseq-checks** (`e38bf5c`, pins `v0.1.0rc4`). Its bindings give the
    gradient analyses the gamma of the target (`bindings.py` lines 43 to
    52), and give `pns.safe.levels` the thresholds `(PNS_LIMIT,)` (lines 55
    to 60). Its PNS check reads `levels.peak`, compares it with 1, and makes
    findings from `levels.above[PNS_LIMIT]` (`checks/pns.py` lines 98 to
    143). For a `Sequence` object, its PNS check uses `seq.system.gamma`
    (through `pns_levels`). When the limits come from the profile, its
    gradient checks use the gamma of the profile (`bindings.py` lines 43 to
    48). Then the two checks can use two gammas. Section 8.1 gives the other
    places.
11. **pulseq-reports** (`2a516b4`, pins `v0.1.0rc2`). Six modules import
    `GAMMA` from `pulseq_analysis.seq_utils`. Its principle 8 allows only
    the proton gamma, and `registry.py` line 338 refuses another
    `seq.system.gamma`. Its plan moves to the gamma of each target later.
    Section 8.2 gives the places.
12. **The release-candidate rule.** In the release candidates, the
    specification versions stay 1. An incompatible change edits version 1
    and goes in `CHANGELOG.md` (fact 7 of `docs/plans/series-coordinate.md`).
13. **The names in a series.** A name in a series has a unit suffix only when
    its unit is not the `unit` of the series (decision L3 of
    `docs/plans/series-coordinate.md`). For example, `peak_time_s` has a
    suffix, and the RUNS array `peak` does not.
14. **The read-only level (`0.1.0rc5`).** `level_min` and `level_max` of a
    `PnsLevels` are read-only (`_read_only` in `pns_levels.py`). Three
    examples convert the level to percent with `levels.level_max * 100`.
    This is correct only for fractions. The examples are in the docstring of
    `PnsLevels`, in `docs/usage.md` section 3, and in `CHANGELOG.md` (the
    entry `0.1.0rc5`). The tests `test_the_arrays_of_the_levels_are_read_only`
    and `test_pns_levels_for_shares_a_read_only_result` multiply by 100 only to
    test the read-only arrays.

## 3. Decisions

### 3.1 Decisions of the user

The user approved U1 to U5 on 2026-10-04.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The PNS values (approved on 2026-10-04) | Hz/T: the model runs on the Hz/m samples, so each value is the fraction times \|γ\|. The thresholds are an input in Hz/T (a caller gives the fraction times \|γ\|). The runs above each threshold stay (fact 7). The default is no threshold. | (a) Hz/T with no thresholds: no `above`, no `PnsInterval` and no `pns_above_*` series. The runs of a caller are then only as fine as a level bin (about 6 ms). (b) Fractions, with a `gamma` argument that has no default. |
| U2 | The constant `seq_utils.GAMMA` (approved on 2026-10-04) | Remove it. The package then has no gamma value. The tests and the examples of the documents define their own. | (a) Rename it to `GAMMA_1H`, as a value for callers that no function uses. (b) Keep `GAMMA`. |
| U3 | The names of the values (approved on 2026-10-04) | Each name gets the suffix of its new unit: `_hz_per_m`, `_hz_per_m_per_s` or `_hz_per_t`. The parameter `thresholds` becomes `thresholds_hz_per_t`. Old code then fails with an error, and does not use a value in the wrong unit. | Keep the PNS names (`peak`, `axis_peaks`, `level_min`, `thresholds`) and change only their unit. Then `thresholds=(1.0,)` means 1 Hz/T, and each sample is above it. |
| U4 | The names of the RUNS series (approved on 2026-10-04) | `pns_above_<k>`: `k` is the position of the threshold in `thresholds_hz_per_t`, from 0. `meta["threshold"]` gives the value. | `pns_above_<t>` with `f"{t:g}"` of the Hz/T value, for example `pns_above_4.2576e+07`. A reader then needs γ to find a series. |
| U5 | The release (approved on 2026-10-04) | `0.1.0rc5`, with #11. The version on `main` is `0.1.0rc5` already, and it has no tag. The tag `v0.1.0rc5` goes on the merge commit of `feature/gamma-free-units`. | `0.1.0rc6`, after a tag `v0.1.0rc5` on `910b1fd`. |

### 3.2 Decisions of this plan

These decisions follow from the code or from the decisions of section 3.1.
The approval of this plan approves them.

| # | Decision | Reason |
|---|---|---|
| L1 | The new names are those of the tables of sections 5.1 and 5.2. Only the unit part of a name changes. The field order does not change. | U3. A caller that builds an `AxisResult` by position (pulseq-checks does) changes only the names. |
| L2 | `gradient_limits` and `block_gradient_values` have no `gamma` argument. A call with `gamma=` raises `TypeError`, as for each unknown keyword. There is no deprecation step. | The release candidates have no compatibility promise (fact 12). An error is better than a value in an unexpected unit. |
| L3 | `gradient.limits` and `gradient.blocks` have `params` `()`. Each `spec.version` stays 1. | Fact 12. |
| L4 | `pns_levels` gives the Hz/m samples to the model. It reads no gamma and not `seq.system.gamma`. | U1, fact 6. |
| L5 | `thresholds_hz_per_t` has the default `()`. An empty tuple is valid and gives `above == {}`. The other rules of a threshold do not change. The kept result of `pns_levels_for` has one key for each tuple of `float(t)`, as now. | U1. A default threshold in Hz/T needs a gamma. |
| L6 | `PNS_LIMIT` stays `1.0`, the stimulation limit as a fraction. Its comment gives the limit in Hz/T: `PNS_LIMIT * abs(gamma)`. It is not a default any more. | A fraction does not depend on a gamma. A caller uses it to make a threshold. |
| L7 | The series `pns_total` and `pns_above_<k>` have the unit `"Hz/T"`. Their arrays and their `meta` keys keep their names (`min`, `max`, `peak`, `axis_peaks_x`, `threshold`). Each of these values is in `"Hz/T"`. | Fact 13. The `unit` of the series gives the unit of these values. |
| L8 | `to_series` of `pns.safe.levels` does not raise `ValueError` for two thresholds with one name any more. Names by position cannot be equal. | U4. |
| L9 | The tests define `GAMMA_1H = 42.576e6` (Hz/T) in `tests/synthetic.py`. A test checks that it equals `SYSTEM.gamma`. | U2. The test sequences use the default gamma of pypulseq to convert their mT/m limits (fact 4). |
| L10 | `tests/oracles/grad_limits.py` changes only its imports: `from synthetic import GAMMA_1H as GAMMA`, and the other names from `pulseq_analysis.seq_utils` as now. Its body does not change. | Fact 9. The oracle stays an independent reference in mT/m. |
| L11 | Each comparison with an oracle converts the values of this package first: `1e3 / GAMMA_1H` for an amplitude, `1 / GAMMA_1H` for a slew, and `1 / seq.system.gamma` for a PNS value compared with `seq.calculate_pns`. The tolerances do not change. | These comparisons also test the conversion of section 5.5, as the spectrum test does (L2 of `docs/plans/gradient-spectrum.md`). |
| L12 | A test of the package checks that no module has a name with "gamma" in it, and that no function or method has a parameter with "gamma" in its name. | The request of the user, as a test that a later change cannot break without a failure. |
| L13 | Tests check that the values do not depend on `seq.system.gamma` (exact equality), and that the values of `-g` equal the values of `g` (exact equality). | The first is the request. The second is the reason that the documents say \|γ\| (facts 4 to 6). |
| L14 | No time measurement. | The change removes a division and adds no operation. |
| L15 | `docs/usage.md` gets a new section 8, "Units and gamma". Sections 1 to 7 keep their numbers. Section 7 keeps the spectrum unit and moves its text on gamma to section 8. | pulseq-checks links to the anchor `#5-series-values-for-json`. One section gives the rule for every value. |
| L16 | The arrays of `PnsLevels` stay read-only. The example of the docstring of `PnsLevels` and of `docs/usage.md` section 3 becomes `levels.level_max_hz_per_t / abs(gamma) * 100`, with a `gamma` that the example defines. The entry `0.1.0rc5` of `CHANGELOG.md` uses the new names and this example. The two read-only tests change only the field names. | Fact 14. U5: the entry `0.1.0rc5` describes the release that holds this change. A test of a read-only array does not depend on the unit. |
| L17 | The tag `v0.1.0rc5` is an annotated tag on the merge commit of the PR of `feature/gamma-free-units`. The executing agent shows the command, and pushes the tag only after the user approves. | Decision L9 of `docs/plans/implementation.md`, and U5. |

## 4. How to execute this plan

The workflow is that of `docs/plans/implementation.md` section 4:

1. Start the branch with the `dev-workflow:start-task` skill, from the
   latest `origin/main`. Then run `nix develop --command uv sync --frozen`
   one time in the worktree, before a worker starts.
2. Each test that a task adds or changes gets its `TESTS.md` entry in the
   same PR.
3. Run `nix develop --command scripts/check` before the PR.
4. Show the commit message to the user, and wait for approval before
   `git commit`. Merge only when the user tells you to.
5. The executing agent reviews each worker's diff line by line.
6. When a task finds that this plan is wrong, stop and ask the user.

The tiers M (`worker-medium`), H (`worker-high`) and X (the executing
agent) are those of `docs/plans/implementation.md` section 4.

## 5. The design

### 5.1 `grad_limits`

The names change as in this table. Each docstring and comment uses the new
names and units.

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

The interface:

```python
@dataclass(frozen=True)
class AxisResult:
    peak_hz_per_m: float
    peak_time_s: float
    peak_block: int | None
    max_slew_hz_per_m_per_s: float
    slew_time_s: float
    slew_block: int | None
    rms_hz_per_m: float


@dataclass(frozen=True)
class GradientLimits:
    reason: str | None
    range_s: tuple[float, float]
    axes: dict[str, AxisResult]
    vector_peak_hz_per_m: float
    vector_peak_time_s: float
    vector_peak_block: int | None
    whole_rms_hz_per_m: dict[str, float] | None = None


@dataclass(frozen=True, eq=False)
class BlockGradientValues:
    block_id: np.ndarray
    start_s: np.ndarray
    peak_hz_per_m: dict[str, np.ndarray]
    peak_time_s: dict[str, np.ndarray]
    slew_hz_per_m_per_s: dict[str, np.ndarray]
    slew_time_s: dict[str, np.ndarray]
    junction_hz_per_m_per_s: dict[str, np.ndarray]
    vector_peak_hz_per_m: np.ndarray
    vector_peak_time_s: np.ndarray


def gradient_limits(
    seq: pp.Sequence, *, window: tuple[float, float] | None = None
) -> GradientLimits: ...


def block_gradient_values(seq: pp.Sequence) -> BlockGradientValues: ...
```

Rules of the code:

- Remove each `/ gamma * 1e3` and each `/ gamma` (fact 2). `_whole_file_rms`
  and `_range_result` lose their argument `gamma`. The other arithmetic does
  not change.
- The maximum of each array of `block_gradient_values` stays exactly equal
  to the value of `gradient_limits`. Both functions remove the same
  division.
- The docstring of `gradient_limits` replaces the paragraph on `gamma` with
  this text: "The values are in Hz/m and Hz/m/s, the units of pypulseq,
  with no gamma. To get T/m and T/m/s, divide them by the magnitude of the
  gamma of the target, in Hz/T (`docs/usage.md` section 8)."
  `block_gradient_values` refers to it.
- The module docstring names `vector_peak_hz_per_m`.

### 5.2 `pns_levels` and `pns`

The names change as in this table.

| `0.1.0rc4` | `0.1.0rc5` |
|---|---|
| `PnsLevels.level_min`, `PnsLevels.level_max` | `PnsLevels.level_min_hz_per_t`, `PnsLevels.level_max_hz_per_t` |
| `PnsLevels.peak` | `PnsLevels.peak_hz_per_t` |
| `PnsLevels.axis_peaks` | `PnsLevels.axis_peaks_hz_per_t` |
| `PnsInterval.peak` | `PnsInterval.peak_hz_per_t` |
| `PnsPrediction.peak` | `PnsPrediction.peak_hz_per_t` |
| `PnsPrediction.axis_peaks` | `PnsPrediction.axis_peaks_hz_per_t` |
| the argument `thresholds=(PNS_LIMIT,)` of `pns_levels` and `pns_levels_for` | the argument `thresholds_hz_per_t=()` |

The other fields keep their names: `reason`, `hardware`, `asc_file`, `hw`,
`dt_s`, `num_samples`, `bin_samples`, `peak_time_s`, `on_raster`, `above`,
`start_s`, `end_s` and `num_samples` of `PnsInterval`. The keys of `above`
are the Hz/T thresholds, as `float(t)`.

The interface:

```python
# The stimulation limit of the SAFE model, as a fraction: a fraction of 1 is
# 100 %. A PNS value of this module is the fraction times abs(gamma), in Hz/T,
# so the limit for a gamma is PNS_LIMIT * abs(gamma).
PNS_LIMIT = 1.0


@dataclass(frozen=True)
class PnsInterval:
    start_s: float
    end_s: float
    peak_hz_per_t: float
    peak_time_s: float
    num_samples: int


@dataclass(frozen=True)
class PnsLevels:
    reason: str | None
    hardware: str
    asc_file: str | None
    hw: dict[str, dict[str, float]]
    dt_s: float
    num_samples: int
    bin_samples: int
    level_min_hz_per_t: np.ndarray
    level_max_hz_per_t: np.ndarray
    peak_hz_per_t: float
    peak_time_s: float | None
    axis_peaks_hz_per_t: dict[str, float]
    on_raster: bool
    above: dict[float, tuple[PnsInterval, ...]]


def pns_levels(
    seq: pp.Sequence,
    *,
    gradient_asc: str | Path | None = None,
    hardware: tuple[SimpleNamespace, str] | None = None,
    thresholds_hz_per_t: tuple[float, ...] = (),
) -> PnsLevels: ...
```

`pns.pns_levels_for` has the same new argument and default. `PnsPrediction`
has `reason`, `hardware`, `asc_file`, `peak_hz_per_t`, `peak_time_s` and
`axis_peaks_hz_per_t`, in this order.

Rules of the code:

- Remove `gamma = seq.system.gamma` and the argument `gamma` of
  `_read_block_range` and `_read_sampled_range`. They give the samples in
  Hz/m (L4).
- `_validated_thresholds` accepts the empty tuple (L5). Its other rules and
  their `ValueError` do not change. Each message names
  `thresholds_hz_per_t`.
- `_chunk_total`, `_IntervalFinder`, `_store_bins`, `_cast_outward` and
  `PEAK_TOLERANCE` do not change. Only their docstrings change: the samples
  are in Hz/m, and the totals are in Hz/T.
- The docstring of `pns_levels`, item 1: "The samples are
  `GradientSampler.block_samples` of each axis, in Hz/m. They are not
  divided by a gamma. (`calc_pns` divides them by `seq.system.gamma`.) Thus
  each value is the value of `calc_pns` times the magnitude of
  `seq.system.gamma`, to the float rounding."
- The docstring of `PnsLevels`: "A PNS value is in Hz/T: the fraction of the
  stimulation limit times the magnitude of gamma. Divide it by the
  magnitude of the gamma of the target, in Hz/T, to get the fraction (1 is
  100 %)." The same sentence goes in the module docstrings of `pns_levels.py`
  and `pns.py`, and in `PnsPrediction`. The example of the read-only level
  in the docstring of `PnsLevels` becomes
  `levels.level_max_hz_per_t / abs(gamma) * 100` (L16).
- `scripts/time_pns_levels.py`: the option `--thresholds` becomes
  `--thresholds-hz-per-t`, and the output and the JSON use the new names.

### 5.3 `analyses`

| Analysis | `params` | `compute` |
|---|---|---|
| `gradient.limits` | `()` | `gradient_limits(seq)` |
| `gradient.blocks` | `()` | `block_gradient_values(seq)` |
| `pns.safe.levels` | `("hardware", "thresholds_hz_per_t")` | `pns_levels_for(seq, hardware=hardware, thresholds_hz_per_t=thresholds_hz_per_t)`, defaults `None` and `()` |

`seq.index` and `gradient.spectrum` do not change. Each `spec.version`
stays 1 (L3).

The text of each `spec.description`:

- `gradient.limits` and `gradient.blocks`: "(Hz/m)" and "(Hz/m/s)" in place
  of "(mT/m)" and "(T/m/s)". Replace "`gamma` (Hz/T) converts the values
  from Hz/m." with "The values are in the units of pypulseq, with no gamma.
  Divide them by the magnitude of gamma (Hz/T) to get T/m and T/m/s."
- `pns.safe.levels`: replace "A value is a fraction of the stimulation limit:
  1 is 100 %." with "A value is in Hz/T: the fraction of the stimulation
  limit times the magnitude of gamma. Divide it by the magnitude of gamma
  (Hz/T) to get the fraction (1 is 100 %)." Replace the sentence on
  `thresholds` with "`thresholds_hz_per_t` is a tuple of finite numbers above
  0, in Hz/T, with no two equal. For a fraction f of the limit, give f times
  the magnitude of gamma. The default is `()`: no runs."

The series of `pns.safe.levels`:

| Name | Kind | Unit | Arrays | `meta` |
|---|---|---|---|---|
| `pns_total` | `ENVELOPE` | `"Hz/T"` | `min`, `max`: `level_min_hz_per_t` and `level_max_hz_per_t` (float32) | `hardware`, `asc_file`, `dt_s`, `bin_samples`, `num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y`, `axis_peaks_z` |
| `pns_above_<k>`, one for each threshold, `k` from 0 in the order of `above` | `RUNS` | `"Hz/T"` | `start`, `end`, `num_samples` (int64), `peak`, `peak_time_s` (float64) | `threshold` |

`meta["peak"]`, `meta["axis_peaks_<axis>"]`, the array `peak` and
`meta["threshold"]` are in Hz/T (L7). Their values come from the renamed
fields. With `thresholds_hz_per_t=()`, `to_series` gives `(pns_total,)`.
With `NO_GRADIENTS`, it gives `()`, as now. `spec.series` gives this table
as text. The coordinates do not change.

The module docstring of `analyses.py`: the two gradient analyses have no
parameters, and `pns.safe.levels` has `hardware` and `thresholds_hz_per_t`.
Remove the imports of `GAMMA` and `PNS_LIMIT` when no code uses them.

### 5.4 `seq_utils`

Remove `GAMMA` and its comment (U2). The first line of the module docstring
becomes: "Helpers that read one event of a pypulseq sequence, and the time
tolerance of the measurements."

### 5.5 The documents: the conversion

This text goes in the new section 8 of `docs/usage.md`, "Units and gamma",
in these words or close to them (L15). The module docstrings refer to it.

> No value of this package uses a gamma. Gamma (γ) is the gyromagnetic
> ratio of the nucleus that the scanner images. A `.seq` file does not give
> it: it is data of the target, not of the sequence. pypulseq keeps the
> gradients in Hz/m. Thus the values of this package are in Hz/m, Hz/m/s,
> Hz/m/√Hz and Hz/T.
>
> **The rule.** To get the unit with tesla, divide the value by \|γ\| in
> Hz/T. Each of these values is a magnitude (0 or above), so use the
> magnitude of γ. pypulseq's `Opts` also converts with `abs(gamma)`.
>
> | Values | Unit | Divided by \|γ\| | For ¹H (γ = 42.576 MHz/T) |
> |---|---|---|---|
> | Amplitudes: `AxisResult.peak_hz_per_m`, `AxisResult.rms_hz_per_m`, `GradientLimits.vector_peak_hz_per_m`, `GradientLimits.whole_rms_hz_per_m`, `BlockGradientValues.peak_hz_per_m`, `BlockGradientValues.vector_peak_hz_per_m` | Hz/m | T/m (times 1e3: mT/m) | 1 mT/m is 42 576 Hz/m |
> | Slew rates: `AxisResult.max_slew_hz_per_m_per_s`, `BlockGradientValues.slew_hz_per_m_per_s`, `BlockGradientValues.junction_hz_per_m_per_s` | Hz/m/s | T/m/s | 1 T/m/s is 4.2576 × 10⁷ Hz/m/s |
> | The spectrum: `GradientSpectrum.axes`, `GradientSpectrum.rss`, the series `gradient_spectrum` | Hz/m/√Hz | T/m/√Hz (times 1e3: mT/m/√Hz) | 1 Hz/m/√Hz is 2.3487 × 10⁻⁵ mT/m/√Hz |
> | PNS: `PnsLevels.peak_hz_per_t`, `PnsLevels.axis_peaks_hz_per_t`, `PnsLevels.level_min_hz_per_t`, `PnsLevels.level_max_hz_per_t`, `PnsInterval.peak_hz_per_t`, `PnsPrediction.peak_hz_per_t`, `PnsPrediction.axis_peaks_hz_per_t`, the series `pns_total` and `pns_above_<k>` | Hz/T | the fraction of the stimulation limit (1 is 100 %) | the limit is 4.2576 × 10⁷ Hz/T |
>
> **The thresholds, an input.** `thresholds_hz_per_t` of `pns_levels`,
> `pns_levels_for` and `pns.safe.levels` is in Hz/T. For a fraction f of the
> stimulation limit, give `f * abs(gamma)`. `pns_levels.PNS_LIMIT` is the
> limit as a fraction (1.0). The keys of `PnsLevels.above` and
> `meta["threshold"]` of `pns_above_<k>` are the Hz/T values that you gave.
>
> **The values with no gamma.** The times (each name that ends in `_s`), the
> block IDs, the frequencies (`frequency_hz`), the numbers of samples,
> `PnsLevels.hw` and `PEAK_TOLERANCE` do not change with gamma.
>
> **Why the division is exact.** Each value changes in proportion to a
> scale of the gradients. A peak, a slope and a junction step are
> magnitudes of the Hz/m values. An RMS is the root of a mean of squares.
> The spectrum is linear (section 7). The SAFE model is a sum of linear
> filters and absolute values of the slew, divided by the stimulation limit.
> Thus the value divided by \|γ\| is the value of the same measurement in
> tesla, to the float rounding. The tests compare it with the oracles and
> with pypulseq's `calculate_pns`.
>
> **The limits of a scanner.** Convert the values to the unit of the limits,
> or convert the limits to the unit of the values. pypulseq's `Opts` keeps
> `max_grad` in Hz/m and `max_slew` in Hz/m/s, converted with its own
> gamma. Thus the `Opts` of a target gives limits in the units of the
> values.

The section gives this example:

```python
from pulseq_analysis.grad_limits import gradient_limits
from pulseq_analysis.pns import pns_prediction
from pulseq_analysis.pns_levels import PNS_LIMIT, pns_levels

gamma = 42.576e6  # Hz/T, the gamma of the target: here 1H

limits = gradient_limits(seq)
peak_mt_per_m = limits.axes["x"].peak_hz_per_m / abs(gamma) * 1e3
slew_t_per_m_per_s = limits.axes["x"].max_slew_hz_per_m_per_s / abs(gamma)

fraction = pns_prediction(seq).peak_hz_per_t / abs(gamma)  # 1.0 is the limit

limit_hz_per_t = PNS_LIMIT * abs(gamma)
levels = pns_levels(seq, thresholds_hz_per_t=(limit_hz_per_t,))
runs = levels.above[limit_hz_per_t]  # the runs at or above the limit
```

The arrays of a `GradientSpectrum` and of a `PnsLevels` are read-only. Thus
the section says: convert an array to a new array
(`s.rss / abs(gamma) * 1e3`, `levels.level_max_hz_per_t / abs(gamma) * 100`),
not in place.

## 6. The change

Branch: `feature/gamma-free-units`. Start after this plan merges.

The order: task 6.1, then 6.2, then 6.3, then 6.4. Each of these tasks
changes `TESTS.md` or `analyses.py`, so they do not run at the same time.
Task 6.5 changes only the documents. It can run at the same time as each of
the others. After each of tasks 6.1 to 6.4,
`nix develop --command uv run pytest` passes.

### 6.1 Task 1: the gamma of the tests (tier M)

Files: `tests/synthetic.py`, `tests/oracles/grad_limits.py`,
`tests/test_grad_limits.py`, `tests/test_analyses.py`,
`tests/test_grad_spectrum.py`, `tests/test_seq_utils.py`, `TESTS.md`
sections 2.1 and 2.10.

The behavior does not change in this task. `seq_utils.GAMMA` stays until
task 6.4.

- `tests/synthetic.py`: remove the import of `GAMMA`. Add this constant, and
  use it at lines 157 and 158:

  ```python
  # The gamma of 1H (Hz/T), the default of pypulseq's Opts. The package has no
  # gamma: the tests use this value to convert its values to tesla.
  GAMMA_1H = 42.576e6
  ```

- `tests/oracles/grad_limits.py`: the imports of L10. Nothing else.
- `tests/test_grad_limits.py`, `tests/test_analyses.py` and
  `tests/test_grad_spectrum.py`: import `GAMMA_1H` from `synthetic` in place
  of `GAMMA` from `pulseq_analysis.seq_utils`. Rename each use.
- `tests/test_seq_utils.py`: a new test,
  `test_the_gamma_of_the_tests_is_the_gamma_of_the_test_system`:
  `GAMMA_1H == SYSTEM.gamma == 42.576e6` (L9).
- `TESTS.md`: the entry of the new test in section 2.1. In section 2.10,
  each entry that names `GAMMA` or `seq_utils.GAMMA` names `GAMMA_1H`.

Checks of task 1:

- [ ] `git grep -n "import.*GAMMA" -- tests` finds only `synthetic` imports.
- [ ] `git diff origin/main -- tests/oracles/grad_limits.py` shows only the
      import lines.
- [ ] `nix develop --command uv run pytest` passes.

### 6.2 Task 2: the gradient values in Hz/m (tier H)

After task 1. Files: `src/pulseq_analysis/grad_limits.py`,
`src/pulseq_analysis/analyses.py` (`_GradientLimits`, `_GradientBlocks`, the
module docstring and the imports), `tests/test_grad_limits.py`,
`tests/test_analyses.py` (the gradient parts), `TESTS.md` sections 2.6 and
2.9.

The code: sections 5.1 and 5.3.

Changes to the tests:

| Test or helper | Change |
|---|---|
| Each test that names a field of section 5.1 | The new name. |
| Each expected value with `/ GAMMA_1H * 1e3` or `/ GAMMA_1H` (for example in `test_trapezoid_peak_slew_and_rms_match_hand_computed_values`) | The value in Hz/m or Hz/m/s: remove the conversion. |
| `test_gamma_converts_the_values_with_that_gamma` | Replace with `test_the_values_do_not_depend_on_the_gamma_of_the_system` (below). |
| `test_block_gradient_values_with_gamma_scale_the_values_as_gradient_limits_does` | Remove. The new test covers `block_gradient_values`. |
| `_assert_block_values_agree_with_gradient_limits` | No argument `gamma`. The comparisons stay exact. |
| `_assert_matches_oracle` | Convert the values of this package to mT/m and T/m/s with `GAMMA_1H` before the comparison (L11). The tolerances do not change. The docstring says that this also tests the conversion of `docs/usage.md` section 8. |
| `tests/test_analyses.py`: `_SPECS` | `params` `()` for `gradient.limits` and `gradient.blocks`. |
| `tests/test_analyses.py`: `test_params_name_the_keyword_only_parameters_of_compute` | The defaults `{}` for the two gradient analyses. |
| `tests/test_analyses.py`: `test_compute_gives_the_value_of_its_function_with_the_same_arguments` | No gamma loop. `compute(seq)` of each gradient analysis equals its function with no argument. The arrays use the new names. |

New tests in `tests/test_grad_limits.py`:

- `test_the_values_do_not_depend_on_the_gamma_of_the_system`: one waveform in
  Hz/m (`make_arbitrary_grad` and a trapezoid with an explicit amplitude) in
  two sequences. One sequence uses `SYSTEM`. The other uses a copy of
  `SYSTEM` with `gamma = 0.9 * SYSTEM.gamma`. `gradient_limits` (with and
  without a window) and `block_gradient_values` give exactly equal values.
  The test also checks that the two gammas are not equal (L13).
- `test_the_values_of_a_negated_waveform_are_equal`: the same sequence with
  each amplitude times -1 gives exactly equal values of `gradient_limits`
  and `block_gradient_values` (L13).

`TESTS.md`: the entries of the changed, removed and new tests in sections
2.6 and 2.9. Each entry that names mT/m, T/m/s or `gamma` changes.

Checks of task 2:

- [ ] `git grep -n -E "_mt_per_m|_t_per_m_per_s|gamma" -- src/pulseq_analysis/grad_limits.py`
      finds only the docstring text of section 5.1 on gamma.
- [ ] `nix develop --command uv run pytest` passes.

### 6.3 Task 3: the PNS values in Hz/T (tier H)

After task 2. Files: `src/pulseq_analysis/pns_levels.py`,
`src/pulseq_analysis/pns.py`, `src/pulseq_analysis/analyses.py`
(`_PnsSafeLevels`, the module docstring and the imports),
`scripts/time_pns_levels.py`, `tests/test_pns_levels.py`,
`tests/test_pns.py`, `tests/test_analyses.py` (the PNS parts), `TESTS.md`
sections 2.2, 2.7 and 2.9.

The code: sections 5.2 and 5.3.

Each of the three test files gets this constant, from `GAMMA_1H` of
`synthetic` and `PNS_LIMIT`:

```python
_LIMIT = PNS_LIMIT * GAMMA_1H  # Hz/T: the stimulation limit for 1H
```

Changes to the tests:

| Test or helper | Change |
|---|---|
| Each test that names a field or an argument of section 5.2 | The new name. |
| `_hardware_for_peak(seq, peak)` (`test_pns_levels.py`, `test_analyses.py`) | `peak` stays a fraction of the limit. The factor of the stimulation limit is `pns_levels(seq).peak_hz_per_t / (peak * _LIMIT)`. |
| Each threshold (`1.0`, `0.5`, `0.8`, `1`) and each key of `above` | The same fraction times `_LIMIT`. |
| Each comparison of a PNS value with a fraction (`peak < 1`, `i.peak >= 1`, `total >= 1`, `0 < example.peak < 1`, `p.peak > 1`) | The comparison with the fraction times `_LIMIT`. |
| `test_summary_matches_calculate_pns_within_the_fork_tolerance`, `test_stored_bins_match_calculate_pns_totals`, `test_off_raster_block_falls_back_to_sampling` | Divide the values of `pns_levels` by `seq.system.gamma` before the comparison with `seq.calculate_pns` (L11). The tolerances do not change. |
| `test_no_gradients` (`test_pns_levels.py`) | `levels.above == {}`. |
| `test_no_gradients_gives_an_empty_tuple_for_each_threshold` | The thresholds `(_LIMIT, 0.5 * _LIMIT)`. |
| `test_pns_levels_refuses_bad_thresholds_before_any_work` | Remove the case `empty`. The argument is `thresholds_hz_per_t`. The match stays "threshold". |
| `test_pns_levels_for_keeps_one_result_for_each_tuple_of_thresholds` | The default key is `()`. The other keys are Hz/T values. |
| `test_the_pns_series_equal_the_level_and_the_runs_of_the_same_call` | `thresholds_hz_per_t=(_LIMIT,)`. The names `pns_total` and `pns_above_0`, the unit `"Hz/T"`, and `meta` `{"threshold": _LIMIT}`. |
| `test_the_pns_series_of_two_thresholds_are_in_the_order_of_the_thresholds` | The names are `pns_above_0` and `pns_above_1` for both orders. The swap changes the runs and `meta`, not the names. |
| `test_to_series_refuses_two_thresholds_with_one_series_name` | Remove (L8). |
| `test_to_series_gives_nothing_for_a_sequence_without_gradients` | The tuples `()`, `(_LIMIT,)` and `(_LIMIT, 0.5 * _LIMIT)`. |
| `test_the_pns_series_survive_the_json_round_trip` | The thresholds `(_LIMIT, 0.8 * _LIMIT)`. |
| `_SPECS` and the defaults of `test_params_name_the_keyword_only_parameters_of_compute` | `("hardware", "thresholds_hz_per_t")` and `{"hardware": None, "thresholds_hz_per_t": ()}`. |

New tests in `tests/test_pns_levels.py`:

- `test_the_levels_do_not_depend_on_the_gamma_of_the_system`: one waveform in
  Hz/m in two sequences, with `SYSTEM` and with a copy of `SYSTEM` with
  `gamma = 0.9 * SYSTEM.gamma`. Use hardware for a peak of 1.5 and
  `thresholds_hz_per_t=(_LIMIT,)`, so that `above` is not empty. The two
  results are exactly equal in each field (`_assert_levels_equal` with
  `ignore=()`). The test also checks that the two gammas are not equal.
- `test_the_levels_divided_by_the_gamma_of_the_system_are_the_fractions_of_calculate_pns`:
  for a sequence whose `seq.system.gamma` is `0.9 * SYSTEM.gamma`, the peak,
  the axis peaks and the peak time of `pns_levels`, divided by
  `seq.system.gamma`, equal `seq.calculate_pns` within the fork tolerance.
  This shows that the division uses the gamma of the caller, not 42.576 MHz/T.
- `test_the_levels_of_a_negated_waveform_are_equal`: the same sequence with
  each amplitude times -1 gives exactly equal levels (L13).
- `test_the_default_has_no_thresholds`: `pns_levels(seq).above == {}`, and
  `thresholds_hz_per_t=()` gives the same result.

New test in `tests/test_analyses.py`:

- `test_the_pns_series_without_thresholds_are_the_level_only`: with the
  default thresholds, `to_series` gives one series, `pns_total`.

`scripts/time_pns_levels.py`: section 5.2. Run it one time with
`--blocks 10000 --thresholds-hz-per-t 42576000`.

`TESTS.md`: the entries of the changed, removed and new tests in sections
2.2, 2.7 and 2.9.

Checks of task 3:

- [ ] `git grep -n "system.gamma" -- src` finds nothing.
- [ ] The script run above prints the peak in Hz/T and one count of
      intervals.
- [ ] `nix develop --command uv run pytest` passes.

### 6.4 Task 4: no gamma in the package (tier M)

After task 3. Files: `src/pulseq_analysis/seq_utils.py`,
`tests/test_seq_utils.py`, `tests/test_package.py`, `TESTS.md` sections 2.0
and 2.1.

- `seq_utils.py`: section 5.4.
- `tests/test_seq_utils.py`: rename `test_gamma_and_time_tolerance` to
  `test_time_tolerance`. It checks only `TIME_TOLERANCE`.
- `tests/test_package.py`: a new test, `test_the_package_has_no_gamma` (L12).
  It imports each module of `pulseq_analysis` (`pkgutil.iter_modules`). It
  checks that no module has a name that contains "gamma" (any case). It
  checks each function and each method of each class that the package
  defines (`inspect`, with a `__module__` in `pulseq_analysis`), and finds no
  parameter whose name contains "gamma" (any case).
- `TESTS.md`: the entries of the two tests.

Checks of task 4:

- [ ] `git grep -n -E "\bGAMMA\b" -- src` finds nothing.
- [ ] `nix develop --command uv run pytest` passes.

### 6.5 Task 5: documents and the release (tier H)

At any time. Files: `docs/usage.md`, `README.md`, `CHANGELOG.md`. The
version in `pyproject.toml` is `0.1.0rc5` already (#11), so `pyproject.toml`
and `uv.lock` do not change (U5).

- `docs/usage.md`:
  - The contents: item 8, "Units and gamma".
  - The rule "Units" of the rules for all modules: "No value uses a gamma.
    The gradient values are in Hz/m and Hz/m/s, the spectrum in Hz/m/√Hz,
    and the PNS values in Hz/T. Divide a value by \|γ\| to get the unit with
    tesla (section 8)."
  - Section 2: the signatures and the field tables of section 5.1. Remove
    the text on the default gamma. Add one sentence that links to section 8.
  - Section 3: the signatures and the field tables of section 5.2, the
    rules of `thresholds_hz_per_t` (L5), and `PNS_LIMIT` (L6). Add: the model
    runs on the Hz/m samples and reads no gamma. pypulseq's
    `seq.calculate_pns` divides by `seq.system.gamma`, so it gives fractions.
    The example of the read-only level divides by the `gamma` that it
    defines (L16).
  - Section 4: remove the row `GAMMA`. The module table: "the constant" in
    place of "the constants".
  - Section 6: the table of the analyses (section 5.3), the defaults
    (`hardware=None`, `thresholds_hz_per_t=()`), and the table of the PNS
    series. The paragraph on `<t>` becomes a paragraph on `<k>` (U4). The
    example uses `thresholds_hz_per_t=(PNS_LIMIT * abs(gamma),)` with a
    `gamma` that the example defines.
  - Section 7: keep the unit and the read-only arrays. Move the text on
    gamma to section 8, and link to it. Remove the sentence "`gradient.limits`
    and `gradient.blocks` take `gamma` and give mT/m". The example defines
    its own `gamma`.
  - Section 8 (new): section 5.5.
- `README.md`: the install line stays `@v0.1.0rc5`. The sentence on
  `0.1.0rc5` becomes: "The fifth, `0.1.0rc5`, makes the arrays of a
  `PnsLevels` read-only, and gives each value with no gamma, in the units of
  pypulseq." The example divides `prediction.peak_hz_per_t` by the gamma
  that the example defines, and says that the gamma is that of the nucleus
  of the target.
- `CHANGELOG.md`: the entry `0.1.0rc5` (from #11) gets this change too (U5).
  Its first paragraph names this plan and `docs/usage.md` section 8. Its
  date is the date of the tag.
  - "Changed": the units (the table of section 1), the name tables of
    sections 5.1 and 5.2, the `params` of the three analyses, the default
    `()` of the thresholds, the series unit `"Hz/T"`, and the names
    `pns_above_<k>`. Say that the PNS model does not use
    `seq.system.gamma` any more. Give the rule: divide by \|γ\|. The item
    of #11 on the read-only arrays uses the new names and the example of
    L16.
  - "Removed" (a new heading): `seq_utils.GAMMA`, the argument `gamma` of
    the two gradient functions, and the `ValueError` of `to_series` for two
    thresholds with one name.
  - The item of #11 on the specification version of `pns.safe.levels`
    becomes: each specification version stays 1 (L3).

After the merge, the executing agent tags `v0.1.0rc5` (L17):

```bash
git -C /Users/dylan/dev/pulseq-analysis tag -a v0.1.0rc5 -m "pulseq-analysis 0.1.0rc5" origin/main
```

## 7. Checks of the branch

- [ ] `nix develop --command scripts/check` passes.
- [ ] The command below finds only docstring and document text that tells
      a caller to divide by gamma, or that says why the package has no gamma.
      The executing agent reads each match.

      ```bash
      git grep -n -i -E "gamma|42\.576" -- src docs/usage.md README.md
      ```
- [ ] The command below finds only `tests/oracles/grad_limits.py`, the lines
      that read the fields of the oracle (in `_assert_matches_oracle` and in
      its `TESTS.md` entry), and the old names in `CHANGELOG.md`. The
      executing agent reads each match.

      ```bash
      git grep -n -E "_mt_per_m|_t_per_m_per_s" -- src tests docs/usage.md README.md TESTS.md CHANGELOG.md
      ```
- [ ] `git diff origin/main -- tests/oracles/grad_limits.py` shows only the
      imports (L10).
- [ ] The executing agent writes the JSON of `to_obj` of each series of
      `pns.safe.levels` for `build_repeating(10)` of
      `tests/scale_sequences.py`, with `thresholds_hz_per_t=(PNS_LIMIT *
      GAMMA_1H,)`. The PR description gives this JSON, with each `data`
      abbreviated. pulseq-checks uses it (section 8.1, item 6).
- [ ] CI passes on the PR.

## 8. Facts for the follow-up work

### 8.1 pulseq-checks

pulseq-checks does this work on its own branch, after the tag
`v0.1.0rc5`, with its own plan. Line numbers are at `e38bf5c`.

1. `pyproject.toml` line 13: change `@v0.1.0rc4` to `@v0.1.0rc5`. Then
   `uv lock`.
2. `bindings.py` lines 51, 52, 65 and 66: `gradient.limits` and
   `gradient.blocks` have no parameters now, so they need no arguments. The
   function `gamma(ctx)` (lines 43 to 48) stays. The checks use it to
   convert.
3. `bindings.py` lines 55 to 60: give
   `"thresholds_hz_per_t": (PNS_LIMIT * abs(gamma(ctx)),)`. Then the PNS
   check and the gradient checks use one gamma, `gamma(ctx)`. This removes
   the difference of section 2, fact 10.
4. `checks/gradient.py`: the values are in Hz/m and Hz/m/s. Convert them
   with `gamma(ctx)` before each comparison and each finding (lines 283 to
   307, 416 to 454, 539 to 562), or compare them with `opts.max_grad` and
   `opts.max_slew` (lines 101 to 103), which are in Hz/m and Hz/m/s. The
   finding data can stay in mT/m and T/m/s. The spec text `_GAMMA` (lines 54
   to 59) changes.
5. `checks/pns.py` lines 98 to 143: the fraction is
   `levels.peak_hz_per_t / abs(gamma(ctx))`. The runs are the value of the
   one key of `levels.above`. The percent of a run is
   `100 * interval.peak_hz_per_t / abs(gamma(ctx))`. The spec text (lines 26
   to 30) changes: pulseq-analysis does not divide by a gamma.
6. The series: `pns_above_0` in place of `pns_above_1`
   (`tests/test_run.py` line 805, `tests/test_cli.py` lines 709 and 710),
   the unit `"Hz/T"`, and `docs/usage.md` lines 1010 to 1057 and 1311 to
   1334. The JSON of section 7 is the new example.
7. The tests: the imports of `GAMMA` (`tests/synthetic.py` line 7,
   `tests/test_check_gradient.py` lines 9 and 10), the `AxisResult` that
   `tests/test_check_gradient.py` lines 343 to 351 builds by position (the
   order does not change), and `thresholds == (PNS_LIMIT,)`
   (`tests/test_bindings.py` line 84).
8. `scripts/compare_with_cards.py` lines 422 and 452 call `gradient_limits`
   and read the mT/m fields.
9. The kept result of `pns_levels_for` has one key for each tuple of
   thresholds. Two targets with the same hardware and two gammas run the
   model two times. In `0.1.0rc4`, they ran it one time.

### 8.2 pulseq-reports

pulseq-reports does this work in its own plans. It pins `v0.1.0rc2`, and its
"Phase 2b" moves the pin to `v0.1.0rc4`. It can move to `v0.1.0rc5` instead.
Line numbers are at `2a516b4`.

1. Define its own proton gamma (principle 8) in place of the imports of
   `GAMMA`: `registry.py` line 22, `targets.py` line 14, `diagram_data.py`
   line 18, `waveforms.py` line 19, `rf_exposure.py` line 24,
   `cards/diagram.py` lines 29 to 31, and the tests.
2. `cards/gradient_limits.py` line 152: convert the Hz/m and Hz/m/s values
   with the proton gamma. Lines 74 to 118 use the new names.
3. `cards/pns.py` lines 35 to 42: `100 * p.peak_hz_per_t / GAMMA` and the same
   for each axis peak.
4. `cards/diagram.py` lines 49 to 69: the level and the peaks are in Hz/T.
   The card divides them by the gamma that its PNS lane uses. `gradScale`
   (line 61) exists because pulseq-analysis divided by `seq.system.gamma`.
   pulseq-analysis does not do this now. The Python level and the lane of
   the browser must use one gamma.
5. `TODO.md` lines 118 to 131 (the places that change Hz into T): after
   `v0.1.0rc5`, pulseq-analysis changes nothing into T. Thus add the PNS
   card, the PNS entry of the diagram and the gradient limits card. Each
   converts in pulseq-reports.
6. The planned PNS card and lane read `pns_above_0`, in Hz/T, and the
   binding gives `thresholds_hz_per_t`.

## 9. Later

- **One PNS result for all the gammas of one hardware** (section 8.1, item
  9). The runs need the totals or a second pass of the model (fact 7), so
  this is not simple. Do it only if a user needs it.
- **pypulseq.** `calculate_pns` of pypulseq still divides by
  `seq.system.gamma` (fact 4). This package does not call it outside the
  tests.
