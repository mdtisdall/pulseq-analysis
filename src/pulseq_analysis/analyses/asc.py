"""The optional reader of a Siemens gradient system .asc file (MP_GPA_*.asc, or
MP_GradSys_*.asc on newer software) into the SAFE hardware that the SAFE PNS functions take:
`hardware_from_asc` makes the `SafeHardware` for `hardware=`, and `read_gradient_asc`,
`safe_hardware` and `hardware_name` are the parts that it uses. The PNS functions take only a
`SafeHardware`, never a file path. This module does not import pypulseq."""

import re
from pathlib import Path

from .safe import SafeAxis, SafeHardware

__all__ = ["hardware_from_asc", "hardware_name", "read_gradient_asc", "safe_hardware"]

# A line that includes another .asc file, for example the _GSWD_SAFETY.asc file with the
# SAFE PNS parameters: `$INCLUDE` in any case, then the name (in double quotes when it has
# spaces), then optionally a comment that starts with `#` or `//` (the comment marks that
# `_FIELD_LINE` accepts after a value). Group "quoted" or group "bare" is the name.
_INCLUDE_LINE = re.compile(
    r'^\s*\$INCLUDE\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>(?:(?!//)[^"\s#])+))\s*(?:#|//|$)',
    re.IGNORECASE,
)
# A line that starts with `$INCLUDE` (in any case), whether or not `_INCLUDE_LINE` matches.
_INCLUDE_START = re.compile(r"^\s*\$INCLUDE", re.IGNORECASE)
# A line that sets a field, as `a[0].b[2][3].c = "string" # comment`, with the line stripped.
# The value is a double-quoted string, a single quoted character, a hex integer (`0x` and hex
# digits), an integer (digits, with an optional `-`), or a number of the characters `0-9`, `.`,
# `e`, `E`, `+` and `-` (read as a float, so that `float` names a number that it cannot read).
# A comment that starts with `#` or `//` can follow it. The brackets are not checked here (see
# `_field_keys`).
_FIELD_LINE = re.compile(
    r"^\s*(?P<name>[a-zA-Z0-9\[\]\._]+)\s*=\s*"
    r"(?:(?P<string>\"[^\"]*\"|'[^']')|(?P<hex>0[xX][0-9a-fA-F]+)|(?P<int>-?\d+)"
    r"|(?P<float>[0-9\.eE+\-]+))"
    r"\s*(?:(?:#|//).*)?$"
)
# One part of a field name between dots: a name and zero or more indices, as `b[2][3]`.
_NAME_PART = re.compile(r"^(?P<name>[A-Za-z0-9_]+)(?P<indices>(?:\[\d+\])*)$")
# The line that ends the `ASCCONV` block. The fields after it are not fields of the file.
_ASCCONV_END = "### ASCCONV END ###"


def read_gradient_asc(path: str | Path) -> dict:
    """The fields of the .asc file `path`, and the fields of each file that a `$INCLUDE` line
    names.

    A line `a[0].b[2][3].c = "string" # comment` sets the field
    `fields["a"][0]["b"][2][3]["c"]`: a nested dict, with the name of each part as a `str`
    key and each index as an `int` key. The value is a `str` for a quoted string, an `int`
    for digits with an optional `-` and for hex (`0x1F`), and else a `float` (of the
    characters `0-9`, `.`, `e`, `E`, `+` and `-`, as `1.5E-3` or `1e+02`). The comment
    starts with `#` or `//`. A blank line, a line that starts with `#` and the lines after
    the line `### ASCCONV END ###` (also a line with `=` that is not a field) are left out.
    A line with `=` that is not a field, a field name that is not names with indices, a
    number that is not a float, and a field that sets a name under a value that is not a
    dict, raise `ValueError` that names the file and the line. The file is read as latin-1,
    so every byte is read.

    An included file is in the same directory as the file that includes it, and its fields
    replace fields with the same name: an included field wins over a field that the
    including file sets after its `$INCLUDE` line. A `$INCLUDE` line is `$INCLUDE` in any
    case, a name (in double quotes when it has spaces) and optionally a comment that starts
    with `#` or `//`. Any other line that starts with `$INCLUDE` raises `ValueError` that
    names the file and the line. When a `$INCLUDE` line names a file that is already on the
    chain of includes that leads to it (or the file itself), `ValueError` names the cycle. A
    file that two branches include is not a cycle."""
    return _read_with_includes(Path(path), ())


def _read_with_includes(path: Path, chain_before: tuple[Path, ...]) -> dict:
    """`read_gradient_asc` of `path`, which the files of `chain_before` include in turn."""
    chain = (*chain_before, path.resolve())
    asc, includes = _read_fields(path)
    for name in includes:
        included = path.parent / name
        if not included.is_file():
            raise FileNotFoundError(f"{path.name} includes {name}, which is not in {path.parent}")
        if included.resolve() in chain:
            names = [p.name for p in chain[chain.index(included.resolve()) :]]
            raise ValueError(f"$INCLUDE cycle: {' -> '.join([*names, included.name])}")
        _merge(asc, _read_with_includes(included, chain))
    return asc


def _read_fields(path: Path) -> tuple[dict, list[str]]:
    """The fields of the file `path` alone, and the names of the files that its `$INCLUDE`
    lines name, in the order of the lines."""
    fields: dict = {}
    includes: list[str] = []
    ended = False
    for number, line in enumerate(path.read_text(encoding="latin-1").split("\n"), 1):
        if _INCLUDE_START.match(line):
            match = _INCLUDE_LINE.match(line)
            if not match:
                raise ValueError(f"{path.name}, line {number}: cannot read the include {line!r}")
            includes.append(match["quoted"] or match["bare"])
            continue
        text = line.strip()
        if text == _ASCCONV_END:
            ended = True
        if not text or text[0] == "#" or ended:
            continue
        match = _FIELD_LINE.match(text)
        if match is None:
            if "=" in text:
                raise ValueError(f"{path.name}, line {number}: cannot read the field {text!r}")
            continue
        try:
            keys = _field_keys(match["name"])
            _set_field(fields, keys, _field_value(match))
        except ValueError as error:
            raise ValueError(f"{path.name}, line {number}: {error}") from None
    return fields, includes


def _field_keys(name: str) -> list[str | int]:
    """The keys of the field `name`, for example `a.b[2][3]` gives `["a", "b", 2, 3]`."""
    keys: list[str | int] = []
    for part in name.split("."):
        match = _NAME_PART.match(part)
        if match is None:
            raise ValueError(f"cannot read the field name {name!r}")
        keys.append(match["name"])
        keys += [int(index) for index in re.findall(r"\d+", match["indices"])]
    return keys


def _field_value(match: re.Match) -> str | float:
    """The value of a line that `_FIELD_LINE` matched."""
    if match["string"] is not None:
        return match["string"][1:-1]
    if match["hex"] is not None:
        return int(match["hex"], 16)
    if match["int"] is not None:
        return int(match["int"])
    try:
        return float(match["float"])
    except ValueError:
        raise ValueError(f"cannot read the number {match['float']!r}") from None


def _set_field(fields: dict, keys: list[str | int], value: str | float) -> None:
    """Sets `fields[keys[0]][keys[1]]...` to `value`, with a new dict for each key that is
    not there."""
    node = fields
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            # A value in the file, not an argument of this function: ValueError, not TypeError.
            raise ValueError(  # noqa: TRY004
                f"cannot set a field under {key!r}, which has the value {node!r}"
            )
    node[keys[-1]] = value


def hardware_from_asc(path: str | Path) -> SafeHardware:
    """The `hardware` of the .asc file `path`, for
    `pns_levels.pns_levels(snap, hardware=...)`: `safe_hardware(asc)`, where `asc` is
    `read_gradient_asc(path)` (with its `$INCLUDE` rule). Its name, the label of the result
    of `pns_levels`, is `hardware_name(asc)`, the component name in the file, so it has no
    path in it: two spellings of the path of one file give equal `SafeHardware`s. Raises
    `ValueError` for a file with no gradient scale factors (see `safe_hardware`), and for a
    component name that a `SafeHardware` refuses ("nan", "inf" or "-inf")."""
    return safe_hardware(read_gradient_asc(path))


def _merge(into: dict, fields: dict) -> None:
    for key, value in fields.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value


def hardware_name(asc: dict) -> str:
    """The component name in `asc`: `asCOMP[0].tName` in a scanner file, or `asCOMP.tName`.
    "unknown" when there is neither."""
    comp = asc.get("asCOMP", {})
    comp = comp.get(0, comp)
    return comp.get("tName", "unknown")


def safe_hardware(asc: dict) -> SafeHardware:
    """The `SafeHardware` of `asc`, the fields that `read_gradient_asc` gives. Its name is
    `hardware_name(asc)`. The fields of each axis (`X`, `Y`, `Z` for `x`, `y`, `z`) are:

    - `flGSWDTau<axis>[0]` to `[2]` for `tau1` to `tau3`, and `flGSWDA<axis>[0]` to `[2]`
      for `a1` to `a3`;
    - `flGSWDStimulationLimit<axis>` and `flGSWDStimulationThreshold<axis>` for `stim_limit`
      and `stim_thresh`;
    - `asGPAParameters[0].sGCParameters.flGScaleFactor<axis>` for `g_scale`.

    The fields of the first two items are under `GradPatSup.Phys.PNS.` in a scanner file (a
    file with a `GradPatSup` field), and at the top in the plain layout.

    Raises `ValueError` that names the field when `asc` has no field of the list. There is no
    default for the gradient scale factors: the SAFE model multiplies each PNS value by the
    factor of its axis, so a file without it gives no hardware. Raises the errors of
    `SafeAxis` for a value that is not valid, and those of `SafeHardware` for a name that is
    not valid."""
    if "GradPatSup" in asc:
        prefix, pns = (
            "GradPatSup.Phys.PNS.",
            _lookup(asc, "GradPatSup.Phys.PNS", "GradPatSup", "Phys", "PNS"),
        )
    else:
        prefix, pns = "", asc

    def pns_field(name: str, *indices: int) -> object:
        shown = prefix + name + "".join(f"[{i}]" for i in indices)
        return _lookup(pns, shown, name, *indices)

    axes = {}
    for axis in "xyz":
        suffix = axis.upper()
        values = {}
        for i in range(3):
            values[f"tau{i + 1}"] = pns_field(f"flGSWDTau{suffix}", i)
            values[f"a{i + 1}"] = pns_field(f"flGSWDA{suffix}", i)
        values["stim_limit"] = pns_field(f"flGSWDStimulationLimit{suffix}")
        values["stim_thresh"] = pns_field(f"flGSWDStimulationThreshold{suffix}")
        values["g_scale"] = _gradient_scale_factor(asc, suffix)
        axes[axis] = SafeAxis(**values)
    return SafeHardware(hardware_name(asc), **axes)


def _gradient_scale_factor(asc: dict, suffix: str) -> object:
    """`asGPAParameters[0].sGCParameters.flGScaleFactor<suffix>` of `asc`. Raises `ValueError`
    that says that the file has no gradient scale factor when it is not there."""
    name = f"asGPAParameters[0].sGCParameters.flGScaleFactor{suffix}"
    try:
        return _lookup(asc, name, "asGPAParameters", 0, "sGCParameters", f"flGScaleFactor{suffix}")
    except ValueError:
        raise ValueError(
            f"the .asc file has no gradient scale factor {name}. The SAFE model multiplies "
            "each PNS value by it, so the package does not assume one"
        ) from None


def _lookup(fields: dict, name: str, *keys: str | int) -> object:
    """`fields[keys[0]][keys[1]]...`. Raises `ValueError` that names the field `name` when a
    key is not there."""
    node: object = fields
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"the .asc file has no field {name}")
        node = node[key]
    return node
