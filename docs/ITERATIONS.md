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

The first failure is the pre-existing identity defect; the export test is the new supported path for intentionally revising configuration. Correction: slot-based immutable compiled attributes, read-only mapping proxies, immutable rule/field records and encoded immutable declaration; `to_dict()` yields a detached copy. Benchmark ablation now uses the public export API. Verification: rebuild/force-reinstall, all 30 tests, SDK workflow and six executable contrasts; observed all tests OK, full/resume equality and one drift failure versus zero in shape/arrival-time/no-aggregate baselines. After: `68bcb72719437b822db29454728eaed0ec637992`.

Remaining boundary: hostile code in the same Python process can use reflection to bypass ordinary object immutability. No in-process security sandbox is claimed.

## Additional round 4 — checkpoint write boundaries

Before: `68bcb72719437b822db29454728eaed0ec637992`. Final operational review found SDK checkpoint source metadata was validated only on restore, so an arbitrary raw-payload-like dictionary could be persisted (and then fail to restore). CLI also attempted checkpoint writes onto its input/contract without detecting aliases. On this Windows machine the open input replacement was blocked by the OS only after event output; on POSIX replacing an open pathname need not fail. The tool should reject configuration before any input processing.

Actual failing probe command: `.venv\Scripts\python.exe -m unittest discover -s tests -v` with the new metadata/path tests against the Round 3 wheel:

```text
ERROR: test_checkpoint_cannot_overwrite_input_or_contract
KeyError: 'code'  # first output was already an event, not the requested preflight rejection
FAIL: test_checkpoint_rejects_payload_like_source_metadata
AssertionError: CheckpointError not raised
Ran 32 tests in 2.286s
FAILED (failures=1, errors=1)
```

Correction: source metadata shape/sequence/digest checked before encoding or writing; CLI rejects resolved or hardlink checkpoint aliases of input/contract before opening input; contract file reads are also limited to 1 MiB + 1 byte. Verification rebuild/force reinstall and full suite: 33 tests OK, including hardlink alias/source byte preservation. After: `bc5222d832245d73372959884fe10146a04ea47a`. Remaining boundary: hostile concurrent path replacement is not an OS sandbox; append-only source and trusted checkpoint directory are required.

## Additional round 5 — remaining immutable/domain edges

Before: `bc5222d832245d73372959884fe10146a04ea47a`. Final API review found normal attribute deletion was not blocked by the assignment freeze; `del contract.size_ms` could invalidate a compiled contract. Checkpoint maximum time also used a generic integer range rather than the declared event-time field's own upper bound/enum. A rehashed state with max=100 and a declared event-time max=50 could therefore restore.

Reproduction: `.venv-clean\Scripts\python.exe -m unittest discover -s tests -p test_engine.py -v`, with the extended immutable test and new maximum-domain test against the fourth-round wheel. Actual output:

```text
FAIL: test_checkpoint_maximum_respects_event_time_field_domain
AssertionError: CheckpointError not raised
FAIL: test_compiled_contract_cannot_change_behind_digest
AssertionError: AttributeError not raised
Ran 26 tests in 0.033s
FAILED (failures=2)
```

Correction: compiled attributes reject deletion as well as assignment; restored maximum time must pass the compiled event-time field. After: `75ce3960585a2086fe32355f87f82a8a8530659a`. Rebuilt wheel/clean install verification observed 34 tests in 2.994s, OK; SDK and CLI full/resume equality and seven executed contrasts. [Final validation](VALIDATION.md) and [machine-readable results](validation-results.json) bind those observations to source digests. The report is a separate final evidence commit, so no commit attempts to embed its own hash. Plausible forged history and reflection remain outside the unkeyed integrity boundary.

## Round 6 — independent rejection of impossible checkpoint domains

Before: frozen `9ab3793e47330776dea6028a28a578818ca0b4c9`, package 0.1.0/wire 2. Independent scores were Commercial 83 / Technical 65 (raw 78, core cap) / Innovation 83, FAIL. The five original cycles above were independently reproduced as genuine; this new failure does not rewrite their history.

The unchanged external `reviews/streamcontract_checkpoint_domain_probe.py` has SHA-256 `7bb8407fea8bee358ca175c0b375bcd83ebd276598f7131fff632064370e5017`. We ran it against the reviewer's original installed 0.1.0 wheel and confirmed engine source matches frozen 9ab3793. Actual before: exit 1; all four `accepted_impossible_state` values true. Enum [100,200] replaced by 0 released a failed window; rational 1/3, arbitrary ungrouped digest and timestamp 99 in window [0,10) with maximum 1 also restored. This is a declared-domain impossibility defect, not a demand to authenticate plausible history. [Raw before evidence](repair-evidence/checkpoint-domain-before.json) preserves command/output/artifact binding.

Substantive correction: `moments.py` uses bounded enum frequencies and binary64 sign/binade integer-lattice witnesses to prove realizability. Proofs reconstruct count/sum/min/max, validate full primitive/enum/range domains and reserve both extrema before checking remaining sum. Integer fields use a direct lattice proof. Enum [0,2,5], n=3, min=0, max=5, sum=8 rejects even with legal extrema and convex bounds. Non-dyadic/unrepresentable extrema and off-lattice residual sums reject. Mandatory time moments enforce window/max/equality with time aggregates. Empty grouping uses its fixed digest; retained numeric grouping identities use at most 2**8 legal representations. New binary-layer overflow is transactional and bounded. There is no event-count expansion or subset-sum search.

Package 0.2.0/wire 3 rejects old formats lacking mandatory witnesses; replay is required. Supported field/enum/window semantics remain. Fifteen new tests cover impossible joint enum sums, illegal/duplicate/old/missing witnesses, exact number domains, subnormal/cancellation every-cut resume, numeric grouping/time identity, atomic layer caps, independent exhaustive enum/adjacent-float multisets and feasible 100,000,000-event enum/normal/subnormal/large-value aggregates.

Actual rebuilt noneditable wheel verification:

```text
unchanged checkpoint_domain_probe: exit 0; all four accepted_impossible_state=false
full suite: 49 tests in 3.121s, OK
unchanged independent probes: 6 tests in 2.199s, OK
40 streams / 3200 records / 160 resume comparisons, zero mismatches
SDK checkpoint 1117 bytes; full/resumed decisions and summary equal
CLI full/pause/resume/corrupt exits 2/0/2/3; concatenated decisions equal
seven contrasts resume equal; main event-time drift 1 vs shape/arrival/noaggregate 0
```

[Raw after evidence](repair-evidence/checkpoint-domain-after.json), [tests](repair-evidence/tests.log), [independent probes](repair-evidence/independent-probes.log), [current validation](VALIDATION.md) and [structured results](validation-results.json) preserve observations. After: `d107ebb9044dbf8df5bba5ae6edbc7d04fd6a4f2`. This evidence commit links that substantive correction; all recorded source digests match its committed library sources. Re-review of 0.2.0 is pending. Witnesses cover retained numeric/time realizability, not actual upstream history, authenticated string-key preimages or finalized receipts; plausible fully realizable hostile replacement still needs authentication/protected storage.

## Round 7 — genuine signed-zero grouping recovery

Before: frozen `8331d4107244b096298adc56bb071d4651fbff68`, package 0.2.0/wire 3. Independent re-review scores were Commercial 84 / Technical 65 (raw 88, core cap) / Innovation 84, FAIL. The six preceding cycles, including the corrected four impossible-state cases, were independently verified and remain historical. Round 6's `2**8` representation claim was incomplete for zero and is preserved above as the historical claim being corrected here.

The unchanged external `reviews/streamcontract_signed_zero_probe.py` has SHA-256 `69ea74ca52ddfc466608ff078c8d5b53cde2ac2a20d3021b9d707a95d584a294`. Before the source correction we ran it on the original installed 0.2.0 wheel, verifying both engine and moments source against frozen 8331d410. No checkpoint byte was altered. Actual output:

```text
Contract.validate({t:1,x:-0.0}): []
push: ACCEPTED / stage; genuine checkpoint_version: 3
genuine_checkpoint_restored: false
error: group digest differs from retained numeric grouping witness
exit: 1
```

[Raw before artifact/output](signed-zero-evidence/signed-zero-before.json) is preserved. Five new grouping tests ran against that same installed wheel: `-m unittest discover -s tests -p test_numeric_grouping.py -v`, 5 tests in 0.020s, FAILED (errors=19). The new CLI every-cut test ran with the original eight CLI tests: `-m unittest discover -s tests -p test_cli.py -v`, 9 tests in 3.680s, FAILED (failures=6). [Grouping before log](signed-zero-evidence/grouping-tests-before.log) and [CLI before log](signed-zero-evidence/cli-tests-before.log) record the actual failures; [exact captured text](signed-zero-evidence/before-tests.json) retains trailing whitespace omitted from the readable log copies. An additional rejection guard test was added after the correction.

Cause: rational moments map all zero signs/types to mathematical zero while JSON group hashing preserves `[0]`, `[0.0]` and `[-0.0]`. `input_candidates` offered only the first two. Substantive correction: enumerate `-0.0` when the exact value is zero and the declaration is `number`, then retain the existing `Field.check` type/range/typed-enum filter. The integer domain and float enum equality semantics are unchanged. No new state, wire field or payload copy is required. Numeric lattice/histogram math is unchanged. Current code/proof/complexity bounds now use the product of legal candidates, at most `3**8 = 6,561` for eight zero-valued number keys, rather than `2**8`.

Package 0.2.1 remains wire v3. Rebuilt wheel installed noneditable in `.venv-clean`; actual metadata is 0.2.1/SPDX MIT and import outside the checkout resolves to that environment's site-packages. Final verification:

```text
unchanged signed_zero_probe: before exit 1 -> after exit 0; genuine checkpoint bytes identical
full suite: 56 tests in 3.857s, OK (prior 49 + 7 representation/recovery tests)
unchanged four-domain probe: exit 0, all four impossible states rejected
unchanged original probes: 6 tests in 1.193s, OK; 40 streams/3200 records/160 resumes equal
unchanged numeric probes: 6 tests in 0.085s, OK; 55 enum/241 binary oracle cases retained
actual installed CLI signed-zero JSONL: all 7 cuts prefix-verified and decisions equal
SDK and original CLI workflow: equal; CLI exits 2/0/2/3
seven contrasts: all resume equal; main event-time drift 1 vs shape/processing/noaggregate 0
```

[Raw after](signed-zero-evidence/signed-zero-after.json), [full tests](signed-zero-evidence/tests.log), [actual CLI cuts](signed-zero-evidence/signed-zero-cli-results.json), [current validation](VALIDATION.md) and [structured results](validation-results.json) preserve actual commands/results/source digests. After: `4ee9553a068dd86196119f7106f2b1989082f146`. This evidence commit binds the correction; all five recorded library source hashes match the committed sources exactly. Independent re-review of 0.2.1 is pending; previous FAIL scores do not become PASS through this implementation report. Unkeyed checksums/realizability witnesses still do not authenticate actual histories or arbitrary string-key preimages.
