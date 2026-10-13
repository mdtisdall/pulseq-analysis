"""The IDs of the record entries: the old IDs D01a to D60 and the IDs by kind of decision, D1.1 to D7.n.

On 2026-10-13 the entries of `docs/discrepancies.md` (D1 to D4, the decisions of `spec`) and of
`packages/pulseq-cpp-siemens/docs/specification.md` (D5 to D7, the exceptions of `cpp-siemens`)
were regrouped by kind of decision. An ID now names a decision, not a condition: a condition on
which each interpreter decides has two IDs. An old entry with decisions of several kinds was split,
and an old entry that records no decision of the two interpreters was removed (`REMOVED`).

    nix develop --command uv run python scripts/record_ids.py table
    nix develop --command uv run python scripts/record_ids.py apply FILE...

`table` writes the table of the record's appendix (old ID, new IDs) to stdout. `apply` rewrites,
in each file, each old ID that has exactly one new ID, and lists every other old ID that it finds
(split or removed) with its line and the candidates, for a person to resolve. Historical documents
(the plans of finished tasks, released CHANGELOG entries) keep the old IDs.
"""

import re
import sys
from pathlib import Path

# The entries by kind: new ID -> (title, old IDs it comes from, codes).
ENTRIES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    # D1: the specification is unclear, and `spec` resolves it.
    "D1.1": ("A file with no [VERSION] section (a recommendation)", ("D02",), ("version.missing",)),
    "D1.2": (
        "The number of fields of an [RF], [GRADIENTS] or [ADC] row (prose against tables)",
        ("D01a", "D01b", "D01c"),
        ("syntax.columns",),
    ),
    "D1.3": (
        "A vertex of a gradient time shape off the gradient raster (slide 6 against slide 4)",
        ("D26",),
        ("raster.gradient-vertex",),
    ),
    "D1.4": (
        "An extension header whose STRING_ID is a word (table against examples)",
        ("D55",),
        (),
    ),
    # D2: the specification is silent, and `spec` reads the file.
    "D2.1": ("Sections in any order", ("D05",), ()),
    "D2.2": ("The last section with no blank line after it", ("D56",), ()),
    "D2.3": ("[EXTENSIONS] as the last section", ("D46",), ()),
    "D2.4": ("A section that the format does not have", ("D08",), ()),
    "D2.5": ("A blank or # line inside a section", ("D06",), ()),
    "D2.6": ("A definition that appears twice", ("D12",), ()),
    "D2.7": ("A definition or a signature hash whose text reads as a number", ("D13",), ()),
    "D2.8": ("An RF magnitude sample below 0", ("D31",), ()),
    "D2.9": ("An RF phase sample outside [0, 1)", ("D32",), ()),
    "D2.10": ("An RF time shape whose times are (i + 0.5) d: cells", ("D35",), ()),
    "D2.11": ("Any other RF time shape: points", ("D36",), ()),
    "D2.12": ("Where an RF pulse with a time shape ends", ("D37",), ()),
    "D2.13": ("An arbitrary gradient between its samples (time ID 0)", ("D41",), ()),
    "D2.14": ("A gap between two gradient events on one axis", ("D42",), ()),
    "D2.15": ("An ADC phase modulation shape: rad, one value per sample", ("D44",), ()),
    "D2.16": ("A soft delay offset with a fraction, or a long hint", ("D16",), ()),
    "D2.17": ("An unknown extension that the file does not require", ("D45",), ()),
    "D2.18": ("A rotation quaternion: divided by its norm", ("D49",), ()),
    "D2.19": ("A label that the specification does not list", ("D50",), ()),
    # D3: the specification is silent, and `spec` rejects by choice.
    "D3.1": ("A byte that is not UTF-8", ("D14",), ("syntax.encoding",)),
    "D3.2": ("A data line before the first section", ("D06",), ("syntax.line",)),
    "D3.3": ("A section that appears twice", ("D10",), ("section.duplicate",)),
    "D3.4": ("A block ID used twice", ("D19",), ("id.unique",)),
    "D3.5": ("NaN or infinity in a float column", ("D14",), ("syntax.number",)),
    "D3.6": ("A negative time or count", ("D14",), ("syntax.negative",)),
    "D3.7": ("An event that uses a shape with no sample", ("D33",), ("shape.empty",)),
    "D3.8": (
        "The shapes of one event with different numbers of samples",
        ("D34", "D44"),
        ("shape.event-length",),
    ),
    "D3.9": (
        "An RF time shape of one sample, or times that do not increase or start below 0",
        ("D36",),
        ("shape.time-order",),
    ),
    "D3.10": ("A rotation quaternion of norm 0", ("D49",), ("rotation.zero",)),
    "D3.11": ("A shape with no blank line after it", ("D07",), ("syntax.shape",)),
    # D4: versions.
    "D4.1": ("A version before 1.4.0 or from 1.6.0 (both interpreters)", ("D03",), ()),
    "D4.2": (
        "The rows of a 1.4 file, and the RF center that it does not have",
        ("D01a", "D01b", "D01c", "D38"),
        (),
    ),
    "D4.3": ("Time ID -1 in a 1.4 file", ("D22",), ("ref.unresolved",)),
    "D4.4": (
        "A 1.4 arbitrary gradient on the default raster: no ends",
        ("D39",),
        ("layer1.gradient-ends",),
    ),
    "D4.5": ("A 1.4 arbitrary gradient with a time shape", ("D40",), ("layer1.gradient-ends",)),
    "D4.6": (
        "An extension before the revision that introduced it",
        ("D45", "D47", "D49", "D58"),
        (),
    ),
    "D4.7": ("A label flag of 1.4.1 in an older file", ("D50",), ()),
    # D5: the undefined behaviour of the C++ reader (`cpp-siemens`).
    "D5.1": (
        "A block uses a shape that the reader did not read",
        ("D21", "D05", "D07"),
        ("ub.shape-missing",),
    ),
    "D5.2": (
        "A [GRADIENTS] row of shape ID 0 that a block uses",
        ("D21",),
        ("ub.gradient-shape-0",),
    ),
    "D5.3": ("An RF event with time ID -1", ("D22",), ("ub.rf-time-id-minus-1",)),
    "D5.4": ("A cycle in an extension list", ("D23",), ("ub.extension-cycle",)),
    "D5.5": (
        "A shape that decompresses to more samples than it declares",
        ("D29",),
        ("ub.shape-decompression",),
    ),
    "D5.6": ("An event that uses a shape with no sample", ("D33",), ("ub.shape-empty",)),
    "D5.7": ("An RF phase shorter than its magnitude", ("D34",), ("ub.rf-shape-lengths",)),
    "D5.8": ("The RF resampling reads past the samples", ("D36",), ("ub.rf-time-overrun",)),
    "D5.9": (
        "An RF time shape whose last time does not fit an int",
        ("D36",),
        ("ub.rf-time-range",),
    ),
    "D5.10": (
        "An extended trapezoid of one point at a time above 0",
        ("D59",),
        ("ub.gradient-one-point",),
    ),
    "D5.11": (
        "An extended trapezoid time that does not fit a long",
        ("D60",),
        ("ub.gradient-time-range",),
    ),
    # D6: the settings of the scanner (`cpp-siemens`).
    "D6.1": ("An oversampled arbitrary gradient: the reader's sampling mode", ("D43",), ()),
    "D6.2": ("A block that plays a rotation", ("D49",), ()),
    # D7: the reader's values in the model (`cpp-siemens`).
    "D7.1": ("Definitions as text", ("D13",), ()),
    "D7.2": ("The reader's float32 values, as float64", ("D18",), ()),
    "D7.3": ("A block's id: its position in play order", ("D20",), ()),
    "D7.4": ("gradients_at between blocks and after a block's end", ("D25", "D42"), ()),
    "D7.5": ("The center of a 1.4 RF event: NaN", ("D38",), ()),
    "D7.6": ("The ADC phase shape as stored", ("D44",), ()),
}

# The old entries, or the parts of them, that record no decision of the two interpreters: the
# specification states the rule and each interpreter follows its own (spec: the specification;
# cpp-siemens: the C++ reader), or only MATLAB Pulseq or pypulseq differ. Old ID -> what it was.
REMOVED: dict[str, str] = {
    "D04": "a [VERSION] value such as 5.0 (spec:193-198 states integers)",
    "D09": "[DELAYS] from 1.4.0 (spec:114, spec:772; both ignore it)",
    "D11": "a required raster missing or invalid (spec:267-276, slide 11)",
    "D14": "the types of the columns (spec:176, spec:293-455); the C++ reader's misreading of a fraction",
    "D15": "an ADC dwell time with a decimal point (spec:437: a float)",
    "D17": "an RF use letter (spec:356-357)",
    "D18": "values beyond float32 (spec:176), for spec",
    "D19": "IDs of shapes and events not positive or not unique (spec:181-183, spec:403)",
    "D20": "block IDs out of order (spec:185, spec:318), for spec",
    "D21": "a reference that does not resolve (spec:178-186), for spec",
    "D22": "time ID -1 of an RF event (spec:349, spec:395), for spec",
    "D23": "a cycle in an extension list (spec:478), for spec",
    "D24": "a file with no block (spec:318)",
    "D25": "an event longer than its block (spec:318)",
    "D26": "times off a raster (spec:275, spec:290, slides 5, 9, 10), except the vertex (D1.3)",
    "D27": "a gradient non-zero at an end (spec:420, slide 6)",
    "D28": "an arbitrary gradient off 10 us (spec section 2.5, slide 11)",
    "D29": "a shape whose length is not num_samples (spec:626), for spec",
    "D30": "an amplitude shape outside [-1, 1] (spec:624)",
    "D43": "an oversampled gradient (spec:420, slides 4, 8), for spec",
    "D47": "an unknown required extension (spec:460), except the revision (D4.6)",
    "D48": "two ROTATIONS or RF_SHIMS objects in a block (spec:567, spec:584)",
    "D51": "equal events with different IDs (only pypulseq merges them)",
    "D52": "no dead time or default raster of a scanner (only MATLAB and pypulseq add them)",
    "D53": "the signature hash (spec:223)",
    "D54": "[SIGNATURE] without Type or Hash (spec:223-232)",
}

OLD_ID = re.compile(r"\bD(?:0[1-9]|[1-5][0-9]|60)[a-c]?\b")


def new_ids(old: str) -> list[str]:
    """The new IDs that an old ID's content went to."""
    return [new for new, (_, olds, _) in ENTRIES.items() if old in olds]


def table() -> str:
    """The table of the record's appendix: each old ID, its new IDs, and what was removed."""
    olds = sorted(
        {old for _, olds, _ in ENTRIES.values() for old in olds} | set(REMOVED),
        key=lambda old: (int(old[1:3]), old[3:]),
    )
    lines = ["| Old ID | New IDs | Removed (no decision of the interpreters) |", "|---|---|---|"]
    for old in olds:
        lines.append(f"| {old} | {', '.join(new_ids(old)) or '—'} | {REMOVED.get(old, '')} |")
    return "\n".join(lines)


def apply(paths: list[Path]) -> int:
    """Rewrite each old ID with one new ID; list the others. Returns the number left to resolve."""
    left = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")

        def replace(match: re.Match[str]) -> str:
            ids = new_ids(match.group(0))
            return ids[0] if len(ids) == 1 and match.group(0) not in REMOVED else match.group(0)

        new = OLD_ID.sub(replace, text)
        if new != text:
            path.write_text(new, encoding="utf-8")
        for number, line in enumerate(new.splitlines(), 1):
            for match in OLD_ID.finditer(line):
                old = match.group(0)
                left += 1
                where = ", ".join(new_ids(old)) or "—"
                removed = f"; removed: {REMOVED[old]}" if old in REMOVED else ""
                print(f"{path}:{number}: {old} -> {where}{removed}")
    return left


def main() -> None:
    if sys.argv[1:2] == ["table"]:
        print(table())
    elif sys.argv[1:2] == ["apply"] and sys.argv[2:]:
        left = apply([Path(arg) for arg in sys.argv[2:]])
        print(f"{left} old IDs left to resolve", file=sys.stderr)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
