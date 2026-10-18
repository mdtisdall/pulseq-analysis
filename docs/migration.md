# Migrating from 0.1.0rc6 to 0.1.0rc7

This guide is for the maintainers of pulseq-checks and pulseq-reports. It gives,
for each name of `0.1.0rc6` that the two projects use, the name that replaces it
in `0.1.0rc7`, and what else changes with it. A caller of `0.1.0rc5` or earlier
applies the entry of `0.1.0rc6` in [`CHANGELOG.md`](../CHANGELOG.md) first.

`0.1.0rc7` breaks the callers of `0.1.0rc6`. The package reads Pulseq files
itself, through an interpreter, and no longer through pypulseq. An incompatible
change has no alias: an old name raises `ImportError`, `AttributeError` or
`TypeError`. [`docs/usage.md`](usage.md) describes each new name;
[`CHANGELOG.md`](../CHANGELOG.md) lists every change.

Contents:

1. [What each project changes](#1-what-each-project-changes)
2. [Install and dependencies](#2-install-and-dependencies)
3. [The modules that moved](#3-the-modules-that-moved)
4. [`load`](#4-load)
5. [The snapshot](#5-the-snapshot)
6. [The events](#6-the-events)
7. [The block table](#7-the-block-table)
8. [SAFE hardware and `.asc` files](#8-safe-hardware-and-asc-files)
9. [The values that changed](#9-the-values-that-changed)
10. [The new names](#10-the-new-names)

## 1. What each project changes

The rows are what the two projects read from `0.1.0rc6`. The last column says
where this guide gives the details.

**pulseq-checks.**

| It reads from `0.1.0rc6` | Now | Section |
|---|---|---|
| The registry: `registry()`, `Analysis.compute`, `to_series`, the `AnalysisSpec` fields `id`, `version`, `params` and `rasters`; `Series` | The same API and the same `spec.version` (1 for each analysis), in `analyses.registry` and `analyses.series`. One parameter changes its name: `window` of `gradient.peaks` is `range_s`, the name of the result field `GradientPeaks.range_s` (`spec.params == ("range_s",)`, `compute(snap, range_s=(start_s, end_s))`); `window=` raises `TypeError`. | [3](#3-the-modules-that-moved) |
| The values of `seq.index` (`block_id`, `start_s`), `gradient.peaks`, `gradient.blocks`, `pns.safe.levels` and `gradient.spectrum` | The same meaning. `block_id` is the block ID of the file. A time of `gradient.peaks` whose block is `None` (a value of 0) is `None`, not 0.0. | [7](#7-the-block-table), [9](#9-the-values-that-changed) |
| A read of each file once for each target, with the target's `pp.Opts` | One `load(path)` for all targets. The snapshot has no target. The read for pypulseq's `check_timing` stays pulseq-checks' own. | [4](#4-load) |
| `ctx.sequence` of a check | It becomes the snapshot. The snapshot has no `sequence`: use `snap.data` and `snap.decoding`. | [5](#5-the-snapshot) |
| A file that breaks a rule: the check `timing.rasters` | `load` raises `SeqFileError` (a `ValueError`) with `violations`, each a `Violation(rule, section, line, message)`. `definitions.raster-missing` and `definitions.raster-invalid` are the codes of a missing and an invalid raster. | [4](#4-load) |
| RF, ADC and soft-delay timing: the check `timing.pypulseq` runs pypulseq's `check_timing` on its own read | Unchanged, so pulseq-checks depends on pypulseq (or on the extra). For checks of its own, the package gives `decode_rf`, `decode_adc`, `snap.data.rasters`, `snap.data.extensions` and the block table. | [2](#2-install-and-dependencies), [6](#6-the-events) |
| SAFE hardware as the pair `(namespace, label)`, the namespace in the form of `asc_to_hw`; `asc.read_gradient_asc` and `asc.hardware_name` | `hardware=SafeHardware.from_namespace(namespace, label)`: a `SafeHardware`, whose `name` is the label (`asc.safe_hardware(asc)` in place of `asc_to_hw`). The pair raises `TypeError`. The two `asc` functions keep their names. | [8](#8-safe-hardware-and-asc-files) |
| `limits_from_sequence` and the `gamma` of a `pp.Sequence` | Unchanged: they stay in pulseq-checks. The model has no gamma. | |

**pulseq-reports.**

| It reads from `0.1.0rc6` | Now | Section |
|---|---|---|
| `pp.Sequence().read(path)` | `load(path)`. | [4](#4-load) |
| `rf_library.data` rows by position, `rf_library.type` | `decode_rf(snap.data)` by RF ID, or the table `snap.data.rf`. `RfEvent.use` is the type. | [6](#6-the-events) |
| `get_block` and the events it gives | `decode_rf`, `decode_gradients` and `decode_adc` on `snap.data`, and the IDs in `snap.data.blocks`. | [6](#6-the-events) |
| The RF delay, `t`, `signal`, `shape_dur`, offsets, `use` and `center` of each unique RF event; the delay, `num_samples` and `dwell` of each unique ADC event | The fields of `RfEvent` and `AdcEvent`. `signal`, `shape_dur`, `use` and `center` differ in form from pypulseq's; the dead times are not fields. | [6](#6-the-events) |
| `pp.calc_rf_center` | `RfEvent.center`. It is `None` in a 1.4 file, where pypulseq's `read` stored the peak. | [6](#6-the-events) |
| `block_events` columns, `block_durations`, `pp.calc_duration` | `snap.data.blocks` (the IDs of the events of each block, in play order) and `snap.data.block_durations_s`. | [7](#7-the-block-table) |
| `definitions`, `rf_raster_time` | `snap.data.definitions` (the text of each definition) and `snap.data.rasters.rf`. | [5](#5-the-snapshot) |
| `seq.system.gamma`, the fallback gamma | None. The model has no gamma: the caller chooses it. | |
| `gradient_peaks(snap, window=(start_s, end_s))` (the `gradient_limits(seq, window=...)` of `0.1.0rc5`, after the entry of `0.1.0rc6` in `CHANGELOG.md`) | `gradient_peaks(snap, range_s=(start_s, end_s))`, the name of the result field `GradientPeaks.range_s`. `window=` raises `TypeError`. The values do not change. A time whose block is `None` (a value of 0) is `None`, not 0.0. | [9](#9-the-values-that-changed) |
| `hold_samples`, `peak_tr_window` | Unchanged: they stay in pulseq-reports. | |

pypulseq is not needed to read a file. A project needs it only to build
sequences in memory or to call a pypulseq function itself.

## 2. Install and dependencies

| | `0.1.0rc6` | `0.1.0rc7` |
|---|---|---|
| Dependencies | numpy, scipy, `pypulseq>=1.5.0.post1` | numpy, scipy |
| pypulseq | required | the extra `pypulseq` (`pulseq-analysis[pypulseq]`, `pypulseq>=1.5.0`) |
| The pin of `[tool.uv.sources]` (the fork `3c3bd85`) | applies to the dependency | stays, for the `dev` group and the extra |
| pulseq-cpp-siemens | none | a separate distribution that adds the interpreter `cpp-siemens` |

No module of the package imports pypulseq. `load(path)`, every analysis, `asc`
and `SafeHardware` work without it. These need it:

- `load(seq)` and `seqfile.read_pypulseq(seq)` take a `pypulseq.Sequence`, which
  a caller builds with pypulseq.
- `safe_example_hw` and `asc_to_hw` are functions of pypulseq.
- A project that imports pypulseq itself must depend on it, or on the extra.
  pulseq-checks does, for `check_timing`; so does pulseq-reports if it keeps
  calling `calc_rf_center`.

**The fork pin.** Under uv, the extra and the `dev` group resolve to the fork
commit `3c3bd85`, as the dependency did. uv applies the pin to a project that
depends on pulseq-analysis by git URL; pip does not. pulseq-analysis,
pulseq-checks and pulseq-reports pin the same commit, and move together to a
pypulseq release when one has the six changes of the fork (`TODO.md`).

**pulseq-cpp-siemens.** The two distributions have the same version and move in
step. For `0.1.0rc7`, both are `0.1.0rc7`. pulseq-cpp-siemens needs only numpy;
its extra `analysis` (`pulseq-cpp-siemens[analysis]`), for the interpreter
`cpp-siemens`, requires `pulseq-analysis>=0.1.0rc7,<0.2`. Install the same
version of both. A plugin of another protocol version raises `TypeError` when it
is chosen. pulseq-analysis has no dependency on pulseq-cpp-siemens, in its code
or in its metadata. [`docs/usage.md`](usage.md#0-install) has the install lines.

**A plugin of your own.** Its decoding implements every member of the protocol
`synth.Decoding` of version 1, which includes `gradient_variants()`: return
None when each gradient event decodes alike in every block that plays it, or
an int64 array (blocks, 3) that says which blocks and axes decode an event
alike ([`docs/usage.md`](usage.md), section 8). Version 1 is not released, and
it changed in place: `gradients_at(block_index, time_us, rotated=None)`, with
the times in µs, is `gradients_at(block_index, time_s, rotated=None)`, with
the times in s from the start of each block, as the rest of the API. A decoding
whose reader takes µs converts them itself (`cpp-siemens`: `time_s * 1e6`). A
call with `time_us=` raises `TypeError`.

## 3. The modules that moved

The modules are in three subpackages, in layers: `analyses` imports from
`synth`, `synth` from `seqfile`. There are no aliases. An import of an old path
raises `ModuleNotFoundError`.

| `0.1.0rc6` | `0.1.0rc7` |
|---|---|
| `analyses` (the registry: `registry`, `Analysis`, `AnalysisSpec`, `RegistryError`, `RegistryWarning`, `GROUP`, `RASTERS`, `SEQ_INDEX` and the other four analysis objects) | `analyses.registry`. The API and each `spec.version` are unchanged, but for the parameter `window` of `gradient.peaks`, which is `range_s` ([section 1](#1-what-each-project-changes)). |
| `series` (`Series`, `FrozenDict`, `SeriesKind`, `encode_array`, `decode_array`) | `analyses.series` |
| `snapshot.Snapshot` | `synth.Snapshot` (`synth.snapshot.Snapshot`) |
| `snapshot.load` | `analyses.load` (`analyses.loading.load`) |
| `seq_index` | `synth.seq_index` |
| `asc` | `analyses.asc` |
| `pns_levels` | `analyses.pns_levels`; `SAFE_FIELDS` is in `analyses.safe` |
| `grad_peaks`, `grad_spectrum` | `analyses.grad_peaks`, `analyses.grad_spectrum` |
| `sampling`, `seq_utils` | `synth.sampling`, `synth.seq_utils`. `GradientSampler.sample` and `GradientSampler.block_samples` take the axis as `"x"`, `"y"` or `"z"`, as the results name it, in place of `"gx"`, `"gy"` or `"gz"`, which raise `ValueError`: `sample("gx", t)` becomes `sample("x", t)`. The values do not change. `GradientSampler(snap)` raises `TypeError`: `sampling.gradient_sampler(snap)` is the one way to make a sampler, and `GradientSampler` stays its type. |
| `extensions` (`refuse_rotations`, `refuse_unsigned`) | removed ([`load`](#4-load)) |

The entry points of the five analyses now name
`pulseq_analysis.analyses.registry:SEQ_INDEX` and its four siblings. Their group
stays `pulseq_analysis.analyses`, and their names (`seq.index`,
`gradient.peaks`, `gradient.blocks`, `pns.safe.levels`, `gradient.spectrum`)
stay. The `description` of `seq.index` has a new sentence about the gradient
events ([The block table](#7-the-block-table)).

**A name that now means another object.** `from pulseq_analysis.analyses import
registry` gives the submodule `analyses.registry`, where it gave the function
`registry()` in `0.1.0rc6`. Import the function from the submodule:
`from pulseq_analysis.analyses.registry import registry`. The other names of
the old module (`Analysis`, `AnalysisSpec`) raise `ImportError` from
`pulseq_analysis.analyses`; the package `analyses` has only `load`.

The new modules: `seqfile` (`read_seqfile`, `read_pypulseq`, `read_as_written`,
`SequenceData`, the interpreters and their errors), `synth.events`,
`synth.decoding` (`decode`), `synth.scanner` (`Session` and its records) and
`analyses.safe`. [The new names](#10-the-new-names) index them.

**The names of a module.** Each public module has an `__all__`: the names of
the interface that it gives. In `0.1.0rc6`, only `series` had one. A name that
a module only imports from another module still imports, but it is not in the
`__all__` and is not part of the interface, so it can change in any release.
Import it from the module whose `__all__` gives it, for example:

| Imported from | Not part of the interface | Import it from |
|---|---|---|
| `analyses.grad_peaks`, `analyses.grad_spectrum`, `analyses.pns_levels`, `analyses.registry` | `NO_GRADIENTS` | `synth.seq_index` |
| `analyses.pns_levels` | `SAFE_FIELDS` | `analyses.safe` |

## 4. `load`

| | `0.1.0rc6` | `0.1.0rc7` |
|---|---|---|
| Call | `pulseq_analysis.snapshot.load(source)` | `pulseq_analysis.analyses.load(source, interpreter="spec", session=None)` |
| A path | read with pypulseq's `Sequence.read` | read with `seqfile.read_seqfile(path, interpreter)` |
| A `pp.Sequence` | `copy.deepcopy`, then the checks | `seqfile.read_pypulseq(seq, interpreter)`: pypulseq's writer writes it, and the interpreter reads the text. `seq` does not change. |
| How a sequence is recognised | `isinstance` of `pp.Sequence` | by its methods `write` and `remove_duplicates` (the package does not import pypulseq) |
| A `seqfile.SequenceData` | | taken as it is, with no reading: the data of `read_seqfile` or `read_pypulseq`. `interpreter` must be the interpreter that read it, so the data of a plugin is `load(data, data.interpreter)`. The snapshot has the decoding and the warning of `load` of the file. |
| `interpreter` | | `"spec"` (the default), the name of a plugin such as `"cpp-siemens"`, or an interpreter object with its settings |
| `session` | | a `synth.Session`: soft-delay values, the rotation of the field of view, the scaling of the gradients. `None` is the neutral session. |

A sequence in memory is measured as its written file: the reading has pypulseq's
rounding and its `[SIGNATURE]` hash, and `SequenceData.origin` is `"pypulseq"`.
`load(seq)` does not run pypulseq's timing check. `Snapshot.source` is the path
for a file and `None` for a sequence, as before, and `None` for a `SequenceData`.

**Exceptions.**

| Case | `0.1.0rc6` | `0.1.0rc7` |
|---|---|---|
| A sequence or file with no `[SIGNATURE]` hash | `ValueError` | no error; `snap.data.signature` is `None` for a file |
| A rotation in the file | `NotImplementedError` | no error ([the warning](#the-warning)) |
| The interpreter rejects the file | the error of `Sequence.read`, or none | `seqfile.SeqFileError` (a `ValueError`): `violations`, `codes`, `interpreter`, `path` |
| A file outside the package's scope (a version outside 1.4.0 to 1.5.x, a binary file, a folder) | the error of `Sequence.read`, or none | `seqfile.NotSupported` (a `NotImplementedError`) |
| A setting of the session that addresses something the file does not have | | `synth.SettingError` (a `ValueError`): `setting`, `interpreter`, `version`, `reason` |
| A name that no installed interpreter has | | `ValueError` |
| A `SequenceData` that `interpreter` did not read | | `ValueError` that names `data.interpreter` |
| A plugin that does not load | | `ImportError` |
| A plugin of another protocol version | | `TypeError` |
| A `source` that is not a path, a pypulseq sequence or a `seqfile.SequenceData`; a `session` that is not a `synth.Session` | `TypeError` | `TypeError` |

`SeqFileError` and `SettingError` are `ValueError`s, so an `except ValueError`
around `load` catches both. `NotSupported` is a `NotImplementedError`, and now
means a file that is out of scope, not a rotation. A caller that required a
hash checks `snap.data.signature` ([The snapshot](#5-the-snapshot)).

### The warning

`load` emits a `synth.ScannerSettingWarning` (a `UserWarning`) where the
decoding leaves content of the file unapplied, such as a block that plays a
rotation under the default of `cpp-siemens`, whose reader never rotates.
`spec` applies the rotations of a 1.5.1 file, so it has no warning.
`load(data)` of the `SequenceData` of the file emits it too. The warnings of pypulseq about the version of a file are gone.

## 5. The snapshot

`Snapshot` holds the model of the file and its decoding. It has no pypulseq
sequence, no block cache and no `get_block`.

| `0.1.0rc6` | `0.1.0rc7` |
|---|---|
| `Snapshot(sequence, source)` | `load(source)`, the one way to make a snapshot: `Snapshot(...)` raises `TypeError` that names `load`, and `Snapshot` stays the type of a snapshot. For a `seqfile.SequenceData`, `load(data, interpreter)` with the interpreter that read it ([`load`](#4-load)). |
| `snap.sequence` | removed. `snap.data` is the `SequenceData`; `snap.decoding` is its decoding. |
| `snap.sequence.signature_value`, `signature_type` | `snap.data.signature`: `None`, or a `Signature` with `type`, `hash` and `matches` |
| `snap.sequence.definitions` (numbers converted) | `snap.data.definitions`: the tokens of each line, as text |
| `snap.sequence.rf_raster_time` and the other three rasters | `snap.data.rasters`: `gradient`, `rf`, `adc` and `block_duration`, in s |
| `snap.sequence.block_events`, `block_durations` | `snap.data.blocks` and `snap.data.block_durations_s` ([The block table](#7-the-block-table)) |
| `snap.source` | `snap.source`, the same |
| | `snap.interpreter`, `snap.records`, `snap.session`, `snap.rotation_record`, `snap.soft_delay_record`, `snap.fov_record` |

Two snapshots are equal only when they are the same object, and the hash is the
identity hash, as before. A copy from `pickle` or `copy.deepcopy` is a new
snapshot of the same data with no kept results. The `TypeError` of a measurement
that gets no snapshot names `pulseq_analysis.synth.snapshot.Snapshot` and
`pulseq_analysis.analyses.load`.

**The hash.** `snap.data.signature.hash` is the text of the hash in the file.
`matches` says whether it is the hash of the file's bytes: for `spec`, the bytes
of the specification (every byte before the first `[SIGNATURE]` header, without
the `\n` right before it); for `cpp-siemens`, the reader's own check, which
hashes other bytes in a CRLF file (`docs/discrepancies.md`). `matches` is `None`
for an algorithm that `hashlib` does not have. A mismatch is not a rejection.
`load(seq)` always has a signature: the writer makes it. To require a hash,
check `snap.data.signature is not None`, and `matches` if you need the bytes to
agree.

## 6. The events

`0.1.0rc6` had `seq_index.rf_events(snap)`, `grad_events(snap)` and
`adc_events(snap)`. Each gave a tuple of `(number, event)` with pypulseq's
`SimpleNamespace` events of the first block that plays the event. They are
removed. The replacements are in `pulseq_analysis.synth.events`:

```python
from pulseq_analysis.analyses import load
from pulseq_analysis.synth.events import decode_adc, decode_gradients, decode_rf

snap = load("sequence.seq")
rf = decode_rf(snap.data)  # {RF ID: RfEvent}
grad = decode_gradients(snap.data)  # {gradient ID: Trapezoid or ArbitraryGradient}
adc = decode_adc(snap.data)  # {ADC ID: AdcEvent}
```

- **The keys are the IDs of the file.** They are not the numbers of the block
  table, which `rf_events` and its siblings used. Each function gives every row
  of its table, whether a block uses it or not, in the order of the table.
  `decode_gradients` gives the rows of `[GRADIENTS]`, then those of `[TRAP]`:
  they share one ID space.
- **A block's events.** A row of `snap.data.blocks` has the ID of each event of
  the block (`rf`, `gx`, `gy`, `gz`, `adc`), 0 for none.
  `rf[int(row["rf"])]` is the pulse of the block.
- **The number to the ID.** To go from the number of the block table to the ID of
  the file, read the first block that plays the event. For RF and ADC, with
  `index = sequence_index(snap)` (`synth.seq_index`):
  `snap.data.blocks["rf"][index.rf_first]` and
  `snap.data.blocks["adc"][index.adc_first]` give the ID of event `k + 1` at
  position `k`. A gradient number has a file ID only in the blocks that the
  decoding does not give from `gradients_at`
  ([The block table](#7-the-block-table)).
- **`spec` only.** The three functions raise `TypeError` for the model of
  `cpp-siemens`, whose decoding is the reader's own. For `spec`,
  `snap.decoding.gradients` has the same gradient events, decoded once by
  `load`. `load` decodes no RF or ADC event: each call of `decode_rf` or
  `decode_adc` decodes them.
- **No value of the target.** The events do not have `dead_time` or
  `ringdown_time`: pypulseq copies them from `seq.system`, and the model has no
  target. A project takes them from its own target.
- **The units** are s, Hz, Hz/m and rad, as the file defines them. A time is in
  s from the start of the event, which is after its `delay`.

### RF events

Each attribute of an RF event of `get_block` that pulseq-reports reads, and its
field in `events.RfEvent`.

| pypulseq `rf.` | `RfEvent.` | Differences |
|---|---|---|
| `delay` | `delay` | The same value. |
| `t` | `t` | The same values. A pulse without a time shape has `t = (i + 0.5) dwell`. |
| `signal` (an array) | `magnitude`, `phase` | `RfEvent.signal` is a method: `signal(times)` gives the complex signal at any times, 0 outside the pulse. The array of `0.1.0rc6` is `ev.magnitude * np.exp(1j * ev.phase)`, or `ev.signal(ev.t)`. |
| `shape_dur` | `shape_dur` | With a time shape, pypulseq rounds the last time up to the RF raster. A pulse of cells (the times are `(i + 0.5) d`) lasts `n d`, and a pulse of points lasts until its last time. |
| `freq_offset` | `freq_offset` | Hz. |
| `phase_offset` | `phase_offset` | rad. |
| `freq_ppm` | `freq_ppm` | ppm. |
| `phase_ppm` | `phase_ppm` | rad/MHz. |
| `use` | `use` | pypulseq gives a word (`"excitation"`, `"refocusing"`, `"inversion"`, `"saturation"`, `"preparation"`, `"other"`, `"undefined"`). The field is the character of the file: `e`, `r`, `i`, `s`, `p`, `o`, and `u` for a 1.4 file. |
| `center`, and `pp.calc_rf_center(rf)[0]` | `center` | `None` in a 1.4 file, which has no center. pypulseq's `read` computes one for such a file. |
| `dead_time`, `ringdown_time` | none | Values of the target. |
| | `id`, `amplitude`, `mag_id`, `phase_id`, `time_id`, `dwell` | New. The amplitude and the shape IDs identify the pulse without its offsets. `dwell` is the dwell of a pulse of cells, `None` for a pulse of points. |

**The center of a 1.4 pulse.** `calc_rf_center` returns `rf.center` when the
event has one, and else the peak: the middle of the times of the first and the last
sample whose magnitude is at least 0.99999 of the maximum. For a pulse with
`center is None`, call it on the arrays:

```python
from types import SimpleNamespace

import numpy as np
import pypulseq as pp

if ev.center is None:
    center, _ = pp.calc_rf_center(
        SimpleNamespace(signal=ev.magnitude * np.exp(1j * ev.phase), t=ev.t)
    )
```

This gives the value that pypulseq's `read` stored for the same 1.4 file.

### Gradient events

| pypulseq `grad.` | `Trapezoid.` / `ArbitraryGradient.` | Differences |
|---|---|---|
| `type` (`"trap"` or `"grad"`) | the class | `isinstance(ev, Trapezoid)` or `ArbitraryGradient`. `events.GradEvent` is the union. |
| `channel` | none | The axis is the column of the block table that holds the ID: `gx`, `gy` or `gz`. |
| `amplitude` (trapezoid) | `amplitude` | Hz/m. An arbitrary gradient of pypulseq has no `amplitude`; `ArbitraryGradient.amplitude` is new. |
| `rise_time`, `flat_time`, `fall_time` | `rise_time`, `flat_time`, `fall_time` | The same names, in s. |
| `delay` | `delay` | s. |
| `waveform` | `waveform` | The amplitude times the samples, Hz/m. |
| `tt` | `tt` | The same values. |
| `shape_dur` | `shape_dur` | The same value for an arbitrary gradient. pypulseq's trapezoid has none; `Trapezoid.shape_dur` is the sum of the three times. |
| `first`, `last` | `first`, `last` | The amplitude at the start and at the end. A trapezoid has them as properties, both 0.0. |
| `shape_id`, `time_id` | `shape_id`, `time_id` | Arbitrary gradient only. |
| `area`, `flat_area` | none | Compute them from the amplitude and the times. |

`seq_utils.gradient_offsets(g)` and `gradient_points(g, t0)` take an
`events.Trapezoid` or an `events.ArbitraryGradient`, not a pypulseq event.

### ADC events

| pypulseq `adc.` | `AdcEvent.` | Differences |
|---|---|---|
| `num_samples` | `num_samples` | An `int`. |
| `dwell` | `dwell` | s. |
| `delay` | `delay` | The delay as written in the file. |
| `freq_offset`, `phase_offset` | `freq_offset`, `phase_offset` | Hz, rad. |
| `freq_ppm`, `phase_ppm` | `freq_ppm`, `phase_ppm` | ppm, rad/MHz. |
| `phase_modulation` | `phase_modulation` | rad, one value for each sample. pypulseq gives an empty array without a shape; the field is `None`. |
| `dead_time` | none | A value of the target. pypulseq's `read` copies `seq.system.adc_dead_time` into each ADC row, and `get_block` gives it as `adc.dead_time`. It is not part of `delay`. |
| | `id`, `phase_shape_id` | New. |

## 7. The block table

`SequenceIndex.block_id` is the block ID of the file (`snap.data.blocks["id"]`).
It is a `uint32` array; a block ID that does not fit raises `ValueError`. The
other fields keep their layout, which is the contract of `seq.index` version 1.
Blocks are in play order, which is the order of the file.

`start_s` and `duration_s` use the actual duration of each block
(`snap.decoding.block_durations`). It is the stored duration unless the session
sets a soft delay, so the values do not change by default. The stored duration is
`snap.data.block_durations_s`.

The IDs of the events of each block are in `snap.data.blocks`. The package has
no `calc_duration`: the duration of a block is the one the file stores.

**The numbers of the gradient events** (`gx`, `gy`, `gz`, `grad_first`,
`grad_first_axis`) can differ from `0.1.0rc6` in two cases:

- A block whose gradients the decoding gives from `gradients_at` has events of
  its own. These are a block with a gradient event that the decoding rotates by
  a rotation that is not the identity (`spec` from 1.5.1; `cpp-siemens` with
  `rotation="apply"`) or that the session's field of view rotates, which has an
  event of its own on each axis; and a block with a gradient event that the
  field of view scales, or with an event that ends after the end of the block
  (`cpp-siemens` only; `spec` rejects such a file), which has one on each axis
  that has an event. These cases are new:
  `0.1.0rc6` refused a file with a rotation and had no session.
- Two events with equal values and different IDs are two events. pypulseq's
  `read` merged them: its default is `remove_duplicates=True`.

A change in either case moves the later numbers, since the numbers follow the
order of first use, as before. The RF and ADC numbers follow the IDs of the file
in the same way, so the second case changes them too.

## 8. SAFE hardware and `.asc` files

| | `0.1.0rc6` | `0.1.0rc7` |
|---|---|---|
| `asc.hardware_from_asc(path)` | `(SimpleNamespace, label)`, made by pypulseq's `asc_to_hw` | a `SafeHardware`, whose `name` is the label of `0.1.0rc6`. `SafeHardware` has the attributes `name`, `x`, `y` and `z`, as the namespace had, and is checked when it is made. `hardware=hardware_from_asc(path)` does not change. |
| `hardware.name` of a scanner `.asc` file | `"unknown"` (pypulseq's `asc_to_hw` read only `asCOMP.tName`) | `hardware_name(asc)`: `asCOMP[0].tName` or `asCOMP.tName`. The label of the pair was already this, so the label of a result does not change. |
| A file with no gradient scale factors | a printed warning, and 1/pi assumed | `ValueError` that names the field |
| pypulseq's `asc_to_hw(asc)` | the way to a hardware struct | `asc.safe_hardware(asc)` |
| `asc.read_gradient_asc(path)` | pypulseq's `readasc` and the `$INCLUDE` rule | an own reader that gives the same fields; a line that it cannot read raises `ValueError` with the file and the line (`readasc` raised `RuntimeError`) |
| `pns_levels(snap, hardware=...)`, `PNS_SAFE_LEVELS.compute` | the pair `(namespace, label)` | a `SafeHardware`, whose `name` is the label: `hardware=(ns, label)` becomes `hardware=SafeHardware.from_namespace(ns, label)`. The pair raises `TypeError`, whose message names `SafeHardware.from_namespace`. `PnsLevels.hardware` and the `meta` key `hardware` of `pns_total` are the name, the value that the label had. |
| `pns_levels.SAFE_FIELDS` | in `pns_levels` | in `analyses.safe` |
| `seq_utils.gradient_offsets(g)` | a pypulseq event | an `events.Trapezoid` or `events.ArbitraryGradient` |

A `SimpleNamespace` in the form of `asc_to_hw`, such as the one pulseq-checks
builds with `safe_model.hw_from_dict`, is given with its label as
`SafeHardware.from_namespace(ns, label)`:

```python
# 0.1.0rc6
levels = pns_levels(snap, hardware=(ns, label))
# 0.1.0rc7
levels = pns_levels(snap, hardware=SafeHardware.from_namespace(ns, label))
```

The PNS values do not change: the package has its own port of the SAFE code
(`analyses.safe`), with the notices of the licenses of pypulseq's. A hardware
that is not valid raises the `TypeError` or `ValueError` of `0.1.0rc6`, but
when its `SafeHardware` is made, not in `pns_levels`. A label `"nan"`, `"inf"`
or `"-inf"` raises `ValueError` when the `SafeHardware` is made: in `0.1.0rc6`,
`to_series` of its result raised `ValueError`.

## 9. The values that changed

The values of the measurements change from those of the reading of
`0.1.0rc6` only where the sources differ. Nothing raises a `spec.version`.

The versions of the analyses count from `0.1.0`. Until then, each analysis
stays at version 1, also when its contract changes. From `0.1.0`, a change of
the contract of an analysis raises its `spec.version`. Three contracts change in
`0.1.0rc7` with no new version:

- **The axes.** The gradient values are of the axes of the gradients as the
  decoding gives them: the logical axes of the file (x, y, z), each block
  turned by its rotation where the decoding applies it, and turned and scaled
  by the field of view of the session
  ([`docs/usage.md`, section 2](usage.md#2-before-you-start)). In `0.1.0rc6`
  they were the logical axes of the file.
- **The tie of the vector peak** of `gradient.peaks`. The description of the
  analysis gave it to the first block in play order. It now gives it to the
  block of the earliest time with the largest value, which is what the code of
  `0.1.0rc6` already did.
- **The time of a value of 0** of `gradient.peaks`. `AxisResult.peak_time_s`,
  `AxisResult.slew_time_s` and `GradientPeaks.vector_peak_time_s` were 0.0
  when their value was 0 and their block `None`. They are now `None` whenever
  their block is `None`, as `PnsLevels.peak_time_s` already was for a peak of
  0. A caller checks for `None` before it formats or compares a time. The
  values, the blocks and the other times do not change, and the times of
  `gradient.blocks` do not change: each is the time of its block, `start_s`
  for a value of 0.

  | `0.1.0rc6` | `0.1.0rc7` |
  |---|---|
  | `axis.peak_time_s == 0.0`, with `axis.peak_block is None` | `axis.peak_time_s is None` |
  | `axis.slew_time_s == 0.0`, with `axis.slew_block is None` | `axis.slew_time_s is None` |
  | `peaks.vector_peak_time_s == 0.0`, with `peaks.vector_peak_block is None` | `peaks.vector_peak_time_s is None` |

| What | `0.1.0rc6` | `0.1.0rc7` |
|---|---|---|
| Amplitudes and shapes | pypulseq's `read` rounded the amplitude of a gradient or RF event to 6 significant digits and the samples of a shape to 9, and merged the events that were then equal | the values of the file, as float64 |
| The numbers of the events | after that merge | the IDs of the file; see [the block table](#7-the-block-table) |
| A sequence in memory | the sequence itself, copied | the file that pypulseq's writer writes from it: its rounding and its hash |
| A 1.4 gradient with a time shape that starts at 0 | `first` was the last value of the previous gradient on the axis (0 after a gap), `last` the last sample | `first` and `last` are the amplitude times the first and the last sample (D4.5) |
| A 1.4 arbitrary gradient on the default raster, or with a time shape that starts after 0 | read; pypulseq guessed the ends | `spec` rejects it: `layer1.gradient-ends`. The file has no values at the ends of the gradient (D4.4, D4.5). `cpp-siemens` reads it, with the reader's `FLOAT_UNDEFINED` ends. |
| A file that pypulseq read and `spec` rejects | read | `SeqFileError`, for example `definitions.raster-commensurate`, `raster.gradient-*` and `gradient.nonzero-*` |
| A file that pypulseq could not read | an error | read, when `spec` accepts it |
| RF with a time shape | `t` is the shape times the RF raster | a regular shape is cells, and any other is points joined by straight lines (D2.10 to D2.12); one sample at `t0` above 0 plays for one dwell (D3.9) |
| The warnings of the file's version | pypulseq's `UserWarning`s | none |

`cpp-siemens` is new in this release. Its values are the reader's: float32
(D7.2) and its own reading of a time-shaped gradient
(`packages/pulseq-cpp-siemens/docs/specification.md`). `docs/discrepancies.md`
gives, for each D-number, the sources and what `spec` does.

## 10. The new names

Each name is described in [`docs/usage.md`](usage.md) under the heading in the
last column.

| Name | What it is | Heading of `docs/usage.md` |
|---|---|---|
| `analyses.load` | `load(source, interpreter="spec", session=None)` | [1. Quick start](usage.md#1-quick-start) |
| `seqfile.read_seqfile`, `seqfile.interpreter_names`, `seqfile.Spec`, `seqfile.Plugin` | the interpreters, by name or object, and plugins | [The interpreters](usage.md#the-interpreters) |
| `seqfile.SeqFileError`, `seqfile.Violation`, `seqfile.NotSupported` | the rejection of a file, and a file out of scope | [The interpreters](usage.md#the-interpreters) |
| `seqfile.SequenceData` and its tables | the model of the file (`snap.data`) | [The model](usage.md#the-model) |
| `seqfile.read_pypulseq` | a `pypulseq.Sequence` as the file that its writer writes | [A pypulseq sequence in memory](usage.md#a-pypulseq-sequence-in-memory) |
| `seqfile.read_as_written` | the "as written" reading | [The "as written" reading](usage.md#the-as-written-reading) |
| `synth.events.decode_rf`, `decode_gradients`, `decode_adc`; `RfEvent`, `Trapezoid`, `ArbitraryGradient`, `AdcEvent` | the events | [The events](usage.md#the-events) |
| `synth.decode`, `synth.Decoding`, `synth.SpecDecoding` | the decoding of a model by its interpreter | [The interpreters](usage.md#the-interpreters) |
| `synth.Session`, `synth.SettingError`, `synth.ScannerSettingWarning`, `synth.RotationRecord`, `synth.SoftDelayRecord`, `synth.FovRecord` | the scanner session and what a decoding applied | [The scanner session](usage.md#the-scanner-session) |
| `Snapshot.data`, `decoding`, `interpreter`, `records`, `session` | the snapshot | [2. Before you start](usage.md#2-before-you-start) |
| `analyses.safe.SafeHardware`, `SafeAxis`; `asc.safe_hardware` | the SAFE hardware | [5. Predict the PNS on a scanner](usage.md#5-predict-the-pns-on-a-scanner) |
| `PnsLevels.bin_s`, and the `meta` key `bin_s` of the series `pns_total` | the `bin_s` of the call, as a `float`; `bin_samples` does not change | [5. Predict the PNS on a scanner](usage.md#5-predict-the-pns-on-a-scanner) |
| `pulseq_cpp_siemens.interpreter.CppSiemens` | the interpreter `cpp-siemens` | [The interpreters](usage.md#the-interpreters) |

[`docs/findings-for-pulseq-checks.md`](findings-for-pulseq-checks.md) describes
the public readings that pulseq-checks compares to find where the interpreters
and the file differ.
