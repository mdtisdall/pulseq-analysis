"""The block iteration that the oracles use.

It was `seq_utils.iter_blocks`. No library code calls it, so it lives with the tests.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import NamedTuple

import pypulseq as pp


class BlockTiming(NamedTuple):
    block_id: int
    start_s: float  # sum of the durations of the blocks before this one
    duration_s: float
    block: SimpleNamespace  # from Sequence.get_block


def iter_blocks(seq: pp.Sequence) -> Iterator[BlockTiming]:
    """Each block of `seq` in play order, with its start time and duration (s).

    The start times are added in play order from 0.0, one block duration at a time,
    so they are equal to `t += seq.block_durations[block_id]` in a loop. The end of
    the sequence is `start_s + duration_s` of the last block.
    """
    start = 0.0
    for block_id in seq.block_events:
        duration = seq.block_durations[block_id]
        yield BlockTiming(int(block_id), start, duration, seq.get_block(block_id))
        start += duration
