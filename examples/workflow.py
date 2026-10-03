"""SDK interruption/resume comparison. Run after installing the wheel."""

from pathlib import Path
import json

from streamcontract import Contract, Engine


def main():
    root = Path(__file__).resolve().parent
    contract = Contract.from_file(root / "contract.json")
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    full, split = Engine(contract), Engine(contract)
    full_decisions = [decision for event in events for decision in full.push(event)] + full.finish()
    first = [decision for event in events[:4] for decision in split.push(event)]
    checkpoint = split.checkpoint()
    resumed, _ = Engine.restore(contract, checkpoint, expected_sequence=4)
    split_decisions = first + [decision for event in events[4:] for decision in resumed.push(event)] + resumed.finish()
    assert full_decisions == split_decisions
    assert full.summary() == resumed.summary()
    assert b"synthetic-" not in checkpoint and b"checkout" not in checkpoint
    print(json.dumps({"resumed_equal": True, "checkpoint_bytes": len(checkpoint),
                      "summary": full.summary(), "windows": [d for d in full_decisions if d["kind"] == "window"]}, indent=2))


if __name__ == "__main__":
    main()
