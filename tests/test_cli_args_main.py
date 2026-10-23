import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli_args.py"


def invoke(*argv: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", str(CLI), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


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
    assert body["returncode"] == 0


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
    ],
)
def test_run_invalid_request_exits_two(stdin: str):
    proc = invoke("run", stdin=stdin)
    assert proc.returncode == 2
    assert proc.stderr.count("\n") <= 1 or proc.stderr.strip()
    assert proc.stderr.strip()
    assert proc.stdout == ""


def test_run_missing_executable_exits_one():
    proc = invoke(
        "run",
        stdin=json.dumps({"argv": ["cli-args-nonexistent-executable-ef75"]}),
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
    assert invoke("--version").returncode == 0
    assert invoke("--version").stdout.startswith("cli_args.py ")
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
