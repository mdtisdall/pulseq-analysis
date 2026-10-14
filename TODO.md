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
  looked like a number; draft 09 of `mdtisdall/pypulseq-issues`), and
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

- **Whether `spec` reads a `[TRAP]` row whose rise, flat and fall times are
  all 0 (decision D4 of the plan of the fixes of `cpp-siemens`, open on
  2026-10-14).** `spec` reads one today, and its event has all its points at
  one time. The measurements handle such an event (B6, PR #138): a block that
  they read through `gradients_at` always has two times or more. Before a
  decision, check what the specification says, and whether pypulseq or
  MATLAB Pulseq write such a row. A rejection would be a rule of
  `spec.RULES` and an entry of `docs/discrepancies.md`, on a branch of its
  own. Also not yet checked: whether pypulseq or MATLAB Pulseq write a
  gradient amplitude of NaN, which `cpp-siemens` reads (B7, PR #140).
- **The other findings of the review of 2026-10-13**
  (`docs/reviews/2026-10-13-code-review.md`). The plan of the fixes of
  `cpp-siemens` (PRs #134 to #141) fixed four of its bugs, and three that the
  work found (B5 to B7); section 7 of the review gives the status. Its
  findings that are not fixed:
  - for the plugin: the "edge" mode with an oversampled gradient of 0
    samples (1.1.5), and undefined behaviour reported as one first-found
    rejection (1.1.6);
  - the findings of sections 1.2 to 6, for `spec`, `synth`, the analyses,
    the duplication, the tests, the documents and the API.
