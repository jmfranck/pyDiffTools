from pydifftools import browser_lifecycle


class FakeBrowser:
    def __init__(self, handles=None, script_error=False, quit_error=False):
        self.window_handles = handles if handles is not None else ["main"]
        self.script_error = script_error
        self.quit_error = quit_error
        self.quit_calls = 0

    def execute_script(self, _code):
        if self.script_error:
            raise RuntimeError("window closed")
        return 1

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


def test_browser_window_is_alive_false_when_script_errors():
    browser = FakeBrowser(script_error=True)
    assert not browser_lifecycle.browser_window_is_alive(browser)


def test_close_browser_window_quits_and_swallows_errors():
    browser = FakeBrowser(quit_error=True)
    browser_lifecycle.close_browser_window(browser)
    assert browser.quit_calls == 1
    browser_lifecycle.close_browser_window(None)
