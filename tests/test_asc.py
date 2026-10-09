import dataclasses
import re

import pytest
from pypulseq.utils.safe_pns_prediction import safe_example_hw

from pulseq_analysis.asc import (
    hardware_from_asc,
    hardware_name,
    read_gradient_asc,
    safe_hardware,
)
from pulseq_analysis.safe import SAFE_FIELDS, SafeHardware

# Every form of a line that `read_gradient_asc` reads, in the layout of a scanner file: a
# comment line, blank lines, a line with no `=` (left out), strings, integers, floats (with an
# exponent, negative), indices, comments after a value, and a field after the end marker.
_FORMS = """\
### ASCCONV BEGIN @Checksum=mp2:0 ###
# a comment line

some text without an equals sign
a.b[0] = 1
a.b[1] = -2.5e-3     # a comment
a.c = "text with spaces"   // another comment
d = 'x'
e[1][2].f = 7
g = 1.5
h = 2e3
i = ""
j = 0
k = -1
### ASCCONV END ###
l = 5
"""
_FORMS_FIELDS = {
    "a": {"b": {0: 1, 1: -0.0025}, "c": "text with spaces"},
    "d": "x",
    "e": {1: {2: {"f": 7}}},
    "g": 1.5,
    "h": 2000.0,
    "i": "",
    "j": 0,
    "k": -1.0,
}


def test_asc_file_with_a_missing_include(write_gradient_asc):
    path = write_gradient_asc(split=True)
    safety = path.with_name(f"{path.stem}_GSWD_SAFETY.asc")
    safety.unlink()
    with pytest.raises(FileNotFoundError, match=f"{path.name} includes {safety.name}"):
        read_gradient_asc(path)


def test_asc_files_that_include_each_other(tmp_path):
    (tmp_path / "a.asc").write_text("x = 1\n$INCLUDE b.asc\n")
    (tmp_path / "b.asc").write_text("y = 2\n$INCLUDE a.asc\n")
    with pytest.raises(ValueError, match=r"a\.asc.*b\.asc.*a\.asc"):
        read_gradient_asc(tmp_path / "a.asc")


def test_asc_file_that_includes_itself(tmp_path):
    (tmp_path / "a.asc").write_text("x = 1\n$INCLUDE a.asc\n")
    with pytest.raises(ValueError, match=r"a\.asc.*a\.asc"):
        read_gradient_asc(tmp_path / "a.asc")


def test_asc_file_included_by_two_branches_is_not_a_cycle(tmp_path):
    (tmp_path / "shared.asc").write_text("z = 3\n")
    (tmp_path / "b.asc").write_text("$INCLUDE shared.asc\n")
    (tmp_path / "c.asc").write_text("$INCLUDE shared.asc\n")
    main = tmp_path / "main.asc"
    main.write_text("x = 1\n$INCLUDE b.asc\n$INCLUDE c.asc\n")
    assert read_gradient_asc(main) == {"x": 1, "z": 3}


def test_included_fields_replace_fields_with_the_same_name(tmp_path):
    (tmp_path / "inc.asc").write_text('a.b[1] = 3\nc = "new"\n')
    main = tmp_path / "main.asc"
    main.write_text('a.b[0] = 1\na.b[1] = 2\nc = "old"\n$INCLUDE inc.asc\n')
    assert read_gradient_asc(main) == {"a": {"b": {0: 1, 1: 3}}, "c": "new"}


@pytest.mark.parametrize(
    "line",
    [
        "$INCLUDE inc.asc",
        "$include inc.asc",
        "$Include inc.asc",
        '$INCLUDE "inc.asc"',
        "  $INCLUDE inc.asc  # the SAFE parameters",
        "$INCLUDE inc.asc // the SAFE parameters",
        '$INCLUDE "inc.asc" # the SAFE parameters',
    ],
    ids=["upper", "lower", "mixed", "quoted", "hash-comment", "slash-comment", "quoted-comment"],
)
def test_include_line_forms_that_read_the_included_file(tmp_path, line):
    (tmp_path / "inc.asc").write_text("y = 2\n")
    main = tmp_path / "main.asc"
    main.write_text(f"x = 1\n{line}\n")
    assert read_gradient_asc(main) == {"x": 1, "y": 2}


def test_include_line_with_a_quoted_name_with_spaces(tmp_path):
    (tmp_path / "my safety.asc").write_text("y = 2\n")
    main = tmp_path / "main.asc"
    main.write_text('x = 1\n$INCLUDE "my safety.asc" # the SAFE parameters\n')
    assert read_gradient_asc(main) == {"x": 1, "y": 2}


@pytest.mark.parametrize(
    "line",
    [
        "$INCLUDE",
        "$include   ",
        "$INCLUDE inc.asc junk",
        '$INCLUDE "inc.asc" junk',
        '$INCLUDE "inc.asc',
    ],
    ids=["no-name", "no-name-lower", "junk", "quoted-junk", "open-quote"],
)
def test_include_line_that_does_not_parse_raises(tmp_path, line):
    (tmp_path / "inc.asc").write_text("y = 2\n")
    main = tmp_path / "main.asc"
    main.write_text(f"x = 1\n{line}\n")
    with pytest.raises(ValueError, match=rf"main\.asc.*line 2.*{re.escape(repr(line))}"):
        read_gradient_asc(main)


def test_hardware_name():
    assert hardware_name({"asCOMP": {0: {"tName": "GPAK2309"}}}) == "GPAK2309"
    assert hardware_name({"asCOMP": {"tName": "MP_GPA_TEST"}}) == "MP_GPA_TEST"
    assert hardware_name({}) == "unknown"


def _example_fields() -> dict:
    """The fields of pypulseq's example hardware, as `dataclasses.asdict` gives them."""
    return {
        axis: {field: getattr(getattr(safe_example_hw(), axis), field) for field in SAFE_FIELDS}
        for axis in "xyz"
    }


def _remove_lines(path, key: str) -> None:
    """Removes the lines with `key` from the file `path` and from the files that it includes
    (the files of the directory that start with the stem of `path`)."""
    for file in path.parent.glob(f"{path.stem}*.asc"):
        lines = file.read_bytes().split(b"\n")
        file.write_bytes(b"\n".join(line for line in lines if key.encode() not in line))


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_read_gradient_asc_reads_every_form_of_a_line(tmp_path, newline):
    path = tmp_path / "forms.asc"
    path.write_bytes(_FORMS.replace("\n", newline).encode())
    fields = read_gradient_asc(path)
    assert fields == _FORMS_FIELDS
    assert type(fields["a"]["b"][0]) is int
    assert type(fields["a"]["b"][1]) is float
    assert type(fields["h"]) is float
    assert type(fields["j"]) is int
    assert type(fields["k"]) is float
    assert type(fields["d"]) is str


def test_read_gradient_asc_leaves_out_the_fields_after_the_end_marker_of_an_included_file(
    tmp_path,
):
    (tmp_path / "inc.asc").write_text("y = 2\n### ASCCONV END ###\nz = 3\n")
    main = tmp_path / "main.asc"
    main.write_text("x = 1\n$INCLUDE inc.asc\n")
    assert read_gradient_asc(main) == {"x": 1, "y": 2}


def test_read_gradient_asc_gives_the_fields_that_pypulseqs_readasc_gives(tmp_path):
    """For the file of every form, the plain file of the fixture and the main file of the
    scanner layout (without the included file), the fields equal the first result of
    pypulseq's `readasc`."""
    readasc = pytest.importorskip("pypulseq.utils.siemens.readasc").readasc
    forms = tmp_path / "forms.asc"
    forms.write_text(_FORMS)
    assert read_gradient_asc(forms) == readasc(str(forms))[0]


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_read_gradient_asc_gives_the_fields_of_a_fixture_file_that_readasc_gives(
    write_gradient_asc, split
):
    readasc = pytest.importorskip("pypulseq.utils.siemens.readasc").readasc
    path = write_gradient_asc(split=split)
    expected = readasc(str(path))[0]
    if split:
        safety = path.with_name(f"{path.stem}_GSWD_SAFETY.asc")
        expected = {**expected, **readasc(str(safety))[0]}
        # the main file has the `asCOMP` and `asGPAParameters` fields, the safety file the
        # `GradPatSup` field
        assert set(expected) == {"asCOMP", "asGPAParameters", "GradPatSup"}
    assert read_gradient_asc(path) == expected


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("a = 1-2", "cannot read the number '1-2'"),
        ("a = b", "cannot read the field 'a = b'"),
        ("a = ", "cannot read the field 'a ='"),
        ("a..b = 1", "cannot read the field name 'a..b'"),
        ("a[x] = 1", r"cannot read the field name 'a\[x\]'"),
        ("x.y = 2", "cannot set a field under 'x', which has the value 5"),
    ],
    ids=["number", "not-a-value", "no-value", "empty-part", "index-not-a-number", "under-a-value"],
)
def test_read_gradient_asc_raises_for_a_line_it_cannot_read(tmp_path, line, message):
    """The error is a `ValueError` that names the file, the line number and the reason. The
    first line of the file is `x = 5`."""
    path = tmp_path / "main.asc"
    path.write_text(f"x = 5\n{line}\n")
    with pytest.raises(ValueError, match=rf"main\.asc, line 2: {message}"):
        read_gradient_asc(path)


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_hardware_from_asc_gives_the_safe_hardware_and_the_name_of_the_file(
    write_gradient_asc, split
):
    """`hardware_from_asc(path)` is the pair `(safe_hardware(asc), hardware_name(asc))` of
    `asc = read_gradient_asc(path)`, for the plain layout and for the layout of a scanner file
    (a main file that includes the PNS parameters with `$INCLUDE`). The `SafeHardware` has the
    name of the file and the fields of pypulseq's example hardware, which the fixture writes."""
    path = write_gradient_asc(split=split)
    asc = read_gradient_asc(path)

    hardware = hardware_from_asc(path)
    assert isinstance(hardware, tuple)
    struct, label = hardware
    assert isinstance(struct, SafeHardware)
    assert label == hardware_name(asc) == struct.name == "MP_GPA_TEST"
    assert struct == safe_hardware(asc)
    for axis, fields in _example_fields().items():
        assert dataclasses.asdict(getattr(struct, axis)) == fields


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_hardware_from_asc_has_the_fields_of_pypulseqs_asc_to_hw(write_gradient_asc, split):
    """The attributes of the `SafeHardware` of a file are those of the namespace that
    pypulseq's `asc_to_hw` gives for its fields: the same attribute names, and for each axis
    the same names and values."""
    asc_to_hw = pytest.importorskip("pypulseq.utils.siemens.asc_to_hw").asc_to_hw
    path = write_gradient_asc(split=split)
    expected = asc_to_hw(read_gradient_asc(path))

    struct, _ = hardware_from_asc(path)
    assert vars(struct).keys() == vars(expected).keys()
    for axis in "xyz":
        assert dataclasses.asdict(getattr(struct, axis)) == vars(getattr(expected, axis))


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_safe_hardware_is_named_after_the_component_of_the_file(write_gradient_asc, split):
    """The name is `hardware_name(asc)`, also for a scanner file (`asCOMP[0].tName`), and
    "unknown" without a component name."""
    asc = read_gradient_asc(write_gradient_asc(split=split, name="OTHER_NAME"))
    assert safe_hardware(asc).name == "OTHER_NAME"
    asc.pop("asCOMP")
    assert safe_hardware(asc).name == "unknown"


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
@pytest.mark.parametrize("function", ["hardware_from_asc", "safe_hardware"])
def test_a_file_without_gradient_scale_factors_is_refused(write_gradient_asc, split, function):
    """A file with no `asGPAParameters` field raises `ValueError` that names the field of the
    first axis and says why there is no default, from `hardware_from_asc` and from
    `safe_hardware`. (pypulseq's `asc_to_hw` prints a warning and assumes 1/pi.)"""
    path = write_gradient_asc(split=split, scale_factors=False)
    assert "asGPAParameters" not in path.read_text()
    call = (
        hardware_from_asc
        if function == "hardware_from_asc"
        else lambda p: safe_hardware(read_gradient_asc(p))
    )
    with pytest.raises(ValueError, match=r"no gradient scale factor.*flGScaleFactorX") as caught:
        call(path)
    assert "does not assume one" in str(caught.value)


@pytest.mark.parametrize("axis", "XYZ")
def test_a_file_without_the_gradient_scale_factor_of_one_axis_is_refused(write_gradient_asc, axis):
    path = write_gradient_asc()
    _remove_lines(path, f"flGScaleFactor{axis}")
    with pytest.raises(ValueError, match=rf"no gradient scale factor.*flGScaleFactor{axis}\b"):
        hardware_from_asc(path)


@pytest.mark.parametrize(
    ("split", "key", "named"),
    [
        (False, "flGSWDTauY[1]", "flGSWDTauY[1]"),
        (False, "flGSWDAZ[2]", "flGSWDAZ[2]"),
        (False, "flGSWDStimulationLimitX", "flGSWDStimulationLimitX"),
        (False, "flGSWDStimulationThresholdZ", "flGSWDStimulationThresholdZ"),
        (True, "flGSWDTauY[1]", "GradPatSup.Phys.PNS.flGSWDTauY[1]"),
        (True, "flGSWDStimulationLimitX", "GradPatSup.Phys.PNS.flGSWDStimulationLimitX"),
    ],
    ids=["tau", "a", "limit", "threshold", "split-tau", "split-limit"],
)
def test_a_file_without_a_pns_field_is_refused_and_the_error_names_it(
    write_gradient_asc, split, key, named
):
    path = write_gradient_asc(split=split)
    _remove_lines(path, f"{key} =")
    with pytest.raises(ValueError, match=re.escape(f"the .asc file has no field {named}")):
        hardware_from_asc(path)


def test_a_scanner_file_without_the_pns_parameters_is_refused(write_gradient_asc):
    """A file with a `GradPatSup` field but no `Phys.PNS` under it names `GradPatSup.Phys.PNS`."""
    asc = read_gradient_asc(write_gradient_asc(split=True))
    asc["GradPatSup"] = {"Phys": {}}
    with pytest.raises(ValueError, match=re.escape("no field GradPatSup.Phys.PNS")):
        safe_hardware(asc)


def test_a_file_with_an_a_sum_that_is_not_1_is_refused(write_gradient_asc):
    path = write_gradient_asc()
    text = path.read_text().replace("flGSWDAX[0] = 0.4", "flGSWDAX[0] = 0.9")
    path.write_text(text)
    with pytest.raises(ValueError, match=r"a1 \+ SafeAxis\.a2 \+ SafeAxis\.a3 must be 1"):
        hardware_from_asc(path)
