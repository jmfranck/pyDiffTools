import subprocess
import html
import sys
import time
import shutil
import math
import threading
import urllib.parse
import http.server
import xml.etree.ElementTree as ET
import traceback
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
from .comparison import PlanComparison
from .graph import EmptyGraphYamlError, endpoint_projects, write_dot_from_yaml


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


def _watch_view_state_from_params(params):
    # Treat each GET query as the full requested mode so navigation links can
    # reliably switch back to the overview without depending on prior state.
    order_by_date = False
    target_task = None
    filter_completed = False
    if "p" in params:
        p_value = params["p"][-1]
        filter_completed = p_value in ("1", "true", "yes", "on", "")
    if "d" in params:
        d_value = params["d"][-1]
        order_by_date = d_value in ("1", "true", "yes", "on", "")
    if "t" in params:
        t_value = params["t"][-1]
        if t_value is not None and str(t_value) != "":
            target_task = str(t_value)
            order_by_date = False
            filter_completed = False
    return order_by_date, target_task, filter_completed


def _watch_html(
    svg_url,
    order_by_date,
    target_task=None,
    filter_completed=False,
    comparison=None,
):
    # Keep the SVG as the page's main content so browser zoom behavior matches
    # the original watcher experience (the graph scales, not just footer text).
    # {{{ Build links for the other preview views
    links = []
    diff_query = (
        "?diff-base=" + urllib.parse.quote(comparison.reference, safe="")
        if comparison is not None
        else ""
    )
    if diff_query:
        separator = "&" if "?" in svg_url else "?"
        svg_url += separator + diff_query[1:]
    query_prefix = f"{diff_query}&" if diff_query else "?"
    if not order_by_date:
        links.append((f"/{query_prefix}d=1", "date-ordered"))
    if not filter_completed and not order_by_date:
        links.append((f"/{query_prefix}p=1", "exclude completed"))
    if order_by_date and not filter_completed:
        links.append((f"/{query_prefix}d=1&p=1", "exclude completed"))
    if not filter_completed:
        links.append((f"/{query_prefix}p=0", "full plan"))
    if (
        order_by_date
        or filter_completed
        or (target_task is not None and str(target_task).strip())
    ):
        links.append((f"/{diff_query}", "project overview"))
    footer_html = " | ".join(
        f"<a href='{url}'>{label}</a>" for url, label in links
    )
    # }}}
    if comparison is not None:
        footer_html += (
            " | Comparing against "
            + html.escape(comparison.reference)
            + " ("
            + comparison.commit[:12]
            + ")"
        )
    return (
        "<html><body style='margin:0'>"
        "<embed id='svg-view' style='display:block;' type='image/svg+xml'"
        f" src='{svg_url}'/>"
        "<p style='margin:0.4em 0.8em;font-family:sans-serif;font-size:13px;'>"
        f"{footer_html}"
        "</p>"
        "</body></html>"
    )


def _send_preview_response(handler, body_bytes, content_type):
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body_bytes)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body_bytes)
    except (
        BrokenPipeError,
        ConnectionAbortedError,
        ConnectionResetError,
        TimeoutError,
    ):
        return False
    return True


def _resolve_due_date_conflict_with_qt(
    name, old_due_text, new_due_text, parent, message
):
    # Run the tiny PySide prompt in its own process so watchdog and preview
    # server worker threads do not create Qt widgets outside the main thread.
    prompt_script = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv[:1])
box = QMessageBox()
box.setWindowTitle("wgrph due date")
box.setIcon(QMessageBox.Icon.Warning)
box.setText(sys.argv[1])
box.setInformativeText("Choose how to resolve this dependency date conflict.")
move_button = box.addButton("Move due date", QMessageBox.ButtonRole.AcceptRole)
break_button = box.addButton(
    "Break dependency", QMessageBox.ButtonRole.DestructiveRole
)
box.setDefaultButton(move_button)
box.exec()
if box.clickedButton() is break_button:
    sys.exit(1)
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", prompt_script, message],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return "move"
    if result.returncode == 1:
        return "break"
    stderr = result.stderr.strip()
    if stderr:
        raise RuntimeError(f"wgrph due-date dialog failed: {stderr}")
    raise RuntimeError("wgrph due-date dialog failed.")


def build_graph(
    yaml_file,
    dot_file,
    svg_file,
    wrap_width,
    order_by_date=False,
    prev_data=None,
    target_task=None,
    filter_completed=False,
    resolve_due_date_conflict=None,
    comparison=None,
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
        filter_completed=filter_completed,
        resolve_due_date_conflict=resolve_due_date_conflict,
        comparison=comparison,
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

    # {{{ Make each task name a navigation link
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
            link.set(
                f"{{{xlink_ns}}}href", f"/?t={urllib.parse.quote(task_name)}"
            )
            link.set("target", "_top")
            link.append(child)
            group.remove(child)
            group.insert(index, link)
    # }}}

    if not order_by_date:
        # In dependency view mode, each endpoint style defines a project
        # color. A project includes the endpoint plus ancestors, but stops
        # before any ancestor that is itself an endpoint.
        projects = endpoint_projects(data)

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
                        child.set("fill", edge_color)
                        if "style" in child.attrib:
                            child.set(
                                "style",
                                _svg_style_set(
                                    child.attrib["style"], "fill", edge_color
                                ),
                            )

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
            # {{{ Read the existing border style before project coloring
            stroke = border_shape.get("stroke") or _svg_style_get(
                border_shape.get("style", ""), "stroke"
            )
            if stroke and stroke.strip().lower() in {
                "red",
                "#ff0000",
                "#f00",
                "rgb(255,0,0)",
            }:
                continue
            base_stroke_width = 1.0
            for value in (
                border_shape.get("stroke-width"),
                _svg_style_get(border_shape.get("style", ""), "stroke-width"),
            ):
                try:
                    base_stroke_width = float(value)
                    break
                except (TypeError, ValueError):
                    pass
            # }}}
            _svg_set_stroke(
                border_shape, colors[0], stroke_width=base_stroke_width
            )
            inserts = []
            for ring_index, ring_color in enumerate(colors[1:], start=1):
                # {{{ Add concentric outlines for shared project membership
                expand = 2.0 * base_stroke_width * ring_index
                shape = border_shape
                try:
                    if shape.tag == f"{namespace}ellipse":
                        attrs = {
                            "cx": shape.attrib["cx"],
                            "cy": shape.attrib["cy"],
                            "rx": str(float(shape.attrib["rx"]) + expand),
                            "ry": str(float(shape.attrib["ry"]) + expand),
                        }
                        tag = "ellipse"
                    else:
                        if shape.tag == f"{namespace}polygon":
                            coords = [
                                tuple(map(float, pair.split(",")))
                                for pair in shape.attrib["points"].split()
                            ]
                            x_min = min(x for x, y in coords)
                            x_max = max(x for x, y in coords)
                            y_min = min(y for x, y in coords)
                            y_max = max(y for x, y in coords)
                        elif shape.tag == f"{namespace}rect":
                            x_min = float(shape.attrib["x"])
                            y_min = float(shape.attrib["y"])
                            x_max = x_min + float(shape.attrib["width"])
                            y_max = y_min + float(shape.attrib["height"])
                        else:
                            continue
                        attrs = {
                            "x": str(x_min - expand),
                            "y": str(y_min - expand),
                            "width": str(x_max - x_min + 2 * expand),
                            "height": str(y_max - y_min + 2 * expand),
                        }
                        tag = "rect"
                except (KeyError, ValueError):
                    continue
                attrs.update(
                    {
                        "fill": "none",
                        "stroke": ring_color,
                        "stroke-width": f"{base_stroke_width:g}",
                    }
                )
                outline = ET.Element(f"{namespace}{tag}", attrs)
                # }}}
                inserts.append((border_index + ring_index, outline))
            for insert_index, outline in reversed(inserts):
                group.insert(insert_index, outline)

    if comparison is not None:
        comparison.style_svg(svg_root, namespace)
    # {{{ Pad the canvas so expanded project borders are never clipped
    try:
        x, y, width, height = map(
            float, svg_root.attrib["viewBox"].replace(",", " ").split()
        )
        if width > 0 and height > 0:
            svg_root.set(
                "viewBox",
                f"{x - 24:.2f} {y - 24:.2f} "
                f"{width + 48:.2f} {height + 48:.2f}",
            )
    except (KeyError, ValueError):
        pass
    # }}}
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
        resolve_due_date_conflict=None,
        debounce=0.25,
        comparison=None,
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
        self.comparison = comparison
        self.resolve_due_date_conflict = resolve_due_date_conflict
        if state is None:
            self.state = {
                "order_by_date": False,
                "target_task": None,
                "filter_completed": False,
            }
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
                build_kwargs = {}
                if self.comparison is not None:
                    build_kwargs["comparison"] = self.comparison
                if self.resolve_due_date_conflict is not None:
                    build_kwargs["resolve_due_date_conflict"] = (
                        self.resolve_due_date_conflict
                    )
                if self.state["filter_completed"]:
                    build_kwargs["filter_completed"] = True
                self.data = build_graph(
                    self.yaml_file,
                    self.dot_file,
                    self.svg_file,
                    self.wrap_width,
                    self.state["order_by_date"],
                    self.data,
                    self.state["target_task"],
                    **build_kwargs,
                )
            except Exception as exc:
                if isinstance(exc, EmptyGraphYamlError):
                    print(
                        "Graph YAML is empty; closing preview window.",
                        flush=True,
                    )
                    close_chrome(self.driver)
                    self.driver = None
                    self._last_mtime = self.yaml_file.stat().st_mtime
                    return
                # Keep the preview open and log the failure so users can
                # see why the graph didn't refresh.
                print(
                    "Graph build failed; keeping preview window open: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                print("---------------------------")
                print("here is the traceback:")
                print(traceback.format_exc(), flush=True)
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
        self.server_thread = None
        self.base_url = None
        self.svg_url = None

    def start(self):
        event_handler = self.event_handler

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/graph.svg":
                    svg_bytes = event_handler.svg_file.read_bytes()
                    _send_preview_response(
                        self,
                        svg_bytes,
                        "image/svg+xml; charset=utf-8",
                    )
                    return

                if parsed.path != "/" and parsed.path != "/index.html":
                    self.send_error(404)
                    return

                # Parse query args so GET requests control graph mode.
                params = urllib.parse.parse_qs(
                    parsed.query, keep_blank_values=True
                )
                (
                    order_by_date,
                    target_task,
                    filter_completed,
                ) = _watch_view_state_from_params(params)

                if (
                    order_by_date != event_handler.state["order_by_date"]
                    or target_task != event_handler.state["target_task"]
                    or filter_completed
                    != event_handler.state["filter_completed"]
                ):
                    event_handler.state["order_by_date"] = order_by_date
                    event_handler.state["target_task"] = target_task
                    event_handler.state["filter_completed"] = filter_completed
                    build_kwargs = {}
                    if event_handler.comparison is not None:
                        build_kwargs["comparison"] = event_handler.comparison
                    if event_handler.resolve_due_date_conflict is not None:
                        build_kwargs["resolve_due_date_conflict"] = (
                            event_handler.resolve_due_date_conflict
                        )
                    if event_handler.state["filter_completed"]:
                        build_kwargs["filter_completed"] = True
                    event_handler.data = build_graph(
                        event_handler.yaml_file,
                        event_handler.dot_file,
                        event_handler.svg_file,
                        event_handler.wrap_width,
                        event_handler.state["order_by_date"],
                        event_handler.data,
                        event_handler.state["target_task"],
                        **build_kwargs,
                    )

                body = _watch_html(
                    "/graph.svg",
                    event_handler.state["order_by_date"],
                    event_handler.state["target_task"],
                    event_handler.state["filter_completed"],
                    event_handler.comparison,
                )
                body_bytes = body.encode("utf-8")
                _send_preview_response(
                    self,
                    body_bytes,
                    "text/html; charset=utf-8",
                )

            def log_message(self, format, *args):
                return

        self.httpd = http.server.ThreadingHTTPServer((self.host, 0), Handler)
        self.httpd.daemon_threads = True
        port = self.httpd.server_address[1]
        self.base_url = f"http://{self.host}:{port}/"
        self.svg_url = f"http://{self.host}:{port}/graph.svg"
        if event_handler.comparison is not None:
            self.svg_url += "?diff-base=" + urllib.parse.quote(
                event_handler.comparison.reference, safe=""
            )
        # Start serving immediately so the first browser navigation does not
        # block waiting for the watcher loop to call handle_request.
        self.server_thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True,
        )
        self.server_thread.start()

    def serve_pending_request(self):
        # The server runs in a background thread; this method remains for
        # compatibility with the watcher loop call site.
        return

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.server_thread is not None:
            self.server_thread.join(timeout=1.0)


@register_command(
    "Watch a flowchart YAML file, rebuild DOT/SVG output, and open the"
    " preview",
    help={
        "yaml": "Path to the flowchart YAML file",
        "wrap_width": "Line wrap width used when generating node labels",
        "d": "Render nodes by date without showing connections",
        "t": "Task name to focus on (show incomplete ancestor tasks only)",
        "p": "Render the full plan with completed tasks filtered out",
        "diff_base": "Compare the live plan against a Git revision",
    },
    filename_extensions={"yaml": (".yaml", ".yml")},
)
def wgrph(yaml, wrap_width=55, d=False, t=None, p=False, diff_base=None):
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

    comparison = (
        PlanComparison(yaml_file, diff_base) if diff_base is not None else None
    )
    dot_file = yaml_file.with_suffix(".dot")
    svg_file = yaml_file.with_suffix(".svg")

    # The browser now drives filtering/date-mode by GET query parameters
    # handled by the local preview server. Keep Python state in sync there.
    initial_state = {
        "order_by_date": False,
        "target_task": None,
        "filter_completed": False,
    }

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
        resolve_due_date_conflict=_resolve_due_date_conflict_with_qt,
        **({"comparison": comparison} if comparison is not None else {}),
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
        _resolve_due_date_conflict_with_qt,
        comparison=comparison,
    )
    preview_server = FlowchartPreviewServer(event_handler)
    preview_server.start()
    event_handler.svg_url = preview_server.svg_url
    preview_url = preview_server.base_url
    if comparison is not None:
        preview_url += "?diff-base=" + urllib.parse.quote(
            comparison.reference, safe=""
        )
    event_handler.preview_url = preview_url

    driver = start_chrome(webdriver, options, preview_url)
    event_handler.driver = driver

    if t is not None and str(t).strip():
        driver.get(
            preview_url
            + ("&" if "?" in preview_url else "?")
            + "t="
            + urllib.parse.quote(str(t).strip())
        )
    elif d:
        driver.get(
            preview_url + ("&" if "?" in preview_url else "?") + "d=1"
        )
    elif p:
        driver.get(
            preview_url + ("&" if "?" in preview_url else "?") + "p=1"
        )

    observer = Observer()
    observer.schedule(event_handler, yaml_file.parent, recursive=False)
    observer.start()
    dead_since = None
    dead_reason = None
    try:
        while True:
            preview_server.serve_pending_request()
            # Exit the watcher when the browser window is really closed, but
            # tolerate short Selenium liveness errors during top-level
            # navigation (for example when opening /?t=... from the links).
            if browser_window_is_alive(event_handler.driver):
                dead_since = None
                dead_reason = None
            else:
                if dead_since is None:
                    dead_since = time.time()
                    dead_reason = (
                        "browser_window_is_alive returned False; likely user "
                        "closed the window or the browser crashed."
                    )
                elif time.time() - dead_since >= 1.0:
                    print(
                        "Stopping flowchart preview because the browser "
                        f"window appears closed. Reason: {dead_reason}",
                        flush=True,
                    )
                    break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print(
            "Stopping flowchart preview due to KeyboardInterrupt.",
            flush=True,
        )
        pass
    finally:
        observer.stop()
        observer.join()
        close_chrome(event_handler.driver)
        preview_server.stop()
