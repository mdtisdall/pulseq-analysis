# Changelog

Each version of `pulseq-analysis` has an entry here. The version numbers
follow [PEP 440](https://peps.python.org/pep-0440/).

## Unreleased

`load` accepts a sequence with no `[SIGNATURE]` hash, and
`extensions.refuse_unsigned` is removed. No result of the package uses the
hash, and the refusal blocked a sequence built in memory and never written,
and a file with no `[SIGNATURE]` section. The values of the measurements do
not change.

This changes the order of `0.1.0rc6` ("A caller moves in this order"):

- Step 2: do not call `write` on a sequence before `load(seq)`. `load`
  accepts an unsigned sequence and raises no `ValueError` for a missing hash.
- Step 1: the pin stays at `3c3bd85`, because pulseq-analysis, pulseq-checks
  and pulseq-reports pin one commit. The code of this package no longer reads
  the hash, so the read of the hash as text no longer matters to it.

### Changed

- `snapshot.load` does not check the hash. A sequence or a file with no hash
  gives a `Snapshot`, and `snap.sequence.signature_value` is the value of the
  source (`''` for a sequence built in memory). `load` still refuses the
  rotation extension (`NotImplementedError`), also for an unsigned sequence,
  which gave `ValueError` before.
- The spec of each analysis is not changed: each `spec.version` stays 1.

### Removed

- `extensions.refuse_unsigned`. A caller who requires a hash checks
  `isinstance(seq.signature_value, str) and seq.signature_value != ""` on the
  source before `load`, or on `snap.sequence`. To sign a sequence, call
  `write` on the source and `load` the file: `write` changes the sequence, so
  do not call it on `snap.sequence`.

## 0.1.0rc6 (2026-10-07)

The sixth release candidate: the fixes of four code reviews of the package
(`docs/reviews/2026-10-04-code-review.md`, `2026-10-05-code-review.md`,
`2026-10-06-code-review.md` and `2026-10-07-code-review.md`), and the changes
of the interface that four plans chose (`docs/plans/review-fixes.md`,
`second-review-fixes.md`, `third-review-fixes.md` and
`fourth-review-fixes.md`). The work is in the pull requests #18 to #85. A
review is named by its date: "review 2026-10-07 1.1" is the finding 1.1 of
`docs/reviews/2026-10-07-code-review.md`. This release breaks callers of
`0.1.0rc5`. In the release candidates, an incompatible change has no alias: an
old name raises `ImportError`, `AttributeError` or `TypeError`.

Three changes need the most work from a caller. Each measurement takes a
`Snapshot` that `snapshot.load` makes, and no longer a pypulseq `Sequence`.
`load` refuses a sequence with no `[SIGNATURE]` hash. And the values of a
sequence that has an end that is not 0 next to a gap change, because the
package has one gradient waveform now.

A caller moves in this order:

1. Install pypulseq at the fork commit `3c3bd85` (the tag
   `pulseq-reports-pin-2`). `pyproject.toml` pins it in `[tool.uv.sources]`.
   uv applies the pin for a project that depends on `pulseq-analysis` by git
   URL. pip does not, so a caller that uses pip installs that commit itself.
   This commit reads the `[SIGNATURE]` hash of a file as text. The pin of
   `0.1.0rc5` (`a74ab06`) could make a float of a hash that looks like a
   number, and `load` refuses a hash that is not a `str`, as it refuses a
   missing hash.
2. Make one snapshot of each file: `snap = load(path)`, or `load(seq)` for a
   `pp.Sequence`. Give `snap` to each measurement and to each `compute`. A
   file must have a `[SIGNATURE]` hash, and `load` raises `ValueError` for a
   sequence that has none. A sequence that was built in memory gets its hash
   from `seq.write(path)`: call `write` on it before `load(seq)`.
3. Rename `grad_limits` to `grad_peaks`, and `gradient.limits` to
   `gradient.peaks`. Replace `pns_levels_for` with `pns_levels`, and
   `gradient_spectrum_for` with `gradient_spectrum`: each is the one function
   of its measurement now, and it keeps its result. Replace `pns_prediction`
   with `pns_levels` (the fields `reason`, `hardware`, `peak_hz_per_t`,
   `peak_time_s` and `axis_peaks_hz_per_t`). Replace `PNS_LIMIT` with
   `abs(gamma)`, and `GradientPeaks.whole_rms_hz_per_m` with
   `gradient_peaks(snap).axes[axis].rms_hz_per_m`. Copy `peak_tr_window` and
   `hold_samples` from the tag `v0.1.0rc5` if you need them.
4. Give the PNS hardware as `hardware=(struct, label)` in each call of
   `pns_levels` and `PNS_SAFE_LEVELS.compute`, and drop `gradient_asc=`. Give
   `bin_s=10.0 / 1624` where you need the bins of `0.1.0rc5`: the default bin
   is 5 ms now.
5. Call `rf_events(snap)`, `grad_events(snap)` and `adc_events(snap)` with no
   index: each gives a tuple. `block_cache_off` is gone.
6. Compare the `reason` of a result with the constants of `seq_index`, and
   catch `TypeError` where you caught `ValueError` for a threshold of a wrong
   type.
7. Read `start` and `end` of the series `pns_above_<k>` as the edges of the
   samples of a run. Add `"format": 1` to a JSON object of a series that you
   stored with `0.1.0rc5`, because `Series.from_obj` refuses an object with no
   `"format"`.
8. An analysis of another package takes the snapshot in `compute(snap,
   **params)`, and its `AnalysisSpec` must pass the new checks. A runner that
   needs a registry that goes on after a broken entry point calls
   `registry(strict=False)`.

The results work as before otherwise, but their arrays and dicts are
read-only, and the values in the section "The values that change" are
different.

### Changed

- **The snapshot.** A measurement describes one fixed sequence and keeps its
  result, but pypulseq lets a caller change a sequence in place:
  `mod_grad_axis`, `flip_grad_axis`, `set_block` on an existing block ID,
  `apply_soft_delay`, and a write into `block_events` or a library. The kept
  results of `0.1.0rc5` (`sequence_index`, `pns_levels_for` and
  `gradient_spectrum_for`) saw none of these. On `build_repeating(3)`, after
  `seq.mod_grad_axis("x", 0.5)` the kept `pns_levels_for` and
  `gradient_spectrum_for` still gave the values of the old gradient, and after
  `seq.set_block(2, pp.make_delay(30e-3))` the kept
  `sequence_index(seq).end_s` was still 0.01797 s (review 2026-10-07 1.1). So
  each measurement takes a `Snapshot` (#80):

  ```python
  from pulseq_analysis.snapshot import load
  from pulseq_analysis.grad_peaks import gradient_peaks

  snap = load("sequence.seq")  # or load(seq) for a pp.Sequence
  peaks = gradient_peaks(snap)
  ```

  `load(source)` takes the path of a `.seq` file (`str` or `os.PathLike`) or a
  `pp.Sequence`. A path is read into a new `pp.Sequence` that no other object
  holds, so `load` makes no copy. A `pp.Sequence` is copied with
  `copy.deepcopy`: the snapshot shares no mutable object with it, so a change
  of `source` after `load` does not change the snapshot, and `load` does not
  change `source` (its block cache is set aside during the copy). On
  `build_repeating(3)`, after `snap = load(seq)` and
  `seq.mod_grad_axis("x", 0.5)`, `gradient_peaks(snap)` still gives the x peak
  of the sequence at `load`, 714 286 Hz/m, and a new `load(seq)` gives
  357 143 Hz/m. Any other type raises `TypeError`. `load` then calls
  `extensions.refuse_unsigned` and `extensions.refuse_rotations` one time
  (`ValueError` for a sequence with no hash, `NotImplementedError` for the
  rotation extension), and sets `use_block_cache` to False for the private
  sequence, so a measurement of a snapshot calls neither check again and
  pypulseq keeps no block. `load` builds no result: each result is made on its
  first use, and kept on the snapshot.

  `Snapshot.sequence` is the private `pp.Sequence`, and `Snapshot.source` is
  the path (a `str`) or `None`. A caller and an analysis must not change
  `snapshot.sequence`, or an object that they get from it (for example a block
  from `get_block`): the kept results are made from it. Two snapshots are equal
  only when they are one object, and a snapshot can be the key of a dict. A
  copy from `pickle` or `copy.deepcopy` is a new snapshot with a copy of the
  sequence and no kept results.

  Each public function that took a sequence takes the snapshot as its first
  argument, and raises `TypeError` that names `load` for another type. The
  function checks its other arguments first.

  | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|
  | `sequence_index(seq)` | `sequence_index(snap)` |
  | `rf_events(seq, index)`, `grad_events(seq, index)`, `adc_events(seq, index)`: generators | `rf_events(snap)`, `grad_events(snap)`, `adc_events(snap)`: tuples, made one time and kept |
  | `block_cache_off(seq)` | none: the sequence of a snapshot has no block cache |
  | `grad_limits.gradient_limits(seq, *, window=None)` | `grad_peaks.gradient_peaks(snap, *, window=None)` |
  | `grad_limits.block_gradient_values(seq)` | `grad_peaks.block_gradient_values(snap)` |
  | `pns.pns_levels_for(seq, *, gradient_asc=None, hardware=None, thresholds_hz_per_t=())`, kept; `pns_levels.pns_levels(seq, ...)`, not kept | `pns_levels.pns_levels(snap, *, hardware, thresholds_hz_per_t=(), bin_s=BIN_S)`, kept |
  | `grad_spectrum.gradient_spectrum_for(seq, *, max_frequency_hz, window_s, frequency_oversampling)`, kept; `gradient_spectrum(seq, ...)`, not kept | `grad_spectrum.gradient_spectrum(snap, *, max_frequency_hz, window_s, frequency_oversampling)`, kept |
  | `GradientSampler(seq, index)` | `sampling.gradient_sampler(snap)`, and `GradientSampler(snap)` |
  | `Analysis.compute(seq, **params)` | `Analysis.compute(snap, **params)` |
  | `extensions.refuse_rotations(seq)` | no change, and `load` calls it |
  | none | `extensions.refuse_unsigned(seq)`, which `load` calls |

  The kept results are on the snapshot, so there is no stamp and no kept
  result of a sequence object: a second call with the same arguments gives the
  kept object. `gradient_peaks` keeps the result for `window=None` only (a
  caller can ask for many windows), and it uses the kept values of each block
  for a window. The result of a call is read-only, because all callers of one
  snapshot share it. `load(seq)` costs a copy, and `load(path)` costs the
  `read` of pypulseq. For 100,000 blocks (`build_repeating(20000)` of
  `tests/scale_sequences.py`): `load(path)` 0.35 s and `load(seq)` 0.15 s. With
  20,000 unique gradient events (`build_worst(20000)`): 1.1 s and 0.40 s.
  (Apple M1 Max, one run.)
- **The values that change.** The first item changes the values of each
  sequence that has an end that is not 0 next to a gap. Each other item is a
  rare case, or the last bits.
  - **The gradient waveform between two events** (review 2026-10-06 1.1 and
    6.3, #58). `0.1.0rc5` had three models: `GradientSampler.sample` drew a
    line across each gap, `GradientSampler.block_samples` and the RMS used 0,
    and `gradient_limits` counted a step at each block junction, from the last
    value of the previous block to the first value of the block (0 for a block
    with no event on the axis), divided by `dt`, at the start of the block. Each
    measurement uses one waveform now, the waveform of MATLAB Pulseq. With
    `dt = seq.grad_raster_time`, and a gap between two consecutive events on an
    axis (the blocks between them have no event on the axis):

    | Gap | The waveform |
    |---|---|
    | Zero (`TIME_TOLERANCE` or less) | A step from the last value to the first value, at the time of the first point. Its slew is `abs(step) / dt`. |
    | Short (more than that, up to `dt + TIME_TOLERANCE`) | The straight line from the last point to the first point. |
    | Long | A ramp to 0 in `dt / 2` after the earlier event, when its last value is not 0, and a ramp from 0 in `dt / 2` before the later event, when its first value is not 0. The value is 0 between them. A ramp has the slew `2 * abs(value) / dt`. |

    Before the first point and after the last point of an axis the value is 0,
    and a first or a last value that is not 0 is a step. pypulseq's
    `waveforms()` draws a line across each gap, so its `get_gradients`,
    `calculate_pns` and `calculate_gradient_spectrum` differ from the package
    for a sequence with an event that starts or ends at a value that is not 0
    next to a long gap, and for a step at a junction. A value of 1e-6 Hz/m or
    less also gets its ramp.

    | Measurement | `0.1.0rc5` | `0.1.0rc6` |
    |---|---|---|
    | `gradient_peaks`, `block_gradient_values`: zero gap | the junction step `abs(last - first) / dt` | no change |
    | the same, short gap | the junction steps | the slope of the line, `abs(first - last) / gap`, from the end of the earlier event |
    | the same, long gap | the junction steps | two ramps: `2 * abs(last) / dt` and `2 * abs(first) / dt` |
    | the same, after the last event of the axis, when the sequence goes on | the junction step `abs(last) / dt`, at the start of the next block, credited to that block | the step `abs(last) / dt` at the last point, credited to the block of the last event |
    | The RMS | 0 in each gap | the line, or the ramps |
    | `GradientSampler.sample` (the spectrum, and the PNS off the raster) | the line across each gap | the ramps across a long gap |
    | `GradientSampler.block_samples` (the PNS on the raster) | 0 in each gap | the line in a short gap |

    A ramp from a raster edge ends at a sample time, where its value is 0, so
    a sequence on the raster has the samples of `0.1.0rc5` except in a short
    gap. The credit of a segment to a block: a ramp to 0 goes to the block of
    the earlier event, a ramp from 0 to the block of the later event, and a
    step or the line of a short gap to the block of the later event. Its time
    is the start of the segment. `BlockGradientValues.slew_hz_per_m_per_s` of a
    block includes the ramps of its event, and `junction_hz_per_m_per_s` is the
    step or the line into its event, and 0 for a long gap. For example, an
    extended trapezoid on x ends at `0.9 * max_slew * grad_raster_time` at the
    end of its block, then there is a delay of 1 ms, then a trapezoid: with the
    default pypulseq `Opts`, the largest slew of x was 6.5e9 Hz/m/s (the step
    to 0) and is 1.3e10 Hz/m/s (the ramp). A sequence with no end that is not
    0 next to a gap and no step at a junction has the values of `0.1.0rc5`: for
    `build_repeating(10)` with `bin_s=10.0 / 1624`, the PNS peak, its time and
    the level are equal, bit for bit (the edges of the runs change, below).
  - **The end of the spectrum, and the number of samples** (review 2026-10-06
    1.2 and 1.3, #52). The spectrum padded the end of the waveform with half a
    window whatever the length, so a gradient near the end was attenuated
    more than one in the middle. The end padding is now the fewest zeros, at
    least half a window, that make the padded waveform one window plus a whole
    number of hops long. The last sample is then within half a hop of the
    centre of some window, as a sample in the middle is. One trapezoid
    (`make_trapezoid(channel="x", area=3000)`) at the end of a sequence of 7000
    samples at the 10 us raster has the largest `rss` 8722 Hz/m/sqrt(Hz)
    before and 18756 now (7499 samples: 10842 and 21827; the same trapezoid at
    the start gives 21831). A sequence whose number of samples is a whole
    number of hops does not change. The number of samples is also one rule
    now, `sampling.sequence_samples`, for `gradient_spectrum` and
    `pns_levels`: the blocks `[0.01938, 0.01268]` s are 3206 samples, and
    `gradient_spectrum` counted 3207. The PNS values do not change.
  - **The runs of the PNS model start and end at the edges of their samples**
    (review 2026-10-06 6.5, #62). `PnsInterval.start_s` is `first * dt` and
    `end_s` is `(last + 1) * dt`. They were the times of the first and the last
    sample, so a run of one sample had the length 0. A run of one sample has
    `end_s - start_s == dt` now, and each run starts half a raster time
    earlier and ends half a raster time later. `peak_time_s` stays the time of
    a sample, `(k + 0.5) * dt`. The series `pns_above_<k>` gives the same
    values, and the bins of `pns_total` already used these edges.
  - **The rasters of `seq.index`.** `spec.rasters` of `seq.index` is
    `("BlockDurationRaster",)`, not `()` (review 2026-10-06 6.1, #60). The rule
    of `rasters` is the rasters of the file whose value changes the value of
    the analysis, and `Sequence.read` makes each block duration from
    `BlockDurationRaster`. The four other analyses keep
    `("GradientRasterTime", "BlockDurationRaster")`.
  - **The default bin of the PNS level** is 5 ms, not about 6.16 ms: 500
    samples at the 10 us raster, not 615 (see "The bin of the PNS level").
  - **The samples of `block_samples` at the edges of an event** (review
    2026-10-07 1.3 and 1.4, #73). At a step inside one event the sample takes
    the value before the step, the rule of `sample`: the third sample of a
    block with a 3-sample arbitrary gradient (`[10000, 20000, 15000]`) was
    12500 (`last`) and is 15000. A sample within `TIME_TOLERANCE` after the
    last point of an event has the value of that point. These two rules can
    change `block_samples`, and so `pns_levels` on the raster, for an arbitrary
    gradient of 4 samples or fewer (pypulseq gives it its own time shape) and
    for a gradient delay off the raster by half a raster time.
  - **The last bits.** A sample of `block_samples` can differ by 1 ulp from
    `0.1.0rc5`. The RMS integral of `AxisResult.rms_hz_per_m` can change by
    2.5e-16 relative, and the RMS of a window by one ulp (the order of the
    sums, #75, #56). The spectrum can change by 4.9e-16 of the largest value of
    an array (`scipy.fft.rfft` in one thread, #78). One chunk still equals many
    chunks, bit for bit.
- **The names of `grad_limits`.** The module measures peaks and checks no
  limit, so the names say peaks. The names `AxisResult`, `BlockGradientValues`,
  `block_gradient_values` and `gradient.blocks` do not change, and neither do
  the fields (#26).

  | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|
  | module `pulseq_analysis.grad_limits` | `pulseq_analysis.grad_peaks` |
  | `GradientLimits` | `GradientPeaks` |
  | `gradient_limits(seq, *, window=None)` | `gradient_peaks(snap, *, window=None)` |
  | analysis `gradient.limits` (title "Gradient limits") | `gradient.peaks` (title "Gradient peaks") |
  | `analyses.GRADIENT_LIMITS` | `analyses.GRADIENT_PEAKS` |
  | the entry point `"gradient.limits"` | the entry point `"gradient.peaks"` |

- **The PNS hardware is necessary.** `pns_levels` and
  `PNS_SAFE_LEVELS.compute` take the keyword argument `hardware`, with no
  default: a pair `(struct, label)`. `struct` is a SAFE hardware struct in the
  form of pypulseq's `asc_to_hw`, and `label` is a `str` that
  `PnsLevels.hardware` gives. The package had pypulseq's example hardware as
  the default, which is not a real scanner. It takes no `.asc` path in the
  PNS interface now (#27).

  | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|
  | `pns_levels(seq)`, `pns_levels_for(seq)`, `compute(seq)`: the example hardware | `hardware=(safe_example_hw(), "<a label>")`: the caller gives the example hardware |
  | `hardware=None` | no value: the call without `hardware`, or with `hardware=None`, raises `TypeError` |
  | `gradient_asc=path` | `hardware=hardware_from_asc(path)` |
  | `hardware=(struct, label)` | no change |
  | `asc.EXAMPLE_HARDWARE`, the label of the example hardware | the caller chooses the label |
  | `PnsLevels.asc_file` | none: the label is the component name in the file |
  | `meta["asc_file"]` of the series `pns_total` | none |

  `safe_example_hw` is in `pypulseq.utils.safe_pns_prediction`. One check,
  `pns_levels._check_hardware`, runs first in `pns_levels`, before the
  snapshot is checked or read and before the kept results are read, also for a
  sequence with no gradient event (review 2026-10-05 1.2, #37). Before, a
  struct with no `stim_thresh` gave `AttributeError` from `pns_levels_for` and
  `ValueError` from `pns_levels`, and a struct with `a1 + a2 + a3` not 1 gave
  a result for a sequence with no gradient event.

  | The hardware | Error |
  |---|---|
  | Not a tuple of two items with a `str` second item | `TypeError` |
  | A struct with no `x`, `y` or `z`, or an axis with no field of `SAFE_FIELDS` (`stim_thresh` too) | `ValueError` that names the field |
  | A field that is not a real number | `TypeError` |
  | A field that is not finite, or a `stim_limit` not above 0 | `ValueError` |
  | An axis with `a1 + a2 + a3` more than 0.001 from 1 (the rule of pypulseq's `safe_hw_check`) | `ValueError` |

  `spec.params` of `pns.safe.levels` is `("hardware", "thresholds_hz_per_t",
  "bin_s")`, and `spec.necessary` is `("hardware",)`. The kept result of
  `pns_levels` is keyed by the label and the 24 values of the struct (8 fields
  of each axis: `stim_thresh` is not one of them, because the model does not use
  it), the thresholds and `float(bin_s)`. Before, the key of a file was its
  resolved path. Now two spellings of one path, and two pairs that
  `hardware_from_asc` makes from one file, give one key, and two structs that
  differ only in `stim_thresh` give one result.
- **The bin of the PNS level is an argument.** `pns_levels` and
  `PNS_SAFE_LEVELS.compute` take the keyword argument `bin_s`, the length of a
  bin in seconds (#29). The default is `BIN_S = 0.005`, 5 ms: 500 samples at
  the 10 us raster. `bin_s=10.0 / 1624` gives the 615 samples of `0.1.0rc5`
  at that raster. `MAX_BINS` still limits the number of bins.

  | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|
  | `EXACT_MAX_S = 10.0`, `DISPLAY_BINS = 812` (the PNS plot of pulseq-reports): 615 samples at the 10 us raster | `BIN_S = 0.005`, and the argument `bin_s`: 500 samples |
  | `bin_samples_for(num_samples, dt)` | `bin_samples_for(num_samples, dt, bin_s=BIN_S)` |
  | none | `pns_levels(snap, ..., bin_s=BIN_S)`, `compute(snap, ..., bin_s=BIN_S)` |

  `bin_samples_for` is `max(wanted, ceil(num_samples / MAX_BINS), 1)`.
  `wanted` is the nearest whole number to `bin_s / dt` when the two are
  within `ON_RASTER_TOLERANCE`, else `floor(bin_s / dt)`. A `bin_s` shorter
  than `dt` gives bins of one sample. A `bin_s` changes only the bins of the
  level: the summary and the intervals do not depend on it. `PnsLevels` has
  no new field: `bin_samples * dt_s` gives the bin. `pns_levels` keeps one
  result for each `float(bin_s)`. The nearest whole number is there because
  the division is not exact: the floor of `0.01 / 1e-5` is 999, and about half
  of the values of `bin_s` on the raster would lose one sample (review
  2026-10-05 1.1, #36).
- **The reasons.** A result with no gradient has a `reason` that is one of
  two constants of `seq_index` (#30). `pns_levels.NO_GRADIENTS` and
  `grad_spectrum.NO_GRADIENTS` are the same object as
  `seq_index.NO_GRADIENTS`, imported. The texts of `GradientPeaks.reason`
  change. A caller that compares the text uses the constants.

  | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|
  | `"no gradient events in the sequence"` (`GradientLimits.reason`, `window` None) | `seq_index.NO_GRADIENTS`, `"no gradients"` |
  | `"no gradient events in the window"` (`window` given) | `seq_index.NO_GRADIENTS_IN_WINDOW`, `"no gradients in the window"` |
  | `pns_levels.NO_GRADIENTS`, `grad_spectrum.NO_GRADIENTS`: two constants with the text `"no gradients"` | the same name in each module, one object, `seq_index.NO_GRADIENTS` |

  A `GradientSpectrum` with `reason == NO_GRADIENTS` has `axes` with the keys
  `x`, `y` and `z`, each an empty read-only float64 array, as `frequency_hz`
  and `rss` are empty. `axes` was `{}`. A caller can read `axes["x"]` of each
  result (review 2026-10-05 6.8, #48).
- **The window of `gradient_peaks`.** `window` is checked before the events
  are read (review 2026-10-05 1.3, #38), and the range is clipped to
  `[0, T]` for a sequence of length `T`, so that its start is never after its
  end: `window=(T + 5e-10, T + 9e-10)` gives `range_s == (T, T)` and
  `NO_GRADIENTS_IN_WINDOW`, not a reversed range. The time of a junction step
  into a delayed event is `start_s + delay` of the event, not the start of the
  block (review 2026-10-05 1.5).
- **The errors of a number argument.** One rule, `_validate.real`, checks the
  thresholds, `bin_s`, the arguments of `gradient_spectrum`, the `window` of
  `gradient_peaks` and the coordinates of a `Series` (#30). A value that is a
  `bool` or not a `numbers.Real` raises `TypeError`. A value that is too large
  for a float, not finite, or not above 0 where the argument must be, raises
  `ValueError`. The valid types are an `int`, a `float`, `fractions.Fraction`
  and the NumPy real scalars, so `np.float32` and `np.int64` thresholds are
  valid now.

  | Input | `0.1.0rc5` | `0.1.0rc6` |
  |---|---|---|
  | `thresholds_hz_per_t` is not a tuple | `ValueError` | `TypeError` |
  | A threshold is a `bool`, a string or not a real number | `ValueError` | `TypeError` |
  | A threshold is an `np.float32`, an `np.int64` or a `Fraction` | `ValueError` | valid |
  | A threshold is NaN, an infinity, 0, negative, or too large for a float | `ValueError` | `ValueError` |
  | Two thresholds are equal as floats | `ValueError` | `ValueError` |
  | `bin_s` is a `bool` or not a number | none (the argument is new) | `TypeError` |
  | `bin_s` is NaN, an infinity, 0 or negative | none | `ValueError` |
  | An argument of `gradient_spectrum` is too large for a float | `OverflowError` | `ValueError` |
  | `window` of `gradient_peaks` is not a tuple or a list of two items | the error of the unpacking: `TypeError` or `ValueError` | `TypeError` |
  | A start or an end of `window` is a `bool` or not a real number | the error of the comparison, or none for a `bool` | `TypeError` |
  | A start or an end of `window` is NaN or an infinity | `ValueError` | `ValueError` |
  | A coordinate of a `Series` is a `Fraction` or another real number that is not an `int` or `float` of Python or NumPy | `TypeError` | valid |
  | `coord_start` of a `SAMPLES` or `ENVELOPE` series, or `coord_end` of an `ENVELOPE` series, is NaN or an infinity | valid | `ValueError` |

  The errors of the thresholds and of `bin_s` are raised before the snapshot
  is checked. A `bool` or a value that is not a number raised `TypeError`
  before in `gradient_spectrum` and `Series`, and still does.
- **FrozenDicts.** Each dict of a result that the package makes is a
  `FrozenDict`, at `series.FrozenDict` (#30, #85): `PnsLevels.hw` (the outer
  dict and each inner dict), `PnsLevels.axis_peaks_hz_per_t` and
  `PnsLevels.above`, `GradientSpectrum.axes`, `GradientPeaks.axes`, the five
  dicts of `BlockGradientValues`, and `Series.arrays` and `Series.meta` (#53).
  A `FrozenDict` is a subclass of `dict`. It keeps `isinstance(x, dict)`,
  `json.dumps`, `pickle` and `copy.deepcopy`, and it equals a `dict` with the
  same items. Each method that changes it raises `TypeError`: `d[k] = v`,
  `del d[k]`, `d |= other`, `clear`, `pop`, `popitem`, `setdefault` and
  `update`. `d | other` and `d.copy()` give a plain `dict`. Before, the
  documents asked the caller not to change `hw`, `axis_peaks_hz_per_t` and
  `above`, and the other dicts had no such rule. The results are shared by all
  callers, so a change would have changed the result for all of them. A caller
  that needs to change a dict makes `dict(d)` first.
- **Read-only arrays.** The arrays of `SequenceIndex` (#20) and of
  `BlockGradientValues` (#30) have `writeable` False. A write in place raises
  `ValueError`. A caller that needs a writable array makes a copy, for example
  `np.array(index.start_s)`. The read-only arrays of a `Series` and of the
  kept results own no data: their base is a `bytes` object, so
  `a.flags.writeable = True` raises `ValueError` and a change cannot reach the
  other callers (review 2026-10-07 1.8, #69).
- **Equality.** `SequenceIndex` and `BlockGradientValues` compare by value, as
  `PnsLevels`, `GradientSpectrum` and `Series` do (#30, the rules of
  `0.1.0rc5`). Before, they compared by identity. Neither is hashable now:
  before, each was hashable by identity. `GradientPeaks` uses the same rule
  (#48): a NaN equals a NaN, and the order of the keys of a dict counts. It
  was unhashable already, because it holds a dict. `AxisResult` and
  `PnsInterval` stay hashable: they have no dict and no array. `Series`
  compares with the rule of the other results (#41): the order of the keys of
  `meta` counts, and `to_obj` and `from_obj` keep it. One decorator,
  `_equality.value_dataclass`, sets the rule for the six classes (#64).
- **The registry.** `registry()` raises `RegistryError` when the name of an
  entry point is not the `spec.id` of its object (#30). The docstring said so
  before, but the function used `spec.id` and did not compare the two. The
  error names the entry point, its package and the `spec.id`. The five entry
  points of this package have their IDs as names. `registry(*, strict=True)`
  keeps this error. With `strict=False`, an entry point that does not load,
  has no `spec.id`, has a name that is not its `spec.id`, or repeats an ID is
  left out, with a `RegistryWarning` (a subclass of `UserWarning`) that has the
  text of the error, and the other analyses are in the result. The entry
  points of this package load first, so they always stay (review 2026-10-07
  6.4, #83).
- **`AnalysisSpec` has the parameters and the checks that a runner needs**
  (review 2026-10-05 6.1, 6.2 and review 2026-10-07 6.2).
  - `AnalysisSpec` has two new fields. `necessary` is the names of `params`
    with no default, and `defaults` gives each other name of `params` with its
    default (None, a `bool`, an `int`, a `float`, a `str` or a tuple of these),
    in the order of `params`. The three fields must agree, or `ValueError`.
    `params` does not change meaning. A runner gives the necessary parameters
    and can leave out the others (#47).
  - The parameters of the analyses:

    | Analysis | `0.1.0rc5` | `0.1.0rc6` |
    |---|---|---|
    | `seq.index` | none | none |
    | `gradient.peaks` | none | `window` (default `None`, the whole sequence) |
    | `gradient.blocks` | none | none |
    | `pns.safe.levels` | `hardware`, `thresholds_hz_per_t` | `hardware` (necessary), `thresholds_hz_per_t` (default `()`), `bin_s` (default `BIN_S`) |
    | `gradient.spectrum` | none | `max_frequency_hz`, `window_s`, `frequency_oversampling` (the defaults of `gradient_spectrum`) |

    A test compares each spec with the signature of its `compute`.
  - `AnalysisSpec` checks its fields (#81): `id` is a `str` that is not empty;
    `version` is an `int` of 1 or more, not a `bool`; `cost` is `"fast"` or
    `"slow"`; each name of `rasters` is in the new `analyses.RASTERS`
    (`"GradientRasterTime"`, `"BlockDurationRaster"`,
    `"RadiofrequencyRasterTime"`, `"AdcRasterTime"`); `params` is a tuple of
    unique `str`; and a float default is finite. A wrong type raises
    `TypeError`, a wrong value `ValueError`. `docs/usage.md` defines the
    costs: "fast" grows with the number of blocks and of unique events, "slow"
    with the duration of the sequence.
  - The layout of `SequenceIndex` (its fields, the numbers of the events from
    1 in the order of first use, one number space for the three gradient axes,
    and the dtype rule) is the contract of `seq.index` version 1. A change of
    it raises `spec.version`.
  - The descriptions of the analyses name the model of MATLAB Pulseq, say that
    the RMS has no block and no time, and give the `ValueError` of an unsigned
    sequence.
  - Each specification version stays 1 (decision L17 of the first plan). In the
    release candidates, an incompatible change edits version 1.
- **`Series` is stricter, and its JSON form has a `"format"` key.**
  - `Series.to_obj()` has the key `"format"`, 1, first. `Series.from_obj`
    raises `ValueError` for an object with no `"format"`, with a `"format"`
    that is not 1, or with a key that format 1 does not have (review
    2026-10-07 6.3, #82). A caller can then tell two forms apart in the
    future.
  - `decode_array(d, *, max_bytes=None)` and
    `Series.from_obj(obj, *, max_bytes=None)` raise `ValueError` for more than
    `max_bytes` bytes after decompression, before any decompression
    (`from_obj` counts over all the arrays of the series). `decode_array`
    decompresses at most `length * itemsize + 1` bytes, so a small object
    cannot expand without a limit (review 2026-10-06 1.5, #53).
  - `from_obj` and `decode_array` raise `ValueError` only, also for a number
    that is too large for a float and for a `"length"` of `10**30`: they
    raised `OverflowError` (review 2026-10-07 1.6, #69).
  - A `Series` checks the order of its coordinates (review 2026-10-05 6.7,
    #48). `coord_start` is finite for `SAMPLES` and `ENVELOPE`. An `ENVELOPE`
    of `n` bins has a finite `coord_end` with
    `coord_start + (n - 1) * coord_step < coord_end <= coord_start + n *
    coord_step`, within `1e-9 * coord_step` (for the rounding of a float
    product), and `coord_end >= coord_start` with no bin. A `RUNS` series has
    `start` and `end` of an integer or float dtype, finite, with
    `end >= start`. An `ENVELOPE` has one integer or float dtype for `min` and
    `max`, and `min <= max` where neither is NaN. `POINTS` has an integer or
    float `coord`. A bad value raises `ValueError`.
  - A NumPy bool, integer or float scalar in `meta` is stored as a Python
    `bool`, `int` or `float` (`np.float32`, `np.int64` and `np.bool_` raised
    `TypeError`), and each string field and each key is a plain `str`, so the
    round trip is exact (review 2026-10-07 6.5, #69). A byte other than 0 in a
    decoded bool array is `True`.
  - A copy of a `Series` from `pickle` or `copy.deepcopy` is made by the
    constructor, so it is checked, and has read-only arrays and `FrozenDict`s.
- **One kept function for each measurement** (review 2026-10-05 6.3, #45).
  `pns_levels.pns_levels` and `grad_spectrum.gradient_spectrum` keep their
  results, as `pns_levels_for` and `gradient_spectrum_for` did, and those two
  names and the module `pns` go away (see "Removed"). `gradient_peaks` keeps
  the result of the whole sequence, and `block_gradient_values` its result.
- **The series `pns_total`.** Its `meta` has no key `asc_file`. The other keys
  do not change.
- **The `$INCLUDE` lines of a Siemens `.asc` file** (review 2026-10-07 6.6,
  #84). `asc.read_gradient_asc` matches `$INCLUDE` in any case, a name in
  double quotes (it can have spaces), and a comment after the name that starts
  with `#` or `//`. Any other line that starts with `$INCLUDE` raises
  `ValueError` that names the file, the line number and the line. Before,
  these lines were ignored, so the fields of the included file were missing
  with no error. A field of an included file replaces a field of the same name,
  also one that the including file sets after the `$INCLUDE` line. A cycle of
  includes raises `ValueError` that names the cycle (#53).
- **The names of the interface** (review 2026-10-07 6.1, #85). `docs/usage.md`
  and `docs/implementation.md` give `SeriesKind` (`series.SeriesKind`), the
  `Analysis` protocol (`analyses.Analysis`), `FrozenDict` (`series.FrozenDict`)
  and the five analysis objects. Each name of a module that no document gives
  has a `_` at the start: `grad_spectrum._CHUNK_WINDOWS` and
  `pns_levels._CHUNK_SAMPLES` (the chunk sizes, which a test can still set) and
  `asc._INCLUDE_LINE`. `tests/test_interface.py` checks both rules.
- **The documents.** `docs/usage.md` is a guide by task, and the new
  `docs/implementation.md` has the exact definitions, the rules for the rare
  cases of the gradient waveform, the algorithms and the cost of each call
  (#65).
- **Speed.** One run on an Apple M1 Max, 100,000 blocks, from `0.1.0rc5` to
  this release. `build_repeating(20000)` has 258 unique gradient events, and
  `build_worst(20000)` has 20,002 (`tests/scale_sequences.py`). Each run
  reads the same `.seq` file.

  | | `build_repeating(20000)` | `build_worst(20000)` |
  |---|---|---|
  | `sequence_index` | 60 ms to 33 ms | 63 ms to 33 ms |
  | The first `gradient_peaks` of the whole sequence | 17 ms to 52 ms | 577 ms to 210 ms |
  | 1000 windows of `gradient_peaks`, one TR each | 8.1 s to 0.68 s | 390 s to 0.72 s |
  | `gradient_spectrum` | 1.26 s to 0.88 s | 1.58 s to 1.04 s |
  | `pns_levels`, example hardware | 0.94 s to 0.91 s | 1.61 s to 1.46 s |

  A window of `gradient_peaks` costs the blocks in the window, not all the
  blocks (#46, #56), and `gradient_peaks` makes the values of each unique event
  with numpy over the pooled points (#75: 1.6 ms for 20,002 events, about
  255 ms before). `sequence_index` reads the block table as one array (#77),
  and an event ID of 10^8 no longer allocates a table of 10^8 entries.
  `block_samples` gathers the samples of the unique events with one indexed
  copy (#76). `gradient_spectrum` does the steps of scipy's `spectrogram`
  itself and takes the magnitude of the kept bins only, about 1/25 of the bins
  at the defaults (#22), with `scipy.fft.rfft` (#78): its values equal those of
  `spectrogram` within 1e-12 of the largest value. The first call of
  `gradient_peaks` is slower for a sequence with few unique events: the vector
  peak of each block is now read from the exact polylines of the whole file.
  `docs/implementation.md` has the times of each call.

### Added

- **`snapshot`**: `load(source)` and `Snapshot`, with the properties `sequence`
  and `source` (#80). See "Changed".
- `analyses.registry(*, strict=True)` and `analyses.RegistryWarning`, a
  subclass of `UserWarning` (#83).
- `AnalysisSpec.necessary` and `AnalysisSpec.defaults` (#47), and
  `analyses.RASTERS`, the tuple of the names that `AnalysisSpec.rasters` can
  have (#81).
- The argument `max_bytes` of `series.decode_array` and `Series.from_obj`, and
  the key `"format"` (1) of `Series.to_obj` (#82).
- `series.FrozenDict` (#85).
- `sampling.gradient_sampler(snap)`, the public way to make a
  `GradientSampler` (#61), and `sampling.sequence_samples(index, dt)`, the
  number of samples of a sequence, which `pns_levels` and `gradient_spectrum`
  use (#52).
- `GradientSampler.block_samples(axis, first, stop, dt, *, skip=0,
  count=None)`: the samples `skip` to `skip + count - 1` of the range, bit for
  bit, without the samples of the first and the last block outside them (#23).
  A `skip` or a `count` below 0, or `skip + count` above the samples of the
  range, raises `ValueError`.
- `asc.hardware_from_asc(path)`: the `hardware` pair `(struct, label)` of a
  Siemens gradient `.asc` file, `(asc_to_hw(asc), hardware_name(asc))` with the
  `$INCLUDE` rule of `read_gradient_asc`. It is the one reader of a vendor
  file; the PNS functions take only the pair (#27).
- `pns_levels.BIN_S` and the argument `bin_s` (#29).
- `seq_index.has_gradients(index)`, which is true when the index has a
  gradient event on any axis, and `seq_index.NO_GRADIENTS_IN_WINDOW` (#30).
- `extensions.refuse_unsigned(seq)` (#43): `ValueError` when
  `seq.signature_value` is not a `str` or is `''`. `load` calls it. The check
  is for the presence of a hash only: the package does not compute the hash
  again, and pypulseq's `read` does not check it against the file. pypulseq
  keeps the hash on the object when the object changes, so a sequence that
  was changed with `add_block` after `read` of a signed file, and a read of an
  unsigned file into an object that read a signed file before, pass the
  check. `load(path)` reads into a new object, so it has neither case.
- `_equality.FrozenDict` and `_validate.real`, for the rules above (private
  modules, #30).

### Removed

- `seq_index.block_cache_off`. The sequence of a snapshot has
  `use_block_cache` False, so the block cache of a caller's sequence is not
  touched. Before, `rf_events`, `grad_events` and `adc_events` kept the block
  cache of the caller's sequence off across a `yield`, so a generator that a
  caller did not run to its end left it off (review 2026-10-07 1.5).
- `pns.pns_levels_for`, `grad_spectrum.gradient_spectrum_for` and the module
  `pns`. Call `pns_levels.pns_levels(snap, hardware=..., ...)` and
  `grad_spectrum.gradient_spectrum(snap, ...)`: each keeps its result (#45).
- `pns.pns_prediction` and `pns.PnsPrediction`. Call
  `pns_levels(snap, hardware=..., ...)` and read the fields `reason`,
  `hardware`, `peak_hz_per_t`, `peak_time_s` and `axis_peaks_hz_per_t` of its
  `PnsLevels`. `PnsPrediction.asc_file` has no replacement (see Changed) (#25).
- `GradientPeaks.whole_rms_hz_per_m`. Use
  `gradient_peaks(snap).axes[axis].rms_hz_per_m`, which is kept, so a second
  call costs nothing (review 2026-10-06 6.4, #63).
- `pns.peak_tr_window` and `seq_utils.hold_samples`. They were helpers for the
  drawings of pulseq-reports. pulseq-reports takes them over: copy them from
  the tag `v0.1.0rc5` (`pulseq_analysis/pns.py` and
  `pulseq_analysis/seq_utils.py`) (#25).
- `pns_levels.PNS_LIMIT`. The package checks no limit. The limit of a
  fraction of 1, in Hz/T, is `abs(gamma)` (#25).
- `asc.EXAMPLE_HARDWARE`, the argument `gradient_asc` of `pns_levels`, the
  parameter `hardware=None` (the example hardware), `PnsLevels.asc_file` and
  the `meta` key `asc_file`. Give `hardware=asc.hardware_from_asc(path)` for a
  file, or `hardware=(safe_example_hw(), "<a label>")` for the example
  hardware (#27).
- `pns_levels.EXACT_MAX_S` and `pns_levels.DISPLAY_BINS`. Give `bin_s`, or use
  `pns_levels.BIN_S` (#29).
- The old names of the rename (`grad_limits`, `GradientLimits`,
  `gradient_limits`, `GRADIENT_LIMITS` and the ID `gradient.limits`). No alias
  stays (#26).
- The public names `grad_spectrum.CHUNK_WINDOWS`, `pns_levels.CHUNK_SAMPLES`
  and `asc.INCLUDE_LINE` (they are `_CHUNK_WINDOWS`, `_CHUNK_SAMPLES` and
  `_INCLUDE_LINE`, #85).
- The `index` argument of `rf_events`, `grad_events`, `adc_events` and of the
  constructor of `GradientSampler`: they take the snapshot only.

### Fixed

- **The kept results were old after a change of the sequence** (review
  2026-10-04 1.1, review 2026-10-07 1.1, #19, #80). `sequence_index`,
  `pns_levels_for` and `gradient_spectrum_for` kept their results by the
  object, the number of blocks and the last block ID. When file B was read into
  the object that held file A, with the same number of blocks, they gave the
  values of A. For example, `sequence_index(seq).end_s` was 0.0034 s, and a new
  object gave 0.0074 s. A change in place that keeps both numbers (see "The
  snapshot") gave the old values too. The snapshot owns its sequence, so no
  result is old.
- **The shared `SequenceIndex` was writable** (review 2026-10-04 1.2, #20). A
  write into an array changed every later gradient, PNS and spectrum result for
  that sequence. The arrays are read-only now.
- **A possible collision of the key of the gradient events** (review
  2026-10-04 1.3, #21). `_range_result` of `grad_limits` (now `grad_peaks`)
  computed `(gx * base + gy) * base + gz` in an `int64`. Above about 2.6
  million unique gradient events, two triples could get one key. The module
  now has one helper for the distinct triples. The output is the same, bit for
  bit.
- **A long block made `pns_levels` quadratic** (review 2026-10-04 2.1, #23).
  `pns_levels` asked `block_samples` for each whole block that touched a chunk
  of 30,000 samples, so a block longer than a chunk was sampled again for each
  chunk. A trapezoid with a delay of 120 s in one block took 17 s with the
  example hardware, and 1200 blocks of 0.1 s took 0.85 s. The one block takes
  0.83 s now. The output is the same, bit for bit.
- **A PNS peak of 0 had a peak time** (review 2026-10-04 1.4, #30). When the
  gradients all have the amplitude 0, `PnsLevels.peak_time_s` was `0.5 * dt`.
  It is `None` now, and the model does not run a second time for it. This is
  the rule of `gradient_peaks` for a largest value of 0.
- **A bad hardware struct gave different errors** (review 2026-10-05 1.2,
  #37), and a result for a sequence with no gradient event (see "The PNS
  hardware is necessary").
- **`gradient_peaks` read the events before it checked `window`, and a window
  just past the end gave a reversed range** (review 2026-10-05 1.3 and 1.4,
  #38). The junction step into a delayed event had the time of the block
  start; it has `start + delay` (review 2026-10-05 1.5).
- **The three models of the gradient between two events** (review 2026-10-06
  1.1, #58). A block ends at `a = 0.9 * max_slew * grad_raster_time` and holds
  it. The next block has an extended trapezoid that starts at `a` after a delay
  of 100 us. `gradient_limits` counted no step (the two blocks join at `a`) and
  gave the largest slew 6.5e8 Hz/m/s, the slope of a ramp. The waveform has two
  steps in the delay, from `a` to 0 and from 0 to `a`: the samples of
  `block_samples` showed them, with the slew 6.5e9 Hz/m/s, 10 times more, and
  the RMS used 0 in the delay. There is one waveform now: `gradient_peaks`
  gives 1.3e10 Hz/m/s here (the ramps of a long gap). See "The gradient
  waveform between two events".
- **The spectrum attenuated a gradient at the end of a sequence, and counted
  the samples with its own rule** (review 2026-10-06 1.2 and 1.3, #52). See
  "The end of the spectrum, and the number of samples".
- **A `Series` could be changed after its checks** (review 2026-10-06 1.4,
  #53). `s.arrays["value"] = shorter_array` and `s.meta["k"] = object()`
  worked, and `to_obj` then raised. `arrays` and `meta` are `FrozenDict`s.
  A copy from `pickle` or `copy.deepcopy` had writable arrays and no check,
  and `a.flags.writeable = True` made a frozen array writable again (review
  2026-10-07 1.8, #69).
- **`decode_array` could expand a small object without a limit** (review
  2026-10-06 1.5, #53). It decompressed all the data before it compared the
  length. It stops at `length * itemsize + 1` bytes.
- **`Series.from_obj` raised `OverflowError`** (review 2026-10-07 1.6, #69),
  for a coordinate of `10**400`. The contract is `ValueError`, and `from_obj`
  and `decode_array` raise only that, also for a `"length"` of `10**30`.
- **An `$INCLUDE` cycle recursed until `RecursionError`** (review 2026-10-06
  1.5, #53), and an `$INCLUDE` line in lower case, with a quoted name that has
  spaces, or with a comment, was ignored with no error (review 2026-10-07 6.6,
  #84). See "The `$INCLUDE` lines of a Siemens `.asc` file".
- **At a step inside one event, `block_samples` took the later value**
  (review 2026-10-07 1.4, #73). See "The values that change".
- **`rf_events`, `grad_events` and `adc_events` left the block cache of the
  caller's sequence off** (review 2026-10-07 1.5), when the caller did not run
  the generator to its end. They give tuples now, and `block_cache_off` is
  gone.
- **Documentation errors** (section 3 of each review). The docstrings, the
  descriptions of the analyses, `docs/usage.md`, `docs/implementation.md` and
  `TESTS.md` say what the code does. Among them: "the four dicts" of
  `BlockGradientValues` is "the five dicts"; the junction step of the first
  block is the step from 0 to the first value of the block, not 0; the
  largest slew of `gradient.peaks` is the larger of the largest segment slew
  and the largest junction step; the `get_block` sentences name the functions
  that read one block for each unique gradient event; the docstring of
  `Series` gives the units of the values and the rules of `meta` and of
  `name` in place; `raster_block_lengths` gives one bool for all the blocks.
  (#21, #23, #26, #30, #39, #54, #70).

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
