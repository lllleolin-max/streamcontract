"""Frozen first-candidate probes; exit nonzero on actual unresolved boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
from streamcontract import Contract, CheckpointError, process_local, read_committed
from streamcontract.contract import canonical

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir()
contract = Contract({'version': 1, 'event_time': 't', 'fields': {'t': {'type': 'integer'}},
                     'window': {'size_ms': 10}, 'checks': [{'name': 'count', 'op': 'count', 'min': 1}]})
source = out / 'input.jsonl'
source.write_bytes(b'{"t":1}\n{"t":12}\n')
malformed = out / 'malformed'
process_local(contract, source, malformed)
pointer = json.loads((malformed / 'CURRENT.json').read_bytes())
manifest_path = malformed / (pointer['commit']['name'] + '.manifest.json')
manifest = json.loads(manifest_path.read_bytes())
manifest['phase'] = []
raw = canonical(manifest)
manifest_path.write_bytes(raw)
pointer['commit']['sha256'] = hashlib.sha256(raw).hexdigest()
(malformed / 'CURRENT.json').write_bytes(canonical(pointer))
try:
    list(read_committed(malformed, contract))
except Exception as exc:
    malformed_kind = type(exc).__name__
else:
    malformed_kind = 'ACCEPTED'
paused = out / 'paused'
process_local(contract, source, paused, stop_after=1)
before = sorted(p.name for p in paused.iterdir())
for _ in range(3):
    process_local(contract, source, paused, stop_after=0)
after = sorted(p.name for p in paused.iterdir())
result = {'malformed_phase_error': malformed_kind, 'malformed_controlled_rejection': malformed_kind == 'CheckpointError',
          'no_op_pause_created_files': len(set(after) - set(before)),
          'no_op_pause_creates_no_files': before == after}
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))
raise SystemExit(not (result['malformed_controlled_rejection'] and result['no_op_pause_creates_no_files']))
