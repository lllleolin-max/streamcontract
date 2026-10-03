# StreamContract

Validate JSONL ingestion contracts in bounded **event-time** windows and resume the same decision stream after a deliberate interruption. Python 3.11+, MIT, installable SDK and CLI. This is a local, single input lane validation component for ingestion engineers, not a distributed stream processor.

**中文：** 为 JSONL 摄取工程团队提供事件时间数据契约检查。字段合法仍可能发生窗口均值偏移；StreamContract 把乱序容忍、迟到隔离、聚合偏移和检查点恢复组成一条可复现的本地流程。输出明确的 `stage/release/quarantine/investigate/stop` 动作，检查点不保存原始事件。

## Install / 安装

From a cloned checkout (no PyPI release is claimed):

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install build
python -m build --wheel
python -m pip install dist/streamcontract-0.1.0-py3-none-any.whl
python -m unittest discover -s tests -v
```

## Useful first run / 可运行示例

```sh
streamcontract --contract examples/contract.json --input examples/events.jsonl
python examples/workflow.py
python examples/cli_workflow.py
python benchmarks/compare.py
```

The synthetic checkout fixture has 11 records: 9 accepted, 1 late, 1 invalid; three observed windows finalize, including one latency drift. The first CLI exits **2**, meaning data needs investigation/quarantine. `workflow.py` asserts every event/window decision and final summary equal after SDK checkpoint/resume. `cli_workflow.py` runs the actual CLI pause/resume, verifies the source prefix, compares concatenated decisions and rejects a damaged checkpoint. No customer data or adoption evidence is used.

**中文：** 首条命令按 1 秒事件窗口验证模拟 checkout 请求，均值基准为 100 ms、允许绝对偏移 25 ms；它定位一个偏移窗口、一条过迟事件和一条字段类型错误。两个 workflow 脚本分别验证 SDK 和 CLI 的恢复结果、源文件前缀与损坏检查点拒绝；compare 脚本实际运行行级检查、处理时间基线和两种机制消融。

Pause without declaring EOF, then verify and replay the consumed source prefix:

```sh
streamcontract --contract examples/contract.json --input examples/events.jsonl --stop-after 4 --checkpoint state.json
streamcontract --contract examples/contract.json --input examples/events.jsonl --resume state.json
```

The second command still exits 2 for the fixture's real issues. `--stop-after` counts **new records**, not total source lines. Save stdout from each segment and exclude each intermediate `summary` to compare the concatenated decision stream. A completed checkpoint cannot resume; use a pause for a growing file. Resume reads and hashes the consumed prefix, so changing a prior byte fails even when the filename stays the same.

## SDK

```python
from streamcontract import Contract, Engine, ResourceLimit

contract = Contract.from_file("examples/contract.json")
engine = Engine(contract)
for decision in engine.push({"event_ms": 100, "service": "checkout",
                             "latency_ms": 100, "request_id": "synthetic"}, sequence=1):
    print(decision)
raw = engine.checkpoint()
resumed, source = Engine.restore(contract, raw, expected_sequence=1)
for decision in resumed.finish():  # explicit end-of-stream, permanently terminal
    print(decision)
```

An `ACCEPTED/stage` event has **not** passed its aggregate contract yet. `window/release` applies only to accepted events in that observed group/window. Invalid and late events have independent quarantine decisions. Callers must retain/retrieve payloads upstream if they need to quarantine actual records; this engine retains only sufficient statistics. `ResourceLimit` leaves the event and sequence unconsumed; retry that sequence after an operational change or replay under a revised contract. Revised contracts cannot resume old checkpoints.

## Contract and operational rules

See [contract reference](docs/CONTRACT.md), [architecture and recovery boundaries](docs/ARCHITECTURE.md), [comparison and bounded buyer rationale](docs/COMPARISON.md), [security](SECURITY.md), and [development](CONTRIBUTING.md).

- Flat primitive fields only, exact declared names, strict types (`bool` is not a number), optional enum/range/string-length checks. Unknown fields/options fail closed.
- Integer epoch milliseconds, epoch-aligned `[start, end)` tumbling windows. Watermark is `max_accepted_timestamp - watermark_delay_ms`.
- A record is too late when the **previous** watermark is `>= end + allowed_lateness_ms`. Accepted records update the watermark; windows finalize once at that deadline. There are no provisional/retraction outputs.
- `count/sum/mean/min/max` checks use exact rational accumulators for parsed binary floats and integers. Inclusive bounds plus fixed-reference absolute drift; minimum sample size produces `INSUFFICIENT`, never a fabricated pass.
- Active windows, per-window groups, per-group events, input bytes and checkpoint bytes have explicit limits. No sampling or silent eviction.
- CLI stdout is JSONL, no raw payloads. Exit codes: `0` completed clean or paused without issues; `2` contract/late/invalid/empty issues; `3` incompatible checkpoint, IO failure or state limit; `argparse` usage errors exit `2` with stderr.

Empty streams emit `EMPTY/investigate`; absent groups/windows are not synthesized. This is not a completeness monitor for an expected calendar, deduplication engine, anomaly model, authenticated provenance service or exactly-once sink. Global watermark assumes a caller-controlled merged lane; a future timestamp can close older windows. See the unfavorable benchmark scenario before choosing the delay/lateness budget.

## Evidence status

Tests and executable examples are the acceptance surface. [Iteration history](docs/ITERATIONS.md) records real post-initial repairs and named commit evidence. Checked-in GitHub Actions covers Ubuntu/Windows and Python 3.11/3.14; remote execution is unknown until publication. Commercial willingness to pay, users, revenue and independently awarded scores are unknown.
