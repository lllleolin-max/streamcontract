"""Bounded, deterministic event-time aggregation and checkpoint state machine."""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from .contract import Contract, ContractError, MAX_NUMBER, MAX_TIME, canonical, strict_json


class SequenceError(ValueError):
    """Caller sequence differs from next consumed sequence."""


class ResourceLimit(RuntimeError):
    """Event was NOT consumed; checkpoint and retry the same sequence."""

    def __init__(self, limit: str, sequence: int):
        self.limit, self.sequence = limit, sequence
        super().__init__(f"{limit} reached; event {sequence} not consumed")


class CheckpointError(ValueError):
    """Invalid, incompatible, oversized or corrupt checkpoint."""


@dataclass
class Moments:
    total: Fraction
    minimum: Fraction
    maximum: Fraction

    def add(self, value: Fraction) -> None:
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)


@dataclass
class Bucket:
    count: int = 0
    values: dict[str, Moments] = field(default_factory=dict)

    def add(self, event: dict, names: tuple[str, ...]) -> None:
        self.count += 1
        for name in names:
            value = Fraction(event[name])
            if name in self.values:
                self.values[name].add(value)
            else:
                self.values[name] = Moments(value, value, value)


def rational(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def read_rational(value: Any) -> Fraction:
    if type(value) is not list or len(value) != 2 or any(type(x) is not int for x in value):
        raise CheckpointError("invalid rational state")
    if abs(value[0]).bit_length() > 1200 or not 0 < value[1] <= 2**1074:
        raise CheckpointError("rational state exceeds numeric domain")
    result = Fraction(*value)
    if rational(result) != value:
        raise CheckpointError("noncanonical rational state")
    return result


class Engine:
    """Single ordered input lane; caller owns partition merge and downstream delivery.

    push returns event disposition followed by any newly finalized windows.
    Accepted event timestamp is checked against the previous watermark, then
    max timestamp and watermark advance. Finalization occurs at end+lateness.
    """

    def __init__(self, contract: Contract):
        self.contract = contract
        self.sequence = 0
        self.max_event_time: int | None = None
        self.watermark: int | None = None
        self.windows: dict[int, dict[str, Bucket]] = {}
        self.finished = False
        self.stats = {k: 0 for k in ("accepted", "invalid", "late", "windows", "failed", "insufficient")}

    def _sequence(self, sequence: int | None) -> int:
        wanted = self.sequence + 1
        if sequence is not None and (type(sequence) is not int or sequence != wanted):
            raise SequenceError(f"expected sequence {wanted}")
        if self.finished:
            raise SequenceError("stream is finished")
        if wanted > MAX_TIME:
            raise ResourceLimit("max_sequence", wanted)
        return wanted

    def reject(self, code: str, *, sequence: int | None = None) -> list[dict]:
        """Consume one parser-invalid record without storing its bytes."""
        seq = self._sequence(sequence)
        if code not in {"invalid_json", "event_bytes_limit", "invalid_utf8"}:
            raise ValueError("unsupported parser rejection code")
        self.sequence = seq
        self.stats["invalid"] += 1
        return [{"kind": "event", "sequence": seq, "status": "INVALID", "action": "quarantine",
                 "evidence": [{"code": code}]}]

    def push(self, event: Any, *, sequence: int | None = None) -> list[dict]:
        seq = self._sequence(sequence)
        reasons = self.contract.validate(event)
        if not reasons:
            try:
                if len(canonical(event)) > self.contract.limits["max_event_bytes"]:
                    reasons = [{"code": "event_bytes_limit"}]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                reasons = [{"code": "invalid_json"}]
        if reasons:
            self.sequence = seq
            self.stats["invalid"] += 1
            return [{"kind": "event", "sequence": seq, "status": "INVALID", "action": "quarantine", "evidence": reasons}]
        timestamp = event[self.contract.event_time]
        start = timestamp // self.contract.size_ms * self.contract.size_ms
        end = start + self.contract.size_ms
        deadline = end + self.contract.lateness_ms
        if self.watermark is not None and self.watermark >= deadline:
            self.sequence = seq
            self.stats["late"] += 1
            return [{"kind": "event", "sequence": seq, "status": "LATE", "action": "quarantine",
                     "evidence": [{"code": "window_finalized", "start_ms": start, "end_ms": end,
                                   "deadline_ms": deadline, "watermark_ms": self.watermark}]}]
        group = hashlib.sha256(canonical([event[g] for g in self.contract.group_by])).hexdigest()
        candidate_max = timestamp if self.max_event_time is None else max(timestamp, self.max_event_time)
        candidate_watermark = candidate_max - self.contract.delay_ms
        # Preflight after prospective finalization; no state/sequence mutation on limits.
        retained = {s for s in self.windows if s + self.contract.size_ms + self.contract.lateness_ms > candidate_watermark}
        if start not in retained and len(retained) >= self.contract.limits["max_active_windows"]:
            raise ResourceLimit("max_active_windows", seq)
        groups = self.windows.get(start, {})
        if group not in groups and len(groups) >= self.contract.limits["max_groups_per_window"]:
            raise ResourceLimit("max_groups_per_window", seq)
        if group in groups and groups[group].count >= self.contract.limits["max_events_per_group"]:
            raise ResourceLimit("max_events_per_group", seq)
        out = [{"kind": "event", "sequence": seq, "status": "ACCEPTED", "action": "stage",
                "evidence": [{"code": "window_assignment", "start_ms": start, "end_ms": end,
                              "group_sha256": group,
                              "behind_watermark": self.watermark is not None and timestamp < self.watermark}]}]
        self.sequence = seq
        self.stats["accepted"] += 1
        self.windows.setdefault(start, {}).setdefault(group, Bucket()).add(event, self.contract.numeric_fields)
        self.max_event_time, self.watermark = candidate_max, candidate_watermark
        out.extend(self._close(candidate_watermark, "watermark"))
        return out

    def _evaluate(self, start: int, group: str, bucket: Bucket, trigger: str) -> dict:
        checks = []
        for rule in self.contract.rules:
            if rule.op == "count":
                value = Fraction(bucket.count)
            else:
                moments = bucket.values[rule.field]
                value = {"sum": moments.total, "mean": moments.total / bucket.count,
                         "min": moments.minimum, "max": moments.maximum}[rule.op]
            sufficient = bucket.count >= rule.min_samples
            failures = []
            if sufficient:
                if rule.minimum is not None and value < Fraction(rule.minimum):
                    failures.append("below_minimum")
                if rule.maximum is not None and value > Fraction(rule.maximum):
                    failures.append("above_maximum")
                if rule.reference is not None and abs(value - Fraction(rule.reference)) > Fraction(rule.max_absolute_delta):
                    failures.append("aggregate_drift")
            checks.append({"name": rule.name, "op": rule.op, "observed": float(value),
                           "status": "INSUFFICIENT" if not sufficient else "FAIL" if failures else "PASS",
                           "reasons": failures, "sample_count": bucket.count,
                           "expected": {"min": rule.minimum, "max": rule.maximum, "reference": rule.reference,
                                        "max_absolute_delta": rule.max_absolute_delta, "min_samples": rule.min_samples}})
        status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "INSUFFICIENT" if any(c["status"] == "INSUFFICIENT" for c in checks) else "PASS"
        self.stats["windows"] += 1
        self.stats["failed"] += status == "FAIL"
        self.stats["insufficient"] += status == "INSUFFICIENT"
        return {"kind": "window", "sequence": self.sequence, "status": status,
                "action": "release" if status == "PASS" else "quarantine" if status == "FAIL" else "investigate",
                "evidence": {"start_ms": start, "end_ms": start + self.contract.size_ms,
                             "group_sha256": group, "trigger": trigger, "watermark_ms": self.watermark,
                             "sample_count": bucket.count, "checks": checks}}

    def _close(self, watermark: int | None, trigger: str) -> list[dict]:
        out = []
        closed = sorted(s for s in self.windows if watermark is None or s + self.contract.size_ms + self.contract.lateness_ms <= watermark)
        for start in closed:
            groups = self.windows.pop(start)
            for group in sorted(groups):
                out.append(self._evaluate(start, group, groups[group], trigger))
        return out

    def finish(self) -> list[dict]:
        """Declare end-of-stream, finalize observed windows, forbid future input."""
        if self.finished:
            raise SequenceError("stream already finished")
        out = self._close(None, "end_of_stream")
        self.finished = True
        return out

    def summary(self) -> dict:
        issues = self.stats["invalid"] + self.stats["late"] + self.stats["failed"] + self.stats["insufficient"]
        status = "EMPTY" if self.sequence == 0 else "ISSUES" if issues else "COMPLETE" if self.finished else "PAUSED"
        return {"kind": "summary", "status": status, "action": "investigate" if status == "EMPTY" else "quarantine" if issues else "release" if self.finished else "resume",
                "sequence": self.sequence, "contract_sha256": self.contract.digest, "watermark_ms": self.watermark,
                "stats": dict(self.stats), "active_windows": len(self.windows),
                "active_groups": sum(len(g) for g in self.windows.values()), "finished": self.finished}

    def checkpoint(self, source: dict | None = None) -> bytes:
        windows = []
        for start, groups in sorted(self.windows.items()):
            windows.append({"start_ms": start, "groups": [
                {"sha256": group, "count": bucket.count, "values": {
                    name: {"sum": rational(m.total), "min": rational(m.minimum), "max": rational(m.maximum)}
                    for name, m in sorted(bucket.values.items())}}
                for group, bucket in sorted(groups.items())]})
        payload = {"version": 1, "contract_sha256": self.contract.digest, "sequence": self.sequence,
                   "max_event_time": self.max_event_time, "watermark": self.watermark,
                   "stats": dict(self.stats), "finished": self.finished, "windows": windows, "source": source}
        result = canonical({"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()})
        if len(result) > self.contract.limits["max_checkpoint_bytes"]:
            raise ResourceLimit("max_checkpoint_bytes", self.sequence + 1)
        return result

    @classmethod
    def restore(cls, contract: Contract, raw: bytes, *, expected_sequence: int | None = None) -> tuple["Engine", dict | None]:
        """Validate checksum AND invariants. Hash is not an authenticity proof."""
        if len(raw) > contract.limits["max_checkpoint_bytes"]:
            raise CheckpointError("checkpoint_bytes_limit")
        try:
            document = strict_json(raw)
            if type(document) is not dict or set(document) != {"payload", "sha256"}:
                raise CheckpointError("invalid checkpoint envelope")
            payload = document["payload"]
            digest = hashlib.sha256(canonical(payload)).hexdigest()
            if type(document["sha256"]) is not str or not hmac.compare_digest(document["sha256"], digest):
                raise CheckpointError("checkpoint checksum mismatch")
            expected_keys = {"version", "contract_sha256", "sequence", "max_event_time", "watermark", "stats", "finished", "windows", "source"}
            if type(payload) is not dict or set(payload) != expected_keys or payload["version"] != 1 or type(payload["version"]) is not int:
                raise CheckpointError("invalid checkpoint payload")
            if payload["contract_sha256"] != contract.digest:
                raise CheckpointError("checkpoint contract mismatch")
            seq = payload["sequence"]
            if type(seq) is not int or not 0 <= seq <= MAX_TIME:
                raise CheckpointError("invalid checkpoint sequence")
            if expected_sequence is not None and seq != expected_sequence:
                raise CheckpointError("checkpoint sequence mismatch")
            engine = cls(contract)
            stats = payload["stats"]
            if type(stats) is not dict or set(stats) != set(engine.stats) or any(type(v) is not int or not 0 <= v <= MAX_TIME for v in stats.values()):
                raise CheckpointError("invalid checkpoint counters")
            if stats["accepted"] + stats["invalid"] + stats["late"] != seq or stats["failed"] + stats["insufficient"] > stats["windows"]:
                raise CheckpointError("inconsistent checkpoint counters")
            maximum, watermark = payload["max_event_time"], payload["watermark"]
            if stats["accepted"] == 0:
                if maximum is not None or watermark is not None:
                    raise CheckpointError("empty state has watermark")
            elif type(maximum) is not int or not 0 <= maximum <= MAX_TIME or type(watermark) is not int or watermark != maximum - contract.delay_ms:
                raise CheckpointError("inconsistent checkpoint watermark")
            if type(payload["finished"]) is not bool:
                raise CheckpointError("invalid finished state")
            windows = payload["windows"]
            if type(windows) is not list or len(windows) > contract.limits["max_active_windows"] or (payload["finished"] and windows):
                raise CheckpointError("invalid window count")
            active_events = 0
            for window in windows:
                if type(window) is not dict or set(window) != {"start_ms", "groups"}:
                    raise CheckpointError("invalid window")
                start, groups = window["start_ms"], window["groups"]
                if type(start) is not int or start < 0 or start % contract.size_ms or maximum is None or start > maximum or start in engine.windows or start + contract.size_ms + contract.lateness_ms <= watermark:
                    raise CheckpointError("invalid active window boundary")
                if type(groups) is not list or not 1 <= len(groups) <= contract.limits["max_groups_per_window"]:
                    raise CheckpointError("invalid group count")
                restored = {}
                for group in groups:
                    if type(group) is not dict or set(group) != {"sha256", "count", "values"}:
                        raise CheckpointError("invalid group")
                    key, count, values = group["sha256"], group["count"], group["values"]
                    if type(key) is not str or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or key in restored:
                        raise CheckpointError("invalid group digest")
                    if type(count) is not int or not 1 <= count <= contract.limits["max_events_per_group"]:
                        raise CheckpointError("invalid group event count")
                    if type(values) is not dict or set(values) != set(contract.numeric_fields):
                        raise CheckpointError("invalid numeric fields")
                    bucket = Bucket(count)
                    for name, state in values.items():
                        if type(state) is not dict or set(state) != {"sum", "min", "max"}:
                            raise CheckpointError("invalid aggregate state")
                        total, lo, hi = (read_rational(state[k]) for k in ("sum", "min", "max"))
                        if lo > hi or abs(lo) > MAX_NUMBER or abs(hi) > MAX_NUMBER or not count * lo <= total <= count * hi:
                            raise CheckpointError("inconsistent aggregate state")
                        bucket.values[name] = Moments(total, lo, hi)
                    restored[key] = bucket
                    active_events += count
                engine.windows[start] = restored
            if active_events > stats["accepted"]:
                raise CheckpointError("active events exceed accepted events")
            source = payload["source"]
            if source is not None:
                if type(source) is not dict or set(source) != {"lines", "prefix_sha256"} or type(source["lines"]) is not int or source["lines"] != seq:
                    raise CheckpointError("invalid source position")
                if type(source["prefix_sha256"]) is not str or len(source["prefix_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["prefix_sha256"]):
                    raise CheckpointError("invalid source digest")
            engine.sequence, engine.max_event_time, engine.watermark = seq, maximum, watermark
            engine.stats, engine.finished = stats, payload["finished"]
            return engine, source
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            if isinstance(exc, CheckpointError):
                raise
            raise CheckpointError("invalid checkpoint encoding or state") from exc

    def save(self, path: str | Path, source: dict | None = None) -> None:
        """Atomic replace in the destination directory; fsync file before replace."""
        raw = self.checkpoint(source)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".streamcontract-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
