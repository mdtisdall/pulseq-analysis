"""The `cpp-siemens` interpreter: a Pulseq file as the C++ reader of the scanner's interpreter on
Siemens systems reads it (`ExternalSequence` of pulseq/pulseq at `c7469123`), through the package
pulseq-cpp-siemens (the extra `pulseq-analysis[cpp-siemens]`). Section 5 of
`docs/plans/parser-redesign.md` gives what it reads and rejects, entry by entry.

`read_cpp_siemens(path, interpreter)`, which `seqfile.read_seqfile(path, "cpp-siemens")` calls,
reads a file in four steps:

1. **The version gate** (Q1 of the plan). The "as written" reading (`as_written`) gives the
   version of the first `[VERSION]` section. A version outside 1.4.0 to 1.5.x raises
   `NotSupported` before the C++ reader runs. pulseq-cpp-siemens then reads the version again
   as the reader does (the reader takes the last row of each key), and refuses it in the same
   way; a binary Pulseq file and a folder are `NotSupported` too.
2. **`ExternalSequence::load`**, then the checks of pulseq-cpp-siemens for the undefined
   behaviour of the reader (section 5.3 of the plan): a case is a rejection with its `ub.*`
   code.
3. **`decodeBlock` of every block**, as the C++ oracle's first mode does. A block that it
   rejects rejects the file. No decoded block is kept.
4. **The model** (`model.SequenceData`) from the reader's own libraries (P14): the events,
   shapes, blocks, definitions and extensions as the reader read them, misreadings included.
   `SequenceData.reading` keeps the reader's object, for its libraries, `decode_block` and
   `gradients_at`.

**The rejections.** The reader gives a message, not a code. `CODES` gives each code of a
rejection, with its entry of `docs/discrepancies.md`, and `_classify` finds it from the reader's
message, and where the message is not enough, from the "as written" reading. The reasons of a
`SeqFileError` of `cpp-siemens` are the code, the section and the line (where the message quotes
a row), and the reader's message. The reader stops at its first error, so a rejection has one
reason.

**The model from the libraries.** Where the reader holds a value, the model has it, in the units
of the model (s, Hz, Hz/m) from the reader's float32 values (P6), so a value can differ from the
file in the last digits of float32 (D18). Where the reader differs from `strict`:

- `blocks`: the reader keeps no block ID, so `id` is the position in play order, from 1. Play
  order is file order (D20).
- `rf`: a 1.4 event has `center` NaN (the reader holds -1, D38); `use` is the character that the
  reader holds, any character (D17).
- `grad` and `trap`: the reader keeps `[GRADIENTS]` and `[TRAP]` in one library; a shape ID of 0
  is a trapezoid. `first` and `last` are the reader's values; NaN where it leaves them unset.
- `adc`: the dwell time is the integer that the reader reads (D15).
- `definitions`: in the order of the keys (the reader keeps a sorted map), each value split at
  white space; a key defined twice has its last value (D12).
- `extensions`: `rotations` are the reader's quaternions, divided by their norm (D49);
  `skipped_extensions` the extensions that the reader does not know (D45).
- `signature`: `matches` is the reader's check of its MD5 hash (D53).
"""

import re
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from .as_written import AsWritten, read_as_written
from .errors import NotSupported, SeqFileError, Violation
from .interpreters import CppSiemens
from .model import TABLE_DTYPES, Extensions, Rasters, SequenceData, Shape, Signature

__all__ = ["CODES", "read_cpp_siemens"]

# The versions that the package reads (Q1): 1.4.0 up to, not including, 1.6.0.
_MIN_VERSION, _MAX_VERSION = (1, 4, 0), (1, 6, 0)

# The codes of the rejections of `cpp-siemens`: each code, its entry of docs/discrepancies.md
# ("—" for none), and what the reader rejects. The `ub.*` codes are those of pulseq-cpp-siemens
# (`pulseq_cpp_siemens.CODES`, section 5.3 of the plan).
CODES: MappingProxyType[str, tuple[str, str]] = MappingProxyType(
    {
        "version.missing": ("D02", "the file has no [VERSION] section"),
        "version.invalid": ("D02", "a line of [VERSION] does not decode, or has an unknown key"),
        "definitions.raster-missing": ("D11", "a required raster is not defined"),
        "definitions.raster-invalid": (
            "D11",
            "a required raster has no value that the reader reads",
        ),
        "definitions.skipped": (
            "D56",
            "the reader skips [DEFINITIONS], after a section that it read to the end of the file",
        ),
        "extension.required-unknown": ("D47", "a required extension is unknown to the reader"),
        "section.extensions-last": ("D46", "[EXTENSIONS] is the last section of the file"),
        "blocks.missing": ("—", "the file has no [BLOCKS] section"),
        "syntax.row": ("D14", "a row does not decode with the reader's sscanf format"),
        "syntax.comment-row": ("D06", "a `#` line inside a table, which the reader reads as a row"),
        "syntax.shape": ("D14", "a line of [SHAPES] does not decode"),
        "ref.unresolved": ("D21", "a block names an event that the reader did not read"),
        "rotation.norm": ("D49", "a quaternion's norm is more than 1e-3 from 1"),
        "gradient.raster": (
            "D28",
            "an arbitrary gradient in a file whose gradient raster is not 10 us",
        ),
        "shape.decompression": ("D29", "a shape whose compression the reader cannot decode"),
        "shape.ext-trap-lengths": (
            "—",
            "the time shape and the waveform of an extended trapezoid differ in length",
        ),
        "cpp.exception": ("—", "the reader throws a C++ exception"),
        "cpp.rejected": ("—", "the reader rejects the file for another reason"),
        "ub.shape-missing": ("D21", "a block uses a shape that the reader did not read"),
        "ub.rf-time-id-minus-1": ("D22", "an RF event with time ID -1"),
        "ub.extension-cycle": ("D23", "a cycle in an extension list"),
        "ub.shape-decompression": ("D29", "a shape decompresses past its buffer"),
        "ub.shape-empty": ("D33", "an event uses a shape with no sample"),
        "ub.rf-shape-lengths": ("D34", "an RF phase shape shorter than its magnitude"),
        "ub.rf-time-overrun": ("D36", "the RF resampling reads past the time shape"),
        "ub.rf-time-range": ("D36", "an RF time shape's last time does not fit an int"),
        "ub.gradient-time-range": ("D29", "an extended trapezoid time does not fit a long"),
        "ub.gradient-one-point": ("—", "gradientsAt reads past an extended trapezoid of one point"),
        "ub.gradient-shape-0": ("—", "a [GRADIENTS] row of shape 0, which load leaves unset"),
    }
)

# The reader's messages of a rejection by `load`, in the order in which they are tried: a regular
# expression, the code, and the section. "syntax.row" is a row that does not decode (cpp:940-1365,
# 1574), which the reader quotes after its message; `_classify` refines it to
# "syntax.comment-row" or "syntax.shape". "definitions.raster-missing" is refined to
# "definitions.raster-invalid" or "definitions.skipped" by the "as written" reading.
_LOAD_MESSAGES = (
    (r"^exception: ", "cpp.exception", None),
    (r"MUST contain the \[VERSION\] section", "version.missing", None),
    (
        r"failed to decode version_|unknown field in the \[VERSION\] block",
        "version.invalid",
        "VERSION",
    ),
    (
        r"failed find the end of the section while reading EXTENSIONS",
        "section.extensions-last",
        "EXTENSIONS",
    ),
    (r"Required: definition (\w+) is not present", "definitions.raster-missing", "DEFINITIONS"),
    (
        r"is unknown to this interpreter but is defined as REQUIRED",
        "extension.required-unknown",
        "DEFINITIONS",
    ),
    (r"Required: \[BLOCKS\] section", "blocks.missing", None),
    (r"contains references to undefined events", "ref.unresolved", "BLOCKS"),
    (r"non-normalized quaternion", "rotation.norm", "extension ROTATIONS"),
    (r"\*\*\* ERROR: failed to decode RF event", "syntax.row", "RF"),
    (r"\*\*\* ERROR: failed to decode v1\.[24]\.x gradient event", "syntax.row", "GRADIENTS"),
    (r"\*\*\* ERROR: failed to decode trapezoid gradient entry", "syntax.row", "TRAP"),
    (r"\*\*\* ERROR: failed to decode ADC event", "syntax.row", "ADC"),
    (r"\*\*\* ERROR: failed to decode delay event", "syntax.row", "DELAYS"),
    (r"\*\*\* ERROR: failed to decode extension (header|list) entry", "syntax.row", "EXTENSIONS"),
    (r"\*\*\* ERROR: failed to decode trigger event", "syntax.row", "extension TRIGGERS"),
    (r"\*\*\* ERROR: failed to decode rotation event", "syntax.row", "extension ROTATIONS"),
    (r"\*\*\* ERROR: failed to (load|decode) labelset event", "syntax.row", "extension LABELSET"),
    (r"\*\*\* ERROR: failed to decode labelinc event", "syntax.row", "extension LABELINC"),
    (r"\*\*\* ERROR: failed to decode soft delay event", "syntax.row", "extension DELAYS"),
    (r"\*\*\* ERROR: failed to decode RF shim event", "syntax.row", "extension RF_SHIMS"),
    (r"\*\*\* ERROR: failed to decode event table entry:", "syntax.row", "BLOCKS"),
    (r"\*\*\* ERROR: failed to decode '(shapeId|numSamples|sample)'", "syntax.row", "SHAPES"),
)

# The reader's messages of a rejection by `decodeBlock`: the text, the code and the section. A
# gradient raster other than 10 us (D28) has no message (`_classify`).
_DECODE_MESSAGES = (
    ("exception: ", "cpp.exception", "BLOCKS"),
    ("compressed shape format error", "shape.decompression", "SHAPES"),
    (
        "extended trapezoid time and wave shape lengths do not match",
        "shape.ext-trap-lengths",
        "GRADIENTS",
    ),
)

# A number as the reader's `istringstream >> double` reads a definition: a decimal number with an
# optional exponent (not nan or inf).
_STREAM_NUMBER = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")

_US, _NS = 1e6, 1e9  # microseconds and nanoseconds in a second

# The extensions that the reader knows (cpp:1233-1249); it ignores any other.
_KNOWN_EXT_TYPES = {"TRIGGERS", "ROTATIONS", "LABELSET", "LABELINC", "DELAYS", "RF_SHIMS"}


def _engine() -> Any:
    try:
        import pulseq_cpp_siemens
    except ImportError as error:
        raise ImportError(
            "the interpreter cpp-siemens needs the package pulseq-cpp-siemens: install "
            "pulseq-analysis[cpp-siemens], or read with interpreter='strict'"
        ) from error
    return pulseq_cpp_siemens


def read_cpp_siemens(path: str | Path, interpreter: CppSiemens | None = None) -> SequenceData:
    """Read the Pulseq text file `path` as the C++ reader reads it (the module docstring).

    Raises `NotSupported` for a file outside the package's scope (the reader is not run),
    `SeqFileError` (a `ValueError`) with the code of `CODES` when the reader rejects the file,
    `ImportError` without pulseq-cpp-siemens, and `OSError` when the file cannot be read."""
    interpreter = interpreter or CppSiemens()
    cs = _engine()
    path = Path(path)
    if path.is_dir():
        raise NotSupported(f"{path} is a folder; the package reads one .seq file")
    written = read_as_written(path)
    if written.version is not None and not _MIN_VERSION <= written.version < _MAX_VERSION:
        name = ".".join(map(str, written.version))
        raise NotSupported(
            f"{path}: version {name} is outside 1.4.0 to 1.5.x; the package does not read it"
        )
    try:
        sequence = cs.load(written.raw, oversampling=interpreter.oversampling)
    except cs.NotSupported as error:
        raise NotSupported(f"{path}: {error}") from None
    except cs.UndefinedBehaviour as error:
        reason = Violation(error.code, None, None, str(error))
        raise SeqFileError(str(path), [reason], interpreter=interpreter.name) from None
    except cs.Rejected as error:
        reason = _classify(error.messages, written, None)
        raise SeqFileError(str(path), [reason], interpreter=interpreter.name) from None
    index = sequence.first_rejected_block()
    if index is not None:
        reason = _classify(sequence.rejection_messages, written, (sequence.libraries, index))
        raise SeqFileError(str(path), [reason], interpreter=interpreter.name)
    return _model(sequence, interpreter, written)


def _quoted_row(messages: str, start: int) -> str:
    """The row that the reader quotes after its message, which ends at `start`: the rest of the
    line, or the next line when the message ends its line."""
    rest = messages[start:]
    first, _, after = rest.partition("\n")
    return (first if first.strip() else after.partition("\n")[0]).strip()


def _line_of(written: AsWritten, section: str, row: str) -> int | None:
    """The first line of the sections `section` whose text is `row` (the reader reads at most 255
    bytes of a line, and drops a `\\r`)."""
    if not row:
        return None
    for s in written.sections:
        name = s.name if s.extension is None else f"extension {s.extension[0]}"
        if name != section:
            continue
        candidates = [(int(s.rows.lines[i]), s.rows.row(i)) for i in range(len(s.rows))]
        candidates += [(line.number, line.text) for line in s.comments]
        for shape in s.shapes:
            candidates.append((shape.line.number, shape.line.text))
            if shape.num_samples_line is not None:
                candidates.append((shape.num_samples_line.number, shape.num_samples_line.text))
        for number, text in sorted(candidates):
            text = text.rstrip("\r").strip()
            if text == row or (len(row) >= 250 and text.startswith(row)):
                return number
    return None


def _definition_value(written: AsWritten, key: str) -> list[str] | None:
    """The value of the last row `key` of the last `[DEFINITIONS]` section as written, or None."""
    found = None
    for section in written.named("DEFINITIONS"):
        for i in range(len(section.rows)):
            fields = section.rows.fields(i)
            if fields and fields[0] == key:
                found = list(fields[1:])
    return found


def _classify(messages: str, written: AsWritten, decoded: tuple[Any, int] | None) -> Violation:
    """The reason of a rejection from the reader's `messages`: by `load` (`decoded` None), or by
    `decodeBlock` of the block `decoded[1]` of the libraries `decoded[0]`. The message of the
    reason is the reader's, from the line of the error that decides the code (the reader prints
    warnings and notes before it, some of them with "ERROR" in them)."""
    text = messages.strip()

    def shown(at: int) -> str:
        return text[text.rfind("\n", 0, at) + 1 :]

    if decoded is not None:
        libraries, index = decoded
        for pattern, code, section in _DECODE_MESSAGES:
            at = text.find(pattern)
            if at >= 0:
                return Violation(code, section, None, f"block {index}: {shown(at)}")
        row = libraries.blocks[index]
        arbitrary = any(
            int(g) in libraries.grad
            and libraries.grad[int(g)]["wave_shape"] != 0
            and libraries.grad[int(g)]["time_shape"] <= 0
            for g in row[2:5]
        )
        if arbitrary and abs(libraries.gradient_raster_us - 10) > 1e-3:
            message = (
                f"block {index}: decodeBlock rejects an arbitrary gradient on a gradient raster "
                f"of {libraries.gradient_raster_us:g} us, not 10 us (cpp:2114-2119)"
            )
            return Violation("gradient.raster", "BLOCKS", None, message)
        return Violation("cpp.rejected", "BLOCKS", None, f"block {index}: {text}")

    for pattern, code, section in _LOAD_MESSAGES:
        match = re.search(pattern, text)
        if match is None:
            continue
        at, line = match.start(), None
        if code == "definitions.raster-missing":
            value = _definition_value(written, match.group(1))
            if value and _STREAM_NUMBER.match(value[0]):
                code = "definitions.skipped"
            elif value is not None:
                code = "definitions.raster-invalid"
        elif code == "syntax.row":
            row = _quoted_row(text, match.end())
            line = _line_of(written, section, row)
            if row.startswith("#"):
                code = "syntax.comment-row"
            elif section == "SHAPES":
                code = "syntax.shape"
        return Violation(code, section, line, shown(at))
    return Violation("cpp.rejected", None, None, text or "the reader rejects the file")


def _floats(values: list[Any]) -> np.ndarray:
    """The reader's values as float64; NaN for a value that the reader leaves unset (None)."""
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _table(name: str, rows: dict[int, dict], columns: dict[str, Any]) -> np.ndarray:
    """The table `name` of the model with one row for each event of `rows` (in ID order) and
    each column from `columns`: a key of the reader's event, or a function of the event."""
    out = np.zeros(len(rows), TABLE_DTYPES[name])
    events = list(rows.values())
    out["id"] = list(rows)
    for column, source in columns.items():
        values = [source(e) if callable(source) else e[source] for e in events]
        if out.dtype[column].kind == "f":
            out[column] = _floats(values)
        else:
            out[column] = values
    return out


def _text(value: bytes | str) -> str:
    return value.decode("utf-8", "surrogateescape") if isinstance(value, bytes) else value


def _text_table(name: str, rows: dict[int, dict], columns: dict[str, Any], text: str, key: str):
    """`_table` with the text column `text` from the reader's `key`, as wide as its longest
    value (at least 1)."""
    values = [_text(e[key]) for e in rows.values()]
    width = max([1, *map(len, values)])
    base = _table(name, rows, columns)
    dtype = np.dtype([(n, f"<U{width}" if n == text else base.dtype[n]) for n in base.dtype.names])
    out = np.zeros(len(rows), dtype)
    for n in base.dtype.names:
        if n != text:
            out[n] = base[n]
    out[text] = values
    return out


def _model(sequence: Any, interpreter: CppSiemens, written: AsWritten) -> SequenceData:
    """The model of a file that the reader read, from its libraries (P14)."""
    lib = sequence.libraries
    v15 = lib.version >= 1_005_000
    blocks = np.zeros(len(lib.blocks), TABLE_DTYPES["blocks"])
    blocks["id"] = np.arange(1, len(lib.blocks) + 1)
    for j, column in enumerate(("duration_ticks", "rf", "gx", "gy", "gz", "adc", "ext")):
        blocks[column] = lib.blocks[:, j]
    rf = _table(
        "rf",
        lib.rf,
        {
            "amplitude": "amplitude",
            "mag_id": "mag_shape",
            "phase_id": "phase_shape",
            "time_id": "time_shape",
            "center": (lambda e: e["center_us"] / _US) if v15 else (lambda e: None),
            "delay": lambda e: e["delay_us"] / _US,
            "freq_ppm": "freq_ppm",
            "phase_ppm": "phase_ppm",
            "freq_offset": "freq_offset",
            "phase_offset": "phase_offset",
        },
    )
    # The `use` of an RF event: the character that the reader holds, any character (D17).
    rf["use"] = [_text(e["use"])[:1] for e in lib.rf.values()]
    arbitrary = {i: e for i, e in lib.grad.items() if e["wave_shape"] != 0}
    trapezoids = {i: e for i, e in lib.grad.items() if e["wave_shape"] == 0}
    grad = _table(
        "grad",
        arbitrary,
        {
            "amplitude": "amplitude",
            "first": "first",
            "last": "last",
            "shape_id": "wave_shape",
            "time_id": "time_shape",
            "delay": lambda e: e["delay_us"] / _US,
        },
    )
    trap = _table(
        "trap",
        trapezoids,
        {
            "amplitude": "amplitude",
            "rise": lambda e: _us(e["ramp_up_us"]),
            "flat": lambda e: _us(e["flat_us"]),
            "fall": lambda e: _us(e["ramp_down_us"]),
            "delay": lambda e: e["delay_us"] / _US,
        },
    )
    adc = _table(
        "adc",
        lib.adc,
        {
            "num_samples": "num_samples",
            "dwell": lambda e: e["dwell_ns"] / _NS,
            "delay": lambda e: e["delay_us"] / _US,
            "freq_ppm": "freq_ppm",
            "phase_ppm": "phase_ppm",
            "freq_offset": "freq_offset",
            "phase_offset": "phase_offset",
            "phase_shape_id": "phase_shape",
        },
    )
    entries = np.zeros(len(lib.extension_list), TABLE_DTYPES["entries"])
    entries["id"] = list(lib.extension_list)
    for j, column in enumerate(("type", "ref", "next")):
        entries[column] = [e[j] for e in lib.extension_list.values()]
    names = {type_id: _text(name) for type_id, (name, _) in lib.extension_types.items()}
    extensions = Extensions(
        entries=entries,
        type_ids={name: type_id for type_id, name in names.items()},
        triggers=_table(
            "triggers",
            lib.triggers,
            {
                "type": "type",
                "channel": "channel",
                "delay": lambda e: e["delay_us"] / _US,
                "duration": lambda e: e["duration_us"] / _US,
            },
        ),
        labelset=_text_table("labelset", lib.labelset, {"value": "value"}, "name", "label"),
        labelinc=_text_table("labelinc", lib.labelinc, {"value": "value"}, "name", "label"),
        soft_delays=_text_table(
            "soft_delays",
            lib.soft_delays,
            {
                "num": "num_id",
                "offset": lambda e: e["offset_us"] / _US,
                "factor": "factor",
            },
            "hint",
            "hint",
        ),
        rotations=_rotations(lib.rotations),
        rf_shims={
            i: np.stack(
                [np.asarray(e["amplitudes"], np.float64), np.asarray(e["phases"], np.float64)],
                axis=1,
            ).reshape(-1, 2)
            for i, e in lib.rf_shims.items()
        },
    )
    definitions = {
        _text(key): tuple(_text(value).split()) for key, value in lib.definitions.items()
    }
    signature = lib.signature
    return SequenceData(
        version=tuple(lib.version_parts),
        definitions=definitions,
        rasters=Rasters(
            gradient=lib.gradient_raster_us / _US,
            rf=lib.rf_raster_us / _US,
            adc=lib.adc_raster_us / _US,
            block_duration=lib.block_raster_us / _US,
        ),
        required_extensions=definitions.get("RequiredExtensions", ()),
        blocks=blocks,
        rf=rf,
        grad=grad,
        trap=trap,
        adc=adc,
        shapes={
            i: Shape(s.num_samples, np.asarray(s.samples, dtype=np.float64))
            for i, s in lib.shapes.items()
        },
        extensions=extensions,
        # The reader keeps no trace of an extension that it does not know (D45): it ignores its
        # section. These are the STRING_IDs of those sections, as written.
        skipped_extensions=tuple(
            dict.fromkeys(
                s.extension[0]
                for s in written.extensions()
                if s.extension and s.extension[0] not in _KNOWN_EXT_TYPES
            )
        ),
        signature=Signature(
            type=_text(signature["type"]),
            hash=_text(signature["value"]),
            matches=bool(signature["ok"]),
        )
        if signature["defined"]
        else None,
        origin="file",
        interpreter=interpreter,
        reading=sequence,
    )


def _us(value: Any) -> float | None:
    return None if value is None else value / _US


def _rotations(rotations: dict[int, tuple[float, float, float, float]]) -> np.ndarray:
    out = np.zeros(len(rotations), TABLE_DTYPES["rotations"])
    out["id"] = list(rotations)
    for j, column in enumerate(("q0", "qx", "qy", "qz")):
        out[column] = [q[j] for q in rotations.values()]
    return out
