"""The figures of `docs/implementation.md`, as SVG files in `docs/figures/`.

Each figure draws the gradient waveform that the package measures
(`GradientSampler.sample`) for a small sequence, with pypulseq's `Sequence.waveforms()`
on top of it where the two differ. The figures are thus made from the code that they
describe. Run it in the devShell after a change of the waveform or of a figure:

    nix develop --command uv run python scripts/doc_figures.py

The SVG files are reproducible: the same code gives the same bytes. matplotlib comes
with pypulseq.
"""

import math
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt
import numpy as np
import pypulseq as pp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import itertools

from scale_sequences import build_repeating
from synthetic import SYSTEM, signed

from pulseq_analysis.sampling import gradient_sampler

OUT = ROOT / "docs" / "figures"
# With `DOC_FIGURES_PREVIEW=<dir>`, a PNG of each figure goes to <dir> too, to look at.
PREVIEW = Path(os.environ["DOC_FIGURES_PREVIEW"]) if os.environ.get("DOC_FIGURES_PREVIEW") else None
DT = SYSTEM.grad_raster_time  # 10 us
U = 1e4  # Hz/m, the unit of the amplitudes of the small sequences
OURS = "#1f5fa8"
PYPULSEQ = "#d9480f"
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


def extended(times, amplitudes, delay=0.0, channel="x"):
    g = pp.make_extended_trapezoid(channel, times=times, amplitudes=amplitudes, system=SYSTEM)
    g.delay = delay
    return g


def sequence(*blocks):
    seq = pp.Sequence(SYSTEM)
    for events in blocks:
        seq.add_block(*events)
    return signed(seq)


def ours(seq, axis, t):
    return gradient_sampler(seq).sample(axis, t)


def pypulseq_points(seq, axis):
    """The points of pypulseq's `waveforms()` of one axis: the line that it draws."""
    wave = seq.waveforms()[{"gx": 0, "gy": 1, "gz": 2}[axis]]
    return np.asarray(wave[0]), np.asarray(wave[1])


def block_edges(seq):
    durations = [seq.block_durations[b] for b in seq.block_events]
    return np.concatenate([[0.0], np.cumsum(durations)])


def draw_blocks(ax, edges, bottom):
    """The block edges (dotted), and the name of each block at the bottom of the panel."""
    for e in edges:
        ax.axvline(e * 1e6, color=BLOCK, lw=0.6, ls=":", zorder=0)
    for i, (a, b) in enumerate(itertools.pairwise(edges)):
        ax.text((a + b) / 2 * 1e6, bottom, f"block {i + 1}", ha="center", va="bottom", color=BLOCK)


def panel(ax, seq, title, *, axis="gx", notes=(), samples=False, show_pypulseq=True):
    """One waveform of `seq` on `ax`: ours (solid), pypulseq's (dashed), the block edges,
    and `notes`, each `(text, (t_us, value_in_U), (text_t_us, text_value_in_U))`."""
    edges = block_edges(seq)
    end = edges[-1]
    pad = 0.06 * end
    t = np.linspace(-pad, end + pad, 4001)
    t = np.union1d(t, edges)
    ax.plot(t * 1e6, ours(seq, axis, t) / U, color=OURS, lw=1.8, label="pulseq-analysis")
    if show_pypulseq:
        pt, pv = pypulseq_points(seq, axis)
        ax.plot(pt * 1e6, pv / U, color=PYPULSEQ, lw=1.2, ls="--", label="pypulseq waveforms()")
    if samples:
        k = np.arange(math.ceil(end / DT - 1e-9))
        ts = (k + 0.5) * DT
        ax.plot(ts * 1e6, ours(seq, axis, ts) / U, "o", ms=3.5, color=OURS, mfc="white")
    values = ours(seq, axis, t) / U
    bottom = min(0.0, float(values.min())) - 0.75
    ax.set_ylim(bottom, max(1.0, float(values.max())) * 1.35)
    ax.set_xlim(-pad * 1e6, (end + pad) * 1e6)
    draw_blocks(ax, edges, bottom + 0.1)
    for text, xy, xytext in notes:
        ax.annotate(
            text,
            xy=xy,
            xytext=xytext,
            fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "#333333", "lw": 0.7},
        )
    ax.set_title(title, loc="left", fontsize=9.5, fontweight="bold")
    ax.set_ylabel("Hz/m (× 10⁴)")
    ax.axhline(0, color="#adb5bd", lw=0.5, zorder=0)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, format="svg", metadata={"Date": None}, bbox_inches="tight")
    if PREVIEW:
        fig.savefig(PREVIEW / f"{name}.png", format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote docs/figures/{name}")


def typical():
    """One TR of the GRE-like sequence of the scale tests: each event starts and ends at 0."""
    seq = build_repeating(1)
    fig, axes = plt.subplots(3, 1, figsize=(7.5, 4.6), sharex=True)
    edges = block_edges(seq)
    t = np.union1d(np.linspace(0, edges[-1], 6001), edges)
    for ax, axis in zip(axes, ("gx", "gy", "gz"), strict=True):
        v = ours(seq, axis, t) / 1e3
        ax.plot(t * 1e3, v, color=OURS, lw=1.6, label="pulseq-analysis")
        pt, pv = pypulseq_points(seq, axis)
        ax.plot(pt * 1e3, pv / 1e3, color=PYPULSEQ, lw=1.0, ls="--", label="pypulseq waveforms()")
        for e in edges:
            ax.axvline(e * 1e3, color=BLOCK, lw=0.6, ls=":", zorder=0)
        ax.set_ylabel(f"{axis} (kHz/m)")
        ax.axhline(0, color="#adb5bd", lw=0.5, zorder=0)
    names = ("RF", "phase\nencode", "readout\n+ ADC", "spoiler", "delay")
    top = axes[0].get_ylim()[1]
    for name, a, b in zip(names, edges[:-1], edges[1:], strict=True):
        axes[0].text((a + b) / 2 * 1e3, top, name, ha="center", va="bottom", color=BLOCK)
    axes[-1].set_xlabel("time (ms)")
    axes[0].legend(loc="upper right", bbox_to_anchor=(1.0, 0.85), frameon=False)
    fig.suptitle(
        "A typical sequence: each event starts and ends at 0, so the two waveforms are equal",
        x=0.02,
        ha="left",
        fontsize=10,
        fontweight="bold",
    )
    save(fig, "waveform-typical.svg")


def gaps():
    """The four cases of section 1 of `docs/implementation.md`, on a 10 us raster."""
    zero = sequence(
        [extended([0, 20e-6, 40e-6], [0, 2 * U, 3 * U])],
        [extended([0, 20e-6, 40e-6], [1.5 * U, 1.5 * U, 0])],
    )
    short = sequence(
        [extended([0, 20e-6, 30e-6], [0, 2 * U, 3 * U]), pp.make_delay(40e-6)],
        [extended([0, 20e-6, 30e-6], [1.5 * U, 1.5 * U, 0])],
    )
    long = sequence(
        [extended([0, 20e-6, 30e-6], [0, 2 * U, 3 * U])],
        [pp.make_delay(40e-6)],
        [extended([0, 20e-6, 30e-6], [1.5 * U, 1.5 * U, 0])],
    )
    ends = sequence(
        [extended([0, 20e-6, 30e-6], [3 * U, 2 * U, 0])],
        [pp.make_delay(30e-6)],
        [extended([0, 20e-6, 30e-6], [0, 2 * U, 3 * U]), pp.make_delay(50e-6)],
    )
    fig, axes = plt.subplots(4, 1, figsize=(7.5, 9.4))
    panel(
        axes[0],
        zero,
        "Zero gap: a step at the junction (MATLAB Pulseq); pypulseq draws no step",
        notes=[("step: slew |step| / dt,\ncredit to block 2", (40, 2.2), (46, 3.2))],
    )
    panel(
        axes[1],
        short,
        "Short gap (one raster time or less): a straight line across it",
        notes=[("line: credit to block 2", (35, 2.25), (48, 3.3))],
    )
    panel(
        axes[2],
        long,
        "Long gap (more than one raster time): ramps of dt / 2 to 0 and from 0",
        notes=[
            ("ramp to 0: credit to block 1", (32.5, 1.5), (36, 3.0)),
            ("ramp from 0: credit to block 3", (67.5, 0.75), (76, 2.6)),
        ],
    )
    panel(
        axes[3],
        ends,
        "Ends of the axis: a step from 0 at the first point, and a step to 0 at the last",
        notes=[
            ("step from 0: block 1", (0, 1.5), (8, 3.4)),
            ("step to 0: block 3", (90, 1.5), (66, 3.4)),
        ],
    )
    axes[-1].set_xlabel("time (µs)")
    axes[0].legend(loc="upper left", frameon=False)
    fig.tight_layout()
    save(fig, "waveform-gaps.svg")


def samples():
    """The samples of the PNS model at (k + 0.5) dt, across a short and a long gap."""
    short = sequence(
        [extended([0, 20e-6, 30e-6], [0, 2 * U, 3 * U]), pp.make_delay(40e-6)],
        [extended([0, 20e-6, 30e-6], [1.5 * U, 1.5 * U, 0])],
    )
    long = sequence(
        [extended([0, 20e-6, 30e-6], [0, 2 * U, 3 * U])],
        [pp.make_delay(40e-6)],
        [extended([0, 20e-6, 30e-6], [1.5 * U, 1.5 * U, 0])],
    )
    fig, axes = plt.subplots(2, 1, figsize=(7.5, 4.8))
    panel(
        axes[0],
        short,
        "Short gap: the sample in the gap has the value of the line",
        samples=True,
        show_pypulseq=False,
    )
    panel(
        axes[1],
        long,
        "Long gap, on the raster: each ramp ends at a sample time, where it is 0",
        samples=True,
        show_pypulseq=False,
    )
    axes[-1].set_xlabel("time (µs)")
    fig.tight_layout()
    save(fig, "waveform-samples.svg")


if __name__ == "__main__":
    typical()
    gaps()
    samples()
