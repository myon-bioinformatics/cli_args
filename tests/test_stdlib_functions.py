from collections import Counter, deque
from configparser import ConfigParser
from contextlib import ExitStack, redirect_stdout
import csv
from functools import lru_cache, partial
import hashlib
from io import StringIO
from itertools import chain, islice
from pathlib import Path
from pprint import pformat
import shlex
from tempfile import TemporaryDirectory
import textwrap
from urllib.parse import quote, unquote


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
