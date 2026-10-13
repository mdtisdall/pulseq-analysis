"""Each case of undefined behaviour of section 5.3 of the plan is rejected by `load`, before
`GetBlock` and `decodeBlock` run, with its code, and the process goes on: after all of them, a
valid file still reads as before. The sanitized C++ oracle confirms each fixture
(test_driver_parity.py, and tests/test_cpp_oracle_sanitized.py of pulseq-analysis)."""

import numpy as np
import pulseq_cpp_siemens as cs
import pytest
from canonical import REPO, SEQFILES, UB_FIXTURES, canonical_dump, wrapper_dump

CASES = {
    # D05: [VERSION] last; the reader then reads no shape, so the RF event's shape is missing.
    SEQFILES / "undefined" / "version_last.seq": "ub.shape-missing",
    SEQFILES / "bad_ref_shape.seq": "ub.shape-missing",  # D21
    SEQFILES / "bad_ref_time_shape.seq": "ub.shape-missing",  # D21
    SEQFILES / "bad_syntax_shape_no_blank_line.seq": "ub.shape-missing",  # D07, then D21
    SEQFILES / "undefined" / "rf_time_id_minus_1.seq": "ub.rf-time-id-minus-1",  # D22
    SEQFILES / "bad_ref_extension_cycle.seq": "ub.extension-cycle",  # D23
    SEQFILES / "undefined" / "shape_decompress_longer.seq": "ub.shape-decompression",  # D29
    UB_FIXTURES / "shape_decompress_count_missing.seq": "ub.shape-decompression",  # D29
    SEQFILES / "bad_shape_empty.seq": "ub.shape-empty",  # D33
    SEQFILES / "bad_shape_event_length.seq": "ub.rf-shape-lengths",  # D34
    SEQFILES / "bad_shape_rf_time_end.seq": "ub.rf-time-overrun",  # D36 (2)
    # D59: gradientsAt of an extended trapezoid of one point reads past its times.
    UB_FIXTURES / "gradient_one_point.seq": "ub.gradient-one-point",
    # D21: a [GRADIENTS] row of shape 0: a trapezoid whose ramp and flat times load never sets.
    UB_FIXTURES / "gradient_shape_0.seq": "ub.gradient-shape-0",
}


def ids(path):
    return path.relative_to(REPO).as_posix()


@pytest.mark.parametrize(("path", "code"), CASES.items(), ids=[ids(p) for p in CASES])
def test_a_case_of_undefined_behaviour_is_rejected_with_its_code(path, code):
    with pytest.raises(cs.UndefinedBehaviour) as error:
        cs.load(path)
    assert error.value.code == code
    assert error.value.entry == cs.CODES[code]


def test_the_process_reads_a_valid_file_after_every_case():
    path = SEQFILES / "valid_1_5_1.seq"
    before = canonical_dump(wrapper_dump(cs.load(path)))
    for case in CASES:
        with pytest.raises(cs.UndefinedBehaviour):
            cs.load(case)
    assert canonical_dump(wrapper_dump(cs.load(path))) == before


def test_the_extension_refuses_to_decode_a_file_that_is_not_checked():
    reader = cs._reader.Reader()
    assert reader.load((SEQFILES / "valid_1_5_1.seq").read_bytes())
    with pytest.raises(RuntimeError, match="not checked"):
        reader.decode_block(0)
    with pytest.raises(RuntimeError, match="not checked"):
        reader.ensure_decoded(np.zeros(1, dtype=np.int64))
