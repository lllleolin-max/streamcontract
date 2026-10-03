# Contributing

Keep the supported subset and output behavior explicit. Submit synthetic fixtures, a failing independent expectation and a focused change. Avoid adding connector wrappers before the single-lane state invariants hold. Use MIT-compatible contributions and never commit real payloads, credentials, virtual environments or generated wheels.

Build and install the wheel into a clean virtual environment, then run:

```sh
python -m unittest discover -s tests -v
python examples/workflow.py
python benchmarks/compare.py
```

Tests include an independent list-based aggregate oracle, exact time boundaries, rejected-event watermark isolation, transactional resource limits, every resume cut, CLI prefix mutation and parser/resource adversarial cases. New checkpoint formats require a version migration policy; currently incompatible contracts/formats reject and must replay input. Preserve fail-closed diagnostics and avoid including payloads in exceptions.

GitHub Actions targets Ubuntu and Windows, Python 3.11/3.14, installed wheel execution. CI YAML alone is not evidence of remote success. Document real review corrections and their before/after commits in `docs/ITERATIONS.md`. Benchmark results must disclose workload, order assumptions and adverse cases; do not imply unexecuted competitors were measured.
