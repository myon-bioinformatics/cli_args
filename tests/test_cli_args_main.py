import base64
import contextlib
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

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
    """Run cli_args.py; decode captured stdout/stderr as UTF-8 (CLI writes stdout.buffer)."""
    input_bytes = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, "-S", str(CLI), *argv],
        input=input_bytes,
        capture_output=True,
        cwd=ROOT,
        env=env,
    )
    return subprocess.CompletedProcess(
        args=completed.args,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8"),
        stderr=completed.stderr.decode("utf-8"),
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
        encoding="utf-8",
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
    assert body["output_limited"] is False
    assert "stdout_b64" in body and "stderr_b64" in body


def test_run_wrapper_zero_even_when_child_fails():
    proc = invoke(
        "run",
        stdin=json.dumps({"argv": [sys.executable, "-S", "-c", "raise SystemExit(3)"]}),
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["returncode"] == 3


def test_run_env_not_altered_by_bridge_defaults():
    code = (
        "import os, json; "
        "print(json.dumps({"
        "'PYTHONUTF8': os.environ.get('PYTHONUTF8'), "
        "'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING')"
        "}))"
    )
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [sys.executable, "-S", "-c", code],
                "env": {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"},
            },
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    seen = json.loads(body["stdout"].strip())
    assert seen["PYTHONUTF8"] == "0"
    assert seen["PYTHONIOENCODING"] == "cp1252"


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
    stdout_raw = base64.b64decode(body["stdout_b64"])
    assert stdout_raw.replace(b"\r\n", b"\n") == "日本語\n".encode("utf-8")
    assert body["stdout"].replace("\r\n", "\n") == "日本語\n"
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
        encoding="utf-8",
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_main_render_text_with_redirect_stdout():
    value = {"title": "日本語", "n": 1}
    capture = io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.TextIOWrapper(
        io.BytesIO(json.dumps(value).encode("utf-8")),
        encoding="utf-8",
    )
    try:
        with contextlib.redirect_stdout(capture):
            assert cli_args._main(["render", "--format", "text"]) == 0
    finally:
        sys.stdin = old_stdin
    assert "日本語" in capture.getvalue()


def test_cli_host_max_buffer_bytes_adds_margin():
    cap = cli_args.CLI_RUN_RESPONSE_MAX_BYTES
    assert cli_args.cli_host_max_buffer_bytes(cap) == cap + cli_args.CLI_HOST_RESPONSE_MARGIN_BYTES


def test_emit_cli_stdout_bytes_writes_measured_utf8(monkeypatch):
    captured: list[bytes] = []

    class _Buffer:
        def write(self, data: bytes) -> int:
            captured.append(data)
            return len(data)

        def flush(self) -> None:
            return None

    class _FakeStdout:
        buffer = _Buffer()

    monkeypatch.setattr(sys, "stdout", _FakeStdout())
    payload = "日本語\n\x01\xff"
    cli_args._emit_cli_stdout(payload, None)
    assert captured == [payload.encode("utf-8")]


def test_cli_render_stdout_bytes_match_utf8_on_pipe():
    value = {"text": "日本語\nsecond", "n": 1}
    proc = subprocess.run(
        [sys.executable, "-S", str(CLI), "render", "--format", "json"],
        input=json.dumps(value, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0
    expected = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert proc.stdout == expected


def test_run_max_output_boundary_under_and_over():
    limit = 64 * 1024
    under = limit - 1
    over = limit + 1
    code_under = (
        "import sys; sys.stdout.buffer.write(b'x' * "
        f"{under}); sys.stderr.buffer.write(b'y')"
    )
    proc_under = invoke(
        "run",
        stdin=json.dumps(
            {"argv": [sys.executable, "-S", "-c", code_under], "max_output": limit},
        ),
    )
    assert proc_under.returncode == 0
    body_under = json.loads(proc_under.stdout)
    assert body_under["output_limited"] is False
    assert len(base64.b64decode(body_under["stdout_b64"])) == under
    assert len(base64.b64decode(body_under["stderr_b64"])) == 1

    code_over = f"import sys; sys.stdout.buffer.write(b'x' * {over})"
    proc_over = invoke(
        "run",
        stdin=json.dumps(
            {"argv": [sys.executable, "-S", "-c", code_over], "max_output": limit},
        ),
    )
    assert proc_over.returncode == 0
    body_over = json.loads(proc_over.stdout)
    assert body_over["output_limited"] is True
    assert body_over["returncode"] is None
    assert len(base64.b64decode(body_over["stdout_b64"])) == limit


def test_run_max_output_exactly_at_limit_binary():
    limit = 512
    pattern = bytes((i % 256 for i in range(32)))
    repeats = limit // len(pattern)
    extra = limit - repeats * len(pattern)
    blob = pattern * repeats + pattern[:extra]
    code = "import sys; sys.stdout.buffer.write(" + repr(blob) + ")"
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [sys.executable, "-S", "-c", code],
                "max_output": limit,
                "response_max_bytes": cli_args.CLI_RUN_RESPONSE_MAX_BYTES,
            },
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["output_limited"] is False
    assert base64.b64decode(body["stdout_b64"]) == blob


def test_run_binary_control_bytes_under_response_cap():
    limit = 128 * 1024
    code = f"import sys; sys.stdout.buffer.write(bytes(i % 256 for i in range({limit})))"
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [sys.executable, "-S", "-c", code],
                "max_output": limit,
                "response_max_bytes": cli_args.CLI_RUN_RESPONSE_MAX_BYTES,
            },
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["output_limited"] is False
    assert len(base64.b64decode(body["stdout_b64"])) == limit


def test_run_response_max_bytes_rejects_oversized_json():
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [sys.executable, "-S", "-c", "import sys; sys.stdout.write('x' * 200)"],
                "response_max_bytes": 64,
            },
        ),
    )
    assert proc.returncode == 1
    assert "response exceeds response_max_bytes" in proc.stderr
    assert proc.stdout == ""


def test_run_long_argv_with_small_max_output_and_response_cap():
    long_arg = "z" * 20000
    proc = invoke(
        "run",
        stdin=json.dumps(
            {
                "argv": [
                    sys.executable,
                    "-S",
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'a' * 900)",
                    long_arg,
                ],
                "max_output": 1000,
                "response_max_bytes": cli_args.CLI_RUN_RESPONSE_MAX_BYTES,
            },
        ),
    )
    assert proc.returncode == 0
    body = json.loads(proc.stdout)
    assert body["argv"][-1] == long_arg
    assert body["output_limited"] is False
    assert len(base64.b64decode(body["stdout_b64"])) == 900


def _deep_nested_array(depth: int, width: int) -> list[Any]:
    value: Any = list(range(width))
    for _ in range(depth):
        value = [value]
    return value


def test_render_deep_nesting_response_cap_boundary():
    value = _deep_nested_array(200, 3000)
    stdin = json.dumps(value)
    ok_proc = invoke("render", "--format", "json", stdin=stdin)
    assert ok_proc.returncode == 0
    rendered_len = len(ok_proc.stdout.encode("utf-8"))
    assert rendered_len > 500_000

    over_proc = invoke(
        "render",
        "--format",
        "json",
        "--response-max-bytes",
        str(rendered_len - 1),
        stdin=stdin,
    )
    assert over_proc.returncode == 1
    assert "response exceeds response_max_bytes" in over_proc.stderr

    at_proc = invoke(
        "render",
        "--format",
        "json",
        "--response-max-bytes",
        str(rendered_len),
        stdin=stdin,
    )
    assert at_proc.returncode == 0
    assert at_proc.stdout == ok_proc.stdout
