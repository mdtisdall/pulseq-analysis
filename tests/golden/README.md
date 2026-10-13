# Golden values

`safe_fork.npz` holds the outputs of two functions that only the pypulseq fork has as the
tests need them: `_safe_gwf_to_pns_chunk` (the SAFE PNS filter in chunks) and
`safe_hw_check`, of `pypulseq.utils.safe_pns_prediction`. The tests of `test_safe.py`
that compare the package's SAFE filter and hardware check with the fork compare with these
values, so that they run with a pypulseq release or with no pypulseq.

- Fork: `mdtisdall/pypulseq`, tag `pulseq-reports-pin-2`, commit
  `3c3bd8515e591ef859399aa20db64b1bd2c3a725` (pypulseq 1.5.0.post1 with six commits).
- Script: `make_golden.py`. It reads the inputs from the constants of `test_safe.py`
  (`CHUNK_NAMESPACES`, `CHUNK_DTS`, `CHUNKS`, `chunk_waveform`, `HW_CHECK_CASES`,
  `SEQUENCES`, `BINS`, `THRESHOLDS`) and the sequences of `synthetic.py`.

To make the file again, pin the fork commit in `pyproject.toml`
(`[tool.uv.sources] pypulseq = { git = "https://github.com/mdtisdall/pypulseq", rev = "..." }`),
then from the root of the repository:

```bash
uv run python tests/golden/make_golden.py
```

The keys:

- `chunk/<namespace>/<dt>/<i>/{pns,g_last,zi}`: the output and the state of chunk `i`;
- `hw_check/<case>`: whether `safe_hw_check` accepts the namespace (a bool);
- `levels/<sequence>/<bin>/<field>`: the fields of `_compute_levels` (`levels_arrays`) with
  the fork's `_safe_gwf_to_pns_chunk` in place of the package's.
