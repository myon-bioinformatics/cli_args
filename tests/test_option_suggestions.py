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
