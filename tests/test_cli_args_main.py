import base64
import dataclasses
import io
import json
import re
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

import cli_args
from cli_args import Command, CommandResult, run_command

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli_args.py"

_COMMAND_RESULT_FIELD_NAMES = (
    "argv",
    "returncode",
    "stdout",
    "stderr",
    "executed",
    "timed_out",
    "output_limited",
)


def test_command_result_public_fields_unchanged():
    assert tuple(field.name for field in fields(CommandResult)) == _COMMAND_RESULT_FIELD_NAMES


def test_command_result_asdict_is_json_serializable():
    result = CommandResult(("tool",), 0, "out", "err", True)
    json.dumps(asdict(result), ensure_ascii=False, allow_nan=False)


def test_run_command_asdict_is_json_serializable():
    result = run_command(
        Command((sys.executable, "-S", "-c", "print('ok')")),
    )
    json.dumps(asdict(result), ensure_ascii=False, allow_nan=False)


def invoke(*argv: str, stdin: str | bytes = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", str(CLI), *argv],
        input=stdin,
        capture_output=True,
        text=isinstance(stdin, str),
        cwd=ROOT,
    )


def test_version_matches_pyproject():
    match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert match is not None
    assert cli_args.__version__ == match.group(1)


def test_version_on_standalone_copy(tmp_path: Path):
    standalone = tmp_path / "cli_args.py"
    standalone.write_text(CLI.read_text(encoding="utf-8"), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-S", str(standalone), "--version"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"cli_args.py {cli_args.__version__}"


def test_run_json_roundtrip_and_child_exit_code_on_stdout():
    payload = {
        "argv": [sys.executable, "-S", "-c", "import sys; sys.exit(6)"],
    }
    proc = invoke("run", stdin=json.dumps(payload))
    assert proc.returncode == 0
    assert proc.stderr == ""
    body = json.loads(proc.stdout)
    assert body["returncode"] == 6
    assert body["executed"] is True
    assert "stdout_b64" in body and "stderr_b64" in body


def test_run_wrapper_zero_even_when_child_fails():
    proc = invoke(
        "run",
        stdin=json.dumps({"argv": [sys.executable, "-S", "-c", "raise SystemExit(3)"]}),
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["returncode"] == 3


def test_run_japanese_argv_and_output():
    payload = {
        "argv": [
            sys.executable,
            "-S",
            "-c",
            "print('日本語')",
        ],
    }
    proc = invoke("run", stdin=json.dumps(payload, ensure_ascii=False))
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["stdout"] == "日本語\n"
    assert base64.b64decode(body["stdout_b64"]) == "日本語\n".encode("utf-8")
    assert body["returncode"] == 0


def test_run_non_utf8_output_has_reversible_b64():
    proc = invoke(
        "run",
        stdin=json.dumps(
            {"argv": [sys.executable, "-S", "-c", "import os; os.write(1, b'\\xff\\xfe')"]},
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert "\ufffd" in body["stdout"]
    assert base64.b64decode(body["stdout_b64"]) == b"\xff\xfe"


def test_run_dry_run():
    proc = invoke(
        "run",
        stdin=json.dumps(
            {"argv": ["cli-args-nonexistent-executable"], "dry_run": True},
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["executed"] is False
    assert body["returncode"] is None
    assert body["stdout_b64"] == ""


def test_run_timeout():
    payload = {
        "argv": [
            sys.executable,
            "-S",
            "-c",
            "import time; print('started', flush=True); time.sleep(30)",
        ],
        "timeout": 1,
    }
    proc = invoke("run", stdin=json.dumps(payload))
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["timed_out"] is True
    assert body["returncode"] is None
    assert "started" in body["stdout"]


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "{",
        json.dumps({"argv": [sys.executable], "shell": True}),
        json.dumps({"argv": [sys.executable], "extra": 1}),
        json.dumps({"argv": "not-a-list"}),
        json.dumps({}),
        json.dumps({"argv": [], "dry_run": "yes"}),
        '{"a":NaN}',
    ],
)
def test_run_invalid_request_exits_two(stdin: str):
    proc = invoke("run", stdin=stdin)
    assert proc.returncode == 2
    assert proc.stderr.strip()
    assert proc.stdout == ""


def test_render_nan_json_exits_two():
    proc = invoke("render", "--format", "json", stdin='{"a":NaN}')
    assert proc.returncode == 2
    assert proc.stderr.strip()
    assert proc.stdout == ""


def test_read_stdin_text_rejects_oversized_input():
    payload = b"x" * (cli_args._CLI_STDIN_MAX_BYTES + 1)
    sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
    try:
        with pytest.raises(cli_args._CliRequestError, match="stdin exceeds size limit"):
            cli_args._read_stdin_text()
    finally:
        sys.stdin = sys.__stdin__


def test_load_stdin_json_rejects_nan_constants():
    sys.stdin = io.TextIOWrapper(io.BytesIO(b'{"x":NaN}'), encoding="utf-8")
    try:
        with pytest.raises(cli_args._CliRequestError, match="NaN or Infinity"):
            cli_args._load_stdin_json()
    finally:
        sys.stdin = sys.__stdin__


def test_run_missing_executable_exits_one():
    proc = invoke(
        "run",
        stdin=json.dumps({"argv": ["cli-args-nonexistent-executable-ef75"]}),
    )
    assert proc.returncode == 1
    assert proc.stderr.strip()
    assert "Traceback" not in proc.stderr


def test_run_missing_cwd_exits_one():
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [sys.executable, "-S", "-c", "print(1)"],
                "cwd": "/nonexistent/cli-args-cwd-ef75",
            },
        ),
    )
    assert proc.returncode == 1
    assert proc.stderr.strip()
    assert "Traceback" not in proc.stderr


def test_render_json_and_text():
    value = {"title": "日本語", "n": 1}
    json_proc = invoke("render", "--format", "json", stdin=json.dumps(value, ensure_ascii=False))
    assert json_proc.returncode == 0
    assert json.loads(json_proc.stdout) == value

    text_proc = invoke("render", "--format", "text", stdin=json.dumps(value))
    assert text_proc.returncode == 0
    assert text_proc.stdout == "{'title': '日本語', 'n': 1}\n"


def test_cli_usage_and_version():
    version_proc = invoke("--version")
    assert version_proc.returncode == 0
    assert version_proc.stdout.strip() == f"cli_args.py {cli_args.__version__}"
    help_proc = invoke("--help")
    assert help_proc.returncode == 0
    assert "run" in help_proc.stdout
    assert invoke().returncode == 2


def test_import_main_has_no_side_effects():
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import cli_args; assert cli_args.__version__"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
