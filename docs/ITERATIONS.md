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

Correction: magnitude comparison precedes float finiteness checking; integers never undergo the conversion. Validate group and aggregate field names before hash lookup, and normalize malformed constructor declarations to privacy-safe ContractError. Verification: rebuild/force-reinstall the wheel and rerun the full suite; observed 28 tests OK. The huge record now yields `INVALID/numeric_domain`, consumes exactly one sequence, and the next valid record continues normally. After: `ef7aa82a5d1393de41c46d61794932f0d6dacbad`.

Remaining boundary: the JSON parser's own digit/depth protections may classify even larger integers as `invalid_json`; both classifications are explicit quarantine dispositions.

## Round 3 — immutable compiled contract identity

Before: `ef7aa82a5d1393de41c46d61794932f0d6dacbad`. SDK review found public `limits`/`fields` dictionaries and window attributes could be changed after the contract digest was calculated. A shared Contract could therefore change event acceptance/window assignment while writing checkpoints under its old identity. Caller input was already deep-copied, but the compiled object's own exposed configuration was mutable.

Reproduction: add `test_compiled_contract_cannot_change_behind_digest` and detached-export support test; run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_engine.py -v` against the Round 2 installed wheel. Actual output:

```text
FAIL: test_compiled_contract_cannot_change_behind_digest
AssertionError: TypeError not raised
ERROR: test_contract_export_is_detached
AttributeError: 'Contract' object has no attribute 'to_dict'
Ran 24 tests in 0.017s
FAILED (failures=1, errors=1)
```

The first failure is the pre-existing identity defect; the export test is the new supported path for intentionally revising configuration. Correction: slot-based immutable compiled attributes, read-only mapping proxies, immutable rule/field records and encoded immutable declaration; `to_dict()` yields a detached copy. Benchmark ablation now uses the public export API. Verification: rebuild/force-reinstall, all 30 tests, SDK workflow and six executable contrasts; observed all tests OK, full/resume equality and one drift failure versus zero in shape/arrival-time/no-aggregate baselines. After: recorded by the Round 3 code commit (full SHA added in the final evidence commit).

Remaining boundary: hostile code in the same Python process can use reflection to bypass ordinary object immutability. No in-process security sandbox is claimed.
