import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from cli_args import Command, run_command


def test_json_tool_real(tmp_path):
    source = tmp_path / "input.json"
    source.write_text('{"z":1,"a":"日本語"}', encoding="utf-8")
    result = run_command(
        Command((sys.executable, "-m", "json.tool"))
        .flag("--sort-keys")
        .positional(source),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list(json.loads(result.stdout)) == ["a", "z"]


def test_zipfile_real_create_and_list(tmp_path):
    first = tmp_path / "a file.txt"
    second = tmp_path / "日本語.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    archive = tmp_path / "bundle.zip"

    created = run_command(
        Command((sys.executable, "-m", "zipfile", "-c", archive))
        .positional(first, second),
        cwd=tmp_path,
        timeout=30,
    )
    assert created.returncode == 0, created.stderr
    assert archive.is_file()

    listed = run_command(
        Command((sys.executable, "-m", "zipfile", "-l", archive)),
        cwd=tmp_path,
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert listed.returncode == 0, listed.stderr
    assert "a file.txt" in listed.stdout
    assert "日本語.txt" in listed.stdout


def test_tarfile_real_create_and_list(tmp_path):
    source = tmp_path / "space 日本語.txt"
    source.write_text("payload", encoding="utf-8")
    archive = tmp_path / "bundle.tar"

    created = run_command(
        Command((sys.executable, "-m", "tarfile", "-c", archive)).positional(source),
        cwd=tmp_path,
        timeout=30,
    )
    assert created.returncode == 0, created.stderr
    assert archive.is_file()

    listed = run_command(
        Command((sys.executable, "-m", "tarfile", "-l", archive)),
        cwd=tmp_path,
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert listed.returncode == 0, listed.stderr
    assert "space 日本語.txt" in listed.stdout


def test_http_server_cli_starts_localhost(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_bytes(b"stdlib-server\n")
    log_path = tmp_path / "http-server.log"
    with log_path.open("w+b") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "http.server",
                "0",
                "--bind",
                "127.0.0.1",
                "--directory",
                str(tmp_path),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.flush()
                    log.seek(0)
                    raise AssertionError(
                        "python -m http.server exited before serving: "
                        + log.read().decode("utf-8", errors="replace")
                    )
                time.sleep(0.05)
                log.flush()
                log.seek(0)
                output = log.read().decode("utf-8", errors="replace")
                if "Serving HTTP on" in output:
                    break
            else:
                # A still-running http.server after startup is stronger evidence
                # than a runner-specific localhost client route.
                assert process.poll() is None
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_platform_and_compileall_real(tmp_path):
    platform = run_command(Command((sys.executable, "-m", "platform")), timeout=30)
    assert platform.returncode == 0
    assert platform.stdout.strip()

    source = tmp_path / "src"
    source.mkdir()
    (source / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    compiled = run_command(
        Command((sys.executable, "-m", "compileall", "-q", source)),
        timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr


def test_tempfile_stdlib_api_real():
    code = (
        "import pathlib,tempfile;"
        "p=pathlib.Path(tempfile.mkdtemp());"
        "print(p.is_dir());"
        "p.rmdir()"
    )
    result = run_command(Command((sys.executable, "-c", code)), timeout=30)
    assert (result.returncode, result.stdout.strip()) == (0, "True")
