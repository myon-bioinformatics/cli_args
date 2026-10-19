import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cli_args import (Argument, Command, CommandResult, add_execution_arguments,
                      add_output_arguments, build_env, make_parser, parse_args, pytest_command,
                      render_output, require_when, run_command, write_output)

ROOT = Path(__file__).resolve().parents[1]


def test_public_collection_boundaries_reject_scalar_or_unordered_inputs():
    with pytest.raises(TypeError):
        Argument("--mode")
    with pytest.raises(ValueError):
        Argument(())
    with pytest.raises(TypeError):
        parse_args([], "--mode a")
    with pytest.raises(TypeError):
        parse_args([], {"--mode", "a"})
    parser = make_parser()
    with pytest.raises(TypeError):
        require_when(parser, argparse.Namespace(output=None), when=True, required="output")
    with pytest.raises(TypeError):
        require_when(parser, argparse.Namespace(output=None), when=True,
                     required=(name for name in ["output"]))


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
    assert Command(["tool", "status"]).argv == ("tool", "status")
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


def test_sequence_apis_reject_scalar_unordered_and_streaming_inputs(tmp_path):
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
    for values in ({"b", "a"}, {"a": "b"}, (value for value in ["a", "b"])):
        with pytest.raises(TypeError):
            command.repeated("-H", values)
        with pytest.raises(TypeError):
            command.multiple("--files", values)
        with pytest.raises(TypeError):
            command.passthrough(values)
    with pytest.raises(TypeError):
        pytest_command(paths={"a", "b"})
    with pytest.raises(TypeError):
        pytest_command(extra=(value for value in ["-q"]))


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
    assert result.stderr.splitlines() == ["failure"]


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
    assert target.read_bytes().endswith(b"}\n")
    assert b"\r\n" not in target.read_bytes()
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


def test_example_boundary_and_exit_codes(tmp_path):
    runner = Command((sys.executable, "-S", str(ROOT / "examples/run_cli.py")))
    result = run_command(runner.positional("--format", "json", "--", sys.executable,
                                         "-S", "-c", "import sys; sys.exit(6)"))
    assert result.returncode == 6
    assert json.loads(result.stdout)["returncode"] == 6
    assert run_command(runner.positional("--format", "json")).returncode == 2
    assert run_command(runner.positional("--")).returncode == 2
    assert run_command(runner.positional("--", "cli-args-nonexistent-executable")).returncode == 127
    missing_output = tmp_path / "missing-parent" / "result.json"
    write_failure = run_command(runner.positional(
        "--format", "json", "--output", missing_output, "--",
        sys.executable, "-S", "-c", "print('done')"))
    assert write_failure.returncode == 1
    assert "failed to write output:" in write_failure.stderr
    assert "Traceback" not in write_failure.stderr
    assert not missing_output.exists()


def test_pytest_preset():
    command = pytest_command(["a.py", "b.py"], quiet=True, tb="short", summary=True,
                             extra=["-k", "a or b"])
    assert command.argv == (sys.executable, "-m", "pytest", "-q", "--tb", "short", "-ra",
                            "-k", "a or b", "a.py", "b.py")
    with pytest.raises(ValueError):
        pytest_command(tb="unknown")


def test_stdin_text_and_binary_records_roundtrip(tmp_path):
    """Flutter-style JSON input and git-style NUL records are distinct transports."""
    command = Command((sys.executable, "-S", "-c",
                       "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"))
    text = '日本語・spaces and -leading\n'
    encoded = run_command(command, stdin=text)
    assert encoded.returncode == 0
    assert encoded.stdout == text
    assert encoded.stderr == ""
    raw = b"file one\0-leading file\0\xff"
    binary = run_command(command, stdin=raw)
    assert binary.returncode == 0
    assert binary.stdout == raw.decode("utf-8", errors="replace")
    assert binary.stdout.count("\0") == 2


def test_stdin_rejects_ambiguous_inputs_even_on_dry_run():
    command = Command(("absent-executable",))
    for invalid in (123, bytearray(b"x"), ["x"], Path("input.txt")):
        with pytest.raises(TypeError, match="stdin must be"):
            run_command(command, stdin=invalid, dry_run=True)
    with pytest.raises(UnicodeEncodeError):
        run_command(command, stdin="\ud800", dry_run=True)
    dry = run_command(command, stdin="not executed", dry_run=True)
    assert not dry.executed and dry.returncode is None


def test_stdin_preserves_nonzero_exit_stderr_and_empty_payload():
    """Adding stdin must not recast nonzero subprocess exits as successful."""
    command = Command((sys.executable, "-S", "-c",
                       "import sys; data=sys.stdin.buffer.read(); "
                       "sys.stdout.buffer.write(data); "
                       "print('child-error', file=sys.stderr); sys.exit(9)"))
    result = run_command(command, stdin=b"")
    assert result.executed and not result.timed_out
    assert result.returncode == 9
    assert result.stdout == ""
    assert result.stderr.strip() == "child-error"
    result = run_command(command, stdin="some input")
    assert result.returncode == 9
    assert result.stdout == "some input"


def test_stdin_timeout_keeps_partial_diagnostics():
    """A finite stdin transaction still reports timeout and captured output."""
    command = Command((sys.executable, "-S", "-c",
                       "import sys,time; sys.stdin.buffer.read(); "
                       "print('started', flush=True); "
                       "print('diagnostic', file=sys.stderr, flush=True); "
                       "time.sleep(30)"))
    result = run_command(command, stdin=b"hello\0world", timeout=1)
    assert result.executed and result.timed_out
    assert result.returncode is None
    assert "started" in result.stdout
    assert "diagnostic" in result.stderr


def test_exclusive_output_never_overwrites_existing_file_or_symlink(tmp_path):
    original = tmp_path / "original.txt"
    original.write_text("unchanged", encoding="utf-8")
    link = tmp_path / "link.txt"
    dangling = tmp_path / "dangling.txt"
    paths = [original]
    try:
        link.symlink_to(original)
        dangling.symlink_to(tmp_path / "absent.txt")
    except (OSError, NotImplementedError):
        # On Windows without symlink privilege, keep the regular-file contract.
        pass
    else:
        paths.extend((link, dangling))
    for output in paths:
        with pytest.raises(FileExistsError):
            write_output({"value": 1}, format="json", output=output, overwrite=False)
    assert original.read_text(encoding="utf-8") == "unchanged"
    if link in paths:
        assert link.is_symlink() and dangling.is_symlink()
    assert not (tmp_path / "absent.txt").exists()
    fresh = tmp_path / "new.json"
    write_output({"title": "日本語"}, format="json", output=fresh, overwrite=False)
    assert json.loads(fresh.read_text(encoding="utf-8"))["title"] == "日本語"
    assert b"\r\n" not in fresh.read_bytes()
    with pytest.raises(TypeError, match="overwrite"):
        write_output("x", output=fresh, overwrite="false")


def test_exclusive_output_renders_before_file_creation(tmp_path):
    target = tmp_path / "new.json"
    with pytest.raises(TypeError):
        write_output(object(), format="json", output=target, overwrite=False)
    assert not target.exists()


def test_bounded_command_exact_limit_and_combined_overflow():
    command = Command((sys.executable, "-S", "-c",
                       "import sys; sys.stdout.buffer.write(b'01234'); "
                       "sys.stdout.flush(); sys.stderr.buffer.write(b'67890'); "
                       "sys.stderr.flush()"))
    exact = run_command(command, max_output_bytes=10, timeout=5)
    assert exact.returncode == 0
    assert not exact.output_limited and not exact.timed_out
    assert exact.stdout == "01234" and exact.stderr == "67890"
    exceeded = run_command(command, max_output_bytes=9, timeout=5)
    assert exceeded.output_limited and exceeded.executed
    assert exceeded.returncode is None
    assert len(exceeded.stdout.encode("utf-8") + exceeded.stderr.encode("utf-8")) == 9
    payload = json.loads(render_output(exceeded, format="json"))
    assert payload["output_limited"] is True
    assert payload["returncode"] is None


def test_bounded_zero_limit_and_stdin_utf8():
    command = Command((sys.executable, "-S", "-c",
                       "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"))
    assert run_command(command, stdin=b"", max_output_bytes=0).returncode == 0
    exceeded = run_command(command, stdin="日本語", max_output_bytes=0, timeout=5)
    assert exceeded.output_limited and exceeded.returncode is None
    assert exceeded.stdout == ""
    ok = run_command(command, stdin="日本語", max_output_bytes=9, timeout=5)
    assert ok.returncode == 0 and ok.stdout == "日本語"
    for invalid in (-1, True, 1.2, "10"):
        with pytest.raises(ValueError, match="max_output_bytes"):
            run_command(command, max_output_bytes=invalid, dry_run=True)


def test_bounded_child_terminates_excessive_output():
    command = Command((sys.executable, "-S", "-c",
                       "import os; [os.write(1,b'x'*4096) for _ in range(5000)]"))
    result = run_command(command, max_output_bytes=1024, timeout=8)
    assert result.output_limited and not result.timed_out
    assert len(result.stdout) <= 1024
    assert result.returncode is None


def test_bounded_timeout_retains_partial_stdout_and_stderr():
    command = Command((sys.executable, "-S", "-c",
                       "import sys,time; print('started',flush=True); "
                       "print('warning',file=sys.stderr,flush=True); time.sleep(30)"))
    result = run_command(command, max_output_bytes=100, timeout=1)
    assert result.timed_out and not result.output_limited
    assert result.returncode is None
    assert "started" in result.stdout and "warning" in result.stderr


def test_example_no_overwrite_and_bounded_output_exit_codes(tmp_path):
    runner = Command((sys.executable, "-S", str(ROOT / "examples/run_cli.py")))
    target = tmp_path / "out.txt"
    target.write_text("keep", encoding="utf-8")
    refused = run_command(runner.positional(
        "--no-overwrite", "--output", target, "--",
        sys.executable, "-S", "-c", "print('hello')"))
    assert refused.returncode == 1
    assert target.read_text(encoding="utf-8") == "keep"
    blocked = run_command(runner.positional(
        "--max-output-bytes", "3", "--",
        sys.executable, "-S", "-c", "print('excess')"))
    assert blocked.returncode == 125
    assert "output limit exceeded" in blocked.stderr
    okay = run_command(runner.positional(
        "--no-overwrite", "--output", tmp_path / "new.txt", "--",
        sys.executable, "-S", "-c", "print('ok')"))
    assert okay.returncode == 0
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "ok\n"



def test_exclusive_output_link_failure_keeps_destination_absent(tmp_path, monkeypatch):
    """An unsupported filesystem or publication failure must not leak a partial target."""
    import cli_args

    def deny_link(source, destination):
        assert Path(source).is_file()
        assert not Path(destination).exists()
        raise OSError("hard links not supported")

    monkeypatch.setattr(cli_args.os, "link", deny_link)
    destination = tmp_path / "result.json"
    with pytest.raises(OSError, match="hard links not supported"):
        write_output({"ok": True}, format="json", output=destination, overwrite=False)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_bounded_small_flushed_overflow_without_waiting_for_eof():
    """cap+1 byte followed by sleep must trigger overflow, not the timeout."""
    import time

    cap = 100
    command = Command((sys.executable, "-S", "-c",
                       "import os,time; os.write(1,b'x'*101); time.sleep(30)"))
    started = time.monotonic()
    result = run_command(command, max_output_bytes=cap, timeout=5)
    assert time.monotonic() - started < 5
    assert result.output_limited and not result.timed_out
    assert result.returncode is None and result.executed
    assert result.stdout == "x" * cap
    assert result.stderr == ""


def test_bounded_small_flushed_stderr_overflow():
    """Both pipes must apply the same non-EOF-dependent limit."""
    command = Command((sys.executable, "-S", "-c",
                       "import os,time; os.write(2,b'e'*51); time.sleep(30)"))
    result = run_command(command, max_output_bytes=50, timeout=5)
    assert result.output_limited and not result.timed_out
    assert result.returncode is None
    assert result.stderr == "e" * 50


def test_build_env_mapping_and_sequence():
    base = {"A": "1", "B": "2"}
    assert build_env(base=base, inherit=True) == base
    assert build_env(base=base, inherit=False) == {}
    assert build_env({"B": "3", "C": "4"}, base=base, inherit=True) == {"A": "1", "B": "3", "C": "4"}
    assert build_env({"B": "3", "C": "4"}, base=base, inherit=False) == {"B": "3", "C": "4"}
    seq_result = build_env(["B=3", "C=4", "D=x=y"], base=base, inherit=True)
    assert seq_result == {"A": "1", "B": "3", "C": "4", "D": "x=y"}


def test_build_env_rejections():
    with pytest.raises(TypeError, match="inherit"):
        build_env(inherit="true")
    with pytest.raises(TypeError, match="base"):
        build_env(base="not_a_map")
    with pytest.raises(TypeError, match="keys and values"):
        build_env({1: "a"})
    with pytest.raises(TypeError, match="keys and values"):
        build_env({"a": 1})
    with pytest.raises(ValueError, match="NUL"):
        build_env({"a\0b": "c"})
    with pytest.raises(ValueError, match="NUL"):
        build_env({"a": "c\0d"})
    with pytest.raises(TypeError, match="ordered sequence"):
        build_env("A=1")
    with pytest.raises(TypeError, match="ordered sequence"):
        build_env(b"A=1")
    with pytest.raises(TypeError, match="ordered sequence"):
        build_env(Path("A=1"))
    with pytest.raises(TypeError, match="ordered sequence"):
        build_env({"A=1", "B=2"})
    with pytest.raises(TypeError, match="ordered sequence"):
        build_env((x for x in ["A=1"]))
    with pytest.raises(TypeError, match="entries must be strings"):
        build_env([123])
    with pytest.raises(ValueError, match="NUL"):
        build_env(["A=1\0" + "2"])
    with pytest.raises(ValueError, match="missing '='"):
        build_env(["NOEQUALS"])
    with pytest.raises(ValueError, match="empty key"):
        build_env(["=VALUE"])


def test_example_stdin_and_env_options(tmp_path):
    runner = Command((sys.executable, "-S", str(ROOT / "examples/run_cli.py")))

    # --stdin option
    stdin_res = run_command(runner.positional(
        "--stdin", "hello from stdin", "--",
        sys.executable, "-S", "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"))
    assert stdin_res.returncode == 0
    assert stdin_res.stdout == "HELLO FROM STDIN"

    # --stdin-file option
    stdin_file = tmp_path / "payload.bin"
    stdin_file.write_bytes(b"binary\0payload")
    file_res = run_command(runner.positional(
        "--stdin-file", stdin_file, "--",
        sys.executable, "-S", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"))
    assert file_res.returncode == 0
    assert file_res.stdout == "binary\0payload"

    # Mutually exclusive --stdin and --stdin-file
    excl_res = run_command(runner.positional(
        "--stdin", "text", "--stdin-file", stdin_file, "--",
        sys.executable, "-S", "-c", "print('bad')"))
    assert excl_res.returncode == 2

    # Missing stdin-file error
    missing_file = tmp_path / "nonexistent.txt"
    missing_res = run_command(runner.positional(
        "--stdin-file", missing_file, "--",
        sys.executable, "-S", "-c", "print('bad')"))
    assert missing_res.returncode == 1
    assert "failed to read stdin file:" in missing_res.stderr

    # --env option
    env_res = run_command(runner.positional(
        "--env", "TEST_VAR_A=alpha", "--env", "TEST_VAR_B=beta=gamma", "--",
        sys.executable, "-S", "-c",
        "import os; print(os.environ.get('TEST_VAR_A'), os.environ.get('TEST_VAR_B'))"))
    assert env_res.returncode == 0
    assert env_res.stdout.strip() == "alpha beta=gamma"

    # Malformed --env option
    bad_env_res = run_command(runner.positional(
        "--env", "INVALID_NO_EQUALS", "--",
        sys.executable, "-S", "-c", "print('bad')"))
    assert bad_env_res.returncode == 2


@pytest.mark.parametrize("invalid", [
    {"BAD=KEY": "value"}, {"": "value"}, {"BAD\0KEY": "value"},
    {"KEY": "bad\0value"}, {1: "value"}, {"KEY": 1},
])
def test_build_env_validates_extra_and_inherited_base(invalid):
    error = TypeError if any(not isinstance(k, str) or not isinstance(v, str)
                             for k, v in invalid.items()) else ValueError
    with pytest.raises(error):
        build_env(invalid, inherit=False)
    with pytest.raises(error):
        build_env(base=invalid)
    assert build_env(base=invalid, inherit=False) == {}


def test_build_env_accepts_empty_and_equals_in_values():
    assert build_env({"EMPTY": "", "VALUE": "x=y"}, inherit=False) == {"EMPTY": "", "VALUE": "x=y"}
