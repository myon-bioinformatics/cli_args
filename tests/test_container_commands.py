"""Container-real CLI evidence: real tools inside the test-only image built from ``tests/docker/Dockerfile``.

Runs only where ``CLI_ARGS_CONTAINER_REAL=1`` (baked into that image); there a missing tool fails instead of skipping.
"""
import hashlib, json, os
from urllib.parse import quote

import pytest

from cli_args import Command, run_command
from conftest import available, local_server


if os.environ.get("CLI_ARGS_CONTAINER_REAL") != "1":
    pytest.skip(
        "container-real suite runs only inside the explicit Docker integration boundary",
        allow_module_level=True,
    )


# ---- argv transport per tool ----
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


# ---- pattern contracts: short-circuit, NUL-safe, archives, ripgrep ----
def test_sed_grep_and_find_short_circuit_patterns(tmp_path):
    sed = available("sed")
    grep = available("grep")
    find = available("find")

    lines = tmp_path / "lines.txt"
    lines.write_text("1\n2\n3\n4\n5\n6\n7\n", encoding="utf-8")
    numeric = run_command(Command((sed, "-n", "4,6p", str(lines))))
    assert (numeric.returncode, numeric.stdout) == (0, "4\n5\n6\n")
    relative = run_command(Command((sed, "-n", "4,+2p", str(lines))))
    assert (relative.returncode, relative.stdout) == (0, "4\n5\n6\n")

    exact = run_command(
        Command((grep,))
        .flag("-F")
        .flag("-x")
        .option("-m", "1")
        .passthrough(["4", str(lines)], separator=True)
    )
    assert (exact.returncode, exact.stdout) == (0, "4\n")

    quiet = run_command(
        Command((grep,)).flag("-F").flag("-q").passthrough(["5", str(lines)], separator=True)
    )
    assert (quiet.returncode, quiet.stdout) == (0, "")

    tree = tmp_path / "tree"
    tree.mkdir()
    for name in ["a.txt", "b.txt", "c.txt"]:
        (tree / name).write_text(name, encoding="utf-8")
    first = run_command(
        Command((find, str(tree), "-type", "f", "-print", "-quit"))
    )
    assert first.returncode == 0
    assert len(first.stdout.splitlines()) == 1


def test_nul_safe_find_xargs_and_sort_contracts(tmp_path):
    find = available("find")
    xargs = available("xargs")
    sort = available("sort")

    tree = tmp_path / "tree"
    tree.mkdir()
    names = ["normal.txt", "space 日本語.txt", "-leading.txt", "line\nbreak.txt"]
    for name in names:
        (tree / name).write_text(name, encoding="utf-8")

    found = run_command(Command((find, str(tree), "-type", "f", "-print0")))
    assert found.returncode == 0
    assert set(found.stdout.split("\0")[:-1]) == {str(tree / name) for name in names}

    args_file = tmp_path / "args.bin"
    values = ["one", "two words", "-leading", "日本語", "line\nbreak"]
    args_file.write_bytes(("\0".join(values) + "\0").encode("utf-8"))
    batched = run_command(
        Command((xargs,))
        .flag("-0")
        .option("-a", args_file)
        .flag("-r")
        .option("-n", "2")
        .positional(
            "python", "-S", "-c",
            "import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))",
        )
    )
    assert batched.returncode == 0, batched.stderr
    assert [json.loads(line) for line in batched.stdout.splitlines()] == [
        ["one", "two words"],
        ["-leading", "日本語"],
        ["line\nbreak"],
    ]

    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    no_run = run_command(
        Command((xargs,))
        .flag("-0")
        .option("-a", empty)
        .flag("-r")
        .positional("python", "-S", "-c", "raise SystemExit(99)")
    )
    assert no_run.returncode == 0

    records = tmp_path / "records.bin"
    records.write_bytes("b\0a\0日本語\0".encode("utf-8"))
    sorted_result = run_command(
        Command((sort,)).flag("-z").flag("--stable").positional(records),
        env={"LC_ALL": "C"},
    )
    assert sorted_result.returncode == 0
    assert sorted_result.stdout == "a\0b\0日本語\0"

    already_sorted = tmp_path / "sorted.bin"
    already_sorted.write_bytes("a\0b\0".encode())
    check = run_command(
        Command((sort,)).flag("-z").flag("-C").positional(already_sorted),
        env={"LC_ALL": "C"},
    )
    assert (check.returncode, check.stdout) == (0, "")


def test_reproducible_tar_and_gzip_options(tmp_path):
    tar = available("tar")
    gzip = available("gzip")

    root = tmp_path / "root"
    root.mkdir()
    (root / "b.txt").write_text("same\n", encoding="utf-8")
    (root / "a 日本語.txt").write_text("same\n", encoding="utf-8")

    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    base = (
        Command((tar,))
        .option("--sort", "name", attached=True)
        .option("--mtime", "@0", attached=True)
        .option("--owner", "0", attached=True)
        .option("--group", "0", attached=True)
        .flag("--numeric-owner")
    )
    assert run_command(base.option("-cf", first).option("-C", root).positional(".")).returncode == 0

    os.utime(root / "a 日本語.txt", (1234567890, 1234567890))
    os.utime(root / "b.txt", (1700000000, 1700000000))
    assert run_command(base.option("-cf", second).option("-C", root).positional(".")).returncode == 0

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()

    one = tmp_path / "one.txt"
    two = tmp_path / "two.txt"
    one.write_text("compress me\n", encoding="utf-8")
    two.write_text("compress me\n", encoding="utf-8")
    os.utime(one, (1000000000, 1000000000))
    os.utime(two, (1800000000, 1800000000))
    assert run_command(Command((gzip, "-n", str(one)))).returncode == 0
    assert run_command(Command((gzip, "-n", str(two)))).returncode == 0
    assert (tmp_path / "one.txt.gz").read_bytes() == (tmp_path / "two.txt.gz").read_bytes()


def test_ripgrep_json_and_nul_filename_modes(tmp_path):
    rg = available("rg")
    root = tmp_path / "rg"
    root.mkdir()
    target = root / "-match 日本語\nfile.txt"
    target.write_text("needle here\n", encoding="utf-8")

    structured = run_command(Command((rg, "--json", "needle", str(root))))
    assert structured.returncode == 0, structured.stderr
    messages = [json.loads(line) for line in structured.stdout.splitlines()]
    kinds = {message["type"] for message in messages}
    assert {"begin", "match", "end", "summary"} <= kinds

    nul_names = run_command(
        Command((rg, "-0", "-l")).passthrough(["needle", str(root)], separator=True)
    )
    assert nul_names.returncode == 0
    assert nul_names.stdout == str(target) + "\0"
