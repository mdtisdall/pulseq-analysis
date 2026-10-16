# pulseq-cpp-siemens

The C++ reader of Pulseq files on Siemens scanners, in the Python process: `ExternalSequence` of
[pulseq/pulseq](https://github.com/pulseq/pulseq) at `c7469123` (MIT; its notice is
`LICENSE.pulseq`, in the wheel's metadata), as a nanobind extension. It gives what the reader
gives, bit for bit: its float32 values, its resampling of RF pulses, the clamps of `checkRF`, its
misreadings, and `gradientsAt`. It is the engine of the `cpp-siemens` interpreter of
pulseq-analysis, and its own distribution with compiled wheels, so that pulseq-analysis stays pure
Python. The module `pulseq_cpp_siemens.interpreter` makes it a plugin of pulseq-analysis (P21),
which finds it through an entry point
([the interpreter](#the-cpp-siemens-interpreter-of-pulseq-analysis)); the rest of the package does
not need pulseq-analysis.

```python
import pulseq_cpp_siemens as cs

sequence = cs.load("tests/seqfiles/valid_1_5_1.seq")  # load, then the checks; decodes nothing
sequence.libraries.rf[1]  # what the reader read: events, shapes, blocks, definitions
sequence.decode_block(0)  # GetBlock and decodeBlock of one block: the driver's --dump
sequence.decode()  # each block in play order; Rejected at the first that fails
sequence.gradients_at(
    [1, 1], [100.0, 105.25]
)  # SeqBlock::gradientsAt (Hz/m): the driver's --sample
sequence.first_rejected_block()  # the driver's first mode, with no block kept: an index or None
sequence.block_rotations()  # the blocks with a rotation, and their quaternions
sequence.gradients_at([1], [100.0], rotated=True)  # turned by each block's rotation
sequence.block_soft_delays()  # the blocks with a soft delay, as GetBlock attaches it
sequence.block_label_sets()  # the LABELSET events of each block that decodeLabel knows
cs.rotate_vec3_by_quat([[1, 0, 0, 0]], [[1.0, 0, 0]])  # the reader's rotation of vectors
cs.load("tests/seqfiles/valid_1_5_1.seq", oversampling="edge")  # the reader's other modes
```

The top-level names that are not described above:

- `PULSEQ_COMMIT`: the full hash of the commit of pulseq/pulseq that the extension compiles, from
  `pulseq-reader.sha256`.
- `Libraries`: the type of `Sequence.libraries`, described below. A frozen dataclass.
- `SoftDelays`: the named tuple that `block_soft_delays()` returns: `blocks`, `num`, `offset_us`,
  `factor` and `hint`.
- `CODES`: the code of each case of undefined behaviour, a key of the dict, with the ID of its
  entry as the value (`UndefinedBehaviour.code` and `.entry`).
  `pulseq_cpp_siemens.interpreter.CODES` has these 11 codes and the codes of the other rejections of `cpp-siemens`.

`load` takes a path or the bytes of a file, and the reader's sampling mode of an oversampled
arbitrary gradient (see below). It raises:

- `NotSupported` (a `NotImplementedError`) for a version outside 1.4.0-1.5.x, a binary Pulseq
  file or a folder (Q1 of the plan). The reader is not run on the file.
- `Rejected` when `ExternalSequence::load` returns false or throws, with the reader's
  `messages`. `decode_block`, `decode` and `gradients_at` raise it when `decodeBlock` returns
  false.
- `UndefinedBehaviour` (a `Rejected`) for the cases of undefined behaviour of the reader (section
  5.3 of the plan). `cases` has every case that the checks find, in play order, each with its
  `code` (a key of `CODES`), its `entry` (the ID of its condition, section 2.2 of
  [`docs/specification.md`](docs/specification.md)) and its `message`. Each event, extension
  list and set of extended trapezoids of a block gives one case at most, at the first block that
  meets it. `code`, `entry`, `block` and `time_us` are those of the first case.
  No block of such a file is decoded. For `ub.gradient-one-point`, which only `gradientsAt` meets,
  `block` and `time_us` give a block and a time where the reader has it. `gradients_at` with
  `actual_ru` also raises it, before the reader runs, at a time where a soft delay longer than
  the stored duration reaches such a read, which starts after the stored duration of the block
  (D5.10); the other times of the call give the reader's values.

`ValueError` for an `oversampling` that is not one of `OVERSAMPLING`.

The reader's messages (`Rejected.messages`, `Sequence.messages`, which has what `load` printed,
and `Sequence.rejection_messages`) are the text that it printed. It quotes lines of the file
there (the row that it fails to decode, the line of an extension that it does not know), so each
byte that is not UTF-8 is written as `\xNN`.

**Oversampling.** An oversampled arbitrary gradient is a `[GRADIENTS]` row with a wave shape and
time shape -1 (D6.1): its n stored samples are half a raster apart. The reader keeps some of
them, by a mode that the interpreter sets before it decodes any block (cpp:2123-2146), and
`gradientsAt` then plays the kept samples on the 10 us raster. `load(oversampling=...)` sets it
for the life of the `Sequence` (decoded blocks are kept, so it cannot change), and
`Sequence.oversampling` records it. `OVERSAMPLING` lists the three:

| `oversampling` | Reader call | Samples kept |
| --- | --- | --- |
| `"center"` (default) | none (`ags_center`) | The centres of the rasters: the samples at even positions, (n + 1) / 2 of them. |
| `"edge"` | `SetArbGradCenterSampling(false)` | The raster edges: the samples at odd positions, (n - 1) / 2 of them. None for n = 1 or 2. |
| `"preserve"` | `SetArbGradPreserveOversampling()` | All n. |

The default is bit for bit what the package gave before the modes. The checks of undefined
behaviour do not depend on the mode: none of the three reads outside a vector that the others
leave alone (`decodeBlock` reads the stored samples at even or odd positions inside their
buffer; the arbitrary gradients of 1 or 2 samples in the mode "edge" have no kept sample, which
`block_values`, `checkGradient` and `gradientsAt` all handle). For such a gradient `gradientsAt`
returns early at the time of its delay, with the channels after it unset (0); the extension
gives each time a new result vector, as the driver does for each line.

`first_rejected_block()` is the first mode of the driver (`GetBlock` and `decodeBlock` of every
block in play order, also after a block that `decodeBlock` rejects) and keeps no block, so a file
of 900 000 blocks needs the memory of one (about 2 to 4 us for each block). It returns the index
of the first rejected block or None, and `rejection_messages` has what the reader printed for
that block.

**Rotations.** The reader stores each block's rotation (the ROTATIONS extension) and applies it
to nothing: `gradientsAt` gives the logical gradients, and the reader leaves the rotation to the
scanner's interpreter. `block_rotations()` gives the play index of each block to which `GetBlock`
attaches a rotation (the first one of its extension list, cpp:1871-1879) and its quaternion
(q0, qx, qy, qz), as `load` divided it by its norm (cpp:1291-1292). `gradients_at(...,
rotated=True)` turns the values of each such block by its quaternion with the reader's own
helper `rotate_vec3_by_quat` (cpp:2666-2684, the active rotation, `c = +1`), which the reader
calls only on its position offsets: a simulation of a scanner that applies the rotation, with the
reader's arithmetic. A block with no rotation is not changed. `rotate_vec3_by_quat(quaternions,
vectors)` gives that rotation of any vectors, bit for bit as `gradients_at(..., rotated=True)`.

**Soft delays and labels.** `block_soft_delays()` gives the soft delay that `GetBlock` attaches to
each block (the first of its list, cpp:1900-1907), as `load` read it: the play index, the numeric
ID, the offset (an int in us), the factor and the hint (bytes). `block_durations_ru(actual_ru)`
gives `GetDuration_ru` of each block after the reader's hook `setActualSoftDelay_ru` with the value
of `actual_ru` for that block (-1 for none: the stored duration), and `gradients_at(...,
actual_ru=...)` sets the hook for the call, so that `gradientsAt` ends the block there. The reader
never sets it: the scanner's interpreter does. A soft delay longer than the stored duration can
reach the read past the times of an extended trapezoid of one point whose delay is after the end
of the block; `gradients_at` raises `UndefinedBehaviour` at those times (D5.10). `block_label_sets()` gives the LABELSET events of
each block that `decodeLabel` knows (it leaves out an unknown name, for example `NOSLC`).

A `Sequence` can be pickled and copied. A pickle carries the bytes of the file and the mode, and
loading it reads and checks the file again; `copy.copy` and `copy.deepcopy` return the same
object.

`Sequence.libraries` is the reader's own reading of the file, from its private members:
`version`, the rasters, `definitions` (bytes to bytes) and `definition_values`, `blocks` (an int64
array with the columns of `BLOCK_COLUMNS`), `shapes` (each a `Shape`: `num_samples`, whether it is
compressed, the stored float32 values), and the events (`rf`, `grad`, `adc`, `extension_list`,
`extension_types`, `triggers`, `rotations`, `labelset`, `labelinc`, `soft_delays`, `rf_shims`),
and the `signature`. A field that `load` leaves unset (first and last of a trapezoid, the ramp
times of an arbitrary gradient) is None.

## How it works

1. **The version gate.** For a file older than 1.4.0, `ExternalSequence::load` itself calls
   `GetBlock` for each block (cpp:1656-1663), before any check could run, so a cycle in an
   extension list would not end inside `load`. The extension first reads the version as `load`
   does, with the reader's own `buildFileIndex` and `skipComments` and the same `sscanf` calls,
   and refuses a version outside 1.4.0-1.5.x. `load` then checks that the reader read the same
   version.
2. **`ExternalSequence::load`** on the bytes of the file. For 1.4.0 and later it runs no
   `GetBlock` and no `decodeBlock`, where each case of undefined behaviour is.
3. **The checks** (`_checks.py`) read the libraries that `load` built, through pointers to the
   private members that an explicit template instantiation hands out (the reader's source is not
   changed), and follow what `GetBlock`, `decodeBlock` and `gradientsAt` would do with each
   block. Section 5.3 of the plan lists the cases. One case needs the text: a `[GRADIENTS]` row of
   shape 0 (`ub.gradient-shape-0`) looks like a `[TRAP]` row in the libraries, so the extension
   reads the rows of `[GRADIENTS]` and `[TRAP]` again with the reader's own `getline` and the
   `sscanf` formats of `load`, from the positions of `load`'s index. The times of an extended
   trapezoid depend on the block: `decodeExtTrapGradInBlock` decodes each shape of a block into
   one buffer, and a decompression that writes fewer samples than `num_samples` keeps the values
   of the shape before it, so the checks follow that buffer block by block.
4. **`GetBlock` and `decodeBlock`** of a block on request, and `gradientsAt`. A block that
   `gradients_at` needs is decoded first; each decoded block is kept (`first_rejected_block`
   keeps none). A NaN time is refused: `gradientsAt` would convert it to an `int`.

The reader keeps state that all its objects share: `SeqBlock::s_blockDurationRaster`, which each
`load` sets and `gradientsAt` reads, and its print function. It reads numbers with `sscanf`,
which follows the C locale. Each call into the reader holds one mutex (with the GIL released),
sets `s_blockDurationRaster` to the value of its own sequence, collects the reader's messages in
a string of its own, which it returns with its result, and runs with the "C" locale in its thread
(`uselocale`; `_configthreadlocale` on Windows). So calls are safe from several threads, also on
one `Sequence`, and each `Rejected` has the messages of its own call. `rejection_messages` is an
attribute of the `Sequence`, set from the result of one call: with several threads that call
`first_rejected_block` on one `Sequence`, it has the messages of the last call to return.

The reader is compiled with `-fsigned-char` and `-ffp-contract=off` (MSVC: `/fp:precise`), as its
x86_64 build on the scanner. `ExternalSequence::getline` compares a `char` with `EOF`: with an
unsigned `char` (gcc on Linux aarch64) it never ends on any file. An arm64 compiler fuses
multiplies and adds unless told not to, and `gradientsAt` then rounds some values differently in
the last bit. The reader keeps its `assert` calls, as the driver of the C++ oracle does; the
extension calls no function whose assert could fail.

## The `cpp-siemens` interpreter of pulseq-analysis

[`docs/specification.md`](docs/specification.md) gives what `cpp-siemens` does and why: its rule (do
what the C++ reader does) and each exception to it.

The module `pulseq_cpp_siemens.interpreter` is a plugin of pulseq-analysis (P21 of
`docs/plans/parser-redesign.md` in that repository): the interpreter `cpp-siemens`. pulseq-analysis
has no import of this package and no reference to it in its metadata. This package declares an
entry point in the group `pulseq_analysis.interpreters` (`pyproject.toml`), whose name is the name
of the interpreter and whose value is the class:

```toml
[project.entry-points."pulseq_analysis.interpreters"]
cpp-siemens = "pulseq_cpp_siemens.interpreter:CppSiemens"
```

With both distributions installed, pulseq-analysis finds it by name, and imports the module only
then:

```python
from pulseq_analysis.seqfile import read_seqfile
from pulseq_analysis.synth import decode
from pulseq_cpp_siemens.interpreter import CppSiemens

data = read_seqfile("sequence.seq", interpreter="cpp-siemens")
data.interpreter  # CppSiemens(oversampling='center', rotation='reader')
edge = read_seqfile("sequence.seq", interpreter=CppSiemens(oversampling="edge"))

cpp = decode(data)  # the C++ reader's own decoding
cpp.block(0)  # GetBlock and decodeBlock of the first block
cpp.gradients_at([0, 0], [10.0, 20.0])  # SeqBlock::gradientsAt (Hz/m), times in us
cpp.rotations()  # the blocks with a rotation, and their quaternions
cpp.rotation_record  # rotation: reader, ... not applied

rotated = decode(read_seqfile("sequence.seq", interpreter=CppSiemens(rotation="apply")))
rotated.gradients_at([0], [10.0])  # each block's gradients turned by its rotation
```

`import pulseq_cpp_siemens` does not import pulseq-analysis; only `pulseq_cpp_siemens.interpreter`
does. The dependency group `analysis` of `pyproject.toml` installs `pulseq-analysis[pypulseq]` from
this repository for this module and its tests; the tests import pypulseq, which its extra
`pypulseq` gives. The published package needs only numpy: its extra `analysis`
(`pulseq-cpp-siemens[analysis]`) requires pulseq-analysis of the same version, up to `0.2`
(`pulseq-analysis>=0.1.0rc7,<0.2` for `0.1.0rc7`), for this module.

`pulseq_cpp_siemens.interpreter` has:

- `CppSiemens`: the interpreter, a frozen dataclass of the protocol
  `pulseq_analysis.seqfile.interpreters.Plugin` (`name` is `"cpp-siemens"`; `read` and `decode`),
  with two settings.
- `OVERSAMPLING` (the modes of `load`, above) and `ROTATION` (`"reader"`, `"apply"`).
- `CODES`: the code of each rejection. It maps a code to a tuple of the ID of its entry and what
  the reader rejects. It includes the 11 `ub.*` codes of the top-level `CODES`, with the same IDs.
- `read_cpp_siemens(path, interpreter)`: `CppSiemens.read`.
- `CppSiemensDecoding`: the decoding, a `pulseq_analysis.synth.Decoding`. The measurements of
  pulseq-analysis (`load(path, "cpp-siemens")`) take their gradients from it, through
  `gradient_points`, `gradient_variants` and `gradients_at`.

It is about six times as long as the `spec` interpreter of pulseq-analysis, which is why `spec` is
the default. On an Apple M1 Max, a file of 21 MB with 899 912 blocks takes about 4 s: 0.3 s for the
"as written" reading, 1.4 s for `load` and the checks, and 2.2 s for `decodeBlock` of every block.

**Reading.** `read_cpp_siemens(path, interpreter)` reads a file in four steps: the version gate on
the "as written" reading of pulseq-analysis (before the C++ reader runs); `load` and the checks of
this package for the reader's undefined behaviour; `decodeBlock` of every block, as the C++ oracle
does (a block that it rejects rejects the file, and no decoded block is kept); and the model from
the reader's own libraries. The version gate reads `AsWritten.version`; the package then reads the
version again with the reader's own code. It raises what `read_seqfile` of pulseq-analysis raises:
`SeqFileError` with the code of each reason, `NotSupported` for a version outside 1.4.0 to 1.5.x, a
binary Pulseq file or a folder, and `OSError`.

**Settings.** `CppSiemens(oversampling=...)` is the reader's sampling mode of an oversampled
arbitrary gradient (time shape -1, D6.1): `"center"` (the reader's default, the samples at the
centres of the gradient raster), `"edge"` (those at its edges) or `"preserve"` (all of them);
`OVERSAMPLING` lists them. `CppSiemens(rotation=...)` is what the decoding does with each block's
rotation (the ROTATIONS extension, D6.2), below; `ROTATION` lists `"reader"` (the default) and
`"apply"`. A value that is not listed is a `ValueError`. `str` gives the name with each setting
that is not its default, for example `cpp-siemens(oversampling='edge')`.

**The codes of the rejections.** `CODES` maps each code of a rejection of `cpp-siemens` to the ID
of its entry (— for none) and what the reader rejects; section 2.5 of
[`docs/specification.md`](docs/specification.md) lists them. The reader stops at its first error,
so a rejection by the reader has one reason, and its message is the reader's own. A rejection for
undefined behaviour has a reason for each case (`UndefinedBehaviour.cases`), at most
`MAX_LOCATIONS` of `pulseq_analysis.seqfile.spec` for each code, and `SeqFileError.omitted` counts
the others, as for `spec`.

The reader gives a message, not a code. Each message of `load` that returns false is a pattern of
`_LOAD_MESSAGES`, and `_classify` finds the code from the message. The order in which the patterns
are tried matters (the reader prints warnings with "ERROR" in them before its error). The "as
written" reading refines a code where the message is not enough (a `#` row, a raster that is there
but skipped, the line of a row that the message quotes). A rejection by `decodeBlock` of a gradient
raster other than 10 µs has no message (the reader prints it at a debug level), so it is found from
the libraries.

**The model.** `SequenceData.reading` is the reader's object (a `Sequence`), with the libraries as
the reader holds them (`SequenceData.reading.libraries`). The model (`_model`) holds what the
reader read, in the units of the model, from the reader's float32 values (P6); the extension gives
each event as a dict of the reader's struct. It differs from the model of `spec` where the reader
does: the reader keeps no block ID, so a block's `id` is its position in play order from 1 (D7.3);
a 1.4 RF event has `center` NaN (the reader holds -1, D7.5); `use` is any character; `first` and
`last` of a 1.4 gradient with a time shape are the reader's sentinel `FLOAT_UNDEFINED` (about
1.18e-38; D4.4 and D4.5 in `spec`); the definitions are in the order of their keys, each with its
last value (D2.6 in `spec`); the rotations are the reader's normalized quaternions (D6.2); and
`skipped_extensions` gives the extensions that the reader ignores (D2.17 in `spec`), which are not
in `SequenceData.extensions.type_ids`.
The reading is not compared by `==`. `pickle` carries the bytes of the file and reads them again;
`copy.deepcopy` shares the reading.

**The decoding.** `CppSiemens.decode(data)` (and `pulseq_analysis.synth.decode`) gives a
`CppSiemensDecoding`: `block(index)` and `blocks()` are `GetBlock` and `decodeBlock` of a block (the
fields of the C++ oracle's `--dump`, `tests/cpp_oracle/README.md` of pulseq-analysis, in the
reader's units), `gradients_at(block_index, time_us, rotated=None)` is `SeqBlock::gradientsAt` in
Hz/m, and `gradient_points(key, block, axis)` gives the points between which `gradientsAt` draws
its straight lines (not rotated; the values are those that `gradientsAt` gives at the points).
`gradient_variants()` says which blocks and axes decode a gradient event alike: the reader
decodes the gradients of a block into one buffer, so a shape that writes fewer samples than it
declares keeps the values of the shape before it in the block (D5.5). It is None for a file with
no such shape. The decoding has the other members of the protocol `pulseq_analysis.synth.Decoding`: `interpreter`,
`session`, `block_count`, `block_durations`, `stored_block_durations`, `rotations()`,
`rotation_record`, `soft_delay_record`, `fov_record` and `fov_flags()`.

**The scanner session.** `CppSiemens` implements version 1 of the plugin protocol of
pulseq-analysis (`protocol`, P22): `decode(data, session)` takes a `pulseq_analysis.synth.Session`
(the neutral one by default). A soft delay with a value in the session sets its block's duration
with the reader's hook `setActualSoftDelay_ru`, by the shared rule of pulseq-analysis (D6.3);
the field of view scales the logical axes (except where `NOSCL` is set), and turns them after the
block's rotation (except where `NOROT` is set), with the reader's `rotate_vec3_by_quat` (D6.4).
The reader drops `NOSLC`, the specification's spelling, so it has no effect here.

**Rotations.** The C++ reader stores each block's rotation and applies it to nothing: its
gradients are the file's logical gradients, and it leaves the rotation to the scanner's
interpreter (D6.2). The decoding gives what the reader gives, and simulates the scanner by a
setting (section 7.8 of `docs/plans/parser-redesign.md`):

- `rotations()` gives the play index of each block to which the reader attaches a rotation (the
  first of its extension list) and its quaternion (q0, qx, qy, qz), divided by its norm, in
  either setting.
- With `CppSiemens(rotation="reader")`, the default, `gradients_at` gives the reader's values, not
  rotated.
- With `CppSiemens(rotation="apply")`, `gradients_at` turns the values of each block with a
  rotation by its quaternion, with the reader's own helper `rotate_vec3_by_quat` (the active
  rotation), so that the arithmetic is the reader's. It follows the reader: it rotates each
  rotation that the reader attaches, in any version of the file. The specification defines
  ROTATIONS from 1.5.1, and what the scanner does with a rotation in an older file is not known.
  On a file with no rotation, `"apply"` is valid and rotates nothing. This is the package's
  simulation of the scanner, and MATLAB's `waveforms_and_times` gives the same gradients on each
  fixture with rotations.
- `gradients_at(..., rotated=False)` or `rotated=True` overrides the setting for one call; the
  reader's own values stay available.
- `rotation_record` (a `pulseq_analysis.synth.RotationRecord`) records what was applied:
  `setting`, `blocks` (with a rotation), `not_identity` (whose rotation is not the identity: the
  blocks that play a rotation) and `rotated`. With the default it has a `hint` for the warning
  that pulseq-analysis gives when a rotation is left unapplied: use
  `CppSiemens(rotation='apply')` for the gradients that the scanner plays.

`spec` of pulseq-analysis rotates the gradients of a file from 1.5.1. It gives, to float32
precision, the gradients of `CppSiemens(rotation="apply")` on such a file.

**Records.** `SequenceData.records` has what the reader ignored, in file order, each with a line:
an extension that the reader does not know (kind `"extension"`, reason `"unknown"`, at the header
of its first section), and a row of LABELSET or LABELINC that the reader leaves out (kind
`"label"`, reason `"unknown"`): a label that `decodeLabel` does not know, such as `NOSLC`, the
specification's spelling of the reader's `NOSCL`, or one that it ignores on purpose, `PMC` and
`TRID` (D6.4).

## The source of the reader

The reader's files are not in this repository; `pulseq-reader.sha256` names the commit, the
four files and the licence, with the SHA-256 of each. CMake takes them from the first of:

1. `$PULSEQ_SOURCE_DIR`: a checkout of pulseq/pulseq. The Nix devShell sets it to the store path
   that `flake.nix` fetches for the C++ oracle.
2. `third_party/pulseq/` (git-ignored): the copy that the sdist carries.
   `scripts/fetch_reader.py` puts it there, from `$PULSEQ_SOURCE_DIR` or from GitHub.
3. raw.githubusercontent.com at the commit, unless `-DPULSEQ_ALLOW_DOWNLOAD=OFF`.

CMake refuses a file with another SHA-256 in all three cases, so the three give the same bytes.

## Build and test

In the Nix devShell, which has CMake, Ninja, a C++ compiler, `PULSEQ_SOURCE_DIR` and both C++
oracles, `scripts/check` of the repository builds the package in its own uv project
(`packages/pulseq-cpp-siemens/.venv`, from its `uv.lock`) and runs its tests. By hand, from the
repository root:

```bash
nix develop --command uv sync --frozen --project packages/pulseq-cpp-siemens --no-editable --reinstall-package pulseq-cpp-siemens
```

```bash
nix develop --command uv run --project packages/pulseq-cpp-siemens --no-sync pytest -q packages/pulseq-cpp-siemens/tests
```

The tests use the fixtures of `tests/seqfiles` of the repository and the package's own
`tests/fixtures`: `shape_decompress_count_missing.seq` (a repeated value with no count at the end
of a shape, D5.5), `gradient_one_point.seq` and `gradient_shape_0.seq` (the two cases that the
fuzzing found). `test_driver_parity.py` compares each fixture with the driver of the C++ oracle
(`pulseq-cpp-oracle`, built by `flake.nix` with the same flags) exactly, in each of the three
sampling modes (the driver's `--oversampling`), and each case of undefined behaviour with the
sanitized driver; it skips without them. `test_digests.py` compares with
`tests/expected_digests.json`, which `scripts/make_digests.py` writes from the driver (a digest
for each fixture and mode), so that a wheel is tested where there is no driver. Run
`make_digests.py` again when a fixture changes. `test_interpreter.py` and
`test_interpreter_in_pulseq_analysis.py` test the interpreter `cpp-siemens`; they need
pulseq-analysis (the dependency group `analysis`, which `scripts/check` installs from this checkout)
and are not collected without it, as in the wheel tests of cibuildwheel. `TESTS.md` of the
repository describes each test.

## Wheels and sdist

`.github/workflows/pulseq-cpp-siemens-wheels.yml` builds the wheels with cibuildwheel for macOS
(arm64, x86_64), Linux (manylinux x86_64, aarch64) and Windows (x86_64), with the stable ABI
(`cp312-abi3`: one wheel per platform for Python 3.12 and later). cibuildwheel installs each in a
clean environment and runs the tests; the native wheel of each runner is also tested on Python
3.14. The sdist job checks that the sdist carries the reader's files and builds a wheel from it
with no download. Each extension links only the system C++ library. The workflow uploads the
wheels and the sdist as artifacts; it publishes nothing.

**Releases.** The package is released only when the pinned commit of the reader or a check
changes. A release is the user's decision, and nothing publishes without it. Before each release:
the longer fuzzing run below, with no failure.

## Fuzzing

The checks are safety-critical: in the process, a case that they miss ends the process or
corrupts it silently. `tests/seqfuzz.py` generates `.seq` files from the grammar of the format
(seeded: a file is a function of its seed and index alone), runs each through the package in a
process of its own (`tests/fuzz_worker.py`) and through `pulseq-cpp-oracle-sanitized` (exit
status 3 for undefined behaviour), and fails on a file that the oracle flags as undefined
behaviour, no end or a crash while the package decodes it. Each file gets one of the three
sampling modes of oversampled gradients, from its seed and index (a function of the two numbers,
from a generator of its own, so that the file does not depend on it); the package and the oracle
(`--oversampling`) read the file in that mode. It also fails on a false alarm (the
checks reject a file that the oracle reads, except a file rejected for the 32-bit build: every
case is `ub.gradient-time-range`, and the checks with the 64-bit `long` of the oracle's build find
none, D5.11), on another verdict, and on another value of
`gradientsAt` at the same times (the oracle's `--sample`, which also runs `gradientsAt` under the
sanitizers). The worker samples each block twice: at its stored duration, and with an
`actual_ru` that makes it last past the end of its last gradient event (the oracle's `--sample`
gets the same soft delay as the third field of each line), so that a case that only a soft delay
reaches is fuzzed too. Two codes are confirmed otherwise: `ub.gradient-one-point` by the oracle's
`--sample` at the block and time of the case (with the worker's soft delay where the case needs
one), and `ub.gradient-shape-0`, whose indeterminate values no sanitizer sees, by a reading of
the file's text in the fuzzing.

The fuzzing found these two cases (2026-10-12); the user decided that `load` rejects both. Before
the checks covered them, a file failed the fuzzing in about 1.7 % of the files: the process died
on an extended trapezoid of one point (the C++ library of the devShell traps its read past the
vector), or `gradientsAt` gave values that differ from the oracle's for a `[GRADIENTS]` row of
shape 0.

A file is a random valid file of version 1.4 or 1.5 (RF pulses with and without time shapes,
regular time shapes, trapezoids, arbitrary gradients, oversampled gradients of 1, 2, 3 and more
samples (of any number: the reader keeps (n + 1) / 2, (n - 1) / 2 or n of them by its mode, and
none in the mode "edge" for 1 and 2), extended trapezoids, ADC events, extensions and lists of
them), then up to three mutations, each with the same chance:
each case of section 5.3 and its neighbours (a missing shape, an RF time shape -1, a cycle, a
shape that decompresses past its buffer or ends in a repeated value with no count, a count at
the edges of an `int`, an empty shape, a short phase, RF times around the cells of the
resampling, RF and gradient times past the range of an `int` and a `long`), values at the edges
of their types in any field, the sections (`[VERSION]` or `[EXTENSIONS]` last, a section missing
or repeated, no blank line at the end or after a shape), IDs, definitions and versions. One file
in eight also gets a change to its text (a line dropped, repeated or swapped, a byte 0xFF, 0x00
or CR, bytes that are not UTF-8, the file cut short). A file with no mutation is valid: the
package reads it. The generator never makes the reader allocate more than 20 000
samples on a path that the checks let through (`CAP`): larger sizes are not undefined behaviour,
but they exhaust the memory of the runner.

**Four tiers.** The seeded set gives the same files on each run, and the oracle is pinned by
`flake.lock`, so it can only change its result where the package, the generator or the oracle
changes. A new seed reaches files that a fixed set never does. So the fuzzing runs in tiers:

1. **Every pull request** (`scripts/check`, about 20 s on 10 cores):
   - the **regression corpus** (`tests/fuzz_corpus/`): the smallest file of each of the 11 codes
     in the seeded set of R6a, each file that once failed the fuzzing, and six valid files (one
     has oversampled gradients of 1 to 4 samples, for the values that `gradientsAt` gave the
     channels after a gradient with no sample in the mode "edge", and one has bytes that are not
     UTF-8 in the reader's messages), with the package's verdict on
     each in `expected.json`. Both readers run on each file in each of the three sampling modes,
     as on a generated one (the verdict does not depend on the mode). It catches a regression of
     a check deterministically.
   - a smoke set: the files 0 to 199 of seed 20261012, so that the generator and the harness do
     not fall behind the package.
2. **A pull request or a push to `main` that changes the package, the oracle or its build**
   (`.github/workflows/pulseq-cpp-siemens-fuzz.yml`, job `seeded`): the full set, the files 0 to
   2 999 of seed 20261012, in about 115 s on 10 cores of an Apple M-series machine (CI has 4). A
   file has 1.6 mutations on average, so each of the 26 mutations is applied about 185 times.
   Each of the 11 codes must be confirmed at least 10 times in the set
   (`test_the_seeded_files_reach_each_case_of_undefined_behaviour`); the rarest,
   `ub.rf-time-overrun`, is confirmed 17 times, the others 53 to 252 times. So the set cannot
   pass by missing a case, and 3 000 is about the smallest set that still reaches each case at
   least 10 times. Each mode has about 1 000 files (962, 1 028 and 1 010), and the files that the
   package reads have an oversampled gradient of each size (1, 2, 3, 4 or more samples) in each
   mode at least 30 times (41 to 157;
   `test_the_seeded_files_have_oversampled_gradients_of_each_size_in_each_mode`).
3. **Each week** (the same workflow, job `weekly`, Monday and by hand): 30 000 new files of a seed
   that is the date. It blocks nothing; its failing files are an artifact. 30 000 files took 20
   minutes on 10 cores (seed 3: each code confirmed 202 to 2 317 times); seed 3 found that the
   checks did not follow the buffer that the reader reuses for the shapes of extended trapezoids
   (`test_checks.py`).
4. **Before each release**, by hand: 200 000 files of a new seed (the date of the run, for
   example), about 2 hours on 10 cores. Each mutation is then applied about 13 000 times, and each
   of the 300 pairs of mutations about 600 times; the rarest code is confirmed about 1 300 times.
   Record the seed, the count and the summary in the release's notes.

```bash
nix develop --command packages/pulseq-cpp-siemens/.venv/bin/python packages/pulseq-cpp-siemens/scripts/fuzz.py --seed 20261101 --count 200000
```

It keeps each failing file and its result in `fuzz-failures/`. A failure is reproduced with
`--seed S --start INDEX --count 1`. A failure is a case of undefined behaviour that the checks
miss, or a fault of the fuzzing: decide which, and report a new case before a check is written
for it. Then add the file to `tests/fuzz_corpus/`, with the package's verdict on it in
`expected.json`, so that every pull request runs it from then on.

## Residual risks

- A case that neither the checks nor the fuzzing find ends the process, or corrupts it silently.
  For files from unknown sources, a worker process is safer.
- The scanner's build is not known. The package matches a build on x86_64 with a signed `char`
  and no FMA; MSVC's `/fp:precise` gives the same bits on the fixtures. `long` is 32 bits on
  Windows and 64 bits on Linux and macOS, which matters only for an extended trapezoid time past
  2^31 us: the checks take 32 bits on every host (D5.11), so such a file is rejected also where
  the reader of the host reads it.
- Process-wide state outside the lock: the global C++ locale (the reader's `istringstream` reads
  the definitions with it), and any other code in the process that calls
  `ExternalSequence::SetPrintFunction`.
