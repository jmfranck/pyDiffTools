import pathlib
import subprocess
import pytest

from pydifftools.flowchart.graph import write_dot_from_yaml
from pydifftools.flowchart.watch_graph import (
    _reload_svg,
    _watch_html,
    _watch_view_state_from_params,
)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def test_reload_preserves_view(tmp_path):
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    html_file = tmp_path / "view.html"
    tmp_yaml = tmp_path / "graph.yaml"
    fixture_yaml = pathlib.Path(__file__).with_name("magnet_setup.yaml")
    tmp_yaml.write_text(fixture_yaml.read_text())
    write_dot_from_yaml(tmp_yaml, dot_file)
    subprocess.run(["dot", "-Tsvg", dot_file, "-o", svg_file], check=True)
    html_file.write_text(
        "<html><body style='margin:0'>"
        f"<embed id='svg-view' type='image/svg+xml' src='{svg_file.name}'/>"
        "</body></html>"
    )
    options = Options()
    options.add_argument("--headless=new")
    try:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        pytest.skip("chromedriver not available")
    driver.get(html_file.resolve().as_uri())
    driver.execute_script("document.body.style.zoom=1.5")
    driver.execute_script("window.scrollTo(0, 120)")
    zoom_before = driver.execute_script("return window.visualViewport.scale")
    scroll_before = driver.execute_script("return window.scrollY")
    _reload_svg(driver, svg_file)
    zoom_after = driver.execute_script("return window.visualViewport.scale")
    scroll_after = driver.execute_script("return window.scrollY")
    driver.quit()
    assert zoom_before == zoom_after
    assert scroll_before == scroll_after


def test_watch_html_uses_block_embed(tmp_path):
    html = _watch_html("/graph.svg", False)
    assert "<body style='margin:0'>" in html
    assert "style='display:block;'" in html
    assert "id='svg-view'" in html
    assert "type='image/svg+xml'" in html
    assert "<a href='/?d=1'>date-ordered</a>" in html


def test_watch_html_shows_project_overview_link_in_date_mode():
    html = _watch_html("/graph.svg", True)
    assert "<a href='/'>project overview</a>" in html


def test_watch_html_shows_project_overview_link_in_task_mode():
    html = _watch_html("/graph.svg", False, "task_a")
    assert "<a href='/?d=1'>date-ordered</a>" in html
    assert "<a href='/'>project overview</a>" in html


def test_watch_view_state_defaults_to_project_overview():
    assert _watch_view_state_from_params({}) == (False, None)


def test_watch_view_state_prefers_task_mode_over_date_mode():
    assert _watch_view_state_from_params(
        {"d": ["1"], "t": ["task_a"]}
    ) == (False, "task_a")


class FakeObserver:
    def __init__(self):
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path, recursive=False):
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self):
        return

    def stop(self):
        self.stopped = True

    def join(self):
        self.joined = True


class FakePreviewServer:
    latest = None

    def __init__(self, event_handler):
        self.event_handler = event_handler
        self.base_url = "http://127.0.0.1:9999/"
        self.svg_url = "http://127.0.0.1:9999/graph.svg"
        self.started = False
        self.stopped = False
        self.served = 0
        FakePreviewServer.latest = self

    def start(self):
        self.started = True

    def serve_pending_request(self):
        self.served += 1

    def stop(self):
        self.stopped = True


def test_wgrph_stops_preview_server_when_browser_window_closed(
    tmp_path, monkeypatch
):
    # Build a minimal yaml graph for the command to read.
    yaml_file = tmp_path / "graph.yaml"
    yaml_file.write_text("nodes:\n  task_a:\n    text: Task A\n")

    close_calls = []

    # Replace expensive components so the command loop can run as a fast
    # unit test.
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.build_graph",
        lambda *args, **kwargs: {"nodes": {"task_a": {"text": "Task A"}}},
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.start_chrome",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.browser_window_is_alive",
        lambda _driver: False,
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.close_chrome",
        close_calls.append,
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.Observer", FakeObserver
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph.FlowchartPreviewServer",
        FakePreviewServer,
    )

    from pydifftools.flowchart.watch_graph import wgrph

    wgrph(str(yaml_file))

    # The browser shutdown path must also stop the local preview server.
    assert FakePreviewServer.latest is not None
    assert FakePreviewServer.latest.started is True
    assert FakePreviewServer.latest.stopped is True
    assert len(close_calls) == 1
