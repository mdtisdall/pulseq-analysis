import importlib.metadata
import tomllib
from pathlib import Path

import pulseq_analysis

ROOT = Path(__file__).resolve().parent.parent


def test_the_package_imports_and_has_the_version_of_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert Path(pulseq_analysis.__file__).resolve().parent == ROOT / "src" / "pulseq_analysis"
    assert importlib.metadata.version("pulseq-analysis") == pyproject["project"]["version"]
