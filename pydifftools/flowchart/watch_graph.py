import subprocess
import time
import shutil
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from pydifftools.command_registry import register_command
from .graph import write_dot_from_yaml


def _reload_svg(driver, svg_file: Path) -> None:
    """Refresh the embedded SVG while preserving zoom and scroll."""
    zoom = driver.execute_script("return window.visualViewport.scale")
    scroll_x = driver.execute_script("return window.scrollX")
    scroll_y = driver.execute_script("return window.scrollY")
    svg_uri = svg_file.resolve().as_uri() + f"?t={time.time()}"
    driver.execute_async_script(
        "const [src,z,x,y,done]=arguments;const"
        " s=document.getElementById('svg-view');s.onload=function()"
        "{document.body.style.zoom=z;"
        " window.scrollTo(x,y); done();};s.setAttribute('src', src);",
        svg_uri,
        zoom,
        scroll_x,
        scroll_y,
    )


def start_chrome(webdriver, options, html_file):
    # Launch Chrome and display the local SVG preview HTML file.
    driver = webdriver.Chrome(options=options)
    driver.get(html_file.resolve().as_uri())
    return driver


def close_chrome(driver):
    # Close the Chrome window if it is still running.
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass


def build_graph(
    yaml_file,
    dot_file,
    svg_file,
    wrap_width,
    order_by_date=False,
    prev_data=None,
    target_task=None,
    no_clustering=False,
):
    # Graphviz is required for dot -> svg rendering.
    if shutil.which("dot") is None:
        raise RuntimeError(
            "Graphviz is required to render flowcharts. Install it so the"
            " 'dot' executable is available on your PATH."
        )
    data = write_dot_from_yaml(
        str(yaml_file),
        str(dot_file),
        wrap_width=wrap_width,
        order_by_date=order_by_date,
        old_data=prev_data,
        validate_due_dates=True,
        filter_task=target_task,
        no_clustering=no_clustering,
    )
    subprocess.run(
        ["dot", "-Tsvg", str(dot_file), "-o", str(svg_file)],
        check=True,
    )
    return data


class GraphEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        yaml_file,
        dot_file,
        svg_file,
        html_file=None,
        driver=None,
        options=None,
        webdriver=None,
        wrap_width=55,
        data=None,
        order_by_date=False,
        target_task=None,
        no_clustering=False,
        debounce=0.25,
    ):
        self.yaml_file = Path(yaml_file)
        self.dot_file = Path(dot_file)
        self.svg_file = Path(svg_file)
        self.html_file = None if html_file is None else Path(html_file)
        self.driver = driver
        self.options = options
        self.webdriver = webdriver
        self.wrap_width = wrap_width
        self.data = data
        self.order_by_date = order_by_date
        self.target_task = target_task
        self.no_clustering = no_clustering
        self.debounce = debounce
        self._last_handled = 0.0
        self._last_mtime = None

    def on_modified(self, event):
        if Path(event.src_path) == self.yaml_file:
            mtime = self.yaml_file.stat().st_mtime
            if self._last_mtime is not None and mtime == self._last_mtime:
                return
            now = time.time()
            if now - self._last_handled < self.debounce:
                return
            self._last_handled = now
            try:
                self.data = build_graph(
                    self.yaml_file,
                    self.dot_file,
                    self.svg_file,
                    self.wrap_width,
                    self.order_by_date,
                    self.data,
                    self.target_task,
                    self.no_clustering,
                )
            except Exception:
                # If the graph fails to build (e.g. invalid date), close the
                # preview window until a clean rebuild occurs.
                close_chrome(self.driver)
                self.driver = None
                self._last_mtime = self.yaml_file.stat().st_mtime
                return
            if self.driver is None:
                # Restart the preview once the SVG successfully builds again.
                if (
                    self.webdriver is not None
                    and self.options is not None
                    and self.html_file is not None
                ):
                    self.driver = start_chrome(
                        self.webdriver, self.options, self.html_file
                    )
                else:
                    # Allow legacy/test usage without a live driver.
                    _reload_svg(self.driver, self.svg_file)
                    self._last_mtime = self.yaml_file.stat().st_mtime
                    return
            else:
                _reload_svg(self.driver, self.svg_file)
            self._last_mtime = self.yaml_file.stat().st_mtime


@register_command(
    "Watch a flowchart YAML file, rebuild DOT/SVG output, and open the"
    " preview",
    help={
        "yaml": "Path to the flowchart YAML file",
        "wrap_width": "Line wrap width used when generating node labels",
        "d": "Render nodes by date without showing connections",
        "t": (
            "Task name to focus on (show incomplete ancestor tasks only)"
        ),
        "no_clustering": "Disable endpoint clustering and render classic node-only graph",
    },
)
def wgrph(yaml, wrap_width=55, d=False, t=None, no_clustering=False):
    # Selenium is only required when actually launching the watcher, so it is
    # imported here to avoid breaking the command-line tools when the optional
    # dependency is not installed.
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.common.exceptions import (
            WebDriverException,
            NoSuchWindowException,
        )
    except ImportError as exc:
        raise ImportError(
            "The 'watch_graph' command requires the 'selenium' package to be"
            " installed."
        ) from exc

    yaml_file = Path(yaml)
    if not yaml_file.exists():
        raise FileNotFoundError(f"YAML file not found: {yaml_file}")

    dot_file = yaml_file.with_suffix(".dot")
    svg_file = yaml_file.with_suffix(".svg")
    html_file = yaml_file.with_suffix(".html")

    # Use date ordering when requested so boxes appear in calendar order.
    # Render the initial graph, optionally restricting to incomplete ancestors
    # of a target task.
    data = build_graph(
        yaml_file, dot_file, svg_file, wrap_width, d, None, t, no_clustering
    )
    html_file.write_text(
        "<html><body style='margin:0'><embed id='svg-view'"
        " type='image/svg+xml'"
        f" src='{svg_file.name}?t={time.time()}'/></body></html>"
    )
    options = Options()
    driver = start_chrome(webdriver, options, html_file)
    event_handler = GraphEventHandler(
        yaml_file,
        dot_file,
        svg_file,
        html_file,
        driver,
        options,
        webdriver,
        wrap_width,
        data,
        d,
        t,
        no_clustering,
    )
    observer = Observer()
    observer.schedule(event_handler, yaml_file.parent, recursive=False)
    observer.start()
    try:
        while True:
            if event_handler.driver is None:
                time.sleep(1)
                continue
            try:
                _ = event_handler.driver.window_handles
                event_handler.driver.execute_script("return 1")
            except (NoSuchWindowException, WebDriverException):
                close_chrome(event_handler.driver)
                event_handler.driver = None
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        close_chrome(event_handler.driver)
