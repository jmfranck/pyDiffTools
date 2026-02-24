import subprocess
import time
import shutil
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from pydifftools.command_registry import register_command
from pydifftools.browser_lifecycle import (
    browser_window_is_alive,
    close_browser_window,
)
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
    close_browser_window(driver)


def build_graph(
    yaml_file,
    dot_file,
    svg_file,
    wrap_width,
    order_by_date=False,
    prev_data=None,
    target_task=None,
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
    )
    subprocess.run(
        ["dot", "-Tsvg", str(dot_file), "-o", str(svg_file)],
        check=True,
    )
    if not order_by_date:
        # In dependency view mode, each endpoint drives a "project" bubble.
        # A project includes the endpoint plus ancestors, but stops before any
        # ancestor that is itself an endpoint.
        endpoints = set()
        for name in data["nodes"]:
            if "children" not in data["nodes"][name]:
                endpoints.add(name)
                continue
            if not data["nodes"][name]["children"]:
                endpoints.add(name)

        projects = {}
        for endpoint in sorted(endpoints):
            projects[endpoint] = [endpoint]
            ancestors_to_visit = []
            if "parents" in data["nodes"][endpoint]:
                for parent in data["nodes"][endpoint]["parents"]:
                    ancestors_to_visit.append(parent)
            already_seen = set([endpoint])
            while ancestors_to_visit:
                ancestor = ancestors_to_visit.pop()
                if ancestor in already_seen:
                    continue
                already_seen.add(ancestor)
                if ancestor in endpoints:
                    continue
                projects[endpoint].append(ancestor)
                if (
                    ancestor in data["nodes"]
                    and "parents" in data["nodes"][ancestor]
                ):
                    for parent in data["nodes"][ancestor]["parents"]:
                        ancestors_to_visit.append(parent)

        svg_tree = ET.parse(str(svg_file))
        svg_root = svg_tree.getroot()
        namespace = ""
        if svg_root.tag.startswith("{"):
            namespace = svg_root.tag[: svg_root.tag.find("}") + 1]

        title_to_group = {}
        graph_group = None
        for group in svg_root.iter(f"{namespace}g"):
            if "class" in group.attrib and group.attrib["class"] == "graph":
                graph_group = group
            for child in group:
                if child.tag == f"{namespace}title" and child.text is not None:
                    title_to_group[child.text.strip()] = group

        color_count = len(projects)
        endpoint_colors = {}
        if color_count > 0:
            # Build a high-saturation rainbow in Lab space with equal lightness
            # and evenly spaced a/b angles so each endpoint stands out.
            for index, endpoint in enumerate(sorted(projects.keys())):
                angle = 2.0 * math.pi * float(index) / float(color_count)
                lab_l = 65.0
                lab_a = 78.0 * math.cos(angle)
                lab_b = 78.0 * math.sin(angle)
                y = (lab_l + 16.0) / 116.0
                x = y + (lab_a / 500.0)
                z = y - (lab_b / 200.0)
                if x**3 > 0.008856:
                    x = x**3
                else:
                    x = (x - (16.0 / 116.0)) / 7.787
                if y**3 > 0.008856:
                    y = y**3
                else:
                    y = (y - (16.0 / 116.0)) / 7.787
                if z**3 > 0.008856:
                    z = z**3
                else:
                    z = (z - (16.0 / 116.0)) / 7.787
                x = 95.047 * x / 100.0
                y = 100.000 * y / 100.0
                z = 108.883 * z / 100.0
                rgb_r = x * 3.2406 + y * -1.5372 + z * -0.4986
                rgb_g = x * -0.9689 + y * 1.8758 + z * 0.0415
                rgb_b = x * 0.0557 + y * -0.2040 + z * 1.0570
                if rgb_r > 0.0031308:
                    rgb_r = 1.055 * (rgb_r ** (1.0 / 2.4)) - 0.055
                else:
                    rgb_r = 12.92 * rgb_r
                if rgb_g > 0.0031308:
                    rgb_g = 1.055 * (rgb_g ** (1.0 / 2.4)) - 0.055
                else:
                    rgb_g = 12.92 * rgb_g
                if rgb_b > 0.0031308:
                    rgb_b = 1.055 * (rgb_b ** (1.0 / 2.4)) - 0.055
                else:
                    rgb_b = 12.92 * rgb_b
                rgb_r = int(round(min(1.0, max(0.0, rgb_r)) * 255.0))
                rgb_g = int(round(min(1.0, max(0.0, rgb_g)) * 255.0))
                rgb_b = int(round(min(1.0, max(0.0, rgb_b)) * 255.0))
                endpoint_colors[endpoint] = (
                    f"#{rgb_r:02x}{rgb_g:02x}{rgb_b:02x}"
                )

        for endpoint in endpoint_colors:
            if endpoint not in title_to_group:
                continue
            for shape in title_to_group[endpoint]:
                if shape.tag in (
                    f"{namespace}polygon",
                    f"{namespace}rect",
                    f"{namespace}ellipse",
                    f"{namespace}path",
                ):
                    shape.set("stroke", endpoint_colors[endpoint])
                    shape.set("stroke-width", "2.5")

        if graph_group is not None and projects:
            bubble_layer = ET.Element(
                f"{namespace}g", {"id": "project-bubbles", "class": "bubbles"}
            )
            for endpoint in sorted(projects.keys()):
                points = []
                for node_name in projects[endpoint]:
                    if node_name not in title_to_group:
                        continue
                    for shape in title_to_group[node_name]:
                        if shape.tag == f"{namespace}polygon" and "points" in shape.attrib:
                            coords = []
                            for pair in shape.attrib["points"].strip().split(" "):
                                if not pair:
                                    continue
                                xy = pair.split(",")
                                if len(xy) == 2:
                                    coords.append((float(xy[0]), float(xy[1])))
                            if coords:
                                min_x = min(x for x, y in coords) - 10.0
                                max_x = max(x for x, y in coords) + 10.0
                                min_y = min(y for x, y in coords) - 10.0
                                max_y = max(y for x, y in coords) + 10.0
                                points.append((min_x, min_y))
                                points.append((max_x, min_y))
                                points.append((max_x, max_y))
                                points.append((min_x, max_y))
                        if shape.tag == f"{namespace}ellipse":
                            cx = float(shape.attrib["cx"])
                            cy = float(shape.attrib["cy"])
                            rx = float(shape.attrib["rx"]) + 10.0
                            ry = float(shape.attrib["ry"]) + 10.0
                            points.append((cx - rx, cy - ry))
                            points.append((cx + rx, cy - ry))
                            points.append((cx + rx, cy + ry))
                            points.append((cx - rx, cy + ry))
                        if shape.tag == f"{namespace}rect":
                            x = float(shape.attrib["x"]) - 10.0
                            y = float(shape.attrib["y"]) - 10.0
                            w = float(shape.attrib["width"]) + 20.0
                            h = float(shape.attrib["height"]) + 20.0
                            points.append((x, y))
                            points.append((x + w, y))
                            points.append((x + w, y + h))
                            points.append((x, y + h))
                if len(points) < 3:
                    continue
                center_x = sum(x for x, y in points) / float(len(points))
                center_y = sum(y for x, y in points) / float(len(points))
                points = sorted(
                    points,
                    key=lambda p: math.atan2(p[1] - center_y, p[0] - center_x),
                )
                hull = []
                for point in points + [points[0], points[1]]:
                    while len(hull) >= 2:
                        cross = (
                            (hull[-1][0] - hull[-2][0])
                            * (point[1] - hull[-2][1])
                            - (hull[-1][1] - hull[-2][1])
                            * (point[0] - hull[-2][0])
                        )
                        if cross > 0:
                            break
                        hull.pop()
                    hull.append(point)
                hull = hull[:-2]
                if len(hull) < 3:
                    continue
                path_parts = [f"M {hull[0][0]:.2f},{hull[0][1]:.2f}"]
                for index in range(len(hull)):
                    prev_point = hull[(index - 1) % len(hull)]
                    point = hull[index]
                    next_point = hull[(index + 1) % len(hull)]
                    control_x = point[0] + (next_point[0] - prev_point[0]) * 0.22
                    control_y = point[1] + (next_point[1] - prev_point[1]) * 0.22
                    path_parts.append(
                        f"Q {control_x:.2f},{control_y:.2f}"
                        f" {next_point[0]:.2f},{next_point[1]:.2f}"
                    )
                path_parts.append("Z")
                bubble_path = ET.Element(
                    f"{namespace}path",
                    {
                        "id": f"project-bubble-{endpoint}",
                        "d": " ".join(path_parts),
                        "fill": "#00000011",
                        "stroke": endpoint_colors[endpoint],
                        "stroke-width": "3",
                    },
                )
                bubble_layer.append(bubble_path)

            insert_index = 0
            for index, child in enumerate(list(graph_group)):
                if child.tag == f"{namespace}polygon":
                    insert_index = index + 1
            graph_group.insert(insert_index, bubble_layer)
            svg_tree.write(str(svg_file), encoding="utf-8", xml_declaration=True)
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
    },
)
def wgrph(yaml, wrap_width=55, d=False, t=None):
    # Selenium is only required when actually launching the watcher, so it is
    # imported here to avoid breaking the command-line tools when the optional
    # dependency is not installed.
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
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
    data = build_graph(yaml_file, dot_file, svg_file, wrap_width, d, None, t)
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
    )
    observer = Observer()
    observer.schedule(event_handler, yaml_file.parent, recursive=False)
    observer.start()
    try:
        while True:
            # Exit the watcher when the browser window is closed so the CLI
            # process does not stay alive in the background.
            if not browser_window_is_alive(event_handler.driver):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        close_chrome(event_handler.driver)
