import pytest
from pypulseq.utils.siemens.asc_to_hw import asc_to_hw

from pulseq_analysis.asc import hardware_from_asc, hardware_name, read_gradient_asc


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


def test_hardware_name():
    assert hardware_name({"asCOMP": {0: {"tName": "GPAK2309"}}}) == "GPAK2309"
    assert hardware_name({"asCOMP": {"tName": "MP_GPA_TEST"}}) == "MP_GPA_TEST"
    assert hardware_name({}) == "unknown"


@pytest.mark.parametrize("split", [False, True], ids=["plain", "split"])
def test_hardware_from_asc_gives_the_struct_and_the_name_of_the_file(write_gradient_asc, split):
    """`hardware_from_asc(path)` is the pair `(asc_to_hw(asc), hardware_name(asc))` of
    `asc = read_gradient_asc(path)`, field by field, for the plain layout and for the layout
    of a scanner file (a main file that includes the PNS parameters with `$INCLUDE`)."""
    path = write_gradient_asc(split=split)
    asc = read_gradient_asc(path)
    expected = asc_to_hw(asc)

    hardware = hardware_from_asc(path)
    assert isinstance(hardware, tuple)
    struct, label = hardware
    assert label == hardware_name(asc) == "MP_GPA_TEST"
    assert vars(struct).keys() == vars(expected).keys()
    for axis in "xyz":
        assert vars(getattr(struct, axis)) == vars(getattr(expected, axis))
