"""Local browser-to-editor requests for source jumps."""

import http.server
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import subprocess
import threading
import urllib.parse


MAX_SOURCE_JUMP_BYTES = 8192


# also used by: SourceJumpServer's HTTP request handler and
# tests/test_source_jump.py
def jump_to_source(source_path, phrase):
    """Find the rendered phrase in the source and open gvim at its line."""

    # {{{ match rendered text through wrapping and Markdown delimiters
    # The browser marks HTML tag boundaries with U+E000, including tags
    # inside words (H<sub>2</sub>O). Ordinary words stay literal; Markdown
    # delimiters are allowed only at word boundaries or these tag markers.
    delimiters = r"[*_~^`]*"
    # The browser replaces math and figure references with whitespace.
    # Permit their source syntax in those gaps, while keeping prose literal.
    source_gap = (
        r"(?:[\s*_~^`]|"
        r"(?<!\\)\$\$(?:\\[\s\S]|[^\\$]|\$(?!\$))*\$\$|"
        r"(?<![\\$])\$(?!\$)(?:\\[\s\S]|[^\\$])+\$(?!\$)|"
        r"@fig[-:][\w-]+)+"
    )
    pieces = re.split(r"(\s+|\uE000)", phrase)
    if not any(char.isalnum() for piece in pieces for char in piece):
        raise ValueError(
            "The source-search phrase contains no searchable words"
        )
    fragments = []
    for piece in pieces:
        if piece == "\uE000":
            fragments.append(delimiters)
        elif piece.isspace():
            fragments.append(source_gap)
        elif piece:
            fragments.append(
                delimiters.join(
                    re.escape(token)
                    for token in re.split(r"\b", piece)
                    if token
                )
            )
    pattern = "".join(fragments)
    source_path = Path(source_path).resolve()
    source = source_path.read_text(encoding="utf-8")
    if source_path.suffix.lower() in {".yaml", ".yml"}:
        # {{{ Match literal YAML task definitions rather than dependencies
        # Task keys are not rendered Markdown. Match a complete key at the
        # start of a line, including quoted keys, followed by its colon.
        keys = [
            phrase,
            "'" + phrase.replace("'", "''") + "'",
            json.dumps(phrase, ensure_ascii=False),
            json.dumps(phrase),
        ]
        pattern = (
            r"(?m)^[ \t]*(?:"
            + "|".join(re.escape(key) for key in keys)
            + r")[ \t]*:(?=[ \t\r\n]|$)"
        )
        # }}}
    matches = list(re.finditer(pattern, source))
    if not matches:
        print(f"pydifft source regex: {pattern}", flush=True)
        visible_phrase = phrase.replace("\uE000", "")
        raise ValueError(
            f"No source match in {source_path} for {visible_phrase!r}"
        )
    line = source.count("\n", 0, matches[0].start()) + 1
    if len(matches) > 1:
        lines = [source.count("\n", 0, match.start()) + 1 for match in matches]
        print(
            f"pydifft source matches on lines {lines}; using line {line}",
            flush=True,
        )
    # }}}

    # {{{ launch the user's gvim alias without taking cpb's terminal
    command = [
        "bash", "-ic", 'gvim "$@"', "pydifft",
        "--servername", "GVIM", "--remote", f"+{line}", str(source_path),
    ]
    print(f"pydifft source regex: {pattern}", flush=True)
    print(f"pydifft source command: {shlex.join(command)}", flush=True)
    # Interactive Bash can otherwise change foreground terminal ownership.
    # Give it a separate session and no terminal input; expose its output in
    # the terminal where cpb was launched, including wrapper/editor errors.
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Stop the wrapper as well as Bash if it is polling indefinitely.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    # }}}


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
