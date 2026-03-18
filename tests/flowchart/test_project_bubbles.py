import xml.etree.ElementTree as ET

from pydifftools.flowchart.watch_graph import build_graph


def _svg_namespace(root):
    if root.tag.startswith("{"):
        return root.tag[: root.tag.find("}") + 1]
    return ""


def _node_groups_by_title(root, namespace):
    title_to_group = {}
    for group in root.iter(f"{namespace}g"):
        if group.attrib.get("class") != "node":
            continue
        for child in group:
            if child.tag == f"{namespace}title" and child.text is not None:
                title_to_group[child.text.strip()] = group
                break
    return title_to_group


def _node_border_shapes(group, namespace):
    return [
        child
        for child in group
        if child.tag
        in (f"{namespace}polygon", f"{namespace}rect", f"{namespace}ellipse")
        and "stroke" in child.attrib
    ]


def _bounds_from_points(points_text):
    coords = []
    for pair in points_text.strip().split():
        if "," not in pair:
            continue
        x_str, y_str = pair.split(",", 1)
        coords.append((float(x_str), float(y_str)))
    if not coords:
        return None
    return (
        min(x for x, _ in coords),
        max(x for x, _ in coords),
        min(y for _, y in coords),
        max(y for _, y in coords),
    )


def _union_bounds(existing, new_bounds):
    if new_bounds is None:
        return existing
    if existing is None:
        return new_bounds
    return (
        min(existing[0], new_bounds[0]),
        max(existing[1], new_bounds[1]),
        min(existing[2], new_bounds[2]),
        max(existing[3], new_bounds[3]),
    )


def _rect_bounds(element):
    x = float(element.attrib["x"])
    y = float(element.attrib["y"])
    width = float(element.attrib["width"])
    height = float(element.attrib["height"])
    return (x, x + width, y, y + height)


def _ellipse_bounds(element):
    cx = float(element.attrib["cx"])
    cy = float(element.attrib["cy"])
    rx = float(element.attrib["rx"])
    ry = float(element.attrib["ry"])
    return (cx - rx, cx + rx, cy - ry, cy + ry)


def test_build_graph_colors_node_borders_and_removes_bubbles(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  root:
    text: Root
    children: [mid, end2]
  mid:
    text: Mid
    children: [end1]
  end1:
    text: End 1
    style: endpoint
  end2:
    text: End 2
    style: endpoint
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    # Bezier project bubbles were removed.
    assert all(
        group.attrib.get("id") != "project-bubbles"
        for group in root.iter(f"{namespace}g")
    )

    end1_stroke = _node_border_shapes(nodes["end1"], namespace)[0].attrib[
        "stroke"
    ]
    end2_stroke = _node_border_shapes(nodes["end2"], namespace)[0].attrib[
        "stroke"
    ]

    root_shapes = _node_border_shapes(nodes["root"], namespace)
    root_strokes = [shape.attrib["stroke"] for shape in root_shapes]
    assert end1_stroke in root_strokes
    assert end2_stroke in root_strokes

    # The extra project border is a transparent outline inserted at SVG stage.
    transparent_outlines = [
        shape
        for shape in root_shapes
        if shape.tag == f"{namespace}rect"
        and shape.attrib.get("fill") == "none"
    ]
    assert transparent_outlines


def test_viewbox_contains_postprocessed_geometry(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  bottom_left:
    text: Bottom Left
    children: [middle, endpoint_b]
  middle:
    text: Middle
    children: [endpoint_a]
  endpoint_a:
    text: Endpoint A
    style: endpoint
  endpoint_b:
    text: Endpoint B
    style: endpoint
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    viewbox = [float(x) for x in root.attrib["viewBox"].split()]
    view_x, view_y, view_w, view_h = viewbox
    graph_group = root.find(f"{namespace}g[@class='graph']")
    assert graph_group is not None

    background = None
    for child in graph_group:
        if (
            child.tag == f"{namespace}polygon"
            and child.attrib.get("stroke") == "transparent"
            and "points" in child.attrib
        ):
            background = _bounds_from_points(child.attrib["points"])
            break
    assert background is not None

    scale_x = view_w / (background[1] - background[0])
    scale_y = view_h / (background[3] - background[2])
    tol = 1e-3
    content_bounds = None
    for element in graph_group.iter():
        if element.tag == f"{namespace}polygon" and "points" in element.attrib:
            content_bounds = _union_bounds(
                content_bounds, _bounds_from_points(element.attrib["points"])
            )
        elif element.tag == f"{namespace}rect":
            content_bounds = _union_bounds(
                content_bounds, _rect_bounds(element)
            )
        elif element.tag == f"{namespace}ellipse":
            content_bounds = _union_bounds(
                content_bounds, _ellipse_bounds(element)
            )
    assert content_bounds is not None

    mapped_min_x = view_x + (content_bounds[0] - background[0]) * scale_x
    mapped_max_x = view_x + (content_bounds[1] - background[0]) * scale_x
    mapped_min_y = view_y + (content_bounds[2] - background[2]) * scale_y
    mapped_max_y = view_y + (content_bounds[3] - background[2]) * scale_y
    assert mapped_min_x >= view_x - tol
    assert mapped_max_x <= (view_x + view_w) + tol
    assert mapped_min_y >= view_y - tol
    assert mapped_max_y <= (view_y + view_h) + tol


def test_project_for_single_endpoint_colors_ancestors(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  root:
    text: Root
    children: [middle]
  middle:
    text: Middle
    children: [child_endpoint]
  child_endpoint:
    text: Child Endpoint
    style: endpoint
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    endpoint_color = _node_border_shapes(nodes["child_endpoint"], namespace)[
        0
    ].attrib["stroke"]
    for node_name in ("root", "middle"):
        border_shapes = _node_border_shapes(nodes[node_name], namespace)
        assert border_shapes[0].attrib["stroke"] == endpoint_color


def test_edge_color_comes_from_child_project(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  left_endpoint:
    text: Left Endpoint
    style: endpoint
    children: [mid]
  mid:
    text: Mid
    children: [right_endpoint]
  right_endpoint:
    text: Right Endpoint
    style: endpoint
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)

    node_colors = {}
    edge_colors = {}
    for group in root.iter(f"{namespace}g"):
        if "class" not in group.attrib:
            continue
        title = None
        for child in group:
            if child.tag == f"{namespace}title" and child.text is not None:
                title = child.text.strip()
                break
        if title is None:
            continue
        if group.attrib["class"] == "node" and title in (
            "left_endpoint",
            "right_endpoint",
        ):
            node_colors[title] = _node_border_shapes(group, namespace)[
                0
            ].attrib["stroke"]
        if group.attrib["class"] == "edge" and title == "left_endpoint->mid":
            for child in group:
                if (
                    child.tag == f"{namespace}path"
                    and "stroke" in child.attrib
                ):
                    edge_colors[title] = child.attrib["stroke"]
                    break

    assert edge_colors["left_endpoint->mid"] == node_colors["right_endpoint"]
    assert edge_colors["left_endpoint->mid"] != node_colors["left_endpoint"]


def test_nonterminal_styled_endpoint_drives_project_coloring(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  root:
    text: Root
    children: [hub]
  hub:
    text: Hub Endpoint
    style: endpoint
    children: [leaf]
  leaf:
    text: Plain Leaf
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    hub_color = _node_border_shapes(nodes["hub"], namespace)[0].attrib[
        "stroke"
    ]
    root_color = _node_border_shapes(nodes["root"], namespace)[0].attrib[
        "stroke"
    ]
    leaf_color = _node_border_shapes(nodes["leaf"], namespace)[0].attrib[
        "stroke"
    ]

    assert hub_color == root_color
    assert leaf_color != hub_color


def test_build_graph_adds_task_links_to_all_nodes(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text("""
nodes:
  first_task:
    text: First Task
    children: [second_task]
  second_task:
    text: Second Task
""".strip())

    build_graph(
        yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False
    )

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    links = list(root.iter(f"{namespace}a"))

    hrefs = []
    for link in links:
        for attr_name in link.attrib:
            if attr_name.endswith("}href"):
                hrefs.append(link.attrib[attr_name])

    assert "/?t=first_task" in hrefs
    assert "/?t=second_task" in hrefs
