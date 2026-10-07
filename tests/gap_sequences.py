"""The sequences of the gradient gap model, with hand-computed values, and their constants.

The sequences have an event that starts or ends at a value that is not 0 next to a gap, a step
at a block junction, or two axes in one block. `test_oracle_waveform.py` checks the oracle
(`oracles/waveform.py`) on them, and the tests of `gradient_peaks`, `sampling`, `pns_levels` and
`grad_spectrum` compare the package with the oracle on them.
"""

import pypulseq as pp
from synthetic import SYSTEM

DT = SYSTEM.grad_raster_time  # 10 us
U = 1e4  # Hz/m. Every value of the sequences below is a multiple of U, or A.
# The largest end value that `add_block` accepts next to a gap: max_slew * DT = 63864 Hz/m.
# The sequences of pypulseq-issues 12 use half of it.
A = 0.5 * SYSTEM.max_slew * SYSTEM.grad_raster_time


def extended(times, amplitudes, delay=0.0, channel="x"):
    g = pp.make_extended_trapezoid(channel, times=times, amplitudes=amplitudes, system=SYSTEM)
    g.delay = delay
    return g


def sequence(*blocks):
    seq = pp.Sequence(SYSTEM)
    for events in blocks:
        seq.add_block(*events)
    return seq


def delayed_sequence():
    """The first sequence of pypulseq-issues 12: the second gradient starts at A after
    a delay of 100 us."""
    return sequence(
        [extended([0, 100e-6, 200e-6], [0, A, A])],
        [extended([0, 100e-6], [A, 0], delay=100e-6)],
    )


def early_end_sequence():
    """The second sequence of pypulseq-issues 12: the first gradient ends at A, 100 us
    before the end of its block."""
    return sequence(
        [extended([0, 100e-6, 200e-6], [0, A, A]), pp.make_delay(300e-6)],
        [extended([0, 100e-6], [A, 0])],
    )


def zero_gap_sequence():
    """Two blocks on x. The first ends at 2 U, and the second starts at U: a step of
    -U at 200 us, which is less than max_slew * DT."""
    return sequence(
        [extended([0, 100e-6, 200e-6], [0, U, 2 * U])],
        [extended([0, 100e-6], [U, 0])],
    )


def short_gap_sequence():
    """The first gradient ends at 3 U at 100 us and its block ends at 110 us. The second
    block starts at 2 U. The gap is one raster time."""
    return sequence(
        [extended([0, 100e-6], [0, 3 * U]), pp.make_delay(110e-6)],
        [extended([0, 100e-6], [2 * U, 0])],
    )


def long_gap_sequence():
    """Gradient ends at 3 U at 100 us, a block of 200 us with no gradient, and a gradient
    that starts at 2 U at 300 us. The gap is 200 us."""
    return sequence(
        [extended([0, 100e-6], [0, 3 * U])],
        [pp.make_delay(200e-6)],
        [extended([0, 100e-6], [2 * U, 0])],
    )


def non_zero_ends_sequence():
    """The first gradient starts at 3 U at 0, and the last one ends at 2 U at 200 us."""
    return sequence(
        [extended([0, 100e-6], [3 * U, 0])],
        [extended([0, 100e-6], [0, 2 * U])],
    )


def vector_sequence():
    """One block of 400 us: x is a trapezoid of 3 U (rise 100 us, flat 200 us, fall
    100 us), y is a triangle of 4 U with the top at 150 us. z has no event."""
    gx = pp.make_trapezoid(
        channel="x",
        amplitude=3 * U,
        rise_time=100e-6,
        flat_time=200e-6,
        fall_time=100e-6,
        system=SYSTEM,
    )
    gy = extended([0, 150e-6, 400e-6], [0, 4 * U, 0], channel="y")
    return sequence([gx, gy])
