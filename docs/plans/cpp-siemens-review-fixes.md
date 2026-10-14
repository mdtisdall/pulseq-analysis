# Implementation plan: three fixes of the plugin cpp-siemens

Status: draft, written on 2026-10-14. Section 6 has the decisions that the
user has not answered yet.

## 1. Scope

A review of `main` at `74fa0b2` on 2026-10-13 (in this plan, "the review"; it
is not in `docs/reviews/`) found three bugs of the plugin `cpp-siemens`
(`packages/pulseq-cpp-siemens/`). Each one defeats the goal of the plugin:
to give the waveforms that the C++ reader `ExternalSequence` gives, and to
reject what the reader rejects, with a process that survives the file.

| Bug | What goes wrong | Section |
|---|---|---|
| B1 | The measurements of a block can use the decoding of another block, so they are not the waveform that the reader plays. | 3 |
| B2 | A byte that is not UTF-8 in the reader's messages raises `UnicodeDecodeError`, also for a file that the reader reads. | 4 |
| B3 | `Sequence.gradients_at` with `actual_ru` can end the Python process on a file that `load` accepted. | 5 |

The other findings of the review are not in this plan (section 7).

Each fix starts with tests that fail on `main` and that show the bug. The fix
then makes them pass (section 2). Each fix is one branch and one PR
(`CLAUDE.md`: one branch, one concern):

| Task | Branch | Result |
|---|---|---|
| 0 | `docs/cpp-siemens-fixes-plan` | This plan, and one line for it in `README.md`. No code. |
| 1 | `fix/gradient-variants` | B1: the protocol `Decoding` says which blocks decode an event alike; `_played` gives each such variant its own key. |
| 2 | `fix/cpp-siemens-one-point-soft-delay` | B3: `Sequence.gradients_at` refuses a time that reaches the reader's read past the times of an extended trapezoid of one point. |
| 3 | `fix/cpp-siemens-messages-bytes` | B2: the reader's messages come to Python as bytes, and the package decodes them with `backslashreplace`. |

### 1.1 Order

```
This plan merged
  Wave 1:  task 1 (B1)  ||  task 2 (B3)
  Wave 2:  task 3 (B2)
```

- Tasks 1 and 2 change different files:
  - Task 1: `synth/_played.py`, `synth/decoding.py`, the plugin's
    `interpreter.py`, and the documents of the protocol.
  - Task 2: the plugin's `_checks.py` and `Sequence.gradients_at` in
    `__init__.py`.
- Task 3 changes each place of `__init__.py` that reads
  `self._reader.messages`. One of them is in `Sequence.gradients_at`, which
  task 2 also changes, so task 3 waits for task 2.
- B1 and B3 come first. B1 gives wrong values with no error. B3 ends the
  process. B2 raises an exception of the wrong class.

## 2. The rule for the tests of each task

1. The first commit of the branch adds the tests of the task (and their
   fixtures) and no fix. The implementer runs them on that commit and they
   fail. The PR description quotes the failure: the test names and the line
   of each assertion or crash.
2. The next commits fix the bug. The same tests then pass, with no change to
   them except a name or a message.
3. A test that the plan calls a *property test* runs on every file of a set
   (the fixtures, or the files of the fuzzer). It must also fail on `main`
   for at least one file of the set. If it fails for no file, the set lacks
   the file of the bug: the task adds that file to the set.
4. Each new test gets an entry in `TESTS.md` (CI fails without it:
   `scripts/check_tests_md.py`). Each test that the task removes or changes
   loses or changes its entry.
5. A test that can end the process (task 2) runs the code in a subprocess,
   as `tests/fuzz_worker.py` does. It asserts on the exit status and the
   output of that subprocess.

## 3. B1: the measurements take the decoding of the first block of an event

### 3.1 The bug

`_played` (`src/pulseq_analysis/synth/_played.py:78-84`) calls
`Decoding.gradient_points(key, block, axis)` once for each gradient event: at
the first block and axis that play it. Every other block that plays the event
gets those points. Its docstring says that "a plugin's decoding of a gradient
event must not depend on the block that plays it".

The C++ reader breaks that rule:

- `decodeArbGradInBlock` (cpp:2094-2153) decompresses the shape of each
  arbitrary gradient of a block, in the order gx, gy, gz, into one local
  `std::vector<float> waveform`.
- `decodeExtTrapGradInBlock` (cpp:2155-2196) does the same for the time
  shape and then the wave shape of each extended trapezoid, into a vector of
  its own.
- `waveform.resize(n)` keeps the values that the vector holds. It adds zeros
  only after them.
- `decompressShape` (cpp:2200-2247) can write fewer than `num_samples`
  values, for example with a run of count -2 (that is, 0 repeats). It then
  takes the cumulative sum of all `num_samples` values.

So the samples of a gradient event can contain values of the event decoded
before it in the same block. The vectors are local to one call, so nothing
passes from one block to another. The decoding of an event in a block
therefore depends on:

- the event;
- for an arbitrary gradient, the arbitrary gradients on the earlier axes of
  the block;
- for an extended trapezoid, the extended trapezoids on the earlier axes of
  the block.

The decoding also depends on the global settings (the sampling mode of
oversampled gradients, the gradient raster).

Reproduction (the review; run again for this plan): event 2 is an extended
trapezoid whose time shape is `0 0 -2` (4 samples, of which it writes none).

- In block 0 it is alone, and decodes with the times `[0, 0, 0, 0]` us.
- In block 1 it is on gy after event 1 on gx, and decodes with the times
  `[10, 20, 30, 40]` us.
- `played_gradients` gives block 1 the points of block 0.
- The reader plays `[250, 750, 1000, 750, 0]` Hz/m on gy at 5, 15, 25, 35 and
  45 us of block 1. The measurements see a gradient of length 0 there.

An arbitrary gradient with the same shape gives the same error. There, the
reader plays 1000 Hz/m and the measured points are all 0.

`CppSiemensDecoding.gradient_points` already decodes the block that it is
given (`interpreter.py:808-816`), so it gives the right points for each
block. The fault is that `_played` asks only once for each event.

The test `test_the_cpp_siemens_decoding_of_a_gradient_event_is_the_same_in_every_block`
(`packages/pulseq-cpp-siemens/tests/test_load_in_pulseq_analysis.py:229`)
asserts the rule that is false. It passes because no fixture has the case.

The documents disagree about the rule:

- `docs/usage.md:881-882` says a plugin "can decode one event differently in
  two blocks, so `gradient_points` takes the block".
- `docs/implementation.md:97-99` and the docstring of `_played` say that it
  must not.
- D5.5 (`packages/pulseq-cpp-siemens/docs/specification.md`) says that "a
  shape that decompresses to fewer samples is read with its last value
  repeated". That is true only in an empty buffer.

### 3.2 The fix

**The protocol.** A new member of the protocol `synth.Decoding`:

```
gradient_variants() -> np.ndarray | None
```

- None: each gradient event decodes alike in every block that plays it. This
  is the case for `spec`.
- Otherwise: an int64 array of shape (blocks, 3), read-only, one value for
  each block and axis. Two cells with the same event and the same value
  decode alike: `gradient_points` gives the same points for both. The values
  have no meaning beyond that, and a cell with no event has 0.

Section 6, D1, asks whether `PROTOCOL` stays 1.

**`spec`.** `SpecDecoding.gradient_variants()` returns None. No value of
`spec` changes.

**`_played`.** When `gradient_variants()` is not None:

1. Take the pairs (event, variant) of all cells, and the first cell of each
   pair (`np.unique` on the pairs, with `return_index`).
2. For each event, the pair of the first cell that plays the event keeps the
   file ID as its key. Each other pair of the event gets a new key above the
   largest key of the columns.
3. Ask `gradient_points(event, block, axis)` once for each pair, at its
   first cell, and put the new keys in the columns.

This runs before the blocks of `gradients_at` are chosen, so that
`_from_gradients_at` and `_plan` see the points of the variant. Its base for
new keys is already the largest key of the columns plus 1
(`_played.py:134`), so its keys stay above the variant keys. A file with no
variant keeps every key that it has now.

**`cpp-siemens`.** `CppSiemensDecoding.gradient_variants()` gives the
variants from the libraries that `load` read, with no block decoded:

- A new helper in `_checks.py`, next to `_decompress_into`: whether the
  decompression of a shape writes each of its `num_samples` values. An
  uncompressed shape always does (memcpy, cpp:2202-2205). A compressed shape
  does not when the run-length decoding writes fewer values (the counter
  `count_unpack` at the end, or a run of count -2 or less).
- An arbitrary gradient depends on the block when its wave shape does not
  write each value. An extended trapezoid depends on the block when its time
  shape does not write each value. Its wave shape follows its own time
  shape, so a short write there depends only on the event.
- For each cell whose event depends on the block, the variant is the number
  of the tuple of the events on the earlier axes of the block (`np.unique`
  with `return_inverse`, plus 1). Every other cell has 0.

  The tuple holds the events of every kind, so two blocks can get two
  variants where the reader decodes alike. The cost of that is one more
  decoding and one more key, and the values do not change.
- The result is None when no cell depends on the block. That is the case for
  the files that MATLAB Pulseq and pypulseq write. It is kept on the
  decoding.

**What changes for a caller.**

- In a file with the case, `played_gradients`, `sequence_index` (the dense
  IDs of `seq.index`) and the kept samples of the sampler count each variant
  as an event of its own.
- The values of each block become those that the reader plays.
- No public name changes. `Decoding` has one more member, which a plugin
  must implement.

### 3.3 The tests (first commit)

New fixtures in `packages/pulseq-cpp-siemens/tests/fixtures/`. Both are
version 1.5.0 files that the C++ reader loads and decodes, and that `spec`
rejects (a run of count -2 makes a shape shorter than `num_samples`):

- `gradient_buffer_ext_trap.seq`: the file of section 3.1. Block 0 has event
  2 alone on gx. Block 1 has event 1 on gx and event 2 on gy. Event 2's time
  shape is `0 0 -2`.
- `gradient_buffer_arbitrary.seq`: the same with arbitrary gradients (time
  shape 0).

The tests:

1. **The waveform of the measurements is the reader's** (property test, in
   `test_load_in_pulseq_analysis.py`).
   - On every file of the plugin's fixtures and `tests/seqfiles/` that
     `cpp-siemens` reads, including the two new ones,
     `gradient_sampler(snap).sample(axis, t)` equals
     `snap.data.reading.gradients_at(blocks, t_in_block)`.
   - The times are the midpoint of each segment of the played points of each
     block, and three block-local times in each block.
   - A time within `TIME_TOLERANCE` of a point of a step is left out: there,
     the two conventions of the value at a step differ.
   - The tolerance is `1e-9` of the largest value of the axis.
   - Today no test compares the measurements of `cpp-siemens` with the
     reader's own `gradientsAt`. The oracle comparisons build the oracle from
     the package's `played_gradients` (`tests/oracles/blocks.py:63`), so they
     could not find B1. This test closes that gap for every later change too.
   - On `main` it fails on both new fixtures: block 1, gy.
2. **The exact values of the case.** On `gradient_buffer_ext_trap.seq`, the
   sampler gives `[250, 750, 1000, 750, 0]` Hz/m on gy at 5, 15, 25, 35 and
   45 us of block 1, and `gradient_peaks` gives a gy peak of 1000 Hz/m.
   - On `main`: 0 everywhere on gy.
3. **The test of the false rule is replaced.**
   `test_the_cpp_siemens_decoding_of_a_gradient_event_is_the_same_in_every_block`
   becomes `test_the_cells_of_one_event_and_one_variant_decode_alike`.
   - It asserts the new rule on every file that `cpp-siemens` reads.
   - It also asserts that `gradient_variants()` is None for each file of
     `tests/seqfiles/` that `spec` reads, and has two variants of event 2 for
     each new fixture.
   - On `main` it fails: the member does not exist.
4. **`_played` gives each variant its own points** (in
   `tests/test_played.py`).
   - A fake plugin's decoding gives other points for one event in block 1
     than in block 0, and a `gradient_variants` that says so.
   - `played_gradients` gives block 1 a new key with the points of block 1,
     and block 0 keeps the file ID.
   - A second case also rotates block 1 through the session, so that
     `_from_gradients_at` builds its points from the variant's points.
   - On `main` block 1 gets the points of block 0.
5. **The helper of the short write** (in `test_checks.py`). It is true for
   an uncompressed shape and for a compressed one that fills its samples. It
   is false for `0 0 -2` and for a shape whose runs end before
   `num_samples`.

The fake plugins of the root tests (`tests/test_interpreters.py`,
`tests/test_played.py`, `tests/test_session.py`) get a `gradient_variants`
that returns None.

### 3.4 The documents

- `_played.py`, module docstring: replace the "must not depend on the block"
  rule with the variants.
- `synth/decoding.py`: the `Decoding` protocol, and `SpecDecoding`.
- `docs/usage.md` section 8: the members of `Decoding`. Replace lines 881-882.
- `docs/implementation.md` section 1.2: the variants. Section 2.5: the keys
  of variants.
- `docs/findings-for-pulseq-checks.md`: the members of the protocol.
- `CHANGELOG.md` (Unreleased): the new member of `Decoding`.
- `docs/migration.md`: for a plugin author, the new member.
- Plugin `docs/specification.md`, D5.5: replace the sentence on a shorter
  decompression. It keeps the values of the buffer, which hold the event
  before it in the block (cpp:2099-2110, cpp:2161-2190), and `cpp-siemens`
  follows the reader there.

  No new record entry: `cpp-siemens` follows the reader, so by the rule of
  the record nothing departs from it.
- `TESTS.md`: the entries of section 3.3.

## 4. B2: the reader's messages that are not UTF-8

### 4.1 The bug

`Reader::messages` (`src/reader.cpp:1099`, bound at :1168) returns a
`std::string`. nanobind converts it to `str` as strict UTF-8. The reader puts
text of the file into its messages:

- `load`: the row, after each "failed to decode" error (for example the ADC
  event, cpp:1150), and the line of an unknown extension, after "unknown
  extension ignored" (cpp:1248), on a file that it loads;
- `GetBlock`: the name of an extension that it does not implement, in
  "unimplemented extension type <name> in block <n>" (cpp:1919). Each
  decoding of a block whose extension list has that extension prints it.

A byte that is not UTF-8 there makes each read of `reader.messages` raise
`UnicodeDecodeError`. That covers every read of `messages`:

- `__init__.py`: lines 242, 257, 338, 382 and 383;
- `load`, for a file that the reader accepts.

Reproduction: `valid_1_5_1.seq` with the extension name `UNKNOWN` changed to
`UNKN\xb5WN` raises `UnicodeDecodeError` in `cs.load`. The C++ reader loads
the file. An ADC row `1 \xb5x` raises it too, where `spec` gives
`SeqFileError` (`syntax.encoding`).

This breaks the contract of `Plugin.read`, which is `SeqFileError` with a
code. The fuzzer misses it, because `mutate_text` inserts only ASCII bytes
and 0xFF (`tests/seqfuzz.py:736`).

The other strings of the binding are safe:

- definitions, the signature and the extension names come to Python as bytes
  (`as_bytes`), and `interpreter.py` decodes them with `surrogateescape`;
- label names come from the reader's fixed table of known labels.

### 4.2 The fix

- `reader.cpp`: `messages` returns `nb::bytes` (`as_bytes(messages_)`).
- `__init__.py`: one helper `_messages(reader) -> str`, which decodes with
  `"utf-8", "backslashreplace"`. Each read of `messages` uses it.
  - `Sequence.messages`, `Sequence.rejection_messages` and
    `Rejected.messages` stay `str`.
  - `backslashreplace` and not `surrogateescape`: a message is for a person,
    and a `str` with surrogates raises again when it is printed or written as
    UTF-8. The patterns of `interpreter.py:259-269` are ASCII, so the codes
    do not change.
- The fuzzer: `mutate_text` (`tests/seqfuzz.py:717`) also inserts a byte that
  is not UTF-8 (`\xb5`, or `\xc3(`).
  - Any change to its choices changes the bytes that some seeds draw, so the
    task runs `test_the_seeded_files_reach_each_case_of_undefined_behaviour`
    and the corpus tests again.
  - It adds a file with such a byte to `tests/fuzz_corpus/`, with its line in
    `expected.json`, so that the case stays covered whatever the seeds draw.

### 4.3 The tests (first commit)

In `packages/pulseq-cpp-siemens/tests/test_api.py`, with the files built as
bytes in the test from `tests/seqfiles/valid_1_5_1.seq`:

1. **A file that the reader loads loads.** With `UNKN\xb5WN`, `cs.load`
   returns a `Sequence`, and its `messages` contain `UNKN\\xb5WN`. On `main`:
   `UnicodeDecodeError`.
2. **A rejection keeps its class and its code.**
   - With the ADC row `1 \xb5x`, `cs.load` raises `Rejected`, and its
     `messages` contain `\\xb5`.
   - `read_seqfile(path, "cpp-siemens")` raises `SeqFileError` with the code
     that it gives for the same file with `x` in place of `\xb5`
     (`syntax.row`, ADC). This is a differential assertion, so it does not
     depend on the text of the message.
   - On `main`: `UnicodeDecodeError`.
3. **The messages of a decoded block.**
   - The file: `UNKN\xb5WN` as in test 1, and the block of ID 4 (play index
     3), whose extension list has that extension, made to fail `decodeBlock`. For example, give it an
     extended trapezoid whose time and wave shapes differ in length
     (cpp:2186-2192).
   - Then `decode_block(3)` raises `Rejected`, `gradients_at` at block 3
     raises `Rejected`, and `first_rejected_block()` gives 3. Each message
     contains `unimplemented extension type UNKN\\xb5WN`.
   - On `main` each of the three raises `UnicodeDecodeError`.
4. **The fuzzer reaches it.** A file of `tests/fuzz_corpus/` has a byte that
   is not UTF-8. `test_the_corpus_agrees_with_the_sanitized_oracle` gives it
   the oracle's verdict. On `main` the worker ends with
   `UnicodeDecodeError`, and the test fails.

## 5. B3: `gradients_at` with a soft delay longer than the stored duration ends the process

### 5.1 The bug

`gradientsAt` of an extended trapezoid with one time reads past its times
(cpp:3639-3650; D5.10, `ub.gradient-one-point`):

- the binary search starts with upper = 1 and does not run;
- it then interpolates between `times[0]` and `times[1]`.

That happens at each time `t` of the block with `max(delay, 0) <= t`,
`t < delay + times[0]` and `t <= GetDuration()`. `GetDuration()` is the
value of the hook `setActualSoftDelay_ru` when one is set, and otherwise the
stored duration (`ExternalSequence.h:705`). The value of the hook replaces the
stored duration: it is the whole duration of the block, not an offset added
to it.

The check (`_checks.py:466-482`) tests the stored duration only
(`not start > duration`). It accepts a file in which every such time is after
the stored duration of the block, that is, `max(delay, 0)` is past the end of
the block. `Sequence.gradients_at(..., actual_ru=...)` can then give the block
a duration that is longer than its stored duration. When that duration
reaches `max(delay, 0)`, the read becomes reachable. A duration that is longer
than the stored one but ends before `max(delay, 0)` is still safe.

Reproduction (the review): `tests/fixtures/gradient_one_point.seq` with the
delay of gradient 5 set to 200 us, which is past the 100 us of the block of
ID 5. Block indices below are play indices from 0, so that block is 4.

- `cs.load` accepts it: the read starts at 200 us, after the stored 100 us.
- `a[4] = 100` sets the duration of block 4 to 100 block rasters, 1000 us,
  which reaches 200 us.
- `gradients_at([4], [205.0], actual_ru=a)` then ends Python
  with SIGTRAP from the hardened libc++.
- A build without the hardening reads memory past the vector and returns a
  value with no error.

The README and the module docstring say that `load` rejects every case of
undefined behaviour "so that the process survives the file".

`CppSiemensDecoding` does not reach the case: the session sets a soft delay
only on a block that is a pure delay (`soft_delay_durations`), and such a
block has no gradient. `block_durations_ru(actual_ru)` runs only
`GetDuration_ru`, which reads no times, so it is safe.

### 5.2 The fix

- `_checks.undefined_behaviour` also gives the one-point reads that the
  stored duration hides: for each block, the intervals `[start, delay + t0)`
  (us) of its extended trapezoids of one point, where `start > duration`.
  It returns them with the case, for example as a small frozen dataclass
  `Checked(case, hidden_one_point)`, whose second field maps a block to its
  intervals. `load` keeps them on the `Sequence` (`_hidden_one_point`).

  The intervals are only for the blocks that have them. That is none in a
  file that MATLAB Pulseq or pypulseq writes, so the cost is one dict.
- `Sequence.gradients_at`, when `actual_ru` is given, checks each pair of
  (block, time) of a block in `_hidden_one_point` with `actual_ru[block] >=
  0`. When the time is in an interval and is not after
  `actual_ru[block] * block_raster_us`, it raises `UndefinedBehaviour` with
  the case `ub.gradient-one-point`, the block and the time, before the reader
  runs. The check is vectorised over the pairs of those blocks.
- The guard is per pair, not per block. The reader reads only at the times
  that it is given, so a call at times outside the intervals stays the
  reader's call. Section 6, D2, asks whether to refuse the whole block
  instead.
- The private binding `_reader.Reader.gradients_at` stays as it is. Only the
  public `Sequence` is the contract.

### 5.3 The tests (first commit)

The fixture `packages/pulseq-cpp-siemens/tests/fixtures/gradient_one_point_after_block.seq`
is `gradient_one_point.seq` with the delay of gradient 5 set to 200 us. The
tests run the calls in a subprocess (section 2, rule 5):

1. **The call that ended the process raises.**
   `gradients_at([4], [205.0], actual_ru=a)` with `a[4] = 100` raises
   `UndefinedBehaviour` with the code `ub.gradient-one-point`, block 4 and
   time 205.0, and the subprocess exits with 0.
   - On `main` the subprocess ends with a signal (the hardened build of the
     devShell), or returns a value with no exception (another build). Both
     fail the assertion.
2. **A time outside the interval keeps the reader's value.** With the same
   `actual_ru`, times before the delay and after `delay + t0` (still inside
   the 1000 us of block 4) give the values of the reader: 0 before the delay, and
   0 after the event. The second time is also checked against the sanitized
   oracle where it is on the PATH. This guards against a fix that refuses
   too much. It passes on `main`; it is in the first commit so that it
   guards the fix.
3. **A duration that does not reach the read is accepted.**
   - With `a[4] = 10` (100 us, the stored duration), the call gives 0: the
     time is after the end of the block.
   - With `a[4] = 15` (150 us, longer than the stored duration but before the
     delay of 200 us), it gives 0 too, with no exception.
   - Both pass on `main` too. They guard against a fix that refuses every
     duration longer than the stored one.
4. **The checks give the hidden intervals** (in `test_checks.py`). On the new
   fixture, `undefined_behaviour` gives no case and the interval of block 4.
   On `gradient_one_point.seq` it gives the case as now. On `main` the
   function has no second result.
5. **The fuzzer covers the path.** The worker (`tests/fuzz_worker.py`) also
   calls `gradients_at` with an `actual_ru` that gives each sampled block a
   duration past the end of its last gradient event (its largest `delay` plus
   the length of the event, plus one block raster). That duration is longer
   than the stored one wherever an event ends after the block. The times are
   those of `sample_points` for that duration.
   `seqfuzz.py` gives the same pairs to the sanitized oracle.
   - The oracle's `--sample` reads lines `block_index time_us` and sets no
     soft delay (`tests/cpp_oracle/driver.cpp:7`). The task adds an optional
     third field, the `actual_ru` of the block, which the driver sets with
     `setActualSoftDelay_ru` around the call, as the binding does.
   - It updates `tests/cpp_oracle/README.md` and the entry of the driver in
     `TESTS.md`. The flake builds the driver from that file, so the
     devShell's oracle has the field after `nix develop`.
   - A file with the case then has the verdict "undefined-behaviour" from the
     worker and a sanitizer report from the oracle: the two agree.
   - A mutation `m_gradient_one_point_after_block`, next to
     `m_gradient_one_point` (`seqfuzz.py:637`), puts the delay past the end
     of the block, so that the seeded files reach the case.
   - On `main` the worker ends with a signal on such a file, and
     `test_the_checks_agree_with_the_sanitized_oracle_on_the_seeded_files`
     fails.

### 5.4 The documents

- Plugin `docs/specification.md`, D5.10: the condition with the duration of
  the hook, and that `gradients_at` refuses the times that reach the read.
- `README.md` of the plugin, and the docstring of `Sequence.gradients_at`:
  the new `UndefinedBehaviour`.
- `TESTS.md`: the entries of section 5.3.

## 6. Decisions

**D1. Does the protocol stay version 1?**

- `PROTOCOL = 1` and the protocol `Plugin` came in the Unreleased section of
  `CHANGELOG.md`. The last tag is `v0.1.0rc6`. No released plugin implements
  version 1.
- pulseq-cpp-siemens is in this repository, and changes in the same PR as
  the protocol.
- Option a (recommended): add the member to version 1, before its first
  release. Nothing outside this repository implements it.
- Option b: `PROTOCOL = 2`. Each place that says "version 1" changes, and
  version 1 never ships.

**D2. Does the guard of B3 refuse a time, or a block?**

- Option a (recommended): a time. The pairs that reach the read raise.
  Others give the reader's value, as the reader gives it.
- Option b: a block. Any call with an `actual_ru` that makes a block with a
  hidden interval reach `start` raises, whatever the times. That is simpler
  (no per-pair check), but it refuses calls that the reader runs safely.

**D3. Does task 3 also fix the race of the messages?**

- The review (plugin finding 5, "plausible") found that threads that share
  one `Sequence` can read `messages_` while another call writes it, because
  the read does not hold `g_reader_mutex`.
- Task 3 changes the same accessor.
- Option a (recommended): no. It is another concern, with its own test
  (threads on one `Sequence`). A later branch makes each call return its
  messages, and removes the shared `messages_`.
- Option b: yes, in task 3.

## 7. Not in this plan

These findings of the review are left out:

- The other findings for the plugin:
  - the "edge" mode with an oversampled gradient of 0 samples;
  - undefined behaviour as one first-found rejection;
  - the duplication with the main package;
  - the race of the messages (section 6, D3).
- The findings for `spec`, `synth`, the analyses, the tests and the
  documents. They are for a later plan, which could commit the review as
  `docs/reviews/2026-10-13-code-review.md`, as the four earlier reviews are.

## 8. When this plan is done

- Delete this file before the last task merges. Its lasting content is in
  the documents of sections 3.4, 4 and 5.4, and in `CHANGELOG.md`.
- Remove its line from `README.md` in the same PR.
