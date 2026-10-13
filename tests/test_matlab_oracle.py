"""Tests of the decoding of a Pulseq file against MATLAB Pulseq, run under GNU Octave by the
command `pulseq-matlab-oracle` (`tests/oracles/matlab.py`, `tests/matlab_oracle/`).

For each file of `tests/seqfiles/valid_*.seq` and `tests/seqfiles/oracle/*.seq` that
`read_strict` accepts, the tests compare the package with what MATLAB Pulseq gives for the
file: the events of each block (`getBlock`) and the block durations, the gradient waveform of
each axis (`waveforms_and_times`), and the times of the ADC samples. Block `b` of the model, in
play order, is block `b + 1` of MATLAB. Both read the same text in float64, so a value is
compared to a relative 1e-12 of the largest magnitude of its event or axis, and a time to an
absolute 1e-12 s. A difference fails the test, with the file, the block, the field and the two
values.

Where the package decodes a file otherwise than MATLAB by a decision of
`docs/plans/own-parser-tasks.md` section 12, the tests do not compare that part, and say why:
`shape_dur` of an RF event with a regular time shape and the samples of one with another time
shape (U25, U26), `first` of a 1.4 gradient with a time
shape (U23), the polyline of an arbitrary gradient of time ID 0 away from its samples and its
ends (U21), and the waveform of a file in which a block plays a rotation (U22).

The module skips when the command is not on the PATH: only the default devShell has it.
"""

from pathlib import Path

import numpy as np
import pytest
from oracles import matlab

from pulseq_analysis.seqfile.model import _rf_time_step
from pulseq_analysis.seqfile.reader import NotSupported, SeqFileError, read_strict
from pulseq_analysis.synth._events import _points_from_events
from pulseq_analysis.synth.events import (
    ArbitraryGradient,
    Trapezoid,
    decode_adc,
    decode_gradients,
    decode_rf,
)
from pulseq_analysis.synth.sampling import GradientSampler
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

# Differences listed in a failure message. The message also gives the number of all of them.
SHOWN = 20


class Case:
    """A file that `read_strict` accepts, its model, its decoded events and MATLAB's JSON."""

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


@pytest.fixture(scope="session")
def cases(request):
    """The model of each file of `FILES` that `read_strict` accepts, and the `SeqFileError` of
    each other file, by path, and MATLAB's JSON of each accepted file. MATLAB reads only the
    files that `read_strict` accepts: a file that it rejects can make MATLAB loop with no end (a
    cycle in an extension list, `tests/matlab_oracle/README.md`)."""
    models, rejected = {}, {}
    for path in FILES:
        try:
            models[path] = read_strict(path)
        except (SeqFileError, NotSupported) as error:
            rejected[path] = error
    cache = getattr(request.config, "cache", None)
    cache_dir = (
        cache.mkdir("matlab-oracle")
        if cache is not None
        else Path(request.config.rootpath) / ".pytest_cache" / "d" / "matlab-oracle"
    )
    dumps = matlab.MatlabOracle(cache_dir, COMMAND).load(list(models))
    return models, dumps, rejected, {}


def case_of(cases, path):
    """The `Case` of `path`, made on its first use. Skips when `read_strict` rejects the file,
    and fails when MATLAB cannot read it."""
    models, dumps, rejected, made = cases
    if path in rejected:
        if isinstance(rejected[path], NotSupported):
            pytest.skip("the version is outside 1.4.0-1.5.x: the package does not read it")
        rules = sorted({v.rule for v in rejected[path].violations})
        if rules == ["layer1.gradient-ends"]:
            pytest.skip(
                "read_strict rejects the file (layer1.gradient-ends): a 1.4 file does not define "
                "the values at the ends of an arbitrary gradient of time ID 0, or of one whose "
                "time shape does not start at 0, and MATLAB guesses them from the block before"
            )
        pytest.skip(f"read_strict rejects the file ({', '.join(rules)})")
    name = path.relative_to(SEQFILES)
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


def compare_rf(diff, where, rf, theirs, data):
    """Compare an `RfEvent` with MATLAB's `rf` of `getBlock`.

    The package decodes an RF event with a time shape as the scanner's reader plays it (U24 to
    U26 of `docs/plans/own-parser-tasks.md`). With a time shape that the reader takes as regular
    (`model._rf_time_step`), it plays the samples at the centres of cells of the step from the
    delay; the parser checks that the stored times are those centres (`shape.rf-time-grid`), so
    the samples and `t` are compared, but not `shape_dur`: MATLAB rounds the last time up to the
    RF raster (`Sequence.m:531`), the reader gives the number of samples times the step. With
    any other time shape, the reader resamples the pulse to the RF raster and MATLAB keeps the
    stored points, so `magnitude`, `phase`, `t` and `shape_dur` are not compared. The scalar
    fields are compared for every RF event."""
    regular = rf.time_id > 0 and _rf_time_step(data.shapes[rf.time_id]) is not None
    if rf.time_id == 0 or regular:
        _compare_rf_samples(diff, where, rf, theirs)
    if rf.time_id == 0:
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


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_gradient_waveform_of_each_axis_is_that_of_matlab_pulseq(cases, path):
    case = case_of(cases, path)
    if case.rotated:
        pytest.skip(
            f"block {min(case.rotated) + 1} plays a rotation: MATLAB rotates its gradients "
            "(Sequence.m:1989-2000), and strict does not (U18, U22); "
            "test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq compares "
            "the rotated gradients of cpp-siemens"
        )
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
        for label, times, expected in (
            ("point", t[~restored], at_points[~restored]),
            ("midpoint", mid_t[kept_mid], mid_v[kept_mid]),
        ):
            ours = case.sampler.sample(axis, times)
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


# The files with a ROTATIONS section, for the rotated gradients of `cpp-siemens`.
ROTATION_FILES = [path for path in FILES if b"extension ROTATIONS" in path.read_bytes()]

# `cpp-siemens` holds the gradient amplitudes in float32 (P6), and MATLAB in float64.
FLOAT32_REL = 1e-6


@pytest.mark.parametrize("path", ROTATION_FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_the_rotated_gradients_of_cpp_siemens_are_those_of_matlab_pulseq(cases, path):
    """`CppSiemens(rotation="apply")` rotates each block's gradients by the reader's quaternion
    with the reader's `rotate_vec3_by_quat`, and MATLAB's `waveforms_and_times` rotates them with
    `mr.rotate3D` (Sequence.m:1988-1999). They agree at the midpoint of each segment of MATLAB's
    polyline, on each axis, where MATLAB does not guess the edges of an arbitrary gradient (U21),
    and on a segment with no end at a block boundary: there MATLAB can join the last point of one
    block to the first sample of the next, and the reader gives each block alone (D42). The
    reader's own gradients, not rotated, do not agree where a block plays a rotation."""
    pytest.importorskip("pulseq_cpp_siemens")
    from pulseq_analysis import synth
    from pulseq_analysis.seqfile import CppSiemens, read_seqfile

    case = case_of(cases, path)
    data = read_seqfile(path, CppSiemens(rotation="apply"))
    decoding = synth.decode(data)
    # valid_1_5_1_rotation_not_played.seq has a rotation that no block plays: 0 blocks rotated.
    assert decoding.rotation_record.rotated == decoding.rotation_record.blocks
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
        tolerance = FLOAT32_REL * scale
        error = np.abs(ours - mid_v)
        diff._first_outside(axis, "rotated value at the midpoints", ours, mid_v, error, tolerance)
        logical = decoding.gradients_at(block, time_us, rotated=False)[:, column]
        unrotated_differs |= bool(np.any(np.abs(logical - mid_v) > tolerance))
    diff.check()
    if decoding.rotation_record.not_identity:
        assert unrotated_differs, "the reader's unrotated gradients agree with MATLAB's"
