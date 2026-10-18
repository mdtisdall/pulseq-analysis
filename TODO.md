# TODO

- **Move from the pypulseq fork to a pypulseq release (decision 2 of
  `docs/plans/pulseq-checks-v1.md` of pulseq-checks, section 2.4, and
  decision T12 of `docs/plans/pulseq-analysis.md` of pulseq-checks).** This
  package pins pypulseq from the fork `mdtisdall/pypulseq` in
  `[tool.uv.sources]` of `pyproject.toml`: the tag `pulseq-reports-pin-2`,
  commit `3c3bd85`. That is the release 1.5.0.post1 with six commits: the
  SAFE PNS filter as a recursion, `calc_pns` in chunks (with the private
  `_safe_gwf_to_pns_chunk`), the `get_block` fix for oversampled arbitrary
  gradients (upstream PR #424), the read fix of upstream #359, `read` of the
  `[SIGNATURE]` values as text (the hash was a float when the hex digest
  looked like a number; the fork reads them with `numeric=False`,
  `Sequence/read_seq.py:97`), and
  `signature_file` set to `'text'` by `read`, as `write` does (upstream PR
  #428). This package no longer reads the `[SIGNATURE]` hash, so it does
  not need the last two. They stay while the three repositories pin one
  commit. The item
  "Move from the pypulseq fork to a pypulseq release" in the `TODO.md` of
  pulseq-reports gives each commit and how to change the pin.
  pulseq-analysis, pulseq-checks and pulseq-reports must pin the same commit.
  pulseq-analysis no longer depends on pypulseq (task 5b of
  `docs/plans/own-parser-tasks.md`): it is the extra `pypulseq`
  (`pypulseq>=1.5.0`), the package does not import it, and its SAFE filter is
  its own port (`analyses/safe.py`). The pin stays in `[tool.uv.sources]` for
  the `dev` group and the extra: the tests and the scripts use the fork, whose
  `calculate_pns` in chunks makes the tests much faster than with the release
  (a run with 1.5.0.post1 had not ended after 10 minutes and was stopped;
  with the fork it takes about one). The tests that compared with the fork's
  `_safe_gwf_to_pns_chunk` and `safe_hw_check` compare with golden values
  (`tests/golden/`). When a pypulseq release has the six changes: pin that
  release in the `dev` group, remove `[tool.uv.sources]`, and run the tests
  with it. Do this in the three repositories at the same time.

- **A limit of the samples of a shape for `cpp-siemens`.** `spec` does not
  decompress a shape that declares more than 2^27 samples
  (`limit.shape-samples`, C14, #182). `cpp-siemens` has no such limit. The
  C++ reader reads the number of samples of a shape as an `int` (cpp:946), up
  to 2^31 - 1, and `decodeArbGradInBlock` resizes a `std::vector<float>` to it
  and copies it (cpp:2109, cpp:2149). `read_cpp_siemens` decodes each block
  (`first_rejected_block`). `valid_no_signature.seq` with shape 3 declared as
  2^26 samples (stored as four runs, 2894 bytes in all) made the peak memory
  of `read_seqfile(path, "cpp-siemens")` 548 MiB, against 35 MiB: about 8
  bytes for each declared sample (164 MiB at 2^24 samples); by that rate,
  200 000 000 samples would take about 1.6 GB (not measured). To decide: whether `cpp-siemens` gets a limit too.
  The scanner's reader has none.

- **The cost of the model objects in `load`.** The plan of the fixes of the
  review of 2026-10-13 found, for task C16, that most of the rest of the time
  of `load` is in the checks of each model object, and left it to a later
  study. For a file of 200 000 blocks and 200 000 trapezoids
  (`_many_trapezoids` of `tests/test_decoding.py`), `load` takes 1.7 s; under
  `cProfile`, 1.8 s of its 3.0 s are in the 200 003 calls of
  `model._post_init`, which makes each field of a model object immutable, and
  only 0.2 s in `read_seqfile`.
