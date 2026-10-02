from pathlib import Path
import hashlib
import json
import os
import shutil

import pytest

from cli_args import Command, run_command


if os.environ.get("CLI_ARGS_CONTAINER_REAL") != "1":
    pytest.skip(
        "container pattern suite runs only inside the Docker integration boundary",
        allow_module_level=True,
    )


def available(name):
    executable = shutil.which(name)
    if executable is None:
        pytest.fail(name + " is not installed in the integration image")
    return executable


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
    names = ["normal.txt", "space 日本語.txt", "-leading.txt"]
    for name in names:
        (tree / name).write_text(name, encoding="utf-8")

    found = run_command(Command((find, str(tree), "-type", "f", "-print0")))
    assert found.returncode == 0
    assert set(found.stdout.split("\0")[:-1]) == {str(tree / name) for name in names}

    args_file = tmp_path / "args.bin"
    values = ["one", "two words", "-leading", "日本語"]
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
    target = root / "-match 日本語 file.txt"
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
