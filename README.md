# cli_args

A single-file, standard-library-only Python toolkit for reusable CLI argument definitions, validation, command construction, execution, and JSON/text output, backed by practical CLI tests.

- **Python 3.10+.** Copy `cli_args.py` into your project. The module runs on the standard library only. Importing it does not parse arguments or run commands. Packaging as a pip distribution is out of scope for the initial version.

## Reusable argument definitions

`cli_args` uses `argparse` options such as `choices`, `required`, `nargs`, `action` and `type` as they are. Abbreviated option names are rejected by default.

```python
import argparse
from cli_args import Argument, parse_args

args = parse_args([
    Argument(("--mode",), {"choices": ("read", "convert"), "required": True}),
    Argument(("--enabled",), {"action": argparse.BooleanOptionalAction}),
    Argument(("files",), {"nargs": "+"}),
], ["--mode", "read", "--no-enabled", "a.html", "b.html"])
```

For finer control, call `add_argument()` or `add_mutually_exclusive_group()` directly on the parser returned by `make_parser()`.

- `Argument.names`, explicit `parse_args(..., argv=...)` and `require_when(..., required=...)` take finite, ordered sequences. Single strings and implicit expansion of sets, dicts or generators are rejected.
- `require_when(parser, args, when=..., required=["output"])` rejects items whose value is `None` when the condition holds, via `parser.error()`. `False` and `0` count as supplied values.
- `add_output_arguments(parser)` adds `--format text|json` and `--output`. `add_execution_arguments(parser)` adds `--dry-run`, `--timeout` and `--cwd`. Choose only the sets you need, and avoid name collisions in your own parser.

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
| `flag(name, enabled)` | Adds the flag only when `enabled` is true. |
| `option(name, value)` | Adds the name and value. `None` is omitted; an empty string is kept. |
| `option(..., attached=True)` | Adds `--name=value`. Use it only when the target command supports that form. |
| `repeated(name, values)` | Repeats the option, e.g. `-H value1 -H value2`. `values` must be an ordered collection of several tokens. |
| `multiple(name, values)` | Places values after one option, e.g. `--files a b`. `values` must be an ordered collection. |
| `positional(*values)` | Appends positional arguments in the given order. |
| `passthrough(values, separator=False)` | Appends argv tokens unchanged. Adds a leading `--` only when `separator=True`. `values` must be an ordered collection. |

Each command defines its own meaning and valid combinations. Pass arguments as strings or text paths, and convert numbers to strings explicitly. The library does no shell expansion, quote interpretation or string splitting. The collection arguments of `repeated()`, `multiple()` and `passthrough()` accept only ordered, finite sequences such as lists and tuples. A single `str` or `PathLike`, a set or dict (unordered), and a one-shot generator all raise `TypeError`. Argument order and reproducibility are part of the API contract. To add one token, use `option()` or `positional()`.

`pytest_command(paths, quiet=True, tb="short", summary=True, extra=[...])` builds `python -m pytest -q --tb short -ra ...` as an optional preset. `paths` and `extra` follow the same rules: ordered finite sequences only. The module never imports pytest and never installs it.

## Explicit stdin

`run_command(command, stdin=...)` passes **a str (encoded as UTF-8) or bytes (sent unchanged)** to the child process exactly once. No trailing newline is added. No shell is used. `None` means no input.

```python
from cli_args import Command, run_command
import sys

# A JSON stdin worker (for example, in Flutter): pass the generated JSON string as-is.
result = run_command(
    Command((sys.executable, "-S", "worker.py")),
    stdin='{"operation":"inspect","values":["日本語"]}',
    timeout=5,
)
assert result.returncode == 0

# NUL-safe Git pathspec: send names with spaces or a leading "-" exactly.
git = Command(("git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"))
result = run_command(git, stdin=b"-leading name.txt\0", timeout=10)
```

`run_command()` handles only synchronous, finite input. File objects and iterators are not accepted for stdin. Streaming, bidirectional batch protocols and long-running processes are not supported. In dry-run mode, the type and UTF-8 encoding are validated, but the input content is not printed, so secrets are not leaked. The existing UTF-8 replacement policy for stdout and stderr and the exit/timeout contract are unchanged.

Cross-repository examples: the JSON stdin of `flutter_navigation_basic`, stdin-based child-process tests in `browser-test-kit`, and external CLI wrappers in `gh_identity`. Argument parsing and domain rules stay in each project. Git NUL pathspecs and finite `git cat-file --batch-command --buffer -Z` calls are **verified against real Git**. Interactive or long-running bidirectional sessions are not supported.

## Output protection and byte limits

`write_output(..., overwrite=False)` is opt-in and **never overwrites an existing path**. For an existing file, symlink or dangling symlink, it raises `FileExistsError` and deletes nothing. It renders the content first, writes it to a temporary file in the destination directory, and publishes it with an exclusive hard link. The default `overwrite=True` keeps the previous behavior. On file systems without hard links, the function fails safely. Publishing a new path is atomic. Crash durability, fsync, protection against third-party changes after publication, and automatic creation of missing directories are **not** guaranteed.

`run_command(..., max_output_bytes=N)` caps the **total raw bytes** of stdout plus stderr. When the cap is exceeded, the child process is stopped. Captured output stays within N bytes, and `CommandResult.output_limited=True` with `returncode=None` distinguishes this from ordinary success. The default `None` keeps the unlimited mode, and the existing JSON shape is unchanged. A truncated stream may end in the middle of a UTF-8 character; decoding still uses `errors="replace"`. Only the directly started child process is monitored. Stopping all descendant processes is not guaranteed.

```python
result = run_command(Command(("git", "status")), max_output_bytes=65536, timeout=10)
if result.output_limited:
    raise RuntimeError("command output exceeded limit")
write_output({"ok": True}, format="json", output="result.json", overwrite=False)
```

`examples/run_cli.py` exposes `--max-output-bytes N`, `--no-overwrite`, `--stdin TEXT` or `--stdin-file PATH` (mutually exclusive), and repeatable `--env KEY=VALUE`. Exit codes: **125** when output exceeds the limit, **124** on timeout (unchanged), and **1** when the output file cannot be created or the stdin file cannot be read. Wrapper options go before the `--` separator; the external command's argv goes after it.

## Reading long output (explicit truncation and pytest decision lines)

`trim_output(text, head=40, tail=40)` keeps the first `head` and last `tail` lines and inserts one line, `... N line(s) omitted ...`, in between. Output that fits is returned unchanged. Truncation is always visible, so a human or an agent can notice missing lines.

`pytest_summary(output)` returns only the lines that decide a pytest result:

- the final `N failed, M passed in Xs` line (`summary`, `counts`);
- `FAILED` and `ERROR` lines from `-ra` (`failed`, `errors`);
- the pytest-cov `TOTAL` line and the `Required test coverage` verdict (`coverage`);
- for each failure, the first `E` line, plus `INTERNALERROR` lines (`deciding_lines`; 60 lines by default, with `truncated` set when exceeded).

```python
result = run_command(pytest_command(["tests"], quiet=True, summary=True), timeout=600)
digest = pytest_summary(result.stdout)
print(digest["summary"], digest["failed"], digest["coverage"]["required_met"])
print(trim_output(result.stdout, head=20, tail=40))
```

## Running and output

```bash
python -S examples/run_cli.py --format json --dry-run -- git status --short
python -S examples/run_cli.py --format json --output result.json --timeout 30 -- python -m pytest -q --tb=short -ra
```

The wrapper options and the target command's options are separated by a required `--`. Options such as `--format` for the target can go after the separator.

- The result contains `argv`, `returncode`, `stdout`, `stderr`, `executed` and `timed_out`.
- A non-zero exit is returned as a result, not an exception. A failure to start raises `OSError`. A timeout returns `timed_out=True` and `returncode=None`, along with the partial output.
- Dry-run does not execute the command. It returns `executed=False` and `returncode=None`, which is distinct from a successful run.
- The JSON is an envelope around the run result. Git, curl and other stdout is not converted into business data automatically.
- Text output is the raw stdout. `run_command()` only decodes captured stdout and stderr as UTF-8. Newlines from the child process (`\n` and `\r\n`) are not normalized. Library users should check stderr and the exit status. The example CLI also prints stderr, reports non-zero exits, and exits with 124 on timeout or 127 when the executable is missing. If writing `--output` fails (for example, the parent directory is missing or permission is denied), it prints `failed to write output: ...` to stderr and exits with 1, without a traceback.
- Saved files are UTF-8 with fixed LF (`\n`) newlines, including on Windows. Existing files are overwritten. Parent directories are not created. The output is converted to JSON before writing, but the write is not atomic.
- The default unlimited execution keeps all output in memory. Set `max_output_bytes` to limit large output. Lossless binary output, interactive stdin, streaming and stopping every descendant process are out of scope.
- An `env` argument replaces the whole environment. To inherit the current environment, merge `os.environ` yourself or use `build_env(extra, inherit=True)`. `build_env()` accepts a Mapping or a sequence of `"KEY=VALUE"` strings and merges environment variables safely.

## Using the standard library as a third CLI surface

Before adding an external CLI, check whether the standard library can meet the same need safely through `python -m`, `python -c` or a normal import. For AI-assisted coding, the default order is **stdlib → existing host CLI → Docker or additional dependencies**.

Representative examples include `json.tool`, `zipfile`, `tarfile`, `http.server`, `platform`, `compileall` and `tempfile`. PR #1 (merged) ran the main examples in CI, so this is not just a cheat sheet. Standard modules are not wrapped with custom aliases. Showing the real `python -m module` name keeps the Python version and provenance unambiguous.

See [docs/stdlib-command-surface.md](docs/stdlib-command-surface.md) for details and the standard features to check before installing an external tool. [docs/cli-argument-patterns.md](docs/cli-argument-patterns.md) collects practical, automation-friendly arguments from classic to modern CLIs, with links to official docs, the evidence level (real or construct-only), and design principles such as NUL-safe, fail-fast and machine-readable output.

## Using stdlib functions and types first

Below `python -m` there are stdlib functions and types to use before writing your own helpers or adding small dependencies. Check these first for commonly rewritten utilities: `print`, `pprint`, `textwrap`, `shlex`, `pathlib`, `tempfile`, `collections`, `itertools`, `functools`, `contextlib`, `difflib`, `csv`, `configparser`, `hashlib` and `urllib.parse`.

Use the APIs as they are rather than creating new aliases. Write a wrapper only when it adds a contract, such as bounds, an encoding policy, domain validation, provenance or an error taxonomy. See [docs/stdlib-function-surface.md](docs/stdlib-function-surface.md).

## Staged execution in plain Python

In shell scripts you often see chains like `VAR=... → command → echo $? → if → exit 0/1/2 → next command`. When Python is available, express the same logic with ordinary `for` and `if`, variables, `CommandResult.returncode`, `os.environ`, `print` and `sys.exit`.

Rules such as “skip steps 2–4 if step 1 fails” do not need a new workflow DSL. Run structured argv in order with normal Python control flow. A child process cannot change its parent's environment variables, so pass state between steps as Python values, values parsed from stdout, temporary files, or an explicit env mapping. See [docs/stdlib-orchestration-surface.md](docs/stdlib-orchestration-surface.md) for details and examples.

## Start from the smallest observation path

For read-only information, do not build a custom API or MCP server first. Choose the smallest surface that meets the contract, in this order: **local or static data → raw HTTP document → generic local parser → official API → MCP**. If the full HTML is enough, use the document fetched with `urllib.request` or an existing curl as is.

Promote to an API when you need authentication, a stable schema, pagination, server-side filtering or search, mutations, or computation. Promote to MCP when tool discovery, typed invocation, or session and resource handling in the agent protocol is itself the value. When Python is the orchestration layer, use the stdlib `logging` module for diagnostics with timestamps and levels, rather than custom shell echo conventions. See [docs/minimal-transport-surface.md](docs/minimal-transport-surface.md).

## Keep failures as evidence

PR #1 (merged) does not discard failures found during exploration. A separate **negative evidence / intentional failures** lane, outside the normal CI, makes child pytest runs fail on purpose and saves the raw JUnit, stdout, stderr and receipts.

The lane pins pass, assertion failure, setup error, strict xfail and strict XPASS as explicit testcase names. An outer validator confirms that the child pytest exits non-zero and that the JUnit classification matches the expectation. The raw JUnit does not join the normal seven-report collector. It goes to a dedicated, pinned shared failure-identity consumer.

This does not make unknown failures "expected" to keep CI green. To add or change an expected failure, update its testcase name and expected classification explicitly, so the change in evidence can be reviewed. See [tests/failure_lab/README.md](tests/failure_lab/README.md).

## Verification scope

Keep the evidence levels separate:

- **Host-real**: real commands run on a GitHub Linux runner.
- **Container-real**: real commands run inside a test-only image built in CI.
- **System-service-real**: real commands run against an actual backing service or state. Use this term only when the service, such as journal or systemd, is really running.
- **Construct-only / stub**: the exact argv or transport is verified, but the real tool, authentication or service is not measured.

| Target | Evidence | Contract |
|---|---|---|
| Python / argparse | Host-real (3.11 / 3.12 / 3.14) | Booleans, choices, required options, mutual exclusion, conditional requirements, invalid input; stdlib-only import under `python -S`. |
| subprocess | Host-real | Spaces, Japanese text, empty strings, leading hyphens, shell-like strings, cwd, env, non-zero exits, timeouts, invalid UTF-8. |
| pytest | Host-real | Multiple files, `-q`, `--tb short`, `-k "a or b"`, explicit `--`, failure results. |
| Git | Host-real + Container-real + Construct-only | Temp repositories; `-C`; `add --`; leading-hyphen, space and Unicode paths; `ls-files -z`; `status --porcelain=v2 -z --branch`; `for-each-ref --format=...%00 --sort=...`. The NUL pathspec input and finite `cat-file --batch-command --buffer -Z` calls are verified with real Git. Long-running bidirectional sessions are not measured. |
| curl | Host-real + Container-real | Local HTTP, repeated headers, empty option values, Unicode URLs and output paths, HTTP failures; `--fail-with-body` (exit 22 with the body kept); `--fail-early` across multiple transfers; `--write-out %{http_code}`. |
| ls / coreutils | Host-real + Container-real | Multiple `ls` flags, explicit `--`, leading-hyphen, space and Unicode filenames; GNU `sort -z --stable` NUL-delimited records. |
| journalctl | Container-real + Construct-only | The real binary and version run inside the container; exact argv for repeated `-u`, since, until, `-n` and no-pager. |
| journal / systemd backing service | **Not measured** | The default CI image does not start systemd PID 1 or the journal service, so System-service-real is not claimed. |
| Docker | Host-real, then Container-real | From the host `cli_args.Command` to a locally built image: exact transport of `--`, empty strings, leading hyphens, spaces and Unicode argv. |
| Docker Compose | Host-real | Uses only a locally built image; runs repeated `-f` and `config --services`. No registry or network is needed. |
| Node / npm | Host-real | A temp package with a local JS probe; measures the transport of spaces, Unicode, leading hyphens and attached options through `npm run ... -- <args>`. |
| Playwright CLI shape | Construct-only | Fixes the direct Node CLI form used by the org; avoids greedy `--project value` by using `--project=value` + `--grep`, and verifies spec order. Real browser and parser evidence lives in browser-test-kit. |
| gh | Host-real binary + Construct-only / stub | `gh --version` runs the real binary. The exact argv for API subcommands, repeated headers, `--jq`, `--paginate --slurp`, `--cache 1h`, and typed `-F` / raw `-f` fields is fixed. Live authentication and network are not measured. |
| Flutter / Dart | Construct-only | Representative argv for `flutter build web -t ... --dart-define=...` and `dart run ... --output ...`. Bootstrap and build measurements are in the Flutter repository. |
| FFmpeg | Container-real | FFmpeg is explicitly installed in the test-only image. A tiny lavfi audio source is processed with `-f lavfi -i ... -f null -`, measuring multiple options and values and the special `-` output. |
| uv | Construct-only | Fixes the nested argv `uv run --no-project --python ... --with ... python -m pytest` used by the org's Python matrix. |

For AI-assisted coding, prefer existing CLI contracts that are **machine-readable, NUL-safe, fail-fast and structure-based** over parsing human-oriented output. Git porcelain v2 with `-z` or `%00`, curl's diagnostic options, and the gh API pagination options are “unglamorous but robust” arguments, and they are worth adding as regression evidence. Interactive bidirectional batch protocols are not implemented. A finite stdin input that works does not guarantee that a long-running process works.

The host Python matrix is limited to the fast core contract and does not depend on Docker or systemd state. The Docker integration lane builds the test-only image `tests/docker/Dockerfile` (`python:3.14.0-slim-bookworm`). Separately from the host-side Docker transport and Compose checks, it runs the same `cli_args.py` and the pytest harness inside that image to verify Git, curl, ls, journalctl and FFmpeg. `CLI_ARGS_CONTAINER_REAL=1` is embedded in the test image itself, so CI and users do not need to switch it. The host matrix has no such marker, so the container-real suite skips automatically there, and it is enabled automatically inside the Docker image. The container-real suite is saved as an independent JUnit report and is not folded into one outer test. The Docker image also pins test dependencies with uv 0.13.3 and the same `uv.lock`. Installing uv with apt or pip is a test-infrastructure detail and is not a runtime dependency of `cli_args.py`.

When Git, curl or ls are missing from the host, host-real test cases skip with a reason. The Docker integration lane installs the required binaries in the image explicitly, so skips are not allowed there. External websites and live authentication are not required.

On Ubuntu CI, the Python 3.11, 3.12 and 3.14 JUnit reports are saved, along with the Docker integration JUnit as a separate artifact. On Windows and macOS, the stdlib and core contract (`tests/test_cli_args.py`) runs on Python 3.12 to lightly check OS-specific differences in subprocess, paths and newlines. All seven reports (three host Python reports, one Docker transport and Compose report, one container-real CLI report, and two Windows and macOS core reports) go to the shared exact-report collector.

**Building argv, passing it to a stub, a real CLI running, and live or service integration are separate contracts.** Windows and macOS core Python behavior is measured. Live-authenticated gh, real Playwright browsers and parsers, Flutter/Dart bootstrap and build, xprobe, and a systemd-backed journal service are not verified in this initial version.

```bash
python -m pip install -r tests/requirements.txt
python -S -c "import cli_args"
python -m pytest -q -ra --tb=short --junitxml=test-results/pytest-local.xml
```

`pyproject.toml` and `uv.lock` are the source of truth for development and test environments. `tests/requirements.txt` is kept for compatibility. The root `requirements.txt` is a test-only compatibility shim, kept so existing local commands keep working; it does not declare runtime dependencies. That `cli_args` runs under `python -S` and that external tools exist are separate conditions. Run pytest with a normal `python -m pytest`.

This project records **which usage patterns were reproduced and verified**, not speed benchmarks. Failures found in practice are added as regression tests, and shared features grow from real cases. HTML fetching and structure extraction are expected to live in separate tools that use this module's argument, execution and output features.

## Runtime and development Python policy

The standard-library runtime supports Python 3.10+; this change preserves the
existing runtime floor. The separate `runtime-compatibility` CI lane executes
behavior tests with `python -S`, without installing pytest or any third-party
package. Development/test environments use Python 3.11+ and a committed uv lock:

```sh
uv sync --locked --python 3.11
uv run --locked python -m pytest
python -S -m unittest discover -s tests -p test_runtime_compatibility.py -v
```

`pyproject.toml` is the canonical development dependency definition.
`tests/requirements.txt` is kept for compatibility, and the root
`requirements.txt` is a test-only shim that does not declare runtime
dependencies. Runtime metadata does not
raise the source/vendoring floor to the development floor. CI pins setup-python
v7.0.0 and setup-uv v10.3.0 by full commit SHA, and uses uv 0.13.3. Setup actions
using Node 24 require runner 2.327.1 or newer (GitHub-hosted runners are used).

CI also exercises the stdlib runtime floor and Python 3.14 on Windows and macOS.
Dependency-bearing portability tests use locked uv environments on Python 3.11+;
raw JUnit reports from both operating systems are required by the identity collector.

---

<details>
<summary>🇯🇵 日本語（クリックで展開）</summary>

`cli_args` は、再利用できる CLI 引数の定義と検証、コマンドの組み立てと実行、JSON・テキスト出力を、標準ライブラリだけで行う単一ファイルの Python ツールキットです。以下は英語版の各節の日本語訳です。コード例と検証表の詳細は、上の英語版を正としてください。

Python 3.10 以上で動作します。`cli_args.py` をプロジェクトにコピーして取り込めます。本体は標準ライブラリのみで動作し、import 時に引数解析やコマンド実行は行いません。pip パッケージ化は初期版の対象外です。

## 引数定義を再利用する

`argparse` の `choices`・`required`・`nargs`・`action`・`type` をそのまま利用します。既定では、略記されたオプション名を拒否します。

細かい設定が必要な場合は、`make_parser()` の戻り値に対して `add_argument()` や `add_mutually_exclusive_group()` を直接呼び出します。

- `Argument.names`、明示的に指定する `parse_args(..., argv=...)`、`require_when(..., required=...)` は、いずれも順序を持つ有限の sequence を前提とします。単一の文字列や、set・dict・generator の暗黙展開は拒否します。
- `require_when(parser, args, when=..., required=["output"])` は、条件が成立したとき、値が `None` の項目を `parser.error()` で拒否します。`False` や `0` は指定された値として扱います。
- `add_output_arguments(parser)` は `--format text|json` と `--output` を追加します。`add_execution_arguments(parser)` は `--dry-run`・`--timeout`・`--cwd` を追加します。必要なセットだけを選び、呼び出し側でオプション名の衝突を避けてください。

## コマンドを組み立てる

`Command` で argv を組み立てます。メソッドの一覧は次のとおりです。

| メソッド | 動作 |
|---|---|
| `flag(name, enabled)` | `enabled` が真のときだけ追加します。 |
| `option(name, value)` | 名前と値を追加します。`None` は省略し、空文字列は保持します。 |
| `option(..., attached=True)` | `--name=value` の形で追加します。実行先が対応している場合にだけ使ってください。 |
| `repeated(name, values)` | `-H value1 -H value2` のように繰り返します。`values` は複数要素の順序付きコレクションに限ります。 |
| `multiple(name, values)` | `--files a b` のように、1つのオプションの後に並べます。`values` は順序付きコレクションに限ります。 |
| `positional(*values)` | 指定された順序で位置引数を追加します。 |
| `passthrough(values, separator=False)` | argv のトークンをそのまま追加します。`separator=True` のときだけ先頭に `--` を追加します。`values` は順序付きコレクションに限ります。 |

各コマンドの意味や有効な組み合わせは、呼び出し側で定義します。引数は文字列またはテキストのパスで渡し、数値は明示的に文字列へ変換してください。ライブラリはシェル展開・引用符の解釈・文字列の分割を行いません。

`repeated()`・`multiple()`・`passthrough()` のコレクション引数は、list や tuple などの順序付きで有限の `Sequence` だけを受け付けます。単一の `str` や `PathLike`、順序が定まらない set や dict、一度しか読めない generator は `TypeError` で拒否します。argv の順序と再現性を API の契約にするためです。トークンを 1 つだけ追加したい場合は `option()` か `positional()` を使ってください。

`pytest_command(paths, quiet=True, tb="short", summary=True, extra=[...])` は、`python -m pytest -q --tb short -ra ...` を組み立てる任意のプリセットです。`paths` と `extra` にも同じ規則が適用されます。このモジュールは pytest を import せず、自動でインストールもしません。

## stdin を明示的に渡す（複数リポジトリの事例から抽出）

`run_command(command, stdin=...)` は、str（UTF-8 で符号化）または bytes（変換なし）を一度だけ子プロセスに渡します。末尾に改行は追加しません。シェルは使いません。`None` は入力なしを意味します。

Flutter などの JSON stdin ワーカーや、GitHub の NUL 区切り pathspec のような用途を想定しています（コード例は英語版を参照）。

`run_command()` が扱うのは、同期的で有限の入力だけです。ファイルオブジェクトや iterator は stdin として受け付けません。ストリーミング、双方向のバッチプロトコル、長時間常駐するプロセスには対応しません。dry-run では型と UTF-8 符号化を検証しますが、入力の中身は表示しません。秘密情報を漏らさないためです。stdout・stderr の既存の UTF-8 replacement 方針と、終了・タイムアウトの契約は変更していません。

実際の利用例は `flutter_navigation_basic` の JSON stdin、`browser-test-kit` の stdin を使う子プロセスのテスト、`gh_identity` の外部 CLI ラッパーです。引数解析や各プロジェクト固有のドメインルールは、それぞれのプロジェクトに残しています。Git の NUL pathspec と、有限の `git cat-file --batch-command --buffer -Z` の呼び出しは、実際の Git で検証済みです。ただし、対話的な常駐・双方向セッションは未対応です。

## 出力保護とバイト上限

`write_output(..., overwrite=False)` は、既存のパスを上書きしないための opt-in の機能です。既存のファイル、シンボリックリンク、リンク切れのシンボリックリンクに対しては `FileExistsError` を送出し、対象を削除しません。出力内容を先にレンダリングし、出力先と同じディレクトリの一時ファイルへ書き込んでから、排他的なハードリンクで公開します。既定値の `overwrite=True` では従来の動作を維持します。ハードリンクに対応していないファイルシステムでは、安全側に失敗します。新規パスへの公開は原子的ですが、クラッシュ時の耐久性（fsync）、公開後に第三者が変更することへの対策、存在しないディレクトリの自動作成は保証しません。

`run_command(..., max_output_bytes=N)` は、stdout と stderr の**合計の生バイト数**に上限を設けます。上限を超えると子プロセスを停止します。保持される出力は合計 N バイト以下になり、`CommandResult.output_limited=True` と `returncode=None` によって、通常の成功と区別できます。既定値の `None` は従来どおりの無制限モードです。省略時の JSON 形式も変わりません。上限で切れた出力は UTF-8 文字の途中で終わることがあります。decode は既存どおり `errors="replace"` です。監視するのは起動した子プロセスだけで、子孫プロセス全体の停止は保証しません。

`examples/run_cli.py` は `--max-output-bytes N`、`--no-overwrite`、`--stdin TEXT` または `--stdin-file PATH`（どちらか一方）、`--env KEY=VALUE`（複数指定可）を提供します。終了コードは、出力が上限を超えた場合 **125**、タイムアウトは従来どおり **124**、出力ファイルを作成できない場合や stdin ファイルを読めない場合は **1** です。ラッパー用のオプションは `--` より前に、外部コマンドの argv は `--` より後ろに置きます。

## 長い出力を読む側に渡す（省略の明示と pytest の判定行）

`trim_output(text, head=40, tail=40)` は、先頭 `head` 行と末尾 `tail` 行を残し、その間に `... N line(s) omitted ...` という 1 行を入れます。省略は常に見える形で示されるので、人やエージェントが欠落に気づけます。収まる出力は変更せずに返します。

`pytest_summary(output)` は、pytest の出力から結果を決める行だけを返します。

- 最終行の `N failed, M passed in Xs`（`summary` と `counts`）
- `-ra` が出す `FAILED` と `ERROR` の行（`failed` と `errors`）
- pytest-cov の `TOTAL` 行と `Required test coverage` の判定（`coverage`）
- 各失敗の最初の `E` 行と `INTERNALERROR` の行（`deciding_lines`。既定は 60 行で、超えた場合は `truncated` を設定します）

## 実行と出力

ラッパーのオプションと実行先のコマンドの間には、必須の `--` を置きます。実行先の `--format` などのオプションは、区切りの後ろに置けます（コマンド例は英語版を参照）。

- 実行結果は `argv`・`returncode`・`stdout`・`stderr`・`executed`・`timed_out` を含みます。
- 非ゼロの終了コードは、例外ではなく結果として返します。起動に失敗した場合は `OSError` を送出します。タイムアウトした場合は `timed_out=True` と `returncode=None` を返し、途中までの出力も残します。
- dry-run ではコマンドを実行しません。`executed=False` と `returncode=None` を返し、成功した実行とは区別します。
- JSON は実行結果を包む封筒です。Git や curl の stdout を業務データへ自動変換することはしません。
- テキスト出力は stdout をそのまま出します。`run_command()` が捕捉した stdout と stderr は UTF-8 として decode するだけです。子プロセスが出力した改行（`\n` と `\r\n`）は正規化しません。ライブラリを使う側で stderr と終了状態を確認してください。例の CLI は stderr も表示し、非ゼロ終了を伝えます。タイムアウトでは 124、実行ファイルが見つからない場合は 127 で終了します。`--output` への書き込みに失敗した場合（親ディレクトリがない、権限がないなど）は、traceback を出さずに `failed to write output: ...` を stderr へ出して、終了コード 1 で終わります。
- 保存されるファイルは UTF-8 で、改行は LF（`\n`）に固定します（Windows を含みます）。既存のファイルは上書きします。親ディレクトリは作成しません。JSON への変換に成功してから書き込みますが、書き込み自体は原子的ではありません。
- 既定の無制限実行では、出力をすべてメモリに保持します。大きな出力には `max_output_bytes` で上限を指定してください。バイナリをそのまま保存する lossless 出力、対話的な stdin、ストリーミング、子孫プロセス全体の停止は対象外です。
- `env` を指定すると、環境変数の全体を置き換えます。現在の環境を引き継ぐ場合は、`os.environ` と自分で合成するか、`build_env(extra, inherit=True)` を使ってください。`build_env()` は Mapping か `"KEY=VALUE"` 形式の文字列の sequence を受け取り、環境変数を安全に合成します。

## 標準ライブラリを第 3 の CLI 面として使う

外部 CLI を追加する前に、Python 標準ライブラリで同じ目的を安全に満たせないか確認してください。`python -m`、`python -c`、通常の import で代替できるかを見ます。AI 支援コーディングでの既定の判断順は、**標準ライブラリ → 既存のホスト CLI → Docker や追加の依存関係**です。

代表例は `json.tool`、`zipfile`、`tarfile`、`http.server`、`platform`、`compileall`、`tempfile` です。PR #1（マージ済み）では主要な例を実際に CI で実行しています。単なるチートシートにはしていません。標準モジュールに独自の alias を被せず、本来の `python -m モジュール名` を示すことで、Python のバージョンと出所を曖昧にしません。

詳しくは [docs/stdlib-command-surface.md](docs/stdlib-command-surface.md) を参照してください。古典的な CLI から現代的な CLI までの、自動化に強い引数の整理は [docs/cli-argument-patterns.md](docs/cli-argument-patterns.md) にあります。

## 標準ライブラリの関数と型を先に使う

`python -m` より下のレベルにも、標準ライブラリの関数と型があります。独自の helper や小さな依存関係を作る前に、まず確認してください。`print`・`pprint`・`textwrap`・`shlex`・`pathlib`・`tempfile`・`collections`・`itertools`・`functools`・`contextlib`・`difflib`・`csv`・`configparser`・`hashlib`・`urllib.parse` は、よく自作される小さな処理の候補です。

独自の alias を増やすのではなく、本来の API をそのまま使ってください。wrapper を作るのは、境界値（bounds）、encoding の方針、ドメインの検証、provenance、エラー分類といった**追加の契約**が必要な場合だけにしてください。詳しくは [docs/stdlib-function-surface.md](docs/stdlib-function-surface.md) を参照してください。

## 標準 Python で段階的な実行を組み立てる

シェルでよく見る `VAR=... → command → echo $? → if → exit 0/1/2 → 次の command` という連鎖は、Python が使える場合、通常の `for`・`if`・変数・`CommandResult.returncode`・`os.environ`・`print`・`sys.exit` で構造化できます。

「手順 1 が失敗したら手順 2 から 4 を実行しない」といった制御のために、新しいワークフローの DSL は必要ありません。構造化された argv を、通常の Python の制御フローで順番に実行してください。子プロセスは親の環境変数を書き換えられないため、手順間の状態は Python の値、stdout から解析した値、一時ファイル、明示的に渡す env の mapping で受け渡します。

詳しくは [docs/stdlib-orchestration-surface.md](docs/stdlib-orchestration-surface.md) を参照してください。

## 最小の観測経路から始める

読み取りだけの情報取得では、最初から独自の API や MCP サーバーを作らないでください。**ローカルまたは静的なデータ → 生の HTTP 文書 → 汎用のローカル parser → 公式 API → MCP** の順に、必要な契約を満たす最小の面を選びます。HTML 全体を取得すれば十分なら、`urllib.request` または既存の curl で取得した文書をそのまま使って構いません。

API に昇格させるのは、認証、安定したスキーマ、ページネーション、サーバー側のフィルタや検索、変更操作、計算が必要になったときです。MCP に昇格させるのは、ツールの発見、型付きの呼び出し、セッションやリソースの扱いといった、エージェント・プロトコル自体が価値になるときです。Python を orchestration の層に使う場合は、独自の shell の echo 規約ではなく、タイムスタンプとレベルを付けた診断に標準ライブラリの `logging` を使ってください。

詳しくは [docs/minimal-transport-surface.md](docs/minimal-transport-surface.md) を参照してください。

## 失敗を証拠として残す

PR #1（マージ済み）では、探索中に見つかった失敗を捨てません。通常の CI とは分けた **negative evidence / intentional failures** の lane で、子の pytest を意図的に失敗させ、raw JUnit、stdout、stderr、receipt を保存します。

この lane では、pass、assertion failure、setup error、strict xfail、strict XPASS を明示的な testcase 名で固定しています。外側の validator は、子の pytest が本当に非ゼロで終了したことと、JUnit の分類が期待どおりであることを確認します。raw JUnit は通常の 7 レポートの collector には混ぜず、専用の固定された shared failure-identity consumer に渡します。

これは、未知の失敗を「期待どおり」として扱い、CI を green に保つための仕組みではありません。expected failure を追加・変更するときは、testcase 名と期待する分類を明示的に更新し、証拠の差分として review できるようにしてください。詳しくは [tests/failure_lab/README.md](tests/failure_lab/README.md) を参照してください。

## 検証範囲

証拠のレベルは混同しないでください。

- **Host-real**: GitHub の Linux runner 上で、実際のコマンドを実行しています。
- **Container-real**: CI で build した test 専用 image の中で、実際のコマンドを実行しています。
- **System-service-real**: 実際の backing service や state に対して実行しています。journal や systemd などの service が本当に動いている場合にだけ、この表現を使います。
- **Construct-only / stub**: 正確な argv や transport は検証していますが、実際のツール、認証、service までは測定していません。

検証表（対象、証拠、契約）の詳細は英語版を参照してください。対象は Python / argparse、subprocess、pytest、Git、curl、ls / coreutils、journalctl、Docker、Docker Compose、Node / npm、Playwright CLI の形、gh、Flutter / Dart、FFmpeg、uv です。journal / systemd の backing service は未測定です。

AI 支援コーディングでは、人間向けの表示を解析するより、**機械可読・NUL 安全・fail-fast・構造化されたフィールド**を持つ既存の CLI 契約を優先してください。Git の porcelain v2 と `-z`・`%00`、curl の診断オプション、gh API のページネーションのような、地味だが壊れにくい引数は、積極的に回帰の証拠として取り込みます。一方で、双方向の対話的なバッチプロトコルは未実装です。有限の stdin 入力が通ったことを、常駐プロセスが動くことの保証として扱わないでください。

ホストの Python マトリクスは、速いコアの契約に限定しています。Docker や systemd の状態には依存しません。Docker integration lane は `tests/docker/Dockerfile`（`python:3.14.0-slim-bookworm`）で test 専用 image を build し、ホスト側の Docker transport と Compose の検証とは別に、その中で同じ `cli_args.py` と pytest のハーネスを使って Git・curl・ls・journalctl・FFmpeg を検証します。`CLI_ARGS_CONTAINER_REAL=1` は test image に埋め込まれているため、CI や利用者が手動で切り替える必要はありません。ホストのマトリクスにはこの marker がないので、container-real suite は自動で skip されます。Docker image の中では自動で有効になります。container-real suite は独立した JUnit として保存し、外側のテスト 1 件にまとめません。Docker image でも uv 0.13.3 と同じ `uv.lock` でテスト依存を固定しています。apt や pip で uv を導入するのはテスト基盤の詳細であり、`cli_args.py` の実行時の依存関係ではありません。

Git・curl・ls などがホストにない場合、ホストで実行する testcase は理由を付けて skip されます。ただし Docker integration lane では、必要なバイナリを image に明示的に入れるため、そこでは skip を認めません。外部の Web サイトやライブ認証は不要です。

Ubuntu の CI では、Python 3.11・3.12・3.14 の JUnit に加えて、Docker integration の JUnit を別の artifact として保存します。Windows と macOS では Python 3.12 で stdlib とコアの契約（`tests/test_cli_args.py`）を実行し、OS 固有の subprocess・パス・改行の差を軽く検証します。ホストの Python 3 件、Docker の transport と Compose 1 件、container-real の CLI 1 件、Windows と macOS のコア 2 件の**計 7 レポート**を、shared exact-report collector に渡します。

**argv を組み立てられること、stub に渡せること、実際の CLI が動いたこと、ライブやサービスとの統合まで測ったことは、別々の契約です。** Windows と macOS のコアの Python の挙動は実測しています。ライブ認証付きの gh、実際の Playwright のブラウザとパーサー、Flutter / Dart の bootstrap と build、xprobe、systemd に支えられた journal サービスは、この初期版では未検証です。

```bash
python -m pip install -r tests/requirements.txt
python -S -c "import cli_args"
python -m pytest -q -ra --tb=short --junitxml=test-results/pytest-local.xml
```

開発とテストの環境の正本は `pyproject.toml` と `uv.lock` です。`tests/requirements.txt` は互換性のために残しています。ルートの `requirements.txt` は、既存のローカルの手順を壊さないための test 専用の shim です。実行時の依存関係は宣言していません。`cli_args` が `python -S` で動くことと、外部ツールが存在することは別の条件です。pytest は通常の `python -m pytest` で実行してください。

このプロジェクトが記録するのは、速度のベンチマークではなく、**どの利用パターンを再現して検証したか**です。実際に見つかった失敗は回帰テストに追加し、共通の機能は実例から育てています。HTML の取得と構造の抽出は、別のツールに分けます。そのツールがこのモジュールの引数・実行・出力の機能を使う想定です。

## 実行時と開発時の Python 方針

標準ライブラリの実行時は Python 3.10 以上をサポートします。今回の変更でも、既存の実行時の下限は維持しています。`python -S` で挙動のテストを実行する別の `runtime-compatibility` CI lane があります。この lane は pytest や他のサードパーティ製パッケージをインストールしません。開発とテストの環境は Python 3.11 以上を使い、コミット済みの uv lock で固定します（コマンド例は英語版を参照）。

`pyproject.toml` が開発時の依存関係の正本です。`tests/requirements.txt` は互換性のために残しています。ルートの `requirements.txt` は test 専用の shim で、実行時の依存関係は宣言していません。runtime のメタデータによって、ソースや vendoring の下限を開発時の下限まで引き上げることはありません。CI は setup-python v7.0.0 と setup-uv v10.3.0 を完全な commit SHA で固定し、uv 0.13.3 を使います。Node 24 で動く setup action には runner 2.327.1 以降が必要です（GitHub がホストする runner を使います）。

CI では、Windows と macOS でも、stdlib の実行時の下限と Python 3.14 を実行します。依存関係を伴う portability のテストは、Python 3.11 以上でロックされた uv 環境を使います。両 OS の raw JUnit レポートは、identity collector が必須としています。

</details>
