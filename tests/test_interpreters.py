"""Tests of the plugin interpreters (`seqfile.interpreters`, P21 of
`docs/plans/parser-redesign.md`): the package finds an interpreter of another distribution
through the entry-point group `pulseq_analysis.interpreters`, reads and decodes a file through
it, and has no reference to any plugin. A fake plugin (`Fake`, in this module) stands for one.
"""

import dataclasses
import importlib.metadata
import re
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from pulseq_analysis import seqfile, synth
from pulseq_analysis.analyses import load
from pulseq_analysis.seqfile import Spec, interpreters, read_seqfile
from pulseq_analysis.synth.events import decode_rf

ROOT = Path(__file__).resolve().parents[1]
SEQFILES = ROOT / "tests" / "seqfiles"


@dataclasses.dataclass(frozen=True, slots=True)
class Fake:
    """A plugin interpreter: `spec`'s model, under its own name, with a decoding that says
    which interpreter made it."""

    name: ClassVar[str] = "fake"
    protocol: ClassVar[int] = 1
    setting: str = "default"
    max_shape_samples: int | None = interpreters.DEFAULT_MAX_SHAPE_SAMPLES

    def read(self, path: Path) -> seqfile.SequenceData:
        assert isinstance(path, Path)
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: seqfile.SequenceData, session=None) -> tuple[str, "Fake"]:
        return ("fake decoding", data.interpreter)


@dataclasses.dataclass(frozen=True, slots=True)
class Misnamed(Fake):
    name: ClassVar[str] = "other"


@dataclasses.dataclass(frozen=True, slots=True)
class Unlimited:
    """A plugin interpreter of protocol version 1 with no setting `max_shape_samples`."""

    name: ClassVar[str] = "unlimited"
    protocol: ClassVar[int] = 1

    def read(self, path: Path) -> seqfile.SequenceData:
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: seqfile.SequenceData, session=None) -> tuple[str, "Unlimited"]:
        return ("unlimited decoding", data.interpreter)


@dataclasses.dataclass(frozen=True, slots=True)
class OtherLimit(Unlimited):
    """A plugin interpreter of protocol version 1 whose `max_shape_samples` has another
    default."""

    name: ClassVar[str] = "other-limit"
    max_shape_samples: int | None = 1000


@dataclasses.dataclass(frozen=True, slots=True)
class Limited(Fake):
    """`Fake` that follows the convention of `max_shape_samples`: it checks the setting as `Spec`
    does, `str` gives it when it is not its default, and `read` reads with
    `Spec(max_shape_samples=...)` of its setting."""

    def __post_init__(self) -> None:
        limit = interpreters._max_shape_samples(self.max_shape_samples)
        object.__setattr__(self, "max_shape_samples", limit)

    def __str__(self) -> str:
        if self.max_shape_samples == interpreters.DEFAULT_MAX_SHAPE_SAMPLES:
            return self.name
        return f"{self.name}(max_shape_samples={self.max_shape_samples!r})"

    def read(self, path: Path) -> seqfile.SequenceData:
        chosen = Spec(max_shape_samples=self.max_shape_samples)
        return dataclasses.replace(read_seqfile(path, chosen), interpreter=self)


@dataclasses.dataclass(frozen=True, slots=True)
class AtLimit(Limited):
    """`Limited` that checks the shapes of the "as written" reading itself, and also refuses a
    shape of exactly `max_shape_samples` samples."""

    def read(self, path: Path) -> seqfile.SequenceData:
        limit = self.max_shape_samples
        for section in seqfile.read_as_written(path).named("SHAPES"):
            for shape in section.shapes:
                if limit is not None and (shape.num_samples or 0) >= limit:
                    raise seqfile.NotSupported(
                        f"{path}: shape {shape.id} declares {shape.num_samples} samples, "
                        f"max_shape_samples is {limit}"
                    )
        chosen = Spec(max_shape_samples=None)
        return dataclasses.replace(read_seqfile(path, chosen), interpreter=self)


@dataclasses.dataclass(frozen=True, slots=True)
class Unchecked(Limited):
    """`Limited` that reads with `spec`'s default, whatever its own setting."""

    def read(self, path: Path) -> seqfile.SequenceData:
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)


@dataclasses.dataclass(frozen=True, slots=True)
class Verbose(Limited):
    """`Limited` whose `str` gives every setting, also a default."""

    def __str__(self) -> str:
        return repr(self)


@dataclasses.dataclass(frozen=True, slots=True)
class Coarse(Limited):
    """`Limited` whose limit is never below 1000 samples."""

    def read(self, path: Path) -> seqfile.SequenceData:
        limit = self.max_shape_samples
        chosen = Spec(max_shape_samples=None if limit is None else max(limit, 1000))
        return dataclasses.replace(read_seqfile(path, chosen), interpreter=self)


@dataclasses.dataclass(frozen=True, slots=True)
class Terse(Limited):
    """`Limited` whose `NotSupported` gives no path, number or setting."""

    def read(self, path: Path) -> seqfile.SequenceData:
        try:
            return Limited.read(self, path)
        except seqfile.NotSupported:
            raise seqfile.NotSupported("a shape is too large") from None


@dataclasses.dataclass(frozen=True, slots=True)
class Forgetful(Limited):
    """`Limited` whose model records the interpreter with its default settings."""

    def read(self, path: Path) -> seqfile.SequenceData:
        return dataclasses.replace(Limited.read(self, path), interpreter=Limited())


@dataclasses.dataclass(frozen=True, slots=True)
class Resampling(Limited):
    """`Limited` that resamples each RF pulse of points on the RF raster, as `cpp-siemens` does,
    into `int(0.5 + t)` cells for the last time `t` of its time shape (in RF rasters), and follows
    the convention for them: more cells than `max_shape_samples` is `NotSupported`, with the path,
    the number of cells and the limit, and the name of the setting."""

    def read(self, path: Path) -> seqfile.SequenceData:
        data = read_seqfile(path, Spec(max_shape_samples=self.max_shape_samples))
        limit = self.max_shape_samples
        for rf in decode_rf(data).values():
            if rf.dwell is None and limit is not None:
                cells = int(0.5 + data.shapes[rf.time_id].samples()[-1])
                if self.over(cells, limit):
                    raise seqfile.NotSupported(self.message(path, rf.id, cells, limit))
        return dataclasses.replace(data, interpreter=self)

    def over(self, cells: int, limit: int) -> bool:
        return cells > limit

    def message(self, path: Path, rf_id: int, cells: int, limit: int) -> str:
        return f"{path}: RF event {rf_id} has {cells} cells, max_shape_samples is {limit}"


@dataclasses.dataclass(frozen=True, slots=True)
class TerseResampling(Resampling):
    """`Resampling` whose `NotSupported` of an RF pulse gives no path or number."""

    def message(self, path: Path, rf_id: int, cells: int, limit: int) -> str:
        return "an RF pulse is too large"


@dataclasses.dataclass(frozen=True, slots=True)
class ResamplingAtLimit(Resampling):
    """`Resampling` that also refuses an RF pulse of exactly `max_shape_samples` cells."""

    def over(self, cells: int, limit: int) -> bool:
        return cells >= limit


def _install(monkeypatch, **values: str) -> None:
    """Entry points of the group with each name and value of `values`, and no other."""
    eps = importlib.metadata.EntryPoints(
        importlib.metadata.EntryPoint(name, value, interpreters.GROUP)
        for name, value in values.items()
    )
    monkeypatch.setattr(
        interpreters.importlib.metadata, "entry_points", lambda group: eps.select(group=group)
    )


def test_no_plugin_is_installed_with_the_package():
    """The environment of the package has `spec` only: the plugins are other distributions."""
    assert interpreters.interpreter_names() == ("spec",)


def test_a_name_that_no_interpreter_has_names_the_installed_ones_and_the_group():
    message = (
        "no interpreter is named 'cpp-siemens'; the installed interpreters are spec. "
        "A distribution adds one through the entry-point group pulseq_analysis.interpreters."
    )
    with pytest.raises(ValueError, match=re.escape(message)):
        read_seqfile(SEQFILES / "valid_1_5_1.seq", "cpp-siemens")
    with pytest.raises(TypeError):
        seqfile.interpreter(3)


def test_a_plugin_reads_and_decodes_a_file_by_name_and_as_an_object(monkeypatch):
    _install(monkeypatch, fake=f"{__name__}:Fake")
    assert interpreters.interpreter_names() == ("spec", "fake")
    assert seqfile.interpreter("fake") == Fake()
    assert isinstance(Fake(), seqfile.Plugin) and not isinstance(Spec(), seqfile.Plugin)
    path = SEQFILES / "valid_1_5_1.seq"
    data = read_seqfile(path, "fake")
    assert data.interpreter == Fake()
    assert read_seqfile(str(path), Fake("other")).interpreter == Fake("other")
    assert synth.decode(data) == ("fake decoding", Fake())
    with pytest.raises(TypeError, match="synth.decode"):
        decode_rf(data)


def test_a_plugin_that_does_not_load_or_has_another_name_or_two_entry_points_is_an_error(
    monkeypatch,
):
    _install(monkeypatch, broken="no_such_module_of_a_plugin:Interpreter")
    with pytest.raises(ImportError, match="'broken'.*did not load") as caught:
        seqfile.interpreter("broken")
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)
    _install(monkeypatch, fake=f"{__name__}:Misnamed")
    with pytest.raises(TypeError, match="whose name is not 'fake'"):
        seqfile.interpreter("fake")
    eps = importlib.metadata.EntryPoints(
        importlib.metadata.EntryPoint("fake", f"{__name__}:Fake", interpreters.GROUP)
        for _ in range(2)
    )
    monkeypatch.setattr(
        interpreters.importlib.metadata, "entry_points", lambda group: eps.select(group=group)
    )
    with pytest.raises(ValueError, match="more than one interpreter is named 'fake'"):
        seqfile.interpreter("fake")


def test_spec_has_the_setting_max_shape_samples_with_the_default_of_every_interpreter():
    """The limit of the samples of a shape is a setting of every interpreter (the user,
    2026-10-18): `Spec.max_shape_samples` is `interpreters.DEFAULT_MAX_SHAPE_SAMPLES` (2^27) by
    default, and None is no limit. It is an int above 0; a numpy int is kept as an int. A bool,
    another type, 0 or less is an error that names the setting. `str` gives the setting when it
    is not its default."""
    assert interpreters.DEFAULT_MAX_SHAPE_SAMPLES == 2**27
    assert Spec().max_shape_samples == interpreters.DEFAULT_MAX_SHAPE_SAMPLES
    assert Spec(max_shape_samples=2**27) == Spec() and Spec(max_shape_samples=None) != Spec()
    assert str(Spec()) == "spec"
    assert str(Spec(max_shape_samples=None)) == "spec(max_shape_samples=None)"
    assert str(Spec(max_shape_samples=100)) == "spec(max_shape_samples=100)"
    numpy_int = Spec(max_shape_samples=np.int64(100))
    assert numpy_int == Spec(max_shape_samples=100)
    assert type(numpy_int.max_shape_samples) is int
    assert str(numpy_int) == "spec(max_shape_samples=100)"
    for value in (True, np.True_, 100.0, np.float64(100), "100"):
        with pytest.raises(TypeError, match="max_shape_samples"):
            Spec(max_shape_samples=value)
    for value in (0, -1):
        with pytest.raises(ValueError, match="max_shape_samples"):
            Spec(max_shape_samples=value)


def test_spec_passes_the_check_of_the_shape_limit_of_every_interpreter():
    """`conformance.check_shape_limit(Spec)` passes: the check that the tests of a plugin call
    for their interpreter."""
    from pulseq_analysis.seqfile import conformance

    conformance.check_shape_limit(Spec)


# A file of one block of 2000 us that plays RF event 1: the magnitude (shape 1), the phase (shape
# 2) and the time shape (shape 3) have two samples each, and the times are 1 and 2000 RF rasters.
# It is `RESAMPLED_RF` of the tests of pulseq-cpp-siemens (`test_api.py`), whose reader resamples
# the pulse into 2000 cells; the two are copies, since the wheel tests of the plugin run without
# the tests of pulseq-analysis.
RESAMPLED_RF = """# Pulseq sequence file
# Hand-written file of the tests, not made by a Pulseq tool.

[VERSION]
major 1
minor 5
revision 0

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

# NUM DUR RF GX GY GZ ADC EXT
[BLOCKS]
1 200 1 0 0 0 0 0

# id ampl. mag_id phase_id time_shape_id center delay freqPPM phasePPM freq phase use
[RF]
1 1000 1 2 3 1000 0 0 0 0 0 e

[SHAPES]

shape_id 1
num_samples 2
1
1

shape_id 2
num_samples 2
0
0

shape_id 3
num_samples 2
1
2000

"""


def test_spec_reads_an_rf_pulse_of_more_cells_than_max_shape_samples(tmp_path):
    """`spec` makes no array whose size is a value of a shape: it keeps an RF pulse of points as
    its points. So `RESAMPLED_RF`, whose pulse `cpp-siemens` resamples into 2000 cells, reads
    with `Spec(max_shape_samples=1000)`, and `decode_rf` gives the pulse of its two points, at 1
    and 2000 us."""
    path = tmp_path / "resampled_rf.seq"
    path.write_text(RESAMPLED_RF)
    (rf,) = decode_rf(read_seqfile(path, Spec(max_shape_samples=1000))).values()
    assert rf.dwell is None
    assert rf.magnitude.tolist() == [1000.0, 1000.0] and rf.phase.tolist() == [0.0, 0.0]
    assert np.allclose(rf.t, [1e-6, 2000e-6], rtol=0, atol=1e-12)


@pytest.mark.parametrize(
    ("cls", "message"),
    [
        (OtherLimit, "the default of max_shape_samples is 1000, not 134217728"),
        (Fake, "max_shape_samples=0 does not raise ValueError"),
        (Verbose, "str gives the default of max_shape_samples"),
        (Unchecked, "a shape of 2097152 samples, over the limit 1048576, reads"),
        (Terse, "the message of NotSupported does not give"),
        (Coarse, "a shape of 8 samples, over the limit 4, reads"),
        (AtLimit, "a shape of 8 samples, at the limit 8, does not read"),
        (Forgetful, "the model records"),
        (TerseResampling, "the message of NotSupported of an RF pulse of 2097152 cells"),
        (ResamplingAtLimit, "an RF pulse of 2097152 cells, at the limit 2097152, does not read"),
    ],
)
def test_the_check_of_the_shape_limit_fails_for_a_plugin_that_does_not_follow_it(cls, message):
    """`conformance.check_shape_limit(cls)` passes for `Limited` and `Resampling`, plugin classes
    that follow the convention of `max_shape_samples`, and raises `AssertionError` that says what
    is wrong for a class that does not: another default, no check of the value, a `str` that
    gives the default, no limit in `read`, a message without the path, a limit that is not the
    setting, a limit that refuses a shape at the limit, a model that does not record the setting,
    a message of an RF pulse over the limit without the path or the number, and a limit that
    refuses an RF pulse of as many cells as the limit."""
    from pulseq_analysis.seqfile import conformance

    conformance.check_shape_limit(Limited)
    conformance.check_shape_limit(Resampling)
    with pytest.raises(AssertionError, match=re.escape(message)):
        conformance.check_shape_limit(cls)


def test_a_plugin_without_the_setting_max_shape_samples_of_its_default_is_refused(monkeypatch):
    """Every interpreter has the dataclass field `max_shape_samples`, of the default
    `DEFAULT_MAX_SHAPE_SAMPLES` (the convention of the protocol `Plugin`; the user, 2026-10-18).
    A plugin class with no such field (`Unlimited`) or with another default (`OtherLimit`) is a
    `TypeError` that names the plugin and the convention: by name, as an object to
    `read_seqfile`, and as an object to `load`."""
    path = SEQFILES / "valid_1_5_1.seq"
    _install(
        monkeypatch, unlimited=f"{__name__}:Unlimited", **{"other-limit": f"{__name__}:OtherLimit"}
    )
    cases = (
        ("unlimited", Unlimited(), "'unlimited' has no dataclass field max_shape_samples"),
        ("other-limit", OtherLimit(), "'other-limit' has the default 1000 of max_shape_samples"),
    )
    convention = f"DEFAULT_MAX_SHAPE_SAMPLES ({2**27})"
    for name, plugin, message in cases:
        for call, arguments in (
            (seqfile.interpreter, (name,)),
            (read_seqfile, (path, plugin)),
            (load, (path, plugin)),
        ):
            with pytest.raises(TypeError) as caught:
                call(*arguments)
            assert message in str(caught.value) and convention in str(caught.value)


def test_a_class_is_not_an_interpreter_and_the_error_names_its_call():
    """Finding 1.2.4c of `docs/reviews/2026-10-13-code-review.md`: the class of a plugin has the
    members of `Plugin`, but an interpreter is an object of the class."""
    path = SEQFILES / "valid_1_5_1.seq"
    with pytest.raises(TypeError, match=re.escape("Fake()")):
        seqfile.interpreter(Fake)
    with pytest.raises(TypeError, match=re.escape("Fake()")):
        read_seqfile(path, Fake)
    with pytest.raises(TypeError, match=re.escape("Spec()")):
        seqfile.interpreter(Spec)


def test_a_plugin_cannot_be_spec(monkeypatch):
    _install(monkeypatch, spec=f"{__name__}:Fake")
    assert interpreters.interpreter_names() == ("spec",)
    assert seqfile.interpreter("spec") == Spec()


def test_the_package_has_no_reference_to_a_plugin():
    """P21: the code and the metadata of the package name no plugin (the sub-project
    packages/pulseq-cpp-siemens gives the interpreter `cpp-siemens`)."""
    pattern = re.compile(r"pulseq[_-]cpp[_-]siemens|CppSiemens|cpp[_-]siemens", re.IGNORECASE)
    files = [*sorted((ROOT / "src").rglob("*.py")), ROOT / "pyproject.toml"]
    found = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert found == []
