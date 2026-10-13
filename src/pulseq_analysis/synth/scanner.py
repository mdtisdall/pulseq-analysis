"""What a decoding applies of the scanner-side settings, and the warning for content of the file
that it leaves unapplied (rules 4 and 7 of section 7.8 of `docs/plans/parser-redesign.md`, P20).

The scanner's interpreter acts on information that a reader can leave to it. Each result of
the package records what it applied of it, and `ScannerSettingWarning` is emitted only where
content of the file itself is left unapplied: today, the rotations that a plugin interpreter's
decoding does not apply, in a file where a block plays a rotation. A neutral scanner session is
recorded, not warned about.

- `RotationRecord`: what the decoding did with the rotations of the file (the ROTATIONS
  extension, D49). `rotation_record` of each decoding (`decoding.Decoding`) gives it. `spec`
  applies the rotations of a file from 1.5.1 (P20, rule 2), so its record never has a warning.
- `ScannerSettingWarning`: the warning; `RotationRecord.warning()` gives it, or None. The
  decoding does not emit it: the measurements (`load`, task R14) emit it, so that a reader of the
  decoding (pulseq-checks) is not warned about the reader's own output.

The records are part of the contract with pulseq-checks (section 7.3 of the plan): a change to
them is noted in `CHANGELOG.md`.
"""

import dataclasses

__all__ = ["RotationRecord", "ScannerSettingWarning"]


class ScannerSettingWarning(UserWarning):
    """Content of the file that the scanner's interpreter applies and the package's result does
    not, for example a block's rotation that a decoding leaves unapplied. It describes the
    package's measurement, not the file."""


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
