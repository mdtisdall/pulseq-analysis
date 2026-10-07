import math

import numpy as np
import pypulseq as pp
import pytest
from gap_sequences import (
    DT,
    A,
    U,
    delayed_sequence,
    early_end_sequence,
    long_gap_sequence,
    non_zero_ends_sequence,
    sequence,
    short_gap_sequence,
    vector_sequence,
    zero_gap_sequence,
)
from oracles import waveform as oracle
from synthetic import SYSTEM, arbitrary_gradient_sequence, gre_sequence, spin_echo_sequence

AMPLITUDE = {"rel": 1e-9, "abs": 1e-6}  # Hz/m
TIME = {"rel": 0.0, "abs": 1e-12}  # s


def _times(actual, expected):
    assert np.asarray(actual) == pytest.approx(np.asarray(expected), **TIME)


def _amplitudes(actual, expected):
    assert np.asarray(actual) == pytest.approx(np.asarray(expected), **AMPLITUDE)


def _distinct(poly):
    """The points of `poly` without a point that is the same as the point before it."""
    keep = np.ones(poly.t.size, dtype=bool)
    keep[1:] = (np.abs(np.diff(poly.t)) > 1e-12) | (np.abs(np.diff(poly.g)) > 1e-6)
    return poly.t[keep], poly.g[keep]


def _assert_values(values, peak, peak_time, peak_block, max_slew, slew_time, slew_block, rms):
    assert values["peak"] == pytest.approx(peak, **AMPLITUDE)
    assert values["peak_time"] == pytest.approx(peak_time, **TIME)
    assert values["peak_block"] == peak_block
    assert values["max_slew"] == pytest.approx(max_slew, rel=1e-9)
    assert values["slew_time"] == pytest.approx(slew_time, **TIME)
    assert values["slew_block"] == slew_block
    assert values["rms"] == pytest.approx(rms, **AMPLITUDE)


@pytest.mark.parametrize("build", [delayed_sequence, early_end_sequence])
def test_the_polyline_of_each_sequence_of_pypulseq_issue_12_is_the_one_of_matlab_pulseq(build):
    seq = build()
    poly = oracle.axis_polyline(seq, "x")

    t, g = _distinct(poly)
    _times(t, np.array([0, 100, 200, 205, 295, 300, 400]) * 1e-6)
    _amplitudes(g, [0, A, A, 0, 0, A, 0])
    assert poly.step_time.size == 0
    # The ramp to 0 is credited to the first block, the ramp from 0 to the second block.
    assert poly.point_play[np.isclose(poly.t, 205e-6, rtol=0, atol=1e-12)].tolist() == [0]
    assert poly.point_play[np.isclose(poly.t, 295e-6, rtol=0, atol=1e-12)].tolist() == [1]
    times = np.array([50, 150, 202.5, 250, 297.5, 350]) * 1e-6
    _amplitudes(oracle.sample(seq, "x", times), [A / 2, A, A / 2, 0, A / 2, A / 2])


@pytest.mark.parametrize("build", [delayed_sequence, early_end_sequence])
def test_the_values_of_each_sequence_of_pypulseq_issue_12_are_hand_values(build):
    values = oracle.peaks(build())

    # Each ramp goes from A to 0 in DT / 2, so its slope is 2 A / DT = max_slew. The ramp
    # to 0 and the ramp from 0 have the same slope, so the time of the slew is one of them.
    assert values["x"]["max_slew"] == pytest.approx(SYSTEM.max_slew, rel=1e-9)
    assert values["x"]["slew_time"] in (
        pytest.approx(200e-6, **TIME),
        pytest.approx(295e-6, **TIME),
    )
    assert values["x"]["peak"] == pytest.approx(A, **AMPLITUDE)
    assert values["vector_peak"] == pytest.approx(A, **AMPLITUDE)
    # The integral of g^2 in units of A^2 x 1 us: 100/3 + 100 + 5/3 + 0 + 5/3 + 100/3 = 170,
    # over the 400 us of the sequence.
    assert values["x"]["rms"] == pytest.approx(A * math.sqrt(170 / 400), **AMPLITUDE)
    for axis in ("y", "z"):
        assert values[axis]["peak_block"] is None


def test_a_zero_gap_with_two_different_values_is_a_step_that_the_later_block_has():
    seq = zero_gap_sequence()
    poly = oracle.axis_polyline(seq, "x")

    t, g = _distinct(poly)
    _times(t, np.array([0, 100, 200, 200, 300]) * 1e-6)
    _amplitudes(g, [0, U, 2 * U, U, 0])
    assert poly.step_time == pytest.approx([200e-6], **TIME)
    assert poly.step_size == pytest.approx([-U], **AMPLITUDE)
    assert poly.step_play.tolist() == [1]
    # The value at the time of the step is the value before it.
    assert oracle.sample(seq, "x", poly.step_time)[0] == pytest.approx(2 * U, **AMPLITUDE)
    _amplitudes(oracle.sample(seq, "x", np.array([50e-6, 150e-6, 250e-6])), [U / 2, 1.5 * U, U / 2])

    # The slope of each segment is U / 100 us = 2e8 Hz/m/s. The step is U / DT = 2e9.
    # The integral of g^2 in units of U^2 x 100 us: 1/3 + 7/3 + 1/3 = 3, over 300 us.
    _assert_values(
        oracle.peaks(seq)["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=1,
        max_slew=U / DT,
        slew_time=200e-6,
        slew_block=2,
        rms=U,
    )


def test_a_window_has_the_step_at_its_start_and_not_the_step_at_its_end():
    seq = zero_gap_sequence()

    # (150, 250) us has the step. The integral of g^2 in units of U^2 x 50 us:
    # (2.25 + 3 + 4) / 3 + (1 + 0.5 + 0.25) / 3 = 11 / 3, over 100 us.
    _assert_values(
        oracle.peaks(seq, window=(150e-6, 250e-6))["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=1,
        max_slew=U / DT,
        slew_time=200e-6,
        slew_block=2,
        rms=U * math.sqrt(11 / 6),
    )
    # (100, 200) us ends at the step: the step is not in it, and neither is the first
    # point of the second block. The slope of the segment is U / 100 us. The integral in
    # units of U^2 x 100 us is 7 / 3.
    _assert_values(
        oracle.peaks(seq, window=(100e-6, 200e-6))["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=1,
        max_slew=U / 100e-6,
        slew_time=100e-6,
        slew_block=1,
        rms=U * math.sqrt(7 / 3),
    )
    # (200, 300) us starts at the step: the step is in it, and the last point of the first
    # block is not. The integral in units of U^2 x 100 us is 1 / 3.
    _assert_values(
        oracle.peaks(seq, window=(200e-6, 300e-6))["x"],
        peak=U,
        peak_time=200e-6,
        peak_block=2,
        max_slew=U / DT,
        slew_time=200e-6,
        slew_block=2,
        rms=U / math.sqrt(3),
    )
    # The vector peak at the time of the step: (100, 200) us has the value before the step
    # (2 U, in the first block), and (200, 300) us the value after it (U, in the second).
    for window, value, block in (((100e-6, 200e-6), 2 * U, 1), ((200e-6, 300e-6), U, 2)):
        values = oracle.peaks(seq, window=window)
        assert values["vector_peak"] == pytest.approx(value, **AMPLITUDE)
        assert values["vector_peak_time"] == pytest.approx(200e-6, **TIME)
        assert values["vector_peak_block"] == block


def test_a_short_gap_is_a_line_that_the_later_block_has():
    seq = short_gap_sequence()
    poly = oracle.axis_polyline(seq, "x")

    t, g = _distinct(poly)
    _times(t, np.array([0, 100, 110, 210]) * 1e-6)
    _amplitudes(g, [0, 3 * U, 2 * U, 0])
    assert poly.step_time.size == 0
    assert oracle.sample(seq, "x", np.array([105e-6]))[0] == pytest.approx(2.5 * U, **AMPLITUDE)

    # The slope of the line is U / 10 us = 1e9 Hz/m/s, more than the slope of the rise
    # (3 U / 100 us) and of the fall (2 U / 100 us). The integral of g^2 in units of
    # U^2 x 1 us: 300 + 19 / 3 x 10 + 400 / 3 = 496.667, over 210 us.
    _assert_values(
        oracle.peaks(seq)["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=1,
        max_slew=U / DT,
        slew_time=100e-6,
        slew_block=2,
        rms=U * math.sqrt(149 / 63),
    )

    # The samples are at 5, 15, ... us of the first block (110 us, so 11 samples), and of
    # the second block (100 us, so 10 samples). The 11th sample is in the gap.
    first = [3 * U * (5 + 10 * j) / 100 for j in range(10)] + [2.5 * U]
    second = [2 * U * (1 - (5 + 10 * j) / 100) for j in range(10)]
    _amplitudes(oracle.block_samples(seq, "x", DT), first + second)


def test_a_long_gap_has_a_ramp_to_zero_for_each_end_that_is_not_zero():
    seq = long_gap_sequence()
    poly = oracle.axis_polyline(seq, "x")

    t, g = _distinct(poly)
    _times(t, np.array([0, 100, 105, 295, 300, 400]) * 1e-6)
    _amplitudes(g, [0, 3 * U, 0, 0, 2 * U, 0])
    assert poly.step_time.size == 0
    # The ramp to 0 is credited to the first block, and the ramp from 0 to the third.
    assert poly.point_play[np.isclose(poly.t, 105e-6, rtol=0, atol=1e-12)].tolist() == [0]
    assert poly.point_play[np.isclose(poly.t, 295e-6, rtol=0, atol=1e-12)].tolist() == [2]

    # The ramp to 0 has the slope 3 U / 5 us = 6e9 Hz/m/s, and is credited to the first
    # block at 100 us. The integral of g^2 in units of U^2 x 1 us: 300 + 15 + 20 / 3 +
    # 400 / 3 = 455, over 400 us.
    _assert_values(
        oracle.peaks(seq)["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=1,
        max_slew=3 * U / 5e-6,
        slew_time=100e-6,
        slew_block=1,
        rms=U * math.sqrt(455 / 400),
    )

    # The ramps end at the times of samples, where they are 0: the 20 samples of the block
    # with no gradient are 0.
    first = [3 * U * (5 + 10 * j) / 100 for j in range(10)]
    third = [2 * U * (1 - (5 + 10 * j) / 100) for j in range(10)]
    _amplitudes(oracle.block_samples(seq, "x", DT), first + [0.0] * 20 + third)


def test_a_window_cuts_the_ramp_of_a_long_gap_and_credits_it_to_the_block_of_the_ramp():
    seq = long_gap_sequence()

    # (150, 250) us is in the gap, where the value is 0.
    values = oracle.peaks(seq, window=(150e-6, 250e-6))
    _assert_values(values["x"], 0.0, 0.0, None, 0.0, 0.0, None, 0.0)
    assert (values["vector_peak"], values["vector_peak_block"]) == (0.0, None)

    # (102.5, 150) us has the half of the ramp to 0, from 1.5 U to 0 in 2.5 us. The
    # integral of g^2 is (1.5 U)^2 x 2.5 us / 3. The block of the vector peak is the block
    # that has the time of the peak, 102.5 us: the second block, not the block of the ramp.
    values = oracle.peaks(seq, window=(102.5e-6, 150e-6))
    _assert_values(
        values["x"],
        peak=1.5 * U,
        peak_time=102.5e-6,
        peak_block=1,
        max_slew=3 * U / 5e-6,
        slew_time=102.5e-6,
        slew_block=1,
        rms=math.sqrt((1.5 * U) ** 2 * 2.5e-6 / 3 / 47.5e-6),
    )
    assert values["vector_peak"] == pytest.approx(1.5 * U, **AMPLITUDE)
    assert values["vector_peak_time"] == pytest.approx(102.5e-6, **TIME)
    assert values["vector_peak_block"] == 2

    # (102.5, 400) us has also the ramp from 0 and the last block: the peak is 2 U at
    # 300 us, in the third block.
    _assert_values(
        oracle.peaks(seq, window=(102.5e-6, 400e-6))["x"],
        peak=2 * U,
        peak_time=300e-6,
        peak_block=3,
        max_slew=3 * U / 5e-6,
        slew_time=102.5e-6,
        slew_block=1,
        rms=math.sqrt(
            ((1.5 * U) ** 2 / 3 * 2.5 + (2 * U) ** 2 / 3 * 5 + (2 * U) ** 2 / 3 * 100)
            * 1e-6
            / 297.5e-6
        ),
    )


def test_a_first_value_and_a_last_value_that_are_not_zero_are_steps_at_the_two_ends():
    seq = non_zero_ends_sequence()
    poly = oracle.axis_polyline(seq, "x")

    t, g = _distinct(poly)
    _times(t, np.array([0, 100, 200]) * 1e-6)
    _amplitudes(g, [3 * U, 0, 2 * U])
    assert poly.step_time == pytest.approx([0.0, 200e-6], **TIME)
    assert poly.step_size == pytest.approx([3 * U, -2 * U], **AMPLITUDE)
    assert poly.step_play.tolist() == [0, 1]
    _amplitudes(
        oracle.sample(seq, "x", np.array([-1e-6, 50e-6, 150e-6, 201e-6])), [0, 1.5 * U, U, 0]
    )

    # The first step is 3 U / DT = 3e9 at 0. The last step is at the end, so the whole
    # sequence does not have it. The integral of g^2 in units of U^2 x 1 us:
    # 300 + 400 / 3 = 433.33, over 200 us.
    _assert_values(
        oracle.peaks(seq)["x"],
        peak=3 * U,
        peak_time=0.0,
        peak_block=1,
        max_slew=3 * U / DT,
        slew_time=0.0,
        slew_block=1,
        rms=U * math.sqrt(13 / 6),
    )
    # (100, 200) us: neither step is in it. The slope is 2 U / 100 us. The integral in
    # units of U^2 x 100 us is 4 / 3.
    _assert_values(
        oracle.peaks(seq, window=(100e-6, 200e-6))["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=2,
        max_slew=2 * U / 100e-6,
        slew_time=100e-6,
        slew_block=2,
        rms=2 * U / math.sqrt(3),
    )
    # (50, 200) us cuts the first segment at 1.5 U, with the slope 3 U / 100 us, which is
    # more than the slope of the second segment. The time of the slew is the start of the cut.
    _assert_values(
        oracle.peaks(seq, window=(50e-6, 200e-6))["x"],
        peak=2 * U,
        peak_time=200e-6,
        peak_block=2,
        max_slew=3 * U / 100e-6,
        slew_time=50e-6,
        slew_block=1,
        rms=U * math.sqrt(((1.5**2 / 3) * 50 + (4 / 3) * 100) / 150),
    )


def test_the_vector_peak_is_at_the_union_of_the_points_of_the_axes():
    seq = vector_sequence()

    values = oracle.peaks(seq)
    # x is 3 U and y is 4 U at 150 us, the time of a point of y only: the vector is 5 U.
    # At 100 us it is hypot(3 U, 2.667 U), and at 300 us hypot(3 U, 1.6 U), both less.
    assert values["vector_peak"] == pytest.approx(5 * U, **AMPLITUDE)
    assert values["vector_peak_time"] == pytest.approx(150e-6, **TIME)
    assert values["vector_peak_block"] == 1
    # The integral of x^2 is (3 U)^2 x (100 / 3 + 200 + 100 / 3) us over 400 us. The one of
    # y^2 is (4 U)^2 x 400 us / 3 over 400 us.
    _assert_values(
        values["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=1,
        max_slew=3 * U / 100e-6,
        slew_time=0.0,
        slew_block=1,
        rms=3 * U * math.sqrt(2 / 3),
    )
    _assert_values(
        values["y"],
        peak=4 * U,
        peak_time=150e-6,
        peak_block=1,
        max_slew=4 * U / 150e-6,
        slew_time=0.0,
        slew_block=1,
        rms=4 * U / math.sqrt(3),
    )

    # (160, 400) us: the largest vector is at the start of the window, where y is
    # 4 U x 240 / 250.
    values = oracle.peaks(seq, window=(160e-6, 400e-6))
    assert values["vector_peak"] == pytest.approx(math.hypot(3 * U, 3.84 * U), **AMPLITUDE)
    assert values["vector_peak_time"] == pytest.approx(160e-6, **TIME)
    assert values["vector_peak_block"] == 1
    assert values["y"]["peak"] == pytest.approx(3.84 * U, **AMPLITUDE)
    assert values["y"]["peak_time"] == pytest.approx(160e-6, **TIME)
    # x is 3 U at the start of the window and at 300 us. The first one wins.
    assert values["x"]["peak_time"] == pytest.approx(160e-6, **TIME)


def test_an_axis_with_no_event_has_no_point_and_is_zero():
    seq = vector_sequence()

    poly = oracle.axis_polyline(seq, "z")
    assert poly.t.size == 0
    assert poly.step_time.size == 0
    assert poly.block_id == (1,)
    np.testing.assert_array_equal(oracle.sample(seq, "z", np.array([0.0, 100e-6, 400e-6])), 0.0)
    np.testing.assert_array_equal(oracle.block_samples(seq, "z", DT), np.zeros(40))
    _assert_values(oracle.peaks(seq)["z"], 0.0, 0.0, None, 0.0, 0.0, None, 0.0)


def test_a_segment_of_length_zero_inside_an_event_is_kept_and_has_no_slope():
    seq = sequence(
        [
            pp.make_trapezoid(
                channel="x",
                amplitude=3 * U,
                rise_time=100e-6,
                flat_time=0,
                fall_time=100e-6,
                system=SYSTEM,
            )
        ]
    )
    poly = oracle.axis_polyline(seq, "x")

    _times(poly.t, [0, 100e-6, 100e-6, 200e-6])
    _amplitudes(poly.g, [0, 3 * U, 3 * U, 0])
    assert poly.step_time.size == 0
    assert not poly.segment_is_step.any()
    # The slope is 3 U / 100 us. The integral of g^2 is 2 x (3 U)^2 x 100 us / 3, over 200 us.
    _assert_values(
        oracle.peaks(seq)["x"],
        peak=3 * U,
        peak_time=100e-6,
        peak_block=1,
        max_slew=3 * U / 100e-6,
        slew_time=0.0,
        slew_block=1,
        rms=3 * U / math.sqrt(3),
    )


@pytest.mark.parametrize("build", [spin_echo_sequence, gre_sequence, arbitrary_gradient_sequence])
def test_the_points_of_a_sequence_with_no_end_next_to_a_gap_are_the_points_of_pypulseq(build):
    seq = build()

    waveforms = seq.waveforms()
    for index, axis in enumerate(("x", "y", "z")):
        t, g = _distinct(oracle.axis_polyline(seq, axis))
        _times(t, waveforms[index][0])
        _amplitudes(g, waveforms[index][1])
