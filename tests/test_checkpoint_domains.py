"""Rehashed impossible states and independently enumerable feasibility oracles."""

import hashlib
import itertools
import json
import math
import unittest
from fractions import Fraction

from streamcontract import CheckpointError, Contract, Engine, ResourceLimit
from streamcontract.contract import canonical
from streamcontract.moments import Moments, MomentError, read_moments


def spec(field=None, checks=None):
    return {"version": 1, "event_time": "t", "fields": {"t": {"type": "integer", "min": 0},
            "x": field or {"type": "number"}}, "window": {"size_ms": 10, "watermark_delay_ms": 10},
            "checks": checks or [{"name": "x", "op": "mean", "field": "x", "max": 50}]}


def encode(document):
    document["sha256"] = hashlib.sha256(canonical(document["payload"])).hexdigest()
    return canonical(document)


class CheckpointDomains(unittest.TestCase):
    def prepared(self, declaration=None, values=(100,), times=None, checks=None):
        contract = Contract(spec(declaration, checks))
        engine = Engine(contract)
        for index, value in enumerate(values):
            engine.push({"t": (times or [1] * len(values))[index], "x": value})
        return contract, engine, json.loads(engine.checkpoint())

    def test_enum_zero_cannot_turn_failure_into_release(self):
        contract, engine, document = self.prepared({"type": "number", "enum": [100, 200]})
        original, _ = Engine.restore(contract, engine.checkpoint())
        self.assertEqual(original.finish()[0]["status"], "FAIL")
        state = document["payload"]["windows"][0]["groups"][0]["values"]["x"]
        state.update(sum=[0, 1], min=[0, 1], max=[0, 1])
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))

    def test_enum_legal_extrema_but_impossible_joint_sum(self):
        contract, _, document = self.prepared({"type": "number", "enum": [0, 2, 5]}, (0, 2, 5))
        state = document["payload"]["windows"][0]["groups"][0]["values"]["x"]
        state["sum"] = [8, 1]  # after mandatory 0 and 5, leftover 3 is not allowed
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))

    def test_enum_witness_cannot_use_illegal_value_or_count(self):
        contract, engine, document = self.prepared({"type": "number", "enum": [0, 2, 5]}, (0, 2, 5))
        for replacement in [
            [{"value": [0, 1], "count": 1}, {"value": [3, 1], "count": 1}, {"value": [5, 1], "count": 1}],
            [{"value": [0, 1], "count": 1}, {"value": [2, 1], "count": True}, {"value": [5, 1], "count": 1}],
            [{"value": [0, 1], "count": 2}, {"value": [5, 1], "count": 1}]]:
            changed = json.loads(engine.checkpoint())
            changed["payload"]["windows"][0]["groups"][0]["values"]["x"]["proof"]["counts"] = replacement
            with self.assertRaises(CheckpointError):
                Engine.restore(contract, encode(changed))

    def test_one_third_and_unrepresentable_dyadic_extrema_rejected(self):
        contract, engine, _ = self.prepared()
        for value in [[1, 3], [2**53 + 1, 2**53]]:
            document = json.loads(engine.checkpoint())
            state = document["payload"]["windows"][0]["groups"][0]["values"]["x"]
            state.update(sum=value, min=value, max=value)
            with self.assertRaises(CheckpointError):
                Engine.restore(contract, encode(document))

    def test_binary_joint_sum_not_on_binade_lattice_rejected(self):
        contract, _, document = self.prepared(values=(1.0, 1.0, 1.5))
        state = document["payload"]["windows"][0]["groups"][0]["values"]["x"]
        impossible = Fraction(7, 2) + Fraction(1, 2**1074)
        replacement = [impossible.numerator, impossible.denominator]
        state["sum"] = replacement
        state["proof"]["strata"][0]["sum"] = replacement
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))

    def test_ungrouped_identity_and_multiple_groups_rejected(self):
        contract, _, document = self.prepared()
        document["payload"]["windows"][0]["groups"][0]["sha256"] = "0" * 64
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))

    def test_observable_numeric_group_identity_and_time_constancy(self):
        for grouping in (["x"], ["t"], ["t", "x"]):
            s = spec()
            s["group_by"] = grouping
            contract = Contract(s)
            engine = Engine(contract)
            engine.push({"t": 1, "x": 100.0})
            Engine.restore(contract, engine.checkpoint())
            document = json.loads(engine.checkpoint())
            document["payload"]["windows"][0]["groups"][0]["sha256"] = "0" * 64
            with self.assertRaises(CheckpointError):
                Engine.restore(contract, encode(document))

    def test_checkpoint_v2_and_duplicate_or_missing_witness_reject(self):
        contract, engine, document = self.prepared(values=(1.0, 1.5))
        document["payload"]["version"] = 2
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))
        for mutate in (lambda g: g.pop("time"),
                       lambda g: g["values"]["x"].pop("proof"),
                       lambda g: g["values"]["x"]["proof"]["strata"].append(g["values"]["x"]["proof"]["strata"][0])):
            document = json.loads(engine.checkpoint())
            mutate(document["payload"]["windows"][0]["groups"][0])
            with self.assertRaises(CheckpointError):
                Engine.restore(contract, encode(document))

    def test_timestamp_aggregate_must_match_window_and_unconditional_time_witness(self):
        checks = [{"name": "t", "op": "max", "field": "t", "max": 9}]
        contract, engine, document = self.prepared(checks=checks)
        state = document["payload"]["windows"][0]["groups"][0]["values"]["t"]
        state.update(sum=[99, 1], min=[99, 1], max=[99, 1])
        with self.assertRaises(CheckpointError):
            Engine.restore(contract, encode(document))
        # Even without any t aggregate check, time is independently retained.
        contract, engine, document = self.prepared()
        time = document["payload"]["windows"][0]["groups"][0]["time"]
        for bad in (0, 2, 10, 99):
            altered = json.loads(engine.checkpoint())
            altered["payload"]["windows"][0]["groups"][0]["time"].update(sum=[bad, 1], min=[bad, 1], max=[bad, 1])
            with self.assertRaises(CheckpointError):
                Engine.restore(contract, encode(altered))

    def test_valid_exact_subnormal_cancellation_and_every_resume_cut(self):
        values = [0.0, 5e-324, -5e-324, 0.1, -0.1, math.nextafter(1.0, math.inf), 1e15, -1e15]
        contract = Contract(spec())
        full = Engine(contract)
        events = [{"t": 1, "x": value} for value in values]
        expected = [decision for event in events for decision in full.push(event)] + full.finish()
        for cut in range(len(events) + 1):
            partial = Engine(contract)
            actual = [decision for event in events[:cut] for decision in partial.push(event)]
            partial, _ = Engine.restore(contract, partial.checkpoint(), expected_sequence=cut)
            actual += [decision for event in events[cut:] for decision in partial.push(event)] + partial.finish()
            self.assertEqual(actual, expected)

    def test_large_feasible_enum_count_does_not_expand_samples(self):
        s = spec({"type": "number", "enum": [0, 2, 5]})
        s["limits"] = {"max_events_per_group": 100000000}
        contract = Contract(s)
        engine = Engine(contract)
        engine.push({"t": 1, "x": 2})
        document = json.loads(engine.checkpoint())
        payload = document["payload"]
        payload["sequence"] = payload["stats"]["accepted"] = 100000000
        group = payload["windows"][0]["groups"][0]
        group["count"] = 100000000
        group["time"]["sum"] = [100000000, 1]
        group["values"]["x"]["sum"] = [200000000, 1]
        group["values"]["x"]["proof"]["counts"][0]["count"] = 100000000
        restored, _ = Engine.restore(contract, encode(document))
        self.assertEqual(restored.finish()[0]["evidence"]["checks"][0]["observed"], 2)
        self.assertLess(len(encode(document)), 2000)

    def test_large_binary_count_preserves_exact_float_sum(self):
        for value in (0.1, 5e-324, 1e15):
            s = spec()
            s["limits"] = {"max_events_per_group": 100000000}
            contract = Contract(s)
            engine = Engine(contract)
            engine.push({"t": 1, "x": value})
            document = json.loads(engine.checkpoint())
            payload = document["payload"]
            payload["sequence"] = payload["stats"]["accepted"] = 100000000
            group = payload["windows"][0]["groups"][0]
            group["count"] = 100000000
            group["time"]["sum"] = [100000000, 1]
            total = Fraction(value) * 100000000
            state = group["values"]["x"]
            state["sum"] = [total.numerator, total.denominator]
            state["proof"]["strata"][0].update(count=100000000, sum=state["sum"])
            restored, _ = Engine.restore(contract, encode(document))
            self.assertEqual(restored.finish()[0]["evidence"]["checks"][0]["observed"], value)

    def test_stratum_limit_is_transactional_and_existing_stratum_continues(self):
        s = spec()
        s["limits"] = {"max_numeric_strata_per_field": 1}
        engine = Engine(Contract(s))
        engine.push({"t": 1, "x": 1.0})
        before = engine.checkpoint()
        with self.assertRaises(ResourceLimit) as caught:
            engine.push({"t": 1, "x": 2.0})
        self.assertEqual(caught.exception.limit, "max_numeric_strata_per_field")
        self.assertEqual(before, engine.checkpoint())
        engine.push({"t": 1, "x": 1.5})
        Engine.restore(engine.contract, engine.checkpoint())

    def test_independent_enum_multiset_oracle_all_small_realizations(self):
        declaration = Contract(spec({"type": "number", "enum": [0, 2, 5]})).fields["x"]
        for count in range(1, 5):
            for values in itertools.combinations_with_replacement([0, 2, 5], count):
                moments = Moments.first(values[0], declaration)
                for value in values[1:]:
                    moments.add(value)
                restored = read_moments(moments.encode(), count, declaration, 128)
                self.assertEqual(restored.total, sum(values))
                # No value sequence with these extrema has this independently chosen sum.
                possible = {sum(xs) for xs in itertools.product([0, 2, 5], repeat=count)
                            if min(xs) == min(values) and max(xs) == max(values)}
                bad_sum = next(x for x in range(count * 5 + 2) if x not in possible)
                altered = moments.encode()
                altered["sum"] = [bad_sum, 1]
                with self.assertRaises(MomentError):
                    read_moments(altered, count, declaration, 128)

    def test_binary_lattice_proof_matches_independent_exhaustive_multisets(self):
        declaration = Contract(spec()).fields["x"]
        lattice = [1.0]
        for _ in range(3):
            lattice.append(math.nextafter(lattice[-1], math.inf))
        for count in range(1, 5):
            possibilities = {(sum(map(Fraction, xs)), min(xs), max(xs))
                             for xs in itertools.product(lattice, repeat=count)}
            for values in itertools.combinations_with_replacement(lattice, count):
                moments = Moments.first(values[0], declaration)
                for value in values[1:]:
                    moments.add(value)
                encoded = moments.encode()
                restored = read_moments(encoded, count, declaration, 128)
                self.assertIn((restored.total, float(restored.minimum), float(restored.maximum)), possibilities)
                changed = Fraction(encoded["sum"][0], encoded["sum"][1]) + Fraction(1, 2**53)
                encoded["sum"] = [changed.numerator, changed.denominator]
                encoded["proof"]["strata"][0]["sum"] = encoded["sum"]
                with self.assertRaises(MomentError):
                    read_moments(encoded, count, declaration, 128)


if __name__ == "__main__":
    unittest.main()
