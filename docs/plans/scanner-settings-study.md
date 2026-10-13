# Study: what the scanner's interpreter sets or applies, and what the C++ reader gives without it

Branch `docs/scanner-settings-study`. This is a study, not a plan: it decides nothing. It feeds
the planned decision P20 (the settings of the interpreter object that simulate the scanner's
interpreter beyond the reader) and task R9 (rotations), which wait for it. Section 11 lists the
decisions for the user.

"The plan of the redesign" is `docs/plans/parser-redesign.md` (P1-P19, Q1-Q6). "The reader" is
`ExternalSequence` of pulseq/pulseq at `c7469123`, the reader of the scanner's interpreter on
Siemens systems. "cpp:N" is a line of its `src/ExternalSequence.cpp`, and "h:N" a line of its
`src/ExternalSequence.h`. "spec:N" is a line of `doc/specification.tex` of the same commit (the
specification 1.5.3, draft). "Sequence.m:N" is a line of `matlab/+mr/@Sequence/Sequence.m` of
the same commit. "pypulseq" is the installed pypulseq 1.5.0.post1, and "sequence.py:N" and
"read_seq.py:N" are lines of its `Sequence/sequence.py` and `Sequence/read_seq.py`. "The
driver" is the C++ oracle `tests/cpp_oracle/driver.cpp`. "The binding" is
`packages/pulseq-cpp-siemens/src/reader.cpp`. As in the plan of the redesign, "the scanner's
interpreter" is the program on the scanner that plays a Pulseq file. Its source is not public.
What it does is known only from the specification, from the reader's comments and hooks, and
from what MATLAB Pulseq and pypulseq simulate.

## 1. The question

The user decided (2026-10-12) that `cpp-siemens` gives what the C++ code actually does (P1,
P14). A simulation of what the scanner's interpreter does beyond the reader (for example, to
apply rotations) is available only as an opt-in setting of the interpreter object. For the
rotation, the user's choice is: by default, warn and give the unrotated gradients; with
`rotation="apply"`, apply the rotation and do not warn.

This study finds each mechanism where the reader stores information and the scanner's
interpreter acts on it. For each mechanism it gives:

1. what the reader stores and exposes, and the hooks that the scanner's interpreter is expected
   to call;
2. the reader's default when no hook is called, and its effect on `gradientsAt`, on block
   durations, and on RF and ADC frequency and phase. This is what `cpp-siemens` gives today;
3. what the driver and pulseq-cpp-siemens call, confirmed by a run;
4. what the specification says the scanner's interpreter does, and what MATLAB Pulseq and
   pypulseq simulate;
5. what an opt-in setting would need, and what `load` could record and warn about.

## 2. The runs

The fixtures of `tests/seqfiles` have every extension, but no fixture attaches a rotation,
soft delay or FOV-relevant label to a block with gradients, RF or ADC
(`valid_1_5_1_rotation_not_played.seq` declares a rotation that no block uses). The study used
two scratch fixtures, outside the repository and not committed:

- `scanner_settings.seq` (1.5.1, 7 blocks):

  | Block (from 0) | Content |
  |---|---|
  | 0 | delay block, `LABELSET ONCE 1` |
  | 1 | trapezoid on GX (1e6 Hz/m, delay 100 us, ramps 100 us, flat 200 us), `ROTATIONS 0.70710678 0 0 0.70710678` (90 degrees about z) |
  | 2 | the same trapezoid, `DELAYS 0 0 1 TE` |
  | 3 | delay block, `TRIGGERS 2 1 0 10` (type 2, channel 1: an input trigger) |
  | 4 | RF (freqPPM 1.5, freq 100 Hz, phase 0.5 rad) during a ramp on GZ, `RF_SHIMS` (2 channels), `LABELSET NOROT 1`, `NOPOS 1`, `PMC 1` |
  | 5 | ADC (freq 50 Hz, phase 0.25 rad) during a trapezoid on GX, `LABELSET ONCE 0` |
  | 6 | delay block, `LABELSET ONCE 2` |

- `noslc.seq`: the same file with the label `NOSLC` (the specification's spelling) in place of
  `NOPOS`.

The tests also used `tests/seqfiles/oracle/koma_v1.5_rotation_radial_tiny.seq` (KomaMRI, 5
blocks, each with a trapezoid on GX and a rotation by 0, 45, 90, ... degrees about z).

The tools were `pulseq-cpp-oracle` (exit status, `--dump`, `--sample`), and
`read_seqfile(path, interpreter="cpp-siemens")` with `synth.decoding.decode` (pulseq-cpp-siemens
in the process). Both load and decode each file with exit status 0 and give the same values. The
sections below give the results.

## 3. Rotations (the ROTATIONS extension)

### 3.1 What the reader stores and exposes

- `load` reads each row `id q0 qx qy qz` as doubles (cpp:1281). It rejects a quaternion whose
  norm is more than 1e-3 from 1 (cpp:1286-1290). It divides the others by their norm
  (cpp:1291-1292), sets `defined` (cpp:1294) and keeps them in `m_rotationLibrary`
  (cpp:1295; h:1285).
- `GetBlock` copies the rotation into `SeqBlock::rotation` (cpp:1871-1879). A second rotation in
  a block gives a warning and is ignored (D48). The default is `rotation.defined=false`
  (cpp:1834).
- Accessors: `isRotation()` (h:702) and `GetRotationEvent()` (h:613, h:719), the struct
  `RotationEvent { bool defined; double rotQuaternion[4]; }` (h:221-225).
- No hook applies the rotation. `gradientsAt` (cpp:3558-3698) and `gradMomentsAt`
  (cpp:3700-3834) read `grad[i]` of each logical channel and never read `rotation`. The only
  user of the quaternion is `rotate_vec3_by_quat` (cpp:2666-2684). The reader calls it in
  `applyRfPhaseModulation` (cpp:2773) and `updateAdcPhaseModulation` (cpp:3024). There, it turns
  the position offset by the conjugate rotation, "because we update the offset, not the
  gradients" (cpp:3024). So the reader assumes that the scanner's interpreter rotates the
  gradients itself (section 5).

### 3.2 The reader's default (what `cpp-siemens` gives today)

The gradients are the file's logical gradients, not rotated. Block durations and RF and ADC
values do not change.

Run, `scanner_settings.seq`, block 1 at 300 us: the oracle's `--sample` and
`CppSiemensDecoding.gradients_at` both give `[1000000, 0, 0]`. The block is rotated by 90
degrees about z, so the scanner plays about `[0, 1000000, 0]`.

Run, `koma_v1.5_rotation_radial_tiny.seq`: blocks 0, 1 and 2 (rotations of 0, 45 and 90 degrees)
each give `[1000, 0, 0]` on the flat top.

### 3.3 What the driver and pulseq-cpp-siemens call

Both report the quaternion and nothing else. The driver has `dump_rotation` (driver.cpp:354-361,
"rotation" in `--dump`, driver.cpp:388). The binding has `has_rotation` and `rotation`
(reader.cpp:390-394), and `SequenceData.extensions.rotations` holds the quaternions after the
reader's division (`pulseq_cpp_siemens/interpreter.py:527`, `_rotations` at `pulseq_cpp_siemens/interpreter.py:588`). Neither calls
anything that rotates. `strict` reads the quaternions as written (D49). `synth.snapshot.load`
refuses a sequence with rotations (`synth/extensions.py:12-41`), and pypulseq cannot read such a
file anyway (section 3.4).

### 3.4 Specification, MATLAB and pypulseq

- Specification: the rotation is "applied to the entire block as a whole" (spec:567). It is a
  normalized quaternion (spec:567-580). X, Y and Z "refer to physical scanner gradient channels"
  (spec:318). Since 1.5.1 an interpreter must stop on a required extension that it does not know
  (spec:460). The reader knows ROTATIONS (cpp:1527-1535), so it accepts a file that requires
  them, although the reader itself does not apply them.
- MATLAB: `waveforms_and_times` always rotates the block's gradients with `mr.rotate3D`. There is
  no flag (Sequence.m:1988-1999). So every consumer of it (`calcPNS`, `gradSpectrum`,
  `testReport`, `calculateKspacePP`) and `SeqPlot` see the rotated gradients. `read` divides by
  the norm (D49, `read.m:182-184`).
- pypulseq 1.5.0.post1: no support. `read` raises `ValueError` "Unknown section code: extension
  ROTATIONS" (read_seq.py:229-230). The run on `scanner_settings.seq` gives that error.

### 3.5 What an opt-in setting needs

- A setting `CppSiemens(rotation="reader"|"apply")`. `"reader"` (the default) is the reader's
  output. `"apply"` gives `R(q) g` for each time of each block that `isRotation()`, with the
  quaternion that the reader normalized (`GetRotationEvent()`). The reader has no code that does
  this, so the rotation is the package's own code (as section 7.6 of the plan of the redesign
  already says). The convention (`q0` is the scalar part; the active rotation of the gradient
  vector, the conjugate of what `applyRfPhaseModulation` applies to the offset) follows
  `rotate_vec3_by_quat` with `c=+1` (cpp:2666-2684). The specification warns that implementations
  get the row and column order wrong (spec:580), so a test should check the result against
  MATLAB's `rotate3D` on `koma_v1.5_rotation_radial_tiny.seq` and `pulseq_make_radial.seq`.
- `gradientsAt` must stay available as the reader gives it (the contract of section 7.3 of the
  plan of the redesign), so the rotated values are a separate output or a separate method (for
  example, `gradients_at(..., rotated=True)`), not a change to the reader's.
- What `load` records: the interpreter with its setting (already on the result, Q6). It can also
  record the number of blocks with a rotation that is not the identity.
- The warning (the user's choice): with `rotation="reader"`, a file in which a block plays a
  rotation that is not the identity gives a warning, for example "N blocks play a rotation;
  the gradients are the logical ones, as the C++ reader gives them; use
  CppSiemens(rotation="apply") for the gradients that the scanner plays". With `"apply"`, no
  warning. This needs decision 1 and decision 2 (section 11): P17 says that pulseq-analysis has
  no warnings, and Q3 and R9 say that `cpp-siemens` applies the rotation.

## 4. Soft delays (the DELAYS extension)

### 4.1 What the reader stores and exposes

- `load` reads each row `id num offset factor hint` into `SoftDelayEvent { int numID; int
  offset; float factor; char hint[32]; }` (cpp:1327-1338; h:195-201). A fractional offset or a
  hint longer than 31 characters is misread (D16).
- `GetBlock` copies the event into `SeqBlock::softDelay` (cpp:1900-1907), with the defaults
  `softDelay.numID=-1` and `actualSoftDelay_ru=-1` (cpp:1837-1838). A second soft delay in a
  block gives a warning and is ignored.
- Accessors: `isSoftDelay()` (h:704), `GetSoftDelayEvent()` (h:598).
- **The hook**: `SeqBlock::setActualSoftDelay_ru(long)` (h:603, h:707) and
  `getActualSoftDelay_ru()` (h:608, h:708). The header says the scanner's interpreter calculates
  the value "based on the extension event" (h:601). `GetDuration()` and `GetDuration_ru()` return
  `actualSoftDelay_ru` when it is 0 or more, and otherwise the file's `duration_ru` (h:705-706).
  `GetStoredDuration()` and `GetStoredDuration_ru()` always return the file's value (h:709-710).
- The reader never evaluates `input/factor + offset`, and it never calls the hook.
- The hook is on a `SeqBlock` object, not on the sequence. `GetBlock` makes a new object, with
  `actualSoftDelay_ru=-1`, on each call (cpp:1820, cpp:1838). So the scanner's interpreter must
  set it on each block object that it plays.
- `GetDuration()` is used inside the reader by `gradientsAt` (0 and a warning after the end of
  the block, cpp:3561-3566), `gradMomentsAt` (the total moment from the end of the block,
  cpp:3710-3712) and `areAllGradientsConstantInRange` (cpp:3899-3900).
- The reader does not check the specification's rule that a soft delay is only in a pure delay
  block (spec:545). The run (block 2: a trapezoid and a soft delay) reads.

### 4.2 The reader's default (what `cpp-siemens` gives today)

Each block lasts its stored duration, the duration that the file's author exported. A soft delay
changes nothing in `gradientsAt`, durations, RF or ADC.

Run, `scanner_settings.seq`, block 2 (stored duration 60, 600 us): `--dump` gives `soft_delay`
`{num_id 0, offset_us 0, factor 1, hint "TE"}` and `duration_ru` 60. `gradientsAt` at 300 us
gives `[1000000, 0, 0]`. At 650 us, past the stored duration, it gives `[0, 0, 0]` (with the
reader's warning).

The stored durations are a consistent state of the sequence. MATLAB's
`getDefaultSoftDelayValues` takes the default UI value from them, `(duration - offset) * factor`
(Sequence.m:2589-2650). So the reader's default is the sequence with the UI values that it was
exported for.

### 4.3 What the driver and pulseq-cpp-siemens call

Both report the event: the driver's `dump_soft_delay` (driver.cpp:325-335, 385) and the binding's
`soft_delay_event` (reader.cpp:454-462). `SequenceData.extensions.soft_delays` holds the rows. Both
report the **stored** duration, `GetStoredDuration_ru()` (driver.cpp:376, reader.cpp:351). Neither
calls `setActualSoftDelay_ru`.

### 4.4 Specification, MATLAB and pypulseq

- Specification: soft delays came in 1.5.0. Only in pure delay blocks, they "rewrite the
  duration of the block at run time" from a value in the scanner's UI (spec:545). The rule is
  `D = input/factor + offset` (spec:550-563, with the examples `TE/2 - 7840 us`,
  `120000 us - TE` with factor -1, and `TR/11 - 126760 us`). UI values that give a negative delay
  are not allowed, and that sets the UI's limits (spec:563). The specification does not say how
  the result is rounded to the block duration raster.
- MATLAB: `seq.applySoftDelay('TE', 40e-3, ...)` (Sequence.m:2518-2587) sets
  `round((value/factor + offset)/blockDurationRaster) * blockDurationRaster` into
  `blockDurations` of each block with that hint (Sequence.m:2564-2576). It warns once for each
  `numID` when the rounding is more than 0.5 us, raises an error for a negative duration or an
  unknown hint, and checks that the hints and `numID`s agree. `waveforms_and_times` uses
  `blockDurations` (Sequence.m:2099), so a soft delay takes effect only after `applySoftDelay`.
- pypulseq: `Sequence.apply_soft_delay(**kwargs)` (sequence.py:1416-1521) has the same rule,
  rounding, warning and errors, and writes `block_durations` (sequence.py:1511).
  `waveforms_and_times` uses them (sequence.py:1673). `synth.snapshot` does not call it. It
  names it only as a method that changes a sequence in place (`snapshot.py:5`), one of the
  reasons that `load` copies the sequence.

### 4.5 What an opt-in setting needs

- A setting, for example `CppSiemens(soft_delays={"TE": 40e-3, "TR": 2.5})` (by hint, as MATLAB
  and pypulseq do; or by `numID`, which the reader's struct also has). For each block with
  `isSoftDelay()` and a hint in the setting, the package computes the duration and calls the
  reader's own hook, `setActualSoftDelay_ru`, on the block object. Then `GetDuration`,
  `gradientsAt`, `gradMomentsAt` and `areAllGradientsConstantInRange` follow it, as on the
  scanner.
- The binding keeps each decoded block in `blocks_` (reader.cpp:930), so it can set the value
  once after `GetBlock`. It must then report `GetDuration_ru()` next to `GetStoredDuration_ru()`.
  The timeline across blocks (R14) must use the actual duration.
- The rule and its rounding are the scanner's interpreter's, which is not public. MATLAB's and
  pypulseq's (`round` to the raster, an error for a negative duration) are the only written rule.
  An unknown hint, a hint whose `numID`s disagree, and a negative result are errors in MATLAB and
  pypulseq. The setting needs the same choices (decision 4).
- What `load` records: the setting, and for each hint, the blocks and the actual durations.
- A warning at the default: the default is the exported sequence (4.2), not a misreading. A
  warning such as "the file has soft delays (TE, TR); the block durations are the exported
  ones" is possible, but the case is weaker than for rotations (decision 4).

## 5. Field-of-view placement, and the flags NOROT, NOPOS, NOSCL and PMC

### 5.1 What the reader stores and exposes

- RF events: `freqPPM`, `phasePPM`, `freqOffset`, `phaseOffset` as written (float32), `use` and
  `center` (h:88-102). ADC events: the same four, and `phaseModulationShapeID` (h:137-147).
  `decodeBlock` changes none of them (cpp:1981-2091). It does not decode the ADC's phase
  modulation shape.
- The flags NOROT, NOPOS and NOSCL are in the enum `Flags` (h:249-262). `decodeLabel` maps them
  (cpp:2378-2380) and stores them in the block's `labelset` (cpp:1880-1888). **PMC** and **TRID**
  are "actively" ignored (cpp:2381-2382): they get no ID (h:257), they give no row in the
  library, and they are not in the block. The reader **does not know `NOSLC`**, the
  specification's spelling (spec:520, spec:537): `decodeLabel` warns "unknown label
  specification" and the label is left out (D50).
- The hooks that the scanner's interpreter calls with the FOV that the user placed. These are
  the reader's own code, in this commit, but nothing in the reader calls them:
  - `applyRfPhaseModulation(positionOffsetPulseqFrame_mm, gradientScaling)` (h:1049,
    cpp:2686-2923). For each block whose RF plays while a gradient changes
    (`areAllGradientsConstantInRange`, cpp:3896-3973), it resamples the RF to the RF raster,
    adds a phase from the gradient moments and the offset (cpp:2834-2884), and inserts a new
    phase shape and RF event into the libraries, and changes the block table (cpp:2886-2916).
    For a block with a rotation, it turns the offset by the conjugate quaternion first
    (cpp:2766-2777).
  - `updateAdcPhaseModulation(...)` (h:1065, cpp:2938-3110): the same for each ADC that samples
    while a gradient changes. It writes a new `phaseModulationShapeID`.
  - `SeqBlock::computeLocalPhaseAndFrequencyOffsets(...)` (h:645, cpp:3975-4010): for an RF or
    ADC during constant gradients, the frequency (`G * scaling * offset`) and phase (from the
    moment) that the scanner adds at run time. During changing gradients it gives 0 (that case
    is in the modulated shapes above).
  - The helpers `gradMomentsAt`, `totalBlockGradMoments`, `areAllGradientsConstantInRange`
    (h:642-644).
  - The comments name the frame of the offset: "the Pulseq logical coordinate frame (x, y, z)"
    (h:1045-1046, h:1061-1062). The parameter `gradientScaling` is a scale factor for each axis.
- None of these hooks reads NOROT, NOPOS or NOSCL. Those flags are only stored, and the scanner's
  interpreter must apply them. `LabelStateAndBookkeeping::updateLabelValues` (cpp:3194-3246),
  which the scanner calls for each block, tracks their current value.
- The rotation of the logical frame into the slice orientation and the gradient scaling are not
  in the reader. The reader has no function that turns or scales `gradientsAt`.

### 5.2 The reader's default (what `cpp-siemens` gives today)

Gradients on the file's axes with no FOV rotation or scaling. RF and ADC frequency and phase as
written, with the ppm terms not weighted (the reader has no system frequency). No phase from a
position offset, and RF and ADC shapes as decoded. Durations do not change.

Run, `scanner_settings.seq`, block 4: RF `freq_ppm 1.5, freq_offset 100, phase_offset 0.5` as
written. The block's `labelset` is `[NOROT 1, NOPOS 1]`, with no PMC. Block 5: ADC
`freq_offset 50, phase_offset 0.25`. `noslc.seq`: the reader prints "unknown label specification"
and "decoding labelset event returned dl_unknown", reads the file (exit status 0), and block 4's
`labelset` is `[NOROT 1]`.

### 5.3 What the driver and pulseq-cpp-siemens call

Both report the RF and ADC values as stored (driver.cpp:251-254, 307-310; reader.cpp:424-440),
and the labels (driver.cpp:337-352; reader.cpp:331-350). Neither calls
`applyRfPhaseModulation`, `updateAdcPhaseModulation` or
`computeLocalPhaseAndFrequencyOffsets`. The binding does not expose `gradMomentsAt`.

### 5.4 Specification, MATLAB and pypulseq

- Specification: the format "omits ... logical coordinate-frame transformations" (spec:136), and
  X, Y and Z are "physical scanner gradient channels" (spec:318). The ppm terms are weighted
  with "the current system frequency of the active nucleus" in MHz and added (spec:361,
  spec:447). ADC offsets are used for "in-plane shifting of the FOV" (spec:457). The flags
  (1.4.1, "EXPERIMENTAL", spec:526-539): PMC, motion correction "may be applied to the current
  block"; NOROT and NOPOS, ignore the rotation or the translation of the FOV placed in the UI or
  by PMC; NOSLC, ignore "FOV / gradient scaling". So the specification implies that the
  scanner's interpreter turns, moves and scales the FOV that the user placed, unless a flag says
  not to, but it does not describe how.
- MATLAB: `waveforms_and_times` adds the ppm terms with `sys.B0` (Sequence.m:2059-2060,
  2085-2086) and the ADC phase modulation (Sequence.m:2087-2097). It does not simulate FOV
  placement. The class `mr.TransformFOV` turns, moves and scales a sequence when it is designed,
  and honours NOPOS, NOROT and NOSCL (`TransformFOV.m:15`, `147`, `267`). MATLAB and pypulseq
  spell the flag `NOSCL` (`getSupportedLabels.m:17`; pypulseq `make_label.py:35`), as the reader
  does.
- pypulseq: `rf_times` adds the RF ppm terms with `system.B0` (sequence.py:1318-1319); the ADC
  gets only `freq_offset` and `phase_offset` (sequence.py:155). No FOV placement.

### 5.5 What an opt-in setting needs

Three separate parts. The measurements of the package today (`analyses`: gradient peaks, PNS,
spectrum, ASC, `safe`) use only gradients. So only the first part changes a measurement.

1. **FOV orientation and scaling** (gradients). A setting such as
   `fov_rotation=<3x3 matrix or quaternion>` and `gradient_scaling=(sx, sy, sz)`, applied to the
   gradients of each block where NOROT (or NOSCL) is not set. The reader has no code for this, so
   it is the package's own, and its order with the ROTATIONS of the block (section 3) must be
   chosen. The sources do not say it. The current value of a flag is a state across blocks
   (`updateLabelValues`), so the package must track it as the scanner does (decision 6).
2. **Position offsets** (RF and ADC phase). The reader has its own code:
   `applyRfPhaseModulation`, `updateAdcPhaseModulation` and
   `computeLocalPhaseAndFrequencyOffsets`. A setting `position_offset_mm=(x, y, z)` could call
   them, and stay exactly the reader's. They change the libraries and the block table (new
   shapes and events), so `SequenceData` (P14, the libraries as read) must be captured before the
   call. These hooks do not read NOPOS, so the package would have to skip the blocks that have
   NOPOS set, as the scanner presumably does.
3. **The system frequency** for the ppm terms: a setting such as `b0=2.89` (T) or
   `system_frequency_mhz=...`. The reader stores the ppm values only.

A warning at the default: the reader's default is the logical frame, the same as the specification
(spec:318) and MATLAB's `waveforms_and_times`. Every file would get a warning, because every
sequence on the scanner is placed. A warning is useful only for files that set NOROT, NOPOS or
NOSCL (then the file says that placement matters) or that have ppm offsets (decision 6).

## 6. The ONCE flag and repetitions of the sequence

### 6.1 What the reader stores and exposes

- `ONCE` is a counter in the enum `Labels` (h:241), after `LAST_ADC_RELEVANT_LABEL` (h:245), so
  it is not an ADC label. `decodeLabel` maps it (cpp:2370) and stores `LABELSET ONCE n` with any
  integer value (cpp:2405-2408). A `LABELINC ONCE` is accepted too.
- The reader has no number of repetitions and no hook for one. It plays nothing: it returns
  blocks by index (`GetBlock`). The repetition loop and the skipping of ONCE blocks are the
  scanner's interpreter's.
- `LabelStateAndBookkeeping` (h:304-371, cpp:3142-3530) gives the current value of each label
  after each block (`updateLabelValues`, cpp:3194-3246; `currVal`, h:374). The scanner's
  interpreter needs it, because ONCE is a state that a LABELSET in an earlier block sets.

### 6.2 The reader's default (what `cpp-siemens` gives today)

Every block, once, in file order: one repetition. The specification says that with one
repetition, ONCE changes nothing (spec:541). So the reader's default is also the specification's
one-repetition case.

Run, `scanner_settings.seq`: blocks 0 (ONCE 1), 5 (ONCE 0) and 6 (ONCE 2) are all decoded, and
the labels are in `labelset`.

### 6.3 What the driver and pulseq-cpp-siemens call

Both report the LABELSET and LABELINC rows of each block (driver.cpp:337-352, 386-387;
reader.cpp:388-389). Neither uses `LabelStateAndBookkeeping`, and neither repeats.

### 6.4 Specification, MATLAB and pypulseq

- Specification: ONCE is a three-state flag for sequences "with repetitions": ONCE=0 on each
  repetition, ONCE=1 only in the first, ONCE=2 or another value only in the last (spec:541). The
  number of repetitions is not in the file. It is a setting of the scanner.
- MATLAB: ONCE is a label (`getSupportedLabels.m:18`, used in `writeTrufi.m`). No function
  repeats the sequence or skips ONCE blocks.
- pypulseq: ONCE is a label (`make_label.py:36-40`). No simulation.

### 6.5 What an opt-in setting needs

- A setting `repetitions=n` (default 1, which is the reader's and the specification's default).
  The timeline plays the blocks n times. In the first repetition it skips the blocks whose
  current ONCE is 2 (or another value that is not 0 or 1), in the last it skips those with ONCE
  1, and in the others it skips both. "Current" is the label state after the block's LABELSET and
  LABELINC, which the package can take from the reader's own `LabelStateAndBookkeeping`
  (`updateLabelValues`) or track itself.
- This is a timeline across blocks, which is the package's own (section 7.6 of the plan of the
  redesign; R14), not a reading of a block. It could be a setting of the interpreter or of the
  measurements (decision 3).
- A warning at the default is not needed: one repetition is a defined case of the specification.
  `load` could record that the file uses ONCE.

## 7. Triggers (the TRIGGERS extension)

### 7.1 What the reader stores and exposes

- `load` reads `id type channel delay duration` into `TriggerEvent` (cpp:1273-1279;
  h:180-186). `GetBlock` copies one trigger into the block, with a warning for a second one
  (cpp:1862-1870), and the default `triggerType=0` (cpp:1832-1833).
- Accessors: `isTrigger()` (true for `triggerType != 0`, h:703), `GetTriggerEvent()` (h:583).
- No hook. The reader does not know which type is an input and which is an output. In 1.4.0 and
  later, a trigger does not change the block duration (only the conversion of files older than
  1.4.0 uses it, cpp:1697-1700).

### 7.2 The reader's default (what `cpp-siemens` gives today)

The trigger is stored. Durations, `gradientsAt`, RF and ADC do not change. No wait for an input
trigger.

Run, `scanner_settings.seq`, block 3: `trigger {type 2, channel 1, delay_us 0, duration_us 10}`,
`duration_ru` 20.

### 7.3 What the driver and pulseq-cpp-siemens call

They report the trigger (driver.cpp:315-323, 384; reader.cpp:384-385, 445-452;
`SequenceData.extensions.triggers`), and nothing else.

### 7.4 Specification, MATLAB and pypulseq

- Specification: TRIGGERS has "input and output" types (spec:109). The example is a cardiac
  trigger (type 2, channel 1) and a digital output (type 1, channel 3) "(Siemens-specific)"
  (spec:507-513). The extension "MAY be subject to rapid changes". The specification does not
  say how long the scanner waits for an input trigger. It names a soft delay for the cardiac
  delay (spec:545).
- MATLAB: `makeTrigger` is a "trigger halt event" on the physio channels; outputs are on
  `osc0`, `osc1`, `ext1` (Sequence.m:745-749, 1236-1257). `waveforms_and_times` ignores
  triggers. `SeqPlot` draws them.
- pypulseq: reads and stores them (read_seq.py:193-196). No simulation.

### 7.5 What an opt-in setting needs

- An output trigger changes no waveform: nothing to simulate.
- An input trigger (type 2) makes the scanner wait for an outside event, such as a heartbeat,
  for a time that the file does not give. A simulation would need a setting such as
  `trigger_wait={channel: seconds}` or a heart rate. It affects only the timeline across blocks
  (gaps with no gradient), so it belongs with repetitions (section 6.5).
- What `load` can record: the blocks with an input trigger. A warning at the default (no wait)
  is possible: "the timeline has no wait for the N input triggers" (decision 7).

## 8. RF shims (the RF_SHIMS extension)

### 8.1 What the reader stores and exposes

- `load` reads `id nchan` and then `nchan` pairs of amplitude and phase (cpp:1340-1373). It keeps
  the event in `m_rfShimLibrary` under its own `id` (cpp:1372; h:208-214). `GetBlock` copies it
  into the block (cpp:1909-1917), with the default `nchan=-1` (cpp:1839). The warning for a
  second shim in a block says "soft delay" (cpp:1911), a copy of the text above it.
- Accessors: `hasRfShim()` (h:720), `GetRfShim()` (h:593), `usesRfShimExtension()` and
  `getRfShimEventByID()` (h:1330-1337).
- No hook. The reader does not apply the amplitudes and phases to the RF, and it does not know
  the number of channels of the hardware.

### 8.2 The reader's default (what `cpp-siemens` gives today)

The RF of one channel as decoded, with no shim. No change to gradients or durations.

Run, `scanner_settings.seq`, block 4: `rf_shim {id 1, nchan 2, amplitudes [1, 0.5], phases [0,
1.57079995]}` (float32), and the RF as decoded.

### 8.3 What the driver and pulseq-cpp-siemens call

They report the shim (driver.cpp:363-371, 389; reader.cpp:395-396, 464-471;
`SequenceData.extensions.rf_shims`), and nothing else.

### 8.4 Specification, MATLAB and pypulseq

- Specification (1.5.1, "highly experimental"): one shim per block, acting only on the RF in
  that block. If `num_chan` does not match the hardware, the interpreter "should probably
  ignore" it, with an error or a warning (spec:584-594).
- MATLAB: stores a complex `shimVector` (Sequence.m:788-793, 1283-1293). `waveforms_and_times`
  and `calcRfPower` do not use it.
- pypulseq: no support. `read` raises `ValueError` (read_seq.py:229-230).

### 8.5 What an opt-in setting needs

No measurement of the package uses RF today, and the result of a shim is the field of several
transmit channels, not one waveform. A simulation needs the coil's channels and fields. The
proposal is: no setting, and `load` records the blocks with a shim (decision 8).

## 9. Other things that the scanner's interpreter sets or applies

| Item | What the reader has | Default (`cpp-siemens` today) | In the package now |
|---|---|---|---|
| Sampling of an oversampled arbitrary gradient (D43) | `SetArbGradCenterSampling(bool)`, `SetArbGradPreserveOversampling()` (h:978-992), `m_ArbGradSamplingMode` (cpp:103, 2123-2146) | `ags_center` | Already a setting: `CppSiemens(oversampling=...)` (P18). It is the model for the settings of this study. |
| `FLOAT_UNDEFINED` first and last of a 1.4 arbitrary gradient (D39) | the sentinel `1.18e-38f` (h:128) | the sentinel, as the reader stores it | P7: follow the reader's default (pulseq-checks reports it). |
| Messages | `SetPrintFunction` (h:910, h:1322) | `cout` | The binding captures them. They are the reasons of a rejection. |
| Label state and ADC bookkeeping | `LabelStateAndBookkeeping`: `updateLabelValues`, `updateBookkeepingRecordsADC` (a comment says the scanner runs it "for every ADC ... in Arbitrary.cpp", cpp:3316), `checkLabelValuesADC` (cpp:3248-3305, false when a label is outside the range seen in preparation), first or last scan in a slice | not called | Not used. It affects the data headers on the scanner, not the waveforms. It is the way to track ONCE (section 6.5) and NOROT, NOPOS and NOSCL (section 5.5). |
| Gradient moments | `gradMomentsAt`, `totalBlockGradMoments`, `areAllGradientsConstantInRange` (h:642-644) | not called | Not exposed by the binding. The FOV hooks use them (section 5). |
| The system frequency for ppm offsets | none: the ppm values only | ppm not weighted | Section 5.5 (3). |
| Signature | `isSigned`, `getSignature`, `isSignatureCheckSucceeded` (h:1324-1328) | records the result; a mismatch does not reject | `--dump` has `signature_ok`. Whether the scanner refuses a file with a wrong signature is not known from these sources. |
| Definitions | `GetDefinition`, `GetDefinitionStr`, `GetAllDefinitions` (h:921-942) | stored | `SequenceData.definitions`. The specification says that some interpreters use optional definitions (FOV, Name, TotalDuration) in their UI (spec:278-283). These change no waveform. |
| Required extensions | `load` rejects a required extension that it does not know (cpp:1505-1537) | the reader's own check | Section 3.4: the reader "knows" ROTATIONS and DELAYS, but does not apply them. |

No other setter, callback or virtual function is in the reader (`grep` of the header for `set`,
`virtual` and function pointers: only `setActualSoftDelay_ru`, `SetArbGrad*` and
`SetPrintFunction`).

## 10. Summary

### 10.1 The reader and `cpp-siemens` today

| Mechanism | The reader stores | Hook for the scanner's interpreter | Reader's default = `cpp-siemens` today | Driver or binding calls the hook | Changes a measurement of the package |
|---|---|---|---|---|---|
| ROTATIONS | normalized quaternion, `isRotation`, `GetRotationEvent` | none for gradients; the quaternion is used only to turn the FOV offset (cpp:2773, 3024) | gradients not rotated (run: `[1e6, 0, 0]` for a 90-degree rotation) | no | yes (all gradient measurements) |
| DELAYS (soft delays) | `numID`, `offset`, `factor`, `hint` | `setActualSoftDelay_ru` on each block | stored durations, the exported ones (run: `gradientsAt` 0 after 600 us) | no; both report `GetStoredDuration_ru` | yes (timing, the timeline) |
| FOV placement (rotation, scaling) | nothing | none | file axes, no scaling | no | yes |
| FOV position offsets | RF and ADC offsets as written | `applyRfPhaseModulation`, `updateAdcPhaseModulation`, `computeLocalPhaseAndFrequencyOffsets` | no offset phase | no | no (RF and ADC phase only) |
| ppm offsets | `freqPPM`, `phasePPM` | none (needs the system frequency) | not weighted | no | no |
| NOROT, NOPOS, NOSCL | flags in `labelset`; `NOSLC` (the specification's spelling) dropped; PMC dropped | none (the FOV hooks do not read them) | stored only | no | only with an FOV setting |
| ONCE and repetitions | ONCE as a counter label | none (no repetition in the reader) | one repetition, every block | no | yes, with more than one repetition |
| TRIGGERS | type, channel, delay, duration | none | no wait | no | only with input-trigger waits |
| RF_SHIMS | channel amplitudes and phases | none | RF of one channel, no shim | no | no |
| Oversampling (D43) | sampling mode | `SetArbGrad*` | `ags_center` | yes: `--oversampling`, `CppSiemens(oversampling=...)` | yes |

### 10.2 What the other sources simulate, and the possible settings

| Mechanism | Specification: the scanner's interpreter | MATLAB `waveforms_and_times` | pypulseq | A possible opt-in setting | Warn at the default? |
|---|---|---|---|---|---|
| ROTATIONS | rotates the whole block (spec:567) | rotates, always (Sequence.m:1988-1999) | cannot read the file | `rotation="apply"` (package code, as `rotate_vec3_by_quat`) | the user's choice: yes |
| DELAYS | `input/factor + offset` (spec:550-563) | after `applySoftDelay` only (Sequence.m:2518-2587) | after `apply_soft_delay` only | `soft_delays={hint: value}` through `setActualSoftDelay_ru` | open (the default is the exported sequence) |
| FOV rotation, scaling | implied by NOROT and NOSLC, not described (spec:136, 526-539) | no (`TransformFOV` at design time) | no | `fov_rotation`, `gradient_scaling` (package code) | open (every file is placed) |
| FOV offsets | ADC offsets for in-plane shift (spec:457) | no | no | `position_offset_mm` through the reader's hooks | probably not |
| ppm | weighted with the system frequency (spec:361) | with `sys.B0` | RF only, with `system.B0` | `b0` or system frequency | probably not |
| ONCE, repetitions | ONCE 0, 1, 2 (spec:541) | no | no | `repetitions=n` | no (1 is defined) |
| TRIGGERS | input and output, wait not described | no | no | `trigger_wait` | open |
| RF_SHIMS | per-channel amplitude and phase (spec:584) | no | no | none proposed | no; record only |

## 11. Decisions for the user

Each decision has its evidence in the section named. None is decided here.

1. **Rotations: the default, and what it replaces.** The user's choice (the reader's unrotated
   gradients by default, with a warning; `rotation="apply"` to rotate) is different from Q3 ("
   `cpp-siemens` applies the rotation") and from R9 ("for both interpreters"). Decide: that Q3
   and R9 change to this; whether `spec` (R11) applies the rotation by default (the
   specification says the block is rotated, spec:567; MATLAB always rotates); and whether the
   setting's values are `"reader"`/`"apply"` or a boolean (section 3.5).
2. **Warnings, and P17.** P17 says that pulseq-analysis has no warnings, and that findings are
   pulseq-checks'. The rotation choice needs a warning from `load` (or `read_seqfile`). Decide:
   a Python `warnings.warn` (which category, for example a new `ScannerSettingWarning`), a field
   on the result (for example, the mechanisms that the file uses and the settings that were left
   at the reader's default), or both. Decide also whether pulseq-checks reports the same
   condition (section 3.5).
3. **Where a setting lives.** Rotation, soft delays and position offsets act on one block, through
   the reader's hooks or next to `gradientsAt`: settings of `CppSiemens`. Repetitions and trigger
   waits act on the timeline across blocks (R14): settings of the interpreter or of `load` and
   the measurements. Decide where each is (sections 4.5, 6.5, 7.5).
4. **Soft delays.** Decide: whether to offer `soft_delays` now; by hint or by `numID`; the
   rounding (MATLAB's `round` to the block duration raster is the only written rule, and the
   scanner's is not known); the errors (an unknown hint, a negative duration, a soft delay
   outside a pure delay block, which the reader allows); and whether the default warns, given
   that it is the exported sequence (sections 4.2, 4.5).
5. **The reported block duration.** The binding and the driver report `GetStoredDuration_ru`.
   With a soft delay setting, decide whether `decode_block` reports `GetDuration_ru` as well,
   and which one the timeline uses (section 4.5). This changes the contract of section 7.3 of the
   plan of the redesign, so it goes in `CHANGELOG.md` and in the document for pulseq-checks.
6. **FOV placement.** Decide whether to offer any of: an FOV rotation and gradient scaling
   (package code, and its order with ROTATIONS, which the sources do not give); position offsets
   through the reader's own `applyRfPhaseModulation` and `updateAdcPhaseModulation` (they change
   the libraries, so `SequenceData` is taken before; and the package must apply NOPOS, which the
   hooks do not read); a system frequency for the ppm terms. The measurements use only gradients
   today, so only the first changes them. Decide also whether a file that sets NOROT, NOPOS or
   NOSCL gives a warning at the default (section 5.5).
7. **Repetitions and triggers.** Decide whether to offer `repetitions=n` (the default 1 is the
   specification's case with no change) and a wait for input triggers, or only to record that
   the file uses ONCE or input triggers (sections 6.5, 7.5).
8. **RF shims.** The proposal is to record them and offer no setting (section 8.5).
9. **`NOSLC` and `NOSCL`.** The specification spells the flag `NOSLC` (spec:520, spec:537). The
   reader, MATLAB and pypulseq spell it `NOSCL`, and the reader drops `NOSLC` with a warning (run,
   section 5.2). Decide whether this is a new entry of `docs/discrepancies.md` or part of D50, and
   whether it is an upstream report (section 12 of the plan of the redesign).
10. **The plan of the redesign.** When these are decided, P20 records them, and the plan's Q3, R9,
    section 5.1 (D49), section 6 (D49 for `spec`), section 7.3 (the settings on a result) and
    section 7.6 ("The rotation (Q3) ... are the package's own") change to match.
