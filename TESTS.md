# Tests

This file describes each check that CI runs. CI runs `scripts/check` in the
`ci` Nix devShell on every pull request and on every push to `main`. The `ci`
devShell has only the tools that `scripts/check` uses. Run the same checks
locally with:

```bash
nix develop --command scripts/check
```

Each check below has:

- **Checks:** one statement of what the check makes sure of.
- **How:** the logic of the check, in words.
- **Assumptions:** what the check takes as true without testing it, and what
  it does not cover. A check can pass while one of its assumptions is false.

When you add, remove or change a test, update this file in the same pull
request. CI fails when a test has no entry here (see
[TESTS.md coverage](#testsmd-coverage)).

Contents:

1. [Static checks](#1-static-checks)
2. [Tests](#2-tests): the package

---

## 1. Static checks

### Dependency install

**Checks:** The locked dependencies install.

**How:** uv installs the project and its dependencies at the exact versions in
`uv.lock`, into the project environment. Every later step uses this
environment.

**Assumptions:**

- The install uses `--frozen`, which reads `uv.lock` and does not compare it to
  `pyproject.toml`. CI does not fail when `pyproject.toml` has a dependency
  change that is not in `uv.lock`.
- The Python version is the one from the Nix devShell (3.12). No other version
  is tested.

### Lint

**Checks:** The Python code has no findings from the rules that ruff turns on
by default.

**How:** ruff checks every Python file in the repository. The project sets
only the line length (100), so ruff uses its default rule set. `uv.lock` has
ruff 0.16.9.

**Assumptions:**

- The rule set is ruff's default, not a choice that the project makes. The
  project does not pin ruff in `pyproject.toml`, so an update of ruff in
  `uv.lock` can add or remove rules.
- Some common rules are not in the default set, so ruff does not report them:
  line length (E501), function complexity (C901), `print` calls (T201),
  `assert` statements (S101), too many arguments (PLR0913) and magic numbers
  (PLR2004). The format check wraps most long lines of code, but it does not
  split long strings or comments, so a line can still be longer than 100.
- ruff does not check types. No type checker runs in CI.

### Format

**Checks:** The Python code is formatted as ruff format would format it.

**How:** ruff format runs in check mode. It fails when any file would change.
The line length is 100.

**Assumptions:** None.

### Shell scripts

**Checks:** The shell scripts have no shellcheck warnings or errors.

**How:** shellcheck runs on `scripts/check` and the hook
`.claude/hooks/block-main-writes.sh`, at severity warning and above.

**Assumptions:**

- Only these two files are checked. A new shell script is not checked until
  it is added to the list in `scripts/check`.
- Info and style findings do not fail the check.

### TESTS.md coverage

**Checks:** TESTS.md has exactly one entry for each test that pytest collects,
in the section of that test's file, and no entry for a test that does not
exist.

**How:** In `scripts/check`, the pytest run writes the ID of each test that
it collects to a temporary file (option `--collected-tests-file`, from
`tests/conftest.py`), and the check reads that file (option `--collected`).
When the check runs alone, without `--collected`, it runs
`pytest --collect-only`, which lists the tests without running them. Each
pytest test is identified by its file name and its function name. A
parametrized test is one test. The check also reads each file that matches
`tests/js/test_*.js` as a file of JavaScript tests. This repository has no
JavaScript tests, so the check finds none. The check reads TESTS.md and takes
each level-4 heading that is a test name in backticks as an entry. The entry
belongs to the test file named in the nearest level-3 heading above it. The
check then reports:

- each pytest test with no entry in its file's section;
- each entry for a test that does not exist in that file;
- each test with more than one entry;
- each entry that is not under a test file's heading.

It fails if it reports anything, if pytest cannot collect the tests, or if it
cannot read the file of test IDs.

**Assumptions:**

- In `scripts/check`, the check runs after pytest, although this file lists
  it before the tests. When a test fails, `scripts/check` stops, and the
  check does not run.
- In `scripts/check`, pytest runs on the `tests` directory without other
  test selection (no `-k`), so the file of test IDs lists every test.
- Test files are identified by file name only, without the directory. The
  check fails if two test files have the same name.
- The check looks only at the headings. It does not check that an entry has
  its Checks, How and Assumptions parts, or that the text is still correct
  after a test changes.
- A level-4 heading that is not a test name in backticks (for example a
  description of shared test sequences) is not an entry and is ignored.

---

## 2. Tests

### 2.0 The package (`test_package.py`)

`test_package.py` tests that the package installs and imports, and that the
installed package has the version that `pyproject.toml` gives.

#### `test_the_package_imports_and_has_the_version_of_pyproject`

**Checks:** The package `pulseq_analysis` imports from `src/pulseq_analysis` of
this repository, and the installed distribution `pulseq-analysis` has the
version that `pyproject.toml` gives in `[project]`.

**How:** The test imports `pulseq_analysis` and compares the directory of the
imported package with `src/pulseq_analysis` of the repository root. It reads `pyproject.toml` from the
repository root with `tomllib` and takes the value of `[project] version`. It
asks `importlib.metadata` for the version of the distribution `pulseq-analysis`
and compares the two versions.

**Assumptions:**

- The metadata of the distribution `pulseq-analysis` is the metadata of the
  editable install that `uv sync` makes. The test does not check where the
  metadata comes from.
- The version in the installed metadata is the version from the time of the
  last `uv sync`. After a change to the version in `pyproject.toml`, the test
  fails until `uv sync` runs again.
