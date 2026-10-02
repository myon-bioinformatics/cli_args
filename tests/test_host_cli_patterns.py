from pathlib import Path
import shutil
import sys

import pytest

from cli_args import Command, run_command


def available(name):
    executable = shutil.which(name)
    if executable is None:
        pytest.skip(name + " is not installed")
    return executable


def test_git_quiet_diff_and_error_unmatch_exit_contracts(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    assert run_command(git.positional("config", "user.name", "CLI Test")).returncode == 0
    assert run_command(git.positional("config", "user.email", "cli@example.invalid")).returncode == 0

    tracked = "tracked 日本語.txt"
    (tmp_path / tracked).write_text("one\n", encoding="utf-8")
    assert run_command(git.positional("add").passthrough([tracked], separator=True)).returncode == 0
    assert run_command(git.positional("commit", "--quiet", "-m", "initial")).returncode == 0

    quiet = (
        git.positional("diff")
        .flag("--quiet")
        .flag("--no-ext-diff")
        .flag("--no-textconv")
        .passthrough([tracked], separator=True)
    )
    clean = run_command(quiet)
    assert (clean.returncode, clean.stdout, clean.stderr) == (0, "", "")

    (tmp_path / tracked).write_text("two\n", encoding="utf-8")
    changed = run_command(quiet)
    assert (changed.returncode, changed.stdout, changed.stderr) == (1, "", "")

    tracked_check = run_command(
        git.positional("ls-files")
        .flag("--error-unmatch")
        .passthrough([tracked], separator=True)
    )
    assert tracked_check.returncode == 0

    missing_check = run_command(
        git.positional("ls-files")
        .flag("--error-unmatch")
        .passthrough(["missing.txt"], separator=True)
    )
    assert missing_check.returncode == 1


def test_pytest_collect_only_and_maxfail_are_cli_contracts(tmp_path):
    target = tmp_path / "test_contract.py"
    sentinel = tmp_path / "should-not-run"
    target.write_text(
        "from pathlib import Path\n"
        "def test_first(): assert False\n"
        "def test_second(): Path('should-not-run').write_text('ran')\n",
        encoding="utf-8",
    )
    common = Command((sys.executable, "-m", "pytest")).option(
        "--override-ini", "addopts="
    )

    collected = run_command(
        common.flag("--collect-only").flag("-q").positional(target.name),
        cwd=tmp_path,
        timeout=30,
    )
    assert collected.returncode == 0
    assert "test_contract.py::test_first" in collected.stdout
    assert "test_contract.py::test_second" in collected.stdout
    assert not sentinel.exists()

    stopped = run_command(
        common.flag("-q").option("--maxfail", "1", attached=True).positional(target.name),
        cwd=tmp_path,
        timeout=30,
    )
    assert stopped.returncode == 1
    assert not sentinel.exists()
    assert "stopping after 1 failures" in stopped.stdout
