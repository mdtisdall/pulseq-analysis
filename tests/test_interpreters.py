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

import pytest

from pulseq_analysis import seqfile, synth
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

    def read(self, path: Path) -> seqfile.SequenceData:
        assert isinstance(path, Path)
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: seqfile.SequenceData, session=None) -> tuple[str, "Fake"]:
        return ("fake decoding", data.interpreter)


@dataclasses.dataclass(frozen=True, slots=True)
class Misnamed(Fake):
    name: ClassVar[str] = "other"


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
