"""A strict reader of Pulseq text files, versions 1.4.0 to 1.5.x, into the model of layer 1.

`read_seqfile(path)` reads a file and returns a `model.SequenceData`, or raises `SeqFileError`
(a `ValueError`) when the file breaks a rule. The error has all the violations, each a
`Violation(rule, section, line, message)`, so a caller can show each kind. The parser lists at
most `MAX_LOCATIONS` violations for each rule and counts the rest (`SeqFileError.omitted`). It
does not import pypulseq, it uses no default for a value that the file must define, and it does
not round a number or renumber an ID (a time is converted to seconds). The binary format is not
read.

The parser reads the file as text (UTF-8) and splits it at the section headers (`[NAME]` and
`extension STRING_ID type`). Blank lines and lines that start with `#` are allowed between
sections. Inside a section they end it, as in the MATLAB Pulseq reader `read.m` (the spec is
silent; the reference implementation decides). A line is blank when it has only white space, and
a comment when its first non-blank character is `#` (`read.m` tests the first character of the
line itself). A data line after the end of a section and before the next header is `syntax.line`.
What `read.m` does, by line:

- `[VERSION]`: `readVersion` (lines 471 to 492) reads with `fgetl` from the line after the header,
  and stops at an empty line or a `#` line (line 480). A comment right after the header gives an
  empty section.
- `[DEFINITIONS]` and `[SIGNATURE]`: `readDefinitions` (lines 452 to 469) skips blank and `#`
  lines before the first line (`skipComments`, line 460, defined at lines 675 to 700), then stops
  at an empty line or a `#` line (line 461). So a comment before `Type`, as in the example of the
  spec, is read, and a comment between `Type` and `Hash` ends the section.
- `[BLOCKS]` (`readBlocks`, lines 502 to 503), `[RF]`, `[GRADIENTS]`, `[TRAP]`, `[ADC]`,
  `[EXTENSIONS]`, `extension TRIGGERS` and `extension ROTATIONS` (`readEvents`, lines 563 to 564),
  the other `extension` tables (`readAndParseEvents`, lines 605 to 606), and an unknown extension
  (`skipSection`, lines 632 to 633): `fgetl` from the line after the header, and stop at an empty
  line or a `#` line. A comment right after the header gives an empty table.
- `[SHAPES]` (`readShapes`, lines 638 to 673): `shape_id`, `num_samples` and the first sample are
  read after `skipComments` (lines 644, 648, 652), the other samples up to an empty line or a `#`
  line (line 653), then blank and `#` lines are skipped up to the next line (line 659). Here a
  `#` line ends a shape like a blank line (spec 2.9: a blank line ends a shape). This reader is
  stricter than `read.m` where `read.m` skips lines: a blank or `#` line between `shape_id` and
  `num_samples`, or before the first sample, is `syntax.shape`.

After a section ends, `read.m` reads the next non-comment line as a section header, so a data
line there is its error "Unknown section code". This reader reports `syntax.line` for it. Each table is read with `numpy.loadtxt` and a
structured dtype, after a check of the characters of the section. If that fails, a slower reader
finds every bad row. When the file has a violation, the parser still reads the other tables, so
the error has all of them, but a check that needs a table with a violation is skipped.

The rules, with their source. "Spec" is the Pulseq specification (1.5.3 draft, and 1.4.1 where it
agrees), by section number; where its prose contradicts its tables and examples (the number of
columns of `[RF]`, `[GRADIENTS]` and `[ADC]`, the names of the shape lines), the tables and the
examples decide. "read.m" is the MATLAB Pulseq reader. "Added" is a rule that the specification
does not state, and that the model needs to be defined.

- `version.missing`: no `[VERSION]` section (spec 2.3 recommends to reject the file; layer 1
  needs the version). `version.invalid`: a line of `[VERSION]` is not `major`, `minor` or
  `revision` with one integer, or a key is missing or repeated (spec 2.3). `version.unsupported`:
  the version is not 1.4.0 up to, not including, 1.6.0.
- `definitions.raster-missing`, `definitions.raster-invalid`: each of `GradientRasterTime`,
  `RadiofrequencyRasterTime`, `AdcRasterTime` and `BlockDurationRaster` is defined, with one
  finite number above 0 (spec 2.5, required from 1.4.0). `definitions.duplicate` (added): a key
  of `[DEFINITIONS]` appears twice.
- `section.unknown`: a section other than `[VERSION]`, `[DEFINITIONS]`, `[BLOCKS]`, `[RF]`,
  `[GRADIENTS]`, `[TRAP]`, `[ADC]`, `[EXTENSIONS]`, `[SHAPES]` and `[SIGNATURE]` (spec 2.3 to
  2.9; the `extension` sections are read as extensions). `section.delays`: a
  `[DELAYS]` section in a file of 1.4.0 or later (read.m: the file "MUST NOT" have it).
  `section.duplicate` (added): two sections, or two `extension` sections with one STRING_ID,
  have one name.
- `syntax.encoding` (added): the file is not UTF-8. `syntax.line` (added): a line outside any
  section: before the first header, or after a blank or `#` line that ended its section. `syntax.columns`: a row has not the number of columns of its table for the version
  (spec 2.7, 2.8). `syntax.integer`, `syntax.number`: a value that the spec types as integer
  or float is not one, or a float is not finite. `syntax.use`: the `use` of an RF event is not
  one of `e r i s p o u` (spec 2.8.1). `syntax.negative` (added): a duration, a delay, a rise,
  flat or fall time, a number of samples or a dwell time is negative. `syntax.shape` (added): a
  shape without its `shape_id` and `num_samples` lines, with samples outside a shape, or a
  `shape_id` line right after the samples of a shape with no blank line between (spec 2.9: a blank
  line ends a shape; the shape before it is still read).
- `id.positive`, `id.unique`: IDs are positive, and unique within a class (spec 2.2).
  `id.gradient-unique`: `[GRADIENTS]` and `[TRAP]` share one ID space (spec 2.2, 2.8.2).
- `ref.unresolved`: an event, shape, time shape or extension that a block or an event names is
  defined; a list of extensions ends and has no cycle (implied by the format; spec 2.2, 2.8.4).
  The time ID -1 is valid from 1.5.0 and for a gradient only (spec 2.8.2 defines it for
  gradients).
- `blocks.empty`: the file has a block (spec 2.7). `blocks.order` (added): block IDs increase
  through the file, so the order of the file and the order of the IDs are one play order (MATLAB
  Pulseq plays the blocks by ID; this reader plays them in file order). A block ID that is used
  twice is `id.unique` only.
- `block.event-too-long`: no event lasts longer than its block (spec 2.7). The end of an event
  is its delay plus its duration (gradient, RF without dead or ringdown time, ADC, trigger).
- `raster.adc-dwell`: the dwell time is a multiple of `AdcRasterTime` (spec 2.5, 2.8.3).
  `raster.gradient-delay`, `raster.gradient-end`, `raster.gradient-ramp`, `raster.gradient-flat`:
  a gradient starts and ends on `GradientRasterTime`, and the rise, fall and flat times of a
  trapezoid are multiples of it (spec 2.6). Times are compared in nanoseconds, with a tolerance
  of 1 ps (`TOLERANCE_NS`).
- `gradient.nonzero-start-delay`: a gradient that starts above 0 has delay 0.
  `gradient.nonzero-end-align`: a gradient that ends above 0 ends at the end of its block (spec
  2.8.2).
- `shape.length`: a shape has the number of samples that it declares after decompression (spec
  2.9). A shape that declares more than 2**27 samples is also reported under this rule. `shape.range`: an amplitude shape (RF magnitude, gradient waveform) is in [-1, 1]
  (spec 2.9), within `RANGE_TOLERANCE`. `shape.event-length` (added): the shapes of one event
  have one number of samples (`Sequence.m` of MATLAB Pulseq asserts it for a gradient and
  multiplies the RF magnitude by the phase).
- `extension.required-unknown`: from 1.5.1, every STRING_ID in `RequiredExtensions` is one that
  the parser knows (spec 2.8.4). `extension.per-block`: at most one ROTATIONS and one RF_SHIMS
  object for each block (spec 2.8.4; the spec says "can", the parser enforces it).
- `layer1.gradient-ends`: a 1.4.x file has no arbitrary gradient with time ID 0, because the
  file does not define its values at the two ends.
- `signature.invalid`: `[SIGNATURE]` has not exactly one `Type` and one `Hash` (spec 2.4). A hash
  that does not match is not a violation: `SequenceData.signature.matches` reports it.

`RULES` maps each ID to a short text.
"""

import dataclasses
import hashlib
import io
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

import numpy as np

from .model import (
    TABLE_DTYPES,
    Extensions,
    Rasters,
    SequenceData,
    Shape,
    Signature,
    decompress_shape,
)

# The most violations of one rule that an error lists.
MAX_LOCATIONS = 20

# A time is a multiple of a raster to within this many nanoseconds (1 ps). The times of the file
# are integer microseconds, so the comparison of a time with a raster is exact in nanoseconds
# except for the float dwell time of an ADC.
TOLERANCE_NS = 1e-3

# An amplitude shape may exceed 1 in absolute value by this much. The largest excess in the oracle
# files (`tests/seqfiles/oracle`) is 1.3e-15 (rounding of the sum). MATLAB Pulseq writes a sample
# with 9 significant digits (`write.m`), so a sample of 1 can be off by 5e-10 in a file whose
# writer does not quantize the shape first, and the tolerance is the next power of ten.
RANGE_TOLERANCE = 1e-9

RULES: Mapping[str, str] = MappingProxyType(
    {
        "version.missing": "no [VERSION] section",
        "version.invalid": "a line of [VERSION] is wrong, or a key is missing or repeated",
        "version.unsupported": "the version is not 1.4.0 to 1.5.x",
        "definitions.raster-missing": "a required raster is not defined",
        "definitions.raster-invalid": "a raster is not one finite number above 0",
        "definitions.duplicate": "a definition appears twice",
        "section.unknown": "a section that the format does not have",
        "section.delays": "a [DELAYS] section in a file of 1.4.0 or later",
        "section.duplicate": "a section appears twice",
        "syntax.encoding": "the file is not UTF-8",
        "syntax.line": "a line outside a section: before the first, or after the section ended",
        "syntax.columns": "a row has the wrong number of columns",
        "syntax.integer": "a value that must be an integer is not",
        "syntax.number": "a value that must be a finite number is not",
        "syntax.use": "the use of an RF event is not one of e r i s p o u",
        "syntax.negative": "a duration, delay or count is negative",
        "syntax.shape": "a shape is not well formed",
        "id.positive": "an ID is not positive",
        "id.unique": "an ID is used twice in one class",
        "id.gradient-unique": "a gradient ID is in [GRADIENTS] and in [TRAP]",
        "ref.unresolved": "a reference names something that is not defined",
        "blocks.empty": "the file has no block",
        "blocks.order": "block IDs do not increase through the file",
        "block.event-too-long": "an event lasts longer than its block",
        "raster.adc-dwell": "an ADC dwell time is not a multiple of AdcRasterTime",
        "raster.gradient-delay": "a gradient starts off the gradient raster",
        "raster.gradient-end": "an arbitrary gradient ends off the gradient raster",
        "raster.gradient-ramp": "a rise or fall time is not a multiple of the gradient raster",
        "raster.gradient-flat": "a flat time is not a multiple of the gradient raster",
        "gradient.nonzero-start-delay": "a gradient that starts above 0 has a delay",
        "gradient.nonzero-end-align": "a gradient that ends above 0 does not end with its block",
        "shape.length": "a shape does not have the samples that it declares",
        "shape.range": "an amplitude shape is outside [-1, 1]",
        "shape.event-length": "the shapes of one event have different numbers of samples",
        "extension.required-unknown": "a required extension is not known",
        "extension.per-block": "a block has more than one ROTATIONS or RF_SHIMS object",
        "layer1.gradient-ends": "a 1.4.x gradient on the default raster has no end values",
        "signature.invalid": "[SIGNATURE] has not one Type and one Hash",
    }
)

_MIN_VERSION, _MAX_VERSION = (1, 4, 0), (1, 6, 0)
_SECTIONS = (
    "VERSION",
    "DEFINITIONS",
    "BLOCKS",
    "RF",
    "GRADIENTS",
    "TRAP",
    "ADC",
    "DELAYS",
    "SHAPES",
    "EXTENSIONS",
    "SIGNATURE",
)
_RASTERS = (
    ("GradientRasterTime", "gradient"),
    ("RadiofrequencyRasterTime", "rf"),
    ("AdcRasterTime", "adc"),
    ("BlockDurationRaster", "block_duration"),
)
# A shape of more samples is not decompressed: a short file can declare any number of samples.
_MAX_SHAPE_SAMPLES = 2**27
_KNOWN_EXTENSIONS = ("TRIGGERS", "LABELSET", "LABELINC", "DELAYS", "RF_SHIMS", "ROTATIONS")
_USES = "erispou"
_US, _NS = 1e6, 1e9  # microseconds and nanoseconds in a second

_INTEGER = re.compile(r"-?[0-9]+")
_NUMBER = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")

# The columns of each table: (name, kind). Kinds: i integer, f float, u the `use` character,
# t text. The times are in the unit of the file here (us, and ns for the ADC dwell) and are
# converted to seconds when the model is made.
_BLOCKS = tuple((n, "i") for n in ("id", "duration_ticks", "rf", "gx", "gy", "gz", "adc", "ext"))
_RF_15 = (
    ("id", "i"),
    ("amplitude", "f"),
    ("mag_id", "i"),
    ("phase_id", "i"),
    ("time_id", "i"),
    ("center", "f"),
    ("delay", "i"),
    ("freq_ppm", "f"),
    ("phase_ppm", "f"),
    ("freq_offset", "f"),
    ("phase_offset", "f"),
    ("use", "u"),
)
_RF_14 = (
    ("id", "i"),
    ("amplitude", "f"),
    ("mag_id", "i"),
    ("phase_id", "i"),
    ("time_id", "i"),
    ("delay", "i"),
    ("freq_offset", "f"),
    ("phase_offset", "f"),
)
_GRAD_15 = (
    ("id", "i"),
    ("amplitude", "f"),
    ("first", "f"),
    ("last", "f"),
    ("shape_id", "i"),
    ("time_id", "i"),
    ("delay", "i"),
)
_GRAD_14 = (
    ("id", "i"),
    ("amplitude", "f"),
    ("shape_id", "i"),
    ("time_id", "i"),
    ("delay", "i"),
)
_TRAP = (
    ("id", "i"),
    ("amplitude", "f"),
    ("rise", "i"),
    ("flat", "i"),
    ("fall", "i"),
    ("delay", "i"),
)
_ADC_15 = (
    ("id", "i"),
    ("num_samples", "i"),
    ("dwell", "f"),
    ("delay", "i"),
    ("freq_ppm", "f"),
    ("phase_ppm", "f"),
    ("freq_offset", "f"),
    ("phase_offset", "f"),
    ("phase_shape_id", "i"),
)
_ADC_14 = (
    ("id", "i"),
    ("num_samples", "i"),
    ("dwell", "f"),
    ("delay", "i"),
    ("freq_offset", "f"),
    ("phase_offset", "f"),
)
_ENTRIES = tuple((n, "i") for n in ("id", "type", "ref", "next"))
_TRIGGERS = (("id", "i"), ("type", "i"), ("channel", "i"), ("delay", "i"), ("duration", "i"))
_LABELS = (("id", "i"), ("value", "i"), ("name", "t"))
_SOFT_DELAYS = (("id", "i"), ("num", "i"), ("offset", "f"), ("factor", "f"), ("hint", "t"))
_ROTATIONS = (("id", "i"), ("q0", "f"), ("qx", "f"), ("qy", "f"), ("qz", "f"))

# The columns that are never negative.
_NON_NEGATIVE = {
    "duration_ticks",
    "delay",
    "rise",
    "flat",
    "fall",
    "num_samples",
    "dwell",
    "duration",
}


@dataclasses.dataclass(frozen=True, slots=True)
class Violation:
    """One place where a file breaks a rule.

    `rule` is the ID of `RULES`, `section` is the section (`BLOCKS`, `extension ROTATIONS`) or
    `None` for the file, `line` is the line number in the file (from 1) or `None`, and `message`
    says what is wrong.
    """

    rule: str
    section: str | None
    line: int | None
    message: str


class SeqFileError(ValueError):
    """A file breaks a rule of the format. `violations` has all of them, at most
    `MAX_LOCATIONS` for each rule, in the order of the file. `omitted` maps a rule to the number
    of its further violations that are not in `violations`. `path` is the file."""

    def __init__(
        self,
        path: str,
        violations: Sequence[Violation],
        omitted: Mapping[str, int] | None = None,
    ):
        self.path = path
        self.violations = tuple(violations)
        self.omitted = MappingProxyType(dict(omitted or {}))
        total = len(self.violations) + sum(self.omitted.values())
        shown = [
            f"  {v.rule} ({v.section or 'file'}"
            + (f", line {v.line}" if v.line is not None else "")
            + f"): {v.message}"
            for v in self.violations[:10]
        ]
        if total > len(shown):
            shown.append(f"  and {total - len(shown)} more (see the `violations` attribute)")
        super().__init__(
            f"{path} has {total} violation(s) of the rules of the Pulseq format:\n"
            + "\n".join(shown)
        )

    def __reduce__(self) -> tuple[Any, ...]:
        return (SeqFileError, (self.path, self.violations, dict(self.omitted)))


class _Report:
    """The violations of one file, at most `MAX_LOCATIONS` for each rule."""

    def __init__(self) -> None:
        self.kept: list[Violation] = []
        self.counts: Counter[str] = Counter()

    def __bool__(self) -> bool:
        return any(self.counts.values())

    def add(self, rule: str, section: str | None, line: int | None, message: str) -> None:
        self.counts[rule] += 1
        if self.counts[rule] <= MAX_LOCATIONS:
            self.kept.append(Violation(rule, section, line, message))

    def rows(
        self, rule: str, table: "_Table", rows: np.ndarray, message: Callable[[int], str]
    ) -> None:
        """Add a violation for each row index of `rows` of `table`."""
        room = max(0, MAX_LOCATIONS - self.counts[rule])
        for row in rows[:room].tolist():
            self.add(rule, table.section, int(table.nums[row]), message(row))
        if len(rows) > room:
            self.counts[rule] += len(rows) - room

    def error(self, path: str) -> SeqFileError:
        kept = sorted(self.kept, key=lambda v: (v.line or 0, v.rule))
        omitted = {rule: n - MAX_LOCATIONS for rule, n in self.counts.items() if n > MAX_LOCATIONS}
        return SeqFileError(path, kept, omitted)


class _Section(NamedTuple):
    name: str  # for `extension`: "extension STRING_ID"
    line: int  # the line of the header
    lines: list[str]  # the stripped lines of the body; "" (a blank line) only in SHAPES
    nums: list[int]  # the line number of each line
    args: tuple[str, ...]  # for `extension`: (STRING_ID, type)


class _Table(NamedTuple):
    """The rows of a table and the line number of each row."""

    data: np.ndarray
    nums: np.ndarray
    section: str


class _Ids:
    """The IDs of a table, for the lookup of references."""

    def __init__(self, ids: np.ndarray):
        self.order = np.argsort(ids, kind="stable")
        self.sorted = ids[self.order]

    def find(self, refs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(row, found) of each reference of `refs`: the row of the table that has that ID
        (any row if the ID is used twice), and whether there is one."""
        if self.sorted.size == 0:
            return np.zeros(len(refs), np.int64), np.zeros(len(refs), bool)
        pos = np.minimum(np.searchsorted(self.sorted, refs), self.sorted.size - 1)
        return self.order[pos], self.sorted[pos] == refs


def read_seqfile(path: str | Path) -> SequenceData:
    """Read the Pulseq text file `path` (versions 1.4.0 to 1.5.x) into a `SequenceData`.

    Raises `SeqFileError` (a `ValueError`) with all the violations when the file breaks a rule
    (see the module docstring), and `OSError` when the file cannot be read.
    """
    raw = Path(path).read_bytes()
    report = _Report()
    data = _build(raw, report)
    if report or data is None:
        raise report.error(str(path))
    return data


def _decode(raw: bytes, report: _Report) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        line = raw.count(b"\n", 0, error.start) + 1
        report.add("syntax.encoding", None, line, f"byte {error.start} is not UTF-8")
        return None


def _split(text: str, report: _Report) -> tuple[dict[str, list[_Section]], list[_Section]]:
    """The sections of `text`: by name for the named ones, and the `extension` sections in
    file order. Reports an unknown section and a line outside any section.

    A section ends at a blank line or a line that starts with `#` (the module docstring has the
    lines of `read.m`). A data line after that and before the next header is `syntax.line` and is
    dropped. `[DEFINITIONS]` and `[SIGNATURE]` skip such lines before their first line. In
    `[SHAPES]` both kinds of line are kept as blank lines, which end a shape."""
    named: dict[str, list[_Section]] = {}
    extensions: list[_Section] = []
    lines: list[str] = []
    nums: list[int] = []
    keep_blank = False  # [SHAPES]: blank and comment lines end a shape
    skip_leading = False  # [DEFINITIONS], [SIGNATURE]
    check_end = False  # a data line after the end of the section is a violation
    ended = False
    where = ""  # the section name of the violations
    started = False
    for n, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s or s[0] == "#":
            if keep_blank:
                lines.append("")
                nums.append(n)
            elif started and not (skip_leading and not lines):
                ended = True
            continue
        c = s[0]
        is_extension = c == "e" and s.startswith("extension") and (len(s) == 9 or s[9] in " \t")
        if c == "[" or is_extension:
            started = True
            ended = False
            if is_extension:
                args = tuple(s.split()[1:])
                section = _Section(f"extension {args[0] if args else ''}".rstrip(), n, [], [], args)
                extensions.append(section)
                name = section.name
            else:
                name = s[1:-1] if s.endswith("]") else None
                if name is None or name not in _SECTIONS:
                    report.add("section.unknown", None, n, f"{s!r} is not a section of the format")
                    name = ""
                section = _Section(name, n, [], [], ())
                if name:
                    named.setdefault(name, []).append(section)
            keep_blank = name == "SHAPES"
            skip_leading = name in ("DEFINITIONS", "SIGNATURE")
            check_end = bool(name)
            where = name
            lines, nums = section.lines, section.nums
            continue
        if not started:
            report.add("syntax.line", None, n, "this line is outside any section")
            continue
        if ended and check_end:
            report.add(
                "syntax.line",
                where,
                n,
                f"this line follows a blank or # line, which ends the section {where}",
            )
            continue
        lines.append(s)
        nums.append(n)
    return named, extensions


def _one(named: dict[str, list[_Section]], name: str, report: _Report) -> _Section | None:
    """The section `name`, or None. Reports a second section with the same name."""
    sections = named.get(name, [])
    for extra in sections[1:]:
        report.add("section.duplicate", name, extra.line, f"[{name}] appears twice")
    return sections[0] if sections else None


def _read_version(section: _Section | None, report: _Report) -> tuple[int, int, int] | None:
    if section is None:
        report.add("version.missing", None, None, "the file has no [VERSION] section")
        return None
    values: dict[str, int] = {}
    for s, n in zip(section.lines, section.nums, strict=True):
        tokens = s.split()
        if (
            len(tokens) != 2
            or tokens[0] not in ("major", "minor", "revision")
            or _cell("i", tokens[1]) is None
            or tokens[0] in values
        ):
            report.add(
                "version.invalid",
                "VERSION",
                n,
                f"{s!r} is not a `major`, `minor` or `revision` line with one integer, "
                "or it repeats one",
            )
        else:
            values[tokens[0]] = int(tokens[1])
    missing = [k for k in ("major", "minor", "revision") if k not in values]
    if missing:
        report.add("version.invalid", "VERSION", section.line, f"{', '.join(missing)} missing")
        return None
    version = (values["major"], values["minor"], values["revision"])
    if not _MIN_VERSION <= version < _MAX_VERSION:
        name = ".".join(map(str, version))
        report.add(
            "version.unsupported",
            "VERSION",
            section.line,
            f"version {name} is not supported: this reader reads 1.4.0 to 1.5.x",
        )
        return None
    return version


def _read_definitions(
    section: _Section | None, report: _Report, name: str = "DEFINITIONS"
) -> dict[str, tuple[tuple[str, ...], int]]:
    """The lines of a section of `key value ...` lines: key -> (tokens, line)."""
    found: dict[str, tuple[tuple[str, ...], int]] = {}
    if section is None:
        return found
    for s, n in zip(section.lines, section.nums, strict=True):
        parts = s.split(None, 1)
        key = parts[0]
        if key in found:
            report.add("definitions.duplicate", name, n, f"{key} is defined twice")
        else:
            found[key] = (tuple(parts[1].split()) if len(parts) > 1 else (), n)
    return found


def _read_rasters(
    found: Mapping[str, tuple[tuple[str, ...], int]], report: _Report
) -> dict[str, float | None]:
    """The four rasters in seconds (None where missing or invalid)."""
    rasters: dict[str, float | None] = {}
    for key, attr in _RASTERS:
        rasters[attr] = None
        if key not in found:
            report.add("definitions.raster-missing", "DEFINITIONS", None, f"{key} is not defined")
            continue
        tokens, n = found[key]
        value = float(tokens[0]) if len(tokens) == 1 and _NUMBER.fullmatch(tokens[0]) else np.nan
        if np.isfinite(value) and value > 0:
            rasters[attr] = value
        else:
            report.add(
                "definitions.raster-invalid",
                "DEFINITIONS",
                n,
                f"{key} must be one finite number above 0, not {' '.join(tokens)!r}",
            )
    return rasters


def _read_table(
    section: _Section | None, columns: Sequence[tuple[str, str]], report: _Report, name: str
) -> _Table | None:
    """The rows of `section` as a structured array with one field for each of `columns`
    (the fields of kind `u` have 8 characters, the fields of kind `t` as many as the longest
    text), or None if the section has a violation. `name` is the section name of the
    violations."""
    if section is None or not section.lines:
        return _Table(_empty(columns), np.zeros(0, np.int64), name)
    nums = np.array(section.nums, dtype=np.int64)
    data = None
    if all(kind != "t" for _, kind in columns):
        data = _fast_table(section.lines, columns)
    if data is None:
        data = _slow_table(section, columns, report, name)
        if data is None:
            return None
    return _Table(data, nums, name)


_KIND_DTYPE = {"i": "<i8", "f": "<f8", "u": "<U8", "t": "<U1"}


def _empty(columns: Sequence[tuple[str, str]]) -> np.ndarray:
    return np.zeros(0, np.dtype([(n, _KIND_DTYPE[k]) for n, k in columns]))


def _fast_table(lines: list[str], columns: Sequence[tuple[str, str]]) -> np.ndarray | None:
    """The table by `numpy.loadtxt`, or None if the lines are not clean: a character other
    than ASCII, a `+` that starts a number (loadtxt accepts it in an integer), a value that is
    not a number, a float that is not finite, or a `use` that is not one of the letters."""
    blob = "\n".join(lines)
    if not blob.isascii() or "+" in blob.replace("e+", "").replace("E+", ""):
        return None
    dtype = np.dtype([(n, _KIND_DTYPE[k]) for n, k in columns])
    try:
        data = np.loadtxt(io.StringIO(blob), dtype=dtype, comments=None, ndmin=1)
    except ValueError:
        return None
    for n, kind in columns:
        if kind == "f" and not np.isfinite(data[n]).all():
            return None
        if kind == "u" and not np.isin(data[n], list(_USES)).all():
            return None
    return data


def _slow_table(
    section: _Section, columns: Sequence[tuple[str, str]], report: _Report, name: str
) -> np.ndarray | None:
    """The table, read one cell at a time. Reports each bad cell; returns None if there is one."""
    ok = True
    cells: list[list[Any]] = [[] for _ in columns]
    for s, n in zip(section.lines, section.nums, strict=True):
        tokens = s.split()
        if len(tokens) != len(columns):
            report.add(
                "syntax.columns", name, n, f"{len(tokens)} values, not the {len(columns)} expected"
            )
            ok = False
            continue
        row = []
        for (column, kind), token in zip(columns, tokens, strict=True):
            value = _cell(kind, token)
            if value is None:
                rule, what = {
                    "i": ("syntax.integer", "an integer"),
                    "f": ("syntax.number", "a finite number"),
                    "u": ("syntax.use", "one of e r i s p o u"),
                }[kind]
                report.add(rule, name, n, f"{column}: {token!r} is not {what}")
                ok = False
            row.append(value)
        if ok:
            for cell, value in zip(cells, row, strict=True):
                cell.append(value)
    if not ok:
        return None
    arrays = [
        np.array(cell, dtype=_KIND_DTYPE[kind] if kind != "t" else None)
        if cell
        else np.zeros(0, _KIND_DTYPE[kind])
        for cell, (_, kind) in zip(cells, columns, strict=True)
    ]
    out = np.zeros(
        len(section.lines),
        np.dtype([(c, a.dtype) for (c, _), a in zip(columns, arrays, strict=True)]),
    )
    for (column, _), array in zip(columns, arrays, strict=True):
        out[column] = array
    return out


def _cell(kind: str, token: str) -> Any:
    """The value of `token` for the column kind `kind`, or None if it is not valid."""
    if kind == "i":
        if not _INTEGER.fullmatch(token) or abs(int(token)) >= 2**63:
            return None
        return int(token)
    if kind == "f":
        if not _NUMBER.fullmatch(token):
            return None
        value = float(token)
        return value if np.isfinite(value) else None
    if kind == "u":
        return token if len(token) == 1 and token in _USES else None
    return token


def _check_table_ids(report: _Report, table: _Table | None) -> None:
    """`id.positive` and `id.unique` for the `id` column of `table`."""
    if table is None or len(table.data) == 0:
        return
    ids = table.data["id"]
    report.rows(
        "id.positive",
        table,
        np.flatnonzero(ids <= 0),
        lambda r: f"ID {ids[r]} is not positive",
    )
    order = np.argsort(ids, kind="stable")
    same = np.flatnonzero(ids[order][1:] == ids[order][:-1])
    later = np.sort(order[same + 1])
    report.rows("id.unique", table, later, lambda r: f"ID {ids[r]} is used twice")


def _check_block_order(report: _Report, table: _Table | None) -> None:
    """`blocks.order`: a block with an ID below that of an earlier block. An ID that is used
    twice is `id.unique` only."""
    if table is None or len(table.data) < 2:
        return
    ids = table.data["id"]
    rows = np.flatnonzero(ids[1:] < np.maximum.accumulate(ids)[:-1]) + 1
    report.rows(
        "blocks.order",
        table,
        rows,
        lambda r: f"block ID {ids[r]} comes after a larger ID: IDs must increase through the file",
    )


def _check_non_negative(report: _Report, table: _Table | None) -> None:
    if table is None:
        return
    for column in table.data.dtype.names or ():
        if column in _NON_NEGATIVE:
            values = table.data[column]
            report.rows(
                "syntax.negative",
                table,
                np.flatnonzero(values < 0),
                lambda r, column=column, values=values: f"{column} {values[r]:g} is negative",
            )


def _check_refs(
    report: _Report,
    table: _Table | None,
    column: str,
    ids: _Ids | None,
    what: str,
    minimum: int = 0,
    zero_ok: bool = True,
) -> None:
    """`ref.unresolved` for each value of `column` that is not an ID of `ids`. 0 is no
    reference (`zero_ok`), and `minimum` is the smallest value that can be a reference or 0 (0,
    or -1 for the time ID of a gradient)."""
    if table is None or ids is None or len(table.data) == 0:
        return
    if column not in table.data.dtype.names:
        return  # a 1.4.x ADC table has no phase_shape_id
    refs = table.data[column]
    _, found = ids.find(refs)
    bad = ((refs > 0) & ~found) | (refs < minimum) | ((refs == 0) & (not zero_ok))
    report.rows(
        "ref.unresolved",
        table,
        np.flatnonzero(bad),
        lambda r: f"{column} {refs[r]}: no {what} has it",
    )


def _raster_ns(rasters: Mapping[str, float | None], key: str) -> float | None:
    return None if rasters[key] is None else rasters[key] * _NS  # type: ignore[operator]


def _off_raster(ns: np.ndarray, raster_ns: float) -> np.ndarray:
    """Which of the times `ns` are not a multiple of `raster_ns`, to `TOLERANCE_NS`."""
    q = ns / raster_ns
    return np.abs(q - np.round(q)) * raster_ns > TOLERANCE_NS


class _ShapeInfo(NamedTuple):
    num_samples: int
    packed: np.ndarray
    line: int
    samples: np.ndarray | None  # the decompressed samples, None if the shape has a violation


def _read_shapes(section: _Section | None, report: _Report) -> dict[int, _ShapeInfo]:
    """The shapes of `[SHAPES]` by ID. A shape ends at a blank line (spec 2.9) or at the end of
    the section. A `shape_id` line with no blank line before it is `syntax.shape`, and it also
    ends the shape before it, so that this shape is read."""
    shapes: dict[int, _ShapeInfo] = {}
    if section is None or not section.lines:
        return shapes
    lines, nums = section.lines, section.nums
    count = len(lines)
    headers = [i for i, s in enumerate(lines) if s.startswith("shape_id")]
    blanks = np.array([i for i, s in enumerate(lines) if not s], dtype=np.int64)
    covered = np.zeros(count, bool)
    declared: list[tuple[int, int, int, int]] = []  # (id, num_samples, first sample line, end)
    broken: list[tuple[int, int]] = []  # (id, line) of a shape that is not well formed
    for k, i in enumerate(headers):
        stop = headers[k + 1] if k + 1 < len(headers) else count
        later = int(np.searchsorted(blanks, i))
        if later < blanks.size and blanks[later] < stop:
            stop = int(blanks[later])
        elif k + 1 < len(headers):
            report.add(
                "syntax.shape",
                "SHAPES",
                nums[stop],
                "this shape_id line has no blank line before it, which ends the shape before",
            )
        covered[i:stop] = True
        head = lines[i].split()
        if len(head) != 2 or _cell("i", head[1]) is None:
            report.add("syntax.shape", "SHAPES", nums[i], f"{lines[i]!r} is not `shape_id <id>`")
            continue
        second = lines[i + 1].split() if i + 1 < stop else []
        if len(second) != 2 or second[0] != "num_samples" or _cell("i", second[1]) is None:
            report.add(
                "syntax.shape", "SHAPES", nums[i], f"shape {head[1]} has no `num_samples <n>` line"
            )
            broken.append((int(head[1]), nums[i]))
            continue
        declared.append((int(head[1]), int(second[1]), i + 2, stop))
    for i in np.flatnonzero(~covered & np.array([bool(s) for s in lines])).tolist():
        report.add("syntax.shape", "SHAPES", nums[i], "this line is outside a shape")
    sample_lines = [s for _, _, a, b in declared for s in lines[a:b]]
    samples = _shape_samples(sample_lines, [(nums[a:b]) for _, _, a, b in declared], report)
    # A shape with a violation is kept as a placeholder (no samples), so that a reference to it
    # is not reported as unresolved too.
    nothing = np.zeros(0)
    for shape_id, line in broken:
        shapes.setdefault(shape_id, _ShapeInfo(-1, nothing, line, None))
    seen: dict[int, int] = {}
    start = 0
    for shape_id, num, a, b in declared:
        n_stored = b - a
        stored = nothing if samples is None else samples[start : start + n_stored]
        start += n_stored
        line = nums[a - 2]
        if shape_id <= 0:
            report.add("id.positive", "SHAPES", line, f"shape ID {shape_id} is not positive")
        if shape_id in seen:
            report.add("id.unique", "SHAPES", line, f"shape ID {shape_id} is used twice")
            continue
        seen[shape_id] = line
        if samples is None:
            shapes[shape_id] = _ShapeInfo(-1, nothing, line, None)
            continue
        if num < 0:
            report.add("syntax.negative", "SHAPES", line, f"num_samples {num} is negative")
            shapes[shape_id] = _ShapeInfo(-1, nothing, line, None)
            continue
        if num > _MAX_SHAPE_SAMPLES:
            report.add(
                "shape.length",
                "SHAPES",
                line,
                f"shape {shape_id} declares {num} samples, more than the {_MAX_SHAPE_SAMPLES} "
                "that the reader decompresses",
            )
            shapes[shape_id] = _ShapeInfo(-1, nothing, line, None)
            continue
        try:
            decoded = decompress_shape(stored, num)
        except ValueError as error:
            report.add("shape.length", "SHAPES", line, f"shape {shape_id}: {error}")
            decoded = None
        shapes[shape_id] = _ShapeInfo(num, stored, line, decoded)
    return shapes


def _shape_samples(
    sample_lines: list[str], line_numbers: list[Sequence[int]], report: _Report
) -> np.ndarray | None:
    """The values of the sample lines of all shapes, or None if one is not a finite number."""
    if not sample_lines:
        return np.zeros(0)
    blob = "\n".join(sample_lines)
    if blob.isascii() and "+" not in blob.replace("e+", "").replace("E+", ""):
        try:
            values = np.loadtxt(io.StringIO(blob), dtype=np.float64, comments=None, ndmin=1)
        except ValueError:
            values = None
        if values is not None and np.isfinite(values).all():
            return values
    numbers = [n for nums in line_numbers for n in nums]
    bad = False
    for s, n in zip(sample_lines, numbers, strict=True):
        if not _NUMBER.fullmatch(s) or not np.isfinite(float(s)):
            report.add("syntax.number", "SHAPES", n, f"sample {s!r} is not one finite number")
            bad = True
    if bad:
        return None
    return np.array([float(s) for s in sample_lines])


class _Ext:
    """The `extension` sections of a file, as the parser reads them."""

    def __init__(self) -> None:
        self.type_ids: dict[str, int] = {}  # STRING_ID -> type ID of the file
        self.tables: dict[str, _Table | None] = {}  # known extensions with a table
        self.shims: dict[int, np.ndarray] = {}  # RF_SHIMS: object ID -> (channels, 2)
        self.ids: dict[str, _Ids | None] = {}  # known extensions: the object IDs
        self.skipped: list[str] = []  # unknown, not required


_EXTENSION_COLUMNS = {
    "TRIGGERS": _TRIGGERS,
    "LABELSET": _LABELS,
    "LABELINC": _LABELS,
    "DELAYS": _SOFT_DELAYS,
    "ROTATIONS": _ROTATIONS,
}


def _read_extensions(sections: list[_Section], required: tuple[str, ...], report: _Report) -> _Ext:
    ext = _Ext()
    type_users: dict[int, str] = {}
    for section in sections:
        name = section.name
        if len(section.args) != 2:
            report.add(
                "syntax.columns", name, section.line, "expected `extension <STRING_ID> <type>`"
            )
            continue
        string_id, type_text = section.args
        if _cell("i", type_text) is None:
            report.add(
                "syntax.integer", name, section.line, f"the type {type_text!r} is not an integer"
            )
            continue
        type_id = int(type_text)
        if string_id in ext.type_ids:
            report.add(
                "section.duplicate", name, section.line, f"extension {string_id} appears twice"
            )
            continue
        if type_id in type_users:
            report.add(
                "id.unique",
                name,
                section.line,
                f"type {type_id} is also the type of extension {type_users[type_id]}",
            )
        type_users[type_id] = string_id
        ext.type_ids[string_id] = type_id
        if string_id in _EXTENSION_COLUMNS:
            table = _read_table(section, _EXTENSION_COLUMNS[string_id], report, name)
            _check_table_ids(report, table)
            _check_non_negative(report, table)
            ext.tables[string_id] = table
            ext.ids[string_id] = None if table is None else _Ids(table.data["id"])
        elif string_id == "RF_SHIMS":
            ext.ids[string_id] = _read_shims(section, ext, report)
        elif string_id not in required:
            ext.skipped.append(string_id)
    return ext


def _read_shims(section: _Section, ext: _Ext, report: _Report) -> _Ids | None:
    """The RF_SHIMS rows `id num_channels (magnitude phase)...` into `ext.shims`."""
    ok = True
    ids: list[int] = []
    for s, n in zip(section.lines, section.nums, strict=True):
        tokens = s.split()
        if len(tokens) < 2 or not all(_cell("i", t) is not None for t in tokens[:2]):
            report.add("syntax.integer", section.name, n, "a row starts with an ID and a count")
            ok = False
            continue
        shim_id, channels = int(tokens[0]), int(tokens[1])
        values = [_cell("f", t) for t in tokens[2:]]
        if channels < 0 or len(values) != 2 * channels:
            report.add(
                "syntax.columns", section.name, n, f"{len(values)} values for {channels} channels"
            )
            ok = False
        elif any(v is None for v in values):
            report.add("syntax.number", section.name, n, "a value is not a finite number")
            ok = False
        elif shim_id <= 0:
            report.add("id.positive", section.name, n, f"ID {shim_id} is not positive")
            ok = False
        elif shim_id in ext.shims:
            report.add("id.unique", section.name, n, f"ID {shim_id} is used twice")
            ok = False
        else:
            ext.shims[shim_id] = np.array(values, dtype=np.float64).reshape(channels, 2)
            ids.append(shim_id)
    return _Ids(np.array(ids, dtype=np.int64)) if ok else None


def _read_signature(section: _Section | None, raw: bytes, report: _Report) -> Signature | None:
    if section is None:
        return None
    found = _read_definitions(section, report, "SIGNATURE")
    for key in ("Type", "Hash"):
        if key not in found or len(found[key][0]) != 1:
            report.add("signature.invalid", "SIGNATURE", section.line, f"{key} must be one value")
            return None
    sig_type, sig_hash = found["Type"][0][0], found["Hash"][0][0]
    matches = None
    cut = raw.find(b"\n[SIGNATURE]")
    if cut >= 0:
        try:
            digest = hashlib.new(sig_type, raw[:cut], usedforsecurity=False).hexdigest()
        except (ValueError, TypeError):
            digest = None
        if digest is not None:
            matches = digest.lower() == sig_hash.lower()
    return Signature(sig_type, sig_hash, matches)


@dataclasses.dataclass
class _File:
    """What the parser has read of one file, for the checks across tables."""

    version: tuple[int, int, int]
    report: _Report
    rasters: dict[str, float | None]
    shapes: dict[int, _ShapeInfo]
    shape_ids: _Ids
    blocks: _Table | None
    rf: _Table | None
    grad: _Table | None
    trap: _Table | None
    adc: _Table | None
    entries: _Table | None
    ext: _Ext


def _ids_of(table: _Table | None) -> _Ids | None:
    return None if table is None else _Ids(table.data["id"])


def _check_gradient_ids(f: _File) -> None:
    """`id.gradient-unique`: no ID is in both `[GRADIENTS]` and `[TRAP]`."""
    if f.grad is None or f.trap is None:
        return
    ids = f.trap.data["id"]
    rows = np.flatnonzero(np.isin(ids, f.grad.data["id"]))
    f.report.rows(
        "id.gradient-unique", f.trap, rows, lambda r: f"ID {ids[r]} is also in [GRADIENTS]"
    )


def _check_references(f: _File) -> None:
    """`ref.unresolved` for the blocks, the events and the extension lists."""
    rep, v15 = f.report, f.version >= (1, 5, 0)
    grad_ids = None
    if f.grad is not None and f.trap is not None:
        grad_ids = _Ids(np.concatenate([f.grad.data["id"], f.trap.data["id"]]))
    entry_ids = _ids_of(f.entries)
    for column, table, what in (("rf", f.rf, "RF event"), ("adc", f.adc, "ADC event")):
        _check_refs(rep, f.blocks, column, _ids_of(table), what)
    for column in ("gx", "gy", "gz"):
        _check_refs(rep, f.blocks, column, grad_ids, "gradient event")
    _check_refs(rep, f.blocks, "ext", entry_ids, "extension list entry")
    _check_refs(rep, f.rf, "mag_id", f.shape_ids, "shape", zero_ok=False)
    _check_refs(rep, f.rf, "phase_id", f.shape_ids, "shape", zero_ok=False)
    _check_refs(rep, f.rf, "time_id", f.shape_ids, "shape")
    _check_refs(rep, f.grad, "shape_id", f.shape_ids, "shape", zero_ok=False)
    _check_refs(rep, f.grad, "time_id", f.shape_ids, "shape", minimum=-1 if v15 else 0)
    _check_refs(rep, f.adc, "phase_shape_id", f.shape_ids, "shape")
    _check_refs(rep, f.entries, "next", entry_ids, "extension list entry")
    _check_entry_objects(f)


def _check_entry_objects(f: _File) -> None:
    """Each entry of `[EXTENSIONS]` names a type that an `extension` section declares, and an
    object of it (the objects of an unknown extension are not read, so they are not checked)."""
    if f.entries is None or len(f.entries.data) == 0:
        return
    data, names = f.entries.data, {t: s for s, t in f.ext.type_ids.items()}
    types, refs = data["type"], data["ref"]
    undeclared = np.flatnonzero(~np.isin(types, list(names)))
    f.report.rows(
        "ref.unresolved",
        f.entries,
        undeclared,
        lambda r: f"type {types[r]}: no `extension` section has it",
    )
    for type_id, string_id in names.items():
        ids = f.ext.ids.get(string_id)
        if ids is None:
            continue
        rows = np.flatnonzero(types == type_id)
        _, found = ids.find(refs[rows])
        f.report.rows(
            "ref.unresolved",
            f.entries,
            rows[~found],
            lambda r, s=string_id: f"ref {refs[r]}: {s} has no object with this ID",
        )


def _reaches_end(entry_ids: _Ids, next_ids: np.ndarray) -> np.ndarray:
    """Whether the list that starts at each entry of `[EXTENSIONS]` ends (it reaches an entry
    with `next` 0, or one with a `next` that no entry has), and does not loop. Pointer doubling:
    after `bit_length(n)` rounds, an entry that has not reached the end is on or before a loop."""
    n = len(next_ids)
    row, found = entry_ids.find(next_ids)
    to = np.append(np.where(found & (next_ids != 0), row, n), n)  # n is the end
    for _ in range(max(1, n.bit_length())):
        to = to[to]
    return to[:n] == n


def _walk_extensions(f: _File) -> tuple[np.ndarray, np.ndarray]:
    """The (block row, entry row) of each entry in the extension list of each block. A list that
    loops is reported as `ref.unresolved` and is not walked."""
    empty = np.zeros(0, np.int64)
    if f.blocks is None or f.entries is None:
        return empty, empty
    entry_ids, next_ids = _Ids(f.entries.data["id"]), f.entries.data["next"]
    block_rows = np.flatnonzero(f.blocks.data["ext"])
    cur = f.blocks.data["ext"][block_rows]
    row, found = entry_ids.find(cur)
    ends = np.append(_reaches_end(entry_ids, next_ids), True)  # True at 0 for no entries
    loops = found & ~ends[row]
    f.report.rows(
        "ref.unresolved",
        f.blocks,
        block_rows[loops],
        lambda r: "the extension list of this block has a cycle",
    )
    block_rows, cur = block_rows[~loops], cur[~loops]
    out_block, out_entry = [empty], [empty]
    for _ in range(len(f.entries.data) + 1):
        row, found = entry_ids.find(cur)
        block_rows, row = block_rows[found], row[found]
        if block_rows.size == 0:
            break
        out_block.append(block_rows)
        out_entry.append(row)
        cur = next_ids[row]
        keep = cur != 0
        block_rows, cur = block_rows[keep], cur[keep]
    return np.concatenate(out_block), np.concatenate(out_entry)


class _Ends(NamedTuple):
    """The end of each event in nanoseconds from the start of its block (NaN where it cannot
    be known), and for the gradients the amplitude at the end."""

    rf: np.ndarray
    grad_ids: np.ndarray
    grad_end: np.ndarray
    grad_last: np.ndarray
    adc: np.ndarray


def _shape_columns(f: _File) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The number of samples, the first sample, the last sample and whether it is decoded, for
    each shape in the order of `f.shapes`, with one more value at the end (-1, NaN, NaN, False)
    so that an index is valid without shapes. A shape that has a violation is not decoded."""
    infos = list(f.shapes.values())
    num = np.array([s.num_samples for s in infos] + [-1], dtype=np.int64)
    nan = (np.nan, np.nan)
    ends = [
        (s.samples[0], s.samples[-1]) if s.samples is not None and s.samples.size else nan
        for s in infos
    ] + [nan]
    valid = np.array([s.samples is not None for s in infos] + [False])
    return num, np.array([e[0] for e in ends]), np.array([e[1] for e in ends]), valid


def _event_ends(f: _File) -> _Ends | None:
    """Checks every event table against the rasters and the shapes, and gives the end of each
    event. None if a table or a raster that the checks need is missing."""
    if None in (f.rf, f.grad, f.trap, f.adc) or f.blocks is None:
        return None
    rep = f.report
    num, first, last, valid = _shape_columns(f)
    r_grad, r_rf, r_adc = (_raster_ns(f.rasters, k) for k in ("gradient", "rf", "adc"))

    def shape(refs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        row, found = f.shape_ids.find(refs)
        return row, found & (refs > 0) & valid[row]

    # RF: the magnitude, phase and time shapes have one length.
    assert f.rf is not None and f.grad is not None and f.trap is not None and f.adc is not None
    d = f.rf.data
    mag, mag_ok = shape(d["mag_id"])
    phase, phase_ok = shape(d["phase_id"])
    time, time_ok = shape(d["time_id"])
    n_mag = np.where(mag_ok, num[mag], -1)
    rep.rows(
        "shape.event-length",
        f.rf,
        np.flatnonzero(mag_ok & phase_ok & (num[phase] != n_mag)),
        lambda r: "the magnitude and phase shapes have different numbers of samples",
    )
    shaped = (d["time_id"] > 0) & time_ok & mag_ok
    rep.rows(
        "shape.event-length",
        f.rf,
        np.flatnonzero(shaped & (num[time] != n_mag)),
        lambda r: "the time shape and the magnitude shape have different numbers of samples",
    )
    rf_end = np.full(len(d), np.nan)
    if r_rf is not None:
        delay = d["delay"] * 1e3
        default = mag_ok & (d["time_id"] == 0)
        rf_end[default] = delay[default] + n_mag[default] * r_rf
        use = shaped & (num[time] == n_mag)
        ticks = np.ceil(last[time] - TOLERANCE_NS / r_rf)
        rf_end[use] = delay[use] + ticks[use] * r_rf

    # Arbitrary gradients.
    g = f.grad.data
    gshape, gshape_ok = shape(g["shape_id"])
    gtime, gtime_ok = shape(g["time_id"])
    n_g = np.where(gshape_ok, num[gshape], -1)
    timed = (g["time_id"] > 0) & gtime_ok & gshape_ok
    rep.rows(
        "shape.event-length",
        f.grad,
        np.flatnonzero(timed & (num[gtime] != n_g)),
        lambda r: "the time shape and the waveform have different numbers of samples",
    )
    g_end = np.full(len(g), np.nan)
    g_delay = g["delay"] * 1e3
    if r_grad is not None:
        ticks = np.full(len(g), np.nan)
        ticks[gshape_ok & (g["time_id"] == 0)] = n_g[gshape_ok & (g["time_id"] == 0)]
        over = gshape_ok & (g["time_id"] == -1) & (f.version >= (1, 5, 0))
        ticks[over] = (n_g[over] + 1) / 2
        use = timed & (num[gtime] == n_g)
        ticks[use] = last[gtime][use]
        g_end = g_delay + ticks * r_grad
        late = _off_raster(g_delay, r_grad)
        rep.rows(
            "raster.gradient-delay",
            f.grad,
            np.flatnonzero(late),
            lambda r: f"delay {g['delay'][r]} us is not a multiple of GradientRasterTime",
        )
        rep.rows(
            "raster.gradient-end",
            f.grad,
            np.flatnonzero(~late & np.isfinite(g_end) & _off_raster(np.nan_to_num(g_end), r_grad)),
            lambda r: f"the gradient ends at {g_end[r] / 1e3:g} us, off GradientRasterTime",
        )
    g_first, g_last = _gradient_ends(f, gshape, gshape_ok, first, last)
    start = np.isfinite(g_first) & (g_first != 0) & (g["delay"] > 0)
    rep.rows(
        "gradient.nonzero-start-delay",
        f.grad,
        np.flatnonzero(start),
        lambda r: f"the gradient starts at {g_first[r]:g} Hz/m and has delay {g['delay'][r]} us",
    )

    # Trapezoids.
    t = f.trap.data
    t_end = (t["delay"] + t["rise"] + t["flat"] + t["fall"]) * 1e3
    if r_grad is not None:
        for rule, column in (
            ("raster.gradient-delay", "delay"),
            ("raster.gradient-ramp", "rise"),
            ("raster.gradient-flat", "flat"),
            ("raster.gradient-ramp", "fall"),
        ):
            values = t[column] * 1e3
            rep.rows(
                rule,
                f.trap,
                np.flatnonzero(_off_raster(values, r_grad)),
                lambda r, column=column: (
                    f"{column} {t[column][r]} us is not a multiple of GradientRasterTime"
                ),
            )

    # ADC.
    a = f.adc.data
    if r_adc is not None:
        rep.rows(
            "raster.adc-dwell",
            f.adc,
            np.flatnonzero(_off_raster(a["dwell"], r_adc)),
            lambda r: f"dwell {a['dwell'][r]:g} ns is not a multiple of AdcRasterTime",
        )
    adc_end = a["delay"] * 1e3 + a["num_samples"] * a["dwell"]
    return _Ends(
        rf_end,
        np.concatenate([g["id"], t["id"]]),
        np.concatenate([g_end, t_end]),
        np.concatenate([g_last, np.zeros(len(t))]),
        adc_end,
    )


def _gradient_ends(
    f: _File,
    shape_row: np.ndarray,
    shape_ok: np.ndarray,
    first: np.ndarray,
    last: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The `first` and `last` of each arbitrary gradient: the columns of the file from 1.5.0.
    In a 1.4.x file, the amplitude times the first and last sample of a gradient with a time
    shape, and NaN for a gradient on the default raster or with no sample (rule
    `layer1.gradient-ends`)."""
    assert f.grad is not None
    g = f.grad.data
    if f.version >= (1, 5, 0):
        return g["first"], g["last"]
    use = shape_ok & (g["time_id"] != 0) & np.isfinite(first[shape_row])
    f.report.rows(
        "layer1.gradient-ends",
        f.grad,
        np.flatnonzero((g["time_id"] == 0) | (shape_ok & ~use)),
        lambda r: (
            "the file does not define the values at the ends of this gradient; "
            "Pulseq 1.5 stores them"
        ),
    )
    out_first = np.where(use, g["amplitude"] * first[shape_row], np.nan)
    out_last = np.where(use, g["amplitude"] * last[shape_row], np.nan)
    return out_first, out_last


def _check_amplitude_shapes(f: _File) -> None:
    """`shape.range` for the shapes that are an RF magnitude or a gradient waveform."""
    used: set[int] = set()
    for table, column in ((f.rf, "mag_id"), (f.grad, "shape_id")):
        if table is not None:
            used.update(np.unique(table.data[column]).tolist())
    for shape_id in sorted(used & set(f.shapes)):
        info = f.shapes[shape_id]
        if info.samples is not None and info.samples.size:
            peak = float(np.abs(info.samples).max())
            if peak > 1 + RANGE_TOLERANCE:
                f.report.add(
                    "shape.range",
                    "SHAPES",
                    info.line,
                    f"shape {shape_id} has a sample of {peak:g}: an amplitude shape is in [-1, 1]",
                )


def _take(values: np.ndarray, row: np.ndarray, found: np.ndarray, fill: float) -> np.ndarray:
    """`values[row]` where `found`, else `fill`."""
    if values.size == 0:
        return np.full(len(row), fill)
    return np.where(found, values[row], fill)


def _check_blocks(f: _File, ends: _Ends | None) -> None:
    """`block.event-too-long`, `gradient.nonzero-end-align` and `extension.per-block`."""
    r_block = _raster_ns(f.rasters, "block_duration")
    if f.blocks is None or r_block is None:
        return
    rep, b = f.report, f.blocks.data
    block_ns = b["duration_ticks"] * r_block
    pair_block, pair_entry = _walk_extensions(f)
    if ends is not None:
        events = [("rf", "RF", _ids_of(f.rf), ends.rf), ("adc", "ADC", _ids_of(f.adc), ends.adc)]
        grad_ids = _Ids(ends.grad_ids)
        for column in ("gx", "gy", "gz"):
            events.append((column, "gradient", grad_ids, ends.grad_end))
        for column, what, ids, end_ns in events:
            assert ids is not None
            row, found = ids.find(b[column])
            found &= b[column] != 0
            end = _take(end_ns, row, found, np.nan)
            rep.rows(
                "block.event-too-long",
                f.blocks,
                np.flatnonzero(end > block_ns + TOLERANCE_NS),
                lambda r, column=column, what=what, end=end: (
                    f"the {what} event {b[column][r]} "
                    f"ends at {end[r] / 1e3:g} us, the block lasts {block_ns[r] / 1e3:g} us"
                ),
            )
            if what == "gradient":
                last = _take(ends.grad_last, row, found, 0.0)
                bad = (
                    found & np.isfinite(end) & (last != 0) & (np.abs(end - block_ns) > TOLERANCE_NS)
                )
                rep.rows(
                    "gradient.nonzero-end-align",
                    f.blocks,
                    np.flatnonzero(bad),
                    lambda r, column=column, end=end: (
                        f"gradient {b[column][r]} ends at "
                        f"{end[r] / 1e3:g} us, not at the end of the block ({block_ns[r] / 1e3:g} us)"
                    ),
                )
        _check_trigger_ends(f, block_ns, pair_block, pair_entry)
    if f.entries is not None:
        types = f.entries.data["type"][pair_entry]
        for string_id in ("ROTATIONS", "RF_SHIMS"):
            if string_id in f.ext.type_ids:
                count = np.bincount(
                    pair_block[types == f.ext.type_ids[string_id]], minlength=len(b)
                )
                rep.rows(
                    "extension.per-block",
                    f.blocks,
                    np.flatnonzero(count > 1),
                    lambda r, string_id=string_id, count=count: (
                        f"the block has {count[r]} {string_id} objects, at most 1 is allowed"
                    ),
                )


def _check_trigger_ends(
    f: _File, block_ns: np.ndarray, pair_block: np.ndarray, pair_entry: np.ndarray
) -> None:
    """`block.event-too-long` for the triggers of the extension lists."""
    table = f.ext.tables.get("TRIGGERS")
    ids = f.ext.ids.get("TRIGGERS")
    if table is None or ids is None or f.entries is None or f.blocks is None:
        return
    mine = f.entries.data["type"][pair_entry] == f.ext.type_ids["TRIGGERS"]
    blocks, entries = pair_block[mine], pair_entry[mine]
    row, found = ids.find(f.entries.data["ref"][entries])
    blocks, row = blocks[found], row[found]
    end = (table.data["delay"][row] + table.data["duration"][row]) * 1e3
    bad = end > block_ns[blocks] + TOLERANCE_NS
    f.report.rows(
        "block.event-too-long",
        f.blocks,
        blocks[bad],
        lambda r: "a trigger of the block ends after the block",
    )


def _build(raw: bytes, report: _Report) -> SequenceData | None:
    """The model of `raw`, or None; every violation goes to `report`."""
    text = _decode(raw, report)
    if text is None:
        return None
    named, extension_sections = _split(text, report)
    version = _read_version(_one(named, "VERSION", report), report)
    if version is None:
        return None
    v15 = version >= (1, 5, 0)
    for extra in named.get("DELAYS", []):
        report.add("section.delays", "DELAYS", extra.line, "a [DELAYS] section is not allowed")

    found = _read_definitions(_one(named, "DEFINITIONS", report), report)
    rasters = _read_rasters(found, report)
    required: tuple[str, ...] = ()
    if version >= (1, 5, 1) and "RequiredExtensions" in found:
        required, line = found["RequiredExtensions"]
        for token in required:
            if token not in _KNOWN_EXTENSIONS:
                report.add(
                    "extension.required-unknown",
                    "DEFINITIONS",
                    line,
                    f"the required extension {token} is not known",
                )
    shapes = _read_shapes(_one(named, "SHAPES", report), report)
    f = _File(
        version,
        report,
        rasters,
        shapes,
        _Ids(np.array(list(shapes), dtype=np.int64)),
        _read_table(_one(named, "BLOCKS", report), _BLOCKS, report, "BLOCKS"),
        _read_table(_one(named, "RF", report), _RF_15 if v15 else _RF_14, report, "RF"),
        _read_table(
            _one(named, "GRADIENTS", report), _GRAD_15 if v15 else _GRAD_14, report, "GRADIENTS"
        ),
        _read_table(_one(named, "TRAP", report), _TRAP, report, "TRAP"),
        _read_table(_one(named, "ADC", report), _ADC_15 if v15 else _ADC_14, report, "ADC"),
        _read_table(_one(named, "EXTENSIONS", report), _ENTRIES, report, "EXTENSIONS"),
        _read_extensions(extension_sections, required, report),
    )
    for table in (f.blocks, f.rf, f.grad, f.trap, f.adc, f.entries):
        _check_table_ids(report, table)
        _check_non_negative(report, table)
    signature = _read_signature(_one(named, "SIGNATURE", report), raw, report)
    if f.blocks is not None and len(f.blocks.data) == 0:
        report.add("blocks.empty", "BLOCKS", None, "the file has no block")
    _check_block_order(report, f.blocks)
    _check_gradient_ids(f)
    _check_references(f)
    ends = _event_ends(f)
    _check_amplitude_shapes(f)
    _check_blocks(f, ends)
    if report:
        return None
    return _assemble(f, found, required, signature)


def _model_table(name: str, data: np.ndarray, **columns: Any) -> np.ndarray:
    """The table `name` of the model from the parsed rows `data`: the columns of `data` that the
    model has (a text column keeps the width of `data`), and `columns` as the others."""
    dtype = TABLE_DTYPES[name]
    names = data.dtype.names or ()
    fields = [
        (n, data.dtype[n] if n in ("name", "hint") and n in names else dtype[n])
        for n in dtype.names
    ]
    out = np.zeros(len(data), np.dtype(fields))
    for n in dtype.names:
        if n in names:
            out[n] = data[n]
    for n, value in columns.items():
        out[n] = value
    return out


def _assemble(
    f: _File,
    definitions: Mapping[str, tuple[tuple[str, ...], int]],
    required: tuple[str, ...],
    signature: Signature | None,
) -> SequenceData:
    """The model of a file with no violation (every table is there)."""
    assert f.blocks and f.rf and f.grad and f.trap and f.adc and f.entries
    rasters = Rasters(*(f.rasters[attr] for _, attr in _RASTERS))  # type: ignore[arg-type]
    rf_d, g_d, t_d, a_d = f.rf.data, f.grad.data, f.trap.data, f.adc.data
    if f.version >= (1, 5, 0):
        rf = _model_table("rf", rf_d, center=rf_d["center"] / _US, delay=rf_d["delay"] / _US)
        adc = _model_table("adc", a_d, dwell=a_d["dwell"] / _NS, delay=a_d["delay"] / _US)
        grad = _model_table("grad", g_d, delay=g_d["delay"] / _US)
    else:
        rf = _model_table("rf", rf_d, center=np.nan, delay=rf_d["delay"] / _US, use="u")
        adc = _model_table("adc", a_d, dwell=a_d["dwell"] / _NS, delay=a_d["delay"] / _US)
        _, first, last, _ = _shape_columns(f)
        row, _ = f.shape_ids.find(g_d["shape_id"])
        grad = _model_table(
            "grad",
            g_d,
            first=g_d["amplitude"] * first[row],
            last=g_d["amplitude"] * last[row],
            delay=g_d["delay"] / _US,
        )
    trap = _model_table(
        "trap",
        t_d,
        rise=t_d["rise"] / _US,
        flat=t_d["flat"] / _US,
        fall=t_d["fall"] / _US,
        delay=t_d["delay"] / _US,
    )
    tables = f.ext.tables

    def ext_table(name: str, string_id: str, **columns: Any) -> np.ndarray:
        table = tables.get(string_id)
        if table is None:
            return np.zeros(0, TABLE_DTYPES[name])
        return _model_table(name, table.data, **{k: v(table.data) for k, v in columns.items()})

    extensions = Extensions(
        entries=_model_table("entries", f.entries.data),
        type_ids=dict(f.ext.type_ids),
        triggers=ext_table(
            "triggers",
            "TRIGGERS",
            delay=lambda d: d["delay"] / _US,
            duration=lambda d: d["duration"] / _US,
        ),
        labelset=ext_table("labelset", "LABELSET"),
        labelinc=ext_table("labelinc", "LABELINC"),
        soft_delays=ext_table("soft_delays", "DELAYS", offset=lambda d: d["offset"] / _US),
        rotations=ext_table("rotations", "ROTATIONS"),
        rf_shims=dict(f.ext.shims),
    )
    return SequenceData(
        version=f.version,
        definitions={k: tokens for k, (tokens, _) in definitions.items()},
        rasters=rasters,
        required_extensions=required,
        blocks=_model_table("blocks", f.blocks.data),
        rf=rf,
        grad=grad,
        trap=trap,
        adc=adc,
        shapes={i: Shape(s.num_samples, s.packed) for i, s in f.shapes.items()},
        extensions=extensions,
        skipped_extensions=tuple(f.ext.skipped),
        signature=signature,
        origin="file",
    )
