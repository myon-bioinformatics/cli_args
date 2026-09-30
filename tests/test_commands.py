from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
from threading import Thread

import pytest

from cli_args import Command, pytest_command, run_command


def available(name):
    executable = shutil.which(name)
    if executable is None:
        pytest.skip(name + " is not installed")
    return executable


def test_pytest_real_two_files_and_failure(tmp_path):
    first = tmp_path / "test_first.py"
    second = tmp_path / "test_second.py"
    first.write_text("def test_ok(): assert True\n")
    second.write_text("def test_bad(): assert False\n")
    result = run_command(pytest_command([str(first), str(second)], quiet=True,
        tb="short", summary=True, extra=["--override-ini", "addopts="]), cwd=tmp_path, timeout=30)
    assert result.returncode == 1
    assert "1 failed, 1 passed" in result.stdout
    assert "FAILED test_second.py::test_bad" in result.stdout


def test_git_real_repository(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    (tmp_path / "日本 語.txt").write_text("hello", encoding="utf-8")
    assert run_command(git.positional("add", "--", "日本 語.txt")).returncode == 0
    result = run_command(git.positional("ls-files", "-z"))
    assert (result.returncode, result.stdout) == (0, "日本 語.txt\0")
    assert run_command(git.positional("not-a-git-command")).returncode != 0


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def local_server(directory):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_curl_real_local_http_and_failure(tmp_path):
    curl = Command((available("curl"),)).positional("--disable").flag("--silent").flag("--show-error").flag("--fail")
    curl = curl.option("--noproxy", "*").option("--max-time", "5")
    (tmp_path / "article.html").write_text("<h1>日本語</h1>", encoding="utf-8")
    output = tmp_path / "saved page.html"
    with local_server(tmp_path) as url:
        result = run_command(curl.repeated("-H", ["Accept: text/html", "X-Test: cli"])
                             .option("--output", output).positional(url + "/article.html"), timeout=10)
        assert result.returncode == 0
        assert output.read_text(encoding="utf-8") == "<h1>日本語</h1>"
        assert run_command(curl.positional(url + "/missing"), timeout=10).returncode == 22


def test_gh_mock_transport_records_argv(tmp_path):
    # Portable subprocess stub; this does NOT claim live/authenticated gh coverage.
    stub = tmp_path / "gh_stub.py"
    stub.write_text("import json,sys\nprint(json.dumps({'argv':sys.argv[1:]}))\n")
    result = run_command(Command((sys.executable, "-S", str(stub)))
        .positional("issue", "list").option("--repo", "owner/repo")
        .option("--json", "number,title").option("--state", "open"))
    assert json.loads(result.stdout)["argv"] == ["issue", "list", "--repo", "owner/repo",
                                               "--json", "number,title", "--state", "open"]
