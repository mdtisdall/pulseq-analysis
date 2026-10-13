"""The fuzzing of the checks of undefined behaviour (section 9 of docs/plans/parser-redesign.md
in pulseq-analysis): files generated from the grammar of .seq, each read by the package
(fuzz_worker.py, in a process of its own) and by the sanitized C++ oracle
(`pulseq-cpp-oracle-sanitized`, exit status 3 for undefined behaviour).

The checks are safety-critical: in the process, a case that they miss ends the process or
corrupts it silently. A file fails the fuzzing when:

- the oracle finds undefined behaviour, does not end, or crashes, and the package decodes the
  file anyway (it does not raise `UndefinedBehaviour` or `NotSupported`);
- the package's process dies or does not end;
- the package raises `UndefinedBehaviour` for a file that the oracle reads (a false alarm: the
  package would reject a file that the C++ reader reads);
- the two give other verdicts, or other values of `gradientsAt` at the same times.

Each file is generated from (seed, index) alone, so a failure is reproduced by its two numbers
(scripts/fuzz.py --seed S --start INDEX --count 1). The same two numbers give the file's sampling
mode of oversampled gradients (`oversampling_mode`), which both readers get. A file is a random valid file, then up to
three mutations: the shapes of section 5.3 of the plan (each case of undefined behaviour and its
neighbours), values at the edges of their types, and changes to the text and the sections.

Sizes: README.md, "Fuzzing".
"""

from __future__ import annotations

import itertools
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WORKER = HERE / "fuzz_worker.py"

# The most samples that any shape, RF resampling or RF shim of a generated file can make the
# reader allocate, when the checks let the file through. Larger ones are not undefined behaviour,
# but they make both the reader and its sanitized build allocate gigabytes. Values that the
# checks reject (above the range of an int) are generated.
CAP = 20_000

# The reader's sampling modes of an oversampled arbitrary gradient (pulseq_cpp_siemens.OVERSAMPLING;
# the oracle's --oversampling): the fuzzing gives each file one.
OVERSAMPLING = ("center", "edge", "preserve")

# The sanitized oracle aborts an allocation above this size (ASan's max_allocation_size_mb): the
# loop of D5.4 (a cycle in an extension list) then ends in about 0.5 s instead of growing until the
# timeout. Its report is "allocation-size-too-big", which the fuzzing reads as "memory".
ORACLE_MAX_ALLOCATION_MB = 256
# A generated file reads in well under a second in either reader. A cycle of extensions that
# allocate nothing (triggers, rotations) loops without growing, and only the timeout ends it.
ORACLE_TIMEOUT = 4
WORKER_TIMEOUT = 10
# The exit status of the sanitized oracle for undefined behaviour (tests/cpp_oracle/README.md).
UNDEFINED_BEHAVIOUR = 3

# Values at the edges of the types that the reader reads: int, long, float and double, and text
# that sscanf and strtod read in part or not at all. None of them is a size between CAP and the
# end of the range of an int, which would allocate (see CAP).
EDGE_NUMBERS = [
    "0", "-0", "1", "-1", "2", "-2", "0.5", "-0.5", "1e-7", "0.99999994", "1.0000001",
    "2147483647", "-2147483648", "2147483648", "-2147483649", "4294967296", "4294967297",
    "9223372036854775807", "-9223372036854775808", "9223372036854775808", "1e19", "-1e19",
    "3.4028235e38", "3.5e38", "-3.5e38", "1e308", "1.8e308", "-1e308", "4.9e-324", "1e-46",
    "nan", "-nan", "inf", "-inf", "NaN", "Infinity", "0x10", "+5", "1e", "e5", ".", "-", "",
    "1,5", "1.5.5", "07", "1_000", "x",
]  # fmt: skip
# Edge values of a count of a run in a compressed shape (cpp:2217-2229).
EDGE_COUNTS = [
    "-3", "-2", "-1", "-0.5", "0", "0.5", "1e-7", "1.0000001", "0.99999994", "2147483520",
    "2147483647", "2147483648", "-2147483648", "-2147483904", "-2147483649", "1e30", "-1e30",
    "3.5e38", "inf", "-inf", "nan",
]  # fmt: skip
# The last time of an RF time shape that is not an int after int(0.5 + t) (cpp:2031): each is
# undefined behaviour, and none is a size that would allocate.
RF_TIME_OUT_OF_RANGE = [
    "2147483648", "2147483647.5", "4294967296", "1e10", "1e30", "3.4e38", "inf", "nan",
    "-2147483904", "-2147483649", "-1e30", "-inf",
]  # fmt: skip
# Times of an extended trapezoid that, times the gradient raster (10 us), are not a long.
GRADIENT_TIME_OUT_OF_RANGE = ["1e18", "9.3e17", "-9.3e17", "1e30", "3.4e38", "inf", "nan"]
NUM_SAMPLES_EDGES = ["0", "-1", "-2", "-2147483648", "2147483648", "4294967297", "1", "2", "3"]

SECTIONS = ["VERSION", "DEFINITIONS", "BLOCKS", "RF", "GRADIENTS", "TRAP", "ADC", "EXTENSIONS",
            "SHAPES", "SIGNATURE"]  # fmt: skip


def fmt(value: float) -> str:
    return format(float(value), ".9g")


def compress(samples: list[float]) -> list[str]:
    """Pulseq's compression: the derivative, then each run of equal values as `v v count`."""
    derivative = [samples[0]] + [samples[i] - samples[i - 1] for i in range(1, len(samples))]
    tokens = [fmt(np.float32(d)) for d in derivative]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        j = i
        while j + 1 < len(tokens) and tokens[j + 1] == tokens[i]:
            j += 1
        run = j - i + 1
        if run >= 2:
            out += [tokens[i], tokens[i], str(run - 2)]
        else:
            out.append(tokens[i])
        i = j + 1
    return out


@dataclass
class Shape:
    id: str
    num: str
    values: list[str]
    blank_after: bool = True


@dataclass
class Model:
    """A .seq file as rows of text tokens, before it is written."""

    version: list[tuple[str, str]]
    format: str  # "1.4" or "1.5": the columns of RF, GRADIENTS and ADC
    definitions: list[tuple[str, str]]
    blocks: list[list[str]]
    rf: list[list[str]] = field(default_factory=list)
    grad: list[list[str]] = field(default_factory=list)
    trap: list[list[str]] = field(default_factory=list)
    adc: list[list[str]] = field(default_factory=list)
    ext_list: list[list[str]] = field(default_factory=list)
    ext_specs: list[tuple[str, str, list[list[str]]]] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    order: list[str] = field(default_factory=lambda: list(SECTIONS[:-1]))
    final_newline: bool = True

    def next_shape_id(self) -> int:
        ids = [int(s.id) for s in self.shapes if s.id.lstrip("-").isdigit()]
        return max(ids, default=0) + 1

    def add_shape(self, rng: random.Random, samples: list[float], compressed=None) -> str:
        shape_id = str(self.next_shape_id())
        if compressed is None:
            compressed = rng.random() < 0.6
        values = compress(samples) if compressed else [fmt(np.float32(v)) for v in samples]
        if len(values) == len(samples) and compressed:
            values = [fmt(np.float32(v)) for v in samples]  # stored as written: not compressed
        self.shapes.append(Shape(shape_id, str(len(samples)), values))
        return shape_id

    def shape(self, shape_id: str) -> Shape | None:
        return next((s for s in self.shapes if s.id == shape_id), None)


# ---- A random valid file ----


def random_rf_samples(rng: random.Random, n: int, low=0.0, high=1.0) -> list[float]:
    kind = rng.random()
    if kind < 0.3:
        return [rng.uniform(low, high) for _ in range(n)]
    if kind < 0.6:
        value = rng.uniform(low, high)
        return [value] * n
    return [low + (high - low) * math.sin(math.pi * (i + 0.5) / n) ** 2 for i in range(n)]


def random_model(rng: random.Random) -> Model:
    fmt_version = rng.choice(["1.4", "1.5", "1.5", "1.5"])
    revision = rng.choice(["0", "1", "2"]) if fmt_version == "1.4" else rng.choice(["0", "1"])
    model = Model(
        version=[("major", "1"), ("minor", fmt_version[-1]), ("revision", revision)],
        format=fmt_version,
        definitions=[
            ("AdcRasterTime", "1e-07"),
            ("BlockDurationRaster", "1e-05"),
            ("GradientRasterTime", "1e-05"),
            ("RadiofrequencyRasterTime", "1e-06"),
        ],
        blocks=[],
    )
    if rng.random() < 0.3:
        model.definitions.append(("Name", rng.choice(["fuzz", "a b c", "x" * 40])))
    # RF events
    for rf_id in range(1, rng.randint(0, 3) + 1):
        n = rng.choice([1, 2, 3, 4, 5, 8, 16, 32, 64, 100, 128])
        mag = model.add_shape(rng, random_rf_samples(rng, n))
        phase = model.add_shape(rng, random_rf_samples(rng, n, 0.0, 0.999))
        time = "0"
        kind = rng.random()
        if kind < 0.3:
            # Times at the cell edges (cell centres are D5.8: the mutation rf-time-overrun).
            step = rng.choice([1, 1, 2, 3])
            offset = rng.choice([0, step])
            time = model.add_shape(rng, [float(offset + step * i) for i in range(n)])
        elif kind < 0.45 and n >= 3:
            dwell = rng.choice([1, 2, 5])
            # A regular time shape, as MATLAB writes it: "1 1 n-2" (or with an offset).
            values = (
                ["1", "1", str(n - 2)] if dwell == 1 else ["0", str(dwell), str(dwell), str(n - 3)]
            )
            if dwell != 1 and n < 4:
                values = ["1", "1", str(n - 2)]
            shape_id = str(model.next_shape_id())
            model.shapes.append(Shape(shape_id, str(n), values))
            time = shape_id
        row = [str(rf_id), fmt(rng.uniform(1, 1000)), mag, phase, time]
        if model.format == "1.5":
            row += [fmt(rng.uniform(0, n)), str(rng.choice([0, 10, 100])), "0", "0",
                    fmt(rng.uniform(-100, 100)), fmt(rng.uniform(0, 3)), rng.choice("eriusp")]  # fmt: skip
        else:
            row += [
                str(rng.choice([0, 10, 100])),
                fmt(rng.uniform(-100, 100)),
                fmt(rng.uniform(0, 3)),
            ]
        model.rf.append(row)
    # Gradients: trapezoids, arbitrary, oversampled arbitrary, extended trapezoids
    grad_ids = []
    next_id = 1
    for _ in range(rng.randint(0, 3)):
        model.trap.append([str(next_id), fmt(rng.uniform(-1e6, 1e6)), str(rng.choice([0, 10, 100])),
                           str(rng.choice([0, 10, 200])), str(rng.choice([0, 10, 100])),
                           str(rng.choice([0, 10, 50]))])  # fmt: skip
        grad_ids.append(str(next_id))
        next_id += 1
    for _ in range(rng.randint(0, 4)):
        kind = rng.choice(["arbitrary", "oversampled", "oversampled", "ext_trap"])
        n = rng.choice([1, 2, 3, 4, 5, 9, 10, 31, 50])
        if kind == "oversampled":
            # Any number of samples (MATLAB writes an odd one, and the reader reads either). The
            # reader keeps (n + 1) / 2, (n - 1) / 2 or n of them, by its mode: none in the "edge"
            # mode for 1 and 2, where gradientsAt returns early. So small sizes are the most
            # frequent.
            n = rng.choice([1, 1, 2, 2, 3, 3, 4, 4, 5, 9, 10, 31, 50])
        if kind == "ext_trap":
            n = max(n, 2)  # one point is ub.gradient-one-point: the mutation gradient-one-point
            times = sorted(rng.sample(range(4 * n + 4), n))
            time = model.add_shape(rng, [float(t) for t in times])
        elif kind == "oversampled":
            time = "-1"
        else:
            time = "0"
        wave = model.add_shape(rng, [rng.uniform(-1, 1) for _ in range(n)])
        if model.format == "1.5":
            row = [str(next_id), fmt(rng.uniform(-1e6, 1e6)), "0", "0", wave, time,
                   str(rng.choice([0, 10, 100]))]  # fmt: skip
        else:
            row = [str(next_id), fmt(rng.uniform(-1e6, 1e6)), wave, time, str(rng.choice([0, 10]))]
        model.grad.append(row)
        grad_ids.append(str(next_id))
        next_id += 1
    # ADC events
    for adc_id in range(1, rng.randint(0, 2) + 1):
        n = rng.choice([1, 8, 64])
        row = [str(adc_id), str(n), str(rng.choice([100, 1000, 25000])), str(rng.choice([0, 10]))]
        if model.format == "1.5":
            phase_id = "0"
            if rng.random() < 0.2:
                phase_id = model.add_shape(rng, [rng.uniform(0, 1) for _ in range(n)])
            row += ["0", "0", fmt(rng.uniform(-100, 100)), fmt(rng.uniform(0, 3)), phase_id]
        else:
            row += [fmt(rng.uniform(-100, 100)), fmt(rng.uniform(0, 3))]
        model.adc.append(row)
    # Extensions
    specs = []
    if rng.random() < 0.5:
        label = rng.choice(["LIN", "SLC", "NAV", "REV"])
        value = rng.randint(0, 1) if label in ("NAV", "REV") else rng.randint(0, 5)  # flags: 0, 1
        specs.append(("LABELSET", [["1", str(value), label]]))
    if rng.random() < 0.4:
        specs.append(
            ("LABELINC", [["1", str(rng.randint(-2, 2)), rng.choice(["LIN", "PAR", "AVG"])]])
        )
    if rng.random() < 0.3:
        specs.append(("TRIGGERS", [["1", "1", "2", "0", "10"]]))
    if rng.random() < 0.3 and model.format == "1.5":
        specs.append(("DELAYS", [["1", "0", "-100", "1", "TE"]]))
    if rng.random() < 0.3:
        specs.append(("ROTATIONS", [["1", "0.92388", "0", "0", "0.382683"]]))
    if rng.random() < 0.2 and model.format == "1.5":
        specs.append(("RF_SHIMS", [["1", "2", "1", "0", "1", "1.5708"]]))
    for type_id, (name, rows) in enumerate(specs, start=1):
        model.ext_specs.append((name, str(type_id), rows))
    entries = []
    for entry_id, (type_id) in enumerate(range(1, len(specs) + 1), start=1):
        entries.append([str(entry_id), str(type_id), "1", "0"])
    # Chain some entries into lists.
    for i in range(len(entries) - 1):
        if rng.random() < 0.4:
            entries[i][3] = entries[i + 1][0]
    model.ext_list = entries
    if any(name == "ROTATIONS" for name, _, _ in model.ext_specs) and model.format == "1.5":
        model.definitions.append(("RequiredExtensions", "ROTATIONS"))
    # Blocks
    for block_id in range(1, rng.randint(1, 10) + 1):
        rf = rng.choice(["0"] + [r[0] for r in model.rf]) if model.rf else "0"
        gx, gy, gz = (rng.choice(["0"] + grad_ids) if grad_ids else "0" for _ in range(3))
        adc = rng.choice(["0"] + [a[0] for a in model.adc]) if model.adc else "0"
        ext = rng.choice(["0"] + [e[0] for e in model.ext_list]) if model.ext_list else "0"
        duration = str(rng.choice([1, 10, 30, 50, 100, 500, 2000]))
        model.blocks.append([str(block_id), duration, rf, gx, gy, gz, adc, ext])
    return model


# ---- Mutations ----


def _pick(rng, items):
    return rng.choice(items) if items else None


def _shape_references(model: Model) -> list[tuple[list[str], int, str]]:
    """Each (row, column, kind) of the file that names a shape."""
    refs = []
    for row in model.rf:
        refs += [(row, 2, "rf-mag"), (row, 3, "rf-phase"), (row, 4, "rf-time")]
    for row in model.grad:
        refs += (
            [(row, 4, "grad-wave"), (row, 5, "grad-time")]
            if model.format == "1.5"
            else [
                (row, 2, "grad-wave"),
                (row, 3, "grad-time"),
            ]
        )
    for row in model.adc:
        if model.format == "1.5":
            refs.append((row, 8, "adc-phase"))
    return refs


def m_shape_missing(model, rng):
    ref = _pick(rng, [r for r in _shape_references(model) if r[0][r[1]] not in ("0", "-1")])
    if ref:
        row, column, _ = ref
        row[column] = str(model.next_shape_id() + rng.randint(0, 3))


def m_rf_time_minus_1(model, rng):
    row = _pick(rng, model.rf)
    if row:
        row[4] = "-1"


def m_extension_cycle(model, rng):
    if not model.ext_list:
        return
    chain = rng.sample(model.ext_list, rng.randint(1, len(model.ext_list)))
    for a, b in itertools.pairwise(chain):
        a[3] = b[0]
    chain[-1][3] = chain[rng.randrange(len(chain))][0]
    if not any(block[7] == chain[0][0] for block in model.blocks) and model.blocks:
        rng.choice(model.blocks)[7] = chain[0][0]


def _compressed_shapes(model):
    return [s for s in model.shapes if len(s.values) != _int_or(s.num, -1)]


def _int_or(text, default):
    try:
        return int(text)
    except ValueError:
        return default


def m_decompression_longer(model, rng):
    shape = _pick(rng, [s for s in model.shapes if s.values])
    if not shape:
        return
    n = _int_or(shape.num, 1)
    choice = rng.random()
    if choice < 0.4:
        shape.num = str(max(1, n - rng.randint(1, 3)))  # fewer samples than the values make
    elif choice < 0.7:
        runs = [
            i for i in range(1, len(shape.values) - 1) if shape.values[i] == shape.values[i - 1]
        ]
        if runs:
            i = rng.choice(runs) + 1
            shape.values[i] = str(_int_or(shape.values[i], 0) + rng.randint(1, 4))
        else:
            shape.values += [shape.values[-1], shape.values[-1], str(rng.randint(0, 3))]
    else:
        shape.values += [fmt(rng.uniform(-1, 1)) for _ in range(rng.randint(1, 3))]


def m_count_missing(model, rng):
    shape = _pick(rng, [s for s in model.shapes if s.values])
    if shape:
        shape.values.append(shape.values[-1])
        if rng.random() < 0.3:
            shape.values.append(shape.values[-1])


def m_count_edge(model, rng):
    shape = _pick(rng, [s for s in model.shapes if s.values])
    if not shape:
        return
    runs = [i for i in range(1, len(shape.values) - 1) if shape.values[i] == shape.values[i - 1]]
    if runs and rng.random() < 0.7:
        shape.values[rng.choice(runs) + 1] = rng.choice(EDGE_COUNTS)
    else:
        i = rng.randrange(len(shape.values))
        shape.values[i + 1 : i + 1] = [shape.values[i], rng.choice(EDGE_COUNTS)]


def m_shape_empty(model, rng):
    shape = _pick(rng, model.shapes)
    if shape:
        shape.num = "0"
        if rng.random() < 0.5:
            shape.values = []


def m_num_samples_edge(model, rng):
    shape = _pick(rng, model.shapes)
    if shape:
        shape.num = rng.choice(NUM_SAMPLES_EDGES + [str(len(shape.values)), str(CAP)])


def m_rf_phase_shorter(model, rng):
    row = _pick(rng, model.rf)
    if not row:
        return
    mag = model.shape(row[2])
    n = _int_or(mag.num, 4) if mag else 4
    m = min(CAP, n) - rng.randint(1, 3) if rng.random() < 0.8 else min(CAP, n + 2)
    m = max(1, m)
    row[3] = model.add_shape(rng, [rng.uniform(0, 0.9) for _ in range(m)])


def m_rf_time_overrun(model, rng):
    """Time shapes near the cells of the resampling (D5.8): the cell centres of MATLAB's short
    pulses, times past the last sample, repeated or decreasing times."""
    row = _pick(rng, model.rf)
    if not row:
        return
    mag = model.shape(row[2])
    n = max(1, min(_int_or(mag.num, 4) if mag else 4, 64))
    kind = rng.random()
    if kind < 0.3:
        times = [i + 0.5 for i in range(n)]  # cell centres
    elif kind < 0.5:
        times = [i + rng.choice([0, 0.25, 0.5, 1.0]) for i in range(n)]
        times[-1] += rng.choice([1, 2, 3, 0.5, 0.49, 0.51])
    elif kind < 0.65:
        times = [float(i) for i in range(n)]
        times[rng.randrange(n)] = times[max(0, rng.randrange(n) - 1)]
    elif kind < 0.8:
        times = [float(n - i) for i in range(n)]
    else:
        times = sorted(rng.uniform(0, n + 2) for _ in range(n))
    row[4] = model.add_shape(rng, times, compressed=rng.random() < 0.3)


def m_rf_time_range(model, rng):
    row = _pick(rng, model.rf)
    if not row:
        return
    mag = model.shape(row[2])
    n = max(1, min(_int_or(mag.num, 4) if mag else 4, 64))
    values = [fmt(i) for i in range(n - 1)] + [rng.choice(RF_TIME_OUT_OF_RANGE + ["-1", "-100"])]
    shape_id = str(model.next_shape_id())
    model.shapes.append(Shape(shape_id, str(n), values))
    row[4] = shape_id


def m_gradient_time_range(model, rng):
    rows = [r for r in model.grad if r[5 if model.format == "1.5" else 3] not in ("0", "-1")]
    row = _pick(rng, rows)
    if row:
        column = 5 if model.format == "1.5" else 3
        shape = model.shape(row[column])
        if shape:
            n = min(max(_int_or(shape.num, 2), 1), 64)
            values = [fmt(i) for i in range(n - 1)] + [rng.choice(GRADIENT_TIME_OUT_OF_RANGE)]
            shape.values, shape.num = values, str(len(values))
    elif rng.random() < 0.5:
        _set_definition(
            model, "GradientRasterTime", rng.choice(["1e10", "1e300", "inf", "nan", "1e13"])
        )


def m_regular_time_shape(model, rng):
    row = _pick(rng, model.rf)
    if not row:
        return
    mag = model.shape(row[2])
    n = _int_or(mag.num, 4) if mag else 4
    values = rng.choice([["1", "1", str(n - 2)], ["0", "2", "2", str(n - 3)], ["0.5", "1", "1"],
                         ["1", "1", "0"], ["0", "0", "0", "0"]])  # fmt: skip
    num = rng.choice([str(n), "0", "-1", str(len(values)), str(min(CAP, n + 5)), "1"])
    shape_id = str(model.next_shape_id())
    model.shapes.append(Shape(shape_id, num, values))
    row[4] = shape_id


def m_oversampling(model, rng):
    rows = [r for r in model.grad]
    row = _pick(rng, rows)
    if row:
        column = 5 if model.format == "1.5" else 3
        row[column] = rng.choice(["-1", "-2", "0", "-2147483648"])
        wave = model.shape(row[4 if model.format == "1.5" else 2])
        if wave and rng.random() < 0.5:
            wave.num = rng.choice(["1", "2", "3", "4"])


def _numeric_cells(model):
    cells = []
    for table in (model.blocks, model.rf, model.grad, model.trap, model.adc, model.ext_list):
        for row in table:
            cells += [(row, i) for i in range(len(row))]
    for _, _, rows in model.ext_specs:
        for row in rows:
            cells += [(row, i) for i in range(len(row))]
    return cells


def m_field_edge(model, rng):
    """A value at the edge of its type in any field of an event, a block, or an extension."""
    cell = _pick(rng, _numeric_cells(model))
    if cell:
        row, i = cell
        row[i] = rng.choice(EDGE_NUMBERS)


def m_shape_value_edge(model, rng):
    shape = _pick(rng, model.shapes)
    if shape and shape.values:
        shape.values[rng.randrange(len(shape.values))] = rng.choice(EDGE_COUNTS + ["0", "1e-30"])


def m_rf_shim_edge(model, rng):
    for i, (name, type_id, rows) in enumerate(model.ext_specs):
        if name == "RF_SHIMS":
            row = rows[0]
            row[1] = rng.choice(["0", "-1", "1", "3", str(CAP), "2147483647", "-2147483648"])
            if rng.random() < 0.5:
                del row[2:]
            return


def m_definitions_edge(model, rng):
    key = rng.choice(["AdcRasterTime", "BlockDurationRaster", "GradientRasterTime",
                      "RadiofrequencyRasterTime", "RequiredExtensions", "TotalDuration"])  # fmt: skip
    value = rng.choice(EDGE_NUMBERS + ["1e-05 2e-05", "ROTATIONS", "UNKNOWN"])
    if rng.random() < 0.2:
        model.definitions = [(k, v) for k, v in model.definitions if k != key]
    else:
        _set_definition(model, key, value)


def _set_definition(model, key, value):
    model.definitions = [(k, v) for k, v in model.definitions if k != key] + [(key, value)]


def m_version_edge(model, rng):
    choice = rng.random()
    if choice < 0.4:
        model.version = [(k, v) for k, v in model.version if rng.random() < 0.7]
    elif choice < 0.7:
        key = rng.choice(["major", "minor", "revision"])
        model.version.append((key, rng.choice(["4", "5", "3", "6", "-1", "x", ""])))
    else:
        # The rows of one version's format under the other version's header.
        model.version = [("major", "1"), ("minor", "4" if model.format == "1.5" else "5"),
                         ("revision", "1")]  # fmt: skip


def m_sections(model, rng):
    """D2.1, D2.3, D2.2 of `spec` and their neighbours: [VERSION] or [EXTENSIONS] last, a section
    missing, repeated or in another order, and no blank line at the end of the file."""
    if not model.order:
        return
    choice = rng.random()
    if choice < 0.2 and "VERSION" in model.order:
        model.order.remove("VERSION")
        model.order.append("VERSION")
    elif choice < 0.35 and "EXTENSIONS" in model.order:
        model.order.remove("EXTENSIONS")
        model.order.append("EXTENSIONS")
    elif choice < 0.5:
        model.final_newline = False
    elif choice < 0.65:
        model.order.remove(rng.choice(model.order))
    elif choice < 0.8:
        model.order.insert(rng.randrange(len(model.order) + 1), rng.choice(model.order))
    else:
        rng.shuffle(model.order)


def m_no_blank_after_shape(model, rng):
    shape = _pick(rng, model.shapes)
    if shape:
        shape.blank_after = False


def m_shape_id_edge(model, rng):
    shape = _pick(rng, model.shapes)
    if shape:
        other = _pick(rng, model.shapes)
        shape.id = rng.choice(["0", "-1", "2147483647", "x", other.id if other else "1"])


def m_ids(model, rng):
    """Repeated or odd IDs of events and blocks."""
    table = _pick(
        rng, [t for t in (model.rf, model.grad, model.trap, model.adc, model.blocks) if t]
    )
    if table:
        row = rng.choice(table)
        row[0] = rng.choice(["0", "-1", table[0][0], "2147483647"])


def m_gradient_shape_0(model, rng):
    """A [GRADIENTS] row of shape 0: a trapezoid whose ramp and flat times load never sets."""
    row = _pick(rng, model.grad)
    if row:
        row[4 if model.format == "1.5" else 2] = "0"


def m_gradient_one_point(model, rng):
    """An extended trapezoid of one point: gradientsAt reads past its times."""
    row = _pick(rng, model.grad)
    if row:
        time = rng.choice(["0", "1", "2", "4", "10", "-1"])
        delay = rng.choice(["0", "10", "100", "490"])
        column = 5 if model.format == "1.5" else 3
        row[column] = model.add_shape(rng, [float(time)], compressed=False)
        row[column - 1] = model.add_shape(rng, [rng.uniform(-1, 1)], compressed=False)
        row[-1] = delay


MUTATIONS = {
    "shape-missing": m_shape_missing,
    "rf-time-minus-1": m_rf_time_minus_1,
    "extension-cycle": m_extension_cycle,
    "decompression-longer": m_decompression_longer,
    "count-missing": m_count_missing,
    "count-edge": m_count_edge,
    "shape-empty": m_shape_empty,
    "num-samples-edge": m_num_samples_edge,
    "rf-phase-shorter": m_rf_phase_shorter,
    "rf-time-overrun": m_rf_time_overrun,
    "rf-time-range": m_rf_time_range,
    "gradient-time-range": m_gradient_time_range,
    "regular-time-shape": m_regular_time_shape,
    "oversampling": m_oversampling,
    "field-edge": m_field_edge,
    "shape-value-edge": m_shape_value_edge,
    "rf-shim-edge": m_rf_shim_edge,
    "definitions-edge": m_definitions_edge,
    "version-edge": m_version_edge,
    "sections": m_sections,
    "no-blank-after-shape": m_no_blank_after_shape,
    "shape-id-edge": m_shape_id_edge,
    "ids": m_ids,
    "gradient-shape-0": m_gradient_shape_0,
    "gradient-one-point": m_gradient_one_point,
}


# ---- Writing the file ----


def render(model: Model) -> str:
    def table(rows):
        return "".join(" ".join(row) + "\n" for row in rows)

    parts = {
        "VERSION": "".join(f"{k} {v}\n" for k, v in model.version),
        "DEFINITIONS": "".join(f"{k} {v}\n" for k, v in model.definitions),
        "BLOCKS": table(model.blocks),
        "RF": table(model.rf),
        "GRADIENTS": table(model.grad),
        "TRAP": table(model.trap),
        "ADC": table(model.adc),
    }
    extensions = table(model.ext_list)
    for name, type_id, rows in model.ext_specs:
        extensions += f"\nextension {name} {type_id}\n" + table(rows)
    parts["EXTENSIONS"] = extensions
    shapes = ""
    for shape in model.shapes:
        shapes += f"\nshape_id {shape.id}\nnum_samples {shape.num}\n"
        shapes += "".join(v + "\n" for v in shape.values)
        if not shape.blank_after:
            shapes = shapes.rstrip("\n") + "\n"
    parts["SHAPES"] = shapes.lstrip("\n") if shapes else ""
    text = "# Pulseq sequence file\n# Generated by the fuzzing of pulseq-cpp-siemens\n\n"
    for name in model.order:
        # An empty [SHAPES] is written, so that [EXTENSIONS] is not the last section (D2.3 in
        # `spec`).
        if name in ("RF", "GRADIENTS", "TRAP", "ADC", "EXTENSIONS") and not parts[name]:
            continue
        text += f"[{name}]\n{parts.get(name, '')}\n"
    if not model.final_newline:
        text = text.rstrip("\n")
    return text


def mutate_text(text: bytes, rng: random.Random) -> tuple[bytes, str]:
    """A change to the text that the grammar does not make: a line dropped, repeated or swapped,
    a byte that the reader reads as the end of the file (0xFF with a signed char) or as a line
    end, a tab, or the file cut short."""
    lines = text.split(b"\n")
    choice = rng.random()
    if choice < 0.2 and len(lines) > 1:
        del lines[rng.randrange(len(lines))]
        return b"\n".join(lines), "text-drop-line"
    if choice < 0.35:
        i = rng.randrange(len(lines))
        lines.insert(i, lines[i])
        return b"\n".join(lines), "text-repeat-line"
    if choice < 0.45 and len(lines) > 2:
        i, j = rng.sample(range(len(lines)), 2)
        lines[i], lines[j] = lines[j], lines[i]
        return b"\n".join(lines), "text-swap-lines"
    if choice < 0.75:
        i = rng.randrange(len(text) + 1)
        byte = rng.choice([b"\xff", b"\x00", b"\r", b"\t", b"\r\n", b" ", b"#", b"[", b"]"])
        return text[:i] + byte + text[i:], "text-byte"
    if choice < 0.85:
        return text.replace(b"\n", b"\r\n"), "text-crlf"
    return text[: rng.randrange(len(text) + 1)], "text-cut"


def oversampling_mode(seed: int, index: int) -> str:
    """The sampling mode of oversampled gradients that both readers get for the file of (seed,
    index): a function of the two numbers, from a generator of its own, so that the file does not
    change with it."""
    return random.Random(f"pulseq-cpp-siemens fuzz oversampling {seed} {index}").choice(
        OVERSAMPLING
    )


def generate(seed: int, index: int) -> tuple[bytes, list[str]]:
    """The file of (seed, index), and the names of its mutations."""
    rng = random.Random(f"pulseq-cpp-siemens fuzz {seed} {index}")
    model = random_model(rng)
    count = rng.choices([0, 1, 2, 3], weights=[1, 4, 3, 2])[0]
    names = rng.sample(sorted(MUTATIONS), count)
    for name in names:
        MUTATIONS[name](model, rng)  # each mutation leaves the model as it is where it cannot apply
    data = render(model).encode("latin-1")
    if rng.random() < 0.12:
        data, name = mutate_text(data, rng)
        names.append(name)
    return data, names


# ---- Running the two readers ----


def _sections(text: str) -> dict[str, list[str]]:
    """The lines of each section, the last one of each name, as the reader's index finds it."""
    sections: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("[") and "]" in line:
            name = line[1 : line.index("]")]
            sections[name] = []
        elif name is not None:
            sections[name].append(line)
    return sections


_SCAN = {
    "d": re.compile(r"\s*([+-]?\d+)"),
    "f": re.compile(
        r"\s*([+-]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|nan|inf(?:inity)?))", re.IGNORECASE
    ),
}


def _scan(line: str, formats: str) -> list[str] | None:
    """The fields that sscanf reads from `line` with the conversions `formats` ("d" for %d, "f"
    for %f), or None when it reads fewer: a reading of the text independent of the reader."""
    fields, position = [], 0
    for conversion in formats:
        match = _SCAN[conversion].match(line, position)
        if not match:
            return None
        fields.append(match.group(1))
        position = match.end()
    return fields


def known_cases(data: bytes) -> list[str]:
    """The names of the cases of undefined behaviour that the fuzzing found after the checks of
    section 5.3 were written (ub.gradient-shape-0, ub.gradient-one-point), from the text of the
    file alone. They confirm a rejection where no sanitizer can, and sort the failures."""
    sections = _sections(data.decode("latin-1"))
    # The reader's version: the last value of each field, as sscanf's %d reads it, combined.
    parts = {"major": 0, "minor": 0, "revision": 0}
    for line in sections.get("VERSION", []):
        for key in parts:
            match = re.match(rf"{key}\s*([+-]?\d+)", line)
            if match:
                parts[key] = int(match.group(1))
    is_15 = parts["major"] * 1_000_000 + parts["minor"] * 1_000 + parts["revision"] >= 1_005_000
    traps = {words[0] for line in sections.get("TRAP", []) if (words := _scan(line, "dfdddd"))}
    num_samples, shape_id = {}, None
    for line in sections.get("SHAPES", []):
        words = line.split()
        if len(words) == 2 and words[0] == "shape_id":
            shape_id = words[1]
        elif len(words) == 2 and words[0] == "num_samples" and shape_id is not None:
            num_samples[shape_id] = words[1]
    found = set()
    for line in sections.get("GRADIENTS", []):
        words = _scan(line, "dfffddd" if is_15 else "dfddd")
        if words is None:
            continue
        wave, time = (words[4], words[5]) if is_15 else (words[2], words[3])
        if int(wave) == 0 and words[0] not in traps:
            found.add("gradients-row-with-shape-0")
        if int(time) > 0 and num_samples.get(str(int(time))) == "1":
            found.add("extended-trapezoid-of-one-point")
    return sorted(found)


@dataclass
class Result:
    index: int
    mutations: list[str]
    oracle: str
    package: str
    code: str = ""
    failure: str = ""
    detail: str = ""
    known: str = ""  # known_cases of a failure
    name: str = ""  # the file's name
    oversampling: str = "center"  # the sampling mode of oversampled gradients


def oracle_env() -> dict:
    env = dict(os.environ)
    env["ASAN_OPTIONS"] = ":".join(
        filter(
            None,
            [env.get("ASAN_OPTIONS", ""), f"max_allocation_size_mb={ORACLE_MAX_ALLOCATION_MB}"],
        )
    )
    return env


def run_oracle(
    oracle: str, path: Path, stdin: str | None = None, oversampling: str = "center"
) -> tuple[str, str]:
    """The sanitized oracle's verdict: "accept", "reject", "undefined", "no end" (a timeout),
    "memory" (an allocation above ORACLE_MAX_ALLOCATION_MB: the growth of D5.4, or a size that the
    file gives), "crash", or "usage" (exit 2, a fault of the fuzzing), with its output. With
    `stdin`, its `--sample` mode. `oversampling` is its `--oversampling`."""
    command = [oracle, f"--oversampling={oversampling}"]
    command += ["--sample", str(path)] if stdin is not None else [str(path)]
    try:
        result = subprocess.run(
            command, input=stdin, capture_output=True, text=True, errors="replace",
            timeout=ORACLE_TIMEOUT, check=False, env=oracle_env(),
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "no end", f"no end in {ORACLE_TIMEOUT} s"
    output = result.stdout if result.returncode == 0 else result.stderr[-2000:]
    if result.returncode == UNDEFINED_BEHAVIOUR:
        if "allocation-size-too-big" in result.stderr:
            return "memory", output
        return "undefined", output
    return {0: "accept", 1: "reject", 2: "usage"}.get(result.returncode, "crash"), output


class Worker:
    """One process of fuzz_worker.py. It is started again after it dies or does not end."""

    def __init__(self, python: str):
        self.python = python
        self.process: subprocess.Popen | None = None

    def _start(self):
        self.process = subprocess.Popen(
            [self.python, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )  # fmt: skip

    def verdict(self, path: Path, oversampling: str) -> dict:
        if self.process is None or self.process.poll() is not None:
            self._start()
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(f"{oversampling}\t{path}\n")
        self.process.stdin.flush()
        answer: list[str] = []
        reader = threading.Thread(target=lambda: answer.append(self.process.stdout.readline()))
        reader.start()
        reader.join(WORKER_TIMEOUT)
        if reader.is_alive():
            self.process.kill()
            reader.join()
            self.process = None
            return {"verdict": "no end"}
        if not answer or not answer[0]:
            code = self.process.wait()
            self.process = None
            return {"verdict": "died", "detail": f"exit status {code}"}
        return json.loads(answer[0])

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)


FLAGGED = {"undefined", "no end", "crash"}


def compare(index: int, mutations: list[str], ours: dict, oracle: str, path: Path, out: str,
            oracle_binary: str, oversampling: str = "center") -> Result:  # fmt: skip
    package = ours["verdict"]
    result = Result(index, mutations, oracle, package, ours.get("code", ""))
    result.oversampling = oversampling
    if package in ("died", "no end"):
        result.failure = f"the package's process {'died' if package == 'died' else 'did not end'}"
        result.detail = ours.get("detail", "")
    elif oracle == "usage":
        result.failure = "the oracle was called wrongly (a fault of the fuzzing)"
        result.detail = out
    elif oracle == "memory":
        # Not undefined behaviour in itself: the package must not read the file (D5.4 grows
        # without end; a size that a file gives is also rejected by the reader or the checks).
        if package == "read":
            result.failure = (
                f"the oracle allocates more than {ORACLE_MAX_ALLOCATION_MB} MB at once, and the "
                "package reads the file (a cap of the generator is missing?)"
            )
            result.detail = out
    elif oracle in FLAGGED:
        if package not in ("undefined-behaviour", "not-supported"):
            result.failure = (
                f"the oracle says {oracle!r}, and the checks let the package "
                f"{'decode' if package == 'read' else 'run'} the file ({package})"
            )
            result.detail = out
    elif package == "undefined-behaviour":
        if oracle == "accept" and ours.get("where"):
            # A case that only gradientsAt meets: the oracle's --sample at its block and time.
            block, time_us = ours["where"]
            verdict, sampled = run_oracle(
                oracle_binary, path, f"{block} {time_us!r}\n", oversampling
            )
            if verdict in FLAGGED:
                result.oracle = verdict
            else:
                result.failure = (
                    f"a false alarm: the oracle's --sample at block {block}, {time_us} us says "
                    f"{verdict!r}, the checks say {result.code}"
                )
                result.detail = sampled
        elif oracle == "accept" and result.code == "ub.gradient-shape-0":
            # Indeterminate values, which no sanitizer sees: the text must have such a row.
            if "gradients-row-with-shape-0" in known_cases(path.read_bytes()):
                result.oracle = "indeterminate"
            else:
                result.failure = "a false alarm: the file has no [GRADIENTS] row of shape 0"
        elif oracle == "accept":
            result.failure = (
                f"a false alarm: the oracle reads the file, the checks say {result.code}"
            )
    elif package == "not-supported":
        pass  # the package's scope (Q1): the reader is not run
    elif oracle == "accept" and package != "read":
        result.failure = f"the oracle reads the file, the package says {package}"
    elif oracle == "reject" and package == "read":
        result.failure = "the oracle rejects the file, the package reads it"
    if result.failure or package != "read" or oracle != "accept":
        return result
    # Both read the file: gradientsAt at the same times, in the sanitized build too.
    points = ours["points"]
    if not points:
        return result
    stdin = "".join(f"{b} {t!r}\n" for b, t in points)
    verdict, sampled = run_oracle(oracle_binary, path, stdin, oversampling)
    if verdict != "accept":
        result.failure = f"the oracle's --sample says {verdict!r}, the package samples the file"
        result.detail = sampled
        return result
    theirs = np.array(sampled.split(), dtype=np.float64).reshape(-1, 3)
    mine = np.frombuffer(bytes.fromhex(ours["values"]), dtype=np.float64).reshape(-1, 3)
    same = (theirs == mine) | (np.isnan(theirs) & np.isnan(mine))
    if theirs.shape != mine.shape or not same.all():
        result.failure = "gradientsAt differs from the oracle's --sample"
    return result


@dataclass
class Report:
    results: list[Result]

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if r.failure]

    def table(self) -> Counter:
        return Counter(
            (r.oracle, r.package + (f":{r.code}" if r.code else "")) for r in self.results
        )

    def confirmed_codes(self) -> Counter:
        """The codes of the files that the oracle flags (or, for ub.gradient-shape-0, that have
        such a row) and the checks reject."""
        flagged = FLAGGED | {"memory", "indeterminate"}
        return Counter(r.code for r in self.results if r.oracle in flagged and r.code)

    def confirmed_codes_by_mode(self) -> dict[str, Counter]:
        """`confirmed_codes` for the files of each sampling mode."""
        flagged = FLAGGED | {"memory", "indeterminate"}
        return {
            mode: Counter(
                r.code
                for r in self.results
                if r.oversampling == mode and r.oracle in flagged and r.code
            )
            for mode in OVERSAMPLING
        }

    def modes(self) -> dict[str, tuple[int, int]]:
        """For each sampling mode of oversampled gradients: its number of files and of failures."""
        files = Counter(r.oversampling for r in self.results)
        failed = Counter(r.oversampling for r in self.failures)
        return {mode: (files[mode], failed[mode]) for mode in OVERSAMPLING}

    def summary(self) -> str:
        known = Counter(r.known or "not known" for r in self.failures)
        lines = [f"{len(self.results)} files, {len(self.failures)} failures {dict(known)}"]
        lines += [
            f"  oversampling {mode:8} {files} files, {failed} failures"
            for mode, (files, failed) in self.modes().items()
        ]
        lines += [f"  oracle {o:9} package {p}: {n}" for (o, p), n in sorted(self.table().items())]
        return "\n".join(lines)


def _run(items: list, make, oracle: str, python: str | None, jobs: int | None,
         keep: Path | None) -> Report:  # fmt: skip
    """Both readers on the file of each item (`make(item)` gives its name, bytes, mutations,
    index and sampling mode of oversampled gradients), compared. `keep` is a folder for the files
    that fail (with a .json of each result)."""
    python = python or sys.executable
    jobs = jobs or os.cpu_count() or 2
    local = threading.local()
    workers: list[Worker] = []
    lock = threading.Lock()

    with tempfile.TemporaryDirectory(prefix="pulseq-cpp-siemens-fuzz-") as folder:

        def one(item) -> Result:
            if not hasattr(local, "worker"):
                local.worker = Worker(python)
                with lock:
                    workers.append(local.worker)
            name, data, mutations, index, oversampling = make(item)
            # The mode is in the name of the temporary file: a file may be run in each mode.
            path = Path(folder) / f"{oversampling}_{name}"
            path.write_bytes(data)
            ours = local.worker.verdict(path, oversampling)
            verdict, out = run_oracle(oracle, path, oversampling=oversampling)
            result = compare(index, mutations, ours, verdict, path, out, oracle, oversampling)
            result.name = name
            if result.failure:
                result.known = ", ".join(known_cases(data))
            if result.failure and keep is not None:
                keep.mkdir(parents=True, exist_ok=True)
                shutil.copy(path, keep / path.name)
                (keep / f"{path.stem}.json").write_text(json.dumps(result.__dict__, indent=1))
            path.unlink()
            return result

        try:
            with ThreadPoolExecutor(jobs) as pool:
                results = list(pool.map(one, items))
        finally:
            for worker in workers:
                worker.close()
    return Report(results)


def run(seed: int, start: int, count: int, oracle: str, python: str | None = None,
        jobs: int | None = None, keep: Path | None = None) -> Report:  # fmt: skip
    """Generate the files start..start+count-1 of `seed`, run both readers on each, and compare.
    Each file gets the sampling mode of `oversampling_mode`. `keep` is a folder for the files
    that fail (with a .json of each result)."""

    def make(index: int):
        data, mutations = generate(seed, index)
        return (f"fuzz_{seed}_{index}.seq", data, mutations, index,
                oversampling_mode(seed, index))  # fmt: skip

    return _run(list(range(start, start + count)), make, oracle, python, jobs, keep)


def run_files(paths: list[Path], oracle: str, python: str | None = None,
              jobs: int | None = None, keep: Path | None = None,
              modes: tuple[str, ...] = OVERSAMPLING) -> Report:  # fmt: skip
    """Both readers on each of the files `paths` (the regression corpus) in each of the sampling
    modes `modes`, compared as the generated files are."""
    items = [(position, mode) for position in range(len(paths)) for mode in modes]

    def make(item: tuple[int, str]):
        position, mode = item
        path = paths[position]
        return path.name, path.read_bytes(), [], position, mode

    return _run(items, make, oracle, python, jobs, keep)
