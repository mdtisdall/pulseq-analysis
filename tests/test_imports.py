"""The package imports without pypulseq and matplotlib: a new interpreter imports
`pulseq_analysis` and each of its modules (`pkgutil.walk_packages`), and then neither is in
`sys.modules`. pypulseq is an optional dependency (`[project.optional-dependencies]`), and the
package draws nothing."""

import subprocess
import sys

_CODE = """
import importlib, pkgutil, sys
import pulseq_analysis
names = [m.name for m in pkgutil.walk_packages(pulseq_analysis.__path__, "pulseq_analysis.")]
for name in names:
    importlib.import_module(name)
bad = sorted(m for m in sys.modules if m.split(".")[0] in ("pypulseq", "matplotlib"))
assert not bad, bad
print(len(names))
"""


def test_the_package_and_each_module_import_neither_pypulseq_nor_matplotlib():
    result = subprocess.run(
        [sys.executable, "-c", _CODE], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    # The package has subpackages (analyses, seqfile, synth) and their modules.
    assert int(result.stdout) > 10
