"""The scanner session, and what a decoding applies of the scanner-side settings (section 7.8 of
`docs/plans/parser-redesign.md`, P20 and P22).

The scanner's interpreter acts on information that a reader can leave to it: content of the file
(the rotations of ROTATIONS) and inputs of the scanner session, which are not in the file (the
values of the soft delays, the orientation and the gradient scaling of the field of view). This
module has:

- `Session`: the inputs of the scanner session, one type for every interpreter (rule 3). The
  default is the neutral session (rule 1): the soft delays at their stored durations, and the
  field of view at the isocentre with no rotation and no scaling. `synth.decode(data, session)`
  and `analyses.load(source, session=...)` take it; a plugin interpreter takes it through
  `Plugin.decode(data, session)` (P22) and applies it with its own hooks.
- The simulation of the session, one implementation for each mechanism, shared by the
  interpreters (rule 6): a plugin may import it. `soft_delay_durations` computes the duration of
  each block from the session's soft delays by the specification's rule, `fov_flags` the flags
  NOROT and the flag that turns off the scaling of each block, as a state across blocks, and
  `physical_gradients` the gradients on the physical axes, in the order of MATLAB Pulseq's
  `mr.TransformFOV`: the scaling of the logical axes first, then the block's rotation, then the
  rotation of the field of view (the user, 2026-10-13). No source gives the order of the
  scanner's interpreter.
- The records of what a decoding applied (rule 4): `RotationRecord`, `SoftDelayRecord` and
  `FovRecord`. Each decoding (`decoding.Decoding`) gives them.
- `ScannerSettingWarning`: the warning for content of the file that a decoding leaves unapplied;
  `RotationRecord.warning()` gives it. A neutral session is recorded, not warned about.
- `SettingError`: a setting of the session that addresses something the file does not have
  under the interpreter (rule 8).

The records and the session are part of the contract with pulseq-checks (section 7.3 of the
plan): a change to them is noted in `CHANGELOG.md`.
"""

import dataclasses
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np

__all__ = [
    "FovRecord",
    "RotationRecord",
    "ScannerSettingWarning",
    "Session",
    "SettingError",
    "SoftDelay",
    "SoftDelayRecord",
    "fov_flags",
    "fov_record",
    "physical_gradients",
    "soft_delay_durations",
]

# How far from 1 the norm of `Session.fov_rotation` may be: the precision of a quaternion that is
# written with eight digits.
_UNIT_TOLERANCE = 1e-6


class ScannerSettingWarning(UserWarning):
    """Content of the file that the scanner's interpreter applies and the package's result does
    not, for example a block's rotation that a decoding leaves unapplied. It describes the
    package's measurement, not the file."""


class SettingError(ValueError):
    """A setting of the session that addresses something that the file does not have under the
    interpreter (rule 8 of section 7.8 of the plan): for example a soft delay hint that no block
    has, or a file older than the revision that introduced soft delays.

    `setting` names the setting (for example `"soft_delays['TE']"`), `interpreter` the
    interpreter, `version` the file's version and `reason` the reason."""

    def __init__(
        self, setting: str, interpreter: str, version: tuple[int, int, int], reason: str
    ) -> None:
        self.setting = setting
        self.interpreter = interpreter
        self.version = tuple(version)
        self.reason = reason
        name = ".".join(map(str, version))
        super().__init__(
            f"the setting {setting} does not apply to this file (version {name}) under the "
            f"interpreter {interpreter}: {reason}"
        )

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.setting, self.interpreter, self.version, self.reason))


def _real(value: Any, what: str) -> float:
    """`value` as a finite float; TypeError for a value that is not a real number (a bool is
    not), ValueError for NaN or infinity."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{what} is a real number, not {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{what} is {out}, not a finite number")
    return out


@dataclasses.dataclass(frozen=True, slots=True)
class Session:
    """The inputs of the scanner session (rule 3 of section 7.8 of the plan): the same for each
    interpreter. The default is the neutral session (rule 1).

    - `soft_delays`: the value (s) that the scanner's UI gives to each soft delay, by its hint
      (`{"TE": 5e-3}`), as the specification and MATLAB Pulseq address them. It is kept as
      (hint, value) pairs sorted by hint. A soft delay with no value keeps its stored duration.
    - `fov_rotation`: the rotation of the field of view, a quaternion (q0, qx, qy, qz) with q0
      the scalar part, as the ROTATIONS extension of the file has it (the user, 2026-10-13). Its
      norm must be 1 within 1e-6; it is divided by its norm. The default (1, 0, 0, 0) is no
      rotation.
    - `gradient_scaling`: the scaling (sx, sy, sz) of the gradients on the logical axes, each
      above 0. The default (1, 1, 1) is no scaling.

    A setting addresses the file: a decoding raises `SettingError` where it addresses something
    that the file does not have (rule 8). The field of view is valid on any file. A field that the
    session does not have is a `TypeError`. A session is frozen, compares by value and can be a
    key of a dict."""

    soft_delays: Any = ()
    fov_rotation: Any = (1.0, 0.0, 0.0, 0.0)
    gradient_scaling: Any = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        delays = self.soft_delays
        if isinstance(delays, Mapping):
            delays = list(delays.items())
        elif isinstance(delays, str) or not isinstance(delays, Iterable):
            raise TypeError(f"soft_delays is a mapping of hints to values, not {type(delays)}")
        pairs: dict[str, float] = {}
        for item in delays:
            hint, value = item
            if not isinstance(hint, str) or not hint:
                raise TypeError(f"a soft delay hint is a text that is not empty, not {hint!r}")
            if hint in pairs:
                raise ValueError(f"the soft delay hint {hint!r} has two values")
            pairs[hint] = _real(value, f"the value of the soft delay {hint!r}")
        object.__setattr__(self, "soft_delays", tuple(sorted(pairs.items())))

        q = tuple(_real(v, "a component of fov_rotation") for v in self.fov_rotation)
        if len(q) != 4:
            raise ValueError(f"fov_rotation is a quaternion of 4 values, not {len(q)}")
        norm = math.sqrt(sum(v * v for v in q))
        if abs(norm - 1) > _UNIT_TOLERANCE:
            raise ValueError(f"fov_rotation has the norm {norm!r}, not 1 within 1e-6")
        object.__setattr__(self, "fov_rotation", tuple(v / norm for v in q))

        s = tuple(_real(v, "a component of gradient_scaling") for v in self.gradient_scaling)
        if len(s) != 3:
            raise ValueError(f"gradient_scaling has 3 values (x, y, z), not {len(s)}")
        if min(s) <= 0:
            raise ValueError(f"gradient_scaling is {s}: each value is above 0")
        object.__setattr__(self, "gradient_scaling", s)

    @property
    def rotates(self) -> bool:
        """Whether the field of view is rotated: a quaternion whose vector part is not 0."""
        return any(self.fov_rotation[1:])

    @property
    def scales(self) -> bool:
        """Whether the gradients are scaled: a scaling that is not (1, 1, 1)."""
        return self.gradient_scaling != (1.0, 1.0, 1.0)

    @property
    def neutral(self) -> bool:
        """Whether this is the neutral session (rule 1): no soft delay value, and the field of
        view not rotated and not scaled."""
        return not self.soft_delays and not self.rotates and not self.scales

    def __str__(self) -> str:
        """`session: neutral`, or each setting that is not its default."""
        settings = []
        if self.soft_delays:
            settings.append(f"soft_delays={dict(self.soft_delays)!r}")
        if self.rotates:
            settings.append(f"fov_rotation={self.fov_rotation!r}")
        if self.scales:
            settings.append(f"gradient_scaling={self.gradient_scaling!r}")
        return f"session({', '.join(settings)})" if settings else "session: neutral"


@dataclasses.dataclass(frozen=True, slots=True)
class RotationRecord:
    """What a decoding did with the rotations of the file.

    - `setting`: what the interpreter does with the rotations, `"apply"` when it rotates the
      gradients, or the name of its setting that does not (for example `"reader"`); `"apply"`
      for `spec`, which has no setting and applies the rotations of the file.
    - `blocks`: the blocks with a rotation, as the interpreter finds them; for `spec` those
      whose extension list has a ROTATIONS object, from 1.5.1.
    - `not_identity`: of these, the blocks whose rotation is not the identity (a quaternion
      with a vector part that is not 0): the blocks that play a rotation.
    - `rotated`: the blocks whose gradients the decoding rotates: `blocks` with `"apply"`, 0
      otherwise.
    - `hint`: what the warning tells the user to do for the gradients that the scanner plays
      (the interpreter gives it), or empty.
    """

    setting: str
    blocks: int
    not_identity: int
    rotated: int
    hint: str = dataclasses.field(default="", compare=False)

    @property
    def unapplied(self) -> int:
        """The blocks that play a rotation that the decoding does not apply."""
        return self.not_identity if self.rotated == 0 else 0

    def warning(self) -> ScannerSettingWarning | None:
        """The `ScannerSettingWarning` for the rotations left unapplied, or None."""
        if not self.unapplied:
            return None
        message = (
            f"{self.unapplied} block(s) play a rotation (ROTATIONS) that is not applied: the "
            "gradients are the logical ones, as the interpreter gives them"
        )
        return ScannerSettingWarning(f"{message}; {self.hint}" if self.hint else message)

    def __str__(self) -> str:
        if self.setting == "apply":
            return f"rotation: apply, {self.rotated} block(s) rotated"
        return (
            f"rotation: {self.setting}, {self.blocks} block(s) with a rotation "
            f"({self.not_identity} not the identity), not applied"
        )


@dataclasses.dataclass(frozen=True, slots=True)
class SoftDelayRecord:
    """What a decoding did with the soft delays of the file (rule 4).

    - `values`: the session's values, (hint, value in s) pairs sorted by hint.
    - `hints`: the hints of the soft delays that the interpreter attaches to the blocks, sorted.
    - `blocks`: the blocks with a soft delay.
    - `applied`: of these, the blocks whose duration the session sets.
    - `unset`: the hints of the file with no value in the session: their blocks keep their
      stored durations (the default of rule 1, recorded, not warned about).
    """

    values: tuple[tuple[str, float], ...]
    hints: tuple[str, ...]
    blocks: int
    applied: int

    @property
    def unset(self) -> tuple[str, ...]:
        given = dict(self.values)
        return tuple(h for h in self.hints if h not in given)

    def __str__(self) -> str:
        if not self.blocks:
            return "soft delays: none in the file"
        text = f"soft delays: {self.applied} of {self.blocks} block(s) set by the session"
        if self.unset:
            text += f"; {', '.join(self.unset)} at the stored durations"
        return text


@dataclasses.dataclass(frozen=True, slots=True)
class FovRecord:
    """What a decoding did with the field of view of the session (rule 4).

    - `rotation` and `scaling`: the session's `fov_rotation` and `gradient_scaling`.
    - `scaling_flag`: the name of the flag that turns off the scaling under the interpreter:
      `"NOSLC"` for `spec` (the specification's spelling), `"NOSCL"` for a reader that spells it
      so.
    - `norot` and `noscale`: the blocks whose NOROT flag, or scaling flag, is set (a state
      across blocks), whatever the session.
    - `rotated` and `scaled`: the blocks whose gradients the decoding turns by the rotation of
      the field of view, or scales: every block without the flag when the session rotates (or
      scales), 0 otherwise.
    """

    rotation: tuple[float, float, float, float]
    scaling: tuple[float, float, float]
    scaling_flag: str
    norot: int
    noscale: int
    rotated: int
    scaled: int

    def __str__(self) -> str:
        return (
            f"field of view: rotation {self.rotation}, {self.rotated} block(s) rotated "
            f"({self.norot} with NOROT); scaling {self.scaling}, {self.scaled} block(s) scaled "
            f"({self.noscale} with {self.scaling_flag})"
        )


@dataclasses.dataclass(frozen=True, slots=True)
class SoftDelay:
    """A soft delay that an interpreter attaches to a block, as `soft_delay_durations` takes it:
    the play index of the block (from 0), the numeric ID, the offset (s), the factor and the
    hint, as the interpreter reads them."""

    block: int
    num: int
    offset: float
    factor: float
    hint: str


def soft_delay_durations(
    session: Session,
    soft_delays: Sequence[SoftDelay],
    stored_ticks: np.ndarray,
    raster: float,
    pure_delay: np.ndarray,
    *,
    interpreter: str,
    version: tuple[int, int, int],
    unavailable: str | None = None,
) -> tuple[np.ndarray, SoftDelayRecord]:
    """The duration of each block (in units of `raster`, the block duration raster in s) under
    the session's soft delays, and the `SoftDelayRecord`: the shared simulation of rule 6.

    `soft_delays` are the soft delays that the interpreter attaches to the blocks, `stored_ticks`
    the stored duration of each block, and `pure_delay` whether each block has no RF, gradient
    or ADC event. `unavailable` is the reason why the file has no soft delays under the
    interpreter (for example a version older than 1.5.0), or None.

    The duration of a block whose soft delay has a value in the session is the specification's
    `value / factor + offset` (spec:550-563), divided by the raster and rounded half away from 0,
    as MATLAB Pulseq's `applySoftDelay` (Sequence.m:2564-2576); other blocks keep their stored
    duration. Raises `SettingError` (rule 8) for a hint of the session when the file has no soft
    delays (`unavailable`) or none with that hint, when its rows disagree on the numeric ID (or
    the numeric ID has another hint too), as MATLAB raises, when a block with that hint has more
    than one soft delay or is not a pure delay block (spec:545), and when the duration is
    negative or not finite (the user, 2026-10-13)."""
    stored_ticks = np.asarray(stored_ticks, dtype=np.int64)
    actual = stored_ticks.copy()
    counts: dict[int, int] = {}
    for d in soft_delays:
        counts[d.block] = counts.get(d.block, 0) + 1
    hints = tuple(sorted({d.hint for d in soft_delays}))

    def error(hint: str, reason: str) -> SettingError:
        return SettingError(f"soft_delays[{hint!r}]", interpreter, version, reason)

    applied = 0
    for hint, value in session.soft_delays:
        if unavailable is not None:
            raise error(hint, unavailable)
        rows = [d for d in soft_delays if d.hint == hint]
        if not rows:
            known = ", ".join(map(repr, hints)) or "none"
            raise error(hint, f"no soft delay of a block has this hint (the hints: {known})")
        nums = sorted({d.num for d in rows})
        if len(nums) > 1:
            raise error(hint, f"its soft delays have the numeric IDs {nums}, not one")
        others = sorted({d.hint for d in soft_delays if d.num == nums[0] and d.hint != hint})
        if others:
            raise error(hint, f"its numeric ID {nums[0]} is also that of the hints {others}")
        for d in rows:
            if counts[d.block] > 1:
                raise error(hint, f"the block at play index {d.block} has more than one soft delay")
            if not pure_delay[d.block]:
                raise error(
                    hint,
                    f"the block at play index {d.block} has an RF, gradient or ADC event: a soft "
                    "delay sets the duration of a pure delay block (spec:545)",
                )
            with np.errstate(divide="ignore", invalid="ignore"):
                ticks = (value / np.float64(d.factor) + d.offset) / raster
            if not np.isfinite(ticks):
                raise error(hint, f"the block at play index {d.block} gets no finite duration")
            rounded = math.copysign(math.floor(abs(ticks) + 0.5), ticks)
            if rounded < 0:
                raise error(
                    hint,
                    f"the block at play index {d.block} gets the negative duration "
                    f"{rounded * raster:g} s",
                )
            actual[d.block] = int(rounded)
            applied += 1
    record = SoftDelayRecord(
        values=session.soft_delays, hints=hints, blocks=len(counts), applied=applied
    )
    return actual, record


def fov_flags(
    block_count: int, label_sets: Iterable[tuple[int, str, int]], scaling_flag: str | None
) -> tuple[np.ndarray, np.ndarray]:
    """The flags NOROT and `scaling_flag` of each block (bool arrays, play order): a state across
    blocks, 0 at the start of the sequence, that each LABELSET of a block sets for that block and
    the blocks after it (spec:522), in the order of the block's list. `label_sets` are the
    (block, name, value) of the LABELSET objects that the interpreter applies; a value that is
    not 0 sets the flag. `scaling_flag` None applies no scaling flag (a file older than 1.4.1)."""
    out = []
    for name in ("NOROT", scaling_flag):
        events = [(b, v) for b, n, v in label_sets if n == name] if name else []
        if not events:
            out.append(np.zeros(block_count, dtype=bool))
            continue
        blocks = np.array([b for b, _ in events], dtype=np.int64)
        values = np.array([v != 0 for _, v in events], dtype=bool)
        order = np.argsort(blocks, kind="stable")
        blocks, values = blocks[order], values[order]
        last = np.searchsorted(blocks, np.arange(block_count), side="right") - 1
        out.append(np.where(last >= 0, values[np.maximum(last, 0)], False))
    return out[0], out[1]


def physical_gradients(
    logical: np.ndarray,
    session: Session,
    scale_rows: np.ndarray,
    block_rows: np.ndarray,
    block_quaternions: np.ndarray,
    fov_rows: np.ndarray,
    rotate: Callable[[np.ndarray, np.ndarray], np.ndarray],
) -> np.ndarray:
    """The gradients (n, 3) on the physical axes from the logical ones `logical` (n, 3), in the
    order of MATLAB Pulseq's `mr.TransformFOV` (TransformFOV.m:58-60, 188-200, 261-263, 416-427;
    the user, 2026-10-13): the session's `gradient_scaling` of the logical axes in the rows
    `scale_rows` (bool, n), then the rotation of the block in the rows `block_rows` (bool, n) by
    `block_quaternions` (one row (q0, qx, qy, qz) for each of them), then the rotation of the
    field of view in the rows `fov_rows` (bool, n). `rotate(quaternions, vectors)` is the
    interpreter's active rotation (for `spec` `decoding.rotate`, for a plugin its reader's). A row
    outside the three masks is `logical` as it is."""
    out = np.array(logical, dtype=np.float64, copy=True).reshape(-1, 3)
    if session.scales:
        out[scale_rows] *= np.asarray(session.gradient_scaling)
    if np.any(block_rows):
        q = np.ascontiguousarray(block_quaternions, dtype=np.float64).reshape(-1, 4)
        out[block_rows] = rotate(q, np.ascontiguousarray(out[block_rows]))
    if session.rotates and np.any(fov_rows):
        n = int(np.count_nonzero(fov_rows))
        q = np.ascontiguousarray(np.broadcast_to(np.asarray(session.fov_rotation), (n, 4)))
        out[fov_rows] = rotate(q, np.ascontiguousarray(out[fov_rows]))
    return out


def fov_record(
    session: Session, norot: np.ndarray, noscale: np.ndarray, scaling_flag: str
) -> FovRecord:
    """The `FovRecord` of a decoding with the flags `norot` and `noscale` of `fov_flags`."""
    norot_count, noscale_count = int(np.count_nonzero(norot)), int(np.count_nonzero(noscale))
    return FovRecord(
        rotation=session.fov_rotation,
        scaling=session.gradient_scaling,
        scaling_flag=scaling_flag,
        norot=norot_count,
        noscale=noscale_count,
        rotated=int(norot.size) - norot_count if session.rotates else 0,
        scaled=int(noscale.size) - noscale_count if session.scales else 0,
    )
