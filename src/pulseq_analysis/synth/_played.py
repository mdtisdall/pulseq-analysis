"""The gradients that the measurements take from the decoding of a snapshot: the gradient event of
each block and axis, as the points that `_events` joins with straight lines
(`docs/implementation.md`, section 1.2).

The measurements read the gradients only through the decoding (`snapshot.Snapshot.decoding`):

- **A decoded event**, by its file ID: the points that the decoding gives of the event in the
  first block and axis that play it (`Decoding.gradient_points`, not rotated). For `spec` these
  are the points of `seq_utils.gradient_offsets` of the event of `events`. A plugin gives the
  points between which its `gradients_at` draws straight lines, in the same layout; the first
  block that plays an event gives its points in every block, so a plugin's decoding of a gradient
  event must not depend on the block that plays it.
- **The events of a block that `gradients_at` gives**: a block that the decoding rotates by a
  rotation that is not the identity (the blocks of `rotations` when `rotation_record.rotated` is
  not 0: `spec` from 1.5.1, P20, and a plugin that applies them), and a block with an event
  that ends after the end of the block (a plugin can play it; `spec` rejects it,
  `block.event-too-long`; `gradients_at` is 0 after the block). The package does not rotate. The gradients of such a block are straight lines
  between the times of the points of its events, up to the end of the block, so its event of an
  axis has a point at each of these times, with the value of `gradients_at` there. Where an event
  of the block has a step (it starts or ends at a value that is not 0, or has two points at one
  time), and at the end of a block that cuts an event, the event has two points at that time: the
  value just before and the value just after, each the straight line of `gradients_at` at two
  times inside the next segment, carried to its end. A rotated block has an event on each axis;
  another block on the axes where it has an event.

`played_gradients(snap)` gives the key of the event of each block and axis: 0 for none, the file
ID of a decoded event, and a key above the largest file ID for an event that `gradients_at`
gives (one for each axis of each distinct such block: the same events, rotation and duration).
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
    event, the file ID of a decoded event, or a key above the largest file ID for an event that
    `gradients_at` gives. `points` gives the points of the event of each key. The arrays are
    read-only."""

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
    duration = data.block_durations_s

    # Each decoded event, at the first block and axis that play it.
    stacked = np.stack(columns, axis=1).ravel()  # block * 3 + axis
    keys, first = np.unique(stacked, return_index=True)
    points: dict[int, Points] = {
        int(key): decoding.gradient_points(int(key), int(at) // 3, int(at) % 3)
        for key, at in zip(keys.tolist(), first.tolist(), strict=True)
        if key != 0
    }

    # The blocks whose events `gradients_at` gives: those that the decoding rotates (not by the
    # identity), and those with an event that ends after the end of the block.
    rotated = np.zeros(duration.size, dtype=bool)
    if decoding.rotation_record.rotated:
        blocks, quaternions = decoding.rotations()
        rotated[blocks[np.any(quaternions[:, 1:] != 0, axis=1)]] = True
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
    special = np.flatnonzero((rotated & has_gradient) | too_long)
    if special.size:
        _from_gradients_at(snap, special, rotated[special], columns, points)
    gx, gy, gz = _freeze(*columns)
    return PlayedGradients(gx, gy, gz, MappingProxyType(points))


def _from_gradients_at(
    snap: Snapshot,
    blocks: np.ndarray,
    rotated: np.ndarray,
    columns: list[np.ndarray],
    points: dict[int, Points],
) -> None:
    """Give each of `blocks` (play indices) the events that `gradients_at` gives (the module
    docstring): new keys in `columns`, and their points in `points`. `rotated` says which blocks
    the decoding rotates: these get an event on each axis, the others on the axes with an event."""
    decoding = snap.decoding
    duration = snap.data.block_durations_s
    quaternion: dict[int, bytes] = {}
    if rotated.any():
        indices, quaternions = decoding.rotations()
        quaternion = {int(b): q.tobytes() for b, q in zip(indices, quaternions, strict=True)}
    base = max(int(column.max(initial=0)) for column in columns) + 1
    groups: dict[tuple, int] = {}  # the events, the rotation and the duration -> the group
    first_block: list[int] = []
    group_of = np.empty(blocks.size, dtype=np.int64)
    for i, block in enumerate(blocks.tolist()):
        key = (
            tuple(int(column[block]) for column in columns),
            quaternion.get(block) if rotated[i] else None,
            float(duration[block]),
        )
        if key not in groups:
            groups[key] = len(first_block)
            first_block.append(block)
        group_of[i] = groups[key]

    # The times of each group, with the steps, and the times at which `gradients_at` is read.
    plans = [_plan(snap, block, columns, points) for block in first_block]
    pairs_block = np.concatenate(
        [np.full(plan[2].size, block) for plan, block in zip(plans, first_block, strict=True)]
    )
    pairs_time_s = np.concatenate([plan[2] for plan in plans])
    values = decoding.gradients_at(pairs_block, pairs_time_s * 1e6)
    at = 0
    for group, (times, steps, reads) in enumerate(plans):
        read = values[at : at + reads.size]
        at += reads.size
        offsets, amp = _points(times, steps, read)
        for axis in range(3):
            points[base + 3 * group + axis] = (float(times[0]), offsets, amp[:, axis])
    for axis, column in enumerate(columns):
        keep = ~rotated & (column[blocks] == 0)  # no event on this axis, and no rotation
        column[blocks] = np.where(keep, 0, base + 3 * group_of + axis)


def _plan(
    snap: Snapshot, block: int, columns: list[np.ndarray], points: dict[int, Points]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For the block `block`: the times of the points of its events up to the end of the block
    (s from the block start, sorted, distinct), with the end of the block when an event goes on
    after it, whether `gradients_at` has a step at each, and the times at which it is read: each
    time, then two times inside each segment (at a quarter and at three quarters of it), in this
    order."""
    duration = float(snap.data.block_durations_s[block])
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
    if times[-1] > duration + TIME_TOLERANCE:  # `gradients_at` is 0 after the end of the block
        times = np.append(times[times < duration - TIME_TOLERANCE], duration)
        step_times.append(duration)
    steps = np.isin(times, np.asarray(step_times, dtype=np.float64))
    quarter = np.diff(times) / 4
    inside = np.stack([times[:-1] + quarter, times[1:] - quarter], axis=1).ravel()
    return times, steps, np.concatenate([times, inside])


def _points(
    times: np.ndarray, steps: np.ndarray, read: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The offsets (from the first time) and the values (n, 3) of the points of a rotated block:
    the values that `gradients_at` gave at `times` (the first `times.size` rows of `read`), and
    at a step the value just before and the value just after, from the two reads inside each
    segment (the following rows of `read`, as `_plan` orders them)."""
    n = times.size
    at_times, inside = read[:n], read[n:].reshape(-1, 2, 3)
    # The two reads are half a segment apart: half their difference is the change over a quarter.
    half = (inside[:, 1] - inside[:, 0]) / 2
    before_end = inside[:, 1] + half  # the value at the end of each segment
    after_start = inside[:, 0] - half  # the value at the start of each segment
    point_times: list[float] = []
    point_values: list[np.ndarray] = []
    for i in range(n):
        if not steps[i]:
            point_times.append(float(times[i]))
            point_values.append(at_times[i])
            continue
        if i > 0:
            point_times.append(float(times[i]))
            point_values.append(before_end[i - 1])
        if i < n - 1:
            point_times.append(float(times[i]))
            point_values.append(after_start[i])
    if not point_times:  # every point at one time, a step: the value there
        point_times, point_values = [float(times[0])], [at_times[0]]
    t = np.asarray(point_times, dtype=np.float64)
    return t - t[0], np.asarray(point_values, dtype=np.float64).reshape(-1, 3)
