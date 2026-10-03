import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_engine import spec


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


if __name__ == "__main__":
    unittest.main()
