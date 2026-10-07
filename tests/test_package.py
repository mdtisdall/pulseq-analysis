import importlib
import importlib.metadata
import inspect
import pkgutil
import tomllib
from pathlib import Path

import pulseq_analysis

ROOT = Path(__file__).resolve().parent.parent


def test_the_package_imports_and_has_the_version_of_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert Path(pulseq_analysis.__file__).resolve().parent == ROOT / "src" / "pulseq_analysis"
    assert importlib.metadata.version("pulseq-analysis") == pyproject["project"]["version"]


def _defined_callables(module):
    """Yield (name, function) for each function of the module and each function in the
    classes of the module, private ones too. Only objects that the package defines."""
    for name, obj in vars(module).items():
        if getattr(obj, "__module__", "").startswith("pulseq_analysis"):
            if inspect.isfunction(obj):
                yield name, obj
            elif inspect.isclass(obj):
                for member_name, member in vars(obj).items():
                    member = getattr(member, "__func__", member)
                    if inspect.isfunction(member):
                        yield f"{name}.{member_name}", member


def test_the_package_has_no_gamma():
    """The package has no gamma: each value is in the units of pypulseq and the caller
    divides by |gamma| (docs/usage.md section 9)."""
    for info in pkgutil.iter_modules(pulseq_analysis.__path__):
        module = importlib.import_module(f"pulseq_analysis.{info.name}")
        for attribute in dir(module):
            assert "gamma" not in attribute.lower(), f"{info.name} has the attribute {attribute}"
        for name, function in _defined_callables(module):
            for parameter in inspect.signature(function).parameters:
                assert "gamma" not in parameter.lower(), (
                    f"{info.name}.{name} has the parameter {parameter}"
                )
