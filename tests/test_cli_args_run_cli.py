"""run_cli / CliResult: the test-side facade over run_command.

The child scripts are written per-test so the assertions cover the real
subprocess boundary: argv integrity, exit codes as results, and the two
JSON views (stdout payload, stderr error object).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import cli_args
from cli_args import CliResult, CommandResult, run_cli


def write_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "tool.py"
    script.write_text(body, encoding="utf-8")
    return script


ECHO = """
import json, sys
print(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}))
"""

FAIL = """
import json, sys
sys.stderr.write(json.dumps({"exit_code": 66, "error": "no input"}) + "\\n")
raise SystemExit(66)
"""

PLAIN = """
print("not json")
"""


def test_success_parses_stdout_json(tmp_path):
    script = write_script(tmp_path, ECHO)
    result = run_cli(script, "analyze", "--format", "json")
    assert isinstance(result, CliResult)
    assert isinstance(result, CommandResult)
    assert result.returncode == 0
    assert result.executed is True
    assert result.json() == {"argv": ["analyze", "--format", "json"], "stdin": ""}


def test_argv_tokens_pass_through_unchanged(tmp_path):
    script = write_script(tmp_path, ECHO)
    result = run_cli(script, "two words", "--case", "a:b", "-x")
    assert result.json()["argv"] == ["two words", "--case", "a:b", "-x"]


def test_nonzero_exit_is_a_result_with_error_json(tmp_path):
    script = write_script(tmp_path, FAIL)
    result = run_cli(script)
    assert result.returncode == 66
    assert result.error() == {"exit_code": 66, "error": "no input"}


def test_json_on_non_json_stdout_names_the_stream_and_exit(tmp_path):
    script = write_script(tmp_path, PLAIN)
    result = run_cli(script)
    with pytest.raises(ValueError, match="stdout is not JSON \\(exit 0\\)"):
        result.json()


def test_error_on_non_json_stderr_names_the_stream_and_exit(tmp_path):
    script = write_script(tmp_path, PLAIN)
    result = run_cli(script)
    with pytest.raises(ValueError, match="stderr is not JSON \\(exit 0\\)"):
        result.error()


def test_stdin_is_passed_through(tmp_path):
    script = write_script(tmp_path, ECHO)
    result = run_cli(script, stdin="hello\n")
    assert result.json()["stdin"] == "hello\n"


def test_python_override_and_launch_failure(tmp_path):
    script = write_script(tmp_path, ECHO)
    assert run_cli(script, python=sys.executable).returncode == 0
    with pytest.raises(OSError):
        run_cli(script, python=str(tmp_path / "no-such-python"))


def test_result_still_renders_as_a_command_result(tmp_path):
    script = write_script(tmp_path, ECHO)
    result = run_cli(script)
    payload = json.loads(cli_args.render_output(result, format="json"))
    assert payload["returncode"] == 0
    assert payload["executed"] is True
