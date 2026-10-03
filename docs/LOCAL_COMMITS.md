# Recoverable local output commits (0.3.0)

Use `--local-output NEW_DIRECTORY` or `process_local(contract, input_path,
directory)` when the output and checkpoint must share one local visibility
boundary. The original stdout/checkpoint mode keeps its disclosed independent
delivery boundary. This protocol uses one ordered file, one contract, one writer
and a trusted local directory. It supplies no broker/database transaction.

## Produce and consume

```sh
streamcontract --contract examples/contract.json --input examples/events.jsonl --local-output run-output/local --stop-after 4 --commit-every 2
streamcontract --contract examples/contract.json --input examples/events.jsonl --local-output run-output/local --commit-every 2
python examples/read_local.py --contract examples/contract.json --input examples/events.jsonl --local-output run-output/local
```

The fixture pause exits 0 and completion exits 2 because its data has issues.
Local mode stdout contains one `local_commit` receipt, rather than the decisions.
The separate consumer writes UTF-8 JSONL through binary stdout on every platform;
its exit 0 means the captured committed snapshot was read successfully. Inspect
the contained decisions/summary for validation outcomes. The SDK equivalent is:

```python
from streamcontract import Contract, process_local, read_committed

contract = Contract.from_file("examples/contract.json")
receipt = process_local(contract, "examples/events.jsonl", "run-output/local",
                        stop_after=4, commit_every=2)
cursor = 0
for row in read_committed("run-output/local", contract,
                          input_path="examples/events.jsonl", after_index=cursor):
    # Apply a row and persist row["index"] together in your own consumer transaction.
    cursor = row["index"]
```

Keep the consumer cursor and effects in the consumer's own transaction. A cursor
alone cannot make an arbitrary external side effect exactly-once. `after_index`
must be a nonnegative integer no greater than the captured committed row count.
For a new run/contract use a new directory. Input and contract files belong
outside that directory. Existing unrelated directories/files are rejected.
`--checkpoint`/`--resume` cannot be combined with local mode; it resumes its own
committed checkpoint automatically. SDK calls reject an input inside the bundle.

## One commit boundary

1. A new directory receives a version-1 `IDENTITY.json` with a random store ID
   and exact contract digest, plus an OS advisory `LOCK`. Process termination
   releases the lock. A second cooperating writer fails without advancing state.
2. A generation gets a unique `gORDINAL-UUID` name. Its `.outputs.jsonl` is written
   one bounded record at a time. Its `.checkpoint.json` is the original v3 engine
   checkpoint, including consumed source line count and exact prefix SHA-256.
3. Both files are flushed and fsynced. An immutable `.manifest.json` binds their
   names (implicit in its generation name), sizes, hashes, output count, total
   output count, source prefix, contract/store identity, parent commit, phase,
   summary and exit code. It is also flushed/fsynced.
4. A small version-1 `CURRENT.json` pointer is flushed/fsynced in a new temporary
   file, then atomically replaces the old pointer. This is the publication point.
   POSIX additionally fsyncs the directory. Portable Windows directory fsync is
   unavailable. No power-loss, storage-controller or network-filesystem
   durability guarantee is claimed on either platform.

Readers follow exactly one captured `CURRENT.json` and its immutable ancestors.
They never glob stage files as output. A crash before pointer replacement leaves
the old committed state visible; the next writer replays only the uncommitted
source suffix. A crash after replacement exposes the new output **and** state.
Generation names are create-only, so abandoned files are never overwritten.
Hashes and complete chain counts are checked before any row is yielded. Reading
uses a validation pass followed by a streaming pass over the same snapshot;
trusted committed files must stay immutable throughout both passes.

Each row is `{version: 1, index, output_id, decision}`. `index` is a strictly
increasing bundle-wide position. `output_id` is SHA-256 of canonical
`[store_id, index, decision]`. This separates multiple window reports at the same
event sequence and EOF reports at that sequence. Replayed uncommitted work has
the same IDs within its surviving bundle. A different store is a different run;
random namespace/generation names do not change deterministic engine decisions.

Pauses contain event/window decisions but no intermediate summary row; progress
is available in the manifest/receipt. EOF publishes remaining windows and **one**
terminal summary with a finished v3 checkpoint. Reopening a finished bundle first
verifies its source prefix and returns its existing receipt without publishing
again. Appending input to a finished bundle does not reopen EOF: use a new run.
A resource stop publishes the prior consumed prefix, one unconsumed-event error
and one summary; subsequent calls return that stop receipt. The same immutable
contract cannot remedy that limit, so replay into a new bundle under an explicit
revised contract. A checkpoint-size failure during commit leaves the previous
pointer unchanged. An IO error after publication can occur with the new pointer
already visible; read/reopen the bundle to determine its committed state.

## Validation, bounds and cost

Local metadata is capped at 65,536 bytes; each output JSONL record, including its
newline, at 262,144 bytes. Current declarations have at most 64 fields with
100-character names and 32 checks with 100-character names, so complete engine
evidence fits this record budget without dropping traces. Producer and consumer
reject duplicate JSON keys, BOMs, malformed UTF-8, NaN/Infinity, overflow to
infinity, lone surrogates, oversized/truncated lines, extra envelope fields,
wrong typed identities/counts, sequence disorder, duplicate/reordered rows,
missing terminal summaries, foreign generations and file/hash/count mismatch.
The engine's existing bounded raw parser is reused unchanged for **input**;
invalid/oversized input still consumes a quarantine decision, not a silent drop.

Every historical checkpoint is bound by byte hash, its own envelope hash, source
position and derived summary. The latest checkpoint additionally goes through
the complete unchanged `Engine.restore` v3 numeric/time realizability checks.
Output integrity/order is checked; payload-free output cannot independently
reconstruct every input aggregate or authenticate a plausible replacement
history. Providing `input_path` checks the actual consumed prefix; omitting it
checks only the stored binding. Source bytes are neither locked nor snapshotted;
concurrent rewrites after verification are unsupported. No raw event/path is
written into the commit metadata or output.

Let G be the committed generation count, S the bounded engine/checkpoint state,
B the input record budget, and D the engine's bounded list of decisions produced
by one push/finish. Production uses O(S + B + D + one output record) memory, not
all historical decisions. A checkpoint serialization temporarily duplicates S.
`commit_every` is 1..1,000,000 new records (default 64); it controls checkpoint and
fsync frequency, not an output omission/sample limit. Resume/consumer validate
O(history bytes + source prefix bytes), retain O(G) small manifest/chain metadata
plus O(S + B + one output record), and do not re-enumerate old numeric groups for
each ancestor. The latest v3 restore retains its existing at-most-6,561 numeric
group representation candidates. These are structural bounds, not a total RSS
cap or a constant-memory claim.

Disk use includes every committed output and checkpoint generation and any
abandoned stage files. There is no automatic pruning/compaction or disk quota.
Never remove an ancestor needed by CURRENT or an active reader. Retain/remove a
whole quiescent bundle according to your policy, and reserve space for the
selected checkpoint cadence. A no-op pause creates no new files; a pause exactly
at a batch boundary reuses that batch's commit instead of duplicating its state.
Monitor disk capacity and treat local IO failures as operational failures.

## Reproducible checks

`python -m unittest discover -s tests -v` covers the original engine invariants and
local commits. `python -I probes/verify_local_workflow.py --work NEW_DIRECTORY`
runs all 12 cuts of the 11-record fixture through the actual installed console
and separate binary consumer, compares full decisions with uninterrupted legacy
stdout, and measures 500/5,000-record SDK production/consumption against an
independent uninterrupted engine digest. The test suite kills real child writers
at record write, output/checkpoint fsync, manifest fsync, before/after pointer
publication, directory fsync and terminal publication. These tests exercise
process interruption and visibility, never simulate a hardware power cut.
See [the update iterations](UPDATE_20261003.md) for actual repairs and evidence
scope. No old audit score is evidence that this new protocol passed review.
