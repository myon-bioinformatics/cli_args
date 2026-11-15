"""Host-real CLI evidence: real git / curl / ls / pytest / node / gh runs on this machine, plus construct-only argv shapes.

Missing tools skip with a reason (see ``conftest.available``); the container-real twin is ``test_container_commands.py``.
"""
import json, os, sys
from urllib.parse import quote

from cli_args import Command, pytest_command, run_command
from conftest import available, local_server


# ---- argv transport per tool ----
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


def test_pytest_real_keyword_and_explicit_separator(tmp_path):
    target = tmp_path / "selected_test.py"
    target.write_text(
        "def test_chosen(): assert True\n"
        "def test_other(): assert False\n",
        encoding="utf-8",
    )
    command = (
        Command((sys.executable, "-m", "pytest"))
        .flag("-q")
        .option("--tb", "short", attached=True)
        .flag("-ra")
        .option("--override-ini", "addopts=")
        .option("-k", "chosen or absent")
        .passthrough([target.name], separator=True)
    )
    result = run_command(command, cwd=tmp_path, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 deselected" in result.stdout


def test_git_real_repository(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    normal = "日本 語.txt"
    leading = "-leading 日本語.txt"
    (tmp_path / normal).write_text("hello", encoding="utf-8")
    (tmp_path / leading).write_text("leading", encoding="utf-8")
    assert run_command(git.positional("add").passthrough([normal, leading], separator=True)).returncode == 0
    result = run_command(git.positional("ls-files", "-z"))
    assert result.returncode == 0
    assert result.stdout.split("\0")[:-1] == [leading, normal]
    assert run_command(git.positional("not-a-git-command")).returncode != 0


def test_git_machine_readable_porcelain_refs_and_batch_shapes(tmp_path):
    git = Command((available("git"),)).option("-C", tmp_path)
    assert run_command(git.positional("init", "--quiet")).returncode == 0
    assert run_command(git.positional("config", "user.name", "CLI Test")).returncode == 0
    assert run_command(git.positional("config", "user.email", "cli@example.invalid")).returncode == 0

    tracked = "tracked 日本語.txt"
    untracked = "untracked space 日本語.txt"
    (tmp_path / tracked).write_text("one\n", encoding="utf-8")
    assert run_command(git.positional("add").passthrough([tracked], separator=True)).returncode == 0
    assert run_command(git.positional("commit", "--quiet", "-m", "initial")).returncode == 0
    (tmp_path / tracked).write_text("two\n", encoding="utf-8")
    (tmp_path / untracked).write_text("new\n", encoding="utf-8")

    status = run_command(
        git.positional("status")
        .option("--porcelain", "v2", attached=True)
        .flag("-z")
        .flag("--branch")
    )
    assert status.returncode == 0
    assert "# branch.head " in status.stdout
    assert tracked in status.stdout and untracked in status.stdout
    assert "\0" in status.stdout

    assert run_command(git.positional("branch", "topic/日本語")).returncode == 0
    refs = run_command(
        git.positional("for-each-ref")
        .option("--format", "%(refname:short)%00%(objectname:short)%00", attached=True)
        .option("--sort", "refname", attached=True)
        .positional("refs/heads")
    )
    assert refs.returncode == 0
    assert "topic/日本語\0" in refs.stdout
    assert refs.stdout.count("\0") >= 4

    # The NUL pathspec now uses real binary stdin, protecting spaces and
    # leading-hyphen filenames without command-string parsing.
    tricky = "-NUL 日本語 file.txt"
    (tmp_path / tricky).write_text("payload", encoding="utf-8")
    pathspec = (
        git.positional("add")
        .option("--pathspec-from-file", "-", attached=True)
        .flag("--pathspec-file-nul")
    )
    assert pathspec.argv[-3:] == (
        "add", "--pathspec-from-file=-", "--pathspec-file-nul",
    )
    staged = run_command(pathspec, stdin=tricky.encode("utf-8") + b"\0")
    assert staged.returncode == 0, staged.stderr
    index = run_command(git.positional("ls-files", "-z"))
    assert tricky in index.stdout.split("\0")
    cat_file = git.positional("cat-file").flag("--batch-command").flag("--buffer").flag("-Z")
    assert cat_file.argv[-4:] == ("cat-file", "--batch-command", "--buffer", "-Z")

    # A finite batch-command transaction is now real, including a NUL byte
    # in the blob body. This is not evidence of a persistent interactive session.
    payload = b"hello\0world"
    stored = run_command(git.positional("hash-object", "-w", "--stdin"), stdin=payload)
    assert stored.returncode == 0, stored.stderr
    oid = stored.stdout.strip()
    assert len(oid) in (40, 64)
    batch = run_command(cat_file, stdin=b"contents " + oid.encode("ascii") + b"\0flush\0")
    assert batch.returncode == 0, batch.stderr
    assert batch.stdout == oid + " blob 11\0hello\0world\0"


def test_ls_real_separator_space_unicode_and_leading_hyphen(tmp_path):
    name = "-leading 日本語 file.txt"
    (tmp_path / name).write_text("ok\n", encoding="utf-8")
    command = (Command((available("ls"),)).flag("-1").flag("--color=never")
               .passthrough([name], separator=True))
    result = run_command(command, cwd=tmp_path)
    assert (result.returncode, result.stdout) == (0, name + "\n")


def test_curl_real_local_http_and_failure(tmp_path):
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
    source = "日本 語.html"
    (tmp_path / source).write_text("<h1>日本語</h1>", encoding="utf-8")
    output = tmp_path / "saved 日本語 page.html"
    with local_server(tmp_path) as url:
        result = run_command(
            curl.repeated("-H", ["Accept: text/html", "X-Test: value with spaces"])
            .option("--output", output)
            .positional(url + "/" + quote(source)),
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == "<h1>日本語</h1>"
        assert run_command(curl.positional(url + "/missing"), timeout=10).returncode == 22


def test_curl_real_fail_with_body_fail_early_and_write_out(tmp_path):
    curl = (
        Command((available("curl"),))
        .positional("--disable")
        .flag("--silent")
        .flag("--show-error")
        .flag("--fail-with-body")
        .flag("--fail-early")
        .option("--noproxy", "*")
        .option("--max-time", "5")
        .option("--write-out", "%{http_code}\\n")
    )
    (tmp_path / "second.txt").write_text("SECOND-SHOULD-NOT-RUN", encoding="utf-8")
    with local_server(tmp_path) as url:
        result = run_command(
            curl.positional(url + "/missing", url + "/second.txt"),
            timeout=10,
        )
    assert result.returncode == 22
    assert result.stdout.endswith("404\n")
    assert "SECOND-SHOULD-NOT-RUN" not in result.stdout


def test_gh_mock_transport_records_argv(tmp_path):
    # Portable subprocess stub; this does NOT claim live/authenticated gh coverage.
    stub = tmp_path / "gh_stub.py"
    stub.write_text("import json,sys\nprint(json.dumps({'argv':sys.argv[1:]}))\n")
    result = run_command(Command((sys.executable, "-S", str(stub)))
        .positional("issue", "list").option("--repo", "owner/repo")
        .option("--json", "number,title").option("--state", "open"))
    assert json.loads(result.stdout)["argv"] == ["issue", "list", "--repo", "owner/repo",
                                               "--json", "number,title", "--state", "open"]


def test_node_and_npm_real_argv_transport_and_playwright_shape(tmp_path):
    node = available("node")
    npm = available("npm")
    probe = tmp_path / "argv_probe.js"
    probe.write_text(
        "console.log(JSON.stringify(process.argv.slice(2)))\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"probe": "node argv_probe.js"}}),
        encoding="utf-8",
    )
    values = ["--project=chromium", "--grep", "value with spaces", "-leading", "日本語"]
    result = run_command(
        Command((npm, "run", "--silent", "probe", "--")).passthrough(values),
        cwd=tmp_path,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == values

    # Playwright itself is construct-only here. browser-test-kit owns real
    # Playwright/browser evidence; this fixes the argv shape used by wrappers.
    playwright = (
        Command((node, "node_modules/@playwright/test/cli.js"))
        .positional("test")
        .option("--project", "chromium", attached=True)
        .option("--project", "webkit", attached=True)
        .option("--grep", "value with spaces")
        .positional("tests/smoke.spec.ts")
    )
    assert playwright.argv == (
        node,
        "node_modules/@playwright/test/cli.js",
        "test",
        "--project=chromium",
        "--project=webkit",
        "--grep",
        "value with spaces",
        "tests/smoke.spec.ts",
    )


def test_gh_real_binary_and_api_shape():
    gh = available("gh")
    version = run_command(Command((gh, "--version")), timeout=10)
    assert version.returncode == 0
    assert "gh version" in version.stdout.lower()

    # Authenticated/network execution is deliberately not claimed here.
    api = (
        Command((gh,))
        .positional("api")
        .option("--hostname", "github.com")
        .option("--method", "GET")
        .repeated("-H", [
            "Accept: application/vnd.github+json",
            "X-GitHub-Api-Version: 2022-11-28",
        ])
        .option("--jq", ".sha")
        .positional("repos/owner/repo/contents/path with space")
    )
    assert api.argv == (
        gh,
        "api",
        "--hostname", "github.com",
        "--method", "GET",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        "--jq", ".sha",
        "repos/owner/repo/contents/path with space",
    )

    paginated = (
        Command((gh,))
        .positional("api")
        .option("--hostname", "github.com")
        .option("--method", "GET")
        .flag("--paginate")
        .flag("--slurp")
        .option("--cache", "1h")
        .repeated("-F", ["per_page=100", "active=true"])
        .repeated("-f", ["q=repo:{owner}/{repo} is:open", "note=value with spaces"])
        .positional("search/issues")
    )
    assert paginated.argv == (
        gh, "api",
        "--hostname", "github.com",
        "--method", "GET",
        "--paginate", "--slurp",
        "--cache", "1h",
        "-F", "per_page=100",
        "-F", "active=true",
        "-f", "q=repo:{owner}/{repo} is:open",
        "-f", "note=value with spaces",
        "search/issues",
    )


def test_construct_only_flutter_and_dart_argv():
    flutter = (
        Command(("flutter",))
        .positional("build", "web")
        .option("-t", "lib/main.dart")
        .option("--base-href", "/flutter_navigation_basic/")
        .option("--dart-define", "E2E=true", attached=True)
    )
    assert flutter.argv == (
        "flutter", "build", "web",
        "-t", "lib/main.dart",
        "--base-href", "/flutter_navigation_basic/",
        "--dart-define=E2E=true",
    )

    dart = (
        Command(("dart",))
        .positional("run", "tool/dev.dart", "bundle")
        .option("--output", "build/my diagnostics.zip")
    )
    assert dart.argv == (
        "dart", "run", "tool/dev.dart", "bundle",
        "--output", "build/my diagnostics.zip",
    )


def test_construct_only_uv_nested_python_pytest_argv():
    command = (
        Command(("uv",))
        .positional("run")
        .flag("--no-project")
        .option("--python", "3.12")
        .repeated("--with", ["pytest", "pytest-cov"])
        .positional("python", "-m", "pytest", "-q", "tests")
    )
    assert command.argv == (
        "uv", "run", "--no-project",
        "--python", "3.12",
        "--with", "pytest",
        "--with", "pytest-cov",
        "python", "-m", "pytest", "-q", "tests",
    )


# ---- exit-code and config contracts ----
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
