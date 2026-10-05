"""Check that TESTS.md has one entry for each test, and no other.

Run it in the devShell from the repository root:

    nix develop --command uv run python scripts/check_tests_md.py

There are two ways to get the pytest tests. Without `--collected`, this script runs
`pytest --collect-only` itself. With `--collected PATH`, it reads the collected test
node IDs from PATH instead, one on each line, in the format of `pytest --collect-only
-q`. `scripts/check` uses this form, with the file that its own pytest run already
wrote:

    nix develop --command uv run python scripts/check_tests_md.py --collected PATH

Either way, a parametrized test is one test. The rest are JavaScript tests: each
top-level `test("test_...")` call in a file that matches `tests/js/test_*.js`.
JavaScript tests are found by reading the file's text, not by running Node.js. The
entries in TESTS.md are the `#### `test_name`` headings. Each one belongs to the test
file that the `###` heading above it names, for example `### 2.1 Shared sequence helpers
(`test_seq_utils.py`)`. Tests and entries are compared by file name and test name, so
a test name that is in two files needs an entry in each file's section.

Exits 1 and lists each difference when TESTS.md does not match.
"""

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_MD = ROOT / "TESTS.md"

FILE_HEADING = re.compile(r"^### .*\(`(test_\w+\.(?:py|js))`\)\s*$")
SECTION_HEADING = re.compile(r"^#{1,3} ")
ENTRY_HEADING = re.compile(r"^#### `(test_\w+)`\s*$")


def collect_node_ids() -> list[str]:
    """Node IDs of each test, from running `pytest --collect-only` here."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"pytest --collect-only failed:\n{result.stdout}{result.stderr}")
    return [line for line in result.stdout.splitlines() if "::" in line]


def read_node_ids(path: Path) -> list[str]:
    """Node IDs of each test, from a file that a pytest run wrote, one on each line."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        sys.exit(f"could not read collected tests file {path}: {error}")
    return [line for line in text.splitlines() if "::" in line]


def _unparametrized(node_id: str) -> str:
    """`node_id` without its parametrize ID, which can contain `::` (`test_y[a::b]`)."""
    return node_id.split("[", 1)[0]


def collected_tests(node_ids: list[str]) -> set[tuple[str, str]]:
    """(file name, test name) of each test named by `node_ids`.

    `node_ids` is in the format of `pytest --collect-only -q`.
    """
    paths = {_unparametrized(node_id).split("::")[0] for node_id in node_ids}
    names = Counter(Path(path).name for path in paths)
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        sys.exit(
            "Test files with the same name in different directories: "
            + ", ".join(duplicates)
            + ". TESTS.md names test files without their directory."
        )
    tests = set()
    for node_id in node_ids:
        path, *_, name = _unparametrized(node_id).split("::")
        tests.add((Path(path).name, name))
    return tests


JS_TEST_LINE = re.compile(r'^test\("(test_\w+)"', re.MULTILINE)
JS_TEST_CALL = re.compile(r"^test\(.*$", re.MULTILINE)


def javascript_tests() -> tuple[set[tuple[str, str]], list[str]]:
    """(file name, test name) of each JS test in `tests/js`, and the problems found.

    A JS test is a top-level `test("test_name", ...)` call at the start of a line in
    a file that matches `test_*.js`. This reads the file's text; it does not run
    Node.js.
    """
    entries: list[tuple[str, str]] = []
    problems = []
    for path in sorted((ROOT / "tests" / "js").glob("test_*.js")):
        text = path.read_text(encoding="utf-8")
        for match in JS_TEST_LINE.finditer(text):
            entries.append((path.name, match.group(1)))
        for call in JS_TEST_CALL.findall(text):
            if not JS_TEST_LINE.match(call):
                problems.append(f"{path.name}: test name is not test_ and word characters: {call}")
    problems += [
        f"{file}: `{name}` is a JavaScript test more than once"
        for (file, name), count in Counter(entries).items()
        if count > 1
    ]
    return set(entries), problems


def documented_tests(text: str) -> tuple[set[tuple[str, str]], list[str]]:
    """(file name, test name) of each entry in TESTS.md, and the problems found."""
    entries: list[tuple[str, str]] = []
    problems = []
    current_file = None
    for number, line in enumerate(text.splitlines(), start=1):
        if match := FILE_HEADING.match(line):
            current_file = match.group(1)
        elif SECTION_HEADING.match(line):
            current_file = None
        elif match := ENTRY_HEADING.match(line):
            if current_file is None:
                problems.append(
                    f"TESTS.md:{number}: entry `{match.group(1)}` is not in a test file section"
                )
            else:
                entries.append((current_file, match.group(1)))
    for (file, name), count in Counter(entries).items():
        if count > 1:
            problems.append(f"TESTS.md: {count} entries for {file}::{name}")
    return set(entries), problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--collected",
        type=Path,
        default=None,
        metavar="PATH",
        help="file of node IDs from a pytest run, one on each line, instead of "
        "running `pytest --collect-only` here",
    )
    args = parser.parse_args()
    node_ids = read_node_ids(args.collected) if args.collected else collect_node_ids()
    tests = collected_tests(node_ids)
    js_tests, problems = javascript_tests()
    same_name = sorted({f for f, _ in tests} & {f for f, _ in js_tests})
    if same_name:
        sys.exit(
            "Test files with the same name in pytest and in the JavaScript tests: "
            + ", ".join(same_name)
            + ". TESTS.md names test files without their directory."
        )
    tests |= js_tests
    entries, more_problems = documented_tests(TESTS_MD.read_text(encoding="utf-8"))
    problems += more_problems
    problems += [f"no entry in TESTS.md for {f}::{n}" for f, n in sorted(tests - entries)]
    problems += [
        f"TESTS.md entry for a test that does not exist: {f}::{n}"
        for f, n in sorted(entries - tests)
    ]
    for problem in problems:
        print(f"error  {problem}")
    if problems:
        print("TESTS.md must have one entry for each test. See the top of TESTS.md.")
        return 1
    print(f"ok    TESTS.md has an entry for each of the {len(tests)} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
