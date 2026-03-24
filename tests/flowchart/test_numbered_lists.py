import pathlib
import re
import yaml

from pydifftools.flowchart.dot_to_yaml import dot_to_yaml
from pydifftools.flowchart.graph import write_dot_from_yaml


def test_numbered_lines(tmp_path):
    source_dot = pathlib.Path(__file__).with_name("magnet_setup.dot")
    tmp_yaml = tmp_path / "out.yaml"
    dot_to_yaml(str(source_dot), tmp_yaml)
    data = yaml.safe_load(tmp_yaml.read_text())
    lines = data["nodes"]["Disconnect"]["text"].splitlines()
    assert lines[3].startswith("1.")
    assert lines[4].startswith("2.")
    assert lines[5].startswith("3.")
    generated_dot = tmp_path / "from_yaml.dot"
    write_dot_from_yaml(tmp_yaml, generated_dot)
    text = generated_dot.read_text()
    m = re.search(r"Disconnect \[label=<(.*?)>\];", text, re.S)
    assert m, "label not found"
    label = m.group(1)
    assert re.search(r'<br align="left"/>\n\s*2\. Add notes', label)
    assert label.strip().endswith('<br align="left"/>' + "\n</font>")
