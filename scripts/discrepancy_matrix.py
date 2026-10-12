"""The acceptance matrix of `docs/discrepancies.md`: each `.seq` file of `tests/seqfiles` (the
fixtures and `oracle/`) through the four readers, as a Markdown table on stdout.

- pulseq-analysis: `reader.read_seqfile`. "accept", or the rule IDs of the violations.
- C++: `pulseq-cpp-oracle FILE`, the reader `ExternalSequence` of pulseq/pulseq
  (`tests/cpp_oracle`). "accept" (exit 0), "reject" (exit 1), "crash" and the exit status (70 is
  a signal), or "no end in 10 s".
- MATLAB: `pulseq-matlab-oracle`, MATLAB Pulseq under GNU Octave (`tests/matlab_oracle`). It
  calls `read`, then `getBlock` for each block and `waveforms_and_times`, so an error can come
  from any of them. "read", or "error:" and the first line of the message. It is not run on a
  file where `read_seqfile` finds a cycle in an extension list: `read` of MATLAB Pulseq may not
  return on one.
- pypulseq: `pypulseq.Sequence().read(FILE)` with its defaults, in a separate process. "read",
  or the type of the exception and the first line of its message, or "no end in 10 s".
- pypulseq, probe: the same on a copy of the file without the parts that pypulseq cannot read
  and that most fixtures have (`probe_text`), so that the change of a fixture is what pypulseq
  meets. "=" when the copy is the file.

A message longer than `WIDTH` characters is cut. Run it in the devShell, where both oracles are
on the PATH:

    nix develop --command uv run python scripts/discrepancy_matrix.py

`--cpp` and `--matlab` give the path of an oracle that is not on the PATH. A reader that cannot
run gives "not run" in its column. The time of the run goes to stderr.
"""

import argparse
import json
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pulseq_analysis.seqfile.reader import SeqFileError, read_seqfile

ROOT = Path(__file__).resolve().parent.parent
SEQFILES = ROOT / "tests" / "seqfiles"
TIMEOUT = 10  # s for one file in the C++ oracle and in pypulseq
WIDTH = 70  # characters of a message in the table

# The extensions that pypulseq's `read` reads. It raises `ValueError` on any other.
PYPULSEQ_EXTENSIONS = {"TRIGGERS", "LABELSET", "LABELINC", "DELAYS"}

# The child process for pypulseq: it reads one path for each line of stdin and writes one JSON
# line for each. The parent starts a new one when a file takes more than `TIMEOUT` s.
PYPULSEQ_WORKER = """
import json, sys, warnings
warnings.simplefilter("ignore")
import pypulseq as pp
for line in sys.stdin:
    path = line.rstrip("\\n")
    try:
        pp.Sequence().read(path)
        verdict = "read"
    except BaseException as error:
        first = (str(error).strip().splitlines() or [""])[0]
        verdict = f"{type(error).__name__}: {first}" if first else type(error).__name__
    print(json.dumps(verdict), flush=True)
"""


def probe_text(text: str) -> str:
    """`text` without the `extension` sections that pypulseq does not read (header and rows, up
    to a blank line) and without the `RequiredExtensions` line, and with time ID -1 set to 0 in
    each row of `[GRADIENTS]` of 7 values (pypulseq's `read` fails on -1)."""
    out: list[str] = []
    skip, section = False, ""
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("extension "):
            section = "extension"
            skip = s.split()[1] not in PYPULSEQ_EXTENSIONS
        elif s.startswith("["):
            section, skip = s, False
        elif skip and not s:
            skip = False
            continue
        if skip or s.startswith("RequiredExtensions"):
            continue
        tokens = s.split()
        if section == "[GRADIENTS]" and len(tokens) == 7 and tokens[5] == "-1":
            tokens[5] = "0"
            line = " ".join(tokens)
        out.append(line)
    return "\n".join(out)


def cut(text: str) -> str:
    return text if len(text) <= WIDTH else text[: WIDTH - 1] + "…"


def package_verdict(path: Path) -> tuple[str, bool]:
    """The verdict of `read_seqfile` and whether it found a cycle in an extension list."""
    try:
        read_seqfile(path)
    except SeqFileError as error:
        rules = sorted({v.rule for v in error.violations})
        cycle = any("cycle" in v.message for v in error.violations)
        return " ".join(f"`{r}`" for r in rules), cycle
    return "accept", False


def cpp_verdict(oracle: str | None, path: Path) -> str:
    if oracle is None:
        return "not run"
    try:
        result = subprocess.run(
            [oracle, str(path)], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return f"no end in {TIMEOUT} s"
    return {0: "accept", 1: "reject"}.get(result.returncode, f"crash ({result.returncode})")


def matlab_verdicts(oracle: str | None, paths: list[Path]) -> dict[Path, str]:
    """The verdict of MATLAB Pulseq for each of `paths`, from one run of the oracle for the
    files of different names (the oracle writes `<stem>.json`)."""
    out: dict[Path, str] = {}
    if oracle is None:
        return out
    groups: list[list[Path]] = []
    for path in paths:
        group = next((g for g in groups if all(p.stem != path.stem for p in g)), None)
        if group is None:
            groups.append([path])
        else:
            group.append(path)
    with tempfile.TemporaryDirectory() as tmp:
        for i, group in enumerate(groups):
            folder = Path(tmp) / str(i)
            folder.mkdir()
            subprocess.run(
                [oracle, str(folder), *map(str, group)], capture_output=True, text=True, check=True
            )
            for path in group:
                result = json.loads((folder / f"{path.stem}.json").read_text())
                if isinstance(result, dict) and "error" in result:
                    first = (str(result["error"]).strip().splitlines() or [""])[0]
                    out[path] = cut(f"error: {first}")
                else:
                    out[path] = "read"
    return out


def pypulseq_verdicts(paths: list[Path]) -> dict[Path, str]:
    """The verdict of pypulseq's `read` for each of `paths`, in a child process."""
    out: dict[Path, str] = {}
    todo = list(paths)
    while todo:
        worker = subprocess.Popen(
            [sys.executable, "-c", PYPULSEQ_WORKER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert worker.stdin is not None and worker.stdout is not None
        try:
            while todo:
                path = todo.pop(0)
                worker.stdin.write(f"{path}\n")
                worker.stdin.flush()
                line = _read_line(worker, TIMEOUT)
                if not line:  # no line in time, or the process ended
                    out[path] = f"no end in {TIMEOUT} s" if line is None else "crash"
                    break
                out[path] = cut(json.loads(line))
        finally:
            worker.kill()
            worker.wait()
    return out


def _read_line(process: subprocess.Popen, timeout: float) -> str | None:
    """A line of stdout of `process`, or None when none comes in `timeout` s."""
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout):
            return None
    return process.stdout.readline()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cpp", default=shutil.which("pulseq-cpp-oracle"))
    parser.add_argument("--matlab", default=shutil.which("pulseq-matlab-oracle"))
    args = parser.parse_args()

    start = time.perf_counter()
    paths = sorted(SEQFILES.rglob("*.seq"), key=lambda p: p.relative_to(SEQFILES).as_posix())
    package, cycles = {}, set()
    for path in paths:
        package[path], cycle = package_verdict(path)
        if cycle:
            cycles.add(path)
    cpp = {path: cpp_verdict(args.cpp, path) for path in paths}
    matlab = matlab_verdicts(args.matlab, [p for p in paths if p not in cycles])
    for path in cycles:
        matlab[path] = "not run (a cycle in an extension list)"
    with tempfile.TemporaryDirectory() as tmp:
        probes: dict[Path, Path] = {}
        for i, path in enumerate(paths):
            text = path.read_text(encoding="utf-8", errors="surrogateescape")
            changed = probe_text(text)
            if changed != text:
                probes[path] = Path(tmp) / f"{i}.seq"
                probes[path].write_text(changed, encoding="utf-8", errors="surrogateescape")
        pypulseq = pypulseq_verdicts(paths + list(probes.values()))

    print("| File | pulseq-analysis | C++ reader | MATLAB Pulseq | pypulseq | pypulseq, probe |")
    print("|---|---|---|---|---|---|")
    for path in paths:
        name = path.relative_to(SEQFILES).as_posix()
        probe = pypulseq[probes[path]] if path in probes else "="
        cells = (package[path], cpp[path], matlab.get(path, "not run"), pypulseq[path], probe)
        cells = tuple(c.replace("|", "\\|") for c in cells)
        print(f"| `{name}` | " + " | ".join(cells) + " |")
    print(f"{len(paths)} files in {time.perf_counter() - start:.0f} s.", file=sys.stderr)


if __name__ == "__main__":
    main()
