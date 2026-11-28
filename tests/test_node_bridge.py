import importlib.util, json, os, shutil, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path

import pytest

import cli_args
from cli_args import (NodeNotFoundError, add_node_arguments, build_env, is_node_target,
                      make_parser, node_command, node_or_command, resolve_node, run_node)


def load_vendored(name, relpath):
    """Load a vendored file by path under a repo-unique name (cli_args README: Loading a vendored copy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relpath)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


fleet = load_vendored("cli_args_fleet_check", "vendor/fleet_check.py")


def reset_node_probe_cache():
    cli_args._NODE_PROBE_CACHE.clear()


@pytest.fixture(autouse=True)
def _clear_node_probe_cache():
    reset_node_probe_cache()
    yield
    reset_node_probe_cache()


def install_probe_stub(monkeypatch):
    """Simulate ``node --version`` probes without platform-specific fake executables."""
    real_run = subprocess.run
    table: dict[str, dict[str, object]] = {}

    def fake_run(argv, **kwargs):
        if len(argv) >= 2 and argv[1] == "--version":
            entry = table.get(argv[0])
            if entry is not None:
                if entry["hang"]:
                    raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 5))
                return subprocess.CompletedProcess(
                    argv, int(entry["returncode"]), entry["stdout"], b"",
                )
        return real_run(argv, **kwargs)

    monkeypatch.setattr(cli_args.subprocess, "run", fake_run)

    def register(path, *, version="v26.0.0", returncode=0, hang=False):
        key = str(path)
        table[key] = {
            "stdout": f"{version}\n".encode(),
            "returncode": returncode,
            "hang": hang,
        }
        Path(path).write_text("stub", encoding="utf-8")
        return key

    return register


ECHO_JS = textwrap.dedent(  # same body as .cjs and .mjs
    """\
    const payload = { argv: process.argv.slice(2), exitCode: Number(process.env.EXIT_CODE || 0) };
    console.log(JSON.stringify(payload));
    process.exit(payload.exitCode);
    """
)


def write_echo_scripts(tmp_path: Path) -> tuple[Path, Path]:
    cjs = tmp_path / "echo_argv.cjs"
    mjs = tmp_path / "echo_argv.mjs"
    cjs.write_text(ECHO_JS, encoding="utf-8")
    mjs.write_text(ECHO_JS, encoding="utf-8")
    return cjs, mjs


def test_is_node_target_extensions():
    assert is_node_target("probe.js")
    assert is_node_target(Path("x.CJS"))
    assert is_node_target("dir/run.mjs")
    assert not is_node_target("node")
    assert not is_node_target("readme.txt")


def test_node_command_argv_order_and_passthrough(tmp_path, monkeypatch):
    register = install_probe_stub(monkeypatch)
    node_bin = register(tmp_path / "node-bin")
    command = node_command(
        "script.mjs",
        "--",
        "-leading",
        "",
        "日本 語",
        node=node_bin,
        node_flags=("--import", "x"),
    )
    assert command.argv == (
        node_bin, "--import", "x", "script.mjs", "--", "-leading", "", "日本 語",
    )


def test_node_or_command_empty_argv_matches_command():
    with pytest.raises(ValueError, match="non-empty executable"):
        node_or_command([])


def test_node_or_command_opt_in():
    plain = node_or_command(("git", "status", "--short"))
    assert plain.argv == ("git", "status", "--short")
    wrapped = node_or_command(("app.cjs", "--flag", "value"), node=shutil_which_node())
    assert wrapped.argv[:2] == (shutil_which_node(), "app.cjs")
    assert wrapped.argv[2:] == ("--flag", "value")


def test_add_node_arguments_and_parser_integration(tmp_path, monkeypatch):
    register = install_probe_stub(monkeypatch)
    node_bin = register(tmp_path / "node-bin")
    parser = make_parser()
    add_node_arguments(parser)
    args = parser.parse_args(["--node", node_bin, "--node-flag=--trace-warnings",
                              "--node-flag=--no-warnings"])
    command = node_or_command(("tool.js", "run"), node=args.node, node_flags=args.node_flags)
    assert command.argv == (
        node_bin, "--trace-warnings", "--no-warnings", "tool.js", "run",
    )


def test_resolve_node_explicit_missing_no_fallback(tmp_path, monkeypatch):
    missing = tmp_path / "missing-node"
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    monkeypatch.delenv("NODE", raising=False)
    monkeypatch.setattr(cli_args.shutil, "which", lambda name: None)
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
    register = install_probe_stub(monkeypatch)
    fake = register(tmp_path / "fake-node", version="v22.14.0")
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match="26"):
        resolve_node(fake)
    reset_node_probe_cache()
    accepted = register(tmp_path / "node-26", version="v26.0.0")
    assert resolve_node(accepted) == accepted


def test_resolve_node_probe_timeout(tmp_path, monkeypatch):
    register = install_probe_stub(monkeypatch)
    slow = register(tmp_path / "slow-node", hang=True)
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    with pytest.raises(NodeNotFoundError, match="timed out"):
        resolve_node(slow)


def test_resolve_node_discovery_order(monkeypatch, tmp_path):
    register = install_probe_stub(monkeypatch)
    primary = register(tmp_path / "primary-node", version="v26.0.0")
    fallback = shutil_which_node()
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    monkeypatch.setenv("NODE", primary)
    monkeypatch.setattr(cli_args.shutil, "which", lambda name: None)
    assert resolve_node() == primary
    reset_node_probe_cache()
    monkeypatch.delenv("NODE", raising=False)
    monkeypatch.setattr(cli_args.shutil, "which", lambda name: fallback if name == "node" else None)
    assert os.path.normcase(resolve_node()) == os.path.normcase(fallback)


def test_node_not_found_is_file_not_found():
    assert issubclass(NodeNotFoundError, FileNotFoundError)


def test_run_node_real_cjs_and_mjs(tmp_path):
    cjs, mjs = write_echo_scripts(tmp_path)
    spaced = tmp_path / "space 日本語.cjs"
    spaced.write_text(ECHO_JS, encoding="utf-8")
    for target, values in (
        (cjs, ["--", "-opt", "", "日本 語"]),
        (mjs, ["--attached", "-x"]),
        (spaced, ["tail"]),
    ):
        result = run_node(target, *values, node=shutil_which_node(), timeout=30)
        assert result.returncode == 0, result.stderr
        assert result.executed
        payload = json.loads(result.stdout)
        assert payload["argv"] == list(values)


def test_run_node_exit_code_and_timeout(tmp_path):
    cjs, _ = write_echo_scripts(tmp_path)
    node = shutil_which_node()
    failed = run_node(cjs, node=node, env=build_env(["EXIT_CODE=7"], inherit=True), timeout=30)
    assert failed.returncode == 7
    hang = tmp_path / "hang.cjs"
    hang.write_text("setInterval(() => {}, 1_000_000);", encoding="utf-8")
    timed = run_node(hang, node=node, timeout=0.5)
    assert timed.timed_out
    assert timed.returncode is None


def shutil_which_node() -> str:
    candidates: list[str] = []
    nvm_root = Path.home() / ".nvm/versions/node"
    if nvm_root.is_dir():
        for entry in sorted(nvm_root.glob("v26*/bin/node"), reverse=True):
            candidates.append(str(entry))
    discovered = shutil.which("node")
    if discovered:
        candidates.append(discovered)
    for path in candidates:
        reset_node_probe_cache()
        try:
            return resolve_node(path)
        except NodeNotFoundError:
            continue
    pytest.skip("Node 26+ is required for host-real node bridge tests")


def test_run_node_rejects_non_bool_dry_run_without_executing(tmp_path):
    marker = tmp_path / "ran.txt"
    script = tmp_path / "touch.cjs"
    script.write_text(
        "require('node:fs').writeFileSync(process.argv[2], 'ran\\n');\n",
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="dry_run must be bool"):
        run_node(script, str(marker), dry_run="yes")
    assert not marker.exists()


def test_run_node_dry_run_matches_run_command(tmp_path):
    cjs, _ = write_echo_scripts(tmp_path)
    result = run_node(cjs, "one", dry_run=True)
    assert result.executed is False
    assert result.returncode is None
    assert result.argv[1:].index("one") > 0


def test_run_node_dry_run_skips_probe_without_node(monkeypatch, tmp_path):
    cjs, _ = write_echo_scripts(tmp_path)
    monkeypatch.delenv("CLI_ARGS_NODE", raising=False)
    monkeypatch.delenv("NODE", raising=False)
    monkeypatch.setattr(cli_args.shutil, "which", lambda name: None)
    def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError("subprocess must not run during dry_run")

    monkeypatch.setattr(cli_args.subprocess, "run", forbid_subprocess)

    result = run_node(cjs, "tail", dry_run=True)
    assert result.executed is False
    assert result.argv == ("node", str(cjs), "tail")


def test_node_command_nul_rejected(tmp_path, monkeypatch):
    register = install_probe_stub(monkeypatch)
    node_bin = register(tmp_path / "node-bin")
    with pytest.raises(ValueError, match="NUL"):
        node_command("ok.js", "bad\0", node=node_bin, probe=False)


def test_resolve_node_probe_runs_once(monkeypatch, tmp_path):
    register = install_probe_stub(monkeypatch)
    counter = register(tmp_path / "count-node")
    stub_run = cli_args.subprocess.run
    calls = {"n": 0}

    def counting_run(argv, **kwargs):
        if len(argv) >= 2 and argv[1] == "--version" and argv[0] == counter:
            calls["n"] += 1
        return stub_run(argv, **kwargs)

    monkeypatch.setattr(cli_args.subprocess, "run", counting_run)
    assert resolve_node(counter) == counter
    assert resolve_node(counter) == counter
    assert calls["n"] == 1


def test_package_json_declares_node_26_floor():
    root = Path(__file__).resolve().parents[1]
    engines = json.loads((root / "package.json").read_text(encoding="utf-8"))["engines"]
    assert engines["node"] == ">=26"


def test_node_min_major_is_26():
    assert cli_args._NODE_MIN_MAJOR == 26


class LauncherRegressionTests(unittest.TestCase):
    """Real Node/Python regressions for the adopted shared launcher."""

    def setUp(self):
        self.node = shutil_which_node()
        if self.node is None:
            self.skipTest("Node 26+ is required for launcher regressions")
        self.root = Path(__file__).resolve().parents[1]
        self.tool = "cli_args"
        self.env = dict(os.environ)
        self.env["CLI_ARGS_PYTHON"] = sys.executable
        self.env.pop("PY_LAUNCH_ERROR_FORMAT", None)

    def test_vendored_launcher_keeps_its_contract(self):
        # Exit 2 on a missing interpreter, -S during discovery, resolvePython noSite/isolated, argv/stdin/exit
        # passthrough and (POSIX) repeated signal forwarding: the parent's shared check, not a local copy.
        if fleet.node(ci_jobs=None) is None:  # no CI job may skip this
            self.skipTest("Node 26+ is required for launcher regressions (set NODE)")
        fleet.launcher_contract(self.root, "CLI_ARGS_PYTHON")

    def test_entry_no_site_also_protects_interpreter_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "site-hook-ran"
            (root / "sitecustomize.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8",
            )
            result = subprocess.run(
                [
                    self.node,
                    str(self.root / "vendor" / "py_launch.cjs"),
                    "--env-var",
                    "CLI_ARGS_PYTHON",
                    "--",
                    str(self.root / f"{self.tool}.py"),
                    "--help",
                ],
                env=dict(self.env, PYTHONPATH=str(root)), capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "noSite must cover interpreter discovery too")
