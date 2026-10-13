"""The package's API: the libraries as read, the decoding of one block, `gradients_at`, and the
version gate before `load`."""

import json
import re

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import (
    DIGESTS,
    SEQFILES,
    canonical_dump,
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

    def __init__(self):
        self._reader = _original_reader()

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
    assert reader.load(data)
    assert reader.libraries()["version_parts"] == (major, minor, revision)


@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_version_gate_reads_each_fixture_as_load_does(path):
    data = path.read_bytes()
    found, *parts = cs._reader.Reader().read_version(data)
    reader = cs._reader.Reader()
    version = parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2]
    if found and 1_004_000 <= version < 1_006_000:
        if reader.load(data):
            assert reader.libraries()["version_parts"] == tuple(parts)
    elif not found:
        assert not reader.load(data)  # load returns false where the gate finds no version
