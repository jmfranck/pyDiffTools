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
    # The primary text should keep its formatting while the due date adds a new line.
    assert (
        'Work item\n<br align="left"/>\n<font color="red">10/2/25</font>'
        in dot
    )
    # Nodes that only declare a due date still render the value in red.
    assert 'Alt [label=<<font color="red">3/4/26</font>' in dot


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

    assert '<font color="red"><i>9/15/25</i>→10/2/25</font>' in dot


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
        " OVERDUE</b></font></font>"
        in dot
    )


def test_due_within_week_is_orange():
    # Due dates within the next week should be colored orange.
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

    assert '<font color="orange">5/17/24</font>' in dot


def test_watch_graph_refuses_child_due_before_parent(tmp_path):
    # Ensure watch_graph rendering refuses a child due date earlier than any parent.
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

    with pytest.raises(ValueError, match="Refusing to render watch_graph"):
        graph.write_dot_from_yaml(
            str(yaml_path),
            str(dot_path),
            update_yaml=False,
            validate_due_dates=True,
        )
