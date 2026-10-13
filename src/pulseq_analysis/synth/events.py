"""The events of a Pulseq file, decoded from the model of layer 1 (`model.SequenceData`) that the
`spec` interpreter read: the decoder of `spec` (stage 2 of section 7.2 of
`docs/plans/parser-redesign.md`). A plugin interpreter gives its own decoding
(`decoding.decode`); these functions refuse its model.

`decode_rf`, `decode_gradients` and `decode_adc` each give every row of a table of the model,
whether a block uses it or not, as an event in a `types.MappingProxyType` by file ID. The order
is that of the table. `[GRADIENTS]` and `[TRAP]` share one ID space, so `decode_gradients` gives
both kinds: the rows of `[GRADIENTS]`, then those of `[TRAP]`. A shape that several events use
is decompressed once in one call.

Each event is a frozen dataclass made with `model._model`: its arrays are read-only, two events
are equal when each field is equal, and an event can be pickled. A time is in s from the start
of the event (after `delay`). An amplitude is in Hz (RF) or Hz/m (gradients), as in the file. No
value of a target (gamma, dead times, ringdown times) is used. The sources are cited as in
`seqfile.spec`: spec:N is line N of the specification, "slide N" a slide of the slide set that its
section 2.6 cites.

**Gradients.** An arbitrary gradient with time ID 0 has a sample at the centre of each cell of
the gradient raster `dt` (spec:290; slide 7): `tt = (i + 0.5) dt`, `shape_dur = n dt`. With time
ID -1 (oversampled, from 1.5.0) all the samples are kept, half a raster apart, the first and the
last at cell centres (spec:420; slides 4 and 8): `tt = (i + 1) / 2 dt`,
`shape_dur = (n + 1) / 2 dt`. With a time shape, the samples are the vertices of an extended
trapezoid (slide 6): `tt` is the shape times `dt`, and `shape_dur` is the last time. Between its
points a gradient is a straight line, from `first` at the start to `last` at the end
(`seq_utils.gradient_offsets` gives the points; D2.13: the C++ reader and pypulseq draw the same
lines, MATLAB Pulseq restores values at the raster edges).

**RF.** Without a time shape, each sample is a cell of the RF raster: `t = (i + 0.5) dwell`,
`shape_dur = n dwell`, `dwell` the RF raster (spec:290). With a time shape (D2.10 to D2.12):

- a regular shape, whose times are `(i + 0.5) d` (`model.rf_time_step`), is cells of `d`: each
  sample is held for one dwell around its time, from the start of the pulse (slide 9), and the
  pulse lasts `n d`;
- any other shape is points at its times (slide 4: they need not be on the raster edges; slide 9:
  a pulse "defined by vertices"), joined by straight lines of the complex signal, and the pulse
  ends at its last time. The straight line is the linear interpolation of the complex signal that
  the C++ reader names as its intent (`ExternalSequence.cpp` of pulseq/pulseq at `c7469123`, the
  FIXME at line 2033: "convert to complex, use linear interpolation and convert back to
  magnitude&phase"), and that MATLAB Pulseq uses for the RF power, bandwidth and simulation
  (`calcRfPower.m`, `calcRfBandwidth.m`, `simRf.m`). The C++ reader itself holds each sample for
  whole RF raster cells (nearest neighbour), and plays a regular-looking shape that does not start
  at half a step as cells from 0 (`docs/discrepancies.md`, D2.10, D2.11).

`RfEvent.dwell` is the dwell of cells, or `None` for points, and `RfEvent.signal(times)` gives the
complex signal at any times. The magnitude is the amplitude times the magnitude shape as written,
a negative sample included (a phase of pi, D2.8); the phase is 2 pi times the phase shape as
written, with no wrap (D2.9).

**ADC.** The phase modulation shape is in rad, one value for each ADC sample (D2.15, D3.8): the reader
rejects a shape of another length.
"""

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from ..seqfile.interpreters import Spec
from ..seqfile.model import SequenceData, _model, rf_time_step


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
    """An RF event (`[RF]`). The module docstring gives the samples, their times `t` and how they
    play.

    `magnitude` is the amplitude times the magnitude shape, and `phase` is 2 pi times the phase
    shape, at the times `t`. `dwell` is the dwell time of a pulse of cells (the RF raster without
    a time shape), or `None` for a pulse of points. The amplitude and the shape IDs identify the
    pulse without its offsets. `center` is `None` for a file of version 1.4, which has no center.
    `use` is one character, as in the file (`u` for a file of version 1.4).
    """

    id: int
    amplitude: float  # Hz
    mag_id: int
    phase_id: int
    time_id: int  # 0 is the default raster
    magnitude: np.ndarray  # Hz
    phase: np.ndarray  # rad
    t: np.ndarray  # s
    dwell: float | None  # s
    shape_dur: float  # s
    center: float | None  # s
    delay: float  # s
    freq_ppm: float  # ppm
    phase_ppm: float  # rad/MHz
    freq_offset: float  # Hz
    phase_offset: float  # rad
    use: str

    def signal(self, times: np.ndarray) -> np.ndarray:
        """The complex signal `magnitude * exp(1j * phase)` (Hz) at `times` (s from the start of
        the event, after `delay`), without the offsets. A pulse of cells holds each sample from
        `i dwell` to `(i + 1) dwell`; a pulse of points is a straight line of the complex signal
        between two neighbouring points. The signal is 0 outside the pulse: for cells before 0 and
        from `shape_dur` on, for points before the first time and after the last."""
        times = np.asarray(times, dtype=np.float64)
        samples = self.magnitude * np.exp(1j * self.phase)
        if self.dwell is not None:
            cell = np.floor(times / self.dwell).astype(np.int64)
            inside = (cell >= 0) & (cell < samples.size)
            return np.where(inside, samples[np.clip(cell, 0, samples.size - 1)], 0j)
        inside = (times >= self.t[0]) & (times <= self.t[-1])
        if samples.size == 1:
            return np.where(inside, samples[0], 0j)
        line = np.interp(times, self.t, samples.real) + 1j * np.interp(times, self.t, samples.imag)
        return np.where(inside, line, 0j)


@_model
class AdcEvent:
    """An ADC event (`[ADC]`).

    `phase_modulation` is the shape `phase_shape_id`, decompressed, in rad: one value for each
    ADC sample (D2.15), or `None` when `phase_shape_id` is 0.
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
    phase_modulation: np.ndarray | None  # rad


class _Shapes:
    """The decompressed samples of the shapes of `data`, each decompressed on its first use."""

    def __init__(self, data: SequenceData) -> None:
        if not isinstance(data.interpreter, Spec):
            raise TypeError(
                f"the events decode the model of the spec interpreter, not of "
                f"{data.interpreter}: use synth.decode"
            )
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
        dwell: float | None = raster
        if time_id > 0:
            times = shapes[time_id]
            step = rf_time_step(times)
            dwell = None if step is None else step * raster
        if dwell is None:
            t = shapes[time_id] * raster
            shape_dur = float(t[-1])
        else:
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
            dwell=dwell,
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
