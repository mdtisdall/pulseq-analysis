# Plan: predict the `decodeBlock` rejections of `cpp-siemens`

Branch `docs/cpp-siemens-verdict-predictor`. This plan is on hold: it is done only when a read
through `cpp-siemens` is too slow for a user (the user, 2026-10-12). Nothing in it is decided
yet; section 7 lists the decisions to take before the work starts.

"The plan of the redesign" is `docs/plans/parser-redesign.md` (P1-P19, Q1-Q6). "cpp:N" is a line
of `src/ExternalSequence.cpp` of pulseq/pulseq at `c7469123`. "The checks" are those of
pulseq-cpp-siemens for the reader's undefined behaviour (`_checks.py`, section 5.3 of the plan of
the redesign).

## 1. Goal

`read_seqfile(path, "cpp-siemens")` gives the verdict of the C++ reader (P2): it reads a file that
the reader reads, and rejects a file that the reader rejects. The reader rejects some files only
in `decodeBlock`, so today the interpreter decodes every block to find them
(`Sequence.first_rejected_block`). On an Apple M1 Max, a file of 21 MB with 899 912 blocks takes
about 4 s:

| Step | Time |
|---|---|
| The "as written" reading | 0.3 s |
| `ExternalSequence::load` | 0.4 s |
| The checks (Python, one pass over the blocks) | 0.8 s |
| `GetBlock` and `decodeBlock` of every block | 2.2 s |

`strict` reads the same file in 0.6 s, so `strict` is the default (P19).

The goal: give the same verdict, with the same code and the same block, without the decoding.
The checks already follow what `GetBlock` and `decodeBlock` do with each block, from the
libraries that `load` built. They can also find the four places where `decodeBlock` returns false
or throws. A read would then take about 1.6 s, perhaps less with a faster pass over the blocks
(section 6).

The predictor changes no verdict and no code. The message of a reason changes: today it is the
reader's own message; with the predictor it is the package's (section 4).

## 2. What `decodeBlock` rejects

`decodeBlock` (cpp:1981-2091) returns false, or throws, at these steps, in this order for one
block. The reader stops at the first one in the block. The C++ oracle's first mode goes on with
the next block, and the verdict names the first block that fails.

| Step | Where | Rejection | Code |
|---|---|---|---|
| 1. RF magnitude shape | `decompressShape` (cpp:1995) | A compressed shape whose repeat count is not a whole number (cpp:2219-2228) | `shape.decompression` |
| 2. RF phase shape | `decompressShape` (cpp:2002) | The same | `shape.decompression` |
| 3. RF time shape, not regular | `decompressShape` (cpp:2026) | The same | `shape.decompression` |
| 4. RF resampling | `std::vector<float> wv_a(nSamples)` (cpp:2032-2034) | `nSamples = int(0.5 + last time)` below 0: the vector throws `std::length_error` | `cpp.exception` |
| 5. Arbitrary gradients, GX to GZ | `decodeArbGradInBlock` (cpp:2094-2151) | `decompressShape` of the waveform (cpp:2108-2111), then a gradient raster other than 10 µs (cpp:2114-2119) | `shape.decompression`, then `gradient.raster` |
| 6. Extended trapezoids, GX to GZ | `decodeExtTrapGradInBlock` (cpp:2155-2196) | `decompressShape` of the time shape (cpp:2177), of the waveform (cpp:2187), then time and waveform of different lengths (cpp:2189-2192) | `shape.decompression`, then `shape.ext-trap-lengths` |

`GetBlock` (cpp:1822-1950) rejects nothing that `load` has not rejected; its cases of undefined
behaviour are the checks' own. Any other exception of the C++ library (`std::bad_alloc` for a
size that the machine cannot allocate) is `cpp.exception` today, and it depends on the machine
(section 5).

The checks already compute the first four columns' facts:

- `_checks._decompression` returns `("false", "")` exactly where `decompressShape` returns false
  (the format test of cpp:2219-2225, in float32). Nothing uses that result yet.
- `_checks._check_rf` computes `nSamples` of the resampling, and knows when it is negative.
- `_checks._extended_trapezoids` follows the buffer that `decodeExtTrapGradInBlock` reuses for the
  shapes of one block, so it has the lengths of each time shape and waveform as decoded.
- The gradient raster is one value of the libraries; `seqfile.cpp_siemens._classify` already finds
  `gradient.raster` this way, after the decoding.

## 3. The design

### 3.1 Where

In pulseq-cpp-siemens, next to the checks: a function `_checks.decode_rejection(libraries,
oversampling) -> Rejection | None`, and a method `Sequence.predicted_rejection()`. A `Rejection`
has the index of the block, the code, the cpp lines and a message. The checks already walk the
blocks in play order with a cache for each event, so the predictor is a second result of the same
walk: the walk returns the first case of undefined behaviour of the whole file, and the first
predicted rejection.

`Sequence.first_rejected_block()` stays: it is the reader's own verdict, for the tests and for a
caller who wants it.

### 3.2 The order

The verdict keeps today's order:

1. A case of undefined behaviour anywhere in the file wins, as today (`load` raises
   `UndefinedBehaviour` before any block is decoded). The sanitized oracle decodes every block,
   also after a rejected one, so it finds the case even after a block that the reader rejects.
2. Else, the first block in play order that `decodeBlock` rejects, and in that block the first step
   of section 2 that fails. A step after the failing one is not reached: its shapes are not
   decoded, and they cannot change the code.

The walk must therefore not stop at the first predicted rejection: it goes on to find a case of
undefined behaviour in a later block, as the checks do today.

### 3.3 Per block, not per event

Most steps depend only on the event: an RF event or an arbitrary gradient gives the same result in
each block, so the walk caches it by event ID, as the checks do. Step 6 depends on the block: the
reader decodes each extended trapezoid of a block into one buffer, and a shape that decompresses
to fewer samples than `num_samples` keeps the values of the shape before it. The checks already
cache step 6 by the tuple of the block's gradients; the predictor uses the same cache.

The oversampling mode (`center`, `edge`, `preserve`) changes no rejection: it acts after
`decompressShape` and the raster test (cpp:2123-2146), and keeps at most the samples that the
waveform has. The predictor takes the mode only to say so in a test.

### 3.4 In pulseq-analysis

`seqfile.cpp_siemens.read_cpp_siemens` calls `Sequence.predicted_rejection()` in place of
`first_rejected_block()`. The reason of the `SeqFileError` has the predicted code, the section
and the message of the predictor. `_classify` keeps only the rejections of `load`, whose messages
it reads. A setting may keep the reader's own verdict for a caller who wants both, for example
`CppSiemens(verdict="decode")` (section 7).

## 4. The contract

Section 7.3 of the plan of the redesign makes the codes and the readings public. The predictor
keeps every code, every block index and every verdict. It changes:

- the `message` of a reason of a `decodeBlock` rejection: the package's text (with the cpp lines),
  not the reader's printed message, which has no code and for `gradient.raster` nothing at all
  (the reader prints that one at a debug level);
- the time of a read.

`CHANGELOG.md` notes both. pulseq-checks names rejections by their codes, so it does not change.

## 5. Allocation failures

`decodeBlock` allocates a buffer of `num_samples` floats for each shape that it decodes, and
`nSamples` floats for a resampled RF pulse. A size near the end of the range of an `int` asks for
up to 8 GB. Today the decoding then succeeds or throws `std::bad_alloc` (`cpp.exception`) by the
memory of the machine, and the oracle does the same. A predictor cannot know which.

The fuzzing already avoids these sizes (`CAP` of `tests/seqfuzz.py`: no path that the checks let
through allocates more than 20 000 samples). Options:

- Predict the decoding as a success (the reader on a machine with the memory), and say so.
- Reject a size above a bound with a code of its own (`decode.too-large`), which neither the
  reader nor the oracle gives: a departure from P2.
- For such a file only, fall back to `first_rejected_block()`.

The third keeps the reader's behaviour on the machine and costs nothing for usual files.

## 6. Cost

The predictor adds little to the walk of the checks: the facts of section 2 are computed already,
and the results are cached by event. The expected time of the file of section 1 is then about
0.3 + 0.4 + 0.8 = 1.5 s, plus the predictor, against 4 s today.

The walk itself is a Python loop over the blocks (0.8 s). It can be made faster without changing
any result: group the blocks by their tuple of event IDs (a file has few unique tuples; the
example has 899 912 blocks and 22 tuples), check each tuple once, and keep the first
block of each. Step 6 and the extension lists depend on the tuple only, so this is exact. Then a
read could take about 0.8 s. This is a separate step of the work (section 8), measured on its own.

## 7. Decisions to take before the work

1. **Where the predictor lives**: in pulseq-cpp-siemens next to the checks (section 3.1, a change
   of its release), or in pulseq-analysis on the libraries (no release of the package, but the
   checks' internals are not public).
2. **Allocation failures** (section 5): which option.
3. **The reader's own verdict**: keep a setting for it (`CppSiemens(verdict="decode")`), or keep
   `first_rejected_block()` only for the tests.
4. **The faster walk** of section 6: in the same work, or only if the predictor is not fast
   enough.

## 8. Tasks

1. The predictor in the walk of the checks (sections 2 and 3), with a unit test for each row of
   section 2 (one file for each code, as `tests/test_cpp_siemens.py` has; the files of
   `CODE_FILES` there are a start).
2. Its verification:
   - every fixture of `tests/seqfiles` and of the package: the prediction equals
     `first_rejected_block()` (block and code), and the driver's first mode;
   - the fuzzing: each generated file compares the prediction with the driver's first mode (the
     verdict and the block), in each oversampling mode, in the corpus, the smoke set, the seeded
     set and the weekly run. The generator must reach each row of section 2 often enough; count
     them as the seeded set counts the codes of undefined behaviour today.
3. pulseq-analysis: `read_cpp_siemens` on the prediction (section 3.4), and the setting of decision
   3 if any. `tests/test_cpp_siemens.py` keeps its comparison of every fixture with the oracle.
4. The faster walk of section 6, if decided, with the same verification.
5. Documents: the timing paragraph of `docs/usage.md` ("The interpreters"), the README of the
   package, `CHANGELOG.md` (section 4), `TESTS.md`; and whether the default (P19) changes, which is
   the user's decision.

## 9. Risks

- **A prediction that differs from the reader.** The predictor replicates code of the reader, so
  it can be wrong where the checks are right. The fuzzing against the driver's first mode is the
  safeguard, as it is for the checks. A wrong prediction costs a wrong verdict, not the process:
  the decoding of a block that the predictor passes still runs in the reader, and still returns
  false or throws if the prediction missed it.
- **The reader changes.** A new pinned commit of pulseq/pulseq can add a rejection to
  `decodeBlock`. The fuzzing finds a new one only if the generator reaches it; the release
  checklist of pulseq-cpp-siemens then reads the diff of `decodeBlock` and its callees.
- **Machine-dependent allocation** (section 5).
