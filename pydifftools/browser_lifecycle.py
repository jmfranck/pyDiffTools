import os
import re
import shutil
import subprocess
import sys

# Optional callbacks for callers that need to prepare for a dialog.
dialog_callbacks = []


# also used by: continuous.py, notebook/fast_build.py, flowchart/watch_graph.py
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
    """Notify registered callers before a dialog appears."""
    for callback in list(dialog_callbacks):
        callback()


# also used by: continuous.py, notebook/fast_build.py, flowchart/watch_graph.py
def browser_window_is_alive(browser):
    # Keep all browser liveness checks in one place so watch commands share
    # the same shutdown behavior when a user closes the browser window.
    # Do not probe with execute_script here: page navigations can briefly
    # interrupt script execution even while the window is still open.
    from selenium.common.exceptions import (
        InvalidSessionIdException, NoSuchWindowException, WebDriverException,
    )

    if browser is None:
        return False
    try:
        handles = browser.window_handles
        if not handles:
            return False
        return True
    except (InvalidSessionIdException, NoSuchWindowException):
        return False
    except WebDriverException:
        # A transient command failure is not evidence of a closed window.
        return True


# also used by: continuous.py, notebook/fast_build.py, flowchart/watch_graph.py
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
        r"""
        const searchText = arguments[0];
        let didFind = window.find && window.find(searchText);
        // Match across inline elements, entities, and rendered references.
        if (!didFind) {
            const escape = text => text.replace(
                /[.*+?^${}()|[\]\\]/g, '\\$&'
            ).replace(/\s+/g, '\\s+');
            const reference =
                /\[?@([a-z]{2,4}):(\w(?:[\w:./-]*[\w/-])?)\]?/gi;
            let pattern = '', cursor = 0, match;
            let valid = true;
            while ((match = reference.exec(searchText))) {
                pattern += escape(searchText.slice(cursor, match.index));
                const id = match[1].toLowerCase() + ':' + match[2];
                const link = Array.from(
                    document.querySelectorAll('a[href]')
                ).find(a => a.getAttribute('href') === '#' + id);
                const target = document.getElementById(id);
                if (!link && !target) {
                    valid = false;
                    break;
                }
                // Unlinked crossrefs still render a numeric label. For a
                // reference alone, select its target rather than guessing
                // which occurrence of that number the user intended.
                if (!link && searchText.trim() === match[0]) {
                    const range = document.createRange();
                    range.selectNodeContents(target);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    didFind = true;
                    valid = false;
                    break;
                }
                pattern += '(?:(?:eq(?:uation)?|fig(?:ure)?|tab(?:le)?|' +
                    'sec(?:tion)?|ch(?:apter)?|lst|listing)s?\\.?\\s*)?' +
                    (link ? escape(link.textContent.trim()) :
                        '\\(?\\d+(?:[.–-]\\d+)*[a-z]?\\)?');
                cursor = reference.lastIndex;
            }
            pattern += escape(searchText.slice(cursor));
            if (valid) {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                const nodes = [], starts = [];
                let text = '', node;
                while ((node = walker.nextNode())) {
                    if (node.parentElement.closest(
                        'script, style, noscript, [hidden]'
                    ) || !node.parentElement.getClientRects().length) {
                        continue;
                    }
                    starts.push(text.length);
                    nodes.push(node);
                    text += node.textContent;
                }
                const result = new RegExp(pattern, 'i').exec(text);
                if (result && result[0].length) {
                    const start = result.index;
                    const end = start + result[0].length;
                    const first = starts.findIndex((offset, i) =>
                        offset + nodes[i].length > start
                    );
                    const last = starts.findIndex((offset, i) =>
                        offset + nodes[i].length >= end
                    );
                    const range = document.createRange();
                    range.setStart(nodes[first], start - starts[first]);
                    range.setEnd(nodes[last], end - starts[last]);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    didFind = true;
                }
            }
        }
        if (didFind && window.getSelection) {
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const rect = selection.getRangeAt(0).getBoundingClientRect();
                window.scrollBy(0, rect.top - window.innerHeight / 3);
            }
        }
        return Boolean(didFind);
        """,
        search_text,
    )
    if not found:
        print("forward search did not find text:", search_text)
    # Bring the browser window to the foreground in Linux window managers,
    # but only when it found the text, since every qmdb session hears it.
    if found and os.name == "posix" and shutil.which("wmctrl"):
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
