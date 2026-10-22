"""The `spec` interpreter: a reader of Pulseq text files, versions 1.4.0 to 1.5.x, as true as
possible to the Pulseq specification, into the model of layer 1. It is the default interpreter
of `seqfile.read_seqfile`; a plugin interpreter is read by name (`interpreters`).

`seqfile.read_seqfile(path)` is the one way to read a file through `spec` (the user,
2026-10-14; `spec.read_spec` was the same): it checks the scope (`errors._read_in_scope`, for every
interpreter) and reads the "as written" reading of the check with `_read_written`. The reading
returns a `model.SequenceData`, or raises `SeqFileError` (a `ValueError`) with every violation of
its rules, and `NotSupported` for a file outside the package's scope (Q1 of
`docs/plans/parser-redesign.md`): a folder, a binary Pulseq file, or a version outside 1.4.0 to
1.5.x. It raises `NotSupported` too for a shape that declares more samples than the setting
`max_shape_samples` of the interpreter (`interpreters.Spec`), before it decompresses the shape.
Each violation is a `Violation(rule, section, line, message)`. The error lists at most
`MAX_LOCATIONS` violations of each rule and counts the rest (`SeqFileError.omitted`). The reader
does not import pypulseq, uses no default for a value that the file must define, and does not
round a number or renumber an ID (a time is converted to seconds). The binary format is not read.

**The sources.** "The specification" is `doc/specification.tex` of pulseq/pulseq at `c7469123`
(1.5.3 draft), cited as spec:N (its line N). Its section 2.6 refers to the slide set
`doc/pulseq_shapes_and_times.pdf` of the same commit for timing, and the slide set is normative
for timing here (the user, 2026-10-12), cited as "slide N". Where the two say "must", `spec`
rejects the file (Q4). Where they are silent or unclear, section 6 of the plan gives the reading
(Q5), and `spec` rejects a file only where no current writer (MATLAB Pulseq and pypulseq, their
makers and writers) writes such a file (the user, 2026-10-12). Every rule records its basis in
`RULES`: the text that it rests on, and, for a rule that is the package's choice, why; the message
of each such violation says that the specification does not state the rule, and why `spec`
rejects the file. `docs/specification.md` gives the rule, each place where it does not decide,
and the codes; `docs/discrepancies.md` gives, entry by entry, what `spec` does and why.

**Lines and sections.** The reader reads the file through its "as written" reading
(`as_written.read_as_written`). A blank line and a line that starts with `#` are skipped anywhere,
also inside a table and inside a shape (spec:171: "Comments are specified by a line starting with
a hash"); inside a shape, a blank line ends the shape (spec:602, D3.11). A data line before the
first header is `syntax.line`. A section that the format does not have and a `[DELAYS]` section
are ignored (D2.4). A section that appears more than once, or two `extension` sections with
one STRING_ID, is `section.duplicate`, and only its first copy is read (D3.3). A definition that
appears twice is the last (D2.6). Blocks play in file order, whatever their IDs. A check that
needs a table with a violation of syntax is skipped, so the error has every violation of the
tables that read, and every violation of syntax.

**Values.** Each field is read by the type of its column in the tables of the specification
(spec:176, spec:293-455): an integer is an optional sign and digits (`+30` is 30), a float a decimal number. NaN and
infinite floats are rejected, and so are the negative times and counts of `syntax.negative`. The
RF `use` is one of `e r i s p o u`. The ADC dwell time is a float in ns (spec:437), the soft delay
offset a float in µs and its hint the whole text (D2.16).

**Versions.** Each mechanism of the format is read from the revision that introduced it (the
user, 2026-10-12): the soft delays (`extension DELAYS`) from 1.5.0 (spec:545), the extensions
ROTATIONS and RF_SHIMS from 1.5.1 (spec:567, spec:584), the definition `RequiredExtensions` from
1.5.1 (spec:460), and the time ID -1 of an oversampled gradient from 1.5.0 (slide 4). In an older
file such an extension is an extension that the interpreter does not know: it is ignored, its
STRING_ID is in `SequenceData.skipped_extensions` (D2.17), and a `model.Record` says why (D4.6).

**Records** (P20, rule 4). `SequenceData.records` has a `model.Record` for each thing that `spec`
ignored: an extension that it does not know (D2.17) or that the version does not have yet (D4.6), a
section that the format does not have or removed (D2.4), and a label that the specification
does not list (D2.19; `NOSCL`, which the specification spells `NOSLC`) or that the version
does not have yet (the flags PMC, NOROT, NOPOS, NOSLC and ONCE of 1.4.1, spec:526). The row of
such a label stays in `Extensions.labelset` or `labelinc`, as written.

**Rotations** (D2.18, D3.10). From 1.5.1, each quaternion of ROTATIONS is divided by its norm (spec:567:
"a normalized rotation quaternion"), and a quaternion of norm 0 is rejected. The decoding of
`spec` rotates each block's gradients by its quaternion (`synth.decoding.SpecDecoding`).

**Time shapes.** An RF time shape (D2.10 to D2.12) is regular when its times are `(i + 0.5) d` for a
step `d` (`model.rf_time_step`): its samples are cells of `d` from the start of the pulse
(slide 9), and the pulse lasts `N d`. Any other RF time shape is points at its times, joined by
straight lines (slide 4: explicit times; slide 9: a pulse "defined by vertices"); the pulse ends
at its last time. A gradient time shape gives the vertices of an extended trapezoid (slide 6). The
decoding is `synth.events`.

`RULES` maps each code to its `Rule`. A code is a stable name of its condition (`errors`): a
reader of the error, such as pulseq-checks, can rely on it.
"""

import bisect
import dataclasses
import hashlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, NamedTuple

import numpy as np

from . import as_written
from .as_written import AsWritten
from .errors import NotSupported, SeqFileError, Violation
from .interpreters import Spec
from .model import (
    TABLE_DTYPES,
    Extensions,
    Rasters,
    Record,
    SequenceData,
    Shape,
    Signature,
    decompress_shape,
    rf_time_step,
)

__all__ = [
    "FIRST_TIME_TOLERANCE",
    "MAX_LOCATIONS",
    "RANGE_TOLERANCE",
    "RATIO_TOLERANCE",
    "RULES",
    "TOLERANCE_NS",
    "Rule",
]

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

# The first time of the time shape of a 1.4.x arbitrary gradient is 0 to within this many gradient
# rasters, a gradient time shape starts before 0 when its first time is below 0 by more, and a
# vertex of a gradient time shape is on the raster to within as many.
FIRST_TIME_TOLERANCE = 1e-6

# Two rasters are integer multiples of each other to within this relative difference.
RATIO_TOLERANCE = 1e-6

# What a rule of the package's choice says in each of its messages: the specification does not
# state it, and no current writer writes such a file.
_NO_WRITER = "no current writer (MATLAB Pulseq, pypulseq) writes such a file"


@dataclasses.dataclass(frozen=True, slots=True)
class Rule:
    """A rule of `spec`.

    - `text`: what the rule rejects.
    - `source`: what it rests on: the lines of the specification (spec:N), the slides of the slide
      set that section 2.6 cites (slide N), and the entries of `docs/discrepancies.md`.
    - `choice`: `None` when the specification or the slides state the rule; otherwise why the
      package rejects such a file. A violation of such a rule says so in its message.
    - `partial`: the choice covers only some of the conditions of the rule (the others are
      stated); only their violations carry `choice`.
    """

    text: str
    source: str
    choice: str | None = None
    partial: bool = False


RULES: Mapping[str, Rule] = MappingProxyType(
    {
        "version.missing": Rule(
            "no [VERSION] section",
            'spec:201 ("It is recommended to reject Pulseq files without [VERSION] section"); D1.1',
        ),
        "version.invalid": Rule(
            "a line of [VERSION] is not major, minor or revision with an integer, or a key is "
            "missing or repeated",
            "spec:193-198 (three lines, each an integer)",
        ),
        "definitions.raster-missing": Rule(
            "a required raster is not defined", "spec:267-276 (required from 1.4.0)"
        ),
        "definitions.raster-invalid": Rule(
            "a raster is not one finite number above 0",
            "spec:267-276 (a raster time in seconds)",
        ),
        "definitions.raster-commensurate": Rule(
            "RadiofrequencyRasterTime or GradientRasterTime is neither an integer multiple nor "
            "an integer divisor of BlockDurationRaster",
            'slide 11 ("rfRasterTime and gradRasterTime must be integer-multiples of '
            'blockDurationRaster or vise versa")',
        ),
        "section.duplicate": Rule(
            "a section that appears twice, or two `extension` sections with one STRING_ID",
            "D3.3",
            choice="the specification is silent on a section that appears twice, the readers "
            "disagree on what it means (the C++ reader keeps the last copy; MATLAB Pulseq and "
            "pypulseq add the copies of some sections and keep the last copy of others), and "
            + _NO_WRITER,
        ),
        "syntax.encoding": Rule(
            "the file is not UTF-8",
            "D3.1",
            choice="the specification gives no encoding; MATLAB Pulseq and pypulseq fail on a "
            "byte that is not UTF-8, and the text of the model must be UTF-8",
        ),
        "syntax.line": Rule(
            "a data line before the first section",
            "D3.2",
            choice="the specification has no line outside a section; MATLAB Pulseq and pypulseq "
            "reject one, and " + _NO_WRITER,
        ),
        "syntax.columns": Rule(
            "a row does not have the number of fields of its table for the version",
            "the tables and examples of spec:293-455 and spec:476-596; D1.2, D4.2",
        ),
        "syntax.integer": Rule(
            "a value of an integer column is not an integer",
            "the types of the tables (spec:176, spec:293-455)",
        ),
        "syntax.number": Rule(
            "a value of a float column is not a finite number",
            "the types of the tables (spec:176, spec:293-455); D3.5",
            choice="the specification types the column as a float and does not say whether NaN "
            "and infinity are floats of the file; they give no waveform, and the makers of the "
            "writers do not check for them, so a script that passes one gets such a file",
            partial=True,
        ),
        "syntax.use": Rule(
            "the use of an RF event is not one of e r i s p o u",
            'spec:356-357 ("the initial of one of" seven words)',
        ),
        "syntax.negative": Rule(
            "a block duration, delay, rise, flat or fall time, number of samples, dwell time or "
            "trigger duration is negative",
            'spec:176 ("integer types are stored as 64-bit unsigned integers"); D3.6',
            choice="this is not literally the specification: it stores integers as unsigned "
            "(spec:176) but defines negative values elsewhere (the time ID -1, a soft delay "
            "offset), and the ADC dwell time is a float; a negative time or count gives no "
            "waveform, and the makers of the writers do not check the sign, so a script that "
            "passes one gets such a file",
        ),
        "syntax.shape": Rule(
            "a shape without its shape_id and num_samples lines, a line of [SHAPES] outside a "
            "shape, or a shape with no blank line after it",
            'spec:602-612 (the header of a shape; "The end of the shape definition is declared '
            'with a blank line"); D3.11',
            choice="the specification declares the end of a shape with a blank line and does not "
            "say what a shape without one is; " + _NO_WRITER,
            partial=True,
        ),
        "id.positive": Rule(
            "an ID, or the type ID of an extension, is not positive",
            'spec:181 ("IDs must be positive"); spec:472, spec:494 (`<type>` is the "ID of the '
            'type" of an extension)',
        ),
        "id.unique": Rule(
            "an ID is used twice in one class",
            "spec:182-183 (shapes, and events of one class); D3.4",
            choice="the specification states uniqueness for shapes and events, not for blocks, "
            "which nothing refers to; both writers number the blocks 1, 2, ..., and MATLAB "
            "Pulseq stores them by ID",
            partial=True,
        ),
        "id.gradient-unique": Rule(
            "a gradient ID is in [GRADIENTS] and in [TRAP]", "spec:183, spec:403"
        ),
        "ref.unresolved": Rule(
            "a reference names something that is not defined, a list of extensions does not "
            "end, or a time ID of -1 where it is not defined",
            "spec:178-186 (IDs refer to the objects one level below), spec:478 (a zero-terminated "
            "list), spec:349 and spec:395 (time ID -1 for gradients only), slide 4 (-1 from "
            "1.5.0); D4.3",
        ),
        "blocks.empty": Rule(
            "the file has no block",
            'spec:318 ("The sequence must declare at least one block")',
        ),
        "block.event-too-long": Rule(
            "an event lasts longer than its block",
            'spec:318 ("The interpreters must to throw an error")',
        ),
        "raster.adc-dwell": Rule(
            "an ADC dwell time is not a multiple of AdcRasterTime", "spec:275; slide 10"
        ),
        "raster.adc-delay": Rule(
            "an ADC does not start on an edge of the RF raster",
            'slide 10 ("ADC start time must be aligned to rfRasterTime")',
        ),
        "raster.rf-delay": Rule(
            "an RF event does not start on an edge of the RF raster",
            'slide 9 ("The beginning of an RF object must be aligned to the RF raster edge"); '
            "spec:290",
        ),
        "raster.gradient-delay": Rule(
            "a gradient starts off the gradient raster", "spec:290; slide 5"
        ),
        "raster.gradient-end": Rule(
            "a gradient with a time shape ends off the gradient raster", "spec:290; slide 5"
        ),
        "raster.gradient-ramp": Rule(
            "a rise or fall time is not a multiple of the gradient raster", "spec:290; slide 5"
        ),
        "raster.gradient-flat": Rule(
            "a flat time is not a multiple of the gradient raster", "spec:290; slide 5"
        ),
        "raster.gradient-vertex": Rule(
            "a vertex of a gradient time shape is off the gradient raster",
            'slide 6 ("all aligned on raster edges") against slide 4 ("not a requirement"); D1.3',
            choice="the slides conflict (slide 6 puts the vertices of an extended trapezoid on "
            "the raster edges, slide 4 does not require it of a time shape); the makers of both "
            "writers refuse a vertex off the raster, and " + _NO_WRITER,
        ),
        "gradient.nonzero-start-delay": Rule(
            "a gradient that starts above 0 has a delay",
            'spec:420 ("the start delay of such gradients must be 0"); slide 6',
        ),
        "gradient.nonzero-end-align": Rule(
            "a gradient that ends above 0 does not end with its block",
            'spec:420 ("they need to be aligned to the end of the block"); slide 6',
        ),
        "shape.length": Rule(
            "a shape does not have the number of samples that it declares",
            'spec:626 ("must be equal the number declared")',
        ),
        "shape.range": Rule(
            "an amplitude shape is outside [-1, 1]",
            'spec:624 ("must be in the normalised range of [-1, 1]")',
        ),
        "shape.empty": Rule(
            "an event uses a shape with no sample",
            "D3.7",
            choice="the specification is silent on a shape with no sample; an event with no "
            "samples has no waveform, and " + _NO_WRITER,
        ),
        "shape.event-length": Rule(
            "the shapes of one event have different numbers of samples, or an ADC phase shape "
            "has not one sample for each ADC sample",
            "spec:349 and spec:443 (the shapes of an event pair up by sample); spec:120 "
            "(an ADC phase offset per sample); D3.8",
            choice="the specification does not say what an event of shapes of different lengths "
            "plays: some samples have no partner, and " + _NO_WRITER,
        ),
        "shape.time-order": Rule(
            "an RF time shape of one sample at 0 or before, or a time shape whose times do not "
            "increase or whose first time is below 0 (an RF time shape of one sample t0 above 0 "
            "is one cell of 2 t0)",
            "spec:349, spec:395 (the time sampling points); D2.10-D2.12, D3.9",
            choice="the specification does not define such time sampling points, and " + _NO_WRITER,
        ),
        "shape.oversampled-length": Rule(
            "an oversampled gradient (time ID -1) has an even number of samples",
            'spec:420 ("N-1 additional points"), slides 4 and 8 (the samples alternate between '
            'centres and edges, and the shape "starts and ends at the cell centers")',
        ),
        "rotation.zero": Rule(
            "a quaternion of ROTATIONS has a norm of 0",
            'spec:567 ("a normalized rotation quaternion"); D3.10',
            choice="`spec` divides each quaternion by its norm, as the specification describes a "
            "normalized one, and a quaternion of norm 0 is no rotation; " + _NO_WRITER,
        ),
        "extension.required-unknown": Rule(
            "a required extension is not known",
            'spec:460 ("it MUST generate an error")',
        ),
        "extension.per-block": Rule(
            "a block has more than one ROTATIONS or RF_SHIMS object",
            'spec:567, spec:584 ("Only one ... object can be specified per block")',
        ),
        "layer1.gradient-ends": Rule(
            "a 1.4.x arbitrary gradient has no value at its start or end",
            "spec:290 (default sampling at the cell centres; a 1.4 file has no first and last); D4.4, D4.5",
            choice="a 1.4 file does not define the values at the ends of an arbitrary gradient "
            "on the default raster, or of one whose time shape starts after 0, and the readers "
            "guess them differently; Pulseq 1.5 stores them",
        ),
        "signature.invalid": Rule(
            "[SIGNATURE] has no Type or no Hash, or one that is not one value",
            'spec:223-232 ("must contain two following fields")',
        ),
    }
)

_SECTIONS = (
    "VERSION",
    "DEFINITIONS",
    "BLOCKS",
    "RF",
    "GRADIENTS",
    "TRAP",
    "ADC",
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
# Each extension that the interpreter knows, and the first version that has it (spec:526-584;
# TRIGGERS from 1.3.0 and the labels from 1.3.1, so in every version that the package reads).
_KNOWN_EXTENSIONS = {
    "TRIGGERS": (1, 4, 0),
    "LABELSET": (1, 4, 0),
    "LABELINC": (1, 4, 0),
    "DELAYS": (1, 5, 0),
    "ROTATIONS": (1, 5, 1),
    "RF_SHIMS": (1, 5, 1),
}
# The labels of LABELSET and LABELINC that the specification lists (spec:519-520), and those of
# them that revision 1.4.1 introduced (spec:526). The C++ reader, MATLAB Pulseq and pypulseq
# spell NOSLC as NOSCL (D2.19); `spec` follows the specification.
_LABELS = frozenset(
    [
        "LIN",
        "PAR",
        "ACQ",
        "SLC",
        "SEG",
        "REP",
        "AVG",
        "SET",
        "ECO",
        "PHS",
        "NAV",
        "REV",
        "SMS",
        "OFF",
        "NOISE",
        "REF",
        "IMA",
        "PMC",
        "NOPOS",
        "NOROT",
        "NOSLC",
        "ONCE",
        "TRID",
    ]
)
_LABELS_1_4_1 = frozenset(["PMC", "NOROT", "NOPOS", "NOSLC", "ONCE"])
_USES = "erispou"
_US, _NS = 1e6, 1e9  # microseconds and nanoseconds in a second

# The columns that are never negative (`syntax.negative`).
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


class _Report:
    """The violations of one file, at most `MAX_LOCATIONS` for each rule."""

    def __init__(self) -> None:
        self.kept: list[Violation] = []
        self.counts: Counter[str] = Counter()

    def __bool__(self) -> bool:
        return any(self.counts.values())

    def add(
        self,
        rule: str,
        section: str | None,
        line: int | None,
        message: str,
        choice: bool | None = None,
    ) -> None:
        """Add a violation. Its message ends with the reason of the package's choice when the rule
        is a choice (`Rule.choice`): always for a rule that is wholly one, and when `choice` is
        true for a rule that is partly one (`Rule.partial`)."""
        self.counts[rule] += 1
        if self.counts[rule] <= MAX_LOCATIONS:
            self.kept.append(Violation(rule, section, line, _message(rule, message, choice)))

    def rows(
        self,
        rule: str,
        table: "_Table",
        rows: np.ndarray,
        message: Callable[[int], str],
        choice: bool | None = None,
    ) -> None:
        """Add a violation for each row index of `rows` of `table`."""
        room = max(0, MAX_LOCATIONS - self.counts[rule])
        for row in rows[:room].tolist():
            self.add(rule, table.section, int(table.nums[row]), message(row), choice)
        if len(rows) > room:
            self.counts[rule] += len(rows) - room

    def error(self, path: str) -> SeqFileError:
        kept = sorted(self.kept, key=lambda v: (v.line or 0, v.rule))
        omitted = {rule: n - MAX_LOCATIONS for rule, n in self.counts.items() if n > MAX_LOCATIONS}
        return SeqFileError(path, kept, omitted, Spec.name)


def _message(rule: str, message: str, choice: bool | None) -> str:
    known = RULES[rule]
    if known.choice is None or (known.partial and not choice):
        return message
    return f"{message} (the specification does not state this rule: {known.choice})"


class _Table(NamedTuple):
    """The rows of a table, the line number of each row and the section name."""

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


def _read_written(written: AsWritten, interpreter: Spec) -> SequenceData:
    """Read the file that `written` reads, a file in the package's scope
    (`errors._read_in_scope`), into a `SequenceData`, by the rules of the `spec` interpreter
    `interpreter`, with its settings: the reading of `seqfile.read_seqfile(path, interpreter)`.

    Raises `SeqFileError` (a `ValueError`) with all the violations when the file breaks a rule
    (see the module docstring), and `NotSupported` for a shape that declares more samples than
    `interpreter.max_shape_samples`.
    """
    report = _Report()
    data = _build(written, report, interpreter)
    if report or data is None:
        raise report.error(written.path)
    return data


def _encoding(written: AsWritten, report: _Report) -> bool:
    """Whether the file is UTF-8; reports the first byte that is not."""
    start = written.not_utf8
    if start is None:
        return True
    line = written.raw.count(b"\n", 0, start) + 1
    report.add("syntax.encoding", None, line, f"byte {start} is not UTF-8")
    return False


def _sections(
    written: AsWritten, report: _Report, records: list[Record]
) -> tuple[dict[str, list[as_written.Section]], list[as_written.Section]]:
    """The sections of the file: each named section of the format (a list of its one copy; a
    second copy is `section.duplicate`), and the `extension` sections, in file order. A section that the format does not have and `[DELAYS]`
    are ignored and recorded (D2.4). Reports a data line before the first header."""
    for n in written.preamble.rows.lines.tolist():
        report.add("syntax.line", None, n, "this line is before the first section")
    named: dict[str, list[as_written.Section]] = {}
    extensions: list[as_written.Section] = []
    for section in written.sections:
        if section.extension is not None:
            extensions.append(section)
        elif section.name in named:
            report.add(
                "section.duplicate",
                section.name,
                section.line,
                f"[{section.name}] appears twice; the first is at line {named[section.name][0].line}",
            )
        elif section.name in _SECTIONS:
            named.setdefault(section.name, []).append(section)
        else:
            reason = "removed" if section.name == "DELAYS" else "unknown"
            records.append(Record("section", section.header, reason, section.line))
    return named, extensions


def _rows(sections: Sequence[as_written.Section], columns: tuple[as_written.Column, ...]):
    """The rows of a section (its one copy, as a list), read as a table by `columns`."""
    if len(sections) == 1 and sections[0].rows.columns == columns:
        return sections[0].rows
    tables = [s.rows for s in sections if len(s.rows)]
    if not tables:
        return as_written._typed(np.zeros(0, np.int64), "", columns, "text")
    nums = np.concatenate([t.lines for t in tables])
    return as_written._typed(nums, "\n".join(t.text for t in tables), columns, "text")


def _read_version(
    sections: list[as_written.Section], report: _Report
) -> tuple[int, int, int] | None:
    """The version of the `[VERSION]` section (as a list of its copy)."""
    if not sections:
        report.add("version.missing", None, None, "the file has no [VERSION] section")
        return None
    table = _rows(sections, as_written._VERSION)
    values: dict[str, int] = {}
    for i in range(len(table)):
        tokens = table.fields(i)
        n = int(table.lines[i])
        if (
            len(tokens) != 2
            or tokens[0] not in ("major", "minor", "revision")
            or not table.valid["value"][i]
            or tokens[0] in values
        ):
            report.add(
                "version.invalid",
                "VERSION",
                n,
                f"{table.row(i).strip()!r} is not a `major`, `minor` or `revision` line with one "
                "integer, or it repeats one",
            )
        else:
            values[tokens[0]] = int(table.values["value"][i])
    missing = [k for k in ("major", "minor", "revision") if k not in values]
    if missing:
        report.add("version.invalid", "VERSION", sections[0].line, f"{', '.join(missing)} missing")
        return None
    return values["major"], values["minor"], values["revision"]


def _read_definitions(
    sections: list[as_written.Section],
) -> dict[str, tuple[tuple[str, ...], int]]:
    """The `key value ...` lines of a section (as a list of its copy): key -> (tokens, line). A key that
    appears twice has its last value (D2.6)."""
    found: dict[str, tuple[tuple[str, ...], int]] = {}
    for section in sections:
        rows = section.rows
        for i in range(len(rows)):
            tokens = rows.fields(i)
            found[tokens[0]] = (tokens[1:], int(rows.lines[i]))
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
        value = as_written._parse("float", tokens[0]) if len(tokens) == 1 else None
        if value is not None and np.isfinite(value) and value > 0:
            rasters[attr] = float(value)
        else:
            report.add(
                "definitions.raster-invalid",
                "DEFINITIONS",
                n,
                f"{key} must be one finite number above 0, not {' '.join(tokens)!r}",
            )
    block = rasters["block_duration"]
    for key, attr in _RASTERS[:2]:
        value = rasters[attr]
        if value is None or block is None:
            continue
        ratio = max(value, block) / min(value, block)
        if abs(ratio - round(ratio)) > RATIO_TOLERANCE * ratio:
            report.add(
                "definitions.raster-commensurate",
                "DEFINITIONS",
                found[key][1],
                f"{key} {value:g} s is neither an integer multiple nor an integer divisor of "
                f"BlockDurationRaster {block:g} s",
            )
    return rasters


_KIND_DTYPE = {"int": "<i8", "float": "<f8"}


def _empty(columns: tuple[as_written.Column, ...]) -> np.ndarray:
    return np.zeros(0, np.dtype([(c.name, _KIND_DTYPE.get(c.kind, "<U1")) for c in columns]))


def _read_table(
    sections: Sequence[as_written.Section],
    columns: tuple[as_written.Column, ...],
    report: _Report,
    name: str,
) -> _Table | None:
    """The rows of a section (as a list of its copy) by `columns`, or None if a row breaks a rule of
    syntax (each is reported). `name` is the section name of the violations."""
    table = _rows(sections, columns)
    if not len(table):
        return _Table(_empty(columns), np.zeros(0, np.int64), name)
    out = _Table(table.values, table.lines, name)
    wrong = table.counts != len(columns)
    report.rows(
        "syntax.columns",
        out,
        np.flatnonzero(wrong),
        lambda r: f"{table.counts[r]} values, not the {len(columns)} expected",
    )
    bad = bool(wrong.any())
    for j, column in enumerate(columns):
        valid = table.valid[column.name] & ~wrong
        values = table.values[column.name]
        token = lambda r, j=j: table.fields(r)[j]
        if column.kind == "int":
            rows = np.flatnonzero(~valid & ~wrong)
            report.rows(
                "syntax.integer",
                out,
                rows,
                lambda r, c=column.name, token=token: f"{c}: {token(r)!r} is not an integer",
            )
        elif column.kind == "float":
            rows = np.flatnonzero(~valid & ~wrong)
            report.rows(
                "syntax.number",
                out,
                rows,
                lambda r, c=column.name, token=token: f"{c}: {token(r)!r} is not a number",
            )
            infinite = np.flatnonzero(valid & ~np.isfinite(values))
            report.rows(
                "syntax.number",
                out,
                infinite,
                lambda r, c=column.name, token=token: f"{c}: {token(r)!r} is not finite",
                choice=True,
            )
            rows = np.concatenate([rows, infinite])
        elif column.name == "use":
            rows = np.flatnonzero(valid & ~np.isin(values, list(_USES)))
            report.rows(
                "syntax.use",
                out,
                rows,
                lambda r, token=token: f"use: {token(r)!r} is not one of e r i s p o u",
            )
        else:
            continue
        bad |= bool(rows.size)
    return None if bad else out


def _check_table_ids(report: _Report, table: _Table | None, blocks: bool = False) -> None:
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
    report.rows("id.unique", table, later, lambda r: f"ID {ids[r]} is used twice", choice=blocks)


def _check_entry_types(report: _Report, entries: _Table | None) -> None:
    """`id.positive` for the `type` column of `[EXTENSIONS]`, which holds the ID of an extension
    type (spec:472). The type of each `extension` header (spec:494) is checked as it is read."""
    if entries is None:
        return
    types = entries.data["type"]
    report.rows(
        "id.positive",
        entries,
        np.flatnonzero(types <= 0),
        lambda r: f"type ID {types[r]} is not positive",
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


@dataclasses.dataclass
class _Declared:
    """A shape of `[SHAPES]` while it is read: its ID, its line, its declared number of samples
    and the row indices of its samples in the section's table."""

    id: int
    line: int
    num_samples: int
    rows: np.ndarray


def _read_shapes(
    sections: list[as_written.Section], report: _Report, path: str, interpreter: Spec
) -> dict[int, _ShapeInfo]:
    """The shapes of `[SHAPES]` (as a list of its copy), by ID (module docstring). Raises
    `NotSupported` for the first shape of the file `path` that declares more samples than
    `interpreter.max_shape_samples`, before any shape is decompressed."""
    declared: list[_Declared] = []
    broken: list[tuple[int, int]] = []  # (id, line) of a shape that is not well formed
    for section in sections:
        _shapes_of(section, report, declared, broken)
    limit = interpreter.max_shape_samples
    for d in declared:
        if limit is not None and d.num_samples > limit:
            raise NotSupported(
                f"{path}: shape {d.id} declares {d.num_samples} samples, more than the limit of "
                f"{limit} (the setting max_shape_samples of the interpreter {interpreter.name}), "
                "and the interpreter does not decompress it. A larger max_shape_samples, or "
                "None for no limit, reads the file."
            )
    shapes: dict[int, _ShapeInfo] = {}
    nothing = np.zeros(0)
    # A shape with a violation is kept as a placeholder (no samples), so that a reference to it
    # is not reported as unresolved too.
    for shape_id, line in broken:
        shapes.setdefault(shape_id, _ShapeInfo(-1, nothing, line, None))
    seen: set[int] = set()
    for d in declared:
        if d.id <= 0:
            report.add("id.positive", "SHAPES", d.line, f"shape ID {d.id} is not positive")
        if d.id in seen:
            report.add("id.unique", "SHAPES", d.line, f"shape ID {d.id} is used twice")
            continue
        seen.add(d.id)
        stored = d.rows
        if stored is None:  # a sample is not a finite number
            shapes[d.id] = _ShapeInfo(-1, nothing, d.line, None)
            continue
        if d.num_samples < 0:
            report.add(
                "syntax.negative", "SHAPES", d.line, f"num_samples {d.num_samples} is negative"
            )
            shapes[d.id] = _ShapeInfo(-1, nothing, d.line, None)
            continue
        try:
            decoded = decompress_shape(stored, d.num_samples)
        except ValueError as error:
            report.add("shape.length", "SHAPES", d.line, f"shape {d.id}: {error}")
            decoded = None
        shapes[d.id] = _ShapeInfo(d.num_samples, stored, d.line, decoded)
    return shapes


def _shapes_of(
    section: as_written.Section,
    report: _Report,
    declared: list[_Declared],
    broken: list[tuple[int, int]],
) -> None:
    """The shapes of one `[SHAPES]` section into `declared` (with their samples) and `broken`.

    The data lines of the section are its rows, its `shape_id` lines and the `num_samples` lines
    that the "as written" reading found (a comment between a `shape_id` and a `num_samples` line
    makes it read the `num_samples` line as a row). Comments are skipped. A shape is its
    `shape_id` line, the next data line as its `num_samples` line, and the data lines after it up
    to the first blank line; a blank line before the `num_samples` line ends the shape there."""
    rows = section.rows
    samples = rows.values["sample"]
    good = rows.valid["sample"] & (rows.counts == 1) & np.isfinite(samples)
    first = np.array([rows.fields(i)[:1] == ("num_samples",) for i in np.flatnonzero(~good)])
    kinds = np.zeros(len(rows), np.int64)  # 0 a sample, 1 a shape_id line, 2 a num_samples line
    if first.size:
        kinds[np.flatnonzero(~good)[first]] = 2
    head_lines = [s.line for s in section.shapes]
    count_lines = [s.num_samples_line for s in section.shapes if s.num_samples_line is not None]
    lines = np.concatenate(
        [
            rows.lines,
            np.array([h.number for h in head_lines], np.int64),
            np.array([c.number for c in count_lines], np.int64),
        ]
    )
    kind = np.concatenate([kinds, np.ones(len(head_lines), np.int64), np.full(len(count_lines), 2)])
    index = np.concatenate(
        [np.arange(len(rows)), -1 - np.arange(len(head_lines) + len(count_lines))]
    )
    texts = {h.number: h.text for h in head_lines} | {c.number: c.text for c in count_lines}
    order = np.argsort(lines, kind="stable")
    lines, kind, index = lines[order], kind[order], index[order]
    blanks = np.array(sorted(b.number for b in section.blank), np.int64)
    covered = np.zeros(len(lines), bool)
    # The positions of the data lines that are not a sample of one finite number, the head lines
    # among them, in order. `index` is negative for the head lines, so only the rows (kind 0)
    # index `good`.
    rows_at = kind == 0
    sample_ok = np.zeros(len(lines), bool)
    sample_ok[rows_at] = good[index[rows_at]]
    not_samples = np.flatnonzero(~sample_ok).tolist()

    def text(p: int) -> str:
        i = int(index[p])
        return rows.row(i) if i >= 0 else texts[int(lines[p])]

    heads = np.flatnonzero(kind == 1).tolist()
    for k, p in enumerate(heads):
        stop = heads[k + 1] if k + 1 < len(heads) else len(lines)
        line = int(lines[p])
        later = int(np.searchsorted(blanks, line))
        end = int(blanks[later]) if later < blanks.size else None
        if end is not None and (stop == len(lines) or end < lines[stop]):
            q = int(np.searchsorted(lines, end))
        else:
            q = stop
            if stop < len(lines):
                report.add(
                    "syntax.shape",
                    "SHAPES",
                    int(lines[stop]),
                    "this shape_id line has no blank line before it, which ends the shape before",
                    choice=True,
                )
            else:
                report.add(
                    "syntax.shape",
                    "SHAPES",
                    line,
                    "this shape has no blank line after it",
                    choice=True,
                )
        covered[p:q] = True
        head = text(p).split()
        shape_id = as_written._parse("int", head[1]) if len(head) == 2 else None
        if shape_id is None:
            report.add(
                "syntax.shape", "SHAPES", line, f"{text(p).strip()!r} is not `shape_id <id>`"
            )
            continue
        count = text(p + 1).split() if p + 1 < q and kind[p + 1] == 2 else []
        num = as_written._parse("int", count[1]) if len(count) == 2 else None
        if num is None:
            report.add(
                "syntax.shape", "SHAPES", line, f"shape {shape_id} has no `num_samples <n>` line"
            )
            broken.append((int(shape_id), line))
            continue
        positions = np.arange(p + 2, q)
        stored: Any = None
        bad = not_samples[
            bisect.bisect_left(not_samples, p + 2) : bisect.bisect_left(not_samples, q)
        ]
        for i in bad:
            sample = text(i).strip()
            value = as_written._parse("float", sample)
            report.add(
                "syntax.number",
                "SHAPES",
                int(lines[i]),
                f"sample {sample!r} is not one finite number",
                choice=value is not None and len(sample.split()) == 1,
            )
        if not bad:
            stored = samples[index[positions]] if positions.size else np.zeros(0)
        declared.append(_Declared(int(shape_id), line, int(num), stored))
    for p in np.flatnonzero(~covered).tolist():
        report.add("syntax.shape", "SHAPES", int(lines[p]), "this line is outside a shape")


class _Ext:
    """The `extension` sections of a file, as the interpreter reads them."""

    def __init__(self) -> None:
        self.type_ids: dict[str, int] = {}  # STRING_ID -> type ID of the file
        self.tables: dict[str, _Table | None] = {}  # known extensions with a table
        self.shims: dict[int, np.ndarray] = {}  # RF_SHIMS: object ID -> (channels, 2)
        self.ids: dict[str, _Ids | None] = {}  # known extensions: the object IDs
        self.skipped: list[str] = []  # unknown (or not in this version), not required


def _read_extensions(
    sections: list[as_written.Section],
    version: tuple[int, int, int],
    required: tuple[str, ...],
    report: _Report,
    records: list[Record],
) -> _Ext:
    ext = _Ext()
    copies: dict[str, list[as_written.Section]] = {}
    type_users: dict[int, str] = {}
    for section in sections:
        args = section.extension or ()
        name = f"extension {args[0] if args else ''}".rstrip()
        if len(args) != 2:
            report.add(
                "syntax.columns", name, section.line, "expected `extension <STRING_ID> <type>`"
            )
            continue
        string_id, type_text = args
        if section.extension_type is None:
            report.add(
                "syntax.integer", name, section.line, f"the type {type_text!r} is not an integer"
            )
            continue
        type_id = section.extension_type
        if string_id in ext.type_ids:
            report.add(
                "section.duplicate",
                name,
                section.line,
                f"extension {string_id} appears twice; the first is at line "
                f"{copies[string_id][0].line}",
            )
            continue
        if type_id <= 0:
            report.add("id.positive", name, section.line, f"type ID {type_id} is not positive")
        if type_id in type_users:
            report.add(
                "id.unique",
                name,
                section.line,
                f"type {type_id} is also the type of extension {type_users[type_id]}",
            )
        type_users[type_id] = string_id
        ext.type_ids[string_id] = type_id
        copies[string_id] = [section]
    for string_id, found in copies.items():
        name = f"extension {string_id}"
        known = string_id in _KNOWN_EXTENSIONS and version >= _KNOWN_EXTENSIONS[string_id]
        if known and string_id == "RF_SHIMS":
            ext.ids[string_id] = _read_shims(found, name, ext, report)
        elif known:
            columns = as_written._EXTENSIONS[string_id][0]
            table = _read_table(found, columns, report, name)
            _check_table_ids(report, table)
            _check_non_negative(report, table)
            ext.tables[string_id] = table
            ext.ids[string_id] = None if table is None else _Ids(table.data["id"])
        elif string_id not in required:
            ext.skipped.append(string_id)
            reason = "version" if string_id in _KNOWN_EXTENSIONS else "unknown"
            records.append(Record("extension", string_id, reason, found[0].line))
    for string_id in ("LABELSET", "LABELINC"):
        table = ext.tables.get(string_id)
        if table is not None:
            _record_labels(table, version, records)
    return ext


def _record_labels(table: _Table, version: tuple[int, int, int], records: list[Record]) -> None:
    """A record for each label of `table` that `spec` does not apply: a name that the
    specification does not list (D2.19), or a flag of 1.4.1 in an older file (D4.6). The row
    stays in the table."""
    for name, line in zip(table.data["name"].tolist(), table.nums.tolist(), strict=True):
        if name not in _LABELS:
            records.append(Record("label", name, "unknown", int(line)))
        elif name in _LABELS_1_4_1 and version < (1, 4, 1):
            records.append(Record("label", name, "version", int(line)))


def _read_shims(
    sections: list[as_written.Section], name: str, ext: _Ext, report: _Report
) -> _Ids | None:
    """The RF_SHIMS rows `id num_channels (magnitude phase)...` into `ext.shims`."""
    ok = True
    ids: list[int] = []
    for section in sections:
        rows = section.rows
        for i in range(len(rows)):
            n = int(rows.lines[i])
            cells = rows.cells(i)
            if len(cells) < 2 or not isinstance(cells[0], int) or not isinstance(cells[1], int):
                report.add("syntax.integer", name, n, "a row starts with an ID and a count")
                ok = False
                continue
            shim_id, channels = cells[0], cells[1]
            values = cells[2:]
            if channels < 0 or len(values) != 2 * channels:
                report.add(
                    "syntax.columns", name, n, f"{len(values)} values for {channels} channels"
                )
                ok = False
            elif any(v is None or not np.isfinite(v) for v in values):  # type: ignore[arg-type]
                report.add(
                    "syntax.number",
                    name,
                    n,
                    "a value is not a finite number",
                    choice=all(v is not None for v in values),
                )
                ok = False
            elif shim_id <= 0:
                report.add("id.positive", name, n, f"ID {shim_id} is not positive")
                ok = False
            elif shim_id in ext.shims:
                report.add("id.unique", name, n, f"ID {shim_id} is used twice")
                ok = False
            else:
                ext.shims[shim_id] = np.array(values, dtype=np.float64).reshape(channels, 2)
                ids.append(shim_id)
    return _Ids(np.array(ids, dtype=np.int64)) if ok else None


def _read_signature(
    sections: list[as_written.Section], written: AsWritten, report: _Report
) -> Signature | None:
    if not sections:
        return None
    found = _read_definitions(sections[:1])
    for key in ("Type", "Hash"):
        if key not in found or len(found[key][0]) != 1:
            report.add(
                "signature.invalid", "SIGNATURE", sections[0].line, f"{key} must be one value"
            )
            return None
    sig_type, sig_hash = found["Type"][0][0], found["Hash"][0][0]
    matches = None
    hashed = written.signed_bytes()
    if hashed is not None:
        try:
            digest = hashlib.new(sig_type, hashed, usedforsecurity=False).hexdigest()
        except (ValueError, TypeError):
            digest = None
        if digest is not None:
            matches = digest.lower() == sig_hash.lower()
    return Signature(sig_type, sig_hash, matches)


@dataclasses.dataclass
class _File:
    """What the interpreter has read of one file, for the checks across tables."""

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
    object of it (the objects of an extension that is not read are not checked)."""
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
    """The IDs of the events of each kind, the end of each event in nanoseconds from the start of
    its block (NaN where it cannot be known), and for the gradients the amplitude at the end.
    `arbitrary` is the `first` and `last` of each row of `[GRADIENTS]` (`_gradient_ends`)."""

    rf_ids: np.ndarray
    rf: np.ndarray
    grad_ids: np.ndarray
    grad_end: np.ndarray
    grad_last: np.ndarray
    adc_ids: np.ndarray
    adc: np.ndarray
    arbitrary: tuple[np.ndarray, np.ndarray]


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


def _rf_played(info: _ShapeInfo) -> float:
    """The duration, in RF rasters, of an RF event with the time shape `info` (module docstring):
    the number of samples times the step of a regular shape, the last time of one of points, or
    NaN for a shape with a violation or with no sample."""
    if info.samples is None or not info.samples.size:
        return np.nan
    step = rf_time_step(info.samples)
    return info.samples.size * step if step is not None else float(info.samples[-1])


def _stand_in(table: _Table | None, name: str, version: tuple[int, int, int]) -> _Table:
    """`table`, or, for a table with a violation of syntax (None), a table of the section `name`
    with no row."""
    if table is not None:
        return table
    return _Table(_empty(_layout(name, version)), np.zeros(0, np.int64), name)


def _event_ends(f: _File) -> _Ends:
    """Checks every event table against the rasters and the shapes, and gives the end of each
    event. A table with a violation of syntax has no row here (`_stand_in`): its events are not
    found, so they have no end, and the other tables are checked. A check whose raster is missing
    is skipped."""
    f = dataclasses.replace(
        f,
        rf=_stand_in(f.rf, "RF", f.version),
        grad=_stand_in(f.grad, "GRADIENTS", f.version),
        trap=_stand_in(f.trap, "TRAP", f.version),
        adc=_stand_in(f.adc, "ADC", f.version),
    )
    rep = f.report
    num, first, last, valid = _shape_columns(f)
    rf_cells = np.array([_rf_played(s) for s in f.shapes.values()] + [np.nan])
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
        rep.rows(
            "raster.rf-delay",
            f.rf,
            np.flatnonzero(_off_raster(delay, r_rf)),
            lambda r: f"delay {d['delay'][r]} us is not a multiple of RadiofrequencyRasterTime",
        )
        default = mag_ok & (d["time_id"] == 0)
        rf_end[default] = delay[default] + n_mag[default] * r_rf
        use = shaped & (num[time] == n_mag)
        rf_end[use] = delay[use] + rf_cells[time][use] * r_rf

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
    over = gshape_ok & (g["time_id"] == -1) & (f.version >= (1, 5, 0))
    rep.rows(
        "shape.oversampled-length",
        f.grad,
        np.flatnonzero(over & (n_g % 2 == 0)),
        lambda r: f"the oversampled waveform has {n_g[r]} samples, not an odd number",
    )
    g_end = np.full(len(g), np.nan)
    g_delay = g["delay"] * 1e3
    if r_grad is not None:
        ticks = np.full(len(g), np.nan)
        ticks[gshape_ok & (g["time_id"] == 0)] = n_g[gshape_ok & (g["time_id"] == 0)]
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
            np.flatnonzero(
                ~late & use & np.isfinite(g_end) & _off_raster(np.nan_to_num(g_end), r_grad)
            ),
            lambda r: f"the gradient ends at {g_end[r] / 1e3:g} us, off GradientRasterTime",
        )
    g_first, g_last = _gradient_ends(f, gshape, gshape_ok, gtime, gtime_ok, first, last)
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

    # ADC: the dwell on its raster, the start on the RF raster, and a phase shape of one sample
    # for each ADC sample (D2.15).
    a = f.adc.data
    if r_adc is not None:
        rep.rows(
            "raster.adc-dwell",
            f.adc,
            np.flatnonzero(_off_raster(a["dwell"], r_adc)),
            lambda r: f"dwell {a['dwell'][r]:g} ns is not a multiple of AdcRasterTime",
        )
    if r_rf is not None:
        rep.rows(
            "raster.adc-delay",
            f.adc,
            np.flatnonzero(_off_raster(a["delay"] * 1e3, r_rf)),
            lambda r: f"delay {a['delay'][r]} us is not a multiple of RadiofrequencyRasterTime",
        )
    if "phase_shape_id" in (a.dtype.names or ()):
        aphase, aphase_ok = shape(a["phase_shape_id"])
        rep.rows(
            "shape.event-length",
            f.adc,
            np.flatnonzero(aphase_ok & (num[aphase] != a["num_samples"])),
            lambda r: (
                f"the phase shape has {num[aphase][r]} samples, the ADC {a['num_samples'][r]}"
            ),
        )
    adc_end = a["delay"] * 1e3 + a["num_samples"] * a["dwell"]
    return _Ends(
        d["id"],
        rf_end,
        np.concatenate([g["id"], t["id"]]),
        np.concatenate([g_end, t_end]),
        np.concatenate([g_last, np.zeros(len(t))]),
        a["id"],
        adc_end,
        (g_first, g_last),
    )


def _gradient_ends(
    f: _File,
    shape_row: np.ndarray,
    shape_ok: np.ndarray,
    time_row: np.ndarray,
    time_ok: np.ndarray,
    first: np.ndarray,
    last: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The `first` and `last` of each arbitrary gradient: the columns of the file from 1.5.0.
    In a 1.4.x file, the amplitude times the first and last sample of a gradient with a time
    shape that starts at time 0, and NaN for a gradient on the default raster, with no sample,
    or with a time shape that starts later (rule `layer1.gradient-ends`)."""
    assert f.grad is not None
    g = f.grad.data
    if f.version >= (1, 5, 0):
        return g["first"], g["last"]
    use = shape_ok & (g["time_id"] != 0) & np.isfinite(first[shape_row])
    late = use & time_ok & (np.abs(first[time_row]) > FIRST_TIME_TOLERANCE)
    f.report.rows(
        "layer1.gradient-ends",
        f.grad,
        np.flatnonzero((g["time_id"] == 0) | (shape_ok & ~use) | late),
        lambda r: (
            "the file does not define the values at the ends of this gradient; "
            "Pulseq 1.5 stores them"
            if not late[r]
            else f"the time shape starts at {first[time_row[r]]:g} gradient rasters, not at 0, "
            "so the file does not define the value at the start of this gradient"
        ),
    )
    use &= ~late
    out_first = np.where(use, g["amplitude"] * first[shape_row], np.nan)
    out_last = np.where(use, g["amplitude"] * last[shape_row], np.nan)
    return out_first, out_last


def _used(table: _Table | None, column: str, shapes: Mapping[int, _ShapeInfo]) -> set[int]:
    """The IDs of the shapes of `shapes` that `column` of `table` names: the values above 0 (a
    time ID of 0 or -1 is the default raster, or half of it, and names no shape)."""
    if table is None or column not in (table.data.dtype.names or ()):
        return set()
    return {i for i in np.unique(table.data[column]).tolist() if i > 0} & set(shapes)


def _check_time_shapes(f: _File) -> None:
    """`shape.time-order` for the RF and gradient time shapes, and `raster.gradient-vertex` for
    the vertices of a gradient time shape before its last (the last is `raster.gradient-end`)."""
    for shape_id in sorted(_used(f.rf, "time_id", f.shapes)):
        info = f.shapes[shape_id]
        times = info.samples
        if times is None or not times.size:
            continue
        if times.size == 1 and rf_time_step(times) is None:
            why = f"has one sample at {times[0]:g} RF rasters: it defines no cell"
        elif times.size == 1:
            continue
        elif (np.diff(times) <= 0).any():
            why = "has times that do not increase"
        elif times[0] < 0:
            why = f"starts at {times[0]:g} RF rasters, before the start of the event"
        else:
            continue
        f.report.add("shape.time-order", "SHAPES", info.line, f"RF time shape {shape_id} {why}")
    r_grad = _raster_ns(f.rasters, "gradient")
    for shape_id in sorted(_used(f.grad, "time_id", f.shapes)):
        info = f.shapes[shape_id]
        times = info.samples
        if times is None or times.size < 1:
            continue
        if times.size > 1 and (np.diff(times) <= 0).any():
            why = "has times that do not increase"
        elif times[0] < -FIRST_TIME_TOLERANCE:
            why = f"starts at {times[0]:g} gradient rasters, before the start of the event"
        else:
            why = None
        if why is not None:
            f.report.add(
                "shape.time-order", "SHAPES", info.line, f"gradient time shape {shape_id} {why}"
            )
        inner = times[:-1]
        off = np.flatnonzero(np.abs(inner - np.round(inner)) > FIRST_TIME_TOLERANCE)
        if off.size and r_grad is not None:
            f.report.add(
                "raster.gradient-vertex",
                "SHAPES",
                info.line,
                f"gradient time shape {shape_id} has a vertex at {inner[off[0]]:g} gradient "
                "rasters, off the raster",
            )


def _check_empty_shapes(f: _File) -> None:
    """`shape.empty` for the shapes that an event uses."""
    used: set[int] = set()
    for table, columns in (
        (f.rf, ("mag_id", "phase_id", "time_id")),
        (f.grad, ("shape_id", "time_id")),
        (f.adc, ("phase_shape_id",)),
    ):
        for column in columns:
            used |= _used(table, column, f.shapes)
    for shape_id in sorted(used):
        info = f.shapes[shape_id]
        if info.num_samples == 0:
            f.report.add(
                "shape.empty",
                "SHAPES",
                info.line,
                f"shape {shape_id} has no sample, and an event uses it",
            )


def _check_amplitude_shapes(f: _File) -> None:
    """`shape.range` for the shapes that are an RF magnitude or a gradient waveform."""
    amplitude = _used(f.rf, "mag_id", f.shapes) | _used(f.grad, "shape_id", f.shapes)
    for shape_id in sorted(amplitude):
        info = f.shapes[shape_id]
        if info.samples is None or not info.samples.size:
            continue
        peak = float(np.abs(info.samples).max())
        if peak > 1 + RANGE_TOLERANCE:
            f.report.add(
                "shape.range",
                "SHAPES",
                info.line,
                f"shape {shape_id} has a sample of {peak:g} in absolute value: an amplitude shape "
                "is in [-1, 1]",
            )


def _take(values: np.ndarray, row: np.ndarray, found: np.ndarray, fill: float) -> np.ndarray:
    """`values[row]` where `found`, else `fill`."""
    if values.size == 0:
        return np.full(len(row), fill)
    return np.where(found, values[row], fill)


def _check_blocks(f: _File, ends: _Ends) -> None:
    """`block.event-too-long`, `gradient.nonzero-end-align` and `extension.per-block`."""
    r_block = _raster_ns(f.rasters, "block_duration")
    if f.blocks is None or r_block is None:
        return
    rep, b = f.report, f.blocks.data
    block_ns = b["duration_ticks"] * r_block
    pair_block, pair_entry = _walk_extensions(f)
    events = [
        ("rf", "RF", _Ids(ends.rf_ids), ends.rf),
        ("adc", "ADC", _Ids(ends.adc_ids), ends.adc),
    ]
    grad_ids = _Ids(ends.grad_ids)
    for column in ("gx", "gy", "gz"):
        events.append((column, "gradient", grad_ids, ends.grad_end))
    for column, what, ids, end_ns in events:
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
            # A gradient whose value at its end the file does not define (NaN,
            # `layer1.gradient-ends`) is not checked.
            last = _take(ends.grad_last, row, found, 0.0)
            bad = (
                found
                & np.isfinite(end)
                & np.isfinite(last)
                & (last != 0)
                & (np.abs(end - block_ns) > TOLERANCE_NS)
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
            if string_id in f.ext.ids:
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


_QUATERNION = ("q0", "qx", "qy", "qz")


def _scaled(table: np.ndarray) -> list[np.ndarray]:
    """The components of each quaternion of `table`, times the power of 2 that brings its largest
    absolute component into [0.5, 1); four zeros stay zeros (D2.18, D3.10). Their squares then
    neither overflow nor underflow. A power of 2 changes no rounding while the numbers stay above
    2^-1022, so where the components as read give a norm with no overflow or underflow, the
    quaternion divided by its norm is the same, bit for bit."""
    exponent = np.frexp(np.max(np.abs([table[c] for c in _QUATERNION]), axis=0))[1]
    return [np.ldexp(table[c], -exponent) for c in _QUATERNION]


def _check_rotations(f: _File) -> None:
    """`rotation.zero` for a quaternion of norm 0, that is four zeros (D3.10). ROTATIONS is read
    from 1.5.1 only."""
    table = f.ext.tables.get("ROTATIONS")
    if table is None:
        return
    d = table.data
    norm = np.sqrt(sum(c**2 for c in _scaled(d)))
    f.report.rows(
        "rotation.zero",
        table,
        np.flatnonzero(norm == 0),
        lambda r: f"the quaternion of rotation {d['id'][r]} has a norm of 0",
    )


def _normalized(rotations: np.ndarray) -> np.ndarray:
    """The quaternions of `rotations` (the model's table) divided by their norm (D2.18), which
    is taken from their components scaled by `_scaled`."""
    out = rotations.copy()
    scaled = _scaled(out)
    norm = np.sqrt(sum(c**2 for c in scaled))
    for c, component in zip(_QUATERNION, scaled, strict=True):
        out[c] = component / norm
    return out


def _layout(name: str, version: tuple[int, int, int]) -> tuple[as_written.Column, ...]:
    """The columns of the section `name` for `version`."""
    if name in ("RF", "GRADIENTS", "ADC"):
        return as_written._layout(name, version)[0]
    return as_written._NAMED[name][0]


def _build(written: AsWritten, report: _Report, interpreter: Spec) -> SequenceData | None:
    """The model of the file `written` by the interpreter `interpreter`, or None; every violation
    goes to `report`."""
    if not _encoding(written, report):
        return None
    records: list[Record] = []
    named, extension_sections = _sections(written, report, records)
    version = _read_version(named.get("VERSION", []), report)
    if version is None:
        return None
    found = _read_definitions(named.get("DEFINITIONS", []))
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
    shapes = _read_shapes(named.get("SHAPES", []), report, written.path, interpreter)

    def table(name: str) -> _Table | None:
        return _read_table(named.get(name, []), _layout(name, version), report, name)

    f = _File(
        version,
        report,
        rasters,
        shapes,
        _Ids(np.array(list(shapes), dtype=np.int64)),
        table("BLOCKS"),
        table("RF"),
        table("GRADIENTS"),
        table("TRAP"),
        table("ADC"),
        table("EXTENSIONS"),
        _read_extensions(extension_sections, version, required, report, records),
    )
    _check_table_ids(report, f.blocks, blocks=True)
    _check_non_negative(report, f.blocks)
    for t in (f.rf, f.grad, f.trap, f.adc, f.entries):
        _check_table_ids(report, t)
        _check_non_negative(report, t)
    _check_entry_types(report, f.entries)
    signature = _read_signature(named.get("SIGNATURE", []), written, report)
    if f.blocks is not None and len(f.blocks.data) == 0:
        report.add("blocks.empty", "BLOCKS", None, "the file has no block")
    _check_gradient_ids(f)
    _check_references(f)
    ends = _event_ends(f)
    _check_empty_shapes(f)
    _check_time_shapes(f)
    _check_amplitude_shapes(f)
    _check_blocks(f, ends)
    _check_rotations(f)
    if report:
        return None
    return _assemble(
        f, ends, found, required, signature, sorted(records, key=lambda r: r.line), interpreter
    )


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
    ends: _Ends,
    definitions: Mapping[str, tuple[tuple[str, ...], int]],
    required: tuple[str, ...],
    signature: Signature | None,
    records: list[Record],
    interpreter: Spec,
) -> SequenceData:
    """The model of a file with no violation (every table is there), by the interpreter
    `interpreter`. `ends` is what `_event_ends` gave for the file."""
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
        # With no violation, `_gradient_ends` gave a value for each gradient.
        first, last = ends.arbitrary
        grad = _model_table("grad", g_d, first=first, last=last, delay=g_d["delay"] / _US)
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
        rotations=_normalized(ext_table("rotations", "ROTATIONS")),
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
        records=tuple(records),
        signature=signature,
        origin="file",
        interpreter=interpreter,
        reading=None,
    )
