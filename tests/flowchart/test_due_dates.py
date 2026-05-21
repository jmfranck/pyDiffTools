import datetime
import pytest

from pydifftools.flowchart import graph
from pydifftools.flowchart.graph import yaml_to_dot


class FixedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2024, 5, 10)


@pytest.fixture(autouse=True)
def stub_today(monkeypatch):
    monkeypatch.setattr(graph, "date", FixedDate)


def test_due_dates_render():
    data = {
        "nodes": {
            "Task": {
                "text": "Work item",
                "due": "2025-10-02",
                "children": [],
                "parents": [],
            },
            "Alt": {
                "due": "March 4 2026",
                "children": [],
                "parents": [],
            },
        }
    }
    dot = yaml_to_dot(data)
    # The primary text should keep its formatting while the due date adds a new
    # line.
    assert (
        'Work item\n<br align="left"/>\n<font color="orange">10/2/25</font>'
        in dot
    )
    # Nodes that only declare a due date still render the value in orange.
    assert (
        '<font point-size="9">__WGRPH_TASK_LINK__:Alt</font>'
        '<br align="left"/><font color="orange">3/4/26</font>'
    ) in dot


def test_completed_due_is_green():
    data = {
        "nodes": {
            "Task": {
                "text": "Work item",
                "due": "2025-10-02",
                "children": [],
                "parents": [],
                "style": "completed",
            },
        }
    }
    dot = yaml_to_dot(data)
    assert 'font color="green">10/2/25</font>' in dot


def test_completed_today_shows_actual_date():
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-10",
                "children": [],
                "parents": [],
                "style": "completed",
            },
        }
    }
    dot = yaml_to_dot(data)
    assert '<font color="green">5/10/24</font>' in dot
    assert "TODAY" not in dot


def test_completed_overdue_shows_actual_date():
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-08",
                "children": [],
                "parents": [],
                "style": "completed",
            },
        }
    }
    dot = yaml_to_dot(data)
    assert '<font color="green">5/8/24</font>' in dot
    assert "OVERDUE" not in dot


def test_completedendpoint_overdue_shows_actual_date():
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-08",
                "children": [],
                "parents": [],
                "style": "completedendpoint",
            },
        }
    }
    dot = yaml_to_dot(data)
    assert '<font color="green">5/8/24</font>' in dot
    assert "OVERDUE" not in dot


def test_original_due_display():
    data = {
        "nodes": {
            "Task": {
                "text": "Work item",
                "orig_due": "2025-09-15",
                "due": "2025-10-02",
                "children": [],
                "parents": [],
            },
        }
    }

    dot = yaml_to_dot(data)

    assert '<font color="orange"><i>9/15/25</i>→10/2/25</font>' in dot


def test_due_today():
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-10",
                "children": [],
                "parents": [],
            },
        }
    }

    dot = yaml_to_dot(data)

    assert (
        '<font color="red"><font point-size="12"><b>TODAY</b></font></font>'
        in dot
    )


def test_due_overdue():
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-08",
                "children": [],
                "parents": [],
            },
        }
    }

    dot = yaml_to_dot(data)

    assert (
        '<font color="red"><font point-size="12"><b>2 DAYS'
        " OVERDUE</b></font></font>" in dot
    )


def test_due_within_week_is_orange():
    # Due dates within the next week should be colored red.
    data = {
        "nodes": {
            "Task": {
                "due": "2024-05-17",
                "children": [],
                "parents": [],
            },
        }
    }

    dot = yaml_to_dot(data)

    assert '<font color="red">5/17/24</font>' in dot


def test_watch_graph_moves_child_due_after_latest_parent(tmp_path, capsys):
    # Ensure watch_graph rendering moves a child due date after its latest
    # parent instead of refusing to render.
    yaml_path = tmp_path / "graph.yaml"
    dot_path = tmp_path / "graph.dot"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  EarlierParent:",
                "    due: 2025-10-10",
                "    children: [Child]",
                "  LatestParent:",
                "    due: 2025-10-12",
                "    children: [Child]",
                "  Child:",
                "    due: 2025-10-10",
            ]
        )
        + "\n"
    )

    data = graph.write_dot_from_yaml(
        str(yaml_path),
        str(dot_path),
        validate_due_dates=True,
    )

    assert data["nodes"]["Child"]["due"] == "10/12/25"
    assert data["nodes"]["Child"]["orig_due"] == "10/10/25"
    assert (
        "**WARNING!** moving due date of Child from 10/10/25 "
        "to 10/12/25 because child of LatestParent"
    ) in capsys.readouterr().out


def test_watch_graph_allows_child_due_on_same_date_as_parent(
    tmp_path, capsys
):
    yaml_path = tmp_path / "graph.yaml"
    dot_path = tmp_path / "graph.dot"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  Parent:",
                "    due: 2025-10-10",
                "    children: [Child]",
                "  Child:",
                "    due: 2025-10-10",
            ]
        )
        + "\n"
    )

    data = graph.write_dot_from_yaml(
        str(yaml_path),
        str(dot_path),
        validate_due_dates=True,
    )

    assert data["nodes"]["Child"]["due"] == "10/10/25"
    assert "orig_due" not in data["nodes"]["Child"]
    assert "**WARNING!** moving due date" not in capsys.readouterr().out


def test_due_move_preserves_existing_original_due(tmp_path, capsys):
    yaml_path = tmp_path / "graph.yaml"
    dot_path = tmp_path / "graph.dot"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  Parent:",
                "    due: 2025-10-11",
                "    children: [Child]",
                "  Child:",
                "    orig_due: 2025-10-01",
                "    due: 2025-10-10",
            ]
        )
        + "\n"
    )

    data = graph.write_dot_from_yaml(
        str(yaml_path),
        str(dot_path),
        validate_due_dates=True,
    )

    assert data["nodes"]["Child"]["due"] == "10/11/25"
    assert data["nodes"]["Child"]["orig_due"] == "10/01/25"
    assert (
        "**WARNING!** moving due date of Child from 10/10/25 "
        "to 10/11/25 because child of Parent"
    ) in capsys.readouterr().out


def test_due_conflict_can_break_dependency(tmp_path, capsys):
    yaml_path = tmp_path / "graph.yaml"
    dot_path = tmp_path / "graph.dot"
    yaml_path.write_text(
        "\n".join(
            [
                "nodes:",
                "  Parent:",
                "    due: 2025-10-10",
                "    children: [Child]",
                "  Child:",
                "    due: 2025-10-09",
            ]
        )
        + "\n"
    )

    data = graph.write_dot_from_yaml(
        str(yaml_path),
        str(dot_path),
        validate_due_dates=True,
        resolve_due_date_conflict=lambda *_: "break",
    )

    assert data["nodes"]["Child"]["due"] == "10/09/25"
    assert "orig_due" not in data["nodes"]["Child"]
    assert data["nodes"]["Child"]["parents"] == []
    assert data["nodes"]["Parent"]["children"] == []
    assert (
        "**WARNING!** breaking dependency between Parent and Child"
    ) in capsys.readouterr().out


def test_due_node_warns_when_parent_has_no_due_date():
    data = {
        "nodes": {
            "Parent": {
                "children": ["Child"],
                "parents": [],
            },
            "Child": {
                "due": "2025-10-10",
                "children": [],
                "parents": ["Parent"],
            },
        }
    }

    dot = yaml_to_dot(data)

    assert (
        '<font color="red"><font point-size="12"><b>Warning! Depends '
        "on parents without due dates!</b></font></font>"
    ) in dot
