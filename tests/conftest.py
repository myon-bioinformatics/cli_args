"""Helpers shared by the real-CLI suites (host, container, stdlib): executable lookup and a local HTTP server."""
import os, shutil
from contextlib import contextmanager; from functools import partial; from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer; from threading import Thread

import pytest


def available(name):
    """Path of ``name`` on PATH: host-real tests skip without it; the container-real image must have it."""
    executable = shutil.which(name)
    if executable is None:
        if os.environ.get("CLI_ARGS_CONTAINER_REAL") == "1":
            pytest.fail(name + " is not installed in the integration image")
        pytest.skip(name + " is not installed")
    return executable


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def local_server(directory):
    """Serve ``directory`` on 127.0.0.1 (free port) and yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
