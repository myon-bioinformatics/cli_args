from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
from threading import Thread
from urllib.parse import quote

import pytest

from cli_args import Command, run_command


def available(name):
    executable = shutil.which(name)
    if executable is None:
        pytest.fail(name + " is not installed in the integration image")
    return executable


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def local_server(directory):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(directory)),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_ls_real_separator_space_unicode_and_leading_hyphen(tmp_path):
    name = "-leading 日本語 file.txt"
    (tmp_path / name).write_text("ok\n", encoding="utf-8")
    command = Command((available("ls"),)).flag("-1").passthrough([name], separator=True)
    result = run_command(command, cwd=tmp_path)
    assert (result.returncode, result.stdout) == (0, name + "\n")


def test_git_real_leading_hyphen_unicode_path(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    name = "-leading 日本語.txt"
    (tmp_path / name).write_text("hello\n", encoding="utf-8")
    assert run_command(git.positional("add").passthrough([name], separator=True)).returncode == 0
    result = run_command(git.positional("ls-files", "-z"))
    assert (result.returncode, result.stdout) == (0, name + "\0")


def test_curl_real_empty_and_unicode_values(tmp_path):
    curl = (
        Command((available("curl"),))
        .positional("--disable")
        .flag("--silent")
        .flag("--show-error")
        .flag("--fail")
        .option("--noproxy", "*")
        .option("--max-time", "5")
        .option("--user-agent", "")
    )
    name = "日本 語.html"
    (tmp_path / name).write_text("<p>container</p>", encoding="utf-8")
    output = tmp_path / "保存 page.html"
    with local_server(tmp_path) as url:
        result = run_command(
            curl.repeated("-H", ["X-Empty:", "X-Label: 日本語 value"])
            .option("--output", output)
            .positional(url + "/" + quote(name)),
            timeout=10,
        )
    assert result.returncode == 0
    assert output.read_text(encoding="utf-8") == "<p>container</p>"


def test_journalctl_container_real_and_service_boundary():
    journalctl = available("journalctl")
    real = run_command(Command((journalctl, "--version")))
    assert real.returncode == 0
    assert "systemd" in real.stdout.lower()

    construct_only = (
        Command((journalctl,))
        .repeated("-u", ["alpha.service", "unit with space.service"])
        .option("--since", "2026-10-01 00:00:00")
        .option("--until", "2026-10-01 01:00:00")
        .option("-n", "5")
        .flag("--no-pager")
    )
    assert construct_only.argv == (
        journalctl,
        "-u", "alpha.service",
        "-u", "unit with space.service",
        "--since", "2026-10-01 00:00:00",
        "--until", "2026-10-01 01:00:00",
        "-n", "5",
        "--no-pager",
    )
