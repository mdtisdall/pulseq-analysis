"""The names of the interface: each public module has an `__all__`, its public names; the
names that `README.md`, `docs/usage.md` and `docs/implementation.md` give with a public module
are in its `__all__`; and each name of an `__all__` is in the documents.

A module is public when no part of its path starts with `_` (`synth._events` is not). The
`__all__` of a module that is not a package gives only the names that the module defines (or
that it imports from a module that is not public, as `series.FrozenDict`): a name that a module
imports from another public module is in the `__all__` of that module only. The `__all__` of a
package (`analyses`, `seqfile`, `synth`) gives names that it imports from its own modules.

The documents write a name in backticks or in a code block. These tests read two forms:

- a dotted name that starts with a module of the package: its path, with or without the
  prefix `pulseq_analysis.` (`pulseq_analysis.analyses.grad_peaks.gradient_peaks`,
  `synth.snapshot.load`), or the last part of its path alone (`registry.registry()`,
  `series.FrozenDict`). The module imports, and the name that follows is in its `__all__`
  (a name with a `_` at the start, or of a module that is not public, is an attribute of the
  module; a further `.part`, for example a method, is not read);
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
DOCS = [ROOT / "README.md", ROOT / "docs" / "usage.md", ROOT / "docs" / "implementation.md"]

# The public names (no `_` at the start) that a public module defines and leaves out of its
# `__all__`, so no document needs to give them. Each has the module, the name and the reason. A
# new public name goes in the `__all__` and in a document, or gets a `_`.
EXCEPTIONS: dict[tuple[str, str], str] = {}

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`([^`]+)`")
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")

PREFIX = "pulseq_analysis."


def _module_names() -> list[str]:
    """The path of each module and subpackage of the package, without the prefix
    `pulseq_analysis.` (`synth.events`, `synth`, `_equality`)."""
    return [
        info.name.removeprefix(PREFIX)
        for info in pkgutil.walk_packages(pulseq_analysis.__path__, PREFIX)
    ]


def _is_public(module_name: str) -> bool:
    """No part of the path of the module starts with `_` (`synth._events` is not public)."""
    return not any(part.startswith("_") for part in module_name.split("."))


def _public_modules() -> list[str]:
    return [name for name in _module_names() if _is_public(name)]


def _all(module_name: str) -> list[str] | None:
    """The `__all__` of the module, or None when it has none."""
    return getattr(importlib.import_module(f"{PREFIX}{module_name}"), "__all__", None)


def _short_names() -> dict[str, str]:
    """The path of each module that is not a subpackage, by the last part of its path
    (`events` gives `synth.events`). The last parts are unique."""
    paths = [
        info.name.removeprefix(PREFIX)
        for info in pkgutil.walk_packages(pulseq_analysis.__path__, PREFIX)
        if not info.ispkg
    ]
    short = {path.rsplit(".", 1)[-1]: path for path in paths}
    assert len(short) == len(paths), paths
    return short


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
    """(module, name) of each dotted name of the documents that starts (after the prefix
    `pulseq_analysis.`) with the path of a module of the package, the longest one, or with the
    last part of the path of a module. `module` is the path, and `name` is None for a module
    alone."""
    modules = set(_module_names())
    short = _short_names()
    found: set[tuple[str, str | None]] = set()
    for _, text in _texts():
        for chain in _DOTTED.findall(text):
            parts = chain.split(".")
            if parts[0] == "pulseq_analysis":
                parts = parts[1:]
            if parts and parts[0] in short:
                module, rest = short[parts[0]], parts[1:]
            else:
                lengths = [n for n in range(len(parts), 0, -1) if ".".join(parts[:n]) in modules]
                if not lengths:
                    continue
                module, rest = ".".join(parts[: lengths[0]]), parts[lengths[0] :]
            found.add((module, rest[0] if rest else None))
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


def _imported_from(module_name: str) -> dict[str, str]:
    """The module that each name of a `from ... import` of the top level of the source of the
    module comes from, by the name, as a path without the prefix `pulseq_analysis.` (in
    `analyses.pns_levels`, `SAFE_FIELDS` gives `analyses.safe`)."""
    module = importlib.import_module(f"{PREFIX}{module_name}")
    package = module.__name__ if hasattr(module, "__path__") else module.__name__.rpartition(".")[0]
    found = {}
    for node in ast.parse(Path(module.__file__).read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ImportFrom):
            continue
        source = node.module or ""
        if node.level:
            parts = package.split(".")[: len(package.split(".")) - node.level + 1]
            source = ".".join(parts + [source] if source else parts)
        found |= {alias.asname or alias.name: source.removeprefix(PREFIX) for alias in node.names}
    return found


def test_each_public_module_has_an_all():
    """Each public module and subpackage of the package has an `__all__`, the names of its
    contract."""
    modules = _public_modules()
    # The walk finds the modules of each subpackage and the subpackages.
    assert {"analyses", "synth.seq_index", "seqfile.spec"} <= set(modules)
    without = [name for name in modules if _all(name) is None]
    assert not without, f"public modules with no `__all__`: {without}"


def test_each_name_that_the_documents_give_with_a_public_module_is_in_its_all():
    """A dotted name or an import of the documents with a public module is in the `__all__` of
    the module, so a document does not give a name that was removed or renamed, or a name
    through a module that only imports it (`pns_levels.SAFE_FIELDS`). A name with a `_` at the
    start, or of a module that is not public, exists in the module."""
    qualified = _qualified_names()
    # The reading finds the names of the documents that this test must cover.
    assert ("analyses.series", "FrozenDict") in qualified
    assert ("analyses", None) in qualified
    imported = _imported_names()
    assert ("analyses.grad_peaks", "gradient_peaks") in imported
    missing = []
    for module_name, name in sorted(
        qualified | imported, key=lambda pair: (pair[0], pair[1] or "")
    ):
        module = importlib.import_module(f"{PREFIX}{module_name}")
        if name is None:
            continue
        if _is_public(module_name) and not name.startswith("_"):
            if name not in (_all(module_name) or ()):
                missing.append(f"{module_name}.{name}")
        elif not hasattr(module, name):
            missing.append(f"{module_name}.{name}")
    assert not missing, (
        f"the documents give names that are not in the `__all__` of their module: {missing}"
    )


def test_each_name_of_an_all_is_in_the_documents():
    """Each name of the `__all__` of a public module exists in the module, and a span or a
    code block of the documents gives it (as a bare name or with its module)."""
    bare = _bare_names()
    absent, undocumented = [], []
    for module_name in _public_modules():
        module = importlib.import_module(f"{PREFIX}{module_name}")
        for name in _all(module_name) or ():
            if not hasattr(module, name):
                absent.append(f"{module_name}.{name}")
            if name not in bare:
                undocumented.append(f"{module_name}.{name}")
    assert not absent, f"names of an `__all__` that the module does not have: {absent}"
    assert not undocumented, f"names of an `__all__` that no document gives: {undocumented}"


def test_an_all_gives_no_name_of_another_public_module():
    """The `__all__` of a public module that is not a package gives the names that the module
    defines, and the names that it imports from a module that is not public
    (`series.FrozenDict` of `_equality`), but no name that it imports from another public module
    (`NO_GRADIENTS` of `synth.seq_index` in `analyses.pns_levels`). The `__all__` of a package
    gives the names that it imports from its own modules."""
    # The reading of the imports finds an import from a public module and one from a module that
    # is not public.
    assert _imported_from("analyses.pns_levels")["NO_GRADIENTS"] == "synth.seq_index"
    assert _imported_from("analyses.series")["FrozenDict"] == "_equality"
    assert _imported_from("synth")["Session"] == "synth.scanner"
    wrong = []
    for module_name in _public_modules():
        module = importlib.import_module(f"{PREFIX}{module_name}")
        defined, sources = _defined_names(module_name), _imported_from(module_name)
        for name in _all(module_name) or ():
            source = sources.get(name)
            if hasattr(module, "__path__"):
                if source is None or not source.startswith(f"{module_name}."):
                    wrong.append(f"{module_name}.{name}")
            elif name not in defined and (source is None or _is_public(source)):
                wrong.append(f"{module_name}.{name} (from {source})")
    assert not wrong, f"names of an `__all__` that belong to another module: {wrong}"


def test_the_interface_names_of_the_review_are_in_the_documents():
    """`SeriesKind`, the `Analysis` protocol and `FrozenDict` are given by the documents, at
    the public paths `series.SeriesKind`, `registry.Analysis` and `series.FrozenDict` (of the
    subpackage `analyses`)."""
    qualified = _qualified_names()
    assert ("analyses.series", "SeriesKind") in qualified
    assert ("analyses.registry", "Analysis") in qualified
    assert ("analyses.series", "FrozenDict") in qualified
    from pulseq_analysis._equality import FrozenDict
    from pulseq_analysis.analyses.registry import Analysis
    from pulseq_analysis.analyses.series import FrozenDict as public_frozen_dict
    from pulseq_analysis.analyses.series import SeriesKind

    assert public_frozen_dict is FrozenDict
    assert Analysis.__module__ == "pulseq_analysis.analyses.registry"
    assert SeriesKind.__module__ == "pulseq_analysis.analyses.series"


def test_each_public_name_of_a_module_is_in_its_all_or_an_exception():
    """A name without a `_` at the start that a public module defines is in the `__all__` of the
    module (so a document gives it), or is in `EXCEPTIONS`."""
    outside = set()
    for module_name in _public_modules():
        names = set(_all(module_name) or ())
        for name in _defined_names(module_name):
            if not name.startswith("_") and name not in names:
                outside.add((module_name, name))
    assert outside == set(EXCEPTIONS) & outside, (
        "public names that are not in the `__all__` of their module (put each in the `__all__`"
        f" and a document, or give it a `_`): {sorted(outside - set(EXCEPTIONS))}"
    )


def test_each_exception_is_a_public_name_outside_the_all():
    """An entry of `EXCEPTIONS` is still needed: the module is public, defines the name and
    leaves it out of its `__all__`, and the entry has a reason."""
    for (module_name, name), reason in EXCEPTIONS.items():
        assert _is_public(module_name), (module_name, name)
        assert name in _defined_names(module_name), (module_name, name)
        assert name not in (_all(module_name) or ()), (module_name, name)
        assert reason, (module_name, name)
