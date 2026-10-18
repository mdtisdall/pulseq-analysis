"""The block table of one sequence, in play order, with dense event indexes.

`sequence_index` reads the block table of the snapshot's data (`SequenceData.blocks`) and the
actual durations of its decoding (`Decoding.block_durations`: the stored ones, except where the
scanner session sets a soft delay) as arrays, so it costs O(N) for N blocks. It numbers
the unique RF, gradient and ADC events from 1, in the order of their first use in play order. The
three gradient axes share one index space: in one block, gx comes before gy and gz. The gradient
events are those that the measurements play (`_played`): the events of the file, and in a block
whose gradients the decoding rotates, the rotated event of each axis. The measurements use these
numbers to compute a value one time for each unique event, not one time for each block, and then
give it to each block that plays the event.

`sequence_index` takes a `snapshot.Snapshot` (`analyses.load`) and keeps its result on it.

`_index_from_columns` builds the index from the block IDs, the durations and the event columns,
and `_index_from_data` from a `model.SequenceData` with the event IDs of the file. These two keep
nothing. `_dense_ids` gives the file ID of each dense index of the index of a `SequenceData`.
"""

from typing import NamedTuple

import numpy as np

from .._equality import _freeze, value_dataclass
from ..seqfile.model import SequenceData
from ._played import played_gradients
from .seq_utils import _GRAD_COLUMNS
from .snapshot import Snapshot, _check_snapshot, _kept_results

__all__ = [
    "NO_GRADIENTS",
    "NO_GRADIENTS_IN_WINDOW",
    "SequenceIndex",
    "has_gradients",
    "sequence_index",
]


@value_dataclass
class SequenceIndex:
    """The blocks of one sequence in play order. N is `num_blocks`.

    The event columns hold dense indexes: 0 is no event, and 1 to K number the K unique
    events of that kind in the order of their first use. Their dtype is the smallest of
    uint8, uint16 and uint32 that holds K (one dtype for the three gradient columns).

    The arrays are read-only (`_equality._freeze`: `writeable` is False and cannot be set to
    True): all callers share the index that `sequence_index` keeps, so a change in place would
    change it for all of them. A caller that needs a writable array makes a copy, for example
    `np.array(index.start_s)`.

    Two indexes are equal when each field is equal (`_equality.values_equal`), for example
    two indexes of two reads of one file. An index is not hashable.
    """

    num_blocks: int
    block_id: np.ndarray  # uint32, N: the block ID of the file
    start_s: np.ndarray  # float64, N: the block start, the sequential sum of the durations
    duration_s: np.ndarray  # float64, N
    end_s: float  # the end of the last block, 0.0 without blocks
    rf: np.ndarray  # N, dense RF index
    gx: np.ndarray  # N, dense gradient index (one space for gx, gy and gz)
    gy: np.ndarray
    gz: np.ndarray
    adc: np.ndarray  # N, dense ADC index
    rf_first: np.ndarray  # int64, K_rf: the play index of the first block of RF event k + 1
    grad_first: np.ndarray  # int64, K_grad: the same for gradient event k + 1
    grad_first_axis: np.ndarray  # uint8, K_grad: 0, 1 or 2 for gx, gy or gz in that block
    adc_first: np.ndarray  # int64, K_adc


# The `reason` values of the results: the sequence has no gradient event, or no gradient
# event in the window.
NO_GRADIENTS = "no gradients"
NO_GRADIENTS_IN_WINDOW = "no gradients in the window"


def has_gradients(index: SequenceIndex) -> bool:
    """Whether `index` has a gradient event on any axis."""
    return index.grad_first.size > 0


def sequence_index(snap: Snapshot) -> SequenceIndex:
    """The `SequenceIndex` of `snap`.

    The result is made on the first call and kept on the snapshot, so that several
    measurements of one snapshot build it one time. Raises TypeError for an argument that is
    not a `Snapshot`.
    """
    _check_snapshot(snap)
    kept = _kept_results(snap)
    if "index" not in kept:
        played = played_gradients(snap)
        kept["index"] = _index_from_data(
            snap.data, (played.gx, played.gy, played.gz), snap.decoding.block_durations
        )
    return kept["index"]


def _index_dtype(max_value: int):
    """The smallest of uint8, uint16, uint32 that holds `max_value`."""
    if max_value <= 0xFF:
        return np.uint8
    if max_value <= 0xFFFF:
        return np.uint16
    return np.uint32


# `_dense` uses a lookup table over the ids, unless the largest id is more than this many
# times the number of entries: then it sorts the used ids.
_LUT_LIMIT = 16


def _dense(columns: list[np.ndarray]) -> tuple[list[np.ndarray], np.ndarray]:
    """Dense indexes for columns of event ids (0 = none) that share one id
    space, each with one id for each of the N blocks. The events are numbered 1 to K in
    the order of their first use: block by block, and in one block in the order of
    `columns`. Returns the dense columns, in the smallest dtype that holds K, and the
    first use of each event as the key `block * len(columns) + column`.

    Event ids are small library numbers, so a lookup table over the ids does the work,
    without a sort of the N ids. A file with a large id (more than `_LUT_LIMIT` times the
    number of entries) uses `np.unique` on the used ids: its memory does not grow with
    the largest id."""
    m, n = len(columns), columns[0].size
    top = max((int(col.max()) for col in columns if col.size), default=0)
    if top > _LUT_LIMIT * m * n:
        return _dense_sorted(columns)
    first = np.full(top + 1, m * n, dtype=np.int64)
    for j, col in enumerate(columns):
        np.minimum.at(first, col, np.arange(j, m * n, m, dtype=np.int64))
    used = np.flatnonzero(first[1:] < m * n) + 1
    order = used[np.argsort(first[used])]
    lut = np.zeros(top + 1, dtype=_index_dtype(order.size))
    lut[order] = np.arange(1, order.size + 1)
    return [lut[col] for col in columns], first[order]


def _dense_sorted(columns: list[np.ndarray]) -> tuple[list[np.ndarray], np.ndarray]:
    """`_dense` with `np.unique` of the used ids: the same result, for a large largest id."""
    m, n = len(columns), columns[0].size
    key_ids = np.stack(columns, axis=1).ravel()  # entry block * m + column has this key
    keys = np.flatnonzero(key_ids)
    ids, first_at, inverse = np.unique(key_ids[keys], return_index=True, return_inverse=True)
    first = keys[first_at]
    order = np.argsort(first)
    rank = np.empty(ids.size, dtype=np.int64)
    rank[order] = np.arange(1, ids.size + 1)
    dense = np.zeros(m * n, dtype=_index_dtype(ids.size))
    dense[keys] = rank[inverse.ravel()]
    return [np.ascontiguousarray(dense[j::m]) for j in range(m)], first[order]


def _index_from_columns(
    block_id: np.ndarray,
    duration_s: np.ndarray,
    rf: np.ndarray,
    gx: np.ndarray,
    gy: np.ndarray,
    gz: np.ndarray,
    adc: np.ndarray,
) -> SequenceIndex:
    """The `SequenceIndex` of the blocks with the IDs `block_id` (uint32), the durations
    `duration_s` (float64, s) and the event IDs `rf`, `gx`, `gy`, `gz` and `adc` (0 = none),
    one entry for each block in play order."""
    n = block_id.size
    # The sequential sum start += duration, the same float operations as
    # tests/oracles/blocks.py:iter_blocks: numpy's cumsum adds in order.
    start_s = np.zeros(n, dtype=np.float64)
    if n > 1:
        np.cumsum(duration_s[:-1], out=start_s[1:])
    end_s = float(start_s[-1] + duration_s[-1]) if n else 0.0

    (rf,), rf_first = _dense([rf])
    (adc,), adc_first = _dense([adc])
    # One index space for the three axes: block by block, then gx, gy, gz in one block.
    (gx, gy, gz), grad_key = _dense([gx, gy, gz])

    grad_first = grad_key // 3
    grad_first_axis = (grad_key % 3).astype(np.uint8)
    # Read-only arrays, shared by all callers through the kept index.
    block_id, start_s, duration_s = _freeze(block_id, start_s, duration_s)
    rf, gx, gy, gz, adc = _freeze(rf, gx, gy, gz, adc)
    rf_first, grad_first, grad_first_axis, adc_first = _freeze(
        rf_first, grad_first, grad_first_axis, adc_first
    )

    return SequenceIndex(
        num_blocks=n,
        block_id=block_id,
        start_s=start_s,
        duration_s=duration_s,
        end_s=end_s,
        rf=rf,
        gx=gx,
        gy=gy,
        gz=gz,
        adc=adc,
        rf_first=rf_first,
        grad_first=grad_first,
        grad_first_axis=grad_first_axis,
        adc_first=adc_first,
    )


def _index_from_data(
    data: SequenceData,
    gradients: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
    durations: np.ndarray | None = None,
) -> SequenceIndex:
    """The `SequenceIndex` of `data`: the blocks of `data.blocks` with the durations `durations`
    (s), or the stored ones (`data.block_durations_s`) when it is None. The event IDs are those of
    the file, or for the gradients those of `gradients` (gx, gy and gz, one key for each block)
    when it is given. Raises ValueError that names the ID when a block ID does not fit in
    uint32."""
    blocks = data.blocks
    ids = blocks["id"]
    outside = (ids < 0) | (ids > np.iinfo(np.uint32).max)
    if outside.any():
        raise ValueError(f"block ID {int(ids[outside][0])} does not fit in uint32")
    return _index_from_columns(
        ids.astype(np.uint32),
        data.block_durations_s if durations is None else durations,
        blocks["rf"],
        *(gradients if gradients is not None else (blocks[axis] for axis in _GRAD_COLUMNS)),
        blocks["adc"],
    )


class _DenseIds(NamedTuple):
    """The file ID of each dense event index of a `SequenceIndex` (int64): entry `k - 1` is
    the ID of the event with the dense index `k`."""

    rf: np.ndarray
    grad: np.ndarray  # one ID space for gx, gy and gz, as in the file
    adc: np.ndarray


def _dense_ids(data: SequenceData, index: SequenceIndex) -> _DenseIds:
    """The `_DenseIds` of `index`, the index of `data` (`_index_from_data`): the ID in
    `data.blocks` of each event at its first use (`rf_first`, `grad_first` with
    `grad_first_axis`, and `adc_first`)."""
    blocks = data.blocks
    grad = np.stack([blocks[axis] for axis in _GRAD_COLUMNS], axis=1)
    return _DenseIds(
        blocks["rf"][index.rf_first].astype(np.int64),
        grad[index.grad_first, index.grad_first_axis].astype(np.int64),
        blocks["adc"][index.adc_first].astype(np.int64),
    )
