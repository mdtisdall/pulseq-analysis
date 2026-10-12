"""The events of a Pulseq file, decoded from the model of layer 1 (`model.SequenceData`).

`decode_rf`, `decode_gradients` and `decode_adc` each give every row of a table of the model,
whether a block uses it or not, as an event in a `types.MappingProxyType` by file ID. The order
is that of the table. `[GRADIENTS]` and `[TRAP]` share one ID space, so `decode_gradients` gives
both kinds: the rows of `[GRADIENTS]`, then those of `[TRAP]`. A shape that several events use
is decompressed once in one call.

Each event is a frozen dataclass made with `model._model`: its arrays are read-only, two events
are equal when each field is equal, and an event can be pickled. A time is in s from the start
of the event (after `delay`). An amplitude is in Hz (RF) or Hz/m (gradients), as in the file. No
value of a target (gamma, dead times, ringdown times) is used.

The times of the gradient samples are those of `getBlock` of MATLAB Pulseq (`Sequence.m`), for
`n` samples. An arbitrary gradient with time ID 0 has a sample at the centre of each cell of the
gradient raster `dt`: `tt = (i + 0.5) * dt` and `shape_dur = n * dt`. With time ID -1
(oversampled) the samples are half a raster apart: `tt = (i + 1) / 2 * dt` and
`shape_dur = (n + 1) / 2 * dt`. With a time shape, `tt` is the shape times `dt`, and `shape_dur`
is the last time.

The RF samples are those that the scanner's reader plays (`ExternalSequence.cpp` of the C++
oracle, `decodeBlock`, lines 2010 to 2063). Where that reader and MATLAB Pulseq disagree, the
package follows the reader, by the decision of the user. Each RF sample is at the centre of a
cell of the dwell time, `t = (i + 0.5) * dwell`, and `shape_dur` is the number of samples times
the dwell time:

- Without a time shape, the dwell time is the RF raster, and the samples are those of the shapes.
- With a time shape that the reader takes as regular (`model._rf_time_step`), the dwell time is
  the step of the shape times the RF raster, and the samples are those of the shapes. The first
  time of the shape is not used.
- With another time shape, the reader resamples the pulse to the RF raster (`model._rf_resample`):
  the dwell time is the RF raster, and each cell plays one stored sample.

MATLAB Pulseq (`rfFromLibData` of `Sequence.m`) keeps the stored samples and the times of the
time shape (the shape times the RF raster), and ends the pulse at the last time rounded up to the
RF raster.
"""

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from .model import SequenceData, _model, _rf_resample, _rf_time_step


@_model
class Trapezoid:
    """A trapezoid gradient (`[TRAP]`). Times in s."""

    id: int
    amplitude: float  # Hz/m
    rise_time: float
    flat_time: float
    fall_time: float
    delay: float

    @property
    def shape_dur(self) -> float:
        """The duration after the delay: the rise, flat and fall times (s)."""
        return self.rise_time + self.flat_time + self.fall_time

    @property
    def first(self) -> float:
        """The amplitude at the start (Hz/m): 0.0."""
        return 0.0

    @property
    def last(self) -> float:
        """The amplitude at the end (Hz/m): 0.0."""
        return 0.0


@_model
class ArbitraryGradient:
    """An arbitrary gradient (`[GRADIENTS]`). The module docstring gives the times `tt`.

    `waveform` is the amplitude times the samples of the shape `shape_id`. `first` and `last`
    are the amplitudes at the start and at the end of the event, from the model.
    """

    id: int
    amplitude: float  # Hz/m
    shape_id: int
    time_id: int  # 0 is the default raster, -1 is half of it
    waveform: np.ndarray  # Hz/m
    tt: np.ndarray  # s
    shape_dur: float  # s
    first: float  # Hz/m
    last: float  # Hz/m
    delay: float  # s


# A gradient event of either kind.
GradEvent = Trapezoid | ArbitraryGradient


@_model
class RfEvent:
    """An RF event (`[RF]`). The module docstring gives the samples and their times `t`.

    `magnitude` is the amplitude times the magnitude shape, and `phase` is 2 pi times the phase
    shape, at the samples that the scanner's reader plays. The amplitude and the shape IDs
    identify the pulse without its offsets. `center` is `None` for a file of version 1.4, which
    has no center. `use` is one character, as in the file (`u` for a file of version 1.4).
    """

    id: int
    amplitude: float  # Hz
    mag_id: int
    phase_id: int
    time_id: int  # 0 is the default raster
    magnitude: np.ndarray  # Hz
    phase: np.ndarray  # rad
    t: np.ndarray  # s
    shape_dur: float  # s
    center: float | None  # s
    delay: float  # s
    freq_ppm: float  # ppm
    phase_ppm: float  # rad/MHz
    freq_offset: float  # Hz
    phase_offset: float  # rad
    use: str


@_model
class AdcEvent:
    """An ADC event (`[ADC]`).

    `phase_modulation` is the shape `phase_shape_id` as the file stores it, decompressed, with no
    factor, or `None` when `phase_shape_id` is 0. The specification gives it no unit.
    """

    id: int
    num_samples: int
    dwell: float  # s
    delay: float  # s
    freq_ppm: float  # ppm
    phase_ppm: float  # rad/MHz
    freq_offset: float  # Hz
    phase_offset: float  # rad
    phase_shape_id: int  # 0 is no modulation
    phase_modulation: np.ndarray | None


class _Shapes:
    """The decompressed samples of the shapes of `data`, each decompressed on its first use."""

    def __init__(self, data: SequenceData) -> None:
        self._shapes = data.shapes
        self._samples: dict[int, np.ndarray] = {}

    def __getitem__(self, shape_id: int) -> np.ndarray:
        if shape_id not in self._samples:
            self._samples[shape_id] = self._shapes[shape_id].samples()
        return self._samples[shape_id]


def decode_rf(data: SequenceData) -> Mapping[int, RfEvent]:
    """Each row of `data.rf` as an `RfEvent`, by RF ID."""
    shapes = _Shapes(data)
    raster = data.rasters.rf
    events = {}
    for row in data.rf:
        amplitude = float(row["amplitude"])
        mag = shapes[int(row["mag_id"])]
        phase = shapes[int(row["phase_id"])]
        time_id = int(row["time_id"])
        dwell = raster
        if time_id > 0:
            step = _rf_time_step(data.shapes[time_id])
            if step is not None:
                dwell = step * raster
            else:
                played = _rf_resample(shapes[time_id])
                mag, phase = mag[played], phase[played]
        t = (np.arange(mag.size) + 0.5) * dwell
        shape_dur = mag.size * dwell
        events[int(row["id"])] = RfEvent(
            id=int(row["id"]),
            amplitude=amplitude,
            mag_id=int(row["mag_id"]),
            phase_id=int(row["phase_id"]),
            time_id=time_id,
            magnitude=amplitude * mag,
            phase=2 * np.pi * phase,
            t=t,
            shape_dur=shape_dur,
            center=None if data.version < (1, 5, 0) else float(row["center"]),
            delay=float(row["delay"]),
            freq_ppm=float(row["freq_ppm"]),
            phase_ppm=float(row["phase_ppm"]),
            freq_offset=float(row["freq_offset"]),
            phase_offset=float(row["phase_offset"]),
            use=str(row["use"]),
        )
    return MappingProxyType(events)


def decode_gradients(data: SequenceData) -> Mapping[int, GradEvent]:
    """Each row of `data.grad` as an `ArbitraryGradient` and each row of `data.trap` as a
    `Trapezoid`, by gradient ID."""
    shapes = _Shapes(data)
    dt = data.rasters.gradient
    events: dict[int, GradEvent] = {}
    for row in data.grad:
        amplitude = float(row["amplitude"])
        samples = shapes[int(row["shape_id"])]
        n = samples.size
        time_id = int(row["time_id"])
        if time_id == 0:
            tt = (np.arange(n) + 0.5) * dt
            shape_dur = n * dt
        elif time_id == -1:
            tt = np.arange(1, n + 1) / 2 * dt
            shape_dur = (n + 1) / 2 * dt
        else:
            tt = shapes[time_id] * dt
            shape_dur = float(tt[-1])
        events[int(row["id"])] = ArbitraryGradient(
            id=int(row["id"]),
            amplitude=amplitude,
            shape_id=int(row["shape_id"]),
            time_id=time_id,
            waveform=amplitude * samples,
            tt=tt,
            shape_dur=shape_dur,
            first=float(row["first"]),
            last=float(row["last"]),
            delay=float(row["delay"]),
        )
    for row in data.trap:
        events[int(row["id"])] = Trapezoid(
            id=int(row["id"]),
            amplitude=float(row["amplitude"]),
            rise_time=float(row["rise"]),
            flat_time=float(row["flat"]),
            fall_time=float(row["fall"]),
            delay=float(row["delay"]),
        )
    return MappingProxyType(events)


def decode_adc(data: SequenceData) -> Mapping[int, AdcEvent]:
    """Each row of `data.adc` as an `AdcEvent`, by ADC ID."""
    shapes = _Shapes(data)
    events = {}
    for row in data.adc:
        phase_shape_id = int(row["phase_shape_id"])
        events[int(row["id"])] = AdcEvent(
            id=int(row["id"]),
            num_samples=int(row["num_samples"]),
            dwell=float(row["dwell"]),
            delay=float(row["delay"]),
            freq_ppm=float(row["freq_ppm"]),
            phase_ppm=float(row["phase_ppm"]),
            freq_offset=float(row["freq_offset"]),
            phase_offset=float(row["phase_offset"]),
            phase_shape_id=phase_shape_id,
            phase_modulation=shapes[phase_shape_id] if phase_shape_id else None,
        )
    return MappingProxyType(events)
