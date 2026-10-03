# Standard-library orchestration surface

AI coding often produces shell relay code like this:

```sh
STEP=one
command_one
rc=$?
echo "$STEP -> $rc"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi
command_two
```

That pattern is useful, but once Python is already available it usually becomes clearer and safer as ordinary Python control flow.

The default rule in this repository is:

- keep each external command as structured argv;
- execute with `shell=False`;
- inspect `returncode`, `timed_out`, stdout and stderr as data;
- use normal `if`, `for`, `break`, variables and exceptions for control flow;
- use `os.environ` or an explicit environment mapping for inherited configuration;
- use `print` / logging for diagnostics;
- use `sys.exit(code)` only at the outer CLI boundary.

Do not build a workflow engine just to replace Python syntax.

## Stop-on-failure

For a fixed series of commands:

```python
steps = [
    ("check", Command(("tool", "check"))),
    ("build", Command(("tool", "build"))),
    ("publish", Command(("tool", "publish"))),
]

for name, command in steps:
    result = run_command(command)
    print(name, result.returncode)
    if result.returncode != 0:
        break
```

This is the Python equivalent of a shell `cmd1 && cmd2 && cmd3`, except each result remains structured and testable.

If a later step must never run after failure, test the absence of its side effect.

## Exit-code contracts

Exit codes are useful machine signals, but their meanings belong to the calling tool's contract.

Common local conventions include:

- `0`: requested condition/action succeeded;
- `1`: ordinary negative result / condition not met;
- `2`: usage, invalid input, or a distinct operational state.

Do not assume every third-party CLI uses those meanings. Preserve the original `returncode` unless the wrapper intentionally defines its own public exit taxonomy.

`argparse` already uses exit 2 for usage errors, which is another reason not to invent a parallel parser.

## Environment handoff

A child process cannot modify the parent Python process environment.

This shell idea:

```sh
export VALUE=before
command
echo "$VALUE"
```

maps to an explicit environment input:

```python
env = {**os.environ, "VALUE": "before"}
result = run_command(command, env=env)
```

If one step produces state for another, carry it explicitly as:

- a Python value parsed from stdout;
- a file in a temporary directory;
- a deliberate environment mapping built by the parent;
- or another structured artifact.

Do not rely on `export` performed inside one subprocess affecting the next.

## Diagnostics without echo relays

Prefer:

```python
print(step_name, result.returncode, file=sys.stderr)
```

or a structured JSON/JUnit/evidence record over a chain of `echo` statements.

For human-readable argv diagnostics, `shlex.join(command.argv)` is appropriate. It is a display representation only; do not feed the joined string back through a shell.

## Boolean composition

Simple shell operators have direct Python equivalents:

| Shell idea | Python |
| --- | --- |
| `a && b` | run `b` only if `a.returncode == 0` |
| `a || b` | run `b` only if `a.returncode != 0` |
| `$?` | `result.returncode` |
| `export X=v` for a child | `env={**os.environ, "X": "v"}` |
| `echo ...` | `print(...)` |
| `exit N` | `raise SystemExit(N)` / `sys.exit(N)` |
| temporary state | `TemporaryDirectory`, Python variables, explicit files |
| shell command string | structured `Command.argv` |

## What stays outside #1

The repository does not add:

- a DAG/workflow engine;
- retries/backoff orchestration;
- parallel job scheduling;
- stdin pipelines between processes;
- process-tree supervision;
- shell syntax parsing.

Those should be added only when a real consumer needs a contract stronger than ordinary Python control flow.

## Measured behavior

`tests/test_orchestration.py` verifies:

- ordered steps stop after the first non-zero result;
- later side effects are absent after failure;
- `0 / 1 / 2` can be propagated distinctly without parsing prose;
- environment mappings are explicit and child mutations do not leak to the parent;
- stdout can be parsed into a Python value and carried to the next step;
- temporary files can act as bounded handoff artifacts;
- shell execution is unnecessary for conditional sequencing.

The same tests run on Windows and macOS portability lanes.
