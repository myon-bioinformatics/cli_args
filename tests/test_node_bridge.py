import json
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

import cli_args
from cli_args import (NodeNotFoundError, add_node_arguments, build_env, is_node_target,
                      make_parser, node_command, node_or_command, resolve_node, run_node)


def reset_node_probe_cache():
    cli_args._NODE_PROBE_CACHE.clear()


@pytest.fixture(autouse=True)
def _clear_node_probe_cache():
    reset_node_probe_cache()
    yield
    reset_node_probe_cache()


ECHO_CJS = textwrap.dedent(
    """\
    const payload = { argv: process.argv.slice(2), exitCode: Number(process.env.EXIT_CODE || 0) };
    console.log(JSON.stringify(payload));
    process.exit(payload.exitCode);
    """
)

ECHO_MJS = textwrap.dedent(
    """\
    const payload = { argv: process.argv.slice(2), exitCode: Number(process.env.EXIT_CODE || 0) };
    console.log(JSON.stringify(payload));
    process.exit(payload.exitCode);
    """
)


def write_echo_scripts(tmp_path: Path) -> tuple[Path, Path]:
    cjs = tmp_path / "echo_argv.cjs"
    mjs = tmp_path / "echo_argv.mjs"
    cjs.write_text(ECHO_CJS, encoding="utf-8")
    mjs.write_text(ECHO_MJS, encoding="utf-8")
    return cjs, mjs


def test_is_node_target_extensions():
    assert is_node_target("probe.js")
    assert is_node_target(Path("x.CJS"))
    assert is_node_target("dir/run.mjs")
    assert not is_node_target("node")
    assert not is_node_target("readme.txt")


def test_node_command_argv_order_and_passthrough(tmp_path):
    node_bin = tmp_path / "node-bin"
    node_bin.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n", encoding="utf-8")
    node_bin.chmod(node_bin.stat().st_mode | stat.S_IXUSR)
    command = node_command(
        "script.mjs",
        "--",
        "-leading",
        "",
        "日本 語",
        node=str(node_bin),
        node_flags=("--import", "x"),
    )
    assert command.argv == (
        str(node_bin), "--import", "x", "script.mjs", "--", "-leading", "", "日本 語",
    )


def test_node_or_command_opt_in():
    plain = node_or_command(("git", "status", "--short"))
    assert plain.argv == ("git", "status", "--short")
    wrapped = node_or_command(("app.cjs", "--flag", "value"))
    assert wrapped.argv[:2] == (resolve_node(), "app.cjs")
    assert wrapped.argv[2:] == ("--flag", "value")


def test_add_node_arguments_and_parser_integration(tmp_path):
    node_bin = tmp_path / "node-bin"
    node_bin.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n", encoding="utf-8")
    node_bin.chmod(node_bin.stat().st_mode | stat.S_IXUSR)
    parser = make_parser()
    add_node_arguments(parser)
    args = parser.parse_args(["--node", str(node_bin), "--node-flag=--trace-warnings",
                              "--node-flag=--no-warnings"])
    command = node_or_command(("tool.js", "run"), node=args.node, node_flags=args.node_flags)
    assert command.argv == (
        str(node_bin), "--trace-warnings", "--no-warnings", "tool.js", "run",
    )


def test_resolve_node_explicit_missing_no_fallback(tmp_path, monkeypatch):
    missing = tmp_path / "missing-node"
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    monkeypatch.delenv("NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match="cli_args: node"):
        resolve_node(missing)


def test_resolve_node_cli_args_node_is_explicit(tmp_path, monkeypatch):
    missing = tmp_path / "env-node"
    monkeypatch.setenv("CLI_ARGS_NODE", str(missing))
    monkeypatch.setenv("NODE", shutil_which_node())
    with pytest.raises(NodeNotFoundError, match="cli_args: node"):
        resolve_node()


def test_resolve_node_rejects_cmd_wrapper(tmp_path, monkeypatch):
    wrapper = tmp_path / "node.cmd"
    wrapper.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match=r"\.cmd"):
        resolve_node(wrapper)


def test_resolve_node_rejects_old_version(tmp_path, monkeypatch):
    fake = tmp_path / "fake-node"
    fake.write_text("#!/bin/sh\nprintf 'v16.9.0\\n'\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match="18"):
        resolve_node(fake)


def test_resolve_node_probe_timeout(tmp_path, monkeypatch):
    slow = tmp_path / "slow-node"
    slow.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    slow.chmod(slow.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match="timed out"):
        resolve_node(slow)


def test_resolve_node_discovery_order(monkeypatch, tmp_path):
    primary = tmp_path / "primary-node"
    primary.write_text("#!/bin/sh\nprintf 'v20.0.0\\n'\n", encoding="utf-8")
    primary.chmod(primary.stat().st_mode | stat.S_IXUSR)
    fallback = shutil_which_node()
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    monkeypatch.setenv("NODE", str(primary))
    assert resolve_node() == str(primary)
    reset_node_probe_cache()
    monkeypatch.delenv("NODE", raising=False)
    assert resolve_node() == fallback


def test_node_not_found_is_file_not_found():
    assert issubclass(NodeNotFoundError, FileNotFoundError)


def test_run_node_real_cjs_and_mjs(tmp_path):
    cjs, mjs = write_echo_scripts(tmp_path)
    spaced = tmp_path / "space 日本語.cjs"
    spaced.write_text(ECHO_CJS, encoding="utf-8")
    for target, values in (
        (cjs, ["--", "-opt", "", "日本 語"]),
        (mjs, ["--attached", "-x"]),
        (spaced, ["tail"]),
    ):
        result = run_node(target, *values, timeout=30)
        assert result.returncode == 0, result.stderr
        assert result.executed
        payload = json.loads(result.stdout)
        assert payload["argv"] == list(values)


def test_run_node_exit_code_and_timeout(tmp_path):
    cjs, _ = write_echo_scripts(tmp_path)
    failed = run_node(cjs, env=build_env(["EXIT_CODE=7"], inherit=True), timeout=30)
    assert failed.returncode == 7
    hang = tmp_path / "hang.cjs"
    hang.write_text("setInterval(() => {}, 1_000_000);", encoding="utf-8")
    timed = run_node(hang, timeout=0.5)
    assert timed.timed_out
    assert timed.returncode is None


def shutil_which_node() -> str:
    import shutil
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not installed")
    return path


def test_run_node_dry_run_matches_run_command(tmp_path):
    cjs, _ = write_echo_scripts(tmp_path)
    result = run_node(cjs, "one", dry_run=True)
    assert result.executed is False
    assert result.returncode is None
    assert result.argv[1:].index("one") > 0


def test_node_command_nul_rejected():
    with pytest.raises(ValueError, match="NUL"):
        node_command("ok.js", "bad\0")


def test_resolve_node_probe_runs_once(monkeypatch, tmp_path):
    counter = tmp_path / "count-node"
    counter.write_text(
        "#!/bin/sh\nprintf 'v22.0.0\\n'\n",
        encoding="utf-8",
    )
    counter.chmod(counter.stat().st_mode | stat.S_IXUSR)
    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(argv, 0, b"v22.0.0\n", b"")

    monkeypatch.setattr(cli_args.subprocess, "run", fake_run)
    assert resolve_node(counter) == str(counter)
    assert resolve_node(counter) == str(counter)
    assert calls["n"] == 1
