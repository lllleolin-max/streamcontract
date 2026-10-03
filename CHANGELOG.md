# Changelog

## 0.3.0

- Add opt-in single-writer local output/checkpoint commit generations with an
  atomic visibility pointer, verified source-prefix recovery, stable per-row IDs
  and a bounded streaming consumer. Publish EOF/resource-stop reports once within
  the bundle and preserve complete engine decisions.
- Keep the existing stdout/checkpoint workflow and v3 numerical/time proof.
- Reject malformed or foreign local metadata, corrupt/truncated outputs and
  source mismatch; avoid stage files on no-op pauses and duplicate checkpoints
  at exact batch pause boundaries.
- Add installed SDK/binary consumer examples, real killed-process recovery tests
  and a create-only console/scale verification helper. This local protocol does
  not transact with an external sink or claim hardware power-loss durability.

## 0.2.1 (historical)

Preserved signed-zero numeric grouping recovery and typed/domain checkpoint
repairs. Historical release/review evidence remains separate from 0.3.0.
