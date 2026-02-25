from pydifftools import continuous


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
        self.firefox = object()

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
