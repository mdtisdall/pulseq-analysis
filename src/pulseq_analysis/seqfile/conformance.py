"""The checks that an interpreter follows a convention of every interpreter, for the tests of a
plugin interpreter (`interpreters.Plugin`) and of `spec`.

- `check_shape_limit(cls)`: the setting `max_shape_samples` of the interpreter class `cls` (the
  user, 2026-10-18). It raises `AssertionError`, with a message that says what is wrong, when
  `cls` does not follow the convention.

A check writes its files to a temporary folder, and reads them with `reading.read_seqfile`.
"""

import tempfile
from pathlib import Path
from typing import Any, NoReturn

from .errors import NotSupported
from .interpreters import DEFAULT_MAX_SHAPE_SAMPLES
from .reading import read_seqfile

__all__ = ["check_shape_limit"]

# A Pulseq 1.5.1 text file, made from the header and the tables of
# `tests/seqfiles/valid_no_signature.seq`: one block, which plays one arbitrary gradient of shape 1
# on the gradient raster. Shape 1 is `num_samples` samples of 0, compressed: the derivative 0,
# repeated `num_samples` times. So the file is short for any number of samples, and the block
# lasts `num_samples` gradient rasters. `spec` reads it.
_TEXT = """# Pulseq sequence file
# Written by pulseq_analysis.seqfile.conformance, not made by a Pulseq tool.

[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

# Format of blocks:
# NUM DUR RF GX GY GZ ADC EXT
[BLOCKS]
1 {num_samples} 0 1 0 0 0 0

# Format of arbitrary gradients:
# id amplitude first last amp_shape_id time_shape_id delay
# ..      Hz/m  Hz/m Hz/m        ..         ..          us
[GRADIENTS]
1 500000 0 0 1 0 0

# Sequence Shapes
[SHAPES]

shape_id 1
num_samples {num_samples}
0
0
{repeats}

"""

# A Pulseq 1.5.1 text file of one block that plays RF event 1, with the header of `_TEXT`. The
# magnitude (shape 1), the phase (shape 2) and the time shape (shape 3) have two samples each, and
# the times are 1 and `last` RF rasters of 1 us: a pulse of two points, which `spec` keeps as its
# points. A reader that resamples it on the RF raster, as `decodeBlock` of the C++ reader does
# (cpp:2031), makes `int(0.5 + last)` cells. The block lasts `duration` block rasters of 10 us.
_RF_TEXT = """# Pulseq sequence file
# Written by pulseq_analysis.seqfile.conformance, not made by a Pulseq tool.

[VERSION]
major 1
minor 5
revision 1

[DEFINITIONS]
AdcRasterTime 1e-07
BlockDurationRaster 1e-05
GradientRasterTime 1e-05
RadiofrequencyRasterTime 1e-06

# Format of blocks:
# NUM DUR RF GX GY GZ ADC EXT
[BLOCKS]
1 {duration} 1 0 0 0 0 0

# Format of RF events:
# id ampl. mag_id phase_id time_shape_id center delay freqPPM phasePPM freq phase use
# ..   Hz      ..       ..            ..     us    us     ppm  rad/MHz   Hz   rad  ..
[RF]
1 1000 1 2 3 0 0 0 0 0 0 e

# Sequence Shapes
[SHAPES]

shape_id 1
num_samples 2
1
1

shape_id 2
num_samples 2
0
0

shape_id 3
num_samples 2
1
{last}

"""

# The shapes of the two files of `check_shape_limit`: one of 2^21 samples (16 MiB of float64),
# which it does not read under a limit, and one of 8 samples, which it reads. The RF pulse of the
# third file ends at 2^21 RF rasters: 2^21 cells of a reader that resamples it.
_LARGE, _SMALL = 2**21, 8


def _write(folder: Path, num_samples: int) -> Path:
    """The file `_TEXT` with a shape of `num_samples` samples, in `folder`."""
    path = folder / f"shape_{num_samples}.seq"
    path.write_text(_TEXT.format(num_samples=num_samples, repeats=num_samples - 2))
    return path


def _write_rf(folder: Path, last: int) -> Path:
    """The file `_RF_TEXT` with an RF pulse whose last time is `last` RF rasters, in a block of
    the fewest block rasters that hold it, in `folder`. The name of the file has no number, so
    that a message that gives the path does not give the number of cells by it."""
    path = folder / "rf_pulse.seq"
    path.write_text(_RF_TEXT.format(duration=-(-last // 10), last=last))
    return path


def _fail(cls: type, message: str) -> NoReturn:
    raise AssertionError(f"the interpreter {getattr(cls, 'name', cls)!r}: {message}")


def _refused(cls: type, path: Path, limit: int | None) -> NotSupported | None:
    """The `NotSupported` of `read_seqfile(path, cls(max_shape_samples=limit))`, or None when it
    reads the file."""
    try:
        read_seqfile(path, cls(max_shape_samples=limit))
    except NotSupported as error:
        return error
    return None


def _check_value(cls: type, value: Any, error: type[Exception]) -> None:
    """`cls(max_shape_samples=value)` raises `error`."""
    try:
        cls(max_shape_samples=value)
    except error:
        return
    _fail(cls, f"max_shape_samples={value!r} does not raise {error.__name__}")


def check_shape_limit(cls: type) -> None:
    """Check that the interpreter class `cls` (`interpreters.Spec`, or the class of a plugin)
    follows the convention of the setting `max_shape_samples` (`interpreters.Plugin`). Raises
    `AssertionError` when it does not:

    - `cls()` has the setting `interpreters.DEFAULT_MAX_SHAPE_SAMPLES` (2^27);
    - `max_shape_samples=0` raises `ValueError`, and `True` and `1.5` raise `TypeError`;
    - `str` does not give the setting for its default, and gives `max_shape_samples=None`;
    - `read_seqfile` with `cls(max_shape_samples=2**20)` raises `NotSupported` for a file whose
      shape declares 2^21 samples (stored in three values), and the message gives the path, the
      declared number and the limit, and names the setting;
    - for a file whose shape has 8 samples, `read_seqfile` raises `NotSupported` with the limit
      4, and reads the file with the limit 8 and with None (no limit); the model records the
      interpreter with its setting;
    - for a file whose shapes have 2 samples and whose RF pulse ends at 2^21 RF rasters (2^21
      cells of a reader that resamples it on the RF raster), `read_seqfile` with the limit 2^20
      reads the file or raises `NotSupported`, whose message gives the path, the number of cells
      and the limit, and names the setting; with the limit 2^21 and with None, it reads the file.

    The files are Pulseq 1.5.1 text files that `spec` reads (one block with one arbitrary
    gradient of zeros, or with one RF pulse of two points). The check allocates little: it reads
    no shape of more than 8 samples when `cls` follows the convention, and a reader that
    resamples the RF pulse makes at most 2^21 cells. It cannot see a plugin that resamples the
    pulse and ignores the limit: the cells of a plugin can be memory that Python does not
    allocate (the vectors of a reader in C++), and `spec` reads the file under any limit. So
    each plugin that resamples guards that in its own tests (the user, 2026-10-21)."""
    default = cls().max_shape_samples
    if default != DEFAULT_MAX_SHAPE_SAMPLES:
        _fail(
            cls, f"the default of max_shape_samples is {default!r}, not {DEFAULT_MAX_SHAPE_SAMPLES}"
        )
    _check_value(cls, 0, ValueError)
    _check_value(cls, True, TypeError)
    _check_value(cls, 1.5, TypeError)
    if "max_shape_samples" in str(cls()):
        _fail(cls, f"str gives the default of max_shape_samples: {str(cls())!r}")
    unlimited = cls(max_shape_samples=None)
    if "max_shape_samples=None" not in str(unlimited):
        _fail(cls, f"str of max_shape_samples=None does not give it: {str(unlimited)!r}")
    with tempfile.TemporaryDirectory(prefix="pulseq-analysis-") as folder:
        large, small = _write(Path(folder), _LARGE), _write(Path(folder), _SMALL)
        error = _refused(cls, large, _LARGE // 2)
        if error is None:
            _fail(cls, f"a shape of {_LARGE} samples, over the limit {_LARGE // 2}, reads")
        for part in (str(large), str(_LARGE), str(_LARGE // 2), "max_shape_samples"):
            if part not in str(error):
                _fail(cls, f"the message of NotSupported does not give {part!r}: {error}")
        if _refused(cls, small, _SMALL // 2) is None:
            _fail(cls, f"a shape of {_SMALL} samples, over the limit {_SMALL // 2}, reads")
        if _refused(cls, small, _SMALL) is not None:
            _fail(cls, f"a shape of {_SMALL} samples, at the limit {_SMALL}, does not read")
        data = read_seqfile(small, unlimited)
        if data.interpreter != unlimited:
            _fail(cls, f"the model records {data.interpreter!r}, not {unlimited!r}")
        rf = _write_rf(Path(folder), _LARGE)
        error = _refused(cls, rf, _LARGE // 2)
        if error is not None:
            for part in (str(rf), str(_LARGE), str(_LARGE // 2), "max_shape_samples"):
                if part not in str(error):
                    _fail(
                        cls,
                        f"the message of NotSupported of an RF pulse of {_LARGE} cells does not "
                        f"give {part!r}: {error}",
                    )
        if _refused(cls, rf, _LARGE) is not None:
            _fail(cls, f"an RF pulse of {_LARGE} cells, at the limit {_LARGE}, does not read")
        if _refused(cls, rf, None) is not None:
            _fail(cls, f"an RF pulse of {_LARGE} cells, with no limit, does not read")
