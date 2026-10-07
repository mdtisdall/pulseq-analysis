"""Small synthetic pypulseq sequences for the tests of pulseq-analysis. This module
imports nothing from the package, so the oracles of `tests/oracles/` can use it."""

import math

import numpy as np
import pypulseq as pp
from pypulseq.event_lib import EventLibrary
from pypulseq.utils.safe_pns_prediction import safe_example_hw

# The gamma of 1H (Hz/T), the default of pypulseq's Opts. The package has no
# gamma: the tests use this value to convert its values to tesla.
GAMMA_1H = 42.576e6

# pypulseq's example SAFE hardware, which is not a real scanner. The package has no
# default hardware: the tests give this pair.
EXAMPLE_HW = (safe_example_hw(), "pypulseq example hardware (not a real scanner)")

SYSTEM = pp.Opts(
    max_grad=28,
    grad_unit="mT/m",
    max_slew=150,
    slew_unit="T/m/s",
    rf_ringdown_time=20e-6,
    rf_dead_time=100e-6,
    adc_dead_time=10e-6,
)
# A fixed MD5-shaped hash for `signed`. The package checks only that a hash is there.
SIGNATURE_VALUE = "0123456789abcdef0123456789abcdef"

NUM_SAMPLES = 64
CENTER = NUM_SAMPLES // 2
DWELL = 20e-6  # s
WIDTH = 5e-3  # m, for crusher and phase-encode areas in cycles across the width


def signed(seq: pp.Sequence) -> pp.Sequence:
    """Give `seq` a `[SIGNATURE]` hash, as `write` does, and return `seq`.

    The package refuses a sequence with no hash (`extensions.refuse_unsigned`), and checks
    only that a hash is there, not that it is the hash of the sequence. So a fixed value is
    enough. The tests do not call `write` to sign each sequence: pypulseq's `write` fails
    for an oversampled arbitrary gradient (pypulseq-issues 04)."""
    seq.signature_type = "md5"
    seq.signature_file = "text"
    seq.signature_value = SIGNATURE_VALUE
    return seq


def block_pulse(use: str, flip: float):
    return pp.make_block_pulse(
        flip_angle=flip, duration=1e-3, delay=SYSTEM.rf_dead_time, system=SYSTEM, use=use
    )


def readout():
    """Readout gradient, its ADC with sample CENTER at the flat-top center, and the
    readout area from the block start to that sample."""
    gx = pp.make_trapezoid(channel="x", flat_time=1.4e-3, flat_area=1000, system=SYSTEM)
    echo_offset = (CENTER + 0.5) * DWELL
    adc = pp.make_adc(
        num_samples=NUM_SAMPLES,
        dwell=DWELL,
        delay=round((gx.rise_time + gx.flat_time / 2 - echo_offset) * 1e6) * 1e-6,
        system=SYSTEM,
    )
    return gx, adc, gx.amplitude * (adc.delay + echo_offset - gx.rise_time / 2)


def spin_echo_sequence(prephaser_position: str = "before") -> pp.Sequence:
    """90°, readout prephaser, crusher (3 cycles across WIDTH), 180°, second crusher
    (the same), readout. Block pulses, so no slice-select gradients. With
    prephaser_position "after", the readout prephaser is after the second crusher, with
    the opposite sign."""
    gx, adc, balance = readout()
    seq = pp.Sequence(SYSTEM)
    sign = 1 if prephaser_position == "before" else -1
    prephaser = pp.make_trapezoid(channel="x", area=sign * balance, system=SYSTEM)
    seq.add_block(block_pulse("excitation", math.pi / 2))
    if prephaser_position == "before":
        seq.add_block(prephaser)
    seq.add_block(pp.make_trapezoid(channel="y", area=3 / WIDTH, system=SYSTEM))
    seq.add_block(block_pulse("refocusing", math.pi))
    seq.add_block(pp.make_trapezoid(channel="y", area=3 / WIDTH, system=SYSTEM))
    if prephaser_position == "after":
        seq.add_block(prephaser)
    seq.add_block(gx, adc)
    return signed(seq)


def gre_sequence(num_trs: int = 4) -> pp.Sequence:
    """A minimal spoiled gradient-echo sequence: `num_trs` repetitions, each a hard
    excitation pulse, a phase-encode trapezoid on y, a readout trapezoid on x with an
    ADC, and a spoiler trapezoid on z, padded to a TR of 20 ms with a delay block."""
    tr = 20e-3
    seq = pp.Sequence(SYSTEM)
    gx, adc, _ = readout()
    pe = pp.make_trapezoid(channel="y", area=1 / WIDTH, system=SYSTEM)
    spoiler = pp.make_trapezoid(channel="z", area=4 / WIDTH, system=SYSTEM)
    for _ in range(num_trs):
        rf = block_pulse("excitation", math.radians(20))
        used = (
            pp.calc_duration(rf)
            + pp.calc_duration(pe)
            + pp.calc_duration(gx, adc)
            + pp.calc_duration(spoiler)
        )
        seq.add_block(rf)
        seq.add_block(pe)
        seq.add_block(gx, adc)
        seq.add_block(spoiler)
        pad = tr - used
        if pad > 0:
            seq.add_block(pp.make_delay(pad))
    seq.set_definition("TR", tr)
    return signed(seq)


def empty_sequence() -> pp.Sequence:
    """A sequence with one delay block only: no RF, gradients or ADC."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_delay(2e-3))
    return signed(seq)


def arbitrary_gradient_sequence() -> pp.Sequence:
    """A sequence with one block: a short sine-lobe arbitrary gradient on x, within
    system limits."""
    seq = pp.Sequence(SYSTEM)
    n = 40
    dt = SYSTEM.grad_raster_time
    t = (np.arange(n) + 0.5) * dt
    waveform = 0.1 * SYSTEM.max_grad * np.sin(np.pi * t / (n * dt))
    g = pp.make_arbitrary_grad(channel="x", waveform=waveform, system=SYSTEM)
    seq.add_block(g)
    return signed(seq)


def border_sequence() -> pp.Sequence:
    """Two extended-trapezoid blocks on x whose gradient is not zero at the border
    between them, unlike a plain trapezoid (which is zero at both ends of its own
    event): the amplitude ramps up in block 0 and continues, unchanged, into block 1,
    where it ramps back down to 0. `add_block` accepts this because the amplitude is
    continuous across the junction (no step)."""
    dt = SYSTEM.grad_raster_time
    amp = 0.1 * SYSTEM.max_grad  # the same fraction of max_grad as arbitrary_gradient_sequence
    n = 40
    rise = n * dt
    g1 = pp.make_extended_trapezoid(
        channel="x", amplitudes=np.array([0.0, amp]), times=np.array([0.0, rise]), system=SYSTEM
    )
    g2 = pp.make_extended_trapezoid(
        channel="x", amplitudes=np.array([amp, 0.0]), times=np.array([0.0, rise]), system=SYSTEM
    )
    seq = pp.Sequence(SYSTEM)
    seq.add_block(g1)
    seq.add_block(g2)
    return signed(seq)


RASTER_4US = 4e-6  # s
# The junction step of `raster_4us_sequence` divided by RASTER_4US, in T/m/s.
RASTER_4US_JUNCTION = 60.0
# The time of the junction in `raster_4us_sequence`, s.
RASTER_4US_JUNCTION_TIME = 800e-6


def raster_4us_sequence() -> pp.Sequence:
    """Two y extended trapezoids, built with a 4 µs gradient raster. Block 1 ramps from 0 to
    16 mT/m in 400 µs (40 T/m/s) and stays there for 400 µs. Block 2 starts at 15.76 mT/m, a
    step of 0.24 mT/m, stays there for 400 µs and ramps to 0 in 400 µs (39.4 T/m/s). The
    junction step divided by 4 µs is 60 T/m/s, and divided by 10 µs is 24 T/m/s. No segment
    slope is above 40 T/m/s."""
    system = pp.Opts(
        max_grad=100,
        grad_unit="mT/m",
        max_slew=200,
        slew_unit="T/m/s",
        grad_raster_time=RASTER_4US,
    )
    top = 16e-3 * GAMMA_1H  # Hz/m
    start = 15.76e-3 * GAMMA_1H  # Hz/m
    seq = pp.Sequence(system)
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="y", times=[0.0, 400e-6, 800e-6], amplitudes=[0.0, top, top], system=system
        )
    )
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="y", times=[0.0, 400e-6, 800e-6], amplitudes=[start, start, 0.0], system=system
        )
    )
    return signed(seq)


# A scalar-first unit quaternion (angle 45 deg about z): q0=cos(22.5deg), qz=sin(22.5deg).
QUATERNION = (0.9238795325112867, 0.0, 0.0, 0.3826834323650898)


def with_rotation_library() -> pp.Sequence:
    """A `gre_sequence` with one rotation stored the way pypulseq draft PR #372 stores
    it: a `rotation_library` (an `EventLibrary` of scalar-first unit quaternions)."""
    seq = gre_sequence(num_trs=2)
    seq.rotation_library = EventLibrary()
    seq.rotation_library.insert(1, QUATERNION)
    return seq


def waveform_sequence(system: pp.Opts, sign: float = 1.0) -> pp.Sequence:
    """A trapezoid on x and an arbitrary gradient on y, each with an explicit amplitude in Hz/m
    (times `sign`), so that the samples and the values do not depend on the gamma of `system`."""
    n = 50
    waveform_hz_per_m = 0.2 * SYSTEM.max_grad * np.sin(np.pi * np.arange(1, n + 1) / (n + 1))
    gx = pp.make_trapezoid(
        channel="x",
        amplitude=sign * 0.5 * SYSTEM.max_grad,  # Hz/m
        rise_time=200e-6,
        flat_time=400e-6,
        system=system,
    )
    gy = pp.make_arbitrary_grad(
        channel="y", waveform=sign * waveform_hz_per_m, first=0.0, last=0.0, system=system
    )
    seq = pp.Sequence(system)
    seq.add_block(gx)
    seq.add_block(gy)
    seq.add_block(gx, gy)
    return signed(seq)
