# Implementation and self-review evidence

Builder: GPT-6.1 SOL / Ultra. This history records implementation evidence, not independent scores. The initial complete SDK/CLI/package/docs/tests implementation is a separate baseline `106b8d7e4433e2d64e27d73e90e86dc394711a54` (22 tests passed, SDK workflow resume equality and six benchmark contrasts executed). All commands below run inside the repository on Windows / Python 3.14.3 with the **installed wheel**, never an editable installation. No remote CI result is claimed.

## Round 1 — accepted-event conservation during restore

Before: `106b8d7e4433e2d64e27d73e90e86dc394711a54`. Self-review of state invariants found that `active_events <= accepted` allowed a checkpoint with omitted active windows to restore after its unkeyed checksum was recalculated. Two related defects accepted moments outside the contract field range and a two-event sum inconsistent with its recorded extrema. These are impossible-state checks, not an attempt to authenticate forged plausible history.

Reproduction: add the three `test_checkpoint_*` adversarial cases, then run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_engine.py -v` against the baseline installed wheel. Actual output:

```text
FAIL: test_checkpoint_cannot_lose_accepted_active_events
AssertionError: CheckpointError not raised
FAIL: test_checkpoint_extrema_must_be_present_in_moments
AssertionError: CheckpointError not raised
FAIL: test_checkpoint_moments_respect_declared_field_domain
AssertionError: CheckpointError not raised
Ran 20 tests in 0.017s
FAILED (failures=3)
```

Correction: checkpoint format v2 records `finalized_events`; restore requires exact conservation, a retained maximum-event window in unfinished state, counters consistent with finalized windows, field numeric bounds/integer values, and extrema that must actually be represented in the sum. v1 rejects. Verification command: rebuild wheel, force reinstall, run the complete suite and `examples/workflow.py`; observed 25 tests OK and identical uninterrupted/resumed decisions. After: `20cd1849df27121409f14c2a98b6479b25e6c77c`.

Remaining boundary: unkeyed checksums do not prove producer identity or prevent a writer from fabricating a fully consistent history.

## Round 2 — large valid JSON integers must not crash ingestion

Before: `20cd1849df27121409f14c2a98b6479b25e6c77c`. Adversarial input review added a 1,000-digit integer, below the raw-byte cap and valid JSON. `math.isfinite(int)` attempted a float conversion before the numeric magnitude guard, raising OverflowError instead of consuming/quarantining the record. CLI exited 1 with a traceback and never processed the next valid record. A malformed SDK contract (`group_by: [{}]`) also escaped with TypeError instead of ContractError.

Reproduction command: `.venv\Scripts\python.exe -m unittest discover -s tests -v` with the new huge-integer and SDK malformed-contract probes against the Round 1 installed wheel. Actual output:

```text
ERROR: test_huge_integer_is_invalid_without_float_conversion
OverflowError: int too large to convert to float
ERROR: test_malformed_sdk_contracts_use_contract_error
TypeError: cannot use 'dict' as a set element (unhashable type: 'dict')
FAIL: test_huge_integer_emits_disposition_then_continues
AssertionError: 1 != 2
Ran 28 tests in 2.121s
FAILED (failures=1, errors=2)
```

Correction: magnitude comparison precedes float finiteness checking; integers never undergo the conversion. Validate group and aggregate field names before hash lookup, and normalize malformed constructor declarations to privacy-safe ContractError. Verification: rebuild/force-reinstall the wheel and rerun the full suite; observed 28 tests OK. The huge record now yields `INVALID/numeric_domain`, consumes exactly one sequence, and the next valid record continues normally. After: recorded by the Round 2 code commit (full SHA added next round).

Remaining boundary: the JSON parser's own digit/depth protections may classify even larger integers as `invalid_json`; both classifications are explicit quarantine dispositions.
