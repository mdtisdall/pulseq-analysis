"""Put the files of the C++ reader in third_party/pulseq/, where the sdist carries them and
CMakeLists.txt finds them: from PULSEQ_SOURCE_DIR (the Nix devShell sets it), else from
raw.githubusercontent.com at the commit of pulseq-reader.sha256. It checks the SHA-256 of each
file, and refuses a file with another hash.

    python packages/pulseq-cpp-siemens/scripts/fetch_reader.py
"""

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE / "pulseq-reader.sha256"
TARGET = PACKAGE / "third_party" / "pulseq"


def manifest() -> tuple[str, list[tuple[str, str]]]:
    """The commit and each (SHA-256, path) of pulseq-reader.sha256."""
    commit, files = "", []
    for line in MANIFEST.read_text().splitlines():
        if line.startswith("# commit "):
            commit = line.split()[-1]
        elif line and not line.startswith("#"):
            sha256, name = line.split(maxsplit=1)
            files.append((sha256, name))
    if not commit or not files:
        sys.exit(f"{MANIFEST} names no commit or no file")
    return commit, files


def main() -> None:
    commit, files = manifest()
    source = os.environ.get("PULSEQ_SOURCE_DIR")
    for sha256, name in files:
        if source:
            data = (Path(source) / name).read_bytes()
            origin = f"{source}/{name}"
        else:
            origin = f"https://raw.githubusercontent.com/pulseq/pulseq/{commit}/{name}"
            with urllib.request.urlopen(origin, timeout=60) as response:
                data = response.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            sys.exit(f"{origin}: SHA-256 {actual}, expected {sha256} (pulseq/pulseq {commit})")
        path = TARGET / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{path.relative_to(PACKAGE)} from {origin}")


if __name__ == "__main__":
    main()
