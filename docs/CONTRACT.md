# Contract v1

The supported format is JSON, not Soda/OCDS/JSON Schema syntax. No nested fields, nullability, joins, percentiles, regex execution, learned baselines or sliding windows are implemented. A malformed contract stops before consuming input. The identity digest binds the exact JSON object (object key order ignored); even semantically equivalent explicit defaults currently produce a different identity.

Required top-level keys: `version: 1`, `event_time`, `fields`, `window`, `checks`. Optional `group_by` and `limits`. All unknown keys reject. Declared field names must be 1..100 characters; 1..64 fields, up to 8 grouping fields, 1..32 checks.

| Component | Options and defaults |
|---|---|
| Field | `type`: string/integer/number/boolean; `required: true`; `min`, `max` numeric inclusive; `max_length: 1024`; `enum`: 1..256 primitive values |
| Event time | Required integer field, nonnegative epoch milliseconds; numeric domain also requires abs <= 1e15 |
| Group | Declared required field tuple, SHA-256 of canonical primitive list; no raw key retained |
| Window | `size_ms > 0`; `watermark_delay_ms: 0`; `allowed_lateness_ms: 0`; integer milliseconds |
| Check | Unique `name`, `op`: count/sum/mean/min/max; numeric required `field` except count; optional inclusive `min`, `max`; paired `reference` and `max_absolute_delta >= 0`; `min_samples: 1` |

All numeric event values and threshold/reference values must be finite, abs <= 1e15. Strings are measured in Unicode characters; raw JSONL bytes are bounded separately. Field enums distinguish primitive types. Missing optional fields are permitted; optional fields cannot be aggregation or grouping keys. Extra event fields yield `INVALID/unexpected_fields` without echoing their names or values. Blank lines count as invalid records. Duplicate JSON keys and NaN/Infinity reject. Each newline-delimited record counts exactly once, including invalid records. The final line need not have a newline.

| Limit | Default | On exceed |
|---|---:|---|
| `max_active_windows` | 32 | stop before consuming next valid event |
| `max_groups_per_window` | 128 | stop before consuming new group |
| `max_events_per_group` | 1,000,000 | stop before consuming next group event |
| `max_event_bytes` | 65,536 | consume and quarantine oversized record |
| `max_checkpoint_bytes` | 16,777,216 | reject oversized save/restore |

Limit values are integers 1..100,000,000; they are configuration bounds, not a promise that the machine has that much memory. Select small realistic limits and filesystem quotas. No raw records are buffered awaiting closure. Window-count checks use the prospective watermark, so an event can close an old window and open a new one without being incorrectly blocked at a full bound.

`checks[].expected` in output reproduces thresholds, reference and minimum samples. A failure reports `below_minimum`, `above_maximum` and/or `aggregate_drift`. `INSUFFICIENT` means too few accepted samples for that rule. A FAIL takes precedence over insufficiency in the same window. `sum` and other statistics are over accepted records only. A passing observed window does not cancel independent invalid/late quarantine outputs.

SDK `push(event, sequence=n)` enforces the exact next sequence; omission automatically uses the next sequence. SDK parser rejection is `reject(code)` with a fixed allowed code set. SDK `restore` returns `(engine, source_metadata)`; callers are responsible for validating their own upstream cursor if they do not use the CLI's source-prefix protocol. `save(path, source)` atomically replaces the checkpoint; `checkpoint(source)` returns encoded bytes. `finish()` declares EOF once and prevents future pushes. Compiled Contract objects are immutable, including fields/limits mappings; `to_dict()` returns a detached declaration to build a new contract with a new identity.
