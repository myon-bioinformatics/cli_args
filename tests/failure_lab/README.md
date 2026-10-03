# Negative evidence / failure lab

This directory intentionally contains tests that **must not all pass**.

The goal is to preserve failure behavior as evidence instead of treating every red child test as noise.
`run_lab.py` launches a child pytest process, writes raw JUnit/stdout/stderr, and then validates that the
failure taxonomy is exactly what the lab expected.

Current intentional cases cover:

- a normal passing test;
- an assertion failure;
- a setup/fixture error;
- a strict xfail (known antipattern);
- a strict XPASS, which is itself a failure because a supposedly-known failure unexpectedly passed.

The child pytest process is expected to return exit code 1. The outer CI job returns success only when:

1. the child process really failed;
2. raw JUnit was produced;
3. each named testcase was classified as expected;
4. the evidence files were preserved.

This is deliberately separate from the normal success JUnit collector. A second, dedicated shared
failure-identity job imports only this intentional-failure artifact, so expected red evidence cannot contaminate
the normal seven-report success contract.

This mechanism is for bounded exploration and regression evidence. It must not be used to relabel an unknown
or newly introduced product failure as "expected" merely to make CI green. Adding or changing an expected
failure requires an explicit testcase name and expected classification in `run_lab.py`.


The executable harness preserves UTC timestamp / level / logger diagnostics in `diagnostics.log`,
including traceback for unexpected harness exceptions. The JSON receipt adds UTC start/end times,
monotonic duration, Python/platform and available GitHub SHA/run/attempt provenance; local unavailable
GitHub values remain null. Child assertion/setup traceback remains in raw stdout/JUnit.
Previous raw artifacts are removed before each child launch, and duplicate testcase names are rejected.
Human diagnostics go to stderr; stdout remains the JSON receipt. These are test-only changes,
not a runtime logging configuration or a new workflow engine.
