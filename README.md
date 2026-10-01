# cli_args
A single-file, standard-library-only Python toolkit for reusable CLI argument definitions, validation, command construction, execution, and JSON/text output, backed by practical CLI tests.

Python 3.10+。`cli_args.py` をコピーして取り込めます。本体は標準ライブラリだけで動き、import時に引数解析・コマンド実行をしません。pipパッケージ化は初期版の対象外です。

## 引数定義を再利用する

`argparse` の `choices` / `required` / `nargs` / `action` / `type` をそのまま利用します。既定ではオプション名の省略を禁止します。

```python
import argparse
from cli_args import Argument, parse_args

args = parse_args([
    Argument(("--mode",), {"choices": ("read", "convert"), "required": True}),
    Argument(("--enabled",), {"action": argparse.BooleanOptionalAction}),
    Argument(("files",), {"nargs": "+"}),
], ["--mode", "read", "--no-enabled", "a.html", "b.html"])
```

細かい設定には `make_parser()` の戻り値へ直接 `add_argument()` や `add_mutually_exclusive_group()` を使えます。`Argument.names`、明示指定する `parse_args(..., argv=...)`、`require_when(..., required=...)` はいずれも順序を持つ有限の sequence を契約とし、単一文字列や set/dict/generator の暗黙展開を拒否します。`require_when(parser, args, when=..., required=["output"])` は条件が成立したとき、値が `None` の項目を `parser.error()` で拒否します。`False` や `0` は指定値として扱います。

`add_output_arguments(parser)` は `--format text/json` と `--output`、`add_execution_arguments(parser)` は `--dry-run` / `--timeout` / `--cwd` を追加します。必要なセットだけ選び、呼び出し側で名前の衝突を避けてください。

## コマンドを組み立てる

```python
from cli_args import Command, run_command, write_output

command = (Command(("git",))
    .option("-C", "/path/to/repository")
    .positional("status")
    .flag("--short"))
result = run_command(command, timeout=10)
write_output(result, format="json")
```

| メソッド | 動作 |
|---|---|
| `flag(name, enabled)` | boolがTrueのときだけ追加 |
| `option(name, value)` | 名前と値を追加。Noneは省略、空文字は保持 |
| `option(..., attached=True)` | `--name=value` を追加。実行先が対応する場合に使用 |
| `repeated(name, values)` | `-H value1 -H value2` のように繰り返す。`values` は複数トークンの collection 専用 |
| `multiple(name, values)` | `--files a b` のように並べる。`values` は複数トークンの collection 専用 |
| `positional(*values)` | 指定順に位置引数を追加 |
| `passthrough(values, separator=False)` | argv をそのまま追加。`separator=True` のときだけ先頭に `--` を追加。`values` は複数トークンの collection 専用 |

コマンドごとの意味や有効な組み合わせは呼び出し側で定義します。引数は文字列またはテキストパスで渡し、数値は明示的に文字列化します。シェル展開・引用符の解釈・文字列の分割は行いません。`repeated()` / `multiple()` / `passthrough()` の collection 引数は、順序を持つ有限の `Sequence`（list/tuple等）専用です。単一の `str` / `PathLike` に加え、順序が不定な set/dict や一度きりの generator も `TypeError` で拒否します。argvの順序・再現性をAPI契約にするためです。1トークンだけ追加したい場合は `option()` / `positional()` を使います。

`pytest_command(paths, quiet=True, tb="short", summary=True, extra=[...])` は `python -m pytest -q --tb short -ra ...` を構築する任意のプリセットです。`paths` と `extra` も順序を持つ有限の `Sequence` 専用で、単一の `str` / `PathLike`、set/dict、generator は拒否します。pytestを本体からimportせず、自動インストールもしません。

## 実行・出力

```bash
python -S examples/run_cli.py --format json --dry-run -- git status --short
python -S examples/run_cli.py --format json --output result.json --timeout 30 -- python -m pytest -q --tb=short -ra
```

ラッパー引数と実行先引数は必須の `--` で区切ります。実行先の `--format` などは境界の後ろに置けます。

- 実行結果: `argv`, `returncode`, `stdout`, `stderr`, `executed`, `timed_out`。
- 非ゼロ終了も結果として返します。起動失敗は `OSError`、タイムアウトは `timed_out=True` / `returncode=None` と途中出力を返します。
- dry-runは実行せず、`executed=False` / `returncode=None` を返します。成功実行とは区別します。
- JSONは実行結果の封筒です。Git・curl等のstdoutを自動で業務データに変換しません。
- textの実行結果はstdoutそのままです。`run_command()` が捕捉したstdout/stderrはUTF-8 decodeのみ行い、子プロセスが出した改行 (`\n` / `\r\n`) は正規化しません。ライブラリ利用者はstderrと終了状態を確認してください。例のCLIはstderrも表示し、非ゼロ終了を伝え、タイムアウト124・実行ファイル不在127で終了します。`--output` の書込みに失敗した場合（親ディレクトリ不存在・権限不足等）は traceback を出さず `failed to write output: ...` をstderrへ出して終了1にします。
- 保存はUTF-8・LF (`\n`) 固定・既存ファイル上書きです。Windowsを含め改行バイトをLFに固定します。親ディレクトリは作成しません。JSON変換に成功してから書き込みますが、原子的な保存ではありません。
- 出力をメモリに保持します。巨大出力、バイナリ、対話的stdin、ストリーミング、子孫プロセス全体の停止は初期版の対象外です。
- `env` 指定は環境全体の置換です。継承する場合は呼び出し側で `os.environ` と合成してください。

## 標準ライブラリを第3のCLI面として使う

外部CLIを追加する前に、Python標準ライブラリの `python -m` / `python -c` / 通常importで同じ目的を安全に満たせないか確認します。AI coding時の既定の判断順は **stdlib → 既存host CLI → Docker/追加依存** です。

代表例は `json.tool`、`zipfile`、`tarfile`、`http.server`、`platform`、`compileall`、`tempfile`。#1では主要例を実際にCIで動かし、単なるcheat sheetにはしません。標準モジュールへ独自aliasを被せず、本来の `python -m module` 名を見せることでPython version/provenanceを曖昧にしません。

詳細と「外部ツールを入れる前に確認する標準機能」は [docs/stdlib-command-surface.md](docs/stdlib-command-surface.md) を参照してください。

## 標準ライブラリの関数・型を先に使う

`python -m` よりさらに下には、独自helperや小規模依存を作る前に使えるstdlibの関数・型があります。特に `print` / `pprint` / `textwrap` / `shlex` / `pathlib` / `tempfile` / `collections` / `itertools` / `functools` / `contextlib` / `difflib` / `csv` / `configparser` / `hashlib` / `urllib.parse` を「よく自作される小物」の候補として先に確認します。

独自aliasを増やすのではなく、本来のAPIをそのまま使います。wrapperを作るのは、bounds・encoding policy・domain validation・provenance・error taxonomyなど**追加の契約**がある場合だけです。

詳細は [docs/stdlib-function-surface.md](docs/stdlib-function-surface.md) を参照してください。

## 標準Pythonで段階実行を組み立てる

Shellでよく見る `VAR=... → command → echo $? → if → exit 0/1/2 → 次のcommand` のバケツリレーは、Pythonが使えるなら通常の `for` / `if` / 変数 / `CommandResult.returncode` / `os.environ` / `print` / `sys.exit` で構造化できます。

`1番が失敗したら2〜4番を実行しない` のような制御は新しいworkflow DSLを作らず、構造化argvを普通のPython制御フローで順番に実行します。子プロセスが親の環境変数を書き換えることはできないため、step間の状態はPython値・stdoutからparseした値・一時ファイル・明示env mappingとして渡します。

詳細と実例は [docs/stdlib-orchestration-surface.md](docs/stdlib-orchestration-surface.md) を参照してください。

## 最小の観測経路から始める

read-onlyな情報取得では、最初から独自API/MCPを作らず **local/static data → raw HTTP document → generic local parser → official API → MCP** の順で、必要な契約を満たす最小の面を選びます。HTML全文を取れば十分なら、`urllib.request` や既存curlで取得した全文をそのまま使って構いません。

APIはauth・stable schema・pagination・server-side filtering/search・mutation・計算が必要なとき、MCPはtool discovery・typed invocation・session/resource等のagent protocol自体が価値になるときに昇格します。

また、Pythonがorchestration layerなら日時/level付き診断は独自shell echo規約ではなくstdlib `logging` を優先します。

詳細は [docs/minimal-transport-surface.md](docs/minimal-transport-surface.md) を参照してください。

## 検証範囲

証拠レベルを混同しません。

- **Host-real**: GitHub Linux runner上で実コマンドを実行。
- **Container-real**: CIでbuildした test-only image 内で実コマンドを実行。
- **System-service-real**: 実際の backing service/state に対して実行。journal/systemd等で本当にserviceが動いている場合だけこの表現を使います。
- **Construct-only/stub**: exact argv/transportは検証するが、実ツール・認証・serviceまでは測定していません。

| 対象 | 証拠 | 契約 |
|---|---|---|
| Python / argparse | Host-real (3.10 / 3.12 / 3.14) | 真偽値・choices・required・排他・条件付き必須・不正入力、stdlib-only `python -S` import |
| subprocess | Host-real | 空白・日本語・空文字・leading hyphen・shell風文字列・cwd・env・非ゼロ・timeout・不正UTF-8 |
| pytest | Host-real | 複数file、`-q`、`--tb short`、`-k "a or b"`、明示 `--`、失敗結果 |
| Git | Host-real + Container-real + Construct-only | temp repo、`-C`、`add --`、leading-hyphen/space/Unicode path、`ls-files -z`、`status --porcelain=v2 -z --branch`、`for-each-ref --format=...%00 --sort=...` を実測。`--pathspec-from-file=- --pathspec-file-nul` と `cat-file --batch-command --buffer -Z` は stdin/batch I/O 未実装のため exact argv のみ固定 |
| curl | Host-real + Container-real | local HTTP、repeated header、empty option value、Unicode URL/output path、HTTP failureに加え、`--fail-with-body` でbodyを残したままexit 22、`--fail-early` の複数transfer停止、`--write-out %{http_code}` を実測 |
| ls/coreutils | Host-real + Container-real | `ls` の複数flag・明示 `--`・leading-hyphen/space/Unicode filenameに加え、GNU `sort -z --stable` のNUL区切りrecord処理を実測 |
| journalctl | Container-real + Construct-only | container内で実binary/versionを実行。repeated `-u` / since / until / `-n` / no-pager のexact argvを固定 |
| journal/systemd backing service | **未測定** | default CI imageはsystemd PID 1/journal serviceを起動しないため System-service-real を主張しない |
| Docker | Host-real → Container-real | hostの `cli_args.Command` からlocal build済みimageへ `--`・空文字・leading hyphen・space・Unicode argvをexact transport |
| Docker Compose | Host-real | local build済みimageだけを参照し、repeated `-f` + `config --services` を実行。registry/networkは不要 |
| Node / npm | Host-real | temp package + local JS probeで `npm run ... -- <args>` のspace/Unicode/leading-hyphen/attached-option transportを実測 |
| Playwright CLI shape | Construct-only | orgで実際に使うdirect Node CLI形を固定し、greedyな `--project value` を避け `--project=value` + `--grep` + spec順序を検証。real browser/parser証拠はbrowser-test-kit側 |
| gh | Host-real binary + Construct-only/stub | `gh --version` は実binary。API subcommand、repeated header、`--jq`、`--paginate --slurp`、`--cache 1h`、typed `-F` / raw `-f` fieldのexact argvを固定。live auth/networkは未測定 |
| Flutter / Dart | Construct-only | `flutter build web -t ... --dart-define=...`、`dart run ... --output ...` の代表argvを固定。bootstrap/build実測はFlutter repo側 |
| FFmpeg | Container-real | test-only imageにFFmpegを明示導入し、lavfiの極小音源を `-f lavfi -i ... -f null -` で処理。複数option/valueと特殊な `-` 出力を実測 |
| uv | Construct-only | orgのPython matrixで使う `uv run --no-project --python ... --with ... python -m pytest` のnested argvを固定 |

AI coding向けには、人間向け表示をparseするよりも **machine-readable / NUL-safe / fail-fast / structured-field** な既存CLI契約を優先します。Git porcelain v2・`-z`/`%00`、curlの診断系、gh API paginationのような「地味だが壊れにくい」引数は積極的に回帰証拠へ取り込みます。一方、stdin/batch protocolを必要とする便利機能は、実行primitiveが無い段階ではConstruct-onlyと明示し、実測済みとは扱いません。

Host Python matrixは速いcore contractに限定し、Docker/systemd stateへ依存しません。Docker integration laneは `tests/docker/Dockerfile` の test-only image (`python:3.14.0-slim-bookworm`) をbuildし、host側のDocker transport/Compose検証とは別に、その中で同じ `cli_args.py` と pytest harnessを使ってGit/curl/ls/journalctl/FFmpegを検証します。`CLI_ARGS_CONTAINER_REAL=1` は test image 自体に埋め込まれ、CIや利用者が手動で切り替える必要はありません。Host matrixではそのmarkerが存在しないためcontainer-real suiteは自動skipし、Docker image内では自動有効になります。container-real suite は独立JUnitとして保存し、外側テスト1件へ証跡を畳み込みません。Docker image内のapt/pip依存はテスト基盤専用であり、`cli_args.py` のruntime依存ではありません。

Git/curl/ls等がhost環境に無い場合、host-real testcaseは理由付きskipになります。ただしDocker integration laneでは必要binaryをimageに明示的に入れるため、そのlaneではskipを許容しません。外部web siteやlive認証は不要です。

Ubuntu CIではPython 3.10 / 3.12 / 3.14のJUnitに加えてDocker integration JUnitを別artifactとして保存します。さらにWindows/macOSではPython 3.12でstdlib/core contract (`tests/test_cli_args.py`) を実行し、OS固有のsubprocess/path/newline差を軽量に検証します。host Python 3件、Docker transport/Compose 1件、container-real CLI 1件、Windows/macOS core 2件の**全7 report**をshared exact-report collectorへ渡します。**argvを構築できること、stubへ渡せること、real CLIが動いたこと、live/service integrationまで測ったことは別契約です。** Windows/macOSのcore Python contractは実測します。live認証付きgh、real Playwright browser/parser、Flutter/Dart bootstrap/build、xprobe、systemd-backed journal serviceはこの初期版では未検証です。

```bash
python -m pip install -r tests/requirements.txt
python -S -c "import cli_args"
python -m pytest -q -ra --tb=short --junitxml=test-results/pytest-local.xml
```

`tests/requirements.txt` が canonical なテスト依存manifestです。root `requirements.txt` は既存のローカル導線を壊さないための test-only compatibility shim で、runtime依存を意味しません。本体が `python -S` で動くことと、外部ツールが存在することは別の条件です。pytestは通常の `python -m pytest` で実行します。

速度ベンチマークではなく「どの利用パターンを再現して検証したか」を記録します。失敗事例は回帰テストへ追加し、実例から共通機能を増やします。HTMLの取得・構造抽出は別のツールへ置き、このファイルの引数・実行・出力機能を利用する想定です。
