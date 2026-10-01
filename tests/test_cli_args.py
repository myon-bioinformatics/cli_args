import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cli_args import (Argument, Command, CommandResult, add_execution_arguments,
                      add_output_arguments, make_parser, parse_args, pytest_command,
                      render_output, require_when, run_command, write_output)

ROOT = Path(__file__).resolve().parents[1]


def test_native_arguments_and_boolean():
    specs = [Argument(("--mode",), {"choices": ("a", "b"), "required": True}),
             Argument(("--enabled",), {"action": argparse.BooleanOptionalAction}),
             Argument(("paths",), {"nargs": "+"})]
    args = parse_args(specs, ["--mode", "a", "--no-enabled", "a.py", "日本 語.py"])
    assert (args.mode, args.enabled, args.paths) == ("a", False, ["a.py", "日本 語.py"])


@pytest.mark.parametrize("argv", [[], ["--mode", "bad"], ["--mo", "a"]])
def test_native_errors(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args([Argument(("--mode",), {"required": True, "choices": ("a", "b")})], argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_conditional_required_and_exclusive():
    parser = make_parser()
    parser.add_argument("--output")
    args = parser.parse_args([])
    require_when(parser, args, when=False, required=["output"])
    with pytest.raises(SystemExit):
        require_when(parser, args, when=True, required=["output"])
    require_when(parser, argparse.Namespace(enabled=False, count=0),
                 when=True, required=["enabled", "count"])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--quiet", action="store_true")
    group.add_argument("--verbose", action="store_true")
    with pytest.raises(SystemExit):
        parser.parse_args(["--quiet", "--verbose"])


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_timeout_parse_rejects(value):
    parser = make_parser()
    add_execution_arguments(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--timeout", value])


def test_shared_options(tmp_path):
    parser = make_parser()
    add_execution_arguments(parser)
    add_output_arguments(parser)
    args = parser.parse_args(["--format", "json", "--output", str(tmp_path / "a.json"),
                              "--cwd", str(tmp_path), "--timeout", "1.5", "--dry-run"])
    assert (args.format, args.cwd, args.timeout, args.dry_run) == ("json", tmp_path, 1.5, True)


def test_command_order_and_values():
    base = Command(("tool",))
    command = (base.flag("-q").flag("-v", False).option("--empty", "")
               .option("--absent", None).option("--pattern", "-x", attached=True)
               .repeated("-H", ["A: b", "C: d"]).multiple("--files", ["a", "b"]))
    assert base.argv == ("tool",)
    assert command.argv == ("tool", "-q", "--empty", "", "--pattern=-x",
                            "-H", "A: b", "-H", "C: d", "--files", "a", "b")
    assert base.multiple("--files", []).argv == base.argv
    assert base.passthrough(["-file"]).argv == ("tool", "-file")
    assert base.passthrough(["-file"], separator=True).argv == ("tool", "--", "-file")


@pytest.mark.parametrize("argv,error", [((), ValueError), (("",), ValueError),
                                       (("tool", "a\0b"), ValueError), (("tool", 2), TypeError),
                                       ("git status", TypeError), (Path("git"), TypeError)])
def test_bad_argv(argv, error):
    with pytest.raises(error):
        Command(argv)


def test_bool_not_truthy_string():
    with pytest.raises(TypeError):
        Command(("tool",)).flag("-q", "false")


def test_sequence_apis_reject_scalar_strings_and_paths(tmp_path):
    command = Command(("tool",))
    with pytest.raises(TypeError):
        command.repeated("-H", "abc")
    with pytest.raises(TypeError):
        command.multiple("--files", "abc")
    with pytest.raises(TypeError):
        command.passthrough("abc")
    with pytest.raises(TypeError):
        command.multiple("--files", tmp_path / "abc")
    with pytest.raises(TypeError):
        pytest_command("tests")
    with pytest.raises(TypeError):
        pytest_command(extra="-q")


def test_actual_argv_roundtrip_without_shell(tmp_path):
    sentinel = tmp_path / "should-not-exist"
    values = ["", "日本 語", "a b", "-x", "quote'\"", "$(touch " + str(sentinel) + ")", "; echo bad"]
    result = run_command(Command((sys.executable, "-S", "-c",
                                  "import json,sys; print(json.dumps(sys.argv[1:]))"))
                         .passthrough(values))
    assert result.returncode == 0
    assert json.loads(result.stdout) == values
    assert not sentinel.exists()


def test_failure_stderr_cwd_env(tmp_path):
    result = run_command(Command((sys.executable, "-S", "-c",
        "import os,sys; print(os.getcwd()); print(os.environ['CLI_TEST']); "
        "print('failure',file=sys.stderr); sys.exit(7)")), cwd=tmp_path, env={"CLI_TEST": "yes"})
    assert result.returncode == 7
    assert result.stdout.splitlines() == [str(tmp_path), "yes"]
    assert result.stderr == "failure\n"


def test_timeout_partial_output():
    result = run_command(Command((sys.executable, "-S", "-c",
        "import time; print('started',flush=True); time.sleep(30)")), timeout=1)
    assert result.timed_out and result.executed
    assert result.returncode is None and "started" in result.stdout


def test_dry_run_missing_command():
    command = Command(("cli-args-nonexistent-executable",))
    result = run_command(command, dry_run=True)
    assert not result.executed and result.returncode is None
    assert json.loads(render_output(result)) == list(command.argv)
    with pytest.raises(FileNotFoundError):
        run_command(command)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_direct_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        run_command(Command((sys.executable,)), timeout=timeout, dry_run=True)


def test_invalid_utf8():
    result = run_command(Command((sys.executable, "-S", "-c", "import os; os.write(1,b'\\xff')")))
    assert result.stdout == "\ufffd"


def test_output_json_file_and_stream(tmp_path):
    result = CommandResult(("tool", "日本 語"), 3, "output", "error", True)
    target = tmp_path / "result.json"
    write_output(result, format="json", output=target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"argv": ["tool", "日本 語"], "returncode": 3, "stdout": "output",
                       "stderr": "error", "executed": True, "timed_out": False}
    stream = io.StringIO()
    write_output("日本語", stream=stream)
    assert stream.getvalue() == "日本語\n"
    assert render_output(result) == "output"
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(TypeError):
        write_output(object(), format="json", output=target)
    assert target.read_text() == "keep"
    with pytest.raises(ValueError):
        render_output({}, format="xml")


def test_import_under_python_s_has_no_side_effects():
    result = subprocess.run([sys.executable, "-S", "-c", "import cli_args"], cwd=ROOT,
                            capture_output=True, text=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_example_boundary_and_exit_codes():
    runner = Command((sys.executable, "-S", str(ROOT / "examples/run_cli.py")))
    result = run_command(runner.positional("--format", "json", "--", sys.executable,
                                         "-S", "-c", "import sys; sys.exit(6)"))
    assert result.returncode == 6
    assert json.loads(result.stdout)["returncode"] == 6
    assert run_command(runner.positional("--format", "json")).returncode == 2
    assert run_command(runner.positional("--")).returncode == 2
    assert run_command(runner.positional("--", "cli-args-nonexistent-executable")).returncode == 127


def test_pytest_preset():
    command = pytest_command(["a.py", "b.py"], quiet=True, tb="short", summary=True,
                             extra=["-k", "a or b"])
    assert command.argv == (sys.executable, "-m", "pytest", "-q", "--tb", "short", "-ra",
                            "-k", "a or b", "a.py", "b.py")
    with pytest.raises(ValueError):
        pytest_command(tb="unknown")
