"""The analyses of a sequence: the `Analysis` protocol, the registry and the five analyses of
this package.

An analysis is a pass that calculates information about a sequence and does not change it
(the analysis passes of a compiler are the model). Each analysis has:

- `spec`, an `AnalysisSpec`: its ID, its version, a title, the description of its value, the
  names of its parameters, the rasters of the sequence that it uses, its cost and the text
  of its series.
- `compute(seq, **params)`, which gives the full Python value (for example `PnsLevels`).
  The parameters are keyword-only arguments, and their names are `spec.params`.
- `to_series(value)`, which gives the part of the value that can go into JSON, as a tuple of
  `series.Series`. An analysis with nothing for JSON gives `()`.

A package gives its analyses as entry points of the group `GROUP`
(`"pulseq_analysis.analyses"`): the name of an entry point is the ID, and the object is the
analysis. `registry()` loads them and gives a dict from each ID to its analysis. Two analyses
with one ID, an entry point that cannot load, an object with no `spec.id`, and an entry point
whose name is not the `spec.id` of its object raise `RegistryError` with the names of the
packages.

The analyses of this package:

- `seq.index` (`SEQ_INDEX`): `seq_index.sequence_index`, no parameters, no series.
- `gradient.peaks` (`GRADIENT_PEAKS`): `grad_peaks.gradient_peaks`, no parameters, no
  series.
- `gradient.blocks` (`GRADIENT_BLOCKS`): `grad_peaks.block_gradient_values`, no parameters,
  no series.
- `pns.safe.levels` (`PNS_SAFE_LEVELS`): `pns_levels.pns_levels`, the parameters `hardware`
  (necessary: a pair of a SAFE hardware struct and its name), `thresholds_hz_per_t` and
  `bin_s`, and the series of the level and of the runs above each threshold.
- `gradient.spectrum` (`GRADIENT_SPECTRUM`): `grad_spectrum.gradient_spectrum`, no
  parameters, and the series of the spectrum.

Each of these functions keeps its result for the sequence object (`_kept`), so `compute`
of a second call for one sequence gives the kept object. `gradient_peaks` has a `window`
argument, but `gradient.peaks` is of the whole sequence and has no such parameter (a result
with a window is not kept). `grad_spectrum.gradient_spectrum` has the arguments of the
method, but `gradient.spectrum` has no parameters and uses the defaults.
"""

import importlib.metadata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

import numpy as np
import pypulseq as pp

from .grad_peaks import BlockGradientValues, GradientPeaks, block_gradient_values, gradient_peaks
from .grad_spectrum import GradientSpectrum, gradient_spectrum
from .pns_levels import BIN_S, PnsLevels, pns_levels
from .seq_index import NO_GRADIENTS, SequenceIndex, sequence_index
from .series import Series, SeriesKind

GROUP = "pulseq_analysis.analyses"


class RegistryError(Exception):
    """An entry point that cannot be used, for example two packages that give one analysis
    ID."""


@dataclass(frozen=True)
class AnalysisSpec:
    """The specification of an analysis."""

    id: str  # for example "pns.safe.levels"
    version: int
    title: str
    description: str  # what the value is: the contract
    params: tuple[str, ...]  # the names of the keyword arguments of compute
    rasters: tuple[str, ...]  # the rasters of the sequence that it uses
    cost: str = "slow"  # "fast" or "slow"
    series: str | None = None  # what to_series gives: names, kinds, units, coordinates


class Analysis(Protocol):
    """An analysis: `spec`, `compute` and `to_series` (see the module docstring)."""

    spec: AnalysisSpec

    def compute(self, seq: pp.Sequence, **params: Any) -> Any: ...

    def to_series(self, value: Any) -> tuple[Series, ...]: ...


_GRADIENT_RASTERS = ("GradientRasterTime", "BlockDurationRaster")


class _SeqIndex:
    spec = AnalysisSpec(
        id="seq.index",
        version=1,
        title="Block table",
        description=(
            "A `SequenceIndex`, the block table of the sequence. It has one entry for each "
            "block, in play order: the block ID, the start and the duration in seconds from "
            "the start of the sequence, and the number of the unique RF, ADC and gradient "
            "events (x, y, z) of the block, 0 for no event. It also gives the play index of "
            "the first block of each unique event, and the end of the sequence. The numbers "
            "of the events start at 1, in the order of their first use. It reads no block "
            "with `get_block`."
        ),
        params=(),
        rasters=(),
        cost="fast",
        series=None,
    )

    def compute(self, seq: pp.Sequence) -> SequenceIndex:
        """`seq_index.sequence_index(seq)`."""
        return sequence_index(seq)

    def to_series(self, value: SequenceIndex) -> tuple[Series, ...]:
        """`()`: this analysis has no series."""
        return ()


class _GradientPeaks:
    spec = AnalysisSpec(
        id="gradient.peaks",
        version=1,
        title="Gradient peaks",
        description=(
            "A `GradientPeaks`: for each logical axis (x, y, z) of the whole sequence, the "
            "largest absolute amplitude (Hz/m), the largest slew (Hz/m/s) and the RMS "
            "amplitude (Hz/m), each with its block ID and its time (seconds from the start "
            "of the sequence), and the largest magnitude of the three-axis vector. The slew "
            "is the largest of the slope of each straight line of each event and the step "
            "at each block junction, divided by the gradient raster of the file. When "
            "several blocks have the largest value, the first in play order gets it. The "
            "values are of the logical axes of the file, not of the axes of a scanner, and "
            "they are not compared with a limit. The values are in the units of pypulseq, "
            "with no gamma. Divide them by the magnitude of gamma (Hz/T) to get T/m and "
            "T/m/s. A sequence with the rotation extension raises `NotImplementedError`. The "
            "result is read-only, and it is kept for the sequence object."
        ),
        params=(),
        rasters=_GRADIENT_RASTERS,
        cost="fast",
        series=None,
    )

    def compute(self, seq: pp.Sequence) -> GradientPeaks:
        """`grad_peaks.gradient_peaks(seq)`: the kept result for the sequence object."""
        return gradient_peaks(seq)

    def to_series(self, value: GradientPeaks) -> tuple[Series, ...]:
        """`()`: this analysis has no series."""
        return ()


class _GradientBlocks:
    spec = AnalysisSpec(
        id="gradient.blocks",
        version=1,
        title="Gradient values of each block",
        description=(
            "A `BlockGradientValues`: the values of `gradient.peaks` for each block, in "
            "play order, not only the largest. For each logical axis (x, y, z) it gives the "
            "largest absolute amplitude (Hz/m) of the event of the block and its time, the "
            "largest slope (Hz/m/s) of a line of that event and the start of that line, and "
            "the junction step (Hz/m/s) at the start of the block. It also gives the largest "
            "magnitude of the three-axis vector in the block and its first time. A block "
            "with no event on an axis has the peak and the slope 0 there, at the start of "
            "the block. The largest of each amplitude array is the value of `gradient.peaks`. "
            "Its slew is the larger of the largest segment slew and the largest junction "
            "step. "
            "The values are in the units of pypulseq, with no gamma. Divide them by the "
            "magnitude of gamma (Hz/T) to get T/m and T/m/s. A sequence with the rotation "
            "extension raises `NotImplementedError`. The result is read-only, and it is kept "
            "for the sequence object."
        ),
        params=(),
        rasters=_GRADIENT_RASTERS,
        cost="fast",
        series=None,
    )

    def compute(self, seq: pp.Sequence) -> BlockGradientValues:
        """`grad_peaks.block_gradient_values(seq)`: the kept result for the sequence object."""
        return block_gradient_values(seq)

    def to_series(self, value: BlockGradientValues) -> tuple[Series, ...]:
        """`()`: this analysis has no series (a later version can give `POINTS` series)."""
        return ()


class _PnsSafeLevels:
    spec = AnalysisSpec(
        id="pns.safe.levels",
        version=1,
        title="SAFE PNS levels",
        description=(
            "A `PnsLevels`: the SAFE model of peripheral nerve stimulation (PNS) on the "
            "gradients of the sequence, with one sample of each axis for each gradient "
            "raster time. A value is in Hz/T: the fraction of the stimulation limit times the "
            "magnitude of gamma. Divide it by the magnitude of gamma (Hz/T) to get the "
            "fraction (1 is 100 %). The total of a sample is `sqrt(x^2 + y^2 + z^2)` of the "
            "three axis values, and sample `k` is at the time `(k + 0.5) * dt_s`. The result "
            "has the peak total, its time, the peak of each axis, the minimum and the "
            "maximum total of each bin of `bin_samples` samples (float32, each total of a "
            "bin is in its range), and, for each threshold, the runs of consecutive samples "
            "at or above it, in time order. The tuple of a threshold is not empty if and "
            "only if the peak is at or above it. The hardware is necessary: `hardware` is a pair of a "
            "SAFE hardware struct and its name (`asc.hardware_from_asc(path)` makes one from "
            "a Siemens gradient .asc file). There is no default hardware; for "
            "pypulseq's example hardware, which is not a real scanner, give "
            '`hardware=(safe_example_hw(), "<a label>")`. A value that is not such a pair '
            "raises `TypeError`. A struct with a missing axis or field, a field that is not a "
            "finite real number, a `stim_limit` not above 0 or an axis with `a1 + a2 + a3` "
            "not within 0.001 of 1 raises `TypeError` or `ValueError`, before the sequence is "
            "read. "
            "`thresholds_hz_per_t` is a tuple of finite numbers above 0, in Hz/T, with no two "
            "equal. For a fraction f of the limit, give f times the magnitude of gamma. The "
            "default is `()`: no runs. A sequence with no gradient event has no "
            "prediction (`reason` is `NO_GRADIENTS`). A sequence with the rotation "
            "extension raises `NotImplementedError`. The arrays are read-only, and the "
            "result is kept for the sequence object, the hardware, the thresholds and the bin "
            "size. `bin_s` is the length of a bin of the level in seconds. It gives a whole "
            "number of samples: the nearest number when `bin_s / dt` is within "
            "`ON_RASTER_TOLERANCE` of it, else the number rounded down. The bin has at least "
            "one sample, and is longer when the level would have more than `MAX_BINS` bins. "
            "It is a finite number above 0; the default is 5 ms (500 samples at the 10 us "
            "raster). A `bool` or a value that is not a number raises `TypeError`, "
            "and a value that is not finite or not above 0 raises `ValueError`."
        ),
        params=("hardware", "thresholds_hz_per_t", "bin_s"),
        rasters=_GRADIENT_RASTERS,
        cost="slow",
        series=(
            "A sequence with no gradient event gives (). Else: "
            '`pns_total`, ENVELOPE, unit "Hz/T", arrays `min` and `max` (float32: '
            '`level_min_hz_per_t` and `level_max_hz_per_t`), `coord_unit` "s", '
            "`coord_start` 0, `coord_step` `bin_samples * dt_s`, `coord_end` "
            "`num_samples * dt_s`, `meta` `hardware`, `dt_s`, `bin_samples`, "
            "`num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y` and "
            "`axis_peaks_z`. And one series for each threshold, in the order of "
            "`thresholds_hz_per_t`: `pns_above_<k>`, with `<k>` the position of the "
            'threshold from 0 (`pns_above_0`, `pns_above_1`), RUNS, unit "Hz/T", '
            '`coord_unit` "s", arrays `start`, `end`, `num_samples` (int64), `peak` and '
            "`peak_time_s` (float64), one entry for each run (the times of its first and "
            "last sample), `meta` `threshold` (the value in Hz/T). With no threshold, "
            "`to_series` gives only `pns_total`. The values of `min`, `max`, `peak`, "
            "`axis_peaks_<axis>` and `threshold` are in Hz/T."
        ),
    )

    def compute(
        self,
        seq: pp.Sequence,
        *,
        hardware: tuple[SimpleNamespace, str],
        thresholds_hz_per_t: tuple[float, ...] = (),
        bin_s: float = BIN_S,
    ) -> PnsLevels:
        """`pns_levels.pns_levels(seq, hardware=hardware,
        thresholds_hz_per_t=thresholds_hz_per_t, bin_s=bin_s)`: the kept result for the
        sequence object, the hardware, the thresholds and the bin size. `hardware` is
        necessary; a call without it, or with a value that is not a pair, raises TypeError
        before the sequence is read."""
        return pns_levels(
            seq,
            hardware=hardware,
            thresholds_hz_per_t=thresholds_hz_per_t,
            bin_s=bin_s,
        )

    def to_series(self, value: PnsLevels) -> tuple[Series, ...]:
        """The series of `spec.series`: the level of `value` (`pns_total`) and the runs
        for each threshold of `value.above` (`pns_above_<k>`, `<k>` the position of the
        threshold from 0), all in Hz/T. The result is `(pns_total,)` for a result with no
        threshold, and `()` for a result with `reason == NO_GRADIENTS`."""
        if value.reason == NO_GRADIENTS:
            return ()

        level = Series(
            name="pns_total",
            kind=SeriesKind.ENVELOPE,
            unit="Hz/T",
            arrays={"min": value.level_min_hz_per_t, "max": value.level_max_hz_per_t},
            coord_unit="s",
            coord_start=0.0,
            coord_step=value.bin_samples * value.dt_s,
            coord_end=value.num_samples * value.dt_s,
            meta={
                "hardware": value.hardware,
                "dt_s": value.dt_s,
                "bin_samples": value.bin_samples,
                "num_samples": value.num_samples,
                "peak": value.peak_hz_per_t,
                "peak_time_s": value.peak_time_s,
                "axis_peaks_x": value.axis_peaks_hz_per_t["x"],
                "axis_peaks_y": value.axis_peaks_hz_per_t["y"],
                "axis_peaks_z": value.axis_peaks_hz_per_t["z"],
            },
        )
        runs = []
        for k, (threshold, intervals) in enumerate(value.above.items()):
            runs.append(
                Series(
                    name=f"pns_above_{k}",
                    kind=SeriesKind.RUNS,
                    unit="Hz/T",
                    coord_unit="s",
                    arrays={
                        "start": np.array([i.start_s for i in intervals], dtype=np.float64),
                        "end": np.array([i.end_s for i in intervals], dtype=np.float64),
                        "num_samples": np.array([i.num_samples for i in intervals], dtype=np.int64),
                        "peak": np.array([i.peak_hz_per_t for i in intervals], dtype=np.float64),
                        "peak_time_s": np.array(
                            [i.peak_time_s for i in intervals], dtype=np.float64
                        ),
                    },
                    meta={"threshold": threshold},
                )
            )
        return (level, *runs)


class _GradientSpectrum:
    spec = AnalysisSpec(
        id="gradient.spectrum",
        version=1,
        title="Gradient spectrum",
        description=(
            "A `GradientSpectrum`: the spectrum of the gradient waveform of the whole "
            "sequence, by the method of `calculate_gradient_spectrum` of pypulseq. Hann "
            "windows with 50 % overlap, the magnitude spectrum of each window, and the "
            "maximum over windows. The result has `frequency_hz` (from 0 up to the largest "
            "frequency, float64), the spectrum of each logical axis (`axes`, with the keys "
            "x, y, z) and `rss`, the root-sum-of-squares of the three axes in each window, "
            "then the maximum over windows. The values are in Hz/m/sqrt(Hz), the unit of "
            "the gradients of a `.seq` file, with no gamma. To get mT/m/sqrt(Hz), multiply "
            "them by 1e3 / abs(gamma), with gamma in Hz/T. A sequence with no gradient event has "
            "no spectrum (`reason` is `NO_GRADIENTS`). A sequence with the rotation "
            "extension raises `NotImplementedError`. The arrays are read-only, and the "
            "result is kept for the sequence object. This analysis has no parameters and "
            "uses the defaults of pypulseq. A caller that needs other values calls "
            "`grad_spectrum.gradient_spectrum` with them."
        ),
        params=(),
        rasters=_GRADIENT_RASTERS,
        cost="slow",
        series=(
            "A sequence with no gradient event gives (). Else one series: "
            '`gradient_spectrum`, SAMPLES, unit "Hz/m/sqrt(Hz)", arrays `value` (`rss`), '
            '`x`, `y` and `z` in this order (float64), `coord_unit` "Hz", `coord_start` 0, '
            "`coord_step` the first nonzero frequency (`frequency_hz[1]`), so that "
            "`coord_start + k * coord_step` is `frequency_hz[k]`, `meta` "
            "`max_frequency_hz`, `window_s` and `frequency_oversampling`."
        ),
    )

    def compute(self, seq: pp.Sequence) -> GradientSpectrum:
        """`grad_spectrum.gradient_spectrum(seq)`: the kept result for the sequence
        object, with the defaults."""
        return gradient_spectrum(seq)

    def to_series(self, value: GradientSpectrum) -> tuple[Series, ...]:
        """The series of `spec.series`: the spectrum of `value` (`gradient_spectrum`), or
        `()` for a result with `reason == NO_GRADIENTS`. `meta` has the three arguments of the
        call that made `value` (the defaults for a value of `compute`)."""
        if value.reason == NO_GRADIENTS:
            return ()
        return (
            Series(
                name="gradient_spectrum",
                kind=SeriesKind.SAMPLES,
                unit="Hz/m/sqrt(Hz)",
                coord_unit="Hz",
                coord_start=0.0,
                coord_step=float(value.frequency_hz[1]),
                arrays={
                    "value": value.rss,
                    "x": value.axes["x"],
                    "y": value.axes["y"],
                    "z": value.axes["z"],
                },
                meta={
                    "max_frequency_hz": value.max_frequency_hz,
                    "window_s": value.window_s,
                    "frequency_oversampling": value.frequency_oversampling,
                },
            ),
        )


SEQ_INDEX = _SeqIndex()
GRADIENT_PEAKS = _GradientPeaks()
GRADIENT_BLOCKS = _GradientBlocks()
PNS_SAFE_LEVELS = _PnsSafeLevels()
GRADIENT_SPECTRUM = _GradientSpectrum()


def registry() -> dict[str, Analysis]:
    """The installed analyses of `GROUP`, by `spec.id`. Two analyses with one ID are a
    `RegistryError` that names both packages. An entry point whose name is not the `spec.id`
    of its object is a `RegistryError` that names the entry point, its package and the
    `spec.id`."""
    found: dict[str, tuple[Analysis, str]] = {}
    for ep in importlib.metadata.entry_points(group=GROUP):
        analysis = _load(ep, GROUP)
        try:
            analysis_id = analysis.spec.id
        except AttributeError as e:
            raise RegistryError(
                f"the analysis entry point {ep.name!r} of the package {_package(ep)!r} "
                "has no `spec.id`"
            ) from e
        if ep.name != analysis_id:
            raise RegistryError(
                f"the name of the analysis entry point {ep.name!r} of the package "
                f"{_package(ep)!r} is not the `spec.id` of its object, {analysis_id!r}"
            )
        _add(found, analysis_id, analysis, ep, f"the analysis ID {analysis_id!r}")
    return {analysis_id: analysis for analysis_id, (analysis, _) in found.items()}


def _package(ep: Any) -> str:
    """The name of the distribution of the entry point `ep`, when it is known."""
    dist = getattr(ep, "dist", None)
    return dist.name if dist is not None else "an unknown package"


def _load(ep: Any, group: str) -> Any:
    """The object of the entry point `ep`. A failure is a `RegistryError` that names the
    entry point and its package."""
    try:
        return ep.load()
    except Exception as e:
        raise RegistryError(
            f"cannot load the entry point {ep.name!r} of the group {group!r} from the package "
            f"{_package(ep)!r}: {type(e).__name__}: {e}"
        ) from e


def _add(found: dict[str, tuple[Any, str]], key: str, obj: Any, ep: Any, what: str) -> None:
    """Add `obj` with the package of `ep` to `found`. A key that is in `found` is a
    `RegistryError` that names both packages."""
    package = _package(ep)
    if key in found:
        raise RegistryError(f"the packages {found[key][1]!r} and {package!r} both give {what}")
    found[key] = (obj, package)
