# Security and evidence handling

No raw event or grouping value is retained or included in output. Event error evidence contains declared field names and reason codes; extra unknown names are suppressed. Reports contain numeric aggregates, counts, timestamps, sequence IDs, contract digest and stable group hashes. These can still reveal sensitive facts, particularly a singleton or a low-entropy grouping key. SHA-256 is **not anonymization**: known keys can be guessed. Apply access controls, aggregate disclosure policy and retention limits; choose grouping fields deliberately. This is payload minimization, not a general privacy guarantee or differential privacy.

A checkpoint SHA-256 checksum is public and unkeyed. Anyone with write access can forge a checksum and consistent state. Invariant checks catch impossible state, not all forged plausible histories. Protect checkpoint/input directories, and authenticate or sign envelopes externally if adversarial tampering is in scope. Do not treat digest equality as producer identity or authorization. The input file is not snapshotted or locked; concurrent rewrites after prefix verification are outside the supported append-only workflow.

Wire v3 proves retained numeric aggregate realizability using enum frequencies and binary precision-layer statistics, and checks independent event-time/window evidence. These extra statistics are still sensitive aggregates and can disclose distribution or singleton values. They are bounded and do not retain event objects or string keys. This stronger domain validation does not authenticate a plausible replacement history or arbitrary hashed string-key preimages.

Bounded raw reading, field/contract limits, numeric domain checks and active-state caps reduce memory hazards. Very large configured caps still consume substantial memory. No OS sandbox, encrypted checkpoint or isolation from a compromised Python process is supplied. Do not execute untrusted plugin code; no plugin/SQL execution is needed here.

The opt-in local commit directory contains sensitive aggregate evidence and all
historical checkpoint/output generations. Its public unkeyed hashes and stable
row IDs are integrity/binding aids, not authorization or anonymity. Protect the
directory and source from hostile writers; committed files must remain immutable
while a reader validates then streams its captured snapshot. One cooperating
writer holds an OS lock; this does not stop a hostile process bypassing it.
Consumers follow CURRENT and manifests, never uncommitted stage files. No raw
payload/path is added to the protocol. Invalid/oversized input retains the same
quarantine behavior as the original CLI. Finite record/metadata limits and v3
state validation remain enforced, but history has O(generations) reader metadata
and retained disk cost. Reserve space and manage whole-bundle retention; no
automatic pruning or quota is provided. Atomic commit visibility does not prove
power-loss durability, and no broker/database/external consumer transaction is
supplied. The source is not locked/snapshotted; its verified prefix is trusted
after the check. See [local protocol details](docs/LOCAL_COMMITS.md).

Report a suspected issue privately to the repository maintainer using GitHub's private vulnerability reporting if enabled; otherwise request a private contact without posting payloads or secrets. Include version, a small synthetic reproducer, expected action and observed output. Availability of a hosted reporting channel is unknown until the repository is published.
