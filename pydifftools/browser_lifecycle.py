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
