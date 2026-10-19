"""Executable contract for opt-in stdlib difflib hints (Python 3.10+)."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cli_args import Argument, make_parser, parse_args

ROOT = Path(__file__).resolve().parents[1]


def test_opt_in_hint_for_unknown_long_option(capsys):
    parser = make_parser(suggest_unknown=True)
    parser.add_argument("--max-output-bytes", type=int)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--max-outpt-bytes", "5"])
    stderr = capsys.readouterr().err
    assert exc.value.code == 2
    assert "unrecognized arguments: --max-outpt-bytes 5" in stderr
    assert "did you mean '--max-output-bytes'?" in stderr


def test_equals_value_and_parse_args_helper(capsys):
    specs = [Argument(("--format",), {"choices": ["json", "text"]})]
    with pytest.raises(SystemExit) as exc:
        parse_args(specs, ["--fomrat=json"], suggest_unknown=True)
    assert exc.value.code == 2
    assert "did you mean '--format'?" in capsys.readouterr().err
    assert parse_args(specs, ["--format", "json"], suggest_unknown=True).format == "json"


def test_no_hint_by_default_or_for_unrelated_input(capsys):
    parser = make_parser()
    parser.add_argument("--output")
    with pytest.raises(SystemExit):
        parser.parse_args(["--outpt", "file"])
    assert "did you mean" not in capsys.readouterr().err
    parser = make_parser(suggest_unknown=True)
    parser.add_argument("--output")
    with pytest.raises(SystemExit):
        parser.parse_args(["--utterly-unrelated-option"])
    assert "did you mean" not in capsys.readouterr().err


def test_hidden_options_not_suggested_and_positional_not_guessed(capsys):
    parser = make_parser(suggest_unknown=True)
    parser.add_argument("--hidden-long-option", help=argparse.SUPPRESS)
    parser.add_argument("--visible-long-option")
    with pytest.raises(SystemExit):
        parser.parse_args(["--hidde-long-option"])
    assert "did you mean" not in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parser.parse_args(["not-a-flag"])
    assert "did you mean" not in capsys.readouterr().err


def test_type_validation_and_parse_known_args_unchanged():
    with pytest.raises(TypeError, match="suggest_unknown must be bool"):
        make_parser(suggest_unknown=1)
    parser = make_parser(suggest_unknown=True)
    parser.add_argument("--format")
    assert parser.parse_known_args(["--fomrat", "json"])[1] == ["--fomrat", "json"]


def test_real_one_liner_typo_does_not_execute_child(tmp_path):
    sentinel = tmp_path / "executed"
    run = subprocess.run(
        [sys.executable, "-S", "examples/run_cli.py", "--max-outpt-bytes=5", "--",
         sys.executable, "-S", "-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 2
    assert "did you mean '--max-output-bytes'?" in run.stderr
    assert not sentinel.exists()


def test_real_one_liner_still_transports_argv():
    run = subprocess.run(
        [sys.executable, "-S", "examples/run_cli.py", "--format", "json", "--",
         sys.executable, "-S", "-c", "print('hello')"],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["stdout"].splitlines() == ["hello"]


@pytest.mark.parametrize('argv', [
    ['text --outpt'], ['line\n--outpt'], ['--other=hello --outpt'],
    ['--other=hello\n--outpt'], ['--', '--outpt'],
    ['value', '--', '--outpt'], ['-outpt'], ['--outpt!'],
])
def test_only_whole_unknown_option_tokens_before_boundary_are_guessed(argv, capsys):
    parser = make_parser(suggest_unknown=True)
    parser.add_argument('--output')
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(argv)
    assert exc.value.code == 2
    assert 'did you mean' not in capsys.readouterr().err


def test_positionals_and_option_values_remain_literal(capsys):
    parser = make_parser(suggest_unknown=True)
    parser.add_argument('--output')
    parser.add_argument('values', nargs='*')
    args = parser.parse_args(['--output=--outpt', 'text --outpt', '--', '--outpt'])
    assert args.output == '--outpt'
    assert args.values == ['text --outpt', '--outpt']
    assert capsys.readouterr().err == ''
    parser = make_parser(suggest_unknown=True)
    parser.add_argument('--output')
    parser.add_argument('value')
    with pytest.raises(SystemExit):
        parser.parse_args(['value', '--', '--outpt', '--extra'])
    # All positional strings after -- are data, even when there are too many.
    assert 'did you mean' not in capsys.readouterr().err


def test_hint_ranking_is_deterministic_and_hidden_winner_has_no_public_fallback(capsys):
    for names in [('format', 'formal'), ('formal', 'format')]:
        parser = make_parser(suggest_unknown=True)
        for name in names:
            parser.add_argument('--' + name)
        with pytest.raises(SystemExit):
            parser.parse_args(['--forma'])
        assert "did you mean '--format'?" in capsys.readouterr().err
    parser = make_parser(suggest_unknown=True)
    parser.add_argument('--format', help=argparse.SUPPRESS)
    parser.add_argument('--formal')
    with pytest.raises(SystemExit):
        parser.parse_args(['--forma'])
    assert 'did you mean' not in capsys.readouterr().err


@pytest.mark.parametrize('argv', [
    [], ['--format', 'json'], ['--format', 'bad'], ['--format'],
    ['--for', 'json'], ['value'], ['--', '--format'],
])
@pytest.mark.parametrize('exit_on_error', [True, False])
def test_opt_in_preserves_native_parse_results_and_failures(argv, exit_on_error, capsys):
    outcomes = []
    for suggest in (False, True):
        parser = make_parser(suggest_unknown=suggest, exit_on_error=exit_on_error)
        parser.add_argument('--format', choices=['json', 'text'])
        namespace = argparse.Namespace(existing=42)
        try:
            result = parser.parse_args(argv, namespace)
        except (SystemExit, argparse.ArgumentError) as exc:
            outcomes.append((type(exc), getattr(exc, 'code', None)))
        else:
            assert result is namespace
            outcomes.append(vars(result))
        capsys.readouterr()
    assert outcomes[0] == outcomes[1]


def test_parse_known_args_and_reuse_do_not_leave_hint_state(capsys):
    parser = make_parser(suggest_unknown=True, allow_abbrev=True)
    parser.add_argument('--output')
    assert parser.parse_args(['--out', 'x']).output == 'x'
    unknown = ['text --outpt', '--outpt=x', '--', '--outpt']
    assert parser.parse_known_args(unknown)[1] == unknown
    assert capsys.readouterr().err == ''
    with pytest.raises(SystemExit):
        parser.parse_args(['--outpt'])
    assert "did you mean '--output'?" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parser.parse_args(['text --outpt'])
    assert 'did you mean' not in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parser.error('unrecognized arguments: --outpt')
    assert 'did you mean' not in capsys.readouterr().err


@pytest.mark.parametrize('entrypoint', [
    ['examples/run_cli.py'],
    ['-c', 'from examples.run_cli import main; raise SystemExit(main())'],
])
@pytest.mark.parametrize('wrapper', [
    ['--max-outpt-bytes=5'], ['--max-outpt-bytes', '5'],
    ['--dry-ru'], ['--format', 'invalid'], ['--timeout', '0'],
    ['--timeout', 'nan'], ['--max-output-bytes=-1'],
    ['--env', 'invalid'], ['positional'], ['text --dry-ru'],
    ['--stdin'], ['--stdin=x', '--stdin-file=missing'],
])
def test_invalid_wrapper_never_executes_child_under_python_S(wrapper, entrypoint, tmp_path):
    sentinel = tmp_path / 'executed'
    child = [sys.executable, '-S', '-c',
             f'from pathlib import Path; Path({str(sentinel)!r}).touch()']
    run = subprocess.run(
        [sys.executable, '-S', *entrypoint, *wrapper, '--', *child],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 2, run.stderr
    assert not sentinel.exists()


def test_missing_boundary_never_executes_child_under_python_S(tmp_path):
    sentinel = tmp_path / 'executed'
    run = subprocess.run(
        [sys.executable, '-S', 'examples/run_cli.py', sys.executable, '-S', '-c',
         f'from pathlib import Path; Path({str(sentinel)!r}).touch()'],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 2
    assert not sentinel.exists()


def test_child_argv_is_not_suggested_rewritten_or_parsed_under_python_S(tmp_path):
    report = tmp_path / 'result.json'
    # File output is UTF-8 on every OS; piped Windows stdout uses its locale.
    child_args = ['--max-outpt-bytes=5', '--dry-ru', 'text --outpt',
                  '--', '--format', 'invalid', '日本 語', '']
    run = subprocess.run(
        [sys.executable, '-S', 'examples/run_cli.py', '--format=json',
         '--output', str(report), '--',
         sys.executable, '-S', '-c',
         'import json,sys;print(json.dumps(sys.argv[1:]))', *child_args],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == ''
    result = json.loads(report.read_text(encoding='utf-8'))
    assert json.loads(result['stdout']) == child_args
    assert result['argv'][-len(child_args):] == child_args
    assert run.stderr == ''


def test_sys_argv_and_argument_files_preserve_boundaries(monkeypatch, tmp_path, capsys):
    parser = make_parser(suggest_unknown=True, fromfile_prefix_chars='@')
    parser.add_argument('--output')
    monkeypatch.setattr(sys, 'argv', ['example', '--outpt=x'])
    with pytest.raises(SystemExit) as exc:
        parser.parse_args()
    assert exc.value.code == 2
    assert "did you mean '--output'?" in capsys.readouterr().err
    argument_file = tmp_path / 'args.txt'
    argument_file.write_text('--\n--outpt\n', encoding='utf-8')
    with pytest.raises(SystemExit):
        parser.parse_args(['@' + str(argument_file)])
    assert 'did you mean' not in capsys.readouterr().err
