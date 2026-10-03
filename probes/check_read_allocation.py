"""Frozen allocation probe: a tiny checkpoint must not allocate its entire cap."""
import argparse
import json
from pathlib import Path
import tracemalloc
from streamcontract import Contract, process_local, read_committed

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir()
source = out / 'input.jsonl'
source.write_bytes(b'{"t":1}\n')
contract = Contract({'version': 1, 'event_time': 't', 'fields': {'t': {'type': 'integer'}},
                     'window': {'size_ms': 10}, 'limits': {'max_checkpoint_bytes': 100000000},
                     'checks': [{'name': 'count', 'op': 'count', 'min': 1}]})
bundle = out / 'bundle'
process_local(contract, source, bundle)
tracemalloc.start()
rows = list(read_committed(bundle, contract, input_path=source))
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
result = {'checkpoint_cap_bytes': contract.limits['max_checkpoint_bytes'],
          'actual_checkpoint_bytes': sum(p.stat().st_size for p in bundle.glob('*.checkpoint.json')),
          'output_records': len(rows), 'consumer_tracemalloc_peak_bytes': peak,
          'tiny_state_peak_below_5MB': peak < 5000000}
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))
raise SystemExit(not result['tiny_state_peak_below_5MB'])
