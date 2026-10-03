import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_engine import spec
from test_numeric_grouping import group_spec


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = self.root / "contract.json"
        self.input = self.root / "events.jsonl"
        self.checkpoint = self.root / "state.json"
        self.contract.write_text(json.dumps(spec()), encoding="utf-8")

    def command(self, *extra):
        result = subprocess.run([sys.executable, "-m", "streamcontract.cli", "--contract", str(self.contract),
                                 "--input", str(self.input), *extra], capture_output=True)
        return result.returncode, [json.loads(line) for line in result.stdout.splitlines()], result.stderr

    def test_cli_resume_matches_full(self):
        self.input.write_text('\n'.join(json.dumps({"t": t, "key": "a", "x": x}) for t, x in [(1, 2), (15, 20), (4, 3), (31, 1)]) + '\n')
        code, full, _ = self.command()
        _, first, _ = self.command("--stop-after", "2", "--checkpoint", str(self.checkpoint))
        resumed_code, second, _ = self.command("--resume", str(self.checkpoint))
        self.assertEqual(full, first[:-1] + second)
        self.assertEqual(code, resumed_code)

    def test_cli_signed_zero_numeric_groups_every_resume_cut(self):
        self.contract.write_text(json.dumps(group_spec()), encoding="utf-8")
        events = [{"t": t, "x": x} for t, x in
                  [(1, -0.0), (2, 0.0), (3, 0), (14, -0.0), (22, 0.0), (5, -0.0)]]
        self.input.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding="utf-8")
        code, full, error = self.command()
        self.assertEqual(code, 2)  # One intentionally late event remains quarantined.
        self.assertEqual(error, b"")
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                _, first, error = self.command("--stop-after", str(cut), "--checkpoint", str(self.checkpoint))
                self.assertEqual(error, b"")
                resumed_code, second, error = self.command("--resume", str(self.checkpoint))
                self.assertEqual(error, b"")
                self.assertEqual(resumed_code, code)
                self.assertEqual(full, first[:-1] + second)

    def test_changed_source_prefix_rejected(self):
        self.input.write_text('{"t":1,"key":"a","x":1}\n{"t":2,"key":"a","x":2}\n')
        self.command("--stop-after", "1", "--checkpoint", str(self.checkpoint))
        self.input.write_text('{"t":1,"key":"b","x":1}\n{"t":2,"key":"a","x":2}\n')
        code, output, _ = self.command("--resume", str(self.checkpoint))
        self.assertEqual(code, 3)
        self.assertEqual(output[0]["code"], "source prefix mismatch")

    def test_malformed_lines_are_reported_not_dropped(self):
        self.input.write_bytes(b'not-json\n{"t":1,"t":2,"key":"a","x":0}\n\xff\n')
        code, output, error = self.command()
        self.assertEqual(code, 2)
        self.assertEqual(len([d for d in output if d["kind"] == "event"]), 3)
        self.assertEqual(output[-1]["stats"]["invalid"], 3)
        self.assertEqual(error, b"")

    def test_huge_integer_emits_disposition_then_continues(self):
        self.input.write_text('{"t":1,"key":"a","x":' + '9' * 1000 + '}\n{"t":2,"key":"a","x":0}\n')
        code, output, error = self.command()
        self.assertEqual(code, 2)
        self.assertEqual(error, b"")
        self.assertEqual(output[-1]["sequence"], 2)
        self.assertEqual(output[-1]["stats"]["invalid"], 1)
        self.assertEqual(output[-1]["stats"]["accepted"], 1)

    def test_oversized_line_bounded_and_next_line_read(self):
        s = spec()
        s["limits"] = {"max_event_bytes": 40}
        self.contract.write_text(json.dumps(s))
        self.input.write_bytes(b'x' * 10000 + b'\n{"t":1,"key":"a","x":0}\n')
        _, output, _ = self.command()
        self.assertEqual(output[-1]["sequence"], 2)
        self.assertEqual(output[-1]["stats"]["accepted"], 1)
        self.assertEqual(output[0]["evidence"][0]["code"], "event_bytes_limit")

    def test_resource_checkpoint_excludes_unconsumed_line(self):
        s = spec()
        s["limits"] = {"max_groups_per_window": 1}
        self.contract.write_text(json.dumps(s))
        prefix = b'{"t":1,"key":"a","x":0}\n'
        self.input.write_bytes(prefix + b'{"t":1,"key":"b","x":0}\n')
        code, output, _ = self.command("--checkpoint", str(self.checkpoint))
        self.assertEqual(code, 3)
        state = json.loads(self.checkpoint.read_bytes())["payload"]
        self.assertEqual(state["source"], {"lines": 1, "prefix_sha256": hashlib.sha256(prefix).hexdigest()})
        self.assertFalse(output[-2]["consumed"])

    def test_checkpoint_cannot_overwrite_input_or_contract(self):
        self.input.write_bytes(b'{"t":1,"key":"a","x":0}\n')
        for path in [self.input, self.contract]:
            original = path.read_bytes()
            code, output, error = self.command("--checkpoint", str(path))
            self.assertEqual(code, 3)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(output[0]["code"], "checkpoint aliases input or contract")
            self.assertEqual(error, b"")

    def test_checkpoint_hardlink_alias_rejects(self):
        self.input.write_bytes(b'{"t":1,"key":"a","x":0}\n')
        alias = self.root / "aliased-state.json"
        os.link(self.input, alias)
        original = self.input.read_bytes()
        code, output, _ = self.command("--checkpoint", str(alias))
        self.assertEqual(code, 3)
        self.assertEqual(output[0]["code"], "checkpoint aliases input or contract")
        self.assertEqual(self.input.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
