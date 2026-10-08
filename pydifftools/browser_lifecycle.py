import os
import re
import shutil
import subprocess
import sys

# callbacks that run before any dialog needs the user; cpb registers one
# that closes its live preview, so issues are dealt with before it reopens
dialog_callbacks = []


def start_browser():
    """Prefer Chrome/Chromium, using installed drivers before discovery.

    If only GeckoDriver is installed, use Firefox directly. Otherwise try
    Chrome first, including version-mismatch recovery, then Firefox.
    """
    from selenium import webdriver
    from selenium.common.exceptions import (
        SessionNotCreatedException,
        WebDriverException,
    )
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.firefox.service import Service as FirefoxService

    chrome_driver = shutil.which("chromedriver")
    firefox_driver = shutil.which("geckodriver")
    chrome_error = None
    if chrome_driver or not firefox_driver:
        # {{{ Use installed ChromeDriver without an online Manager lookup
        kwargs = {}
        if chrome_driver:
            options = webdriver.ChromeOptions()
            # Debian's driver defaults to Chromium even if Chrome is installed;
            # retain Selenium Manager's preference for Google Chrome.
            browser_path = (
                shutil.which("google-chrome")
                or shutil.which("google-chrome-stable")
                or shutil.which("chromium")
                or shutil.which("chromium-browser")
            )
            if browser_path:
                options.binary_location = browser_path
            kwargs = {
                "service": ChromeService(chrome_driver),
                "options": options,
            }
        # }}}
        try:
            try:
                return webdriver.Chrome(**kwargs)
            except SessionNotCreatedException as exc:
                # {{{ Retry ChromeDriver's explicit browser-version rejection
                details = str(exc)
                driver_match = re.search(
                    r"ChromeDriver only supports Chrome version (\d+)", details
                )
                browser_match = re.search(
                    r"Current browser version is (\d+)", details
                )
                if driver_match is None or browser_match is None:
                    raise
                print(
                    "pydifft: warning: ChromeDriver "
                    f"{driver_match.group(1)} and Chrome "
                    f"{browser_match.group(1)} do not match; retrying "
                    "with the driver version check disabled.",
                    file=sys.stderr,
                )
                service = kwargs.get("service")
                kwargs["service"] = ChromeService(
                    executable_path=service.path if service else None,
                    service_args=[
                        *(service.service_args if service else []),
                        "--disable-build-check",
                    ],
                )
                return webdriver.Chrome(**kwargs)
                # }}}
        except WebDriverException as exc:
            chrome_error = exc
            print(
                f"pydifft: warning: Chrome/Chromium could not start: {exc}\n"
                "Trying Firefox instead.",
                file=sys.stderr,
            )

    try:
        if firefox_driver:
            return webdriver.Firefox(service=FirefoxService(firefox_driver))
        return webdriver.Firefox()
    except WebDriverException as exc:
        if chrome_error is not None:
            raise exc from chrome_error
        raise


def prepare_for_dialog():
    """Let watch commands close their preview before a dialog appears."""
    for callback in list(dialog_callbacks):
        callback()


def browser_window_is_alive(browser):
    # Keep all browser liveness checks in one place so watch commands share
    # the same shutdown behavior when a user closes the browser window.
    # Do not probe with execute_script here: page navigations can briefly
    # interrupt script execution even while the window is still open.
    if browser is None:
        return False
    try:
        handles = browser.window_handles
        if not handles:
            return False
        return True
    except Exception:
        return False


def close_browser_window(browser):
    # Close a Selenium browser session and ignore errors from already-closed
    # windows so cleanup paths stay simple.
    if browser is None:
        return
    try:
        browser.quit()
    except Exception:
        pass


# also used by: notebook/fast_build.py (qmdb's forward search), besides
# cpb in continuous.py; tests/test_continuous_shutdown.py monkeypatches it
def forward_search_in_browser(browser, search_text):
    # Reuse the same browser-side find logic across cpb and qmdb.
    if browser is None or not search_text:
        return False
    found = browser.execute_script(
        """
        var searchText = arguments[0];
        if (!window.find) {
            return false;
        }
        var didFind = window.find(searchText);
        if (didFind && window.getSelection) {
            var selection = window.getSelection();
            if (selection.rangeCount > 0) {
                var rect = selection.getRangeAt(0).getBoundingClientRect();
                window.scrollBy(0, rect.top - window.innerHeight / 3);
            }
        }
        return didFind;
        """,
        search_text,
    )
    if not found:
        print("forward search did not find text:", search_text)
    # Bring the browser window to the foreground in Linux window managers.
    if os.name == "posix" and shutil.which("wmctrl"):
        window_title = browser.execute_script("return document.title;")
        if window_title:
            # Try common browser title forms used by desktop environments.
            for title_candidate in [
                window_title,
                window_title + " - Google Chrome",
                window_title + " - Chromium",
                window_title + " - Chrome",
                window_title + " - Mozilla Firefox",
            ]:
                subprocess.run(["wmctrl", "-a", title_candidate], check=False)
    return found
