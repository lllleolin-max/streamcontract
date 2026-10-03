# Historical 0.1.0 observations · 2026-10-03

This artifact later received independent 83/65/83 and FAIL because restore accepted four impossible domain states. Original passing tests did not establish acceptance; current repaired evidence is in [VALIDATION.md](VALIDATION.md).

Implementation source commit: `75ce3960585a2086fe32355f87f82a8a8530659a`. The tests were run on its identical working-tree source immediately before that commit; the final evidence commit additionally records the CLI demonstration, assertion-bearing benchmark, README/CI additions and this report. [Machine-readable observed results](validation-results.json) record source digests, command arguments, actual exit codes, output summaries and benchmark measurements. These are builder observations; independent evaluation and remote CI remain pending.

Environment: Windows 11 / Python 3.14.3, Git 2.55.0. Only Python 3.14 is installed locally. Declared Python 3.11 compatibility is covered by CI configuration but its runtime execution is not locally verified. No editable install or `PYTHONPATH=src` was used.

Commands actually executed from the repository:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip build
.venv\Scripts\python.exe -m build --wheel
py -3 -m venv .venv-clean
.venv-clean\Scripts\python.exe -m pip install --no-deps dist\streamcontract-0.1.0-py3-none-any.whl
.venv-clean\Scripts\python.exe -m unittest discover -s tests -v
.venv-clean\Scripts\python.exe examples\workflow.py
.venv-clean\Scripts\python.exe examples\cli_workflow.py
.venv-clean\Scripts\python.exe benchmarks\compare.py
.venv-clean\Scripts\streamcontract.exe --contract examples/contract.json --input examples/events.jsonl
```

Wheel rebuilds after changes were installed with `--force-reinstall --no-deps`. Import was also executed from the system temporary directory, outside the checkout; module resolved to `.venv-clean/Lib/site-packages/streamcontract/__init__.py`. Distribution `License-Expression` was MIT. Clean environment full suite: **34 tests, 2.994 seconds, OK**. No runtime dependencies were installed with the wheel.

The tests validate time boundaries, invalid-record isolation, every resume cut, exact independent list/rational aggregate oracle, extrema/domain/event conservation, impossible and checksum-damaged state, strict SDK contracts, huge integer/malformed JSON/UTF-8 records, resource atomicity, bounded high cardinality, source mutation and hardlink/path preservation. Passing tests do not certify arbitrary checkpoints as authentic.

SDK workflow: all decisions and summaries equal between uninterrupted input and a checkpoint at sequence 4; checkpoint 752 bytes with no raw request IDs or service value. CLI workflow: full=2, pause=0, resume=2, corrupted checkpoint=3; source prefix verified; concatenated decisions equal. Final 11-record fixture: accepted=9, invalid=1, late=1, group-windows=3, failed=1, insufficient=0, finalized_events=9. Two windows release; one drift window quarantines. The exit 2 is the expected contract result, not an execution failure.

Actual executable comparison (synthetic; Soda/Flink not executed):

| Scenario | Batch shape invalid | Processing-time failed windows | Event-time failed windows / late | No aggregate failed windows | No disorder budget failed / late |
|---|---:|---:|---:|---:|---:|
| Drift hidden by interleaved arrivals | 0 | 0 | 1 / 0 | 0 | 2 / 1 |
| Clean bounded disorder | 0 | 0 | 0 / 0 | 0 | 1 / 1 |
| Too small disorder budget (adverse) | 0 | 0 | 0 / 0 | 0 | 1 / 1 |
| Event after window closure | 0 | 0 | 1 / 1 | 1 | 1 / 1 |
| Empty | 0 | 0 | 0 / 0, EMPTY | 0 | 0 / 0 |
| Exact half-open boundary | 0 | 0 | 0 / 0 | 0 | 1 / 1 |
| Invalid future row | 1 | 0 | 0 / 0, ISSUES | 0 | 0 / 0 |

All seven cases had full/resumed equivalence. High-cardinality stream offered 10,000 distinct keys: consumed=16, next sequence=17 unconsumed, active groups=16; local traced Python peak allocation **8,595 bytes**, wall time **0.000799 seconds** in this small cap exercise. These measurements are neither total process memory nor a throughput forecast. Row-only/processing-time checks miss the main drift while the mechanism ablation removes it. Poor time budgets cause false quarantine relative to the intended grouping; this is shown, not hidden.

Five real correction commits after the complete initial implementation are listed in [ITERATIONS.md](ITERATIONS.md). The first three satisfy the required code-change cycles; later two close further findings. No customer, willingness-to-pay, revenue, public repository or independently passing score is claimed.
