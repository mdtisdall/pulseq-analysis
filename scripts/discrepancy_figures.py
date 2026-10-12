"""The figures of `docs/discrepancies.md`, as SVG files in `docs/figures/discrepancy-*.svg`.

Each figure draws what the readers give for a small Pulseq file that this script writes: MATLAB
Pulseq (the JSON of `pulseq-matlab-oracle`, `tests/matlab_oracle`), the C++ reader of the
scanner (`pulseq-cpp-oracle --dump` and `--sample`, `tests/cpp_oracle`) and the package
(`reader.read_seqfile` and `events`). The values are the outputs of the readers, not a copy of
their rules. Run it in the devShell, where both oracles are on the PATH:

    nix develop --command uv run python scripts/discrepancy_figures.py

`--cpp` and `--matlab` give the path of an oracle that is not on the PATH. The SVG files are
reproducible: the same outputs give the same bytes. The style is that of
`scripts/doc_figures.py`.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt
import numpy as np

from pulseq_analysis.seqfile.reader import SeqFileError, read_seqfile
from pulseq_analysis.synth.events import decode_gradients, decode_rf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "figures"
# With `DOC_FIGURES_PREVIEW=<dir>`, a PNG of each figure goes to <dir> too, to look at.
PREVIEW = Path(os.environ["DOC_FIGURES_PREVIEW"]) if os.environ.get("DOC_FIGURES_PREVIEW") else None
OURS = "#1f5fa8"
MATLAB = "#d9480f"
CPP = "#2b8a3e"
BLOCK = "#868e96"

plt.rcParams.update(
    {
        "svg.hashsalt": "pulseq-analysis",
        "svg.fonttype": "none",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

HEADER = """\
[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

"""


def shape(shape_id: int, num_samples: int, stored) -> str:
    values = "\n".join(f"{v:.12g}" for v in stored)
    return f"shape_id {shape_id}\nnum_samples {num_samples}\n{values}\n\n"


# The magnitude of the RF pulses: a Hann window of 20 samples (no sample is 0).
HANN = 0.5 - 0.5 * np.cos(2 * np.pi * (np.arange(20) + 0.5) / 20)


def rf_file(time_shape: str, block_ticks: int, magnitude: np.ndarray = HANN) -> str:
    """One block with one RF event of amplitude 1000 Hz and delay 0, the magnitude
    `magnitude` (shape 1), the phase 0 (shape 2) and the time shape `time_shape` (shape 3)."""
    n = magnitude.size
    return (
        HEADER
        + f"[BLOCKS]\n1 {block_ticks} 1 0 0 0 0 0\n\n"
        + "[RF]\n1 1000 1 2 3 0 0 0 0 0 0 e\n\n[SHAPES]\n"
        + shape(1, n, magnitude)
        + shape(2, n, [0, 0, n - 2])
        + time_shape
    )


# The files of the figures, by name.
FILES = {
    # A regular time shape (3 or 4 stored values) of step 2 RF rasters whose times are the
    # centres of its cells: 1, 3, ..., 39 us. The block lasts 40 us.
    "rf_regular_step_2": rf_file(shape(3, 20, [1, 2, 2, 17]), 4),
    # A regular time shape of step 1 whose first time is 10: 10, 11, ..., 29 us.
    "rf_regular_offset": rf_file(shape(3, 20, [10, 1, 1, 17]), 3),
    # A time shape that is not regular (stored uncompressed): 1, 2, 4, 7, 10 us.
    "rf_resampled": rf_file(
        shape(3, 5, [1, 2, 4, 7, 10]), 1, magnitude=np.array([0.2, 0.6, 1.0, 0.6, 0.2])
    ),
    # An arbitrary gradient on the default raster (time ID 0): a half sine of 10 samples at the
    # centres of the raster cells, with first and last 0. The samples are those of the 1.4.1 file
    # `tests/seqfiles/oracle/koma_v1.4_gr-uniformly-shaped.seq`.
    "gradient_half_sine": (
        HEADER
        + "[BLOCKS]\n1 10 0 1 0 0 0 0\n\n[GRADIENTS]\n1 42576 0 0 1 0 0\n\n[SHAPES]\n"
        + shape(1, 10, np.round(np.sin(np.pi * np.arange(10) / 9), 12))
    ),
}


def run_matlab(oracle: str, paths: list[Path], out: Path) -> dict[str, dict]:
    subprocess.run([oracle, str(out), *map(str, paths)], capture_output=True, check=True)
    return {p.stem: json.loads((out / f"{p.stem}.json").read_text()) for p in paths}


def cpp_dump(oracle: str, path: Path) -> dict:
    result = subprocess.run(
        [oracle, "--dump", str(path)], capture_output=True, text=True, check=True, timeout=10
    )
    return json.loads(result.stdout)


def cpp_sample(oracle: str, path: Path, block: int, t_us: np.ndarray) -> np.ndarray:
    lines = "".join(f"{block} {t!r}\n" for t in t_us.tolist())
    result = subprocess.run(
        [oracle, "--sample", str(path)],
        input=lines,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return np.array(result.stdout.split(), dtype=np.float64).reshape(-1, 3)


def package(path: Path):
    """The model of `path`, or the rule IDs of the violations."""
    try:
        return read_seqfile(path)
    except SeqFileError as error:
        return sorted({v.rule for v in error.violations})


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, format="svg", metadata={"Date": None}, bbox_inches="tight")
    if PREVIEW:
        fig.savefig(PREVIEW / f"{name}.png", format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote docs/figures/{name}")


def matlab_rf(result: dict) -> dict:
    return next(b["rf"] for b in result["blocks"] if b["rf"])


def cpp_cells(ax, dump: dict, label: str) -> float:
    """The RF magnitude that the C++ reader plays: each sample for one dwell time, from the
    delay. Returns the end of the pulse (us)."""
    rf = dump["blocks"][0]["rf"]
    dwell, delay = rf["dwell_us"], rf["delay_us"]
    mag = np.asarray(rf["magnitude"]) * rf["amplitude"]
    edges = delay + dwell * np.arange(mag.size + 1)
    ax.stairs(mag, edges, color=CPP, lw=1.6, label=label)
    return delay + rf["shape_dur_us"]


def rf_panel(ax, name: str, path: Path, matlab: dict, cpp: str, title: str) -> None:
    rf = matlab_rf(matlab[name])
    t_matlab = (np.asarray(rf["t"]) + rf["delay"]) * 1e6
    end_matlab = (rf["delay"] + rf["shape_dur"]) * 1e6
    end_cpp = cpp_cells(ax, cpp_dump(cpp, path), "C++ reader: plays each sample for one dwell")
    ax.plot(t_matlab, rf["signal_abs"], "o", ms=3.5, color=MATLAB, label="MATLAB Pulseq: rf.t")
    model = package(path)
    if isinstance(model, list):
        verdict = "pulseq-analysis rejects the file: " + ", ".join(model)
    else:
        event = decode_rf(model)[1]
        t = (event.delay + event.t) * 1e6
        ax.plot(t, event.magnitude, "x", ms=4, color=OURS, label="pulseq-analysis: RfEvent.t")
        verdict = f"pulseq-analysis: shape_dur {event.shape_dur * 1e6:g} µs"
    top = 1150
    if abs(end_matlab - end_cpp) < 1e-9:
        ends = [(end_cpp, CPP, f"MATLAB and C++ end\n{end_cpp:g} µs", "center")]
    else:
        # The label of the earlier end goes to its left, the other to its right.
        left, right = ("right", "left") if end_matlab < end_cpp else ("left", "right")
        ends = [
            (end_matlab, MATLAB, f"MATLAB end\n{end_matlab:g} µs ", left),
            (end_cpp, CPP, f" C++ end\n {end_cpp:g} µs", right),
        ]
    for x, color, text, align in ends:
        ax.axvline(x, color=color, lw=0.8, ls="--")
        ax.text(x, top, text, color=color, ha=align, va="bottom", fontsize=8)
    ax.text(0.0, -0.32, verdict, transform=ax.transAxes, fontsize=8, color=OURS)
    ax.set_ylim(0, 1100)
    ax.set_title(title, loc="left", fontsize=9.5, fontweight="bold", pad=26)
    ax.set_ylabel("|B1| (Hz)")


def rf_time_shapes(paths: dict[str, Path], matlab: dict, cpp: str) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(7.5, 9.6))
    rf_panel(
        axes[0],
        "rf_regular_step_2",
        paths["rf_regular_step_2"],
        matlab,
        cpp,
        "Regular time shape, step 2 µs, times 1, 3, …, 39 µs (stored 1 2 2 17)",
    )
    rf_panel(
        axes[1],
        "rf_regular_offset",
        paths["rf_regular_offset"],
        matlab,
        cpp,
        "Regular time shape, step 1 µs, times 10, 11, …, 29 µs (stored 10 1 1 17)",
    )
    rf_panel(
        axes[2],
        "rf_resampled",
        paths["rf_resampled"],
        matlab,
        cpp,
        "Other time shape, times 1, 2, 4, 7, 10 µs (stored uncompressed)",
    )
    axes[-1].set_xlabel("time from the start of the block (µs)")
    axes[0].legend(loc="center left", bbox_to_anchor=(0.0, 0.45), frameon=False, fontsize=8)
    fig.tight_layout(h_pad=2.2)
    save(fig, "discrepancy-rf-time-shapes.svg")


def gradient_edges(path: Path, matlab: dict, cpp: str) -> None:
    wave = matlab["gradient_half_sine"]["waveforms"]["gx"]
    event = decode_gradients(package(path))[1]
    t_ours = np.concatenate([[0.0], event.tt, [event.shape_dur]]) * 1e6
    v_ours = np.concatenate([[event.first], event.waveform, [event.last]])
    t_fine = np.linspace(0.0, 100.0, 401)
    v_cpp = cpp_sample(cpp, path, 0, t_fine)[:, 0]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.plot(
        np.asarray(wave["t"]) * 1e6,
        wave["v"],
        "-o",
        ms=3,
        color=MATLAB,
        lw=1.2,
        label="MATLAB Pulseq waveforms_and_times: values restored at the raster edges",
    )
    ax.plot(t_ours, v_ours, color=OURS, lw=1.8, label="pulseq-analysis: lines between the samples")
    ax.plot(t_fine, v_cpp, color=CPP, lw=1.0, ls="--", label="C++ reader gradientsAt")
    ax.plot(event.tt * 1e6, event.waveform, "o", ms=4, color=OURS, mfc="white")
    for e in np.arange(11) * 10.0:
        ax.axvline(e, color=BLOCK, lw=0.4, ls=":", zorder=0)
    ax.set_xlabel("time (µs); dotted: the edges of the gradient raster")
    ax.set_ylabel("gx (Hz/m)")
    ax.set_title(
        "Arbitrary gradient on the default raster (time ID 0): the samples are at the cell centres",
        loc="left",
        fontsize=9.5,
        fontweight="bold",
    )
    ax.legend(loc="lower center", frameon=False, fontsize=8)
    ax.set_ylim(-5000, 50000)
    fig.tight_layout()
    save(fig, "discrepancy-arbitrary-gradient-edges.svg")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cpp", default=shutil.which("pulseq-cpp-oracle"))
    parser.add_argument("--matlab", default=shutil.which("pulseq-matlab-oracle"))
    args = parser.parse_args()
    if args.cpp is None or args.matlab is None:
        parser.error("both oracles are needed: run it in the devShell, or give --cpp and --matlab")
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for name, text in FILES.items():
            paths[name] = Path(tmp) / f"{name}.seq"
            paths[name].write_text(text)
        out = Path(tmp) / "matlab"
        out.mkdir()
        matlab = run_matlab(args.matlab, list(paths.values()), out)
        rf_time_shapes(paths, matlab, args.cpp)
        gradient_edges(paths["gradient_half_sine"], matlab, args.cpp)


if __name__ == "__main__":
    main()
