import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


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


def _serve(directory: Path):
    def handler(*args, **kwargs):
        return _QuietHandler(*args, directory=str(directory), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_static_html_is_a_real_read_only_interface(tmp_path):
    html = """<!doctype html>
<html><head><title>Report</title></head>
<body><h1>Technical report</h1><p>All useful information is here.</p>
<h2>Results</h2><p>42</p></body></html>"""
    (tmp_path / "report.html").write_text(html, encoding="utf-8", newline="\n")

    server, thread = _serve(tmp_path)
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/report.html", timeout=5) as response:
            payload = response.read().decode("utf-8")
            assert response.status == 200
        assert payload == html
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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
    server, thread = _serve(tmp_path)
    try:
        host, port = server.server_address
        try:
            urlopen(f"http://{host}:{port}/missing.html", timeout=5)
        except HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("missing static document unexpectedly succeeded")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_logging_supplies_metadata_without_echo_plumbing():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("cli_args.observation")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("fetch_complete")
    finally:
        logger.handlers = []
    assert stream.getvalue() == "INFO cli_args.observation fetch_complete\n"
