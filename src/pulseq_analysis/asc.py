"""The optional reader of a Siemens gradient system .asc file (MP_GPA_*.asc, or
MP_GradSys_*.asc on newer software) into the vendor-neutral hardware pair that the SAFE PNS
functions take: `hardware_from_asc` makes the pair `(struct, label)` for `hardware=`, and
`read_gradient_asc` and `hardware_name` are the parts that it uses. The PNS functions take
only the pair, never a file path."""

import re
from pathlib import Path
from types import SimpleNamespace

from pypulseq.utils.siemens.asc_to_hw import asc_to_hw
from pypulseq.utils.siemens.readasc import readasc

# A line that includes another .asc file, for example the _GSWD_SAFETY.asc file with the
# SAFE PNS parameters: `$INCLUDE` in any case, then the name (in double quotes when it has
# spaces), then optionally a comment that starts with `#` or `//` (the comment marks that
# pypulseq's `readasc` accepts after a value). Group "quoted" or group "bare" is the name.
_INCLUDE_LINE = re.compile(
    r'^\s*\$INCLUDE\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>(?:(?!//)[^"\s#])+))\s*(?:#|//|$)',
    re.IGNORECASE,
)
# A line that starts with `$INCLUDE` (in any case), whether or not `_INCLUDE_LINE` matches.
_INCLUDE_START = re.compile(r"^\s*\$INCLUDE", re.IGNORECASE)


def read_gradient_asc(path: str | Path) -> dict:
    """The fields of the .asc file `path`, as pypulseq's `readasc` gives them, and the fields
    of each file that a `$INCLUDE` line names. `readasc` ignores `$INCLUDE`. An included
    file is in the same directory as the file that includes it, and its fields replace
    fields with the same name: an included field wins over a field that the including file
    sets after its `$INCLUDE` line. A `$INCLUDE` line is `$INCLUDE` in any case, a name (in
    double quotes when it has spaces) and optionally a comment that starts with `#` or `//`.
    Any other line that starts with `$INCLUDE` raises `ValueError` that names the file and
    the line. When a `$INCLUDE` line names a file that is already on the chain of includes
    that leads to it (or the file itself), `ValueError` names the cycle. A file that two
    branches include is not a cycle."""
    return _read_with_includes(Path(path), ())


def _read_with_includes(path: Path, chain_before: tuple[Path, ...]) -> dict:
    """`read_gradient_asc` of `path`, which the files of `chain_before` include in turn."""
    chain = (*chain_before, path.resolve())
    asc, _ = readasc(str(path))
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if _INCLUDE_START.match(line):
            match = _INCLUDE_LINE.match(line)
            if not match:
                raise ValueError(f"{path.name}, line {number}: cannot read the include {line!r}")
            name = match["quoted"] or match["bare"]
            included = path.parent / name
            if not included.is_file():
                raise FileNotFoundError(
                    f"{path.name} includes {name}, which is not in {path.parent}"
                )
            if included.resolve() in chain:
                names = [p.name for p in chain[chain.index(included.resolve()) :]]
                raise ValueError(f"$INCLUDE cycle: {' -> '.join([*names, included.name])}")
            _merge(asc, _read_with_includes(included, chain))
    return asc


def hardware_from_asc(path: str | Path) -> tuple[SimpleNamespace, str]:
    """The `hardware` pair of the .asc file `path`, for
    `pns_levels.pns_levels(seq, hardware=...)`: `(asc_to_hw(asc), hardware_name(asc))`, where
    `asc` is `read_gradient_asc(path)` (with its `$INCLUDE` rule). The label is the
    component name in the file, so a pair has no path in it: two spellings of the path of
    one file give equal pairs."""
    asc = read_gradient_asc(path)
    return asc_to_hw(asc), hardware_name(asc)


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
