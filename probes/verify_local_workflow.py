"""Create-only installed SDK/actual console/consumer and bounded-scale checks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import tracemalloc

from streamcontract import Contract, Engine, process_local, read_committed
from streamcontract.contract import canonical
from streamcontract.cli import records  # warm the lazy producer import before measuring

parser = argparse.ArgumentParser()
parser.add_argument('--work', required=True, help='new evidence directory; refuses an existing path')
args = parser.parse_args()
work = Path(args.work).resolve()
work.mkdir()
repo = Path(__file__).resolve().parents[1]
contract_path = repo / 'examples/contract.json'
source_path = repo / 'examples/events.jsonl'
contract = Contract.from_file(contract_path)
command = Path(sysconfig.get_path('scripts')) / ('streamcontract.exe' if sys.platform == 'win32' else 'streamcontract')
assert command.is_file(), 'installed console command not found'


def run(argv, expected_code):
    result = subprocess.run(list(map(str, argv)), cwd=work, capture_output=True)
    assert result.returncode == expected_code, (result.returncode, expected_code, result.stderr.decode('utf-8', 'replace'))
    assert not result.stderr, 'unexpected console stderr'
    return [json.loads(line) for line in result.stdout.splitlines()]


base = [command, '--contract', contract_path, '--input', source_path]
expected = run(base, 2)
cuts = []
for cut in range(12):
    directory = work / f'console-cut-{cut}'
    paused = subprocess.run(list(map(str, base + ['--local-output', directory, '--stop-after', cut, '--commit-every', 2])), cwd=work, capture_output=True)
    assert paused.returncode in {0, 2} and not paused.stderr
    pause_receipt, = [json.loads(line) for line in paused.stdout.splitlines()]
    prefix = run([sys.executable, '-I', repo / 'examples/read_local.py', '--contract', contract_path,
                  '--input', source_path, '--local-output', directory], 0)
    finished, = run(base + ['--local-output', directory, '--commit-every', 2], 2)
    tail = run([sys.executable, '-I', repo / 'examples/read_local.py', '--contract', contract_path,
                '--input', source_path, '--local-output', directory, '--after-index', len(prefix)], 0)
    rows = prefix + tail
    assert [r['decision'] for r in rows] == expected
    assert len({r['output_id'] for r in rows}) == len(rows)
    pointer = (directory / 'CURRENT.json').read_bytes()
    repeated, = run(base + ['--local-output', directory], 2)
    assert repeated == finished and (directory / 'CURRENT.json').read_bytes() == pointer
    cuts.append({'cut': cut, 'pause_exit': paused.returncode, 'prefix_rows': len(prefix), 'total_rows': len(rows)})

declaration = {'version': 1, 'event_time': 't', 'fields': {'t': {'type': 'integer'}},
               'window': {'size_ms': 10}, 'checks': [{'name': 'count', 'op': 'count', 'min': 1}]}
scale_contract = Contract(declaration)
measurements = []
for count in (500, 5000):
    source = work / f'scale-{count}.jsonl'
    with source.open('xb') as file:
        for index in range(count):
            file.write(canonical({'t': index * 10}) + b'\n')
    oracle = Engine(scale_contract)
    expected_digest = hashlib.sha256()
    for index in range(count):
        for decision in oracle.push({'t': index * 10}):
            expected_digest.update(canonical(decision) + b'\n')
    for decision in oracle.finish() + [oracle.summary()]:
        expected_digest.update(canonical(decision) + b'\n')
    directory = work / f'scale-{count}-bundle'
    tracemalloc.start()
    receipt = process_local(scale_contract, source, directory)
    _, producer_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    tracemalloc.start()
    actual_digest, total = hashlib.sha256(), 0
    for row in read_committed(directory, scale_contract, input_path=source):
        actual_digest.update(canonical(row['decision']) + b'\n')
        total += 1
    _, consumer_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert actual_digest.digest() == expected_digest.digest() and total == count * 2 + 1
    largest_record = 0
    for path in directory.glob('*.outputs.jsonl'):
        with path.open('rb') as file:
            for line in file:
                largest_record = max(largest_record, len(line))
    measurements.append({'input_records': count, 'source_bytes': source.stat().st_size,
                         'output_records': total, 'generations': receipt['generation'],
                         'producer_tracemalloc_peak_bytes': producer_peak, 'consumer_tracemalloc_peak_bytes': consumer_peak,
                         'largest_output_record_bytes': largest_record,
                         'retained_bundle_bytes': sum(p.stat().st_size for p in directory.iterdir() if p.is_file()),
                         'all_decisions_equal_oracle': True})
result = {'actual_console_and_binary_consumer_pause_cuts': cuts, 'scale': measurements,
          'measurement_scope': 'Python tracemalloc peaks, not process RSS or hardware durability',
          'installed_package': __import__('streamcontract').__version__, 'passed': True}
(work / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2))
