"""Tests of the decoded events and the gradient waveform of the `spec` interpreter against the C++
oracle: the reader `ExternalSequence` of pulseq/pulseq (the reader of the Pulseq interpreter on the
scanner), in the modes `--dump` and `--sample` of `pulseq-cpp-oracle` (`tests/oracles/cpp.py`;
`tests/cpp_oracle/README.md` has the fields and their units).

Each test compares each file of `tests/seqfiles/` that `spec` (`seqfile.read_seqfile`, decoded by
`synth.events`) and the oracle accept, except the files of `ORACLE_KNOWN_WRONG`, those that the two
read as different sequences (`READ_DIFFERENTLY`) and those with an arbitrary gradient on a gradient
raster other than 10 us (`decodeBlock` fails on them). The event values of the reader are `float`
(32 bits), so two values agree when they differ by at most `REL` times the largest magnitude of the
event. An integer field agrees when it is equal.

A difference means that the reader of the scanner holds another value than the package, for a
file that the parser accepts: for an event, the scanner plays something else than the package
reads in the file. A test fails with each difference, with the rule of the reader for the field
when `READER_RULES` has it. It does not skip a difference, except where `spec` differs from the
reader by design: each such field is compared after the change that the design makes (or not
compared), and is recorded as a property of the test with the entry of `docs/discrepancies.md`
that explains it. The fields are:

- an RF pulse of points (an RF time shape that is not regular, D2.11; the reader resamples it to
  cells): the duration, the dwell and the samples are not compared;
- an RF magnitude below 0 and an RF phase outside [0, 2 pi - 1e-4], which `spec` plays as written
  (D2.8, D2.9) and the reader clamps: compared after the reader's clamp;
- the samples of an oversampled gradient (time ID -1), all of them in `spec` and every second one
  in the reader (D6.1): compared at the even indices;
- the ROTATIONS and RF_SHIMS objects in a file before 1.5.1, which `spec` does not read and the
  reader does (D4.6): not compared;
- the soft delay offset with a fraction, which the reader misreads (D2.16);
- the signature of a file with CRLF line ends (spec:223).

The test of the gradient waveform samples at the centres of the raster cells and at the ends of
the events, where the lines between all the samples of an oversampled gradient (`spec`) and those
between its even samples (the reader) agree.

The module skips when the binary is not on the PATH, as outside the Nix devShell.
"""

from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest
from oracles import cpp
from test_cpp_oracle import (
    ORACLE,
    ORACLE_KNOWN_WRONG,
    SEQFILES,
    SKIPPED_ARBITRARY_GRADIENT_RASTER,
    arbitrary_gradient_off_the_10_us_raster,
)

from pulseq_analysis.seqfile import NotSupported, SeqFileError, read_seqfile
from pulseq_analysis.seqfile.model import SequenceData
from pulseq_analysis.synth import _events, events, sampling, seq_index

pytestmark = [
    pytest.mark.cpp_oracle,
    pytest.mark.skipif(ORACLE is None, reason="pulseq-cpp-oracle is not on the PATH"),
]

# The relative tolerance of a value: the reader holds its values as `float` (32 bits).
REL = 1e-6

_AXES = ("gx", "gy", "gz")

# The reasons of the planned skips (docs/plans/own-parser-tasks.md, section 4.7). Each skip is by
# a rule on the model, never by the name of a file.
SKIPPED_BLOCK_BOUNDARY = (
    "a time at a block boundary: gradientsAt works inside one block and does not join blocks"
)

# The files that both interpreters read, as different sequences: the corpus leaves them out. Each
# value is the entry of `docs/discrepancies.md` and what differs. None today: `spec` rejects a
# section that appears twice (D3.3), which the reader reads as its last copy.
READ_DIFFERENTLY: dict[str, str] = {}

# The labels that the reader knows (`decodeLabel`, ExternalSequence.cpp:2355-2404): a counter
# or a flag. It keeps no other label in a block (1880-1899): PMC and TRID are ignored, and another
# name is unknown.
READER_COUNTERS = ("SLC", "SEG", "REP", "AVG", "ECO", "PHS", "SET", "ACQ", "LIN", "PAR", "ONCE")
READER_FLAGS = ("NAV", "REV", "SMS", "REF", "IMA", "OFF", "NOISE", "NOPOS", "NOROT", "NOSCL")

# How the reader computes the fields that it does not take from the file as they are, for the
# message of a difference.
READER_RULES = {
    "shape_dur (us)": "the reader: the dwell times the number of samples "
    "(ExternalSequence.cpp:2063)",
    "dwell (us)": "the reader: the RF raster without a time shape (ExternalSequence.cpp:2056); "
    "with a compressed time shape of 3 or 4 stored values, the second stored value times the RF "
    "raster (2015-2021); with another time shape, the RF raster (2030)",
    "magnitude (Hz)": "the reader: with a time shape that is not compressed to 3 or 4 stored "
    "values, int(0.5 + last time) samples on the RF raster, each a stored sample that its loop "
    "picks (ExternalSequence.cpp:2022-2051); then checkRF sets a sample of the magnitude shape "
    "below 0 to 0 and above 1 to 1 (2282-2291)",
    "phase (rad)": "the reader: 2 pi times the phase shape in float (ExternalSequence.cpp:2005), "
    "resampled as the magnitude with such a time shape (2022-2051); then checkRF sets a sample "
    "below 0 to 0 and above 2 pi - 1e-4 to 2 pi - 1e-4 (2282-2291)",
    "waveform (Hz/m)": "the reader: checkGradient sets a sample of the shape below -1 to -1 and "
    "above 1 to 1 (ExternalSequence.cpp:2265-2278); of an oversampled gradient it keeps every "
    "second sample from the first (2123-2147)",
    "tt (us)": "the reader: each time of the time shape times the gradient raster, rounded to a "
    "whole number of us (ExternalSequence.cpp:2182)",
    "signature": "the reader: the MD5 of the lines before [SIGNATURE] as the file has them, with "
    "their line ends, without the last line before [SIGNATURE] when it is empty (\\n or \\r\\n) "
    "(buildFileIndex, ExternalSequence.cpp:1750-1800)",
}


class _File(NamedTuple):
    name: str  # the path from `tests/seqfiles/`
    path: Path
    data: SequenceData
    dump: dict


class _Corpus(NamedTuple):
    files: list[_File]
    skipped: list[str]  # "name: reason"


@pytest.fixture(scope="module")
def corpus():
    """The files that both readers accept, each with its model and its dump."""
    paths = sorted(SEQFILES.rglob("*.seq"))
    if not paths:
        pytest.skip(f"no .seq file in {SEQFILES}")
    files, skipped = [], []
    for path in paths:
        name = path.relative_to(SEQFILES).as_posix()
        if name in ORACLE_KNOWN_WRONG:
            continue
        if name in READ_DIFFERENTLY:
            skipped.append(f"{name}: {READ_DIFFERENTLY[name]}")
            continue
        try:
            data = read_seqfile(path)
        except (SeqFileError, NotSupported):
            continue
        if arbitrary_gradient_off_the_10_us_raster(data):
            skipped.append(f"{name}: {SKIPPED_ARBITRARY_GRADIENT_RASTER}")
            continue
        try:
            dump = cpp.dump(path)
        except cpp.OracleError as error:
            # `test_the_oracle_and_spec_accept_and_reject_the_same_files_but_those_of_the_tables`
            # reports it.
            skipped.append(f"{name}: the oracle does not accept it: {error}")
            continue
        files.append(_File(name, path, data, dump))
    return _Corpus(files, skipped)


def _us(seconds: float) -> float:
    """`seconds` in µs, rounded to 1e-6 µs, so that an integer number of µs is an integer."""
    return round(float(seconds) * 1e6, 6)


def _floats(values) -> np.ndarray:
    """`values` as float64; `None` (the `null` of the dump for NaN or infinity) is NaN."""
    return np.array(values if values is not None else np.nan, dtype=np.float64)


class _Differences:
    """The differences found in one file, each as one line of text. A line of a field of
    `READER_RULES` ends with the rule of the reader for that field. A comparison with `by_design`
    (a reason that starts with the entry of `docs/discrepancies.md`) that finds a difference
    records the reason in `designed` and no line: `spec` differs from the reader there on
    purpose."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lines: list[str] = []
        self.designed: set[str] = set()

    def add(self, where: str, text: str, field: str | None = None, by_design: str | None = None):
        if by_design:
            self.designed.add(f"{field}: {by_design}")
            return
        rule = f" ({READER_RULES[field]})" if field in READER_RULES else ""
        self.lines.append(f"{self.name}: {where}: {text}{rule}")

    def equal(self, where: str, field: str, ours, theirs, by_design: str | None = None) -> None:
        """An integer, a text or a flag: equal, or a difference."""
        if ours != theirs:
            self.add(where, f"{field}: package {ours!r}, oracle {theirs!r}", field, by_design)

    def close(
        self,
        where: str,
        field: str,
        ours,
        theirs,
        scale: float | None = None,
        by_design: str | None = None,
    ) -> None:
        """Floats (one or an array) that agree to `REL` times `scale`, by default the largest
        magnitude of the two."""
        ours, theirs = _floats(ours), _floats(theirs)
        if ours.shape != theirs.shape:
            text = f"{field}: package {ours.size} values, oracle {theirs.size} values"
            self.add(where, text, field, by_design)
            return
        if scale is None:
            scale = max(np.abs(ours).max(initial=0.0), np.abs(theirs).max(initial=0.0))
        with np.errstate(invalid="ignore"):
            wrong = (np.abs(ours - theirs) > REL * scale) | (np.isnan(ours) != np.isnan(theirs))
        if not wrong.any():
            return
        if ours.ndim == 0:
            text = f"{field}: package {float(ours)!r}, oracle {float(theirs)!r}"
            self.add(where, text, field, by_design)
            return
        i = int(np.flatnonzero(wrong)[0])
        self.add(
            where,
            f"{field}: {int(wrong.sum())} of {ours.size} values differ by more than "
            f"{REL:g} x {scale:.9g}; the first at [{i}]: package {float(ours.flat[i])!r}, "
            f"oracle {float(theirs.flat[i])!r}",
            field,
            by_design,
        )


# The reasons of the differences by design (the module docstring lists them).
DESIGNED_RF_POINTS = (
    "D2.11: an RF time shape that is not regular is points in `spec`, cells in the reader"
)
DESIGNED_RF_MAGNITUDE = "D2.8: `spec` plays a magnitude below 0 as written, the reader sets it to 0"
DESIGNED_RF_PHASE = (
    "D2.9: `spec` plays a phase outside [0, 1) turns as written, the reader clamps it"
)
DESIGNED_EXTENSION_SKIPPED = (
    "D4.6: an extension that the version of the file does not have is skipped by `spec` and read "
    "by the reader"
)
DESIGNED_SOFT_DELAY_FRACTION = (
    "D2.16: the reader reads a soft delay offset with a fraction as two values and moves the rest "
    "of the row; `spec` reads the offset as a float"
)
DESIGNED_OVERSAMPLED = (
    "D6.1: `spec` keeps all the samples of an oversampled gradient, the reader every second one"
)


def _shape_samples(data: SequenceData, shape_id: int) -> np.ndarray:
    """The decompressed samples of the shape `shape_id`."""
    return data.shapes[shape_id].samples()


def _compare_rf(
    diff: _Differences, where: str, data: SequenceData, ev: events.RfEvent, rf: dict
) -> None:
    """The RF event `ev` of the package against `rf` of the dump."""
    diff.close(where, "amplitude (Hz)", ev.amplitude, rf["amplitude"])
    diff.equal(where, "mag_id", ev.mag_id, rf["mag_shape"])
    diff.equal(where, "phase_id", ev.phase_id, rf["phase_shape"])
    diff.equal(where, "time_id", ev.time_id, rf["time_shape"])
    # The reader marks the center of a 1.4 file, which has none, with -1
    # (ExternalSequence.cpp:1037).
    center = -1.0 if ev.center is None else ev.center * 1e6
    diff.close(where, "center (us)", center, rf["center_us"])
    diff.equal(where, "delay (us)", _us(ev.delay), rf["delay_us"])
    diff.close(where, "freq_ppm", ev.freq_ppm, rf["freq_ppm"])
    diff.close(where, "phase_ppm", ev.phase_ppm, rf["phase_ppm"])
    diff.close(where, "freq_offset (Hz)", ev.freq_offset, rf["freq_offset"])
    diff.close(where, "phase_offset (rad)", ev.phase_offset, rf["phase_offset"])
    diff.equal(where, "use", ev.use, rf["use"])
    # A pulse of points is not the reader's cells: its duration, dwell and samples differ.
    points = DESIGNED_RF_POINTS if ev.dwell is None else None
    dwell = np.nan if ev.dwell is None else ev.dwell * 1e6
    diff.close(where, "shape_dur (us)", ev.shape_dur * 1e6, rf["shape_dur_us"], by_design=points)
    diff.close(where, "dwell (us)", dwell, rf["dwell_us"], by_design=points)
    # The reader sets a magnitude sample below 0 to 0 (D2.8) and clamps the phase to
    # [0, 2 pi - 1e-4] (D2.9); `spec` plays both as written. Only an event whose samples are out of
    # those ranges differs by design: every other one must agree.
    magnitude = _floats(rf["magnitude"]) * np.float64(rf["amplitude"])
    negative = bool((_shape_samples(data, ev.mag_id) < 0).any())
    outside = bool(((ev.phase < 0) | (ev.phase > 2 * np.pi - 1e-4)).any())
    diff.close(
        where,
        "magnitude (Hz)",
        ev.magnitude,
        magnitude,
        by_design=points or (DESIGNED_RF_MAGNITUDE if negative else None),
    )
    diff.close(
        where,
        "phase (rad)",
        ev.phase,
        rf["phase"],
        by_design=points or (DESIGNED_RF_PHASE if outside else None),
    )
    if negative or outside:
        # The values that the reader plays are the clamped ones.
        clamped = np.where(ev.magnitude < 0, 0.0, ev.magnitude) if ev.amplitude >= 0 else None
        if clamped is not None:
            diff.close(where, "magnitude, clamped (Hz)", clamped, magnitude, by_design=points)
        phase = np.clip(ev.phase, 0.0, 2 * np.pi - 1e-4)
        diff.close(where, "phase, clamped (rad)", phase, rf["phase"], by_design=points)


def _magnitude(ev: events.GradEvent) -> float:
    """The largest magnitude of the gradient event `ev` (Hz/m)."""
    if isinstance(ev, events.Trapezoid):
        return abs(ev.amplitude)
    return max(np.abs(ev.waveform).max(initial=0.0), abs(ev.first), abs(ev.last))


def _compare_gradient(diff: _Differences, where: str, ev: events.GradEvent, grad: dict) -> None:
    """The gradient event `ev` of the package against `grad` of the dump."""
    diff.close(where, "amplitude (Hz/m)", ev.amplitude, grad["amplitude"])
    diff.equal(where, "delay (us)", _us(ev.delay), grad["delay_us"])
    if isinstance(ev, events.Trapezoid):
        diff.equal(where, "kind", "trap", grad["kind"])
        if grad["kind"] == "trap":
            diff.equal(where, "rise_time (us)", _us(ev.rise_time), grad["ramp_up_us"])
            diff.equal(where, "flat_time (us)", _us(ev.flat_time), grad["flat_us"])
            diff.equal(where, "fall_time (us)", _us(ev.fall_time), grad["ramp_down_us"])
        return
    # An arbitrary gradient with a time shape is an extended trapezoid of the reader.
    kind = "ext_trap" if ev.time_id > 0 else "arbitrary"
    diff.equal(where, "kind", kind, grad["kind"])
    if kind != grad["kind"]:
        return
    scale = _magnitude(ev)
    if kind == "ext_trap":
        diff.equal(where, "tt (us)", [_us(t) for t in ev.tt], grad["times_us"])
        shape = _floats(grad["shape"]) * np.float64(grad["amplitude"])
        diff.close(where, "waveform with a time shape (Hz/m)", ev.waveform, shape, scale)
    else:
        diff.equal(where, "shape_id", ev.shape_id, grad["wave_shape"])
        diff.equal(where, "time_id", ev.time_id, grad["time_shape"])
        diff.equal(where, "oversampled", ev.time_id == -1, grad["oversampled"])
        # An oversampled gradient (time ID -1) has the samples of the centres of the raster cells
        # at the even indices (`tt = (i + 1) / 2 * dt`), which are the samples of the dump;
        # `spec` keeps all of them.
        waveform = ev.waveform[::2] if ev.time_id == -1 else ev.waveform
        samples = _floats(grad["samples"]) * np.float64(grad["amplitude"])
        diff.close(where, "waveform (Hz/m)", waveform, samples, scale)
        if ev.time_id == -1:
            diff.close(
                where,
                "waveform (Hz/m)",
                ev.waveform,
                samples,
                scale,
                by_design=DESIGNED_OVERSAMPLED,
            )
    # The dump has `first` and `last` of an arbitrary gradient only.
    if kind == "arbitrary":
        diff.close(where, "first (Hz/m)", ev.first, grad["first"], scale)
        diff.close(where, "last (Hz/m)", ev.last, grad["last"], scale)


def _compare_adc(diff: _Differences, where: str, ev: events.AdcEvent, adc: dict) -> None:
    diff.equal(where, "num_samples", ev.num_samples, adc["num_samples"])
    diff.equal(where, "dwell (ns)", round(float(ev.dwell) * 1e9, 6), adc["dwell_ns"])
    diff.equal(where, "delay (us)", _us(ev.delay), adc["delay_us"])
    diff.close(where, "freq_ppm", ev.freq_ppm, adc["freq_ppm"])
    diff.close(where, "phase_ppm", ev.phase_ppm, adc["phase_ppm"])
    diff.close(where, "freq_offset (Hz)", ev.freq_offset, adc["freq_offset"])
    diff.close(where, "phase_offset (rad)", ev.phase_offset, adc["phase_offset"])
    diff.equal(where, "phase_shape_id", ev.phase_shape_id, adc["phase_shape"])


def _extension_objects(data: SequenceData, head: int) -> list[tuple[str, int]]:
    """The (STRING_ID, object ID) of each entry of the extension list that starts at the entry
    `head`, in the order of the list."""
    entries = data.extensions.entries
    row_of = {int(i): n for n, i in enumerate(entries["id"])}
    string_id = {v: k for k, v in data.extensions.type_ids.items()}
    objects = []
    while head:
        entry = entries[row_of[head]]
        objects.append((string_id[int(entry["type"])], int(entry["ref"])))
        head = int(entry["next"])
    return objects


def _rows_by_id(table: np.ndarray) -> dict[int, np.void]:
    return {int(row["id"]): row for row in table}


def _expected_labels(rows: list[np.void]) -> list[dict]:
    """The labels of the dump for the label rows `rows` of a block, in the order of the list:
    the labels that the reader knows, a flag with the value 0 or 1."""
    labels = []
    for row in rows:
        name, value = str(row["name"]), int(row["value"])
        if name in READER_COUNTERS:
            labels.append({"label": name, "value": value})
        elif name in READER_FLAGS:
            labels.append({"label": name, "value": int(bool(value))})
    return labels


def _kept(objects: list, holds) -> object | None:
    """The object of one extension that the reader keeps in a block, of the objects `objects`
    of the block in the order of the list: it takes an object while the one that it has does
    not count (`holds` is false for it), and it has none when the last one does not count
    (ExternalSequence.cpp:1828-1840, 1862-1917, and the accessors of ExternalSequence.h:702-720).
    """
    kept = None
    for obj in objects:
        if kept is None or not holds(kept):
            kept = obj
    return kept if kept is not None and holds(kept) else None


def _compare_extensions(diff: _Differences, where: str, data: SequenceData, head: int, block):
    """The extension objects of the block (the list that starts at `head`) against the dump."""
    ext = data.extensions
    # `spec` skips an extension that the version of the file does not have yet, and one that it
    # does not know (D2.17, D4.6). The reader reads the first kind, and keeps no object of the second.
    skipped = set(data.skipped_extensions)
    objects = [(kind, ref) for kind, ref in _extension_objects(data, head) if kind not in skipped]

    def rows(string_id: str, table: np.ndarray) -> list[np.void]:
        by_id = _rows_by_id(table)
        return [by_id[ref] for kind, ref in objects if kind == string_id]

    def present(field: str, ours, kind: str) -> bool:
        """Whether both have the object, after a difference when one has it only: by design when
        `spec` skipped the extension `kind`."""
        if (ours is None) != (block[field] is None):
            by_design = DESIGNED_EXTENSION_SKIPPED if kind in skipped else None
            diff.equal(where, field, ours is not None, block[field] is not None, by_design)
        return ours is not None and block[field] is not None

    # A trigger of type 0 is no trigger for the reader (`isTrigger`).
    trigger = _kept(rows("TRIGGERS", ext.triggers), lambda row: int(row["type"]) != 0)
    if present("trigger", trigger, "TRIGGERS"):
        theirs = block["trigger"]
        diff.equal(where, "trigger type", int(trigger["type"]), theirs["type"])
        diff.equal(where, "trigger channel", int(trigger["channel"]), theirs["channel"])
        diff.equal(where, "trigger delay (us)", _us(trigger["delay"]), theirs["delay_us"])
        diff.equal(where, "trigger duration (us)", _us(trigger["duration"]), theirs["duration_us"])

    # A soft delay with a negative number is no soft delay for the reader (`isSoftDelay`).
    soft_delay = _kept(rows("DELAYS", ext.soft_delays), lambda row: int(row["num"]) >= 0)
    if present("soft_delay", soft_delay, "DELAYS"):
        theirs = block["soft_delay"]
        diff.equal(where, "soft delay num", int(soft_delay["num"]), theirs["num_id"])
        # The reader reads the offset as an integer, so it reads a fraction as two values and
        # moves the rest of the row (D2.16).
        offset = _us(soft_delay["offset"])
        fraction = DESIGNED_SOFT_DELAY_FRACTION if offset != round(offset) else None
        diff.equal(where, "soft delay offset (us)", offset, theirs["offset_us"], fraction)
        diff.close(
            where, "soft delay factor", soft_delay["factor"], theirs["factor"], by_design=fraction
        )
        # The reader keeps the first 31 characters of the hint.
        diff.equal(where, "soft delay hint", str(soft_delay["hint"])[:31], theirs["hint"], fraction)

    diff.equal(
        where, "labelset", _expected_labels(rows("LABELSET", ext.labelset)), block["labelset"]
    )
    diff.equal(
        where, "labelinc", _expected_labels(rows("LABELINC", ext.labelinc)), block["labelinc"]
    )

    rotation = _kept(rows("ROTATIONS", ext.rotations), lambda row: True)
    if present("rotation", rotation, "ROTATIONS"):
        q = np.array([rotation[k] for k in ("q0", "qx", "qy", "qz")], dtype=np.float64)
        # The reader divides the quaternion by its norm (ExternalSequence.cpp:1286-1293).
        diff.close(where, "rotation (normalized)", q / np.linalg.norm(q), block["rotation"])

    # An RF shim of no channel is no RF shim for the reader (`hasRfShim`).
    shims = [ref for kind, ref in objects if kind == "RF_SHIMS"]
    shim_id = _kept(shims, lambda ref: ext.rf_shims[ref].shape[0] > 0)
    if present("rf_shim", shim_id, "RF_SHIMS"):
        ours, theirs = ext.rf_shims[shim_id], block["rf_shim"]
        diff.equal(where, "rf shim id", shim_id, theirs["id"])
        diff.equal(where, "rf shim channels", ours.shape[0], theirs["nchan"])
        diff.close(where, "rf shim magnitudes", ours[:, 0], theirs["amplitudes"])
        diff.close(where, "rf shim phases", ours[:, 1], theirs["phases"])


def _compare_file(f: _File) -> tuple[list[str], set[str]]:
    """The differences of one file, and the differences by design that it has."""
    data, dump = f.data, f.dump
    diff = _Differences(f.name)
    rf_events = events.decode_rf(data)
    grad_events = events.decode_gradients(data)
    adc_events = events.decode_adc(data)
    if len(dump["blocks"]) != len(data.blocks):
        diff.equal("file", "number of blocks", len(data.blocks), len(dump["blocks"]))
        return diff.lines, diff.designed
    for k, (row, block) in enumerate(zip(data.blocks, dump["blocks"], strict=True)):
        where = f"block {k} (ID {int(row['id'])})"
        diff.equal(where, "index", k, block["index"])
        diff.equal(
            where, "duration (block rasters)", int(row["duration_ticks"]), block["duration_ru"]
        )

        rf_id = int(row["rf"])
        if (rf_id != 0) != (block["rf"] is not None):
            diff.equal(where, "rf", rf_id != 0, block["rf"] is not None)
        elif rf_id:
            _compare_rf(diff, f"{where} rf {rf_id}", data, rf_events[rf_id], block["rf"])

        for c, axis in enumerate(_AXES):
            grad_id = int(row[axis])
            theirs = block["grad"][c]
            if (grad_id != 0) != (theirs is not None):
                diff.equal(where, axis, grad_id != 0, theirs is not None)
            elif grad_id:
                _compare_gradient(diff, f"{where} {axis} {grad_id}", grad_events[grad_id], theirs)

        adc_id = int(row["adc"])
        if (adc_id != 0) != (block["adc"] is not None):
            diff.equal(where, "adc", adc_id != 0, block["adc"] is not None)
        elif adc_id:
            _compare_adc(diff, f"{where} adc {adc_id}", adc_events[adc_id], block["adc"])

        _compare_extensions(diff, f"{where} extensions", data, int(row["ext"]), block)
    return diff.lines, diff.designed


def test_the_decoded_events_equal_the_dump_of_the_cpp_reader(corpus, record_property):
    """Each field of each decoded event, the block durations and the extension objects. The
    differences by design (the module docstring) are recorded, each with its files."""
    assert corpus.files, "no file to compare"
    differences = []
    designed: dict[str, list[str]] = {}
    for f in corpus.files:
        lines, met = _compare_file(f)
        differences += lines
        for reason in met:
            designed.setdefault(reason, []).append(f.name)
    record_property("skipped", "; ".join(corpus.skipped))
    record_property(
        "by_design",
        "; ".join(f"{reason}: {', '.join(names)}" for reason, names in sorted(designed.items())),
    )
    assert not differences, "\n".join(differences)


# The files with an md5 signature on which `spec` and the reader differ, with the place of the
# specification that `spec` follows: `spec` hashes the bytes before the `\n` before `[SIGNATURE]` (spec:223),
# the reader drops an empty line (`\n` or `\r\n`) and keeps the `\r` of the other line ends.
SIGNATURE_BY_DESIGN = {"valid_crlf.seq": "spec:223"}


def test_signature_matches_equals_the_signature_check_of_the_cpp_reader(corpus):
    """For each file with an md5 signature, `signature.matches` against `signature_ok`, except
    the files of `SIGNATURE_BY_DESIGN`, where `spec` finds no match and the reader finds one. The
    reader lowers the case of the type (ExternalSequence.cpp:1633)."""
    compared = [
        f for f in corpus.files if f.data.signature and f.data.signature.type.lower() == "md5"
    ]
    assert compared, "no file with an md5 signature"
    differences = []
    for f in compared:
        diff = _Differences(f.name)
        if f.name in SIGNATURE_BY_DESIGN:
            diff.equal("[SIGNATURE]", "signature (spec)", f.data.signature.matches, False)
            diff.equal("[SIGNATURE]", "signature (oracle)", f.dump["signature_ok"], True)
        else:
            diff.equal("[SIGNATURE]", "signature", f.data.signature.matches, f.dump["signature_ok"])
        differences += diff.lines
    assert not differences, "\n".join(differences)
    assert {f.name for f in compared} >= set(SIGNATURE_BY_DESIGN)


def test_a_regular_rf_time_shape_equals_the_dump_and_a_pulse_of_points_does_not(
    tmp_path, record_property
):
    """`valid_rf_time_shapes.seq` without the block of RF 3 (the short uncompressed pulse, which
    the reader reads past its end and crashes on): RF 2 has a regular time shape `1 2 2 47`
    (50 samples, times 1, 3, ..., 99: cells of 2 us), which the two read alike; RF 4 and 5 are
    points, which `spec` joins by lines and the reader resamples to cells of 1 us (D2.11)."""
    text = (SEQFILES / "valid_rf_time_shapes.seq").read_text()
    without_rf_3 = text.replace("11 20  3  0  0  0  0  0\n", "")
    assert without_rf_3 != text
    path = tmp_path / "rf_time_shapes.seq"
    path.write_text(without_rf_3)
    data = read_seqfile(path)
    dump = cpp.dump(path)
    lines, designed = _compare_file(_File(path.name, path, data, dump))
    assert not lines, "\n".join(lines)
    rf = events.decode_rf(data)
    assert rf[2].dwell == pytest.approx(2e-6) and rf[2].magnitude.size == 50
    assert rf[2].shape_dur == pytest.approx(100e-6)
    assert rf[4].dwell is None and rf[5].dwell is None
    reader = [block["rf"] for block in dump["blocks"][-3:]]
    assert [r["time_shape"] for r in reader] == [12, 18, 21]
    assert [r["dwell_us"] for r in reader] == [2, 1, 1]
    assert [r["dwell_us"] * len(r["magnitude"]) for r in reader] == [100, 100, 10]
    assert any(reason.startswith("dwell (us): D2.11") for reason in designed)
    record_property("by_design", "; ".join(sorted(designed)))


def _sample_times(data: SequenceData, grad_events) -> tuple[np.ndarray, np.ndarray]:
    """The block index and the time (µs from the block start) of each time to sample, in play
    order: the centre of each gradient raster cell of a block from the start of its first
    gradient event to the end of its last one (on any axis), and the start and the end of each
    gradient event, each when it is strictly inside its block."""
    dt_us = data.rasters.gradient * 1e6
    durations_us = data.blocks["duration_ticks"] * data.rasters.block_duration * 1e6
    block_index, time_us = [], []
    for k, row in enumerate(data.blocks):
        ends = []
        for axis in _AXES:
            if row[axis]:
                ev = grad_events[int(row[axis])]
                ends += [ev.delay * 1e6, (ev.delay + ev.shape_dur) * 1e6]
        if not ends:
            continue
        duration = durations_us[k]
        cells = (np.arange(np.floor(min(ends) / dt_us), np.ceil(max(ends) / dt_us)) + 0.5) * dt_us
        times = np.unique(np.concatenate([cells, ends]))
        # A time within 1e-6 us of a block boundary is at the boundary.
        times = times[(times > 1e-6) & (times < duration - 1e-6)]
        block_index.append(np.full(times.size, k))
        time_us.append(times)
    if not block_index:
        return np.zeros(0, np.int64), np.zeros(0)
    return np.concatenate(block_index), np.concatenate(time_us)


def test_the_gradient_waveform_equals_gradients_at_of_the_cpp_reader(corpus, record_property):
    """`GradientSampler` of the model against `--sample` at the times of `_sample_times`. The
    times of a block before its first gradient event and after its last one are not sampled:
    there the reader gives 0 on each axis, since no event of the block covers them, and the
    10 M cells of the corpus would take more than the time budget of the test. The scale of a
    value is the largest magnitude of the event of the block on the axis, or the largest of the
    axis when the block has no event on it."""
    differences = []
    sampled = []
    for f in corpus.files:
        data = f.data
        grads = events.decode_gradients(data)
        block_index, time_us = _sample_times(data, grads)
        if not block_index.size:
            continue
        index = seq_index._index_from_data(data)
        ids = seq_index._dense_ids(data, index)
        points = _events._points_from_events(
            [(k + 1, grads[int(i)]) for k, i in enumerate(ids.grad)], data.rasters.gradient
        )
        sampler = sampling.GradientSampler._from_parts(index, points, {})
        t = index.start_s[block_index] + time_us * 1e-6
        theirs = cpp.sample(f.path, block_index, time_us)
        sampled.append(f"{f.name}: {block_index.size}")
        for c, axis in enumerate(_AXES):
            ours = sampler.sample(axis, t)
            magnitudes = np.array(
                [_magnitude(grads[int(i)]) if i else 0.0 for i in data.blocks[axis]]
            )
            # The sampler joins the events of neighbouring blocks with a ramp (D2.14), which starts
            # at 0 half a raster before the next event. A block with no event on the axis can
            # hold the start of that ramp, at a value that is rounding noise against the
            # amplitudes of the axis, so its scale is the largest of the axis.
            magnitudes[magnitudes == 0] = magnitudes.max(initial=0.0)
            wrong = np.flatnonzero(np.abs(ours - theirs[:, c]) > REL * magnitudes[block_index])
            for i in wrong[:5].tolist():
                k = int(block_index[i])
                differences.append(
                    f"{f.name}: block {k} (ID {int(data.blocks['id'][k])}) {axis} at "
                    f"{float(time_us[i])!r} us from the block start: package {float(ours[i])!r}, "
                    f"oracle {float(theirs[i, c])!r}"
                )
            if wrong.size > 5:
                differences.append(f"{f.name}: {axis}: {wrong.size} times differ in all")
    assert sampled, "no file to sample"
    record_property("sampled", "; ".join(sampled))
    record_property("skipped", "; ".join(corpus.skipped + [SKIPPED_BLOCK_BOUNDARY]))
    assert not differences, "\n".join(differences)
