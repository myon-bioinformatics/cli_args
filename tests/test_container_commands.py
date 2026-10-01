from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import shutil
from threading import Thread
from urllib.parse import quote

import pytest

from cli_args import Command, run_command


if os.environ.get("CLI_ARGS_CONTAINER_REAL") != "1":
    pytest.skip(
        "container-real suite runs only inside the explicit Docker integration boundary",
        allow_module_level=True,
    )


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
    command = (Command((available("ls"),)).flag("-1").flag("--color=never")
               .passthrough([name], separator=True))
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
            curl.repeated("-H", ["X-Empty:", "X-Label: value with spaces"])
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


def test_coreutils_sort_zero_terminated_real(tmp_path):
    sort = available("sort")
    source = tmp_path / "records.bin"
    source.write_bytes("b\0a\0日本語\0".encode("utf-8"))
    result = run_command(
        Command((sort,)).flag("-z").flag("--stable").positional(source),
        env={"LC_ALL": "C"},
    )
    assert result.returncode == 0
    assert result.stdout == "a\0b\0日本語\0"


def test_sed_real_numeric_and_relative_ranges(tmp_path):
    sed = available("sed")
    source = tmp_path / "lines.txt"
    source.write_text("1\n2\n3\n4\n5\n6\n7\n", encoding="utf-8")

    numeric = run_command(Command((sed, "-n", "4,6p", str(source))))
    assert (numeric.returncode, numeric.stdout) == (0, "4\n5\n6\n")

    # GNU sed extension: addr,+N means the matching address plus N lines.
    relative = run_command(Command((sed, "-n", "4,+2p", str(source))))
    assert (relative.returncode, relative.stdout) == (0, "4\n5\n6\n")


def test_grep_real_literal_exact_max_count_and_nul_filename(tmp_path):
    grep = available("grep")
    content = tmp_path / "content.txt"
    content.write_text("alpha\nalpha beta\nbeta\n", encoding="utf-8")

    exact = run_command(
        Command((grep,))
        .flag("-F")
        .flag("-x")
        .option("-m", "1")
        .passthrough(["alpha", str(content)], separator=True)
    )
    assert (exact.returncode, exact.stdout) == (0, "alpha\n")

    weird = tmp_path / "-match 日本語 file.txt"
    weird.write_text("needle\n", encoding="utf-8")
    names = run_command(
        Command((grep,))
        .flag("-F")
        .flag("-l")
        .flag("-Z")
        .passthrough(["needle", str(weird)], separator=True)
    )
    assert names.returncode == 0
    assert names.stdout == str(weird) + "\0"


def test_find_print0_and_xargs_arg_file_real(tmp_path):
    find = available("find")
    xargs = available("xargs")
    root = tmp_path / "tree"
    root.mkdir()
    names = ["normal.txt", "space 日本語.txt", "-leading.txt"]
    for name in names:
        (root / name).write_text(name, encoding="utf-8")

    found = run_command(Command((find, str(root), "-type", "f", "-print0")))
    assert found.returncode == 0
    actual = set(found.stdout.split("\0")[:-1])
    expected = {str(root / name) for name in names}
    assert actual == expected

    arg_file = tmp_path / "args.bin"
    values = ["one", "two words", "-leading", "日本語"]
    arg_file.write_bytes(("\0".join(values) + "\0").encode("utf-8"))
    probe = (
        Command((xargs,))
        .flag("-0")
        .option("-a", arg_file)
        .flag("-r")
        .option("-n", "2")
        .positional(
            "python", "-S", "-c",
            "import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))",
        )
    )
    result = run_command(probe)
    assert result.returncode == 0, result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        ["one", "two words"],
        ["-leading", "日本語"],
    ]


def test_ffmpeg_container_real_lavfi_to_null():
    ffmpeg = available("ffmpeg")
    command = (
        Command((ffmpeg,))
        .flag("-hide_banner")
        .flag("-nostdin")
        .option("-loglevel", "error")
        .option("-f", "lavfi")
        .option("-i", "sine=frequency=440:duration=0.05")
        .option("-f", "null")
        .positional("-")
    )
    result = run_command(command, timeout=30)
    assert result.returncode == 0, result.stderr
