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
- textの実行結果はstdoutそのままです。ライブラリ利用者はstderrと終了状態を確認してください。例のCLIはstderrも表示し、非ゼロ終了を伝え、タイムアウト124・実行ファイル不在127で終了します。`--output` の書込みに失敗した場合（親ディレクトリ不存在・権限不足等）は traceback を出さず `failed to write output: ...` をstderrへ出して終了1にします。
- 保存はUTF-8・LF (`\n`) 固定・既存ファイル上書きです。Windowsを含め改行バイトをLFに固定します。親ディレクトリは作成しません。JSON変換に成功してから書き込みますが、原子的な保存ではありません。
- 出力をメモリに保持します。巨大出力、バイナリ、対話的stdin、ストリーミング、子孫プロセス全体の停止は初期版の対象外です。
- `env` 指定は環境全体の置換です。継承する場合は呼び出し側で `os.environ` と合成してください。

## 検証範囲

| 対象 | テスト内容 | 実行条件 |
|---|---|---|
| Python / argparse | 真偽値・choices・required・排他・条件付き必須・不正入力 | Pythonのみ |
| subprocess | 空白・日本語・空文字・ハイフン・シェル風文字列・cwd・env・非ゼロ・タイムアウト・不正UTF-8 | Pythonのみ |
| pytest | 複数ファイル・`-q`・`--tb short`・`-ra`・失敗結果 | pytestが必要 |
| Git | 一時リポジトリでinit/add/ls-files、NUL出力と日本語ファイル名、失敗 | Gitが必要 |
| curl | ローカルHTTP記事取得・ヘッダー複数指定・ファイル保存・HTTP 404 | curlが必要 |
| gh | コマンド構築と模擬子プロセスへのargv受け渡し | 実gh・認証・ネットワークは未検証 |

Git/curlがない環境では該当テストがskipされ、理由を表示します。外部サイトへのアクセスは不要です。Ubuntu CIではPython 3.10 / 3.12 / 3.14で検証し、JUnitを各ジョブのartifactとして成功・失敗を問わず保存します。さらに shared exact-report collector を通し、失敗identityの横断形式へ接続します。CIの結果がその環境での証拠となります。**argvを構築できることと、そのツール/OSを実測検証済みであることは別契約です。** Windows/macOS、live認証付きgh、Node/Playwright、xprobeはこの初期版では未検証です。

```bash
python -m pip install -r tests/requirements.txt
python -S -c "import cli_args"
python -m pytest -q -ra --tb=short --junitxml=test-results/pytest-local.xml
```

`tests/requirements.txt` が canonical なテスト依存manifestです。root `requirements.txt` は既存のローカル導線を壊さないための test-only compatibility shim で、runtime依存を意味しません。本体が `python -S` で動くことと、外部ツールが存在することは別の条件です。pytestは通常の `python -m pytest` で実行します。

速度ベンチマークではなく「どの利用パターンを再現して検証したか」を記録します。失敗事例は回帰テストへ追加し、実例から共通機能を増やします。HTMLの取得・構造抽出は別のツールへ置き、このファイルの引数・実行・出力機能を利用する想定です。
