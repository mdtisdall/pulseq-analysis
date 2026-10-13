"""The package's side of the fuzzing (seqfuzz.py), in a process of its own: a case that the checks
miss can end the process, so the fuzzing runs the package here and watches this process.

It reads a sampling mode of oversampled gradients and a path of a .seq file on each line of stdin
(separated by a tab) and writes one JSON object on a line of stdout for each:

- "verdict": "not-supported", "rejected" (load, or a decodeBlock), "undefined-behaviour" (with
  "code", and "where": [block, time] for a case that only gradientsAt meets), or "read" (every
  block decodes);
- for "read": "points", the [block, time] pairs that seqfuzz.py gives the sanitized oracle's
  `--sample`, and "values", the package's `gradients_at` there, as the hex of each float64.

Like the oracle's first mode, it decodes every block, also after one that decodeBlock rejects.
"""

import json
import math
import sys

import numpy as np
import pulseq_cpp_siemens as cs

# At most this many blocks are sampled, at a few times each.
SAMPLED_BLOCKS = 24


def sample_points(sequence: cs.Sequence) -> tuple[list[int], list[float]]:
    """A few times in each of the first blocks: before, at and after its start and its end, its
    middle, and the delays of its gradients and a few rasters after them. The middle comes before
    each delay: the channels after a gradient that gradientsAt returns early for (an oversampled
    gradient with no sample, in the "edge" mode) must not keep the values of the time before."""
    libraries = sequence.libraries
    blocks, times = [], []
    for index, row in enumerate(libraries.blocks[:SAMPLED_BLOCKS].tolist()):
        duration = row[0] * libraries.block_raster_us
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


def verdict(path: str, oversampling: str) -> dict:
    try:
        sequence = cs.load(path, oversampling=oversampling)
    except cs.NotSupported:
        return {"verdict": "not-supported"}
    except cs.UndefinedBehaviour as error:
        where = None if error.block is None else [error.block, error.time_us]
        return {"verdict": "undefined-behaviour", "code": error.code, "where": where}
    except cs.Rejected:
        return {"verdict": "rejected", "stage": "load"}
    rejected = False
    for index in range(sequence.block_count):
        try:
            sequence.decode_block(index)
        except cs.Rejected:
            rejected = True
    if rejected:
        return {"verdict": "rejected", "stage": "decode"}
    blocks, times = sample_points(sequence)
    values = sequence.gradients_at(blocks, times) if blocks else np.zeros((0, 3))
    return {
        "verdict": "read",
        "points": [[b, t] for b, t in zip(blocks, times, strict=True)],
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
