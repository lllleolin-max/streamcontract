"""Primitive JSON identity is distinct from exact numeric-value identity."""

import hashlib
import itertools
import json
import unittest

from streamcontract import CheckpointError, Contract, Engine


def group_spec(field=None):
    return {"version": 1, "event_time": "t",
            "fields": {"t": {"type": "integer", "min": 0},
                       "x": field or {"type": "number"}},
            "group_by": ["x"], "window": {"size_ms": 10, "watermark_delay_ms": 10},
            "checks": [{"name": "mean", "op": "mean", "field": "x", "min": -1, "max": 1}]}


def expected_group(values):
    # Independent JSON primitive encoding, including the sign of float zero.
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


class NumericGrouping(unittest.TestCase):
    def assert_every_cut(self, contract, events):
        complete = Engine(contract)
        expected = [d for event in events for d in complete.push(event)] + complete.finish()
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                partial = Engine(contract)
                actual = [d for event in events[:cut] for d in partial.push(event)]
                raw = partial.checkpoint()
                restored, _ = Engine.restore(contract, raw, expected_sequence=cut)
                self.assertEqual(restored.checkpoint(), raw)
                actual += [d for event in events[cut:] for d in restored.push(event)] + restored.finish()
                self.assertEqual(actual, expected)
        return expected

    def test_zero_primitives_have_distinct_recoverable_groups(self):
        contract = Contract(group_spec())
        engine = Engine(contract)
        hashes = []
        for spelling in ("0", "0.0", "-0.0"):
            value = json.loads(spelling)
            self.assertEqual(contract.validate({"t": 1, "x": value}), [])
            decision = engine.push({"t": 1, "x": value})[0]
            self.assertEqual(decision["status"], "ACCEPTED")
            actual = decision["evidence"][0]["group_sha256"]
            self.assertEqual(actual, expected_group([value]))
            hashes.append(actual)
        self.assertEqual(len(set(hashes)), 3)
        raw = engine.checkpoint()
        self.assertNotIn(b"-0.0", raw)  # Numeric witnesses need no primitive payload copy.
        restored, _ = Engine.restore(contract, raw)
        self.assertEqual(restored.checkpoint(), raw)
        windows = restored.finish()
        self.assertEqual({d["evidence"]["group_sha256"] for d in windows}, set(hashes))
        self.assertTrue(all(d["status"] == "PASS" and d["evidence"]["sample_count"] == 1
                            for d in windows))

    def test_typed_zero_enums_and_ranges_keep_accepted_representations(self):
        values = [json.loads(s) for s in ("0", "0.0", "-0.0")]
        declarations = [
            ({"type": "number", "min": 0, "max": 0}, {0, 1, 2}),
            ({"type": "number", "enum": [0]}, {0}),
            ({"type": "number", "enum": [0.0]}, {1, 2}),
            ({"type": "number", "enum": [-0.0]}, {1, 2}),
            ({"type": "number", "enum": [0, 0.0]}, {0, 1, 2}),
            ({"type": "integer", "enum": [0]}, {0}),
        ]
        for field, accepted in declarations:
            contract = Contract(group_spec(field))
            for index, value in enumerate(values):
                with self.subTest(field=field, primitive=index):
                    event = {"t": 1, "x": value}
                    self.assertEqual(not contract.validate(event), index in accepted)
                    engine = Engine(contract)
                    disposition = engine.push(event)[0]
                    self.assertEqual(disposition["status"], "ACCEPTED" if index in accepted else "INVALID")
                    raw = engine.checkpoint()
                    restored, _ = Engine.restore(contract, raw)
                    self.assertEqual(restored.checkpoint(), raw)
                    self.assertEqual(restored.finish(), engine.finish())

    def test_mixed_numeric_key_tuples_and_every_resume_cut(self):
        spec = group_spec()
        spec["fields"].update(i={"type": "integer", "enum": [0]}, y={"type": "number", "enum": [0.0]})
        spec["group_by"] = ["t", "i", "x", "y"]
        spec["checks"] += [{"name": name, "op": "mean", "field": name, "min": 0, "max": 0}
                           for name in ("i", "y")]
        events = [{"t": 1, "i": 0, "x": x, "y": y}
                  for x, y in itertools.product((0, 0.0, -0.0), (0.0, -0.0))]
        expected = self.assert_every_cut(Contract(spec), events)
        event_hashes = [d["evidence"][0]["group_sha256"] for d in expected if d["kind"] == "event"]
        self.assertEqual(event_hashes, [expected_group([e["t"], e["i"], e["x"], e["y"]]) for e in events])
        self.assertEqual(len(set(event_hashes)), 6)

    def test_signed_zero_every_resume_cut_across_windows_and_late_records(self):
        events = [{"t": t, "x": value} for t, value in
                  [(1, -0.0), (2, 0.0), (3, 0), (14, -0.0), (4, 0.0), (22, 0), (5, -0.0), (35, -0.0)]]
        expected = self.assert_every_cut(Contract(group_spec()), events)
        self.assertEqual(sum(d.get("status") == "LATE" for d in expected), 1)
        self.assertEqual(sum(d["kind"] == "event" for d in expected), len(events))

    def test_eight_zero_number_keys_restore_with_finite_candidate_bound(self):
        spec = group_spec()
        names = [f"x{i}" for i in range(8)]
        spec["fields"] = {"t": {"type": "integer", "min": 0}, **{name: {"type": "number"} for name in names}}
        spec["group_by"] = names
        spec["checks"] = [{"name": name, "op": "mean", "field": name, "min": 0, "max": 0} for name in names]
        contract = Contract(spec)
        engine = Engine(contract)
        event = {"t": 1, **dict.fromkeys(names, -0.0)}
        decision = engine.push(event)[0]
        self.assertEqual(decision["evidence"][0]["group_sha256"], expected_group([-0.0] * 8))
        raw = engine.checkpoint()
        restored, _ = Engine.restore(contract, raw)
        self.assertEqual(restored.checkpoint(), raw)
        self.assertEqual(restored.finish(), engine.finish())

    def test_zero_digest_for_disallowed_primitive_still_rejects(self):
        for field, allowed, disallowed in [({"type": "integer"}, 0, -0.0),
                                           ({"type": "number", "enum": [0]}, 0, 0.0),
                                           ({"type": "number", "enum": [0.0]}, 0.0, 0)]:
            with self.subTest(field=field):
                contract = Contract(group_spec(field))
                engine = Engine(contract)
                engine.push({"t": 1, "x": allowed})
                document = json.loads(engine.checkpoint())
                document["payload"]["windows"][0]["groups"][0]["sha256"] = expected_group([disallowed])
                raw = json.dumps(document["payload"], sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode()
                document["sha256"] = hashlib.sha256(raw).hexdigest()
                with self.assertRaises(CheckpointError):
                    Engine.restore(contract, json.dumps(document).encode())


if __name__ == "__main__":
    unittest.main()
