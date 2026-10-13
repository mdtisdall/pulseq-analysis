"""pypulseq for the test helpers and the test modules that have tests with and without it.

`pp` is pypulseq when it is installed. Without it (the run of `scripts/check` without pypulseq),
`pp` is a stand-in: an attribute of it is another stand-in, so a module that names `pp.Sequence`
in an annotation or builds a constant from `pp.Opts` lazily still imports, and a call of it
raises `ImportError`. A test that calls pypulseq, directly or through a builder of
`synthetic.py`, must have the `pypulseq` marker: `-m "not pypulseq"` leaves it out, and without
the marker it fails with this error. A module whose tests all need pypulseq starts with
`pytestmark = pytest.mark.pypulseq` and `pytest.importorskip("pypulseq")` instead.
"""

from typing import Any


class Missing:
    """A stand-in for a part of pypulseq that is not installed: `name` is its dotted name."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> "Missing":
        if attr.startswith("__"):
            raise AttributeError(attr)
        return Missing(f"{self._name}.{attr}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise ImportError(
            f"{self._name} needs pypulseq, which is not installed: "
            "a test that uses it needs the `pypulseq` marker"
        )

    def __repr__(self) -> str:
        return f"<{self._name}: pypulseq is not installed>"


try:
    import pypulseq as pp
except ImportError:
    pp = Missing("pypulseq")
    HAVE_PYPULSEQ = False
else:
    HAVE_PYPULSEQ = True
