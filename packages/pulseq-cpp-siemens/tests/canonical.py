"""One form for the driver's output (`pulseq-cpp-oracle --dump` and `--sample`) and the
package's, so the two compare exactly, and a digest of it for the platforms without the driver.

The JSON of `--dump` does not say which numbers are `float`: a float of the reader is written
with `%.9g`, so `1000.0f` is `1000`. The form takes the type from the field: an integer field is
an int, `rotation` is double, and each other number is the float32 that the reader holds, as its
bits. NaN and infinity are None (the driver writes `null`). Text is a Python str: the driver
keeps valid UTF-8 and writes each other byte as the code point of the same number.
"""

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pulseq_cpp_siemens as cs

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SEQFILES = REPO / "tests" / "seqfiles"
# The package's own fixtures (cases of undefined behaviour that tests/seqfiles does not have).
UB_FIXTURES = HERE / "fixtures"
DIGESTS = HERE / "expected_digests.json"
# The time that the driver gets for one file. A file with a cycle in an extension list never
# ends (D23).
TIMEOUT = 20

INT_KEYS = {
    "index", "duration_ru", "mag_shape", "phase_shape", "time_shape", "delay_us",
    "ramp_up_us", "flat_us", "ramp_down_us", "times_us", "wave_shape", "num_samples",
    "dwell_ns", "type", "channel", "duration_us", "num_id", "offset_us", "value", "id",
    "nchan", "version",
}  # fmt: skip
DOUBLE_KEYS = {"rotation"}


def fixtures() -> list[Path]:
    """The .seq files of the repository's tests/seqfiles and the package's own fixtures."""
    return sorted(SEQFILES.rglob("*.seq")) + sorted(UB_FIXTURES.glob("*.seq"))


def fixture_id(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _text(value) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return value


def _float32(value) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return np.float32(value).tobytes().hex()


def _float64(value) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return np.float64(value).tobytes().hex()


def _canonical(value, key: str | None):
    if isinstance(value, dict):
        return {_text(k): _canonical(v, _text(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_canonical(v, key) for v in list(value)]
    if value is None or isinstance(value, (bool, np.bool_)):
        return None if value is None else bool(value)
    if isinstance(value, (str, bytes)):
        return _text(value)
    if key in INT_KEYS:
        return int(value)
    if key in DOUBLE_KEYS:
        return _float64(float(value))
    return _float32(float(value))


def parse_driver_dump(text: str) -> dict:
    """The driver's `--dump` JSON. `%.9g` writes -0.0f as `-0`, which json reads as the int 0."""
    return json.loads(text, parse_int=lambda s: -0.0 if s == "-0" else int(s))


def canonical_dump(dump: dict) -> dict:
    """The canonical form of the driver's `--dump` object, or of `wrapper_dump`."""
    return _canonical(dump, None)


def wrapper_dump(sequence, blocks: list[dict] | None = None) -> dict:
    """The package's `Sequence` in the shape of the driver's `--dump` object. `blocks` are its
    decoded blocks (decoded here when not given)."""
    return {
        "version": sequence.version,
        "definitions": sequence.libraries.definitions,
        "signature_ok": sequence.signature_ok,
        "blocks": sequence.decode() if blocks is None else blocks,
    }


def read(path: Path, oversampling: str = "center") -> tuple[str, object, list[dict] | None]:
    """The package's verdict on a file, in the words of tests/expected_digests.json, with the
    sequence and its decoded blocks when it reads the file: `load` in the sampling mode
    `oversampling`, then `decode` of each block, as the driver does."""
    try:
        sequence = cs.load(path, oversampling=oversampling)
        blocks = sequence.decode()
    except cs.NotSupported:
        return "not-supported", None, None
    except cs.UndefinedBehaviour as error:
        return f"undefined-behaviour:{error.code}", None, None
    except cs.Rejected:
        return "rejected", None, None
    return "read", sequence, blocks


def has_oversampled_gradient(sequence) -> bool:
    """Whether a block of the sequence uses an oversampled arbitrary gradient (a wave shape and
    time shape -1): the only gradient that the sampling mode of the reader changes."""
    libraries = sequence.libraries
    used = {g for row in libraries.blocks.tolist() for g in row[2:5] if g in libraries.grad}
    return any(
        libraries.grad[g]["wave_shape"] != 0 and libraries.grad[g]["time_shape"] == -1 for g in used
    )


def sample_points(dump: dict) -> tuple[np.ndarray, np.ndarray]:
    """The block indices and times (us) at which the tests ask `gradientsAt`: in each block, the
    times from 1 us before its start to 1 us after its end, every 1.25 us up to 400 times (so
    the gradient raster, its half and points between them), the block's start and end, and the
    raster edges of each gradient event."""
    raster = 1e6 * float(dump["definitions"]["BlockDurationRaster"].split()[0])
    blocks, times = [], []
    for block in dump["blocks"]:
        end = block["duration_ru"] * raster
        t = np.arange(-1.0, end + 1.0, 1.25)[:400]
        t = np.concatenate([t, [0.0, end, end / 2, end + 1e-3]])
        for grad in block["grad"]:
            if grad is not None:
                t = np.concatenate([t, grad["delay_us"] + np.arange(0, 41, 5.0)])
        blocks.append(np.full(t.size, block["index"], dtype=np.int64))
        times.append(t)
    if not blocks:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    return np.concatenate(blocks), np.concatenate(times)


def canonical_samples(values: np.ndarray) -> str:
    """The bits of each value, with one NaN for all: the bits of a NaN depend on the compiler
    and its C library (MSVC's differ from clang's and gcc's for `nan` in a file)."""
    values = np.array(values, dtype=np.float64)
    values[np.isnan(values)] = np.nan
    return values.tobytes().hex()


def digest(dump: dict, samples: np.ndarray) -> str:
    text = json.dumps(
        {"dump": canonical_dump(dump), "samples": canonical_samples(samples)}, sort_keys=True
    )
    return hashlib.sha256(text.encode()).hexdigest()


# ---- The driver ----


def driver() -> str | None:
    """The driver: the environment variable PULSEQ_CPP_ORACLE, else `pulseq-cpp-oracle` on the
    PATH (the Nix devShell has it), else None. flake.nix builds it with the flags of the
    package (-fsigned-char -ffp-contract=off), so the two give the same bits."""
    if os.environ.get("PULSEQ_CPP_ORACLE"):
        return os.environ["PULSEQ_CPP_ORACLE"]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "pulseq-cpp-oracle"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def oversampling_option(oversampling: str) -> list[str]:
    """The driver's leading option for a sampling mode of oversampled gradients; none for the
    reader's default, so that the call with no option is tested too."""
    return [] if oversampling == "center" else [f"--oversampling={oversampling}"]


def run_driver(
    mode: str, path: Path, stdin: str | None = None, oversampling: str = "center"
) -> tuple[str, str]:
    """("ok", stdout), ("reject", stderr) or ("crash", reason) for one call of the driver. The
    mode "" is the driver's first mode: load and decode, the exit status only. `oversampling` is
    the sampling mode of oversampled gradients (`--oversampling`)."""
    try:
        result = subprocess.run(
            [driver(), *oversampling_option(oversampling), *([mode] if mode else []), str(path)],
            input=stdin, capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "crash", f"no end in {TIMEOUT} s"
    if result.returncode == 0:
        return "ok", result.stdout
    if result.returncode == 1:
        return "reject", result.stderr
    return "crash", f"exit status {result.returncode}: {result.stderr[-300:]}"


def driver_samples(
    path: Path, block_index: np.ndarray, time_us: np.ndarray, oversampling: str = "center"
) -> np.ndarray:
    lines = "".join(f"{b} {t!r}\n" for b, t in zip(block_index.tolist(), time_us.tolist()))
    verdict, out = run_driver("--sample", path, lines, oversampling)
    assert verdict == "ok", out
    return np.array(out.split(), dtype=np.float64).reshape(-1, 3)
