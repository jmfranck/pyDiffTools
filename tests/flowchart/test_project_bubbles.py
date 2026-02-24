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
        if child.tag in (f"{namespace}polygon", f"{namespace}rect", f"{namespace}ellipse")
        and "stroke" in child.attrib
    ]


def test_build_graph_colors_node_borders_and_removes_bubbles(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text(
        """
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
""".strip()
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False)

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    # Bezier project bubbles were removed.
    assert all(
        group.attrib.get("id") != "project-bubbles"
        for group in root.iter(f"{namespace}g")
    )

    end1_stroke = _node_border_shapes(nodes["end1"], namespace)[0].attrib["stroke"]
    end2_stroke = _node_border_shapes(nodes["end2"], namespace)[0].attrib["stroke"]

    root_shapes = _node_border_shapes(nodes["root"], namespace)
    root_strokes = [shape.attrib["stroke"] for shape in root_shapes]
    assert end1_stroke in root_strokes
    assert end2_stroke in root_strokes

    # The extra project border is a transparent outline inserted at SVG stage.
    transparent_outlines = [
        shape
        for shape in root_shapes
        if shape.tag == f"{namespace}rect" and shape.attrib.get("fill") == "none"
    ]
    assert transparent_outlines


def test_project_for_single_endpoint_colors_ancestors(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text(
        """
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
""".strip()
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False)

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    endpoint_color = _node_border_shapes(nodes["child_endpoint"], namespace)[0].attrib[
        "stroke"
    ]
    for node_name in ("root", "middle"):
        border_shapes = _node_border_shapes(nodes[node_name], namespace)
        assert border_shapes[0].attrib["stroke"] == endpoint_color


def test_edge_color_comes_from_child_project(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text(
        """
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
""".strip()
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False)

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
            node_colors[title] = _node_border_shapes(group, namespace)[0].attrib["stroke"]
        if group.attrib["class"] == "edge" and title == "left_endpoint->mid":
            for child in group:
                if child.tag == f"{namespace}path" and "stroke" in child.attrib:
                    edge_colors[title] = child.attrib["stroke"]
                    break

    assert (
        edge_colors["left_endpoint->mid"] == node_colors["right_endpoint"]
    )
    assert edge_colors["left_endpoint->mid"] != node_colors["left_endpoint"]


def test_nonterminal_styled_endpoint_drives_project_coloring(tmp_path):
    yaml_file = tmp_path / "graph.yaml"
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    yaml_file.write_text(
        """
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
""".strip()
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False)

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = _svg_namespace(root)
    nodes = _node_groups_by_title(root, namespace)

    hub_color = _node_border_shapes(nodes["hub"], namespace)[0].attrib["stroke"]
    root_color = _node_border_shapes(nodes["root"], namespace)[0].attrib["stroke"]
    leaf_color = _node_border_shapes(nodes["leaf"], namespace)[0].attrib["stroke"]

    assert hub_color == root_color
    assert leaf_color != hub_color
