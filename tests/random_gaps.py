"""Random sequences with gradient ends that are not 0 next to zero, short and long gaps.

`random_gap_sequence(rng)` is the input of the oracle comparisons of `gradient_peaks`,
`GradientSampler`, `pns_levels` and `gradient_spectrum`. Moved from `test_grad_peaks.py` so
that each test file can use it. It imports nothing from the package, so the oracles can use it.
"""

import math

import numpy as np
import pypulseq as pp
from synthetic import SYSTEM, signed

AXES = ("x", "y", "z")
_RASTER = SYSTEM.grad_raster_time
_MAX_STEP = SYSTEM.max_slew * _RASTER  # the largest step add_block accepts


def end_value(rng: np.random.Generator, previous: float) -> float:
    """A first or a last value of a gradient that is not 0 for most calls: 0, the value
    `previous` (no step), or a random value below the largest step that `add_block` accepts,
    and within 0.9 of that step of `previous`."""
    choice = rng.random()
    if choice < 0.3:
        value = 0.0
    elif choice < 0.5:
        value = previous
    else:
        value = rng.uniform(-0.9, 0.9) * _MAX_STEP
    value = float(np.clip(value, previous - 0.9 * _MAX_STEP, previous + 0.9 * _MAX_STEP))
    return float(np.clip(value, -0.9 * _MAX_STEP, 0.9 * _MAX_STEP))


def gap_event(rng: np.random.Generator, channel: str, previous_last: float):
    """A random gradient event on `channel`, and its last value: a trapezoid (it starts and ends
    at 0), an extended trapezoid or an arbitrary gradient. The last two have a first value and a
    last value from `end_value` (not 0 for most events, `previous_last` is the last value of
    the block before). The event has a delay of 0 to 7 raster times, so the gap before it is
    zero, short or long. An event with a delay has a first value that is not 0 for 70% of its
    calls: `add_block` accepts it below `max_slew * grad_raster_time`."""
    kind = int(rng.integers(0, 3))
    delay = float(rng.choice([0, 0, 0, 1, 2, 3, 7]) * _RASTER)
    if kind == 0:
        amplitude = rng.uniform(0.05, 0.8) * SYSTEM.max_grad * rng.choice([-1.0, 1.0])
        rise = math.ceil(max(abs(amplitude) / (0.7 * SYSTEM.max_slew), 50e-6) / _RASTER) * _RASTER
        flat = round(rng.uniform(0.0, 300e-6) / _RASTER) * _RASTER
        g = pp.make_trapezoid(
            channel=channel, amplitude=amplitude, rise_time=rise, flat_time=flat, system=SYSTEM
        )
        g.delay = delay
        return g, 0.0
    first = end_value(rng, previous_last) if delay == 0 or rng.random() < 0.7 else 0.0
    last = end_value(rng, 0.0)
    if kind == 1:
        peak = rng.uniform(0.05, 0.6) * SYSTEM.max_grad * rng.choice([-1.0, 1.0])
        ramp = math.ceil(max(abs(peak) / (0.7 * SYSTEM.max_slew), 50e-6) / _RASTER) * _RASTER
        flat = round(rng.uniform(_RASTER, 200e-6) / _RASTER) * _RASTER
        g = pp.make_extended_trapezoid(
            channel=channel,
            times=[0.0, ramp, ramp + flat, 2 * ramp + flat],
            amplitudes=[first, peak, peak, last],
            system=SYSTEM,
        )
    else:
        # A waveform that is slow enough for the slew limit, with the first and the last value
        # of 0.2 of the largest step at most.
        n = int(rng.integers(6, 30))
        amplitude = rng.uniform(0.02, 0.2) * SYSTEM.max_grad
        amplitude = min(amplitude, 0.2 * _MAX_STEP * (n + 1) / np.pi)
        waveform = amplitude * np.sin(np.pi * np.arange(1, n + 1) / (n + 1))
        first = float(np.clip(first, -0.2 * _MAX_STEP, 0.2 * _MAX_STEP))
        last = float(np.clip(last, -0.2 * _MAX_STEP, 0.2 * _MAX_STEP))
        g = pp.make_arbitrary_grad(
            channel=channel,
            waveform=waveform * rng.choice([-1.0, 1.0]),
            first=first,
            last=last,
            system=SYSTEM,
        )
    g.delay = delay
    return g, last


def random_gap_sequence(rng: np.random.Generator) -> pp.Sequence:
    """A sequence of 2 to 8 blocks (a block of zero duration among them for 12% of the blocks),
    each with 0 to 3 random gradient events (`gap_event`) that start and end at values that are
    not 0 for most of them, and each block with a delay event of 0 to 5 raster times after
    its events for half of them. The gaps between the events of one axis are zero, short and long,
    with steps, lines and ramps. A block that `add_block` refuses (a step at a block
    junction of more than `max_slew * grad_raster_time`) is not added."""
    seq = signed(pp.Sequence(SYSTEM))
    last = dict.fromkeys(AXES, 0.0)
    for _ in range(int(rng.integers(2, 9))):
        if rng.random() < 0.12:
            seq.add_block(pp.make_label(label="LIN", type="SET", value=1))
            continue
        new_last = dict.fromkeys(AXES, 0.0)
        events = []
        for axis in AXES:
            if rng.random() < 0.55:
                event, new_last[axis] = gap_event(rng, axis, last[axis])
                events.append(event)
        extra = float(rng.choice([0, 0, 1, 2, 5]) * _RASTER)
        if events and extra:
            events.append(pp.make_delay(pp.calc_duration(*events) + extra))
        elif not events:
            events.append(pp.make_delay(float(rng.choice([1, 3, 10]) * 1e-4)))
        try:
            seq.add_block(*events)
        except RuntimeError:
            continue
        last = new_last
    return seq
