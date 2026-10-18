"""The analyses layer: the measurements of a sequence, their registry, and SAFE PNS with its
hardware files. It imports from the layers below it and the base modules.

`load(path or sequence, interpreter="spec")` reads a file or a pypulseq sequence through an
interpreter into the `synth.snapshot.Snapshot` that each measurement takes (`loading`), and
`load(data, interpreter)` takes the `SequenceData` of such a reading."""

from .loading import load

__all__ = ["load"]
