import io
import queue
import socket
import threading
import time

import pytest

from pydifftools import command_line, forward_search
from pydifftools.notebook import fast_build


def available_address():
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.bind((forward_search.FORWARD_SEARCH_HOST, 0))
    address = reservation.getsockname()
    reservation.close()
    return address


def start_listener(address=None):
    if address is None:
        address = (forward_search.FORWARD_SEARCH_HOST, 0)
    server = forward_search.bind_forward_search_server(address, "test")
    stop_event = threading.Event()
    search_queue = queue.Queue()
    thread = threading.Thread(
        target=forward_search.serve_forward_search,
        args=(server, stop_event, search_queue),
        daemon=True,
    )
    thread.start()
    return server, stop_event, search_queue, thread


def stop_listener(server, stop_event, thread):
    stop_event.set()
    server.close()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_forward_search_round_trip_queues_exact_payload():
    server, stop_event, search_queue, thread = start_listener()
    try:
        address = server.getsockname()
        forward_search.send_forward_search(address, "Result near")
        assert search_queue.get(timeout=1) == "Result near"
        assert thread.is_alive()
    finally:
        stop_listener(server, stop_event, thread)


def test_broken_clients_do_not_terminate_listener(monkeypatch):
    monkeypatch.setattr(
        forward_search, "FORWARD_SEARCH_CONNECTION_TIMEOUT", 0.05
    )
    server, stop_event, search_queue, thread = start_listener()
    address = server.getsockname()
    try:
        # An empty client, malformed UTF-8, and a client that never shuts down
        # its write side are all isolated to their own connection.
        with socket.create_connection(address, timeout=1):
            pass
        with socket.create_connection(address, timeout=1) as client:
            client.sendall(b"\xff")
            client.shutdown(socket.SHUT_WR)
        stalled = socket.create_connection(address, timeout=1)
        stalled.sendall(b"unfinished")
        time.sleep(0.1)
        stalled.close()

        forward_search.send_forward_search(address, "still healthy")
        assert search_queue.get(timeout=1) == "still healthy"
        assert search_queue.empty()
        assert thread.is_alive()
    finally:
        stop_listener(server, stop_event, thread)


def test_non_protocol_service_is_not_reported_as_available():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((forward_search.FORWARD_SEARCH_HOST, 0))
    server.listen(1)
    address = server.getsockname()

    def answer_incorrectly():
        connection, _ = server.accept()
        with connection:
            while connection.recv(4096):
                pass
            connection.sendall(b"not-pydifft\n")

    thread = threading.Thread(target=answer_incorrectly, daemon=True)
    thread.start()
    try:
        with pytest.raises(forward_search.ForwardSearchProtocolError):
            forward_search.send_forward_search(address, "needle")
    finally:
        server.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_mfs_uses_existing_acknowledged_listener_without_fork(
    monkeypatch, tmp_path
):
    server, stop_event, search_queue, thread = start_listener()
    monkeypatch.setattr(
        command_line, "FORWARD_SEARCH_PORT", server.getsockname()[1]
    )
    monkeypatch.setattr(
        command_line, "QMDB_FORWARD_SEARCH_PORT", available_address()[1]
    )
    monkeypatch.setattr(
        command_line.os,
        "fork",
        lambda: pytest.fail("mfs must not fork when cpb acknowledges"),
    )
    monkeypatch.chdir(tmp_path)
    try:
        command_line.mfs("**Result** near @FIG:overview [@smith2024]")
        assert search_queue.get(timeout=1) == "Result near"
    finally:
        stop_listener(server, stop_event, thread)


def test_mfs_refuses_to_fork_for_unhealthy_existing_service(
    monkeypatch, tmp_path
):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((forward_search.FORWARD_SEARCH_HOST, 0))
    server.listen(1)
    cpb_address = server.getsockname()
    qmdb_address = available_address()
    fork_calls = []

    def answer_incorrectly():
        connection, _ = server.accept()
        with connection:
            while connection.recv(4096):
                pass
            connection.sendall(b"wrong service\n")

    thread = threading.Thread(target=answer_incorrectly, daemon=True)
    thread.start()
    monkeypatch.setattr(command_line, "FORWARD_SEARCH_PORT", cpb_address[1])
    monkeypatch.setattr(
        command_line, "QMDB_FORWARD_SEARCH_PORT", qmdb_address[1]
    )
    monkeypatch.setattr(
        command_line.os, "fork", lambda: fork_calls.append(True)
    )
    monkeypatch.chdir(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="Refusing to open another"):
            command_line.mfs("needle")
        assert fork_calls == []
    finally:
        server.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_mfs_autostarts_once_only_when_both_ports_refuse(
    monkeypatch, tmp_path
):
    (tmp_path / "notes.md").write_text("alpha\nneedle\nomega\n")
    cpb_address = available_address()
    qmdb_address = available_address()
    listener = {}
    fork_calls = []

    def fake_fork():
        fork_calls.append(True)
        server, stop_event, search_queue, thread = start_listener(cpb_address)
        listener.update(
            server=server,
            stop_event=stop_event,
            search_queue=search_queue,
            thread=thread,
        )
        return 123

    monkeypatch.setattr(command_line, "FORWARD_SEARCH_PORT", cpb_address[1])
    monkeypatch.setattr(
        command_line, "QMDB_FORWARD_SEARCH_PORT", qmdb_address[1]
    )
    monkeypatch.setattr(command_line.os, "fork", fake_fork)
    monkeypatch.chdir(tmp_path)
    try:
        command_line.mfs("needle")
        assert fork_calls == [True]
        assert listener["search_queue"].get(timeout=1) == "needle"
    finally:
        if listener:
            stop_listener(
                listener["server"],
                listener["stop_event"],
                listener["thread"],
            )


class FakeHttpServer:
    def __init__(self, *_args, **_kwargs):
        self.shutdown_calls = 0
        self.close_calls = 0

    def serve_forever(self):
        return

    def shutdown(self):
        self.shutdown_calls += 1

    def server_close(self):
        self.close_calls += 1


def test_qmdb_port_binding_failure_prevents_build_and_browser(
    monkeypatch, tmp_path
):
    owner = forward_search.bind_forward_search_server(
        (forward_search.FORWARD_SEARCH_HOST, 0), "existing qmdb"
    )
    machine = type("Machine", (), {"build": lambda self, **_k: None})()
    browser_calls = []
    httpd = FakeHttpServer()
    monkeypatch.setattr(
        fast_build.RenderNotebook,
        "from_project",
        classmethod(lambda cls, **_k: machine),
    )
    monkeypatch.setattr(fast_build, "load_rendered_files", lambda: [])
    monkeypatch.setattr(
        fast_build, "ThreadingHTTPServer", lambda *_a, **_k: httpd
    )
    monkeypatch.setattr(
        fast_build, "QMDB_FORWARD_SEARCH_PORT", owner.getsockname()[1]
    )
    monkeypatch.setattr(fast_build, "QMDB_PORT_ATTEMPTS", 1)
    monkeypatch.setattr(
        fast_build,
        "BrowserReloader",
        lambda _url: browser_calls.append(True),
    )
    monkeypatch.setattr(fast_build, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fast_build, "DISPLAY_DIR", tmp_path / "_display")

    try:
        with pytest.raises(RuntimeError, match="Could not bind"):
            fast_build.watch_and_serve()
    finally:
        owner.close()

    assert browser_calls == []
    assert httpd.close_calls == 1


def test_qmdb_closes_listener_observer_http_server_and_browser(
    monkeypatch, tmp_path
):
    qmdb_address = available_address()
    httpd = FakeHttpServer()

    class Machine:
        def __init__(self):
            self.build_calls = 0

        def build(self, **_kwargs):
            self.build_calls += 1

    class Browser:
        def __init__(self):
            self.quit_calls = 0

        def quit(self):
            self.quit_calls += 1

    class Reloader:
        def __init__(self, _url):
            self.browser = Browser()

        def refresh(self):
            return

        def is_alive(self):
            return False

    class Observer:
        def __init__(self):
            self.started = False
            self.stopped = False
            self.joined = False

        def schedule(self, *_args, **_kwargs):
            return

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self):
            self.joined = True

    machine = Machine()
    observer = Observer()
    reloader = Reloader("")
    monkeypatch.setattr(
        fast_build.RenderNotebook,
        "from_project",
        classmethod(lambda cls, **_k: machine),
    )
    monkeypatch.setattr(fast_build, "load_rendered_files", lambda: [])
    monkeypatch.setattr(
        fast_build, "ThreadingHTTPServer", lambda *_a, **_k: httpd
    )
    monkeypatch.setattr(fast_build, "_serve_forever", lambda _httpd: None)
    monkeypatch.setattr(fast_build, "BrowserReloader", lambda _url: reloader)
    monkeypatch.setattr(fast_build, "Observer", lambda: observer)
    monkeypatch.setattr(
        fast_build, "QMDB_FORWARD_SEARCH_PORT", qmdb_address[1]
    )
    monkeypatch.setattr(fast_build, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fast_build, "DISPLAY_DIR", tmp_path / "_display")
    monkeypatch.setattr(fast_build.time, "sleep", lambda _seconds: None)

    fast_build.watch_and_serve()

    rebound = forward_search.bind_forward_search_server(
        qmdb_address, "qmdb shutdown check"
    )
    rebound.close()
    assert machine.build_calls == 1
    assert observer.started
    assert observer.stopped
    assert observer.joined
    assert httpd.shutdown_calls == 1
    assert httpd.close_calls == 1
    assert reloader.browser.quit_calls == 1


def test_mfs_delivers_to_every_qmdb_session(monkeypatch, tmp_path):
    first = start_listener()
    base = first[0].getsockname()[1]
    try:
        second = start_listener((forward_search.FORWARD_SEARCH_HOST, base + 1))
    except RuntimeError:
        stop_listener(first[0], first[1], first[3])
        pytest.skip("neighboring test port is in use")
    monkeypatch.setattr(
        command_line, "FORWARD_SEARCH_PORT", available_address()[1]
    )
    monkeypatch.setattr(command_line, "QMDB_FORWARD_SEARCH_PORT", base)
    monkeypatch.setattr(command_line, "QMDB_PORT_ATTEMPTS", 2)
    monkeypatch.setattr(
        command_line.os,
        "fork",
        lambda: pytest.fail("mfs must not fork when qmdb acknowledges"),
    )
    monkeypatch.chdir(tmp_path)
    try:
        command_line.mfs("needle")
        assert first[2].get(timeout=1) == "needle"
        assert second[2].get(timeout=1) == "needle"
    finally:
        for server, stop_event, _queue, thread in (first, second):
            stop_listener(server, stop_event, thread)


def test_second_qmdb_takes_next_ports_and_accepts_rebuild(
    monkeypatch, tmp_path
):
    owner = forward_search.bind_forward_search_server(
        (forward_search.FORWARD_SEARCH_HOST, 0), "existing qmdb"
    )
    base = owner.getsockname()[1]
    built = threading.Event()
    build_calls = []
    http_ports = []
    handlers = []
    urls = []
    httpd = FakeHttpServer()

    class Machine:
        nodes = {"doc.qmd": object()}

        def build(self, **kwargs):
            build_calls.append(kwargs)
            if "rerun_cells" in kwargs:
                built.set()

    def fake_http_server(address, handler):
        http_ports.append(address[1])
        if len(http_ports) == 1:
            raise OSError(fast_build.errno.EADDRINUSE, "in use")
        handlers.append(handler)
        return httpd

    class Reloader:
        browser = None

        def __init__(self, url):
            urls.append(url)

        def refresh(self):
            return

        def is_alive(self):
            # Exercise the rebuild endpoint before the session closes.
            handler = handlers[0].__new__(handlers[0])
            body = b'{"src": "doc.qmd", "idx": 2}'
            handler.path = fast_build.RERUN_ENDPOINT
            handler.headers = {
                "Origin": "http://localhost:8001",
                "Host": "localhost:8001",
                "Content-Length": str(len(body)),
            }
            handler.rfile = io.BytesIO(body)
            responses = []
            handler.send_response = responses.append
            handler.end_headers = lambda: None
            handler.do_POST()
            assert responses == [202]
            assert built.wait(timeout=2)
            return False

    class Observer:
        def schedule(self, *_args, **_kwargs):
            return

        def start(self):
            return

        def stop(self):
            return

        def join(self):
            return

    monkeypatch.setattr(
        fast_build.RenderNotebook,
        "from_project",
        classmethod(lambda cls, **_k: Machine()),
    )
    monkeypatch.setattr(fast_build, "load_rendered_files", lambda: [])
    monkeypatch.setattr(fast_build, "ThreadingHTTPServer", fake_http_server)
    monkeypatch.setattr(fast_build, "_serve_forever", lambda _httpd: None)
    monkeypatch.setattr(fast_build, "BrowserReloader", Reloader)
    monkeypatch.setattr(fast_build, "Observer", Observer)
    monkeypatch.setattr(fast_build, "QMDB_FORWARD_SEARCH_PORT", base)
    monkeypatch.setattr(fast_build, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fast_build, "DISPLAY_DIR", tmp_path / "_display")
    monkeypatch.setattr(fast_build.time, "sleep", lambda _seconds: None)

    try:
        fast_build.watch_and_serve()
    finally:
        owner.close()

    assert http_ports == [8000, 8001]
    assert urls == ["http://localhost:8001/"]
    # The fallback forward-search port was released on shutdown.
    forward_search.bind_forward_search_server(
        (forward_search.FORWARD_SEARCH_HOST, base + 1), "released"
    ).close()
    (rerun,) = [call for call in build_calls if "rerun_cells" in call]
    assert rerun["rerun_cells"] == {("doc.qmd", 2)}
    assert rerun["changed_paths"] == [tmp_path / "doc.qmd"]
