"""The package on each fixture against tests/expected_digests.json, which scripts/make_digests.py
made from the driver's output: the same verdict, and for a file that it reads the same `--dump`
and `--sample`, bit for bit. This is the test of a wheel on a platform without the driver."""

import json

import pytest
from canonical import (
    DIGESTS,
    canonical_dump,
    digest,
    fixture_id,
    fixtures,
    read,
    sample_points,
    wrapper_dump,
)

EXPECTED = json.loads(DIGESTS.read_text())


def test_each_fixture_has_a_digest():
    assert sorted(EXPECTED) == sorted(fixture_id(path) for path in fixtures())


@pytest.mark.parametrize("path", fixtures(), ids=fixture_id)
def test_the_package_matches_the_digest_of_the_driver(path):
    expected = EXPECTED[fixture_id(path)]
    verdict, sequence, blocks = read(path)
    assert verdict == expected["verdict"]
    if verdict != "read":
        return
    dump = wrapper_dump(sequence, blocks)
    block_index, time_us = sample_points(canonical_dump(dump))
    assert digest(dump, sequence.gradients_at(block_index, time_us)) == expected["sha256"]
