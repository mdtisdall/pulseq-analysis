# The C++ oracle

`driver.cpp` is a small program that reads one `.seq` file with `ExternalSequence::load`, the
reader of the Pulseq interpreter on the scanner, and then decodes each block with `decodeBlock`.
Nix builds it as `pulseq-cpp-oracle` (`flake.nix`), and `tests/test_cpp_oracle.py` runs it.

`ExternalSequence.h`, `ExternalSequence.cpp`, `md5.h` and `md5.cpp` are not in this folder. The
derivation takes the folder `src/` of [pulseq/pulseq](https://github.com/pulseq/pulseq) at commit
`c7469123c2f381f065986e6cc3a7d09730ed16ef`. That project is under the MIT license; its notice is
in `LICENSE.pulseq` in this folder, which is a copy of the `LICENSE` file of that commit.

Each build of `flake.nix` (also the sanitized build below) has `-fsigned-char -ffp-contract=off`,
so that the reader has the `char` and the arithmetic of its x86_64 build on the scanner on each
system:

- `-fsigned-char`: `ExternalSequence::getline` compares a `char` with `EOF`. Where `char` is
  unsigned (gcc and clang on Linux aarch64) the comparison is never true, and the reader does not
  end on any file.
- `-ffp-contract=off`: the x86_64 build has no FMA instructions, so it never fuses a multiply and
  an add. On arm64 the compiler fuses them by default, and `gradientsAt` then gives some values
  that differ in the last bit (`--sample`; `--dump` is the same).

## Modes and exit status

| Call | What it does |
| --- | --- |
| `pulseq-cpp-oracle FILE` | Says only whether the file loads and each block decodes: the exit status. |
| `pulseq-cpp-oracle --dump FILE` | Writes what the reader holds after `load` and `decodeBlock` of every block, as one JSON object on stdout. |
| `pulseq-cpp-oracle --sample FILE` | Reads lines `block_index time_us [actual_ru]` on stdin and writes the three gradient values of `SeqBlock::gradientsAt` for each line. |

A call with one argument is always the first mode, so a file named `--dump` is read as a file.

A leading `--oversampling=center|edge|preserve` sets the reader's sampling mode of an oversampled
arbitrary gradient (time shape -1) for every mode, for example `pulseq-cpp-oracle
--oversampling=edge --sample FILE` or `pulseq-cpp-oracle --oversampling=edge FILE`. It needs at
least two more arguments (with one argument, the first mode reads it as a file name). Another
value, or an option anywhere else, is a wrong call (status 2). With no option the mode is
`center`, the reader's default. The sampling modes are under `--dump` below.

| Exit status | Meaning |
| --- | --- |
| 0 | The file loads and each block decodes (and the mode did its work). |
| 1 | The file does not load, a block does not decode, or the reader throws. The messages of the reader are on stderr. |
| 2 | A wrong call; in `--sample` also a line of stdin that is not `block_index time_us [actual_ru]`, or a block index outside the sequence. |
| 70 | The reader crashed (SIGSEGV, SIGABRT, SIGFPE, SIGILL, SIGBUS or SIGTRAP). |

`--dump` writes its JSON only at the end, so a call that exits with 1 has written nothing on
stdout. `--dump` also calls `GetAllDefinitions`, which the first mode does not.

## The sanitized build

Nix also builds the same driver and reader as `pulseq-cpp-oracle-sanitized` (`flake.nix`; on the
PATH of the devShell and the `ci` devShell), with clang of LLVM 22, the two flags above, and:

- AddressSanitizer and UndefinedBehaviorSanitizer (`-fsanitize=address,undefined`,
  `-fno-sanitize-recover=all`);
- the annotation of the unused capacity of a `std::vector` for AddressSanitizer
  (`_GLIBCXX_SANITIZE_VECTOR` for libstdc++; libc++ always annotates it), so that a write past the
  size of a vector inside its capacity is a report of container-overflow on both systems;
- the assertions of the C++ standard library: `_GLIBCXX_ASSERTIONS` for libstdc++ (Linux) and
  `_LIBCPP_HARDENING_MODE_DEBUG` for libc++ (macOS). They check, for example, the index of
  `std::vector::operator[]`, which the reader takes past the end without a read that
  AddressSanitizer would see (`&shape[0]` of an empty shape).

It has the same modes. Its exit status 3 says that a sanitizer or an assertion of the standard
library fired: the reader has undefined behaviour on the file. An ordinary build then crashes,
accepts or rejects the file by platform and compiler; the verdict of this build is the same on
each. The report is on stderr. The driver sets the options of the sanitizers
(`__asan_default_options`, `__ubsan_default_options`: `exitcode=3`, `abort_on_error=0`, no leak
check, as the reader leaks when it rejects a file); `ASAN_OPTIONS` and `UBSAN_OPTIONS` can change
them.

| Exit status | Meaning in the sanitized build |
| --- | --- |
| 0, 1, 2 | As in the table above. |
| 3 | Undefined behaviour: a report of AddressSanitizer (also for SIGSEGV, SIGBUS and SIGFPE, which it handles) or UndefinedBehaviorSanitizer, or a failed assertion of the standard library. |
| 70 | SIGABRT, SIGILL or SIGTRAP that is none of these, for example a failed `assert` of the reader. |

LLVM 22, not the default LLVM 21 of the stdenv on macOS: the AddressSanitizer of LLVM 21 hangs at
the start of each process on macOS 26. Clang on Linux too, so that both systems have the same
sanitizers.

The build has no debug information, so a report names the functions but not the lines. To find
the line, compile the three files with the clang of LLVM 22 and the same flags with `-O0 -g` in
place of `-O1`, run `dsymutil` on the program (macOS), and set `ASAN_SYMBOLIZER_PATH` to
`llvm-symbolizer` of LLVM 22.

`tests/test_cpp_oracle_sanitized.py` has the verdict for each fixture of `tests/seqfiles/`.
The files where the reader has undefined behaviour, with the entry of
`packages/pulseq-cpp-siemens/docs/specification.md` and the line of `ExternalSequence.cpp` where the build stops:

| Fixture | Entry | Line | What the reader does |
| --- | --- | --- | --- |
| `undefined/version_last.seq` | D5.1 | 1995 | With `[VERSION]` as the last section, the stream stays failed after `[VERSION]` is read to the end of the file; the seek to `[SHAPES]` fails, so no shape is read, and the RF event names shape 1. |
| `bad_ref_shape.seq` | D5.1 | 1995 | The RF magnitude shape does not exist. |
| `bad_ref_time_shape.seq` | D5.1 | 2177 | The time shape of a gradient does not exist. |
| `bad_syntax_shape_no_blank_line.seq` | D5.1 | 2177 | The shapes after a shape with no blank line are not read (D3.11), and a gradient names one. |
| `undefined/rf_time_id_minus_1.seq` | D5.3 | 2026 | An RF event with time ID -1. |
| `undefined/shape_decompress_longer.seq` | D5.5 | 2231 | The RF shapes decompress to 100 samples into a buffer of `num_samples` 99 (heap-buffer-overflow). |
| `bad_shape_empty.seq` | D5.6 | 1995 | Element 0 of an empty shape. |
| `bad_shape_event_length.seq` | D5.7 | 2288 | The phase shape is shorter than the magnitude shape. |
| `bad_shape_rf_time_end.seq` | D5.8 | 2044 | The resampling reads one sample past the end of the shape. |

`bad_ref_extension_cycle.seq` (D5.4) has no end in either build, and no sanitizer fires: the loop
over the cycle appends a label to a vector in each turn, so the memory grows with no end.

## `--dump`

The values are those that the C++ structs hold, with no conversion of units. A `float` member is
written with `%.9g` and a `double` member with `%.17g`, so each value reads back exactly. Integers
are written as integers. NaN and infinity are not valid JSON: they are written as `null`. Text is
JSON-escaped; when it is not valid UTF-8 (the reader keeps the bytes of the file), each byte from
0x80 on is written as the code point of the same number (`\u0080` to `ÿ`).

```json
{"version": 1005001, "definitions": {"...": "..."}, "signature_ok": true, "blocks": ["..."]}
```

| Field | Value (accessor) |
| --- | --- |
| `version` | `GetVersion()`: the combined integer, `1005001` for 1.5.1. |
| `definitions` | Object from each key of `GetAllDefinitions()` to `GetDefinitionStr(key)`, the text of the value. |
| `signature_ok` | `isSignatureCheckSucceeded()`. |
| `blocks` | One object for each block, in play order. |

A block has these fields. The absent events are `null` (`grad` has always 3 entries) and the
absent labels are `[]`.

| Field | Value (accessor) |
| --- | --- |
| `index` | `GetIndex()`: the position in play order from 0. The reader has no accessor of the block ID. |
| `duration_ru` | `GetStoredDuration_ru()`: the stored duration in block duration raster units. |
| `rf` | An object when `isRF()`, else `null`. |
| `grad` | A list of 3 (X, Y, Z): an object, or `null` when the channel has no gradient. |
| `adc` | An object when `isADC()`, else `null`. |
| `trigger` | An object when `isTrigger()`, else `null`. `isTrigger()` is false for a trigger of type 0. |
| `soft_delay` | An object when `isSoftDelay()`, else `null`. |
| `labelset`, `labelinc` | `GetLabelSetEvents()`, `GetLabelIncEvents()`: a list of `{"label", "value"}`. |
| `rotation` | A list of the 4 numbers of `rotQuaternion` (`GetRotationEvent()`) when `isRotation()`, else `null`. The reader divides them by their norm when it loads them. |
| `rf_shim` | An object when `hasRfShim()`, else `null`. |

`rf` (`GetRFEvent()` and the accessors of the decoded RF):

| Field | Unit | Source |
| --- | --- | --- |
| `amplitude` | Hz | `RFEvent::amplitude` |
| `mag_shape`, `phase_shape`, `time_shape` | shape ID | `magShape`, `phaseShape`, `timeShape` |
| `shape_dur_us` | µs | `shape_dur`: the dwell times the number of samples, set by `decodeBlock` |
| `center_us` | µs | `center` |
| `delay_us` | µs | `delay` |
| `freq_ppm`, `phase_ppm` | ppm, rad/MHz | `freqPPM`, `phasePPM` |
| `freq_offset` | Hz | `freqOffset` |
| `phase_offset` | rad | `phaseOffset` |
| `use` | text of 1 character | `use` |
| `dwell_us` | µs | `GetRFDwellTime()` |
| `magnitude` | fraction of `amplitude` | `GetRFAmplitudePtr()`, `GetRFLength()` values, after `checkRF` |
| `phase` | rad | `GetRFPhasePtr()`, the same number of values: the phase shape times 2π, after `checkRF` |

`grad[c]` (`GetGradEvent(c)`) has `kind`, `amplitude` (Hz/m, `GradEvent::amplitude`) and
`delay_us` (`delay`), and:

| `kind` | When | More fields |
| --- | --- | --- |
| `trap` | `isTrapGradient(c)` | `ramp_up_us`, `flat_us`, `ramp_down_us` (µs: `rampUpTime`, `flatTime`, `rampDownTime`) |
| `ext_trap` | `isExtTrapGradient(c)` | `times_us` (µs, `GetExtTrapGradTimes(c)`), `shape` (fractions of `amplitude`, `GetExtTrapGradShape(c)`) |
| `arbitrary` | `isArbitraryGradient(c)` | `wave_shape`, `time_shape` (shape IDs; `-1` is an oversampled gradient), `first`, `last` (Hz/m: `first`, `last`), `oversampled` (`isArbGradWithOversampling(c)`), `samples` (fractions of `amplitude`, `GetArbGradShapePtr(c)`, `GetArbGradNumSamples(c)` values, after `checkGradient`) |

For an oversampled arbitrary gradient, `samples` depend on the sampling mode of the reader, which
`--oversampling` sets (`ExternalSequence.h:970-993`, `ExternalSequence.cpp:2123-2146`). For a shape
of n stored samples:

| `--oversampling` | Reader call | Samples kept |
| --- | --- | --- |
| `center` (default) | none (`ags_center`) | The centres of the rasters: every second stored sample from the first, (n+1)/2 samples. |
| `edge` | `SetArbGradCenterSampling(false)` | The raster edges: every second stored sample from the second, (n-1)/2 samples. None for n = 1 or 2: `samples` is empty and `gradientsAt` returns early (a warning) for such a gradient at the time of its delay, leaving the channels after it at 0. |
| `preserve` | `SetArbGradPreserveOversampling()` | All n stored samples. |

`--sample` uses the samples as a 10 µs raster in every mode, as `gradientsAt` does. The reader
sets `first` and `last` of a file of version 1.4 to `FLOAT_UNDEFINED` (`1.18e-38f`,
written as `1.17999995e-38`).

`adc` (`GetADCEvent()`): `num_samples`, `dwell_ns` (ns), `delay_us` (µs), `freq_ppm`, `phase_ppm`,
`freq_offset` (Hz), `phase_offset` (rad), `phase_shape` (shape ID of the phase modulation).

`trigger` (`GetTriggerEvent()`): `type`, `channel`, `delay_us` (µs), `duration_us` (µs).

`soft_delay` (`GetSoftDelayEvent()`): `num_id`, `offset_us` (µs), `factor`, `hint` (text). The
reader keeps the first 31 characters of the hint.

A label of `labelset` or `labelinc` is `{"label": NAME, "value": N}`. `NAME` is the name that the
reader gives the label (`getCounterIdAsString`, for example `LIN`) or the flag
(`getFlagIdAsString`, for example `NAV`); a flag has the value 0 or 1.

`rf_shim` (`GetRfShim()`): `id`, `nchan`, `amplitudes` and `phases` (lists of `float`).

## `--sample`

After `load`, the driver reads stdin line by line. A line is `block_index time_us`: the index of a
block in play order from 0, and a time in µs from the start of the block (a number that `strtod`
reads; not NaN or infinity). For each line it writes one line `gx gy gz` on stdout: the three
values of `SeqBlock::gradientsAt`, each with `%.17g` (Hz/m, as the reader holds them: the
amplitude is a `float`). A value that is not finite would be written as `printf` writes it.

A line can have a third number, `actual_ru`: an integer (a `long` that `strtol` reads in base 10)
that the driver sets on the block with the reader's hook `SeqBlock::setActualSoftDelay_ru` for
the call to `gradientsAt` of that line, and sets back to -1 (the reader's default) after it, as
`gradients_at` of pulseq-cpp-siemens does with its `actual_ru`. `GetDuration` is then
`actual_ru` block duration rasters in place of the stored duration, so `gradientsAt` gives 0
after that time. A value below 0 sets no soft delay, and a line with two numbers is the same as
one with -1.

The driver decodes each block once, when a line first asks for it. A line that does not read as
`block_index time_us`, or a block index that is not in `0` to the number of blocks minus 1, makes
it exit with 2 and a message on stderr; the lines before it are already written. A block that does
not decode gives exit status 1.

`gradientsAt` gives 0 for a time before the start or after the end of the block. It looks only
inside one block, so it does not join the blocks. The driver does not pass on the messages that
`gradientsAt` prints (one for each call on a ramp down, and one for a time outside the block).
