"""The state that the C++ reader shares between its objects, and the lock around it.

`SeqBlock::s_blockDurationRaster` (cpp:89) is set by each `load` (cpp:1540) and read by
`SeqBlock::GetDuration`, which `gradientsAt` uses to give 0 after the end of a block. The
print function (`ExternalSequence::print_fun`, cpp:23) is global too. `sscanf`, with which the
reader reads every number, follows the C locale of the process. The extension holds one lock for
each call, sets the raster of the sequence it works on, and runs with the "C" locale in its
thread."""

import ctypes
import ctypes.util
import locale
import sys
import threading

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import SEQFILES, canonical_dump, sample_points, wrapper_dump

VALID = SEQFILES / "valid_1_5_1.seq"


@pytest.fixture
def fine_raster(tmp_path):
    """valid_1_5_1.seq with a BlockDurationRaster of 1 us instead of 10 us, and each block
    duration times 10: the same blocks, with another value of s_blockDurationRaster."""
    text = VALID.read_text()
    head, blocks = text.split("[BLOCKS]\n", 1)
    rows, rest = blocks.split("\n\n", 1)
    scaled = []
    for row in rows.splitlines():
        fields = row.split()
        fields[1] = str(int(fields[1]) * 10)
        scaled.append(" ".join(fields))
    head = head.replace("BlockDurationRaster 1e-05", "BlockDurationRaster 1e-06")
    path = tmp_path / "fine_raster.seq"
    path.write_text(head + "[BLOCKS]\n" + "\n".join(scaled) + "\n\n" + rest.split("[SIGNATURE]")[0])
    return path


def samples(sequence):
    dump = canonical_dump(wrapper_dump(sequence))
    block_index, time_us = sample_points(dump)
    return block_index, time_us, sequence.gradients_at(block_index, time_us)


def test_the_two_files_give_the_same_gradients(fine_raster):
    *_, coarse = samples(cs.load(VALID))
    *_, fine = samples(cs.load(fine_raster))
    assert np.array_equal(coarse, fine)


def test_a_sequence_samples_with_its_own_raster_after_another_load(fine_raster):
    sequence = cs.load(VALID)
    block_index, time_us, before = samples(sequence)
    cs.load(fine_raster)  # sets s_blockDurationRaster to 1 us
    assert np.array_equal(sequence.gradients_at(block_index, time_us), before)


def test_loads_and_samples_in_threads_give_the_values_of_one_thread(fine_raster):
    paths = [VALID, fine_raster, SEQFILES / "oracle" / "pulseq_epi_rs.seq"]
    expected = {}
    for path in paths:
        sequence = cs.load(path)
        expected[path] = (canonical_dump(wrapper_dump(sequence)), samples(sequence)[2])
    errors = []

    def work(offset):
        try:
            for i in range(12):
                path = paths[(i + offset) % len(paths)]
                sequence = cs.load(path)
                dump, values = expected[path]
                assert canonical_dump(wrapper_dump(sequence)) == dump
                assert np.array_equal(samples(sequence)[2], values)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def _a_locale_with_a_decimal_comma():
    for name in ("de_DE.UTF-8", "de_DE.utf8", "fr_FR.UTF-8", "fr_FR.utf8", "German_Germany.1252"):
        try:
            locale.setlocale(locale.LC_NUMERIC, name)
        except locale.Error:
            continue
        locale.setlocale(locale.LC_NUMERIC, "C")
        return name
    return None


@pytest.mark.skipif(sys.platform == "win32", reason="the C library of the process is not checked")
def test_the_c_library_of_the_process_reads_numbers_by_its_locale():
    # strtod as sscanf's %f: ctypes cannot call the variadic sscanf on every platform.
    name = _a_locale_with_a_decimal_comma()
    if name is None:
        pytest.skip("no locale with a decimal comma")
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    libc.strtod.restype = ctypes.c_double
    libc.strtod.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    try:
        locale.setlocale(locale.LC_NUMERIC, name)
        value = libc.strtod(b"0.5", None)
    finally:
        locale.setlocale(locale.LC_NUMERIC, "C")
    assert value == 0.0  # "0.5" reads as 0 with a decimal comma


def test_the_reader_reads_in_the_c_locale_whatever_the_process_locale():
    name = _a_locale_with_a_decimal_comma()
    if name is None:
        pytest.skip("no locale with a decimal comma")
    expected = canonical_dump(wrapper_dump(cs.load(VALID)))
    try:
        locale.setlocale(locale.LC_NUMERIC, name)
        actual = canonical_dump(wrapper_dump(cs.load(VALID)))
    finally:
        locale.setlocale(locale.LC_NUMERIC, "C")
    assert actual == expected
