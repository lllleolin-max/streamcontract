"""Installed SDK example: publish, resume, consume once by a stored cursor."""
from pathlib import Path
import sys
import tempfile

from streamcontract import Contract, process_local, read_committed
from streamcontract.contract import canonical

examples = Path(__file__).resolve().parent
contract = Contract.from_file(examples / 'contract.json')
source = examples / 'events.jsonl'
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary) / 'committed'
    process_local(contract, source, directory, stop_after=4, commit_every=2)
    cursor = 0
    for row in read_committed(directory, contract, input_path=source):
        sys.stdout.buffer.write(canonical(row) + b'\n')
        cursor = row['index']
    result = process_local(contract, source, directory, commit_every=2)
    for row in read_committed(directory, contract, input_path=source, after_index=cursor):
        sys.stdout.buffer.write(canonical(row) + b'\n')
        cursor = row['index']
    assert result['phase'] == 'finished' and cursor == result['total_outputs']
    assert list(read_committed(directory, contract, input_path=source, after_index=cursor)) == []
sys.stdout.buffer.flush()
