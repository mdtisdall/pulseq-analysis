import pickle
import tracemalloc
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from pulseq_analysis import analyses, seqfile, synth
from pulseq_analysis.seqfile import NotSupported, SeqFileError, interpreters, model
from pulseq_analysis.synth.events import (
    AdcEvent,
    ArbitraryGradient,
    RfEvent,
    Trapezoid,
    decode_adc,
    decode_gradients,
    decode_rf,
)
from pulseq_analysis.synth.seq_utils import gradient_offsets

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ORACLE = SEQFILES / "oracle"

# A 1.5.1 file with RF time shapes, an ADC phase shape, and an RF event and a trapezoid that no
# block uses. RF 1 has the time shape 3 (0.5, 1, 2, 4), which is not regular: points. RF 2 has the
# time shape 4, stored compressed in 4 values (5 10 10 2: the times 5, 15, 25, 35, 45), which is
# regular with a step of 10 RF raster times: cells. RF 3 (no time shape) uses no block.
TIME_SHAPED = """\
[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

[BLOCKS]
1 20 1 0 0 0 1 0
2 20 2 0 0 0 2 0

[RF]
1 2000 6 2 3 2.5 10 1.5 -2.5 100 0.5 e
2 500 7 8 4 2 0 0 0 0 0 r
3 250 1 2 0 2 0 0 0 0 0 s

[TRAP]
7 1000 10 0 10 0

[ADC]
1 4 25000 10 1.5 -2.5 100 0.5 5
2 4 25000 0 0 0 0 0 0

[SHAPES]

shape_id 1
num_samples 4
0.5
1
1
0.5

shape_id 2
num_samples 4
0
0.25
0.5
0.75

shape_id 3
num_samples 4
0.5
1
2
4

shape_id 4
num_samples 5
5
10
10
2

shape_id 5
num_samples 4
0
0.5
1
1.5

shape_id 6
num_samples 4
0.25
0.5
0.75
1

shape_id 7
num_samples 5
0.2
0.4
0.6
0.8
1

shape_id 8
num_samples 5
0
0.1
0.2
0.3
0.4
"""


@pytest.fixture
def time_shaped(tmp_path):
    path = tmp_path / "time_shaped.seq"
    path.write_text(TIME_SHAPED)
    return seqfile.read_seqfile(path)


def _samples(n, dt):
    """The centres of `n` raster cells of `dt` s, as MATLAB Pulseq gives them."""
    return (np.arange(n) + 0.5) * dt


def _rf_time_shapes():
    """The RF events of `valid_rf_time_shapes.seq` (RF 2 to 5 have each kind of time shape,
    RF 1 has none), by RF ID."""
    return decode_rf(seqfile.read_seqfile(SEQFILES / "valid_rf_time_shapes.seq"))


# ---- Gradients ----


def test_trapezoid_has_the_values_of_the_file():
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert grads[1] == Trapezoid(
        id=1, amplitude=1e6, rise_time=1e-4, flat_time=2e-4, fall_time=1e-4, delay=1e-4
    )
    assert grads[1].shape_dur == 1e-4 + 2e-4 + 1e-4
    assert (grads[1].first, grads[1].last) == (0.0, 0.0)


def test_arbitrary_gradient_on_the_default_raster():
    """Time ID 0: a sample at the centre of each cell of the gradient raster (spec:290, slide 7,
    D2.13)."""
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    samples = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1])
    assert grads[3] == ArbitraryGradient(
        id=3,
        amplitude=5e5,
        shape_id=3,
        time_id=0,
        waveform=5e5 * samples,
        tt=_samples(10, 1e-5),
        shape_dur=10 * 1e-5,
        first=0.0,
        last=5e5,
        delay=4e-4,
    )


def test_arbitrary_gradient_oversampled():
    """Time ID -1: all the samples, half a gradient raster apart, the first at half a raster
    (spec:420, slides 4 and 8)."""
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert grads[6] == ArbitraryGradient(
        id=6,
        amplitude=3e5,
        shape_id=7,
        time_id=-1,
        waveform=3e5 * np.array([0, 0.5, 1, 0.5, 0]),
        tt=np.array([1, 2, 3, 4, 5]) / 2 * 1e-5,
        shape_dur=3 * 1e-5,
        first=0.0,
        last=0.0,
        delay=0.0,
    )


def test_oversampled_gradients_of_a_spiral_keep_all_samples():
    """Time ID -1 in a file with two such gradients (`koma_v1.5_spiral.seq`): an odd number of
    samples, half a raster apart, from the centre of the first cell to the centre of the last
    (spec:420, slides 4 and 8)."""
    data = seqfile.read_seqfile(ORACLE / "koma_v1.5_spiral.seq")
    dt = data.rasters.gradient
    oversampled = [g for g in decode_gradients(data).values() if getattr(g, "time_id", 0) == -1]
    assert [g.id for g in oversampled] == [4, 5]
    for g in oversampled:
        n = g.waveform.size
        assert n % 2 == 1
        np.testing.assert_array_equal(g.tt, np.arange(1, n + 1) / 2 * dt)
        assert g.shape_dur == (n + 1) / 2 * dt


def test_arbitrary_gradient_with_a_time_shape():
    """A time shape: the samples are the vertices, at the shape times times the gradient raster
    (slide 6)."""
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert grads[5] == ArbitraryGradient(
        id=5,
        amplitude=4e5,
        shape_id=5,
        time_id=6,
        waveform=4e5 * np.array([0, 0.25, 0.5, 0.75, 1]),
        tt=np.array([0.0, 1, 3, 6, 10]) * 1e-5,
        shape_dur=10 * 1e-5,
        first=0.0,
        last=4e5,
        delay=0.0,
    )


def test_arbitrary_gradient_with_a_time_shape_in_a_1_4_file():
    """A 1.4 file has no `first` and `last`: the model's values are the amplitude times the
    first and the last sample."""
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_4_1.seq"))
    waveform = 4e5 * np.array([0.2, 0.6, 1, 0.6, 0.2])
    assert grads[2] == ArbitraryGradient(
        id=2,
        amplitude=4e5,
        shape_id=3,
        time_id=4,
        waveform=waveform,
        tt=np.array([0.0, 1, 3, 6, 10]) * 1e-5,
        shape_dur=10 * 1e-5,
        first=float(waveform[0]),
        last=float(waveform[-1]),
        delay=0.0,
    )


def test_gradients_and_trapezoids_are_in_one_mapping_by_id():
    grads = decode_gradients(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert isinstance(grads, MappingProxyType)
    assert sorted(grads) == [1, 2, 3, 4, 5, 6]
    assert isinstance(grads[1], Trapezoid)
    assert all(isinstance(grads[i], ArbitraryGradient) for i in (2, 3, 4, 5, 6))
    assert all(g.id == i for i, g in grads.items())


# ---- RF ----


def test_rf_event_without_a_time_shape():
    """Without a time shape, a sample at the centre of each RF raster cell (spec:290), each held
    for one dwell: the RF raster. The 1.5 file gives the center and the use."""
    (rf,) = decode_rf(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq")).values()
    assert rf == RfEvent(
        id=1,
        amplitude=1000.0,
        mag_id=1,
        phase_id=2,
        time_id=0,
        magnitude=np.full(100, 1000.0),
        phase=np.zeros(100),
        t=_samples(100, 1e-6),
        dwell=1e-6,
        shape_dur=100 * 1e-6,
        center=5e-5,
        delay=1e-4,
        freq_ppm=0.0,
        phase_ppm=0.0,
        freq_offset=0.0,
        phase_offset=0.0,
        use="e",
    )


def test_the_dwell_of_an_rf_event_without_a_time_shape_is_the_rf_raster(tmp_path):
    """Without a time shape the dwell is the RF raster of the file (spec:290), and a time shape
    is in RF rasters (spec:349). The written file has the RF raster 2 us instead of 1 us: RF 3
    (no time shape) has cells of 2 us, RF 2 (regular, step 10) cells of 20 us, and RF 1 (points)
    has its time shape 0.5, 1, 2, 4 times 2 us."""
    path = tmp_path / "raster_2.seq"
    path.write_text(
        TIME_SHAPED.replace("RadiofrequencyRasterTime 1e-06", "RadiofrequencyRasterTime 2e-06")
    )
    rfs = decode_rf(seqfile.read_seqfile(path))
    assert rfs[3].dwell == 2e-6
    np.testing.assert_allclose(rfs[3].t, _samples(4, 2e-6), rtol=1e-12)
    assert rfs[3].shape_dur == pytest.approx(4 * 2e-6, rel=1e-12)
    assert rfs[2].dwell == pytest.approx(20e-6, rel=1e-12)
    assert rfs[1].dwell is None
    np.testing.assert_allclose(rfs[1].t, np.array([0.5, 1, 2, 4]) * 2e-6, rtol=1e-12)
    assert rfs[1].shape_dur == pytest.approx(8e-6, rel=1e-12)


def test_rf_event_of_a_1_4_file_has_no_center():
    (rf,) = decode_rf(seqfile.read_seqfile(SEQFILES / "valid_1_4_0.seq")).values()
    assert rf.center is None
    assert (rf.use, rf.freq_ppm, rf.phase_ppm, rf.delay) == ("u", 0.0, 0.0, 1e-4)
    assert rf.dwell == 1e-6
    np.testing.assert_array_equal(rf.t, _samples(100, 1e-6))
    assert rf.shape_dur == 100 * 1e-6


def test_rf_event_with_an_irregular_time_shape_is_points(time_shaped):
    """A time shape that is not regular (0.5, 1, 2, 4: unequal steps) gives points at the shape
    times times the RF raster, and the pulse ends at the last time (slides 4 and 9, D2.11, D2.12). The
    magnitude is in Hz and the phase in rad (2 pi times the shape); no sample is dropped or
    repeated."""
    rf = decode_rf(time_shaped)[1]
    assert rf == RfEvent(
        id=1,
        amplitude=2000.0,
        mag_id=6,
        phase_id=2,
        time_id=3,
        magnitude=2000.0 * np.array([0.25, 0.5, 0.75, 1]),
        phase=2 * np.pi * np.array([0, 0.25, 0.5, 0.75]),
        t=np.array([0.5, 1, 2, 4]) * 1e-6,
        dwell=None,
        shape_dur=4 * 1e-6,
        center=2.5e-6,
        delay=1e-5,
        freq_ppm=1.5,
        phase_ppm=-2.5,
        freq_offset=100.0,
        phase_offset=0.5,
        use="e",
    )


def test_rf_event_with_a_regular_time_shape(time_shaped):
    """A time shape stored compressed in 4 values (5 10 10 2: the times 5, 15, 25, 35, 45) is
    regular: cells of the step 10 RF raster times, each sample held for one dwell around its
    time, and the pulse lasts `n d` (slide 9, D2.10, D2.12)."""
    rf = decode_rf(time_shaped)[2]
    dwell = 10.0 * 1e-6
    assert rf == RfEvent(
        id=2,
        amplitude=500.0,
        mag_id=7,
        phase_id=8,
        time_id=4,
        magnitude=500.0 * np.array([0.2, 0.4, 0.6, 0.8, 1]),
        phase=2 * np.pi * np.array([0, 0.1, 0.2, 0.3, 0.4]),
        t=(np.arange(5) + 0.5) * dwell,
        dwell=dwell,
        shape_dur=5 * dwell,
        center=2e-6,
        delay=0.0,
        freq_ppm=0.0,
        phase_ppm=0.0,
        freq_offset=0.0,
        phase_offset=0.0,
        use="r",
    )


def test_rf_event_with_a_regular_time_shape_of_step_2_is_cells_of_two_rasters():
    """RF 2 of `valid_rf_time_shapes.seq`: the time shape `1 2 2 47` (50 samples, times 1, 3, ...,
    99) is cells of 2 us, the pulse lasts 100 us, not 99 us (slide 9, D2.10, D2.12)."""
    rf = _rf_time_shapes()[2]
    assert rf.dwell == pytest.approx(2e-6, rel=1e-12)
    np.testing.assert_allclose(rf.t, _samples(50, 2e-6), rtol=1e-12)
    assert rf.shape_dur == pytest.approx(100e-6, rel=1e-12)
    np.testing.assert_array_equal(rf.magnitude, np.full(50, 1000.0))


def test_rf_event_with_the_time_shape_of_a_short_pulse_is_cells_of_one_raster():
    """RF 3 of `valid_rf_time_shapes.seq`: the uncompressed time shape 0.5, 1.5, 2.5 (3 samples)
    is cells of 1 us, the pulse lasts 3 us (slide 9, D2.10, D2.12)."""
    rf = _rf_time_shapes()[3]
    assert rf.dwell == pytest.approx(1e-6, rel=1e-12)
    np.testing.assert_allclose(rf.t, [0.5e-6, 1.5e-6, 2.5e-6], rtol=1e-12)
    assert rf.shape_dur == pytest.approx(3e-6, rel=1e-12)
    np.testing.assert_array_equal(rf.magnitude, [1000.0, 500.0, 250.0])


def test_rf_event_of_a_block_pulse_is_two_points():
    """RF 4 of `valid_rf_time_shapes.seq`: the time shape 0, 100 with the magnitude 1, 1 is two
    points, 0 and 100 us, and no cells: the pulse ends at 100 us (slides 4 and 9, D2.11, D2.12)."""
    rf = _rf_time_shapes()[4]
    assert rf.dwell is None
    np.testing.assert_allclose(rf.t, [0.0, 100e-6], rtol=1e-12)
    assert rf.shape_dur == pytest.approx(100e-6, rel=1e-12)
    np.testing.assert_array_equal(rf.magnitude, [1000.0, 1000.0])


def test_rf_event_with_vertices_is_points():
    """RF 5 of `valid_rf_time_shapes.seq`: the time shape 1, 2, 4, 7, 10 (5 samples) is 5 points,
    at 1, 2, 4, 7 and 10 us, and the pulse ends at 10 us (slides 4 and 9, D2.11, D2.12). The phase is 2 pi
    times the shape turns."""
    rf = _rf_time_shapes()[5]
    assert rf.dwell is None
    np.testing.assert_allclose(rf.t, np.array([1, 2, 4, 7, 10]) * 1e-6, rtol=1e-12)
    assert rf.shape_dur == pytest.approx(10e-6, rel=1e-12)
    np.testing.assert_allclose(rf.magnitude, 1000.0 * np.array([0.2, 0.6, 1, 0.6, 0.2]))
    np.testing.assert_allclose(rf.phase, 2 * np.pi * np.array([0, 0.25, 0.5, 0.25, 0]))


def test_the_signal_of_cells_holds_each_sample_over_its_cell_and_is_0_outside():
    """RF 3 of `valid_rf_time_shapes.seq` (cells of 1 us: 1000, 500, 250 Hz): each sample is
    held from `i dwell` to `(i + 1) dwell`, and the signal is 0 before the start and from the
    end (slide 9, D2.10 to D2.12). RF 2 (cells of 2 us) gives the same at its start and its end."""
    rfs = _rf_time_shapes()
    times = np.array([-0.5, 0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5]) * 1e-6
    np.testing.assert_array_equal(rfs[3].signal(times), [0, 1000, 1000, 500, 500, 250, 250, 0, 0])
    times = np.array([-1, 0, 1, 99, 101]) * 1e-6
    np.testing.assert_array_equal(rfs[2].signal(times), [0, 1000, 1000, 1000, 0])


def test_the_signal_of_cells_is_the_complex_sample(time_shaped):
    """A cell holds the complex sample `magnitude * exp(1j * phase)`, the phase included. RF 2
    of the written file has cells of 10 us, and the sample 1 has the magnitude 200 Hz and the
    phase 2 pi 0.1."""
    rf = decode_rf(time_shaped)[2]
    expected = 200.0 * np.exp(1j * 2 * np.pi * 0.1)
    np.testing.assert_allclose(
        rf.signal(np.array([12e-6, 19e-6])), [expected, expected], rtol=1e-12
    )


def test_the_signal_of_cells_puts_each_cell_boundary_in_the_cell_after_it():
    """A pulse of 5000 cells of 1 us, each with its own sample: the boundary `k dwell`, computed
    as `decode_rf` computes `shape_dur = n dwell`, is in the cell `k` (the end, `n dwell`, gives
    0), although `k dwell / dwell` is a hair under `k` for some `k`. A time 2e-6 dwells below the
    boundary is still in the cell `k - 1`."""
    n, dwell = 5000, 1e-6
    samples = 1.0 + np.arange(n)
    rf = RfEvent(
        id=1,
        amplitude=1.0,
        mag_id=1,
        phase_id=2,
        time_id=0,
        magnitude=samples,
        phase=np.zeros(n),
        t=_samples(n, dwell),
        dwell=dwell,
        shape_dur=n * dwell,
        center=None,
        delay=0.0,
        freq_ppm=0.0,
        phase_ppm=0.0,
        freq_offset=0.0,
        phase_offset=0.0,
        use="e",
    )
    below = (np.arange(1, n + 1) - 2e-6) * dwell
    np.testing.assert_array_equal(rf.signal(below), samples)
    boundaries = np.arange(n + 1) * dwell
    np.testing.assert_array_equal(rf.signal(boundaries), np.append(samples, 0))


def test_the_signal_of_points_is_the_straight_line_of_the_complex_signal():
    """RF 5 of `valid_rf_time_shapes.seq`: between two points the signal is the straight line of
    the complex signal (linear interpolation of the real and the imaginary part, D2.11). The
    samples at 2 us (0.6 at the phase 0.25 turn) and 4 us (1 at 0.5 turn) are 600j and -1000
    Hz: at 3 us the signal is their average, -500 + 300j (583 Hz), and not the average
    magnitude, 800 Hz, with the average phase."""
    rf = _rf_time_shapes()[5]
    times = np.array([1e-6, 2e-6, 3e-6, 4e-6, 5.5e-6, 7e-6])
    expected = [200, 600j, (600j - 1000) / 2, -1000, (-1000 + 600j) / 2, 600j]
    np.testing.assert_allclose(rf.signal(times), expected, atol=1e-9)
    assert abs(rf.signal(np.array([3e-6]))[0]) == pytest.approx(np.hypot(500, 300))
    assert abs(rf.signal(np.array([3e-6]))[0]) != pytest.approx(800)


def test_the_signal_of_points_is_0_before_the_first_point_and_after_the_last():
    """The signal of points is 0 before the first point (RF 5: 1 us; RF 4: 0) and after the last
    point (RF 5: 10 us; RF 4: 100 us); RF 4, the block pulse, is the constant 1000 Hz between
    its two points (slides 4 and 9)."""
    rfs = _rf_time_shapes()
    times = np.array([-1e-6, 0, 0.5e-6, 1e-6, 10.5e-6, 11e-6])
    np.testing.assert_array_equal(rfs[5].signal(times), [0, 0, 0, 200, 0, 0])
    times = np.array([-1, 0, 50, 100.5]) * 1e-6
    np.testing.assert_array_equal(rfs[4].signal(times), [0, 1000, 1000, 0])


@pytest.mark.parametrize(
    ("num_samples", "packed", "step"),
    [
        (100, [0.5, 1, 1, 97], 1.0),  # 0.5 1 1 N-3: the times 0.5, 1.5, ..., 99.5
        (50, [1, 2, 2, 47], 2.0),  # 1 2 2 N-3: the times 1, 3, ..., 99
        (3, [0.5, 1.5, 2.5], 1.0),  # uncompressed
        (5, [1, 1, 3], None),  # 1 1 N-2: the times 1 to 5, the first is a whole step
        (2, [0, 100], None),  # a block pulse as MATLAB writes it
        (5, [1, 2, 4, 7, 10], None),  # vertices
        (4, [0.5, 1, 2, 4], None),  # unequal steps
        (1, [0.5], 1.0),  # one sample t0 above 0: one cell of 2 t0 (D3.9)
        (1, [5], 10.0),  # MATLAB's arbitrary pulse of one sample on a dwell of 10 rasters
        (1, [0], None),  # one sample at 0: no cell
        (1, [-1], None),  # one sample below 0
        (3, [2.5, 1.5, 0.5], None),  # decreasing times
        (2, [0.5, 0.5], None),  # a step of 0
    ],
)
def test_rf_time_step_of_a_time_shape(num_samples, packed, step):
    """A regular RF time shape (2 or more samples, equal steps, the first time half a step, or one
    sample above 0, D3.9) gives its step in RF rasters: cells; any other shape gives `None`:
    points (slide 9, D2.10 to D2.12). The shape is stored as in a file and decompressed."""
    shape = model.Shape(num_samples=num_samples, packed=np.array(packed, dtype=float))
    result = model.rf_time_step(shape.samples())
    if step is None:
        assert result is None
    else:
        assert result == pytest.approx(step, rel=1e-12)


@pytest.mark.parametrize(
    ("shift", "regular"),
    [
        ([0, 0, 0.4, 0, 0], True),  # one time late by less than the tolerance
        ([0, 0, 3, 0, 0], False),  # one time late by more
        ([0.4] * 5, True),  # all the times late by less than the tolerance
        ([3] * 5, False),  # all the times late by more: the first is not half a step
    ],
)
def test_rf_time_step_has_the_tolerance_of_the_model(shift, regular):
    """The steps are equal, and the first time is half a step, to within
    `model.RF_TIME_SHAPE_TOLERANCE` RF raster times. The times 0.5, 1.5, ..., 4.5 are late by
    `shift` times the tolerance."""
    times = np.arange(5) + 0.5 + np.array(shift) * model.RF_TIME_SHAPE_TOLERANCE
    result = model.rf_time_step(times)
    if regular:
        assert result == pytest.approx(1.0, abs=model.RF_TIME_SHAPE_TOLERANCE)
    else:
        assert result is None


def test_the_tolerance_of_an_rf_time_shape_is_named_for_rf_time_shapes():
    """The tolerance of `model.rf_time_step` is `model.RF_TIME_SHAPE_TOLERANCE`, 1e-6 RF raster
    times, and the model has no `TIME_TOLERANCE`, the old name, which `seq_utils` also has for
    a tolerance of 1e-9 s (Q21)."""
    from pulseq_analysis.seqfile.model import RF_TIME_SHAPE_TOLERANCE

    assert RF_TIME_SHAPE_TOLERANCE == 1e-6
    with pytest.raises(AttributeError):
        _ = model.TIME_TOLERANCE


def test_rf_event_with_a_time_shape_in_a_1_4_file():
    """The block pulse of the file has the magnitude 1, 1 at the times 0, 100: two points, 0 and
    100 us, and no cells (slides 4 and 9, D2.11)."""
    (rf,) = decode_rf(seqfile.read_seqfile(ORACLE / "koma_v1.4_rf-time-shaped.seq")).values()
    np.testing.assert_array_equal(rf.magnitude, np.full(2, 2500.0))
    np.testing.assert_array_equal(rf.phase, np.zeros(2))
    assert rf.dwell is None
    np.testing.assert_allclose(rf.t, [0.0, 100e-6], rtol=1e-12)
    assert rf.shape_dur == pytest.approx(100e-6, rel=1e-12)
    assert rf.center is None


# ---- ADC ----


def test_adc_events_with_and_without_a_phase_shape(time_shaped):
    """The phase modulation is the shape as the file stores it, in rad, with no factor (D2.15)."""
    adcs = decode_adc(time_shaped)
    assert isinstance(adcs, MappingProxyType)
    assert adcs[1] == AdcEvent(
        id=1,
        num_samples=4,
        dwell=2.5e-5,
        delay=1e-5,
        freq_ppm=1.5,
        phase_ppm=-2.5,
        freq_offset=100.0,
        phase_offset=0.5,
        phase_shape_id=5,
        phase_modulation=np.array([0, 0.5, 1, 1.5]),
    )
    assert adcs[2].phase_shape_id == 0
    assert adcs[2].phase_modulation is None


def test_adc_phase_modulation_has_one_value_for_each_sample():
    """ADC 2 of `valid_1_5_1.seq` has the phase shape 8 (8 samples, all 0) and 8 ADC samples: the
    modulation is in rad and has `num_samples` values (D2.15)."""
    adc = decode_adc(seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq"))[2]
    assert adc.num_samples == 8
    np.testing.assert_array_equal(adc.phase_modulation, np.zeros(8))


def test_adc_phase_modulation_is_the_shape_with_no_factor_and_no_wrap(tmp_path):
    """ADC 2 of `valid_no_signature.seq` (8 samples) with its phase shape 8 written as the phases
    0, 0.5, ..., 3.5: the modulation is these 8 values in rad, with no factor, and the values
    above pi are not wrapped (D2.15)."""
    text = (SEQFILES / "valid_no_signature.seq").read_text()
    old = "shape_id 8\nnum_samples 8\n0\n0\n6\n"
    assert old in text
    values = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5]
    new = "shape_id 8\nnum_samples 8\n" + "\n".join(map(str, values)) + "\n"
    path = tmp_path / "adc_phase.seq"
    path.write_text(text.replace(old, new))
    assert decode_adc(seqfile.read_seqfile(path))[2].phase_modulation.tolist() == values


# ---- All events ----


def test_each_row_is_decoded_whether_a_block_uses_it_or_not(time_shaped):
    assert list(decode_rf(time_shaped)) == [1, 2, 3]
    assert list(decode_gradients(time_shaped)) == [7]
    assert list(decode_adc(time_shaped)) == [1, 2]
    rf = decode_rf(time_shaped)[3]
    np.testing.assert_array_equal(rf.magnitude, [125.0, 250, 250, 125])
    assert decode_gradients(time_shaped)[7].shape_dur == 1e-5 + 0.0 + 1e-5


def test_a_shape_that_several_events_use_is_decompressed_once(time_shaped, monkeypatch):
    """The three RF events use the shapes 1, 2 (twice), 3, 6, 7 and 8, and the time shape 4,
    which is decompressed to find its step. Seven decompressions."""
    calls = []
    samples = model.Shape.samples

    def counted(shape):
        calls.append(shape)
        return samples(shape)

    monkeypatch.setattr(model.Shape, "samples", counted)
    decode_rf(time_shaped)
    assert len(calls) == 7


def test_events_are_read_only_equal_by_value_and_pickle(time_shaped):
    for decode in (decode_rf, decode_gradients, decode_adc):
        events = decode(time_shaped)
        again = decode(time_shaped)
        for i, event in events.items():
            assert event == again[i]
            assert event is not again[i]
            assert pickle.loads(pickle.dumps(event)) == event
            for value in (getattr(event, name) for name in event.__dataclass_fields__):
                if isinstance(value, np.ndarray):
                    assert not value.flags.writeable
                    with pytest.raises(ValueError):
                        value.flags.writeable = True
    rf = decode_rf(time_shaped)[1]
    with pytest.raises(AttributeError):
        rf.amplitude = 1.0


def test_synth_decode_gives_the_events_of_spec():
    """`synth.decode` of the model of `spec` is a `SpecDecoding` with the interpreter and the
    gradient events of `decode_gradients`."""
    data = seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq")
    decoding = synth.decode(data)
    assert isinstance(decoding, synth.SpecDecoding)
    assert decoding.interpreter == interpreters.Spec()
    assert decoding.gradients == decode_gradients(data)


FILES = sorted(SEQFILES.glob("valid_*.seq")) + sorted(ORACLE.glob("*.seq"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_file_that_loads_decodes(path):
    """Each event has the values of its row of the model, its arrays have one sample for each
    sample of its shape, an RF event is cells or points as its time shape says (slide 9, D2.10 to
    D2.12) and its signal at its sample times is its samples, an ADC phase modulation has one value
    for each ADC sample (D2.15), and an RF or gradient event ends inside each block that plays it."""
    try:
        data = seqfile.read_seqfile(path)
    except SeqFileError as error:
        pytest.skip(
            f"the spec interpreter rejects the file: {sorted({v.rule for v in error.violations})}"
        )
    except NotSupported:
        pytest.skip("the version is outside 1.4.0-1.5.x")
    rfs, grads, adcs = decode_rf(data), decode_gradients(data), decode_adc(data)
    assert list(rfs) == data.rf["id"].tolist()
    assert list(adcs) == data.adc["id"].tolist()
    assert list(grads) == data.grad["id"].tolist() + data.trap["id"].tolist()

    for row in data.rf:
        rf = rfs[int(row["id"])]
        for name in ("amplitude", "mag_id", "phase_id", "time_id", "delay", "use"):
            assert getattr(rf, name) == row[name]
        assert type(rf.amplitude) is float and type(rf.mag_id) is int and type(rf.use) is str
        n = data.shapes[int(row["mag_id"])].num_samples
        time_id = int(row["time_id"])
        assert rf.magnitude.shape == rf.phase.shape == rf.t.shape == (n,)
        step = model.rf_time_step(data.shapes[time_id].samples()) if time_id > 0 else 1.0
        if step is None:
            assert rf.dwell is None
            assert rf.shape_dur == rf.t[-1]
        else:
            assert rf.dwell == step * data.rasters.rf
            assert rf.shape_dur == n * rf.dwell
            assert rf.t[-1] < rf.shape_dur
        np.testing.assert_allclose(
            rf.signal(rf.t), rf.magnitude * np.exp(1j * rf.phase), rtol=1e-12, atol=1e-9
        )
        assert (rf.center is None) == (data.version < (1, 5, 0))
    for row in data.grad:
        g = grads[int(row["id"])]
        for name in ("amplitude", "first", "last", "shape_id", "time_id", "delay"):
            assert getattr(g, name) == row[name]
        n = data.shapes[int(row["shape_id"])].num_samples
        assert g.waveform.shape == g.tt.shape == (n,)
        assert g.tt[-1] <= g.shape_dur
    for row in data.trap:
        g = grads[int(row["id"])]
        assert (g.amplitude, g.rise_time, g.flat_time, g.fall_time, g.delay) == (
            row["amplitude"],
            row["rise"],
            row["flat"],
            row["fall"],
            row["delay"],
        )
    for row in data.adc:
        adc = adcs[int(row["id"])]
        for name in ("num_samples", "dwell", "delay", "freq_offset", "phase_shape_id"):
            assert getattr(adc, name) == row[name]
        assert (adc.phase_modulation is None) == (row["phase_shape_id"] == 0)
        if adc.phase_modulation is not None:
            assert adc.phase_modulation.shape == (adc.num_samples,)

    durations = data.block_durations_s
    for column, events in (("rf", rfs), ("gx", grads), ("gy", grads), ("gz", grads)):
        for i, event_id in enumerate(data.blocks[column].tolist()):
            if event_id:
                event = events[event_id]
                assert event.delay + event.shape_dur <= durations[i] + 1e-12


RADIAL = ORACLE / "koma_v1.5_rotation_radial_tiny.seq"


def test_spec_gradients_at_are_the_lines_between_the_points_of_each_event():
    """`SpecDecoding.gradients_at` (Hz/m) at block-relative times in us: the trapezoid of block
    2 of valid_1_4_1.seq (1e6 Hz/m, delay 100 us, rise 100 us, flat 200 us, fall 100 us, block
    500 us) on gx; 0 before the delay, after the event and outside the block. The arguments are
    checked as for a plugin interpreter's decoding."""
    decoding = synth.decode(seqfile.read_seqfile(SEQFILES / "valid_1_4_1.seq"))
    assert decoding.block_count == 4
    times = [-1.0, 50.0, 150.0, 250.0, 450.0, 500.0, 501.0]
    values = decoding.gradients_at(np.ones(7, int), times)
    assert values.shape == (7, 3)
    np.testing.assert_allclose(values[:, 0], [0, 0, 0.5e6, 1e6, 0.5e6, 0, 0], atol=1e-6)
    assert not values[:, 1:].any()
    assert decoding.gradients_at([], []).shape == (0, 3)
    with pytest.raises(ValueError, match="differ in length"):
        decoding.gradients_at([1, 1], [0.0])
    with pytest.raises(ValueError, match="NaN"):
        decoding.gradients_at([1], [np.nan])
    for index in (-1, 4):
        with pytest.raises(IndexError):
            decoding.gradients_at([index], [0.0])


def test_rotate_is_the_active_rotation_of_a_unit_quaternion():
    """`decoding.rotate` turns a vector by `R(q) v` with q0 the scalar part: a quarter turn
    about z takes x to y, about x takes y to z, about y takes z to x; the identity keeps the
    vector; and the result is `q v q*` computed with the Hamilton product."""
    s = np.sqrt(0.5)
    quarter = np.array([[s, 0, 0, s], [s, s, 0, 0], [s, 0, s, 0], [1, 0, 0, 0]])
    vectors = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0], [1.0, 2.0, 3.0]])
    expected = np.array([[0, 1.0, 0], [0, 0, 1.0], [1.0, 0, 0], [1.0, 2.0, 3.0]])
    np.testing.assert_allclose(synth.decoding.rotate(quarter, vectors), expected, atol=1e-15)

    def product(a, b):
        w1, v1, w2, v2 = a[0], a[1:], b[0], b[1:]
        return np.concatenate([[w1 * w2 - v1 @ v2], w1 * v2 + w2 * v1 + np.cross(v1, v2)])

    rng = np.random.default_rng(0)
    q = rng.normal(size=(20, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    v = rng.normal(size=(20, 3))
    conjugate = q * [1, -1, -1, -1]
    hamilton = [product(product(q[i], np.r_[0, v[i]]), conjugate[i])[1:] for i in range(20)]
    np.testing.assert_allclose(synth.decoding.rotate(q, v), hamilton, rtol=0, atol=1e-12)


def test_spec_rotates_the_gradients_of_each_block_that_has_a_rotation(recwarn):
    """From 1.5.1 `spec` rotates each block's gradients by its normalized quaternion (D2.18, P20
    rule 2): blocks 1 to 5 of the radial file are turned by 0, 45, 90, 45 and 0 degrees about z.
    `rotated` None is True; False gives the logical gradients, all on x. The record has the
    setting "apply", every block with a rotation rotated, and no warning; the decoding emits
    none (P20 rule 4)."""
    decoding = synth.decode(seqfile.read_seqfile(RADIAL))
    indices, quaternions = decoding.rotations()
    assert indices.tolist() == [0, 1, 2, 3, 4]
    np.testing.assert_allclose(np.linalg.norm(quaternions, axis=1), 1, rtol=0, atol=1e-15)
    block_index = np.repeat(np.arange(5), 4)
    time_us = np.tile([50.0, 150.0, 200.0, 350.0], 5)
    logical = decoding.gradients_at(block_index, time_us, rotated=False)
    rotated = decoding.gradients_at(block_index, time_us)
    assert np.array_equal(rotated, decoding.gradients_at(block_index, time_us, rotated=True))
    assert np.array_equal(logical[:, 1:], np.zeros((20, 2))) and logical[:, 0].any()
    angle = np.radians(np.repeat([0, 45, 90, 45, 0], 4))
    expected = logical[:, :1] * np.stack([np.cos(angle), np.sin(angle), 0 * angle], axis=1)
    np.testing.assert_allclose(rotated, expected, rtol=0, atol=1e-3)
    record = decoding.rotation_record
    assert record == synth.RotationRecord("apply", blocks=5, not_identity=3, rotated=5)
    assert record.warning() is None and str(record) == "rotation: apply, 5 block(s) rotated"
    assert not [w for w in recwarn if issubclass(w.category, synth.ScannerSettingWarning)]
    # A file with no rotation that a block plays rotates 0 blocks.
    for name in ("valid_1_5_1_rotation_not_played.seq", "valid_1_4_1.seq"):
        record = synth.decode(seqfile.read_seqfile(SEQFILES / name)).rotation_record
        assert record == synth.RotationRecord("apply", 0, 0, 0)


def _with_rotation_1_4_1(tmp_path: Path) -> Path:
    """valid_1_4_1.seq with a ROTATIONS object (45 degrees about z) in the extension list of
    block 2, which plays a trapezoid on gx."""
    text = (SEQFILES / "valid_1_4_1.seq").read_text()
    assert "[EXTENSIONS]\n1 1 1 0\n" in text and "\n[SHAPES]" in text
    text = text.replace("[EXTENSIONS]\n1 1 1 0\n", "[EXTENSIONS]\n1 1 1 3\n3 3 1 0\n")
    text = text.replace(
        "\n[SHAPES]", "\nextension ROTATIONS 3\n1 0.92388 0 0 0.382683\n\n[SHAPES]", 1
    )
    path = tmp_path / "rotation_1_4_1.seq"
    path.write_text(text)
    return path


def test_a_file_older_than_1_5_1_with_rotations_is_not_rotated(tmp_path):
    """Before 1.5.1 ROTATIONS is an unknown extension for `spec` (P20 rule 2, D4.6): ignored and
    recorded, no block has a rotation, and the gradients are the logical ones, in a 1.5.0 file
    (block 5 plays gx with a ROTATIONS object) and in a 1.4.1 file."""
    for path, block in (
        (SEQFILES / "valid_1_5_0_extensions_of_1_5_1.seq", 4),
        (_with_rotation_1_4_1(tmp_path), 1),
    ):
        data = seqfile.read_seqfile(path)
        assert data.version < (1, 5, 1)
        assert model.Record("extension", "ROTATIONS", "version", 0) in [
            model.Record(r.kind, r.subject, r.reason, 0) for r in data.records
        ]
        decoding = synth.decode(data)
        indices, quaternions = decoding.rotations()
        assert indices.size == 0 and quaternions.shape == (0, 4)
        assert decoding.rotation_record == synth.RotationRecord("apply", 0, 0, 0)
        times = np.linspace(0.05, 0.95, 10) * decoding.block_durations[block] * 1e6
        values = decoding.gradients_at(np.full(10, block), times)
        assert values[:, 0].any()
        assert np.array_equal(values, decoding.gradients_at(np.full(10, block), times, False))


def test_the_rotation_ids_of_spec_are_int64_as_every_other_id():
    """The `id` of the ROTATIONS table that `spec` makes is int64, as the `id` of every other
    table of the model (1.2.4a of `docs/reviews/2026-10-13-code-review.md`): the rotation of
    `valid_1_5_1.seq` has the ID 1."""
    data = seqfile.read_seqfile(SEQFILES / "valid_1_5_1.seq")
    ext = data.extensions
    rotations = ext.rotations
    assert rotations.dtype["id"] == np.int64
    assert rotations["id"].tolist() == [1]
    tables = (data.blocks, data.rf, data.grad, data.trap, data.adc, ext.entries, ext.triggers)
    tables += (ext.labelset, ext.labelinc, ext.soft_delays, rotations)
    assert {table.dtype["id"] for table in tables} == {np.dtype(np.int64)}


_HEADER_1_5_1 = """\
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


def _many_trapezoids(path: Path, blocks: int, traps: int, seed: int) -> Path:
    """A 1.5.1 file of `blocks` blocks of 500 us, each with a trapezoid of the `traps` (random
    amplitude, ramps and flat time, delay of 0 to 100 us, all in 500 us) on each axis, or none
    (one cell in five), and a ROTATIONS object (one of 50 random quaternions) in the extension
    list of one block in two."""
    rng = np.random.default_rng(seed)
    cells = rng.integers(1, traps + 1, size=(blocks, 3))
    cells[rng.random((blocks, 3)) < 0.2] = 0
    rotation = np.where(rng.random(blocks) < 0.5, rng.integers(1, 51, size=blocks), 0)
    lines = [_HEADER_1_5_1, "[BLOCKS]"]
    lines += [
        f"{i + 1} 50 0 {x} {y} {z} 0 {r}"
        for i, ((x, y, z), r) in enumerate(zip(cells.tolist(), rotation.tolist(), strict=True))
    ]
    lines += ["", "[TRAP]"]
    for i in range(1, traps + 1):
        rise, flat, fall, delay = (10 * rng.integers([1, 0, 1, 0], [11, 21, 11, 11])).tolist()
        lines.append(f"{i} {rng.uniform(-1e5, 1e5):.3f} {rise} {flat} {fall} {delay}")
    lines += ["", "[EXTENSIONS]"]
    lines += [f"{j} 1 {j} 0" for j in range(1, 51)]
    lines += ["", "extension ROTATIONS 1"]
    lines += [f"{j} " + " ".join(f"{q:.6f}" for q in rng.normal(size=4)) for j in range(1, 51)]
    path.write_text("\n".join(lines) + "\n")
    return path


def _gradients_one_read_at_a_time(decoding, block_index, time_us):
    """`gradients_at` of `spec` under the neutral session, one read at a time: the logical
    gradients (the straight lines of `gradient_offsets` of each cell's event, 0 outside the
    block), and those turned by the quaternion of each block with a rotation."""
    indices, quaternions = decoding.rotations()
    quaternion_of = dict(zip(indices.tolist(), quaternions, strict=True))
    logical = np.zeros((block_index.size, 3))
    for k, (b, us) in enumerate(zip(block_index.tolist(), time_us.tolist(), strict=True)):
        t = us * 1e-6
        if t < 0 or t > decoding.block_durations[b]:
            continue
        for axis, column in enumerate(("gx", "gy", "gz")):
            gid = int(decoding.blocks[column][b])
            if gid:
                delay, offsets, amp = gradient_offsets(decoding.gradients[gid])
                logical[k, axis] = np.interp(t - delay, offsets, amp, left=0.0, right=0.0)
    rotated = logical.copy()
    for k, b in enumerate(block_index.tolist()):
        if b in quaternion_of:
            rotated[k] = synth.decoding.rotate(quaternion_of[b][None], logical[k][None])[0]
    return logical, rotated


def test_spec_gradients_at_of_many_events_is_each_read_alone(tmp_path):
    """`SpecDecoding.gradients_at` of many reads of many events (C10 of
    `docs/plans/remaining-review-fixes.md`, 2.1 of `docs/reviews/2026-10-13-code-review.md`) is,
    bit for bit, the value of each read alone: 3000 blocks of 1500 trapezoids, one block in two
    with a rotation, and 20 000 reads in random order, with repeats, at random times and at times
    on the 10 us raster, from 50 us before each block to 50 us after it."""
    path = _many_trapezoids(tmp_path / "many.seq", blocks=3000, traps=1500, seed=10)
    decoding = synth.decode(seqfile.read_seqfile(path))
    assert decoding.block_count == 3000
    assert np.unique(decoding.blocks[["gx", "gy", "gz"]].tolist()).size > 1400
    assert 1300 < decoding.rotation_blocks.size < 1700
    rng = np.random.default_rng(11)
    block_index = rng.integers(0, 3000, size=20_000)
    time_us = np.where(
        rng.random(20_000) < 0.5, rng.uniform(-50, 550, 20_000), 10.0 * rng.integers(-5, 56, 20_000)
    )
    logical, rotated = _gradients_one_read_at_a_time(decoding, block_index, time_us)
    assert logical.any(axis=1).mean() > 0.3 and not logical[(time_us < 0) | (time_us > 500)].any()
    assert np.array_equal(decoding.gradients_at(block_index, time_us, rotated=False), logical)
    assert np.array_equal(decoding.gradients_at(block_index, time_us), rotated)


def test_spec_gradients_at_allocates_no_array_of_the_size_of_the_sequence(tmp_path):
    """A call of `SpecDecoding.gradients_at` with one read allocates nothing in proportion to the
    blocks (3 of 2.1 of `docs/reviews/2026-10-13-code-review.md`, C10): in a file of 100 000
    blocks, the first of which has a rotation, the peak of `tracemalloc` over the second call is
    below 100 kB, with the rotations (`rotated` None and True) and without them. A map of 8 bytes
    for each block is 800 kB."""
    blocks = 100_000
    lines = [_HEADER_1_5_1, "[BLOCKS]", "1 50 0 1 0 0 0 1"]
    lines += [f"{i} 50 0 1 0 0 0 0" for i in range(2, blocks + 1)]
    lines += ["", "[TRAP]", "1 1000 100 200 100 0", "", "[EXTENSIONS]", "1 1 1 0", ""]
    lines += ["extension ROTATIONS 1", "1 0.92388 0 0 0.382683"]
    path = tmp_path / "long.seq"
    path.write_text("\n".join(lines) + "\n")
    decoding = synth.decode(seqfile.read_seqfile(path))
    assert decoding.block_count == blocks
    turned = 1000 * np.sqrt(0.5)
    for rotated in (False, None, True):
        decoding.gradients_at([0], [250.0], rotated)
        tracemalloc.start()
        try:
            values = decoding.gradients_at([0], [250.0], rotated)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        expected = [1000, 0, 0] if rotated is False else [turned, turned, 0]
        np.testing.assert_allclose(values, [expected], rtol=0, atol=1e-2)
        assert peak < 100e3, (rotated, peak)


def test_load_decodes_no_rf_event(tmp_path, monkeypatch):
    """`load` builds no `RfEvent` and no `AdcEvent` (C16 of `docs/plans/remaining-review-fixes.md`,
    2.4 of `docs/reviews/2026-10-13-code-review.md`): no analysis reads them, and a caller
    decodes them with `decode_rf(snap.data)` and `decode_adc(snap.data)`. Of the file of
    `time_shaped` (3 RF and 2 ADC events), those two calls after `load` build each event once."""
    path = tmp_path / "time_shaped.seq"
    path.write_text(TIME_SHAPED)
    built = []

    def counted(cls):
        def make(*args, **kwargs):
            built.append(cls.__name__)
            return cls(*args, **kwargs)

        return make

    monkeypatch.setattr("pulseq_analysis.synth.events.RfEvent", counted(RfEvent))
    monkeypatch.setattr("pulseq_analysis.synth.events.AdcEvent", counted(AdcEvent))
    snap = analyses.load(path)
    assert built == []
    assert sorted(decode_rf(snap.data)) == [1, 2, 3]
    assert sorted(decode_adc(snap.data)) == [1, 2]
    assert built == ["RfEvent"] * 3 + ["AdcEvent"] * 2


def _labelled(path: Path, third: str) -> Path:
    """A 1.5.1 file of four blocks of a trapezoid on gx and three LABELSET objects: 1 (LIN 1) and
    2 (LIN 2) in the extension list of blocks 1 and 3, and 3 (`third`, set to 1) in the list of
    block 2 (play order from 0)."""
    lines = [_HEADER_1_5_1, "[BLOCKS]"]
    lines += [f"{i + 1} 50 0 1 0 0 0 {ext}" for i, ext in enumerate((0, 1, 3, 1))]
    lines += ["", "[TRAP]", "1 1000 100 200 100 0", ""]
    lines += ["[EXTENSIONS]", "1 1 1 2", "2 1 2 0", "3 1 3 0", ""]
    lines += ["extension LABELSET 1", "1 1 LIN", "2 2 LIN", f"3 1 {third}"]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_spec_walks_the_lists_only_for_the_labels_of_the_field_of_view(tmp_path, monkeypatch):
    """`spec`'s decoding walks the extension lists for the LABELSET objects NOROT and NOSLC only
    (C16 of `docs/plans/remaining-review-fixes.md`, 2.4 of
    `docs/reviews/2026-10-13-code-review.md`): of a file whose LABELSET objects are LIN only, it
    walks no list for LABELSET, and every flag is False; when the third object is NOROT, the walk
    for LABELSET gives that object alone, in block 2, and NOROT is set from block 2 on."""
    walks = []
    walk = synth.decoding._extension_objects

    def counted(data, string_id, *args, **kwargs):
        found = walk(data, string_id, *args, **kwargs)
        walks.append((string_id, found))
        return found

    monkeypatch.setattr(synth.decoding, "_extension_objects", counted)
    decoding = synth.decode(seqfile.read_seqfile(_labelled(tmp_path / "lin.seq", "LIN")))
    assert walks == []
    norot, noscale = decoding.fov_flags()
    assert not norot.any() and not noscale.any()
    decoding = synth.decode(seqfile.read_seqfile(_labelled(tmp_path / "norot.seq", "NOROT")))
    assert walks == [("LABELSET", [(2, 3)])]
    norot, noscale = decoding.fov_flags()
    assert norot.tolist() == [False, False, True, True] and not noscale.any()
