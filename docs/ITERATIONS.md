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

Correction: checkpoint format v2 records `finalized_events`; restore requires exact conservation, a retained maximum-event window in unfinished state, counters consistent with finalized windows, field numeric bounds/integer values, and extrema that must actually be represented in the sum. v1 rejects. Verification command: rebuild wheel, force reinstall, run the complete suite and `examples/workflow.py`; observed 25 tests OK and identical uninterrupted/resumed decisions. After: recorded by the Round 1 commit (full SHA added in the next evidence entry).

Remaining boundary: unkeyed checksums do not prove producer identity or prevent a writer from fabricating a fully consistent history.
