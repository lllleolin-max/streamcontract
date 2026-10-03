"""Strict contract compiler and shared JSON parsing."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_NUMBER = 1e15
MAX_TIME = 2**63 - 1


class ContractError(ValueError):
    """Invalid or unsupported contract; messages contain no event values."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise ValueError("nonfinite_json_number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def integer(value: Any, name: str, minimum: int = 0, maximum: int = MAX_TIME) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(f"{name}: expected integer in [{minimum}, {maximum}]")
    return value


def number(value: Any, name: str) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > MAX_NUMBER:
        raise ContractError(f"{name}: expected finite number with abs <= 1e15")
    return value


def keys(obj: Any, allowed: set[str], required: set[str], name: str) -> dict:
    if type(obj) is not dict or any(type(k) is not str for k in obj):
        raise ContractError(f"{name}: expected object")
    if set(obj) - allowed or required - set(obj):
        raise ContractError(f"{name}: unsupported or missing option")
    return obj


@dataclass(frozen=True)
class Field:
    type: str
    required: bool
    minimum: int | float | None
    maximum: int | float | None
    max_length: int
    enum: tuple | None

    def check(self, value: Any) -> str | None:
        types = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}
        if type(value) not in types[self.type]:
            return "type"
        if self.type in ("integer", "number"):
            if not math.isfinite(value) or abs(value) > MAX_NUMBER:
                return "numeric_domain"
            if self.minimum is not None and value < self.minimum:
                return "minimum"
            if self.maximum is not None and value > self.maximum:
                return "maximum"
        if self.type == "string" and len(value) > self.max_length:
            return "max_length"
        if self.enum is not None and not any(type(value) is type(item) and value == item for item in self.enum):
            return "enum"
        return None


@dataclass(frozen=True)
class Rule:
    name: str
    op: str
    field: str | None
    minimum: int | float | None
    maximum: int | float | None
    reference: int | float | None
    max_absolute_delta: int | float | None
    min_samples: int


class Contract:
    """Compile a supported flat JSON contract. Unknown options fail closed."""

    def __init__(self, spec: dict):
        spec = deepcopy(spec)
        keys(spec, {"version", "event_time", "fields", "group_by", "window", "limits", "checks"},
             {"version", "event_time", "fields", "window", "checks"}, "contract")
        if spec["version"] != 1 or type(spec["version"]) is not int:
            raise ContractError("unsupported contract version")
        if type(spec["event_time"]) is not str:
            raise ContractError("event_time: expected field name")
        fields = keys(spec["fields"], set(spec["fields"]) if type(spec["fields"]) is dict else set(),
                      set(), "fields")
        if not 1 <= len(fields) <= 64:
            raise ContractError("fields: require 1..64 declarations")
        self.fields = {}
        for name, options in fields.items():
            if not name or len(name) > 100:
                raise ContractError("field names: require 1..100 characters")
            keys(options, {"type", "required", "min", "max", "max_length", "enum"}, {"type"}, "field")
            if options["type"] not in ("string", "integer", "number", "boolean"):
                raise ContractError("field: unsupported type")
            required = options.get("required", True)
            if type(required) is not bool:
                raise ContractError("required: expected boolean")
            lo = number(options["min"], "field.min") if "min" in options else None
            hi = number(options["max"], "field.max") if "max" in options else None
            if (lo is not None or hi is not None) and options["type"] not in ("integer", "number"):
                raise ContractError("numeric limits on nonnumeric field")
            if lo is not None and hi is not None and lo > hi:
                raise ContractError("field.min exceeds field.max")
            enum = options.get("enum")
            if enum is not None and (type(enum) is not list or not 1 <= len(enum) <= 256):
                raise ContractError("enum: require 1..256 primitive values")
            field = Field(options["type"], required, lo, hi,
                          integer(options.get("max_length", 1024), "max_length", 0, 65536),
                          None if enum is None else tuple(enum))
            if enum is not None and any(field.check(item) for item in enum):
                raise ContractError("enum value violates field declaration")
            self.fields[name] = field
        self.event_time = spec["event_time"]
        if self.event_time not in self.fields or self.fields[self.event_time].type != "integer" or not self.fields[self.event_time].required:
            raise ContractError("event_time must be a required integer field (epoch milliseconds)")
        groups = spec.get("group_by", [])
        if type(groups) is not list or len(groups) > 8 or len(set(groups)) != len(groups):
            raise ContractError("group_by: require up to 8 distinct field names")
        if any(g not in self.fields or not self.fields[g].required for g in groups):
            raise ContractError("group_by fields must be declared and required")
        self.group_by = tuple(groups)
        window = keys(spec["window"], {"size_ms", "watermark_delay_ms", "allowed_lateness_ms"}, {"size_ms"}, "window")
        self.size_ms = integer(window["size_ms"], "size_ms", 1)
        self.delay_ms = integer(window.get("watermark_delay_ms", 0), "watermark_delay_ms")
        self.lateness_ms = integer(window.get("allowed_lateness_ms", 0), "allowed_lateness_ms")
        defaults = {"max_active_windows": 32, "max_groups_per_window": 128,
                    "max_events_per_group": 1000000, "max_event_bytes": 65536,
                    "max_checkpoint_bytes": 16777216}
        limits = keys(spec.get("limits", {}), set(defaults), set(), "limits")
        self.limits = {k: integer(limits.get(k, v), k, 1, 100000000) for k, v in defaults.items()}
        checks = spec["checks"]
        if type(checks) is not list or not 1 <= len(checks) <= 32:
            raise ContractError("checks: require 1..32 rules")
        rules = []
        for check in checks:
            keys(check, {"name", "op", "field", "min", "max", "reference", "max_absolute_delta", "min_samples"}, {"name", "op"}, "check")
            if type(check["name"]) is not str or not 1 <= len(check["name"]) <= 100:
                raise ContractError("check name: require 1..100 characters")
            if check["op"] not in ("count", "sum", "mean", "min", "max"):
                raise ContractError("unsupported aggregate operation")
            field = check.get("field")
            if check["op"] == "count":
                if field is not None:
                    raise ContractError("count must not declare field")
            elif field not in self.fields or self.fields[field].type not in ("integer", "number") or not self.fields[field].required:
                raise ContractError("aggregate field must be required and numeric")
            lo = number(check["min"], "check.min") if "min" in check else None
            hi = number(check["max"], "check.max") if "max" in check else None
            ref = number(check["reference"], "reference") if "reference" in check else None
            delta = number(check["max_absolute_delta"], "max_absolute_delta") if "max_absolute_delta" in check else None
            if lo is not None and hi is not None and lo > hi:
                raise ContractError("check.min exceeds check.max")
            if (ref is None) != (delta is None) or (delta is not None and delta < 0):
                raise ContractError("reference requires nonnegative max_absolute_delta")
            if lo is None and hi is None and ref is None:
                raise ContractError("check requires threshold or reference")
            rules.append(Rule(check["name"], check["op"], field, lo, hi, ref, delta,
                              integer(check.get("min_samples", 1), "min_samples", 1, self.limits["max_events_per_group"])))
        if len({r.name for r in rules}) != len(rules):
            raise ContractError("duplicate check name")
        self.rules = tuple(rules)
        self.numeric_fields = tuple(sorted({r.field for r in rules if r.field is not None}))
        self._spec = spec
        self.digest = hashlib.sha256(canonical(spec)).hexdigest()

    @classmethod
    def from_file(cls, path: str | Path) -> "Contract":
        raw = Path(path).read_bytes()
        if len(raw) > 1048576:
            raise ContractError("contract exceeds 1 MiB")
        try:
            return cls(strict_json(raw))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError("invalid contract JSON or declaration") from exc

    def validate(self, event: Any) -> list[dict[str, str]]:
        if type(event) is not dict or any(type(k) is not str for k in event):
            return [{"code": "object_required"}]
        reasons = []
        if set(event) - set(self.fields):
            reasons.append({"code": "unexpected_fields"})
        for name, field in self.fields.items():
            if name not in event:
                if field.required:
                    reasons.append({"code": "missing", "field": name})
            else:
                reason = field.check(event[name])
                if reason:
                    reasons.append({"code": reason, "field": name})
        if not reasons and not 0 <= event[self.event_time] <= MAX_TIME:
            reasons.append({"code": "event_time_domain", "field": self.event_time})
        return reasons
