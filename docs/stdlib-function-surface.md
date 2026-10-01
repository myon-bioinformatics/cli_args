# Standard-library function surface

The standard library is not only a set of importable modules and `python -m` commands. Many small helpers that are often reimplemented in project code already exist as stable functions, classes, and protocols.

For AI coding, use this question before creating a new helper or adding a dependency:

> Is this already a small standard-library operation with a clearer contract?

Do not wrap these APIs merely to rename them. Prefer the original function/type unless the project has a real domain contract to add.

## High-leverage surfaces

| Need that is often reimplemented | Prefer |
| --- | --- |
| human-readable stdout, separators, terminators, alternate stream | built-in `print(..., sep=, end=, file=, flush=)` |
| readable nested Python values | `pprint.pprint` / `pprint.pformat(indent=, width=, compact=, sort_dicts=)` |
| machine-readable structured text | `json.dumps` / `json.dump` |
| dedent / wrap / indent prose | `textwrap.dedent`, `fill`, `indent` |
| shell-like token parsing / diagnostic argv rendering | `shlex.split` / `shlex.join` |
| path composition / traversal / suffix handling | `pathlib.Path` |
| scratch files and directories | `tempfile.TemporaryDirectory`, `NamedTemporaryFile` |
| copy / move / remove trees and executable lookup | `shutil` |
| counting / queues / grouped defaults | `collections.Counter`, `deque`, `defaultdict` |
| lazy iteration / slicing / chaining | `itertools` |
| function adaptation / caching | `functools.partial`, `lru_cache` |
| context/resource composition | `contextlib.contextmanager`, `ExitStack`, `redirect_stdout` |
| text diffs | `difflib.unified_diff` |
| CSV | `csv.reader` / `csv.writer` / Dict variants |
| INI-style configuration | `configparser.ConfigParser` |
| hashes / digests | `hashlib` |
| URL quoting/parsing/joining | `urllib.parse` |
| simple records / state values | `dataclasses.dataclass`, `enum.Enum` |
| standard diagnostics | `logging` |
| CLI parsing / process execution | `argparse` / `subprocess` |
| bounded thread/process work | `concurrent.futures` |

The list is a discovery index, not a mandate. A domain-specific abstraction is still appropriate when it adds validation, provenance, bounds, evidence, or a stable project contract.

## Output is a particularly strong example

Python's built-in `print` already supports behavior that frequently grows custom helpers elsewhere:

```python
print("a", "b", sep=" | ", end="\n")
print(value, file=sys.stderr, flush=True)
```

For nested values, use `pprint` before inventing a formatter:

```python
from pprint import pformat

text = pformat(
    value,
    indent=2,
    width=80,
    compact=True,
    sort_dicts=False,
)
```

For a machine contract, use JSON rather than parsing pretty output.

The three surfaces are intentionally different:

- `print`: direct human/output-stream behavior.
- `pprint`: readable representation of Python values.
- `json`: interoperable machine-readable data.

Do not silently substitute one for another.

## Paths and temporary state

Prefer a temporary context rather than ad-hoc names under the checkout:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

with TemporaryDirectory() as raw:
    root = Path(raw)
    (root / "result.txt").write_text("ok\n", encoding="utf-8", newline="\n")
```

This is especially useful for AI-generated diagnostics and experiments: the repository stays clean, cleanup is automatic, and tests can be isolated.

## Exact argv and shell diagnostics

`cli_args.Command` intentionally owns an **argv tuple**, not a shell command string. When a human-readable shell-like representation is needed for logs, use `shlex.join` as a diagnostic representation; do not execute it through a shell.

```python
from shlex import join

display = join(["git", "status", "--short"])
```

Conversely, `shlex.split` is for deliberately parsing shell-like text. Do not use it to split an argv token that is already structured.

## Representative measured behavior in PR #1

`tests/test_stdlib_functions.py` keeps representative behaviors executable on the supported Python floor:

- `print` separator/end/file behavior;
- `pprint.pformat` indentation, width and insertion-order preservation;
- `textwrap` dedent/indent/fill;
- `shlex` split/join roundtrip for spaces and Unicode;
- `pathlib` + `TemporaryDirectory`;
- `Counter` / `deque`;
- `itertools.chain` / `islice`;
- `functools.partial` / `lru_cache`;
- `contextlib.redirect_stdout` / `ExitStack`;
- `difflib.unified_diff`;
- CSV and ConfigParser roundtrips;
- SHA-256 and URL quote/unquote behavior.

These tests are not here because the Python standard library itself needs retesting. They are evidence for **the repository's recommended usage contract and Python 3.10+ floor**, and they prevent documentation examples from drifting into newer-only APIs.

## What not to do

Avoid creating local helpers whose only behavior is one of these:

- `pretty(value)` that only calls `pprint.pformat`;
- `tmpdir()` that only wraps `TemporaryDirectory`;
- `safe_join_argv()` that only wraps `shlex.join`;
- `sha256_file()` with no project-specific bounds/streaming/provenance contract;
- `read_csv()` that only forwards to `csv.DictReader`.

A wrapper becomes worthwhile when it adds a real contract: bounds, encoding policy, domain validation, error taxonomy, provenance, evidence identity, or compatibility behavior used by several consumers.
