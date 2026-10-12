"""Tests of the decoded events and the gradient waveform of the package against the C++ oracle:
the reader `ExternalSequence` of pulseq/pulseq (the reader of the Pulseq interpreter on the
scanner), in the modes `--dump` and `--sample` of `pulseq-cpp-oracle` (`tests/oracles/cpp.py`;
`tests/cpp_oracle/README.md` has the fields and their units).

Each test compares each file of `tests/seqfiles/` that `read_seqfile` and the oracle accept,
except the files of `ORACLE_KNOWN_WRONG` and those with an arbitrary gradient on a gradient raster
other than 10 us (`decodeBlock` fails on them). The event values of the reader are `float` (32
bits), so two values agree when they differ by at most `REL` times the largest magnitude of the
event. An integer field agrees when it is equal.

A difference means that the reader of the scanner holds another value than the package, for a
file that the parser accepts: for an event, the scanner plays something else than the package
reads in the file. A test fails with each difference, with the rule of the reader for the field
when `READER_RULES` has it. It does not skip a difference.

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

from pulseq_analysis.seqfile.model import SequenceData
from pulseq_analysis.seqfile.reader import SeqFileError, read_seqfile
from pulseq_analysis.synth import _events, events, sampling, seq_index

pytestmark = pytest.mark.skipif(ORACLE is None, reason="pulseq-cpp-oracle is not on the PATH")

# The relative tolerance of a value: the reader holds its values as `float` (32 bits).
REL = 1e-6

_AXES = ("gx", "gy", "gz")

# The reasons of the planned skips (docs/plans/own-parser-tasks.md, section 4.7). Each skip is by
# a rule on the model, never by the name of a file.
SKIPPED_FIRST_LAST_1_4 = (
    "first and last of an arbitrary gradient of a 1.4 file: the reader sets them to "
    "FLOAT_UNDEFINED (ExternalSequence.cpp:1085-1086)"
)
SKIPPED_BLOCK_BOUNDARY = (
    "a time at a block boundary: gradientsAt works inside one block and does not join blocks"
)

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
        try:
            data = read_seqfile(path)
        except SeqFileError:
            continue
        if arbitrary_gradient_off_the_10_us_raster(data):
            skipped.append(f"{name}: {SKIPPED_ARBITRARY_GRADIENT_RASTER}")
            continue
        try:
            dump = cpp.dump(path)
        except cpp.OracleError as error:
            # `test_the_oracle_and_read_seqfile_accept_and_reject_the_same_files` reports it.
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
    `READER_RULES` ends with the rule of the reader for that field."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lines: list[str] = []

    def add(self, where: str, text: str, field: str | None = None) -> None:
        rule = f" ({READER_RULES[field]})" if field in READER_RULES else ""
        self.lines.append(f"{self.name}: {where}: {text}{rule}")

    def equal(self, where: str, field: str, ours, theirs) -> None:
        """An integer, a text or a flag: equal, or a difference."""
        if ours != theirs:
            self.add(where, f"{field}: package {ours!r}, oracle {theirs!r}", field)

    def close(self, where: str, field: str, ours, theirs, scale: float | None = None) -> None:
        """Floats (one or an array) that agree to `REL` times `scale`, by default the largest
        magnitude of the two."""
        ours, theirs = _floats(ours), _floats(theirs)
        if ours.shape != theirs.shape:
            text = f"{field}: package {ours.size} values, oracle {theirs.size} values"
            self.add(where, text, field)
            return
        if scale is None:
            scale = max(np.abs(ours).max(initial=0.0), np.abs(theirs).max(initial=0.0))
        with np.errstate(invalid="ignore"):
            wrong = (np.abs(ours - theirs) > REL * scale) | (np.isnan(ours) != np.isnan(theirs))
        if not wrong.any():
            return
        if ours.ndim == 0:
            text = f"{field}: package {float(ours)!r}, oracle {float(theirs)!r}"
            self.add(where, text, field)
            return
        i = int(np.flatnonzero(wrong)[0])
        self.add(
            where,
            f"{field}: {int(wrong.sum())} of {ours.size} values differ by more than "
            f"{REL:g} x {scale:.9g}; the first at [{i}]: package {float(ours.flat[i])!r}, "
            f"oracle {float(theirs.flat[i])!r}",
            field,
        )


def _compare_rf(diff: _Differences, where: str, ev: events.RfEvent, rf: dict) -> None:
    """The RF event `ev` of the package against `rf` of the dump."""
    diff.close(where, "amplitude (Hz)", ev.amplitude, rf["amplitude"])
    diff.equal(where, "mag_id", ev.mag_id, rf["mag_shape"])
    diff.equal(where, "phase_id", ev.phase_id, rf["phase_shape"])
    diff.equal(where, "time_id", ev.time_id, rf["time_shape"])
    diff.close(where, "shape_dur (us)", ev.shape_dur * 1e6, rf["shape_dur_us"])
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
    # The package's samples are one dwell apart, in cells that fill `shape_dur`.
    dwell = ev.shape_dur / ev.magnitude.size if ev.magnitude.size else np.nan
    diff.close(where, "dwell (us)", dwell * 1e6, rf["dwell_us"])
    magnitude = _floats(rf["magnitude"]) * np.float64(rf["amplitude"])
    diff.close(where, "magnitude (Hz)", ev.magnitude, magnitude)
    diff.close(where, "phase (rad)", ev.phase, rf["phase"])


def _magnitude(ev: events.GradEvent) -> float:
    """The largest magnitude of the gradient event `ev` (Hz/m)."""
    if isinstance(ev, events.Trapezoid):
        return abs(ev.amplitude)
    return max(np.abs(ev.waveform).max(initial=0.0), abs(ev.first), abs(ev.last))


def _compare_gradient(
    diff: _Differences, where: str, ev: events.GradEvent, grad: dict, version: tuple
) -> str | None:
    """The gradient event `ev` of the package against `grad` of the dump. Returns a planned
    skip, or `None`."""
    diff.close(where, "amplitude (Hz/m)", ev.amplitude, grad["amplitude"])
    diff.equal(where, "delay (us)", _us(ev.delay), grad["delay_us"])
    if isinstance(ev, events.Trapezoid):
        diff.equal(where, "kind", "trap", grad["kind"])
        if grad["kind"] == "trap":
            diff.equal(where, "rise_time (us)", _us(ev.rise_time), grad["ramp_up_us"])
            diff.equal(where, "flat_time (us)", _us(ev.flat_time), grad["flat_us"])
            diff.equal(where, "fall_time (us)", _us(ev.fall_time), grad["ramp_down_us"])
        return None
    # An arbitrary gradient with a time shape is an extended trapezoid of the reader.
    kind = "ext_trap" if ev.time_id > 0 else "arbitrary"
    diff.equal(where, "kind", kind, grad["kind"])
    if kind != grad["kind"]:
        return None
    scale = _magnitude(ev)
    if kind == "ext_trap":
        diff.equal(where, "tt (us)", [_us(t) for t in ev.tt], grad["times_us"])
        shape = _floats(grad["shape"]) * np.float64(grad["amplitude"])
        diff.close(where, "waveform with a time shape (Hz/m)", ev.waveform, shape, scale)
        return None
    diff.equal(where, "shape_id", ev.shape_id, grad["wave_shape"])
    diff.equal(where, "time_id", ev.time_id, grad["time_shape"])
    diff.equal(where, "oversampled", ev.time_id == -1, grad["oversampled"])
    # An oversampled gradient (time ID -1) has the samples of the centres of the raster cells
    # at the even indices (`tt = (i + 1) / 2 * dt`), which are the samples of the dump.
    waveform = ev.waveform[::2] if ev.time_id == -1 else ev.waveform
    samples = _floats(grad["samples"]) * np.float64(grad["amplitude"])
    diff.close(where, "waveform (Hz/m)", waveform, samples, scale)
    if version < (1, 5, 0):
        return SKIPPED_FIRST_LAST_1_4
    diff.close(where, "first (Hz/m)", ev.first, grad["first"], scale)
    diff.close(where, "last (Hz/m)", ev.last, grad["last"], scale)
    return None


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
    objects = _extension_objects(data, head)

    def rows(string_id: str, table: np.ndarray) -> list[np.void]:
        by_id = _rows_by_id(table)
        return [by_id[ref] for kind, ref in objects if kind == string_id]

    def present(field: str, ours) -> bool:
        """Whether both have the object, after a difference when one has it only."""
        if (ours is None) != (block[field] is None):
            diff.equal(where, field, ours is not None, block[field] is not None)
        return ours is not None and block[field] is not None

    # A trigger of type 0 is no trigger for the reader (`isTrigger`).
    trigger = _kept(rows("TRIGGERS", ext.triggers), lambda row: int(row["type"]) != 0)
    if present("trigger", trigger):
        theirs = block["trigger"]
        diff.equal(where, "trigger type", int(trigger["type"]), theirs["type"])
        diff.equal(where, "trigger channel", int(trigger["channel"]), theirs["channel"])
        diff.equal(where, "trigger delay (us)", _us(trigger["delay"]), theirs["delay_us"])
        diff.equal(where, "trigger duration (us)", _us(trigger["duration"]), theirs["duration_us"])

    # A soft delay with a negative number is no soft delay for the reader (`isSoftDelay`).
    soft_delay = _kept(rows("DELAYS", ext.soft_delays), lambda row: int(row["num"]) >= 0)
    if present("soft_delay", soft_delay):
        theirs = block["soft_delay"]
        diff.equal(where, "soft delay num", int(soft_delay["num"]), theirs["num_id"])
        diff.equal(where, "soft delay offset (us)", _us(soft_delay["offset"]), theirs["offset_us"])
        diff.close(where, "soft delay factor", soft_delay["factor"], theirs["factor"])
        # The reader keeps the first 31 characters of the hint.
        diff.equal(where, "soft delay hint", str(soft_delay["hint"])[:31], theirs["hint"])

    diff.equal(
        where, "labelset", _expected_labels(rows("LABELSET", ext.labelset)), block["labelset"]
    )
    diff.equal(
        where, "labelinc", _expected_labels(rows("LABELINC", ext.labelinc)), block["labelinc"]
    )

    rotation = _kept(rows("ROTATIONS", ext.rotations), lambda row: True)
    if present("rotation", rotation):
        q = np.array([rotation[k] for k in ("q0", "qx", "qy", "qz")], dtype=np.float64)
        # The reader divides the quaternion by its norm (ExternalSequence.cpp:1286-1293).
        diff.close(where, "rotation (normalized)", q / np.linalg.norm(q), block["rotation"])

    # An RF shim of no channel is no RF shim for the reader (`hasRfShim`).
    shims = [ref for kind, ref in objects if kind == "RF_SHIMS"]
    shim_id = _kept(shims, lambda ref: ext.rf_shims[ref].shape[0] > 0)
    if present("rf_shim", shim_id):
        ours, theirs = ext.rf_shims[shim_id], block["rf_shim"]
        diff.equal(where, "rf shim id", shim_id, theirs["id"])
        diff.equal(where, "rf shim channels", ours.shape[0], theirs["nchan"])
        diff.close(where, "rf shim magnitudes", ours[:, 0], theirs["amplitudes"])
        diff.close(where, "rf shim phases", ours[:, 1], theirs["phases"])


def _compare_file(f: _File) -> tuple[list[str], set[str]]:
    """The differences of one file, and the planned skips that it met."""
    data, dump = f.data, f.dump
    diff = _Differences(f.name)
    skips: set[str] = set()
    rf_events = events.decode_rf(data)
    grad_events = events.decode_gradients(data)
    adc_events = events.decode_adc(data)
    if len(dump["blocks"]) != len(data.blocks):
        diff.equal("file", "number of blocks", len(data.blocks), len(dump["blocks"]))
        return diff.lines, skips
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
            _compare_rf(diff, f"{where} rf {rf_id}", rf_events[rf_id], block["rf"])

        for c, axis in enumerate(_AXES):
            grad_id = int(row[axis])
            theirs = block["grad"][c]
            if (grad_id != 0) != (theirs is not None):
                diff.equal(where, axis, grad_id != 0, theirs is not None)
            elif grad_id:
                skip = _compare_gradient(
                    diff, f"{where} {axis} {grad_id}", grad_events[grad_id], theirs, data.version
                )
                if skip:
                    skips.add(skip)

        adc_id = int(row["adc"])
        if (adc_id != 0) != (block["adc"] is not None):
            diff.equal(where, "adc", adc_id != 0, block["adc"] is not None)
        elif adc_id:
            _compare_adc(diff, f"{where} adc {adc_id}", adc_events[adc_id], block["adc"])

        _compare_extensions(diff, f"{where} extensions", data, int(row["ext"]), block)
    return diff.lines, skips


def test_the_decoded_events_equal_the_dump_of_the_cpp_reader(corpus, record_property):
    """Each field of each decoded event, the block durations and the extension objects."""
    assert corpus.files, "no file to compare"
    differences = []
    skips: dict[str, list[str]] = {}
    for f in corpus.files:
        lines, met = _compare_file(f)
        differences += lines
        for skip in met:
            skips.setdefault(skip, []).append(f.name)
    record_property(
        "skipped",
        "; ".join(corpus.skipped + [f"{reason}: {', '.join(n)}" for reason, n in skips.items()]),
    )
    assert not differences, "\n".join(differences)


def test_signature_matches_equals_the_signature_check_of_the_cpp_reader(corpus):
    """For each file with an md5 signature, `signature.matches` against `signature_ok`. The
    reader lowers the case of the type (ExternalSequence.cpp:1633)."""
    compared = [
        f for f in corpus.files if f.data.signature and f.data.signature.type.lower() == "md5"
    ]
    assert compared, "no file with an md5 signature"
    differences = []
    for f in compared:
        diff = _Differences(f.name)
        diff.equal("[SIGNATURE]", "signature", f.data.signature.matches, f.dump["signature_ok"])
        differences += diff.lines
    assert not differences, "\n".join(differences)


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
    value is the largest magnitude of the event of the block on the axis, or 0 when the block
    has no event on the axis."""
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
