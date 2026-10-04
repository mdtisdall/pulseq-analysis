# Implementation plan: the coordinate unit of a series (0.1.0rc3)

Mode: Strict STE100. Structural rules are enforced. Lexical rules are a
direction of travel, not a verified dictionary match.

Status: draft, not approved. Written on 2026-10-04.

## 1. Scope

In `0.1.0rc2`, each kind of `Series` puts its values on a time axis. The
fields `t0_s`, `step_s` and `end_s`, the `POINTS` array `time_s` and the
`RUNS` arrays `start_s` and `end_s` are in seconds. Thus a series cannot
hold a spectrum or a band of frequencies.

This plan gives each series a *coordinate* with its own unit. The
coordinate is the quantity of the horizontal axis of the series: the time
for a waveform, the frequency for a spectrum, the position for a slice
profile. The four kinds do not change. They describe a shape of data, and
the shape does not depend on the quantity of the coordinate:

| Data | Kind | `coord_unit` |
|---|---|---|
| The SAFE PNS level (now) | `ENVELOPE` | `"s"` |
| The runs above a PNS threshold (now) | `RUNS` | `"s"` |
| A gradient spectrum (later) | `SAMPLES` | `"Hz"` |
| The acoustic resonance bands (later) | `RUNS` | `"Hz"` |
| The peak of each resonance band (later) | `POINTS` | `"Hz"` |
| A 1D RF profile along a position (later) | `SAMPLES` | `"m"` |
| A 1D RF profile along the frequency offset (later) | `SAMPLES` | `"Hz"` |

The rows "later" are not part of this plan. They are the reason for it:
the move of `grad_spectrum` from pulseq-reports, an acoustic check in
pulseq-checks, and the resonance bands of each target in the spectrum card
of pulseq-reports need a series in hertz. Section 1.2 shows that the data of
pulseq-reports fit the new form.

This plan gives the work in this repository:

| Branch | Result |
|---|---|
| `docs/series-axis-plan` | This plan (section 5 lists no code). |
| `feature/series-coordinate-unit` | The change, the documents and tag `v0.1.0rc3` (section 6). |

Section 8 lists the facts for the follow-up work in pulseq-checks, and
section 9 lists them for pulseq-reports.

### 1.1 Order

```
This plan merged  ->  feature/series-coordinate-unit  ->  tag v0.1.0rc3
                                                              |
                                                              +->  pulseq-checks: pin v0.1.0rc3 (section 8)
```

pulseq-checks pins `v0.1.0rc2`. The tag `v0.1.0rc3` does not break it,
because it keeps its pin until its own branch changes the pin.
pulseq-reports does not use `pulseq-analysis` yet (section 2, fact 9).

### 1.2 The data of pulseq-reports that do not have a time coordinate

pulseq-reports has two measurement modules whose data have no time
coordinate: `grad_spectrum` and `rf_profiles` (section 2, facts 9 to 11).
This table gives a series form for each value. The forms are examples, to
check this plan. They are not an interface. The plan that moves a module
gives the names of its series.

| Value (pulseq-reports) | Kind, `coord_unit` | Coordinate | Arrays, `unit` |
|---|---|---|---|
| `GradientSpectrum.rss` and `.axes` (one coordinate for the four spectra) | `SAMPLES`, `"Hz"` | `coord_start` 0.0, `coord_step` `frequency_hz[1]` | `value` (RSS), `x`, `y`, `z`, unit `"mT/m/√Hz"` |
| The resonances `(frequency_hz, bandwidth_hz)` of a target | `RUNS`, `"Hz"` | `start` = f − bw/2, `end` = f + bw/2 | `frequency_hz`, `bandwidth_hz` |
| `GradientSpectrum.band_peaks` | `POINTS`, `"Hz"` | `coord` = `BandPeak.frequency_hz` | `value` (`peak`), `relative`, `low_hz`, `high_hz` |
| `Profile` of the view `"profile"`, a position axis (`x`, `y`, `z`, `select`) | `SAMPLES`, `"m"` | `coord_start` `lo`, `coord_step` `(hi - lo) / (n - 1)` | `value` (for example `mxy_abs`), `mz`, `beta_sq`, the echo phase (NaN where \|Mxy\| is small), or the complex `a` and `b` |
| `Profile` of the view `"profile"`, the axis `df` | `SAMPLES`, `"Hz"` | as the row above, and `coord_start` can be below 0 | as the row above |
| `widths`, `CombinedProfile.numbers`, `PulseSummary` | none | — | Numbers, not series. They go in `meta`, or in the value of the analysis. |
| `Profile` of the views `"z_df"` and `"2d"`, `CombinedMap` | none | two coordinates | Not possible: a series has one coordinate and one-dimensional arrays (U5). |

Notes on the table:

1. `scipy.signal.spectrogram` gives the frequencies of
   `numpy.fft.rfftfreq`, which are `k * frequency_hz[1]` for each `k`. Thus
   `coord_start + k * coord_step` gives the same frequencies, bit for bit.
2. `numpy.linspace(lo, hi, n)` gives `lo + k * step`, and sets its last value
   to `hi`. Thus `SAMPLES` gives the same positions, to the rounding of the
   last value.
3. The unit `"m"` does not say which position (`x`, `y`, `z` or `select`).
   The analysis puts that in `meta`, and its `spec.series` names the key
   (U6).
4. A spectrum has about 300 values (2000 Hz in steps of about 6.7 Hz). It
   needs no `ENVELOPE`.
5. The value types of these rows are in `Series` already: more arrays of
   the same length, complex arrays, and NaN in an array.

## 2. Context (verified on 2026-10-04)

This repository's `main` is at `9f65863` (version `0.1.0rc2`).
pulseq-checks `origin/main` is at `4ec751b` (its own version `0.1.0rc3`,
which is not this rc3). pulseq-reports `origin/main` is at `cffad7c`.

1. **`series.py`.** `SeriesKind` has `SAMPLES`, `ENVELOPE`, `POINTS` and
   `RUNS`. `Series` has the fields `name`, `kind`, `unit`, `arrays`, `t0_s`
   (default 0.0), `step_s` (default None), `end_s` (default None) and
   `meta`. `unit` is the unit of the values. `_NECESSARY` gives the arrays
   of each kind: `POINTS` needs `time_s` and `value`, and `RUNS` needs
   `start_s` and `end_s`. `to_obj` writes the keys in the order of
   `_SERIES_KEYS`: `name`, `kind`, `unit`, `t0_s`, `step_s`, `end_s`, `meta`,
   `arrays`. `from_obj` refuses an unknown key and a missing key. The file
   names `t0_s` or `step_s` 30 times.
2. **The rules of a field.** `t0_s` is a number, and it can be infinite or
   NaN. `step_s` is finite and above 0. A field that a kind does not use must
   have its default. No rule compares two fields or the values of an array
   (for example, `start_s[k] <= end_s[k]` is not checked).
3. **`analyses.py`.** Only `_PnsSafeLevels.to_series` makes a `Series`
   (lines 247 and 271). It gives `pns_total` (`ENVELOPE`, `t0_s` 0, `step_s`
   `bin_samples * dt_s`, `end_s` `num_samples * dt_s`) and one
   `pns_above_<t>` for each threshold (`RUNS`, arrays `start_s`, `end_s`,
   `num_samples`, `peak`, `peak_time_s`). The text `spec.series` of
   `PNS_SAFE_LEVELS` names these fields and arrays. The other three analyses
   give `()`. Each `spec.version` is 1.
4. **The tests.** `tests/test_series.py` (648 lines) names `t0_s` or `step_s`
   45 times. Its helpers `_samples`, `_envelope`, `_points`, `_runs` and
   `_used_fields` make each kind. `tests/test_analyses.py` names them 2
   times, and the RUNS array names 4 times (lines 258 to 309).
5. **The documents.** `docs/usage.md` section 5 ("`series`: values for
   JSON") and section 6 (the table of the series of `pns.safe.levels`, and
   the paragraph after it). In `TESTS.md`, 15 lines of sections 2.8 and 2.9
   name `t0_s` or `step_s`, and section 2.9 names the RUNS arrays (lines
   2581 to 2601). Other mentions of `start_s` and
   `end_s` in these files are fields of `SequenceIndex` and `PnsInterval`,
   not of a series.
6. **The users of `Series` in other repositories.** pulseq-checks
   `src/pulseq_checks/results.py` reads and writes a series with `to_obj`
   and `from_obj`. `src/pulseq_checks/run.py` checks the type only.
   `tests/test_results.py` (`_series_pair`, lines 585 to 611) makes an
   `ENVELOPE` and a `RUNS` series with the rc2 names. `docs/usage.md` of
   pulseq-checks (lines 987 to 1050) lists the keys of a series object and
   gives an example JSON item. pulseq-reports does not import
   `pulseq_analysis`.
7. **The release-candidate rule.** In the release candidates, the
   specification versions and the JSON result format of pulseq-checks stay
   1, and no code reads an older form (decision T10 of
   `docs/plans/pulseq-analysis.md` of pulseq-checks, and its design section
   4.4). An incompatible change edits version 1 and goes in the
   `CHANGELOG.md`.
8. **The time script.** `scripts/time_pns_levels.py` times
   `pns_levels.pns_levels`. It does not call `to_series` and does not make a
   `Series`.
9. **pulseq-reports and its plan.** pulseq-reports does not import
   `pulseq_analysis` at `cffad7c`. Its plan (`docs/plans/pulseq-checks.md`
   of pulseq-reports, section 4.4) gives the card `gradient-spectrum` "the
   bands of each target, in the color of the target", and section 4.5 lists
   the move of `grad_spectrum` to pulseq-analysis as later work. Its
   principle 1 says that a mark against a limit comes from a check result
   or from an analysis result.
10. **The spectrum card of pulseq-reports.** `cards/spectrum.py` gives the
    four spectra (`x`, `y`, `z`, RSS) as lanes of points `[f, value]` on one
    frequency coordinate, unit `"mT/m/√Hz"`. `assets/cards/spectrum.js` gives
    them to `PulseqReport.laneChart` with `xDomain` `[0, 2000]`, `xLabel`
    "Frequency (Hz)" and `bands`, a list of `[low, high]` pairs in Hz. The
    lane chart (`assets/lane_chart.js`) does not assume a time coordinate.
    The caller gives the domain, the label and the bands.
11. **The RF profiles of pulseq-reports.** The card `rf-profile` computes
    its profiles in the browser (`assets/rf_profiles.js`), from the RF
    table that `cards/rf_profile.py` gives. `rf_profiles.py` is the Python
    reference of that code, and an interface "for other projects and CI
    gates". A `ProfileAxis` has a kind (`x`, `y`, `z`, `select` or `df`),
    `lo`, `hi` and `n`, in m for a position and in Hz for `df`. A `Profile`
    has one or two axes. `CombinedMap` has two.

## 3. Decisions

### 3.1 Decisions of the user (not approved yet)

| # | Decision | Proposed answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The name of the coordinate | `coord`: the field `coord_unit`, the fields `coord_start`, `coord_step` and `coord_end`, and the `POINTS` array `coord`. "Coordinate" is the term of xarray for the values along a dimension. | `axis` (`axis_unit`, `axis_start`, ...). In this package, "axis" is a gradient axis: `axis_peaks`, `axis_peaks_x`, and `meta` `{"axis": "x"}` in `test_series.py`. `x` (`x_unit`, `x0`, ...) has the same problem: `x` is the gradient axis x. |
| U2 | The name of the unit of the values | `unit` stays. Its meaning does not change. | `value_unit`, a pair with `coord_unit`. It changes one more key in each JSON object and each document, for no new meaning. |
| U3 | A default for `coord_unit` | No default. Each series gives its coordinate unit. | `"s"`. The rename of the fields breaks each caller, so a default saves no change. It also lets a spectrum go out as seconds by error. |
| U4 | The names of the `RUNS` arrays | `start` and `end`. | `coord_start` and `coord_end`. These are also the names of two fields, so one JSON object has `"coord_end": null` and an array `coord_end`. rc2 has this problem with `end_s`. |
| U5 | Data on two coordinates (the RF maps of section 1.2) | Not in this plan. No user needs them as a series: the RF profile card computes its maps in the browser (fact 11), and no check of pulseq-checks uses a map. A later kind can add a second coordinate (for example `coord2_unit`, `coord2_start`, `coord2_step`) and keep the names of this plan for the first coordinate. | A kind for a regular two-dimensional grid now. It needs a rule for the shape and the order of a flat array, and it has no user. |
| U6 | A name of the coordinate quantity | No field. The unit gives the quantity (`"s"` time, `"Hz"` frequency, `"m"` position). When the unit does not give all of it (which position), the analysis puts it in `meta`. | A field `coord_name` (for example `"frequency"`), for the axis label of a general viewer. Each card of pulseq-reports knows its data and sets its own label (fact 10). |

### 3.2 Decisions of this plan

These decisions follow from the code or from the decisions of section 3.1.
The approval of this plan approves them.

| # | Decision | Reason |
|---|---|---|
| L1 | The rules of section 2, fact 2, do not change. Only the names change, and `coord_unit` is new. This plan adds no rule that compares two fields or the values of an array. | One concern for each branch. A rule such as `start[k] <= end[k]` is a separate change. |
| L2 | `coord_unit` is a string, and it is not empty, else `TypeError` or `ValueError`. The code does not check it against a list of units. `docs/usage.md` gives `"s"` and `"Hz"` as examples, and tells the writer to use the SI symbol. | `unit` has no list either. A sample index can use `"1"`. |
| L3 | An array other than a necessary array keeps its own name and unit. `peak_time_s` of `pns_above_<t>` stays, and the `meta` keys `dt_s` and `peak_time_s` of `pns_total` stay. | They are values, not the coordinate. They are always in seconds. |
| L4 | The specification version of `pns.safe.levels` stays 1. `from_obj` does not read an rc2 object: the key `t0_s` is an unknown key, so it raises `ValueError`. | Fact 7. |
| L5 | The field order of `Series` is `name`, `kind`, `unit`, `coord_unit`, `arrays`, `coord_start`, `coord_step`, `coord_end`, `meta`. The key order of `to_obj` is `name`, `kind`, `unit`, `coord_unit`, `coord_start`, `coord_step`, `coord_end`, `meta`, `arrays`. | `coord_unit` has no default (U3), so it comes before the fields with a default. The key order keeps the order of rc2, with each coordinate key in the place of its rc2 key. |
| L6 | No time measurement. | Fact 8. `pns_levels` does not change. |
| L7 | The title of `docs/usage.md` section 5 does not change. | pulseq-checks links to its anchor `#5-series-values-for-json`. |
| L8 | The tests of `test_series.py` keep their names. Their `pytest.param` IDs change where they name a field (for example `t0-not-a-number` becomes `coord-start-not-a-number`). | `TESTS.md` names the tests, not the IDs. |
| L9 | The tag is an annotated tag on the merge commit of the release PR. The executing agent shows the command, and pushes the tag only after the user approves. | Decision L9 of `docs/plans/implementation.md`. |
| L10 | This plan does not move `grad_spectrum` or `rf_profiles`, and adds no analysis. The series forms of section 1.2 are not an interface. | One concern for each branch. The move needs its own plan (fact 9). |

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

## 5. The plan branch

Branch: `docs/series-axis-plan`. Files: this plan, and one line for it in
the "Documents" list of `README.md`. No code changes.

## 6. The change

Branch: `feature/series-coordinate-unit`. Start after this plan merges.
Task 6.1 comes first. Tasks 6.2 and 6.3 share no file, and they can run at
the same time after task 6.1.

### 6.1 Task 1: `series.py` and its tests (tier H)

Files: `src/pulseq_analysis/series.py`, `tests/test_series.py`, `TESTS.md`
section 2.8.

The names change as in this table. Each docstring, comment and error
message uses the new names.

| rc2 | rc3 |
|---|---|
| — | field `coord_unit` (new, U3) |
| field `t0_s` | field `coord_start` |
| field `step_s` | field `coord_step` |
| field `end_s` | field `coord_end` |
| `POINTS` array `time_s` | `POINTS` array `coord` |
| `RUNS` arrays `start_s`, `end_s` | `RUNS` arrays `start`, `end` (U4) |

The interface:

```python
class SeriesKind(Enum):
    SAMPLES = "samples"  # value[k] at coord_start + k * coord_step
    ENVELOPE = "envelope"  # min[i] and max[i] of the bin
    # [coord_start + i * coord_step, coord_start + (i + 1) * coord_step);
    # the last bin stops at coord_end
    POINTS = "points"  # value[k] at coord[k] (not regular, for example one for each block)
    RUNS = "runs"  # a boolean that is true from start[k] to end[k], else false


_NECESSARY = {
    SeriesKind.SAMPLES: ("value",),
    SeriesKind.ENVELOPE: ("min", "max"),
    SeriesKind.POINTS: ("coord", "value"),
    SeriesKind.RUNS: ("start", "end"),
}


@dataclass(frozen=True, eq=False)
class Series:
    name: str
    kind: SeriesKind
    unit: str  # the unit of the values, for example "1", "mT/m"
    coord_unit: str  # the unit of the coordinate, for example "s", "Hz"
    arrays: Mapping[str, np.ndarray]
    coord_start: float = 0.0  # SAMPLES and ENVELOPE
    coord_step: float | None = None  # SAMPLES and ENVELOPE
    coord_end: float | None = None  # ENVELOPE
    meta: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)


_SERIES_KEYS = (
    "name",
    "kind",
    "unit",
    "coord_unit",
    "coord_start",
    "coord_step",
    "coord_end",
    "meta",
    "arrays",
)
```

Rules of the code:

- `__post_init__` checks `coord_unit` after `unit`: `TypeError` when it is
  not a string, `ValueError` when it is empty (L2). The other rules do not
  change (L1).
- `__eq__` compares `coord_unit` with `name`, `kind` and `unit`.
- `to_obj` writes `coord_unit` as a string, and the three coordinate fields
  with `_float_to_json`, in the order of L5. `from_obj` reads them. It
  raises `ValueError` for an object of rc2 (L4), with no special message.
- The module docstring and the `Series` docstring define the coordinate in
  one sentence: "The coordinate of a series is the quantity of its
  horizontal axis, for example the time (unit "s") or the frequency (unit
  "Hz")."

Changes to the tests of `test_series.py`:

- Each helper (`_samples`, `_envelope`, `_points`, `_runs`, `_used_fields`)
  and each test uses the new names. Each helper gives `coord_unit="s"`. The
  test names do not change (L8).
- `test_series_refuses_a_bad_field`: add the IDs `coord-unit-not-a-string`
  (`coord_unit=None`, `TypeError`) and `coord-unit-empty` (`coord_unit=""`,
  `ValueError`).
- `test_series_not_equal_for_a_different_field_or_array`: add a series with
  another `coord_unit` (`"Hz"`).
- `test_to_obj_keys_and_types`: the keys of L5, and `obj["coord_unit"] ==
  "s"`.
- `test_from_obj_refuses`: add the IDs `coord-unit-null`,
  `coord-unit-a-number`, `missing-coord-unit` and `rc2-object`. To make the
  object `rc2-object`, start from `_good_obj()`. Remove `coord_unit`, and
  rename `coord_start`, `coord_step` and `coord_end` to `t0_s`, `step_s`
  and `end_s`. Keep the values.

New test:

- `test_series_with_a_coordinate_other_than_time`: the forms of section
  1.2, with synthetic data:
  - a `SAMPLES` spectrum, `coord_unit="Hz"`, `coord_start` 0.0,
    `coord_step` 500.0, `unit` `"mT/m/√Hz"`, with the float64 arrays
    `value`, `x`, `y` and `z` of length 5.
  - a `RUNS` series of two bands, `coord_unit="Hz"`: `start`
    `[540.0, 1030.0]`, `end` `[640.0, 1250.0]`.
  - a `POINTS` series of the peak in each band, `coord_unit="Hz"`: `coord`
    `[590.0, 1140.0]`, `value` `[0.2, 0.7]`, `relative` `[0.3, 1.0]`.
  - a `SAMPLES` RF profile, `coord_unit="m"`, `coord_start` -0.01,
    `coord_step` 0.005, `unit` `"1"`, with the arrays `value` (float64),
    `phase` (float64, with NaN) and `a` (complex128) of length 5, and `meta`
    `{"position": "select"}`.

  For each one, the round trip gives an equal series, and `to_obj()` keeps
  `coord_unit`. The docstring says that the data are synthetic, and that a
  spectrum or a profile uses the same kinds as a time series.

`TESTS.md` section 2.8: change the field names in each entry that names
them (section 2, fact 5). Add the new IDs to the entries of the changed
tests. Add the entry of the new test. Change "design section 4.2" in the
introduction to "design section 4.2, with the names of
`docs/plans/series-coordinate.md`".

Checks of task 1:

- [ ] `git grep -n -E "t0_s|step_s|time_s|start_s|end_s" -- src/pulseq_analysis/series.py tests/test_series.py`
      finds nothing.
- [ ] `nix develop --command uv run pytest tests/test_series.py` passes.

### 6.2 Task 2: `analyses.py` and its tests (tier M)

After task 1. Files: `src/pulseq_analysis/analyses.py`,
`tests/test_analyses.py`, `TESTS.md` section 2.9.

`_PnsSafeLevels.to_series`:

- `pns_total`: `coord_unit="s"`, `coord_start=0.0`,
  `coord_step=value.bin_samples * value.dt_s`,
  `coord_end=value.num_samples * value.dt_s`. The arrays and `meta` do not
  change (L3).
- `pns_above_<t>`: `coord_unit="s"`. The arrays are `start`, `end`,
  `num_samples`, `peak` and `peak_time_s`, in this order. The values do not
  change: `start` is `[i.start_s for i in intervals]`, and `end` is
  `[i.end_s for i in intervals]`.

`spec.series` of `PNS_SAFE_LEVELS`: the same text with the new names. Add
`coord_unit "s"` to the text of each series. `spec.version` stays 1 (L4).

`tests/test_analyses.py`: the assertions of lines 258 to 309 use the new
names. Add `assert total.coord_unit == "s"`, and the same for each RUNS
series. No new test.

`TESTS.md` section 2.9: the entries of these tests (lines 2581 to 2601) use
the new names.

Checks of task 2:

- [ ] `git grep -n -E "t0_s|step_s|\"start_s\"|\"end_s\"" -- src/pulseq_analysis/analyses.py tests/test_analyses.py`
      finds nothing. (`i.start_s` and `i.end_s` of `PnsInterval` stay.)
- [ ] `nix develop --command uv run pytest tests/test_analyses.py` passes.

### 6.3 Task 3: documents and the release (tier M)

After task 1. Files: `docs/usage.md`, `README.md`, `CHANGELOG.md`,
`pyproject.toml`, `uv.lock`.

- `docs/usage.md` section 5 (L7: the title does not change):
  - The field table: a row for `coord_unit` after `unit`. The rows of the
    coordinate fields use the new names. Define the coordinate with the
    sentence of task 1.
  - The kind table: the new names.
  - The `to_obj` paragraph: the keys of L5.
  - A new paragraph: one `Series` can hold a time series, a spectrum or a
    profile along a position. Give the table of section 1 of this plan,
    without the words "(now)" and "(later)". Say that `coord_unit` uses the
    SI symbol, and that no code checks it (L2). Say that a series has one
    coordinate, so it cannot hold a map on two coordinates (U5). Say that
    the unit gives the quantity of the coordinate, and that `meta` gives
    more (for example which position) when the analysis needs it (U6).
- `docs/usage.md` section 6: the table of the series of `pns.safe.levels`
  gets a column `coord_unit` (`"s"` for both). The arrays and the paragraph
  after the table use the new names.
- `README.md`: the install line with `@v0.1.0rc3`. In the paragraph on the
  release candidates, add one sentence: "The third, `0.1.0rc3`, gives each
  series a coordinate unit, so that a series can be in seconds or in hertz."
- `CHANGELOG.md`: the entry `0.1.0rc3` with the date. The text names this
  plan. "Changed": the table of task 1, the new required field
  `coord_unit`, the new names of the series of `pns.safe.levels`, and that
  `from_obj` does not read an rc2 object. Say that the specification
  version of `pns.safe.levels` stays 1 (L4).
- `pyproject.toml`: version `0.1.0rc3`. Then
  `nix develop --command uv lock`.

After the merge, the executing agent tags `v0.1.0rc3` (L9):

```bash
git -C /Users/dylan/dev/pulseq-analysis tag -a v0.1.0rc3 -m "pulseq-analysis 0.1.0rc3" origin/main
```

## 7. Checks of the branch

- [ ] `nix develop --command scripts/check` passes.
- [ ] `git grep -n -E "t0_s|step_s" -- src tests docs/usage.md TESTS.md README.md`
      finds nothing.
- [ ] The command below finds only the fields of `SequenceIndex`,
      `GradientLimits`, `BlockGradientValues`, `PnsLevels` and
      `PnsInterval`. The executing agent reads each match.

      ```bash
      git grep -n -E '`(time_s|start_s|end_s)`' -- docs/usage.md TESTS.md
      ```
- [ ] The executing agent writes the JSON of `to_obj` of each series of
      `pns.safe.levels` for `build_repeating(10)` of
      `tests/scale_sequences.py`. The PR description gives this JSON, with
      each `data` abbreviated. pulseq-checks uses it for its example
      (section 8, item 3).
- [ ] CI passes on the PR.

## 8. Facts for the follow-up in pulseq-checks

pulseq-checks does this work on its own branch, after the tag
`v0.1.0rc3`, with its own plan. Line numbers are at `4ec751b`.

1. `pyproject.toml` line 13: change `@v0.1.0rc2` to `@v0.1.0rc3`. Then
   `uv lock`.
2. `tests/test_results.py`, `_series_pair` (lines 585 to 611): the new
   names of section 6.1, and `coord_unit="s"` for both series. The test
   names and their `TESTS.md` entries do not name a field, so they do not
   change.
3. `docs/usage.md` (lines 987 to 1050): the keys of a series object (L5),
   the "time field" in the sentence on values that are not finite (it
   becomes "a coordinate field"), the link to the usage document of
   `v0.1.0rc3`, and the example JSON item. The anchor
   `#5-series-values-for-json` does not change (L7).
4. The JSON result format stays 1 (fact 7). A JSON result with series of
   rc2 cannot be read after the pin changes. The `CHANGELOG.md` of
   pulseq-checks says so.
5. `src/pulseq_checks/checks/pns.py` uses `PnsLevels` and `PnsInterval`,
   not a series. It does not change.
6. `docs/plans/pulseq-analysis.md` of pulseq-checks (design section 4.2)
   keeps the rc2 names. It is a record of the design. Do not edit it.

## 9. Facts for pulseq-reports

pulseq-reports does this work in its own plans. This plan changes nothing
in pulseq-reports now (fact 9).

1. When the spectrum card reads series from a result matrix, `coord_unit`
   gives the label of the x axis (`"Hz"`: "Frequency (Hz)"). The card can
   also keep its own label, because it knows its data (U6).
2. A `RUNS` series in Hz gives the `bands` of `PulseqReport.laneChart`
   directly: `[start[k], end[k]]` for each `k`. These are the "bands of each
   target" of section 4.4 of its plan.
3. A `SAMPLES` series gives the frequency of value `k` as
   `coord_start + k * coord_step`. For the spectrum, this is the frequency
   of `grad_spectrum`, bit for bit (section 1.2, note 1).
4. The RF maps (the views `"z_df"` and `"2d"`, and `CombinedMap`) cannot be
   series (U5). The card computes them in the browser, so this is not a
   gap now. A later plan that needs a map from Python adds a kind with a
   second coordinate.
