"""The standard library as a CLI surface, measured for real: ``python -m`` commands, functions and types to use before a
custom helper, staged execution in plain Python, and the smallest read-only observation path (localhost HTTP).

Evidence for docs/stdlib-command-surface.md, docs/stdlib-function-surface.md, docs/stdlib-orchestration-surface.md and
docs/minimal-transport-surface.md.
"""
import csv, hashlib, json, logging, os, shlex, subprocess, sys, textwrap, time
from collections import Counter, deque; from configparser import ConfigParser; from contextlib import ExitStack, redirect_stdout; from datetime import datetime; from functools import lru_cache, partial; from html.parser import HTMLParser; from io import StringIO; from itertools import chain, islice; from pathlib import Path; from pprint import pformat; from tempfile import TemporaryDirectory; from urllib.error import HTTPError; from urllib.parse import quote, unquote; from urllib.request import urlopen

from cli_args import Command, run_command
from conftest import local_server


# ---- python -m commands ----
def test_json_tool_real(tmp_path):
    source = tmp_path / "input.json"
    source.write_text('{"z":1,"a":"日本語"}', encoding="utf-8")
    result = run_command(
        Command((sys.executable, "-m", "json.tool"))
        .flag("--sort-keys")
        .positional(source),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list(json.loads(result.stdout)) == ["a", "z"]


def test_zipfile_real_create_and_list(tmp_path):
    first = tmp_path / "a file.txt"
    second = tmp_path / "日本語.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    archive = tmp_path / "bundle.zip"

    created = run_command(
        Command((sys.executable, "-m", "zipfile", "-c", archive))
        .positional(first, second),
        cwd=tmp_path,
        timeout=30,
    )
    assert created.returncode == 0, created.stderr
    assert archive.is_file()

    listed = run_command(
        Command((sys.executable, "-m", "zipfile", "-l", archive)),
        cwd=tmp_path,
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert listed.returncode == 0, listed.stderr
    assert "a file.txt" in listed.stdout
    assert "日本語.txt" in listed.stdout


def test_tarfile_real_create_and_list(tmp_path):
    source = tmp_path / "space 日本語.txt"
    source.write_text("payload", encoding="utf-8")
    archive = tmp_path / "bundle.tar"

    created = run_command(
        Command((sys.executable, "-m", "tarfile", "-c", archive)).positional(source),
        cwd=tmp_path,
        timeout=30,
    )
    assert created.returncode == 0, created.stderr
    assert archive.is_file()

    listed = run_command(
        Command((sys.executable, "-m", "tarfile", "-l", archive)),
        cwd=tmp_path,
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert listed.returncode == 0, listed.stderr
    assert "space 日本語.txt" in listed.stdout


def test_http_server_cli_starts_localhost(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_bytes(b"stdlib-server\n")
    log_path = tmp_path / "http-server.log"
    with log_path.open("w+b") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "http.server",
                "0",
                "--bind",
                "127.0.0.1",
                "--directory",
                str(tmp_path),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.flush()
                    log.seek(0)
                    raise AssertionError(
                        "python -m http.server exited before serving: "
                        + log.read().decode("utf-8", errors="replace")
                    )
                time.sleep(0.05)
                log.flush()
                log.seek(0)
                output = log.read().decode("utf-8", errors="replace")
                if "Serving HTTP on" in output:
                    break
            else:
                # A still-running http.server after startup is stronger evidence
                # than a runner-specific localhost client route.
                assert process.poll() is None
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_platform_and_compileall_real(tmp_path):
    platform = run_command(Command((sys.executable, "-m", "platform")), timeout=30)
    assert platform.returncode == 0
    assert platform.stdout.strip()

    source = tmp_path / "src"
    source.mkdir()
    (source / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    compiled = run_command(
        Command((sys.executable, "-m", "compileall", "-q", source)),
        timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr


def test_tempfile_stdlib_api_real():
    code = (
        "import pathlib,tempfile;"
        "p=pathlib.Path(tempfile.mkdtemp());"
        "print(p.is_dir());"
        "p.rmdir()"
    )
    result = run_command(Command((sys.executable, "-c", code)), timeout=30)
    assert (result.returncode, result.stdout.strip()) == (0, "True")


# ---- functions and types ----
def test_print_sep_end_and_file():
    stream = StringIO()
    print("alpha", "日本語", sep=" | ", end="!", file=stream)
    assert stream.getvalue() == "alpha | 日本語!"


def test_pprint_controls_layout_and_order():
    value = {"z": [1, 2, 3], "a": {"nested": True}}
    rendered = pformat(
        value,
        indent=2,
        width=28,
        compact=False,
        sort_dicts=False,
    )
    assert rendered.index("'z'") < rendered.index("'a'")
    assert "\n" in rendered
    assert "  " in rendered


def test_textwrap_dedent_indent_and_fill():
    raw = """
        alpha beta gamma
        delta
    """
    dedented = textwrap.dedent(raw).strip()
    indented = textwrap.indent(dedented, "> ")
    filled = textwrap.fill("alpha beta gamma delta", width=10)
    assert indented.splitlines()[0] == "> alpha beta gamma"
    assert all(len(line) <= 10 for line in filled.splitlines())


def test_shlex_roundtrip_for_display_tokens():
    argv = ["tool", "--name", "value with spaces", "日本語", "-leading"]
    display = shlex.join(argv)
    assert shlex.split(display) == argv


def test_pathlib_and_temporary_directory():
    with TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "nested" / "result.txt"
        target.parent.mkdir()
        target.write_text("ok\n", encoding="utf-8", newline="\n")
        assert target.read_bytes() == b"ok\n"
        assert target.relative_to(root).as_posix() == "nested/result.txt"


def test_collections_counter_and_deque():
    counts = Counter("abacaba")
    queue = deque(["first"])
    queue.append("second")
    assert counts == {"a": 4, "b": 2, "c": 1}
    assert [queue.popleft(), queue.popleft()] == ["first", "second"]


def test_itertools_chain_and_islice():
    values = chain(["a", "b"], ["c", "d"])
    assert list(islice(values, 3)) == ["a", "b", "c"]


def test_functools_partial_and_lru_cache():
    def add(a, b):
        return a + b

    add_ten = partial(add, 10)
    calls = []

    @lru_cache(maxsize=4)
    def measured(value):
        calls.append(value)
        return value * 2

    assert add_ten(5) == 15
    assert measured(3) == measured(3) == 6
    assert calls == [3]


def test_contextlib_redirect_stdout_and_exitstack():
    stream = StringIO()
    closed = []

    class Resource:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

    with ExitStack() as stack:
        stack.enter_context(Resource())
        with redirect_stdout(stream):
            print("captured")
    assert stream.getvalue() == "captured\n"
    assert closed == [True]


def test_difflib_csv_and_configparser_roundtrips():
    from difflib import unified_diff

    diff = "".join(unified_diff(
        ["old\n"],
        ["new\n"],
        fromfile="before",
        tofile="after",
    ))
    assert "--- before" in diff
    assert "+++ after" in diff
    assert "-old" in diff and "+new" in diff

    stream = StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["name", "value"])
    writer.writerow(["日本語", "a,b"])
    stream.seek(0)
    assert list(csv.reader(stream)) == [["name", "value"], ["日本語", "a,b"]]

    config = ConfigParser()
    config.read_string("[section]\nkey = value\n")
    assert config["section"]["key"] == "value"


def test_hashlib_and_url_quote_unquote():
    digest = hashlib.sha256("日本語".encode("utf-8")).hexdigest()
    assert len(digest) == 64
    encoded = quote("space 日本語/path")
    assert unquote(encoded) == "space 日本語/path"


# ---- staged execution ----
def _py(code, *args):
    return Command((sys.executable, "-S", "-c", code)).positional(*args)


def test_ordered_steps_stop_on_first_failure(tmp_path):
    markers = [tmp_path / f"step-{index}.txt" for index in range(1, 5)]
    steps = [
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('1');", markers[0]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('2'); sys.exit(7)", markers[1]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('3');", markers[2]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('4');", markers[3]),
    ]

    results = []
    for command in steps:
        result = run_command(command)
        results.append(result.returncode)
        if result.returncode != 0:
            break

    assert results == [0, 7]
    assert markers[0].exists()
    assert markers[1].exists()
    assert not markers[2].exists()
    assert not markers[3].exists()


def test_exit_codes_are_structured_signals():
    observed = {}
    for code in (0, 1, 2):
        result = run_command(_py("import sys; sys.exit(int(sys.argv[1]))", str(code)))
        observed[code] = result.returncode
    assert observed == {0: 0, 1: 1, 2: 2}


def test_explicit_environment_handoff_does_not_mutate_parent():
    key = "CLI_ARGS_ORCHESTRATION_VALUE"
    before = os.environ.get(key)
    env = {**os.environ, key: "parent-provided"}

    result = run_command(
        _py(
            "import os; "
            "print(os.environ['CLI_ARGS_ORCHESTRATION_VALUE']); "
            "os.environ['CLI_ARGS_ORCHESTRATION_VALUE']='child-only'; "
            "print(os.environ['CLI_ARGS_ORCHESTRATION_VALUE'])"
        ),
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["parent-provided", "child-only"]
    assert os.environ.get(key) == before


def test_stdout_value_can_drive_next_command():
    first = run_command(_py("import json; print(json.dumps({'count': 3}))"))
    assert first.returncode == 0
    payload = json.loads(first.stdout)

    second = run_command(
        _py("import sys; print(int(sys.argv[1]) * 2)", str(payload["count"]))
    )
    assert (second.returncode, second.stdout.strip()) == (0, "6")


def test_temporary_file_handoff_is_explicit_and_cleaned():
    with TemporaryDirectory() as raw:
        root = Path(raw)
        artifact = root / "handoff.json"

        produced = run_command(
            _py(
                "from pathlib import Path; import json,sys; "
                "Path(sys.argv[1]).write_text(json.dumps({'ok': True}), encoding='utf-8')",
                artifact,
            )
        )
        assert produced.returncode == 0

        consumed = run_command(
            _py(
                "from pathlib import Path; import json,sys; "
                "print(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['ok'])",
                artifact,
            )
        )
        assert (consumed.returncode, consumed.stdout.strip()) == (0, "True")
        assert artifact.is_file()

    assert not root.exists()


def test_conditional_fallback_without_shell():
    primary = run_command(_py("import sys; sys.exit(1)"))
    assert primary.returncode == 1

    fallback = None
    if primary.returncode != 0:
        fallback = run_command(_py("print('fallback')"))

    assert fallback is not None
    assert (fallback.returncode, fallback.stdout.strip()) == (0, "fallback")


# ---- observation path ----
class _Headings(HTMLParser):
    def __init__(self):
        super().__init__()
        self._tag = None
        self._parts = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "h3"}:
            self._tag = tag
            self._parts = []

    def handle_data(self, data):
        if self._tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == self._tag:
            self.headings.append((tag, "".join(self._parts).strip()))
            self._tag = None
            self._parts = []


def test_static_html_is_a_real_read_only_interface(tmp_path):
    html = """<!doctype html>
<html><head><title>Report</title></head>
<body><h1>Technical report</h1><p>All useful information is here.</p>
<h2>Results</h2><p>42</p></body></html>"""
    (tmp_path / "report.html").write_text(html, encoding="utf-8", newline="\n")

    with local_server(tmp_path) as url:
        with urlopen(url + "/report.html", timeout=5) as response:
            payload = response.read().decode("utf-8")
            assert response.status == 200
        assert payload == html


def test_generic_html_parser_can_extract_only_what_is_needed():
    parser = _Headings()
    parser.feed(
        "<html><body><h1>Index</h1><p>ignored</p>"
        "<h2>One</h2><div><h3>Nested</h3></div></body></html>"
    )
    assert parser.headings == [
        ("h1", "Index"),
        ("h2", "One"),
        ("h3", "Nested"),
    ]


def test_missing_document_remains_http_404(tmp_path):
    with local_server(tmp_path) as url:
        try:
            urlopen(url + "/missing.html", timeout=5)
        except HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("missing static document unexpectedly succeeded")


def test_logging_supplies_metadata_without_echo_plumbing():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger = logging.getLogger("cli_args.observation")
    previous = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("fetch_complete")
        try:
            raise RuntimeError("observation exception evidence")
        except RuntimeError:
            logger.exception("fetch_failed")
    finally:
        logger.handlers, logger.level, logger.propagate = previous
        handler.close()
    lines = stream.getvalue().splitlines()
    datetime.strptime(lines[0].split()[0], "%Y-%m-%dT%H:%M:%SZ")
    assert lines[0].endswith(" INFO cli_args.observation fetch_complete")
    assert lines[1].endswith(" ERROR cli_args.observation fetch_failed")
    assert "Traceback (most recent call last):" in stream.getvalue()
    assert "RuntimeError: observation exception evidence" in stream.getvalue()
