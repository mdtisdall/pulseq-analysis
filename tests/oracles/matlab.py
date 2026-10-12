"""The MATLAB oracle: MATLAB Pulseq under GNU Octave, run by the command `pulseq-matlab-oracle`
(`flake.nix`, `tests/matlab_oracle/`). `tests/matlab_oracle/README.md` gives the JSON of a file.

`MatlabOracle` runs the command at most one time, in one Octave process, on all the files that
it is given and that are not in its cache. The cache is a folder of JSON files, one for each
file, named by a key: the SHA-256 of the store path of the command (the resolved path of the
executable) and of the SHA-256 of the bytes of the file. So a run with the same files and the
same command reads the cache and does not start Octave.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

COMMAND = "pulseq-matlab-oracle"


def command_path() -> Path | None:
    """The resolved path of `pulseq-matlab-oracle` on the PATH, or None when it is not there."""
    found = shutil.which(COMMAND)
    return None if found is None else Path(found).resolve()


class MatlabOracle:
    """The JSON of MATLAB Pulseq for `.seq` files, with the cache folder `cache_dir`."""

    def __init__(self, cache_dir: Path, command: Path):
        self._cache_dir = Path(cache_dir)
        self._command = Path(command)
        self._ran = False

    def _key(self, data: bytes) -> str:
        """The key of a file with the bytes `data`, for this command."""
        file_hash = hashlib.sha256(data).hexdigest()
        return hashlib.sha256(f"{self._command}\n{file_hash}".encode()).hexdigest()

    def load(self, paths: list[Path]) -> dict[Path, dict]:
        """The parsed JSON of each file of `paths`, by path. The files that are not in the cache
        are read by one run of the command, which this oracle does at most one time. Raises
        RuntimeError when the command fails or does not write the JSON of a file, and when a
        second run is needed."""
        contents = {Path(p): Path(p).read_bytes() for p in paths}
        keys = {p: self._key(data) for p, data in contents.items()}
        missing = {keys[p]: contents[p] for p in contents if not self._entry(keys[p]).exists()}
        if missing:
            self._run(missing)
        return {
            p: json.loads(self._entry(key).read_text(encoding="utf-8")) for p, key in keys.items()
        }

    def _entry(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def _run(self, files: dict[str, bytes]) -> None:
        """Run the command on the files `files` (bytes by key) and put each JSON in the cache. The
        command reads a copy of each file named `<key>.seq`, so two files never have one stem."""
        if self._ran:
            raise RuntimeError(f"{COMMAND} ran already in this session")
        self._ran = True
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._cache_dir) as tmp:
            inputs, outputs = Path(tmp) / "in", Path(tmp) / "out"
            inputs.mkdir()
            outputs.mkdir()
            names = []
            for key, data in files.items():
                (inputs / f"{key}.seq").write_bytes(data)
                names.append(str(inputs / f"{key}.seq"))
            result = subprocess.run(
                [str(self._command), str(outputs), *names],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"{COMMAND} exited with {result.returncode}:\n{result.stdout}{result.stderr}"
                )
            for key in files:
                written = outputs / f"{key}.json"
                if not written.exists():
                    raise RuntimeError(
                        f"{COMMAND} wrote no JSON for a file:\n{result.stdout}{result.stderr}"
                    )
                # In the cache folder, so the move is one rename: a JSON there is complete.
                os.replace(written, self._entry(key))
