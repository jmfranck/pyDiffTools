from pydifftools.flowchart.graph import write_dot_from_yaml


def test_write_dot_filters_to_incomplete_ancestors(tmp_path):
    # Create a simple dependency chain with a completed ancestor to exclude.
    yaml_path = tmp_path / "graph.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  root:",
                "    children: [grandparent]",
                "  grandparent:",
                "    children: [parent1]",
                "  completed_parent:",
                "    style: completed",
                "    children: [parent1]",
                "  parent1:",
                "    children: [target]",
                "  target:",
                "    children: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dot_path = tmp_path / "graph.dot"

    write_dot_from_yaml(yaml_path, dot_path, filter_task="target")

    dot_text = dot_path.read_text(encoding="utf-8")
    assert "target" in dot_text
    assert "completed_parent" not in dot_text
    assert "parent1" in dot_text
    assert "grandparent" in dot_text
    assert "root" in dot_text
    assert "parent1 -> target" in dot_text


def test_write_dot_filters_out_completedendpoint_ancestors(tmp_path):
    yaml_path = tmp_path / "graph.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  root:",
                "    children: [completed_ep]",
                "  completed_ep:",
                "    style: completedendpoint",
                "    children: [target]",
                "  target:",
                "    children: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dot_path = tmp_path / "graph.dot"

    write_dot_from_yaml(yaml_path, dot_path, filter_task="target")

    dot_text = dot_path.read_text(encoding="utf-8")
    assert "target" in dot_text
    assert "completed_ep" not in dot_text
    assert "root" in dot_text
