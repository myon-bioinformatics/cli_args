import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

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


def _free_local_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_http_server_real_localhost(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_bytes(b"stdlib-server\n")
    port = _free_local_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/hello.txt", timeout=1) as response:
                    assert response.read().decode("utf-8") == "stdlib-server\n"
                    break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError("python -m http.server exited before serving")
                if time.monotonic() >= deadline:
                    raise AssertionError("python -m http.server did not become ready")
                time.sleep(0.05)
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
