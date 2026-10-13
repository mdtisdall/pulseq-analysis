"""The checks of undefined behaviour of the C++ reader (section 5.3 of
docs/plans/parser-redesign.md in pulseq-analysis). Each runs on what `ExternalSequence::load` put
in its libraries (the reader's own reading of the file, `Libraries`) and follows what `GetBlock`
and `decodeBlock` would do with it, without running them. `undefined_behaviour` returns the first
case it finds, with its code.

The checks are safety-critical: a case that they miss runs in the process, and can end it or
corrupt it silently. tests/test_fuzz.py compares them with the sanitized build of the reader.

They look at every block, whether or not an earlier block would make `decodeBlock` return false,
because `Sequence.decode_block` decodes any block. Within a block they are a superset: a step of
`decodeBlock` that a clean rejection earlier in the same block would skip is still checked. Such
a file is rejected either way; it only gets the code of the case instead of the plain rejection.
Where the reader takes another path and reads no more (a regular RF time shape is not
decompressed; the resampling needs the times), the checks follow it, so that a file that the
reader reads is not rejected.

"cpp:N" is a line of `src/ExternalSequence.cpp` of pulseq/pulseq at c7469123.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from . import Libraries

INT_MIN, INT_MAX = -(2**31), 2**31 - 1

# The code of each case, with the ID of its entry (section 2.2 of docs/specification.md).
CODES = {
    "ub.shape-missing": "D5.1",
    "ub.rf-time-id-minus-1": "D5.3",
    "ub.extension-cycle": "D5.4",
    "ub.shape-decompression": "D5.5",
    "ub.shape-empty": "D5.6",
    "ub.rf-shape-lengths": "D5.7",
    "ub.rf-time-overrun": "D5.8",
    "ub.rf-time-range": "D5.9",
    "ub.gradient-time-range": "D5.11",
    "ub.gradient-one-point": "D5.10",
    "ub.gradient-shape-0": "D5.2",
}

_F32_TWO = np.float32(2)


@dataclass(frozen=True)
class Case:
    """A case of undefined behaviour: its code (a key of `CODES`), the ID of its
    condition (docs/specification.md), and what the reader would do."""

    code: str
    entry: str
    message: str
    # Where the reader has it, for a case that only gradientsAt meets: a block and a time (us).
    block: int | None = None
    time_us: float | None = None


def _case(code: str, message: str, block=None, time_us=None) -> Case:
    return Case(code, CODES[code], message, block, time_us)


def _int(value: int) -> bool:
    """Whether an integer is a value of a C++ `int` (no signed overflow)."""
    return INT_MIN <= value <= INT_MAX


def _to_int(value: float) -> int | None:
    """The C++ conversion of a float or a double to `int`, or None where it is undefined: NaN,
    infinity, or a value whose truncation is not an `int`."""
    if not math.isfinite(value):
        return None
    truncated = math.trunc(value)
    return truncated if _int(truncated) else None


def _decompression(num: int, compressed: bool, packed: np.ndarray) -> tuple[str, str]:
    """What `decompressShape` (cpp:2200-2247) does with a shape into a buffer of `num` floats
    (`num` > 0): ("ok", ""), ("false", "") when it returns false (a clean rejection of the block),
    or ("ub", the reason) when it reads or writes outside its buffers, or overflows an `int`.
    `packed` holds the stored values as the reader holds them, in float32."""
    if not compressed:
        # memcpy of num floats from samples.front(); load sets isCompressed false only when
        # num_samples equals the number of stored values (cpp:967-971).
        return "ok", ""
    n_packed = len(packed)
    if n_packed == 0:
        return "ub", "the shape stores no value (&samples[0] of an empty vector)"
    count_pack = count_unpack = 1
    while count_pack < n_packed:
        if packed[count_pack - 1] != packed[count_pack]:
            if not 0 <= count_unpack - 1 < num:
                return "ub", f"it writes sample {count_unpack - 1} of {num}"
            count_pack += 1
            count_unpack += 1
            continue
        if count_pack + 1 >= n_packed:
            return "ub", f"a repeated value at stored value {count_pack} has no count after it"
        count = packed[count_pack + 1]
        as_int = _to_int(float(count))
        if as_int is None or not _int(as_int + 2):
            return "ub", f"the count {float(count)} is not an int"
        rep = as_int + 2
        # fabs(packed[countPack+1]+2-rep) > 1e-6, computed in float as the reader does.
        if abs(float(count + _F32_TWO - np.float32(rep))) > 1e-6:
            return "false", ""  # a format error that the reader detects (cpp:2219-2225)
        if not _int(count_unpack + rep) or not _int(count_unpack + rep - 2):
            return "ub", f"countUnpack + rep ({count_unpack} + {rep}) overflows an int"
        first, last = count_unpack - 1, count_unpack + rep - 2
        if first <= last and not (0 <= first and last < num):
            return "ub", f"it writes samples {first} to {last} of {num}"
        count_pack += 3
        count_unpack += rep
    if count_pack == n_packed and not 0 <= count_unpack - 1 < num:
        return "ub", f"it writes sample {count_unpack - 1} of {num}"
    return "ok", ""


def _decompress_into(
    buffer: np.ndarray, num: int, compressed: bool, packed: np.ndarray
) -> np.ndarray:
    """The samples of a shape whose decompression is "ok", in float32 as the reader holds them:
    `waveform.resize(num)` of a buffer that holds `buffer` (resize keeps the values it had, and
    adds zeros), then the run-length decoding, then the cumulative sum in float (cpp:2232-2235).
    An uncompressed shape is copied, with no sum. A decompression may write fewer samples than
    `num` (a run of count -2 or less, a shape shorter than num_samples): the others keep the
    buffer's values, which matters where the reader reuses its buffer (the extended trapezoids
    of a block, cpp:2163-2190)."""
    out = np.zeros(num, dtype=np.float32)
    kept = min(num, len(buffer))
    out[:kept] = buffer[:kept]
    if not compressed:
        out[:] = packed[:num]
        return out
    count_pack = count_unpack = 1
    while count_pack < len(packed):
        if packed[count_pack - 1] != packed[count_pack]:
            out[count_unpack - 1] = packed[count_pack - 1]
            count_pack += 1
            count_unpack += 1
        else:
            rep = math.trunc(float(packed[count_pack + 1])) + 2
            if rep > 0:
                out[count_unpack - 1 : count_unpack + rep - 1] = packed[count_pack - 1]
            count_pack += 3
            count_unpack += rep
    if count_pack == len(packed):
        out[count_unpack - 1] = packed[count_pack - 1]
    return np.add.accumulate(out, dtype=np.float32)


_EMPTY = np.zeros(0, dtype=np.float32)


class _Shapes:
    """The shape library as `decodeBlock` looks shapes up: `m_shapeLibrary[id]`, where a missing
    ID gives an empty shape (std::map::operator[] value-initializes it: 0 samples)."""

    def __init__(self, shapes: dict):
        self.shapes = shapes
        self._decompression: dict[int, tuple[str, str]] = {}

    def check(self, shape_id: int, what: str) -> Case | None:
        """The case of `waveform.resize(num)` and `decompressShape(shape, &waveform[0])`, or
        None. A negative `num` makes `resize` throw `std::length_error` before `&waveform[0]`:
        a clean rejection, but it is reported as `ub.shape-empty` (the superset of the module's
        docstring)."""
        if shape_id not in self.shapes:
            if what.startswith("RF") and "time shape" in what and shape_id == -1:
                return _case(
                    "ub.rf-time-id-minus-1",
                    f"{what} is -1, which the reader looks up as a shape that does not exist",
                )
            # With [VERSION] as the last section the reader reads no shape at all, so each shape
            # is missing here: that file is a case of this one.
            note = (
                " (the reader read no shape: is [VERSION] the last section?)"
                if not self.shapes
                else ""
            )
            return _case(
                "ub.shape-missing", f"{what} uses shape {shape_id}, which does not exist{note}"
            )
        num = self.shapes[shape_id][0]
        if num <= 0:
            return _case("ub.shape-empty", f"{what} uses shape {shape_id}, which has {num} samples")
        status, reason = self.decompression(shape_id)
        if status == "ub":
            return _case(
                "ub.shape-decompression",
                f"{what} uses shape {shape_id}: its decompression goes outside its buffers "
                f"({reason})",
            )
        return None

    def decompression(self, shape_id: int) -> tuple[str, str]:
        if shape_id not in self._decompression:
            num, compressed, packed = self.shapes[shape_id]
            self._decompression[shape_id] = _decompression(num, compressed, packed)
        return self._decompression[shape_id]

    def samples(self, shape_id: int, buffer: np.ndarray = _EMPTY) -> np.ndarray:
        """The samples of a checked shape, decompressed into a buffer that holds `buffer` (a new
        buffer by default, as decodeBlock's RF buffers are)."""
        num, compressed, packed = self.shapes[shape_id]
        return _decompress_into(buffer, num, compressed, packed)


def _first_cell_past(x: np.float32, low: int, high: int) -> int | None:
    """The first k in [low, high] with float(k) > x, compared in float as the reader compares
    `waveform_t[tc] < (c+1)`, or None. float(k) does not decrease as k grows."""
    if low > high or not np.float32(high) > x:
        return None
    while low < high:
        middle = (low + high) // 2
        if np.float32(middle) > x:
            high = middle
        else:
            low = middle + 1
    return low


def _resampling(what: str, t: np.ndarray, n_cells: int, n_mag: int, n_phase: int) -> Case | None:
    """The resampling of an RF pulse on its time shape (cpp:2032-2047):

        for (int c = 0; c < nSamples; ++c) {
            if (waveform_t[tc] < (c+1)) { if (tc < waveform_t.size()) ++tc; }
            wv_a[c] = waveform[tc]; wv_p[c] = waveform_p[tc];
        }

    `waveform_t[tc]` reads past the times once tc reaches their number; the two reads after it
    read past the magnitude or the phase once tc reaches their length. tc moves on at most once
    per cell, so the loop jumps over the cells where it stays."""
    n_time = len(t)
    tc = 0
    c = 0
    while c < n_cells:
        if tc >= n_time:
            return _case(
                "ub.rf-time-overrun",
                f"{what}: the resampling reads time {tc} of {n_time} in cell {c} (cpp:2039)",
            )
        x = t[tc]
        if x < np.float32(c + 1):
            tc += 1
            if tc >= n_mag or tc >= n_phase:
                code = "ub.rf-time-overrun" if tc >= n_time else "ub.rf-shape-lengths"
                return _case(
                    code,
                    f"{what}: the resampling reads sample {tc} of the magnitude ({n_mag}) and "
                    f"the phase ({n_phase}) in cell {c} (cpp:2044-2045)",
                )
            c += 1
            continue
        # tc stays until the first cell c' with float(c'+1) > x.
        k = _first_cell_past(x, c + 2, n_cells)
        if k is None:
            return None
        c = k - 1
    return None


def _check_rf(shapes: _Shapes, rf_id: int, rf: dict) -> Case | None:
    mag, phase, time = rf["mag_shape"], rf["phase_shape"], rf["time_shape"]
    what = f"RF event {rf_id}"
    for shape_id, name in ((mag, "magnitude"), (phase, "phase")):
        case = shapes.check(shape_id, f"{what} ({name})")
        if case:
            return case
    n_mag, n_phase = shapes.shapes[mag][0], shapes.shapes[phase][0]
    lengths = _case(
        "ub.rf-shape-lengths", f"{what}: checkRF reads {n_mag} phase samples of {n_phase}"
    )
    if time == 0:
        # checkRF reads the phase at each index of the magnitude (cpp:2284-2290).
        return lengths if n_phase < n_mag else None
    entry = shapes.shapes.get(time)
    if entry is not None and len(entry[2]) != entry[0] and len(entry[2]) in (3, 4):
        # A regular time shape: not decompressed, the dwell is samples[1] (cpp:2012-2021).
        return lengths if n_phase < n_mag else None
    case = shapes.check(time, f"{what} (time shape)")
    if case:
        return case
    if shapes.decompression(time)[0] != "ok":
        return None  # decodeBlock returns false before the resampling
    t = shapes.samples(time)
    n_cells = _to_int(0.5 + float(t[-1]))  # int(0.5+waveform_t.back()), in double
    if n_cells is None:
        return _case(
            "ub.rf-time-range",
            f"{what}: the last time {float(t[-1])} of its time shape is not an int (cpp:2031)",
        )
    # A negative number of cells makes std::vector<float> wv_a(nSamples) throw: a clean
    # rejection. After the resampling the magnitude and the phase have nSamples samples each.
    return _resampling(what, t, n_cells, n_mag, n_phase)


def _check_gradient(shapes: _Shapes, grad_id: int, grad: dict) -> Case | None:
    """The cases of one gradient event that do not depend on the block: its shapes. The times of
    an extended trapezoid depend on the block (`_extended_trapezoids`)."""
    wave, time = grad["wave_shape"], grad["time_shape"]
    what = f"gradient event {grad_id}"
    if wave == 0:
        return None  # a trapezoid
    if time <= 0:
        # An arbitrary gradient (cpp:2090-2135): the waveform; the oversampling (time -1) reads
        # inside it.
        return shapes.check(wave, f"{what} (waveform)")
    # An extended trapezoid (cpp:2160-2195): the time shape and the waveform.
    return shapes.check(time, f"{what} (time shape)") or shapes.check(wave, f"{what} (waveform)")


def _extended_trapezoids(
    shapes: _Shapes, events: list[tuple[int, dict]], raster_us: float, sizeof_long: int
) -> tuple[Case | None, dict[int, int]]:
    """decodeExtTrapGradInBlock (cpp:2155-2195) of the extended trapezoids of one block, in the
    order of their channels, after `_check_gradient` found no case for any of them. It decodes
    each time shape and each waveform into one buffer, whose values a shorter decompression keeps
    (`_decompress_into`), so the times of an event depend on the events before it in the block.

    The case `ub.gradient-time-range` where a time is not a long (cpp:2182), and for each event
    of one point (by its position in `events`) its time in us, where gradientsAt reads past its
    times (cpp:3639-3650): with one time, the binary search starts with upper = 1, does not run,
    and interpolates between times[0] and times[1], at each time between the delay and the delay
    plus that time. With 2 or more times it stays inside them. decodeBlock returns false where a
    shape does not decompress or the two lengths differ (cpp:2186): the events after it are not
    decoded."""
    limit = 2 ** (8 * sizeof_long - 1)
    buffer = _EMPTY
    one_point: dict[int, int] = {}
    for position, (grad_id, grad) in enumerate(events):
        time, wave = grad["time_shape"], grad["wave_shape"]
        if shapes.decompression(time)[0] != "ok":
            break
        buffer = shapes.samples(time, buffer)
        # long(0.5 + m_dGradientRasterTime_us*waveform[i]), in double.
        times = 0.5 + raster_us * buffer.astype(np.float64)
        with np.errstate(invalid="ignore"):
            truncated = np.trunc(times)
            bad = ~np.isfinite(times) | (truncated < -limit) | (truncated >= limit)
        if bad.any():
            return _case(
                "ub.gradient-time-range",
                f"gradient event {grad_id}: a time of its time shape is not a long (cpp:2182)",
            ), one_point
        if shapes.decompression(wave)[0] != "ok":
            break
        buffer = shapes.samples(wave, buffer)
        if len(truncated) != len(buffer):
            break
        # gradientsAt returns 0 for an amplitude of 0 (a NaN amplitude is not 0).
        if len(truncated) == 1 and truncated[0] > 0 and grad["amplitude"] != 0.0:
            one_point[position] = int(truncated[0])
    return None, one_point


def _same_float(a: float, b: float) -> bool:
    return struct.pack("<f", a) == struct.pack("<f", b)


def _gradients_of_shape_0(libraries: Libraries, rows) -> set[int]:
    """The gradient events that load read from a [GRADIENTS] row of shape 0 (cpp:1069): a
    trapezoid whose ramp and flat times load never set. `rows` are the rows of [GRADIENTS] and
    [TRAP] as load reads them (`Reader.gradient_rows`). A [TRAP] row of the same ID replaces the
    event (load reads [TRAP] after [GRADIENTS]), unless load skipped [TRAP]; the event's amplitude
    and delay say which row it holds, and where both rows have the same ones the event counts as
    the [GRADIENTS] row."""
    gradients, traps = rows
    last_gradient = {row[0]: row for row in gradients}
    last_trap = {row[0]: row for row in traps}
    events = set()
    for grad_id, row in last_gradient.items():
        entry = libraries.grad.get(grad_id)
        if row[2] != 0 or entry is None or entry["wave_shape"] != 0:
            continue
        trap = last_trap.get(grad_id)
        from_trap = (
            trap is not None
            and _same_float(entry["amplitude"], trap[1])
            and entry["delay_us"] == trap[2]
        )
        from_gradient = _same_float(entry["amplitude"], row[1]) and entry["delay_us"] == row[4]
        if not from_trap or from_gradient:
            events.add(grad_id)
    return events


def _check_extension_list(extension_list: dict, first: int, block: int) -> Case | None:
    """`GetBlock` follows `next` until it is 0 or not in the list (cpp:1849-1928)."""
    seen = set()
    entry = first
    while entry:
        if entry not in extension_list:
            return None
        if entry in seen:
            return _case(
                "ub.extension-cycle",
                f"block {block}: the extension list from entry {first} comes back to entry "
                f"{entry}, and GetBlock never ends",
            )
        seen.add(entry)
        entry = extension_list[entry][2]
    return None


def undefined_behaviour(
    libraries: Libraries, sizeof_long: int, gradient_rows=((), ())
) -> Case | None:
    """The first case of undefined behaviour that `GetBlock`, `decodeBlock` and `gradientsAt` of
    the blocks in play order would meet, or None. `libraries` is what a `load` that succeeded
    built; `load` checks that each event that a block names exists (cpp:2250-2262).
    `gradient_rows` are the rows of [GRADIENTS] and [TRAP] (`Reader.gradient_rows`)."""
    shapes = _Shapes(libraries.shapes)
    shape_0 = _gradients_of_shape_0(libraries, gradient_rows)
    checked_rf: dict[int, Case | None] = {}
    checked_grad: dict[int, Case | None] = {}
    checked_lists: dict[int, Case | None] = {}
    checked_traps: dict[tuple[int, ...], tuple[Case | None, dict[int, int]]] = {}
    for index, (duration_ru, rf, gx, gy, gz, _adc, ext) in enumerate(libraries.blocks.tolist()):
        if ext > 0:
            if ext not in checked_lists:
                checked_lists[ext] = _check_extension_list(libraries.extension_list, ext, index)
            if checked_lists[ext]:
                return checked_lists[ext]
        if rf > 0:
            if rf not in checked_rf:
                checked_rf[rf] = _check_rf(shapes, rf, libraries.rf[rf])
            if checked_rf[rf]:
                return checked_rf[rf]
        for grad in (gx, gy, gz):
            if grad > 0:
                if grad not in checked_grad:
                    checked_grad[grad] = _check_gradient(shapes, grad, libraries.grad[grad])
                if checked_grad[grad]:
                    return checked_grad[grad]
                if grad in shape_0:
                    return _case(
                        "ub.gradient-shape-0",
                        f"block {index}: gradient event {grad} is a [GRADIENTS] row of shape 0, "
                        "which the reader plays as a trapezoid with ramp and flat times that load "
                        "never sets (cpp:1069)",
                    )
        traps = tuple(
            grad
            for grad in (gx, gy, gz)
            if grad > 0
            and libraries.grad[grad]["wave_shape"] != 0
            and libraries.grad[grad]["time_shape"] > 0
        )
        if not traps:
            continue
        if traps not in checked_traps:
            events = [(grad, libraries.grad[grad]) for grad in traps]
            checked_traps[traps] = _extended_trapezoids(
                shapes, events, libraries.gradient_raster_us, sizeof_long
            )
        case, one_point = checked_traps[traps]
        if case:
            return case
        for position, time_us in sorted(one_point.items()):
            grad = traps[position]
            delay = libraries.grad[grad]["delay_us"]
            # The first time that reaches the read: gradientsAt returns 0 before the delay, before
            # 0 and after the block's duration (a NaN duration lets every time through).
            start = float(max(delay, 0))
            duration = duration_ru * libraries.block_raster_us
            if start - delay < time_us and not start > duration:
                return _case(
                    "ub.gradient-one-point",
                    f"block {index}: gradient event {grad} is an extended trapezoid of one point "
                    f"at {time_us} us; gradientsAt reads past its times from {start} us "
                    "(cpp:3639-3650)",
                    index,
                    start,
                )
    return None
