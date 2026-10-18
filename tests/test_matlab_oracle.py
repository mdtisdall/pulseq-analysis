"""Tests of the decoding of a Pulseq file against MATLAB Pulseq, run under GNU Octave by the
command `pulseq-matlab-oracle` (`tests/oracles/matlab.py`, `tests/matlab_oracle/`).

For each file of `tests/seqfiles/valid_*.seq` and `tests/seqfiles/oracle/*.seq` that the `spec`
interpreter (`seqfile.read_seqfile`) accepts, the tests compare the package with what MATLAB Pulseq gives for the
file: the events of each block (`getBlock`) and the block durations, the gradient waveform of
each axis (`waveforms_and_times`), and the times of the ADC samples. For each such file with a
ROTATIONS section, and for one file that a test builds from `valid_1_5_1.seq`, they compare the
gradient peaks of the package with the values of MATLAB's rotated polylines. Block `b` of the
model, in play order, is block `b + 1` of MATLAB. Both read the same text in float64, so a value is
compared to a relative 1e-12 of the largest magnitude of its event or axis, and a time to an
absolute 1e-12 s. A difference fails the test, with the file, the block, the field and the two
values.

Where the package decodes a file otherwise than MATLAB, the tests do not compare that part, and
say why: `shape_dur` of an RF event of cells whose dwell is more than one RF raster, and of one of
points whose last time is not a whole number of RF rasters (D2.12: MATLAB rounds the last time up
to the RF raster), `first` of a 1.4 gradient with a time shape (U23), the polyline of an arbitrary
gradient of time ID 0 away from its samples and its ends (U21), the waveform of a file older than
1.5.1 with a rotation (MATLAB rotates in any version, `spec` from 1.5.1 only, D4.6), the
midpoints of the waveform at the boundary of a block that plays a rotation (D2.14), and for the
gradient peaks the segments that start at such a boundary where an event starts or ends at a
value that is not 0 (D2.14).

The module skips when the command is not on the PATH: only the default devShell has it.
"""

from pathlib import Path

import numpy as np
import pytest
from oracles import matlab

from pulseq_analysis import seqfile
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.seqfile import NotSupported, SeqFileError
from pulseq_analysis.seqfile.model import TIME_TOLERANCE
from pulseq_analysis.synth import seq_utils
from pulseq_analysis.synth._events import _points_from_events
from pulseq_analysis.synth.events import (
    ArbitraryGradient,
    Trapezoid,
    decode_adc,
    decode_gradients,
    decode_rf,
)
from pulseq_analysis.synth.sampling import GradientSampler, gradient_sampler
from pulseq_analysis.synth.seq_index import _dense_ids, _index_from_data

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
FILES = sorted(SEQFILES.glob("valid_*.seq")) + sorted((SEQFILES / "oracle").glob("*.seq"))
COMMAND = matlab.command_path()

pytestmark = pytest.mark.skipif(
    COMMAND is None,
    reason="pulseq-matlab-oracle is not on the PATH (only the default devShell has it)",
)

REL = 1e-12  # values: relative to the largest magnitude of the event or the axis
TIME = 1e-12  # s

# The word of MATLAB Pulseq for each letter of the RF use of the file: `rfFromLibData`
# (`Sequence.m:562-576`) has a case for e, r, i, s and p, and gives 'undefined' for any other
# letter, so also for 'o' (`getSupportedRfUse.m` has the word 'other', which `rfFromLibData`
# does not give).
RF_USE = {
    "e": "excitation",
    "r": "refocusing",
    "i": "inversion",
    "s": "saturation",
    "p": "preparation",
    "o": "undefined",
    "u": "undefined",
}

# The files that `spec` reads and MATLAB Pulseq cannot read, by name, with the reason. The test of
# such a file skips when MATLAB fails on it; for any other file a failure of MATLAB fails the test.
MATLAB_CANNOT_READ = {
    "valid_comment_in_shape.seq": (
        "MATLAB ends a section at a line that starts with `#` (read.m), so it cannot read a shape "
        "with a comment inside (D2.5)"
    ),
    "valid_label_unknown.seq": (
        "MATLAB looks up the name of a label in `mr.getSupportedLabels` (read.m:165) and fails "
        "for a name that it does not know (D2.19)"
    ),
}

# Differences listed in a failure message. The message also gives the number of all of them.
SHOWN = 20


class Case:
    """A file that the `spec` interpreter accepts, its model, its decoded events and MATLAB's
    JSON."""

    def __init__(self, name, data, dump):
        self.name = name
        self.data = data
        self.dump = dump
        self.rf = decode_rf(data)
        self.grads = decode_gradients(data)
        self.adc = decode_adc(data)
        self.index = _index_from_data(data)
        ids = _dense_ids(data, self.index)
        points = _points_from_events(
            [(k + 1, self.grads[int(i)]) for k, i in enumerate(ids.grad)],
            data.rasters.gradient,
        )
        self.sampler = GradientSampler._from_parts(self.index, points, {})
        self.rotated = _rotated_blocks(data)


def _rotated_blocks(data):
    """The play index of each block whose extension list has a `ROTATIONS` object."""
    rotation = data.extensions.type_ids.get("ROTATIONS")
    entries = {int(e["id"]): e for e in data.extensions.entries}
    rotated = set()
    for b, entry in enumerate(data.blocks["ext"].tolist()):
        while entry:
            if int(entries[entry]["type"]) == rotation:
                rotated.add(b)
            entry = int(entries[entry]["next"])
    return rotated


def _cache_dir(request):
    """The folder of the cache of the oracle (`tests/oracles/matlab.py`)."""
    cache = getattr(request.config, "cache", None)
    return (
        cache.mkdir("matlab-oracle")
        if cache is not None
        else Path(request.config.rootpath) / ".pytest_cache" / "d" / "matlab-oracle"
    )


@pytest.fixture(scope="session")
def cases(request):
    """The model of each file of `FILES` that the `spec` interpreter accepts, and the
    `SeqFileError` of each other file, by path, and MATLAB's JSON of each accepted file. MATLAB
    reads only the files that `spec` accepts: a file that it rejects can make MATLAB loop with no
    end (a cycle in an extension list, `tests/matlab_oracle/README.md`)."""
    models, rejected = {}, {}
    for path in FILES:
        try:
            models[path] = seqfile.read_seqfile(path)
        except (SeqFileError, NotSupported) as error:
            rejected[path] = error
    dumps = matlab.MatlabOracle(_cache_dir(request), COMMAND).load(list(models))
    return models, dumps, rejected, {}


def case_of(cases, path):
    """The `Case` of `path`, made on its first use. Skips when the `spec` interpreter rejects the
    file, and fails when MATLAB cannot read it."""
    models, dumps, rejected, made = cases
    if path in rejected:
        if isinstance(rejected[path], NotSupported):
            pytest.skip("the version is outside 1.4.0-1.5.x: the package does not read it")
        rules = sorted({v.rule for v in rejected[path].violations})
        if rules == ["layer1.gradient-ends"]:
            pytest.skip(
                "spec rejects the file (layer1.gradient-ends): a 1.4 file does not define "
                "the values at the ends of an arbitrary gradient of time ID 0, or of one whose "
                "time shape does not start at 0, and MATLAB guesses them from the block before"
            )
        pytest.skip(f"spec rejects the file ({', '.join(rules)})")
    name = path.relative_to(SEQFILES)
    if "error" in dumps[path] and str(name) in MATLAB_CANNOT_READ:
        pytest.skip(f"MATLAB cannot read the file: {MATLAB_CANNOT_READ[str(name)]}")
    assert "error" not in dumps[path], f"{name}: MATLAB cannot read it: {dumps[path]['error']}"
    if path not in made:
        made[path] = Case(name, models[path], dumps[path])
    return made[path]


def _array(value):
    return np.asarray([] if value is None else value, dtype=np.float64)


class Differences:
    """The differences found in one file, as lines of a failure message."""

    def __init__(self, name):
        self.name = name
        self.lines: list[str] = []

    def add(self, where, field, ours, theirs, why=""):
        self.lines.append(f"{where}, {field}: package {ours!r}, MATLAB {theirs!r}{why}")

    def values(self, where, field, ours, theirs, scale=None):
        """Values (Hz, Hz/m, rad): equal to a relative `REL` of `scale`, by default the largest
        magnitude of the two."""
        a, b = _array(ours), _array(theirs)
        if a.shape != b.shape:
            self.add(where, f"{field} (shape)", a.shape, b.shape)
            return
        if a.size == 0:
            return
        if scale is None:
            scale = max(np.abs(a).max(), np.abs(b).max())
        self._first_outside(where, field, a, b, np.abs(a - b), REL * scale)

    def times(self, where, field, ours, theirs):
        """Times (s): equal to an absolute `TIME`."""
        a, b = _array(ours), _array(theirs)
        if a.shape != b.shape:
            self.add(where, f"{field} (shape)", a.shape, b.shape)
            return
        self._first_outside(where, field, a, b, np.abs(a - b), TIME)

    def exact(self, where, field, ours, theirs):
        if ours != theirs:
            self.add(where, field, ours, theirs)

    def _first_outside(self, where, field, a, b, error, tolerance):
        outside = np.flatnonzero(error > tolerance)
        if outside.size:
            i = int(outside[0])
            at = f"[{i}]" if a.ndim else ""
            count = f" ({outside.size} of {a.size} samples outside)" if a.ndim else ""
            self.add(
                where,
                f"{field}{at}",
                float(a.flat[i]),
                float(b.flat[i]),
                f"; difference {float(error.flat[i]):.3g} > {tolerance:.3g}{count}",
            )

    def check(self):
        lines = self.lines
        shown = "\n".join(lines[:SHOWN])
        more = f"\n... and {len(lines) - SHOWN} more" if len(lines) > SHOWN else ""
        assert not lines, f"{self.name}: {len(lines)} differences with MATLAB:\n{shown}{more}"


def _compare_rf_samples(diff, where, rf, theirs):
    """Compare `magnitude`, `phase` and `t` of an `RfEvent` with MATLAB's `rf`."""
    scale = max(
        np.abs(rf.magnitude).max(initial=0.0), np.abs(_array(theirs["signal_abs"])).max(initial=0.0)
    )
    diff.values(where, "magnitude/signal_abs", rf.magnitude, theirs["signal_abs"], scale)
    # The phase modulo 2 pi, where the magnitude is not 0: a signal of 0 has no phase.
    ours, angle = rf.phase, _array(theirs["signal_angle"])
    if ours.shape != angle.shape:
        diff.add(where, "phase/signal_angle (shape)", ours.shape, angle.shape)
    else:
        nonzero = rf.magnitude != 0
        wrapped = np.abs((ours - angle + np.pi) % (2 * np.pi) - np.pi)
        wrapped = np.where(nonzero, wrapped, 0.0)
        phase_scale = max(
            np.abs(ours[nonzero]).max(initial=0.0), np.abs(angle[nonzero]).max(initial=0.0)
        )
        diff._first_outside(
            where, "phase/signal_angle (mod 2 pi)", ours, angle, wrapped, REL * phase_scale
        )
    diff.times(where, "t", rf.t, theirs["t"])


def _same_end_as_matlab(rf, raster):
    """Whether MATLAB's `shape_dur` of the event is the package's `shape_dur`. MATLAB rounds the
    last time of a time shape up to the RF raster (`Sequence.m:531`), and has the number of
    samples times the RF raster without one (`Sequence.m:535`). So the two are equal for an event
    with no time shape, for cells of one RF raster (the last time is `(n - 0.5)` rasters, which
    rounds up to `n`) and for points whose last time is a whole number of RF rasters. They differ
    for cells of a dwell of more than one raster (the pulse ends at `n d`, MATLAB's at its last
    time rounded up) and for points whose last time is not a whole number (D2.12)."""
    if rf.dwell is not None:
        return rf.dwell == raster
    last = rf.t[-1] / raster
    return abs(last - round(last)) <= TIME_TOLERANCE


def compare_rf(diff, where, rf, theirs, data):
    """Compare an `RfEvent` with MATLAB's `rf` of `getBlock`.

    MATLAB's `rf.t` is the time shape times the RF raster, and `rf.signal` the samples, so
    `magnitude`, `phase` and `t` are compared for every RF event, cells and points (the cells of a
    regular time shape are at the times of the shape). `shape_dur` is compared where MATLAB's
    rounding gives the end of the package (`_same_end_as_matlab`). The scalar fields are compared
    for every RF event."""
    _compare_rf_samples(diff, where, rf, theirs)
    if _same_end_as_matlab(rf, data.rasters.rf):
        diff.times(where, "shape_dur", rf.shape_dur, theirs["shape_dur"])
    if data.version >= (1, 5, 0):
        diff.times(where, "center", rf.center, theirs["center"])
    else:
        # A 1.4 file has no center: the package gives None, MATLAB computes one (read.m:305).
        diff.exact(where, "center (1.4)", rf.center, None)
    diff.times(where, "delay", rf.delay, theirs["delay"])
    diff.values(where, "freq_ppm/freqPPM", rf.freq_ppm, theirs["freqPPM"])
    diff.values(where, "phase_ppm/phasePPM", rf.phase_ppm, theirs["phasePPM"])
    diff.values(where, "freq_offset/freqOffset", rf.freq_offset, theirs["freqOffset"])
    diff.values(where, "phase_offset/phaseOffset", rf.phase_offset, theirs["phaseOffset"])
    diff.exact(where, f"use ({rf.use!r})", RF_USE[rf.use], theirs["use"])


def compare_gradient(diff, where, g, theirs, version):
    if isinstance(g, Trapezoid):
        diff.exact(where, "type", "trap", theirs["type"])
        if theirs["type"] != "trap":
            return
        diff.values(where, "amplitude", g.amplitude, theirs["amplitude"])
        diff.times(where, "rise_time/riseTime", g.rise_time, theirs["riseTime"])
        diff.times(where, "flat_time/flatTime", g.flat_time, theirs["flatTime"])
        diff.times(where, "fall_time/fallTime", g.fall_time, theirs["fallTime"])
        diff.times(where, "delay", g.delay, theirs["delay"])
        return
    assert isinstance(g, ArbitraryGradient)
    diff.exact(where, "type", "grad", theirs["type"])
    if theirs["type"] != "grad":
        return
    waveform = _array(theirs["waveform"])
    ends = [g.first, g.last, theirs["first"], theirs["last"]]
    scale = max(
        np.abs(g.waveform).max(initial=0.0),
        np.abs(waveform).max(initial=0.0),
        *(abs(v) for v in ends if v is not None),
    )
    diff.values(where, "waveform", g.waveform, waveform, scale)
    diff.times(where, "tt", g.tt, theirs["tt"])
    diff.times(where, "shape_dur", g.shape_dur, theirs["shape_dur"])
    # Not `first` of a 1.4 gradient with a time shape (U23): MATLAB carries it over from the
    # gradient of the block before on the axis, 0 when that block has none there
    # (read.m:339-350); the package takes the amplitude times the sample at time 0.
    if version >= (1, 5, 0) or g.time_id <= 0:
        diff.values(where, "first", g.first, theirs["first"], scale)
    diff.values(where, "last", g.last, theirs["last"], scale)
    diff.times(where, "delay", g.delay, theirs["delay"])
    diff.exact(where, "shape_id", g.shape_id, theirs["shape_id"])
    diff.exact(where, "time_id", g.time_id, theirs["time_id"])


def compare_adc(diff, where, adc, theirs):
    diff.exact(where, "num_samples/numSamples", adc.num_samples, theirs["numSamples"])
    diff.times(where, "dwell", adc.dwell, theirs["dwell"])
    diff.times(where, "delay", adc.delay, theirs["delay"])
    diff.values(where, "freq_ppm/freqPPM", adc.freq_ppm, theirs["freqPPM"])
    diff.values(where, "phase_ppm/phasePPM", adc.phase_ppm, theirs["phasePPM"])
    diff.values(where, "freq_offset/freqOffset", adc.freq_offset, theirs["freqOffset"])
    diff.values(where, "phase_offset/phaseOffset", adc.phase_offset, theirs["phaseOffset"])
    # MATLAB gives [] for no phase modulation, the package None.
    diff.values(
        where, "phase_modulation/phaseModulation", adc.phase_modulation, theirs["phaseModulation"]
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_events_of_each_block_are_those_of_matlab_pulseq(cases, path):
    case = case_of(cases, path)
    diff = Differences(case.name)
    blocks, theirs = case.data.blocks, case.dump["blocks"]
    version = case.data.version
    diff.exact("file", "number of blocks", int(blocks.size), len(theirs))
    for b, (row, block) in enumerate(zip(blocks, theirs, strict=False)):
        for column in ("rf", "gx", "gy", "gz", "adc"):
            event_id, event = int(row[column]), block[column]
            where = f"block {b + 1} (ID {int(row['id'])}) {column}"
            if (event_id == 0) != (event is None):
                diff.add(where, "event", event_id or None, event and event["type"])
            elif column == "rf" and event_id:
                compare_rf(diff, f"{where} (ID {event_id})", case.rf[event_id], event, case.data)
            elif column == "adc" and event_id:
                compare_adc(diff, f"{where} (ID {event_id})", case.adc[event_id], event)
            elif event_id:
                where = f"{where} (ID {event_id})"
                compare_gradient(diff, where, case.grads[event_id], event, version)
    diff.check()


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_block_durations_are_those_of_matlab_pulseq(cases, path):
    case = case_of(cases, path)
    diff = Differences(case.name)
    diff.times("file", "block durations", case.data.block_durations_s, case.dump["block_durations"])
    diff.check()


def _matlab_values(t, v):
    """The times of MATLAB's polyline `(t, v)` and the value at each, and the midpoint of each
    pair of consecutive points with distinct times, the value there and the index of the first
    point of the pair. Where the polyline has several points at one time (a step), the value at
    the time is the value of the first of them: the value before the step.

    A midpoint is the float of `(t0 + t1) / 2`, which can be up to half an ulp of the time from
    the exact midpoint (2.2e-16 s at 2 s). Its value is the line of MATLAB's segment at that
    float, so that a steep segment late in a file does not give a difference of the time."""
    group_start = np.ones(t.size, dtype=bool)
    group_start[1:] = t[1:] != t[:-1]
    first = np.maximum.accumulate(np.where(group_start, np.arange(t.size), 0))
    at_points = v[first]
    pairs = np.flatnonzero(t[1:] != t[:-1])
    t0, t1, v0, v1 = t[pairs], t[pairs + 1], v[pairs], v[pairs + 1]
    mid_t = (t0 + t1) / 2
    mid_v = v0 + (mid_t - t0) / (t1 - t0) * (v1 - v0)
    return at_points, mid_t, mid_v, pairs


def _restored(case, axis, t):
    """True for each time of `t` (sorted) that is inside an arbitrary gradient of time ID 0 on
    `axis`, more than `TIME` from its two ends, and not at one of its sample centres.

    MATLAB draws such a gradient with `mr.restoreAdditionalShapeSamples` (`Sequence.m:2018`): it
    guesses values at the raster edges from the samples. Layer 1 does not guess, and the package
    keeps the straight lines between the sample centres (U21 of
    `docs/plans/own-parser-tasks.md`). So MATLAB's points there, and the midpoints next to them,
    are not compared. Its points at the sample centres and at the two ends are."""
    restored = np.zeros(t.size, dtype=bool)
    dt = case.data.rasters.gradient
    for p in np.flatnonzero(case.data.blocks[axis]):
        g = case.grads[int(case.data.blocks[axis][p])]
        if not (isinstance(g, ArbitraryGradient) and g.time_id == 0):
            continue
        start = case.index.start_s[p] + g.delay
        lo = int(np.searchsorted(t, start + TIME, side="right"))
        hi = int(np.searchsorted(t, start + g.shape_dur - TIME, side="left"))
        x = (t[lo:hi] - start) / dt - 0.5  # a whole number at a sample centre
        restored[lo:hi] |= np.abs(x - np.round(x)) > 1e-6
    return restored


def _at_a_boundary(case, blocks, t):
    """True for each time of `t` that is within `TIME` of the start or the end of a block of
    `blocks` (play indices).

    MATLAB rotates the points of each block's own events (`mr.rotate3D`, Sequence.m:1988-1999)
    and joins them across blocks (D2.14). The measurements of `spec` take the gradients of a
    block that plays a rotation from `gradients_at` up to the end of the block (`_played`), and
    draw their own gap to the next block. So a segment of MATLAB with an end at the boundary of
    such a block is not compared at its midpoint. MATLAB's points there are."""
    starts = case.index.start_s[blocks]
    edges = np.concatenate([starts, starts + case.index.duration_s[blocks]])
    return np.abs(t[:, None] - edges[None, :]).min(axis=1, initial=np.inf) <= TIME


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_gradient_waveform_of_each_axis_is_that_of_matlab_pulseq(cases, path):
    """The sampler of the package gives MATLAB's waveform at each point of MATLAB's polyline and
    at the midpoint of each of its segments. For a file with a rotated block, the sampler is that
    of `load(path)`, whose decoding rotates the gradients as MATLAB does (`spec` from 1.5.1, P20),
    and the midpoints of a segment with an end at the boundary of a block that plays a rotation
    are left out (`_at_a_boundary`)."""
    case = case_of(cases, path)
    sampler, turned = case.sampler, np.empty(0, dtype=np.int64)
    if case.rotated:
        if case.data.version < (1, 5, 1):
            pytest.skip(
                f"block {min(case.rotated) + 1} has a rotation: MATLAB rotates its gradients in "
                "any version (Sequence.m:1989-2000), and spec reads ROTATIONS from 1.5.1 only "
                "(D4.6)"
            )
        snap = load(path)
        sampler = gradient_sampler(snap)
        # The blocks that play a rotation: a quaternion whose vector part is not 0.
        blocks, quaternions = snap.decoding.rotations()
        turned = blocks[np.any(quaternions[:, 1:] != 0, axis=1)]
    diff = Differences(case.name)
    for axis in ("gx", "gy", "gz"):
        wave = case.dump["waveforms"][axis]
        if wave is None:
            used = int(np.count_nonzero(case.data.blocks[axis]))
            diff.exact(axis, "blocks with an event (MATLAB has no point)", used, 0)
            continue
        t, v = _array(wave["t"]), _array(wave["v"])
        if np.any(np.diff(t) < 0):
            diff.add(axis, "times of the polyline in increasing order", True, False)
            continue
        scale = np.abs(v).max()
        at_points, mid_t, mid_v, pairs = _matlab_values(t, v)
        restored = _restored(case, axis, t)
        kept_mid = ~restored[pairs] & ~restored[pairs + 1]
        boundary = _at_a_boundary(case, turned, t)
        kept_mid &= ~boundary[pairs] & ~boundary[pairs + 1]
        for label, times, expected in (
            ("point", t[~restored], at_points[~restored]),
            ("midpoint", mid_t[kept_mid], mid_v[kept_mid]),
        ):
            # The sampler names the axis of the column "gx" "x".
            ours = sampler.sample(axis.removeprefix("g"), times)
            error = np.abs(ours - expected)
            outside = np.flatnonzero(error > REL * scale)
            for i in outside[:3]:
                # The play index of the block of the time; a time at a block boundary is in the
                # later block.
                b = int(np.searchsorted(case.index.start_s, times[i], side="right")) - 1
                diff.add(
                    f"{axis} at the {label} t = {float(times[i])!r} s (block {b + 1})",
                    "value",
                    float(ours[i]),
                    float(expected[i]),
                    f"; difference {error[i]:.3g} > {REL * scale:.3g}"
                    f" ({outside.size} of {times.size} {label}s outside)",
                )
    diff.check()


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_adc_sample_times_are_those_of_matlab_pulseq(cases, path):
    case = case_of(cases, path)
    diff = Differences(case.name)
    index = case.index
    times = [
        index.start_s[b] + adc.delay + (np.arange(adc.num_samples) + 0.5) * adc.dwell
        for b, adc in ((b, case.adc[int(i)]) for b, i in enumerate(case.data.blocks["adc"]) if i)
    ]
    ours = np.concatenate(times) if times else np.empty(0)
    diff.times("file", "ADC sample times / t_adc", ours, case.dump["t_adc"])
    diff.check()


# The files with a ROTATIONS section, for the rotated gradients of the interpreters.
ROTATION_FILES = [path for path in FILES if b"extension ROTATIONS" in path.read_bytes()]

# A plugin interpreter can hold the gradient amplitudes in float32 (`cpp-siemens`, P6), and
# MATLAB holds them in float64.
FLOAT32_REL = 1e-6


@pytest.mark.parametrize("path", ROTATION_FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_rotated_gradients_of_spec_are_those_of_matlab_pulseq(cases, path):
    """`spec` (from 1.5.1) rotates each block's gradients by the model's quaternion with the
    package's `decoding.rotate`, and MATLAB's `waveforms_and_times` rotates them with
    `mr.rotate3D` (Sequence.m:1988-1999): `compare_rotated_gradients`, to a relative `REL`, as
    both hold the amplitudes in float64. MATLAB rotates in any version and `spec` from 1.5.1 only
    (P20, rule 2), so a file older than 1.5.1 is left out."""
    from pulseq_analysis.seqfile import read_seqfile

    case = case_of(cases, path)
    try:
        data = read_seqfile(path, "spec")
    except SeqFileError as error:
        pytest.skip(f"spec rejects the file ({', '.join(sorted(error.codes))})")
    if data.version < (1, 5, 1):
        pytest.skip("spec reads ROTATIONS from 1.5.1 only")
    compare_rotated_gradients(case, data, REL)


def compare_rotated_gradients(case, data, rel):
    """The rotated gradients of the decoding of `data` (`synth.decode`) agree with MATLAB's at
    the midpoint of each segment of MATLAB's polyline, on each axis, where MATLAB does not guess
    the edges of an arbitrary gradient (U21), and on a segment with no end at a block boundary:
    there MATLAB can join the last point of one block to the first sample of the next, and each
    interpreter gives each block alone (D2.14). They agree to a relative `rel` of the largest
    magnitude of MATLAB's axis: `REL` for `spec`, which holds the amplitudes in float64 as MATLAB
    does, and `FLOAT32_REL` for a plugin interpreter that holds them in float32. The unrotated
    gradients do not agree where a block plays a rotation. The tests of a plugin interpreter call
    it too."""
    from pulseq_analysis import synth

    decoding = synth.decode(data)
    # The decoding applies the rotations of the file, to each block with a rotation (0 blocks
    # for valid_1_5_1_rotation_not_played.seq). The setting is checked too: a setting that leaves
    # the rotations unapplied has 0 blocks rotated, which is also `blocks` for such a file.
    record = decoding.rotation_record
    assert record.setting == "apply"
    assert record.rotated == record.blocks
    starts = np.concatenate([[0.0], np.cumsum(data.block_durations_s)])
    diff = Differences(case.name)
    unrotated_differs = False
    for column, axis in enumerate(("gx", "gy", "gz")):
        wave = case.dump["waveforms"][axis]
        if wave is None:
            continue
        t, v = _array(wave["t"]), _array(wave["v"])
        _, mid_t, mid_v, pairs = _matlab_values(t, v)
        restored = _restored(case, axis, t)
        kept = ~restored[pairs] & ~restored[pairs + 1]
        for end in (t[pairs], t[pairs + 1]):
            nearest = np.abs(end[:, None] - starts[None, :]).min(axis=1)
            kept &= nearest > TIME
        mid_t, mid_v = mid_t[kept], mid_v[kept]
        block = np.searchsorted(starts, mid_t, side="right") - 1
        inside = block < data.blocks.size
        mid_t, mid_v, block = mid_t[inside], mid_v[inside], block[inside]
        time_us = (mid_t - starts[block]) * 1e6
        ours = decoding.gradients_at(block, time_us)[:, column]
        scale = np.abs(v).max()
        tolerance = rel * scale
        error = np.abs(ours - mid_v)
        diff._first_outside(axis, "rotated value at the midpoints", ours, mid_v, error, tolerance)
        logical = decoding.gradients_at(block, time_us, rotated=False)[:, column]
        unrotated_differs |= bool(np.any(np.abs(logical - mid_v) > tolerance))
    diff.check()
    if decoding.rotation_record.not_identity:
        assert unrotated_differs, "the reader's unrotated gradients agree with MATLAB's"


# The changes of `valid_1_5_1.seq` that `_rotated_two_axes` makes: the rows of the file and
# their replacements.
TWO_AXES_ROWS = {
    "\n5  10  0  5  0  0  0  3\n": "\n5  10  0  5  7  0  0  3\n",
    "\n9  10  0  0  0  0  0  6\n": "\n9  10  0  5  7  0  0  6\n",
    "\n1 1000000 100 200 100 100\n": "\n1 1000000 100 200 100 100\n7 50000 20 20 20 20\n",
    "\n6 6 1 3\n7 7 1 0\n": "\n6 6 1 8\n7 7 1 0\n8 5 2 0\n",
    "\n1 0.92388 0 0 0.382683\n": "\n1 0.92388 0 0 0.382683\n2 0.92388 0 0.382683 0\n",
}


def _rotated_two_axes(directory):
    """`valid_1_5_1.seq` with gradient events on two axes in its two rotated blocks, written in
    `directory` (`TWO_AXES_ROWS`). Block 5 plays gx 5 and a new trapezoid 7 on gy, with its
    rotation of 45 degrees about z. Block 9 (of the same duration, with a rotation and no
    gradient in `valid_1_5_1.seq`) plays the same two events with a new rotation of 45 degrees
    about y: the same scalar part of the quaternion, about another axis. The trapezoid (50 000
    Hz/m, a delay, rise, flat and fall time of 20 us each) has its corners at 20, 40, 60 and 80
    us, and gx 5 at 0, 10, 30, 60 and 100 us, so each rotated axis has the times of both. No file
    of `tests/seqfiles` has a rotated block with events on two axes, or two blocks with the same
    events and two rotations of one angle. The amplitude keeps the slew of the rotated gradients
    within the limit that MATLAB checks when `mr.rotate3D` adds them (`mr.addGradients`): with
    200 000 Hz/m, MATLAB cannot read the file (a slew rate violation of 122 %)."""
    text = (SEQFILES / "valid_1_5_1.seq").read_text()
    for old, new in TWO_AXES_ROWS.items():
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path = directory / "rotated_two_axes.seq"
    path.write_text(text)
    return path


def _steps_at(case, edges):
    """The times of `edges` (s) where a gradient event of MATLAB's `getBlock` starts or ends at a
    value that is not 0: `first` and `last` of an arbitrary gradient, and the amplitude of a
    trapezoid with a rise or a fall time of 0. Only at such a time can the gradient of one block
    end at one value and that of the next start at another."""
    starts = case.index.start_s
    steps = set()
    for edge in edges:
        for b, block in enumerate(case.dump["blocks"]):
            for axis in ("gx", "gy", "gz"):
                g = block[axis]
                if g is None:
                    continue
                begin = starts[b] + g["delay"]
                if g["type"] == "trap":
                    end = begin + g["riseTime"] + g["flatTime"] + g["fallTime"]
                    first = g["amplitude"] if g["riseTime"] == 0 else 0.0
                    last = g["amplitude"] if g["fallTime"] == 0 else 0.0
                else:
                    end, first, last = begin + g["shape_dur"], g["first"], g["last"]
                if (abs(begin - edge) <= TIME and first != 0) or (
                    abs(end - edge) <= TIME and last != 0
                ):
                    steps.add(float(edge))
    return np.array(sorted(steps))


def _left_out(case, turned):
    """The open intervals of time (s) that the test of the gradient peaks leaves out, on every
    axis: each segment of MATLAB's polyline that starts at the start or the end of a block of
    `turned` (play indices) where a gradient event starts or ends at a value that is not 0
    (`_steps_at`, D2.14), and each segment with a point that MATLAB restores (`_restored`, U21).

    Where the gradient of one block ends and that of the next block starts at one time, MATLAB
    keeps the last point of the earlier block and leaves out the points of the later block at
    that time (`waveforms_and_times`, Sequence.m:2143). So its segment into the later block
    starts at the value of the earlier block, and the measurements draw a step there, with its
    slew, and the segment of the later block from its own first value. A segment that ends at
    such a boundary is the same in both. So is a segment that starts at a boundary where no event
    starts or ends at a value that is not 0 (both values are 0 there), and a segment at a boundary
    of a block that plays no rotation, where the test of the waveform compares the midpoints."""
    starts, durations = case.index.start_s[turned], case.index.duration_s[turned]
    steps = _steps_at(case, np.concatenate([starts, starts + durations]))
    intervals = []
    for axis in ("gx", "gy", "gz"):
        wave = case.dump["waveforms"][axis]
        if wave is None:
            continue
        t = _array(wave["t"])
        restored = _restored(case, axis, t)
        at_step = np.abs(t[:, None] - steps[None, :]).min(axis=1, initial=np.inf) <= TIME
        for i in np.flatnonzero(t[1:] > t[:-1]).tolist():
            if restored[i] or restored[i + 1] or at_step[i]:
                intervals.append((float(t[i]), float(t[i + 1])))
    return sorted(intervals)


def _windows(lo, hi, left_out):
    """The closed intervals of `[lo, hi]` that are outside each open interval of `left_out`
    (sorted by their starts), each of a length above 0."""
    windows, start = [], lo
    for a, b in left_out:
        if b <= start or a >= hi:
            continue
        if a > start:
            windows.append((float(start), float(a)))
        start = max(start, b)
    if start < hi:
        windows.append((float(start), float(hi)))
    return windows


def _sides(t, v, q):
    """The values of MATLAB's polyline `(t, v)` just before and just after each time of `q`: 0
    before its first point and after its last point, and at a time of several points the value
    of the first of them before it and of the last of them after it."""
    if t.size < 2:
        return np.zeros(q.size), np.zeros(q.size)
    i = np.clip(np.searchsorted(t, q, side="left"), 1, t.size - 1)
    j = np.clip(np.searchsorted(t, q, side="right") - 1, 0, t.size - 2)

    def line(k0, k1):
        span = np.where(t[k1] > t[k0], t[k1] - t[k0], 1.0)
        return v[k0] + (v[k1] - v[k0]) * (q - t[k0]) / span

    before = np.where(t[i] == q, v[i], line(i - 1, i))
    after = np.where(t[j] == q, v[j], line(j, j + 1))
    return (
        np.where((q > t[0]) & (q <= t[-1]), before, 0.0),
        np.where((q >= t[0]) & (q < t[-1]), after, 0.0),
    )


class _Expected:
    """The values that `gradient_peaks` gives for the window `[lo, hi]`, from MATLAB's polylines
    `waves` (the axis letter to `(t, v)`, or `(None, None)` for an axis with no point), by the
    rules of `analyses/grad_peaks.py`. Each value is a list of candidates `(time, value)`, of
    which the largest is the value:

    - the peak of an axis: the ends of each segment of a length above 0, cut by the window, with
      the value of the line at an edge that cuts it;
    - the slew: the slope of each cut segment of `seq_utils.TIME_TOLERANCE` or more, at its start,
      and the step from 0 at the first point and to 0 at the last point of the axis, `|value| /
      dt`, when its time `t` has `lo <= t < hi` and is more than `seq_utils.TIME_TOLERANCE`
      before the end of the sequence `end_s`;
    - the vector peak: `sqrt(gx² + gy² + gz²)` at `lo`, at `hi` and at the time of each point of
      the three axes in the window, just before and just after it (`_sides`), but not before
      `lo` nor after `hi`.

    The RMS of an axis is the square root of the integral of the square of the cut segments,
    divided by `hi - lo`."""

    def __init__(self, waves, dt, end_s, lo, hi):
        tolerance = seq_utils.TIME_TOLERANCE
        self.peak, self.slew, self.rms = {}, {}, {}
        times = [np.array([lo, hi])]
        for axis, (t, v) in waves.items():
            self.peak[axis], self.slew[axis], self.rms[axis] = [], [], 0.0
            if t is None:
                continue
            t0, t1, v0, v1 = t[:-1], t[1:], v[:-1], v[1:]
            a, b = np.maximum(t0, lo), np.minimum(t1, hi)
            cut = b > a
            t0, t1, v0, v1, a, b = (x[cut] for x in (t0, t1, v0, v1, a, b))
            span = t1 - t0
            va = np.where(a == t0, v0, v0 + (v1 - v0) * (a - t0) / span)
            vb = np.where(b == t1, v1, v0 + (v1 - v0) * (b - t0) / span)
            self.peak[axis] = [*zip(a, np.abs(va), strict=True), *zip(b, np.abs(vb), strict=True)]
            long = b - a >= tolerance
            self.slew[axis] = list(zip(a[long], (np.abs(v1 - v0) / span)[long], strict=True))
            for at, value in ((t[0], v[0]), (t[-1], v[-1])):
                if value != 0 and lo <= at < min(hi, end_s - tolerance):
                    self.slew[axis].append((at, abs(value) / dt))
            integral = np.sum((b - a) * (va * va + va * vb + vb * vb)) / 3.0
            self.rms[axis] = float(np.sqrt(integral / (hi - lo)))
            times.append(t[(t >= lo) & (t <= hi)])
        q = np.unique(np.concatenate(times))
        before, after = np.zeros(q.size), np.zeros(q.size)
        for t, v in waves.values():
            if t is not None:
                axis_before, axis_after = _sides(t, v, q)
                before += axis_before**2
                after += axis_after**2
        before[q == lo] = 0.0
        after[q == hi] = 0.0
        self.vector = [*zip(q, np.sqrt(before), strict=True), *zip(q, np.sqrt(after), strict=True)]


def _compare_largest(diff, where, field, value, time, candidates, tolerance):
    """`value` is the largest value of `candidates` (`_Expected`) to `tolerance`, and when that
    is above `tolerance`, `time` is the time (to `TIME`) of a candidate with that value: of the
    values that are equal but for MATLAB's rounding, the package can give any."""
    largest = float(max((c for _, c in candidates), default=0.0))
    if abs(value - largest) > tolerance:
        diff.add(where, field, value, largest, f"; difference {abs(value - largest):.3g}")
    elif largest > tolerance and not any(
        abs(at - time) <= TIME and abs(c - largest) <= tolerance for at, c in candidates
    ):
        times = sorted({float(at) for at, c in candidates if abs(c - largest) <= tolerance})
        diff.add(where, f"{field} (time)", time, times)


def compare_gradient_peaks(case, path):
    """`gradient_peaks` of `load(path)` (`spec`) has the values of MATLAB's polylines
    (`_Expected`) in each window: the peak, the slew and the RMS of each axis and the vector
    peak, each with a time of MATLAB's that has the value. The windows are the whole file and
    each block, without the intervals of `_left_out`; a window of the whole file without one is
    `range_s=None`. `block_gradient_values` has the vector peak of each block that has no
    interval left out and no neighbour of duration 0, which is that of the window of the block.

    A value is compared to a relative `REL` of the largest value of MATLAB's axis, a slew to a
    relative `REL` of the largest slew of MATLAB's axis (both of the three axes for the vector
    peak and for an axis where MATLAB has no point), and a time to `TIME`."""
    snap = load(path)
    blocks, quaternions = snap.decoding.rotations()
    turned = blocks[np.any(quaternions[:, 1:] != 0, axis=1)]
    left_out = _left_out(case, turned)
    dt = case.data.rasters.gradient
    starts, durations = case.index.start_s, case.index.duration_s
    end_s = float(starts[-1] + durations[-1])
    waves = {}
    for axis in ("gx", "gy", "gz"):
        wave = case.dump["waveforms"][axis]
        waves[axis[1]] = (None, None) if wave is None else (_array(wave["t"]), _array(wave["v"]))
    scale = {a: np.abs(v).max() for a, (_, v) in waves.items() if v is not None}
    whole_file = _Expected(waves, dt, end_s, 0.0, end_s)
    slew_scale = {a: max((c for _, c in whole_file.slew[a]), default=0.0) for a in scale}
    vector_scale, largest_slew = max(scale.values()), max(slew_scale.values())
    for axis in waves:
        scale.setdefault(axis, vector_scale)
        slew_scale.setdefault(axis, largest_slew)

    whole = _windows(0.0, end_s, left_out)
    windows = [(None, None)] if whole == [(0.0, end_s)] else [(None, w) for w in whole]
    for b in range(starts.size):
        windows += [(b, w) for w in _windows(starts[b], starts[b] + durations[b], left_out)]
    diff = Differences(case.name)
    for b, window in windows:
        lo, hi = (0.0, end_s) if window is None else window
        where = f"window ({lo!r}, {hi!r})" + ("" if b is None else f" in block {b + 1}")
        peaks = gradient_peaks(snap, range_s=window)
        expected = _Expected(waves, dt, end_s, lo, hi)
        for axis, ours in peaks.axes.items():
            at = f"{where} {axis}"
            tolerance = REL * scale[axis]
            peak, time = ours.peak_hz_per_m, ours.peak_time_s
            _compare_largest(diff, at, "peak", peak, time, expected.peak[axis], tolerance)
            slew, time = ours.max_slew_hz_per_m_per_s, ours.slew_time_s
            slew_tolerance = REL * slew_scale[axis]
            _compare_largest(diff, at, "slew", slew, time, expected.slew[axis], slew_tolerance)
            if abs(ours.rms_hz_per_m - expected.rms[axis]) > tolerance:
                diff.add(at, "rms", ours.rms_hz_per_m, expected.rms[axis])
        peak, time = peaks.vector_peak_hz_per_m, peaks.vector_peak_time_s
        tolerance = REL * vector_scale
        _compare_largest(diff, where, "vector peak", peak, time, expected.vector, tolerance)
    values = block_gradient_values(snap)
    for b in range(starts.size):
        lo, hi = starts[b], starts[b] + durations[b]
        next_to_0 = np.any(durations[max(b - 1, 0) : b + 2] == 0)
        if next_to_0 or _windows(lo, hi, left_out) != [(lo, hi)]:
            continue
        peak, time = float(values.vector_peak_hz_per_m[b]), float(values.vector_peak_time_s[b])
        expected = _Expected(waves, dt, end_s, lo, hi).vector
        where = f"block {b + 1}, block_gradient_values"
        _compare_largest(diff, where, "vector peak", peak, time, expected, REL * vector_scale)
    diff.check()


# The files of the test of the gradient peaks: those with a ROTATIONS section, and the one of
# `_rotated_two_axes` (None).
PEAK_FILES = [*ROTATION_FILES, None]


@pytest.mark.parametrize(
    "path",
    PEAK_FILES,
    ids=lambda p: "built/rotated_two_axes.seq" if p is None else str(p.relative_to(SEQFILES)),
)
def test_the_gradient_peaks_of_a_rotated_file_are_those_of_matlab_pulseq(
    cases, request, tmp_path, path
):
    """The gradient peaks of each file with a ROTATIONS section from 1.5.1, and of a file with
    events on two axes in each of its two rotated blocks, of two rotations of one angle
    (`_rotated_two_axes`, which MATLAB reads in a run of its own), are those of MATLAB's rotated
    polylines (`compare_gradient_peaks`). A file older than 1.5.1 is left out: MATLAB rotates in
    any version, and `spec` reads ROTATIONS from 1.5.1 only (D4.6)."""
    if path is None:
        path = _rotated_two_axes(tmp_path)
        dump = matlab.MatlabOracle(_cache_dir(request), COMMAND).load([path])[path]
        assert "error" not in dump, f"{path.name}: MATLAB cannot read it: {dump['error']}"
        case = Case(path.name, seqfile.read_seqfile(path), dump)
    else:
        case = case_of(cases, path)
    if case.data.version < (1, 5, 1):
        pytest.skip("spec reads ROTATIONS from 1.5.1 only (D4.6)")
    compare_gradient_peaks(case, path)
