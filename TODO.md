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
  When a pypulseq release has all six changes: pin that release in
  `[project] dependencies`, remove `[tool.uv.sources]`, and change
  `pns_levels.py` of this package to the released name of the chunk
  function. Do this in the three repositories at the same time.
