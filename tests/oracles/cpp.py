"""The modes `--dump` and `--sample` of the C++ oracle `pulseq-cpp-oracle` (the reader
`ExternalSequence` of pulseq/pulseq, the reader of the Pulseq interpreter on the scanner).
`tests/cpp_oracle/README.md` has the fields of the dump, their units and the protocol of
`--sample`.

Each call gets the time `TIMEOUT` of `tests/test_cpp_oracle.py`. The functions need the binary
on the PATH (`ORACLE` of that module is `None` when it is not).
"""

import json
import subprocess
from os import PathLike

import numpy as np
from test_cpp_oracle import ORACLE, TIMEOUT


class OracleError(Exception):
    """The oracle did not exit with 0 in the time `TIMEOUT`. The message has the exit status
    and the messages of the oracle."""


def _run(mode: str, path: str | PathLike, stdin: str | None = None) -> str:
    """The stdout of `pulseq-cpp-oracle MODE PATH` with `stdin`. Raises `OracleError` when it
    does not exit with 0 in `TIMEOUT` s."""
    try:
        result = subprocess.run(
            [ORACLE, mode, str(path)],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise OracleError(f"{mode} {path}: no end after {TIMEOUT} s") from error
    if result.returncode != 0:
        raise OracleError(f"{mode} {path}: exit status {result.returncode}\n{result.stderr}")
    return result.stdout


def dump(path: str | PathLike) -> dict:
    """The JSON object that `--dump` writes for the file `path`."""
    return json.loads(_run("--dump", path))


def sample(path: str | PathLike, block_index: np.ndarray, time_us: np.ndarray) -> np.ndarray:
    """The values (Hz/m) of `SeqBlock::gradientsAt` of the file `path` at each pair of a block
    index (play order from 0) and a time in µs from the start of that block, as an array of
    shape (n, 3): gx, gy and gz. One call of the oracle for all the pairs."""
    block_index = np.asarray(block_index, dtype=np.int64)
    time_us = np.asarray(time_us, dtype=np.float64)
    # `repr` of a float is the shortest text that reads back as the same double (`strtod`).
    lines = "".join(
        f"{b} {t!r}\n" for b, t in zip(block_index.tolist(), time_us.tolist(), strict=True)
    )
    out = _run("--sample", path, lines)
    values = np.array(out.split(), dtype=np.float64).reshape(-1, 3)
    if values.shape[0] != block_index.size:
        raise OracleError(f"--sample {path}: {values.shape[0]} lines for {block_index.size} times")
    return values
