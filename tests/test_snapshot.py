"""Tests of `analyses.load` and the snapshot (`synth/snapshot.py`, task R14).

`load` reads a file or a pypulseq sequence through one interpreter, and the snapshot holds the
interpreter's `SequenceData` and its decoding. The tests check that:

1. `load` of a file is `read_seqfile` of it, and `load` of a sequence is `read_pypulseq` of it,
   through the interpreter given (a name or an object), with its rejections;
2. the snapshot records the interpreter, its settings, the records of the reading and the
   rotation record of the decoding, and `load` warns only for a rotation left unapplied;
3. a snapshot does not change when its sequence changes, and its copies are new snapshots;
4. the type of the argument and the properties of a snapshot.

The tests run without any plugin interpreter installed. A fake plugin (`Unrotated`, in this
module) stands for one: `spec`'s model and decoding, with the rotations left unapplied. The
same tests through `cpp-siemens` are in the plugin's tests
(`packages/pulseq-cpp-siemens/tests/test_load_in_pulseq_analysis.py`).

The results that the tests compare are the index, the event points, the samples of the sampler,
and the four measurements of the gradients with their default arguments.
"""

import copy
import dataclasses
import pathlib
import pickle
import warnings
from typing import Any, ClassVar

import pytest
from optional_pypulseq import pp
from pns_hardware import EXAMPLE_HW
from synthetic import (
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    spin_echo_sequence,
)

from pulseq_analysis._equality import values_equal
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.analyses.grad_spectrum import gradient_spectrum
from pulseq_analysis.analyses.pns_levels import pns_levels
from pulseq_analysis.seqfile import (
    NotSupported,
    SeqFileError,
    SequenceData,
    Spec,
    read_pypulseq,
    read_seqfile,
)
from pulseq_analysis.synth import (
    Decoding,
    RotationRecord,
    ScannerSettingWarning,
    SpecDecoding,
    decode,
)
from pulseq_analysis.synth._events import event_points
from pulseq_analysis.synth.sampling import gradient_sampler, raster_block_lengths
from pulseq_analysis.synth.seq_index import sequence_index
from pulseq_analysis.synth.snapshot import Snapshot, _check_snapshot, _kept_results

SEQFILES = pathlib.Path(__file__).parent / "seqfiles"
# A file of pypulseq with blocks of every kind of gradient, and two radial files whose blocks
# play rotations (ROTATIONS, D2.18): in each, some blocks have a rotation that is not the identity.
GRE_FILE = SEQFILES / "oracle" / "pulseq_seq4.seq"
RADIAL_FILES = [
    SEQFILES / "oracle" / "pulseq_make_radial.seq",
    SEQFILES / "oracle" / "koma_v1.5_rotation_radial_tiny.seq",
]


@dataclasses.dataclass(frozen=True, slots=True)
class Unrotated:
    """A plugin interpreter of the tests (P21): `spec`'s model and decoding under its own name,
    with the rotations of the file left unapplied, as a plugin's default can leave them
    (`cpp-siemens`'s does, D6.2). `load` takes it as an object; it is not installed."""

    name: ClassVar[str] = "unrotated"
    protocol: ClassVar[int] = 1

    def read(self, path: pathlib.Path) -> SequenceData:
        return dataclasses.replace(read_seqfile(path, "spec"), interpreter=self)

    def decode(self, data: SequenceData, session=None) -> "UnrotatedDecoding":
        spec = decode(dataclasses.replace(data, interpreter=Spec()), session)
        assert isinstance(spec, SpecDecoding)
        return UnrotatedDecoding(self, spec)

    def __str__(self) -> str:
        return self.name


@dataclasses.dataclass(frozen=True, eq=False)
class UnrotatedDecoding:
    """The decoding of `Unrotated`: the methods of the protocol `Decoding`, from `spec`'s
    decoding, with the gradients not rotated (the session's field of view is not applied
    either)."""

    interpreter: Unrotated
    spec: SpecDecoding

    @property
    def session(self):
        return self.spec.session

    @property
    def block_count(self) -> int:
        return self.spec.block_count

    @property
    def block_durations(self):
        return self.spec.block_durations

    @property
    def stored_block_durations(self):
        return self.spec.stored_block_durations

    @property
    def soft_delay_record(self):
        return self.spec.soft_delay_record

    @property
    def fov_record(self):
        return self.spec.fov_record

    def fov_flags(self):
        return self.spec.fov_flags()

    def rotations(self):
        return self.spec.rotations()

    @property
    def rotation_record(self) -> RotationRecord:
        applied = self.spec.rotation_record
        return RotationRecord(
            setting="unrotated",
            blocks=applied.blocks,
            not_identity=applied.not_identity,
            rotated=0,
            hint="read the file with spec",
        )

    def gradients_at(self, block_index: Any, time_us: Any, rotated: bool | None = None):
        return self.spec.gradients_at(block_index, time_us, rotated=bool(rotated))

    def gradient_points(self, key: int, block: int, axis: int):
        return self.spec.gradient_points(key, block, axis)

    def gradient_variants(self):
        return self.spec.gradient_variants()


INTERPRETERS = [
    pytest.param("spec", id="spec"),
    pytest.param(Unrotated(), id="plugin"),
]

# The builders of the sequences that the tests run on, with an ID for each.
_BUILDERS = [
    pytest.param(spin_echo_sequence, id="spin_echo"),
    pytest.param(gre_sequence, id="gre"),
    pytest.param(arbitrary_gradient_sequence, id="arbitrary_gradient"),
    pytest.param(border_sequence, id="border"),
    pytest.param(empty_sequence, id="empty"),
]


def _results(snap: Snapshot) -> dict:
    """The results of a snapshot that the tests compare: the index, the event points, the
    samples of the sampler on the raster, and the four measurements of the gradients."""
    index = sequence_index(snap)
    sampler = gradient_sampler(snap)
    lengths = raster_block_lengths(index, snap.data.rasters.gradient)
    samples = {
        axis: sampler.block_samples(axis, 0, index.num_blocks, snap.data.rasters.gradient)
        for axis in ("x", "y", "z")
    }
    return {
        "index": index,
        "points": event_points(snap),
        "lengths": lengths,
        "samples": samples,
        "peaks": gradient_peaks(snap),
        "blocks": block_gradient_values(snap),
        "pns": pns_levels(snap, hardware=EXAMPLE_HW),
        "spectrum": gradient_spectrum(snap),
    }


def _differences(a: dict, b: dict) -> list[str]:
    """The keys of two `_results` whose values are not equal (`values_equal`)."""
    return [key for key in a if not values_equal(a[key], b[key])]


# ---- 1. load reads through the interpreter ----


def check_load_of_a_file(interpreter, decoding_type: str) -> None:
    """`load(GRE_FILE, interpreter)` holds `read_seqfile(GRE_FILE, interpreter)`: equal data,
    the same interpreter object, and the path as `source`. Its decoding is a `Decoding`, of the
    class named `decoding_type`."""
    snap = load(GRE_FILE, interpreter)
    data = read_seqfile(GRE_FILE, interpreter)
    assert snap.data == data
    assert snap.interpreter == data.interpreter
    assert snap.source == str(GRE_FILE)
    assert isinstance(snap.decoding, Decoding)
    assert type(snap.decoding).__name__ == decoding_type


@pytest.mark.parametrize("interpreter", INTERPRETERS)
def test_load_of_a_file_is_the_reading_of_the_interpreter(interpreter):
    """`load(path, interpreter)` holds `read_seqfile(path, interpreter)`
    (`check_load_of_a_file`): for `spec` with a `SpecDecoding`, and for a plugin with the
    decoding that the plugin gives."""
    check_load_of_a_file(
        interpreter, "SpecDecoding" if interpreter == "spec" else "UnrotatedDecoding"
    )


def test_the_default_interpreter_of_load_is_spec():
    """`load` with no interpreter reads through `spec`, the default of `read_seqfile` (P19)."""
    assert load(GRE_FILE).interpreter == Spec()


def check_load_of_a_sequence(seq: pp.Sequence, interpreter) -> None:
    """`load(seq, interpreter)` holds `read_pypulseq(seq, interpreter)` (the sequence written with
    pypulseq's writer, then read, task R15), with `source` None, and changes nothing of `seq`
    that the writer reads: a second `load` gives equal data."""
    snap = load(seq, interpreter)
    assert snap.data == read_pypulseq(seq, interpreter)
    assert snap.data.origin == "pypulseq"
    assert snap.source is None
    assert load(seq, interpreter).data == snap.data


@pytest.mark.pypulseq
@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize("build", _BUILDERS)
def test_load_of_a_sequence_is_read_pypulseq_of_it(build, interpreter):
    """`load(seq, interpreter)` holds `read_pypulseq(seq, interpreter)`
    (`check_load_of_a_sequence`)."""
    check_load_of_a_sequence(build(), interpreter)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("bad_gradient_nonzero_end_align.seq", "gradient.nonzero-end-align"),
        ("bad_raster_gradient_delay.seq", "raster.gradient-delay"),
    ],
)
def test_load_raises_the_rejection_of_the_interpreter(name, code):
    """A file that `spec` rejects raises its `SeqFileError` from `load`, with the code."""
    with pytest.raises(SeqFileError) as caught:
        load(SEQFILES / name)
    assert code in caught.value.codes


def test_load_raises_not_supported_for_a_version_outside_the_package():
    """A file of version 1.3 raises `NotSupported` from `load` (Q1)."""
    with pytest.raises(NotSupported):
        load(SEQFILES / "bad_version_unsupported_1_3.seq")


def test_load_accepts_a_file_with_no_signature():
    """A file with no `[SIGNATURE]` section gives a snapshot whose data has no signature."""
    snap = load(SEQFILES / "valid_no_signature.seq")
    assert snap.data.signature is None
    assert sequence_index(snap).num_blocks > 0


# ---- 2. What the snapshot records, and the warning ----


def test_the_snapshot_records_the_interpreter_with_its_settings_and_the_records():
    """`interpreter` is the interpreter object that `load` was given, and `records` is the
    records of the reading (P20, rule 4): here the unknown extension of `valid_1_5_1.seq` that
    `spec` ignores and records (D2.17)."""
    setting = Unrotated()
    assert load(GRE_FILE, setting).interpreter is setting
    spec = load(SEQFILES / "valid_1_5_1.seq")
    assert spec.records == read_seqfile(SEQFILES / "valid_1_5_1.seq").records
    assert [(r.kind, r.subject, r.reason) for r in spec.records] == [
        ("extension", "UNKNOWN", "unknown")
    ]


def check_load_warns_for_an_unapplied_rotation(path: pathlib.Path, interpreter) -> RotationRecord:
    """`load(path, interpreter)` keeps the decoding's rotation record and emits its
    `ScannerSettingWarning` once: blocks play a rotation that the measurements do not apply
    (P20, rule 4; Q3). Returns the record."""
    with pytest.warns(ScannerSettingWarning, match="play a rotation") as caught:
        snap = load(path, interpreter)
    assert len([w for w in caught if w.category is ScannerSettingWarning]) == 1
    record = snap.rotation_record
    assert record == snap.decoding.rotation_record
    assert record.rotated == 0 and record.unapplied > 0
    return record


@pytest.mark.parametrize("path", RADIAL_FILES, ids=lambda p: p.stem)
def test_load_warns_for_a_rotation_that_a_plugin_leaves_unapplied(path):
    """With a plugin whose decoding leaves the rotations unapplied, `load` emits the warning of
    its rotation record once (`check_load_warns_for_an_unapplied_rotation`), with the
    plugin's hint."""
    with pytest.warns(ScannerSettingWarning, match="read the file with spec"):
        load(path, Unrotated())
    assert check_load_warns_for_an_unapplied_rotation(path, Unrotated()).setting == "unrotated"


def check_load_applies_rotations_without_a_warning(path: pathlib.Path, interpreter) -> None:
    """`load(path, interpreter)` reads a file whose blocks play rotations, the decoding rotates
    every block that has a rotation, the record has no block left unapplied, and `load` emits
    no `ScannerSettingWarning`."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", ScannerSettingWarning)
        snap = load(path, interpreter)
    record = snap.rotation_record
    assert record.setting == "apply"
    assert record.rotated == record.blocks > 0
    assert record.unapplied == 0
    assert gradient_peaks(snap).reason is None


@pytest.mark.parametrize("path", RADIAL_FILES, ids=lambda p: p.stem)
def test_load_does_not_refuse_rotations_and_does_not_warn_when_they_are_applied(path):
    """`load` reads a file whose blocks play rotations (it no longer refuses the extension), and
    with `spec` (from 1.5.1) the decoding rotates every block that has a rotation
    (`check_load_applies_rotations_without_a_warning`)."""
    check_load_applies_rotations_without_a_warning(path, "spec")


def check_load_does_not_warn_for_a_rotation_that_no_block_plays(interpreter) -> None:
    """A file that defines a rotation that no block uses has no block with a rotation in the
    record of `interpreter`, and `load` does not warn."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", ScannerSettingWarning)
        snap = load(SEQFILES / "valid_1_5_1_rotation_not_played.seq", interpreter)
    assert snap.rotation_record.blocks == 0


def test_load_does_not_warn_for_a_rotation_that_no_block_plays():
    """With a plugin that leaves the rotations unapplied, a rotation that no block plays gives
    no warning (`check_load_does_not_warn_for_a_rotation_that_no_block_plays`)."""
    check_load_does_not_warn_for_a_rotation_that_no_block_plays(Unrotated())


def test_the_rotation_changes_the_measured_gradients_only_where_it_is_applied():
    """On a radial file, the peaks of `spec` (which rotates, P20) differ from those of a plugin
    that leaves the rotations unapplied: the measurements take the gradients of the decoding."""
    path = RADIAL_FILES[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        unrotated = load(path, Unrotated())
    applied = gradient_peaks(load(path, "spec"))
    assert not values_equal(applied.axes, gradient_peaks(unrotated).axes)


# ---- 3. Independence and copies ----


def _scale_first_trapezoid(seq: pp.Sequence) -> None:
    """Scale the amplitude of the first trapezoid of `seq` in its library, in place."""
    for key, row in seq.grad_library.data.items():
        if seq.grad_library.type[key] == "t":
            seq.grad_library.data[key] = (row[0] * 0.5, *row[1:])
            return
    raise AssertionError("no trapezoid")


@pytest.mark.pypulseq
@pytest.mark.parametrize("warm", [False, True], ids=["results_after_the_change", "kept_results"])
def test_a_change_of_the_sequence_changes_no_result_of_its_snapshot(warm):
    """After `load(seq)`, a change of `seq` in place changes no result of the snapshot (made
    after the change, or kept before it), and a new `load` of `seq` gives the new results."""
    seq = spin_echo_sequence()
    snap = load(seq)
    reference = _results(load(spin_echo_sequence()))
    if warm:
        _results(snap)
    _scale_first_trapezoid(seq)
    assert _differences(_results(snap), reference) == []
    assert _differences(_results(load(seq)), reference) != []


COPIERS = [
    pytest.param(lambda s: pickle.loads(pickle.dumps(s)), id="pickle"),
    pytest.param(copy.deepcopy, id="deepcopy"),
]


def check_a_copy_of_a_snapshot(copier, interpreter) -> None:
    """A copy of a snapshot of `GRE_FILE` from `copier` is a new `Snapshot` with equal data, the
    same interpreter and `source`, no kept results, and equal results (made again)."""
    snap = load(GRE_FILE, interpreter)
    results = _results(snap)
    assert _kept_results(snap)
    other = copier(snap)
    assert isinstance(other, Snapshot)
    assert other is not snap
    assert other.data == snap.data
    assert other.interpreter == snap.interpreter
    assert other.source == snap.source
    assert _kept_results(other) == {}
    assert _differences(_results(other), results) == []


@pytest.mark.parametrize("copier", COPIERS)
def test_a_copy_of_a_snapshot_is_a_new_snapshot_with_no_kept_results(copier):
    """A copy of a `spec` snapshot from `pickle` or `copy.deepcopy` is a new snapshot with no
    kept results (`check_a_copy_of_a_snapshot`)."""
    check_a_copy_of_a_snapshot(copier, "spec")


# ---- 4. Types and properties ----


@pytest.mark.parametrize(
    "bad", [None, 3, b"sequence.seq", [spin_echo_sequence], "snapshot"], ids=str
)
def test_load_refuses_another_type_and_a_snapshot(bad):
    """`load` raises `TypeError` that names `load` for `None`, an `int`, `bytes`, a list and a
    `Snapshot`."""
    if bad == "snapshot":
        bad = load(GRE_FILE)
    with pytest.raises(TypeError, match="load"):
        load(bad)


def test_load_raises_for_an_interpreter_that_does_not_exist():
    """An interpreter name that does not exist raises the `ValueError` of `seqfile.interpreter`."""
    with pytest.raises(ValueError, match="no interpreter"):
        load(GRE_FILE, "strict")


@pytest.mark.parametrize(
    "make_bad",
    [
        pytest.param(spin_echo_sequence, id="Sequence", marks=pytest.mark.pypulseq),
        pytest.param(lambda: None, id="NoneType"),
        pytest.param(lambda: "sequence.seq", id="str"),
    ],
)
def test_check_snapshot_raises_a_type_error_that_names_load(make_bad):
    """`_check_snapshot` raises `TypeError` that names `load` for a `pp.Sequence`, `None` and a
    path, and nothing for a `Snapshot`."""
    _check_snapshot(load(GRE_FILE))
    bad = make_bad()
    with pytest.raises(TypeError, match="load"):
        _check_snapshot(bad)


@pytest.mark.pypulseq
def test_a_snapshot_takes_only_a_sequence_data():
    """`Snapshot(data)` raises `TypeError` for an argument that is not a `SequenceData`."""
    with pytest.raises(TypeError, match="SequenceData"):
        Snapshot(spin_echo_sequence())


def test_a_snapshot_has_read_only_properties_no_new_attribute_and_the_hash_of_its_identity():
    """The properties cannot be set, a new attribute cannot be added (`__slots__`), two
    snapshots of one file are not equal, and a snapshot is a key of a dict by identity."""
    snap, other = load(GRE_FILE), load(GRE_FILE)
    for name in (
        "data",
        "decoding",
        "interpreter",
        "records",
        "rotation_record",
        "source",
        "extra",
    ):
        with pytest.raises(AttributeError):
            setattr(snap, name, None)
    same = snap
    assert snap == same
    assert snap != other
    assert hash(snap) == hash(same)
    assert {snap: 1, other: 2}[snap] == 1


@pytest.mark.pypulseq
@pytest.mark.parametrize("make_path", [str, pathlib.Path], ids=["str", "path"])
def test_load_accepts_a_path_like_and_source_is_its_str(make_path, tmp_path):
    """`load` takes a `str` and an `os.PathLike`, and `snapshot.source` is the `str` of the path."""
    path = tmp_path / "a.seq"
    spin_echo_sequence().write(str(path))
    snap = load(make_path(str(path)))
    assert snap.source == str(path)
    assert isinstance(snap.source, str)
    assert sequence_index(snap).num_blocks == 6
