"""Portable binary stdout consumer of one verified local commit snapshot."""
import argparse
import sys

from streamcontract import Contract, CheckpointError, read_committed
from streamcontract.contract import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--input', required=True, help='verify the committed source prefix')
    parser.add_argument('--local-output', required=True)
    parser.add_argument('--after-index', type=int, default=0)
    args = parser.parse_args()
    try:
        for row in read_committed(args.local_output, Contract.from_file(args.contract),
                                  input_path=args.input, after_index=args.after_index):
            sys.stdout.buffer.write(canonical(row) + b'\n')
        sys.stdout.buffer.flush()
        return 0
    except (CheckpointError, OSError, ValueError) as exc:
        sys.stdout.buffer.write(canonical({'kind': 'error', 'code': 'io_error' if isinstance(exc, OSError) else 'invalid_local_commit'}) + b'\n')
        sys.stdout.buffer.flush()
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
