from types import SimpleNamespace

import pytest
from selenium.common.exceptions import (
    SessionNotCreatedException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options

from pydifftools import browser_lifecycle
from pydifftools.flowchart.watch_graph import start_chrome


class FakeBrowser:
    def __init__(self, handles=None, quit_error=False):
        self.window_handles = handles if handles is not None else ["main"]
        self.quit_error = quit_error
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1
        if self.quit_error:
            raise RuntimeError("already closed")


def test_browser_window_is_alive_true():
    browser = FakeBrowser(handles=["main"])
    assert browser_lifecycle.browser_window_is_alive(browser)


def test_browser_window_is_alive_false_when_handles_missing():
    browser = FakeBrowser(handles=[])
    assert not browser_lifecycle.browser_window_is_alive(browser)


def test_close_browser_window_quits_and_swallows_errors():
    browser = FakeBrowser(quit_error=True)
    browser_lifecycle.close_browser_window(browser)
    assert browser.quit_calls == 1
    browser_lifecycle.close_browser_window(None)


@pytest.mark.parametrize("flowchart", [False, True])
def test_chrome_version_mismatch_warns_and_opens_preview(
    capsys, flowchart
):
    calls = []
    loaded_urls = []
    browser = SimpleNamespace(get=loaded_urls.append)
    options = Options()

    def fake_chrome(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise SessionNotCreatedException(
                "This version of ChromeDriver only supports Chrome "
                "version 154\nCurrent browser version is 153.0.8010.47"
            )
        return browser

    webdriver = SimpleNamespace(Chrome=fake_chrome)
    if flowchart:
        result = start_chrome(webdriver, options, "http://localhost/preview")
        assert loaded_urls == ["http://localhost/preview"]
        assert calls[0] == {"options": options}
        assert calls[1]["options"] is options
    else:
        result = browser_lifecycle.launch_chrome(webdriver)
        assert calls[0] == {}
    assert result is browser
    assert len(calls) == 2
    assert "--disable-build-check" in calls[1]["service"].service_args
    warning = capsys.readouterr().err
    assert "warning: ChromeDriver 154 and Chrome 153 do not match" in warning
    assert "retrying" in warning


@pytest.mark.parametrize(
    "error",
    [
        SessionNotCreatedException("user data directory is already in use"),
        WebDriverException("Chrome is unreachable"),
    ],
)
def test_other_chrome_startup_errors_do_not_retry(error, capsys):
    calls = []

    def fake_chrome(**kwargs):
        calls.append(kwargs)
        raise error

    with pytest.raises(type(error)) as excinfo:
        browser_lifecycle.launch_chrome(SimpleNamespace(Chrome=fake_chrome))
    assert excinfo.value is error
    assert calls == [{}]
    assert capsys.readouterr().err == ""


def test_chrome_retry_failure_is_reported():
    calls = []
    retry_error = SessionNotCreatedException("Chrome crashed during startup")

    def fake_chrome(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise SessionNotCreatedException(
                "This version of ChromeDriver only supports Chrome "
                "version 154\nCurrent browser version is 153.0.8010.47"
            )
        raise retry_error

    with pytest.raises(SessionNotCreatedException) as excinfo:
        browser_lifecycle.launch_chrome(SimpleNamespace(Chrome=fake_chrome))
    assert excinfo.value is retry_error
    assert len(calls) == 2
