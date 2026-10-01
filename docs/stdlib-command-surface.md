# Standard-library command surface

`cli_args.py` is intentionally standard-library-only. The same preference should apply one level above it: before installing another CLI or Python package, check whether the Python runtime already provides the operation.

For AI coding and CI, use this order as a default:

1. **Python standard library / `python -m` / small `python -c`** when it already expresses the task.
2. **Existing host CLI** such as Git, curl, Node/npm, Docker, FFmpeg when that tool owns the capability.
3. **Pinned Docker/test environment or an added dependency** when the operation genuinely needs one.

This is a preference, not a ban on external tools. Do not contort a stdlib command into a job it does not model well.

## Why this belongs in the initial contract

AI coding makes one-off shell commands much more frequent. Reinstalling tools for capabilities that ship with Python increases bootstrap time, platform drift, network dependence, and the number of things an agent can accidentally mutate.

The standard library is therefore a third command surface alongside the OS CLI and project-specific tools.

`cli_args.py` does **not** wrap or rename these modules. Use their real module names so provenance, Python-version behavior, and upstream documentation stay visible.

## Python 3.10+ baseline

These examples are useful building blocks for this repository's supported Python floor.

| Need | Standard-library command |
| --- | --- |
| validate / pretty-print JSON | `python -m json.tool --sort-keys input.json` |
| create / list / extract / test ZIP | `python -m zipfile -c out.zip a.txt b.txt` |
| create / list / extract TAR | `python -m tarfile -c out.tar a.txt b.txt` |
| serve a directory locally | `python -m http.server 8000 --bind 127.0.0.1 --directory DIR` |
| show platform information | `python -m platform` |
| syntax-check a tree | `python -m compileall -q src/` |
| run unittest discovery | `python -m unittest discover -v` |
| run doctests | `python -m doctest module.py -v` |
| benchmark a snippet | `python -m timeit "sum(range(100))"` |
| profile a script | `python -m cProfile -s cumtime script.py` |
| create a virtual environment | `python -m venv .venv` |
| package a runnable directory | `python -m zipapp app_dir -o app.pyz` |

Some standard-library CLIs are version-specific. For example, the `sqlite3` CLI and useful `uuid` command surface are available only on newer Python versions. Do not advertise a module command at the repository's Python 3.10 floor unless CI has measured it there.

## Standard-library operations without a dedicated `-m` CLI

The library surface is equally valuable even when the module is not a useful standalone CLI.

Examples:

```sh
# fresh scratch directory outside the checkout
python -c "import tempfile; print(tempfile.mkdtemp())"

# SHA-256 without installing a checksum package
python -c "import hashlib,sys; [print(hashlib.sha256(open(f,'rb').read()).hexdigest(), f) for f in sys.argv[1:]]" FILE

# inspect JSON with pprint
python -c "import json,pprint,sys; pprint.pp(json.load(open(sys.argv[1])))" FILE

# check whether localhost:8000 can be bound
python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',8000)); print(True)"
```

For longer or reused logic, import the module normally instead of growing an opaque shell one-liner.

## Evidence in PR #1

The test suite executes a representative subset rather than only documenting it:

- `json.tool` performs a real JSON transformation.
- `zipfile` creates and lists a real archive.
- `tarfile` creates and lists a real archive.
- `http.server` starts a real localhost-only server and serves a temporary file.
- `platform` runs as a real module CLI.
- `compileall` compiles a temporary Python source tree.
- `tempfile` is exercised through the standard Python API / `python -c` style boundary.

The Windows and macOS portability lanes also run this stdlib-command suite so these examples are not Linux-only documentation.

## Relationship to the wider repository set

The fuller cross-repository cookbook originated in `browser-test-kit/docs/python-m.md`. This repository keeps a smaller, contract-focused subset because its purpose is argv/execution infrastructure rather than a general Python cheat sheet.

When a downstream repository repeatedly installs a tool for something already covered by a measured stdlib command, prefer documenting or reusing the stdlib route before creating another wrapper.

When an external tool has the stronger domain contract—Git, Docker, Playwright, FFmpeg, Flutter, gh, etc.—use that real tool instead of imitating it with Python.
