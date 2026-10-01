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
