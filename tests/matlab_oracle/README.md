# The MATLAB oracle

`dump.m` reads `.seq` files with MATLAB Pulseq, the `matlab` folder of
[pulseq/pulseq](https://github.com/pulseq/pulseq) at commit
`c7469123c2f381f065986e6cc3a7d09730ed16ef` (the same commit as the C++ oracle in
`tests/cpp_oracle`), and writes what MATLAB holds as JSON. It runs under GNU Octave from the
nixpkgs of `flake.lock`, not under MATLAB. It calls `mr.Sequence().read`, `getBlock` and
`waveforms_and_times(true)`.

## The command

```
pulseq-matlab-oracle OUT_DIR FILE.seq...
```

Nix builds it as `pulseq-matlab-oracle` (`flake.nix`; `nix build .#pulseq-matlab-oracle`). It
runs one `octave-cli` process for all the files, with `<source>/matlab` and a folder with
`dump.m` only (a change to this README does not change the store path) on the Octave path, and
writes `OUT_DIR/<stem>.json` for each file. Octave prints one
line for each file (name, time, `ok` or the message of the error).

- Exit 0: Octave ran. A file that MATLAB cannot read gives `{"error": message}` in its JSON.
- Exit 2: the arguments are wrong: no file, a name that does not end in `.seq`, or two files
  with the same stem (they would write the same JSON file).
- Another non-zero status: Octave or `mkdir` failed (for example, `OUT_DIR` is not writable).

Octave read the 26 files of `tests/seqfiles/valid_*.seq` and `tests/seqfiles/oracle/*.seq` in
13 to 17 s in two runs (Octave 11.3.0); `pulseq_epi_rs.seq` took 5.5 s in the first.

`tests/seqfiles/bad_ref_extension_cycle.seq` did not finish in 15 s and was stopped, so
`read` of MATLAB Pulseq may not return for a file with a cycle in its extension list. The
command has no time limit for one file.

## The devShell

The command is in the default devShell only, not in the `ci` shell. Octave and its libraries
are about 2.5 GiB (`nix path-info -S`), and CI does not cache the Nix store.

## The JSON

One JSON object for each file. All times are in seconds, as MATLAB holds them (MATLAB converts
the microseconds and nanoseconds of the file on read). Gradient amplitudes are in Hz/m, RF
amplitudes in Hz, phases in rad.

| Key | Value |
| --- | --- |
| `version` | `{"major", "minor", "revision"}` of the `[VERSION]` section of the file. `read` of MATLAB Pulseq checks these numbers but keeps them in local variables, so `dump.m` repeats the three lines of its `readVersion`. |
| `toolbox_version` | `{"major", "minor", "revision"}` of MATLAB Pulseq itself (`seq.version_major` and the others). |
| `definitions` | Object, key to string. See below. |
| `definitions_numeric` | Object. The keys of `definitions` that MATLAB holds as numbers, each with a list of numbers. |
| `block_durations` | List of the duration of each block in s (`seq.blockDurations`). |
| `blocks` | List, one object for each block, from `getBlock(b)`. See below. |
| `waveforms` | Object from `waveforms_and_times(true)`. See below. |
| `t_adc` | List of the times of all ADC samples in s (the fourth output of `waveforms_and_times`). |

`definitions`: MATLAB reads each line of `[DEFINITIONS]` as a key and tokens. When every token
is a finite number (`str2double`), MATLAB holds a row of numbers; otherwise it holds the text
after the key. In `definitions`, every value is a string. A number is written as the shortest
text that gives the same double (`1e-7`, `0.00001`), and the numbers of one key are joined by
spaces. So the text of the file is not kept: `1e-07` in the file is `1e-7` here. The keys are
in the order of `keys()` of the MATLAB map (sorted), not the order of the file. Where
`definitions_numeric` has the key, the value is also there as numbers.

`blocks[b]` has these keys, in this order, for every block:

- `blockDuration`: number, s.
- `rf`, `gx`, `gy`, `gz`, `adc`: the event as an object, or `null` when the block has none.
- `trig`, `label`: lists of event objects, `[]` when the block has none.
- `rotation`, `softDelay`, `rfShim`: the event as an object, or `null`.
- Any other field of the struct of `getBlock`, after these (none in those files).

The keys of an event object are the names of the MATLAB fields. For example, `rf` has `type`,
`signal_abs`, `signal_angle`, `t`, `shape_dur`, `center`, `delay`, `freqPPM`, `phasePPM`,
`freqOffset`, `phaseOffset`, `deadTime`, `ringdownTime` and `use`. A gradient has the fields of
its `type`: `"trap"` has `amplitude`, `riseTime`, `flatTime`, `fallTime`, `delay`, `area` and
`flatArea`; `"grad"` has `waveform`, `tt`, `area`, `shape_id`, `time_id`, `delay`, `shape_dur`,
`first` and `last`. Both have `channel`. `adc` has `numSamples`, `dwell`, `delay`, `freqPPM`,
`phasePPM`, `freqOffset`, `phaseOffset`, `phaseModulation`, `deadTime` and `type`.
`phaseModulation` is the decompressed phase shape with no conversion.

A complex field is written as two lists, because `jsonencode` of Octave drops the imaginary
part without a message. `signal` of `rf` and `shimVector` of `rfShim` are always split, as
`signal_abs` and `signal_angle` (rad), `shimVector_abs` and `shimVector_angle` (rad). The
split applies to any other complex field in the same way.

`waveforms` has the keys `gx`, `gy`, `gz` and `rf`: the cell `wave_data` of
`waveforms_and_times(true)`. Each value is `null` when the channel has no point, and otherwise
`{"t": [...], "v": [...]}` (s; Hz/m) for a gradient, and `{"t": [...], "v_abs": [...],
"v_angle": [...]}` (s; Hz; rad) for `rf`. The polyline is as MATLAB gives it, including the
points that `waveforms_and_times` adds before and after an RF pulse.

### The rule of regularity

- An event that is absent is `null`, never `{}` or `[]`.
- A field that holds an array is always a list of numbers, also with one element (`[0.5]`) or
  none (`[]`). These fields are: `block_durations`, `t_adc`, the values of
  `definitions_numeric`, `t`, `tt`, `waveform`, `phaseModulation`, `rotQuaternion`, the
  `_abs` and `_angle` lists, and the lists of `waveforms`. They are flat lists in the order of
  the MATLAB array, whether it is a row or a column.
- `trig` and `label` are always lists.
- Every other number is a scalar, and a MATLAB field that is empty is `null`.
- `NaN` and `Inf` are `null`: `jsonencode` of Octave writes them so.
- The keys of an event depend on its type (`trap` or `grad`), as in MATLAB. They do not
  depend on the file.

## The license

The pulseq/pulseq project is under the MIT license. The toolbox is not copied into this
repository: Nix fetches it at the commit above (`fetchFromGitHub` in `flake.nix`). `dump.m` is
code of this project.
