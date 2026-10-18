"""The state that the C++ reader shares between its objects, and the lock around it.

`SeqBlock::s_blockDurationRaster` (cpp:89) is set by each `load` (cpp:1540) and read by
`SeqBlock::GetDuration`, which `gradientsAt` uses to give 0 after the end of a block. The
print function (`ExternalSequence::print_fun`, cpp:23) is global too. `sscanf`, with which the
reader reads every number, follows the C locale of the process. The extension holds one lock for
each call, sets the raster of the sequence it works on, and runs with the "C" locale in its
thread.

Threads that share one `Sequence` share its reader: each rejection must carry the messages of its
own call, not those of a call of another thread."""

import ctypes
import ctypes.util
import locale
import re
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


# valid_1_5_1.seq with time shape 6 (5 samples) on the gradients 2 and 4, whose wave shapes have
# 10: decodeBlock rejects the blocks that play them, and only those ("uncompressed extended
# trapezoid time and wave shape lengths do not match").
REJECTED = (1, 3)
CALLS = 2000


def two_rejected_blocks():
    text = VALID.read_bytes()
    for row, rejected in (
        (b"\n2 500000 0 0 3 0 100\n", b"\n2 500000 0 0 3 6 100\n"),
        (b"\n4 500000 500000 0 4 0 0\n", b"\n4 500000 500000 0 4 6 0\n"),
    ):
        assert row in text
        text = text.replace(row, rejected)
    return text


def blocks_named(messages):
    """The blocks of each line "decodeBlock returned false for block <n>" of `messages`."""
    return [int(n) for n in re.findall(r"decodeBlock returned false for block (\d+)", messages)]


def run_together(*works):
    """Each function of `works` in its own thread, started together; what each returned."""
    barrier = threading.Barrier(len(works))
    results = [None] * len(works)

    def run(k):
        barrier.wait()
        results[k] = works[k]()

    threads = [threading.Thread(target=run, args=(k,)) for k in range(len(works))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_each_rejection_of_decode_block_has_the_messages_of_its_own_block():
    sequence = cs.load(two_rejected_blocks())

    def decode(index):
        def work():
            wrong = []
            for _ in range(CALLS):
                try:
                    sequence.decode_block(index)
                except cs.Rejected as error:
                    if blocks_named(error.messages) != [index]:
                        wrong.append(error.messages)
                else:
                    wrong.append("decoded")
            return wrong

        return work

    first, second = run_together(decode(REJECTED[0]), decode(REJECTED[1]))
    assert (len(first), len(second), first[:2], second[:2]) == (0, 0, [], [])


def test_gradients_at_and_first_rejected_block_have_the_messages_of_their_own_block():
    sequence = cs.load(two_rejected_blocks())
    late, first = REJECTED[1], REJECTED[0]

    def sample():
        wrong = []
        for _ in range(CALLS):
            try:
                sequence.gradients_at([late], [0.0])
            except cs.Rejected as error:
                if blocks_named(error.messages) != [late]:
                    wrong.append(error.messages)
            else:
                wrong.append("sampled")
        return wrong

    def find_first():
        # Only this thread calls first_rejected_block, so rejection_messages, read just after
        # the call, is set by that call.
        wrong = []
        for _ in range(CALLS):
            index = sequence.first_rejected_block()
            if index != first or blocks_named(sequence.rejection_messages) != [first]:
                wrong.append((index, sequence.rejection_messages))
        return wrong

    sampled, found = run_together(sample, find_first)
    assert (len(sampled), len(found), sampled[:2], found[:2]) == (0, 0, [], [])


def _a_locale_with_a_decimal_comma():
    for name in ("de_DE.UTF-8", "de_DE.utf8", "fr_FR.UTF-8", "fr_FR.utf8", "German_Germany.1252"):
        try:
            locale.setlocale(locale.LC_NUMERIC, name)
        except locale.Error:
            continue
        locale.setlocale(locale.LC_NUMERIC, "C")
        return name
    return None


def test_the_reader_reads_in_the_c_locale_whatever_the_process_locale():
    name = _a_locale_with_a_decimal_comma()
    if name is None:
        pytest.skip("no locale with a decimal comma")
    expected = canonical_dump(wrapper_dump(cs.load(VALID)))
    try:
        locale.setlocale(locale.LC_NUMERIC, name)
        if sys.platform != "win32":  # the C library of the process is not checked on Windows
            # The precondition: the C library of the process reads "0.5" as 0 in this locale,
            # so the hazard that the extension guards against is real. strtod as sscanf's %f:
            # ctypes cannot call the variadic sscanf on every platform.
            libc = ctypes.CDLL(ctypes.util.find_library("c"))
            libc.strtod.restype = ctypes.c_double
            libc.strtod.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
            assert libc.strtod(b"0.5", None) == 0.0
        actual = canonical_dump(wrapper_dump(cs.load(VALID)))
    finally:
        locale.setlocale(locale.LC_NUMERIC, "C")
    assert actual == expected
