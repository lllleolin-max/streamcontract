"""JSONL CLI; checkpoints bind the consumed source prefix, not just its path."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from .contract import Contract, ContractError, canonical, strict_json
from .engine import CheckpointError, Engine, ResourceLimit, SequenceError


def records(file, cap: int):
    """Yield bounded raw record and incremental digest state, including newline."""
    digest = hashlib.sha256()
    while True:
        raw = file.readline(cap + 1)
        if not raw:
            break
        digest.update(raw)
        oversized = len(raw) > cap
        if not raw.endswith(b"\n"):
            while raw and not raw.endswith(b"\n") and oversized:
                raw = file.readline(cap + 1)
                digest.update(raw)
            if oversized:
                raw = None
        yield None if oversized else raw, digest.copy()


def emit(value: dict) -> None:
    sys.stdout.buffer.write(canonical(value) + b"\n")
    sys.stdout.buffer.flush()


def run(args) -> int:
    if args.local_output:
        from .local import process_local
        root = Path(args.local_output).resolve()
        for protected in (Path(args.input).resolve(), Path(args.contract).resolve()):
            if protected == root or root in protected.parents:
                raise CheckpointError("input and contract must be outside local output directory")
        receipt = process_local(Contract.from_file(args.contract), args.input, args.local_output,
                                stop_after=args.stop_after, commit_every=args.commit_every)
        emit(receipt)
        return receipt["exit_code"]
    if args.checkpoint:
        destination = Path(args.checkpoint).resolve()
        for protected in (Path(args.input).resolve(), Path(args.contract).resolve()):
            if destination == protected or (destination.exists() and protected.exists() and os.path.samefile(destination, protected)):
                raise CheckpointError("checkpoint aliases input or contract")
    contract = Contract.from_file(args.contract)
    engine, source = Engine(contract), None
    if args.resume:
        with Path(args.resume).open("rb") as file:
            raw = file.read(contract.limits["max_checkpoint_bytes"] + 1)
        engine, source = Engine.restore(contract, raw)
        if source is None or engine.finished:
            raise CheckpointError("CLI requires unfinished checkpoint with source position")
    digest = hashlib.sha256()
    with Path(args.input).open("rb") as file:
        iterator = iter(records(file, contract.limits["max_event_bytes"]))
        if source:
            for _ in range(source["lines"]):
                try:
                    _, digest = next(iterator)
                except StopIteration as exc:
                    raise CheckpointError("source shorter than checkpoint prefix") from exc
            if digest.hexdigest() != source["prefix_sha256"]:
                raise CheckpointError("source prefix mismatch")
        consumed = 0
        for raw, next_digest in iterator:
            if args.stop_after is not None and consumed >= args.stop_after:
                break
            try:
                if raw is None:
                    decisions = engine.reject("event_bytes_limit")
                else:
                    try:
                        event = strict_json(raw)
                    except UnicodeDecodeError:
                        decisions = engine.reject("invalid_utf8")
                    except (ValueError, RecursionError, OverflowError):
                        decisions = engine.reject("invalid_json")
                    else:
                        decisions = engine.push(event)
            except ResourceLimit as exc:
                if args.checkpoint:
                    engine.save(args.checkpoint, {"lines": engine.sequence, "prefix_sha256": digest.hexdigest()})
                emit({"kind": "error", "status": "RESOURCE_LIMIT", "action": "stop",
                      "limit": exc.limit, "next_sequence": exc.sequence, "consumed": False})
                emit(engine.summary())
                return 3
            for decision in decisions:
                emit(decision)
            digest = next_digest
            consumed += 1
        if args.stop_after is None:
            for decision in engine.finish():
                emit(decision)
        if args.checkpoint:
            engine.save(args.checkpoint, {"lines": engine.sequence, "prefix_sha256": digest.hexdigest()})
        summary = engine.summary()
        emit(summary)
        return 2 if summary["status"] in {"EMPTY", "ISSUES"} else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded event-time JSONL contract checks")
    parser.add_argument("--contract", required=True, help="contract JSON")
    parser.add_argument("--input", required=True, help="JSONL file; resume verifies consumed prefix")
    parser.add_argument("--checkpoint", help="atomic checkpoint destination")
    parser.add_argument("--resume", help="unfinished checkpoint to restore")
    parser.add_argument("--stop-after", type=int, help="pause after this many NEW records, without EOF finalization")
    parser.add_argument("--local-output", help="opt-in single-writer local committed output directory; auto-resume")
    parser.add_argument("--commit-every", type=int, default=64, help="local commit batch size, 1..1000000 (default 64)")
    args = parser.parse_args(argv)
    if args.stop_after is not None and args.stop_after < 0:
        parser.error("--stop-after must be nonnegative")
    if args.local_output and (args.checkpoint or args.resume):
        parser.error("--local-output contains its own checkpoint; do not combine --checkpoint/--resume")
    if not 1 <= args.commit_every <= 1000000:
        parser.error("--commit-every must be in 1..1000000")
    try:
        return run(args)
    except (ContractError, CheckpointError, SequenceError, OSError, ResourceLimit) as exc:
        # Do not echo source paths or parser text containing payloads.
        emit({"kind": "error", "status": type(exc).__name__, "action": "stop",
              "code": "io_error" if isinstance(exc, OSError) else str(exc)})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
