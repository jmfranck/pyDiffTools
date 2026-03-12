import subprocess
import time
import shutil
import math
import urllib.parse
import http.server
import socketserver
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except (
    ImportError
):  # pragma: no cover - allows build_graph tests without watchdog

    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass

    Observer = None  # type: ignore[assignment]
from pydifftools.command_registry import register_command
from pydifftools.browser_lifecycle import (
    browser_window_is_alive,
    close_browser_window,
)
from .graph import write_dot_from_yaml


def _reload_svg(driver, svg_src) -> None:
    """Refresh the embedded SVG while preserving zoom and scroll."""
    zoom = driver.execute_script("return window.visualViewport.scale")
    scroll_x = driver.execute_script("return window.scrollX")
    scroll_y = driver.execute_script("return window.scrollY")
    if isinstance(svg_src, Path):
        svg_uri = svg_src.resolve().as_uri()
    else:
        svg_uri = str(svg_src)
    if "?" in svg_uri:
        svg_uri = svg_uri + f"&ts={time.time()}"
    else:
        svg_uri = svg_uri + f"?ts={time.time()}"
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


def start_chrome(webdriver, options, preview_url):
    # Launch Chrome and display the local SVG preview page from the server.
    driver = webdriver.Chrome(options=options)
    driver.get(preview_url)
    return driver


def close_chrome(driver):
    # Close the Chrome window if it is still running.
    close_browser_window(driver)


def _svg_style_get(style_text, key):
    for piece in style_text.split(";"):
        piece = piece.strip()
        if not piece or ":" not in piece:
            continue
        found_key, found_value = piece.split(":", 1)
        if found_key.strip() == key:
            return found_value.strip()
    return None


def _svg_style_set(style_text, key, value):
    parts = []
    replaced = False
    for piece in style_text.split(";"):
        piece = piece.strip()
        if not piece:
            continue
        if ":" not in piece:
            parts.append(piece)
            continue
        found_key, _ = piece.split(":", 1)
        if found_key.strip() == key:
            parts.append(f"{key}:{value}")
            replaced = True
        else:
            parts.append(piece)
    if not replaced:
        parts.append(f"{key}:{value}")
    return ";".join(parts)


def _svg_get_float_attr(shape, attr_name, default_value):
    if attr_name in shape.attrib:
        try:
            return float(shape.attrib[attr_name])
        except ValueError:
            pass
    if "style" in shape.attrib:
        styled = _svg_style_get(shape.attrib["style"], attr_name)
        if styled is not None:
            try:
                return float(styled)
            except ValueError:
                pass
    return default_value


def _svg_set_stroke(shape, color, stroke_width=None):
    shape.set("stroke", color)
    if stroke_width is not None:
        shape.set("stroke-width", f"{stroke_width:g}")
    if "style" in shape.attrib:
        shape.set(
            "style", _svg_style_set(shape.attrib["style"], "stroke", color)
        )
        if stroke_width is not None:
            shape.set(
                "style",
                _svg_style_set(
                    shape.attrib["style"], "stroke-width", f"{stroke_width:g}"
                ),
            )


def _svg_set_fill(shape, color):
    shape.set("fill", color)
    if "style" in shape.attrib:
        shape.set(
            "style", _svg_style_set(shape.attrib["style"], "fill", color)
        )


def _svg_stroke_color(shape):
    if "stroke" in shape.attrib:
        return shape.attrib["stroke"].strip().lower()
    if "style" in shape.attrib:
        styled = _svg_style_get(shape.attrib["style"], "stroke")
        if styled:
            return styled.strip().lower()
    return None


def _svg_shape_is_red(shape):
    stroke = _svg_stroke_color(shape)
    if stroke is None:
        return False
    return stroke in {"red", "#ff0000", "#f00", "rgb(255,0,0)"}


def _svg_shape_bounds(shape, namespace):
    if shape.tag == f"{namespace}polygon" and "points" in shape.attrib:
        coords = []
        for pair in shape.attrib["points"].strip().split(" "):
            if not pair:
                continue
            xy = pair.split(",")
            if len(xy) != 2:
                continue
            try:
                coords.append((float(xy[0]), float(xy[1])))
            except ValueError:
                return None
        if coords:
            return (
                min(x for x, y in coords),
                max(x for x, y in coords),
                min(y for x, y in coords),
                max(y for x, y in coords),
            )
    if shape.tag == f"{namespace}rect":
        try:
            x = float(shape.attrib["x"])
            y = float(shape.attrib["y"])
            width = float(shape.attrib["width"])
            height = float(shape.attrib["height"])
        except (KeyError, ValueError):
            return None
        return (x, x + width, y, y + height)
    if shape.tag == f"{namespace}ellipse":
        try:
            cx = float(shape.attrib["cx"])
            cy = float(shape.attrib["cy"])
            rx = float(shape.attrib["rx"])
            ry = float(shape.attrib["ry"])
        except (KeyError, ValueError):
            return None
        return (cx - rx, cx + rx, cy - ry, cy + ry)
    return None


def _svg_parse_viewbox(svg_root):
    viewbox = svg_root.attrib.get("viewBox")
    if viewbox is None:
        return None
    parts = viewbox.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(part) for part in parts)
    except ValueError:
        return None


def _svg_add_canvas_padding(svg_root, padding=8.0):
    # Graphviz emits a tight canvas; add small fixed padding so post-processed
    # outlines and anti-aliased strokes are never clipped at edges.
    viewbox = _svg_parse_viewbox(svg_root)
    if viewbox is None:
        return

    view_x, view_y, view_w, view_h = viewbox
    if view_w <= 0.0 or view_h <= 0.0:
        return

    new_view_x = view_x - padding
    new_view_y = view_y - padding
    new_view_w = view_w + 2.0 * padding
    new_view_h = view_h + 2.0 * padding
    svg_root.set(
        "viewBox",
        f"{new_view_x:.2f} {new_view_y:.2f} {new_view_w:.2f} {new_view_h:.2f}",
    )


def _watch_html(svg_url, date_ordered_url):
    # The local preview page points the embed to a server URL so query-string
    # toggles (?t=... and ?d=1) can trigger server-side graph rebuilds.
    return (
        "<html><body style='margin:0'>"
        "<embed id='svg-view' style='display:block;width:100%;height:calc(100vh - 2.2em);'"
        f" type='image/svg+xml' src='{svg_url}'/>"
        "<p style='margin:0.4em 0.8em;font-family:sans-serif;font-size:13px;'>"
        f"<a href='{date_ordered_url}'>date-ordered</a>"
        "</p>"
        "</body></html>"
    )


def _svg_expanded_outline(
    shape, namespace, expand, stroke_color, stroke_width
):
    bounds = _svg_shape_bounds(shape, namespace)
    if bounds is None:
        return None
    x_min, x_max, y_min, y_max = bounds
    if shape.tag == f"{namespace}ellipse":
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        return ET.Element(
            f"{namespace}ellipse",
            {
                "cx": f"{cx:.2f}",
                "cy": f"{cy:.2f}",
                "rx": f"{((x_max - x_min) / 2.0) + expand:.2f}",
                "ry": f"{((y_max - y_min) / 2.0) + expand:.2f}",
                "fill": "none",
                "stroke": stroke_color,
                "stroke-width": f"{stroke_width:g}",
            },
        )
    return ET.Element(
        f"{namespace}rect",
        {
            "x": f"{x_min - expand:.2f}",
            "y": f"{y_min - expand:.2f}",
            "width": f"{(x_max - x_min) + 2.0 * expand:.2f}",
            "height": f"{(y_max - y_min) + 2.0 * expand:.2f}",
            "fill": "none",
            "stroke": stroke_color,
            "stroke-width": f"{stroke_width:g}",
        },
    )



def _svg_add_task_links(svg_root, namespace):
    # Replace marker text emitted in DOT labels with clickable links. Graphviz
    # generates one <text> item per line, so the marker occupies its own row.
    xlink_ns = "http://www.w3.org/1999/xlink"
    ET.register_namespace("xlink", xlink_ns)
    link_marker = "__WGRPH_TASK_LINK__:"
    for group in svg_root.iter(f"{namespace}g"):
        if "class" not in group.attrib or group.attrib["class"] != "node":
            continue
        for index, child in enumerate(list(group)):
            if child.tag != f"{namespace}text" or child.text is None:
                continue
            if not child.text.startswith(link_marker):
                continue
            task_name = child.text[len(link_marker) :]
            child.text = task_name
            link = ET.Element(f"{namespace}a")
            link.set(f"{{{xlink_ns}}}href", f"/?t={urllib.parse.quote(task_name)}")
            link.set("target", "_top")
            link.append(child)
            group.remove(child)
            group.insert(index, link)



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
    svg_tree = ET.parse(str(svg_file))
    svg_root = svg_tree.getroot()
    namespace = ""
    if svg_root.tag.startswith("{"):
        namespace = svg_root.tag[: svg_root.tag.find("}") + 1]

    _svg_add_task_links(svg_root, namespace)

    if not order_by_date:
        # In dependency view mode, each node explicitly tagged with
        # ``style: endpoint`` defines a project color. A project includes the
        # endpoint plus ancestors, but stops before any ancestor that is
        # itself an endpoint.
        endpoints = set()
        for name, node_data in data["nodes"].items():
            if node_data.get("style") == "endpoint":
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

        title_to_group = {}
        node_title_to_group = {}
        for group in svg_root.iter(f"{namespace}g"):
            for child in group:
                if child.tag == f"{namespace}title" and child.text is not None:
                    title = child.text.strip()
                    title_to_group[title] = group
                    if group.attrib.get("class") == "node":
                        node_title_to_group[title] = group

        color_count = len(projects)
        endpoint_colors = {}
        if color_count > 0:
            # Build a high-saturation rainbow in Lab space with equal lightness
            # and evenly spaced a/b angles so each endpoint stands out.
            for index, endpoint in enumerate(sorted(projects.keys())):
                angle = 2.0 * math.pi * float(index) / float(color_count)
                lab_l = 50.0
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

        # Build reverse membership so we can color edges by source-side
        # project assignment after SVG generation.
        node_to_projects = {}
        for endpoint in projects:
            for node_name in projects[endpoint]:
                if node_name not in node_to_projects:
                    node_to_projects[node_name] = []
                node_to_projects[node_name].append(endpoint)

        # Color each edge by the project of the target node (arrowhead/child
        # side), preferring a project that both source and target share.
        for group in svg_root.iter(f"{namespace}g"):
            if "class" not in group.attrib or group.attrib["class"] != "edge":
                continue
            edge_title = None
            for child in group:
                if child.tag == f"{namespace}title" and child.text is not None:
                    edge_title = child.text.strip()
                    break
            if edge_title is None or "->" not in edge_title:
                continue
            source_name = edge_title.split("->", 1)[0].strip()
            target_name = edge_title.split("->", 1)[1].strip()
            edge_color = None
            if (
                source_name in node_to_projects
                and target_name in node_to_projects
            ):
                shared_projects = []
                for endpoint in node_to_projects[target_name]:
                    if endpoint in node_to_projects[source_name]:
                        shared_projects.append(endpoint)
                if shared_projects:
                    edge_color = endpoint_colors[sorted(shared_projects)[0]]
            if edge_color is None and target_name in node_to_projects:
                edge_color = endpoint_colors[
                    sorted(node_to_projects[target_name])[0]
                ]
            if edge_color is None:
                continue
            for child in group:
                if child.tag in (f"{namespace}path", f"{namespace}polygon"):
                    _svg_set_stroke(child, edge_color)
                    if child.tag == f"{namespace}polygon":
                        _svg_set_fill(child, edge_color)

        # Color node borders by project membership after edge coloring. Nodes
        # that belong to multiple projects get concentric transparent outlines.
        for node_name, memberships in node_to_projects.items():
            if node_name not in node_title_to_group:
                continue
            colors = [
                endpoint_colors[endpoint]
                for endpoint in sorted(set(memberships))
                if endpoint in endpoint_colors
            ]
            if not colors:
                continue
            group = node_title_to_group[node_name]
            border_shape = None
            border_index = None
            for index, child in enumerate(list(group)):
                if child.tag not in (
                    f"{namespace}polygon",
                    f"{namespace}rect",
                    f"{namespace}ellipse",
                    f"{namespace}path",
                ):
                    continue
                border_shape = child
                border_index = index
                break
            if border_shape is None or border_index is None:
                continue
            if _svg_shape_is_red(border_shape):
                continue
            base_stroke_width = _svg_get_float_attr(
                border_shape, "stroke-width", 1.0
            )
            _svg_set_stroke(
                border_shape, colors[0], stroke_width=base_stroke_width
            )
            inserts = []
            for ring_index, ring_color in enumerate(colors[1:], start=1):
                outline = _svg_expanded_outline(
                    border_shape,
                    namespace,
                    # Graphviz's emitted geometry can effectively make a
                    # one-line-width expansion render as only ~half-width
                    # visual offset, so push each added ring out by two
                    # stroke widths per ring to keep borders distinct.
                    expand=2.0 * base_stroke_width * ring_index,
                    stroke_color=ring_color,
                    stroke_width=base_stroke_width,
                )
                if outline is None:
                    continue
                inserts.append((border_index + ring_index, outline))
            for insert_index, outline in reversed(inserts):
                group.insert(insert_index, outline)

    _svg_add_canvas_padding(svg_root, padding=24.0)
    svg_tree.write(str(svg_file), encoding="utf-8", xml_declaration=True)
    return data


class GraphEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        yaml_file,
        dot_file,
        svg_file,
        preview_url=None,
        svg_url=None,
        driver=None,
        options=None,
        webdriver=None,
        wrap_width=55,
        data=None,
        state=None,
        debounce=0.25,
    ):
        self.yaml_file = Path(yaml_file)
        self.dot_file = Path(dot_file)
        self.svg_file = Path(svg_file)
        self.preview_url = preview_url
        self.svg_url = svg_url
        self.driver = driver
        self.options = options
        self.webdriver = webdriver
        self.wrap_width = wrap_width
        self.data = data
        if state is None:
            self.state = {"order_by_date": False, "target_task": None}
        else:
            self.state = state
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
                    self.state["order_by_date"],
                    self.data,
                    self.state["target_task"],
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
                    and self.preview_url is not None
                ):
                    self.driver = start_chrome(
                        self.webdriver, self.options, self.preview_url
                    )
                else:
                    # Allow test/legacy usage where no browser driver exists.
                    if self.svg_url is not None:
                        _reload_svg(self.driver, self.svg_url)
                    else:
                        _reload_svg(self.driver, self.svg_file)
                    self._last_mtime = self.yaml_file.stat().st_mtime
                    return
            if self.svg_url is not None:
                _reload_svg(self.driver, self.svg_url)
            else:
                _reload_svg(self.driver, self.svg_file)
            self._last_mtime = self.yaml_file.stat().st_mtime


class FlowchartPreviewServer:
    def __init__(self, event_handler, host="127.0.0.1"):
        self.event_handler = event_handler
        self.host = host
        self.httpd = None
        self.base_url = None
        self.svg_url = None
        self.date_ordered_url = None

    def start(self):
        event_handler = self.event_handler

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/graph.svg":
                    svg_bytes = event_handler.svg_file.read_bytes()
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", "image/svg+xml; charset=utf-8"
                    )
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(svg_bytes)
                    return

                if parsed.path != "/" and parsed.path != "/index.html":
                    self.send_error(404)
                    return

                # Parse query args so GET requests control graph mode.
                params = urllib.parse.parse_qs(
                    parsed.query, keep_blank_values=True
                )
                order_by_date = event_handler.state["order_by_date"]
                target_task = event_handler.state["target_task"]
                if "d" in params:
                    d_value = params["d"][-1]
                    order_by_date = d_value in (
                        "1",
                        "true",
                        "yes",
                        "on",
                        "",
                    )
                if "t" in params:
                    t_value = params["t"][-1].strip()
                    if t_value:
                        target_task = t_value
                        order_by_date = False
                    else:
                        target_task = None

                if (
                    order_by_date != event_handler.state["order_by_date"]
                    or target_task != event_handler.state["target_task"]
                ):
                    event_handler.state["order_by_date"] = order_by_date
                    event_handler.state["target_task"] = target_task
                    event_handler.data = build_graph(
                        event_handler.yaml_file,
                        event_handler.dot_file,
                        event_handler.svg_file,
                        event_handler.wrap_width,
                        event_handler.state["order_by_date"],
                        event_handler.data,
                        event_handler.state["target_task"],
                    )

                body = _watch_html("/graph.svg", "/?d=1")
                body_bytes = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format, *args):
                return

        self.httpd = socketserver.TCPServer((self.host, 0), Handler)
        # Run request handling in the main watcher loop. A short timeout keeps
        # the CLI responsive while still serving GET requests quickly.
        self.httpd.timeout = 0.25
        port = self.httpd.server_address[1]
        self.base_url = f"http://{self.host}:{port}/"
        self.svg_url = f"http://{self.host}:{port}/graph.svg"
        self.date_ordered_url = f"http://{self.host}:{port}/?d=1"

    def serve_pending_request(self):
        if self.httpd is not None:
            self.httpd.handle_request()

    def stop(self):
        if self.httpd is not None:
            self.httpd.server_close()



@register_command(
    "Watch a flowchart YAML file, rebuild DOT/SVG output, and open the"
    " preview",
    help={
        "yaml": "Path to the flowchart YAML file",
        "wrap_width": "Line wrap width used when generating node labels",
        "d": "Render nodes by date without showing connections",
        "t": ("Task name to focus on (show incomplete ancestor tasks only)"),
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

    # The browser now drives filtering/date-mode by GET query parameters
    # handled by the local preview server. Keep Python state in sync there.
    initial_state = {"order_by_date": False, "target_task": None}

    # Build the default dependency graph first. Optional -t / -d args are then
    # applied by requesting server URLs with query parameters.
    data = build_graph(
        yaml_file,
        dot_file,
        svg_file,
        wrap_width,
        initial_state["order_by_date"],
        None,
        initial_state["target_task"],
    )

    options = Options()
    event_handler = GraphEventHandler(
        yaml_file,
        dot_file,
        svg_file,
        None,
        None,
        None,
        options,
        webdriver,
        wrap_width,
        data,
        initial_state,
    )
    preview_server = FlowchartPreviewServer(event_handler)
    preview_server.start()
    event_handler.preview_url = preview_server.base_url
    event_handler.svg_url = preview_server.svg_url

    driver = start_chrome(webdriver, options, preview_server.base_url)
    event_handler.driver = driver

    if t is not None and str(t).strip():
        driver.get(preview_server.base_url + "?t=" + urllib.parse.quote(str(t).strip()))
    elif d:
        driver.get(preview_server.base_url + "?d=1")

    observer = Observer()
    observer.schedule(event_handler, yaml_file.parent, recursive=False)
    observer.start()
    try:
        while True:
            preview_server.serve_pending_request()
            # Exit the watcher when the browser window is closed so the CLI
            # process does not stay alive in the background.
            if not browser_window_is_alive(event_handler.driver):
                break
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        close_chrome(event_handler.driver)
        preview_server.stop()
