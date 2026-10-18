"""The gradients that the measurements take from the decoding of a snapshot: the gradient event of
each block and axis, as the points that `_events` joins with straight lines
(`docs/implementation.md`, section 1.2).

The measurements read the gradients only through the decoding (`snapshot.Snapshot.decoding`):

- **A decoded event**, by its file ID: the points that the decoding gives of the event in the
  first block and axis that play it (`Decoding.gradient_points`, not rotated). For `spec` these
  are the points of `seq_utils.gradient_offsets` of the event of `events`. A plugin gives the
  points between which its `gradients_at` draws straight lines, in the same layout. A decoded
  event whose points are all at one time (an event of length 0, such as a trapezoid with rise,
  flat and fall times 0) has no segment, and `gradients_at` gives 0 for it at each time but that
  one, so its points keep their times and get the values 0, whatever values the decoding gives
  them.
- **A variant of a decoded event**: a plugin can decode one event otherwise in two blocks (a
  reader can decode the gradients of a block into one buffer). Its `Decoding.gradient_variants`
  then says which cells (a block and an axis) decode alike: those with the same event and the
  same variant. Each pair of an event and a variant is an event of its own, with the points of
  its first cell. The pair of the first cell that plays the event
  keeps the file ID; each other pair gets a new key above the largest file ID. With no
  variants (None, as for `spec`), every block that plays an event has the points of the first.
- **The events of a block that `gradients_at` gives**: a block that the decoding rotates by a
  rotation that is not the identity (the blocks of `rotations` when `rotation_record.rotated` is
  not 0: `spec` from 1.5.1, P20, and a plugin that applies them), a block that the scanner
  session's field of view rotates or scales (the blocks without NOROT, or without the scaling
  flag, of `fov_flags`, when the session rotates or scales), and a block with an event
  that ends after the end of the block (a plugin can play it; `spec` rejects it,
  `block.event-too-long`; `gradients_at` is 0 after the block). The package does not rotate. The gradients of such a block are straight lines
  between the times of the points of its events, up to the end of the block, so its event of an
  axis has a point at each of these times, with the value of `gradients_at` there. There are
  always two times or more: the end of the block is a time when an event goes on after it, and
  when every point of the events is at one time (an event of length 0); with no point before the
  end, the block start is a time too (the events lie wholly after the end, or at it). So a block
  of duration 0 has the times 0 and 0. The end of a block is its actual duration
  (`Decoding.block_durations`). Where an event
  of the block has a step (it starts or ends at a value that is not 0, or has two points at one
  time), and at the end of a block that cuts an event, the event has two points at that time: the
  value just before and the value just after, each the straight line of `gradients_at` at two
  times inside the next segment, carried to its end. A rotated block (by its rotation or by the
  field of view) has an event on each axis; another block on the axes where it has an event.

`played_gradients(snap)` gives the key of the event of each block and axis: 0 for none, the file
ID of a decoded event, a key above the largest file ID for each other variant of a decoded
event, and a key above those for an event that `gradients_at` gives (one for each axis of each
distinct such block: the same events, rotation, flags of the field of view and duration).
Two blocks with one key play the same event. The result is kept on the snapshot.
"""

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from .._equality import _freeze
from .decoding import Points
from .seq_utils import _GRAD_COLUMNS, TIME_TOLERANCE
from .snapshot import Snapshot, _kept_results


@dataclasses.dataclass(frozen=True, eq=False)
class PlayedGradients:
    """The gradient event of each block and axis of one snapshot (the module docstring).

    `gx`, `gy` and `gz` (int64, one entry for each block in play order) are the keys: 0 for no
    event, the file ID of a decoded event, or a key above the largest file ID for another
    variant of a decoded event or for an event that `gradients_at` gives. `points` gives the
    points of the event of each key. The arrays are read-only."""

    gx: np.ndarray
    gy: np.ndarray
    gz: np.ndarray
    points: Mapping[int, Points]


def played_gradients(snap: Snapshot) -> PlayedGradients:
    """The `PlayedGradients` of `snap`, made on the first call and kept on the snapshot. `snap`
    must be a `Snapshot`: the caller has called `_check_snapshot`."""
    kept = _kept_results(snap)
    if "played" not in kept:
        kept["played"] = _played(snap)
    return kept["played"]


def _played(snap: Snapshot) -> PlayedGradients:
    """The `PlayedGradients` of `snap`, without the keep of `played_gradients`."""
    data, decoding = snap.data, snap.decoding
    columns = [np.asarray(data.blocks[axis], dtype=np.int64).copy() for axis in _GRAD_COLUMNS]
    duration = decoding.block_durations

    # Each decoded event, at the first block and axis that play it; with variants, each pair of
    # an event and a variant, at its first cell, under its own key.
    variants = decoding.gradient_variants()
    if variants is None:
        stacked = np.stack(columns, axis=1).ravel()  # block * 3 + axis
        keys, first = np.unique(stacked, return_index=True)
        points: dict[int, Points] = {
            int(key): decoding.gradient_points(int(key), int(at) // 3, int(at) % 3)
            for key, at in zip(keys.tolist(), first.tolist(), strict=True)
            if key != 0
        }
    else:
        points = _variants(snap, columns, variants)
        keys = np.unique(np.concatenate(columns))

    # The blocks whose events `gradients_at` gives: those that the decoding rotates (not by the
    # identity) or the session's field of view rotates, those that the field of view scales, and
    # those with an event that ends after the end of the block.
    rotated = np.zeros(duration.size, dtype=bool)
    if decoding.rotation_record.rotated:
        blocks, quaternions = decoding.rotations()
        rotated[blocks[np.any(quaternions[:, 1:] != 0, axis=1)]] = True
    norot, noscale = decoding.fov_flags()
    if decoding.session.rotates:
        rotated |= ~norot
    scaled = ~noscale if decoding.session.scales else np.zeros(duration.size, dtype=bool)
    # The end of each event, by the position of its key in `keys` (sorted; no table as long as
    # the largest ID).
    end = np.array(
        [0.0 if key == 0 else points[key][0] + points[key][1][-1] for key in keys.tolist()]
    )
    has_gradient = np.zeros(duration.size, dtype=bool)
    too_long = np.zeros(duration.size, dtype=bool)
    for column in columns:
        has_gradient |= column != 0
        too_long |= (column != 0) & (end[np.searchsorted(keys, column)] > duration + TIME_TOLERANCE)
    special = np.flatnonzero(((rotated | scaled) & has_gradient) | too_long)
    decoded = list(points)
    if special.size:
        flags = norot.astype(np.int64) + 2 * noscale.astype(np.int64)
        _from_gradients_at(snap, special, rotated[special], flags, columns, points)
    # A decoded event whose points are all at one time (an event of length 0) plays 0: the
    # straight lines of `gradients_at` have no segment between its points, and are 0 before and
    # after them. Its points keep their times. This comes after `_from_gradients_at`, whose plans
    # take the steps of a block from the decoded values: at a step, the values just before and
    # just after the time of such an event, not the value at that time.
    for key in decoded:
        delay, offsets, amp = points[key]
        if np.size(offsets) and np.all(offsets == offsets[0]):
            points[key] = (delay, offsets, np.zeros(np.shape(amp)))
    gx, gy, gz = _freeze(*columns)
    return PlayedGradients(gx, gy, gz, MappingProxyType(points))


def _variants(snap: Snapshot, columns: list[np.ndarray], variants: np.ndarray) -> dict[int, Points]:
    """Give each pair of a gradient event and a variant (`Decoding.gradient_variants`, an array
    (blocks, 3)) its key in `columns` (the module docstring): the pair of the first cell that
    plays the event keeps the file ID, and each other pair gets a new key above the largest key
    of the columns, in the order of their first cells. Returns the points of each key, which the
    decoding gives at the first cell of its pair."""
    events = np.stack(columns, axis=1).ravel()  # block * 3 + axis
    played = np.flatnonzero(events)
    cells = np.stack([events[played], np.asarray(variants, dtype=np.int64).ravel()[played]], axis=1)
    pairs, first, inverse = np.unique(cells, axis=0, return_index=True, return_inverse=True)
    first = played[first]  # the first cell of each pair, sorted by event, then by variant
    # The pairs of one event are adjacent: the one with the first cell of the event keeps its ID.
    _, starts, counts = np.unique(pairs[:, 0], return_index=True, return_counts=True)
    earliest = np.repeat(np.minimum.reduceat(first, starts), counts) if pairs.size else first
    key = pairs[:, 0].copy()
    others = np.flatnonzero(first != earliest)
    others = others[np.argsort(first[others], kind="stable")]
    key[others] = int(events.max(initial=0)) + 1 + np.arange(others.size)
    renamed = events.copy()
    renamed[played] = key[inverse.ravel()]
    for axis, column in enumerate(columns):
        column[:] = renamed[axis::3]
    decoding = snap.decoding
    return {
        int(k): decoding.gradient_points(int(event), int(at) // 3, int(at) % 3)
        for k, event, at in zip(key.tolist(), pairs[:, 0].tolist(), first.tolist(), strict=True)
    }


def _from_gradients_at(
    snap: Snapshot,
    blocks: np.ndarray,
    rotated: np.ndarray,
    flags: np.ndarray,
    columns: list[np.ndarray],
    points: dict[int, Points],
) -> None:
    """Give each of `blocks` (play indices) the events that `gradients_at` gives (the module
    docstring): new keys in `columns`, and their points in `points`. `rotated` says which blocks
    the decoding rotates: these get an event on each axis, the others on the axes with an event.
    `flags` are the flags of the field of view of each block of the sequence (an int).

    The blocks with the same events, rotation, flags and duration are a group, numbered in the
    order of their first blocks, with the keys `base + 3 * group + axis`. The groups with the
    same events and duration share one plan (`_plan`), and one `gradients_at` reads them all."""
    decoding = snap.decoding
    duration = np.asarray(decoding.block_durations, dtype=np.float64)[blocks]
    base = max(int(column.max(initial=0)) for column in columns) + 1
    events = np.stack([column[blocks] for column in columns], axis=1)

    # The key of each block as int64 columns: the events, the flags, the duration (by value: 0.0
    # and -0.0 alike, and each NaN apart), and the bytes of the quaternion of a rotated block
    # with one (by bytes), or none.
    nan = np.isnan(duration)
    nan_id = np.where(nan, np.arange(blocks.size), -1)[:, None]
    by_value = np.where(nan, 0.0, duration + 0.0).view(np.int64)[:, None]
    quaternion = np.zeros((blocks.size, 1), dtype=np.int64)
    if rotated.any():
        indices, quaternions = decoding.rotations()
        indices = np.asarray(indices, dtype=np.int64)
        # The row of the quaternion of each block (the last row of a block given twice).
        position = np.full(int(blocks.max()) + 1, -1, dtype=np.int64)
        present, last = np.unique(indices[::-1], return_index=True)
        inside = (present >= 0) & (present < position.size)
        position[present[inside]] = indices.size - 1 - last[inside]
        at = position[blocks]
        has = rotated & (at >= 0)
        rows = np.ascontiguousarray(quaternions)
        row_bytes = rows.view(np.uint8).reshape(rows.shape[0], rows[:1].nbytes)
        row_bytes = np.pad(row_bytes, ((0, 0), (0, -row_bytes.shape[1] % 8)))
        quaternion = np.zeros((blocks.size, 1 + row_bytes.shape[1] // 8), dtype=np.int64)
        quaternion[has, 0] = 1
        quaternion[has, 1:] = row_bytes.view(np.int64)[at[has]]
    keys = np.concatenate([events, flags[blocks][:, None], by_value, nan_id, quaternion], axis=1)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first)
    rank = np.empty(order.size, dtype=np.int64)
    rank[order] = np.arange(order.size)
    group_of = rank[inverse.ravel()]
    first = first[order]  # the first of `blocks` of each group, in group order
    first_block = blocks[first]

    # The plans: the groups with the same events and duration (by its bytes, as `_plan` reads
    # it, and each NaN apart). The plan of a block depends on these alone, so each plan is made
    # at the first block of its first group.
    plan_keys = np.concatenate([events, duration.view(np.int64)[:, None], nan_id], axis=1)[first]
    _, plan_first, plan_of_group = np.unique(
        plan_keys, axis=0, return_index=True, return_inverse=True
    )
    plan_of_group = plan_of_group.ravel()
    plans = [_plan(snap, int(first_block[group]), columns, points) for group in plan_first]

    # The times at which `gradients_at` is read: those of the plan of each group, at its first
    # block, in group order.
    size = np.array([plan[2].size for plan in plans], dtype=np.int64)
    plan_start = np.cumsum(size) - size
    group_size = size[plan_of_group]
    group_start = np.cumsum(group_size) - group_size
    within = np.arange(int(group_size.sum())) - np.repeat(group_start, group_size)
    pairs_time_s = np.concatenate([plan[2] for plan in plans])[
        np.repeat(plan_start[plan_of_group], group_size) + within
    ]
    pairs_block = np.repeat(first_block, group_size)
    values = decoding.gradients_at(pairs_block, pairs_time_s * 1e6)

    # The points of each group, from the reads of the groups of each plan together. The keys of
    # a plan's groups share its offsets, and the three axes of a group share its values, so
    # these are read-only. The points are added in the order of the keys.
    delays: list[float] = [0.0] * first.size
    offsets_of: list[np.ndarray] = [np.empty(0)] * first.size
    amp_of: list[np.ndarray] = [np.empty(0)] * first.size
    by_plan = np.argsort(plan_of_group, kind="stable")
    bounds = np.cumsum(np.bincount(plan_of_group, minlength=len(plans)))[:-1]
    for (times, steps, reads), groups in zip(plans, np.split(by_plan, bounds), strict=True):
        read = values[group_start[groups][:, None] + np.arange(reads.size)]
        offsets, amp = _points(times, steps, read)
        offsets.flags.writeable = False
        amp.flags.writeable = False
        delay = float(times[0])
        for i, group in enumerate(groups.tolist()):
            delays[group], offsets_of[group], amp_of[group] = delay, offsets, amp[i]
    for group in range(first.size):
        for axis in range(3):
            points[base + 3 * group + axis] = (
                delays[group],
                offsets_of[group],
                amp_of[group][:, axis],
            )
    for axis, column in enumerate(columns):
        keep = ~rotated & (column[blocks] == 0)  # no event on this axis, and no rotation
        column[blocks] = np.where(keep, 0, base + 3 * group_of + axis)


def _plan(
    snap: Snapshot, block: int, columns: list[np.ndarray], points: dict[int, Points]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For the block `block`: the times of the points of its events up to the end of the block
    (s from the block start, sorted), two or more: with the end of the block when an event goes
    on after it or when every point is at one time, and the block start before it when no point
    is before the end; whether `gradients_at` has a step at each (the end, when it is added, is
    one), and the times at which it is read: each time, then two times inside each segment (at a
    quarter and at three quarters of it), in this order. The times are distinct, except the start
    and the end of a block of duration 0."""
    duration = float(snap.decoding.block_durations[block])
    all_times: list[np.ndarray] = []
    step_times: list[float] = []
    for column in columns:
        key = int(column[block])
        if key == 0:
            continue
        delay, offsets, amp = points[key]
        t = delay + offsets
        all_times.append(t)
        if amp[0] != 0:
            step_times.append(float(t[0]))
        if amp[-1] != 0:
            step_times.append(float(t[-1]))
        same = (np.diff(t) == 0) & (np.diff(amp) != 0)
        step_times.extend(t[1:][same].tolist())
    times = np.unique(np.concatenate(all_times))
    # Two times or more: the times stop at the end of the block when an event goes on after it
    # (`gradients_at` is 0 after the end), and go on to it when every point is at one time. With
    # no point before the end, they start at the block start. The end is a step: its value is the
    # one just before it, from the two reads inside the last segment, so it is the value that
    # plays in the block whatever `gradients_at` gives at the end itself.
    if times[-1] > duration + TIME_TOLERANCE or times.size == 1:
        before = times[times < duration - TIME_TOLERANCE]
        times = np.append(before if before.size else 0.0, duration)
        step_times.append(duration)
    steps = np.isin(times, np.asarray(step_times, dtype=np.float64))
    quarter = np.diff(times) / 4
    inside = np.stack([times[:-1] + quarter, times[1:] - quarter], axis=1).ravel()
    return times, steps, np.concatenate([times, inside])


def _points(
    times: np.ndarray, steps: np.ndarray, read: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The offsets (from the first time) and the values (g, n, 3) of the points of the g rotated
    blocks of one plan (`_plan`): the values that `gradients_at` gave at `times` (the first
    `times.size` rows of each block of `read`, an array (g, rows, 3)), and at a step the value
    just before and the value just after, from the two reads inside each segment (the following
    rows of each block of `read`, as `_plan` orders them). The offsets are the same for every
    block."""
    n = times.size
    at_times, inside = read[:, :n], read[:, n:].reshape(read.shape[0], -1, 2, 3)
    # The two reads are half a segment apart: half their difference is the change over a quarter.
    half = (inside[:, :, 1] - inside[:, :, 0]) / 2
    before_end = inside[:, :, 1] + half  # the value at the end of each segment
    after_start = inside[:, :, 0] - half  # the value at the start of each segment
    # The rows of `table` that give the points: `at_times` (n), then `before_end` and
    # `after_start` (n - 1 each).
    table = np.concatenate([at_times, before_end, after_start], axis=1)
    point_times: list[float] = []
    sources: list[int] = []
    for i in range(n):
        if not steps[i]:
            point_times.append(float(times[i]))
            sources.append(i)
            continue
        if i > 0:
            point_times.append(float(times[i]))
            sources.append(n + i - 1)
        if i < n - 1:
            point_times.append(float(times[i]))
            sources.append(2 * n - 1 + i)
    if not point_times:  # every point at one time, a step: the value there
        point_times, sources = [float(times[0])], [0]
    t = np.asarray(point_times, dtype=np.float64)
    return t - t[0], np.asarray(table[:, sources], dtype=np.float64)
