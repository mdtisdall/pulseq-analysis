"""The package works without pypulseq: in a new interpreter where `import pypulseq` fails
(`sys.modules["pypulseq"] = None`), `load(path)` and each analysis of the registry
(`compute`, then `to_series`) run on each oracle file that `spec` reads, and `read_pypulseq`
refuses an object that is not a pypulseq sequence with its `TypeError`. `read_pypulseq` needs
pypulseq only through its argument: without pypulseq, a caller has no sequence to give it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pulseq_analysis.analyses import load
from pulseq_analysis.seqfile import NotSupported, SeqFileError

TESTS = Path(__file__).resolve().parent
ORACLE = TESTS / "seqfiles" / "oracle"

_CODE = """
import json, sys
sys.modules["pypulseq"] = None
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from pns_hardware import EXAMPLE_HARDWARE
from pulseq_analysis.analyses import load
from pulseq_analysis.analyses.registry import registry
from pulseq_analysis.seqfile import NotSupported, SeqFileError, read_pypulseq

try:
    import pypulseq
except ImportError:
    pass
else:
    raise AssertionError("pypulseq imports")

hardware = (EXAMPLE_HARDWARE, "pypulseq example hardware (not a real scanner)")
analyses = registry()
loaded, ran = [], []
for path in sorted(Path(sys.argv[2]).glob("*.seq")):
    try:
        snap = load(path)
    except (SeqFileError, NotSupported):
        continue
    loaded.append(path.name)
    for analysis_id, analysis in analyses.items():
        params = {"hardware": hardware} if "hardware" in analysis.spec.necessary else {}
        analysis.to_series(analysis.compute(snap, **params))
        ran.append(f"{path.name}:{analysis_id}")

try:
    read_pypulseq(object())
except TypeError as error:
    refused = str(error)
else:
    raise AssertionError("read_pypulseq took an object")

print(json.dumps({"loaded": loaded, "ran": ran, "analyses": sorted(analyses), "refused": refused}))
"""


@pytest.fixture(scope="module")
def without_pypulseq() -> dict:
    """What the interpreter without pypulseq loaded and ran (the output of `_CODE`)."""
    result = subprocess.run(
        [sys.executable, "-c", _CODE, str(TESTS), str(ORACLE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_load_reads_the_oracle_files_that_it_reads_with_pypulseq(without_pypulseq):
    """The files that load without pypulseq are those that load in this interpreter, and
    there are some."""
    here = []
    for path in sorted(ORACLE.glob("*.seq")):
        try:
            load(path)
        except (SeqFileError, NotSupported):
            continue
        here.append(path.name)
    assert here
    assert without_pypulseq["loaded"] == here


def test_each_analysis_of_the_registry_runs_on_each_oracle_file(without_pypulseq):
    """`compute` and `to_series` of each analysis ran for each file that loaded."""
    analyses = without_pypulseq["analyses"]
    assert "pns.safe.levels" in analyses
    assert without_pypulseq["ran"] == [
        f"{name}:{analysis_id}" for name in without_pypulseq["loaded"] for analysis_id in analyses
    ]


def test_read_pypulseq_refuses_an_object_that_is_not_a_sequence(without_pypulseq):
    assert "read_pypulseq takes a pypulseq.Sequence" in without_pypulseq["refused"]
