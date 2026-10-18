"""The checks of the documents: what a document cites or links exists, no link names this
repository at a commit, a table of a document that repeats a table of the code has the values of
the code, and the version and the requirement of pulseq-cpp-siemens that the documents give are
those of its `pyproject.toml`.

The documents are the Markdown files at the top of the repository, of `docs/` and of `tests/` (and
its folders), and the same of `packages/pulseq-cpp-siemens/`. The folders of `docs/` (`plans/`,
`reviews/`) are not read: they keep the text of the time they were written. The check of the
names of the tests also reads the Python files of `src/` and `tests/`, and the same of the plugin.

The module imports only `pulseq_analysis` and the standard library, so it needs no build of the
plugin: it reads `CODES` of `cpp-siemens` from the source of the plugin with `ast`.
"""

import ast
import collections
import dataclasses
import functools
import importlib
import inspect
import pkgutil
import re
import tomllib
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import pulseq_analysis
from pulseq_analysis.analyses.registry import registry
from pulseq_analysis.seqfile import spec

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "packages" / "pulseq-cpp-siemens"
USAGE = ROOT / "docs" / "usage.md"
SPECIFICATION = ROOT / "docs" / "specification.md"
FINDINGS = ROOT / "docs" / "findings-for-pulseq-checks.md"
MIGRATION = ROOT / "docs" / "migration.md"
CHANGELOG = ROOT / "CHANGELOG.md"
PLUGIN_SPECIFICATION = PLUGIN / "docs" / "specification.md"
INTERPRETER = PLUGIN / "src" / "pulseq_cpp_siemens" / "interpreter.py"

# The record: the entries of the decisions of `spec` (D1 to D4) and of `cpp-siemens` (D5 to D7).
RECORD = [ROOT / "docs" / "discrepancies.md", PLUGIN_SPECIFICATION]

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`[^`\n]*`")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", re.MULTILINE)
_EXPLICIT_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
_LINK_MARKUP = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\]\(([^()\s]+)(?:\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_LINE_ANCHOR = re.compile(r"L(\d+)(?:-L(\d+))?")
_RECORD_ID = re.compile(r"(?<![\w.])D[1-7]\.\d+(?!\w)")
_TEST_NAME = re.compile(r"(?<![\w./])test_\w+(?![\w.])")
_ENTRY = re.compile(r"^#{2,6} (D[1-7]\.\d+): ", re.MULTILINE)
_REQUIREMENT = re.compile(r"`(pulseq-analysis\s*[<>=!~][^`]*)`")
_UNRELEASED = re.compile(r"^## Unreleased\n(.*?)^## ", re.DOTALL | re.MULTILINE)

# This repository at a commit: a URL of GitHub (a file, a folder, a commit, or a `pip` install),
# a raw file, or a flake reference, with a commit ID of 7 to 40 hex digits as its ref.
REPOSITORY = "mdtisdall/pulseq-analysis"
_PINNED = re.compile(
    rf"(?:github\.com/{REPOSITORY}(?:/(?:blob|tree|commit|raw|blame)/|@)"
    rf"|raw\.githubusercontent\.com/{REPOSITORY}/|github:{REPOSITORY}/)"
    r"([0-9a-f]{7,40})(?![\w-])",
    re.IGNORECASE,
)

PREFIX = "pulseq_analysis."


def _documents() -> list[Path]:
    """The documents that the checks read (the docstring of the module)."""
    found = []
    for base in (ROOT, PLUGIN):
        found += sorted(base.glob("*.md"))
        found += sorted((base / "docs").glob("*.md"))
        found += sorted((base / "tests").rglob("*.md"))
    return found


def _python_files() -> list[Path]:
    """The Python files of `src/` and `tests/` (and their folders), and the same of the plugin."""
    return [
        path
        for base in (ROOT, PLUGIN)
        for folder in ("src", "tests")
        for path in sorted((base / folder).rglob("*.py"))
    ]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _without_code_blocks(text: str) -> str:
    """`text` with each fenced code block made empty lines, so the line numbers stay."""
    return _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _table(text: str, header: str) -> list[list[str]]:
    """The cells of each row of the table of `text` whose header row is `header`, without the
    header and the delimiter row. A `\\|` is a `|` of a cell."""
    lines = text.splitlines()
    rows = []
    for line in lines[lines.index(header) + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])])
    return rows


def _slug(heading: str) -> str:
    """The anchor that GitHub gives a heading: its text without the marks of a code span or a link
    (the backticks, the brackets and the URL), in lower case, without each character that is not
    a letter, a mark, a digit, `_`, `-` or a space, and with each space a `-`."""
    text = _LINK_MARKUP.sub(r"\1", heading).replace("`", "")
    kept = (c for c in text.lower() if c in "_- " or unicodedata.category(c)[0] in "LMN")
    return "".join(kept).replace(" ", "-")


@functools.cache
def _anchors(path: Path) -> frozenset[str]:
    """The anchors of a Markdown file: the slug of each heading outside a code block, with `-n`
    for the n-th repeat of a slug in the file (as GitHub does), and each `<a id="...">` or
    `<a name="...">`."""
    text = _without_code_blocks(_text(path))
    counts: collections.Counter[str] = collections.Counter()
    anchors = set(_EXPLICIT_ANCHOR.findall(text))
    for heading in _HEADING.findall(text):
        slug = _slug(heading)
        anchors.add(f"{slug}-{counts[slug]}" if counts[slug] else slug)
        counts[slug] += 1
    return frozenset(anchors)


def _anchored_links() -> list[tuple[Path, int, str, Path, str]]:
    """(document, line, link, target, anchor) of each relative link with an anchor of the
    documents, outside a code block and a code span. The target of a link with no path
    (`#anchor`) is its document."""
    found = []
    for document in _documents():
        lines = _without_code_blocks(_text(document)).splitlines()
        for number, line in enumerate(lines, 1):
            for link in _LINK.findall(_SPAN.sub("", line)):
                if "#" not in link or _SCHEME.match(link):
                    continue
                path, anchor = link.split("#", 1)
                target = (document.parent / unquote(path)).resolve() if path else document
                found.append((document, number, link, target, unquote(anchor)))
    return found


def _resolves(target: Path, anchor: str) -> bool:
    """The anchor is a heading or an anchor of the Markdown file `target`, or a line (`L12`) or
    a range of lines (`L12-L20`) of another file."""
    if not target.is_file():
        return False
    if target.suffix == ".md":
        return anchor in _anchors(target)
    match = _LINE_ANCHOR.fullmatch(anchor)
    if match is None:
        return False
    first, last = int(match.group(1)), int(match.group(2) or match.group(1))
    return 1 <= first <= last <= len(_text(target).splitlines())


@functools.cache
def _modules() -> dict[str, object]:
    """Each module of the package, by its path without the prefix `pulseq_analysis.`."""
    return {
        info.name.removeprefix(PREFIX): importlib.import_module(info.name)
        for info in pkgutil.walk_packages(pulseq_analysis.__path__, PREFIX)
    }


def _module_defining(function_name: str):
    """The module of the package that defines the function `function_name`."""
    (module,) = (
        module
        for module in _modules().values()
        if inspect.isfunction(getattr(module, function_name, None))
        and getattr(module, function_name).__module__ == module.__name__
    )
    return module


def _cpp_siemens_codes() -> dict[str, tuple[str, str]]:
    """`CODES` of the plugin's `interpreter.py`, read from its source: a `MappingProxyType` of a
    dict of literals, from each code to the ID of its entry and what the reader rejects."""
    for node in ast.parse(_text(INTERPRETER)).body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "CODES":
            call = node.value
            assert isinstance(call, ast.Call) and ast.unparse(call.func) == "MappingProxyType"
            return ast.literal_eval(call.args[0])
    raise AssertionError(f"{INTERPRETER} assigns no CODES")


def _difference(written: list, code: list) -> str:
    """The message of a list of a document that is not the list of the code: what the document
    has that the code does not, what it does not have, and what it repeats (all three empty when
    only the order differs)."""
    repeated = sorted(item for item, count in collections.Counter(written).items() if count > 1)
    return (
        f"not in the code: {sorted(set(written) - set(code))}; "
        f"not in the document: {sorted(set(code) - set(written))}; repeated: {repeated}"
    )


def test_each_record_id_that_a_document_cites_is_an_entry_of_the_record():
    """Each ID of the form `D<group>.<n>` (groups 1 to 7) in a document is the ID of an entry of
    `docs/discrepancies.md` or of the plugin's `docs/specification.md` (a heading
    `#### D<group>.<n>: ...`), so a document does not cite an entry that was removed or
    renumbered."""
    entries = {entry for path in RECORD for entry in _ENTRY.findall(_text(path))}
    # The reading finds the entries of both parts of the record, and the IDs of the documents.
    assert {"D1.1", "D4.7", "D5.1", "D7.6"} <= entries
    cited = [
        (document, number, record_id)
        for document in _documents()
        for number, line in enumerate(_text(document).splitlines(), 1)
        for record_id in _RECORD_ID.findall(line)
    ]
    assert USAGE in {document for document, _, _ in cited}
    missing = [
        f"{document.relative_to(ROOT)}:{number}: {record_id}"
        for document, number, record_id in cited
        if record_id not in entries
    ]
    assert not missing, f"the documents cite IDs that are no entry of the record: {missing}"


def test_each_relative_link_with_an_anchor_resolves():
    """Each relative link of a document with an anchor (`file.md#heading`, `#heading`) names a
    file that exists, and the anchor is a heading or an explicit anchor of the file, as GitHub
    makes them; for a file that is not Markdown, the anchor is a line or a range of lines of the
    file. A heading that is renamed breaks the links to it."""
    links = _anchored_links()
    # The reading finds a link to another document and a link within a document.
    found = {(document, link) for document, _, link, _, _ in links}
    assert (USAGE, "implementation.md#7-what-load-does") in found
    assert (USAGE, "#2-before-you-start") in found
    broken = [
        f"{document.relative_to(ROOT)}:{number}: {link}"
        for document, number, link, target, anchor in links
        if not _resolves(target, anchor)
    ]
    assert not broken, f"links whose anchor is not in their target: {broken}"


def _tests() -> set[str]:
    """The name of each test function (a method of a class too) and of each test module of the
    `tests/` of the repository and of the plugin, read with `ast`: `test_interface` is the
    module `tests/test_interface.py`."""
    names = set()
    for base in (ROOT, PLUGIN):
        for path in (base / "tests").rglob("test_*.py"):
            names.add(path.stem)
            names |= {
                node.name
                for node in ast.walk(ast.parse(_text(path)))
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test_")
            }
    return names


def test_each_test_that_a_document_names_exists():
    """Each test name (`test_...`) in a code span of a document, or of the text (the docstrings
    and the comments) of a Python file of `src/` or `tests/` of the repository or of the plugin,
    is a test function or a test module of their `tests/`, so a text does not cite a test that
    was removed or renamed. A name in a path (`tests/test_x.py`) or followed by a dot is not
    read, and a parametrize ID (`[id]`) after a name is not read."""
    tests = _tests()
    cited = [
        (path, number, name)
        for path in _documents() + _python_files()
        for number, line in enumerate(_text(path).splitlines(), 1)
        for span in _SPAN.findall(line)
        for name in _TEST_NAME.findall(span)
    ]
    # The reading finds the names of a document and of a docstring, of a test and of a module.
    found = {(path, name) for path, _, name in cited}
    assert (ROOT / "TESTS.md", "test_each_relative_link_with_an_anchor_resolves") in found
    assert (ROOT / "TESTS.md", "test_interpreters") in found
    spectrum_tests = ROOT / "tests" / "test_grad_spectrum.py"
    assert (spectrum_tests, "test_matches_oracle_with_many_chunks") in found
    missing = [
        f"{path.relative_to(ROOT)}:{number}: {name}"
        for path, number, name in cited
        if name not in tests
    ]
    assert not missing, f"the texts name tests that do not exist: {missing}"


def test_no_document_links_a_commit():
    """No document links this repository at a commit (a URL or a flake reference whose ref is a
    commit ID), code blocks too: a document describes `main`, and the tag of a release pins it.
    A link to a file of the repository is relative. Another repository at a commit (the C++
    reader at `c7469123`) is a source whose lines a document cites, and is kept."""
    # The pattern finds each form of a pin, and not a branch, a tag or another repository.
    pinned = (
        f"https://github.com/{REPOSITORY}/tree/6fa807d "
        f"https://github.com/{REPOSITORY}/blob/6fa807d/docs/usage.md#2-before-you-start "
        f"git+https://github.com/{REPOSITORY}@6fa807d "
        f"`nix run github:{REPOSITORY}/6fa807d#pulseq-cpp-oracle`"
    )
    assert _PINNED.findall(pinned) == ["6fa807d"] * 4
    kept = (
        f"https://github.com/{REPOSITORY}@main git+https://github.com/{REPOSITORY}@v0.1.0rc6 "
        "https://github.com/pulseq/pulseq/blob/c7469123c2f381f065986e6cc3a7d09730ed16ef/README.md"
    )
    assert _PINNED.findall(kept) == []
    found = [
        f"{document.relative_to(ROOT)}:{number}: {match.group(0)}"
        for document in _documents()
        for number, line in enumerate(_text(document).splitlines(), 1)
        for match in _PINNED.finditer(line)
    ]
    assert not found, f"the documents link this repository at a commit: {found}"


def test_the_codes_of_spec_in_the_documents_are_spec_rules():
    """The codes of `spec` are in the keys of `spec.RULES` and in three documents. The table of
    section 3 of `docs/specification.md` gives each code once, in the order of `RULES`; the
    table of `docs/usage.md` ("The interpreters") gives each code once; and section 2.5 of
    `docs/findings-for-pulseq-checks.md` gives the number of the codes, and lists each once."""
    rules = list(spec.RULES)
    specification = [
        code
        for row in _table(_text(SPECIFICATION), "| Code | ID | Rejects | Rests on |")
        for code in _CODE.findall(row[0])
    ]
    assert specification == rules, _difference(specification, rules)
    usage = [
        code
        for row in _table(_text(USAGE), "| Code | Basis | `spec` rejects |")
        for code in _CODE.findall(row[0])
    ]
    assert sorted(usage) == sorted(rules), _difference(usage, rules)
    match = re.search(
        r"\*\*The codes of `spec`\*\*\s+are\s+the\s+keys\s+of\s+`seqfile\.spec\.RULES`\s+"
        r"\((\d+)\s+codes\).*?the\s+codes\s+are:\n\n(.*?)\n\n",
        _text(FINDINGS),
        re.DOTALL,
    )
    assert match is not None, f"{FINDINGS.name} has no list of the codes of spec"
    assert int(match.group(1)) == len(rules)
    listed = _CODE.findall(match.group(2))
    assert sorted(listed) == sorted(rules), _difference(listed, rules)


def test_the_codes_of_cpp_siemens_in_the_documents_are_interpreter_codes():
    """The codes of `cpp-siemens` are in the keys of `CODES` of the plugin's `interpreter.py` and
    in two documents. The table of section 2.5 of the plugin's `docs/specification.md` gives
    each code once, with the ID of `CODES` ("—" for none); section 2.5 of
    `docs/findings-for-pulseq-checks.md` gives the number of the codes, and its table gives each
    code once, in the order of `CODES`."""
    codes = _cpp_siemens_codes()
    # The reading finds the codes of the reader and those of the checks of undefined behaviour.
    assert {"cpp.rejected", "ub.shape-missing"} <= set(codes)
    rows = _table(_text(PLUGIN_SPECIFICATION), "| Code | ID | The reader rejects |")
    specification = [(code, row[1]) for row in rows for code in _CODE.findall(row[0])]
    pairs = [(code, entry) for code, (entry, _) in codes.items()]
    assert sorted(specification) == sorted(pairs), _difference(specification, pairs)
    text = _text(FINDINGS)
    match = re.search(
        r"\*\*The codes of `cpp-siemens`\*\*\s+are\s+the\s+keys\s+of\s+"
        r"`pulseq_cpp_siemens\.interpreter\.CODES`\s+\((\d+)\s+codes\)",
        text,
    )
    assert match is not None, f"{FINDINGS.name} has no number of the codes of cpp-siemens"
    assert int(match.group(1)) == len(codes)
    findings = [
        code
        for row in _table(text, "| Code | Entry | The C++ reader rejects |")
        for code in _CODE.findall(row[0])
    ]
    assert findings == list(codes), _difference(findings, list(codes))


def _defaults(cell: str, function_name: str, params: tuple[str, ...]) -> tuple:
    """The defaults that a cell of the column "Defaults" gives, as `(name, default)` pairs:
    `none`; `name=value` in code spans, where a value written as a name (`BIN_S`) is the attribute
    of that name of the module that defines the function `function_name`; or "the defaults of
    `module`", the defaults of the parameters `params` of the function `function_name` of the
    module with that last part of its path."""
    if cell == "none":
        return ()
    match = re.fullmatch(r"the defaults of `(\w+)`", cell)
    if match is not None:
        (module,) = (m for path, m in _modules().items() if path.rsplit(".", 1)[-1] == match[1])
        parameters = inspect.signature(getattr(module, function_name)).parameters
        return tuple((name, parameters[name].default) for name in params)
    module = _module_defining(function_name)
    defaults = []
    for span in _CODE.findall(cell):
        name, value = span.split("=", 1)
        try:
            defaults.append((name, ast.literal_eval(value)))
        except ValueError:
            defaults.append((name, getattr(module, value)))
    return tuple(defaults)


def test_the_analyses_table_of_usage_is_the_registry():
    """The table of the analyses of `docs/usage.md` (section 7) has one row for each analysis of
    `registry()`, and each row gives its `spec`: the ID, the names of `params` (the keyword
    arguments of the call of the column `compute`, in order), `necessary`, `defaults` and
    `cost`."""
    analyses = registry()
    rows = _table(_text(USAGE), "| ID | `compute` | Necessary | Defaults | Cost | `to_series` |")
    ids = [analysis_id for row in rows for analysis_id in _CODE.findall(row[0])]
    assert sorted(ids) == sorted(analyses), _difference(ids, list(analyses))
    for row in rows:
        (analysis_id,) = _CODE.findall(row[0])
        analysis_spec = analyses[analysis_id].spec
        (call,) = _CODE.findall(row[1])
        function_name = call.split("(", 1)[0]
        written = (
            tuple(re.findall(r"(\w+)=", call)),
            () if row[2] == "none" else tuple(_CODE.findall(row[2])),
            _defaults(row[3], function_name, analysis_spec.params),
            row[4],
        )
        registered = (
            analysis_spec.params,
            analysis_spec.necessary,
            analysis_spec.defaults,
            analysis_spec.cost,
        )
        assert written == registered, (
            f"{analysis_id}: (params, necessary, defaults, cost) are {written} in the document "
            f"and {registered} in the registry"
        )


def _has_field(cls: type, name: str) -> bool:
    """`name` is a field of the dataclass `cls`, or a property of the class `cls`."""
    if dataclasses.is_dataclass(cls):
        return name in {field.name for field in dataclasses.fields(cls)}
    return isinstance(getattr(cls, name, None), property)


def test_the_defaults_table_of_usage_gives_each_default_and_its_field_on_the_result():
    """The table of the defaults of `docs/usage.md` (section 2) has one row for each parameter
    with a default of `load`, `read_seqfile` and `read_pypulseq`, and one for each default of an
    analysis of `registry()`, of the function of the column `compute` of the analyses table
    (decision Q24 of `docs/plans/remaining-review-fixes.md`). Each row gives the default of the
    signature of the function, and each `Class.field` of its column "On the result" is a field
    of the class that the function returns."""
    text = _text(USAGE)
    analyses = registry()
    expected = [
        (function_name, name)
        for function_name in ("load", "read_seqfile", "read_pypulseq")
        for name, parameter in inspect.signature(
            getattr(_module_defining(function_name), function_name)
        ).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    ]
    for row in _table(text, "| ID | `compute` | Necessary | Defaults | Cost | `to_series` |"):
        (analysis_id,) = _CODE.findall(row[0])
        function_name = _CODE.findall(row[1])[0].split("(", 1)[0]
        expected += [(function_name, name) for name, _ in analyses[analysis_id].spec.defaults]
    rows = _table(text, "| Call | Parameter | Default | On the result |")
    written = [(_CODE.findall(row[0])[0], _CODE.findall(row[1])[0]) for row in rows]
    assert sorted(written) == sorted(expected), _difference(written, expected)
    for (function_name, name), row in zip(written, rows, strict=True):
        module = _module_defining(function_name)
        signature = inspect.signature(getattr(module, function_name))
        span = _CODE.findall(row[2])[0]
        try:
            default = ast.literal_eval(span)
        except ValueError:
            default = getattr(module, span)
        assert default == signature.parameters[name].default, (
            f"{function_name}: the default of {name} is {default!r} in the document and "
            f"{signature.parameters[name].default!r} in the code"
        )
        returned = signature.return_annotation
        fields = [
            match.groups()
            for span in _CODE.findall(row[3])
            if (match := re.fullmatch(r"([A-Z]\w*)\.(\w+)", span)) is not None
        ]
        assert fields, f"{function_name}: the row of {name} names no field of the result"
        for class_name, field in fields:
            assert class_name == returned.__name__ and _has_field(returned, field), (
                f"{function_name}: {class_name}.{field} is not a field of {returned.__name__}"
            )


def _project_name(requirement: str) -> str:
    """The name of the project of a requirement of `pyproject.toml`, normalized (PEP 503)."""
    name = re.match(r"[A-Za-z0-9._-]+", requirement.strip())[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _unspaced(requirement: str) -> str:
    return "".join(requirement.split())


def test_the_documents_give_the_version_of_pulseq_cpp_siemens():
    """`docs/migration.md` and the entry "Unreleased" of `CHANGELOG.md` give the version of
    pulseq-cpp-siemens and its requirement on pulseq-analysis, and the plugin's `pyproject.toml`
    has them. The release that the documents describe is the "to" of the title of
    `docs/migration.md`, and the "from" is the last release: pulseq-analysis has the version of
    one of the two. At that release, both distributions have its version ("both are"). The
    dependencies of the plugin do not name pulseq-analysis, so its wheels install and run their
    tests without it; one extra of the plugin has the requirement that both documents give, both
    documents name that extra (`pulseq-cpp-siemens[extra]`), and the lower bound of the
    requirement is the version of the release."""
    analysis = tomllib.loads(_text(ROOT / "pyproject.toml"))["project"]
    plugin = tomllib.loads(_text(PLUGIN / "pyproject.toml"))["project"]
    migration = " ".join(_text(MIGRATION).split())
    match = re.match(r"# Migrating from (\S+) to (\S+) ", migration)
    assert match is not None, f"{MIGRATION.name} has no title 'Migrating from <last> to <next>'"
    last, release = match.groups()
    assert analysis["version"] in (last, release), (
        f"pulseq-analysis is {analysis['version']}; {MIGRATION.name} is from {last} to {release}"
    )
    unreleased = _UNRELEASED.search(_text(CHANGELOG))
    assert unreleased is not None, f"{CHANGELOG.name} has no entry 'Unreleased'"
    documents = {MIGRATION.name: migration, CHANGELOG.name: " ".join(unreleased[1].split())}

    assert re.findall(r"For `([^`]+)`, both are `([^`]+)`", migration) == [(release, release)]
    assert plugin["version"] == release, (
        f"pulseq-cpp-siemens is {plugin['version']} in its pyproject.toml; "
        f"{MIGRATION.name} gives {release}"
    )

    written = {
        name: {_unspaced(r) for r in _REQUIREMENT.findall(text)} for name, text in documents.items()
    }
    assert len(written[MIGRATION.name]) == 1, f"the requirements on pulseq-analysis: {written}"
    assert written[CHANGELOG.name] == written[MIGRATION.name], f"they differ: {written}"
    (requirement,) = written[MIGRATION.name]
    assert requirement.startswith(f"pulseq-analysis>={release},")
    named = [r for r in plugin["dependencies"] if _project_name(r) == "pulseq-analysis"]
    assert not named, f"the dependencies of pulseq-cpp-siemens name pulseq-analysis: {named}"
    extras = [
        extra
        for extra, requirements in plugin.get("optional-dependencies", {}).items()
        if requirement in map(_unspaced, requirements)
    ]
    assert len(extras) == 1, f"the extras of pulseq-cpp-siemens with {requirement}: {extras}"
    (extra,) = extras
    unnamed = [
        name for name, text in documents.items() if f"pulseq-cpp-siemens[{extra}]" not in text
    ]
    assert not unnamed, f"documents that do not name pulseq-cpp-siemens[{extra}]: {unnamed}"
