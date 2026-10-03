"""Installed CLI input -> decisions -> checkpoint -> resume -> corruption stop."""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    examples = Path(__file__).resolve().parent
    base = [sys.executable, "-m", "streamcontract.cli", "--contract", str(examples / "contract.json"),
            "--input", str(examples / "events.jsonl")]

    def run(*extra):
        result = subprocess.run([*base, *extra], capture_output=True)
        assert not result.stderr, result.stderr.decode("utf-8", errors="replace")
        return result.returncode, [json.loads(line) for line in result.stdout.splitlines()]

    with tempfile.TemporaryDirectory(prefix="streamcontract-example-") as directory:
        checkpoint = Path(directory) / "state.json"
        full_code, full = run()
        pause_code, first = run("--stop-after", "4", "--checkpoint", str(checkpoint))
        source = json.loads(checkpoint.read_bytes())["payload"]["source"]
        prefix = b"".join((examples / "events.jsonl").read_bytes().splitlines(keepends=True)[:4])
        assert source == {"lines": 4, "prefix_sha256": hashlib.sha256(prefix).hexdigest()}
        resume_code, second = run("--resume", str(checkpoint))
        assert full_code == resume_code == 2 and pause_code == 0
        assert full == first[:-1] + second
        document = json.loads(checkpoint.read_bytes())
        document["payload"]["sequence"] += 1
        checkpoint.write_text(json.dumps(document), encoding="utf-8")
        corrupt_code, rejected = run("--resume", str(checkpoint))
        assert corrupt_code == 3 and rejected[0]["code"] == "checkpoint checksum mismatch"
        print(json.dumps({"input_records": 11, "full_exit": full_code, "pause_exit": pause_code,
                          "resume_exit": resume_code, "corrupt_exit": corrupt_code,
                          "source_prefix_verified": True, "decisions_equal": True,
                          "summary": full[-1]}, indent=2))


if __name__ == "__main__":
    main()
