import xml.etree.ElementTree as ET

from pydifftools.flowchart.watch_graph import build_graph


def test_rendered_svg_node_carries_its_plan_key_for_source_jump(tmp_path):
    yaml_file = tmp_path / "plan.yaml"
    dot_file = tmp_path / "plan.dot"
    svg_file = tmp_path / "plan.svg"
    yaml_file.write_text(
        "nodes:\n  task_key:\n    text: Visible description\n"
    )

    build_graph(yaml_file, dot_file, svg_file, wrap_width=55)

    root = ET.parse(svg_file).getroot()
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[: root.tag.find("}") + 1]
    node = next(
        group
        for group in root.iter(f"{namespace}g")
        if group.attrib.get("class") == "node"
    )
    assert node.attrib["data-source-name"] == "task_key"
