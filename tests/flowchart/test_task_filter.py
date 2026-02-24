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
    assert "parent1 -> target [weight=1];" in dot_text


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
                "children": ["child", "done_ep"],
                "parents": ["mid"],
                "style": "endpoints",
                "text": "Quantify noise levels from Genesys power supply",
                "due": "2099-01-02",
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
    assert "pad=0.20" in dot_text
    assert "label=<Quantify noise levels from Genesys power" in dot_text
    assert 'font color="orange"' in dot_text
    assert "ep [label=" not in dot_text
    assert "done_ep [label=" not in dot_text
    assert "subgraph endpoints" not in dot_text
    assert " top_ep;" not in dot_text
    assert " root;" in dot_text
    assert " mid;" in dot_text
    assert "color=green;" in dot_text
    assert "penwidth=2;" in dot_text
    assert "compound=true" in dot_text
    assert "cluster_anchor_ep -> cluster_anchor_done_ep" in dot_text
    assert "ltail=cluster_ep" in dot_text
    assert "lhead=cluster_done_ep" in dot_text
    assert "cluster_anchor_ep -> child" in dot_text
    assert "cluster_anchor_done_ep -> child" in dot_text
    assert "mid -> cluster_anchor_ep [weight=1];" in dot_text
    assert "weight=100" in dot_text
    assert "color=red" in dot_text
    assert "cluster_proxy_ep_node -> child" not in dot_text
    assert "cluster_proxy_done_ep_node -> child" not in dot_text



def test_yaml_to_dot_cluster_label_keeps_due_without_text():
    data = {
        "styles": {
            "endpoint": {"attrs": {"node": {"color": "red"}}},
        },
        "nodes": {
            "ep": {
                "children": ["task"],
                "parents": [],
                "style": "endpoint",
                "due": "2099-01-01",
            },
            "task": {"children": [], "parents": ["ep"]},
        },
    }

    dot_text = yaml_to_dot(data, wrap_width=20, order_by_date=False)

    assert "subgraph cluster_ep" in dot_text
    assert 'font color="orange"' in dot_text



def test_yaml_to_dot_cluster_edge_uses_edge_attrs():
    data = {
        "styles": {
            "endpoint": {
                "attrs": {
                    "node": {"color": "darkred", "penwidth": 2},
                    "edge": {"color": "purple", "penwidth": 5, "style": "dashed"},
                }
            },
        },
        "nodes": {
            "ep": {
                "children": ["child"],
                "parents": [],
                "style": "endpoint",
                "text": "Endpoint",
            },
            "child": {"children": [], "parents": ["ep"]},
        },
    }

    dot_text = yaml_to_dot(data, order_by_date=False)

    assert (
        "cluster_anchor_ep -> child "
        "[weight=100,color=purple,penwidth=5,style=dashed];"
        in dot_text
    )


def test_yaml_to_dot_no_clustering_restores_plain_edges():
    data = {
        "styles": {
            "endpoint": {"attrs": {"node": {"color": "red"}}},
        },
        "nodes": {
            "ep": {
                "children": ["child"],
                "parents": [],
                "style": "endpoint",
                "text": "Endpoint",
            },
            "child": {"children": [], "parents": ["ep"]},
        },
    }

    dot_text = yaml_to_dot(data, order_by_date=False, cluster_endpoints=False)

    assert "subgraph cluster_ep" not in dot_text
    assert "ep [label=" in dot_text
    assert "ep -> child [weight=1];" in dot_text

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


def test_yaml_to_dot_endpoint_cluster_edges_render_with_dot(tmp_path):
    data = {
        "styles": {
            "endpoint": {"attrs": {"node": {"color": "red"}}},
        },
        "nodes": {
            "parent_ep": {
                "children": ["child_ep"],
                "parents": [],
                "style": "endpoint",
                "text": "Parent",
            },
            "child_ep": {
                "children": ["leaf"],
                "parents": ["parent_ep"],
                "style": "endpoint",
                "text": "Child",
            },
            "leaf": {"children": [], "parents": ["child_ep"]},
        },
    }

    dot_path = tmp_path / "graph.dot"
    svg_path = tmp_path / "graph.svg"
    dot_path.write_text(yaml_to_dot(data, order_by_date=False), encoding="utf-8")

    import subprocess

    subprocess.run(["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)], check=True)
    assert svg_path.exists()


def test_yaml_to_dot_default_style_sets_global_node_attrs():
    data = {
        "styles": {
            "default": {
                "attrs": {
                    "node": {"fillcolor": "mintcream", "style": "filled"}
                }
            }
        },
        "nodes": {
            "a": {"children": [], "parents": []},
        },
    }

    dot_text = yaml_to_dot(data, order_by_date=False)

    assert "node [fillcolor=mintcream, style=filled];" in dot_text


def test_yaml_to_dot_endpoint_cluster_complex_graphviz_warnings(tmp_path):
    # Regression for large endpoint-to-endpoint routing that previously
    # triggered Graphviz compound-edge warnings and SIGABRT.
    data = {
        "styles": {
            "endpoint": {"attrs": {"node": {"color": "red"}}},
        },
        "nodes": {
            "generalBackground": {
                "children": ["operatorOverloadDraft", "RSIstyleDraft"],
                "parents": [],
                "style": "endpoint",
                "text": "general",
            },
            "improvedRelaxation": {
                "children": ["RSIstyleDraft"],
                "parents": [],
                "style": "endpoint",
                "text": "improved",
            },
            "routineODNPGoal": {
                "children": ["RSIstyleDraft", "ODNPgoal"],
                "parents": [],
                "style": "endpoint",
                "text": "routine",
            },
            "ODNPgoal": {
                "children": ["WaterInterlock"],
                "parents": ["routineODNPGoal"],
                "style": "endpoint",
                "text": "goal",
            },
            "operatorOverloadDraft": {
                "children": ["WaterInterlock"],
                "parents": ["generalBackground"],
                "style": "endpoint",
                "text": "op",
            },
            "RSIstyleDraft": {
                "children": ["WaterInterlock"],
                "parents": ["generalBackground", "improvedRelaxation", "routineODNPGoal"],
                "style": "endpoint",
                "text": "rsi",
            },
            "WaterInterlock": {
                "children": [],
                "parents": ["ODNPgoal", "operatorOverloadDraft", "RSIstyleDraft"],
            },
        },
    }

    dot_path = tmp_path / "complex.dot"
    svg_path = tmp_path / "complex.svg"
    dot_path.write_text(yaml_to_dot(data, order_by_date=False), encoding="utf-8")

    import subprocess

    result = subprocess.run(
        ["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "tail not inside tail cluster" not in result.stderr
    assert "head not inside head cluster" not in result.stderr
    assert "spline size > 1 not supported" not in result.stderr
    assert svg_path.exists()
