import hashlib
import json
import random
import unittest
from copy import deepcopy
from fractions import Fraction

from streamcontract import CheckpointError, Contract, ContractError, Engine, ResourceLimit, SequenceError


def spec(**window):
    return {"version": 1, "event_time": "t",
            "fields": {"t": {"type": "integer", "min": 0}, "key": {"type": "string"},
                       "x": {"type": "number", "min": -100, "max": 100}},
            "group_by": ["key"], "window": {"size_ms": 10, "watermark_delay_ms": 10,
                                           "allowed_lateness_ms": 5, **window},
            "checks": [{"name": "mean", "op": "mean", "field": "x", "reference": 0, "max_absolute_delta": 10}]}


def event(t, x=0, key="a"):
    return {"t": t, "x": x, "key": key}


class EngineTests(unittest.TestCase):
    def rehash(self, document):
        raw = json.dumps(document["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        document["sha256"] = hashlib.sha256(raw).hexdigest()
        return json.dumps(document).encode()

    def test_checkpoint_cannot_lose_accepted_active_events(self):
        e = Engine(Contract(spec()))
        e.push(event(1))
        document = json.loads(e.checkpoint())
        document["payload"]["windows"] = []
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, self.rehash(document))

    def test_checkpoint_moments_respect_declared_field_domain(self):
        e = Engine(Contract(spec()))
        e.push(event(1, 10))
        document = json.loads(e.checkpoint())
        moments = document["payload"]["windows"][0]["groups"][0]["values"]["x"]
        moments.update({"sum": [200, 1], "min": [200, 1], "max": [200, 1]})
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, self.rehash(document))

    def test_checkpoint_extrema_must_be_present_in_moments(self):
        e = Engine(Contract(spec()))
        e.push(event(1, 0))
        e.push(event(2, 10))
        document = json.loads(e.checkpoint())
        document["payload"]["windows"][0]["groups"][0]["values"]["x"]["sum"] = [0, 1]
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, self.rehash(document))

    def test_half_open_boundary(self):
        e = Engine(Contract(spec()))
        self.assertEqual(e.push(event(9))[0]["evidence"][0]["start_ms"], 0)
        self.assertEqual(e.push(event(10))[0]["evidence"][0]["start_ms"], 10)
        self.assertEqual([d["evidence"]["sample_count"] for d in e.finish()], [1, 1])

    def test_watermark_and_lateness_exact_boundary(self):
        e = Engine(Contract(spec(watermark_delay_ms=0)))
        e.push(event(1))
        e.push(event(14))
        self.assertEqual(e.push(event(2))[0]["status"], "ACCEPTED")
        closed = e.push(event(15))
        self.assertEqual(closed[-1]["kind"], "window")
        self.assertEqual(e.push(event(9))[0]["status"], "LATE")
        self.assertEqual(e.stats["late"], 1)

    def test_invalid_does_not_advance_watermark(self):
        e = Engine(Contract(spec()))
        e.push(event(1))
        self.assertEqual(e.push(event(100000, "SECRET"))[0]["status"], "INVALID")
        self.assertEqual(e.max_event_time, 1)
        self.assertNotIn("SECRET", json.dumps(e.summary()))

    def test_types_nonfinite_unknown_fields(self):
        c = Contract(spec())
        for bad in [event(True), event(1, True), event(1, float("nan")), event(1, float("inf")),
                    {"t": 1, "key": "a"}, {**event(1), "secret": "password"}, [], None]:
            self.assertTrue(c.validate(bad))

    def test_huge_integer_is_invalid_without_float_conversion(self):
        c = Contract(spec())
        e = Engine(c)
        output = e.push(event(1, 10**1000))
        self.assertEqual(output[0]["status"], "INVALID")
        self.assertEqual(output[0]["evidence"], [{"code": "numeric_domain", "field": "x"}])
        self.assertEqual(e.sequence, 1)

    def test_malformed_sdk_contracts_use_contract_error(self):
        for mutate in [lambda s: s.update(group_by=[{}]), lambda s: s["checks"][0].update(field=[]),
                       lambda s: s["fields"]["x"].update(min=10**1000)]:
            s = spec()
            mutate(s)
            with self.assertRaises(ContractError):
                Contract(s)

    def test_compiled_contract_cannot_change_behind_digest(self):
        c = Contract(spec())
        e = Engine(c)
        e.push(event(1))
        before = e.checkpoint()
        with self.assertRaises(TypeError):
            c.limits["max_groups_per_window"] = 1
        with self.assertRaises(TypeError):
            c.fields["x"] = c.fields["t"]
        with self.assertRaises(AttributeError):
            c.size_ms = 20
        self.assertEqual(e.checkpoint(), before)

    def test_contract_export_is_detached(self):
        original = spec()
        c = Contract(original)
        original["window"]["size_ms"] = 999
        exported = c.to_dict()
        exported["window"]["size_ms"] = 888
        self.assertEqual(c.size_ms, 10)
        self.assertEqual(c.to_dict()["window"]["size_ms"], 10)

    def test_drift_and_insufficient(self):
        s = spec()
        s["checks"][0]["min_samples"] = 2
        e = Engine(Contract(s))
        e.push(event(1, 30))
        e.push(event(2, 30))
        e.push(event(11, 5))
        results = e.finish()
        self.assertEqual([x["status"] for x in results], ["FAIL", "INSUFFICIENT"])
        self.assertEqual(results[0]["evidence"]["checks"][0]["reasons"], ["aggregate_drift"])

    def test_empty_and_eof_terminal(self):
        e = Engine(Contract(spec()))
        self.assertEqual(e.finish(), [])
        self.assertEqual(e.summary()["status"], "EMPTY")
        with self.assertRaises(SequenceError):
            e.push(event(1))

    def test_sequence_failure_atomic(self):
        e = Engine(Contract(spec()))
        before = e.checkpoint()
        with self.assertRaises(SequenceError):
            e.push(event(1), sequence=2)
        self.assertEqual(before, e.checkpoint())

    def test_limits_transactional(self):
        for limit, inputs in [
            ("max_groups_per_window", [event(1, key="a"), event(2, key="b")]),
            ("max_events_per_group", [event(1), event(2)]),
            ("max_active_windows", [event(1), event(11)])]:
            s = spec(watermark_delay_ms=100)
            s["limits"] = {limit: 1}
            e = Engine(Contract(s))
            e.push(inputs[0])
            before = e.checkpoint()
            with self.assertRaises(ResourceLimit) as context:
                e.push(inputs[1])
            self.assertEqual(context.exception.limit, limit)
            self.assertEqual(before, e.checkpoint())

    def test_new_window_can_finalize_before_limit(self):
        s = spec(watermark_delay_ms=0, allowed_lateness_ms=0)
        s["limits"] = {"max_active_windows": 1}
        e = Engine(Contract(s))
        e.push(event(1))
        self.assertEqual(len(e.push(event(11))), 2)
        self.assertEqual(len(e.windows), 1)

    def test_many_keys_remain_bounded(self):
        s = spec()
        s["limits"] = {"max_groups_per_window": 8}
        e = Engine(Contract(s))
        for i in range(8):
            e.push(event(1, key=str(i)))
        for i in range(8, 1000):
            with self.assertRaises(ResourceLimit):
                e.push(event(1, key=str(i)))
        self.assertEqual(e.summary()["active_groups"], 8)
        self.assertEqual(e.sequence, 8)

    def test_checkpoint_corruption_mismatch(self):
        e = Engine(Contract(spec()))
        e.push(event(1))
        data = json.loads(e.checkpoint())
        data["payload"]["sequence"] = 100
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, json.dumps(data).encode())
        changed = spec()
        changed["window"]["size_ms"] = 20
        with self.assertRaises(CheckpointError):
            Engine.restore(Contract(changed), e.checkpoint())
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, e.checkpoint(), expected_sequence=2)

    def test_rehashed_invalid_state_rejected(self):
        e = Engine(Contract(spec()))
        e.push(event(1))
        data = json.loads(e.checkpoint())
        data["payload"]["watermark"] = 0
        payload = json.dumps(data["payload"], sort_keys=True, separators=(",", ":")).encode()
        data["sha256"] = hashlib.sha256(payload).hexdigest()
        with self.assertRaises(CheckpointError):
            Engine.restore(e.contract, json.dumps(data).encode())

    def test_every_resume_cut_identical(self):
        events = [event(t, x) for t, x in [(1, 0.1), (12, 20), (5, 0.2), (15, 22),
                                          (31, 0), (2, 9), (22, 10), (30, 0.3)]]
        full = Engine(Contract(spec()))
        expected = [d for x in events for d in full.push(x)] + full.finish()
        for cut in range(len(events) + 1):
            split = Engine(full.contract)
            actual = [d for x in events[:cut] for d in split.push(x)]
            split, _ = Engine.restore(full.contract, split.checkpoint(), expected_sequence=cut)
            actual += [d for x in events[cut:] for d in split.push(x)] + split.finish()
            self.assertEqual(expected, actual)
            self.assertEqual(full.summary(), split.summary())

    def test_independent_batch_oracle_on_bounded_disorder(self):
        rng = random.Random(42)
        events = [event(t, rng.randrange(-20, 21), str(t % 3)) for t in range(80)]
        # Delay covers the whole input so no late eviction: independent lists oracle.
        rng.shuffle(events)
        e = Engine(Contract(spec(watermark_delay_ms=100)))
        oracle = {}
        for value in events:
            start = value["t"] - value["t"] % 10
            group = hashlib.sha256(json.dumps([value["key"]], separators=(",", ":")).encode()).hexdigest()
            oracle.setdefault((start, group), []).append(value["x"])
            e.push(value)
        for result in e.finish():
            ev = result["evidence"]
            values = oracle[(ev["start_ms"], ev["group_sha256"])]
            mean = sum(Fraction(x) for x in values) / len(values)
            self.assertEqual(ev["checks"][0]["observed"], float(mean))
            self.assertEqual(result["status"], "FAIL" if abs(mean) > 10 else "PASS")

    def test_no_payload_retained(self):
        e = Engine(Contract(spec()))
        output = e.push(event(1, key="SECRET-CUSTOMER"))
        raw = e.checkpoint()
        self.assertNotIn(b"SECRET-CUSTOMER", raw)
        self.assertNotIn("SECRET-CUSTOMER", json.dumps(output))

    def test_operations_and_zero_reference(self):
        s = spec()
        s["checks"] = [{"name": op, "op": op, "field": "x", "min": 0, "max": 5}
                       for op in ("sum", "mean", "min", "max")]
        e = Engine(Contract(s))
        for x in [1, 2, 3]:
            e.push(event(1, x))
        checks = e.finish()[0]["evidence"]["checks"]
        self.assertEqual([c["observed"] for c in checks], [6, 2, 1, 3])

    def test_invalid_contracts(self):
        for mutate in [lambda s: s.update(version=2), lambda s: s["window"].update(size_ms=0),
                       lambda s: s["fields"]["x"].update(type="array"),
                       lambda s: s["checks"][0].update(max_absolute_delta=-1),
                       lambda s: s.update(unknown=True), lambda s: s["fields"]["t"].update(required=False)]:
            s = spec()
            mutate(s)
            with self.assertRaises(ContractError):
                Contract(s)


if __name__ == "__main__":
    unittest.main()
