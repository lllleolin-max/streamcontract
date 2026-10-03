# Repaired 0.2.0 evidence · 2026-10-03

Frozen 0.1.0 commit `9ab3793e47330776dea6028a28a578818ca0b4c9` received independent 83/65/83 and FAIL for impossible checkpoint states. [Original observations](VALIDATION_0.1.0.md) and [result archive](validation-results-0.1.0.json) remain historical evidence. Package 0.2.0/wire 3 is substantively repaired and awaits re-review. Correction commit `d107ebb9044dbf8df5bba5ae6edbc7d04fd6a4f2` contains the identical sources tested immediately before that commit; [structured results](validation-results.json) bind observations to source digests.

Windows 11 / CPython 3.14.3. Rebuilt wheel installed noneditable in `.venv-clean`; import from system temporary directory resolves to site-packages, version 0.2.0, SPDX MIT. No editable install or `PYTHONPATH=src`. Python 3.11 and remote CI runtime results remain unknown; CI targets Ubuntu/Windows × Python 3.11/3.14.

Actual commands from the repository:

```powershell
.venv\Scripts\python.exe -m build --wheel
.venv-clean\Scripts\python.exe -m pip install --force-reinstall --no-deps dist\streamcontract-0.2.0-py3-none-any.whl
.venv-clean\Scripts\python.exe -m unittest discover -s tests -v
.venv-clean\Scripts\python.exe ../reviews/streamcontract_checkpoint_domain_probe.py
.venv-clean\Scripts\python.exe ../reviews/streamcontract_independent_probes.py
.venv-clean\Scripts\python.exe examples/workflow.py
.venv-clean\Scripts\python.exe examples/cli_workflow.py
.venv-clean\Scripts\python.exe benchmarks/compare.py
.venv-clean\Scripts\streamcontract.exe --contract examples/contract.json --input examples/events.jsonl
```

External reviewer scripts ran unchanged; portable regression/oracle tests are included in `tests/`. **49 tests in 3.121s, OK**, original 34 plus 15 domain/witness tests. Unchanged independent probes: **6 tests in 2.199s, OK**; 40 streams / 3200 records / 160 resume comparisons, zero mismatches.

The same domain script SHA-256 `7bb8407fea8bee358ca175c0b375bcd83ebd276598f7131fff632064370e5017` ran on frozen-wheel 0.1.0 (engine source matched 9ab3793) and repaired 0.2.0: **exit 1/all four impossible states accepted → exit 0/all four rejected**. [Before](repair-evidence/checkpoint-domain-before.json) and [after](repair-evidence/checkpoint-domain-after.json) retain actual outputs. The genuine enum 100 checkpoint still FAILs; replacement 0 cannot release.

New proof tests reject enum [0,2,5], n=3/min=0/max=5/sum=8, illegal frequencies, missing/duplicate/v2 witnesses, an unrepresentable dyadic scalar and an off-binade-lattice sum. Independent exhaustive enum/adjacent-float multisets check acceptance/rejection. Feasible 100,000,000-event enum and binary witnesses (0.1, smallest subnormal, 1e15) restore without expanding events. Exact subnormal/cancellation cases preserve every resume cut; layer overflow preserves checkpoint bytes and sequence.

SDK checkpoint **1117 bytes**, full/resume equality true, no raw request/service strings. Actual CLI full/pause/resume/corrupt exits **2/0/2/3**; prefix verified, concatenated decisions equal. Eleven records: accepted 9, invalid 1, late 1, finalized windows 3, failed 1, finalized events 9. Exit 2 is expected quarantine behavior.

Seven synthetic contrasts retain their decisions: main event-time drift 1, batch shape 0, processing time 0, no aggregate 0; removing disorder budget yields 2 failures/1 late. Clean, empty, half-open boundary, too-small budget, after-close and invalid-future cases run; every scenario resumes identically. Soda/Flink executables were not run. [Comparison output](repair-evidence/benchmark.log) contains all results.

High-cardinality stop retains 16 groups, leaves sequence 17 unconsumed out of 10,000 offered keys. Repaired state observed **18,275 traced Python bytes / 0.0014633 seconds** in this tiny capped run; historical 0.1.0 observed 8,595 bytes. Bounded witnesses cost memory; neither figure is RSS or a production throughput estimate. Measurements are not inherited across versions.

See [numeric proof](NUMERIC_WITNESSES.md) and [iterations](ITERATIONS.md). Checks do not authenticate plausible histories, arbitrary string-key preimages, upstream identity or sink receipts. No customer/revenue/validated willingness-to-pay or new passing independent score is claimed.
