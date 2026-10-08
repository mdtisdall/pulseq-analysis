"""The names of the interface: the names that `docs/usage.md` and `docs/implementation.md` give
exist, and each public name of a module is in the documents.

The documents write a name in backticks or in a code block. These tests read two forms:

- a dotted name whose first part is a module of the package, with or without the prefix
  `pulseq_analysis.` (`pulseq_analysis.grad_peaks.gradient_peaks`, `analyses.registry()`,
  `series.FrozenDict`): the module imports, and it has the attribute that follows (a
  further `.part`, for example a method, is not read);
- a `from pulseq_analysis.module import name, ...` line of a Python code block.

A bare name (`Series`, `gradient_peaks`) in backticks or in a code block gives the name of
any module that defines it.
"""

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pulseq_analysis

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "docs" / "usage.md", ROOT / "docs" / "implementation.md"]

# The public names (no `_` at the start) of a module of the package that no document gives.
# Each has the module, the name and the reason. A new public name needs a document, or a `_`.
EXCEPTIONS: dict[tuple[str, str], str] = {}

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`([^`]+)`")
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")

PREFIX = "pulseq_analysis."


def _module_names() -> list[str]:
    return [info.name for info in pkgutil.iter_modules(pulseq_analysis.__path__)]


def _texts() -> list[tuple[str, str]]:
    """(language, text) of each code block and each backtick span of the documents. The
    language is the one of the fence, and "" for a span."""
    found = []
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        found += [(m.group(1), m.group(2)) for m in _FENCE.finditer(text)]
        found += [("", m.group(1)) for m in _SPAN.finditer(_FENCE.sub("", text))]
    return found


def _qualified_names() -> set[tuple[str, str | None]]:
    """(module, name) of each dotted name of the documents whose first part (after the prefix
    `pulseq_analysis.`) is a module of the package. `name` is None for a module alone."""
    modules = set(_module_names())
    found: set[tuple[str, str | None]] = set()
    for _, text in _texts():
        for chain in _DOTTED.findall(text):
            parts = chain.split(".")
            if parts[0] == "pulseq_analysis":
                parts = parts[1:]
            if parts and parts[0] in modules:
                found.add((parts[0], parts[1] if len(parts) > 1 else None))
    return found


def _imported_names() -> set[tuple[str, str]]:
    """(module, name) of each `from pulseq_analysis.module import name` of a Python code
    block of the documents."""
    found = set()
    for language, text in _texts():
        if language != "python":
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(PREFIX):
                found |= {(node.module.removeprefix(PREFIX), alias.name) for alias in node.names}
    return found


def _bare_names() -> set[str]:
    return {name for _, text in _texts() for name in _IDENTIFIER.findall(text)}


def _defined_names(module_name: str) -> set[str]:
    """The names that the source of the module defines at its top level (a def, a class or an
    assignment), so a name that the module only imports is not in the set."""
    path = Path(importlib.import_module(f"{PREFIX}{module_name}").__file__)
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign | ast.TypeAlias):
            target = node.target if isinstance(node, ast.AnnAssign) else node.name
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_each_name_that_the_documents_give_with_a_module_can_be_imported():
    """A dotted name or an import of the documents exists, so a document does not give a
    name that was removed or renamed."""
    qualified = _qualified_names()
    # The reading finds the names of the documents that this test must cover.
    assert ("series", "FrozenDict") in qualified
    assert ("analyses", None) in qualified
    imported = _imported_names()
    assert ("grad_peaks", "gradient_peaks") in imported
    missing = []
    for module_name, name in sorted(
        qualified | imported, key=lambda pair: (pair[0], pair[1] or "")
    ):
        module = importlib.import_module(f"{PREFIX}{module_name}")
        if name is not None and not hasattr(module, name):
            missing.append(f"{module_name}.{name}")
    assert not missing, f"the documents give names that do not exist: {missing}"


def test_the_interface_names_of_the_review_are_in_the_documents():
    """`SeriesKind`, the `Analysis` protocol and `FrozenDict` are given by the documents, at
    the public paths `series.SeriesKind`, `analyses.Analysis` and `series.FrozenDict`."""
    qualified = _qualified_names()
    assert ("series", "SeriesKind") in qualified
    assert ("analyses", "Analysis") in qualified
    assert ("series", "FrozenDict") in qualified
    from pulseq_analysis._equality import FrozenDict
    from pulseq_analysis.analyses import Analysis
    from pulseq_analysis.series import FrozenDict as public_frozen_dict
    from pulseq_analysis.series import SeriesKind

    assert public_frozen_dict is FrozenDict
    assert Analysis.__module__ == "pulseq_analysis.analyses"
    assert SeriesKind.__module__ == "pulseq_analysis.series"


def test_each_public_name_of_a_module_is_in_the_documents_or_an_exception():
    """A name of a module without a `_` at the start that the module defines is in the
    documents (as a bare name or with its module), or is in `EXCEPTIONS`. The modules with a
    `_` at the start (`_equality`, `_events`, `_validate`) are not public."""
    bare = _bare_names()
    undocumented = set()
    for module_name in _module_names():
        if module_name.startswith("_"):
            continue
        for name in _defined_names(module_name):
            if not name.startswith("_") and name not in bare:
                undocumented.add((module_name, name))
    assert undocumented == set(EXCEPTIONS) & undocumented, (
        "public names that no document gives (give each a `_`, or a document): "
        f"{sorted(undocumented - set(EXCEPTIONS))}"
    )


def test_each_exception_is_a_public_name_that_no_document_gives():
    """An entry of `EXCEPTIONS` is still needed: the module defines the name, no document gives
    it, and the entry has a reason."""
    bare = _bare_names()
    for (module_name, name), reason in EXCEPTIONS.items():
        assert name in _defined_names(module_name), (module_name, name)
        assert name not in bare, (module_name, name)
        assert reason, (module_name, name)
