"""Write tests/expected_digests.json: for each fixture, the verdict of the package and, for a file
that it reads, the SHA-256 of the canonical form of the driver's `--dump` and `--sample`
(tests/canonical.py) in each sampling mode of oversampled gradients (`--oversampling`). The
wheels' tests compare against it on the platforms without the driver.

Run it in the Nix devShell (its `pulseq-cpp-oracle` has the package's build flags) with the
package installed, from the repository root:

    nix develop --command packages/pulseq-cpp-siemens/.venv/bin/python \
        packages/pulseq-cpp-siemens/scripts/make_digests.py

It stops when the package and the driver differ.
"""

import json
import sys
from pathlib import Path

import pulseq_cpp_siemens as cs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from canonical import (
    DIGESTS,
    canonical_dump,
    digest,
    driver,
    driver_samples,
    fixture_id,
    fixtures,
    parse_driver_dump,
    read,
    run_driver,
    sample_points,
    wrapper_dump,
)


def main() -> None:
    if driver() is None:
        sys.exit("no driver: run in the Nix devShell, or set PULSEQ_CPP_ORACLE")
    expected = {}
    for path in fixtures():
        name = fixture_id(path)
        readings = {mode: read(path, mode) for mode in cs.OVERSAMPLING}
        verdicts = {reading[0] for reading in readings.values()}
        if len(verdicts) > 1:
            sys.exit(f"{name}: the package's verdict depends on the sampling mode: {verdicts}")
        verdict = verdicts.pop()
        if verdict != "read":
            expected[name] = {"verdict": verdict}
            continue
        digests = {}
        for oversampling, (_, sequence, blocks) in readings.items():
            driver_verdict, out = run_driver("--dump", path, oversampling=oversampling)
            if driver_verdict != "ok":
                sys.exit(f"{name}: the driver says {driver_verdict}, the package reads it")
            dump = parse_driver_dump(out)
            block_index, time_us = sample_points(canonical_dump(dump))
            theirs = digest(dump, driver_samples(path, block_index, time_us, oversampling))
            ours = digest(
                wrapper_dump(sequence, blocks), sequence.gradients_at(block_index, time_us)
            )
            if theirs != ours:
                sys.exit(
                    f"{name}: the package and the driver differ in the mode {oversampling} "
                    "(tests/test_driver_parity.py)"
                )
            digests[oversampling] = theirs
        expected[name] = {"verdict": "read", "sha256": digests}
        print(name, *(f"{mode} {value[:8]}" for mode, value in digests.items()))
    DIGESTS.write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
