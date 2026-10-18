"""Tests of the SAFE model of the package against the original SAFE package
(filip-szczepankiewicz/safe_pns_prediction, the commit in `flake.nix`) and `calcPNS` of MATLAB
Pulseq, run under GNU Octave by the command `pulseq-safe-oracle` (`tests/oracles/safe.py`,
`tests/safe_oracle/`).

- The filter: `safe._safe_gwf_to_pns_chunk`, in one chunk and in the chunks of `test_safe.py`,
  against `safe_gwf_to_pns` of the original on the same waveform, for the hardware and the
  rasters of `test_safe.py`.
- The hardware check: `SafeHardware.from_namespace` against `safe_hw_check` of the original.
- The whole model: `pns_levels` of each file of `tests/seqfiles/oracle` that the `spec`
  interpreter accepts, with the hardware of a gradient `.asc` file (`asc.hardware_from_asc`),
  against `calcPNS` of MATLAB Pulseq with the same `.asc` file.

The module skips when the command is not on the PATH: only the default devShell has it.
"""

from pathlib import Path

import numpy as np
import pytest
from oracles import safe
from test_safe import CHUNK_DTS, CHUNK_NAMESPACES, CHUNKS, HW_CHECK_CASES, chunk_waveform

from pulseq_analysis import seqfile
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.asc import hardware_from_asc
from pulseq_analysis.analyses.pns_levels import PEAK_TOLERANCE, pns_levels
from pulseq_analysis.analyses.safe import SAFE_FIELDS, SafeHardware, _safe_gwf_to_pns_chunk
from pulseq_analysis.seqfile import NotSupported, SeqFileError
from pulseq_analysis.synth.seq_index import NO_GRADIENTS

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
FILES = sorted((SEQFILES / "oracle").glob("*.seq"))
COMMAND = safe.command_path()

pytestmark = pytest.mark.skipif(
    COMMAND is None,
    reason="pulseq-safe-oracle is not on the PATH (only the default devShell has it)",
)

# The filter: relative to the largest magnitude of the rows of the original. The port and the
# original do the same operations in another order (`alpha` is `dt_ms / (tau + dt_ms)` in the
# port and `dt / (tau * 1e-3 + dt)` in the original, and `lfilter` sums in its own order), so
# they differ by the rounding: at most 5.6e-16 of the largest magnitude in a measurement
# (2026-10-18, macOS).
FILTER_REL = 1e-14

# The whole model: relative to the peak of the file. calcPNS samples MATLAB's polyline at its
# own times (`interp1` at `t_axis`) and the package samples each block, so the times of a sample
# are rounded differently. A difference d of a time changes a slew, a difference over one raster
# time dt, by a relative d / dt, and d is of the order of the ulp of the time: so the difference
# grows with the number of samples N, of the order of eps * N (6.7e-11 for pulseq_epi_rs.seq,
# the longest file, 300,000 samples). The largest difference measured is 8.2e-12, of that file
# (2026-10-18, macOS); it was 1.1e-12 or less for the files of 60,000 samples or fewer.
REL = 1e-10
TIME = 1e-12  # s


def _hw_cases() -> dict:
    """The hardware structs of the check: those of the filter, the cases of `test_safe.py`, and
    the example with `x.a1` changed by 0.001 and by -0.001, at the bound of both checks, which sum
    in the same order: `|a1 + a2 + a3 - 1|` is then 0.0009999999999998899 (valid) and
    0.0010000000000000009 (not valid)."""
    cases = {name: of() for name, of in CHUNK_NAMESPACES.items()}
    cases.update({name: of() for name, of in HW_CHECK_CASES.items()})
    for name, change in (("x-at-the-bound-above", 0.001), ("x-at-the-bound-below", -0.001)):
        ns = CHUNK_NAMESPACES["example"]()
        ns.x.a1 += change
        cases[name] = ns
    return cases


HW_CASES = _hw_cases()


@pytest.fixture(scope="module")
def filtered():
    """The rows of `safe_gwf_to_pns` of the original for `chunk_waveform()` with each hardware
    of `CHUNK_NAMESPACES` and each raster of `CHUNK_DTS` (by the ID `<hardware>-<raster>`), and
    the result of `safe_hw_check` for each struct of `HW_CASES`, from one run of the command."""
    gwf = chunk_waveform()
    cases = {
        f"{scaled_id}-{dt_id}": (gwf, dt, of())
        for scaled_id, of in CHUNK_NAMESPACES.items()
        for dt_id, dt in CHUNK_DTS.items()
    }
    return safe.run_filter(COMMAND, cases, HW_CASES)


@pytest.mark.parametrize("dt_id", CHUNK_DTS)
@pytest.mark.parametrize("scaled_id", CHUNK_NAMESPACES)
def test_the_chunk_function_gives_the_rows_of_the_originals_safe_gwf_to_pns(
    filtered, scaled_id, dt_id
):
    """`_safe_gwf_to_pns_chunk` of a waveform from the state None, in one chunk and in the
    chunks of `CHUNKS` with the state of each passed to the next, gives the rows of
    `safe_gwf_to_pns` of the original (no padding, with a row of 0 in front of the waveform), to
    `FILTER_REL` of their largest magnitude. Octave read the raster and the hardware of the JSON
    as the same doubles."""
    rows, _ = filtered
    expected, inputs = rows[f"{scaled_id}-{dt_id}"]
    ns, dt, gwf = CHUNK_NAMESPACES[scaled_id](), CHUNK_DTS[dt_id], chunk_waveform()
    np.testing.assert_array_equal(
        inputs, [dt, *(getattr(getattr(ns, axis), f) for axis in "xyz" for f in SAFE_FIELDS)]
    )
    hardware = SafeHardware.from_namespace(ns)
    assert expected.shape == gwf.shape
    atol = FILTER_REL * float(np.abs(expected).max())
    whole, _ = _safe_gwf_to_pns_chunk(gwf, dt, hardware, None)
    np.testing.assert_allclose(whole, expected, rtol=0, atol=atol)
    parts, state = [], None
    for start, stop in CHUNKS:
        pns, state = _safe_gwf_to_pns_chunk(gwf[start:stop], dt, hardware, state)
        parts.append(pns)
    np.testing.assert_allclose(np.concatenate(parts), expected, rtol=0, atol=atol)


@pytest.mark.parametrize("case_id", HW_CASES)
def test_from_namespace_accepts_a_hardware_if_and_only_if_the_originals_safe_hw_check_does(
    filtered, case_id
):
    """`SafeHardware.from_namespace` accepts a struct if and only if `safe_hw_check` of the
    original gives 1. For a struct without an axis or a field, `safe_hw_check` fails (the field
    of an Octave struct that is not there), and `from_namespace` raises `ValueError`. The cases
    are in the domain of the original: every field is a finite number and `stim_limit` is above 0.
    The original does not check these, and the package does (`test_safe.py`)."""
    _, checks = filtered
    original = checks[case_id]
    try:
        SafeHardware.from_namespace(HW_CASES[case_id])
    except ValueError:
        own_accepts = False
    else:
        own_accepts = True
    assert own_accepts is (original.get("is_ok") == 1), original


@pytest.fixture(scope="module")
def calcpns(request):
    """A function of the path of a `.asc` file and of a file of `FILES`: `calcPNS` of the file with
    the `.asc` file, as `CalcPnsOracle.load` gives it. The oracle runs one time for each `.asc`
    content, on the files of `FILES` that the `spec` interpreter accepts (MATLAB reads only
    these, as in `test_matlab_oracle.py`). The function returns `((dump, rows), None)`, and
    `((None, None), error)` for a file that `spec` rejects."""
    accepted, rejected = [], {}
    for path in FILES:
        try:
            seqfile.read_seqfile(path)
        except (SeqFileError, NotSupported) as error:
            rejected[path] = error
        else:
            accepted.append(path)
    cache = getattr(request.config, "cache", None)
    cache_dir = (
        cache.mkdir("safe-oracle")
        if cache is not None
        else Path(request.config.rootpath) / ".pytest_cache" / "d" / "safe-oracle"
    )
    oracle = safe.CalcPnsOracle(cache_dir, COMMAND)
    loaded = {}

    def of(asc: Path, path: Path):
        if path in rejected:
            return (None, None), rejected[path]
        key = asc.read_bytes()
        if key not in loaded:
            loaded[key] = oracle.load(asc, accepted)
        return loaded[key][path], None

    return of


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_pns_levels_gives_the_peaks_and_the_totals_of_calcpns(calcpns, write_gradient_asc, path):
    """`pns_levels` of the file, with `hardware_from_asc` of the `.asc` file of
    `write_gradient_asc`, gives what `calcPNS` of MATLAB Pulseq gives with the same file: the
    peak and the peak of each axis (divided by the magnitude of MATLAB's gamma), to `REL` of the
    peak; and, with bins of one sample, the total of each sample of calcPNS within the level of
    that sample, to `REL` of the peak.

    calcPNS gives sample j the time `t_axis(j)`, but its row j is the slew from the gradient at
    `t_axis(j)` to the gradient at `t_axis(j + 1)`, as the samples of the package one raster time
    later: the sample of calcPNS at `(m + 0.5) * dt` is the sample `m + 1` of the package. So the
    peak time is compared with that shift: the time of the first total of calcPNS at or above
    `peak * (1 - PEAK_TOLERANCE)`, plus dt. calcPNS starts at the first gradient point (the
    samples of the package before it are 0) and does not give the slew from 0 to its first
    sample; its last rows, after the end of the last block, are not in the package.

    A sequence without gradients has no sample in calcPNS, and `NO_GRADIENTS` in `pns_levels`.
    The test skips a file that `spec` rejects."""
    asc = write_gradient_asc()
    (dump, rows), rejected = calcpns(asc, path)
    if rejected is not None:
        rules = sorted({v.rule for v in getattr(rejected, "violations", ())})
        pytest.skip(f"spec rejects the file ({', '.join(rules) or rejected})")
    assert "error" not in dump, dump["error"]
    snap = load(path)
    hardware = hardware_from_asc(asc)
    levels = pns_levels(snap, hardware=hardware)
    if dump["num_samples"] == 0:
        assert levels.reason == NO_GRADIENTS
        return
    gamma, dt = abs(dump["gamma"]), dump["grad_raster"]
    assert dt == levels.dt_s
    peak = float(rows[:, 3].max())
    assert levels.peak_hz_per_t / gamma == pytest.approx(peak, rel=REL)
    np.testing.assert_allclose(
        [levels.axis_peaks_hz_per_t[axis] / gamma for axis in "xyz"],
        rows[:, :3].max(axis=0),
        rtol=REL,
        atol=REL * peak,
    )
    first = int(np.flatnonzero(rows[:, 3] >= peak * (1 - PEAK_TOLERANCE))[0])
    assert levels.peak_time_s == pytest.approx(dump["t_axis_first"] + (first + 1) * dt, abs=TIME)

    one = pns_levels(snap, hardware=hardware, bin_s=dt)
    assert one.bin_samples == 1
    start = round(dump["t_axis_first"] / dt - 0.5) + 1
    samples = start + np.arange(rows.shape[0])
    inside = samples < one.num_samples
    total = rows[inside, 3]
    low = one.level_min_hz_per_t[samples[inside]].astype(np.float64) / gamma
    high = one.level_max_hz_per_t[samples[inside]].astype(np.float64) / gamma
    assert np.all(total >= low - REL * peak), np.flatnonzero(total < low - REL * peak)
    assert np.all(total <= high + REL * peak), np.flatnonzero(total > high + REL * peak)
