import errno
import threading
import time
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from watchdog.observers.polling import PollingObserver

from pydifftools import continuous
from pydifftools.forward_search import (
    bind_forward_search_server,
    send_forward_search,
)


class ExhaustedObserver:
    def __init__(self):
        self.stopped = False

    def schedule(self, handler, path=".", recursive=False):
        self.handler = handler
        self.path = path

    def start(self):
        raise OSError(errno.EMFILE, "inotify instance limit reached")

    def stop(self):
        self.stopped = True


class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.loaded = threading.Event()
        self.refreshed = threading.Event()
        self.refresh_calls = 0
        self.refresh_threads = []
        self.quit_calls = 0
        self.refresh_error = False

    @property
    def window_handles(self):
        return [] if self.closed else ["main"]

    def get(self, _url):
        self.loaded.set()

    def refresh(self):
        self.refresh_calls += 1
        self.refresh_threads.append(threading.current_thread())
        self.refreshed.set()
        if self.refresh_error:
            raise WebDriverException("window closed")

    def quit(self):
        self.quit_calls += 1
        self.closed = True

    def close(self):
        self.closed = True


def install_cpb_runtime(monkeypatch, build_hook=None):
    builds = []
    build_threads = []
    browser = FakeBrowser()
    chrome_calls = []
    native_observers = []
    polling_observers = []
    port_reservation = bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "test reservation"
    )
    forward_search_port = port_reservation.getsockname()[1]
    port_reservation.close()

    def fake_run_pandoc(filename, html_file, **_kwargs):
        source_text = Path(filename).read_text()
        builds.append(source_text)
        build_threads.append(threading.current_thread())
        if build_hook is not None:
            build_hook(len(builds), source_text)
        Path(html_file).write_text(
            "<html><head></head><body>" + source_text + "</body></html>"
        )

    def fake_chrome():
        chrome_calls.append(True)
        return browser

    def exhausted_observer():
        observer = ExhaustedObserver()
        native_observers.append(observer)
        return observer

    def polling_observer(*args, **kwargs):
        observer = PollingObserver(*args, **kwargs)
        polling_observers.append(observer)
        return observer

    monkeypatch.setattr(continuous, "run_pandoc", fake_run_pandoc)
    monkeypatch.setattr(webdriver, "Chrome", fake_chrome)
    monkeypatch.setattr(continuous, "Observer", exhausted_observer)
    monkeypatch.setattr(continuous, "PollingObserver", polling_observer)
    monkeypatch.setattr(
        continuous, "FORWARD_SEARCH_PORT", forward_search_port
    )
    return {
        "browser": browser,
        "builds": builds,
        "build_threads": build_threads,
        "chrome_calls": chrome_calls,
        "native_observers": native_observers,
        "polling_observers": polling_observers,
        "forward_search_port": forward_search_port,
    }


def run_cpb_with_editor(source, browser, editor):
    editor_errors = []

    def edit_then_close():
        try:
            assert browser.loaded.wait(timeout=2)
            editor()
        except BaseException as exc:
            editor_errors.append(exc)
        finally:
            browser.close()

    editor_thread = threading.Thread(target=edit_then_close, daemon=True)
    editor_thread.start()
    continuous.cpb(str(source))
    editor_thread.join(timeout=2)
    assert not editor_thread.is_alive()
    if editor_errors:
        raise editor_errors[0]


def assert_clean_polling_shutdown(runtime):
    assert len(runtime["chrome_calls"]) == 1
    assert len(runtime["native_observers"]) == 1
    assert runtime["native_observers"][0].stopped
    assert len(runtime["polling_observers"]) == 1
    assert not runtime["polling_observers"][0].is_alive()
    rebound_server = bind_forward_search_server(
        (
            continuous.FORWARD_SEARCH_HOST,
            runtime["forward_search_port"],
        ),
        "shutdown check",
    )
    rebound_server.close()
    assert runtime["browser"].quit_calls == 1


def test_cpb_waits_through_vim_style_save(monkeypatch, tmp_path, capsys):
    source = tmp_path / "content.md"
    backup = tmp_path / "content.md~"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)
    built_while_missing = []

    def editor():
        source.rename(backup)
        time.sleep(continuous.POLL_INTERVAL_SECONDS * 3)
        built_while_missing.append(len(runtime["builds"]) > 1)
        source.write_text("after\n")
        assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert built_while_missing == [False]
    assert runtime["builds"] == ["before\n", "after\n"]
    assert runtime["browser"].refresh_calls == 1
    assert runtime["build_threads"] == [
        threading.current_thread(),
        threading.current_thread(),
    ]
    assert runtime["browser"].refresh_threads == [threading.current_thread()]
    assert "falling back to polling" in capsys.readouterr().err
    assert_clean_polling_shutdown(runtime)


@pytest.mark.parametrize("save_style", ["in_place", "atomic_replace"])
def test_cpb_rebuilds_common_save_styles(monkeypatch, tmp_path, save_style):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)

    def editor():
        if save_style == "in_place":
            source.write_text("after\n")
        else:
            replacement = tmp_path / "content.md.tmp"
            replacement.write_text("after\n")
            replacement.replace(source)
        assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n", "after\n"]
    assert runtime["browser"].refresh_calls == 1
    assert_clean_polling_shutdown(runtime)


def test_cpb_does_not_rebuild_or_reopen_after_browser_closes(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    backup = tmp_path / "content.md~"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)

    def editor():
        source.rename(backup)
        time.sleep(continuous.POLL_INTERVAL_SECONDS * 2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n"]
    assert runtime["browser"].refresh_calls == 0
    assert_clean_polling_shutdown(runtime)


def test_cpb_keeps_watching_after_rebuild_error(monkeypatch, tmp_path, capsys):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    failed_build = threading.Event()

    def build_hook(call_number, _source_text):
        if call_number == 2:
            failed_build.set()
            raise RuntimeError("deliberate rebuild failure")

    runtime = install_cpb_runtime(monkeypatch, build_hook=build_hook)

    def editor():
        source.write_text("broken\n")
        assert failed_build.wait(timeout=2)
        source.write_text("recovered\n")
        assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n", "broken\n", "recovered\n"]
    assert runtime["browser"].refresh_calls == 1
    assert "rebuild failed; keeping the current preview open" in (
        capsys.readouterr().err
    )
    assert_clean_polling_shutdown(runtime)


def test_cpb_refresh_failure_stops_without_reopening(monkeypatch, tmp_path):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)
    runtime["browser"].refresh_error = True

    def editor():
        source.write_text("after\n")
        assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n", "after\n"]
    assert runtime["browser"].refresh_calls == 1
    assert len(runtime["chrome_calls"]) == 1
    assert_clean_polling_shutdown(runtime)


def test_cpb_initial_build_failure_does_not_open_chrome(monkeypatch, tmp_path):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    chrome_calls = []

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("initial build failed")

    reservation = bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "test reservation"
    )
    forward_search_port = reservation.getsockname()[1]
    reservation.close()
    monkeypatch.setattr(continuous, "run_pandoc", fail_build)
    monkeypatch.setattr(webdriver, "Chrome", lambda: chrome_calls.append(True))
    monkeypatch.setattr(
        continuous, "FORWARD_SEARCH_PORT", forward_search_port
    )

    with pytest.raises(RuntimeError, match="initial build failed"):
        continuous.cpb(str(source))

    assert chrome_calls == []


def test_cpb_listener_acknowledges_before_initial_build_finishes(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = None
    forwarded = threading.Event()
    forwarded_searches = []

    def build_hook(call_number, _source_text):
        if call_number == 1:
            send_forward_search(
                (
                    continuous.FORWARD_SEARCH_HOST,
                    runtime["forward_search_port"],
                ),
                "during initial build",
            )

    runtime = install_cpb_runtime(monkeypatch, build_hook=build_hook)

    def fake_forward_search(_browser, search_text):
        forwarded_searches.append(search_text)
        forwarded.set()

    monkeypatch.setattr(
        continuous, "forward_search_in_browser", fake_forward_search
    )

    def editor():
        assert forwarded.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert forwarded_searches == ["during initial build"]
    assert_clean_polling_shutdown(runtime)


def test_cpb_port_binding_failure_prevents_build_and_browser(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    owner = bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "existing owner"
    )
    build_calls = []
    chrome_calls = []
    monkeypatch.setattr(
        continuous, "FORWARD_SEARCH_PORT", owner.getsockname()[1]
    )
    monkeypatch.setattr(
        continuous, "run_pandoc", lambda *_a, **_k: build_calls.append(True)
    )
    monkeypatch.setattr(
        webdriver, "Chrome", lambda: chrome_calls.append(True)
    )

    try:
        with pytest.raises(RuntimeError, match="Could not bind"):
            continuous.cpb(str(source))
    finally:
        owner.close()

    assert build_calls == []
    assert chrome_calls == []


def test_cpb_listener_failure_closes_visible_preview(monkeypatch, tmp_path):
    source = tmp_path / "content.md"
    source.write_text("before\n")

    def stopped_listener(*_args):
        return

    monkeypatch.setattr(continuous, "serve_forward_search", stopped_listener)
    runtime = install_cpb_runtime(monkeypatch)

    with pytest.raises(RuntimeError, match="listener stopped unexpectedly"):
        continuous.cpb(str(source))

    assert runtime["builds"] == ["before\n"]
    assert runtime["browser"].loaded.is_set()
    assert_clean_polling_shutdown(runtime)
