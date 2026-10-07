"""The kept results of one sequence object, and the rule that makes them old.

`seq_index.sequence_index`, `_events.event_points`, `grad_peaks.gradient_peaks` (for
`window=None`) and `grad_peaks.block_gradient_values`, `pns_levels.pns_levels` and
`grad_spectrum.gradient_spectrum` keep their results for the sequence object, so that
several measurements of one sequence build each result one time. `kept_results` is the one
place of the rule that says when the kept results of an object are old.

The stamp of a sequence has these parts:

- the objects `seq.block_events`, `seq.block_durations` and `seq.grad_library`, compared
  with `is`. `Sequence.read` sets a new object in each, and `add_block` changes them in
  place, so a new read of a file into the object gives a new stamp;
- the number of blocks, and the last block ID, which `add_block` changes;
- `seq.grad_raster_time`, which the measurements read.

A different stamp empties the kept results of that object. A change that keeps the
whole stamp is not seen: a call of pypulseq that changes the sequence in place, `mod_grad_axis`
and `flip_grad_axis` (they rewrite the entries of `grad_library`), `set_block` on a block ID
that exists, `apply_soft_delay` (it writes the values of `block_durations`), and a direct write
into `block_events`, `block_durations` or a library. A caller makes a new sequence object after
such a change.

The stamp holds a reference to the three objects, not to the sequence, so the
`WeakKeyDictionary` still lets the sequence go. Each of these modules has its own
`WeakKeyDictionary`, so the keys of the modules cannot collide, and each module
uses the keys that fit its results.
"""

import weakref
from dataclasses import dataclass, field
from typing import Any

import pypulseq as pp


@dataclass(eq=False)
class _Entry:
    """The stamp of a sequence and the kept results made while that stamp was true."""

    block_events: Any
    block_durations: Any
    grad_library: Any
    num_blocks: int
    last_id: int
    grad_raster_time: float
    results: dict = field(default_factory=dict)

    def matches(self, seq: pp.Sequence, num_blocks: int, last_id: int) -> bool:
        """True when `seq` still has the stamp of this entry."""
        return (
            seq.block_events is self.block_events
            and seq.block_durations is self.block_durations
            and seq.grad_library is self.grad_library
            and num_blocks == self.num_blocks
            and last_id == self.last_id
            and seq.grad_raster_time == self.grad_raster_time
        )


def kept_results(cache: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]", seq: pp.Sequence) -> dict:
    """The dict of the kept results of `seq` in `cache`. It is a new, empty dict when the
    stamp of `seq` is not the stamp of the last call."""
    block_events = seq.block_events
    num_blocks = len(block_events)
    last_id = int(next(reversed(block_events))) if num_blocks else 0
    entry = cache.get(seq)
    if entry is None or not entry.matches(seq, num_blocks, last_id):
        entry = _Entry(
            block_events,
            seq.block_durations,
            seq.grad_library,
            num_blocks,
            last_id,
            seq.grad_raster_time,
        )
        cache[seq] = entry
    return entry.results
