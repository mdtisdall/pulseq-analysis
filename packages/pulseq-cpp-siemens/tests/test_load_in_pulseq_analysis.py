"""Tests of `load` of pulseq-analysis through `cpp-siemens` (task R14): the snapshot, the
warning of an unapplied rotation, the block table, and the gradients that the measurements play
(`pulseq_analysis.synth._played`), from the decoding of the C++ reader.

The tests of pulseq-analysis run without the plugin, with `spec` and a fake plugin. These are
their cases for `cpp-siemens` and its settings: they call the `check_*` helpers of
`test_snapshot`, `test_seq_index` and `test_played`, or test what only the reader's decoding has.
The module is not collected without pulseq-analysis (`conftest.py`).
"""

import warnings
from pathlib import Path

import numpy as np
import pytest
from canonical import UB_FIXTURES, fixture_id, fixtures
from pulseq_cpp_siemens.interpreter import CppSiemens, CppSiemensDecoding
from test_played import FIXTURES, RTOL, check_the_points_are_the_gradients, load_or_none
from test_seq_index import _seqfiles, check_the_index_of_a_snapshot_is_the_index_of_its_model
from test_snapshot import (
    COPIERS,
    GRE_FILE,
    RADIAL_FILES,
    check_a_copy_of_a_snapshot,
    check_load_applies_rotations_without_a_warning,
    check_load_does_not_warn_for_a_rotation_that_no_block_plays,
    check_load_of_a_file,
    check_load_warns_for_an_unapplied_rotation,
)

from pulseq_analysis._equality import values_equal
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.grad_peaks import gradient_peaks
from pulseq_analysis.seqfile import NotSupported, SeqFileError
from pulseq_analysis.synth import ScannerSettingWarning
from pulseq_analysis.synth._played import played_gradients
from pulseq_analysis.synth.sampling import gradient_sampler
from pulseq_analysis.synth.seq_index import has_gradients, sequence_index
from pulseq_analysis.synth.seq_utils import TIME_TOLERANCE

SEQFILES = Path(__file__).resolve().parents[3] / "tests" / "seqfiles"

# `cpp-siemens` by name, and as objects with each setting that changes the played gradients.
INTERPRETERS = [
    pytest.param("cpp-siemens", id="cpp-siemens"),
    pytest.param(CppSiemens(oversampling="edge", rotation="apply"), id="cpp-siemens-settings"),
]
SETTINGS = [
    pytest.param(CppSiemens(), id="cpp-siemens"),
    pytest.param(CppSiemens(oversampling="edge"), id="cpp-siemens-edge"),
    pytest.param(CppSiemens(oversampling="preserve"), id="cpp-siemens-preserve"),
    pytest.param(CppSiemens(rotation="apply"), id="cpp-siemens-apply"),
]
FIXTURE_IDS = {"ids": lambda p: str(p.relative_to(SEQFILES))}
# Two files in which gradient event 2 is alone on gx in block 0, and on gy after event 1 on gx in
# block 1. The shape of event 2 that the reader decompresses into the buffer of the block (the
# time shape of an extended trapezoid, the wave shape of an arbitrary gradient) is "0 0 -2", which
# writes none of its 4 samples, so in block 1 it keeps the values of the wave shape of event 1.
BUFFER_EXT_TRAP = UB_FIXTURES / "gradient_buffer_ext_trap.seq"
BUFFER_ARBITRARY = UB_FIXTURES / "gradient_buffer_arbitrary.seq"


# ---- The snapshot (`test_snapshot.py`) ----


@pytest.mark.parametrize("interpreter", INTERPRETERS)
def test_load_of_a_file_is_the_reading_of_cpp_siemens(interpreter):
    """`load(path, interpreter)` holds `read_seqfile(path, interpreter)`, with a
    `CppSiemensDecoding` (`check_load_of_a_file`)."""
    check_load_of_a_file(interpreter, "CppSiemensDecoding")


@pytest.mark.parametrize(
    "name", ["bad_gradient_nonzero_end_align.seq", "bad_raster_gradient_delay.seq"]
)
def test_load_through_cpp_siemens_gives_a_snapshot_of_a_file_that_spec_rejects(name):
    """A file that `spec` rejects (`gradient.nonzero-end-align`, `raster.gradient-delay`) gives a
    snapshot through `cpp-siemens`, which plays it as the C++ reader does."""
    with pytest.raises(SeqFileError):
        load(SEQFILES / name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        assert sequence_index(load(SEQFILES / name, "cpp-siemens")).num_blocks > 0


def test_load_raises_not_supported_for_a_version_outside_the_package_through_cpp_siemens():
    """A file of version 1.3 raises `NotSupported` from `load` through `cpp-siemens` (Q1)."""
    with pytest.raises(NotSupported):
        load(SEQFILES / "bad_version_unsupported_1_3.seq", "cpp-siemens")


def test_the_snapshot_records_cpp_siemens_with_its_settings():
    """`interpreter` is the `CppSiemens` object that `load` was given, and its `str` names the
    settings that are not the defaults."""
    setting = CppSiemens(oversampling="edge")
    snap = load(GRE_FILE, setting)
    assert snap.interpreter is setting
    assert str(snap.interpreter) == "cpp-siemens(oversampling='edge')"


@pytest.mark.parametrize("path", RADIAL_FILES, ids=lambda p: p.stem)
def test_load_warns_for_a_rotation_that_cpp_siemens_leaves_unapplied(path):
    """With `cpp-siemens`'s default (`rotation="reader"`, D6.2), `load` emits the warning of the
    rotation record once (`check_load_warns_for_an_unapplied_rotation`), and the warning tells
    the user to apply the rotations."""
    with pytest.warns(ScannerSettingWarning, match="rotation='apply'"):
        load(path, "cpp-siemens")
    assert check_load_warns_for_an_unapplied_rotation(path, "cpp-siemens").setting == "reader"


@pytest.mark.parametrize("path", RADIAL_FILES, ids=lambda p: p.stem)
def test_load_does_not_warn_when_cpp_siemens_applies_the_rotations(path):
    """With `CppSiemens(rotation="apply")` the decoding rotates every block that has a rotation,
    and `load` does not warn (`check_load_applies_rotations_without_a_warning`)."""
    check_load_applies_rotations_without_a_warning(path, CppSiemens(rotation="apply"))


def test_load_does_not_warn_for_a_rotation_that_no_block_plays_through_cpp_siemens():
    """A rotation that no block plays gives no warning with `cpp-siemens`'s default
    (`check_load_does_not_warn_for_a_rotation_that_no_block_plays`)."""
    check_load_does_not_warn_for_a_rotation_that_no_block_plays("cpp-siemens")


def test_the_rotation_of_cpp_siemens_changes_the_measured_gradients_only_where_it_is_applied():
    """On a radial file, `CppSiemens(rotation="apply")` and `spec` give the same peaks (both
    rotate, P20), which differ from those of `cpp-siemens`'s unrotated default."""
    path = RADIAL_FILES[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ScannerSettingWarning)
        reader = gradient_peaks(load(path, "cpp-siemens"))
    applied = gradient_peaks(load(path, CppSiemens(rotation="apply")))
    spec = gradient_peaks(load(path, "spec"))
    for axis in ("x", "y"):
        assert applied.axes[axis].peak_hz_per_m == pytest.approx(
            spec.axes[axis].peak_hz_per_m, rel=1e-6
        )
    assert not values_equal(applied.axes, reader.axes)


@pytest.mark.parametrize("copier", COPIERS)
def test_a_copy_of_a_cpp_siemens_snapshot_is_a_new_snapshot_with_no_kept_results(copier):
    """A copy of a `cpp-siemens` snapshot from `pickle` or `copy.deepcopy` is a new snapshot
    with no kept results, which decodes the data again (`check_a_copy_of_a_snapshot`)."""
    check_a_copy_of_a_snapshot(copier, "cpp-siemens")


# ---- The block table (`test_seq_index.py`) ----


def test_the_index_of_a_cpp_siemens_file_with_no_blocks_is_empty():
    """`cpp-siemens` reads a file with an empty `[BLOCKS]` section (`spec` rejects it,
    `blocks.empty`): its index has no block and no gradient."""
    index = sequence_index(load(SEQFILES / "bad_blocks_empty.seq", "cpp-siemens"))
    assert index.num_blocks == 0
    assert index.end_s == 0.0
    assert has_gradients(index) is False


def test_the_index_of_a_cpp_siemens_snapshot_is_the_index_of_its_model_for_each_file():
    """Through `cpp-siemens`, the index of a snapshot is that of its model
    (`check_the_index_of_a_snapshot_is_the_index_of_its_model`)."""
    check_the_index_of_a_snapshot_is_the_index_of_its_model("cpp-siemens")


def test_the_index_of_spec_and_of_cpp_siemens_are_equal_where_both_play_the_file_ids():
    """For each file that both interpreters read with no rotation or event after its block's
    end, the two indexes are equal: both keep the block and event IDs of the file (the fixtures
    with IDs that are not unique are rejected by `spec`, `id.unique`)."""
    compared = 0
    for path in _seqfiles():
        try:
            spec = load(path, "spec")
            cpp = load(path, CppSiemens())
        except (SeqFileError, NotSupported):
            continue
        if spec.rotation_record.blocks or cpp.rotation_record.blocks:
            continue
        assert sequence_index(spec) == sequence_index(cpp), path.name
        compared += 1
    assert compared >= 10


# ---- The played gradients (`test_played.py`) ----


@pytest.mark.parametrize("interpreter", SETTINGS)
@pytest.mark.parametrize("path", FIXTURES, **FIXTURE_IDS)
def test_the_points_of_the_played_events_are_the_gradients_of_cpp_siemens(path, interpreter):
    """On each fixture that `cpp-siemens` reads, in each setting, the points of the played
    events are the reader's `gradientsAt` (`check_the_points_are_the_gradients`): for the
    decoded events, for a block that the decoding rotates (`rotation="apply"`), and for a block
    whose event the reader plays after the end of the block (`oversampling="preserve"`
    stretches an oversampled gradient, D6.1)."""
    check_the_points_are_the_gradients(path, interpreter)


def test_a_rotated_block_has_an_event_on_each_axis_from_gradients_at():
    """In a radial file read with `CppSiemens(rotation="apply")`, each block with a rotation that
    is not the identity and a gradient has an event on each axis, with a key above the largest
    file ID; the other blocks keep the file IDs of their events."""
    path = SEQFILES / "oracle" / "pulseq_make_radial.seq"
    snap = load(path, CppSiemens(rotation="apply"))
    played = played_gradients(snap)
    indices, quaternions = snap.decoding.rotations()
    turned = indices[np.any(quaternions[:, 1:] != 0, axis=1)]
    blocks = snap.data.blocks
    has_gradient = (blocks["gx"] != 0) | (blocks["gy"] != 0) | (blocks["gz"] != 0)
    turned = turned[has_gradient[turned]]
    assert turned.size > 0
    top = max(int(blocks[axis].max()) for axis in ("gx", "gy", "gz"))
    for column in (played.gx, played.gy, played.gz):
        assert np.all(column[turned] > top)
    others = np.setdiff1d(np.arange(blocks.size), turned)
    for axis, column in zip(("gx", "gy", "gz"), (played.gx, played.gy, played.gz), strict=True):
        assert np.array_equal(column[others], blocks[axis][others])


def test_an_event_that_cpp_siemens_plays_after_the_end_of_its_block_ends_at_the_block_end():
    """With `oversampling="preserve"`, `cpp-siemens` stretches the oversampled gradient of the
    spiral beyond its block (D6.1); `gradientsAt` is 0 after the end of a block (D7.4), so the
    played event of that block ends at the block's end, and every other block keeps its
    decoded event."""
    path = SEQFILES / "oracle" / "koma_v1.5_spiral.seq"
    snap = load(path, CppSiemens(oversampling="preserve"))
    played = played_gradients(snap)
    duration = snap.data.block_durations_s
    top = max(int(snap.data.blocks[axis].max()) for axis in ("gx", "gy", "gz"))
    clipped = 0
    for column in (played.gx, played.gy, played.gz):
        for block in np.flatnonzero(column):
            delay, offsets, _ = played.points[int(column[block])]
            assert delay + offsets[-1] <= duration[block] + 1e-12
            clipped += int(column[block]) > top
    assert clipped > 0


def _reader_probes(snap, axis: int):
    """For the axis `axis` (0, 1, 2) of `snap`: the block, the time (s from the block start) and
    the value of the sampler at each probe, which are the middle of each segment of the played
    points of each block, and a quarter, a half and three quarters of each block of positive
    duration. A probe within `TIME_TOLERANCE` of a step of the played points (two points at one
    time with two values, or an end of an event at a value that is not 0), or of a gap where the
    sampler draws a line between two events (`sampling`, the module docstring), is left out."""
    played = played_gradients(snap)
    column = (played.gx, played.gy, played.gz)[axis]
    name = ("gx", "gy", "gz")[axis]
    duration = snap.decoding.block_durations
    start = sequence_index(snap).start_s
    sampler = gradient_sampler(snap)
    blocks, times, steps = [], [], []
    for block in range(duration.size):
        key = int(column[block])
        if key:
            delay, offsets, amp = played.points[key]
            t = delay + offsets
            for i in range(t.size - 1):
                if t[i + 1] > t[i]:
                    blocks.append(block)
                    times.append((t[i] + t[i + 1]) / 2)
                elif amp[i + 1] != amp[i]:
                    steps.append(start[block] + t[i])
            if amp[0] != 0:
                steps.append(start[block] + t[0])
            if amp[-1] != 0:
                steps.append(start[block] + t[-1])
        if duration[block] > 0:
            blocks += [block] * 3
            times += [f * float(duration[block]) for f in (0.25, 0.5, 0.75)]
    blocks, times = np.array(blocks, dtype=np.int64), np.array(times)
    at = start[blocks] + times
    keep = np.ones(at.size, dtype=bool)
    for step in steps:
        keep &= np.abs(at - step) > TIME_TOLERANCE
    gaps = sampler._gaps(name)
    for gap_start, gap_end in zip(gaps.start_s, gaps.end_s, strict=True):
        keep &= (at < gap_start - TIME_TOLERANCE) | (at > gap_end + TIME_TOLERANCE)
    blocks, times, at = blocks[keep], times[keep], at[keep]
    order = np.argsort(at, kind="stable")
    values = np.empty(at.size)
    values[order] = sampler.sample(name, at[order])
    return blocks, times, values


@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_waveform_of_the_measurements_is_the_gradients_of_the_reader(path):
    """On each fixture that `cpp-siemens` reads (the files of `tests/seqfiles` and the plugin's
    own), the sampler of the measurements (`gradient_sampler`) gives the reader's own
    `gradientsAt` (`Sequence.gradients_at`) at the probes of `_reader_probes`, on each axis, to
    `RTOL` of the largest value of the axis (a NaN of the file is NaN in both)."""
    snap = load_or_none(path, "cpp-siemens")
    if snap is None:
        pytest.skip("cpp-siemens rejects the file")
    for axis in range(3):
        blocks, times, values = _reader_probes(snap, axis)
        if blocks.size == 0:
            continue
        reader = snap.data.reading.gradients_at(blocks, times * 1e6)[:, axis]
        assert np.array_equal(np.isnan(values), np.isnan(reader)), axis
        finite = ~np.isnan(reader)
        scale = max(float(np.abs(reader[finite]).max(initial=0.0)), 1.0)
        bad = np.abs(values[finite] - reader[finite]) > RTOL * scale
        assert not bad.any(), (axis, blocks[finite][bad], times[finite][bad] * 1e6)


def test_the_measurements_of_an_event_that_keeps_the_buffer_of_its_block_are_the_reader_s():
    """In block 1 of `gradient_buffer_ext_trap.seq` the reader plays event 2 on gy with the
    times 10, 20, 30 and 40 us, which its time shape keeps from the wave shape of event 1: 250,
    750, 1000, 750 and 0 Hz/m at 5, 15, 25, 35 and 45 us. The sampler gives these values, and
    `gradient_peaks` a peak of 1000 Hz/m on y. In `gradient_buffer_arbitrary.seq` the reader plays
    1000 Hz/m on gy in block 1, and the peak on y is 1000 Hz/m."""
    snap = load(BUFFER_EXT_TRAP, "cpp-siemens")
    time_us = np.array([5.0, 15.0, 25.0, 35.0, 45.0])
    expected = [250.0, 750.0, 1000.0, 750.0, 0.0]
    reader = snap.data.reading.gradients_at(np.ones(time_us.size, dtype=np.int64), time_us)
    np.testing.assert_allclose(reader[:, 1], expected, rtol=0, atol=RTOL * 1000)
    at = sequence_index(snap).start_s[1] + time_us * 1e-6
    sampled = gradient_sampler(snap).sample("gy", at)
    np.testing.assert_allclose(sampled, expected, rtol=0, atol=RTOL * 1000)
    assert gradient_peaks(snap).axes["y"].peak_hz_per_m == pytest.approx(1000.0, rel=RTOL)
    arbitrary = load(BUFFER_ARBITRARY, "cpp-siemens")
    assert gradient_peaks(arbitrary).axes["y"].peak_hz_per_m == pytest.approx(1000.0, rel=RTOL)


@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_cells_of_one_event_and_one_variant_decode_alike(path):
    """`CppSiemensDecoding.gradient_variants()` is the rule of `_played` for a plugin: each two
    cells (a block and an axis) with the same gradient event and the same variant decode alike
    (`gradient_points`, bit for bit), and with None every cell of an event does. Otherwise it is an
    int64 array (blocks, 3), read-only, with 0 at each cell with no event. It is None on each file
    of `tests/seqfiles` that `spec` reads, and gives event 2 two variants in each of the two files
    of the buffer of a block."""
    snap = load_or_none(path, "cpp-siemens")
    if snap is None:
        pytest.skip("cpp-siemens rejects the file")
    variants = snap.decoding.gradient_variants()
    blocks = snap.data.blocks
    columns = np.stack([np.asarray(blocks[c], dtype=np.int64) for c in ("gx", "gy", "gz")], axis=1)
    if variants is None:
        cells = np.zeros(columns.shape, dtype=np.int64)
    else:
        assert variants.dtype == np.int64 and variants.shape == columns.shape
        assert not variants.flags.writeable
        assert np.all(variants[columns == 0] == 0)
        cells = variants
    first: dict[tuple[int, int], object] = {}
    for block, axis in np.argwhere(columns != 0).tolist():
        cell = (int(columns[block, axis]), int(cells[block, axis]))
        points = snap.decoding.gradient_points(cell[0], block, axis)
        if cell not in first:
            first[cell] = points
            continue
        delay, offsets, amp = first[cell]
        assert points[0] == delay
        assert np.array_equal(points[1], offsets)
        assert np.array_equal(points[2], amp)
    if path.is_relative_to(SEQFILES) and load_or_none(path, "spec") is not None:
        assert variants is None
    if path in (BUFFER_EXT_TRAP, BUFFER_ARBITRARY):
        assert variants is not None
        assert np.unique(variants[columns == 2]).size == 2


def test_cpp_siemens_decodes_one_block_for_each_unique_gradient_event(monkeypatch):
    """`played_gradients` decodes one block for each unique gradient event of a `cpp-siemens`
    file (the first block that plays it), and is kept: a second call decodes nothing."""
    snap = load(SEQFILES / "oracle" / "pulseq_epi_rs.seq", "cpp-siemens")
    calls = []
    original = CppSiemensDecoding.block

    def counted(self, index):
        calls.append(index)
        return original(self, index)

    monkeypatch.setattr(CppSiemensDecoding, "block", counted)
    played = played_gradients(snap)
    blocks = snap.data.blocks
    unique = np.unique(np.concatenate([blocks[axis] for axis in ("gx", "gy", "gz")]))
    assert len(calls) == np.count_nonzero(unique)
    assert played_gradients(snap) is played
    assert len(calls) == np.count_nonzero(unique)
