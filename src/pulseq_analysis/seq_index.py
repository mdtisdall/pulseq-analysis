"""The block table of one sequence, in play order, with dense event indexes.

`sequence_index` reads `seq.block_events` as one array and `seq.block_durations` as one
vector (`seq` is the sequence of the snapshot), without `get_block`, so it costs O(N) for N
blocks with no per-block pypulseq call. It numbers the unique RF, gradient and ADC events from 1, in the order of their
first use in play order. The three gradient axes share one index space: in one block, gx
comes before gy and gz. The measurements use these numbers to compute a value one time
for each unique event, not one time for each block, and then give it to each block that
plays the event.

All the functions take a `snapshot.Snapshot` (`snapshot.load`) and keep their result on it.
The sequence of a snapshot does not change, and `load` has refused an unsigned sequence and a
sequence with a rotation, so these functions check neither.

`rf_events`, `grad_events` and `adc_events` give each unique event one time, from the
first block that uses it, as a tuple that is made on the first call and kept. Only they call
`get_block`. The block cache of the sequence of a snapshot is off (`load`), so pypulseq keeps
no block.
"""

from types import SimpleNamespace

import numpy as np
import pypulseq as pp

from ._equality import _freeze, value_dataclass
from .seq_utils import GRAD_COLUMNS
from .snapshot import Snapshot, _check_snapshot, _kept_results

# The columns of a row of `seq.block_events`.
_RF, _GX, _GY, _GZ, _ADC = 1, 2, 3, 4, 5


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
    block_id: np.ndarray  # uint32, N: the pypulseq block id
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
        kept["index"] = _build_index(snap.sequence)
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
    """Dense indexes for columns of pypulseq event ids (0 = none) that share one id
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


def _build_index(seq: pp.Sequence) -> SequenceIndex:
    """The `SequenceIndex` of `seq`, built from `seq.block_events` and `seq.block_durations`
    without the keep of `sequence_index`."""
    block_events = seq.block_events
    n = len(block_events)
    block_id = np.fromiter(block_events.keys(), dtype=np.uint32, count=n)
    durations = seq.block_durations
    if len(durations) == n and np.array_equal(
        np.fromiter(durations.keys(), dtype=np.uint32, count=n), block_id
    ):
        duration_s = np.fromiter(durations.values(), dtype=np.float64, count=n)
    else:  # the durations are not in the order of the blocks
        duration_s = np.fromiter((durations[b] for b in block_events), dtype=np.float64, count=n)
    # The sequential sum start += duration, the same float operations as
    # tests/oracles/blocks.py:iter_blocks: numpy's cumsum adds in order.
    start_s = np.zeros(n, dtype=np.float64)
    if n > 1:
        np.cumsum(duration_s[:-1], out=start_s[1:])
    end_s = float(start_s[-1] + duration_s[-1]) if n else 0.0

    try:
        rows = np.asarray(list(block_events.values()))
    except ValueError:  # the rows differ in length
        rows = None
    if rows is not None and rows.ndim == 2 and rows.shape[1] > _ADC:
        # one read of the block dict, then a copy of each column
        def column(col: int) -> np.ndarray:
            return np.ascontiguousarray(rows[:, col], dtype=np.int32)
    else:

        def column(col: int) -> np.ndarray:
            return np.fromiter((ev[col] for ev in block_events.values()), dtype=np.int32, count=n)

    (rf,), rf_first = _dense([column(_RF)])
    (adc,), adc_first = _dense([column(_ADC)])
    # One index space for the three axes: block by block, then gx, gy, gz in one block.
    (gx, gy, gz), grad_key = _dense([column(_GX), column(_GY), column(_GZ)])

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


def _first_events(
    snap: Snapshot, first: np.ndarray, attrs: list[str]
) -> tuple[tuple[int, SimpleNamespace], ...]:
    """(dense index, event) for each unique event, in dense order: attribute `attrs[k]`
    of the block at play index `first[k]`. A block is read one time for consecutive
    events in it."""
    seq, block_id = snap.sequence, sequence_index(snap).block_id
    events = []
    position, block = -1, None
    for k, (p, attr) in enumerate(zip(first.tolist(), attrs, strict=True)):
        if p != position:
            position, block = p, seq.get_block(int(block_id[p]))
        events.append((k + 1, getattr(block, attr)))
    return tuple(events)


def rf_events(snap: Snapshot) -> tuple[tuple[int, SimpleNamespace], ...]:
    """(dense index, event) for each unique RF event of `snap`, in dense order, as a tuple.

    The tuple is made on the first call and kept on the snapshot. The events are the objects
    that `get_block` gives, shared by all callers: a caller must not change them. Raises
    TypeError for an argument that is not a `Snapshot`."""
    _check_snapshot(snap)
    kept = _kept_results(snap)
    if "rf_events" not in kept:
        first = sequence_index(snap).rf_first
        kept["rf_events"] = _first_events(snap, first, ["rf"] * first.size)
    return kept["rf_events"]


def grad_events(snap: Snapshot) -> tuple[tuple[int, SimpleNamespace], ...]:
    """(dense index, event) for each unique gradient event of `snap`, in dense order, as a
    tuple, kept as `rf_events` is, with the same rules for the events. The axis of the block
    where it is first used is `sequence_index(snap).grad_first_axis[k - 1]`."""
    _check_snapshot(snap)
    kept = _kept_results(snap)
    if "grad_events" not in kept:
        index = sequence_index(snap)
        attrs = [GRAD_COLUMNS[a] for a in index.grad_first_axis.tolist()]
        kept["grad_events"] = _first_events(snap, index.grad_first, attrs)
    return kept["grad_events"]


def adc_events(snap: Snapshot) -> tuple[tuple[int, SimpleNamespace], ...]:
    """(dense index, event) for each unique ADC event of `snap`, in dense order, as a tuple,
    kept as `rf_events` is, with the same rules for the events."""
    _check_snapshot(snap)
    kept = _kept_results(snap)
    if "adc_events" not in kept:
        first = sequence_index(snap).adc_first
        kept["adc_events"] = _first_events(snap, first, ["adc"] * first.size)
    return kept["adc_events"]
