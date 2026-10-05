# Code review, 2026-10-04

A review of the whole package at commit `8043553` (`0.1.0rc5`), for things
that are incorrect, mis-documented, duplicative or inefficient, and for parts
of the API that do not fit the goals of the project. The line numbers are of
that commit.

Method: a read of every module of `src/pulseq_analysis/`; a check of
`docs/usage.md`, `README.md`, `CHANGELOG.md` (the `0.1.0rc5` entry), the
docstrings, `pyproject.toml` and `TODO.md` against the code; and a review of
`tests/` and `scripts/`, with 14 single-line mutations of a copy of `src/` to
find tests that cannot fail. The findings marked *reproduced* were run against
the pinned pypulseq fork (`a74ab06`).

At this commit, `pytest` gives 678 passed and `nix develop --command
scripts/check` passes.

## 1. Correctness

1. **The kept results go stale when a file is read into the same `Sequence`
   again** (*reproduced*). The caches key on the sequence object, the number
   of blocks and the last block ID. When file B is read into the object that
   held file A, and B has the same number of blocks:

   - `sequence_index` gives the `end_s` of A (0.0034 s, where B has 0.0074 s);
   - `pns_prediction` and `gradient_spectrum_for` give the values of A;
   - `gradient_limits` uses the block times of A with the events of B.

   Files of one protocol often have the same number of blocks. pypulseq's
   `read` sets a new dict in `seq.block_events` (`Sequence/read_seq.py` line 61
   of the fork), so a key on the identity of that dict (with a reference to it
   in the cache entry) finds a new read. The rule is written three times, so
   one shared helper is the place for the fix:
   [seq_index.py:71](../../src/pulseq_analysis/seq_index.py#L71),
   [pns.py:104](../../src/pulseq_analysis/pns.py#L104),
   [grad_spectrum.py:245](../../src/pulseq_analysis/grad_spectrum.py#L245).

   ```python
   seq = pp.Sequence()
   seq.read("a.seq")
   pns_prediction(seq)
   seq.read("b.seq")  # the same number of blocks as a.seq
   pns_prediction(seq)  # the result of a.seq
   ```

2. **The kept `SequenceIndex` is writable** (*reproduced*). Every measurement
   of a sequence shares one index, and its arrays have `writeable` True. A
   change by one caller (`idx.start_s[...] = ...`) changes each later gradient,
   PNS and spectrum result of that sequence. `PnsLevels` is read-only for this
   reason.

3. **The triple key of `_range_result` can overflow int64.**
   [grad_limits.py:457](../../src/pulseq_analysis/grad_limits.py#L457) computes
   `(gx * base + gy) * base + gz`. Two triples can get one key above about
   2.6 million unique gradient events. `_block_vector_peaks`
   ([grad_limits.py:647](../../src/pulseq_analysis/grad_limits.py#L647)) has
   the safe two-step key. The risk is low; share the code.

4. **A peak of 0 has a peak time.** When all the gradients have the amplitude
   0, `peak_time_s` is `0.5 * dt`, not `None`
   ([pns_levels.py:317](../../src/pulseq_analysis/pns_levels.py#L317)).
   `grad_limits` gives no credited block and the time 0.0 for a largest value
   of 0. Minor.

## 2. Efficiency

1. **`pns_levels` is quadratic in the length of one block** (*reproduced*).
   `_read_block_range`
   ([pns_levels.py:414](../../src/pulseq_analysis/pns_levels.py#L414)) asks
   `block_samples` for each whole block that touches a chunk of 30,000
   samples. Thus a block longer than a chunk is made again, for three axes,
   for each chunk. This includes a delay with no gradient, which gets
   `np.zeros` of its full length
   ([sampling.py:182](../../src/pulseq_analysis/sampling.py#L182)).

   | 120 s of sequence | `pns_levels` |
   |---|---|
   | 1200 blocks of 0.1 s delay, each after a trapezoid | 0.87 s |
   | 1 block of 120 s delay, after a trapezoid | 9.78 s |

   Fix: let `block_samples` take a sample range inside its first and last
   block.

2. **The spectrum calculates about 25 times the bins that it keeps.** At the
   defaults, each spectrogram has 7501 frequency bins and the result keeps
   about 300 ([grad_spectrum.py:199](../../src/pulseq_analysis/grad_spectrum.py#L199)).
   That is about 15 MB for each axis and each chunk. An `rfft` of the windows,
   cut before the `abs`, does not make the bins that are not kept.

## 3. Mis-documentation

- `block_gradient_values` "does not read a block with `get_block`"
  ([grad_limits.py:676](../../src/pulseq_analysis/grad_limits.py#L676),
  `docs/usage.md` line 158), and `gradient_limits` reads blocks only where a
  window edge cuts them ([grad_limits.py:18](../../src/pulseq_analysis/grad_limits.py#L18),
  [575](../../src/pulseq_analysis/grad_limits.py#L575)). Both read one block
  for each unique gradient event, through `_event_values` and `grad_events`.
- References to files that do not exist:
  [seq_index.py:121](../../src/pulseq_analysis/seq_index.py#L121) names
  `waveforms._timed_blocks`; `tests/oracles/blocks.py` line 1 names
  `tests/test_waveforms.py`; a docstring of `tests/test_pns_levels.py` names
  `docs/plans/cards-at-scale.md`.
- [grad_limits.py:116](../../src/pulseq_analysis/grad_limits.py#L116):
  "The four dicts". `BlockGradientValues` has five.
- [grad_limits.py:126](../../src/pulseq_analysis/grad_limits.py#L126): the
  junction step is "0 for the first block". It is not 0 when the first event
  starts at a value that is not 0. `docs/usage.md` gives the correct rule.
- "The largest of each array is the value of `gradient.limits`"
  (`docs/usage.md` line 156,
  [analyses.py:166](../../src/pulseq_analysis/analyses.py#L166)) is false for
  the slew: `gradient_limits` takes the larger of the segment slew and the
  junction step.
- [extensions.py:11](../../src/pulseq_analysis/extensions.py#L11) names two
  callers of `refuse_rotations`. There are four (`block_gradient_values` and
  `gradient_spectrum` also call it).
- `pyproject.toml` line 39 says `calculate_pns` in chunks, and `TODO.md` line 8
  says `calc_pns`. The fork has both; the chunks are in `calc_pns`.
- [series.py:130](../../src/pulseq_analysis/series.py#L130) gives units from
  before `0.1.0rc5` as examples (`"1"`, a fraction, and `"mT/m"`), and
  [series.py:1](../../src/pulseq_analysis/series.py#L1) names "design
  section 4.2", a document of pulseq-checks.
- `docs/usage.md` lines 283-285: `raster_block_lengths` gives one bool for all
  the blocks, not one for each block. The text can be read either way.

## 4. Duplication

- In `grad_limits`: the polyline values (peak, integral, slew) in
  `_event_values` and again in the edge-block loop of `_range_result`; the
  junction steps in `_range_result` and again in `block_gradient_values`; the
  deduplication of the event triples in `_range_result` and again in
  `_block_vector_peaks`, with different overflow handling (section 1, item 3).
- Two equalities with different rules: `Series.__eq__` and `_same_value`
  ([series.py:253](../../src/pulseq_analysis/series.py#L253)) ignore the order
  of the keys of `meta`; `_equality.values_equal` compares dicts with their
  keys in order.
- Three validators of a number with different rules:
  `grad_spectrum._number` (any `numbers.Real`, `TypeError`), `series._real`
  (Python and numpy ints and floats, `TypeError`) and the threshold check of
  `pns_levels` (`int` or `float` only, so `np.float32` and `np.int64` are
  refused, with `ValueError` for a wrong type).
- Constants: `NO_GRADIENTS` in `pns_levels` and in `grad_spectrum`; the axis
  tuples in four modules; `_HW_FIELDS` and `SAFE_FIELDS`; `_has_gradients` of
  `pns_levels` and the same test inline in
  [grad_spectrum.py:163](../../src/pulseq_analysis/grad_spectrum.py#L163).
- Tests: the fixture `write_gradient_asc` in `tests/conftest.py` and again in
  `tests/test_pns_levels.py` line 512, where it overrides the first;
  `tests/scale_sequences.py` copies constants and builders of
  `tests/synthetic.py`, with a reason that is not true now (the file is in
  `tests/`); and `_assert_levels_equal`, `_with_rotation_library`,
  `_waveform_sequence`, `_hardware_for_peak` and `_assert_block_values_equal`
  are each written twice.

## 5. Tests

For 10 of the 14 mutations, all the tests passed. The gaps that matter:

- **The off-raster path with more than one chunk.** When `_read_sampled_range`
  ignores `s0`, all the tests pass, and each chunk of a long off-raster file
  gets the gradients of the first chunk: a wrong PNS result with no error.
  `test_off_raster_block_falls_back_to_sampling` has one chunk.
- **The neighbour events of `GradientSampler.sample`**
  ([sampling.py:121](../../src/pulseq_analysis/sampling.py#L121)). When the
  neighbours are removed, all the tests pass: the gap test uses trapezoids
  that end at 0. Without them, a range that starts after a step at a junction
  is 2.6 % off `get_gradients`. The spectrum chunks and the off-raster PNS
  chunks use this path.
- **No test** for the rebuild of the kept result of `pns_levels_for` after
  `add_block`, an interval across three or more chunks, the two `ValueError`s
  of a bad `window` of `gradient_limits`, or one key for a relative and an
  absolute path of one `.asc` file.
- **Weak checks.** The `window_of_one_sample` case of `tests/test_grad_spectrum.py`
  has no `match=`, so a different `ValueError` passes it.
  `test_pns_levels_is_a_frozen_dataclass` checks only `isinstance`. The oracle
  `tests/oracles/grad_limits.py` imports the production `gradient_points`, so
  it cannot find an error there.
- **Scripts.** `scripts/check_tests_md.py` line 80 splits a test ID on `::`,
  which fails for a parametrize ID that contains `::` (none does now).
  `scripts/time_pns_levels.py` matches the current API.

## 6. The API and the goals of the project

The README says that an analysis takes a sequence and *explicit* physical
parameters, and that it has no limit, no pass or fail and no finding.

1. **The default hardware is not a real scanner.** `pns_levels`,
   `pns_levels_for`, `pns_prediction` and the analysis `pns.safe.levels` use
   pypulseq's example hardware when no hardware is given. A generic runner
   that calls `compute(seq)` gets values for a scanner that does not exist,
   with only the label to show it. `AnalysisSpec.params` gives only the names,
   so a runner cannot know what the default is. Proposal: make the hardware
   necessary, or an explicit value such as `"example"`.
2. **The plot of one caller is in the analysis.** `EXACT_MAX_S` and
   `DISPLAY_BINS` ([pns_levels.py:46](../../src/pulseq_analysis/pns_levels.py#L46))
   are the PNS plot of pulseq-reports (a 10 s view, 812 columns). They set
   `bin_samples`, and thus the series `pns_total`, and no parameter changes
   them.
3. **Helpers of a report are in the analysis package.** `pns.peak_tr_window`
   is for a drawing; `seq_utils.hold_samples` is RF sampling for
   pulseq-reports, and no module of the package uses it;
   `pns_prediction` and `PnsPrediction` give a part of `PnsLevels`, a second
   way to get one value.
4. **Words of limits.** `PNS_LIMIT` is in the interface, but only the tests
   use it. The names `grad_limits`, `GradientLimits` and `gradient.limits`
   suggest a check against limits, which the package does not do. A change of
   these names breaks the callers, so the time for it is before `0.1.0`.
5. **The hardware arguments are not the same.** `pns_prediction` takes only
   `gradient_asc`, `pns_levels_for` takes `gradient_asc` or `hardware`, and
   the analysis takes only `hardware`. Thus a caller of the registry cannot
   give an `.asc` file.
6. **"No result" is given in different ways.** There are two `NO_GRADIENTS`
   constants, and `GradientLimits.reason` has two free strings with no
   constant.
7. **The results have different contracts.** The shared `SequenceIndex` is
   writable (section 1, item 2). The shared `PnsLevels` has dicts that a
   caller can change, and only the documentation says not to.
   `BlockGradientValues` compares by identity, and `PnsLevels`,
   `GradientSpectrum` and `Series` compare by value.
8. **`registry()` does not use the name of the entry point.** The docstring
   says that the name is the ID, but
   [analyses.py:376](../../src/pulseq_analysis/analyses.py#L376) uses
   `spec.id` and does not compare the two. An entry point with a different
   name gets the ID of its `spec`, with no error.

The thresholds of `PnsLevels.above` agree with the goals: the caller gives
them, and the result tells where the values are high, not whether a check
passed.

## 7. Order of the fixes

1. The stale kept results (section 1, item 1), with one shared cache helper.
2. Read-only arrays in `SequenceIndex` (section 1, item 2).
3. Tests for the off-raster path with more than one chunk and for a sampled
   range after a step at a junction (section 5).
4. The block range of `block_samples` (section 2, item 1).
5. The documentation errors of section 3.
