# Implementation plan: the gradient spectrum analysis (0.1.0rc4)

Mode: Strict STE100. Structural rules are enforced. Lexical rules are a
direction of travel, not a verified dictionary match.

Status: draft, not approved. Written on 2026-10-04.

## 1. Scope

This plan moves the gradient spectrum of pulseq-reports
(`src/pulseq_reports/grad_spectrum.py`) to this package. It adds the
analysis `gradient.spectrum`, with one `SAMPLES` series in hertz. It is
the first analysis that uses the coordinate unit of `0.1.0rc3`
(`docs/plans/series-coordinate.md`).

The spectrum measures the sequence only:

- **No resonance bands.** The moved module has no `resonances` argument,
  no `BandPeak` and no `band_peaks`. The bands are data of the target.
  The peak in a band is a comparison with data of the target. Both go to
  an acoustic check of pulseq-checks (decision L11 of
  `docs/plans/series-coordinate.md`).
- **No gamma.** The values are in Hz/m/√Hz, the unit of the gradients of a
  `.seq` file, not in mT/m/√Hz (decision U1, section 3.1). Section 5.3
  gives the reason and the conversion.

This plan gives the work in this repository:

| Branch | Result |
|---|---|
| `docs/gradient-spectrum-plan` | This plan. No code. |
| `feature/gradient-spectrum` | The module, the analysis, the documents and tag `v0.1.0rc4` (section 6). |

Section 8 lists the facts for the follow-up work in pulseq-reports and in
pulseq-checks.

### 1.1 Order

```
This plan merged  ->  feature/gradient-spectrum  ->  tag v0.1.0rc4
                                                        |
                                                        +->  pulseq-reports: use the moved module (section 8.1)
                                                        +->  pulseq-checks: pin v0.1.0rc4, later the acoustic check (section 8.2)
```

pulseq-reports pins `v0.1.0rc2`, and pulseq-checks pins `v0.1.0rc3`. The
tag `v0.1.0rc4` does not break them, because each keeps its pin until its
own branch changes the pin.

## 2. Context (verified on 2026-10-04)

This repository's `main` is at `62dc9e4` (version `0.1.0rc3`).
pulseq-reports `origin/main` is at `cc87563`. pulseq-checks `origin/main`
is at `e4af709`.

1. **The module in pulseq-reports.** `src/pulseq_reports/grad_spectrum.py`
   at `cc87563` (169 lines). It imports `GradientSampler` from
   `pulseq_analysis.sampling` and `sequence_index` from
   `pulseq_analysis.seq_index`, so its imports are in this package already.
   It also imports `scipy.signal.spectrogram`. It has the constants
   `MAX_FREQUENCY_HZ` (2000.0), `FFT_WINDOW_S` (0.05),
   `FREQUENCY_OVERSAMPLING` (3), `CHUNK_WINDOWS` (256) and `NO_GRADIENTS`,
   the dataclasses `BandPeak` and `GradientSpectrum`, the function
   `gradient_spectrum(seq, *, resonances=())`, and the private functions
   `_chunk_spectrogram` and `_band_peaks`.
2. **Gamma in the module.** `gradient_spectrum` multiplies each sample by
   `to_mt = 1e3 / seq.system.gamma` before the spectrogram. The `.seq` file
   gives the gradients in Hz/m and does not give a gamma. pypulseq gives
   `seq.system.gamma` its default, 42.576 MHz/T, which is `GAMMA` of
   `seq_utils.py`. The `TODO.md` of pulseq-reports lists this line in its
   table of the places that change Hz into T.
3. **The method is linear.** Each step of the method changes in proportion
   to a positive scale `c` of the waveform: the constant detrend, the Hann
   window, the magnitude of the FFT, the maximum over windows, and the
   root-sum-of-squares of the three axes. Thus the spectrum of `c * w` is
   `c` times the spectrum of `w`, to the float rounding.
4. **Rotations.** `gradient_spectrum` does not refuse the rotation
   extension. The card of pulseq-reports calls `refuse_rotations` before
   it. In this package, `gradient_limits` and `pns_levels` refuse it
   themselves.
5. **The tests in pulseq-reports.** `tests/test_grad_spectrum.py` (190
   lines, 10 test functions, `TESTS.md` section 2.9 of pulseq-reports) and
   `tests/oracles/grad_spectrum.py` (152 lines). The oracle is the module
   before phase 5 of `docs/plans/cards-at-scale.md` of pulseq-reports: it
   samples with `Sequence.get_gradients()`, and its values are in mT/m/√Hz
   with `seq.system.gamma`. Two tests check only band values:
   `test_sine_outside_the_bands` and
   `test_without_resonances_there_are_no_band_peaks`. Five more have band
   lines: `test_spin_echo_spectrum`, `test_sine_in_the_first_band`,
   `test_no_gradients`, `test_chunks_give_the_same_spectrum_as_one_chunk`
   and the oracle comparison.
6. **The test helpers.** `tests/synthetic.py` of this package is the file
   of pulseq-reports without `load_diagram_scale`. It has `SYSTEM`,
   `spin_echo_sequence`, `gre_sequence`, `arbitrary_gradient_sequence` and
   `empty_sequence`. `tests/scale_sequences.py` of this package has
   `TR_BLOCKS`, `build_repeating` and `build_worst`, the builders that
   `load_diagram_scale` gives in pulseq-reports.
7. **scipy.** `pyproject.toml` has `scipy` in the `dev` group only (L3 of
   `docs/plans/implementation.md`). pypulseq depends on `scipy` (`uv.lock`),
   so it is installed with this package already.
8. **The card of pulseq-reports.** `cards/spectrum.py` converts nothing
   itself: it uses the mT/m/√Hz values of the module. It gives the page
   `resonances` (empty) and `bands` (from `band_peaks`).
   `assets/cards/spectrum.js` draws the shaded bands from
   `data.resonances` and does not read `data.bands`.
9. **The time of the spectrum.** On 2026-10-04, on an Apple M1 Max, the
   module of `cc87563` (a copy that imports `pulseq_analysis`) took 1.27 s
   for `build_repeating(20000)` (10⁵ blocks, 119.8 s) and 12.29 s for
   `build_repeating(200000)` (10⁶ blocks, 1198 s). In the same runs,
   `pns_levels` took 0.99 s and 9.86 s, and `gradient_limits` took 0.02 s
   and 0.11 s. The spectrum has 301 frequencies, with a step of
   6.666… Hz (`1 / (FREQUENCY_OVERSAMPLING * FFT_WINDOW_S)`).
10. **The frequencies.** `scipy.signal.spectrogram` gives the frequencies of
    `numpy.fft.rfftfreq`, which are `k * frequency_hz[1]` for each `k`
    (`docs/plans/series-coordinate.md`, section 1.2, note 1).
11. **pulseq-checks runs an analysis for each target.**
    `run.py` makes one `AnalysisResult` for each target. `bindings.py` makes
    an analysis available with no binding when its `spec.params` is empty.
12. **The kept results.** `seq_index.sequence_index` and
    `pns.pns_levels_for` keep a result for each sequence object in a
    `weakref.WeakKeyDictionary`. They build it again when the number of
    blocks or the last block ID changed.
13. **`docs/usage.md`.** Sections 1 to 4 are the modules, section 5 is
    `series` and section 6 is `analyses`. pulseq-checks links to the anchor
    `#5-series-values-for-json`.
14. **The arguments of pypulseq.** `calculate_gradient_spectrum` of the
    pinned pypulseq has `max_frequency` (2000.0), `window_width` (0.05),
    `frequency_oversampling` (3.0, a float), `time_range`, `plot`,
    `combine_mode` (`"max"`), `use_derivative` (False) and
    `acoustic_resonances`. It uses `nfft = round(frequency_oversampling *
    nwin)` and `noverlap = nwin // 2`, so the overlap is not an argument.
15. **The `window` of `gradient_limits`.** `grad_limits.gradient_limits`
    has a `window` argument. The analysis `gradient.limits` does not have
    it: the module docstring of `analyses.py` says that the analysis is of
    the whole sequence.
16. **`thresholds` of `pns.safe.levels`.** The analysis has the parameter
    `thresholds`, a value of the check, and `bindings.py` of pulseq-checks
    gives it the constant `(PNS_LIMIT,)`. The parameter is there because
    pulseq-reports must mark the runs above the threshold of the check, from
    the analysis result (principle 1 of its plan).

## 3. Decisions

### 3.1 Decisions of the user

The user approved U1 to U4 on 2026-10-04.

| # | Decision | Answer | Alternative (not chosen) |
|---|---|---|---|
| U1 | The unit of the spectrum (approved on 2026-10-04) | Hz/m/√Hz, with no gamma. The documents say why (section 5.3) and give the conversion. | mT/m/√Hz with a `gamma` parameter, as `gradient.limits`. |
| U2 | A kept result (approved on 2026-10-04) | Yes: `gradient_spectrum_for(seq)` keeps the result for each sequence object, with the rule of fact 12. `compute` uses it. The arrays of a `GradientSpectrum` are read-only, so that a caller cannot change the kept result for the other callers (L12). | No kept result. pulseq-checks then calculates the spectrum one time for each target (fact 11): 12 s each at 10⁶ blocks (fact 9). |
| U3 | The parameters of the method (approved on 2026-10-04) | The functions `gradient_spectrum` and `gradient_spectrum_for` take `max_frequency_hz`, `window_s` and `frequency_oversampling`, with the defaults of pypulseq's `calculate_gradient_spectrum` (fact 14). The analysis `gradient.spectrum` has no parameters (`spec.params` is `()`), and `compute` uses the defaults. A check that needs other values gives them itself and calls the function. The target profile never gives them. This is the form of `gradient.limits`, whose function has a `window` argument that the analysis does not have (fact 15). | (a) No parameters: the values stay module constants. (b) Parameters of `compute`: pulseq-checks then needs a binding, but a binding is for data of the target, and these values are not (fact 11). |
| U4 | The form of the series (approved on 2026-10-04) | One `SAMPLES` series, `gradient_spectrum`, with the arrays `value` (RSS), `x`, `y` and `z`. | Four series, one for each array. They have one coordinate, so one series is smaller and keeps them together. |

### 3.2 Decisions of this plan

These decisions follow from the code or from the decisions of section 3.1.
The approval of this plan approves them.

| # | Decision | Reason |
|---|---|---|
| L1 | The module is `src/pulseq_analysis/grad_spectrum.py`. It is the file of pulseq-reports at `cc87563` with only the changes of section 5.1. | pulseq-reports changes one import line (section 8.1). The move rule of `docs/plans/implementation.md` section 4.1 shows the diff. |
| L2 | `tests/oracles/grad_spectrum.py` is a copy of the file of pulseq-reports at `cc87563`, with no change. It keeps mT/m/√Hz, `seq.system.gamma` and its band code. The tests multiply the values of this module by `1e3 / seq.system.gamma` and call the oracle with no resonances. | The oracle is an independent reference (L7 of `docs/plans/implementation.md`). Its mT/m values also test the conversion of section 5.3. |
| L3 | `scipy` moves from the `dev` group to `[project] dependencies`. | The module imports it at run time. pypulseq installs it already (fact 7), so no new package comes in. |
| L4 | `gradient_spectrum` calls `refuse_rotations(seq)` first, as `gradient_limits`. | Fact 4. The sampler does not apply a rotation, so a spectrum of a sequence with rotations is wrong. |
| L5 | The analysis: ID `gradient.spectrum`, object `GRADIENT_SPECTRUM`, version 1, `params` `()` (U3), `rasters` `("GradientRasterTime", "BlockDurationRaster")`, `cost` `"slow"`. | Fact 9: the spectrum takes more time than `pns.safe.levels`, which is "slow". The rasters are those of the other gradient analyses. |
| L6 | The unit text of the series is `"Hz/m/sqrt(Hz)"`. | ASCII text for a program that reads the JSON. The documents write Hz/m/√Hz. |
| L7 | `coord_start` is 0.0 and `coord_step` is `frequency_hz[1]`. | Fact 10: `coord_start + k * coord_step` gives the frequencies bit for bit. A test checks this. |
| L8 | `docs/usage.md` gets a new section 7 for `grad_spectrum`. Sections 1 to 6 keep their numbers. | Fact 13: the anchor of section 5. |
| L9 | `gradient.limits` and `gradient.blocks` keep their `gamma` parameter and their mT/m values. Section 5.3 says that they differ from the spectrum. | One concern for each branch. Section 9 lists the alignment as later work. |
| L10 | The time of the moved module must not be more than 5 % above the time of fact 9 (12.29 s at 10⁶ blocks, on the same machine). | The rule of task 3.2 of `docs/plans/implementation.md`. The change removes one multiplication, so the time should not grow. |
| L11 | The tag is an annotated tag on the merge commit of the release PR. The executing agent shows the command, and pushes the tag only after the user approves. | Decision L9 of `docs/plans/implementation.md`. |
| L12 | `gradient_spectrum` sets `flags.writeable = False` on `frequency_hz`, `rss` and each array of `axes`, also for `NO_GRADIENTS`. A change in place (for example `s.rss *= 1e3 / GAMMA`) raises `ValueError`. A caller converts to a new array (`s.rss * 1e3 / GAMMA`). | U2: all callers share the kept object. Section 5.3 tells a caller to convert the values, and a conversion in place would change the spectrum of the other callers without an error. `Series` makes its arrays read-only for the same reason. |

## 4. How to execute this plan

The workflow is that of `docs/plans/implementation.md` section 4:

1. Start the branch with the `dev-workflow:start-task` skill, from the
   latest `origin/main`. Then run `nix develop --command uv sync --frozen`
   one time in the worktree, before a worker starts.
2. Each test that a task adds, moves or changes gets its `TESTS.md` entry in
   the same PR.
3. Run `nix develop --command scripts/check` before the PR.
4. Show the commit message to the user, and wait for approval before
   `git commit`. Merge only when the user tells you to.
5. The executing agent reviews each worker's diff line by line.
6. When a task finds that this plan is wrong, stop and ask the user.

The tiers M (`worker-medium`), H (`worker-high`) and X (the executing
agent) are those of `docs/plans/implementation.md` section 4.

## 5. The design

### 5.1 `grad_spectrum.py`: the changes to the file of pulseq-reports

1. Remove `BandPeak`, `_band_peaks`, the argument `resonances`, and the
   fields `resonances` and `band_peaks` of `GradientSpectrum`.
2. Remove `to_mt`. `_chunk_spectrogram` loses its argument `to_mt`, and
   the samples stay in Hz/m.
3. Call `refuse_rotations(seq)` (from `.extensions`) at the start of
   `gradient_spectrum` (L4).
4. Use relative imports (`from .sampling import GradientSampler`, as the
   other modules of this package).
5. The module docstring: remove the text on the resonances and on Siemens.
   Add the text of section 5.3. Keep the text on the method, the padding
   and the chunks.
6. Add `gradient_spectrum_for(seq, ...)` (U2), with the rule of fact 12.
   The kept results of one sequence object have one key for each tuple
   `(max_frequency_hz, window_s, frequency_oversampling)` of floats, as
   `pns_levels_for` has a key for each hardware and thresholds.
7. Make each array of the result read-only (L12).
8. Replace the constants of the method with the keyword arguments of U3
   (section 5.1.1). The constants stay, as the defaults.

The interface:

```python
@dataclass(frozen=True, eq=False)
class GradientSpectrum:
    reason: str | None  # NO_GRADIENTS, or None
    frequency_hz: np.ndarray  # float64, F: 0 to MAX_FREQUENCY_HZ
    axes: dict[str, np.ndarray]  # "x", "y", "z": float64, F, Hz/m/sqrt(Hz)
    rss: np.ndarray  # float64, F, Hz/m/sqrt(Hz)


def gradient_spectrum(
    seq: pp.Sequence,
    *,
    max_frequency_hz: float = MAX_FREQUENCY_HZ,
    window_s: float = FFT_WINDOW_S,
    frequency_oversampling: float = FREQUENCY_OVERSAMPLING,
) -> GradientSpectrum: ...


def gradient_spectrum_for(
    seq: pp.Sequence,
    *,
    max_frequency_hz: float = MAX_FREQUENCY_HZ,
    window_s: float = FFT_WINDOW_S,
    frequency_oversampling: float = FREQUENCY_OVERSAMPLING,
) -> GradientSpectrum: ...
```

`eq=False` because the fields are arrays (as `Series`). With
`NO_GRADIENTS`, `frequency_hz` and `rss` are empty and `axes` is `{}`, as
in pulseq-reports. Each array is read-only (L12). The dataclass is frozen,
so a caller cannot replace an array either. The dict `axes` stays a plain
dict.

#### 5.1.1 The arguments of the method

| Argument | Default | pypulseq (fact 14) | Use |
|---|---|---|---|
| `max_frequency_hz` | `MAX_FREQUENCY_HZ` (2000.0) | `max_frequency` | The highest frequency of the result. |
| `window_s` | `FFT_WINDOW_S` (0.05) | `window_width` | The length of a Hann window. `nwin = round(window_s / dt)`. |
| `frequency_oversampling` | `FREQUENCY_OVERSAMPLING` (3.0) | `frequency_oversampling` | `nfft = round(frequency_oversampling * nwin)`, as pypulseq. |

The other arguments of pypulseq are not arguments here:

- The overlap: pypulseq has no argument for it. It stays `nwin // 2`.
- `combine_mode` and `use_derivative`: they change what a value is (for
  example a spectrum of the slew rate). A later quantity gets its own
  function.
- `time_range`: the spectrum is of the whole sequence, as
  `gradient_limits` without `window`.
- `acoustic_resonances`: data of the target (L11 of
  `docs/plans/series-coordinate.md`).

`FREQUENCY_OVERSAMPLING` becomes the float `3.0`. With `nwin` an integer,
`round(3.0 * nwin)` is `3 * nwin`, so the defaults give the values of
pulseq-reports.

The rules of the arguments. A refused value raises `ValueError` (or
`TypeError` for a value that is not a number, or a bool) before
`gradient_spectrum` reads the blocks:

- Each argument is a finite number.
- `window_s` is above 0, and `nwin` is 2 or more at the gradient raster of
  the file.
- `frequency_oversampling` is 1 or more.
- `max_frequency_hz` is above 0 and at most the Nyquist frequency,
  `1 / (2 * dt)`. It is at least the frequency step,
  `1 / (nfft * dt)`, so that the result has two or more frequencies
  (L7 needs `frequency_hz[1]`).

### 5.2 The analysis `gradient.spectrum`

In `analyses.py`, `_GradientSpectrum` with the specification of L5:

- `compute(seq)` gives `gradient_spectrum_for(seq)`, with the defaults of
  section 5.1.1 (U3).
- `to_series(value)` gives `()` for `NO_GRADIENTS`. Else it gives one
  series:

  | Field | Value |
  |---|---|
  | `name` | `"gradient_spectrum"` |
  | `kind` | `SAMPLES` |
  | `unit` | `"Hz/m/sqrt(Hz)"` (L6) |
  | `coord_unit` | `"Hz"` |
  | `coord_start`, `coord_step` | 0.0, `frequency_hz[1]` (L7) |
  | `arrays` | `value` (`rss`), `x`, `y`, `z`, float64, in this order |
  | `meta` | `max_frequency_hz`, `window_s`, `frequency_oversampling`: the values of the call, so that the JSON says how the spectrum was made |

- `spec.description` gives the contract of `GradientSpectrum`, the unit,
  and the conversion sentence of section 5.3. `spec.series` gives the table
  above as text.
- `pyproject.toml`: the entry point
  `"gradient.spectrum" = "pulseq_analysis.analyses:GRADIENT_SPECTRUM"`.
- The module docstring of `analyses.py` lists the fifth analysis.

### 5.3 The unit: why, and the conversion

This text goes in the module docstring of `grad_spectrum.py` and in
section 7 of `docs/usage.md`, in these words or close to them:

> The spectrum is in Hz/m/√Hz, the unit of the gradients of a `.seq` file.
> A change to T/m needs gamma, the gyromagnetic ratio of the nucleus that
> the scanner images. The `.seq` file does not give gamma: it is data of
> the target, not of the sequence. Thus the spectrum depends only on the
> sequence.
>
> To get mT/m/√Hz for a gamma γ in Hz/T, multiply each value by
> `1e3 / γ`. For ¹H, γ is 42.576 MHz/T (`seq_utils.GAMMA`), and 1 Hz/m/√Hz
> is 2.3487 × 10⁻⁵ mT/m/√Hz. The conversion is exact to the float
> rounding, because each step of the method changes in proportion to a
> positive scale of the waveform (fact 3). This includes the RSS spectrum.
>
> `gradient.limits` and `gradient.blocks` take `gamma` and give mT/m. The
> spectrum does not.

The usage section gives a short example:

```python
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.seq_utils import GAMMA

s = gradient_spectrum(seq)
rss_mt = s.rss * 1e3 / GAMMA  # mT/m/sqrt(Hz), for 1H: a new array
```

The arrays of the result are read-only (L12), so `s.rss *= 1e3 / GAMMA`
raises `ValueError`. The section says so.

## 6. The change

Branch: `feature/gradient-spectrum`. Start after this plan merges. Tasks
6.1 and 6.3 share no file, and they can run at the same time. Task 6.2
comes after task 6.1.

### 6.1 Task 1: the module and its tests (tier H)

Files: `src/pulseq_analysis/grad_spectrum.py` (new),
`tests/test_grad_spectrum.py` (new), `tests/oracles/grad_spectrum.py`
(new), `TESTS.md` section 2.10 (new).

The module: section 5.1. Then the executing agent checks it with the move
rule:

```bash
diff <(git -C /Users/dylan/dev/pulseq-reports show cc87563:src/pulseq_reports/grad_spectrum.py) src/pulseq_analysis/grad_spectrum.py
```

The diff must show only the changes of section 5.1. Put it in the PR
description.

The oracle: a copy with no change (L2). Check it with `diff`, which must be
empty.

The tests: the file of pulseq-reports at `cc87563`, with these changes:

| Test or helper | Change |
|---|---|
| Imports | `from pulseq_analysis import grad_spectrum`. `scale_sequences` in place of `load_diagram_scale`. |
| `RESONANCES` | Remove. The oracle calls give no resonances. |
| `SINE_1MT_PEAK` | Keep, and add `SINE_PEAK = SINE_1MT_PEAK * 1e-3 * SYSTEM.gamma`, the peak of the same sine in Hz/m/√Hz. The comment gives the reason. |
| `_assert_same_spectrum` | Remove the band comparison. |
| `test_spin_echo_spectrum` | Remove the band lines. |
| `test_sine_in_the_first_band` | Rename to `test_sine_peak_is_at_its_frequency`. Keep the frequency and the value of the peak (`SINE_PEAK`). Remove the band lines. |
| `test_sine_outside_the_bands` | Remove. It tests bands only. |
| `test_short_sequence_is_padded_to_one_window` | No change. |
| `test_gradients_at_the_end_are_not_attenuated` | `SINE_PEAK` in place of `SINE_1MT_PEAK`. |
| `test_without_resonances_there_are_no_band_peaks` | Remove. |
| `test_no_gradients` | Remove the band line. Add: `frequency_hz` and `rss` are empty, `axes` is `{}`. |
| `test_chunks_give_the_same_spectrum_as_one_chunk` | No resonances. |
| `_assert_matches_oracle` | Compare `got` times `1e3 / seq.system.gamma` with the oracle (L2). Remove the band comparison. The docstring says that this also tests the conversion of section 5.3. |
| `test_matches_oracle_on_synthetic_sequences`, `test_matches_oracle_on_long_sequences` | No resonances. The long test uses `scale_sequences.TR_BLOCKS`, `build_repeating` and `build_worst`. The tolerance does not change. |

New tests:

- `test_spectrum_does_not_depend_on_the_gamma_of_the_system`: one sine
  waveform in Hz/m in two sequences, one with `SYSTEM` and one with a copy
  of `SYSTEM` with another `gamma`. The two spectra are exactly equal.
- `test_gradient_spectrum_refuses_rotations`: a sequence with the rotation
  extension raises `NotImplementedError` (as `test_gradient_limits_refuses_rotations`
  in `test_grad_limits.py`).
- `test_gradient_spectrum_for_keeps_the_result`: two calls give the same
  object. After `add_block`, the call gives a new object.
- `test_the_arrays_of_a_spectrum_are_read_only`: for a spectrum and for
  `NO_GRADIENTS`, a change in place of `frequency_hz`, `rss` and each array
  of `axes` raises `ValueError`. A conversion to a new array works.
- `test_the_defaults_are_those_of_pypulseq`: a call with the three
  arguments of pypulseq's defaults, given explicitly, is equal to a call
  with no arguments.
- `test_the_arguments_change_the_frequencies`: with `window_s=0.1`, the
  step is `1 / (3 * 0.1)` Hz. With `frequency_oversampling=1`, the step is
  `1 / 0.05` Hz. With `max_frequency_hz=500`, the last frequency is at most
  500 Hz. The 600 Hz sine peak stays at 600 Hz with `window_s=0.1`.
- `test_gradient_spectrum_refuses_bad_arguments`: parametrized. Each rule
  of section 5.1.1 has a case: NaN, infinity, a string, a bool, a window of
  one sample, an oversampling below 1, a highest frequency of 0, above the
  Nyquist frequency, or below the frequency step. The test checks the error
  type, and that the sequence was not read (a monkeypatched
  `sequence_index` that fails).
- `test_gradient_spectrum_for_keeps_one_result_for_each_set_of_arguments`:
  two calls with other arguments give two objects. A call with the same
  values again gives the first object.

`TESTS.md` section 2.10, "Gradient spectrum (`test_grad_spectrum.py`)":
section 2.9 of the `TESTS.md` of pulseq-reports at `cc87563`, with these
changes. Remove the text on the resonances and `RESONANCES`. Change the
entries of the changed tests. Remove the entries of the removed tests. Add
the entries of the new tests. Add the unit (Hz/m/√Hz) and the conversion of
the oracle comparison to the introduction.

Checks of task 1:

- [ ] `nix develop --command uv run pytest tests/test_grad_spectrum.py` passes.
- [ ] The two `diff` commands above.
- [ ] `git grep -n -i -E "resonan|band" -- src/pulseq_analysis/grad_spectrum.py tests/test_grad_spectrum.py` finds nothing.

### 6.2 Task 2: the analysis (tier M)

After task 1. Files: `src/pulseq_analysis/analyses.py`, `pyproject.toml`
(the entry point and L3), `uv.lock` (the executing agent runs
`nix develop --command uv lock` and `uv sync`), `tests/test_analyses.py`,
`TESTS.md` section 2.9.

The analysis: section 5.2.

Tests in `tests/test_analyses.py`:

- The registry test: five IDs.
- New: `test_the_spectrum_series_equals_the_spectrum_of_the_same_call`. For
  `spin_echo_sequence()`: the fields and the arrays of section 5.2, and
  `coord_start + arange(n) * coord_step` equals `frequency_hz` exactly
  (L7).
- New: `test_the_spectrum_series_of_a_sequence_without_gradients_is_empty`.
- The test of `compute` of each analysis includes `gradient.spectrum`, and
  `compute` gives the object of `gradient_spectrum_for`.

`TESTS.md` section 2.9: the entries of the changed and new tests.

Check of task 2: `nix develop --command uv run pytest tests/test_analyses.py`
passes.

### 6.3 Task 3: documents and the release (tier M)

Files: `docs/usage.md`, `README.md`, `CHANGELOG.md`, and the version in
`pyproject.toml` (the executing agent merges this with task 2, which also
changes this file).

- `docs/usage.md`: a new section 7, "`grad_spectrum`: the gradient
  spectrum" (L8). The method (from the module docstring), the fields of
  `GradientSpectrum`, `gradient_spectrum_for` and its kept result, the
  read-only arrays (L12), `NO_GRADIENTS`, the rotation refusal, and section
  5.3 with its example. In section 6: a row
  for `gradient.spectrum` in the table of the analyses, and a table of its
  series, as for `pns.safe.levels`. Change "each `version` is 1" only if it
  is not true.
- `README.md`: the install line with `@v0.1.0rc4`. One sentence on
  `0.1.0rc4` in the paragraph on the release candidates. The description of
  the package names the gradient spectrum.
- `CHANGELOG.md`: the entry `0.1.0rc4` with the date. "Added": the module,
  the analysis and its series. "Changed": `scipy` is a runtime dependency.
  Name this plan. Say that the values are in Hz/m/√Hz, and give the
  conversion.
- `pyproject.toml`: version `0.1.0rc4`.

### 6.4 Measurement (tier X)

After tasks 1 and 2. Time `grad_spectrum.gradient_spectrum` on
`build_repeating(200000)` (10⁶ blocks), three times, on the machine of
fact 9. Record the minimum in section 10 of this plan, in the same PR.
When it is more than 5 % above 12.29 s, stop and ask the user (L10).

After the merge, the executing agent tags `v0.1.0rc4` (L11):

```bash
git -C /Users/dylan/dev/pulseq-analysis tag -a v0.1.0rc4 -m "pulseq-analysis 0.1.0rc4" origin/main
```

## 7. Checks of the branch

- [ ] `nix develop --command scripts/check` passes.
- [ ] The two `diff` commands of task 1.
- [ ] Section 10 has the time, and it is not more than 5 % above 12.29 s.
- [ ] CI passes on the PR.

## 8. Facts for the follow-up work

### 8.1 pulseq-reports

pulseq-reports does this work in its own plan, after the tag `v0.1.0rc4`.

1. Pin `v0.1.0rc4` of pulseq-analysis. The pin must be the same tag as the
   pin of pulseq-checks, or a later one that pulseq-checks accepts.
2. Delete `src/pulseq_reports/grad_spectrum.py`,
   `tests/test_grad_spectrum.py`, `tests/oracles/grad_spectrum.py` and
   section 2.9 of its `TESTS.md`. `cards/spectrum.py` imports
   `pulseq_analysis.grad_spectrum`.
3. The card converts the values to mT/m/√Hz with `1e3 / GAMMA` (its
   principle 8: the proton gamma only). The `TODO.md` table of the places
   that change Hz into T changes the row of `grad_spectrum.gradient_spectrum`
   to the card, with `GAMMA`.
4. The card has no `band_peaks`. Remove `bands` from its page data:
   `spectrum.js` does not read it (fact 8). The shaded bands come from
   `data.resonances`, which the card takes from the target profile (its
   plan, section 4.4).
5. The test of the reader options
   (`test_rf_exposure_and_spectrum_do_not_depend_on_the_reader_opts`)
   compares the spectra with no band peaks.

### 8.2 pulseq-checks

1. When pulseq-checks pins `v0.1.0rc4`, `gradient.spectrum` is in the
   registry with no binding, because `spec.params` is empty (fact 11, U3).
   `--analysis gradient.spectrum` then gives its series in the JSON result,
   with the defaults of pypulseq. pulseq-checks needs no code for this.
2. The acoustic check is a separate plan of pulseq-checks. It reads
   `acoustic.resonances` from the target, takes the spectrum from
   `gradient_spectrum_for` (one calculation for all the targets, U2), and
   gives the findings. The spectrum is in Hz/m/√Hz. If the limit of the
   check is in mT/m/√Hz, the check converts with the gamma of its target
   (section 5.3).
3. The check chooses the arguments of section 5.1.1 itself, as constants
   or as options of the check. A target profile does not give them, so they
   are not in `bindings.py`.
4. When the check uses values other than the defaults, its findings and
   the spectrum of the analysis result (which a report draws) are of two
   calculations. Each finding of the check gives the values that it used.
   If a report must mark the spectrum of the check, a later version gives
   the analysis the parameters, as `thresholds` of `pns.safe.levels`
   (fact 16).

## 9. Later

- **Parameters of the analysis** (U3): if a report must draw the spectrum
  with the values of a check (section 8.2, item 4).
- **One result for all the targets in pulseq-checks.** `run.py` could
  calculate one time each analysis whose arguments are the same for all the
  targets. This is more general than U2 inside pulseq-checks, but it does
  not help a caller outside pulseq-checks.
- **Read-only arrays in `PnsLevels`.** `pns_levels_for` shares its kept
  result with writable arrays, so it has the risk of L12.
- **The gamma of the gradient analyses** (L9): `gradient.limits` and
  `gradient.blocks` could also give Hz/m, for the reason of section 5.3.
  That changes their interface and the checks of pulseq-checks.

## 10. Measurements

Task 6.4 records the time here.
