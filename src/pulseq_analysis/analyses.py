"""The analyses of a sequence: the `Analysis` protocol, the registry and the four analyses of
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
with one ID, an entry point that cannot load, and an object with no `spec.id` raise
`RegistryError` with the names of the packages.

The analyses of this package:

- `seq.index` (`SEQ_INDEX`): `seq_index.sequence_index`, no parameters, no series.
- `gradient.limits` (`GRADIENT_LIMITS`): `grad_limits.gradient_limits`, the parameter
  `gamma`, no series.
- `gradient.blocks` (`GRADIENT_BLOCKS`): `grad_limits.block_gradient_values`, the parameter
  `gamma`, no series.
- `pns.safe.levels` (`PNS_SAFE_LEVELS`): `pns.pns_levels_for`, the parameters `hardware` and
  `thresholds`, and the series of the level and of the runs above each threshold.

`gradient_limits` has a `window` argument, but `gradient.limits` is of the whole sequence and
has no such parameter. `pns.pns_levels_for` keeps its result for the sequence object, so
`compute` of `pns.safe.levels` gives the kept object.
"""

import importlib.metadata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

import numpy as np
import pypulseq as pp

from .grad_limits import BlockGradientValues, GradientLimits, block_gradient_values, gradient_limits
from .pns import pns_levels_for
from .pns_levels import NO_GRADIENTS, PNS_LIMIT, PnsLevels
from .seq_index import SequenceIndex, sequence_index
from .seq_utils import GAMMA
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
    series: str | None = None  # what to_series gives: names, kinds, units, times


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


class _GradientLimits:
    spec = AnalysisSpec(
        id="gradient.limits",
        version=1,
        title="Gradient limits",
        description=(
            "A `GradientLimits`: for each logical axis (x, y, z) of the whole sequence, the "
            "largest absolute amplitude (mT/m), the largest slew (T/m/s) and the RMS "
            "amplitude (mT/m), each with its block ID and its time (seconds from the start "
            "of the sequence), and the largest magnitude of the three-axis vector. The slew "
            "is the largest of the slope of each straight line of each event and the step "
            "at each block junction, divided by the gradient raster of the file. When "
            "several blocks have the largest value, the first in play order gets it. The "
            "values are of the logical axes of the file, not of the axes of a scanner, and "
            "they are not compared with a limit. `gamma` (Hz/T) converts the values from "
            "Hz/m. A sequence with the rotation extension raises `NotImplementedError`."
        ),
        params=("gamma",),
        rasters=_GRADIENT_RASTERS,
        cost="fast",
        series=None,
    )

    def compute(self, seq: pp.Sequence, *, gamma: float = GAMMA) -> GradientLimits:
        """`grad_limits.gradient_limits(seq, gamma=gamma)`."""
        return gradient_limits(seq, gamma=gamma)

    def to_series(self, value: GradientLimits) -> tuple[Series, ...]:
        """`()`: this analysis has no series."""
        return ()


class _GradientBlocks:
    spec = AnalysisSpec(
        id="gradient.blocks",
        version=1,
        title="Gradient values of each block",
        description=(
            "A `BlockGradientValues`: the values of `gradient.limits` for each block, in "
            "play order, not only the largest. For each logical axis (x, y, z) it gives the "
            "largest absolute amplitude (mT/m) of the event of the block and its time, the "
            "largest slope (T/m/s) of a line of that event and the start of that line, and "
            "the junction step (T/m/s) at the start of the block. It also gives the largest "
            "magnitude of the three-axis vector in the block and its first time. A block "
            "with no event on an axis has the peak and the slope 0 there, at the start of "
            "the block. The largest of each array is the value of `gradient.limits`. "
            "`gamma` (Hz/T) converts the values from Hz/m. A sequence with the rotation "
            "extension raises `NotImplementedError`."
        ),
        params=("gamma",),
        rasters=_GRADIENT_RASTERS,
        cost="fast",
        series=None,
    )

    def compute(self, seq: pp.Sequence, *, gamma: float = GAMMA) -> BlockGradientValues:
        """`grad_limits.block_gradient_values(seq, gamma=gamma)`."""
        return block_gradient_values(seq, gamma=gamma)

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
            "raster time. A value is a fraction of the stimulation limit: 1 is 100 %. The "
            "total of a sample is `sqrt(x^2 + y^2 + z^2)` of the three axis values, and "
            "sample `k` is at the time `(k + 0.5) * dt_s`. The result has the peak total, "
            "its time, the peak of each axis, the minimum and the maximum total of each bin "
            "of `bin_samples` samples (float32, each total of a bin is in its range), and, "
            "for each threshold, the runs of consecutive samples at or above it, in time "
            "order. The tuple of a threshold is not empty if and only if the peak is at or "
            "above it. `hardware` is a pair of a SAFE hardware struct and its name, or None "
            "for the example hardware of pypulseq, which is not a real scanner. "
            "`thresholds` is a tuple of finite numbers above 0, with no two equal, "
            "and the default is `(1.0,)`. A sequence with no gradient event has no "
            "prediction (`reason` is `NO_GRADIENTS`). A sequence with the rotation "
            "extension raises `NotImplementedError`. The result is kept for the sequence "
            "object, the hardware and the thresholds."
        ),
        params=("hardware", "thresholds"),
        rasters=_GRADIENT_RASTERS,
        cost="slow",
        series=(
            "A sequence with no gradient event gives (). Else: "
            '`pns_total`, ENVELOPE, unit "1", arrays `min` and `max` (float32: `level_min` '
            "and `level_max`), `t0_s` 0, `step_s` `bin_samples * dt_s`, `end_s` "
            "`num_samples * dt_s`, `meta` `hardware`, `asc_file`, `dt_s`, `bin_samples`, "
            "`num_samples`, `peak`, `peak_time_s`, `axis_peaks_x`, `axis_peaks_y` and "
            "`axis_peaks_z`. And one series for each threshold, in the order of "
            '`thresholds`: `pns_above_<t>`, with `<t>` the threshold as `f"{t:g}"` (for '
            'example `pns_above_1`, `pns_above_0.8`), RUNS, unit "1", arrays `start_s`, '
            "`end_s`, `num_samples` (int64), `peak` and `peak_time_s` (float64), one entry "
            "for each run (the times of its first and last sample), `meta` `threshold`. "
            "Two thresholds with the same text of `:g` (for example 1.0000001 and "
            "1.0000002) raise `ValueError` in `to_series`."
        ),
    )

    def compute(
        self,
        seq: pp.Sequence,
        *,
        hardware: tuple[SimpleNamespace, str] | None = None,
        thresholds: tuple[float, ...] = (PNS_LIMIT,),
    ) -> PnsLevels:
        """`pns.pns_levels_for(seq, hardware=hardware, thresholds=thresholds)`: the kept
        result for the sequence object, the hardware and the thresholds."""
        return pns_levels_for(seq, hardware=hardware, thresholds=thresholds)

    def to_series(self, value: PnsLevels) -> tuple[Series, ...]:
        """The series of `spec.series`: the level of `value` (`pns_total`) and the runs
        for each threshold of `value.above` (`pns_above_<t>`, `<t>` as `f"{t:g}"`), or `()`
        for a result with `reason == NO_GRADIENTS`.

        Raises ValueError when two thresholds have the same name with `:g` (for example
        1.0000001 and 1.0000002), because two series would have one name."""
        if value.reason == NO_GRADIENTS:
            return ()
        names = [f"pns_above_{t:g}" for t in value.above]
        if len(set(names)) != len(names):
            raise ValueError(
                f"two thresholds of {list(value.above)!r} have the same series name: {names!r}"
            )

        level = Series(
            name="pns_total",
            kind=SeriesKind.ENVELOPE,
            unit="1",
            arrays={"min": value.level_min, "max": value.level_max},
            t0_s=0.0,
            step_s=value.bin_samples * value.dt_s,
            end_s=value.num_samples * value.dt_s,
            meta={
                "hardware": value.hardware,
                "asc_file": value.asc_file,
                "dt_s": value.dt_s,
                "bin_samples": value.bin_samples,
                "num_samples": value.num_samples,
                "peak": value.peak,
                "peak_time_s": value.peak_time_s,
                "axis_peaks_x": value.axis_peaks["x"],
                "axis_peaks_y": value.axis_peaks["y"],
                "axis_peaks_z": value.axis_peaks["z"],
            },
        )
        runs = []
        for name, (threshold, intervals) in zip(names, value.above.items(), strict=True):
            runs.append(
                Series(
                    name=name,
                    kind=SeriesKind.RUNS,
                    unit="1",
                    arrays={
                        "start_s": np.array([i.start_s for i in intervals], dtype=np.float64),
                        "end_s": np.array([i.end_s for i in intervals], dtype=np.float64),
                        "num_samples": np.array([i.num_samples for i in intervals], dtype=np.int64),
                        "peak": np.array([i.peak for i in intervals], dtype=np.float64),
                        "peak_time_s": np.array(
                            [i.peak_time_s for i in intervals], dtype=np.float64
                        ),
                    },
                    meta={"threshold": threshold},
                )
            )
        return (level, *runs)


SEQ_INDEX = _SeqIndex()
GRADIENT_LIMITS = _GradientLimits()
GRADIENT_BLOCKS = _GradientBlocks()
PNS_SAFE_LEVELS = _PnsSafeLevels()


def registry() -> dict[str, Analysis]:
    """The installed analyses of `GROUP`, by `spec.id`. Two analyses with one ID are a
    `RegistryError` that names both packages."""
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
