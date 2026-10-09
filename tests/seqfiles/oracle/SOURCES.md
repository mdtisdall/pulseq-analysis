# The oracle files

These Pulseq files were written by tools other than this package (MATLAB Pulseq, pypulseq,
KomaMRI.jl). `tests/test_seqfile.py` reads each one with `read_seqfile` and checks that it loads,
or that it breaks the one rule that the table names. Each file is a byte-for-byte copy of the file
at the commit given. The name of a copy is the source (`pulseq`, `koma`, `pypulseq`) and the name
of the original, with the folders (`read_comparison/v1.4`) shortened.

A file is copied only when the license of its repository allows it (MIT, below) and when the
file does not say that it comes from another project. In KomaMRI.jl, the folder of the Pulseq test
files has no license or notice file for single files.

| File | Source (URL at the commit) | Commit | License | Use |
|---|---|---|---|---|
| `pulseq_fid.seq` | [pulseq/pulseq `tests/legacy/approved/fid.seq`](https://github.com/pulseq/pulseq/blob/c7469123c2f381f065986e6cc3a7d09730ed16ef/tests/legacy/approved/fid.seq) | `c7469123c2f381f065986e6cc3a7d09730ed16ef` | MIT, pulseq/pulseq | 1.5.1, written by MATLAB: FID with delay blocks and a signature that matches |
| `pulseq_epi_rs.seq` | [pulseq/pulseq `tests/legacy/approved/epi_rs.seq`](https://github.com/pulseq/pulseq/blob/c7469123c2f381f065986e6cc3a7d09730ed16ef/tests/legacy/approved/epi_rs.seq) | `c7469123c2f381f065986e6cc3a7d09730ed16ef` | MIT, pulseq/pulseq | 1.5.1: triggers, labels, soft delays, a phase shape of the ADC, gradients with a time shape |
| `pulseq_make_radial.seq` | [pulseq/pulseq `tests/expected_output/seq_make_radial.seq`](https://github.com/pulseq/pulseq/blob/c7469123c2f381f065986e6cc3a7d09730ed16ef/tests/expected_output/seq_make_radial.seq) | `c7469123c2f381f065986e6cc3a7d09730ed16ef` | MIT, pulseq/pulseq | 1.5.1: the ROTATIONS extension, not required |
| `pulseq_seq4.seq` | [pulseq/pulseq `tests/expected_output/seq4.seq`](https://github.com/pulseq/pulseq/blob/c7469123c2f381f065986e6cc3a7d09730ed16ef/tests/expected_output/seq4.seq) | `c7469123c2f381f065986e6cc3a7d09730ed16ef` | MIT, pulseq/pulseq | 1.5.0: LABELSET, RF with time shapes |
| `koma_v1.4_fid.seq` | [KomaMRI.jl `read_comparison/v1.4/fid.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/fid.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1, written by MATLAB (header): a 1.4 file with a signature that matches |
| `koma_v1.4_epi.seq` | [KomaMRI.jl `read_comparison/v1.4/epi.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/epi.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1, written by MATLAB (header): a signature that does not match the file (the parser reports it and loads the file) |
| `koma_v1.4_gr-trapezoidal.seq` | [KomaMRI.jl `read_comparison/v1.4/gr-trapezoidal.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/gr-trapezoidal.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1: one trapezoid |
| `koma_v1.4_gr-time-shaped.seq` | [KomaMRI.jl `read_comparison/v1.4/gr-time-shaped.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/gr-time-shaped.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1 (header: KomaMRI.jl), no signature: a gradient with a time shape, so its end values are those of its end samples |
| `koma_v1.4_gr-uniformly-shaped.seq` | [KomaMRI.jl `read_comparison/v1.4/gr-uniformly-shaped.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/gr-uniformly-shaped.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1: a gradient on the default raster, so the parser rejects it with `layer1.gradient-ends` |
| `koma_v1.4_rf-time-shaped.seq` | [KomaMRI.jl `read_comparison/v1.4/rf-time-shaped.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.4/rf-time-shaped.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.1: an RF pulse with a time shape |
| `koma_v1.4_label_test.seq` | [KomaMRI.jl `basic_tests/v1.4/label_test.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/basic_tests/v1.4/label_test.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.4.0, written by pypulseq (header): LABELSET and LABELINC in extension lists |
| `koma_v1.5_spiral.seq` | [KomaMRI.jl `read_comparison/v1.5/spiral.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/read_comparison/v1.5/spiral.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.5.1, written by MATLAB (header): gradients with time ID -1 (oversampled) and compressed shapes |
| `koma_v1.5_unknown_ext.seq` | [KomaMRI.jl `basic_tests/v1.5/unknown_ext.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/basic_tests/v1.5/unknown_ext.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.5.0, written by pypulseq (header): two extensions that the parser does not know and the file does not require, and no signature |
| `koma_v1.5_rotation_radial_tiny.seq` | [KomaMRI.jl `basic_tests/v1.5/rotation_radial_tiny.seq`](https://github.com/JuliaHealth/KomaMRI.jl/blob/f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4/KomaMRIFiles/test/test_files/pulseq/basic_tests/v1.5/rotation_radial_tiny.seq) | `f58d6c8cce8d4e7ca1e92f0985a6f9ab99e967f4` | MIT, KomaMRI.jl | 1.5.1, written by MATLAB (header): ROTATIONS in `RequiredExtensions` |
| `pypulseq_simple_mprage140.seq` | [pulseq/pypulseq `tests/expected_output/simple_mprage140.seq`](https://github.com/pulseq/pypulseq/blob/f2c582bae13145b8ac71958726bc8b5a14bd1cfd/tests/expected_output/simple_mprage140.seq) | `f2c582bae13145b8ac71958726bc8b5a14bd1cfd` | MIT, pypulseq (since 2026-01-28) | 1.4.0, written by MATLAB (header): gradients on the default raster, so the parser rejects it with `layer1.gradient-ends` |
| `pypulseq_simple_mprage150.seq` | [pulseq/pypulseq `tests/expected_output/simple_mprage150.seq`](https://github.com/pulseq/pypulseq/blob/f2c582bae13145b8ac71958726bc8b5a14bd1cfd/tests/expected_output/simple_mprage150.seq) | `f2c582bae13145b8ac71958726bc8b5a14bd1cfd` | MIT, pypulseq (since 2026-01-28) | 1.5.0, written by MATLAB (header): the sequence of the 1.4.0 file above, with the end values of the gradients in the file |
| `pypulseq_seq6.seq` | [pulseq/pypulseq `tests/expected_output/seq6.seq`](https://github.com/pulseq/pypulseq/blob/f2c582bae13145b8ac71958726bc8b5a14bd1cfd/tests/expected_output/seq6.seq) | `f2c582bae13145b8ac71958726bc8b5a14bd1cfd` | MIT, pypulseq (since 2026-01-28) | 1.5.0, written by pypulseq (header): soft delays (extension DELAYS) |

## How the copies were checked

- The files of KomaMRI.jl: the Git blob SHA-1 of each copy (`git hash-object`) is the SHA-1 of the
  file at the commit in the tree that the GitHub API gives for the commit.
- The files of pulseq/pulseq: the same check, against the tree of the commit.
- The files of pypulseq: each copy is equal, byte for byte, to the file at the head of the default
  branch of pulseq/pypulseq (the commit above) and to the copy in a local clone.

## Not copied

- The files of KomaMRI.jl whose names say that they come from JEMRIS (`epi_JEMRIS`,
  `radial_JEMRIS`, `gre_JEMRIS`), `read_comparison/v1.4/fid-gammaSTAR.seq` (its header names
  gammaSTAR), and the files of the folder `examples/1.sequences`: the license of the other project
  is not checked.
- The files of version 1.3.1 and earlier: the parser rejects them with `version.unsupported`, which a
  fixture of `tests/seqfiles` tests.
- Two files of the folder `examples/1.sequences` of KomaMRI.jl (`epi_se.seq`, `ge.seq`), because of
  their origin (the line above). Both are 1.4.0 files with an ADC dwell time that is not a multiple
  of `AdcRasterTime`; the parser rejects them with `raster.adc-dwell`.

## The licenses

Each of the three repositories has an MIT license file at the commit above. Their notices:

- pulseq/pulseq: Copyright (c) 2015, Kelvin Layton and Maxim Zaitsev.
- KomaMRI.jl: Copyright (c) 2020 Carlos Castillo Passi.
- pypulseq: Copyright (c) 2019-2025 PyPulseq Contributors.

The MIT license (from the files of the three repositories, with the notice of each above):

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute,
> sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
> NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
> OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
