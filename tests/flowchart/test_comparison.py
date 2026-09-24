from copy import deepcopy
import subprocess
from types import SimpleNamespace
import urllib.request
import xml.etree.ElementTree as ET

import pytest
import yaml

from pydifftools.command_line import build_parser
from pydifftools.flowchart.comparison import PlanComparison
from pydifftools.flowchart.graph import (
    endpoint_projects,
    load_graph_yaml,
    save_graph_yaml,
    write_dot_from_yaml,
    yaml_to_dot,
)
from pydifftools.flowchart.watch_graph import (
    build_graph,
    FlowchartPreviewServer,
    GraphEventHandler,
    _watch_html,
    wgrph,
)


@pytest.fixture
def plan(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "plan.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "nodes": {
                    "root": {"text": "Starting task", "children": ["old"]},
                    "old": {
                        "text": (
                            "Prepare the detailed experimental report "
                            "for review"
                        ),
                        "due": "10/02/26",
                        "children": ["end"],
                    },
                    "end": {"text": "Finish", "style": "endpoint"},
                    "gone": {
                        "text": (
                            "* Inspect `old` samples\n* Record <b>results</b>"
                        ),
                        "due": "10/01/26",
                    },
                }
            }
        )
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "baseline",
        ],
        check=True,
    )
    return path


def test_cli_and_git_references(plan):
    parsed = build_parser().parse_args(
        [
            "wgrph",
            str(plan),
            "--diff-base",
            "@{0}",
        ]
    )
    assert parsed.diff_base == "@{0}"
    baseline = PlanComparison(plan, "@")
    for revision in ("HEAD", "@{0}", "HEAD~0", baseline.commit):
        assert PlanComparison(plan, revision).commit == baseline.commit
    assert baseline.commit[:12] in _watch_html(
        "/graph.svg", False, comparison=baseline
    )
    diff_html = _watch_html(
        "/graph.svg", False, comparison=baseline
    )
    assert "src='/graph.svg?diff-base=%40'" in diff_html
    assert "href='/?diff-base=%40&d=1'" in diff_html
    assert "href='/?diff-base=%40&p=1'" in diff_html
    with pytest.raises(ValueError, match="Cannot compare"):
        PlanComparison(plan, "not-a-revision")
    assert PlanComparison(plan.parent / "new.yaml", "HEAD").data == {
        "nodes": {}
    }


def test_startup_errors(plan, tmp_path):
    outside = tmp_path.parent / "outside-plan.yaml"
    with pytest.raises(ValueError, match="Cannot compare"):
        PlanComparison(outside, "HEAD")
    plan.write_text("nodes: [invalid schema]")
    subprocess.run(["git", "-C", str(plan.parent), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(plan.parent),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "invalid",
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="Cannot compare"):
        PlanComparison(plan, "HEAD")


def test_reordering_whitespace_and_exact_rename(plan):
    baseline = PlanComparison(plan, "HEAD")
    current = deepcopy(baseline.data)
    current["nodes"] = dict(reversed(list(current["nodes"].items())))
    current["nodes"]["old"][
        "text"
    ] = "Prepare  the detailed\nexperimental report for review"
    model = baseline.render(current, 55)
    assert set(baseline.node_states.values()) == {"same"}
    assert "#16803c" not in model["nodes"]["old"]["_comparison_label"]
    current["nodes"]["renamed"] = current["nodes"].pop("old")
    assert baseline.correspondence(current)["old"] == "renamed"


def test_edited_rename_needs_neighbors_and_margin(plan):
    baseline = PlanComparison(plan, "HEAD")
    current = deepcopy(baseline.data)
    node = current["nodes"].pop("old")
    node["text"] += "."
    current["nodes"]["renamed"] = node
    assert baseline.correspondence(current)["old"] == "renamed"
    current["nodes"]["another"] = deepcopy(node)
    assert "old" not in baseline.correspondence(current)
    del current["nodes"]["another"]
    node["parents"] = []
    assert "old" not in baseline.correspondence(current)
    node["parents"] = ["root"]
    node["text"] = "An entirely different task"
    assert "old" not in baseline.correspondence(current)


def test_render_rich_changes_and_no_yaml_artifacts(plan):
    baseline = PlanComparison(plan, "HEAD")
    frozen = deepcopy(baseline.data)
    current = deepcopy(baseline.data)
    current["nodes"].pop("gone")
    current["nodes"]["added"] = {"text": "Brand new", "due": "10/03/26"}
    current["nodes"]["root"][
        "text"
    ] = "* Starting `revised` task\n* <b>Keep</b> <obs>observations</obs>"
    current["nodes"]["root"]["children"] = ["added"]
    current["nodes"]["old"]["due"] = "10/04/26"
    current["nodes"]["old"]["style"] = "complete"
    save_graph_yaml(plan, current)
    data = build_graph(
        plan,
        plan.with_suffix(".dot"),
        plan.with_suffix(".svg"),
        55,
        comparison=baseline,
    )
    assert (
        "<b>deleted:</b>"
        in baseline.render(current, 55)["nodes"]["gone"]["_comparison_label"]
    )
    assert (
        "<b>added:</b>"
        in baseline.render(current, 55)["nodes"]["added"]["_comparison_label"]
    )
    saved = yaml.safe_load(plan.read_text())
    assert saved == data
    assert "gone" not in saved["nodes"]
    assert "_comparison" not in plan.read_text()
    assert baseline.data == frozen
    svg = plan.with_suffix(".svg").read_text()
    assert "#c62828" in svg and "#16803c" in svg
    assert "stroke-dasharray" in svg and "line-through" in svg
    assert "Courier" in svg and "observations" in svg
    assert baseline.edge_states["root->old"] == "removed"
    assert baseline.edge_states["root->added"] == "added"
    assert "10/02/26" in svg and "10/04/26" in svg
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_deleted_navigation_filters_and_date_order(plan):
    baseline = PlanComparison(plan, "HEAD")
    current = deepcopy(baseline.data)
    del current["nodes"]["gone"]
    current["nodes"]["old"]["style"] = "complete"
    current["nodes"]["old"]["due"] = "10/05/26"
    model = baseline.render(current, 55, target="gone")
    assert set(model["nodes"]) == {"gone"}
    model = baseline.render(current, 55, completed=True)
    assert "old" in model["nodes"]  # independently visible in history
    assert baseline.edge_states["root->old"] == "same"
    assert model["nodes"]["old"]["due"] == "10/05/26"
    save_graph_yaml(plan, current)
    dot = plan.with_suffix(".dot")
    write_dot_from_yaml(plan, dot, comparison=baseline, order_by_date=True)
    text = dot.read_text()
    assert "gone [label=" in text and "old [label=" in text
    assert text.index("sortv=0") < text.index("sortv=1")
    assert "10/01/26" in text and "10/05/26" in text


def test_rename_box_and_rich_word_diff(plan):
    baseline = PlanComparison(plan, "HEAD")
    current = deepcopy(baseline.data)
    current["nodes"]["renamed"] = current["nodes"].pop("old")
    current["nodes"]["root"]["children"] = ["renamed"]
    current["nodes"]["end"]["parents"] = ["renamed"]
    model = baseline.render(current, 55)
    assert "old" not in model["nodes"]
    assert "root" in endpoint_projects(model)["end"]
    assert "renamed [label=" in yaml_to_dot(model)
    assert "<s>old</s>" in model["nodes"]["renamed"]["_comparison_label"]
    assert baseline.edge_states["root->renamed"] == "same"
    label = baseline.label(
        "* Use `old code` and <b>bold</b>",
        "* Use `new code` and <b>bold</b>",
        55,
    )
    assert 'face="Courier"' in label and "<b>" in label
    assert "<s>old</s>" in label and '#16803c">new' in label
    assert "•" in label


def test_baseline_persists_on_reload_and_navigation(plan, monkeypatch):
    baseline = PlanComparison(plan, "HEAD")
    handler = GraphEventHandler(
        plan,
        plan.with_suffix(".dot"),
        plan.with_suffix(".svg"),
        data=load_graph_yaml(plan),
        comparison=baseline,
        debounce=0,
    )
    monkeypatch.setattr(
        "pydifftools.flowchart.watch_graph._reload_svg", lambda *args: None
    )
    original = plan.read_text()
    plan.write_text(original.replace("Starting task", "New starting task"))
    handler.on_modified(SimpleNamespace(src_path=str(plan)))
    assert handler.comparison is baseline
    assert baseline.data["nodes"]["root"]["text"] == "Starting task"
    server = FlowchartPreviewServer(handler)
    server.start()
    try:
        for query in ("?t=gone", "?d=1&p=1", "?p=1", ""):
            with urllib.request.urlopen(server.base_url + query) as response:
                page = response.read().decode()
            assert baseline.commit[:12] in page
            assert handler.comparison is baseline
    finally:
        server.stop()


@pytest.mark.parametrize("revision", ["missing-ref", "HEAD~999"])
def test_watcher_reports_invalid_baseline_before_launch(plan, revision):
    with pytest.raises(ValueError, match="Cannot compare"):
        wgrph(str(plan), diff_base=revision)
