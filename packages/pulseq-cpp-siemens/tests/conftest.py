"""The tests of the `cpp-siemens` interpreter (`pulseq_cpp_siemens.interpreter`, the plugin of
pulseq-analysis) need pulseq-analysis (the dependency group `analysis`). Without it, as in the
wheel tests of cibuildwheel, their modules (`ANALYSIS_TESTS`) are not collected. With it, the
tests directory of pulseq-analysis (the root of this repository) is put on `sys.path`, for its
fixtures and its helpers (`test_cpp_oracle`, `test_from_pypulseq`, `synthetic`, the MATLAB
oracle, and the measurement tests that `test_measurements_in_pulseq_analysis` calls).
"""

import importlib.util
import sys
from pathlib import Path

ANALYSIS_TESTS = [
    "test_interpreter.py",
    "test_interpreter_in_pulseq_analysis.py",
    "test_load_in_pulseq_analysis.py",
    "test_measurements_in_pulseq_analysis.py",
    "test_session_in_pulseq_analysis.py",
]

ROOT_TESTS = Path(__file__).resolve().parents[3] / "tests"

if importlib.util.find_spec("pulseq_analysis") is None:
    collect_ignore = ANALYSIS_TESTS
elif str(ROOT_TESTS) not in sys.path:
    sys.path.append(str(ROOT_TESTS))
