"""The `cpp-siemens` interpreter of pulseq-analysis: a Pulseq file as the C++ reader of the
scanner's interpreter on Siemens systems reads it (`ExternalSequence` of pulseq/pulseq at
`c7469123`), through this package. It is a plugin of pulseq-analysis (P21 of
`docs/plans/parser-redesign.md` in pulseq-analysis): this package gives the class `CppSiemens`
through the entry-point group `pulseq_analysis.interpreters`, so that
`pulseq_analysis.seqfile.read_seqfile(path, "cpp-siemens")` finds it, and pulseq-analysis does
not import this package. This module needs pulseq-analysis; the rest of the package does not.
`docs/specification.md` of this package gives what it does and why: the rule, and each exception.

- `CppSiemens`: the interpreter, with its settings (`oversampling`, `rotation`); its `read`
  gives the model (`SequenceData`), and its `decode(data, session)` the decoding
  (`CppSiemensDecoding`) under a scanner session (`pulseq_analysis.synth.Session`). It implements
  version 1 of the plugin protocol of pulseq-analysis (`protocol`, P22).
- `CODES`: the code of each rejection, with the ID of its condition (`docs/specification.md`).

`CppSiemens.read(path)` (`read_cpp_siemens`) reads a file in four steps:

1. **The version gate** (Q1 of the plan). `read_seqfile` of pulseq-analysis checks the scope
   before it calls `read`, for every interpreter (Q14 of `docs/plans/remaining-review-fixes.md`
   in pulseq-analysis): a folder, a binary Pulseq file, and a version outside 1.4.0 to 1.5.x in
   the "as written" reading (`as_written`, the first row of each key) raise `NotSupported`.
   `load` then reads the version again as the reader does (the reader takes the last row of each
   key), and refuses a version outside 1.4.0 to 1.5.x and a binary Pulseq file before the C++
   reader runs: `NotSupported` too.
2. **`ExternalSequence::load`**, then the checks of this package for the undefined
   behaviour of the reader (section 5.3 of the plan): a file with a case is a rejection, with a
   reason for each case and its `ub.*` code.
3. **`decodeBlock` of every block**, as the C++ oracle's first mode does. A block that it
   rejects rejects the file. No decoded block is kept.
4. **The model** (`model.SequenceData`) from the reader's own libraries (P14): the events,
   shapes, blocks, definitions and extensions as the reader read them, misreadings included.
   `SequenceData.reading` keeps the reader's object, for its libraries, `decode_block` and
   `gradients_at`.

**The rejections.** The reader gives a message, not a code. `CODES` gives each code of a
rejection, with the ID of its condition, and `_classify` finds it from the reader's
message, and where the message is not enough, from the "as written" reading. The reasons of a
`SeqFileError` of `cpp-siemens` are the code, the section and the line (where the message quotes
a row), and the reader's message. The reader stops at its first error, so a rejection by the
reader has one reason. A rejection for undefined behaviour has a reason for each case that the
checks find, in play order, at most `MAX_LOCATIONS` of `seqfile.spec` for each code, and
`omitted` counts the others, as for `spec`.

**The model from the libraries.** Where the reader holds a value, the model has it, in the units
of the model (s, Hz, Hz/m) from the reader's float32 values (P6), so a value can differ from the
file in the last digits of float32 (D7.2). Where the reader differs from `spec`:

- `blocks`: the reader keeps no block ID, so `id` is the position in play order, from 1. Play
  order is file order (D7.3).
- `rf`: a 1.4 event has `center` NaN (the reader holds -1, D7.5); `use` is the character that the
  reader holds, any character.
- `grad` and `trap`: the reader keeps `[GRADIENTS]` and `[TRAP]` in one library; a shape ID of 0
  is a trapezoid. `first` and `last` are the reader's values; NaN where it leaves them unset.
- `adc`: the dwell time is the integer that the reader reads.
- `definitions`: in the order of the keys (the reader keeps a sorted map), each value split at
  white space; a key defined twice has its last value (D2.6 in `spec`).
- `extensions`: `rotations` are the reader's quaternions, divided by their norm (D6.2; the rotation
  of each block, as `GetBlock` attaches it, is `reading.block_rotations()`);
  `skipped_extensions` the extensions that the reader does not know (D2.17 in `spec`).
- `records`: what the reader ignored (rule 4 of P20): an extension that it does not know
  (`"extension"`, reason `"unknown"`), and a row of LABELSET or LABELINC whose label
  `decodeLabel` does not know, which the reader leaves out (`"label"`, reason `"unknown"`): for
  example `NOSLC`, the specification's spelling of the reader's `NOSCL`, and `PMC` and `TRID`,
  which the reader ignores (D6.4).
- `signature`: `matches` is the reader's check of its MD5 hash.
"""

import dataclasses
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

import numpy as np

import pulseq_cpp_siemens as cs
from pulseq_analysis.seqfile.as_written import AsWritten, read_as_written
from pulseq_analysis.seqfile.errors import NotSupported, SeqFileError, Violation
from pulseq_analysis.seqfile.model import (
    TABLE_DTYPES,
    Extensions,
    Rasters,
    Record,
    SequenceData,
    Shape,
    Signature,
)
from pulseq_analysis.seqfile.spec import MAX_LOCATIONS
from pulseq_analysis.synth.decoding import Points
from pulseq_analysis.synth.scanner import (
    FovRecord,
    RotationRecord,
    Session,
    SoftDelay,
    block_physical_gradients,
    fov_flags,
    fov_record,
    pure_delay_blocks,
    rotation_rows,
    soft_delay_durations,
)
from pulseq_cpp_siemens import _checks

__all__ = [
    "CODES",
    "OVERSAMPLING",
    "ROTATION",
    "CppSiemens",
    "CppSiemensDecoding",
    "read_cpp_siemens",
]

OVERSAMPLING = cs.OVERSAMPLING

# What the `cpp-siemens` decoding does with the rotation of a block (the ROTATIONS extension,
# D6.2): the reader's own output, whose gradients are not rotated (the reader leaves the rotation
# to the scanner's interpreter), or the simulation of the scanner, which rotates them.
ROTATION = ("reader", "apply")


@dataclasses.dataclass(frozen=True, slots=True)
class CppSiemens:
    """The `cpp-siemens` interpreter: the C++ reader, with its settings (a plugin interpreter of
    pulseq-analysis, `pulseq_analysis.seqfile.interpreters.Plugin`). It reads what that reader
    reads and rejects what it rejects. It decodes every block of a file with the C++ reader,
    about six times as long as `spec`, so pulseq-analysis reads it by name.

    `oversampling` is the reader's mode for an oversampled arbitrary gradient (D6.1): `"center"`
    (the default, `SetArbGradCenterSampling(true)`) keeps the samples at the centres of the
    raster, `"edge"` (`SetArbGradCenterSampling(false)`) those at its edges, and `"preserve"`
    (`SetArbGradPreserveOversampling()`) all of them.

    `rotation` is what the decoding does with each block's rotation (D6.2): `"reader"` (the
    default) gives the reader's output, the logical gradients with the block's quaternion beside
    them (the reader never rotates them); `"apply"` rotates the gradients of each block to which
    the reader attached a rotation by its quaternion, with the reader's own
    `rotate_vec3_by_quat`, in any version of the file. `"apply"` is the simulation of the
    scanner: the scanner's behaviour for a file older than 1.5.1, the revision that defines the
    extension, is not known (the user, 2026-10-12). It is valid on a file with no rotation, and
    then rotates no block.

    The scanner session (`pulseq_analysis.synth.Session`) is not a setting: `decode(data,
    session)` applies it (P22). The soft delays of the session set the duration of each block with
    the reader's own hook `setActualSoftDelay_ru`, and the field of view turns the gradients with
    the reader's `rotate_vec3_by_quat`, in the order and with the flags of
    `pulseq_analysis.synth.scanner` (D6.3, D6.4 of `docs/specification.md`)."""

    name: ClassVar[str] = "cpp-siemens"
    # The version of the plugin protocol of pulseq-analysis (`seqfile.interpreters.PROTOCOL`).
    protocol: ClassVar[int] = 1
    oversampling: str = "center"
    rotation: str = "reader"

    def __post_init__(self) -> None:
        if self.oversampling not in OVERSAMPLING:
            raise ValueError(
                f"oversampling is {self.oversampling!r}, not one of {', '.join(OVERSAMPLING)}"
            )
        if self.rotation not in ROTATION:
            raise ValueError(f"rotation is {self.rotation!r}, not one of {', '.join(ROTATION)}")

    def __str__(self) -> str:
        """The name, with each setting that is not its default."""
        default = CppSiemens()
        settings = [
            f"{field}={getattr(self, field)!r}"
            for field in ("oversampling", "rotation")
            if getattr(self, field) != getattr(default, field)
        ]
        return f"{self.name}({', '.join(settings)})" if settings else self.name

    def read(self, path: str | Path) -> SequenceData:
        """`read_cpp_siemens(path, self)`."""
        return read_cpp_siemens(path, self)

    def decode(self, data: SequenceData, session: Session | None = None) -> "CppSiemensDecoding":
        """The decoding of `data`, a model that this interpreter read, under the scanner session
        `session` (the neutral one for None): `CppSiemensDecoding`. Raises
        `pulseq_analysis.synth.SettingError` for a setting of the session that addresses
        something that the reader did not attach to the file."""
        return CppSiemensDecoding(data, session)


# The codes of the rejections of `cpp-siemens`: each code, the ID of its entry ("—" for none: the
# reader rejects it and `cpp-siemens` follows the rule; section 2.5 of docs/specification.md), and
# what the reader rejects. The `ub.*` codes are those of the checks of this
# package (`pulseq_cpp_siemens.CODES`, section 5.3 of the plan).
CODES: MappingProxyType[str, tuple[str, str]] = MappingProxyType(
    {
        "version.missing": ("—", "the file has no [VERSION] section"),
        "version.invalid": ("—", "a line of [VERSION] does not decode, or has an unknown key"),
        "definitions.raster-missing": ("—", "a required raster is not defined"),
        "definitions.raster-invalid": (
            "—",
            "a required raster has no value that the reader reads",
        ),
        "definitions.skipped": (
            "—",
            "the reader skips [DEFINITIONS], after a section that it read to the end of the file",
        ),
        "extension.required-unknown": ("—", "a required extension is unknown to the reader"),
        "section.extensions-last": ("—", "[EXTENSIONS] is the last section of the file"),
        "blocks.missing": ("—", "the file has no [BLOCKS] section"),
        "syntax.row": ("—", "a row does not decode with the reader's sscanf format"),
        "syntax.comment-row": ("—", "a `#` line inside a table, which the reader reads as a row"),
        "syntax.shape": ("—", "a line of [SHAPES] does not decode"),
        "ref.unresolved": ("—", "a block names an event that the reader did not read"),
        "rotation.norm": ("—", "a quaternion's norm is more than 1e-3 from 1"),
        "gradient.raster": (
            "—",
            "an arbitrary gradient in a file whose gradient raster is not 10 us",
        ),
        "shape.decompression": ("—", "a shape whose compression the reader cannot decode"),
        "shape.ext-trap-lengths": (
            "—",
            "the time shape and the waveform of an extended trapezoid differ in length",
        ),
        "cpp.exception": ("—", "the reader throws a C++ exception"),
        "cpp.rejected": ("—", "the reader rejects the file for another reason"),
        "ub.shape-missing": ("D5.1", "a block uses a shape that the reader did not read"),
        "ub.rf-time-id-minus-1": ("D5.3", "an RF event with time ID -1"),
        "ub.extension-cycle": ("D5.4", "a cycle in an extension list"),
        "ub.shape-decompression": ("D5.5", "a shape decompresses past its buffer"),
        "ub.shape-empty": ("D5.6", "an event uses a shape with no sample"),
        "ub.rf-shape-lengths": ("D5.7", "an RF phase shape shorter than its magnitude"),
        "ub.rf-time-overrun": ("D5.8", "the RF resampling reads past the time shape"),
        "ub.rf-time-range": ("D5.9", "an RF time shape's last time does not fit an int"),
        "ub.gradient-time-range": ("D5.11", "an extended trapezoid time does not fit a long"),
        "ub.gradient-one-point": (
            "D5.10",
            "gradientsAt reads past an extended trapezoid of one point",
        ),
        "ub.gradient-shape-0": ("D5.2", "a [GRADIENTS] row of shape 0, which load leaves unset"),
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
# gradient raster other than 10 us (`gradient.raster`) has no message (`_classify`).
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


def read_cpp_siemens(path: str | Path, interpreter: CppSiemens | None = None) -> SequenceData:
    """Read the Pulseq text file `path` as the C++ reader reads it (the module docstring).

    `read_seqfile` of pulseq-analysis checks the scope before it calls this. Raises
    `NotSupported` when `load` refuses the file (the reader's version is outside 1.4.0 to 1.5.x,
    or a binary Pulseq file; the reader is not run), `SeqFileError` (a `ValueError`) with the code
    of `CODES` when the reader rejects the file, and `OSError` when the file cannot be read."""
    interpreter = interpreter or CppSiemens()
    path = Path(path)
    written = read_as_written(path)
    try:
        sequence = cs.load(written.raw, oversampling=interpreter.oversampling)
    except cs.NotSupported as error:
        raise NotSupported(f"{path}: {error}") from None
    except cs.UndefinedBehaviour as error:
        raise _undefined_behaviour(path, error.cases, interpreter) from None
    except cs.Rejected as error:
        reason = _classify(error.messages, written, None)
        raise SeqFileError(str(path), [reason], interpreter=interpreter.name) from None
    index = sequence.first_rejected_block()
    if index is not None:
        reason = _classify(sequence.rejection_messages, written, (sequence.libraries, index))
        raise SeqFileError(str(path), [reason], interpreter=interpreter.name)
    return _model(sequence, interpreter, written)


def _undefined_behaviour(
    path: Path, cases: tuple[_checks.Case, ...], interpreter: CppSiemens
) -> SeqFileError:
    """The rejection of a file with the cases of undefined behaviour `cases` (play order): a
    reason for each, at most `MAX_LOCATIONS` for each code, and the number of the others of each
    code (`SeqFileError.omitted`), as `spec` gives its violations."""
    counts: Counter[str] = Counter()
    reasons = []
    for case in cases:
        counts[case.code] += 1
        if counts[case.code] <= MAX_LOCATIONS:
            reasons.append(Violation(case.code, None, None, str(case)))
    omitted = {code: n - MAX_LOCATIONS for code, n in counts.items() if n > MAX_LOCATIONS}
    return SeqFileError(str(path), reasons, omitted, interpreter=interpreter.name)


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
    # The `use` of an RF event: the character that the reader holds, any character.
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
        # The reader keeps no trace of an extension that it does not know (D2.17 in `spec`): it
        # ignores its section. These are the STRING_IDs of those sections, as written.
        skipped_extensions=tuple(
            dict.fromkeys(
                s.extension[0]
                for s in written.extensions()
                if s.extension and s.extension[0] not in _KNOWN_EXT_TYPES
            )
        ),
        records=_records(lib, written),
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


def _records(lib: Any, written: AsWritten) -> tuple[Record, ...]:
    """What the reader ignored (the module docstring), in file order: each extension that it does
    not know, at the header of its first section, and each row of LABELSET or LABELINC that is not
    in the reader's library of that extension."""
    records: list[Record] = []
    seen: set[str] = set()
    for section in written.extensions():
        name = section.extension[0] if section.extension else None
        if name is None:
            continue
        if name not in _KNOWN_EXT_TYPES and name not in seen:
            seen.add(name)
            records.append(Record("extension", name, "unknown", section.line))
        if name not in ("LABELSET", "LABELINC"):
            continue
        library = lib.labelset if name == "LABELSET" else lib.labelinc
        for i in range(len(section.rows)):
            fields = section.rows.fields(i)
            try:
                kept = int(fields[0]) in library
            except (ValueError, IndexError):
                continue
            if not kept and len(fields) > 2:
                records.append(Record("label", fields[2], "unknown", int(section.rows.lines[i])))
    return tuple(sorted(records, key=lambda r: r.line))


def _us(value: Any) -> float | None:
    return None if value is None else value / _US


def _rotations(rotations: dict[int, tuple[float, float, float, float]]) -> np.ndarray:
    out = np.zeros(len(rotations), TABLE_DTYPES["rotations"])
    out["id"] = list(rotations)
    for j, column in enumerate(("q0", "qx", "qy", "qz")):
        out[column] = [q[j] for q in rotations.values()]
    return out


# A value that `CppSiemensDecoding` keeps (`gradient_variants`, and the rows of the rotations of
# `gradients_at`), before its first call.
_NOT_KEPT = object()


class CppSiemensDecoding:
    """The C++ reader's decoding of a file that `cpp-siemens` read (`CppSiemens.decode`), of the
    protocol `pulseq_analysis.synth.Decoding`: a view of `SequenceData.reading` (a `Sequence`).
    Blocks are indexed in play order from 0; the reader decodes each on request, and keeps it
    for `gradients_at`.

    These are the values that the reader gives, bit for bit: its float32 values, the
    resampling of RF pulses, the clamps of `checkRF` and `checkGradient`, the sampling mode of
    an oversampled gradient (the setting `oversampling`), and its misreadings. The reader gives
    each block's rotation (`rotations`) and applies it to nothing; with the setting
    `rotation="apply"`, `gradients_at` rotates the gradients of each block that has one, with
    the reader's own `rotate_vec3_by_quat` (the simulation of the scanner). `rotation_record`
    records what was applied.

    The scanner session (`session`, P22): the soft delays that it sets give the duration of their
    blocks through the reader's hook `setActualSoftDelay_ru` (`block_durations`; the shared rule
    of `pulseq_analysis.synth.scanner.soft_delay_durations`, on the soft delays as `GetBlock`
    attaches them, D6.3), and `gradients_at` ends each block there. The field of view of the
    session scales and turns the gradients in the order of `scanner.physical_gradients`, with the
    reader's `rotate_vec3_by_quat`; the flags are NOROT and `NOSCL`, as the reader keeps them
    (D6.4). `soft_delay_record` and `fov_record` record what was applied."""

    def __init__(self, data: SequenceData, session: Session | None = None) -> None:
        self.interpreter: CppSiemens = data.interpreter
        self.session = Session() if session is None else session
        self._reading = data.reading
        self._gradient_raster = data.rasters.gradient
        self._rotation_record: RotationRecord | None = None
        self._gradient_variants: Any = _NOT_KEPT
        # The row of the quaternions of `rotations` of each block (-1 for none), and the
        # quaternions, for `gradients_at`.
        self._rotation_rows: Any = _NOT_KEPT
        blocks = data.blocks
        stored = np.asarray(blocks["duration_ticks"], dtype=np.int64)
        found = self._reading.block_soft_delays()
        soft_delays = [
            SoftDelay(int(b), int(n), int(o) / _US, float(f), _text(h))
            for b, n, o, f, h in zip(*found, strict=True)
        ]
        ticks, self.soft_delay_record = soft_delay_durations(
            self.session,
            soft_delays,
            stored,
            data.rasters.block_duration,
            pure_delay_blocks(blocks),
            interpreter=self.interpreter.name,
            version=data.version,
        )
        given = {hint for hint, _ in self.session.soft_delays}
        hook = np.full(stored.size, -1, dtype=np.int64)
        for d in soft_delays:
            if d.hint in given:
                hook[d.block] = ticks[d.block]
        # The actual soft delay of each block for the reader's hook, or None for none.
        self._actual_ru = hook if (hook >= 0).any() else None
        actual = self._reading.block_durations_ru(hook) if self._actual_ru is not None else stored
        self.block_durations = _frozen(actual * data.rasters.block_duration)
        self.stored_block_durations = _frozen(stored * data.rasters.block_duration)
        indices, names, values = self._reading.block_label_sets()
        label_sets = list(zip(indices.tolist(), names, values.tolist(), strict=True))
        self._norot, self._noscale = (
            _frozen(a) for a in fov_flags(stored.size, label_sets, "NOSCL")
        )
        self.fov_record: FovRecord = fov_record(self.session, self._norot, self._noscale, "NOSCL")

    @property
    def block_count(self) -> int:
        return int(self._reading.block_count)

    def fov_flags(self) -> tuple[np.ndarray, np.ndarray]:
        """The flags NOROT and NOSCL of each block (`pulseq_analysis.synth.scanner.fov_flags`), from
        the LABELSET events that `GetBlock` attaches (`Sequence.block_label_sets`), as copies. The
        reader leaves out `NOSLC`, so it sets nothing (D6.4)."""
        return self._norot.copy(), self._noscale.copy()

    def block(self, index: int) -> dict[str, Any]:
        """`GetBlock` and `decodeBlock` of the block `index`: the fields of the C++ oracle's
        `--dump` (`tests/cpp_oracle/README.md` of pulseq-analysis), in the reader's units (us,
        Hz, Hz/m, rad), with the RF and gradient samples after the resampling and the clamps."""
        return self._reading.decode_block(index)

    def blocks(self) -> Iterator[dict[str, Any]]:
        """`block` of each block, in play order."""
        for index in range(self.block_count):
            yield self.block(index)

    def rotations(self) -> tuple[np.ndarray, np.ndarray]:
        """The rotation of each block, as the reader gives it: the play indices (from 0) of the
        blocks to which `GetBlock` attaches a rotation (the first of the block's extension list),
        and their quaternions, an array (n, 4) of q0, qx, qy and qz, as the reader divided them by
        their norm (D6.2). The same in each setting."""
        return self._reading.block_rotations()

    @property
    def rotation_record(self) -> RotationRecord:
        """What the decoding does with the rotations of the file (rule 4 of P20): the setting,
        the blocks with a rotation, those that are not the identity, and those rotated."""
        if self._rotation_record is None:
            indices, quaternions = self.rotations()
            setting = self.interpreter.rotation
            self._rotation_record = RotationRecord(
                setting=setting,
                blocks=int(indices.size),
                not_identity=int(np.count_nonzero(np.any(quaternions[:, 1:] != 0, axis=1))),
                rotated=int(indices.size) if setting == "apply" else 0,
                hint="use CppSiemens(rotation='apply') for the gradients that the scanner plays",
            )
        return self._rotation_record

    def gradients_at(
        self, block_index: Any, time_us: Any, rotated: bool | None = None
    ) -> np.ndarray:
        """`SeqBlock::gradientsAt` (Hz/m) at each pair of a block index and a time in us from the
        start of that block: an array (n, 3) of gx, gy and gz (0 before and after the block, at
        its actual duration: the reader's hook `setActualSoftDelay_ru` with the session's soft
        delays).

        `rotated` None follows the interpreter's setting `rotation` and the session's field of
        view. False gives the values as the reader gives them, the logical gradients. True turns
        the values of each block with a rotation (`rotations`) by its quaternion, with the
        reader's `rotate_vec3_by_quat`: the gradients that the scanner plays when it applies the
        rotation, and applies the field of view too. The field of view scales the logical axes of
        each block without NOSCL before the block's rotation, and turns each block without NOROT
        after it (`pulseq_analysis.synth.scanner.block_physical_gradients`)."""
        rotate_blocks = self.interpreter.rotation == "apply" if rotated is None else rotated
        session = self.session
        if (rotated is not None and not rotated) or not (session.rotates or session.scales):
            return self._reading.gradients_at(
                block_index, time_us, rotated=rotate_blocks, actual_ru=self._actual_ru
            )
        block_index = np.asarray(block_index, dtype=np.int64).reshape(-1)
        logical = self._reading.gradients_at(
            block_index, time_us, rotated=False, actual_ru=self._actual_ru
        )
        rows = table = None
        if rotate_blocks:
            if self._rotation_rows is _NOT_KEPT:
                indices, quaternions = self.rotations()
                self._rotation_rows = rotation_rows(self.block_count, indices), _frozen(quaternions)
            rows, table = self._rotation_rows
        return block_physical_gradients(
            logical,
            session,
            block_index,
            self._norot,
            self._noscale,
            cs.rotate_vec3_by_quat,
            rows,
            table,
        )

    def gradient_points(self, key: int, block: int, axis: int) -> Points:
        """The points of the gradient event that the block `block` plays on the axis `axis`
        (`key` is its file ID; the reader decodes the gradients of a block together, so the
        points of an event can depend on the block: `gradient_variants`), as the reader decoded
        it (not rotated): those between which `SeqBlock::gradientsAt` draws its straight lines
        (cpp:3558-3690), in the layout of
        `pulseq_analysis.synth.seq_utils.gradient_offsets`. The values are those that
        `gradientsAt` gives at the points: the amplitude (a float32) times each sample of a
        shape in float32, and 0 everywhere when the amplitude is 0 or when the reader keeps no
        sample of an arbitrary gradient (an oversampled one of 1 or 2 samples in the mode
        "edge")."""
        return _points(self.block(block)["grad"][axis], self._gradient_raster)

    def gradient_variants(self) -> np.ndarray | None:
        """Which cells (a block and an axis) decode their gradient event alike
        (`pulseq_analysis.synth.Decoding.gradient_variants`), from the libraries that `load` read,
        with no block decoded. The result is kept.

        `decodeArbGradInBlock` decompresses the wave shapes of the arbitrary gradients of a block
        into one buffer, in the order gx, gy, gz, and `decodeExtTrapGradInBlock` the time shape
        and then the wave shape of each extended trapezoid into another (cpp:2094-2196). A shape
        whose decompression does not write each of its samples (`_checks._writes_every_sample`)
        keeps the values that the buffer holds (`_checks._decompress_into`). So an arbitrary
        gradient whose wave shape does so, and an extended trapezoid whose time shape does so,
        depend on the events on the earlier axes of the block; the wave shape of an extended
        trapezoid follows its own time shape. The variant of each cell of such an event is 1
        plus the number of the events on the earlier axes of its block (`np.unique`), and every
        other cell has 0. The events of every kind count, so two blocks can have two variants
        where the reader decodes alike. None when no cell depends on its block; otherwise an
        int64 array (blocks, 3), read-only."""
        if self._gradient_variants is _NOT_KEPT:
            self._gradient_variants = _gradient_variants(self._reading.libraries)
        return self._gradient_variants


def _depends_on_its_block(libraries: cs.Libraries, grad_id: int) -> bool:
    """Whether the reader's decoding of the gradient event `grad_id` depends on the shapes that
    it decompressed before it in the block (`CppSiemensDecoding.gradient_variants`). A shape whose
    decompression is not "ok" makes `decodeBlock` reject the block, so it has no decoding."""
    grad = libraries.grad[grad_id]
    wave, time = grad["wave_shape"], grad["time_shape"]
    if wave == 0:
        return False  # a trapezoid
    shape = libraries.shapes.get(time if time > 0 else wave)
    if shape is None or shape.num_samples <= 0:
        return False
    if _checks._decompression(*shape)[0] != "ok":
        return False
    return not _checks._writes_every_sample(*shape)


def _gradient_variants(libraries: cs.Libraries) -> np.ndarray | None:
    """`CppSiemensDecoding.gradient_variants` of the libraries that `load` read."""
    cells = np.asarray(libraries.blocks[:, 2:5], dtype=np.int64)  # gx, gy, gz
    events = np.unique(cells[cells > 0]).tolist()
    dependent = np.isin(cells, [e for e in events if _depends_on_its_block(libraries, e)])
    if not dependent.any():
        return None
    # The events on the earlier axes of each cell, with -1 for the axis itself and those after.
    earlier = np.stack([np.where(np.arange(3) < axis, cells, -1) for axis in range(3)], axis=1)
    _, number = np.unique(earlier[dependent], axis=0, return_inverse=True)
    variants = np.zeros(cells.shape, dtype=np.int64)
    variants[dependent] = number.reshape(-1) + 1
    variants.flags.writeable = False
    return variants


def _frozen(a: np.ndarray) -> np.ndarray:
    """`a` as a read-only array."""
    a = np.array(a)
    a.flags.writeable = False
    return a


def _points(grad: Mapping[str, Any], raster_s: float) -> Points:
    """`CppSiemensDecoding.gradient_points` of a `grad` entry of `CppSiemensDecoding.block`, with
    `raster_s` the gradient raster of the file (s)."""
    # A time in us divided by 1e6, as the model gives it.
    delay = grad["delay_us"] / 1e6
    amplitude = np.float32(grad["amplitude"])
    kind = grad["kind"]
    if kind == "trap":
        offsets = np.cumsum(
            [0.0, grad["ramp_up_us"] / 1e6, grad["flat_us"] / 1e6, grad["ramp_down_us"] / 1e6]
        )
        amp = np.array([0.0, amplitude, amplitude, 0.0], dtype=np.float64)
    elif kind == "ext_trap":
        times_us = np.asarray(grad["times_us"], dtype=np.float64)
        shape = np.asarray(grad["shape"], dtype=np.float32)
        times = times_us / 1e6
        values = (shape * amplitude).astype(np.float64)
        first = values[0]
        if times_us[0] > 0 and times_us.size > 1:
            # Between the delay and the first time, `gradientsAt` carries the first segment
            # backwards (its binary search, cpp:3634-3645; D4.5 in `spec`): the value at the
            # delay.
            t1, t2, v1, v2 = times_us[0], times_us[1], float(shape[0]), float(shape[1])
            first = (v1 * (t2 - 0.0) + v2 * (0.0 - t1)) / (t2 - t1) * float(amplitude)
        # The layout of `gradient_offsets`: the value at the delay, the vertices, and the value
        # at the end.
        offsets = np.concatenate([[0.0], times, times[-1:]])
        amp = np.concatenate([[first], values, values[-1:]])
    else:  # arbitrary: the samples at the centres of the raster, `first` and `last` at its edges
        samples = np.asarray(grad["samples"], dtype=np.float32)
        n = samples.size
        offsets = np.concatenate([[0.0], (np.arange(n) + 0.5) * raster_s, [n * raster_s]])
        amp = np.concatenate(
            [[grad["first"]], (samples * amplitude).astype(np.float64), [grad["last"]]]
        )
        if n == 0:
            # No sample kept (an oversampled gradient of 1 or 2 samples in the mode "edge",
            # D6.1): `gradientsAt` gives 0 before the delay and after it, and returns early at it
            # (cpp:3653-3678), so `first` and `last` are never played.
            amp = np.zeros_like(amp)
    if amplitude == 0:
        amp = np.zeros_like(amp)
    return delay, offsets, amp
