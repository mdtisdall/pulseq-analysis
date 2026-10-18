# The SAFE oracle

`dump_safe.m` runs the original SAFE PNS model of Szczepankiewicz and Witzel,
[filip-szczepankiewicz/safe_pns_prediction](https://github.com/filip-szczepankiewicz/safe_pns_prediction)
at commit `152ab67c086170c40c1988ebba9002e018a0652c`, and `calcPNS` of MATLAB Pulseq (the
`matlab` folder of [pulseq/pulseq](https://github.com/pulseq/pulseq) at commit
`c7469123c2f381f065986e6cc3a7d09730ed16ef`, as `tests/matlab_oracle`), which calls it. It runs
under GNU Octave from the nixpkgs of `flake.lock`, not under MATLAB. The SAFE package is the
source of pypulseq's `safe_pns_prediction.py`, from which `src/pulseq_analysis/analyses/safe.py`
is ported.

## The command

```
pulseq-safe-oracle filter REQUEST.json OUT_DIR
pulseq-safe-oracle calcpns FILE.asc OUT_DIR FILE.seq...
```

Nix builds it as `pulseq-safe-oracle` (`flake.nix`; `nix build .#pulseq-safe-oracle`). It runs
one `octave-cli` process, with `<pulseq>/matlab`, the SAFE package and a folder with
`dump_safe.m` only (a change to this README does not change the store path) on the Octave path,
and writes into `OUT_DIR`, which it makes.

- Exit 0: Octave ran. In the mode `calcpns`, a file that MATLAB cannot read, or that `calcPNS`
  fails on, gives `{"error": message}` in its JSON.
- Exit 2: the arguments are wrong: no mode or another mode, the wrong number of arguments, or in
  the mode `calcpns` a name that does not end in `.seq` or two files with the same stem.
- Another non-zero status: Octave or `mkdir` failed. In the mode `filter`, an error of Octave on
  a case (a file that it cannot read, a hardware without a field that `safe_gwf_to_pns` reads) is
  such a failure.

`safe_hw_from_asc` of the SAFE package does not read a `.asc` file under Octave: each field of
the struct that it gives is empty. It removes the white space of the text, and `sscanf` of Octave
with `%g` gives no number for a number that a letter follows (`0.2flgswdtaux[1]=...`). So the
mode `filter` takes the hardware as JSON, and the mode `calcpns` gives the `.asc` file to
`calcPNS`, which reads it with `mr.Siemens.readasc` and its own `asc_to_hw`. `calcPNS` of this
commit takes the path of a `.asc` file, not a hardware struct.

## The mode `filter`

`REQUEST.json` is an object with two lists:

- `cases`: objects `{"id", "dt", "gwf", "rows", "hw"}`. `gwf` is the name of a file in the folder
  of `REQUEST.json`: `rows` x 3 float64 values, little-endian, row by row (x, y, z of each
  sample), in T/m or in any unit (the model is linear). `dt` is the raster in s. `hw` is the
  hardware: `{"x": {...}, "y": {...}, "z": {...}}`, each with `tau1`, `tau2`, `tau3` (ms),
  `a1`, `a2`, `a3`, `stim_limit`, `stim_thresh` (T/m/s) and `g_scale`.
- `hw_checks`: objects `{"id", "hw"}`, `hw` as above. An axis or a field can be left out.

For each case, `dump_safe.m` calls `safe_gwf_to_pns([zeros(1, 3); gwf], rf, dt, hw, 0)`: no
padding, and a row of 0 in front, so that the first row is the slew from 0 to the first sample
and the filters start from 0 (as the state `None` of `_safe_gwf_to_pns_chunk`). It writes:

- `OUT_DIR/<id>.f64`: the `rows` x 3 rows of `safe_gwf_to_pns` (percent of the stimulation
  limit), float64, little-endian, row by row.
- `OUT_DIR/<id>.inputs.f64`: 28 float64 values, the inputs as Octave read them from the JSON:
  `dt`, then the nine fields of x, y and z in the order above (`stim_thresh` before `g_scale`).

`OUT_DIR/hw_check.json` is a list, one object for each case of `hw_checks`, in order: `{"id",
"is_ok"}` with the 0 or 1 of `safe_hw_check(hw)`, or `{"id", "error"}` when it failed (for a
struct without an axis or a field: the field of an Octave struct that is not there).

## The mode `calcpns`

For each `.seq` file, `dump_safe.m` reads it with `mr.Sequence().read` and calls
`seq.calcPNS(FILE.asc, false)`. It writes `OUT_DIR/<stem>.json`:

| Key | Value |
| --- | --- |
| `ok` | The first output of `calcPNS`: true when each total is below 1. |
| `gamma` | `seq.sys.gamma`, Hz/T: `calcPNS` divides the gradients (Hz/m) by it. |
| `grad_raster` | `seq.gradRasterTime`, s. |
| `t_axis_first` | The time of the first sample (`t_axis(1)`), s, or `null` when there is no sample (a sequence with no gradient). |
| `num_samples` | The number of samples (`numel(t_axis)`). |

and `OUT_DIR/<stem>.f64`: `num_samples` x 4 float64 values, little-endian, row by row: the three
axes (`pns_comp`) and the total (`pns_norm`) of each sample, as fractions of the stimulation
limit (1 is 100 %). A file that fails gives `{"error": message}` and no `.f64` file.

`calcPNS` samples MATLAB's polyline of the gradients (`waveforms_and_times`) at
`t_axis = (m + 0.5) * dt`, the centers of the raster periods from the one of the first gradient
point to the one of the last, pads the samples with zeros before and after (`safe_gwf_to_pns` with
padding) and keeps the rows of the samples of `t_axis`. Row j of the model is the slew from
sample j to sample j + 1, so the row that `calcPNS` gives the time `t_axis(j)` is the slew from
the gradient at `t_axis(j)` to the gradient at `t_axis(j + 1)`, and the slew from 0 to the first
sample is not in the output.

For a file with no gradient, `calcPNS` gives no sample. The command read the 17 files of
`tests/seqfiles/oracle` in 22 to 23 s in two runs (Octave 11.3.0, macOS, 2026-10-18);
`pulseq_epi_rs.seq` took 10.7 to 11.3 s.

## The devShell

As `pulseq-matlab-oracle`, the command is in the default devShell only, not in the `ci` shell:
Octave and its libraries are about 2.5 GiB. The tests that use the command
(`tests/test_safe_oracle.py`) run in CI in `.github/workflows/matlab-oracle.yml`, in the default
devShell, and only for a change to what they read; `scripts/check` in the `ci` shell skips them.

## The license

The SAFE package is under the BSD 3-Clause license (its `LICENSE`), and pulseq/pulseq under
the MIT license. Neither is copied into this repository: Nix fetches each at the commit above
(`fetchFromGitHub` in `flake.nix`). `dump_safe.m` is code of this project.
