"""The block table of one sequence, in play order, with dense event indexes.

`sequence_index` reads `seq.block_events` as one array and `seq.block_durations` as one
vector, without `get_block`, so it costs O(N) for N blocks with no per-block pypulseq
call. It numbers the unique RF, gradient and ADC events from 1, in the order of their
first use in play order. The three gradient axes share one index space: in one block, gx
comes before gy and gz. The measurements use these numbers to compute a value one time
for each unique event, not one time for each block, and then give it to each block that
plays the event.

`sequence_index` refuses a sequence with no `[SIGNATURE]` hash
(`extensions.refuse_unsigned`). Each measurement reads the index before it reads a block,
so each one refuses an unsigned sequence through it.

`rf_events`, `grad_events` and `adc_events` give each unique event one time, from the
first block that uses it. Only they call `get_block`, with the block cache off
(`block_cache_off`): pypulseq keeps every block that `get_block` reads in
`seq.block_cache` when `use_block_cache` is True, and nothing removes it.
"""

import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pypulseq as pp

from ._equality import value_dataclass
from ._kept import _Entry, kept_results
from .extensions import refuse_unsigned
from .seq_utils import GRAD_COLUMNS

# The columns of a row of `seq.block_events`.
_RF, _GX, _GY, _GZ, _ADC = 1, 2, 3, 4, 5


@value_dataclass
class SequenceIndex:
    """The blocks of one sequence in play order. N is `num_blocks`.

    The event columns hold dense indexes: 0 is no event, and 1 to K number the K unique
    events of that kind in the order of their first use. Their dtype is the smallest of
    uint8, uint16 and uint32 that holds K (one dtype for the three gradient columns).

    The arrays are read-only (`writeable` is False): all callers share the index that
    `sequence_index` keeps, so a change in place would change it for all of them. A caller
    that needs a writable array makes a copy, for example `np.array(index.start_s)`.

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


# One index for each sequence object, under the key "index" of its kept results.
_CACHE: "weakref.WeakKeyDictionary[pp.Sequence, _Entry]" = weakref.WeakKeyDictionary()


def sequence_index(seq: pp.Sequence) -> SequenceIndex:
    """The `SequenceIndex` of `seq`.

    Raises `ValueError` for a sequence with no `[SIGNATURE]` hash
    (`extensions.refuse_unsigned`, before the kept results are read). The hash is
    not part of the rule for a new build (`_kept`): the hash can be stale.

    The result is kept for the sequence object, so that several measurements of one
    sequence build it one time. It is built again after `add_block`, after a new read of
    a file into the object, and after a change of `seq.grad_raster_time` (the rule of
    `_kept`). A change that keeps the number of blocks and the last block id and does not
    replace `seq.block_events`, `seq.block_durations` or `seq.grad_library` is not seen:
    `mod_grad_axis` and `flip_grad_axis` (they rewrite the entries of `seq.grad_library`),
    `set_block` on a block id that exists, `apply_soft_delay` (it writes the values of
    `seq.block_durations`), and a direct write into `seq.block_events`, `seq.block_durations`
    or a library. Build a new sequence object for it.
    """
    refuse_unsigned(seq)
    kept = kept_results(_CACHE, seq)
    if "index" not in kept:
        kept["index"] = _build_index(seq)
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
    without the cache of `sequence_index`."""
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
    arrays = (
        block_id, start_s, duration_s, rf, gx, gy, gz, adc,
        rf_first, grad_first, grad_first_axis, adc_first,
    )  # fmt: skip
    for array in arrays:
        array.flags.writeable = False  # shared by all callers through the kept index

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


@contextmanager
def block_cache_off(seq: pp.Sequence) -> Iterator[None]:
    """Turn pypulseq's block cache off for `seq` while the block runs, and give back the
    old setting after it, also after an error. Blocks already in `seq.block_cache` stay
    there."""
    old = seq.use_block_cache
    seq.use_block_cache = False
    try:
        yield
    finally:
        seq.use_block_cache = old


def _first_events(
    seq: pp.Sequence, index: SequenceIndex, first: np.ndarray, attrs: list[str]
) -> Iterator[tuple[int, SimpleNamespace]]:
    """(dense index, event) for each unique event, in dense order: attribute `attrs[k]`
    of the block at play index `first[k]`. A block is read one time for consecutive
    events in it."""
    with block_cache_off(seq):
        position, block = -1, None
        for k, (p, attr) in enumerate(zip(first.tolist(), attrs, strict=True)):
            if p != position:
                position, block = p, seq.get_block(int(index.block_id[p]))
            yield k + 1, getattr(block, attr)


def rf_events(seq: pp.Sequence, index: SequenceIndex) -> Iterator[tuple[int, SimpleNamespace]]:
    """(dense index, event) for each unique RF event of `seq`, in dense order."""
    return _first_events(seq, index, index.rf_first, ["rf"] * index.rf_first.size)


def grad_events(seq: pp.Sequence, index: SequenceIndex) -> Iterator[tuple[int, SimpleNamespace]]:
    """(dense index, event) for each unique gradient event of `seq`, in dense order. The
    axis of the block where it is first used is `index.grad_first_axis[k - 1]`."""
    attrs = [GRAD_COLUMNS[a] for a in index.grad_first_axis.tolist()]
    return _first_events(seq, index, index.grad_first, attrs)


def adc_events(seq: pp.Sequence, index: SequenceIndex) -> Iterator[tuple[int, SimpleNamespace]]:
    """(dense index, event) for each unique ADC event of `seq`, in dense order."""
    return _first_events(seq, index, index.adc_first, ["adc"] * index.adc_first.size)
