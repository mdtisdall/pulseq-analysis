"""The SAFE oracle: the original SAFE package (filip-szczepankiewicz/safe_pns_prediction) and
`calcPNS` of MATLAB Pulseq under GNU Octave, run by the command `pulseq-safe-oracle`
(`flake.nix`, `tests/safe_oracle/`). `tests/safe_oracle/README.md` gives its files.

`run_filter` runs `safe_gwf_to_pns` and `safe_hw_check` on the cases that it is given, in one
Octave process. `CalcPnsOracle` runs `calcPNS` at most one time, in one Octave process, on all
the files that it is given and that are not in its cache. The cache is a folder with two files
for each `.seq` file, named by a key: the SHA-256 of the store path of the command (the
resolved path of the executable), of the SHA-256 of the bytes of the `.asc` file and of the
SHA-256 of the bytes of the `.seq` file. So a run with the same files and the same command reads
the cache and does not start Octave.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from pulseq_analysis.analyses.safe import SAFE_FIELDS

COMMAND = "pulseq-safe-oracle"


def command_path() -> Path | None:
    """The resolved path of `pulseq-safe-oracle` on the PATH, or None when it is not there."""
    found = shutil.which(COMMAND)
    return None if found is None else Path(found).resolve()


def _run(command: Path, args: list[str]) -> None:
    """Run the command with `args`. Raises RuntimeError when it does not exit with 0."""
    result = subprocess.run([str(command), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"{COMMAND} exited with {result.returncode}:\n{result.stdout}{result.stderr}"
        )


def hardware_json(hw: object) -> dict:
    """The hardware struct `hw` (an object with `.x`, `.y` and `.z`, each with the fields of
    `SAFE_FIELDS`) as the JSON object of the request: the axes and the fields that `hw` has, so a
    struct without an axis or a field gives an object without it."""
    out = {}
    for axis in "xyz":
        axis_hw = getattr(hw, axis, None)
        if axis_hw is not None:
            out[axis] = {f: getattr(axis_hw, f) for f in SAFE_FIELDS if hasattr(axis_hw, f)}
    return out


def run_filter(
    command: Path,
    cases: dict[str, tuple[np.ndarray, float, object]],
    hw_checks: dict[str, object],
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[str, dict]]:
    """`safe_gwf_to_pns` of the original for each case of `cases` (`id: (gwf, dt, hw)`, `gwf`
    of shape `(n, 3)`, `dt` in s, `hw` a hardware struct), and `safe_hw_check` for each struct
    of `hw_checks` (`id: hw`), in one run of the command.

    Returns `(rows, checks)`. `rows[id]` is `(pns, inputs)`: `pns` the `(n, 3)` rows of the
    waveform with no padding and with the samples before it at 0, in percent; `inputs` the
    `dt` and the 27 fields (`SAFE_FIELDS` of x, y and z) as Octave read them from the JSON.
    `checks[id]` is `{"is_ok": 0 or 1}`, or `{"error": message}` when `safe_hw_check` failed
    (for a struct without an axis or a field). Raises RuntimeError when the command fails."""
    with tempfile.TemporaryDirectory() as tmp:
        folder, out = Path(tmp) / "in", Path(tmp) / "out"
        folder.mkdir()
        request = {"cases": [], "hw_checks": []}
        for case_id, (gwf, dt, hw) in cases.items():
            gwf = np.ascontiguousarray(gwf, dtype="<f8")
            gwf.tofile(folder / f"{case_id}.f64")
            request["cases"].append(
                {
                    "id": case_id,
                    "dt": dt,
                    "gwf": f"{case_id}.f64",
                    "rows": gwf.shape[0],
                    "hw": hardware_json(hw),
                }
            )
        for case_id, hw in hw_checks.items():
            request["hw_checks"].append({"id": case_id, "hw": hardware_json(hw)})
        # `json` writes a float as `repr`, the shortest text that reads back as the same
        # double; `inputs` shows what Octave read.
        (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
        _run(command, ["filter", str(folder / "request.json"), str(out)])
        rows = {}
        for case_id in cases:
            pns = np.fromfile(out / f"{case_id}.f64", dtype="<f8").reshape(-1, 3)
            inputs = np.fromfile(out / f"{case_id}.inputs.f64", dtype="<f8")
            rows[case_id] = (pns, inputs)
        checks = json.loads((out / "hw_check.json").read_text(encoding="utf-8"))
    return rows, {c.pop("id"): c for c in checks}


class CalcPnsOracle:
    """`calcPNS` of MATLAB Pulseq for `.seq` files, with the cache folder `cache_dir`."""

    def __init__(self, cache_dir: Path, command: Path):
        self._cache_dir = Path(cache_dir)
        self._command = Path(command)
        self._ran = False

    def _key(self, asc_hash: str, data: bytes) -> str:
        """The key of a `.seq` file with the bytes `data`, for the `.asc` file of the SHA-256
        `asc_hash` and this command."""
        file_hash = hashlib.sha256(data).hexdigest()
        return hashlib.sha256(f"{self._command}\n{asc_hash}\n{file_hash}".encode()).hexdigest()

    def load(self, asc: Path, paths: list[Path]) -> dict[Path, tuple[dict, np.ndarray | None]]:
        """`calcPNS(asc, false)` of each file of `paths`, by path: the parsed JSON of the file
        and its rows, an array of shape `(num_samples, 4)` (the three axes and the total, as a
        fraction of the stimulation limit), or None when the JSON has an `error`. The files
        that are not in the cache are read by one run of the command, which this oracle does at
        most one time. Raises RuntimeError when the command fails or does not write the files
        of a `.seq` file, and when a second run is needed."""
        asc_bytes = Path(asc).read_bytes()
        asc_hash = hashlib.sha256(asc_bytes).hexdigest()
        contents = {Path(p): Path(p).read_bytes() for p in paths}
        keys = {p: self._key(asc_hash, data) for p, data in contents.items()}
        missing = {
            keys[p]: contents[p] for p in contents if not self._entry(keys[p], ".json").exists()
        }
        if missing:
            self._run(asc_bytes, missing)
        out = {}
        for p, key in keys.items():
            dump = json.loads(self._entry(key, ".json").read_text(encoding="utf-8"))
            rows = None
            if "error" not in dump:
                rows = np.fromfile(self._entry(key, ".f64"), dtype="<f8").reshape(-1, 4)
            out[p] = (dump, rows)
        return out

    def _entry(self, key: str, suffix: str) -> Path:
        return self._cache_dir / f"{key}{suffix}"

    def _run(self, asc: bytes, files: dict[str, bytes]) -> None:
        """Run the command on the files `files` (bytes by key) with the `.asc` file of the bytes
        `asc`, and put the files of each in the cache. The command reads a copy of each file
        named `<key>.seq`, so two files never have one stem."""
        if self._ran:
            raise RuntimeError(f"{COMMAND} ran already in this session")
        self._ran = True
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._cache_dir) as tmp:
            inputs, outputs = Path(tmp) / "in", Path(tmp) / "out"
            inputs.mkdir()
            outputs.mkdir()
            (inputs / "hardware.asc").write_bytes(asc)
            names = []
            for key, data in files.items():
                (inputs / f"{key}.seq").write_bytes(data)
                names.append(str(inputs / f"{key}.seq"))
            _run(self._command, ["calcpns", str(inputs / "hardware.asc"), str(outputs), *names])
            for key in files:
                written = outputs / f"{key}.json"
                if not written.exists():
                    raise RuntimeError(f"{COMMAND} wrote no JSON for a file")
                # In the cache folder, so each move is one rename. The JSON is moved last, and
                # `load` reads an entry only when its JSON exists: an entry is complete.
                if (outputs / f"{key}.f64").exists():
                    os.replace(outputs / f"{key}.f64", self._entry(key, ".f64"))
                os.replace(written, self._entry(key, ".json"))
