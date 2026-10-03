"""Frozen probe: an owned committed store cannot silently become a new run."""
import argparse
import json
from pathlib import Path
from streamcontract import Contract, process_local, read_committed

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir()
source = out / 'input.jsonl'
source.write_bytes(b'{"t":1}\n{"t":12}\n')
contract = Contract({'version': 1, 'event_time': 't', 'fields': {'t': {'type': 'integer'}},
                     'window': {'size_ms': 10}, 'checks': [{'name': 'count', 'op': 'count', 'min': 1}]})
bundle = out / 'bundle'
process_local(contract, source, bundle)
(bundle / 'CURRENT.json').unlink()
before = sorted(p.name for p in bundle.iterdir())
results = {}
for label, action in [('consumer', lambda: list(read_committed(bundle, contract, input_path=source))),
                      ('producer', lambda: process_local(contract, source, bundle))]:
    try:
        action()
    except Exception as exc:
        results[label] = type(exc).__name__
    else:
        results[label] = 'ACCEPTED'
results['no_new_files'] = before == sorted(p.name for p in bundle.iterdir())
results['passed'] = results['consumer'] == results['producer'] == 'CheckpointError' and results['no_new_files']
(out / 'result.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
print(json.dumps(results))
raise SystemExit(not results['passed'])
