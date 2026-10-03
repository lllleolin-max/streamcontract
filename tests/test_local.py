"""Local commit correctness against the existing engine and real killed writers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from streamcontract import CheckpointError, Contract, Engine, ResourceLimit, process_local, read_committed
from streamcontract.cli import records
from streamcontract.contract import canonical, strict_json
from test_engine import spec, event


def oracle(contract, path):
    engine, result = Engine(contract), []
    with path.open('rb') as file:
        for raw, _ in records(file, contract.limits['max_event_bytes']):
            try:
                if raw is None:
                    decisions = engine.reject('event_bytes_limit')
                else:
                    try:
                        value = strict_json(raw)
                    except UnicodeDecodeError:
                        decisions = engine.reject('invalid_utf8')
                    except (ValueError, OverflowError, RecursionError):
                        decisions = engine.reject('invalid_json')
                    else:
                        decisions = engine.push(value)
            except ResourceLimit as exc:
                result += [{'kind': 'error', 'status': 'RESOURCE_LIMIT', 'action': 'stop',
                            'limit': exc.limit, 'next_sequence': exc.sequence, 'consumed': False}, engine.summary()]
                return result
            result += decisions
    return result + engine.finish() + [engine.summary()]


WORKER = r'''
import json, os, sys, time
from pathlib import Path
from streamcontract import Contract, process_local
import streamcontract.local as local
contract, source, bundle, marker, selected = map(Path, sys.argv[1:])
stage_name = str(selected)
def hook(stage):
    if stage_name == 'terminal_published':
        if stage != 'after_publish': return
        pointer = json.loads((bundle / 'CURRENT.json').read_bytes())
        manifest = json.loads((bundle / (pointer['commit']['name'] + '.manifest.json')).read_bytes())
        if manifest['phase'] != 'finished': return
    elif stage != stage_name:
        return
    with marker.open('xb') as file:
        file.write(stage.encode()); file.flush(); os.fsync(file.fileno())
    while True: time.sleep(1)
local._transition_hook = hook
process_local(Contract.from_file(contract), source, bundle, commit_every=2)
'''


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = Contract(spec())
        self.source = self.root / 'input.jsonl'
        self.source.write_bytes(b''.join(canonical(event(t, x, key)) + b'\n'
            for t, x, key in [(1, 0, 'a'), (2, 1, 'b'), (12, 0, 'a'), (14, -0.0, 'b'), (31, 2, 'a')]))

    def rows(self, directory, **kw):
        return list(read_committed(directory, self.contract, input_path=self.source, **kw))

    def test_examples_every_pause_cut_and_multiwindow(self):
        examples = Path(__file__).resolve().parents[1] / 'examples'
        self.contract = Contract.from_file(examples / 'contract.json')
        self.source.write_bytes((examples / 'events.jsonl').read_bytes())
        expected = oracle(self.contract, self.source)
        self.assertEqual(len(self.source.read_bytes().splitlines()), 11)
        for cut in range(12):
            with self.subTest(cut=cut):
                directory = self.root / f'cut-{cut}'
                process_local(self.contract, self.source, directory, stop_after=cut, commit_every=2)
                prefix = self.rows(directory)
                cursor = len(prefix)
                process_local(self.contract, self.source, directory, commit_every=2)
                rows = prefix + self.rows(directory, after_index=cursor)
                self.assertEqual([r['decision'] for r in rows], expected)
                self.assertEqual(len({r['output_id'] for r in rows}), len(rows))
                before = (directory / 'CURRENT.json').read_bytes()
                process_local(self.contract, self.source, directory)
                self.assertEqual((directory / 'CURRENT.json').read_bytes(), before)
        self.contract = Contract(spec(watermark_delay_ms=100))
        self.source.write_bytes(b''.join(canonical(event(t)) + b'\n' for t in [1, 12, 23, 1000]))
        expected = oracle(self.contract, self.source)
        self.assertEqual(sum(r['kind'] == 'window' and r['sequence'] == 4 for r in expected), 4)
        for cut in range(5):
            directory = self.root / f'multi-{cut}'
            process_local(self.contract, self.source, directory, stop_after=cut, commit_every=1)
            process_local(self.contract, self.source, directory, commit_every=1)
            self.assertEqual([r['decision'] for r in self.rows(directory)], expected)

    def test_invalid_late_oversized_and_resource_every_cut(self):
        cases = [b'not-json\n', b'\xff\n', b'{"t":1,"t":2}\n', b'{"t":NaN}\n',
                 b'x' * 1000 + b'\n', canonical(event(1)) + b'\n', canonical(event(100)) + b'\n',
                 canonical(event(0)) + b'\n']
        declaration = spec()
        declaration['limits'] = {'max_event_bytes': 100}
        self.contract = Contract(declaration)
        self.source.write_bytes(b''.join(cases))
        expected = oracle(self.contract, self.source)
        for cut in range(len(cases) + 1):
            directory = self.root / f'invalid-{cut}'
            process_local(self.contract, self.source, directory, stop_after=cut, commit_every=2)
            process_local(self.contract, self.source, directory, commit_every=2)
            self.assertEqual([r['decision'] for r in self.rows(directory)], expected)
        declaration = spec()
        declaration['limits'] = {'max_groups_per_window': 1}
        self.contract = Contract(declaration)
        self.source.write_bytes(canonical(event(1, key='a')) + b'\n' + canonical(event(2, key='b')) + b'\n')
        expected = oracle(self.contract, self.source)
        for cut in range(3):
            directory = self.root / f'resource-{cut}'
            process_local(self.contract, self.source, directory, stop_after=cut, commit_every=1)
            result = process_local(self.contract, self.source, directory)
            self.assertEqual(result['exit_code'], 3)
            self.assertEqual(result['summary']['sequence'], 1)
            self.assertEqual([r['decision'] for r in self.rows(directory)], expected)
            before = (directory / 'CURRENT.json').read_bytes()
            process_local(self.contract, self.source, directory)
            self.assertEqual((directory / 'CURRENT.json').read_bytes(), before)

    def test_actual_process_interruptions_and_terminal_publish(self):
        declaration = self.root / 'contract.json'
        declaration.write_bytes(canonical(self.contract.to_dict()))
        expected = oracle(self.contract, self.source)
        for stage in ('stage_record_written', 'output_fsynced', 'checkpoint_fsynced',
                      'manifest_fsynced', 'before_publish', 'after_publish', 'directory_fsynced', 'terminal_published'):
            with self.subTest(stage=stage):
                directory = self.root / stage
                process_local(self.contract, self.source, directory, stop_after=1)
                marker = self.root / (stage + '.marker')
                child = subprocess.Popen([sys.executable, '-c', WORKER, str(declaration), str(self.source),
                                          str(directory), str(marker), stage], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 20
                    while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(marker.exists(), child.communicate(timeout=2) if child.poll() is not None else 'marker timeout')
                    if stage == 'stage_record_written':
                        with self.assertRaises(CheckpointError):
                            process_local(self.contract, self.source, directory)
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.communicate(timeout=10)
                committed = self.rows(directory)
                self.assertEqual([r['decision'] for r in committed], expected[:len(committed)])
                cursor = len(committed)
                process_local(self.contract, self.source, directory, commit_every=2)
                all_rows = committed + self.rows(directory, after_index=cursor)
                self.assertEqual([r['decision'] for r in all_rows], expected)
                self.assertEqual(len({r['output_id'] for r in all_rows}), len(all_rows))

    def test_corrupt_files_rejected_before_any_consumer_output(self):
        for suffix in ('.outputs.jsonl', '.checkpoint.json', '.manifest.json', 'CURRENT.json'):
            directory = self.root / suffix.lstrip('.')
            process_local(self.contract, self.source, directory, commit_every=2)
            files = [directory / suffix] if suffix == 'CURRENT.json' else sorted(directory.glob('*' + suffix))
            target = files[0]
            target.write_bytes(target.read_bytes()[:-1])
            iterator = read_committed(directory, self.contract, input_path=self.source)
            with self.assertRaises(CheckpointError):
                next(iterator)
            with self.assertRaises(CheckpointError):
                process_local(self.contract, self.source, directory)

    def test_prefix_contract_foreign_bundle_and_create_only(self):
        directory = self.root / 'bundle'
        process_local(self.contract, self.source, directory, stop_after=2)
        before = (directory / 'CURRENT.json').read_bytes()
        self.source.write_bytes(self.source.read_bytes().replace(b'"t":1', b'"t":0', 1))
        with self.assertRaises(CheckpointError):
            process_local(self.contract, self.source, directory)
        self.assertEqual((directory / 'CURRENT.json').read_bytes(), before)
        with self.assertRaises(CheckpointError):
            list(read_committed(directory, Contract(spec(size_ms=20))))
        foreign = self.root / 'unrelated'
        foreign.mkdir()
        sentinel = foreign / 'CURRENT.json'
        sentinel.write_bytes(b'keep')
        with self.assertRaises((CheckpointError, OSError)):
            process_local(self.contract, self.source, foreign)
        self.assertEqual(sentinel.read_bytes(), b'keep')
        with self.assertRaises((CheckpointError, OSError)):
            process_local(self.contract, self.source, self.source)
        with self.assertRaises(CheckpointError):
            process_local(self.contract, directory / 'CURRENT.json', directory)
        with self.assertRaises(CheckpointError):
            list(read_committed(directory, self.contract, after_index=True))

    def test_checkpoint_limit_keeps_prior_commit(self):
        declaration = spec()
        declaration['limits'] = {'max_checkpoint_bytes': 500}
        self.contract = Contract(declaration)
        directory = self.root / 'small-state'
        # Empty v3 state fits, populated state exceeds this explicit cap.
        process_local(self.contract, self.source, directory, stop_after=0)
        pointer = (directory / 'CURRENT.json').read_bytes()
        with self.assertRaises(ResourceLimit):
            process_local(self.contract, self.source, directory, commit_every=1)
        self.assertEqual((directory / 'CURRENT.json').read_bytes(), pointer)
        self.assertEqual(self.rows(directory), [])

    def test_rebound_schema_and_output_parser_fail_closed(self):
        import shutil
        baseline = self.root / 'template'
        process_local(self.contract, self.source, baseline)

        def rebound(directory, raw=None, mutate=None):
            pointer_path = directory / 'CURRENT.json'
            pointer = json.loads(pointer_path.read_bytes())
            name = pointer['commit']['name']
            manifest_path = directory / (name + '.manifest.json')
            manifest = json.loads(manifest_path.read_bytes())
            if raw is not None:
                (directory / (name + '.outputs.jsonl')).write_bytes(raw)
                manifest['output_bytes'] = len(raw)
                manifest['output_sha256'] = hashlib.sha256(raw).hexdigest()
            if mutate is not None:
                mutate(manifest)
            encoded = canonical(manifest)
            manifest_path.write_bytes(encoded)
            pointer['commit']['sha256'] = hashlib.sha256(encoded).hexdigest()
            pointer_path.write_bytes(canonical(pointer))

        mutations = [lambda m: m.update(phase=[]), lambda m: m.update(generation=True),
                     lambda m: m.update(output_count=1.0), lambda m: m.update(exit_code=False),
                     lambda m: m['source'].update(lines=True), lambda m: m['source'].update(prefix_sha256='0'*64),
                     lambda m: m['summary'].update(sequence=True), lambda m: m.update(store_id='0'*32)]
        for index, mutate in enumerate(mutations):
            directory = self.root / f'rebound-{index}'
            shutil.copytree(baseline, directory)
            rebound(directory, mutate=mutate)
            with self.assertRaises(CheckpointError):
                next(read_committed(directory, self.contract))
        bad_lines = [b'\xef\xbb\xbf{}\n', b'\xff\n', b'{"version":1,"version":1}\n',
                     b'{"value":NaN}\n', b'{"value":Infinity}\n', b'{"value":1e999}\n',
                     b'{"value":"\\ud800"}\n', b'{}', b'x' * 262145 + b'\n']
        pointer = json.loads((baseline / 'CURRENT.json').read_bytes())
        original = (baseline / (pointer['commit']['name'] + '.outputs.jsonl')).read_bytes()
        lines = original.splitlines(keepends=True)
        bad_lines += [lines[1] + lines[0] + b''.join(lines[2:]), lines[0] + original, b''.join(lines[:-1])]
        for index, raw in enumerate(bad_lines):
            directory = self.root / f'parser-{index}'
            shutil.copytree(baseline, directory)
            rebound(directory, raw=raw)
            with self.assertRaises(CheckpointError):
                next(read_committed(directory, self.contract))

    def test_noop_pause_preserves_files_and_earlier_metadata_binding(self):
        directory = self.root / 'no-op'
        process_local(self.contract, self.source, directory, stop_after=1)
        names = sorted(p.name for p in directory.iterdir())
        for _ in range(3):
            process_local(self.contract, self.source, directory, stop_after=0)
        self.assertEqual(sorted(p.name for p in directory.iterdir()), names)
        process_local(self.contract, self.source, directory)
        # Rehashing an ancestor summary alone cannot detach it from its snapshot.
        pointer_path = directory / 'CURRENT.json'
        pointer = json.loads(pointer_path.read_bytes())
        latest_path = directory / (pointer['commit']['name'] + '.manifest.json')
        latest = json.loads(latest_path.read_bytes())
        parent_path = directory / (latest['parent']['name'] + '.manifest.json')
        parent = json.loads(parent_path.read_bytes())
        parent['summary']['sequence'] = 0
        encoded = canonical(parent)
        parent_path.write_bytes(encoded)
        latest['parent']['sha256'] = hashlib.sha256(encoded).hexdigest()
        encoded = canonical(latest)
        latest_path.write_bytes(encoded)
        pointer['commit']['sha256'] = hashlib.sha256(encoded).hexdigest()
        pointer_path.write_bytes(canonical(pointer))
        with self.assertRaises(CheckpointError):
            next(read_committed(directory, self.contract))

    def test_exact_batch_pause_avoids_redundant_snapshot(self):
        directory = self.root / 'exact-batch'
        receipt = process_local(self.contract, self.source, directory, stop_after=1, commit_every=1)
        self.assertEqual(receipt['generation'], 1)
        self.assertEqual(len(list(directory.glob('*.manifest.json'))), 1)
        self.assertEqual(len(list(directory.glob('*.outputs.jsonl'))), 1)
        process_local(self.contract, self.source, directory, commit_every=1)
        self.assertEqual([r['decision'] for r in self.rows(directory)], oracle(self.contract, self.source))


if __name__ == '__main__':
    unittest.main()
