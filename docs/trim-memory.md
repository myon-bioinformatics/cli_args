# Optional bounded-memory log trimming

`trim_output(text, bounded_memory=True)` retains only head/tail line spans rather
than allocating every line. Default behavior and speed remain unchanged.
This option preserves splitlines boundaries (including CRLF and Unicode separators),
omission counts and original-object return when text fits. The input string itself
is still held; this is not a streaming input API. Additional retained storage is
proportional to head+tail, plus output slices.

`python -S -m unittest discover -s tests -p test_trim_memory.py` passes two tests,
including seeded mixed separators, zero budgets and 100,000 lines.
`python -S scripts/benchmark_trim_memory.py` compares the pinned git baseline.

On CPython 3.12.14/Linux, 100,000 lines, head/tail 40, three alternating samples:
median traced temporary peak 7,607,007 → 14,622 bytes. Input was allocated before
tracing. Time under tracemalloc increased 55.5 → 288.0 ms, so memory reduction is
opt-in. These traced times are not ordinary production latency measurements.
Raw samples are in trim-memory-measurement.json. No build-time improvement or
additional dependency is claimed.
