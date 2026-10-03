# Repaired 0.2.1 evidence · 2026-10-03

Frozen 0.2.0 commit `8331d4107244b096298adc56bb071d4651fbff68` received independent Commercial 84 / Technical 65 (raw 88, core cap) / Innovation 84 and FAIL: a genuine supported `-0.0` numeric-group checkpoint could not restore. [0.2.0 observations](VALIDATION_0.2.0.md) and [result archive](validation-results-0.2.0.json) remain unchanged historical evidence. Original 0.1.0 observations/83/65/83 FAIL and all six preceding correction cycles remain preserved. Package 0.2.1 repairs the primitive candidate omission, keeps wire v3 and awaits independent re-review. Correction commit `4ee9553a068dd86196119f7106f2b1989082f146` contains the identical tested library sources; [structured results](validation-results.json) bind observations to actual source digests and wheel bytes.

Windows 11 / CPython 3.14.3. The rebuilt ordinary wheel is installed noneditable in `.venv-clean`; importing from the system temporary directory resolves to site-packages/version 0.2.1/SPDX MIT. Wheel SHA-256: `66be1d20c635c59cc113a652e83de4860e0d67c56cc973635b6d91eb5f98af49`. Wheel contents match the tested source tree. This hash binds that wheel, not reproducibility of future ZIP builds. Python 3.11 and remote CI execution remain unknown; CI targets Ubuntu/Windows × Python 3.11/3.14.

Actual commands from the repository:

```powershell
.venv\Scripts\python.exe -m build --wheel
.venv-clean\Scripts\python.exe -m pip install --force-reinstall --no-deps dist\streamcontract-0.2.1-py3-none-any.whl
.venv-clean\Scripts\python.exe -m unittest discover -s tests -v
.venv-clean\Scripts\python.exe ../reviews/streamcontract_signed_zero_probe.py
.venv-clean\Scripts\python.exe ../reviews/streamcontract_checkpoint_domain_probe.py
.venv-clean\Scripts\python.exe ../reviews/streamcontract_independent_probes.py
.venv-clean\Scripts\python.exe ../reviews/streamcontract_numeric_rereview_probes.py
.venv-clean\Scripts\python.exe examples/workflow.py
.venv-clean\Scripts\python.exe examples/cli_workflow.py
.venv-clean\Scripts\python.exe benchmarks/compare.py
.venv-clean\Scripts\streamcontract.exe --contract examples/contract.json --input examples/events.jsonl
```

The signed-zero script is unchanged with SHA-256 `69ea74ca52ddfc466608ff078c8d5b53cde2ac2a20d3021b9d707a95d584a294`. Before: original installed 0.2.0 engine/moments matched frozen 8331d410; event valid/ACCEPTED, genuine checkpoint failed restore, **exit 1**. After: untouched genuine checkpoint restores byte-identically and finishes PASS, **exit 0**. [Before](signed-zero-evidence/signed-zero-before.json), [after](signed-zero-evidence/signed-zero-after.json) and [iteration history](ITERATIONS.md) retain the actual artifact/command/output binding.

**56 tests in 3.857s, OK**, prior 49 plus seven new representation/recovery tests. Coverage includes the distinct group identities of integer zero, positive float zero and negative float zero; typed zero enums and ranges; mixed integer/time/float group keys; every SDK resume cut with window closure/late events; all eight negative-zero numeric keys; and continued rejection of digests for disallowed primitive types. The actual CLI regression runs all seven cuts. [Full log](signed-zero-evidence/tests.log).

Unchanged original four-domain probe: **exit 0**, all four impossible states reject. Original independent probes: **6 tests in 1.193s, OK**, 40 streams / 3200 records / 160 resume comparisons, zero mismatches. Unchanged numeric re-review probes: **6 tests in 0.085s, OK**, preserving independently enumerated 55 enum and 241 binary multisets, off-lattice/time/group/cap rejection and legitimate 100,000,000-sample states. [Domain](signed-zero-evidence/checkpoint-domain.log), [original oracle](signed-zero-evidence/independent-probes.log), [numeric oracle](signed-zero-evidence/numeric-rereview-probes.log).

The installed `streamcontract.exe` also ran literal signed-zero JSONL with `number enum:[0,0.0], min:0, max:0`. All **7 cuts** (0 through 6) verify the exact input prefix and reproduce uninterrupted decisions/summary. Full/resume exit 2 correctly reports one declared late record. [Every-cut results](signed-zero-evidence/signed-zero-cli-results.json) and command arrays in [structured results](validation-results.json) retain actual exits and executable paths.

SDK checkpoint **1117 bytes**, full/resume equality true. Original actual CLI full/pause/resume/corrupt exits **2/0/2/3**, concatenated decisions equal and prefix verified. Eleven original demo records: accepted 9, invalid 1, late 1, windows 3, failed 1, finalized events 9. Seven synthetic contrasts all resume identically; main event-time drift 1 versus shape/processing-time/noaggregate 0. Removing disorder budget still produces 2 failures/1 late. [SDK](signed-zero-evidence/sdk.log), [CLI](signed-zero-evidence/cli-workflow.log), [comparison](signed-zero-evidence/benchmark.log).

The 10,000 offered-key cardinality case retains 16 groups and leaves sequence 17 unconsumed, observing **18,275 traced Python bytes / 0.0026284 seconds**. This tiny capped measurement is neither RSS nor production throughput or incumbent performance. The negative-zero repair adds no retained witness field. Candidate enumeration is at most **6,561** (`3**8`) per fully observed numeric group, independent of event count; type/enum restrictions often reduce it. Existing numeric witness and resource-cap behavior remains.

See [constructive numeric proof and primitive identity](NUMERIC_WITNESSES.md). v1/v2 still require replay; genuine v3 states remain supported under 0.2.1. Checks do not authenticate plausible history, arbitrary string-key preimages, upstream identity or sink receipts. No new passing independent score, customers/revenue or remote CI pass is claimed.
