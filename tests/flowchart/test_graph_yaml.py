import threading
import time

import pytest

from pydifftools.flowchart.graph import EmptyGraphYamlError, load_graph_yaml


def test_load_graph_yaml_raises_on_empty_after_retries(tmp_path):
    yaml_path = tmp_path / "graph.yaml"
    yaml_path.write_text("")

    with pytest.raises(EmptyGraphYamlError):
        load_graph_yaml(str(yaml_path), old_data={"nodes": {}})


def test_load_graph_yaml_retries_empty_file(tmp_path):
    yaml_path = tmp_path / "graph.yaml"
    yaml_path.write_text("")

    def delayed_write():
        time.sleep(0.02)
        yaml_path.write_text("nodes:\n  task_a:\n    text: Task A\n")

    writer = threading.Thread(target=delayed_write)
    writer.start()

    data = load_graph_yaml(str(yaml_path), old_data={"nodes": {}})
    writer.join()

    assert "task_a" in data.get("nodes", {})
