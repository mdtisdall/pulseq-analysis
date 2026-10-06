"""The large synthetic sequences of the sequence index tests.

Copied from pulseq-reports `scripts/diagram_scale.py`, lines 89 to 230 at commit 475a1eb.
"""

import copy
import math
import sys

import numpy as np
import pypulseq as pp
from synthetic import SYSTEM, WIDTH, block_pulse, readout, signed

# ---- The TR ----

TR_BLOCKS = 5  # rf, phase-encode, readout (gx + adc), spoiler, delay
PE_STEPS = 256  # the repeating case's phase-encode table
GOLDEN_ANGLE = 2.399963229728653  # rad; the worst case's RF phase step
RF_DURATION = 2e-3  # s; the worst case's shaped pulse
TR_MARGIN_S = 2e-3  # padding added to the busiest part of the TR, to fill it out


def _pe_family(amplitudes: np.ndarray) -> list:
    """Trapezoids on y with the ramps and the flat time of one area-based trapezoid,
    each with one of `amplitudes` (Hz/m) instead of that trapezoid's own amplitude: all
    have the same duration, and each amplitude is a distinct gradient event."""
    base = pp.make_trapezoid(channel="y", area=1 / WIDTH, system=SYSTEM)
    return [
        pp.make_trapezoid(
            channel="y",
            amplitude=float(amp),
            rise_time=base.rise_time,
            flat_time=base.flat_time,
            fall_time=base.fall_time,
            system=SYSTEM,
        )
        for amp in amplitudes
    ]


def _pe_max_amplitude() -> float:
    return float(pp.make_trapezoid(channel="y", area=1 / WIDTH, system=SYSTEM).amplitude)


def _progress(case: str, done: int, total: int, step: int) -> None:
    if done == total or done % step == 0:
        print(f"  {case}: {done}/{total} TRs ({100 * done / total:.0f}%)", file=sys.stderr)


def build_repeating(n_trs: int) -> pp.Sequence:
    """A GRE-like TR of 5 blocks, repeated `n_trs` times, with a phase-encode table of
    `PE_STEPS` amplitudes (TR `i` uses entry `i mod PE_STEPS`). The RF, readout, spoiler
    and delay events are each made once and reused, so their libraries stay at 1 entry;
    the phase-encode library stays at `min(PE_STEPS, n_trs)` entries."""
    seq = pp.Sequence(SYSTEM)
    rf = block_pulse("excitation", math.radians(20))
    gx, adc, _ = readout()
    spoiler = pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM)
    pe_max = _pe_max_amplitude()
    pe_events = _pe_family(np.linspace(-pe_max, pe_max, min(PE_STEPS, n_trs)))
    used = (
        pp.calc_duration(rf)
        + pp.calc_duration(pe_events[0])
        + pp.calc_duration(gx, adc)
        + pp.calc_duration(spoiler)
    )
    delay = pp.make_delay(TR_MARGIN_S)
    step = max(1, n_trs // 10)
    for i in range(n_trs):
        seq.add_block(rf)
        seq.add_block(pe_events[i % len(pe_events)])
        seq.add_block(gx, adc)
        seq.add_block(spoiler)
        seq.add_block(delay)
        _progress("repeating", i + 1, n_trs, step)
    seq.set_definition("TR", used + TR_MARGIN_S)
    return signed(seq)


def build_worst(n_trs: int) -> pp.Sequence:
    """The same TR as `build_repeating`, but with a shaped RF pulse (a 2 ms sinc, made
    once; each TR uses a shallow copy with a new `phase_offset`, the golden angle times
    the TR index, so no two TRs repeat one) and a phase-encode amplitude that is new in
    every TR (linearly spaced over all `n_trs` TRs, so the RF and gradient libraries
    grow with the number of TRs). The readout, spoiler and delay are made once and
    reused, as in `build_repeating`."""
    seq = pp.Sequence(SYSTEM)
    rf_base = pp.make_sinc_pulse(
        flip_angle=math.radians(20),
        duration=RF_DURATION,
        delay=SYSTEM.rf_dead_time,
        system=SYSTEM,
        use="excitation",
    )
    gx, adc, _ = readout()
    spoiler = pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM)
    pe_max = _pe_max_amplitude()
    pe_amplitudes = np.linspace(-pe_max, pe_max, n_trs)
    pe_events = _pe_family(pe_amplitudes)
    used = (
        pp.calc_duration(rf_base)
        + pp.calc_duration(pe_events[0])
        + pp.calc_duration(gx, adc)
        + pp.calc_duration(spoiler)
    )
    delay = pp.make_delay(TR_MARGIN_S)
    step = max(1, n_trs // 10)
    for i in range(n_trs):
        rf = copy.copy(rf_base)
        rf.phase_offset = (i * GOLDEN_ANGLE) % (2 * math.pi)
        seq.add_block(rf)
        seq.add_block(pe_events[i])
        seq.add_block(gx, adc)
        seq.add_block(spoiler)
        seq.add_block(delay)
        _progress("worst", i + 1, n_trs, step)
    seq.set_definition("TR", used + TR_MARGIN_S)
    return signed(seq)
