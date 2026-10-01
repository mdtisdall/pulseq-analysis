"""The gradient system's .asc file (MP_GPA_*.asc, or MP_GradSys_*.asc on newer software)
that the SAFE PNS model reads its hardware parameters from: `read_gradient_asc` and
`hardware_name`, and the name of pypulseq's example hardware, which is used without a
file (`pns_levels.pns_levels`)."""

import re
from pathlib import Path

from pypulseq.utils.siemens.readasc import readasc

EXAMPLE_HARDWARE = "pypulseq example hardware (not a real scanner)"
# A line that includes another .asc file, for example the _GSWD_SAFETY.asc file with the
# SAFE PNS parameters.
INCLUDE_LINE = re.compile(r'^\s*\$INCLUDE\s+"?([^"\s]+)"?\s*$')


def read_gradient_asc(path: str | Path) -> dict:
    """The fields of the .asc file `path`, as pypulseq's `readasc` gives them, and the fields
    of each file that a `$INCLUDE` line names. `readasc` ignores `$INCLUDE`. An included
    file is in the same directory as the file that includes it, and its fields replace
    fields with the same name."""
    path = Path(path)
    asc, _ = readasc(str(path))
    for line in path.read_text().splitlines():
        match = INCLUDE_LINE.match(line)
        if match:
            included = path.parent / match[1]
            if not included.is_file():
                raise FileNotFoundError(
                    f"{path.name} includes {match[1]}, which is not in {path.parent}"
                )
            _merge(asc, read_gradient_asc(included))
    return asc


def _merge(into: dict, fields: dict) -> None:
    for key, value in fields.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value


def hardware_name(asc: dict) -> str:
    """The component name in `asc`: `asCOMP[0].tName` in a scanner file, or `asCOMP.tName`.
    pypulseq's `asc_to_hw` reads only `asCOMP.tName` and gives "unknown" for a scanner
    file."""
    comp = asc.get("asCOMP", {})
    comp = comp.get(0, comp)
    return comp.get("tName", "unknown")
