import subprocess
import time
from pathlib import Path
from typing import Dict, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException, NoSuchWindowException

from graph import write_dot_from_yaml


def build_graph(
    yaml_file: Path,
    dot_file: Path,
    svg_file: Path,
    wrap_width: int,
    prev_data: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Regenerate DOT and SVG output from the YAML description."""
    data = write_dot_from_yaml(
        str(yaml_file), str(dot_file), wrap_width=wrap_width, old_data=prev_data
    )
    subprocess.run(
        ["dot", "-Tsvg", str(dot_file), "-o", str(svg_file)],
        check=True,
    )
    return data


def _reload_svg(driver, svg_file: Path) -> None:
    """Refresh the embedded SVG while preserving zoom and scroll."""
    zoom = driver.execute_script("return window.visualViewport.scale")
    scroll_x = driver.execute_script("return window.scrollX")
    scroll_y = driver.execute_script("return window.scrollY")
    svg_uri = svg_file.resolve().as_uri() + f"?t={time.time()}"
    driver.execute_async_script(
        "const [src,z,x,y,done]=arguments;"
        "const s=document.getElementById('svg-view');"
        "s.onload=function(){document.body.style.zoom=z; window.scrollTo(x,y); done();};"
        "s.setAttribute('src', src);",
        svg_uri,
        zoom,
        scroll_x,
        scroll_y,
    )


class GraphEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        yaml_file,
        dot_file,
        svg_file,
        driver,
        wrap_width: int,
        data: Dict[str, Any] | None,
        *,
        debounce: float = 0.25,
    ):
        self.yaml_file = Path(yaml_file)
        self.dot_file = Path(dot_file)
        self.svg_file = Path(svg_file)
        self.driver = driver
        self.wrap_width = wrap_width
        self.data = data
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
            self.data = build_graph(
                self.yaml_file,
                self.dot_file,
                self.svg_file,
                self.wrap_width,
                self.data,
            )
            self._last_mtime = self.yaml_file.stat().st_mtime
            _reload_svg(self.driver, self.svg_file)


def main(yaml_path: str, wrap_width: int = 55) -> None:
    yaml_file = Path(yaml_path)
    dot_file = yaml_file.with_suffix(".dot")
    svg_file = yaml_file.with_suffix(".svg")
    html_file = yaml_file.with_suffix(".html")
    data = build_graph(yaml_file, dot_file, svg_file, wrap_width)
    html_file.write_text(
        "<html><body style='margin:0'>"
        f"<embed id='svg-view' type='image/svg+xml' src='{svg_file.name}?t={time.time()}'/>"
        "</body></html>"
    )
    options = Options()
    driver = webdriver.Chrome(options=options)
    driver.get(html_file.resolve().as_uri())
    event_handler = GraphEventHandler(
        yaml_file, dot_file, svg_file, driver, wrap_width, data
    )
    observer = Observer()
    observer.schedule(event_handler, yaml_file.parent, recursive=False)
    observer.start()
    try:
        while True:
            try:
                # Cheap liveness checks: if the window is gone these raise
                _ = driver.window_handles
                driver.execute_script("return 1")
            except (NoSuchWindowException, WebDriverException):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Watch YAML and render flowchart")
    parser.add_argument("yaml", help="Path to YAML graph description")
    parser.add_argument(
        "--wrap-width",
        type=int,
        default=55,
        help="Line wrap width for node text",
    )
    args = parser.parse_args()
    main(args.yaml, wrap_width=args.wrap_width)

