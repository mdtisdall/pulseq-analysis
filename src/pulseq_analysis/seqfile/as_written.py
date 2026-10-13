"""The "as written" reading of a Pulseq text file: its bytes into sections and typed fields, with
line numbers, without loss and without interpretation.

`read_as_written(path)` returns an `AsWritten`. It reads every file: it rejects nothing, and it
raises only `OSError` when the file cannot be read. It applies no rule of the specification and
no default: a value that the specification forbids, a row with too few or too many fields, a
section that the format does not have, and a byte that is not UTF-8 are all kept as written.
The interpreters of the package (`reading.read_seqfile`) and pulseq-checks read the file through
it. Its types are part of the contract with pulseq-checks: a change to them is noted in
`CHANGELOG.md`.

**Lines.** The file is decoded as UTF-8; a byte that is not UTF-8 is kept as a lone surrogate
(`errors="surrogateescape"`), and `AsWritten.not_utf8` gives the offset of the first one. The
text is split at each `\\n` only, so a line keeps its `\\r` and its white space. Line numbers start
at 1, and a file that ends with `\\n` has one more, empty, line after it. Each line is one of:

- **blank**: only white space (`str.isspace`);
- **comment**: its first character that is not white space is `#`;
- **header**: its first character that is not white space is `[` (a section `[NAME]`), or its
  first word is `extension`, followed by a space, a tab or the end of the line (a section
  `extension STRING_ID type`);
- **data**: any other line.

**Sections.** A section runs from its header to the line before the next header. A blank or
comment line does not end it: the section records it (`Section.blank`, `Section.comments`), and
the data lines after it belong to the section too. Which lines a reader takes is the reader's
choice (D06, D07). The lines before the first header are `AsWritten.preamble`, a section with no
header.

**Fields.** The data lines of a section are the rows of its `Table`, in file order, each split
at white space (`str.split`) into fields. A column of a table has a kind, and a field's value is
read by the kind of its column:

- `int`: an optional sign and decimal digits (`+30` is 30), in the range of a signed 64-bit
  integer;
- `float`: an optional sign and a decimal number with an optional exponent (`1.5`, `.5`, `5.`,
  `1e-3`), or `nan`, `inf` or `infinity` in any case. `1e999` is infinite;
- `text`: the field itself.

A field that is not of its column's kind, or a field that a row lacks, is not valid
(`Table.valid`), and its value is 0, NaN or "". A field after the last column has the kind
`Table.extra`. The columns are those of the specification for the section, with the names of
`model.SequenceData` and the units of the file (µs, and ns for the ADC dwell time):

- `[VERSION]`: `key` (text), `value` (int). `[DEFINITIONS]`: `key` (text), and the values as
  text. `[SIGNATURE]`: `key`, `value` (text).
- `[BLOCKS]`: `id`, `duration_ticks`, `rf`, `gx`, `gy`, `gz`, `adc`, `ext` (int).
- `[RF]`: `id`, `amplitude`, `mag_id`, `phase_id`, `time_id`, `center`, `delay`, `freq_ppm`,
  `phase_ppm`, `freq_offset`, `phase_offset`, `use` (text); a 1.4 file has no `center`,
  `freq_ppm`, `phase_ppm` and `use`.
- `[GRADIENTS]`: `id`, `amplitude`, `first`, `last`, `shape_id`, `time_id`, `delay`; a 1.4 file
  has no `first` and `last`.
- `[TRAP]`: `id`, `amplitude`, `rise`, `flat`, `fall`, `delay`.
- `[ADC]`: `id`, `num_samples`, `dwell`, `delay`, `freq_ppm`, `phase_ppm`, `freq_offset`,
  `phase_offset`, `phase_shape_id`; a 1.4 file has no `freq_ppm`, `phase_ppm` and
  `phase_shape_id`.
- `[EXTENSIONS]`: `id`, `type`, `ref`, `next`.
- `extension TRIGGERS`: `id`, `type`, `channel`, `delay`, `duration`. `extension LABELSET` and
  `extension LABELINC`: `id`, `value`, `name` (text). `extension DELAYS`: `id`, `num`,
  `offset` (float), `factor` (float), `hint` (text). `extension ROTATIONS`: `id`, `q0`, `qx`,
  `qy`, `qz` (float). `extension RF_SHIMS`: `id`, `num_channels`, and the values as float.
- Any other section (an unknown one, `[DELAYS]`, an unknown extension, the preamble): no
  column, every field as text.

The columns of `[RF]`, `[GRADIENTS]` and `[ADC]` are those of 1.4 when `AsWritten.version` is
below 1.5.0, and those of 1.5 otherwise (also with no version). Every other column is
int, except where the list says otherwise. `model.SequenceData` has the same names; the readers
convert the units and check the values.

**Shapes.** In `[SHAPES]`, a data line whose first field is `shape_id` starts a shape
(`ShapeWritten`), and the data line right after it is its `num_samples` line when the first field
of that line is `num_samples`. Every other data line of the section is a row of
`Section.rows`, with one column `sample` (float); a shape's rows run to the next `shape_id`
line or to the end of the section (a blank line does not end them here: D07 is a reader's
choice), and the rows before the first `shape_id` line belong to no shape.

**The signature.** `AsWritten.signed_bytes()` gives the bytes that the hash of `[SIGNATURE]`
covers by the specification (section 2.4): every byte before the first `[SIGNATURE]` header,
without the `\\n` right before it. The C++ reader hashes other bytes for a CRLF file (D53).

Every array of the reading is read-only. Nothing of the reading is shared with another reading.
"""

import dataclasses
import io
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

__all__ = [
    "AsWritten",
    "Column",
    "Line",
    "Section",
    "ShapeWritten",
    "Table",
    "read_as_written",
]


@dataclasses.dataclass(frozen=True, slots=True)
class Column:
    """A column of a table: its name and the kind of its values (`int`, `float` or `text`)."""

    name: str
    kind: str


class Line(NamedTuple):
    """A line of the file: its number (from 1) and its text, without the `\\n`."""

    number: int
    text: str


def _cols(spec: str) -> tuple[Column, ...]:
    """The columns of `spec`, "name:kind name ..." with the kind `int` when it is left out."""
    out = []
    for item in spec.split():
        name, _, kind = item.partition(":")
        out.append(Column(name, {"": "int", "f": "float", "t": "text"}[kind]))
    return tuple(out)


_VERSION = _cols("key:t value")
_DEFINITIONS = _cols("key:t")
_SIGNATURE = _cols("key:t value:t")
_BLOCKS = _cols("id duration_ticks rf gx gy gz adc ext")
_RF_15 = _cols(
    "id amplitude:f mag_id phase_id time_id center:f delay freq_ppm:f phase_ppm:f "
    "freq_offset:f phase_offset:f use:t"
)
_RF_14 = _cols("id amplitude:f mag_id phase_id time_id delay freq_offset:f phase_offset:f")
_GRAD_15 = _cols("id amplitude:f first:f last:f shape_id time_id delay")
_GRAD_14 = _cols("id amplitude:f shape_id time_id delay")
_TRAP = _cols("id amplitude:f rise flat fall delay")
_ADC_15 = _cols(
    "id num_samples dwell:f delay freq_ppm:f phase_ppm:f freq_offset:f phase_offset:f "
    "phase_shape_id"
)
_ADC_14 = _cols("id num_samples dwell:f delay freq_offset:f phase_offset:f")
_ENTRIES = _cols("id type ref next")
_TRIGGERS = _cols("id type channel delay duration")
_LABELS = _cols("id value name:t")
_SOFT_DELAYS = _cols("id num offset:f factor:f hint:t")
_ROTATIONS = _cols("id q0:f qx:f qy:f qz:f")
_RF_SHIMS = _cols("id num_channels")
_SAMPLES = _cols("sample:f")

# The columns of each section by name, and the kind of the fields after them. RF, GRADIENTS and
# ADC depend on the version (`_layout`).
_NAMED: dict[str, tuple[tuple[Column, ...], str]] = {
    "VERSION": (_VERSION, "text"),
    "DEFINITIONS": (_DEFINITIONS, "text"),
    "SIGNATURE": (_SIGNATURE, "text"),
    "BLOCKS": (_BLOCKS, "text"),
    "TRAP": (_TRAP, "text"),
    "EXTENSIONS": (_ENTRIES, "text"),
}
_EXTENSIONS: dict[str, tuple[tuple[Column, ...], str]] = {
    "TRIGGERS": (_TRIGGERS, "text"),
    "LABELSET": (_LABELS, "text"),
    "LABELINC": (_LABELS, "text"),
    "DELAYS": (_SOFT_DELAYS, "text"),
    "ROTATIONS": (_ROTATIONS, "text"),
    "RF_SHIMS": (_RF_SHIMS, "float"),
}

_INT = re.compile(r"[-+]?[0-9]+")
_FLOAT = re.compile(
    r"[-+]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|(?i:nan|inf|infinity))"
)
_INT_MIN, _INT_END = -(2**63), 2**63

# A structural line (blank, comment or header) of "\n" + text: the match starts at the "\n"
# before the line. Groups: 1 a comment, 2 a `[` header, 3 an `extension` header; none: blank.
_STRUCTURE = re.compile(r"\n[^\S\n]*(?:(#)|(\[)|(extension)(?=[ \t]|[^\S\n]*(?:\n|\Z))|(?=\n|\Z))")
# A data line whose first field is `shape_id`, in "\n" + the rows of [SHAPES].
_SHAPE_ID = re.compile(r"\n[^\S\n]*shape_id(?=\s|\Z)")
# The bytes of text that `numpy.loadtxt` reads as `str.split` does (`_safe`).
_SAFE_BYTES = bytes(range(0x20, 0x7F)) + b"\t\n\r"
# The white space characters (`str.isspace`) but `\n`, ` ` and `\t`. `_fast` replaces each with a
# space, which does not change the fields of a row.
_OTHER_SPACES = (
    "\r\x0b\x0c\x1c\x1d\x1e\x1f\x85\xa0\u1680"
    + "".join(map(chr, range(0x2000, 0x200B)))
    + "\u2028\u2029\u202f\u205f\u3000"
)
_TEXT_WIDTH = 64  # the width of a text column for `numpy.loadtxt`; a longer field is read slowly
_LOADTXT_DTYPE = {"int": "<i8", "float": "<f8", "text": f"<U{_TEXT_WIDTH}"}


def _read_only(*arrays: np.ndarray) -> None:
    for a in arrays:
        a.flags.writeable = False


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class Table:
    """The data rows of a section, in file order, typed by column (module docstring).

    - `columns`: the columns, and `extra` the kind of each field after them.
    - `lines`: the line number of each row (int64).
    - `counts`: the number of fields of each row (int64).
    - `values`: a structured array with one field for each column: the value of each row's
      field by the column's kind (int64, float64, or str as wide as the longest text, at least
      1), and 0, NaN or "" where the field is not valid.
    - `valid`: a structured array of bool, one field for each column: the row has the field,
      and it is of the column's kind.
    - `text`: the rows as written, joined with `\\n` (a row keeps its white space and `\\r`).

    `row(i)` gives the text of row `i`, `fields(i)` its fields, and `cells(i)` the value of
    each of its fields by kind (None for a field that is not valid), the fields after the last
    column included.
    """

    columns: tuple[Column, ...]
    extra: str
    lines: np.ndarray
    counts: np.ndarray
    values: np.ndarray
    valid: np.ndarray
    text: str
    _rows: list[str] = dataclasses.field(default_factory=list, repr=False)

    def __len__(self) -> int:
        return len(self.lines)

    def row(self, i: int) -> str:
        """The text of row `i`, as written."""
        if not self._rows and len(self.lines):
            self._rows.extend(self.text.split("\n"))
        return self._rows[i]

    def fields(self, i: int) -> tuple[str, ...]:
        """The fields of row `i`."""
        return tuple(self.row(i).split())

    def cells(self, i: int) -> tuple[int | float | str | None, ...]:
        """The value of each field of row `i` by the kind of its column (`extra` after the last
        column), or None for a field that is not of its kind."""
        kinds = [c.kind for c in self.columns]
        tokens = self.fields(i)
        return tuple(
            _parse(kinds[j] if j < len(kinds) else self.extra, token)
            for j, token in enumerate(tokens)
        )


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class ShapeWritten:
    """A shape of `[SHAPES]` as written (module docstring).

    - `line`: its `shape_id` line, and `fields` the fields of that line.
    - `id`: the second field of that line as an int, or None if it has none or it is not one.
    - `num_samples_line`: the `num_samples` line right after the `shape_id` line, or None, and
      `num_samples` its second field as an int, or None.
    - `rows`: the rows of the shape in `Section.rows` (a range of row indices): the data lines
      after these lines, up to the next `shape_id` line or the end of the section.
    """

    line: Line
    fields: tuple[str, ...]
    id: int | None
    num_samples_line: Line | None
    num_samples: int | None
    rows: range


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class Section:
    """A section as written (module docstring).

    - `line`: the line of its header (0 for the preamble), and `header` the header with its
      white space stripped ("" for the preamble).
    - `name`: for a header `[NAME]`, the text between the brackets as written (`[ BLOCKS ]`
      gives " BLOCKS "); None for a header with no `]` at its end, an `extension` header and
      the preamble.
    - `extension`: for an `extension` header, its fields after the word `extension`
      (`("LABELSET", "1")`); None otherwise. `extension_type` is its second field as an int, or
      None.
    - `end`: the last line of the section.
    - `rows`: its data lines (`Table`); in `[SHAPES]`, the lines that are not `shape_id` or
      `num_samples` lines of a shape.
    - `blank` and `comments`: its blank lines and its `#` lines, in file order.
    - `shapes`: in `[SHAPES]`, its shapes in file order; empty in any other section.
    """

    line: int
    header: str
    name: str | None
    extension: tuple[str, ...] | None
    extension_type: int | None
    end: int
    rows: Table
    blank: tuple[Line, ...]
    comments: tuple[Line, ...]
    shapes: tuple[ShapeWritten, ...]


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class AsWritten:
    """A Pulseq text file as written (module docstring).

    - `path`: the path as given; `raw`: every byte of the file.
    - `not_utf8`: the offset of the first byte that is not UTF-8, or None.
    - `line_count`: the number of lines (a file that ends with `\\n` ends with an empty line).
    - `preamble`: the lines before the first header, as a section with no header.
    - `sections`: the sections in file order, each one as many times as the file has it.
    - `version`: (major, minor, revision) from the first `[VERSION]` section: for each key, the
      value of its first row that has two fields, the key and an int; None if a key has no
      such row. It picks the columns of `[RF]`, `[GRADIENTS]` and `[ADC]`.

    `named(name)` gives the sections `[name]` in file order, `extensions()` the `extension`
    sections, and `signed_bytes()` the bytes that the signature hashes.
    """

    path: str
    raw: bytes
    not_utf8: int | None
    line_count: int
    preamble: Section
    sections: tuple[Section, ...]
    version: tuple[int, int, int] | None

    def named(self, name: str) -> tuple[Section, ...]:
        """The sections `[name]`, in file order."""
        return tuple(s for s in self.sections if s.name == name)

    def extensions(self) -> tuple[Section, ...]:
        """The `extension` sections, in file order."""
        return tuple(s for s in self.sections if s.extension is not None)

    def signed_bytes(self) -> bytes | None:
        """The bytes that the hash of `[SIGNATURE]` covers by the specification (section 2.4):
        the bytes before the line of the first `[SIGNATURE]` header, without the `\\n` that
        ends the line before it. None if the file has no such header."""
        for section in self.sections:
            if section.name == "SIGNATURE":
                start = _line_offset(self.raw, section.line)
                return self.raw[: max(0, start - 1)]
        return None


def _line_offset(raw: bytes, number: int) -> int:
    """The byte offset of the start of line `number` of `raw`."""
    if number <= 1:
        return 0
    return int(np.flatnonzero(np.frombuffer(raw, np.uint8) == ord("\n"))[number - 2]) + 1


def read_as_written(path: str | Path) -> AsWritten:
    """Read the Pulseq text file `path` as written (module docstring). Raises `OSError` when the
    file cannot be read, and nothing else."""
    raw = Path(path).read_bytes()
    not_utf8 = None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        not_utf8 = error.start
        text = raw.decode("utf-8", errors="surrogateescape")
    pieces = _split(text)
    version = _version(pieces)
    preamble, *sections = (_section(p, version) for p in pieces)
    return AsWritten(
        path=str(path),
        raw=raw,
        not_utf8=not_utf8,
        line_count=pieces[-1].end,
        preamble=preamble,
        sections=tuple(sections),
        version=version,
    )


@dataclasses.dataclass
class _Piece:
    """A section while the text is split: its header line (0 and "" for the preamble), its runs
    of data lines (first line, number of lines, text) and its blank and comment lines."""

    line: int
    header: str
    end: int = 0
    runs: list[tuple[int, int, str]] = dataclasses.field(default_factory=list)
    blank: list[Line] = dataclasses.field(default_factory=list)
    comments: list[Line] = dataclasses.field(default_factory=list)


def _split(text: str) -> list[_Piece]:
    """The preamble and the sections of `text`, in file order."""
    pieces = [_Piece(0, "")]
    number = 0  # the line of the last structural line
    start = 0  # the offset of the line after it
    for match in _STRUCTURE.finditer("\n" + text):
        at = match.start()  # the offset in `text` of the line of the match
        line = number + 1 + text.count("\n", start, at)
        if line > number + 1:
            pieces[-1].runs.append((number + 1, line - number - 1, text[start : at - 1]))
        stop = text.find("\n", at)
        stop = len(text) if stop < 0 else stop
        content = text[at:stop]
        if match.group(2) or match.group(3):
            pieces[-1].end = line - 1
            pieces.append(_Piece(line, content.strip()))
        elif match.group(1):
            pieces[-1].comments.append(Line(line, content))
        else:
            pieces[-1].blank.append(Line(line, content))
        number, start = line, stop + 1
    count = number
    if start <= len(text):  # data lines after the last structural line
        count = number + 1 + text.count("\n", start)
        pieces[-1].runs.append((number + 1, count - number, text[start:]))
    pieces[-1].end = count
    return pieces


def _name(header: str) -> tuple[str | None, tuple[str, ...] | None]:
    """The name and the extension fields of a header (`Section`)."""
    if header.startswith("["):
        return (header[1:-1] if header.endswith("]") else None), None
    if header:
        return None, tuple(header.split()[1:])
    return None, None


def _version(pieces: list[_Piece]) -> tuple[int, int, int] | None:
    """`AsWritten.version` from the first `[VERSION]` section."""
    for piece in pieces[1:]:
        if _name(piece.header)[0] == "VERSION":
            table = _table(piece.runs, _VERSION, "text")
            found: dict[str, int] = {}
            for i in range(len(table)):
                key = str(table.values["key"][i])
                if table.counts[i] == 2 and table.valid["value"][i] and key not in found:
                    found[key] = int(table.values["value"][i])
            if all(k in found for k in ("major", "minor", "revision")):
                return found["major"], found["minor"], found["revision"]
            return None
    return None


def _layout(name: str, version: tuple[int, int, int] | None) -> tuple[tuple[Column, ...], str]:
    """The columns of `[RF]`, `[GRADIENTS]` and `[ADC]` for `version`."""
    old = version is not None and version < (1, 5, 0)
    return {
        "RF": _RF_14 if old else _RF_15,
        "GRADIENTS": _GRAD_14 if old else _GRAD_15,
        "ADC": _ADC_14 if old else _ADC_15,
    }[name], "text"


def _section(piece: _Piece, version: tuple[int, int, int] | None) -> Section:
    name, extension = _name(piece.header)
    shapes: tuple[ShapeWritten, ...] = ()
    if name == "SHAPES":
        rows, shapes = _shapes(piece)
    else:
        if name in _NAMED:
            columns, extra = _NAMED[name]
        elif name in ("RF", "GRADIENTS", "ADC"):
            columns, extra = _layout(name, version)
        elif extension and extension[0] in _EXTENSIONS:
            columns, extra = _EXTENSIONS[extension[0]]
        else:
            columns, extra = (), "text"
        rows = _table(piece.runs, columns, extra)
    extension_type = None
    if extension is not None and len(extension) >= 2:
        extension_type = _parse("int", extension[1])
    return Section(
        line=piece.line,
        header=piece.header,
        name=name,
        extension=extension,
        extension_type=extension_type,  # type: ignore[arg-type]
        end=piece.end,
        rows=rows,
        blank=tuple(piece.blank),
        comments=tuple(piece.comments),
        shapes=shapes,
    )


def _shapes(piece: _Piece) -> tuple[Table, tuple[ShapeWritten, ...]]:
    """The sample rows and the shapes of a `[SHAPES]` section."""
    runs: list[tuple[int, int, str]] = []  # the runs of sample rows
    heads: list[tuple[int, Line, Line | None]] = []  # (first row, shape_id line, num_samples)
    rows = 0
    for first, n, text in piece.runs:
        starts, index, offset = [], 0, 0
        for match in _SHAPE_ID.finditer("\n" + text):
            index += text.count("\n", offset, match.start())
            offset = match.start()
            starts.append(index)
        if not starts:
            runs.append((first, n, text))
            rows += n
            continue
        lines = text.split("\n")
        if starts[0] > 0:
            runs.append((first, starts[0], "\n".join(lines[: starts[0]])))
            rows += starts[0]
        for k, i in enumerate(starts):
            stop = starts[k + 1] if k + 1 < len(starts) else len(lines)
            j, count = i + 1, None
            if j < stop and lines[j].split()[:1] == ["num_samples"]:
                count = Line(first + j, lines[j])
                j += 1
            heads.append((rows, Line(first + i, lines[i]), count))
            if j < stop:
                runs.append((first + j, stop - j, "\n".join(lines[j:stop])))
                rows += stop - j
    table = _table(runs, _SAMPLES, "text")
    shapes = []
    for k, (row, head, count) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(table)
        fields = tuple(head.text.split())
        shapes.append(
            ShapeWritten(
                line=head,
                fields=fields,
                id=_parse("int", fields[1]) if len(fields) > 1 else None,  # type: ignore[arg-type]
                num_samples_line=count,
                num_samples=_count(count),
                rows=range(row, end),
            )
        )
    return table, tuple(shapes)


def _count(line: Line | None) -> int | None:
    if line is None:
        return None
    fields = line.text.split()
    return _parse("int", fields[1]) if len(fields) > 1 else None  # type: ignore[return-value]


def _parse(kind: str, token: str) -> int | float | str | None:
    """The value of `token` by `kind`, or None if it is not of that kind."""
    if kind == "int":
        if not _INT.fullmatch(token):
            return None
        value = int(token)
        return value if _INT_MIN <= value < _INT_END else None
    if kind == "float":
        return float(token) if _FLOAT.fullmatch(token) else None
    return token


def _table(runs: Sequence[tuple[int, int, str]], columns: tuple[Column, ...], extra: str) -> Table:
    """The table of the runs of data lines (first line, number of lines, text) by `columns`."""
    lines = [np.arange(first, first + n, dtype=np.int64) for first, n, _ in runs]
    nums = np.concatenate(lines) if lines else np.zeros(0, np.int64)
    return _typed(nums, "\n".join(text for _, _, text in runs), columns, extra)


def _typed(nums: np.ndarray, text: str, columns: tuple[Column, ...], extra: str) -> Table:
    """The table of the rows `text` (joined with `\\n`), at the lines `nums`, by `columns`."""
    typed = _fast(text, len(nums), columns) if columns and len(nums) else None
    if typed is None:
        typed = _slow(text, len(nums), columns)
    values, valid, counts = typed
    nums = np.array(nums, dtype=np.int64)
    _read_only(nums, counts, values, valid)
    return Table(columns, extra, nums, counts, values, valid, text)


def _fast(
    text: str, n: int, columns: tuple[Column, ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """The table by `numpy.loadtxt` when every row has a valid field for each column and no
    other, or None. A non-finite float or a long text is left to `_slow`, which reads them by
    the rules of the module docstring."""
    if not _safe(text):
        for space in _OTHER_SPACES:
            if space in text:
                text = text.replace(space, " ")
        if not _safe(text):
            return None
    dtype = np.dtype([(c.name, _LOADTXT_DTYPE[c.kind]) for c in columns])
    try:
        data = np.loadtxt(io.StringIO(text), dtype=dtype, comments=None, ndmin=1)
    except ValueError:
        return None
    if len(data) != n:
        return None
    fields = []
    for c in columns:
        column = data[c.name]
        if c.kind == "float" and not np.isfinite(column).all():
            return None
        if c.kind == "text":
            width = int(np.char.str_len(column).max(initial=1))
            if width >= _TEXT_WIDTH:
                return None
            column = column.astype(f"<U{max(width, 1)}")
        fields.append(column)
    values = np.zeros(
        n, np.dtype([(c.name, a.dtype) for c, a in zip(columns, fields, strict=True)])
    )
    for c, a in zip(columns, fields, strict=True):
        values[c.name] = a
    valid = np.ones(n, np.dtype([(c.name, bool) for c in columns]))
    return values, valid, np.full(n, len(columns), np.int64)


def _safe(text: str) -> bool:
    """Whether `text` has only printable ASCII, tabs and line ends, with a `\\r` only before a
    `\\n` or at the end: `numpy.loadtxt` splits such text into rows and fields as `str.split`
    does."""
    if not text.isascii() or text.encode("ascii").translate(None, _SAFE_BYTES):
        return False
    return text.count("\r") == text.count("\r\n") + text.endswith("\r")


def _slow(
    text: str, n: int, columns: tuple[Column, ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The table, one field at a time."""
    rows = text.split("\n") if n else []
    counts = np.zeros(n, np.int64)
    cells: list[list[Any]] = [[] for _ in columns]
    oks: list[list[bool]] = [[] for _ in columns]
    blank = {"int": 0, "float": np.nan, "text": ""}
    for i, row in enumerate(rows):
        tokens = row.split()
        counts[i] = len(tokens)
        for j, c in enumerate(columns):
            value = _parse(c.kind, tokens[j]) if j < len(tokens) else None
            oks[j].append(value is not None)
            cells[j].append(blank[c.kind] if value is None else value)
    arrays = []
    for c, cell in zip(columns, cells, strict=True):
        if c.kind == "text":
            width = max((len(s) for s in cell), default=1)
            arrays.append(np.array(cell, dtype=f"<U{max(width, 1)}").reshape(n))
        else:
            arrays.append(np.array(cell, dtype=_LOADTXT_DTYPE[c.kind]).reshape(n))
    values = np.zeros(
        n, np.dtype([(c.name, a.dtype) for c, a in zip(columns, arrays, strict=True)])
    )
    valid = np.zeros(n, np.dtype([(c.name, bool) for c in columns]))
    for c, a, ok in zip(columns, arrays, oks, strict=True):
        values[c.name] = a
        valid[c.name] = ok
    return values, valid, counts
