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



def test_git_untracked_inventory_and_optional_lock_boundary(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("tracked", encoding="utf-8")
    assert run_command(git.positional("add", "tracked.txt")).returncode == 0
    (tmp_path / "untracked").mkdir()
    (tmp_path / "untracked" / "space 日本語.txt").write_text("new", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "secret.txt").write_text("ignored", encoding="utf-8")

    files = run_command(git.positional(
        "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    assert files.returncode == 0
    assert set(files.stdout.split("\0")[:-1]) == {
        "tracked.txt", ".gitignore", "untracked/space 日本語.txt",
    }
    # An existing index lock must not block this read-only status observation.
    index_before = (tmp_path / ".git" / "index").read_bytes()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_bytes(b"do not replace")
    status = run_command(git.flag("--no-optional-locks").positional(
        "status", "--porcelain=v2", "-z", "--untracked-files=all"))
    assert status.returncode == 0, status.stderr
    assert "? untracked/space 日本語.txt\0" in status.stdout
    assert "ignored/secret.txt" not in status.stdout
    assert lock.read_bytes() == b"do not replace"
    assert (tmp_path / ".git" / "index").read_bytes() == index_before


def test_pytest_override_ini_clears_inherited_addopts(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = --maxfail=1\n", encoding="utf-8")
    (tmp_path / "test_two.py").write_text(
        "def test_one(): assert False\ndef test_two(): assert False\n", encoding="utf-8")
    common = Command((sys.executable, "-m", "pytest", "-q", "--tb=no"))
    stopped = run_command(common.positional("test_two.py"), cwd=tmp_path, timeout=30)
    assert stopped.returncode == 1
    assert "1 failed" in stopped.stdout
    full = run_command(common.option("--override-ini", "addopts=").positional("test_two.py"),
                       cwd=tmp_path, timeout=30)
    assert full.returncode == 1
    assert "2 failed" in full.stdout


def test_curl_disables_default_config_and_bypasses_inherited_proxy(tmp_path):
    import os
    from test_commands import local_server

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".curlrc").write_text('header = "X-Default: injected"\n', encoding="utf-8")
    (tmp_path / "payload.txt").write_text("local payload", encoding="utf-8")
    env = {
        **os.environ,
        "CURL_HOME": str(config_dir),
        "http_proxy": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "no_proxy": "",
        "NO_PROXY": "",
    }
    curl = Command((available("curl"),))
    # --disable must be curl's first argument to suppress its default config.
    trace = tmp_path / "trace.txt"
    with local_server(tmp_path) as url:
        control_trace = tmp_path / "control-trace.txt"
        control = run_command(
            curl.positional("--silent", "--show-error")
            .option("--noproxy", "*").option("--max-time", "5")
            .option("--trace-ascii", control_trace).positional(url + "/payload.txt"),
            env=env, timeout=10,
        )
        assert control.returncode == 0
        assert "X-Default: injected" in control_trace.read_text(encoding="utf-8")
        result = run_command(
            curl.positional("--disable", "--silent", "--show-error")
            .option("--noproxy", "*").option("--max-time", "5")
            .option("--trace-ascii", trace).positional(url + "/payload.txt"),
            env=env, timeout=10,
        )
    assert (result.returncode, result.stdout) == (0, "local payload")
    assert "X-Default: injected" not in trace.read_text(encoding="utf-8")
