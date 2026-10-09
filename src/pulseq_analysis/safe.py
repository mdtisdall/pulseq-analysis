# The hardware check and the chunked filter of this module are ported from pypulseq's
# `pypulseq/utils/safe_pns_prediction.py` (`safe_hw_check` and `_safe_gwf_to_pns_chunk`, as
# in the pypulseq fork at commit 3c3bd85). That file says that it is "a direct Python
# translation of the relevant functions in
# https://github.com/filip-szczepankiewicz/safe_pns_prediction/". The notices of both
# licenses follow.
#
#
# BSD 3-Clause License (safe_pns_prediction)
#
# Copyright (c) 2018, Filip Szczepankiewicz and Thomas Witzel
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
#
# MIT License (pypulseq)
#
# Copyright (c) 2019-2025 PyPulseq Contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""The hardware of the SAFE PNS model (`SafeAxis`, `SafeHardware`) and the SAFE filter that
`pns_levels` runs over the gradient samples in chunks.

A `SafeHardware` is the nine parameters of each gradient axis (`SAFE_FIELDS`) and a name. It
is immutable and checked when it is made, so a function that takes one needs no further check:
every field is a finite real number, `stim_limit` is above 0, and `a1 + a2 + a3` of each axis
is within 0.001 of 1. `asc.safe_hardware` makes one from a Siemens gradient `.asc` file, and
`SafeHardware.from_namespace` from a `types.SimpleNamespace` in the form of pypulseq's
`asc_to_hw` and `safe_example_hw`. This module does not import pypulseq.

The units of the fields are those of `safe_example_hw` of pypulseq: `tau1`, `tau2` and `tau3`
in ms, `stim_limit` and `stim_thresh` in T/m/s, and `a1`, `a2`, `a3` and `g_scale` without a
unit.
"""

from dataclasses import dataclass

import numpy as np
from scipy.signal import lfilter

from ._validate import real

# The nine fields of each axis of a SAFE hardware, in the order of `safe_example_hw` and
# `asc_to_hw` of pypulseq.
SAFE_FIELDS = ("tau1", "tau2", "tau3", "a1", "a2", "a3", "stim_limit", "stim_thresh", "g_scale")
# The largest distance of `a1 + a2 + a3` from 1 for an axis (the rule of pypulseq's
# `safe_hw_check`).
_A_SUM_TOLERANCE = 0.001
_AXES = ("x", "y", "z")


def _checked_field(prefix: str, axis: str, field: str, value: object) -> float:
    """`value` of `field` of the axis named `axis` as a `float`. The name in an error is
    `prefix + axis.field`. See `SafeAxis` for the rules."""
    return real(f"{prefix}{axis}.{field}", value, positive=field == "stim_limit")


def _check_a_sum(prefix: str, axis: str, values: dict[str, float]) -> None:
    """Raise `ValueError` when `a1 + a2 + a3` of `values` is more than `_A_SUM_TOLERANCE`
    from 1."""
    total = values["a1"] + values["a2"] + values["a3"]
    if abs(total - 1) > _A_SUM_TOLERANCE:
        raise ValueError(
            f"{prefix}{axis}.a1 + {axis}.a2 + {axis}.a3 must be 1 (within "
            f"{_A_SUM_TOLERANCE}), not {total!r}"
        )


@dataclass(frozen=True)
class SafeAxis:
    """The SAFE parameters of one gradient axis: `tau1`, `tau2`, `tau3` (ms), `a1`, `a2`, `a3`,
    `stim_limit` (T/m/s), `stim_thresh` (T/m/s) and `g_scale`. Each is stored as a `float`.
    Construction raises `TypeError` for a field that is a `bool` or not a real number, and
    `ValueError` for a field that is not finite, a `stim_limit` that is not above 0, and an
    `a1 + a2 + a3` that is more than 0.001 from 1 (`_validate.real`)."""

    tau1: float
    tau2: float
    tau3: float
    a1: float
    a2: float
    a3: float
    stim_limit: float
    stim_thresh: float
    g_scale: float

    def __post_init__(self) -> None:
        values = {
            field: _checked_field("", "SafeAxis", field, getattr(self, field))
            for field in SAFE_FIELDS
        }
        _check_a_sum("", "SafeAxis", values)
        for field, value in values.items():
            object.__setattr__(self, field, value)


@dataclass(frozen=True)
class SafeHardware:
    """The SAFE hardware: `name` (a `str`) and the `SafeAxis` of `x`, `y` and `z`. The same
    attributes as the `types.SimpleNamespace` of pypulseq's `asc_to_hw`, so a function that
    reads `hardware.x.tau1` takes either. Construction raises `TypeError` when `name` is not
    a `str` or an axis is not a `SafeAxis`."""

    name: str
    x: SafeAxis
    y: SafeAxis
    z: SafeAxis

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(f"SafeHardware.name must be a str, not {self.name!r}")
        for axis in _AXES:
            if not isinstance(getattr(self, axis), SafeAxis):
                raise TypeError(
                    f"SafeHardware.{axis} must be a SafeAxis, not {getattr(self, axis)!r}"
                )

    @classmethod
    def from_namespace(cls, ns: object, name: str | None = None) -> "SafeHardware":
        """The `SafeHardware` of `ns`, an object with `.x`, `.y` and `.z`, each with the
        fields of `SAFE_FIELDS` (the `SimpleNamespace` of pypulseq's `asc_to_hw` or
        `safe_example_hw()`). `name` is the name of the result; without it, it is `ns.name`,
        or "unknown" when `ns` has none. An extra field of `ns` is ignored.

        Raises `ValueError` when `ns` has no `x`, `y` or `z`, or an axis has no field of
        `SAFE_FIELDS` (the message names it, for example "'x.stim_thresh' missing in the
        hardware struct"), and the errors of `SafeAxis` for a field that is not valid, with
        the name of the axis in the message."""
        axes = {}
        for axis in _AXES:
            axis_ns = getattr(ns, axis, None)
            if axis_ns is None:
                raise ValueError(f"'{axis}' missing in the hardware struct")
            values = {}
            for field in SAFE_FIELDS:
                if not hasattr(axis_ns, field):
                    raise ValueError(f"'{axis}.{field}' missing in the hardware struct")
                values[field] = _checked_field("hardware ", axis, field, getattr(axis_ns, field))
            _check_a_sum("hardware ", axis, values)
            axes[axis] = SafeAxis(**values)
        if name is None:
            name = getattr(ns, "name", "unknown")
        return cls(name, **axes)


@dataclass(frozen=True)
class _SafeState:
    """The state that `_safe_gwf_to_pns_chunk` carries from one chunk to the next: `g_last`
    (shape `(3,)`), the last gradient sample of each axis, and `zi` (shape `(3, 3)`), the
    `lfilter` state, indexed `[axis, filter]` with the filters in the order `tau1`, `tau2`,
    `tau3`. The arrays are not changed after they are made."""

    g_last: np.ndarray
    zi: np.ndarray


def _safe_gwf_to_pns_chunk(
    gwf: np.ndarray, dt: float, hw: SafeHardware, state: _SafeState | None = None
) -> tuple[np.ndarray, _SafeState]:
    """The SAFE model over one chunk of a waveform. `gwf` is `(n, 3)`, the samples of x, y and
    z on the raster `dt` (seconds), with no padding. `hw` is a `SafeHardware`. `state` is
    `None` for the first chunk (the sample before it and the filters are 0), and the state
    that the call for the previous chunk returned for the next.

    Returns `(pns, state)`: `pns` is `(n, 3)` and `state` is for the next chunk. For `gwf` in
    T/m, `pns` is in percent of the stimulation limit (as pypulseq's function of the same
    name gives it); it is linear in `gwf`. The chunks of one waveform, in order, give the
    same rows as one chunk of the whole waveform: the first row of a chunk is the difference
    from the last sample of the chunk before.

    Each axis has three first-order low-pass filters of the slew, with `alpha = dt_ms /
    (tau + dt_ms)` and `dt_ms = dt * 1000`: of the slew with `tau1`, of its absolute value
    with `tau2`, and of the slew with `tau3`. The value of a sample is
    `(a1 * abs(lp1) + a2 * lp2 + a3 * abs(lp3)) / stim_limit * g_scale * 100`."""
    if state is None:
        g_last = np.zeros(3)
        zi = np.zeros((3, 3))
    else:
        g_last = state.g_last
        zi = state.zi

    dgdt = np.diff(np.vstack([g_last, gwf]), axis=0) / dt

    dt_ms = dt * 1000
    pns = np.zeros((gwf.shape[0], 3))
    zi_new = np.zeros((3, 3))

    for ax_idx, axn in enumerate(_AXES):
        hw_ax = getattr(hw, axn)
        dgdt_ax = dgdt[:, ax_idx]

        alpha1 = dt_ms / (hw_ax.tau1 + dt_ms)
        lp1, zi1 = lfilter([alpha1], [1.0, alpha1 - 1.0], dgdt_ax, zi=zi[ax_idx, 0:1])
        stim1 = hw_ax.a1 * abs(lp1)

        alpha2 = dt_ms / (hw_ax.tau2 + dt_ms)
        lp2, zi2 = lfilter([alpha2], [1.0, alpha2 - 1.0], abs(dgdt_ax), zi=zi[ax_idx, 1:2])
        stim2 = hw_ax.a2 * lp2

        alpha3 = dt_ms / (hw_ax.tau3 + dt_ms)
        lp3, zi3 = lfilter([alpha3], [1.0, alpha3 - 1.0], dgdt_ax, zi=zi[ax_idx, 2:3])
        stim3 = hw_ax.a3 * abs(lp3)

        pns[:, ax_idx] = (stim1 + stim2 + stim3) / hw_ax.stim_limit * hw_ax.g_scale * 100

        zi_new[ax_idx, 0] = zi1[0]
        zi_new[ax_idx, 1] = zi2[0]
        zi_new[ax_idx, 2] = zi3[0]

    return pns, _SafeState(g_last=gwf[-1, :].copy(), zi=zi_new)
