import pytest
from pypulseq.utils.safe_pns_prediction import safe_example_hw


def pytest_addoption(parser):
    """Add `--collected-tests-file`, so the TESTS.md check can read this run's test
    IDs instead of collecting the test files a second time in `scripts/check`."""
    parser.addoption(
        "--collected-tests-file",
        action="store",
        default=None,
        help="write the node ID of each collected test, one per line, to this path",
    )


def pytest_collection_finish(session):
    """Write the collected node IDs to `--collected-tests-file`, if it was given."""
    path = session.config.getoption("--collected-tests-file")
    if path is None:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(f"{item.nodeid}\n" for item in session.items)


@pytest.fixture
def write_gradient_asc(tmp_path):
    """A function that writes a gradient .asc file with the PNS parameters of pypulseq's
    example hardware, with the stimulation limits and thresholds multiplied by
    `limit_scale`, and returns its path. The real .asc files are confidential.

    With `split`, it writes the layout of a scanner file: an `ASCCONV` block with CRLF line
    ends and `asCOMP[0].tName`, which includes a `_GSWD_SAFETY.asc` file with the SAFE
    parameters under `GradPatSup.Phys.PNS`.

    With `gpa`, it also writes the GPA limits: a dict from the Siemens mode name (`Fast`,
    `UltraFast`, ...) to `(amplitude in mT/m, rise time in µs per mT/m)`, as the lines
    `asGPAParameters[0].flGradMaxAmpl<Mode>` and `...flGradMinRiseTime<Mode>` (in the main
    file of the split layout). Without `gpa`, the file has no GPA limits."""

    def write(
        limit_scale: float = 1.0,
        name: str = "MP_GPA_TEST",
        split: bool = False,
        gpa: dict[str, tuple[float, float]] | None = None,
    ):
        hw = safe_example_hw()
        prefix = "GradPatSup.Phys.PNS." if split else ""
        pns_lines, scale_lines = [], []
        for axis in "xyz":
            a, suffix = getattr(hw, axis), axis.upper()
            pns_lines += [
                f"{prefix}flGSWDTau{suffix}[{i}] = {getattr(a, f'tau{i + 1}')!r}" for i in range(3)
            ]
            pns_lines += [
                f"{prefix}flGSWDA{suffix}[{i}] = {getattr(a, f'a{i + 1}')!r}" for i in range(3)
            ]
            pns_lines += [
                f"{prefix}flGSWDStimulationLimit{suffix} = {a.stim_limit * limit_scale!r}",
                f"{prefix}flGSWDStimulationThreshold{suffix} = {a.stim_thresh * limit_scale!r}",
            ]
            scale_lines.append(
                f"asGPAParameters[0].sGCParameters.flGScaleFactor{suffix} = {a.g_scale!r}"
            )
        gpa_lines = []
        for mode, (amplitude, rise_time) in (gpa or {}).items():
            gpa_lines += [
                f"asGPAParameters[0].flGradMaxAmpl{mode} = {amplitude!r}",
                f"asGPAParameters[0].flGradMinRiseTime{mode} = {rise_time!r}",
            ]
        path = tmp_path / f"{name}_{limit_scale:g}.asc"
        if not split:
            path.write_text(
                "\n".join([f'asCOMP.tName = "{name}"', *pns_lines, *scale_lines, *gpa_lines]) + "\n"
            )
            return path

        def ascconv(lines):
            block = ["### ASCCONV BEGIN @Checksum=mp2:0 ###", "", *lines, "", "### ASCCONV END ###"]
            return "\r\n".join(block) + "\r\n"

        safety = path.with_name(f"{path.stem}_GSWD_SAFETY.asc")
        safety.write_bytes(ascconv(pns_lines).encode())
        main = [f'asCOMP[0].tName = "{name}"', *scale_lines, *gpa_lines, f"$INCLUDE {safety.name}"]
        path.write_bytes(ascconv(main).encode())
        return path

    return write
