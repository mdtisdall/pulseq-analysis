"""The package's side of the fuzzing (seqfuzz.py), in a process of its own: a case that the checks
miss can end the process, so the fuzzing runs the package here and watches this process.

It reads a sampling mode of oversampled gradients and a path of a .seq file on each line of stdin
(separated by a tab) and writes one JSON object on a line of stdout for each:

- "verdict": "not-supported", "rejected" (load, or a decodeBlock), "undefined-behaviour" (with
  "code", the code of the first case, "where": [block, time] for a case that only gradientsAt
  meets, or [block, time, actual_ru] for one that only gradientsAt with a soft delay meets, and
  "long_32_only" from `load`: true when every case is `ub.gradient-time-range` and the checks with
  the `long` of this host, which the sanitized oracle's build has, find no case), or "read"
  (every block decodes);
- for "read": "points", the [block, time] and [block, time, actual_ru] lines that seqfuzz.py gives
  the sanitized oracle's `--sample`, and "values", the package's `gradients_at` there, as the hex
  of each float64.

Like the oracle's first mode, it decodes every block, also after one that decodeBlock rejects.
It samples each block twice: at its stored duration, and with a soft delay (`actual_ru`) that
makes it last past the end of its last gradient event, where the stored duration can hide a case
(an extended trapezoid of one point whose delay is past the end of the block).
"""

import json
import math
import sys

import numpy as np
import pulseq_cpp_siemens as cs
from pulseq_cpp_siemens import _checks

# At most this many blocks are sampled, at a few times each.
SAMPLED_BLOCKS = 24
# The raster (us) of an arbitrary gradient in gradientsAt: SeqBlock::s_gradientRaster (cpp:90),
# which the reader never changes.
GRADIENTS_AT_RASTER_US = 10.0
# The largest soft delay that the worker sets, so that it is an int64 and a long of the reader.
MAX_ACTUAL_RU = 2**62


def sample_points(sequence: cs.Sequence, actual_ru=None) -> tuple[list[int], list[float]]:
    """A few times in each of the first blocks: before, at and after its start and its end, its
    middle, and the delays of its gradients and a few rasters after them. The middle comes before
    each delay: the channels after a gradient that gradientsAt returns early for (an oversampled
    gradient with no sample, in the "edge" mode) must not keep the values of the time before.

    With `actual_ru` (one int for each block), only the blocks with a value of 0 or more, each
    with that soft delay as its end in place of its stored duration."""
    libraries = sequence.libraries
    blocks, times = [], []
    for index, row in enumerate(libraries.blocks[:SAMPLED_BLOCKS].tolist()):
        duration_ru = row[0]
        if actual_ru is not None:
            if actual_ru[index] < 0:
                continue
            duration_ru = int(actual_ru[index])
        duration = duration_ru * libraries.block_raster_us
        candidates = [-1.0, 0.0, 0.5, 5.0, 10.0, 15.25, duration / 2, duration, duration + 1.0]
        for grad_id in row[2:5]:
            if grad_id in libraries.grad:
                delay = float(libraries.grad[grad_id]["delay_us"])
                candidates += [duration / 2, delay, delay + 5.0, delay + 12.5, delay + 40.0]
        for t in candidates:
            if math.isfinite(t):
                blocks.append(index)
                times.append(float(t))
    return blocks, times


def actual_ru_past_the_gradients(sequence: cs.Sequence, decoded: list[dict]) -> np.ndarray:
    """A soft delay (in units of BlockDurationRaster) for each of the sampled blocks that has a
    gradient event: past the end of its last event (the largest delay plus length of an event, the
    length as gradientsAt reads it), plus one block raster. It is longer than the stored duration
    wherever an event ends after the block. The other blocks get -1 (none)."""
    raster = sequence.libraries.block_raster_us
    actual = np.full(sequence.block_count, -1, dtype=np.int64)
    if not (math.isfinite(raster) and raster > 0):
        return actual
    for index, block in enumerate(decoded[:SAMPLED_BLOCKS]):
        ends = []
        for grad in block["grad"]:
            if grad is None:
                continue
            if grad["kind"] == "trap":
                length = grad["ramp_up_us"] + grad["flat_us"] + grad["ramp_down_us"]
            elif grad["kind"] == "ext_trap":
                length = int(grad["times_us"][-1]) if grad["times_us"].size else 0
            else:
                length = grad["samples"].size * GRADIENTS_AT_RASTER_US
            ends.append(grad["delay_us"] + length)
        if not ends:
            continue
        end_ru = max(ends) / raster
        if math.isfinite(end_ru) and end_ru < MAX_ACTUAL_RU:
            actual[index] = max(math.ceil(end_ru) + 1, 0)
    return actual


def long_32_only(path: str, oversampling: str, error: cs.UndefinedBehaviour) -> bool:
    """Whether `load` rejects the file only for its `long` of 32 bits (`CHECKED_SIZEOF_LONG`,
    D5.11): every case is `ub.gradient-time-range`, and the checks with the `long` of this host
    (`_reader.SIZEOF_LONG`, 8 on Linux and macOS, where the sanitized oracle is built) find no
    case, so that the oracle's build has no undefined behaviour on the file."""
    if any(case.code != "ub.gradient-time-range" for case in error.cases):
        return False
    if cs._reader.SIZEOF_LONG == _checks.CHECKED_SIZEOF_LONG:
        return False
    reader = cs._reader.Reader(oversampling)
    with open(path, "rb") as file:
        reader.load(file.read())
    libraries = cs.Libraries._from_reader(reader.libraries())
    checked = _checks.undefined_behaviour(libraries, cs._reader.SIZEOF_LONG, reader.gradient_rows())
    return not checked.cases


def verdict(path: str, oversampling: str) -> dict:
    try:
        sequence = cs.load(path, oversampling=oversampling)
    except cs.NotSupported:
        return {"verdict": "not-supported"}
    except cs.UndefinedBehaviour as error:
        where = None if error.block is None else [error.block, error.time_us]
        return {
            "verdict": "undefined-behaviour",
            "code": error.code,
            "where": where,
            "long_32_only": long_32_only(path, oversampling, error),
        }
    except cs.Rejected:
        return {"verdict": "rejected", "stage": "load"}
    rejected = False
    decoded = []
    for index in range(sequence.block_count):
        try:
            decoded.append(sequence.decode_block(index))
        except cs.Rejected:
            rejected = True
    if rejected:
        return {"verdict": "rejected", "stage": "decode"}
    blocks, times = sample_points(sequence)
    values = sequence.gradients_at(blocks, times) if blocks else np.zeros((0, 3))
    points = [[b, t] for b, t in zip(blocks, times, strict=True)]
    # The same blocks with a soft delay past their gradients (a call of its own: the actual_ru of
    # a call is for each block).
    actual = actual_ru_past_the_gradients(sequence, decoded)
    blocks, times = sample_points(sequence, actual)
    if blocks:
        try:
            delayed = sequence.gradients_at(blocks, times, actual_ru=actual)
        except cs.UndefinedBehaviour as error:
            where = [error.block, error.time_us, int(actual[error.block])]
            return {"verdict": "undefined-behaviour", "code": error.code, "where": where}
        values = np.concatenate([values, delayed])
        points += [[b, t, int(actual[b])] for b, t in zip(blocks, times, strict=True)]
    return {
        "verdict": "read",
        "points": points,
        "values": np.ascontiguousarray(values, dtype=np.float64).tobytes().hex(),
    }


def limit_memory() -> None:
    """At most 8 GiB of address space on Linux, so that a size that a file gives makes the reader
    throw std::bad_alloc instead of filling the runner's memory (macOS has no such limit)."""
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (8 << 30, 8 << 30))


def main() -> None:
    limit_memory()
    for line in sys.stdin:
        oversampling, _, path = line.rstrip("\n").partition("\t")
        if not path:
            continue
        sys.stdout.write(json.dumps(verdict(path, oversampling)) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
