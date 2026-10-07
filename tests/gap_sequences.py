"""The sequences of the gradient gap model, with hand-computed values, and their constants.

The sequences have an event that starts or ends at a value that is not 0 next to a gap, a step
at a block junction, or two axes in one block. `test_oracle_waveform.py` checks the oracle
(`oracles/waveform.py`) on them, and the tests of `gradient_peaks`, `sampling`, `pns_levels` and
`grad_spectrum` compare the package with the oracle on them.
"""

import numpy as np
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


def negated(seq: pp.Sequence) -> pp.Sequence:
    """A new sequence with the blocks of `seq`, each gradient scaled by -1 (`pp.scale_grad`) and
    each block duration kept (as a delay event). The result has no kept result of any analysis:
    those are for one object."""
    negative = pp.Sequence(seq.system)
    for block_id in seq.block_events:
        block = seq.get_block(block_id)
        events = [
            pp.scale_grad(getattr(block, name), -1.0)
            for name in ("gx", "gy", "gz")
            if getattr(block, name) is not None
        ]
        negative.add_block(*events, pp.make_delay(block.block_duration))
    return negative


def gap_of_1_5_raster_times_sequence() -> pp.Sequence:
    """The first gradient ends at 3 U at 100 us, and its block ends at 110 us. The second
    gradient starts at 2 U after a delay of 5 us, so at 115 us: a gap of 15 us (1.5 raster
    times), which is a long gap, between two values that are not 0."""
    return sequence(
        [extended([0, 100e-6], [0, 3 * U]), pp.make_delay(110e-6)],
        [extended([0, 100e-6], [2 * U, 0], delay=5e-6), pp.make_delay(110e-6)],
    )


def short_gap_from_0_sequence() -> pp.Sequence:
    """The first gradient ends at 0 at 200 us, and its block ends at 210 us. The second
    gradient starts at 2 U. The gap is one raster time, from 0 to a value that is not 0."""
    return sequence(
        [extended([0, 100e-6, 200e-6], [0, 3 * U, 0]), pp.make_delay(210e-6)],
        [extended([0, 100e-6], [2 * U, 0])],
    )


def short_gap_to_0_sequence() -> pp.Sequence:
    """The first gradient ends at 3 U at 100 us, and its block ends at 110 us. The second
    gradient starts at 0. The gap is one raster time, from a value that is not 0 to 0."""
    return sequence(
        [extended([0, 100e-6], [0, 3 * U]), pp.make_delay(110e-6)],
        [extended([0, 100e-6, 200e-6], [0, 3 * U, 0])],
    )


# The cases of `delayed_ramp_sequence` (the delay and the ramp in raster times, the number of
# filler blocks, and the length of a filler block in raster times) in which the sum `delay +
# offset` of the last point of the ramp is one ulp before the sample time `(j + 0.5) * DT` that it
# falls on, and `block_samples` of the sequence before the fix of review 1.3 gave 0 there.
DELAYED_RAMP_CASES = (
    (1.5, 23, 2, 5),
    (1.5, 25, 2, 2),
    (1.5, 27, 2, 5),
    (1.5, 29, 2, 2),
    (2.5, 22, 2, 5),
    (3.5, 21, 1, 2),
    (3.5, 23, 2, 2),
    (4.5, 20, 1, 2),
)

# More cases of `delayed_ramp_sequence`, chosen from a scan of 6960 cases (delays of 0.5 to 4.5 raster
# times, ramps of 1 to 29, 0 to 11 fillers of 1, 2, 5 or 7 raster times). The sum `(start + delay)
# + offset` of the last point is before the sample time `start + (j + 0.5) * DT` in each case, so
# an oracle with no tolerance after the last point gives 0 there. In the first three the local sum
# `delay + offset` is not before `(j + 0.5) * DT`, so `block_samples` gave the end value before the
# fix of review 1.3 too. In the last three it is before, and `block_samples` gave 0.
ULP_EDGE_CASES = (
    (0.5, 1, 2, 2),
    (2.5, 24, 8, 7),
    (4.5, 29, 11, 2),
    (1.5, 23, 0, 1),
    (3.5, 21, 11, 7),
    (4.5, 22, 11, 2),
)


def delayed_ramp_sequence(
    delay_rasters: float, ramp_rasters: int, fillers: int, filler_rasters: int
) -> pp.Sequence:
    """`fillers` blocks of `filler_rasters` raster times with no gradient, and then a block of
    `ramp_rasters + 10` raster times with a ramp on x from 0 to A over `ramp_rasters` raster
    times, after a delay of `delay_rasters` raster times. The delay is a whole number of raster
    times and a half, so the last point of the ramp is at a sample time of the raster. The
    filler blocks put the block away from the start of the sequence, where the oracle takes the
    times of the points from the sum of the block durations."""
    blocks = [[pp.make_delay(filler_rasters * DT)] for _ in range(fillers)]
    ramp = extended([0.0, ramp_rasters * DT], [0.0, A], delay=delay_rasters * DT)
    blocks.append([ramp, pp.make_delay((ramp_rasters + 10) * DT)])
    return sequence(*blocks)


def short_arbitrary_sequence() -> pp.Sequence:
    """An arbitrary gradient of 3 samples (U, 1.5 U and 2 U) with first value U and last
    value 1.5 U, in a block of 8 raster times. `get_block` gives it the points (25 us, 2 U) and
    (25 us, 1.5 U): a step at 25 us, which is the time of the third sample of the raster, and
    the value there is the one before the step, 2 U."""
    g = pp.make_arbitrary_grad(
        channel="x",
        waveform=np.array([U, 1.5 * U, 2 * U]),
        first=U,
        last=1.5 * U,
        system=SYSTEM,
    )
    return sequence([g, pp.make_delay(8 * DT)])
