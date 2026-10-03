"""Frozen measurement of redundant checkpoint generations at a pause boundary."""
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
receipt = process_local(contract, source, bundle, stop_after=1, commit_every=1)
manifests = sorted(bundle.glob('*.manifest.json'))
snapshots = sorted(bundle.glob('*.checkpoint.json'))
result = {'generation': receipt['generation'], 'manifest_files': len(manifests),
          'checkpoint_bytes': sum(p.stat().st_size for p in snapshots),
          'committed_records': len(list(read_committed(bundle, contract, input_path=source))),
          'one_batch_one_generation': len(manifests) == 1}
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))
raise SystemExit(not result['one_batch_one_generation'])
