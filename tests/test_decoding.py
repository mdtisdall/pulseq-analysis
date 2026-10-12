import pickle
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from pulseq_analysis import model
from pulseq_analysis.events import (
    AdcEvent,
    ArbitraryGradient,
    RfEvent,
    Trapezoid,
    decode_adc,
    decode_gradients,
    decode_rf,
)
from pulseq_analysis.seqfile import SeqFileError, read_seqfile

SEQFILES = Path(__file__).resolve().parent / "seqfiles"
ORACLE = SEQFILES / "oracle"

# A 1.5.1 file with RF time shapes, an ADC phase shape, and an RF event and a trapezoid that no
# block uses. RF 1 has the time shape 3 (0.5, 1, 2, 4), which the scanner's reader resamples to
# the RF raster. RF 2 has the time shape 4, stored compressed in 4 values (5 10 10 2: the times
# 5, 15, 25, 35, 45), which the reader takes as regular with a step of 10 RF raster times. RF 3
# (no time shape) uses no block.
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
    return read_seqfile(path)


def _samples(n, dt):
    """The centres of `n` raster cells of `dt` s, as MATLAB Pulseq gives them."""
    return (np.arange(n) + 0.5) * dt


# ---- Gradients ----


def test_trapezoid_has_the_values_of_the_file():
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert grads[1] == Trapezoid(
        id=1, amplitude=1e6, rise_time=1e-4, flat_time=2e-4, fall_time=1e-4, delay=1e-4
    )
    assert grads[1].shape_dur == 1e-4 + 2e-4 + 1e-4
    assert (grads[1].first, grads[1].last) == (0.0, 0.0)


def test_arbitrary_gradient_on_the_default_raster():
    """Time ID 0: a sample at the centre of each gradient raster cell."""
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_5_1.seq"))
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
    """Time ID -1: samples half a gradient raster apart, the first at half a raster."""
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_5_1.seq"))
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


def test_arbitrary_gradient_with_a_time_shape():
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_5_1.seq"))
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
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_4_1.seq"))
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
    grads = decode_gradients(read_seqfile(SEQFILES / "valid_1_5_1.seq"))
    assert isinstance(grads, MappingProxyType)
    assert sorted(grads) == [1, 2, 3, 4, 5, 6]
    assert isinstance(grads[1], Trapezoid)
    assert all(isinstance(grads[i], ArbitraryGradient) for i in (2, 3, 4, 5, 6))
    assert all(g.id == i for i, g in grads.items())


# ---- RF ----


def test_rf_event_without_a_time_shape():
    """A sample at the centre of each RF raster cell. The 1.5 file gives the center and the
    use."""
    (rf,) = decode_rf(read_seqfile(SEQFILES / "valid_1_5_1.seq")).values()
    assert rf == RfEvent(
        id=1,
        amplitude=1000.0,
        mag_id=1,
        phase_id=2,
        time_id=0,
        magnitude=np.full(100, 1000.0),
        phase=np.zeros(100),
        t=_samples(100, 1e-6),
        shape_dur=100 * 1e-6,
        center=5e-5,
        delay=1e-4,
        freq_ppm=0.0,
        phase_ppm=0.0,
        freq_offset=0.0,
        phase_offset=0.0,
        use="e",
    )


def test_rf_event_of_a_1_4_file_has_no_center():
    (rf,) = decode_rf(read_seqfile(SEQFILES / "valid_1_4_0.seq")).values()
    assert rf.center is None
    assert (rf.use, rf.freq_ppm, rf.phase_ppm, rf.delay) == ("u", 0.0, 0.0, 1e-4)
    np.testing.assert_array_equal(rf.t, _samples(100, 1e-6))
    assert rf.shape_dur == 100 * 1e-6


def test_rf_event_with_a_time_shape(time_shaped):
    """A time shape that the reader does not take as regular: the pulse is resampled to the RF
    raster. The time shape 0.5, 1, 2, 4 gives 4 cells, which play the stored samples 1, 2, 3
    and 3. The magnitude is in Hz and the phase in rad (2 pi times the shape)."""
    rf = decode_rf(time_shaped)[1]
    played = [1, 2, 3, 3]
    assert rf == RfEvent(
        id=1,
        amplitude=2000.0,
        mag_id=6,
        phase_id=2,
        time_id=3,
        magnitude=2000.0 * np.array([0.25, 0.5, 0.75, 1])[played],
        phase=2 * np.pi * np.array([0, 0.25, 0.5, 0.75])[played],
        t=_samples(4, 1e-6),
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
    """A time shape stored compressed in 4 values (5 10 10 2): the reader takes the step 10 as
    the dwell time and keeps the 5 stored samples, at the centre of each dwell time."""
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
        shape_dur=5 * dwell,
        center=2e-6,
        delay=0.0,
        freq_ppm=0.0,
        phase_ppm=0.0,
        freq_offset=0.0,
        phase_offset=0.0,
        use="r",
    )


def test_rf_event_with_a_time_shape_in_a_1_4_file():
    """The block pulse of the file has the magnitude 1, 1 at the times 0, 100. The reader
    resamples it to 100 RF raster cells, each of which plays the stored sample 1."""
    (rf,) = decode_rf(read_seqfile(ORACLE / "koma_v1.4_rf-time-shaped.seq")).values()
    np.testing.assert_array_equal(rf.magnitude, np.full(100, 2500.0))
    np.testing.assert_array_equal(rf.phase, np.zeros(100))
    np.testing.assert_array_equal(rf.t, _samples(100, 1e-6))
    assert rf.shape_dur == 100 * 1e-6
    assert rf.center is None


@pytest.mark.parametrize(
    ("num_samples", "packed", "step"),
    [
        (5, [5, 10, 10, 2], 10.0),  # t0 d d N-3: the times 5, 15, 25, 35, 45
        (5, [1, 1, 3], 1.0),  # 1 1 N-2: the times 1 to 5
        (3, [5, 15, 25], None),  # 3 values, not compressed
        (4, [5, 15, 25, 35], None),  # 4 values, not compressed
        (10, [0.5, 1, 1, 6, 2], None),  # compressed in 5 values
        (2, [0, 100], None),  # a block pulse as MATLAB writes it
    ],
)
def test_rf_time_step_of_a_time_shape(num_samples, packed, step):
    """The reader takes a time shape as regular when it is compressed in 3 or 4 values, and its
    step is the second stored value."""
    shape = model.Shape(num_samples=num_samples, packed=np.array(packed, dtype=float))
    assert model._rf_time_step(shape) == step


@pytest.mark.parametrize(
    ("times", "played"),
    [
        ([0, 100], [1] * 100),  # a block pulse: sample 0 is never played
        ([1, 2, 3], [0, 1, 2]),  # times at the ends of the cells
        ([0.5, 1, 2, 4], [1, 2, 3, 3]),  # the last sample is played twice
        ([1, 5], [0, 1, 1, 1, 1]),  # a gap: the last sample is played from cell 1
        ([0.2, 0.6, 3], [1, 2, 2]),  # two times in cell 0: one step per cell
        ([0.2], []),  # int(0.5 + 0.2) is 0 cells
    ],
)
def test_rf_resample_plays_one_stored_sample_in_each_cell(times, played):
    """The number of cells is `int(0.5 + times[-1])`. In cell `c` the index goes up by one when
    the time at the index is below `c + 1`, and the cell plays the sample at the index."""
    result = model._rf_resample(np.array(times, dtype=float))
    assert result.dtype == np.int64
    assert result.tolist() == played


@pytest.mark.parametrize(
    "times",
    [
        [0, 99.6],  # 100 cells: the last cell plays sample 2 of 2
        [0.5, 1, 2, 4.5],  # 5 cells: the last cell plays sample 4 of 4
        [],
        [-2],  # int(0.5 - 2) is -1 cells
    ],
)
def test_rf_resample_raises_where_the_reader_reads_after_the_samples(times):
    """Where the reader would read after the end of the stored samples, and for an empty time
    shape or a negative number of cells, `_rf_resample` raises `ValueError`."""
    with pytest.raises(ValueError):
        model._rf_resample(np.array(times, dtype=float))


# ---- ADC ----


def test_adc_events_with_and_without_a_phase_shape(time_shaped):
    """The phase modulation is the shape as the file stores it, with no factor."""
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


# ---- All events ----


def test_each_row_is_decoded_whether_a_block_uses_it_or_not(time_shaped):
    assert list(decode_rf(time_shaped)) == [1, 2, 3]
    assert list(decode_gradients(time_shaped)) == [7]
    assert list(decode_adc(time_shaped)) == [1, 2]
    rf = decode_rf(time_shaped)[3]
    np.testing.assert_array_equal(rf.magnitude, [125.0, 250, 250, 125])
    assert decode_gradients(time_shaped)[7].shape_dur == 1e-5 + 0.0 + 1e-5


def test_a_shape_that_several_events_use_is_decompressed_once(time_shaped, monkeypatch):
    """The three RF events use the shapes 1, 2 (twice), 3, 6, 7 and 8. The regular time shape 4
    is not decompressed. Six decompressions."""
    calls = []
    samples = model.Shape.samples

    def counted(shape):
        calls.append(shape)
        return samples(shape)

    monkeypatch.setattr(model.Shape, "samples", counted)
    decode_rf(time_shaped)
    assert len(calls) == 6


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


FILES = sorted(SEQFILES.glob("valid_*.seq")) + sorted(ORACLE.glob("*.seq"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_every_file_that_loads_decodes(path):
    """Each event has the values of its row of the model, its arrays have one sample for each
    sample of its shape, and an RF or gradient event ends inside each block that plays it."""
    try:
        data = read_seqfile(path)
    except SeqFileError as error:
        pytest.skip(f"read_seqfile rejects the file: {sorted({v.rule for v in error.violations})}")
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
        if time_id > 0 and model._rf_time_step(data.shapes[time_id]) is None:
            n = int(0.5 + data.shapes[time_id].samples()[-1])
        assert rf.magnitude.shape == rf.phase.shape == rf.t.shape == (n,)
        assert rf.t[-1] < rf.shape_dur
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

    durations = data.block_durations_s
    for column, events in (("rf", rfs), ("gx", grads), ("gy", grads), ("gz", grads)):
        for i, event_id in enumerate(data.blocks[column].tolist()):
            if event_id:
                event = events[event_id]
                assert event.delay + event.shape_dur <= durations[i] + 1e-12
