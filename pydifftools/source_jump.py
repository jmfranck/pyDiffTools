"""Local browser-to-editor requests for source jumps."""

import http.server
import re
import secrets
import subprocess
import threading
import urllib.parse


MAX_SOURCE_JUMP_BYTES = 8192
SOURCE_JUMP_WORDS = re.compile(r"[\w]+", re.UNICODE)


def _run_gvim_shell_command(*arguments):
    """Run the user's interactive Bash ``gvim`` alias with safe arguments."""

    subprocess.run(
        ["bash", "-ic", 'gvim "$@"', "pydifft", *arguments],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# also used by: SourceJumpServer's HTTP request handler and
# tests/test_source_jump.py
def jump_to_source(source_path, phrase):
    """Open *source_path* through the user's gvim alias and run ``SW!``."""

    words = [word.lower() for word in SOURCE_JUMP_WORDS.findall(phrase)]
    if not words:
        raise ValueError(
            "The source-search phrase contains no searchable words"
        )
    if len(words) > 120:
        words = words[:120]

    _run_gvim_shell_command(str(source_path))
    remote_keys = "<C-\\><C-N>:SW! " + " ".join(words) + "<CR>"
    _run_gvim_shell_command(
        "--servername", "GVIM", "--remote-send", remote_keys
    )


class SourceJumpServer:
    """An ephemeral loopback HTTP endpoint scoped to one preview session."""

    def __init__(self, source_path):
        self.source_path = str(source_path)
        self.token = secrets.token_urlsafe(24)
        self.httpd = None
        self.thread = None
        self.url = None

    def start(self):
        source_path = self.source_path
        token = self.token

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if (
                    parsed.path != "/jump"
                    or query.get("token", [None])[-1] != token
                ):
                    self.send_error(404)
                    return
                try:
                    content_length = int(
                        self.headers.get("Content-Length", "0")
                    )
                except ValueError:
                    self.send_error(400)
                    return
                if (
                    content_length <= 0
                    or content_length > MAX_SOURCE_JUMP_BYTES
                ):
                    self.send_error(413)
                    return
                try:
                    phrase = self.rfile.read(content_length).decode("utf-8")
                except UnicodeDecodeError:
                    self.send_error(400)
                    return
                try:
                    jump_to_source(source_path, phrase)
                except (
                    OSError,
                    subprocess.SubprocessError,
                    ValueError,
                ) as exc:
                    print(f"pydifft source jump failed: {exc}", flush=True)
                    self.send_error(500)
                    return
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

            def log_message(self, format, *args):
                return

        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), Handler
        )
        self.httpd.daemon_threads = True
        host, port = self.httpd.server_address
        self.url = (
            f"http://{host}:{port}/jump?token="
            + urllib.parse.quote(self.token, safe="")
        )
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True,
        )
        self.thread.start()
        return self.url

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
