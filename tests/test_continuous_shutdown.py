import errno
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import MaxRetryError, NewConnectionError
from watchdog.observers.polling import PollingObserver

from pydifftools import command_line, continuous
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
        refresh_error = self.refresh_error
        self.refreshed.set()
        if refresh_error:
            raise WebDriverException("window closed")

    def quit(self):
        self.quit_calls += 1
        self.closed = True

    def close(self):
        self.closed = True


def install_cpb_runtime(monkeypatch, build_hook=None):
    builds = []
    build_threads = []
    build_options = []
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
        stat = Path(filename).stat()
        source_text = Path(filename).read_text()
        builds.append(source_text)
        build_threads.append(threading.current_thread())
        build_options.append(_kwargs)
        if build_hook is not None:
            build_hook(len(builds), source_text)
        Path(html_file).write_text(
            "<html><head></head><body>" + source_text + "</body></html>"
        )
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def fake_chrome(**_kwargs):
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
    monkeypatch.setattr(continuous, "zotero_notice", lambda: None)
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
        "build_options": build_options,
        "chrome_calls": chrome_calls,
        "native_observers": native_observers,
        "polling_observers": polling_observers,
        "forward_search_port": forward_search_port,
    }


def run_cpb_with_editor(source, browser, editor, **options):
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
    continuous.cpb(str(source), **options)
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
@pytest.mark.parametrize("distance", [0, 9, 20])
@pytest.mark.parametrize("diff", [None, "jf_last"])
def test_cpb_rebuilds_common_save_styles(
    monkeypatch, tmp_path, save_style, distance, diff,
):
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

    run_cpb_with_editor(source, runtime["browser"], editor,
                        wrapnumber=72, trailing_dependent_phrase=distance,
                        diff=diff)

    assert runtime["builds"] == ["before\n", "after\n"]
    assert [options["trailing_dependent_phrase"]
            for options in runtime["build_options"]] == [distance, distance]
    assert [options["wrapnumber"]
            for options in runtime["build_options"]] == [72, 72]
    assert [options["diff"]
            for options in runtime["build_options"]] == [diff, diff]
    assert runtime["browser"].refresh_calls == 1
    assert_clean_polling_shutdown(runtime)


def test_cpb_ignores_its_own_fixes_but_rebuilds_after_editor_save(
    monkeypatch, tmp_path,
):
    source = tmp_path / "content.md"
    source.write_text("Initial unwrapped text.\n")
    runtime = install_cpb_runtime(monkeypatch)
    build = continuous.run_pandoc

    def build_after_autocorrect(filename, html_file, **options):
        before = source.read_text()
        after = before.replace("unwrapped", "wrapped")
        if after != before:
            source.write_text(after)
        return build(filename, html_file, **options)

    monkeypatch.setattr(continuous, "run_pandoc", build_after_autocorrect)
    refreshed = runtime["browser"].refreshed
    settle = (
        continuous.SOURCE_SETTLE_SECONDS + 3 * continuous.POLL_INTERVAL_SECONDS
    )

    def editor():
        assert not refreshed.wait(timeout=settle)
        source.write_text("Edited unwrapped text.\n")
        assert refreshed.wait(timeout=2)
        refreshed.clear()
        assert not refreshed.wait(timeout=settle)

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == [
        "Initial wrapped text.\n", "Edited wrapped text.\n",
    ]
    assert runtime["browser"].refresh_calls == 1
    assert_clean_polling_shutdown(runtime)


def test_cpb_cli_builds_opens_and_reloads_a_real_pandoc_preview(
    monkeypatch, tmp_path,
):
    for tool in ("pandoc", "pandoc-crossref"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} is not available")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    source = tmp_path / "content.md"
    html = tmp_path / "content.html"
    reference = (
        "![The field changes along the cavity axis.]"
        '(<diagram> "Literal <tag>")'
        "{#fig:field}\n\n" + "xyz " * 19 + "end.\n"
    )
    source.write_text(reference)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "add", source.name], check=True)
    source.write_text(reference.replace("cavity axis", "cavity\naxis"))
    with bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "test reservation",
    ) as reservation:
        port = reservation.getsockname()[1]
    monkeypatch.setattr(continuous, "FORWARD_SEARCH_PORT", port)
    monkeypatch.setattr(continuous, "zotero_notice", lambda: None)
    reports = []
    monkeypatch.setattr(
        continuous, "show_markdown_fix_dialog",
        lambda report, **_options: reports.append(report),
    )

    class BrowserWithDriverDisconnect(FakeBrowser):
        @property
        def window_handles(self):
            if self.closed:
                raise MaxRetryError(
                    None, "/session/preview/window/handles",
                    NewConnectionError(None, "Connection refused"),
                )
            return super().window_handles

    browser = BrowserWithDriverDisconnect()
    monkeypatch.setattr(continuous, "start_browser", lambda: browser)
    previews = []

    def open_preview(url):
        assert url == html.as_uri()
        previews.append(html.read_text())
        formatted = source.read_text()
        assert "cavity axis." in formatted
        assert max(map(len, formatted.split("\n\n")[1].splitlines())) <= 79
        source.write_text(
            formatted + "\nThe saved edit reached the preview.\n"
        )

    def reload_preview():
        previews.append(html.read_text())
        browser.close()

    monkeypatch.setattr(browser, "get", open_preview)
    monkeypatch.setattr(browser, "refresh", reload_preview)
    deadline = threading.Timer(10, browser.close)
    deadline.start()
    try:
        command_line.main(["cpb", source.name])
    finally:
        deadline.cancel()

    first, second = previews
    assert 'id="fig:field"' in first
    assert 'id="pydifft-source-jump-config"' in first
    assert "The saved edit reached the preview." in second
    assert len(reports) == 1 and not reports[0]["warnings"]
    assert browser.quit_calls == 1


def test_cpb_sigterm_dismisses_source_fixes_before_opening_preview(
    monkeypatch, tmp_path, capsys,
):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    source = tmp_path / "content.md"
    source.write_text("Many different words need to wrap. " * 5 + "\n")
    monkeypatch.setattr(continuous, "zotero_notice", lambda: None)
    with bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "test reservation",
    ) as reservation:
        port = reservation.getsockname()[1]
    monkeypatch.setattr(continuous, "FORWARD_SEARCH_PORT", port)
    monkeypatch.setattr(
        continuous, "start_browser",
        lambda: pytest.fail("termination should stop before browser startup"),
    )
    application = QApplication.instance() or QApplication([])
    sent = []

    def terminate_from_dialog():
        dialog = application.activeModalWidget()
        if dialog is None:
            return
        timer.stop()
        sent.append(dialog.windowTitle())
        # Bound the wait even when the handler raises inside the Qt callback.
        QTimer.singleShot(1000, dialog.reject)
        os.kill(os.getpid(), signal.SIGTERM)

    timer = QTimer()
    timer.timeout.connect(terminate_from_dialog)
    timer.start(10)
    try:
        continuous.cpb(str(source))
    finally:
        timer.stop()

    assert sent == ["Markdown source fixes"]
    assert "KeyboardInterrupt" not in capsys.readouterr().err
    assert not source.with_suffix(".html").exists()


@pytest.mark.skipif(
    os.environ.get("PYDIFFTOOLS_LOCAL_CPB_BROWSER") != "1",
    reason="opt in to the local Chrome smoke test",
)
def test_cpb_cli_loads_the_preview_in_chrome(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    monkeypatch.setattr(continuous, "zotero_notice", lambda: None)
    source = tmp_path / "content.md"
    source.write_text(
        '# Preview smoke test\n\n![Caption.](<diagram> "Literal <tag>")'
        "{#fig:smoke}\n"
    )
    with bind_forward_search_server(
        (continuous.FORWARD_SEARCH_HOST, 0), "test reservation",
    ) as reservation:
        port = reservation.getsockname()[1]
    monkeypatch.setattr(continuous, "FORWARD_SEARCH_PORT", port)
    chrome = webdriver.Chrome
    visited = []

    def headless_chrome(**kwargs):
        options = kwargs.setdefault("options", webdriver.ChromeOptions())
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.page_load_strategy = "eager"
        preview = chrome(**kwargs)
        navigate = preview.get

        def verify(url):
            navigate(url)
            assert preview.current_url == url
            assert preview.execute_script(
                "return !!document.getElementById('fig:smoke')"
                " && !!document.getElementById('pydifft-source-jump-config');"
            )
            visited.append(url)
            preview.close()

        preview.get = verify
        return preview

    monkeypatch.setattr(webdriver, "Chrome", headless_chrome)
    command_line.main(["cpb", source.name])
    assert visited == [source.with_suffix(".html").as_uri()]


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
        previous_stat = source.stat()
        source.write_text("broken\n")
        # Make this same-size save detectable when rapid writes share an mtime.
        os.utime(
            source,
            ns=(
                previous_stat.st_atime_ns,
                previous_stat.st_mtime_ns + 1_000_000_000,
            ),
        )
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


def test_cpb_refresh_failure_keeps_preview_until_user_closes_it(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)
    runtime["browser"].refresh_error = True

    def editor():
        source.write_text("after\n")
        assert runtime["browser"].refreshed.wait(timeout=2)
        runtime["browser"].refreshed.clear()
        runtime["browser"].refresh_error = False
        source.write_text("recovered\n")
        assert runtime["browser"].refreshed.wait(timeout=2)
        assert runtime["browser"].quit_calls == 0

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n", "after\n", "recovered\n"]
    assert runtime["browser"].refresh_calls == 2
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


def test_cpb_notice_comes_before_the_first_build_and_not_on_rebuild(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    events = []
    runtime = install_cpb_runtime(
        monkeypatch, build_hook=lambda number, _text: events.append(number)
    )
    monkeypatch.setattr(
        continuous, "zotero_notice", lambda: events.append("notice")
    )

    def editor():
        source.write_text("after\n")
        assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)
    # the notice waits for OK, so it is dealt with before Pandoc runs
    assert events == ["notice", 1, 2]
    assert_clean_polling_shutdown(runtime)


@pytest.mark.parametrize("build_fails", [False, True])
def test_cpb_keeps_preview_open_during_rebuild_dialog(
    monkeypatch, tmp_path, build_fails
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    dialog_seen = threading.Event()
    runtime = None

    def build_hook(number, _text):
        if number > 1:
            continuous.prepare_for_dialog()
            assert not runtime["browser"].closed
            assert runtime["browser"].quit_calls == 0
            dialog_seen.set()
            if build_fails:
                raise RuntimeError("source formatting needs attention")

    runtime = install_cpb_runtime(monkeypatch, build_hook=build_hook)

    def editor():
        source.write_text("after\n")
        assert dialog_seen.wait(timeout=2)
        if not build_fails:
            assert runtime["browser"].refreshed.wait(timeout=2)

    run_cpb_with_editor(source, runtime["browser"], editor)
    assert runtime["builds"] == ["before\n", "after\n"]
    assert runtime["browser"].refresh_calls == (0 if build_fails else 1)
    assert_clean_polling_shutdown(runtime)


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


def test_cpb_busy_port_continues_to_initial_build(
    monkeypatch, tmp_path, capsys
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
        webdriver, "Chrome", lambda: chrome_calls.append(True)
    )

    def fail_build(*_a, **_k):
        build_calls.append(True)
        raise RuntimeError("initial build failed")

    monkeypatch.setattr(continuous, "run_pandoc", fail_build)
    try:
        with pytest.raises(RuntimeError, match="initial build failed"):
            continuous.cpb(str(source))
    finally:
        owner.close()

    assert build_calls == [True]
    assert "is taken; trying port" in capsys.readouterr().out
    assert chrome_calls == []


def test_cpb_listener_failure_keeps_visible_preview(monkeypatch, tmp_path):
    source = tmp_path / "content.md"
    source.write_text("before\n")

    def stopped_listener(*_args):
        return

    monkeypatch.setattr(continuous, "serve_forward_search", stopped_listener)
    runtime = install_cpb_runtime(monkeypatch)

    def editor():
        assert not runtime["browser"].closed
        assert runtime["browser"].quit_calls == 0

    run_cpb_with_editor(source, runtime["browser"], editor)

    assert runtime["builds"] == ["before\n"]
    assert runtime["browser"].loaded.is_set()
    assert_clean_polling_shutdown(runtime)


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
def test_cpb_process_signal_closes_browser_and_releases_resources(
    monkeypatch, tmp_path, stop_signal
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate():
        assert runtime["browser"].loaded.wait(timeout=2)
        os.kill(os.getpid(), stop_signal)

    sender = threading.Thread(target=terminate, daemon=True)
    sender.start()
    continuous.cpb(str(source))
    sender.join(timeout=2)
    assert not sender.is_alive()
    assert signal.getsignal(signal.SIGTERM) == previous_handler
    assert_clean_polling_shutdown(runtime)


def test_cpb_forward_search_error_keeps_preview_and_watcher_alive(
    monkeypatch, tmp_path
):
    source = tmp_path / "content.md"
    source.write_text("before\n")
    runtime = install_cpb_runtime(monkeypatch)
    searched = threading.Event()

    def fail_search(_browser, _text):
        searched.set()
        raise WebDriverException("navigation interrupted search")

    monkeypatch.setattr(continuous, "forward_search_in_browser", fail_search)

    def editor():
        send_forward_search(
            (continuous.FORWARD_SEARCH_HOST, runtime["forward_search_port"]),
            "needle",
        )
        assert searched.wait(timeout=2)
        source.write_text("after\n")
        assert runtime["browser"].refreshed.wait(timeout=2)
        assert runtime["browser"].quit_calls == 0

    run_cpb_with_editor(source, runtime["browser"], editor)
    assert runtime["builds"] == ["before\n", "after\n"]
    assert_clean_polling_shutdown(runtime)
