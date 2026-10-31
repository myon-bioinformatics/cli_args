# cli_args

<p align="center">
  <img src="docs/brand/icon.png" alt="cli_args icon" width="160" />
</p>

[Icon](docs/brand/icon.png) · [Favicon](docs/brand/favicon.png)

A single-file, standard-library-only Python toolkit for reusable CLI argument definitions, validation, command construction, execution, and JSON/text output, backed by practical CLI tests.

Python 3.10+. Vendor it by copying `cli_args.py`. The module runs on the standard library alone and does no argument parsing or command execution at import time. Packaging for pip is out of scope for the initial version.

## Reusing argument definitions

`argparse`'s `choices` / `required` / `nargs` / `action` / `type` are used as-is. Abbreviated option names are rejected by default.

```python
import argparse
from cli_args import Argument, parse_args

args = parse_args([
    Argument(("--mode",), {"choices": ("read", "convert"), "required": True}),
    Argument(("--enabled",), {"action": argparse.BooleanOptionalAction}),
    Argument(("files",), {"nargs": "+"}),
], ["--mode", "read", "--no-enabled", "a.html", "b.html"])
```

For finer control, call `add_argument()` or `add_mutually_exclusive_group()` directly on the parser returned by `make_parser()`. `Argument.names`, an explicit `parse_args(..., argv=...)`, and `require_when(..., required=...)` all take an ordered, finite sequence; a single string or implicit expansion of a set/dict/generator is rejected. `require_when(parser, args, when=..., required=["output"])` rejects, via `parser.error()`, any listed item whose value is `None` when the condition holds. `False` and `0` count as given values.

`add_output_arguments(parser)` adds `--format text/json` and `--output`; `add_execution_arguments(parser)` adds `--dry-run` / `--timeout` / `--cwd`. Pick only the sets you need and avoid name clashes on the caller side.

## Building commands

```python
from cli_args import Command, run_command, write_output

command = (Command(("git",))
    .option("-C", "/path/to/repository")
    .positional("status")
    .flag("--short"))
result = run_command(command, timeout=10)
write_output(result, format="json")
```

| Method | Behavior |
|---|---|
| `flag(name, enabled)` | Added only when the bool is True |
| `option(name, value)` | Adds the name and value. None is omitted; an empty string is kept |
| `option(..., attached=True)` | Adds `--name=value`. Use when the target supports it |
| `repeated(name, values)` | Repeats, as in `-H value1 -H value2`. `values` must be a multi-token collection |
| `multiple(name, values)` | Lists values, as in `--files a b`. `values` must be a multi-token collection |
| `positional(*values)` | Adds positional arguments in the given order |
| `passthrough(values, separator=False)` | Appends argv as-is. Prepends `--` only when `separator=True`. `values` must be a multi-token collection |

The meaning of each command and its valid combinations are defined by the caller. Pass arguments as strings or text paths, and convert numbers to strings explicitly. No shell expansion, quote interpretation, or string splitting is done. The collection arguments of `repeated()` / `multiple()` / `passthrough()` accept only ordered, finite `Sequence`s (list/tuple, etc.). A single `str` / `PathLike`, an unordered set/dict, or a one-shot generator is rejected with `TypeError`, so that argv order and reproducibility are part of the API contract. To add a single token, use `option()` / `positional()`.

`pytest_command(paths, quiet=True, tb="short", summary=True, extra=[...])` is an optional preset that builds `python -m pytest -q --tb short -ra ...`. `paths` and `extra` also accept only ordered, finite `Sequence`s; a single `str` / `PathLike`, set/dict, or generator is rejected. pytest is not imported by the module and is never auto-installed. This repository's own tests run with `uv run --locked pytest`. `pytest_command` only builds the target pytest CLI; it does not call uv.

## Running Node.js from argv

`node_command(target, *args, node=None, node_flags=())` builds `[node, *node_flags, target, *args]`. `run_node(...)` is a thin wrapper over `run_command()` and keeps the existing execution contract (`timeout` / `max_output_bytes` / `env` / `dry_run`, etc.). `dry_run` rejects non-bool values with `TypeError`; a string is never treated as false and executed. With `dry_run=True`, neither the `node --version` probe nor a child process runs; only the argv[0] token following the lookup order is built (the last fallback is the literal `node`). `is_node_target(path)` checks for `.js` / `.cjs` / `.mjs`. `node_or_command([])` raises `ValueError`, as `Command(())` does.

Node lookup order: the `node=` argument, `--node`, and `CLI_ARGS_NODE` are **explicit** and do not fall back on failure. After those, the `NODE` environment variable and `shutil.which('node')` are tried. Windows `.cmd` / `.bat` wrappers are rejected; the executable found is checked once with `node --version` within 5 seconds and must be Node 24 or later (the probe is skipped under `dry_run`). Not found, too old, or timed out raises `NodeNotFoundError` (a `FileNotFoundError` subclass, message `cli_args: node …`). The child's exit code is passed through in `returncode`. `shell=True` is never used. `engines.node` in `package.json` is also **>=24**.

To opt in from a CLI, `add_node_arguments(parser)` adds `--node PATH` and a repeatable `--node-flag` (use the `--node-flag=--import=x` form when the value starts with `-`); call `node_or_command(argv, node=args.node, node_flags=args.node_flags)` right before building the argv to run. It wraps the argv with Node only when the first token is `.js` / `.cjs` / `.mjs`, and otherwise returns `Command(argv)` unchanged. Existing argv semantics are unchanged unless you use this helper.

```python
from cli_args import node_command, run_node, node_or_command

result = run_node("tools/probe.cjs", "--", "-flag", "", "日本 語", timeout=30)
command = node_or_command(["playwright.cjs", "test", "--list"], node_flags=["--no-warnings"])
```

## Calling `cli_args.py` from Node.js

To use the Python-side `run_command` / `render_output` from Node 24+, require `cli_args.cjs` at the repository root. `cli_args.cjs` rejects Node older than 24 at call time. It only launches `cli_args.py run` / `render` through the parent repository `myon-bioinformatics`'s shared launcher `vendor/py_launch.cjs`; it never launches Node from Node. `shell: true` is not used. The stdin limit is `py_launch`'s `maxInputBytes` (`CLI_STDIN_MAX_BYTES`, 4 MiB), and response capture is `responseMaxBytes` (96 MiB; `maxBuffer` adds only the shared 512-byte margin).

| Lookup | Meaning |
|---|---|
| `opts.python` / `runCommand(..., { python })` | Explicit (no fallback on failure) |
| `CLI_ARGS_PYTHON` | Explicit environment variable (`py_launch`'s `envVar`) |
| `PYTHON` → `python3` → `python` (`py -3` on Windows) | Automatic lookup |

```javascript
const {runCommand, render} = require("./cli_args.cjs");

const result = runCommand(["git", "status", "--short"], {cwd: "/path/to/repo", timeout: 30});
console.log(result.returncode, result.stdout, result.stdout_b64);

const text = render({title: "日本語"}, "json");
```

Running it directly as a CLI has the same contract as `node cli_args.cjs run` (JSON on stdin) or `node cli_args.cjs render --format json` (value on stdin). Invalid JSON or unknown fields make Python exit 2, which surfaces as `CliArgsRequestError` in the library API. An interpreter launch failure is `cli_args Python process failed: …`.

**Behavior change (#27):** if Node's `runCommand` omits `opts.max_output`, Python is **always** sent `max_output: CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES` (4 MiB). The earlier Node wrapper was close to unlimited, but the bridge cuts the child's combined stdout/stderr at 4 MiB. For larger output, set `opts.max_output` explicitly (up to `CLI_RUN_MAX_OUTPUT_BYTES`, 8 MiB). Calling `python -S cli_args.py run` directly is still unlimited when `max_output` is omitted.

Node adds `response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES` (96 MiB) to `run` requests, and Python checks **the UTF-8 length of the JSON it actually serialized** against that limit before writing to stdout. Exceeding it exits **1** (`response exceeds response_max_bytes` on stderr). The Node-side spawn buffer is only `py_launch`'s `responseMaxBytes` (with `CLI_HOST_RESPONSE_MARGIN_BYTES` added internally); no JSON size estimate is used. `render` performs the same check with `--response-max-bytes CLI_RENDER_RESPONSE_MAX_BYTES`. `run` JSON always includes `output_limited` (`false` is not omitted).

The vendored launcher is byte-for-byte from parent commit
`1116d5c4f55d25af4d21cfe9b3c88f49d3a476fa` (parent PR #171).
`noSite: true` now covers interpreter discovery as well as execution.
The shared launcher's opt-in `isolated` flag also covers discovery; it remains off
for this entry. On POSIX, repeated SIGINT/SIGTERM are forwarded until the Python
child exits, including when it handles an earlier signal and keeps running.
Launcher signal failures still exit 2 in text and JSON diagnostic modes.
Node >=24 and the existing runtime CI lanes are unchanged.

## Passing stdin explicitly (collected from cross-repo use)

`run_command(command, stdin=...)` passes any **str (encoded to UTF-8) or bytes (unchanged)** to the child process once. No trailing newline is added and no shell is used. `None` means no input.

```python
from cli_args import Command, run_command
import sys

# JSON stdin worker such as Flutter's. Pass the generated JSON string as-is.
result = run_command(
    Command((sys.executable, "-S", "worker.py")),
    stdin='{"operation":"inspect","values":["日本語"]}',
    timeout=5,
)
assert result.returncode == 0

# Git NUL-safe pathspec. Sends names with spaces or a leading - exactly.
git = Command(("git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"))
result = run_command(git, stdin=b"-leading name.txt\0", timeout=10)
```

`run_command()` handles only synchronous, finite input; file objects and iterators are not accepted as stdin. Streaming/bidirectional batch protocols and long-running resident processes are not supported. Dry-run validates type and UTF-8 encoding but never prints the input, so secrets are not leaked. The existing UTF-8 replacement policy for stdout/stderr and the exit/timeout contract are unchanged.

Cross-repo examples: `flutter_navigation_basic`'s stdin JSON, `browser-test-kit`'s stdin-based child-process tests, and external CLI wrappers such as `gh_identity`. Argument parsing and domain-specific rules stay in each project. Git NUL pathspecs and finite `git cat-file --batch-command --buffer -Z` calls are **verified against real Git**. Interactive, long-running bidirectional sessions are not supported.

## Output protection and byte limits

`write_output(..., overwrite=False)` is an opt-in that **never overwrites an existing path**. For an existing file, symlink, or broken symlink it raises `FileExistsError` without deleting the target. The content is rendered first, saved to a temporary file in the destination directory, and then published with an exclusive hard link. The default `overwrite=True` keeps the previous behavior. On filesystems without hard-link support it fails safe. Making a new path visible is atomic, but crash durability, fsync, protection against third-party changes after publishing, and automatic creation of missing directories are not guaranteed.

`run_command(..., max_output_bytes=N)` caps capture at the **combined raw byte count** of stdout/stderr and stops the child process when exceeded. Output kept in memory totals at most N bytes, and `CommandResult.output_limited=True` with `returncode=None` distinguishes it from a normal success. The default `None` is the previous unlimited mode, and the existing JSON shape is kept when omitted. When the limit is hit, the display may be cut in the middle of a UTF-8 character; decoding stays `errors="replace"` as before. Only the launched child is monitored; stopping the whole descendant tree is not guaranteed.

```python
result = run_command(Command(("git", "status")), max_output_bytes=65536, timeout=10)
if result.output_limited:
    raise RuntimeError("command output exceeded limit")
write_output({"ok": True}, format="json", output="result.json", overwrite=False)
```

`examples/run_cli.py` exposes `--max-output-bytes N`, `--no-overwrite`, `--stdin TEXT` / `--stdin-file PATH` (mutually exclusive), and `--env KEY=VALUE` (repeatable). Exceeding the output limit exits **125**, a timeout exits **124** as before, and failing to create the file or read the stdin file exits **1**. CLI options go before `--`; the external command argv goes after it.

## Handing long output to the reader (explicit omissions, pytest deciding lines)

`trim_output(text, head=40, tail=40)` keeps the first `head` lines and the last `tail` lines, with a single `... N line(s) omitted ...` line in between. Output cut with plain `head`/`tail` looks complete even when lines are missing, so the omission is made explicit for the reader (human or agent). Output that fits is returned unchanged.

`pytest_summary(output)` returns only the lines in captured pytest output that decide the result: the final `N failed, M passed in Xs` line (`summary`/`counts`), `-ra` `FAILED`/`ERROR` lines (`failed`/`errors`), pytest-cov's `TOTAL` line and the `Required test coverage` verdict (`coverage`), and `deciding_lines` with the first `E` line of each failure and any `INTERNALERROR` (60 lines by default; excess sets `truncated`).

```python
result = run_command(pytest_command(["tests"], quiet=True, summary=True), timeout=600)
digest = pytest_summary(result.stdout)
print(digest["summary"], digest["failed"], digest["coverage"]["required_met"])
print(trim_output(result.stdout, head=20, tail=40))
```

## Execution and output

```bash
python -S examples/run_cli.py --format json --dry-run -- git status --short
python -S examples/run_cli.py --format json --output result.json --timeout 30 -- uv run --locked pytest -q --tb=short -ra
```

`cli_args.py` itself also has a machine-facing entry point that hosts such as Node can call with `python -S cli_args.py` (argv is not parsed at import time).

| Subcommand | Input | Output |
|---|---|---|
| `run` | JSON request on stdin | `CommandResult` as JSON on stdout |
| `render --format text\|json` | Any JSON value on stdin | Result of `render_output` on stdout |

The `run` JSON object takes `argv` (required) and optionally `timeout` / `cwd` / `env` / `input` / `max_output` / `dry_run`. stdin is UTF-8 up to **4 MiB** (exceeding it, non-UTF-8, or JSON containing `NaN`/`Infinity` exits **2**). Unknown keys, type mismatches, and invalid JSON also exit **2** (one line on stderr). When the request is processed it exits **0**, and the child's exit code goes into the JSON `returncode`. A **launch failure** such as a missing executable or missing `cwd` exits **1**. `shell` is not accepted.

Separately from the library's `render_output`, `run` JSON always carries **Base64** fields `stdout_b64` / `stderr_b64` with the captured raw bytes. `output_limited` is always returned as `true` / `false` (CLI only; the library's `render_output` JSON still omits it when `false`). `stdout` / `stderr` are decoded as UTF-8 with invalid bytes replaced by U+FFFD. Use `*_b64` to handle binary or non-UTF-8 data without loss. `--version` prints the `__version__` constant in `cli_args.py` (the same value in a standalone vendored copy).

```bash
printf '%s' '{"argv":["python","-c","print(1)"],"dry_run":true}' | python -S cli_args.py run
printf '%s' '{"argv":["日本語"],"returncode":0,"stdout":"","stderr":"","executed":true}' | python -S cli_args.py render --format json
```

Wrapper arguments and target arguments are separated by a required `--`. Target options such as `--format` can go after the boundary.

- Result: `argv`, `returncode`, `stdout`, `stderr`, `executed`, `timed_out`.
- A non-zero exit is returned as a result too. A launch failure raises `OSError`; a timeout returns `timed_out=True` / `returncode=None` with partial output.
- Dry-run does not execute and returns `executed=False` / `returncode=None`, distinct from a successful run.
- The JSON is an envelope for the execution result. Stdout from Git, curl, etc. is not turned into domain data automatically.
- The text result is stdout as-is. Stdout/stderr captured by `run_command()` is only UTF-8 decoded; newlines emitted by the child (`\n` / `\r\n`) are not normalized. Library users should check stderr and the exit status. The example CLI also prints stderr, reports non-zero exits, and exits 124 on timeout and 127 when the executable is missing. If writing `--output` fails (missing parent directory, insufficient permissions, etc.), it prints `failed to write output: ...` to stderr without a traceback and exits 1.
- Saving is UTF-8, always LF (`\n`), and overwrites existing files. Newline bytes are LF on every OS, including Windows. Parent directories are not created. The file is written only after JSON conversion succeeds, but the save is not atomic.
- Unlimited execution (the default) keeps output in memory. Limit large output by setting `max_output_bytes` explicitly. Lossless binary output, interactive stdin, streaming, and stopping the whole descendant tree are out of scope.
- `env` replaces the whole environment. To inherit, merge with `os.environ` on the caller side or use the `build_env(extra, inherit=True)` helper. `build_env()` takes a Mapping or a sequence of `"KEY=VALUE"` strings and merges environment variables safely.

## The standard library as a third CLI surface

Before adding an external CLI, check whether Python's standard library (`python -m` / `python -c` / plain import) can meet the same goal safely. The default order of choice for AI coding is **stdlib → existing host CLI → Docker/extra dependencies**.

Typical examples are `json.tool`, `zipfile`, `tarfile`, `http.server`, `platform`, `compileall`, and `tempfile`. PR #1 (merged) runs the main examples in CI so this is not just a cheat sheet. Standard modules get no custom aliases; showing the real `python -m module` name keeps the Python version and provenance unambiguous.

For details and "standard features to check before installing an external tool", see [docs/stdlib-command-surface.md](docs/stdlib-command-surface.md).

"Unglamorous but automation-friendly arguments" from classic to modern CLIs are collected in [docs/cli-argument-patterns.md](docs/cli-argument-patterns.md), with links to official docs, real/construct-only evidence levels, and design principles such as NUL-safe, fail-fast, and machine-readable in one place.

## Use standard library functions and types first

Below `python -m` there are stdlib functions and types to use before writing a custom helper or adding a small dependency. In particular, check `print` / `pprint` / `textwrap` / `shlex` / `pathlib` / `tempfile` / `collections` / `itertools` / `functools` / `contextlib` / `difflib` / `csv` / `configparser` / `hashlib` / `urllib.parse` first as candidates for "small things people often write themselves".

Use the real API instead of adding custom aliases. Write a wrapper only when there is an **extra contract** such as bounds, encoding policy, domain validation, provenance, or an error taxonomy.

See [docs/stdlib-function-surface.md](docs/stdlib-function-surface.md) for details.

## Building staged execution in plain Python

The shell bucket brigade often seen as `VAR=... → command → echo $? → if → exit 0/1/2 → next command` can be structured, when Python is available, with ordinary `for` / `if` / variables / `CommandResult.returncode` / `os.environ` / `print` / `sys.exit`.

Control such as "if step 1 fails, do not run steps 2–4" needs no new workflow DSL; run structured argvs in order with normal Python control flow. A child process cannot change its parent's environment variables, so state between steps is passed as Python values, values parsed from stdout, temporary files, or an explicit env mapping.

See [docs/stdlib-orchestration-surface.md](docs/stdlib-orchestration-surface.md) for details and examples.

## Start with the smallest observation path

For read-only data retrieval, do not start with a custom API/MCP; pick the smallest surface that meets the needed contract, in the order **local/static data → raw HTTP document → generic local parser → official API → MCP**. If the full HTML is enough, use the full text fetched with `urllib.request` or existing curl as-is.

Move up to an API when you need auth, a stable schema, pagination, server-side filtering/search, mutation, or computation; move up to MCP when the agent protocol itself (tool discovery, typed invocation, sessions/resources, etc.) adds value.

When Python is the orchestration layer, prefer stdlib `logging` for timestamped, leveled diagnostics over a custom shell echo convention.

See [docs/minimal-transport-surface.md](docs/minimal-transport-surface.md) for details.

## Keeping failures as evidence

PR #1 (merged) does not throw away failures found during exploration as noise. In a **negative evidence / intentional failures** lane kept apart from normal CI, child pytest runs are made to fail on purpose, and raw JUnit, stdout, stderr, and receipts are saved.

Pass / assertion failure / setup error / strict xfail / strict XPASS are currently recorded under explicit testcase names as past patterns, and an outer validator confirms that the child pytest really exits non-zero and that the JUnit classification matches. That raw JUnit is not mixed into the normal 7-report collector; it goes to a dedicated pinned shared failure-identity consumer.

This mechanism is not for "treating unknown failures as expected to turn CI green". Adding or changing an expected failure means updating the testcase name and expected classification explicitly, so the evidence diff can be reviewed. See [tests/failure_lab/README.md](tests/failure_lab/README.md) for details.

## Verification scope

Evidence levels are kept distinct.

- **Host-real**: real commands run on a GitHub Linux runner.
- **Container-real**: real commands run inside a test-only image built in CI.
- **System-service-real**: run against a real backing service/state. This term is used only when a service is really running under journal/systemd, etc.
- **Construct-only/stub**: the exact argv/transport is verified, but the real tool, auth, or service is not measured.

| Target | Evidence | Contract |
|---|---|---|
| Python / argparse | Host-real (3.11 / 3.12 / 3.14) | Booleans, choices, required, mutual exclusion, conditional requirements, invalid input, stdlib-only `python -S` import |
| subprocess | Host-real | Spaces, Japanese text, empty strings, leading hyphens, shell-like strings, cwd, env, non-zero exit, timeout, invalid UTF-8 |
| pytest | Host-real | Multiple files, `-q`, `--tb short`, `-k "a or b"`, explicit `--`, failure results |
| Git | Host-real + Container-real + Construct-only | Measured: temp repo, `-C`, `add --`, leading-hyphen/space/Unicode paths, `ls-files -z`, `status --porcelain=v2 -z --branch`, `for-each-ref --format=...%00 --sort=...`. `--pathspec-from-file=- --pathspec-file-nul` and finite `cat-file --batch-command --buffer -Z` calls are verified with NUL I/O against real Git. Resident/bidirectional sessions are not measured |
| curl | Host-real + Container-real | Local HTTP, repeated headers, empty option values, Unicode URL/output paths, HTTP failure, plus measured `--fail-with-body` exiting 22 while keeping the body, `--fail-early` stopping multiple transfers, and `--write-out %{http_code}` |
| ls/coreutils | Host-real + Container-real | `ls` with multiple flags, explicit `--`, leading-hyphen/space/Unicode filenames, plus measured NUL-delimited record handling with GNU `sort -z --stable` |
| journalctl | Container-real + Construct-only | Real binary/version run in the container. Exact argv for repeated `-u` / since / until / `-n` / no-pager recorded as past patterns |
| journal/systemd backing service | **Not measured** | The default CI image does not start systemd PID 1 or a journal service, so System-service-real is not claimed |
| Docker | Host-real → Container-real | Exact transport of `--`, empty strings, leading hyphens, spaces, and Unicode argv from the host's `cli_args.Command` into a locally built image |
| Docker Compose | Host-real | Runs repeated `-f` + `config --services` referencing only the locally built image. No registry/network needed |
| Node / npm | Host-real | Argv building, lookup, and version probe for `node_command` / `run_node` / `node_or_command` (Node 24+, explicit-choice failures, `.cmd` rejection) and real `.cjs` / `.mjs` runs (`--`, empty strings, leading hyphens, Unicode paths, timeout and exit code). CI has dedicated Node 24 and latest lanes on Ubuntu/Windows/macOS. Transport of `npm run ... -- <args>` is also measured with a temp package + local JS probe |
| Playwright CLI shape | Construct-only | Records the direct Node CLI form actually used in the org as a past pattern, avoiding greedy `--project value` and verifying `--project=value` + `--grep` + spec order. Real browser/parser evidence lives in browser-test-kit |
| gh | Host-real binary + Construct-only/stub | `gh --version` uses the real binary. Exact argv for API subcommands, repeated headers, `--jq`, `--paginate --slurp`, `--cache 1h`, and typed `-F` / raw `-f` fields recorded as past patterns. Live auth/network not measured |
| Flutter / Dart | Construct-only | Representative argv for `flutter build web -t ... --dart-define=...` and `dart run ... --output ...` recorded as past patterns. Bootstrap/build is measured in the Flutter repo |
| FFmpeg | Container-real | FFmpeg is installed explicitly in the test-only image and processes a tiny lavfi source with `-f lavfi -i ... -f null -`. Multiple options/values and the special `-` output are measured |
| uv | Construct-only | Nested argv `uv run --no-project --python ... --with ... python -m pytest` used by the org's Python matrix recorded as a past pattern |

For AI coding, prefer existing **machine-readable / NUL-safe / fail-fast / structured-field** CLI contracts over parsing human-oriented output. "Unglamorous but sturdy" arguments such as Git porcelain v2, `-z`/`%00`, curl diagnostics, and gh API pagination are actively added to regression evidence. Bidirectional interactive batch protocols are not implemented, and finite stdin input working is not stretched into a guarantee for resident processing.

The host Python matrix is limited to fast core contracts and does not depend on Docker/systemd state. The Docker integration lane builds the test-only image in `tests/docker/Dockerfile` (`python:3.14.0-slim-bookworm`) and, separately from host-side Docker transport/Compose checks, verifies Git/curl/ls/journalctl/FFmpeg inside it with the same `cli_args.py` and pytest harness. `CLI_ARGS_CONTAINER_REAL=1` is baked into the test image itself; neither CI nor users need to toggle it. The host matrix lacks that marker, so the container-real suite skips automatically there and is enabled automatically inside the Docker image. The container-real suite is saved as its own JUnit rather than folded into a single outer test. The Docker image also uses the latest uv and the same uv.lock for test dependencies. Installing uv via apt/pip is test infrastructure only, not a runtime dependency of `cli_args.py`.

If Git/curl/ls, etc. are missing from the host, host-real testcases skip with a reason. The Docker integration lane installs the needed binaries explicitly into the image, so skips are not allowed there. No external website or live auth is needed.

Ubuntu CI saves, as separate artifacts, the JUnit for Python 3.11 / 3.12 / 3.14 plus the Node bridge (Ubuntu/Windows/macOS × Node 24 / latest, 6 in total) and the Docker integration JUnit. Windows/macOS also run the stdlib/core contract and `tests/test_node_bridge.py` on Python 3.12 to check OS-specific subprocess/path/newline differences cheaply. **All 13 reports** — 3 host Python, 6 Node, 1 Docker transport/Compose, 1 container-real CLI, and 2 Windows/macOS core — go to the shared exact-report collector. **Being able to build argv, passing it to a stub, a real CLI running, and measuring live/service integration are separate contracts.** The core Python contract on Windows/macOS is measured. Live-authenticated gh, a real Playwright browser/parser, Flutter/Dart bootstrap/build, xprobe, and a systemd-backed journal service are not verified in this initial version.

```bash
uv sync --locked
python -S -c "import cli_args"
uv run --locked pytest -q -ra --tb=short --junitxml=test-results/pytest-local.xml
node --test tests/node/cli_args.test.cjs
```

`pyproject.toml` and `uv.lock` are the source of truth for the development/test environment. `tests/requirements.txt` is kept for compatibility. The root `requirements.txt` is a test-only compatibility shim that keeps existing local workflows working; it does not imply runtime dependencies. The module running under `python -S` and external tools being present are separate conditions. pytest runs with `uv run --locked pytest`. The development dependency pytest has a lower bound only (`pytest>=8`), with no exact pin or upper bound. `node --test` remains the Node test runner.

This records "which usage patterns were reproduced and verified", not speed benchmarks. Failure cases are added to regression tests, and shared features grow from real examples. HTML fetching and structure extraction belong in separate tools, which are expected to use this file's argument, execution, and output features.

## Runtime and development Python policy

The standard-library runtime supports Python 3.10+; this change preserves the
existing runtime floor. The separate `runtime-compatibility` CI lane executes
behavior tests with `python -S`, without installing pytest or any third-party
package. Development/test environments use Python 3.11+ and a committed uv lock:

```sh
uv sync --locked --python 3.11
uv run --locked pytest
node --test tests/node/cli_args.test.cjs
python -S -m unittest discover -s tests -p test_runtime_compatibility.py -v
```

`pyproject.toml` is the canonical development dependency definition; legacy
requirements files remain for downstream callers. Runtime metadata does not
raise the source/vendoring floor to the development floor. CI pins setup-uv v10.3.3 by full commit SHA, gets Python from it
(`actions/setup-python` is not used), and uses the latest uv. Setup actions
using Node 24 require runner 2.327.1 or newer (GitHub-hosted runners are used).

CI also exercises the stdlib runtime floor and Python 3.14 on Windows and macOS.
Dependency-bearing portability tests use locked uv environments on Python 3.11+;
raw JUnit reports from both operating systems are required by the identity collector.
