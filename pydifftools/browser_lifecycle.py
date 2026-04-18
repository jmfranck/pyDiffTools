import os
import shutil
import subprocess

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
            # Try common Chromium title forms used by desktop environments.
            for title_candidate in [
                window_title,
                window_title + " - Google Chrome",
                window_title + " - Chromium",
                window_title + " - Chrome",
            ]:
                subprocess.run(["wmctrl", "-a", title_candidate], check=False)
    return found
