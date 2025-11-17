import pathlib
import datetime

from pydifftools.flowchart import graph
from pydifftools.flowchart.graph import write_dot_from_yaml
import pytest


class FixedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2024, 5, 10)


@pytest.fixture(autouse=True)
def stub_today(monkeypatch):
    monkeypatch.setattr(graph, "date", FixedDate)


def test_yaml_to_dot(tmp_path):
    sample_yaml = pathlib.Path(__file__).with_name("sample.yaml")
    expected_dot = pathlib.Path(__file__).with_name("sample.dot")
    generated_dot = tmp_path / "generated.dot"
    write_dot_from_yaml(sample_yaml, generated_dot, update_yaml=False)
    assert (
        generated_dot.read_text().rstrip() == expected_dot.read_text().rstrip()
    )
