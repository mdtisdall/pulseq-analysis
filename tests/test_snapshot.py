"""Tests of the snapshot (`snapshot.py`): the four guards of `load`.

1. No mutable object is shared between the source and the snapshot (a walk of both object
   graphs), so no change of the source reaches the snapshot.
2. The snapshot is faithful: it writes the bytes of its source, and its results are those of
   the same sequence with no copy and of the file that it was read from.
3. A change of the source with each kind of call of pypulseq changes no result of the
   snapshot, and a new `load` of the source gives the new results.
4. `load` refuses a sequence with a rotation and accepts a sequence and a file with no
   `[SIGNATURE]` hash, and no measurement of a snapshot calls the check again.

The results that the tests compare are the index, the events, the event points, the samples
of the sampler, and the four measurements of the gradients with their default arguments.
"""

import copy
import importlib
import math
import pathlib
import pickle

import numpy as np
import pypulseq as pp
import pytest
from synthetic import (
    EXAMPLE_HW,
    SYSTEM,
    WIDTH,
    arbitrary_gradient_sequence,
    border_sequence,
    empty_sequence,
    gre_sequence,
    signed,
    spin_echo_sequence,
    with_rotation_library,
)

from pulseq_analysis import extensions
from pulseq_analysis import snapshot as snapshot_module
from pulseq_analysis._equality import values_equal
from pulseq_analysis._events import event_points
from pulseq_analysis.grad_peaks import block_gradient_values, gradient_peaks
from pulseq_analysis.grad_spectrum import gradient_spectrum
from pulseq_analysis.pns_levels import pns_levels
from pulseq_analysis.sampling import gradient_sampler, raster_block_lengths
from pulseq_analysis.seq_index import adc_events, grad_events, rf_events, sequence_index
from pulseq_analysis.snapshot import Snapshot, _check_snapshot, _kept_results, load

# The columns of a row of `seq.block_events` that the direct writes of the tests use.
_GX_COLUMN, _GY_COLUMN = 2, 3


def _every_event_sequence() -> pp.Sequence:
    """A signed sequence with each kind of event that `add_block` takes: a sinc pulse with its
    slice gradients (shapes), a trapezoid with an ADC and two labels, an arbitrary gradient, an
    extended trapezoid, a digital output, a trigger, a soft delay and a delay, and definitions
    of a string, a number and a list."""
    seq = pp.Sequence(SYSTEM)
    rf, gz, gz_reph = pp.make_sinc_pulse(
        flip_angle=math.pi / 6,
        duration=1e-3,
        delay=SYSTEM.rf_dead_time,
        slice_thickness=5e-3,
        apodization=0.5,
        time_bw_product=4,
        system=SYSTEM,
        return_gz=True,
        use="excitation",
    )
    seq.add_block(rf, gz)
    seq.add_block(gz_reph)
    gx = pp.make_trapezoid(channel="x", flat_time=1e-3, flat_area=500, system=SYSTEM)
    adc = pp.make_adc(num_samples=32, dwell=20e-6, delay=gx.rise_time, system=SYSTEM)
    seq.add_block(gx, adc, pp.make_label("LIN", "SET", 3), pp.make_label("REP", "INC", 1))
    n = 40
    waveform = 0.1 * SYSTEM.max_grad * np.sin(np.pi * (np.arange(n) + 0.5) / n)
    seq.add_block(pp.make_arbitrary_grad(channel="y", waveform=waveform, system=SYSTEM))
    seq.add_block(
        pp.make_extended_trapezoid(
            channel="z",
            amplitudes=np.array([0.0, 1e4, 1e4, 0.0]),
            times=np.array([0.0, 1e-4, 5e-4, 6e-4]),
            system=SYSTEM,
        )
    )
    seq.add_block(pp.make_digital_output_pulse("osc0", duration=1e-3, system=SYSTEM))
    seq.add_block(pp.make_trigger("physio1", duration=1e-3, system=SYSTEM))
    seq.add_block(pp.make_soft_delay("TE", default_duration=2e-3))
    seq.add_block(pp.make_delay(1e-3))
    seq.set_definition("Name", "every")
    seq.set_definition("FOV", [0.2, 0.2, 0.005])
    seq.set_definition("Number", 3)
    return signed(seq)


def _soft_delay_sequence() -> pp.Sequence:
    """A signed sequence with a trapezoid on x, a soft delay `TE` of 2 ms and a trapezoid on y:
    `apply_soft_delay(TE=...)` changes the duration of the block between them."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=2 / WIDTH, system=SYSTEM))
    seq.add_block(pp.make_soft_delay("TE", default_duration=2e-3))
    seq.add_block(pp.make_trapezoid(channel="y", area=3 / WIDTH, system=SYSTEM))
    return signed(seq)


def _unsigned_sequence() -> pp.Sequence:
    """A sequence that `add_block` built, with no `[SIGNATURE]` hash."""
    seq = pp.Sequence(SYSTEM)
    seq.add_block(pp.make_trapezoid(channel="x", area=2 / WIDTH, system=SYSTEM))
    return seq


def _read(path) -> pp.Sequence:
    seq = pp.Sequence()
    seq.read(str(path))
    return seq


def _written(seq: pp.Sequence, path) -> str:
    """`seq.write(path)` and the path as a `str`."""
    seq.write(str(path))
    return str(path)


# The builders of the signed sequences that the guards run on, with an ID for each.
_BUILDERS = [
    pytest.param(_every_event_sequence, id="every_event"),
    pytest.param(spin_echo_sequence, id="spin_echo"),
    pytest.param(gre_sequence, id="gre"),
    pytest.param(arbitrary_gradient_sequence, id="arbitrary_gradient"),
    pytest.param(border_sequence, id="border"),
    pytest.param(_soft_delay_sequence, id="soft_delay"),
    pytest.param(empty_sequence, id="empty"),
]


# ---- Guard 1: no mutable object is shared ----

_IMMUTABLE = (bool, int, float, complex, str, bytes, type(None), np.generic, np.dtype)


def _read_only(array: np.ndarray) -> bool:
    """Whether `array` cannot change: it and each array that it is a view of is read-only,
    and the data is `bytes` or has no owner object."""
    base = array
    while isinstance(base, np.ndarray):
        if base.flags.writeable:
            return False
        base = base.base
    return base is None or isinstance(base, bytes)


def _mutable_objects(root: object) -> dict[int, object]:
    """Each object that can be reached from `root` and that can change, by `id`: lists, dicts,
    sets, arrays that are not read-only, objects with attributes, and an object of a type
    that this walk does not know. It does not include numbers, strings, `None`, numpy scalars
    and dtypes, tuples and frozensets (a tuple holds no mutable object that the walk does not
    find in it), or a read-only array. The walk goes through attributes, `__slots__`, dicts,
    lists, tuples, sets and the items and the base of an array."""
    found: dict[int, object] = {}
    seen: set[int] = set()
    stack = [root]
    while stack:
        obj = stack.pop()
        if id(obj) in seen or isinstance(obj, _IMMUTABLE):
            continue
        seen.add(id(obj))
        if isinstance(obj, tuple | frozenset):
            stack.extend(obj)
            continue
        if isinstance(obj, np.ndarray):
            if not _read_only(obj):
                found[id(obj)] = obj
            if obj.dtype == object:
                stack.extend(obj.ravel().tolist())
            if isinstance(obj.base, np.ndarray):
                stack.append(obj.base)
            continue
        found[id(obj)] = obj
        # An object that has none of these is of a type that the walk does not know: it is in
        # `found` as mutable, and the walk goes no further.
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, list | set):
            stack.extend(obj)
        if hasattr(obj, "__dict__"):
            stack.extend(vars(obj).values())
        for cls in type(obj).__mro__:
            for name in getattr(cls, "__slots__", ()):
                if hasattr(obj, name):
                    stack.append(getattr(obj, name))
    return found


def _shared(a: object, b: object) -> list[object]:
    """The mutable objects that are in the object graph of both `a` and `b`."""
    in_a, in_b = _mutable_objects(a), _mutable_objects(b)
    return [in_a[i] for i in in_a.keys() & in_b.keys()]


def _describe(objects: list[object]) -> list[str]:
    return [f"{type(obj).__name__}: {str(obj)[:60]}" for obj in objects]


@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold", "warm_block_cache"])
@pytest.mark.parametrize("build", _BUILDERS)
def test_a_snapshot_of_a_sequence_shares_no_mutable_object_with_it(build, warm_cache):
    """The object graph of the sequence and the object graph of `load(seq).sequence` (a walk
    through attributes, dicts, lists, tuples, sets, and the items and the base of arrays) have
    no mutable object in common: no list, dict, set, writable array, object with attributes, or
    object of an unknown type. Before the check, the walk finds the objects that a shallow
    copy shares with the sequence, so it can fail. With `warm_cache`, each block of the source is
    in `seq.block_cache` before `load`: the snapshot has an empty block cache that is turned off,
    and the source keeps its own cache object with the same blocks."""
    seq = build()
    if warm_cache:
        for block_id in list(seq.block_events):
            seq.get_block(block_id)
        cache, cached = seq.block_cache, dict(seq.block_cache)
        assert cached
    assert _shared(seq, copy.copy(seq))
    snap = load(seq)
    assert _describe(_shared(seq, snap.sequence)) == []
    assert snap.sequence is not seq
    assert snap.source is None
    assert snap.sequence.use_block_cache is False
    assert snap.sequence.block_cache == {}
    if warm_cache:
        assert seq.block_cache is cache
        assert seq.block_cache == cached
        assert seq.use_block_cache is True


@pytest.mark.parametrize("build", [_every_event_sequence, _soft_delay_sequence, gre_sequence])
def test_a_snapshot_of_a_sequence_read_from_a_file_shares_no_mutable_object_with_it(
    build, tmp_path
):
    """A sequence that `read` made from a file with definitions, labels, extensions and soft
    delays (the file that `write` makes from the synthetic sequence) shares no mutable object
    with `load(seq).sequence`, by the walk of the test above."""
    seq = _read(_written(build(), tmp_path / "a.seq"))
    snap = load(seq)
    assert _describe(_shared(seq, snap.sequence)) == []
    assert snap.sequence is not seq


# ---- Guard 2: fidelity ----


def _gradient_results(snap: Snapshot) -> dict[str, object]:
    """The four measurements of the gradients of `snap`, with their default arguments."""
    return {
        "peaks": gradient_peaks(snap),
        "block_values": block_gradient_values(snap),
        "pns": pns_levels(snap, hardware=EXAMPLE_HW),
        "spectrum": gradient_spectrum(snap),
    }


def _results(snap: Snapshot) -> dict[str, object]:
    """The results that the tests compare: the index, the events (each as its attributes), the
    event points, the samples of each axis of the sampler at 501 times from 0 to the end (and
    `block_samples` of the whole sequence, when it is on the raster), and the four measurements
    of the gradients."""
    index = sequence_index(snap)
    results: dict[str, object] = {"index": index, "points": event_points(snap)}
    for name, events in (("rf", rf_events), ("grad", grad_events), ("adc", adc_events)):
        results[name] = tuple((number, vars(event)) for number, event in events(snap))
    sampler = gradient_sampler(snap)
    dt = SYSTEM.grad_raster_time
    on_raster = raster_block_lengths(index, dt)[1]
    for axis in ("gx", "gy", "gz"):
        results[f"sample_{axis}"] = sampler.sample(axis, np.linspace(0.0, index.end_s, 501))
        if on_raster:
            results[f"block_samples_{axis}"] = sampler.block_samples(axis, 0, index.num_blocks, dt)
    results.update(_gradient_results(snap))
    return results


def _differences(a: dict[str, object], b: dict[str, object]) -> list[str]:
    """The names of the results of `a` and `b` that are not equal (`values_equal`)."""
    assert a.keys() == b.keys()
    return [name for name in a if not values_equal(a[name], b[name])]


@pytest.mark.parametrize("build", _BUILDERS)
def test_a_snapshot_writes_the_bytes_of_its_source(build, tmp_path):
    """`load(seq).sequence.write(path)` gives a file with the same bytes as
    `seq.write(path)`, for the sequences of the guards. The snapshot is made before either
    write, because `write` sets the definition `TotalDuration` and the signature of the
    sequence that it writes."""
    seq = build()
    snap = load(seq)
    expected = _written(seq, tmp_path / "source.seq")
    actual = _written(snap.sequence, tmp_path / "snapshot.seq")
    with open(expected, "rb") as f, open(actual, "rb") as g:
        assert f.read() == g.read()


@pytest.mark.parametrize("build", _BUILDERS)
def test_load_of_a_sequence_and_of_its_file_give_equal_results(build, tmp_path):
    """For the file that `write` makes from a sequence and the sequence that `read` makes
    from that file, `load(seq)` (a copy) and `load(path)` (no copy) have equal results: the
    index, the events, the event points, the samples and the four measurements. The sequence
    is read from the file, because `write` rounds the values of the file, and then `load(path)` has
    the same values as the source. `snapshot.source` is the path."""
    path = _written(build(), tmp_path / "a.seq")
    from_path = load(path)
    assert from_path.source == path
    assert _differences(_results(load(_read(path))), _results(from_path)) == []


@pytest.mark.parametrize("build", _BUILDERS)
def test_a_snapshot_of_a_sequence_has_the_results_of_the_same_sequence_with_no_copy(build):
    """The results of `load(build())` (a copy) are equal to the results of
    `Snapshot(build())`, which holds a second sequence of the same blocks with no copy, so the
    copy does not change a value (here the values are those of memory, not rounded by a
    file)."""
    assert _differences(_results(load(build())), _results(Snapshot(build()))) == []


# ---- Guard 3: independence ----


def _mod_grad_axis(seq: pp.Sequence) -> None:
    seq.mod_grad_axis("x", 0.5)


def _set_existing_block(seq: pp.Sequence) -> None:
    """Replace block 3 of the spin echo (a crusher on y) with a larger one."""
    seq.set_block(3, pp.make_trapezoid(channel="y", area=6 / WIDTH, system=SYSTEM))


def _apply_soft_delay(seq: pp.Sequence) -> None:
    seq.apply_soft_delay(TE=5e-3)


def _write_into_block_events(seq: pp.Sequence) -> None:
    """Remove the gradient of x of block 2 of the spin echo, with a write into its row."""
    seq.block_events[2][_GX_COLUMN] = 0


def _write_into_block_durations(seq: pp.Sequence) -> None:
    seq.block_durations[1] *= 2


def _write_the_gradient_raster(seq: pp.Sequence) -> None:
    seq.grad_raster_time = 2 * seq.grad_raster_time


_CHANGES = [
    pytest.param(gre_sequence, _mod_grad_axis, id="mod_grad_axis"),
    pytest.param(spin_echo_sequence, _set_existing_block, id="set_block_existing_id"),
    pytest.param(_soft_delay_sequence, _apply_soft_delay, id="apply_soft_delay"),
    pytest.param(spin_echo_sequence, _write_into_block_events, id="write_block_events"),
    pytest.param(spin_echo_sequence, _write_into_block_durations, id="write_block_durations"),
    pytest.param(gre_sequence, _write_the_gradient_raster, id="write_grad_raster_time"),
]


@pytest.mark.parametrize("warm", [False, True], ids=["results_after_the_change", "kept_results"])
@pytest.mark.parametrize(("build", "change"), _CHANGES)
def test_a_change_of_the_source_changes_no_result_of_the_snapshot(build, change, warm):
    """After `load(seq)`, a call of pypulseq that changes `seq` in place (`mod_grad_axis`,
    `set_block` on an existing block ID, `apply_soft_delay`) or a direct write into
    `seq.block_events`, `seq.block_durations` or `seq.grad_raster_time` changes no result of the
    snapshot: its results equal those of `load` of a second sequence that was built in the
    same way and not changed. This holds when the snapshot made its results before the change
    (`kept_results`) and when it makes them after it (`results_after_the_change`). The change does
    change the results: a new `load(seq)` gives results that differ from the old ones and equal
    those of `load` of the second sequence with the same change."""
    reference = _results(load(build()))
    seq = build()
    snap = load(seq)
    if warm:
        _results(snap)
    change(seq)
    assert _differences(_results(snap), reference) == []

    changed = build()
    change(changed)
    after = _results(load(seq))
    assert _differences(after, _results(load(changed))) == []
    assert _differences(after, reference) != []


# ---- Guard 4: the checks ----


def _signed_and_unsigned_files(directory) -> tuple[str, str]:
    """Two files of the spin echo: the file that `write` made, and a copy with its
    `[SIGNATURE]` section removed."""
    signed_path = directory / "signed.seq"
    _written(spin_echo_sequence(), signed_path)
    text = signed_path.read_text()
    unsigned_path = directory / "unsigned.seq"
    unsigned_path.write_text(text[: text.index("[SIGNATURE]")])
    assert "[SIGNATURE]" not in unsigned_path.read_text()
    return str(signed_path), str(unsigned_path)


def _with_hash(seq: pp.Sequence) -> pp.Sequence:
    """`seq` with the three signature attributes that `write` sets, given by hand."""
    seq.signature_type = "md5"
    seq.signature_file = "text"
    seq.signature_value = "0123456789abcdef0123456789abcdef"
    return seq


def _with_rotations_extension_type() -> pp.Sequence:
    """A `gre_sequence` with the `"ROTATIONS"` extension type registered, as the `read` of a
    file with a rotation section registers it."""
    seq = gre_sequence(num_trs=2)
    seq.set_extension_string_ID("ROTATIONS", 1)
    return seq


def _unsigned_and_rotated() -> pp.Sequence:
    seq = with_rotation_library()
    seq.signature_value = ""
    return seq


def test_load_accepts_an_unsigned_sequence_and_an_unsigned_file(tmp_path):
    """`load` gives a snapshot of a sequence that `add_block` built (no hash) and of a file with
    no `[SIGNATURE]` section. It adds no hash, and the hash changes no result: the results equal
    those of the same sequence with a hash, and of the same file with its section. The file is
    compared with a file, because `write` rounds the values."""
    snap = load(_unsigned_sequence())
    assert snap.sequence.signature_value == ""
    assert _differences(_results(snap), _results(load(_with_hash(_unsigned_sequence())))) == []

    signed_path, unsigned_path = _signed_and_unsigned_files(tmp_path)
    unsigned_snap = load(unsigned_path)
    assert unsigned_snap.sequence.signature_value == ""
    assert _differences(_results(unsigned_snap), _results(load(signed_path))) == []


@pytest.mark.parametrize(
    "build", [with_rotation_library, _with_rotations_extension_type], ids=["library", "extension"]
)
def test_load_refuses_a_sequence_with_a_rotation(build):
    """`load` raises `NotImplementedError` for a sequence with a rotation library, and for a
    sequence with the `ROTATIONS` extension type."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        load(build())


def test_load_refuses_an_unsigned_sequence_with_a_rotation():
    """A sequence that is unsigned and has a rotation gives the `NotImplementedError` of the
    rotation: the rotation check does not depend on a hash."""
    with pytest.raises(NotImplementedError, match="rotation extension"):
        load(_unsigned_and_rotated())


@pytest.mark.parametrize("build", _BUILDERS)
def test_load_calls_refuse_rotations_once_and_no_measurement_calls_it(build, monkeypatch):
    """`load` calls `refuse_rotations` one time. After that, the index, the events, the event
    points, the sampler and the four measurements of the gradients of the snapshot do not call
    it: it is replaced, in `extensions` and in each module that can have imported it, by a
    function that fails."""
    calls = 0
    original = extensions.refuse_rotations

    def count(seq):
        nonlocal calls
        calls += 1
        original(seq)

    monkeypatch.setattr(snapshot_module, "refuse_rotations", count)
    snap = load(build())
    assert calls == 1

    def fail(seq):
        raise AssertionError("refuse_rotations was called by a measurement")

    names = ("seq_index", "_events", "sampling", "grad_peaks", "pns_levels", "grad_spectrum")
    modules = [importlib.import_module(f"pulseq_analysis.{name}") for name in names]
    for module in (extensions, snapshot_module, *modules):
        monkeypatch.setattr(module, "refuse_rotations", fail, raising=False)
    _results(snap)
    assert calls == 1


# ---- The type of the argument, the copies and the properties of a snapshot ----


@pytest.mark.parametrize(
    "bad", [None, 3, b"sequence.seq", [spin_echo_sequence], "snapshot"], ids=str
)
def test_load_refuses_another_type_and_a_snapshot(bad):
    """`load` raises `TypeError` that names `load` for `None`, an `int`, `bytes`, a list and a
    `Snapshot`."""
    if bad == "snapshot":
        bad = load(spin_echo_sequence())
    with pytest.raises(TypeError, match="load"):
        load(bad)


@pytest.mark.parametrize("bad", [spin_echo_sequence(), None, "sequence.seq"], ids=type)
def test_check_snapshot_raises_a_type_error_that_names_load(bad):
    """`_check_snapshot` raises `TypeError` that names `load` for a `pp.Sequence`, `None` and a
    path, and nothing for a `Snapshot`."""
    _check_snapshot(load(spin_echo_sequence()))
    with pytest.raises(TypeError, match="load"):
        _check_snapshot(bad)


@pytest.mark.parametrize("copier", [lambda s: pickle.loads(pickle.dumps(s)), copy.deepcopy])
def test_a_copy_of_a_snapshot_is_a_new_snapshot_with_no_kept_results(copier, tmp_path):
    """A copy of a snapshot of a file from `pickle` or `copy.deepcopy` is a `Snapshot` and a new
    object, with a new sequence, the same `source` (the path), no kept results, and an equal
    index and equal event points (made again)."""
    path = tmp_path / "gre.seq"
    gre_sequence().write(str(path))
    snap = load(path)
    assert snap.source == str(path)
    index, points = sequence_index(snap), event_points(snap)
    assert _kept_results(snap)
    other = copier(snap)
    assert isinstance(other, Snapshot)
    assert other is not snap
    assert other.sequence is not snap.sequence
    assert other.source == snap.source
    assert _kept_results(other) == {}
    assert values_equal(sequence_index(other), index)
    assert values_equal(event_points(other), points)


def test_a_snapshot_has_read_only_properties_no_new_attribute_and_the_hash_of_its_identity():
    """`sequence` and `source` cannot be set, a new attribute cannot be added (`__slots__`), two
    snapshots of one sequence are not equal, and a snapshot is a key of a dict by identity."""
    seq = spin_echo_sequence()
    snap, other = load(seq), load(seq)
    for name in ("sequence", "source", "extra"):
        with pytest.raises(AttributeError):
            setattr(snap, name, None)
    same = snap
    assert snap == same
    assert snap != other
    assert hash(snap) == hash(same)
    assert {snap: 1, other: 2}[snap] == 1


@pytest.mark.parametrize("make_path", [str, pathlib.Path], ids=["str", "path"])
def test_load_accepts_a_path_like_and_source_is_its_str(make_path, tmp_path):
    """`load` takes a `str` and an `os.PathLike`, and `snapshot.source` is the `str` of the path."""
    path = _written(spin_echo_sequence(), tmp_path / "a.seq")
    snap = load(make_path(path))
    assert snap.source == path
    assert isinstance(snap.source, str)
    assert sequence_index(snap).num_blocks == 6
