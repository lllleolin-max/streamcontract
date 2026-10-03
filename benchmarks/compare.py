"""Executable synthetic contrasts, not measurements of Soda/Flink performance."""

import hashlib
import json
import time
import tracemalloc
from collections import defaultdict
from copy import deepcopy

from streamcontract import Contract, Engine, ResourceLimit


def contract(delay=15, lateness=5, aggregate=True):
    spec = {"version": 1, "event_time": "t", "fields": {"t": {"type": "integer", "min": 0},
            "service": {"type": "string"}, "latency": {"type": "number", "min": 0, "max": 1000}},
            "group_by": ["service"], "window": {"size_ms": 10, "watermark_delay_ms": delay, "allowed_lateness_ms": lateness},
            "checks": [{"name": "count", "op": "count", "min": 2}]}
    if aggregate:
        spec["checks"].append({"name": "mean_shift", "op": "mean", "field": "latency", "reference": 100,
                               "max_absolute_delta": 25, "min_samples": 2})
    return Contract(spec)


def e(t, latency=100, service="checkout"):
    return {"t": t, "latency": latency, "service": service}


def process(events, policy, resume_cut=None):
    engine = Engine(policy)
    decisions = []
    for i, event in enumerate(events):
        if resume_cut == i:
            engine, _ = Engine.restore(policy, engine.checkpoint(), expected_sequence=i)
        decisions.extend(engine.push(event))
    decisions.extend(engine.finish())
    return decisions, engine.summary()


def batch_shape(events, policy):
    # Actually run strict per-event contract checks, without aggregate windows.
    return {"invalid": sum(bool(policy.validate(event)) for event in events), "failed_windows": 0,
            "late": 0, "scope": "row shape/domain only"}


def processing_time(events, policy):
    # Synthetic arrivals one millisecond apart, same checks and grouping.
    # Source event t deliberately replaced with arrival clock for this baseline.
    arrivals = [{**event, "t": i} for i, event in enumerate(events)]
    return process(arrivals, policy)[1]


def metrics(result):
    return {"failed_windows": result[1]["stats"]["failed"], "late": result[1]["stats"]["late"],
            "insufficient": result[1]["stats"]["insufficient"], "accepted": result[1]["stats"]["accepted"]}


def main():
    scenarios = {
        "drift_hidden_in_arrival_mix": [e(1), e(11, 160), e(2), e(12, 160), e(21), e(22)],
        "clean_bounded_disorder": [e(1), e(11), e(2), e(12), e(21), e(22)],
        "adverse_too_small_watermark_delay": [e(1), e(21), e(2), e(22)],
        "declared_late_after_close": [e(1), e(2), e(40), e(3, 200)],
        "empty": [],
        "exact_half_open_boundary": [e(9), e(10), e(8), e(11)]}
    reports = []
    for name, events in scenarios.items():
        policy = contract()
        complete = process(events, policy)
        resumed = process(events, policy, len(events) // 2)
        assert complete == resumed
        no_drift = process(events, contract(aggregate=False))
        zero_delay = process(events, contract(delay=0, lateness=0))
        reports.append({"scenario": name, "records": len(events), "batch_shape": batch_shape(events, policy),
                        "processing_time": metrics(([], processing_time(events, policy))), "event_time": metrics(complete),
                        "ablation_no_aggregate": metrics(no_drift), "ablation_no_disorder_budget": metrics(zero_delay),
                        "resume_equal": True})
    # High cardinality must STOP, not keep allocating or silently drop keys.
    s = deepcopy(contract()._spec)
    s["limits"] = {"max_groups_per_window": 16}
    engine = Engine(Contract(s))
    tracemalloc.start()
    start = time.perf_counter()
    for i in range(10000):
        try:
            engine.push(e(1, service=f"synthetic-{i}"))
        except ResourceLimit:
            break
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert engine.sequence == 16 and engine.summary()["active_groups"] == 16
    print(json.dumps({"fixture": "disclosed synthetic; no incumbents executed", "scenarios": reports,
                      "cardinality_limit": {"offered_records": 10000, "consumed": engine.sequence,
                                            "next_sequence": i + 1, "active_groups": 16,
                                            "python_allocation_peak_bytes": peak, "seconds": time.perf_counter() - start}}, indent=2))


if __name__ == "__main__":
    main()
