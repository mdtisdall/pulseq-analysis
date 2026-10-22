"""The package's API: the libraries as read, the decoding of one block, `gradients_at`, and the
version gate before `load`."""

import copy
import json
import pickle
import re

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import (
    DIGESTS,
    SEQFILES,
    canonical_dump,
    driver,
    driver_samples,
    fixture_id,
    fixtures,
    sample_points,
    wrapper_dump,
)

VALID = SEQFILES / "valid_1_5_1.seq"
_VERDICTS = json.loads(DIGESTS.read_text())
READ = [path for path in fixtures() if _VERDICTS[fixture_id(path)]["verdict"] == "read"]

# NaN is a value of a file (a float field that reads "nan"), so events compare in the canonical
# form of canonical.py. The fields of an event that decodeBlock changes or adds: shape_dur is computed from the
# decoded samples (cpp:2050), and the RF samples are added.
DECODED_ONLY = {"shape_dur_us", "dwell_us", "magnitude", "phase"}


def with_version(text: bytes, version: bytes) -> bytes:
    """The file with its [VERSION] section's lines replaced."""
    return re.sub(rb"\[VERSION\]\n.*?\n\n", b"[VERSION]\n" + version + b"\n", text, flags=re.DOTALL)


@pytest.mark.parametrize("path", READ, ids=fixture_id)
def test_each_decoded_block_is_built_from_the_libraries(path):
    sequence = cs.load(path)
    libraries = sequence.libraries
    assert libraries.blocks.shape == (sequence.block_count, len(cs.BLOCK_COLUMNS))
    for index, block in enumerate(sequence.decode()):
        duration, rf, gx, gy, gz, adc, _ext = libraries.blocks[index].tolist()
        assert block["index"] == index and block["duration_ru"] == duration
        if rf:
            decoded = {k: v for k, v in block["rf"].items() if k not in DECODED_ONLY}
            library = {k: v for k, v in libraries.rf[rf].items() if k not in DECODED_ONLY}
            assert canonical_dump(decoded) == canonical_dump(library)
        else:
            assert block["rf"] is None
        for grad_id, grad in zip((gx, gy, gz), block["grad"], strict=True):
            assert (grad is None) == (grad_id == 0)
            if grad is not None:
                event = libraries.grad[grad_id]
                same = ("amplitude", "delay_us")
                assert canonical_dump({k: grad[k] for k in same}) == canonical_dump(
                    {k: event[k] for k in same}
                )
                assert (grad["kind"] == "trap") == (event["wave_shape"] == 0)
        assert canonical_dump(block["adc"]) == canonical_dump(libraries.adc[adc] if adc else None)


def test_the_libraries_of_a_file():
    libraries = cs.load(VALID).libraries
    assert libraries.version == 1_005_001 and libraries.version_parts == (1, 5, 1)
    assert libraries.gradient_raster_us == 10.0 and libraries.rf_raster_us == 1.0
    assert libraries.block_raster_us == 10.0 and libraries.adc_raster_us == pytest.approx(0.1)
    assert libraries.definitions[b"BlockDurationRaster"] == b"1e-05"
    assert libraries.definition_values[b"BlockDurationRaster"].tolist() == [1e-05]
    assert libraries.signature["defined"] and libraries.signature["ok"]
    assert libraries.signature["type"] == b"md5"
    assert libraries.signature["value"] == libraries.signature["calculated"]
    for shape in libraries.shapes.values():
        assert isinstance(shape, cs.Shape) and shape.samples.dtype == np.float32
    assert libraries.blocks.dtype == np.int64


def sequence_path():
    return SEQFILES / "oracle" / "pulseq_epi_rs.seq"


def test_a_block_decodes_on_its_own_in_any_order():
    sequence = cs.load(sequence_path())
    expected = canonical_dump({"blocks": cs.load(sequence_path()).decode()})
    blocks = [None] * sequence.block_count
    for index in reversed(range(sequence.block_count)):
        blocks[index] = sequence.decode_block(index)
    assert canonical_dump({"blocks": blocks}) == expected


def test_gradients_at_decodes_the_blocks_that_it_needs():
    sequence = cs.load(VALID)
    block_index, time_us = sample_points(canonical_dump(wrapper_dump(cs.load(VALID))))
    lazily = sequence.gradients_at(block_index, time_us)
    sequence.decode()
    assert np.array_equal(sequence.gradients_at(block_index, time_us), lazily)


def test_gradients_at_refuses_a_nan_time_and_a_block_that_does_not_exist():
    sequence = cs.load(VALID)
    with pytest.raises(ValueError, match="NaN"):
        sequence.gradients_at([0], [np.nan])
    with pytest.raises(IndexError):
        sequence.gradients_at([sequence.block_count], [0.0])
    with pytest.raises(IndexError):
        sequence.gradients_at([-1], [0.0])
    with pytest.raises(ValueError, match="length"):
        sequence.gradients_at([0, 1], [0.0])
    assert sequence.gradients_at([], []).shape == (0, 3)


def test_gradients_at_refuses_a_block_index_that_is_not_an_integer():
    """`gradients_at` raises TypeError, with a message that names `block_index`, for a block index
    whose dtype is not an integer: a float (`[1.9]` gave the values of block 1), also one with an
    integer value, and a bool. A list of ints and arrays of int32 and uint8 read block 1 (the
    trapezoid of 1e6 Hz/m on gx at 250 us), and an empty list, which numpy makes float64, gives an
    array (0, 3)."""
    sequence = cs.load(VALID)
    for index in ([1.9], [1.0], np.array([1.0]), [True], np.array([True])):
        with pytest.raises(TypeError, match="block_index"):
            sequence.gradients_at(index, [250.0])
    expected = sequence.gradients_at([1], [250.0])
    assert expected[0, 0] == 1e6
    for index in (np.array([1], np.int32), np.array([1], np.uint8)):
        assert np.array_equal(sequence.gradients_at(index, [250.0]), expected)
    assert sequence.gradients_at([], []).shape == (0, 3)


def test_a_block_that_decodeblock_rejects_raises_rejected():
    # An arbitrary gradient on a gradient raster of 4 us: decodeBlock returns false (cpp:2116).
    sequence = cs.load(SEQFILES / "valid_arbitrary_gradient_4us_raster.seq")
    with pytest.raises(cs.Rejected) as error:
        sequence.decode_block(0)
    assert not isinstance(error.value, cs.UndefinedBehaviour)
    assert "decodeBlock returned false for block 0" in error.value.messages
    with pytest.raises(cs.Rejected):
        sequence.decode()
    with pytest.raises(cs.Rejected):
        sequence.gradients_at([0], [0.0])


def test_a_rejection_of_load_carries_the_reader_s_messages():
    with pytest.raises(cs.Rejected) as error:
        cs.load(SEQFILES / "bad_version_missing.seq")
    assert "[VERSION]" in error.value.messages


def test_a_file_whose_messages_are_not_utf_8_loads():
    """`load` quotes the line of an extension that it does not know (cpp:1248); a byte there that
    is not UTF-8 comes to `messages` as its escape."""
    text = VALID.read_bytes()
    data = text.replace(b"extension UNKNOWN 7", b"extension UNKN\xb5WN 7")
    assert data != text
    assert "extension UNKN\\xb5WN 7" in cs.load(data).messages


def test_a_rejection_whose_messages_are_not_utf_8_keeps_its_class_and_its_code():
    """`load` quotes the ADC row that it fails to decode (cpp:1150). With a byte there that is not
    UTF-8, `load` raises `Rejected` with the byte escaped in its messages. The code that
    `read_seqfile` gives is checked in `test_interpreter_in_pulseq_analysis.py`, which needs
    pulseq-analysis."""
    text = VALID.read_bytes()
    row = b"\n1 8 25000 100 0 0 0 0 0\n"
    assert text.count(row) == 1
    with pytest.raises(cs.Rejected) as error:
        cs.load(text.replace(row, b"\n1 \xb5x 25000 100 0 0 0 0 0\n"))
    assert "1 \\xb5x 25000" in error.value.messages


def test_load_reads_the_bytes_of_a_file():
    from_bytes = canonical_dump(wrapper_dump(cs.load(VALID.read_bytes())))
    assert from_bytes == canonical_dump(wrapper_dump(cs.load(VALID)))


def test_a_binary_file_and_a_folder_are_not_supported(tmp_path):
    with pytest.raises(cs.NotSupported, match="binary"):
        cs.load(b"\x01pulseq\x02" + bytes(100))
    with pytest.raises(cs.NotSupported, match="folder"):
        cs.load(tmp_path)


class _ReaderThatMustNotLoad:
    """The extension's Reader, whose `load` fails the test."""

    def __init__(self, oversampling="center"):
        self._reader = _original_reader(oversampling)

    def read_version(self, data):
        return self._reader.read_version(data)

    def load(self, data):
        raise AssertionError("ExternalSequence::load ran on a version that is not supported")


_original_reader = cs._reader.Reader


@pytest.mark.parametrize(
    "version",
    [
        b"major 1\nminor 3\nrevision 1\n",  # load would convert its blocks with GetBlock
        b"major 1\nminor 2\nrevision 0\n",
        b"major 1\nminor 6\nrevision 0\n",
        b"major 1\nminor 4\nrevision -1\n",  # 1003999
        b"major 1\nminor 5\nrevision 1\nmajor 1\nminor 3\n",  # a repeated field: the last one
        b"major 1\nminor 5\nrevision 99999999999\n",  # sscanf wraps it; the sum is not an int
    ],
)
def test_a_version_outside_1_4_to_1_5_is_refused_before_the_reader_loads_the_file(
    version, monkeypatch
):
    monkeypatch.setattr(cs._reader, "Reader", _ReaderThatMustNotLoad)
    with pytest.raises(cs.NotSupported, match="outside 1.4.0-1.5.x"):
        cs.load(with_version(VALID.read_bytes(), version))


@pytest.mark.parametrize(
    "version",
    [
        b"major 1\nminor 5\nrevision 1\n",
        b"major 1\nminor 4\n",  # the revision stays 0
        b"# a comment\nmajor 1\nminor 4\nrevision 2\n",
        b"major\t1\nminor 5x\nrevision 1\n",  # sscanf stops at x
        b"major 0\nminor 1004\nrevision 0\n",  # 1004000: the reader's 1.4.0
        b"major 4294967297\nminor 5\nrevision 1\n",  # sscanf wraps it to 1
    ],
)
def test_the_version_gate_reads_the_version_as_load_does(version):
    data = with_version(VALID.read_bytes(), version)
    found, major, minor, revision = cs._reader.Reader().read_version(data)
    assert found
    reader = cs._reader.Reader()
    ok, _ = reader.load(data)
    assert ok
    assert reader.libraries()["version_parts"] == (major, minor, revision)


@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_version_gate_reads_each_fixture_as_load_does(path):
    data = path.read_bytes()
    found, *parts = cs._reader.Reader().read_version(data)
    reader = cs._reader.Reader()
    version = parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2]
    if found and 1_004_000 <= version < 1_006_000:
        ok, _ = reader.load(data)
        if ok:
            assert reader.libraries()["version_parts"] == tuple(parts)
    elif not found:
        ok, _ = reader.load(data)
        assert not ok  # load returns false where the gate finds no version


# The files of the tests of `load`'s `max_shape_samples`. In `valid_no_signature.seq` the shapes
# 1 and 2 declare 100 samples, the most of the file. `shape_decompress_longer.seq` is that file
# with 99 declared in the shapes 1 and 2, which decompress to 100 samples (D5.5).
NO_SIGNATURE = SEQFILES / "valid_no_signature.seq"
DECOMPRESS_LONGER = SEQFILES / "undefined" / "shape_decompress_longer.seq"


def test_a_shape_over_max_shape_samples_is_not_supported_before_the_checks():
    """With `max_shape_samples=98`, `load` raises `NotSupported` for shape 1 of
    `shape_decompress_longer.seq`, not `UndefinedBehaviour`: the number of samples of each shape
    is checked before the checks decompress any shape. The message gives the file, the shape, the
    declared number and the limit, and names the setting and None. With the limit 99, the
    default and None, `load` gives the `UndefinedBehaviour` of a `load` with no limit."""
    with pytest.raises(cs.NotSupported) as caught:
        cs.load(DECOMPRESS_LONGER, max_shape_samples=98)
    for part in (str(DECOMPRESS_LONGER), "shape 1 ", "99", "98", "max_shape_samples", "None"):
        assert part in str(caught.value)
    for setting in ({"max_shape_samples": 99}, {}, {"max_shape_samples": None}):
        with pytest.raises(cs.UndefinedBehaviour) as caught:
            cs.load(DECOMPRESS_LONGER, **setting)
        assert caught.value.code == "ub.shape-decompression"


def test_max_shape_samples_is_the_most_samples_that_a_shape_can_declare():
    """`load` reads `valid_no_signature.seq` with `max_shape_samples=100`, as with None, and with
    99 raises `NotSupported` for shape 1, the first of the two shapes of 100 samples."""
    unlimited = canonical_dump(wrapper_dump(cs.load(NO_SIGNATURE, max_shape_samples=None)))
    at_limit = cs.load(NO_SIGNATURE, max_shape_samples=100)
    assert max(shape.num_samples for shape in at_limit.libraries.shapes.values()) == 100
    assert canonical_dump(wrapper_dump(at_limit)) == unlimited
    with pytest.raises(cs.NotSupported) as caught:
        cs.load(NO_SIGNATURE, max_shape_samples=99)
    for part in ("shape 1 ", "100", "99", "max_shape_samples"):
        assert part in str(caught.value)


def test_max_shape_samples_of_load_is_an_int_above_0_or_none():
    """As the setting of every interpreter of pulseq-analysis: a numpy int is kept as an int, a
    bool or another type is a `TypeError`, and 0 or less a `ValueError`."""
    limit = cs.load(NO_SIGNATURE, max_shape_samples=np.int64(100)).max_shape_samples
    assert limit == 100 and type(limit) is int
    message = "max_shape_samples is an int above 0 or None"
    for value in (True, 1.5, "100"):
        with pytest.raises(TypeError, match=message):
            cs.load(NO_SIGNATURE, max_shape_samples=value)
    for value in (0, -1):
        with pytest.raises(ValueError, match=message):
            cs.load(NO_SIGNATURE, max_shape_samples=value)


# A file of one block of 2000 us that plays RF event 1: the magnitude (shape 1), the phase (shape
# 2) and the time shape (shape 3) have two samples each, and the times are 1 and 2000 RF rasters.
# decodeBlock resamples the pulse into int(0.5 + 2000) = 2000 cells of the RF raster (cpp:2031).
# tests/test_interpreters.py of pulseq-analysis has a copy, since the wheel tests run without the
# tests of pulseq-analysis.
RESAMPLED_RF = b"""# Pulseq sequence file
# Hand-written file of the tests, not made by a Pulseq tool.

[VERSION]
major 1
minor 5
revision 0

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

# NUM DUR RF GX GY GZ ADC EXT
[BLOCKS]
1 200 1 0 0 0 0 0

# id ampl. mag_id phase_id time_shape_id center delay freqPPM phasePPM freq phase use
[RF]
1 1000 1 2 3 1000 0 0 0 0 0 e

[SHAPES]

shape_id 1
num_samples 2
1
1

shape_id 2
num_samples 2
0
0

shape_id 3
num_samples 2
1
2000

"""


def test_an_rf_pulse_whose_resampling_has_more_cells_than_max_shape_samples_is_not_supported():
    """`max_shape_samples` also limits the samples that `decodeBlock` resamples from a shape
    (the user, 2026-10-21): `RESAMPLED_RF` has shapes of two samples, and its RF pulse is
    resampled into 2000 cells. With the limit 1000, `load` raises `NotSupported` whose message
    names the RF event, its time shape, the 2000 cells, the limit and the setting. With the limit
    2000 and with None it loads, and the decoded block has 2000 samples of the magnitude and of
    the phase."""
    with pytest.raises(cs.NotSupported) as caught:
        cs.load(RESAMPLED_RF, max_shape_samples=1000)
    for part in ("<bytes>: RF event 1 ", "time shape 3 ", "2000", "1000", "max_shape_samples"):
        assert part in str(caught.value)
    for limit in (2000, None):
        rf = cs.load(RESAMPLED_RF, max_shape_samples=limit).decode_block(0)["rf"]
        assert len(rf["magnitude"]) == len(rf["phase"]) == 2000


def test_an_rf_last_time_that_is_not_an_int_is_not_supported_under_a_limit():
    """`RESAMPLED_RF` with the last time inf: `int(0.5 + inf)` is undefined (cpp:2031, D5.9), and
    inf cells are more than any limit. Under the default limit `load` raises `NotSupported` for
    RF event 1, before the checks; with None it raises `UndefinedBehaviour` with the code
    `ub.rf-time-range`. A last time of NaN is not over any limit: `ub.rf-time-range` under the
    default limit too."""
    infinite = RESAMPLED_RF.replace(b"\n2000\n", b"\ninf\n")
    with pytest.raises(cs.NotSupported) as caught:
        cs.load(infinite)
    for part in ("<bytes>: RF event 1 ", "inf cells", "max_shape_samples"):
        assert part in str(caught.value)
    with pytest.raises(cs.UndefinedBehaviour) as caught:
        cs.load(infinite, max_shape_samples=None)
    assert caught.value.code == "ub.rf-time-range"
    with pytest.raises(cs.UndefinedBehaviour) as caught:
        cs.load(RESAMPLED_RF.replace(b"\n2000\n", b"\nnan\n"))
    assert caught.value.code == "ub.rf-time-range"


def oversampled_file(tmp_path, samples: list[float], name="oversampled.seq", first=0, last=0):
    """A file of one block of 200 us: gradient 1 on X is an oversampled arbitrary gradient (time
    shape -1) of `samples` with no delay and the first and last values `first` and `last`, and
    gradient 2 on Y is a trapezoid with a plateau from 10 to 110 us. The reader plays Y at 1e6
    Hz/m there, and X from the shape."""
    text = (
        f"""# Pulseq sequence file
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
1 20 0 1 2 0 0 0

[GRADIENTS]
1 500000 {first} {last} 1 -1 0

[TRAP]
2 1000000 10 100 10 0

[SHAPES]
shape_id 1
num_samples {len(samples)}
"""
        + "".join(f"{v}\n" for v in samples)
        + "\n"
    )
    path = tmp_path / name
    path.write_text(text)
    return path


def x_samples(sequence):
    return sequence.decode_block(0)["grad"][0]["samples"].tolist()


def test_oversampling_keeps_the_samples_of_its_mode(tmp_path):
    path = oversampled_file(tmp_path, [0.25, 0.5, 0.75, 1.0, 0.5, 0.25, 0.0])
    assert cs.OVERSAMPLING == ("center", "edge", "preserve")
    seen = {}
    for mode in cs.OVERSAMPLING:
        sequence = cs.load(path, oversampling=mode)
        assert sequence.oversampling == mode
        assert sequence.decode_block(0)["grad"][0]["oversampled"]
        seen[mode] = x_samples(sequence)
    assert seen == {
        "center": [0.25, 0.75, 0.5, 0.0],
        "edge": [0.5, 1.0, 0.25],
        "preserve": [0.25, 0.5, 0.75, 1.0, 0.5, 0.25, 0.0],
    }
    assert cs.load(path).oversampling == "center"
    # An even number of samples (MATLAB writes an odd one, the reader reads either).
    path = oversampled_file(tmp_path, [0.25, 0.5, 0.75, 1.0], "even.seq")
    assert [x_samples(cs.load(path, oversampling=mode)) for mode in cs.OVERSAMPLING] == [
        [0.25, 0.75],
        [0.5],
        [0.25, 0.5, 0.75, 1.0],
    ]


@pytest.mark.parametrize("mode", ["Center", "left", "", None])
def test_an_oversampling_mode_that_is_not_one_of_the_three_raises_value_error(mode):
    with pytest.raises(ValueError, match="oversampling"):
        cs.load(VALID, oversampling=mode)
    with pytest.raises(ValueError):
        cs._reader.Reader(mode if mode is not None else "")


@pytest.mark.parametrize("count", [1, 2])
def test_an_edge_gradient_with_no_sample_leaves_no_value_from_the_sample_before(tmp_path, count):
    """An oversampled gradient of 1 or 2 samples has none in the "edge" mode, and gradientsAt
    returns early for it at its delay (cpp:3673-3677), after the channel before it and before
    the channels after it. Y is on its plateau (1e6) at 50 us, and at the delay of X (0 us)
    gradientsAt returns early: the Y of that line is 0, as the driver gives for a line of its
    own, not the 1e6 of the line before."""
    path = oversampled_file(tmp_path, [0.5, 1.0][:count])
    times = [50.0, 0.0, 50.0, 0.0]
    edge = cs.load(path, oversampling="edge")
    assert x_samples(edge) == []
    values = edge.gradients_at([0] * 4, times)
    assert values[:, 1].tolist() == [1e6, 0.0, 1e6, 0.0]
    assert values[1].tolist() == [0.0, 0.0, 0.0] and values[3].tolist() == [0.0, 0.0, 0.0]
    for mode in ("center", "preserve"):
        other = cs.load(path, oversampling=mode).gradients_at([0] * 4, times)
        assert other[:, 1].tolist() == [1e6, 0.0, 1e6, 0.0]
        kept = [0.5] if mode == "center" else [0.5, 1.0][:count]
        assert x_samples(cs.load(path, oversampling=mode)) == kept
    if driver() is not None:
        expected = driver_samples(path, np.zeros(4, dtype=np.int64), np.array(times), "edge")
        assert np.array_equal(values, expected)


def test_a_sequence_survives_pickle_and_copy():
    for mode in cs.OVERSAMPLING:
        original = cs.load(VALID, oversampling=mode)
        original.decode_block(1)  # a decoded block is a cache that a pickle does not carry
        restored = pickle.loads(pickle.dumps(original))
        assert restored is not original and restored.oversampling == mode
        assert np.array_equal(restored.libraries.blocks, original.libraries.blocks)
        assert restored.libraries.version == original.libraries.version
        assert restored.messages == original.messages
        dump = wrapper_dump(original)
        assert canonical_dump(wrapper_dump(restored)) == canonical_dump(dump)
        block_index, time_us = sample_points(canonical_dump(dump))
        expected = original.gradients_at(block_index, time_us)
        assert np.array_equal(restored.gradients_at(block_index, time_us), expected)
        assert copy.copy(original) is original and copy.deepcopy(original) is original
        assert copy.deepcopy({"reading": original})["reading"] is original


def test_a_pickle_of_a_sequence_loads_under_the_max_shape_samples_of_its_load(tmp_path):
    """`Sequence.max_shape_samples` is the limit of its `load`, and a pickle carries it. A file
    with a shape of 200 000 000 declared samples that no event uses loads with None, not with the
    default, and its pickle loads. A sequence that loaded with a limit loads again with it."""
    path = tmp_path / "unused_shape.seq"
    unused = "\nshape_id 99\nnum_samples 200000000\n0\n0\n199999998\n"
    path.write_text(NO_SIGNATURE.read_text() + unused)
    with pytest.raises(cs.NotSupported):
        cs.load(path)
    for source, limit in ((path, None), (NO_SIGNATURE, 100), (NO_SIGNATURE, 2**27)):
        original = cs.load(source, max_shape_samples=limit)
        restored = pickle.loads(pickle.dumps(original))
        assert original.max_shape_samples == restored.max_shape_samples == limit
        assert canonical_dump(wrapper_dump(restored)) == canonical_dump(wrapper_dump(original))


def test_first_rejected_block_is_the_first_block_that_decodeblock_rejects(tmp_path):
    assert cs.load(VALID).first_rejected_block() is None
    sequence = cs.load(SEQFILES / "valid_arbitrary_gradient_4us_raster.seq")
    assert sequence.first_rejected_block() == 0
    assert "decodeBlock returned false for block 0" in sequence.rejection_messages
    # It keeps no block: gradients_at still decodes the block that it needs, and rejects it.
    with pytest.raises(cs.Rejected):
        sequence.gradients_at([0], [0.0])
    # The first of several rejected blocks: a second block that uses the same gradient.
    text = (SEQFILES / "valid_arbitrary_gradient_4us_raster.seq").read_text()
    two = text.replace(
        "\n1   5  0  1  0  0  0  0\n", "\n1   5  0  1  0  0  0  0\n2   5  0  1  0  0  0  0\n"
    )
    assert two != text
    path = tmp_path / "two_rejected.seq"
    path.write_text(two)
    sequence = cs.load(path)
    assert sequence.block_count == 2 and sequence.first_rejected_block() == 0
    assert sequence.rejection_messages.count("decodeBlock returned false") == 1
    assert cs.load(VALID).rejection_messages == ""


ROTATED = SEQFILES / "oracle" / "koma_v1.5_rotation_radial_tiny.seq"


def rotation_matrix(q):
    """The matrix of the active rotation by the unit quaternion q = (q0, qx, qy, qz)."""
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def test_block_rotations_are_the_quaternions_that_getblock_attaches():
    sequence = cs.load(ROTATED)
    indices, quaternions = sequence.block_rotations()
    assert indices.dtype == np.int64 and quaternions.shape == (5, 4)
    assert indices.tolist() == [0, 1, 2, 3, 4]
    library = sequence.libraries.rotations
    # The extension lists of blocks 1 to 5 are 1, 2, 3, 2, 1, each a rotation of that ID.
    for index, rotation_id in zip(indices, (1, 2, 3, 2, 1), strict=True):
        assert tuple(quaternions[index]) == library[rotation_id]
        assert tuple(quaternions[index]) == sequence.decode_block(int(index))["rotation"]
    assert np.allclose(np.linalg.norm(quaternions, axis=1), 1, rtol=0, atol=1e-15)
    # The result is a copy: changing it changes no later result.
    quaternions[:] = 0
    assert np.array_equal(sequence.block_rotations()[1][0], [1, 0, 0, 0])


NO_ROTATION = SEQFILES / "valid_1_5_0.seq"


def test_block_rotations_of_a_file_with_no_rotation_are_empty():
    indices, quaternions = cs.load(NO_ROTATION).block_rotations()
    assert indices.shape == (0,) and quaternions.shape == (0, 4)


def test_a_block_with_two_rotations_has_the_first(tmp_path):
    # Block 1's list now goes on to the entry of rotation 3: GetBlock keeps rotation 1 and warns.
    text = ROTATED.read_bytes().replace(b"\n1 1 1 0\n", b"\n1 1 1 3\n")
    assert text != ROTATED.read_bytes()
    sequence = cs.load(text)
    indices, quaternions = sequence.block_rotations()
    assert indices.tolist() == [0, 1, 2, 3, 4]
    assert tuple(quaternions[0]) == sequence.libraries.rotations[1]


def test_rotated_gradients_are_the_reader_s_turned_by_each_block_s_quaternion():
    sequence = cs.load(ROTATED)
    block_index = np.repeat(np.arange(sequence.block_count), 41)
    time_us = np.tile(np.arange(0.0, 410.0, 10.0), sequence.block_count)
    logical = sequence.gradients_at(block_index, time_us)
    rotated = sequence.gradients_at(block_index, time_us, rotated=True)
    _, quaternions = sequence.block_rotations()
    for b, q in enumerate(quaternions):
        here = block_index == b
        expected = logical[here] @ rotation_matrix(q).T
        assert np.allclose(rotated[here], expected, rtol=0, atol=1e-9 * np.abs(logical).max())
    # A rotation keeps the length of each vector; the identity (blocks 1 and 5) changes nothing.
    assert np.allclose(np.linalg.norm(rotated, axis=1), np.linalg.norm(logical, axis=1))
    for b in (0, 4):
        assert np.array_equal(rotated[block_index == b], logical[block_index == b])
    # 90 degrees about z (block 3): x goes to y.
    flat = (block_index == 2) & (time_us == 200.0)
    assert np.allclose(rotated[flat], [[0, 1000, 0]], rtol=0, atol=1e-9)
    # The reader's own values are not changed.
    assert np.array_equal(sequence.gradients_at(block_index, time_us), logical)


def test_rotated_gradients_turn_only_the_blocks_with_a_rotation():
    # valid_1_5_1.seq: a rotation in some blocks only.
    sequence = cs.load(VALID)
    block_index, time_us = sample_points(canonical_dump(wrapper_dump(cs.load(VALID))))
    logical = sequence.gradients_at(block_index, time_us)
    rotated = sequence.gradients_at(block_index, time_us, rotated=True)
    indices, quaternions = sequence.block_rotations()
    assert 0 < indices.size < sequence.block_count
    plain = ~np.isin(block_index, indices)
    assert plain.any() and np.array_equal(rotated[plain], logical[plain])
    for b, q in zip(indices, quaternions, strict=True):
        here = block_index == b
        expected = logical[here] @ rotation_matrix(q).T
        assert np.allclose(rotated[here], expected, rtol=0, atol=1e-9 * np.abs(logical).max())


def test_rotated_gradients_of_a_file_with_no_rotation_are_the_reader_s():
    sequence = cs.load(NO_ROTATION)
    block_index, time_us = sample_points(canonical_dump(wrapper_dump(cs.load(NO_ROTATION))))
    assert np.array_equal(
        sequence.gradients_at(block_index, time_us, rotated=True),
        sequence.gradients_at(block_index, time_us),
    )


# The fixture of the scanner session of pulseq-analysis (task R16): soft delays TE (blocks 1 and 6)
# and TR (block 7), and the labels NOROT (blocks 3, 4), NOSLC (blocks 4, 5) and NOSCL (block 5).
SESSION = SEQFILES.parent / "session" / "scanner_session.seq"


def test_rotate_vec3_by_quat_is_the_rotation_of_rotated_gradients():
    """`rotate_vec3_by_quat` is the reader's rotation of `gradients_at(..., rotated=True)`, bit
    for bit."""
    sequence = cs.load(ROTATED)
    block_index = np.repeat(np.arange(sequence.block_count), 41)
    time_us = np.tile(np.arange(0.0, 410.0, 10.0), sequence.block_count)
    logical = sequence.gradients_at(block_index, time_us)
    _, quaternions = sequence.block_rotations()
    turned = cs.rotate_vec3_by_quat(quaternions[block_index], logical)
    assert np.array_equal(turned, sequence.gradients_at(block_index, time_us, rotated=True))
    assert cs.rotate_vec3_by_quat(np.zeros((0, 4)), np.zeros((0, 3))).shape == (0, 3)
    with pytest.raises(ValueError, match="differ in length"):
        cs.rotate_vec3_by_quat(quaternions[:2], logical[:3])


def test_block_soft_delays_are_those_that_getblock_attaches():
    """The soft delay of each block, as `load` read it: the offset is an int, so `-100.5 1 TE` is
    the offset -100, the factor 0.5 and the hint `1 TE` (D2.16 of pulseq-analysis)."""
    found = cs.load(SESSION).block_soft_delays()
    assert found.blocks.tolist() == [1, 6, 7]
    assert found.num.tolist() == [0, 0, 1]
    assert found.offset_us.tolist() == [-100, 5000, 0]
    assert found.factor.tolist() == [2.0, -1.0, 1.0]
    assert found.hint == (b"TE", b"TE", b"TR")
    misread = cs.load(SEQFILES / "valid_soft_delay_fraction.seq").block_soft_delays()
    assert misread.blocks.tolist() == [7] and misread.offset_us.tolist() == [-100]
    assert misread.factor.tolist() == [0.5] and misread.hint == (b"1 TE",)
    assert cs.load(SEQFILES / "valid_1_4_0.seq").block_soft_delays().blocks.size == 0


def test_a_change_to_the_soft_delays_that_a_sequence_gives_does_not_change_the_sequence():
    sequence = cs.load(SESSION)
    changed = sequence.block_soft_delays()
    changed.blocks[:] = 0
    changed.num[:] = 9
    changed.offset_us[:] = 1
    changed.factor[:] = 3.0
    found = sequence.block_soft_delays()
    assert found.blocks.tolist() == [1, 6, 7]
    assert found.num.tolist() == [0, 0, 1]
    assert found.offset_us.tolist() == [-100, 5000, 0]
    assert found.factor.tolist() == [2.0, -1.0, 1.0]


def test_block_label_sets_are_the_labels_that_decodelabel_knows():
    """The LABELSET events of each block: the reader leaves out `NOSLC`, the specification's
    spelling of its `NOSCL`."""
    blocks, names, values = cs.load(SESSION).block_label_sets()
    assert blocks.tolist() == [3, 4, 5]
    assert names == ("NOROT", "NOROT", "NOSCL")
    assert values.tolist() == [1, 0, 1]


def test_the_soft_delay_hook_sets_the_duration_and_the_end_of_gradients_at():
    """`block_durations_ru` is `GetDuration_ru` after the hook `setActualSoftDelay_ru`; -1 keeps
    the stored duration. `gradients_at` with `actual_ru` ends a block at that duration (block 0,
    a trapezoid that ends at 450 us, cut at 400 us), and the next call without it does not."""
    sequence = cs.load(SESSION)
    stored = sequence.block_durations_ru(np.full(9, -1))
    assert stored.tolist() == [50, 10, 50, 50, 50, 50, 20, 30, 50]
    actual = np.full(9, -1)
    actual[[0, 1]] = [40, 90]
    assert sequence.block_durations_ru(actual).tolist() == [40, 90, 50, 50, 50, 50, 20, 30, 50]
    assert sequence.gradients_at([0], [420.0], actual_ru=actual)[0, 0] == 0
    assert sequence.gradients_at([0], [420.0])[0, 0] != 0
    assert sequence.gradients_at([0], [300.0], actual_ru=actual)[0, 0] == 1e6
    with pytest.raises(ValueError, match="one value for each block"):
        sequence.block_durations_ru(actual[:3])
    with pytest.raises(ValueError, match="one value for each block"):
        sequence.gradients_at([0], [1.0], actual_ru=actual[:3])
