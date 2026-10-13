import hashlib
import math
import random
import string
from pathlib import Path

import numpy as np
import pytest

from pulseq_analysis import seqfile
from pulseq_analysis.seqfile import as_written
from pulseq_analysis.seqfile.as_written import Column, Line, read_as_written

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ALL_FILES = sorted(SEQFILES.rglob("*.seq"))


def _write(tmp_path, text, name="file.seq"):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


def _lines_of(written):
    """Every line of the reading, (number, text), from its sections."""
    found = []
    for section in (written.preamble, *written.sections):
        if section.line:
            found.append((section.line, None))  # a header: its text is checked separately
        found += [tuple(line) for line in (*section.blank, *section.comments)]
        for shape in section.shapes:
            found.append(tuple(shape.line))
            if shape.num_samples_line is not None:
                found.append(tuple(shape.num_samples_line))
        rows = section.rows
        found += [(int(n), rows.row(i)) for i, n in enumerate(rows.lines)]
    return sorted(found, key=lambda pair: pair[0])


def _check_lossless(written):
    text = written.raw.decode("utf-8", errors="surrogateescape")
    lines = text.split("\n")
    found = _lines_of(written)
    assert [n for n, _ in found] == list(range(1, len(lines) + 1))
    assert written.line_count == len(lines)
    for n, line in found:
        if line is not None:
            assert line == lines[n - 1], n
    for section in written.sections:
        assert section.header == lines[section.line - 1].strip()


# ---- What the reading keeps ----


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: str(p.relative_to(SEQFILES)))
def test_every_fixture_is_read_without_loss(path):
    """Each line of each fixture is in the reading once, with its number and its text as
    written: a header, a blank or `#` line, a `shape_id` or `num_samples` line, or a row."""
    written = read_as_written(path)
    assert written.raw == path.read_bytes()
    _check_lossless(written)


def test_random_edits_are_read_without_loss_and_without_an_error(tmp_path):
    """Whatever the text, the reading gives an `AsWritten` that keeps every line: it raises
    nothing, and each row has the fields of its line."""
    rng = random.Random(5)
    texts = [p.read_text() for p in sorted(SEQFILES.glob("valid_*.seq"))]
    pieces = [
        "0",
        "-1",
        "+2",
        "1.5",
        "nan",
        "x",
        "",
        "1e999",
        "[BLOCKS]",
        "[SHAPES]",
        "#",
        " ",
        "extension FOO 3",
        "extension",
        "shape_id 3",
        "shape_id",
        "num_samples 2",
        "\r",
        "\xa0",
        " ",
        "\x0b",
        "é",
        "[X",
        "-9223372036854775808",
        "99999999999999999999",
    ]
    for k in range(300):
        lines = rng.choice(texts).split("\n")
        for _ in range(rng.randint(1, 4)):
            i = rng.randrange(len(lines))
            kind = rng.randrange(4)
            if kind == 0:
                lines.insert(i, rng.choice(pieces))
            elif kind == 1:
                words = lines[i].split(" ")
                words[rng.randrange(len(words))] = rng.choice(pieces)
                lines[i] = " ".join(words)
            elif kind == 2:
                del lines[i]
            else:
                lines[i] = rng.choice(pieces) + lines[i] + rng.choice(pieces)
            lines = lines or [""]
        data = "\n".join(lines).encode("utf-8")
        if k % 10 == 0:
            data = data.replace(b"\n", b"\r\n")
        if k % 15 == 0:
            data = data + b"\xff"
        written = read_as_written(_write(tmp_path, data))
        _check_lossless(written)
        for section in (written.preamble, *written.sections):
            rows = section.rows
            for i in range(len(rows)):
                assert rows.counts[i] == len(rows.row(i).split())


def test_a_byte_that_is_not_utf_8_is_kept_and_its_offset_given(tmp_path):
    """The reading does not reject a byte that is not UTF-8: it gives the offset of the first one,
    and keeps it as a lone surrogate in the text of its line."""
    written = read_as_written(SEQFILES / "bad_syntax_encoding.seq")
    raw = (SEQFILES / "bad_syntax_encoding.seq").read_bytes()
    assert written.not_utf8 == raw.index(b"\xb5")
    comments = [line.text for s in (written.preamble, *written.sections) for line in s.comments]
    assert any("\udcb5" in text for text in comments)
    assert read_as_written(SEQFILES / "valid_1_5_1.seq").not_utf8 is None


def test_blank_and_comment_lines_do_not_end_a_section(tmp_path):
    """A blank or `#` line inside a section is recorded, and the rows after it belong to the
    section (D2.5): which rows a reader takes is the reader's choice."""
    path = _write(
        tmp_path,
        "pre 1\n[VERSION]\nmajor 1\n\nminor 5\n# c\nrevision 0\n[BLOCKS]\n  \n1 2 0 0 0 0 0 0\n",
    )
    written = read_as_written(path)
    assert written.preamble.rows.lines.tolist() == [1]
    version, blocks = written.sections
    assert version.rows.lines.tolist() == [3, 5, 7]
    assert version.blank == (Line(4, ""),)
    assert version.comments == (Line(6, "# c"),)
    assert version.end == 7
    assert written.version == (1, 5, 0)
    assert blocks.blank == (Line(9, "  "), Line(11, ""))
    assert blocks.rows.lines.tolist() == [10]
    assert written.line_count == 11


def test_headers_and_their_names_as_written(tmp_path):
    """A header is a line whose first character that is not white space is `[`, or whose first
    word is `extension`; its name and its fields are kept as written."""
    path = _write(
        tmp_path,
        " [BLOCKS] \n[ BLOCKS ]\n[TRAP\nextension\tLABELSET 7\nextension\nextensions 1\n"
        "extension FOO x\n",
    )
    sections = read_as_written(path).sections
    headers = ["[BLOCKS]", "[ BLOCKS ]", "[TRAP", "extension\tLABELSET 7", "extension"]
    assert [s.header for s in sections] == [*headers, "extension FOO x"]
    assert [s.name for s in sections] == ["BLOCKS", " BLOCKS ", None, None, None, None]
    extensions = [s.extension for s in sections]
    assert extensions == [None, None, None, ("LABELSET", "7"), (), ("FOO", "x")]
    assert [s.extension_type for s in sections] == [None, None, None, 7, None, None]
    # Not a header: its first word is not `extension`.
    assert sections[4].rows.text == "extensions 1"


def test_the_signed_bytes_are_those_of_the_specification(tmp_path):
    """`signed_bytes` is every byte before the `[SIGNATURE]` line, without the `\\n` that ends the
    line before it (spec 2.4). For a LF file it gives the stored md5; for the CRLF fixture, the
    md5 that the rule of the specification gives (spec:223)."""
    signed = read_as_written(SEQFILES / "valid_1_5_1.seq").signed_bytes()
    raw = (SEQFILES / "valid_1_5_1.seq").read_bytes()
    assert signed == raw[: raw.index(b"\n[SIGNATURE]")]
    stored = raw.split(b"Hash ")[1].split()[0].decode()
    assert hashlib.md5(signed).hexdigest() == stored
    crlf = read_as_written(SEQFILES / "valid_crlf.seq").signed_bytes()
    assert hashlib.md5(crlf).hexdigest() == "e06b91d84d3fba7303a915e068320754"
    assert read_as_written(SEQFILES / "valid_no_signature.seq").signed_bytes() is None
    assert read_as_written(_write(tmp_path, "[SIGNATURE]\n")).signed_bytes() == b""


def test_the_arrays_of_the_reading_are_read_only():
    written = read_as_written(SEQFILES / "valid_1_5_1.seq")
    for section in (written.preamble, *written.sections):
        rows = section.rows
        for array in (rows.lines, rows.counts, rows.values, rows.valid):
            assert not array.flags.writeable


def test_seqfile_exports_the_reading():
    assert seqfile.read_as_written is read_as_written
    assert seqfile.AsWritten is as_written.AsWritten
    assert seqfile.Table is as_written.Table


# ---- Fields and their values ----


def test_the_1_5_1_fixture_has_its_values_as_written():
    """The tables of the 1.5.1 fixture have the columns of 1.5, the values of the text in the
    units of the file (µs, and ns for the ADC dwell), and the line of each row."""
    written = read_as_written(SEQFILES / "valid_1_5_1.seq")
    assert written.version == (1, 5, 1)
    (rf,) = written.named("RF")
    assert [c.name for c in rf.rows.columns][-2:] == ["phase_offset", "use"]
    assert rf.rows.values.tolist() == [(1, 1000.0, 1, 2, 0, 50.0, 100, 0.0, 0.0, 0.0, 0.0, "e")]
    assert rf.rows.lines.tolist() == [35]
    (adc,) = written.named("ADC")
    assert adc.rows.values["dwell"].tolist() == [25000.0, 25000.0]
    (definitions,) = written.named("DEFINITIONS")
    assert definitions.rows.columns == (Column("key", "text"),)
    assert definitions.rows.extra == "text"
    assert definitions.rows.fields(0)[0] == definitions.rows.values["key"][0]
    (shims,) = [s for s in written.extensions() if s.extension[0] == "RF_SHIMS"]
    assert shims.rows.extra == "float"
    assert shims.rows.cells(0)[:2] == (1, 2)
    assert all(isinstance(v, float) for v in shims.rows.cells(0)[2:])


def test_a_1_4_file_has_the_columns_of_1_4():
    written = read_as_written(SEQFILES / "valid_1_4_1.seq")
    assert written.version == (1, 4, 1)
    names = {s.name: [c.name for c in s.rows.columns] for s in written.sections if s.name}
    assert names["RF"] == [
        "id",
        "amplitude",
        "mag_id",
        "phase_id",
        "time_id",
        "delay",
        "freq_offset",
        "phase_offset",
    ]
    assert names["GRADIENTS"] == ["id", "amplitude", "shape_id", "time_id", "delay"]
    assert "phase_shape_id" not in names["ADC"]


def test_a_file_with_no_version_has_the_columns_of_1_5(tmp_path):
    written = read_as_written(_write(tmp_path, "[RF]\n1 2 3\n"))
    assert written.version is None
    assert written.sections[0].rows.columns[-1] == Column("use", "text")


def test_each_field_is_read_by_the_kind_of_its_column(tmp_path):
    """The fields of the tables as written (spec:176, spec:293-455): `30.5` in an integer column is not an int, `+30` is 30,
    `nan` is a float, a row of 7 values lacks its eighth, and a row of 9 keeps the ninth."""
    path = _write(
        tmp_path,
        "[BLOCKS]\n1 30.5 0 0 0 0 0 0\n2 +30 0 0 0 0 0 0\n3 1 0 0 0 0 0\n4 1 0 0 0 0 0 0 9\n"
        "[TRAP]\n1 nan 10 20 10 -9223372036854775808\n2 1e999 1 1 1 9223372036854775808\n",
    )
    blocks, trap = read_as_written(path).sections
    rows = blocks.rows
    assert rows.counts.tolist() == [8, 8, 7, 9]
    assert rows.valid["duration_ticks"].tolist() == [False, True, True, True]
    assert rows.values["duration_ticks"].tolist() == [0, 30, 1, 1]
    assert rows.valid["ext"].tolist() == [True, True, False, True]
    assert rows.fields(0)[1] == "30.5"
    assert rows.cells(3)[-1] == "9"
    t = trap.rows
    assert math.isnan(t.values["amplitude"][0]) and t.valid["amplitude"][0]
    assert t.values["amplitude"][1] == np.inf
    assert t.values["delay"][0] == -(2**63) and t.valid["delay"][0]
    assert not t.valid["delay"][1]


def test_the_fast_and_the_slow_typing_agree(tmp_path):
    """`numpy.loadtxt` (the fast typing) and the typing one field at a time give the same
    values, validity and counts, for random rows of tokens at the edges of each kind."""
    rng = random.Random(3)
    tokens = [
        "0",
        "-0",
        "+7",
        "007",
        "12",
        "-9223372036854775808",
        "9223372036854775807",
        "9223372036854775808",
    ]
    tokens += [
        "1.5",
        "-.5",
        "5.",
        "+1e3",
        "1E-3",
        "1e999",
        "nan",
        "NaN",
        "-inf",
        "Infinity",
        "1_0",
        "0x10",
        "e",
        "1e",
        "-",
        ".",
        "abc",
        "u",
        "é",
    ]
    seps = [" ", "  ", "\t", " \t", "\xa0", "\x0b"]
    columns = (Column("a", "int"), Column("b", "float"), Column("c", "text"))
    for _ in range(400):
        rows = []
        for _ in range(rng.randint(1, 5)):
            n = rng.choice([3, 3, 3, 2, 4])
            row = rng.choice(seps).join(rng.choice(tokens) for _ in range(n))
            rows.append(rng.choice(["", " "]) + row + rng.choice(["", " ", "\r"]))
        text = "\n".join(rows)
        fast = as_written._fast(text, len(rows), columns)
        slow = as_written._slow(text, len(rows), columns)
        if fast is None:
            continue
        for f, s in zip(fast, slow, strict=True):
            assert f.dtype == s.dtype, text
            for name in f.dtype.names or (None,):
                a, b = (f, s) if name is None else (f[name], s[name])
                assert np.array_equal(a, b, equal_nan=a.dtype.kind == "f"), text


def test_the_other_spaces_are_the_white_space_of_str_split():
    spaces = {chr(c) for c in range(0x110000) if chr(c).isspace()} - {"\n", " ", "\t"}
    assert set(as_written._OTHER_SPACES) == spaces


# ---- Shapes ----


def test_the_shapes_and_their_rows(tmp_path):
    """A `shape_id` line starts a shape, the line right after it is its `num_samples` line, and
    its rows run to the next `shape_id` line, past a blank line (D3.11 is a reader's choice)."""
    path = _write(
        tmp_path,
        "[SHAPES]\n0.5\n\nshape_id 1\nnum_samples 2\n1\n2\n\n3\nshape_id x\n\nnum_samples 1\n4\n"
        "shape_idX 2\nshape_id 3 4\n",
    )
    (shapes,) = read_as_written(path).sections
    rows = shapes.rows
    one, two, three = shapes.shapes
    assert (one.id, one.num_samples) == (1, 2)
    assert (one.line, one.num_samples_line) == (Line(4, "shape_id 1"), Line(5, "num_samples 2"))
    assert rows.lines[one.rows.start : one.rows.stop].tolist() == [6, 7, 9]
    assert (two.id, two.num_samples_line, two.fields) == (None, None, ("shape_id", "x"))
    assert rows.lines[two.rows.start : two.rows.stop].tolist() == [12, 13, 14]
    assert rows.valid["sample"].tolist() == [True, True, True, True, False, True, False]
    assert (three.id, three.fields, len(three.rows)) == (3, ("shape_id", "3", "4"), 0)
    assert rows.lines[0] == 2  # before the first shape: no shape has it
    assert shapes.blank == (Line(3, ""), Line(8, ""), Line(11, ""), Line(16, ""))


def test_a_section_other_than_shapes_has_no_shapes():
    written = read_as_written(SEQFILES / "valid_1_5_1.seq")
    assert all(not s.shapes for s in written.sections if s.name != "SHAPES")


@pytest.mark.parametrize("width", [1, 63, 64, 100])
def test_a_text_field_of_any_length_is_kept(tmp_path, width):
    name = "".join(random.Random(width).choice(string.ascii_letters) for _ in range(width))
    path = _write(tmp_path, f"extension LABELSET 1\n1 2 {name}\n2 3 x\n")
    (labels,) = read_as_written(path).sections
    assert labels.rows.values["name"].tolist() == [name, "x"]
    assert labels.rows.values.dtype["name"] == np.dtype(f"<U{width}")
