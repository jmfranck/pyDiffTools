from pydifftools.flowchart.graph import write_dot_from_yaml
from pydifftools.flowchart.graph import yaml_to_dot


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


def test_yaml_to_dot_clusters_endpoint_ancestors_in_non_date_mode():
    data = {
        "styles": {
            "endpoints": {"attrs": {"node": {"color": "red"}}},
            "endpoint": {"attrs": {"node": {"color": "red"}}},
            "completedendpoint": {
                "attrs": {"node": {"color": "green", "penwidth": 2}}
            },
        },
        "nodes": {
            "top_parent": {"children": ["top_ep"], "parents": []},
            "top_ep": {
                "children": ["root"],
                "parents": ["top_parent"],
                "style": "endpoint",
                "text": "Top endpoint",
            },
            "root": {"children": ["mid"], "parents": ["top_ep"]},
            "mid": {"children": ["ep"], "parents": ["root"]},
            "ep": {
                "children": ["child"],
                "parents": ["mid"],
                "style": "endpoints",
                "text": "Quantify noise levels from Genesys power supply",
            },
            "done_ep": {
                "children": ["child"],
                "parents": [],
                "style": "completedendpoint",
                "text": "Completed endpoint",
            },
            "child": {"children": [], "parents": ["ep", "done_ep"]},
        },
    }

    dot_text = yaml_to_dot(data, wrap_width=20, order_by_date=False)

    assert "subgraph cluster_ep" in dot_text
    assert "subgraph cluster_done_ep" in dot_text
    assert "label=<Quantify noise levels from Genesys power" in dot_text
    assert "ep [label=" not in dot_text
    assert "done_ep [label=" not in dot_text
    assert "subgraph endpoints" not in dot_text
    assert " top_ep;" not in dot_text
    assert " root;" in dot_text
    assert " mid;" in dot_text
    assert "color=green;" in dot_text
    assert "penwidth=2;" in dot_text
    assert "cluster_anchor_ep -> child [ltail=cluster_ep];" in dot_text
    assert (
        "cluster_anchor_done_ep -> child [ltail=cluster_done_ep];"
        in dot_text
    )


def test_yaml_to_dot_keeps_endpoint_style_in_date_mode():
    data = {
        "styles": {
            "endpoints": {
                "attrs": {"node": {"color": "red", "fontcolor": "red"}}
            }
        },
        "nodes": {
            "ep": {
                "children": [],
                "parents": [],
                "style": "endpoints",
                "due": "2025-01-01",
                "text": "Endpoint still red in date mode",
            }
        },
    }

    dot_text = yaml_to_dot(data, wrap_width=30, order_by_date=True)

    assert "subgraph endpoints" in dot_text
    assert "node [color=red, fontcolor=red];" in dot_text
    assert "ep [label=" in dot_text
