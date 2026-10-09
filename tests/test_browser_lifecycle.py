from types import SimpleNamespace

import pytest
from selenium.common.exceptions import (
    SessionNotCreatedException,
    WebDriverException,
)
from pydifftools import browser_lifecycle
from pydifftools.flowchart.watch_graph import start_preview_browser
from pydifftools.notebook.fast_build import BrowserReloader
from selenium import webdriver
from selenium.webdriver.common.selenium_manager import SeleniumManager


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


@pytest.mark.parametrize("preview", ["shared", "flowchart", "notebook"])
def test_chrome_version_mismatch_warns_and_opens_preview(
    monkeypatch, capsys, preview
):
    monkeypatch.setattr(browser_lifecycle.shutil, "which", lambda _name: None)
    calls = []
    loaded_urls = []
    browser = SimpleNamespace(get=loaded_urls.append)

    def fake_chrome(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise SessionNotCreatedException(
                "This version of ChromeDriver only supports Chrome "
                "version 154\nCurrent browser version is 153.0.8010.47"
            )
        return browser

    monkeypatch.setattr(webdriver, "Chrome", fake_chrome)
    if preview == "flowchart":
        result = start_preview_browser("http://localhost/preview")
    elif preview == "notebook":
        result = BrowserReloader("http://localhost/preview").browser
    else:
        result = browser_lifecycle.start_browser()
    assert loaded_urls == (
        [] if preview == "shared" else ["http://localhost/preview"]
    )
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
def test_other_chrome_startup_errors_try_firefox(monkeypatch, error, capsys):
    monkeypatch.setattr(browser_lifecycle.shutil, "which", lambda _name: None)
    calls = []

    def fake_chrome(**kwargs):
        calls.append(kwargs)
        raise error

    browser = FakeBrowser()
    monkeypatch.setattr(webdriver, "Chrome", fake_chrome)
    monkeypatch.setattr(webdriver, "Firefox", lambda: browser)
    assert browser_lifecycle.start_browser() is browser
    assert calls == [{}]
    warning = capsys.readouterr().err
    assert str(error) in warning
    assert "Trying Firefox instead" in warning


def test_chrome_retry_failure_tries_firefox(monkeypatch, capsys):
    monkeypatch.setattr(browser_lifecycle.shutil, "which", lambda _name: None)
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

    browser = FakeBrowser()
    monkeypatch.setattr(webdriver, "Chrome", fake_chrome)
    monkeypatch.setattr(webdriver, "Firefox", lambda: browser)
    assert browser_lifecycle.start_browser() is browser
    assert len(calls) == 2
    assert str(retry_error) in capsys.readouterr().err


@pytest.mark.parametrize(
    "browser_name",
    [None, "google-chrome", "google-chrome-stable", "chromium",
     "chromium-browser"],
)
@pytest.mark.parametrize("mismatch", [False, True])
def test_start_browser_uses_installed_chrome_driver_without_manager(
    monkeypatch, browser_name, mismatch,
):
    from selenium.webdriver.common.driver_finder import DriverFinder

    driver_path = webdriver.__file__
    browser_path = "/opt/browser" if browser_name else None
    paths = {"chromedriver": driver_path, "geckodriver": driver_path}
    if browser_name:
        paths[browser_name] = browser_path
    monkeypatch.setattr(
        browser_lifecycle.shutil, "which", paths.get,
    )

    def unexpected_manager(*args, **kwargs):
        raise AssertionError("An installed driver must not need the network")

    monkeypatch.setattr(SeleniumManager, "binary_paths", unexpected_manager)
    services = []
    browser = FakeBrowser()

    def chrome(*, service, options):
        # Exercise Selenium's real discovery path without opening a window.
        finder = DriverFinder(service, options)
        assert finder.get_driver_path() == driver_path
        assert finder.get_browser_path() == ""
        assert options.binary_location == (browser_path or "")
        services.append(service)
        if mismatch and len(services) % 2:
            raise SessionNotCreatedException(
                "This version of ChromeDriver only supports Chrome "
                "version 154\nCurrent browser version is 153.0.8010.47"
            )
        return browser

    monkeypatch.setattr(webdriver, "Chrome", chrome)
    assert browser_lifecycle.start_browser() is browser
    assert browser_lifecycle.start_browser() is browser
    assert len(services) == (4 if mismatch else 2)
    assert services[0] is not services[1]
    if mismatch:
        assert "--disable-build-check" in services[1].service_args
        assert "--disable-build-check" in services[3].service_args


def test_start_browser_keeps_automatic_discovery_without_driver(monkeypatch):
    monkeypatch.setattr(
        browser_lifecycle.shutil, "which", lambda _name: None
    )
    browser = FakeBrowser()
    monkeypatch.setattr(webdriver, "Chrome", lambda: browser)
    assert browser_lifecycle.start_browser() is browser


@pytest.mark.parametrize("chrome_installed", [False, True])
@pytest.mark.parametrize("preview", ["shared", "flowchart", "notebook"])
def test_start_browser_uses_installed_firefox_driver_without_manager(
    monkeypatch, chrome_installed, preview, capsys
):
    from selenium.webdriver.common.driver_finder import DriverFinder

    driver_path = webdriver.__file__
    paths = {"geckodriver": driver_path, "firefox": "/opt/firefox"}
    if chrome_installed:
        paths["chromedriver"] = driver_path
    monkeypatch.setattr(browser_lifecycle.shutil, "which", paths.get)

    def unexpected_manager(*args, **kwargs):
        raise AssertionError("An installed driver must not need the network")

    monkeypatch.setattr(SeleniumManager, "binary_paths", unexpected_manager)
    chrome_calls = []

    def chrome(**kwargs):
        chrome_calls.append(kwargs)
        raise WebDriverException("Chrome unavailable")

    loaded_urls = []
    browser = SimpleNamespace(get=loaded_urls.append)

    def firefox(*, service):
        options = webdriver.FirefoxOptions()
        finder = DriverFinder(service, options)
        assert finder.get_driver_path() == driver_path
        assert finder.get_browser_path() == ""
        return browser

    monkeypatch.setattr(webdriver, "Chrome", chrome)
    monkeypatch.setattr(webdriver, "Firefox", firefox)
    if preview == "flowchart":
        result = start_preview_browser("http://localhost/preview")
    elif preview == "notebook":
        result = BrowserReloader("http://localhost/preview").browser
    else:
        result = browser_lifecycle.start_browser()
    assert result is browser
    assert len(chrome_calls) == int(chrome_installed)
    assert loaded_urls == (
        [] if preview == "shared" else ["http://localhost/preview"]
    )
    warning = capsys.readouterr().err
    if chrome_installed:
        assert "Chrome unavailable" in warning
        assert "Trying Firefox instead" in warning
    else:
        assert warning == ""


def test_start_browser_preserves_both_startup_errors(monkeypatch):
    monkeypatch.setattr(browser_lifecycle.shutil, "which", lambda _name: None)
    chrome_error = WebDriverException("Chrome unavailable")
    firefox_error = WebDriverException("Firefox unavailable")

    def chrome():
        raise chrome_error

    def firefox():
        raise firefox_error

    monkeypatch.setattr(webdriver, "Chrome", chrome)
    monkeypatch.setattr(webdriver, "Firefox", firefox)
    with pytest.raises(WebDriverException) as excinfo:
        browser_lifecycle.start_browser()
    assert excinfo.value is firefox_error
    assert excinfo.value.__cause__ is chrome_error


def test_start_browser_does_not_hide_programming_errors(monkeypatch):
    monkeypatch.setattr(browser_lifecycle.shutil, "which", lambda _name: None)

    def chrome():
        raise TypeError("unexpected argument")

    def firefox():
        pytest.fail("A programming error must not trigger browser fallback")

    monkeypatch.setattr(webdriver, "Chrome", chrome)
    monkeypatch.setattr(webdriver, "Firefox", firefox)
    with pytest.raises(TypeError, match="unexpected argument"):
        browser_lifecycle.start_browser()
