from pydifftools import continuous
from selenium.common.exceptions import WebDriverException


class FakeObserver:
    def __init__(self):
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path=".", recursive=False):
        self.handler = handler

    def start(self):
        return

    def stop(self):
        self.stopped = True

    def join(self):
        self.joined = True


class FakeThread:
    def __init__(self, target=None, args=None, daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.joined = False

    def start(self):
        self.started = True

    def join(self):
        self.joined = True


class FakeHandler:
    def __init__(self, filename, observer, comments_to_margin=False, **kwargs):
        self.filename = filename
        self.observer = observer
        self.comments_to_margin = comments_to_margin
        self.chrome = object()

    def forward_search(self, _search_text):
        return


def test_cpb_exits_when_browser_window_closed(monkeypatch):
    close_calls = []

    monkeypatch.setattr(continuous, "Observer", FakeObserver)
    monkeypatch.setattr(continuous, "Handler", FakeHandler)
    monkeypatch.setattr(continuous.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        continuous,
        "browser_window_is_alive",
        lambda _browser: False,
    )
    monkeypatch.setattr(continuous, "close_browser_window", close_calls.append)
    monkeypatch.setattr(continuous.time, "sleep", lambda _seconds: None)

    continuous.cpb("notes.md")

    assert len(close_calls) == 1


def test_cpb_refresh_failure_does_not_reopen_chrome(monkeypatch):
    class Browser:
        window_handles = ["main"]

        def refresh(self):
            raise WebDriverException("window closed")

    class Event:
        src_path = "notes.md"

    handler = continuous.Handler.__new__(continuous.Handler)
    handler.filename = "notes.md"
    handler.html_file = "notes.html"
    handler.comments_to_margin = False
    handler.no_comments = False
    handler.chrome = Browser()
    reopened = []
    closed = []
    handler.init_chrome = lambda: reopened.append(True)
    handler.append_autorefresh = lambda: None
    monkeypatch.setattr(continuous, "run_pandoc", lambda *args, **kwargs: None)
    monkeypatch.setattr(continuous, "close_browser_window", closed.append)

    handler.on_modified(Event())

    assert len(closed) == 1
    assert handler.chrome is None
    assert not reopened


def test_cpb_ignores_file_event_after_browser_closed(monkeypatch):
    class Event:
        src_path = "notes.md"

    handler = continuous.Handler.__new__(continuous.Handler)
    handler.filename = "notes.md"
    handler.chrome = None
    builds = []
    monkeypatch.setattr(
        continuous, "run_pandoc", lambda *args, **kwargs: builds.append(True)
    )

    handler.on_modified(Event())

    assert not builds
