import xml.etree.ElementTree as ET

from pydifftools.flowchart.watch_graph import build_graph


def test_build_graph_adds_project_bubbles(tmp_path):
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
  end2:
    text: End 2
""".strip()
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55, order_by_date=False)

    tree = ET.parse(svg_file)
    root = tree.getroot()
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[: root.tag.find("}") + 1]

    title_to_group = {}
    bubble_group = None
    for group in root.iter(f"{namespace}g"):
        if "id" in group.attrib and group.attrib["id"] == "project-bubbles":
            bubble_group = group
        for child in group:
            if child.tag == f"{namespace}title" and child.text is not None:
                title_to_group[child.text.strip()] = group

    assert bubble_group is not None
    bubbles = [child for child in bubble_group if child.tag == f"{namespace}path"]
    assert len(bubbles) == 2

    endpoint_colors = {}
    for endpoint in ["end1", "end2"]:
        for child in title_to_group[endpoint]:
            if child.tag == f"{namespace}polygon" and "stroke" in child.attrib:
                endpoint_colors[endpoint] = child.attrib["stroke"]
                break
        assert endpoint in endpoint_colors

    bubble_strokes = set()
    for bubble in bubbles:
        bubble_strokes.add(bubble.attrib["stroke"])
        assert bubble.attrib["fill"] == "#00000011"

    assert endpoint_colors["end1"] in bubble_strokes
    assert endpoint_colors["end2"] in bubble_strokes
